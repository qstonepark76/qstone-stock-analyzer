"""Replay archived Naver provider values with the approved hierarchical peer rule.
No provider requests, cross-source verification, or historical score mutation.
Sector fallback is a diagnostic only: broad house sectors are not yet
established as equivalent business models.
"""
import json
from pathlib import Path
from collections import Counter,defaultdict
from datetime import datetime
from final_leading_model import percentile,finite,MIN_PEERS,SIMPLIFIED_SPECIAL
from collect import classify_industry_code
from leading_direct_valuation import FIELDS
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
def group_keys(row,k,r):
    code=str(row.get("industry_code") or "")
    model=row.get("financial_model")
    basis=r.get("basis_key")
    stamp=r.get("observed_at")
    if not isinstance(basis,str) or not basis or r.get("source")!="Naver" or not isinstance(stamp,str):return {}
    try:day=datetime.fromisoformat(stamp).date().isoformat()
    except ValueError:return {}
    if not finite(r.get("value")) or r["value"]<=0:return {}
    if not code.isdigit():return {}
    tail=(model,k,basis,day)
    keys={"exact":(code,*tail)}
    if model in (None,"operating_holding") and len(code)>=2:
        keys["parent"]=(code[:2],*tail)
        sector=classify_industry_code(code)
        if sector and sector!="금융":keys["sector_diagnostic"]=(sector,*tail)
    # Known regulated financial models are never compared to general
    # industrial companies; their business-model class is the fallback.
    if model in SIMPLIFIED_SPECIAL:keys["financial_model"]=(model,*tail)
    return keys
def evaluate_rows(rows):
    groups=defaultdict(list)
    for row in rows:
        for k,r in row.get("ratios",{}).items():
            for level,key in group_keys(row,k,r).items():
                groups[(level,key)].append(r["value"])
    c=Counter();results=[]
    for row in rows:
        if row.get("peer_only"):continue
        detail={}
        for k in FIELDS:
            r=row.get("ratios",{}).get(k,{})
            v=r.get("value");keys=group_keys(row,k,r)
            if finite(v):c[k+"_raw"]+=1
            item={"value":v,"source_ref":r.get("source_ref"),"observed_at":r.get("observed_at"),"basis":r.get("basis_key"),"points":None,"peer_level":None,"peer_count":0,"sector_diagnostic_points":None}
            for level in ("exact","parent","financial_model"):
                if level not in keys:continue
                vals=groups[(level,keys[level])]
                item["peer_count"]=max(item["peer_count"],len(vals))
                q=percentile(v,vals,True)
                if q is not None:
                    item.update(points=round(5*q,6),peer_level=level,peer_count=len(vals))
                    c[k+"_scored"]+=1;c[k+"_"+level]+=1
                    break
            if item["points"] is not None:
                item["sector_diagnostic_points"]=item["points"];c[k+"_diagnostic_scored"]+=1
            elif "sector_diagnostic" in keys:
                vals=groups[("sector_diagnostic",keys["sector_diagnostic"])]
                q=percentile(v,vals,True)
                if q is not None:
                    item["sector_diagnostic_points"]=round(5*q,6);c[k+"_diagnostic_scored"]+=1
                    item["sector_diagnostic_peer_count"]=len(vals)
            if item["points"] is None:
                item["status"]="데이터 없음" if not finite(v) else "0 또는 음수" if v<=0 else "비교기준/기업 부족"
                c[k+"_missing_"+item["status"]]+=1
            else:item["status"]="산출"
            detail[k]=item
        results.append({"ticker":row["ticker"],"industry_code":row.get("industry_code"),"financial_model":row.get("financial_model"),"valuation":detail})
    return dict(c),results
def main():
    out=Path("audit-leading-valuation-hierarchy");out.mkdir(exist_ok=True)
    original=read("direct/summary.json");rows=read("direct/records.json")
    if len({r["ticker"] for r in rows})!=len(rows):raise ValueError("duplicate ticker")
    c,records=evaluate_rows(rows);n=len(records)
    if n!=original["target_count"]:raise ValueError("target mismatch")
    raw=100*sum(c.get(k+"_raw",0) for k in FIELDS)/(2*n)
    cov=100*sum(c.get(k+"_scored",0) for k in FIELDS)/(2*n)
    diag=100*sum(c.get(k+"_diagnostic_scored",0) for k in FIELDS)/(2*n)
    s={"target_count":n,"peer_count":len(rows)-n,"source_observed_at":original["observed_at"],"raw_coverage_pct":raw,
       "prior_exact_coverage_pct":original["score_coverage_pct"],"hierarchy_score_coverage_pct":cov,"sector_diagnostic_coverage_pct":diag,
       "counts":c,"historical_scores_modified":False,"status":"current_provider_candidate_only",
       "note":"Same-day and same provider display basis; exact then KSIC two-digit parent, or same known financial model. Financial-model fallback is provisional because issuer group scope may differ. Broad house sector results are diagnostic only. No cross-validation or recomputation. Missing and loss-company PER remain missing."}
    write(out/"summary.json",s);write(out/"records.json",records);print("VALUATION HIERARCHY SUMMARY",json.dumps(s,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
