import sys
import unittest

sys.path.insert(0, "scripts")
import collect


class DartIndustryMetricExtractionTests(unittest.TestCase):
    def test_extracts_only_real_statement_values(self):
        rows = [
            {"sj_div": "IS", "account_nm": "매출액", "thstrm_amount": "1000", "frmtrm_amount": "800", "currency": "KRW"},
            {"sj_div": "IS", "account_nm": "영업이익", "thstrm_amount": "100", "frmtrm_amount": "80", "currency": "KRW"},
            {"sj_div": "IS", "account_nm": "당기순이익", "thstrm_amount": "70", "frmtrm_amount": "60", "currency": "KRW"},
            {"sj_div": "BS", "account_nm": "자본총계", "thstrm_amount": "500", "frmtrm_amount": "400", "currency": "KRW"},
            {"sj_div": "BS", "account_nm": "자산총계", "thstrm_amount": "1200", "frmtrm_amount": "800", "currency": "KRW"},
            {"sj_div": "CF", "account_nm": "영업활동으로 인한 현금흐름", "thstrm_amount": "150", "frmtrm_amount": "90", "currency": "KRW"},
        ]
        result = collect.extract_financial(rows)
        self.assertAlmostEqual(result["industry_metrics"]["operating_margin_pct"], 10.0)
        self.assertAlmostEqual(result["industry_metrics"]["asset_turnover"], 1.0)
        self.assertAlmostEqual(result["industry_metrics"]["cash_conversion_pct"], 150.0)
        self.assertIsNone(result["industry_metrics"]["roic_pct"])
        self.assertIsNone(result["industry_metrics"]["net_debt_to_ebitda"])

    def test_cis_and_statement_isolation(self):
        rows = [
            {"sj_div": "CIS", "account_nm": "매출액", "thstrm_amount": "2000", "frmtrm_amount": "1600"},
            {"sj_div": "CIS", "account_nm": "영업이익", "thstrm_amount": "300", "frmtrm_amount": "240"},
            {"sj_div": "BS", "account_nm": "자산총계", "thstrm_amount": "3000", "frmtrm_amount": "2500"},
            {"sj_div": "BS", "account_nm": "영업활동현금흐름", "thstrm_amount": "9999"},
            {"sj_div": "CF", "account_nm": "영업활동현금흐름", "thstrm_amount": "360"},
        ]
        metrics = collect.extract_financial(rows)["industry_metrics"]
        self.assertAlmostEqual(metrics["operating_margin_pct"], 15)
        self.assertAlmostEqual(metrics["asset_turnover"], 2000 / 2750)
        self.assertAlmostEqual(metrics["cash_conversion_pct"], 120)

    def test_negative_operating_profit_does_not_reward_cash_loss(self):
        rows = [
            {"sj_div": "IS", "account_nm": "영업이익", "thstrm_amount": "-100"},
            {"sj_div": "CF", "account_nm": "영업활동현금흐름", "thstrm_amount": "-200"},
        ]
        self.assertIsNone(collect.extract_financial(rows)["industry_metrics"]["cash_conversion_pct"])

    def test_missing_cash_flow_is_not_filled_with_zero(self):
        rows = [
            {"sj_div": "IS", "account_nm": "매출액", "thstrm_amount": "1000", "frmtrm_amount": "800"},
            {"sj_div": "IS", "account_nm": "영업이익", "thstrm_amount": "100"},
            {"sj_div": "BS", "account_nm": "자산총계", "thstrm_amount": "1200", "frmtrm_amount": "800"},
        ]
        result = collect.extract_financial(rows)
        self.assertIsNone(result["industry_metrics"]["cash_conversion_pct"])
        self.assertIsNone(result["industry_metrics"]["roic_pct"])
        self.assertIsNone(result["industry_metrics"]["net_debt_to_ebitda"])



