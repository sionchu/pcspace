/* Synthetic, read-only demo. This adapter never fetches a backend or accesses files. */
(() => {
  'use strict';
  const GiB=1024**3;
  const file=(name,gb,review=false,kind='normal')=>({name,directory:false,size:Math.round(gb*GiB),candidates:review?Math.round(gb*GiB):0,files:1,kind});
  const folder=(name,children,kind='normal')=>({name,directory:true,children,kind});
  const roots=[
    folder('D:\\',[
      folder('Projects',[
        folder('design-system',[folder('node_modules',[file('packages.bin',18,true)],'generated'),folder('build',[file('bundle-cache.bin',10,true)],'generated'),file('source-assets.zip',28)]),
        folder('Studio',[file('scene-assets.blend',42),file('textures.pack',28)])
      ],'project'),
      folder('Downloads',[folder('Installers',[file('older-sdk.zip',36,true),file('tools-setup.iso',20,true)]),folder('Recent',[file('reference-assets.zip',24),file('archive.7z',14)])]),
      folder('Media',[folder('Video',[file('episode-01.mov',30),file('episode-02.mov',22)]),folder('Photos',[file('photo-library.pack',30)])]),
      folder('Virtual Machines',[file('ext4.vhdx',64,false,'wsl')],'wsl'),
      folder('Cache',[folder('Package cache',[file('download-cache.bin',26,true)]),folder('Build cache',[file('build-cache.bin',12,true)])],'generated'),
      folder('Archive',[file('project-backup.zip',24),file('old-export.tmp',4,true)],'archive'),
      file('old-system-image.iso',18,true)
    ]),
    folder('C:\\',[folder('Users',[folder('demo',[folder('Documents',[file('project-library.pack',92)]),folder('Downloads',[file('old-installer.zip',34,true),file('recent-assets.zip',28)]),folder('Media',[file('video-library.pack',104)])])]),folder('Tools',[file('tools.pack',60)])])
  ];
  const index=new Map();
  function measure(node,parent=null) {
    node.path=parent?parent.path.replace(/[\\/]$/,'')+'\\'+node.name:node.name;
    node.parent=parent?.path||null; node.measured=true;node.blocked=null;
    node.hint='Synthetic example, not a real file.';
    if(node.directory){node.children.forEach(c=>measure(c,node));node.size=node.children.reduce((n,c)=>n+c.size,0);node.candidates=node.children.reduce((n,c)=>n+c.candidates,0);node.files=node.children.reduce((n,c)=>n+c.files,0);}
    index.set(node.path,node);
  }
  roots.forEach(r=>measure(r));
  const started=Date.UTC(2026,8,1,10,0)/1000;
  const scans=roots.map((r,i)=>({id:'demo-'+i,root:r.path,status:'complete',files:r.files,logical_bytes:r.size,started:started-i*60,ended:started-i*60+12,engine:'tree2',stale:0,skipped:0,errors:0,current_path:''}));
  const row=node=>Object.fromEntries(Object.entries(node).filter(([k])=>!['children','parent'].includes(k)));
  window.PCSpaceDemo={
    async api(raw,body) {
      const url=new URL(raw,'https://demo.invalid'),path=url.pathname;
      if(path==='/api/session')return {csrf:'demo-only',version:'0.3.0',connection:'Demo'};
      if(body!==undefined)throw Error('Read-only demo. No files can be scanned, moved, deleted, or protected.');
      if(path==='/api/dashboard')return {roots:roots.map(r=>r.path),scans,active_id:null,disks:roots.map((r,i)=>{const total=(i?512:1024)*GiB,free=total-r.size;return {root:r.path,total,free,used:r.size,free_percent:Math.round(free/total*10000)/100,error:null};})};
      if(path==='/api/tree'){
        const scan=scans.find(s=>s.id===url.searchParams.get('scan_id'));
        let p=url.searchParams.get('path'),node=index.get(p);if(!node?.directory){p=scan.root;node=index.get(p);}
        const q=(url.searchParams.get('q')||'').toLowerCase(),children=node.children.filter(c=>c.name.toLowerCase().includes(q));
        return {scan,path:p,parent:node.parent,total:{logical_bytes:node.size,files:node.files,candidate_bytes:node.candidates},folders:children.filter(n=>n.directory).map(row),files:children.filter(n=>!n.directory).map(row),missing_folders:0,omitted_files:0,excluded:0};
      }
      if(path==='/api/operations')return [];
      if(path==='/api/policy')return {protected_paths:['C:\\Windows','C:\\Program Files'],cloud_paths:[],auto_delete:false};
      throw Error('This action is not part of the read-only demo.');
    }
  };
})();
