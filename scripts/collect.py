#!/usr/bin/env python3
"""Q Stone Park KOSPI screener.
KRX supplies daily market data. OpenDART supplies filed financial indicators when DART_AUTH_KEY is configured.
Investor flows, PER/PBR and analyst consensus are deliberately not fabricated: they require additional licensed/provider APIs.
"""
import os, json, math, statistics, datetime as dt, io, zipfile
from pathlib import Path
import requests
import xml.etree.ElementTree as ET

KRX_URL = os.getenv("KRX_API_BASE", "https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd")
KRX_KEY = os.environ["KRX_AUTH_KEY"].strip()
DART_KEY = os.getenv("DART_AUTH_KEY", "").strip()
OUT = Path("data")
OUT.mkdir(exist_ok=True)
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "QStonePark-StockAnalyzer/2.0"})

def parse_rows(payload):
    if isinstance(payload, list): return payload
    for key in ("OutBlock_1", "output", "data", "result"):
        if isinstance(payload, dict) and isinstance(payload.get(key), list): return payload[key]
    return None

def get_krx_day(day):
    resp = SESSION.get(KRX_URL, headers={"AUTH_KEY": KRX_KEY, "Content-Type": "application/json"},
                       params={"basDd": day.strftime("%Y%m%d")}, timeout=45)
    if resp.status_code == 401:
        raise RuntimeError("KRX 401 Unauthorized: KRX_AUTH_KEY 또는 해당 API 서비스 승인/요청 방식 확인 필요")
    resp.raise_for_status()
    payload = resp.json()
    rows = parse_rows(payload)
    if rows is not None: return rows
    raise RuntimeError(f"KRX 응답 구조 오류: {str(payload)[:350]}")

def number(row, *keys):
    for key in keys:
        raw = row.get(key)
        if raw not in (None, ""):
            try: return float(str(raw).replace(",", "").replace("%", "").strip())
            except ValueError: pass
    return None

def string(row, *keys):
    for key in keys:
        if row.get(key) not in (None, ""): return str(row[key]).strip()
    return ""

def get_latest_market_data():
    last_error = None
    for offset in range(8):
        day = dt.date.today() - dt.timedelta(days=offset)
        try:
            rows = get_krx_day(day)
            if rows: return day, rows
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"최근 KRX 거래일 데이터를 가져오지 못했습니다: {last_error}")

def normalize_market(rows):
    stocks=[]
    for row in rows:
        code=string(row,"ISU_CD","isuCd","isu_cd")
        name=string(row,"ISU_NM","isuNm","isu_nm")
        close=number(row,"TDD_CLSPRC","tddClsprc","close")
        if not code or not name or not close or close <= 0: continue
        stocks.append({
            "ticker":code[-6:],"name":name,"close":close,
            "change_pct":number(row,"FLUC_RT","flucRt","change_pct"),
            "volume":number(row,"ACC_TRDVOL","accTrdVol","volume"),
            "trading_value":number(row,"ACC_TRDVAL","accTrdVal","trading_value"),
            "market_cap":number(row,"MKTCAP","mkcap","market_cap")
        })
    return stocks

def dart_get_corp_map():
    """Download DART's official stock-code -> corp-code mapping file."""
    url="https://opendart.fss.or.kr/api/corpCode.xml"
    resp=SESSION.get(url,params={"crtfc_key":DART_KEY},timeout=90)
    resp.raise_for_status()
    try:
        archive=zipfile.ZipFile(io.BytesIO(resp.content))
        xml_name=next(n for n in archive.namelist() if n.lower().endswith(".xml"))
        root=ET.fromstring(archive.read(xml_name))
    except Exception as exc:
        raise RuntimeError(f"OpenDART 고유번호 파일 해석 실패: {exc}")
    mapping={}
    for item in root.findall(".//list"):
        stock=(item.findtext("stock_code") or "").strip()
        corp=(item.findtext("corp_code") or "").strip()
        if stock and corp: mapping[stock]=corp
    return mapping

