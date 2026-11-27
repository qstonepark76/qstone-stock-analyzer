"""Recover the approved three-year operating-margin stability metric.
Reuse archived annual statements first; fetch only missing target/peer history.
No cross-provider value verification, no production or frozen artifact changes.
"""
import json,time
from datetime import date
from pathlib import Path
from collections import Counter,defaultdict
from statistics import pstdev
import requests
from final_leading_model import evaluate,finite
from leading_fundamental_inputs import receipt_day,summary
from leading_reuse_stage1 import obs
from leading_stage7_gaps import factor_gaps
from leading_true_cagr import fetch
from collect import DART_KEY
from fundamental_candidate import select,number
from metric_quality import source_check,account_check
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
def annual_margins(raw,year,scope,cutoff):
    if not source_check(raw,year,scope):return None
    sales,op=select(raw,"sales"),select(raw,"op")
    if not account_check([sales,op]):return None
    receipt=str(sales.get("rcept_no"));d=receipt_day(receipt)
    if not d or not date(year,12,31)<=d<=cutoff:return None
    values={}
    for i,k in enumerate(("thstrm_amount","frmtrm_amount","bfefrmtrm_amount")):
        a,b=number(sales,k),number(op,k)
        if finite(a) and finite(b) and a>0:values[year-i]=100*b/a
    return {"values":values,"receipt":receipt,"available":d.isoformat(),"currency":sales["currency"],"accounts":[x["account_id"].replace("ifrs-full_","").replace("ifrs_","") for x in (sales,op)]}
def combine(parts,year):
    if not parts or len({(x["currency"],tuple(x["accounts"])) for x in parts})!=1:return None
    values={};refs=set()
    for p in sorted(parts,key=lambda x:x["available"],reverse=True):
        for y,v in p["values"].items():
            if year-2<=y<=year and y not in values:values[y]=v;refs.add(p["receipt"])
    if set(values)!=set(range(year-2,year+1)):return None
    return {"value":pstdev(list(values.values())),"annual_margins":values,"receipts":sorted(refs)}
def main():
    out=Path("audit-leading-industry-margin");out.mkdir(exist_ok=True)
    p=read("cagr/observations.json");a=read("replay-source/report.json");year=int(a["year"]);cutoff=date.fromisoformat(p["asof"])
    before=evaluate(p);target_meta={r["ticker"]:r for r in a["records"]}
    peer_dir=Path("reuse-peers/audit-wider-peers");peer_meta={r["ticker"]:r for r in read(peer_dir/"peers.json")}
    targets=[r for r in p["stocks"] if not r.get("excluded") and r.get("financial_model") in (None,"operating_holding")]
    peers=[r for r in p["comparison_peers"] if r.get("financial_model") in (None,"operating_holding")]
    counts=Counter();errors=Counter();records=[];session=requests.Session();stopped=False
    def group(row,scope):
        code=str(row.get("industry_code") or "")
        return (row.get("financial_model"),scope,code[:2]) if code.isdigit() and len(code)>=2 else None
    def recover(row,online=False):
        nonlocal stopped
        t=row["ticker"];peer=row.get("peer_only",False);meta=(peer_meta if peer else target_meta).get(t,{})
        scope="CFS" if peer else meta.get("scope")
        if scope not in ("CFS","OFS"):return False
        m=row["metrics"].get("margin_stability")
        # Existing valid three-year metric with same approved statistic: align
        # basis and identifier so all like-for-like observations can compare.
        if isinstance(m,dict) and finite(m.get("value")) and "3 annual operating-margin standard deviation pp" in str(m.get("basis")):
            m["basis"]=f"{year}|{scope}|three_year_op_margin_std_pp";m["metric_id"]="margin_stability";counts["existing_aligned"]+=1
            return True
        path=(peer_dir/"source-rows" if peer else Path("replay-source/source-rows"))/(t+".json")
        if not path.exists():return False
        raw=read(path);current=annual_margins(raw,year,scope,cutoff)
        if not current or [current["receipt"]]!=meta.get("receipts"):return False
        parts=[current]
        old=Path("prior/recovered-prior")/(t+".json")
        if old.exists():
            x=annual_margins(read(old),year-1,scope,cutoff)
            if x:parts.append(x);counts["archive_prior_used"]+=1
        z=combine(parts,year)
        if not z and online and not stopped and DART_KEY and meta.get("corp_code") and counts["requests"]<160:
            try:
                rows,err=fetch(session,meta["corp_code"],year-1,scope);counts["requests"]+=1
                if err:errors["DART_"+err]+=1;stopped=err=="stop"
                if rows:
                    x=annual_margins(rows,year-1,scope,cutoff)
                    if x:parts.append(x)
                z=combine(parts,year)
            except (requests.RequestException,ValueError,TypeError) as e:errors[type(e).__name__]+=1
            finally:time.sleep(.3)
        if not z:return False
        available=max(receipt_day(x) for x in z["receipts"]).isoformat()
        row["metrics"]["margin_stability"]=obs(z["value"],f"{year}|{scope}|three_year_op_margin_std_pp",f"{year}-12-31",available,"OpenDART receipts "+" ".join(z["receipts"]),True,"margin_stability")
        records.append({"ticker":t,"peer_only":peer,"scope":scope,**z})
        counts["peer_recovered" if peer else "target_recovered"]+=1
        return True
    # First normalize and recover from all existing archives, no API calls.
    for r in targets+peers:recover(r)
    for r in targets:
        if "margin_stability" not in r["metrics"]:recover(r,True)
    # Fetch only where additional same-parent peers could reach minimum five.
    pool=Counter();needed=set()
    for r in targets+peers:
        scope="CFS" if r.get("peer_only") else target_meta.get(r["ticker"],{}).get("scope")
        g=group(r,scope)
        if g and "margin_stability" in r["metrics"]:pool[g]+=1
        if g and not r.get("peer_only") and "margin_stability" in r["metrics"]:needed.add(g)
    for r in peers:
        g=group(r,"CFS")
        if g in needed and pool[g]<5 and "margin_stability" not in r["metrics"]:
            if recover(r,True):pool[g]+=1
    result=evaluate(p);result["point_in_time_verified"]=False
    bf=factor_gaps(before);af=factor_gaps(result);bs=summary(before);as_=summary(result)
    report={"before_industry_pct":bf["base"]["industry_relative"]["coverage_pct"],"after_industry_pct":af["base"]["industry_relative"]["coverage_pct"],"before_margin_scored":bs["base_slot_counts"].get("margin_stability",0),"after_margin_scored":as_["base_slot_counts"].get("margin_stability",0),"before_base":bs["base_weighted_coverage_pct"],"after_base":as_["base_weighted_coverage_pct"],"counts":dict(counts),"errors":dict(errors),"remaining_industry_gaps":af["base"]["industry_relative"]["missing"],"official_integrated":False,"note":"Latest filing comparative data preferred, same account and currency; no cross-provider verification. Candidate replay only. No widening beyond approved KSIC two-digit parent. Maximum 160 targeted prior-year requests."}
    write(out/"summary.json",report);write(out/"records.json",records);write(out/"observations.json",p);write(out/"final-leading.json",result)
    print("INDUSTRY MARGIN RECOVERY",json.dumps(report,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
