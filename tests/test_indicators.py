import json
import tempfile
import unittest
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from sleep_analysis.effects import apply_bh, estimate_effect, minimum_detectable_effect, minimum_n, plan_n_of_1
from sleep_analysis.features import build_night_features, cluster_episodes
from sleep_analysis.reliability import combine_scores, icc_2_1, load_indicator_config, spearman_brown
from sleep_analysis.respiratory_metrics import add_baseline, detect_hypopneas, ratios_for_drop
from sleep_analysis.study import Study, habits_for_nights, load_daily_log, load_night_notes
from sleep_analysis.undercount import bland_altman, event_agreement, lin_ccc, points_match_intervals, summarize_undercount


def breaths_with(ventilation):
    start = pd.Timestamp("2026-01-01 23:00:00")
    times = pd.date_range(start, periods=len(ventilation), freq="4s")
    return pd.DataFrame({
        "night": times[0].normalize(),
        "session_start": start,
        "t_start": times,
        "ttot": 4.0,
        "ventilation": ventilation,
        "vt": np.asarray(ventilation) * 4,
        "flatness": 0.5,
        "ned": 1.0,
        "valid": True,
        "long_pause": False,
        "rate": 15.0,
        "leak": 0.0,
    })


class ThresholdTests(unittest.TestCase):
    def test_drop_of_30_percent_matches_the_original_ratios(self):
        self.assertEqual(ratios_for_drop(0.30), (0.7, 0.8))

    def test_mild_drop_is_not_a_resmed_hypopnea_or_an_apnea(self):
        ventilation = [10.0] * 30 + [6.0] * 4 + [10.0] * 10
        breaths = add_baseline(breaths_with(ventilation))
        surges = pd.DataFrame(columns=["position", "timestamp", "intensity"])
        mild, _ = detect_hypopneas(breaths, surges)
        mean_ratio, edge_ratio = ratios_for_drop(0.50)
        deeper, _ = detect_hypopneas(breaths, surges, vent_ratio=mean_ratio, edge_vent_ratio=edge_ratio)
        self.assertEqual(len(mild), 1)
        self.assertEqual(len(deeper), 0)

    def test_near_zero_ventilation_is_an_apnea(self):
        ventilation = [10.0] * 30 + [0.5] * 4 + [10.0] * 10
        breaths = add_baseline(breaths_with(ventilation))
        surges = pd.DataFrame(columns=["position", "timestamp", "intensity"])
        mean_ratio, edge_ratio = ratios_for_drop(0.90)
        apneas, _ = detect_hypopneas(breaths, surges, vent_ratio=mean_ratio, edge_vent_ratio=edge_ratio)
        self.assertEqual(len(apneas), 1)
        self.assertGreaterEqual(apneas["duration_s"].iloc[0], 10)


class AgreementTests(unittest.TestCase):
    def test_point_inside_interval_matches_and_a_later_point_does_not(self):
        start = np.array(["2026-01-01T00:00:00"], dtype="datetime64[ns]")
        end = start + np.timedelta64(20, "s")
        points = np.array(["2026-01-01T00:00:10", "2026-01-01T00:00:40"], dtype="datetime64[ns]")
        matched = points_match_intervals(points, start, end, 15)
        self.assertEqual(matched.tolist(), [True, False])

    def test_sensitivity_and_concordance(self):
        night = pd.Timestamp("2026-01-01")
        device = pd.DataFrame({
            "night": [night, night],
            "timestamp": pd.to_datetime(["2026-01-01 00:00:10", "2026-01-01 01:00:00"]),
            "event_type": ["hypopnea", "hypopnea"],
            "duration_s": [0, 0],
        })
        own = pd.DataFrame({
            "night": [night],
            "timestamp": pd.to_datetime(["2026-01-01 00:00:00"]),
            "event_type": ["hypopnea50"],
            "duration_s": [20],
        })
        agreement = event_agreement(device, own, ["hypopnea"], "hypopnea50")
        self.assertAlmostEqual(agreement["sensitivity"], 0.5)
        self.assertAlmostEqual(agreement["ppv"], 1)
        self.assertAlmostEqual(lin_ccc(pd.Series([1.0, 2.0, 3.0]), pd.Series([1.0, 2.0, 3.0])), 1)
        bias = bland_altman(pd.Series([1.0, 2.0, 3.0, 4.0]), pd.Series([2.0, 3.0, 4.0, 5.0]))
        self.assertAlmostEqual(bias["bias"], 1)

    def test_cluster_and_summary_do_not_invent_a_gold_standard(self):
        origin = pd.Timestamp("2026-01-01")
        self.assertEqual(cluster_episodes([origin, origin + pd.Timedelta(minutes=1), origin + pd.Timedelta(minutes=2)]), 1)
        self.assertEqual(cluster_episodes([origin, origin + pd.Timedelta(minutes=1)]), 0)
        text = summarize_undercount(0.6, 0.7, 6.0, 0.8, 0.2, 0.4, 0.1, 0.5)
        self.assertIn("não é polissonografia", text.lower())


