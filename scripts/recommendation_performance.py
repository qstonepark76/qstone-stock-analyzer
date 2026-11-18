"""Immutable recommendation snapshots and realized forward-performance tracking."""
import json
from pathlib import Path

HORIZONS = {"1w": 5, "1m": 20, "3m": 60}
STRATEGY_LABELS = {
    "overall": "종합 TOP 15",
    "financial": "재무",
    "growth": "성장",
    "undervalued": "저평가",
    "momentum": "모멘텀",
    "foreign_flow": "외국인 수급",
    "institution_flow": "기관 수급",
}


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def _stock_snapshot(items, strategy_key="overall"):
    output = []
    seen = set()
    for item in items or []:
        ticker = str(item.get("ticker", "")).zfill(6)
        close = item.get("close")
        if not ticker or ticker == "000000" or close in (None, 0) or ticker in seen:
            continue
        seen.add(ticker)
        output.append({
            "ticker": ticker,
            "name": item.get("name", ticker),
            "close": float(close),
            "score": item.get("list_score") if item.get("list_score") is not None else (
                item.get("financial_score") if strategy_key == "financial" else
                item.get("growth_score") if strategy_key == "growth" else
                (item.get("component_scores") or {}).get("valuation") if strategy_key == "undervalued" else
                item.get("momentum_score") if strategy_key == "momentum" else
                item.get("foreign_flow_score") if strategy_key == "foreign_flow" else
                item.get("institution_flow_score") if strategy_key == "institution_flow" else
                item.get("score")
            ),
            "sector": item.get("sector"),
        })
    return output


def update_recommendation_performance(history, price_history_dir, index_history_dir, as_of=None, lists=None):
    """Add an immutable daily strategy snapshot and calculate realized 5/20/60-session returns."""
    price_history_dir = Path(price_history_dir)
    index_history_dir = Path(index_history_dir)
    records = history if isinstance(history, list) else []

    # Add or enrich only the current date. Existing historical snapshots are never rewritten
    # with today's recommendation universe or prices.
    if as_of:
        day = str(as_of)
        record = next((x for x in records if x.get("as_of") == day), None)
        if record is None:
            record = {"as_of": day, "tickers": [], "strategies": {}}
            records.append(record)
        strategies = record.setdefault("strategies", {})
        for key, items in (lists or {}).items():
            if key in STRATEGY_LABELS and (key not in strategies or not strategies[key]):
                strategies[key] = _stock_snapshot(items, key)
        if not record.get("tickers") and strategies.get("overall"):
            record["tickers"] = strategies["overall"]

    price_snapshots = {}
    for path in sorted(price_history_dir.glob("*.json")):
        if not path.stem.isdigit():
            continue
        rows = _read_json(path, [])
        if isinstance(rows, list) and rows:
            price_snapshots[path.stem] = {
                str(row.get("ticker", "")).zfill(6): float(row["close"])
                for row in rows if row.get("ticker") and row.get("close") not in (None, 0)
            }
    dates = sorted(price_snapshots)
    date_index = {day: i for i, day in enumerate(dates)}

    index_snapshots = {}
    for path in sorted(index_history_dir.glob("*.json")):
        if not path.stem.isdigit():
            continue
        item = _read_json(path, {})
        if item.get("close") not in (None, 0):
            index_snapshots[path.stem] = float(item["close"])

    for record in records:
        start_day = str(record.get("as_of", "")).replace("-", "")
        if start_day not in date_index:
            continue
        start_index = date_index[start_day]
        strategies = record.get("strategies") or {}
        # Backward compatibility: old records contained only the overall list.
        if not strategies and record.get("tickers"):
            strategies = {"overall": record["tickers"]}
            record["strategies"] = strategies
        results = record.setdefault("strategy_results", {})
        for key, stocks in strategies.items():
            if key not in STRATEGY_LABELS:
                continue
            stock_returns, averages, benchmarks, excess = {}, {}, {}, {}
            success_rates, counts = {}, {}
            for label, offset in HORIZONS.items():
                target_index = start_index + offset
                if target_index >= len(dates):
                    stock_returns[label] = {}
                    averages[label] = benchmarks[label] = excess[label] = None
                    success_rates[label] = {"absolute": None, "outperform": None}
                    counts[label] = {"evaluated": 0, "positive": 0, "outperform": 0}
                    continue
                target_day = dates[target_index]
                target_prices = price_snapshots[target_day]
                values = {}
                for stock in stocks:
                    ticker = str(stock.get("ticker", "")).zfill(6)
                    initial = stock.get("close")
                    later = target_prices.get(ticker)
                    if initial not in (None, 0) and later is not None:
                        values[ticker] = round((later / float(initial) - 1) * 100, 2)
                stock_returns[label] = values
                averages[label] = round(sum(values.values()) / len(values), 2) if values else None
                base_index = index_snapshots.get(start_day)
                later_index = index_snapshots.get(target_day)
                benchmark = round((later_index / base_index - 1) * 100, 2) if base_index and later_index else None
                benchmarks[label] = benchmark
                excess[label] = round(averages[label] - benchmark, 2) if averages[label] is not None and benchmark is not None else None
                positive = sum(1 for value in values.values() if value > 0)
                outperform = sum(1 for value in values.values() if benchmark is not None and value > benchmark)
                counts[label] = {"evaluated": len(values), "positive": positive, "outperform": outperform, "benchmark_evaluated": len(values) if benchmark is not None else 0}
                success_rates[label] = {
                    "absolute": round(100 * positive / len(values), 1) if values else None,
                    "outperform": round(100 * outperform / len(values), 1) if values and benchmark is not None else None,
                }
            results[key] = {
                "returns": averages,
                "kospi_returns": benchmarks,
                "excess_returns": excess,
                "success_rates": success_rates,
                "counts": counts,
                "stock_returns": stock_returns,
            }

        overall = results.get("overall")
        if overall:
            record["returns"] = overall["returns"]
            record["kospi_returns"] = overall["kospi_returns"]
            record["excess_returns"] = overall["excess_returns"]
            record["stock_returns"] = overall["stock_returns"]

    return records[-500:]


