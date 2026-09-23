import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const context=vm.createContext({window:{},URL,Date});
vm.runInContext(fs.readFileSync(new URL('../pcspace/static/demo.js',import.meta.url),'utf8'),context);
const api=context.window.PCSpaceDemo.api;
const d=await api('/api/dashboard');
assert.equal(d.scans.length,2);assert.equal(d.active_id,null);
for(const scan of d.scans){
 const q=new URLSearchParams({scan_id:scan.id,path:scan.root});const tree=await api('/api/tree?'+q);
 assert.equal(tree.total.logical_bytes,[...tree.folders,...tree.files].reduce((s,r)=>s+r.size,0));
 assert(tree.total.candidate_bytes>0 && tree.total.candidate_bytes<tree.total.logical_bytes);
}
await assert.rejects(api('/api/operations/preview',{paths:['D:\\Projects'],action:'delete'}),/Read-only/);
await assert.rejects(api('/api/scans',{root:'D:\\'}),/Read-only/);
assert.equal((await api('/api/operations')).length,0);
console.log('Read-only demo: totals, two drives, mutation rejection, no backend dependency passed');
