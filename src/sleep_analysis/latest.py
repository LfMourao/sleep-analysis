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
# Calculados neste repositório sobre o fluxo de 25 Hz, um por dimensão. Escolha e fontes em
# docs/quality-indicators.md, seção "Grupo calculado". (rótulo, valor maior é pior)
CALCULATED = {
    "flow_limited_pct": ("achatadas %", True),
    "hypopnea50_per_usage_h": ("IAH fluxo", True),
    "surge_index": ("surge", True),
    "stable_pct": ("estável %", False),
    "flow_resp_rate": ("FR", None),
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


def _flag(value, column: str, reference: pd.DataFrame, higher_is_worse: bool = True) -> str:
    if pd.isna(value) or column not in reference or reference[column].notna().sum() < MIN_REFERENCE_NIGHTS:
        return _fmt(value)
    if higher_is_worse:
        q3, p90 = reference[column].quantile([0.75, 0.90])
        marker = " ⚠⚠" if value > p90 else " ⚠" if value > q3 else ""
    else:
        q1, p10 = reference[column].quantile([0.25, 0.10])
        marker = " ⚠⚠" if value < p10 else " ⚠" if value < q1 else ""
    return f"{_fmt(value)}{marker}"


def _summary_rows(indicators: dict, comparable: pd.DataFrame, reference: pd.DataFrame, mdc: dict) -> list[list[str]]:
    rows = []
    for column, spec in indicators.items():
        label, higher_is_worse = spec if isinstance(spec, tuple) else (spec, True)
        if column not in reference:
            continue
        values = comparable[column].dropna()
        base = reference[column].dropna()
        if base.empty:
            continue
        if higher_is_worse is None:
            attention = regression = "—"
        else:
            levels = (0.75, 0.90) if higher_is_worse else (0.25, 0.10)
            attention, regression = (_fmt(base.quantile(level), 2) for level in levels)
        rows.append([
            label,
            f"{_fmt(values.median(), 2)} (n={len(values)})" if not values.empty else "—",
            _fmt(base.median(), 2),
            attention,
            regression,
            _fmt(mdc.get(column), 2),
        ])
    return rows


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
    cpap_table = "CPAP: indicadores do aparelho\n\n" + _table(
        cpap_rows,
        ["noite", "cmH2O", "EPR", "umid.", "uso h", "AHI", "rin", "limitação", "ronco", "CAI", "vaz. p95", "nota"],
    )

    calculated_rows = []
    for row in recent.itertuples():
        row_reference = references.get(row.pressure, empty)
        cells = [f"{row.night:%d/%m}", _fmt(row.pressure)]
        for column, (_, higher_is_worse) in CALCULATED.items():
            value = getattr(row, column, np.nan)
            cells.append(_fmt(value) if higher_is_worse is None else _flag(value, column, row_reference, higher_is_worse))
        calculated_rows.append(cells)
    calculated_table = "Calculados no fluxo de 25 Hz\n\n" + _table(
        calculated_rows, ["noite", "cmH2O", *[label for label, _ in CALCULATED.values()]],
    )

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
    garmin_table = "Garmin\n\n" + _table(
        garmin_rows, ["noite", "sono h", "HRV", "FC rep.", "estresse", "SpO2 méd.", "SpO2 mín.", "despertares", "profundo h"],
    )

    if reference_pressure is None:
        blocks += [cpap_table, calculated_table, garmin_table, "Sem referência anterior à cirurgia com sinal suficiente."]
        return "\n\n".join(blocks)

    comparable = recent[(recent["usage_hours"] >= USAGE_MIN_HOURS) & np.isclose(recent["pressure"], pressure)]
    header = ["indicador", "recentes", "mediana ref.", "atenção", "regressão", "mudança mínima"]
    blocks.append(cpap_table)
    blocks.append(
        f"Mediana das noites acima a {pressure:.1f} cmH2O com uso ≥ {USAGE_MIN_HOURS} h contra a referência "
        f"de {len(reference)} noites antes da cirurgia a {reference_pressure:.1f} cmH2O. "
        "Cada noite é marcada contra a referência da própria pressão: ⚠ além do Q3 (Q1 quando menor é pior); "
        "⚠⚠ além do P90 (P10). Uma noite só muda a conclusão se passar da mudança mínima detectável.\n\n"
        + _table(_summary_rows(CORE, comparable, reference, mdc), header)
    )
    blocks.append(calculated_table)
    blocks.append(
        "Mesma referência. Achatadas, IAH e surge: maior é pior; estável: menor é pior; FR é contexto, sem marca. "
        "São mais ruidosos que os do aparelho: leia a mediana da semana, não a noite.\n\n"
        + _table(_summary_rows(CALCULATED, comparable, reference, mdc), header)
    )
    blocks.append(garmin_table)
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
