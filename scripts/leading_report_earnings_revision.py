"""Report-based earnings revision for the approved 2-point base outlook slot.

No cross-provider validation. Only explicit annual net-income forecast revisions
or like-for-like annual forecast table pairs are used. Preserve page and source.
Current-date score evidence only, no historical backfill or leading 30d substitution.
"""
import json,re,time,os,math
from pathlib import Path
from datetime import date,datetime,timedelta,timezone
from collections import defaultdict,Counter
from statistics import mean
from urllib.parse import urljoin,urlparse
from html.parser import HTMLParser
import requests
import fitz
from outlook_candidate import broker_key
from forecast_score_policy import forecast_fraction
KST=timezone(timedelta(hours=9))
NUM=r"[+-]?\d+(?:,\d{3})*(?:\.\d+)?"
METRIC=r"(지배주주(?:지분)?\s*(?:당기)?순이익|지배(?:주주)?\s*당기순이익|순이익\s*\(지배\)|지배순이익|당기\s*순이익|순이익)"
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
def num(x):
    try:
        v=float(str(x).replace(",","").strip())
        return v if math.isfinite(v) else None
    except (ValueError,TypeError):return None
def account(label):
    x=re.sub(r"\s","",label)
    return "owner_net_income" if x.startswith("지배") or x=="순이익(지배)" else "total_net_income" if x=="당기순이익" else "net_income_unspecified"
def change(old,new):
    if old>0 and new>=0:return 100*(new/old-1)
    den=abs(old)+abs(new)
    return 200*(new-old)/den if den else 0.0
def explicit(text,year,page):
    # Require annual year, net-income metric, explicit estimate/revision wording
    # and directional change. Never interpret YoY growth or target revision as earnings revision.
    s=re.sub(r"\s+"," ",text)
    pat=rf"(?<![\d.]){year}년(?:도)?\s*(?:연간\s*)?{METRIC}\s*(?:전망치|추정치|예상치|전망|추정)(?:를|을|은|는)?\s*(?:기존\s*대비\s*)?({NUM})\s*%\s*(상향|하향)(?:\s*조정)?"
    out=[]
    for m in re.finditer(pat,s):
        v=num(m[2])
        if v is None or v<0:continue
        out.append({"metric":account(m[1]),"period_end":f"{year}-12-31","value":v if m[3]=="상향" else -v,"page":page,"evidence":m[0],"kind":"explicit_report_revision"})
    return out
def metadata(text):
    units=set(re.findall(r"(?:단위\s*[:：]\s*|\(\s*)(백만원|억원|십억원|조원)(?=[,\s)\n]|$)",text))
    scopes=set(re.findall(r"(?:IFRS|K-IFRS|회계기준)\s*[-(]?\s*(연결|별도)|(?:연결|별도)\s*(?:기준|재무제표)",text,re.I))
    scopes.discard("")
    for m in re.finditer(r"(연결|별도)\s*(?:기준|재무제표)",text):scopes.add(m[1])
    return (next(iter(units)) if len(units)==1 else None,next(iter(scopes)) if len(scopes)==1 else None)
def year_header(v,year):
    x=re.sub(r"\s","",str(v or "")).upper().replace("(E)","E").replace("(F)","F")
    return x in {f"{y}{suffix}" for y in (str(year),str(year)[2:]) for suffix in ("E","F","년E","년F","년추정",".12E",".12F","A/E")} - {f"{y}A/E" for y in (str(year),str(year)[2:])}
def amount_table(table,page_text,year,page):
    if not table or len(table)<2:return []
    # Prefer the local table unit and scope, then unambiguous page metadata.
    local=" ".join(str(v or "") for r in table[:4] for v in r)
    u,s=metadata(local);pu,ps=metadata(page_text)
    unit=u or pu;scope=s or ps
    if not unit or not scope:return []
    headers=[(i,j) for i,r in enumerate(table[:5]) for j,v in enumerate(r) if year_header(v,year)]
    if len(headers)!=1:return []
    i,j=headers[0]
    out=[]
    for r in table[i+1:]:
        if j>=len(r) or not r:continue
        label=next((str(v).strip() for v in r[:j] if re.fullmatch(METRIC,str(v or "").strip())),None)
        if not label:continue
        v=num(r[j])
        if v is None:continue
        out.append({"metric":account(label),"period_end":f"{year}-12-31","amount":v,"unit":unit,"scope":scope,"page":page,"evidence":f"{label} | {year}E/F | {r[j]} | {unit} | {scope}","kind":"annual_forecast_amount"})
    return out
