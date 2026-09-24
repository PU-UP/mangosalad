"""Page-level assignments, with explicit confirmation and Agent acknowledgement."""
import json
import secrets
import time
from datetime import datetime
from flask import abort, request

ACTIVE = ('queued','dispatching','running','cancelling')


def cancel_page(c, page_id):
    now=time.time()
    c.execute("UPDATE tasks SET status=CASE WHEN status='queued' THEN 'cancelled' ELSE 'cancelling' END, revision=revision+1,updated=? WHERE page_id=? AND status IN ('queued','dispatching','running')",(now,page_id))


def task_state(row):
    if row['status']=='cancelled':return 'cancelled'
    delivered=bool(row['receipt'])
    if delivered and not row['error'] and (row['status']=='completed' or row['status']=='needs_input' and row['kind'] in ('reminder','discussion')):
        return 'done'
    return 'waiting'


def can_cancel(row):
    return task_state(row)=='waiting' and (row['status'] in ACTIVE+('failed','interrupted') or bool(row['receipt'] or row['error']))


def install(app,db,actor,owner,enabled):
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY, page_id TEXT NOT NULL, agent TEXT NOT NULL,
          run_at REAL NOT NULL, instructions TEXT NOT NULL, snapshot TEXT NOT NULL,
          status TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
          created REAL NOT NULL, updated REAL NOT NULL, acknowledged REAL,
          result TEXT, error TEXT, session_id TEXT, receipt TEXT, kind TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS tasks_one_active ON tasks(page_id)
          WHERE status IN ('queued','dispatching','running','cancelling');
        ''')

    def public(row):
        d=dict(row);d['status']=task_state(row);d['active']=row['status'] in ACTIVE
        d['can_cancel']=can_cancel(row)
        d['delivered']=bool(d.get('receipt'));d.pop('snapshot',None);d.pop('receipt',None)
        return d

    @app.get('/api/pages/<page_id>/tasks')
    def page_tasks(page_id):
        with db() as c:
            rows=c.execute('SELECT * FROM tasks WHERE page_id=? ORDER BY created DESC LIMIT 10',(page_id,)).fetchall()
        return {'tasks':[public(r) for r in rows],'enabled':enabled()}

    @app.post('/api/pages/<page_id>/tasks')
    def assign_page(page_id):
        owner();b=request.get_json()
        if not isinstance(b,dict) or b.get('agent') not in ('lychee','olive'):abort(400,'请选择负责人。')
        note=b.get('instructions','')
        if not isinstance(note,str) or len(note)>2000:abort(400,'任务要求最多 2000 字。')
        now=time.time()
        try:
            dt=datetime.fromisoformat(b['run_at']) if b.get('run_at') else None
            if dt is not None and dt.tzinfo is None:raise ValueError()
            due=dt.timestamp() if dt else now
            if not now-60<=due<=now+366*86400:raise ValueError()
        except (TypeError,ValueError,OverflowError):abort(400,'请填写未来一年内的开始时间；留空则立即处理。')
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            p=c.execute('SELECT * FROM pages WHERE id=?',(page_id,)).fetchone()
            if not p or p['archived']:abort(400,'请先打开未收起的任务页面。')
            if type(b.get('page_revision')) is not int or b['page_revision']!=p['revision']:abort(409,'页面刚被修改，请刷新后确认任务内容。')
            old=c.execute("SELECT * FROM tasks WHERE page_id=? AND status IN ('queued','dispatching','running','cancelling')",(page_id,)).fetchone()
            if old:abort(409,'这份任务已有负责人。请先取消当前安排，再重新确认。')
            if c.execute("SELECT count(*) FROM tasks WHERE status IN ('queued','dispatching','running','cancelling')").fetchone()[0]>=20:abort(429,'当前待处理任务较多，请先完成或取消一些。')
            if c.execute('SELECT count(*) FROM tasks WHERE created>?',(now-86400,)).fetchone()[0]>=30:abort(429,'今日已提交 30 次，请明天再试。')
            snapshot={k:p[k] for k in ('id','title','kind','revision')}
            snapshot['state']=json.loads(p['state']);snapshot['content']=json.loads(p['content'])
            if len(json.dumps(snapshot,ensure_ascii=False).encode())>60000:abort(400,'页面内容过大，请简化后再交给 Agent。')
            tid=secrets.token_hex(16)
            c.execute('INSERT INTO tasks (id,page_id,agent,run_at,instructions,snapshot,status,created,updated) VALUES (?,?,?,?,?,?,\'queued\',?,?)',(tid,page_id,b['agent'],due,note.strip(),json.dumps(snapshot,ensure_ascii=False),now,now))
        return {'id':tid,'status':'waiting'},201

    @app.delete('/api/tasks/<tid>')
    def cancel_task(tid):
        owner();b=request.get_json()
        if not isinstance(b,dict) or type(b.get('revision')) is not int:abort(400)
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            r=c.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone()
            if not r:abort(404)
            if r['revision']!=b['revision']:abort(409,'任务状态刚变化，请刷新后重试。')
            if not can_cancel(r):abort(409,'这次任务已结束或正在确认发送，请刷新后重试。')
            status='cancelling' if r['status'] in ('dispatching','running','cancelling') else 'cancelled'
            c.execute('UPDATE tasks SET status=?,revision=revision+1,updated=? WHERE id=?',(status,time.time(),tid))
        return {'status':'cancelled' if status=='cancelled' else 'waiting'}

    @app.get('/api/tasks')
    def agent_tasks():
        name=actor()
        if name not in ('lychee','olive'):abort(403)
        with db() as c:rows=c.execute('SELECT * FROM tasks WHERE agent=? ORDER BY created DESC LIMIT 30',(name,)).fetchall()
        return {'tasks':[public(r) for r in rows]}

    @app.get('/api/tasks/<tid>')
    def agent_task(tid):
        name=actor()
        with db() as c:r=c.execute('SELECT * FROM tasks WHERE id=? AND agent=?',(tid,name)).fetchone()
        if not r:abort(404)
        d=public(r);d['snapshot']=json.loads(r['snapshot']);return d

    @app.post('/api/tasks/<tid>/ack')
    def task_ack(tid):
        name=actor()
        if name not in ('lychee','olive'):abort(403)
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            r=c.execute('SELECT * FROM tasks WHERE id=? AND agent=?',(tid,name)).fetchone()
            if not r:abort(404)
            if r['status']=='running':return {'status':'waiting'}
            if r['status']!='dispatching':abort(409,'任务已取消或不在接单阶段，请停止处理。')
            c.execute("UPDATE tasks SET status='running',acknowledged=?,revision=revision+1,updated=? WHERE id=?",(time.time(),time.time(),tid))
        return {'status':'waiting'}
