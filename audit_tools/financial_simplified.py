"""Simplified specialist-model candidate audit, isolated from official ranking.

Regulatory capital and asset quality are not replaced with generic leverage.
Each new accounting observation carries period, scope, receipt and exact IDs.
Proposed classifications require review of actual principal business before use.
"""
import json
import sys
from collections import Counter
from pathlib import Path
sys.path.insert(0,"scripts")
from collect import pick_standard_account
from metric_quality import source_check,account_check,finite
from financial_industry import comparable_observation,FINANCIAL_MODELS
from industry_relative import percentile_score
from coverage_experiment import number

# Fixed economic slots (2 points each). Explicit alternatives remain separate
# definitions and are never mixed in one comparison distribution.
MODELS={
 "bank_group":("roa_pct","cet1_pct","npl_pct","cir_pct","credit_cost_pct"),
 "direct_bank":("roa_pct","cet1_pct","npl_pct","cir_pct","credit_cost_pct"),
 "life_insurance":("roa_pct","kics_pct","impaired_asset_pct","insurance_service_margin_pct","investment_yield_pct"),
 "nonlife_insurance":("roa_pct","kics_pct","impaired_asset_pct","insurance_service_margin_pct","investment_yield_pct"),
 "securities":("roa_pct","ncr_pct","contingent_liability_equity_pct","cir_pct","liquidity_pct"),
 "card_capital":("roa_pct","adjusted_capital_pct","delinquency_pct","operating_expense_revenue_pct","liquidity_pct"),
 "operating_holding":("roa_pct","debt_equity_pct","asset_turnover_pct","cash_flow_margin_pct","operating_margin_pct"),
 "investment_holding":("roa_pct","nav_discount_pct","net_debt_nav_pct","cash_assets_pct","investment_income_assets_pct"),
 "reit":("ffo_assets_pct","ltv_pct","interest_coverage_pct","p_nav_discount_pct","distribution_coverage_pct"),
 "infrastructure":("cash_flow_assets_pct","debt_service_coverage_pct","ltv_pct","distribution_coverage_pct","cash_assets_pct"),
}
LOWER={"npl_pct","cir_pct","credit_cost_pct","impaired_asset_pct","contingent_liability_equity_pct","delinquency_pct","operating_expense_revenue_pct","debt_equity_pct","net_debt_nav_pct","ltv_pct"}
# Actual issuer/corp-code pairs from review run 45646466701. The three direct
# banks must not be compared with consolidated financial holding groups.
PROPOSED={
 "024110":("00149646","direct_bank"),"323410":("01133217","direct_bank"),"279570":("01203312","direct_bank"),
 "003530":("00148610","securities"),"003470":("00117601","securities"),"000400":("00113562","nonlife_insurance"),
 "402340":("01596425","investment_holding"),"0126Z0":("01965324","investment_holding"),
 "034730":("00181712","operating_holding"),"009540":("00164830","operating_holding"),
 "180640":("00983040","operating_holding"),"003550":("00120021","operating_holding"),
 "267250":("01205709","operating_holding"),"078930":("00500254","operating_holding"),
 "006260":("00105952","operating_holding"),"008930":("00161426","operating_holding"),
 "001040":("00148540","operating_holding"),"010060":("00148896","operating_holding"),
 "004990":("00120562","operating_holding"),"005440":("00105280","operating_holding"),
 "004800":("00117188","operating_holding"),"009970":("00140964","operating_holding"),
 "000240":("00160047","operating_holding"),"006040":("00118026","operating_holding"),
 "001800":("00117577","operating_holding"),"229640":("01093007","operating_holding"),
 "006120":("00131832","operating_holding"),"012630":("00164636","operating_holding"),
 "192400":("00132354","operating_holding"),"000640":("00116824","operating_holding"),
 "383800":("01562589","operating_holding"),"036530":("00225159","operating_holding"),
 "007700":("00126487","operating_holding"),"499790":("01882845","operating_holding"),
 "005810":("00155531","operating_holding"),
}
def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))
def classify(r):
    model=r["financial_model"]
    if model in MODELS:
        return model,"existing"
    candidate=PROPOSED.get(r["ticker"])
    if candidate and candidate[0]==r.get("corp_code") and r.get("industry_confidence") in ("high","verified"):
        return candidate[1],"proposed_business_review_required"
    return "unclassified","unresolved"

