"""Direct provider valuation: preserve published ratios, no DART recomputation.
Current-date candidate only. Do not mutate a frozen historical score.
"""
import argparse,json,math,re,time
from pathlib import Path
from datetime import datetime,timezone,timedelta
from collections import Counter,defaultdict
from concurrent.futures import ThreadPoolExecutor
import requests
from final_leading_model import percentile,finite

KST=timezone(timedelta(hours=9))
URL="https://m.stock.naver.com/api/stock/{ticker}/integration"
FIELDS={"per":"earnings_value","pbr":"book_value"}
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
def parse_ratio(v):
    if isinstance(v,bool):return None
    if isinstance(v,(int,float)):return float(v) if finite(v) else None
    if not isinstance(v,str):return None
    s=v.strip().replace(",","").removesuffix("배").strip()
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?",s):return None
    x=float(s);return x if finite(x) else None

def parse_naver(payload,ticker):
    if not isinstance(payload,dict):return {},"invalid_payload"
    # The endpoint is already ticker-specific. Reject an explicit conflicting ticker.
    code=payload.get("itemCode") or payload.get("stockCode")
    if code and str(code).strip().zfill(6)!=ticker:return {},"ticker_mismatch"
    rows=payload.get("totalInfos")
    if not isinstance(rows,list):return {},"no_totalInfos"
    candidates=defaultdict(list)
    for r in rows:
        if not isinstance(r,dict):continue
        code=str(r.get("code","")).lower()
        if code not in FIELDS:continue
        v=parse_ratio(r.get("value"))
        if v is None:continue
        candidates[code].append({"value":v,"display":r.get("value"),"label":r.get("key") or r.get("name"),"provider_basis":r.get("desc") or r.get("description") or r.get("period")})
    out={}
    for k,rs in candidates.items():
        if len({r["value"] for r in rs})==1:out[k]=rs[0]
    return out,None if out else "no_ratio_values"

def compare(rows):
    groups=defaultdict(list);c=Counter()
    for row in rows:
        for k,r in row["ratios"].items():
            if r["value"]<=0 or not row.get("industry_code"):continue
            # Compare like provider display fields; no mixing forecast PER or different providers.
            groups[(row["industry_code"],row.get("financial_model"),k,r.get("basis_key"))].append(r["value"])
    for row in rows:
        if row["peer_only"]:continue
        for k in FIELDS:
            r=row["ratios"].get(k);v=r["value"] if r else None
            n=0;q=None;status="데이터 없음"
            if r:
                c[k+"_raw"]+=1
                if v<=0:status="0 또는 음수: 별도 기준 필요";c[k+"_nonpositive"]+=1
                else:
                    c[k+"_positive"]+=1
                    if row.get("industry_code"):
                        vals=groups[(row["industry_code"],row.get("financial_model"),k,r.get("basis_key"))];n=len(vals);q=percentile(v,vals,True)
                    status="산출" if q is not None else "비교기업 부족"
            if q is not None:c[k+"_scored"]+=1
            row.setdefault("valuation",{})[k]={"value":v,"points":round(5*q,6) if q is not None else None,"peer_count":n,"status":status}
    return dict(c)

def main():
    out=Path("audit-leading-direct-valuation");out.mkdir(exist_ok=True)
    p=read("stage5/observations.json");u=read("replay-source/universe.json")
    if p["asof"]!=u["asof"]:raise ValueError("universe date mismatch")
    history={r["ticker"]:r for r in read("data/history/"+p["asof"].replace("-","")+".json")}
    targets=[r for r in p["stocks"] if not r.get("excluded")]
    codes={r["industry_code"] for r in targets if r.get("industry_code")}
    peer=[r for r in p.get("comparison_peers",[]) if r.get("industry_code") in codes and r["ticker"] in history]
    selected=targets+peer
    if len({r["ticker"] for r in selected})!=len(selected):raise ValueError("duplicate ticker")
    rows=[];errors=Counter();started=datetime.now(KST)
    s=requests.Session();s.headers.update({"User-Agent":"Mozilla/5.0","Accept":"application/json","Referer":"https://m.stock.naver.com/"})
    # Sequential, conservative request rate; stop on access restriction.
    for idx,r in enumerate(selected,1):
        t=r["ticker"];record={"ticker":t,"name":history.get(t,{}).get("name",r.get("name")),"industry_code":r.get("industry_code"),"financial_model":r.get("financial_model"),"peer_only":bool(r.get("peer_only")),"ratios":{}}
        try:
            res=s.get(URL.format(ticker=t),timeout=(5,12),allow_redirects=False)
            record["observed_at"]=datetime.now(KST).isoformat()
            if res.status_code in (401,403,429):
                errors["http_"+str(res.status_code)]+=1;rows.append(record);break
            res.raise_for_status()
            raw,why=parse_naver(res.json(),t)
            if why:errors[why]+=1
            for k,v in raw.items():
                record["ratios"][k]={**v,"source":"Naver","source_ref":URL.format(ticker=t),"observed_at":record["observed_at"],
                    "basis_key":"Naver totalInfos "+k+"|"+str(v.get("provider_basis") or "provider display basis unspecified")}
        except (requests.RequestException,ValueError) as e:errors[type(e).__name__]+=1
        rows.append(record)
        if idx%50==0:print("DIRECT VALUATION PROGRESS",idx,"/",len(selected),flush=True)
        time.sleep(.45)
    # Account for unprocessed issuers as missing, not as zeros.
    seen={r["ticker"] for r in rows}
    for r in selected:
        if r["ticker"] not in seen:rows.append({"ticker":r["ticker"],"industry_code":r.get("industry_code"),"financial_model":r.get("financial_model"),"peer_only":bool(r.get("peer_only")),"ratios":{}})
    counts=compare(rows);n=len(targets)
    summary={"universe_asof":p["asof"],"observed_at":started.isoformat(),"target_count":n,"peer_count":len(peer),"queried":len(seen),"counts":counts,"errors":dict(errors),"raw_coverage_pct":100*sum(counts.get(k+"_raw",0) for k in FIELDS)/(2*n),"score_coverage_pct":100*sum(counts.get(k+"_scored",0) for k in FIELDS)/(2*n),"historical_scores_modified":False,"status":"new_date_provider_candidate","note":"No independent DART validation. Provider display basis preserved, unspecified basis not asserted as annual or TTM. Same-provider peer comparisons are provisional until scope/basis and classification policy are set. No merging with frozen overall score."}
    write(out/"summary.json",summary);write(out/"records.json",rows)
    print("DIRECT VALUATION SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
