import unittest
from datetime import date

from scripts.discover_broker_reports import attach_tickers, parse_report_rows, parse_api_items


class ReportDiscoveryTests(unittest.TestCase):
    def test_parses_candidate_without_inventing_rating_or_target(self):
        html = """
        <table class="type_1"><tr>
          <td>삼성전자</td>
          <td><a href="/research/company_read.naver?nid=123">메모리 업황 점검</a></td>
          <td>한국투자증권</td><td class="file"><a href="/research/file.naver?id=123">PDF</a></td>
          <td>2026.11.16</td><td>100</td>
        </tr></table>
        """
        rows = parse_report_rows(html, asof=date(2026, 11, 17))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["company"], "삼성전자")
        self.assertEqual(row["broker"], "한국투자증권")
        self.assertEqual(row["target_price"], None)
        self.assertEqual(row["rating"], None)
        self.assertEqual(row["verification_status"], "candidate_unverified")

    def test_prefers_report_detail_link_over_auxiliary_image_link(self):
        html = """
        <table><tr><td>삼성전자</td>
        <td><a href="/research/company_read.naver?nid=777">실적 분석</a><a href="/img/new.gif">NEW</a></td>
        <td>한국투자증권</td><td></td><td>26.11.16</td><td>10</td></tr></table>
        """
        rows = parse_report_rows(html, asof=date(2026, 11, 17))
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["detail_url"].endswith("company_read.naver?nid=777"))

    def test_parses_naver_two_digit_year_date(self):
        html = """
        <table><tr><td>삼성전자</td><td><a href="/r?id=2">반도체 업황 점검</a></td>
        <td>한국투자증권</td><td></td><td>26.08.10</td><td>100</td></tr></table>
        """
        rows = parse_report_rows(html, asof=date(2026, 11, 17))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["published_at"], "2026-08-10")

    def test_parses_current_naver_research_v2_item_without_inventing_consensus(self):
        payload = {
            "totalCount": 125,
            "hasNext": True,
            "items": [{
                "nid": 98765,
                "itemName": "삼성전자",
                "itemCode": "005930",
                "title": "메모리 업황 및 실적 전망",
                "brokerName": "한국투자증권",
                "publishedAt": "2026-11-16",
                "opinionType": "BUY",
                "opinionText": "매수",
                "goalPrice": 120000,
            }],
        }
        rows = parse_api_items(payload, asof=date(2026, 11, 17))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ticker"], "005930")
        self.assertEqual(rows[0]["published_at"], "2026-11-16")
        self.assertEqual(rows[0]["rating"], None)
        self.assertEqual(rows[0]["target_price"], None)
        self.assertEqual(rows[0]["source_opinion_type"], "BUY")
        self.assertEqual(rows[0]["source_opinion_text"], "매수")
        self.assertEqual(rows[0]["source_goal_price"], 120000)
        self.assertTrue(rows[0]["detail_url"].endswith("/98765"))

    def test_attaches_ticker_only_for_unique_exact_company_name(self):
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp)
            (history / "20261117.json").write_text(json.dumps([
                {"ticker": "005930", "name": "삼성전자"},
                {"ticker": "000660", "name": "SK하이닉스"},
                {"ticker": "012345", "name": "중복회사"},
                {"ticker": "012346", "name": "중복회사"},
            ], ensure_ascii=False), encoding="utf-8")
            candidates = [
                {"company": "삼성전자", "ticker": None, "verification_status": "candidate_unverified"},
                {"company": "중복회사", "ticker": None, "verification_status": "candidate_unverified"},
            ]
            result = attach_tickers(candidates, history)
            self.assertEqual(result[0]["ticker"], "005930")
            self.assertEqual(result[0]["verification_status"], "ticker_matched_unverified")
            self.assertIsNone(result[1]["ticker"])
            self.assertEqual(result[1]["verification_status"], "candidate_unverified")

    def test_rejects_future_or_invalid_dates(self):
        html = """
        <table><tr><td>회사</td><td><a href="/r?id=1">리포트</a></td>
        <td>증권사</td><td></td><td>2026.11.18</td></tr></table>
        """
        self.assertEqual(parse_report_rows(html, asof=date(2026, 11, 17)), [])


if __name__ == "__main__":
    unittest.main()
