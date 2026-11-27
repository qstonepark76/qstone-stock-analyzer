"""Public displayed consensus history pilot for leading score.
Provider-labelled one-month values are candidates, not asserted exact 30 days.
No cross-provider check, no historical backdating, no inferred broker breadth.
"""
import json,re,time,os,calendar
from pathlib import Path
from datetime import date,datetime,timedelta,timezone
from collections import Counter,defaultdict
from statistics import median
import requests
from bs4 import BeautifulSoup
from final_leading_model import finite,curve,LEADING,evaluate
from forecast_score_policy import raw_fraction
from leading_naver_outlook_replay import report_rows
from outlook_candidate import broker_key
KST=timezone(timedelta(hours=9))
URL="https://comp.wisereport.co.kr/company/c1050001.aspx"
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
def num(x):
    try:
        v=float(str(x).replace(",","").replace("%","").strip())
        return v if finite(v) else None
    except (ValueError,TypeError):return None
def dt(x):
    try:return date.fromisoformat(str(x).strip().replace("/","-").replace(".","-"))
    except (TypeError,ValueError):return None
def change(a,b):
    d=abs(a)+abs(b)
    return 200*(b-a)/d if d else 0.0
def parse(html,asof,ticker):
    soup=BeautifulSoup(html,"html.parser")
    out={};errors=Counter()
    # Only match a table containing the documented labelled columns.
    for table in soup.find_all("table"):
        rows=[[c.get_text(" ",strip=True) for c in tr.find_all(["th","td"],recursive=False)] for tr in table.find_all("tr")]
        for i,r in enumerate(rows):
            if "1개월전" not in r or "날짜" not in r:continue
            j=r.index("날짜")+1;k=r.index("1개월전")
            if j>=len(r):continue
            d=dt(r[j])
            if not d or d>asof or (asof-d).days>3:errors["stale_or_invalid_table_date"]+=1;continue
            # Calendar month is not necessarily exactly 30 days.
            py,pm=(d.year-1,12) if d.month==1 else (d.year,d.month-1)
            prior=d.replace(year=py,month=pm,day=min(d.day,calendar.monthrange(py,pm)[1]))
            for rr in rows[i+1:]:
                if len(rr)!=len(r) or not re.fullmatch(r"\d{4}/12",rr[1]):continue
                if rr[1]!=f"{d.year}/12":continue
                a,b=num(rr[k]),num(rr[j])
                if a is None or b is None:continue
                label=rr[0].replace(" ","")
                field={"영업이익(억원)":"op_revision_1m","순이익(억원)":"net_revision_1m"}.get(label)
                if field:
                    z={"value":change(a,b),"current":b,"prior":a,"period_end":f"{d.year}-12-31","table_date":d.isoformat(),"nominal_prior_month":prior.isoformat(),"nominal_window_days":(d-prior).days,"basis":"provider displayed annual consensus, same table 1개월전","scope":"provider_display_unspecified","source_ref":URL+"?cmp_cd="+ticker}
                    if field in out and out[field]!=z:errors["ambiguous_"+field]+=1;out[field]=None
                    elif field not in out:out[field]=z
    # Annual surprise: provider labels actual release date and pre-release consensus.
    for table in soup.find_all("table"):
        rows=[[c.get_text(" ",strip=True) for c in tr.find_all(["th","td"],recursive=False)] for tr in table.find_all("tr")]
        heads=[r for r in rows if "구분" in r and str(asof.year-1) in r]
        metric_headers=[r for r in rows if "영업이익" in r and "Surprise" in r]
        actual=[r for r in rows if r and r[0]=="연간실적(A)"]
        estimate=[r for r in rows if r and r[0]=="발표직전(E)"]
        if len(heads)!=1 or not metric_headers or len(actual)!=1 or len(estimate)!=1:continue
        years=[int(v) for v in heads[0] if re.fullmatch(r"20\d{2}",v)]
        if len(years)!=len(set(years)) or years!=sorted(years):continue
        aa,ee=actual[0],estimate[0]
        if len(aa)!=1+2*len(years) or len(ee)!=len(aa):continue
        for i,y in reversed(list(enumerate(years))):
            pos=1+2*i;d=dt(aa[pos+1]);a,b=num(aa[pos]),num(ee[pos])
            reported=num(ee[pos+1])
            if not d or not date(y,12,31)<=d<=asof or (asof-d).days>365 or None in (a,b,reported):continue
            if b==0:continue
            # Preserve provider surprise as displayed, not recalculated from rounded values.
            z={"value":reported,"actual":a,"estimate_before_release":b,"actual_release_on":d.isoformat(),"period_end":f"{y}-12-31","basis":"provider annual operating profit surprise, pre-release consensus","source_ref":URL+"?cmp_cd="+ticker}
            if "earnings_surprise" not in out:out["earnings_surprise"]=z
            elif out["earnings_surprise"]!=z:out["earnings_surprise"]=None;errors["ambiguous_surprise"]+=1
            break
    return {k:v for k,v in out.items() if v is not None},dict(errors)
