"""Inspect real remaining income statement totals, and recover source documents
for new listings. Candidate evidence only; no label-only account admission.
"""
import sys,json,io,zipfile,re,time
from pathlib import Path
from datetime import date
from collections import defaultdict
import requests
from lxml import etree
sys.path.insert(0,"scripts");sys.path.insert(0,"audit_tools")
from own_forecast import fetch,read,DART_KEY
from fundamental_candidate import IDS
LABELS={"매출액","매출","수익(매출액)","영업수익","영업수익합계","영업이익","영업이익(손실)","영업손익","당기순이익","당기순이익(손실)","지배기업의소유주에게귀속되는당기순이익","지배기업소유주지분순이익"}
STANDARD={v for k in ("sales","op","net","owner_net") for v in IDS[k][1:]}
def totals(raw):
    rows=[]
    for r in raw:
        if r.get("sj_div") not in ("IS","CIS"):continue
        label=re.sub(r"\s+","",str(r.get("account_nm") or ""))
        if label in LABELS or r.get("account_id") in STANDARD:
            rows.append({k:r.get(k) for k in ("account_id","account_nm","account_detail","sj_div","currency","thstrm_nm","thstrm_amount","thstrm_add_amount","frmtrm_nm","frmtrm_amount","frmtrm_add_amount","rcept_no","bsns_year","reprt_code","corp_code")})
    return rows
def get_tables(receipt):
    p=requests.get("https://opendart.fss.or.kr/api/document.xml",params={"crtfc_key":DART_KEY,"rcept_no":receipt},timeout=(5,25),allow_redirects=False)
    p.raise_for_status()
    if len(p.content)>25_000_000:raise ValueError("document_size")
    tables=[]
    with zipfile.ZipFile(io.BytesIO(p.content)) as z:
        if sum(x.file_size for x in z.infolist())>80_000_000:raise ValueError("expanded_size")
        for member in z.infolist():
            if not member.filename.lower().endswith(".xml"):continue
            root=etree.fromstring(z.read(member),etree.XMLParser(recover=True,no_network=True,resolve_entities=False,load_dtd=False))
            if root is None:continue
            def tag(n):return n.tag.rsplit("}",1)[-1].upper() if isinstance(n.tag,str) else ""
            for table in (n for n in root.iter() if tag(n)=="TABLE"):
                rows=[[" ".join("".join(c.itertext()).split())[:300] for c in tr if tag(c) in ("TD","TH","TE","TU")] for tr in table.iter() if tag(tr)=="TR"]
                joined=" ".join(" ".join(row) for row in rows)
                if ("매출액" in joined or "영업수익" in joined) and ("영업이익" in joined or "당기순이익" in joined):
                    tables.append({"member":member.filename,"rows":rows[:80]})
                if len(tables)>=12:return tables
    return tables
def main():
    if not DART_KEY:raise SystemExit("DART credential unavailable")
    u=read("replay-source/universe.json");asof=date.fromisoformat(u["asof"])
    sources={r["ticker"]:r for r in read("replay-source/report.json")["records"]}
    gaps={r["ticker"]:r for r in read("gaps/records.json")}
    missing=defaultdict(list)
    for r in read("reuse/missing.json"):missing[r["ticker"]].append(r["metric"])
    out=Path("audit-forecast-account-recovery");out.mkdir(exist_ok=True)
    results=[]
    for t,metrics in sorted(missing.items()):
        s=sources[t];g=gaps.get(t,{});corp=s.get("corp_code") or g.get("corp_code")
        item={"ticker":t,"corp_code":corp,"metrics":metrics,"periods":[],"documents":[],"errors":[]}
        if corp and s["status"]=="source_received":
            annual=read("replay-source/source-rows/"+t+".json")
            item["periods"].append({"period":"2025FY","scope":s["scope"],"totals":totals(annual)})
            # Only gaps' current quarter data, not another broad retrospective run.
            for code,period in (("11014","2026Q3"),("11012","2026Q2")):
                if code=="11012" and "earnings_forecast_revision" not in metrics:continue
                try:
                    raw=fetch(corp,2026,code,s["scope"],asof)
                    item["periods"].append({"period":period,"scope":s["scope"],"totals":totals(raw),"raw_count":len(raw)})
                except (OSError,ValueError,KeyError) as e:item["errors"].append(type(e).__name__)
        elif corp:
            # Reuse financial statement candidates from the earlier run.
            for r in g.get("annual_candidates",[])+g.get("quarter_candidates",[]):
                item["periods"].append({"period":str(r["year"])+r.get("code","FY"),"scope":r["scope"],"totals":totals(r["rows"])})
            filings=[f for f in g.get("filings",[]) if str(f.get("corp_code"))==str(corp) and re.fullmatch(r"\d{14}",str(f.get("rcept_no"))) and str(f.get("rcept_dt",""))<=asof.strftime("%Y%m%d")]
            selected=[]
            for labels in (("증권신고서","투자설명서"),("감사보고서","사업보고서"),("분할",)):
                match=sorted((f for f in filings if any(k in str(f.get("report_nm")) for k in labels)),key=lambda f:str(f.get("rcept_dt")),reverse=True)
                if match and match[0]["rcept_no"] not in {f["rcept_no"] for f in selected}:selected.append(match[0])
            for f in selected:
                try:item["documents"].append({**f,"tables":get_tables(f["rcept_no"]),"status":"candidate_unverified"})
                except (OSError,ValueError,zipfile.BadZipFile,etree.XMLSyntaxError) as e:item["errors"].append(type(e).__name__)
                time.sleep(.25)
        else:item["errors"].append("issuer_identity_unresolved")
        results.append(item)
        print("ACCOUNT RECOVERY",t,json.dumps({"periods":[{"period":p["period"],"accounts":[[r["account_id"],r["account_nm"]] for r in p["totals"]]} for p in item["periods"]],"documents":len(item["documents"]),"errors":item["errors"]},ensure_ascii=False),flush=True)
        (out/"records.json").write_text(json.dumps(results,ensure_ascii=False,indent=2,allow_nan=False))
    summary={"target_issuers":len(results),"periods_with_totals":sum(bool(p["totals"]) for r in results for p in r["periods"]),"documents_with_tables":sum(bool(d["tables"]) for r in results for d in r["documents"]),"errors":sum(len(r["errors"]) for r in results),"admitted_forecasts":0,"warning":"New account definition, full-year period and correction/scope reconciliation needed before new forecasts are admitted."}
    (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print("ACCOUNT RECOVERY SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
