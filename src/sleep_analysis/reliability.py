"""Repetibilidade, resposta à pressão, convergência com o Garmin e nota do indicador."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

from sleep_analysis.paths import PROJECT_DIR

HALF_COLUMNS = {
    "ahi": ("device_respiratory_even", "device_respiratory_odd"),
    "oai": ("device_obstructive_even", "device_obstructive_odd"),
    "hi": ("device_hypopnea_even", "device_hypopnea_odd"),
    "cai": ("device_central_even", "device_central_odd"),
    "rin": ("device_arousal_even", "device_arousal_odd"),
    "snore_min_h": ("snore_even_min", "snore_odd_min"),
    "device_flow_lim_min_h": ("flow_lim_even_min", "flow_lim_odd_min"),
    "hypopnea30_per_usage_h": ("hypopnea30_even", "hypopnea30_odd"),
    "hypopnea50_per_usage_h": ("hypopnea50_even", "hypopnea50_odd"),
    "apnea90_per_usage_h": ("apnea90_even", "apnea90_odd"),
    "surge_index": ("surge_even", "surge_odd"),
    "rera_like_index": ("rera_like_even", "rera_like_odd"),
}


def load_indicator_config(path: Path | None = None) -> dict:
    path = path if path is not None else PROJECT_DIR / "config" / "indicator_weights.json"
    return json.loads(path.read_text(encoding="utf-8"))


def analysis_mask(features: pd.DataFrame, usage_min: float) -> pd.Series:
    mask = features["usage_hours"] >= usage_min
    if "partial" in features.columns:
        mask = mask & ~features["partial"].fillna(False)
    return mask


def icc_2_1(ratings: np.ndarray) -> float:
    """ICC(2,1), acordo absoluto, avaliadores aleatórios. Linhas são alvos, colunas são medidas."""
    ratings = np.asarray(ratings, float)
    if ratings.ndim != 2:
        return np.nan
    n_targets, n_raters = ratings.shape
    if n_targets < 2 or n_raters < 2 or not np.isfinite(ratings).all():
        return np.nan
    grand = ratings.mean()
    target_mean = ratings.mean(axis=1)
    rater_mean = ratings.mean(axis=0)
    between_targets = n_raters * np.sum((target_mean - grand) ** 2) / (n_targets - 1)
    between_raters = n_targets * np.sum((rater_mean - grand) ** 2) / (n_raters - 1)
    residual = ratings - target_mean[:, None] - rater_mean + grand
    error = np.sum(residual ** 2) / ((n_targets - 1) * (n_raters - 1))
    denominator = between_targets + (n_raters - 1) * error + n_raters * (between_raters - error) / n_targets
    if denominator == 0:
        return np.nan
    return float((between_targets - error) / denominator)


def adjacent_icc(features: pd.DataFrame, column: str, min_pairs: int, gap_days: int) -> float:
    """Pares não sobrepostos de noites vizinhas na mesma pressão."""
    data = features.dropna(subset=[column, "pressure", "night"]).sort_values("night")
    pairs = []
    for _, group in data.groupby("pressure"):
        group = group.sort_values("night")
        nights = group["night"].to_list()
        values = group[column].to_list()
        cursor = 0
        while cursor + 1 < len(group):
            gap = (nights[cursor + 1] - nights[cursor]).days
            if 0 < gap <= gap_days:
                pairs.append((values[cursor], values[cursor + 1]))
                cursor += 2
            else:
                cursor += 1
    if len(pairs) < min_pairs:
        return np.nan
    return icc_2_1(np.asarray(pairs, float))


def spearman_brown(correlation: float) -> float:
    if not np.isfinite(correlation) or correlation <= -1:
        return np.nan
    return float(2 * correlation / (1 + correlation))


def split_half_reliability(left: pd.Series, right: pd.Series, min_n: int) -> float:
    frame = pd.DataFrame({"left": left, "right": right}).dropna()
    if len(frame) < min_n or frame["left"].nunique() < 3 or frame["right"].nunique() < 3:
        return np.nan
    correlation = stats.pearsonr(frame["left"], frame["right"]).statistic
    return spearman_brown(float(correlation))


def minimum_detectable_change(values: pd.Series, icc: float) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if len(clean) < 3 or not np.isfinite(icc):
        return np.nan
    reliability = float(np.clip(icc, 0, 0.999))
    sem = float(clean.std(ddof=1) * np.sqrt(1 - reliability))
    return 1.96 * np.sqrt(2) * sem


def _safe_spearman(left: pd.Series, right: pd.Series, min_n: int) -> float:
    frame = pd.DataFrame({"left": left, "right": right}).dropna()
    if len(frame) < min_n or frame["left"].nunique() < 3 or frame["right"].nunique() < 3:
        return np.nan
    return float(stats.spearmanr(frame["left"], frame["right"]).statistic)


def partial_spearman(frame: pd.DataFrame, left: str, right: str, covariates: list[str], min_n: int) -> float:
    columns = [left, right, *covariates]
    data = frame[columns].dropna()
    usable = [column for column in covariates if data[column].nunique() >= 2] if not data.empty else []
    if len(data) < min_n or data[left].nunique() < 3 or data[right].nunique() < 3:
        return np.nan
    ranks = data.rank()

    def residual(target: str) -> np.ndarray:
        if not usable:
            return ranks[target].to_numpy(float)
        predictors = np.column_stack([np.ones(len(ranks)), ranks[usable].to_numpy(float)])
        beta, *_ = np.linalg.lstsq(predictors, ranks[target].to_numpy(float), rcond=None)
        return ranks[target].to_numpy(float) - predictors @ beta

    correlation = stats.pearsonr(residual(left), residual(right)).statistic
    return float(correlation)


def rolling_deviation(features: pd.DataFrame, column: str, window: int) -> pd.Series:
    ordered = features.sort_values("night")
    median = ordered[column].rolling(window, min_periods=max(5, window // 2), center=True).median()
    deviation = ordered[column] - median
    return deviation.reindex(features.index)


def pressure_response(
    features: pd.DataFrame,
    column: str,
    expected: str | None,
    window: int,
    gap_days: int,
    min_switches: int,
) -> dict:
    empty = {"effect_per_cm": np.nan, "n_switches": 0, "hit_rate": np.nan}
    if expected not in {"decreases", "increases"} or column not in features:
        return empty
    data = features.dropna(subset=[column, "pressure", "night"]).sort_values("night").copy()
    if "period" in data.columns:
        data = data[data["period"] != "recovery"]
    if len(data) < window:
        return empty
    data["previous_pressure"] = data["pressure"].shift()
    data["gap_days"] = data["night"].diff().dt.days
    switches = data[data["previous_pressure"].notna() & (data["pressure"] != data["previous_pressure"]) & (data["gap_days"] <= gap_days)]
    effects = []
    for switch in switches.itertuples():
        before = _contiguous(data, switch.night, switch.previous_pressure, window, gap_days, forward=False)
        after = _contiguous(data, switch.night, switch.pressure, window, gap_days, forward=True)
        if len(before) < 3 or len(after) < 3:
            continue
        delta_pressure = switch.pressure - switch.previous_pressure
        if delta_pressure == 0:
            continue
        effects.append((after[column].median() - before[column].median()) / delta_pressure)
    if len(effects) < min_switches:
        return {"effect_per_cm": np.nanmedian(effects) if effects else np.nan, "n_switches": len(effects), "hit_rate": np.nan}
    values = np.asarray(effects, float)
    hits = values < 0 if expected == "decreases" else values > 0
    return {"effect_per_cm": float(np.median(values)), "n_switches": int(len(values)), "hit_rate": float(hits.mean())}


def _contiguous(data: pd.DataFrame, origin: pd.Timestamp, pressure: float, window: int, gap_days: int, forward: bool) -> pd.DataFrame:
    subset = data[np.isclose(data["pressure"], pressure)].sort_values("night")
    if forward:
        subset = subset[subset["night"] >= origin]
        rows = subset.itertuples()
    else:
        subset = subset[subset["night"] < origin]
        rows = reversed(list(subset.itertuples()))
    chosen = []
    previous = origin
    for row in rows:
        gap = abs((row.night - previous).days)
        if gap > gap_days:
            break
        chosen.append(row.Index)
        previous = row.night
        if len(chosen) >= window:
            break
    return data.loc[chosen]


def _clip01(value: float) -> float:
    if not np.isfinite(value):
        return np.nan
    return float(np.clip(value, 0, 1))


def combine_scores(components: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Média ponderada, redistribuindo o peso dos critérios ausentes."""

    columns = {"evidence": "evidence_score"}

    def row_score(row: pd.Series) -> float:
        total = 0.0
        used = 0.0
        for key, weight in weights.items():
            value = row[columns.get(key, key)]
            if pd.notna(value):
                total += weight * float(value)
                used += weight
        return total / used if used else np.nan

    return components.apply(row_score, axis=1)


