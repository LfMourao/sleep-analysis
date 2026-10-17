"""Converte data/raw/garmin em tabelas Parquet.

A calendarDate do Garmin é o dia em que acordei. A noite da ResMed é o dia
anterior, então night = calendarDate - 1 dia. As séries guardam timestamp em UTC.
"""

import json
from pathlib import Path

import pandas as pd

from sleep_analysis.paths import (
    GARMIN_ACTIVITIES_DIR,
    GARMIN_DAILY_DIR,
    GARMIN_RAW_DIR,
    GARMIN_STATS_DIR,
    PROCESSED_DIR,
)

STAGE_BY_LEVEL = {0: "deep", 1: "light", 2: "rem", 3: "awake"}
DAY_FILE = "????-??-??.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def night_of(calendar_date: str) -> pd.Timestamp:
    return pd.Timestamp(calendar_date) - pd.Timedelta(days=1)


def utc_from_millis(value) -> pd.Timestamp:
    if value is None:
        return pd.NaT
    return pd.to_datetime(int(value), unit="ms", utc=True)


def utc_from_text(value) -> pd.Timestamp:
    if not value:
        return pd.NaT
    return pd.to_datetime(value, utc=True)


def _utc_columns(frame: pd.DataFrame, columns: list[str], unit: str | None = None) -> pd.DataFrame:
    for column in columns:
        if column not in frame:
            continue
        if unit:
            frame[column] = pd.to_datetime(pd.to_numeric(frame[column]), unit=unit, utc=True)
        else:
            frame[column] = pd.to_datetime(frame[column].replace("", None), utc=True, format="ISO8601")
    return frame


def hours(seconds) -> float | None:
    if seconds is None:
        return None
    return seconds / 3600


def score_value(sleep: dict, key: str):
    score = (sleep.get("sleepScores") or {}).get(key) or {}
    return score.get("value"), score.get("qualifierKey")


def build_sleep_tables() -> dict[str, pd.DataFrame]:
    nights, heart_rate, spo2, hrv, stages = [], [], [], [], []
    for path in sorted(GARMIN_DAILY_DIR.glob(DAY_FILE)):
        payload = load_json(path)
        sleep = payload.get("dailySleepDTO") or {}
        sleep_seconds = sleep.get("sleepTimeSeconds")
        if not sleep_seconds:
            continue
        calendar_date = sleep.get("calendarDate") or path.stem
        night = night_of(calendar_date)
        overall, qualifier = score_value(sleep, "overall")
        device_id = (sleep.get("sleepNeed") or {}).get("deviceId")
        nights.append(
            {
                "night": night,
                "calendar_date": pd.Timestamp(calendar_date),
                "sleep_start_utc": utc_from_millis(sleep.get("sleepStartTimestampGMT")),
                "sleep_end_utc": utc_from_millis(sleep.get("sleepEndTimestampGMT")),
                "sleep_hours": hours(sleep_seconds),
                "deep_hours": hours(sleep.get("deepSleepSeconds")),
                "light_hours": hours(sleep.get("lightSleepSeconds")),
                "rem_hours": hours(sleep.get("remSleepSeconds")),
                "awake_hours": hours(sleep.get("awakeSleepSeconds")),
                "awake_count": sleep.get("awakeCount"),
                "sleep_score": overall,
                "sleep_score_qualifier": qualifier,
                "resting_heart_rate": payload.get("restingHeartRate"),
                "avg_heart_rate": sleep.get("avgHeartRate"),
                "avg_overnight_hrv": payload.get("avgOvernightHrv"),
                "hrv_status": payload.get("hrvStatus"),
                "spo2_avg": sleep.get("averageSpO2Value"),
                "spo2_lowest": sleep.get("lowestSpO2Value"),
                "respiration_avg": sleep.get("averageRespirationValue"),
                "respiration_low": sleep.get("lowestRespirationValue"),
                "respiration_high": sleep.get("highestRespirationValue"),
                "sleep_stress": sleep.get("avgSleepStress"),
                "body_battery_change": payload.get("bodyBatteryChange"),
                "breathing_disruption": sleep.get("breathingDisruptionSeverity"),
                "has_detail": bool(payload.get("sleepLevels") or payload.get("sleepHeartRate")),
                "device_id": None if device_id is None else str(device_id),
            }
        )
        for sample in payload.get("sleepHeartRate") or []:
            heart_rate.append(
                {"night": night, "timestamp_utc": sample.get("startGMT"), "heart_rate_bpm": sample.get("value")}
            )
        for sample in payload.get("wellnessEpochSPO2DataDTOList") or []:
            spo2.append(
                {
                    "night": night,
                    "timestamp_utc": sample.get("epochTimestamp"),
                    "spo2_percent": sample.get("spo2Reading"),
                    "reading_confidence": sample.get("readingConfidence"),
                }
            )
        for sample in payload.get("hrvData") or []:
            hrv.append(
                {"night": night, "timestamp_utc": sample.get("startGMT"), "hrv_ms": sample.get("value")}
            )
        for segment in payload.get("sleepLevels") or []:
            level = segment.get("activityLevel")
            level_key = int(level) if level is not None else None
            stages.append(
                {
                    "night": night,
                    "start_utc": segment.get("startGMT"),
                    "end_utc": segment.get("endGMT"),
                    "activity_level": level_key,
                    "stage": STAGE_BY_LEVEL.get(level_key, "unknown"),
                }
            )
    return {
        "garmin_nights": pd.DataFrame(nights),
        "garmin_hr": _utc_columns(pd.DataFrame(heart_rate), ["timestamp_utc"], unit="ms"),
        "garmin_spo2": _utc_columns(pd.DataFrame(spo2), ["timestamp_utc"]),
        "garmin_hrv": _utc_columns(pd.DataFrame(hrv), ["timestamp_utc"], unit="ms"),
        "garmin_stages": _utc_columns(pd.DataFrame(stages), ["start_utc", "end_utc"]),
    }


