"""Maintainer-only, cited cash dividend terms. No model/API access to this action."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit
from decimal import Decimal
from datetime import date
from investment import append, now, symbol_ok, events


def register(db,terms):
    required={'symbol','record_day','ex_day','pay_day','fen_per_share','evidence_id'}
    if set(terms)!=required or not symbol_ok(terms['symbol']):raise ValueError('现金分红参数无效')
    for key in ('record_day','ex_day','pay_day'):date.fromisoformat(terms[key])
    if not terms['record_day']<terms['ex_day']<=terms['pay_day']:raise ValueError('分红日期顺序无效')
    rate=Decimal(str(terms['fen_per_share']))
    if not rate.is_finite() or rate<=0:raise ValueError('每股税前分红须为正数，单位分')
    terms={**terms,'fen_per_share':str(rate)}
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        e=c.execute('SELECT url FROM invest_evidence WHERE id=?',(terms['evidence_id'],)).fetchone()
        host=urlsplit(e['url']).hostname if e else ''
        if not host or not any(host==d or host.endswith('.'+d) for d in ('sse.com.cn','szse.cn','cninfo.com.cn')):raise ValueError('需要已保存的官方公告证据')
        if any(r['day']>=terms['ex_day'] for r in events(c,'valuation')):raise ValueError('除息后已估值，需人工核对并追加纠错，不能倒改历史')
        append(c,'dividend-terms:'+terms['symbol']+':'+terms['ex_day'],'dividend_terms',now().date().isoformat(),terms)


if __name__=='__main__':
    from app import db
    p=argparse.ArgumentParser();p.add_argument('--file',required=True);a=p.parse_args()
    register(db,json.loads(Path(a.file).read_text()))
    print('已追加官方现金分红条款；按权益登记持仓计算，除息计应收，到账日计现金。')