def weight_sensitivity(components: pd.DataFrame, weights: dict[str, float], delta: float = 0.1) -> pd.DataFrame:
    base = combine_scores(components, weights)
    rows = []
    for key in weights:
        for sign in (-delta, delta):
            changed = dict(weights)
            changed[key] = max(0.01, changed[key] + sign)
            scale = sum(changed.values())
            changed = {name: value / scale for name, value in changed.items()}
            scores = combine_scores(components, changed)
            correlation = _safe_spearman(base, scores, min_n=5)
            rows.append({"weight": key, "delta": sign, "score_spearman": correlation})
    return pd.DataFrame(rows)


def spearman_matrix(features: pd.DataFrame, columns: list[str], min_n: int) -> pd.DataFrame:
    usable = [column for column in columns if column in features and features[column].notna().sum() >= min_n]
    matrix = pd.DataFrame(np.eye(len(usable)), index=usable, columns=usable, dtype=float)
    for i, left in enumerate(usable):
        for right in usable[i + 1 :]:
            correlation = _safe_spearman(features[left], features[right], min_n)
            matrix.loc[left, right] = correlation
            matrix.loc[right, left] = correlation
    return matrix


def redundancy_clusters(matrix: pd.DataFrame, threshold: float = 0.5) -> pd.Series:
    if len(matrix) < 2:
        return pd.Series(dtype=int)
    distance = (1 - matrix.abs()).clip(0, 1).to_numpy(float, copy=True)
    np.fill_diagonal(distance, 0)
    distance = (distance + distance.T) / 2
    labels = fcluster(linkage(squareform(distance, checks=False), method="average"), t=threshold, criterion="distance")
    return pd.Series(labels, index=matrix.index, name="cluster")


