import fs from 'node:fs';import vm from 'node:vm';import assert from 'node:assert/strict';
const source=fs.readFileSync(new URL('../pcspace/static/app.js',import.meta.url),'utf8');
const partition=source.slice(source.indexOf('function partition('),source.indexOf('function renderMap('));
const c=vm.createContext({});vm.runInContext(partition,c);
for(let n=1;n<60;n++){const rows=Array.from({length:n},(_,i)=>({size:(i+1)*9}));c.rows=rows;const boxes=vm.runInContext('partition(rows,0,0,800,400)',c);assert.equal(boxes.length,n);const area=boxes.reduce((s,b)=>s+b.w*b.h,0);assert(Math.abs(area-320000)<.0001);for(const b of boxes){assert(b.w>0&&b.h>0);assert(b.x>=0&&b.y>=0);assert(b.x+b.w<=800.00001&&b.y+b.h<=400.00001);}}
const load=source.slice(source.indexOf('async function loadTree('),source.indexOf('function renderTree('));
let calls=[],rendered=[];const state={scan:'old',folder:'/old',generation:0};
const context=vm.createContext({S:state,$:()=>({value:''}),URLSearchParams,Date,api:q=>new Promise(resolve=>calls.push(resolve)),renderTree:()=>rendered.push(state.tree.path),renderEmpty:()=>{}});vm.runInContext(load,context);
const first=vm.runInContext('loadTree()',context);state.scan='new';state.folder='/new';const second=vm.runInContext('loadTree()',context);calls[1]({path:'/new'});await second;calls[0]({path:'/old'});await first;assert.deepEqual(rendered,['/new']);assert.equal(state.tree.path,'/new');
console.log('59 geometry cases and stale-response scenario passed');
