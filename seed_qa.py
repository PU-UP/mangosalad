"""Isolated browser QA fixtures, never run against the live data directory."""
import os
assert os.environ.get('MANGO_DATA','').endswith('qa-data')
from app import app, db, save_setting
from werkzeug.security import generate_password_hash
with db() as c:
    save_setting(c,'password',generate_password_hash('mango-browser-test-2026'))
    save_setting(c,'generation','qa')
    c.execute('DELETE FROM pages')
client=app.test_client()
h={'X-Mango-Request':'1'}
client.post('/api/login',headers=h,json={'password':'mango-browser-test-2026'})
for title,pinned,items in [('明天去超市',False,['牛奶 · 2 瓶','鸡蛋 · 一盒','苹果和香蕉','洗衣液']),('最近想做的事',True,['整理旅行照片','想一想下一次小旅行','把想读的书留下来'])]:
    client.post('/api/pages',headers=h,json={'title':title,'kind':'checklist','pinned':pinned,'state':{'items':[{'id':str(i),'text':t,'done':False} for i,t in enumerate(items)]}})
html='''<style>body{font-family:system-ui;padding:24px;color:#1b3555}button{font-size:18px;padding:14px;border:0;border-radius:10px;background:#f5b642;color:#1b3555}h1{font-size:28px}#value{font-size:60px;margin:24px 0}</style><h1>一点点进展</h1><p>自定义界面也能保存状态</p><div id="value">0</div><button id="plus" disabled>再加一点 ＋</button><p id="status"></p><script>let state={},revision;const b=document.getElementById('plus');function draw(){document.getElementById('value').textContent=state.count||0;}addEventListener('message',e=>{if(e.source!==parent)return;const m=e.data;if(m.type==='mango:init'||m.type==='mango:saved'){state=m.state;revision=m.revision;draw();b.disabled=false;document.getElementById('status').textContent=m.type==='mango:saved'?'已保存':'';}if(m.type==='mango:error'){document.getElementById('status').textContent=m.error;b.disabled=false;}});b.onclick=()=>{b.disabled=true;parent.postMessage({type:'mango:save',state:{count:(state.count||0)+1},revision},'*');};parent.postMessage({type:'mango:ready'},'*');</script>'''
client.post('/api/pages',headers=h,json={'title':'一个可交互的小页面','kind':'canvas','content':{'html':html},'state':{'count':0}})
print('QA pages seeded in isolated directory')
