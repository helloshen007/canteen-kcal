'use strict';
const $ = (selector) => document.querySelector(selector);
const state = {user: null, file: null, preview: null, job: null, poll: null, page: 'workspace', authMode: 'login', pending: null, offset: 0, total: 0};
const names = {'avocado':'牛油果','bacon':'培根','blackberries':'黑莓','broccoli':'西兰花','brussels sprouts':'抱子甘蓝','caesar salad':'凯撒沙拉','cantaloupe':'哈密瓜','cauliflower':'花椰菜','celery':'芹菜','chicken':'鸡肉','cucumbers':'黄瓜','eggplant':'茄子','eggs':'鸡蛋','fish':'鱼肉','honeydew melons':'蜜瓜','mixed greens':'混合生菜','olives':'橄榄','potatoes':'土豆','raspberries':'覆盆子','spinach (raw)':'生菠菜','steak':'牛排','strawberries':'草莓','watermelon':'西瓜','yam':'山药'};
const statuses = {queued:'排队中',running:'分析中',succeeded:'已完成',partial:'部分失败',failed:'执行失败',pending:'等待处理',success:'已完成'};
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const displayNumber = (n) => Number.isFinite(n) ? new Intl.NumberFormat('zh-CN',{maximumFractionDigits:1}).format(n) : '—';
let toastTimer;

function toast(message,error=false) {
  clearTimeout(toastTimer);
  $('#toast').textContent=message;
  $('#toast').className=`toast${error?' error':''}`;
  $('#toast').hidden=false;
  toastTimer=setTimeout(()=>{$('#toast').hidden=true;},4500);
}

async function api(path, options={}) {
  const headers=new Headers(options.headers || {});
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type','application/json');
  let response;
  try { response=await fetch(path,{...options,headers,credentials:'same-origin'}); }
  catch { throw new Error('暂时无法连接服务，请稍后重试'); }
  let data;
  try { data=await response.json(); } catch { data={detail:response.status===429?'请求过于频繁，请稍后再试':'服务器返回异常，请稍后重试'}; }
  if (!response.ok) {
    if(response.status===401 && !path.startsWith('/api/auth/')) { state.user=null; renderAccount(); }
    throw new Error(typeof data.detail==='string' ? data.detail : '输入格式不正确，请检查后重试');
  }
  return data;
}

function renderAccount() {
  $('#account-name').hidden=!state.user;
  $('#account-name').textContent=state.user?.username || '';
  $('#auth-open').hidden=!!state.user;
  $('#logout').hidden=!state.user;
}

function authMode(mode) {
  state.authMode=mode;
  $('#login-tab').classList.toggle('active',mode==='login');
  $('#register-tab').classList.toggle('active',mode==='register');
  $('#auth-title').textContent=mode==='login'?'欢迎回来。':'开始你的餐盘观察。';
  $('#auth-submit').textContent=mode==='login'?'登录工作台 ↗':'创建账号 ↗';
  $('#password').autocomplete=mode==='login'?'current-password':'new-password';
  $('#auth-error').textContent='';
}

function requireAuth(action) {
  if (state.user) return action();
  state.pending=action;
  if(!$('#auth-dialog').open) $('#auth-dialog').showModal();
}

function navigate(page) {
  state.page=page;
  for(const section of document.querySelectorAll('.page')) section.hidden=section.id!==`${page}-page`;
  for(const button of document.querySelectorAll('[data-page]')) button.classList.toggle('active',button.dataset.page===page);
  if(page==='history') loadHistory();
  window.scrollTo({top:0,behavior:'smooth'});
}

function selectFile(file) {
  if(!file) return;
  if(!['image/jpeg','image/png','image/webp'].includes(file.type)) return toast('请选择 JPG、PNG 或 WebP 图片',true);
  if(file.size>10*1024*1024) return toast('图片不能超过 10 MiB',true);
  if(state.preview) URL.revokeObjectURL(state.preview);
  state.file=file; state.preview=URL.createObjectURL(file);
  $('#upload-preview').src=state.preview;
  $('#upload-preview').hidden=false;
  $('#upload-placeholder').hidden=true;
  $('#file-caption').hidden=false;
  $('#file-caption').textContent=`${file.name} · ${(file.size/1024).toFixed(0)} KB`;
  $('#clear-upload').hidden=false;
  $('#analyze').disabled=false;
}

function clearUpload() {
  if(state.preview) URL.revokeObjectURL(state.preview);
  state.file=null; state.preview=null;
  $('#image-file').value=''; $('#upload-preview').removeAttribute('src');
  $('#upload-preview').hidden=true; $('#upload-placeholder').hidden=false;
  $('#file-caption').hidden=true; $('#clear-upload').hidden=true; $('#analyze').disabled=true;
}

