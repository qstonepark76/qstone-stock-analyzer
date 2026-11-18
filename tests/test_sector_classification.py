import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, "scripts")
import collect


class FakeFrame:
    def __init__(self, rows):
        self.rows = rows
        self.columns = list(rows[0].keys()) if rows else []

    def to_dict(self, orient):
        if orient != "records":
            raise ValueError(orient)
        return self.rows


class SectorClassificationTests(unittest.TestCase):
    def test_official_sector_is_preferred_to_product_text(self):
        sector, confidence = collect.classify_sector("의약품 제조업", "화장품 및 생활용품")
        self.assertEqual(sector, "바이오·헬스케어")
        self.assertEqual(confidence, "high")

    def test_major_product_is_used_when_sector_is_too_broad(self):
        sector, confidence = collect.classify_sector("기타 제조업", "반도체 장비 및 부품")
        self.assertEqual(sector, "반도체·전자")
        self.assertEqual(confidence, "medium")

    def test_unknown_is_not_forced_into_another_bucket(self):
        self.assertEqual(collect.classify_sector("분류 불명 업종", "특이 사업"), (None, None))

    def test_ticker_normalization_accepts_isin_and_numeric_code(self):
        self.assertEqual(collect._listing_ticker({"ISU_CD": "KR7005930003"}), "005930")
        self.assertEqual(collect._listing_ticker({"Symbol": 5930}), "005930")

    def test_opendart_industry_codes_map_to_the_twelve_house_sectors(self):
        examples = {
            "264": "반도체·전자",
            "212": "바이오·헬스케어",
            "301": "자동차·모빌리티",
            "282": "2차전지·소재",
            "641": "금융",
            "620": "IT·소프트웨어",
            "582": "IT·소프트웨어",
            "292": "산업재·방산",
            "201": "에너지·화학",
            "411": "건설·인프라",
            "107": "소비재·유통",
            "591": "통신·미디어·엔터",
            "493": "운송·물류",
        }
        for code, expected in examples.items():
            with self.subTest(code=code):
                self.assertEqual(collect.classify_industry_code(code), expected)

    def test_nan_listing_cells_are_not_treated_as_real_sector_text(self):
        frame = FakeFrame([
            {"Code": "005930", "Name": "삼성전자", "Sector": float("nan"), "Industry": float("nan")}
        ])
        fake_module = SimpleNamespace(StockListing=lambda name: frame)
        with patch.dict(sys.modules, {"FinanceDataReader": fake_module}):
            result = collect.load_sector_classification()
        self.assertEqual(result, {})

    def test_listing_prefers_krx_desc_and_keeps_source_metadata(self):
        calls = []

        def stock_listing(name):
            calls.append(name)
            if name == "KRX-DESC":
                return FakeFrame([
                    {"Code": "005930", "Name": "삼성전자", "Sector": "전자부품 제조업", "Industry": "반도체, 스마트폰"},
                    {"Code": "068270", "Name": "셀트리온", "Sector": "의약품 제조업", "Industry": "바이오의약품"},
                    {"Code": "999999", "Name": "미분류", "Sector": "분류 불명", "Industry": "특이 사업"},
                ])
            raise AssertionError("KRX fallback should not run when DESC has usable rows")

        fake_module = SimpleNamespace(StockListing=stock_listing)
        with patch.dict(sys.modules, {"FinanceDataReader": fake_module}):
            result = collect.load_sector_classification()

        self.assertEqual(calls, ["KRX-DESC"])
        self.assertEqual(result["005930"]["sector"], "반도체·전자")
        self.assertEqual(result["005930"]["sector_confidence"], "high")
        self.assertEqual(result["068270"]["sector"], "바이오·헬스케어")
        self.assertEqual(result["068270"]["sector_source"], "KRX-DESC")
        self.assertNotIn("999999", result)


if __name__ == "__main__":
    unittest.main()
