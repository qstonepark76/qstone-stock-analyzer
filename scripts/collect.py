#!/usr/bin/env python3
"""Q Stone Park Stock Analyzer v2.1
KRX daily market data + throttled/cached OpenDART annual financials.
Unconnected data (foreign/institution flows, PER/PBR, analyst targets) are never fabricated.
"""
import os, json, math, statistics, datetime as dt, io, zipfile, time
from pathlib import Path
import requests
import xml.etree.ElementTree as ET

KRX_URL = os.getenv("KRX_API_BASE", "https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd")
KRX_KEY = os.environ["KRX_AUTH_KEY"].strip()
DART_KEY = os.getenv("DART_AUTH_KEY", "").strip()
OUT = Path("data")
OUT.mkdir(exist_ok=True)
CACHE_FILE = OUT / "financial_cache.json"
FINANCIAL_UNIVERSE = 50
CACHE_DAYS = 30
REQUEST_TIMEOUT = (8, 20)
S = requests.Session()
S.headers.update({"User-Agent": "QStonePark-StockAnalyzer/2.1"})

def parse_rows(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("OutBlock_1", "output", "data", "result"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return None

def get_krx_day(day):
    response = S.get(
        KRX_URL,
        headers={"AUTH_KEY": KRX_KEY, "Content-Type": "application/json"},
        params={"basDd": day.strftime("%Y%m%d")},
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code == 401:
        raise RuntimeError("KRX 401 Unauthorized: KRX_AUTH_KEY 또는 API 이용승인/요청 헤더 확인 필요")
    response.raise_for_status()
    rows = parse_rows(response.json())
    if rows is None:
        raise RuntimeError(f"KRX 응답 구조를 해석할 수 없습니다: {response.text[:250]}")
    return rows

def latest_krx_rows():
    errors = []
    for offset in range(10):
        day = dt.date.today() - dt.timedelta(days=offset)
        try:
            rows = get_krx_day(day)
            if rows:
                print(f"[KRX] 거래일 {day.isoformat()} 데이터 {len(rows)}건 수신", flush=True)
                return day, rows
        except Exception as exc:
            errors.append(f"{day}:{str(exc)[:100]}")
    raise RuntimeError("최근 KRX 거래일 데이터 수집 실패: " + " | ".join(errors[-3:]))

def num(row, *keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            try:
                return float(str(value).replace(",", "").replace("%", "").strip())
            except ValueError:
                continue
    return None

def txt(row, *keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""

def normalize(rows):
    result = []
    for row in rows:
        code = txt(row, "ISU_CD", "isuCd", "isu_cd")
        name = txt(row, "ISU_NM", "isuNm", "isu_nm")
        close = num(row, "TDD_CLSPRC", "tddClsprc", "close")
        if not code or not name or not close or close <= 0:
            continue
        result.append({
            "ticker": code[-6:], "name": name, "close": close,
            "change_pct": num(row, "FLUC_RT", "flucRt", "change_pct"),
            "volume": num(row, "ACC_TRDVOL", "accTrdVol", "volume"),
            "trading_value": num(row, "ACC_TRDVAL", "accTrdVal", "trading_value"),
            "market_cap": num(row, "MKTCAP", "mkcap", "market_cap"),
        })
    return result

def load_cache():
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            print("[DART] 캐시 파일을 읽지 못해 새로 생성합니다.", flush=True)
    return {}

def save_cache(cache):
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

def download_corp_map():
    print("[DART] 기업 고유번호 파일 다운로드 시작", flush=True)
    response = S.get(
        "https://opendart.fss.or.kr/api/corpCode.xml",
        params={"crtfc_key": DART_KEY},
        timeout=(10, 30),
    )
    response.raise_for_status()
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    xml_name = next(name for name in archive.namelist() if name.lower().endswith(".xml"))
    root = ET.fromstring(archive.read(xml_name))
    mapping = {}
    for item in root.findall(".//list"):
        stock = (item.findtext("stock_code") or "").strip()
        corp = (item.findtext("corp_code") or "").strip()
        if stock and corp:
            mapping[stock] = corp
    print(f"[DART] 상장 종목 고유번호 {len(mapping)}개 매칭 준비 완료", flush=True)
    return mapping

def amount(item):
    raw = item.get("thstrm_amount") or item.get("thstrm_add_amount") or ""
    raw = str(raw).replace(",", "").strip()
    try:
        return float(raw)
    except ValueError:
        return None

def previous_amount(item):
    raw = item.get("frmtrm_amount") or item.get("frmtrm_q_amount") or ""
    raw = str(raw).replace(",", "").strip()
    try:
        return float(raw)
    except ValueError:
        return None

def pick_account(items, names):
    # Prefer exact account names, then substring matches.
    for wanted in names:
        for item in items:
            if (item.get("account_nm") or "").replace(" ", "") == wanted.replace(" ", ""):
                value = amount(item)
                if value is not None:
                    return item
    for wanted in names:
        for item in items:
            if wanted.replace(" ", "") in (item.get("account_nm") or "").replace(" ", ""):
                value = amount(item)
                if value is not None:
                    return item
    return None

def dart_company_financial(corp_code, year):
    """One company, one annual report request. Try consolidated, then separate statements."""
    endpoint = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
    last_message = ""
    for fs_div in ("CFS", "OFS"):
        response = S.get(
            endpoint,
            params={
                "crtfc_key": DART_KEY, "corp_code": corp_code,
                "bsns_year": str(year), "reprt_code": "11011",
                "fs_div": fs_div,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        status = payload.get("status")
        if status == "000" and isinstance(payload.get("list"), list):
            items = payload["list"]
            if items:
                return items, fs_div, ""
        last_message = f"{status}: {payload.get('message', '')}"
        if status not in ("013", "020"):
            break
    return None, None, last_message

def extract_financial(items):
    sales = pick_account(items, ["매출액", "수익(매출액)", "영업수익"])
    op = pick_account(items, ["영업이익", "영업이익(손실)"])
    net = pick_account(items, [
        "당기순이익", "당기순이익(손실)",
        "지배기업의 소유주에게 귀속되는 당기순이익",
    ])
    equity = pick_account(items, ["자본총계"])
    sales_now = amount(sales) if sales else None
    sales_prev = previous_amount(sales) if sales else None
    op_now = amount(op) if op else None
    op_prev = previous_amount(op) if op else None
    net_now = amount(net) if net else None
    equity_now = amount(equity) if equity else None
    equity_prev = previous_amount(equity) if equity else None
    sales_growth = ((sales_now / sales_prev) - 1) * 100 if sales_now is not None and sales_prev not in (None, 0) else None
    op_growth = ((op_now / op_prev) - 1) * 100 if op_now is not None and op_prev not in (None, 0) else None
    avg_equity = ((equity_now + equity_prev) / 2) if equity_now is not None and equity_prev not in (None, 0) else None
    roe = (net_now / avg_equity) * 100 if net_now is not None and avg_equity not in (None, 0) else None
    return {
        "roe_pct": roe, "sales_growth_pct": sales_growth,
        "operating_profit_growth_pct": op_growth,
    }

def collect_dart(stocks):
    if not DART_KEY:
        return {}, "DART_AUTH_KEY 미등록"
    year = dt.date.today().year - 1
    cache = load_cache()
    try:
        corp_map = download_corp_map()
    except Exception as exc:
        return {}, f"DART 기업코드 파일 오류: {str(exc)[:160]}"
    # Prioritize liquid names; only a bounded set is queried in a run.
    selected = sorted(
        stocks,
        key=lambda x: (x.get("trading_value") or 0),
        reverse=True
    )[:FINANCIAL_UNIVERSE]
    now = dt.datetime.now(dt.timezone.utc)
    results = {}
    todo = []
    for stock in selected:
        ticker = stock["ticker"]
        cached = cache.get(ticker)
        fresh = False
        if cached:
            try:
                saved = dt.datetime.fromisoformat(cached.get("cached_at", "").replace("Z", "+00:00"))
                fresh = (now - saved).days < CACHE_DAYS and cached.get("financial_year") == year
            except Exception:
                fresh = False
        if fresh:
            results[ticker] = cached.get("metrics", {})
        else:
            corp = corp_map.get(ticker)
            if corp:
                todo.append((stock, corp))
    print(
        f"[DART] 우선 조회 {len(selected)}개 종목 / 캐시 재사용 {len(results)}개 / 신규 조회 {len(todo)}개",
        flush=True,
    )
    successes = 0
    failures = 0
    for index, (stock, corp) in enumerate(todo, start=1):
        try:
            items, fs_div, message = dart_company_financial(corp, year)
            if not items:
                failures += 1
                print(f"[DART] {index}/{len(todo)} {stock['ticker']} {stock['name']}: 자료 없음 ({message})", flush=True)
                continue
            metrics = extract_financial(items)
            if not any(value is not None for value in metrics.values()):
                failures += 1
                print(f"[DART] {index}/{len(todo)} {stock['ticker']} {stock['name']}: 필요한 계정과목 미확인", flush=True)
                continue
            cache[stock["ticker"]] = {
                "cached_at": now.isoformat(), "financial_year": year,
                "corp_code": corp, "fs_div": fs_div, "metrics": metrics,
            }
            results[stock["ticker"]] = metrics
            successes += 1
            print(f"[DART] {index}/{len(todo)} {stock['ticker']} {stock['name']}: 수집 성공", flush=True)
        except Exception as exc:
            failures += 1
            print(f"[DART] {index}/{len(todo)} {stock['ticker']} {stock['name']}: 오류 {str(exc)[:120]}", flush=True)
        # Be gentle to the public API and avoid burst requests.
        time.sleep(0.15)
    save_cache(cache)
    note = f"OpenDART {year}년 사업보고서: 재무지표 확보 {len(results)}개사, 신규 성공 {successes}개, 실패/자료없음 {failures}개"
    print("[DART] " + note, flush=True)
    return results, note

def percentile(values, higher=True):
    valid = sorted(v for v in values if v is not None and math.isfinite(v))
    output = []
    for value in values:
        if value is None or not math.isfinite(value) or not valid:
            output.append(None)
        else:
            below = sum(1 for x in valid if x < value)
            equal = sum(1 for x in valid if x == value)
            p = 100 * (below + (equal + 1) / 2) / len(valid)
            output.append(p if higher else 100 - p)
    return output

def score_field(stocks, field, reverse=False):
    scores = percentile([s.get(field) for s in stocks], not reverse)
    return {s["ticker"]: score for s, score in zip(stocks, scores)}

def main():
    asof, raw = latest_krx_rows()
    stocks = normalize(raw)
    if len(stocks) < 30:
        raise RuntimeError(f"KRX 정상 종목 수 부족: {len(stocks)}")

    history = OUT / "history"
    history.mkdir(exist_ok=True)
    (history / f"{asof:%Y%m%d}.json").write_text(json.dumps(stocks, ensure_ascii=False), encoding="utf-8")
    snapshots = []
    for path in sorted(history.glob("*.json"))[-35:]:
        try:
            snapshots.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            pass
    by_ticker = {}
    for snapshot in snapshots:
        for item in snapshot:
            by_ticker.setdefault(item["ticker"], []).append(item)
    for stock in stocks:
        series = by_ticker.get(stock["ticker"], [])
        closes = [item["close"] for item in series]
        stock["momentum_5d"] = (stock["close"] / closes[-6] - 1) * 100 if len(closes) >= 6 and closes[-6] else None
        stock["momentum_20d"] = (stock["close"] / closes[-21] - 1) * 100 if len(closes) >= 21 and closes[-21] else None
        changes = [item.get("change_pct") for item in series[-20:] if item.get("change_pct") is not None]
        stock["volatility_20d"] = statistics.pstdev(changes) if len(changes) >= 5 else None

    financial, dart_note = collect_dart(stocks)
    for stock in stocks:
        metrics = financial.get(stock["ticker"], {})
        stock.update(metrics)
        stock["financial_metrics_available"] = any(v is not None for v in metrics.values())

    p20 = score_field(stocks, "momentum_20d")
    p5 = score_field(stocks, "momentum_5d")
    pvalue = score_field(stocks, "trading_value")
    pvol = score_field(stocks, "volatility_20d", reverse=True)
    pday = score_field(stocks, "change_pct")
    proe = score_field(stocks, "roe_pct")
    psales = score_field(stocks, "sales_growth_pct")
    pop = score_field(stocks, "operating_profit_growth_pct")

    for stock in stocks:
        ticker = stock["ticker"]
        technical_parts = [(p20[ticker], 35), (p5[ticker], 20), (pvalue[ticker], 20), (pvol[ticker], 15), (pday[ticker], 10)]
        technical = [(v, w) for v, w in technical_parts if v is not None]
        stock["technical_score"] = round(sum(v*w for v,w in technical)/sum(w for _,w in technical), 1) if technical else None
        fin_parts = [(proe[ticker], 35), (psales[ticker], 30), (pop[ticker], 35)]
        fin = [(v,w) for v,w in fin_parts if v is not None]
        stock["financial_score"] = round(sum(v*w for v,w in fin)/sum(w for _,w in fin), 1) if fin else None
        # Current connected target model: fundamentals 25 + momentum 15.
        # Unconnected factors remain unavailable and are not imputed.
        model_parts = [
            (stock["financial_score"], 25),
            (None, 15), (None, 15),
            (p20[ticker], 15),
            (None, 15), (None, 15),
        ]
        available = [(v,w) for v,w in model_parts if v is not None]
        stock["score"] = round(sum(v*w for v,w in available)/sum(w for _,w in available), 1) if available else stock["technical_score"]
        stock["score_coverage_pct"] = round(sum(w for _,w in available), 0)
        stock["status"] = "잠정 평가" if stock["score_coverage_pct"] < 100 else "종합평가 완료"

    ranked = sorted(stocks, key=lambda x: (x.get("score") is not None, x.get("score") or -1), reverse=True)
    advancers = sum(1 for x in stocks if (x.get("change_pct") or 0) > 0)
    decliners = sum(1 for x in stocks if (x.get("change_pct") or 0) < 0)
    fields = (
        "ticker","name","close","change_pct","score","score_coverage_pct","status",
        "momentum_20d","trading_value","technical_score","financial_score",
        "roe_pct","sales_growth_pct","operating_profit_growth_pct",
    )
    top10 = [{key: stock.get(key) for key in fields} for stock in ranked[:10]]
    avg_coverage = round(sum(x["score_coverage_pct"] for x in top10)/len(top10), 1) if top10 else 0
    result = {
        "as_of": asof.isoformat(),
        "market": {"kospi": None, "kospi_change_pct": None, "analyzed_count": len(stocks),
                   "advancers": advancers, "decliners": decliners},
        "top10": top10,
        "performance": {"avg_return_pct": None},
        "data_quality": {
            "label": "KRX 시세 수집 완료",
            "note": dart_note + ". 외국인·기관 수급, PER/PBR, 증권사 목표주가는 별도 공급자 미연결.",
        },
        "providers": {
            "krx": "connected",
            "opendart": "connected" if financial else ("configured_no_data" if DART_KEY else "not_configured"),
            "investor_flows": "not_connected", "valuation": "not_connected",
            "analyst_consensus": "not_connected",
        },
        "model": {
            "version": "2.1",
            "weights": {"fundamentals":25,"foreign_flow":15,"institution_flow":15,
                        "momentum":15,"valuation":15,"analyst_consensus":15},
            "top10_average_coverage_pct": avg_coverage,
            "note": "연결된 항목만 가중치를 재정규화한 잠정 점수. 데이터 커버리지를 함께 확인하세요.",
        },
    }
    (OUT / "latest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[완료] {asof}: KRX {len(stocks)}개 종목 / DART 재무 확보 {len(financial)}개 / TOP10 {len(top10)}개 / 평균 커버리지 {avg_coverage}%", flush=True)

if __name__ == "__main__":
    main()
