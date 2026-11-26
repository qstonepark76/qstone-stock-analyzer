"""Offline deterministic coverage improvement with actual saved v1 evidence.
Do not redo the API fetch or prediction tests for identical inputs.
"""
import sys,json
from pathlib import Path
from datetime import date
sys.path.insert(0,"scripts")
from collect import PREFERRED_SHARE_PARENT
from forecast_reuse import extend_loss,share_issuer
from outlook_candidate import score,WEIGHTS
from outlook_combined_candidate import combined
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def main():
    u=read("replay-source/universe.json");a=read("replay-source/report.json")
    asof=date.fromisoformat(u["asof"])
    source={r["ticker"]:r for r in a["records"]}
    gaps=read("source-gaps/report.json")["records"]
    prior={r["ticker"]:r for r in read("prior-own/audit-own-forecast/records.json")}
    gates=read("prior-own/audit-own-forecast/summary.json")["backtest"]
    models,links=share_issuer({t:extend_loss(r) for t,r in prior.items()},source,gaps,PREFERRED_SHARE_PARENT)
    ledger=read("prior-external/data/analyst_reports.json")["reports"]
    market={r["ticker"]:r for r in read("data/history/"+asof.strftime("%Y%m%d")+".json")}
    rows=[];missing=[];added={}
    for x in u["stocks"]:
        t=x["ticker"];m=market.get(t,{})
        ext=score(dict(x,close=m.get("close") if m.get("market_cap")==x.get("market_cap") else None),ledger,asof)
        old=combined(ext,prior.get(t),gates,asof,t)
        r=combined(ext,models.get(t),gates,asof,t)
        for k,d in r["detail"].items():
            if d["status"]=="own_model_candidate":
                ev=d.get("model_evidence",{})
                if ev.get("change_basis")=="symmetric_profit_change":
                    # bounded directional score, separate candidate calibration
                    d["points"]=round(max(0,min(1,.5+ev["value"]/400)),4)
                    d["change_basis"]=ev["change_basis"]
                if t in links:d["issuer_forecast_reference"]=links[t]
                if old["detail"][k]["points"] is None:added[k]=added.get(k,0)+1
            if d["points"] is None:
                missing.append({"ticker":t,"name":x["name"],"metric":k,"source_status":source[t]["status"],"corp_code":source[t].get("corp_code"),"scope":source[t].get("scope"),"had_saved_model":t in prior,"had_saved_current":bool(prior.get(t,{}).get("raw_current")),"had_saved_previous":bool(prior.get(t,{}).get("raw_previous"))})
        r["points_out_of_10"]=round(sum(d["points"] or 0 for d in r["detail"].values()),4)
        rows.append({"name":x["name"],**r})
    counts={k:{"external":sum(r["detail"][k]["observed"] for r in rows),"own_model":sum(r["detail"][k]["status"]=="own_model_candidate" for r in rows),"missing":sum(r["detail"][k]["points"] is None for r in rows),"policy_zero":sum(r["detail"][k]["status"]=="missing_zero_policy" for r in rows)} for k in WEIGHTS}
    summary={"universe":len(rows),"issuer_links":links,"added_slots":added,"field_counts":counts,"own_forecast_slot_pct":round(sum(v["own_model"] for v in counts.values())/900*100,2),"full_candidate_count":sum(r["full_policy_score_available"] for r in rows),"official":0,"release_gate":"not_verified",**{k:round(sum(r[k] for r in rows)/len(rows),2) for k in ("external_observed_pct","own_model_coverage_pct","evidence_plus_model_pct","policy_calculation_pct")}}
    out=Path("audit-forecast-reuse");out.mkdir(exist_ok=True)
    for name,v in (("records.json",rows),("summary.json",summary),("missing.json",missing),("models.json",models)):
        (out/name).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False))
    print("FORECAST REUSE SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
