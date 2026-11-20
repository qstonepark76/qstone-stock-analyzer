#!/usr/bin/env python3
"""Conservative rule-based Telegram evidence extraction (shadow mode only).

This module does NOT modify the approved 100-point score. It tags messages with
candidate evidence for human/model validation and later backtesting.
"""
import json
import re
from pathlib import Path
from collections import defaultdict

DATA = Path("data")
MESSAGES = DATA / "telegram_messages.json"
LATEST = DATA / "latest.json"
OUT = DATA / "telegram_analysis.json"

AREA_RULES = {
    "financial": ["실적", "영업이익", "매출", "순이익", "마진", "수익성", "가이던스", "eps"],
    "growth": ["신규 수주", "수주", "신사업", "기술이전", "임상", "신제품", "증설", "해외 진출", "시장점유율", "성장"],
    "momentum": ["급등", "강세", "약세", "상승", "하락", "거래량", "모멘텀", "관심종목", "추천종목", "top pick"],
    "foreign_flow": ["외국인 순매수", "외국인 매수", "외국인 순매도", "외국인 매도"],
    "institution_flow": ["기관 순매수", "기관 매수", "기관 순매도", "기관 매도"],
    "valuation": ["per", "pbr", "저평가", "고평가", "밸류에이션", "목표주가", "적정주가"],
    "analyst_outlook": ["투자의견", "매수", "중립", "매도", "목표주가", "리포트", "증권사", "analyst"],
}
POSITIVE = ["매수", "비중확대", "상향", "호조", "개선", "성장", "강세", "수주", "흑자전환"]
NEGATIVE = ["매도", "비중축소", "하향", "악화", "부진", "약세", "적자", "리스크"]
TICKER_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


def read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def main():
    messages = read(MESSAGES, [])
    latest = read(LATEST, {})
    stocks = latest.get("stocks", []) if isinstance(latest, dict) else []
    by_name = {}
    for stock in stocks:
        name = str(stock.get("name", "")).strip()
        ticker = str(stock.get("ticker", "")).zfill(6)
        if name and ticker:
            by_name[name] = ticker

    output = []
    counts = defaultdict(int)
    for msg in messages:
        text = str(msg.get("text", ""))
        compact = text.lower()
        tickers = set(TICKER_RE.findall(text))
        matched_names = []
        for name, ticker in by_name.items():
            if len(name) >= 2 and name in text:
                tickers.add(ticker)
                matched_names.append(name)
        areas = [area for area, words in AREA_RULES.items()
                 if any(word.lower() in compact for word in words)]
        pos = sum(1 for word in POSITIVE if word.lower() in compact)
        neg = sum(1 for word in NEGATIVE if word.lower() in compact)
        sentiment = "positive" if pos > neg else "negative" if neg > pos else "mixed_or_neutral"
        for ticker in tickers:
            counts[ticker] += 1
        output.append({
            "message_key": msg.get("message_key"),
            "channel_username": msg.get("channel_username"),
            "channel_title": msg.get("channel_title"),
            "published_at": msg.get("published_at"),
            "permalink": msg.get("permalink"),
            "tickers": sorted(tickers),
            "matched_names": sorted(set(matched_names)),
            "candidate_areas": areas,
            "keyword_sentiment": sentiment,
            "positive_keyword_count": pos,
            "negative_keyword_count": neg,
            "evidence_text": text[:1200],
            "review_required": True,
            "score_impact": "shadow_only",
        })

    summary = {
        "mode": "shadow_only",
        "message_count": len(output),
        "ticker_mention_counts": dict(sorted(counts.items(), key=lambda x: x[1], reverse=True)),
        "messages": output,
        "notice": "규칙 기반 후보 추출 결과입니다. 사실 검증 및 백테스트 전에는 기존 100점 점수에 반영하지 않습니다.",
    }
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[TELEGRAM ANALYSIS] messages={len(output)}, tickers={len(counts)}; shadow-only")


if __name__ == "__main__":
    main()
