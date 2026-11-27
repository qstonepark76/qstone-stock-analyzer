import sys,unittest
from pathlib import Path
from datetime import date
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from leading_naver_outlook_replay import close_map,select_slots
class Replay(unittest.TestCase):
    def test_ticker(self):
        self.assertEqual(close_map([{"ISU_CD":"KR7005930003","TDD_CLSPRC":"100,000"},{"ISU_CD":"000660","TDD_CLSPRC":"200000"}]),{"005930":100000,"000660":200000})
    def test_naver_priority(self):
        a={"report_date":"2026-11-20","broker":"A","opinion":"매수","target_price_candidate":120}
        b={**a,"target_price_candidate":140}
        r=select_slots([a],[b],date(2026,11,28),100)
        self.assertAlmostEqual(r["upside"]["value"],20);self.assertEqual(r["upside"]["source"],"Naver broker reports")
    def test_fallback(self):
        b={"report_date":"2026-11-20","broker":"A","opinion":"매수","target_price_candidate":140}
        self.assertEqual(select_slots([], [b],date(2026,11,28),100)["upside"]["source"],"KIS invest-opinion")
if __name__=="__main__":unittest.main()
