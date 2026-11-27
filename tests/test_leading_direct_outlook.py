import sys,unittest
from pathlib import Path
from datetime import date
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from leading_direct_outlook import broker_metrics,naver_forecast,profit_growth
class Direct(unittest.TestCase):
    def test_single_broker(self):
        rows=[{"report_date":"2026-11-20","broker":"A","opinion":"매수","target_price_candidate":120},{"report_date":"2026-10-20","broker":"A","opinion":"매수","target_price_candidate":100}]
        r=broker_metrics(rows,date(2026,11,28),100)
        self.assertAlmostEqual(r["upside"]["value"],20);self.assertAlmostEqual(r["target_revision"]["value"],20)
    def test_no_backfill(self):
        self.assertEqual(broker_metrics([{"report_date":"2026-11-29","broker":"A","opinion":"매수","target_price_candidate":120}],date(2026,11,28),100),{})
    def test_growth(self):
        self.assertGreater(profit_growth(-100,-50),0);self.assertLess(profit_growth(100,-50),0)
    def test_forecast(self):
        f={"financeInfo":{"trTitleList":[{"key":"202512","isConsensus":"N"},{"key":"202612","isConsensus":"Y"}],"rowList":[{"title":"영업이익","columns":{"202512":{"value":"100"},"202612":{"value":"150"}}}]}}
        self.assertEqual(naver_forecast(f,2026)["value"],50)
if __name__=="__main__":unittest.main()
