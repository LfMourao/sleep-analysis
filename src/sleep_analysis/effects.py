"""Efeito de um fator sobre os indicadores, com autocorrelação e comparações múltiplas."""

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.stats import norm
from statsmodels.stats.multitest import multipletests


def minimum_detectable_effect(sd: float, icc: float, n: int, alpha: float = 0.05, power: float = 0.8) -> float:
    """Diferença mínima entre dois grupos, inflada pela autocorrelação medida pelo ICC."""
    if n < 4 or not np.isfinite(sd) or sd <= 0:
        return np.nan
    rho = 0.0 if not np.isfinite(icc) else float(np.clip(icc, 0, 0.95))
    design_effect = (1 + rho) / (1 - rho)
    z = norm.ppf(1 - alpha / 2) + norm.ppf(power)
    return float(z * sd * np.sqrt(design_effect * 2 / n))


def minimum_n(sd: float, icc: float, effect: float, alpha: float = 0.05, power: float = 0.8) -> float:
    if not np.isfinite(effect) or effect == 0 or not np.isfinite(sd) or sd <= 0:
        return np.nan
    rho = 0.0 if not np.isfinite(icc) else float(np.clip(icc, 0, 0.95))
    design_effect = (1 + rho) / (1 - rho)
    z = norm.ppf(1 - alpha / 2) + norm.ppf(power)
    return float(2 * design_effect * (z * sd / abs(effect)) ** 2)


def apply_bh(results: pd.DataFrame, p_column: str = "p_value") -> pd.DataFrame:
    out = results.copy()
    valid = out[p_column].notna()
    q_values = np.full(len(out), np.nan)
    if int(valid.sum()) > 0:
        _, adjusted, _, _ = multipletests(out.loc[valid, p_column], method="fdr_bh")
        q_values[np.flatnonzero(valid.to_numpy())] = adjusted
    out["q_value"] = q_values
    return out


def _block_indices(n: int, block: int, rng: np.random.Generator) -> np.ndarray:
    if n <= block:
        return np.arange(n)
    starts = rng.integers(0, n - block + 1, size=int(np.ceil(n / block)))
    return np.concatenate([np.arange(start, start + block) for start in starts])[:n]


def _fit(data: pd.DataFrame, outcome: str, factor: str, covariates: list[str]):
    predictors = [factor, *[column for column in covariates if column != factor and data[column].nunique(dropna=True) >= 2]]
    design = sm.add_constant(data[predictors].astype(float), has_constant="add")
    model = sm.OLS(data[outcome].astype(float), design)
    lags = max(1, int(len(data) ** 0.25))
    fit = model.fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return fit, predictors


def estimate_effect(
    features: pd.DataFrame,
    factor: str,
    outcomes: list[str],
    covariates: list[str] | None = None,
    min_n: int = 20,
    n_boot: int = 1000,
    block: int = 7,
    icc_by_outcome: dict | None = None,
    rng: np.random.Generator | None = None,
) -> pd.DataFrame:
    """Regressão com erro Newey-West e intervalo por bootstrap em blocos."""
    covariates = [column for column in (covariates or []) if column != factor]
    icc_by_outcome = icc_by_outcome or {}
    rng = rng or np.random.default_rng(7)
    rows = []
    ordered = features.sort_values("night")
    levels = ordered[factor].dropna().unique() if factor in ordered else []
    for outcome in outcomes:
        outcome_covariates = [column for column in covariates if column != outcome]
        needed = ["night", outcome, factor, *outcome_covariates]
        data = ordered.dropna(subset=[column for column in needed if column in ordered.columns]).copy()
        if outcome not in ordered or factor not in ordered or len(data) < min_n or data[factor].nunique() < 2:
            rows.append({"factor": factor, "outcome": outcome, "n": int(len(data)), "note": "amostra ou variação insuficiente"})
            continue
        fit, predictors = _fit(data, outcome, factor, outcome_covariates)
        coefficient = float(fit.params[factor])
        interval = fit.conf_int().loc[factor]
        boot = _bootstrap_coefficient(data, outcome, factor, predictors, n_boot, block, rng)
        two_levels = data[factor].nunique() == 2
        median_difference = _median_difference(data, outcome, factor) if two_levels else np.nan
        boot_median = _bootstrap_median(data, outcome, factor, n_boot, block, rng) if two_levels else (np.nan, np.nan)
        sd = float(data[outcome].std(ddof=1))
        icc = icc_by_outcome.get(outcome, np.nan)
        rows.append({
            "factor": factor,
            "outcome": outcome,
            "n": int(len(data)),
            "n_levels": int(data[factor].nunique()),
            "levels": ",".join(str(level) for level in sorted(levels, key=str)[:6]),
            "coefficient": coefficient,
            "std_error": float(fit.bse[factor]),
            "p_value": float(fit.pvalues[factor]),
            "ci_low": float(interval.iloc[0]),
            "ci_high": float(interval.iloc[1]),
            "boot_low": boot[0],
            "boot_high": boot[1],
            "median_difference": median_difference,
            "median_boot_low": boot_median[0],
            "median_boot_high": boot_median[1],
            "mde": minimum_detectable_effect(sd, icc, len(data)),
            "minimum_n": minimum_n(sd, icc, coefficient),
            "note": "",
        })
    return pd.DataFrame(rows)


