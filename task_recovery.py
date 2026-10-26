
"""Bounded, non-notifying late-result collection for the existing macro project."""
import hashlib
import json
import sqlite3
import time
from pathlib import Path

PAGE = 'hM5d9av_ph0n'
MAX_ATTEMPTS = 10
INTERVAL = 60
WINDOW = 600


def scoped(task):
    return task['page_id'] == PAGE and task['agent'] == 'olive'


def outcome(task, raw, returncode, expired, acknowledged):
    """Keep transport metadata separate from the model's business envelope."""
    if not scoped(task):
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        data = {}
    if isinstance(data, dict) and data.get('status') == 'timeout':
        phase = data.get('timeoutPhase')
        reason = 'provider_timeout' if phase == 'provider' else 'gateway_timeout'
        text = '执行等待已超时；后台停止未确认。结果将只读核对，不自动重跑；请勿直接重复提交。'
    elif expired:
        reason, text = 'worker_deadline', '派工等待期限已到；请核对停止回执与实际结果，不自动重跑。'
    elif returncode:
        reason, text = 'transport_exit', '派工客户端异常退出；后台是否仍执行尚未确认，不自动重跑。'
    elif not acknowledged:
        reason, text = 'ack_missing', '尚未取得有效接单回执；执行状态需核对，不自动重跑。'
    else:
        return None
    return dict(status='interrupted', message=text, error=reason+': '+text,
                recover=reason in ('provider_timeout', 'gateway_timeout', 'transport_exit'))


def save(path, data):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    temp.replace(path)


def register(folder, task, now=None):
    path = folder/'recovery.json'
    if path.exists():
        return
    now = time.time() if now is None else now
    save(path, dict(task_id=task['id'], session_key='agent:main:mangosalad:'+task['id'],
                   created=now, deadline=now+WINDOW, next_check=now, attempts=0, state='pending'))


def visible_result(database, session_key, parse):
    """No credentials, Gateway RPC, model calls or writes to native session storage."""
    with sqlite3.connect('file:'+str(database)+'?mode=ro', uri=True, timeout=2) as c:
        c.execute('PRAGMA query_only=ON')
        row = c.execute('SELECT current_session_id FROM session_nodes WHERE session_key=?', (session_key,)).fetchone()
        if not row:
            return None
        # Bound both row count and materialized bytes; oversized events stay unverified.
        rows = c.execute('SELECT seq, CASE WHEN length(event_json)<=262144 THEN event_json ELSE NULL END '
                         'FROM transcript_events WHERE session_id=? ORDER BY seq DESC LIMIT 64', (row[0],)).fetchall()
    for seq, raw in rows:
        if raw is None:
            continue
        event = json.loads(raw)
        if not isinstance(event, dict):
            continue
        message = event.get('message', {})
        if not isinstance(message, dict):
            continue
        if message.get('role') != 'assistant' or message.get('stopReason') != 'stop':
            continue
        content = message.get('content', [])
        text = '\n'.join(item.get('text', '') for item in content
                         if isinstance(item, dict) and item.get('type') == 'text') if isinstance(content, list) else ''
        if not text or len(text) > 16000:
            continue
        try:
            result = parse(text)
        except (ValueError, TypeError, KeyError):
            continue
        return dict(session_id=row[0], seq=seq, result=result,
                    digest=hashlib.sha256(text.encode()).hexdigest())
    return None


def collect(db, data, database, parse, now=None):
    """At most four receipts per existing worker tick; no sends or task starts."""
    now = time.time() if now is None else now
    with db() as c:
        rows = c.execute("SELECT * FROM tasks WHERE page_id=? AND agent='olive' AND status='interrupted' "
                         "ORDER BY created DESC LIMIT 20", (PAGE,)).fetchall()
    checks = 0
    for row in rows:
        task = dict(row);path = data/'task-runs'/task['id']/'recovery.json'
        if not path.exists():
            continue  # Historical tasks are never silently enrolled.
        receipt = json.loads(path.read_text())
        if receipt['state'] != 'pending' or now < receipt['next_check']:
            continue
        if now > receipt['deadline'] or receipt['attempts'] >= MAX_ATTEMPTS:
            receipt['state'] = 'unresolved';save(path, receipt);continue
        if checks >= 4:
            break
        checks += 1
        receipt['attempts'] += 1;receipt['next_check'] = now+INTERVAL
        save(path, receipt)  # Consume admission before the read; crash cannot spin/replay.
        try:
            found = visible_result(database, receipt['session_key'], parse)
        except (sqlite3.Error, OSError, ValueError, TypeError):
            receipt['last_read_error'] = 'native_result_unavailable';save(path, receipt);continue
        if not found:
            continue
        marker = '[迟到结果 '+found['digest'][:16]+']'
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            current = c.execute('SELECT status,result,revision FROM tasks WHERE id=?', (task['id'],)).fetchone()
            if not current or current['status'] != 'interrupted':
                receipt['state'] = 'state_changed';save(path, receipt);continue
            if marker not in (current['result'] or ''):
                text = (current['result'] or '')+'\n\n'+marker+'\n已回收到原会话的最终文本，尚未验收；这不证明后台停止或页面写入正确。\n'+found['result']['message'][:8000]
                c.execute('UPDATE tasks SET result=?,revision=revision+1,updated=? WHERE id=? AND revision=?',
                          (text,now,task['id'],current['revision']))
        # Preserve original status/error/notification receipt; this is not acceptance.
        receipt.update(state='recovered_unreviewed', evidence=found)
        save(path, receipt)
