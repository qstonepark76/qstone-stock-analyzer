import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from leading_direct_valuation_hierarchy import evaluate_rows
def row(i,code,v=10,model=None,basis="same",day="2026-11-28"):
    return {"ticker":str(i),"industry_code":code,"financial_model":model,"peer_only":False,"ratios":{"per":{"value":v,"source":"Naver","basis_key":basis,"observed_at":day+"T02:00:00+09:00"}}}
class Hierarchy(unittest.TestCase):
    def test_parent(self):
        c,r=evaluate_rows([row(i,"26"+str(i),i+1) for i in range(5)])
        self.assertEqual(c["per_parent"],5);self.assertEqual(r[0]["valuation"]["per"]["peer_level"],"parent")
    def test_no_mixed_basis_date(self):
        c,_=evaluate_rows([row(i,"261",i+1,basis=str(i)) for i in range(5)])
        self.assertEqual(c.get("per_scored",0),0)
        c,_=evaluate_rows([row(i,"261",i+1,day="2026-11-"+str(20+i)) for i in range(5)])
        self.assertEqual(c.get("per_scored",0),0)
    def test_finance_separate(self):
        c,_=evaluate_rows([row(i,"64"+str(i),i+1,model="bank_group") for i in range(5)]+[row(6,"641",1)])
        self.assertEqual(c["per_financial_model"],5)
    def test_negative(self):
        c,r=evaluate_rows([row(i,"261",i+1) for i in range(5)]+[row(6,"261",-1)])
        self.assertEqual(c["per_scored"],5);self.assertIsNone(r[-1]["valuation"]["per"]["points"])
if __name__=="__main__":unittest.main()
