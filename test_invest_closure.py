import contextlib
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from invest_closure import reconcile, persist


class ClosureTests(unittest.TestCase):
    def test_reports_are_reconciled_without_writes_or_retry(self):
        c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
        c.execute('CREATE TABLE invest_events(id INTEGER,event_key TEXT,payload TEXT)')
        @contextlib.contextmanager
        def db():yield c
        self.assertEqual(reconcile(db,'a'*32,'2026-10-27','review'),{'report':'missing'})
        payload=json.dumps({'run_id':'a'*32,'orders':[],'summary':'unverified test'})
        c.execute('INSERT INTO invest_events VALUES(1,?,?)',('review:2026-10-27',payload))
        before=list(c.execute('SELECT * FROM invest_events'))
        for _ in range(2):
            result=reconcile(db,'a'*32,'2026-10-27','review')
            self.assertEqual(result['report'],'saved')
            self.assertEqual(result['payload_sha256'],hashlib.sha256(payload.encode()).hexdigest())
        self.assertEqual(reconcile(db,'b'*32,'2026-10-27','review')['report'],'run_mismatch')
        self.assertEqual(list(c.execute('SELECT * FROM invest_events')),before)

    def test_diagnostic_is_idempotent_and_not_an_investment_report(self):
        with tempfile.TemporaryDirectory() as root:
            for state in ('missing','saved','run_mismatch'):
                d=Path(root)/state
                receipt=dict(report=state,execution='failed',stop_confirmed=False)
                persist(d,'a'*32,receipt);persist(d,'a'*32,receipt)
                self.assertEqual(len(list(d.iterdir())),1)
                with self.assertRaises(RuntimeError):persist(d,'a'*32,dict(receipt,execution='returned'))
                saved=json.loads((d/('a'*32+'.json')).read_text())
                self.assertNotIn('orders',saved);self.assertNotIn('judgments',saved)
                self.assertEqual(saved['execution'],'failed')
            with patch('pathlib.Path.open',side_effect=OSError('disk failed')):
                with self.assertRaises(OSError):persist(Path(root)/'failure','b'*32,{})

if __name__=='__main__':unittest.main()
