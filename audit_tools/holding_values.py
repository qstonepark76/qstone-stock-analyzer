"""Probe exact group-level CET1/NPL values, never substitute bank subsidiaries.

Only FISIS company/account identifiers actually observed in metadata audit
45628431830 are used. Source evidence only until rule tests pass.
"""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,"scripts")
from audit_v33_fisis import query, KEY
from fisis_expansion import annual_probe

OUT=Path("audit-holding-values")
COMPANIES={
 "0012028":"주식회사 케이비금융지주",
 "0010926":"주식회사 신한금융지주회사",
 "0011573":"주식회사 하나금융지주",
 "0016619":"주식회사 우리금융지주",
 "0012710":"(주)BNK금융지주",
 "0012739":"주식회사 디지비금융지주",
 "0013406":"JB금융지주",
 "0013188":"농협금융지주 주식회사",
}
ACCOUNTS={
 ("SL008","C2"):"BIS기준 자기자본비율_보통주자본 비율",
 ("SL026","C"):"보통주자본 비율",
 ("SL009","B1"):"(고정이하여신비율)",
}

def main():
    OUT.mkdir(exist_ok=True)
    if not KEY:
        return 1
    catalog={r["finance_cd"]:r["finance_nm"] for r in query("companySearch",{"partDiv":"L"})["rows"]}
    account_catalog={}
    for table in sorted({p[0] for p in ACCOUNTS}):
        account_catalog[table]={r["account_cd"]:r["account_nm"] for r in query("accountListSearch",{"listNo":table})["rows"]}
    records=[]
    for company,name in COMPANIES.items():
        for (table,account),label in ACCOUNTS.items():
            rec={"company":company,"name":name,"table":table,"account":account,"label":label,"term":"Y"}
            if catalog.get(company)!=name or account_catalog[table].get(account)!=label:
                rec["status"]="metadata_mismatch"
            else:
                rec.update(annual_probe(company,table,account,"Y"))
            records.append(rec)
            print("HOLDING VALUE EVIDENCE",json.dumps(rec,ensure_ascii=False),flush=True)
            time.sleep(.35)
    report={"period":"202512","records":records,"received":sum(r["status"]=="received" for r in records)}
    (OUT/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("HOLDING VALUE SUMMARY",json.dumps({"requested":len(records),"received":report["received"]}),flush=True)
    return 0 if report["received"] else 1

if __name__=="__main__":
    raise SystemExit(main())
