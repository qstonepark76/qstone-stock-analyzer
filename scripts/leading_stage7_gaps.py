"""Targeted release-gap audit and KRX index source inventory.
Keep price-index and research proxies out of the approved total-return slot.
No legacy collection, trading or production writes.
"""
import json,time,os
from pathlib import Path
from collections import defaultdict,Counter
from statistics import median
from datetime import datetime
from final_leading_model import evaluate,finite,BASE,LEADING
from leading_fundamental_inputs import summary
from collect import S,KRX_KEY,parse_rows,txt,num
from dart_capital_metrics import extract_capital_metrics
from metric_quality import source_check

def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")

def factor_gaps(result):
    rows=[r for r in result["records"] if not r["excluded"]]
    factors={}
    for model,weights in (("base",BASE),("leading",LEADING)):
        factors[model]={}
        for factor,fields in weights.items():
            expected=len(rows)*sum(fields.values())
            observed=0;full=0;missing=Counter()
            for r in rows:
                slots={k:v for k,v in r[model]["detail"].items() if v["factor"]==factor}
                observed+=sum(v["weight"] for v in slots.values() if v["points"] is not None)
                full+=int(all(v["points"] is not None for v in slots.values()))
                for k,v in slots.items():
                    if v["points"] is None:missing[k+"|"+v["status"]]+=1
            factors[model][factor]={"coverage_pct":100*observed/expected if expected else None,"full_issuers":full,"missing":dict(missing)}
    return factors

def industry_proxy(payload):
    # Existing adjusted stock returns, not an official industry index or
    # dividend total returns. Diagnostic only; no metric inserted into score.
    groups=defaultdict(list)
    for r in payload["stocks"]:
        if r.get("excluded") or not r.get("industry_code"):continue
        o=r["metrics"].get("momentum_20d",{})
        if finite(o.get("value")) and o.get("asof")==payload["asof"]:
            groups[r["industry_code"]].append((r["ticker"],o["value"]))
    return [{"industry_code":k,"sample":len(v),"median_adjusted_stock_return_pct":median(x[1] for x in v),
             "tickers":[x[0] for x in v],"research_only":True} for k,v in groups.items() if len(v)>=5]

def krx_indices(days,root):
    if not KRX_KEY:raise ValueError("KRX credential unavailable")
    endpoint="https://data-dbg.krx.co.kr/svc/apis/idx/kospi_dd_trd"
    by_name=defaultdict(dict);errors=[]
    for d in days:
        try:
            r=S.get(endpoint,headers={"AUTH_KEY":KRX_KEY,"Content-Type":"application/json"},params={"basDd":d},timeout=(5,15))
            if r.status_code in (401,403,429):
                errors.append({"date":d,"status":r.status_code});break
            r.raise_for_status()
            data=parse_rows(r.json())
            if not isinstance(data,list) or not data:raise ValueError("empty index response")
            write(root/(d+".json"),data)
            current={};conflicts=set()
            for x in data:
                name=txt(x,"IDX_NM","idxNm","idx_nm").strip()
                v=num(x,"CLSPRC_IDX","clsprcIdx","close")
                if not name or not finite(v) or v<=0:continue
                if name in current and current[name]!=v:conflicts.add(name)
                current[name]=v
            for name,v in current.items():
                if name not in conflicts:by_name[name][d]=v
        except Exception as e:errors.append({"date":d,"status":type(e).__name__})
        time.sleep(.3)
    rows=[]
    for name,values in sorted(by_name.items()):
        complete=set(values)==set(days)
        rows.append({"name":name,"session_count":len(values),"complete":complete,
            "observed_index_change_pct":100*(values[days[-1]]/values[days[0]]-1) if complete else None,
            "total_return_basis_verified":False,"industry_code_mapping_verified":False,"admitted":False})
    return rows,errors

def main():
    out=Path("audit-leading-stage7");out.mkdir(exist_ok=True)
    payload=read("stage5/observations.json");result=evaluate(payload)
    audit=read("replay-source/report.json")
    if audit["universe_asof"]!=payload["asof"]:raise ValueError("date mismatch")
    src={r["ticker"]:r for r in audit["records"]}
    roic=Counter();details=[]
    for r in payload["stocks"]:
        if r.get("excluded") or r.get("financial_model") not in (None,"operating_holding"):continue
        t=r["ticker"];s=src[t];p=Path("replay-source/source-rows")/(t+".json")
        if not p.exists() or s.get("scope")!="CFS":roic["source_or_scope_missing"]+=1;continue
        raw=read(p)
        if not source_check(raw,audit["year"],"CFS") or sorted({str(x["rcept_no"]) for x in raw})!=s.get("receipts"):roic["receipt_mismatch"]+=1;continue
        cap=extract_capital_metrics(raw,ticker=t,financial_year=audit["year"],fs_div="CFS")
        a=cap["capital_metric_audit"]
        reasons=[]
        if a.get("lease_basis")!="lease_excluded":reasons.append("lease_scope_unverified")
        if a.get("debt_current") is None or a.get("debt_previous") is None:reasons.append("borrowing_totals_missing")
        if a.get("effective_tax_rate") is None:reasons.append("effective_tax_missing")
        if not finite(cap.get("roic_pct")):reasons.append("roic_unavailable")
        if not reasons:reasons=["formula_available_review_peer_count"]
        roic.update(reasons)
        details.append({"ticker":t,"industry_code":r.get("industry_code"),"reasons":reasons,"capital_audit":a,"candidate_roic_pct":cap.get("roic_pct")})
    proxy=industry_proxy(payload)
    cutoff=payload["asof"].replace("-","")
    sessions=sorted(p.stem for p in Path("data/history").glob("*.json") if len(p.stem)==8 and p.stem.isdigit() and p.stem<=cutoff)[-21:]
    if len(sessions)!=21 or sessions[-1]!=cutoff:raise ValueError("calendar mismatch")
    rawdir=out/"index-raw";rawdir.mkdir(exist_ok=True)
    index_rows,errors=krx_indices(sessions,rawdir)
    s=summary(result)
    s["factor_gaps"]=factor_gaps(result)
    s["roic_reasons"]=dict(roic)
    s["index_inventory"]={"sessions":len(sessions),"index_names":len(index_rows),"complete_series":sum(r["complete"] for r in index_rows),"errors":errors,"official_admitted_series":0,"research_proxy_industries":len(proxy),"research_proxy_issuers":sum(r["sample"] for r in proxy)}
    s["release_gate"]="blocked"
    for name,v in (("summary.json",s),("roic_diagnostics.json",details),("index_inventory.json",index_rows),("industry_proxy.json",proxy)):
        write(out/name,v)
    print("STAGE7 COVERAGE",s["base_weighted_coverage_pct"],s["leading_weighted_coverage_pct"],flush=True)
    print("STAGE7 FACTORS",json.dumps({m:{k:round(v["coverage_pct"],2) for k,v in fs.items()} for m,fs in s["factor_gaps"].items()}),flush=True)
    print("STAGE7 ROIC",json.dumps(s["roic_reasons"]),flush=True)
    print("STAGE7 INDEX",json.dumps(s["index_inventory"],ensure_ascii=False),flush=True)
if __name__=="__main__":main()
