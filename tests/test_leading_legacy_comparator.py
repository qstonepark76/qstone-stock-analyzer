import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from leading_legacy_comparator import make_cohorts,evaluate_cohort
class Legacy(unittest.TestCase):
    def test_next_open(self):
        r={"status":"pending","tickers":["A"],"sessions":["1","2"]}
        p={"A":{"1":{"open":100,"close":105},"2":{"close":110}}}
        i={"1":{"open":100},"2":{"close":103}}
        v=evaluate_cohort(r,p,i)
        self.assertEqual(v["status"],"evaluated")
        self.assertAlmostEqual(v["net_return_pct"],9.67)
        self.assertAlmostEqual(v["excess_pct"],6.67)
    def test_missing(self):
        r={"status":"pending","tickers":["A","B"],"sessions":["1"]}
        p={"A":{"1":{"open":100,"close":105}}};i={"1":{"open":100,"close":103}}
        self.assertEqual(evaluate_cohort(r,p,i)["status"],"missing_constituent_or_delisting")
    def test_maturity(self):
        d=["20261117","20261118"]
        h=[{"as_of":"2026-11-17","strategies":{"overall":[{"ticker":"A","close":100}]}}]
        self.assertTrue(all(r["status"]=="not_mature" for r in make_cohorts(h,d,{"20261117":{"A":{"close":100}}})))
if __name__=="__main__":unittest.main()
