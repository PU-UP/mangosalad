"""Isolated transport tests: no real Gateway, agent, or database calls."""
import errno
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import invest_worker as worker

class InvokeTests(unittest.TestCase):
    def test_large_utf8_request_through_real_pipe_and_mock_gateway(self):
        message = '中文🙂' * 40000
        rid = 'a' * 32
        expected = dict(agentId='main', sessionKey='agent:main:mangosalad:'+rid,
                        message=message, idempotencyKey=rid, deliver=False,
                        disableMessageTool=True, timeout=480)
        adapter = Path(worker.__file__).with_name('invoke_olive.mjs').as_uri()
        harness = f"import {{run}} from {json.dumps(adapter)};\n" + r"""
import assert from 'node:assert/strict';
await run(process.stdin, process.stdout, async (method, opts, params, extra) => {
  assert.equal(method, 'agent');
  assert.deepEqual(opts, {json:true, expectFinal:true, timeout:'500000'});
  assert.deepEqual(extra, {defaultTimeoutMs:10000, sharedStateMode:'read-only'});
  assert.equal(params.message, '中文🙂'.repeat(40000));
  return {result:{payloads:[{text:'completed'}]}, systemPrompt:{text:'excluded'}};
});
"""
        real_run = subprocess.run
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp)/'mock-gateway.mjs'; script.write_text(harness)
            def transport(command, **kwargs):
                self.assertEqual(command, ['node', str(Path(worker.__file__).with_name('invoke_olive.mjs'))])
                self.assertEqual(json.loads(kwargs['input']), expected)
                self.assertGreater(len(kwargs['input'].encode('utf-8')), 131072)
                self.assertEqual(kwargs['timeout'], 520)
                self.assertEqual(kwargs['cwd'], Path.home()/'.openclaw/workspace')
                return real_run(['node', str(script)], **kwargs)
            with patch.object(worker.subprocess, 'run', side_effect=transport):
                self.assertEqual(worker.invoke(message, rid), 'completed')

    def failure(self, outcome, category):
        kwargs = {'side_effect':outcome} if isinstance(outcome, BaseException) else {'return_value':outcome}
        with patch.object(worker.subprocess, 'run', **kwargs) as run:
            with self.assertRaises(worker.InvestmentRunError) as caught:
                worker.invoke('PRIVATE_SENTINEL', 'b'*32)
            self.assertEqual(caught.exception.category, category)
            self.assertEqual(run.call_count, 1)

    def test_spawn_error_safe_diagnostic(self):
        with self.assertLogs('invest_worker', level='ERROR') as logs:
            self.failure(OSError(errno.E2BIG, 'PRIVATE_SENTINEL'), 'gateway_spawn_failed')
        self.assertIn('errno=7', logs.output[0])
        self.assertIn('request_bytes=', logs.output[0])
        self.assertNotIn('PRIVATE_SENTINEL', str(logs.output))

    def test_timeout_no_retry(self):
        self.failure(subprocess.TimeoutExpired(['PRIVATE_SENTINEL'], 520), 'agent_timeout')

    def test_gateway_failure_no_error_content_propagation(self):
        with self.assertLogs('invest_worker', level='ERROR') as logs:
            self.failure(subprocess.CompletedProcess([], 1, '', 'PRIVATE_SENTINEL'), 'gateway_call_failed')
        self.assertNotIn('PRIVATE_SENTINEL', str(logs.output))

    def test_invalid_response(self):
        self.failure(subprocess.CompletedProcess([], 0, 'not-json', ''), 'gateway_response_invalid')

    def test_reported_agent_timeout(self):
        self.failure(subprocess.CompletedProcess([], 0, json.dumps({'text':'Request timed out before a response was generated.'}), ''), 'agent_timeout')

    def test_adapter_parse_and_gateway_errors_propagate(self):
        adapter = Path(worker.__file__).with_name('invoke_olive.mjs').as_uri()
        harness = f"import {{run, dispatch}} from {json.dumps(adapter)};\n" + r"""
import assert from 'node:assert/strict';
import {Readable, Writable} from 'node:stream';
const output = new Writable({write(chunk, enc, cb) { cb(); }});
let calls=0;
await assert.rejects(run(Readable.from(['{']), output, async()=>{calls++;}), SyntaxError);
assert.equal(calls,0);
const sentinel = new Error('mock transport failure');
await assert.rejects(dispatch({timeout:480}, async()=>{throw sentinel;}), e=>e===sentinel);
"""
        result = subprocess.run(['node','--input-type=module'], input=harness, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

if __name__ == '__main__':
    unittest.main()