class CapitalMetricTests(unittest.TestCase):
    def row(self, section, name, now, prev=None, **extra):
        return dict(sj_div=section, account_nm=name, thstrm_amount=str(now),
                    frmtrm_amount="" if prev is None else str(prev), currency="KRW",
                    account_detail="-", **extra)

    def fixture(self):
        return [
            self.row("BS", "자본총계", 500, 400),
            self.row("BS", "현금및현금성자산", 100, 80),
            self.row("BS", "유동 차입금 및 비유동차입금(사채 포함)의 유동성 대체 부분", 100, 80),
            self.row("BS", "비유동차입금(사채 포함)의 비유동성 부분", 200, 100),
            self.row("CIS", "영업이익", 120),
            self.row("CIS", "법인세비용차감전순이익", 100),
            self.row("CIS", "법인세비용", 20),
            self.row("CF", "감가상각비", 20),
            self.row("CF", "무형자산상각비", 10),
        ]

    def extract(self, rows):
        return collect.extract_financial(rows)

    def test_roic_and_leverage_with_complete_real_account_shape(self):
        out = self.extract(self.fixture())
        metrics = out["industry_metrics"]
        # Average invested capital = (700 + 500)/2 = 600; NOPAT = 96.
        self.assertAlmostEqual(metrics["roic_pct"], 16)
        self.assertAlmostEqual(metrics["net_debt_to_ebitda"], 200 / 150)
        self.assertAlmostEqual(out["capital_metric_audit"]["effective_tax_rate"], .2)

    def test_missing_previous_capital_blocks_roic_only(self):
        rows = self.fixture()
        rows[0]["frmtrm_amount"] = ""
        metrics = self.extract(rows)["industry_metrics"]
        self.assertIsNone(metrics["roic_pct"])
        self.assertAlmostEqual(metrics["net_debt_to_ebitda"], 200 / 150)

    def test_unreported_amortization_is_not_zero(self):
        metrics = self.extract(self.fixture()[:-1])["industry_metrics"]
        self.assertAlmostEqual(metrics["roic_pct"], 16)
        self.assertIsNone(metrics["net_debt_to_ebitda"])

    def test_prefer_total_not_subcomponents(self):
        rows = self.fixture()
        rows += [self.row("BS", "차입금및사채합계", 300, 180),
                 self.row("CF", "감가상각비 및 무형자산상각비", 30)]
        metrics = self.extract(rows)["industry_metrics"]
        self.assertAlmostEqual(metrics["roic_pct"], 16)
        self.assertAlmostEqual(metrics["net_debt_to_ebitda"], 200 / 150)

    def test_split_maturity_is_not_ignored(self):
        rows = self.fixture()
        rows[2]["account_nm"] = "유동 차입금(사채 포함)"
        self.assertIsNone(self.extract(rows)["industry_metrics"]["roic_pct"])
        rows.append(self.row("BS", "비유동차입금(사채 포함)의 유동성 대체 부분", 0, 0))
        self.assertAlmostEqual(self.extract(rows)["industry_metrics"]["roic_pct"], 16)

    def test_ambiguous_duplicate_or_currency_mismatch_blocks_calculation(self):
        rows = self.fixture()
        rows.append(self.row("BS", "현금및현금성자산", 120, 80))
        self.assertIsNone(self.extract(rows)["industry_metrics"]["roic_pct"])
        rows = self.fixture()
        rows[1]["currency"] = "USD"
        metrics = self.extract(rows)["industry_metrics"]
        self.assertIsNone(metrics["roic_pct"])
        self.assertIsNone(metrics["net_debt_to_ebitda"])

    def test_nonpositive_denominator_and_invalid_tax(self):
        rows = self.fixture()
        rows[4]["thstrm_amount"] = "-50"
        rows[5]["thstrm_amount"] = "-100"
        metrics = self.extract(rows)["industry_metrics"]
        self.assertIsNone(metrics["roic_pct"])
        self.assertIsNone(metrics["net_debt_to_ebitda"])

    def test_net_cash_is_allowed(self):
        rows = self.fixture()
        rows[1]["thstrm_amount"] = "350"
        metrics = self.extract(rows)["industry_metrics"]
        self.assertAlmostEqual(metrics["net_debt_to_ebitda"], -50 / 150)

    def test_financial_sector_metrics_are_excluded_from_scoring(self):
        metrics = {"roic_pct": 10, "net_debt_to_ebitda": 1, "operating_margin_pct": 12}
        for code, sector in [("64121", None), ("65110", None), ("66110", None), (None, "금융")]:
            out = collect.industry_metrics_for_scoring(metrics, code, sector)
            self.assertIsNone(out["roic_pct"])
            self.assertIsNone(out["net_debt_to_ebitda"])
            self.assertEqual(out["operating_margin_pct"], 12)
        self.assertEqual(collect.industry_metrics_for_scoring(metrics, "26110", "반도체·전자"), metrics)



    def test_samsung_published_four_line_mapping_is_issuer_year_scope_specific(self):
        rows = self.fixture()
        rows = [r for r in rows if r["sj_div"] != "BS" or r["account_nm"] in ("자본총계","현금및현금성자산")]
        rows.extend([self.row("BS","단기차입금",100,80),
                     self.row("BS","유동성장기부채",20,10),
                     self.row("BS","사채",30,20),
                     self.row("BS","장기차입금",150,70)])
        result = collect.extract_financial(rows,ticker="005930",financial_year=2025,fs_div="CFS")
        self.assertAlmostEqual(result["industry_metrics"]["roic_pct"],16)
        self.assertAlmostEqual(result["industry_metrics"]["net_debt_to_ebitda"],200/150)
        for ticker,year,scope in [("005930",2024,"CFS"),("005930",2025,"OFS"),("000660",2025,"CFS")]:
            result = collect.extract_financial(rows,ticker=ticker,financial_year=year,fs_div=scope)
            self.assertIsNone(result["industry_metrics"]["roic_pct"])


    def test_standard_id_precedes_alias_and_rejects_conflicting_duplicates(self):
        from dart_capital_metrics import pick_standard_account
        rows = [self.row("IS", "영업이익", 999),
                self.row("CIS", "영업손익", 120, account_id="dart_OperatingIncomeLoss")]
        self.assertEqual(pick_standard_account(rows, ("IS","CIS"), ["영업이익"], ["dart_OperatingIncomeLoss"])["thstrm_amount"], "120")
        rows.append(self.row("CIS", "영업손익", 121, account_id="dart_OperatingIncomeLoss"))
        self.assertIsNone(pick_standard_account(rows, ("IS","CIS"), ["영업이익"], ["dart_OperatingIncomeLoss"]))

    def test_observed_standard_cf_adjustment_ids(self):
        rows = self.fixture()
        rows[-2].update(account_nm="감가상각", account_id="ifrs-full_AdjustmentsForDepreciationExpense")
        rows[-1].update(account_nm="무형자산의 상각", account_id="ifrs-full_AdjustmentsForAmortisationExpense")
        self.assertAlmostEqual(self.extract(rows)["industry_metrics"]["net_debt_to_ebitda"], 200/150)

    def test_unreviewed_borrowing_pattern_not_scored(self):
        rows = self.fixture()
        rows[2].update(account_nm="차입금", account_id="ifrs-full_CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings")
        rows[3].update(account_nm="차입금", account_id="ifrs-full_LongtermBorrowings")
        out = collect.extract_financial(rows,ticker="000660",financial_year=2025,fs_div="CFS")
        self.assertIsNone(out["industry_metrics"]["roic_pct"])
        self.assertIsNone(out["industry_metrics"]["net_debt_to_ebitda"])
        self.assertEqual(out["capital_metric_audit"]["unreviewed_debt_preview"]["debt_current"],300)
        self.assertEqual(out["capital_metric_audit"]["unreviewed_debt_preview"]["debt_previous"],180)
        other = collect.extract_financial(rows,ticker="000660",financial_year=2024,fs_div="CFS")
        self.assertIsNone(other["capital_metric_audit"]["unreviewed_debt_preview"])

    def test_standard_revenue_and_operating_income_not_confused_with_components(self):
        rows = [self.row("CIS", "매출", 1000, 800, account_id="ifrs-full_Revenue"),
                self.row("CIS", "매출원가", 700, 650, account_id="ifrs-full_CostOfSales"),
                self.row("CIS", "영업손익", 120, 100, account_id="dart_OperatingIncomeLoss")]
        self.assertAlmostEqual(self.extract(rows)["industry_metrics"]["operating_margin_pct"],12)
        self.assertIsNone(self.extract(rows[:1]+[self.row("CIS","영업이익",900,800,account_id="ifrs-full_GrossProfit")])["industry_metrics"]["operating_margin_pct"])


    def test_auto_admission_source_and_scope(self):
        from metric_quality import assess_industry_metrics, admitted_industry_metrics
        rows = [self.row("IS","매출액",1000,800,account_id="ifrs-full_Revenue"),
                self.row("IS","영업이익",100,80,account_id="dart_OperatingIncomeLoss")]
        for row in rows:
            row.update(rcept_no="20260317000001", fs_div="CFS", bsns_year="2025", reprt_code="11011")
        v = {"operating_margin_pct":10,"roic_pct":12}
        q = assess_industry_metrics(v,rows,2025,"CFS",{"operating_margin_pct":rows},{})
        self.assertEqual(q["operating_margin_pct"]["state"],"정상")
        self.assertEqual(q["roic_pct"]["state"],"주의")
        self.assertEqual(admitted_industry_metrics(v,q,2025),{"operating_margin_pct":10,"roic_pct":None})
        self.assertIsNone(admitted_industry_metrics(v,q,2024)["operating_margin_pct"])
        rows[1]["rcept_no"]="different"
        self.assertEqual(assess_industry_metrics(v,rows,2025,"CFS",{"operating_margin_pct":rows},{})["operating_margin_pct"]["state"],"주의")

    def test_auto_standard_debt_pair_requires_separate_leases_and_no_extra_borrowing(self):
        rows = self.fixture()
        rows[2].update(account_nm="차입금", account_id="ifrs-full_CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings")
        rows[3].update(account_nm="차입금", account_id="ifrs-full_LongtermBorrowings")
        rows.extend([self.row("BS","유동리스부채",5,4,account_id="ifrs-full_CurrentLeaseLiabilities"),
                     self.row("BS","비유동리스부채",10,8,account_id="ifrs-full_NoncurrentLeaseLiabilities")])
        result = collect.extract_financial(rows,ticker="123456",financial_year=2025,fs_div="CFS")
        self.assertAlmostEqual(result["industry_metrics"]["roic_pct"],16)
        self.assertAlmostEqual(result["industry_metrics"]["net_debt_to_ebitda"],200/150)
        self.assertEqual(result["capital_metric_audit"]["lease_basis"],"lease_excluded")
        rows.append(self.row("BS","사채",50,40,account_id="ifrs-full_NoncurrentPortionOfNoncurrentBondsIssued"))
        self.assertIsNone(collect.extract_financial(rows,ticker="123456",financial_year=2025,fs_div="CFS")["industry_metrics"]["roic_pct"])

    def test_auto_admission_rejects_mixed_currencies_and_outliers(self):
        from metric_quality import assess_industry_metrics, admitted_industry_metrics
        rows = [self.row("IS","매출액",1000,800,account_id="ifrs-full_Revenue"),
                self.row("IS","영업이익",100,80,account_id="dart_OperatingIncomeLoss")]
        for row in rows:
            row.update(rcept_no="20260317000001",fs_div="CFS",bsns_year="2025",reprt_code="11011")
        rows[1]["currency"]="USD"
        values={"operating_margin_pct":10,"roic_pct":2000,"asset_turnover":float("nan")}
        q=assess_industry_metrics(values,rows,2025,"CFS",{"operating_margin_pct":rows},{"lease_basis":"lease_excluded"})
        self.assertEqual(q["operating_margin_pct"]["state"],"주의")
        self.assertEqual(q["roic_pct"]["state"],"주의")
        self.assertEqual(q["asset_turnover"]["state"],"오류")
        self.assertTrue(all(v is None for v in admitted_industry_metrics(values,q,2025).values()))


