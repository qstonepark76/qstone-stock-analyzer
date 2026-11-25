#!/usr/bin/env python3
"""Q Stone Park Stock Analyzer v3.2-beta
KRX daily market data + throttled/cached OpenDART annual financials.
Unconnected data (foreign/institution flows, PER/PBR, analyst targets) are never fabricated.
"""
import os, json, math, statistics, datetime as dt, io, zipfile, time
from pathlib import Path
import requests
import xml.etree.ElementTree as ET
from analyst_consensus import load_and_score_consensus
from recommendation_performance import update_recommendation_performance, build_performance_summary, STRATEGY_LABELS
from industry_relative import score_industry_relative, aggregate_candidate
from dart_capital_metrics import extract_capital_metrics, industry_metrics_for_scoring, pick_standard_account
from financial_industry import financial_model_for, load_financial_observations, external_financial_peers
from metric_quality import assess_industry_metrics, admitted_industry_metrics

KRX_URL = os.getenv("KRX_API_BASE", "https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd")
KRX_KEY = os.getenv("KRX_AUTH_KEY", "").strip()
DART_KEY = os.getenv("DART_AUTH_KEY", "").strip()
OUT = Path("data")
OUT.mkdir(exist_ok=True)
CACHE_FILE = OUT / "financial_cache.json"
FINANCIAL_UNIVERSE = int(os.getenv("DART_BATCH_SIZE", "100"))  # 3-run coverage across top 300
KIS_UNIVERSE = int(os.getenv("KIS_BATCH_SIZE", "100"))  # 3-run coverage across top 300
KIS_STATE_FILE = OUT / "kis_universe_state.json"
KIS_FLOW_CACHE_FILE = OUT / "kis_flow_cache.json"
SECTOR_CACHE_FILE = OUT / "sector_industry_cache.json"
CACHE_DAYS = 90
UNIVERSE_STATE_FILE = OUT / "financial_universe_state.json"
REQUEST_TIMEOUT = (5, 12)
API_PAUSE_SECONDS = 0.2
S = requests.Session()
S.headers.update({"User-Agent": "QStonePark-StockAnalyzer/3.2-beta"})

def request_with_retry(method, url, attempts=3, **kwargs):
    """Retry transient provider failures without hiding final HTTP/API errors."""
    last_error = None
    for attempt in range(attempts):
        try:
            response = S.request(method, url, **kwargs)
            if response.status_code == 429 or response.status_code >= 500:
                response.raise_for_status()
                raise requests.RequestException(f"Transient HTTP {response.status_code}")
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt + 1 >= attempts:
                raise
            delay = min(0.8 * (2 ** attempt), 5.0)
            print(f"[API RETRY] {method} {url}: {type(exc).__name__} / {attempt + 1}/{attempts}, {delay:.1f}s 후 재시도", flush=True)
            time.sleep(delay)
    raise last_error

def kis_request_with_retry(url, *, headers, params, timeout=REQUEST_TIMEOUT, attempts=4):
    """Retry KIS transient 5xx/429 responses with a slower, provider-friendly backoff."""
    last_error = None
    for attempt in range(attempts):
        try:
            response = S.get(url, headers=headers, params=params, timeout=timeout)
            if response.status_code == 429 or response.status_code >= 500:
                response.raise_for_status()
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt + 1 >= attempts:
                raise
            retry_after = response.headers.get("Retry-After") if "response" in locals() else None
            try:
                delay = float(retry_after)
            except (TypeError, ValueError):
                delay = min(1.5 * (2 ** attempt), 12.0)
            print(
                f"[KIS RETRY] {params.get('FID_INPUT_ISCD', '')} "
                f"HTTP/API 오류: {str(exc)[:100]} / {attempt + 1}/{attempts}, "
                f"{delay:.1f}s 후 재시도",
                flush=True,
            )
            time.sleep(max(1.0, delay))
    raise last_error


def has_financial_metrics(metrics):
    """A cache entry is valid only when at least one actual financial value exists."""
    if not isinstance(metrics, dict):
        return False
    industry = metrics.get("industry_metrics") if isinstance(metrics.get("industry_metrics"), dict) else {}
    return any(metrics.get(key) is not None for key in (
        "roe_pct", "sales_growth_pct", "operating_profit_growth_pct",
        "net_income", "equity_total",
    )) or any(industry.get(key) is not None for key in (
        "operating_margin_pct", "roic_pct", "asset_turnover",
        "net_debt_to_ebitda", "cash_conversion_pct",
    ))


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

def get_krx_kospi_day(day):
    """Fetch the KOSPI composite index close from the KRX index API."""
    endpoint = "https://data-dbg.krx.co.kr/svc/apis/idx/kospi_dd_trd"
    response = S.get(endpoint, headers={"AUTH_KEY": KRX_KEY, "Content-Type": "application/json"},
                     params={"basDd": day.strftime("%Y%m%d")}, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    rows = parse_rows(response.json())
    if rows is None:
        raise RuntimeError(f"KRX 지수 응답 구조를 해석할 수 없습니다: {response.text[:250]}")
    for row in rows:
        name = txt(row, "IDX_NM", "idxNm", "idx_nm").replace(" ", "").upper()
        close = num(row, "CLSPRC_IDX", "clsprcIdx", "close")
        if close and (name in ("코스피", "KOSPI", "코스피종합") or name.startswith("코스피종합")):
            return {"date": day.isoformat(), "name": txt(row, "IDX_NM", "idxNm", "idx_nm"),
                    "close": close, "change_pct": num(row, "FLUC_RT", "flucRt", "change_pct")}
    raise RuntimeError("KRX 지수 응답에서 KOSPI 종합지수를 찾지 못했습니다.")


def latest_krx_kospi(asof):
    errors = []
    for offset in range(10):
        day = asof - dt.timedelta(days=offset)
        try:
            return get_krx_kospi_day(day)
        except Exception as exc:
            errors.append(f"{day}:{str(exc)[:90]}")
    raise RuntimeError("최근 KOSPI 지수 데이터 수집 실패: " + " | ".join(errors[-3:]))


def backfill_kospi_history(asof, index_history_dir, target_sessions=61, max_calendar_days=110):
    """Persist actual daily KOSPI closes needed for 5/20/60-session benchmarking."""
    index_history_dir = Path(index_history_dir)
    index_history_dir.mkdir(parents=True, exist_ok=True)

    def valid_count():
        count = 0
        for path in index_history_dir.glob("*.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                if path.stem.isdigit() and item.get("close") not in (None, 0):
                    count += 1
            except Exception:
                continue
        return count

    count = valid_count()
    if count >= target_sessions:
        print(f"[KOSPI HISTORY] 기존 지수 이력 {count}거래일 확보, 추가 조회 생략", flush=True)
        return count

    added = 0
    attempted = 0
    for offset in range(1, max_calendar_days + 1):
        if count >= target_sessions:
            break
        day = asof - dt.timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        path = index_history_dir / f"{day:%Y%m%d}.json"
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                if existing.get("close") not in (None, 0):
                    continue
            except Exception:
                pass
        attempted += 1
        try:
            item = get_krx_kospi_day(day)
            actual_day = dt.date.fromisoformat(item["date"])
            target = index_history_dir / f"{actual_day:%Y%m%d}.json"
            if not target.exists():
                target.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
                count += 1
                added += 1
            if added % 10 == 0 or count >= target_sessions:
                print(f"[KOSPI HISTORY] {count}/{target_sessions} 거래일 확보", flush=True)
        except Exception as exc:
            if attempted <= 3:
                print(f"[KOSPI HISTORY] {day} 조회 건너뜀: {str(exc)[:100]}", flush=True)
        time.sleep(0.12)

    print(f"[KOSPI HISTORY] 최종 {count}거래일 확보, 이번 실행 추가 {added}일 / 조회 {attempted}일", flush=True)
    return count


def backfill_krx_history(asof, history_dir, target_sessions=61, max_calendar_days=110):
    """Backfill actual KRX daily snapshots until 61 trading sessions are available."""
    history_dir = Path(history_dir)
    history_dir.mkdir(parents=True, exist_ok=True)

    def valid_snapshot_count():
        count = 0
        for path in history_dir.glob("*.json"):
            try:
                rows = json.loads(path.read_text(encoding="utf-8"))
                if path.stem.isdigit() and isinstance(rows, list) and rows:
                    count += 1
            except Exception:
                continue
        return count

    count = valid_snapshot_count()
    if count >= target_sessions:
        print(f"[KRX HISTORY] 기존 이력 {count}거래일 확보, 추가 조회 생략", flush=True)
        return count

    attempted = 0
    added = 0
    for offset in range(1, max_calendar_days + 1):
        if count >= target_sessions:
            break
        day = asof - dt.timedelta(days=offset)
        path = history_dir / f"{day:%Y%m%d}.json"
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(existing, list) and existing:
                    continue
            except Exception:
                pass
        attempted += 1
        try:
            rows = normalize(get_krx_day(day))
            if rows:
                path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
                count += 1
                added += 1
                if added % 10 == 0 or count >= target_sessions:
                    print(f"[KRX HISTORY] {count}/{target_sessions} 거래일 확보 (과거 데이터 {added}일 추가)", flush=True)
        except Exception as exc:
            # Weekends, holidays, and dates outside the provider's range are expected.
            if attempted <= 3:
                print(f"[KRX HISTORY] {day} 조회 건너뜀: {str(exc)[:100]}", flush=True)
        time.sleep(0.12)

    print(f"[KRX HISTORY] 최종 {count}거래일 확보, 이번 실행 추가 {added}일 / 조회 {attempted}일", flush=True)
    return count


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
            "sector_raw": txt(row, "SECT_NM", "SECT_NM_KOR", "IDX_IND_NM", "INDUSTRY_NM", "IND_NM", "sector", "industry"),
        })
    return result

