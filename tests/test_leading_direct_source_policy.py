import sys,unittest
from datetime import date
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from leading_direct_source_policy import target_revision
from leading_market_inputs import price_metrics
class DirectSource(unittest.TestCase):
    def test_target_direct(self):
        z={"source":"Naver reports","pairs":[{"broker":str(i),"prior_date":"2026-10-20","current_date":"2026-11-20","prior_target":100,"current_target":110} for i in range(3)]}
        r=target_revision(z,date(2026,11,28))
        self.assertAlmostEqual(r["value"],10);self.assertFalse(r["cross_provider_validation_required"])
        self.assertIsNone(target_revision({**z,"source":"unknown"},date(2026,11,28)))
        self.assertIsNone(target_revision({**z,"pairs":z["pairs"][:2]},date(2026,11,28)))
    def test_price_direct(self):
        from datetime import timedelta
        days=[(date(2026,10,1)+timedelta(days=i)).strftime("%Y%m%d") for i in range(21)]
        rows={d:(100+i,) for i,d in enumerate(days)}
        self.assertEqual(price_metrics(rows,days,999,{}),{})
        self.assertAlmostEqual(price_metrics(rows,days,999,{},direct=True)["momentum_20d"],20)
if __name__=="__main__":unittest.main()
