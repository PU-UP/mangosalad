import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import invest_model_cli

class ModelRouteTests(unittest.TestCase):
    def invoke(self,args,value):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);token=root/'.config/mangosalad/olive.token';token.parent.mkdir(parents=True);token.write_text('isolated-test-only')
            stream=io.StringIO();argv=['invest_model_cli.py',*args]
            with patch('sys.argv',argv),patch('invest_cli.Path.home',return_value=root),patch.dict(os.environ,{'MANGO_DATA':td}),patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(value).encode())) as call,patch('sys.stdout',stream):
                invest_model_cli.main()
                import sys
                self.assertIs(sys.argv,argv)
            return json.loads(stream.getvalue()),call.call_args.args[0]
    def test_bare_status_really_projects(self):
        value={'rules':{'same':True},'reports':[{'id':7,'payload':{'counterevidence':'old full prose'}}],'hypotheses':[]}
        out,request=self.invoke(['status'],value)
        self.assertIn('context_projection',out);self.assertNotIn('old full prose',json.dumps(out));self.assertEqual(out['rules'],value['rules']);self.assertEqual(request.get_method(),'GET')
    def test_full_report_still_accessible(self):
        report={'id':7,'kind':'research','payload':{'counterevidence':'complete original'}}
        out,request=self.invoke(['status','--report-id','7'],{'journal':[report]})
        self.assertEqual(out['report'],report);self.assertTrue(request.full_url.endswith('/export'))
    def test_explicit_projection_not_duplicated(self):
        out,_=self.invoke(['status','--model-context'],{'reports':[],'hypotheses':[]});self.assertIn('context_projection',out)
    def test_market_route_unchanged(self):
        out,request=self.invoke(['market','--symbols','fixture'],{'ok':True});self.assertEqual(out,{'ok':True});self.assertTrue(request.full_url.endswith('/market?symbols=fixture'))
    def test_skill_and_prompt_bind_actual_entrypoint(self):
        root=Path(__file__).parent;skill=(root/'skill/olive-investing/SKILL.md').read_text()
        self.assertIn('invest_model_cli.py',skill);self.assertNotIn('只用 `python3 /home/ubuntu/mangosalad-desk/invest_cli.py`',skill)
        self.assertIn('invest_model_cli.py status',(root/'invest_worker.py').read_text())

if __name__=='__main__':unittest.main()
