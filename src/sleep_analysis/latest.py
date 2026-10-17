"""Resumo compacto das últimas noites, em Markdown, contra a referência da mesma pressão."""

import argparse

import numpy as np
import pandas as pd

from sleep_analysis.db import connect
from sleep_analysis.features import build_night_features
from sleep_analysis.paths import REPORTS_DIR

CORE = {
    "device_flow_lim_min_h": "limitação",
    "rin": "rin",
    "snore_min_h": "ronco",
}
MIN_REFERENCE_NIGHTS = 8
USAGE_MIN_HOURS = 4


def _fmt(value, digits: int = 1) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)) or pd.isna(value):
        return "—"
    if isinstance(value, (bool, np.bool_)):
        return "sim" if value else "não"
    if isinstance(value, (int, np.integer)):
        return str(value)
    return f"{value:.{digits}f}"


def _table(rows: list[list[str]], header: list[str]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def reference_for(features: pd.DataFrame, pressure: float) -> tuple[float | None, pd.DataFrame]:
    """Noites antes da cirurgia, uso ≥ 4 h, na pressão mais próxima com sinal suficiente."""
    before = features[(features["period"] == "before") & (features["usage_hours"] >= USAGE_MIN_HOURS)]
    counts = before.dropna(subset=["device_flow_lim_min_h"]).groupby("pressure").size()
    eligible = counts[counts >= MIN_REFERENCE_NIGHTS]
    if eligible.empty or pd.isna(pressure):
        return None, before.iloc[0:0]
    chosen = float(min(eligible.index, key=lambda level: (abs(level - pressure), -level)))
    return chosen, before[np.isclose(before["pressure"], chosen)]


def _flag(value, column: str, reference: pd.DataFrame) -> str:
    if pd.isna(value) or reference[column].notna().sum() < MIN_REFERENCE_NIGHTS:
        return _fmt(value)
    q3, p90 = reference[column].quantile([0.75, 0.90])
    marker = " ⚠⚠" if value > p90 else " ⚠" if value > q3 else ""
    return f"{_fmt(value)}{marker}"


def freshness(features: pd.DataFrame) -> str:
    def last(mask) -> str:
        nights = features.loc[mask, "night"]
        return nights.max().strftime("%d/%m/%Y") if not nights.empty else "—"

    return (
        f"Última noite no resumo: {last(features['has_summary'].fillna(False))}. "
        f"Com sinais de 2 s: {last(features['has_signals'].fillna(False))}. "
        f"Com fluxo de 25 Hz: {last(features['has_flow'].fillna(False))}. "
        f"Com Garmin: {last(features['has_garmin'].fillna(False))}."
    )


def render(features: pd.DataFrame, nights: int) -> str:
    recent = features.sort_values("night").tail(nights)
    mdc = features.attrs.get("mdc", {})
    blocks = [freshness(features)]

    pressure = recent["pressure"].dropna().iloc[-1] if recent["pressure"].notna().any() else np.nan
    reference_pressure, reference = reference_for(features, pressure)

    references = {level: reference_for(features, level)[1] for level in recent["pressure"].dropna().unique()}
    empty = features.iloc[0:0]
    cpap_rows = []
    for row in recent.itertuples():
        row_reference = references.get(row.pressure, empty)
        note = "; ".join(
            part
            for part in [
                "fita" if row.mouth_tape is True else "",
                "parcial" if row.partial is True else "",
                row.note if isinstance(row.note, str) else "",
            ]
            if part
        )
        cpap_rows.append([
            f"{row.night:%d/%m}",
            _fmt(row.pressure),
            _fmt(row.epr_effective, 0),
            _fmt(row.humidity_level, 0),
            _fmt(row.usage_hours),
            _fmt(row.ahi),
            _flag(row.rin, "rin", row_reference),
            _flag(row.device_flow_lim_min_h, "device_flow_lim_min_h", row_reference),
            _flag(row.snore_min_h, "snore_min_h", row_reference),
            _fmt(row.cai),
            _fmt(row.leak_95_l_min),
            note,
        ])
    blocks.append("CPAP\n\n" + _table(
        cpap_rows,
        ["noite", "cmH2O", "EPR", "umid.", "uso h", "AHI", "rin", "limitação", "ronco", "CAI", "vaz. p95", "nota"],
    ))

    garmin_rows = [
        [
            f"{row.night:%d/%m}",
            _fmt(row.garmin_sleep_hours),
            _fmt(row.garmin_hrv, 0),
            _fmt(row.garmin_resting_heart_rate, 0),
            _fmt(row.garmin_sleep_stress, 0),
            _fmt(row.garmin_spo2_avg, 0),
            _fmt(row.garmin_spo2_lowest, 0),
            _fmt(row.garmin_awake_count, 0),
            _fmt(row.garmin_deep_hours),
        ]
        for row in recent.itertuples()
    ]
    blocks.append("Garmin\n\n" + _table(
        garmin_rows, ["noite", "sono h", "HRV", "FC rep.", "estresse", "SpO2 méd.", "SpO2 mín.", "despertares", "profundo h"],
    ))

    if reference_pressure is None:
        blocks.append("Sem referência anterior à cirurgia com sinal suficiente.")
        return "\n\n".join(blocks)

    comparable = recent[(recent["usage_hours"] >= USAGE_MIN_HOURS) & np.isclose(recent["pressure"], pressure)]
    summary_rows = []
    for column, label in CORE.items():
        values = comparable[column].dropna()
        base = reference[column].dropna()
        if base.empty:
            continue
        summary_rows.append([
            label,
            f"{_fmt(values.median(), 2)} (n={len(values)})" if not values.empty else "—",
            _fmt(base.median(), 2),
            _fmt(base.quantile(0.75), 2),
            _fmt(base.quantile(0.90), 2),
            _fmt(mdc.get(column), 2),
        ])
    blocks.append(
        f"Núcleo: mediana das noites acima a {pressure:.1f} cmH2O com uso ≥ {USAGE_MIN_HOURS} h contra a referência "
        f"de {len(reference)} noites antes da cirurgia a {reference_pressure:.1f} cmH2O. "
        "Cada noite é marcada contra a referência da própria pressão: ⚠ acima do Q3; ⚠⚠ acima do P90. Uma noite só muda a conclusão se passar da mudança mínima detectável.\n\n"
        + _table(summary_rows, ["indicador", "recentes", "mediana ref.", "Q3", "P90", "mudança mínima"])
    )
    return "\n\n".join(blocks)


def _load_mdc(features: pd.DataFrame) -> None:
    path = REPORTS_DIR / "07_scorecard.csv"
    if path.exists():
        scorecard = pd.read_csv(path)
        features.attrs["mdc"] = dict(zip(scorecard["indicator"], scorecard["mdc95"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Resumo das últimas noites (CPAP + Garmin)")
    parser.add_argument("--nights", type=int, default=7, help="Quantas noites mostrar (padrão: 7)")
    args = parser.parse_args()
    features = build_night_features(connect())
    _load_mdc(features)
    print(render(features, args.nights))


if __name__ == "__main__":
    main()
