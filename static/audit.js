'use strict';
const el=id=>document.getElementById(id);
let source='status',offset=0;
async function api(path,body){
  const options={credentials:'same-origin',cache:'no-store'};
  if(body!==undefined)Object.assign(options,{method:'POST',headers:{'Content-Type':'application/json','X-Mango-Request':'1'},body:JSON.stringify(body)});
  const r=await fetch('/api/audit/'+path,options);
  const value=await r.json().catch(()=>({error:'请求失败'}));
  if(r.status===401){el('viewer').hidden=true;el('login').hidden=false;el('output').textContent='';}
  if(!r.ok)throw new Error(value.error||'请求失败');
  return value;
}
async function load(){
  el('message').textContent='读取中…';
  try{
    const value=await api(source+'?offset='+offset+'&limit=5');
    el('output').textContent=JSON.stringify(value,null,2);
    el('viewer').hidden=false;el('login').hidden=true;
    el('page').textContent='偏移 '+offset+' · 每页最多 5 条';
    el('previous').disabled=offset===0;el('next').disabled=offset>=10000;
    el('message').textContent='已读取。会话最长 12 小时；到期后需要本人重新登录。';
  }catch(e){el('message').textContent=e.message;}
}
el('login').addEventListener('submit',async e=>{
  e.preventDefault();const button=e.submitter;button.disabled=true;
  try{await api('login',{password:el('password').value});el('password').value='';await load();}
  catch(error){el('password').value='';el('message').textContent=error.message;}
  finally{button.disabled=false;}
});
document.querySelectorAll('[data-source]').forEach(button=>button.addEventListener('click',()=>{source=button.dataset.source;offset=0;load();}));
el('previous').addEventListener('click',()=>{offset=Math.max(0,offset-5);load();});
el('next').addEventListener('click',()=>{offset=Math.min(10000,offset+5);load();});
el('logout').addEventListener('click',async()=>{try{await api('logout',{});el('output').textContent='';el('viewer').hidden=true;el('login').hidden=false;el('message').textContent='本浏览器已退出。服务器 revoke 命令可撤销全部审计会话。';}catch(e){el('message').textContent=e.message;}});
load();
