"""Direct specialist ratio scoring from archived public FISIS observations.
Use all known independent listed peers, not only the top-300 universe.
No cross-provider value verification or historical backfill.
"""
import json
from pathlib import Path
from collections import Counter,defaultdict
from final_leading_model import SIMPLIFIED_SPECIAL,percentile
from financial_industry import load_financial_observations,comparable_observation,FINANCIAL_MODELS,ISSUER_MODELS
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
def main():
    out=Path("audit-leading-specialist-direct");out.mkdir(exist_ok=True)
    payload=read("cagr/observations.json");year=int(read("replay-source/report.json")["year"]);period=f"{year}-12"
    source=load_financial_observations(period=period)
    targets={r["ticker"]:r["financial_model"] for r in payload["stocks"] if not r.get("excluded") and r.get("financial_model") in SIMPLIFIED_SPECIAL}
    groups=defaultdict(list);values={};stats=Counter();missing=Counter()
    for t,model in ISSUER_MODELS.items():
        record=source.get(t,{})
        for k in SIMPLIFIED_SPECIAL.get(model,{}):
            x=comparable_observation(record,k,model,period)
            if not x:continue
            # Same economic definition, entity scope and period; do not require
            # agreement with another provider. One issuer only once per group.
            sig=(model,k,*x["signature"])
            groups[sig].append((t,x["value"]));values[t,k]=(sig,x)
    rows=[];model_stats=defaultdict(Counter)
    for t,model in targets.items():
        details={}
        for k,w in SIMPLIFIED_SPECIAL[model].items():
            stats["expected_slots"]+=1;stats["expected_weight"]+=w
            model_stats[model]["expected_slots"]+=1
            found=values.get((t,k))
            if not found:
                missing[model+"|"+k+"|source_missing"]+=1;continue
            sig,x=found;peers=groups[sig]
            stats["observed_slots"]+=1;stats["observed_weight"]+=w
            model_stats[model]["observed_slots"]+=1
            direction=FINANCIAL_MODELS.get(model,{}).get(k,{}).get("higher_is_better",True)
            q=percentile(x["value"],[v for _,v in peers],not direction)
            details[k]={**x,"weight":w,"peer_count":len(peers),"peer_tickers":[i for i,_ in peers],"points_candidate":round(w*q,6) if q is not None else None}
            if q is None:missing[model+"|"+k+"|peer_shortage"]+=1;continue
            stats["scored_slots"]+=1;stats["scored_weight"]+=w
            model_stats[model]["scored_slots"]+=1
        rows.append({"ticker":t,"model":model,"details":details})
    s={"target_issuers":len(targets),"known_listed_source_issuers":len(source),"period":period,"stats":dict(stats),"by_model":{k:dict(v) for k,v in model_stats.items()},"missing":dict(missing),"specialist_weighted_coverage_pct":100*stats["scored_weight"]/stats["expected_weight"] if stats["expected_weight"] else None,"official_integrated":False,"note":"Current-source candidate scores; first publication date not asserted. Existing source normalization retained. Missing specialist ratios remain missing. No subsidiary/parent mixing, no relaxed minimum peer count, no old snapshot mutation."}
    write(out/"summary.json",s);write(out/"records.json",rows);print("SPECIALIST DIRECT REPLAY",json.dumps(s,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
