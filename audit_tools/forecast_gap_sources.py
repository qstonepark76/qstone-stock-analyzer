"""Collect targeted historical and listing evidence for still-unavailable forecast slots.
Use the existing gap list, no whole-universe redundant queries. Metadata from
prospectus/prelisting reports remains evidence candidates until period and scope
can be reconciled. No invented annual baseline from quarterly estimates.
"""
import sys,json,time
from pathlib import Path
from datetime import date
from collections import defaultdict
import requests
sys.path.insert(0,"scripts");sys.path.insert(0,"audit_tools")
from own_forecast import fetch,read,DART_KEY
from fundamental_candidate import IDS,number
from forecast_extended_models import canonical,pick_exact
def main():
    if not DART_KEY:raise SystemExit("DART credential unavailable")
    u=read("replay-source/universe.json");asof=date.fromisoformat(u["asof"])
    gaps={r["ticker"]:r for r in read("source-gaps/report.json")["records"]}
    sources={r["ticker"]:r for r in read("replay-source/report.json")["records"]}
    missing=defaultdict(set)
    for r in read("reuse/missing.json"):missing[r["ticker"]].add(r["metric"])
    records=[]
    for t,metrics in sorted(missing.items()):
        s=sources[t];g=gaps.get(t,{})
        corp=s.get("corp_code") or g.get("corp_code")
        row={"ticker":t,"corp_code":corp,"metrics":sorted(metrics),"source_status":s["status"],"filings":[],"annual_candidates":[],"quarter_candidates":[]}
        if not corp:
            row["status"]="issuer_identity_unresolved";records.append(row);continue
        # Full quarterly and 5-year annual collection is reserved for gaps
        # with no complete saved source, not for 300 issuers already covered.
        scope=s.get("scope")
        scopes=[scope] if scope in ("CFS","OFS") else ["CFS","OFS"]
        try:
            for typ in ("A","C","D"):
                p=requests.get("https://opendart.fss.or.kr/api/list.json",params={"crtfc_key":DART_KEY,"corp_code":corp,"bgn_de":str(asof.year-5)+"0101","end_de":asof.strftime("%Y%m%d"),"pblntf_ty":typ,"page_count":100},timeout=(5,15),allow_redirects=False)
                p.raise_for_status();data=p.json()
                if data.get("status") in ("010","011","012","020"):raise SystemExit("DART access or quota unavailable")
                for f in data.get("list",[]):
                    title=str(f.get("report_nm") or "")
                    if any(k in title for k in ("사업보고서","반기보고서","분기보고서","감사보고서","증권신고서","투자설명서","분할")):
                        row["filings"].append({k:f.get(k) for k in ("rcept_no","rcept_dt","report_nm","corp_code","stock_code")})
                if int(data.get("total_page") or 0)>1:row.setdefault("metadata_page_limit",[]).append(typ)
                time.sleep(.25)
            # For missing original annual source/new listings, try exact actual
            # financial statements; other gaps receive filing candidates only
            # because the targeted vintage batch already queries their actuals.
            if s["status"]!="source_received" and g.get("category")!="known_preferred_share":
                for sc in scopes:
                    for y in range(asof.year-5,asof.year):
                        raw=fetch(corp,y,"11011",sc,asof)
                        if raw:row["annual_candidates"].append({"year":y,"scope":sc,"receipt":raw[0]["rcept_no"],"rows":raw})
                    for y in range(asof.year-3,asof.year+1):
                        for code in ("11013","11012","11014"):
                            raw=fetch(corp,y,code,sc,asof)
                            if raw:row["quarter_candidates"].append({"year":y,"code":code,"scope":sc,"receipt":raw[0]["rcept_no"],"rows":raw})
            row["status"]="candidate_sources_collected"
        except (requests.RequestException,ValueError,TypeError,KeyError) as e:
            row["status"]=type(e).__name__
        records.append(row)
        print("FORECAST GAP",t,len(row["filings"]),len(row["annual_candidates"]),len(row["quarter_candidates"]),row["status"],flush=True)
    out=Path("audit-forecast-gap-sources");out.mkdir(exist_ok=True)
    summary={"target_issuers":len(records),"filing_candidates":sum(len(r["filings"]) for r in records),"annual_statements":sum(len(r["annual_candidates"]) for r in records),"quarter_statements":sum(len(r["quarter_candidates"]) for r in records),"admitted_new_forecasts":0,"warning":"Listing prospectus and audit-report metadata only; actual new statements are candidate evidence. Verify identical issuer, fiscal year and accounting definition before scoring."}
    for n,v in (("records.json",records),("summary.json",summary)):
        (out/n).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False))
    print("FORECAST GAP SOURCE SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
