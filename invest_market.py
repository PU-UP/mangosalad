"""Small public-data adapter. Never accept model-supplied executable prices."""
import concurrent.futures
import base64
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from datetime import datetime, timedelta
from investment import TZ, now, dump, fen, evidence, append, symbol_ok

ALLOWED = ('sse.com.cn','szse.cn','cninfo.com.cn','eastmoney.com','gtimg.cn',
           'news.cn','xinhuanet.com','pbc.gov.cn','stats.gov.cn','csrc.gov.cn','gov.cn',
           'cs.com.cn','stcn.com','cnstock.com','finance.sina.com.cn')

MAX_REQUESTS = 8
MAX_FAILURES = 3
MAX_QUERY_FAILURES = 2
FETCH_SECONDS = 360  # Keep the final two minutes of the existing eight-minute run for submission.


class MarketDataError(Exception):
    def __init__(self, diagnostic):
        self.diagnostic=diagnostic
        super().__init__(diagnostic['category'])


def diagnostic(error, source='market_data'):
    if isinstance(error,MarketDataError):return dict(error.diagnostic)
    result={'source':source}
    if isinstance(error,urllib.error.HTTPError):
        result.update(category='upstream_http',http_status=int(error.code))
    elif isinstance(error,(TimeoutError,socket.timeout)) or isinstance(error,urllib.error.URLError) and isinstance(error.reason,TimeoutError):
        result['category']='upstream_timeout'
    elif isinstance(error,(urllib.error.URLError,OSError)):
        result['category']='upstream_network'
    elif isinstance(error,(ValueError,KeyError,TypeError,IndexError)):
        result['category']='invalid_market_data'
    else:result['category']='unexpected_market_error'
    return result


def source_fetch(url, encoding, source):
    try:return fetch(url,encoding)
    except Exception as error:raise MarketDataError(diagnostic(error,source)) from None


def budget_reason(run, records, query, stamp):
    deadline=datetime.fromisoformat(run['started'])+timedelta(seconds=FETCH_SECONDS)
    end=stamp.replace(hour=run.get('deadline_hour',14),minute=run.get('deadline_minute',55),second=0,microsecond=0) if run['stage']=='research' else stamp.replace(hour=21,minute=0,second=0,microsecond=0)
    if stamp>=min(deadline,end-timedelta(seconds=120)):return 'submission_time_reserved'
    if len(records)>=MAX_REQUESTS:return 'request_budget_exhausted'
    if sum(r['ok']==0 for r in records)>=MAX_FAILURES:return 'failure_budget_exhausted'
    if any(r['finished'] is None for r in records):return 'request_in_progress'
    if sum(r['query']==query and r['ok']==0 for r in records)>=MAX_QUERY_FAILURES:return 'query_attempts_exhausted'
    return None


def market_request(db, symbols):
    result={'ok':False,'partial':False,'quotes':[],'candidates':[],'errors':[],'stop_market':False,
            'next_action':'Read ok/errors before quotes; never infer a quote from an error.'}
    values=symbols.split(',') if symbols else []
    if len(values)>3 or any(not (symbol_ok(x) or x=='sh000300') for x in values):
        result.update(errors=[{'category':'invalid_symbols'}],stop_market=True,
                      next_action='Fix the symbols; no network request was made.')
        return result
    query=','.join(sorted(set(values))) or 'discover'
    stamp=now();request_id=None;run=None
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute("SELECT * FROM invest_runs WHERE status='running' AND day=? ORDER BY started DESC LIMIT 1",(stamp.date().isoformat(),)).fetchone()
        if row:
            run=dict(row)
            from invest_daily import rules
            schedule=rules(db,stamp.date().isoformat())
            run['deadline_hour'],run['deadline_minute']=map(int,schedule['deadline'].split(':'))
            records=[dict(r) for r in c.execute('SELECT query,finished,ok FROM invest_market_requests WHERE run_id=? ORDER BY id',(run['id'],))]
            reason=budget_reason(run,records,query,stamp)
            if reason:
                result.update(errors=[{'category':reason}],stop_market=reason!='request_in_progress',
                              next_action='Stop market calls and submit using already verified evidence. If evidence is insufficient, submit a truthful report with orders=[]; do not invent facts or judgments. Confirm record_id before the existing deadline.')
                if reason=='request_in_progress':result['next_action']='Wait for the already-running request to finish; do not start duplicate calls or count this as a data failure.'
                return result
            request_id=c.execute('INSERT INTO invest_market_requests(run_id,query,started) VALUES(?,?,?)',(run['id'],query,stamp.isoformat())).lastrowid
    if values:
        # Preserve good snapshots even if another symbol fails; errors are never quotes.
        def one(symbol):
            try:return snapshot(db,symbol),None
            except Exception as error:return None,{'symbol':symbol,**diagnostic(error)}
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            for quote,error in pool.map(one,sorted(set(values))):
                if error:result['errors'].append(error)
                else:result['quotes'].append(quote)
    else:
        try:result.update(discover(db))
        except Exception as error:result['errors'].append(diagnostic(error))
    result['partial']=bool(result['quotes'] and result['errors'])
    result['ok']=bool(result['quotes']) if values else not result['errors']
    if request_id is not None:
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('UPDATE invest_market_requests SET finished=?,ok=?,diagnostics=? WHERE id=?',
                      (now().isoformat(),int(result['ok']),dump(result['errors']),request_id))
            records=[dict(r) for r in c.execute('SELECT query,finished,ok FROM invest_market_requests WHERE run_id=? ORDER BY id',(run['id'],))]
            reason=budget_reason(run,records,query,now())
        if reason in ('submission_time_reserved','request_budget_exhausted','failure_budget_exhausted'):
            result['stop_market']=True
    if result['errors'] or result['stop_market']:
        result['next_action']='Do not repeat a failed query more than once. If stop_market is true, stop fetching and submit using already verified evidence. If data is insufficient, use orders=[] and explain the missing data; confirm record_id. Do not claim completed research.'
    return result