class FisisAutoAdmissionTests(unittest.TestCase):
    def test_actual_snapshot_has_27_direct_metrics_without_bank_proxies(self):
        from fisis_auto import load_auto_observations
        result=load_auto_observations(period="2025-12")
        self.assertEqual(len(result),11)
        self.assertEqual(sum(len(r["metrics"]) for r in result.values()),27)
        self.assertEqual(result["032830"]["metrics"]["kics_pct"]["value"],197.97)
        self.assertEqual(result["029780"]["metrics"]["delinquency_pct"]["value"],.94)
        self.assertNotIn("105560",result)
        self.assertNotIn("investment_yield_pct",result["032830"]["metrics"])
        self.assertEqual(load_auto_observations(period="2026-12"),{})

    def test_exact_identity_scope_and_period_are_required(self):
        import copy
        import json
        from fisis_auto import SNAPSHOT, normalize_record
        snapshot=json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        raw=next(r for r in snapshot["records"] if r["company"]=="0010595" and r["table"]=="SH021" and r["account"]=="A")
        self.assertIsNotNone(normalize_record(raw,"2025-12",snapshot["source_run"]))
        for field,value in [("base_month","202509"),("finance_cd","0010593"),("account_cd","D"),("a","NaN"),("a","0")]:
            altered=copy.deepcopy(raw)
            altered["response"]["list"][0][field]=value
            self.assertIsNone(normalize_record(altered,"2025-12",snapshot["source_run"]))
        altered=copy.deepcopy(raw)
        altered["response"]["unit"]="원"
        self.assertIsNone(normalize_record(altered,"2025-12",snapshot["source_run"]))

    def test_duplicate_source_metric_is_excluded(self):
        import json
        import tempfile
        from pathlib import Path
        from fisis_auto import SNAPSHOT,load_auto_observations
        obj=json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        raw=next(r for r in obj["records"] if r["company"]=="0010595" and r["table"]=="SH021" and r["account"]=="A")
        obj["records"].append(raw)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"snapshot.json"
            path.write_text(json.dumps(obj),encoding="utf-8")
            result=load_auto_observations(path=path)
        self.assertNotIn("kics_pct",result["032830"]["metrics"])



