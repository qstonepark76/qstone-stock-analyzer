"""Reuse archived legacy recommendations as a separate actual-return comparator.
No new model historical ranks are fabricated. Read-only KIS adjusted OHLC,
reconciled to frozen KRX end close; no calls for immature cohorts.
"""
import os,json,time
from pathlib import Path
from statistics import mean
from collections import Counter
from final_leading_model import finite
from leading_market_inputs import HOST,session_rows
from collect import kis_access_token,kis_request_with_retry,txt,num

HORIZONS={"1w":5,"1m":20,"3m":60}
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
def positive(v):return finite(v) and v>0

def make_cohorts(history,days,raw):
    cohorts=[];seen=set()
    for record in history:
        d=record["as_of"].replace("-","")
        if d in seen:raise ValueError("duplicate historical snapshot")
        seen.add(d)
        if d not in days:continue
        i=days.index(d)
        for strategy,stocks in record.get("strategies",{}).items():
            if not stocks:continue
            tickers=[r["ticker"] for r in stocks]
            if len(tickers)!=len(set(tickers)):raise ValueError("duplicate ticker")
            initial_ok=all(positive(r.get("close")) and raw[d].get(r["ticker"],{}).get("close")==r["close"] for r in stocks)
            for label,h in HORIZONS.items():
                end=i+h
                cohorts.append({"snapshot":record["as_of"],"strategy":strategy,"horizon":label,"tickers":tickers,
                 "sessions":days[i+1:end+1] if end<len(days) else [],
                 "status":"price_reconciliation_failed" if not initial_ok else "pending" if end<len(days) else "not_mature"})
    return cohorts

def evaluate_cohort(row,prices,index,cost_bps=30):
    if row["status"]!="pending":return row
    days=row["sessions"];ts=row["tickers"]
    if not days:return dict(row,status="not_mature")
    first,last=days[0],days[-1]
    if not positive(index.get(first,{}).get("open")) or not positive(index.get(last,{}).get("close")):
        return dict(row,status="benchmark_missing")
    if any(not positive(prices.get(t,{}).get(first,{}).get("open")) or any(not positive(prices.get(t,{}).get(d,{}).get("close")) for d in days) for t in ts):
        return dict(row,status="missing_constituent_or_delisting")
    start={t:prices[t][first]["open"] for t in ts}
    cost=1-cost_bps/10000
    path=[mean(prices[t][d]["close"]/start[t] for t in ts)*cost for d in days]
    returns=[100*(prices[t][last]["close"]/start[t]*cost-1) for t in ts]
    benchmark=100*(index[last]["close"]/index[first]["open"]-1)
    peak=1;dd=0
    for v in path:peak=max(peak,v);dd=min(dd,v/peak-1)
    return dict(row,status="evaluated",entry=first,exit=last,net_return_pct=100*(path[-1]-1),benchmark_pct=benchmark,
        excess_pct=mean(returns)-benchmark,win_rate_pct=100*sum(v>0 for v in returns)/len(ts),
        outperform_rate_pct=100*sum(v>benchmark for v in returns)/len(ts),cohort_mdd_pct=100*dd)

