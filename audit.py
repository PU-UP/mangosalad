"""Fixed, bounded, read-only audit projections; separate from owner/agent auth."""
import hmac
import itertools
import json
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from flask import abort, jsonify, request
from itsdangerous import BadSignature, URLSafeTimedSerializer
from audit_access import ACCESS, load_access, authenticate

COOKIE = '__Host-mango-audit'
LIFETIME = 12*3600
MAX_RESPONSE = 192*1024
SECRET = re.compile(r'(?i)(password|passwd|secret|token|api[_ -]?key|authorization|cookie|credential|private[_ -]?key|密码|私钥|配对码)')
URL = re.compile(r'https?://[^\s<>"\)]+')
OPAQUE = re.compile(r'(?<![\w])[A-Za-z0-9_+/=-]{32,}(?![\w])')


def clean_text(value):
    value = re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?(?:-----END [^-]*PRIVATE KEY-----|\Z)', '[REDACTED]', value)
    value = '\n'.join('[REDACTED]' if SECRET.search(line) else line for line in value.splitlines())
    def safe_url(match):
        try:
            u = urlsplit(match.group())
            return urlunsplit((u.scheme, u.hostname or '', u.path, '', ''))
        except ValueError:
            return '[REDACTED URL]'
    value = URL.sub(safe_url, value)
    value = OPAQUE.sub('[REDACTED LONG VALUE]', value)
    return value[:16000]


def clean(value, depth=0):
    if depth > 8: return '[DEPTH LIMIT]'
    if isinstance(value, dict):
        return {str(k): clean(v, depth+1) for k,v in list(value.items())[:100] if not SECRET.search(str(k))}
    if isinstance(value, (list, tuple)): return [clean(v, depth+1) for v in value[:100]]
    if isinstance(value, str): return clean_text(value)
    if value is None or isinstance(value, (bool, int, float)): return value
    return '[UNSUPPORTED]'


def document(path):
    if path.resolve() != path.absolute():
        return {'available': False, 'reason': 'symlink excluded'}
    try:
        with path.open('rb') as stream: raw = stream.read(32769)
        return {'available': True, 'modified_utc': datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                'text': clean_text(raw[:32768].decode('utf-8', errors='replace')),
                'truncated': len(raw)>16000}
    except OSError:
        return {'available': False, 'reason': 'source unavailable'}


@contextmanager
def readonly(path):
    if not path.is_file() or path.resolve() != path.absolute():
        abort(503, 'Audit source unavailable')
    c = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=1)
    c.row_factory = sqlite3.Row
    deadline = time.monotonic()+2
    c.set_progress_handler(lambda: int(time.monotonic()>deadline), 1000)
    c.execute('PRAGMA query_only=ON')
    try:
        yield c
    finally:
        c.close()


def rows(path, sql, parameters=()):
    with readonly(path) as c: return [dict(r) for r in c.execute(sql, parameters)]


