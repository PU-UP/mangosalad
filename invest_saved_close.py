"""End only a live invocation whose own immutable report is already saved.

No report writes, retries, model calls, or trading decisions live here.
"""
import subprocess
import time


class SavedCloseError(Exception):
    def __init__(self, category, stop_confirmed=None):
        self.category = category
        self.stop_confirmed = stop_confirmed
        super().__init__(category)


def collect(process, payload, timeout, read_receipt, stop, clock=time.monotonic):
    deadline = clock() + timeout
    supplied = False
    try:
        while True:
            try:
                stdout, stderr = process.communicate(
                    input=None if supplied else payload,
                    timeout=min(1.0, max(0.01, deadline + 40 - clock())))
                if clock() >= deadline:
                    raise SavedCloseError("agent_timeout")
                return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr), None
            except subprocess.TimeoutExpired:
                supplied = True
            # A returned error wins over a concurrently observed saved report.
            if process.poll() is not None:
                continue
            if clock() >= deadline:
                raise SavedCloseError('agent_timeout')
            before = read_receipt()
            if before.get('report') != 'saved':
                continue
            if not before.get('payload_sha256') or not isinstance(before.get('event_id'), int):
                raise SavedCloseError('report_unverified')
            # Recheck the execution deadline immediately before requesting a stop.
            if clock() >= deadline:
                raise SavedCloseError('agent_timeout')
            if not stop():
                raise SavedCloseError('saved_report_stop_unconfirmed', False)
            try:
                stdout, stderr = process.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                raise SavedCloseError('saved_report_adapter_unresolved', False) from None
            if clock() >= deadline:
                raise SavedCloseError("agent_timeout", True)
            after = read_receipt()
            if after != before:
                raise SavedCloseError('saved_report_changed_during_stop', True)
            result = subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
            # Preserve adapter failures: saving a report is not proof of clean execution.
            if result.returncode:
                raise SavedCloseError('gateway_call_failed_after_saved_stop', True)
            return result, dict(before, execution='host_stopped_after_report', stop_confirmed=True)
    finally:
        # Only the local RPC transport is reaped here; server stop is handled above/caller.
        if process.poll() is None:
            process.kill()
            process.communicate()

