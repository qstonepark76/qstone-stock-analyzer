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
            self._cell = {"text": [], "href": ""}
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
                self._cell["href"] = self._anchor_href
            self._in_anchor = False
            self._anchor_href = None
            self._anchor_text = []
        elif tag == "td" and self._cell is not None:
            text = " ".join(" ".join(self._cell["text"]).split())
            self._row.append({"text": text, "href": self._cell["href"]})
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
        match = re.search(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", date_text)
        if not (company and title and broker and href and match):
            continue
        try:
            year = int(match.group(1))\n            if year < 100:\n                year += 2000\n            published = datetime(year, int(match.group(2)), int(match.group(3))).date()
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


def discover(pages=10):
    session = requests.Session()
    session.headers.update(HEADERS)
    candidates = {}
    errors = []
    for page in range(1, pages + 1):
        try:
            response = session.get(LIST_URL, params={"page": page}, timeout=TIMEOUT)
            response.raise_for_status()
            response.encoding = response.apparent_encoding or "euc-kr"
            for row in parse_report_rows(response.text):
                candidates[row["detail_url"]] = row
            time.sleep(0.4)
        except Exception as exc:
            errors.append(f"page {page}: {str(exc)[:160]}")
            print(f"[REPORT DISCOVERY] page {page} failed: {exc}", flush=True)

    candidates = attach_tickers(list(candidates.values()), OUT / "history")
    candidates = {row["detail_url"]: row for row in candidates}
    OUT.mkdir(exist_ok=True)
    payload = {
        "schema_version": 1,
        "source": "Naver Finance Research",
        "collected_at": datetime.now().astimezone().isoformat(),
        "candidate_count": len(candidates),
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
