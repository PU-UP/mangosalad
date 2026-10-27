import {readFileSync} from 'node:fs';
const ROOT='/home/ubuntu/.local/share/mangosalad/runtime/invest-execution-contracts';
export function loadContract(id) {
  try {return JSON.parse(readFileSync(`${ROOT}/${id}.json`,'utf8'));}
  catch(error) {if(error.code==='ENOENT') return undefined; throw error;}
}
export function evaluate(event, ctx, lookup=loadContract, now=Date.now()/1000) {
  if(ctx.agentId && ctx.agentId!=='main') return;
  const match=/^agent:main:mangosalad:([a-f0-9]{32})$/.exec(ctx.sessionKey || '');
  if(!match) return;
  const id=match[1], c=lookup(id);
  if(!c) return; // No host-written investing contract: other Mango tasks are unchanged.
  if(c.namespace!=='olive-investment' || c.run_id!==id || !['research','review'].includes(c.stage) ||
     ![c.started_at,c.research_until,c.expires_at].every(Number.isFinite) ||
     c.started_at>c.research_until || c.research_until>c.expires_at || c.expires_at-c.started_at>1200)
    throw new Error('Invalid investing execution contract');
  if(now<c.research_until) return;
  // Code-mode wrappers and polling collect admitted work; every nested host tool is gated again.
  if(event.toolKind==='code_mode_exec' || event.toolName==='wait' ||
     (event.toolName==='process' && ['poll','log'].includes(event.params?.action))) return;
  const draft=`/tmp/mangosalad-invest-${id}/report.json`, p=event.params || {};
  let allowed=false;
  if(now<c.expires_at) {
    if(['read','write','edit'].includes(event.toolName)) allowed=(p.path ?? p.file_path)===draft;
    if(event.toolName==='read' && (p.path ?? p.file_path)==='/home/ubuntu/.openclaw/workspace/skills/olive-investing/SKILL.md') allowed=true;
    if(event.toolName==='exec' && !p.background) allowed=[
      `python3 /home/ubuntu/mangosalad-desk/invest_cli.py report --file ${draft}`,
      'python3 /home/ubuntu/mangosalad-desk/invest_cli.py report --help',
      'python3 /home/ubuntu/mangosalad-desk/invest_model_cli.py status'
    ].includes(p.command);
  }
  if(allowed) return; // Never returns an allow override or modifies parameters.
  return {block:true,blockReason:`Investment research phase ended; not dispatched. Use existing evidence and explicit unknowns, write ${draft}, submit with the exact existing report command, then verify. Do not fetch new evidence or retry uncertain submission. Existing report rules and deadline remain in force.`};
}
