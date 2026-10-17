"""Backup incremental do cartão do CPAP para data/raw.

- data/raw/card/: espelho acumulado do cartão. Nada é apagado, então noites que
  sumirem ou corromperem no cartão depois continuam guardadas aqui.
- data/raw/snapshots/<timestamp>/: cópia dos arquivos que o aparelho reescreve
  (STR.edf, SETTINGS, Identification), um por execução.
"""

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from sleep_analysis.paths import CARD_DIR, SNAPSHOTS_DIR

SNAPSHOT_ITEMS = ["STR.edf", "Identification.tgt", "Identification.crc", "SETTINGS"]
SKIPPED_DIRS = ["System Volume Information", "FOUND.000"]
SKIPPED_FILES = ["Journal.dat"]
# robocopy: códigos >= 8 indicam falha de cópia
ROBOCOPY_FAILURE_CODE = 8


def is_windows_drive(source: str) -> bool:
    return re.fullmatch(r"[A-Za-z]:\\?", source) is not None


def to_windows_path(path: Path) -> str:
    return subprocess.run(["wslpath", "-w", str(path)], check=True, capture_output=True, text=True).stdout.strip()


def robocopy(source: str, dest: Path, extra_args: list[str]) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    command = [
        "robocopy.exe",
        source,
        to_windows_path(dest),
        *extra_args,
        "/R:0",
        "/W:0",
        "/NP",
        "/NFL",
        "/NDL",
        "/XD",
        *SKIPPED_DIRS,
        "/XF",
        *SKIPPED_FILES,
    ]
    result = subprocess.run(command, capture_output=True, text=True, encoding="cp850", errors="replace")
    if result.returncode >= ROBOCOPY_FAILURE_CODE:
        failed_lines = [line.strip() for line in result.stdout.splitlines() if "ERRO" in line or "ERROR" in line]
        print(f"  robocopy terminou com código {result.returncode}; {len(failed_lines)} itens com erro")
        for line in failed_lines[:10]:
            print(f"    {line}")
    return result.returncode


def copy_from_windows_drive(drive: str, snapshot_dir: Path) -> None:
    root = drive.rstrip("\\") + "\\"
    print(f"Copiando {root} -> {CARD_DIR}")
    robocopy(root, CARD_DIR, ["/E"])

    print(f"Snapshot -> {snapshot_dir}")
    files = [item for item in SNAPSHOT_ITEMS if item != "SETTINGS"]
    robocopy(root, snapshot_dir, files)
    robocopy(root + "SETTINGS", snapshot_dir / "SETTINGS", ["/E"])


def copy_from_local_path(source: Path, snapshot_dir: Path) -> None:
    print(f"Copiando {source} -> {CARD_DIR}")
    failed: list[str] = []

    def copy_tree(src: Path, dst: Path) -> None:
        dst.mkdir(parents=True, exist_ok=True)
        try:
            entries = list(src.iterdir())
        except OSError as error:
            failed.append(f"{src}: {error}")
            return
        for entry in entries:
            if entry.name in SKIPPED_DIRS or entry.name in SKIPPED_FILES:
                continue
            target = dst / entry.name
            if entry.is_dir():
                copy_tree(entry, target)
                continue
            if target.exists() and target.stat().st_size == entry.stat().st_size:
                continue
            try:
                shutil.copy2(entry, target)
            except OSError as error:
                failed.append(f"{entry}: {error}")

    copy_tree(source, CARD_DIR)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    for item in SNAPSHOT_ITEMS:
        path = source / item
        if path.is_dir():
            copy_tree(path, snapshot_dir / item)
        elif path.exists():
            shutil.copy2(path, snapshot_dir / item)
    if failed:
        print(f"  {len(failed)} itens ilegíveis")
        for line in failed[:10]:
            print(f"    {line}")


def summarize() -> None:
    datalog = CARD_DIR / "DATALOG"
    nights = sorted(path.parent.name for path in datalog.glob("*/*_PLD.edf")) if datalog.exists() else []
    nights = sorted(set(nights))
    if not nights:
        print("Nenhuma noite no backup.")
        return
    print(f"Backup com {len(nights)} noites com sinais detalhados ({nights[0]} a {nights[-1]})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backup incremental do cartão do CPAP")
    parser.add_argument("source", nargs="?", default="D:", help="Letra do cartão no Windows (ex.: D:) ou caminho local")
    args = parser.parse_args()

    snapshot_dir = SNAPSHOTS_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
    if is_windows_drive(args.source):
        copy_from_windows_drive(args.source, snapshot_dir)
    else:
        source = Path(args.source)
        if not (source / "DATALOG").exists():
            sys.exit(f"{source} não parece um cartão do CPAP (sem DATALOG)")
        copy_from_local_path(source, snapshot_dir)
    summarize()


if __name__ == "__main__":
    main()
