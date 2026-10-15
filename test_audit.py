"""Isolated authentication, read boundaries and regression tests; no live secrets."""
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch
from flask import Flask
from itsdangerous import URLSafeTimedSerializer
import audit
from audit_access import configure, load_access

PASSWORD = '012345'  # Isolated fixture only; never installed in production.
HEADERS = {'X-Mango-Request':'1','Origin':'https://localhost'}


def database(path, script):
    path.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(path) as c:c.executescript(script)


with tempfile.TemporaryDirectory() as temp:
    home=Path(temp);data=home/'runtime';data.mkdir()
    access=home/'config/audit-access.json'
    app=Flask(__name__);app.secret_key='isolated-test-app-secret'
    audit.install(app,data,home,access)
    client=app.test_client()
    routes=['rules','status','olive/runs','lychee/runs','lychee/results','olive/ledger','olive/evidence']
    for route in routes:assert client.get('/api/audit/'+route).status_code==401
    assert client.post('/api/audit/login',json={'password':PASSWORD},headers=HEADERS).status_code==401
    # A normal owner session cannot authorize audit access.
    with client.session_transaction() as s:s['reminders']='owner';s['owner']=True
    assert client.get('/api/audit/rules').status_code==401
    configure(access,PASSWORD)
    assert access.stat().st_mode&0o077==0 and load_access(access)
    assert PASSWORD not in access.read_text()
    assert client.post('/api/audit/login',json={'password':PASSWORD}).status_code==403
    assert client.post('/api/audit/login',json={'password':PASSWORD},headers=HEADERS|{'Origin':'https://evil.invalid'}).status_code==403
    assert client.post('/api/audit/login?password=forbidden',json={'password':PASSWORD},headers=HEADERS).status_code==400
    assert client.post('/api/audit/login',json={'password':PASSWORD+'wrong'},headers=HEADERS).status_code==401
    response=client.post('/api/audit/login',json={'password':PASSWORD},headers=HEADERS)
    assert response.status_code==200
    cookie=response.headers['Set-Cookie']
    assert 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=Strict' in cookie and 'Domain=' not in cookie
    assert PASSWORD not in response.get_data(as_text=True)
    assert client.get('/api/audit/rules').status_code==200
    for method in ['post','put','patch','delete']:
        assert getattr(client,method)('/api/audit/rules',json={},headers=HEADERS).status_code==405
    for query in ['path=/etc/passwd','sql=select+1','agent=olive','offset=-1','offset=10001','limit=0','limit=51','limit=2&limit=3','offset=0%20OR%201=1','limit='+('9'*90)]:
        assert client.get('/api/audit/rules?'+query).status_code==400,query
    for route in ['../private.json','%2e%2e/private.json','olive/../../config','mango/runs']:
        assert client.get('/api/audit/'+route).status_code in (400,404)
    assert client.get('/api/audit/olive/runs').status_code==503

    work=home/'.hermes/profiles/lychee/workspace/weekend';(work/'notes').mkdir(parents=True)
    (work/'STATE.md').write_text('Visible research\napi_key = SENSITIVE_FIXTURE\nhttps://user:pass@example.com/research?token=LEAK#secret\n-----BEGIN PRIVATE KEY-----\nPEM_FIXTURE\n-----END PRIVATE KEY-----\n'+'a'*48)
    for i in range(4):(work/'notes'/('note-'+str(i)+'.md')).write_text('note '+str(i))
    (work/'notes'/'secret-link.md').symlink_to(access)
    result=client.get('/api/audit/lychee/results?limit=2&offset=1')
    assert result.status_code==200
    text=result.get_data(as_text=True)
    for secret in ['SENSITIVE_FIXTURE','user:pass','LEAK','PEM_FIXTURE','a'*48,'password_hash']:
        assert secret not in text,secret
    assert len(result.json['data']['notes'])==2
    assert not audit.document(work/'notes/secret-link.md')['available']
    assert audit.clean({'password':'hidden','nested':{'Authorization':'hidden','result':'safe'}})=={'nested':{'result':'safe'}}
    (work/'JOURNAL.md').write_text('x '*40000)
    assert audit.document(work/'JOURNAL.md')['truncated']
    # Read-only connections cannot mutate even if a future query accidentally does so.
    database(data/'mango.sqlite','CREATE TABLE sample (value TEXT); INSERT INTO sample VALUES ("unchanged");')
    try:
        with audit.readonly(data/'mango.sqlite') as c:c.execute('DELETE FROM sample')
        raise AssertionError('write accepted')
    except sqlite3.OperationalError:pass
    with sqlite3.connect(data/'mango.sqlite') as c:assert c.execute('SELECT value FROM sample').fetchone()[0]=='unchanged'
    database(home/'.openclaw/state/openclaw.sqlite','CREATE TABLE cron_jobs(job_id TEXT,name TEXT,enabled INTEGER,state_json TEXT); CREATE TABLE cron_run_receipts(receipt_id TEXT,job_id TEXT,status TEXT,started_at_ms INTEGER,finished_at_ms INTEGER,error_text TEXT); INSERT INTO cron_jobs VALUES("j","heartbeat",1,\'{"lastError":"no-route"}\'); INSERT INTO cron_run_receipts VALUES("r","j","skipped",1,2,"no-route");')
    database(data/'mango.sqlite','CREATE TABLE invest_runs(id TEXT,day TEXT,stage TEXT,status TEXT,started TEXT,finished TEXT,error TEXT); CREATE TABLE tasks(id TEXT,agent TEXT,status TEXT,created REAL,updated REAL,acknowledged REAL,kind TEXT,result TEXT,error TEXT); CREATE TABLE invest_control(enabled INTEGER); INSERT INTO invest_control VALUES(1);')
    cron=home/'.hermes/profiles/lychee/cron';cron.mkdir(parents=True,exist_ok=True)
    (cron/'jobs.json').write_text(json.dumps({'jobs':[{'name':'weekend','enabled':True,'password':'not-exported'}]}))
    result=client.get('/api/audit/olive/runs').json['data']
    assert result['runs'][0]['error']=='no-route' and result['runs'][0]['status']=='skipped'
    assert client.get('/api/audit/status').status_code==200
    assert 'not-exported' not in client.get('/api/audit/status').get_data(as_text=True)
    with patch.object(audit,'MAX_RESPONSE',100):
        assert client.get('/api/audit/rules').status_code==413
    # Cookie expiry, corruption, rotation and immediate revocation.
    old_cookie=client.get_cookie(audit.COOKIE).value
    configure(access,PASSWORD)
    assert client.get('/api/audit/rules').status_code==401
    assert client.post('/api/audit/login',json={'password':PASSWORD},headers=HEADERS).status_code==200
    with patch('time.time',return_value=__import__('time').time()+audit.LIFETIME+1):
        assert client.get('/api/audit/rules').status_code==401
    client.set_cookie(audit.COOKIE,'bad-signature')
    assert client.get('/api/audit/rules').status_code==401
    assert client.post('/api/audit/login',json={'password':PASSWORD},headers=HEADERS).status_code==200
    assert client.post('/api/audit/logout',headers=HEADERS).status_code==200
    assert client.get('/api/audit/rules').status_code==401
    assert client.post('/api/audit/login',json={'password':PASSWORD},headers=HEADERS).status_code==200
    access.unlink()
    assert client.get('/api/audit/rules').status_code==401
    configure(access,PASSWORD);access.chmod(0o644)
    assert load_access(access) is None
    access.chmod(0o600)
    # Separate Flask instances share the durable account-wide lockout.
    limited=Flask('limited');limited.secret_key='fixture';audit.install(limited,data,home,access)
    attacker=limited.test_client()
    for i in range(4):assert attacker.post('/api/audit/login',json={'password':'999999'},headers=HEADERS).status_code==401
    locked=attacker.post('/api/audit/login',json={'password':'999999'},headers=HEADERS)
    assert locked.status_code==429 and locked.headers['Retry-After']=='3600'
    assert client.post('/api/audit/login',json={'password':PASSWORD},headers=HEADERS).status_code==429
    configure(access,PASSWORD)

    # Original app integration: audit identity cannot reuse Agent/device APIs.
    os.environ['MANGO_DATA']=str(home/'integration');os.environ['MANGO_PUBLIC']='1'
    audit.ACCESS=access
    from app import app as original,db,private,save_setting
    normal=original.test_client()
    assert normal.get('/api/pages').status_code==200
    assert normal.post('/api/audit/login',json={'password':PASSWORD},headers=HEADERS).status_code==200
    for endpoint in ['/api/pages','/api/invest','/api/tasks']:
        assert normal.get(endpoint).status_code==403
    for endpoint in ['/api/pages','/api/pages/fixture/tasks','/api/invest/report','/api/invest/evidence']:
        assert normal.post(endpoint,json={},headers=HEADERS|{'Authorization':'Bearer '+private['agents']['olive']}).status_code==403
    assert normal.post('/api/audit/logout',json={},headers=HEADERS).status_code==200
    assert normal.get('/api/pages').status_code==200
    with db() as c:save_setting(c,'reminder_generation','existing-device')
    with normal.session_transaction() as s:s['reminders']='existing-device'
    assert normal.get('/api/invest').status_code==200
    assert normal.get('/api/audit/rules').status_code==401
    # Ledger/evidence reads use fixture data only and preserve all rows.
    from investment import start
    start(db,'2026-10-14')
    assert normal.post('/api/audit/login',json={'password':PASSWORD},headers=HEADERS).status_code==200
    before=Path(os.environ['MANGO_DATA'])/'mango.sqlite'
    with sqlite3.connect(before) as c:count=c.execute('SELECT count(*) FROM invest_events').fetchone()[0]
    ledger=normal.get('/api/audit/olive/ledger?limit=1')
    assert ledger.status_code==200 and ledger.json['data']['account']['cash_fen']==20000000
    assert len(ledger.json['data']['events'])==1
    assert normal.get('/api/audit/olive/evidence').status_code==200
    with sqlite3.connect(before) as c:assert c.execute('SELECT count(*) FROM invest_events').fetchone()[0]==count
    from invest_daily import activate
    from investment import TZ
    from datetime import datetime
    with patch('invest_daily.now',return_value=datetime(2026,10,15,13,tzinfo=TZ)):activate(db)
    result=normal.get('/api/audit/rules')
    assert result.status_code==200 and result.json['data']['investment']['version']=='2.0-daily'
    assert result.json['data']['mode_verified'] is True
print('Audit security and integration checks passed')
