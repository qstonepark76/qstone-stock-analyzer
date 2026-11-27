"""Test a fixed five-column KIS layout hypothesis against saved DART actuals.
Do not infer official units or account definitions from numeric agreement.
The sample is diagnostic, not independent holdout or official model admission.
"""
import json,math
from pathlib import Path
from collections import Counter
from leading_kis_estimate_schema import period,reconcile
from leading_kis_outlook_probe import rows,numeric
from fundamental_candidate import select,number
from metric_quality import account_check,source_check
from final_leading_model import finite

def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")

def layout(outputs,year):
    dates=[period(x.get("dt")) for x in rows(outputs.get("output4"))]
    income=rows(outputs.get("output2"))
    if len(dates)!=5 or len(income)!=6 or not all(dates):return None
    if [(d["year"],d["month"]) for d in dates]!=[(y,12) for y in range(year-2,year+3)]:return None
    if any(d["kind"]=="forecast" for d in dates[:3]) or any(d["kind"]!="forecast" for d in dates[3:]):return None
    # Explicit hypothesis from pilot shapes: alternating absolute values and
    # YoY growth rows, numeric data1..data5, not a text label in data1.
    if any(not set("data"+str(i) for i in range(1,6))<=set(r) for r in income):return None
    return {k:{"levels":[numeric(income[j]["data"+str(i)]) for i in range(1,6)],
               "growth":[numeric(income[j+1]["data"+str(i)]) for i in range(1,6)]}
            for k,j in (("sales",0),("op",2),("net_candidate",4))}

def unique_scale(v,actual):
    if not finite(v) or not finite(actual) or v==0 or actual==0:return None
    possible=reconcile(v,actual)
    return possible[0] if len(possible)==1 else None

def check_amounts(table,raw,year,scope,older=None):
    if not source_check(raw,year,scope):return {}
    out={}
    for metric in ("sales","op","net_candidate"):
        variants=("net","owner_net") if metric=="net_candidate" and scope=="CFS" else ("net",) if metric=="net_candidate" else (metric,)
        comparisons=[]
        for k in variants:
            row=select(raw,k)
            if not account_check([row]) or row["currency"]!="KRW":continue
            actual=[number(row,f) for f in ("bfefrmtrm_amount","frmtrm_amount","thstrm_amount")]
            # If the third historical period isn't in the current filing,
            # only recover it from a same-scope prior filing reconciled to FY-1.
            if actual[0] is None and older and source_check(older,year-1,scope):
                previous=select(older,k)
                if account_check([row,previous]) and previous.get("account_id")==row.get("account_id") and finite(actual[1]) and number(previous,"thstrm_amount")==actual[1]:
                    actual[0]=number(previous,"frmtrm_amount")
            checks=[{"year":year-2+i,"kis":v,"dart":a,"scale":unique_scale(v,a)}
                    for i,(v,a) in enumerate(zip(table[metric]["levels"][:3],actual)) if finite(v) and finite(a) and v!=0 and a!=0]
            scales={r["scale"] for r in checks}
            passed=len(checks)>=2 and len(scales)==1 and None not in scales and any(r["year"]==year for r in checks)
            comparisons.append({"account":k,"checks":checks,"passed":passed,"scale":next(iter(scales)) if passed else None})
        out[metric]=comparisons
    return out

def growth_checks(table):
    out=[]
    for k,r in table.items():
        for i in range(1,5):
            a,b=r["levels"][i-1:i+1];g=r["growth"][i]
            if not all(finite(v) for v in (a,b,g)) or a<=0 or b<0:continue
            actual=100*(b/a-1)
            # Report alternatives separately; do not pick a favorable scale
            # and do not treat this as documented provider semantics.
            out.append({"metric":k,"column":i+1,"reported":g,"implied_pct":actual,
                        "raw_pct_match":abs(g-actual)<=.15,
                        "tenths_pct_match":abs(g/10-actual)<=.15})
    return out

def main():
    out=Path("audit-leading-kis-layout");out.mkdir(exist_ok=True)
    audit=read("replay-source/report.json");year=int(audit["year"]);source={r["ticker"]:r for r in audit["records"]}
    records=read("pilot/raw_candidates.json");c=Counter();scales=Counter();detail=[]
    for r in records:
        t=r["ticker"];e=r.get("estimate-perform",{});s=source.get(t,{})
        c["pilot_issuers"]+=1
        table=layout(e.get("outputs",{}),year)
        if table is None:c["layout_unavailable"]+=1;continue
        c["layout_candidate"]+=1
        path=Path("replay-source/source-rows")/(t+".json");old=Path("stage5/recovered-prior")/(t+".json")
        if not path.exists():c["dart_missing"]+=1;continue
        raw=read(path)
        if sorted({str(x.get("rcept_no")) for x in raw})!=s.get("receipts") or any(str(x.get("corp_code"))!=str(s.get("corp_code")) for x in raw):
            c["source_mismatch"]+=1;continue
        older=read(old) if old.exists() else None
        if older and any(str(x.get("corp_code"))!=str(s.get("corp_code")) for x in older):older=None
        checks=check_amounts(table,raw,year,s.get("scope"),older)
        growth=growth_checks(table)
        c["growth_pairs"]+=len(growth)
        c["growth_raw_pct_matches"]+=sum(x["raw_pct_match"] for x in growth)
        c["growth_tenths_pct_matches"]+=sum(x["tenths_pct_match"] for x in growth)
        primary=[checks.get(k,[]) for k in ("sales","op")]
        compatible=[x[0]["scale"] for x in primary if len(x)==1 and x[0]["passed"]]
        ok=len(compatible)==2 and compatible[0]==compatible[1]
        c["sales_actual_reconciled"]+=bool(primary[0] and primary[0][0]["passed"])
        c["op_actual_reconciled"]+=bool(primary[1] and primary[1][0]["passed"])
        if ok:
            c["sales_op_common_scale"]+=1;scales[str(compatible[0])]+=1
        n=[x for x in checks.get("net_candidate",[]) if x["passed"] and ok and x["scale"]==compatible[0]]
        c["net_unique_account_match"]+=len(n)==1
        c["net_account_ambiguous"]+=len(n)>1
        # The forecast growth is exposed only as a research candidate,
        # retaining acquisition date and never adding to an older snapshot.
        a,b=table["op"]["levels"][2:4]
        candidate=100*(b/a-1) if ok and finite(a) and finite(b) and a>0 and b>=0 else None
        c["positive_base_op_forecast_candidate"]+=finite(candidate)
        detail.append({"ticker":t,"observed_at":e.get("observed_at"),"scope":s.get("scope"),"checks":checks,"growth_checks":growth,
            "common_scale_candidate":compatible[0] if ok else None,"op_forecast_growth_candidate":candidate,
            "status":"hypothesis_only","official":False})
    summary={"counts":dict(c),"common_scales":dict(scales),"official_admitted":0,
             "note":"Fixed row-order hypothesis motivated by pilot; same-sample DART comparison cannot establish official schema, accounting scope or forecast vintage. No changes to scores."}
    write(out/"summary.json",summary);write(out/"issuer_reconciliation.json",detail)
    print("KIS FIVE COLUMN LAYOUT REVIEW",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