def build_performance_summary(history, as_of=None):
    """Aggregate realized recommendation observations without counting immature horizons."""
    summary = {
        "as_of": as_of,
        "methodology": {
            "recommendation_price": "추천일 종가",
            "horizons": {"1w": 5, "1m": 20, "3m": 60},
            "benchmark": "추천일과 평가일의 KOSPI 종가 수익률",
            "absolute_success": "종목 수익률 > 0%",
            "outperform_success": "종목 수익률 > 동일 기간 KOSPI 수익률",
            "averaging": "평가 완료된 추천 종목 관측치의 단순 평균",
        },
        "strategy_labels": STRATEGY_LABELS,
        "strategies": {},
        "snapshot_count": len(history),
    }
    for key, label in STRATEGY_LABELS.items():
        horizons = {}
        for horizon in HORIZONS:
            returns, benchmarks, excess = [], [], []
            evaluated = positive = outperform = benchmark_evaluated = 0
            completed_days = 0
            for record in history:
                result = (record.get("strategy_results") or {}).get(key)
                if not result:
                    continue
                value = result.get("returns", {}).get(horizon)
                if value is None:
                    continue
                completed_days += 1
                count = result.get("counts", {}).get(horizon, {})
                evaluated += int(count.get("evaluated", 0))
                positive += int(count.get("positive", 0))
                outperform += int(count.get("outperform", 0))
                benchmark_evaluated += int(count.get("benchmark_evaluated", 0))
                # Weight average returns by actual stock observations, not by days.
                stock_values = list((result.get("stock_returns", {}).get(horizon) or {}).values())
                returns.extend(stock_values)
                benchmark = result.get("kospi_returns", {}).get(horizon)
                if benchmark is not None:
                    benchmarks.append(benchmark)
                ex = result.get("excess_returns", {}).get(horizon)
                if ex is not None:
                    excess.append(ex)
            horizons[horizon] = {
                "average_return": round(sum(returns) / len(returns), 2) if returns else None,
                "average_kospi_return": round(sum(benchmarks) / len(benchmarks), 2) if benchmarks else None,
                "average_excess_return": round(sum(excess) / len(excess), 2) if excess else None,
                "absolute_success_rate": round(100 * positive / evaluated, 1) if evaluated else None,
                "outperform_success_rate": round(100 * outperform / benchmark_evaluated, 1) if benchmark_evaluated else None,
                "evaluated_count": evaluated,
                "completed_recommendation_days": completed_days,
            }
        summary["strategies"][key] = {"label": label, "horizons": horizons}
    return summary
