"""Retrieve 2024 annual revenue comparison for candidate CAGR; no imputation."""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,"scripts")
from collect import DART_KEY,dart_company_financial
from fundamental_candidate import select,number
from metric_quality import source_check,account_check
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def main():
    if not DART_KEY:raise SystemExit("DART credential unavailable")
    audit=read("replay-source/report.json")
    year=audit["year"]
    out=Path("audit-cagr");out.mkdir(exist_ok=True)
    results={}
    for s in audit["records"]:
        if s["status"]!="source_received" or not s.get("corp_code"):continue
        t=s["ticker"]
        try:
            raw=read("replay-source/source-rows/"+t+".json")
            if not source_check(raw,year,s.get("scope")) or sorted({str(x["rcept_no"]) for x in raw if x.get("rcept_no")})!=s.get("receipts"):continue
            curr=select(raw,"sales")
            if not account_check([curr]):continue
            past,scope,_=dart_company_financial(s["corp_code"],year-1)
            if scope!=s.get("scope") or not source_check(past,year-1,scope):continue
            old=select(past,"sales")
            if not account_check([curr,old]):continue
            a,b,c,d=[number(r,k) for r,k in [(curr,"thstrm_amount"),(curr,"frmtrm_amount"),(old,"thstrm_amount"),(old,"frmtrm_amount")]]
            # Reject restatement mismatch and non-positive endpoints.
            if None in (a,b,c,d) or min(a,b,c,d)<=0 or abs(b-c)>max(1,abs(b)*1e-9):continue
            results[t]={"value":100*((a/d)**.5-1),"basis":"three_annual_observations_two_intervals","scope":scope,"year":year,"receipt":curr["rcept_no"],"prior_receipt":old["rcept_no"],"account_ids":[curr["account_id"],old["account_id"]],"lower_better":False}
        except Exception as e:
            print("CAGR SOURCE ISSUE",t,type(e).__name__,flush=True)
        time.sleep(.25)
    (out/"records.json").write_text(json.dumps(results,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    print("CAGR SOURCE SUMMARY",json.dumps({"universe":300,"matched":len(results)}),flush=True)
if __name__=="__main__":main()
