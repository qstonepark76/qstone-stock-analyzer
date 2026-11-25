"""Financial-sector candidate scoring definitions and fail-closed data adapter.

Financial metrics are never inferred from industrial ratios. Source mappings
must be verified before a normalized observation can enter the scoring engine.
"""
from pathlib import Path
import json
import math

def _metric(label, higher=True):
    return {"label": label, "weight": 2.0, "higher_is_better": higher}

FINANCIAL_MODELS = {
    "bank_group": {
        "nim_pct": _metric("순이자마진(NIM)"),
        "cet1_pct": _metric("보통주자본비율(CET1)"),
        "npl_pct": _metric("고정이하여신비율(NPL)", False),
        "credit_cost_pct": _metric("대손비용률(CCR)", False),
        "cir_pct": _metric("비용수익비율(CIR)", False),
    },
    "life_insurance": {
        "kics_pct": _metric("지급여력비율(K-ICS)"),
        "new_csm_margin_pct": _metric("신계약 CSM 마진율"),
        "insurance_service_margin_pct": _metric("보험서비스손익률"),
        "investment_yield_pct": _metric("운용자산이익률"),
        "impaired_asset_pct": _metric("부실자산비율", False),
    },
    "nonlife_insurance": {
        "kics_pct": _metric("지급여력비율(K-ICS)"),
        "new_csm_margin_pct": _metric("신계약 CSM 마진율"),
        "combined_ratio_pct": _metric("합산비율", False),
        "investment_yield_pct": _metric("운용자산이익률"),
        "impaired_asset_pct": _metric("부실자산비율", False),
    },
    "securities": {
        "ncr_pct": _metric("순자본비율(NCR)"),
        "regulatory_leverage_pct": _metric("감독기준 레버리지비율", False),
        "liquidity_pct": _metric("유동성비율"),
        "contingent_liability_equity_pct": _metric("우발채무/자기자본", False),
        "cir_pct": _metric("비용수익비율(CIR)", False),
    },
    "card_capital": {
        "adjusted_capital_pct": _metric("조정자기자본비율"),
        "delinquency_pct": _metric("연체율", False),
        "npl_pct": _metric("고정이하여신비율(NPL)", False),
        "credit_cost_pct": _metric("대손비용률(CCR)", False),
        "liquidity_pct": _metric("유동성비율"),
    },
}
MODEL_LABELS = {
    "bank_group": "은행 중심 금융지주", "life_insurance": "생명보험",
    "nonlife_insurance": "손해보험", "securities": "증권",
    "card_capital": "카드·캐피탈",
}
# Conservative issuer allowlist; this is not a full universe classification.
# Direct banks and holding companies must not be mixed using subsidiary ratios.
ISSUER_MODELS = {
    "105560": "bank_group", "055550": "bank_group", "086790": "bank_group",
    "316140": "bank_group", "138930": "bank_group", "139130": "bank_group",
    "175330": "bank_group",
    "032830": "life_insurance", "088350": "life_insurance",
    "082640": "life_insurance",
    "000810": "nonlife_insurance", "005830": "nonlife_insurance",
    "001450": "nonlife_insurance", "000370": "nonlife_insurance",
    "003690": "nonlife_insurance",
    "016360": "securities", "006800": "securities", "005940": "securities",
    "039490": "securities", "003540": "securities", "001510": "securities",
    "030610": "securities", "001720": "securities",
    "029780": "card_capital",
}
ALLOWED_SOURCES = {"FISIS", "OpenDART", "KOFIA", "KLIA", "KNIA", "issuer_IR"}

def financial_model_for(ticker, industry_code=None, sector=None):
    code = str(industry_code or "").strip()
    known = ISSUER_MODELS.get(str(ticker))
    if known:
        return known
    if code[:2] in ("64", "65", "66") or sector == "금융":
        return "financial_unclassified"
    return None

def load_financial_observations(path=Path("data/financial_industry_observations.json")):
    """Load normalized, independently reviewed observations; no API guesses."""
    try:
        obj = json.loads(Path(path).read_text(encoding="utf-8"))
        if obj.get("schema_version") != 1 or not isinstance(obj.get("issuers"), dict):
            return {}
        return obj["issuers"]
    except (OSError, ValueError, TypeError, AttributeError):
        return {}

def comparable_observation(record, metric, model, period):
    """Return a value and comparison signature, or null if unverified.

    Each observation must provide its exact source and metric definition.
    Only the selected annual period and percentage units are allowed.
    """
    if not isinstance(record, dict) or record.get("model") != model:
        return None
    obs = (record.get("metrics") or {}).get(metric)
    if not isinstance(obs, dict) or obs.get("verified") is not True:
        return None
    if obs.get("period") != period or obs.get("unit") != "percent":
        return None
    if obs.get("source") not in ALLOWED_SOURCES:
        return None
    required = ("source_ref", "definition_id", "scope", "basis")
    if any(not isinstance(obs.get(k), str) or not obs[k].strip() for k in required):
        return None
    # Holding-company metrics must be group-level, never subsidiary proxies.
    if model == "bank_group" and obs["scope"] != "consolidated_group":
        return None
    value = obs.get("value")
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(value):
        return None
    return {"value": value, "signature": (period, obs["definition_id"], obs["scope"], obs["basis"]),
            "source": obs["source"], "source_ref": obs["source_ref"]}