async function submitUpload() {
  if(!state.file) return;
  const data=new FormData(); data.append('file',state.file);
  $('#analyze').disabled=true;
  try { const job=await api('/api/jobs',{method:'POST',body:data}); showJob(job,true); }
  catch(error) { toast(error.message,true); }
  finally { $('#analyze').disabled=!state.file; }
}

async function sample(id) {
  try {
    const job=await api('/api/jobs/from-sample',{method:'POST',body:JSON.stringify({sample_id:id,mode:'replay'})});
    showJob(job,true);
  } catch(error) { toast(error.message,true); }
}

async function loadSamples() {
  try {
    const list=await api('/api/samples');
    $('#sample-grid').innerHTML=list.map(item=>`<button class="sample-card" data-sample="${escapeHtml(item.id)}"><img src="${escapeHtml(item.image_url)}" alt="${escapeHtml(item.title)}"><span><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.description)}</p></span><span aria-hidden="true">↗</span></button>`).join('');
    for(const button of document.querySelectorAll('[data-sample]')) button.addEventListener('click',()=>requireAuth(()=>sample(button.dataset.sample)));
  } catch { $('#sample-grid').textContent='样例暂时不可用，请稍后刷新。'; }
}

function badge(status) { return `<span class="badge ${escapeHtml(status)}">${escapeHtml(statuses[status] || status)}</span>`; }

function renderMethod(job,method) {
  const a=method==='a', status=job[`${method}_status`], result=job[`${method}_result`];
  const header=`<div class="result-card-head"><div><h3>方案 ${a?'A · 看见轮廓':'B · 理解餐盘'}</h3><p class="route-name">${a?'YOLO-World + SAM':'多模态大模型'}</p></div>${badge(status)}</div>`;
  if(status==='failed') return header+`<div class="result-error"><span aria-hidden="true">⚑</span><strong>这次分析未完成</strong><p>${escapeHtml(job[`${method}_error`])}</p><p>失败没有被记为零热量。已成功的另一方案会保留。</p></div>`;
  if(status!=='success' || !result) return header+`<div class="result-wait">${status==='running'?'<span class="spinner" aria-label="处理中"></span>':'<span aria-hidden="true">◷</span>'}<strong>${status==='running'?(job.mode==='replay'?'正在读取历史结果':'正在观察餐盘'):'等待处理'}</strong><p>${job.mode==='replay'?'从已保存的真实实验记录中读取':'任务会在后台执行，你可以稍后从分析记录查看。'}</p></div>`;
  const total=result.total;
  const rows=result.dishes.length ? result.dishes.map(d=>`<tr><td>${escapeHtml(names[d.name] || d.name)}</td><td>${displayNumber(d.weight_g)} g</td><td>${displayNumber(d.kcal)}</td></tr>`).join('') : '<tr><td colspan="3">模型明确返回无可见食材</td></tr>';
  const seconds=Number.isFinite(result.seconds)?`${job.mode==='replay'?'原推理':'本次推理'} ${displayNumber(result.seconds)}s`:job.mode==='replay'?'历史结果':'';
  return header+`<img class="result-image" src="${escapeHtml(a?job.overlay_url:job.image_url)}?g=${job.generation}" alt="${a?'传统模型检测与分割':'相同输入照片'}"><div class="result-body"><div class="calories"><strong>${displayNumber(total.kcal)}</strong><span>kcal / 估算热量</span><small>${escapeHtml(seconds)}</small></div><div class="nutrition-row"><div><span>蛋白质</span><strong>${displayNumber(total.protein_g)} g</strong></div><div><span>脂肪</span><strong>${displayNumber(total.fat_g)} g</strong></div><div><span>碳水化合物</span><strong>${displayNumber(total.carb_g)} g</strong></div></div><table class="dish-table"><thead><tr><th>识别食材</th><th>估算重量</th><th>千卡</th></tr></thead><tbody>${rows}</tbody></table>${!a?`<details><summary>查看模型原始回复与来源</summary><pre>${escapeHtml(result.raw || '无原始文本')}</pre><p class="hint">模型：${escapeHtml(result.provenance?.model || '未知')} · ${job.mode==='replay'?'历史实验回放':'本次真实调用'}</p></details>`:''}</div>`;
}

