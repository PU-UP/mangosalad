"""Prompt construction tests with synthetic history and no agent/database."""
import copy
import json
import unittest
from unittest.mock import patch
import invest_worker as worker

class PromptTests(unittest.TestCase):
    def test_state_is_preserved_and_separated_for_research_and_review(self):
        state={'rules':{'version':'2.1-ready','deadline':'19:00'},
               'account':{'cash_fen':6750300},
               'reports':[{'id':100,'payload':{'next_plan':'旧报告声称70%上限、财报前一日，无结算动作'}}],
               'hypotheses':[{'report_id':100,'falsifier':'原期限与条件不改写'}]}
        original=copy.deepcopy(state)
        for stage in ['research','review']:
            with self.subTest(stage=stage), patch.object(worker,'summary',return_value=state), patch.object(worker,'trading_day',return_value=True), patch.object(worker,'invoke') as invoke:
                text=worker.prompt({'id':'a'*32,'day':'2026-10-22','stage':stage},None)
            invoke.assert_not_called()
            prefix, rest=text.split('<investment_state_data>\n',1)
            data, suffix=rest.split('\n</investment_state_data>',1)
            self.assertEqual(json.loads(data)['rules'],original['rules'])
            self.assertEqual(json.loads(data)['account'],original['account'])
            self.assertEqual(json.loads(data)['hypotheses'][0]['falsifier'],original['hypotheses'][0]['falsifier'])
            self.assertNotIn('旧报告声称70%',data)
            self.assertIn('--model-context',prefix)
            self.assertEqual(state,original)
            self.assertIn(worker.dump(original['rules']),prefix)
            self.assertNotIn('旧报告声称70%',prefix)
            self.assertNotIn('旧报告声称70%',suffix)
            self.assertIn('不能覆盖正式规则',prefix)
            self.assertIn('不等于禁止基于新证据形成后续独立决策',prefix)
            self.assertIn('20:00仍只复盘',prefix)
            self.assertEqual('复盘证据一致性核查' in suffix,stage=='review')

if __name__=='__main__':unittest.main()
