"""Durable, bounded data checks before settlement and the single model run."""
import json
import uuid
from datetime import datetime, timedelta
from investment import now, dump, events, replay, settle, append
from invest_daily import RULES_DAILY, pending, probe, save_probe

RULES_READY={**RULES_DAILY,'version':'2.1-ready','effective_day':'2026-10-16',
    'settle':'16:30','research':'16:30','deadline':'19:00','latest_research_start':'18:50',
    'readiness_slots':['16:30','17:00','17:30','18:00','18:30'],
    'readiness_check_window_seconds':300,'research_delay_seconds':300,
    'execution':'T日完整日线研究，下一交易日收盘价模拟撮合。16:30起每30分钟检查数据，18:30最后一轮；不重做终态。研究19:00截止。',
    'readiness':'最多5轮；每轮在计划时间起5分钟内完成有限检查，不补过期轮次。18:30最后一轮，18:35停止一切就绪取数并按现有逐标的标准结算，缺数拒单。等待不调用模型；模型最多8分钟。',
    'first_day':'本版本生效不重启实验；正常处理此前冻结且执行日为今日的日线订单。已结束研究或结算绝不重做。'}


def schedule(db):
    stamp=now()
    if stamp.date().isoformat()>=RULES_READY['effective_day']:raise ValueError('Schedule before effective day')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute("SELECT 1 FROM invest_events WHERE event_key='rules:2.0-daily'").fetchone():raise ValueError('Daily mode required')
        append(c,'rules:2.1-ready','rules',RULES_READY['effective_day'],RULES_READY)


def status(db,day):
    with db() as c:r=c.execute('SELECT day,state,checks,errors FROM invest_readiness WHERE day=?',(day,)).fetchone()
    if not r:return None
    return {**dict(r),'checks':json.loads(r['checks']),'errors':json.loads(r['errors'])}


def advance(db,stamp=None):
    """Return True only when today's settlement is terminal. Never invoke a model."""
    from invest_daily import rules
    from invest_market import diagnostic
    stamp=stamp or now();day=stamp.date().isoformat()
    if rules(db,day)['version']!=RULES_READY['version']:raise ValueError('Readiness mode not effective')
    slots=[stamp.replace(hour=int(s[:2]),minute=int(s[3:]),second=0,microsecond=0) for s in RULES_READY['readiness_slots']]
    if stamp<slots[0]:return False
    window=timedelta(seconds=RULES_READY['readiness_check_window_seconds'])
    owner=uuid.uuid4().hex
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT 1 FROM invest_events WHERE event_key=?',('settled:'+day,)).fetchone():
            c.execute("UPDATE invest_readiness SET state='settled',owner=NULL WHERE day=?",(day,))
            return True
        c.execute("INSERT OR IGNORE INTO invest_readiness(day,state) VALUES(?,'waiting')",(day,))
        r=dict(c.execute('SELECT * FROM invest_readiness WHERE day=?',(day,)).fetchone())
        if r['state']=='settled':return True
        if r['state'] in ('checking','finalizing') and stamp-datetime.fromisoformat(r['claimed'])<window:return False
        checks=json.loads(r['checks']);cache=json.loads(r['cache']);errors=json.loads(r['errors'])
        if r['state']=='checking':
            checks[-1]['state']='interrupted'
        slot=max(i for i,s in enumerate(slots) if s<=stamp)
        used={x['slot'] for x in checks}
        finalizing=r['state']=='finalizing' or stamp>=slots[-1]+window
        if not finalizing and (slot in used or stamp>=slots[slot]+window):
            c.execute("UPDATE invest_readiness SET state='waiting',owner=NULL,checks=? WHERE day=?",(dump(checks),day))
            return False
        account=replay(c)
        symbols=sorted(set(account['positions'])|{'sh000300'}|{o['symbol'] for report in pending(c,day) for o in report['payload']['orders']})
        if not finalizing:checks.append({'slot':slot,'scheduled':slots[slot].isoformat(),'started':stamp.isoformat(),'state':'checking'})
        c.execute('UPDATE invest_readiness SET state=?,owner=?,claimed=?,checks=? WHERE day=?',
            ('finalizing' if finalizing else 'checking',owner,stamp.isoformat(),dump(checks),day))
    if not finalizing:
        # One bounded request per symbol per slot. Checkpoint each result before the next.
        for symbol in symbols:
            current=now()
            if current.date().isoformat()!=day or current>=slots[slot]+window:break
            if errors.get(symbol,{}).get('http_status') in (401,403):continue
            try:
                q=probe(db,symbol)
                if q['day']!=day:raise ValueError('Cross-day probe')
                cache[symbol]=q
                if q['verified']:errors.pop(symbol,None)
                else:errors[symbol]={'category':'daily_verification_failed'}
            except Exception as e:
                cache.pop(symbol,None);errors[symbol]=diagnostic(e)
            with db() as c:
                c.execute('BEGIN IMMEDIATE')
                if c.execute('UPDATE invest_readiness SET cache=?,errors=? WHERE day=? AND owner=?',
                    (dump(cache),dump(errors),day,owner)).rowcount!=1:return False
        checks[-1]['finished']=now().isoformat();checks[-1]['state']='checked'
        fresh=lambda q:q['day']==day and q['verified'] and 0<=(now()-datetime.fromisoformat(q['observed_at'])).total_seconds()<=RULES_READY['quote_max_age_seconds']
        finalizing=slot==4 or all(s in cache and fresh(cache[s]) for s in symbols)
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('UPDATE invest_readiness SET state=?,checks=? WHERE day=? AND owner=?',
                ('finalizing' if finalizing else 'waiting',dump(checks),day,owner)).rowcount!=1:return False
        if not finalizing:return False
    # Only current-day cached observations may be persisted; their actual acquisition time is unchanged.
    if now().date().isoformat()!=day:return False
    with db() as c:
        if c.execute('SELECT owner FROM invest_readiness WHERE day=?',(day,)).fetchone()[0]!=owner:return False
    quotes={}
    for symbol in symbols:
        q=cache.get(symbol)
        if q and q['day']==day and 0<=(now()-datetime.fromisoformat(q['observed_at'])).total_seconds()<=RULES_READY['quote_max_age_seconds']:
            quotes[symbol]=save_probe(db,q)
        else:errors.setdefault(symbol,{'category':'daily_bar_unavailable_at_cutoff'})
    settle(db,day,quotes,now())
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        append(c,'readiness:'+day,'readiness',day,{'rules_version':RULES_READY['version'],'checks':checks,'errors':errors,'symbols':symbols})
        c.execute("UPDATE invest_readiness SET state='settled',owner=NULL,checks=?,errors=? WHERE day=?",(dump(checks),dump(errors),day))
    return True
