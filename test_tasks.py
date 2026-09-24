"""Isolated end-to-end dispatch state checks. No real Agent or Feishu calls."""
import os
import tempfile
import time
from datetime import datetime,timezone

with tempfile.TemporaryDirectory() as tmp:
    os.environ.update(MANGO_DATA=tmp,MANGO_PUBLIC='1',MANGO_INSECURE='1')
    from app import app,db,private,save_setting
    from reminders import activation
    from task_worker import claim,finish,recover,envelope
    a=app.test_client();anon=app.test_client();h={'X-Mango-Request':'1'}
    ly=h|{'Authorization':'Bearer '+private['agents']['lychee']}
    ol=h|{'Authorization':'Bearer '+private['agents']['olive']}
    p=a.post('/api/pages',headers=h,json={'title':'整份任务','kind':'checklist','state':{'items':[{'id':'a','text':'A','done':False},{'id':'b','text':'B','done':False}]}}).json
    path='/api/pages/'+p['id'];tp=path+'/tasks'
    b={'agent':'lychee','page_revision':1,'instructions':'到时和我讨论整份计划','run_at':None}
    assert a.post(tp,headers=h,json=b).status_code==403
    token=activation(db,save_setting).split('=',1)[1]
    assert a.post('/api/reminder-access',headers=h,json={'token':token}).status_code==200
    assert anon.post('/api/reminder-access',headers=h,json={'token':token}).status_code==403
    assert a.post(tp,headers=h,json=b|{'run_at':'2026-09-24T18:00'}).status_code==400
    future=datetime.fromtimestamp(time.time()+3600,timezone.utc).isoformat()
    tid=a.post(tp,headers=h,json=b|{'run_at':future}).json['id']
    assert claim() is None
    assert a.post(tp,headers=h,json=b).status_code==409
    assert anon.get('/api/tasks').status_code==403
    assert len(anon.get('/api/tasks',headers=ly).json['tasks'])==1
    assert anon.get('/api/tasks/'+tid,headers=ol).status_code==404
    assert a.delete('/api/tasks/'+tid,headers=h,json={'revision':1}).json['status']=='cancelled'
    assert claim() is None
    tid=a.post(tp,headers=h,json=b).json['id']
    job=claim();assert job['id']==tid and claim() is None
    assert anon.post('/api/tasks/'+tid+'/ack',headers=ol,json={}).status_code==404
    assert anon.post('/api/tasks/'+tid+'/ack',headers=ly,json={}).json['status']=='running'
    snapshot=anon.get('/api/tasks/'+tid,headers=ly).json['snapshot']
    assert len(snapshot['state']['items'])==2
    # Edits after confirmation do not silently change the assigned instructions.
    assert a.patch(path,headers=h,json={'revision':1,'title':'changed'}).status_code==200
    assert anon.get('/api/tasks/'+tid,headers=ly).json['snapshot']['title']=='整份任务'
    r=a.get(tp).json['tasks'][0]
    assert a.delete('/api/tasks/'+tid,headers=h,json={'revision':r['revision']}).json['status']=='cancelling'
    assert anon.post('/api/tasks/'+tid+'/ack',headers=ly,json={}).status_code==409
    assert finish(tid,'completed','must not publish') is False
    assert a.get(tp).json['tasks'][0]['status']=='cancelled'
    tid=a.post(tp,headers=h,json=b|{'page_revision':2}).json['id'];claim();recover()
    assert a.get(tp).json['tasks'][0]['status']=='interrupted' and claim() is None
    tid=a.post(tp,headers=h,json=b|{'page_revision':2}).json['id']
    a.patch(path,headers=h,json={'revision':2,'archived':True})
    assert a.get(tp).json['tasks'][0]['status']=='cancelled'
    assert envelope('text {"kind":"discussion","status":"needs_input","message":"what next?"}')['kind']=='discussion'
    assert anon.post(path+'/reminders',headers=ly,json={}).status_code==410
    print('PASS: authorized whole-page confirmation, schedule, one active owner, true Agent ACK, private inbox, frozen snapshot, cancel, archive, restart no duplicate, legacy disabled')
