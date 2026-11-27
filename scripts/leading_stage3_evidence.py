"""Stage 3 offline evidence admission review. No provider calls or production writes."""
import json
from pathlib import Path
from collections import Counter
from datetime import date
from final_leading_model import evaluate,finite,SPECIAL_RELATIVE
from leading_reuse_stage1 import known,obs
from leading_fundamental_inputs import summary
from financial_industry import load_financial_observations,comparable_observation,FINANCIAL_MODELS

def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")

def review(payload,ledger,market,financial,prior):
    asof=date.fromisoformat(payload["asof"]);period="2025-12"
    if market["as_of"]!=payload["asof"]:raise ValueError("market date mismatch")
    # Only use explicitly basis-verified price targets. A report's target
    # currency/share basis and contemporaneous close must both be established.
    from outlook_candidate import broker_evidence,weighted
    closes={r["ticker"]:r["close"] for r in market["rows"] if finite(r.get("close")) and r["close"]>0}
    reports=[r for r in ledger if known(r,asof) and r.get("target_price_basis_verified") is True and r.get("verification_method") and str(r.get("source_url","")).startswith("https://")]
    counts=Counter();blocked=Counter();special=[];forecast=[]
    old={r["ticker"]:r for r in prior}
    for row in payload["stocks"]:
        if row.get("excluded"):continue
        t=row["ticker"];model=row.get("financial_model")
        if model in SPECIAL_RELATIVE:
            record=financial.get(t,{})
            for k in SPECIAL_RELATIVE[model]:
                v=comparable_observation(record,k,model,period)
                if not v:blocked["specialist_source_or_definition_missing"]+=1;continue
                raw=record["metrics"][k]
                # Existing FISIS archives identify annual reference period,
                # but do not by themselves prove actual first publication date.
                public=raw.get("available_on")
                try:valid=date.fromisoformat(period+"-31")<=date.fromisoformat(public)<=asof
                except (TypeError,ValueError):valid=False
                special.append({"ticker":t,"model":model,"metric":k,"value":v["value"],"signature":v["signature"],"source_ref":v["source_ref"],"available_on":public,"admitted":valid})
                if not valid:blocked["specialist_publication_date_unverified"]+=1;continue
                o=obs(v["value"],"|".join(v["signature"]),period+"-31",public,v["source_ref"],not FINANCIAL_MODELS[model][k]["higher_is_better"])
                row["metrics"][k]=o;counts["specialist_admitted"]+=1
        # Reuse previously validated own-forecast research as a separate
        # diagnostic, NOT as an independent broker consensus or a new score.
        d=old.get(t,{}).get("detail",{})
        for k,v in d.items():
            if v.get("status")!="own_model_candidate":continue
            forecast.append({"ticker":t,"metric":k,"value":v.get("value"),"status":"separate_model_candidate","source_kind":"qstone_model_forecast","backtest":v.get("backtest"),"source_ref":"GitHub Actions run 45817314640"})
            counts["own_model_slots_retained"]+=1
        if t not in closes:continue
        evidence=broker_evidence({"ticker":t,"close":closes[t]},reports,asof)
        for k,key in (("upside","upside"),("revision","target_revision")):
            ev=evidence[k]
            # Minimum three independent brokers and like-for-like verified
            # target-price basis. Do not use arbitrary prior report dates as 30d.
            if len({b for _,_,b,_ in ev})<3:blocked[k+"_minimum_brokers"]+=1;continue
            value=weighted([(v,w) for v,w,_,_ in ev])
            if not finite(value):continue
            row["metrics"][key]=obs(value,"broker recency weighted verified comparable target basis",payload["asof"],payload["asof"],"; ".join(sorted({u for _,_,_,u in ev})))
            counts[key+"_admitted"]+=1
    return dict(counts),dict(blocked),special,forecast

def main():
    root=Path("audit-leading-stage3");root.mkdir(exist_ok=True)
    payload=read("audit-leading-reuse/observations.json")
    before=summary(evaluate(payload))
    asof=payload["asof"]
    ledger=read("reuse-external/data/analyst_reports.json")["reports"]
    # Dedup without selecting a conflicting report arbitrarily.
    grouped={}
    for r in read("data/analyst_reports.json")["reports"]+ledger:
        key=tuple(r.get(k) for k in ("ticker","broker","published_at","source_url"))
        if key not in grouped:grouped[key]=r
        elif grouped[key] is not None and any(grouped[key].get(k)!=r.get(k) for k in ("rating","target_price","previous_target_price","target_price_basis_verified")):grouped[key]=None
    ledger=[r for r in grouped.values() if r]
    market={"as_of":asof,"rows":read("data/history/"+asof.replace("-","")+".json")}
    counts,blocked,special,forecast=review(payload,ledger,market,load_financial_observations(period="2025-12"),read("reuse-forecast/records.json"))
    result=evaluate(payload);result["point_in_time_verified"]=False
    report={"asof":asof,"before":before,"after":summary(result),"counts":counts,"blocked":blocked,
            "regulatory_candidate_observations":len(special),"own_model_candidate_observations":len(forecast),
            "status":"candidate_preflight","stage2_dependency":"Stage 2 market audit must complete before final merge."}
    for name,data in (("summary.json",report),("observations.json",payload),("specialist_candidates.json",special),("own_forecast_candidates.json",forecast)):
        write(root/name,data)
    print("STAGE3 REUSE PREFLIGHT",json.dumps({k:v for k,v in report.items() if k not in ("before","after")},ensure_ascii=False),flush=True)
    print("STAGE3 BASE COVERAGE",before["base_weighted_coverage_pct"],report["after"]["base_weighted_coverage_pct"],flush=True)
if __name__=="__main__":main()
