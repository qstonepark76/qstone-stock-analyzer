"""Approved roadmap priority 1: source ledger and additional own-model stress test.
No scoring mutation, no orders, no production writes. Archived data first.
"""
import json,sys,math,time
from pathlib import Path
from datetime import date,datetime,timedelta,timezone
from collections import Counter,defaultdict
from statistics import mean
from final_leading_model import finite
from outlook_candidate import broker_key,broker_evidence
from forecast_extended_models import canonical
from leading_stage6_scenarios import verify_evidence
from fundamental_candidate import number
from metric_quality import account_check
sys.path.insert(0,"audit_tools")
from forecast_batch import fit_inputs
from own_forecast import fetch,pick,DART_KEY
from own_forecast_v2 import error

KST=timezone(timedelta(hours=9))
FIELDS={"operating_profit_forecast_growth":"op_forecast_growth","earnings_forecast_revision":"earnings_revision"}
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")

def archive(ledgers,cutoff):
    groups=defaultdict(list)
    for ledger in ledgers:
        for r in ledger:
            try:
                pub=date.fromisoformat(r["published_at"])
                v=datetime.fromisoformat(r["verified_at"].replace("Z","+00:00"))
                if v.tzinfo is None or not pub<=v.astimezone(KST).date()<=cutoff:continue
            except (KeyError,ValueError,TypeError):continue
            if not r.get("verification_method") or not str(r.get("source_url","")).startswith("https://"):continue
            k=(r.get("ticker"),broker_key(r.get("broker")),r.get("published_at"),r.get("source_url"))
            if all(k):groups[k].append((v,r))
    accepted=[];conflicts=[]
    for key,rows in groups.items():
        if len({(r.get("rating"),r.get("target_price")) for _,r in rows})!=1:
            conflicts.append({"key":key,"versions":len(rows)});continue
        v,r=min(rows,key=lambda x:x[0])
        accepted.append({**r,"first_verified_at":v.isoformat(),"first_verified_kst":v.astimezone(KST).date().isoformat()})
    return accepted,conflicts