class DartSourceSchemaTests(unittest.TestCase):
    def test_full_statement_response_without_scope_field_uses_request_context(self):
        from metric_quality import source_check
        rows=[{"rcept_no":"20260317000001","bsns_year":"2025","reprt_code":"11011"},
              {"rcept_no":"20260317000001","bsns_year":"2025","reprt_code":"11011","fs_div":None}]
        self.assertTrue(source_check(rows,2025,"CFS"))
        self.assertFalse(source_check(rows,2025,None))
        rows[1]["fs_div"]="OFS"
        self.assertFalse(source_check(rows,2025,"CFS"))
        rows[1]["fs_div"]="CFS"
        rows[1]["bsns_year"]="2024"
        self.assertFalse(source_check(rows,2025,"CFS"))



class HoldingAutoTests(unittest.TestCase):
    def test_real_holding_snapshot(self):
        from fisis_holding_auto import load_holding_observations
        from financial_industry import comparable_observation, load_financial_observations
        r=load_holding_observations()
        self.assertEqual(len(r),7)
        self.assertEqual(sum(len(x["metrics"]) for x in r.values()),14)
        self.assertEqual(r["105560"]["metrics"]["cet1_pct"]["value"],13.82)
        self.assertEqual(r["086790"]["metrics"]["npl_pct"]["value"],.59)
        self.assertEqual(load_holding_observations(period="2026-12"),{})
        integrated=load_financial_observations(period="2025-12")
        self.assertEqual(comparable_observation(integrated["105560"],"cet1_pct","bank_group","2025-12")["value"],13.82)

    def test_holding_conflict_or_duplicate_withholds_only_affected_metric(self):
        import json,tempfile
        from pathlib import Path
        from fisis_holding_auto import SNAPSHOT,load_holding_observations
        raw=json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        altered=next(x for x in raw["records"] if x["company"]=="0012028" and x["table"]=="SL008")
        altered["response"]["list"][0]["a"]="10"
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"snapshot.json"
            p.write_text(json.dumps(raw),encoding="utf-8")
            r=load_holding_observations(p)
            self.assertNotIn("cet1_pct",r["105560"]["metrics"])
            self.assertEqual(r["105560"]["metrics"]["npl_pct"]["value"],.99)
            npl=next(x for x in raw["records"] if x["company"]=="0012028" and x["table"]=="SL009")
            raw["records"].append(npl)
            p.write_text(json.dumps(raw),encoding="utf-8")
            self.assertNotIn("105560",load_holding_observations(p))



