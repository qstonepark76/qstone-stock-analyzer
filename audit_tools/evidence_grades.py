"""Source provenance grades and non-comparable alternative metric diagnostics.
A grade describes evidence lineage, not an empirical probability of accuracy.
No provisional alternative value is inserted into the original score.
"""
import math
from collections import Counter
from pathlib import Path
import json
import sys
sys.path.insert(0,"scripts")
from collect import pick_standard_account
from metric_quality import source_check, account_check, finite
from financial_industry import FINANCIAL_MODELS, comparable_observation
from industry_relative import METRICS

def evidence_grade(value,admitted,source=None,derived=False,notes=False,crosschecked=False):
    if not finite(value):
        return "F"
    if not admitted:
        return "E"
    if source=="OpenDART" or source=="FISIS":
        return "C" if notes else "B" if derived else "A"
    return "D" if crosschecked else "E"

def number(r,k):
    try:
        v=float(str(r[k]).replace(",","").strip())
        return v if math.isfinite(v) else None
    except (ValueError,TypeError,KeyError):
        return None

def alternatives(rows,year,scope,cap):
    if scope!="CFS" or not source_check(rows,year,scope):
        return {}
    sales=pick_standard_account(rows,("IS","CIS"),[],["ifrs-full_Revenue","ifrs_Revenue"])
    op=pick_standard_account(rows,("IS","CIS"),[],["dart_OperatingIncomeLoss","ifrs-full_ProfitLossFromOperatingActivities"])
    net=pick_standard_account(rows,("IS","CIS"),[],["ifrs-full_ProfitLossAttributableToOwnersOfParent"])
    cfo=pick_standard_account(rows,("CF",),[],["ifrs-full_CashFlowsFromUsedInOperatingActivities"])
    out={}
    if account_check([sales,net]) and sales.get("currency")=="KRW" and finite(cap) and cap>0:
        s,n=number(sales,"thstrm_amount"),number(net,"thstrm_amount")
        if s is not None and s>0 and n is not None and n<=0:
            out["psr"]={"value":cap/s,"grade":"B","reason":"nonpositive_net_income","status":"alternative_only"}
    if account_check([op]):
        p,c=number(op,"frmtrm_amount"),number(op,"thstrm_amount")
        if p is not None and c is not None:
            if p<0<c:
                out["profit_transition"]={"value":"loss_to_profit","status":"alternative_only"}
            elif p>0>c:
                out["profit_transition"]={"value":"profit_to_loss","status":"alternative_only"}
            elif p<0 and c<0:
                out["profit_transition"]={"value":"loss_narrowed" if c>p else "loss_widened" if c<p else "unchanged_loss","status":"alternative_only"}
        if c is not None and c<=0 and account_check([sales,cfo,op]):
            s,f=number(sales,"thstrm_amount"),number(cfo,"thstrm_amount")
            if s is not None and s>0 and f is not None:
                out["cash_flow_margin_pct"]={"value":100*f/s,"grade":"B","reason":"nonpositive_operating_profit","status":"alternative_only"}
    return out

def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))

def main():
    audit=read("replay-source/report.json")
    universe=read("replay-source/universe.json")
    records=read("audit-top300-replay/records.json")
    sources={r["ticker"]:r for r in audit["records"]}
    caps={r["ticker"]:r["market_cap"] for r in universe["stocks"]}
    assert len(records)==len(sources)==len(caps)==300
    grades=Counter()
    alt_counts=Counter()
    result=[]
    for r in records:
        ticker=r["ticker"]
        src=sources[ticker]
        fields={}
        alt={}
        if r["screening_class"]=="industrial_or_unclassified":
            for k in METRICS:
                value=r.get("raw_values",{}).get(k)
                approved=r.get("admitted",{}).get(k) is not None
                grade=evidence_grade(value,approved,"OpenDART",derived=True,notes=k=="net_debt_to_ebitda" and r.get("da_source")=="same_receipt_xbrl_cf_adjustments")
                fields[k]={"grade":grade,"value":value,"admitted":approved,"reason":r.get("quality",{}).get(k,{}).get("reason",src["status"])}
            if src["status"]=="source_received" and r.get("industry_code") and r.get("industry_confidence") in ("high","verified"):
                raw=read("replay-source/source-rows/"+ticker+".json")
                receipts=sorted({str(x.get("rcept_no")) for x in raw if x.get("rcept_no")})
                if receipts==src.get("receipts"):
                    alt=alternatives(raw,audit["year"],src.get("scope"),caps[ticker])
        elif r["screening_class"]=="financial":
            model=r["financial_model"]
            record=r.get("financial_observations") or {}
            for k in FINANCIAL_MODELS.get(model,{}):
                obs=record.get("metrics",{}).get(k,{})
                normalized=comparable_observation(record,k,model,str(audit["year"])+"-12")
                value=normalized["value"] if normalized else obs.get("value")
                grade=evidence_grade(value,normalized is not None,obs.get("source"))
                fields[k]={"grade":grade,"value":value,"admitted":normalized is not None}
        grades.update(x["grade"] for x in fields.values())
        alt_counts.update(alt.keys())
        result.append({"ticker":ticker,"name":r["name"],"class":r["screening_class"],"metric_evidence":fields,"alternatives":alt})
    out=Path("audit-evidence-grades")
    out.mkdir(exist_ok=True)
    summary={"count":300,"metric_grade_counts":dict(grades),"alternative_counts":dict(alt_counts),
             "financial_unclassified_count":sum(r.get("financial_model")=="financial_unclassified" for r in records),
             "warning":"Grades describe provenance under current automatic checks, not independent accuracy. Alternatives are diagnostic only; no score substitution or denominator change."}
    (out/"records.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print("EVIDENCE GRADE SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
