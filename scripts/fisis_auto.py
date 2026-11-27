"""Candidate FISIS automatic normalization for validated direct-entity rules.

Source: actual metadata and December 2025 observations in runs 45619807754
and 45623891222. No subsidiary-to-holding or annual/quarterly substitutions.
Only explicit ratio account rules are enabled; other metrics remain missing.
"""
import json
import math
from pathlib import Path

SNAPSHOT = Path("data/fisis_candidate_snapshot_202512.json")
VERSION = "fisis-auto-1"
# Exact company name and direct listed issuer. No unlisted peers admitted here.
DIRECT = {
    "0010595": ("032830","life_insurance","삼성생명보험주식회사"),
    "0010593": ("088350","life_insurance","한화생명보험주식회사"),
    "0010608": ("085620","life_insurance","미래에셋생명보험주식회사"),
    "0010636": ("005830","nonlife_insurance","DB손해보험주식회사"),
    "0010633": ("000810","nonlife_insurance","삼성화재해상보험주식회사"),
    "0010634": ("001450","nonlife_insurance","현대해상화재보험주식회사"),
    "0010627": ("000370","nonlife_insurance","한화손해보험주식회사"),
    "0010119": ("016360","securities","삼성증권(주)"),
    "0010094": ("006800","securities","미래에셋증권 주식회사"),
    "0010090": ("030610","securities","교보증권(주)"),
    "0010228": ("029780","card_capital","삼성카드㈜"),
}
# rule = (model, metric, exact label, description column, lower, upper, basis)
RULES = {
    ("SH021","A"): ("life_insurance","kics_pct","지급여력비율(경과조치 적용 전)(①/②)","값",0,5000,"before_transition"),
    ("SI021","A"): ("nonlife_insurance","kics_pct","지급여력비율(경과조치 적용 전)(①/②)","값",0,5000,"before_transition"),
    ("SH112","A"): ("life_insurance","impaired_asset_pct","가중부실자산비율","값",0,100,"weighted_impaired_assets"),
    ("SI112","A"): ("nonlife_insurance","impaired_asset_pct","가중부실자산비율","값",0,100,"weighted_impaired_assets"),
    ("SF308","E"): ("securities","ncr_pct","순자본비율(C/D×100)","금액",-5000,100000,"individual_ncr"),
    ("SF331","C"): ("securities","regulatory_leverage_pct","레버리지비율","값",0,10000,"regulatory_leverage"),
    ("SF209","C"): ("securities","liquidity_pct","유동성비율(A/B×100)","금액",0,100000,"three_month_maturity"),
    ("SC007","A"): ("card_capital","adjusted_capital_pct","조정자기자본비율","값",-100,100,"card_adjusted_capital"),
    ("SC008","D"): ("card_capital","npl_pct","고정이하여신비율","값",0,100,"card_npl"),
    ("SC010","A"): ("card_capital","liquidity_pct","원화 유동성비율","값",0,100000,"card_krw_liquidity"),
    ("SC117","B"): ("card_capital","delinquency_pct","연체채권비율(1개월 이상)","금액",0,100,"card_30day_managed_assets"),
}

def normalize_record(record, period, source_run):
    if not isinstance(record,dict) or record.get("status") != "rows_received":
        return None
    company = record.get("company")
    identity = DIRECT.get(company)
    rule = RULES.get((record.get("table"),record.get("account")))
    if not identity or not rule:
        return None
    ticker,model,name = identity
    rule_model,metric,label,col,low,high,basis = rule
    if model != rule_model or record.get("name") != name or record.get("label") != label:
        return None
    if record.get("group") != ("card_only" if model=="card_capital" else model):
        return None
    response = record.get("response")
    if not isinstance(response,dict) or response.get("err_cd") != "000" or str(response.get("total_count")) != "1":
        return None
    if str(response.get("unit","")).replace(" ","") != "원,%" or response.get("date_of_settlement") != "12/31":
        return None
    if response.get("description") != [{"column_id":"a","column_nm":col}]:
        return None
    rows = response.get("list")
    if not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0],dict):
        return None
    row = rows[0]
    if (row.get("base_month") != period.replace("-","") or row.get("finance_cd") != company
            or row.get("finance_nm") != name or row.get("account_cd") != record.get("account")
            or row.get("account_nm") != label):
        return None
    if isinstance(row.get("a"),bool):
        return None
    try:
        value=float(str(row.get("a")).replace(",",""))
    except (ValueError,TypeError):
        return None
    if not math.isfinite(value) or not low<=value<=high:
        return None
    # A zero reported K-ICS is ambiguous (observed transition-field placeholder).
    if metric=="kics_pct" and value==0:
        return None
    return ticker,model,metric,{"value":value,"period":period,"unit":"percent",
        "source":"FISIS","source_ref":f"https://github.com/qstonepark76/qstone-stock-analyzer/actions/runs/{source_run}#{company}-{record['table']}-{record['account']}",
        "definition_id":f"FISIS:{record['table']}:{record['account']}",
        "scope":"regulatory_legal_entity","basis":basis,"verified":True,
        "verification_method":"automatic_rule","rule_version":VERSION}

def load_auto_observations(path=SNAPSHOT, period="2025-12"):
    try:
        obj=json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError,ValueError,TypeError):
        return {}
    if not isinstance(obj,dict) or obj.get("schema_version")!=1 or obj.get("period")!=period or obj.get("source")!="FISIS":
        return {}
    if obj.get("source_run")!=45623891222 or not isinstance(obj.get("records"),list):
        return {}
    result={}
    rejected=set()
    for raw in obj["records"]:
        row=normalize_record(raw,period,obj["source_run"])
        if not row:
            continue
        ticker,model,metric,observation=row
        target=result.setdefault(ticker,{"model":model,"metrics":{}})
        key=(ticker,metric)
        if key in rejected:
            continue
        if metric in target["metrics"]:
            del target["metrics"][metric]
            rejected.add(key)
            continue
        target["metrics"][metric]=observation
    return result