class XbrlIntegrationTests(unittest.TestCase):
    def setUp(self):
        import json
        from pathlib import Path
        self.facts=json.loads(Path("docs/audit-evidence/xbrl-da-2025-sample.json").read_text(encoding="utf-8"))["records"]["000660"]
        self.note={"receipt":"20260317000635","year":2025,"facts":self.facts}
        self.rows=CapitalMetricTests().fixture()[:-2]
        self.rows[2].update(account_nm="차입금",account_id="ifrs-full_CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings")
        self.rows[3].update(account_nm="차입금",account_id="ifrs-full_LongtermBorrowings")
        self.rows.extend([CapitalMetricTests().row("BS","유동리스부채",5,4,account_id="ifrs-full_CurrentLeaseLiabilities"),
                          CapitalMetricTests().row("BS","비유동리스부채",10,8,account_id="ifrs-full_NoncurrentLeaseLiabilities")])
        for row in self.rows:
            row.update(rcept_no=self.note["receipt"],bsns_year="2025",reprt_code="11011",fs_div="CFS")
            for k in ("thstrm_amount","frmtrm_amount"):
                if row.get(k):
                    row[k]=str(int(row[k])*100000000000)
    def run_extract(self,rows=None,note=None):
        return collect.extract_financial(self.rows if rows is None else rows,ticker="000660",financial_year=2025,fs_div="CFS",xbrl_note=self.note if note is None else note)
    def test_real_xbrl_facts_flow_to_leverage_and_quality(self):
        result=self.run_extract()
        self.assertEqual(result["capital_metric_audit"]["depreciation_amortisation"],13930130000000)
        self.assertEqual(result["capital_metric_audit"]["da_source"],"same_receipt_xbrl_cf_adjustments")
        self.assertAlmostEqual(result["industry_metrics"]["net_debt_to_ebitda"],20000000000000/(12000000000000+13930130000000))
        self.assertEqual(result["industry_metric_quality"]["net_debt_to_ebitda"]["state"],"정상")
    def test_receipt_mismatch_and_partial_cf_withhold_fallback(self):
        result=self.run_extract(note=dict(self.note,receipt="20260317000000"))
        self.assertIsNone(result["industry_metrics"]["net_debt_to_ebitda"])
        self.assertEqual(result["capital_metric_audit"]["xbrl_note_status"],"receipt_year_or_scope_mismatch")
        rows=self.rows+[CapitalMetricTests().row("CF","감가상각비",10,rcept_no=self.note["receipt"],bsns_year="2025",reprt_code="11011",fs_div="CFS")]
        result=self.run_extract(rows=rows)
        self.assertIsNone(result["industry_metrics"]["net_debt_to_ebitda"])
        self.assertEqual(result["capital_metric_audit"]["xbrl_note_status"],"existing_cf_component_requires_review")
    def test_conflicting_cf_and_xbrl_totals_withhold(self):
        rows=self.rows+[CapitalMetricTests().row("CF","감가상각비및무형자산상각비",999,rcept_no=self.note["receipt"],bsns_year="2025",reprt_code="11011",fs_div="CFS")]
        result=self.run_extract(rows=rows)
        self.assertIsNone(result["industry_metrics"]["net_debt_to_ebitda"])
        self.assertEqual(result["capital_metric_audit"]["xbrl_note_status"],"conflicting_cf_and_xbrl_totals")



