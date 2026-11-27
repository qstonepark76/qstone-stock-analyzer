"""Separate research-only reuse of legacy own forecasts.
Never add forecasts to the verified external observations or official rankings.
Recompute candidate values from saved numeric evidence and receipt dates.
"""
import json,math
from datetime import date
from pathlib import Path
from collections import Counter,defaultdict
from final_leading_model import evaluate,finite,curve
from leading_fundamental_inputs import receipt_day,summary
from leading_reuse_stage1 import known
from outlook_candidate import broker_key
from forecast_extended_models import canonical
from own_forecast_v2 import change

FIELDS={"operating_profit_forecast_growth":"op_forecast_growth","earnings_forecast_revision":"earnings_revision"}
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")

def gate_ok(g,version,field,group):
    if g.get("candidate_pass") is not True:return False
    if version=="v3_batch":
        minimum=20 if str(group).startswith("industrial|") else 5
        if not str(group).strip():return False
        if not all(finite(g.get(k)) and g[k]>=minimum for k in ("training_n","holdout_n")):return False
        if not all(finite(g.get(k)) for k in ("holdout_smape","baseline_smape")) or g["holdout_smape"]>g["baseline_smape"]:return False
        if field=="earnings_revision":
            q=g.get("q2_holdout",{})
            if not finite(q.get("n")) or q["n"]<minimum or not all(finite(q.get(k)) for k in ("smape","baseline")) or q["smape"]>q["baseline"]:return False
        return True
    return finite(g.get("n")) and g["n"]>=20 and all(finite(g.get(k)) for k in ("smape","baseline_smape")) and g["smape"]<=g["baseline_smape"]

def verify_evidence(d,field,src,asof):
    if d.get("status")!="own_model_candidate" or d.get("source_kind")!="qstone_model_forecast" or d.get("issuer_forecast_reference"):return None,"not_independent_own_candidate"
    if src.get("status")!="source_received" or not src.get("corp_code") or src.get("scope") not in ("CFS","OFS"):return None,"issuer_or_scope"
    version=d.get("model_version","v1");group=d.get("validation_group","")
    if version=="v3_batch" and not str(group).endswith("|"+src["scope"]):return None,"group_scope"
    if not gate_ok(d.get("backtest",{}),version,field,group):return None,"legacy_gate"
    if version=="v3_batch":
        a=d.get("current") or {};b=d.get("previous") or {};model=d.get("model")
        if model!=d.get("backtest",{}).get("model"):return None,"model_mismatch"
        current=a.get("models",{}).get(model)
        previous=b.get("models",{}).get(model) if field=="earnings_revision" else a.get("last")
    else:
        ev=d.get("model_evidence") or {}
        a=ev.get("current") or ev;b=ev.get("previous") or {}
        current=a.get("estimate")
        previous=b.get("estimate") if field=="earnings_revision" else a.get("prior_year_actual")
    def receipts_ok(x):
        ar=x.get("annual_receipt");qr=x.get("quarter_receipt");ad=receipt_day(ar);qd=receipt_day(qr)
        return bool(ar in src.get("receipts",[]) and ad and qd and ad<=qd<=asof and qd.year==asof.year and x.get("currency") and x.get("account_id"))
    if not receipts_ok(a):return None,"receipt_or_account"
    if field=="earnings_revision":
        if not receipts_ok(b) or a["annual_receipt"]!=b["annual_receipt"] or a["currency"]!=b["currency"] or canonical(a["account_id"])!=canonical(b["account_id"]) or not receipt_day(b["quarter_receipt"])<receipt_day(a["quarter_receipt"]):return None,"vintage_mismatch"
    if not finite(current) or not finite(previous):return None,"missing_numeric_evidence"
    v=change(current,previous,True)
    if not v:return None,"invalid_change"
    value,basis=v
    # Legacy percent or symmetric loss-change must independently reconcile.
    if not finite(d.get("value")) or not math.isclose(value,d["value"],rel_tol=1e-7,abs_tol=1e-5):return None,"legacy_value_mismatch"
    return {"value":value,"basis":basis,"source_kind":"qstone_model_forecast","source_ref":"OpenDART receipts "+a["annual_receipt"]+" "+a["quarter_receipt"]+(" "+b["quarter_receipt"] if field=="earnings_revision" else ""),
        "model_version":version,"scope":src["scope"],"validation_group":group,"backtest":d["backtest"],"candidate_points":round(2*curve(field,value),6),"official":False},None

