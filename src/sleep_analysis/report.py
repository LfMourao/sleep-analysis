"""Página HTML comparativa: antes e depois da cirurgia, pressão do CPAP e as últimas 90 noites."""

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from sleep_analysis.db import connect
from sleep_analysis.features import build_night_features
from sleep_analysis.latest import CALCULATED, CORE, USAGE_MIN_HOURS
from sleep_analysis.paths import REPORTS_DIR
from sleep_analysis.reliability import load_indicator_config, pressure_response
from sleep_analysis.serve import ensure_server, report_url
from sleep_analysis.study import load_study

TEMPLATE = Path(__file__).with_name("report_template.html")
OUTPUT = REPORTS_DIR / "comparativo.html"
HISTORY_NIGHTS = 90
ROLLING_NIGHTS = 7
ROLLING_MIN_NIGHTS = 3
# A linha da mediana móvel quebra em lacunas maiores que isso
MAX_LINE_GAP_DAYS = 3
BOOTSTRAP_SAMPLES = 2000
BASELINE_PRESSURE = 7.0
# Faixas de docs/quality-indicators.md, mais a de 5,8–6,1 das noites antigas
PRESSURE_BANDS = [5.75, 6.15, 6.75, 7.15, 7.75, 8.15, 8.75, 9.05]

# (rótulo, unidade, valor maior é pior; None = contexto)
SPECS = {
    "usage_hours": ("Uso", "h", False),
    "device_flow_lim_min_h": ("Limitação de fluxo", "min/h", True),
    "rin": ("Despertares respiratórios (rin)", "/h", True),
    "snore_min_h": ("Ronco", "min/h", True),
    "ahi": ("AHI", "/h", True),
    "flow_limited_pct": ("Respirações achatadas", "%", True),
    "hypopnea50_per_usage_h": ("IAH do fluxo", "/h", True),
    "surge_index": ("Surge", "/h", True),
    "stable_pct": ("Respiração estável", "%", False),
    "flow_resp_rate": ("Frequência respiratória", "rpm", None),
    "garmin_avg_heart_rate": ("FC média do sono", "bpm", True),
    "garmin_hrv": ("VFC da noite", "ms", False),
    "garmin_sleep_hours": ("Sono pelo Garmin", "h", False),
}
GROUPS = {
    "Aparelho (CPAP)": ["usage_hours", *CORE, "ahi"],
    "Calculados no fluxo de 25 Hz": list(CALCULATED),
    "Garmin": ["garmin_avg_heart_rate", "garmin_hrv", "garmin_sleep_hours"],
}
PRESSURE_INDICATORS = [*CORE, *CALCULATED]


def _clean(value):
    if value is None or (isinstance(value, float) and not np.isfinite(value)) or pd.isna(value):
        return None
    if isinstance(value, (np.floating, float)):
        return round(float(value), 3)
    if isinstance(value, (np.integer, int)):
        return int(value)
    return value


def _median_difference_ci(after: np.ndarray, before: np.ndarray, rng: np.random.Generator) -> tuple[float, float]:
    """IC de 90% da diferença de medianas por bootstrap independente dos dois grupos."""
    if len(after) < 2 or len(before) < 2:
        return np.nan, np.nan
    draws = (
        np.median(rng.choice(after, (BOOTSTRAP_SAMPLES, len(after))), axis=1)
        - np.median(rng.choice(before, (BOOTSTRAP_SAMPLES, len(before))), axis=1)
    )
    low, high = np.quantile(draws, [0.05, 0.95])
    return float(low), float(high)


def _verdict(low: float, high: float, higher_is_worse: bool | None) -> str:
    if not np.isfinite(low) or not np.isfinite(high):
        return "poucos dados"
    if low <= 0 <= high:
        return "sem diferença clara"
    if higher_is_worse is None:
        return "maior" if low > 0 else "menor"
    worse = (low > 0) == higher_is_worse
    return "pior" if worse else "melhor"


def full_nights(features: pd.DataFrame) -> pd.DataFrame:
    partial = features["partial"].astype("boolean").fillna(False).astype(bool)
    return features[(features["usage_hours"] >= USAGE_MIN_HOURS) & ~partial]


