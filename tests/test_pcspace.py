import os
import time
import stat
import threading
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from pcspace.web import create_app
from pcspace.policy import PolicyError,inside,canonical,snapshot,folder_hint
import pcspace.scanner as scanmod

ORIGIN='http://127.0.0.1:8768'
@pytest.fixture
def system(tmp_path):
    root=tmp_path/'files';root.mkdir();app=create_app(tmp_path/'state',[str(root)])
    yield app,root
    s=app.state.scanner;s.cancel_event.set()
    if s.thread:s.thread.join(10)
    if app.state.actions.thread:app.state.actions.thread.join(10)

def client(app,origin=ORIGIN,headers=None):
    c=TestClient(app,base_url=origin,client=('127.0.0.1',51322),headers=headers or {})
    r=c.post('/api/session',json={},headers={'Origin':origin});assert r.status_code==200,r.text
    c.headers.update({'Origin':origin,'X-PCSpace-CSRF':r.json()['csrf']});return c

def scan(app,root):
    sid=app.state.scanner.start(str(root))['id'];app.state.scanner.thread.join(20)
    s=app.state.db.one('SELECT * FROM scans WHERE id=?',(sid,));assert s['status'] in {'complete','complete_with_exclusions'},s
    return sid,s

def run(app,plan):
    app.state.actions.apply(plan['id'],True);app.state.actions.thread.join(20)
    return app.state.actions.get(plan['id'])

def test_passwordless_local_no_key_file(system):
    app,_=system;c=client(app)
    assert c.get('/api/dashboard').status_code==200
    assert not (app.state.policy.state/'access-key.txt').exists()

def test_no_session_no_data(system):
    c=TestClient(system[0],base_url=ORIGIN,client=('127.0.0.1',1))
    assert c.get('/api/dashboard').status_code==401

def test_remote_without_owner_rejected(system):
    app,_=system;origin='https://pc.example.ts.net:8769';app.state.policy.data['origins'].append(origin)
    c=TestClient(app,base_url=origin,client=('127.0.0.1',1))
    assert c.post('/api/session',json={},headers={'Origin':origin}).status_code==401

def test_tailnet_owner_passwordless_and_rechecked(system):
    app,_=system;origin='https://pc.example.ts.net:8769';app.state.policy.data['origins'].append(origin);app.state.policy.data['tailnet_users']=['owner@example.com']
    c=client(app,origin,{'Tailscale-User-Login':'owner@example.com'})
    assert c.get('/api/dashboard').status_code==200
    c.headers['Tailscale-User-Login']='not-owner@example.com'
    assert c.get('/api/dashboard').status_code==401

def test_local_forwarded_identity_rejected(system):
    c=TestClient(system[0],base_url=ORIGIN,client=('127.0.0.1',1))
    assert c.post('/api/session',json={},headers={'Origin':ORIGIN,'X-Forwarded-For':'100.1.2.3'}).status_code==401

def test_direct_nonloopback_rejected(system):
    c=TestClient(system[0],base_url=ORIGIN,client=('192.168.1.8',1))
    assert c.post('/api/session',json={},headers={'Origin':ORIGIN}).status_code==401

@pytest.mark.parametrize('header,value',[('Host','evil.example'),('Origin','http://evil.example'),('Sec-Fetch-Site','cross-site'),('X-PCSpace-CSRF','invalid')])
def test_request_boundaries(system,header,value):
    c=client(system[0]);assert c.post('/api/scans',json={'root':str(system[1])},headers={header:value}).status_code==403

def test_scan_does_not_open_user_contents_or_snapshot_files(system,monkeypatch):
    app,root=system;(root/'sample.txt').write_text('hello')
    old=Path.open
    def no_open(p,*a,**k):
        if inside(p,root):raise AssertionError('file content opened')
        return old(p,*a,**k)
    monkeypatch.setattr(Path,'open',no_open)
    sid,s=scan(app,root);assert s['files']==1 and s['logical_bytes']==5

def test_directory_aggregates(system):
    app,root=system;p=root/'Workspace'/'node_modules';p.mkdir(parents=True)
    (p/'a.txt').write_bytes(b'a'*10);(p/'b.txt').write_bytes(b'b'*20);(root/'keep.txt').write_bytes(b'k')
    sid,s=scan(app,root);rows=app.state.db.rows('SELECT * FROM tree WHERE scan_id=?',(sid,));index={r['path']:r for r in rows}
    assert s['files']==3 and s['logical_bytes']==31
    assert index[str(root)]['candidate_bytes']==30
    assert index[str(root/'Workspace')]['logical_bytes']==30
    assert index[str(p)]['own_files']==2

def test_tree_directory_and_direct_files(system):
    app,root=system;(root/'sub').mkdir();(root/'sub'/'a.txt').write_text('child');(root/'top.txt').write_text('top')
    sid,s=scan(app,root);r=client(app).get('/api/tree',params={'scan_id':sid,'path':str(root)}).json()
    assert len(r['folders'])==1 and len(r['files'])==1
    assert r['folders'][0]['size']==5 and r['files'][0]['size']==3

