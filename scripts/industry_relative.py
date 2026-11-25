"""Industry-relative scoring engine for the isolated v3.3 candidate model.

This module deliberately scores only independently supplied operating/cash-flow
metrics. It does not infer missing values or map broad house sectors to peers.
"""
from __future__ import annotations

import math
from typing import Any
from financial_industry import FINANCIAL_MODELS, MODEL_LABELS, comparable_observation

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
INDUSTRY_SOURCE_FIELDS = frozenset(METRICS) | frozenset(k for m in FINANCIAL_MODELS.values() for k in m)
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
    score = 100.0 * (below + equal / 2.0) / len(valid)
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

    model = target.get("financial_model")
    if model:
        return score_financial_relative(stocks, target, model)
    industry_code = str(target.get("industry_code") or "").strip()
    if not industry_code or target.get("industry_confidence") not in ("high", "verified"):
        return {"status": "업종 비교 불가", "industry_code": industry_code or None,
                "official_score": None, "provisional_score": None,
                "coverage_pct": 0.0, "details": {}}

    peers = [s for s in stocks
             if str(s.get("industry_code") or "").strip() == industry_code
             and s.get("industry_confidence") in ("high", "verified")
             and not s.get("financial_model")]
    if len(peers) < MIN_VALID_PEERS:
        return {"status": "비교대상 부족", "industry_code": industry_code,
                "peer_count": len(peers), "official_score": None,
                "provisional_score": None, "coverage_pct": 0.0, "details": {}}

    details = {}
    subtotal = 0.0
    covered_weight = 0.0
    for key, spec in METRICS.items():
        values = [(p.get("industry_metrics") or {}).get(key) for p in peers]
        valid_values = [float(v) for v in values if _valid_number(v)]
        subject_value = (target.get("industry_metrics") or {}).get(key)
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


def score_financial_relative(stocks, target, model):
    """Compare verified, same-scope annual observations only within one model."""
    spec = FINANCIAL_MODELS.get(model)
    base = {"financial_model": model, "model_label": MODEL_LABELS.get(model, "금융업 분류 확인 필요"),
            "official_score": None, "provisional_score": None, "coverage_pct": 0.0, "details": {}}
    if spec is None or target.get("industry_confidence") not in ("high", "verified"):
        return dict(base, status="금융업 분류 확인 필요", peer_count=0)
    peers = {str(s["ticker"]): s for s in stocks if s.get("ticker")
             and s.get("financial_model") == model
             and s.get("industry_confidence") in ("high", "verified")}
    period = target.get("financial_period")
    if not period or len(peers) < MIN_VALID_PEERS:
        return dict(base, status="비교대상 부족" if len(peers) < MIN_VALID_PEERS else "기준기간 확인 필요",
                    peer_count=len(peers))
    details, subtotal, covered = {}, 0.0, 0.0
    for key, metric in spec.items():
        subject = comparable_observation(target.get("financial_observations"), key, model, period)
        observations = [comparable_observation(p.get("financial_observations"), key, model, period)
                        for p in peers.values()]
        values = [x["value"] for x in observations if subject and x and x["signature"] == subject["signature"]]
        detail = {"label": metric["label"], "weight": metric["weight"], "value": subject["value"] if subject else None,
                  "peer_valid_count": len(values), "score": None, "percentile": None,
                  "status": "데이터 또는 비교대상 부족"}
        if subject:
            detail.update(source=subject["source"], source_ref=subject["source_ref"],
                          period=period, definition_id=subject["signature"][1],
                          scope=subject["signature"][2], basis=subject["signature"][3])
        if subject and len(values) >= MIN_VALID_PEERS:
            pct = percentile_score(subject["value"], values, metric["higher_is_better"])
            points = round(metric["weight"] * pct / 100, 4)
            covered += metric["weight"]
            subtotal += points
            detail.update(score=points, percentile=pct, status="산출 완료")
        details[key] = detail
    complete = math.isclose(covered, INDUSTRY_RELATIVE_WEIGHT)
    return dict(base, status="산출 완료" if complete else "금융업 지표 데이터 부족",
                peer_count=len(peers), details=details, coverage_pct=round(100 * covered / INDUSTRY_RELATIVE_WEIGHT, 2),
                official_score=round(subtotal, 4) if complete else None,
                provisional_score=round(subtotal, 4) if covered else None)


def validate_metric_separation(existing_fields=None) -> bool:
    """Guard against accidental reuse of an existing model input field."""
    existing = EXISTING_MODEL_SOURCE_FIELDS if existing_fields is None else set(existing_fields)
    return not (INDUSTRY_SOURCE_FIELDS & set(existing))

# Candidate aggregation is independent of production v3.2.
CANDIDATE_WEIGHTS = {
    "financial": 20, "growth": 15, "momentum": 10,
    "foreign_flow": 10, "institution_flow": 10,
    "valuation": 15, "analyst_outlook": 10, "industry_relative": 10,
}


def aggregate_candidate(components, coverage, relative):
    """Normalize observed points exactly once; never grade incomplete data."""
    scores = dict(components)
    fractions = dict(coverage)
    industry_coverage = relative.get("coverage_pct", 0)
    subtotal = relative.get("official_score")
    if subtotal is None:
        subtotal = relative.get("provisional_score")
    # A partial subtotal is already expressed in earned points out of 10.
    # Divide by observed weight, not the full 10, before weighted aggregation.
    scores["industry_relative"] = (
        float(subtotal) * 1000 / industry_coverage
        if _valid_number(subtotal) and _valid_number(industry_coverage)
        and 0 < industry_coverage <= 100 else None
    )
    fractions["industry_relative"] = industry_coverage
    observed = 0.0
    earned = 0.0
    normalized_coverage = {}
    for key, weight in CANDIDATE_WEIGHTS.items():
        value, cov = scores.get(key), fractions.get(key)
        if not (_valid_number(value) and 0 <= float(value) <= 100
                and _valid_number(cov) and 0 <= float(cov) <= 100):
            scores[key], cov = None, 0.0
        cov = float(cov)
        normalized_coverage[key] = cov
        if cov > 0:
            effective = weight * cov / 100
            observed += effective
            earned += float(value) * effective / 100
    provisional = round(100 * earned / observed, 2) if observed else None
    complete = (all(c == 100 for c in normalized_coverage.values())
                and _valid_number(relative.get("official_score"))
                and provisional is not None)
    grade = None
    if complete:
        grade = ("S" if provisional >= 90 else "A" if provisional >= 80 else
                 "B" if provisional >= 70 else "C" if provisional >= 60 else "D")
    return {
        "model_version": MODEL_VERSION, "weights": dict(CANDIDATE_WEIGHTS),
        "component_scores": scores, "component_coverage_pct": normalized_coverage,
        "industry_relative": relative, "coverage_pct": round(observed, 2),
        "provisional_score": provisional, "score": provisional if complete else None,
        "grade": grade, "official_recommendation_eligible": complete,
        "status": "공식 평가 가능" if complete else (
            relative.get("status") if relative.get("status") not in (None, "산출 완료") else "데이터 부족"
        ),
    }
