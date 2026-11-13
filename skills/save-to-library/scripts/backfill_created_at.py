#!/usr/bin/env python3
"""Проставить `created_at` в frontmatter старых отчётов советника из времени файла (разовая чистка).

С 2026-10-28 save-to-library пишет `created_at: "YYYY-MM-DDTHH:MM"` в frontmatter отчёта при сохранении;
вьюер сортирует отчёты и события «Истории» внутри дня по этому полю, а без него — по времени файла (mtime).
mtime теряется при копировании и правке, поэтому у старых отчётов время переносится в шапку один раз.

Правило: только Portfolio/reports/*.md с YAML-frontmatter, полем `date` и БЕЗ `created_at`; время берётся
из mtime файла (локальное время) и записывается, только если день mtime совпадает с `date` — отчёт,
дописанный или сохранённый на следующий день, пропускается (время файла не говорит, когда он создан).
Файл переписывается атомарно, mtime восстанавливается (его читают и другие потребители).

Запуск (писатель — save-to-library, правило D3): сначала без флага — таблица «что будет», затем --apply.
    python3 backfill_created_at.py --memory ~/Library/CloudStorage/SynologyDrive-home/Claude-Memory [--apply]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import sys
import tempfile
from pathlib import Path

_FM_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_DATE_RE = re.compile(r"^date:\s*[\"']?(\d{4}-\d{2}-\d{2})[\"']?\s*$", re.M)
_CREATED_RE = re.compile(r"^created_at:", re.M)


def plan_file(path: Path) -> dict:
    """Решение по одному файлу: {file, action: stamp|skip, reason, created_at}."""
    text = path.read_text(encoding="utf-8")
    m = _FM_RE.match(text)
    if not m:
        return {"file": path.name, "action": "skip", "reason": "нет frontmatter"}
    fm = m.group(1)
    if _CREATED_RE.search(fm):
        return {"file": path.name, "action": "skip", "reason": "created_at уже есть"}
    dm = _DATE_RE.search(fm)
    if not dm:
        return {"file": path.name, "action": "skip", "reason": "нет поля date"}
    mtime = _dt.datetime.fromtimestamp(path.stat().st_mtime)
    if mtime.strftime("%Y-%m-%d") != dm.group(1):
        return {"file": path.name, "action": "skip",
                "reason": f"день файла {mtime:%Y-%m-%d %H:%M} ≠ date {dm.group(1)}"}
    return {"file": path.name, "action": "stamp", "created_at": mtime.strftime("%Y-%m-%dT%H:%M")}


def stamp_file(path: Path, created_at: str) -> None:
    """Вставить `created_at` строкой после `date:` атомарно, сохранив mtime файла."""
    st = path.stat()
    text = path.read_text(encoding="utf-8")
    m = _FM_RE.match(text)
    fm = m.group(1)
    new_fm = _DATE_RE.sub(lambda d: d.group(0) + f'\ncreated_at: "{created_at}"', fm, count=1)
    out = text[: m.start(1)] + new_fm + text[m.end(1):]
    fd, tmp = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(out)
    os.replace(tmp, path)
    os.utime(path, (st.st_atime, st.st_mtime))


def run(memory: Path, apply: bool) -> list[dict]:
    rdir = memory / "Portfolio" / "reports"
    plans = [plan_file(p) for p in sorted(rdir.glob("*.md"))]
    if apply:
        for pl in plans:
            if pl["action"] == "stamp":
                stamp_file(rdir / pl["file"], pl["created_at"])
    return plans


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--memory", required=True, help="корень Claude-Memory")
    ap.add_argument("--apply", action="store_true", help="записать (без флага — только показать)")
    a = ap.parse_args()
    memory = Path(a.memory).expanduser()
    if not (memory / "Portfolio" / "reports").is_dir():
        print(f"нет папки {memory / 'Portfolio' / 'reports'}", file=sys.stderr)
        return 2
    plans = run(memory, a.apply)
    n_st = sum(1 for p in plans if p["action"] == "stamp")
    for p in plans:
        print(f"{'✓' if p['action'] == 'stamp' else '·'} {p['file']}  {p.get('created_at') or p['reason']}")
    print(f"\n{'записано' if a.apply else 'будет записано'}: {n_st} из {len(plans)}; пропущено: {len(plans) - n_st}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
