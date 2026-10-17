"""Converte o backup do cartão (data/raw/card) em tabelas Parquet (data/processed).

Tabelas:
- nights: uma linha por dia de uso, a partir do resumo diário STR.edf
- sessions: cada período contínuo de máscara registrado em DATALOG
- events: eventos respiratórios marcados pelo aparelho (EVE)
- signals_2s/<noite>.parquet: sinais de pressão, vazamento, respiração e ronco a cada 2 s (PLD)
- breaths/<noite>.parquet: uma linha por respiração, segmentada do fluxo de 25 Hz (BRP)
- respiratory_events: eventos inferidos do fluxo bruto (surge, hypopnea30, hypopnea50, apnea75, apnea90, rera_like, wake_like)
- night_metrics: métricas respiratórias por noite a partir do fluxo bruto
- garmin_*: sono, séries e hábitos do relógio, quando data/raw/garmin existe
"""

import argparse
import hashlib
import json
import pickle
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from sleep_analysis.breaths import segment_night
from sleep_analysis.edf import read_edf, signal_timestamps
from sleep_analysis.paths import BREATHS_DIR, CARD_DIR, PROCESSED_DIR, SIGNALS_DIR
from sleep_analysis.respiratory_metrics import analyze_night

CACHE_DIR = PROCESSED_DIR / "cache"
SESSIONS_CACHE_DIR = CACHE_DIR / "sessions"
METRICS_CACHE_DIR = CACHE_DIR / "metrics"
MANIFEST_PATH = CACHE_DIR / "manifest.json"
SEGMENT_CODE = ["build.py", "edf.py", "breaths.py"]
METRICS_CODE = ["respiratory_metrics.py"]
SESSION_COLUMNS = ["night", "session_start", "signal_start", "signal_end", "duration_min"]
EPOCH = date(1970, 1, 1)
# O dia da ResMed vai de meio-dia a meio-dia; MaskOn/MaskOff são minutos desde o meio-dia
DAY_START_HOUR = 12
LITERS_PER_SECOND_TO_PER_MINUTE = 60
LEAK_COLUMNS = ["leak_50", "leak_95", "leak_70", "leak_max"]
SETTING_COLUMNS = {
    "s_c_press": "pressure",
    "s_c_start_press": "start_pressure",
    "s_ramp_enable": "ramp_enabled",
    "s_ramp_time": "ramp_time_min",
    "s_epr_eprenable": "epr_enabled",
    "s_epr_level": "epr_level",
    "s_hum_enable": "humidifier_enabled",
    "s_hum_level": "humidity_level",
    "s_mask": "mask_type",
    "s_tube": "tube_type",
    "s_climate_control": "climate_control",
}
PLD_COLUMNS = {
    "MaskPress.2s": "mask_press",
    "Press.2s": "target_press",
    "EprPress.2s": "epr_press",
    "Leak.2s": "leak",
    "RespRate.2s": "resp_rate",
    "TidVol.2s": "tidal_volume",
    "MinVent.2s": "minute_vent",
    "Snore.2s": "snore",
    "FlowLim.2s": "flow_limitation",
}
EVENT_TYPES = {
    "Obstructive Apnea": "obstructive_apnea",
    "Central Apnea": "central_apnea",
    "Apnea": "unclassified_apnea",
    "Hypopnea": "hypopnea",
    "Arousal": "arousal",
}


