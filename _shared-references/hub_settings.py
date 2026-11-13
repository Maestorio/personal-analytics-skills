#!/usr/bin/env python3
"""
hub_settings.py — режим сайта «с ИИ / без ИИ» для скриптов-писателей Claude-Memory (hub-settings@1).

Флаг пишет только hub-api (`GET/POST /api/hub/settings`) в `Claude-Memory/_hub/settings.json`. Скрипт на Mac
читает его **сначала по сети** (переменные окружения `HUB_URL` — адрес сайта, `HUB_AUTH` — значение заголовка
Authorization), **иначе из файла зеркала** Synology. Нет ни файла, ни сети — режим `on` (обратная совместимость).
Файл на зеркале может отставать от NAS: если `updated_at` старше `max_age_days`, модуль предупреждает в stderr.

  ai_mode(path, max_age_days=7)        → "on" | "off"; path — корень Claude-Memory или любой путь внутри него
  require_ai(path, script, action="запись")
                                       → при "off" печатает причину в stderr и завершает процесс кодом 3;
                                         для писателей, чей вход — вывод модели (гейт по происхождению входа);
                                         при доступной сети дополнительно сверяет зеркало с NAS (mirror_lag) —
                                         отстаёт → код 4, запись не делается (инцидент с отставшим зеркалом)
  mirror_lag(path, hours=6, zones=None) → None, если проверить нельзя (нет HUB_URL/HUB_AUTH или сайт не ответил);
                                         иначе {"checked", "behind": [пути, где зеркало не совпало с NAS], "truncated"}
  find_root(path)                      → корень Claude-Memory по маркерам (`_hub/`, `Portfolio/` + `INDEX.md`, имя
                                         `Claude-Memory`) или None
  read(path)                           → {"ai_mode", "source": network|file|default, "settings", "stale": bool}

В репозитории модуль лежит в `_shared-references/`, в упакованном скилле — в `scripts/` (pack.sh кладёт по импорту).
Зависимости: stdlib.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = "hub-settings@1"
FILE_REL = Path("_hub") / "settings.json"
MODES = ("on", "off")
EXIT_OFF = 3
EXIT_LAG = 4
LAG_HOURS = 6
_MSK = timezone(timedelta(hours=3))
_NET_TIMEOUT = 3.0


def find_root(path) -> Path | None:
    """Корень Claude-Memory: сам путь или ближайший предок с `_hub/`, с `Portfolio/` и `INDEX.md`, либо с именем
    `Claude-Memory`. Файл → от его папки."""
    p = Path(os.path.expanduser(str(path))).resolve()
    if p.is_file():
        p = p.parent
    for cand in (p, *p.parents):
        if cand.name == "Claude-Memory" or (cand / "_hub").is_dir() or ((cand / "Portfolio").is_dir() and (cand / "INDEX.md").is_file()):
            return cand
    return None


def _parse(doc) -> dict:
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA or doc.get("ai_mode") not in MODES:
        raise ValueError(f"ожидается {SCHEMA} с ai_mode on|off")
    return doc


def _read_network() -> dict | None:
    url, auth = os.environ.get("HUB_URL", "").rstrip("/"), os.environ.get("HUB_AUTH", "")
    if not url or not auth:
        return None
    req = urllib.request.Request(url + "/api/hub/settings", headers={"Authorization": auth, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=_NET_TIMEOUT) as r:
            body = json.loads(r.read().decode("utf-8"))
        return _parse(body.get("settings"))
    except Exception:   # сеть, 403, формат — всё одинаково: падаем на файл зеркала
        return None


def _read_file(root: Path | None) -> dict | None:
    if root is None:
        return None
    p = root / FILE_REL
    if not p.is_file():
        return None
    try:
        return _parse(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        print(f"⚠ {p}: файл флага не читается ({exc}) — считаю режим «с ИИ»", file=sys.stderr)
        return None


def _stale(settings: dict, max_age_days: int) -> bool:
    upd = settings.get("updated_at")
    if not isinstance(upd, str) or len(upd) < 19:
        return False
    try:
        t = datetime.fromisoformat(upd)
    except ValueError:
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=_MSK)
    return datetime.now(_MSK) - t > timedelta(days=max_age_days)


def read(path, max_age_days: int = 7) -> dict:
    """Режим и откуда он взят. Сеть → файл зеркала → по умолчанию `on`."""
    net = _read_network()
    if net is not None:
        return {"ai_mode": net["ai_mode"], "source": "network", "settings": net, "stale": False}
    root = find_root(path)
    doc = _read_file(root)
    if doc is not None:
        stale = _stale(doc, max_age_days)
        if stale:
            print(f"⚠ флаг режима на зеркале от {doc.get('updated_at')} — старше {max_age_days} дн.; "
                  f"сверь с сайтом (хаб → «Режим») или задай HUB_URL/HUB_AUTH", file=sys.stderr)
        return {"ai_mode": doc["ai_mode"], "source": "file", "settings": doc, "stale": stale}
    return {"ai_mode": "on", "source": "default", "settings": None, "stale": False}


def ai_mode(path, max_age_days: int = 7) -> str:
    return read(path, max_age_days)["ai_mode"]


def mirror_lag(path, hours: int = LAG_HOURS, zones=None) -> dict | None:
    """Сверка зеркала Mac с NAS: файлы, изменённые на NAS за последние `hours` часов (GET /api/hub/changes с sha256),
    против файлов зеркала; `zones` — только пути с этими префиксами (зона скрипта: ("Portfolio", "scenarios") у
    портфельных, ("Health",) у здоровья …), None — все. Отставать могут только файлы, которые пишет сайт, поэтому
    зона сужает проверку без потери защиты. None — проверить нельзя (нет HUB_URL/HUB_AUTH, нет корня, сайт не ответил)."""
    import hashlib
    url, auth = os.environ.get("HUB_URL", "").rstrip("/"), os.environ.get("HUB_AUTH", "")
    root = find_root(path)
    if not url or not auth or root is None:
        return None
    since = (datetime.now(_MSK) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S+03:00")
    req = urllib.request.Request(url + "/api/hub/changes?since=" + urllib.parse.quote(since),
                                 headers={"Authorization": auth, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=_NET_TIMEOUT * 4) as r:
            body = json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    files = body.get("files") if isinstance(body, dict) else None
    if not isinstance(files, list):
        return None
    if zones:
        zs = tuple(z.rstrip("/") + "/" for z in zones)
        files = [f for f in files if ((f or {}).get("path") or "").startswith(zs)]
    behind = []
    for f in files:
        rel, sha = (f or {}).get("path") or "", (f or {}).get("sha256")
        if not rel or not sha:
            continue
        local = root / rel
        try:
            ok = local.is_file() and hashlib.sha256(local.read_bytes()).hexdigest() == sha
        except OSError:
            ok = False
        if not ok:
            behind.append(rel)
    return {"checked": len(files), "behind": behind, "truncated": bool(body.get("truncated"))}


def guard_mirror(path, script: str, action: str = "запись", zones=None) -> dict | None:
    """Отстающее зеркало — stderr и выход кодом EXIT_LAG; проверить нельзя — молча None (запись идёт)."""
    lag = mirror_lag(path, zones=zones)
    if lag and lag["behind"]:
        shown = ", ".join(lag["behind"][:5]) + (" …" if len(lag["behind"]) > 5 else "")
        print(f"✗ зеркало Mac отстаёт от NAS: {len(lag['behind'])} файл(ов) не совпадают ({shown}). {script} — {action} "
              f"не выполняется, иначе запись пойдёт поверх устаревшей копии. Дождись Synology Drive «Up to date» и повтори.",
              file=sys.stderr)
        raise SystemExit(EXIT_LAG)
    return lag


def require_ai(path, script: str, action: str = "запись", zones=None) -> dict:
    """Гейт писателя с входом от модели: при `off` — stderr и выход кодом EXIT_OFF; при доступной сети — ещё и сверка
    зеркала (guard_mirror, код EXIT_LAG); иначе возвращает read()."""
    info = read(path)
    if info["ai_mode"] == "off":
        since = (info["settings"] or {}).get("off_since") or "?"
        print(f"✗ сайт в режиме «без ИИ» (с {since}): {script} — {action} в Claude-Memory не выполняется, "
              f"правки идут с сайта. Вернуть режим «с ИИ»: хаб → «Режим» → «Вернуться к ИИ».", file=sys.stderr)
        raise SystemExit(EXIT_OFF)
    guard_mirror(path, script, action, zones)
    return info


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    info = read(argv[0])
    print(json.dumps({"ai_mode": info["ai_mode"], "source": info["source"], "stale": info["stale"],
                      "root": str(find_root(argv[0]) or "")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
