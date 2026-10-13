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
    p.add_argument('--symbols',default='');p.add_argument('--file');a=p.parse_args()
    path={'status':'','market':'/market','evidence':'/evidence','report':'/report','export':'/export'}[a.action]
    if a.action=='market':
        from urllib.parse import quote
        path+='?symbols='+quote(a.symbols)
    body=None
    if a.action in ('evidence','report'):
        if not a.file:p.error('需要--file JSON文件（-为标准输入）')
        body=json.dumps(json.loads(sys.stdin.read() if a.file=='-' else Path(a.file).read_text(encoding='utf-8-sig')),ensure_ascii=False).encode()
    token=(Path.home()/'.config/mangosalad/olive.token').read_text().strip()
    req=urllib.request.Request(os.environ.get('MANGO_API','http://127.0.0.1:5010')+'/api/invest'+path,data=body,
        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','X-Mango-Request':'1'})
    try:
        with urllib.request.urlopen(req,timeout=180) as r:print(r.read().decode())
    except urllib.error.HTTPError as e:
        print(e.read().decode(),file=sys.stderr);raise SystemExit(1)


if __name__=='__main__':main()