def fetch_dart_indicators(stocks, report_year):
    """Fetch filed profitability/growth indicators in batches of <=100 corporations."""
    corp_map=dart_get_corp_map()
    linked=[(s,corp_map.get(s["ticker"])) for s in stocks]
    linked=[(s,c) for s,c in linked if c]
    financial={}
    if not linked:
        return financial, "DART 종목코드 매핑 결과 없음"
    # The official API accepts up to 100 company codes in a request.
    for start in range(0,len(linked),100):
        batch=linked[start:start+100]
        codes=",".join(c for _,c in batch)
        for category in ("M210000","M230000"):
            resp=SESSION.get("https://opendart.fss.or.kr/api/fnlttCmpnyIndx.json",
                params={"crtfc_key":DART_KEY,"corp_code":codes,"bsns_year":str(report_year),
                        "reprt_code":"11011","idx_cl_code":category},timeout=60)
            resp.raise_for_status()
            payload=resp.json()
            status=payload.get("status")
            if status=="013": continue
            if status!="000":
                raise RuntimeError(f"OpenDART 응답 오류 {status}: {payload.get('message','')}")
            for item in payload.get("list",[]):
                ticker=(item.get("stock_code") or "").strip()
                name=(item.get("idx_nm") or "").strip()
                raw=item.get("idx_val")
                try: value=float(str(raw).replace(",",""))
                except (TypeError,ValueError): continue
                # DART ratio fields are commonly returned as decimal fractions.
                pct=value*100 if abs(value)<=5 else value
                financial.setdefault(ticker,{})[name]=pct
    return financial, f"OpenDART {report_year}년 사업보고서 지표 {len(financial)}개사"

def find_metric(metrics, candidates):
    for key,value in metrics.items():
        normalized=key.replace(" ","").lower()
        if any(candidate.replace(" ","").lower() in normalized for candidate in candidates):
            return value
    return None

def percentile(values, higher_is_better=True):
    valid=[v for v in values if v is not None and math.isfinite(v)]
    if not valid: return [None for _ in values]
    ordered=sorted(valid)
    output=[]
    for v in values:
        if v is None or not math.isfinite(v): output.append(None); continue
        # Mid-rank percentile gives ties the same score.
        below=sum(1 for x in ordered if x < v)
        equal=sum(1 for x in ordered if x == v)
        p=100*(below+(equal+1)/2)/len(ordered)
        output.append(p if higher_is_better else 100-p)
    return output

