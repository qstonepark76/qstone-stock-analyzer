import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from leading_market_inputs import flow_metrics,price_metrics,session_rows
from leading_backtest import test,VERSION
class Inputs(unittest.TestCase):
    def test_flow_exact_windows(self):
        days=[str(i) for i in range(61)];rows={d:(2,3,100) for d in days}
        r=flow_metrics(rows,days)
        self.assertEqual(r["foreign_60d"],2)
        self.assertEqual(r["institution_acceleration"],0)
        rows.pop(days[-10])
        r=flow_metrics(rows,days)
        self.assertNotIn("foreign_20d",r);self.assertNotIn("foreign_60d",r);self.assertIn("foreign_5d",r)
    def test_price_reconciliation(self):
        days=[str(i) for i in range(61)];rows={d:(100+int(d),) for d in days}
        self.assertEqual(price_metrics(rows,days,161,{}),{})
        self.assertAlmostEqual(price_metrics(rows,days,160,{})["momentum_60d"],60)
    def test_conflicting_rows(self):
        self.assertEqual(session_rows([{"stck_bsop_date":"d","x":"1"},{"stck_bsop_date":"d","x":"2"}],("x",),{"d"}),{})
class Backtest(unittest.TestCase):
    def fixture(self):
        ds=[f"2026-01-{i:02}" for i in range(1,9)]
        panel={"verified":True,"basis":"corporate_action_adjusted_ohlc","sessions":ds,
            "prices":{"A":{d:{"open":100,"close":110} for d in ds}},
            "benchmark":{d:{"open":100,"close":105} for d in ds}}
        snap={"asof":ds[0],"model_version":VERSION,"point_in_time_verified":True,"base_top15":["A"]}
        return snap,panel
    def test_net_return_and_next_open(self):
        s,p=self.fixture();r=test([s],p,30);v=r["summary"]["base_top15"]["1w"]
        self.assertEqual(v["evaluated_cohorts"],1)
        self.assertAlmostEqual(v["net_return_pct"],9.67)
        self.assertAlmostEqual(v["excess_pct"],4.67)
        self.assertEqual(r["cohorts"][0]["entry"],p["sessions"][1])
    def test_missing_invalidates_cohort(self):
        s,p=self.fixture();s["base_top15"].append("B")
        self.assertEqual(test([s],p)["cohorts"][0]["status"],"missing_constituent_or_delisting")
    def test_no_future_or_unverified(self):
        s,p=self.fixture();s["point_in_time_verified"]=False
        self.assertEqual(test([s],p)["status"],"no_verified_mature_cohorts")
if __name__=="__main__":unittest.main()
