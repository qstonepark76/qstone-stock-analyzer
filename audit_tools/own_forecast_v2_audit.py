"""Two-vintage, sector/scope-specific own forecast candidate replay.
2024 selection, 2025 holdout, 2026 forward estimates. Receipt dates guard
against lookahead; final restatement/period reconciliation remains required.
"""
import sys,json,math
from pathlib import Path
from datetime import date
from collections import defaultdict,Counter
sys.path.insert(0,"scripts")
sys.path.insert(0,"audit_tools")
from own_forecast import fetch,pick,valid_receipt,read,DART_KEY
from fundamental_candidate import number,transition
from metric_quality import account_check,source_check
from own_forecast_v2 import candidates,change,error,choose
from outlook_candidate import score,WEIGHTS,curve
from outlook_combined_candidate import combined
METRICS={"sales_forecast_growth":"sales","operating_profit_forecast_growth":"op","earnings_forecast_revision":"net"}
def fit_inputs(a,q,scope,group,quarters):
    out={}
    ar=pick(q,"assets",("thstrm_amount","frmtrm_amount"))
    asset_ratio=None
    if group!="industrial" and account_check([ar]):
        x,y=number(ar,"thstrm_amount"),number(ar,"frmtrm_amount")
        if x is not None and y is not None and y>0 and x>0:asset_ratio=x/y
    for k,key in (("sales","sales"),("op","op"),("net","owner_net" if scope=="CFS" else "net")):
        aa=pick(a,key,("thstrm_amount",))
        qq=pick(q,key,("thstrm_add_amount","frmtrm_add_amount"))
        if not account_check([aa,qq]) or aa["account_id"]!=qq["account_id"]:continue
        last,current,prior=number(aa,"thstrm_amount"),number(qq,"thstrm_add_amount"),number(qq,"frmtrm_add_amount")
        if None in (last,current,prior):continue
        if k=="sales" and (last<=0 or min(current,prior)<0 or prior>last):continue
        v=candidates(last,current,prior,quarters,asset_ratio if k!="sales" else None)
        if k=="sales":v={m:n for m,n in v.items() if n>=0}
        out[k]={"models":v,"last":last,"current_ytd":current,"prior_ytd":prior,"annual_receipt":aa["rcept_no"],"quarter_receipt":qq["rcept_no"],"account_id":aa["account_id"],"currency":aa["currency"],"asset_ratio":asset_ratio}
    return out
