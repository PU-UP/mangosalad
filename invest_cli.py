"""Olive-only local API client; credentials never enter prompts or output."""
import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['status','market','evidence','report','export'])
    p.add_argument('--symbols',default='');p.add_argument('--file')
    view=p.add_mutually_exclusive_group();view.add_argument('--model-context',action='store_true');view.add_argument('--report-id',type=int)
    a=p.parse_args()
    if (a.model_context or a.report_id is not None) and a.action!='status':p.error('Context views apply only to status')
    path={'status':'','market':'/market','evidence':'/evidence','report':'/report','export':'/export'}[a.action]
    if a.action=='market':
        from urllib.parse import quote
        path+='?symbols='+quote(a.symbols)
    if a.report_id is not None:path='/export'
    body=None
    if a.action in ('evidence','report'):
        if not a.file:p.error('需要--file JSON文件（-为标准输入）')
        body=json.dumps(json.loads(sys.stdin.read() if a.file=='-' else Path(a.file).read_text(encoding='utf-8-sig')),ensure_ascii=False).encode()
    token=(Path.home()/'.config/mangosalad/olive.token').read_text().strip()
    req=urllib.request.Request(os.environ.get('MANGO_API','http://127.0.0.1:5010')+'/api/invest'+path,data=body,
        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','X-Mango-Request':'1'})
    try:
        with urllib.request.urlopen(req,timeout=180) as r:raw=r.read().decode()
        if a.model_context or a.report_id is not None:
            from invest_context import project, full_report, reviews
            data=Path(os.environ.get('MANGO_DATA',Path.home()/'.local/share/mangosalad/runtime'))
            value=json.loads(raw)
            value=project(value,reviews(data)) if a.model_context else full_report(value,a.report_id,reviews(data))
            print(json.dumps(value,ensure_ascii=False))
        else:print(raw)
    except urllib.error.HTTPError as e:
        print(e.read().decode(),file=sys.stderr);raise SystemExit(1)


if __name__=='__main__':main()
