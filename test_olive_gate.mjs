import assert from 'node:assert/strict';
import test from 'node:test';
import plugin from './plugins/olive-invest-closure/index.mjs';
import {evaluate} from './plugins/olive-invest-closure/gate.mjs';
const id='a'.repeat(32),ctx={agentId:'main',sessionKey:'agent:main:mangosalad:'+id};
const c={namespace:'olive-investment',run_id:id,stage:'research',started_at:0,research_until:900,expires_at:1200};
const gate=(toolName,params={},now=901,extra={})=>evaluate({toolName,params,...extra},ctx,()=>c,now);
test('registration declares one scoped policy without granting or rewriting tools',()=>{
  const entries=[];plugin.register({registerTrustedToolPolicy:p=>entries.push(p)});
  assert.equal(entries.length,1);assert.equal(entries[0].id,'investment-phase-budget');assert.equal(entries[0].evaluate,evaluate);
  for(const other of [{agentId:'lychee',sessionKey:ctx.sessionKey},{agentId:'main',sessionKey:'agent:main:main'}])
    assert.equal(evaluate({toolName:'exec'},other,()=>{throw Error('must not read contract')}),undefined);
  assert.equal(evaluate({toolName:'exec'},ctx,()=>undefined,901),undefined);
});
test('phase, exact closure commands, nested tools and late results',()=>{
  assert.equal(gate('web_fetch',{},899),undefined);
  assert.equal(gate('web_fetch').block,true);
  const file=`/tmp/mangosalad-invest-${id}/report.json`;
  const command=`python3 /home/ubuntu/mangosalad-desk/invest_cli.py report --file ${file}`;
  for(const tool of ['read','write','edit'])assert.equal(gate(tool,{path:file}),undefined);
  assert.equal(gate('exec',{command}),undefined);
  for(const cmd of [command+'; id',command+' && id','curl https://example.com']) assert.equal(gate('exec',{command:cmd}).block,true);
  assert.equal(gate('exec',{command,background:true}).block,true);
  assert.equal(gate('exec',{command},1200).block,true);
  assert.equal(gate('exec',{code:'tools.fetch()'},901,{toolKind:'code_mode_exec'}),undefined);
  assert.equal(gate('web_fetch').block,true); // host bridge nested call
  assert.equal(gate('process',{action:'poll'},1201),undefined);
  assert.equal(gate('process',{action:'write'},1201).block,true);
  assert.equal(gate('write',{path:'/tmp/other.json'}).block,true);
  const before=JSON.stringify(c);gate('web_search');gate('web_search');assert.equal(JSON.stringify(c),before);
});
test('invalid host contract is never accepted as a valid budget',()=>{
  for(const bad of [{...c,run_id:'b'.repeat(32)},{...c,expires_at:3600},{...c,research_until:1500}])
    assert.throws(()=>evaluate({toolName:'exec'},ctx,()=>bad,901),/contract/);
});
