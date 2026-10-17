"""Eventos e métricas por noite a partir das respirações segmentadas (breaths.py).

Tudo é relativo à linha de base local (mediana das respirações anteriores), para não
depender de limiares absolutos que mudam com posição, vazamento ou pressão.

Eventos (respiratory_events):
- surge: salto de ventilação típico de microdespertar (Khoo 1996; patente ResMed de RERA)
- hypopnea30: ventilação média <= 70% da base por >= 10 s (inclui apneias); critério
  de fluxo da AASM, mais sensível que os 50% da ResMed
- hypopnea50: ventilação média <= 50% por >= 10 s, no critério de hipopneia do guia
  clínico do AirSense 10; também inclui apneias
- apnea75: ventilação média <= 25% por >= 10 s (queda de 75%, definição de apneia da ResMed)
- apnea90: ventilação média <= 10% por >= 10 s (queda de 90%, definição de apneia da AASM)
- rera_like: surge precedido por respirações achatadas (Hosselet 1998; patente ResMed)
- wake_like: minuto de respiração irregular, padrão de vigília (Ayappa 2008)
"""

import numpy as np
import pandas as pd
from scipy.signal import welch

BASELINE_BREATHS = 40
BASELINE_MIN_BREATHS = 20
SURGE_RATIO = 1.5
SURGE_WINDOW_BREATHS = 3
SURGE_MIN_HIGH_BREATHS = 2
SURGE_REFRACTORY_S = 15
# A queda de 30% vale para a média do evento; respirações isoladas podem passar um pouco
HYPOPNEA_VENT_RATIO = 0.7
HYPOPNEA_EDGE_VENT_RATIO = 0.8
HYPOPNEA_EDGE_MARGIN = HYPOPNEA_EDGE_VENT_RATIO - HYPOPNEA_VENT_RATIO
HYPOPNEA_MIN_S = 10
HYPOPNEA_SURGE_WINDOW_S = 15
# Quedas gravadas além do hypopnea30. A de 40% só vira índice (curva de limiar);
# 50%, 75% e 90% também viram eventos.
DROP_INDEXES = {"hypopnea40": 0.40, "hypopnea50": 0.50, "apnea75": 0.75, "apnea90": 0.90}
STORED_DROP_EVENTS = ("hypopnea50", "apnea75", "apnea90")
# Limiares de limitação de fluxo usados pelo AirwayLab
FLOW_LIMITED_NED = 34
FLOW_LIMITED_FLATNESS = 0.85
# Antes dos RERAs da própria ResMed a flatness sobe ~0,1 acima da base, mas raramente
# chega a 0,85; por isso o critério do rera_like é relativo à base local
RERA_LOOKBACK_BREATHS = 5
RERA_MIN_FLATTENED_BREATHS = 3
RERA_FLATNESS_ABOVE_BASELINE = 0.06
# Calibrados por percentil nas 67 noites a 7,0 cmH2O até 22/09/2026:
# estável ~ p25 em janelas de 5 min; vigília ~ p95 (ttot) e p90 (vt) em janelas de 1 min
STABLE_WINDOW = "5min"
STABLE_MIN_BREATHS = 30
STABLE_MAX_CV_TTOT = 0.07
STABLE_MAX_CV_VT = 0.12
WAKE_WINDOW = "1min"
WAKE_MIN_BREATHS = 8
WAKE_MIN_CV_TTOT = 0.21
WAKE_MIN_CV_VT = 0.32
SLEEP_ONSET_QUIET_MIN = 10
HIGH_RATE_ABOVE_MEDIAN_BPM = 4
PERIODIC_BAND_HZ = (0.01, 0.03)
PERIODIC_TOTAL_BAND_HZ = (0.005, 0.2)
PERIODIC_MIN_SESSION_S = 1800


