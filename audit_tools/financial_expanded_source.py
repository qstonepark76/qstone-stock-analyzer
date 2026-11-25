"""Collect missing financial specialist evidence from actual FISIS catalogs.
No accounting ratio substitution for prudential metrics; no automatic scoring.
Group and legal-entity scopes remain distinct. Unlisted peers require review.
"""
import json
import sys
import time
import re
from pathlib import Path
from collections import Counter
sys.path.insert(0,"scripts")
from audit_v33_fisis import query,KEY
from fisis_expansion import annual_probe
OUT=Path("audit-financial-expanded-source")
# Known metadata account pairs are probed directly for additional legal entities.
KNOWN={"A":[("SA014","A2"),("SA015","C"),("SA017","C")],
       "H":[("SH021","A"),("SH112","A"),("SH114","B")],
       "I":[("SI021","A"),("SI112","A"),("SI114","D")],
       "F":[("SF308","E"),("SF209","C"),("SF331","C")],
       "C":[("SC007","A"),("SC010","A"),("SC117","B")],
       "L":[("SL008","C2"),("SL009","B1"),("SL026","C")]}
TERMS=("순이자마진","순이자수익률","비용수익비율","대손비용률","우발채무","보험서비스","운용자산이익률","영업비용률","자기자본비율","고정이하여신비율")
def norm(x):
    return re.sub(r"[\s()㈜]","",str(x or "").replace("주식회사","")).strip().casefold()
def main():
    if not KEY:
        raise SystemExit("FISIS credential unavailable")
    models=json.loads(Path("audit-financial-simplified/records.json").read_text(encoding="utf-8"))
    target_names={norm(x["name"]):x for x in models}
    OUT.mkdir(exist_ok=True)
    evidence=[]
    metadata={}
    counts=Counter()
    for sector,pairs in KNOWN.items():
        companies=query("companySearch",{"partDiv":sector})
        tables=query("statisticsListSearch",{"lrgDiv":sector})
        active=[r for r in companies["rows"] if r.get("finance_cd") and r.get("finance_nm") and "[폐]" not in r["finance_nm"]]
        relevant=[r for r in tables["rows"] if any(t in str(r.get("list_nm") or "") for t in TERMS+("경영지표","주요경영","수익성","건전성","손익"))]
        chosen=sorted({x[0] for x in pairs}|{str(x["list_no"]) for x in relevant if x.get("list_no")})[:40]
        accounts={}
        actual=[]
        for table in chosen:
            rows=query("accountListSearch",{"listNo":table})["rows"]
            accounts[table]=rows
            for r in rows:
                label=str(r.get("account_nm") or "")
                if (table,r.get("account_cd")) in pairs or any(t in label for t in TERMS):
                    actual.append((table,r["account_cd"],label))
            time.sleep(.25)
        # Exact normalized legal-name matches only. Broader company catalog
        # retained for identity review, including unlisted independent peers.
        # Do not assume names with insurance/holding suffixes are equivalent.
        selected=[r for r in active if norm(r["finance_nm"]) in target_names]
        # Add a bounded set of sector peers for scope and identity review.
        remainder=[r for r in active if r not in selected]
        selected=selected+remainder[:max(0,20-len(selected))]
        metadata[sector]={"companies":active,"tables":relevant,"accounts":accounts,"selected":selected}
        unique=list(dict.fromkeys(actual))[:18]
        for company in selected:
            for table,account,label in unique:
                rec={"sector":sector,"company":company["finance_cd"],"name":company["finance_nm"],"table":table,"account":account,"label":label,"term":"Y"}
                match=target_names.get(norm(company["finance_nm"]))
                if match:
                    rec["candidate_ticker"]=match["ticker"]
                rec.update(annual_probe(company["finance_cd"],table,account,"Y"))
                counts[sector+":"+rec["status"]]+=1
                evidence.append(rec)
                time.sleep(.25)
        print("FINANCIAL EXPANDED SECTOR",sector,json.dumps({"active_entities":len(active),"selected":len(selected),"candidate_exact_names":sum(norm(r["finance_nm"]) in target_names for r in selected),"account_candidates":len(unique),"received":counts[sector+":received"]},ensure_ascii=False),flush=True)
        (OUT/"records.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf-8")
    summary={"requested":len(evidence),"received":sum(r["status"]=="received" for r in evidence),"counts":dict(counts),"candidate_tickers":len({r["candidate_ticker"] for r in evidence if r.get("candidate_ticker") and r["status"]=="received"}),"release_gate":"not_verified","warning":"Annual source evidence only. Exact legal name candidates and independent peer identities, account definitions, scopes and period must be reviewed before scoring."}
    (OUT/"metadata.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print("FINANCIAL EXPANDED SOURCE SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__":
    main()