def layout_amounts(lines,year,page):
    """Read whitespace-aligned PDF text rows only when year and numeric columns
    can be uniquely paired. Header must carry actual/estimate suffix on target."""
    result=[]
    for i,line in enumerate(lines):
        tokens=line.split()
        if len(tokens)<3 or sum(year_header(t,year) for t in tokens)!=1:continue
        cols=[t for t in tokens if re.fullmatch(r"(?:20)?\d{2}(?:년)?(?:\.\d{2})?(?:\(?[AEF]\)?)?",t,re.I)]
        if len(cols)<3 or sum(year_header(t,year) for t in cols)!=1:continue
        j=next(k for k,t in enumerate(cols) if year_header(t,year))
        unit,scope=metadata("\n".join(lines[max(0,i-5):i+2]))
        if not unit or not scope:continue
        for row in lines[i+1:i+25]:
            if any(year_header(t,year) for t in row.split()):break
            m=re.fullmatch(rf"\s*{METRIC}\s+(.+?)\s*",row)
            if not m:continue
            vals=m[2].split()
            if len(vals)!=len(cols) or any(num(v) is None for v in vals):continue
            result.append({"metric":account(m[1]),"period_end":f"{year}-12-31","amount":num(vals[j]),"unit":unit,"scope":scope,"page":page,"evidence":f"{m[1]} | {cols[j]} | {vals[j]} | {unit} | {scope}","kind":"annual_forecast_amount","extraction":"aligned_text"})
    return result
class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.links=[];self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in ("a","iframe","embed"):
            a=dict(attrs);v=a.get("href") or a.get("src")
            if v:self.links.append(v)
    def handle_data(self,data):self.parts.append(data)
def safe_pdf(url):
    p=urlparse(url);h=p.hostname or ""
    return p.scheme=="https" and (h=="naver.com" or h.endswith(".naver.com") or h.endswith(".pstatic.net") or h=="pstatic.net") and p.path.lower().endswith(".pdf")
def norm(v):return re.sub(r"\s+","",str(v or "")).casefold()
def same_report(detail,report):
    # Only identity and publication date in the source response; no cross-provider check.
    if str(detail.get("nid") or "")!=str(report.get("research_id") or ""):return False
    if str(detail.get("itemCode") or "").zfill(6)!=str(report.get("ticker") or ""):return False
    if broker_key(detail.get("brokerName"))!=broker_key(report.get("broker")):return False
    d=str(detail.get("writeDate") or "")[:10].replace(".","-").replace("/","-")
    if re.fullmatch(r"\d{8}",d):d=d[:4]+"-"+d[4:6]+"-"+d[6:]
    return d==report.get("published_at")
def parse_document(body,year,diagnostics=None):
    out=[]
    with fitz.open(stream=body,filetype="pdf") as doc:
        for i,p in enumerate(doc):
            if i>=12:break
            text=p.get_text("text",sort=True)
            if diagnostics is not None:
                diagnostics["pages"]+=1
                diagnostics["text_pages"]+=bool(text.strip())
                diagnostics["net_income_pages"]+=("순이익" in text)
                diagnostics["annual_label_pages"]+=bool(re.search(rf"\b(?:{year}|{str(year)[2:]})\s*\(?[EF]\)?",text))
                u,sc=metadata(text);diagnostics["unit_pages"]+=bool(u);diagnostics["scope_pages"]+=bool(sc)
            out.extend(layout_amounts(text.splitlines(),year,i+1))
            out.extend(explicit(text,year,i+1))
            # Table parser is only used for pages with relevant annual labels.
            if (str(year) not in text and str(year)[2:]+"E" not in text and str(year)[2:]+"F" not in text) or "순이익" not in text:continue
            try:
                for strategy in ("lines","text"):
                    tables=p.find_tables(strategy=strategy).tables
                    if diagnostics is not None:diagnostics["tables_"+strategy]+=len(tables)
                    for t in tables:
                        v=amount_table(t.extract(),text,year,i+1);out.extend(v)
                        if diagnostics is not None:diagnostics["value_rows_"+strategy]+=len(v)
            except (ValueError,RuntimeError,AttributeError):pass
    return out
