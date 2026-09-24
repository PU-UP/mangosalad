const $ = s => document.querySelector(s);
let current = null, tab = 'desk', busy = false, setupToken = '', toastTimer;
function toast(text) { $('#toast').textContent=text; $('#toast').style.display='block'; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('#toast').style.display='none',5500); }
async function api(path, method='GET', body) {
  const r=await fetch('/api/'+path,{method,headers:{'Content-Type':'application/json','X-Mango-Request':'1'},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await r.json();
  if(!r.ok){if(r.status===401 && path!=='login'){showLogin(true);} const e=new Error(data.error||'暂时无法连接，请稍后重试。');e.status=r.status;throw e;}
  return data;
}
function el(tag, cls, text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;}
function author(name){return name==='you'?'你':name;}
function date(ts){return new Date(ts*1000).toLocaleDateString('zh-CN',{month:'numeric',day:'numeric'});}
function showLogin(configured){$('#login').hidden=false;$('#workspace').hidden=true;$('#login-title').textContent=configured?'欢迎回来。':'先给这里一把钥匙。';$('#login-hint').textContent=configured?'登录后，接着上次的事。':setupToken?'设置一个至少 10 个字符的密码，以后直接登录。':'请从首次登录链接进入，完成密码设置。';$('#password').autocomplete=configured?'current-password':'new-password';}
async function boot(){
  if(location.hash.startsWith('#enable-reminders=')){const token=decodeURIComponent(location.hash.slice(18));history.replaceState(null,'','/');try{await api('reminder-access','POST',{token});toast('此设备已启用提醒，无需密码。');}catch(e){toast(e.message);}}
  if(location.hash.startsWith('#setup=')){setupToken=decodeURIComponent(location.hash.slice(7));history.replaceState(null,'','/');}
  try{const s=await api('session');if(!s.authenticated){showLogin(s.configured);return;}$('#logout').hidden=!!s.public;$('#login').hidden=true;$('#workspace').hidden=false;$('#today').textContent=new Date().toLocaleDateString('zh-CN',{month:'long',day:'numeric',weekday:'long'});await route();}
  catch(e){toast(e.message);}
}
$('#login-form').onsubmit=async e=>{e.preventDefault();const b=e.submitter;b.disabled=true;$('#login-error').textContent='';try{await api('login','POST',{password:$('#password').value,setup:setupToken});$('#password').value='';setupToken='';await boot();}catch(e){$('#login-error').textContent=e.message;}finally{b.disabled=false;}};
$('#logout').onclick=async()=>{try{await api('logout','POST',{});location.hash='';current=null;$('#cards').replaceChildren();$('#items').replaceChildren();$('#page-frame').srcdoc='';await boot();}catch(e){toast(e.message);}};
async function route(){
  if($('#workspace').hidden)return;
  try{
    const id=new URLSearchParams(location.hash.slice(1)).get('page');
    if(id){current=await api('pages/'+encodeURIComponent(id));$('#shelf').hidden=true;$('#detail').hidden=false;renderPage();}
    else{current=null;$('#page-frame').srcdoc='';$('#detail').hidden=true;$('#shelf').hidden=false;await loadShelf();}
  }catch(e){toast(e.message);if(e.status===404)location.hash='';}
}
window.addEventListener('hashchange',()=>location.hash.startsWith('#enable-reminders=')?boot():route());
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{tab=b.dataset.tab;document.querySelectorAll('[data-tab]').forEach(x=>x.removeAttribute('aria-current'));b.setAttribute('aria-current','page');loadShelf().catch(e=>toast(e.message));});
async function loadShelf(){
  const {pages}=await api('pages');
  const visible=pages.filter(p=>tab==='archive'?p.archived:tab==='all'?true:!p.archived).sort((a,b)=>(b.pinned-a.pinned)||(b.updated-a.updated));
  $('#count').textContent=visible.length+' 个页面';$('#cards').replaceChildren();$('#empty').hidden=!!visible.length;
  for(const p of visible){
    const card=el('a','card');card.href='#page='+p.id;card.dataset.author=p.author;
    const top=el('div','card-top');top.append(el('span','',p.kind==='checklist'?'清单':'自定义页面'),el('span','',p.archived?'已收起':p.pinned?'留着':'最近'));card.append(top,el('h2','',p.title));
    if(p.kind==='checklist'){const ul=el('ul','preview');p.preview.forEach(t=>ul.append(el('li','',t)));if(!p.total)ul.append(el('li','','还没有内容'));else if(p.done===p.total)ul.append(el('li','','都完成了'));card.append(ul);}
    const bottom=el('div','card-bottom');bottom.append(el('span','',p.kind==='checklist'?`${p.done} / ${p.total} 已完成`:'打开看看'),el('span','',`${author(p.author)} · ${date(p.updated)}`));card.append(bottom);$('#cards').append(card);
  }
}
function createDialog(){$('#create-form').reset();$('#create-dialog').showModal();$('#new-title').focus();}
function askText(title,value,max=500){
  const dialog=$('#edit-dialog'),input=$('#edit-value');$('#edit-heading').textContent=title;input.value=value;input.maxLength=max;dialog.returnValue='';dialog.showModal();input.focus();input.select();
  return new Promise(resolve=>{dialog.onclose=()=>resolve(dialog.returnValue==='save'?input.value:null);});
}
$('#edit-cancel').onclick=()=>$('#edit-dialog').close('cancel');
$('#edit-form').onsubmit=e=>{e.preventDefault();if(!$('#edit-value').value.trim())return;$('#edit-dialog').close('save');};
$('#new-page').onclick=createDialog;$('#empty-create').onclick=createDialog;$('#create-cancel').onclick=()=>$('#create-dialog').close();
$('#create-form').onsubmit=async e=>{e.preventDefault();e.submitter.disabled=true;try{const p=await api('pages','POST',{title:$('#new-title').value.trim(),kind:'checklist',pinned:$('#new-pinned').checked,state:{items:[]}});$('#create-dialog').close();location.hash='page='+p.id;}catch(e){toast(e.message);}finally{e.submitter.disabled=false;}};
async function change(patch, redraw=true){
  if(busy)throw new Error('上一项正在保存，请稍等。');
  const pageId=current.id;
  busy=true;$('#save-state').textContent='正在保存…';$('#canvas-status').textContent='正在保存…';
  try{const updated=await api('pages/'+pageId,'PATCH',{revision:current.revision,...patch});if(current?.id!==pageId)return updated;current=updated;if(redraw)renderPage();$('#save-state').textContent='已保存';$('#canvas-status').textContent='已保存';return updated;}
  catch(e){$('#save-state').textContent='尚未保存';$('#canvas-status').textContent=e.message;if(e.status===409&&current?.id===pageId){const updated=await api('pages/'+pageId);if(current?.id===pageId){current=updated;if(redraw)renderPage();}}throw e;}
  finally{busy=false;}
}
function renderPage(){
  const p=current;document.title=p.title+' · mangosalad';$('#page-title').textContent=p.title;$('#page-kind').textContent=p.kind==='checklist'?'清单':'自定义页面';$('#page-meta').textContent=`${author(p.author)} 最近修改 · ${date(p.updated)}`;$('#pin').textContent=p.pinned?'取消留着':'留在桌面';$('#archive').textContent=p.archived?'放回桌面':'用完了';$('#checklist').hidden=p.kind!=='checklist';$('#canvas').hidden=p.kind!=='canvas';
  if(taskPageId!==p.id)for(const id of ['task-agent','task-time','task-instructions','task-submit'])$('#'+id).disabled=true;
  refreshTasks(p.id).catch(e=>toast(e.message));
  if(p.kind==='canvas'){renderCanvas();return;}
  const items=p.state.items||[],done=items.filter(i=>i.done).length;$('#progress-text').textContent=`${done} / ${items.length} 已完成`;$('#progress').max=items.length||1;$('#progress').value=done;$('#items').replaceChildren();
  for(const item of items){
    const row=el('div','item'+(item.done?' done':'')),label=el('label'),box=el('input');box.type='checkbox';box.checked=!!item.done;
    row.dataset.itemId=item.id;
    const handle=el('button','quiet drag-handle','⠿');handle.type='button';handle.setAttribute('aria-label','排序 '+item.text);handle.title='拖动排序，也可以使用上下方向键';
    enableReorder(handle,row,item.id);
    box.onchange=async()=>{const desired=box.checked;box.disabled=true;try{await change({state:{...current.state,items:current.state.items.map(x=>x.id===item.id?{...x,done:desired}:x)}});}catch(e){box.checked=!!item.done;toast(e.message);}finally{box.disabled=false;}};
    const edit=el('button','quiet item-edit','编辑');edit.setAttribute('aria-label','编辑 '+item.text);edit.onclick=async()=>{const text=await askText('修改这一项',item.text);if(text===null)return;if(!text.trim()){toast('内容不能为空');return;}if(text.trim().length>500){toast('每项最多 500 个字符');return;}try{await change({state:{...current.state,items:current.state.items.map(x=>x.id===item.id?{...x,text:text.trim()}:x)}});}catch(e){toast(e.message);}};
    label.append(box,el('span','',item.text));const remove=el('button','quiet','×');remove.setAttribute('aria-label','移除 '+item.text);remove.onclick=async()=>{if(!confirm('移除“'+item.text+'”？'))return;try{await change({state:{...current.state,items:current.state.items.filter(x=>x.id!==item.id)}});}catch(e){toast(e.message);}};row.append(handle,label,edit,remove);$('#items').append(row);
  }

}
function enableReorder(handle,row,id){
  let dragging=false;
  const pageId=current.id;
  async function saveOrder(ids){
    if(current?.id!==pageId)return;
    const items=current.state.items;
    if(ids.every((id,i)=>id===items[i]?.id))return;
    try{await change({state:{...current.state,items:ids.map(id=>items.find(x=>x.id===id))}});toast('顺序已保存');}
    catch(e){if(current?.id===pageId)renderPage();toast(e.message);}
  }
  handle.onkeydown=async e=>{
    if(!['ArrowUp','ArrowDown'].includes(e.key))return;e.preventDefault();
    if(busy){toast('上一项正在保存，请稍等。');return;}
    const ids=current.state.items.map(x=>x.id),from=ids.indexOf(id),to=from+(e.key==='ArrowUp'?-1:1);
    if(to<0||to>=ids.length)return;[ids[from],ids[to]]=[ids[to],ids[from]];
    await saveOrder(ids);$('#items').querySelector('[data-item-id="'+CSS.escape(id)+'"] .drag-handle')?.focus();
  };
  handle.onpointerdown=e=>{
    if(e.button!==0||busy)return;
    dragging=true;handle.setPointerCapture(e.pointerId);row.classList.add('dragging');e.preventDefault();
  };
  handle.onpointermove=e=>{
    if(!dragging||!row.isConnected)return;
    const siblings=[...$('#items').children].filter(x=>x!==row);
    const next=siblings.find(x=>e.clientY<x.getBoundingClientRect().top+x.getBoundingClientRect().height/2)||null;
    if(row.nextElementSibling!==next){$('#items').insertBefore(row,next);handle.setPointerCapture(e.pointerId);}
    if(e.clientY<70)window.scrollBy(0,-16);else if(e.clientY>window.innerHeight-70)window.scrollBy(0,16);
  };
  handle.onpointerup=()=>{if(!dragging)return;dragging=false;row.classList.remove('dragging');saveOrder([...$('#items').children].map(x=>x.dataset.itemId));};
  handle.onpointercancel=()=>{if(!dragging)return;dragging=false;if(current?.id===pageId)renderPage();};
}
$('#add-form').onsubmit=async e=>{e.preventDefault();const input=$('#new-item'),text=input.value.trim();if(!text)return;e.submitter.disabled=true;try{await change({state:{...current.state,items:[...(current.state.items||[]),{id:crypto.randomUUID(),text,done:false}]}});input.value='';input.focus();}catch(e){toast(e.message);}finally{e.submitter.disabled=false;}};
$('#pin').onclick=()=>change({pinned:!current.pinned,archived:false}).catch(e=>toast(e.message));
$('#archive').onclick=async()=>{try{await change({archived:!current.archived});location.hash='';}catch(e){toast(e.message);}};
$('#rename').onclick=async()=>{const title=await askText('新的标题',current.title,120);if(title?.trim())change({title:title.trim()}).catch(e=>toast(e.message));};
$('#delete').onclick=async()=>{if(!confirm('永久删除“'+current.title+'”？网页和其中的数据都会删除。'))return;try{await api('pages/'+current.id,'DELETE',{revision:current.revision});location.hash='';toast('已删除');}catch(e){toast(e.message);}};
function renderCanvas(){
  const frame=$('#page-frame');
  frame.removeAttribute('srcdoc');
  frame.src='/api/pages/'+current.id+'/render?v='+current.revision;
  frame.onload=()=>frame.contentWindow.postMessage({type:'mango:init',state:current.state,revision:current.revision},'*');
  $('#canvas-status').textContent='';
}
window.addEventListener('message',async event=>{
  if(!current||current.kind!=='canvas'||event.source!==$('#page-frame').contentWindow)return;
  const m=event.data;if(!m||typeof m!=='object')return;
  if(m.type==='mango:ready')event.source.postMessage({type:'mango:init',state:current.state,revision:current.revision},'*');
  if(m.type==='mango:save'){
    const source=event.source;
    try{if(m.revision!==current.revision)throw new Error('页面已变化，请读取最新状态后重试。');const updated=await change({state:m.state},false);source.postMessage({type:'mango:saved',state:updated.state,revision:updated.revision},'*');}
    catch(e){source.postMessage({type:'mango:error',error:e.message,state:current?.state,revision:current?.revision},'*');toast(e.message);}
  }
});
boot();
let currentTask=null,taskPageId=null;
const taskLabels={queued:'等待指定时间',dispatching:'正在联系 Agent',running:'Agent 已接单，处理中',cancelling:'正在取消',cancelled:'已取消',completed:'已完成',needs_input:'需要你回复',failed:'未完成',interrupted:'处理被中断'};
function taskTime(ts){return new Date(ts*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false});}
async function refreshTasks(pageId){
  const data=await api('pages/'+pageId+'/tasks');if(current?.id!==pageId)return;
  const task=data.tasks[0]||null,changed=taskPageId!==pageId||currentTask?.id!==task?.id;
  taskPageId=pageId;currentTask=task;
  if(changed){$('#task-agent').value=task?.agent||'lychee';$('#task-time').value=task?new Date(task.run_at*1000+8*3600000).toISOString().slice(0,16):'';$('#task-instructions').value=task?.instructions||'';}
  const active=task&&['queued','dispatching','running','cancelling'].includes(task.status);
  for(const id of ['task-agent','task-time','task-instructions'])$('#'+id).disabled=!!active||!!current.archived;
  $('#task-submit').disabled=!!active||!data.enabled||!!current.archived;
  $('#task-submit').textContent=active?'已确定交给 '+task.agent:'确定交给 Agent';
  $('#task-access-hint').hidden=data.enabled;
  $('#task-cancel').hidden=!task||!['queued','dispatching','running','cancelling','needs_input'].includes(task.status);
  $('#task-cancel').disabled=!data.enabled||task?.status==='cancelling';
  $('#task-status').textContent=task?`${task.agent} · ${taskTime(task.run_at)} · ${taskLabels[task.status]||task.status}`:'未安排；填写后点击确定才会交给 Agent。';
  if(task?.status==='completed'&&task.kind==='reminder')$('#task-status').textContent=`${task.agent} · 已处理提醒`;
  if(task?.result)$('#task-status').textContent+=task.delivered?' · 飞书已发送':' · 飞书发送待确认';
  $('#task-error').textContent=task?.error||'';
  $('#task-result').hidden=!task?.result;$('#task-result').textContent=task?.result||'';
}
$('#task-form').onsubmit=async e=>{
  e.preventDefault();const page=current;e.submitter.disabled=true;$('#task-error').textContent='';
  const value=$('#task-time').value;
  try{await api('pages/'+page.id+'/tasks','POST',{page_revision:page.revision,agent:$('#task-agent').value,run_at:value?value+':00+08:00':null,instructions:$('#task-instructions').value.trim()});await refreshTasks(page.id);toast('整份任务已确认提交');}
  catch(e){$('#task-error').textContent=e.message;e.submitter.disabled=false;}
};
$('#task-cancel').onclick=async e=>{
  const task=currentTask;if(!task)return;e.target.disabled=true;
  try{await api('tasks/'+task.id,'DELETE',{revision:task.revision});await refreshTasks(task.page_id);toast('已提交取消');}
  catch(e){toast(e.message);await refreshTasks(task.page_id);}
};
setInterval(()=>{if(current&&!document.hidden)refreshTasks(current.id).catch(()=>{});},5000);