class ReliabilityTests(unittest.TestCase):
    def test_perfect_agreement_has_icc_one_and_spearman_brown_corrects(self):
        perfect = np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0], [4.0, 4.0]])
        self.assertAlmostEqual(icc_2_1(perfect), 1)
        self.assertAlmostEqual(spearman_brown(0.5), 2 / 3)

    def test_missing_criterion_is_left_out_of_the_weight(self):
        components = pd.DataFrame([{"repeatability": 1.0, "coverage": np.nan}])
        score = combine_scores(components, {"repeatability": 0.25, "coverage": 0.75})
        self.assertAlmostEqual(score.iloc[0], 1)

    def test_config_weights_sum_to_one_and_cover_the_five_dimensions(self):
        config = load_indicator_config()
        self.assertAlmostEqual(sum(config["weights"].values()), 1)
        dimensions = {item["dimension"] for item in config["indicators"]}
        self.assertEqual(dimensions, {"dose", "obstruction", "fragmentation", "stability", "recovery"})

    def test_effect_size_helpers_and_false_discovery(self):
        self.assertLess(minimum_n(1, 0, 1), minimum_n(1, 0, 0.2))
        self.assertGreater(minimum_detectable_effect(1, 0.5, 20), minimum_detectable_effect(1, 0, 20))
        adjusted = apply_bh(pd.DataFrame({"p_value": [0.001, 0.04, np.nan]}))
        self.assertLess(adjusted["q_value"].iloc[0], adjusted["q_value"].iloc[1])
        self.assertTrue(np.isnan(adjusted["q_value"].iloc[2]))


class EffectTests(unittest.TestCase):
    def test_regression_recovers_a_known_slope(self):
        rng = np.random.default_rng(1)
        pressure = np.tile([6.0, 7.0, 8.0, 9.0], 12)
        nights = pd.date_range("2026-01-01", periods=len(pressure), freq="D")
        outcome = 2 * pressure + rng.normal(0, 0.05, len(pressure))
        frame = pd.DataFrame({"night": nights, "pressure": pressure, "ahi": outcome, "usage_hours": 7})
        result = estimate_effect(frame, "pressure", ["ahi"], covariates=["usage_hours"], n_boot=80, block=4, rng=rng)
        self.assertAlmostEqual(result["coefficient"].iloc[0], 2, delta=0.15)
        self.assertTrue(result["boot_low"].iloc[0] < 2 < result["boot_high"].iloc[0])

    def test_n_of_1_schedule_alternates_blocks(self):
        schedule = plan_n_of_1("2026-11-01", periods=4, block_nights=7)
        self.assertEqual(len(schedule), 28)
        self.assertEqual(schedule.groupby("block")["phase"].first().tolist(), ["off", "on", "off", "on"])
        with self.assertRaises(ValueError):
            plan_n_of_1("2026-11-01", block_nights=6)


