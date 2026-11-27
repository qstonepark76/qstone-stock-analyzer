"""Direct borrowing reconstruction using complete reported balance-sheet lines.

Only exact recognized debt-account roles are added. Reject totals mixed with
components, unexpected debt-like rows, missing comparative amounts, and
ambiguous lease presentation. No implied zero for a missing mandatory role.
"""
import math
from collections import defaultdict

ROLES={
 "ifrs-full_ShorttermBorrowings":"short",
 "ifrs-full_CurrentLoansReceivedAndCurrentPortionOfNoncurrentLoansReceived":"current_loans_total",
 "ifrs-full_CurrentBondsIssuedAndCurrentPortionOfNoncurrentBondsIssued":"current_bonds_total",
 "ifrs-full_NoncurrentPortionOfOtherNoncurrentBorrowings":"long_other",
 "ifrs-full_CurrentPortionOfLongtermBorrowings":"current_maturity",
 "ifrs-full_CurrentPortionOfBonds":"current_bonds",
 "dart_CurrentPortionOfBonds":"current_bonds",
 "ifrs-full_NoncurrentPortionOfNoncurrentBondsIssued":"long_bonds",
 "ifrs-full_NoncurrentPortionOfNoncurrentLoansReceived":"long_loans",
 "ifrs-full_NoncurrentPortionOfNoncurrentSecuredBankLoansReceived":"long_loans",
 "ifrs-full_CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings":"current_total",
 "ifrs-full_LongtermBorrowings":"long_total",
 "ifrs-full_CurrentLeaseLiabilities":"lease_current",
 "ifrs-full_NoncurrentLeaseLiabilities":"lease_long",
}
# Exact aliases only for issuer-defined accounts without an incompatible
# standard concept. These aliases describe a specific liability, not a total.
ALIASES={"단기차입금":"short","유동성장기차입금":"current_maturity",
         "유동성사채":"current_bonds","비유동사채":"long_bonds",
         "장기차입금":"long_loans","비유동차입금":"long_loans",
         "유동리스부채":"lease_current","비유동리스부채":"lease_long"}

def norm(x):
    return "".join(str(x or "").split())

def amounts(r):
    try:
        values=tuple(float(str(r.get(k,"")).replace(",","").strip()) for k in ("thstrm_amount","frmtrm_amount"))
    except (ValueError,TypeError):
        return None
    currency=str(r.get("currency") or "").upper()
    return (*values,currency) if currency and all(math.isfinite(v) and v>=0 for v in values) else None

def debt_like(r):
    name=norm(r.get("account_nm"))
    aid=str(r.get("account_id") or "").lower()
    return any(k in name for k in ("차입금","사채","리스부채","장기부채")) or any(k in aid for k in ("borrow","bondsissued","loansreceived","leaseliabilit"))

def direct_borrowing(rows):
    grouped=defaultdict(list)
    unknown=[]
    for r in rows:
        if r.get("sj_div")!="BS" or norm(r.get("account_detail")) not in ("","-"):
            continue
        aid=str(r.get("account_id") or "")
        role=ROLES.get(aid)
        if role is None and not aid.startswith(("ifrs","dart_")):
            role=ALIASES.get(norm(r.get("account_nm")))
        if role:
            grouped[role].append(r)
        elif debt_like(r):
            unknown.append({"id":aid,"name":r.get("account_nm")})
    if unknown:
        return {"status":"unknown_debt_lines","unknown":unknown}
    chosen={}
    for role,group in grouped.items():
        values={amounts(r) for r in group}
        if None in values or len(values)!=1:
            return {"status":"ambiguous_or_missing_comparative","role":role}
        chosen[role]=group[0]
    keys=set(chosen)
    leases={"lease_current","lease_long"}
    if not leases<=keys:
        return {"status":"lease_scope_unresolved"}
    debt=keys-leases
    # Complete disjoint standard layouts. A separate current maturity may
    # cover bonds and loans, so do not add a separate current bonds row to it.
    if debt=={"current_total","long_total"}:
        layout="two_totals"
    elif debt=={"short","current_maturity","long_bonds","long_loans"}:
        layout="four_components"
    elif debt=={"short","current_maturity","long_total"}:
        layout="three_components"
    elif debt=={"current_loans_total","current_bonds_total","long_loans","long_bonds"}:
        layout="loans_bonds_by_maturity"
    elif debt=={"short","current_maturity","current_bonds","long_bonds","long_loans"}:
        # Current maturity and current bonds can overlap; require notes.
        return {"status":"current_maturity_overlap_unresolved"}
    else:
        return {"status":"incomplete_or_overlapping_layout","roles":sorted(debt)}
    selected=[chosen[k] for k in sorted(debt)]
    vals=[amounts(r) for r in selected+[chosen[k] for k in sorted(leases)]]
    if len({v[2] for v in vals})!=1:
        return {"status":"currency_conflict"}
    # No inferred debt total: both years are sums of observed balance-sheet
    # borrowing liabilities. Lease rows are separately stated, not added.
    return {"status":"auto_pass","layout":layout,"rows":selected,
            "lease_rows":[chosen[k] for k in sorted(leases)],
            "debt_current":sum(amounts(r)[0] for r in selected),
            "debt_previous":sum(amounts(r)[1] for r in selected),
            "currency":vals[0][2],"lease_basis":"lease_excluded"}
