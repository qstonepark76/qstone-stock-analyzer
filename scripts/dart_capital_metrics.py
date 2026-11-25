"""Conservative annual ROIC and net borrowing/EBITDA for v3.3.

Only unambiguous statement totals are accepted. A missing line is not zero.
Borrowing includes bonds, excluding separately disclosed lease liabilities.
The effective tax rate is observed income-tax expense / pre-tax profit.
"""
import math


def _norm(value):
    return "".join(str(value or "").split())


def _amount(row, key):
    try:
        value = float(str(row.get(key, "")).replace(",", "").strip())
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def _pick(rows, sections, names, ids=()):
    """Exact total-only matches; disagreeing duplicates are ambiguous."""
    names = {_norm(n) for n in names}
    ids = set(ids)
    for section in sections:
        matches = [r for r in rows if r.get("sj_div") == section
                   and _norm(r.get("account_detail")) in ("", "-")
                   and (_norm(r.get("account_nm")) in names or r.get("account_id") in ids)]
        if not matches:
            continue
        signatures = {(_amount(r, "thstrm_amount"), _amount(r, "frmtrm_amount"),
                       str(r.get("currency") or "").upper()) for r in matches}
        if len(signatures) != 1:
            return None
        return matches[0]
    return None


def _compatible(rows):
    currencies = [str(r.get("currency") or "").upper() for r in rows if r]
    return bool(currencies) and all(currencies) and len(set(currencies)) == 1


def _sum(rows, period):
    if any(r is None for r in rows) or not _compatible(rows):
        return None
    values = [_amount(r, period) for r in rows]
    if any(v is None or v < 0 for v in values):
        return None
    return sum(values)


def extract_capital_metrics(rows):
    bs = ("BS",)
    income = ("IS", "CIS")
    cf = ("CF",)
    cash = _pick(rows, bs, ["현금및현금성자산", "현금및현금등가물"],
                 ["ifrs-full_CashAndCashEquivalents", "ifrs_CashAndCashEquivalents"])
    equity = _pick(rows, bs, ["자본총계", "자본 합계"], ["ifrs-full_Equity", "ifrs_Equity"])
    op = _pick(rows, income, ["영업이익", "영업이익(손실)", "영업손익"],
               ["dart_OperatingIncomeLoss", "ifrs-full_ProfitLossFromOperatingActivities"])
    pretax = _pick(rows, income, ["법인세비용차감전순이익", "법인세비용차감전순이익(손실)",
                                  "법인세비용차감전계속영업이익", "법인세비용차감전계속영업이익(손실)",
                                  "법인세비용차감전이익", "법인세비용차감전이익(손실)"],
                   ["ifrs-full_ProfitLossBeforeTax", "ifrs_ProfitLossBeforeTax"])
    tax = _pick(rows, income, ["법인세비용", "법인세비용(수익)", "법인세수익(비용)",
                               "계속영업법인세비용"],
                ["ifrs-full_IncomeTaxExpenseContinuingOperations", "ifrs_IncomeTaxExpenseContinuingOperations"])

    # Prefer a clearly identified comprehensive borrowing total, otherwise
    # use comprehensive current and noncurrent totals. Separate current
    # maturities are never silently ignored or double counted.
    total = _pick(rows, bs, ["차입금및사채합계", "차입금(사채포함)합계", "총차입금(사채포함)"])
    current = _pick(rows, bs, ["유동차입금및비유동차입금(사채포함)의유동성대체부분",
                               "유동차입금및사채합계", "유동차입금(사채포함)합계"])
    long = _pick(rows, bs, ["비유동차입금(사채포함)의비유동성부분",
                            "비유동차입금(사채포함)", "비유동차입금및사채합계"])
    short = _pick(rows, bs, ["유동차입금(사채포함)"])
    maturity = _pick(rows, bs, ["비유동차입금(사채포함)의유동성대체부분"])
    debt_rows = [total] if total else ([current, long] if current else [short, maturity, long])

    # Use one explicit aggregate D&A row, or the two distinct reported
    # totals. Do not combine a subtotal with its children.
    da = _pick(rows, cf, ["감가상각비및무형자산상각비", "감가상각비와무형자산상각비"],
               ["ifrs-full_DepreciationAndAmortisationExpense"])
    dep = _pick(rows, cf, ["감가상각비", "유형자산감가상각비"],
                ["ifrs-full_DepreciationExpense"])
    amort = _pick(rows, cf, ["무형자산상각비", "무형자산감가상각비"],
                  ["ifrs-full_AmortisationExpense"])
    da_rows = [da] if da else [dep, amort]

    now, prev = "thstrm_amount", "frmtrm_amount"
    debt_now, debt_prev = _sum(debt_rows, now), _sum(debt_rows, prev)
    cash_now, cash_prev = _amount(cash or {}, now), _amount(cash or {}, prev)
    op_now = _amount(op or {}, now)
    pretax_now, tax_now = _amount(pretax or {}, now), _amount(tax or {}, now)
    eq_now, eq_prev = _amount(equity or {}, now), _amount(equity or {}, prev)
    da_now = _sum(da_rows, now)
    roic = leverage = None
    tax_rate = None
    if pretax_now is not None and pretax_now > 0 and tax_now is not None and 0 <= tax_now <= pretax_now:
        tax_rate = tax_now / pretax_now
    if (all(v is not None for v in (debt_now, debt_prev, cash_now, cash_prev,
                                     eq_now, eq_prev, op_now, tax_rate))
            and cash_now >= 0 and cash_prev >= 0
            and _compatible([*debt_rows, cash, equity, op, tax, pretax])):
        cap_now = eq_now + debt_now - cash_now
        cap_prev = eq_prev + debt_prev - cash_prev
        if cap_now > 0 and cap_prev > 0:
            roic = 100 * op_now * (1 - tax_rate) / ((cap_now + cap_prev) / 2)
    if (all(v is not None for v in (debt_now, cash_now, op_now, da_now))
            and cash_now >= 0 and op_now + da_now > 0
            and _compatible([*debt_rows, cash, op, *da_rows])):
        leverage = (debt_now - cash_now) / (op_now + da_now)
    return {
        "roic_pct": roic, "net_debt_to_ebitda": leverage,
        "capital_metric_audit": {
            "debt_current": debt_now, "debt_previous": debt_prev,
            "cash_current": cash_now, "cash_previous": cash_prev,
            "effective_tax_rate": tax_rate, "depreciation_amortisation": da_now,
            "debt_accounts": [r.get("account_nm") for r in debt_rows if r],
            "da_accounts": [r.get("account_nm") for r in da_rows if r],
            "status_roic": "산출 완료" if roic is not None else "계정 부족 또는 산식 적용 불가",
            "status_net_debt_to_ebitda": "산출 완료" if leverage is not None else "계정 부족 또는 산식 적용 불가",
        }
    }
