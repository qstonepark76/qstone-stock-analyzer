#!/usr/bin/env python3
"""Discover public Naver Finance company research metadata.

This collector stores discovery candidates only. It does not download PDFs,
infer ratings/target prices, or promote candidates into the scored report ledger.
"""
import json
import re
import time
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import requests

BASE = "https://finance.naver.com"
LIST_URL = BASE + "/research/company_list.naver"
OUT = Path("data")
OUTPUT = OUT / "analyst_report_candidates.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; QStoneParkResearchBot/1.0)"}
TIMEOUT = (5, 15)


class ResearchTableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self._row = None
        self._cell = None
        self._anchor_href = None
        self._anchor_text = []
        self._in_anchor = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr":
            self._row = []
        elif tag == "td" and self._row is not None:
            self._cell = {"text": [], "href": "", "hrefs": []}
        elif tag == "a" and self._cell is not None:
            self._in_anchor = True
            self._anchor_href = attrs.get("href", "")
            self._anchor_text = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell["text"].append(data)
        if self._in_anchor:
            self._anchor_text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._in_anchor:
            if self._cell is not None and self._anchor_href:
                self._cell["hrefs"].append(self._anchor_href)
                # Prefer a report-detail URL over image, PDF, or auxiliary links.
                if ("company_read" in self._anchor_href or "nid=" in self._anchor_href) and not self._cell["href"]:
                    self._cell["href"] = self._anchor_href
            self._in_anchor = False
            self._anchor_href = None
            self._anchor_text = []
        elif tag == "td" and self._cell is not None:
            text = " ".join(" ".join(self._cell["text"]).split())
            href = self._cell["href"] or next(
                (item for item in self._cell["hrefs"] if "file.naver" not in item and not item.lower().endswith((".png", ".jpg", ".gif"))),
                ""
            )
            self._row.append({"text": text, "href": href})
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def parse_report_rows(html, asof=None):
    """Parse Naver company research rows into unscored discovery candidates."""
    parser = ResearchTableParser()
    parser.feed(html)
    asof = asof or datetime.now().date()
    found = []
    for cells in parser.rows:
        if len(cells) < 5:
            continue
        # Naver company research table: company, title, broker, attachment, date, views.
        company, title, broker = cells[0]["text"], cells[1]["text"], cells[2]["text"]
        date_text = cells[4]["text"]
        href = cells[1]["href"]
        match = re.search(r"(20\d{2}|\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", date_text)
        if not (company and title and broker and href and match):
            continue
        try:
            year = int(match.group(1))
            if year < 100:
                year += 2000
            published = datetime(year, int(match.group(2)), int(match.group(3))).date()
        except ValueError:
            continue
        if published > asof:
            continue
        found.append({
            "company": company,
            "title": title,
            "broker": broker,
            "published_at": published.isoformat(),
            "discovery_source": "Naver Finance Research",
            "detail_url": urljoin(BASE, href),
            "verification_status": "candidate_unverified",
            "rating": None,
            "target_price": None,
            "ticker": None,
        })
    return found


def attach_tickers(candidates, history_dir):
    """Attach ticker only when a candidate company name matches one unique KRX name."""
    snapshots = sorted(Path(history_dir).glob("*.json"))
    if not snapshots:
        return candidates
    try:
        rows = json.loads(snapshots[-1].read_text(encoding="utf-8"))
    except Exception:
        return candidates
    names = {}
    for stock in rows if isinstance(rows, list) else []:
        name = re.sub(r"\s+", "", str(stock.get("name", ""))).casefold()
        ticker = str(stock.get("ticker", "")).zfill(6)
        if name and ticker:
            names.setdefault(name, set()).add(ticker)
    for candidate in candidates:
        key = re.sub(r"\s+", "", str(candidate.get("company", ""))).casefold()
        matches = names.get(key, set())
        if len(matches) == 1:
            candidate["ticker"] = next(iter(matches))
            candidate["verification_status"] = "ticker_matched_unverified"
    return candidates


def _pick(item, *keys):
    """Pick the first non-empty value from a Naver API item or nested object."""
    if not isinstance(item, dict):
        return None
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    for value in item.values():
        if isinstance(value, dict):
            found = _pick(value, *keys)
            if found not in (None, ""):
                return found
    return None