# Twelve investment-oriented sectors. Match official KRX sector first, then
# the issuer's disclosed major products (Industry); never force unknowns into "Other".
SECTOR_RULES = [
    ("반도체·전자", ("반도체", "전자부품", "전자제품", "디스플레이", "광학", "전기장비", "통신장비", "전자기기")),
    ("바이오·헬스케어", ("의약품", "제약", "바이오", "생명과학", "의료기기", "의료용 물질", "진단", "병원", "건강관리")),
    ("자동차·모빌리티", ("자동차", "자동차부품", "자동차용", "차량", "완성차", "모빌리티")),
    ("2차전지·소재", ("2차전지", "이차전지", "축전지", "배터리", "양극재", "음극재", "전지소재")),
    ("금융", ("은행", "증권", "보험", "금융", "신용카드", "캐피탈", "자산운용", "투자업", "지주회사")),
    ("IT·소프트웨어", ("소프트웨어", "정보서비스", "컴퓨터프로그래밍", "시스템통합", "게임", "전자상거래", "인터넷", "데이터처리", "IT서비스")),
    ("산업재·방산", ("방위", "방산", "무기", "항공기", "우주항공", "조선", "선박", "기계장비", "산업용로봇", "철강", "제철", "비철금속", "금속", "엔진", "터빈", "철도차량")),
    ("에너지·화학", ("원유", "정유", "석유", "가스", "전력", "에너지", "화학물질", "화학제품", "정밀화학", "합성고무", "플라스틱", "태양광", "풍력")),
    ("건설·인프라", ("건설", "건축", "토목", "시멘트", "콘크리트", "건자재", "건축자재", "인프라")),
    ("소비재·유통", ("식료품", "음료", "식품", "음식료", "육류", "곡물", "제과", "종합소매", "백화점", "대형마트", "유통", "생활용품", "가구", "화장품", "섬유", "의복", "패션")),
    ("통신·미디어·엔터", ("전기통신", "무선통신", "통신업", "방송", "영화", "영상", "음악", "엔터테인먼트", "광고", "출판", "콘텐츠")),
    ("운송·물류", ("항공운송", "육상운송", "해상운송", "운송", "물류", "택배", "창고", "해운", "항만")),
]

def classify_sector(sector_value, industry_value=None):
    """Map official KRX sector / disclosed major products into the 12 house sectors."""
    sector_text = str(sector_value or "").replace(" ", "").lower()
    industry_text = str(industry_value or "").replace(" ", "").lower()
    for sector_name, keywords in SECTOR_RULES:
        normalized = tuple(str(k).replace(" ", "").lower() for k in keywords)
        if any(k in sector_text for k in normalized):
            return sector_name, "high"
    for sector_name, keywords in SECTOR_RULES:
        normalized = tuple(str(k).replace(" ", "").lower() for k in keywords)
        if any(k in industry_text for k in normalized):
            return sector_name, "medium"
    return None, None

def _listing_value(value):
    """Normalize provider cells; pandas NaN/NaT must not become the literal text 'nan'."""
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in ("", "nan", "none", "nat", "<na>") else text


def _listing_ticker(row):
    for key in ("Code", "Symbol", "ticker", "Ticker", "ISU_CD", "isuCd"):
        value = _listing_value(row.get(key))
        if not value:
            continue
        raw = str(value).strip()
        # KRX ISIN format: KR + security type + six-digit issue code + check digit.
        if key in ("ISU_CD", "isuCd") and raw.upper().startswith("KR") and len(raw) == 12:
            digits = "".join(ch for ch in raw[3:9] if ch.isdigit())
            if len(digits) == 6:
                return digits
        digits = "".join(ch for ch in raw if ch.isdigit())
        if 1 <= len(digits) <= 6:
            return digits.zfill(6)
        if len(digits) > 6:
            return digits[-6:]
    return ""

def classify_industry_code(industry_code):
    """Map OpenDART's official company industry code to the 12 house sectors."""
    code = "".join(ch for ch in str(industry_code or "") if ch.isdigit())
    if len(code) < 2:
        return None
    prefix = int(code[:2])
    # More specific OpenDART sub-industry codes used by service-sector issuers.
    if code.startswith("721"):
        return "건설·인프라"
    if code.startswith("713"):
        return "통신·미디어·엔터"
    if code.startswith("752"):
        return "소비재·유통"
    if code.startswith("753"):
        return "IT·소프트웨어"
    if code.startswith("761"):
        return "자동차·모빌리티"
    if code.startswith("762") or code == "969":
        return "소비재·유통"
    # KSIC 582 is software publishing; other 58-61 codes are media/broadcast/telecom.
    if code.startswith("582"):
        return "IT·소프트웨어"
    if prefix == 28 and (code == "282" or code.startswith("2820")):
        return "2차전지·소재"
    if prefix in (5, 19, 20, 22, 35):
        return "에너지·화학"
    if prefix in (21, 27, 86):
        return "바이오·헬스케어"
    if prefix == 26:
        return "반도체·전자"
    if prefix == 30:
        return "자동차·모빌리티"
    if prefix in (24, 25, 29, 31, 34, 6, 7, 8):
        return "산업재·방산"
    if prefix in (23, 36, 37, 38, 39, 41, 42):
        return "건설·인프라"
    if prefix in (10, 11, 12, 13, 14, 15, 16, 17, 18, 32, 33, 45, 46, 47, 55, 56):
        return "소비재·유통"
    if prefix in (49, 50, 51, 52):
        return "운송·물류"
    if prefix in (58, 59, 60, 61, 90, 91):
        return "통신·미디어·엔터"
    if prefix in (62, 63):
        return "IT·소프트웨어"
    if prefix in (64, 65, 66):
        return "금융"
    if prefix == 28:
        return "산업재·방산"
    return None


