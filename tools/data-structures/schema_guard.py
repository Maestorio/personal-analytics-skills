#!/usr/bin/env python3
"""Сторож «нет файлов вне схемы» (schema.md §2 и §4.7; шаг 17 цикла машиночитаемости).

Обходит Portfolio/, forecasts/, scenarios/, macro-chain/, monitor-reports/, macro-snapshots/ корня Claude-Memory
и сверяет путь каждого файла с РАЗРЕШЁННЫМ СПИСКОМ масок (ALLOWED ниже — единственное место, где он живёт;
выведен из schema.md §2 «Карта сущностей» и _shared-references/claude-memory-layout.md; при расхождении двух
документов верим schema.md). Новый носитель в схеме = новая маска здесь и строка в тесте.

Выход:
  «вне схемы» — путь, размер, причина: упразднённый носитель / копия-бэкап / служебный или пробный файл /
                маска не подошла (папки без разрешённых масок тоже сюда);
  «разрешено, но пусто» — папки схемы без файлов (справочно, на код возврата не влияют).
Код возврата: 0 — чисто, 1 — есть лишнее, 2 — корень не найден. Ничего не удаляет и не пишет.

Запуск: ~/.pyenv/versions/3.12.9/bin/python3 tools/data-structures/schema_guard.py --root <Claude-Memory> [--json]
Зависимости: только stdlib.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

DEFAULT_ROOT = Path.home() / "Library/CloudStorage/SynologyDrive-home/Claude-Memory"

D = r"\d{4}-\d{2}-\d{2}"
SLUG = r"[a-z0-9][a-z0-9.-]*"

# Разрешённый список: путь файла относительно корня Claude-Memory -> полное совпадение регулярного выражения.
# Ключ — обходимая папка верхнего уровня. Подпапки задаются самой маской (путь содержит «/»).
ALLOWED: dict[str, list[str]] = {
    "Portfolio": [
        r"INDEX\.md", r"README\.md",
        r"plan\.json", r"plan-journal\.jsonl",                                   # №2, №3
        r"conditions\.yaml", rf"conditions-archive-\d{{4}}\.yaml",                 # №8
        r"conditions-state\.json", rf"conditions-state-\d{{4}}\.json",             # №9 (+ годовой срез)
        r"security-attrs\.json", r"security-types\.json",                          # №19, №1
        rf"decisions/{D}T\d{{4}}-[^/]+\.json",                                     # №4
        rf"weekly-reviews/weekly-review(-stock|-bond)?-{D}\.(yaml|md)",           # №5
        rf"reports/[^/]+\.(md|yaml)",                                             # №6
        rf"snapshots/portfolio-{D}\.json",                                        # №10
        rf"snapshots/\.versions/portfolio-{D}\.[^/]+\.json",
        rf"snapshots/auto/(portfolio|build-summary)-{D}[^/]*\.json",
        rf"snapshots/auto/\.versions/[^/]+\.json",
        r"decision-journal/(inputs|baselines|journal)\.json",                     # №11
        rf"decision-journal/report-{D}\.md",
        r"decision-journal/(refusals|theses|incidents)\.yaml",
        rf"stress/stress-{D}-[^/]+\.(md|yaml)", r"stress/INDEX\.md",              # №13
        r"stress/_archive-pre-v2/[^/]+",                                           # история V2-CUTOVER
        rf"integrated-views/integrated-view-{D}[^/]*\.md", r"integrated-views/INDEX\.md",
        rf"coherence-audits/coherence-audit-{D}\.md",
        rf"coherence-audits/coherence-input-bundle-{D}\.json",                    # в раскладке не описан
        r"sensitivity/macro-scenarios-[^/]+\.yaml",
        r"forecasts/[^/]+/[^/]+\.(md|yaml)",                                      # per-stock / portfolio-level
        rf"inputs/{D}/[^/]+",
        rf"\.backups/INDEX-{D}-\d{{4}}\.md",                                      # копии INDEX.md от update_index.py
        r"_bak-cutover-2026-08-03/.+",                                            # история, не трогать
    ],
    "forecasts": [rf"{SLUG}\.(yaml|md)", r"INDEX\.md"],                           # №12
    "scenarios": [rf"scenario-{SLUG}\.(yaml|md)", r"INDEX\.md"],
    "macro-chain": [rf"macro-(scenarios|marginal|input)-{D}\.yaml"],              # №18
    "monitor-reports": [rf"monitor-report-{D}(-v\d+)?\.yaml"],                    # №14
    "macro-snapshots": [rf"ru-{D}\.md", rf"auto/ru-{D}\.(md|json)", r"auto/\.versions/[^/]+"],
}
# Папки схемы, которые должны быть непустыми (иначе «разрешено, но пусто»).
EXPECTED_DIRS = [
    "Portfolio/decisions", "Portfolio/weekly-reviews", "Portfolio/reports", "Portfolio/snapshots",
    "Portfolio/decision-journal", "Portfolio/stress", "forecasts", "scenarios", "macro-chain", "monitor-reports",
    "macro-snapshots",
]
# Файлы корня, упразднённые схемой (проверяются отдельно, обход корня не делается).
ROOT_ABOLISHED = ["stale_flags.yaml", "checkpoints.yaml"]

R_ABOLISHED = "упразднённый носитель"
# В .backups/ разрешены только копии INDEX.md, которые update_index.py делает перед правкой индекса.
_INDEX_BACKUP = re.compile(rf"Portfolio/\.backups/INDEX-{D}-\d{{4}}\.md")
R_BACKUP = "копия-бэкап"
R_SERVICE = "служебный/пробный файл"
R_MASK = "маска не подошла"


def classify_special(rel: str) -> str | None:
    """Причина для заведомо лишних файлов (раньше проверки масок) или None."""
    parts = rel.split("/")
    name = parts[-1]
    if re.fullmatch(r"gate-reviews.*\.yaml", name):
        return f"{R_ABOLISHED}: gate-reviews*.yaml (schema.md §4.4)"
    if "securities" in parts[:-1]:
        return f"{R_ABOLISHED}: securities/ (шаг 15)"
    if ".backups" in parts[:-1] and not _INDEX_BACKUP.fullmatch(rel):
        return f"{R_ABOLISHED}: .backups/ кроме копий INDEX.md (шаг 8)"
    if name in ROOT_ABOLISHED:
        return f"{R_ABOLISHED}: {name}"
    if name.endswith(".pre-ds.bak"):
        return f"{R_BACKUP}: *.pre-ds.bak"
    if ".bak" in name:
        return f"{R_BACKUP}: *.bak*"
    if "_to_delete" in parts[:-1]:
        return f"{R_BACKUP}: _to_delete/"
    if name == ".DS_Store" or name.endswith(".wtest") or name.startswith("write_test"):
        return f"{R_SERVICE}: {name if name == '.DS_Store' else 'проба записи'}"
    return None


_COMPILED = {top: [re.compile(m) for m in masks] for top, masks in ALLOWED.items()}


def scan(root: Path) -> dict:
    outside: list[dict] = []
    seen_dirs: dict[str, int] = {}
    for top in ALLOWED:
        base = root / top
        if not base.is_dir():
            continue
        for cur, dirs, names in os.walk(base):
            dirs.sort()
            for n in sorted(names):
                p = Path(cur) / n
                rel = p.relative_to(root).as_posix()
                sub = p.relative_to(base).as_posix()
                reason = classify_special(rel)
                if reason is None and not any(rx.fullmatch(sub) for rx in _COMPILED[top]):
                    reason = R_MASK
                if reason is not None:
                    outside.append({"path": rel, "size": p.stat().st_size if p.exists() else 0, "reason": reason})
                else:
                    d = str(Path(rel).parent.as_posix())
                    seen_dirs[d] = seen_dirs.get(d, 0) + 1
    for name in ROOT_ABOLISHED:
        p = root / name
        if p.is_file():
            outside.append({"path": name, "size": p.stat().st_size, "reason": classify_special(name)})
    empty = [d for d in EXPECTED_DIRS if not any(k == d or k.startswith(d + "/") for k in seen_dirs)]
    return {"root": str(root), "outside": outside, "empty": empty}


def format_report(res: dict) -> str:
    out = res["outside"]
    lines = [f"Корень: {res['root']}", ""]
    if out:
        groups: dict[str, list[dict]] = {}
        for e in out:
            groups.setdefault(e["reason"].split(":")[0], []).append(e)
        lines.append(f"ВНЕ СХЕМЫ: {len(out)} файл(ов)")
        for g in (R_ABOLISHED, R_BACKUP, R_SERVICE, R_MASK):
            items = groups.get(g, [])
            if not items:
                continue
            lines.append(f"\n[{g}] {len(items)}")
            for e in items:
                lines.append(f"  {e['path']}  ({e['size']} байт)  — {e['reason']}")
    else:
        lines.append("Вне схемы: ничего.")
    lines.append("")
    lines.append("Разрешено, но пусто: " + (", ".join(res["empty"]) if res["empty"] else "нет"))
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Сторож «нет файлов вне схемы» (только чтение)")
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="корень Claude-Memory")
    ap.add_argument("--json", action="store_true", help="вывод JSON")
    args = ap.parse_args(argv)
    root = Path(args.root)
    if not root.is_dir():
        print(f"Корень не найден: {root}", file=sys.stderr)
        return 2
    res = scan(root)
    print(json.dumps(res, ensure_ascii=False, indent=1) if args.json else format_report(res))
    return 1 if res["outside"] else 0


if __name__ == "__main__":
    sys.exit(main())
