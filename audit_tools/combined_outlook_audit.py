"""Run combined candidate on all 300; external evidence remains separate."""
import sys,json
from pathlib import Path
from datetime import date
sys.path.insert(0,"scripts")
from outlook_candidate import score,WEIGHTS
from outlook_combined_candidate import combined
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def main():
    u=read("replay-source/universe.json");asof=date.fromisoformat(u["asof"])
    market={x["ticker"]:x for x in read("data/history/"+asof.strftime("%Y%m%d")+".json")}
    ledger=read("data/analyst_reports.json")["reports"]
    forecasts=read("data/verified_forward_forecasts.json").get("records",[]) if Path("data/verified_forward_forecasts.json").exists() else []
    own={r["ticker"]:r for r in read("audit-own-forecast/records.json")}
    gates=read("audit-own-forecast/summary.json")["backtest"]
    rows=[]
    assert len(u["stocks"])==300
    for x in u["stocks"]:
        t=x["ticker"];m=market.get(t,{})
        close=m.get("close") if m.get("market_cap")==x.get("market_cap") else None
        ext=score(dict(x,close=close),ledger,asof,forecasts)
        rows.append({"name":x["name"],**combined(ext,own.get(t),gates,asof,t)})
    metrics={k:{"external":sum(r["detail"][k]["observed"] for r in rows),"own_model":sum(r["detail"][k]["status"]=="own_model_candidate" for r in rows),"missing":sum(r["detail"][k]["points"] is None for r in rows),"policy_zero":sum(r["detail"][k]["status"]=="missing_zero_policy" for r in rows)} for k in WEIGHTS}
    summary={"universe":300,"weights":WEIGHTS,"field_counts":metrics,"backtest":gates,
      **{k:round(sum(r[k] for r in rows)/300,2) for k in ("external_observed_pct","own_model_coverage_pct","evidence_plus_model_pct","policy_calculation_pct")},
      "full_candidate_count":sum(r["full_policy_score_available"] for r in rows),"official":0,"release_gate":"not_verified",
      "warning":"Own model points count only in experimental forecast slots, never as external evidence; one-year retrospective backtest and scoring calibration need independent validation."}
    out=Path("audit-combined-outlook");out.mkdir(exist_ok=True)
    for path,v in (("records.json",rows),("summary.json",summary)):
        (out/path).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False))
    print("COMBINED OUTLOOK SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
