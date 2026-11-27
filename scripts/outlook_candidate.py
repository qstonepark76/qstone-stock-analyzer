"""Isolated v3.3 outlook candidate. Missing broker fields earn zero by policy,
not by evidence. Never convert missing inputs into observed coverage.
Forecasts must be independently verified forward-looking observations.
"""
import math
from datetime import date
from collections import defaultdict

WEIGHTS={"rating":3,"upside":3,"revision":1,"sales_forecast_growth":1,"operating_profit_forecast_growth":1,"earnings_forecast_revision":1}
RATINGS={"강력매수":3,"매수":2.5,"비중확대":2,"중립":1.5,"보유":1.5,"비중축소":.5,"매도":0}
BROKER_FIELDS=("rating","upside","revision")
FORECAST_FIELDS=tuple(k for k in WEIGHTS if k not in BROKER_FIELDS)
def number(v):
    if isinstance(v,bool):
        return None
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):
        return None
def day(v):
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError,ValueError):
        return None
def recency(age):
    return 1 if age<=30 else .9 if age<=60 else .8 if age<=90 else .6 if age<=120 else .4 if age<=180 else 0
def broker_key(v):
    # Strip whitespace and common legal suffixes. Further alias review required.
    return "".join(str(v or "").split()).replace("주식회사","").replace("(주)","").replace("㈜","").casefold()
def weighted(rows):
    if not rows:
        return None
    return sum(x*w for x,w in rows)/sum(w for x,w in rows)
def clipped(x,lo=0,hi=1):
    return min(hi,max(lo,x))
def curve(metric,value):
    # Explicit candidate-only calibration, not a fitted forecast model.
    if metric=="rating":
        return value
    if metric=="upside":
        return 3*clipped(value/50)
    if metric=="revision":
        return clipped(.5+value/40)
    return clipped(.5+value/40)

def broker_evidence(stock,reports,asof):
    groups=defaultdict(list)
    for r in reports:
        if r.get("ticker")!=stock["ticker"]:
            continue
        d=day(r.get("published_at"))
        b=broker_key(r.get("broker"))
        if not d or not b or d>asof or (asof-d).days>365:
            continue
        if not r.get("verification_method") or not r.get("verified_at") or not str(r.get("source_url") or "").startswith("https://"):
            continue
        groups[b].append((d,r))
    evidence={k:[] for k in BROKER_FIELDS}
    for b,rows in groups.items():
        rows.sort(key=lambda p:p[0],reverse=True)
        d=rows[0][0]
        w=recency((asof-d).days)
        if not w:
            continue
        # Conflicting same-day observations are withheld, not resolved by URL.
        latest=[r for dd,r in rows if dd==d]
        def unique(key):
            vals={r.get(key) for r in latest if r.get(key) is not None}
            return next(iter(vals)) if len(vals)==1 else None
        rating=RATINGS.get(unique("rating"))
        target=number(unique("target_price"))
        close=number(stock.get("close"))
        link=latest[0]["source_url"]
        if rating is not None:
            evidence["rating"].append((rating,w,b,link))
        if target is not None and target>0 and close is not None and close>0:
            evidence["upside"].append((100*(target/close-1),w,b,link))
        # Revision uses the most recent strictly earlier valid target from the
        # same broker. Require explicit corporate-action basis confirmation.
        earlier=[(dd,r) for dd,r in rows if dd<d and number(r.get("target_price")) is not None and number(r["target_price"])>0]
        if target is not None and target>0 and earlier and all(r.get("target_price_basis_verified") is True for r in latest):
            pd=earlier[0][0]
            prior=[r for dd,r in earlier if dd==pd]
            vals={number(r["target_price"]) for r in prior}
            if len(vals)==1 and all(r.get("target_price_basis_verified") is True for r in prior):
                prev=next(iter(vals))
                evidence["revision"].append((100*(target/prev-1),w,b,link))
    return evidence

def score(stock,reports,asof,forecasts=()):
    ev=broker_evidence(stock,reports,asof)
    detail={}
    for k in BROKER_FIELDS:
        rows=ev[k]
        v=weighted([(x,w) for x,w,_,_ in rows])
        detail[k]={"points":round(curve(k,v),4) if v is not None else 0,
                   "observed":v is not None,"value":v,"broker_count":len(rows),
                   "status":"observed" if v is not None else "missing_zero_policy",
                   "sources":sorted({u for _,_,_,u in rows})}
    for k in FORECAST_FIELDS:
        # No historical results may serve as forecasts. Require explicit
        # annual future-period evidence, provenance and like-for-like basis.
        valid=[]
        for r in forecasts:
            d=day(r.get("published_at"))
            end=day(r.get("period_end"))
            v=number(r.get("value"))
            if r.get("ticker")==stock["ticker"] and r.get("metric")==k and r.get("verified") is True and r.get("forward_looking") is True and r.get("basis_verified") is True and r.get("unit")=="percent" and r.get("source_kind") in ("broker_forecast","issuer_guidance") and str(r.get("source_url") or "").startswith("https://") and d and end and d<=asof<end and recency((asof-d).days)>0 and v is not None:
                valid.append((d,r,v))
        # No averaging different forecast periods or issuers' and brokers'
        # estimates; retain most recent unambiguous evidence for now.
        valid.sort(key=lambda x:x[0],reverse=True)
        top=[x for x in valid if x[0]==valid[0][0]] if valid else []
        value=top[0][2] if len(top)==1 else None
        detail[k]={"points":round(curve(k,value),4) if value is not None else None,
                   "observed":value is not None,"value":value,
                   "status":"observed" if value is not None else "missing_forecast",
                   "sources":[top[0][1]["source_url"]] if value is not None else []}
    observed=sum(WEIGHTS[k] for k,v in detail.items() if v["observed"])
    policy=sum(WEIGHTS[k] for k,v in detail.items() if v["points"] is not None)
    points=round(sum(v["points"] or 0 for v in detail.values()),4)
    return {"points_out_of_10":points,"observed_coverage_pct":10*observed,"policy_calculation_pct":10*policy,
            "full_policy_score_available":policy==10,"all_evidence_observed":observed==10,
            "broker_evidence_count":max(v["broker_count"] for k,v in detail.items() if k in BROKER_FIELDS),
            "detail":detail,"official":False}
