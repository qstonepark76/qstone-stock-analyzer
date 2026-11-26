"""Read actual DART guidance documents and preserve candidate table rows.
Only explicit annual future-period values, units, scope, and correction history
may later qualify for verified forecast ledger. No automatic admission here.
"""
import io
import json
import re
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
import requests
sys.path.insert(0,"scripts")
from collect import DART_KEY
def main():
    if not DART_KEY:raise SystemExit("DART credential unavailable")
    rows=json.loads(Path("guidance-candidates/records.json").read_text(encoding="utf-8"))
    out=Path("audit-guidance-documents");out.mkdir(exist_ok=True)
    records=[]
    for r in rows:
        receipt=r["receipt"]
        if not re.fullmatch(r"\d{14}",receipt):continue
        result={**r,"status":"unverified","candidate_tables":[]}
        try:
            response=requests.get("https://opendart.fss.or.kr/api/document.xml",params={"crtfc_key":DART_KEY,"rcept_no":receipt},timeout=(5,30),allow_redirects=False)
            if response.status_code!=200 or len(response.content)>20_000_000:raise ValueError("http_or_size")
            with zipfile.ZipFile(io.BytesIO(response.content)) as z:
                if sum(x.file_size for x in z.infolist())>60_000_000:raise ValueError("expanded_size")
                for member in z.infolist():
                    if not member.filename.lower().endswith(".xml") or member.file_size>20_000_000:continue
                    root=ET.fromstring(z.read(member))
                    def tag(node):return node.tag.rsplit("}",1)[-1].upper()
                    def txt(node):return " ".join("".join(node.itertext()).split())
                    for table in (node for node in root.iter() if tag(node)=="TABLE"):
                        cells=[]
                        for tr in (node for node in table.iter() if tag(node)=="TR"):
                            row=[txt(td)[:500] for td in tr if tag(td) in ("TD","TH","TE","TU")]
                            if row:cells.append(row)
                        text=" ".join(x for row in cells for x in row)
                        if any(x in text for x in ("매출액","영업이익","당기순이익","영업수익")) and cells:
                            result["candidate_tables"].append({"member":member.filename,"rows":cells[:60]})
                result["status"]="tables_received_unverified" if result["candidate_tables"] else "no_candidate_table"
        except Exception as e:
            result["status"]=type(e).__name__
        records.append(result)
        print("GUIDANCE DOCUMENT",receipt,result["status"],len(result["candidate_tables"]),flush=True)
        time.sleep(.4)
    summary={"requested":len(rows),"documents_with_tables":sum(bool(r["candidate_tables"]) for r in records),"verified_forecasts":0,"release_gate":"not_verified","warning":"Candidate tables only. Annual period, currency scale, financial scope and corrected forecasts require validation."}
    (out/"records.json").write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print("GUIDANCE DOCUMENT SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
