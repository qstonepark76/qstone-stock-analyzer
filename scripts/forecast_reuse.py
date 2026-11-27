"""Fast reuse of already tested v1 forecasts and verified issuer mappings.
Loss transitions are a deterministic transformation of saved forecast values,
not a new prediction. Shared issuer forecasts never share stock-level scores.
"""
from copy import deepcopy
from own_forecast_v2 import change
from fundamental_candidate import transition
FIELDS={"sales_forecast_growth":"sales","operating_profit_forecast_growth":"op","earnings_forecast_revision":"net"}
def extend_loss(model):
    model=deepcopy(model)
    values=model.setdefault("values",{})
    cur=model.get("raw_current",{});prev=model.get("raw_previous",{})
    for field,k in FIELDS.items():
        if field in values or k=="sales":continue
        n=cur.get(k,{});p=prev.get(k,{}) if k=="net" else n
        if not n or not p or not n.get("currency") or n.get("currency")!=p.get("currency"):continue
        if n.get("account_id")!=p.get("account_id") or not n.get("annual_receipt") or n["annual_receipt"]!=p.get("annual_receipt") or not n.get("quarter_receipt") or not p.get("quarter_receipt"):continue
        c=n.get("estimate");b=p.get("estimate") if k=="net" else n.get("prior_year_actual")
        v=change(c,b,True)
        if v is None:continue
        value,basis=v
        values[field]={"metric":field,"value":value,"change_basis":basis,"transition":transition(c,b),"current":n,"previous":p if k=="net" else None,"method":"saved_forecast_loss_aware_v3"}
    return model
def share_issuer(models,source,gaps,preferred):
    result=deepcopy(models);links={}
    for r in gaps:
        t=r.get("ticker");p=r.get("parent")
        if r.get("category")!="known_preferred_share" or preferred.get(t)!=p or t==p or t in result or p not in models:continue
        if not r.get("parent_corp") or source.get(p,{}).get("corp_code")!=r["parent_corp"]:continue
        m=deepcopy(models[p]);m["ticker"]=t;m["issuer_forecast_reference"]=p;m["issuer_corp_code"]=r["parent_corp"]
        # Nothing apart from forecast evidence is inherited.
        result[t]=m;links[t]=p
    return result,links
