import subprocess
import sys
import unittest
from unittest.mock import Mock
from invest_saved_close import collect, SavedCloseError


SAVED = dict(report='saved', event_id=7, payload_sha256='a'*64)


class Process:
    args = ['fake-rpc']
    def __init__(self, script, clock):
        self.script = list(script)
        self.clock = clock
        self.returncode = None
        self.inputs = []
        self.killed = False
    def communicate(self, input=None, timeout=None):
        self.inputs.append(input)
        if self.returncode is not None:
            return '{}', ''
        item = self.script.pop(0)
        if item == 'wait':
            self.clock[0] += 1
            raise subprocess.TimeoutExpired(self.args, timeout)
        self.returncode = item
        return '{}', ''
    def poll(self):
        return self.returncode
    def kill(self):
        self.killed = True
        self.returncode = -9


class SavedCloseTests(unittest.TestCase):
    def run_case(self, script, reader, stop, seconds=20):
        clock = [0]
        p = Process(script, clock)
        return p, lambda: collect(p, 'unchanged request', seconds, reader, stop, lambda: clock[0])

    def test_saved_report_uses_one_stop_and_stable_receipt(self):
        stop = Mock(return_value=True)
        p, run = self.run_case(['wait', 0], Mock(return_value=SAVED), stop)
        result, receipt = run()
        self.assertEqual(receipt['execution'], 'host_stopped_after_report')
        self.assertEqual(receipt['payload_sha256'], SAVED['payload_sha256'])
        stop.assert_called_once_with()
        self.assertEqual(p.inputs, ['unchanged request', None])
        self.assertFalse(p.killed)

    def test_normal_return_without_stop(self):
        stop = Mock()
        p, run = self.run_case([0], Mock(return_value=SAVED), stop)
        self.assertIsNone(run()[1])
        stop.assert_not_called()

    def test_missing_or_wrong_run_does_not_claim_success(self):
        for state in ['missing','run_mismatch']:
            stop = Mock()
            p, run = self.run_case(['wait',0], Mock(return_value={'report':state}), stop)
            self.assertIsNone(run()[1])
            stop.assert_not_called()

    def test_saved_after_deadline_keeps_timeout(self):
        stop = Mock()
        p, run = self.run_case(['wait'], Mock(return_value=SAVED), stop, seconds=1)
        with self.assertRaisesRegex(SavedCloseError, 'agent_timeout'): run()
        stop.assert_not_called()

    def test_unknown_stop_no_retry(self):
        stop = Mock(return_value=False)
        p, run = self.run_case(['wait'], Mock(return_value=SAVED), stop)
        with self.assertRaises(SavedCloseError) as caught: run()
        self.assertFalse(caught.exception.stop_confirmed)
        stop.assert_called_once_with()

    def test_changed_receipt_after_stop_is_failure(self):
        reader = Mock(side_effect=[SAVED, dict(SAVED,payload_sha256='b'*64)])
        p, run = self.run_case(['wait',0], reader, Mock(return_value=True))
        with self.assertRaisesRegex(SavedCloseError,'changed_during_stop'): run()

    def test_failed_transport_preserved_after_saved_stop(self):
        p, run = self.run_case(['wait',1], Mock(return_value=SAVED), Mock(return_value=True))
        with self.assertRaisesRegex(SavedCloseError,'gateway_call_failed_after_saved_stop'): run()

    def test_unresolved_adapter_does_not_claim_completed_stop(self):
        p, run = self.run_case(['wait','wait'], Mock(return_value=SAVED), Mock(return_value=True))
        with self.assertRaises(SavedCloseError) as caught: run()
        self.assertEqual(caught.exception.category,'saved_report_adapter_unresolved')
        self.assertFalse(caught.exception.stop_confirmed)

    def test_save_read_failure_propagates_without_submission(self):
        stop = Mock()
        p, run = self.run_case(['wait'], Mock(side_effect=OSError('read failure')), stop)
        with self.assertRaises(OSError): run()
        stop.assert_not_called()

    def test_late_normal_return_remains_timeout(self):
        p, run = self.run_case([0], Mock(return_value=SAVED), Mock(), seconds=0)
        with self.assertRaisesRegex(SavedCloseError,'agent_timeout'): run()

    def test_stop_confirmation_after_budget_remains_failure(self):
        clock=[0]
        p=Process(['wait',0],clock)
        def slow_stop():
            clock[0]=21
            return True
        with self.assertRaises(SavedCloseError) as caught:
            collect(p,'request',20,lambda:SAVED,slow_stop,lambda:clock[0])
        self.assertEqual(caught.exception.category,'agent_timeout')
        self.assertTrue(caught.exception.stop_confirmed)

    def test_real_pipe_large_input_and_output_no_model(self):
        code = 'import sys; data=sys.stdin.read(); sys.stdout.write(data)'
        p = subprocess.Popen([sys.executable,'-c',code],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        payload = 'x' * (256 * 1024)
        result, receipt = collect(p,payload,10,lambda:{'report':'missing'},lambda:False)
        self.assertEqual(result.stdout,payload)
        self.assertIsNone(receipt)


if __name__ == '__main__': unittest.main()