def choose_pairs(rows,asof):
    # Prefer explicit latest report revision per broker; otherwise compare two
    # consecutive dated observations of same metric/period/unit/scope.
    grouped=defaultdict(list)
    for r in rows:
        d=date.fromisoformat(r["published_at"])
        if 0<=(asof-d).days<=180:grouped[broker_key(r["broker"])].append(r)
    pairs=[]
    for b,rs in grouped.items():
        if not b:continue
        ds=sorted({r["published_at"] for r in rs},reverse=True)
        if (asof-date.fromisoformat(ds[0])).days>90:continue
        latest=[r for r in rs if r["published_at"]==ds[0]]
        # Parent-attributable net income preferred, then explicitly total,
        # then unspecified label. No mixing of these accounting definitions.
        for metric in ("owner_net_income","total_net_income","net_income_unspecified"):
            a=[r for r in latest if r["metric"]==metric and r["kind"]=="explicit_report_revision"]
            if a and len({(r["period_end"],r["value"]) for r in a})==1:
                pairs.append({**a[0],"broker_key":b,"method":"report_explicit_revision"});break
            a=[r for r in latest if r["metric"]==metric and r["kind"]=="annual_forecast_amount"]
            if not a or len({(r["period_end"],r["scope"],r["unit"],r["amount"]) for r in a})!=1:continue
            current=a[0]
            # Unspecified net income label is not enough to pair separate reports.
            if metric=="net_income_unspecified":continue
            prior=[r for r in rs if r["published_at"]<ds[0] and r["kind"]=="annual_forecast_amount" and all(r[k]==current[k] for k in ("metric","period_end","unit","scope"))]
            if not prior:continue
            pd=max(r["published_at"] for r in prior);prior=[r for r in prior if r["published_at"]==pd]
            if len({r["amount"] for r in prior})!=1:continue
            prev=prior[0]
            pairs.append({**current,"value":change(prev["amount"],current["amount"]),"broker_key":b,"method":"same_broker_report_pair","prior":prev});break
    # Do not combine inconsistent metrics or fiscal periods across brokers.
    for metric in ("owner_net_income","total_net_income","net_income_unspecified"):
        chosen=[r for r in pairs if r["metric"]==metric]
        if chosen:
            periods={r["period_end"] for r in chosen}
            if len(periods)==1:return chosen
    return []
def score(rows,asof):
    evidence=choose_pairs(rows,asof)
    if not evidence:return None
    v=mean(r["value"] for r in evidence);n=len(evidence)
    kind="broker_consensus" if n>=3 else "single_broker"
    return {"value":v,"broker_count":n,"source_kind":kind,"confidence":1 if n>=3 else .9,"points_out_of_2":round(2*forecast_fraction("earnings_revision",v,kind),6),"evidence":evidence,"status":"report_based_score_candidate","note":"No independent cross-provider verification; one or two brokers use conservative single-broker confidence."}
