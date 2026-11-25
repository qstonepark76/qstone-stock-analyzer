"""Discover actual XBRL note contexts for annual D&A and borrowing scope.

Read only; nothing from this discovery is admitted to official scores.
Source API: https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS003&apiId=2019019
"""
import io
import json
import math
import os
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
import requests

sys.path.insert(0,"scripts")
from collect import download_corp_map, dart_company_financial

OUT=Path("audit-xbrl-notes")
KEY=os.environ.get("DART_AUTH_KEY","").strip()
SAMPLE=("005930","000660","005380","128940")
XBRLI="http://www.xbrl.org/2003/instance"
MAX_BYTES=100*1024*1024

def local(tag):
    return tag.rsplit("}",1)[-1]

def text_of(node,name):
    child=next((x for x in node.iter() if local(x.tag)==name),None)
    return child.text.strip() if child is not None and child.text else None

def describe_context(ctx):
    dimensions=[]
    for e in ctx.iter():
        if local(e.tag) in ("explicitMember","typedMember"):
            dimensions.append({"axis":e.get("dimension"),"member":"".join(e.itertext()).strip()[:300]})
    return {"start":text_of(ctx,"startDate"),"end":text_of(ctx,"endDate"),
            "instant":text_of(ctx,"instant"),"dimensions":dimensions}

def extract_instance(raw,year):
    root=ET.fromstring(raw)
    if root.tag!="{"+XBRLI+"}xbrl":
        return None
    contexts={e.get("id"):describe_context(e) for e in root if local(e.tag)=="context"}
    units={e.get("id"):[x.text for x in e.iter() if local(x.tag)=="measure"] for e in root if local(e.tag)=="unit"}
    facts=[]
    for e in root:
        name=local(e.tag)
        if not re.search("Depreciation|Amorti[sz]ation|LeaseLiabilit|Borrowing|BondsIssued",name,re.I):
            continue
        context=contexts.get(e.get("contextRef"))
        if not context or not str(context.get("end") or context.get("instant") or "").startswith((str(year),str(year-1))):
            continue
        if not e.get("unitRef") or e.text is None:
            continue
        try:
            value=float(e.text.strip())
        except (TypeError,ValueError):
            continue
        if not math.isfinite(value):
            continue
        facts.append({"concept":e.tag,"context_ref":e.get("contextRef"),"context":context,
                      "unit":units.get(e.get("unitRef")),"decimals":e.get("decimals"),"value":e.text.strip()})
    return {"context_count":len(contexts),"fact_count":len(facts),"facts":facts}

def fetch_archive(receipt):
    with requests.get("https://opendart.fss.or.kr/api/fnlttXbrl.xml",
            params={"crtfc_key":KEY,"rcept_no":receipt,"reprt_code":"11011"},
            timeout=(10,60),allow_redirects=False,stream=True) as response:
        if response.status_code!=200:
            return None,"http_"+str(response.status_code)
        content=bytearray()
        for chunk in response.iter_content(65536):
            content.extend(chunk)
            if len(content)>MAX_BYTES:
                return None,"archive_size_limit"
    if not zipfile.is_zipfile(io.BytesIO(content)):
        try:
            code=text_of(ET.fromstring(content),"status")
        except ET.ParseError:
            code=None
        return None,"api_"+str(code or "non_zip")
    return bytes(content),"received"

def main():
    OUT.mkdir(exist_ok=True)
    if not KEY:
        print("DART_AUTH_KEY missing",flush=True)
        return 1
    import datetime
    year=datetime.date.today().year-1
    mapping=download_corp_map()
    report=[]
    for ticker in SAMPLE:
        result={"ticker":ticker,"year":year,"status":"not_started","instances":[]}
        try:
            items,scope,_=dart_company_financial(mapping[ticker],year)
            receipts={str(r.get("rcept_no") or "") for r in (items or [])}
            if scope!="CFS" or len(receipts)!=1 or not re.fullmatch(r"\d{14}",next(iter(receipts),"")):
                result["status"]="annual_consolidated_receipt_unavailable"
            else:
                receipt=next(iter(receipts))
                result["receipt"]=receipt
                blob,status=fetch_archive(receipt)
                result["status"]=status
                if blob:
                    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                        members=[i for i in archive.infolist() if not i.is_dir()]
                        result["archive_members"]=[{"name":i.filename,"size":i.file_size} for i in members[:100]]
                        if sum(i.file_size for i in members)>3*MAX_BYTES:
                            raise ValueError("expanded_archive_size_limit")
                        for member in members:
                            if not member.filename.lower().endswith((".xbrl",".xml")) or member.file_size>MAX_BYTES:
                                continue
                            data=extract_instance(archive.read(member),year)
                            if data:
                                result["instances"].append({"file":member.filename,**data})
                        result["status"]="instance_received" if result["instances"] else "no_xbrl_instance"
        except Exception as exc:
            result["status"]=type(exc).__name__
        report.append(result)
        # Print bounded concept/context examples, not credentials or request URLs.
        facts=[f for i in result["instances"] for f in i["facts"]]
        da=[f for f in facts if re.search("Depreciation|Amorti[sz]ation",f["concept"],re.I)]
        print("XBRL NOTE SUMMARY",json.dumps({"ticker":ticker,"status":result["status"],
              "instances":len(result["instances"]),"fact_count":len(facts),
              "da_count":len(da),"receipt":result.get("receipt")},ensure_ascii=False),flush=True)
        for f in da[:35]:
            print("XBRL DA EVIDENCE",ticker,json.dumps(f,ensure_ascii=False),flush=True)
    (OUT/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    return 0 if any(r["status"]=="instance_received" for r in report) else 1

if __name__=="__main__":
    raise SystemExit(main())