def install(app, data, home=None, access_path=None):
    home = home or Path.home()
    access_path = access_path or ACCESS
    serializer = URLSafeTimedSerializer(app.secret_key, salt='mangosalad-readonly-audit-v1')
    mango = data/'mango.sqlite'
    olive = home/'.openclaw/state/openclaw.sqlite'
    lychee = home/'.hermes/profiles/lychee'
    weekend = lychee/'workspace/weekend'

    def authenticated():
        config = load_access(access_path)
        cookie = request.cookies.get(COOKIE, '')
        if not config or len(cookie)>1024: return False
        try:
            generation = serializer.loads(cookie, max_age=LIFETIME)
            return isinstance(generation,str) and hmac.compare_digest(generation,config['generation'])
        except BadSignature:
            return False

    @app.before_request
    def audit_guard():
        # Never mix an audit browser with existing owner/Agent API privileges.
        if request.cookies.get(COOKIE) and request.path.startswith('/api/') and not request.path.startswith('/api/audit'):
            abort(403, 'Log out of the audit browser before using other APIs')
        if not request.path.startswith('/api/audit'): return
        if request.path == '/api/audit/login': return
        if not authenticated(): abort(401, 'Audit login required')
        if request.path == '/api/audit/logout': return
        if request.method != 'GET': abort(405)
        if set(request.args)-{'offset','limit'} or any(len(request.args.getlist(k))!=1 for k in request.args):
            abort(400, 'Only offset and limit are accepted')
        if len(request.query_string)>80: abort(400)

    @app.get('/audit')
    def audit_page():
        return app.send_static_file('audit.html')

    @app.post('/api/audit/login')
    def audit_login():
        if request.headers.get('X-Mango-Request')!='1': abort(403)
        if request.args or request.content_length is None or request.content_length>1024: abort(400)
        if request.headers.get('Origin') not in (None,'https://'+request.host): abort(403)
        body = request.get_json(silent=True)
        if not isinstance(body,dict) or set(body)!={'password'}: abort(400)
        try:
            outcome,generation,retry_after=authenticate(access_path,data/'audit-login.sqlite',body['password'])
        except (OSError,sqlite3.Error):
            abort(503,'Audit authentication temporarily unavailable')
        if outcome=='locked':
            response=jsonify(error='Audit login locked after five failed attempts; try again after the lock expires.',retry_after_seconds=retry_after)
            response.status_code=429
            response.headers['Retry-After']=str(retry_after)
            return response
        if outcome!='ok':
            abort(401, 'Audit login unavailable or password incorrect')
        response = jsonify({'authenticated':True,'expires_in_seconds':LIFETIME})
        response.set_cookie(COOKIE, serializer.dumps(generation), max_age=LIFETIME,
                            secure=True, httponly=True, samesite='Strict', path='/')
        return response

    @app.post('/api/audit/logout')
    def audit_logout():
        if request.args: abort(400)
        response = jsonify({'authenticated':False})
        response.delete_cookie(COOKIE, secure=True, httponly=True, samesite='Strict', path='/')
        return response

    def pagination():
        try:
            if any(not re.fullmatch(r'\d{1,5}',v) for v in request.args.values()): raise ValueError()
            offset,limit = int(request.args.get('offset','0')),int(request.args.get('limit','20'))
            if not 0<=offset<=10000 or not 1<=limit<=50: raise ValueError()
            return offset,limit
        except ValueError: abort(400,'offset 0–10000; limit 1–50')

    def response(value):
        result = {'generated_at_utc':datetime.now(timezone.utc).isoformat(),'data':clean(value)}
        if len(json.dumps(result,ensure_ascii=False).encode())>MAX_RESPONSE: abort(413,'Reduce the page limit')
        return jsonify(result)

    @app.get('/api/audit/rules')
    def audit_rules():
        pagination()
        from investment import RULES
        from invest_daily import RULES_DAILY, rules, now
        current=RULES;mode_verified=False;scheduled=[]
        if mango.is_file():
            with readonly(mango) as c:
                if c.execute("SELECT 1 FROM sqlite_master WHERE name='invest_events'").fetchone():
                    mode_verified=True
                    current=rules(lambda:readonly(mango))
                    scheduled=[json.loads(r[0]) for r in c.execute("SELECT payload FROM invest_events WHERE kind='rules' AND day>? ORDER BY day LIMIT 5",(now().date().isoformat(),))]
        return response({'investment':current,'mode_verified':mode_verified,'scheduled_investment_rules':scheduled,
                         'olive_rules':document(home/'.openclaw/workspace/AGENTS.md'),
                         'olive_identity':document(home/'.openclaw/workspace/IDENTITY.md'),
                         'olive_soul':document(home/'.openclaw/workspace/SOUL.md'),
                         'lychee_rules':document(weekend/'AGENTS.md'),
                         'lychee_soul':document(lychee/'SOUL.md')})

    @app.get('/api/audit/status')
    def audit_status():
        pagination()
        jobs = rows(olive,'SELECT name,enabled,substr(state_json,1,16384) AS state_json FROM cron_jobs ORDER BY name LIMIT 50')
        for job in jobs:
            state = json.loads(job.pop('state_json'))
            job['state'] = {k:state[k] for k in ('nextRunAtMs','lastRunAtMs','lastRunStatus','lastError','consecutiveErrors','consecutiveSkipped') if k in state}
        cron_file = lychee/'cron/jobs.json'
        if cron_file.resolve()!=cron_file.absolute() or cron_file.stat().st_size>262144: abort(503,'Audit source unavailable')
        config = json.loads(cron_file.read_text())
        jobs2 = config if isinstance(config,list) else config.get('jobs',[])
        fields = ('name','enabled','schedule','last_run_at','next_run_at','last_status')
        return response({'olive_jobs':jobs,'lychee_jobs':[{k:j[k] for k in fields if k in j} for j in jobs2[:50]],
                         'investment':rows(mango,'SELECT enabled FROM invest_control'),
                         'scope':'Read-only projections; raw conversations, credentials and tool arguments excluded.'})

    @app.get('/api/audit/<agent>/runs')
    def audit_runs(agent):
        if agent not in ('olive','lychee'): abort(404)
        offset,limit = pagination()
        if agent=='olive':
            runs = rows(olive,'SELECT j.name,r.status,r.started_at_ms,r.finished_at_ms,substr(r.error_text,1,4000) AS error FROM cron_run_receipts r LEFT JOIN cron_jobs j ON r.job_id=j.job_id ORDER BY r.started_at_ms DESC,r.receipt_id DESC LIMIT ? OFFSET ?',(limit,offset))
            extra = rows(mango,'SELECT day,stage,status,started,finished,substr(error,1,4000) AS error FROM invest_runs ORDER BY started DESC,id DESC LIMIT ? OFFSET ?',(limit,offset))
        else:
            runs = rows(lychee/'cron/executions.db','SELECT status,started_at,finished_at,substr(error,1,4000) AS error,delivery_outcome FROM executions ORDER BY started_at DESC,id DESC LIMIT ? OFFSET ?',(limit,offset))
            extra = rows(lychee/'state.db','SELECT source,started_at,last_activity_at,ended_at,message_count,tool_call_count FROM sessions ORDER BY last_activity_at DESC,id DESC LIMIT ? OFFSET ?',(limit,offset))
        tasks = rows(mango,'SELECT status,created,updated,acknowledged,kind,substr(result,1,4000) AS result,substr(error,1,4000) AS error FROM tasks WHERE agent=? ORDER BY created DESC,id DESC LIMIT ? OFFSET ?',(agent,limit,offset))
        result={'offset':offset,'limit':limit,'runs':runs,'investment_runs' if agent=='olive' else 'session_activity':extra,'page_tasks':tasks,
                'pagination':'Each stream uses the same offset/limit; stop a stream when fewer than limit rows remain.'}
        if agent=='olive':
            with readonly(mango) as c:
                available=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='invest_market_requests'").fetchone()
                readiness=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='invest_readiness'").fetchone()
            if readiness:
                result['readiness']=rows(mango,'SELECT day,state,claimed,substr(checks,1,16000) AS checks,substr(errors,1,16000) AS errors FROM invest_readiness ORDER BY day DESC LIMIT ? OFFSET ?',(limit,offset))
            if available:
                result['market_requests']=rows(mango,'SELECT r.day,r.stage,m.started,m.finished,m.ok,m.diagnostics FROM invest_market_requests m JOIN invest_runs r ON r.id=m.run_id ORDER BY m.id DESC LIMIT ? OFFSET ?',(limit,offset))
        return response(result)

    @app.get('/api/audit/lychee/results')
    def lychee_results():
        offset,limit = pagination()
        notes_dir = weekend/'notes'
        if notes_dir.resolve()!=notes_dir.absolute(): abort(503,'Audit source unavailable')
        notes = sorted(itertools.islice((p for p in notes_dir.glob('*.md') if re.fullmatch(r'[\w.-]{1,100}\.md',p.name)),1000))
        return response({'state':document(weekend/'STATE.md'),'journal':document(weekend/'JOURNAL.md'),
                         'lessons':document(weekend/'LESSONS.md'),'offset':offset,'limit':limit,
                         'notes':[{'name':p.name,**document(p)} for p in notes[offset:offset+limit]],
                         'notes_index_capped':len(notes)==1000})

    @app.get('/api/audit/olive/ledger')
    def olive_ledger():
        offset,limit = pagination()
        from investment import replay
        with readonly(mango) as c:
            c.execute('BEGIN')
            size = c.execute('SELECT count(*),coalesce(sum(length(payload)),0) FROM invest_events').fetchone()
            if size[0]>5000 or size[1]>8*1024*1024: abort(503,'Ledger exceeds online audit budget; maintainer review required')
            account = replay(c)
            journal = [dict(r) for r in c.execute('SELECT id,kind,day,at,payload,previous,digest FROM invest_events ORDER BY id DESC LIMIT ? OFFSET ?',(limit,offset))]
            for event in journal: event['payload']=json.loads(event['payload'])
        return response({'account':account,'offset':offset,'limit':limit,'total':size[0],'events':journal,
                         'integrity':'Original ledger hash chain checked before projection; text in the projection may be redacted.'})

    @app.get('/api/audit/olive/evidence')
    def olive_evidence():
        offset,limit = pagination()
        return response({'offset':offset,'limit':limit,'evidence':rows(mango,'SELECT id,at,substr(url,1,2000) AS url,event_date,published_at FROM invest_evidence ORDER BY at DESC,id DESC LIMIT ? OFFSET ?',(limit,offset)),
                         'scope':'Evidence metadata and source URLs only; raw fetched bodies excluded.'})

    @app.errorhandler(sqlite3.Error)
    def audit_database_error(error):
        if request.path.startswith('/api/audit'): return jsonify(error='Audit source unavailable'),503
        raise error
