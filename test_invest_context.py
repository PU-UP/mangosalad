import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from invest_context import project, full_report
import invest_cli

class ContextTests(unittest.TestCase):
    def setUp(self):
        self.report={'id':7,'kind':'research','day':'2026-10-26','at':'2026-10-26T17:00:00+08:00','payload':{'facts':[{'text':'adverse fact','evidence_id':'e1','event_date':None}], 'orders':[{'symbol':'fixture','side':'sell','qty':100,'quote_id':'q1'}], 'counterevidence':'OLD COUNTEREVIDENCE','inferences':'OLD INFERENCE','judgments':[{'reason':'OLD REASON','sizing':'OLD SIZING'}], 'reviews':[{'report_id':3,'symbol':'fixture','verdict':'pending','reason':'OLD REVIEW','evidence_ids':['e1']}]}}
        self.state={'rules':{'goal':'unchanged'},'account':{'fixture':True},'history':[{'immutable':True}],'latest':{'immutable':True},'reports':[self.report],'hypotheses':[{'report_id':7,'action':'hold','symbol':'fixture','horizon_days':4,'due':'2026-10-30','falsifier':'ORIGINAL CONDITION','risk':'ADVERSE RISK','evidence_ids':['e1'],'reason':'OLD REASON','sizing':'OLD SIZING','resolution':{'verdict':'pending','reason':'OLD REVIEW','evidence_ids':['e1']}}]}
    def test_no_mutation_and_factual_fields_equal(self):
        before=copy.deepcopy(self.state);out=project(self.state)
        self.assertEqual(before,self.state)
        for k in ('rules','account','history','latest'):self.assertEqual(out[k],before[k])
        for k in ('facts','orders'):self.assertEqual(out['reports'][0]['payload'][k],self.report['payload'][k])
    def test_no_duplicate_analysis_but_risk_and_references_retained(self):
        out=project(self.state);text=json.dumps(out)
        for phrase in ('OLD REASON','OLD SIZING','OLD COUNTEREVIDENCE','OLD INFERENCE','OLD REVIEW'):self.assertNotIn(phrase,text)
        h=out['hypotheses'][0]
        for k in ('falsifier','due','horizon_days','risk','evidence_ids','action'):self.assertEqual(h[k],self.state['hypotheses'][0][k])
        self.assertEqual(h['resolution']['verdict'],'pending')
        self.assertIn('--report-id 7',out['reports'][0]['full_report_command'])
        self.assertIn('counterevidence',out['reports'][0]['analysis_index'])
    def test_full_history_fetch_including_beyond_summary_window(self):
        export={'summary':{'reports':[]},'journal':[self.report]}
        got=full_report(export,7);self.assertEqual(got['report'],self.report)
        got['report']['payload']['orders'].clear();self.assertTrue(self.report['payload']['orders'])
        with self.assertRaises(ValueError):full_report(export,8)
    def test_annotations_are_separate_and_scoped(self):
        notes=[{'report_id':7,'original_quote':'OLD REASON','finding':'not a formal rule'}, {'report_id':99,'finding':'unrelated'}]
        out=project(self.state,notes);self.assertEqual(out['context_review_notes'],notes[:1])
        self.assertEqual(full_report({'journal':[self.report]},7,notes)['report'],self.report)
        self.assertNotIn('context_review_notes',self.report)
    def cli(self,args,payload):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);token=root/'.config/mangosalad/olive.token';token.parent.mkdir(parents=True);token.write_text('isolated-test-only')
            stream=io.StringIO()
            with patch('sys.argv',['invest_cli.py']+args), patch('invest_cli.Path.home',return_value=root), patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(payload).encode())) as call, patch.dict(os.environ,{'MANGO_DATA':td}), patch('sys.stdout',stream):
                invest_cli.main()
            return json.loads(stream.getvalue()),call.call_args.args[0].full_url
    def test_cli_default_remains_full(self):
        out,url=self.cli(['status'],self.state);self.assertEqual(out,self.state);self.assertTrue(url.endswith('/api/invest'))
    def test_cli_model_view_is_opt_in(self):
        out,url=self.cli(['status','--model-context'],self.state);self.assertEqual(out,project(self.state));self.assertTrue(url.endswith('/api/invest'))
    def test_cli_full_report_uses_existing_export(self):
        out,url=self.cli(['status','--report-id','7'],{'journal':[self.report]});self.assertEqual(out['report'],self.report);self.assertTrue(url.endswith('/api/invest/export'))
    def test_flags_cannot_change_write_operations(self):
        with patch('sys.argv',['invest_cli.py','report','--model-context']),patch('sys.stderr',io.StringIO()):
            with self.assertRaises(SystemExit):invest_cli.main()

if __name__=='__main__':unittest.main()
