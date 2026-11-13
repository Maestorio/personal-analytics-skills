#!/usr/bin/env python3
"""Архивация старых носителей перед миграцией цикла машиночитаемости (schema.md §4.7).

Источники (относительно корня --memory):
  Portfolio/conditions.yaml, Portfolio/gate-reviews.yaml, Portfolio/gate-reviews-archive-2026.yaml,
  Portfolio/reports/*.md, Portfolio/weekly-reviews/*.yaml, Portfolio/plan-journal.jsonl, stale_flags.yaml, Portfolio/securities/**,
  Portfolio/.backups/**, macro-chain/** (целиком), Portfolio/decision-journal/** (целиком); с флагом --extra ещё Portfolio/_bak-cutover-2026-08-03/** и Portfolio.zip.
Назначение --dest (по умолчанию новая папка на каждый прогон: <memory>/_archive/data-structures/<ГГГГ-ММ-ДД>T<ЧЧММ>-step<N>/,
  архивов может быть много — решение владельца 31.10) с теми же относительными путями.

Команды:
  (по умолчанию) сухой прогон — таблица «источник · размер · md5 · в архиве», ничего не пишет;
  --run           — копирует (shutil.copy2), совпадающие файлы пропускает, отличающиеся не перезаписывает без
                    --force; пишет/дополняет MANIFEST.md и manifest.json (дата, шаг цикла из --step, путь,
                    размер, md5). Повторный --run строки манифеста не дублирует;
  verify          — сверяет md5 и размер файлов архива с manifest.json (код возврата 1 при расхождении).

ВНИМАНИЕ: зеркало Мака отстаёт для Portfolio/plan-journal.jsonl (его пишет hub-api мимо File Station) —
  передавать копию с NAS через --journal <файл> (в манифесте такая запись помечается source: nas);
источник правды для него — NAS. Если файл в списке, а --memory указывает на зеркало (SynologyDrive), скрипт
печатает предупреждение: архивировать этот файл надо с NAS.
Запускать с --run только после «да» владельца на шаг архивации.

Запуск: ~/.pyenv/versions/3.12.9/bin/python3 archive_pre_ds.py [plan|verify] [--memory DIR] [--dest DIR]
        [--extra] [--step N] [--run] [--force]
Зависимости: только stdlib.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

DEFAULT_MEMORY = Path.home() / "Library/CloudStorage/SynologyDrive-home/Claude-Memory"
ARCHIVE_PARENT_REL = "_archive/data-structures"   # внутри — папка на каждый прогон: <дата>T<ЧЧММ>-step<N>

SOURCES = [
    "Portfolio/conditions.yaml",
    "Portfolio/gate-reviews.yaml",
    "Portfolio/gate-reviews-archive-2026.yaml",
    "Portfolio/reports/*.md",
    "Portfolio/weekly-reviews/*.yaml",
    "Portfolio/reports/*.yaml",   # YAML-копия advisory-portfolio-iis3 (формат advisory-report/1)
    "Portfolio/plan-journal.jsonl",
    "stale_flags.yaml",
    "Portfolio/securities/**",
    "Portfolio/.backups/**",
    "macro-chain/**",                 # два макросценария меняет backfill_forecast_links.py (forecast_files)
    "Portfolio/decision-journal/**",  # журнал пересобирается на новых источниках
]
EXTRA_SOURCES = [
    "Portfolio/_bak-cutover-2026-08-03/**",
    "Portfolio.zip",
]
MSK = dt.timezone(dt.timedelta(hours=3))
MANIFEST_JSON = "manifest.json"
MANIFEST_MD = "MANIFEST.md"
PLAN_JOURNAL = "Portfolio/plan-journal.jsonl"


def md5_of(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def now_msk() -> str:
    return dt.datetime.now(MSK).replace(microsecond=0).isoformat()


def expand_sources(memory: Path, patterns: list[str], exclude: Path | None = None) -> tuple[list[str], list[str]]:
    """Возвращает (относительные пути существующих файлов, шаблоны без файлов)."""
    files: list[str] = []
    missing: list[str] = []
    for pat in patterns:
        found: list[Path] = []
        if pat.endswith("/**"):
            base = memory / pat[:-3]
            if base.is_dir():
                for root, _dirs, names in os.walk(base):
                    found.extend(Path(root) / n for n in names)
        elif any(ch in pat for ch in "*?["):
            found = [p for p in memory.glob(pat) if p.is_file()]
        else:
            p = memory / pat
            if p.is_file():
                found = [p]
        if exclude is not None:
            found = [p for p in found if exclude not in p.parents]
        if not found:
            missing.append(pat)
        files.extend(p.relative_to(memory).as_posix() for p in sorted(found))
    seen, uniq = set(), []
    for f in files:
        if f not in seen:
            seen.add(f)
            uniq.append(f)
    return uniq, missing


def archive_status(src: Path, dst: Path, src_md5: str) -> str:
    if not dst.exists():
        return "нет"
    return "совпадает" if md5_of(dst) == src_md5 else "отличается"


def build_plan(memory: Path, dest: Path, patterns: list[str],
               overrides: dict[str, Path] | None = None) -> tuple[list[dict], list[str]]:
    """overrides: относительный путь -> файл, откуда брать байты вместо <memory>/<rel>
    (журнал плана берётся с NAS: зеркало Мака его не догоняет)."""
    overrides = overrides or {}
    rels, missing = expand_sources(memory, patterns, exclude=dest if memory in dest.parents else None)
    for rel in overrides:
        if rel not in rels:
            rels.append(rel)
    plan = []
    for rel in rels:
        src = overrides.get(rel, memory / rel)
        m = md5_of(src)
        plan.append({"rel": rel, "size": src.stat().st_size, "md5": m,
                     "status": archive_status(src, dest / rel, m), "src": src,
                     "source": "override" if rel in overrides else "memory"})
    return plan, missing


def format_plan(plan: list[dict], missing: list[str]) -> str:
    lines = ["| Источник | Размер, байт | md5 | В архиве |", "|---|---:|---|---|"]
    for e in plan:
        lines.append(f"| {e['rel']} | {e['size']} | {e['md5']} | {e['status']} |")
    total = sum(e["size"] for e in plan)
    by = {s: sum(1 for e in plan if e["status"] == s) for s in ("нет", "совпадает", "отличается")}
    lines += ["", f"Файлов: {len(plan)}; общий размер: {total} байт ({total / 1048576:.2f} МиБ); "
                  f"в архиве: нет {by['нет']}, совпадает {by['совпадает']}, отличается {by['отличается']}"]
    if missing:
        lines.append("Шаблоны без файлов: " + ", ".join(missing))
    return "\n".join(lines)


def load_manifest(dest: Path) -> dict:
    p = dest / MANIFEST_JSON
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"schema_version": "archive-manifest@1", "entries": {}}


def write_manifest(dest: Path, manifest: dict) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    (dest / MANIFEST_JSON).write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True),
                                      encoding="utf-8")
    lines = ["# MANIFEST — архив перед миграцией цикла машиночитаемости", "",
             "| Дата | Шаг | Путь | Размер, байт | md5 |", "|---|---|---|---:|---|"]
    for rel, e in sorted(manifest["entries"].items()):
        lines.append(f"| {e['archived_at']} | {e['step']} | {rel} | {e['size']} | {e['md5']} |")
    (dest / MANIFEST_MD).write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_archive(memory: Path, dest: Path, plan: list[dict], step: str, force: bool) -> dict:
    """Копирует файлы по плану. Возвращает счётчики copied/skipped_same/conflicts/replaced."""
    manifest = load_manifest(dest)
    stats = {"copied": 0, "skipped_same": 0, "conflicts": [], "replaced": 0}
    for e in plan:
        rel = e["rel"]
        src, dst = e.get("src", memory / rel), dest / rel
        if e["status"] == "отличается" and not force:
            stats["conflicts"].append(rel)
            continue
        if e["status"] == "совпадает":
            stats["skipped_same"] += 1
            if rel not in manifest["entries"]:
                manifest["entries"][rel] = _entry(e, step)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if e["status"] == "отличается":
            stats["replaced"] += 1
        stats["copied"] += 1
        manifest["entries"][rel] = _entry(e, step)
    write_manifest(dest, manifest)
    return stats


def _entry(e: dict, step: str) -> dict:
    entry = {"size": e["size"], "md5": e["md5"], "step": step, "archived_at": now_msk()}
    if e.get("source") == "override":
        entry["source"] = "nas"   # байты взяты не из зеркала (см. --journal)
    return entry


def verify_archive(dest: Path) -> list[str]:
    """Сверяет архив с manifest.json. Возвращает список проблем (пусто — всё сходится)."""
    mf = dest / MANIFEST_JSON
    if not mf.exists():
        return [f"нет {MANIFEST_JSON} в {dest}"]
    manifest = json.loads(mf.read_text(encoding="utf-8"))
    problems = []
    for rel, e in sorted(manifest["entries"].items()):
        p = dest / rel
        if not p.is_file():
            problems.append(f"{rel}: файла нет в архиве")
        elif p.stat().st_size != e["size"]:
            problems.append(f"{rel}: размер {p.stat().st_size} != {e['size']}")
        elif md5_of(p) != e["md5"]:
            problems.append(f"{rel}: md5 не совпадает")
    known = set(manifest["entries"]) | {MANIFEST_JSON, MANIFEST_MD}
    for root, _d, names in os.walk(dest):
        for n in names:
            rel = (Path(root) / n).relative_to(dest).as_posix()
            if rel not in known:
                problems.append(f"{rel}: файл в архиве не описан в манифесте")
    return problems


def default_dest(memory: Path, step: str, when: str | None = None) -> Path:
    """Новая папка архива на каждый прогон: _archive/data-structures/2026-10-31T1130-step1 (время МСК)."""
    when = when or now_msk()
    stamp = when[:10] + "T" + when[11:13] + when[14:16]
    return memory / ARCHIVE_PARENT_REL / f"{stamp}-step{step}"


def latest_dest(memory: Path) -> Path | None:
    """Последняя по имени папка архива (имена начинаются с времени, поэтому сортировка = хронология)."""
    parent = memory / ARCHIVE_PARENT_REL
    if not parent.is_dir():
        return None
    dirs = sorted(p for p in parent.iterdir() if p.is_dir())
    return dirs[-1] if dirs else None


def is_mirror(memory: Path) -> bool:
    return "SynologyDrive" in str(memory.resolve())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Архивация старых носителей перед миграцией (schema.md §4.7)")
    ap.add_argument("command", nargs="?", choices=["plan", "verify"], default="plan")
    ap.add_argument("--memory", default=str(DEFAULT_MEMORY), help="корень Claude-Memory")
    ap.add_argument("--dest", help=f"папка архива (по умолчанию новая <memory>/{ARCHIVE_PARENT_REL}/<дата>T<ЧЧММ>-step<N>; "
                                   "verify без --dest берёт последнюю)")
    ap.add_argument("--extra", action="store_true", help="добавить _bak-cutover-2026-08-03 и Portfolio.zip")
    ap.add_argument("--step", default="0", help="шаг цикла для манифеста")
    ap.add_argument("--run", action="store_true", help="копировать (без флага — сухой прогон)")
    ap.add_argument("--force", action="store_true", help="перезаписывать отличающиеся файлы архива")
    ap.add_argument("--journal", help=f"файл с NAS для {PLAN_JOURNAL} (зеркало Мака его не догоняет)")
    args = ap.parse_args(argv)

    memory = Path(args.memory)
    if args.command == "verify":
        dest = Path(args.dest) if args.dest else latest_dest(memory)
        if dest is None:
            print(f"Архивов нет: {memory / ARCHIVE_PARENT_REL}", file=sys.stderr)
            return 2
        print(f"Архив: {dest}")
        problems = verify_archive(dest)
        for p in problems:
            print("РАСХОЖДЕНИЕ:", p)
        print("Архив сходится с манифестом." if not problems else f"Проблем: {len(problems)}")
        return 1 if problems else 0
    if not memory.is_dir():
        print(f"Корень памяти не найден: {memory}", file=sys.stderr)
        return 2
    dest = Path(args.dest) if args.dest else default_dest(memory, args.step)
    print(f"Папка архива: {dest}")
    patterns = SOURCES + (EXTRA_SOURCES if args.extra else [])
    overrides = {}
    if args.journal:
        jp = Path(args.journal)
        if not jp.is_file():
            print(f"Файл --journal не найден: {jp}", file=sys.stderr)
            return 2
        overrides[PLAN_JOURNAL] = jp
    plan, missing = build_plan(memory, dest, patterns, overrides)
    if any(e["rel"] == PLAN_JOURNAL for e in plan) and is_mirror(memory) and not overrides:
        print("ПРЕДУПРЕЖДЕНИЕ: Portfolio/plan-journal.jsonl взят из зеркала Мака — оно отстаёт от NAS "
              "(пишет hub-api мимо File Station). Источник правды — NAS; архивировать этот файл с NAS.",
              file=sys.stderr)
    print(format_plan(plan, missing))
    if not args.run:
        print("\nСухой прогон: ничего не записано (для копирования — --run).")
        return 0
    stats = run_archive(memory, dest, plan, args.step, args.force)
    print(f"\nСкопировано: {stats['copied']} (из них заменено: {stats['replaced']}); "
          f"уже совпадало: {stats['skipped_same']}; конфликтов: {len(stats['conflicts'])}")
    for rel in stats["conflicts"]:
        print("КОНФЛИКТ (отличается, нужен --force):", rel, file=sys.stderr)
    return 1 if stats["conflicts"] else 0


if __name__ == "__main__":
    sys.exit(main())
