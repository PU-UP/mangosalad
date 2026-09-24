"""Append against the real Flask API in an isolated database."""
import os,tempfile,urllib.error
with tempfile.TemporaryDirectory() as tmp:
 os.environ.update(MANGO_DATA=tmp,MANGO_PUBLIC='1',MANGO_INSECURE='1')
 from app import app,private
 from mango import append_items
 c=app.test_client();h={'X-Mango-Request':'1','Authorization':'Bearer '+private['agents']['lychee']}
 def call(path,method,body=None):
  r=c.open(path,method=method,json=body,headers=h)
  if r.status_code>=400:raise urllib.error.HTTPError(path,r.status_code,'test',{},None)
  return r.json
 p=call('/api/pages','POST',{'title':'test','kind':'checklist','state':{'note':'keep','items':[{'id':'old','text':'keep','done':True}]}});pid=p['id']
 first=True
 def conflict(path,method,body=None):
  global first
  if method=='PATCH' and first:
   first=False
   current=call(path,'GET')
   call(path,'PATCH',{'revision':current['revision'],'state':{**current['state'],'items':current['state']['items']+[{'id':'other','text':'other agent','done':False}]}})
  return call(path,method,body)
 result=append_items(conflict,pid,['new','second','new'])
 assert result['verified'] and result['total']==4 and result['added']==['new','second']
 saved=call('/api/pages/'+pid,'GET')
 assert saved['state']['note']=='keep' and saved['state']['items'][0]['done']
 again=append_items(call,pid,['new','second'])
 assert again['added']==[] and again['revision']==saved['revision']
 def lost(path,method,body=None):
  if method=='PATCH':return {}
  return call(path,method,body)
 try:append_items(lost,pid,['lost'])
 except RuntimeError:pass
 else:raise AssertionError('False success on lost write')
 call('/api/pages/'+pid,'PATCH',{'revision':saved['revision'],'archived':True})
 try:append_items(call,pid,['blocked'])
 except ValueError:pass
 else:raise AssertionError('Archived page accepted')
 print('PASS append: conflict merge, checked state, unrelated state, dedup, readback failure, archived rejection')
