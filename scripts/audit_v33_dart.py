"""Read-only real OpenDART audit for the v3.3 representative sample.
No production files or scores are written. Authentication is environment-only.
A successful API request is NOT independent confirmation of the calculations.
"""
import datetime as dt
import json
import math
import os
from pathlib import Path
import time
from collect import DART_KEY, download_corp_map, dart_company_financial, extract_financial
from financial_industry import financial_model_for
from industry_relative import METRICS

SAMPLE = {
    "005930":"삼성전자", "000660":"SK하이닉스",
    "005380":"현대차", "000270":"기아",
    "267260":"HD현대일렉트릭", "298040":"효성중공업",
    "064350":"현대로템", "012450":"한화에어로스페이스",
    "207940":"삼성바이오로직스", "128940":"한미약품",
    "010950":"S-OIL", "051910":"LG화학",
    "105560":"KB금융", "032830":"삼성생명", "016360":"삼성증권",
}
FIELDS = ("rcept_no","bsns_year","reprt_code","fs_div","sj_div","account_id",
          "account_nm","account_detail","thstrm_nm","thstrm_amount",
          "frmtrm_nm","frmtrm_amount","currency")
OUT = Path("audit-v33")

def audit():
    OUT.mkdir(exist_ok=True)
    year = dt.date.today().year - 1
    report = {"year":year,"source":"OpenDART annual full financial statements",
              "sample_count":len(SAMPLE),"records":[],"status":"not_started",
              "review_status":"independent source-account review pending"}
    if not DART_KEY:
        report["status"] = "DART_AUTH_KEY missing"
        return report
    try:
        mapping = download_corp_map()
    except Exception as exc:
        # Exception strings may contain a URL with a secret query parameter.
        report["status"] = "corp_map_failed:" + type(exc).__name__
        return report
    raw_dir = OUT / "source-rows"
    raw_dir.mkdir(exist_ok=True)
    for ticker, name in SAMPLE.items():
        model = financial_model_for(ticker)
        row = {"ticker":ticker,"name":name,"financial_model":model}
        corp = mapping.get(ticker)
        if not corp:
            row["status"] = "corp_code_missing"
        else:
            try:
                items, scope, message = dart_company_financial(corp, year)
                if not items:
                    row["status"] = "no_statement"
                else:
                    # Store public filing data only, not request URLs or credentials.
                    clean = [{k:r.get(k) for k in FIELDS} for r in items
                             if isinstance(r, dict) and r.get("sj_div") in ("BS","IS","CIS","CF")]
                    (raw_dir / (ticker+".json")).write_text(json.dumps(clean,ensure_ascii=False,indent=2),encoding="utf-8")
                    # Expose public account evidence for targeted review without needing
                    # to download the entire artifact. No headers, keys or URLs.
                    if not model:
                        selected = []
                        terms = {
                            "BS": ("차입", "사채", "장기부채", "리스", "현금및현금", "자본총계"),
                            "IS": ("매출", "영업이익", "영업손익", "법인세", "세전"),
                            "CIS": ("매출", "영업이익", "영업손익", "법인세", "세전"),
                            "CF": ("감가상각", "무형자산상각", "영업활동"),
                        }
                        for rr in clean:
                            name = str(rr.get("account_nm") or "").replace(" ", "")
                            section = rr.get("sj_div")
                            if any(term in name for term in terms.get(section, ())):
                                selected.append([section, rr.get("account_id"), rr.get("account_nm"),
                                                 rr.get("account_detail"), rr.get("thstrm_amount"),
                                                 rr.get("frmtrm_amount"), rr.get("currency")])
                        print("DART ACCOUNT EVIDENCE", ticker, scope, json.dumps(selected, ensure_ascii=False), flush=True)
                    metrics = extract_financial(items, ticker=ticker, financial_year=year, fs_div=scope)
                    values = metrics.get("industry_metrics") or {}
                    row.update(status="source_received",scope=scope,corp_code=corp,
                               receipts=sorted({str(r.get("rcept_no")) for r in clean if r.get("rcept_no")}),
                               source_row_count=len(clean),
                               industry_metrics=values if not model else None,
                               capital_metric_audit=metrics.get("capital_metric_audit") if not model else None,
                               financial_status="specialized_source_pending" if model else None)
            except Exception as exc:
                row["status"] = "request_or_extract_failed:" + type(exc).__name__
        report["records"].append(row)
        print(ticker, name, row["status"], json.dumps(row.get("industry_metrics"), ensure_ascii=False),flush=True)
        time.sleep(.25)
    industrial = [r for r in report["records"] if not r["financial_model"]]
    coverage = {}
    for key in METRICS:
        valid = sum(isinstance((r.get("industry_metrics") or {}).get(key), (int,float))
                    and not isinstance((r.get("industry_metrics") or {}).get(key),bool)
                    and math.isfinite((r.get("industry_metrics") or {})[key]) for r in industrial)
        coverage[key] = {"calculated":valid,"sample":len(industrial)}
    report.update(status="sample_collection_finished",
                  received_count=sum(r["status"]=="source_received" for r in report["records"]),
                  industrial_coverage=coverage)
    return report

if __name__ == "__main__":
    report = audit()
    (OUT/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    summary = "DART AUDIT SUMMARY: " + json.dumps({k:v for k,v in report.items() if k!="records"},ensure_ascii=False)
    print(summary,flush=True)
    if report.get("received_count",0) != len(SAMPLE):
        raise SystemExit(1)