def test_nested_root_tree_cannot_escape(system):
    app,root=system;p=root/'sub';p.mkdir();sid,_=scan(app,p)
    assert client(app).get('/api/tree',params={'scan_id':sid,'path':str(root)}).status_code==400

def test_more_than_500000_files_without_storage_bloat(system,monkeypatch):
    app,root=system
    st=SimpleNamespace(st_mode=stat.S_IFREG|0o644,st_size=2,st_mtime=time.time(),st_file_attributes=0)
    ent=SimpleNamespace(name='sample.txt',path=str(root/'sample.txt'),stat=lambda **kw:st)
    class Entries:
        def __enter__(self):return (ent for _ in range(500010))
        def __exit__(self,*a):pass
    original=os.scandir
    monkeypatch.setattr(scanmod.os,'scandir',lambda p:Entries() if str(p)==str(root) else original(p))
    sid,s=scan(app,root);assert s['files']==500010 and s['logical_bytes']==1000020
    assert len(app.state.db.rows('SELECT * FROM tree WHERE scan_id=?',(sid,)))==1
    assert app.state.db.path.stat().st_size<2*1024**2

def test_pause_resume_without_double_count(system,monkeypatch):
    app,root=system;p=root/'sub';p.mkdir()
    for i in range(100):(p/f'{i}.txt').write_bytes(b'x'*3)
    start=threading.Event();old=scanmod.candidate_bytes
    def slow(*a):start.set();time.sleep(.003);return old(*a)
    monkeypatch.setattr(scanmod,'candidate_bytes',slow)
    sid=app.state.scanner.start(str(root))['id'];assert start.wait(5);time.sleep(.02)
    app.state.scanner.pause(sid);app.state.scanner.thread.join(5)
    assert app.state.db.one('SELECT status FROM scans WHERE id=?',(sid,))['status']=='paused'
    monkeypatch.setattr(scanmod,'candidate_bytes',old)
    app.state.scanner.resume(sid);app.state.scanner.thread.join(10)
    s=app.state.db.one('SELECT * FROM scans WHERE id=?',(sid,))
    assert s['status']=='complete' and s['files']==100 and s['logical_bytes']==300
    assert not app.state.db.rows('SELECT * FROM scan_queue WHERE scan_id=?',(sid,))

def test_pause_survives_app_restart(system,monkeypatch):
    app,root=system;p=root/'x';p.mkdir();(p/'a.txt').write_text('abc')
    sid,_=scan(app,root)
    app.state.db.execute("UPDATE scans SET status='running' WHERE id=?",(sid,))
    app.state.db.execute('INSERT INTO scan_queue VALUES(?,?)',(sid,str(p)))
    reopened=create_app(app.state.policy.state)
    assert reopened.state.db.one('SELECT status FROM scans WHERE id=?',(sid,))['status']=='paused'
    reopened.state.scanner.resume(sid);reopened.state.scanner.thread.join(10)
    s=reopened.state.db.one('SELECT * FROM scans WHERE id=?',(sid,));assert s['files']==1 and s['logical_bytes']==3

def test_projects_backups_originals_are_not_locked(system):
    app,root=system
    for name in ['Workspace','.git','backup','node_modules']:
        p=root/name;p.mkdir();(p/'original.dng').write_text('test only')
        assert app.state.policy.mutable(p)==p
        assert app.state.actions.prepare([str(p)],'delete')['items'][0]['files']==1

def test_single_confirmation_permanent_file(system):
    app,root=system;p=root/'disposable.txt';p.write_text('test only');plan=app.state.actions.prepare([str(p)],'delete')
    assert p.exists();assert 'confirmation' not in plan
    with pytest.raises(PolicyError):app.state.actions.apply(plan['id'],False)
    assert run(app,plan)['status']=='complete';assert not p.exists()
    with pytest.raises(PolicyError):app.state.actions.apply(plan['id'],True)

def test_folder_permanent_delete_preserves_sibling(system):
    app,root=system;p=root/'obsolete';(p/'nested').mkdir(parents=True);(p/'nested'/'한글.txt').write_text('disposable');(root/'keep.txt').write_text('keep')
    plan=app.state.actions.prepare([str(p)],'delete');assert plan['items'][0]['files']==1
    r=run(app,plan);assert r['status']=='complete',r;assert not p.exists() and (root/'keep.txt').exists()

def test_recycle_one_call_for_folder_and_no_review(system,tmp_path):
    app,root=system;p=root/'obsolete';p.mkdir();(p/'a.txt').write_text('test')
    called=[]
    def mock(path):called.append(path);path.rename(tmp_path/'mock-recycle')
    app.state.actions.recycler=mock
    plan=app.state.actions.prepare([str(p)],'recycle');assert run(app,plan)['status']=='complete'
    assert called==[p] and (tmp_path/'mock-recycle'/'a.txt').exists()

