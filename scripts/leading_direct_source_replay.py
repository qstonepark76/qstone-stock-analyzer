"""Apply direct-source rule to existing source evidence; no new external requests."""
import json
from pathlib import Path
from datetime import date
from collections import Counter
from leading_direct_source_policy import target_revision
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
def main():
    out=Path("audit-leading-direct-source");out.mkdir(exist_ok=True)
    source=read("leading/summary.json");asof=date.fromisoformat(source["asof"])
    rows=read("leading/records.json");seen=set();records=[];c=Counter()
    for row in rows:
        t=row["ticker"]
        if t in seen:raise ValueError("duplicate ticker")
        seen.add(t);slots={};z=row.get("slots",{}).get("target_revision_30d")
        if z:
            c["source_available"]+=1
            v=target_revision(z,asof)
            if v:slots["target_revision_30d"]=v;c["direct_scored"]+=1
            else:c["insufficient_matched_brokers_or_period"]+=1
        records.append({"ticker":t,"slots":slots})
    n=len(records)
    summary={"asof":asof.isoformat(),"target_count":n,"counts":dict(c),"target_revision_slot_coverage_pct":100*c["direct_scored"]/n,"direct_target_weighted_coverage_pp":6*c["direct_scored"]/n,
             "source_run":46052441920,"official_integrated":False,"note":"Approved no cross-provider check. Same broker 30-day cutoff, min three brokers retained. Direct target price basis as published; source date 2026-11-28, separate from frozen 2026-11-24 market inputs. Missing data remains missing."}
    write(out/"summary.json",summary);write(out/"records.json",records);print("LEADING DIRECT SOURCE REPLAY",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
