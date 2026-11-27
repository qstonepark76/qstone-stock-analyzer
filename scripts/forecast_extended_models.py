"""Candidate forecast components, exact account aliases, and partial-period models.
Alias rules are explicit, not fuzzy label matching. Specialized line items remain
predictors of the actual total (not replacements for revenue or operating profit).
"""
import math
from fundamental_candidate import IDS,number
from metric_quality import account_check
from own_forecast_v2 import candidates,finite
def canonical(account):
    # Same IFRS concept across old/new standard prefixes only; dart_ concepts
    # remain distinct. Explicit operating-profit standard equivalence not assumed.
    if isinstance(account,str) and account.startswith("ifrs-full_"):return account[10:]
    if isinstance(account,str) and account.startswith("ifrs_"):return account[5:]
    return account
def pick_exact(rows,ids,fields):
    matches=[r for r in rows if r.get("sj_div") in ("IS","CIS") and r.get("account_id") in ids and account_check([r])]
    signatures={(canonical(r["account_id"]),r["currency"],*(number(r,f) for f in fields)) for r in matches}
    return matches[0] if len(signatures)==1 else None
COMPONENTS={
    "bank_group":("dart_NetInterestIncome","ifrs-full_InterestRevenueCalculatedUsingEffectiveInterestMethod"),
    "direct_bank":("dart_NetInterestIncome","ifrs-full_InterestRevenueCalculatedUsingEffectiveInterestMethod"),
    "life_insurance":("ifrs-full_InsuranceServiceResult",),
    "nonlife_insurance":("ifrs-full_InsuranceServiceResult",),
    "securities":("ifrs-full_FeeAndCommissionIncome","dart_FeeAndCommissionIncome"),
    "card_capital":("ifrs-full_InterestRevenueCalculatedUsingEffectiveInterestMethod",),
    "operating_holding":("ifrs-full_ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod",),
    "investment_holding":("ifrs-full_ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod",),
    "reit":("ifrs-full_RevenueFromRentalIncome",),
    "infrastructure":("ifrs-full_Revenue",),
}
def component_inputs(a,q,group,currency):
    found=[]
    for ident in COMPONENTS.get(group,()):
        aa=pick_exact(a,(ident,),("thstrm_amount",));qq=pick_exact(q,(ident,),("thstrm_add_amount","frmtrm_add_amount"))
        if not account_check([aa,qq]) or aa["currency"]!=currency:continue
        v=[number(aa,"thstrm_amount"),number(qq,"thstrm_add_amount"),number(qq,"frmtrm_add_amount")]
        if not all(finite(x) for x in v):continue
        found.append({"account_id":ident,"annual":v[0],"current_ytd":v[1],"prior_ytd":v[2],"annual_receipt":aa["rcept_no"],"quarter_receipt":qq["rcept_no"],"currency":currency})
    return found
def extended_candidates(last,current,prior,quarters,asset_ratio=None,components=()):
    if not finite(last) or not finite(current) or quarters not in (2,3):return {}
    out=candidates(last,current,prior,quarters,asset_ratio) if finite(prior) else {}
    out["annualized_ytd"]=current*4/quarters
    # A bounded ensemble of distinct models (TTM == seasonal residual algebraically).
    existing=[out[k] for k in ("seasonal_residual","annualized_ytd","trend_scaled_residual") if k in out]
    if len(existing)>=2:out["equal_weight_ensemble"]=sum(existing)/len(existing)
    if finite(prior) and prior!=0:
        # Financial component trend plus seasonal residual of the remaining
        # TOTAL, not a component substituted for a total. One component at a
        # time, no overlapping sums. Gate each model separately.
        for x in components:
            a,c,p=x["annual"],x["current_ytd"],x["prior_ytd"]
            if p>0 and c>=0 and .25<=c/p<=4:
                v=c+(a-p)*c/p + ((current-c)+(last-a)-(prior-p))
                if finite(v):out["component_trend:"+x["account_id"]]=v
    return {k:v for k,v in out.items() if finite(v)}