def main():
    asof, raw=get_latest_market_data()
    stocks=normalize_market(raw)
    if len(stocks)<30: raise RuntimeError(f"정상적인 KOSPI 데이터로 보기 어려운 종목 수: {len(stocks)}")

    history_dir=OUT/"history"; history_dir.mkdir(exist_ok=True)
    (history_dir/f"{asof:%Y%m%d}.json").write_text(json.dumps(stocks,ensure_ascii=False,indent=2),encoding="utf-8")
    snapshots=[]
    for path in sorted(history_dir.glob("*.json"))[-35:]:
        try: snapshots.append((path.stem,json.loads(path.read_text(encoding="utf-8"))))
        except Exception: pass
    by_ticker={}
    for date,items in snapshots:
        for item in items: by_ticker.setdefault(item["ticker"],[]).append((date,item))

    for s in stocks:
        series=by_ticker.get(s["ticker"],[])
        closes=[x[1]["close"] for x in series]
        s["momentum_20d"]=(s["close"]/closes[-21]-1)*100 if len(closes)>=21 and closes[-21] else None
        s["momentum_5d"]=(s["close"]/closes[-6]-1)*100 if len(closes)>=6 and closes[-6] else None
        changes=[x[1].get("change_pct") for x in series[-20:] if x[1].get("change_pct") is not None]
        s["volatility_20d"]=statistics.pstdev(changes) if len(changes)>=5 else None

    dart_message="OpenDART 미연결: DART_AUTH_KEY 등록 시 재무지표 반영"
    dart_year=dt.date.today().year-1
    financial={}
    if DART_KEY:
        try:
            financial,dart_message=fetch_dart_indicators(stocks,dart_year)
        except Exception as exc:
            dart_message=f"OpenDART 수집 실패: {str(exc)[:180]}"
    for s in stocks:
        m=financial.get(s["ticker"],{})
        s["roe_pct"]=find_metric(m,["자기자본이익률","ROE"])
        s["sales_growth_pct"]=find_metric(m,["매출액증가율","매출증가율"])
        s["operating_profit_growth_pct"]=find_metric(m,["영업이익증가율"])
        s["financial_metrics_available"]=bool(m)

    # Cross-sectional percentile components. Unavailable data are omitted, never imputed.
    def pmap(field, reverse=False):
        vals=[x.get(field) for x in stocks]
        scores=percentile(vals,not reverse)
        return {x["ticker"]:score for x,score in zip(stocks,scores)}
    p20=pmap("momentum_20d")
    p5=pmap("momentum_5d")
    pv=pmap("trading_value")
    pvol=pmap("volatility_20d",True)
    pday=pmap("change_pct")
    proe=pmap("roe_pct")
    psales=pmap("sales_growth_pct")
    pop=pmap("operating_profit_growth_pct")

    for s in stocks:
        ticker=s["ticker"]
        tech_parts=[(p20[ticker],35),(p5[ticker],20),(pv[ticker],20),(pvol[ticker],15),(pday[ticker],10)]
        tech=[(v,w) for v,w in tech_parts if v is not None]
        s["technical_score"]=round(sum(v*w for v,w in tech)/sum(w for _,w in tech),1) if tech else None
        fin_parts=[(proe[ticker],35),(psales[ticker],30),(pop[ticker],35)]
        fin=[(v,w) for v,w in fin_parts if v is not None]
        s["financial_score"]=round(sum(v*w for v,w in fin)/sum(w for _,w in fin),1) if fin else None
        # Target model: fundamentals 25, foreign 15, institutions 15, momentum 15,
        # valuation 15, analyst consensus 15. Until approved providers are connected,
        # only fundamentals and momentum are scored; coverage is explicitly shown.
        model_parts=[
            (s["financial_score"],25),
            (None,15), # foreign investor flow provider not connected
            (None,15), # institutional flow provider not connected
            (p20[ticker],15),
            (None,15), # PER/PBR provider not connected
            (None,15)  # analyst consensus provider not connected
        ]
        available=[(v,w) for v,w in model_parts if v is not None]
        s["score"]=round(sum(v*w for v,w in available)/sum(w for _,w in available),1) if available else s["technical_score"]
        s["score_coverage_pct"]=round(sum(w for _,w in available),0)
        s["status"]="종합평가 일부항목 미연결" if s["score_coverage_pct"]<100 else "종합평가 완료"

    ranked=sorted(stocks,key=lambda x:(x.get("score") is not None,x.get("score") or -1),reverse=True)
    adv=sum(1 for x in stocks if (x.get("change_pct") or 0)>0)
    dec=sum(1 for x in stocks if (x.get("change_pct") or 0)<0)
    top=[]
    for x in ranked[:10]:
        top.append({k:x.get(k) for k in (
            "ticker","name","close","change_pct","score","score_coverage_pct","status",
            "momentum_20d","trading_value","technical_score","financial_score",
            "roe_pct","sales_growth_pct","operating_profit_growth_pct")})
    result={
        "as_of":asof.isoformat(),
        "market":{"kospi":None,"kospi_change_pct":None,"analyzed_count":len(stocks),"advancers":adv,"decliners":dec},
        "top10":top,
        "performance":{"avg_return_pct":None},
        "data_quality":{"label":"KRX 시세 수집 완료","note":f"{dart_message}. 외국인·기관 수급, PER/PBR, 증권사 목표주가는 아직 별도 공급자 미연결."},
        "providers":{"krx":"connected","opendart":"connected" if financial else ("configured_no_data" if DART_KEY else "not_configured"),
                     "investor_flows":"not_connected","valuation":"not_connected","analyst_consensus":"not_connected"},
        "model":{"version":"0.2","weights":{"fundamentals":25,"foreign_flow":15,"institution_flow":15,"momentum":15,"valuation":15,"analyst_consensus":15},
                 "note":"사용 가능한 항목만 가중치 재정규화. score_coverage_pct를 반드시 함께 확인."},
        "financial_year":dart_year if financial else None
    }
    (OUT/"latest.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"{asof}: {len(stocks)} KOSPI stocks; DART mapped={len(financial)}; top10={len(top)}")

if __name__=="__main__": main()
