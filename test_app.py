"""One end-to-end check: privacy, persistence, handoff, conflict, lifecycle."""
import os
import tempfile
import hashlib
import time

with tempfile.TemporaryDirectory() as tmp:
    os.environ['MANGO_DATA']=tmp
    os.environ['MANGO_INSECURE']='1'
    from app import app, db, save_setting, private
    client=app.test_client()
    headers={'X-Mango-Request':'1'}
    assert client.get('/api/pages').status_code==401
    assert client.post('/api/login',json={}).status_code==403
    with db() as c:
        save_setting(c,'setup_hash',hashlib.sha256(b'test-setup').hexdigest())
        save_setting(c,'setup_expires',str(time.time()+60))
    assert client.post('/api/login',headers=headers,json={'password':'test-password-123','setup':'test-setup'}).status_code==200
    assert client.post('/api/pages',headers=headers|{'Origin':'https://other.example'},json={}).status_code==403
    anon=app.test_client()
    lychee=headers|{'Authorization':'Bearer '+private['agents']['lychee']}
    olive=headers|{'Authorization':'Bearer '+private['agents']['olive']}
    assert anon.get('/api/pages',headers=lychee|{'X-Forwarded-For':'8.8.8.8'}).status_code==401
    r=anon.post('/api/pages',headers=lychee,json={'title':'购物','kind':'checklist','state':{'items':[{'id':'milk','text':'牛奶','done':False}]}})
    assert r.status_code==201,r.json
    page=r.json
    path='/api/pages/'+page['id']
    assert page['author']=='lychee'
    state={'items':[{'id':'milk','text':'牛奶','done':True}]}
    assert client.patch(path,headers=headers,json={'revision':1,'state':state}).status_code==200
    assert anon.patch(path,headers=olive,json={'revision':1,'title':'旧版'}).status_code==409
    latest=anon.get(path,headers=olive).json
    assert latest['state']['items'][0]['done'] is True
    assert anon.patch(path,headers=olive,json={'revision':2,'title':'明天购物'}).json['author']=='olive'
    assert client.get(path).json['state']['items'][0]['done'] is True
    assert client.patch(path,headers=headers,json={'revision':3,'archived':True}).status_code==200
    assert client.patch(path,headers=headers,json={'revision':4,'archived':False,'pinned':True}).status_code==200
    assert client.delete(path,headers=headers,json={'revision':4}).status_code==409
    assert client.delete(path,headers=headers,json={'revision':5}).status_code==200
    assert client.get(path).status_code==404
    canvas=anon.post('/api/pages',headers=olive,json={'title':'交互测试','kind':'canvas','content':{'html':'<h1>hello</h1>'},'state':{'count':0}}).json
    render=client.get('/api/pages/'+canvas['id']+'/render')
    assert render.status_code==200 and "sandbox allow-scripts" in render.headers['Content-Security-Policy']
    assert anon.get('/api/pages/'+canvas['id']+'/render').status_code==401
    assert client.post('/api/logout',headers=headers,json={}).status_code==200
    assert client.get('/api/pages').status_code==401
    os.environ['MANGO_PUBLIC']='1'
    assert anon.get('/api/session').json['authenticated'] is True
    assert anon.get('/api/session').json['public'] is True
    assert anon.get('/api/pages').status_code==200
    assert anon.post('/api/login',headers=headers,json={}).status_code==404
    public_page=anon.post('/api/pages',headers=headers,json={'title':'无需密码','kind':'checklist','state':{'items':[]}})
    assert public_page.status_code==201
    public_id=public_page.json['id']
    assert anon.patch('/api/pages/'+public_id,headers=headers,json={'revision':1,'pinned':True}).status_code==200
    assert anon.delete('/api/pages/'+public_id,headers=headers,json={'revision':2}).status_code==200
    os.environ.pop('MANGO_PUBLIC')
    print('PASS: auth, CSRF, private agent transport, persistent edits, conflict rejection, archive/restore/delete, isolated canvas')
