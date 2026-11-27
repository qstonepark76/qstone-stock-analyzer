import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from leading_direct_financial import parse
class Direct(unittest.TestCase):
    def test_actual(self):
        raw={"financeInfo":{"trTitleList":[{"key":"202512","isConsensus":"N","title":"2025.12."}],"rowList":[{"title":"ROE(%)","columns":{"202512":{"value":"-2.5"}}},{"title":"부채비율","columns":{"202512":{"value":"123.4"}}}]}}
        x,_,_=parse(raw,2025);self.assertEqual(x["roe"]["value"],-2.5);self.assertEqual(x["stability"]["value"],123.4)
        raw["financeInfo"]["trTitleList"][0]["isConsensus"]="Y";self.assertEqual(parse(raw,2025)[0],{})
    def test_no_missing_zero(self):
        self.assertEqual(parse({},2025)[0],{})
if __name__=="__main__":unittest.main()