function renderJob(job) {
  state.job=job;
  $('#comparison').hidden=false;
  $('#result-title').textContent=job.title;
  $('#result-mode').textContent=job.mode==='replay'?'历史样例回放 · 不调用模型 · 不作为新实验':'实时分析 · 同一输入照片 · 共用营养表';
  $('#job-status').className=`badge ${job.status}`;
  $('#job-status').textContent=statuses[job.status] || job.status;
  $('#result-a').innerHTML=renderMethod(job,'a');
  $('#result-b').innerHTML=renderMethod(job,'b');
  $('#result-note').textContent=job.note || '图像估重受角度、遮挡与食材厚度影响，结果不能替代实际称重。';
  $('#retry-job').hidden=!['failed','partial'].includes(job.status);
  $('#export-result').disabled=['queued','running'].includes(job.status);
  const stage=job.status==='queued'?0:job.a_status==='running'?1:job.b_status==='running'?2:3;
  [...$('#job-progress').children].forEach((el,i)=>el.classList.toggle('active',i<=stage));
}

function showJob(job,scroll=false) {
  clearTimeout(state.poll);
  if(state.page!=='workspace') navigate('workspace');
  renderJob(job);
  if(scroll) $('#comparison').scrollIntoView({behavior:'smooth',block:'start'});
  if(['queued','running'].includes(job.status)) state.poll=setTimeout(()=>pollJob(job.id),1200);
}

async function pollJob(id) {
  if(!state.user || state.job?.id!==id) return;
  try {
    const job=await api(`/api/jobs/${id}`);
    if(state.job?.id===id) {renderJob(job);if(['queued','running'].includes(job.status)) state.poll=setTimeout(()=>pollJob(id),1500);}
  } catch(error) { toast(error.message,true); if(state.user) state.poll=setTimeout(()=>pollJob(id),5000); }
}

async function openJob(id) {
  try { showJob(await api(`/api/jobs/${id}`),true); }
  catch(error) { toast(error.message,true); }
}

async function loadHistory() {
  if(!state.user) {
    $('#history-total').textContent='分析记录';$('#history-list').innerHTML='<div class="empty-state">登录后，你的照片与分析结果会保存在这里。<br><button class="text-button" id="history-login">登录 / 注册 ↗</button></div>';
    $('#history-login').addEventListener('click',()=>requireAuth(loadHistory));
    $('#history-page-label').textContent='';$('#history-prev').disabled=true;$('#history-next').disabled=true;
    return;
  }
  try {
    const data=await api(`/api/jobs?limit=10&offset=${state.offset}`);state.total=data.total;
    $('#history-total').textContent=`共 ${data.total} 条记录`;
    $('#history-list').innerHTML=data.items.length?data.items.map(job=>`<div class="history-row"><img src="${escapeHtml(job.image_url)}" alt="餐盘缩略图"><div><h3>${escapeHtml(job.title)}</h3><p>${new Date(job.created_at).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})} · ${job.mode==='replay'?'历史回放':'实时分析'}</p></div>${badge(job.status)}<div class="history-cal"><small>方案 A</small>${escapeHtml(statuses[job.a_status])}</div><div class="history-cal"><small>方案 B</small>${escapeHtml(statuses[job.b_status])}</div><div class="history-actions"><button class="text-button" data-open-job="${job.id}">查看 ↗</button><button class="text-button delete-button" data-delete-job="${job.id}" ${['queued','running'].includes(job.status)?'disabled':''}>删除</button></div></div>`).join(''):'<div class="empty-state">还没有分析记录。<br>上传一张照片，或先体验内置样例。</div>';
    for(const el of document.querySelectorAll('[data-open-job]')) el.addEventListener('click',()=>openJob(el.dataset.openJob));
    for(const el of document.querySelectorAll('[data-delete-job]')) el.addEventListener('click',()=>deleteJob(el.dataset.deleteJob));
    $('#history-prev').disabled=state.offset===0;$('#history-next').disabled=state.offset+10>=data.total;
    $('#history-page-label').textContent=data.total?`${Math.floor(state.offset/10)+1} / ${Math.ceil(data.total/10)}`:'';
  } catch(error) { toast(error.message,true); }
}

async function deleteJob(id) {
  if(!confirm('删除这条记录及其照片？此操作无法撤销。')) return;
  try {
    await api(`/api/jobs/${id}`,{method:'DELETE'});
    if(state.job?.id===id) {clearTimeout(state.poll);state.job=null;$('#comparison').hidden=true;}
    if(state.offset && state.total-state.offset===1) state.offset=Math.max(0,state.offset-10);
    await loadHistory();toast('记录已删除');
  } catch(error) { toast(error.message,true); }
}

