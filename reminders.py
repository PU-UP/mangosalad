"""Single-shot, fixed-recipient reminders. No model calls or arbitrary commands."""
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime
from flask import abort, request, session


def install(app, db, actor, setting, save_setting):
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS reminders (
          id TEXT PRIMARY KEY, page_id TEXT NOT NULL, item_id TEXT NOT NULL,
          agent TEXT NOT NULL, message TEXT NOT NULL, due REAL NOT NULL,
          status TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
          created REAL NOT NULL, updated REAL NOT NULL, receipt TEXT, error TEXT);
        CREATE INDEX IF NOT EXISTS reminders_due ON reminders(status,due);
        ''')

    def enabled():
        return bool(session.get('reminders') and
                    session['reminders'] == setting('reminder_generation'))

    def owner():
        if actor() in ('lychee', 'olive') or enabled(): return
        abort(403, '请先打开飞书中的「启用此设备」链接，无需密码。')

    @app.get('/api/reminder-access')
    def access():
        return {'enabled': enabled()}

    @app.post('/api/reminder-access')
    def activate():
        body = request.get_json()
        token = body.get('token', '') if isinstance(body, dict) else ''
        if not isinstance(token, str) or len(token) > 200: abort(400)
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            values = dict(c.execute("SELECT key,value FROM settings WHERE key LIKE 'reminder_%'"))
            if (not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), values.get('reminder_activation', ''))
                    or time.time() > float(values.get('reminder_activation_expires', '0'))):
                abort(403, '启用链接已失效，请在飞书让 lychee 或 olive 重新生成。')
            c.execute("DELETE FROM settings WHERE key='reminder_activation'")
            session['reminders'] = values['reminder_generation']
            session.permanent = True
        return {'enabled': True}

    @app.post('/api/reminder-link')
    def link():
        if actor() not in ('lychee','olive'): abort(403)
        return {'url':activation(db,save_setting)}

    @app.get('/api/pages/<page_id>/reminders')
    def listing(page_id):
        with db() as c:
            rows = c.execute('SELECT id,item_id,agent,message,due,status,revision,error FROM reminders WHERE page_id=? ORDER BY created', (page_id,)).fetchall()
        return {'reminders': [dict(r) for r in rows], 'enabled': enabled()}

    @app.post('/api/pages/<page_id>/reminders')
    def create_reminder(page_id):
        abort(410, '逐项安排已停用，请在页面顶部提交整份任务。')

    @app.delete('/api/reminders/<rid>')
    def cancel(rid):
        owner()
        b=request.get_json()
        if not isinstance(b,dict) or type(b.get('revision')) is not int: abort(400)
        with db() as c:
            r=c.execute("UPDATE reminders SET status='cancelled',revision=revision+1,updated=? WHERE id=? AND revision=? AND status IN ('pending','unscheduled')",(time.time(),rid,b['revision']))
            if not r.rowcount: abort(409,'提醒已变化或正在发送，请刷新。')
        return {'ok':True}

    return owner, enabled


def reconcile(c, page_id, state=None, archived=False):
    rows=c.execute("SELECT id,item_id FROM reminders WHERE page_id=? AND status IN ('pending','unscheduled')",(page_id,)).fetchall()
    active={x['id'] for x in (state or {}).get('items',[]) if not x.get('done')}
    for r in rows:
        if archived or r['item_id'] not in active:
            c.execute("UPDATE reminders SET status='cancelled',revision=revision+1,updated=? WHERE id=?",(time.time(),r['id']))


def activation(db, save_setting):
    token=secrets.token_urlsafe(32)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute("SELECT 1 FROM settings WHERE key='reminder_generation'").fetchone():
            save_setting(c,'reminder_generation',secrets.token_hex(32))
        save_setting(c,'reminder_activation',hashlib.sha256(token.encode()).hexdigest())
        save_setting(c,'reminder_activation_expires',str(time.time()+86400))
    return 'https://mangosalad.cn/#enable-reminders='+token