def _api_date(value, asof):
    if value in (None, ""):
        return None
    text = str(value).strip()
    # Naver v2 commonly returns ISO dates; also accept compact and dotted forms.
    match = re.search(r"(20\\d{2}|\\d{2})[-./]?(\\d{1,2})[-./]?(\\d{1,2})", text)
    if not match:
        return None
    year = int(match.group(1))
    if year < 100:
        year += 2000
    try:
        parsed = datetime(year, int(match.group(2)), int(match.group(3))).date()
    except ValueError:
        return None
    return parsed if parsed <= asof else None


def parse_api_items(payload, asof=None):
    """Normalize public Naver Stock Research v2 company-list items."""
    asof = asof or datetime.now().date()
    items = payload.get("items", []) if isinstance(payload, dict) else []
    found = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        nid = _pick(item, "nid", "researchId", "id")
        company = _pick(item, "itemName", "stockName", "companyName", "company", "name")
        title = _pick(item, "title", "researchTitle", "reportTitle")
        broker = _pick(item, "brokerName", "broker", "securitiesName", "writerName")
        date_value = _pick(item, "publishedAt", "publishDate", "regDate", "date", "createdAt", "writeDate")
        published = _api_date(date_value, asof)
        if not (nid and company and title and broker and published):
            continue
        item_code = _pick(item, "itemCode", "stockCode", "code")
        detail_url = f"https://stock.naver.com/research/company/{nid}"
        found.append({
            "company": str(company).strip(),
            "title": str(title).strip(),
            "broker": str(broker).strip(),
            "published_at": published.isoformat(),
            "discovery_source": "Naver Stock Research API v2",
            "detail_url": detail_url,
            "research_id": str(nid),
            "ticker": str(item_code).zfill(6) if item_code else None,
            "verification_status": "candidate_unverified",
            "rating": None,
            "target_price": None,
        })
    return found


def discover(pages=10):
    """Discover public reports through the current Naver Stock Research v2 API."""
    session = requests.Session()
    session.headers.update({
        **HEADERS,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://stock.naver.com/research/company",
    })
    candidates = {}
    errors = []
    total_count = None
    page_size = int(__import__("os").getenv("REPORT_DISCOVERY_PAGE_SIZE", "50"))
    base_url = "https://stock.naver.com/api/stockSecurity/researches/v2/company"

    for page in range(pages):
        try:
            response = session.get(
                base_url,
                params={"index": page, "size": page_size},
                timeout=TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
            page_rows = parse_api_items(payload)
            for row in page_rows:
                candidates[row["detail_url"]] = row
            if isinstance(payload, dict):
                total_count = payload.get("totalCount", total_count)
                has_next = payload.get("hasNext")
                items = payload.get("items")
                if page == 0:
                    sample_keys = sorted(items[0].keys()) if isinstance(items, list) and items and isinstance(items[0], dict) else []
                    print(
                        f"[REPORT DISCOVERY] v2 응답 totalCount={total_count}, "
                        f"hasNext={has_next}, 첫 항목 필드={sample_keys[:30]}",
                        flush=True,
                    )
                if has_next is False or (isinstance(items, list) and not items):
                    break
            else:
                raise ValueError("Naver research API 응답이 JSON 객체가 아닙니다.")
            print(
                f"[REPORT DISCOVERY] v2 page {page + 1}: 원본 {len(payload.get('items', []))}건 / "
                f"정규화 후보 {len(page_rows)}건 / 누적 {len(candidates)}건",
                flush=True,
            )
            time.sleep(0.25)
        except Exception as exc:
            errors.append(f"v2 page {page}: {str(exc)[:180]}")
            print(f"[REPORT DISCOVERY] v2 page {page + 1} failed: {exc}", flush=True)
            break

    # Keep the KRX exact-name match as an independent verification step.
    candidates = attach_tickers(list(candidates.values()), OUT / "history")
    candidates = {row["detail_url"]: row for row in candidates}
    OUT.mkdir(exist_ok=True)
    payload = {
        "schema_version": 2,
        "source": "Naver Stock Research API v2",
        "collected_at": datetime.now().astimezone().isoformat(),
        "candidate_count": len(candidates),
        "source_total_count": total_count,
        "verified_for_scoring": 0,
        "errors": errors,
        "candidates": sorted(candidates.values(), key=lambda x: (x["published_at"], x["broker"]), reverse=True),
        "notice": "발견 후보일 뿐입니다. 투자의견·목표주가·종목코드를 검증하기 전에는 컨센서스 점수에 반영하지 않습니다.",
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[REPORT DISCOVERY] 후보 {len(candidates)}건 저장, 검증·점수 반영 0건", flush=True)
    return payload


if __name__ == "__main__":
    discover(int(__import__("os").getenv("REPORT_DISCOVERY_PAGES", "10")) )
