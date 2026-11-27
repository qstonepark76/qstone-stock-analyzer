"""Approved v3.3 3/5-year strategy comparisons; no synthetic historical ranks."""
import argparse,json
from pathlib import Path
from datetime import date
from final_leading_model import VERSION,finite
from leading_backtest import test
SIZES=(5,10,15)
MIXES={"base":1.0,"leading":0.0,"combined_60_40":.6,"combined_70_30":.7,"combined_50_50":.5}
STRATEGIES=tuple(f"{k}_top{n}" for k in MIXES for n in SIZES)
FINAL_VERSION=VERSION+"-simplified-v1"
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
def rank(snapshot):
    if snapshot.get("model_version")!=FINAL_VERSION or snapshot.get("point_in_time_verified") is not True:return None
    # A complete historical universe and date-stamped source evidence must be
    # certified by the historical data builder, not inferred from current ranks.
    if snapshot.get("historical_universe_verified") is not True or not snapshot.get("historical_source_manifest"):return None
    rows=snapshot["records"];ts=[r["ticker"] for r in rows]
    if len(ts)!=300 or len(set(ts))!=300:raise ValueError("historical top300 universe required")
    out={"asof":snapshot["asof"],"model_version":VERSION,"point_in_time_verified":True}
    def val(r,weight):
        if r.get("excluded"):return None
        def get(k):
            x=r.get(k,{})
            v=x.get("score")
            return v if x.get("complete") is True and finite(v) and 0<=v<=100 else None
        a,b=get("base"),get("leading")
        if weight==1:return a
        if weight==0:return b
        return weight*a+(1-weight)*b if a is not None and b is not None else None
    for label,w in MIXES.items():
        scored=[(v,r["ticker"]) for r in rows if (v:=val(r,w)) is not None]
        ranked=[t for _,t in sorted(scored,key=lambda x:(-x[0],x[1]))]
        for n in SIZES:
            out[f"{label}_top{n}"]=ranked[:n] if len(ranked)>=n else []
    return out
def subtract_years(d,years):
    try:return d.replace(year=d.year-years)
    except ValueError:return d.replace(year=d.year-years,day=28)
def extended(snapshots,panel,end,years,cost_bps=30):
    if years not in (3,5):raise ValueError("3 or 5 years required")
    end=date.fromisoformat(end);start=subtract_years(end,years);split=subtract_years(end,1)
    selected=[r for s in snapshots if start<=date.fromisoformat(s["asof"])<=end and (r:=rank(s)) is not None]
    # Never use outcomes after test cutoff, even if later prices exist in panel.
    panel={**panel,"sessions":[d for d in panel["sessions"] if date.fromisoformat(d)<=end]}
    result=test(selected,panel,cost_bps,strategies=STRATEGIES)
    # Freeze weights before validation; purge cohorts crossing holdout boundary.
    train=[r for r in selected if r["asof"]<split.isoformat()]
    hold=[r for r in selected if r["asof"]>=split.isoformat()]
    train_panel={**panel,"sessions":[d for d in panel["sessions"] if d<split.isoformat()]}
    return {"years":years,"start":start.isoformat(),"end":end.isoformat(),"holdout_start":split.isoformat(),"verified_snapshots":len(selected),"all":result,
            "development":test(train,train_panel,cost_bps,strategies=STRATEGIES),"holdout":test(hold,panel,cost_bps,strategies=STRATEGIES),
            "note":"Final simplified model only. TOP5/10/15, fixed 60:40, 70:30 and 50:50, plus base and leading. Last year holdout, training horizons crossing split excluded. No claim of independent validation if prior tuning used holdout. Cohort MDD, price-return basis, no continuous portfolio CAGR."}
def main():
    p=argparse.ArgumentParser();p.add_argument("snapshots",type=Path);p.add_argument("panel",type=Path);p.add_argument("out",type=Path);p.add_argument("--end",required=True);a=p.parse_args()
    result=[extended(read(a.snapshots),read(a.panel),a.end,y) for y in (3,5)]
    a.out.parent.mkdir(exist_ok=True,parents=True);write(a.out,result)
if __name__=="__main__":main()
