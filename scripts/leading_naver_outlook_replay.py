"""Use already collected Naver broker reports directly, with KIS gap filling.
No cross-provider agreement required; do not mix the frozen historical snapshot.
"""
import json,re
from pathlib import Path
from datetime import date,datetime
from collections import Counter,defaultdict
from leading_direct_outlook import broker_metrics
from final_leading_model import finite
from outlook_candidate import broker_key

def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
def ticker(row):
    for k in ("ISU_SRT_CD","ISU_CD","isuCd","isu_cd","ticker"):
        s=str(row.get(k) or "").strip()
        if re.fullmatch(r"KR\d{10}",s):return s[3:9]
        if re.fullmatch(r"\d{1,6}",s):return s.zfill(6)
        if re.fullmatch(r"[0-9A-Z]{6}",s):return s
    return None
def close_map(rows):
    d=defaultdict(set)
    for r in rows:
        t=ticker(r)
        try:v=float(str(r.get("TDD_CLSPRC") or r.get("tddClsprc") or r.get("close")).replace(",",""))
        except (TypeError,ValueError):continue
        if t and finite(v) and v>0:d[t].add(v)
    return {t:next(iter(v)) for t,v in d.items() if len(v)==1}
def report_rows(records,asof):
    out=defaultdict(list)
    for r in records:
        try:d=date.fromisoformat(r["published_at"])
        except (KeyError,ValueError,TypeError):continue
        if not 0<=(asof-d).days<=90 or not r.get("ticker") or not broker_key(r.get("broker")):continue
        if not str(r.get("source_url","")).startswith("https://"):continue
        out[r["ticker"]].append({"report_date":d.isoformat(),"broker":r["broker"],"opinion":r.get("rating"),"target_price_candidate":r.get("target_price"),"source_ref":r["source_url"]})
    return out
def select_slots(naver,kis,asof,close):
    # Select source per slot; no cross-source matching or double counting.
    a=broker_metrics(naver,asof,close);b=broker_metrics(kis,asof,close)
    for v in a.values():v["source"]="Naver broker reports"
    return {**b,**a}
def main():
    out=Path("audit-leading-naver-outlook");out.mkdir(exist_ok=True)
    prior=read("direct/summary.json");asof=date.fromisoformat(prior["asof"])
    records=read("direct/records.json");closes=close_map(read("direct/krx-price-source.json"))
    nav=report_rows(read("roadmap/reports-2026-11-27.json"),asof)
    kis={r["ticker"]:r.get("invest-opinion",{}).get("date_checked_candidates",[]) for r in read("kis/raw_candidates.json")}
    c=Counter();m=Counter();n=len(records)
    for row in records:
        t=row["ticker"];close=closes.get(t);row["close"]=close
        slots=select_slots(nav.get(t,[]),kis.get(t,[]),asof,close)
        if "op_forecast_growth" in row["slots"]:slots["op_forecast_growth"]=row["slots"]["op_forecast_growth"]
        row["slots"]=slots
        c["price_mapped"]+=finite(close)
        for k,v in slots.items():
            c[k]+=1;c[k+"|"+v["source"]]+=1;m[k]+=1
        if "op_forecast_growth" not in slots and row.get("own_growth_candidate"):m["op_forecast_growth"]+=1
        if row.get("own_revision_candidate"):m["earnings_revision"]+=1
    fields=("rating","upside","target_revision","op_forecast_growth","earnings_revision")
    s={"target_count":n,"asof":prior["asof"],"price_date":prior["price_date"],"counts":dict(c),"mixed_counts":{k:m[k] for k in fields},"external_candidate_coverage_pct":100*sum(c[k] for k in fields)/(5*n),"hypothetical_mixed_coverage_pct":100*sum(m[k] for k in fields)/(5*n),"prior_external_candidate_pct":prior["external_candidate_coverage_pct"],"official_new_admitted":0,"note":"Direct Naver report values preferred, KIS fallback; no independent cross-provider checks. Source timestamps preserved in original artifacts. KRX short/ISIN ticker parsing fixed. Target revision uses consecutive broker reports, not 30-day leading signal. Own-model revision still hypothetical. No historical or deployment changes."}
    write(out/"summary.json",s);write(out/"records.json",records);print("NAVER DIRECT OUTLOOK SUMMARY",json.dumps(s,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
