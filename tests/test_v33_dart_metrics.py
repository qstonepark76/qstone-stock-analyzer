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


if __name__ == "__main__":
    unittest.main()
