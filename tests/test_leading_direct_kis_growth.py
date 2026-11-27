import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from leading_direct_kis_growth import annual_value,cagr,parse
class DirectGrowth(unittest.TestCase):
    def test_source(self):
        x=parse([{"stac_yymm":"202512","grs":"12.3","bsop_prfi_inrt":"-15","ntin_inrt":"0","roe_val":"4.5","lblt_rate":"120"}],[],2025)
        self.assertEqual(x["sales_growth"],12.3);self.assertEqual(x["op_growth"],-15);self.assertEqual(x["net_growth"],0)
    def test_cagr(self):
        x=[{"stac_yymm":str(y)+"12","sale_account":str(v)} for y,v in zip(range(2022,2026),(100,110,121,133.1))]
        self.assertAlmostEqual(cagr(x,2025),10)
        self.assertIsNone(cagr(x[1:],2025))
    def test_conflict(self):
        self.assertIsNone(annual_value([{"stac_yymm":"202512","grs":"10"},{"stac_yymm":"202512","grs":"20"}],2025,"grs"))
if __name__=="__main__":unittest.main()
