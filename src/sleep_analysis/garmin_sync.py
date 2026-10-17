"""Backup incremental do Garmin Connect para data/raw/garmin.

- daily/<YYYY-MM-DD>.json: dailySleepData, um arquivo por calendarDate (dia em que acordei).
- stats/<YYYY-MM-DD>.json: resumo do dia (passos, intensidade, estresse, FC de repouso).
- activities/<activityId>.json: resumo de cada atividade registrada.
- snapshots/<timestamp>/garmin/<pasta>/: versão anterior quando o conteúdo muda.

Nada é apagado. O token fica em ~/.garminconnect; a senha não é salva.
"""

import argparse
import getpass
import json
import shutil
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from sleep_analysis.paths import (
    GARMIN_ACTIVITIES_DIR,
    GARMIN_DAILY_DIR,
    GARMIN_RAW_DIR,
    GARMIN_STATS_DIR,
    SNAPSHOTS_DIR,
)

TOKEN_DIR = Path("~/.garminconnect").expanduser()
META_FILE = GARMIN_RAW_DIR / "sync_meta.json"
DEFAULT_START = date(2024, 12, 13)
REFRESH_DAYS = 3
REQUEST_PAUSE_SECONDS = 1.0
DAY_FILE = "????-??-??.json"
SOURCES = ("sleep", "stats", "activities")
# Muda a cada leitura sem alterar o dia; não conta como recálculo.
VOLATILE_KEYS = {"lastSyncTimestampGMT"}


def same_payload(stored: dict, payload: dict) -> bool:
    def stable(value: dict) -> dict:
        return {key: item for key, item in value.items() if key not in VOLATILE_KEYS}

    return stable(stored) == stable(payload)


def store_json(target: Path, payload: dict, snapshot_dir: Path, snapshot_subdir: str) -> str:
    """Grava o JSON e devolve 'new', 'updated' ou 'unchanged'."""
    if target.exists():
        if same_payload(json.loads(target.read_text(encoding="utf-8")), payload):
            return "unchanged"
        backup_dir = snapshot_dir / "garmin" / snapshot_subdir
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup_dir / target.name)
        status = "updated"
    else:
        status = "new"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return status


def import_dir(source: Path, snapshot_dir: Path) -> None:
    files = sorted(source.glob(DAY_FILE))
    if not files:
        sys.exit(f"{source} não tem arquivos YYYY-MM-DD.json")
    counts = {"new": 0, "updated": 0, "unchanged": 0}
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        target = GARMIN_DAILY_DIR / path.name
        counts[store_json(target, payload, snapshot_dir, "daily")] += 1
    print(f"Importados de {source}: {counts}")


def login():
    from garminconnect import Garmin, GarminConnectAuthenticationError

    TOKEN_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        client = Garmin()
        client.login(str(TOKEN_DIR))
        return client
    except GarminConnectAuthenticationError:
        print("Sem token válido; login no Garmin Connect (só nesta vez).")

    email = input("E-mail: ").strip()
    password = getpass.getpass("Senha: ")
    client = Garmin(email=email, password=password, prompt_mfa=lambda: input("Código MFA: ").strip())
    client.login(str(TOKEN_DIR))
    return client


def last_stored_day(directory: Path) -> date | None:
    days = sorted(directory.glob(DAY_FILE))
    return date.fromisoformat(days[-1].stem) if days else None


def default_start(directory: Path) -> date:
    last = last_stored_day(directory)
    return last - timedelta(days=REFRESH_DAYS - 1) if last else DEFAULT_START


