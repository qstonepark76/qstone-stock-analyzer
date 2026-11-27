"""Review source coverage and reconcile exact same-date broker targets.
Source candidates acquired after the frozen date cannot become past scores.
"""
import json
from pathlib import Path
from collections import defaultdict,Counter
from datetime import datetime,date
from leading_kis_outlook_probe import rows,numeric
from outlook_candidate import broker_key
from verify_broker_reports import norm_name,normalize_rating
from final_leading_model import finite
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")

def index_naver(reports):
    groups=defaultdict(set)
    for r in reports:
        k=(r.get("ticker"),broker_key(r.get("broker")),r.get("published_at"))
        t=r.get("target_price")
        if all(k) and finite(t) and t>0 and r.get("verification_method") and r.get("verified_at"):groups[k].add(t)
    return groups

def review(records,universe,naver):
    c=Counter();details=[];overlap=[]
    for r in records:
        t=r["ticker"];e=r.get("estimate-perform",{});o=r.get("invest-opinion",{})
        s={"ticker":t,"estimate_observed_at":e.get("observed_at"),"opinion_observed_at":o.get("observed_at")}
        meta=rows(e.get("outputs",{}).get("output1"))
        ident=bool(meta and all(str(x.get("sht_cd","")).zfill(6)==t and norm_name(x.get("item_kor_nm"))==norm_name(universe[t]["name"]) for x in meta))
        c["estimate_identity_verified"]+=ident
        s["estimate_identity_verified"]=ident
        table={k:rows(e.get("outputs",{}).get(k)) for k in ("output2","output3","output4")}
        # Header-only output is not an actual earnings forecast.
        populated=ident and bool(table["output2"] or table["output3"]) and bool(table["output4"]) and any(numeric(v) is not None for k in ("output2","output3") for x in table[k] for f,v in x.items() if f in ("data1","data2","data3","data4","data5"))
        c["estimate_table_with_numeric_candidate_and_period"]+=populated
        s["estimate_numeric_table_candidate"]=populated
        s["estimate_row_counts"]={k:len(v) for k,v in table.items()}
        s["estimate_period_labels"]=[str(x.get("dt","")) for x in table["output4"]]
        # Unspecified field semantics and monetary scale stay unverified.
        s["estimate_admitted"]=False
        op=defaultdict(set)
        for x in o.get("date_checked_candidates",[]):
            broker=broker_key(x.get("broker"));d=x.get("report_date")
            if not broker or not d:continue
            rating=normalize_rating({"source_opinion_text":x.get("opinion")})
            target=x.get("target_price_candidate")
            op[(broker,d)].add((rating,target))
        accepted=[];conflicts=0
        for (b,d),vs in op.items():
            if len(vs)!=1:conflicts+=1;continue
            rating,target=next(iter(vs))
            accepted.append((b,d,rating,target))
            if target is not None:
                k=(t,b,d);v=naver.get(k,set())
                if len(v)==1:
                    other=next(iter(v));same=target==other
                    overlap.append({"ticker":t,"broker":b,"date":d,"kis_target":target,"naver_target":other,"match":same})
        s["opinion_distinct_broker_date_rows"]=len(accepted);s["opinion_conflicts"]=conflicts
        s["opinion_brokers"]=len({b for b,d,a,v in accepted if a})
        s["target_brokers"]=len({b for b,d,a,v in accepted if finite(v) and v>0})
        s["three_broker_ratings"]=s["opinion_brokers"]>=3
        s["three_broker_targets"]=s["target_brokers"]>=3
        c["opinion_issuers_with_rows"]+=bool(accepted)
        c["three_broker_rating_candidates"]+=s["three_broker_ratings"]
        c["three_broker_target_candidates"]+=s["three_broker_targets"]
        c["distinct_broker_date_rows"]+=len(accepted);c["same_broker_date_conflicts"]+=conflicts
        details.append(s)
    c["exact_naver_target_comparisons"]=len(overlap);c["exact_naver_target_matches"]=sum(x["match"] for x in overlap)
    return dict(c),details,overlap
def main():
    out=Path("audit-leading-kis-outlook-expanded")
    records=read(out/"raw_candidates.json")
    if len({r["ticker"] for r in records})!=len(records):raise ValueError("duplicate issuers")
    universe={r["ticker"]:r for r in read("replay-source/universe.json")["stocks"]}
    naver=index_naver(read("data/analyst_reports.json")["reports"])
    c,details,overlap=review(records,universe,naver)
    s={"processed_issuers":len(records),"coverage":c,"official_admitted":0,"note":"Actual observation date retained. Exact target agreement is not proof of adjusted share basis; no historical frozen scoring or estimate field interpretation."}
    for n,v in (("review-summary.json",s),("review-issuers.json",details),("review-target-overlap.json",overlap)):write(out/n,v)
    print("KIS OUTLOOK EXPANDED REVIEW",json.dumps(s,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
