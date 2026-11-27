import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from leading_true_cagr import combine
class TrueCAGR(unittest.TestCase):
    def test_three_intervals(self):
        a={"currency":"KRW","account":"ifrs-full_Revenue","values":{2025:1331,2024:1210,2023:1100},"receipt":"a","available":"2026-03-01"}
        b={**a,"values":{2024:1210,2023:1100,2022:1000},"receipt":"b","available":"2025-03-01"}
        self.assertIsNone(combine([a],2025));self.assertAlmostEqual(combine([a,b],2025)["value"],10)
        self.assertIsNone(combine([a,{**b,"currency":"USD"}],2025))
if __name__=="__main__":unittest.main()
