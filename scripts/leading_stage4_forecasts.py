"""Stage 4 source inventory, old artifacts first. No automatic source admission."""
import json
from pathlib import Path
from collections import Counter
from datetime import date
from leading_reuse_stage1 import known
from leading_forecast_vintages import valid,add_signals
from leading_fundamental_inputs import summary
from final_leading_model import evaluate
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
def main():
    payload=read("audit-leading-stage3/observations.json")
    asof=date.fromisoformat(payload["asof"])
    sources=[Path("data/analyst_reports.json"),Path("reuse-external/data/analyst_reports.json"),Path("reuse-targeted/data/analyst_reports.json")]
    reports={};conflicts=set()
    for path in sources:
        for r in read(path)["reports"]:
            key=tuple(r.get(k) for k in ("ticker","broker","published_at","source_url"))
            if not all(key):continue
            if key in reports and any(reports[key].get(k)!=r.get(k) for k in ("rating","target_price","previous_target_price","target_price_basis_verified")):conflicts.add(key)
            elif key not in reports:reports[key]=r
    ledger=[v for k,v in reports.items() if k not in conflicts]
    known_reports=[r for r in ledger if known(r,asof)]
    vintage_rows=[r for r in ledger if valid(r,asof)]
    # Existing ledgers lack certified monetary units, time-stamped comparable
    # fiscal vintages and price adjustment basis. Do not reconstruct them.
    # Optional reviewed ledger is admitted only with explicit selection.
    reviewed=Path("data/verified_forecast_vintages.json")
    selection={}
    if reviewed.exists():
        data=read(reviewed);vintage_rows.extend(r for r in data["records"] if valid(r,asof));selection=data.get("selection",{})
    accepted=add_signals(payload,vintage_rows,selection)
    guidance=read("reuse-guidance/records.json")
    target_pairs=read("reuse-targeted/audit-targeted-outlook/revision-candidates.json")
    own=read("audit-leading-stage3/own_forecast_candidates.json")
    result=evaluate(payload);result["point_in_time_verified"]=False
    s=summary(result)
    s["source_inventory"]={"unique_report_rows":len(ledger),"conflicting_keys":len(conflicts),
      "verified_by_frozen_date":len(known_reports),"report_tickers":len({r["ticker"] for r in known_reports}),
      "existing_target_pair_candidates":len(target_pairs),"guidance_candidate_documents":len(guidance),
      "guidance_tables_received":sum(bool(r.get("candidate_tables")) for r in guidance),
      "own_model_slots_retained":len(own),"valid_external_vintage_records":len(vintage_rows),
      "matched_issuer_metric_series":len(accepted)}
    s["status"]="partial_candidate_only"
    s["blocking_fields"]=["independent operating profit forecast vintages","announcement-time earnings surprise","matched target price adjustment basis","industry index total returns","historical adjusted price and verified recommendation snapshots"]
    out=Path("audit-leading-stage4");out.mkdir(exist_ok=True)
    for name,data in (("summary.json",s),("observations.json",payload),("final-leading.json",result),("accepted_vintages.json",accepted)):
        write(out/name,data)
    print("STAGE4 FORECAST INVENTORY",json.dumps(s["source_inventory"],ensure_ascii=False),flush=True)
    print("STAGE4 COVERAGE",s["base_weighted_coverage_pct"],s["leading_weighted_coverage_pct"],flush=True)
if __name__=="__main__":main()
