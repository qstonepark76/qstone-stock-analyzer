import unittest,sys
from datetime import date
sys.path.insert(0,"scripts")
from own_forecast_v2 import change,candidates,choose,error
from outlook_candidate import score,WEIGHTS
class OwnForecastV2Test(unittest.TestCase):
    def test_loss_directions(self):
        self.assertGreater(change(-30,-100,True)[0],0)
        self.assertLess(change(-100,-30,True)[0],0)
        self.assertEqual(change(30,-100,True),(200,"symmetric_profit_change"))
        self.assertEqual(change(-30,100,True),(-200,"symmetric_profit_change"))
        self.assertEqual(change(0,0,True),(0,"symmetric_profit_change"))
    def test_ordinary_growth(self):
        value,basis=change(120,100,True)
        self.assertAlmostEqual(value,20.0,places=10)
        self.assertEqual(basis,"ordinary_growth")
        self.assertIsNone(change(10,0,False))
    def test_models(self):
        self.assertEqual(candidates(100,90,75,3)["seasonal_residual"],115)
        self.assertEqual(candidates(100,90,75,3)["annualized_ytd"],120)
        self.assertEqual(candidates(100,90,75,3)["trend_scaled_residual"],120)
        self.assertEqual(candidates(100,90,75,3,1.2)["asset_scaled_residual"],120)
        self.assertNotIn("asset_scaled_residual",candidates(100,90,75,3))
    def test_holdout_not_selection(self):
        a=[{"error":2,"baseline_error":10}]*5
        b=[{"error":5,"baseline_error":10}]*5
        bad=[{"error":20,"baseline_error":10}]*5
        r=choose({"a":a,"b":b},{"a":bad,"b":a})
        self.assertEqual(r["model"],"a")
        self.assertFalse(r["candidate_pass"])
    def test_missing_target_revision_zero(self):
        r=score({"ticker":"005930","close":100},[],date(2026,11,24))
        self.assertEqual(r["detail"]["revision"]["points"],0)
        self.assertFalse(r["detail"]["revision"]["observed"])
        self.assertEqual(r["policy_calculation_pct"],70)
        self.assertEqual(list(WEIGHTS.values()),[3,3,1,1,1,1])
if __name__=="__main__":unittest.main()
