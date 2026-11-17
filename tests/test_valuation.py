import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collect import calculate_valuation


class ValuationTests(unittest.TestCase):
    def test_per_and_pbr_are_calculated_from_krw_values(self):
        per, pbr = calculate_valuation(
            market_cap=1_000_000_000_000,
            net_income=100_000_000_000,
            equity_total=500_000_000_000,
            currency="KRW",
        )
        self.assertEqual(per, 10)
        self.assertEqual(pbr, 2)

    def test_loss_making_company_has_no_per_but_can_have_pbr(self):
        per, pbr = calculate_valuation(1_000, -100, 500, "KRW")
        self.assertIsNone(per)
        self.assertEqual(pbr, 2)

    def test_zero_or_negative_equity_has_no_pbr(self):
        per, pbr = calculate_valuation(1_000, 100, 0, "KRW")
        self.assertEqual(per, 10)
        self.assertIsNone(pbr)

    def test_non_krw_financials_are_not_mixed_with_krw_market_cap(self):
        per, pbr = calculate_valuation(1_000, 100, 500, "USD")
        self.assertIsNone(per)
        self.assertIsNone(pbr)

    def test_missing_market_cap_produces_no_valuation(self):
        per, pbr = calculate_valuation(None, 100, 500, "KRW")
        self.assertIsNone(per)
        self.assertIsNone(pbr)


if __name__ == "__main__":
    unittest.main()
