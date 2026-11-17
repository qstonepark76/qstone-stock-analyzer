#!/usr/bin/env python3
"""Fetch KRX KOSPI daily trading data and rank stocks using disclosed technical factors."""
import os, json, math, statistics, datetime as dt
from pathlib import Path
import requests

BASE = os.getenv("KRX_API_BASE", "https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd")
API_ID = os.getenv("KRX_API_ID", "sto/stk_bydd_trd")
AUTH_KEY = os.environ["KRX_AUTH_KEY"]
OUT = Path("data")
OUT.mkdir(exist_ok=True)

def get_day(day):
    url = BASE
    headers = {"AUTH_KEY": AUTH_KEY, "Content-Type": "application/json"}
    params = {"basDd": day.strftime("%Y%m%d")}
    resp = requests.get(url, headers=headers, params=params, timeout=40)
    resp.raise_for_status()
    payload = resp.json()
    if isinstance(payload, list): return payload
    for key in ("OutBlock_1", "output", "data", "result"):
        if isinstance(payload.get(key), list): return payload[key]
    # Surface provider errors rather than silently creating empty rankings.
    if payload.get("resultCode") not in (None, "00", "0"):
        raise RuntimeError(f"KRX 응답 오류: {payload}")
    raise RuntimeError(f"예상하지 못한 KRX 응답 구조: {str(payload)[:500]}")

def val(row, *keys):
    for k in keys:
        if k in row and row[k] not in (None, ""):
            s = str(row[k]).replace(",", "").replace("%", "").strip()
            try: return float(s)
            except ValueError: pass
    return None

def txt(row, *keys):
    for k in keys:
        if row.get(k) not in (None, ""): return str(row[k]).strip()
    return ""

def trading_day_data():
    # The latest KRX business-day data may not be published immediately after close.
    # Try today and up to 7 calendar days backward (weekends/holidays included).
    today = dt.date.today()
    last_error = None
    for offset in range(0, 8):
        day = today - dt.timedelta(days=offset)
        try:
            rows = get_day(day)
            if rows: return day, rows
        except Exception as exc: last_error = exc
    raise RuntimeError(f"최근 거래일 데이터를 가져오지 못했습니다: {last_error}")

def normalize(rows):
    out=[]
    for r in rows:
        code=txt(r,"ISU_CD","isuCd","isu_cd")
        name=txt(r,"ISU_NM","isuNm","isu_nm")
        # Skip rows without stock code/name; retain only common-stock-like KOSPI listings.
        if not code or not name: continue
        close=val(r,"TDD_CLSPRC","tddClsprc","close")
        if not close or close <= 0: continue
        out.append({
            "ticker":code[-6:],"name":name,
            "close":close,
            "change_pct":val(r,"FLUC_RT","flucRt","change_pct"),
            "volume":val(r,"ACC_TRDVOL","accTrdVol","volume"),
            "trading_value":val(r,"ACC_TRDVAL","accTrdVal","trading_value"),
            "market_cap":val(r,"MKTCAP","mkcap","market_cap"),
        })
    return out

def main():
    asof, raw = trading_day_data()
    stocks = normalize(raw)
    if len(stocks) < 30:
        raise RuntimeError(f"정상적인 KOSPI 종목 데이터로 보기 어려운 행 수: {len(stocks)}")
    # Archive one daily snapshot. Historical snapshots support later performance tracking.
    hist_dir=OUT/"history"; hist_dir.mkdir(exist_ok=True)
    hist_path=hist_dir/f"{asof:%Y%m%d}.json"
    hist_path.write_text(json.dumps(stocks,ensure_ascii=False,indent=2),encoding="utf-8")
    # Read up to 30 recent snapshots for technical features.
    snapshots=[]
    for p in sorted(hist_dir.glob("*.json"))[-30:]:
        try: snapshots.append((p.stem,json.loads(p.read_text(encoding="utf-8"))))
        except Exception: continue
    by_ticker={}
    for date, snap in snapshots:
        for item in snap: by_ticker.setdefault(item["ticker"],[]).append((date,item))
    scored=[]
    for s in stocks:
        series=by_ticker.get(s["ticker"],[])
        closes=[x[1]["close"] for x in series]
        # Score only available KRX market data. Missing financial/flow/consensus data are not fabricated.
        mom20=(s["close"]/closes[-21]-1)*100 if len(closes)>=21 and closes[-21] else None
        mom5=(s["close"]/closes[-6]-1)*100 if len(closes)>=6 and closes[-6] else None
        changes=[x[1].get("change_pct") for x in series[-20:] if x[1].get("change_pct") is not None]
        vol=statistics.pstdev(changes) if len(changes)>=5 else None
        # Cross-sectional percentile scores among available KOSPI names.
        scored.append({**s,"momentum_20d":mom20,"momentum_5d":mom5,"volatility_20d":vol})
    def percentile_map(field, reverse=False):
        vals=[x[field] for x in scored if x.get(field) is not None]
        vals.sort(reverse=reverse)
        result={}
        for x in scored:
            v=x.get(field)
            result[x["ticker"]]= (100*(vals.index(v)+1)/len(vals)) if v is not None and vals else None
        return result
    p20=percentile_map("momentum_20d")
    p5=percentile_map("momentum_5d")
    pv=percentile_map("trading_value")
    pvol=percentile_map("volatility_20d", reverse=True) # low volatility ranks higher
    pday=percentile_map("change_pct")
    for x in scored:
        components=[
            (p20.get(x["ticker"]),30),(p5.get(x["ticker"]),20),
            (pv.get(x["ticker"]),20),(pvol.get(x["ticker"]),15),
            (pday.get(x["ticker"]),15)
        ]
        available=[(v,w) for v,w in components if v is not None]
        x["score"]=round(sum(v*w for v,w in available)/sum(w for _,w in available),1) if available else None
        x["status"]="기술지표 기준" if len(available)==5 else "일부 지표 부족"
    ranked=sorted([x for x in scored if x["score"] is not None],key=lambda x:x["score"],reverse=True)
    adv=sum(1 for x in stocks if (x.get("change_pct") or 0)>0)
    dec=sum(1 for x in stocks if (x.get("change_pct") or 0)<0)
    # Keep a stable latest data contract; index level is omitted unless a separate index API is approved.
    result={
      "as_of":asof.isoformat(),
      "market":{"kospi":None,"kospi_change_pct":None,"analyzed_count":len(stocks),"advancers":adv,"decliners":dec},
      "top10":[{k:x.get(k) for k in ("ticker","name","close","change_pct","score","momentum_20d","trading_value","status")} for x in ranked[:10]],
      "performance":{"avg_return_pct":None},
      "data_quality":{"label":"KRX 시세 수집 완료","note":"주가·거래 지표 기반. 재무·외국인/기관 수급·목표주가 미연결."},
      "method":{"version":"0.1","score":"가용 기술지표의 가중평균 백분위. 누락 지표는 가중치 재정규화."}
    }
    (OUT/"latest.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"{asof}: {len(stocks)} stocks; top10={len(result['top10'])}")

if __name__=="__main__": main()
