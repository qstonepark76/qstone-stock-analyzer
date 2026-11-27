"""Direct source outlook candidate under approved no-cross-validation policy.
Use real acquisition dates, never backfill older snapshots.
Own-model candidates and 30-day signals remain separate.
"""
import json,time
from datetime import datetime,date,timedelta,timezone
from pathlib import Path
from collections import Counter,defaultdict
import requests
from collect import get_krx_day,txt,num
from outlook_candidate import broker_key,RATINGS,recency,weighted
from verify_broker_reports import normalize_rating
from final_leading_model import finite,curve
from forecast_score_policy import forecast_fraction
from leading_direct_financial import number,URL
from leading_kis_expanded_layout import layout
KST=timezone(timedelta(hours=9))
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
def broker_metrics(reports,asof,close):
    grouped=defaultdict(lambda:defaultdict(set))
    for r in reports:
        try:d=date.fromisoformat(r["report_date"])
        except (ValueError,TypeError,KeyError):continue
        b=broker_key(r.get("broker"))
        if not b or not 0<=(asof-d).days<=90:continue
        rating=RATINGS.get(normalize_rating({"source_opinion_text":r.get("opinion")}))
        t=r.get("target_price_candidate")
        grouped[b][d].add((rating,t if finite(t) and t>0 else None))
    slots=defaultdict(list)
    for broker,dates in grouped.items():
        ds=sorted(dates,reverse=True)
        if len(dates[ds[0]])!=1:continue
        r,t=next(iter(dates[ds[0]]));w=recency((asof-ds[0]).days)
        if finite(r):slots["rating"].append((r,w,broker))
        if finite(t) and finite(close) and close>0:slots["upside"].append((100*(t/close-1),w,broker))
        if finite(t) and len(ds)>1 and len(dates[ds[1]])==1:
            old=next(iter(dates[ds[1]]))[1]
            if finite(old) and old>0:slots["target_revision"].append((100*(t/old-1),w,broker))
    out={}
    for k,items in slots.items():
        v=weighted([(x,w) for x,w,b in items])
        out[k]={"value":v,"broker_count":len(items),"brokers":[b for x,w,b in items],"source":"KIS invest-opinion","points_candidate":round(2*curve(k,v),6)}
        if k=="target_revision":out[k]["basis"]="same broker consecutive reported targets; corporate action adjustment not independently checked; not a 30-day signal"
    return out
def profit_growth(a,b):
    if not finite(a) or not finite(b):return None
    if a>0 and b>=0:return 100*(b/a-1)
    return 200*(b-a)/(abs(a)+abs(b)) if abs(a)+abs(b)>0 else 0
def naver_forecast(raw,year):
    f=raw.get("financeInfo") if isinstance(raw,dict) else None
    if not isinstance(f,dict):return None
    prev=f"{year-1}12";current=f"{year}12"
    ts=f.get("trTitleList",[])
    actual=[x for x in ts if str(x.get("key"))==prev and x.get("isConsensus") in (False,"N")]
    forecast=[x for x in ts if str(x.get("key"))==current and x.get("isConsensus") in (True,"Y")]
    if len(actual)!=1 or len(forecast)!=1:return None
    rows=[r for r in f.get("rowList",[]) if str(r.get("title","")).replace(" ","")=="영업이익"]
    if len(rows)!=1:return None
    cols=rows[0].get("columns",{})
    a,b=number(cols.get(prev)),number(cols.get(current));v=profit_growth(a,b)
    if v is None:return None
    return {"value":v,"source":"Naver annual consensus display","provider_actual":a,"provider_forecast":b,"period_end":f"{year}-12-31","points_candidate":round(2*curve("op_forecast_growth",v),6),"basis":"same annual table operating profit; broker count unspecified"}
