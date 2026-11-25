"""Read-only FISIS actual-value audit for observed source account codes.

These are raw regulatory observations, not official scores. Bank subsidiaries
must never stand in for consolidated listed holding groups. Do not assume that
a ratio uses percent units, or that the observation matches a model definition.
"""
import json
import time
from pathlib import Path
import requests
from audit_v33_fisis import BASE, KEY, query

OUT = Path("audit-fisis-values")
PERIOD = "202512"
# Company IDs and table/account pairs observed in run 45619807754.
GROUPS = {
    "bank_subsidiary_only": ("A", ("0010927","0011625","0010001","0013909"),
        (("SA014","A2"),("SA015","C"),("SA017","C"))),
    "life_insurance": ("H", ("0010595","0010593","0010608","0010597","0010620","0010599"),
        (("SH021","A"),("SH021","D"),("SH112","A"),("SH114","B"))),
    "nonlife_insurance": ("I", ("0010636","0010633","0010634","0010627","0010635","0010626"),
        (("SI021","A"),("SI021","D"),("SI112","A"),("SI114","D"))),
    "securities": ("F", ("0010119","0010094","0010129","0010106","0010091","0010090"),
        (("SF308","E"),("SF331","C"),("SF209","C"))),
    "card_only": ("C", ("0010228","0010229","0010225","0012627","0010226"),
        (("SC007","A"),("SC008","D"),("SC010","A"),("SC117","B"))),
}

def safe_public(value, depth=0):
    """Allow only scalar public response data, excluding keys and request URLs."""
    if depth > 6:
        return None
    if isinstance(value, dict):
        return {k:safe_public(v,depth+1) for k,v in value.items()
                if k.lower() not in ("auth","key","apikey","url","message","err_msg","error_msg","request")
                and KEY not in k}
    if isinstance(value,list):
        return [safe_public(v,depth+1) for v in value[:100]]
    if isinstance(value,str) and (KEY in value or "http://" in value or "https://" in value):
        return None
    if isinstance(value,(str,int,float,bool,type(None))):
        return value
    return None

def get_observation(company, table, account):
    try:
        response = requests.get(BASE+"statisticsInfoSearch.json",
            params={"lang":"kr","auth":KEY,"financeCd":company,"listNo":table,
                    "accountCd":account,"term":"Q","startBaseMm":PERIOD,"endBaseMm":PERIOD},
            timeout=(8,20),allow_redirects=False)
        if response.status_code != 200:
            return {"status":"http_"+str(response.status_code)}
        result = response.json().get("result")
        if not isinstance(result,dict):
            return {"status":"unexpected_response"}
        public = safe_public(result)
        rows = result.get("list")
        return {"status":"rows_received" if isinstance(rows,list) and rows else "no_rows",
                "response":public}
    except Exception as exc:
        return {"status":type(exc).__name__}

def main():
    if not KEY:
        print("FISIS_AUTH_KEY missing",flush=True)
        return 1
    OUT.mkdir(exist_ok=True)
    report = {"period":PERIOD,"scope":"raw observation only; definition and unit review pending","groups":{}}
    for group,(sector,companies,pairs) in GROUPS.items():
        catalog = query("companySearch",{"partDiv":sector})
        identities = {r.get("finance_cd"):r.get("finance_nm") for r in catalog["rows"]}
        accounts = {}
        for table in sorted({p[0] for p in pairs}):
            raw = query("accountListSearch",{"listNo":table})
            accounts[table] = {r.get("account_cd"):r.get("account_nm") for r in raw["rows"]}
        records = []
        for company in companies:
            for table,account in pairs:
                name = identities.get(company)
                label = accounts[table].get(account)
                if not name or "[폐]" in name or not label:
                    observation = {"status":"metadata_mismatch"}
                else:
                    observation = get_observation(company,table,account)
                    time.sleep(.3)
                record = {"company":company,"name":name,"table":table,"account":account,"label":label,**observation}
                records.append(record)
                print("FISIS VALUE EVIDENCE",group,json.dumps(record,ensure_ascii=False),flush=True)
        report["groups"][group] = records
    summary = {g:{"requested":len(rows),"received":sum(r["status"]=="rows_received" for r in rows)}
               for g,rows in report["groups"].items()}
    report["summary"] = summary
    (OUT/"raw_observations.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("FISIS VALUE SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
    return 0 if all(v["received"]>0 for v in summary.values()) else 1

if __name__ == "__main__":
    raise SystemExit(main())
