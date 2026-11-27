"""User-approved source hierarchy and neutral-centered confidence adjustment.
Policy coefficients and bins are provisional calibration, not probabilities.
Do not equate issuer or own forecasts with independent broker consensus.
"""
import math
from datetime import date,timedelta
CONFIDENCE={"broker_consensus":1.0,"single_broker":.9,"issuer_guidance":.85,"own_model":.8}
FACTORS={"op_forecast_growth","earnings_revision","op_revision_30d","upward_broker_share","industry_earnings_revision","revision_price_gap","earnings_surprise"}
# Broker breadth is strictly independent broker evidence. Quarterly model
# revisions can supplement base outlook, never the 30-day leading slots.
WINDOWED={"op_revision_30d","upward_broker_share","industry_earnings_revision","revision_price_gap"}
def day(v):
    try:return date.fromisoformat(v)
    except (ValueError,TypeError):return None
def finite(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
def valid(k,r,asof):
    if k not in FACTORS or not isinstance(r,dict) or r.get("metric")!=k:return False
    kind=r.get("source_kind")
    if kind not in CONFIDENCE or not finite(r.get("value")):return False
    if r.get("verified") is not True or r.get("basis_verified") is not True or r.get("admission_gate_pass") is not True:return False
    if not all(isinstance(r.get(x),str) and r[x].strip() for x in ("source_ref","basis","validation_ref","account_basis","unit")):return False
    if r["unit"]!="percent" or r.get("scope") not in ("CFS","OFS"):return False
    a,b,p=day(r.get("asof")),day(r.get("available_on")),day(r.get("period_end"))
    if not a or not b or not p or not a<=b<=asof or a!=asof:return False
    if k!="earnings_surprise" and p<=asof:return False
    if kind=="broker_consensus":
        brokers=r.get("independent_brokers")
        if not isinstance(brokers,list) or len({x.strip().casefold() for x in brokers if isinstance(x,str) and x.strip()})<3:return False
    if kind=="single_broker" and not r.get("broker"):return False
    if kind=="own_model" and (r.get("out_of_sample_validated") is not True or not r.get("model_version")):return False
    if k=="upward_broker_share" and (kind!="broker_consensus" or not 0<=r["value"]<=100):return False
    if k in WINDOWED:
        prior=day(r.get("prior_cutoff"))
        if prior!=asof-timedelta(days=30) or r.get("same_period_basis") is not True:return False
        # Actual forecasts must be available at both cutoffs, not retrospectively backfilled.
        prior_available=day(r.get("prior_available_on"));current_available=day(r.get("current_available_on"))
        if not prior_available or not current_available or not prior_available<=prior<current_available<=asof:return False
    if k=="earnings_revision" and r.get("same_period_basis") is not True:return False
    if k=="industry_earnings_revision":
        if r.get("same_source_class") is not True or not isinstance(r.get("peer_issuers"),list) or len(set(r["peer_issuers"]))<5:return False
    if k=="revision_price_gap" and r.get("matched_price_window_verified") is not True:return False
    if k=="earnings_surprise":
        release=day(r.get("actual_release_on"));forecast=day(r.get("forecast_available_on"))
        if not release or not forecast or not forecast<release<=asof or p>release or r.get("same_period_basis") is not True:return False
    return True

def choose_forecast(k,records,asof):
    if not isinstance(records,list):return None
    for kind in CONFIDENCE:
        accepted=[r for r in records if isinstance(r,dict) and r.get("source_kind")==kind and valid(k,r,asof)]
        if not accepted:continue
        # Source precedence, not selection of the largest forecast. Conflicting
        # equally ranked observations are withheld, not cherry-picked.
        signatures={(r["value"],r["period_end"],r["account_basis"],r["scope"]) for r in accepted}
        if len(signatures)!=1:return None
        r=min(accepted,key=lambda x:x["source_ref"])
        return {**r,"confidence":CONFIDENCE[kind]}
    return None

def raw_fraction(k,v):
    if k=="op_revision_30d":
        # Approved provisional bins (exact boundaries defined here).
        for threshold,q in ((20,1),(10,.9),(5,.8),(2,.7),(0,.5),(-2,.4),(-5,.3),(-10,.2),(-20,.1)):
            if v>=threshold:return q
        return 0
    lo,hi=(0,100) if k=="upward_broker_share" else (-15,15) if k=="industry_earnings_revision" else (-20,20)
    return max(0,min(1,(v-lo)/(hi-lo)))

def forecast_fraction(k,v,kind):
    return .5+CONFIDENCE[kind]*(raw_fraction(k,v)-.5)
