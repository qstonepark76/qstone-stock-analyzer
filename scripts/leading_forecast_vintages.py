"""Verified external forecast vintages for the final leading model.
This adapter never turns issuer guidance or own predictions into broker consensus.
Source schema requires documented availability, numeric scale and accounting basis.
"""
from collections import defaultdict
from datetime import date,timedelta
from statistics import mean,median
from final_leading_model import finite,day
from outlook_candidate import broker_key

def valid(r,cutoff):
    published=day(r.get("published_at"));available=day(r.get("available_on"));period=day(r.get("period_end"))
    return (r.get("verified") is True and r.get("basis_verified") is True and
            r.get("source_kind")=="broker_forecast" and r.get("forward_looking") is True and
            r.get("metric") in ("operating_profit","net_income","target_price") and
            bool(r.get("ticker") and broker_key(r.get("broker")) and r.get("basis_id") and r.get("source_ref")) and
            r.get("unit")==("KRW_per_share" if r.get("metric")=="target_price" else "KRW") and
            finite(r.get("value")) and (r["value"]>0 if r["metric"]=="target_price" else True) and
            bool(published and available and period and published<=available<=cutoff and
                 (period>cutoff if r["metric"]!="target_price" else True)))

def matched(records,asof,ticker,metric,period,basis,max_age=45):
    """Same broker, fiscal period, unit, basis. Latest unambiguous vintage
    at each cutoff; 30 calendar days between cutoff dates. Freshness 45 days."""
    prior=asof-timedelta(days=30)
    rows=[r for r in records if r.get("ticker")==ticker and r.get("metric")==metric and
          r.get("period_end")==period and r.get("basis_id")==basis and valid(r,asof)]
    def snapshot(cut):
        groups=defaultdict(list)
        for r in rows:
            d=day(r["published_at"])
            if valid(r,cut) and 0<=(cut-d).days<=max_age:groups[broker_key(r["broker"])].append(r)
        out={}
        for b,rs in groups.items():
            latest=max(day(r["published_at"]) for r in rs)
            rs=[r for r in rs if day(r["published_at"])==latest]
            if len({r["value"] for r in rs})==1:out[b]=rs[0]
        return out
    a,b=snapshot(asof),snapshot(prior)
    pairs=[]
    for broker in sorted(set(a)&set(b)):
        current,previous=a[broker],b[broker]
        # Require a distinct updated report after the prior cutoff; stale
        # unchanged forecasts do not count as a newly observed revision.
        if day(current["published_at"])<=prior:continue
        x,y=current["value"],previous["value"]
        if metric=="target_price":
            v=100*(x/y-1)
        else:
            denom=abs(x)+abs(y)
            v=200*(x-y)/denom if denom else 0.0
        pairs.append({"broker":broker,"change":v,"current":current,"prior":previous})
    return pairs

def signals(pairs,metric,min_brokers=3):
    if len(pairs)<min_brokers:return {}
    changes=[p["change"] for p in pairs]
    if metric=="operating_profit":
        return {"op_revision_30d":mean(changes),"upward_broker_share":100*sum(v>0 for v in changes)/len(changes)}
    if metric=="net_income":return {"earnings_revision":mean(changes)}
    if metric=="target_price":return {"target_revision_30d":mean(changes),"target_revision":mean(changes)}
    return {}

def add_signals(payload,records,selection):
    """Explicit period and basis selection; never pick the best-looking series.
    Selection per ticker/metric is required. Unavailable fields remain missing."""
    asof=date.fromisoformat(payload["asof"])
    accepted={}
    for row in payload["stocks"]:
        if row.get("excluded"):continue
        t=row["ticker"]
        for metric,chosen in selection.get(t,{}).items():
            pairs=matched(records,asof,t,metric,chosen["period_end"],chosen["basis_id"])
            s=signals(pairs,metric)
            if not s:continue
            refs=sorted({p[x]["source_ref"] for p in pairs for x in ("current","prior")})
            basis="30-calendar-day matched independent brokers|"+chosen["period_end"]+"|"+chosen["basis_id"]
            for k,v in s.items():
                row["metrics"][k]={"value":v,"verified":True,"basis":basis,"asof":payload["asof"],
                                   "available_on":payload["asof"],"source_ref":"; ".join(refs)}
            accepted[t+"|"+metric]=pairs
    # Industry revisions require 5 different eligible issuers with admitted
    # same-period, same-definition changes and same exact industry code.
    groups=defaultdict(list)
    for row in payload["stocks"]:
        if row.get("excluded") or not row.get("industry_code"):continue
        o=row["metrics"].get("op_revision_30d")
        if o and row["ticker"]+"|operating_profit" in accepted:
            groups[(row["industry_code"],o["basis"])].append(row)
    for rows in groups.values():
        if len(rows)<5:continue
        val=median(r["metrics"]["op_revision_30d"]["value"] for r in rows)
        refs=sorted({r["metrics"]["op_revision_30d"]["source_ref"] for r in rows})
        for row in rows:
            row["metrics"]["industry_earnings_revision"]={"value":val,"verified":True,"basis":"industry median|"+row["metrics"]["op_revision_30d"]["basis"],"asof":payload["asof"],"available_on":payload["asof"],"source_ref":"; ".join(refs)}
    return accepted