class DirectBorrowingTests(unittest.TestCase):
    def rows(self):
        row=CapitalMetricTests().row
        return [row("BS","자본총계",500,400),row("BS","현금및현금성자산",100,80),
                row("BS","단기차입금",80,60,account_id="ifrs-full_ShorttermBorrowings"),
                row("BS","유동성장기부채",20,20,account_id="ifrs-full_CurrentPortionOfLongtermBorrowings"),
                row("BS","사채",50,30,account_id="ifrs-full_NoncurrentPortionOfNoncurrentBondsIssued"),
                row("BS","장기차입금",150,70,account_id="ifrs-full_NoncurrentPortionOfNoncurrentLoansReceived"),
                row("BS","유동리스부채",5,4,account_id="ifrs-full_CurrentLeaseLiabilities"),
                row("BS","비유동리스부채",10,8,account_id="ifrs-full_NoncurrentLeaseLiabilities"),
                row("CIS","영업이익",120),row("CIS","법인세비용차감전순이익",100),
                row("CIS","법인세비용",20),row("CF","감가상각비",20),row("CF","무형자산상각비",10)]
    def test_disjoint_components_calculated(self):
        from direct_borrowing import direct_borrowing
        rows=self.rows()
        d=direct_borrowing(rows)
        self.assertEqual(d["status"],"auto_pass")
        self.assertEqual((d["debt_current"],d["debt_previous"]),(300,180))
        for r in rows:
            r.update(rcept_no="20260317000001",bsns_year="2025",reprt_code="11011",fs_div="CFS")
        out=collect.extract_financial(rows,ticker="999999",financial_year=2025,fs_div="CFS")
        self.assertAlmostEqual(out["industry_metrics"]["roic_pct"],16)
        self.assertAlmostEqual(out["industry_metrics"]["net_debt_to_ebitda"],200/150)
        self.assertEqual(out["industry_metric_quality"]["roic_pct"]["state"],"정상")
    def test_overlapping_or_unknown_debt_not_admitted(self):
        from direct_borrowing import direct_borrowing
        rows=self.rows()
        row=CapitalMetricTests().row
        self.assertNotEqual(direct_borrowing(rows+[row("BS","차입금합계",300,180)])["status"],"auto_pass")
        self.assertNotEqual(direct_borrowing(rows+[row("BS","유동성사채",10,10,account_id="dart_CurrentPortionOfBonds")])["status"],"auto_pass")
        self.assertNotEqual(direct_borrowing(rows[:6]+rows[7:])["status"],"auto_pass")
    def test_missing_prior_or_currency_conflict(self):
        from direct_borrowing import direct_borrowing
        rows=self.rows()
        rows[2]["frmtrm_amount"]=""
        self.assertNotEqual(direct_borrowing(rows)["status"],"auto_pass")
        rows=self.rows()
        rows[2]["currency"]="USD"
        self.assertNotEqual(direct_borrowing(rows)["status"],"auto_pass")



