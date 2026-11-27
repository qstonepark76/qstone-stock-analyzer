import sys,unittest
from datetime import date
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from leading_forecast_vintages import matched,signals,valid
ASOF=date(2026,11,24)
def row(b,d,v,**kw):
    return dict({"ticker":"A","broker":b,"published_at":d,"available_on":d,"period_end":"2026-12-31","basis_id":"CFS|annual|KRW","metric":"operating_profit","unit":"KRW","value":v,"source_ref":"synthetic fixture","verified":True,"basis_verified":True,"source_kind":"broker_forecast","forward_looking":True},**kw)
def data():
    return [row(b,d,v) for b in ("1","2","3") for d,v in (("2026-10-20",-100),("2026-11-20",-50))]
def pairs(rows):
    return matched(rows,ASOF,"A","operating_profit","2026-12-31","CFS|annual|KRW")
class Vintage(unittest.TestCase):
    def test_loss_improvement(self):
        s=signals(pairs(data()),"operating_profit")
        self.assertAlmostEqual(s["op_revision_30d"],200/3)
        self.assertEqual(s["upward_broker_share"],100)
    def test_late_verified(self):
        rs=data();rs[1]["available_on"]="2026-11-25"
        self.assertEqual(signals(pairs(rs),"operating_profit"),{})
    def test_wrong_basis(self):
        rs=data();rs[1]["basis_id"]="OFS"
        self.assertEqual(signals(pairs(rs),"operating_profit"),{})
    def test_own_forecast_not_broker(self):
        rs=data();rs[1]["source_kind"]="qstone_model_forecast"
        self.assertEqual(signals(pairs(rs),"operating_profit"),{})
    def test_conflict(self):
        rs=data()+[row("1","2026-11-20",100)]
        self.assertEqual(signals(pairs(rs),"operating_profit"),{})
    def test_no_update(self):
        rs=[r for r in data() if r["published_at"]=="2026-10-20"]
        self.assertEqual(pairs(rs),[])
if __name__=="__main__":unittest.main()
