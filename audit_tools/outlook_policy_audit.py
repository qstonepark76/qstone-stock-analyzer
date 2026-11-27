"""Read-only comparison of the approved outlook policy on the frozen universe."""
import json
import sys
from pathlib import Path
from datetime import date
from collections import Counter
sys.path.insert(0,"scripts")
from outlook_candidate import score,WEIGHTS
def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))
def main():
    u=read("replay-source/universe.json")
    asof=date.fromisoformat(u["asof"])
    snapshot=read("data/history/"+asof.strftime("%Y%m%d")+".json")
    market={r["ticker"]:r for r in snapshot}
    ledger=read("data/analyst_reports.json")["reports"]
    # No unverified earnings estimates or historical growth placeholders.
    forecasts=[]
    f=Path("data/verified_forward_forecasts.json")
    if f.exists():
        forecasts=read(f).get("records",[])
    records=[]
    assert len(u["stocks"])==300 and len({r["ticker"] for r in u["stocks"]})==300
    for x in u["stocks"]:
        m=market.get(x["ticker"],{})
        close=m.get("close") if m.get("market_cap")==x.get("market_cap") else None
        records.append({"ticker":x["ticker"],"name":x["name"],**score(dict(x,close=close),ledger,asof,forecasts)})
    n=len(records)
    fields={k:{"observed":sum(r["detail"][k]["observed"] for r in records),
               "policy_zero":sum(r["detail"][k]["status"]=="missing_zero_policy" for r in records)}
            for k in WEIGHTS}
    summary={"asof":u["asof"],"count":n,"ledger_reports":len(ledger),"forecast_records":len(forecasts),
             "broker_policy_calculation_count":sum(r["policy_calculation_pct"]>=70 for r in records),
             "any_broker_evidence_count":sum(r["broker_evidence_count"]>0 for r in records),
             "any_observed_count":sum(r["observed_coverage_pct"]>0 for r in records),
             "full_policy_score_count":sum(r["full_policy_score_available"] for r in records),
             "full_evidence_count":sum(r["all_evidence_observed"] for r in records),
             "mean_observed_coverage_pct":round(sum(r["observed_coverage_pct"] for r in records)/n,2),
             "mean_policy_calculation_pct":round(sum(r["policy_calculation_pct"] for r in records)/n,2),
             "field_counts":fields,"official":0,"release_gate":"not_verified",
             "warning":"Broker missing zero policy is not observed evidence. Forecast fields remain missing without verified forward evidence. Target revisions require confirmed corporate-action basis; score curves are experimental."}
    out=Path("audit-outlook-policy")
    out.mkdir(exist_ok=True)
    (out/"records.json").write_text(json.dumps(records,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print("OUTLOOK POLICY SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__":
    main()
