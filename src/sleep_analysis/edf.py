"""Leitor EDF/EDF+ mínimo para os arquivos da ResMed.

O pyedflib recusa o STR.edf (unidade "°C" fora do ASCII) e os EDF+D de eventos,
por isso a leitura é feita aqui direto dos bytes.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

SIGNAL_FIELDS = [
    ("label", 16),
    ("transducer", 80),
    ("unit", 8),
    ("phys_min", 8),
    ("phys_max", 8),
    ("dig_min", 8),
    ("dig_max", 8),
    ("prefilter", 80),
    ("samples", 8),
    ("reserved", 32),
]
ANNOTATION_LABEL = "EDF Annotations"


@dataclass
class Signal:
    label: str
    unit: str
    phys_min: float
    phys_max: float
    dig_min: int
    dig_max: int
    samples_per_record: int

    def to_physical(self, digital: np.ndarray) -> np.ndarray:
        gain = (self.phys_max - self.phys_min) / (self.dig_max - self.dig_min)
        values = (digital.astype(np.float64) - self.dig_min) * gain + self.phys_min
        # A ResMed grava valores fora da faixa digital (ex.: -1) como "sem dado"
        values[(digital < self.dig_min) | (digital > self.dig_max)] = np.nan
        return values


@dataclass
class EdfFile:
    path: Path
    start: datetime
    record_duration_s: float
    n_records: int
    signals: list[Signal]
    data: bytes

    @property
    def record_size(self) -> int:
        return sum(signal.samples_per_record for signal in self.signals) * 2

    def read_digital(self) -> dict[str, np.ndarray]:
        """Retorna o sinal digital de cada canal, com shape (n_records, samples_per_record)."""
        n_records = min(self.n_records, len(self.data) // self.record_size)
        samples = np.frombuffer(self.data[: n_records * self.record_size], dtype="<i2").reshape(
            n_records, self.record_size // 2
        )
        result = {}
        offset = 0
        for signal in self.signals:
            result[signal.label] = samples[:, offset : offset + signal.samples_per_record]
            offset += signal.samples_per_record
        return result

    def read_physical(self) -> dict[str, np.ndarray]:
        digital = self.read_digital()
        return {
            signal.label: signal.to_physical(digital[signal.label])
            for signal in self.signals
            if signal.label not in (ANNOTATION_LABEL, "Crc16")
        }

    def read_annotations(self) -> list[tuple[float, float, str]]:
        """Retorna (onset_s, duration_s, text) de cada anotação EDF+."""
        n_records = min(self.n_records, len(self.data) // self.record_size)
        annotation_bytes = 0
        offset = 0
        for signal in self.signals:
            if signal.label == ANNOTATION_LABEL:
                annotation_bytes = signal.samples_per_record * 2
                break
            offset += signal.samples_per_record * 2
        annotations = []
        for index in range(n_records):
            start = index * self.record_size + offset
            chunk = self.data[start : start + annotation_bytes].rstrip(b"\x00")
            for tal in chunk.split(b"\x00"):
                annotations.extend(parse_tal(tal))
        return annotations


def parse_tal(tal: bytes) -> list[tuple[float, float, str]]:
    # TAL: +onset[\x15duration]\x14texto\x14texto\x14
    parts = tal.decode("latin-1").split("\x14")
    if not parts or not parts[0]:
        return []
    timing = parts[0].split("\x15")
    onset = float(timing[0])
    duration = float(timing[1]) if len(timing) > 1 and timing[1] else 0.0
    return [(onset, duration, text) for text in parts[1:] if text]


def read_edf(path: Path) -> EdfFile:
    raw = path.read_bytes()

    def text(start: int, end: int) -> str:
        return raw[start:end].decode("latin-1").strip()

    start_date = text(168, 176)
    start_time = text(176, 184)
    day, month, year = (int(part) for part in start_date.split("."))
    hour, minute, second = (int(part) for part in start_time.split("."))
    start = datetime(2000 + year if year < 85 else 1900 + year, month, day, hour, minute, second)

    header_bytes = int(text(184, 192))
    n_signals = int(text(252, 256))
    fields: dict[str, list[str]] = {}
    offset = 256
    for name, width in SIGNAL_FIELDS:
        fields[name] = [text(offset + i * width, offset + (i + 1) * width) for i in range(n_signals)]
        offset += width * n_signals

    signals = [
        Signal(
            label=fields["label"][i],
            unit=fields["unit"][i],
            phys_min=float(fields["phys_min"][i]),
            phys_max=float(fields["phys_max"][i]),
            dig_min=int(fields["dig_min"][i]),
            dig_max=int(fields["dig_max"][i]),
            samples_per_record=int(fields["samples"][i]),
        )
        for i in range(n_signals)
    ]
    return EdfFile(
        path=path,
        start=start,
        record_duration_s=float(text(244, 252)),
        n_records=int(text(236, 244)),
        signals=signals,
        data=raw[header_bytes:],
    )


def signal_timestamps(edf: EdfFile, samples_per_record: int, n_records: int) -> np.ndarray:
    step_ms = edf.record_duration_s * 1000 / samples_per_record
    offsets = (np.arange(samples_per_record * n_records) * step_ms).astype("timedelta64[ms]")
    return np.datetime64(edf.start, "ms") + offsets
