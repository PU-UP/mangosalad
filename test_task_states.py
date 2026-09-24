"""Three user states, including legacy discussion rows and delivery failures."""
import os,tempfile
with tempfile.TemporaryDirectory() as tmp:
 os.environ.update(MANGO_DATA=tmp,MANGO_PUBLIC='1',MANGO_INSECURE='1')
 from tasks import task_state,can_cancel
 from task_worker import envelope
 base={'status':'needs_input','kind':'discussion','receipt':'sent','error':None}
 assert task_state(base)=='done'
 assert task_state(base|{'kind':'work'})=='waiting'
 assert task_state(base|{'receipt':None})=='waiting'
 assert task_state(base|{'status':'completed'})=='done'
 assert task_state(base|{'status':'completed','error':'delivery uncertain'})=='waiting'
 for status in ['queued','dispatching','running','cancelling','failed','interrupted']:
  assert task_state(base|{'status':status})=='waiting'
 assert task_state(base|{'status':'cancelled'})=='cancelled'
 assert not can_cancel(base)
 assert not can_cancel(base|{'status':'completed','receipt':None})
 assert can_cancel(base|{'status':'failed','receipt':None})
 assert envelope('{"kind":"discussion","status":"done","message":"Hello"}')['status']=='completed'
 assert envelope('{"kind":"work","status":"waiting","message":"Need input"}')['status']=='needs_input'
 print('PASS: only waiting/done/cancelled; contact vs work; real delivery required; legacy mapping; valid cancellation')
