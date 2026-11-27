"""Diagnose actual top-300 collection gaps, without changing its denominator.

Read original artifacts and retry only missing annual statements. Determine
whether a periodic filing exists; do not substitute a different fiscal year.
"""
import json
import re
import sys
from pathlib import Path
import requests
sys.path.insert(0,"scripts")
from collect import download_corp_map, dart_company_financial, DART_KEY, PREFERRED_SHARE_PARENT
SOURCE=Path("replay-source")
OUT=Path("audit-source-gaps")

def main():
    OUT.mkdir(exist_ok=True)
    report=json.loads((SOURCE/"report.json").read_text(encoding="utf-8"))
    if report.get("sample_count")!=300 or not DART_KEY:
        raise ValueError("Missing source or credential")
    mapping=download_corp_map()
    year=report["year"]
    results=[]
    for r in report["records"]:
        if r["status"]=="source_received":
            continue
        ticker=r["ticker"]
        parent=PREFERRED_SHARE_PARENT.get(ticker)
        item={"ticker":ticker,"name":r["name"],"original_status":r["status"]}
        if parent and parent in mapping:
            item.update(category="known_preferred_share",parent=parent,parent_corp=mapping[parent])
        elif ticker not in mapping:
            item.update(category="unmapped_security_pending_identity")
        else:
            corp=mapping[ticker]
            item["corp_code"]=corp
            try:
                rows,scope,message=dart_company_financial(corp,year)
                if rows:
                    item.update(category="retry_received",scope=scope,row_count=len(rows))
                    (OUT/(ticker+".json")).write_text(json.dumps(rows,ensure_ascii=False),encoding="utf-8")
                else:
                    item.update(category="annual_statement_unavailable",api_status=str(message).split(":")[0])
                res=requests.get("https://opendart.fss.or.kr/api/list.json",params={
                    "crtfc_key":DART_KEY,"corp_code":corp,"bgn_de":str(year+1)+"0101",
                    "end_de":str(year+1)+"1125","pblntf_ty":"A","page_count":100},
                    timeout=(5,15),allow_redirects=False)
                if res.status_code==200:
                    payload=res.json()
                    item["filing_search_status"]=payload.get("status")
                    item["filings"]=[{k:f.get(k) for k in ("report_nm","rcept_no","rcept_dt")} for f in payload.get("list",[]) if isinstance(f,dict)]
                else:
                    item["filing_search_status"]="http_"+str(res.status_code)
            except Exception as exc:
                item.update(retry_error=type(exc).__name__)
        results.append(item)
        print("SOURCE GAP EVIDENCE",json.dumps(item,ensure_ascii=False),flush=True)
    from collections import Counter
    summary={"original_universe":300,"original_received":report["received_count"],
             "original_missing":len(results),"categories":dict(Counter(r.get("category","unresolved") for r in results)),
             "release_gate":"not_verified","note":"Preferred shares are reported separately; the 300-security denominator has not been changed."}
    (OUT/"report.json").write_text(json.dumps({"summary":summary,"records":results},ensure_ascii=False,indent=2),encoding="utf-8")
    print("SOURCE GAP SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
