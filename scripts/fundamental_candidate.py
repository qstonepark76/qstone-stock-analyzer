"""Experimental approved valuation/financial/growth redesign; no production scoring.
All amounts are taken from same annual filing, exact account IDs, same currency.
No historical values substituted for forecasts. No missing value becomes zero.
"""
import math
from collections import Counter
from metric_quality import source_check,account_check,finite

WEIGHTS={"financial":{"roe":6,"roa":4,"margin":4,"stability":3,"cash":3},
         "growth":{"sales_growth":5,"op_growth":5,"net_growth":3,"sales_cagr":2},
         "valuation":{"earnings_value":7.5,"book_value":7.5}}
IDS={
 "sales":("IS CIS","ifrs-full_Revenue","ifrs_Revenue"),
 "op":("IS CIS","dart_OperatingIncomeLoss","ifrs-full_ProfitLossFromOperatingActivities"),
 "net":("IS CIS","ifrs-full_ProfitLoss","ifrs_ProfitLoss"),
 "owner_net":("IS CIS","ifrs-full_ProfitLossAttributableToOwnersOfParent","ifrs_ProfitLossAttributableToOwnersOfParent"),
 "assets":("BS","ifrs-full_Assets","ifrs_Assets"),
 "equity":("BS","ifrs-full_Equity","ifrs_Equity"),
 "owner_equity":("BS","ifrs-full_EquityAttributableToOwnersOfParent","ifrs_EquityAttributableToOwnersOfParent"),
 "liabilities":("BS","ifrs-full_Liabilities","ifrs_Liabilities"),
 "cfo":("CF","ifrs-full_CashFlowsFromUsedInOperatingActivities","ifrs_CashFlowsFromUsedInOperatingActivities"),
}
def number(row,k):
    try:
        x=float(str(row[k]).replace(",","").strip())
        return x if math.isfinite(x) else None
    except (KeyError,TypeError,ValueError):
        return None
def select(rows,field):
    sections,*ids=IDS[field]
    found=[r for r in rows if r.get("sj_div") in sections.split() and r.get("account_id") in ids and account_check([r])]
    # Identical duplicate IS/CIS entries permitted; ambiguous values withheld.
    signatures={(r.get("currency"),number(r,"thstrm_amount"),number(r,"frmtrm_amount"),number(r,"bfefrmtrm_amount")) for r in found}
    return found[0] if len(signatures)==1 else None
def profit_change(current,previous):
    if not finite(current) or not finite(previous):
        return None
    # Bounded symmetric percentage: positive means improvement even from loss.
    denom=abs(current)+abs(previous)
    return 200*(current-previous)/denom if denom else 0.0
def transition(c,p):
    if not finite(c) or not finite(p): return None
    if p<0<c: return "loss_to_profit"
    if p>0>c: return "profit_to_loss"
    if p<0 and c<0: return "loss_narrowed" if c>p else "loss_widened" if c<p else "unchanged_loss"
    return "improved" if c>p else "worsened" if c<p else "unchanged"
def derive(rows,year,scope,cap,model=None,regulatory=None):
    if not source_check(rows,year,scope): return {}
    a={k:select(rows,k) for k in IDS}
    if scope=="OFS":
        a["owner_net"]=a["net"]
        a["owner_equity"]=a["equity"]
    receipt=str(rows[0]["rcept_no"])
    out={}
    def put(key,value,fields,basis,lower=False):
        if finite(value):
            out[key]={"value":value,"basis":basis,"scope":scope,"year":year,"receipt":receipt,
                      "account_ids":[a[k]["account_id"] for k in fields],"lower_better":lower}
    def ratio(key,n,d,average=False,lower=False,nonnegative=False):
        if not account_check([a[n],a[d]]): return
        x,y=number(a[n],"thstrm_amount"),number(a[d],"thstrm_amount")
        if x is None or y is None or y<=0 or (nonnegative and x<0): return
        if average:
            p=number(a[d],"frmtrm_amount")
            if p is None or p<=0: return
            y=(y+p)/2
        put(key,100*x/y,[n,d],key,lower)
    ratio("roe","owner_net","owner_equity",True)
    ratio("roa","net","assets",True)
    ratio("margin","op","sales")
    # Financial intermediaries never get industrial debt/equity substitutes.
    if not model or model=="operating_holding":
        ratio("debt_equity","liabilities","equity",lower=True,nonnegative=True)
        ratio("cfo_sales","cfo","sales")
    else:
        # Actual specialist inputs require separately verified scope and identity.
        # Missing regulatory observations remain missing, not a generic ratio.
        if isinstance(regulatory,dict):
            for k,v in regulatory.items():
                if isinstance(v,dict) and v.get("verified") is True and finite(v.get("value")) and v.get("source_ref") and v.get("period")==str(year)+"-12":
                    out[k]=dict(v)
        ratio("cfo_assets","cfo","assets")
    for k,field in (("sales_growth","sales"),("op_growth","op"),("net_growth","owner_net")):
        row=a[field]
        if not account_check([row]): continue
        c,p=number(row,"thstrm_amount"),number(row,"frmtrm_amount")
        if k=="sales_growth":
            if c is not None and c>=0 and p is not None and p>0: put(k,100*(c/p-1),[field],k)
        else:
            put(k,profit_change(c,p),[field],"symmetric_profit_change")
            if k in out: out[k]["transition"]=transition(c,p)
    if account_check([a["sales"]]):
        c,p=number(a["sales"],"thstrm_amount"),number(a["sales"],"bfefrmtrm_amount")
        if c is not None and c>0 and p is not None and p>0:
            put("sales_cagr",100*((c/p)**.5-1),["sales"],"three_annual_observations_two_intervals")
    if finite(cap) and cap>0:
        def market_ratio(key,field):
            row=a[field]
            if not account_check([row]) or str(row.get("currency")).upper()!="KRW":return
            v=number(row,"thstrm_amount")
            if v is not None and v>0: put(key,cap/v,[field],key,True)
        market_ratio("per","owner_net")
        market_ratio("pbr","owner_equity")
        # PSR is only a candidate for loss-making non-financial issuers.
        # NAV, FFO and EV need independent definitions and actual evidence.
        if not model or model=="operating_holding":
            market_ratio("psr","sales")
            if account_check([a["owner_net"]]):
                n=number(a["owner_net"],"thstrm_amount")
                if n is not None: out["profit_state"]="loss" if n<=0 else "profit"
    return out
def slots(metrics,model):
    stability={"bank_group":"cet1_pct","direct_bank":"cet1_pct","life_insurance":"kics_pct","nonlife_insurance":"kics_pct","securities":"ncr_pct","card_capital":"adjusted_capital_pct"}.get(model)
    industrial=not model or model=="operating_holding"
    earnings="per"
    book="pbr"
    if model=="reit": earnings,book="p_ffo","p_nav"
    elif model=="investment_holding": earnings="nav_discount_pct"
    elif industrial and metrics.get("profit_state")=="loss": earnings="ev_ebitda" if "ev_ebitda" in metrics else "psr"
    return {"financial":{"roe":"roe","roa":"roa","margin":"margin","stability":"debt_equity" if industrial else stability,"cash":"cfo_sales" if industrial else "cfo_assets"},
            "growth":{k:k for k in WEIGHTS["growth"]},
            "valuation":{"earnings_value":earnings,"book_value":book}}
