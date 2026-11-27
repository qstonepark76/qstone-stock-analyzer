"""Direct Naver annual actuals, no cross-provider validation.
Preserve source evidence and keep current acquisition out of frozen historical scores.
"""
import json,time,re
from datetime import datetime,timezone,timedelta
from pathlib import Path
from collections import Counter,defaultdict
import requests
from final_leading_model import finite,evaluate
from leading_direct_financial import number,URL
from leading_direct_outlook import profit_growth
KST=timezone(timedelta(hours=9))
WEIGHTS={"sales_growth":5,"op_growth":7,"net_growth":5,"sales_cagr":3}
LABELS={"매출액":"sales","영업이익":"op","당기순이익":"net"}
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
def parse(raw,year):
    f=raw.get("financeInfo") if isinstance(raw,dict) else None
    if not isinstance(f,dict):return {},{}
    dates=Counter(str(t.get("key")) for t in f.get("trTitleList",[]) if isinstance(t,dict) and t.get("isConsensus") in ("N",False) and "E" not in str(t.get("title","")).upper())
    ys=[y for y in range(year-3,year+1) if dates[f"{y}12"]==1]
    candidates=defaultdict(list)
    for r in f.get("rowList",[]):
        if not isinstance(r,dict):continue
        k=LABELS.get(re.sub(r"\s+","",str(r.get("title",""))))
        cols=r.get("columns")
        if not k or not isinstance(cols,dict):continue
        for y in ys:
            v=number(cols.get(f"{y}12"))
            if finite(v):candidates[(k,y)].append(v)
    levels={k:{str(y):vs[0] for (kk,y),vs in candidates.items() if kk==k and len(set(vs))==1} for k in LABELS.values()}
    result={}
    for k,field in (("sales","sales_growth"),("op","op_growth"),("net","net_growth")):
        a,b=[levels[k].get(str(y)) for y in (year-1,year)]
        if not all(finite(v) for v in (a,b)):continue
        if k=="sales":
            if a>0 and b>=0:result[field]=100*(b/a-1)
        else:result[field]=profit_growth(a,b)
    ss=[levels["sales"].get(str(y)) for y in range(year-3,year+1)]
    if all(finite(v) and v>0 for v in ss):result["sales_cagr"]=100*((ss[-1]/ss[0])**(1/3)-1)
    return result,levels
def main():
    out=Path("audit-leading-naver-growth");out.mkdir(exist_ok=True)
    p=read("simplified/observations.json");year=int(read("replay-source/report.json")["year"])
    targets=[r for r in p["stocks"] if not r.get("excluded")]
    existing={r["ticker"]:r["base"]["detail"] for r in evaluate(p)["records"]}
    session=requests.Session();session.headers.update({"User-Agent":"Mozilla/5.0","Accept":"application/json","Referer":"https://m.stock.naver.com/"})
    records=[];errors=Counter();counts=Counter();stop=False
    for i,r in enumerate(targets,1):
        t=r["ticker"];item={"ticker":t,"year":year,"source_ref":URL.format(ticker=t),"values":{},"annual_actuals":{}}
        if not stop:
            try:
                res=session.get(item["source_ref"],timeout=(5,12),allow_redirects=False);item["observed_at"]=datetime.now(KST).isoformat()
                if res.status_code in (401,403,429):errors["http_"+str(res.status_code)]+=1;stop=True
                else:
                    res.raise_for_status();raw=res.json()
                    if isinstance(raw,dict) and raw.get("itemCode") and str(raw["itemCode"]).zfill(6)!=t:errors["ticker_mismatch"]+=1
                    else:
                        item["values"],item["annual_actuals"]=parse(raw,year)
                        f=raw.get("financeInfo",{}) if isinstance(raw,dict) else {}
                        item["provider_basis"]=f.get("financeType") or f.get("accountingType")
                        if not item["values"]:errors["no_growth_values"]+=1
            except (requests.RequestException,ValueError) as e:errors[type(e).__name__]+=1
            finally:time.sleep(.45)
        for k in WEIGHTS:
            old=existing[t][k]["points"] is not None
            if old:counts[k+"_baseline"]+=1
            if k in item["values"]:
                counts[k+"_provider"]+=1
                if not old:counts[k+"_gap_candidate"]+=1
        records.append(item)
        if i%50==0:print("NAVER GROWTH PROGRESS",i,"/",len(targets),flush=True)
    n=len(targets)
    cov=lambda suffix:sum(w*counts[k+suffix] for k,w in WEIGHTS.items())/(20*n)*100
    summary={"target_count":n,"counts":dict(counts),"errors":dict(errors),"baseline_growth_pct":cov("_baseline"),"provider_growth_coverage_pct":cov("_provider"),"hypothetical_if_all_gaps_scored_pct":cov("_baseline")+cov("_gap_candidate"),"official_new_admitted":0,"note":"Direct actuals from same provider table, no cross-source verification. True 3-year CAGR requires four actual annual columns. Current acquisition is separate from frozen scores; loss transitions and accounting basis retained for integration."}
    write(out/"summary.json",summary);write(out/"records.json",records);print("NAVER DIRECT GROWTH SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
