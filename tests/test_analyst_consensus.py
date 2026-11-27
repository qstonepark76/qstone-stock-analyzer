import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
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

        self.assertEqual(summaries["005930"]["analyst_broker_count"], 0)
        self.assertEqual(stocks[0]["analyst_report_count"], 0)
        self.assertIsNone(stocks[0]["analyst_consensus_score"])


    def test_recent_five_reports_and_three_month_trend_are_exposed(self):
        dates = [
            "2026-11-16", "2026-11-10", "2026-10-20",
            "2026-10-02", "2026-09-15", "2026-09-03",
            "2026-08-01",
        ]
        reports = []
        for index, published_at in enumerate(dates):
            reports.append({
                **self.report(f"증권사{index+1}", target=110),
                "published_at": published_at,
                "previous_target_price": 100,
                "title": f"테스트 리포트 {index+1}",
            })
        self.write_reports(reports)
        with patch("analyst_consensus.LEDGER", self.ledger):
            stocks = self.stock()
            summaries, _ = load_and_score_consensus(stocks, date(2026, 11, 17))

        summary = summaries["005930"]
        self.assertEqual(summary["analyst_report_count"], 6)
        self.assertEqual(len(summary["analyst_recent_reports"]), 5)
        self.assertEqual(summary["analyst_recent_reports"][0]["published_at"], "2026-11-16")
        self.assertEqual(summary["analyst_recent_reports"][0]["target_revision_pct"], 10.0)
        self.assertEqual(
            summary["analyst_monthly_report_counts"],
            [
                {"month": "2026-09", "count": 2},
                {"month": "2026-10", "count": 2},
                {"month": "2026-11", "count": 2},
            ],
        )
        self.assertEqual(summary["analyst_target_revision_pct"], 10.0)



    def test_candidate_single_broker_all_fields_stays_provisional(self):
        self.write_reports([{**self.report("A",target=110000),"previous_target_price":100000}])
        with patch("analyst_consensus.LEDGER",self.ledger):
            stocks=self.stock()
            load_and_score_consensus(stocks,date(2026,11,17),candidate=True)
        x=stocks[0]
        self.assertEqual(x["analyst_observed_coverage_pct"],100)
        self.assertAlmostEqual(x["analyst_consensus_coverage_pct"],100/3)
        self.assertEqual(x["analyst_confidence"],"partial")
        self.assertIsNotNone(x["analyst_consensus_score"])
    def test_candidate_three_brokers_each_field_required(self):
        self.write_reports([{**self.report(b,target=110000),"previous_target_price":100000 if b=="A" else None} for b in ("A","B","C")])
        with patch("analyst_consensus.LEDGER",self.ledger):
            stocks=self.stock()
            load_and_score_consensus(stocks,date(2026,11,17),candidate=True)
        x=stocks[0]
        self.assertAlmostEqual(x["analyst_consensus_coverage_pct"],80+20/3)
        self.assertEqual(x["analyst_revision_broker_count"],1)
    def test_candidate_full_independent_evidence(self):
        self.write_reports([{**self.report(b,target=110000),"previous_target_price":100000} for b in ("A","B","C")])
        with patch("analyst_consensus.LEDGER",self.ledger):
            stocks=self.stock()
            load_and_score_consensus(stocks,date(2026,11,17),candidate=True)
        self.assertEqual(stocks[0]["analyst_consensus_coverage_pct"],100)
        self.assertEqual(stocks[0]["analyst_confidence"],"high")


if __name__ == "__main__":
    unittest.main()