class ExpandedDirectBorrowingTests(unittest.TestCase):
    def test_three_components(self):
        from direct_borrowing import direct_borrowing
        rows=DirectBorrowingTests().rows()
        rows[4].update(account_nm="장기차입금",account_id="ifrs-full_LongtermBorrowings",thstrm_amount="200",frmtrm_amount="100")
        del rows[5]
        out=direct_borrowing(rows)
        self.assertEqual(out["layout"],"three_components")
        self.assertEqual(out["debt_current"],300)
        self.assertEqual(out["debt_previous"],180)
    def test_current_loans_and_bonds(self):
        from direct_borrowing import direct_borrowing
        rows=DirectBorrowingTests().rows()
        rows[2].update(account_nm="유동 금융기관 차입금",account_id="ifrs-full_CurrentLoansReceivedAndCurrentPortionOfNoncurrentLoansReceived")
        rows[3].update(account_nm="유동 사채",account_id="ifrs-full_CurrentBondsIssuedAndCurrentPortionOfNoncurrentBondsIssued")
        out=direct_borrowing(rows)
        self.assertEqual(out["layout"],"loans_bonds_by_maturity")
        self.assertEqual(out["debt_current"],300)
        rows.append(CapitalMetricTests().row("BS","전환사채",20,10,account_id="dart_ConvertibleBondsNet"))
        self.assertNotEqual(direct_borrowing(rows)["status"],"auto_pass")


if __name__ == "__main__":
    unittest.main()
