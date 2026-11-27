"""Stage 5: expand exact-code valuation peers and repair missing margin history.
No legacy scores, no estimated missing values, no provider write or deployment.
"""
import json, argparse, time, os
from collections import Counter,defaultdict
from pathlib import Path
from datetime import date
from statistics import pstdev
from final_leading_model import evaluate,finite
from leading_fundamental_inputs import merge_market,summary,receipt_day,margin_stability
from leading_reuse_stage1 import obs
from fundamental_candidate import derive,select,number
from metric_quality import source_check,account_check
from collect import dart_company_financial,DART_KEY

def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")

def reconciled_margin(current,previous,year,cutoff):
    if not source_check(current,year,"CFS") or not source_check(previous,year-1,"CFS"):return None
    receipts=[str(r[0]["rcept_no"]) for r in (current,previous)]
    dates=[receipt_day(r) for r in receipts]
    if not all(dates) or not date(year-1,12,31)<=dates[1]<=dates[0]<=cutoff:return None
    a,b,c,d=[select(r,k) for r in (current,previous) for k in ("sales","op")]
    if not account_check([a,b,c,d]):return None
    # Current filing's FY-1 amounts must reconcile to the older filing's
    # FY-1 current values before using its FY-2 comparisons.
    vals=[]
    for x,y in ((a,c),(b,d)):
        n,p,q,z=[number(r,k) for r,k in ((x,"thstrm_amount"),(x,"frmtrm_amount"),(y,"thstrm_amount"),(y,"frmtrm_amount"))]
        if None in (n,p,q,z) or abs(p-q)>max(1,abs(p)*1e-9):return None
        vals.append((n,p,z))
    sales,profit=vals
    if min(sales)<=0:return None
    return pstdev([100*p/s for s,p in zip(sales,profit)]),receipts,dates[0].isoformat()

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--recover-margin",action="store_true");args=ap.parse_args()
    out=Path("audit-leading-stage5");out.mkdir(exist_ok=True)
    payload=read("audit-leading-stage4/observations.json")
    market=read("audit-leading-market/market.json")
    if set(market["records"])!={r["ticker"] for r in payload["stocks"]}:raise ValueError("market universe mismatch")
    merge_market(payload,market);before=summary(evaluate(payload))
    cutoff=date.fromisoformat(payload["asof"])
    audit=read("replay-source/report.json");year=int(audit["year"]);period=f"{year}-12-31"
    if audit["universe_asof"]!=payload["asof"]:raise ValueError("source date mismatch")
    source={r["ticker"]:r for r in audit["records"]}
    market_rows={r["ticker"]:r for r in read("data/history/"+cutoff.strftime("%Y%m%d")+".json")}
    peers_dir=Path("reuse-peers/audit-wider-peers")
    metadata={r["ticker"]:r for r in read(peers_dir/"peers.json")}
    counts=Counter();missing=Counter()
    # Expand valuation peer distribution using the original KRX snapshot only.
    # Peer candidates were independently issuer-deduplicated in stage 1.
    for p in payload["comparison_peers"]:
        t=p["ticker"];m=metadata.get(t,{});q=market_rows.get(t,{})
        if not q or q.get("name")!=m.get("name") or not finite(q.get("market_cap")) or q["market_cap"]<=0:continue
        raw=read(peers_dir/"source-rows"/(t+".json"))
        if not source_check(raw,year,"CFS"):continue
        receipt=str(raw[0]["rcept_no"]);d=receipt_day(receipt)
        if [receipt]!=m.get("receipts") or not d or not date.fromisoformat(period)<=d<=cutoff:continue
        v=derive(raw,year,"CFS",q["market_cap"])
        for k,metric in (("earnings_value","per"),("book_value","pbr")):
            x=v.get(metric)
            if not x:continue
            o=obs(x["value"],f"{year}|CFS|{x['basis']}",payload["asof"],payload["asof"],"OpenDART receipt "+receipt+" + KRX frozen market cap",True,metric)
            if o:p["metrics"][k]=o;counts["valuation_peer_"+k]+=1
    if args.recover_margin:
        if not DART_KEY:raise ValueError("DART credentials missing")
        rawdir=out/"recovered-prior";rawdir.mkdir(exist_ok=True)
        # Recover target margins and only enough exact-code comparison peers
        # to make the five-observation minimum. Do not recollect full universe.
        groups=defaultdict(list)
        for p in payload["comparison_peers"]:
            if p.get("industry_code"):groups[p["industry_code"]].append(p)
        def recover(r,meta,folder):
            t=r["ticker"];path=folder/(t+".json")
            if not path.exists() or not meta.get("corp_code"):return
            raw=read(path)
            if not source_check(raw,year,"CFS"):return
            receipt=str(raw[0]["rcept_no"]);d=receipt_day(receipt)
            if [receipt]!=meta.get("receipts") or not d or not date.fromisoformat(period)<=d<=cutoff:return
            direct=margin_stability(raw)
            if finite(direct):v,refs,available=direct,[receipt],d.isoformat()
            else:
                try:
                    older,scope,_=dart_company_financial(meta["corp_code"],year-1)
                    counts["prior_year_requests"]+=1
                    if scope!="CFS" or not older:missing["prior_scope_or_source"]+=1;return
                    result=reconciled_margin(raw,older,year,cutoff)
                    if not result:missing["prior_account_or_restatement"]+=1;return
                    v,refs,available=result
                    write(rawdir/(t+".json"),older)
                except Exception as e:missing[type(e).__name__]+=1;return
                finally:time.sleep(.25)
            r["metrics"]["margin_stability"]=obs(v,f"{year}|CFS|3 annual operating-margin standard deviation pp",period,available,"OpenDART receipts "+" ".join(refs),True)
            counts["target_margin" if not r.get("peer_only") else "peer_margin"]+=1
        targets=[r for r in payload["stocks"] if not r.get("excluded") and r.get("financial_model") in (None,"operating_holding") and r.get("industry_code")]
        for r in targets:
            if "margin_stability" not in r["metrics"]:recover(r,source.get(r["ticker"],{}),Path("replay-source/source-rows"))
        for code in sorted({r["industry_code"] for r in targets if not r.get("financial_model") and "margin_stability" in r["metrics"]}):
            n=sum(r.get("industry_code")==code and not r.get("financial_model") and "margin_stability" in r["metrics"] for r in targets)+sum("margin_stability" in r["metrics"] for r in groups[code])
            for p in groups[code]:
                if n>=5:break
                if "margin_stability" in p["metrics"]:continue
                recover(p,metadata.get(p["ticker"],{}),peers_dir/"source-rows")
                n+=int("margin_stability" in p["metrics"])
        print("MARGIN RECOVERY",json.dumps({"counts":dict(counts),"missing":dict(missing)}),flush=True)
    result=evaluate(payload);result["point_in_time_verified"]=False
    s=summary(result);s["before"]=before;s["recovery_counts"]=dict(counts);s["missing_reasons"]=dict(missing)
    s["release_gate"]="not_verified"
    for name,data in (("summary.json",s),("observations.json",payload),("final-leading.json",result)):
        write(out/name,data)
    print("STAGE5 RECOVERY SUMMARY",json.dumps({"before_base":before["base_weighted_coverage_pct"],"after_base":s["base_weighted_coverage_pct"],"leading":s["leading_weighted_coverage_pct"],"before_slots":{k:before["base_slot_counts"].get(k,0) for k in ("earnings_value","book_value","margin_stability")},"after_slots":{k:s["base_slot_counts"].get(k,0) for k in ("earnings_value","book_value","margin_stability")},"counts":dict(counts),"missing":dict(missing),"complete":s["coverage"]},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
