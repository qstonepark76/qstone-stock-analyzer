"""Replay immutable top-300 source artifacts with the current candidate rules.

No provider calls, production writes or recommendation publication.
This avoids collecting the same 300 annual statements again after rule changes.
"""
import json
import math
from collections import Counter
from pathlib import Path
from collect import extract_financial, PREFERRED_SHARE_PARENT, classify_sector, classify_industry_code
from financial_industry import financial_model_for, load_financial_observations, comparable_observation, external_financial_peers
from industry_relative import METRICS, FINANCIAL_MODELS, score_industry_relative
from metric_quality import admitted_industry_metrics, RULE_VERSION

SOURCE = Path("replay-source")
OUT = Path("audit-top300-replay")

def read(path):
    return json.loads(path.read_text(encoding="utf-8"))

def main():
    OUT.mkdir(exist_ok=True)
    universe = read(SOURCE/"universe.json")
    original = read(SOURCE/"report.json")
    stocks = universe["stocks"]
    if len(stocks)!=300 or len({s["ticker"] for s in stocks})!=300:
        raise ValueError("Invalid top-300 source universe")
    year = original["year"]
    if original.get("universe_asof") != universe["asof"] or original.get("sample_count")!=300:
        raise ValueError("Source universe and audit report disagree")
    records = original["records"]
    by_ticker = {r["ticker"]:r for r in records}
    if len(records)!=300 or set(by_ticker)!={s["ticker"] for s in stocks}:
        raise ValueError("Incomplete or duplicate audit record list")
    fiscal_period = str(year)+"-12"
    financial = load_financial_observations(period=fiscal_period)
    sector_cache = read(Path("data/sector_industry_cache.json"))
    note_path = Path("audit-top300-xbrl/notes.json")
    notes = read(note_path) if note_path.exists() else {}
    results,exceptions = [],[]
    states = {key:Counter() for key in METRICS}
    source_received = 0
    for stock in stocks:
        ticker = stock["ticker"]
        src = by_ticker[ticker]
        row = {"ticker":ticker,"name":stock["name"],"source_status":src["status"],"corp_code":src.get("corp_code")}
        # Only a cached official code with matching source issuer identity
        # and a recent timestamp may define a comparison group.
        from datetime import date
        cache = sector_cache.get(ticker) or {}
        code = str(cache.get("industry_code") or "").strip()
        try:
            age = (date.fromisoformat(universe["asof"]) - date.fromisoformat(cache["cached_at"][:10])).days
        except (KeyError,TypeError,ValueError):
            age = -1
        verified = bool(code.isdigit() and src.get("corp_code") and cache.get("corp_code")==src["corp_code"] and 0<=age<365)
        row["industry_code"] = code if verified else None
        row["industry_confidence"] = "high" if verified else None
        sector,confidence = classify_sector(stock.get("sector_raw"))
        model = financial_model_for(ticker, code if verified else None,
                                    classify_industry_code(code) if verified else (sector if confidence=="high" else None))
        row["financial_model"] = model
        row["financial_period"] = fiscal_period
        if ticker in PREFERRED_SHARE_PARENT:
            row["screening_class"]="known_preferred_share"
        elif model:
            row["screening_class"]="financial"
            row["financial_model"]=model
            row["financial_observations"]=financial.get(ticker)
        else:
            row["screening_class"]="industrial_or_unclassified"
        try:
            if src["status"]=="source_received":
                raw=read(SOURCE/"source-rows"/(ticker+".json"))
                if not isinstance(raw,list) or not raw:
                    raise ValueError("Missing source rows")
                receipts=sorted({str(r["rcept_no"]) for r in raw if r.get("rcept_no")})
                if receipts!=src.get("receipts"):
                    raise ValueError("Receipt mismatch")
                source_received+=1
                if row["screening_class"]=="industrial_or_unclassified":
                    metrics=extract_financial(raw,ticker=ticker,financial_year=year,fs_div=src.get("scope"),xbrl_note=notes.get(ticker))
                    row["da_source"]=metrics["capital_metric_audit"].get("da_source")
                    row["xbrl_note_status"]=metrics["capital_metric_audit"].get("xbrl_note_status")
                    quality=metrics["industry_metric_quality"]
                    values=metrics["industry_metrics"]
                    row["quality"]=quality
                    row["raw_values"]={k:v if isinstance(v,(int,float)) and math.isfinite(v) else None for k,v in values.items()}
                    row["admitted"]=admitted_industry_metrics(values,quality,year)
        except (ValueError,KeyError,TypeError,OSError,ArithmeticError) as exc:
            row["replay_error"]=type(exc).__name__
        if row["screening_class"]=="industrial_or_unclassified":
            for metric in METRICS:
                q=row.get("quality",{}).get(metric,{})
                if row.get("admitted",{}).get(metric) is not None:
                    state,reason="정상","자동검증 통과"
                else:
                    state=q.get("state","주의")
                    if state=="정상":
                        state="주의"
                    reason=q.get("reason",row.get("replay_error",src["status"]))
                    exceptions.append({"ticker":ticker,"name":row["name"],"metric":metric,"state":state,"reason":reason})
                states[metric][state]+=1
        results.append(row)
        print("TOP300 REPLAY RECORD",json.dumps({"ticker":ticker,"class":row["screening_class"],
              "source":row["source_status"],"admitted_count":sum(v is not None for v in row.get("admitted",{}).values()),
              "replay_error":row.get("replay_error")},ensure_ascii=False),flush=True)
    # Calculate the 10-point industry factor separately; never present
    # the industry score as the full 100-point stock recommendation.
    # Exclude duplicate issuer records from industrial comparisons, even
    # when an unfamiliar preferred share is absent from the static map.
    issuer_counts=Counter(r["corp_code"] for r in results
                          if r.get("corp_code") and r["screening_class"]!="known_preferred_share")
    for row in results:
        if row.get("corp_code") and issuer_counts[row["corp_code"]]>1:
            row["screening_class"]="duplicate_issuer_pending"
    peers = [{"ticker":r["ticker"],"industry_code":r["industry_code"],
              "industry_confidence":r["industry_confidence"],
              "financial_model":r["financial_model"],"financial_period":fiscal_period,
              "financial_observations":r.get("financial_observations"),
              "industry_metrics":r.get("admitted",{})}
             for r in results if r["screening_class"] not in ("known_preferred_share","duplicate_issuer_pending")]
    peers.extend(external_financial_peers(listed_records=financial))
    score_status=Counter()
    peer_counts=Counter()
    for row in results:
        if row["screening_class"] in ("known_preferred_share","duplicate_issuer_pending"):
            relative={"status":"전략 제외","official_score":None,"provisional_score":None,"coverage_pct":0}
        else:
            relative=score_industry_relative(peers,row["ticker"])
        row["industry_relative"]=relative
        score_status[relative["status"]]+=1
        if relative.get("official_score") is not None:
            peer_counts["complete_10_point_factor"]+=1
        elif relative.get("coverage_pct",0)>0:
            peer_counts["partial_factor"]+=1
        else:
            peer_counts["unavailable_factor"]+=1
    counts=Counter(r["screening_class"] for r in results)
    slots=sum(sum(c.values()) for c in states.values())
    admitted=sum(c["정상"] for c in states.values())
    financial_counts=Counter()
    financial_slots=Counter()
    for r in results:
        if r["screening_class"]=="financial":
            model=r["financial_model"]
            financial_slots[model]+=len(FINANCIAL_MODELS.get(model,{}))
            record=r.get("financial_observations") or {}
            financial_counts[model]+=sum(comparable_observation(record,k,model,fiscal_period) is not None for k in FINANCIAL_MODELS.get(model,{}))
    summary={"source_run":45625150031,"universe_asof":universe["asof"],"financial_year":year,
             "rule_version":RULE_VERSION,"universe_count":300,"source_received":source_received,
             "screening_classes":dict(counts),"industry_auto_admission":{k:dict(v) for k,v in states.items()},
             "industry_admitted_pct":round(100*admitted/slots,2) if slots else None,
             "financial_observation_counts":dict(financial_counts),"financial_expected_slots":dict(financial_slots),
             "xbrl_da_fallback_count":sum(r.get("da_source")=="same_receipt_xbrl_cf_adjustments" for r in results),
             "xbrl_note_status_counts":dict(Counter(r.get("xbrl_note_status") for r in results if r.get("xbrl_note_status"))),
             "exception_count":len(exceptions),"exception_reasons":dict(Counter(e["reason"] for e in exceptions)),
             "verified_industry_code_count":sum(r["industry_code"] is not None for r in results),
             "duplicate_issuer_pending_count":sum(r["screening_class"]=="duplicate_issuer_pending" for r in results),
             "industry_factor_status":dict(score_status),"industry_factor_coverage_counts":dict(peer_counts),
             "release_gate":"not_verified",
             "warning":"Exact cached codes require source identity and date match; missing codes remain unclassified. This replay checks the 10-point industry factor only, not full eight-factor scores or release eligibility."}
    (OUT/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"records.json").write_text(json.dumps(results,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    (OUT/"exceptions.json").write_text(json.dumps(exceptions,ensure_ascii=False,indent=2),encoding="utf-8")
    print("TOP300 AUTO REPLAY SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
