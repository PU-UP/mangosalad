"""Isolated synthetic lifecycle. No provider requests, agent invocation or production state."""
import os, tempfile, json, copy
from datetime import datetime, timedelta
from unittest.mock import patch

def rejects(fn):
    try:fn()
    except ValueError:return
    raise AssertionError('Expected rejection')

with tempfile.TemporaryDirectory() as folder:
    os.environ.update(MANGO_DATA=folder,MANGO_PUBLIC='1')
    from app import db
    import investment as inv
    import invest_daily as daily
    import invest_market as market
    import invest_worker as worker
    stamp=datetime(2026,10,15,16,35,tzinfo=inv.TZ)
    inv.start(db,'2026-10-14')
    with db() as c:
        before=[dict(r) for r in c.execute('SELECT * FROM invest_events')]
        c.execute('UPDATE invest_control SET enabled=1')
    with patch('invest_daily.now',return_value=stamp):daily.activate(db);daily.activate(db)
    assert daily.active(db) and daily.rules(db)['research']=='16:30'
    with db() as c:assert [dict(r) for r in c.execute('SELECT * FROM invest_events WHERE id<=?',(len(before),))]==before
    assert daily.adjacent('2026-10-16')=='2026-10-19'
    assert daily.adjacent('2026-09-30')=='2026-10-08'
    rejects(lambda:daily.adjacent('2026-12-31'))

    sequence=[0]
    def quote(symbol='sh600519',when=stamp,mutate=None):
        sequence[0]+=1
        stored_at=when-timedelta(seconds=1)+timedelta(microseconds=sequence[0])
        rows=[[f'2026-10-{d:02d}','10','10','10.5','9.5','100'] for d in (8,9,12,13,14,15,16)]
        t=['']*50
        for i,v in {1:'普通股票',2:symbol[2:],3:'10',4:'10',6:'100',30:when.strftime('%Y%m%d')+'150000',47:'11',48:'9'}.items():t[i]=v
        a={'data':{symbol:{'day':rows,'qt':{symbol:t}}}}
        b=[{'date':r[0]+'T00:00:00.000Z','open':r[1],'close':r[2],'high':r[3],'low':r[4],'volume':10000,'amount':100000} for r in rows]
        if mutate:mutate(a,b)
        def source(url,*args):return json.dumps(a) if 'gtimg.cn' in url else 'compressed fixture'
        with patch('investment.now',return_value=stored_at),patch('invest_daily.now',return_value=when),patch('invest_market.source_fetch',side_effect=source),patch('invest_daily.decode_sina',return_value=b):
            return market.snapshot(db,symbol)
    q=quote();assert q['verified'] and q['eligible'] and q['final']
    assert all(r[0]<='2026-10-15' for r in q['history'])
    assert quote('sz000001')['eligible']
    assert quote('sh000300')['verified'] and not quote('sh000300')['eligible']
    rejects(lambda:quote(when=stamp.replace(hour=14)))
    rejects(lambda:quote(mutate=lambda a,b:b.pop(5)))
    assert not quote(mutate=lambda a,b:b[5].update(close='10.01'))['verified']
    assert not quote(mutate=lambda a,b:a['data']['sh600519']['qt']['sh600519'].__setitem__(47,'12'))['eligible']
    assert not quote(mutate=lambda a,b:a['data']['sh600519']['qt']['sh600519'].__setitem__(1,'ST测试'))['eligible']
    assert not quote(mutate=lambda a,b:b[5].update(volume=0))['eligible']
    with patch('invest_daily.now',return_value=stamp),patch('invest_market.source_fetch',side_effect=ValueError('missing source')):
        rejects(lambda:market.snapshot(db,'sh600519'))
    with patch('invest_worker.now',return_value=stamp.replace(hour=14,minute=30)),patch('invest_worker.invoke') as invoke:
        assert worker.tick(db,lambda *a:None) is False
        invoke.assert_not_called()
    # First day has no pending daily orders and never consumes a same-day research report.
    inv.settle(db,'2026-10-15',{},stamp)
    with db() as c:
        assert not inv.events(c,'fill')
        c.execute('INSERT INTO invest_runs VALUES(?,?,?,?,?,?,?)',('daily-run','2026-10-15','research','running',stamp.isoformat(),None,None))
    body={'run_id':'daily-run','stage':'research','summary':'fixture','facts':[{'text':'fixture','evidence_id':q['id'],'event_date':'2026-10-15'}],
        'inferences':'fixture','uncertainties':'fixture','counterevidence':'fixture','next_plan':'fixture',
        'judgments':[{'symbol':'sh600519','action':'buy','reason':'fixture','horizon_days':5,'falsifier':'fixture','risk':'fixture','sizing':'fixture','evidence_ids':[q['id']]}],
        'orders':[{'symbol':'sh600519','side':'buy','qty':100,'quote_id':q['id']}],'reviews':[]}
    # Fixture evidence was captured just before the frozen research submission.
    inv.submit(db,body,stamp)
    with db() as c:
        p=inv.events(c,'research')[-1]['payload']
        assert p['research_day']=='2026-10-15' and p['execution_day']=='2026-10-16'
        assert not daily.pending(c,'2026-10-15') and len(daily.pending(c,'2026-10-16'))==1
    rejects(lambda:inv.submit(db,{**body,'orders':[]},stamp))
    rejects(lambda:inv.submit(db,body,stamp.replace(hour=14)))
    rejects(lambda:inv.submit(db,body,stamp.replace(minute=55)))
    next_stamp=stamp.replace(day=16,hour=16,minute=0)
    next_q=quote(when=next_stamp)
    inv.settle(db,'2026-10-16',{'sh600519':next_q},next_stamp)
    inv.settle(db,'2026-10-16',{'sh600519':next_q},next_stamp)
    with db() as c:
        fills=inv.events(c,'fill');assert len(fills)==1
        assert fills[0]['payload']['research_day']=='2026-10-15' and fills[0]['day']=='2026-10-16'
        assert inv.replay(c)['cash_fen']==19900000
    friday=next_stamp.replace(hour=16,minute=35)
    with db() as c:c.execute('INSERT INTO invest_runs VALUES(?,?,?,?,?,?,?)',('friday-run','2026-10-16','research','running',friday.isoformat(),None,None))
    friday_body=copy.deepcopy(body);friday_body['run_id']='friday-run'
    friday_body['orders'][0]['quote_id']=next_q['id']
    friday_body['facts']=[{'text':'fixture','evidence_id':next_q['id'],'event_date':'2026-10-16'}]
    inv.submit(db,friday_body,friday)
    with db() as c:assert daily.pending(c,'2026-10-19')
    # A missing execution quote explicitly rejects the order; no later retry or roll-forward.
    inv.settle(db,'2026-10-19',{},next_stamp.replace(day=19))
    with db() as c:
        assert len(inv.events(c,'fill'))==1 and len(inv.events(c,'rejected'))==1
        assert not daily.pending(c,'2026-10-20')
    with patch('invest_market.source_fetch') as fetch:
        assert market.discover(db)['candidates']==[]
        fetch.assert_not_called()
    rejects(lambda:daily.decode_sina('var KLC_K2_sz000001="wrong";','sh600519'))
    rejects(lambda:daily.parse_bars([{'date':'2026-10-15','open':10,'close':10,'high':9,'low':8,'volume':1}],'sina'))

print('PASS daily: calendar, immutable activation, dual sources, stale/missing/incomplete bars, status rejection, no 14:30 run, freeze T / execute T+1, idempotency, no late fill')
