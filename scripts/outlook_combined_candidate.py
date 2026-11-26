"""External-first candidate scoring: own estimates may fill ONLY forecast slots.
The approved 3:3:1:1:1:1 weights and broker zero policy are unchanged.
"""
from outlook_candidate import WEIGHTS,FORECAST_FIELDS,curve,number,day
MODEL_METRIC={"sales_forecast_growth":"sales","operating_profit_forecast_growth":"op","earnings_forecast_revision":"net"}
def combined(external,model,backtest,asof,ticker):
    assert sum(WEIGHTS.values())==10
    detail={k:dict(v) for k,v in external["detail"].items()}
    model_weight=0
    for k in FORECAST_FIELDS:
        if detail[k]["observed"]:continue
        if not model or model.get("ticker")!=ticker or model.get("source_kind")!="qstone_model_forecast":continue
        if day(model.get("asof"))!=asof or not day(model.get("period_end")) or day(model["period_end"])<=asof:continue
        gate=backtest.get(MODEL_METRIC[k],{})
        if gate.get("candidate_pass") is not True or gate.get("n",0)<20:continue
        row=model.get("values",{}).get(k,{})
        v=number(row.get("value"))
        if v is None or row.get("metric")!=k:continue
        detail[k].update({"points":round(curve(k,v),4),"value":v,"observed":False,"status":"own_model_candidate","source_kind":"qstone_model_forecast","model_evidence":row,"backtest":gate})
        model_weight+=WEIGHTS[k]
    observed=sum(WEIGHTS[k] for k,v in detail.items() if v["observed"])
    calculated=sum(WEIGHTS[k] for k,v in detail.items() if v["points"] is not None)
    return {"ticker":ticker,"detail":detail,"points_out_of_10":round(sum(v["points"] or 0 for v in detail.values()),4),
      "external_observed_pct":10*observed,"own_model_coverage_pct":10*model_weight,
      "evidence_plus_model_pct":10*(observed+model_weight),"policy_calculation_pct":10*calculated,
      "full_policy_score_available":calculated==10,"official":False}
