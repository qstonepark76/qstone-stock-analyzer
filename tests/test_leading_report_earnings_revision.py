import sys,unittest
from pathlib import Path
from datetime import date
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from leading_report_earnings_revision import explicit,amount_table,score,change,same_report
class Revision(unittest.TestCase):
    def test_same_report(self):
        r={"research_id":"1","ticker":"005930","broker":"A증권","published_at":"2026-11-27"}
        d={"nid":"1","itemCode":"005930","brokerName":"A증권","writeDate":"2026-11-27"}
        self.assertTrue(same_report(d,r));self.assertFalse(same_report({**d,"itemCode":"000660"},r))
    def test_explicit(self):
        self.assertEqual(explicit("2026년 지배주주순이익 추정치를 10% 상향",2026,1)[0]["value"],10)
        self.assertEqual(explicit("2026년 영업이익 추정치를 10% 상향",2026,1),[])
        self.assertEqual(explicit("2026년 순이익은 전년대비 10% 증가",2026,1),[])
    def test_amount(self):
        t=[["구분","2025","2026E"],["지배주주순이익","100","120"]]
        r=amount_table(t,"단위: 억원 IFRS 연결",2026,1)
        self.assertEqual(r[0]["amount"],120)
        self.assertEqual(amount_table(t,"단위: 억원",2026,1),[])
    def test_score(self):
        a={**explicit("2026년 당기순이익 추정치를 10% 상향",2026,1)[0],"broker":"A","published_at":"2026-11-27"}
        b={**a,"value":-10}
        self.assertGreater(score([a],date(2026,11,28))["points_out_of_2"],1)
        self.assertLess(score([b],date(2026,11,28))["points_out_of_2"],1)
    def test_pair(self):
        a={"metric":"owner_net_income","period_end":"2026-12-31","kind":"annual_forecast_amount","amount":120,"unit":"억원","scope":"연결","broker":"A","published_at":"2026-11-27"}
        b={**a,"amount":100,"published_at":"2026-10-20"}
        self.assertAlmostEqual(score([a,b],date(2026,11,28))["value"],20)
        self.assertIsNone(score([a,{**b,"scope":"별도"}],date(2026,11,28)))
        self.assertGreater(change(-100,-50),0)
if __name__=="__main__":unittest.main()