def main():
    out=Path("audit-leading-direct-outlook");out.mkdir(exist_ok=True)
    p=read("simplified/observations.json")
    archived=read("kis/raw_candidates.json");by={r["ticker"]:r for r in archived}
    # Use last actual completed trading day from archive acquisition date.
    observed=[datetime.fromisoformat(r["invest-opinion"]["observed_at"]).astimezone(KST).date() for r in archived if r.get("invest-opinion",{}).get("observed_at")]
    asof=max(observed);price_date=asof-timedelta(days=1)
    if price_date.weekday()>=5:price_date-=timedelta(days=price_date.weekday()-4)
    raw=get_krx_day(price_date)
    closes={txt(r,"ISU_CD","isuCd","ticker").strip().zfill(6):num(r,"TDD_CLSPRC","tddClsprc","close") for r in raw}
    write(out/"krx-price-source.json",raw)
    layout_evidence={r["ticker"]:r for r in read("layout/issuer_reconciliation.json")}
    targets=[r for r in p["stocks"] if not r.get("excluded")]
    own=read("own/own_forecast_scenario.json")
    own_sets=defaultdict(set)
    for r in own:own_sets[r["metric"]].add(r["ticker"])
    session=requests.Session();session.headers.update({"User-Agent":"Mozilla/5.0","Accept":"application/json","Referer":"https://m.stock.naver.com/"})
    counts=Counter();errors=Counter();records=[];stopped=False
    for i,row in enumerate(targets,1):
        t=row["ticker"];r=by.get(t,{});o=r.get("invest-opinion",{});close=closes.get(t)
        slots=broker_metrics(o.get("date_checked_candidates",[]),asof,close)
        # Same-table labelled Naver estimates are direct source candidates.
        f=None;at=None
        if not stopped:
            try:
                res=session.get(URL.format(ticker=t),timeout=(5,12),allow_redirects=False);at=datetime.now(KST).isoformat()
                if res.status_code in (401,403,429):
                    errors["http_"+str(res.status_code)]+=1;stopped=True
                else:
                    res.raise_for_status();f=naver_forecast(res.json(),asof.year)
            except (requests.RequestException,ValueError) as e:errors[type(e).__name__]+=1
            finally:time.sleep(.45)
        if f:slots["op_forecast_growth"]=f;counts["naver_growth"]+=1
        else:
            l=layout_evidence.get(t,{})
            v=l.get("op_forecast_growth_candidate")
            if finite(v):
                slots["op_forecast_growth"]={"value":v,"source":"KIS research estimate layout candidate","points_candidate":round(2*forecast_fraction("op_forecast_growth",v,"single_broker"),6),"basis":"previous schema reconciliation, current estimate candidate"}
                counts["kis_growth"]+=1
        for k in slots:counts[k]+=1
        records.append({"ticker":t,"close":close,"price_date":price_date.isoformat(),"broker_observed_at":o.get("observed_at"),"naver_observed_at":at,"slots":slots,
                        "own_growth_candidate":t in own_sets["op_forecast_growth"],"own_revision_candidate":t in own_sets["earnings_revision"]})
        if i%50==0:print("DIRECT OUTLOOK PROGRESS",i,"/",len(targets),flush=True)
    n=len(targets);fields=("rating","upside","target_revision","op_forecast_growth","earnings_revision")
    coverage=100*sum(counts[k] for k in fields)/(5*n)
    # Own estimates are explicitly hypothetical; quarterly prior evidence is not
    # a substitute for the actual 30-day leading signals.
    mix=dict(counts);mix["op_forecast_growth"]=sum("op_forecast_growth" in r["slots"] or r["own_growth_candidate"] for r in records);mix["earnings_revision"]=sum(r["own_revision_candidate"] for r in records)
    s={"target_count":n,"asof":asof.isoformat(),"price_date":price_date.isoformat(),"counts":dict(counts),"external_candidate_coverage_pct":coverage,"hypothetical_mixed_coverage_pct":100*sum(mix.get(k,0) for k in fields)/(5*n),"mixed_counts":{k:mix.get(k,0) for k in fields},"errors":dict(errors),"official_new_admitted":0,"note":"No cross-source verification required. Current provider candidate snapshot, not integrated with frozen past prices. Own-model validation pending; earnings revision not fabricated; target revisions use consecutive reports, not leading 30-day measure. Corporate actions and precise same-date source timestamps must be handled before final ranking."}
    write(out/"summary.json",s);write(out/"records.json",records);print("DIRECT OUTLOOK SUMMARY",json.dumps(s,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
