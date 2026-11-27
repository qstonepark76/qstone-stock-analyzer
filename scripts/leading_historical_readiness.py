"""Historical 5-year monthly universe feasibility, using actual dated KRX rows.
Current universe is never backfilled as past constituents. No production writes.
"""
import json,time,calendar
from pathlib import Path
from datetime import date,timedelta,datetime,timezone
from collections import Counter
import requests
from collect import KRX_URL,KRX_KEY,parse_rows,txt,num
from final_leading_model import finite
from leading_backtest_extended import subtract_years
END=date(2026,11,27)
def read(p,default=None):return json.loads(Path(p).read_text(encoding="utf-8")) if Path(p).exists() else default
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
def anchors(end,years):
    return [min(end,date(y,m,calendar.monthrange(y,m)[1])) for i in range(years*12-1,-1,-1) for y,m in [divmod(end.year*12+end.month-1-i,12)] for m in [m+1]]
def universe(rows,day):
    if not isinstance(rows,list):return []
    result={}
    for r in rows:
        d=txt(r,"BAS_DD","basDd","date").replace("-","")
        if d!=day.strftime("%Y%m%d"):continue
        t=txt(r,"ISU_CD","isuCd","ticker");name=txt(r,"ISU_NM","isuNm","name")
        cap=num(r,"MKTCAP","mkcap","market_cap");close=num(r,"TDD_CLSPRC","tddClsprc","close")
        if not t or not name or not finite(cap) or cap<=0 or not finite(close) or close<=0:continue
        if t in result:raise ValueError("duplicate historical issue")
        result[t]={"ticker":t,"name":name,"market_cap":cap,"close":close}
    return sorted(result.values(),key=lambda r:(-r["market_cap"],r["ticker"]))[:300]
def main():
    out=Path("audit-leading-historical-readiness");out.mkdir(exist_ok=True);rawdir=out/"universe";rawdir.mkdir(exist_ok=True)
    session=requests.Session();errors=Counter();records=[];stop=not bool(KRX_KEY);requests_count=0
    for anchor in anchors(END,5):
        item={"month":anchor.strftime("%Y-%m"),"requested_anchor":anchor.isoformat(),"status":"missing"}
        if not stop:
            for n in range(10):
                d=anchor-timedelta(days=n)
                if d.month!=anchor.month:break
                if d.weekday()>=5:continue
                try:
                    r=session.get(KRX_URL,headers={"AUTH_KEY":KRX_KEY,"Content-Type":"application/json"},params={"basDd":d.strftime("%Y%m%d")},timeout=(5,15),allow_redirects=False);requests_count+=1
                    if r.status_code in (401,403,429):errors["http_"+str(r.status_code)]+=1;stop=True;break
                    r.raise_for_status();rows=parse_rows(r.json());top=universe(rows,d)
                    if len(top)==300:
                        write(rawdir/(d.isoformat()+".json"),top)
                        item.update(status="universe_received",session=d.isoformat(),count=len(top),source_ref="KRX dated KOSPI daily stock market cap")
                        break
                    errors["empty_or_unusable_day"]+=1
                except (requests.RequestException,ValueError,TypeError,AttributeError) as e:errors[type(e).__name__]+=1;break
                finally:time.sleep(.35)
        records.append(item)
        if len(records)%12==0:print("HISTORICAL UNIVERSE PROGRESS",len(records),"/60",flush=True)
    ledger=read("data/analyst_reports.json",{}) or {};reports=ledger.get("reports",[]) if isinstance(ledger,dict) else []
    eligible=Counter();published=Counter()
    for r in reports:
        try:
            p=date.fromisoformat(r["published_at"]);v=datetime.fromisoformat(r["verified_at"].replace("Z","+00:00")).date()
            if p<=END:published[str(p.year)]+=1
            if p<=v<=END and r.get("source_url") and r.get("verification_method"):eligible[str(v.year)]+=1
        except (KeyError,TypeError,ValueError,AttributeError):continue
    archive_days=sorted(x.stem for x in Path("data/history").glob("*.json") if len(x.stem)==8 and x.stem.isdigit())
    current=read("cagr/final-leading.json",{}) or {}
    summary={"end":END.isoformat(),"five_year_start":subtract_years(END,5).isoformat(),"three_year_start":subtract_years(END,3).isoformat(),"monthly_universe_5y_received":sum(r["status"]=="universe_received" for r in records),"monthly_universe_3y_received":sum(r["status"]=="universe_received" for r in records[-36:]),"monthly_universe_5y_expected":60,"monthly_universe_3y_expected":36,"requests":requests_count,"errors":dict(errors),"archived_market_sessions":len(archive_days),"archived_market_first":archive_days[0] if archive_days else None,"archived_market_last":archive_days[-1] if archive_days else None,"archived_report_publication_year_counts":dict(published),"archived_report_verification_year_counts":dict(eligible),"current_model_coverage":current.get("coverage"),"verified_historical_full_model_snapshots":0,"backtest_status":"blocked_historical_full_model_inputs_not_yet_reconstructed","note":"Monthly anchors are a feasibility inventory, not verified historical ranks. Historical issuer classes, delisted prices, adjusted OHLC, daily flows, annual filing vintages, historical forecasts and index mapping still required. No return fabricated. KOSPI universe only."}
    write(out/"summary.json",summary);write(out/"monthly_universes.json",records);print("HISTORICAL BACKTEST READINESS",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
