"""One confirmation; direct recycle or manifest-based permanent deletion."""
from __future__ import annotations
import ctypes
import json
import os
import stat
import threading
import time
import uuid
from pathlib import Path
from .db import Database, encode
from .policy import Policy, PolicyError, canonical, inside, snapshot, unchanged, guard_chain
from .scanner import disks


def guarded_unlink(p: Path, expected: dict):
    guard_chain(p)
    unchanged(p, expected)
    if os.name != "nt":
        p.unlink()
        return
    # Hold a delete-capable handle denying concurrent write/delete opens.
    # Delete the verified handle, not a subsequently resolved arbitrary pathname.
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    k.CreateFileW.restype = ctypes.c_void_p
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    k.SetFileInformationByHandle.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    k.SetFileInformationByHandle.restype = ctypes.c_int
    k.GetFinalPathNameByHandleW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32]
    k.GetFinalPathNameByHandleW.restype = ctypes.c_uint32
    handle = k.CreateFileW(str(p), 0x00010000 | 0x0080, 0x1, None, 3, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        buf = ctypes.create_unicode_buffer(32768)
        n = k.GetFinalPathNameByHandleW(handle, buf, len(buf), 0)
        if not n or n >= len(buf):
            raise PolicyError("삭제 핸들의 실제 경로를 확인하지 못했습니다.")
        actual_path = buf.value.removeprefix("\\\\?\\")
        if os.path.normcase(actual_path) != os.path.normcase(str(p)):
            raise PolicyError("삭제 핸들 경로가 격리 기록과 다릅니다.")
        unchanged(p, expected)
        flag = ctypes.c_int(1)
        if not k.SetFileInformationByHandle(handle, 4, ctypes.byref(flag), ctypes.sizeof(flag)):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        k.CloseHandle(handle)


def recycle(path:Path):
    """Native Windows recycle. Refuse non-recycle callbacks; never fall back to unlink."""
    if os.name!='nt':
        raise PolicyError('이 설치의 휴지통 동작은 Windows에서만 지원합니다.')
    import sys
    deps=Path(__file__).resolve().parent.parent/'.deps'
    if deps.exists() and str(deps) not in sys.path:sys.path.insert(0,str(deps))
    import pythoncom
    from win32com.shell import shell,shellcon
    from win32com.server.exception import COMException
    from send2trash.win.IFileOperationProgressSink import FileOperationProgressSink
    class Sink(FileOperationProgressSink):
        def PreDeleteItem(self,flags,item):
            if not flags & shellcon.TSF_DELETE_RECYCLE_IF_POSSIBLE:
                raise COMException('Recycle unavailable; permanent fallback refused.',scode=-2147467259)
            return 0
        def PostDeleteItem(self,flags,item,hr_delete,newly_created):
            if hr_delete<0:raise COMException('Recycle failed.',scode=hr_delete)
            return super().PostDeleteItem(flags,item,hr_delete,newly_created)
    pythoncom.CoInitialize()
    try:
        sink=Sink();wrapped=pythoncom.WrapObject(sink,shell.IID_IFileOperationProgressSink)
        op=pythoncom.CoCreateInstance(shell.CLSID_FileOperation,None,pythoncom.CLSCTX_ALL,shell.IID_IFileOperation)
        op.SetOperationFlags(0x4|0x10|0x400|0x100000|0x80000|0x20000000|0x2000)
        op.DeleteItem(shell.SHCreateItemFromParsingName(str(path),None,shell.IID_IShellItem),wrapped)
        hr=op.PerformOperations()
        if hr or op.GetAnyOperationsAborted() or path.exists():raise OSError('Windows 휴지통 이동이 완료되지 않았습니다.')
    finally:pythoncom.CoUninitialize()

class Actions:
    def __init__(self,db,policy):
        self.db=db;self.policy=policy;self.lock=threading.RLock();self.thread=None;self.recycler=recycle

    def prepare(self,paths:list[str],action='recycle',scan_id=None):
        if action not in {'recycle','delete'}:raise PolicyError('지원하지 않는 작업입니다.')
        if scan_id and not self.db.one('SELECT id FROM scans WHERE id=?',(scan_id,)):
            raise PolicyError('선택한 분석 기록을 찾을 수 없습니다.')
        targets=list(dict.fromkeys(str(self.policy.allowed(p)) for p in paths))
        if not 1<=len(targets)<=200:raise PolicyError('항목을 1~200개 선택하세요. 폴더는 그 안의 항목을 함께 처리합니다.')
        # Selecting a parent and child must not execute twice.
        targets=[p for p in targets if not any(p!=q and inside(Path(p),Path(q)) for q in targets)]
        pid=uuid.uuid4().hex;items=[]
        with self.lock:
            if self.thread and self.thread.is_alive():raise PolicyError('현재 삭제 작업이 끝난 뒤 다시 시도하세요.')
            with self.db.connect() as c:
                for raw in targets:
                    p=self.policy.mutable(raw);snap=snapshot(p);directory=stat.S_ISDIR(snap['mode'])
                    count=size=0
                    if action=='delete':
                        # Freeze exact paths before the one confirmation. New files cannot be swept in.
                        stack=[p]
                        while stack:
                            node=stack.pop();ns=snapshot(node);isdir=stat.S_ISDIR(ns['mode'])
                            self.policy.mutable(node,ns)
                            c.execute('INSERT INTO operation_entries VALUES(?,?,?,?)',(pid,str(node),int(isdir),encode(ns)))
                            if isdir:
                                with os.scandir(node) as it:stack.extend(Path(e.path) for e in it)
                            else:count+=1;size+=ns['size']
                    else:
                        if directory:
                            stack=[p]
                            while stack:
                                folder=stack.pop();self.policy.mutable(folder)
                                with os.scandir(folder) as entries:
                                    for entry in entries:
                                        es=entry.stat(follow_symlinks=False)
                                        if stat.S_ISLNK(es.st_mode) or getattr(es,'st_file_attributes',0)&(0x400|0x1000|0x40000|0x400000):
                                            raise PolicyError('선택 폴더 안에 링크·클라우드 항목이 있습니다. 해당 항목을 제외하고 선택하세요.')
                                        if stat.S_ISDIR(es.st_mode):stack.append(Path(entry.path))
                                        elif stat.S_ISREG(es.st_mode):count+=1;size+=es.st_size
                        else:size=snap['size'];count=1
                    items.append(dict(source=raw,snapshot=snap,directory=directory,size=size,files=count,scan_id=scan_id))
                c.execute("INSERT INTO plans(id,created,action,status,policy_hash,items) VALUES(?,?,?,'planned',?,?)",(pid,time.time(),action,self.policy.digest,encode(items)))
        return self.get(pid)

    def get(self,pid):
        p=self.db.one('SELECT * FROM plans WHERE id=?',(pid,))
        if not p:raise PolicyError('작업을 찾을 수 없습니다.')
        for k in ('items','results','before_space','after_space'):p[k]=json.loads(p[k])
        return p

    def apply(self,pid,approved:bool):
        if approved is not True:raise PolicyError('삭제 확인이 필요합니다.')
        with self.lock:
            if self.thread and self.thread.is_alive():raise PolicyError('삭제 작업이 진행 중입니다.')
            p=self.get(pid)
            if p['action'] not in {'recycle','delete'} or p['status']!='planned':raise PolicyError('이미 처리되었거나 현재 버전의 작업이 아닙니다.')
            if time.time()-p['created']>900 or p['policy_hash']!=self.policy.digest:raise PolicyError('오래되었거나 정책이 바뀐 선택입니다. 다시 선택하세요.')
            self.db.execute("UPDATE plans SET status='applying',before_space=? WHERE id=?",(encode(disks(self.policy)),pid))
            self.thread=threading.Thread(target=self._run,args=(p,),daemon=True);self.thread.start()
        return {'id':pid,'status':'applying'}

    def _run(self,plan):
        results=[];pid=plan['id']
        try:
            for item in plan['items']:
                r={'source':item['source'],'status':'failed'}
                try:
                    p=self.policy.mutable(item['source'],item['snapshot'])
                    if plan['action']=='recycle':self.recycler(p)
                    else:self._delete_tree(pid,p)
                    r['status']='done'
                    try:self._reconcile_tree(item)
                    except Exception as exc:
                        r['warning']='File operation completed; refresh scan totals: '+type(exc).__name__
                        if item.get('scan_id'):self.db.execute('UPDATE scans SET stale=1 WHERE id=?',(item['scan_id'],))
                except Exception as e:r['error']=f'{type(e).__name__}: {str(e)[:220]}'
                results.append(r);self.db.execute('UPDATE plans SET results=? WHERE id=?',(encode(results),pid))
            state='complete' if all(r['status']=='done' for r in results) else 'partial_failure'
        except Exception as e:
            state='partial_failure';results.append(dict(status='failed',error=str(e)[:220]))
        finally:
            # Operations without scan context cannot reconcile a specific snapshot.
            if any(not x.get('scan_id') for x in plan['items']):self.db.execute('UPDATE scans SET stale=1')
            self.db.execute('UPDATE plans SET status=?,results=?,after_space=? WHERE id=?',(state,encode(results),encode(disks(self.policy)),pid))

    def _reconcile_tree(self,item):
        sid=item.get('scan_id')
        if not sid:return
        scan=self.db.one('SELECT * FROM scans WHERE id=?',(sid,))
        if not scan or scan.get('engine')!='tree2':return
        if scan.get('status')=='running':
            self.db.execute('UPDATE scans SET stale=1 WHERE id=?',(sid,))
            return
        p=Path(item['source'])
        if not item.get('directory'):
            self.db.execute('UPDATE scans SET stale=1 WHERE id=?',(sid,))
            return
        row=self.db.one('SELECT * FROM tree WHERE scan_id=? AND path=?',(sid,str(p)))
        if not row:
            self.db.execute('UPDATE scans SET stale=1 WHERE id=?',(sid,))
            return
        delta=(row['logical_bytes'],row['files'],row['candidate_bytes']);root=canonical(scan['root'])
        with self.db.connect() as c:
            cur=row['parent']
            while inside(Path(cur),root):
                parent=c.execute('SELECT parent FROM tree WHERE scan_id=? AND path=?',(sid,cur)).fetchone()
                c.execute("UPDATE tree SET logical_bytes=MAX(0,logical_bytes-?),files=MAX(0,files-?),candidate_bytes=MAX(0,candidate_bytes-?) WHERE scan_id=? AND path=?",(*delta,sid,cur))
                if Path(cur)==root or not parent:break
                cur=parent['parent']
            # Indexed, separator-bounded range: includes descendants, never similarly named siblings.
            low=str(p)+os.sep;high=str(p)+chr(ord(os.sep)+1)
            for table in ('scan_queue','tree'):
                c.execute(f'DELETE FROM {table} WHERE scan_id=? AND path>=? AND path<?',(sid,low,high))
                c.execute(f'DELETE FROM {table} WHERE scan_id=? AND path=?',(sid,str(p)))
            rootrow=c.execute('SELECT logical_bytes,files FROM tree WHERE scan_id=? AND path=?',(sid,str(root))).fetchone()
            if rootrow:c.execute('UPDATE scans SET logical_bytes=?,files=? WHERE id=?',(rootrow['logical_bytes'],rootrow['files'],sid))

    def _delete_tree(self,pid,root):
        entries=self.db.rows('SELECT * FROM operation_entries WHERE plan_id=?',(pid,))
        entries=[e for e in entries if inside(Path(e['path']),root)]
        expected={e['path']:e for e in entries};stack=[root];seen=set()
        # Preflight the whole selected tree before any irreversible change.
        while stack:
            p=stack.pop();e=expected.get(str(p))
            if e is None:raise PolicyError('확인 이후 파일이 추가되었습니다. 다시 선택하세요.')
            self.policy.mutable(p,json.loads(e['snapshot']));seen.add(str(p))
            if e['is_dir']:
                with os.scandir(p) as it:stack.extend(Path(v.path) for v in it)
        if seen!=set(expected):raise PolicyError('확인 이후 파일이 사라졌습니다. 다시 선택하세요.')
        for e in sorted(entries,key=lambda r:len(Path(r['path']).parts),reverse=True):
            p=Path(e['path']);snap=json.loads(e['snapshot'])
            if e['is_dir']:
                guard_chain(p);actual=snapshot(p)
                if any(actual[k]!=snap[k] for k in ('dev','ino','mode')):raise PolicyError('폴더가 교체되었습니다.')
                p.rmdir()  # Fails, rather than deleting a new/unplanned child.
            else:guarded_unlink(p,snap)
