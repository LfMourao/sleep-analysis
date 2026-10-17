"""Segmentação respiração a respiração do fluxo de 25 Hz (BRP) da ResMed.

Cada respiração vai de um início de inspiração (cruzamento negativo -> positivo do
fluxo filtrado) até o próximo. Pausas sem respiração (apneias) viram uma única
"respiração" longa com volume quase nulo, marcada em `long_pause`.
"""

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt

from sleep_analysis.edf import read_edf, signal_timestamps

SAMPLE_RATE_HZ = 25
CROSSING_CUTOFF_HZ = 1.0
SHAPE_CUTOFF_HZ = 5.0
# Oscilações menores que isso (ex.: cardiogênicas durante apneia) não abrem nova respiração
MIN_EXCURSION_L_S = 0.04
MIN_BREATH_S = 1.5
MAX_BREATH_S = 15.0
# Limiar da ResMed para "vazamento alto"
MAX_VALID_LEAK_L_MIN = 24.0
LITERS_PER_SECOND_TO_PER_MINUTE = 60


def lowpass(signal: np.ndarray, cutoff_hz: float) -> np.ndarray:
    b, a = butter(2, cutoff_hz / (SAMPLE_RATE_HZ / 2))
    return filtfilt(b, a, signal)


def find_breath_starts(smooth: np.ndarray) -> np.ndarray:
    """Inícios de inspiração, exigindo excursão mínima positiva e negativa entre eles."""
    crossings = np.where((smooth[:-1] < 0) & (smooth[1:] >= 0))[0] + 1
    if crossings.size == 0:
        return crossings
    starts = [crossings[0]]
    for crossing in crossings[1:]:
        segment = smooth[starts[-1] : crossing]
        if segment.max() >= MIN_EXCURSION_L_S and segment.min() <= -MIN_EXCURSION_L_S:
            starts.append(crossing)
    return np.asarray(starts)


def breath_features(shape: np.ndarray, smooth: np.ndarray, start: int, end: int) -> dict:
    dt = 1 / SAMPLE_RATE_HZ
    below = np.where(smooth[start:end] < 0)[0]
    insp_len = int(below[0]) if below.size else end - start
    inspiration = np.clip(shape[start : start + insp_len], 0, None)
    ttot = (end - start) * dt
    ti = insp_len * dt
    vt = float(inspiration.sum() * dt)
    peak = float(inspiration.max()) if inspiration.size else 0.0
    if peak > 0 and insp_len >= 5:
        mid_flow = inspiration[insp_len // 2]
        ned = (peak - mid_flow) / peak * 100
        flatness = inspiration.mean() / peak
    else:
        ned = np.nan
        flatness = np.nan
    return {
        "ttot": ttot,
        "ti": ti,
        "te": ttot - ti,
        "vt": vt,
        "peak_flow": peak,
        "ned": ned,
        "flatness": flatness,
        "has_gap": bool(np.isnan(shape[start:end]).any()),
    }


def segment_session(brp_path: Path) -> pd.DataFrame:
    edf = read_edf(brp_path)
    physical = edf.read_physical()
    flow = physical["Flow.40ms"]
    n_records = flow.shape[0]
    if n_records == 0:
        return pd.DataFrame()
    flow = flow.reshape(-1)
    timestamps = signal_timestamps(edf, flow.size // n_records, n_records)

    missing = np.isnan(flow)
    filled = np.where(missing, 0.0, flow)
    smooth = lowpass(filled, CROSSING_CUTOFF_HZ)
    shape = lowpass(filled, SHAPE_CUTOFF_HZ)
    shape[missing] = np.nan

    starts = find_breath_starts(smooth)
    rows = []
    for start, end in zip(starts[:-1], starts[1:]):
        row = breath_features(shape, smooth, start, end)
        row["t_start"] = timestamps[start]
        rows.append(row)
    return pd.DataFrame(rows)


def load_flow(night_dir: Path) -> pd.DataFrame:
    """Fluxo bruto de 25 Hz de todas as sessões da noite, para inspeção visual."""
    frames = []
    for brp_path in sorted(night_dir.glob("*_BRP.edf")):
        edf = read_edf(brp_path)
        flow = edf.read_physical()["Flow.40ms"]
        if flow.shape[0] == 0:
            continue
        frames.append(
            pd.DataFrame({"timestamp": signal_timestamps(edf, flow.shape[1], flow.shape[0]), "flow": flow.reshape(-1)})
        )
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["timestamp", "flow"])


def load_leak(night_dir: Path) -> pd.DataFrame:
    frames = []
    for pld_path in sorted(night_dir.glob("*_PLD.edf")):
        edf = read_edf(pld_path)
        leak = edf.read_physical()["Leak.2s"]
        if leak.shape[0] == 0:
            continue
        frames.append(
            pd.DataFrame(
                {
                    "timestamp": signal_timestamps(edf, leak.shape[1], leak.shape[0]),
                    "leak": leak.reshape(-1) * LITERS_PER_SECOND_TO_PER_MINUTE,
                }
            )
        )
    if not frames:
        return pd.DataFrame(columns=["timestamp", "leak"])
    return pd.concat(frames).sort_values("timestamp").reset_index(drop=True)


def segment_night(night_dir: Path) -> pd.DataFrame:
    frames = []
    for brp_path in sorted(night_dir.glob("*_BRP.edf")):
        breaths = segment_session(brp_path)
        if breaths.empty:
            continue
        breaths.insert(0, "session_start", pd.Timestamp(brp_path.stem[:15].replace("_", "T")))
        frames.append(breaths)
    if not frames:
        return pd.DataFrame()

    breaths = pd.concat(frames, ignore_index=True).sort_values("t_start").reset_index(drop=True)
    breaths["t_start"] = breaths["t_start"].astype("datetime64[ms]")
    breaths["ventilation"] = breaths["vt"] / breaths["ttot"] * 60
    breaths["rate"] = 60 / breaths["ttot"]
    breaths["long_pause"] = breaths["ttot"] > MAX_BREATH_S

    leak = load_leak(night_dir)
    if leak.empty:
        breaths["leak"] = np.nan
    else:
        leak["timestamp"] = leak["timestamp"].astype("datetime64[ms]")
        breaths = pd.merge_asof(
            breaths, leak, left_on="t_start", right_on="timestamp", direction="nearest", tolerance=pd.Timedelta("4s")
        ).drop(columns="timestamp")

    breaths["valid"] = (
        ~breaths["has_gap"]
        & (breaths["ttot"] >= MIN_BREATH_S)
        & (breaths["leak"] <= MAX_VALID_LEAK_L_MIN)
    )
    breaths.insert(0, "night", pd.Timestamp(night_dir.name))
    return breaths.drop(columns="has_gap")
