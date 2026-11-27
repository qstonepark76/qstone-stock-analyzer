"""Replace the legacy two-interval sales CAGR with true three-year growth.
Reuse archived filings before requesting missing historical annual statements.
No cross-source verification, no historical production mutation.
"""
import json,time
from pathlib import Path
from datetime import date
from collections import Counter
import requests
from collect import DART_KEY
from fundamental_candidate import select,number
from metric_quality import source_check,account_check
from leading_fundamental_inputs import receipt_day,summary
from leading_reuse_stage1 import obs
from final_leading_model import evaluate,finite
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
def annual_sales(rows,year,scope,cutoff):
    if not source_check(rows,year,scope):return None
    a=select(rows,"sales")
    if not account_check([a]):return None
    r=str(a.get("rcept_no") or "");d=receipt_day(r)
    if not d or not date(year,12,31)<=d<=cutoff:return None
    vals={year-i:number(a,k) for i,k in enumerate(("thstrm_amount","frmtrm_amount","bfefrmtrm_amount"))}
    return {"values":{y:v for y,v in vals.items() if finite(v) and v>0},"receipt":r,"available":d.isoformat(),"currency":a["currency"],"account":a["account_id"]}
def combine(parts,year):
    if not parts:return None
    if len({str(p["currency"]).upper() for p in parts})!=1:return None
    # Same standard revenue account; take the latest filing's published comparative values.
    if len({p["account"].replace("ifrs-full_","").replace("ifrs_","") for p in parts})!=1:return None
    vals={};refs=set()
    for p in sorted(parts,key=lambda x:x["available"],reverse=True):
        for y,v in p["values"].items():
            if year-3<=y<=year and y not in vals:vals[y]=v;refs.add(p["receipt"])
    if set(vals)!=set(range(year-3,year+1)):return None
    return {"value":100*((vals[year]/vals[year-3])**(1/3)-1),"sales":vals,"receipts":sorted(refs)}
def fetch(session,corp,year,scope):
    r=session.get("https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json",params={"crtfc_key":DART_KEY,"corp_code":corp,"bsns_year":year,"reprt_code":"11011","fs_div":scope},timeout=(5,20))
    if r.status_code in (401,403,429):return None,"stop"
    r.raise_for_status();j=r.json()
    if str(j.get("status")) in ("020","010","011","012"):return None,"stop"
    if str(j.get("status"))!="000":return None,str(j.get("status"))
    return j.get("list"),None
def main():
    out=Path("audit-leading-true-cagr");out.mkdir(exist_ok=True)
    payload=read("simplified/observations.json");audit=read("replay-source/report.json");year=int(audit["year"]);cutoff=date.fromisoformat(payload["asof"])
    before=summary(evaluate(payload));meta={r["ticker"]:r for r in audit["records"]}
    counts=Counter();errors=Counter();records=[];session=requests.Session();stopped=False
    for i,row in enumerate(payload["stocks"],1):
        if row.get("excluded"):continue
        t=row["ticker"];m=meta[t];scope=m.get("scope");parts=[]
        old=row["metrics"].pop("sales_cagr",None);counts["legacy_removed"]+=bool(old)
        if not m.get("corp_code") or scope not in ("CFS","OFS"):errors["missing_issuer_scope"]+=1;continue
        paths=[(year,Path("replay-source/source-rows")/(t+".json")),(year-1,Path("prior/recovered-prior")/(t+".json"))]
        for y,p in paths:
            if p.exists():
                a=annual_sales(read(p),y,scope,cutoff)
                if a:parts.append(a);counts["archive_used"]+=1
        z=combine(parts,year)
        if z is None and DART_KEY and not stopped:
            for y in (year-1,year-2):
                if any(y in p["values"] and year-3 in p["values"] for p in parts):continue
                try:
                    raw,err=fetch(session,m["corp_code"],y,scope);counts["requests"]+=1
                    if err:errors["DART_"+err]+=1;stopped=err=="stop"
                    if raw:
                        a=annual_sales(raw,y,scope,cutoff)
                        if a:parts.append(a)
                    z=combine(parts,year)
                    if z or stopped:break
                except (requests.RequestException,ValueError,TypeError) as e:errors[type(e).__name__]+=1
                finally:time.sleep(.3)
        if z:
            available=max(receipt_day(r) for r in z["receipts"]).isoformat()
            row["metrics"]["sales_cagr"]=obs(z["value"],f"{year}|{scope}|true_three_year_sales_cagr",f"{year}-12-31",available,"OpenDART receipts "+" ".join(z["receipts"]),metric_id="sales_cagr")
            counts["true_cagr"]+=1
            records.append({"ticker":t,"scope":scope,**z})
        else:errors["four_actual_years_missing"]+=1
        if i%50==0:print("TRUE CAGR PROGRESS",i,"/",len(payload["stocks"]),flush=True)
    result=evaluate(payload);result["point_in_time_verified"]=False
    after=summary(result);s={"before_growth":before["base_slot_counts"],"after_growth":after["base_slot_counts"],"before_base":before["base_weighted_coverage_pct"],"after_base":after["base_weighted_coverage_pct"],"counts":dict(counts),"errors":dict(errors),"true_cagr_scored":after["base_slot_counts"].get("sales_cagr",0),"status":"candidate_only","note":"Removed legacy two-interval CAGR instead of treating it as true 3-year. Latest filing comparative values accepted without cross-source matching. Frozen historical source-date replay only; new acquisition not proof of prior availability."}
    write(out/"summary.json",s);write(out/"records.json",records);write(out/"observations.json",payload);write(out/"final-leading.json",result)
    print("TRUE CAGR SUMMARY",json.dumps(s,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
