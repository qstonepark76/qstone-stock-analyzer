#!/usr/bin/env python3
"""Q Stone Park Stock Analyzer v3.0-beta
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
FINANCIAL_UNIVERSE = 120  # rolling incremental universe; cache prevents repeated calls
CACHE_DAYS = 90
REQUEST_TIMEOUT = (8, 20)
S = requests.Session()
S.headers.update({"User-Agent": "QStonePark-StockAnalyzer/3.0-beta"})

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

def safe_pct(a, b):
    return ((a / b) - 1) * 100 if a is not None and b not in (None, 0) else None

def weighted_score(parts):
    usable = [(v, w) for v, w in parts if v is not None and math.isfinite(v)]
    if not usable:
        return None, 0
    return round(sum(v*w for v,w in usable) / sum(w for _,w in usable), 1), sum(w for _,w in usable)

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
        try: snapshots.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception: pass
    by_ticker = {}
    for snapshot in snapshots:
        for item in snapshot: by_ticker.setdefault(item["ticker"], []).append(item)
    for stock in stocks:
        series = by_ticker.get(stock["ticker"], [])
        closes = [item["close"] for item in series]
        stock["momentum_5d"] = (stock["close"] / closes[-6] - 1) * 100 if len(closes) >= 6 and closes[-6] else None
        stock["momentum_20d"] = (stock["close"] / closes[-21] - 1) * 100 if len(closes) >= 21 and closes[-21] else None
        changes = [x.get("change_pct") for x in series[-20:] if x.get("change_pct") is not None]
        stock["volatility_20d"] = statistics.pstdev(changes) if len(changes) >= 5 else None

    financial, dart_note = collect_dart(stocks)
    for stock in stocks:
        metrics = financial.get(stock["ticker"], {})
        stock.update(metrics)
        stock["financial_metrics_available"] = any(v is not None for v in metrics.values())

    # Percentile scores are cross-sectional ranks; they are not absolute forecasts.
    score_maps = {
        "roe": score_field(stocks, "roe_pct"),
        "sales_growth": score_field(stocks, "sales_growth_pct"),
        "op_growth": score_field(stocks, "operating_profit_growth_pct"),
        "momentum20": score_field(stocks, "momentum_20d"),
        "momentum5": score_field(stocks, "momentum_5d"),
        "liquidity": score_field(stocks, "trading_value"),
        "volatility": score_field(stocks, "volatility_20d", reverse=True),
    }
    for x in stocks:
        t=x["ticker"]
        # Seven fixed buckets preserve the approved 100-point model. Unconnected
        # factors remain null; the score is shown as provisional with coverage.
        fin, finw = weighted_score([(score_maps["roe"].get(t), 50), (score_maps["sales_growth"].get(t), 25), (score_maps["op_growth"].get(t),25)])
        growth, growthw = weighted_score([(score_maps["sales_growth"].get(t),50),(score_maps["op_growth"].get(t),50)])
        mom, momw = weighted_score([(score_maps["momentum20"].get(t),50),(score_maps["momentum5"].get(t),25),(score_maps["liquidity"].get(t),15),(score_maps["volatility"].get(t),10)])
        x["component_scores"] = {
          "financial": fin, "growth": growth, "momentum": mom,
          "foreign_flow": None, "institution_flow": None,
          "valuation": None, "analyst_outlook": None
        }
        parts=[(fin,20),(growth,20),(mom,15),(None,15),(None,10),(None,10),(None,10)]
        total, coverage = weighted_score(parts)
        x["score"] = total
        x["score_coverage_pct"] = coverage
        x["grade"] = ("S" if total>=90 else "A" if total>=80 else "B" if total>=70 else "C" if total>=60 else "제외") if total is not None else "평가보류"
        x["official_recommendation_eligible"] = coverage == 100 and total is not None
        x["status"] = "공식 추천 심사 가능" if x["official_recommendation_eligible"] else "잠정 평가·공식추천 제외"
        x["reason"] = "재무·성장·모멘텀 상대점수 기반; 미연결 항목은 미반영"
        x["risk_factors"] = [label for key,label in [("roe_pct","ROE 자료 부족"),("sales_growth_pct","매출성장 자료 부족"),("operating_profit_growth_pct","영업이익 성장 자료 부족"),("momentum_20d","20일 주가 이력 부족")] if x.get(key) is None]

    for x in stocks:
        x["financial_score"]=x["component_scores"]["financial"]
        x["growth_score"]=x["component_scores"]["growth"]
        x["momentum_score"]=x["component_scores"]["momentum"]

    # Five strategy lists. Composite TOP10 is deliberately restricted to 100% coverage.
    def top(field, eligible=None):
        pool=[x for x in stocks if x.get(field) is not None and (eligible(x) if eligible else True)]
        return sorted(pool,key=lambda z:z[field],reverse=True)[:10]
    official=top("score",lambda x:x["official_recommendation_eligible"])
    lists={
      "overall": official,
      "financial": top("financial_score"),
      "growth": top("growth_score"),
      "undervalued": [],  # PER/PBR/ROE complete valuation feed not connected yet
      "momentum": top("momentum_score"),
    }
    # Expose named strategy metrics consistently.
    for x in stocks:
        x["financial_score"]=x["component_scores"]["financial"]
        x["growth_score"]=x["component_scores"]["growth"]
        x["momentum_score"]=x["component_scores"]["momentum"]
    lists["financial"]=top("financial_score")
    lists["growth"]=top("growth_score")
    lists["momentum"]=top("momentum_score")

    # Recommendation snapshots and forward return tracking. Future returns are filled
    # by later runs when corresponding trading-day observations become available.
    perf_file=OUT/"recommendation_history.json"
    try: perf=json.loads(perf_file.read_text(encoding="utf-8"))
    except Exception: perf=[]
    if not any(p.get("as_of")==asof.isoformat() for p in perf):
        perf.append({"as_of":asof.isoformat(),"tickers":[{"ticker":x["ticker"],"name":x["name"],"close":x["close"]} for x in official],"returns":{"1w":None,"1m":None,"3m":None}})
    (perf_file).write_text(json.dumps(perf[-500:],ensure_ascii=False,indent=2),encoding="utf-8")

    def compact(items):
        keys=["ticker","name","close","change_pct","score","score_coverage_pct","grade","status","official_recommendation_eligible","component_scores","financial_score","growth_score","momentum_score","roe_pct","sales_growth_pct","operating_profit_growth_pct","momentum_20d","trading_value","reason","risk_factors"]
        return [{k:x.get(k) for k in keys} for x in items]
    result={
      "as_of":asof.isoformat(),"market":{"kospi":None,"kospi_change_pct":None,"analyzed_count":len(stocks),"advancers":sum(1 for x in stocks if (x.get("change_pct") or 0)>0),"decliners":sum(1 for x in stocks if (x.get("change_pct") or 0)<0)},
      "lists":{k:compact(v) for k,v in lists.items()},"top10":compact(official),
      "performance":{"snapshots":len(perf),"note":"추천일 종가 저장. 1주·1개월·3개월 수익률은 이후 거래일 데이터 축적 후 계산 예정."},
      "data_quality":{"label":"v3.0 베타 · 데이터 커버리지 우선","note":dart_note+". 외국인·기관 수급, PER/PBR, 증권사 전망 데이터 공급자는 미연결이며 임의 추정하지 않습니다.","official_top10_count":len(official),"coverage_gate":"공식 종합 TOP10은 7개 평가영역 전체 확보(100%) 시에만 포함"},
      "providers":{"krx":"connected","opendart":"connected" if financial else ("configured_no_data" if DART_KEY else "not_configured"),"investor_flows":"not_connected","valuation":"not_connected","analyst_consensus":"not_connected"},
      "model":{"version":"3.0-beta","weights":{"financial_health_profitability":20,"growth":20,"price_momentum":15,"foreign_flow":15,"institution_flow":10,"valuation_per_pbr":10,"broker_outlook":10},"grade_thresholds":{"S":90,"A":80,"B":70,"C":60,"excluded":0},"note":"고정 배점 유지. 미연결 항목은 점수 0점으로 간주하지 않고 미확보 처리; 커버리지 표시. 등급은 백테스트 전 잠정 기준."}
    }
    (OUT/"latest.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"[완료] v3.0-beta {asof}: KRX {len(stocks)}개 / DART 재무 {len(financial)}개 / 공식추천 가능 {len(official)}개",flush=True)


if __name__ == "__main__":
    main()
