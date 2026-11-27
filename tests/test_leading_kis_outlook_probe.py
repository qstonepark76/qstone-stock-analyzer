import sys,unittest
from pathlib import Path
from datetime import date
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from leading_kis_outlook_probe import opinion_inventory,select_pilot
class Probe(unittest.TestCase):
    def test_dates_and_target(self):
        x={"output":[{"stck_bsop_date":"20261120","mbcr_name":"A","invt_opnn":"매수","hts_goal_prc":"10,000"},{"stck_bsop_date":"20261129","invt_opnn":"매수"},{"stck_bsop_date":"wrong","hts_goal_prc":"100"}]}
        a,b=opinion_inventory(x,date(2026,9,1),date(2026,11,28))
        self.assertEqual(b,2);self.assertEqual(a[0]["target_price_candidate"],10000);self.assertEqual(a[0]["broker"],"A")
    def test_no_broker_inferred(self):
        a,_=opinion_inventory({"output":{"stck_bsop_date":"20261120","invt_opnn":"매수","hts_goal_prc":"0"}},date(2026,9,1),date(2026,11,28))
        self.assertIsNone(a[0]["broker"]);self.assertIsNone(a[0]["target_price_candidate"])
    def test_fixed_pilot(self):
        p={"stocks":[{"ticker":str(i),"excluded":i==0,"metrics":{}} for i in range(60)]}
        u={"stocks":[{"ticker":str(i),"market_cap":60-i} for i in range(60)]}
        ts=select_pilot(p,u);self.assertEqual(len(ts),40);self.assertEqual(len(set(ts)),40);self.assertNotIn("0",ts)
if __name__=="__main__":unittest.main()