def accounting(raw,year,scope,model):
    if not source_check(raw,year,scope):
        return {}
    # Standalone holding accounts cannot represent operating subsidiaries.
    if model in ("operating_holding","investment_holding","bank_group") and scope!="CFS":
        return {}
    def pick(sec,*ids):
        return pick_standard_account(raw,sec,[],ids)
    inc=("IS","CIS")
    bs=("BS",)
    assets=pick(bs,"ifrs-full_Assets","ifrs_Assets")
    equity=pick(bs,"ifrs-full_Equity","ifrs_Equity")
    liabilities=pick(bs,"ifrs-full_Liabilities","ifrs_Liabilities")
    cash=pick(bs,"ifrs-full_CashAndCashEquivalents")
    profit=pick(inc,"ifrs-full_ProfitLoss","ifrs_ProfitLoss")
    sales=pick(inc,"ifrs-full_Revenue","ifrs_Revenue")
    op=pick(inc,"dart_OperatingIncomeLoss","ifrs-full_ProfitLossFromOperatingActivities")
    cfo=pick(("CF",),"ifrs-full_CashFlowsFromUsedInOperatingActivities")
    ins_rev=pick(inc,"ifrs-full_InsuranceRevenue")
    ins_result=pick(inc,"ifrs-full_InsuranceServiceResult")
    out={}
    def ratio(k,n,d,average=False,positive=False):
        if not account_check([n,d]):
            return
        x,y=number(n),number(d)
        if x is None or y is None or y<=0 or (positive and x<0):
            return
        if average:
            p=number(d,"frmtrm_amount")
            if p is None or p<=0:
                return
            y=(y+p)/2
        v=100*x/y
        if not finite(v):
            return
        out[k]={"value":v,"signature":[str(year)+"-12",k,scope,"annual_avg" if average else "annual_end_or_flow"],
                "source":"OpenDART","receipt":str(n["rcept_no"]),"account_ids":[n["account_id"],d["account_id"]]}
    ratio("roa_pct",profit,assets,True)
    if model in ("life_insurance","nonlife_insurance"):
        ratio("insurance_service_margin_pct",ins_result,ins_rev)
    if model=="operating_holding":
        ratio("debt_equity_pct",liabilities,equity,positive=True)
        ratio("asset_turnover_pct",sales,assets,True,True)
        ratio("cash_flow_margin_pct",cfo,sales)
        ratio("operating_margin_pct",op,sales)
    if model in ("investment_holding","infrastructure"):
        ratio("cash_assets_pct",cash,assets,positive=True)
    if model=="infrastructure":
        ratio("cash_flow_assets_pct",cfo,assets,True)
    return out

def main():
    rows=read("audit-top300-replay/records.json")
    report=read("replay-source/report.json")
    src={r["ticker"]:r for r in report["records"]}
    assert len(rows)==len(src)==300
    year=report["year"]
    period=str(year)+"-12"
    records=[]
    for r in rows:
        if r["screening_class"]!="financial":
            continue
        t=r["ticker"]
        model,classification=classify(r)
        s=src[t]
        observations={}
        if s["status"]=="source_received":
            raw=read("replay-source/source-rows/"+t+".json")
            if sorted({str(x["rcept_no"]) for x in raw if x.get("rcept_no")})==s.get("receipts"):
                observations=accounting(raw,year,s.get("scope"),model)
        # Retain original regulatory observations only when original model
        # and proposed model agree; no cross-entity or cross-scope proxies.
        if model==r["financial_model"]:
            for k in MODELS.get(model,()):
                obs=comparable_observation(r.get("financial_observations"),k,model,period)
                if obs:
                    observations[k]=obs
        records.append({"ticker":t,"name":r["name"],"corp_code":r["corp_code"],"model":model,"classification":classification,"metrics":{k:v for k,v in observations.items() if k in MODELS.get(model,())}})
    summary={}
    full=0
    for model in sorted({r["model"] for r in records}):
        pool=[r for r in records if r["model"]==model]
        specs=MODELS.get(model,())
        # Keep 5 missing slots for each unclassified issuer in denominator.
        slots=5*len(pool)
        count=sum(len(r["metrics"]) for r in pool)
        complete=sum(len(r["metrics"])==5 for r in pool)
        full+=complete
        compared=0
        for r in pool:
            details={}
            for k,obs in r["metrics"].items():
                values=[p["metrics"][k]["value"] for p in pool if k in p["metrics"] and tuple(p["metrics"][k]["signature"])==tuple(obs["signature"])]
                if len(values)>=5:
                    details[k]={"peer_count":len(values),"points":round(percentile_score(obs["value"],values,k not in LOWER)/50,4)}
            r["experimental_comparison"]=details
            compared+=len(details)
        summary[model]={"issuers":len(pool),"observed_slots":count,"expected_slots":slots,"observed_pct":round(100*count/slots,2),"complete_observations":complete,"comparable_slots":compared,
                        "complete_comparisons":sum(len(r["experimental_comparison"])==5 for r in pool)}
    n=len(records)
    observed=sum(x["observed_slots"] for x in summary.values())
    result={"financial_issuers":n,"observed_slots":observed,"expected_slots":5*n,"observed_pct":round(100*observed/(5*n),2),
            "fully_observed_issuers":full,"models":summary,"release_gate":"not_verified",
            "warning":"Experimental simplified model. All 62 original financial issuers remain in denominator; proposed business classifications and metric equivalence require review. No regulator ratio substitutes, no production scores."}
    out=Path("audit-financial-simplified")
    out.mkdir(exist_ok=True)
    (out/"summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"records.json").write_text(json.dumps(records,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    print("FINANCIAL SIMPLIFIED SUMMARY",json.dumps(result,ensure_ascii=False),flush=True)
if __name__=="__main__":
    main()
