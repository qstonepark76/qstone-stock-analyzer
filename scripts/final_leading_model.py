"""Final v3.3 allocation and independent leading indicator (candidate only).
Input: point-in-time verified metric observations; no fabricated coverage.
Run: python scripts/final_leading_model.py observations.json output.json
"""
import argparse
import json
import math
from datetime import date
from pathlib import Path
from forecast_score_policy import choose_forecast,forecast_fraction,FACTORS as FORECAST_FIELDS

VERSION = "3.3-final-leading-candidate"
SIMPLIFIED_SPECIAL={"bank_group":{"nim_pct":4,"cet1_pct":3,"npl_pct":3},"life_insurance":{"kics_pct":4,"csm_growth_pct":3,"investment_yield_pct":3},"nonlife_insurance":{"kics_pct":4,"combined_ratio_pct":3,"investment_yield_pct":3},"securities":{"ncr_pct":4,"regulatory_leverage_pct":3,"cir_pct":3},"card_capital":{"adjusted_capital_pct":4,"delinquency_pct":3,"credit_cost_pct":3}}
SIMPLIFIED_INDUSTRIAL={"operating_return_on_assets":3,"asset_turnover":3,"cash_conversion":2,"margin_stability":2}
BASE = {
    "financial": {"roe":5,"roa":3,"margin":4,"stability":4,"cash":4},
    "growth": {"sales_growth":5,"op_growth":7,"net_growth":5,"sales_cagr":3},
    "momentum": {"momentum_5d":2,"momentum_20d":3,"momentum_60d":3,"trading_value":1,"volatility_20d":1},
    "foreign_flow": {"foreign_5d":2,"foreign_20d":4,"foreign_60d":4},
    "institution_flow": {"institution_5d":2,"institution_20d":4,"institution_60d":4},
    "valuation": {"earnings_value":5,"book_value":5},
    "outlook": {"rating":2,"upside":2,"target_revision":2,"op_forecast_growth":2,"earnings_revision":2},
    "industry_relative": {"roic":3,"asset_turnover":3,"cash_conversion":2,"margin_stability":2},
}
LEADING = {
    "earnings": {"op_revision_30d":10,"upward_broker_share":8,"target_revision_30d":6,"earnings_surprise":6},
    "flows": {"foreign_acceleration":10,"institution_acceleration":10,"joint_buy":5},
    "price": {"relative_acceleration":8,"turnover_growth":7,"breakout":5},
    "industry": {"industry_relative_return":8,"industry_earnings_revision":7},
    "headroom": {"revision_price_gap":6,"overheat":4},
}
# Separate approved specialist relative models retain their five 2-point slots.
SPECIAL_RELATIVE = {
    "bank_group": ("nim_pct","cet1_pct","npl_pct","credit_cost_pct","cir_pct"),
    "life_insurance": ("kics_pct","new_csm_margin_pct","insurance_service_margin_pct","investment_yield_pct","impaired_asset_pct"),
    "nonlife_insurance": ("kics_pct","new_csm_margin_pct","investment_yield_pct","combined_ratio_pct","impaired_asset_pct"),
    "securities": ("ncr_pct","liquidity_pct","regulatory_leverage_pct","contingent_liability_equity_pct","cir_pct"),
    "card_capital": ("adjusted_capital_pct","liquidity_pct","delinquency_pct","npl_pct","credit_cost_pct"),
}
LOWER = {"stability","volatility_20d","earnings_value","book_value","margin_stability", "npl_pct","credit_cost_pct","cir_pct","impaired_asset_pct","combined_ratio_pct","regulatory_leverage_pct","contingent_liability_equity_pct","delinquency_pct"}
# Percent units except rating (0..3), shares (0..100), ratio-based growth (%).
# Fixed, provisional calibration; not estimated probabilities.
CURVES = {
    "rating":(0,3),"upside":(0,50),"target_revision":(-20,20),
    "op_forecast_growth":(-20,20),"earnings_revision":(-20,20),
    "op_revision_30d":(-15,15),"upward_broker_share":(0,100),
    "target_revision_30d":(-15,15),"earnings_surprise":(-20,20),
    "foreign_acceleration":(-5,5),"institution_acceleration":(-5,5),
    "joint_buy":(-5,5),"relative_acceleration":(-10,10),
    "turnover_growth":(-50,100),"breakout":(-5,5),
    "industry_relative_return":(-10,10),"industry_earnings_revision":(-15,15),
    "revision_price_gap":(-20,20),"overheat":(0,20),
}
# Industry/specialist financial and valuation comparisons use exact comparable
# metric definitions and peer groups; the collector supplies comparable basis.
PEER_FACTORS = {"financial","growth","valuation","industry_relative"}
MIN_PEERS=5

