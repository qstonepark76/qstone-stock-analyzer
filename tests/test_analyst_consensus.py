import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from analyst_consensus import load_and_score_consensus


class AnalystConsensusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ledger = Path(self.temp.name) / "analyst_reports.json"

    def tearDown(self):
        self.temp.cleanup()

    def write_reports(self, reports):
        self.ledger.write_text(
            json.dumps({"reports": reports}, ensure_ascii=False),
            encoding="utf-8",
        )

    def stock(self):
        return [{"ticker": "005930", "name": "삼성전자", "close": 100000}]

    def report(self, broker, rating="매수", target=None):
        return {
            "ticker": "005930",
            "broker": broker,
            "published_at": "2026-11-01",
            "rating": rating,
            "target_price": target,
            "source_url": f"https://example.com/{broker}",
        }

    def test_metadata_is_visible_below_three_broker_threshold(self):
        self.write_reports([self.report("증권사A"), self.report("증권사B")])
        with patch("analyst_consensus.LEDGER", self.ledger):
            stocks = self.stock()
            summaries, _ = load_and_score_consensus(stocks, date(2026, 11, 17))

        self.assertEqual(summaries["005930"]["analyst_broker_count"], 2)
        self.assertEqual(stocks[0]["analyst_report_count"], 2)
        self.assertIsNone(stocks[0]["analyst_consensus_score"])

    def test_three_brokers_allow_rating_only_consensus_with_partial_coverage(self):
        self.write_reports([
            self.report("증권사A"),
            self.report("증권사B"),
            self.report("증권사C"),
        ])
        with patch("analyst_consensus.LEDGER", self.ledger):
            stocks = self.stock()
            summaries, _ = load_and_score_consensus(stocks, date(2026, 11, 17))

        self.assertEqual(summaries["005930"]["analyst_broker_count"], 3)
        self.assertEqual(stocks[0]["analyst_consensus_coverage_pct"], 50)
        self.assertIsNotNone(stocks[0]["analyst_consensus_score"])

    def test_reports_older_than_90_days_do_not_enter_consensus(self):
        self.write_reports([
            {
                **self.report("증권사A"),
                "published_at": "2026-06-01",
            }
        ])
        with patch("analyst_consensus.LEDGER", self.ledger):
            stocks = self.stock()
            summaries, _ = load_and_score_consensus(stocks, date(2026, 11, 17))

        self.assertEqual(summaries, {})
        self.assertNotIn("analyst_report_count", stocks[0])


if __name__ == "__main__":
    unittest.main()
