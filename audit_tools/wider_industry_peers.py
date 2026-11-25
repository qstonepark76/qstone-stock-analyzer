"""Build peer-only candidates from the wider actual KRX snapshot.
No change to the top-300 investment universe or scoring model.
"""
import datetime as dt
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
sys.path.insert(0,"scripts")
from collect import DART_KEY, download_corp_map, dart_company_financial, extract_financial, request_with_retry
from financial_industry import financial_model_for
from metric_quality import source_check, admitted_industry_metrics
from industry_relative import METRICS

OUT=Path("audit-wider-peers")
SOURCE=Path("replay-source")
LIMIT=250

def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def main():
    if not DART_KEY:
        raise ValueError("DART credential unavailable")
    OUT.mkdir(exist_ok=True)
    universe=read(SOURCE/"universe.json")
    audit=read(SOURCE/"report.json")
    year=audit["year"]
    asof=dt.date.fromisoformat(universe["asof"])
    market=read(Path("data/history")/(asof.strftime("%Y%m%d")+".json"))
    targets={s["ticker"] for s in universe["stocks"]}
    target_records=read("audit-top300-replay/records.json")
    target_codes={str(r["industry_code"]) for r in target_records if r.get("industry_code") and r["screening_class"]=="industrial_or_unclassified"}
    if len(targets)!=300 or not target_codes:
        raise ValueError("Target codes missing")
    corpmap=download_corp_map()
    existing={corpmap[t] for t in targets if t in corpmap}
    rows=sorted((s for s in market if s["ticker"] not in targets and s["ticker"] in corpmap and (s.get("market_cap") or 0)>0),key=lambda s:(-s["market_cap"],s["ticker"]))
    cache=read("data/sector_industry_cache.json")
    selected=[]
    seen=set(existing)
    for s in rows:
        corp=corpmap[s["ticker"]]
        if corp in seen:
            continue
        seen.add(corp)
        selected.append(s)
    counts=Counter()
    peers=[]
    metadata=[]
    for s in selected[:LIMIT]:
        t=s["ticker"]
        corp=corpmap[t]
        saved=cache.get(t) or {}
        code=None
        try:
            age=(asof-dt.date.fromisoformat(saved["cached_at"][:10])).days
            if saved.get("corp_code")==corp and 0<=age<365 and str(saved.get("industry_code")).isdigit():
                code=str(saved["industry_code"])
        except (KeyError,TypeError,ValueError):
            pass
        try:
            if code is None:
                response=request_with_retry("GET","https://opendart.fss.or.kr/api/company.json",params={"crtfc_key":DART_KEY,"corp_code":corp},timeout=(5,12))
                p=response.json()
                if p.get("status")=="000" and p.get("corp_code")==corp and str(p.get("induty_code")).isdigit():
                    code=str(p["induty_code"])
                else:
                    counts["industry_code_unavailable"]+=1
                time.sleep(.2)
            if code is None:
                continue
            metadata.append({"ticker":t,"corp_code":corp,"industry_code":code})
            counts["industry_code_verified"]+=1
            if code not in target_codes or financial_model_for(t,code):
                continue
            counts["exact_code_match"]+=1
            raw,scope,_=dart_company_financial(corp,year)
            if not raw or scope!="CFS" or not source_check(raw,year,scope):
                counts["financial_source_unavailable"]+=1
                continue
            metrics=extract_financial(raw,ticker=t,financial_year=year,fs_div=scope)
            admitted=admitted_industry_metrics(metrics["industry_metrics"],metrics["industry_metric_quality"],year)
            peer={"ticker":t,"corp_code":corp,"name":s["name"],"industry_code":code,
                  "industry_confidence":"verified","financial_model":None,"industry_metrics":admitted,
                  "financial_year":year,"peer_only":True}
            peers.append(peer)
            counts["peer_rows"]+=1
            counts["complete_five_metrics"]+=int(all(admitted.get(k) is not None for k in METRICS))
            print("WIDER PEER RECORD",json.dumps({"ticker":t,"code":code,"admitted":sum(v is not None for v in admitted.values())}),flush=True)
            time.sleep(.2)
        except Exception as exc:
            counts["error:"+type(exc).__name__]+=1
        (OUT/"peers.json").write_text(json.dumps(peers,ensure_ascii=False,indent=2),encoding="utf-8")
    summary={"asof":asof.isoformat(),"market_snapshot_count":len(market),"outside_target_distinct_issuers":len(selected),"batch_limit":LIMIT,"counts":dict(counts),"scope":"First batch of the available KRX snapshot only; exchange coverage not yet established. Peer-only, not recommendation candidates."}
    (OUT/"peers.json").write_text(json.dumps(peers,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"metadata.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print("WIDER PEER SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