class FeatureTests(unittest.TestCase):
    def test_features_keep_missing_flow_empty_and_count_clusters(self):
        night = pd.Timestamp("2026-02-01")
        nights = pd.DataFrame([{
            "night": night, "usage_hours": 8.0, "mask_events": 2, "ahi": 1.0, "hi": 0.5, "ai": 0.5,
            "oai": 0.4, "cai": 0.1, "uai": 0.0, "rin": 0.2, "pressure": 7.0, "epr_level": 1.0,
            "epr_enabled": 1.0, "humidity_level": 4.0, "ramp_enabled": 0.0, "ramp_time_min": 5.0,
            "mask_type": 2.0, "leak_95_l_min": 0.0, "first_mask_on": night + pd.Timedelta(hours=23),
            "resp_rate_50": 16.0, "csr": 0.0, "humidifier_enabled": 1.0,
        }])
        metrics = pd.DataFrame([{
            "night": night, "sleep_hours": 7.0, "hypopnea50_count": 4, "hypopnea30_count": 10,
            "hypopnea40_count": 6, "apnea75_count": 1, "apnea90_count": 1, "surge_index": 8.0,
            "rera_like_index": 1.0,
        }])
        origin = night + pd.Timedelta(hours=23)
        events = pd.DataFrame({
            "night": [night] * 3,
            "timestamp": [origin, origin + pd.Timedelta(minutes=1), origin + pd.Timedelta(minutes=2)],
            "event_type": ["obstructive_apnea"] * 3,
        })
        sessions = pd.DataFrame({"night": [night]})
        connection = duckdb.connect()
        connection.register("nights", nights)
        connection.register("night_metrics", metrics)
        connection.register("events", events)
        connection.register("sessions", sessions)
        notes = load_night_notes(Path(tempfile.gettempdir()) / "missing-notes.json")
        features = build_night_features(connection, notes=notes, study=Study(pd.Timestamp("2026-09-28"), 30, 60))
        self.assertEqual(len(features), 1)
        self.assertAlmostEqual(features["hypopnea50_per_usage_h"].iloc[0], 0.5)
        self.assertEqual(features["apnea_clusters"].iloc[0], 1)
        self.assertFalse(bool(features["has_garmin"].iloc[0]))
        self.assertFalse(bool(features["has_signals"].iloc[0]))
        self.assertEqual(features["period"].iloc[0], "before")


class HabitTests(unittest.TestCase):
    def test_daily_log_validates_and_shifts_previous_day(self):
        catalog = {
            "alcohol": {"type": "boolean", "unit": None, "lag": "same_night", "expected": "worse"},
            "supplement_dose_mg": {"type": "number", "unit": "mg", "lag": "previous_day", "expected": None},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "daily_log.csv"
            missing = load_daily_log(path, catalog)
            self.assertTrue(missing.empty)
            path.write_text("date,variable,value,unit,note\n2026-10-16,alcohol,true,,\n2026-10-16,supplement_dose_mg,200,mg,magnesio\n")
            log = load_daily_log(path, catalog)
            self.assertEqual(log["value_number"].tolist(), [1.0, 200.0])
            nights = habits_for_nights(log)
            alcohol = nights[nights["variable"] == "alcohol"]["night"].iloc[0]
            dose = nights[nights["variable"] == "supplement_dose_mg"]["night"].iloc[0]
            self.assertEqual(alcohol, pd.Timestamp("2026-10-16"))
            self.assertEqual(dose, pd.Timestamp("2026-10-17"))
            path.write_text("date,variable,value,unit,note\n2026-10-16,alcohol,yes,,\n")
            with self.assertRaises(ValueError):
                load_daily_log(path, catalog)
            path.write_text("date,variable,value,unit,note\n2026-10-16,unknown,1,,\n")
            with self.assertRaises(ValueError):
                load_daily_log(path, catalog)


if __name__ == "__main__":
    unittest.main()
