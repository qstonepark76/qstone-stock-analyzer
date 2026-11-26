"""Coverage and candidate points on frozen 300; never changes published scores."""
import json
import sys
from pathlib import Path
from collections import Counter
sys.path.insert(0,"scripts")
from fundamental_candidate import derive,slots,WEIGHTS
from financial_industry import FINANCIAL_MODELS,comparable_observation
from industry_relative import percentile_score
def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))
def main():
    audit=read("replay-source/report.json")
    universe=read("replay-source/universe.json")
    replay=read("audit-top300-replay/records.json")
    sources={r["ticker"]:r for r in audit["records"]}
    meta={r["ticker"]:r for r in replay}
    assert len(sources)==len(meta)==len(universe["stocks"])==300
    data=[]
    for u in universe["stocks"]:
        t=u["ticker"]
        s=sources[t]; r=meta[t]
        model=r.get("financial_model")
        row={"ticker":t,"name":u["name"],"model":model,"industry_code":r.get("industry_code"),"class":r["screening_class"],"metrics":{}}
        if s["status"]=="source_received" and row["class"] not in ("known_preferred_share","duplicate_issuer_pending"):
            raw=read("replay-source/source-rows/"+t+".json")
            if sorted({str(x["rcept_no"]) for x in raw if x.get("rcept_no")})==s.get("receipts"):
                regulatory={}
                for k in FINANCIAL_MODELS.get(model,{}):
                    obs=comparable_observation(r.get("financial_observations"),k,model,str(audit["year"])+"-12")
                    if obs:
                        orig=r["financial_observations"]["metrics"][k]
                        regulatory[k]={**orig,"lower_better":not FINANCIAL_MODELS[model][k]["higher_is_better"]}
                row["metrics"]=derive(raw,audit["year"],s.get("scope"),u["market_cap"],model,regulatory)
        row["slots"]=slots(row["metrics"],model)
        data.append(row)
    def signature(v):
        return (v.get("year",v.get("period")),v.get("scope"),v.get("basis"),v.get("definition_id"))
    summaries={}
    for row in data:
        factors={}
        for factor,weights in WEIGHTS.items():
            detail={}
            for slot,w in weights.items():
                key=row["slots"][factor][slot]
                v=row["metrics"].get(key)
                if not isinstance(v,dict): continue
                # Same metric, fiscal/scope basis and economic model only.
                # Valuation peers additionally require exact industry code;
                # avoid using unrelated sectors' P/S multiples.
                peers=[]
                for p in data:
                    if p["model"]!=row["model"]:continue
                    if factor=="valuation" and (not row["industry_code"] or p["industry_code"]!=row["industry_code"]):continue
                    other=p["metrics"].get(key)
                    if isinstance(other,dict) and signature(other)==signature(v):
                        peers.append(other["value"])
                points=round(w*percentile_score(v["value"],peers,not v.get("lower_better",False))/100,4) if len(peers)>=5 else None
                detail[slot]={"metric":key,"weight":w,"observed":True,"points":points,"peer_count":len(peers)}
            factors[factor]={"observed_weight":sum(d["weight"] for d in detail.values()),
                             "comparable_weight":sum(d["weight"] for d in detail.values() if d["points"] is not None),
                             "experimental_points":sum(d["points"] or 0 for d in detail.values()),"detail":detail}
        row["factors"]=factors
    for f,w in WEIGHTS.items():
        total=sum(w.values())
        summaries[f]={"weight":total,"full_observed":sum(r["factors"][f]["observed_weight"]==total for r in data),
          "full_comparable":sum(r["factors"][f]["comparable_weight"]==total for r in data),
          "weighted_observed_pct":round(100*sum(r["factors"][f]["observed_weight"] for r in data)/(300*total),2),
          "slot_counts":{k:sum(k in r["factors"][f]["detail"] for r in data) for k in w},
          "metric_use":dict(Counter(d["metric"] for r in data for d in r["factors"][f]["detail"].values()))}
    summary={"universe":300,"asof":universe["asof"],"factors":summaries,"release_gate":"not_verified",
             "warning":"Candidate only. Missing stays missing; proposed financial classifications, alternative valuation calibration, overlap between financial and relative factors, and cross-source reconciliation remain pending. EV/EBITDA, NAV, FFO inputs not yet independently verified. CAGR uses three annual observations over two years."}
    out=Path("audit-fundamental-candidate");out.mkdir(exist_ok=True)
    (out/"records.json").write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print("FUNDAMENTAL CANDIDATE SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__": main()
