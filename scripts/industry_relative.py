"""Industry-relative scoring engine for the isolated v3.3 candidate model.

This module deliberately scores only independently supplied operating/cash-flow
metrics. It does not infer missing values or map broad house sectors to peers.
"""
from __future__ import annotations

import math
from typing import Any

MODEL_VERSION = "3.3-candidate"
INDUSTRY_RELATIVE_WEIGHT = 10.0
MIN_VALID_PEERS = 5

METRICS = {
    "operating_margin_pct": {"label": "영업이익률", "weight": 2.0, "higher_is_better": True},
    "roic_pct": {"label": "ROIC", "weight": 2.0, "higher_is_better": True},
    "asset_turnover": {"label": "자산회전율", "weight": 2.0, "higher_is_better": True},
    "net_debt_to_ebitda": {"label": "순차입금/EBITDA", "weight": 2.0, "higher_is_better": False},
    "cash_conversion_pct": {"label": "영업현금흐름/영업이익", "weight": 2.0, "higher_is_better": True},
}

# These fields are intentionally disjoint from the existing seven-factor
# inputs (ROE, growth, price momentum, investor flows, PER/PBR, analyst outlook).
INDUSTRY_SOURCE_FIELDS = frozenset(METRICS)
EXISTING_MODEL_SOURCE_FIELDS = frozenset({
    "roe_pct", "sales_growth_pct", "operating_profit_growth_pct",
    "momentum_5d_pct", "momentum_20d_pct", "momentum_60d_pct",
    "foreign_net_buy", "institution_net_buy", "per", "pbr",
    "analyst_target_upside_pct", "analyst_opinion_score",
})


def _valid_number(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number)


def percentile_score(value: float, peer_values: list[float], higher_is_better: bool = True) -> float:
    """Mid-rank percentile in [0, 100], including the subject in its peer set."""
    valid = sorted(float(v) for v in peer_values if _valid_number(v))
    if not _valid_number(value) or len(valid) < MIN_VALID_PEERS:
        raise ValueError("유효 peer가 5개 미만이거나 평가값이 유효하지 않습니다.")
    below = sum(v < float(value) for v in valid)
    equal = sum(v == float(value) for v in valid)
    score = 100.0 * (below + (equal + 1) / 2.0) / len(valid)
    if not higher_is_better:
        score = 100.0 - score
    return round(max(0.0, min(100.0, score)), 4)


def score_industry_relative(stocks: list[dict], ticker: str) -> dict:
    """Score one stock against exact same-industry-code peers.

    A metric is scored only if at least five peers have actual finite values.
    A provisional subtotal may be returned, but official_score is null unless
    all five metric components are present (100% coverage).
    """
    target = next((s for s in stocks if str(s.get("ticker")) == str(ticker)), None)
    if target is None:
        return {"status": "종목 데이터 없음", "official_score": None,
                "provisional_score": None, "coverage_pct": 0.0, "details": {}}

    industry_code = str(target.get("industry_code") or "").strip()
    if not industry_code or target.get("industry_confidence") not in ("high", "verified"):
        return {"status": "업종 비교 불가", "industry_code": industry_code or None,
                "official_score": None, "provisional_score": None,
                "coverage_pct": 0.0, "details": {}}

    peers = [s for s in stocks
             if str(s.get("industry_code") or "").strip() == industry_code
             and s.get("industry_confidence") in ("high", "verified")]
    if len(peers) < MIN_VALID_PEERS:
        return {"status": "비교대상 부족", "industry_code": industry_code,
                "peer_count": len(peers), "official_score": None,
                "provisional_score": None, "coverage_pct": 0.0, "details": {}}

    details = {}
    subtotal = 0.0
    covered_weight = 0.0
    for key, spec in METRICS.items():
        values = [p.get("industry_metrics", {}).get(key) for p in peers]
        valid_values = [float(v) for v in values if _valid_number(v)]
        subject_value = target.get("industry_metrics", {}).get(key)
        if len(valid_values) < MIN_VALID_PEERS or not _valid_number(subject_value):
            details[key] = {
                "label": spec["label"], "weight": spec["weight"],
                "value": subject_value if _valid_number(subject_value) else None,
                "peer_valid_count": len(valid_values), "percentile": None,
                "score": None, "status": "데이터 부족",
            }
            continue
        pct = percentile_score(float(subject_value), valid_values, spec["higher_is_better"])
        points = round(spec["weight"] * pct / 100.0, 4)
        subtotal += points
        covered_weight += spec["weight"]
        details[key] = {
            "label": spec["label"], "weight": spec["weight"],
            "value": float(subject_value), "peer_valid_count": len(valid_values),
            "percentile": pct, "score": points, "status": "산출 완료",
        }

    coverage = round(covered_weight / INDUSTRY_RELATIVE_WEIGHT * 100.0, 2)
    complete = math.isclose(covered_weight, INDUSTRY_RELATIVE_WEIGHT, abs_tol=1e-9)
    return {
        "status": "산출 완료" if complete else "지표 데이터 부족",
        "industry_code": industry_code, "peer_count": len(peers),
        "official_score": round(subtotal, 4) if complete else None,
        "provisional_score": round(subtotal, 4),
        "coverage_pct": coverage, "details": details,
    }


def validate_metric_separation(existing_fields=None) -> bool:
    """Guard against accidental reuse of an existing model input field."""
    existing = EXISTING_MODEL_SOURCE_FIELDS if existing_fields is None else set(existing_fields)
    return not (INDUSTRY_SOURCE_FIELDS & set(existing))
