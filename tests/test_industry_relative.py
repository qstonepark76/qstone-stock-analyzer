import sys
import unittest

sys.path.insert(0, "scripts")
from industry_relative import (
    METRICS, INDUSTRY_RELATIVE_WEIGHT, MIN_VALID_PEERS,
    percentile_score, score_industry_relative, validate_metric_separation,
    CANDIDATE_WEIGHTS, aggregate_candidate,
)


def stock(ticker, industry="101", **metrics):
    return {
        "ticker": ticker,
        "industry_code": industry,
        "industry_confidence": "high",
        "industry_metrics": metrics,
    }


class IndustryRelativeTests(unittest.TestCase):
    def make_peers(self):
        return [
            stock(str(i), operating_margin_pct=i, roic_pct=i, asset_turnover=i,
                  net_debt_to_ebitda=10-i, cash_conversion_pct=i)
            for i in range(1, 7)
        ]

    def test_weights_sum_to_ten(self):
        self.assertEqual(sum(x["weight"] for x in METRICS.values()), INDUSTRY_RELATIVE_WEIGHT)

    def test_percentile_direction_and_ties(self):
        self.assertGreater(percentile_score(6, [1, 2, 3, 4, 5, 6]), 90)
        self.assertGreater(percentile_score(1, [1, 2, 3, 4, 5, 6], False), 90)
        self.assertEqual(percentile_score(3, [1, 2, 3, 3, 5]), 60.0)

    def test_minimum_five_peers(self):
        result = score_industry_relative(self.make_peers()[:4], "1")
        self.assertEqual(result["status"], "비교대상 부족")
        self.assertIsNone(result["official_score"])

    def test_full_coverage_gets_official_score(self):
        result = score_industry_relative(self.make_peers(), "6")
        self.assertEqual(result["coverage_pct"], 100.0)
        self.assertIsNotNone(result["official_score"])
        self.assertGreaterEqual(result["official_score"], 0)
        self.assertLessEqual(result["official_score"], 10)

    def test_missing_values_are_not_zero_filled(self):
        peers = self.make_peers()
        for item in peers:
            item["industry_metrics"].pop("roic_pct")
        result = score_industry_relative(peers, "1")
        self.assertEqual(result["coverage_pct"], 80.0)
        self.assertIsNone(result["official_score"])
        self.assertIsNone(result["details"]["roic_pct"]["score"])

    def test_distinct_industry_codes_never_mix(self):
        peers = self.make_peers()
        peers.extend(stock("x"+str(i), industry="202", operating_margin_pct=999,
                           roic_pct=999, asset_turnover=999,
                           net_debt_to_ebitda=-999, cash_conversion_pct=999)
                     for i in range(10))
        result = score_industry_relative(peers, "1")
        self.assertEqual(result["peer_count"], 6)
        self.assertEqual(result["industry_code"], "101")

    def test_unknown_or_low_confidence_industry_is_not_scored(self):
        peers = self.make_peers()
        peers[0]["industry_confidence"] = "medium"
        result = score_industry_relative(peers, "1")
        self.assertEqual(result["status"], "업종 비교 불가")

    def test_result_is_reproducible(self):
        peers = self.make_peers()
        self.assertEqual(score_industry_relative(peers, "3"),
                         score_industry_relative(peers, "3"))

    def test_no_existing_factor_overlap(self):
        self.assertTrue(validate_metric_separation())
        self.assertFalse(validate_metric_separation({"operating_margin_pct", "roe_pct"}))


class CandidateAggregationTests(unittest.TestCase):
    def setUp(self):
        self.components = {k: 80 for k in CANDIDATE_WEIGHTS if k != "industry_relative"}
        self.coverage = {k: 100 for k in self.components}

    def test_weights_sum_to_100(self):
        self.assertEqual(sum(CANDIDATE_WEIGHTS.values()), 100)

    def test_partial_industry_points_not_discounted_twice(self):
        r = aggregate_candidate(self.components, self.coverage,
                                {"status": "지표 데이터 부족", "official_score": None,
                                 "provisional_score": 4, "coverage_pct": 50})
        self.assertEqual(r["coverage_pct"], 95)
        self.assertEqual(r["provisional_score"], 80)
        self.assertIsNone(r["score"])
        self.assertIsNone(r["grade"])
        self.assertFalse(r["official_recommendation_eligible"])

    def test_full_coverage_grade(self):
        r = aggregate_candidate(self.components, self.coverage,
                                {"status": "산출 완료", "official_score": 8,
                                 "provisional_score": 8, "coverage_pct": 100})
        self.assertEqual(r["score"], 80)
        self.assertEqual(r["grade"], "A")
        self.assertTrue(r["official_recommendation_eligible"])

    def test_missing_score_despite_reported_coverage(self):
        self.components["foreign_flow"] = None
        r = aggregate_candidate(self.components, self.coverage,
                                {"status": "산출 완료", "official_score": 8,
                                 "coverage_pct": 100})
        self.assertEqual(r["coverage_pct"], 90)
        self.assertIsNone(r["score"])

    def test_incomplete_industry_has_no_grade(self):
        r = aggregate_candidate(self.components, self.coverage,
                                {"status": "비교대상 부족", "coverage_pct": 0})
        self.assertEqual(r["coverage_pct"], 90)
        self.assertIsNone(r["grade"])
        self.assertEqual(r["status"], "비교대상 부족")

    def test_symmetric_extremes_and_all_ties(self):
        values = [1, 2, 3, 4, 5]
        self.assertEqual(percentile_score(5, values), percentile_score(1, values, False))
        self.assertEqual(percentile_score(3, [3] * 5), 50)

    def test_null_metric_object(self):
        peers = IndustryRelativeTests().make_peers()
        peers[0]["industry_metrics"] = None
        r = score_industry_relative(peers, "1")
        self.assertEqual(r["coverage_pct"], 0)
        self.assertIsNone(r["official_score"])