def add_baseline(breaths: pd.DataFrame) -> pd.DataFrame:
    breaths = breaths.copy()
    for column in ["ventilation", "vt", "flatness"]:
        masked = breaths[column].where(breaths["valid"] & ~breaths["long_pause"])
        breaths[f"{column}_baseline"] = masked.groupby(breaths["session_start"]).transform(
            lambda values: values.rolling(BASELINE_BREATHS, min_periods=BASELINE_MIN_BREATHS).median().shift(1)
        )
    breaths["vent_ratio"] = breaths["ventilation"] / breaths["ventilation_baseline"]
    breaths["vt_ratio"] = breaths["vt"] / breaths["vt_baseline"]
    breaths["t_end"] = breaths["t_start"] + pd.to_timedelta(breaths["ttot"], unit="s")
    breaths["flow_limited"] = (breaths["ned"] >= FLOW_LIMITED_NED) | (breaths["flatness"] >= FLOW_LIMITED_FLATNESS)
    return breaths


def find_runs(mask: pd.Series, sessions: pd.Series) -> list[tuple[int, int]]:
    """Trechos contíguos (posições início/fim inclusivas) onde mask é verdadeiro, sem cruzar sessões."""
    flags = mask.to_numpy(dtype=bool)
    session_values = sessions.to_numpy()
    breaks = np.ones(len(flags), dtype=bool)
    breaks[1:] = (flags[1:] != flags[:-1]) | (session_values[1:] != session_values[:-1])
    starts = np.flatnonzero(flags & breaks)
    ends = np.flatnonzero(flags & np.append(breaks[1:], True))
    return list(zip(starts.tolist(), ends.tolist()))


def detect_surges(breaths: pd.DataFrame) -> pd.DataFrame:
    high = (breaths["valid"] & (breaths["vent_ratio"] >= SURGE_RATIO)).astype(int)
    same_session = breaths["session_start"]
    count = high.copy()
    peak = breaths["vent_ratio"].copy()
    for offset in range(1, SURGE_WINDOW_BREATHS):
        shifted_same = same_session.shift(-offset) == same_session
        count += high.shift(-offset, fill_value=0).where(shifted_same, 0)
        peak = np.fmax(peak, breaths["vent_ratio"].shift(-offset).where(shifted_same))
    candidates = np.where((high == 1) & (count >= SURGE_MIN_HIGH_BREATHS))[0]

    rows = []
    last_time = None
    for position in candidates:
        time = breaths["t_start"].iat[position]
        if last_time is not None and (time - last_time).total_seconds() < SURGE_REFRACTORY_S:
            continue
        last_time = time
        rows.append({"position": position, "timestamp": time, "intensity": float(peak.iat[position])})
    return pd.DataFrame(rows, columns=["position", "timestamp", "intensity"])


def ratios_for_drop(drop_fraction: float) -> tuple[float, float]:
    """Converte uma queda (0,30 = cai 30%) nos limiares médio e de borda da ventilação."""
    if not 0 < drop_fraction < 1:
        raise ValueError(f"Queda fora do intervalo (0, 1): {drop_fraction}")
    mean_ratio = 1 - drop_fraction
    return mean_ratio, min(mean_ratio + HYPOPNEA_EDGE_MARGIN, 0.99)


def detect_hypopneas(
    breaths: pd.DataFrame,
    surges: pd.DataFrame,
    vent_ratio: float = HYPOPNEA_VENT_RATIO,
    edge_vent_ratio: float = HYPOPNEA_EDGE_VENT_RATIO,
    min_s: float = HYPOPNEA_MIN_S,
) -> tuple[pd.DataFrame, np.ndarray]:
    # Ventilação, não volume: a pausa de uma apneia cai na expiração da respiração anterior,
    # que mantém volume normal mas fica longa
    low = breaths["valid"] & (breaths["vent_ratio"] <= edge_vent_ratio)
    in_hypopnea = np.zeros(len(breaths), dtype=bool)
    surge_times = surges["timestamp"].to_numpy(dtype="datetime64[ns]")
    starts = breaths["t_start"].to_numpy(dtype="datetime64[ns]")
    ends = breaths["t_end"].to_numpy(dtype="datetime64[ns]")
    ratios = breaths["vent_ratio"].to_numpy(dtype=float)
    surge_window = np.timedelta64(int(HYPOPNEA_SURGE_WINDOW_S * 1e9), "ns")
    rows = []
    for start, end in find_runs(low, breaths["session_start"]):
        begin = starts[start]
        finish = ends[end]
        duration = (finish - begin) / np.timedelta64(1, "s")
        segment = ratios[start : end + 1]
        if duration < min_s or segment.mean() > vent_ratio:
            continue
        in_hypopnea[start : end + 1] = True
        with_surge = bool(((surge_times >= finish) & (surge_times <= finish + surge_window)).any())
        rows.append({"timestamp": pd.Timestamp(begin), "duration_s": float(duration), "with_surge": with_surge})
    return pd.DataFrame(rows, columns=["timestamp", "duration_s", "with_surge"]), in_hypopnea


