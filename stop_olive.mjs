// A separate connection needs native operator control to stop its own dispatched run.
// Keep this adapter limited to mangosalad task IDs; no arbitrary RPC or session input.
import { callGatewayFromCli } from '/home/ubuntu/.npm-global/lib/node_modules/openclaw/dist/plugin-sdk/gateway-runtime.js';
const id = process.argv[2];
if (!/^[a-f0-9]{30,32}$/.test(id || '')) throw new Error('Invalid task ID');
const result = await callGatewayFromCli('sessions.abort', {json:true, timeout:'15000'}, {
  key:'agent:main:mangosalad:'+id, agentId:'main', clearQueued:true
}, {scopes:['operator.admin'], progress:false});
console.log(JSON.stringify(result));