def asof_reports(ledgers,cutoff):
    """Filter by availability BEFORE conflict detection. Later enriched
    metadata cannot disqualify an earlier known report retroactively."""
    groups=defaultdict(list)
    for ledger in ledgers:
        for r in ledger:
            if not known(r,cutoff) or not r.get("verification_method") or not str(r.get("source_url","")).startswith("https://"):continue
            key=(r.get("ticker"),broker_key(r.get("broker")),r.get("published_at"),r.get("source_url"))
            if all(key):groups[key].append(r)
    chosen=[];conflicts=0
    for rows in groups.values():
        # Derived prior-target metadata may change without contradicting the
        # original report. It is NOT a primary observation and is ignored here.
        signatures={(r.get("rating"),r.get("target_price")) for r in rows}
        if len(signatures)!=1:conflicts+=1;continue
        chosen.append(min(rows,key=lambda r:r["verified_at"]))
    return chosen,conflicts

def main():
    out=Path("audit-leading-stage6");out.mkdir(exist_ok=True)
    payload=read("stage5/observations.json");asof=date.fromisoformat(payload["asof"])
    audit=read("replay-source/report.json")
    if audit["universe_asof"]!=payload["asof"]:raise ValueError("source date mismatch")
    sources={r["ticker"]:r for r in audit["records"]};prior={r["ticker"]:r for r in read("reuse-forecast/records.json")}
    if set(sources)!={r["ticker"] for r in payload["stocks"]} or set(prior)!=set(sources):raise ValueError("universe mismatch")
    baseline=evaluate(payload)
    details=[];counts=Counter();blocked=Counter();added_weight=0
    eligible=sum(not r.get("excluded") for r in payload["stocks"])
    for row in payload["stocks"]:
        if row.get("excluded"):continue
        t=row["ticker"]
        for legacy,field in FIELDS.items():
            if field in row["metrics"]:continue
            d=prior[t].get("detail",{}).get(legacy,{})
            v,reason=verify_evidence(d,field,sources[t],asof)
            if not v:blocked[field+"|"+reason]+=1;continue
            details.append({"ticker":t,"name":row["name"],"metric":field,**v})
            counts[field]+=1;added_weight+=2
    ledgers=[read(p)["reports"] for p in ("data/analyst_reports.json","reuse-external/data/analyst_reports.json","reuse-targeted/data/analyst_reports.json")]
    reports,conflicts=asof_reports(ledgers,asof)
    s=summary(baseline)
    s["scenario"]={"own_forecast_candidate_counts":dict(counts),"blocked":dict(blocked),
       "external_evidence_coverage_pct":s["base_weighted_coverage_pct"],
       "hypothetical_mixed_candidate_coverage_pct":s["base_weighted_coverage_pct"]+added_weight/eligible if eligible else None,
       "leading_coverage_unchanged_pct":s["leading_weighted_coverage_pct"],
       "eligible":eligible,"point_in_time_report_records":len(reports),"point_in_time_report_tickers":len({r["ticker"] for r in reports}),
       "true_asof_report_conflicts":conflicts,"status":"research_only_not_official",
       "note":"Legacy own estimates passed preliminary historical gates, not independent broker consensus or final backtest. No scores/ranks promoted and no 30-day signal substitution. Candidate curve not calibrated."}
    write(out/"summary.json",s);write(out/"own_forecast_scenario.json",details);write(out/"asof_report_inventory.json",reports)
    print("STAGE6 SCENARIO",json.dumps(s["scenario"],ensure_ascii=False),flush=True)
if __name__=="__main__":main()
