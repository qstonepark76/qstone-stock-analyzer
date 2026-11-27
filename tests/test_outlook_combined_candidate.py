import unittest,sys
from datetime import date
sys.path.insert(0,"scripts")
from outlook_candidate import score,WEIGHTS
from outlook_combined_candidate import combined
class CombinedTest(unittest.TestCase):
    def setUp(self):
        self.asof=date(2026,11,24)
        self.ext=score({"ticker":"005930","close":100},[],self.asof)
        self.model={"ticker":"005930","source_kind":"qstone_model_forecast","asof":"2026-11-24","period_end":"2026-12-31","values":{k:{"metric":k,"value":10} for k in ("sales_forecast_growth","operating_profit_forecast_growth","earnings_forecast_revision")}}
        self.gates={k:{"candidate_pass":True,"n":30} for k in ("sales","op","net")}
    def test_weights_unchanged(self):
        self.assertEqual(list(WEIGHTS.values()),[3,3,1,1,1,1])
    def test_own_points_not_external(self):
        r=combined(self.ext,self.model,self.gates,self.asof,"005930")
        self.assertEqual(r["external_observed_pct"],0)
        self.assertEqual(r["own_model_coverage_pct"],30)
        self.assertEqual(r["policy_calculation_pct"],100)
        self.assertGreater(r["points_out_of_10"],0)
        self.assertFalse(r["official"])
        self.assertEqual(r["detail"]["rating"]["status"],"missing_zero_policy")
    def test_external_precedence(self):
        self.ext["detail"]["sales_forecast_growth"].update({"observed":True,"points":.4,"value":-4,"status":"observed"})
        r=combined(self.ext,self.model,self.gates,self.asof,"005930")
        self.assertEqual(r["detail"]["sales_forecast_growth"]["points"],.4)
        self.assertEqual(r["external_observed_pct"],10)
        self.assertEqual(r["own_model_coverage_pct"],20)
    def test_no_gate_no_score(self):
        self.gates["sales"]["candidate_pass"]=False
        r=combined(self.ext,self.model,self.gates,self.asof,"005930")
        self.assertIsNone(r["detail"]["sales_forecast_growth"]["points"])
    def test_wrong_ticker(self):
        self.model["ticker"]="000660"
        r=combined(self.ext,self.model,self.gates,self.asof,"005930")
        self.assertEqual(r["own_model_coverage_pct"],0)
if __name__=="__main__":unittest.main()
