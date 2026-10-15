"""Complete-session paper execution. No realtime endpoint and no single-source fallback."""
import concurrent.futures
import json
import re
import subprocess
from datetime import date, timedelta, datetime
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
from investment import RULES, TZ, now, trading_day, symbol_ok, fen, evidence, append, events, dump

RULES_DAILY = {**RULES, 'version':'2.0-daily', 'research':'16:30', 'deadline':'16:55',
    'settle':'16:00', 'review':'20:00', 'quote_max_age_seconds':3600, 'effective_day':'2026-10-15',
    'execution':'完整T日日线研究，16:55前冻结方向和数量；下一交易日收盘价模拟撮合，16:00核验。非真实成交保证。缺数拒绝，不补跑。',
    'data':'腾讯+新浪未复权完整日线；收盘价格按分精确相同；指数按0.01点。OHLC差异至多0.01。成交量统一股，容许腾讯整手舍入100股。',
    'eligibility':'沪深主板，排除ST/退市/N/C；至少5个历史交易日。腾讯历史响应所附收盘元数据须同日且匹配双源收盘/前收盘，涨跌停必须匹配普通10%规则；特殊状态、公司行为或信息不足拒绝。',
    'first_day':'生效首日只研究，无新模式待执行订单；旧模式订单不迁移、不回填。'}


def active(db):
    with db() as c:
        return bool(c.execute("SELECT 1 FROM invest_events WHERE event_key='rules:2.0-daily'").fetchone())


def rules(db):
    return RULES_DAILY if active(db) else RULES


def adjacent(day, direction=1):
    d=date.fromisoformat(day)
    for _ in range(370):
        d+=timedelta(days=direction)
        if trading_day(d.isoformat()):return d.isoformat()
    raise ValueError('No verified trading session')


def activate(db):
    stamp=now();day=stamp.date().isoformat()
    if day!=RULES_DAILY['effective_day']:raise ValueError('Activation date must match approved effective date')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute("SELECT 1 FROM invest_events WHERE event_key='start'").fetchone():raise ValueError('Experiment not started')
        if c.execute("SELECT 1 FROM invest_runs WHERE status='running'").fetchone():raise ValueError('Investment run active')
        if c.execute("SELECT 1 FROM invest_runs WHERE day=? AND stage='research'",(day,)).fetchone() or c.execute("SELECT 1 FROM invest_events WHERE event_key=?",('settled:'+day,)).fetchone():raise ValueError('Cannot switch mode after this day has executed')
        append(c,'rules:2.0-daily','rules',day,RULES_DAILY)


def pending(c, day):
    return [r for r in events(c,'research') if r['payload'].get('rules_version')==RULES_DAILY['version']
            and r['payload'].get('execution_day')==day and r['day']<day]


def decode_sina(raw,symbol):
    # Extract a quoted compressed string, never evaluate provider-supplied JavaScript.
    match=re.match(r'\s*var\s+KLC_K2_'+re.escape(symbol)+r'\s*=\s*"([^"\r\n]*)"\s*;',raw)
    if not match:raise ValueError('Invalid Sina historical envelope')
    result=subprocess.run(['node',str(Path(__file__).with_name('sina_daily_decode.mjs'))],
        input=json.dumps(match[1]),text=True,capture_output=True,timeout=15,check=True)
    return json.loads(result.stdout)


def parse_bars(rows, source):
    bars={}
    for row in rows:
        if source=='tencent':
            day=row[0]; values=dict(zip(('open','close','high','low'),row[1:5]));volume=Decimal(str(row[5]))*100
            amount=None
        else:
            day=row['date'][:10];values={k:row[k] for k in ('open','close','high','low')}
            volume=Decimal(str(row['volume']));amount=row.get('amount')
        date.fromisoformat(day)
        if day in bars:raise ValueError('Duplicate daily date')
        prices={k:Decimal(str(v)) for k,v in values.items()}
        if any(not x.is_finite() or x<=0 for x in prices.values()) or not volume.is_finite() or volume<0:raise ValueError('Invalid daily numbers')
        if not prices['low']<=min(prices['open'],prices['close'])<=max(prices['open'],prices['close'])<=prices['high']:raise ValueError('Invalid OHLC')
        if amount is not None and (not Decimal(str(amount)).is_finite() or Decimal(str(amount))<0):raise ValueError('Invalid amount')
        bars[day]={**{k:fen(v) for k,v in prices.items()},'volume':int(volume),'amount':amount}
    return bars