PREFERRED_SHARE_PARENT = {
    "005935": "005930",  # 삼성전자우 -> 삼성전자
    "005387": "005380",  # 현대차2우B -> 현대차
    "005385": "005380",  # 현대차우 -> 현대차
    "000815": "000810",  # 삼성화재우 -> 삼성화재
    "00680K": "006800",  # 미래에셋증권2우B -> 미래에셋증권
    "066575": "066570",  # LG전자우 -> LG전자
    "009155": "009150",  # 삼성전기우 -> 삼성전기
    "051915": "051910",  # LG화학우 -> LG화학
    "000155": "000150",  # 두산우 -> 두산
    "071055": "071050",  # 한국금융지주우 -> 한국금융지주
}
MANUAL_SECTOR_OVERRIDES = {
    "326030": "바이오·헬스케어",  # SK바이오팜: 신약 연구·개발 및 판매
    "395400": "금융",  # SK리츠
    "330590": "금융",  # 롯데리츠
    "451800": "금융",  # 한화리츠
    "365550": "금융",  # ESR켄달스퀘어리츠
    "293940": "금융",  # 신한알파리츠
}


def apply_sector_overrides(stocks, sector_map):
    """Apply only verified issuer-share links and explicit, documented business-type overrides."""
    result = dict(sector_map)
    for stock in stocks:
        ticker = stock["ticker"]
        if ticker in MANUAL_SECTOR_OVERRIDES:
            result[ticker] = {
                "sector": MANUAL_SECTOR_OVERRIDES[ticker],
                "sector_industry_code": None,
                "sector_source": "Manual verified company mapping",
                "sector_confidence": "medium",
            }
            continue
        parent = PREFERRED_SHARE_PARENT.get(ticker)
        if parent and parent in result:
            inherited = dict(result[parent])
            inherited["sector_source"] = "Same issuer ordinary share"
            inherited["sector_confidence"] = "high"
            result[ticker] = inherited
    return result


def load_dart_sector_classification(stocks):
    """Fetch official OpenDART company industry codes, cache them, and classify without name guessing."""
    if not DART_KEY:
        return {}, "OpenDART 업종코드: DART_AUTH_KEY 미등록"
    try:
        cache = json.loads(SECTOR_CACHE_FILE.read_text(encoding="utf-8"))
        if not isinstance(cache, dict):
            cache = {}
    except Exception:
        cache = {}
    try:
        corp_map = download_corp_map()
    except Exception as exc:
        return {}, f"OpenDART 업종코드: 기업코드 파일 오류 ({str(exc)[:120]})"

    now = dt.datetime.now(dt.timezone.utc)
    results, requested, errors = {}, 0, 0
    endpoint = "https://opendart.fss.or.kr/api/company.json"
    for stock in stocks:
        ticker = stock["ticker"]
        cached = cache.get(ticker) or {}
        code = _listing_value(cached.get("industry_code"))
        try:
            saved = dt.datetime.fromisoformat(str(cached.get("cached_at", "")).replace("Z", "+00:00"))
            fresh = bool(code) and (now - saved).days < 365
        except Exception:
            fresh = False
        if not fresh:
            corp_code = corp_map.get(ticker)
            if not corp_code:
                errors += 1
                continue
            try:
                response = request_with_retry(
                    "GET", endpoint,
                    params={"crtfc_key": DART_KEY, "corp_code": corp_code},
                    timeout=REQUEST_TIMEOUT,
                )
                payload = response.json()
                if payload.get("status") == "000":
                    code = _listing_value(payload.get("induty_code"))
                    cache[ticker] = {
                        "corp_code": corp_code, "industry_code": code or None,
                        "cached_at": now.isoformat(),
                    }
                    requested += 1
                else:
                    errors += 1
                    continue
            except Exception as exc:
                errors += 1
                print(f"[SECTOR DART] {ticker} 업종코드 조회 실패: {str(exc)[:100]}", flush=True)
                continue
            if code:
                time.sleep(float(os.getenv("DART_COMPANY_PAUSE_SECONDS", "0.2")))
        if code:
            metadata = {
                "sector_industry_code": code,
                "sector_source": "OpenDART industry code",
                "sector_confidence": "high",
            }
            category = classify_industry_code(code)
            # Keep exact official code even when the broad display-sector map
            # does not recognize it; peer grouping must not collapse to 12 sectors.
            if category:
                metadata["sector"] = category
            results[ticker] = metadata

    results = apply_sector_overrides(stocks, results)
    SECTOR_CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    note = f"OpenDART 업종코드 및 검증된 보완매핑: {len(results)}/{len(stocks)}개 분류, 이번 회차 신규 조회 {requested}개, 미확보 {errors}개"
    print("[SECTOR DART] " + note, flush=True)
    return results, note