def main():
    out=Path("audit-leading-report-revision");out.mkdir(exist_ok=True)
    previous=read("outlook/summary.json");records=read("outlook/records.json")
    asof=date.fromisoformat(previous["forecast_asof"]);year=asof.year
    nav=read("roadmap/reports-2026-11-27.json")
    targets={r["ticker"] for r in records};by=defaultdict(lambda:defaultdict(list))
    for r in nav:
        if r["ticker"] not in targets or not r.get("research_id"):continue
        d=date.fromisoformat(r["published_at"])
        if 0<=(asof-d).days<=180:by[r["ticker"]][broker_key(r["broker"])].append(r)
    # Pilot: two recent reports per broker, up to two brokers per issuer.
    # Fixed cap avoids excessive requests, expands in a separate run.
    limit=int(os.getenv("REPORT_REVISION_LIMIT","60"))
    selected=[]
    for t in sorted(by):
        brokers=sorted(by[t].values(),key=lambda rs:max(r["published_at"] for r in rs),reverse=True)[:2]
        for rs in brokers:
            selected.extend(sorted(rs,key=lambda r:r["published_at"],reverse=True)[:2])
    # Round-robin issuer ordering so pilot covers more issuers, retaining pairs.
    per=defaultdict(list)
    for r in selected:per[r["ticker"]].append(r)
    chosen=[]
    for t in sorted(per):
        if len(chosen)+len(per[t])>limit:break
        chosen.extend(per[t])
    session=requests.Session();session.headers.update({"User-Agent":"Mozilla/5.0","Referer":"https://stock.naver.com/"})
    stats=Counter();errors=Counter();raw=[];stop=False
    for r in chosen:
        if stop:break
        nid=str(r["research_id"])
        if not nid.isdigit():errors["invalid_research_id"]+=1;continue
        url="https://stock.naver.com/api/stockSecurity/researches/v2/company/"+nid
        stats["attempted"]+=1
        try:
            h=session.get(url,timeout=(5,12),allow_redirects=False,headers={"Accept":"application/json","Referer":"https://stock.naver.com/research/company/"+nid})
            if h.status_code in (401,403,429):errors["http_"+str(h.status_code)]+=1;break
            h.raise_for_status();detail=h.json()
            if not isinstance(detail,dict):errors["detail_not_object"]+=1;continue
            if stats["attempted"]==1:print("REPORT DETAIL SCHEMA",json.dumps(sorted(detail),ensure_ascii=False),flush=True)
            if not same_report(detail,r):
                errors["detail_identity_missing"]+=1;continue
            stats["detail_identity_matched"]+=1
            page=Page();page.feed(str(detail.get("content") or ""))
            body=" ".join(page.parts)
            stats["detail_content_received"]+=bool(body.strip())
            vals=explicit(body,year,None)
            stats["explicit_content_values"]+=len(vals)
            attachment=detail.get("attachUrl")
            links=[attachment] if isinstance(attachment,str) and safe_pdf(attachment) else []
            if links:
                stats["pdf_link_found"]+=1
            if len(links)==1:
                with session.get(links[0],timeout=(5,20),allow_redirects=False,stream=True) as pdf:
                    if pdf.status_code in (401,403,429):errors["pdf_http_"+str(pdf.status_code)]+=1;stop=True;continue
                    pdf.raise_for_status();parts=[];size=0
                    for chunk in pdf.iter_content(65536):
                        size+=len(chunk)
                        if size>15_000_000:break
                        parts.append(chunk)
                    if size<=15_000_000:
                        data=b"".join(parts)
                        if data.startswith(b"%PDF"):
                            stats["pdf_read"]+=1
                            for x in parse_document(data,year,stats):vals.append({**x,"pdf_url":links[0]})
                        else:errors["not_pdf"]+=1
                    else:errors["pdf_size_limit"]+=1
            elif len(links)>1:errors["ambiguous_pdf_links"]+=1
            stats["report_with_values"]+=bool(vals);stats["value_rows"]+=len(vals)
            for v in vals:raw.append({**v,"ticker":r["ticker"],"broker":r["broker"],"published_at":r["published_at"],"source_ref":r["source_url"],"detail_url":url,"observed_at":datetime.now(KST).isoformat()})
        except (requests.RequestException,ValueError,RuntimeError,TypeError,AttributeError) as e:errors[type(e).__name__]+=1
        finally:
            if stats["attempted"]%10==0:print("REPORT REVISION PROGRESS",stats["attempted"],"/",len(chosen),flush=True)
            time.sleep(.6)
    by_t=defaultdict(list)
    for r in raw:by_t[r["ticker"]].append(r)
    admitted=0
    for row in records:
        z=score(by_t[row["ticker"]],asof)
        if z:
            row["slots"]["earnings_revision"]=z;admitted+=1
    fields=("rating","upside","target_revision","op_forecast_growth","earnings_revision")
    counts={k:sum(k in r["slots"] for r in records) for k in fields}
    summary={"target_count":len(records),"report_pilot_limit":limit,"selected_reports":len(chosen),"stats":dict(stats),"errors":dict(errors),"report_revision_scored_issuers":admitted,"counts":counts,"external_candidate_coverage_pct":100*sum(counts.values())/(5*len(records)),"official_integrated":False,"note":"Scored report revision candidates use 2-point existing forecast rule. Explicit numeric report values require no cross-check. PDF table parsing pilot is incomplete; missing stays missing. Current-date candidate only."}
    write(out/"summary.json",summary);write(out/"records.json",records);write(out/"extracted_values.json",raw)
    print("REPORT EARNINGS REVISION SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