def principal_components(features: pd.DataFrame, columns: list[str]) -> tuple[pd.DataFrame, pd.Series]:
    data = features[columns].dropna()
    if len(data) < max(10, len(columns) + 2):
        return pd.DataFrame(), pd.Series(dtype=float)
    standard = (data - data.mean()) / data.std(ddof=0).replace(0, np.nan)
    standard = standard.dropna(axis=1)
    if standard.shape[1] < 2:
        return pd.DataFrame(), pd.Series(dtype=float)
    _, singular, vectors = np.linalg.svd(standard.to_numpy(float), full_matrices=False)
    variance = singular ** 2
    variance = variance / variance.sum()
    loadings = pd.DataFrame(vectors.T[:, : min(3, vectors.shape[0])], index=standard.columns)
    loadings.columns = [f"pc{i + 1}" for i in range(loadings.shape[1])]
    return loadings, pd.Series(variance[: loadings.shape[1]], index=loadings.columns)


def _convergence(features: pd.DataFrame, spec: dict, anchors: list[dict], covariates: list[str], config: dict) -> float:
    min_n = config["min_spearman_n"]
    window = config["rolling_window"]
    aligned = []
    deviations = features.copy()
    for column in [spec["name"], *[anchor["name"] for anchor in anchors]]:
        if column in deviations:
            deviations[column] = rolling_deviation(features, column, window)
    for anchor in anchors:
        if anchor["name"] not in features or anchor["name"] == spec["name"]:
            continue
        if spec["name"].startswith("garmin_") and anchor["name"].startswith("garmin_"):
            continue
        sign = 1 if spec["direction"] == anchor["direction"] else -1
        correlation = _safe_spearman(deviations[spec["name"]], deviations[anchor["name"]], min_n)
        if not np.isfinite(correlation):
            usable = [column for column in covariates if column in features and column != spec["name"]]
            correlation = partial_spearman(features, spec["name"], anchor["name"], usable, min_n)
        if np.isfinite(correlation):
            aligned.append(_clip01(sign * correlation))
    return float(np.mean(aligned)) if aligned else np.nan


