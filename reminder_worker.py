"""Run once per minute from systemd. Delivery is a template, not an LLM task."""
import json
import time
import urllib.request
from app import db, DATA


def post(url, body, token=None):
    headers={'Content-Type':'application/json'}
    if token: headers['Authorization']='Bearer '+token
    req=urllib.request.Request('https://open.feishu.cn/open-apis/'+url,
        data=json.dumps(body).encode(),headers=headers,method='POST')
    with urllib.request.urlopen(req,timeout=20) as r: result=json.load(r)
    if result.get('code',0)!=0: raise RuntimeError('Feishu code '+str(result.get('code')))
    return result


def send(agent, text, uuid):
    config=json.loads((DATA/'delivery.json').read_text())[agent]
    token=post('auth/v3/tenant_access_token/internal',
        {'app_id':config['app_id'],'app_secret':config['app_secret']})['tenant_access_token']
    r=post('im/v1/messages?receive_id_type=chat_id',
        {'receive_id':config['chat_id'],'msg_type':'text','content':json.dumps({'text':text}), 'uuid':uuid}, token)
    return r['data']['message_id']


def tick(deliver=send):
    now=time.time()
    with db() as c:
        # A crash during delivery is ambiguous. Never automatically resend.
        c.execute("UPDATE reminders SET status='uncertain',error='发送结果未确认，请在飞书核对。',revision=revision+1,updated=? WHERE status='sending' AND updated<?",(now,now-180))
        ids=[r['id'] for r in c.execute("SELECT id FROM reminders WHERE status='pending' AND due<=? ORDER BY due LIMIT 20",(now,))]
    for rid in ids:
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            r=c.execute("SELECT * FROM reminders WHERE id=? AND status='pending'",(rid,)).fetchone()
            if not r: continue
            page=c.execute('SELECT * FROM pages WHERE id=?',(r['page_id'],)).fetchone()
            item=next((i for i in json.loads(page['state']).get('items',[]) if i['id']==r['item_id']),None) if page else None
            if not page or page['archived'] or not item or item.get('done'):
                c.execute("UPDATE reminders SET status='cancelled',revision=revision+1,updated=? WHERE id=?",(now,rid));continue
            if now-r['due']>86400:
                c.execute("UPDATE reminders SET status='missed',error='已超过提醒时间一天，未补发。',revision=revision+1,updated=? WHERE id=?",(now,rid));continue
            c.execute("UPDATE reminders SET status='sending',revision=revision+1,updated=? WHERE id=?",(now,rid))
            text=(('🍒 lychee 提醒你：' if r['agent']=='lychee' else '🫒 olive 提醒你：')+'\n'+r['message']+'\n\nhttps://mangosalad.cn/#page='+r['page_id'])
            if now-r['due']>120: text+='\n（服务恢复后补发）'
        try:
            receipt=deliver(r['agent'],text,rid)
            status,error='sent',None
        except Exception:
            # Network errors may occur after Feishu accepts the message.
            receipt,status,error=None,'uncertain','发送未确认，请在飞书核对；不会自动重复发送。'
        with db() as c:
            c.execute('UPDATE reminders SET status=?,receipt=?,error=?,revision=revision+1,updated=? WHERE id=?',(status,receipt,error,time.time(),rid))


if __name__=='__main__': tick()
