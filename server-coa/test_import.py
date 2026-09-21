import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_coa_zip import extract_lots


class ExtractLotsTest(unittest.TestCase):
    def test_single_lot(self):
        self.assertEqual(extract_lots("EC64405-26030133.pdf"), ["26030133"])

    def test_all_related_lots(self):
        self.assertEqual(
            extract_lots("G020250-25011106-CSE-24115185-25045128.pdf"),
            ["25011106", "24115185", "25045128"],
        )

    def test_product_digits_are_not_lots(self):
        self.assertEqual(extract_lots("GC08170060_24080232.png"), ["24080232"])

    def test_four_digit_month_lot(self):
        self.assertEqual(extract_lots("PT25096 2512.pdf"), ["2512"])

    def test_visually_verified_related_lots(self):
        self.assertEqual(
            extract_lots("G020030 24061151.pdf"),
            ["24061151", "23045133", "24045124"],
        )


if __name__ == "__main__":
    unittest.main()