def _artifact_independence(features: pd.DataFrame, column: str, min_n: int) -> float:
    correlations = []
    for artifact in ("leak_95_l_min", "invalid_pct"):
        if artifact in features and artifact != column:
            correlations.append(abs(_safe_spearman(features[column], features[artifact], min_n)))
    finite = [value for value in correlations if np.isfinite(value)]
    if not finite:
        return np.nan
    return _clip01(1 - max(finite))


def score_indicators(features: pd.DataFrame, halves: pd.DataFrame, config: dict | None = None) -> dict:
    config = config if config is not None else load_indicator_config()
    sample = features.loc[analysis_mask(features, config["usage_min_hours"])].copy()
    joined = sample.merge(halves, on="night", how="left") if halves is not None and not halves.empty else sample
    rows = []
    for spec in config["indicators"]:
        column = spec["name"]
        if column not in sample:
            continue
        icc = adjacent_icc(sample, column, config["min_pairs"], config["switch_gap_days"])
        half = HALF_COLUMNS.get(column)
        split_half = np.nan
        if half and half[0] in joined and half[1] in joined:
            split_half = split_half_reliability(joined[half[0]], joined[half[1]], config["min_spearman_n"])
        repeatability_parts = [_clip01(icc), _clip01(split_half)]
        finite_parts = [value for value in repeatability_parts if np.isfinite(value)]
        response = pressure_response(
            sample, column, spec.get("pressure_response"), config["switch_window"], config["switch_gap_days"], config["min_switches"],
        )
        coverage = float(sample[column].notna().mean()) if len(sample) else np.nan
        rows.append({
            "indicator": column,
            "dimension": spec["dimension"],
            "direction": spec["direction"],
            "pressure_response": spec.get("pressure_response"),
            "evidence": spec["evidence"],
            "source": spec["source"],
            "icc": icc,
            "split_half": split_half,
            "mdc95": minimum_detectable_change(sample[column], icc),
            "effect_per_cm": response["effect_per_cm"],
            "n_switches": response["n_switches"],
            "repeatability": float(np.mean(finite_parts)) if finite_parts else np.nan,
            "responsiveness": response["hit_rate"],
            "convergence": _convergence(sample, spec, config["anchors"], config["partial_covariates"], config),
            "artifact_independence": _artifact_independence(sample, column, config["min_spearman_n"]),
            "coverage": coverage,
            "evidence_score": config["evidence_scores"][spec["evidence"]],
        })
    components = pd.DataFrame(rows)
    if components.empty:
        return {"components": components, "sensitivity": pd.DataFrame(), "spearman": pd.DataFrame(), "clusters": pd.Series(dtype=int), "pca": pd.DataFrame()}
    components["score"] = combine_scores(components, config["weights"])
    components = components.sort_values(["score", "indicator"], ascending=[False, True]).reset_index(drop=True)
    columns = components["indicator"].tolist()
    matrix = spearman_matrix(sample, columns, config["min_spearman_n"])
    loadings, variance = principal_components(sample, columns)
    return {
        "components": components,
        "sensitivity": weight_sensitivity(components, config["weights"]),
        "spearman": matrix,
        "clusters": redundancy_clusters(matrix.fillna(0)),
        "pca": loadings,
        "pca_variance": variance,
    }


