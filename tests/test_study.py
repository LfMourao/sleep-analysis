import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from sleep_analysis.study import Study, label_period, load_night_notes


class StudyTests(unittest.TestCase):
    def test_recovery_boundaries(self):
        study = Study(pd.Timestamp("2026-09-28"), 30, 60)
        nights = pd.DataFrame({"night": pd.to_datetime([
            "2026-09-27", "2026-09-28", "2026-10-27", "2026-10-28",
        ])}, index=[3, 5, 8, 9])
        result = label_period(nights, study)
        self.assertEqual(result.tolist(), ["before", "recovery", "recovery", "after"])
        self.assertTrue(result.index.equals(nights.index))

    def test_optional_notes_preserve_unknown_context(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.json"
            missing = load_night_notes(path)
            self.assertTrue(missing.empty)
            self.assertEqual(str(missing.night.dtype), "datetime64[ns]")
            path.write_text(json.dumps({"2026-10-16": {"mouthTape": True}}))
            notes = load_night_notes(path)
            self.assertTrue(notes.mouth_tape.iloc[0])
            self.assertTrue(pd.isna(notes.partial.iloc[0]))
            nights = pd.DataFrame({"night": pd.to_datetime(["2026-10-15", "2026-10-16"])})
            merged = nights.merge(notes, on="night", how="left", validate="one_to_one")
            self.assertTrue(pd.isna(merged.mouth_tape.iloc[0]))

    def test_notes_reject_invalid_context_and_duplicate_dates(self):
        cases = [
            {"2026-10-16": {"mouthTape": "false"}},
            {"2026-10-16": {"partial": 1}},
            {"2026-10-16": {"note": []}},
            {"2026-10-16T12:00:00": {}},
            {"2026-10-16": {}, "2026-10-16T00:00:00": {}},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.json"
            for context in cases:
                with self.subTest(context=context):
                    path.write_text(json.dumps(context))
                    with self.assertRaises(ValueError):
                        load_night_notes(path)


if __name__ == "__main__":
    unittest.main()
