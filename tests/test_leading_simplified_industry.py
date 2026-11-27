import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from final_leading_model import evaluate,group_weights,SIMPLIFIED_SPECIAL
def o(v):return {"value":v,"verified":True,"basis":"test","source_ref":"fixture","asof":"2025-12-31","available_on":"2026-03-31","metric_id":"operating_return_on_assets"}
class Simple(unittest.TestCase):
    def test_weights(self):
        for model in [None,*SIMPLIFIED_SPECIAL]:
            w=group_weights({"financial_model":model,"simplified_industry_policy":True})
            self.assertEqual(sum(w["industry_relative"].values()),10)
            self.assertEqual(len(w["industry_relative"]),3 if model else 4)
    def test_parent(self):
        p={"asof":"2026-11-24","industry_policy":"simplified_v1","stocks":[{"ticker":str(i),"industry_code":"26"+str(i),"metrics":{"operating_return_on_assets":o(i)}} for i in range(5)]}
        d=evaluate(p)["records"][0]["base"]["detail"]["operating_return_on_assets"]
        self.assertEqual(d["peer_count"],5);self.assertEqual(d["peer_level"],"KSIC_2digit");self.assertIsNotNone(d["points"])
    def test_no_cross_division(self):
        p={"asof":"2026-11-24","industry_policy":"simplified_v1","stocks":[{"ticker":str(i),"industry_code":str(20+i)+"1","metrics":{"operating_return_on_assets":o(i)}} for i in range(5)]}
        self.assertIsNone(evaluate(p)["records"][0]["base"]["detail"]["operating_return_on_assets"]["points"])
if __name__=="__main__":unittest.main()
