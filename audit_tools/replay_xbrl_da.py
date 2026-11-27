"""Apply the D&A rule to the original complete XBRL sample artifact."""
import json
import copy
from pathlib import Path
from xbrl_da_rule import select_da

def main():
    src=json.loads(Path("xbrl-replay-source/report.json").read_text(encoding="utf-8"))
    expected={"005930":(43605740000000,3320852000000),"000660":(13099311000000,830819000000)}
    results=[]
    for record in src:
        ticker=record["ticker"]
        facts=[f for instance in record["instances"] for f in instance["facts"]]
        result=select_da(facts,record["year"])
        result.update(ticker=ticker,receipt=record.get("receipt"))
        if ticker in expected:
            assert result["status"]=="auto_pass", (ticker,result["status"])
            assert (result["depreciation"],result["amortisation"])==expected[ticker],ticker
            # Add a conflicting exact-context observation; it must be withheld.
            altered=copy.deepcopy(result["source_facts"][0])
            altered["value"]=str(int(altered["value"])+1000000)
            assert select_da(facts+[altered],record["year"])["status"]=="conflicting_adjustment_values"
            # The selector must not accept a separate company or incomplete pair.
            wrong=copy.deepcopy(result["source_facts"])
            wrong[0]["context"]["dimensions"][0]["member"]="ifrs-full:SeparateMember"
            assert select_da(wrong,record["year"])["status"]!="auto_pass"
        results.append(result)
        print("XBRL DA RULE RESULT",json.dumps({k:v for k,v in result.items() if k!="source_facts"},ensure_ascii=False),flush=True)
    out=Path("audit-xbrl-da-rule")
    out.mkdir(exist_ok=True)
    (out/"report.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
    print("XBRL DA RULE SUMMARY",json.dumps({"sample":len(results),"passed":sum(r["status"]=="auto_pass" for r in results),"representative_regressions":"passed"}),flush=True)

if __name__=="__main__":
    main()