def select_core(components: pd.DataFrame, features: pd.DataFrame, config: dict | None = None) -> pd.DataFrame:
    """Um indicador por dimensão, mais um complemento se ele medir outra coisa."""
    config = config if config is not None else load_indicator_config()
    chosen = []
    complements = []
    sample = features.loc[analysis_mask(features, config["usage_min_hours"])] if "usage_hours" in features else features
    for _, group in components.groupby("dimension", sort=False):
        ordered = group.sort_values("score", ascending=False)
        passes = (ordered["icc"] >= config["min_icc"]) | (ordered["split_half"] >= config["min_split_half"])
        eligible = ordered[passes.fillna(False)]
        pool = eligible if not eligible.empty else ordered
        if pool.empty:
            continue
        best = pool.iloc[0]
        chosen.append({**best.to_dict(), "role": "primary", "below_icc": bool(eligible.empty)})
        if len(pool) < 2 or best["score"] - pool.iloc[1]["score"] > config["complement_score_gap"]:
            continue
        second = pool.iloc[1]
        correlation = _safe_spearman(sample[best["indicator"]], sample[second["indicator"]], config["min_spearman_n"])
        if np.isfinite(correlation) and abs(correlation) < config["complement_max_correlation"]:
            complements.append({**second.to_dict(), "role": "complement", "below_icc": bool(eligible.empty)})
    for extra in complements:
        if len(chosen) >= config["max_indicators"]:
            break
        chosen.append(extra)
    return pd.DataFrame(chosen)


def _worse_than_baseline(features: pd.DataFrame, column: str, direction: str, baseline: pd.DataFrame) -> pd.Series:
    if baseline.empty or baseline[column].notna().sum() < 3:
        return pd.Series(np.nan, index=features.index)
    stats_by_pressure = baseline.groupby("pressure")[column].agg(["median", "std", "count"])
    global_median = baseline[column].median()
    global_std = baseline[column].std(ddof=1)
    pressure = features["pressure"]
    median = pressure.map(stats_by_pressure["median"])
    std = pressure.map(stats_by_pressure["std"])
    count = pressure.map(stats_by_pressure["count"])
    median = median.where(count >= 8, global_median)
    std = std.where((count >= 8) & (std > 0), global_std)
    std = std.replace(0, np.nan)
    score = (features[column] - median) / std
    if direction == "higher_better":
        score = -score
    return score


def quality_index(features: pd.DataFrame, core: pd.DataFrame, config: dict | None = None) -> pd.DataFrame:
    """Índice v2 (maior = pior) calibrado antes de maio/2026, e o v1 do notebook 03 na mesma escala."""
    config = config if config is not None else load_indicator_config()
    indexed = features[["night", "pressure", "usage_hours", "period"]].copy()
    if core.empty:
        indexed["quality_v2"] = np.nan
        indexed["quality_v2_cpap"] = np.nan
        indexed["quality_v1"] = np.nan
        return indexed
    cutoff = pd.Timestamp(config["calibration_until"])
    eligible = analysis_mask(features, config["usage_min_hours"])
    calibration = features.loc[eligible & (features["night"] < cutoff)]
    directions = dict(zip(core["indicator"], core["direction"]))
    evidence = core.set_index("indicator")["evidence_score"]
    z_columns = []
    for indicator, direction in directions.items():
        column = f"z_{indicator}"
        indexed[column] = _worse_than_baseline(features, indicator, direction, calibration)
        z_columns.append(column)

    calibration_mask = indexed["night"] < cutoff
    cpap = core.loc[core["dimension"] != "recovery", "indicator"].tolist()
    indexed["quality_v2"] = _apply_weights(indexed, core["indicator"].tolist(), calibration_mask, evidence)
    indexed["quality_v2_cpap"] = _apply_weights(indexed, cpap, calibration_mask, evidence)
    flow = [name for name in core["indicator"] if not str(name).startswith("garmin_")]
    indexed["quality_v2_flow"] = _apply_weights(indexed, flow, calibration_mask, evidence)
    indexed["quality_v1"] = _quality_v1(features, calibration)
    return indexed


