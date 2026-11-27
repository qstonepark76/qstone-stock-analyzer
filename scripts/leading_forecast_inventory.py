"""Audit available verified external forecast fields; never parse title as estimate."""
import json
from pathlib import Path
from collections import Counter
from datetime import date,datetime
from final_leading_model import finite
def main():
    root=Path("data")
    asof=date.fromisoformat(json.loads((root/"latest.json").read_text())["as_of"])
    ledger=json.loads((root/"analyst_reports.json").read_text())["reports"]
    usable=[]
    for r in ledger:
        try:
            published=date.fromisoformat(r["published_at"])
            verified=datetime.fromisoformat(r["verified_at"].replace("Z","+00:00")).date()
        except (KeyError,ValueError,TypeError):continue
        if published<=verified<=asof and r.get("verification_method") and str(r.get("source_url","")).startswith("https://"):
            usable.append(r)
    keys=Counter(k for r in usable for k,v in r.items() if v is not None)
    # Exact comparable forecast values require fiscal period, forecast metric,
    # numeric amount and unit plus verified basis, not report title or rating.
    valid=[r for r in usable if r.get("forward_looking") is True and r.get("basis_verified") is True and
           r.get("metric") in ("operating_profit","net_income") and finite(r.get("value")) and
           r.get("period_end") and r.get("unit")]
    result={"asof":asof.isoformat(),"all_reports":len(ledger),"point_in_time_verified_reports":len(usable),
            "covered_tickers":len({r["ticker"] for r in usable}),"field_counts":dict(keys),
            "comparable_forecast_records":len(valid),
            "status":"source_gap" if not valid else "requires_matched_vintage_validation"}
    out=Path("audit-leading-forecast");out.mkdir(exist_ok=True)
    (out/"summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print("LEADING FORECAST INVENTORY",json.dumps(result),flush=True)
if __name__=="__main__":main()
