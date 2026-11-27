"""Focused gap and forecast-error diagnosis, using already saved evidence.
No new forecasts are admitted from names alone. No repeated full-universe fetch.
"""
import sys,json,statistics,re
from pathlib import Path
from collections import Counter,defaultdict
sys.path.insert(0,"scripts")
from fundamental_candidate import IDS,number
from forecast_extended_models import canonical
from metric_quality import account_check
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def main():
    summary=read("merged/summary.json");records=read("merged/records.json")
    missing=read("reuse/missing.json");source={r["ticker"]:r for r in read("replay-source/report.json")["records"]}
    fin={r["ticker"]:r for r in read("financial/records.json")}
    filings={r["ticker"]:r for r in read("gaps/records.json")}
    inputs={};hold=defaultdict(list)
    for path in sorted(Path("batches").glob("*/batch.json")):
        b=read(path);inputs.update(b["inputs"])
        for r in b["hold"]:
            for m,rows in r["models"].items():hold[(r["group"],r["metric"],r["quarter"],m)].extend(rows)
    errors=[]
    for key,g in summary["gates"].items():
        group,k=key.rsplit("|",1)
        for q in ((2,3) if k=="net" else (3,)):
            rows=hold.get((group,k,q,g["model"]),[])
            if not rows:continue
            vals=[r["error"] for r in rows]
            errors.append({"group":group,"metric":k,"quarter":q,"model":g["model"],"candidate_pass":g["candidate_pass"],"n":len(vals),"mean":statistics.mean(vals),"median":statistics.median(vals),"over_10":sum(v>10 for v in vals),"over_50":sum(v>50 for v in vals),"max":max(vals),"top_errors":sorted(rows,key=lambda r:r["error"],reverse=True)[:5]})
    result=[];counts=Counter()
    for r in missing:
        t=r["ticker"];metric=r["metric"];s=source[t];f=filings.get(t,{})
        k={"sales_forecast_growth":"sales","operating_profit_forecast_growth":"op","earnings_forecast_revision":"net"}[metric]
        key="owner_net" if k=="net" and s.get("scope")=="CFS" else k
        i=inputs.get(t,{});g=i.get("group");q=i.get("quarters",{})
        now=q.get("3",{}).get(k);prev=q.get("2",{}).get(k)
        annual_path=Path("replay-source/source-rows")/(t+".json")
        a=read(annual_path) if annual_path.exists() else []
        candidates=[]
        for x in a:
            if x.get("sj_div") not in ("IS","CIS"):continue
            label=re.sub(r"\s+","",str(x.get("account_nm") or ""))
            # Include exact totals and observed potential aliases, never admit
            # component accounts (interest, insurance, fees) as total revenue.
            if label in ("매출액","매출","수익(매출액)","영업수익","영업수익합계","영업이익","영업이익(손실)","영업손익","당기순이익","당기순이익(손실)","지배기업의소유주에게귀속되는당기순이익","지배기업소유주지분순이익") or x.get("account_id") in IDS[key][1:]:
                candidates.append({n:x.get(n) for n in ("account_id","account_nm","account_detail","sj_div","currency","thstrm_amount","frmtrm_amount","rcept_no")})
        if s["status"]!="source_received":reason="annual_source_or_identity_missing"
        elif not any(x.get("account_id") in IDS[key][1:] and account_check([x]) for x in candidates):reason="standard_annual_account_missing_or_ambiguous"
        elif not i:reason="target_group_or_scope_unavailable"
        elif not now:reason="quarter_account_or_comparable_input_missing"
        elif k=="net" and not prev:reason="prior_forecast_input_missing"
        elif not summary["gates"].get(g+"|"+k,{}).get("candidate_pass"):reason="group_holdout_gate_missing_or_failed"
        else:reason="selected_model_or_growth_baseline_unavailable"
        counts[(metric,reason)]+=1
        item={**r,"reason":reason,"financial_model":fin.get(t,{}).get("model"),"group":g,"annual_account_candidates":candidates,"current_input":now,"previous_input":prev,"filing_candidates":len(f.get("filings",[])),"quarter_statements":len(f.get("quarter_candidates",[]))}
        result.append(item)
        print("FOCUSED GAP",json.dumps({"ticker":t,"metric":metric,"reason":reason,"accounts":[[x["account_id"],x["account_nm"]] for x in candidates]},ensure_ascii=False),flush=True)
    out=Path("audit-forecast-diagnostics");out.mkdir(exist_ok=True)
    data={"missing_slots":len(result),"missing_securities":len({r["ticker"] for r in result}),"reasons":[{"metric":m,"reason":r,"count":n} for (m,r),n in sorted(counts.items())],"holdout_error_distributions":errors,"warning":"Saved errors are sMAPE values only; sign changes, actual small denominators and one-off causes cannot be inferred from errors alone. Account labels are diagnostic, not evidence of equivalence."}
    for name,v in (("summary.json",data),("missing.json",result)):
        (out/name).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False))
    print("FOCUSED DIAGNOSTIC SUMMARY",json.dumps(data,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
