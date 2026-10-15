"""Readiness transitions with synthetic data, real SQLite and no network/model."""
import tempfile,sqlite3,json,threading
from contextlib import contextmanager, ExitStack
from datetime import datetime,timedelta
from unittest.mock import patch
import investment as inv
import invest_daily as daily
import invest_ready as ready
import invest_worker as worker
from invest_market import MarketDataError, budget_reason

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
        with db() as c:
            c.execute('UPDATE invest_control SET enabled=1')
            # Preserve a synthetic prior-day report at the same id as today's real report.
            while c.execute('SELECT count(*) FROM invest_events').fetchone()[0]<27:
                n=c.execute('SELECT count(*) FROM invest_events').fetchone()[0]
                inv.append(c,'fixture:'+str(n),'fixture','2026-10-15',{})
            inv.append(c,'research:2026-10-15','research','2026-10-15',
                {**report('fixture'),'rules_version':'2.0-daily','research_day':'2026-10-15','execution_day':'2026-10-16',
                 'orders':[{'symbol':'sh600519','side':'buy','qty':100,'quote_id':'prior'}]})
            before=c.execute('SELECT digest FROM invest_events WHERE id=28').fetchone()[0]
        with patch('invest_ready.now',return_value=datetime(2026,10,15,17,tzinfo=inv.TZ)):ready.schedule(db)
        assert daily.rules(db,'2026-10-15')['version']=='2.0-daily'
        assert daily.rules(db,'2026-10-16')['version']=='2.1-ready'
        yield db
        with db() as c:assert c.execute('SELECT digest FROM invest_events WHERE id=28').fetchone()[0]==before

def report(rid):
    return dict(run_id=rid,stage='research',summary='fixture',facts=[],inferences='fixture',uncertainties='fixture',counterevidence='fixture',judgments=[],orders=[],next_plan='fixture',reviews=[])

@contextmanager
def at(hour,minute=0,day=16):
    stamp=datetime(2026,10,day,hour,minute,tzinfo=inv.TZ)
    with ExitStack() as stack:
        for module in ('investment','invest_daily','invest_ready','invest_worker'):
            stack.enter_context(patch(module+'.now',return_value=stamp))
        yield stamp

def quote(db,symbol):
    stamp=ready.now();day=stamp.date().isoformat()
    return dict(symbol=symbol,name='fixture',day=day,observed_at=stamp.isoformat(),price_fen=1000,previous_fen=1000,
        upper_fen=1100,lower_fen=900,verified=True,eligible=symbol!='sh000300',final=True,corporate_action=False,
        rules_version='2.1-ready',history=[],_urls=['https://one.test/'+symbol,'https://two.test/'+symbol],_raws=['one','two'])

def missing(db,symbol):raise MarketDataError({'source':'sina_daily','category':'daily_bar_missing','required_day':'2026-10-16','latest_day':'2026-10-15'})

with fixture() as db:
    with at(16,29),patch('invest_ready.probe') as fetch:
        assert not ready.advance(db);fetch.assert_not_called()
    with at(16,30),patch('invest_ready.probe',side_effect=missing) as fetch:
        assert not ready.advance(db);assert fetch.call_count==2
        assert not ready.advance(db);assert fetch.call_count==2
    with db() as c:
        assert not inv.events(c,'quote') and not inv.events(c,'settled')
        assert c.execute('SELECT count(*) FROM invest_market_requests').fetchone()[0]==0
    with at(17),patch('invest_ready.probe',side_effect=quote) as fetch:
        assert ready.advance(db);assert fetch.call_count==2
        assert ready.advance(db);assert fetch.call_count==2
    with db() as c:
        assert len(inv.events(c,'fill'))==1 and len(inv.events(c,'settled'))==1
        assert inv.events(c,'fill')[0]['payload']['research_day']=='2026-10-15'
        assert inv.events(c,'quote')[0]['payload']['observed_at'].startswith('2026-10-16T17:00')
    with at(17,4),patch('invest_worker.invoke') as model:
        assert not worker.tick(db,lambda *a:None);model.assert_not_called()
    def invoke(text,rid):inv.submit(db,report(rid))
    with at(17,5),patch('invest_worker.invoke',side_effect=invoke) as model:
        assert worker.tick(db,lambda *a:None);assert model.call_count==1
        assert not worker.tick(db,lambda *a:None);assert model.call_count==1
    with db() as c:
        assert inv.events(c,'research')[-1]['payload']['execution_day']=='2026-10-19'
        assert len(inv.events(c,'fill'))==1

for partial in (False,True):
    with fixture() as db:
        def fetch(db,symbol):return quote(db,symbol) if partial and symbol=='sh000300' else missing(db,symbol)
        with patch('invest_ready.probe',side_effect=fetch) as calls:
            for i,(h,m) in enumerate(((16,30),(17,0),(17,30),(18,0),(18,30))):
                with at(h,m):assert ready.advance(db)==(i==4)
            assert calls.call_count==10
            with at(18,40):assert ready.advance(db)
            assert calls.call_count==10
        with db() as c:
            assert not inv.events(c,'fill') and len(inv.events(c,'rejected'))==1
            assert len(json.loads(c.execute('SELECT checks FROM invest_readiness').fetchone()[0]))==5
            assert bool(inv.events(c,'valuation')[-1]['payload']['benchmark_price'])==partial

