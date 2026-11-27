"""Offline score replay of direct Naver data and corrected three-year CAGR.

Do not overwrite frozen observations or mix peer distributions across source
definitions. Union coverage is a diagnostic, not a same-date overall score.
"""
import json
from pathlib import Path
from collections import Counter,defaultdict
from final_leading_model import finite,percentile,evaluate
from fundamental_candidate import profit_change
from leading_fundamental_inputs import summary
FIN={"roe":5,"roa":3,"margin":4,"stability":4,"cash":4}
GROW={"sales_growth":5,"op_growth":7,"net_growth":5,"sales_cagr":3}
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
def direct_growth(record):
    levels=record.get("annual_actuals",{});y=int(record["year"]);out={}
    for label,k in (("sales","sales_growth"),("op","op_growth"),("net","net_growth")):
        a,b=[levels.get(label,{}).get(str(i)) for i in (y-1,y)]
        if not finite(a) or not finite(b):continue
        if label=="sales":
            if a>0 and b>=0:out[k]=100*(b/a-1)
        else:out[k]=profit_change(b,a)
    ss=[levels.get("sales",{}).get(str(i)) for i in range(y-3,y+1)]
    if all(finite(v) and v>0 for v in ss):out["sales_cagr"]=100*((ss[-1]/ss[0])**(1/3)-1)
    return out
def direct_financial(record,model):
    vals={}
    for k in FIN:
        x=record.get("fields",{}).get(k,{}).get("value")
        if not finite(x):continue
        if k in ("stability","cash") and model not in (None,"operating_holding"):continue
        if k=="stability" and x<0:continue
        vals[k]=x
    return vals
def scope_label(record):
    s=str(record.get("provider_basis") or "").strip()
    if not s:return "provider_scope_unspecified"
    return s
def main():
    out=Path("audit-leading-direct-fundamental-replay");out.mkdir(exist_ok=True)
    payload=read("cagr/observations.json");baseline=evaluate(payload)
    old={r["ticker"]:r["base"]["detail"] for r in baseline["records"] if not r["excluded"]}
    targets={r["ticker"]:r for r in payload["stocks"] if not r.get("excluded")}
    growth={r["ticker"]:r for r in read("growth/records.json")}
    financial={r["ticker"]:r for r in read("finance/records.json")}
    groups=defaultdict(list);values={};counts=Counter()
    for t,row in targets.items():
        model=row.get("financial_model");v={}
        for family,record,vals in (("growth",growth.get(t,{}),direct_growth(growth[t]) if t in growth else {}),("financial",financial.get(t,{}),direct_financial(financial.get(t,{}),model))):
            for k,x in vals.items():
                if not finite(x) or not record.get("observed_at"):continue
                basis=(family,model,record["year"],scope_label(record),k)
                groups[basis].append(x)
                v[k]={"value":x,"basis":list(basis),"source_ref":record["source_ref"],"observed_at":record["observed_at"],"definition":"total_net_income" if k=="net_growth" else k}
        values[t]=v
    result=[];scored=Counter();gaps=Counter();strict=Counter()
    for t,v in values.items():
        slots={}
        for k,x in v.items():
            peers=groups[tuple(x["basis"])]
            q=percentile(x["value"],peers,k=="stability")
            if q is None:continue
            pts=(FIN.get(k) or GROW[k])*q
            slots[k]={**x,"points":round(pts,6),"peer_count":len(peers)}
            scored[k]+=1
            if old[t][k]["points"] is None:
                gaps[k]+=1
                # Parent-attributable vs total earnings not silently interchanged.
                if k!="net_growth":strict[k]+=1
        result.append({"ticker":t,"direct_scores":slots})
    n=len(targets)
    def report(weights):
        total=sum(weights.values())*n
        count={k:sum(old[t][k]["points"] is not None for t in targets) for k in weights}
        cv=lambda d:100*sum(w*d[k] for k,w in weights.items())/total
        return {"baseline_scored":count,"direct_scored":{k:scored[k] for k in weights},"direct_gap_scored":{k:gaps[k] for k in weights},"baseline_coverage_pct":cv(count),"provider_only_coverage_pct":cv(scored),"union_diagnostic_coverage_pct":cv(count)+cv(gaps),"union_without_total_net_substitution_pct":cv(count)+cv(strict)}
    s={"target_count":n,"frozen_source_replay_base_pct":summary(baseline)["base_weighted_coverage_pct"],"financial":report(FIN),"growth":report(GROW),"official_integrated":False,"note":"Actual candidate points calculated against same-source same-model peers, with declared provider scope retained. Unknown scope is provisional, not confirmed CFS/OFS. Union is coverage only, not a same-date integrated ranking. Total net income is not silently substituted for parent-attributable income. No cross-provider verification."}
    write(out/"summary.json",s);write(out/"records.json",result);print("DIRECT FUNDAMENTAL SCORE REPLAY",json.dumps(s,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