def main():
    if not DART_KEY:raise SystemExit("DART credential unavailable")
    u=read("replay-source/universe.json");a=read("replay-source/report.json")
    asof=date.fromisoformat(u["asof"]);year=asof.year
    assert year==2026 and a["year"]==2025 and len(u["stocks"])==300
    fin={r["ticker"]:r for r in read("financial/records.json")}
    source={r["ticker"]:r for r in a["records"]}
    train=defaultdict(lambda:defaultdict(list));hold=defaultdict(lambda:defaultdict(list))
    inputs={};failures=[]
    for x in u["stocks"]:
        t=x["ticker"];s=source[t]
        if s["status"]!="source_received" or not s.get("corp_code"):continue
        scope=s["scope"];corp=s["corp_code"]
        group="industrial";classification="non_financial"
        if t in fin:
            group=fin[t]["model"];classification=fin[t]["classification"]
            if fin[t]["corp_code"]!=corp:continue
            if group in ("bank_group","operating_holding","investment_holding") and scope!="CFS":continue
            if group=="unclassified":continue
        # Separate every business model and accounting scope, never pool with
        # industrial firms to manufacture a passing financial-sector result.
        groupkey=group+"|"+scope
        try:
            annual25=read("replay-source/source-rows/"+t+".json")
            if not source_check(annual25,2025,scope) or not valid_receipt(str(annual25[0]["rcept_no"]),asof):continue
            if sorted({str(r["rcept_no"]) for r in annual25})!=s.get("receipts"):continue
            annual24=fetch(corp,2024,"11011",scope,date(2025,11,24))
            annual23=fetch(corp,2023,"11011",scope,date(2024,11,24))
            # Current and historical forecast vintages use identical horizons.
            annuals={2023:annual23,2024:annual24,2025:annual25}
            for y in (2024,2025,2026):
                curr={}
                for q,code,cut in ((2,"11012",date(y,8,31)),(3,"11014",date(y,11,24))):
                    raw=fetch(corp,y,code,scope,cut)
                    f=fit_inputs(annuals[y-1],raw,scope,group,q)
                    curr[q]=f
                    if y==2026:continue
                    for k,z in f.items():
                        actual=pick(annuals[y],"owner_net" if k=="net" and scope=="CFS" else k,("thstrm_amount",))
                        if not account_check([actual]) or actual["currency"]!=z["currency"] or actual["account_id"]!=z["account_id"]:continue
                        actual_value=number(actual,"thstrm_amount")
                        if actual_value is None:continue
                        bucket=train if y==2024 else hold
                        for m,v in z["models"].items():
                            bucket[(groupkey,k,q)][m].append({"ticker":t,"error":error(actual_value,v),"baseline_error":error(actual_value,z["last"])})
                if y==2026:inputs[t]={"group":groupkey,"classification":classification,"quarters":curr}
        except (KeyError,TypeError,ValueError,OSError) as e:
            failures.append({"ticker":t,"error":type(e).__name__})
        if len(inputs) and len(inputs)%25==0:print("OWN V2 PROGRESS",len(inputs),flush=True)
    gates={}
    # For earnings revision require same chosen model at both horizons.
    for g,k,q in sorted(train):
        if q!=3:continue
        min_n=20 if g.startswith("industrial|") else 5
        gate=choose(train[(g,k,3)],hold[(g,k,3)],min_n)
        if not gate:continue
        if k=="net":
            m=gate["model"]
            tr=train[(g,k,2)].get(m,[]);te=hold[(g,k,2)].get(m,[])
            n=len(te);err=sum(r["error"] for r in te)/n if n else None;base=sum(r["baseline_error"] for r in te)/n if n else None
            gate["q2_holdout"]={"n":n,"smape":err,"baseline":base}
            gate["candidate_pass"]=gate["candidate_pass"] and len(tr)>=min_n and n>=min_n and err<=base
        gates[g+"|"+k]=gate
    v1={r["ticker"]:r for r in read("prior-own/audit-own-forecast/records.json")}
    baseg=read("prior-own/audit-own-forecast/summary.json")["backtest"]
    ledger=read("data/analyst_reports.json")["reports"]
    market={r["ticker"]:r for r in read("data/history/"+asof.strftime("%Y%m%d")+".json")}
    result=[];added=Counter();replaced=Counter();symmetric=Counter();groups=defaultdict(Counter)
    for x in u["stocks"]:
        t=x["ticker"];m=market.get(t,{})
        ext=score(dict(x,close=m.get("close") if m.get("market_cap")==x.get("market_cap") else None),ledger,asof)
        r=combined(ext,v1.get(t),baseg,asof,t)
        current=inputs.get(t)
        if current:
            g=current["group"];q=current["quarters"]
            for field,k in METRICS.items():
                if r["detail"][field]["observed"]:continue
                gate=gates.get(g+"|"+k,{})
                if gate.get("candidate_pass") is not True:continue
                model=gate["model"];now=q[3].get(k,{})
                c=now.get("models",{}).get(model)
                p=now.get("last")
                prev=None
                if k=="net":
                    prev=q[2].get(k,{})
                    if prev.get("currency")!=now.get("currency") or prev.get("account_id")!=now.get("account_id"):continue
                    p=prev.get("models",{}).get(model)
                v=change(c,p,k!="sales")
                if v is None:continue
                value,basis=v
                d=r["detail"][field]
                # V2 selection is experimental; prior V1 score remains fallback
                # when newer candidate is not validated on its own group.
                if d["points"] is None:added[field]+=1
                else:replaced[field]+=1
                if basis=="symmetric_profit_change":symmetric[field]+=1
                points=round(max(0,min(1,.5+value/400)) if basis=="symmetric_profit_change" else curve(field,value),4)
                d.update({"points":points,"value":value,"observed":False,"status":"own_model_candidate","source_kind":"qstone_model_forecast","model_version":"v2","change_basis":basis,"transition":transition(c,p) if k!="sales" else None,"current":now,"previous":prev,"model":model,"validation_group":g,"classification":current["classification"],"backtest":gate})
                groups[g][field]+=1
        d=r["detail"];observed=sum(WEIGHTS[k] for k in d if d[k]["observed"])
        own=sum(WEIGHTS[k] for k in d if d[k]["status"]=="own_model_candidate")
        calc=sum(WEIGHTS[k] for k in d if d[k]["points"] is not None)
        r.update({"name":x["name"],"points_out_of_10":round(sum(v["points"] or 0 for v in d.values()),4),"external_observed_pct":observed*10,"own_model_coverage_pct":own*10,"evidence_plus_model_pct":(observed+own)*10,"policy_calculation_pct":calc*10,"full_policy_score_available":calc==10})
        result.append(r)
    summary={"universe":300,"v2_input_issuers":len(inputs),"gates":gates,"added_slots":dict(added),"replaced_slots":dict(replaced),"symmetric_changes":dict(symmetric),"v2_group_usage":{g:dict(v) for g,v in groups.items()},"failures":len(failures),
      "field_counts":{k:{"external":sum(r["detail"][k]["observed"] for r in result),"own_model":sum(r["detail"][k]["status"]=="own_model_candidate" for r in result),"missing":sum(r["detail"][k]["points"] is None for r in result),"policy_zero":sum(r["detail"][k]["status"]=="missing_zero_policy" for r in result)} for k in WEIGHTS},
      **{k:round(sum(r[k] for r in result)/300,2) for k in ("external_observed_pct","own_model_coverage_pct","evidence_plus_model_pct","policy_calculation_pct")},
      "full_candidate_count":sum(r["full_policy_score_available"] for r in result),"official":0,"release_gate":"not_verified","warning":"Mixed v1/v2 candidate only; V2 two-vintage and subgroup gates, proposed classifications, symmetric scoring curve and final independent point-in-time validation remain pending. No missing broker evidence counted as data."}
    out=Path("audit-own-forecast-v2");out.mkdir(exist_ok=True)
    for name,v in (("records.json",result),("summary.json",summary),("failures.json",failures)):
        (out/name).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False))
    print("OWN V2 SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