def main():
    root=Path("data");out=Path("audit-leading-stage8");out.mkdir(exist_ok=True)
    cutoff=read(root/"latest.json")["as_of"].replace("-","")
    days=sorted(p.stem for p in (root/"history").glob("*.json") if len(p.stem)==8 and p.stem.isdigit() and p.stem<=cutoff)
    history=read(root/"recommendation_history.json")
    raw={d:{r["ticker"]:r for r in read(root/"history"/(d+".json"))} for d in days}
    cohorts=make_cohorts(history,days,raw)
    mature=[r for r in cohorts if r["status"]=="pending"]
    tickers=sorted({t for r in mature for t in r["tickers"]})
    needed=sorted({d for r in mature for d in r["sessions"]}|{cutoff})
    prices={};errors=Counter();index={}
    # Reuse exact KRX official index raw responses from stage 7.
    for d in needed:
        p=Path("stage7/index-raw")/(d+".json")
        if not p.exists():continue
        rows=read(p);matches=[]
        for r in rows:
            name=txt(r,"IDX_NM","idxNm","idx_nm").replace(" ","").upper()
            if name not in ("코스피","KOSPI","코스피종합"):continue
            o=num(r,"OPNPRC_IDX","opnprcIdx","open");c=num(r,"CLSPRC_IDX","clsprcIdx","close")
            if positive(o) and positive(c):matches.append((o,c))
        if len(set(matches))==1:
            o,c=matches[0]
            saved=root/"index_history"/(d+".json")
            if saved.exists() and abs(c/read(saved)["close"]-1)<.0001:index[d]={"open":o,"close":c}
    if tickers:
        key=os.getenv("KIS_APP_KEY","").strip();secret=os.getenv("KIS_APP_SECRET","").strip()
        if not key or not secret:raise ValueError("KIS credentials unavailable")
        token=kis_access_token(key,secret)
        headers={"authorization":"Bearer "+token,"appkey":key,"appsecret":secret,"custtype":"P","tr_id":"FHKST03010100"}
        for t in tickers:
            try:
                rawclose=raw[cutoff].get(t,{}).get("close")
                if not positive(rawclose):errors["end_close_missing"]+=1;continue
                p=kis_request_with_retry(HOST+"inquire-daily-itemchartprice",headers=headers,params={
                    "FID_COND_MRKT_DIV_CODE":"J","FID_INPUT_ISCD":t,"FID_INPUT_DATE_1":needed[0],
                    "FID_INPUT_DATE_2":cutoff,"FID_PERIOD_DIV_CODE":"D","FID_ORG_ADJ_PRC":"0"}).json()
                if str(p.get("rt_cd"))!="0":errors["provider_error"]+=1;continue
                rows=session_rows(p.get("output2") or [],("stck_oprc","stck_clpr"),set(needed))
                if cutoff not in rows or not positive(rows[cutoff][1]) or abs(rows[cutoff][1]/rawclose-1)>.0001:
                    errors["end_close_mismatch"]+=1;continue
                prices[t]={d:{"open":v[0],"close":v[1]} for d,v in rows.items() if positive(v[0]) and positive(v[1])}
            except Exception as e:errors[type(e).__name__]+=1
            finally:time.sleep(.7)
    evaluated=[evaluate_cohort(r,prices,index) for r in cohorts]
    s={"asof":read(root/"latest.json")["as_of"],"legacy_only":True,"new_model_backtest_status":"blocked_no_verified_historical_ranks",
       "archived_snapshot_count":len(history),"archive_session_count":len(days),"mature_cohorts":len(mature),
       "unique_mature_tickers":len(tickers),"adjusted_price_tickers":len(prices),"index_sessions":len(index),
       "cohort_status_counts":dict(Counter(r["status"] for r in evaluated)),"errors":dict(errors),
       "cost_bps_roundtrip":30,"entry":"next trading session open","exit":"horizon session close","return_basis":"corporate-action-adjusted price, not dividend total return",
       "caveat":"Legacy history lacks independent immutable publication proof and final model version. This is a comparison-only archival reconstruction, not new-model backtest or investment result.",
       "evaluated_cohorts":[r for r in evaluated if r["status"]=="evaluated"]}
    for n,v in (("summary.json",s),("cohorts.json",evaluated),("adjusted_prices.json",prices),("benchmark.json",index)):
        write(out/n,v)
    print("STAGE8 LEGACY COMPARATOR",json.dumps({k:v for k,v in s.items() if k!="evaluated_cohorts"},ensure_ascii=False),flush=True)
    print("STAGE8 LEGACY RETURNS",json.dumps([{k:r[k] for k in ("snapshot","strategy","horizon","net_return_pct","benchmark_pct","excess_pct","win_rate_pct","cohort_mdd_pct")} for r in s["evaluated_cohorts"]],ensure_ascii=False),flush=True)
if __name__=="__main__":main()