def build_days() -> pd.DataFrame:
    rows = []
    for path in sorted(GARMIN_STATS_DIR.glob(DAY_FILE)):
        payload = load_json(path)
        if not payload or not payload.get("calendarDate"):
            continue
        rows.append(
            {
                "day": pd.Timestamp(payload["calendarDate"]),
                "steps": payload.get("totalSteps"),
                "distance_m": payload.get("totalDistanceMeters"),
                "active_seconds": payload.get("activeSeconds"),
                "highly_active_seconds": payload.get("highlyActiveSeconds"),
                "sedentary_seconds": payload.get("sedentarySeconds"),
                "moderate_intensity_minutes": payload.get("moderateIntensityMinutes"),
                "vigorous_intensity_minutes": payload.get("vigorousIntensityMinutes"),
                "stress_avg": payload.get("averageStressLevel"),
                "stress_max": payload.get("maxStressLevel"),
                "resting_heart_rate": payload.get("restingHeartRate"),
                "min_heart_rate": payload.get("minHeartRate"),
                "max_heart_rate": payload.get("maxHeartRate"),
                "body_battery_high": payload.get("bodyBatteryHighestValue"),
                "body_battery_low": payload.get("bodyBatteryLowestValue"),
                "body_battery_charged": payload.get("bodyBatteryChargedValue"),
                "body_battery_drained": payload.get("bodyBatteryDrainedValue"),
                "active_kcal": payload.get("activeKilocalories"),
                "spo2_avg": payload.get("averageSpo2"),
                "spo2_lowest": payload.get("lowestSpo2"),
            }
        )
    return pd.DataFrame(rows)


def build_activities() -> pd.DataFrame:
    rows = []
    for path in sorted(GARMIN_ACTIVITIES_DIR.glob("*.json")):
        activity = load_json(path)
        activity_id = activity.get("activityId")
        if activity_id is None:
            continue
        activity_type = activity.get("activityType") or {}
        rows.append(
            {
                "activity_id": int(activity_id),
                "activity_type": activity_type.get("typeKey"),
                "activity_name": activity.get("activityName"),
                "start_local": pd.to_datetime(activity.get("startTimeLocal")),
                "start_utc": utc_from_text(activity.get("startTimeGMT")),
                "duration_s": activity.get("duration"),
                "average_hr": activity.get("averageHR"),
                "max_hr": activity.get("maxHR"),
            }
        )
    return pd.DataFrame(rows)


TABLE_COLUMNS = {
    "garmin_nights": [
        "night", "calendar_date", "sleep_start_utc", "sleep_end_utc", "sleep_hours",
        "deep_hours", "light_hours", "rem_hours", "awake_hours", "awake_count",
        "sleep_score", "sleep_score_qualifier", "resting_heart_rate", "avg_heart_rate",
        "avg_overnight_hrv", "hrv_status", "spo2_avg", "spo2_lowest", "respiration_avg",
        "respiration_low", "respiration_high", "sleep_stress", "body_battery_change",
        "breathing_disruption", "has_detail", "device_id",
    ],
    "garmin_hr": ["night", "timestamp_utc", "heart_rate_bpm"],
    "garmin_spo2": ["night", "timestamp_utc", "spo2_percent", "reading_confidence"],
    "garmin_hrv": ["night", "timestamp_utc", "hrv_ms"],
    "garmin_stages": ["night", "start_utc", "end_utc", "activity_level", "stage"],
    "garmin_days": [
        "day", "steps", "distance_m", "active_seconds", "highly_active_seconds",
        "sedentary_seconds", "moderate_intensity_minutes", "vigorous_intensity_minutes",
        "stress_avg", "stress_max", "resting_heart_rate", "min_heart_rate", "max_heart_rate",
        "body_battery_high", "body_battery_low", "body_battery_charged", "body_battery_drained",
        "active_kcal", "spo2_avg", "spo2_lowest",
    ],
    "garmin_activities": [
        "activity_id", "activity_type", "activity_name", "start_local", "start_utc",
        "duration_s", "average_hr", "max_hr",
    ],
}


def build_garmin() -> None:
    """Gera as tabelas garmin_*. Sem a pasta raw, não faz nada."""
    if not GARMIN_RAW_DIR.exists():
        print("garmin: pasta ausente, tabelas não geradas")
        return
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    tables = build_sleep_tables()
    tables["garmin_days"] = build_days()
    tables["garmin_activities"] = build_activities()
    for name, frame in tables.items():
        if frame.empty:
            frame = pd.DataFrame(columns=TABLE_COLUMNS[name])
        if "night" in frame.columns:
            frame["night"] = pd.to_datetime(frame["night"])
        if "day" in frame.columns:
            frame["day"] = pd.to_datetime(frame["day"])
        frame.to_parquet(PROCESSED_DIR / f"{name}.parquet", index=False)
        print(f"{name}: {len(frame)} linhas")