from financial_industry import FINANCIAL_MODELS, financial_model_for, comparable_observation

class FinancialIndustryTests(unittest.TestCase):
    def peers(self, model="bank_group", n=5):
        return [{
            "ticker": str(i), "industry_confidence": "high", "financial_model": model,
            "financial_period": "2025-12", "industry_code": "64999",
            "industry_metrics": {k: 99 for k in METRICS},
            "financial_observations": {"model": model, "metrics": {
                key: {"value": i, "period": "2025-12", "unit": "percent",
                      "verified": True, "source": "FISIS", "source_ref": "fixture",
                      "definition_id": key + "-v1", "scope": "consolidated_group",
                      "basis": "annual_comparable_fixture"}
                for key in FINANCIAL_MODELS[model]}}
        } for i in range(1, n+1)]

    def test_all_models_have_five_independent_metrics_and_ten_points(self):
        self.assertEqual(len(FINANCIAL_MODELS), 5)
        for model, metrics in FINANCIAL_MODELS.items():
            self.assertEqual(len(metrics), 5)
            self.assertEqual(sum(m["weight"] for m in metrics.values()), 10)
            result = score_industry_relative(self.peers(model), "5")
            self.assertEqual(result["coverage_pct"], 100)
            self.assertIsNotNone(result["official_score"])
            self.assertEqual(set(result["details"]), set(metrics))

    def test_bank_direction(self):
        result = score_industry_relative(self.peers(), "5")
        self.assertAlmostEqual(result["details"]["nim_pct"]["score"], 1.8)
        self.assertAlmostEqual(result["details"]["npl_pct"]["score"], .2)

    def test_models_never_mix_and_require_five(self):
        peers = self.peers(n=4) + self.peers("securities")
        peers[-1]["ticker"] = "9"
        result = score_industry_relative(peers, "1")
        self.assertEqual(result["peer_count"], 4)
        self.assertIsNone(result["official_score"])

    def test_wrong_period_scope_basis_units_source_or_unverified_is_missing(self):
        changes = [{"period":"2024-12"}, {"scope":"subsidiary"}, {"basis":"other"},
                   {"unit":"ratio"}, {"source":"unknown"}, {"verified":False}, {"definition_id":"other"}]
        for change in changes:
            peers = self.peers()
            peers[0]["financial_observations"]["metrics"]["nim_pct"].update(change)
            result = score_industry_relative(peers, "5")
            self.assertEqual(result["coverage_pct"], 80)
            self.assertIsNone(result["official_score"])
            self.assertEqual(result["details"]["nim_pct"]["peer_valid_count"], 4)

    def test_no_source_means_no_industrial_fallback(self):
        peers = self.peers()
        for p in peers:
            p.pop("financial_observations")
        result = score_industry_relative(peers, "1")
        self.assertIsNone(result["official_score"])
        self.assertEqual(result["coverage_pct"], 0)

    def test_unknown_finance_and_issuer_routing(self):
        self.assertEqual(financial_model_for("105560"), "bank_group")
        self.assertEqual(financial_model_for("032830"), "life_insurance")
        self.assertEqual(financial_model_for("000810"), "nonlife_insurance")
        self.assertEqual(financial_model_for("016360"), "securities")
        self.assertEqual(financial_model_for("029780"), "card_capital")
        self.assertEqual(financial_model_for("071050", "64999"), "financial_unclassified")
        self.assertIsNone(financial_model_for("005930", "26110", "반도체·전자"))
        result = score_industry_relative([{"ticker":"x","financial_model":"financial_unclassified",
                                           "industry_confidence":"high"}], "x")
        self.assertIsNone(result["official_score"])

    def test_duplicate_ticker_does_not_expand_peer_count(self):
        peers = self.peers(n=4)
        result = score_industry_relative(peers + [peers[0]], "1")
        self.assertEqual(result["peer_count"], 4)
        self.assertIsNone(result["official_score"])


if __name__ == "__main__":
    unittest.main()
