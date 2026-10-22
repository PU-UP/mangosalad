// Keep the CLI agent RPC unchanged; carry its JSON over stdin, not argv.
import { pathToFileURL } from 'node:url';
export async function dispatch(params, callGateway) {
  return await callGateway('agent', {
    json: true, expectFinal: true, timeout: String((params.timeout + 20) * 1000)
  }, params, {defaultTimeoutMs: 10000, sharedStateMode: 'read-only'});
}
export async function run(input, output, callGateway) {
  let text = '';
  input.setEncoding('utf8');
  for await (const chunk of input) text += chunk;
  const result = await dispatch(JSON.parse(text), callGateway);
  output.write(JSON.stringify(result) + '\n');
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const {callGatewayFromCli} = await import('/home/ubuntu/.npm-global/lib/node_modules/openclaw/dist/plugin-sdk/gateway-runtime.js');
    await run(process.stdin, process.stdout, callGatewayFromCli);
  } catch {
    // Never print provider errors, request contents, or authentication details.
    process.stderr.write('gateway_call_failed\n');
    process.exitCode = 1;
  }
}