def snapshot(db,symbol):
    from invest_market import source_fetch
    if not symbol_ok(symbol) and symbol!='sh000300':raise ValueError('Unsupported symbol')
    observed=now();day=observed.date().isoformat()
    if not trading_day(day) or observed.strftime('%H:%M')<'16:00':raise ValueError('Complete daily data available only after 16:00 on a trading day')
    urls=['https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param='+symbol+',day,,,90,',
          'https://finance.sina.com.cn/realstock/company/'+symbol+'/hisdata_klc2/klc_kl.js']
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(source_fetch,u,'utf-8',s) for u,s in zip(urls,('tencent_daily','sina_daily'))]
        raws=[f.result() for f in futures]
    data=json.loads(raws[0])['data'][symbol]
    a=parse_bars(data['day'],'tencent')
    # Ignore decades outside the requested Tencent window, including pre-launch placeholders.
    b=parse_bars([r for r in decode_sina(raws[1],symbol) if r['date'][:10] in a],'sina')
    previous_day=adjacent(day,-1)
    if any(d not in bars for bars in (a,b) for d in (day,previous_day)):raise ValueError('Missing required complete daily bar')
    x,y=a[day],b[day];prev=a[previous_day]['close']
    history_days=[d for d in sorted(a.keys() & b.keys()) if d<=day and a[d]['close']==b[d]['close'] and all(abs(a[d][k]-b[d][k])<=1 for k in ('open','high','low')) and abs(a[d]['volume']-b[d]['volume'])<=100]
    verified=(x['close']==y['close'] and prev==b[previous_day]['close']
        and all(abs(x[k]-y[k])<=1 for k in ('open','high','low'))
        and abs(x['volume']-y['volume'])<=100)
    name=symbol;up=down=None;eligible=False;reason='Trade status unavailable'
    try:
        closing=data['qt'][symbol]
        closing_at=datetime.strptime(closing[30],'%Y%m%d%H%M%S').replace(tzinfo=TZ)
        verified=verified and closing[2]==symbol[2:] and closing_at.date().isoformat()==day and closing_at.hour>=15 and closing_at<=observed and fen(closing[3])==x['close']
    except (ValueError,KeyError,TypeError,IndexError):verified=False
    if symbol!='sh000300':
        try:
            t=data['qt'][symbol];name=t[1]
            qt=datetime.strptime(t[30],'%Y%m%d%H%M%S').replace(tzinfo=TZ)
            up=fen(t[47]);down=fen(t[48])
            expected_up=int((Decimal(prev)*Decimal('1.1')).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
            expected_down=int((Decimal(prev)*Decimal('0.9')).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
            eligible=(verified and t[2]==symbol[2:] and qt.date().isoformat()==day and qt.hour>=15 and qt<=observed
                and fen(t[3])==x['close'] and fen(t[4])==prev and up==expected_up and down==expected_down
                and not re.search(r'ST|退|^[NC]',name,re.I) and len([d for d in history_days if d<day])>=5
                and x['volume']>0 and y['volume']>0 and float(t[6])>0 and down<=x['close']<=up)
            reason='' if eligible else 'Trading status, ordinary limits or dual-source data not verified'
        except (ValueError,KeyError,TypeError,IndexError):pass
    ids=[evidence(db,u,r,day) for u,r in zip(urls,raws)]
    with db() as c:
        prior=next((r['payload'] for r in reversed(events(c,'quote')) if r['day']<day and r['payload']['symbol']==symbol and r['payload'].get('final')),None)
        action=bool(prior and prior['price_fen']!=prev)
        if action:
            action=not any(r['payload']['symbol']==symbol and r['payload']['ex_day']==day and
                abs(prior['price_fen']-prev-float(r['payload']['fen_per_share']))<=1 for r in events(c,'dividend_terms'))
        result={'id':ids[0],'symbol':symbol,'name':name,'day':day,'observed_at':observed.isoformat(),
            'quote_at':day+'T15:00:00+08:00','second_quote_at':day+'T15:00:00+08:00',
            'timestamp_basis':'daily session label, not a provider publication timestamp',
            'price_fen':x['close'],'previous_fen':prev,'upper_fen':up,'lower_fen':down,
            'verified':verified,'eligible':eligible,'eligibility_reason':reason,'final':True,
            'corporate_action':action,'evidence_ids':ids,'sources':['tencent_daily','sina_daily'],
            'rules_version':RULES_DAILY['version'],'volume_shares':y['volume'],'amount_cny':y['amount'],
            'amount_source':'sina_daily','price_unit':'index_points' if symbol=='sh000300' else 'CNY',
            'status_source':'tencent daily response closing metadata; ordinary limits cross-checked against both prior closes','adjust':'none','history':[[d,a[d]['open']/100,a[d]['close']/100,a[d]['high']/100,a[d]['low']/100,a[d]['volume']] for d in history_days]}
        c.execute('BEGIN IMMEDIATE');append(c,'quote:'+result['id'],'quote',day,result)
    return result
