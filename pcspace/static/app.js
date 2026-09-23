'use strict';
const $ = id => document.getElementById(id);
const DEMO = document.documentElement.dataset.demo === 'true' || new URLSearchParams(location.search).get('demo') === '1';
function preference(key, fallback) { try { return localStorage.getItem('pcspace-' + key) || fallback; } catch { return fallback; } }
function savePreference(key, value) { try { localStorage.setItem('pcspace-' + key, value); } catch {} }
let language = new URLSearchParams(location.search).get('lang') || preference('language', navigator.language.startsWith('ko') ? 'ko' : 'en');
if (!['ko', 'en'].includes(language)) language = 'en';
const tr = (en, ko) => language === 'ko' ? ko : en;
const S = {csrf:'', view:'map', dashboard:null, scan:null, folder:null, tree:null, selected:new Map(), generation:0, refreshing:false, lastTree:0, plan:null};
const h = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
const count = n => Number(n || 0).toLocaleString(language === 'ko' ? 'ko-KR' : 'en-US');
const date = n => n ? new Date(n * 1000).toLocaleString(language === 'ko' ? 'ko-KR' : 'en-US', {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'}) : '';
function bytes(n) {
  if (n === null || n === undefined) return tr('Not measured', '미집계');
  if (n === 0) return '0 B';
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'], k = Math.min(4, Math.floor(Math.log(Math.max(n, 1)) / Math.log(1024)));
  return (n / 1024 ** k).toLocaleString(language === 'ko' ? 'ko-KR' : 'en-US', {maximumFractionDigits:k >= 3 ? 2 : 1}) + ' ' + units[k];
}
function statusLabel(s) {
  const labels = {running:['Analyzing', '분석 중'], paused:['Paused', '일시정지'], complete:['Complete', '분석 완료'], complete_with_exclusions:['Complete · exclusions', '분석 완료 · 제외 항목 있음'], partial:['Legacy partial scan', '이전 버전 부분 스캔'], cancelled:['Stopped', '중지됨'], interrupted:['Interrupted', '이전 분석 중단'], failed:['Error', '오류'], planned:['Awaiting confirmation', '확인 대기'], applying:['Processing', '처리 중'], partial_failure:['Some items failed', '일부 실패'], needs_review:['Check interrupted operation', '중단 후 확인 필요']};
  return labels[s] ? tr(...labels[s]) : s;
}
function hint(r) {
  if (language === 'ko') return r.blocked || r.hint || '';
  if (r.blocked) return 'Protected path · unavailable for cleanup';
  const labels = {generated:'Cache / build / dependencies · check before removing', archive:'Archive or backup · confirm another copy exists', project:'Project files · other tools may rely on this path', wsl:'WSL Linux data · deleting the virtual disk loses the distribution', appdata:'Installed app data · check the application first', candidate:'Old installer, archive or temporary-file candidate', normal:'Explore by size · you decide what stays'};
  return labels[r.kind] || r.hint || labels.normal;
}
function errorText(message) {
  if (language === 'ko' || !/[가-힣]/.test(message)) return message;
  const messages = {
    '경로가 존재하지 않습니다.':'The path no longer exists. Refresh this folder.',
    '진행 중인 분석이 아닙니다.':'This scan is not running.',
    '현재 분석을 일시정지한 뒤 다른 분석을 시작하세요.':'Pause the active scan before starting another.',
    '스캔/계획 이후 파일이 변경되었습니다. 다시 스캔해 주세요.':'The item changed after the preview. Select it again.',
    '폴더를 선택하세요.':'Select an existing folder.',
    '잘못된 경로입니다.':'Invalid path.',
    '허용된 로컬 드라이브 밖입니다.':'This path is outside the allowed local roots.',
    '선택한 분석 범위 밖입니다.':'This path is outside the selected scan.',
    '링크·정션·클라우드 경로는 일반 작업에서 제외됩니다.':'Links, junctions and cloud placeholders are excluded.',
    '분석 루트가 더 이상 존재하지 않습니다. 새 분석을 시작하세요.':'The scan root no longer exists. Start a scan of an existing folder.'
  };
  return messages[message] || 'The operation could not be completed. Details: ' + message;
}
function toast(text, bad=false) {
  $('toast').textContent = errorText(text); $('toast').classList.toggle('error', bad); $('toast').hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => $('toast').hidden = true, 6000);
}
async function api(path, body, retry=true) {
  if (DEMO) return window.PCSpaceDemo.api(path, body);
  const opts = {credentials:'same-origin', headers:{}};
  if (body !== undefined) { opts.method='POST'; opts.headers={'Content-Type':'application/json', 'X-PCSpace-CSRF':S.csrf}; opts.body=JSON.stringify(body); }
  const response = await fetch(path, opts);
  if (response.status === 401 && retry && path !== '/api/session') { await connect(false); return api(path, body, false); }
  const data = await response.json();
  if (!response.ok) throw Error(errorText(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)));
  return data;
}
async function connect(load=true) {
  const d = await api('/api/session', {}, false); S.csrf = d.csrf;
  $('connection').textContent = DEMO ? tr('Sample workspace', '샘플 워크스페이스') : d.connection.includes('Tailscale') ? tr('Private Tailscale connection', 'Tailscale 본인 인증') : tr('Connected to this PC', 'PC 직접 접속');
  $('version').textContent = 'PCSpace ' + d.version; $('connect-error').hidden = true;
  if (location.hash) history.replaceState(null, '', location.pathname + location.search);
  if (load) await refresh(true);
}
function currentScan() { return S.dashboard?.scans.find(x => x.id === S.scan); }
function sortRows(rows) { const key = $('sort-mode').value; return [...rows].sort((a,b) => (b[key] || 0) - (a[key] || 0) || (b.size || 0) - (a.size || 0)); }
function setSelected(r, on) {
  if (r.blocked) return;
  if (on) S.selected.set(r.path, r); else S.selected.delete(r.path);
  selection();
  document.querySelectorAll('[data-select]').forEach(e => { e.checked=S.selected.has(e.dataset.select); e.closest('.tile,.entry')?.classList.toggle('selected', e.checked); });
}
function selection() {
  const rows = [...S.selected.values()]; $('selection-bar').hidden = !rows.length;
  $('selection-count').textContent = count(rows.length) + tr(' selected', '개 선택');
  $('selection-size').textContent = bytes(rows.reduce((n,r) => n + (r.size || 0), 0)) + tr(' · includes folder contents', ' · 하위 항목 포함');
}
function clearSelection() { S.selected.clear(); selection(); document.querySelectorAll('[data-select]').forEach(e => {e.checked=false; e.closest('.tile,.entry')?.classList.remove('selected');}); }
async function navigate(path) { S.folder=path; S.generation++; clearSelection(); $('search').value=''; $('tooltip').hidden=true; await loadTree(); }
async function refresh(force=false) {
  if (S.refreshing || !S.csrf) return;
  S.refreshing = true;
  try {
    const previousStatus = currentScan()?.status; S.dashboard = await api('/api/dashboard');
    if (!S.scan && S.dashboard.scans.length) { S.scan=S.dashboard.scans[0].id; S.folder=S.dashboard.scans[0].root; }
    if (!$('scan-root').value) $('scan-root').value = S.dashboard.roots.find(x => /^D:/i.test(x)) || S.dashboard.roots[0] || '';
    renderDashboard();
    if (S.view === 'map' && (force || !S.tree || previousStatus !== currentScan()?.status || Date.now() - S.lastTree > (S.dashboard.active_id ? 5000 : 20000))) await loadTree();
    if (S.view === 'history' && force) await historyView();
  } finally { S.refreshing = false; }
}
function renderDashboard() {
  const d=S.dashboard, root=currentScan()?.root || $('scan-root').value;
  $('drives').innerHTML=d.disks.map(x => `<button class="drive-button ${root.toLowerCase().startsWith(x.root.toLowerCase())?'active':''}" data-drive="${h(x.root)}"><span class="drive-title"><strong><span aria-hidden="true">▱</span> ${h(x.root)}</strong><span>${x.error?tr('Unavailable','사용 불가'):(100-x.free_percent).toFixed(1)+'%'}</span></span>${x.error?'':`<div class="meter"><i class="${x.free_percent<10?'low':''}" style="width:${100-x.free_percent}%"></i></div><small>${bytes(x.free)} ${tr('free','여유')} / ${bytes(x.total)}</small>`}</button>`).join('');
  $('drives').querySelectorAll('[data-drive]').forEach(b => b.onclick=() => chooseDrive(b.dataset.drive).catch(e=>toast(e.message,true)));
  $('scan-selector').innerHTML=d.scans.length ? d.scans.map(r => `<option value="${h(r.id)}">${h(r.root)} · ${date(r.started)} · ${h(statusLabel(r.status))}</option>`).join('') : `<option>${tr('No scan yet','아직 분석 기록이 없습니다')}</option>`;
  $('scan-selector').value=S.scan || '';
  const scan=currentScan(); $('start-scan').disabled=!!d.active_id || DEMO;
  $('pause-scan').hidden=!(scan && scan.status==='running' && scan.id===d.active_id);
  $('resume-scan').hidden=!(scan && scan.engine==='tree2' && ['paused','failed'].includes(scan.status)); $('resume-scan').disabled=!!d.active_id || DEMO;
  if (scan) {
    $('scan-status').textContent=statusLabel(scan.status); $('status-dot').classList.toggle('running', scan.status==='running');
    const elapsed=Math.max(1,(scan.ended || Date.now()/1000)-scan.started);
    $('scan-progress').textContent=`${count(scan.files)} ${tr('files','개 파일')} · ${Math.round(elapsed)}s · ${count(Math.round(scan.files/elapsed))} ${tr('files/s avg.','개/초 평균')}`;
    $('current-path').textContent=scan.current_path || tr('No time or file-count cutoff. Folder checkpoints support pause and resume.','시간·파일 수 강제 중단 없음 · 완료 폴더는 체크포인트로 저장됩니다.');
  }
  const disk=d.disks.find(x => root.toLowerCase().startsWith(x.root.toLowerCase()) && !x.error);
  $('metric-free').textContent=disk?bytes(disk.free):'—';
  $('metric-free-note').textContent=disk?`${disk.root} · ${bytes(disk.total)} ${tr('total','전체')} · ${disk.free_percent}% ${tr('free','여유')}`:tr('Recycle Bin contents still occupy space.','휴지통은 비우기 전까지 공간을 차지합니다.');
}
async function chooseDrive(root) {
  $('scan-root').value=root; const scan=S.dashboard.scans.find(s=>s.root===root);
  S.scan=scan?.id || null; S.tree=null; S.folder=root; S.generation++; clearSelection();
  if (S.view!=='map') await view('map');
  if (scan) await loadTree(); else {renderEmpty(); toast(tr('Analyze this drive to see its folders.','분석 시작을 누르면 이 드라이브를 읽습니다.'));}
  renderDashboard();
}
function renderEmpty() {
  S.tree=null; $('treemap').innerHTML=`<div class="empty"><strong>${tr('A clearer view starts here.','먼저 용량을 분석해 보세요.')}</strong><span>${tr('Choose a folder, then analyze storage.','폴더를 고르고 분석하면 큰 폴더부터 표시됩니다.')}</span></div>`;
  $('entry-list').innerHTML=''; $('breadcrumbs').textContent=S.folder || ''; $('metric-total').textContent='—'; $('metric-candidate').textContent='—';
}
async function loadTree() {
  if (!S.scan || !S.folder) {renderEmpty(); return;}
  const gen=++S.generation, sid=S.scan, path=S.folder;
  const query=new URLSearchParams({scan_id:sid, path, q:$('search').value});
  const t=await api('/api/tree?' + query);
  if (gen!==S.generation || sid!==S.scan || path!==S.folder) return;
  if (t.redirected_from && t.path!==path) {S.folder=t.path; clearSelection(); toast(tr('That folder moved or disappeared. Showing its nearest existing parent.','삭제·이동된 경로라 가장 가까운 상위 폴더로 이동했습니다.'));}
  S.tree=t; S.lastTree=Date.now(); renderTree();
}
function renderTree() {
  const t=S.tree; if (!t) return;
  const r=t.total, total=r?.logical_bytes ?? t.folders.reduce((n,x)=>n+x.size,0)+t.files.reduce((n,x)=>n+x.size,0);
  $('metric-total').textContent=bytes(total); $('metric-count').textContent=`${count(r?.files)} ${tr('files','개 파일')} · ${count(t.folders.length)} ${tr('folders · logical size','개 하위 폴더 · 논리 크기')}`;
  $('metric-candidate').textContent=bytes(r?.candidate_bytes || 0);
  const notes=[];
  if (['running','paused'].includes(t.scan.status) || t.scan.engine==='legacy') notes.push(tr('Partial totals: only the entries scanned so far are included.','현재까지 읽은 범위의 부분 합계입니다. 미집계 항목은 포함되지 않습니다.'));
  if (t.scan.stale) notes.push(tr('Some data changed after this scan. Missing paths are hidden; rescan for current totals.','분석 이후 파일시스템이 바뀌었습니다. 없는 경로는 숨기며 정확한 합계는 다시 분석하세요.'));
  if (t.missing_folders) notes.push(count(t.missing_folders)+tr(' missing folders hidden.','개 사라진 폴더를 자동 제외했습니다.'));
  if (t.scan.skipped || t.scan.errors) notes.push(`${count(t.scan.skipped)} ${tr('excluded','제외')} · ${count(t.scan.errors)} ${tr('errors. Unread data is not included.','오류. 읽지 못한 용량은 제외됩니다.')}`);
  $('scan-note').hidden=!notes.length; $('scan-note').textContent=notes.join(' ');
  const root=t.scan.root, sep=root.includes('\\')?'\\':'/', rest=t.path.slice(root.length).split(/[\\/]/).filter(Boolean), crumbs=[{label:root,path:root}];
  let cur=root; for (const part of rest) {cur=cur.replace(/[\\/]$/,'')+sep+part; crumbs.push({label:part,path:cur});}
  $('breadcrumbs').innerHTML=crumbs.map((x,i)=>`${i?'<span>/</span>':''}<button data-path="${h(x.path)}">${h(x.label)}</button>`).join('');
  $('breadcrumbs').querySelectorAll('button').forEach(b=>b.onclick=()=>navigate(b.dataset.path).catch(e=>toast(e.message,true)));
  $('go-up').disabled=!t.parent;
  const rows=sortRows([...t.folders,...t.files]), available=new Set(rows.filter(x=>!x.blocked).map(x=>x.path));
  for (const path of S.selected.keys()) if (!available.has(path)) S.selected.delete(path);
  selection(); $('row-count').textContent=count(rows.length);
  const maxSize=Math.max(1,...rows.map(x=>x.size || 0));
  $('entry-list').innerHTML=rows.map((r,i)=>`<div class="entry ${S.selected.has(r.path)?'selected':''}" role="listitem"><input type="checkbox" data-select="${h(r.path)}" data-index="${i}" aria-label="${h(tr('Select ','선택: ')+r.name)}" ${r.blocked?'disabled':''} ${S.selected.has(r.path)?'checked':''}><div class="entry-main" data-index="${i}" tabindex="0" role="button" title="${h(r.path+'\n'+hint(r))}"><div class="entry-name"><span class="folder-icon" aria-hidden="true">${r.directory?'▰':'▤'}</span>${h(r.name)}</div><div class="entry-hint">${h(hint(r))}</div><div class="entry-bar"><i class="${r.candidates?'candidate':''}" style="width:${Math.max(1,100*(r.size||0)/maxSize)}%"></i></div></div><div class="entry-size">${r.measured?bytes(r.size):tr('Not measured','미집계')}${r.candidates?`<small>${tr('Review ','후보 ')}${bytes(r.candidates)}</small>`:''}</div></div>`).join('') || `<div class="empty">${tr('No items to display here.','이 위치에 표시할 항목이 없습니다.')}</div>`;
  $('entry-list').querySelectorAll('[data-select]').forEach(e=>e.onchange=()=>setSelected(rows[+e.dataset.index],e.checked));
  $('entry-list').querySelectorAll('.entry-main').forEach(e=>{const enter=()=>{const r=rows[+e.dataset.index]; if(r.directory) navigate(r.path).catch(err=>toast(err.message,true)); else setSelected(r,!S.selected.has(r.path));}; e.onclick=enter; e.onkeydown=k=>{if(['Enter',' '].includes(k.key)){k.preventDefault();enter();}};});
  $('list-note').textContent=t.omitted_files?tr(`Showing ${t.files.length} largest direct files. ${count(t.omitted_files)} others are available by name search or parent-folder selection.`,`직접 파일은 큰 항목 ${t.files.length}개만 표시합니다. 나머지 ${count(t.omitted_files)}개는 이름 검색이나 상위 폴더 선택으로 관리하세요.`):tr('Select a folder to include its contents. One confirmation. No forced quarantine.','폴더 선택은 하위 항목을 포함합니다. 사유 입력·격리 없이 한 번 확인합니다.');
  renderMap(rows);
}
function partition(items,x,y,w,hgt,result=[]) {
  if (!items.length) return result;
  if (items.length===1) {result.push({...items[0],x,y,w,h:hgt});return result;}
  const total=items.reduce((n,r)=>n+r.size,0);let sum=0,cut=0;
  while(cut<items.length-1 && sum<total/2) {sum+=items[cut].size;cut++;}
  const ratio=sum/total;
  if(w>=hgt){partition(items.slice(0,cut),x,y,w*ratio,hgt,result);partition(items.slice(cut),x+w*ratio,y,w*(1-ratio),hgt,result);}
  else{partition(items.slice(0,cut),x,y,w,hgt*ratio,result);partition(items.slice(cut),x,y+hgt*ratio,w,hgt*(1-ratio),result);}
  return result;
}
function renderMap(rows) {
  const box=$('treemap'), positive=rows.filter(x=>x.size>0), items=positive.slice(0,40), others=positive.slice(40);
  if(others.length) items.push({name:tr(`${others.length} other items`,`그 외 ${others.length}개`),path:'',size:others.reduce((n,r)=>n+r.size,0),candidates:others.reduce((n,r)=>n+r.candidates,0),other:true});
  items.sort((a,b)=>b.size-a.size);
  if(!items.length){box.innerHTML=`<div class="empty"><strong>${tr('No measured space yet','아직 집계된 용량이 없습니다.')}</strong><span>${tr('Results appear as the scan progresses.','분석 중에는 결과가 순차적으로 나타납니다.')}</span></div>`;return;}
  const cells=partition(items,0,0,box.clientWidth,box.clientHeight), total=items.reduce((n,r)=>n+r.size,0);
  box.innerHTML='';
  cells.forEach((r,i)=>{
    const tile=document.createElement('div'), candidate=r.candidates>0 && r.candidates/r.size>.12;
    tile.className='tile'+(r.w<145 || r.h<108?' small':'')+(S.selected.has(r.path)?' selected':'');
    const blue=['#566bc7','#6175bf','#527d9e','#7584b9','#577caa','#6978a0'], amber=['#b88240','#bf9557','#ad7c44','#bc8e56'];
    tile.style.cssText=`left:${r.x+2}px;top:${r.y+2}px;width:${Math.max(1,r.w-4)}px;height:${Math.max(1,r.h-4)}px;background:${candidate?amber[i%amber.length]:blue[i%blue.length]}`;
    tile.tabIndex=0; tile.setAttribute('role','button');tile.setAttribute('aria-label',`${r.name} ${bytes(r.size)} ${r.directory?tr('open folder','하위 폴더 열기'):tr('select','선택')}`);
    tile.innerHTML=`<div class="tile-inner"><div class="tile-name">${h(r.name)}</div><div class="tile-size">${bytes(r.size)}</div>${r.directory?`<div class="tile-note">${count(r.files)} ${tr('files','개 파일')}</div>`:''}<div class="tile-share">${(100*r.size/total).toFixed(1)}% ${tr('of shown items','표시 항목 중')}</div></div>${r.candidates?`<div class="candidate-stripe" style="width:${Math.min(100,100*r.candidates/r.size)}%"></div>`:''}${!r.other && r.w>65 && r.h>45?`<input type="checkbox" data-select="${h(r.path)}" aria-label="${h(tr('Select ','선택: ')+r.name)}" ${r.blocked?'disabled':''} ${S.selected.has(r.path)?'checked':''}>`:''}`;
    const enter=()=>{if(r.other){$('entry-list').scrollIntoView({behavior:'smooth',block:'nearest'});return;}if(r.directory) navigate(r.path).catch(e=>toast(e.message,true));else setSelected(r,!S.selected.has(r.path));};
    tile.onclick=e=>{if(e.target.tagName!=='INPUT')enter();}; tile.onkeydown=e=>{if(e.target===tile && ['Enter',' '].includes(e.key)){e.preventDefault();enter();}};
    const checkbox=tile.querySelector('input');if(checkbox){checkbox.onclick=e=>e.stopPropagation();checkbox.onchange=()=>setSelected(r,checkbox.checked);}
    tile.onmousemove=e=>{const tip=$('tooltip');tip.hidden=false;tip.textContent=`${r.path||r.name}\n${bytes(r.size)}${r.candidates?' · '+tr('Review ','후보 ')+bytes(r.candidates):''}${r.hint?'\n'+hint(r):''}`;tip.style.whiteSpace='pre-line';tip.style.left=Math.max(8,Math.min(innerWidth-350,e.clientX+16))+'px';tip.style.top=Math.max(8,Math.min(innerHeight-135,e.clientY+18))+'px';};
    tile.onmouseleave=()=>$('tooltip').hidden=true;box.appendChild(tile);
  });
}
async function startScan() {
  const root=$('scan-root').value.trim();$('start-scan').disabled=true;
  try{const r=await api('/api/scans',{root});S.scan=r.id;S.tree=null;S.generation++;clearSelection();S.dashboard=await api('/api/dashboard');S.folder=currentScan()?.root||root;await refresh(true);toast(tr('Analyzing folders. You can pause and resume at any time.','폴더를 분석합니다. 언제든 일시정지하고 이어서 분석할 수 있습니다.'));}
  finally{$('start-scan').disabled=!!S.dashboard?.active_id||DEMO;}
}
function modal(title,body) {$('modal-title').textContent=title;$('modal-body').innerHTML=body;if(!$('operation-modal').open)$('operation-modal').showModal();}
async function prepare(action) {
  if(!S.selected.size)return;
  if(DEMO){toast(tr('Read-only demo: no files are scanned, moved, or deleted.','읽기 전용 데모입니다. 파일을 읽거나 이동·삭제하지 않습니다.'));return;}
  const paths=[...S.selected.keys()];modal(tr('Checking selection','선택 항목 확인'),`<div class="empty">${tr('Checking the selected paths…','선택한 경로를 확인하고 있습니다…')}</div>`);
  try{
    const p=await api('/api/operations/preview',{paths,action,scan_id:S.scan});S.plan=p;
    const label=action==='delete'?tr('Delete permanently','영구 삭제'):tr('Move to Recycle Bin','휴지통으로 이동');
    const warning=action==='delete'?tr('These files and folders will be permanently deleted. PCSpace and the Recycle Bin cannot restore them.','선택한 파일·폴더를 바로 영구 삭제합니다. PCSpace나 휴지통에서 복원할 수 없습니다.'):tr('Move these items to the Windows Recycle Bin. Restore them there if needed. Space is not freed until the bin is emptied.','Windows 휴지통으로 이동합니다. 복원은 PC 휴지통에서 할 수 있습니다. 비워지기 전까지 공간은 확보되지 않습니다.');
    modal(label,`<div class="warning ${action==='delete'?'permanent':''}">${warning}</div><div class="targets">${p.items.map(r=>`<div class="target">${h(r.source)}<small>${r.directory?tr('All contents included · ','하위 항목 전체 포함 · '):''}${bytes(r.size)} · ${count(r.files)} ${tr('files','개 파일')}</small></div>`).join('')}</div><p>${count(p.items.length)} ${tr('selected items. Check this list, then confirm once.','개 대상입니다. 위 목록을 확인한 뒤 한 번만 승인하세요.')}</p><div class="modal-actions"><button id="cancel-operation">${tr('Cancel','취소')}</button><button id="confirm-operation" class="${action==='delete'?'danger':'primary'}">${label}</button></div>`);
    $('cancel-operation').onclick=()=>$('operation-modal').close();$('confirm-operation').onclick=()=>execute(p.id).catch(e=>toast(e.message,true));
  }catch(e){modal(tr('Nothing was changed','실행하지 않았습니다.'),`<p>${h(errorText(e.message))}</p>`);}
}
async function execute(id) {
  $('confirm-operation').disabled=true;await api(`/api/operations/${id}/apply`,{approved:true});
  modal(tr('Processing','처리 중'),`<div class="empty">${tr('Processing the selected items. Results are recorded in Activity.','선택한 항목을 처리합니다. 작업 기록에도 결과가 남습니다.')}</div>`);
  for(;;){
    await new Promise(r=>setTimeout(r,500));const p=await api('/api/operations/'+id);if(p.status==='applying')continue;S.plan=p;
    const done=p.results.filter(r=>r.status==='done').length;
    modal(done===p.items.length?tr('Cleanup complete','정리 완료'):tr('Some items need attention','일부 항목을 처리하지 못했습니다.'),`<h3>${done} / ${p.items.length} ${tr('completed','개 완료')}</h3>${p.results.map(r=>`<div class="target ${r.status==='done'?'success':'failure'}">${h(r.source)}<small>${h(r.error?errorText(r.error):tr('Completed','완료'))}${r.index_warning?' · '+h(r.index_warning):''}</small></div>`).join('')}<p>${tr('Missing paths are removed from view. Rescan if other changes leave totals out of date.','없는 경로는 지도에서 제거합니다. 다른 변경으로 합계가 오래되면 다시 분석하세요.')}</p><div class="modal-actions"><button id="done-operation" class="primary">${tr('Close','닫기')}</button></div>`);
    $('done-operation').onclick=()=>$('operation-modal').close();clearSelection();await refresh(true);break;
  }
}
async function historyView() {
  const list=await api('/api/operations'),labels={recycle:tr('Recycle Bin','휴지통 이동'),delete:tr('Permanent deletion','영구 삭제'),quarantine:tr('Legacy quarantine','이전 격리'),restore:tr('Legacy restore','이전 복원'),purge:tr('Legacy purge','이전 영구삭제')};
  $('history-list').innerHTML=list.map(p=>{const results=JSON.parse(p.results),items=JSON.parse(p.items);return `<article class="history-card"><h3>${h(labels[p.action]||p.action)} · ${h(statusLabel(p.status))}</h3><small>${date(p.created)} · ${items.length} ${tr('selected items','개 대상')}</small><pre>${h((results.length?results.map(r=>(r.status==='done'?tr('Done','완료'):tr('Failed','실패'))+' '+r.source+(r.error?' — '+errorText(r.error):'')):items.map(r=>r.source)).join('\n'))}</pre></article>`;}).join('') || `<div class="empty"><strong>${tr('Nothing changed yet.','아직 정리 작업이 없습니다.')}</strong><span>${tr('Your approved operations will appear here.','승인한 정리 작업의 결과가 여기에 표시됩니다.')}</span></div>`;
}
async function view(name) {
  S.view=name;['map','history','settings'].forEach(x=>$(x+'-view').hidden=x!==name);
  document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===name));
  $('header-label').textContent={map:tr('Storage map','용량 지도'),history:tr('Activity','작업 기록'),settings:tr('Settings','설정')}[name];
  if(name==='history')await historyView();if(name==='map')await refresh(true);
  if(name==='settings'){const p=await api('/api/policy');$('policy-list').innerHTML=p.protected_paths.map(x=>`<div class="target">${h(x)}</div>`).join('');}
}
function applyLanguage() {
  document.documentElement.lang=language;$('language').value=language;
  document.querySelectorAll('[data-en]').forEach(e=>e.textContent=e.dataset[language]);
  document.querySelectorAll('[data-placeholder-en]').forEach(e=>e.placeholder=e.dataset[language==='ko'?'placeholderKo':'placeholderEn']);
  document.title='PCSpace · '+tr('Storage explorer','용량 지도');
}
function bind(id,fn) {$(id).onclick=()=>Promise.resolve().then(fn).catch(e=>toast(e.message,true));}
bind('start-scan',startScan);bind('pause-scan',async()=>{await api(`/api/scans/${S.scan}/pause`,{});toast(tr('Saving a checkpoint and pausing.','체크포인트를 저장하고 일시정지합니다.'));});bind('resume-scan',async()=>{await api(`/api/scans/${S.scan}/resume`,{});await refresh(true);});
bind('refresh',()=>refresh(true));bind('retry',()=>connect());bind('clear-selection',clearSelection);bind('recycle-selected',()=>prepare('recycle'));bind('delete-selected',()=>prepare('delete'));bind('close-modal',()=>$('operation-modal').close());
bind('go-up',()=>S.tree?.parent&&navigate(S.tree.parent));bind('open-folder',()=>api('/api/open-folder',{path:S.folder||$('scan-root').value}));bind('open-recycle',()=>api('/api/recycle-bin',{}));
bind('protect-folder',async()=>{await api('/api/protect',{path:$('protect-path').value});toast(tr('Folder protection added.','보호 경로를 추가했습니다.'));await view('settings');});
bind('theme-toggle',()=>{const theme=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=theme;savePreference('theme',theme);});
$('language').onchange=async()=>{language=$('language').value;savePreference('language',language);applyLanguage();await connect(false);await view(S.view);selection();};
$('scan-selector').onchange=async()=>{S.scan=$('scan-selector').value;S.folder=currentScan().root;S.tree=null;S.generation++;clearSelection();await refresh(true);};
$('sort-mode').onchange=()=>renderTree();$('search').oninput=()=>{clearTimeout(S.searchTimer);S.searchTimer=setTimeout(()=>loadTree().catch(e=>toast(e.message,true)),350);};
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>view(b.dataset.view).catch(e=>toast(e.message,true)));
new ResizeObserver(()=>{if(S.tree&&S.view==='map')renderMap(sortRows([...S.tree.folders,...S.tree.files]));}).observe($('treemap'));
document.documentElement.dataset.theme=preference('theme','light');applyLanguage();
if(DEMO){$('demo-banner').hidden=false;$('demo-link').hidden=true;['open-folder','open-recycle','protect-folder'].forEach(id=>$(id).disabled=true);}
connect().then(()=>view(S.view)).catch(e=>{$('connect-error').hidden=false;$('connection-message').textContent=errorText(e.message);});
setInterval(()=>{if(!document.hidden)refresh().catch(e=>toast(e.message,true));},2500);
