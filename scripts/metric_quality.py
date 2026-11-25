"""Automatic admission checks for official candidate industry metrics.

No per-company manual sign-off is required for validated source rules.
A missing/ambiguous value remains unavailable. A finite but unusual value
is withheld for exception review, not clipped or replaced.
"""
import math

RULE_VERSION = "dart-auto-1"
RULES = {
    "operating_margin_pct": (-1000, 1000),
    "roic_pct": (-1000, 1000),
    "asset_turnover": (0, 100),
    "net_debt_to_ebitda": (-1000, 1000),
    "cash_conversion_pct": (-10000, 10000),
}
CAPITAL = {"roic_pct", "net_debt_to_ebitda"}

def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

def source_check(rows, year, scope):
    if not rows or not year or scope not in ("CFS", "OFS"):
        return False
    # Require a single annual filing and one declared scope.
    receipts = {str(r.get("rcept_no") or "") for r in rows}
    return (len(receipts) == 1 and "" not in receipts
            and all(r.get("fs_div") == scope and str(r.get("bsns_year")) == str(year)
                    and str(r.get("reprt_code")) == "11011" for r in rows))

def account_check(accounts):
    if not accounts or any(not isinstance(r,dict) for r in accounts):
        return False
    currencies = {str(r.get("currency") or "").upper() for r in accounts}
    return (len(currencies) == 1 and "" not in currencies
            and all(str(r.get("account_id") or "").startswith(("ifrs", "dart_"))
                    and str(r.get("account_detail") or "").strip() in ("", "-") for r in accounts))

def assess_industry_metrics(values, rows, year, scope, selected, capital_audit):
    source_ok = source_check(rows, year, scope)
    out = {}
    for key, (low, high) in RULES.items():
        value = values.get(key)
        if value is None:
            state, reason = "주의", "산출 불가 또는 계정 부족"
        elif not finite(value):
            state, reason = "오류", "유한한 숫자가 아님"
        elif not source_ok:
            state, reason = "주의", "원본 회계기간·보고서·범위 확인 필요"
        elif scope != "CFS":
            state, reason = "주의", "연결 기준 비교 불가"
        elif key in CAPITAL and capital_audit.get("lease_basis") != "lease_excluded":
            state, reason = "주의", "리스부채 또는 차입금 범위 확인 필요"
        elif key not in CAPITAL and not account_check(selected.get(key)):
            state, reason = "주의", "계정코드 또는 통화 확인 필요"
        elif not low <= value <= high:
            state, reason = "주의", "이상치 검토 필요"
        else:
            state, reason = "정상", "자동검증 통과"
        out[key] = {"state":state,"reason":reason,"rule_version":RULE_VERSION,
                    "period":str(year) if year else None,"scope":scope}
    return out

def admitted_industry_metrics(values, quality, period):
    """Use only auto-validated values matching the current annual period."""
    return {k:v if (quality.get(k,{}).get("state") == "정상"
                   and quality[k].get("rule_version") == RULE_VERSION
                   and quality[k].get("period") == str(period)
                   and quality[k].get("scope") == "CFS"
                   and finite(v)) else None for k,v in (values or {}).items()}
