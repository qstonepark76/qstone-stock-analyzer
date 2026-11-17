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
            update_recommendation_performance(perf, history)
            self.assertEqual(perf[0]["returns"]["1w"], 10.0)
            self.assertIsNone(perf[0]["returns"]["1m"])
            self.assertEqual(perf[0]["stock_returns"]["1w"]["005930"], 10.0)
            self.assertIsNone(perf[0]["kospi_returns"]["1w"])

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
