"""Build a partial candidate audit from checked-in KRX/KIS/research snapshots.
No network calls, no production files written, no unverified price/forecast proxies.
The fixed 300 securities follow the existing cap selection; duplicate/preferred
issuer admission remains pending, so snapshot rows are screening-only.
"""
import argparse
import json
from pathlib import Path
from datetime import date,datetime
from statistics import mean
from final_leading_model import evaluate,finite
from outlook_candidate import broker_evidence, weighted
from financial_industry import financial_model_for

def read(path,default=None):
    if not path.exists(): return default
    return json.loads(path.read_text(encoding="utf-8"))

def build(root):
    latest=read(root/"latest.json")
    asof=date.fromisoformat(latest["as_of"])
    stamp=asof.strftime("%Y%m%d")
    market=read(root/"history"/(stamp+".json"))
    if not isinstance(market,list): raise ValueError("Missing exact-date market snapshot")
    eligible=[x for x in market if finite(x.get("market_cap")) and x["market_cap"]>0]
    universe=sorted(eligible,key=lambda x:(-x["market_cap"],x["ticker"]))[:300]
    if len(universe)!=300 or len({x["ticker"] for x in universe})!=300: raise ValueError("300 universe mismatch")
    flows=read(root/"kis_flow_cache.json",{})
    sectors=read(root/"sector_industry_cache.json",{})
    reports=read(root/"analyst_reports.json",{}).get("reports",[])
    def known(r):
        try:
            return datetime.fromisoformat(r["verified_at"].replace("Z","+00:00")).date()<=asof
        except (KeyError,TypeError,ValueError):return False
    reports=[r for r in reports if known(r)]
    paths=sorted(p for p in (root/"history").glob("*.json") if len(p.stem)==8 and p.stem.isdigit() and p.stem<=stamp)[-25:]
    history=[{r["ticker"]:r for r in read(p,[])} for p in paths]
    rows=[]
    for u in universe:
        t=u["ticker"]
        sector=sectors.get(t,{})
        code=sector.get("industry_code")
        row={"ticker":t,"name":u["name"],"industry_code":code,
             "financial_model":financial_model_for(t,code),"metrics":{}}
        # Preferred share/duplicate issuer exclusion requires source validation;
        # only partial scores are possible with this adapter by design.
        def put(k,v,source,basis):
            if finite(v):
                row["metrics"][k]={"value":v,"verified":True,"source_ref":source,
                    "basis":basis,"asof":asof.isoformat(),"available_on":asof.isoformat()}
        put("trading_value",u.get("trading_value"),"KRX data/history/"+stamp+".json","KRX daily trading value KRW")
        f=flows.get(t,{})
        fm=f.get("metrics",{})
        if f.get("as_of")==asof.isoformat() and fm.get("investor_flow_as_of")==stamp and fm.get("investor_flow_sessions")==5:
            source="KIS data/kis_flow_cache.json:"+t
            a=fm.get("foreign_flow_5d_pct"); b=fm.get("institution_flow_5d_pct")
            put("foreign_5d",a,source,"KIS five sessions net quantity / volume percent")
            put("institution_5d",b,source,"KIS five sessions net quantity / volume percent")
            if finite(a) and finite(b): put("joint_buy",min(a,b),source,"KIS min foreign/institution five sessions net quantity / volume percent")
        values=[h.get(t,{}).get("trading_value") for h in history]
        if len(values)==25 and paths[-1].stem==stamp and all(finite(v) and v>=0 for v in values) and mean(values[:20])>0:
            put("turnover_growth",100*(mean(values[-5:])/mean(values[:20])-1),
                "KRX data/history "+paths[0].stem+".."+stamp,"KRX trading value five vs preceding twenty sessions percent")
        ev=broker_evidence(u,reports,asof)
        rating=weighted([(v,w) for v,w,_,_ in ev["rating"]])
        if rating is not None:
            put("rating",rating,"; ".join(sorted({url for _,_,_,url in ev["rating"]})),
                "Verified broker rating recency weighted 0..3")
        rows.append(row)
    return {"asof":asof.isoformat(),"stocks":rows}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--data",type=Path,default=Path("data"))
    p.add_argument("--out",type=Path,default=Path("audit-final-leading"))
    a=p.parse_args()
    a.out.mkdir(parents=True,exist_ok=True)
    payload=build(a.data)
    result=evaluate(payload)
    result["source_scope"]="Partial checked-in snapshots only: no full forecast, adjusted-price, 20/60-day flow or fundamental inputs"
    for name,obj in (("observations.json",payload),("final-leading.json",result)):
        (a.out/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    summary={"asof":result["asof"],"count":len(result["records"]),"coverage":result["coverage"],
             "base_slot_counts":{k:sum(r["base"]["detail"].get(k,{}).get("points") is not None for r in result["records"]) for k in {k for r in result["records"] for k in r["base"]["detail"]}},
             "leading_slot_counts":{k:sum(r["leading"]["detail"].get(k,{}).get("points") is not None for r in result["records"]) for k in {k for r in result["records"] for k in r["leading"]["detail"]}}}
    (a.out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print("FINAL LEADING AUDIT",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__": main()
