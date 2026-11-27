"""Target gaps and historical report pairs without relaxing issuer verification."""
import json,sys,time
from datetime import date,timedelta
from pathlib import Path
import requests
sys.path.insert(0,"scripts")
from discover_broker_reports import parse_api_items,HEADERS
from verify_broker_reports import verify_candidate,merge_ledger,norm_name
from outlook_candidate import score,broker_key,day
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def main():
    u=read("replay-source/universe.json");asof=date.fromisoformat(u["asof"])
    names={s["ticker"]:norm_name(s["name"]) for s in u["stocks"]}
    ledger=read("data/analyst_reports.json")["reports"]
    market={s["ticker"]:s for s in read("data/history/"+asof.strftime("%Y%m%d")+".json")}
    missing=[];pairs=[]
    for s in u["stocks"]:
        m=market.get(s["ticker"],{})
        result=score(dict(s,close=m.get("close") if m.get("market_cap")==s.get("market_cap") else None),ledger,asof)
        if not result["detail"]["rating"]["observed"] or not result["detail"]["upside"]["observed"]:missing.append(s["ticker"])
    # Prioritize gaps, then all targets for older reports. Query filter must be
    # independently confirmed in each response; never overwrite source ticker.
    session=requests.Session();session.headers.update(HEADERS)
    found=[];issues={};requests_made=0
    for t in missing+[s["ticker"] for s in u["stocks"] if s["ticker"] not in missing]:
        for page in range(3):
            try:
                resp=session.get("https://stock.naver.com/api/stockSecurity/researches/v2/company",params={"itemCodes":t,"index":page,"size":50,"startDate":(asof-timedelta(days=365)).isoformat(),"endDate":asof.isoformat()},timeout=(5,12))
                requests_made+=1
                if resp.status_code in (401,403,429):raise SystemExit("Provider access/rate limit: stop; no bypass")
                resp.raise_for_status();p=resp.json()
                rows=parse_api_items(p,asof)
                if any(x["ticker"]!=t for x in rows):
                    issues[t]="filter_or_identity_mismatch";break
                for x in rows:
                    # For historical baseline only, allow 365 days, while the
                    # scoring engine retains the original 180-day recency limit.
                    d=day(x["published_at"])
                    if not d or d>asof or (asof-d).days>365:continue
                    validation_day=min(asof,d+timedelta(days=180))
                    r,why=verify_candidate(x,names,validation_day)
                    if r:found.append(r)
                    else:issues[why]=issues.get(why,0)+1
                if p.get("hasNext") is False or not rows:break
                time.sleep(.35)
            except (requests.RequestException,ValueError,TypeError) as e:
                issues[t]=type(e).__name__;break
        time.sleep(.35)
    merged=merge_ledger(ledger,found)
    Path("data/analyst_reports.json").write_text(json.dumps({"schema_version":2,"reports":merged},ensure_ascii=False,indent=2))
    groups={}
    for r in merged:
        d=day(r.get("published_at"))
        if r.get("ticker") in names and d and 0<=(asof-d).days<=365 and r.get("target_price"):
            groups.setdefault((r["ticker"],broker_key(r.get("broker"))),[]).append(r)
    for (t,b),rs in groups.items():
        dates=sorted({r["published_at"] for r in rs},reverse=True)
        if len(dates)<2 or (asof-day(dates[0])).days>180:continue
        latest=[r for r in rs if r["published_at"]==dates[0]]
        prior=[r for r in rs if r["published_at"]==dates[1]]
        if len({r["target_price"] for r in latest})!=1 or len({r["target_price"] for r in prior})!=1:continue
        pairs.append({"ticker":t,"broker":b,"latest":latest[0],"prior":prior[0],"basis_verified":False})
    out=Path("audit-targeted-outlook");out.mkdir(exist_ok=True)
    (out/"revision-candidates.json").write_text(json.dumps(pairs,ensure_ascii=False,indent=2))
    summary={"gap_targets":len(missing),"requests":requests_made,"new_verified_rows":len(found),"ledger":len(merged),"candidate_revision_pairs":len(pairs),"revision_candidate_issuers":len({p["ticker"] for p in pairs}),"issues":issues,"admitted_revisions":0}
    (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print("TARGETED OUTLOOK SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
