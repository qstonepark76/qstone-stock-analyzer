"""Join existing frozen DART source artifacts, preserving receipt and scope."""
import json,argparse
from pathlib import Path
from datetime import date
from statistics import pstdev
from collections import Counter
from audit_final_leading_snapshot import build
from final_leading_model import evaluate,finite
from fundamental_candidate import derive,select,number,slots
from metric_quality import source_check,account_check

def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def receipt_day(receipt):
    try:return date(int(receipt[:4]),int(receipt[4:6]),int(receipt[6:8]))
    except (ValueError,TypeError,IndexError):return None

def margin_stability(raw):
    s,o=select(raw,"sales"),select(raw,"op")
    if not account_check([s,o]):return None
    v=[]
    for k in ("thstrm_amount","frmtrm_amount","bfefrmtrm_amount"):
        a,b=number(s,k),number(o,k)
        if a is None or b is None or a<=0:return None
        v.append(100*b/a)
    return pstdev(v)

def join(payload,source,replay):
    universe=read(source/"universe.json");audit=read(source/"report.json")
    rel=read(replay/"records.json")
    if universe["asof"]!=payload["asof"] or audit["universe_asof"]!=payload["asof"]:raise ValueError("source dates differ")
    rows={r["ticker"]:r for r in payload["stocks"]}
    sources={r["ticker"]:r for r in audit["records"]}
    rel={r["ticker"]:r for r in rel}
    stocks={r["ticker"]:r for r in universe["stocks"]}
    if len(rows)!=300 or not set(rows)==set(stocks)==set(rel)==set(sources):raise ValueError("universe mismatch")
    asof=date.fromisoformat(payload["asof"]);year=int(audit["year"]);period=f"{year}-12-31"
    for t,row in rows.items():
        r=rel[t];s=sources[t]
        row["industry_code"]=r["industry_code"] if r.get("industry_confidence")=="high" else None
        row["financial_model"]=r.get("financial_model")
        row["excluded"]=r["screening_class"] in ("known_preferred_share","duplicate_issuer_pending")
        if row["excluded"] or s["status"]!="source_received":continue
        raw=read(source/"source-rows"/(t+".json"))
        scope=s.get("scope")
        if not source_check(raw,year,scope):continue
        receipt=str(raw[0]["rcept_no"]);available=receipt_day(receipt)
        if [receipt]!=s.get("receipts") or not available or not date.fromisoformat(period)<=available<=asof:continue
        m=derive(raw,year,scope,stocks[t]["market_cap"],row["financial_model"])
        mapping=slots(m,row["financial_model"])
        # Alternative financial stability based on the same regulatory metric
        # as the relative factor is deliberately withheld to avoid duplicate weighting.
        for factor,items in mapping.items():
            for k,key in items.items():
                v=m.get(key)
                if not isinstance(v,dict) or not finite(v.get("value")):continue
                if k=="stability" and row["financial_model"] not in (None,"operating_holding"):continue
                if k in ("earnings_value","book_value") and key not in ("per","pbr"):continue
                if k=="sales_cagr" and v.get("basis")!="three_annual_observations_two_intervals":continue
                obs_day=asof.isoformat() if factor=="valuation" else period
                public_day=asof.isoformat() if factor=="valuation" else available.isoformat()
                row["metrics"][k]={"value":v["value"],"verified":True,
                    "source_ref":"OpenDART receipt "+receipt+" "+",".join(v.get("account_ids",[])),
                    "basis":str(year)+"|"+scope+"|"+v["basis"],"asof":obs_day,
                    "available_on":public_day,"metric_id":key,"lower_better":v.get("lower_better",False)}
        if row["financial_model"] in (None,"operating_holding") and scope=="CFS":
            def put(k,v,basis,lower=False):
                if finite(v):row["metrics"][k]={"value":v,"verified":True,"source_ref":"OpenDART receipt "+receipt,
                    "basis":str(year)+"|"+scope+"|"+basis,"asof":period,"available_on":available.isoformat(),"lower_better":lower}
            for k,old in (("roic","roic_pct"),("asset_turnover","asset_turnover"),("cash_conversion","cash_conversion_pct")):
                q=r.get("quality",{}).get(old,{})
                # Only previously admitted values from this exact receipt.
                if q.get("state")=="정상" and q.get("scope")=="CFS" and str(q.get("period"))==str(year):
                    put(k,r.get("admitted",{}).get(old),old)
            put("margin_stability",margin_stability(raw),"3 annual operating-margin standard deviation pp",True)
    return payload

def summary(result):
    out={"asof":result["asof"],"count":len(result["records"]),"coverage":result["coverage"],
         "excluded":sum(r["excluded"] for r in result["records"])}
    for model in ("base","leading"):
        rows=[r[model] for r in result["records"] if not r["excluded"]]
        out[model+"_weighted_coverage_pct"]=sum(r["coverage_pct"] for r in rows)/len(rows) if rows else None
        keys={k for r in rows for k in r["detail"]}
        out[model+"_slot_counts"]={k:sum(r["detail"].get(k,{}).get("points") is not None for r in rows) for k in sorted(keys)}
    return out

def merge_market(payload,market):
    if market["asof"]!=payload["asof"]:raise ValueError("market date mismatch")
    for row in payload["stocks"]:
        record=market["records"].get(row["ticker"],{})
        for family in ("flow","price"):
            for k,v in record.get(family,{}).items():
                if finite(v):
                    row["metrics"][k]={"value":v,"verified":True,"source_ref":"KIS read-only audit market.json:"+row["ticker"],
                        "basis":"KIS exact KRX sessions "+family+" "+k,"asof":payload["asof"],"available_on":payload["asof"]}
    return payload

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source",type=Path,default=Path("replay-source"))
    p.add_argument("--replay",type=Path,default=Path("audit-top300-replay"))
    p.add_argument("--data",type=Path,default=Path("data"))
    p.add_argument("--market",type=Path)
    p.add_argument("--out",type=Path,default=Path("audit-leading-fundamentals"))
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    payload=join(build(a.data),a.source,a.replay)
    if a.market:merge_market(payload,read(a.market))
    result=evaluate(payload)
    # Point-in-time full historical data certification remains separate.
    result["point_in_time_verified"]=False
    for n,v in (("observations.json",payload),("final-leading.json",result),("summary.json",summary(result))):
        (a.out/n).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    print("FINAL FUNDAMENTALS SUMMARY",json.dumps(summary(result),ensure_ascii=False),flush=True)
if __name__=="__main__":main()
