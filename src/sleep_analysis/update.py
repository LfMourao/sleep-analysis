"""Atualiza tudo de uma vez: backup do cartão, Garmin, build incremental e resumo das últimas noites."""

import argparse
import subprocess
import sys

from sleep_analysis.garmin_sync import AUTH_REQUIRED_EXIT

FIND_CARD = (
    "Get-PSDrive -PSProvider FileSystem | "
    "Where-Object { (Test-Path ($_.Root + 'STR.edf')) -and (Test-Path ($_.Root + 'DATALOG')) } | "
    "ForEach-Object { $_.Root }"
)


def find_card() -> str | None:
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", FIND_CARD], check=False, capture_output=True, text=True, timeout=60
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    roots = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return roots[0].rstrip("\\") if roots else None


def run_step(title: str, args: list[str], tail: int = 6) -> int:
    print(f"\n## {title}")
    result = subprocess.run([sys.executable, "-m", *args], check=False, capture_output=True, text=True)
    lines = (result.stdout + result.stderr).strip().splitlines()
    for line in lines[-tail:]:
        print(line)
    return result.returncode


def main() -> None:
    parser = argparse.ArgumentParser(description="Backup do cartão e do Garmin, build incremental e resumo")
    parser.add_argument("--card", help="Letra do cartão (ex.: D:) ou caminho local; padrão: procurar")
    parser.add_argument("--skip-card", action="store_true", help="Não copiar o cartão")
    parser.add_argument("--skip-garmin", action="store_true", help="Não acessar o Garmin Connect")
    parser.add_argument("--full", action="store_true", help="Build sem cache")
    parser.add_argument("--nights", type=int, default=7, help="Noites no resumo final")
    args = parser.parse_args()

    problems = []
    if not args.skip_card:
        card = args.card or find_card()
        if card:
            if run_step(f"Cartão ({card})", ["sleep_analysis.ingest", card], tail=4) != 0:
                problems.append("cópia do cartão falhou")
        else:
            print("\n## Cartão\nNenhuma unidade com STR.edf e DATALOG; seguindo com o backup já salvo.")
            problems.append("cartão não encontrado")

    if not args.skip_garmin:
        code = run_step("Garmin", ["sleep_analysis.garmin_sync", "--non-interactive", "--quiet"], tail=8)
        if code == AUTH_REQUIRED_EXIT:
            problems.append("Garmin sem login")
        elif code != 0:
            problems.append(f"Garmin terminou com código {code}")

    build_args = ["sleep_analysis.build"] + (["--full"] if args.full else [])
    if run_step("Build", build_args, tail=12) != 0:
        print("\nBuild falhou; resumo não gerado.")
        sys.exit(1)

    print("\n## Últimas noites\n")
    sys.stdout.flush()
    subprocess.run([sys.executable, "-m", "sleep_analysis.latest", "--nights", str(args.nights)], check=False)
    if problems:
        print("\nPendências: " + "; ".join(problems) + ".")


if __name__ == "__main__":
    main()
