"""Merge separately collected vintage evidence and retain earlier candidate baseline."""
import sys,json
from pathlib import Path
from datetime import date
from collections import defaultdict,Counter
sys.path.insert(0,"scripts")
from outlook_candidate import score,WEIGHTS,curve
from outlook_combined_candidate import combined
from own_forecast_v2 import change,choose
from fundamental_candidate import transition
from forecast_extended_models import canonical
from forecast_reuse import FIELDS as METRICS
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def main():
    u=read("replay-source/universe.json");asof=date.fromisoformat(u["asof"])
    train=defaultdict(lambda:defaultdict(list));hold=defaultdict(lambda:defaultdict(list))
    inputs={};failures=[];expected=set();shards=set();selected_count=None
    for path in sorted(Path("batches").glob("*/batch.json")):
        b=read(path)
        assert b["shard"] not in shards and not (expected & set(b["expected"]))
        shards.add(b["shard"]);expected.update(b["expected"])
        assert selected_count in (None,b["selected_count"]);selected_count=b["selected_count"]
        inputs.update({t:{**v,"quarters":{int(q):r for q,r in v["quarters"].items()}} for t,v in b["inputs"].items()})
        failures+=b["failures"]
        for key,pool in (("train",train),("hold",hold)):
            for row in b[key]:
                for m,rs in row["models"].items():
                    pool[(row["group"],row["metric"],row["quarter"])][m].extend(rs)
    assert len(shards)==15 and len(expected)==selected_count
    gates={}
    # For earnings revision require same chosen model at both horizons.
    for g,k,q in sorted(train):
        if q!=3:continue
        min_n=20 if g.startswith("industrial|") else 5
        gate=choose(train[(g,k,3)],hold[(g,k,3)],min_n)
        if not gate:continue
        if k=="net":
            m=gate["model"]
            tr=train[(g,k,2)].get(m,[]);te=hold[(g,k,2)].get(m,[])
            n=len(te);err=sum(r["error"] for r in te)/n if n else None;base=sum(r["baseline_error"] for r in te)/n if n else None
            gate["q2_holdout"]={"n":n,"smape":err,"baseline":base}
            gate["candidate_pass"]=gate["candidate_pass"] and len(tr)>=min_n and n>=min_n and err<=base
        gates[g+"|"+k]=gate
    v1=read("reuse/models.json")
    baseg=read("prior-own/audit-own-forecast/summary.json")["backtest"]
    ledger=read("prior-external/data/analyst_reports.json")["reports"]
    market={r["ticker"]:r for r in read("data/history/"+asof.strftime("%Y%m%d")+".json")}
    result=[];added=Counter();replaced=Counter();symmetric=Counter();groups=defaultdict(Counter)
    for x in u["stocks"]:
        t=x["ticker"];m=market.get(t,{})
        ext=score(dict(x,close=m.get("close") if m.get("market_cap")==x.get("market_cap") else None),ledger,asof)
        r=combined(ext,v1.get(t),baseg,asof,t)
        # Apply the same separate loss calibration to the reused baseline.
        for f,d in r["detail"].items():
            ev=d.get("model_evidence",{})
            if d["status"]=="own_model_candidate" and ev.get("change_basis")=="symmetric_profit_change":d["points"]=round(max(0,min(1,.5+ev["value"]/400)),4)
        current=inputs.get(t)
        if current:
            g=current["group"];q=current["quarters"]
            for field,k in METRICS.items():
                if r["detail"][field]["observed"]:continue
                gate=gates.get(g+"|"+k,{})
                if gate.get("candidate_pass") is not True:continue
                model=gate["model"];now=q[3].get(k,{})
                c=now.get("models",{}).get(model)
                p=now.get("last")
                prev=None
                if k=="net":
                    prev=q[2].get(k,{})
                    if prev.get("currency")!=now.get("currency") or canonical(prev.get("account_id"))!=canonical(now.get("account_id")):continue
                    p=prev.get("models",{}).get(model)
                v=change(c,p,k!="sales")
                if v is None:continue
                value,basis=v
                d=r["detail"][field]
                # V2 selection is experimental; prior V1 score remains fallback
                # when newer candidate is not validated on its own group.
                if d["points"] is None:added[field]+=1
                else:replaced[field]+=1
                if basis=="symmetric_profit_change":symmetric[field]+=1
                points=round(max(0,min(1,.5+value/400)) if basis=="symmetric_profit_change" else curve(field,value),4)
                d.update({"points":points,"value":value,"observed":False,"status":"own_model_candidate","source_kind":"qstone_model_forecast","model_version":"v3_batch","change_basis":basis,"transition":transition(c,p) if k!="sales" else None,"current":now,"previous":prev,"model":model,"validation_group":g,"classification":current["classification"],"backtest":gate})
                groups[g][field]+=1
        d=r["detail"];observed=sum(WEIGHTS[k] for k in d if d[k]["observed"])
        own=sum(WEIGHTS[k] for k in d if d[k]["status"]=="own_model_candidate")
        calc=sum(WEIGHTS[k] for k in d if d[k]["points"] is not None)
        r.update({"name":x["name"],"points_out_of_10":round(sum(v["points"] or 0 for v in d.values()),4),"external_observed_pct":observed*10,"own_model_coverage_pct":own*10,"evidence_plus_model_pct":(observed+own)*10,"policy_calculation_pct":calc*10,"full_policy_score_available":calc==10})
        result.append(r)
    summary={"universe":300,"batch_count":len(shards),"targeted_issuers":len(expected),"v2_input_issuers":len(inputs),"gates":gates,"added_slots":dict(added),"replaced_slots":dict(replaced),"symmetric_changes":dict(symmetric),"v2_group_usage":{g:dict(v) for g,v in groups.items()},"failures":len(failures),
      "field_counts":{k:{"external":sum(r["detail"][k]["observed"] for r in result),"own_model":sum(r["detail"][k]["status"]=="own_model_candidate" for r in result),"missing":sum(r["detail"][k]["points"] is None for r in result),"policy_zero":sum(r["detail"][k]["status"]=="missing_zero_policy" for r in result)} for k in WEIGHTS},
      **{k:round(sum(r[k] for r in result)/300,2) for k in ("external_observed_pct","own_model_coverage_pct","evidence_plus_model_pct","policy_calculation_pct")},
      "own_forecast_slot_pct":round(sum(r["own_model_coverage_pct"] for r in result)/300/30*100,2),"full_candidate_count":sum(r["full_policy_score_available"] for r in result),"official":0,"release_gate":"not_verified","warning":"Mixed v1/v2 candidate only; V2 two-vintage and subgroup gates, proposed classifications, symmetric scoring curve and final independent point-in-time validation remain pending. No missing broker evidence counted as data."}
    out=Path("audit-forecast-batch-merged");out.mkdir(exist_ok=True)
    for name,v in (("records.json",result),("summary.json",summary),("failures.json",failures)):
        (out/name).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False))
    print("FORECAST BATCH MERGED SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
