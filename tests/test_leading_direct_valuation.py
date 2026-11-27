import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from leading_direct_valuation import parse_ratio,parse_naver,compare
class Direct(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_ratio("1,234.5배"),1234.5)
        self.assertEqual(parse_ratio("-3.2배"),-3.2)
        self.assertIsNone(parse_ratio("N/A"))
    def test_preserve(self):
        r,_=parse_naver({"totalInfos":[{"code":"per","value":"12.34배"},{"code":"pbr","value":"1.20배"},{"code":"expectedPer","value":"5배"}]},"005930")
        self.assertEqual(r["per"]["value"],12.34);self.assertEqual(len(r),2)
    def test_code(self):
        self.assertEqual(parse_naver({"itemCode":"000660","totalInfos":[]},"005930")[1],"ticker_mismatch")
    def test_no_negative_cheap(self):
        rows=[{"ticker":str(i),"industry_code":"A","peer_only":False,"ratios":{"per":{"value":v,"basis_key":"Naver per"}}} for i,v in enumerate([-2,5,6,7,8,9])]
        c=compare(rows);self.assertEqual(c["per_scored"],5);self.assertIsNone(rows[0]["valuation"]["per"]["points"])
if __name__=="__main__":unittest.main()
