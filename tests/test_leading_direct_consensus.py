import sys,unittest
from pathlib import Path
from datetime import date
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from leading_direct_consensus import parse,target_pairs
class Consensus(unittest.TestCase):
    def test_direct(self):
        html='<table><tr><th>구분</th><th>날짜</th><th>2026/11/27</th><th>1주전</th><th>1개월전</th></tr><tr><td>영업이익(억원)</td><td>2026/12</td><td>120</td><td>110</td><td>100</td></tr></table>'
        z,_=parse(html,date(2026,11,28),"005930")
        self.assertAlmostEqual(z["op_revision_1m"]["value"],200*20/220)
        self.assertEqual(parse(html,date(2026,12,10),"005930")[0],{})
    def test_targets(self):
        rows=[{"broker":"A","report_date":"2026-10-20","target_price_candidate":100},{"broker":"A","report_date":"2026-11-20","target_price_candidate":120}]
        self.assertAlmostEqual(target_pairs(rows,date(2026,11,28))[0]["value"],20)
if __name__=="__main__":unittest.main()
