"""One per-issuer score ledger from completed candidate experiments.

Frozen official-model replay stays intact. Mixed-date coverage and provisional
subtotals are for integration diagnostics only, never ranks or final scores.
"""
import json
from pathlib import Path
from collections import Counter,defaultdict
from final_leading_model import finite
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
def index(path):
    rows=read(path);out={r["ticker"]:r for r in rows}
    if len(out)!=len(rows):raise ValueError("duplicate candidate ticker")
    return out
def candidate(slot,points,evidence,origin,reason,replace=False):
    if slot is None or (slot.get("points") is not None and not replace):return False
    if not finite(points) or not 0<=points<=slot["weight"]+1e-6:return False
    slot.update(points=round(points,6),status="후보 산출",source_ref=evidence.get("source_ref") or origin,origin=origin,provisional=True,qualification=reason,evidence=evidence)
    return True
def summarize_slots(slots):
    known=sum(z["weight"] for z in slots.values() if finite(z.get("points")))
    total=sum(z["weight"] for z in slots.values())
    points=sum(z["points"] for z in slots.values() if finite(z.get("points")))
    if total!=100:raise ValueError("model weights must total 100")
    return {"coverage_pct":known,"observed_points":round(points,6) if known else None,"missing_weight":total-known,
            "missing_slots":[k for k,z in slots.items() if not finite(z.get("points"))],
            "candidate_all_slots_filled":known==total,"final_score":None,"rank_eligible":False,"detail":slots}
def combine(base,leading):
    return {"coverage_pct":round(.6*base["coverage_pct"]+.4*leading["coverage_pct"],6),
            "observed_weighted_points":round(.6*(base["observed_points"] or 0)+.4*(leading["observed_points"] or 0),6),
            "candidate_all_slots_filled":base["candidate_all_slots_filled"] and leading["candidate_all_slots_filled"],
            "final_score":None,"rank_eligible":False}
def main():
    out=Path("audit-leading-full-score-preview");out.mkdir(exist_ok=True)
    frozen=read("base/final-leading.json")
    fundamentals=index("fundamental/records.json");valuation=index("valuation/records.json")
    specialty=index("specialty/records.json");outlook=index("outlook/records.json");leading=index("leading/records.json")
    rows=[r for r in frozen["records"] if not r["excluded"]];targets={r["ticker"] for r in rows}
    if len(targets)!=290 or any(set(z)!=targets for z in (fundamentals,valuation,outlook,leading)) or not set(specialty)<=targets:raise ValueError("source universe mismatch")
    stats=Counter();factors=defaultdict(Counter);records=[]
    for r in rows:
        t=r["ticker"]
        b={k:{**z,"origin":"frozen model replay","provisional":False,"snapshot_date":frozen["asof"]} for k,z in r["base"]["detail"].items()}
        l={k:{**z,"origin":"frozen model replay","provisional":False,"snapshot_date":frozen["asof"]} for k,z in r["leading"]["detail"].items()}
        for k,z in fundamentals[t]["direct_scores"].items():
            if k=="net_growth" and z.get("definition")=="total_net_income":continue
            if candidate(b.get(k),z["points"],z,"Naver fundamentals 46050303475","current provider scope may differ; not historical point-in-time"):stats["fundamental_added"]+=1
        for k,z in valuation[t]["valuation"].items():
            field={"per":"earnings_value","pbr":"book_value"}.get(k,k)
            if candidate(b.get(field),z.get("points"),z,"Naver valuation 46045769152","same-provider peer score; current acquisition, not frozen market date"):stats["valuation_added"]+=1
        for k,z in specialty.get(t,{}).get("slots",{}).items():
            if candidate(b.get(k),z.get("points_candidate"),z,"FISIS 46050749586","legal-entity peer candidate, not verified consolidated independence or historical availability"):stats["specialty_added"]+=1
        for k,z in outlook[t]["slots"].items():
            if k not in ("rating","upside","target_revision","op_forecast_growth","earnings_revision"):continue
            points=z.get("points_candidate",z.get("points_out_of_2"))
            if candidate(b.get(k),points,z,"report outlook 46051236237","2026-11-28 source candidate; market date differs from frozen replay",replace=True):stats["outlook_scored"]+=1
        for k,z in leading[t]["slots"].items():
            # Only actual 30-day matched target revisions; one-month display
            # aggregates are not the approved 30-day signal or broker breadth.
            if k!="target_revision_30d" or z.get("broker_count",0)<3:continue
            if candidate(l.get(k),z.get("points_candidate"),z,"30-day broker targets 46052441920","target corporate-action basis unverified; provisional only"):stats["leading_target_added"]+=1
        bs,ls=summarize_slots(b),summarize_slots(l);cs=combine(bs,ls)
        for model,slots in (("base",b),("leading",l)):
            for k,z in slots.items():
                f=factors[model+"|"+z["factor"]]
                f["weight_total"]+=z["weight"]
                if finite(z.get("points")):f["weight_scored"]+=z["weight"]
                else:stats[model+"|missing|"+k]+=1
        records.append({"ticker":t,"name":r["name"],"base":bs,"leading":ls,"combined":cs,"frozen_scores":{"base":r["base"]["score"],"leading":r["leading"]["score"],"combined":r["combined"]}})
    n=len(records)
    summary={"target_count":n,"frozen_asof":frozen["asof"],"candidate_snapshot_note":"mixed source dates; no official integration or ranks","source_runs":{"base":46051543687,"fundamental":46050303475,"valuation":46045769152,"specialty":46050749586,"outlook":46051236237,"leading":46052441920},
             "frozen_coverage_pct":{k:sum(r[k]["coverage_pct"] for r in rows)/n for k in ("base","leading")},
             "candidate_coverage_pct":{k:sum(r[k]["coverage_pct"] for r in records)/n for k in ("base","leading","combined")},
             "candidate_all_slots_filled":{k:sum(r[k]["candidate_all_slots_filled"] for r in records) for k in ("base","leading","combined")},
             "factor_coverage_pct":{k:100*v["weight_scored"]/v["weight_total"] for k,v in factors.items()},
             "counts":dict(stats),"official_final_score_count":0,"rank_eligible_count":0,"official_integrated":False,
             "note":"Per-issuer score evidence ledger with actual candidate points. Do not sum mixed dates into a final investment score. Missing slots not zero-filled or rescaled; total net income does not replace owner net income. Same-date market and source basis certification pending."}
    write(out/"summary.json",summary);write(out/"records.json",records);print("FULL SCORE PREVIEW",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
