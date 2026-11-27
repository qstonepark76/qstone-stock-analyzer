"""Explain remaining direct-calculation gaps and peer-size bottlenecks.
Read actual saved audit rows; diagnostics only, no score rule changes.
"""
import json
import sys
from collections import Counter,defaultdict
from pathlib import Path
sys.path.insert(0,"scripts")
from collect import extract_financial
from direct_borrowing import direct_borrowing, debt_like
from metric_quality import admitted_industry_metrics

def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))

def main():
    records=read("audit-top300-replay/records.json")
    audit=read("replay-source/report.json")
    sources={r["ticker"]:r for r in audit["records"]}
    codes=Counter(r["industry_code"] for r in records if r.get("industry_code") and r["screening_class"]=="industrial_or_unclassified")
    parent_codes=Counter()
    for r in records:
        code=r.get("industry_code")
        if code and len(code)>=3 and r["screening_class"]=="industrial_or_unclassified":
            parent_codes[code[:3]]+=1
    reasons=Counter()
    unknown=Counter()
    patterns=defaultdict(list)
    groups=Counter()
    for r in records:
        if r["screening_class"]!="industrial_or_unclassified":
            continue
        t=r["ticker"]
        code=r.get("industry_code")
        if code and len(code)>=3:
            groups["exact_peer_ge5"]+=int(codes[code]>=5)
            groups["three_digit_peer_ge5"]+=int(parent_codes[code[:3]]>=5)
        src=sources[t]
        if src["status"]!="source_received":
            reasons["source_unavailable"]+=1
            continue
        if src.get("scope")!="CFS":
            reasons["non_consolidated"]+=1
            continue
        rows=read("replay-source/source-rows/"+t+".json")
        b=direct_borrowing(rows)
        m=extract_financial(rows,ticker=t,financial_year=audit["year"],fs_div=src["scope"])
        cap=m["capital_metric_audit"]
        admitted=admitted_industry_metrics(m["industry_metrics"],m["industry_metric_quality"],audit["year"])
        if admitted.get("roic_pct") is None:
            reasons["roic:"+b["status"]]+=1
        if admitted.get("net_debt_to_ebitda") is None:
            reasons["leverage:"+b["status"]]+=1
        for x in b.get("unknown",[]):
            unknown[(x["id"],x["name"])]+=1
        if b["status"]!="auto_pass":
            debt=[{"id":x.get("account_id"),"name":x.get("account_nm"),"current":x.get("thstrm_amount"),"previous":x.get("frmtrm_amount"),"currency":x.get("currency")} for x in rows if x.get("sj_div")=="BS" and str(x.get("account_detail") or "").strip() in ("","-") and debt_like(x)]
            pattern=tuple(sorted(set(str(x["id"])+":"+str(x["name"]) for x in debt)))
            patterns[pattern].append({"ticker":t,"name":r["name"],"status":b["status"],"debt":debt,"capital_audit":cap})
    ranked=sorted(patterns.items(),key=lambda x:-len(x[1]))
    out=Path("audit-direct-diagnostics")
    out.mkdir(exist_ok=True)
    summary={"universe":len(records),"direct_gap_reasons":dict(reasons),"peer_size_sensitivity":dict(groups),"distinct_unresolved_debt_layouts":len(ranked),"most_frequent_unknown_accounts":[{"id":k[0],"name":k[1],"count":v} for k,v in unknown.most_common(30)],"warning":"Three-digit peer groups are a diagnostic scenario only; official exact-code scoring is unchanged."}
    (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"debt_patterns.json").write_text(json.dumps([{"pattern":list(k),"count":len(v),"records":v} for k,v in ranked],ensure_ascii=False,indent=2),encoding="utf-8")
    print("DIRECT GAP SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
    for k,v in ranked[:12]:
        print("DIRECT DEBT PATTERN",json.dumps({"count":len(v),"sample":v[0]},ensure_ascii=False),flush=True)
if __name__=="__main__":
    main()
