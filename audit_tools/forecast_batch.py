"""Two-vintage, sector/scope-specific own forecast candidate replay.
2024 selection, 2025 holdout, 2026 forward estimates. Receipt dates guard
against lookahead; final restatement/period reconciliation remains required.
"""
import sys,json,math,os
from pathlib import Path
from datetime import date
from collections import defaultdict,Counter
sys.path.insert(0,"scripts")
sys.path.insert(0,"audit_tools")
from own_forecast import fetch,pick,valid_receipt,read,DART_KEY
from fundamental_candidate import number,transition
from metric_quality import account_check,source_check
from own_forecast_v2 import change,error,choose
from forecast_extended_models import canonical,component_inputs,extended_candidates
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
        if not account_check([aa,qq]) or canonical(aa["account_id"])!=canonical(qq["account_id"]):continue
        last,current,prior=number(aa,"thstrm_amount"),number(qq,"thstrm_add_amount"),number(qq,"frmtrm_add_amount")
        if None in (last,current):continue
        if k=="sales" and (last<=0 or current<0 or (prior is not None and (prior<0 or prior>last))):continue
        components=component_inputs(a,q,group,aa["currency"]) if k=="op" else []
        v=extended_candidates(last,current,prior,quarters,asset_ratio if k!="sales" else None,components)
        if k=="sales":v={m:n for m,n in v.items() if n>=0}
        out[k]={"models":v,"last":last,"current_ytd":current,"prior_ytd":prior,"annual_receipt":aa["rcept_no"],"quarter_receipt":qq["rcept_no"],"account_id":aa["account_id"],"currency":aa["currency"],"asset_ratio":asset_ratio,"component_evidence":components,"quarter_account_id":qq["account_id"]}
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
    base=read("reuse/missing.json")
    missing={r["ticker"] for r in base}
    # Target uncovered issuers first, financial specialists next, then a
    # deterministic sample for industrial candidate calibration. No preferred
    # shares in training; already verified issuer links reused only at scoring.
    eligible=[x for x in u["stocks"] if source[x["ticker"]]["status"]=="source_received"]
    selected={x["ticker"] for x in eligible if x["ticker"] in missing or x["ticker"] in fin}
    for scope in ("CFS","OFS"):
        sample=[x["ticker"] for x in eligible if x["ticker"] not in fin and source[x["ticker"]]["scope"]==scope]
        sample=sorted(sample)
        # evenly-spaced deterministic sample, not cherry-picked on outcomes
        selected.update(sample[i*len(sample)//min(40,len(sample))] for i in range(min(40,len(sample))))
    ordered=[x for x in eligible if x["ticker"] in selected]
    shard=int(os.environ.get("SHARD","0"));size=20
    subset=ordered[shard*size:(shard+1)*size]
    print("FORECAST BATCH",shard,len(subset),"total targeted",len(ordered),flush=True)
    for x in subset:
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
                        if not account_check([actual]) or actual["currency"]!=z["currency"] or canonical(actual["account_id"])!=canonical(z["account_id"]):continue
                        actual_value=number(actual,"thstrm_amount")
                        if actual_value is None:continue
                        bucket=train if y==2024 else hold
                        for m,v in z["models"].items():
                            bucket[(groupkey,k,q)][m].append({"ticker":t,"error":error(actual_value,v),"baseline_error":error(actual_value,z["last"])})
                if y==2026:inputs[t]={"group":groupkey,"classification":classification,"quarters":curr}
        except (KeyError,TypeError,ValueError,OSError) as e:
            failures.append({"ticker":t,"error":type(e).__name__})
        print("FORECAST BATCH ISSUER",t,len(inputs),flush=True)
    out=Path("forecast-batch");out.mkdir(exist_ok=True)
    payload={"shard":shard,"expected":[x["ticker"] for x in subset],"selected_count":len(ordered),"inputs":inputs,"train":[{"group":g,"metric":k,"quarter":q,"models":dict(v)} for (g,k,q),v in train.items()],"hold":[{"group":g,"metric":k,"quarter":q,"models":dict(v)} for (g,k,q),v in hold.items()],"failures":failures}
    (out/"batch.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False))
    print("FORECAST BATCH SUMMARY",json.dumps({"shard":shard,"expected":len(subset),"inputs":len(inputs),"failures":len(failures)}),flush=True)
if __name__=="__main__":main()
