"""Mangosalad: a small private shelf of persistent interactive pages."""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from reminders import install as install_reminders, reconcile
from tasks import install as install_tasks, cancel_page
from datetime import timedelta, date, datetime, timezone
from pathlib import Path

from flask import Flask, abort, jsonify, request, session, send_from_directory, Response
from werkzeug.security import generate_password_hash, check_password_hash

ROOT = Path(__file__).parent
DATA = Path(os.environ.get('MANGO_DATA', ROOT / 'data'))
DATA.mkdir(parents=True, exist_ok=True)
CONFIG = DATA / 'private.json'
if not CONFIG.exists():
    fd = os.open(CONFIG, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump({'secret': secrets.token_hex(32), 'agents': {
            name: secrets.token_urlsafe(32) for name in ('lychee', 'olive')}}, f)
private = json.loads(CONFIG.read_text())
app = Flask(__name__, static_folder='static')
app.config.update(SECRET_KEY=private['secret'], MAX_CONTENT_LENGTH=2*1024*1024,
                  SESSION_COOKIE_SECURE=os.environ.get('MANGO_INSECURE') != '1',
                  SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict',
                  PERMANENT_SESSION_LIFETIME=timedelta(days=30))

def db():
    c = sqlite3.connect(DATA / 'mango.sqlite', timeout=10)
    c.row_factory = sqlite3.Row
    return c

with db() as c:
    c.executescript('''
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS pages (
      id TEXT PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL,
      content TEXT NOT NULL, state TEXT NOT NULL, pinned INTEGER NOT NULL DEFAULT 0,
      archived INTEGER NOT NULL DEFAULT 0, author TEXT NOT NULL,
      revision INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL, updated REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS page_focus (page_id TEXT PRIMARY KEY, focus_date TEXT);
    CREATE TABLE IF NOT EXISTS desktop_order (id INTEGER PRIMARY KEY, revision INTEGER NOT NULL, ids TEXT NOT NULL);
    INSERT OR IGNORE INTO desktop_order VALUES (1,1,'[]');
    CREATE TABLE IF NOT EXISTS attempts (ip TEXT NOT NULL, at REAL NOT NULL);
    ''')

def setting(key):
    with db() as c:
        row = c.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return row['value'] if row else None

def save_setting(c, key, value):
    c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, value))

def actor():
    token = request.headers.get('Authorization', '').removeprefix('Bearer ')
    if token and request.remote_addr in ('127.0.0.1', '::1') and not request.headers.get('X-Forwarded-For'):
        for name, value in private['agents'].items():
            if hmac.compare_digest(token, value):
                return name
    if os.environ.get('MANGO_PUBLIC') == '1':
        return 'you'
    if session.get('owner') and session.get('generation') == setting('generation'):
        return 'you'
    abort(401, '请先登录。')

@app.before_request
def protect():
    if request.method in ('POST', 'PATCH', 'DELETE'):
        if not request.is_json or request.headers.get('X-Mango-Request') != '1':
            abort(403, '请求格式不正确，请刷新页面。')
        origin = request.headers.get('Origin')
        if origin and origin != request.host_url.rstrip('/'):
            # nginx supplies HTTPS via the trusted local proxy below.
            expected = 'https://' + request.host
            if origin != expected:
                abort(403, '请求来源不匹配。')
    if request.path.startswith('/api/pages'):
        actor()

