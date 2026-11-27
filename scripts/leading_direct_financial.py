"""Collect Naver annual reported financial values without cross-source validation.
Separate current-observation audit; never backdate to frozen snapshot.
"""
import json,re,time
from datetime import datetime,timezone,timedelta
from pathlib import Path
from collections import Counter,defaultdict
import requests
from final_leading_model import finite
KST=timezone(timedelta(hours=9))
URL="https://m.stock.naver.com/api/stock/{ticker}/finance/annual"
LABELS={"ROE":"roe","ROE(%)":"roe","ROE(지배주주)":"roe","ROA":"roa","ROA(%)":"roa","영업이익률":"margin","영업이익률(%)":"margin","부채비율":"stability","부채비율(%)":"stability","영업활동현금흐름":"cfo","영업활동으로인한현금흐름":"cfo","매출액":"sales","영업수익":"sales","당기순이익":"net","자산총계":"assets","영업현금흐름/매출액":"cash"}
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
def number(v):
    if isinstance(v,dict):v=v.get("value")
    if finite(v):return float(v)
    if not isinstance(v,str):return None
    v=v.strip().replace(",","").removesuffix("%").strip()
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?",v):return None
    x=float(v);return x if finite(x) else None
def parse(raw,year):
    if not isinstance(raw,dict):return {},{},None
    f=raw.get("financeInfo")
    if not isinstance(f,dict):return {},{},None
    # Actual December annual column only; never read a consensus forecast as actual.
    key=f"{year}12";ts=[t for t in f.get("trTitleList",[]) if isinstance(t,dict) and str(t.get("key"))==key and t.get("isConsensus") in ("N",False) and "E" not in str(t.get("title","")).upper()]
    if len(ts)!=1:return {},{},None
    candidates=defaultdict(list);all_labels=Counter()
    for r in f.get("rowList",[]):
        if not isinstance(r,dict):continue
        title=re.sub(r"\s+","",str(r.get("title","")))
        all_labels[title]+=1
        k=LABELS.get(title)
        cols=r.get("columns")
        if not k or not isinstance(cols,dict):continue
        x=number(cols.get(key))
        if x is not None:candidates[k].append({"value":x,"label":title,"raw":cols[key]})
    vals={k:rs[0] for k,rs in candidates.items() if len({r["value"] for r in rs})==1}
    basis=f.get("financeType") or f.get("accountingType") or raw.get("financeType") or raw.get("accountingType")
    return vals,dict(all_labels),basis
def main():
    out=Path("audit-leading-direct-financial");out.mkdir(exist_ok=True)
    p=read("simplified/observations.json");a=read("replay-source/report.json");year=int(a["year"])
    target=[r for r in p["stocks"] if not r.get("excluded")]
    fields=("roe","roa","margin","stability","cash");weights=dict(zip(fields,(5,3,4,4,4)))
    errors=Counter();labels=Counter();counts=Counter();records=[]
    session=requests.Session();session.headers.update({"User-Agent":"Mozilla/5.0","Accept":"application/json","Referer":"https://m.stock.naver.com/"})
    for i,r in enumerate(target,1):
        t=r["ticker"];item={"ticker":t,"model":r.get("financial_model"),"source_ref":URL.format(ticker=t),"year":year,"fields":{}}
        try:
            res=session.get(item["source_ref"],timeout=(5,12),allow_redirects=False);item["observed_at"]=datetime.now(KST).isoformat()
            if res.status_code in (401,403,429):
                errors["http_"+str(res.status_code)]+=1;records.append(item);break
            res.raise_for_status();raw=res.json()
            vals,ls,basis=parse(raw,year);labels.update(ls);item["fields"]=vals;item["provider_basis"]=basis
            if not vals:errors["no_actual_fields"]+=1
        except (requests.RequestException,ValueError) as e:errors[type(e).__name__]+=1
        records.append(item)
        if i%50==0:print("DIRECT FINANCIAL PROGRESS",i,"/",len(target),flush=True)
        time.sleep(.45)
    by={r["ticker"]:r for r in records}
    from final_leading_model import evaluate
    scored={r["ticker"]:r["base"]["detail"] for r in evaluate(p)["records"]}
    for r in target:
        t=r["ticker"];item=by.get(t,{});v=item.get("fields",{});industrial=r.get("financial_model") in (None,"operating_holding")
        # Preserve published values, but never substitute industrial debt/cash
        # ratios for financial-sector stability. Calculated ratios are separate.
        for k in fields:
            val=v.get(k,{}).get("value")
            ok=finite(val) and (industrial or k not in ("stability","cash"))
            if k=="stability" and ok and val<0:ok=False
            if ok:counts[k+"_provider"]+=1
            if k=="cash" and industrial and not ok:
                c,s=[v.get(x,{}).get("value") for x in ("cfo","sales")]
                if finite(c) and finite(s) and s>0:
                    # Only candidate: confirm monetary unit metadata before combining.
                    item["cash_calculation_candidate"]=100*c/s
                    counts["cash_calculated_candidate"]+=1
            if k=="roa" and not ok and finite(v.get("net",{}).get("value")) and finite(v.get("assets",{}).get("value")):
                counts["roa_amounts_candidate"]+=1
            before=scored[t][k]["points"] is not None
            if before:counts[k+"_baseline_scored"]+=1
            if ok and not before:counts[k+"_provider_gap_candidates"]+=1
    n=len(target);base=sum(weights[k]*counts[k+"_baseline_scored"] for k in fields)/(20*n)*100
    added=sum(weights[k]*counts[k+"_provider_gap_candidates"] for k in fields)/(20*n)*100
    summary={"target_count":n,"queried":len(records),"counts":dict(counts),"labels":dict(labels),"errors":dict(errors),"baseline_financial_coverage_pct":base,"potential_provider_gap_pp":added,"hypothetical_if_all_provider_gaps_scored_pct":base+added,"official_new_admitted":0,"note":"No independent cross-source validation. Source field, fiscal period, scope and peer comparability still matter. Current query not backdated. KRX/KIS fallback not yet implemented. Cash amount candidates are not counted in hypothetical coverage."}
    write(out/"summary.json",summary);write(out/"records.json",records)
    print("DIRECT FINANCIAL SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