def sample_specs(payload,prior,sources):
    groups=defaultdict(list);missing=Counter()
    for row in payload["stocks"]:
        if row.get("excluded"):continue
        t=row["ticker"];src=sources[t];model=row.get("financial_model")
        if model in ("life_insurance","nonlife_insurance"):
            missing["insurance_ifrs17_regime_change"]+=1;continue
        group=model or "industrial"
        if group=="financial_unclassified":missing["unclassified_financial"]+=1;continue
        scope=src.get("scope")
        for old,field in FIELDS.items():
            d=prior[t].get("detail",{}).get(old,{})
            ev,why=verify_evidence(d,field,src,date.fromisoformat(payload["asof"]))
            if not ev:continue
            if d.get("model_version")=="v3_batch":
                vg=d.get("validation_group")
                if vg!=group+"|"+scope:missing["group_not_aligned"]+=1;continue
                method=d.get("model")
            else:method="seasonal_residual"
            if not method:continue
            groups[(group,scope,field,method)].append(t)
    # Deterministic evenly spaced issuer sample, max 24 per industrial
    # method/scope, 8 per specialist. Fix samples before examining outcomes.
    specs=[]
    for (group,scope,field,method),ts in sorted(groups.items()):
        ts=sorted(set(ts));n=min(len(ts),24 if group=="industrial" else 8)
        selected=[ts[i*len(ts)//n] for i in range(n)]
        for t in selected:specs.append({"ticker":t,"group":group,"scope":scope,"field":field,"method":method})
    return specs,dict(missing)

def assess(spec,prior,actual,q2,q3):
    k="op" if spec["field"]=="op_forecast_growth" else "net"
    group=spec["group"];scope=spec["scope"];m=spec["method"]
    key="owner_net" if k=="net" and scope=="CFS" else k
    a=pick(actual,key,("thstrm_amount",))
    if not account_check([a]):return None,"actual_account_missing"
    v=number(a,"thstrm_amount")
    if not finite(v):return None,"actual_missing"
    out={}
    for n,q in ((2,q2),(3,q3)):
        if n==2 and k=="op":continue
        f=fit_inputs(prior,q,scope,group,n).get(k,{})
        pred=f.get("models",{}).get(m);base=f.get("last")
        if not finite(pred) or not finite(base) or f.get("currency")!=a.get("currency") or canonical(f.get("account_id"))!=canonical(a.get("account_id")):return None,"comparable_forecast_missing"
        out[str(n)]={"forecast":pred,"actual":v,"naive":base,"smape":error(v,pred),"baseline_smape":error(v,base),"annual_receipt":f["annual_receipt"],"quarter_receipt":f["quarter_receipt"],"actual_receipt":a["rcept_no"]}
    return out,None

def main():
    out=Path("audit-leading-roadmap-outlook");out.mkdir(exist_ok=True)
    payload=read("stage5/observations.json")
    audit=read("replay-source/report.json")
    if audit["universe_asof"]!=payload["asof"]:raise ValueError("date mismatch")
    source={r["ticker"]:r for r in audit["records"]}
    prior={r["ticker"]:r for r in read("reuse-forecast/records.json")}
    ledgers=[read(p)["reports"] for p in ("data/analyst_reports.json","reuse-external/data/analyst_reports.json","reuse-targeted/data/analyst_reports.json")]
    inventory={}
    for cutoff in (date.fromisoformat(payload["asof"]),date(2026,11,27)):
        rows,conflicts=archive(ledgers,cutoff)
        targets={r["ticker"] for r in payload["stocks"] if not r.get("excluded")}
        rows=[r for r in rows if r["ticker"] in targets]
        stocks=[{"ticker":t} for t in sorted(targets)]
        rated=[len(broker_evidence(s,rows,cutoff)["rating"]) for s in stocks]
        info={"reports":len(rows),"issuers":len({r["ticker"] for r in rows}),"rating_issuers":sum(n>0 for n in rated),"three_broker_rating_issuers":sum(n>=3 for n in rated),"conflicts":len(conflicts),"explicit_targets":sum(finite(r.get("target_price")) for r in rows),"basis_verified_targets":sum(r.get("target_price_basis_verified") is True for r in rows)}
        inventory[cutoff.isoformat()]=info
        write(out/("reports-"+cutoff.isoformat()+".json"),rows)
        write(out/("conflicts-"+cutoff.isoformat()+".json"),conflicts)
    print("ROADMAP REPORT INVENTORY",json.dumps(inventory,ensure_ascii=False),flush=True)
    specs,excluded=sample_specs(payload,prior,source)
    write(out/"fixed_sample.json",specs)
    if not DART_KEY:raise ValueError("DART credentials unavailable")
    grouped=defaultdict(list)
    for spec in specs:grouped[spec["ticker"]].append(spec)
    results=[];failures=Counter()
    raw=out/"raw";raw.mkdir(exist_ok=True)
    for i,(t,ss) in enumerate(sorted(grouped.items()),1):
        corp=source[t]["corp_code"];scope=source[t]["scope"]
        try:
            a=fetch(corp,2021,"11011",scope,date(2022,8,31))
            q2=fetch(corp,2022,"11012",scope,date(2022,8,31))
            q3=fetch(corp,2022,"11014",scope,date(2022,11,24))
            actual=fetch(corp,2022,"11011",scope,date(2023,11,24))
            write(raw/(t+".json"),{"annual2021":a,"q2_2022":q2,"q3_2022":q3,"annual2022":actual,"scope":scope,"corp_code":corp})
            for spec in ss:
                v,why=assess(spec,a,actual,q2,q3)
                if v:results.append({**spec,"quarters":v})
                else:failures[why]+=1
        except (ValueError,TypeError,KeyError,OSError) as e:failures[type(e).__name__]+=len(ss)
        if i%10==0:print("ROADMAP STRESS PROGRESS",i,"/",len(grouped),flush=True)
    groups=defaultdict(list)
    for r in results:
        groups[(r["group"],r["scope"],r["field"],r["method"])].append(r)
    metrics=[]
    for (g,scope,field,m),rs in sorted(groups.items()):
        minimum=20 if g=="industrial" else 5
        q={}
        for n in ("2","3"):
            values=[r["quarters"][n] for r in rs if n in r["quarters"]]
            if values:q[n]={"n":len(values),"smape":mean(x["smape"] for x in values),"baseline":mean(x["baseline_smape"] for x in values)}
        pass_stress=all(v["n"]>=minimum and v["smape"]<=v["baseline"] for v in q.values()) and ("2" in q or field=="op_forecast_growth") and "3" in q
        metrics.append({"group":g,"scope":scope,"field":field,"method":m,"quarters":q,"additional_stress_pass":pass_stress,"official":False})
    s={"report_inventory":inventory,"sample_issuers":len(grouped),"sample_metric_slots":len(specs),"evaluated_metric_slots":len(results),"excluded":excluded,"failures":dict(failures),"groups":metrics,"passing_groups":sum(r["additional_stress_pass"] for r in metrics),"status":"retrospective_stress_only","note":"2022 extra retrospective period; not an independent final approval. IFRS17 insurance excluded. No changes to frozen 2026-11-24 scores."}
    write(out/"summary.json",s);write(out/"stress_results.json",results)
    print("ROADMAP STRESS SUMMARY",json.dumps(s,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
