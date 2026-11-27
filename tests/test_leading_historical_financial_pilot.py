import unittest,sys
from datetime import date
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from leading_historical_financial_pilot import accepted
class HistoricalFinancial(unittest.TestCase):
    def test_receipt_cutoff(self):
        row={"rcept_no":"20230331000001","bsns_year":"2022","reprt_code":"11011","fs_div":"CFS"}
        self.assertEqual(accepted([row],2022,"CFS",date(2023,11,30)),row["rcept_no"])
        self.assertIsNone(accepted([{**row,"rcept_no":"20240101000001"}],2022,"CFS",date(2023,11,30)))
        self.assertIsNone(accepted([row],2022,"OFS",date(2023,11,30)))
if __name__=="__main__":unittest.main()
