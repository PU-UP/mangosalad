"""Olive's paper experiment. Money is integer fen; the journal is append-only."""
import hashlib
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from flask import abort, request, Response

TZ = timezone(timedelta(hours=8))
RULES = {
    'version': '1.0', 'initial_fen': 20000000, 'agent': 'olive',
    'market': '沪深主板普通A股；排除ST、退市整理及无涨跌幅限制新股',
    'research': '14:30', 'deadline': '14:55', 'settle': '15:10', 'review': '20:00',
    'timezone': 'Asia/Shanghai', 'fees': 0, 'slippage': 0,
    'execution': '截止前锁定数量；当日核验收盘价模拟；涨跌停双向不成交',
    'capital': '不透支、不卖空、不杠杆；T+1；买入100股整数倍；无仓位上限',
    'horizon_days': 89, 'benchmark': '沪深300价格指数（不含分红），同日起点',
    'goal': '首期89个自然日争取正收益；不得重置亏损或顺延原判断',
    'calendar_source': 'https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml',
    'calendar_year': 2026,
}
HOLIDAYS = [('01-01','01-03'),('02-15','02-23'),('04-04','04-06'),
            ('05-01','05-05'),('06-19','06-21'),('09-25','09-27'),('10-01','10-07')]


def now(): return datetime.now(TZ)
def dump(x): return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
def fen(x):
    n = Decimal(str(x))
    if not n.is_finite() or n <= 0: raise ValueError('价格无效')
    return int((n * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def trading_day(day):
    d = date.fromisoformat(day)
    if d.year != RULES['calendar_year']: raise ValueError('交易日历未覆盖该年，暂停并更新官方日历')
    return d.weekday() < 5 and not any(a <= day[5:] <= b for a, b in HOLIDAYS)


def symbol_ok(symbol):
    return isinstance(symbol, str) and bool(re.fullmatch(r'(sh60[0135]\d{3}|sz00[0123]\d{3})', symbol))


def schema(db):
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS invest_events (
          id INTEGER PRIMARY KEY, event_key TEXT UNIQUE NOT NULL, kind TEXT NOT NULL,
          day TEXT NOT NULL, at TEXT NOT NULL, payload TEXT NOT NULL,
          previous TEXT NOT NULL, digest TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS invest_evidence (
          id TEXT PRIMARY KEY, at TEXT NOT NULL, url TEXT NOT NULL,
          event_date TEXT, published_at TEXT, raw TEXT NOT NULL, digest TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS invest_runs (
          id TEXT PRIMARY KEY, day TEXT NOT NULL, stage TEXT NOT NULL,
          status TEXT NOT NULL, started TEXT NOT NULL, finished TEXT, error TEXT,
          UNIQUE(day,stage));
        CREATE TABLE IF NOT EXISTS invest_readiness (
          day TEXT PRIMARY KEY, state TEXT NOT NULL, owner TEXT, claimed TEXT,
          checks TEXT NOT NULL DEFAULT '[]', cache TEXT NOT NULL DEFAULT '{}',
          errors TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS invest_control (id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS invest_market_requests (
          id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, query TEXT NOT NULL,
          started TEXT NOT NULL, finished TEXT, ok INTEGER, diagnostics TEXT);
        CREATE INDEX IF NOT EXISTS invest_market_requests_run ON invest_market_requests(run_id,id);
        INSERT OR IGNORE INTO invest_control VALUES(1,0);
        CREATE TRIGGER IF NOT EXISTS invest_no_update BEFORE UPDATE ON invest_events
          BEGIN SELECT RAISE(ABORT,'journal is append-only'); END;
        CREATE TRIGGER IF NOT EXISTS invest_no_delete BEFORE DELETE ON invest_events
          BEGIN SELECT RAISE(ABORT,'journal is append-only'); END;
        CREATE TRIGGER IF NOT EXISTS evidence_no_update BEFORE UPDATE ON invest_evidence
          BEGIN SELECT RAISE(ABORT,'evidence is append-only'); END;
        CREATE TRIGGER IF NOT EXISTS evidence_no_delete BEFORE DELETE ON invest_evidence
          BEGIN SELECT RAISE(ABORT,'evidence is append-only'); END;
        ''')


def append(c, key, kind, day, payload, at=None):
    old = c.execute('SELECT * FROM invest_events WHERE event_key=?', (key,)).fetchone()
    if old:
        if old['payload'] != dump(payload): raise ValueError('记录编号已存在且内容不同，不能覆盖')
        return old['id']
    previous = c.execute('SELECT digest FROM invest_events ORDER BY id DESC LIMIT 1').fetchone()
    previous = previous[0] if previous else ''
    at = at or now().isoformat()
    raw = dump(payload)
    digest = hashlib.sha256(dump([key, kind, day, at, raw, previous]).encode()).hexdigest()
    return c.execute('INSERT INTO invest_events(event_key,kind,day,at,payload,previous,digest) VALUES(?,?,?,?,?,?,?)',
                     (key, kind, day, at, raw, previous, digest)).lastrowid


def evidence(db, url, raw, event_date=None, published_at=None):
    at = now().isoformat()
    digest = hashlib.sha256(raw.encode()).hexdigest()
    eid = hashlib.sha256(dump([url, at, digest]).encode()).hexdigest()[:24]
    with db() as c:
        c.execute('INSERT INTO invest_evidence VALUES(?,?,?,?,?,?,?)', (eid, at, url, event_date, published_at, raw, digest))
    return eid


def events(c, kind=None):
    rows = c.execute('SELECT * FROM invest_events' + (' WHERE kind=?' if kind else '') + ' ORDER BY id', (kind,) if kind else ())
    return [{**dict(r), 'payload': json.loads(r['payload'])} for r in rows]


def replay(c, through=None):
    cash = 0; positions = {}; receivable = 0; previous = ''
    for r in events(c):
        expected = hashlib.sha256(dump([r['event_key'],r['kind'],r['day'],r['at'],dump(r['payload']),previous]).encode()).hexdigest()
        if r['previous'] != previous or r['digest'] != expected: raise ValueError('审计链核对失败')
        previous = expected; p = r['payload']
        if through and r['day']>through:continue
        if r['kind'] == 'start': cash += p['initial_fen']
        if r['kind'] == 'fill':
            symbol = p['symbol']; qty = p['qty']; value = qty * p['price_fen']
            pos = positions.setdefault(symbol, {'qty':0, 'lots':[], 'name':p['name']})
            if p['side'] == 'buy':
                cash -= value; pos['qty'] += qty; pos['lots'].append({'day':r['day'],'qty':qty})
            else:
                cash += value; pos['qty'] -= qty; left = qty
                for lot in pos['lots']:
                    sold = min(left, lot['qty']); lot['qty'] -= sold; left -= sold
                if left: raise ValueError('卖出超过持仓')
        if r['kind'] == 'dividend_due': receivable += p['amount_fen']
        if r['kind'] == 'dividend_paid': receivable -= p['amount_fen']; cash += p['amount_fen']
        if r['kind'] == 'shares':
            pos = positions[p['symbol']]; pos['qty'] += p['qty']
            pos['lots'].append({'day':r['day'], 'qty':p['qty']})
        if cash < 0 or receivable < 0 or any(x['qty'] < 0 for x in positions.values()): raise ValueError('账本核对失败')
    return {'cash_fen':cash, 'receivable_fen':receivable, 'positions':{k:v for k,v in positions.items() if v['qty']}}


def start(db, day):
    if not trading_day(day): raise ValueError('实验起点必须为交易日')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if events(c, 'start'): raise ValueError('已有实验，不允许重置')
        append(c, 'rules:1.0', 'rules', day, RULES)
        append(c, 'start', 'start', day, {'initial_fen':RULES['initial_fen'], 'evaluate_on':(date.fromisoformat(day)+timedelta(days=89)).isoformat()})


def text_field(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 6000: raise ValueError('缺少或过长：'+name)


def submit(db, body, stamp=None):
    stamp = stamp or now(); day = stamp.date().isoformat(); hhmm = stamp.strftime('%H:%M')
    if not isinstance(body, dict) or set(body) != {'run_id','stage','summary','facts','inferences','uncertainties','counterevidence','judgments','orders','next_plan','reviews'}:
        raise ValueError('请使用技能中的完整报告结构，不接受账本余额或自定义时间')
    stage = body['stage']
    from invest_daily import active, adjacent, rules, RULES_DAILY
    daily=active(db)
    schedule=rules(db,day)
    if stage not in ('research','review'): raise ValueError('阶段无效')
    if not trading_day(day): raise ValueError('非交易日不接受投资报告')
    if stage == 'research' and not schedule['research'] <= hhmm < schedule['deadline']: raise ValueError('Outside research window '+schedule['research']+'-'+schedule['deadline']+'; no backfill')
    if stage == 'review' and not '20:00' <= hhmm < '21:00': raise ValueError('不在晚间复盘时间')
    for key in ('summary','inferences','uncertainties','counterevidence','next_plan'): text_field(body[key], key)
    for key in ('facts','judgments','orders','reviews'):
        if not isinstance(body[key],list) or len(body[key])>50: raise ValueError('列表格式无效：'+key)
    if stage == 'review' and body['orders']: raise ValueError('复盘不能下单')
    if stage == 'research' and body['orders'] and not body['facts']: raise ValueError('无可核验证据不得交易')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if not events(c,'start'): raise ValueError('实验尚未初始化')
        if not c.execute('SELECT enabled FROM invest_control').fetchone()[0]:raise ValueError('实验已暂停，不能提交新报告')
        run = c.execute('SELECT * FROM invest_runs WHERE id=? AND day=? AND stage=?',(body['run_id'],day,stage)).fetchone()
        if not run or run['status'] not in ('running','done'): raise ValueError('没有对应的有效olive运行')
        for fact in body['facts']:
            if not isinstance(fact,dict) or set(fact)!={'text','evidence_id','event_date'}: raise ValueError('事实需要正文、证据编号、事件日期（未知用null）')
            text_field(fact['text'],'fact')
            e=c.execute('SELECT * FROM invest_evidence WHERE id=?',(fact['evidence_id'],)).fetchone()
            if not e or datetime.fromisoformat(e['at'])>stamp: raise ValueError('证据不存在或晚于决策')
            if fact['event_date'] is not None: date.fromisoformat(fact['event_date'])
        symbols=set()
        for j in body['judgments']:
            if not isinstance(j,dict) or set(j)!={'symbol','action','reason','horizon_days','falsifier','risk','sizing','evidence_ids'}: raise ValueError('判断结构无效')
            if not symbol_ok(j['symbol']) or j['symbol'] in symbols: raise ValueError('标的不在范围或重复')
            symbols.add(j['symbol'])
            if j['action'] not in ('buy','sell','hold','watch'): raise ValueError('动作无效')
            if type(j['horizon_days']) is not int or not 1<=j['horizon_days']<=89: raise ValueError('观察期为1–89天')
            for k in ('reason','falsifier','risk','sizing'): text_field(j[k],k)
            if not isinstance(j['evidence_ids'],list) or not j['evidence_ids']: raise ValueError('判断须引用证据')
            for eid in j['evidence_ids']:
                e=c.execute('SELECT at FROM invest_evidence WHERE id=?',(eid,)).fetchone()
                if not e or datetime.fromisoformat(e['at'])>stamp: raise ValueError('判断证据无效')
        ordered=set()
        for order in body['orders']:
            if not isinstance(order,dict) or set(order)!={'symbol','side','qty','quote_id'}: raise ValueError('订单结构无效')
            symbol=order['symbol']; qty=order['qty']
            if symbol in ordered or not any(j['symbol']==symbol and j['action']==order['side'] for j in body['judgments']): raise ValueError('订单须对应唯一判断')
            ordered.add(symbol)
            if order['side'] not in ('buy','sell') or type(qty) is not int or qty<=0 or (order['side']=='buy' and qty%100): raise ValueError('数量/方向无效')
            q=c.execute("SELECT payload FROM invest_events WHERE event_key=? AND kind='quote'",('quote:'+order['quote_id'],)).fetchone()
            if not q: raise ValueError('缺少系统行情快照')
            q=json.loads(q[0])
            if q['symbol']!=symbol or not q['eligible'] or q['day']!=day or not q['verified']: raise ValueError('行情或标的资格未核验')
            age=(stamp-datetime.fromisoformat(q['observed_at'])).total_seconds()
            if daily and (q.get('rules_version')!=schedule['version'] or not q.get('final') or q.get('corporate_action')):raise ValueError('Daily quote not verified for this mode')
            if not 0<=age<=(schedule['quote_max_age_seconds'] if daily else 300): raise ValueError('Quote acquisition age exceeds mode limit; fetch again')
        for review in body['reviews']:
            if not isinstance(review,dict) or set(review)!={'report_id','symbol','verdict','reason','evidence_ids'}: raise ValueError('复核结构无效')
            if review['verdict'] not in ('pending','supported','refuted','unverifiable'): raise ValueError('复核结论无效')
            old=c.execute("SELECT payload FROM invest_events WHERE id=? AND kind='research'",(review['report_id'],)).fetchone()
            if not old or not any(j['symbol']==review['symbol'] for j in json.loads(old[0])['judgments']): raise ValueError('复核须关联原判断')
            text_field(review['reason'],'review reason')
            if not isinstance(review['evidence_ids'],list): raise ValueError('复核证据无效')
            if review['verdict'] in ('supported','refuted') and not review['evidence_ids']: raise ValueError('判断兑现/失败须引用证据')
            for eid in review['evidence_ids']:
                if not c.execute('SELECT 1 FROM invest_evidence WHERE id=? AND at<=?',(eid,stamp.isoformat())).fetchone(): raise ValueError('复核证据不存在')
        if daily:
            body={**body,'rules_version':schedule['version'],'research_day':day,'execution_day':adjacent(day) if stage=='research' else None}
        eid=append(c,stage+':'+day,stage,day,body,stamp.isoformat())
    return {'record_id':eid,'locked':True,'day':day}


def settle(db, day, quotes, stamp=None):
    stamp=stamp or now()
    from invest_daily import active, pending, rules, RULES_DAILY
    daily=active(db);schedule=rules(db,day)
    if stamp.date().isoformat()!=day or stamp.strftime('%H:%M')<schedule['settle'] or not trading_day(day): raise ValueError('只能在当日收盘核验后结算')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT 1 FROM invest_events WHERE event_key=?',('settled:'+day,)).fetchone(): return
        apply_dividends(c,day)
        reports=pending(c,day) if daily else [r for r in events(c,'research') if r['day']==day]
        account=replay(c)
        for index,order in enumerate(reports[0]['payload']['orders'] if reports else []):
            symbol=order['symbol']; q=quotes.get(symbol); reason=None
            if not q or not q.get('verified') or q.get('day')!=day or not q.get('final'): reason='收盘行情无法验证'
            elif daily and q.get('rules_version')!=schedule['version']: reason='Daily mode quote required'
            elif not q['eligible']: reason='标的状态不符合范围'
            elif q['price_fen'] in (q['upper_fen'],q['lower_fen']): reason='收盘触及涨跌停，双向不成交'
            elif q.get('corporate_action'): reason='公司行为或前收盘变化待核实'
            qty=order['qty']; pos=account['positions'].get(symbol,{'qty':0,'lots':[]})
            if not reason and order['side']=='sell':
                available=sum(x['qty'] for x in pos['lots'] if x['day']<day)
                if qty>available or (qty%100 and qty!=pos['qty']): reason='超出可卖数量或不满足T+1/零股规则'
            if not reason and order['side']=='buy' and qty*q['price_fen']>account['cash_fen']: reason='收盘价下现金不足，不调整锁定数量'
            key='order:'+day+':'+str(index)
            if reason: append(c,key,'rejected',day,{'order':order,'reason':reason})
            else:
                append(c,key,'fill',day,{**order,'price_fen':q['price_fen'],'name':q['name'],'evidence_ids':q['evidence_ids'],'fees_fen':0,**({'research_day':reports[0]['day'],'execution_day':day,'rules_version':schedule['version'],'execution_model':'next-session-close-paper'} if daily else {})})
                account=replay(c)
        append(c,'settled:'+day,'settled',day,{'report_id':reports[0]['id'] if reports else None,**({'execution_day':day,'research_day':reports[0]['day'] if reports else None,'rules_version':schedule['version']} if daily else {}),'note':'无有效截止前判断，不交易' if not reports else '按预先锁定顺序处理'})
        valuation(c,day,quotes)


def valuation(c,day,quotes):
    account=replay(c); value=account['cash_fen']+account['receivable_fen']; missing=[]; holdings=[]
    for symbol,pos in account['positions'].items():
        q=quotes.get(symbol)
        if not q or not q.get('verified') or not q.get('final') or q.get('day')!=day or q.get('corporate_action'): missing.append(symbol); continue
        value+=pos['qty']*q['price_fen']; holdings.append({'symbol':symbol,'qty':pos['qty'],'price_fen':q['price_fen']})
    benchmark=quotes.get('sh000300',{})
    bp=benchmark.get('price_fen') if benchmark.get('verified') and benchmark.get('final') and benchmark.get('day')==day else None
    first=events(c,'valuation')
    base=first[0]['payload']['benchmark_base'] if first else bp
    # shortcut: never shift a missing benchmark start; repair only with a cited, appended correction.
    append(c,'valuation:'+day,'valuation',day,{'value_fen':None if missing else value,'missing':missing,'cash_fen':account['cash_fen'],
        'holdings':holdings,'benchmark_price':bp,'benchmark_base':base,'benchmark_return':bp/base-1 if bp and base else None})


def summary(db):
    with db() as c:
        account=replay(c); journal=events(c); vals=[r for r in journal if r['kind']=='valuation']
        reports=[r for r in journal if r['kind'] in ('research','review')]
        peak=RULES['initial_fen']; drawdown=0
        for v in vals:
            n=v['payload']['value_fen']
            if n is not None: peak=max(peak,n);drawdown=max(drawdown,1-n/peak)
        resolutions={}
        for r in reports:
            for item in r['payload']['reviews']: resolutions[(item['report_id'],item['symbol'])]=item
        hypotheses=[]
        for r in reports:
            if r['kind']!='research':continue
            for j in r['payload']['judgments']:
                verdict=resolutions.get((r['id'],j['symbol']),{'verdict':'pending'})
                due=(date.fromisoformat(r['day'])+timedelta(days=j['horizon_days'])).isoformat()
                hypotheses.append({'report_id':r['id'],**j,'due':due,'resolution':verdict,'overdue':due<now().date().isoformat() and verdict['verdict']=='pending'})
        from invest_daily import rules
        from invest_ready import status as readiness_status
        return {'rules':rules(db),'readiness':readiness_status(db,now().date().isoformat()),'enabled':bool(c.execute('SELECT enabled FROM invest_control').fetchone()[0]),'account':account,
                'start':next((r for r in journal if r['kind']=='start'),None),'latest':vals[-1] if vals else None,
                'history':vals,'max_drawdown':drawdown,'reports':reports[-20:],'hypotheses':hypotheses,
                'exceptions':[r for r in journal if r['kind'] in ('rejected','error','missed','control','corporate_action')][-30:],
                'runs':[dict(r) for r in c.execute('SELECT * FROM invest_runs ORDER BY started DESC LIMIT 10')],
                'audit_head':journal[-1]['digest'] if journal else None}


def apply_dividends(c,day):
    for term in events(c,'dividend_terms'):
        p=term['payload'];key='dividend:'+str(term['id'])
        if day>=p['ex_day']:
            qty=replay(c,p['record_day'])['positions'].get(p['symbol'],{}).get('qty',0)
            amount=int((Decimal(p['fen_per_share'])*qty).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
            payload={'symbol':p['symbol'],'amount_fen':amount,'terms_id':term['id'],'entitled_qty':qty}
            if not c.execute('SELECT 1 FROM invest_events WHERE event_key=?',(key+':due',)).fetchone():
                append(c,key+':due','dividend_due',day,payload)
            if day>=p['pay_day'] and not c.execute('SELECT 1 FROM invest_events WHERE event_key=?',(key+':paid',)).fetchone():
                append(c,key+':paid','dividend_paid',day,payload)


def install(app,db,actor,owner_enabled):
    schema(db)
    def access(write=False):
        who=actor()
        if write:
            if who!='olive':abort(403,'仅olive可提交报告；规则与账本不能由模型修改')
        elif who!='olive' and not owner_enabled():abort(403,'请先在MangoSalad启用你的设备，再进入投资区')

    @app.get('/invest')
    def investment_page(): return app.send_static_file('invest.html')

    @app.get('/api/invest')
    def investment_summary():
        access();return summary(db)

    @app.post('/api/invest/report')
    def investment_report():
        access(True)
        try:return submit(db,request.get_json())
        except (ValueError,KeyError,TypeError) as e:abort(400,str(e))

    @app.get('/api/invest/market')
    def investment_market():
        access(True)
        from invest_market import market_request
        return market_request(db,request.args.get('symbols',''))

    @app.post('/api/invest/evidence')
    def investment_evidence():
        access(True)
        from invest_market import capture
        try:return capture(db,request.get_json())
        except (ValueError,KeyError,TypeError,OSError) as e:abort(400,'证据未保存：'+type(e).__name__)

    @app.get('/api/invest/evidence/<eid>')
    def investment_evidence_get(eid):
        access()
        with db() as c:r=c.execute('SELECT * FROM invest_evidence WHERE id=?',(eid,)).fetchone()
        if not r:abort(404)
        if request.args.get('raw')=='1' and r['raw'].startswith('{"mime_type": "application/pdf"'):
            import base64
            return Response(base64.b64decode(json.loads(r['raw'])['base64']),mimetype='application/pdf',headers={'Content-Disposition':'attachment; filename=evidence.pdf'})
        return dict(r)

    @app.get('/api/invest/export')
    def investment_export():
        access()
        with db() as c:
            data={'summary':summary(db),'journal':events(c),'evidence':[dict(r) for r in c.execute('SELECT * FROM invest_evidence ORDER BY at')]}
        if request.args.get('format')=='md':
            s=data['summary'];lines=['# olive 模拟投资审查包','零费用、零滑点、收盘价模拟；不代表真实可成交收益。',
                '规则版本：'+RULES['version'],'审计头：'+str(s['audit_head']),'现金：'+str(s['account']['cash_fen']/100)+' 元',
                '最大回撤：'+str(round(s['max_drawdown']*100,2))+'%', '## 最近判断']
            for r in s['reports']:
                lines += ['### '+r['day']+' '+r['kind']+' #'+str(r['id']),r['payload']['summary'],
                          '反证：'+r['payload']['counterevidence'],'次日计划：'+r['payload']['next_plan']]
                for f in r['payload']['facts']:lines.append('- '+f['text']+' [原始证据](/api/invest/evidence/'+f['evidence_id']+')')
            lines+=['## 原始账本与完整判断','下载同一入口的 JSON 包；所有历史记录、判断字段与原始响应均保留。',
                    '审查关注：有无事后信息、判断是否兑现、集中风险、数据/执行异常、未解决假设与规则变更。']
            return Response('\n\n'.join(lines),mimetype='text/markdown',headers={'Content-Disposition':'attachment; filename=olive-review.md'})
        return Response(dump(data),mimetype='application/json',headers={'Content-Disposition':'attachment; filename=olive-audit.json'})