def _bootstrap_coefficient(data, outcome, factor, predictors, n_boot, block, rng) -> tuple[float, float]:
    design_columns = data[predictors].astype(float).to_numpy()
    y = data[outcome].astype(float).to_numpy()
    coefficients = []
    n = len(data)
    for _ in range(n_boot):
        index = _block_indices(n, block, rng)
        design = np.column_stack([np.ones(len(index)), design_columns[index]])
        if np.linalg.matrix_rank(design, tol=1e-8) < design.shape[1]:
            continue
        try:
            fit = sm.OLS(y[index], design).fit()
        except (ValueError, np.linalg.LinAlgError):
            continue
        position = predictors.index(factor) + 1
        coefficients.append(float(fit.params[position]))
    if len(coefficients) < max(20, n_boot // 5):
        return np.nan, np.nan
    return tuple(float(value) for value in np.percentile(coefficients, [2.5, 97.5]))


def _median_difference(data: pd.DataFrame, outcome: str, factor: str) -> float:
    levels = sorted(data[factor].unique())
    return float(data.loc[data[factor] == levels[1], outcome].median() - data.loc[data[factor] == levels[0], outcome].median())


def _bootstrap_median(data, outcome, factor, n_boot, block, rng) -> tuple[float, float]:
    values = data[outcome].to_numpy(float)
    labels = data[factor].to_numpy()
    levels = sorted(pd.unique(labels))
    differences = []
    n = len(data)
    for _ in range(n_boot):
        index = _block_indices(n, block, rng)
        drawn_labels = labels[index]
        if not np.isin(levels, drawn_labels).all():
            continue
        high = np.median(values[index][drawn_labels == levels[1]])
        low = np.median(values[index][drawn_labels == levels[0]])
        differences.append(high - low)
    if len(differences) < max(20, n_boot // 5):
        return np.nan, np.nan
    return tuple(float(value) for value in np.percentile(differences, [2.5, 97.5]))


def plan_n_of_1(start, periods: int = 4, block_nights: int = 14, labels: tuple[str, str] = ("off", "on")) -> pd.DataFrame:
    """Grade ABAB. Blocos de 7 a 14 noites, para um hábito que ainda vai ser registrado."""
    if periods < 2:
        raise ValueError("Um N-de-1 precisa de pelo menos dois blocos")
    if not 7 <= block_nights <= 14:
        raise ValueError("O bloco deve ter entre 7 e 14 noites")
    day = pd.Timestamp(start).normalize()
    rows = []
    for block in range(periods):
        phase = labels[block % 2]
        for _ in range(block_nights):
            rows.append({"night": day, "block": block + 1, "phase": phase})
            day += pd.Timedelta(days=1)
    return pd.DataFrame(rows)
