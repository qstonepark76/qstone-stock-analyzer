import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from leading_direct_fundamental_replay import direct_growth,direct_financial
class DirectReplay(unittest.TestCase):
    def test_symmetric(self):
        r={"year":2025,"annual_actuals":{"op":{"2024":100,"2025":200},"sales":{"2022":1000,"2023":1100,"2024":1210,"2025":1331}}}
        v=direct_growth(r)
        self.assertAlmostEqual(v["op_growth"],200/3);self.assertAlmostEqual(v["sales_cagr"],10)
    def test_specialist(self):
        r={"fields":{"roe":{"value":8},"stability":{"value":100}}}
        self.assertEqual(direct_financial(r,"bank_group"),{"roe":8})
if __name__=="__main__":unittest.main()