async function refreshHealth() {
  try {
    const health=await api('/api/health');
    $('#service-dot').classList.toggle('ready',health.status==='ok');
    $('#service-label').textContent=health.status!=='ok'?'后台任务服务暂不可用':!health.local_models?'服务在线 · 传统模型待准备':!health.vlm_configured?'服务在线 · 大模型待配置':'分析服务在线 · 双方案已配置';
  } catch { $('#service-label').textContent='服务暂时不可用';$('#service-dot').classList.remove('ready'); }
}

for(const el of document.querySelectorAll('[data-page]')) el.addEventListener('click',()=>navigate(el.dataset.page));
for(const el of document.querySelectorAll('[data-close]')) el.addEventListener('click',()=>{$(`#${el.dataset.close}`).close();if(el.dataset.close==='auth-dialog') state.pending=null;});
$('#auth-open').addEventListener('click',()=>requireAuth(()=>{}));
$('#login-tab').addEventListener('click',()=>authMode('login'));
$('#register-tab').addEventListener('click',()=>authMode('register'));
$('#auth-form').addEventListener('submit',async event=>{
  event.preventDefault();$('#auth-error').textContent='';$('#auth-submit').disabled=true;
  const data=Object.fromEntries(new FormData(event.target));
  try {
    state.user=await api(`/api/auth/${state.authMode}`,{method:'POST',body:JSON.stringify(data)});
    event.target.reset();renderAccount();$('#auth-dialog').close();
    const pending=state.pending;state.pending=null;
    if(pending) await pending();else if(state.page==='history') await loadHistory();
    toast(state.authMode==='register'?'账号已创建，欢迎来到 Canteen Lab':'已登录工作台');
  } catch(error) { $('#auth-error').textContent=error.message; }
  finally { $('#auth-submit').disabled=false; }
});
$('#logout').addEventListener('click',async()=>{
  try { await api('/api/auth/logout',{method:'POST'});state.user=null;state.job=null;state.pending=null;clearTimeout(state.poll);$('#comparison').hidden=true;renderAccount();if(state.page==='history') loadHistory();toast('已退出登录'); }
  catch(error) { toast(error.message,true); }
});
$('#image-file').addEventListener('change',event=>selectFile(event.target.files[0]));
$('#dropzone').addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();$('#image-file').click();}});
for(const name of ['dragenter','dragover']) $('#dropzone').addEventListener(name,event=>{event.preventDefault();$('#dropzone').classList.add('dragging');});
for(const name of ['dragleave','drop']) $('#dropzone').addEventListener(name,event=>{event.preventDefault();$('#dropzone').classList.remove('dragging');});
$('#dropzone').addEventListener('drop',event=>selectFile(event.dataTransfer.files[0]));
$('#clear-upload').addEventListener('click',clearUpload);
$('#analyze').addEventListener('click',()=>requireAuth(submitUpload));
$('#refresh-health').addEventListener('click',refreshHealth);
$('#refresh-history').addEventListener('click',loadHistory);
$('#history-prev').addEventListener('click',()=>{state.offset=Math.max(0,state.offset-10);loadHistory();});
$('#history-next').addEventListener('click',()=>{state.offset+=10;loadHistory();});
$('#retry-job').addEventListener('click',async()=>{
  if(!state.job) return;$('#retry-job').disabled=true;
  try {showJob(await api(`/api/jobs/${state.job.id}/retry`,{method:'POST'}));}
  catch(error) {toast(error.message,true);}
  finally {$('#retry-job').disabled=false;}
});
$('#edit-record').addEventListener('click',()=>{
  if(!state.job) return;$('#edit-form [name="title"]').value=state.job.title;$('#edit-form [name="note"]').value=state.job.note;$('#edit-dialog').showModal();
});
$('#edit-form').addEventListener('submit',async event=>{
  event.preventDefault();if(!state.job) return;
  try {renderJob(await api(`/api/jobs/${state.job.id}`,{method:'PATCH',body:JSON.stringify(Object.fromEntries(new FormData(event.target)))}));$('#edit-dialog').close();toast('记录已更新');}
  catch(error) {toast(error.message,true);}
});
$('#export-result').addEventListener('click',()=>{
  if(!state.job) return;
  const url=URL.createObjectURL(new Blob([JSON.stringify(state.job,null,2)],{type:'application/json'}));
  const anchor=document.createElement('a');anchor.href=url;anchor.download=`canteen-${state.job.id}.json`;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&state.page==='history'&&state.user) loadHistory();});
async function boot() {
  try {state.user=await api('/api/auth/me');} catch {state.user=null;}
  renderAccount();loadSamples();refreshHealth();
}
boot();
