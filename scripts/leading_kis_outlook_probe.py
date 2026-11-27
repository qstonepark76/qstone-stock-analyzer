"""Priority 1: probe official KIS read-only outlook APIs on a fixed pilot.
Capture actual acquisition timestamp; never backdate current estimates.
No order endpoints, no automatic scoring, no production or legacy writes.
"""
import os,json,time,re
from pathlib import Path
from collections import Counter
from datetime import datetime,date,timedelta,timezone
import requests
from collect import kis_access_token
from final_leading_model import finite

HOST="https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/"
KST=timezone(timedelta(hours=9))
DOC="https://github.com/koreainvestment/open-trading-api/tree/main/examples_llm/domestic_stock"
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
def rows(v):
    return v if isinstance(v,list) and all(isinstance(x,dict) for x in v) else [v] if isinstance(v,dict) and v else []
def numeric(v):
    try:
        f=float(str(v).replace(",","").strip())
        return f if finite(f) else None
    except (ValueError,TypeError):return None
def opinion_inventory(data,start,end):
    accepted=[];rejected=0
    for r in rows(data.get("output")):
        d=str(r.get("stck_bsop_date",""))
        try:
            day=datetime.strptime(d,"%Y%m%d").date()
        except ValueError:
            rejected+=1;continue
        if not start<=day<=end:
            rejected+=1;continue
        broker=str(r.get("mbcr_name") or "").strip()
        opinion=str(r.get("invt_opnn") or "").strip()
        target=numeric(r.get("hts_goal_prc"))
        if not opinion and (target is None or target<=0):
            rejected+=1;continue
        accepted.append({"report_date":day.isoformat(),"broker":broker or None,"opinion":opinion or None,
                         "target_price_candidate":target if target is not None and target>0 else None})
    return accepted,rejected

def select_pilot(payload,universe):
    eligible={r["ticker"]:r for r in payload["stocks"] if not r.get("excluded")}
    order=[s["ticker"] for s in sorted(universe["stocks"],key=lambda r:(-r["market_cap"],r["ticker"])) if s["ticker"] in eligible]
    top=order[:20]
    gaps=[t for t in order if t not in top and not eligible[t]["metrics"].get("rating")]
    n=min(20,len(gaps))
    return top+[gaps[i*len(gaps)//n] for i in range(n)] if n else top

def main():
    out=Path("audit-leading-kis-outlook");out.mkdir(exist_ok=True)
    payload=read("stage5/observations.json");universe=read("replay-source/universe.json")
    if payload["asof"]!=universe["asof"]:raise ValueError("date mismatch")
    if set(r["ticker"] for r in payload["stocks"])!=set(r["ticker"] for r in universe["stocks"]):raise ValueError("universe mismatch")
    targets=select_pilot(payload,universe)
    key=os.getenv("KIS_APP_KEY","").strip();secret=os.getenv("KIS_APP_SECRET","").strip()
    if not key or not secret:raise ValueError("KIS credentials unavailable")
    token=kis_access_token(key,secret)
    headers={"authorization":"Bearer "+token,"appkey":key,"appsecret":secret,"custtype":"P"}
    session=requests.Session()
    start_at=datetime.now(KST);end=start_at.date();start=end-timedelta(days=90)
    stats=Counter();errors=Counter();records=[];schemas=Counter();disabled=set()
    def call(name,tr,params):
        if name in disabled:return None,"endpoint_disabled"
        try:
            response=session.get(HOST+name,headers=dict(headers,tr_id=tr),params=params,timeout=(5,20),allow_redirects=False)
            if response.status_code in (401,403,429):
                # Stop all queries on authorization or rate limiting.
                disabled.update(("estimate-perform","invest-opinion"))
                return None,"http_"+str(response.status_code)
            response.raise_for_status();j=response.json()
            if not isinstance(j,dict):return None,"invalid_payload"
            if str(j.get("rt_cd"))!="0":
                code=str(j.get("msg_cd") or "provider_error")
                if code in ("EGW00201","EGW00123"):
                    disabled.update(("estimate-perform","invest-opinion"))
                return None,code
            return {"observed_at":datetime.now(KST).isoformat(),"continuation":response.headers.get("tr_cont",""),
                    "outputs":{k:v for k,v in j.items() if re.fullmatch(r"output[1-4]?",k)}} ,None
        except (requests.RequestException,ValueError) as e:return None,type(e).__name__
        finally:time.sleep(1)
    for t in targets:
        record={"ticker":t}
        for name,tr,params in (
            ("estimate-perform","HHKST668300C0",{"SHT_CD":t}),
            ("invest-opinion","FHKST663300C0",{"FID_COND_MRKT_DIV_CODE":"J","FID_COND_SCR_DIV_CODE":"16633","FID_INPUT_ISCD":t,"FID_INPUT_DATE_1":start.strftime("%Y%m%d"),"FID_INPUT_DATE_2":end.strftime("%Y%m%d")})):
            data,why=call(name,tr,params)
            stats[name+"_attempted"]+=int(why!="endpoint_disabled")
            if why:
                errors[name+"|"+why]+=1;record[name]={"status":why};continue
            stats[name+"_success"]+=1
            outs=data["outputs"]
            counts={k:len(rows(v)) for k,v in outs.items()}
            if any(counts.values()):stats[name+"_nonempty"]+=1
            if data["continuation"] in ("M","F"):stats[name+"_pagination_needed"]+=1
            for k,v in outs.items():
                for r in rows(v):
                    for field in r:schemas[name+"|"+k+"|"+field]+=1
            record[name]={**data,"status":"source_candidate","row_counts":counts}
            if name=="invest-opinion":
                candidates,rejected=opinion_inventory(outs,start,end)
                stats["opinion_valid_date_rows"]+=len(candidates)
                stats["opinion_rejected_rows"]+=rejected
                stats["opinion_broker_identified_rows"]+=sum(bool(x["broker"]) for x in candidates)
                stats["opinion_positive_target_rows"]+=sum(x["target_price_candidate"] is not None for x in candidates)
                stats["opinion_issuer_with_rows"]+=bool(candidates)
                record[name]["date_checked_candidates"]=candidates
            else:
                # data1..data5 meaning and units are not clear in official
                # sample. Preserve original values; no inferred forecast.
                record[name]["schema_review_required"]=True
        records.append(record)
        if len(records)%10==0:print("KIS OUTLOOK PILOT",len(records),"/",len(targets),flush=True)
        if len(disabled)==2:break
    s={"universe_asof":payload["asof"],"observed_at":start_at.isoformat(),"pilot_size":len(targets),
       "processed":len(records),"stats":dict(stats),"errors":dict(errors),"schema_fields":dict(schemas),
       "official_admitted":0,"status":"source_probe_only","official_reference":DOC,
       "limits":"One page per endpoint, no completeness assumption. No historic snapshot substitution; verify estimate period, units, accounting scope, broker identity and price adjustment basis before scoring."}
    write(out/"summary.json",s);write(out/"raw_candidates.json",records);write(out/"pilot_tickers.json",targets)
    print("KIS OUTLOOK PILOT SUMMARY",json.dumps(s,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
