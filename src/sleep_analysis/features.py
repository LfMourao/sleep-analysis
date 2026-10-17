"""Uma linha por noite com o resumo do aparelho, o fluxo, o Garmin e o dia anterior."""

import numpy as np
import pandas as pd

from sleep_analysis.study import Study, label_period, load_night_notes, load_study

TIMEZONE = "America/Sao_Paulo"
APNEA_TYPES = ["obstructive_apnea", "central_apnea", "unclassified_apnea"]
DEVICE_RESPIRATORY = APNEA_TYPES + ["hypopnea"]
CLUSTER_WINDOW = np.timedelta64(5, "m")
CLUSTER_MINIMUM = 3

NIGHT_COLUMNS = [
    "night", "usage_hours", "mask_events", "ahi", "hi", "ai", "oai", "cai", "uai", "rin",
    "pressure", "epr_level", "epr_enabled", "humidity_level", "ramp_enabled", "ramp_time_min",
    "mask_type", "leak_95_l_min", "first_mask_on", "resp_rate_50", "csr", "humidifier_enabled",
]
METRIC_COLUMNS = [
    "night", "sleep_hours", "surge_index", "surge_intensity_median", "hypopnea30_index", "hypopnea30_count",
    "hypopnea30_with_surge_index", "rera_like_index", "flow_limited_pct", "ned_median", "flatness_median",
    "stable_pct", "stable_pct_t1", "stable_pct_t2", "stable_pct_t3", "wake_like_minutes", "wake_like_bouts",
    "periodicity_index", "resp_rate_median", "resp_rate_high_pct", "ventilation_median", "leak_median",
    "invalid_pct", "hypopnea40_index", "hypopnea40_count", "hypopnea50_index", "hypopnea50_count",
    "apnea75_index", "apnea75_count", "apnea90_index", "apnea90_count", "device_flow_lim_p95",
    "device_flow_lim_over_0_1_pct",
]
GARMIN_RENAME = {
    "sleep_hours": "garmin_sleep_hours",
    "deep_hours": "garmin_deep_hours",
    "light_hours": "garmin_light_hours",
    "rem_hours": "garmin_rem_hours",
    "awake_hours": "garmin_awake_hours",
    "awake_count": "garmin_awake_count",
    "sleep_score": "garmin_sleep_score",
    "resting_heart_rate": "garmin_resting_heart_rate",
    "avg_heart_rate": "garmin_avg_heart_rate",
    "avg_overnight_hrv": "garmin_hrv",
    "hrv_status": "garmin_hrv_status",
    "spo2_avg": "garmin_spo2_avg",
    "spo2_lowest": "garmin_spo2_lowest",
    "respiration_avg": "garmin_resp_rate",
    "sleep_stress": "garmin_sleep_stress",
    "body_battery_change": "garmin_body_battery_change",
    "breathing_disruption": "garmin_breathing_disruption",
    "has_detail": "has_garmin_detail",
    "sleep_start_utc": "garmin_sleep_start_utc",
}
COUNT_COLUMNS = {
    "hypopnea30_count": "hypopnea30_per_usage_h",
    "hypopnea40_count": "hypopnea40_per_usage_h",
    "hypopnea50_count": "hypopnea50_per_usage_h",
    "apnea75_count": "apnea75_per_usage_h",
    "apnea90_count": "apnea90_per_usage_h",
}


def relation_exists(connection, name: str) -> bool:
    try:
        connection.execute(f"SELECT 1 FROM {name} LIMIT 0")
        return True
    except Exception:
        return False


def _table(connection, name: str, query: str) -> pd.DataFrame:
    if not relation_exists(connection, name):
        return pd.DataFrame()
    frame = connection.execute(query).fetchdf()
    for column in ("night", "day"):
        if column in frame.columns:
            stamps = pd.to_datetime(frame[column])
            if getattr(stamps.dt, "tz", None) is not None:
                stamps = stamps.dt.tz_convert("UTC").dt.tz_localize(None)
            frame[column] = stamps
    return frame


