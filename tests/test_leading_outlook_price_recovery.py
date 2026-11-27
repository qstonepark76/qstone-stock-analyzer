import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from leading_outlook_price_recovery import published_close
class TestPrice(unittest.TestCase):
    def test_exact(self):
        p=[{"localTradedAt":"2026-11-27","closePrice":"100,000"},{"localTradedAt":"2026-11-26","closePrice":"90,000"}]
        self.assertEqual(published_close(p,"2026-11-27","005930"),100000)
        self.assertIsNone(published_close(p,"2026-11-25","005930"))
    def test_conflict(self):
        p=[{"localTradedAt":"2026-11-27","closePrice":"1"},{"localTradedAt":"2026-11-27","closePrice":"2"}]
        self.assertIsNone(published_close(p,"2026-11-27","005930"))
if __name__=="__main__":unittest.main()
