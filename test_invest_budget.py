import unittest
from datetime import datetime, timezone, timedelta
from invest_budget import plan, remaining
TZ=timezone(timedelta(hours=8))

class BudgetTests(unittest.TestCase):
    def test_runtime_budget_never_extends_formal_window(self):
        run=dict(id='a'*32,day='2026-10-27',stage='research');schedule=dict(deadline='19:00')
        for hour,minute,total,research in [(17,5,1200,900),(18,50,570,270)]:
            stamp=datetime(2026,10,27,hour,minute,tzinfo=TZ);c=plan(run,schedule,stamp)
            self.assertEqual((c['seconds'],c['research_seconds']),(total,research))
            self.assertLess(c['expires_at'],datetime(2026,10,27,19,tzinfo=TZ).timestamp())
            self.assertEqual(remaining(c,stamp+timedelta(seconds=40)),total-40)
            self.assertEqual(remaining(c,stamp+timedelta(seconds=total+1)),0)
        self.assertIsNone(plan(run,schedule,datetime(2026,10,27,18,59,45,tzinfo=TZ)))
        run['stage']='review';c=plan(run,schedule,datetime(2026,10,27,20,50,tzinfo=TZ))
        self.assertEqual(c['seconds'],570)
        self.assertTrue(c['window_ends_at'].endswith('21:00:00+08:00'))

if __name__=='__main__':unittest.main()
