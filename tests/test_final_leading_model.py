import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from final_leading_model import BASE,LEADING,SPECIAL_RELATIVE,evaluate,curve,group_weights

def obs(v=1):
    return {"value":v,"verified":True,"source_ref":"synthetic test only","basis":"test basis",
            "asof":"2026-11-24","available_on":"2026-11-24"}

def fixture():
    keys={k for m in BASE.values() for k in m}|{k for m in LEADING.values() for k in m}
    return {"asof":"2026-11-24","stocks":[{"ticker":str(i),"industry_code":"001",
             "metrics":{k:obs(min(i,3) if k=="rating" else i) for k in keys}} for i in range(5)]}

class FinalModelTests(unittest.TestCase):
    def test_weights(self):
        self.assertEqual([sum(m.values()) for m in BASE.values()],[20,20,10,10,10,10,10,10])
        self.assertEqual([sum(m.values()) for m in LEADING.values()],[30,25,20,15,10])
        for model in SPECIAL_RELATIVE:
            self.assertEqual(sum(group_weights({"financial_model":model})["industry_relative"].values()),10)
    def test_complete(self):
        r=evaluate(fixture())
        self.assertEqual(r["coverage"],{"base_complete":5,"leading_complete":5,"combined_complete":5})
        x=r["records"][0]
        self.assertAlmostEqual(x["combined"],.6*x["base"]["score"]+.4*x["leading"]["score"],delta=.0051)
    def test_comparison_only_peers(self):
        p=fixture()
        p["stocks"]=p["stocks"][:4]
        peer=fixture()["stocks"][4]
        peer["peer_only"]=True
        p["comparison_peers"]=[peer]
        result=evaluate(p)
        self.assertEqual(len(result["records"]),4)
        self.assertNotIn(peer["ticker"],result["leading_top10"])
        self.assertNotIn(peer["ticker"],result["base_top15"])
        self.assertIsNotNone(result["records"][0]["base"]["detail"]["roic"]["points"])
        self.assertIsNone(result["records"][0]["base"]["detail"]["roe"]["points"])
    def test_missing_and_future(self):
        p=fixture()
        p["stocks"][0]["metrics"].pop("foreign_60d")
        p["stocks"][0]["metrics"]["op_revision_30d"]["available_on"]="2026-11-25"
        r=evaluate(p)
        x=r["records"][0]
        self.assertIsNone(x["base"]["score"])
        self.assertIsNone(x["leading"]["score"])
        self.assertIsNone(x["combined"])
        self.assertNotIn("0",r["combined_top15"])
        self.assertIsNone(x["grade"])
        self.assertEqual(x["leading"]["coverage_pct"],90)
    def test_missing_peer(self):
        p=fixture()
        p["stocks"].pop()
        r=evaluate(p)
        self.assertIsNone(r["records"][0]["base"]["score"])
        self.assertIsNotNone(r["records"][0]["leading"]["score"])
    def test_direction(self):
        self.assertGreater(curve("op_revision_30d",5),curve("op_revision_30d",-5))
        self.assertGreater(curve("overheat",0),curve("overheat",20))
    def test_excluded(self):
        p=fixture()
        p["stocks"][0]["excluded"]=True
        r=evaluate(p)
        self.assertNotIn("0",r["leading_top10"])
        self.assertIsNone(r["records"][0]["combined"])
    def test_stale_market_metric(self):
        p=fixture()
        p["stocks"][0]["metrics"]["foreign_5d"]["asof"]="2026-11-23"
        self.assertIsNone(evaluate(p)["records"][0]["base"]["score"])
    def test_unknown_financial_model(self):
        p=fixture()
        for r in p["stocks"]: r["financial_model"]="financial_unclassified"
        self.assertIsNone(evaluate(p)["records"][0]["base"]["score"])
    def test_unverified(self):
        p=fixture()
        p["stocks"][0]["metrics"]["joint_buy"]["verified"]=False
        self.assertIsNone(evaluate(p)["records"][0]["leading"]["score"])

if __name__=="__main__": unittest.main()
