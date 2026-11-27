"""Stage 1: re-admit prior evidence, never old points, with the final score rules."""
import json
from pathlib import Path
from datetime import date,datetime
from collections import Counter
from final_leading_model import evaluate,finite
from leading_fundamental_inputs import receipt_day,margin_stability,summary
from metric_quality import source_check,admitted_industry_metrics
from collect import extract_financial
from outlook_candidate import broker_evidence,weighted

def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
def obs(value,basis,asof,available,ref,lower=False,metric_id=None):
    if not finite(value):return None
    r={"value":value,"basis":basis,"asof":asof,"available_on":available,"verified":True,"source_ref":ref,"lower_better":lower}
    if metric_id:r["metric_id"]=metric_id
    return r
def known(r,asof):
    try:
        return date.fromisoformat(r["published_at"])<=datetime.fromisoformat(r["verified_at"].replace("Z","+00:00")).date()<=asof
    except (KeyError,ValueError,TypeError):return False

def main():
    out=Path("audit-leading-reuse");out.mkdir(exist_ok=True)
    payload=read("audit-leading-fundamentals/observations.json")
    original=evaluate(payload)
    asof=date.fromisoformat(payload["asof"])
    source=read("replay-source/report.json")
    year=int(source["year"]);period=f"{year}-12-31"
    if source["universe_asof"]!=payload["asof"]:raise ValueError("date mismatch")
    sources={r["ticker"]:r for r in source["records"]}
    stocks={r["ticker"]:r for r in payload["stocks"]}
    if len(stocks)!=300 or set(stocks)!=set(sources):raise ValueError("universe mismatch")
    counts=Counter()
    cagr=read("reuse-growth/audit-cagr/records.json")
    for t,v in cagr.items():
        row=stocks.get(t);s=sources.get(t,{})
        if not row or row["excluded"] or s.get("status")!="source_received":continue
        a,b=receipt_day(v.get("receipt")),receipt_day(v.get("prior_receipt"))
        if not a or not b or not b<=a<=asof or v.get("year")!=year or v.get("scope")!=s.get("scope") or v.get("receipt") not in s.get("receipts",[]):continue
        if v.get("basis")!="three_annual_observations_two_intervals" or not v.get("account_ids"):continue
        o=obs(v.get("value"),f"{year}|{v['scope']}|{v['basis']}",period,a.isoformat(),
              "OpenDART receipts "+v["receipt"]+" "+v["prior_receipt"],metric_id="sales_cagr")
        if o and "sales_cagr" not in row["metrics"]:
            row["metrics"]["sales_cagr"]=o;counts["cagr_added"]+=1
    # Previous expanded peers are comparison-only; rederive from frozen raw source.
    peers=[];seen={s.get("corp_code") for s in sources.values() if s.get("corp_code")}
    peer_dir=Path("reuse-peers/audit-wider-peers")
    previous=read(peer_dir/"peers.json")
    for r in previous:
        t=r.get("ticker");corp=r.get("corp_code");code=r.get("industry_code")
        if not t or t in stocks or not corp or corp in seen or not code or r.get("financial_model") or r.get("industry_confidence")!="verified" or not r.get("peer_only") or r.get("financial_year")!=year:continue
        path=peer_dir/"source-rows"/(t+".json")
        if not path.exists():continue
        raw=read(path)
        if not source_check(raw,year,"CFS"):continue
        receipt=str(raw[0]["rcept_no"]);available=receipt_day(receipt)
        if [receipt]!=r.get("receipts") or not available or not date.fromisoformat(period)<=available<=asof:continue
        m=extract_financial(raw,ticker=t,financial_year=year,fs_div="CFS")
        vals=admitted_industry_metrics(m["industry_metrics"],m["industry_metric_quality"],year)
        metrics={}
        for k,old in (("roic","roic_pct"),("asset_turnover","asset_turnover"),("cash_conversion","cash_conversion_pct")):
            o=obs(vals.get(old),f"{year}|CFS|{old}",period,available.isoformat(),"OpenDART receipt "+receipt)
            if o:metrics[k]=o
        o=obs(margin_stability(raw),f"{year}|CFS|3 annual operating-margin standard deviation pp",period,available.isoformat(),"OpenDART receipt "+receipt,True)
        if o:metrics["margin_stability"]=o
        if metrics:
            peers.append({"ticker":t,"industry_code":code,"peer_only":True,"metrics":metrics})
            seen.add(corp)
    payload["comparison_peers"]=peers
    counts["peers_admitted"]=len(peers)
    # Preserve prior verified external report data; exclude records verified after
    # the frozen date and never use own-model estimates as broker revisions.
    ledgers=[read("data/analyst_reports.json"),read("reuse-external/data/analyst_reports.json")]
    reports={}
    for ledger in ledgers:
        for r in ledger["reports"]:
            if known(r,asof) and r.get("verification_method") and r.get("source_url"):
                key=(r.get("ticker"),r.get("broker"),r.get("published_at"),r.get("source_url"))
                if key in reports and reports[key]!=r:
                    # Retain both only when observations agree, else withhold.
                    old=reports[key]
                    if old is None or any(old.get(k)!=r.get(k) for k in ("rating","target_price","previous_target_price")):reports[key]=None
                elif key not in reports:reports[key]=r
    ledger=[r for r in reports.values() if r]
    counts["verified_prior_reports"]=len(ledger)
    for t,row in stocks.items():
        if row["excluded"]:continue
        ev=broker_evidence({"ticker":t},ledger,asof)["rating"]
        if not ev:continue
        rating=weighted([(v,w) for v,w,_,_ in ev])
        o=obs(rating,"Verified broker rating recency weighted 0..3",payload["asof"],payload["asof"],"; ".join(sorted({url for _,_,_,url in ev})))
        if o:
            if "rating" not in row["metrics"]:counts["rating_added"]+=1
            row["metrics"]["rating"]=o
    # Keep old own forecast evidence as distinct research. It cannot substitute
    # for the leading indicator's actual independent analyst vintages.
    prior_forecast=read("reuse-forecast/records.json")
    counts["prior_forecast_candidate_rows"]=len(prior_forecast)
    counts["prior_own_model_rows"]=sum(any(v.get("status")=="own_model_candidate" for v in r.get("detail",{}).values()) for r in prior_forecast)
    result=evaluate(payload);result["point_in_time_verified"]=False
    s=summary(result);s["before"]=summary(original);s["reuse_counts"]=dict(counts);s["source_artifacts"]=[45625150031,46031239443,45726502771,45726349207,45726434788,45817314640]
    s["forecast_policy"]="Own forecast evidence retained separately; not admitted as external consensus."
    write(out/"observations.json",payload);write(out/"final-leading.json",result);write(out/"summary.json",s)
    print("LEADING REUSE SUMMARY",json.dumps({k:v for k,v in s.items() if k not in ("before","base_slot_counts","leading_slot_counts")},ensure_ascii=False),flush=True)
    print("LEADING REUSE BEFORE AFTER",json.dumps({"before_base":s["before"]["base_weighted_coverage_pct"],"after_base":s["base_weighted_coverage_pct"],"cagr_before":s["before"]["base_slot_counts"].get("sales_cagr"),"cagr_after":s["base_slot_counts"].get("sales_cagr"),"industry_before":{k:s["before"]["base_slot_counts"].get(k) for k in ("roic","asset_turnover","cash_conversion")},"industry_after":{k:s["base_slot_counts"].get(k) for k in ("roic","asset_turnover","cash_conversion")}},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