def surgery_groups(features: pd.DataFrame, baseline_nights: int) -> dict[str, pd.DataFrame]:
    nights = full_nights(features)
    before = nights[(nights["period"] == "before") & np.isclose(nights["pressure"], BASELINE_PRESSURE)]
    return {
        "Antes": before.sort_values("night").tail(baseline_nights),
        "Recuperação": nights[nights["period"] == "recovery"],
        "Depois": nights[nights["period"] == "after"],
    }


def surgery_section(features: pd.DataFrame, baseline_nights: int, mdc: dict) -> dict:
    groups = surgery_groups(features, baseline_nights)
    rng = np.random.default_rng(0)
    before = groups["Antes"]
    rows, points = [], {}
    for column, (label, unit, higher_is_worse) in SPECS.items():
        if column not in features:
            continue
        base = before[column].dropna().to_numpy(float)
        row = {"column": column, "label": label, "unit": unit, "higher_is_worse": higher_is_worse,
               "mdc": _clean(mdc.get(column)), "groups": {}}
        for name, frame in groups.items():
            values = frame[column].dropna().to_numpy(float)
            entry = {"n": int(len(values))}
            if len(values):
                entry.update(median=_clean(np.median(values)), q1=_clean(np.quantile(values, 0.25)),
                             q3=_clean(np.quantile(values, 0.75)))
            if name != "Antes" and len(values):
                low, high = _median_difference_ci(values, base, rng)
                entry.update(delta=_clean(np.median(values) - np.median(base)) if len(base) else None,
                             ci_low=_clean(low), ci_high=_clean(high), verdict=_verdict(low, high, higher_is_worse))
            row["groups"][name] = entry
        rows.append(row)
        points[column] = {
            name: [
                {"night": f"{night:%Y-%m-%d}", "value": _clean(value), "pressure": _clean(pressure)}
                for night, value, pressure in frame[["night", column, "pressure"]].dropna(subset=[column]).itertuples(index=False)
            ]
            for name, frame in groups.items()
        }
    ranges = {
        name: [f"{frame['night'].min():%d/%m/%Y}", f"{frame['night'].max():%d/%m/%Y}"] if not frame.empty else None
        for name, frame in groups.items()
    }
    pressures = {
        name: sorted({_clean(level) for level in frame["pressure"].dropna()}) for name, frame in groups.items()
    }
    return {"rows": rows, "points": points, "ranges": ranges, "pressures": pressures}


def pressure_section(features: pd.DataFrame, config: dict) -> dict:
    nights = full_nights(features)
    before = nights[nights["period"] == "before"].copy()
    before["band"] = pd.cut(before["pressure"], PRESSURE_BANDS)
    after = nights[nights["period"] != "before"]
    charts = []
    for column in PRESSURE_INDICATORS:
        label, unit, higher_is_worse = SPECS[column]
        bands = []
        for band, frame in before.groupby("band", observed=True):
            values = frame[column].dropna()
            if len(values) < 3:
                continue
            bands.append({
                "band": f"{band.left + 0.05:.1f}–{band.right - 0.05:.1f}".replace(".", ","),
                "pressure": _clean(frame.loc[values.index, "pressure"].median()),
                "median": _clean(values.median()), "q1": _clean(values.quantile(0.25)),
                "q3": _clean(values.quantile(0.75)), "n": int(len(values)),
            })
        post = [
            {"night": f"{night:%Y-%m-%d}", "pressure": _clean(pressure), "value": _clean(value)}
            for night, pressure, value in after[["night", "pressure", column]].dropna().itertuples(index=False)
        ]
        response = pressure_response(
            features[features["usage_hours"] >= USAGE_MIN_HOURS], column,
            None if higher_is_worse is None else ("decreases" if higher_is_worse else "increases"),
            config["switch_window"], config["switch_gap_days"], config["min_switches"],
        )
        charts.append({
            "column": column, "label": label, "unit": unit, "higher_is_worse": higher_is_worse,
            "bands": bands, "post": post, "effect_per_cm": _clean(response["effect_per_cm"]),
            "n_switches": response["n_switches"], "hit_rate": _clean(response["hit_rate"]),
        })
    return {"charts": charts}


