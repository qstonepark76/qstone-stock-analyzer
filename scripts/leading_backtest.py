"""Point-in-time candidate performance evaluator. Never infers historical ranks.
Input is a verified common-calendar panel of adjusted open/close prices and
market index levels plus immutable final-model snapshots. Empty results are
explicit, and a missing constituent invalidates the entire cohort return.
"""
import argparse,json
from pathlib import Path
from statistics import mean
from final_leading_model import finite,VERSION

HORIZONS={"1w":5,"1m":20,"3m":60}
STRATEGIES=("base_top15","leading_top10","combined_top15")
def positive(x):return finite(x) and x>0

def test(snapshots,panel,cost_bps=30):
    if not finite(cost_bps) or not 0<=cost_bps<10000:raise ValueError("invalid costs")
    days=panel["sessions"]
    if days!=sorted(set(days)):raise ValueError("invalid calendar")
    if panel.get("verified") is not True or panel.get("basis")!="corporate_action_adjusted_ohlc":raise ValueError("adjusted price panel required")
    if len({s["asof"] for s in snapshots})!=len(snapshots):raise ValueError("duplicate snapshot")
    prices=panel["prices"];bench=panel["benchmark"]
    results=[]
    for snap in snapshots:
        if snap.get("model_version")!=VERSION or snap.get("point_in_time_verified") is not True:continue
        d=snap["asof"]
        if d not in days:continue
        i=days.index(d);entry=i+1
        for strategy in STRATEGIES:
            tickers=snap.get(strategy,[])
            if len(tickers)!=len(set(tickers)):raise ValueError("duplicate recommendation")
            for label,h in HORIZONS.items():
                row={"asof":d,"strategy":strategy,"horizon":label,"selected":len(tickers),"status":"no_candidates"}
                results.append(row)
                if not tickers:continue
                end=i+h
                if end>=len(days):row["status"]="not_mature";continue
                period=days[entry:end+1]
                if not period:row["status"]="not_mature";continue
                b0=bench.get(period[0],{}).get("open");b1=bench.get(period[-1],{}).get("close")
                if not positive(b0) or not positive(b1):row["status"]="missing_benchmark";continue
                starts={t:prices.get(t,{}).get(period[0],{}).get("open") for t in tickers}
                if not all(positive(v) for v in starts.values()) or any(not positive(prices.get(t,{}).get(day,{}).get("close")) for t in tickers for day in period):
                    row["status"]="missing_constituent_or_delisting";continue
                cost=cost_bps/10000
                series=[mean(prices[t][day]["close"]/starts[t] for t in tickers)*(1-cost) for day in period]
                vals=[100*(prices[t][period[-1]]["close"]/starts[t]*(1-cost)-1) for t in tickers]
                market=100*(b1/b0-1)
                peak=1;dd=0
                for v in series:
                    peak=max(peak,v);dd=min(dd,v/peak-1)
                row.update(status="evaluated",entry=period[0],exit=period[-1],net_return_pct=100*(series[-1]-1),benchmark_pct=market,
                    excess_pct=mean(vals)-market,win_rate_pct=100*sum(v>0 for v in vals)/len(vals),
                    outperform_rate_pct=100*sum(v>market for v in vals)/len(vals),cohort_mdd_pct=100*dd)
    summary={}
    for strategy in STRATEGIES:
        summary[strategy]={}
        for label in HORIZONS:
            cohort=[r for r in results if r["strategy"]==strategy and r["horizon"]==label]
            valid=[r for r in cohort if r["status"]=="evaluated"]
            summary[strategy][label]={"evaluated_cohorts":len(valid),"total_cohorts":len(cohort),
                **{k:mean(r[k] for r in valid) if valid else None for k in ("net_return_pct","excess_pct","win_rate_pct","outperform_rate_pct")},
                "worst_cohort_mdd_pct":min((r["cohort_mdd_pct"] for r in valid),default=None)}
    return {"status":"evaluated" if any(r["status"]=="evaluated" for r in results) else "no_verified_mature_cohorts",
            "cost_bps_roundtrip":cost_bps,"summary":summary,"cohorts":results,
            "note":"Equal-weight buy at next session open; no rebalancing within cohort. Cohort MDD is not continuous portfolio MDD. Missing/delisted names block cohort; report exclusions before interpreting. Price returns, not dividend total returns."}

def main():
    p=argparse.ArgumentParser();p.add_argument("snapshots",type=Path);p.add_argument("panel",type=Path);p.add_argument("out",type=Path);p.add_argument("--cost-bps",type=float,default=30)
    a=p.parse_args()
    result=test(json.loads(a.snapshots.read_text()),json.loads(a.panel.read_text()),a.cost_bps)
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
if __name__=="__main__":main()
