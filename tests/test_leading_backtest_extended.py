import sys,unittest
from pathlib import Path
from datetime import date
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from leading_backtest_extended import rank,extended,FINAL_VERSION
from leading_historical_readiness import anchors,universe
class Historical(unittest.TestCase):
    def test_anchors(self):
        a=anchors(date(2026,11,27),5)
        self.assertEqual(len(a),60);self.assertEqual(a[0],date(2021,12,31));self.assertEqual(a[-1],date(2026,11,27))
    def test_no_future_or_partial(self):
        s={"asof":"2025-01-02","model_version":FINAL_VERSION,"point_in_time_verified":True,"historical_universe_verified":True,"historical_source_manifest":"fixture","records":[{"ticker":str(i),"base":{"complete":i<10,"score":90-i},"leading":{"complete":i<10,"score":80+i}} for i in range(300)]}
        self.assertEqual(len(rank(s)["combined_60_40_top10"]),10);self.assertEqual(rank(s)["combined_60_40_top15"],[])
        self.assertIsNone(rank({**s,"point_in_time_verified":False}))
    def test_dates(self):
        self.assertEqual(universe([{"BAS_DD":"20250103","ISU_CD":"005930","ISU_NM":"Samsung","MKTCAP":"1000","TDD_CLSPRC":"100"}],date(2025,1,2)),[])
    def test_empty(self):
        panel={"sessions":[],"prices":{},"benchmark":{},"verified":True,"basis":"corporate_action_adjusted_ohlc"}
        self.assertEqual(extended([],panel,"2026-11-27",5)["holdout"]["status"],"no_verified_mature_cohorts")
if __name__=="__main__":unittest.main()
