"""Merge disjoint peer batches, rederive metrics from receipt-verified raw rows."""
import json
import sys
import shutil
from pathlib import Path
sys.path.insert(0,"scripts")
from collect import extract_financial
from metric_quality import source_check,admitted_industry_metrics
from coverage_experiment import alternatives
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def main():
    audit=read("replay-source/report.json")
    year=audit["year"]
    target={r["corp_code"] for r in read("audit-top300-replay/records.json") if r.get("corp_code")}
    dest=Path("audit-wider-peers");dest.mkdir(exist_ok=True)
    (dest/"source-rows").mkdir(exist_ok=True)
    result=[];seen=set(target);tickers=set();counts={}
    for folder in sorted(Path("peer-batches").glob("*")):
        rows=read(folder/"peers.json")
        accepted=0
        for r in rows:
            t=r["ticker"];corp=r.get("corp_code")
            rawfile=folder/"source-rows"/(t+".json")
            if not corp or corp in seen or t in tickers or r.get("financial_model") or r.get("financial_year")!=year or not r.get("peer_only") or r.get("industry_confidence")!="verified" or not rawfile.exists():continue
            raw=read(rawfile)
            if not source_check(raw,year,"CFS") or sorted({str(x["rcept_no"]) for x in raw if x.get("rcept_no")})!=r.get("receipts"):continue
            metrics=extract_financial(raw,ticker=t,financial_year=year,fs_div="CFS")
            r["industry_metrics"]=admitted_industry_metrics(metrics["industry_metrics"],metrics["industry_metric_quality"],year)
            r["alternative_metrics"]=alternatives(raw,year,"CFS")
            result.append(r);seen.add(corp);tickers.add(t);accepted+=1
            shutil.copyfile(rawfile,dest/"source-rows"/(t+".json"))
        counts[folder.name]=accepted
    (dest/"peers.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    summary={"peer_count":len(result),"accepted_by_batch":counts,"year":year,"release_gate":"not_verified"}
    (dest/"merge-summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print("PEER MERGE SUMMARY",json.dumps(summary),flush=True)
if __name__=="__main__":main()
