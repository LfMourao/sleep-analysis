import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from sleep_analysis.paths import PROJECT_DIR


def load_night_notes(path: Path | None = None) -> pd.DataFrame:
    """Notas locais por dia ResMed; ausências são desconhecidas, não False.

    O arquivo é opcional, pois data/ não é versionado. Datas inválidas e
    campos incompatíveis falham explicitamente para evitar anotações erradas.
    """
    path = path if path is not None else PROJECT_DIR / "data/reference/night_notes.json"
    notes = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    rows = []
    for night, context in notes.items():
        parsed = pd.Timestamp(night)
        if pd.isna(parsed) or parsed.tz is not None or parsed != parsed.normalize():
            raise ValueError(f"Data de noite inválida: {night}")
        for key in ("mouthTape", "partial"):
            if context.get(key) is not None and not isinstance(context[key], bool):
                raise ValueError(f"{night}: {key} precisa ser booleano")
        if context.get("note") is not None and not isinstance(context["note"], str):
            raise ValueError(f"{night}: note precisa ser texto")
        rows.append({"night": parsed, "mouth_tape": context.get("mouthTape"),
                     "partial": context.get("partial"), "note": context.get("note")})
    frame = pd.DataFrame(rows, columns=["night", "mouth_tape", "partial", "note"])
    frame = frame.astype({"night": "datetime64[ns]", "mouth_tape": "boolean",
                          "partial": "boolean", "note": "string"})
    if frame["night"].duplicated().any():
        raise ValueError("Notas contêm datas de noite duplicadas")
    return frame.sort_values("night").reset_index(drop=True)


@dataclass
class Study:
    surgery_date: pd.Timestamp | None
    recovery_days_excluded: int
    baseline_nights: int


HABIT_TYPES = {"boolean", "number", "text"}
HABIT_LAGS = {"same_night", "previous_day"}
HABIT_EFFECTS = {None, "worse", "better"}
TRUE_VALUES = {"true"}
FALSE_VALUES = {"false"}


def load_habits_catalog(path: Path | None = None) -> dict:
    path = path if path is not None else PROJECT_DIR / "config" / "habits_catalog.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(catalog, dict) or not catalog:
        raise ValueError("Catálogo de hábitos vazio ou inválido")
    for name, spec in catalog.items():
        if spec.get("type") not in HABIT_TYPES:
            raise ValueError(f"{name}: type inválido")
        if spec.get("lag") not in HABIT_LAGS:
            raise ValueError(f"{name}: lag inválida")
        if spec.get("expected") not in HABIT_EFFECTS:
            raise ValueError(f"{name}: expected inválido")
    return catalog


def load_daily_log(path: Path | None = None, catalog: dict | None = None) -> pd.DataFrame:
    """Lê o diário longo. Arquivo ausente vira tabela vazia; valor fora do catálogo falha."""
    path = path if path is not None else PROJECT_DIR / "data" / "reference" / "daily_log.csv"
    columns = ["date", "variable", "value_number", "value_text", "unit", "note", "lag", "expected"]
    empty = pd.DataFrame(columns=columns).astype({
        "date": "datetime64[ns]", "variable": "string", "value_number": "float64",
        "value_text": "string", "unit": "string", "note": "string", "lag": "string", "expected": "string",
    })
    if not path.exists() or path.stat().st_size == 0:
        return empty
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    if raw.empty:
        return empty
    required = {"date", "variable", "value", "unit", "note"}
    if set(raw.columns) != required and not required.issubset(raw.columns):
        raise ValueError("daily_log precisa das colunas date, variable, value, unit, note")
    catalog = catalog if catalog is not None else load_habits_catalog()
    if raw.duplicated(["date", "variable"]).any():
        raise ValueError("daily_log tem date e variable repetidos")
    rows = []
    for record in raw.to_dict("records"):
        parsed = pd.Timestamp(record["date"])
        if pd.isna(parsed) or parsed.tz is not None or parsed != parsed.normalize() or str(record["date"]) != parsed.strftime("%Y-%m-%d"):
            raise ValueError(f"Data inválida: {record['date']}")
        spec = catalog.get(record["variable"])
        if spec is None:
            raise ValueError(f"Variável fora do catálogo: {record['variable']}")
        unit = record.get("unit") or ""
        expected_unit = spec.get("unit") or ""
        if unit != expected_unit:
            raise ValueError(f"{record['date']} {record['variable']}: unit deve ser '{expected_unit}'")
        value_number, value_text = _parse_habit_value(record["variable"], spec["type"], record.get("value", ""))
        rows.append({
            "date": parsed, "variable": record["variable"], "value_number": value_number,
            "value_text": value_text, "unit": unit or pd.NA, "note": record.get("note") or pd.NA,
            "lag": spec["lag"], "expected": spec.get("expected"),
        })
    frame = pd.DataFrame(rows)
    return frame.astype({
        "date": "datetime64[ns]", "variable": "string", "value_number": "float64",
        "value_text": "string", "unit": "string", "note": "string", "lag": "string", "expected": "string",
    }).sort_values(["date", "variable"]).reset_index(drop=True)


def _parse_habit_value(variable: str, kind: str, value: str) -> tuple[float, str | None]:
    text = str(value).strip()
    if text == "":
        raise ValueError(f"{variable}: value vazio")
    if kind == "boolean":
        lowered = text.lower()
        if lowered in TRUE_VALUES:
            return 1.0, None
        if lowered in FALSE_VALUES:
            return 0.0, None
        raise ValueError(f"{variable}: booleano deve ser true ou false")
    if kind == "number":
        try:
            return float(text), None
        except ValueError as error:
            raise ValueError(f"{variable}: número inválido") from error
    return np.nan, text


def habits_for_nights(log: pd.DataFrame) -> pd.DataFrame:
    """Associa cada registro à noite ResMed. previous_day cai na noite do dia seguinte."""
    if log.empty:
        out = log.copy()
        out["night"] = pd.Series(dtype="datetime64[ns]")
        return out
    frame = log.copy()
    shift = np.where(frame["lag"].eq("previous_day"), 1, 0)
    frame["night"] = frame["date"] + pd.to_timedelta(shift, unit="D")
    return frame


def load_study() -> Study:
    config = json.loads((PROJECT_DIR / "config" / "study.json").read_text())
    surgery_date = pd.Timestamp(config["surgeryDate"]) if config.get("surgeryDate") else None
    return Study(
        surgery_date=surgery_date,
        recovery_days_excluded=config["recoveryDaysExcluded"],
        baseline_nights=config["baselineNights"],
    )


def label_period(nights: pd.DataFrame, study: Study) -> pd.Series:
    """Classifica cada noite como before, recovery ou after em relação à cirurgia."""
    if study.surgery_date is None:
        return pd.Series("before", index=nights.index)
    recovery_end = study.surgery_date + pd.Timedelta(days=study.recovery_days_excluded)
    period = pd.Series("recovery", index=nights.index)
    period[nights["night"] < study.surgery_date] = "before"
    period[nights["night"] >= recovery_end] = "after"
    return period
