const $ = s => document.querySelector(s);
let current = null, tab = 'all', busy = false, setupToken = '', toastTimer;
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
let shelfRevision=1, shelfSaving=false, focusPage=null;
async function loadShelf(){
  const data=await api('pages');shelfRevision=data.order_revision;
  const visible=data.pages.filter(p=>tab==='archive'?p.archived:!p.archived&&(tab!=='focus'||p.needs_focus));
  $('#shelf-hint').textContent=tab==='focus'?`显示关注日期不晚于今天（${data.focus_through}，北京时间）的未结束页面。`:'拖动卡片左上角调整顺序；点击日期设置关注时间。';
  $('#count').textContent=visible.length+' 个页面';$('#cards').replaceChildren();$('#empty').hidden=!!visible.length;
  $('#empty h2').textContent=tab==='focus'?'近期没有需要关注的页面':'留一点空白。';
  $('#empty p').textContent=tab==='focus'?'在「全部」中给页面设置关注日期，到时会自动出现在这里。':'创建一张清单，或让 lychee、olive 为你制作页面。';
  for(const p of visible){
    const card=el('article','card');card.dataset.pageId=p.id;card.dataset.author=p.author;
    const top=el('div','card-top'),handle=el('button','quiet card-drag','⠿');handle.type='button';handle.setAttribute('aria-label','排序 '+p.title);handle.title='拖动排序，也可用方向键移动';
    const focus=el('button','quiet card-focus',p.focus_date?`${p.focus_date.slice(5).replace('-','/')} 关注`:'设置关注');focus.type='button';focus.setAttribute('aria-label','关注日期 '+p.title);focus.onclick=()=>openFocus(p.id).catch(e=>toast(e.message));
    top.append(handle,el('span','card-kind',p.pinned?'留着':p.kind==='checklist'?'清单':'页面'),focus);card.append(top);
    const link=el('a','card-open');link.href='#page='+p.id;link.append(el('h2','',p.title));
    if(p.kind==='checklist'){const ul=el('ul','preview');p.preview.slice(0,2).forEach(t=>ul.append(el('li','',t)));if(!p.total)ul.append(el('li','','还没有内容'));else if(p.done===p.total)ul.append(el('li','','都完成了'));link.append(ul);}
    const bottom=el('div','card-bottom');bottom.append(el('span','',p.kind==='checklist'?`${p.done} / ${p.total} 已完成`:'打开看看'),el('span','',`${author(p.author)} · ${date(p.updated)}`));link.append(bottom);card.append(link);$('#cards').append(card);bindCardDrag(card,handle);
  }
}
async function saveShelfOrder(ids){
  if(shelfSaving)return;
  shelfSaving=true;
  try{await api('pages/order','POST',{revision:shelfRevision,ids});toast('桌面顺序已保存');}
  catch(e){toast(e.message);}
  finally{shelfSaving=false;await loadShelf();}
}
function bindCardDrag(card,handle){
  let moving=false,original=[];
  const ids=()=>[...$('#cards').children].map(x=>x.dataset.pageId);
  handle.onkeydown=e=>{
    if(!['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.key)||shelfSaving)return;
    e.preventDefault();const order=ids(),i=order.indexOf(card.dataset.pageId),j=i+(['ArrowUp','ArrowLeft'].includes(e.key)?-1:1);
    if(j<0||j>=order.length)return;[order[i],order[j]]=[order[j],order[i]];
    saveShelfOrder(order).then(()=>$('#cards').querySelector(`[data-page-id="${card.dataset.pageId}"] .card-drag`)?.focus());
  };
  handle.onpointerdown=e=>{if(e.button!==0||shelfSaving)return;e.preventDefault();moving=true;original=ids();card.classList.add('card-moving');handle.setPointerCapture(e.pointerId);};
  handle.onpointermove=e=>{
    if(!moving)return;
    const target=document.elementFromPoint(e.clientX,e.clientY)?.closest('#cards .card');
    if(target&&target!==card){const children=[...$('#cards').children];$('#cards').insertBefore(card,children.indexOf(card)<children.indexOf(target)?target.nextSibling:target);handle.setPointerCapture(e.pointerId);}
    if(e.clientY<70)window.scrollBy(0,-16);else if(e.clientY>innerHeight-70)window.scrollBy(0,16);
  };
  handle.onpointerup=()=>{if(!moving)return;moving=false;card.classList.remove('card-moving');const next=ids();if(next.join()!==original.join())saveShelfOrder(next);};
  handle.onpointercancel=()=>{moving=false;card.classList.remove('card-moving');loadShelf().catch(e=>toast(e.message));};
}
async function openFocus(id){focusPage=await api('pages/'+id);$('#focus-title').textContent=focusPage.title;$('#focus-date').value=focusPage.focus_date||'';$('#focus-dialog').showModal();}
$('#focus-date-button').onclick=()=>openFocus(current.id).catch(e=>toast(e.message));
$('#focus-cancel').onclick=()=>$('#focus-dialog').close();
$('#focus-clear').onclick=()=>{$('#focus-date').value='';};
$('#focus-form').onsubmit=async e=>{
  e.preventDefault();e.submitter.disabled=true;
  try{const updated=await api('pages/'+focusPage.id,'PATCH',{revision:focusPage.revision,focus_date:$('#focus-date').value||null});$('#focus-dialog').close();if(current?.id===updated.id){current=updated;renderPage();}else await loadShelf();toast('关注日期已保存');}
  catch(error){toast(error.message);if(error.status===409){focusPage=await api('pages/'+focusPage.id);}}
  finally{e.submitter.disabled=false;}
};
function createDialog(){$('#create-form').reset();$('#create-dialog').showModal();$('#new-title').focus();}
function askText(title,value,max=500){
  const dialog=$('#edit-dialog'),input=$('#edit-value');$('#edit-heading').textContent=title;input.value=value;input.maxLength=max;dialog.returnValue='';dialog.showModal();input.focus();input.select();
  return new Promise(resolve=>{dialog.onclose=()=>resolve(dialog.returnValue==='save'?input.value:null);});
}
$('#edit-cancel').onclick=()=>$('#edit-dialog').close('cancel');
$('#edit-form').onsubmit=e=>{e.preventDefault();if(!$('#edit-value').value.trim())return;$('#edit-dialog').close('save');};
$('#new-page').onclick=createDialog;$('#empty-create').onclick=createDialog;$('#create-cancel').onclick=()=>$('#create-dialog').close();
$('#create-form').onsubmit=async e=>{e.preventDefault();e.submitter.disabled=true;try{const p=await api('pages','POST',{title:$('#new-title').value.trim(),kind:'checklist',pinned:$('#new-pinned').checked,focus_date:$('#new-focus-date').value||null,state:{items:[]}});$('#create-dialog').close();location.hash='page='+p.id;}catch(e){toast(e.message);}finally{e.submitter.disabled=false;}};
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
  $('#focus-date-button').textContent=p.focus_date?`${p.focus_date} 关注`:'设置关注日期';
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
let currentTask=null,taskPageId=null,taskSubmitting=false,historySignature='',taskHistoryEnabled=false;
const taskLabels={waiting:'待处理',done:'已完成',cancelled:'已取消'};
function taskTime(ts){return new Date(ts*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false});}
function clearTaskDraft(){$('#task-form').reset();$('#task-error').textContent='';}
function renderTaskHistory(tasks,pageId){
  const signature=pageId+taskHistoryEnabled+JSON.stringify(tasks);if(signature===historySignature)return;
  const opened=new Set([...document.querySelectorAll('#task-history-list details[open]')].map(x=>x.dataset.taskId));
  historySignature=signature;const list=$('#task-history-list');list.replaceChildren();
  if(!tasks.length){list.append(el('p','muted','还没有安排。提交后会在这里保留进展和结果。'));return;}
  for(const task of tasks){
    const record=el('details','task-record');record.dataset.taskId=task.id;record.open=opened.has(task.id);
    const summary=el('summary','');summary.append(el('span','',`${task.agent} · ${taskTime(task.run_at)}`),el('span','task-record-status',taskLabels[task.status]||task.status));record.append(summary);
    const body=el('div','task-record-body');
    body.append(el('p','task-request',task.instructions||'按当时确认的整页内容处理。'));
    const steps=el('ul','task-timeline');steps.append(el('li','',`${taskTime(task.created)} · 已确认提交`));
    if(task.acknowledged)steps.append(el('li','',`${taskTime(task.acknowledged)} · Agent 已接单`));
    if(task.status!=='waiting')steps.append(el('li','',`${taskTime(task.updated)} · ${taskLabels[task.status]||task.status}`));
    body.append(steps);
    if(task.result){body.append(el('div','task-result',task.result));body.append(el('p','muted',task.delivered?'飞书已发送':'飞书发送待确认'));}
    if(task.error)body.append(el('p','error',task.error));
    if(task.status==='done'&&['reminder','discussion'].includes(task.kind))body.append(el('p','muted','本次联系已完成；后续在飞书继续交流，不追踪回复状态。'));
    if(task.status==='waiting'&&!task.active){
      body.append(el('p','muted','本次尚未完成；可核对结果后重新安排，或取消此记录。'));
      if(task.can_cancel){const cancel=el('button','quiet danger','取消这次安排');cancel.type='button';cancel.disabled=!taskHistoryEnabled;cancel.onclick=async()=>{cancel.disabled=true;try{await api('tasks/'+task.id,'DELETE',{revision:task.revision});await refreshTasks(pageId);}catch(e){toast(e.message);cancel.disabled=false;}};body.append(cancel);}
    }
    record.append(body);list.append(record);
  }
}
async function refreshTasks(pageId){
  const data=await api('pages/'+pageId+'/tasks');if(current?.id!==pageId)return;
  if(taskPageId!==pageId){clearTaskDraft();historySignature='';}
  taskPageId=pageId;
  taskHistoryEnabled=data.enabled;
  currentTask=data.tasks.find(t=>t.active)||null;
  for(const id of ['task-agent','task-time','task-instructions'])$('#'+id).disabled=!!current.archived||taskSubmitting;
  $('#task-submit').disabled=!!currentTask||!data.enabled||!!current.archived||taskSubmitting;
  $('#task-submit').textContent=currentTask?'当前安排结束或取消后可提交':'确定交给 Agent';
  $('#task-access-hint').hidden=data.enabled;
  $('#task-cancel').hidden=!currentTask;
  $('#task-cancel').disabled=!data.enabled;
  $('#task-status').textContent=currentTask?`${currentTask.agent} · ${taskTime(currentTask.run_at)} · ${taskLabels[currentTask.status]}。可以先填写下一次安排。`:'填写新的安排并确认；此前的进展和结果保留在下方历史中。';
  renderTaskHistory(data.tasks,pageId);
}
$('#task-form').onsubmit=async e=>{
  e.preventDefault();if(taskSubmitting)return;const page=current;taskSubmitting=true;e.submitter.disabled=true;$('#task-error').textContent='';
  const value=$('#task-time').value;
  try{
    await api('pages/'+page.id+'/tasks','POST',{page_revision:page.revision,agent:$('#task-agent').value,run_at:value?value+':00+08:00':null,instructions:$('#task-instructions').value.trim()});
    if(current?.id===page.id)clearTaskDraft();
    toast('已提交，进展已记入历史');
  }catch(error){if(current?.id===page.id)$('#task-error').textContent=error.message;}
  finally{taskSubmitting=false;await refreshTasks(page.id).catch(error=>toast(error.message));}
};
$('#task-cancel').onclick=async e=>{
  const task=currentTask;if(!task)return;e.target.disabled=true;
  try{await api('tasks/'+task.id,'DELETE',{revision:task.revision});await refreshTasks(task.page_id);toast('已提交取消');}
  catch(e){toast(e.message);await refreshTasks(task.page_id);}
};
setInterval(()=>{if(current&&!document.hidden)refreshTasks(current.id).catch(()=>{});},5000);
