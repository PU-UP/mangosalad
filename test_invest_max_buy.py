"""2.1-ready max buy price: new buys above ¥200 rejected; existing holdings kept."""
import tempfile, sqlite3
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch
import investment as inv
import invest_daily as daily
import invest_ready as ready


@contextmanager
def fixture():
    with tempfile.TemporaryDirectory() as folder:
        @contextmanager
        def db():
            c=sqlite3.connect(folder+'/test.sqlite',timeout=5);c.row_factory=sqlite3.Row
            try:
                with c:yield c
            finally:c.close()
        inv.schema(db);inv.start(db,'2026-10-14')
        with patch('invest_daily.now',return_value=datetime(2026,10,15,13,tzinfo=inv.TZ)):daily.activate(db)
        with patch('invest_ready.now',return_value=datetime(2026,10,15,17,tzinfo=inv.TZ)):ready.schedule(db)
        with db() as c:c.execute('UPDATE invest_control SET enabled=1')
        yield db


def stamp(day,hour=17,minute=0):
    return datetime(2026,10,day,hour,minute,tzinfo=inv.TZ)


def quote_body(eid,symbol,day,when,price_fen):
    return dict(id=eid,symbol=symbol,name='fixture',day=day,observed_at=when.isoformat(),
        price_fen=price_fen,previous_fen=price_fen,upper_fen=price_fen+1000,lower_fen=max(1,price_fen-1000),
        verified=True,eligible=True,final=True,corporate_action=False,evidence_ids=[eid],
        rules_version='2.1-ready')


def report(rid,symbol,side,eid,day):
    return dict(run_id=rid,stage='research',summary='fixture',
        facts=[{'text':'fixture','evidence_id':eid,'event_date':day}],
        inferences='fixture',uncertainties='fixture',counterevidence='fixture',next_plan='fixture',reviews=[],
        judgments=[{'symbol':symbol,'action':side,'reason':'fixture','horizon_days':5,'falsifier':'fixture',
                    'risk':'fixture','sizing':'fixture','evidence_ids':[eid]}],
        orders=[{'symbol':symbol,'side':side,'qty':100,'quote_id':eid}])


def seed_quote(db,symbol,day,when,price_fen,run_id):
    with patch('investment.now',return_value=when):
        eid=inv.evidence(db,'https://www.sse.com.cn/'+symbol+'-'+day+'-'+str(price_fen),'fixture',day)
    q=quote_body(eid,symbol,day,when,price_fen)
    with db() as c:
        inv.append(c,'quote:'+eid,'quote',day,q,when.isoformat())
        c.execute('INSERT OR IGNORE INTO invest_runs VALUES(?,?,?,?,?,?,?)',(run_id,day,'research','running',when.isoformat(),None,None))
    return eid,q


def rejects(fn):
    try:fn()
    except ValueError as e:return str(e)
    raise AssertionError('Expected rejection')


# Persisted 2.1-ready rules event carries the enforceable cap.
with fixture() as db:
    rules=daily.rules(db,'2026-10-16')
    assert rules['version']=='2.1-ready' and rules['max_buy_price_fen']==20000
    with db() as c:
        stored=inv.events(c,'rules')
        ready_event=next(r for r in stored if r['event_key']=='rules:2.1-ready')
        assert ready_event['payload']['max_buy_price_fen']==20000
        assert ready_event['payload']['max_buy']


# Buy at and under ¥200: submit and settle fill; cash/position move only by that fill.
for price in (20000,19900):
    with fixture() as db:
        research,exec_day=stamp(16),stamp(19,16,30)
        eid,q=seed_quote(db,'sz000001','2026-10-16',research,price,'buy-ok-'+str(price))
        inv.submit(db,report('buy-ok-'+str(price),'sz000001','buy',eid,'2026-10-16'),research)
        close={**q,'day':'2026-10-19','observed_at':exec_day.isoformat()}
        inv.settle(db,'2026-10-19',{'sz000001':close,'sh000300':{**close,'symbol':'sh000300','eligible':False}},exec_day)
        with db() as c:
            account=inv.replay(c)
            assert account['positions']['sz000001']['qty']==100
            assert account['cash_fen']==20000000-100*price
            fills=inv.events(c,'fill')
            assert len(fills)==1 and fills[0]['payload']['price_fen']==price
            assert not inv.events(c,'rejected')


