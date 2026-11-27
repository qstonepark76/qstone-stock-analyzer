import sys,unittest
from pathlib import Path
from datetime import date
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from forecast_score_policy import choose_forecast,forecast_fraction,valid
from final_leading_model import evaluate
D=date(2026,11,24)
def item(kind="own_model",metric="op_forecast_growth",v=20):
    return {"metric":metric,"source_kind":kind,"value":v,"verified":True,"basis_verified":True,
            "admission_gate_pass":True,"source_ref":"test","basis":"annual growth","validation_ref":"test validation",
            "account_basis":"operating profit","scope":"CFS","unit":"percent","asof":D.isoformat(),
            "available_on":D.isoformat(),"period_end":"2026-12-31","out_of_sample_validated":True,
            "model_version":"test","broker":"broker A","independent_brokers":["A","B","C"]}
class Policy(unittest.TestCase):
    def test_neutral_shrink(self):
        self.assertAlmostEqual(forecast_fraction("op_forecast_growth",20,"own_model"),.9)
        self.assertAlmostEqual(forecast_fraction("op_forecast_growth",-20,"own_model"),.1)
        self.assertEqual(forecast_fraction("op_forecast_growth",0,"own_model"),.5)
    def test_priority(self):
        self.assertEqual(choose_forecast("op_forecast_growth",[item(v=20),item("single_broker",v=-20)],D)["source_kind"],"single_broker")
    def test_conflict(self):
        self.assertIsNone(choose_forecast("op_forecast_growth",[item(v=20),item(v=10)],D))
    def test_gate(self):
        x=item();x["out_of_sample_validated"]=False
        self.assertIsNone(choose_forecast("op_forecast_growth",[x],D))
    def test_breadth(self):
        self.assertFalse(valid("upward_broker_share",item(metric="upward_broker_share"),D))
    def test_window(self):
        x=item(metric="op_revision_30d");x.update(prior_cutoff="2026-10-25",prior_available_on="2026-10-20",current_available_on="2026-11-20",same_period_basis=True)
        self.assertTrue(valid("op_revision_30d",x,D));x["prior_cutoff"]="2026-08-24";self.assertFalse(valid("op_revision_30d",x,D))
    def test_future(self):
        x=item();x["available_on"]="2026-11-25";self.assertFalse(valid("op_forecast_growth",x,D))
    def test_integration(self):
        p={"asof":D.isoformat(),"stocks":[{"ticker":"1","metrics":{},"forecast_evidence":{"op_forecast_growth":[item()]}}]}
        r=evaluate(p)["records"][0];self.assertAlmostEqual(r["base"]["detail"]["op_forecast_growth"]["points"],1.8)
        self.assertIsNone(r["base"]["score"])
    def test_bins(self):
        self.assertEqual(forecast_fraction("op_revision_30d",20,"broker_consensus"),1)
        self.assertEqual(forecast_fraction("op_revision_30d",-21,"broker_consensus"),0)
if __name__=="__main__":unittest.main()
