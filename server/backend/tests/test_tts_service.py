from __future__ import annotations

from pathlib import Path
import sys
import unittest


SERVER_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_BACKEND_ROOT))

from tts_service import normalize_text_for_tts


class TtsNormalizationTests(unittest.TestCase):
    def test_normalize_text_for_tts_removes_punctuation_and_restores_title_case(self) -> None:
        text = (
            "Tôi nghe không rõ Ý của bạn có phải là "
            "LẠC TRÔI | OFFICIAL MUSIC VIDEO | SƠN TÙNG M TP hay một video nào khác?"
        )

        normalized = normalize_text_for_tts(text)

        self.assertEqual(
            normalized,
            "Tôi nghe không rõ Ý của bạn có phải là "
            "Lạc Trôi Official Music Video Sơn Tùng M Tp hay một video nào khác",
        )

    def test_normalize_text_for_tts_parses_european_decimal_format(self) -> None:
        normalized = normalize_text_for_tts("Giá là 200.000,90 đồng.")

        self.assertEqual(normalized, "Giá là hai trăm nghìn phẩy chín đồng")

    def test_normalize_text_for_tts_parses_us_decimal_format(self) -> None:
        normalized = normalize_text_for_tts("Giá là 200,000.90 đồng.")

        self.assertEqual(normalized, "Giá là hai trăm nghìn phẩy chín đồng")

    def test_normalize_text_for_tts_rounds_fractional_numbers(self) -> None:
        normalized = normalize_text_for_tts("Nhiệt độ là 1,234.567 độ.")

        self.assertEqual(
            normalized,
            "Nhiệt độ là một nghìn hai trăm ba mươi tư phẩy năm bảy độ",
        )

    def test_normalize_text_for_tts_reads_grouped_integers_without_punctuation(self) -> None:
        normalized = normalize_text_for_tts("Tỷ giá bán ra là 26.360 đồng/USD.")

        self.assertEqual(
            normalized,
            "Tỷ giá bán ra là hai mươi sáu nghìn ba trăm sáu mươi đồng Usd",
        )


if __name__ == "__main__":
    unittest.main()
