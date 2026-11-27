"""Read-only KIS historical flow and adjusted-price audit; no orders or data commits."""
import os,json,time,argparse
from datetime import date,timedelta
from pathlib import Path
from statistics import pstdev
from final_leading_model import finite
from collect import kis_access_token,kis_request_with_retry, num

HOST="https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/"
def read(p):return json.loads(p.read_text(encoding="utf-8"))
def session_rows(rows,keys,allowed):
    out={};conflicts=set()
    for r in rows:
        d=str(r.get("stck_bsop_date",""))
        if d not in allowed:continue
        vals=tuple(num(r,k) for k in keys)
        if not all(finite(v) for v in vals):continue
        if d in out and out[d]!=vals:conflicts.add(d)
        out[d]=vals
    for d in conflicts:out.pop(d,None)
    return out

def flow_metrics(rows,days):
    def ratio(window,i):
        if any(d not in rows or rows[d][2]<=0 for d in window):return None
        return 100*sum(rows[d][i] for d in window)/sum(rows[d][2] for d in window)
    result={}
    for i,label in enumerate(("foreign","institution")):
        for n in (5,20,60):
            if len(days)>=n:result[f"{label}_{n}d"]=ratio(days[-n:],i)
        a=result.get(label+"_5d");b=ratio(days[-20:-5],i) if len(days)>=20 else None
        if a is not None and b is not None:result[label+"_acceleration"]=min(a,a-b)
    if all(result.get(k) is not None for k in ("foreign_5d","institution_5d")):
        result["joint_buy"]=min(result["foreign_5d"],result["institution_5d"])
    return {k:v for k,v in result.items() if v is not None}

def price_metrics(rows,days,raw_close,index):
    # Price adjustments must be enabled and latest close reconcile to KRX.
    if not days or days[-1] not in rows or not finite(raw_close) or raw_close<=0:return {}
    if abs(rows[days[-1]][0]/raw_close-1)>.0001:return {}
    def window(n):
        ds=days[-n:]
        if len(ds)!=n or any(d not in rows or rows[d][0]<=0 for d in ds):return []
        return [rows[d][0] for d in ds]
    out={}
    for n in (5,20,60):
        p=window(n+1)
        if p:out[f"momentum_{n}d"]=100*(p[-1]/p[0]-1)
    p=window(21)
    if p:
        out["volatility_20d"]=pstdev(100*(b/a-1) for a,b in zip(p,p[1:]))
        out["overheat"]=max(0,out["momentum_20d"])
        gap=100*(p[-1]/max(p[:-1])-1)
        out["breakout"]=gap if max(p[:-1])/min(p[:-1])<=1.10 else min(0,gap)
        q=[index.get(d) for d in days[-21:]]
        if all(finite(v) and v>0 for v in q):
            out["relative_acceleration"]=100*((p[-1]/p[-6]-1)-(q[-1]/q[-6]-1)-((p[-6]/p[0]-1)-(q[-6]/q[0]-1))/3)
    return out

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--data",type=Path,default=Path("data"))
    p.add_argument("--out",type=Path,default=Path("audit-leading-market"))
    p.add_argument("--limit",type=int,default=300)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    root=a.data
    asof=read(root/"latest.json")["as_of"];stamp=asof.replace("-","")
    # Require exact KRX session dates, rather than count returned rows.
    days=sorted(p.stem for p in (root/"history").glob("*.json") if len(p.stem)==8 and p.stem.isdigit() and p.stem<=stamp)[-61:]
    if len(days)<61 or days[-1]!=stamp:raise ValueError("Missing 61-session calendar")
    market=read(root/"history"/(stamp+".json"))
    stocks=sorted((r for r in market if finite(r.get("market_cap")) and r["market_cap"]>0),key=lambda x:(-x["market_cap"],x["ticker"]))[:300]
    volumes={d:{r["ticker"]:r.get("volume") for r in read(root/"history"/(d+".json"))} for d in days}
    index={d:read(root/"index_history"/(d+".json")).get("close") for d in days if (root/"index_history"/(d+".json")).exists()}
    key=os.getenv("KIS_APP_KEY","").strip();secret=os.getenv("KIS_APP_SECRET","").strip()
    if not key or not secret:raise RuntimeError("KIS credentials missing")
    token=kis_access_token(key,secret)
    headers={"authorization":"Bearer "+token,"appkey":key,"appsecret":secret,"custtype":"P"}
    def call(path,tr,params):
        try:
            r=kis_request_with_retry(HOST+path,headers=dict(headers,tr_id=tr),params=params).json()
            if str(r.get("rt_cd"))!="0":return [],"provider_"+str(r.get("msg_cd","error"))
            rows=r.get("output2") or []
            return ([rows] if isinstance(rows,dict) else rows),None
        except Exception as e:return [],type(e).__name__
        finally:time.sleep(.7)
    results={}
    for i,s in enumerate(stocks[:a.limit],1):
        t=s["ticker"];common={"FID_COND_MRKT_DIV_CODE":"J","FID_INPUT_ISCD":t}
        flow={};errors=[]
        # Date-based pagination, bounded to 4 calls; duplicates/conflicts withheld.
        allrows=[];end=stamp
        for page in range(4):
            r,e=call("investor-trade-by-stock-daily","FHPTJ04160001",dict(common,FID_INPUT_DATE_1=end,FID_ORG_ADJ_PRC="",FID_ETC_CLS_CODE=""))
            if e:errors.append(e);break
            allrows.extend(r)
            valid=[str(x.get("stck_bsop_date","")) for x in r if str(x.get("stck_bsop_date","")).isdigit() and len(str(x.get("stck_bsop_date","")))==8 and str(x.get("stck_bsop_date",""))<=end]
            if not valid:break
            oldest=min(valid)
            if oldest<=days[-60]:break
            end=(date.fromisoformat(oldest[:4]+"-"+oldest[4:6]+"-"+oldest[6:])-timedelta(days=1)).strftime("%Y%m%d")
        flow=session_rows(allrows,("frgn_ntby_qty","orgn_ntby_qty","acml_vol"),set(days))
        # Reconcile trading volume against KRX for the same sessions. Missing
        # or inconsistent sessions never produce an exact-window flow metric.
        flow={d:v for d,v in flow.items() if finite(volumes[d].get(t)) and v[2]==volumes[d][t]}
        raw,e=call("inquire-daily-itemchartprice","FHKST03010100",dict(common,FID_INPUT_DATE_1=days[0],FID_INPUT_DATE_2=stamp,FID_PERIOD_DIV_CODE="D",FID_ORG_ADJ_PRC="0"))
        if e:errors.append(e)
        prices=session_rows(raw,("stck_clpr",),set(days))
        pm=price_metrics(prices,days,s.get("close"),index)
        fm=flow_metrics(flow,days)
        results[t]={"flow":fm,"price":pm,"flow_sessions":len(flow),"price_sessions":len(prices),"errors":errors}
        if i%25==0:print("MARKET AUDIT",i,"/",a.limit,flush=True)
    payload={"asof":asof,"basis":"KIS exact KRX sessions; adjusted price FID_ORG_ADJ_PRC=0; KRX close reconciliation; KOSPI benchmark","records":results}
    (a.out/"market.json").write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False),encoding="utf-8")
    keys={k for r in results.values() for k in [*r["flow"],*r["price"]]}
    summary={"asof":asof,"count":len(results),"coverage":{k:sum(k in r["flow"] or k in r["price"] for r in results.values()) for k in sorted(keys)}}
    (a.out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False),encoding="utf-8")
    print("LEADING MARKET SUMMARY",json.dumps(summary),flush=True)
if __name__=="__main__":main()
