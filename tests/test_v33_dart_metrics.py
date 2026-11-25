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


if __name__ == "__main__":
    unittest.main()
