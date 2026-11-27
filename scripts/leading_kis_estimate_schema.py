"""Inspect archived KIS estimate tables against annual DART actuals.
The KIS HTS 6632 help describes Korea Investment research center estimates,
not independent multi-broker consensus. Do not promote into official scores.
"""
import json,re,math
from pathlib import Path
from collections import Counter,defaultdict
from datetime import datetime
from leading_kis_outlook_probe import rows,numeric
from fundamental_candidate import select,number
from metric_quality import source_check,account_check

HELP="https://securities.koreainvestment.com/pro_help/6632.html"
METRICS={"매출액":"sales","영업수익":"sales","영업이익":"op","영업이익(손실)":"op","당기순이익":"net","당기순이익(손실)":"net","지배주주순이익":"owner_net","지배기업소유주지분순이익":"owner_net"}
SCALES=(1,1000,1000000,100000000)
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
def norm(x):return re.sub(r"\s+","",str(x or ""))
def period(x):
    # Explicit year/month, optional explicit forecast/actual marker.
    s=norm(x)
    m=re.fullmatch(r"(20\d{2})[./-]?(0[1-9]|1[0-2])(?:월)?(?:\(?([EAea]|추정|예상|실적|확정)\)?)?",s)
    if not m:return None
    return {"year":int(m[1]),"month":int(m[2]),"kind":"forecast" if m[3] in ("E","e","추정","예상") else "actual" if m[3] in ("A","a","실적","확정") else "unspecified"}
def reconcile(a,b):
    # Candidate inferred scale only, not proof of official unit/basis.
    if not a or not b or a*b<=0:return []
    return [scale for scale in SCALES if abs(a*scale-b)<=max(abs(b)*.005,scale*.5)]
def main():
    out=Path("audit-leading-kis-estimate-schema");out.mkdir(exist_ok=True)
    records=read("pilot/raw_candidates.json");audit=read("replay-source/report.json")
    year=int(audit["year"]);src={r["ticker"]:r for r in audit["records"]}
    counts=Counter();labels=Counter();periods=Counter();shape=Counter();checks=[];detail=[]
    for r in records:
        t=r["ticker"];e=r.get("estimate-perform",{})
        if e.get("status")!="source_candidate":continue
        counts["responded"]+=1
        o=e.get("outputs",{});headers=rows(o.get("output1"));dates=rows(o.get("output4"));income=rows(o.get("output2"));indicators=rows(o.get("output3"))
        # Only a 4-column table with four explicit dates and data1 label
        # is comparable to the expected raw response. No shifted columns.
        parsed=[period(x.get("dt")) for x in dates]
        periods.update(str(x.get("dt","")) for x in dates)
        labels.update("income|"+str(x.get("data1","")) for x in income)
        labels.update("indicator|"+str(x.get("data1","")) for x in indicators)
        shape[(len(dates),len(income),len(indicators))]+=1
        counts["income_rows"]+=len(income);counts["indicator_rows"]+=len(indicators)
        meta=src.get(t,{});p=Path("replay-source/source-rows")/(t+".json")
        entry={"ticker":t,"observed_at":e.get("observed_at"),"provider_estdate":[h.get("estdate") for h in headers],"period_labels":[x.get("dt") for x in dates],"periods":parsed,"income_labels":[x.get("data1") for x in income],"source_kind":"KIS research estimate candidate","official":False}
        detail.append(entry)
        if len(dates)!=4 or not all(parsed) or len({(x["year"],x["month"]) for x in parsed})!=4:
            counts["column_period_mapping_unresolved"]+=1;continue
        counts["four_explicit_periods"]+=1
        if not p.exists() or meta.get("scope") not in ("CFS","OFS"):continue
        raw=read(p)
        if not source_check(raw,year,meta["scope"]) or sorted({str(x["rcept_no"]) for x in raw})!=meta.get("receipts"):continue
        for i,per in enumerate(parsed,2):
            if per["year"]!=year or per["month"]!=12 or per["kind"]=="forecast":continue
            for row in income:
                k=METRICS.get(norm(row.get("data1")));v=numeric(row.get("data"+str(i)))
                if not k or v is None:continue
                dart=select(raw,k)
                if not account_check([dart]) or dart.get("currency")!="KRW":continue
                actual=number(dart,"thstrm_amount")
                scales=reconcile(v,actual)
                checks.append({"ticker":t,"metric":k,"period":per,"kis_value":v,"dart_actual_krw":actual,"scope":meta["scope"],"receipt":dart["rcept_no"],"matching_scale_candidates":scales,"official":False})
    counts["actual_comparison_pairs"]=len(checks)
    counts["unique_scale_matches"]=sum(len(x["matching_scale_candidates"])==1 for x in checks)
    result={"status":"diagnostic_only","source_help":HELP,"source_kind":"single research center, not broker consensus","counts":dict(counts),"table_shapes":[{"period_rows":k[0],"income_rows":k[1],"indicator_rows":k[2],"issuers":v} for k,v in shape.items()],"row_labels":dict(labels),"period_labels":dict(periods),"official_admitted":0,"note":"Units, actual/forecast markers, fiscal scope, and column mapping must be explicitly established. Historical actual agreement is a diagnostic, never automatic admission."}
    for n,v in (("summary.json",result),("issuer_schema.json",detail),("actual_reconciliation.json",checks)):write(out/n,v)
    print("KIS ESTIMATE SCHEMA REVIEW",json.dumps(result,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
