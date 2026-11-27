"""Automatically admit exact FISIS holding-group metrics; not bank proxies."""
import json
import math
from pathlib import Path

SNAPSHOT=Path("data/fisis_holding_snapshot_202512.json")
DIRECT={
 "0012028":("105560","주식회사 케이비금융지주"),
 "0010926":("055550","주식회사 신한금융지주회사"),
 "0011573":("086790","주식회사 하나금융지주"),
 "0016619":("316140","주식회사 우리금융지주"),
 "0012710":("138930","(주)BNK금융지주"),
 "0012739":("139130","주식회사 디지비금융지주"),
 "0013406":("175330","JB금융지주"),
}
RULES={
 ("SL008","C2"):("BIS기준 자기자본비율_보통주자본 비율","값","원,%"),
 ("SL026","C"):("보통주자본 비율","비율","%"),
 ("SL009","B1"):("(고정이하여신비율)","값","원,%"),
}

def parse(raw,period):
    if not isinstance(raw,dict) or raw.get("status")!="received" or raw.get("term")!="Y":
        return None
    cid=raw.get("company")
    identity=DIRECT.get(cid)
    key=(raw.get("table"),raw.get("account"))
    rule=RULES.get(key)
    if not identity or not rule:
        return None
    ticker,name=identity
    label,column,unit=rule
    if raw.get("name")!=name or raw.get("label")!=label:
        return None
    response=raw.get("response")
    if not isinstance(response,dict) or response.get("err_cd")!="000" or str(response.get("total_count"))!="1":
        return None
    if response.get("date_of_settlement")!="12/31" or str(response.get("unit")).replace(" ","")!=unit:
        return None
    if response.get("description")!=[{"column_id":"a","column_nm":column}]:
        return None
    rows=response.get("list")
    if not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0],dict):
        return None
    row=rows[0]
    if (row.get("finance_cd")!=cid or row.get("finance_nm")!=name or row.get("base_month")!=period.replace("-","")
            or row.get("account_cd")!=key[1] or row.get("account_nm")!=label):
        return None
    try:
        v=float(str(row.get("a")))
    except (ValueError,TypeError):
        return None
    if not math.isfinite(v) or not 0<=v<=100 or (key!=("SL009","B1") and v==0):
        return None
    return ticker,key,v

def load_holding_observations(path=SNAPSHOT,period="2025-12"):
    try:
        obj=json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError,ValueError,TypeError):
        return {}
    if not isinstance(obj,dict) or obj.get("schema_version")!=1 or obj.get("period")!=period or obj.get("source")!="FISIS" or obj.get("source_run")!=45628809838 or not isinstance(obj.get("records"),list):
        return {}
    by_ticker={}
    duplicates=set()
    for raw in obj["records"]:
        parsed=parse(raw,period)
        if not parsed:
            continue
        ticker,key,v=parsed
        group=by_ticker.setdefault(ticker,{})
        if key in group:
            duplicates.add((ticker,key))
        group[key]=v
    result={}
    for ticker,group in by_ticker.items():
        metrics={}
        def add(metric,key,basis):
            metrics[metric]={"value":group[key],"period":period,"unit":"percent","source":"FISIS",
                "source_ref":"https://github.com/qstonepark76/qstone-stock-analyzer/actions/runs/45628809838",
                "definition_id":"FISIS:"+":".join(key),"scope":"consolidated_group","basis":basis,
                "verified":True,"verification_method":"automatic_rule","rule_version":"holding-auto-1"}
        k1,k2,npl=("SL008","C2"),("SL026","C"),("SL009","B1")
        if all(k in group and (ticker,k) not in duplicates for k in (k1,k2)) and abs(group[k1]-group[k2])<0.005:
            add("cet1_pct",k2,"group_regulatory_cet1_cross_table")
        if npl in group and (ticker,npl) not in duplicates:
            add("npl_pct",npl,"group_regulatory_npl")
        if metrics:
            result[ticker]={"model":"bank_group","metrics":metrics}
    return result
