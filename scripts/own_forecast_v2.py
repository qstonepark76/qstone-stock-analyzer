"""Own forecast v2 candidate: negative-base changes and comparable alternatives.
No historical actual is presented as an external forecast. All candidates retain
source receipts. Selection uses older vintage, evaluation a separate vintage.
"""
import math
def finite(x):
    return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
def change(c,p,profit=False):
    if not finite(c) or not finite(p):return None
    if not profit:
        return (100*(c/p-1),"ordinary_growth") if p>0 and c>=0 else None
    if p>0 and c>=0:return 100*(c/p-1),"ordinary_growth"
    d=abs(c)+abs(p)
    return (200*(c-p)/d if d else 0,"symmetric_profit_change")
def candidates(last,current,prior,quarters,asset_ratio=None):
    if not all(finite(v) for v in (last,current,prior)) or quarters not in (2,3):return {}
    residual=last-prior
    out={"seasonal_residual":current+residual,"annualized_ytd":current*4/quarters}
    # Trend scaling only where prior-year YTD and current YTD are positive,
    # capped to avoid extreme leverage of a small denominator.
    if prior>0 and current>=0 and .25<=current/prior<=4:
        out["trend_scaled_residual"]=current+residual*current/prior
    # Financial-sector asset-scaled remaining-period profit; not a regulatory
    # metric substitution. Requires actual matching asset observations.
    if finite(asset_ratio) and .5<=asset_ratio<=2:
        out["asset_scaled_residual"]=current+residual*asset_ratio
    return {k:v for k,v in out.items() if finite(v)}
def error(actual,forecast):
    d=abs(actual)+abs(forecast)
    return 200*abs(actual-forecast)/d if d else 0.0
def choose(training,holdout,minimum=5):
    """Select using training only. Compare on matched holdout samples."""
    valid=[]
    for model,rows in training.items():
        if len(rows)<minimum:continue
        m=sum(x["error"] for x in rows)/len(rows)
        # Compare model with naive baseline on the exact same matched sample.
        b=sum(x["baseline_error"] for x in rows)/len(rows)
        if m<=b:valid.append((m,model))
    if not valid:return None
    _,model=min(valid)
    rows=holdout.get(model,[])
    if len(rows)<minimum:return None
    m=sum(x["error"] for x in rows)/len(rows)
    b=sum(x["baseline_error"] for x in rows)/len(rows)
    return {"model":model,"training_n":len(training[model]),"holdout_n":len(rows),"holdout_smape":m,"baseline_smape":b,"candidate_pass":m<=b}