def to_snake_case(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", re.sub(r"([a-z])([A-Z])", r"\1_\2", label).lower()).strip("_")


def build_nights() -> pd.DataFrame:
    edf = read_edf(CARD_DIR / "STR.edf")
    physical = edf.read_physical()
    first_day = edf.start.date()

    rows = []
    for index in range(physical["Date"].shape[0]):
        duration = physical["Duration"][index, 0]
        if np.isnan(duration) or duration <= 0:
            continue
        day_number = physical["Date"][index, 0]
        night = EPOCH + timedelta(days=int(day_number)) if not np.isnan(day_number) else first_day + timedelta(days=index)
        row: dict = {"night": night}
        for label, values in physical.items():
            if label in ("Date", "MaskOn", "MaskOff"):
                continue
            row[to_snake_case(label)] = values[index, 0]

        day_start = datetime.combine(night, datetime.min.time()) + timedelta(hours=DAY_START_HOUR)
        mask_on = physical["MaskOn"][index][~np.isnan(physical["MaskOn"][index])]
        mask_off = physical["MaskOff"][index][~np.isnan(physical["MaskOff"][index])]
        row["first_mask_on"] = day_start + timedelta(minutes=float(mask_on.min())) if mask_on.size else pd.NaT
        row["last_mask_off"] = day_start + timedelta(minutes=float(mask_off.max())) if mask_off.size else pd.NaT
        rows.append(row)

    nights = pd.DataFrame(rows).rename(columns=SETTING_COLUMNS)
    nights["night"] = pd.to_datetime(nights["night"])
    nights["usage_hours"] = nights["duration"] / 60
    for column in LEAK_COLUMNS:
        nights[f"{column}_l_min"] = nights[column] * LITERS_PER_SECOND_TO_PER_MINUTE
    # Oxímetro não está conectado: colunas de SpO2 ficam sempre vazias
    empty_columns = [column for column in nights.columns if nights[column].isna().all()]
    return nights.drop(columns=empty_columns)


def session_start(path: Path) -> datetime:
    return datetime.strptime("_".join(path.stem.split("_")[:2]), "%Y%m%d_%H%M%S")


def read_night_signals(night_dir: Path) -> tuple[list[dict], pd.DataFrame]:
    rows = []
    frames = []
    night = pd.Timestamp(datetime.strptime(night_dir.name, "%Y%m%d"))
    for pld_path in sorted(night_dir.glob("*_PLD.edf")):
        edf = read_edf(pld_path)
        physical = edf.read_physical()
        n_records = next(iter(physical.values())).shape[0]
        if n_records == 0:
            continue
        samples_per_record = physical["Press.2s"].shape[1]
        frame = pd.DataFrame({"timestamp": signal_timestamps(edf, samples_per_record, n_records)})
        for label, column in PLD_COLUMNS.items():
            frame[column] = physical[label].reshape(-1)
        frame["leak"] = frame["leak"] * LITERS_PER_SECOND_TO_PER_MINUTE
        frame["session_start"] = session_start(pld_path)
        frames.append(frame)

        rows.append(
            {
                "night": night,
                "session_start": session_start(pld_path),
                "signal_start": edf.start,
                "signal_end": edf.start + timedelta(seconds=n_records * edf.record_duration_s),
                "duration_min": n_records * edf.record_duration_s / 60,
            }
        )
    if not frames:
        return rows, pd.DataFrame()
    signals = pd.concat(frames, ignore_index=True)
    signals.insert(0, "night", night)
    return rows, signals


def build_events() -> pd.DataFrame:
    rows = []
    for eve_path in sorted((CARD_DIR / "DATALOG").glob("*/*_EVE.edf")):
        edf = read_edf(eve_path)
        night = pd.Timestamp(datetime.strptime(eve_path.parent.name, "%Y%m%d"))
        for onset, duration, text in edf.read_annotations():
            if text == "Recording starts":
                continue
            rows.append(
                {
                    "night": night,
                    "timestamp": edf.start + timedelta(seconds=onset),
                    "event_type": EVENT_TYPES.get(text, to_snake_case(text)),
                    "duration_s": duration,
                }
            )
    return pd.DataFrame(rows, columns=["night", "timestamp", "event_type", "duration_s"])


def _code_hash(names: list[str]) -> str:
    digest = hashlib.sha256()
    for name in names:
        digest.update((Path(__file__).parent / name).read_bytes())
    return digest.hexdigest()[:16]


def _fingerprint(night_dir: Path) -> str:
    entries = sorted((path.name, path.stat().st_size, path.stat().st_mtime_ns) for path in night_dir.iterdir() if path.is_file())
    return hashlib.sha256(repr(entries).encode()).hexdigest()[:16]


def _load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8")) if MANIFEST_PATH.exists() else {}


def _remove(*paths: Path) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


def _analyze_cached_breaths(name: str) -> None:
    breaths_path = BREATHS_DIR / f"{name}.parquet"
    metrics_path = METRICS_CACHE_DIR / f"{name}.pkl"
    if not breaths_path.exists():
        _remove(metrics_path)
        return
    breaths = pd.read_parquet(breaths_path)
    signals_path = SIGNALS_DIR / f"{name}.parquet"
    device_flow_limitation = (
        pd.read_parquet(signals_path, columns=["flow_limitation"])["flow_limitation"] if signals_path.exists() else None
    )
    with metrics_path.open("wb") as handle:
        pickle.dump(analyze_night(breaths, device_flow_limitation), handle)


def _segment_night_dir(night_dir: Path) -> None:
    name = night_dir.name
    sessions_path = SESSIONS_CACHE_DIR / f"{name}.parquet"
    signals_path = SIGNALS_DIR / f"{name}.parquet"
    breaths_path = BREATHS_DIR / f"{name}.parquet"
    _remove(sessions_path, signals_path, breaths_path)
    rows, signals = read_night_signals(night_dir)
    pd.DataFrame(rows, columns=SESSION_COLUMNS).to_parquet(sessions_path, index=False)
    if not signals.empty:
        signals.to_parquet(signals_path, index=False)
    breaths = segment_night(night_dir)
    if not breaths.empty:
        breaths.to_parquet(breaths_path, index=False)


def build_detail(full: bool = False, refresh_metrics: bool = False) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Sessões, sinais, breaths e métricas do fluxo, refazendo só as noites que mudaram no cartão.

    O cache cai inteiro quando muda o código de leitura (edf, breaths, build) e só as métricas
    quando muda respiratory_metrics.py.
    """
    for directory in (SIGNALS_DIR, BREATHS_DIR, SESSIONS_CACHE_DIR, METRICS_CACHE_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest()
    segment_code = _code_hash(SEGMENT_CODE)
    metrics_code = _code_hash(METRICS_CODE)
    known = manifest.get("nights", {}) if not full and manifest.get("segment_code") == segment_code else {}
    metrics_stale = refresh_metrics or full or manifest.get("metrics_code") != metrics_code

    night_dirs = sorted(path for path in (CARD_DIR / "DATALOG").iterdir() if path.is_dir())
    fingerprints = {}
    segmented = analyzed = 0
    for night_dir in night_dirs:
        name = night_dir.name
        fingerprints[name] = _fingerprint(night_dir)
        changed = known.get(name) != fingerprints[name] or not (SESSIONS_CACHE_DIR / f"{name}.parquet").exists()
        if changed:
            _segment_night_dir(night_dir)
            segmented += 1
        missing_metrics = (BREATHS_DIR / f"{name}.parquet").exists() and not (METRICS_CACHE_DIR / f"{name}.pkl").exists()
        if changed or metrics_stale or missing_metrics:
            _analyze_cached_breaths(name)
            analyzed += 1
    MANIFEST_PATH.write_text(
        json.dumps({"segment_code": segment_code, "metrics_code": metrics_code, "nights": fingerprints}, indent=1),
        encoding="utf-8",
    )
    print(f"detalhe: {segmented} noites lidas do cartão, {analyzed} com métricas recalculadas, {len(night_dirs)} no total")

    session_frames = [pd.read_parquet(SESSIONS_CACHE_DIR / f"{path.name}.parquet") for path in night_dirs]
    sessions = pd.concat([frame for frame in session_frames if not frame.empty], ignore_index=True)
    metrics, events = [], []
    for path in night_dirs:
        metrics_path = METRICS_CACHE_DIR / f"{path.name}.pkl"
        if not metrics_path.exists():
            continue
        with metrics_path.open("rb") as handle:
            night_metrics, night_events = pickle.load(handle)
        metrics.append(night_metrics)
        if not night_events.empty:
            events.append(night_events)
    respiratory_events = pd.concat(events, ignore_index=True) if events else pd.DataFrame()
    return sessions, pd.DataFrame(metrics), respiratory_events


def rebuild_flow_metrics() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Recalcula night_metrics e respiratory_events a partir dos breaths já segmentados."""
    _, night_metrics, respiratory_events = build_detail(refresh_metrics=True)
    night_metrics.to_parquet(PROCESSED_DIR / "night_metrics.parquet", index=False)
    respiratory_events.to_parquet(PROCESSED_DIR / "respiratory_events.parquet", index=False)
    print(f"night_metrics: {len(night_metrics)} noites; {len(respiratory_events)} eventos inferidos")
    return night_metrics, respiratory_events


def main() -> None:
    parser = argparse.ArgumentParser(description="Converte o backup do cartão e do Garmin em Parquet")
    parser.add_argument("--full", action="store_true", help="Ignora o cache e relê todas as noites do cartão")
    args = parser.parse_args()
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    nights = build_nights()
    nights.to_parquet(PROCESSED_DIR / "nights.parquet", index=False)
    print(f"nights: {len(nights)} noites ({nights['night'].min():%d/%m/%Y} a {nights['night'].max():%d/%m/%Y})")

    sessions, night_metrics, respiratory_events = build_detail(full=args.full)
    sessions.to_parquet(PROCESSED_DIR / "sessions.parquet", index=False)
    print(f"sessions: {len(sessions)} sessões em {sessions['night'].nunique()} noites com sinais detalhados")

    events = build_events()
    events.to_parquet(PROCESSED_DIR / "events.parquet", index=False)
    print(f"events: {len(events)} eventos")

    night_metrics.to_parquet(PROCESSED_DIR / "night_metrics.parquet", index=False)
    respiratory_events.to_parquet(PROCESSED_DIR / "respiratory_events.parquet", index=False)
    print(f"night_metrics: {len(night_metrics)} noites com fluxo de 25 Hz; {len(respiratory_events)} eventos inferidos")

    from sleep_analysis.garmin import build_garmin

    build_garmin()


if __name__ == "__main__":
    main()
