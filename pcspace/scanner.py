"""Directory-first metadata scanner: no hard stop, live aggregates, resumable queue."""
from __future__ import annotations
import os
import stat
import shutil
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from .policy import Policy,PolicyError,guard_chain,REPARSE,CLOUD,folder_hint,candidate_bytes


def disks(policy):
    out=[];seen=set()
    for root in policy.roots:
        volume=root.anchor if os.name=='nt' else str(root)
        if volume in seen:continue
        seen.add(volume)
        try:
            s=shutil.disk_usage(volume)
            out.append(dict(root=volume,total=s.total,free=s.free,used=s.used,free_percent=round(100*s.free/s.total,2),error=None))
        except OSError as e:out.append(dict(root=volume,error=type(e).__name__))
    return out

class Scanner:
    def __init__(self,db,policy):
        self.db=db;self.policy=policy;self.lock=threading.Lock();self.cancel_event=threading.Event()
        self.thread=None;self.active_id=None

    def start(self,root):
        p=self.policy.allowed(root)
        if not p.is_dir():raise PolicyError('폴더를 선택하세요.')
        if why:=self.policy.skip_directory(p):raise PolicyError(why)
        with self.lock:
            self._idle()
            sid=uuid.uuid4().hex
            with self.db.connect() as c:
                c.execute("INSERT INTO scans(id,root,started,status,policy_hash,engine) VALUES(?,?,?,'running',?,'tree2')",(sid,str(p),time.time(),self.policy.digest))
                c.execute('INSERT INTO tree(scan_id,path,parent) VALUES(?,?,?)',(sid,str(p),str(p.parent)))
                c.execute('INSERT INTO scan_queue VALUES(?,?)',(sid,str(p)))
            self._launch(sid)
        return {'id':sid}

    def _idle(self):
        if self.thread and self.thread.is_alive():raise PolicyError('현재 분석을 일시정지한 뒤 다른 분석을 시작하세요.')

    def _launch(self,sid):
        self.cancel_event.clear();self.active_id=sid
        self.thread=threading.Thread(target=self._scan,args=(sid,),daemon=True);self.thread.start()

    def resume(self,sid):
        with self.lock:
            self._idle();s=self.db.one('SELECT * FROM scans WHERE id=?',(sid,))
            if not s or s['engine']!='tree2' or s['status'] not in {'paused','failed'}:raise PolicyError('이어서 분석 가능한 작업이 아닙니다. 이전 버전 스캔은 새로 시작하세요.')
            if s['policy_hash']!=self.policy.digest:raise PolicyError('분석 범위 정책이 바뀌었습니다. 새 분석을 시작하세요.')
            self.db.execute("UPDATE scans SET status='running',ended=NULL,note='' WHERE id=?",(sid,));self._launch(sid)
        return {'id':sid}

    def pause(self,sid):
        if sid!=self.active_id or not self.thread or not self.thread.is_alive():raise PolicyError('진행 중인 분석이 아닙니다.')
        self.cancel_event.set();return {'pause_requested':True}

    def _scan(self,sid):
        s=self.db.one('SELECT * FROM scans WHERE id=?',(sid,));root=s['root']
        nodes={r['path']:r for r in self.db.rows('SELECT * FROM tree WHERE scan_id=?',(sid,))}
        pending=deque(r['path'] for r in self.db.rows('SELECT path FROM scan_queue WHERE scan_id=? ORDER BY rowid',(sid,)))
        dirty=set();added=set();finished=set();issue_rows=[];last=time.monotonic();current=root
        skipped=s['skipped'];errors=s['errors'];seen_issues={(r['path'],r['reason']) for r in self.db.rows('SELECT path,reason FROM issues WHERE scan_id=?',(sid,))}
        state='complete';note='폴더 분석 완료 · 논리 크기 기준 · 파일 내용/해시/할당 공간은 읽지 않음'
        def issue(path,reason,error=False):
            nonlocal skipped,errors
            key=(path,reason)
            if key in seen_issues:return
            seen_issues.add(key)
            if error:errors+=1
            else:skipped+=1
            if len(seen_issues)<=1000:issue_rows.append((sid,path,reason))
        def register(path,parent):
            if path in nodes:return
            nodes[path]=dict(scan_id=sid,path=path,parent=parent,own_bytes=0,own_files=0,own_candidates=0,logical_bytes=0,files=0,candidate_bytes=0,done=0)
            dirty.add(path);added.add(path);pending.append(path)
        def publish(path,b,n,k,done):
            r=nodes[path];delta=(b-r['own_bytes'],n-r['own_files'],k-r['own_candidates'])
            r.update(own_bytes=b,own_files=n,own_candidates=k,done=done)
            cur=path
            while cur in nodes:
                t=nodes[cur];t['logical_bytes']+=delta[0];t['files']+=delta[1];t['candidate_bytes']+=delta[2];dirty.add(cur)
                if cur==root:break
                cur=t['parent']
        def flush():
            nonlocal last
            with self.db.connect() as c:
                c.executemany('''INSERT INTO tree VALUES(:scan_id,:path,:parent,:own_bytes,:own_files,:own_candidates,:logical_bytes,:files,:candidate_bytes,:done)
                ON CONFLICT(scan_id,path) DO UPDATE SET own_bytes=excluded.own_bytes,own_files=excluded.own_files,
                own_candidates=excluded.own_candidates,logical_bytes=excluded.logical_bytes,files=excluded.files,candidate_bytes=excluded.candidate_bytes,done=excluded.done''',[nodes[p] for p in dirty])
                c.executemany('INSERT OR IGNORE INTO scan_queue VALUES(?,?)',[(sid,p) for p in added])
                c.executemany('DELETE FROM scan_queue WHERE scan_id=? AND path=?',[(sid,p) for p in finished])
                c.executemany('INSERT INTO issues(scan_id,path,reason) VALUES(?,?,?)',issue_rows)
                r=nodes[root]
                c.execute('UPDATE scans SET files=?,logical_bytes=?,unknown_alloc=?,skipped=?,errors=?,current_path=? WHERE id=?',(r['files'],r['logical_bytes'],r['files'],skipped,errors,current,sid))
            dirty.clear();added.clear();finished.clear();issue_rows.clear();last=time.monotonic()
        try:
            while pending:
                if self.cancel_event.is_set():state='paused';break
                current=pending.popleft();b=n=k=0
                p=Path(current);generated=folder_hint(p)[0]=='generated';now=time.time()
                try:
                    guard_chain(p)
                    if why:=self.policy.skip_directory(p):
                        issue(current,why);publish(current,0,0,0,1);finished.add(current);continue
                    with os.scandir(current) as entries:
                        for ent in entries:
                            if self.cancel_event.is_set():state='paused';break
                            try:
                                st=ent.stat(follow_symlinks=False);attrs=getattr(st,'st_file_attributes',0)
                                if stat.S_ISLNK(st.st_mode) or attrs&(REPARSE|CLOUD):issue(ent.path,'링크/클라우드 항목 제외');continue
                                if stat.S_ISDIR(st.st_mode):
                                    if why:=self.policy.skip_directory(Path(ent.path)):issue(ent.path,why)
                                    else:register(ent.path,current)
                                elif stat.S_ISREG(st.st_mode):
                                    n+=1;b+=st.st_size;k+=candidate_bytes(ent.name,st.st_size,st.st_mtime,generated,now)
                            except OSError as e:issue(ent.path,type(e).__name__,True)
                            if (n%1024==0 and time.monotonic()-last>=0.8) or len(dirty)>5000:
                                publish(current,b,n,k,0);flush()
                except (OSError,PolicyError) as e:issue(current,str(e)[:180],True)
                publish(current,b,n,k,int(state!='paused'))
                if state=='paused':break
                finished.add(current)
                if time.monotonic()-last>=0.8:flush()
            flush()
            if state=='complete' and (skipped or errors):state='complete_with_exclusions'
            if state=='paused':note='일시정지 · 완료 폴더는 유지합니다. 이어서 분석 시 작업 중이던 폴더만 다시 읽습니다.'
        except Exception as e:
            state='failed';note=f'{type(e).__name__}: {str(e)[:180]} · 체크포인트에서 재개 가능'
        finally:self.db.execute('UPDATE scans SET status=?,ended=?,note=?,current_path=? WHERE id=?',(state,time.time(),note,current if state=='paused' else '',sid))