def target_pairs(rows,asof):
    prior=asof-timedelta(days=30);groups=defaultdict(lambda:defaultdict(set))
    for r in rows:
        d=dt(r.get("report_date"));b=broker_key(r.get("broker"));v=r.get("target_price_candidate")
        if d and b and finite(v) and v>0 and 0<=(asof-d).days<=75:groups[b][d].add(v)
    out=[]
    for b,rs in groups.items():
        now=max(rs);old=max((d for d in rs if d<=prior),default=None)
        if old is None or now<=prior or (prior-old).days>45 or len(rs[now])!=1 or len(rs[old])!=1:continue
        x,y=next(iter(rs[old])),next(iter(rs[now]))
        out.append({"broker":b,"current_date":now.isoformat(),"prior_date":old.isoformat(),"current_target":y,"prior_target":x,"value":100*(y/x-1)})
    return out
def main():
    out=Path("audit-leading-direct-consensus");out.mkdir(exist_ok=True)
    payload=read("base/observations.json");baseline=evaluate(payload);targets=[r for r in payload["stocks"] if not r.get("excluded")]
    asof=date.fromisoformat(read("outlook/summary.json")["forecast_asof"]);reports=report_rows(read("roadmap/reports-2026-11-27.json"),asof)
    kis={r["ticker"]:r.get("invest-opinion",{}).get("date_checked_candidates",[]) for r in read("kis/raw_candidates.json")}
    session=requests.Session();session.headers.update({"User-Agent":"Mozilla/5.0","Referer":"https://finance.naver.com/","Accept":"text/html"})
    counts=Counter();errors=Counter();records=[];stop=False;limit=max(1,min(len(targets),int(os.getenv("CONSENSUS_LIMIT","40"))))
    for i,r in enumerate(targets,1):
        t=r["ticker"];slots={}
        pairs=target_pairs(reports.get(t,[]),asof);source="Naver reports"
        if len(pairs)<3:
            k=target_pairs(kis.get(t,[]),asof)
            if len(k)>len(pairs):pairs=k;source="KIS invest-opinion"
        if pairs:
            v=sum(x["value"] for x in pairs)/len(pairs)
            slots["target_revision_30d"]={"value":v,"points_candidate":6*curve("target_revision_30d",v),"broker_count":len(pairs),"source":source,"pairs":pairs,"status":"raw_target_basis_not_corporate_action_verified"}
            counts["target_revision_any"]+=1
            if len(pairs)>=3:counts["target_revision_three_brokers"]+=1
        if i<=limit and not stop:
            try:
                res=session.get(URL,params={"cmp_cd":t},timeout=(5,15),allow_redirects=False)
                if res.status_code in (401,403,429):errors["http_"+str(res.status_code)]+=1;stop=True
                else:
                    res.raise_for_status();v,e=parse(res.content,asof,t);errors.update(e)
                    for k,z in v.items():
                        z["observed_at"]=datetime.now(KST).isoformat()
                        if k=="op_revision_1m":z["points_candidate"]=10*raw_fraction("op_revision_30d",z["value"])
                        elif k=="earnings_surprise":z["points_candidate"]=6*raw_fraction(k,z["value"])
                        slots[k]=z;counts[k]+=1
                    if not v:errors["no_usable_consensus_table"]+=1
            except (requests.RequestException,ValueError,TypeError) as e:errors[type(e).__name__]+=1
            finally:time.sleep(.7)
        records.append({"ticker":t,"industry_code":r.get("industry_code"),"slots":slots})
    # Current same-provider exact industry diagnostic, not independent broker breadth.
    groups=defaultdict(list)
    for r in records:
        z=r["slots"].get("op_revision_1m")
        if z and r["industry_code"]:groups[(r["industry_code"],z["period_end"],z["table_date"],z["basis"])].append(r)
    for rs in groups.values():
        if len(rs)<5:continue
        v=median(r["slots"]["op_revision_1m"]["value"] for r in rs)
        for r in rs:
            r["slots"]["industry_revision_1m"]={"value":v,"points_candidate":7*raw_fraction("industry_earnings_revision",v),"peer_count":len(rs),"source":"same provider consensus table"};counts["industry_revision_1m"]+=1
    old=[r["leading"] for r in baseline["records"] if not r["excluded"]]
    base=sum(r["coverage_pct"] for r in old)/len(old)
    summary={"asof":asof.isoformat(),"target_count":len(targets),"consensus_pilot_limit":limit,"counts":dict(counts),"errors":dict(errors),"frozen_leading_coverage_pct":base,"official_new_admitted":0,"note":"Provider-labelled 1-month values and published pre-release surprise are direct-source candidates. Do not equate calendar month with verified 30-day history, or aggregate consensus with broker breadth. Target adjustments not independently checked. No price/forecast date mixing; no official integration."}
    write(out/"summary.json",summary);write(out/"records.json",records);print("LEADING DIRECT CONSENSUS SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