def detect_rera_like(breaths: pd.DataFrame, surges: pd.DataFrame, in_hypopnea: np.ndarray) -> pd.DataFrame:
    flattened = (
        breaths["valid"]
        & (
            (breaths["flatness"] >= breaths["flatness_baseline"] + RERA_FLATNESS_ABOVE_BASELINE)
            | (breaths["ned"] >= FLOW_LIMITED_NED)
        )
    ).to_numpy()
    rows = []
    for position in surges["position"]:
        start = position - RERA_LOOKBACK_BREATHS
        if start < 0 or breaths["session_start"].iat[start] != breaths["session_start"].iat[position]:
            continue
        n_flattened = int(flattened[start:position].sum())
        if n_flattened < RERA_MIN_FLATTENED_BREATHS or in_hypopnea[start:position].any():
            continue
        begin = breaths["t_start"].iat[start]
        rows.append(
            {
                "timestamp": begin,
                "duration_s": (breaths["t_start"].iat[position] - begin).total_seconds(),
                "n_breaths": n_flattened,
            }
        )
    return pd.DataFrame(rows, columns=["timestamp", "duration_s", "n_breaths"])


def mark_events(breaths: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Detecta surge, hypopnea30 e rera_like e marca em `in_event` as respirações envolvidas."""
    surges = detect_surges(breaths)
    hypopneas, in_hypopnea = detect_hypopneas(breaths, surges)
    reras = detect_rera_like(breaths, surges, in_hypopnea)
    in_event = in_hypopnea.copy()
    for position in surges["position"]:
        in_event[position : position + SURGE_WINDOW_BREATHS] = True
    breaths["in_event"] = in_event
    return surges, hypopneas, reras


def window_stats(breaths: pd.DataFrame, window: str, min_breaths: int) -> pd.DataFrame:
    """CV da duração e do volume por janela, sem as respirações de eventos (contados à parte)."""
    in_event = breaths["in_event"] if "in_event" in breaths else pd.Series(False, index=breaths.index)
    valid = breaths[breaths["valid"]].assign(in_event=in_event)
    keys = ["session_start", valid["t_start"].dt.floor(window)]
    events_per_window = valid.groupby(keys)["in_event"].sum().rename("n_event_breaths")
    regular = valid[~valid["long_pause"] & ~valid["in_event"]]
    grouped = regular.groupby(["session_start", regular["t_start"].dt.floor(window)])
    stats = grouped.agg(
        n=("ttot", "size"),
        ttot_mean=("ttot", "mean"),
        ttot_std=("ttot", "std"),
        vt_mean=("vt", "mean"),
        vt_std=("vt", "std"),
    ).join(events_per_window)
    stats = stats[stats["n"] >= min_breaths]
    stats["cv_ttot"] = stats["ttot_std"] / stats["ttot_mean"]
    stats["cv_vt"] = stats["vt_std"] / stats["vt_mean"]
    return stats.reset_index().rename(columns={"t_start": "window_start"})[
        ["session_start", "window_start", "n", "n_event_breaths", "cv_ttot", "cv_vt"]
    ]


def find_sleep_onset(wake_windows: pd.DataFrame) -> pd.Timestamp | None:
    """Início do primeiro trecho de SLEEP_ONSET_QUIET_MIN minutos seguidos sem padrão de vigília."""
    quiet = wake_windows.loc[~wake_windows["wake_like"], "window_start"].sort_values().reset_index(drop=True)
    if quiet.empty:
        return None
    new_run = quiet.diff() != pd.Timedelta(WAKE_WINDOW)
    run_id = new_run.cumsum()
    run_length = quiet.groupby(run_id).transform("size")
    onset = quiet[run_length >= SLEEP_ONSET_QUIET_MIN]
    return onset.iloc[0] if not onset.empty else None


def periodicity_index(breaths: pd.DataFrame) -> float:
    """Fração da potência da ventilação em ciclos de 30 a 100 s (respiração periódica)."""
    weighted = []
    for _, session in breaths[breaths["valid"]].groupby("session_start"):
        seconds = (session["t_start"] - session["t_start"].iloc[0]).dt.total_seconds().to_numpy()
        if seconds.size < 2 or seconds[-1] < PERIODIC_MIN_SESSION_S:
            continue
        grid = np.arange(0, seconds[-1], 1.0)
        ventilation = np.interp(grid, seconds, session["ventilation"].to_numpy())
        frequencies, power = welch(ventilation - ventilation.mean(), fs=1.0, nperseg=512)
        total = (frequencies >= PERIODIC_TOTAL_BAND_HZ[0]) & (frequencies <= PERIODIC_TOTAL_BAND_HZ[1])
        band = (frequencies >= PERIODIC_BAND_HZ[0]) & (frequencies <= PERIODIC_BAND_HZ[1])
        weighted.append((power[band].sum() / power[total].sum(), seconds[-1]))
    if not weighted:
        return np.nan
    values, weights = zip(*weighted)
    return float(np.average(values, weights=weights))


def analyze_night(breaths: pd.DataFrame, device_flow_limitation: pd.Series | None = None) -> tuple[dict, pd.DataFrame]:
    night = breaths["night"].iat[0]
    breaths = add_baseline(breaths.sort_values("t_start").reset_index(drop=True))
    surges, hypopneas, reras = mark_events(breaths)

    wake_windows = window_stats(breaths, WAKE_WINDOW, WAKE_MIN_BREATHS)
    wake_windows["wake_like"] = (wake_windows["cv_ttot"] >= WAKE_MIN_CV_TTOT) & (
        wake_windows["cv_vt"] >= WAKE_MIN_CV_VT
    )
    onset = find_sleep_onset(wake_windows)
    if onset is None:
        return {"night": night, "sleep_hours": 0.0}, pd.DataFrame()

    wake_starts = set(wake_windows.loc[wake_windows["wake_like"], "window_start"])
    breath_minute = breaths["t_start"].dt.floor(WAKE_WINDOW)
    breaths["asleep"] = (breaths["t_start"] >= onset) & ~breath_minute.isin(wake_starts)
    scored = breaths["valid"] & breaths["asleep"]
    sleep_hours = breaths.loc[scored, "ttot"].sum() / 3600
    if sleep_hours == 0:
        return {"night": night, "sleep_hours": 0.0}, pd.DataFrame()

    night_end = breaths["t_end"].max()
    span = (night_end - onset).total_seconds()

    def third_of(times: pd.Series) -> pd.Series:
        times = pd.to_datetime(times)
        return np.minimum(((times - onset).dt.total_seconds() / span * 3).astype(int), 2) + 1

    breaths["third"] = third_of(breaths["t_start"])

    def is_scored(times: pd.Series) -> np.ndarray:
        times = pd.to_datetime(times)
        minute = times.dt.floor(WAKE_WINDOW)
        return ((times >= onset) & ~minute.isin(wake_starts)).to_numpy()

    detected_surges = surges
    surges = surges[is_scored(surges["timestamp"])]
    hypopneas = hypopneas[is_scored(hypopneas["timestamp"])]
    reras = reras[is_scored(reras["timestamp"])]
    # Os limiares extras não entram em `in_event`: stable_pct continua contando só hypopnea30 e surge.
    drop_events = {}
    for name, drop_fraction in DROP_INDEXES.items():
        mean_ratio, edge_ratio = ratios_for_drop(drop_fraction)
        found, _ = detect_hypopneas(breaths, detected_surges, vent_ratio=mean_ratio, edge_vent_ratio=edge_ratio)
        drop_events[name] = found[is_scored(found["timestamp"])] if not found.empty else found

    stable_windows = window_stats(breaths[breaths["asleep"]], STABLE_WINDOW, STABLE_MIN_BREATHS)
    stable_windows["stable"] = (
        (stable_windows["cv_ttot"] <= STABLE_MAX_CV_TTOT)
        & (stable_windows["cv_vt"] <= STABLE_MAX_CV_VT)
        & (stable_windows["n_event_breaths"] == 0)
    )
    stable_windows["third"] = third_of(stable_windows["window_start"])

    after_onset = wake_windows[wake_windows["window_start"] >= onset].sort_values("window_start")
    wake_minutes = after_onset.loc[after_onset["wake_like"], "window_start"]
    wake_bouts = int(((wake_minutes.diff() != pd.Timedelta(WAKE_WINDOW))).sum()) if not wake_minutes.empty else 0

    asleep = breaths[scored]
    rate_limit = asleep["rate"].median() + HIGH_RATE_ABOVE_MEDIAN_BPM
    metrics = {
        "night": night,
        "sleep_onset": onset,
        "sleep_hours": sleep_hours,
        "breaths": len(asleep),
        "surge_index": len(surges) / sleep_hours,
        "surge_intensity_median": surges["intensity"].median(),
        "hypopnea30_index": len(hypopneas) / sleep_hours,
        "hypopnea30_count": len(hypopneas),
        "hypopnea30_with_surge_index": hypopneas["with_surge"].sum() / sleep_hours,
        "rera_like_index": len(reras) / sleep_hours,
        "flow_limited_pct": asleep["flow_limited"].mean() * 100,
        "ned_median": asleep["ned"].median(),
        "flatness_median": asleep["flatness"].median(),
        "stable_pct": stable_windows["stable"].mean() * 100 if not stable_windows.empty else np.nan,
        "wake_like_minutes": len(wake_minutes),
        "wake_like_bouts": wake_bouts,
        "periodicity_index": periodicity_index(breaths[breaths["asleep"]]),
        "resp_rate_median": asleep["rate"].median(),
        "resp_rate_high_pct": asleep.loc[asleep["rate"] > rate_limit, "ttot"].sum() / asleep["ttot"].sum() * 100,
        "ventilation_median": asleep["ventilation"].median(),
        "leak_median": breaths["leak"].median(),
        "invalid_pct": (~breaths["valid"]).mean() * 100,
    }
    for name, found in drop_events.items():
        metrics[f"{name}_index"] = len(found) / sleep_hours
        metrics[f"{name}_count"] = len(found)
    for third in (1, 2, 3):
        third_hours = asleep.loc[asleep["third"] == third, "ttot"].sum() / 3600
        third_surges = (third_of(surges["timestamp"]) == third).sum()
        metrics[f"surge_index_t{third}"] = third_surges / third_hours if third_hours else np.nan
        metrics[f"flow_limited_pct_t{third}"] = asleep.loc[asleep["third"] == third, "flow_limited"].mean() * 100
        windows = stable_windows[stable_windows["third"] == third]
        metrics[f"stable_pct_t{third}"] = windows["stable"].mean() * 100 if not windows.empty else np.nan
    if device_flow_limitation is not None and device_flow_limitation.notna().any():
        metrics["device_flow_lim_p95"] = device_flow_limitation.quantile(0.95)
        metrics["device_flow_lim_over_0_1_pct"] = (device_flow_limitation > 0.1).mean() * 100

    event_frames = [
        surges.assign(event_type="surge").drop(columns="position"),
        hypopneas.assign(event_type="hypopnea30"),
        reras.assign(event_type="rera_like"),
        after_onset.loc[after_onset["wake_like"], ["window_start"]]
        .rename(columns={"window_start": "timestamp"})
        .assign(event_type="wake_like", duration_s=60.0),
    ]
    for name in STORED_DROP_EVENTS:
        event_frames.append(drop_events[name].assign(event_type=name))
    events = pd.concat(event_frames, ignore_index=True)
    events.insert(0, "night", night)
    return metrics, events
