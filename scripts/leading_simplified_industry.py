"""Approved simplified industry replay and financial coverage diagnosis."""
import json
from pathlib import Path
from datetime import date
from collections import Counter
from final_leading_model import evaluate,finite,SIMPLIFIED_SPECIAL
from fundamental_candidate import select,number
from metric_quality import source_check,account_check
from leading_fundamental_inputs import receipt_day,summary
from leading_reuse_stage1 import obs
from leading_stage7_gaps import factor_gaps
from financial_industry import load_financial_observations,comparable_observation,FINANCIAL_MODELS
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
def ratios(raw):
    a={k:select(raw,k) for k in ("sales","op","assets","cfo")}
    out={}
    if account_check([a["assets"]]):
        x,y=[number(a["assets"],k) for k in ("thstrm_amount","frmtrm_amount")]
        if finite(x) and finite(y) and min(x,y)>0:
            avg=(x+y)/2
            for key,k,scale in (("operating_return_on_assets","op",100),("asset_turnover","sales",1)):
                v=number(a[k],"thstrm_amount")
                if account_check([a[k],a["assets"]]) and finite(v) and (k!="sales" or v>=0):out[key]=scale*v/avg
    if account_check([a["cfo"],a["op"]]):
        x,y=[number(a[k],"thstrm_amount") for k in ("cfo","op")]
        if finite(x) and finite(y) and y>0:out["cash_conversion"]=100*x/y
    return out
def main():
    out=Path("audit-leading-simplified");out.mkdir(exist_ok=True)
    p=read("stage5/observations.json");a=read("replay-source/report.json");year=int(a["year"]);cutoff=date.fromisoformat(p["asof"])
    if a["universe_asof"]!=p["asof"]:raise ValueError("snapshot mismatch")
    baseline=evaluate(p);sources={r["ticker"]:r for r in a["records"]}
    peersdir=Path("reuse-peers/audit-wider-peers")
    peer_meta={r["ticker"]:r for r in read(peersdir/"peers.json")}
    p["industry_policy"]="simplified_v1";c=Counter();missing=Counter()
    for row in p["stocks"]+p["comparison_peers"]:
        if row.get("excluded") or row.get("financial_model") not in (None,"operating_holding"):continue
        t=row["ticker"];peer=row.get("peer_only",False);m=(peer_meta if peer else sources).get(t,{})
        folder=peersdir/"source-rows" if peer else Path("replay-source/source-rows")
        path=folder/(t+".json");scope="CFS" if peer else m.get("scope")
        if not path.exists():missing["source_missing"]+=1;continue
        raw=read(path)
        if not source_check(raw,year,scope):missing["source_or_scope"]+=1;continue
        receipt=str(raw[0]["rcept_no"]);d=receipt_day(receipt)
        if [receipt]!=m.get("receipts") or not d or not date(year,12,31)<=d<=cutoff:missing["receipt_or_date"]+=1;continue
        for k,v in ratios(raw).items():
            row["metrics"][k]=obs(v,f"{year}|{scope}|simplified-v1|{k}",f"{year}-12-31",d.isoformat(),"OpenDART receipt "+receipt,metric_id=k)
            c[("peer_" if peer else "target_")+k]+=1
    financial=load_financial_observations(period=f"{year}-12");specialists=[];sc=Counter()
    for r in p["stocks"]:
        if r.get("excluded"):continue
        model=r.get("financial_model")
        if model not in SIMPLIFIED_SPECIAL:continue
        record=financial.get(r["ticker"],{})
        for k,w in SIMPLIFIED_SPECIAL[model].items():
            sc["required"]+=1
            v=comparable_observation(record,k,model,f"{year}-12")
            if not v:sc["missing"]+=1;continue
            public=record["metrics"][k].get("available_on")
            try:d=date.fromisoformat(public)
            except (TypeError,ValueError):d=None
            eligible=bool(d and date(year,12,31)<=d<=cutoff)
            specialists.append({"ticker":r["ticker"],"metric":k,"weight":w,**v,"available_on":public,"frozen_eligible":eligible})
            sc["direct_source_available"]+=1
            if eligible and k in FINANCIAL_MODELS[model]:
                r["metrics"][k]=obs(v["value"],"|".join(v["signature"]),f"{year}-12-31",public,v["source_ref"],not FINANCIAL_MODELS[model][k]["higher_is_better"],k)
                sc["frozen_admitted"]+=1
    result=evaluate(p);result["point_in_time_verified"]=False
    before=summary(baseline);after=summary(result);factors=factor_gaps(result);basef=factor_gaps(baseline)
    financial_gaps={}
    for k,w in (("roe",5),("roa",3),("margin",4),("stability",4),("cash",4)):
        rows=[r for r in result["records"] if not r["excluded"]];n=sum(r["base"]["detail"][k]["points"] is not None for r in rows)
        financial_gaps[k]={"weight":w,"scored":n,"eligible":len(rows),"missing":len(rows)-n,"coverage_pct":100*n/len(rows)}
    report={"before":before,"after":after,"industry_before":basef["base"]["industry_relative"]["coverage_pct"],"industry_after":factors["base"]["industry_relative"]["coverage_pct"],"valuation_after":factors["base"]["valuation"]["coverage_pct"],"computed":dict(c),"missing":dict(missing),"specialists":dict(sc),"financial_gaps":financial_gaps,"financial_missing_reasons":factors["base"]["financial"]["missing"],"release_gate":"not_verified","note":"Approved simplified weights and same KSIC two-digit fallback; no broad unverified groups. CSM growth and missing specialist sources remain missing. Frozen baseline unchanged."}
    for n,v in (("summary.json",report),("observations.json",p),("final-leading.json",result),("specialist_inventory.json",specialists)):write(out/n,v)
    print("SIMPLIFIED INDUSTRY SUMMARY",json.dumps({k:v for k,v in report.items() if k not in ("before","after")},ensure_ascii=False),flush=True)
    print("SIMPLIFIED INDUSTRY BASE",before["base_weighted_coverage_pct"],after["base_weighted_coverage_pct"],flush=True)
if __name__=="__main__":main()
