"""Read-only top-300 financial extraction preflight, not a release validation.

Use the same market-cap ranking as the candidate collector. Do not modify
production data, caches, recommendation history or the dashboard.
"""
import json
from pathlib import Path
import math
import audit_v33_dart as audit
from collect import latest_krx_rows, normalize

OUT = Path("audit-top300")
def main():
    OUT.mkdir(exist_ok=True)
    try:
        asof, rows = latest_krx_rows()
        unique = {}
        for row in normalize(rows):
            cap = row.get("market_cap")
            if not isinstance(cap,(int,float)) or not math.isfinite(cap) or cap <= 0:
                continue
            ticker = row["ticker"]
            if ticker in unique and unique[ticker] != row:
                raise ValueError("Conflicting KRX duplicate")
            unique[ticker] = row
        selected = sorted(unique.values(),key=lambda x:(-x["market_cap"],x["ticker"]))[:300]
        if len(selected) != 300:
            raise ValueError("Fewer than 300 distinct market-cap covered tickers")
    except Exception as exc:
        print("TOP300 UNIVERSE FAILED",type(exc).__name__,flush=True)
        return 1
    universe = {"asof":asof.isoformat(),"count":len(selected),
                "stocks":[{k:r.get(k) for k in ("ticker","name","market_cap","sector_raw")} for r in selected]}
    (OUT/"universe.json").write_text(json.dumps(universe,ensure_ascii=False,indent=2),encoding="utf-8")
    print("TOP300 UNIVERSE",asof.isoformat(),len(selected),flush=True)
    audit.SAMPLE = {r["ticker"]:r["name"] for r in selected}
    audit.OUT = OUT
    report = audit.audit()
    report["universe_asof"] = asof.isoformat()
    report["scope"] = "raw extraction preflight; industry classification, financial scope and independent review incomplete; no official scoring"
    report["release_gate"] = "not_verified"
    report["coverage_warning"] = "industrial_coverage excludes known financial allowlist only; unclassified financial entities and preferred shares may remain, so this is not final eligible industrial coverage"
    (OUT/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    print("TOP300 PREFLIGHT SUMMARY",json.dumps({k:v for k,v in report.items() if k!="records"},ensure_ascii=False),flush=True)
    return 0 if report.get("received_count",0) >= 297 else 1

if __name__ == "__main__":
    raise SystemExit(main())
