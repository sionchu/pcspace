"""Disposable Windows browser test data, never real user files."""
import argparse,json,time,os
from pathlib import Path
import uvicorn
from pcspace.web import create_app
p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--port',type=int,required=True);a=p.parse_args()
root=a.base/'sample-files';root.mkdir(parents=True)
fixtures={'Downloads/old-installer.zip':16,'Workspace/node_modules/cache.bin':12,'Projects/model.step':7,'Photos/photo-original.dng':6,'Backups/backup.zip':4,'Obsolete/nested/old.log':2}
for name,size in fixtures.items():
    f=root/name;f.parent.mkdir(parents=True,exist_ok=True)
    with f.open('wb') as stream:stream.truncate(size*1024**2)
    if 'old' in name:os.utime(f,(time.time()-180*86400,)*2)
(root/'keep-notes.txt').write_text('Generated browser fixture; keep during test.',encoding='utf-8')
app=create_app(a.base/'state',[str(root)]);app.state.policy.data['origins']=[f'http://127.0.0.1:{a.port}'];app.state.policy.save();app.state.policy.reload()
(a.base/'fixture.json').write_text(json.dumps({'root':str(root),'state':str(a.base/'state')}),encoding='utf-8')
uvicorn.run(app,host='127.0.0.1',port=a.port,access_log=False,proxy_headers=False)
