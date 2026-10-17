import duckdb

from sleep_analysis.paths import BREATHS_DIR, PROCESSED_DIR, SIGNALS_DIR


GARMIN_TABLES = [
    "garmin_nights",
    "garmin_hr",
    "garmin_spo2",
    "garmin_hrv",
    "garmin_stages",
    "garmin_days",
    "garmin_activities",
]


def connect() -> duckdb.DuckDBPyConnection:
    """Conexão DuckDB em memória com as tabelas Parquet expostas como views."""
    connection = duckdb.connect()
    for table in ["nights", "sessions", "events", "night_metrics", "respiratory_events"]:
        connection.execute(f"CREATE VIEW {table} AS SELECT * FROM read_parquet('{PROCESSED_DIR / f'{table}.parquet'}')")
    connection.execute(f"CREATE VIEW signals_2s AS SELECT * FROM read_parquet('{SIGNALS_DIR}/*.parquet')")
    connection.execute(f"CREATE VIEW breaths AS SELECT * FROM read_parquet('{BREATHS_DIR}/*.parquet')")
    for table in GARMIN_TABLES:
        path = PROCESSED_DIR / f"{table}.parquet"
        if path.exists():
            connection.execute(f"CREATE VIEW {table} AS SELECT * FROM read_parquet('{path}')")
    return connection