def test_parent_child_selection_deduplicated(system):
    app,root=system;p=root/'folder';p.mkdir();f=p/'a.txt';f.write_text('test')
    assert len(app.state.actions.prepare([str(p),str(f)],'delete')['items'])==1

def test_changed_file_not_deleted(system):
    app,root=system;p=root/'file.txt';p.write_text('old');plan=app.state.actions.prepare([str(p)],'delete');p.write_text('changed content')
    assert run(app,plan)['status']=='partial_failure' and p.exists()

def test_new_child_not_deleted(system):
    app,root=system;p=root/'folder';p.mkdir();(p/'a').touch();plan=app.state.actions.prepare([str(p)],'delete');(p/'new').write_text('keep')
    assert run(app,plan)['status']=='partial_failure' and (p/'a').exists() and (p/'new').exists()

def test_root_and_explicit_protection(system):
    app,root=system;p=root/'important';p.mkdir();q=p/'secret';q.mkdir();app.state.policy.protect(q)
    for target in (root,p,q):
        with pytest.raises(PolicyError):app.state.actions.prepare([str(target)],'delete')

def test_cloud_skipped_and_not_deleted(system):
    app,root=system;p=root/'iCloudDrive';p.mkdir();(p/'cloud.txt').write_text('do not open')
    sid,s=scan(app,root);assert s['files']==0 and s['skipped']==1
    with pytest.raises(PolicyError):app.state.actions.prepare([str(p)],'delete')

def test_known_cloud_descendant_blocks_parent_recycle(system):
    app,root=system;p=root/'storage';p.mkdir();q=p/'synced';q.mkdir();app.state.policy.data['cloud_paths'].append(str(q));app.state.policy.save();app.state.policy.reload()
    with pytest.raises(PolicyError):app.state.actions.prepare([str(p)],'recycle')

def test_link_rejected(system,tmp_path):
    app,root=system;target=tmp_path/'keep';target.write_text('keep');p=root/'link'
    try:p.symlink_to(target)
    except OSError:pytest.skip('Windows policy does not allow symlink creation')
    with pytest.raises(PolicyError):app.state.actions.prepare([str(p)],'delete')
    assert target.exists()

def test_operation_api_and_history(system):
    app,root=system;p=root/'test.txt';p.write_text('fixture');c=client(app)
    plan=c.post('/api/operations/preview',json={'paths':[str(p)],'action':'delete'}).json();assert p.exists()
    r=c.post('/api/operations/'+plan['id']+'/apply',json={'approved':True});assert r.status_code==200
    app.state.actions.thread.join(10)
    assert c.get('/api/operations/'+plan['id']).json()['status']=='complete'
    assert c.get('/api/operations').json()[0]['id']==plan['id']

@pytest.mark.skipif(os.name!='nt',reason='Native Windows recycle only')
def test_native_windows_recycle_fixture_only(system):
    app,root=system;p=root/'PCSpace-disposable-recycle-test';p.mkdir();(p/'fixture.txt').write_text('Generated by automated PCSpace test. Not a user file.')
    plan=app.state.actions.prepare([str(p)],'recycle');r=run(app,plan)
    assert r['status']=='complete',r;assert not p.exists()

def test_missing_folder_hidden_and_deleted_path_redirects(system):
    app,root=system;p=root/'ghost';p.mkdir();(p/'a.bin').write_bytes(b'x'*123)
    sid,_=scan(app,root);p.joinpath('a.bin').unlink();p.rmdir();c=client(app)
    top=c.get('/api/tree',params={'scan_id':sid,'path':str(root)}).json()
    assert top['missing_folders']==1 and not [x for x in top['folders'] if x['name']=='ghost']
    moved=c.get('/api/tree',params={'scan_id':sid,'path':str(p)}).json()
    assert moved['path']==str(root) and moved['redirected_from']==str(p)

def test_folder_delete_reconciles_current_scan_tree(system):
    app,root=system;p=root/'obsolete';p.mkdir();(p/'a.bin').write_bytes(b'x'*321)
    sid,_=scan(app,root);plan=app.state.actions.prepare([str(p)],'delete',sid)
    assert run(app,plan)['status']=='complete' and not p.exists()
    assert app.state.db.one('SELECT * FROM tree WHERE scan_id=? AND path=?',(sid,str(p))) is None
    rr=app.state.db.one('SELECT logical_bytes,files FROM tree WHERE scan_id=? AND path=?',(sid,str(root)))
    ss=app.state.db.one('SELECT logical_bytes,files FROM scans WHERE id=?',(sid,))
    assert rr['files']==0 and rr['logical_bytes']==0 and ss==rr

def test_wsl_ubuntu_package_is_explained_not_called_junk():
    p=Path(r'C:\Users\sample\AppData\Local\Packages\CanonicalGroupLimited.Ubuntu24.04LTS_79rhkp1fndgsc')
    kind,hint=folder_hint(p)
    assert kind=='wsl' and 'WSL Ubuntu' in hint and '찌꺼기가 아님' in hint
