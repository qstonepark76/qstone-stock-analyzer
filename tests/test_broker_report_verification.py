import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from scripts.verify_broker_reports import verify_candidate, normalize_rating, normalize_target, merge_ledger


class BrokerReportVerificationTests(unittest.TestCase):
    def setUp(self):
        self.krx = {"005930": "삼성전자", "000660": "sk하이닉스"}
        self.base = {
            "ticker": "005930", "company": "삼성전자", "broker": "한국투자증권",
            "published_at": "2026-11-16",
            "detail_url": "https://stock.naver.com/research/company/12345",
            "research_id": "12345", "source_opinion_type": "buy",
            "source_opinion_text": "Buy", "source_goal_price": "120,000",
        }

    def test_normalizes_explicit_buy_and_target(self):
        report, status = verify_candidate(self.base, self.krx, date(2026, 11, 17))
        self.assertEqual(status, "verified")
        self.assertEqual(report["rating"], "매수")
        self.assertEqual(report["target_price"], 120000)

    def test_rejects_ticker_company_mismatch(self):
        row = {**self.base, "company": "SK하이닉스"}
        report, status = verify_candidate(row, self.krx, date(2026, 11, 17))
        self.assertIsNone(report)
        self.assertEqual(status, "ticker_company_mismatch")

    def test_rejects_untrusted_url(self):
        row = {**self.base, "detail_url": "https://example.com/research/12345"}
        report, status = verify_candidate(row, self.krx, date(2026, 11, 17))
        self.assertIsNone(report)
        self.assertEqual(status, "untrusted_source_url")

    def test_does_not_guess_unknown_rating_or_target(self):
        row = {**self.base, "source_opinion_type": "positive-ish", "source_opinion_text": "좋아 보임", "source_goal_price": "미제시"}
        report, status = verify_candidate(row, self.krx, date(2026, 11, 17))
        self.assertIsNone(report)
        self.assertEqual(status, "no_explicit_rating_or_target")

    def test_rejects_reports_older_than_180_days(self):
        row = {**self.base, "published_at": "2026-01-01"}
        report, status = verify_candidate(row, self.krx, date(2026, 11, 17))
        self.assertIsNone(report)
        self.assertEqual(status, "invalid_metadata")

    def test_merges_without_duplicate_source_reports(self):
        report, _ = verify_candidate(self.base, self.krx, date(2026, 11, 17))
        merged = merge_ledger([report], [report])
        self.assertEqual(len(merged), 1)


if __name__ == "__main__":
    unittest.main()
