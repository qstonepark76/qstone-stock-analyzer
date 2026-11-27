"""Use archived annual FISIS legal-entity ratios and broader same-sector peers.
Source values accepted directly; no cross-provider verification. Candidate-only.
"""
import json,math,re
from pathlib import Path
from collections import defaultdict,Counter
from final_leading_model import percentile,SIMPLIFIED_SPECIAL
from fisis_auto import DIRECT
from financial_industry import load_financial_observations,comparable_observation
RULES={
 ("H","SH021","A"):("life_insurance","kics_pct","지급여력비율(경과조치 적용 전)(①/②)","값",0,5000,False),
 ("I","SI021","A"):("nonlife_insurance","kics_pct","지급여력비율(경과조치 적용 전)(①/②)","값",0,5000,False),
 ("F","SF308","E"):("securities","ncr_pct","순자본비율(C/D×100)","금액",-5000,100000,False),
 ("F","SF331","C"):("securities","regulatory_leverage_pct","레버리지비율","값",0,10000,True),
 ("C","SC007","A"):("card_capital","adjusted_capital_pct","조정자기자본비율","값",-100,100,False),
 ("C","SC117","B"):("card_capital","delinquency_pct","연체채권비율(1개월 이상)","금액",0,100,True),
}
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
def norm(s):return re.sub(r"[\s()㈜]","",str(s or "").replace("주식회사","")).casefold()
def parse(r,period):
    key=(r.get("sector"),r.get("table"),r.get("account"));rule=RULES.get(key)
    if not rule or r.get("term")!="Y" or r.get("status")!="received":return None
    model,k,label,column,lo,hi,lower=rule
    p=r.get("response",{});rows=p.get("list")
    if r.get("label")!=label or p.get("err_cd")!="000" or str(p.get("total_count"))!="1" or str(p.get("unit","")).replace(" ","")!="원,%" or p.get("date_of_settlement")!="12/31" or p.get("description")!=[{"column_id":"a","column_nm":column}] or not isinstance(rows,list) or len(rows)!=1:return None
    x=rows[0];cid=r.get("company");name=r.get("name")
    if not cid or not name or "[폐]" in name or x.get("finance_cd")!=cid or x.get("finance_nm")!=name or x.get("base_month")!=period or x.get("account_cd")!=key[2] or x.get("account_nm")!=label:return None
    try:v=float(str(x["a"]).replace(",",""))
    except (ValueError,TypeError,KeyError):return None
    if not math.isfinite(v) or not lo<=v<=hi or (k=="kics_pct" and v==0):return None
    return {"model":model,"metric":k,"value":v,"company":cid,"name":name,"candidate_ticker":r.get("candidate_ticker"),"definition":":".join(key),"lower":lower,"period":period,"source_ref":"FISIS archived annual source run 45657812226"}
def main():
    out=Path("audit-leading-specialist-expanded");out.mkdir(exist_ok=True)
    p=read("cagr/observations.json");targets={r["ticker"]:r for r in p["stocks"] if not r.get("excluded") and r.get("financial_model") in SIMPLIFIED_SPECIAL}
    raw=read("expanded/records.json");groups=defaultdict(dict);conflicts=set()
    for r in raw:
        x=parse(r,"202512")
        if not x:continue
        key=(x["model"],x["metric"],x["definition"]);cid=x["company"]
        if cid in groups[key] and groups[key][cid]["value"]!=x["value"]:conflicts.add((key,cid))
        groups[key][cid]=x
    for key,cid in conflicts:groups[key].pop(cid,None)
    # Direct-entity FISIS ratios: one distinct regulated legal entity per peer.
    # Never use these peers in holding-group comparisons.
    manual=load_financial_observations(period="2025-12")
    records=[];stats=Counter();by_model=defaultdict(Counter)
    for t,r in targets.items():
        model=r["financial_model"];slots={}
        for k,w in SIMPLIFIED_SPECIAL[model].items():
            stats["expected_weight"]+=w;by_model[model]["expected_weight"]+=w
            for key,peers in groups.items():
                if key[:2]!=(model,k):continue
                matches=[]
                for x in peers.values():
                    known=DIRECT.get(x["company"])
                    if known and known[:2]==(t,model) and norm(known[2])==norm(x["name"]):matches.append(x)
                    elif x["candidate_ticker"]==t and norm(r.get("name"))==norm(x["name"]):matches.append(x)
                if len(matches)!=1:continue
                x=matches[0];q=percentile(x["value"],[z["value"] for z in peers.values()],x["lower"])
                if q is not None:slots[k]={**x,"points_candidate":round(w*q,6),"weight":w,"peer_count":len(peers),"peer_scope":"distinct regulated legal entities; not holding groups"}
            # Reuse original bank-group observations, never subsidiary values.
            if k not in slots and model=="bank_group":
                x=comparable_observation(manual.get(t),k,model,"2025-12")
                if x:
                    vals=[]
                    for rr in manual.values():
                        z=comparable_observation(rr,k,model,"2025-12")
                        if z and z["signature"]==x["signature"]:vals.append(z["value"])
                    q=percentile(x["value"],vals,k=="npl_pct")
                    if q is not None:slots[k]={**x,"points_candidate":round(w*q,6),"weight":w,"peer_count":len(vals)}
            if k in slots:stats["scored_weight"]+=w;stats["scored_slots"]+=1;by_model[model]["scored_weight"]+=w
        records.append({"ticker":t,"model":model,"slots":slots})
    s={"target_issuers":len(targets),"stats":dict(stats),"by_model":{k:dict(v) for k,v in by_model.items()},"peer_groups":{"|".join(k):len(v) for k,v in groups.items()},"specialist_coverage_pct":100*stats["scored_weight"]/stats["expected_weight"],"official_integrated":False,"note":"Annual archived FISIS direct ratios, no independent source check. Unlisted legal entities are comparison-only; no claim of consolidated-group independence. Annual investment yield, CSM and other undefined metrics remain missing."}
    write(out/"summary.json",s);write(out/"records.json",records);print("SPECIALIST EXPANDED REPLAY",json.dumps(s,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
