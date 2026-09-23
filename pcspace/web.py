"""Local automatic sessions; owner-only Tailscale identity; directory-first API."""
from __future__ import annotations
import os
import secrets
import time
import threading
import heapq
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI,Request,Response,HTTPException,Query
from fastapi.responses import FileResponse,JSONResponse
from pydantic import BaseModel,Field,ConfigDict
from . import __version__
from .db import Database
from .policy import Policy,PolicyError,canonical,inside,snapshot,folder_hint,candidate_bytes,REPARSE,CLOUD
from .scanner import Scanner,disks
from .actions import Actions
import stat
STATIC=Path(__file__).parent/'static'

def default_state():return Path(os.environ.get('LOCALAPPDATA',Path.home()/'.local/share'))/'PCSpace'
class Model(BaseModel):model_config=ConfigDict(extra='forbid')
class PathInput(Model):path:str=Field(min_length=1,max_length=2048)
class ScanInput(Model):root:str=Field(min_length=1,max_length=2048)
class PlanInput(Model):
    paths:list[str]=Field(min_length=1,max_length=200)
    action:str='recycle'
    scan_id:str|None=None
class ApplyInput(Model):approved:bool=False

def create_app(state=None,roots=None):
    state=state or default_state();policy=Policy(state,roots);db=Database(state/'pcspace.sqlite3')
    scanner=Scanner(db,policy);actions=Actions(db,policy)
    sessions={};lock=threading.Lock();last_sample=[0.0]
    app=FastAPI(title='PCSpace',version=__version__,docs_url=None,redoc_url=None,openapi_url=None)
    app.state.policy=policy;app.state.db=db;app.state.scanner=scanner;app.state.actions=actions

    def identity(request,origin):
        # Backend must stay loopback-only and uvicorn proxy_headers=False.
        peer=request.client.host if request.client else ''
        if peer not in {'127.0.0.1','::1'}:return None
        parts=urlsplit(origin)
        if parts.scheme=='http' and parts.hostname in {'127.0.0.1','localhost'}:
            # Forwarded proxy traffic must not masquerade as a direct-local request.
            if request.headers.get('x-forwarded-for') or request.headers.get('tailscale-user-login'):return None
            return 'local'
        login=request.headers.get('tailscale-user-login','').casefold()
        allowed={x.casefold() for x in policy.data.get('tailnet_users',[])}
        if parts.scheme=='https' and parts.hostname.endswith('.ts.net') and login and login in allowed:return 'tailnet:'+login
        return None

    @app.middleware('http')
    async def security(request,call_next):
        host=request.headers.get('host','').casefold()
        origins=[o for o in policy.data['origins'] if urlsplit(o).netloc.casefold()==host]
        def deny(msg,code=403):return JSONResponse({'detail':msg},status_code=code)
        if not origins:return deny('허용되지 않은 Host')
        origin=origins[0];user=identity(request,origin);path=request.url.path
        if request.headers.get('sec-fetch-site')=='cross-site':return deny('교차 사이트 접근 차단')
        if request.method not in {'GET','HEAD','POST'}:return deny('허용되지 않은 요청',405)
        if request.method=='POST':
            if request.headers.get('origin')!=origin:return deny('다른 출처에서 실행할 수 없습니다.')
            if request.headers.get('content-type','').split(';')[0]!='application/json':return deny('JSON 요청 필요',415)
            try:n=int(request.headers.get('content-length','-1'))
            except ValueError:return deny('잘못된 요청 크기',400)
            if not 0<=n<=65536:return deny('요청 크기 초과',413)
        request.state.identity=user;request.state.origin=origin
        if path.startswith('/api/'):
            if not user:return deny('이 PC 또는 허용된 본인 Tailscale 계정으로 접속하세요.',401)
            if not (path=='/api/session' and request.method=='POST'):
                sid=request.cookies.get('pcspace_session','');session=sessions.get(sid)
                if not session or session['expires']<time.time() or session['origin']!=origin or session['user']!=user:return deny('세션 갱신 필요',401)
                if request.method=='POST' and not secrets.compare_digest(request.headers.get('x-pcspace-csrf',''),session['csrf']):return deny('요청 검증 실패')
                request.state.session=session
        response=await call_next(request)
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY',
            'Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"})
        return response

    @app.exception_handler(PolicyError)
    async def policy_error(request,exc):return JSONResponse({'detail':str(exc)},status_code=400)
    @app.exception_handler(OSError)
    async def io_error(request,exc):return JSONResponse({'detail':f'{type(exc).__name__}: 파일 사용 중·권한·경로 상태를 확인하세요.'},status_code=400)
    @app.get('/health')
    def health():return {'app':'PCSpace','version':__version__}
    @app.get('/')
    def index():return FileResponse(STATIC/'index.html',media_type='text/html')
    @app.get('/static/{name}')
    def asset(name:str):
        types={'app.js':'text/javascript','app.css':'text/css','icon.svg':'image/svg+xml'}
        if name not in types:raise HTTPException(404)
        return FileResponse(STATIC/name,media_type=types[name])
    @app.post('/api/session')
    def session(request:Request,response:Response):
        with lock:
            now=time.time()
            for old in [k for k,v in sessions.items() if v['expires']<now]:sessions.pop(old,None)
            old=request.cookies.get('pcspace_session','');existing=sessions.get(old)
            if existing and existing['origin']==request.state.origin and existing['user']==request.state.identity:
                sid=old;csrf=existing['csrf']
            else:
                if len(sessions)>200:raise HTTPException(429,'세션 수 제한')
                sid=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
            sessions[sid]={'csrf':csrf,'origin':request.state.origin,'user':request.state.identity,'expires':now+8*3600}
        response.set_cookie('pcspace_session',sid,httponly=True,secure=request.state.origin.startswith('https:'),samesite='strict',max_age=8*3600)
        return {'csrf':csrf,'version':__version__,'connection':'PC 직접 접속' if request.state.identity=='local' else 'Tailscale 본인 인증'}

    @app.get('/api/dashboard')
    def dashboard():
        ds=disks(policy);now=time.time()
        if now-last_sample[0]>60:
            last_sample[0]=now
            with db.connect() as c:c.executemany('INSERT INTO disk_history(sampled,root,total,free) VALUES(?,?,?,?)',[(now,d['root'],d['total'],d['free']) for d in ds if not d['error']])
        return {'disks':ds,'roots':[str(r) for r in policy.roots],'scans':db.rows('SELECT * FROM scans ORDER BY started DESC LIMIT 30'),
                'active_id':scanner.active_id if scanner.thread and scanner.thread.is_alive() else None}
    @app.post('/api/scans')
    def scan(body:ScanInput):return scanner.start(body.root)
    @app.post('/api/scans/{sid}/pause')
    def pause(sid:str):return scanner.pause(sid)
    @app.post('/api/scans/{sid}/resume')
    def resume(sid:str):return scanner.resume(sid)
    @app.get('/api/scans/{sid}')
    def detail(sid:str):
        r=db.one('SELECT * FROM scans WHERE id=?',(sid,))
        if not r:raise HTTPException(404)
        return {'scan':r,'issues':db.rows('SELECT path,reason FROM issues WHERE scan_id=? LIMIT 100',(sid,))}

    @app.get('/api/tree')
    def tree(scan_id:str,path:str=Query(min_length=1,max_length=2048),q:str=Query(default='',max_length=200),limit:int=Query(default=200,ge=1,le=500)):
        scan=db.one('SELECT * FROM scans WHERE id=?',(scan_id,))
        if not scan:raise HTTPException(404)
        rootp=canonical(scan['root']);requested=canonical(path)
        if not inside(requested,rootp):raise PolicyError('선택한 분석 범위 밖입니다.')
        p=requested
        while p!=rootp and not p.exists():p=p.parent
        if not p.exists():raise PolicyError('분석 루트가 더 이상 존재하지 않습니다. 새 분석을 시작하세요.')
        p=policy.allowed(p)
        if why:=policy.skip_directory(p):raise PolicyError(why)
        total=db.one('SELECT * FROM tree WHERE scan_id=? AND path=?',(scan_id,str(p)))
        children=db.rows('SELECT * FROM tree WHERE scan_id=? AND parent=? AND path!=? ORDER BY logical_bytes DESC',(scan_id,str(p),str(p)))
        folders=[];missing=0
        for r in children:
            rp=Path(r['path'])
            if not rp.is_dir():
                missing+=1
                continue
            kind,hint=folder_hint(rp)
            if q.casefold() not in rp.name.casefold():continue
            folders.append(dict(path=str(rp),name=rp.name,directory=True,size=r['logical_bytes'],files=r['files'],candidates=r['candidate_bytes'],
                                measured=bool(r['done'] or r['files']),kind=kind,hint=hint,blocked=policy.deletion_reason(rp,True)))
        # Direct files are read only when opening/refreshing this level; no million-row sort.
        direct=[];file_count=0;now=time.time();folder_kind,folder_note=folder_hint(p);generated=folder_kind=='generated';excluded=0
        with os.scandir(p) as it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):continue
                    s=e.stat(follow_symlinks=False)
                    if stat.S_ISLNK(s.st_mode) or getattr(s,'st_file_attributes',0)&(REPARSE|CLOUD):excluded+=1;continue
                    if not stat.S_ISREG(s.st_mode) or q.casefold() not in e.name.casefold():continue
                    file_count+=1;rp=Path(e.path);candidate=candidate_bytes(e.name,s.st_size,s.st_mtime,generated,now)
                    wsl_disk=folder_kind=='wsl' and e.name.casefold()=='ext4.vhdx'
                    r=dict(path=e.path,name=e.name,directory=False,size=s.st_size,files=1,candidates=0 if wsl_disk else candidate,measured=True,
                           kind='wsl' if wsl_disk else ('candidate' if candidate else 'normal'),
                           hint='WSL2 Ubuntu Linux 파일시스템 가상디스크 · 일반 찌꺼기가 아님 · 직접 삭제하면 배포판 데이터가 손실됩니다' if wsl_disk else ('캐시·임시·오래된 설치/압축 형식' if candidate else '일반 파일'),
                           blocked=policy.deletion_reason(rp),mtime=s.st_mtime)
                    pair=(s.st_size,e.path,r)
                    if len(direct)<limit:heapq.heappush(direct,pair)
                    elif pair[:2]>direct[0][:2]:heapq.heapreplace(direct,pair)
                except OSError:excluded+=1
        files=[r for _,_,r in sorted(direct,reverse=True)]
        if missing:db.execute('UPDATE scans SET stale=1 WHERE id=?',(scan_id,))
        return {'scan':scan,'path':str(p),'redirected_from':str(requested) if requested!=p else None,
                'parent':str(p.parent) if str(p)!=scan['root'] else None,'total':total,
                'folders':folders,'files':files,'omitted_files':max(0,file_count-len(files)),
                'excluded':excluded,'missing_folders':missing}

    @app.post('/api/operations/preview')
    def preview(body:PlanInput):return actions.prepare(body.paths,body.action,body.scan_id)
    @app.post('/api/operations/{pid}/apply')
    def apply(pid:str,body:ApplyInput):return actions.apply(pid,body.approved)
    @app.get('/api/operations/{pid}')
    def get_operation(pid:str):return actions.get(pid)
    @app.get('/api/operations')
    def operations():return db.rows('SELECT id,created,action,status,items,results,before_space,after_space FROM plans ORDER BY created DESC LIMIT 60')
    @app.post('/api/open-folder')
    def open_folder(body:PathInput):
        p=policy.allowed(body.path)
        if not p.is_dir():p=p.parent
        if os.name!='nt':raise PolicyError('Windows PC에서만 지원합니다.')
        os.startfile(str(p));return {'opened':str(p)}
    @app.post('/api/recycle-bin')
    def recycle_bin():
        if os.name!='nt':raise PolicyError('Windows에서만 지원합니다.')
        os.startfile('shell:RecycleBinFolder');return {'opened':True}
    @app.get('/api/policy')
    def get_policy():return {'protected_paths':policy.data['protected_paths'],'cloud_paths':policy.data['cloud_paths'],'connection':'PC 자동 접속 / 허용된 Tailscale 본인 인증','auto_delete':False,'version':__version__}
    @app.post('/api/protect')
    def protect(body:PathInput):policy.protect(body.path);return {'ok':True}
    return app
