"""Persistent ordering and date filtering using an isolated real database."""
import os,tempfile
from datetime import datetime,timedelta,timezone
with tempfile.TemporaryDirectory() as tmp:
 os.environ.update(MANGO_DATA=tmp,MANGO_PUBLIC='1',MANGO_INSECURE='1')
 from app import app
 c=app.test_client();h={'X-Mango-Request':'1'}
 def create(title,focus=None):
  r=c.post('/api/pages',headers=h,json={'title':title,'kind':'checklist','state':{'items':[]},'focus_date':focus});assert r.status_code==201;return r.json
 today=datetime.now(timezone(timedelta(hours=8))).date()
 a=create('overdue',(today-timedelta(days=1)).isoformat());b=create('this week',(today+timedelta(days=6)).isoformat());d=create('later',(today+timedelta(days=7)).isoformat());e=create('undated')
 data=c.get('/api/pages').json
 assert {p['id'] for p in data['pages'] if p['needs_focus']}=={a['id'],b['id']}
 before=[p['id'] for p in data['pages']];visible=[a['id'],d['id']]
 r=c.post('/api/pages/order',headers=h,json={'ids':visible,'revision':data['order_revision']});assert r.status_code==200
 after=c.get('/api/pages').json
 assert [p['id'] for p in after['pages'] if p['id'] in visible]==visible
 assert [p['id'] for p in after['pages'] if p['id'] not in visible]==[i for i in before if i not in visible]
 assert c.post('/api/pages/order',headers=h,json={'ids':visible,'revision':data['order_revision']}).status_code==409
 assert c.post('/api/pages/order',headers=h,json={'ids':[a['id'],a['id']],'revision':r.json['revision']}).status_code==400
 assert c.patch('/api/pages/'+e['id'],headers=h,json={'revision':1,'focus_date':'2026-02-30'}).status_code==400
 updated=c.patch('/api/pages/'+e['id'],headers=h,json={'revision':1,'focus_date':today.isoformat()});assert updated.status_code==200
 assert c.patch('/api/pages/'+e['id'],headers=h,json={'revision':1,'focus_date':None}).status_code==409
 assert c.get('/api/pages/'+e['id']).json['focus_date']==today.isoformat()
 assert c.patch('/api/pages/'+e['id'],headers=h,json={'revision':2,'focus_date':None}).status_code==200
 assert c.patch('/api/pages/'+a['id'],headers=h,json={'revision':1,'archived':True}).status_code==200
 assert not next(p for p in c.get('/api/pages').json['pages'] if p['id']==a['id'])['needs_focus']
 assert c.get('/api/pages').json['order_revision']==after['order_revision']
 print('PASS desktop: dates, Beijing seven-day boundary, null/invalid/conflict, archive, persistent subset order, concurrent sort rejection')
