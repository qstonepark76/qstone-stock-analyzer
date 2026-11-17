import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collect import update_recommendation_performance


class RecommendationPerformanceTests(unittest.TestCase):
    def test_calculates_returns_only_when_target_trading_day_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp)
            for day, close in [
                ("20261102", 100),
                ("20261103", 101),
                ("20261104", 102),
                ("20261105", 103),
                ("20261106", 104),
                ("20261109", 110),
            ]:
                (history / f"{day}.json").write_text(
                    json.dumps([{"ticker": "005930", "close": close}]),
                    encoding="utf-8",
                )
            perf = [{
                "as_of": "2026-11-02",
                "tickers": [{"ticker": "005930", "close": 100}],
                "returns": {"1w": None, "1m": None, "3m": None},
            }]
            index_history = history / "index"
            index_history.mkdir()
            update_recommendation_performance(perf, history, index_history)
            self.assertEqual(perf[0]["returns"]["1w"], 10.0)
            self.assertIsNone(perf[0]["returns"]["1m"])
            self.assertEqual(perf[0]["stock_returns"]["1w"]["005930"], 10.0)
            self.assertIsNone(perf[0]["kospi_returns"]["1w"])

    def test_calculates_kospi_benchmark_and_excess_return(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = root / "history"
            index_history = root / "index"
            history.mkdir()
            index_history.mkdir()
            dates = [
                ("20261102", 100), ("20261103", 101), ("20261104", 102),
                ("20261105", 103), ("20261106", 104), ("20261109", 110),
            ]
            for day, close in dates:
                (history / f"{day}.json").write_text(
                    json.dumps([{"ticker": "005930", "close": close}]), encoding="utf-8"
                )
            for day, close in [
                ("20261102", 2500), ("20261103", 2510), ("20261104", 2520),
                ("20261105", 2530), ("20261106", 2540), ("20261109", 2550),
            ]:
                (index_history / f"{day}.json").write_text(
                    json.dumps({"close": close}), encoding="utf-8"
                )
            perf = [{
                "as_of": "2026-11-02",
                "tickers": [{"ticker": "005930", "close": 100}],
                "returns": {},
            }]
            update_recommendation_performance(perf, history, index_history)
            self.assertEqual(perf[0]["kospi_returns"]["1w"], 2.0)
            self.assertEqual(perf[0]["excess_returns"]["1w"], 8.0)

    def test_missing_ticker_price_is_not_fabricated(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp)
            (history / "20261102.json").write_text(
                json.dumps([{"ticker": "005930", "close": 100}]), encoding="utf-8"
            )
            (history / "20261109.json").write_text(
                json.dumps([{"ticker": "000660", "close": 200}]), encoding="utf-8"
            )
            perf = [{
                "as_of": "2026-11-02",
                "tickers": [{"ticker": "005930", "close": 100}],
                "returns": {},
            }]
            update_recommendation_performance(perf, history)
            self.assertIsNone(perf[0]["returns"]["1w"])
            self.assertEqual(perf[0]["stock_returns"]["1w"], {})


if __name__ == "__main__":
    unittest.main()
