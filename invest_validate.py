"""Live olive rehearsal, isolated from the real account and delivery. Never backfills production."""
import json
import os
import secrets
import tempfile
from pathlib import Path
from unittest.mock import patch


if __name__=='__main__':
    folder=Path(tempfile.mkdtemp(prefix='olive-invest-rehearsal-'))
    os.chmod(folder,0o700)
    os.environ['MANGO_DATA']=str(folder);os.environ['MANGO_PUBLIC']='1'
    from app import app,db,private
    from investment import now,start,append,settle,summary,dump,events
    from invest_market import collect
    from invest_worker import invoke
    day=now().date().isoformat();start(db,day)
    with db() as c:c.execute('UPDATE invest_control SET enabled=1')
    quotes,errors=collect(db,['sh600519','sz000001','sh000300'])
    if errors or not all(q['verified'] for q in quotes.values()):raise SystemExit('Live market verification failed: '+dump(errors))
    client=app.test_client();headers={'Authorization':'Bearer '+private['agents']['olive'],'X-Mango-Request':'1'}
    skill=(Path(__file__).parent/'skill/olive-investing/SKILL.md').read_text()
    for stage,hour,minute in [('research',14,40),('review',20,10)]:
        stamp=now().replace(hour=hour,minute=minute,second=0,microsecond=0)
        rid=secrets.token_hex(16)
        with db() as c:c.execute('INSERT INTO invest_runs VALUES(?,?,?,?,?,?,?)',(rid,day,stage,'running',stamp.isoformat(),None,None))
        evidence_ids=[eid for q in quotes.values() for eid in q['evidence_ids']]
        message=f'''用户授权的olive投资隔离验收。不是正式投资，不交易，不修改文件/服务/定时任务，不发消息，不调用生产API。
请阅读下面的正式规则，使用提供的真实数据生成一次{stage}报告。此处当前真实时间是{now().isoformat()}，数据可能为上一交易日，必须承认数据时间，不能伪装成今天盘中。
为验证完整报告保存链路，验收器在隔离数据库模拟{stamp.isoformat()}接收报告；不进入正式20万账户。若原research的judgments为空，本次reviews必须[]，无交易的复盘只写summary；禁止把行情记录或不存在的编号当原判断。
run_id={rid}，stage={stage}。仅输出一个符合规则的JSON对象，无markdown。orders必须[]；judgments可为空；事实必须引用下面的真实evidence_ids，解释为何不交易。研究要给反证检索计划，复盘要区分本次无交易、数据和模型判断，给明日具体检查计划。不需要调用工具。
{skill}
行情与证据：{dump(quotes)}
账户及已保存记录：{dump(summary(db))}
'''
        output=invoke(message,rid,240)
        decoder=json.JSONDecoder();report=None
        for i,char in enumerate(output):
            if char!='{':continue
            try:obj,_=decoder.raw_decode(output[i:])
            except ValueError:continue
            if isinstance(obj,dict) and obj.get('run_id')==rid:report=obj;break
        if report is None:raise ValueError('olive未返回有效报告JSON')
        with patch('investment.now',return_value=stamp):
            result=client.post('/api/invest/report',headers=headers,json=report)
        if result.status_code!=200:
            (folder/'rejected-report.json').write_text(dump({'report':report,'error':result.json}))
            raise ValueError(result.json)
        with db() as c:c.execute("UPDATE invest_runs SET status='done',finished=? WHERE id=?",(stamp.isoformat(),rid))
        if stage=='research':
            # Deliberately stale real quotes must not be relabeled or used for today's fills.
            settle(db,day,quotes,stamp.replace(hour=15,minute=15))
        print(stage+': persisted record '+str(result.json['record_id']),flush=True)
    export=client.get('/api/invest/export',headers=headers)
    assert export.status_code==200
    audit=export.json
    assert len([r for r in audit['journal'] if r['kind']=='fill'])==0
    assert audit['summary']['account']['cash_fen']==20000000
    (folder/'audit.json').write_text(dump(audit))
    result={'passed':True,'kind':'live-model-isolated-rehearsal','at':now().isoformat(),'directory':str(folder),
            'checks':['live dual-source quotes','olive research','API validation and persistence','stale-date close rejection','olive review','audit export','cash reconciliation'],
            'limits':'非交易时段隔离演练，未声称真实盘中下单或首日盈利；完整成交异常由test_investment.py验证'}
    (folder/'result.json').write_text(dump(result))
    print(dump(result),flush=True)
