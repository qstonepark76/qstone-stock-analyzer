import sys,unittest
from datetime import date
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from leading_stage6_scenarios import verify_evidence,asof_reports
ASOF=date(2026,11,24)
def fixture():
    src={"status":"source_received","corp_code":"123","scope":"CFS","receipts":["20260331000001"]}
    d={"status":"own_model_candidate","source_kind":"qstone_model_forecast","value":25.0,"model_evidence":{"estimate":125,"prior_year_actual":100,"annual_receipt":"20260331000001","quarter_receipt":"20261114000001","currency":"KRW","account_id":"dart_OperatingIncomeLoss"},"backtest":{"candidate_pass":True,"n":25,"smape":15,"baseline_smape":20}}
    return d,src
class Scenario(unittest.TestCase):
    def test_recompute(self):
        d,s=fixture();v,_=verify_evidence(d,"op_forecast_growth",s,ASOF);self.assertEqual(v["value"],25);self.assertFalse(v["official"])
    def test_wrong_receipt(self):
        d,s=fixture();d["model_evidence"]["quarter_receipt"]="20261125000001";self.assertIsNone(verify_evidence(d,"op_forecast_growth",s,ASOF)[0])
    def test_conflict_value(self):
        d,s=fixture();d["value"]=30;self.assertIsNone(verify_evidence(d,"op_forecast_growth",s,ASOF)[0])
    def test_gate(self):
        d,s=fixture();d["backtest"]["smape"]=25;self.assertIsNone(verify_evidence(d,"op_forecast_growth",s,ASOF)[0])
    def test_future_enrichment(self):
        r={"ticker":"1","broker":"A","published_at":"2026-11-20","verified_at":"2026-11-20T10:00:00+09:00","verification_method":"explicit","source_url":"https://example.com/a","rating":"매수","target_price":100}
        late={**r,"verified_at":"2026-11-25T00:00:00+09:00","target_price":200}
        rows,c=asof_reports([[r],[late]],ASOF);self.assertEqual(len(rows),1);self.assertEqual(c,0)
if __name__=="__main__":unittest.main()