def check_url(url):
    p=urlsplit(url)
    if p.scheme!='https' or p.username or p.password or p.port not in (None,443): raise ValueError('仅允许公开HTTPS资料')
    if not p.hostname or not any(p.hostname==h or p.hostname.endswith('.'+h) for h in ALLOWED): raise ValueError('来源不在基础白名单；补充来源先提出并由维护者核验')
    if re.search(r'(token|secret|password|api[_-]?key)=',p.query,re.I):raise ValueError('证据链接不得含凭据')
    for address in socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(address[4][0]).is_global:raise ValueError('拒绝私网地址')


class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        check_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def fetch(url,encoding='utf-8'):
    check_url(url)
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Referer':'https://quote.eastmoney.com/'})
    with urllib.request.build_opener(Redirect).open(req,timeout=12) as r:
        raw=r.read(2097153)
        if len(raw)>2097152:raise ValueError('原始证据超过2MB，使用官方公告摘要或较小原文')
        if raw.startswith(b'%PDF'):return json.dumps({'mime_type':'application/pdf','base64':base64.b64encode(raw).decode()})
        return raw.decode(encoding)


def capture(db,body):
    if not isinstance(body,dict) or set(body)-{'url','event_date','published_at'}:raise ValueError('证据参数无效')
    url=body['url'];raw=fetch(url)
    event_date=body.get('event_date');published_at=body.get('published_at')
    if event_date:datetime.strptime(event_date,'%Y-%m-%d')
    if published_at:
        dt=datetime.fromisoformat(published_at)
        if dt.tzinfo is None or dt>now():raise ValueError('发布时间无效')
    eid=evidence(db,url,raw,event_date,published_at)
    preview='PDF原件已保存；用原链接的文档阅读工具核验内容，无法读取则不得推断。' if raw.startswith('{"mime_type": "application/pdf"') else raw[:18000]
    return {'evidence_id':eid,'url':url,'raw':preview,'metadata_note':'事件/发布时间是提交者标注，获取时间与原文由服务器保存'}


def discover(db):
    from invest_daily import active
    if active(db):return {'candidates':[],'note':'Daily mode has no intraday turnover discovery. Choose candidates from public research within the existing scope; verify each with market --symbols. No fixed pool is imposed.'}
    url='https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=30&po=1&fid=f6&fs=m:1+t:2,m:0+t:6&fields=f12,f14,f2,f3,f6&invt=2&fltt=2'
    raw=source_fetch(url,'utf-8','eastmoney_candidates');data=json.loads(raw)['data']['diff'];eid=evidence(db,url,raw)
    rows=data.values() if isinstance(data,dict) else data
    candidates=[]
    for r in rows:
        code=r['f12'];symbol=('sh' if code.startswith('6') else 'sz')+code
        if symbol_ok(symbol) and not re.search(r'ST|退',r['f14'],re.I):
            candidates.append({'symbol':symbol,'name':r['f14'],'last':r['f2'],'change_pct':r['f3'],'turnover':r['f6']})
    return {'evidence_id':eid,'candidates':candidates,'note':'成交额排序仅供发现，有偏向活跃股；非固定股票池。报价可能为上一交易日，交易前必须查询带时间快照。'}


