"""Local Agent client. Tokens stay in a private local file, never in page URLs."""
import argparse
import json
import os
from pathlib import Path
import sys
import urllib.request
import urllib.error

def main():
    p = argparse.ArgumentParser(description='Read and publish your mangosalad pages.')
    p.add_argument('--agent', required=True, choices=['lychee','olive'])
    p.add_argument('action', choices=['list','get','create','update','delete','reminders','remind','cancel-reminder','reminder-link','my-tasks','task-get','task-ack'])
    p.add_argument('id', nargs='?')
    p.add_argument('--file', help='UTF-8 JSON document. Use - for stdin.')
    args = p.parse_args()
    token_path = Path(os.environ.get('MANGO_TOKEN_FILE', Path.home()/'.config/mangosalad'/f'{args.agent}.token'))
    token = token_path.read_text().strip()
    methods = {'list':'GET','get':'GET','create':'POST','update':'PATCH','delete':'DELETE','reminders':'GET','remind':'POST','cancel-reminder':'DELETE','reminder-link':'POST','my-tasks':'GET','task-get':'GET','task-ack':'POST'}
    needs_id = args.action in ('get','update','delete','reminders','remind','cancel-reminder','task-get','task-ack')
    if needs_id and (not args.id or not all(c.isalnum() or c in '-_' for c in args.id)):
        p.error('This action requires a valid page id.')
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