def _apply_weights(indexed: pd.DataFrame, indicators: list[str], calibration_mask: pd.Series, evidence: pd.Series) -> pd.Series:
    if not indicators:
        return pd.Series(np.nan, index=indexed.index)
    z_columns = [f"z_{indicator}" for indicator in indicators]
    weights = _index_weights(indexed.loc[calibration_mask], z_columns, evidence, indicators)
    values = indexed[z_columns]
    present = values.notna().sum(axis=1)
    numerator = values.mul(weights, axis=1).sum(axis=1, min_count=1)
    denominator = values.notna().mul(weights, axis=1).sum(axis=1).replace(0, np.nan)
    return (numerator / denominator).where(present >= max(1, int(np.ceil(len(z_columns) / 2))))


def _index_weights(calibration_indexed, z_columns, evidence, indicators) -> pd.Series:
    complete = calibration_indexed[z_columns].dropna()
    evidence_weight = pd.Series({f"z_{name}": evidence.get(name, 0.4) for name in indicators}, dtype=float)
    if len(complete) < max(10, len(z_columns) + 2):
        return evidence_weight / evidence_weight.sum()
    standard = (complete - complete.mean()) / complete.std(ddof=0).replace(0, np.nan)
    standard = standard.dropna(axis=1)
    _, _, vectors = np.linalg.svd(standard.to_numpy(float), full_matrices=False)
    loading = pd.Series(vectors[0], index=standard.columns)
    if loading.sum() < 0:
        loading = -loading
    loading = loading.clip(lower=0)
    if loading.sum() == 0:
        loading = pd.Series(1.0, index=standard.columns)
    loading = loading / loading.sum()
    evidence_weight = evidence_weight.reindex(loading.index).fillna(0.4)
    evidence_weight = evidence_weight / evidence_weight.sum()
    blended = 0.5 * loading + 0.5 * evidence_weight
    blended = blended.reindex(z_columns).fillna(0)
    if blended.sum() == 0:
        blended = pd.Series(1.0, index=z_columns)
    return blended / blended.sum()


def _quality_v1(features: pd.DataFrame, calibration: pd.DataFrame) -> pd.Series:
    needed = ["surge_index", "hypopnea30_index", "rera_like_index", "stable_pct"]
    if any(column not in features for column in needed):
        return pd.Series(np.nan, index=features.index)
    baseline = calibration[np.isclose(calibration["pressure"], 7.0)]
    if len(baseline) < 8:
        baseline = calibration
    event_index = features["hypopnea30_index"] + features["rera_like_index"]
    base_event = baseline["hypopnea30_index"] + baseline["rera_like_index"]

    def z_from(values: pd.Series, center: pd.Series, higher_better: bool = False) -> pd.Series:
        std = center.std(ddof=1)
        if not np.isfinite(std) or std <= 0:
            return pd.Series(np.nan, index=values.index)
        score = (values - center.median()) / std
        return -score if higher_better else score

    parts = pd.concat([
        z_from(features["surge_index"], baseline["surge_index"]),
        z_from(event_index, base_event),
        z_from(features["stable_pct"], baseline["stable_pct"], higher_better=True),
    ], axis=1)
    return parts.mean(axis=1, skipna=False)


def holdout_validation(indexed: pd.DataFrame, features: pd.DataFrame, anchors: list[dict], cutoff: str) -> pd.DataFrame:
    """Spearman do índice com âncoras do Garmin só depois da data de calibração."""
    holdout = indexed["night"] >= pd.Timestamp(cutoff)
    sample = indexed.loc[holdout].merge(features[["night", *[anchor["name"] for anchor in anchors if anchor["name"] in features]]], on="night")
    rows = []
    for index_name in ("quality_v2", "quality_v2_cpap", "quality_v2_flow", "quality_v1"):
        for anchor in anchors:
            if anchor["name"] not in sample:
                continue
            correlation = _safe_spearman(sample[index_name], sample[anchor["name"]], min_n=20)
            sign = -1 if anchor["direction"] == "higher_better" else 1
            rows.append({
                "index": index_name,
                "anchor": anchor["name"],
                "spearman": correlation,
                "aligned": sign * correlation if pd.notna(correlation) else np.nan,
                "n": int(sample[[index_name, anchor["name"]]].dropna().shape[0]),
            })
    return pd.DataFrame(rows)