def day_range(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def missing_days(directory: Path, start: date, end: date) -> list[date]:
    stored = {date.fromisoformat(path.stem) for path in directory.glob(DAY_FILE)}
    return [day for day in day_range(start, end) if day not in stored]


def days_to_fetch(directory: Path, explicit_start: date | None, end: date) -> list[date]:
    """Intervalo pedido, ou os buracos desde o início mais os últimos dias salvos."""
    if explicit_start is not None:
        return list(day_range(explicit_start, end))
    refresh = list(day_range(default_start(directory), end))
    return sorted(set(missing_days(directory, DEFAULT_START, end)) | set(refresh))


def sync_sleep(client, days: list[date], snapshot_dir: Path) -> dict:
    counts = {"new": 0, "updated": 0, "unchanged": 0}
    print(f"Sono: {days[0]} a {days[-1]} ({len(days)} dias)")
    for day in days:
        payload = client.get_sleep_data(day.isoformat())
        status = store_json(GARMIN_DAILY_DIR / f"{day.isoformat()}.json", payload, snapshot_dir, "daily")
        counts[status] += 1
        sleep_seconds = (payload.get("dailySleepDTO") or {}).get("sleepTimeSeconds")
        hours = f"{sleep_seconds / 3600:.1f} h" if sleep_seconds else "sem sono"
        print(f"  {day}: {status} ({hours})")
        time.sleep(REQUEST_PAUSE_SECONDS)
    return counts


def sync_stats(client, days: list[date], snapshot_dir: Path) -> dict:
    counts = {"new": 0, "updated": 0, "unchanged": 0}
    print(f"Estatísticas: {days[0]} a {days[-1]} ({len(days)} dias)")
    for day in days:
        payload = client.get_stats(day.isoformat())
        status = store_json(GARMIN_STATS_DIR / f"{day.isoformat()}.json", payload, snapshot_dir, "stats")
        counts[status] += 1
        steps = payload.get("totalSteps") if isinstance(payload, dict) else None
        print(f"  {day}: {status} ({steps} passos)" if steps is not None else f"  {day}: {status}")
        time.sleep(REQUEST_PAUSE_SECONDS)
    return counts


def latest_activity_day() -> date | None:
    latest = None
    for path in GARMIN_ACTIVITIES_DIR.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        started = payload.get("startTimeLocal")
        if not started:
            continue
        day = date.fromisoformat(started[:10])
        if latest is None or day > latest:
            latest = day
    return latest


def month_windows(start: date, end: date):
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        if cursor.month == 12:
            next_month = date(cursor.year + 1, 1, 1)
        else:
            next_month = date(cursor.year, cursor.month + 1, 1)
        window_end = min(end, next_month - timedelta(days=1))
        window_start = max(start, cursor)
        yield window_start, window_end
        cursor = next_month


def sync_activities(client, start: date, end: date, snapshot_dir: Path) -> dict:
    counts = {"new": 0, "updated": 0, "unchanged": 0}
    print(f"Atividades: {start} a {end}")
    for window_start, window_end in month_windows(start, end):
        activities = client.get_activities_by_date(window_start.isoformat(), window_end.isoformat()) or []
        for activity in activities:
            activity_id = activity.get("activityId")
            if activity_id is None:
                continue
            status = store_json(
                GARMIN_ACTIVITIES_DIR / f"{activity_id}.json", activity, snapshot_dir, "activities"
            )
            counts[status] += 1
        print(f"  {window_start} a {window_end}: {len(activities)} atividades")
        time.sleep(REQUEST_PAUSE_SECONDS)
    return counts


def write_meta(ranges: dict, counts: dict) -> None:
    days = sorted(path.stem for path in GARMIN_DAILY_DIR.glob(DAY_FILE))
    stats = sorted(path.stem for path in GARMIN_STATS_DIR.glob(DAY_FILE))
    meta = {
        "syncedAt": datetime.now().isoformat(timespec="seconds"),
        "lastRange": ranges.get("sleep"),
        "lastCounts": counts.get("sleep"),
        "days": len(days),
        "firstDay": days[0] if days else None,
        "lastDay": days[-1] if days else None,
        "statsDays": len(stats),
        "statsFirstDay": stats[0] if stats else None,
        "statsLastDay": stats[-1] if stats else None,
        "activities": len(list(GARMIN_ACTIVITIES_DIR.glob("*.json"))),
        "ranges": ranges,
        "counts": counts,
    }
    META_FILE.parent.mkdir(parents=True, exist_ok=True)
    META_FILE.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def summarize() -> None:
    days = sorted(path.stem for path in GARMIN_DAILY_DIR.glob(DAY_FILE))
    stats = sorted(path.stem for path in GARMIN_STATS_DIR.glob(DAY_FILE))
    activities = list(GARMIN_ACTIVITIES_DIR.glob("*.json"))
    if days:
        print(f"Sono: {len(days)} dias ({days[0]} a {days[-1]})")
    if stats:
        print(f"Estatísticas: {len(stats)} dias ({stats[0]} a {stats[-1]})")
    print(f"Atividades: {len(activities)}")


def resolve_start(kind: str, explicit: date | None) -> date:
    if explicit is not None:
        return explicit
    if kind == "activities":
        latest = latest_activity_day()
        return latest - timedelta(days=REFRESH_DAYS - 1) if latest else DEFAULT_START
    directory = GARMIN_DAILY_DIR if kind == "sleep" else GARMIN_STATS_DIR
    return default_start(directory)


def main() -> None:
    from garminconnect import GarminConnectTooManyRequestsError

    parser = argparse.ArgumentParser(description="Backup incremental do Garmin Connect")
    parser.add_argument("--import-dir", type=Path, help="Pasta com YYYY-MM-DD.json já exportados (ex.: OneDrive)")
    parser.add_argument("--start", type=date.fromisoformat, help="Primeiro dia (padrão: últimos dias salvos)")
    parser.add_argument("--end", type=date.fromisoformat, default=date.today(), help="Último dia (padrão: hoje)")
    parser.add_argument("--only", choices=SOURCES, action="append", help="Limita a sleep, stats ou activities")
    parser.add_argument("--no-fetch", action="store_true", help="Só importa a pasta, sem acessar o Garmin")
    args = parser.parse_args()

    snapshot_dir = SNAPSHOTS_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.import_dir:
        import_dir(args.import_dir, snapshot_dir)
    if args.no_fetch:
        summarize()
        return

    selected = args.only or list(SOURCES)
    client = login()
    ranges, counts = {}, {}
    dated = {"sleep": (GARMIN_DAILY_DIR, sync_sleep), "stats": (GARMIN_STATS_DIR, sync_stats)}
    for kind in selected:
        try:
            if kind == "activities":
                start = resolve_start(kind, args.start)
                if start > args.end:
                    print("activities: nada a buscar.")
                    continue
                counts[kind] = sync_activities(client, start, args.end, snapshot_dir)
                ranges[kind] = [start.isoformat(), args.end.isoformat()]
            else:
                directory, runner = dated[kind]
                days = days_to_fetch(directory, args.start, args.end)
                if not days:
                    print(f"{kind}: nada a buscar.")
                    continue
                counts[kind] = runner(client, days, snapshot_dir)
                ranges[kind] = [days[0].isoformat(), days[-1].isoformat()]
        except GarminConnectTooManyRequestsError:
            print(f"Limite de requisições durante {kind}; parei aqui. Rode de novo mais tarde.")
            break
        print(f"{kind}: {counts[kind]}")
    if ranges:
        write_meta(ranges, counts)
    summarize()


if __name__ == "__main__":
    main()
