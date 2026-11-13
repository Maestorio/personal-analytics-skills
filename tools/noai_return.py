#!/usr/bin/env python3
"""
noai_return.py — сверка зеркала Mac с NAS перед возвратом к ИИ (docs/no-ai-mode/return-to-ai.md, шаг 3).

Что делает: читает флаг режима (`_hub/settings.json`: `off_since`), запрашивает у сайта список файлов,
изменённых на NAS с этого момента (`GET /api/hub/changes?since=`, с sha256), и сравнивает с зеркалом
Synology Drive по хэшам. Печатает, что менялось на сайте за период «без ИИ» (по зонам и папкам), и вердикт:
«зеркало догнало NAS — можно включать ИИ» (код 0) или «зеркало отстаёт: N файлов — подождать» (код 1).

  python3 tools/noai_return.py --root ~/Library/CloudStorage/SynologyDrive-home/Claude-Memory
      [--url https://<хост>] [--auth '<значение Authorization>']   # иначе HUB_URL / HUB_AUTH из окружения
      [--since 2026-11-20T10:15:00+03:00]                           # вместо off_since из флага
      [--changes-json файл.json]                                    # ответ маршрута из файла (без сети, тесты)
      [--json]                                                      # машинный вывод

Коды выхода: 0 — зеркало совпадает; 1 — отстаёт; 2 — нет данных (ни сети, ни файла ответа, ни since).
Только stdlib; флаг читается модулем `_shared-references/hub_settings.py`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _cand in (_HERE, _HERE.parent / "_shared-references"):
    if str(_cand) not in sys.path:
        sys.path.insert(0, str(_cand))
import hub_settings  # noqa: E402

# Папки, чьи правки на сайте надо назвать человеку (что именно появилось за период «без ИИ»)
KINDS = (
    ("Portfolio/decisions/", "решения владельца с сайта"),
    ("Portfolio/conditions.yaml", "условия-напоминания (определения)"),
    ("Portfolio/conditions-state.json", "состояние условий (кнопки сделал / отложить / не актуально)"),
    ("Portfolio/plan", "план и журнал плана"),
    ("Portfolio/snapshots/", "снапшоты сайта"),
    ("Portfolio/stress/auto/", "пересчёты стресса"),
    ("Portfolio/known-splits.json", "реестр сплитов"),
    ("Portfolio/security-attrs.json", "атрибуты бумаг"),
    ("scenarios/", "веса сценариев и сроки"),
    ("Gaming/user-state.json", "оверлей игр"),
    ("Gaming/", "игры: прочее"),
    ("Health/labs.json", "точки анализов (ручные — source: manual)"),
    ("Health/studies", "исследования и файлы"),
    ("Health/reports/", "отчёты здоровья"),
    ("Health/", "здоровье: прочее"),
    ("ZenMoney/audit/", "итоги месяцев и поездок из CSV"),
    ("ZenMoney/", "деньги: прочее"),
    ("_hub/", "настройки сайта"),
    ("Portfolio/", "портфель: прочее"),
)


def classify(path: str) -> str:
    for prefix, label in KINDS:
        if path.startswith(prefix):
            return label
    return "прочее"


def fetch_changes(url: str, auth: str, since: str) -> dict:
    q = urllib.parse.urlencode({"since": since})
    req = urllib.request.Request(f"{url.rstrip('/')}/api/hub/changes?{q}",
                                 headers={"Authorization": auth, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def sha256_path(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return None


def compare(root: Path, files: list[dict]) -> dict:
    """→ {"same": [...], "differs": [...], "missing": [...]} по путям."""
    out = {"same": [], "differs": [], "missing": []}
    for f in files:
        rel = f.get("path") or ""
        local = root / rel
        if not local.is_file():
            out["missing"].append(rel)
        elif f.get("sha256") and sha256_path(local) == f["sha256"]:
            out["same"].append(rel)
        else:
            out["differs"].append(rel)
    return out


FLAG_PATH = "_hub/settings.json"   # сам файл режима — не правка владельца, в сводку не входит (в сверке зеркала остаётся)


def summarize(files: list[dict]) -> list[tuple[str, int]]:
    counts = defaultdict(int)
    for f in files:
        if (f.get("path") or "") == FLAG_PATH:
            continue
        counts[classify(f.get("path") or "")] += 1
    return sorted(counts.items(), key=lambda kv: -kv[1])


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(description="сверка зеркала Mac с NAS перед возвратом к ИИ")
    ap.add_argument("--root", required=True, help="корень Claude-Memory на зеркале Mac")
    ap.add_argument("--url", default=os.environ.get("HUB_URL", ""), help="адрес сайта (или HUB_URL)")
    ap.add_argument("--auth", default=os.environ.get("HUB_AUTH", ""), help="заголовок Authorization (или HUB_AUTH)")
    ap.add_argument("--since", default=None, help="момент начала периода «без ИИ» (по умолчанию off_since из флага)")
    ap.add_argument("--changes-json", default=None, help="ответ /api/hub/changes из файла (без сети)")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    a = ap.parse_args(argv)

    root = Path(os.path.expanduser(a.root)).resolve()
    if not root.is_dir():
        print(f"✗ нет папки {root}", file=sys.stderr)
        return 2
    flag = hub_settings._read_file(root) or {}
    since = a.since or flag.get("off_since")
    if not since:
        print("✗ режим «без ИИ» на зеркале не включался (нет off_since) — задай --since явно", file=sys.stderr)
        return 2

    if a.changes_json:
        changes = json.loads(Path(a.changes_json).read_text(encoding="utf-8"))
    elif a.url and a.auth:
        try:
            changes = fetch_changes(a.url, a.auth, since)
        except Exception as exc:   # сеть, пароль, формат — сверять нечем
            print(f"✗ сайт не ответил на /api/hub/changes: {exc}", file=sys.stderr)
            return 2
    else:
        print("✗ нет ни --url/--auth (HUB_URL/HUB_AUTH), ни --changes-json — сверять нечем", file=sys.stderr)
        return 2

    files = changes.get("files") or []
    cmp = compare(root, files)
    site_mode = None
    if a.url and a.auth and not a.changes_json:
        os.environ["HUB_URL"], os.environ["HUB_AUTH"] = a.url, a.auth
        net = hub_settings._read_network()
        site_mode = net["ai_mode"] if net else None
    behind = len(cmp["differs"]) + len(cmp["missing"])
    result = {"since": since, "files_changed_on_nas": len(files), "truncated": bool(changes.get("truncated")),
              "same": len(cmp["same"]), "differs": cmp["differs"], "missing": cmp["missing"],
              "by_kind": summarize(files), "mirror_flag": flag.get("ai_mode"), "site_flag": site_mode,
              "ok": behind == 0 and not changes.get("truncated")}
    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Период «без ИИ» с {since}: на NAS изменено файлов — {len(files)}"
              + (" (список обрезан — повтори позже)" if result["truncated"] else ""))
        for label, n in result["by_kind"]:
            print(f"  · {label}: {n}")
        if site_mode and flag.get("ai_mode") and site_mode != flag.get("ai_mode"):
            print(f"⚠ флаг на сайте «{site_mode}», на зеркале «{flag.get('ai_mode')}» — зеркало ещё не догнало")
        if result["ok"]:
            print(f"✓ зеркало догнало NAS ({len(cmp['same'])} файлов совпадают) — можно включать ИИ")
        else:
            print(f"✗ зеркало отстаёт: {behind} файлов — подождать синхронизацию Synology Drive и повторить")
            for rel in cmp["differs"][:20]:
                print(f"    ≠ {rel}")
            for rel in cmp["missing"][:20]:
                print(f"    — нет на зеркале: {rel}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(run())
