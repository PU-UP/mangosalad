"""One isolated lifecycle plus boundary failures; never touches production data."""
import copy
import json
import os
import sqlite3
import tempfile
from datetime import datetime
from unittest.mock import patch


def raises(fn):
    try:fn()
    except (ValueError,sqlite3.IntegrityError):return
    raise AssertionError('Expected rejection')


with tempfile.TemporaryDirectory() as tmp:
    os.environ['MANGO_DATA']=tmp;os.environ['MANGO_PUBLIC']='1'
    from app import app,db,private,save_setting
    from investment import start,append,evidence,submit,settle,replay,events,summary,TZ,trading_day,symbol_ok
    day='2026-10-14';stamp=datetime(2026,10,14,14,40,tzinfo=TZ)
    client=app.test_client();headers={'X-Mango-Request':'1'}
    olive=headers|{'Authorization':'Bearer '+private['agents']['olive']}
    lychee=headers|{'Authorization':'Bearer '+private['agents']['lychee']}
    assert client.get('/api/invest').status_code==403
    assert client.get('/api/invest/export').status_code==403
    assert client.get('/api/invest',headers=lychee).status_code==403
    assert client.get('/api/invest',headers=olive|{'X-Forwarded-For':'1.2.3.4'}).status_code==403
    assert client.post('/api/invest/report',headers=lychee,json={}).status_code==403
    assert client.post('/api/invest/report',headers=headers,json={}).status_code==403
    with db() as c:save_setting(c,'reminder_generation','test-device')
    with client.session_transaction() as s:s['reminders']='test-device'
    assert client.get('/api/invest').status_code==200
    assert client.post('/api/invest/report',headers=headers,json={}).status_code==403
    assert not trading_day('2026-10-10') and not trading_day('2026-10-01') and trading_day(day)
    raises(lambda:trading_day('2027-01-04'))
    assert symbol_ok('sh600519') and not symbol_ok('sh688001') and not symbol_ok('sz300001')
    start(db,day);raises(lambda:start(db,day))
    with db() as c:c.execute('UPDATE invest_control SET enabled=1')
    with patch('investment.now',return_value=stamp):eid=evidence(db,'https://www.sse.com.cn/test','fixture evidence',day)
    q={'id':eid,'symbol':'sh600519','name':'测试普通A股','day':day,'observed_at':stamp.isoformat(),
       'price_fen':1000,'upper_fen':1100,'lower_fen':900,'verified':True,'eligible':True,'final':False,'evidence_ids':[eid]}
    with db() as c:
        append(c,'quote:'+eid,'quote',day,q)
        c.execute('INSERT INTO invest_runs VALUES(?,?,?,?,?,?,?)',('test-run',day,'research','running',stamp.isoformat(),None,None))
    body={'run_id':'test-run','stage':'research','summary':'fixture: 买入有证据的假设','facts':[{'text':'测试事实','evidence_id':eid,'event_date':day}],
          'inferences':'测试推断','uncertainties':'测试不确定性','counterevidence':'测试反证','next_plan':'明日验证',
          'judgments':[{'symbol':'sh600519','action':'buy','reason':'测试理由','horizon_days':5,'falsifier':'条件不兑现','risk':'价格下跌','sizing':'小仓位验证','evidence_ids':[eid]}],
          'orders':[{'symbol':'sh600519','side':'buy','qty':100,'quote_id':eid}],'reviews':[]}
    bad=copy.deepcopy(body);bad['balance']=1;raises(lambda:submit(db,bad,stamp))
    bad=copy.deepcopy(body);bad['orders'][0]['qty']=True;raises(lambda:submit(db,bad,stamp))
    raises(lambda:submit(db,body,stamp.replace(hour=15)))
    raises(lambda:submit(db,body,stamp.replace(minute=55)))
    raises(lambda:submit(db,body,stamp.replace(minute=46)))
    rid=submit(db,body,stamp)['record_id'];assert submit(db,body,stamp)['record_id']==rid
    bad=copy.deepcopy(body);bad['summary']='改写历史';raises(lambda:submit(db,bad,stamp))
    close=datetime(2026,10,14,15,15,tzinfo=TZ);q['final']=True
    index={'day':day,'price_fen':400000,'verified':True,'final':True}
    settle(db,day,{'sh600519':q,'sh000300':index},close)
    settle(db,day,{'sh600519':q,'sh000300':index},close)
    with db() as c:
        a=replay(c);assert a['cash_fen']==19900000 and a['positions']['sh600519']['qty']==100
        assert len(events(c,'fill'))==1
        raises(lambda:c.execute('UPDATE invest_events SET payload=\'{}\''))
        raises(lambda:c.execute('DELETE FROM invest_events'))
        raises(lambda:c.execute('UPDATE invest_evidence SET raw=\'changed\''))
    # Next day attempts the full available balance at a gap-up price: reject, never resize.
    day2='2026-10-15'
    with db() as c:
        b=copy.deepcopy(body);b['orders'][0]['qty']=2000000
        append(c,'research:'+day2,'research',day2,b)
    q2={**q,'day':day2};index2={**index,'day':day2}
    settle(db,day2,{'sh600519':q2,'sh000300':index2},close.replace(day=15))
    with db() as c:assert events(c,'rejected')[-1]['payload']['reason'].startswith('收盘价下现金不足')
    # Missing quote: no fill and no invented valuation; limit quote: no buy/sell.
    for d,quotes in [('2026-10-16',{}),('2026-10-19',{'sh600519':{**q,'day':'2026-10-19','price_fen':1100}})]:
        with db() as c:append(c,'research:'+d,'research',d,body)
        settle(db,d,quotes,datetime.fromisoformat(d+'T15:15:00+08:00'))
    with db() as c:
        assert len(events(c,'fill'))==1
        assert events(c,'valuation')[-2]['payload']['value_fen'] is None
        assert events(c,'rejected')[-1]['payload']['reason']=='收盘触及涨跌停，双向不成交'
        # T+1: deliberately feed a same-day-only lot to the settlement checker.
        append(c,'fixture-lot','fill','2026-10-20',{'symbol':'sz000001','name':'fixture','qty':100,'side':'buy','price_fen':1000})
        b=copy.deepcopy(body);b['orders']=[{'symbol':'sz000001','side':'sell','qty':100,'quote_id':eid}]
        append(c,'research:2026-10-20','research','2026-10-20',b)
    settle(db,'2026-10-20',{'sz000001':{**q,'symbol':'sz000001','day':'2026-10-20'}},close.replace(day=20))
    with db() as c:assert 'T+1' in events(c,'rejected')[-1]['payload']['reason']
    with patch('investment.now',return_value=stamp):
        assert client.get('/api/invest/export',headers=olive).status_code==200
        assert client.get('/api/invest/export?format=md',headers=olive).status_code==200
    from invest_worker import tick
    # Calendar gate and idempotent scheduler misses need no model or delivery.
    with db() as c:c.execute('UPDATE invest_control SET enabled=1')
    with patch('invest_worker.now',return_value=datetime(2026,10,17,14,30,tzinfo=TZ)),patch('invest_worker.invoke') as model:
        assert tick(db,lambda *x:None) is False;model.assert_not_called()
    with patch('invest_worker.now',return_value=datetime(2026,10,21,14,56,tzinfo=TZ)),patch('invest_worker.invoke') as model:
        assert tick(db,lambda *x:None) is False
        assert tick(db,lambda *x:None) is False;model.assert_not_called()
    from invest_dividend import register
    from investment import apply_dividends
    terms={'symbol':'sh600519','record_day':'2026-10-21','ex_day':'2026-10-22','pay_day':'2026-10-23','fen_per_share':'12.5','evidence_id':eid}
    register(db,terms)
    with db() as c:
        before=replay(c)['cash_fen'];apply_dividends(c,'2026-10-22');apply_dividends(c,'2026-10-22')
        assert replay(c)['receivable_fen']==1250 and replay(c)['cash_fen']==before
        apply_dividends(c,'2026-10-23');apply_dividends(c,'2026-10-23')
        assert replay(c)['cash_fen']==before+1250 and replay(c)['receivable_fen']==0
        c.execute('UPDATE invest_control SET enabled=0')
    raises(lambda:submit(db,body,stamp))
    from invest_market import check_url
    for url in ['http://www.sse.com.cn','https://127.0.0.1','https://evil.example','https://www.sse.com.cn?api_key=secret']:
        raises(lambda:check_url(url))
    print('PASS: cash dividend entitlement/receivable/payment/idempotency, pause rejects writes, unsafe evidence URLs rejected')
    print('PASS: private read/write, calendar, deadline, stale quotes, immutable evidence, duplicate report/run/settlement, full lifecycle, missing data, limit, cash, T+1, replay and exports')
