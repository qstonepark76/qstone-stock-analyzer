"""Candidate-only coverage experiment. Keep all original ratios and scores.
Five economic slots each worth 2 points. Alternatives compare against the
same alternative metric on a matched peer set, never the primary distribution.
Parent-code comparisons remain experimental until business comparability review.
"""
import json
import sys
from collections import Counter
from pathlib import Path
sys.path.insert(0,"scripts")
from collect import pick_standard_account
from metric_quality import source_check, account_check, finite
from industry_relative import METRICS, percentile_score, MIN_VALID_PEERS

SLOTS={
 "profitability":(("operating_margin_pct",True),("net_margin_pct",True)),
 "capital_efficiency":(("roic_pct",True),("roa_pct",True)),
 "asset_efficiency":(("asset_turnover",True),),
 "solvency":(("net_debt_to_ebitda",False),("debt_equity_pct",False)),
 "cash_generation":(("cash_conversion_pct",True),("cash_flow_margin_pct",True)),
}
def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
def number(row,key="thstrm_amount"):
    try:
        v=float(str(row[key]).replace(",",""))
        return v if finite(v) else None
    except (KeyError,TypeError,ValueError):
        return None
def alternatives(raw,year,scope):
    if scope!="CFS" or not source_check(raw,year,scope):
        return {}
    def pick(sec,*ids):
        return pick_standard_account(raw,sec,[],ids)
    inc=("IS","CIS")
    sales=pick(inc,"ifrs-full_Revenue","ifrs_Revenue")
    # Use total consolidated net income, not parent-attributable income,
    # for total-asset and total-sales denominators.
    net=pick(inc,"ifrs-full_ProfitLoss","ifrs_ProfitLoss")
    assets=pick(("BS",),"ifrs-full_Assets","ifrs_Assets")
    liabilities=pick(("BS",),"ifrs-full_Liabilities","ifrs_Liabilities")
    equity=pick(("BS",),"ifrs-full_Equity","ifrs_Equity")
    cfo=pick(("CF",),"ifrs-full_CashFlowsFromUsedInOperatingActivities","ifrs_CashFlowsFromUsedInOperatingActivities")
    out={}
    def ratio(k,n,d,positive=True):
        if account_check([n,d]):
            x,y=number(n),number(d)
            if x is not None and y is not None and y>0 and (not positive or x>=0):
                v=100*x/y
                if finite(v):
                    out[k]=v
    ratio("net_margin_pct",net,sales,False)
    ratio("debt_equity_pct",liabilities,equity)
    ratio("cash_flow_margin_pct",cfo,sales,False)
    if account_check([net,assets]):
        n,a,b=number(net),number(assets),number(assets,"frmtrm_amount")
        if n is not None and a is not None and b is not None and a>0 and b>0:
            v=100*n/((a+b)/2)
            if finite(v):
                out["roa_pct"]=v
    return out

def score(target,peers,allow_parent=False,allow_alternatives=False):
    code=target.get("industry_code")
    if not code or not code.isdigit():
        return {"covered_slots":0,"details":{}}
    groups=[("exact",lambda p:p.get("industry_code")==code)]
    if allow_parent and len(code)>=3:
        groups.append(("parent3",lambda p:len(p.get("industry_code") or "")>=3 and p["industry_code"][:3]==code[:3]))
    details={}
    for slot,choices in SLOTS.items():
        # Prefer primary metric with exact peers, then its parent group,
        # then the alternative with exact peers and finally parent peers.
        for metric,higher in (choices if allow_alternatives else choices[:1]):
            value=target["metrics"].get(metric)
            if not finite(value):
                continue
            for group,match in groups:
                selected=[p for p in peers if match(p) and finite(p["metrics"].get(metric))]
                if len(selected)<MIN_VALID_PEERS:
                    continue
                pct=percentile_score(value,[p["metrics"][metric] for p in selected],higher)
                details[slot]={"metric":metric,"peer_group":group,"peer_count":len(selected),"value":value,"points":round(pct/50,4),"alternative":metric!=choices[0][0]}
                break
            if slot in details:
                break
    return {"covered_slots":len(details),"experimental_points":round(sum(x["points"] for x in details.values()),4),"details":details}

def main():
    audit=read("replay-source/report.json")
    records=read("audit-top300-replay/records.json")
    external=read("audit-wider-peers/peers.json")
    src={r["ticker"]:r for r in audit["records"]}
    assert len(records)==len(src)==300
    targets=[]
    seen={r["corp_code"] for r in records if r.get("corp_code")}
    seen_tickers={r["ticker"] for r in records}
    for r in records:
        if r["screening_class"]!="industrial_or_unclassified" or not r.get("corp_code") or not r.get("industry_code") or r.get("industry_confidence") not in ("high","verified"):
            continue
        s=src[r["ticker"]]
        values=dict(r.get("admitted",{}))
        if s["status"]=="source_received":
            raw=read("replay-source/source-rows/"+r["ticker"]+".json")
            if sorted({str(x.get("rcept_no")) for x in raw if x.get("rcept_no")})==s.get("receipts"):
                values.update(alternatives(raw,audit["year"],s.get("scope")))
        targets.append({"ticker":r["ticker"],"corp_code":r["corp_code"],"industry_code":r["industry_code"],"metrics":values})
    peers=list(targets)
    for r in external:
        if not r.get("peer_only") or r.get("financial_model") or r.get("industry_confidence")!="verified" or r.get("financial_year")!=audit["year"] or not r.get("corp_code") or r["corp_code"] in seen or r["ticker"] in seen_tickers:
            continue
        seen.add(r["corp_code"])
        seen_tickers.add(r["ticker"])
        peers.append({"ticker":r["ticker"],"corp_code":r["corp_code"],"industry_code":r["industry_code"],"metrics":r["industry_metrics"]})
    out=[]
    counts={}
    denominator=sum(r["screening_class"]=="industrial_or_unclassified" for r in records)
    for label,pool,parent,alt in (("original",targets,False,False),("wider_exact",peers,False,False),("wider_parent",peers,True,False),("wider_parent_alternatives",peers,True,True)):
        result=[{"ticker":t["ticker"],**score(t,pool,parent,alt)} for t in targets]
        full=sum(x["covered_slots"]==5 for x in result)
        slots=sum(x["covered_slots"] for x in result)
        counts[label]={"complete":full,"full_pct":round(100*full/denominator,2),"slot_pct":round(100*slots/(5*denominator),2),"partial":sum(0<x["covered_slots"]<5 for x in result),"alternative_slots":sum(d["alternative"] for x in result for d in x["details"].values()),"parent_slots":sum(d["peer_group"]=="parent3" for x in result for d in x["details"].values())}
        out.append({"scenario":label,"records":result})
    summary={"industrial_denominator":denominator,"verified_targets":len(targets),"added_peers":len(peers)-len(targets),"scenarios":counts,"release_gate":"not_verified","warning":"Experimental scenarios only. Alternatives use same-metric distributions; additional peer data currently contains primary metrics only. Parent groups and alternative score equivalence require independent validation."}
    dest=Path("audit-coverage-experiment")
    dest.mkdir(exist_ok=True)
    (dest/"records.json").write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    (dest/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print("COVERAGE EXPERIMENT SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__":
    main()