# Buy above ¥200 rejected on submit; journal has no research/fill for that attempt.
with fixture() as db:
    research=stamp(16)
    eid,_=seed_quote(db,'sz000001','2026-10-16',research,20001,'buy-submit-over')
    before=None
    with db() as c:before=[r['event_key'] for r in inv.events(c)]
    message=rejects(lambda:inv.submit(db,report('buy-submit-over','sz000001','buy',eid,'2026-10-16'),research))
    assert '20000' in message and '上限' in message
    with db() as c:
        assert [r['event_key'] for r in inv.events(c)]==before
        assert not inv.events(c,'research') and not inv.events(c,'fill') and not inv.events(c,'rejected')
        assert inv.replay(c)['cash_fen']==20000000 and not inv.replay(c)['positions']


# Frozen buy whose execution close gaps above ¥200 is rejected on settle; no invented fill.
with fixture() as db:
    research,exec_day=stamp(16),stamp(19,16,30)
    eid,q=seed_quote(db,'sz000001','2026-10-16',research,19900,'buy-settle-over')
    inv.submit(db,report('buy-settle-over','sz000001','buy',eid,'2026-10-16'),research)
    close={**q,'day':'2026-10-19','price_fen':20100,'upper_fen':22100,'lower_fen':18100,'observed_at':exec_day.isoformat()}
    inv.settle(db,'2026-10-19',{'sz000001':close,'sh000300':{**close,'symbol':'sh000300','eligible':False}},exec_day)
    with db() as c:
        assert not inv.events(c,'fill')
        rejected=inv.events(c,'rejected')
        assert len(rejected)==1
        assert rejected[0]['payload']['reason'].startswith('买入价超过平台上限')
        assert '20000' in rejected[0]['payload']['reason']
        assert rejected[0]['payload']['order']['symbol']=='sz000001'
        assert inv.replay(c)['cash_fen']==20000000 and not inv.replay(c)['positions']


# Existing Maotai-like holding is not auto-sold; a new high-price buy is refused; a sell remains allowed.
with fixture() as db:
    with db() as c:
        inv.append(c,'fixture-maotai','fill','2026-10-14',
            {'symbol':'sh600519','name':'贵州茅台','qty':100,'side':'buy','price_fen':140000})
        held=inv.replay(c)
        assert held['positions']['sh600519']['qty']==100
        cash_after_lot=held['cash_fen']
    research,exec_day=stamp(16),stamp(19,16,30)
    eid,_=seed_quote(db,'sh600519','2026-10-16',research,140000,'day16')
    message=rejects(lambda:inv.submit(db,report('day16','sh600519','buy',eid,'2026-10-16'),research))
    assert '20000' in message
    cheap_id,cheap_q=seed_quote(db,'sz000002','2026-10-16',research,15000,'day16')
    # Unrelated cheap buy still settles; Maotai lot is untouched.
    inv.submit(db,report('day16','sz000002','buy',cheap_id,'2026-10-16'),research)
    close_cheap={**cheap_q,'day':'2026-10-19','observed_at':exec_day.isoformat()}
    maotai_mark={**quote_body('mark','sh600519','2026-10-19',exec_day,140000),'id':'mark','evidence_ids':[]}
    inv.settle(db,'2026-10-19',{
        'sz000002':close_cheap,
        'sh600519':maotai_mark,
        'sh000300':{**close_cheap,'symbol':'sh000300','eligible':False},
    },exec_day)
    with db() as c:
        account=inv.replay(c)
        assert account['positions']['sh600519']['qty']==100
        assert account['positions']['sz000002']['qty']==100
        assert account['cash_fen']==cash_after_lot-100*15000
        assert all(f['payload']['symbol']!='sh600519' or f['event_key']=='fixture-maotai' for f in inv.events(c,'fill'))

# Sell of the existing high-priced lot is not blocked by the buy cap.
with fixture() as db:
    with db() as c:
        inv.append(c,'fixture-maotai','fill','2026-10-14',
            {'symbol':'sh600519','name':'贵州茅台','qty':100,'side':'buy','price_fen':140000})
    research,exec_day=stamp(16),stamp(19,16,30)
    eid,q=seed_quote(db,'sh600519','2026-10-16',research,140000,'maotai-sell')
    inv.submit(db,report('maotai-sell','sh600519','sell',eid,'2026-10-16'),research)
    close={**q,'day':'2026-10-19','observed_at':exec_day.isoformat()}
    inv.settle(db,'2026-10-19',{'sh600519':close,'sh000300':{**close,'symbol':'sh000300','eligible':False}},exec_day)
    with db() as c:
        account=inv.replay(c)
        assert 'sh600519' not in account['positions']
        fills=[f for f in inv.events(c,'fill') if f['payload']['side']=='sell']
        assert len(fills)==1 and fills[0]['payload']['symbol']=='sh600519'

print('PASS max buy price: rules event persists 20000 fen cap; at/under ¥200 fill; above rejected on submit and settle; existing Maotai lot kept; sells still allowed')
