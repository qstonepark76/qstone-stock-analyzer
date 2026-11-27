"""Approved direct-source leading-score admission.

Accept published Naver, KRX and KIS data without agreement from another
provider. Keep identity, period, numeric units and same-window requirements.
Never represent 1-month estimates as exact 30-day data or single brokers as
consensus; preserve source observation dates and do not backdate.
"""
from datetime import date,timedelta
from statistics import mean
from final_leading_model import finite,curve
APPROVED={"Naver reports","KIS invest-opinion","Naver","KRX","KIS"}
def day(x):
    try:return date.fromisoformat(x)
    except (TypeError,ValueError):return None
def target_revision(z,asof):
    if z.get("source") not in ("Naver reports","KIS invest-opinion"):return None
    prior=asof-timedelta(days=30);pairs=z.get("pairs")
    if not isinstance(pairs,list):return None
    by={}
    for p in pairs:
        b=str(p.get("broker") or "").strip()
        a,c=day(p.get("prior_date")),day(p.get("current_date"))
        x,y=p.get("prior_target"),p.get("current_target")
        if not b or not a or not c or not a<=prior<c<=asof or (prior-a).days>45 or not all(finite(v) and v>0 for v in (x,y)):continue
        if b in by:return None
        by[b]=p
    # Keep existing approved consensus minimum; 1–2 broker observations
    # remain separate evidence, not artificially expanded consensus.
    if len(by)<3:return None
    value=mean(100*(p["current_target"]/p["prior_target"]-1) for p in by.values())
    return {"value":value,"points":6*curve("target_revision_30d",value),"weight":6,"broker_count":len(by),
            "asof":asof.isoformat(),"prior_cutoff":prior.isoformat(),"source":z["source"],"pairs":list(by.values()),
            "basis":"same-source reported targets, matched broker and 30-calendar-day cutoff",
            "cross_provider_validation_required":False,"provider_target_basis":"as_reported",
            "historical_backfill":False}
