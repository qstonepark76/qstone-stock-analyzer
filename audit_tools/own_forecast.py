"""Q Stone Park own forecast experiment. Actual YTD + prior-year remaining period.
Never writes an external forecast ledger. Point-in-time receipt checks; one-year
retrospective backtest, not a production approval or guaranteed accuracy.
"""
import json,sys,math,time
from datetime import date
from pathlib import Path
sys.path.insert(0,"scripts")
from collect import DART_KEY,request_with_retry
from fundamental_candidate import IDS,number,profit_change
from metric_quality import account_check,source_check
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def pick(rows,key,fields):
    section,*ids=IDS[key]
    candidates=[r for r in rows if r.get("sj_div") in section.split() and r.get("account_id") in ids and account_check([r])]
    signatures={(r.get("currency"),*(number(r,f) for f in fields)) for r in candidates}
    return candidates[0] if len(signatures)==1 else None
def valid_receipt(r,cutoff):
    try:return len(r)==14 and date.fromisoformat(r[:4]+"-"+r[4:6]+"-"+r[6:8])<=cutoff
    except (ValueError,TypeError):return False
def fetch(corp,year,code,scope,cutoff):
    resp=request_with_retry("GET","https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json",params={"crtfc_key":DART_KEY,"corp_code":corp,"bsns_year":str(year),"reprt_code":code,"fs_div":scope},timeout=(5,15))
    resp.raise_for_status();p=resp.json()
    if p.get("status") in ("010","011","012","020"):raise SystemExit("DART access or quota unavailable")
    rows=p.get("list",[]) if p.get("status")=="000" else []
    receipts={r.get("rcept_no") for r in rows}
    if len(receipts)!=1 or not valid_receipt(next(iter(receipts)),cutoff):return []
    if not all(str(r.get("corp_code"))==corp and str(r.get("bsns_year"))==str(year) and str(r.get("reprt_code"))==code and r.get("fs_div") in (None,"",scope) for r in rows):return []
    time.sleep(.25)
    return rows
def forecast(annual,quarter,scope):
    data={}
    for key in ("sales","op","owner_net" if scope=="CFS" else "net"):
        a=pick(annual,key,("thstrm_amount",))
        q=pick(quarter,key,("thstrm_add_amount","frmtrm_add_amount"))
        if not account_check([a,q]):continue
        last=number(a,"thstrm_amount");current=number(q,"thstrm_add_amount");prior=number(q,"frmtrm_add_amount")
        if None in (last,current,prior):continue
        if key=="sales" and (last<=0 or current<0 or prior<0 or prior>last):continue
        est=current+last-prior
        if not math.isfinite(est):continue
        data["net" if key=="owner_net" else key]={"estimate":est,"prior_year_actual":last,
          "growth_pct":100*(est/last-1) if last>0 else None,"profit_transition_value":profit_change(est,last) if key!="sales" else None,
          "currency":a["currency"],"annual_receipt":a["rcept_no"],"quarter_receipt":q["rcept_no"],"account_id":a["account_id"],
          "method":"ytd_plus_prior_remaining_period_v1"}
    return data
def smape(a,b):
    return 200*abs(a-b)/(abs(a)+abs(b)) if abs(a)+abs(b)>0 else 0
def main():
    if not DART_KEY:raise SystemExit("DART credential unavailable")
    audit=read("replay-source/report.json");u=read("replay-source/universe.json")
    cutoff=date.fromisoformat(u["asof"]);year=cutoff.year;prev=year-1
    assert audit["year"]==prev
    backdate=date(prev,cutoff.month,cutoff.day)
    out=Path("audit-own-forecast");out.mkdir(exist_ok=True)
    rows=[];backtests=[];failures=[]
    for s in audit["records"]:
        if s["status"]!="source_received" or not s.get("corp_code"):continue
        t=s["ticker"];corp=s["corp_code"];scope=s["scope"]
        try:
            annual=read("replay-source/source-rows/"+t+".json")
            if not source_check(annual,prev,scope) or not valid_receipt(str(annual[0]["rcept_no"]),cutoff):continue
            if sorted({str(r["rcept_no"]) for r in annual})!=s.get("receipts"):continue
            q3=fetch(corp,year,"11014",scope,cutoff);q2=fetch(corp,year,"11012",scope,cutoff)
            # Use only same fiscal/calendar year and accounting scope.
            current=forecast(annual,q3,scope);previous=forecast(annual,q2,scope)
            values={}
            for metric,k in (("sales_forecast_growth","sales"),("operating_profit_forecast_growth","op")):
                x=current.get(k,{})
                if x.get("growth_pct") is not None:values[metric]={**x,"value":x["growth_pct"],"metric":metric}
            n,p=current.get("net",{}),previous.get("net",{})
            if n and p and n["currency"]==p["currency"] and p["estimate"]>0:
                v=100*(n["estimate"]/p["estimate"]-1)
                if math.isfinite(v):values["earnings_forecast_revision"]={"metric":"earnings_forecast_revision","value":v,"current":n,"previous":p,"method":"same_fiscal_year_q3_vs_q2_net_income_forecast_v1"}
            old=fetch(corp,prev-1,"11011",scope,backdate)
            past_q=fetch(corp,prev,"11014",scope,backdate)
            past=forecast(old,past_q,scope)
            for k,x in past.items():
                actual=pick(annual,"owner_net" if k=="net" and scope=="CFS" else k,("thstrm_amount",))
                if not account_check([actual]) or actual["currency"]!=x["currency"]:continue
                a=number(actual,"thstrm_amount")
                if a is not None:backtests.append({"ticker":t,"metric":k,"actual":a,"forecast":x["estimate"],"baseline":x["prior_year_actual"],"error":smape(a,x["estimate"]),"baseline_error":smape(a,x["prior_year_actual"])})
            rows.append({"ticker":t,"scope":scope,"period_end":str(year)+"-12-31","asof":u["asof"],"source_kind":"qstone_model_forecast","values":values,"raw_current":current,"raw_previous":previous})
        except (KeyError,TypeError,ValueError,OSError) as e:failures.append({"ticker":t,"error":type(e).__name__})
        if len(rows)%25==0:print("OWN FORECAST PROGRESS",len(rows),flush=True)
    gates={}
    for k in ("sales","op","net"):
        x=[r for r in backtests if r["metric"]==k]
        mean=sum(r["error"] for r in x)/len(x) if x else None
        base=sum(r["baseline_error"] for r in x)/len(x) if x else None
        # Preliminary candidate admission: at least 20 actual matched outcomes,
        # no worse than naive prior-year actual. Not an independent validation.
        gates[k]={"n":len(x),"smape":mean,"baseline_smape":base,"candidate_pass":len(x)>=20 and mean<=base}
    summary={"universe":300,"rows":len(rows),"backtest":gates,"observed_external":0,"failures":len(failures),"official":False}
    for path,payload in (("records.json",rows),("backtests.json",backtests),("summary.json",summary),("failures.json",failures)):
        (out/path).write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False))
    print("OWN FORECAST SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
