import sys,unittest
sys.path.insert(0,"scripts")
from forecast_extended_models import canonical,extended_candidates
class ExtendedForecastTest(unittest.TestCase):
    def test_alias(self):
        self.assertEqual(canonical("ifrs-full_Revenue"),canonical("ifrs_Revenue"))
        self.assertNotEqual(canonical("dart_OperatingIncomeLoss"),canonical("ifrs-full_ProfitLoss"))
    def test_partial_year(self):
        self.assertEqual(extended_candidates(120,90,None,3),{"annualized_ytd":120.0})
    def test_ensemble(self):
        r=extended_candidates(120,80,60,3)
        self.assertIn("equal_weight_ensemble",r)
        self.assertNotIn("ttm",r)
    def test_component_not_substitution(self):
        r=extended_candidates(100,80,70,3,components=[{"account_id":"example","annual":50,"current_ytd":40,"prior_ytd":25}])
        self.assertEqual(r["component_trend:example"],125.0)
        self.assertNotEqual(r["component_trend:example"],40)
if __name__=="__main__":unittest.main()