@app.after_request
def headers(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    if request.endpoint == 'render_canvas':
        response.headers.pop('X-Frame-Options', None)
        response.headers['Content-Security-Policy'] = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; connect-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'; sandbox allow-scripts"
    return response

@app.errorhandler(400)
@app.errorhandler(401)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(409)
@app.errorhandler(413)
@app.errorhandler(429)
def error(e):
    return jsonify(error=e.description), e.code

@app.get('/')
def index():
    return send_from_directory(ROOT / 'static', 'index.html')

@app.get('/health')
def health():
    with db() as c:
        c.execute('SELECT 1').fetchone()
    return {'ok': True}

@app.get('/api/session')
def session_info():
    public = os.environ.get('MANGO_PUBLIC') == '1'
    return {'authenticated': public or bool(session.get('owner') and session.get('generation') == setting('generation')),
            'public': public,
            'configured': bool(setting('password'))}

@app.post('/api/login')
def login():
    if os.environ.get('MANGO_PUBLIC') == '1':
        abort(404, '当前无需登录。')
    body = request.get_json()
    if not isinstance(body, dict): abort(400, '请求格式不正确。')
    password = body.get('password', '')
    if not isinstance(password, str) or len(password) > 256: abort(400, '密码格式不正确。')
    ip = request.headers.get('X-Real-IP', request.remote_addr)
    with db() as c:
        c.execute('DELETE FROM attempts WHERE at < ?', (time.time()-900,))
        if c.execute('SELECT COUNT(*) FROM attempts WHERE ip=?', (ip,)).fetchone()[0] >= 10:
            abort(429, '尝试次数较多，请 15 分钟后再试。')
        c.execute('INSERT INTO attempts VALUES (?,?)', (ip, time.time()))
    encoded = setting('password')
    if not encoded:
        token = body.get('setup', '')
        if not isinstance(token, str): abort(403, '初始化链接无效。')
        digest = hashlib.sha256(token.encode()).hexdigest()
        if not hmac.compare_digest(digest, setting('setup_hash') or '') or time.time() > float(setting('setup_expires') or 0):
            abort(403, '请使用有效的首次登录链接。')
        if len(password) < 10: abort(400, '请设置至少 10 个字符的密码。')
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute("SELECT 1 FROM settings WHERE key='password'").fetchone():
                abort(409, '账号已设置，请直接登录。')
            save_setting(c, 'password', generate_password_hash(password))
            save_setting(c, 'generation', secrets.token_hex(16))
            c.execute("DELETE FROM settings WHERE key IN ('setup_hash','setup_expires')")
    elif not check_password_hash(encoded, password):
        abort(401, '密码不正确。')
    session.clear()
    session.permanent = True
    session.update(owner=True, generation=setting('generation'))
    with db() as c: c.execute('DELETE FROM attempts WHERE ip=?', (ip,))
    return {'ok': True}

@app.post('/api/logout')
def logout():
    session.clear()
    return {'ok': True}

def decode(row):
    result = dict(row)
    for k in ('state', 'content'): result[k] = json.loads(result[k])
    result['url'] = '/#page=' + result['id']
    return result

def validate(body, creating=False):
    if not isinstance(body, dict): abort(400, '页面内容应为对象。')
    allowed = {'title', 'kind', 'content', 'state', 'pinned', 'archived', 'revision', 'focus_date'}
    if set(body) - allowed: abort(400, '包含不支持的字段。')
    if creating and not {'title', 'kind'} <= set(body): abort(400, '需要标题和页面类型。')
    if 'title' in body and (not isinstance(body['title'], str) or not 1 <= len(body['title'].strip()) <= 120):
        abort(400, '标题需要 1–120 个字符。')
    if 'kind' in body and body['kind'] not in ('checklist', 'canvas'): abort(400, '不支持的页面类型。')
    if 'state' in body and not isinstance(body['state'], dict): abort(400, '页面状态应为对象。')
    if 'content' in body and not isinstance(body['content'], dict): abort(400, '页面内容应为对象。')
    if body.get('focus_date') is not None:
        try:
            if date.fromisoformat(body['focus_date']).isoformat()!=body['focus_date']: raise ValueError()
        except (ValueError, TypeError): abort(400, '关注日期应为 YYYY-MM-DD，或留空。')
    for k in ('pinned', 'archived'):
        if k in body and type(body[k]) is not bool: abort(400, '状态应为 true 或 false。')

def validate_page(kind, content, state):
    if kind == 'canvas':
        if not isinstance(content.get('html'), str) or len(content['html']) > 500000:
            abort(400, '自定义页面需要有效的 HTML，最多 500 KB。')
    else:
        items = state.get('items', [])
        if not isinstance(items, list) or len(items) > 1000: abort(400, '清单最多 1000 项。')
        ids = set()
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not 1 <= len(item['id']) <= 100 or item['id'] in ids:
                abort(400, '清单项目需要互不重复的编号。')
            if not isinstance(item.get('text'), str) or not 1 <= len(item['text'].strip()) <= 500 or type(item.get('done', False)) is not bool:
                abort(400, '清单项目内容不正确。')
            ids.add(item['id'])

@app.get('/api/pages')
def pages():
    with db() as c:
        rows = c.execute('SELECT pages.*,page_focus.focus_date FROM pages LEFT JOIN page_focus ON pages.id=page_focus.page_id ORDER BY pinned DESC,updated DESC,id').fetchall()
        order = c.execute('SELECT * FROM desktop_order WHERE id=1').fetchone()
    ranks={pid:i for i,pid in enumerate(json.loads(order['ids']))}
    rows=sorted(rows,key=lambda r:ranks.get(r['id'],-1))
    through=datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    result = []
    for row in rows:
        p = decode(row)
        items = p['state'].get('items', []) if p['kind'] == 'checklist' else []
        p['needs_focus']=bool(not p['archived'] and p['focus_date'] and p['focus_date']<=through)
        p['total'] = len(items)
        p['done'] = sum(bool(i.get('done')) for i in items)
        p['preview'] = [i['text'] for i in items if not i.get('done')][:3]
        del p['content'], p['state']
        result.append(p)
    return {'pages': result, 'order_revision':order['revision'], 'focus_through':through}

@app.post('/api/pages/order')
def order_pages():
    body=request.get_json()
    if not isinstance(body,dict) or type(body.get('revision')) is not int:abort(400,'需要排序版本。')
    ids=body.get('ids')
    if not isinstance(ids,list) or not ids or any(not isinstance(x,str) for x in ids) or len(set(ids))!=len(ids):abort(400,'页面编号不得重复或为空。')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        order=c.execute('SELECT * FROM desktop_order WHERE id=1').fetchone()
        if order['revision']!=body['revision']:abort(409,'顺序刚被修改，请刷新后重试。')
        all_ids=[r['id'] for r in c.execute('SELECT id FROM pages ORDER BY pinned DESC,updated DESC,id')]
        if not set(ids)<=set(all_ids):abort(409,'页面已变化，请刷新后重试。')
        saved=[x for x in json.loads(order['ids']) if x in all_ids]
        current=[x for x in all_ids if x not in saved]+saved
        # Reorder only visible slots, preserving hidden pages' relative positions.
        selected=set(ids); replacements=iter(ids)
        merged=[next(replacements) if x in selected else x for x in current]
        c.execute('UPDATE desktop_order SET ids=?,revision=revision+1 WHERE id=1',(json.dumps(merged),))
    return {'ok':True,'revision':order['revision']+1}

@app.post('/api/pages')
def create():
    body = request.get_json()
    validate(body, True)
    content, state = body.get('content', {}), body.get('state', {})
    validate_page(body['kind'], content, state)
    page_id, now = secrets.token_urlsafe(9), time.time()
    with db() as c:
        c.execute('INSERT INTO pages VALUES (?,?,?,?,?,?,?,?,?,?,?)', (
            page_id, body['title'].strip(), body['kind'], json.dumps(content), json.dumps(state),
            bool(body.get('pinned')), bool(body.get('archived')), actor(), 1, now, now))
        c.execute('INSERT INTO page_focus VALUES (?,?)',(page_id,body.get('focus_date')))
    return get_page(page_id), 201

@app.get('/api/pages/<page_id>')
def get_page(page_id):
    with db() as c:
        row = c.execute('SELECT pages.*,page_focus.focus_date FROM pages LEFT JOIN page_focus ON pages.id=page_focus.page_id WHERE pages.id=?', (page_id,)).fetchone()
    if not row: abort(404, '这个页面不存在或已删除。')
    return decode(row)

@app.get('/api/pages/<page_id>/render')
def render_canvas(page_id):
    page = get_page(page_id)
    if page['kind'] != 'canvas': abort(404, '不是自定义页面。')
    return Response('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' + page['content']['html'], mimetype='text/html')

@app.patch('/api/pages/<page_id>')
def update(page_id):
    body = request.get_json()
    validate(body)
    if type(body.get('revision')) is not int: abort(400, '请先读取页面的最新版本。')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT pages.*,page_focus.focus_date FROM pages LEFT JOIN page_focus ON pages.id=page_focus.page_id WHERE pages.id=?', (page_id,)).fetchone()
        if not row: abort(404, '这个页面不存在或已删除。')
        old = decode(row)
        if body['revision'] != old['revision']: abort(409, '页面刚被修改，请重新读取后再修改。你的更改尚未保存。')
        new = old | body
        if 'focus_date' in body:c.execute('INSERT OR REPLACE INTO page_focus VALUES (?,?)',(page_id,body['focus_date']))
        if new['kind'] != old['kind']: abort(400, '已有页面不能更换类型，请另建页面。')
        validate_page(new['kind'], new['content'], new['state'])
        reconcile(c, page_id, new['state'], bool(new['archived']))
        if new['archived']: cancel_page(c, page_id)
        c.execute('UPDATE pages SET title=?,content=?,state=?,pinned=?,archived=?,author=?,revision=revision+1,updated=? WHERE id=?', (
            new['title'].strip(), json.dumps(new['content']), json.dumps(new['state']),
            bool(new['pinned']), bool(new['archived']), actor(), time.time(), page_id))
    return get_page(page_id)

@app.delete('/api/pages/<page_id>')
def delete(page_id):
    body = request.get_json()
    if not isinstance(body, dict) or type(body.get('revision')) is not int: abort(400, '需要页面版本。')
    with db() as c:
        result = c.execute('DELETE FROM pages WHERE id=? AND revision=?', (page_id, body['revision']))
        if not result.rowcount: abort(409, '页面已变化，请刷新后再删除。')
        c.execute('DELETE FROM page_focus WHERE page_id=?', (page_id,))
        c.execute('DELETE FROM reminders WHERE page_id=?', (page_id,))
        cancel_page(c, page_id)
        c.execute("UPDATE tasks SET snapshot='{}',instructions='',result=NULL WHERE page_id=?",(page_id,))
    return {'ok': True}

task_owner, task_enabled = install_reminders(app, db, actor, setting, save_setting)
install_tasks(app, db, actor, task_owner, task_enabled)

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'setup-link':
        if setting('password'): raise SystemExit('Already configured; no setup link generated.')
        token = secrets.token_urlsafe(32)
        with db() as c:
            save_setting(c, 'setup_hash', hashlib.sha256(token.encode()).hexdigest())
            save_setting(c, 'setup_expires', str(time.time()+86400))
        print('https://mangosalad.cn/#setup=' + token)
    else:
        app.run(host='127.0.0.1', port=5010)
