"""Exact annual consolidated cash-flow D&A selector for DART XBRL facts."""
import math
import re
from decimal import Decimal, InvalidOperation

SCOPE = ("ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis","ifrs-full:ConsolidatedMember")
REPORTED = ("ifrs-full:CarryingAmountAccumulatedDepreciationAmortisationAndImpairmentAndGrossCarryingAmountAxis","dart:ReportedAmountMember")
CONCEPTS = ("AdjustmentsForDepreciationExpense","AdjustmentsForAmortisationExpense")

def select_da(facts, year, currency="KRW"):
    selected = {}
    for fact in facts:
        concept = str(fact.get("concept",""))
        match = re.fullmatch(r"\{https?://xbrl\.ifrs\.org/taxonomy/[^/]+/ifrs-full\}(.+)",concept)
        if not match or match[1] not in CONCEPTS:
            continue
        context = fact.get("context") or {}
        if context.get("start") != f"{year}-01-01" or context.get("end") != f"{year}-12-31" or context.get("instant"):
            continue
        dims = context.get("dimensions") or []
        if len(dims)!=2 or {(d.get("axis"),d.get("member")) for d in dims}!={SCOPE,REPORTED}:
            continue
        if fact.get("unit") != ["iso4217:"+currency]:
            continue
        try:
            value = Decimal(str(fact.get("value")))
        except (InvalidOperation,ValueError):
            continue
        if not value.is_finite() or value<0 or value!=value.to_integral_value():
            continue
        selected.setdefault(match[1],[]).append((value,fact))
    if any(not selected.get(c) for c in CONCEPTS):
        return {"status":"missing_exact_annual_consolidated_adjustments"}
    if any(len({x[0] for x in selected[c]})!=1 for c in CONCEPTS):
        return {"status":"conflicting_adjustment_values"}
    values={c:int(selected[c][0][0]) for c in CONCEPTS}
    return {"status":"auto_pass","depreciation":values[CONCEPTS[0]],"amortisation":values[CONCEPTS[1]],
            "total":sum(values.values()),"currency":currency,"year":year,
            "source_facts":[selected[c][0][1] for c in CONCEPTS]}
