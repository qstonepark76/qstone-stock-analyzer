"""Review actual specialist source observations, with no unverified admissions.
Show exact available account definitions and value response labels for each
target/peer; do not guess issuer identity or annual flow basis.
"""
import json
import re
from collections import Counter,defaultdict
from pathlib import Path
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def main():
    rows=read("expanded-source/records.json")
    meta=read("expanded-source/metadata.json")
    models=read("audit-financial-simplified/records.json")
    targets={x["ticker"]:x for x in models}
    groups=defaultdict(list)
    counts=Counter()
    for r in rows:
        if r.get("status")!="received":continue
        p=r.get("response",{})
        values=p.get("list",[])
        if p.get("err_cd")!="000" or not isinstance(values,list) or len(values)!=1:continue
        v=values[0]
        if v.get("base_month")!="202512" or v.get("finance_cd")!=r["company"] or v.get("account_cd")!=r["account"] or v.get("account_nm")!=r["label"]:continue
        k=(r["sector"],r["table"],r["account"],r["label"])
        groups[k].append({"company":r["company"],"name":r["name"],"candidate_ticker":r.get("candidate_ticker"),
                          "unit":p.get("unit"),"description":p.get("description"),"settlement":p.get("date_of_settlement"),"values":v})
        counts[r["sector"]]+=1
    review=[]
    for (sector,table,account,label),v in sorted(groups.items()):
        entry={"sector":sector,"table":table,"account":account,"label":label,"valid_response_count":len(v),
               "target_matches":len({x["candidate_ticker"] for x in v if x["candidate_ticker"]}),"sample":v[:2],"observations":v}
        review.append(entry)
        print("SPECIALIST ACCOUNT REVIEW",json.dumps({k:x for k,x in entry.items() if k!="observations"},ensure_ascii=False),flush=True)
    out=Path("audit-specialist-account-review");out.mkdir(exist_ok=True)
    summary={"raw_received":sum(r.get("status")=="received" for r in rows),"structurally_valid":sum(counts.values()),"counts":dict(counts),"account_definitions":len(review),"admitted_new_metrics":0,"release_gate":"not_verified","warning":"Exact FISIS response reconciliation only; issuer identity, regulatory scope, annual flow definitions and comparability still require review."}
    (out/"records.json").write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print("SPECIALIST ACCOUNT REVIEW SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
