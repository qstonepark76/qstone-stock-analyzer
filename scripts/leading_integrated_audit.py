"""Combine immutable candidate evidence artifacts, and report backtest readiness."""
import json,argparse
from pathlib import Path
from final_leading_model import evaluate
from leading_fundamental_inputs import merge_market,summary

def read(p):return json.loads(p.read_text(encoding="utf-8"))
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--fundamental",type=Path,default=Path("audit-leading-fundamentals/observations.json"))
    p.add_argument("--market",type=Path,default=Path("audit-leading-market/market.json"))
    p.add_argument("--forecast",type=Path,default=Path("audit-leading-forecast/summary.json"))
    p.add_argument("--out",type=Path,default=Path("audit-leading-integrated"))
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    payload=read(a.fundamental)
    market=read(a.market)
    if set(market["records"])!={r["ticker"] for r in payload["stocks"]}:raise ValueError("market and fundamental universe mismatch")
    result=evaluate(merge_market(payload,market))
    result["point_in_time_verified"]=False
    result["candidate_only"]=True
    s=summary(result)
    f=read(a.forecast)
    if f["asof"]!=result["asof"]:raise ValueError("forecast date mismatch")
    s["forecast_inventory"]=f
    s["backtest"]={"status":"not_ready","verified_historical_snapshot_count":0,"evaluated_cohorts":0,
        "net_return_pct":None,"excess_return_pct":None,"reason":"No immutable full-model historical ranks with verified adjusted OHLC and benchmark; no historical performance claimed."}
    for name,data in (("final-leading.json",result),("summary.json",s),("observations.json",payload)):
        (a.out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    print("LEADING INTEGRATED SUMMARY",json.dumps(s,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