def snapshot(db,symbol):
    from invest_daily import active, snapshot as daily_snapshot
    if active(db):return daily_snapshot(db,symbol)
    if not symbol_ok(symbol) and symbol!='sh000300':raise ValueError('不支持的代码')
    secid=('1.' if symbol.startswith('sh') else '0.')+symbol[2:]
    urls=[('https://qt.gtimg.cn/q='+symbol,'gb18030'),
          ('https://push2.eastmoney.com/api/qt/stock/get?secid='+secid+'&fields=f57,f58,f43,f60,f44,f45,f46,f47,f51,f52,f86&invt=2&fltt=2','utf-8')]
    sources=['tencent_quote','eastmoney_quote']
    # Only equities need listing history for eligibility; the benchmark still requires both price sources.
    if symbol!='sh000300':
        urls.append(('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param='+symbol+',day,,,90,','utf-8'))
        sources.append('tencent_history')
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        raws=list(pool.map(lambda item:source_fetch(*item[0],item[1]),zip(urls,sources)))
    observed=now()
    t=raws[0].split('"')[1].split('~');e=json.loads(raws[1])['data']
    history=json.loads(raws[2])['data'][symbol].get('day',[]) if symbol!='sh000300' else []
    if t[2]!=symbol[2:] or e['f57']!=symbol[2:]:raise ValueError('行情代码不匹配')
    qt=datetime.strptime(t[30],'%Y%m%d%H%M%S').replace(tzinfo=TZ)
    et=datetime.fromtimestamp(e['f86'],TZ);day=qt.date().isoformat()
    price=fen(t[3]);other=fen(e['f43']);prev=fen(t[4]);closed=qt.hour>=15 and et.hour>=15
    same_day=day==et.date().isoformat()
    # Intraday snapshots can differ slightly in time. The close must agree to the fen.
    verified=same_day and qt<=observed and et<=observed and (price==other if closed else abs(price-other)<=max(1,price//200))
    if not closed:verified=verified and all(0<=(observed-x).total_seconds()<=180 for x in (qt,et))
    bad_name=bool(re.search(r'ST|退|^[NC]',t[1],re.I) or re.search(r'ST|退|^[NC]',e['f58'],re.I))
    up=down=None;eligible=False
    if symbol!='sh000300':
        up=fen(t[47]);down=fen(t[48])
        eligible=not bad_name and len([r for r in history if r[0]<day])>=5 and up==fen(e['f51']) and down==fen(e['f52']) and down<price<up
        # Boundary prices remain verified but are explicitly rejected by settlement.
        if price in (up,down):eligible=not bad_name and len([r for r in history if r[0]<day])>=5 and up==fen(e['f51']) and down==fen(e['f52'])
        eligible=eligible and float(t[6])>0 and e['f47']>0 and prev==fen(e['f60'])
    ids=[evidence(db,u,raw,day) for (u,_),raw in zip(urls,raws)]
    with db() as c:
        old=c.execute("SELECT payload FROM invest_events WHERE kind='quote' AND day<? ORDER BY id DESC",(day,)).fetchall()
        prior=next((json.loads(r[0]) for r in old if json.loads(r[0])['symbol']==symbol and json.loads(r[0]).get('final')),None)
        action=bool(prior and prior['price_fen']!=prev)
        if action:
            terms=c.execute("SELECT payload FROM invest_events WHERE kind='dividend_terms'").fetchall()
            action=not any(json.loads(r[0])['symbol']==symbol and json.loads(r[0])['ex_day']==day and
                           abs(prior['price_fen']-prev-float(json.loads(r[0])['fen_per_share']))<=1 for r in terms)
        result={'id':ids[0],'symbol':symbol,'name':t[1],'day':day,'observed_at':observed.isoformat(),
                'quote_at':qt.isoformat(),'second_quote_at':et.isoformat(),'price_fen':price,'previous_fen':prev,
                'upper_fen':up,'lower_fen':down,'verified':verified,'eligible':eligible,'final':closed,
                'corporate_action':action,'evidence_ids':ids,'history':history,
                'note':'未复权行情；当日K线收盘前未完成；公司行为异常需核实'}
        c.execute('BEGIN IMMEDIATE');append(c,'quote:'+result['id'],'quote',day,result)
    return result


def collect(db,symbols):
    quotes={};errors={}
    for symbol in dict.fromkeys(symbols):
        try:quotes[symbol]=snapshot(db,symbol)
        except Exception as e:errors[symbol]=type(e).__name__
    return quotes,errors
