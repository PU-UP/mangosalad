"""Small public-data adapter. Never accept model-supplied executable prices."""
import concurrent.futures
import base64
import ipaddress
import json
import re
import socket
import urllib.request
from urllib.parse import urlsplit
from datetime import datetime
from investment import TZ, now, dump, fen, evidence, append, symbol_ok

ALLOWED = ('sse.com.cn','szse.cn','cninfo.com.cn','eastmoney.com','gtimg.cn',
           'news.cn','xinhuanet.com','pbc.gov.cn','stats.gov.cn','csrc.gov.cn','gov.cn',
           'cs.com.cn','stcn.com','cnstock.com')


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
    url='https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=30&po=1&fid=f6&fs=m:1+t:2,m:0+t:6&fields=f12,f14,f2,f3,f6&invt=2&fltt=2'
    raw=fetch(url);data=json.loads(raw)['data']['diff'];eid=evidence(db,url,raw)
    rows=data.values() if isinstance(data,dict) else data
    candidates=[]
    for r in rows:
        code=r['f12'];symbol=('sh' if code.startswith('6') else 'sz')+code
        if symbol_ok(symbol) and not re.search(r'ST|退',r['f14'],re.I):
            candidates.append({'symbol':symbol,'name':r['f14'],'last':r['f2'],'change_pct':r['f3'],'turnover':r['f6']})
    return {'evidence_id':eid,'candidates':candidates,'note':'成交额排序仅供发现，有偏向活跃股；非固定股票池。报价可能为上一交易日，交易前必须查询带时间快照。'}


def snapshot(db,symbol):
    if not symbol_ok(symbol) and symbol!='sh000300':raise ValueError('不支持的代码')
    secid=('1.' if symbol.startswith('sh') else '0.')+symbol[2:]
    urls=[('https://qt.gtimg.cn/q='+symbol,'gb18030'),
          ('https://push2.eastmoney.com/api/qt/stock/get?secid='+secid+'&fields=f57,f58,f43,f60,f44,f45,f46,f47,f51,f52,f86&invt=2&fltt=2','utf-8'),
          ('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param='+symbol+',day,,,90,','utf-8')]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:raws=list(pool.map(lambda pair:fetch(*pair),urls))
    observed=now()
    t=raws[0].split('"')[1].split('~');e=json.loads(raws[1])['data'];k=json.loads(raws[2])['data'][symbol]
    history=k.get('day',[])
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
