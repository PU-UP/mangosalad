const $=id=>document.getElementById(id);
const money=n=>n==null?'待核验':(n/100).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});
const pct=n=>n==null?'—':(n*100).toFixed(2)+'%';
function node(tag,text,parent){const e=document.createElement(tag);e.textContent=text;if(parent)parent.append(e);return e;}
function evidence(id,parent){const a=node('a','原始证据 '+id.slice(0,6),parent);a.href='/api/invest/evidence/'+encodeURIComponent(id);a.target='_blank';a.rel='noopener';}
async function load(){
 try{
  const r=await fetch('/api/invest');const s=await r.json();if(!r.ok)throw new Error(s.error||'读取失败');
  $('content').hidden=false;$('status').textContent=s.enabled?'运行中 · 每个交易日按计划研究与复盘':'尚未启用 / 已暂停 · 不会自动下单';
  const v=s.latest?.payload;const initial=s.rules.initial_fen;
  $('cash').textContent=money(s.account.cash_fen);$('receivable').textContent='应收分红 '+money(s.account.receivable_fen);
  $('equity').textContent=money(v?v.value_fen:(s.start?initial:null));$('asof').textContent=s.latest?'估值日 '+s.latest.day:'等待首个交易日估值';
  $('returns').textContent=pct(v?.value_fen==null?null:v.value_fen/initial-1)+' / '+pct(v?.benchmark_return);
  $('drawdown').textContent=s.latest?pct(s.max_drawdown):'—';$('evaluation').textContent=s.start?'首期评估 '+s.start.payload.evaluate_on:'实验尚未初始化';
  const positions=Object.entries(s.account.positions);$('holdings-empty').textContent=positions.length?'价格缺失时不以旧行情冒充当前市值。':'当前没有持仓。持币也是一种需要解释的选择。';
  for(const [symbol,p] of positions){const h=v?.holdings.find(x=>x.symbol===symbol);const tr=node('tr','',$('holdings'));for(const x of [p.name+' '+symbol,String(p.qty),money(h?.price_fen),money(h?h.qty*h.price_fen:null)])node('td',x,tr);}
  if(!s.exceptions.length)node('p','暂无已记录异常。',$('exceptions'));
  if(s.start?.payload.evaluate_on>String(s.rules.calendar_year)+'-12-31')node('p','待维护：首期跨年，需在年底前核验下一年度交易日历；未核验将自动暂停。',$('exceptions'));
  for(const e of [...s.exceptions].reverse().slice(0,8))node('p',e.day+' · '+(e.payload.reason||JSON.stringify(e.payload)),$('exceptions'));
  for(const r of [...s.reports].reverse()){
   const d=node('details','',$('reports'));d.className='report';node('summary',r.day+' · '+(r.kind==='research'?'交易判断':'晚间复盘'),d);
   const p=r.payload;node('p',p.summary,d);if(p.execution_day)node('p','研究日 '+p.research_day+' · 模拟执行日 '+p.execution_day+' · '+p.rules_version,d);
   for(const [label,key] of [['推断','inferences'],['不确定性','uncertainties'],['反证','counterevidence'],['下一步','next_plan']])node('p',label+'：'+p[key],d);
   for(const f of p.facts){node('p','事实：'+f.text+'（事件日期 '+(f.event_date||'未知')+'）',d);evidence(f.evidence_id,d);}
   for(const j of p.judgments)node('p',j.symbol+' · '+j.action+'\n'+j.reason+'\n失效条件：'+j.falsifier+'\n风险：'+j.risk+'\n仓位理由：'+j.sizing,d);
  }
  if(!s.reports.length)node('p','第一份判断将在有效运行后出现。',$('reports'));
  const pending=s.hypotheses.filter(x=>['pending','unverifiable'].includes(x.resolution.verdict));
  if(!pending.length)node('p','暂无待验证假设。',$('hypotheses'));
  for(const h of pending){const d=node('div','',$('hypotheses'));d.className='report';node('strong',h.symbol+' · '+(h.overdue?'已到期，待复核':'复核 '+h.due),d);node('p',h.reason,d);node('p','失效条件：'+h.falsifier,d);}
  $('rules').textContent=JSON.stringify(s.rules,null,2);$('audit').textContent='审计链末端：'+(s.audit_head||'暂无记录');
  const hist=s.history;const paths=[hist.map(x=>x.payload.value_fen==null?null:x.payload.value_fen/initial-1),hist.map(x=>x.payload.benchmark_return)];
  $('chart-note').textContent=hist.length<2?'至少两个有效估值日后显示轨迹；缺失数据保留断点。':hist[0].day+' — '+hist[hist.length-1].day+' · 缺失估值不连线';
  if(hist.length>=2){const nums=paths.flat().filter(x=>x!=null);const lo=Math.min(0,...nums),hi=Math.max(.001,...nums);paths.forEach((values,i)=>{let d='',last=false;values.forEach((y,j)=>{if(y==null){last=false;return;}const x=15+j/(hist.length-1)*690,py=165-(y-lo)/(hi-lo)*150;d+=(last?'L':'M')+x+','+py;last=true;});const p=document.createElementNS('http://www.w3.org/2000/svg','path');p.setAttribute('d',d);p.setAttribute('fill','none');p.setAttribute('stroke',i?'#8a96aa':'#37685a');p.setAttribute('stroke-width','2');$('chart').append(p);});}
 }catch(e){$('status').textContent=e.message+'。若设备未启用，请在飞书让 olive 提供现有设备启用链接，再返回此页。';}
}
load();
