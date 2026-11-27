"""Collect published KIS financial/growth ratios and annual sales.
No external cross-validation; no historical backfill or trading.
"""
import os,json,time
from pathlib import Path
from datetime import datetime,timezone,timedelta
from collections import Counter,defaultdict
import requests
from collect import kis_access_token
from leading_kis_outlook_probe import rows,numeric
from final_leading_model import finite,evaluate
HOST="https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/finance/"
KST=timezone(timedelta(hours=9))
GROWTH={"sales_growth":"grs","op_growth":"bsop_prfi_inrt","net_growth":"ntin_inrt"}
FIN={"roe":"roe_val","stability":"lblt_rate"}
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
def annual_value(data,year,field):
    v={numeric(r.get(field)) for r in rows(data) if str(r.get("stac_yymm","")).strip()==f"{year}12"}
    return next(iter(v)) if len(v)==1 and None not in v else None
def cagr(data,year):
    series=[annual_value(data,y,"sale_account") for y in range(year-3,year+1)]
    if not all(finite(v) and v>0 for v in series):return None
    return 100*((series[-1]/series[0])**(1/3)-1)
def parse(ratios,income,year):
    values={k:annual_value(ratios,year,f) for k,f in {**GROWTH,**FIN}.items()}
    # Retain direct provider growth values even if negative. Loss transitions
    # require explicit policy before ranking, not cross-source rechecking.
    values["sales_cagr"]=cagr(income,year)
    return {k:v for k,v in values.items() if finite(v)}
def main():
    out=Path("audit-leading-kis-growth");out.mkdir(exist_ok=True)
    p=read("simplified/observations.json");a=read("replay-source/report.json");year=int(a["year"])
    target=[r for r in p["stocks"] if not r.get("excluded")];n=len(target)
    key=os.getenv("KIS_APP_KEY","").strip();secret=os.getenv("KIS_APP_SECRET","").strip()
    if not key or not secret:raise ValueError("KIS credentials unavailable")
    token=kis_access_token(key,secret);session=requests.Session()
    headers={"authorization":"Bearer "+token,"appkey":key,"appsecret":secret,"custtype":"P"}
    counts=Counter();errors=Counter();records=[];stopped=False
    def call(t,endpoint,tr):
        nonlocal stopped
        result={"source_ref":HOST+endpoint,"rows":[]}
        if stopped:return result
        try:
            res=session.get(HOST+endpoint,headers=dict(headers,tr_id=tr),params={"FID_DIV_CLS_CODE":"0","FID_COND_MRKT_DIV_CODE":"J","FID_INPUT_ISCD":t},timeout=(5,15),allow_redirects=False)
            result["observed_at"]=datetime.now(KST).isoformat()
            if res.status_code in (401,403,429):stopped=True;errors[endpoint+"|"+str(res.status_code)]+=1;return result
            res.raise_for_status();j=res.json()
            if str(j.get("rt_cd"))!="0":
                code=str(j.get("msg_cd") or "provider_error");errors[endpoint+"|"+code]+=1
                if code in ("EGW00201","EGW00123"):stopped=True
                return result
            result["rows"]=rows(j.get("output"));result["continuation"]=res.headers.get("tr_cont","")
            counts[endpoint+"_success"]+=1
            if result["continuation"] in ("M","F"):counts[endpoint+"_continuation"]+=1
        except (requests.RequestException,ValueError) as e:errors[endpoint+"|"+type(e).__name__]+=1
        finally:time.sleep(1)
        return result
    for i,r in enumerate(target,1):
        t=r["ticker"]
        ratio=call(t,"financial-ratio","FHKST66430300")
        income=call(t,"income-statement","FHKST66430200")
        values=parse(ratio["rows"],income["rows"],year)
        records.append({"ticker":t,"model":r.get("financial_model"),"year":year,"provider_values":values,"ratios":ratio,"income":income,"basis":"KIS annual fiscal period; preserve provider scope as unspecified if absent"})
        if i%25==0:print("DIRECT KIS GROWTH PROGRESS",i,"/",n,flush=True)
        if stopped:break
    index={r["ticker"]:r for r in records}
    existing={r["ticker"]:r["base"]["detail"] for r in evaluate(p)["records"]}
    weights={"sales_growth":5,"op_growth":7,"net_growth":5,"sales_cagr":3}
    for r in target:
        t=r["ticker"];v=index.get(t,{}).get("provider_values",{})
        for k in weights:
            old=existing[t][k]["points"] is not None
            if old:counts[k+"_baseline"]+=1
            if k in v:
                counts[k+"_provider"]+=1
                if not old:counts[k+"_gap_candidate"]+=1
        for k in FIN:
            if k in v and (k!="stability" or (r.get("financial_model") in (None,"operating_holding") and v[k]>=0)):
                counts[k+"_financial_provider"]+=1
                if existing[t][k]["points"] is None:counts[k+"_financial_gap_candidate"]+=1
    baseline=sum(w*counts[k+"_baseline"] for k,w in weights.items())/(20*n)*100
    added=sum(w*counts[k+"_gap_candidate"] for k,w in weights.items())/(20*n)*100
    summary={"target_count":n,"queried":len(records),"counts":dict(counts),"errors":dict(errors),"baseline_growth_pct":baseline,"provider_growth_coverage_pct":sum(w*counts[k+"_provider"] for k,w in weights.items())/(20*n)*100,"potential_gap_pp":added,"hypothetical_if_all_gaps_scored_pct":baseline+added,"official_new_admitted":0,"note":"No cross-source verification. Provider growth convention not assumed identical to legacy symmetric profit changes. True CAGR uses four actual annual sales values. Scope, comparable loss transitions and scoring must be handled consistently. Current acquisition not backdated."}
    write(out/"summary.json",summary);write(out/"records.json",records)
    print("DIRECT KIS GROWTH SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