def finite(v):
    return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)

def day(v):
    try: return date.fromisoformat(v)
    except (TypeError,ValueError): return None

def observed(o,asof):
    if not isinstance(o,dict) or o.get("verified") is not True or not finite(o.get("value")):
        return False
    d=day(o.get("available_on"))
    end=day(o.get("asof"))
    return bool(d and end and end<=d<=asof and o.get("source_ref") and o.get("basis"))
    
def clip(v):
    return max(0.0,min(1.0,v))

def curve(k,v):
    lo,hi=CURVES[k]
    q=clip((v-lo)/(hi-lo))
    return 1-q if k=="overheat" else q

def percentile(v,values,lower=False):
    n=len(values)
    if n<MIN_PEERS: return None
    q=(sum(x<v for x in values)+0.5*sum(x==v for x in values))/n
    return 1-q if lower else q

def group_weights(row):
    w={f:dict(m) for f,m in BASE.items()}
    # Specialist alternatives are separate, never compared to industrial ratios.
    model=row.get("financial_model")
    if row.get("simplified_industry_policy") and model in (None,"operating_holding",*SIMPLIFIED_SPECIAL):
        w["industry_relative"]=dict(SIMPLIFIED_SPECIAL.get(model,SIMPLIFIED_INDUSTRIAL))
    elif model in SPECIAL_RELATIVE:
        w["industry_relative"]={k:2 for k in SPECIAL_RELATIVE[model]}
    return w

def score_groups(row,rows,weights,asof,leading=False):
    detail={}
    earned=covered=0
    # Specialist stability must specify direction and an independent metric ID.
    model=row.get("financial_model")
    specialist=bool(model and model!="operating_holding")
    for factor,metrics in weights.items():
        for k,w in metrics.items():
            o=row.get("metrics",{}).get(k)
            # New policy inputs are separate from historical replay observations.
            # Only validated, comparable and timely source records may replace a slot.
            policy=None
            if k in FORECAST_FIELDS:
                policy=choose_forecast(k,row.get("forecast_evidence",{}).get(k,[]),asof)
                if policy and (not observed(o,asof) or policy["source_kind"]=="broker_consensus"):
                    o=policy
                else:
                    policy=None
            q=None
            n=None
            peer_level=None
            status="데이터 부족"
            valid=observed(o,asof)
            if valid and k in {"rating","upward_broker_share","overheat"}:
                valid=(0<=o["value"]<=3 if k=="rating" else
                       0<=o["value"]<=100 if k=="upward_broker_share" else o["value"]>=0)
            if valid and specialist and not leading and factor=="financial" and k in {"stability","cash"}:
                valid=bool(o.get("metric_id") and o["metric_id"] not in SPECIAL_RELATIVE.get(model,())
                           and isinstance(o.get("lower_better"),bool))
            if valid and k in {"momentum_5d","momentum_20d","momentum_60d","trading_value","volatility_20d",
                               "foreign_5d","foreign_20d","foreign_60d","institution_5d","institution_20d",
                               "institution_60d","foreign_acceleration","institution_acceleration","joint_buy",
                               "relative_acceleration","turnover_growth","breakout","industry_relative_return","overheat","revision_price_gap","upside"}:
                valid=o.get("asof")==asof.isoformat()
            if valid:
                if k in CURVES:
                    q=forecast_fraction(k,o["value"],policy["source_kind"]) if policy else curve(k,o["value"])
                else:
                    # Matching definition and direction required. Financial
                    # types must match; valuation/industry also exact industry.
                    lower=o.get("lower_better",k in LOWER)
                    def comparable(p,level="exact"):
                        if p.get("excluded") or (p.get("peer_only") and factor not in {"industry_relative","valuation"}): return False
                        x=p.get("metrics",{}).get(k)
                        if not observed(x,asof) or x["basis"]!=o["basis"] or x.get("lower_better",k in LOWER)!=lower: return False
                        if x.get("asof")!=o.get("asof") or x.get("metric_id")!=o.get("metric_id"): return False
                        if factor in PEER_FACTORS and p.get("financial_model")!=row.get("financial_model"): return False
                        if factor in {"valuation","industry_relative"}:
                            if factor=="industry_relative" and row.get("financial_model") in SPECIAL_RELATIVE:
                                return True
                            code=str(row.get("industry_code") or "")
                            other=str(p.get("industry_code") or "")
                            if level=="parent":return code.isdigit() and other.isdigit() and len(code)>=2 and len(other)>=2 and code[:2]==other[:2]
                            return bool(code and other==code)
                        return True
                    peers=[p["metrics"][k]["value"] for p in rows if comparable(p)]
                    n=len(peers)
                    peer_level="exact"
                    if n<MIN_PEERS and row.get("simplified_industry_policy") and factor in {"industry_relative","valuation"} and not specialist:
                        peers=[p["metrics"][k]["value"] for p in rows if comparable(p,"parent")]
                        n=len(peers);peer_level="KSIC_2digit"
                    q=percentile(o["value"],peers,lower)
                status="산출" if q is not None else "비교대상 부족"
            pts=round(w*q,6) if q is not None else None
            if pts is not None:
                earned+=pts
                covered+=w
            detail[k]={"factor":factor,"weight":w,"points":pts,"status":status,
                       "value":o["value"] if valid else None,
                       "source_ref":o.get("source_ref") if valid else None,
                       "peer_count":n,"peer_level":peer_level,
                       "forecast_source_kind":policy["source_kind"] if valid and policy else None,
                       "forecast_confidence":policy["confidence"] if valid and policy else None}
    complete=covered==100 and not row.get("excluded") and (leading or not specialist or model in SPECIAL_RELATIVE)
    # A partial subtotal is NOT an estimate of the full score.
    return {"score":round(earned,2) if complete else None,
            "observed_points":round(earned,2) if covered else None,
            "coverage_pct":covered,"complete":complete,"detail":detail}

