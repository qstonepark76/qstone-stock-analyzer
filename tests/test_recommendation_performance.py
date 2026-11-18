import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from recommendation_performance import build_performance_summary, update_recommendation_performance


class RecommendationPerformanceTests(unittest.TestCase):
    def test_calculates_5_20_60_session_returns_and_success_rates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prices, indexes = root / "prices", root / "indexes"
            prices.mkdir()
            indexes.mkdir()
            days = [(date(2026, 1, 1) + timedelta(days=i)).strftime("%Y%m%d") for i in range(61)]
            for i, day in enumerate(days):
                (prices / f"{day}.json").write_text(json.dumps([
                    {"ticker": "005930", "name": "삼성전자", "close": 100 + i},
                    {"ticker": "000660", "name": "SK하이닉스", "close": 200 + 2 * i},
                ]), encoding="utf-8")
                (indexes / f"{day}.json").write_text(json.dumps({"close": 1000 + 5 * i}), encoding="utf-8")
            as_of = f"{days[0][:4]}-{days[0][4:6]}-{days[0][6:]}"
            records = update_recommendation_performance(
                [], prices, indexes, as_of=as_of,
                lists={"overall": [
                    {"ticker": "005930", "name": "삼성전자", "close": 100, "score": 80},
                    {"ticker": "000660", "name": "SK하이닉스", "close": 200, "score": 75},
                ]},
            )
            result = records[0]["strategy_results"]["overall"]
            self.assertEqual(result["stock_returns"]["1w"]["005930"], 5.0)
            self.assertEqual(result["stock_returns"]["1m"]["005930"], 20.0)
            self.assertEqual(result["stock_returns"]["3m"]["005930"], 60.0)
            self.assertEqual(result["counts"]["3m"]["evaluated"], 2)
            self.assertEqual(result["success_rates"]["3m"]["absolute"], 100.0)
            summary = build_performance_summary(records, as_of=as_of)
            self.assertEqual(summary["strategies"]["overall"]["horizons"]["3m"]["evaluated_count"], 2)

    def test_unmatured_horizons_are_not_counted_as_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prices, indexes = root / "prices", root / "indexes"
            prices.mkdir()
            indexes.mkdir()
            for i in range(3):
                day = f"2026010{i+1}"
                (prices / f"{day}.json").write_text(
                    json.dumps([{"ticker": "005930", "name": "삼성전자", "close": 100 + i}]),
                    encoding="utf-8",
                )
                (indexes / f"{day}.json").write_text(json.dumps({"close": 1000 + i}), encoding="utf-8")
            records = update_recommendation_performance(
                [], prices, indexes, as_of="2026-01-01",
                lists={"overall": [{"ticker": "005930", "name": "삼성전자", "close": 100}]},
            )
            one_week = build_performance_summary(records)["strategies"]["overall"]["horizons"]["1w"]
            self.assertIsNone(one_week["average_return"])
            self.assertIsNone(one_week["absolute_success_rate"])
            self.assertEqual(one_week["evaluated_count"], 0)

    def test_missing_ticker_price_is_not_fabricated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prices, indexes = root / "prices", root / "indexes"
            prices.mkdir()
            indexes.mkdir()
            for i, day in enumerate(["20261102", "20261103", "20261104", "20261105", "20261106", "20261109"]):
                (prices / f"{day}.json").write_text(
                    json.dumps([{"ticker": "000660", "close": 200 + i}]), encoding="utf-8"
                )
                (indexes / f"{day}.json").write_text(json.dumps({"close": 2500 + i * 10}), encoding="utf-8")
            records = update_recommendation_performance(
                [{"as_of": "2026-11-02", "tickers": [{"ticker": "005930", "close": 100}]}],
                prices, indexes,
            )
            self.assertEqual(records[0]["strategy_results"]["overall"]["stock_returns"]["1w"], {})
            self.assertIsNone(records[0]["strategy_results"]["overall"]["returns"]["1w"])


if __name__ == "__main__":
    unittest.main()
