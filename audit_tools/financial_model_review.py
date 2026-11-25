"""Inventory the unclassified financial-sector issuers before new model design.
Do not classify investment holdings, REITs or funds from names alone.
Extract exact annual balance-sheet and income-statement evidence for review.
"""
import json
import sys
from collections import Counter
from pathlib import Path
sys.path.insert(0,"scripts")
from collect import pick_standard_account
from metric_quality import source_check,account_check
from financial_industry import FINANCIAL_MODELS,comparable_observation
from coverage_experiment import number

def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def annual_observations(raw,year,scope):
    if not source_check(raw,year,scope):
        return {}
    fields={}
    specs={
      "assets":(("BS",),("ifrs-full_Assets","ifrs_Assets")),
      "equity":(("BS",),("ifrs-full_Equity","ifrs_Equity")),
      "liabilities":(("BS",),("ifrs-full_Liabilities","ifrs_Liabilities")),
      "cash":(("BS",),("ifrs-full_CashAndCashEquivalents",)),
      "interest_income":(("IS","CIS"),("ifrs-full_InterestRevenueCalculatedUsingEffectiveInterestMethod",)),
      "insurance_revenue":(("IS","CIS"),("ifrs-full_InsuranceRevenue",)),
      "insurance_service_expenses":(("IS","CIS"),("ifrs-full_InsuranceServiceExpenses",)),
      "profit":(("IS","CIS"),("ifrs-full_ProfitLoss","ifrs_ProfitLoss")),
      "cfo":(("CF",),("ifrs-full_CashFlowsFromUsedInOperatingActivities",)),
      "investment_property":(("BS",),("ifrs-full_InvestmentProperty",)),
      "equity_method_investments":(("BS",),("ifrs-full_InvestmentsAccountedForUsingEquityMethod",)),
    }
    for key,(sec,ids) in specs.items():
        r=pick_standard_account(raw,sec,[],ids)
        if account_check([r]) and number(r) is not None:
            fields[key]={"current":number(r),"previous":number(r,"frmtrm_amount"),"account_id":r["account_id"],"currency":r["currency"],"scope":scope}
    # These are diagnostic financial ratios, not substitutes for regulatory
    # solvency, liquidity or any official five-slot specialist model.
    metrics={}
    def ratio(key,a,b):
        x,y=fields.get(a),fields.get(b)
        if x and y and x["currency"]==y["currency"] and y["current"]>0:
            metrics[key]=100*x["current"]/y["current"]
    ratio("accounting_equity_assets_pct","equity","assets")
    ratio("investment_property_assets_pct","investment_property","assets")
    ratio("equity_method_investments_assets_pct","equity_method_investments","assets")
    ratio("cash_assets_pct","cash","assets")
    return {"fields":fields,"diagnostic_ratios":metrics}

def main():
    records=read("audit-top300-replay/records.json")
    report=read("replay-source/report.json")
    sources={r["ticker"]:r for r in report["records"]}
    assert len(records)==len(sources)==300
    counts=Counter()
    missing=Counter()
    unclassified_codes=Counter()
    observations=Counter()
    result=[]
    for r in records:
        if r["screening_class"]!="financial":
            continue
        t=r["ticker"]
        model=r["financial_model"]
        counts[model]+=1
        src=sources[t]
        item={"ticker":t,"name":r["name"],"corp_code":r.get("corp_code"),"industry_code":r.get("industry_code"),"model":model,"source_status":src["status"],"scope":src.get("scope")}
        if model=="financial_unclassified":
            unclassified_codes[str(r.get("industry_code"))]+=1
        else:
            period=str(report["year"])+"-12"
            obs=r.get("financial_observations")
            item["missing_specialist_metrics"]=[k for k in FINANCIAL_MODELS.get(model,{}) if comparable_observation(obs,k,model,period) is None]
            missing.update(model+":"+k for k in item["missing_specialist_metrics"])
        if src["status"]=="source_received":
            raw=read("replay-source/source-rows/"+t+".json")
            receipts=sorted({str(x.get("rcept_no")) for x in raw if x.get("rcept_no")})
            if receipts==src.get("receipts"):
                item["annual_evidence"]=annual_observations(raw,report["year"],src.get("scope"))
                observations.update(model+":"+k for k in item["annual_evidence"].get("diagnostic_ratios",{}))
        result.append(item)
        if model=="financial_unclassified":
            print("FINANCIAL MODEL REVIEW",json.dumps({k:v for k,v in item.items() if k!="annual_evidence"},ensure_ascii=False),flush=True)
    summary={"universe":300,"financial_count":sum(counts.values()),"model_counts":dict(counts),"unclassified_codes":dict(unclassified_codes),"missing_specialist_metrics":dict(missing),"diagnostic_ratio_coverage":dict(observations),"release_gate":"not_verified","warning":"Industry codes and accounting ratios are review evidence, not automatic new models or regulatory metric substitutes."}
    out=Path("audit-financial-model-review")
    out.mkdir(exist_ok=True)
    (out/"records.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print("FINANCIAL MODEL REVIEW SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__":
    main()
