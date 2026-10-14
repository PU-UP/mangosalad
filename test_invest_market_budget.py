"""No network or agent calls: bounded market failures and honest empty reports."""
import json
import os
import tempfile
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

with tempfile.TemporaryDirectory() as folder:
    os.environ.update(MANGO_DATA=folder,MANGO_PUBLIC='1')
    from app import app,db,private
    import invest_market as market
    import invest_worker as worker
    from investment import TZ,RULES,start,submit,replay
    stamp=datetime(2026,10,15,14,30,tzinfo=TZ)
    original_rules=json.dumps(RULES,sort_keys=True)
    start(db,'2026-10-15')
    with db() as c:
        c.execute('UPDATE invest_control SET enabled=1')
        c.execute('INSERT INTO invest_runs VALUES(?,?,?,?,?,?,?)',('fixture','2026-10-15','research','running',stamp.isoformat(),None,None))
    client=app.test_client();headers={'Authorization':'Bearer '+private['agents']['olive']}
    error=urllib.error.HTTPError('https://example.invalid/?token=DO_NOT_EXPORT',403,'SENSITIVE_REASON',{},None)
    safe=market.diagnostic(error,'eastmoney_quote')
    assert safe=={'source':'eastmoney_quote','category':'upstream_http','http_status':403}
    assert 'SENSITIVE' not in json.dumps(safe) and 'token' not in json.dumps(safe)
    with patch('invest_market.fetch',side_effect=error):
        try:market.source_fetch('https://example.invalid','utf-8','eastmoney_quote')
        except market.MarketDataError as e:assert e.diagnostic==safe
        else:raise AssertionError('expected classified error')
    with patch('invest_market.now',return_value=stamp),patch('invest_market.snapshot',side_effect=market.MarketDataError(safe)) as upstream:
        for i in range(2):
            result=client.get('/api/invest/market?symbols=sh600519',headers=headers)
            assert result.status_code==200 and result.json['quotes']==[] and result.json['candidates']==[]
            assert not result.json['ok'] and result.json['errors'][0]['http_status']==403
        blocked=client.get('/api/invest/market?symbols=sh600519',headers=headers).json
        assert blocked['stop_market'] and blocked['errors'][0]['category']=='query_attempts_exhausted'
        assert upstream.call_count==2
        third=client.get('/api/invest/market?symbols=sh600036',headers=headers).json
        assert third['stop_market'] and upstream.call_count==3
        fourth=client.get('/api/invest/market?symbols=sz000858',headers=headers).json
        assert fourth['errors'][0]['category']=='failure_budget_exhausted' and upstream.call_count==3
    with db() as c:
        assert c.execute('SELECT count(*) FROM invest_market_requests').fetchone()[0]==3
        assert 'SENSITIVE' not in ''.join(r[0] for r in c.execute('SELECT diagnostics FROM invest_market_requests'))
        assert not c.execute("SELECT 1 FROM invest_events WHERE kind='research'").fetchone()
        c.execute('DELETE FROM invest_market_requests')
    # Partial success remains distinguishable from failed symbols, never a KeyError.
    def partial(db,symbol):
        if symbol=='sh600519':return {'symbol':symbol,'verified':True}
        raise market.MarketDataError(safe)
    with patch('invest_market.now',return_value=stamp),patch('invest_market.snapshot',side_effect=partial):
        data=market.market_request(db,'sh600519,sh600036')
        assert not data['ok'] and len(data['quotes'])==1 and len(data['errors'])==1
    with patch('invest_market.now',return_value=stamp+timedelta(seconds=360)),patch('invest_market.snapshot') as upstream:
        data=market.market_request(db,'sh600519')
        assert data['stop_market'] and data['errors'][0]['category']=='submission_time_reserved'
        upstream.assert_not_called()
    with patch('invest_market.now',return_value=stamp),patch('invest_market.snapshot') as upstream:
        assert not market.market_request(db,'../../etc/passwd')['ok'];upstream.assert_not_called()
    with db() as c:c.execute('DELETE FROM invest_market_requests')
    # Successful refreshes are not mistaken for failed retries.
    with patch('invest_market.now',return_value=stamp),patch('invest_market.snapshot',return_value={'symbol':'sh600519'}):
        for _ in range(3):assert market.market_request(db,'sh600519')['ok']
    with db() as c:
        assert c.execute('SELECT count(*) FROM invest_market_requests WHERE ok=0').fetchone()[0]==0
        c.execute('DELETE FROM invest_market_requests')
    # Concurrent callers cannot race past the total request cap.
    with patch('invest_market.now',return_value=stamp),patch('invest_market.snapshot',return_value={'symbol':'sh600519'}) as upstream:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda _:market.market_request(db,'sh600519'),range(12)))
        assert upstream.call_count<=8
        for result in results:
            if result['errors'] and result['errors'][0]['category']=='request_in_progress':assert not result['stop_market']
    with db() as c:c.execute('DELETE FROM invest_market_requests')
    with patch('invest_market.now',return_value=stamp),patch('invest_market.snapshot',return_value={}) as upstream:
        for symbol in ['sh600000','sh600001','sh600002','sh600003','sh600004','sh600005','sh600006','sh600007']:
            market.market_request(db,symbol)
        assert market.market_request(db,'sh600008')['stop_market'] and upstream.call_count==8
    # The existing validator accepts an explicit data-insufficient, no-order report.
    report={'run_id':'fixture','stage':'research','summary':'测试：数据接口失败，未完成研究，本轮无订单。',
            'facts':[],'inferences':'无可验证推断。','uncertainties':'数据获取失败。','counterevidence':'证据不足，不能判断。',
            'next_plan':'后续正常运行重新核验，不补单。','judgments':[],'orders':[],'reviews':[]}
    receipt=submit(db,report,stamp+timedelta(minutes=6,seconds=30))
    assert receipt['record_id']
    with db() as c:
        assert replay(c)['cash_fen']==20000000 and not replay(c)['positions']
        assert not c.execute("SELECT 1 FROM invest_events WHERE kind IN ('fill','rejected')").fetchone()
    assert json.dumps(RULES,sort_keys=True)==original_rules
    # Classify the original gateway timeout without retaining raw output or secrets.
    for completed,category in [(SimpleNamespace(returncode=0,stdout=json.dumps({'text':'Request timed out before a response was generated.'})),'agent_timeout'),
                               (SimpleNamespace(returncode=0,stdout='not json'),'gateway_response_invalid'),
                               (SimpleNamespace(returncode=1,stdout=''),'gateway_call_failed')]:
        with patch('invest_worker.subprocess.run',return_value=completed):
            try:worker.invoke('fixture','fixture')
            except worker.InvestmentRunError as e:assert e.category==category
            else:raise AssertionError('Missing error category')
    # Settlement collector is unchanged and does not use the research circuit.
    with patch('invest_market.snapshot',return_value={'final':True}) as upstream:
        quotes,errors=market.collect(db,['sh000300'])
        assert quotes['sh000300']['final'] and not errors and upstream.call_count==1
print('PASS market budget: safe diagnostics, bounded retries, concurrency, reserved time, stable error shape, empty report and unchanged settlement/rules')
