"""Read-only FISIS connectivity and metadata discovery; never score unreviewed data."""
import os
import json
from pathlib import Path
import time
import requests

BASE = "https://fisis.fss.or.kr/openapi/"
KEY = os.environ.get("FISIS_AUTH_KEY", "").strip()
OUT = Path("audit-fisis")
# Candidate codes from published API examples; actual response labels must be reviewed.
COMPANY_CODES = ("A", "H", "I", "F", "C")
TABLES = ("SA014", "SA015", "SA017", "SH021", "SH112", "SH114",
          "SI021", "SI112", "SI114", "SF308", "SF331", "SF209",
          "SC007", "SC008", "SC010", "SC117")
SAFE_FIELDS = {"finance_cd","finance_nm","list_no","list_nm","account_cd","account_nm",
               "part_div","part_div_nm","lrg_div","sml_div","unit","unit_nm"}

def query(endpoint, params):
    if not KEY:
        return {"status":"missing_secret", "rows":[]}
    try:
        # Do not follow redirects or transmit credentials over plaintext HTTP.
        response = requests.get(BASE+endpoint+".json",
                                params={"lang":"kr","auth":KEY,**params},
                                timeout=(8,20),allow_redirects=False)
        if response.status_code != 200:
            return {"status":"http_"+str(response.status_code),"rows":[]}
        payload = response.json()
        result = payload.get("result")
        if not isinstance(result,dict):
            return {"status":"unexpected_response","rows":[]}
        raw = result.get("list")
        if not isinstance(raw,list):
            return {"status":"no_list","rows":[]}
        rows = [{k:v for k,v in row.items() if k in SAFE_FIELDS and isinstance(v,(str,int,float,type(None)))
                 and KEY not in str(v)} for row in raw if isinstance(row,dict)]
        rows = [r for r in rows if r]
        return {"status":"metadata_received" if rows else "empty_list","rows":rows}
    except Exception as exc:
        return {"status":type(exc).__name__,"rows":[]}

def main():
    OUT.mkdir(exist_ok=True)
    report = {"companies":{},"statistics":{},"accounts":{},"scope":"metadata discovery only; no verified scoring"}
    if not KEY:
        print("FISIS_AUTH_KEY: missing",flush=True)
        return 1
    for code in COMPANY_CODES:
        result = query("companySearch",{"partDiv":code})
        report["companies"][code] = result
        print("FISIS companySearch",code,result["status"],"rows",len(result["rows"]),flush=True)
        time.sleep(.3)
    # Discover actual table names by sector, not guessed account codes.
    # Only metadata is logged; never request URL, credentials or headers.
    terms = ("순이자", "자본", "고정이하", "대손", "경영", "건전", "지급여력", "보험", "손해율",
             "합산", "수익", "유동", "연체", "우발", "레버리지", "CSM", "신계약", "위험")
    for code in COMPANY_CODES:
        if report["companies"][code]["status"] != "metadata_received":
            continue
        companies = report["companies"][code]["rows"]
        print("FISIS COMPANY EVIDENCE",code,json.dumps(companies,ensure_ascii=False),flush=True)
        result = query("statisticsListSearch",{"lrgDiv":code})
        report["statistics"][code] = result
        relevant = [row for row in result["rows"]
                    if any(term in str(row.get("list_nm") or "") for term in terms)]
        print("FISIS TABLE EVIDENCE",code,result["status"],json.dumps(relevant,ensure_ascii=False),flush=True)
        time.sleep(.3)
    if any(r["status"]=="metadata_received" for r in report["companies"].values()):
        for code in TABLES:
            result = query("accountListSearch",{"listNo":code})
            report["accounts"][code] = result
            print("FISIS ACCOUNT EVIDENCE",code,result["status"],json.dumps(result["rows"],ensure_ascii=False),flush=True)
            time.sleep(.3)
    (OUT/"metadata.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    return 0 if any(r["status"]=="metadata_received" for r in report["companies"].values()) else 1

if __name__ == "__main__":
    raise SystemExit(main())
