"""Confronto entre os eventos do aparelho e os eventos lidos no fluxo.

O análogo justo do AHI da ResMed é `hypopnea50_per_usage_h`: queda de 50% por
≥10 s, e cada trecho entra uma vez. Apneias de 75% e de 90% são subconjuntos
mais fundos, não parcelas para somar.
"""

import numpy as np
import pandas as pd
from scipy import stats

MATCH_MARGIN_S = 15
HIGH_LEAK_L_MIN = 24.0
SESSION_EDGE = pd.Timedelta(minutes=5)
POST_SURGE = pd.Timedelta(seconds=30)
SHORT_DURATION_S = (10.0, 12.0)
DEVICE_RESPIRATORY = ["obstructive_apnea", "central_apnea", "unclassified_apnea", "hypopnea"]
CURVE = {
    0.30: "hypopnea30_per_usage_h",
    0.40: "hypopnea40_per_usage_h",
    0.50: "hypopnea50_per_usage_h",
    0.75: "apnea75_per_usage_h",
    0.90: "apnea90_per_usage_h",
}


def _intervals(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    start = pd.to_datetime(frame["timestamp"]).to_numpy(dtype="datetime64[ns]")
    duration = pd.to_numeric(frame.get("duration_s", 0), errors="coerce").fillna(0).to_numpy(dtype=float)
    end = start + duration.astype("timedelta64[s]")
    return start, end


def points_match_intervals(points: np.ndarray, starts: np.ndarray, ends: np.ndarray, margin_s: float) -> np.ndarray:
    """Verdadeiro quando o instante cai num intervalo expandido pela folga."""
    matched = np.zeros(len(points), dtype=bool)
    if len(points) == 0 or len(starts) == 0:
        return matched
    margin = np.timedelta64(int(margin_s * 1000), "ms")
    covered = (points[:, None] >= starts - margin) & (points[:, None] <= ends + margin)
    matched[covered.any(axis=1)] = True
    return matched


def _match_by_night(reference: pd.DataFrame, candidates: pd.DataFrame, margin_s: float) -> np.ndarray:
    matched = np.zeros(len(reference), dtype=bool)
    if reference.empty:
        return matched
    reference = reference.reset_index(drop=True)
    grouped = {night: group for night, group in candidates.groupby("night")} if not candidates.empty else {}
    for night, group in reference.groupby("night"):
        others = grouped.get(night, candidates.iloc[0:0])
        starts, ends = _intervals(others) if not others.empty else (np.array([], dtype="datetime64[ns]"), np.array([], dtype="datetime64[ns]"))
        points = pd.to_datetime(group["timestamp"]).to_numpy(dtype="datetime64[ns]")
        matched[group.index.to_numpy()] = points_match_intervals(points, starts, ends, margin_s)
    return matched


def event_agreement(
    device: pd.DataFrame,
    own: pd.DataFrame,
    device_types: list[str],
    own_type: str,
    margin_s: float = MATCH_MARGIN_S,
) -> dict:
    """Sensibilidade: marca do aparelho cai no evento próprio. VPP: o inverso."""
    reference = device[device["event_type"].isin(device_types)].copy()
    candidates = own[own["event_type"] == own_type].copy()
    device_hit = _match_by_night(reference, candidates, margin_s)
    own_hit = _match_by_night(candidates, reference, margin_s)
    sensitivity = float(device_hit.mean()) if len(device_hit) else np.nan
    ppv = float(own_hit.mean()) if len(own_hit) else np.nan
    return {
        "device_events": int(len(reference)),
        "own_events": int(len(candidates)),
        "sensitivity": sensitivity,
        "ppv": ppv,
        "device_matched": device_hit,
        "own_matched": own_hit,
        "reference_index": reference.index.to_numpy(),
        "candidate_frame": candidates.reset_index(drop=True),
        "reference_frame": reference.reset_index(drop=True),
    }


def lin_ccc(reference: pd.Series, estimate: pd.Series) -> float:
    """Coeficiente de concordância de Lin."""
    frame = pd.DataFrame({"reference": reference, "estimate": estimate}).dropna()
    if len(frame) < 3:
        return np.nan
    x = frame["reference"].to_numpy(float)
    y = frame["estimate"].to_numpy(float)
    vx, vy = x.var(ddof=1), y.var(ddof=1)
    covariance = np.cov(x, y, ddof=1)[0, 1]
    return float(2 * covariance / (vx + vy + (x.mean() - y.mean()) ** 2))


def bland_altman(reference: pd.Series, estimate: pd.Series) -> dict:
    """Viés = estimativa − referência. Viés positivo: o fluxo conta mais que o aparelho."""
    frame = pd.DataFrame({"reference": reference, "estimate": estimate}).dropna()
    if len(frame) < 3:
        return {"n": int(len(frame)), "bias": np.nan, "loa_low": np.nan, "loa_high": np.nan, "bias_vs_level": np.nan}
    difference = frame["estimate"] - frame["reference"]
    level = (frame["estimate"] + frame["reference"]) / 2
    bias = float(difference.mean())
    spread = float(difference.std(ddof=1))
    slope = stats.spearmanr(level, difference).statistic if level.nunique() > 2 and difference.nunique() > 2 else np.nan
    return {
        "n": int(len(frame)),
        "bias": bias,
        "loa_low": bias - 1.96 * spread,
        "loa_high": bias + 1.96 * spread,
        "bias_vs_level": float(slope) if pd.notna(slope) else np.nan,
        "level": level,
        "difference": difference,
    }


def threshold_curve(features: pd.DataFrame, min_usage: float = 4.0) -> pd.DataFrame:
    sample = features[features["usage_hours"] >= min_usage]
    rows = []
    for drop, column in CURVE.items():
        values = sample[column]
        rows.append({"drop_fraction": drop, "source": column, "median_per_h": values.median(), "n": int(values.notna().sum())})
    device = sample["ahi"]
    rows.append({"drop_fraction": np.nan, "source": "ahi", "median_per_h": device.median(), "n": int(device.notna().sum())})
    return pd.DataFrame(rows)


def _near_any(times: np.ndarray, anchors: np.ndarray, window: np.timedelta64) -> np.ndarray:
    if len(times) == 0:
        return np.array([], dtype=bool)
    if len(anchors) == 0:
        return np.zeros(len(times), dtype=bool)
    return ((times[:, None] >= anchors) & (times[:, None] <= anchors + window)).any(axis=1)


def discordant_breakdown(
    device: pd.DataFrame,
    own: pd.DataFrame,
    signals: pd.DataFrame,
    sessions: pd.DataFrame,
    nights: pd.DataFrame,
    surges: pd.DataFrame,
    wakes: pd.DataFrame,
    margin_s: float = MATCH_MARGIN_S,
) -> pd.DataFrame:
    """Onde estão os eventos de fluxo de 50% que o aparelho não marcou, e o inverso."""
    agreement = event_agreement(device, own, DEVICE_RESPIRATORY, "hypopnea50", margin_s)
    own_events = agreement["candidate_frame"].copy()
    device_events = agreement["reference_frame"].copy()
    own_events["unmatched"] = ~agreement["own_matched"]
    device_events["unmatched"] = ~agreement["device_matched"]

    def annotate(events: pd.DataFrame) -> pd.DataFrame:
        if events.empty:
            events["high_leak"] = pd.Series(dtype=bool)
            events["session_start"] = pd.Series(dtype=bool)
            events["ramp"] = pd.Series(dtype=bool)
            events["wake_like"] = pd.Series(dtype=bool)
            events["post_surge"] = pd.Series(dtype=bool)
            events["short_duration"] = pd.Series(dtype=bool)
            return events
        events = events.copy()
        events["timestamp"] = pd.to_datetime(events["timestamp"])
        leak = _leak_at(events, signals)
        events["high_leak"] = leak > HIGH_LEAK_L_MIN
        events["session_start"] = _session_edge(events, sessions, SESSION_EDGE, ramp_only=False)
        events["ramp"] = _session_edge(events, sessions, None, ramp_only=True, nights=nights)
        wake_minutes = set(pd.to_datetime(wakes["timestamp"]).dt.floor("min")) if not wakes.empty else set()
        events["wake_like"] = events["timestamp"].dt.floor("min").isin(wake_minutes)
        events["post_surge"] = False
        events["short_duration"] = events["duration_s"].between(*SHORT_DURATION_S) if "duration_s" in events else False
        if not surges.empty:
            for night, group in events.groupby("night"):
                anchors = pd.to_datetime(surges.loc[surges["night"] == night, "timestamp"]).to_numpy(dtype="datetime64[ns]")
                times = group["timestamp"].to_numpy(dtype="datetime64[ns]")
                events.loc[group.index, "post_surge"] = _near_any(times, anchors, np.timedelta64(30, "s"))
        return events

    own_events = annotate(own_events)
    device_events = annotate(device_events)
    flags = ["high_leak", "session_start", "ramp", "wake_like", "post_surge", "short_duration"]
    rows = []
    for flag in flags + ["unexplained"]:
        rows.append(_flag_row(flag, flags, own_events, device_events))
    summary = pd.DataFrame(rows)
    summary.attrs["sensitivity"] = agreement["sensitivity"]
    summary.attrs["ppv"] = agreement["ppv"]
    summary.attrs["device_events"] = agreement["device_events"]
    summary.attrs["own_events"] = agreement["own_events"]
    return summary


def _flag_row(flag: str, flags: list[str], own_events: pd.DataFrame, device_events: pd.DataFrame) -> dict:
    def count(frame: pd.DataFrame) -> tuple[int, int, float]:
        unmatched = frame[frame["unmatched"]] if "unmatched" in frame else frame.iloc[0:0]
        total = int(len(unmatched))
        if flag == "unexplained":
            if total == 0 or not flags:
                hits = 0
            else:
                hits = int((~unmatched[flags].fillna(False).any(axis=1)).sum())
        else:
            hits = int(unmatched[flag].fillna(False).sum()) if total and flag in unmatched else 0
        return hits, total, hits / total if total else np.nan

    own_hits, own_total, own_pct = count(own_events)
    device_hits, device_total, device_pct = count(device_events)
    return {
        "category": flag,
        "own_unmatched": own_hits,
        "own_unmatched_total": own_total,
        "own_pct": own_pct,
        "device_unmatched": device_hits,
        "device_unmatched_total": device_total,
        "device_pct": device_pct,
    }


def _leak_at(events: pd.DataFrame, signals: pd.DataFrame) -> pd.Series:
    if signals.empty:
        return pd.Series(np.nan, index=events.index)
    left = events[["timestamp"]].copy()
    left["_row"] = np.arange(len(left))
    right = signals[["timestamp", "leak"]].dropna(subset=["timestamp"]).sort_values("timestamp")
    left = left.sort_values("timestamp")
    merged = pd.merge_asof(left, right, on="timestamp", direction="nearest", tolerance=pd.Timedelta(seconds=2))
    merged = merged.sort_values("_row")
    return pd.Series(merged["leak"].to_numpy(), index=events.index)


def _session_edge(events, sessions, window, ramp_only: bool, nights: pd.DataFrame | None = None) -> pd.Series:
    result = pd.Series(False, index=events.index)
    if sessions.empty:
        return result
    ramp = {}
    if ramp_only and nights is not None and not nights.empty:
        indexed = nights.set_index("night")[["ramp_enabled", "ramp_time_min"]]
        ramp = {pd.Timestamp(key): value for key, value in indexed.to_dict("index").items()}
    for night, group in events.groupby("night"):
        starts = pd.to_datetime(sessions.loc[pd.to_datetime(sessions["night"]) == pd.Timestamp(night), "session_start"]).dropna()
        if starts.empty:
            continue
        local_window = window
        if ramp_only:
            spec = ramp.get(pd.Timestamp(night))
            if spec is None or not spec.get("ramp_enabled"):
                continue
            local_window = pd.Timedelta(minutes=float(spec.get("ramp_time_min") or 0))
        anchors = starts.to_numpy(dtype="datetime64[ns]")
        times = pd.to_datetime(group["timestamp"]).to_numpy(dtype="datetime64[ns]")
        if local_window is None or local_window <= pd.Timedelta(0):
            continue
        result.loc[group.index] = _near_any(times, anchors, np.timedelta64(int(local_window.total_seconds()), "s"))
    return result


def summarize_undercount(
    device_median: float,
    flow50_median: float,
    flow30_median: float,
    sensitivity: float,
    ppv: float,
    unexplained_own_pct: float,
    bias: float,
    ccc: float,
) -> str:
    """Texto da conclusão. Não transforma proximidade em prova de polissonografia."""
    ratio = device_median / flow50_median if flow50_median else np.nan
    if pd.notna(sensitivity) and sensitivity < 0.7:
        claim = (
            "Igualar o percentual não torna os dois o mesmo critério: o detector usa ventilação média "
            "contra uma base local, e a ResMed usa queda do fluxo. Os conjuntos de eventos não se cobrem."
        )
    elif pd.notna(ratio) and ratio >= 0.7:
        claim = (
            "No percentual de 50%, as medianas ficam próximas e o fluxo encontra a maior parte dos eventos do aparelho. "
            "O excesso da queda de 30% vem da definição mais sensível, sem SpO2 e sem despertar."
        )
    elif pd.notna(ratio):
        claim = (
            "O fluxo encontra os eventos do aparelho, mas ainda conta mais. "
            "A diferença que sobra não está explicada só pelo percentual de queda."
        )
    else:
        claim = "Não há mediana suficiente para comparar o AHI com a queda de 50%."
    return (
        f"AHI mediano {device_median:.2f}/h; fluxo a 50% {flow50_median:.2f}/h "
        f"(razão {ratio:.2f}); fluxo a 30% {flow30_median:.2f}/h. "
        f"Sensibilidade do fluxo aos eventos do aparelho {sensitivity:.0%}; "
        f"valor preditivo {ppv:.0%}. Viés (fluxo − aparelho) {bias:.2f}/h; CCC {ccc:.2f}. "
        f"Dos eventos de 50% sem par no aparelho, {unexplained_own_pct:.0%} não caem em vazamento, "
        f"início de sessão, rampa, vigília estimada, pós-surto ou duração de 10–12 s. {claim} "
        "Isto não é polissonografia: falta EEG e oximetria de evento."
    )