def evaluate(payload):
    asof=day(payload.get("asof"))
    if not asof: raise ValueError("Invalid asof")
    rows=payload["stocks"]
    if payload.get("industry_policy")=="simplified_v1":
        rows=[{**r,"simplified_industry_policy":True} for r in rows]
    if len({r["ticker"] for r in rows})!=len(rows): raise ValueError("Duplicate tickers")
    peers=payload.get("comparison_peers",[])
    if any(not p.get("peer_only") for p in peers): raise ValueError("Comparison-only designation required")
    all_rows=rows+peers
    if len({r["ticker"] for r in all_rows})!=len(all_rows): raise ValueError("Duplicate target/peer tickers")
    results=[]
    for row in rows:
        a=score_groups(row,all_rows,group_weights(row),asof)
        b=score_groups(row,rows,LEADING,asof,True)
        combined=round(.6*a["score"]+.4*b["score"],2) if a["complete"] and b["complete"] else None
        grade=None if not a["complete"] else next(g for threshold,g in [(90,"S"),(80,"A"),(70,"B"),(60,"C"),(0,"D")] if a["score"]>=threshold)
        results.append({"ticker":row["ticker"],"name":row.get("name",row["ticker"]),
                        "industry_code":row.get("industry_code"),"excluded":bool(row.get("excluded")),
                        "base":a,"leading":b,"combined":combined,"grade":grade})
    def rank(key,n):
        def val(r):return r[key]["score"] if key in ("base","leading") else r[key]
        return [r["ticker"] for r in sorted((r for r in results if not r["excluded"] and val(r) is not None),
                    key=lambda r:(-val(r),r["ticker"]))[:n]]
    return {"model_version":VERSION+("-simplified-v1" if payload.get("industry_policy")=="simplified_v1" else ""),"asof":asof.isoformat(),"candidate_only":True,
            "base_weights":{f:sum(m.values()) for f,m in BASE.items()},
            "leading_weights":{f:sum(m.values()) for f,m in LEADING.items()},
            "records":results,"base_top15":rank("base",15),"leading_top10":rank("leading",10),
            "combined_top15":rank("combined",15),
            "coverage":{"base_complete":sum(r["base"]["complete"] for r in results),
                        "leading_complete":sum(r["leading"]["complete"] for r in results),
                        "combined_complete":sum(r["combined"] is not None for r in results)}}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("input",type=Path)
    p.add_argument("output",type=Path)
    a=p.parse_args()
    result=evaluate(json.loads(a.input.read_text(encoding="utf-8")))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")

if __name__=="__main__": main()
