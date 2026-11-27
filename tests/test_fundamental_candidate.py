import unittest
import sys
sys.path.insert(0,"scripts")
from fundamental_candidate import profit_change,transition,derive,slots,WEIGHTS

class FundamentalTest(unittest.TestCase):
    def row(self,field,section,now,prev,old=None,currency="KRW"):
        return {"account_id":field,"sj_div":section,"thstrm_amount":str(now),"frmtrm_amount":str(prev),"bfefrmtrm_amount":str(old) if old is not None else "",
                "currency":currency,"account_detail":"-","bsns_year":"2025","reprt_code":"11011","rcept_no":"20260301000001"}
    def test_loss_safe(self):
        self.assertGreater(profit_change(-10,-20),0)
        self.assertLess(profit_change(-20,-10),0)
        self.assertEqual(profit_change(10,-10),200)
        self.assertEqual(profit_change(-10,10),-200)
        self.assertEqual(transition(1,-1),"loss_to_profit")
        self.assertIsNone(profit_change(None,1))
    def test_weights(self):
        self.assertEqual([sum(v.values()) for v in WEIGHTS.values()],[20,15,15])
    def test_psr_and_cagr(self):
        rows=[self.row("ifrs-full_Revenue","IS",121,110,100),self.row("ifrs-full_ProfitLossAttributableToOwnersOfParent","IS",-10,-20),self.row("ifrs-full_EquityAttributableToOwnersOfParent","BS",100,90)]
        r=derive(rows,2025,"CFS",242)
        self.assertAlmostEqual(r["sales_cagr"]["value"],10)
        self.assertEqual(r["psr"]["value"],2)
        self.assertNotIn("per",r)
        self.assertEqual(slots(r,None)["valuation"]["earnings_value"],"psr")
    def test_financial_no_debt_proxy(self):
        rows=[self.row("ifrs-full_Liabilities","BS",100,90),self.row("ifrs-full_Equity","BS",20,20)]
        self.assertNotIn("debt_equity",derive(rows,2025,"CFS",50,"bank_group"))
    def test_mixed_receipts(self):
        rows=[self.row("ifrs-full_Revenue","IS",100,80),dict(self.row("ifrs-full_Assets","BS",100,80),rcept_no="other")]
        self.assertEqual(derive(rows,2025,"CFS",50),{})
    def test_negative_book(self):
        rows=[self.row("ifrs-full_EquityAttributableToOwnersOfParent","BS",-1,-2)]
        self.assertNotIn("pbr",derive(rows,2025,"CFS",50))
if __name__=="__main__":unittest.main()
