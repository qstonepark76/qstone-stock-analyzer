"""Read-only eight-factor top-300 score audit using the fixed source universe.

Recalculate rather than reuse old seven-factor scores. Source-date mismatches
remain missing. Never update published data or recommendation history.
"""
import datetime as dt
import json
import math
import statistics
from collections import Counter
from pathlib import Path
from collect import (extract_financial, calculate_valuation, normalize, get_krx_day,
                     score_field, weighted_score, load_and_score_consensus)
from industry_relative import aggregate_candidate, CANDIDATE_WEIGHTS
from metric_quality import source_check, account_check, finite

SOURCE=Path("replay-source")
REPLAY=Path("audit-top300-replay")
OUT=Path("audit-top300-eight-factor")

def read(p):
    return json.loads(p.read_text(encoding="utf-8"))

def main():
    OUT.mkdir(exist_ok=True)
    universe=read(SOURCE/"universe.json")
    audit=read(SOURCE/"report.json")
    relative=read(REPLAY/"records.json")
    asof=dt.date.fromisoformat(universe["asof"])
    year=audit["year"]
    entries={r["ticker"]:r for r in audit["records"]}
    rel={r["ticker"]:r for r in relative}
    tickers={r["ticker"] for r in universe["stocks"]}
    if len(tickers)!=300 or set(entries)!=tickers or set(rel)!=tickers:
        raise ValueError("Universe mismatch")
    history={}
    for p in Path("data/history").glob("*.json"):
        try:
            day=dt.datetime.strptime(p.stem,"%Y%m%d").date()
            if day<=asof:
                rows=read(p)
                if isinstance(rows,list) and rows:
                    history[day]={r["ticker"]:r for r in rows}
        except (ValueError,KeyError,TypeError,OSError):
            continue
    if asof not in history:
        history[asof]={r["ticker"]:r for r in normalize(get_krx_day(asof))}
    days=sorted(history)[-61:]
    flows=read(Path("data/kis_flow_cache.json"))
    notes_path=Path("audit-top300-xbrl/notes.json")
    notes=read(notes_path) if notes_path.exists() else {}
    stocks=[]
    for u in universe["stocks"]:
        t=u["ticker"]
        market=history[asof].get(t,{})
        if market.get("market_cap")!=u["market_cap"]:
            market={}
        x={"ticker":t,"name":u["name"],"market_cap":u["market_cap"],
           "close":market.get("close"),"trading_value":market.get("trading_value")}
        for n in (5,20,60):
            window=days[-(n+1):]
            prices=[history[d].get(t,{}).get("close") for d in window]
            x[f"momentum_{n}d"]=(x["close"]/prices[0]-1)*100 if len(prices)==n+1 and finite(x["close"]) and all(finite(v) and v>0 for v in prices) else None
        changes=[history[d].get(t,{}).get("change_pct") for d in days[-20:]]
        x["volatility_20d"]=statistics.pstdev(changes) if len(changes)==20 and all(finite(v) for v in changes) else None
        flow=flows.get(t,{})
        fm=flow.get("metrics") or {}
        if flow.get("as_of")==asof.isoformat() and fm.get("investor_flow_as_of")==asof.strftime("%Y%m%d") and fm.get("investor_flow_sessions")==5:
            for k in ("foreign_flow_5d_pct","institution_flow_5d_pct"):
                x[k]=fm.get(k) if finite(fm.get(k)) else None
        src=entries[t]
        if src["status"]=="source_received":
            rows=read(SOURCE/"source-rows"/(t+".json"))
            receipts=sorted({str(r.get("rcept_no")) for r in rows if r.get("rcept_no")})
            if receipts==src.get("receipts") and source_check(rows,year,src.get("scope")):
                m=extract_financial(rows,ticker=t,financial_year=year,fs_div=src.get("scope"),xbrl_note=notes.get(t))
                for k in ("roe_pct","sales_growth_pct","operating_profit_growth_pct"):
                    x[k]=m.get(k) if finite(m.get(k)) else None
                x["per"],x["pbr"]=calculate_valuation(x["market_cap"],m.get("net_income"),m.get("equity_total"),m.get("financial_currency"))
        stocks.append(x)
    load_and_score_consensus(stocks,asof,candidate=True)
    fields={"roe":"roe_pct","sales":"sales_growth_pct","op":"operating_profit_growth_pct",
            "m60":"momentum_60d","m20":"momentum_20d","m5":"momentum_5d","liquidity":"trading_value",
            "vol":"volatility_20d","foreign":"foreign_flow_5d_pct","institution":"institution_flow_5d_pct","per":"per","pbr":"pbr"}
    ranks={k:score_field(stocks,f,reverse=k in ("vol","per","pbr")) for k,f in fields.items()}
    result=[]
    for x in stocks:
        t=x["ticker"]
        def part(pairs):
            return weighted_score([(ranks[k].get(t),w) for k,w in pairs])
        fin,fc=part([("roe",50),("sales",25),("op",25)])
        growth,gc=part([("sales",50),("op",50)])
        momentum,mc=part([("m60",60),("m20",20),("m5",10),("liquidity",5),("vol",5)])
        if x.get("momentum_60d") is None:
            momentum,mc=None,0
        val,vc=part([("per",50),("pbr",50)])
        components={"financial":fin,"growth":growth,"momentum":momentum,
                    "foreign_flow":ranks["foreign"].get(t),"institution_flow":ranks["institution"].get(t),
                    "valuation":val,"analyst_outlook":x.get("analyst_consensus_score")}
        coverage={"financial":fc,"growth":gc,"momentum":mc,"valuation":vc,
                  "foreign_flow":100 if x.get("foreign_flow_5d_pct") is not None else 0,
                  "institution_flow":100 if x.get("institution_flow_5d_pct") is not None else 0,
                  "analyst_outlook":x.get("analyst_consensus_coverage_pct",0)}
        relative_result=rel[t]["industry_relative"]
        candidate=aggregate_candidate(components,coverage,relative_result)
        if rel[t]["screening_class"] in ("known_preferred_share","duplicate_issuer_pending"):
            candidate.update(score=None,grade=None,official_recommendation_eligible=False,status="전략 제외")
        result.append({"ticker":t,"name":x["name"],"candidate":candidate,"analyst_evidence":{k:x.get(k) for k in ("analyst_broker_count","analyst_rating_broker_count","analyst_target_broker_count","analyst_revision_broker_count","analyst_observed_coverage_pct","analyst_consensus_coverage_pct","analyst_confidence")}})
    counts=Counter()
    for r in result:
        c=r["candidate"]
        counts["official"]+=int(c["official_recommendation_eligible"])
        counts["excluded"]+=int(c["status"]=="전략 제외")
        counts["provisional"]+=int(c["status"]!="전략 제외" and not c["official_recommendation_eligible"] and c["provisional_score"] is not None)
    summary={"asof":asof.isoformat(),"count":len(result),"weights":CANDIDATE_WEIGHTS,
             "score_counts":dict(counts),"history_sessions":len(days),
             "factor_full_coverage":{k:sum(r["candidate"]["component_coverage_pct"].get(k)==100 for r in result) for k in CANDIDATE_WEIGHTS},
             "analyst_partial_count":sum(0<(r["analyst_evidence"].get("analyst_consensus_coverage_pct") or 0)<100 for r in result),
             "analyst_observed_count":sum((r["analyst_evidence"].get("analyst_observed_coverage_pct") or 0)>0 for r in result),
             "release_gate":"not_verified",
             "warning":"Candidate audit only: exact date cached flows may be missing; existing seven-factor financial formulas retained; no production changes."}
    (OUT/"records.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    (OUT/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print("TOP300 EIGHT FACTOR SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
