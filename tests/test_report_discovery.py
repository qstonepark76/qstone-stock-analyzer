import unittest
from datetime import date

from scripts.discover_broker_reports import parse_report_rows


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

    def test_rejects_future_or_invalid_dates(self):
        html = """
        <table><tr><td>회사</td><td><a href="/r?id=1">리포트</a></td>
        <td>증권사</td><td></td><td>2026.11.18</td></tr></table>
        """
        self.assertEqual(parse_report_rows(html, asof=date(2026, 11, 17)), [])


if __name__ == "__main__":
    unittest.main()
