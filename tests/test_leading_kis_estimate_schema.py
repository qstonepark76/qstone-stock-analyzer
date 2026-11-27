import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from leading_kis_estimate_schema import period,reconcile
class Schema(unittest.TestCase):
    def test_period(self):
        self.assertEqual(period("2026/12(E)"),{"year":2026,"month":12,"kind":"forecast"})
        self.assertEqual(period("2025.12")["kind"],"unspecified")
        self.assertIsNone(period("2026"))
    def test_scale(self):
        self.assertEqual(reconcile(100,10000000000),[100000000])
        self.assertEqual(reconcile(0,0),[])
        self.assertEqual(reconcile(-100,10000000000),[])
if __name__=="__main__":unittest.main()
