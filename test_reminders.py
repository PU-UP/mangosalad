"""Retired per-item endpoint and device activation regression checks."""
import os, tempfile
with tempfile.TemporaryDirectory() as tmp:
    os.environ.update(MANGO_DATA=tmp,MANGO_PUBLIC='1',MANGO_INSECURE='1')
    from app import app, db, save_setting
    from reminders import activation
    client=app.test_client(); anonymous=app.test_client()
    h={'X-Mango-Request':'1'}
    page=client.post('/api/pages',headers=h,json={'title':'test','kind':'checklist','state':{'items':[]}}).json
    token=activation(db,save_setting).split('=',1)[1]
    assert client.post('/api/reminder-access',headers=h,json={'token':token}).status_code==200
    assert anonymous.post('/api/reminder-access',headers=h,json={'token':token}).status_code==403
    assert client.post('/api/pages/'+page['id']+'/reminders',headers=h,json={}).status_code==410
    print('PASS: activation one-use; retired item reminders cannot be created')
