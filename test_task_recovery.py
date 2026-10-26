
"""No models, Gateway RPC or notifications; real temporary SQLite stores."""
import contextlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from task_recovery import PAGE, outcome, register, collect, visible_result, MAX_ATTEMPTS

def parse(text):
    d=json.loads(text)
    if d.get('kind') not in ('work','discussion','reminder') or d.get('status') not in ('done','waiting') or not d.get('message'):
        raise ValueError()
    return d

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'mango.sqlite';self.native=self.root/'native.sqlite'
        with self.db() as c:
            c.execute('CREATE TABLE tasks(id TEXT PRIMARY KEY,page_id TEXT,agent TEXT,status TEXT,result TEXT,error TEXT,revision INTEGER,created REAL,updated REAL,receipt TEXT)')
            c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?)',('t1',PAGE,'olive','interrupted','original timeout','provider_timeout: stop unconfirmed',4,1,1,'original-notification'))
        with sqlite3.connect(self.native) as c:
            c.execute('CREATE TABLE session_nodes(session_key TEXT,current_session_id TEXT)')
            c.execute('CREATE TABLE transcript_events(session_id TEXT,seq INTEGER,event_json TEXT)')
            c.execute('INSERT INTO session_nodes VALUES(?,?)',('agent:main:mangosalad:t1','s1'))
        self.task={'id':'t1','page_id':PAGE,'agent':'olive'}
        self.folder=self.root/'task-runs/t1';self.folder.mkdir(parents=True)
    @contextlib.contextmanager
    def db(self):
        c=sqlite3.connect(self.path);c.row_factory=sqlite3.Row
        try:
            yield c;c.commit()
        finally:c.close()
    def put(self,text=None,role='assistant',stop='stop'):
        text=text or json.dumps({'kind':'work','status':'done','message':'late candidate only'})
        event={'message':{'role':role,'stopReason':stop,'content':[{'type':'thinking','thinking':'must never collect'},{'type':'text','text':text}]}}
        with sqlite3.connect(self.native) as c:c.execute('INSERT INTO transcript_events VALUES(?,?,?)',('s1',1,json.dumps(event)))
    def row(self):
        with self.db() as c:return dict(c.execute('SELECT * FROM tasks').fetchone())
    def test_timeout_classification_and_other_projects(self):
        d=outcome(self.task,json.dumps({'status':'timeout','timeoutPhase':'provider'}),0,False,True)
        self.assertEqual(d['status'],'interrupted');self.assertIn('停止未确认',d['error']);self.assertTrue(d['recover'])
        other=self.task|{'page_id':'other-project'}
        self.assertIsNone(outcome(other,'{"status":"timeout"}',0,False,True))
        for raw,rc,expired,ack,reason in [('{}',1,False,True,'transport_exit'),('{}',0,True,True,'worker_deadline'),('{}',0,False,False,'ack_missing')]:
            self.assertTrue(outcome(self.task,raw,rc,expired,ack)['error'].startswith(reason))
        self.assertIsNone(outcome(self.task,'{"status":"ok"}',0,False,True))
    def test_recovery_is_unreviewed_idempotent_and_preserves_failure(self):
        register(self.folder,self.task,100);self.put();collect(self.db,self.root,self.native,parse,100)
        first=self.row();self.assertEqual(first['status'],'interrupted');self.assertEqual(first['error'],'provider_timeout: stop unconfirmed')
        self.assertEqual(first['receipt'],'original-notification');self.assertIn('尚未验收',first['result']);self.assertIn('original timeout',first['result'])
        self.assertNotIn('must never collect',first['result']);collect(self.db,self.root,self.native,parse,200);self.assertEqual(self.row(),first)
    def test_commit_before_receipt_crash_does_not_duplicate(self):
        register(self.folder,self.task,100);self.put();collect(self.db,self.root,self.native,parse,100);first=self.row()
        p=self.folder/'recovery.json';d=json.loads(p.read_text());d['state']='pending';d['next_check']=150;p.write_text(json.dumps(d))
        collect(self.db,self.root,self.native,parse,200);self.assertEqual(self.row(),first)
    def test_cancelled_task_and_unregistered_history_unchanged(self):
        self.put();before=self.row();collect(self.db,self.root,self.native,parse,100);self.assertEqual(before,self.row())
        register(self.folder,self.task,100)
        with self.db() as c:c.execute("UPDATE tasks SET status='cancelled'")
        before=self.row();collect(self.db,self.root,self.native,parse,100);self.assertEqual(before,self.row())
    def test_bounded_reads_and_no_final_text(self):
        register(self.folder,self.task,100);self.put(role='toolResult')
        for n in range(20):collect(self.db,self.root,self.native,parse,100+n*60)
        d=json.loads((self.folder/'recovery.json').read_text());self.assertLessEqual(d['attempts'],MAX_ATTEMPTS);self.assertEqual(d['state'],'unresolved')
        self.assertEqual(self.row()['result'],'original timeout')
    def test_missing_database_is_bounded_and_never_created(self):
        register(self.folder,self.task,100);missing=self.root/'missing.sqlite'
        collect(self.db,self.root,missing,parse,100);self.assertFalse(missing.exists())
        self.assertEqual(json.loads((self.folder/'recovery.json').read_text())['last_read_error'],'native_result_unavailable')
    def test_only_exact_session_final_envelope_accepted(self):
        self.put(text='not a result');self.assertIsNone(visible_result(self.native,'agent:main:mangosalad:t1',parse))
        self.assertIsNone(visible_result(self.native,'another-session',parse))

if __name__=='__main__':unittest.main()
