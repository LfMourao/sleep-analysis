import unittest

import pandas as pd

from sleep_analysis.latest import _flag, _summary_rows


REFERENCE = pd.DataFrame({"value": [float(level) for level in range(1, 11)]})


class FlagTests(unittest.TestCase):
    def test_higher_is_worse_marks_the_top_of_the_reference(self):
        self.assertEqual(_flag(9.5, "value", REFERENCE), "9.5 ⚠⚠")
        self.assertEqual(_flag(8.0, "value", REFERENCE), "8.0 ⚠")
        self.assertEqual(_flag(5.0, "value", REFERENCE), "5.0")

    def test_lower_is_worse_marks_the_bottom_of_the_reference(self):
        self.assertEqual(_flag(1.5, "value", REFERENCE, higher_is_worse=False), "1.5 ⚠⚠")
        self.assertEqual(_flag(3.0, "value", REFERENCE, higher_is_worse=False), "3.0 ⚠")
        self.assertEqual(_flag(9.5, "value", REFERENCE, higher_is_worse=False), "9.5")

    def test_missing_column_is_shown_without_mark(self):
        self.assertEqual(_flag(3.0, "other", REFERENCE), "3.0")


class SummaryTests(unittest.TestCase):
    def test_context_indicator_has_no_limits(self):
        rows = _summary_rows({"value": ("FR", None)}, REFERENCE, REFERENCE, {})
        self.assertEqual(rows[0][3:5], ["—", "—"])

    def test_lower_is_worse_uses_low_quantiles(self):
        rows = _summary_rows({"value": ("estável", False)}, REFERENCE, REFERENCE, {})
        self.assertEqual(rows[0][3:5], ["3.25", "1.90"])


if __name__ == "__main__":
    unittest.main()