def load_sector_classification():
    """Load KRX listing metadata, preferring KRX-DESC; log schema and never guess unknown sectors."""
    try:
        import FinanceDataReader as fdr
    except Exception as exc:
        print(f"[SECTOR] FinanceDataReader 불러오기 실패: {str(exc)[:180]}", flush=True)
        return {}

    best = {}
    for listing_name in ("KRX-DESC", "KRX"):
        try:
            frame = fdr.StockListing(listing_name)
            if frame is None or not hasattr(frame, "to_dict"):
                print(f"[SECTOR] {listing_name} 응답이 DataFrame 형식이 아닙니다.", flush=True)
                continue
            records = frame.to_dict("records")
            columns = list(getattr(frame, "columns", []))
            print(f"[SECTOR] {listing_name} 행={len(records)}, 컬럼={columns[:18]}", flush=True)
            mapped = {}
            raw_sector_count = 0
            raw_industry_count = 0
            for row in records:
                ticker = _listing_ticker(row)
                if not ticker:
                    continue
                sector_raw = next((_listing_value(row.get(k)) for k in ("Sector", "sector", "업종", "업종명") if _listing_value(row.get(k))), "")
                industry_raw = next((_listing_value(row.get(k)) for k in ("Industry", "industry", "주요제품", "주요 제품", "Products") if _listing_value(row.get(k))), "")
                raw_sector_count += bool(sector_raw)
                raw_industry_count += bool(industry_raw)
                category, confidence = classify_sector(sector_raw, industry_raw)
                if not category:
                    continue
                mapped[ticker] = {
                    "sector": category,
                    "sector_raw": sector_raw,
                    "sector_industry": industry_raw,
                    "sector_source": listing_name,
                    "sector_confidence": confidence,
                }
            print(
                f"[SECTOR] {listing_name}: 업종값 {raw_sector_count}건, 주요제품값 {raw_industry_count}건, "
                f"분류성공 {len(mapped)}종목",
                flush=True,
            )
            if len(mapped) > len(best):
                best = mapped
            # A non-empty DESC result is preferred; KRX is only a fallback.
            if listing_name == "KRX-DESC" and mapped:
                break
        except Exception as exc:
            print(f"[SECTOR] {listing_name} 수집 실패: {str(exc)[:180]}", flush=True)

    print(f"[SECTOR] 최종 KRX 업종분류 {len(best)}개 종목 매칭", flush=True)
    return best

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
        response = request_with_retry(
            "GET", endpoint,
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

def pick_statement_account(items, statement, names):
    """Pick an account only from its declared statement section.

    OpenDART may label a comprehensive income statement as CIS (not IS),
    especially in consolidated filings. Accept explicit aliases without
    mixing balance-sheet or cash-flow rows into income-statement metrics.
    """
    statements = (statement,) if isinstance(statement, str) else tuple(statement)
    for code in statements:
        scoped = [item for item in items if item.get("sj_div") == code]
        found = pick_account(scoped, names)
        if found is not None:
            return found
    return None


def extract_financial(items, ticker=None, financial_year=None, fs_div=None):
    """Extract verified annual financial values; unsupported ratios remain null."""
    income = ("IS", "CIS")
    sales = pick_standard_account(items, income, ["매출액", "수익(매출액)", "영업수익", "매출"],
                                  ["ifrs-full_Revenue", "ifrs_Revenue"])
    op = pick_standard_account(items, income, ["영업이익", "영업이익(손실)", "영업손익"],
                               ["dart_OperatingIncomeLoss", "ifrs-full_ProfitLossFromOperatingActivities"])
    # Preserve owner-attributable earnings priority for per-share valuation.
    net = pick_standard_account(items, income, ["지배기업의 소유주에게 귀속되는 당기순이익"],
                                ["ifrs-full_ProfitLossAttributableToOwnersOfParent"])
    if net is None and fs_div != "CFS":
        net = pick_standard_account(items, income, ["당기순이익", "당기순이익(손실)", "당기순이익(손실)(*)"],
                                    ["ifrs-full_ProfitLoss", "ifrs_ProfitLoss"])
    equity = pick_standard_account(items, ("BS",), ["자본총계"], ["ifrs-full_Equity", "ifrs_Equity"])
    assets = pick_standard_account(items, ("BS",), ["자산총계"], ["ifrs-full_Assets", "ifrs_Assets"])
    cfo = pick_standard_account(items, ("CF",), [
        "영업활동으로 인한 현금흐름", "영업활동현금흐름", "영업활동으로부터의 현금흐름",
    ], ["ifrs-full_CashFlowsFromUsedInOperatingActivities", "ifrs_CashFlowsFromUsedInOperatingActivities"])
    sales_now = amount(sales) if sales else None
    sales_prev = previous_amount(sales) if sales else None
    op_now = amount(op) if op else None
    op_prev = previous_amount(op) if op else None
    net_now = amount(net) if net else None
    equity_now = amount(equity) if equity else None
    equity_prev = previous_amount(equity) if equity else None
    assets_now = amount(assets) if assets else None
    assets_prev = previous_amount(assets) if assets else None
    cfo_now = amount(cfo) if cfo else None
    financial_currency = (equity or net or sales or {}).get("currency")
    sales_growth = ((sales_now / sales_prev) - 1) * 100 if sales_now is not None and sales_prev not in (None, 0) else None
    op_growth = ((op_now / op_prev) - 1) * 100 if op_now is not None and op_prev not in (None, 0) else None
    avg_equity = ((equity_now + equity_prev) / 2) if equity_now is not None and equity_prev not in (None, 0) else None
    avg_assets = ((assets_now + assets_prev) / 2) if assets_now is not None and assets_prev not in (None, 0) else None
    roe = (net_now / avg_equity) * 100 if net_now is not None and avg_equity not in (None, 0) else None
    operating_margin = (op_now / sales_now) * 100 if op_now is not None and sales_now not in (None, 0) else None
    asset_turnover = sales_now / avg_assets if sales_now is not None and avg_assets not in (None, 0) else None
    cash_conversion = (cfo_now / op_now) * 100 if cfo_now is not None and op_now is not None and op_now > 0 else None
    capital = extract_capital_metrics(items, ticker=ticker, financial_year=financial_year, fs_div=fs_div)
    industry_values = {
        "operating_margin_pct": operating_margin,
        "roic_pct": capital["roic_pct"],
        "asset_turnover": asset_turnover,
        "net_debt_to_ebitda": capital["net_debt_to_ebitda"],
        "cash_conversion_pct": cash_conversion,
    }
    quality = assess_industry_metrics(industry_values, items, financial_year, fs_div,
        {"operating_margin_pct":[op,sales], "asset_turnover":[sales,assets],
         "cash_conversion_pct":[cfo,op]}, capital["capital_metric_audit"])
    return {
        "roe_pct": roe, "sales_growth_pct": sales_growth,
        "operating_profit_growth_pct": op_growth,
        "net_income": net_now, "equity_total": equity_now,
        "financial_currency": financial_currency,
        "industry_metrics": industry_values,
        "industry_metric_quality": quality,
        "capital_metric_audit": capital["capital_metric_audit"],
        "industry_metric_sources": {
            "roic_pct": "OpenDART annual BS/IS/CIS; observed effective tax, average invested capital",
            "net_debt_to_ebitda": "OpenDART annual BS/IS/CIS/CF; reported borrowing incl. bonds, excl. separately reported lease liabilities",
            "operating_margin_pct": "OpenDART IS",
            "asset_turnover": "OpenDART IS + BS average total assets",
            "cash_conversion_pct": "OpenDART CF / IS",
        },
    }

def calculate_valuation(market_cap, net_income, equity_total, currency):
    """Calculate PER/PBR only when KRX market cap and DART amounts share KRW units."""
    if str(currency or "").upper() != "KRW" or market_cap is None or market_cap <= 0:
        return None, None
    per = market_cap / net_income if net_income is not None and net_income > 0 else None
    pbr = market_cap / equity_total if equity_total is not None and equity_total > 0 else None
    return per, pbr

def collect_dart(stocks):
    if not DART_KEY:
        return {}, "DART_AUTH_KEY 미등록"
    year = dt.date.today().year - 1
    cache = load_cache()
    try:
        corp_map = download_corp_map()
    except Exception as exc:
        return {}, f"DART 기업코드 파일 오류: {str(exc)[:160]}"
    # Rotate through the full KRX universe in bounded batches. A fixed top-120
    # selection would repeatedly hit the same firms and never broaden coverage.
    ordered = sorted(stocks, key=lambda x: (x.get("market_cap") or 0), reverse=True)
    try:
        state = json.loads(UNIVERSE_STATE_FILE.read_text(encoding="utf-8"))
        offset = int(state.get("offset", 0)) % max(1, len(ordered))
    except Exception:
        offset = 0
    if not ordered:
        selected = []
    else:
        end = offset + min(FINANCIAL_UNIVERSE, len(ordered))
        selected = ordered[offset:end] if end <= len(ordered) else ordered[offset:] + ordered[:end-len(ordered)]
        next_offset = (offset + len(selected)) % len(ordered)
        UNIVERSE_STATE_FILE.write_text(json.dumps({"offset": next_offset, "universe_size": len(ordered), "batch_size": len(selected), "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[DART] 순환 배치 offset={offset}, 다음 offset={((offset + len(selected)) % max(1,len(ordered)))}", flush=True)
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
                cached_metrics = cached.get("metrics", {})
                fresh = (now - saved).days < CACHE_DAYS and cached.get("financial_year") == year and cached.get("schema_version") == 7 and has_financial_metrics(cached_metrics)
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
            metrics = extract_financial(items, ticker=stock['ticker'], financial_year=year, fs_div=fs_div)
            if not has_financial_metrics(metrics):
                failures += 1
                print(f"[DART] {index}/{len(todo)} {stock['ticker']} {stock['name']}: 필요한 계정과목 미확인", flush=True)
                continue
            cache[stock["ticker"]] = {
                "cached_at": now.isoformat(), "financial_year": year, "schema_version": 7,
                "corp_code": corp, "fs_div": fs_div, "metrics": metrics,
            }
            results[stock["ticker"]] = metrics
            successes += 1
            print(f"[DART] {index}/{len(todo)} {stock['ticker']} {stock['name']}: 수집 성공", flush=True)
        except Exception as exc:
            failures += 1
            print(f"[DART] {index}/{len(todo)} {stock['ticker']} {stock['name']}: 오류 {str(exc)[:120]}", flush=True)
        # Be gentle to the public API and avoid burst requests.
        time.sleep(API_PAUSE_SECONDS)
    save_cache(cache)
    # Reuse valid cached financials for the entire top-300 universe, not only
    # today's rotating batch. This lets daily batches accumulate coverage.
    for stock in stocks:
        ticker = stock["ticker"]
        cached = cache.get(ticker) or {}
        try:
            saved = dt.datetime.fromisoformat(cached.get("cached_at", "").replace("Z", "+00:00"))
            metrics = cached.get("metrics", {})
            fresh = (
                (now - saved).days < CACHE_DAYS
                and cached.get("financial_year") == year
                and cached.get("schema_version") == 7 and has_financial_metrics(metrics)
            )
        except Exception:
            fresh = False
            metrics = {}
        if fresh:
            results.setdefault(ticker, metrics)
    note = f"OpenDART {year}년 사업보고서: 실제 재무값이 확인된 캐시 포함 {len(results)}개사, 이번 회차 신규 성공 {successes}개, 실패/자료없음 {failures}개"
    print("[DART] " + note, flush=True)
    return results, note


def kis_access_token(app_key, app_secret):
    response = S.post(
        "https://openapi.koreainvestment.com:9443/oauth2/tokenP",
        json={"grant_type": "client_credentials", "appkey": app_key, "appsecret": app_secret},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    token = payload.get("access_token")
    if not token:
        raise RuntimeError(f"KIS token response missing access_token: {payload.get('msg1', 'unknown response')}")
    return token

def collect_kis_investor_flows(stocks, asof):
    app_key = os.getenv("KIS_APP_KEY", "").strip()
    app_secret = os.getenv("KIS_APP_SECRET", "").strip()
    if not app_key or not app_secret:
        return {}, "KIS 인증정보 미등록"
    try:
        token = kis_access_token(app_key, app_secret)
    except Exception as exc:
        return {}, f"KIS 토큰 발급 실패: {str(exc)[:140]}"
    endpoint = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily"
    headers = {"authorization": f"Bearer {token}", "appkey": app_key, "appsecret": app_secret,
               "tr_id": "FHPTJ04160001", "custtype": "P"}
    results, errors = {}, 0
    # Rotate a bounded batch because the KIS endpoint is called once per ticker.
    try:
        state = json.loads(KIS_STATE_FILE.read_text(encoding="utf-8"))
        offset = int(state.get("offset", 0)) % max(1, len(stocks))
    except Exception:
        offset = 0
    ordered = sorted(stocks, key=lambda x: (x.get("market_cap") or 0), reverse=True)
    if ordered:
        end = offset + min(KIS_UNIVERSE, len(ordered))
        selected = ordered[offset:end] if end <= len(ordered) else ordered[offset:] + ordered[:end-len(ordered)]
        next_offset = (offset + len(selected)) % len(ordered)
        KIS_STATE_FILE.write_text(json.dumps({"offset": next_offset, "universe_size": len(ordered), "batch_size": len(selected), "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        selected = []
    print(f"[KIS] 순환 배치 offset={offset}, 조회 대상 {len(selected)}개", flush=True)
    for index, stock in enumerate(selected, start=1):
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock["ticker"],
                  "FID_INPUT_DATE_1": asof.strftime("%Y%m%d"),
                  "FID_ORG_ADJ_PRC": "", "FID_ETC_CLS_CODE": ""}
        try:
            response = kis_request_with_retry(endpoint, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
            if str(payload.get("rt_cd", "")) != "0":
                errors += 1
                print(f"[KIS] {stock['ticker']} 응답 오류 {payload.get('msg_cd', '')}: {payload.get('msg1', '')[:100]}", flush=True)
                continue
            rows = payload.get("output2") or []
            if isinstance(rows, dict):
                rows = [rows]
            usable = []
            for row in rows:
                date_text = txt(row, "stck_bsop_date")
                if not date_text or date_text > asof.strftime("%Y%m%d"):
                    continue
                foreign_qty = num(row, "frgn_ntby_qty")
                institution_qty = num(row, "orgn_ntby_qty")
                traded_volume = num(row, "acml_vol")
                if foreign_qty is not None and institution_qty is not None and traded_volume is not None and traded_volume > 0:
                    usable.append((date_text, foreign_qty, institution_qty, traded_volume))
            usable.sort(key=lambda item: item[0], reverse=True)
            recent = usable[:5]
            if len(recent) == 5:
                denominator = sum(item[3] for item in recent)
                results[stock["ticker"]] = {
                    "foreign_net_buy_qty_5d": sum(item[1] for item in recent),
                    "institution_net_buy_qty_5d": sum(item[2] for item in recent),
                    "foreign_flow_5d_pct": 100 * sum(item[1] for item in recent) / denominator,
                    "institution_flow_5d_pct": 100 * sum(item[2] for item in recent) / denominator,
                    "investor_flow_as_of": recent[0][0], "investor_flow_sessions": 5,
                }
            else:
                errors += 1
        except Exception as exc:
            errors += 1
            print(f"[KIS] {stock['ticker']} 조회 실패: {str(exc)[:120]}", flush=True)
        if index % 25 == 0:
            print(f"[KIS] {index}/{len(selected)} 종목 처리, 이번 회차 확보 {len(results)}개", flush=True)
        # KIS per-ticker endpoint is sensitive to burst traffic; use a dedicated
        # interval rather than the shorter general public-API pause.
        time.sleep(float(os.getenv("KIS_REQUEST_PAUSE_SECONDS", "0.65")))
    # Persist each successful 5-session result so rotating batches build
    # universe-wide coverage over subsequent runs.
    try:
        flow_cache = json.loads(KIS_FLOW_CACHE_FILE.read_text(encoding="utf-8"))
        if not isinstance(flow_cache, dict):
            flow_cache = {}
    except Exception:
        flow_cache = {}
    for ticker, metrics in results.items():
        flow_cache[ticker] = {"as_of": asof.isoformat(), "metrics": metrics}
    merged = {}
    for stock in stocks:
        ticker = stock["ticker"]
        item = flow_cache.get(ticker) or {}
        try:
            cached_day = dt.date.fromisoformat(item.get("as_of", ""))
            age = (asof - cached_day).days
            metrics = item.get("metrics", {})
            if 0 <= age <= 7 and metrics.get("investor_flow_sessions") == 5:
                merged[ticker] = metrics
        except Exception:
            continue
    flow_cache = {ticker: item for ticker, item in flow_cache.items() if ticker in merged}
    KIS_FLOW_CACHE_FILE.write_text(
        json.dumps(flow_cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    note = (
        f"KIS 외국인·기관 5거래일 수급: 이번 회차 {len(selected)}개 중 신규 {len(results)}개사, "
        f"최근 7일 이내 유효 캐시 포함 {len(merged)}개사 / 오류·자료부족 {errors}개사"
    )
    print("[KIS] " + note, flush=True)
    return merged, note

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
    """Return weighted score and fraction of the component's own weight observed."""
    usable = [(v, w) for v, w in parts if v is not None and math.isfinite(v)]
    if not usable:
        return None, 0.0
    observed_weight = sum(w for _, w in usable)
    score = sum(v*w for v, w in usable) / observed_weight
    return round(score, 1), observed_weight / sum(w for _, w in parts) * 100

def grade_for(score):
    if score is None:
        return None
    return "S" if score >= 90 else "A" if score >= 80 else "B" if score >= 70 else "C" if score >= 60 else "D"

def main():
    asof, raw = latest_krx_rows()
    all_stocks = normalize(raw)
    index_history = OUT / "index_history"
    index_history.mkdir(exist_ok=True)
    kospi = None
    try:
        kospi = latest_krx_kospi(asof)
        index_day = dt.date.fromisoformat(kospi["date"])
        (index_history / f"{index_day:%Y%m%d}.json").write_text(json.dumps(kospi, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[KOSPI] {kospi['date']} 종가 {kospi['close']}", flush=True)
    except Exception as exc:
        print(f"[KOSPI] 지수 데이터 미확보: {str(exc)[:180]}", flush=True)
    kospi_history_sessions = backfill_kospi_history(asof, index_history, target_sessions=61, max_calendar_days=110)
    if len(all_stocks) < 300:
        raise RuntimeError(f"KRX 정상 종목 수 부족: {len(all_stocks)}")
    cap_covered = [x for x in all_stocks if x.get("market_cap") is not None and x["market_cap"] > 0]
    if len(cap_covered) < 300:
        raise RuntimeError(f"시가총액 데이터가 있는 종목이 300개 미만입니다: {len(cap_covered)}개. 시총 상위 300개 분석을 보류합니다.")
    # Save the full market snapshot so daily universe membership can change.
    history = OUT / "history"
    history.mkdir(exist_ok=True)
    (history / f"{asof:%Y%m%d}.json").write_text(json.dumps(all_stocks, ensure_ascii=False), encoding="utf-8")
    # A single latest-day snapshot is not enough for momentum. Backfill real
    # historical KRX sessions before calculating 5/20/60-session returns.
    history_sessions_available = backfill_krx_history(asof, history, target_sessions=61, max_calendar_days=110)
    stocks = sorted(cap_covered, key=lambda x: x["market_cap"], reverse=True)[:300]
    sector_map = load_sector_classification()
    for stock in stocks:
        metadata = sector_map.get(stock["ticker"])
        if metadata:
            stock.update(metadata)
        else:
            # Last-resort classification uses only an actual KRX daily sector field.
            fallback, confidence = classify_sector(stock.get("sector_raw"))
            stock["sector"] = fallback
            stock["sector_source"] = "KRX daily field" if fallback else None
            stock["sector_confidence"] = confidence
            stock["sector_industry"] = None
    history_files = sorted(history.glob("*.json"))[-160:]
    snapshots = []
    for path in history_files:
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
        stock["history_observations"] = len(closes)
        stock["momentum_5d"] = (stock["close"] / closes[-6] - 1) * 100 if len(closes) >= 6 and closes[-6] else None
        stock["momentum_20d"] = (stock["close"] / closes[-21] - 1) * 100 if len(closes) >= 21 and closes[-21] else None
        stock["momentum_60d"] = (stock["close"] / closes[-61] - 1) * 100 if len(closes) >= 61 and closes[-61] else None
        changes = [x.get("change_pct") for x in series[-20:] if x.get("change_pct") is not None]
        stock["volatility_20d"] = statistics.pstdev(changes) if len(changes) >= 5 else None

    investor_flows, kis_note = collect_kis_investor_flows(stocks, asof)
    analyst_data, analyst_note = load_and_score_consensus(stocks, asof)
    for stock in stocks:
        stock.update(investor_flows.get(stock["ticker"], {}))

    financial, dart_note = collect_dart(stocks)
    dart_sector_map, sector_note = load_dart_sector_classification(stocks)
    for stock in stocks:
        official_sector = dart_sector_map.get(stock["ticker"])
        if official_sector:
            stock.update(official_sector)
    for stock in stocks:
        metrics = financial.get(stock["ticker"], {})
        stock.update(metrics)
        stock["financial_metrics_available"] = has_financial_metrics(metrics)
        market_cap = stock.get("market_cap")
        net_income = metrics.get("net_income")
        equity_total = metrics.get("equity_total")
        stock["per"], stock["pbr"] = calculate_valuation(
            market_cap, net_income, equity_total, metrics.get("financial_currency")
        )
        stock["valuation_as_of"] = asof.isoformat() if stock["per"] is not None or stock["pbr"] is not None else None

    score_maps = {
        "roe": score_field(stocks, "roe_pct"),
        "sales_growth": score_field(stocks, "sales_growth_pct"),
        "op_growth": score_field(stocks, "operating_profit_growth_pct"),
        "momentum20": score_field(stocks, "momentum_20d"),
        "momentum60": score_field(stocks, "momentum_60d"),
        "momentum5": score_field(stocks, "momentum_5d"),
        "foreign_flow": score_field(stocks, "foreign_flow_5d_pct"),
        "institution_flow": score_field(stocks, "institution_flow_5d_pct"),
        "liquidity": score_field(stocks, "trading_value"),
        "analyst_rating": score_field(stocks, "analyst_rating_score"),
        "analyst_upside": score_field(stocks, "analyst_upside_pct"),
        "analyst_revision": score_field(stocks, "analyst_target_revision_pct"),
        "volatility": score_field(stocks, "volatility_20d", reverse=True),
        "per": score_field(stocks, "per", reverse=True),
        "pbr": score_field(stocks, "pbr", reverse=True),
    }

    for x in stocks:
        t = x["ticker"]
        fin, fin_cov = weighted_score([
            (score_maps["roe"].get(t), 50),
            (score_maps["sales_growth"].get(t), 25),
            (score_maps["op_growth"].get(t), 25),
        ])
        growth, growth_cov = weighted_score([
            (score_maps["sales_growth"].get(t), 50),
            (score_maps["op_growth"].get(t), 50),
        ])
        # Momentum must have an actual 20-trading-day price observation.
        # Liquidity alone must never create a momentum score.
        mom_parts = [
            (score_maps["momentum60"].get(t), 60),
            (score_maps["momentum20"].get(t), 20),
            (score_maps["momentum5"].get(t), 10),
            (score_maps["liquidity"].get(t), 5),
            (score_maps["volatility"].get(t), 5),
        ]
        mom, mom_cov = weighted_score(mom_parts)
        if x.get("momentum_60d") is None:
            mom, mom_cov = None, 0.0

        valuation, valuation_cov = weighted_score([
            (score_maps["per"].get(t), 50),
            (score_maps["pbr"].get(t), 50),
        ])
        components = {
            "financial": fin, "growth": growth, "momentum": mom,
            "foreign_flow": score_maps["foreign_flow"].get(t), "institution_flow": score_maps["institution_flow"].get(t),
            "valuation": valuation, "analyst_outlook": x.get("analyst_consensus_score"),
        }
        component_coverage = {
            "financial": round(fin_cov, 1), "growth": round(growth_cov, 1),
            "momentum": round(mom_cov, 1),
            "foreign_flow": 100 if x.get("foreign_flow_5d_pct") is not None else 0,
            "institution_flow": 100 if x.get("institution_flow_5d_pct") is not None else 0,
            "valuation": round(valuation_cov, 1), "analyst_outlook": x.get("analyst_consensus_coverage_pct", 0),
        }
        # The approved seven category weights remain unchanged.
        category_weights = {
            "financial": 20, "growth": 20, "momentum": 15,
            "foreign_flow": 15, "institution_flow": 10,
            "valuation": 10, "analyst_outlook": 10,
        }
        score_parts = [(components[k], category_weights[k] * component_coverage[k] / 100) for k in category_weights if components[k] is not None and component_coverage[k] > 0]
        effective_weights = [w for _, w in score_parts]
        provisional_score = round(sum(v*w for v, w in score_parts) / sum(effective_weights), 1) if effective_weights else None
        covered_points = sum(category_weights[k] * component_coverage[k] / 100 for k in category_weights)
        coverage_pct = round(covered_points, 1)
        eligible = coverage_pct >= 99.99 and provisional_score is not None
        x["component_scores"] = components
        x["foreign_flow_score"] = components["foreign_flow"]
        x["institution_flow_score"] = components["institution_flow"]
        x["component_coverage_pct"] = component_coverage
        x["score_coverage_pct"] = coverage_pct
        x["provisional_score"] = provisional_score
        x["score"] = provisional_score if eligible else None
        x["grade"] = grade_for(provisional_score) if eligible else None
        x["provisional_grade"] = grade_for(provisional_score) if not eligible else None
        x["official_recommendation_eligible"] = eligible
        x["status"] = "공식 추천 심사 가능" if eligible else "잠정 평가·공식추천 제외"
        x["reason"] = "확보된 재무·성장 데이터의 상대평가. 60거래일 모멘텀 및 미연결 항목은 점수에 포함하지 않음"
        x["risk_factors"] = [label for key, label in [
            ("roe_pct", "ROE 자료 부족"), ("sales_growth_pct", "매출성장 자료 부족"),
            ("operating_profit_growth_pct", "영업이익 성장 자료 부족"),
            ("momentum_60d", "60거래일 주가 이력 부족"),
            ("foreign_flow_5d_pct", "외국인 수급 자료 부족"),
            ("institution_flow_5d_pct", "기관 수급 자료 부족"),
            ("per", "PER 산출 자료 부족 또는 적자"),
            ("pbr", "PBR 산출 자료 부족 또는 자본잠식"),
        ] if x.get(key) is None]
        x["financial_score"] = fin
        x["growth_score"] = growth
        x["momentum_score"] = mom

    # Isolated v3.3 candidate: exact OpenDART industry-code peers only.
    # Preferred shares must not inflate the peer count of an issuer.
    financial_observations = load_financial_observations()
    financial_period = str(dt.date.today().year - 1) + "-12"
    candidate_peer_rows = []
    for item in stocks:
        if item["ticker"] in PREFERRED_SHARE_PARENT:
            continue
        candidate_peer_rows.append({
            "ticker": item["ticker"],
            "industry_code": item.get("sector_industry_code"),
            "industry_confidence": item.get("sector_confidence"),
            "financial_model": financial_model_for(item["ticker"], item.get("sector_industry_code"), item.get("sector")),
            "financial_period": financial_period,
            "financial_observations": financial_observations.get(item["ticker"]),
            "industry_metrics": industry_metrics_for_scoring(
                admitted_industry_metrics(item.get("industry_metrics"), item.get("industry_metric_quality") or {}, financial_period[:4]),
                item.get("sector_industry_code"), item.get("sector")),
        })
    # Non-listed financial entities are comparison-only, never recommendation candidates.
    candidate_peer_rows.extend(external_financial_peers(listed_records=financial_observations))
    for item in stocks:
        if item["ticker"] in PREFERRED_SHARE_PARENT:
            relative = {"status": "전략 제외", "official_score": None, "provisional_score": None,
                        "coverage_pct": 0, "details": {}}
        else:
            relative = score_industry_relative(candidate_peer_rows, item["ticker"])
        item["v33_candidate"] = aggregate_candidate(
            item.get("component_scores", {}),
            item.get("component_coverage_pct", {}),
            relative,
        )

    # Category lists only include stocks with real data for that category.
    def top(field, coverage_field=None, minimum_coverage=0):
        pool = [x for x in stocks if x.get(field) is not None and (coverage_field is None or x.get(coverage_field, 0) >= minimum_coverage)]
        return sorted(pool, key=lambda z: z[field], reverse=True)[:15]

    official = top("score", "score_coverage_pct", 99.99)
    # Intersection: official overall TOP15 stocks with a positive, explicitly
    # documented average target-price revision from verified recent reports.
    analyst_upgrades_in_top15 = [
        x for x in official
        if x.get("analyst_target_revision_pct") is not None
        and x.get("analyst_target_revision_pct") > 0
    ]
    lists = {
        "overall": official,
        "financial": top("financial_score", "component_coverage_pct" if False else None),
        "growth": top("growth_score"),
        "undervalued": sorted([x for x in stocks if x.get("component_scores", {}).get("valuation") is not None], key=lambda z: z["component_scores"]["valuation"], reverse=True)[:15],
        "momentum": top("momentum_score"),
        "foreign_flow": top("foreign_flow_score"),
        "institution_flow": top("institution_flow_score"),
    }

    perf_file = OUT / "recommendation_history.json"
    try:
        perf = json.loads(perf_file.read_text(encoding="utf-8"))
        if not isinstance(perf, list):
            perf = []
    except Exception:
        perf = []
    # Migrate the last published recommendation snapshot into the strategy-aware ledger
    # before today's latest.json is replaced. This preserves the original recommendation date/price.
    previous_latest = {}
    try:
        previous_latest = json.loads((OUT / "latest.json").read_text(encoding="utf-8"))
    except Exception:
        previous_latest = {}
    previous_day = previous_latest.get("as_of")
    previous_lists = previous_latest.get("lists", {})
    if previous_day and previous_lists:
        perf = update_recommendation_performance(
            perf, history, index_history, as_of=previous_day, lists=previous_lists
        )
    perf = update_recommendation_performance(
        perf, history, index_history, as_of=asof.isoformat(), lists=lists
    )
    perf_file.write_text(json.dumps(perf, ensure_ascii=False, indent=2), encoding="utf-8")
    performance_summary = build_performance_summary(perf, as_of=asof.isoformat())
    (OUT / "recommendation_performance_summary.json").write_text(
        json.dumps(performance_summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    def compact(items, list_key):
        keys = ["ticker", "name", "sector", "sector_raw", "sector_industry", "sector_industry_code", "sector_source", "sector_confidence", "close", "change_pct", "market_cap", "per", "pbr", "valuation_as_of", "net_income", "equity_total", "score", "provisional_score", "score_coverage_pct", "grade", "provisional_grade", "status", "official_recommendation_eligible", "component_scores", "component_coverage_pct", "industry_metrics", "industry_metric_sources", "capital_metric_audit", "v33_candidate", "financial_score", "growth_score", "momentum_score", "foreign_flow_score", "institution_flow_score", "roe_pct", "sales_growth_pct", "operating_profit_growth_pct", "momentum_5d", "momentum_20d", "momentum_60d", "history_observations", "trading_value", "foreign_net_buy_qty_5d", "institution_net_buy_qty_5d", "foreign_flow_5d_pct", "institution_flow_5d_pct", "investor_flow_as_of", "investor_flow_sessions", "reason", "risk_factors", "strategy_excluded", "strategy_exclusion_reason", "analyst_report_count", "analyst_broker_count", "analyst_avg_target_price", "analyst_avg_upside_pct", "analyst_rating_score", "analyst_consensus_score", "analyst_consensus_coverage_pct", "analyst_latest_report_date", "analyst_target_revision_pct", "analyst_recent_reports", "analyst_monthly_report_counts", "analyst_sources"]
        out = []
        for x in items:
            row = {k: x.get(k) for k in keys}
            if list_key == "financial": row["list_score"] = x.get("financial_score"); row["list_coverage_pct"] = x.get("component_coverage_pct", {}).get("financial", 0)
            elif list_key == "growth": row["list_score"] = x.get("growth_score"); row["list_coverage_pct"] = x.get("component_coverage_pct", {}).get("growth", 0)
            elif list_key == "momentum": row["list_score"] = x.get("momentum_score"); row["list_coverage_pct"] = x.get("component_coverage_pct", {}).get("momentum", 0)
            elif list_key == "foreign_flow": row["list_score"] = x.get("foreign_flow_score"); row["list_coverage_pct"] = x.get("component_coverage_pct", {}).get("foreign_flow", 0)
            elif list_key == "institution_flow": row["list_score"] = x.get("institution_flow_score"); row["list_coverage_pct"] = x.get("component_coverage_pct", {}).get("institution_flow", 0)
            elif list_key == "undervalued": row["list_score"] = x.get("component_scores", {}).get("valuation"); row["list_coverage_pct"] = x.get("component_coverage_pct", {}).get("valuation", 0)
            elif list_key == "v33_official": row["list_score"] = x.get("v33_candidate", {}).get("score"); row["list_coverage_pct"] = x.get("v33_candidate", {}).get("coverage_pct", 0)
            elif list_key == "v33_provisional": row["list_score"] = x.get("v33_candidate", {}).get("provisional_score"); row["list_coverage_pct"] = x.get("v33_candidate", {}).get("coverage_pct", 0)
            else: row["list_score"] = x.get("score"); row["list_coverage_pct"] = x.get("score_coverage_pct", 0)
            out.append(row)
        return out

    # Independent v3.3 TOP15 outputs. They are separate from the v3.2
    # recommendation lists and only include official candidates with full coverage.
    v33_official = sorted(
        [x for x in stocks if x.get("v33_candidate", {}).get("official_recommendation_eligible")
         and x.get("v33_candidate", {}).get("score") is not None],
        key=lambda x: (-x["v33_candidate"]["score"], x["ticker"]),
    )[:15]
    v33_provisional = sorted(
        [x for x in stocks if x.get("v33_candidate", {}).get("provisional_score") is not None
         and not x.get("v33_candidate", {}).get("official_recommendation_eligible")
         and x.get("v33_candidate", {}).get("status") != "전략 제외"],
        key=lambda x: (-x["v33_candidate"]["provisional_score"], -x["v33_candidate"]["coverage_pct"], x["ticker"]),
    )[:15]

    sector_groups = {}
    for stock in stocks:
        if stock.get("score") is None or not stock.get("sector"):
            continue
        sector_groups.setdefault(stock["sector"], []).append(stock)
    sector_top5 = {
        sector: compact(sorted(items, key=lambda item: item["score"], reverse=True)[:5], "overall")
        for sector, items in sorted(sector_groups.items())
    }

    def average_metric(items, key):
        values = [float(item[key]) for item in items if item.get(key) is not None and math.isfinite(float(item[key]))]
        return round(sum(values) / len(values), 2) if values else None

    sector_summary = {}
    sector_names = sorted({x.get("sector") for x in stocks if x.get("sector")})
    for sector in sector_names:
        items = [x for x in stocks if x.get("sector") == sector]
        scored = [x for x in items if x.get("score") is not None]
        sector_summary[sector] = {
            "stock_count": len(items),
            "scored_count": len(scored),
            "average_score": average_metric(scored, "score"),
            "advancer_pct": round(100 * sum(1 for x in items if (x.get("change_pct") or 0) > 0) / len(items), 1) if items else None,
            "average_change_pct": average_metric(items, "change_pct"),
            "average_foreign_flow_5d_pct": average_metric(items, "foreign_flow_5d_pct"),
            "average_institution_flow_5d_pct": average_metric(items, "institution_flow_5d_pct"),
            "average_analyst_upside_pct": average_metric(items, "analyst_avg_upside_pct"),
        }

    result = {
        "as_of": asof.isoformat(),
        "market": {"kospi": kospi.get("close") if kospi else None, "kospi_change_pct": kospi.get("change_pct") if kospi else None, "analyzed_count": len(stocks), "advancers": sum(1 for x in stocks if (x.get("change_pct") or 0) > 0), "decliners": sum(1 for x in stocks if (x.get("change_pct") or 0) < 0)},
        "lists": {k: compact(v, k) for k, v in lists.items()},
        "candidate_models": {
            "3.3-candidate": {
                "status": "개발 후보 · 미배포",
                "official_top15": compact(v33_official, "v33_official"),
                "provisional_top15": compact(v33_provisional, "v33_provisional"),
                "official_eligible_count": sum(1 for x in stocks if x.get("v33_candidate", {}).get("official_recommendation_eligible")),
                "industry_peer_group_count": len({x.get("sector_industry_code") for x in stocks if x.get("sector_industry_code") and x.get("sector_confidence") in ("high", "verified")}),
                "industry_relative_complete_count": sum(1 for x in stocks if x.get("v33_candidate", {}).get("industry_relative", {}).get("status") == "산출 완료"),
                "note": "v3.2 운영 추천목록과 분리. 공식 TOP15는 8개 평가영역의 데이터 충족률이 모두 100%인 종목만 포함하며, 잠정 TOP15는 별도 표시."
            }
        },
        "sector_top5": sector_top5,
        "sector_summary": sector_summary,
        "top15": compact(official, "overall"),
        "analyst_upgrades_in_top15": compact(analyst_upgrades_in_top15, "overall"),
        "performance": {"snapshots": len(perf), "kospi_history_sessions": kospi_history_sessions, "note": "추천일 종가 기준 실제 후속 거래일 종가로 1주(5거래일)·1개월(20거래일)·3개월(60거래일) 성과를 계산합니다. 7개 전략별 평균수익률, KOSPI 초과수익률, 절대수익 성공률 및 시장초과 성공률을 추적합니다."},
        "data_quality": {"label": "v3.2 베타 · 시가총액 상위 300개 · 가격 이력 누적", "note": dart_note + ". " + sector_note + ". " + kis_note + ". " + analyst_note + ". PER/PBR은 KRX 시가총액과 OpenDART 최신 연간 순이익·자본총계로 산출하며 적자·자본잠식은 제외합니다.", "official_top15_count": len(official), "sector_classified_count": sum(1 for x in stocks if x.get("sector")), "sector_unclassified_count": sum(1 for x in stocks if not x.get("sector")), "sector_classification_pct": round(100 * sum(1 for x in stocks if x.get("sector")) / len(stocks), 1) if stocks else 0, "sector_classification_source_count": sum(1 for x in stocks if x.get("sector")), "sector_classification_sources": {"opendart_industry_code": sum(1 for x in stocks if x.get("sector_source") == "OpenDART industry code"), "fdr_krx_desc": sum(1 for x in stocks if x.get("sector_source") == "KRX-DESC"), "same_issuer_ordinary_share": sum(1 for x in stocks if x.get("sector_source") == "Same issuer ordinary share"), "manual_verified_company_mapping": sum(1 for x in stocks if x.get("sector_source") == "Manual verified company mapping")}, "sector_count": len(sector_summary), "coverage_gate": "7개 평가영역의 실제 확보 가중치가 100%일 때만 공식 추천 점수/등급 부여", "financial_universe_batch": FINANCIAL_UNIVERSE, "financial_universe_total": len(stocks), "market_cap_covered_count": len(cap_covered), "universe_limit": 300, "history_sessions_available": history_sessions_available, "history_sessions_required": 61, "history_progress_pct": round(min(history_sessions_available, 61) / 61 * 100, 1), "kis_flow_coverage_count": len(investor_flows), "foreign_flow_coverage_count": sum(1 for x in stocks if x.get("foreign_flow_5d_pct") is not None), "institution_flow_coverage_count": sum(1 for x in stocks if x.get("institution_flow_5d_pct") is not None), "analyst_report_count": sum(int(x.get("analyst_report_count", 0) or 0) for x in analyst_data.values()), "analyst_covered_stock_count": len(analyst_data), "analyst_three_broker_count": sum(1 for x in analyst_data.values() if x.get("analyst_broker_count", 0) >= 3), "analyst_full_factor_coverage_count": sum(1 for x in analyst_data.values() if x.get("analyst_consensus_coverage_pct", 0) >= 99.99), "analyst_revision_covered_count": sum(1 for x in analyst_data.values() if x.get("analyst_target_revision_pct") is not None), "analyst_upgrades_in_top15_count": len(analyst_upgrades_in_top15)},
        "providers": {"krx": "connected", "kospi_index": "connected" if kospi else "configured_no_data", "opendart": "connected" if financial else ("configured_no_data" if DART_KEY else "not_configured"), "investor_flows": "connected" if investor_flows else ("configured_no_data" if os.getenv("KIS_APP_KEY") and os.getenv("KIS_APP_SECRET") else "not_configured"), "valuation": "connected" if any(x.get("per") is not None or x.get("pbr") is not None for x in stocks) else "configured_no_data", "analyst_consensus": "connected" if analyst_data else "configured_no_data"},
        "model": {"version": "3.2-beta", "candidate_models": {"3.3-candidate": {"status": "개발 후보 · 미배포", "weights": {"financial_health_profitability": 20, "growth": 15, "price_momentum": 10, "foreign_flow": 10, "institution_flow": 10, "valuation_per_pbr": 15, "broker_outlook": 10, "industry_relative": 10}, "note": "v3.2 점수·TOP15를 변경하지 않는 별도 후보 데이터. 업종 상대평가는 정확히 일치하는 OpenDART 업종코드 peer만 사용. candidate_models.3.3-candidate에서 공식/잠정 TOP15를 분리 제공."}}, "weights": {"financial_health_profitability": 20, "growth": 20, "price_momentum": 15, "foreign_flow": 15, "institution_flow": 10, "valuation_per_pbr": 10, "broker_outlook": 10}, "grade_thresholds": {"S": 90, "A": 80, "B": 70, "C": 60, "D": "below_60"}, "grade_statuses": {"insufficient_data": "데이터 부족", "strategy_excluded": "전략 제외"}, "note": "확정 100점 배점 유지. 부분 데이터는 provisional_score로만 표시하고 공식 score/grade를 부여하지 않음. 모멘텀은 현재 종가를 포함해 61개 거래일 종가(직전 60거래일 비교)가 누적되어야 산출."}
    }
    (OUT / "latest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[완료] v3.2-beta {asof}: KRX {len(stocks)}개 / DART 재무 {len(financial)}개 / 공식추천 가능 {len(official)}개", flush=True)


if __name__ == "__main__":
    main()