def _present(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise KeyError(f"Colunas ausentes: {', '.join(missing)}")
    return frame[columns].copy()


def cluster_episodes(timestamps, window=CLUSTER_WINDOW, minimum: int = CLUSTER_MINIMUM) -> int:
    """Episódios com `minimum` eventos dentro de `window`, sem recontar a mesma janela."""
    times = pd.to_datetime(pd.Series(list(timestamps))).dropna().sort_values().to_numpy(dtype="datetime64[ns]")
    if len(times) < minimum:
        return 0
    episodes = 0
    covered_until = None
    for index, start in enumerate(times):
        if covered_until is not None and start <= covered_until:
            continue
        count = int(np.searchsorted(times, start + window, side="right") - index)
        if count >= minimum:
            episodes += 1
            covered_until = start + window
    return episodes


def _per_usage(count: pd.Series, usage: pd.Series) -> pd.Series:
    valid = usage > 0
    return count.where(valid) / usage.where(valid)


def _sao_paulo_naive(timestamps: pd.Series) -> pd.Series:
    stamps = pd.to_datetime(timestamps, errors="coerce")
    if getattr(stamps.dt, "tz", None) is None:
        stamps = stamps.dt.tz_localize("UTC")
    return stamps.dt.tz_convert(TIMEZONE).dt.tz_localize(None)


def build_half_counts(connection) -> pd.DataFrame:
    """Contagens em horas pares e ímpares, para a confiabilidade das metades."""
    nights = _table(connection, "nights", "SELECT night FROM nights")
    if nights.empty:
        return pd.DataFrame(columns=["night"])
    halves = nights.drop_duplicates("night").set_index("night")
    sessions = _table(connection, "sessions", "SELECT DISTINCT night FROM sessions")
    detail = set(pd.to_datetime(sessions["night"])) if not sessions.empty else set()

    if relation_exists(connection, "events"):
        counts = _table(connection, "events", """
            SELECT night, event_type,
                   count(*) FILTER (WHERE extract('hour' FROM timestamp) % 2 = 0) AS even_n,
                   count(*) FILTER (WHERE extract('hour' FROM timestamp) % 2 = 1) AS odd_n
            FROM events GROUP BY 1, 2
        """)
        halves = halves.join(_pivot_halves(counts, {
            "device_respiratory": DEVICE_RESPIRATORY,
            "device_obstructive": ["obstructive_apnea"],
            "device_central": ["central_apnea"],
            "device_hypopnea": ["hypopnea"],
            "device_arousal": ["arousal"],
        }), how="left")
        for column in [name for name in halves.columns if name.startswith("device_")]:
            halves.loc[halves.index.isin(detail), column] = halves.loc[halves.index.isin(detail), column].fillna(0)

    if relation_exists(connection, "signals_2s"):
        signal_halves = _table(connection, "signals_2s", """
            SELECT night,
                   sum(CASE WHEN extract('hour' FROM timestamp) % 2 = 0 AND snore > 0 THEN 2 ELSE 0 END) / 60.0 AS snore_even_min,
                   sum(CASE WHEN extract('hour' FROM timestamp) % 2 = 1 AND snore > 0 THEN 2 ELSE 0 END) / 60.0 AS snore_odd_min,
                   sum(CASE WHEN extract('hour' FROM timestamp) % 2 = 0 AND flow_limitation > 0 THEN 2 ELSE 0 END) / 60.0 AS flow_lim_even_min,
                   sum(CASE WHEN extract('hour' FROM timestamp) % 2 = 1 AND flow_limitation > 0 THEN 2 ELSE 0 END) / 60.0 AS flow_lim_odd_min
            FROM signals_2s GROUP BY night
        """).set_index("night")
        halves = halves.join(signal_halves, how="left")

    if relation_exists(connection, "respiratory_events"):
        counts = _table(connection, "respiratory_events", """
            SELECT night, event_type,
                   count(*) FILTER (WHERE extract('hour' FROM timestamp) % 2 = 0) AS even_n,
                   count(*) FILTER (WHERE extract('hour' FROM timestamp) % 2 = 1) AS odd_n
            FROM respiratory_events GROUP BY 1, 2
        """)
        flow = _pivot_halves(counts, {
            "hypopnea30": ["hypopnea30"],
            "hypopnea50": ["hypopnea50"],
            "apnea75": ["apnea75"],
            "apnea90": ["apnea90"],
            "surge": ["surge"],
            "rera_like": ["rera_like"],
        })
        halves = halves.join(flow, how="left")
        for column in flow.columns:
            halves.loc[halves.index.isin(detail), column] = halves.loc[halves.index.isin(detail), column].fillna(0)
    return halves.reset_index()


def _pivot_halves(counts: pd.DataFrame, groups: dict[str, list[str]]) -> pd.DataFrame:
    if counts.empty:
        columns = [f"{name}_{side}" for name in groups for side in ("even", "odd")]
        return pd.DataFrame(columns=columns)
    frame = counts.copy()
    rows = []
    for night, group in frame.groupby("night"):
        row = {"night": night}
        for name, types in groups.items():
            selected = group[group["event_type"].isin(types)]
            row[f"{name}_even"] = selected["even_n"].sum()
            row[f"{name}_odd"] = selected["odd_n"].sum()
        rows.append(row)
    return pd.DataFrame(rows).set_index("night")


def build_night_features(connection, notes: pd.DataFrame | None = None, study: Study | None = None) -> pd.DataFrame:
    nights = _table(connection, "nights", "SELECT * FROM nights")
    if nights.empty:
        return pd.DataFrame()
    features = _present(nights, [column for column in NIGHT_COLUMNS if column in nights.columns or column == "night"])
    missing = [column for column in NIGHT_COLUMNS if column not in features.columns]
    if missing:
        raise KeyError(f"nights sem {', '.join(missing)}")
    features = features.rename(columns={"resp_rate_50": "device_resp_rate"})
    features["night"] = pd.to_datetime(features["night"])
    features["has_summary"] = True
    features["mask_events_per_h"] = _per_usage(features["mask_events"], features["usage_hours"])
    # O STR guarda o nível mesmo com o EPR desligado.
    features["epr_effective"] = features["epr_level"].where(features["epr_enabled"] == 1, 0.0)
    features["weekday"] = features["night"].dt.dayofweek
    features["month_index"] = (features["night"].dt.year - 2025) * 12 + features["night"].dt.month

    study = study if study is not None else load_study()
    features["period"] = label_period(features, study)
    notes = notes if notes is not None else load_night_notes()
    features = features.merge(notes, on="night", how="left")

    signals = _table(connection, "signals_2s", """
        SELECT night,
               60 * avg(CASE WHEN flow_limitation > 0 THEN 1 ELSE 0 END) AS device_flow_lim_min_h,
               60 * avg(CASE WHEN snore > 0 THEN 1 ELSE 0 END) AS snore_min_h,
               count(*) AS signal_rows
        FROM signals_2s GROUP BY night
    """)
    features = features.merge(signals, on="night", how="left") if not signals.empty else features.assign(signal_rows=np.nan)
    features["has_signals"] = features.get("signal_rows", pd.Series(np.nan, index=features.index)).fillna(0) > 0

    metrics = _table(connection, "night_metrics", "SELECT * FROM night_metrics")
    if not metrics.empty and "hypopnea50_count" not in metrics.columns:
        raise RuntimeError("night_metrics sem hypopnea50_count. Rode sleep_analysis.build.rebuild_flow_metrics().")
    if not metrics.empty:
        keep = [column for column in METRIC_COLUMNS if column in metrics.columns]
        renamed = metrics[keep].rename(columns={
            "sleep_hours": "flow_sleep_hours",
            "resp_rate_median": "flow_resp_rate",
            "leak_median": "flow_leak_median",
        })
        features = features.merge(renamed, on="night", how="left")
    features["has_flow"] = features.get("flow_sleep_hours", pd.Series(np.nan, index=features.index)).fillna(0) > 0
    for count_column, rate_column in COUNT_COLUMNS.items():
        if count_column in features:
            features[rate_column] = _per_usage(features[count_column], features["usage_hours"])
    if "surge_index" in features and "flow_sleep_hours" in features:
        features["surge_per_usage_h"] = _per_usage(features["surge_index"] * features["flow_sleep_hours"], features["usage_hours"])
        features["rera_like_per_usage_h"] = _per_usage(features["rera_like_index"] * features["flow_sleep_hours"], features["usage_hours"])

    events = _table(connection, "events", "SELECT night, timestamp, event_type FROM events")
    sessions = _table(connection, "sessions", "SELECT DISTINCT night FROM sessions")
    detail = set(sessions["night"]) if not sessions.empty else set()
    if not events.empty:
        respiratory = events[events["event_type"].isin(DEVICE_RESPIRATORY)]
        counted = respiratory.groupby("night").size().rename("device_respiratory_count")
        features = features.merge(counted, left_on="night", right_index=True, how="left")
        features.loc[features["night"].isin(detail), "device_respiratory_count"] = (
            features.loc[features["night"].isin(detail), "device_respiratory_count"].fillna(0)
        )
        features["device_respiratory_per_h"] = _per_usage(features["device_respiratory_count"], features["usage_hours"])
        clusters = (
            events[events["event_type"].isin(APNEA_TYPES)]
            .groupby("night")["timestamp"]
            .apply(cluster_episodes)
            .rename("apnea_clusters")
        )
        features = features.merge(clusters, left_on="night", right_index=True, how="left")
        features.loc[features["night"].isin(detail), "apnea_clusters"] = features.loc[features["night"].isin(detail), "apnea_clusters"].fillna(0)
        features["apnea_cluster_per_h"] = _per_usage(features["apnea_clusters"], features["usage_hours"])

    garmin = _table(connection, "garmin_nights", "SELECT * FROM garmin_nights")
    if not garmin.empty:
        garmin = garmin.drop_duplicates("night", keep="last")
        keep = ["night", *[column for column in GARMIN_RENAME if column in garmin.columns]]
        garmin = garmin[keep].rename(columns=GARMIN_RENAME)
        features = features.merge(garmin, on="night", how="left")
        if "garmin_sleep_start_utc" in features and "first_mask_on" in features:
            sleep_start = _sao_paulo_naive(features["garmin_sleep_start_utc"])
            features["sleep_lag_min"] = (sleep_start - pd.to_datetime(features["first_mask_on"])).dt.total_seconds() / 60
    features["has_garmin"] = features.get("garmin_sleep_hours", pd.Series(np.nan, index=features.index)).notna()
    if "has_garmin_detail" not in features:
        features["has_garmin_detail"] = False

    days = _table(connection, "garmin_days", """
        SELECT day, steps, stress_avg, moderate_intensity_minutes, vigorous_intensity_minutes, resting_heart_rate
        FROM garmin_days
    """)
    if not days.empty:
        days = days.rename(columns={
            "day": "night",
            "steps": "day_steps",
            "stress_avg": "day_stress_avg",
            "resting_heart_rate": "day_resting_heart_rate",
        })
        days["day_intensity_minutes"] = days["moderate_intensity_minutes"].fillna(0) + days["vigorous_intensity_minutes"].fillna(0)
        days.loc[days["moderate_intensity_minutes"].isna() & days["vigorous_intensity_minutes"].isna(), "day_intensity_minutes"] = np.nan
        features = features.merge(
            days[["night", "day_steps", "day_stress_avg", "day_intensity_minutes", "day_resting_heart_rate"]],
            on="night", how="left",
        )
    features["has_day_load"] = features.get("day_steps", pd.Series(np.nan, index=features.index)).notna()
    return features.sort_values("night").reset_index(drop=True)
