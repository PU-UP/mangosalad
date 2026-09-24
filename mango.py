"""Local Agent client. Tokens stay in a private local file, never in page URLs."""
import argparse
import json
import os
from pathlib import Path
import sys
import uuid
import urllib.request
import urllib.error

def append_items(call, page_id, texts):
    """Preserve current state, retry revision conflicts, and verify actual persistence."""
    if not texts or any(not isinstance(t,str) or not t.strip() or len(t.strip())>500 for t in texts):
        raise ValueError('Provide nonempty item text, at most 500 characters each')
    texts=list(dict.fromkeys(t.strip() for t in texts))
    path='/api/pages/'+page_id
    for attempt in range(3):
        page=call(path,'GET')
        if page['kind']!='checklist' or page['archived']:raise ValueError('An active checklist is required')
        items=page['state'].get('items',[])
        existing={i['text'].strip():i for i in items}
        added=[{'id':str(uuid.uuid4()),'text':t,'done':False} for t in texts if t not in existing]
        expected={t:existing[t]['id'] for t in texts if t in existing}
        expected.update({i['text']:i['id'] for i in added})
        if added:
            try:call(path,'PATCH',{'revision':page['revision'],'state':{**page['state'],'items':items+added}})
            except urllib.error.HTTPError as e:
                if e.code==409 and attempt<2:continue
                raise
        saved=call(path,'GET')
        found={i['id']:i['text'] for i in saved['state']['items']}
        if any(found.get(i)!=t for t,i in expected.items()):
            raise RuntimeError('Write not verified; read the current page before retrying')
        return {'verified':True,'operation':'append-items','page_id':page_id,
                'revision':saved['revision'],'added':[i['text'] for i in added],
                'already_present':[t for t in texts if t in existing],
                'total':len(saved['state']['items']),'url':'https://mangosalad.cn/#page='+page_id}


def main():
    p = argparse.ArgumentParser(description='Read and publish your mangosalad pages.')
    p.add_argument('--agent', required=True, choices=['lychee','olive'])
    p.add_argument('action', choices=['list','get','create','update','delete','reminders','remind','cancel-reminder','reminder-link','my-tasks','task-get','task-ack','append-items'])
    p.add_argument('id', nargs='?')
    p.add_argument('--file', help='UTF-8 JSON document. Use - for stdin.')
    p.add_argument('--item', action='append', help='Item text; repeat for multiple items')
    args = p.parse_args()
    token_path = Path(os.environ.get('MANGO_TOKEN_FILE', Path.home()/'.config/mangosalad'/f'{args.agent}.token'))
    token = token_path.read_text().strip()
    methods = {'list':'GET','get':'GET','create':'POST','update':'PATCH','delete':'DELETE','reminders':'GET','remind':'POST','cancel-reminder':'DELETE','reminder-link':'POST','my-tasks':'GET','task-get':'GET','task-ack':'POST'}
    needs_id = args.action in ('get','update','delete','reminders','remind','cancel-reminder','task-get','task-ack','append-items')
    if needs_id and (not args.id or not all(c.isalnum() or c in '-_' for c in args.id)):
        p.error('This action requires a valid page id.')
    if args.action=='append-items':
        def call(path,method,body=None):
            req=urllib.request.Request(os.environ.get('MANGO_API','http://127.0.0.1:5010')+path,
                data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,
                method=method,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','X-Mango-Request':'1'})
            with urllib.request.urlopen(req,timeout=20) as response:return json.load(response)
        try:result=append_items(call,args.id,args.item)
        except Exception as e:
            print('未确认完成：'+str(e),file=sys.stderr);raise SystemExit(1)
        result['agent']=args.agent
        print(json.dumps(result,ensure_ascii=False,indent=2));return
    body = None
    if args.action in ('create','update','delete','remind','cancel-reminder'):
        if not args.file: p.error('Provide --file containing JSON.')
        raw = sys.stdin.read() if args.file == '-' else Path(args.file).read_text(encoding='utf-8-sig')
        body = json.dumps(json.loads(raw), ensure_ascii=False).encode()
    url = os.environ.get('MANGO_API','http://127.0.0.1:5010')+'/api/pages'+('/'+args.id if needs_id else '')
    if args.action in ('reminders','remind'): url+='/reminders'
    if args.action=='cancel-reminder': url=os.environ.get('MANGO_API','http://127.0.0.1:5010')+'/api/reminders/'+args.id
    if args.action=='reminder-link':
        url=os.environ.get('MANGO_API','http://127.0.0.1:5010')+'/api/reminder-link'
        body=b'{}'
    if args.action in ('my-tasks','task-get','task-ack'):
        url=os.environ.get('MANGO_API','http://127.0.0.1:5010')+'/api/tasks'+('/'+args.id if args.id else '')
        if args.action=='task-ack': url+='/ack';body=b'{}'
    req = urllib.request.Request(url, data=body, method=methods[args.action], headers={
        'Authorization':'Bearer '+token,'Content-Type':'application/json','X-Mango-Request':'1'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r: result=json.load(r)
    except urllib.error.HTTPError as e:
        print(e.read().decode(), file=sys.stderr)
        raise SystemExit(1)
    if 'url' in result and result['url'].startswith('/'): result['url']='https://mangosalad.cn/'+result['url'].lstrip('/')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
