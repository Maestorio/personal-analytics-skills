#!/usr/bin/env python3
"""
archive_snapshot.py — отложить существующий снапшот дня перед перезаписью (PDL-SNAPV).

Зачем. 16.10.2026 `portfolio-2026-10-16.json` пересобран в 18:21 под тем же именем, уже после
того как на него сослались обзоры акций и облигаций. В новой версии другие доли IE и цены —
обзоры по `snapshot_id` больше не воспроизводились, стаб на новой версии дал несогласованные
веса (inc-2026-10-20-4, -10). Имя файла не меняем (на шаблон `portfolio-YYYY-MM-DD.json`
завязаны вьюер, советник, стресс и журнал решений) — вместо этого старая версия уходит в
`snapshots/.versions/portfolio-YYYY-MM-DD.<generated_at>.json`. Обзор, вышедший до перезаписи,
восстанавливается по своей дате и времени из этой папки.

CLI (Шаг 7 SKILL.md, ПЕРЕД Write нового снапшота):
  python3 scripts/archive_snapshot.py --snapshots-dir "{MEMORY_ROOT}/Portfolio/snapshots" --date 2026-10-16
Выход — JSON: {"archived": true, "to": "...", "generated_at": "..."} или {"archived": false, "reason": "..."}.
Ничего не удаляет и не перезаписывает: если версия с таким generated_at уже отложена — пропуск.
Зависимости: только stdlib.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys


def archive(snapshots_dir: str, day: str) -> dict:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        return {"archived": False, "reason": f"дата {day!r} не ISO"}
    src = os.path.join(snapshots_dir, f"portfolio-{day}.json")
    if not os.path.exists(src):
        return {"archived": False, "reason": "снапшота за эту дату нет — перезаписывать нечего"}
    try:
        with open(src, encoding="utf-8") as f:
            gen = str(json.load(f).get("generated_at") or "")
    except (OSError, json.JSONDecodeError) as exc:
        gen = ""
        reason = f"старый файл не читается как JSON ({exc}); отложен по времени изменения"
    else:
        reason = None
    stamp = re.sub(r"[^0-9T]", "", gen)[:13] if gen else ""  # 2026-10-16T00:45:47 → 20261016T0045
    if not stamp:
        import datetime as _dt
        stamp = _dt.datetime.fromtimestamp(os.path.getmtime(src)).strftime("%Y%m%dT%H%M") + "mtime"
    dst_dir = os.path.join(snapshots_dir, ".versions")
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, f"portfolio-{day}.{stamp}.json")
    if os.path.exists(dst):
        return {"archived": False, "reason": "эта версия уже отложена", "to": dst, "generated_at": gen}
    shutil.copy2(src, dst)
    out = {"archived": True, "to": dst, "generated_at": gen}
    if reason:
        out["note"] = reason
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--snapshots-dir", required=True)
    ap.add_argument("--date", required=True)
    a = ap.parse_args(argv)
    print(json.dumps(archive(a.snapshots_dir, a.date), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
