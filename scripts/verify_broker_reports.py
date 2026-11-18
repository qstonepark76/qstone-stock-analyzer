#!/usr/bin/env python3
"""Verify public Naver research metadata and promote only explicit source values."""
import json
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

DATA = Path("data")
CANDIDATES = DATA / "analyst_report_candidates.json"
LEDGER = DATA / "analyst_reports.json"
HISTORY = DATA / "history"

RATING_MAP = {
    "strong_buy": "강력매수", "strong buy": "강력매수", "strongbuy": "강력매수",
    "buy": "매수", "매수": "매수", "outperform": "비중확대", "overweight": "비중확대",
    "비중확대": "비중확대", "hold": "중립", "neutral": "중립", "market perform": "중립",
    "중립": "중립", "보유": "보유", "underperform": "비중축소", "underweight": "비중축소",
    "비중축소": "비중축소", "sell": "매도", "매도": "매도",
}


def norm_name(value):
    name = re.sub(r"\s+", "", str(value or "")).casefold()
    name = re.sub(r"^(?:㈜|주식회사)", "", name)
    name = re.sub(r"(?:㈜|주식회사)$", "", name)
    return name


def load_latest_krx():
    snapshots = sorted(p for p in HISTORY.glob("*.json") if p.stem.isdigit())
    for path in reversed(snapshots):
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(rows, list) and rows:
                return {
                    str(row.get("ticker", "")).zfill(6): norm_name(row.get("name"))
                    for row in rows if row.get("ticker") and row.get("name")
                }
        except Exception:
            continue
    return {}


def normalize_rating(candidate):
    for key in ("source_opinion_type", "source_opinion_text"):
        raw = str(candidate.get(key) or "").strip().casefold()
        if raw in RATING_MAP:
            return RATING_MAP[raw]
    return None


def normalize_target(value):
    if value in (None, ""):
        return None
    raw = str(value).strip().replace(",", "").replace("₩", "").replace("원", "").strip()
    if not re.fullmatch(r"\d+(?:\.\d+)?", raw):
        return None
    try:
        target = float(raw)
    except ValueError:
        return None
    if target <= 0 or target > 100_000_000:
        return None
    return int(target) if target.is_integer() else target


def verify_candidate(row, krx_names, asof):
    ticker = str(row.get("ticker") or "").strip()
    company = str(row.get("company") or "").strip()
    broker = str(row.get("broker") or "").strip()
    published = str(row.get("published_at") or "")[:10]
    url = str(row.get("detail_url") or "").strip()
    try:
        pub_date = date.fromisoformat(published)
    except ValueError:
        return None, "invalid_date"
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "stock.naver.com" or not re.fullmatch(r"/research/company/\d+", parsed.path):
        return None, "untrusted_source_url"
    if not re.fullmatch(r"\d{6}", ticker) or ticker == "000000":
        return None, "invalid_ticker"
    if ticker not in krx_names or krx_names[ticker] != norm_name(company):
        return None, "ticker_company_mismatch"
    if not broker or not company or pub_date > asof or (asof - pub_date).days > 180:
        return None, "invalid_metadata"
    rating = normalize_rating(row)
    target = normalize_target(row.get("source_goal_price"))
    if rating is None and target is None:
        return None, "no_explicit_rating_or_target"

    report = {
        "ticker": ticker,
        "company": company,
        "broker": broker,
        "published_at": published,
        "rating": rating,
        "target_price": target,
        "previous_target_price": None,
        "source_url": url,
        "research_id": str(row.get("research_id") or parsed.path.rsplit("/", 1)[-1]),
        "verification_method": "Naver Stock Research API v2 explicit fields + exact KRX ticker/name match",
        "verified_at": datetime.now().astimezone().isoformat(),
    }
    return report, "verified"


def merge_ledger(existing, verified):
    """Merge unique reports and derive prior target from the same broker's older report."""
    by_key = {}
    for report in existing + verified:
        key = (report.get("ticker"), report.get("broker"), report.get("published_at"), report.get("source_url"))
        by_key[key] = report

    reports = list(by_key.values())
    grouped = {}
    for report in reports:
        grouped.setdefault((report.get("ticker"), report.get("broker")), []).append(report)

    for rows in grouped.values():
        rows.sort(key=lambda r: (r.get("published_at", ""), r.get("source_url", "")))
        prior_target = None
        prior_date = None
        for report in rows:
            current_date = str(report.get("published_at") or "")
            current_target = normalize_target(report.get("target_price"))
            # Only a strictly earlier report from the same broker can be the baseline.
            if prior_target is not None and prior_date and prior_date < current_date:
                report["previous_target_price"] = prior_target
                report["previous_target_source_date"] = prior_date
                report["previous_target_method"] = "same_broker_previous_verified_report"
            if current_target is not None:
                prior_target = current_target
                prior_date = current_date

    return sorted(reports, key=lambda r: (r.get("published_at", ""), r.get("ticker", ""), r.get("broker", "")), reverse=True)


def main():
    asof = date.today()
    if not CANDIDATES.exists():
        raise SystemExit("analyst_report_candidates.json not found")
    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8")).get("candidates", [])
    try:
        ledger_payload = json.loads(LEDGER.read_text(encoding="utf-8"))
    except Exception:
        ledger_payload = {"schema_version": 1, "reports": []}
    existing = ledger_payload.get("reports", []) if isinstance(ledger_payload, dict) else []
    krx_names = load_latest_krx()
    verified, rejected = [], {}
    for row in candidates:
        report, reason = verify_candidate(row, krx_names, asof)
        if report:
            verified.append(report)
        else:
            rejected[reason] = rejected.get(reason, 0) + 1

    merged = merge_ledger(existing, verified)
    LEDGER.write_text(json.dumps({
        "schema_version": 2,
        "description": "무료 공개 증권사 리포트 중 원문 API 명시 필드와 KRX 종목코드·회사명 일치가 확인된 메타데이터만 저장합니다.",
        "verified_count_this_run": len(verified),
        "reports": merged,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    candidate_payload = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    candidate_payload["verified_for_scoring"] = len(verified)
    candidate_payload["verification_summary"] = {
        "verified": len(verified), "rejected": rejected,
        "method": "explicit Naver opinion/target fields + exact KRX ticker/name match",
    }
    for row in candidate_payload.get("candidates", []):
        report, reason = verify_candidate(row, krx_names, asof)
        row["verification_status"] = "verified" if report else reason
        if report:
            row["rating"] = report["rating"]
            row["target_price"] = report["target_price"]
    CANDIDATES.write_text(json.dumps(candidate_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[REPORT VERIFY] 후보 {len(candidates)}건 / 이번 회차 검증 {len(verified)}건 / 원장 누적 {len(merged)}건")
    print(f"[REPORT VERIFY] 제외 사유: {json.dumps(rejected, ensure_ascii=False, sort_keys=True)}")


if __name__ == "__main__":
    main()