def history_section(features: pd.DataFrame, surgery_date: pd.Timestamp | None) -> dict:
    ordered = features.sort_values("night")
    last = ordered["night"].max()
    start = last - pd.Timedelta(days=HISTORY_NIGHTS - 1)
    calendar = pd.DataFrame({"night": pd.date_range(start, last, freq="D")})
    window = calendar.merge(ordered, on="night", how="left")
    usable = window["usage_hours"] >= USAGE_MIN_HOURS
    after_surgery = window["night"] >= surgery_date if surgery_date is not None else pd.Series(False, index=window.index)
    series = []
    for column, (label, unit, higher_is_worse) in SPECS.items():
        if column not in window:
            continue
        values = window[column].where(usable | column.startswith("garmin_"))
        if column == "usage_hours":
            values = window[column].where(window[column] > 0)
        # Mediana das últimas 7 noites com dado, não de 7 dias do calendário; recomeça na cirurgia
        present = values.dropna()
        rolling = (
            present.groupby(after_surgery[present.index])
            .transform(lambda part: part.rolling(ROLLING_NIGHTS, min_periods=ROLLING_MIN_NIGHTS).median())
            .reindex(values.index)
        )
        recent = values.tail(ROLLING_NIGHTS).dropna()
        series.append({
            "column": column, "label": label, "unit": unit, "higher_is_worse": higher_is_worse,
            "values": [_clean(value) for value in values], "rolling": [_clean(value) for value in rolling],
            "n": int(values.notna().sum()), "median": _clean(values.median()),
            "recent_median": _clean(recent.median()) if not recent.empty else None,
        })
    pressure = window["pressure"].where(window["usage_hours"] > 0)
    return {
        "nights": [f"{night:%Y-%m-%d}" for night in window["night"]],
        "pressure": [_clean(value) for value in pressure],
        "surgery": f"{surgery_date:%Y-%m-%d}" if surgery_date is not None and start <= surgery_date <= last else None,
        "series": series, "groups": GROUPS, "max_gap_days": MAX_LINE_GAP_DAYS,
        "without_cpap": int((window["usage_hours"].fillna(0) == 0).sum()),
    }


def _load_mdc() -> dict:
    path = REPORTS_DIR / "07_scorecard.csv"
    if not path.exists():
        return {}
    scorecard = pd.read_csv(path)
    return dict(zip(scorecard["indicator"], scorecard["mdc95"]))


def build_report(features: pd.DataFrame) -> dict:
    study = load_study()
    config = load_indicator_config()
    last = features["night"].max()
    return {
        "generated": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "last_night": f"{last:%d/%m/%Y}",
        "surgery": f"{study.surgery_date:%d/%m/%Y}" if study.surgery_date is not None else None,
        "recovery_end": f"{study.surgery_date + pd.Timedelta(days=study.recovery_days_excluded):%d/%m/%Y}"
        if study.surgery_date is not None else None,
        "usage_min_hours": USAGE_MIN_HOURS,
        "baseline_pressure": BASELINE_PRESSURE,
        "groups": GROUPS,
        "surgery_section": surgery_section(features, study.baseline_nights, _load_mdc()),
        "pressure_section": pressure_section(features, config),
        "history": history_section(features, study.surgery_date),
    }


def render_html(report: dict) -> str:
    payload = json.dumps(report, ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.read_text(encoding="utf-8").replace("__REPORT_DATA__", payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera a página comparativa em data/reports/comparativo.html")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--serve", action="store_true", help="Sobe o servidor local e imprime o link para o navegador")
    args = parser.parse_args()
    report = build_report(build_night_features(connect()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_html(report), encoding="utf-8")
    print(f"Relatório comparativo -> {args.output}")
    if args.serve:
        print(f"Abrir no navegador: {report_url(ensure_server())}")


if __name__ == "__main__":
    main()
