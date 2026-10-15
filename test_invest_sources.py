"""Synthetic public-provider payloads only; no network or production database."""
import json
import os
import tempfile
import urllib.error
from datetime import datetime
from unittest.mock import patch

with tempfile.TemporaryDirectory() as folder:
    os.environ.update(MANGO_DATA=folder,MANGO_PUBLIC='1')
    from app import db
    import invest_market as market
    from investment import TZ
    stamp=datetime(2026,10,15,14,30,tzinfo=TZ)

    def payloads(symbol,when=stamp,other_price=None):
        index=symbol=='sh000300';price='4000.00' if index else '100.00'
        t=['']*50
        for i,value in {1:'沪深300' if index else '测试普通股',2:symbol[2:],3:price,4:price,6:'100',
                        30:when.strftime('%Y%m%d%H%M%S'),47:'-1' if index else '110.00',48:'-1' if index else '90.00'}.items():t[i]=value
        e={'f57':symbol[2:],'f58':t[1],'f43':float(price) if other_price is None else other_price,
           'f60':float(price),'f86':int(when.timestamp()),'f51':-1 if index else 110,'f52':-1 if index else 90,'f47':100}
        history={'data':{symbol:{'day':[[f'2026-10-{d:02d}','100','100','100','100','100'] for d in range(8,15)]}}}
        return 'v_'+symbol+'="'+'~'.join(t)+'";',json.dumps({'data':e}),json.dumps(history)

    def run_snapshot(symbol,when=stamp,other_price=None,fail_source=None):
        values=payloads(symbol,when,other_price);seen=[]
        def fake_fetch(url,encoding='utf-8'):
            if 'qt.gtimg.cn/q=' in url:
                source='tencent';assert url.endswith('q='+symbol);value=values[0]
            elif 'push2.eastmoney.com' in url:
                source='eastmoney';assert 'secid='+('1.' if symbol.startswith('sh') else '0.')+symbol[2:]+'&' in url;value=values[1]
            elif 'fqkline/get' in url:source='history';value=values[2]
            else:raise AssertionError('Unexpected provider')
            seen.append(source)
            if source==fail_source:raise urllib.error.HTTPError(url,502,'not logged',{},None)
            return value
        with patch('invest_market.now',return_value=when),patch('invest_market.fetch',side_effect=fake_fetch):
            result=market.snapshot(db,symbol)
        return result,seen

    benchmark,seen=run_snapshot('sh000300')
    assert set(seen)=={'tencent','eastmoney'} and len(seen)==2
    assert benchmark['verified'] and benchmark['symbol']=='sh000300' and benchmark['history']==[]
    assert benchmark['price_fen']==400000 and not benchmark['eligible']
    equity,seen=run_snapshot('sh600519')
    assert set(seen)=={'tencent','eastmoney','history'} and equity['verified'] and equity['eligible']
    assert len(equity['history'])>=5
    sz,seen=run_snapshot('sz000001')
    assert sz['verified'] and sz['eligible']
    close=stamp.replace(hour=15,minute=0)
    mismatch,_=run_snapshot('sh000300',close,4000.01)
    assert mismatch['final'] and not mismatch['verified']
    for symbol,source,label in [('sh000300','eastmoney','eastmoney_quote'),('sh600519','eastmoney','eastmoney_quote'),('sh600519','history','tencent_history')]:
        with db() as c:before=c.execute('SELECT count(*) FROM invest_events').fetchone()[0]
        try:run_snapshot(symbol,fail_source=source)
        except market.MarketDataError as e:assert e.diagnostic=={'source':label,'category':'upstream_http','http_status':502}
        else:raise AssertionError('Required source failure accepted')
        with db() as c:assert c.execute('SELECT count(*) FROM invest_events').fetchone()[0]==before
print('PASS sources: correct CSI300/SH/SZ identifiers, two-source benchmark, required equity history, exact close agreement and no single-source fallback')
