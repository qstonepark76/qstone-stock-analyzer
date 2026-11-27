import sys,unittest
from pathlib import Path
from statistics import pstdev
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from leading_industry_margin_recovery import combine
class MarginRecovery(unittest.TestCase):
    def test_latest_comparatives(self):
        a={"currency":"KRW","accounts":["Revenue","OperatingIncomeLoss"],"values":{2025:10,2024:20},"available":"2026-03-01","receipt":"a"}
        b={**a,"values":{2024:21,2023:30},"available":"2025-03-01","receipt":"b"}
        self.assertAlmostEqual(combine([a,b],2025)["value"],pstdev([10,20,30]))
        self.assertIsNone(combine([a,{**b,"currency":"USD"}],2025))
        self.assertIsNone(combine([a],2025))
if __name__=="__main__":unittest.main()
