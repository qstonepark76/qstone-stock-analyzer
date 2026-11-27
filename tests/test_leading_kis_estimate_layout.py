import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from leading_kis_estimate_layout import layout,growth_checks,unique_scale
def fixture():
    return {"output4":[{"dt":s} for s in ("2023.12","2024.12","2025.12","2026.12E","2027.12E")],
            "output2":[{f"data{i}":str(i*100 if j%2==0 else (100/(i-1)*10 if i>1 else 0)) for i in range(1,6)} for j in range(6)]}
class Layout(unittest.TestCase):
    def test_columns(self):
        a=layout(fixture(),2025);self.assertEqual(a["op"]["levels"],[100,200,300,400,500]);self.assertTrue(all(x["tenths_pct_match"] for x in growth_checks(a)))
    def test_wrong_period(self):
        x=fixture();x["output4"][3]["dt"]="2026.12";self.assertIsNone(layout(x,2025))
    def test_missing_column(self):
        x=fixture();del x["output2"][0]["data1"];self.assertIsNone(layout(x,2025))
    def test_units(self):
        self.assertEqual(unique_scale(100,10000000000),100000000);self.assertIsNone(unique_scale(0,0))
if __name__=="__main__":unittest.main()
