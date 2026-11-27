"""Discover missing financial holding and capital-sector source mappings.

L/T/K are candidate sector identifiers from public API documentation examples.
Verify actual metadata before mapping any financial company or account.
No scoring, no subsidiary proxies, no production writes.
"""
import json
import sys
import time
from pathlib import Path
import requests

sys.path.insert(0,"scripts")
from audit_v33_fisis import query, KEY, BASE
from audit_v33_fisis_values import safe_public

OUT=Path("audit-fisis-expansion")
SECTORS={"L":"holding_candidate","T":"capital_candidate","K":"leasing_candidate"}
TERMS=("보통주","자본","건전","여신","대손","연체","유동","순이자","비용","수익","경영","레버리지","충당","이자")
ANNUAL_PROBES=(("0010595","SH114","B"),("0010593","SH114","B"),("0010633","SI114","D"),("0010636","SI114","D"))

def annual_probe(company,table,account,term):
    try:
        r=requests.get(BASE+"statisticsInfoSearch.json",params={"lang":"kr","auth":KEY,
            "financeCd":company,"listNo":table,"accountCd":account,"term":term,
            "startBaseMm":"202512","endBaseMm":"202512"},timeout=(8,20),allow_redirects=False)
        if r.status_code!=200:
            return {"status":"http_"+str(r.status_code)}
        result=r.json().get("result")
        if not isinstance(result,dict):
            return {"status":"unexpected_response"}
        return {"status":"received" if result.get("err_cd")=="000" and result.get("list") else "no_value",
                "response":safe_public(result)}
    except Exception as exc:
        return {"status":type(exc).__name__}

def main():
    OUT.mkdir(exist_ok=True)
    if not KEY:
        print("FISIS_AUTH_KEY missing",flush=True)
        return 1
    report={"period":"202512","scope":"discovery only; identity and financial basis pending","sectors":{},"annual_probes":[]}
    for sector,name in SECTORS.items():
        companies=query("companySearch",{"partDiv":sector})
        catalog=query("statisticsListSearch",{"lrgDiv":sector})
        relevant=[r for r in catalog["rows"] if r.get("list_no") and any(t in str(r.get("list_nm") or "") for t in TERMS)]
        group={"candidate_type":name,"companies":companies,"catalog":catalog,"accounts":{}}
        print("FISIS EXPANSION COMPANIES",sector,json.dumps(companies,ensure_ascii=False),flush=True)
        print("FISIS EXPANSION TABLES",sector,json.dumps(relevant,ensure_ascii=False),flush=True)
        # Bound metadata requests; report the complete table catalog in artifact.
        for table in sorted({r["list_no"] for r in relevant})[:40]:
            result=query("accountListSearch",{"listNo":table})
            group["accounts"][table]=result
            matches=[r for r in result["rows"] if any(t in str(r.get("account_nm") or "") for t in TERMS)]
            print("FISIS EXPANSION ACCOUNTS",sector,table,json.dumps(matches,ensure_ascii=False),flush=True)
            time.sleep(.35)
        report["sectors"][sector]=group
    # Do not equate Q4 and annual observations just because base_month matches.
    for company,table,account in ANNUAL_PROBES:
        for term in ("Y","Q"):
            record={"company":company,"table":table,"account":account,"term":term,
                    **annual_probe(company,table,account,term)}
            report["annual_probes"].append(record)
            print("FISIS ANNUAL PROBE",json.dumps(record,ensure_ascii=False),flush=True)
            time.sleep(.35)
    summary={code:{"companies":len(g["companies"]["rows"]),"tables":len(g["catalog"]["rows"]),
                   "account_tables":len(g["accounts"])} for code,g in report["sectors"].items()}
    report["summary"]=summary
    (OUT/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("FISIS EXPANSION SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
    return 0 if all(g["companies"] and g["tables"] for g in summary.values()) else 1

if __name__=="__main__":
    raise SystemExit(main())
