import unittest
import sys
from datetime import date
sys.path.insert(0,"scripts")
from outlook_candidate import score,recency

class OutlookTest(unittest.TestCase):
    def setUp(self):
        self.stock={"ticker":"005930","close":100}
        self.day=date(2026,11,24)
        self.report={"ticker":"005930","broker":"A증권","published_at":"2026-11-20","rating":"매수","target_price":150,"source_url":"https://example.com/1","verification_method":"test","verified_at":"2026-11-20"}
    def test_missing_zero_not_coverage(self):
        r=score(self.stock,[],self.day)
        self.assertEqual(r["points_out_of_10"],0)
        self.assertEqual(r["observed_coverage_pct"],0)
        self.assertEqual(r["policy_calculation_pct"],70)
        self.assertFalse(r["full_policy_score_available"])
    def test_one_broker(self):
        r=score(self.stock,[self.report],self.day)
        self.assertEqual(r["points_out_of_10"],5.5)
        self.assertEqual(r["observed_coverage_pct"],60)
        self.assertEqual(r["detail"]["revision"]["status"],"missing_zero_policy")
    def test_sell_observed(self):
        r=score(self.stock,[dict(self.report,rating="매도",target_price=None)],self.day)
        self.assertEqual(r["detail"]["rating"]["points"],0)
        self.assertTrue(r["detail"]["rating"]["observed"])
    def test_duplicate_broker(self):
        r=score(self.stock,[self.report,dict(self.report,broker="A증권(주)")],self.day)
        self.assertEqual(r["detail"]["rating"]["broker_count"],1)
    def test_reject_future_unverified_stale(self):
        for row in [dict(self.report,published_at="2026-11-25"),dict(self.report,verified_at=None),dict(self.report,published_at="2026-01-01")]:
            self.assertEqual(score(self.stock,[row],self.day)["observed_coverage_pct"],0)
    def test_recency(self):
        self.assertEqual([recency(x) for x in (30,31,61,91,121,181)],[1,.9,.8,.6,.4,0])
    def test_conflicting_same_day(self):
        r=score(self.stock,[self.report,dict(self.report,target_price=200)],self.day)
        self.assertFalse(r["detail"]["upside"]["observed"])
    def test_revision_confirmed_basis(self):
        earlier=dict(self.report,published_at="2026-10-01",target_price=125,target_price_basis_verified=True)
        current=dict(self.report,target_price_basis_verified=True)
        r=score(self.stock,[earlier,current],self.day)
        self.assertEqual(r["detail"]["revision"]["points"],1)
    def test_no_historical_forecast(self):
        f={"ticker":"005930","metric":"sales_forecast_growth","published_at":"2026-11-20","period_end":"2025-12-31","value":20,"verified":True,"forward_looking":True,"basis_verified":True,"unit":"percent","source_kind":"issuer_guidance","source_url":"https://example.com/ir"}
        self.assertFalse(score(self.stock,[],self.day,[f])["detail"]["sales_forecast_growth"]["observed"])
        self.assertTrue(score(self.stock,[],self.day,[dict(f,period_end="2027-12-31")])["detail"]["sales_forecast_growth"]["observed"])
if __name__=="__main__":
    unittest.main()
