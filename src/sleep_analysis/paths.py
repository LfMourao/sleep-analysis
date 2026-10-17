from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
CARD_DIR = RAW_DIR / "card"
SNAPSHOTS_DIR = RAW_DIR / "snapshots"
GARMIN_RAW_DIR = RAW_DIR / "garmin"
GARMIN_DAILY_DIR = GARMIN_RAW_DIR / "daily"
GARMIN_STATS_DIR = GARMIN_RAW_DIR / "stats"
GARMIN_ACTIVITIES_DIR = GARMIN_RAW_DIR / "activities"
PROCESSED_DIR = DATA_DIR / "processed"
SIGNALS_DIR = PROCESSED_DIR / "signals_2s"
BREATHS_DIR = PROCESSED_DIR / "breaths"
