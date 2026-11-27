import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from leading_naver_growth import parse
class Growth(unittest.TestCase):
    def test_actual_only(self):
        raw={"financeInfo":{"trTitleList":[{"key":f"{y}12","isConsensus":"N","title":str(y)} for y in range(2022,2026)],"rowList":[{"title":"매출액","columns":{f"{y}12":{"value":str(100*1.1**(y-2022))} for y in range(2022,2026)}},{"title":"영업이익","columns":{"202412":{"value":"-100"},"202512":{"value":"-50"}}}]}}
        r,_=parse(raw,2025);self.assertAlmostEqual(r["sales_growth"],10);self.assertAlmostEqual(r["sales_cagr"],10);self.assertGreater(r["op_growth"],0)
        raw["financeInfo"]["trTitleList"][-1]["isConsensus"]="Y";self.assertEqual(parse(raw,2025)[0],{})
    def test_null_finance(self):
        self.assertEqual(parse({"financeInfo":None},2025),({},{}))
    def test_missing_cagr(self):
        raw={"financeInfo":{"trTitleList":[{"key":f"{y}12","isConsensus":"N"} for y in range(2023,2026)],"rowList":[{"title":"매출액","columns":{"202312":"100","202412":"110","202512":"121"}}]}}
        r,_=parse(raw,2025);self.assertNotIn("sales_cagr",r);self.assertAlmostEqual(r["sales_growth"],10)
if __name__=="__main__":unittest.main()
