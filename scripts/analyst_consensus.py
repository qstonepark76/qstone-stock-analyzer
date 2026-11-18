"""Free public brokerage research report consensus.

The ledger stores report metadata and links only; it does not mirror copyrighted PDF files.
Only verified, explicitly published values are used.
"""
import json
import datetime as dt
from pathlib import Path

LEDGER = Path("data/analyst_reports.json")
RATING = {
    "강력매수": 100, "매수": 85, "비중확대": 75,
    "중립": 50, "보유": 45, "비중축소": 25, "매도": 10,
    "not rated": None, "nr": None, "": None,
}


def _date(value):
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def _percentile(values, value):
    valid = sorted(x for x in values if x is not None)
    if value is None or not valid:
        return None
    below = sum(x < value for x in valid)
    equal = sum(x == value for x in valid)
    return 100 * (below + (equal + 1) / 2) / len(valid)


def load_and_score_consensus(stocks, asof):
    """Apply consensus metadata to stocks; score only with >=3 brokers and fresh reports."""
    try:
        payload = json.loads(LEDGER.read_text(encoding="utf-8"))
        reports = payload.get("reports", []) if isinstance(payload, dict) else []
    except Exception:
        reports = []

    universe = {s["ticker"]: s for s in stocks}
    grouped = {}
    for report in reports:
        ticker = str(report.get("ticker", "")).zfill(6)
        if ticker not in universe:
            continue
        published = _date(report.get("published_at"))
        broker = str(report.get("broker", "")).strip()
        url = str(report.get("source_url", "")).strip()
        target = report.get("target_price")
        previous = report.get("previous_target_price")
        rating = str(report.get("rating", "")).strip().lower()
        if not published or not broker or not url:
            continue
        if published > asof or (asof - published).days > 180:
            continue
        try:
            target = float(target) if target not in (None, "") else None
        except (TypeError, ValueError):
            target = None
        try:
            previous = float(previous) if previous not in (None, "") else None
        except (TypeError, ValueError):
            previous = None
        rating_score = RATING.get(rating, RATING.get(rating.upper()))
        if target is not None and target <= 0:
            target = None
        if previous is not None and previous <= 0:
            previous = None
        grouped.setdefault(ticker, []).append({
            "published": published, "broker": broker, "target": target,
            "previous": previous, "rating_score": rating_score,
            "source_url": url, "rating": str(report.get("rating", "")).strip(),
            "title": str(report.get("title", "")).strip(),
        })

    target_upside, target_revision = {}, {}
    summaries = {}
    for ticker, rows in grouped.items():
        rows.sort(key=lambda x: x["published"], reverse=True)
        # Use the newest report from each brokerage to avoid double counting.
        latest_by_broker = {}
        for row in rows:
            latest_by_broker.setdefault(row["broker"], row)
        latest = list(latest_by_broker.values())
        fresh = [r for r in latest if (asof - r["published"]).days <= 90]
        usable_targets = [r["target"] for r in fresh if r["target"] is not None]
        usable_ratings = [r["rating_score"] for r in fresh if r["rating_score"] is not None]
        revisions = [
            (r["target"] / r["previous"] - 1) * 100
            for r in fresh if r["target"] is not None and r["previous"] not in (None, 0)
        ]
        recent_rows = [r for r in rows if (asof - r["published"]).days <= 90]
        recent_rows.sort(key=lambda r: r["published"], reverse=True)
        recent_reports = [{
            "published_at": r["published"].isoformat(), "broker": r["broker"],
            "rating": r["rating"], "target_price": r["target"],
            "previous_target_price": r["previous"],
            "target_revision_pct": round((r["target"] / r["previous"] - 1) * 100, 2)
                if r["target"] is not None and r["previous"] not in (None, 0) else None,
            "title": r["title"], "source_url": r["source_url"],
        } for r in recent_rows[:5]]
        month_keys = []
        for offset in (2, 1, 0):
            year, month = asof.year, asof.month - offset
            while month <= 0:
                year -= 1
                month += 12
            month_keys.append(f"{year:04d}-{month:02d}")
        monthly_counts = {key: 0 for key in month_keys}
        for r in rows:
            key = r["published"].strftime("%Y-%m")
            if key in monthly_counts:
                monthly_counts[key] += 1
        monthly_report_counts = [{"month": key, "count": monthly_counts[key]} for key in month_keys]
        stock = universe[ticker]
        avg_target = sum(usable_targets) / len(usable_targets) if usable_targets else None
        upside = (avg_target / stock["close"] - 1) * 100 if avg_target is not None and stock.get("close") else None
        revision = sum(revisions) / len(revisions) if revisions else None
        summaries[ticker] = {
            "analyst_report_count": sum(1 for r in rows if (asof - r["published"]).days <= 90),
            "analyst_broker_count": len(fresh),
            "analyst_avg_target_price": round(avg_target, 2) if avg_target is not None else None,
            "analyst_avg_upside_pct": round(upside, 2) if upside is not None else None,
            "analyst_latest_report_date": max((r["published"] for r in fresh), default=None).isoformat() if fresh else None,
            "analyst_rating_score": sum(usable_ratings) / len(usable_ratings) if usable_ratings else None,
            "analyst_upside_pct": upside,
            "analyst_sources": sorted({r["source_url"] for r in fresh}),
            "analyst_target_revision_pct": round(revision, 2) if revision is not None else None,
            "analyst_recent_reports": recent_reports,
            "analyst_monthly_report_counts": monthly_report_counts,
            "analyst_consensus_score": None,
            "analyst_consensus_coverage_pct": 0.0,
        }
        if len(fresh) >= 3 and len({r["broker"] for r in fresh}) >= 3:
            if upside is not None:
                target_upside[ticker] = upside
            if revision is not None:
                target_revision[ticker] = revision

    # Normalize upside and revision across covered companies, while keeping the
    # rating score on a fixed 0-100 scale. All three inputs are required.
    for ticker, summary in summaries.items():
        # Always expose verified report metadata, even when the minimum
        # three-broker threshold is not met for consensus scoring.
        universe[ticker].update(summary)
        if summary["analyst_broker_count"] < 3:
            continue
        rating_score = summary["analyst_rating_score"]
        upside_score = _percentile(list(target_upside.values()), summary["analyst_upside_pct"])
        revision_score = _percentile(list(target_revision.values()), summary["analyst_target_revision_pct"])
        parts = [(rating_score, 50), (upside_score, 30), (revision_score, 20)]
        available = [(v, w) for v, w in parts if v is not None]
        coverage = sum(w for _, w in available)
        summary["analyst_consensus_coverage_pct"] = coverage
        if coverage:
            summary["analyst_consensus_score"] = round(sum(v*w for v, w in available) / coverage, 1)
        universe[ticker].update(summary)

    note = (
        f"무료 공개 증권사 리포트: 원문 링크 기반 메타데이터 {len(reports)}건 중 "
        f"분석대상 종목 {len(summaries)}개사. 최근 90일 내 3개 이상 증권사 자료를 기준으로 산출"
        if reports else
        "무료 공개 증권사 리포트 원장 비어 있음: 검증된 자료 입력 전 컨센서스 점수 미산출"
    )
    return summaries, note
