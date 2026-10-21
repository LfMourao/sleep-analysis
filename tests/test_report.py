import json
import unittest

import numpy as np
import pandas as pd

from sleep_analysis.report import _median_difference_ci, _verdict, history_section, render_html


class VerdictTests(unittest.TestCase):
    def test_interval_crossing_zero_is_not_a_difference(self):
        self.assertEqual(_verdict(-1.0, 2.0, True), "sem diferença clara")

    def test_direction_follows_what_is_worse(self):
        self.assertEqual(_verdict(1.0, 2.0, True), "pior")
        self.assertEqual(_verdict(1.0, 2.0, False), "melhor")
        self.assertEqual(_verdict(-2.0, -1.0, False), "pior")

    def test_context_indicator_only_says_the_direction(self):
        self.assertEqual(_verdict(-2.0, -1.0, None), "menor")

    def test_missing_interval(self):
        self.assertEqual(_verdict(np.nan, np.nan, True), "poucos dados")


class IntervalTests(unittest.TestCase):
    def test_separated_groups_exclude_zero(self):
        low, high = _median_difference_ci(np.full(5, 10.0) + np.arange(5), np.arange(20, dtype=float) / 10, np.random.default_rng(0))
        self.assertGreater(low, 0)
        self.assertGreaterEqual(high, low)

    def test_single_night_has_no_interval(self):
        low, high = _median_difference_ci(np.array([1.0]), np.arange(10, dtype=float), np.random.default_rng(0))
        self.assertTrue(np.isnan(low) and np.isnan(high))


class HistoryTests(unittest.TestCase):
    def test_rolling_median_restarts_at_surgery(self):
        nights = pd.date_range("2026-09-01", periods=90, freq="D")
        surgery = pd.Timestamp("2026-10-01")
        features = pd.DataFrame({
            "night": nights,
            "usage_hours": 8.0,
            "pressure": 7.0,
            "rin": np.where(nights < surgery, 0.0, 5.0),
        })
        history = history_section(features, surgery)
        rin = next(series for series in history["series"] if series["column"] == "rin")
        first_after = history["nights"].index("2026-10-01")
        self.assertIsNone(rin["rolling"][first_after])
        self.assertEqual(rin["rolling"][first_after + 2], 5.0)
        self.assertEqual(history["surgery"], "2026-10-01")


class RenderTests(unittest.TestCase):
    def test_payload_cannot_close_the_script_tag(self):
        page = render_html({"note": "</script><b>x</b>"})
        payload = page.split('id="report-data">', 1)[1].split("</script>", 1)[0]
        self.assertEqual(json.loads(payload.replace("<\\/", "</")), {"note": "</script><b>x</b>"})


if __name__ == "__main__":
    unittest.main()
