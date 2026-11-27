"""Historical annual filing pilot across five dated KRX universes.
Reject filings dated after signal; do not label latest restated API data as PIT
when receipt is later than the signal. No current constituents or fake scores.
"""
import json,time,io,zipfile,re
from pathlib import Path
from datetime import date,datetime,timezone
from collections import Counter,defaultdict
from xml.etree import ElementTree as ET
import requests
from collect import DART_KEY
from leading_true_cagr import fetch
from leading_fundamental_inputs import receipt_day
from fundamental_candidate import derive
from metric_quality import source_check
from final_leading_model import finite
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
def norm(s):return re.sub(r"[\s()㈜]","",str(s or "").replace("주식회사","")).casefold()
def identity_map(body):
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        names=[n for n in z.namelist() if n.lower().endswith(".xml")]
        if len(names)!=1:raise ValueError("corporate identity archive")
        root=ET.fromstring(z.read(names[0]))
    grouped=defaultdict(list)
    for node in root.findall(".//list"):
        t=(node.findtext("stock_code") or "").strip();c=(node.findtext("corp_code") or "").strip();n=(node.findtext("corp_name") or "").strip()
        if t and c and n:grouped[t].append({"corp_code":c,"name":n})
    return {t:xs[0] for t,xs in grouped.items() if len(xs)==1}
def accepted(raw,year,scope,signal):
    if not source_check(raw,year,scope):return None
    receipt=str(raw[0]["rcept_no"]);d=receipt_day(receipt)
    if not d or not date(year,12,31)<=d<=signal:return None
    return receipt
def main():
    out=Path("audit-leading-historical-financial");out.mkdir(exist_ok=True);rawdir=out/"filings";rawdir.mkdir(exist_ok=True)
    months=read("history/monthly_universes.json")
    # November annual anchors, 2022–2026, top30 only as bounded source pilot.
    anchors=[r for r in months if r.get("status")=="universe_received" and r["month"].endswith("-11")]
    if not DART_KEY:raise SystemExit("DART credential unavailable")
    session=requests.Session()
    res=session.get("https://opendart.fss.or.kr/api/corpCode.xml",params={"crtfc_key":DART_KEY},timeout=(10,30),allow_redirects=False)
    res.raise_for_status();identities=identity_map(res.content)
    counts=Counter();by_year={};records=[];stop=False
    for a in anchors:
        signal=date.fromisoformat(a["session"]);year=signal.year-1;stats=Counter()
        universe=read("history/universe/"+a["session"]+".json")[:30]
        for r in universe:
            t=r["ticker"];stats["target"]+=1;identity=identities.get(t);item={"asof":a["session"],"ticker":t,"name":r["name"],"fiscal_year":year,"status":"missing"}
            if not identity or norm(identity["name"])!=norm(r["name"]):
                stats["identity_missing_or_name_changed"]+=1;records.append(item);continue
            if stop:stats["stopped"]+=1;records.append(item);continue
            corp=identity["corp_code"]
            for scope in ("CFS","OFS"):
                try:
                    rows,err=fetch(session,corp,year,scope);counts["requests"]+=1
                    if err:stats["DART_"+err]+=1;stop=err=="stop"
                    if stop:break
                    if not rows:continue
                    receipt=accepted(rows,year,scope,signal)
                    if not receipt:stats["receipt_after_signal_or_invalid"]+=1;break
                    # No current industry/model classifications: only raw accounting
                    # measures are retained, no full points or historic ranking.
                    metrics=derive(rows,year,scope,r["market_cap"])
                    keys=("roe","roa","margin","sales_growth","op_growth","net_growth","per","pbr")
                    vals={k:metrics[k] for k in keys if isinstance(metrics.get(k),dict) and finite(metrics[k].get("value"))}
                    item.update(status="receipt_eligible_candidate",scope=scope,receipt=receipt,corp_code=corp,metrics=vals)
                    write(rawdir/(a["session"]+"-"+t+".json"),rows)
                    stats["receipt_eligible"]+=1
                    for k in vals:stats[k]+=1
                    break
                except (requests.RequestException,ValueError,TypeError,KeyError) as e:stats[type(e).__name__]+=1;break
                finally:time.sleep(.35)
            records.append(item)
        by_year[str(signal.year)]=dict(stats);print("HISTORICAL FINANCIAL YEAR",signal.year,json.dumps(dict(stats),ensure_ascii=False),flush=True)
    summary={"anchors":len(anchors),"pilot_targets":len(records),"requests":counts["requests"],"receipt_eligible_candidates":sum(r["status"]=="receipt_eligible_candidate" for r in records),"by_signal_year":by_year,"verified_full_model_snapshots":0,"official_backtest_ready":False,"note":"Current DART corporate map exact historical name match only; renamed/delisted unmatched names remain missing. Annual source receipt <= historical signal required. Actual historic accounting inputs only; issuer mapping and original filing provenance still need PIT certification. No current provider forecasts used."}
    write(out/"summary.json",summary);write(out/"records.json",records);print("HISTORICAL FINANCIAL PILOT",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
