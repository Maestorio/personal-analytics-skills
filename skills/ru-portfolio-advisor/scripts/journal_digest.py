#!/usr/bin/env python3
"""
journal_digest.py — короткая выборка журнала решений `Portfolio/decision-journal/journal.json` (C5, schema.md §6):
вопросы об отказах, эпизоды по бумаге или за период и открытые тезисы — вместо чтения журнала целиком (≈1,5 МБ).

Журнал пишет только сборка (portfolio-data-loader, сайт); ответы об отказах уже вложены в эпизоды (`owner_reason`),
поэтому `refusals.yaml` и `theses.yaml` отдельно не читаются. Скрипт только читает.

Вызов:  python3 journal_digest.py --root <корень Claude-Memory> [--class stock|bond] [--key K] [--since ГГГГ-ММ-ДД]
                                   [--limit N]
  --class   вопросы и итог только этого класса (режим 1 — stock, режим 2 — bond);
  --key     эпизоды одной бумаги (все, новые первыми, не больше --limit);
  --since   эпизоды с last_date ≥ даты (новые первыми, не больше --limit);
  без --key и --since эпизодов в выдаче нет: только итог, вопросы и тезисы.
Выдача (JSON): as_of, summary (по классу), pending_questions (episode_id, вопрос дословно), episodes (episode_id,
вердикт, направление, даты, исполнено/нет, причина владельца, исход 3 мес.), theses (открытые: id, событие,
срок проверки, p). Нет журнала — `{"ok": true, "missing": true}`: шаг пропускается, журнал не создаётся.

Зависимости: stdlib.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

JOURNAL_REL = ("Portfolio", "decision-journal", "journal.json")
CLASSES = ("stock", "bond")
LIMIT = 10


def _episode(e: dict) -> dict:
    o = e.get("outcome") or {}
    return {"episode_id": e.get("episode_id"), "verdict": e.get("verdict"), "direction": e.get("direction"),
            "first_date": e.get("first_date"), "last_date": e.get("last_date"), "reviews": e.get("reviews"),
            "concordance": e.get("concordance"), "owner_reason": e.get("owner_reason"),
            "hit_3m": o.get("hit_3m"), "rel_3m": o.get("rel_3m")}


def build(root: str, cls: str | None, key: str | None, since: str | None, limit: int) -> dict:
    path = os.path.join(os.path.abspath(os.path.expanduser(root)), *JOURNAL_REL)
    if not os.path.isfile(path):
        return {"ok": True, "missing": True, "path": "/".join(JOURNAL_REL)}
    with open(path, encoding="utf-8") as f:
        j = json.load(f)
    summary = j.get("summary") or {}
    pq = [q for q in j.get("pending_questions") or [] if cls is None or q.get("class") == cls]
    out = {"ok": True, "missing": False, "as_of": j.get("as_of"),
           "summary": {cls: summary.get(cls)} if cls else summary,
           "pending_questions": [{"episode_id": q.get("episode_id"), "question": q.get("question")} for q in pq],
           "theses": [{"id": t.get("id"), "event": t.get("event"), "check_date": t.get("check_date"), "p": t.get("p"),
                       "opened": t.get("opened")}
                      for t in j.get("theses") or [] if isinstance(t, dict) and t.get("status") == "open"]}
    if key or since:
        eps = [e for e in j.get("episodes") or [] if isinstance(e, dict)
               and (cls is None or e.get("class") == cls)
               and (key is None or e.get("position") == key)
               and (since is None or str(e.get("last_date") or "") >= since)]
        eps.sort(key=lambda e: (str(e.get("last_date") or ""), str(e.get("episode_id") or "")), reverse=True)
        out["episodes_total"] = len(eps)
        out["episodes"] = [_episode(e) for e in eps[:limit]]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Выборка журнала решений (C5)")
    ap.add_argument("--root", required=True, help="корень Claude-Memory (в Cowork — $HOME/mnt/Claude-Memory)")
    ap.add_argument("--class", dest="cls", choices=CLASSES, default=None)
    ap.add_argument("--key", default=None, help="тикер или ISIN")
    ap.add_argument("--since", default=None, help="ГГГГ-ММ-ДД")
    ap.add_argument("--limit", type=int, default=LIMIT)
    a = ap.parse_args(argv)
    if a.since is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.since):
        print(json.dumps({"ok": False, "error": f"--since: ожидается ГГГГ-ММ-ДД, получено {a.since!r}"},
                         ensure_ascii=False))
        return 1
    if a.limit < 1:
        print(json.dumps({"ok": False, "error": "--limit: ожидается целое ≥ 1"}, ensure_ascii=False))
        return 1
    try:
        out = build(a.root, a.cls, a.key, a.since, a.limit)
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