# Lost process: never repeat its slot; recover in a later slot.
with fixture() as db:
    with at(16,30),patch('invest_ready.probe',side_effect=SystemExit):
        try:ready.advance(db)
        except SystemExit:pass
    with at(16,31),patch('invest_ready.probe') as fetch:
        assert not ready.advance(db);fetch.assert_not_called()
    with at(17),patch('invest_ready.probe',side_effect=quote):assert ready.advance(db)
    assert ready.status(db,'2026-10-16')['checks'][0]['state']=='interrupted'

# Crash after an evidence/quote write: deterministic persistence is idempotent.
with fixture() as db:
    real_save=ready.save_probe
    def crash(db,q):real_save(db,q);raise SystemExit
    with at(16,30),patch('invest_ready.probe',side_effect=quote),patch('invest_ready.save_probe',side_effect=crash):
        try:ready.advance(db)
        except SystemExit:pass
    with at(16,36),patch('invest_ready.probe') as fetch:
        assert ready.advance(db);fetch.assert_not_called()
    with db() as c:assert len(inv.events(c,'quote'))==2 and len(inv.events(c,'fill'))==1

# Crash after the settlement transaction but before readiness status update cannot fill twice.
with fixture() as db:
    real_settle=ready.settle
    def after_settle(*args):real_settle(*args);raise SystemExit
    with at(16,30),patch('invest_ready.probe',side_effect=quote),patch('invest_ready.settle',side_effect=after_settle):
        try:ready.advance(db)
        except SystemExit:pass
    with at(16,31),patch('invest_ready.probe') as fetch:
        assert ready.advance(db);fetch.assert_not_called()
    with db() as c:assert len(inv.events(c,'fill'))==1
    assert ready.status(db,'2026-10-16')['state']=='settled'

# Competing workers cannot start a duplicate probe.
with fixture() as db:
    entered=threading.Event();release=threading.Event();out=[]
    def blocked(db,symbol):entered.set();release.wait(5);return quote(db,symbol)
    with at(16,30),patch('invest_ready.probe',side_effect=blocked) as fetch:
        t=threading.Thread(target=lambda:out.append(ready.advance(db)));t.start();assert entered.wait(5)
        assert not ready.advance(db);release.set();t.join(10)
        assert out==[True] and fetch.call_count==2

with fixture() as db:
    with at(18,51),patch('invest_ready.probe') as fetch,patch('invest_worker.invoke') as model:
        assert worker.tick(db,lambda *a:None) # reject missing execution data once
        assert not worker.tick(db,lambda *a:None) # no late research start
        fetch.assert_not_called();model.assert_not_called()
    with at(18,57),patch('invest_worker.invoke') as model:
        assert not worker.tick(db,lambda *a:None);model.assert_not_called()
    with db() as c:assert c.execute("SELECT status FROM invest_runs WHERE day='2026-10-16'").fetchone()[0]=='missed'

# Startup after the research window records a miss before review, without invoking research.
with fixture() as db:
    with at(20),patch('invest_ready.probe') as fetch,patch('invest_worker.invoke') as model:
        assert worker.tick(db,lambda *a:None)
        assert not worker.tick(db,lambda *a:None)
        fetch.assert_not_called();model.assert_not_called()
    with db() as c:assert c.execute("SELECT status FROM invest_runs WHERE stage='research'").fetchone()[0]=='missed'

# Cached observations cannot be made fresh merely by restarting the worker.
with fixture() as db:
    with at(16,30):
        cached={s:quote(db,s) for s in ('sh600519','sh000300')}
    with db() as c:c.execute("INSERT INTO invest_readiness(day,state,cache) VALUES(?,'waiting',?)",('2026-10-16',inv.dump(cached)))
    with at(18,35),patch('invest_ready.probe') as fetch:
        assert ready.advance(db);fetch.assert_not_called()
    with db() as c:assert not inv.events(c,'fill') and len(inv.events(c,'rejected'))==1

# Access-denied responses are terminal for that source/symbol today, not repeatedly retried.
with fixture() as db:
    def denied(db,symbol):raise MarketDataError({'source':'sina_daily','category':'upstream_http','http_status':403})
    with patch('invest_ready.probe',side_effect=denied) as fetch:
        with at(16,30):assert not ready.advance(db)
        with at(17):assert not ready.advance(db)
        assert fetch.call_count==2

# Submission cutoff is absolute, separate from when the eight-minute run started.
with fixture() as db:
    with db() as c:c.execute('INSERT INTO invest_runs VALUES(?,?,?,?,?,?,?)',('cutoff','2026-10-16','research','running','2026-10-16T18:50:00+08:00',None,None))
    with at(18,59):inv.submit(db,report('cutoff'))
    with at(19):
        try:inv.submit(db,report('cutoff'))
        except ValueError:pass
        else:raise AssertionError('Late submission accepted')
    with db() as c:
        assert inv.events(c,'research')[-1]['payload']['execution_day']=='2026-10-19'
        assert len(inv.events(c,'research'))==2

stamp=datetime(2026,10,16,18,50,tzinfo=inv.TZ)
run={'started':stamp.isoformat(),'stage':'research','deadline_hour':19,'deadline_minute':0}
assert budget_reason(run,[], 'x',stamp+timedelta(minutes=5)) is None
assert budget_reason(run,[], 'x',stamp+timedelta(minutes=6))=='submission_time_reserved'
print('PASS readiness: future rules, #28 preserved, 5 slots, partial/all missing, true timestamps, single settlement/research, holidays, concurrency, crash recovery, late cutoff, independent model budget')
