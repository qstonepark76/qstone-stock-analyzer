"""Recover direct published close on the precise target session.
Use archived KRX if available; otherwise Naver dated daily close.
No cross-source verification, no backdated scoring, no trading.
"""
import json,re,time
from pathlib import Path
from datetime import date,datetime,timezone,timedelta
from collections import Counter,defaultdict
import requests
from leading_naver_outlook_replay import close_map,report_rows,select_slots
from final_leading_model import finite
KST=timezone(timedelta(hours=9))
URL="https://m.stock.naver.com/api/stock/{ticker}/price"
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
def published_close(payload,day,ticker):
    if not isinstance(payload,list):return None
    values=set()
    for r in payload:
        if not isinstance(r,dict):continue
        if r.get("itemCode") and str(r["itemCode"]).zfill(6)!=ticker:continue
        d=str(r.get("localTradedAt") or "")[:10]
        if d!=day:continue
        try:v=float(str(r.get("closePrice")).replace(",",""))
        except (TypeError,ValueError):continue
        if finite(v) and v>0:values.add(v)
    return next(iter(values)) if len(values)==1 else None
def main():
    out=Path("audit-leading-outlook-price");out.mkdir(exist_ok=True)
    prior=read("replay/summary.json");records=read("replay/records.json")
    day=prior["price_date"];asof=date.fromisoformat(prior["asof"])
    krx=read("direct/krx-price-source.json")
    print("KRX ARCHIVE DIAGNOSTIC",json.dumps({"rows":len(krx),"keys":sorted(krx[0]) if krx else [],"sample":krx[:1]},ensure_ascii=False),flush=True)
    closes=close_map(krx)
    nav=report_rows(read("roadmap/reports-2026-11-27.json"),asof)
    kis={r["ticker"]:r.get("invest-opinion",{}).get("date_checked_candidates",[]) for r in read("kis/raw_candidates.json")}
    session=requests.Session();session.headers.update({"User-Agent":"Mozilla/5.0","Accept":"application/json","Referer":"https://m.stock.naver.com/"})
    counts=Counter();errors=Counter();mixed=Counter();sources=[];stop=False
    for i,r in enumerate(records,1):
        t=r["ticker"];v=closes.get(t);src=None;stamp=None
        if finite(v):src="KRX archived close"
        elif not stop:
            try:
                res=session.get(URL.format(ticker=t),params={"pageSize":10,"page":1},timeout=(5,12),allow_redirects=False)
                stamp=datetime.now(KST).isoformat()
                if res.status_code in (401,403,429):
                    errors["http_"+str(res.status_code)]+=1;stop=True
                else:
                    res.raise_for_status();raw=res.json()
                    v=published_close(raw,day,t)
                    if finite(v):src="Naver dated daily close"
                    else:
                        errors["no_exact_session_close"]+=1
                        if errors["no_exact_session_close"]==1:
                            print("NAVER PRICE SCHEMA",json.dumps({"type":type(raw).__name__,"sample":raw[:1] if isinstance(raw,list) else list(raw) if isinstance(raw,dict) else None},ensure_ascii=False),flush=True)
            except (requests.RequestException,ValueError) as e:errors[type(e).__name__]+=1
            finally:time.sleep(.45)
        slots=select_slots(nav.get(t,[]),kis.get(t,[]),asof,v)
        if "op_forecast_growth" in r["slots"]:slots["op_forecast_growth"]=r["slots"]["op_forecast_growth"]
        r["slots"]=slots;r["close"]=v;r["close_source"]=src;r["close_observed_at"]=stamp
        if src:
            counts["price_mapped"]+=1;counts["price|"+src]+=1
            sources.append({"ticker":t,"price":v,"session":day,"source":src,"source_ref":URL.format(ticker=t) if stamp else "KRX archived artifact 46045554502","observed_at":stamp})
        for k,z in slots.items():counts[k]+=1;mixed[k]+=1
        if "op_forecast_growth" not in slots and r.get("own_growth_candidate"):mixed["op_forecast_growth"]+=1
        if r.get("own_revision_candidate"):mixed["earnings_revision"]+=1
        if i%50==0:print("OUTLOOK PRICE RECOVERY",i,"/",len(records),flush=True)
    fields=("rating","upside","target_revision","op_forecast_growth","earnings_revision");n=len(records)
    summary={"target_count":n,"price_date":day,"forecast_asof":asof.isoformat(),"counts":dict(counts),"mixed_counts":{k:mixed[k] for k in fields},"errors":dict(errors),"prior_external_candidate_pct":prior["external_candidate_coverage_pct"],"external_candidate_coverage_pct":100*sum(counts[k] for k in fields)/(5*n),"hypothetical_mixed_coverage_pct":100*sum(mixed[k] for k in fields)/(5*n),"official_new_admitted":0,"note":"Use exact dated published prices without cross-check. Later acquisition retained; this is a current candidate scenario, not proof of historical availability. Own forecast validation and comparable forecast revisions still pending."}
    write(out/"summary.json",summary);write(out/"records.json",records);write(out/"price_evidence.json",sources)
    print("OUTLOOK PRICE RECOVERY SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
