"""Enrich the saved top-300 audit with XBRL only where annual D&A is missing."""
import json
import io
import sys
import time
import zipfile
import re
from pathlib import Path
sys.path.insert(0,"scripts")
from collect import extract_financial
from financial_industry import financial_model_for
from xbrl_note_evidence import fetch_archive, extract_instance, MAX_BYTES, KEY
from xbrl_da_rule import select_da

SOURCE=Path("replay-source")
OUT=Path("audit-top300-xbrl")

def main():
    OUT.mkdir(exist_ok=True)
    report=json.loads((SOURCE/"report.json").read_text(encoding="utf-8"))
    if report.get("sample_count")!=300 or not KEY:
        raise SystemExit("Source universe or DART credential unavailable")
    cache=json.loads(Path("data/sector_industry_cache.json").read_text(encoding="utf-8"))
    year=report["year"]
    results={}
    status_counts={}
    seen={}
    for r in report["records"]:
        ticker=r["ticker"]
        receipts=r.get("receipts") or []
        code=(cache.get(ticker) or {}).get("industry_code")
        if r["status"]!="source_received" or r.get("scope")!="CFS" or financial_model_for(ticker,code) or len(receipts)!=1 or not re.fullmatch(r"\d{14}",receipts[0]):
            continue
        raw=json.loads((SOURCE/"source-rows"/(ticker+".json")).read_text(encoding="utf-8"))
        baseline=extract_financial(raw,ticker=ticker,financial_year=year,fs_div="CFS")
        capital=baseline["capital_metric_audit"]
        if capital.get("depreciation_amortisation") is not None:
            continue
        receipt=receipts[0]
        if receipt in seen:
            result=seen[receipt]
        else:
            result={"receipt":receipt,"year":year,"facts":[]}
            try:
                blob,status=fetch_archive(receipt)
                result["status"]=status
                if blob:
                    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                        members=[m for m in archive.infolist() if not m.is_dir()]
                        if sum(m.file_size for m in members)>3*MAX_BYTES:
                            raise ValueError("expanded_archive_size_limit")
                        for m in members:
                            if m.filename.lower().endswith((".xbrl",".xml")) and m.file_size<=MAX_BYTES:
                                instance=extract_instance(archive.read(m),year)
                                if instance:
                                    result["facts"].extend(f for f in instance["facts"] if f["concept"].endswith(("}AdjustmentsForDepreciationExpense","}AdjustmentsForAmortisationExpense")))
                    result["status"]=select_da(result["facts"],year)["status"]
            except Exception as exc:
                result["status"]=type(exc).__name__
            seen[receipt]=result
            time.sleep(.35)
        results[ticker]=result
        status_counts[result["status"]]=status_counts.get(result["status"],0)+1
        print("TOP300 XBRL RECORD",ticker,result["status"],flush=True)
        # Save incrementally so timeout does not discard completed observations.
        (OUT/"notes.json").write_text(json.dumps(results,ensure_ascii=False),encoding="utf-8")
    (OUT/"notes.json").write_text(json.dumps(results,ensure_ascii=False),encoding="utf-8")
    print("TOP300 XBRL SUMMARY",json.dumps({"targeted":len(results),"distinct_receipts":len(seen),"status":status_counts},ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
