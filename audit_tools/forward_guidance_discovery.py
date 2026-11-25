"""Collect official forward-guidance disclosure metadata, not inferred forecasts.
OpenDART list.json, exchange disclosure type I; frozen as-of date.
A disclosure title is only a discovery candidate, never a forecast observation.
"""
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path
import requests
sys.path.insert(0,"scripts")
from collect import DART_KEY
OUT=Path("audit-forward-guidance")
def main():
    if not DART_KEY:
        raise SystemExit("DART credential unavailable")
    u=json.loads(Path("replay-source/universe.json").read_text(encoding="utf-8"))
    targets={r["ticker"]:r["name"] for r in u["stocks"]}
    end=dt.date.fromisoformat(u["asof"])
    start=end-dt.timedelta(days=179)
    cursor=start
    records={}
    errors=[]
    total_pages=0
    session=requests.Session()
    while cursor<=end:
        stop=min(cursor+dt.timedelta(days=13),end)
        page=1
        while page<=100:
            try:
                response=session.get("https://opendart.fss.or.kr/api/list.json",params={"crtfc_key":DART_KEY,"bgn_de":cursor.strftime("%Y%m%d"),"end_de":stop.strftime("%Y%m%d"),"pblntf_ty":"I","corp_cls":"Y","page_no":page,"page_count":100},timeout=(5,20),allow_redirects=False)
                response.raise_for_status()
                p=response.json()
                if p.get("status")=="013":
                    break
                if p.get("status")!="000" or not isinstance(p.get("list"),list):
                    errors.append({"from":str(cursor),"page":page,"status":str(p.get("status"))})
                    break
                total_pages+=1
                for r in p["list"]:
                    t=str(r.get("stock_code") or "")
                    title=str(r.get("report_nm") or "")
                    receipt=str(r.get("rcept_no") or "")
                    pub=str(r.get("rcept_dt") or "")
                    if t not in targets or not re.fullmatch(r"\d{14}",receipt) or not re.fullmatch(r"\d{8}",pub) or not cursor.strftime("%Y%m%d")<=pub<=stop.strftime("%Y%m%d"):
                        continue
                    normalized="".join(title.split())
                    if not ("전망" in normalized and ("영업실적" in normalized or "매출액" in normalized or "영업이익" in normalized)):
                        continue
                    records[receipt]={"ticker":t,"name":targets[t],"corp_code":r.get("corp_code"),"receipt":receipt,"published_at":pub,"title":title,"source_url":"https://dart.fss.or.kr/dsaf001/main.do?rcpNo="+receipt,"status":"guidance_discovery_unverified"}
                if page>=int(p.get("total_page",0)):
                    break
                page+=1
                time.sleep(.25)
            except Exception as exc:
                errors.append({"from":str(cursor),"page":page,"status":type(exc).__name__})
                break
        if page>100:
            errors.append({"from":str(cursor),"status":"page_limit"})
        cursor=stop+dt.timedelta(days=1)
    OUT.mkdir(exist_ok=True)
    summary={"universe":len(targets),"start":str(start),"end":str(end),"pages":total_pages,"candidate_filings":len(records),"candidate_issuers":len({r["ticker"] for r in records.values()}),"errors":errors,"admitted_forecasts":0,"release_gate":"not_verified"}
    (OUT/"records.json").write_text(json.dumps(list(records.values()),ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print("FORWARD GUIDANCE SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__":
    main()
