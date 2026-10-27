import assert from 'node:assert/strict';
import {mkdtempSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
const home=mkdtempSync(join(tmpdir(),'olive-loader-test-'));
process.env.OPENCLAW_STATE_DIR=home;
process.env.OPENCLAW_CONFIG_PATH=join(home,'config.json');
writeFileSync(process.env.OPENCLAW_CONFIG_PATH,'{}');
const dist='/home/ubuntu/.npm-global/lib/node_modules/openclaw/dist/';
const {r:load}=await import(dist+'loader-runtime-load-CdQ5OcQq.mjs');
const {i:initialize,a:reset}=await import(dist+'hook-runner-global-CN2-D2Rq.mjs');
const {x:before}=await import(dist+'agent-tools.before-tool-call-ya9NNSXc.mjs');
const config={plugins:{enabled:true,allow:['olive-invest-closure'],
  load:{paths:[resolve('plugins/olive-invest-closure')]},entries:{'olive-invest-closure':{enabled:true}}}};
try {
  const registry=load({config,workspaceDir:home,activate:false,cache:false,logger:{info(){},warn(){},error(){},debug(){}}});
  const record=registry.plugins.find(p=>p.id==='olive-invest-closure');
  assert(record,'real loader discovered plugin');
  assert.equal(record.status,'loaded',JSON.stringify({status:record.status,error:record.error}));
  const registered=registry.trustedToolPolicies.find(p=>p.pluginId==='olive-invest-closure');
  assert(registered,'real loader accepted explicitly enabled declared trusted policy');
  const original=registered.policy.evaluate,id='a'.repeat(32);
  const contract={namespace:'olive-investment',run_id:id,stage:'research',started_at:0,research_until:900,expires_at:1200};
  let clock=899,lookups=0,safety=0,current=contract;
  registered.policy.evaluate=(event,ctx)=>original(event,ctx,()=>{lookups++;return current},clock);
  registry.typedHooks.push({pluginId:'test-existing-safety',hookName:'before_tool_call',priority:0,
    handler:()=>{safety++;return {block:true,blockReason:'existing safety denied'}}});
  initialize(registry);
  const ctx={agentId:'main',sessionKey:'agent:main:mangosalad:'+id,runId:'isolated',config};
  const run=(toolName,params,context=ctx)=>before({toolName,params,ctx:context,toolCallId:'test-'+Math.random()});
  let result=await run('web_fetch',{});
  assert.equal(result.blocked,true);assert.equal(result.reason,'existing safety denied');assert.equal(safety,1);
  clock=901;result=await run('web_fetch',{});
  assert.equal(result.blocked,true);assert.match(result.reason,/research phase ended/);assert.equal(safety,1);
  result=await run('exec',{command:`python3 /home/ubuntu/mangosalad-desk/invest_cli.py report --file /tmp/mangosalad-invest-${id}/report.json`});
  assert.equal(result.reason,'existing safety denied');assert.equal(safety,2);
  const reads=lookups;
  result=await run('web_fetch',{}, {...ctx,agentId:'another',sessionKey:'agent:another:main'});
  assert.equal(lookups,reads);assert.equal(result.reason,'existing safety denied');
  current=undefined; result=await run('web_fetch',{}); assert.equal(result.reason,'existing safety denied');
  current=contract; clock=1201; result=await run('write',{path:'/tmp/mangosalad-invest-'+id+'/report.json'}); assert.equal(result.blocked,true);
  current={...contract,run_id:'b'.repeat(32)}; result=await run('web_fetch',{}); assert.equal(result.blocked,true);
  console.log('PASS real OpenClaw loader + trusted policy chain: phase veto, existing safety, other-agent isolation; no model/network');
} finally {reset();rmSync(home,{recursive:true,force:true});}
