import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from leading_full_score_preview import candidate,summarize_slots,combine
class FullPreview(unittest.TestCase):
    def test_partial(self):
        x={"a":{"weight":60,"points":42},"b":{"weight":40,"points":None}}
        a=summarize_slots(x);self.assertEqual(a["coverage_pct"],60)
        self.assertEqual(a["observed_points"],42);self.assertIsNone(a["final_score"])
        self.assertFalse(candidate(x["b"],41,{},"test","test"))
        self.assertTrue(candidate(x["b"],20,{},"test","test"))
        b=summarize_slots(x);self.assertTrue(b["candidate_all_slots_filled"])
        self.assertIsNone(b["final_score"]);self.assertIsNone(combine(a,b)["final_score"])
        self.assertEqual(combine(a,b)["coverage_pct"],76)
if __name__=="__main__":unittest.main()
