#!/usr/bin/env python3
"""
sweep_collect.py — сборщик результатов fan-out sweep из файлов (RPA-25).

Зачем. 16.10.2026 четыре sweep-агента обзора акций вернули результаты прямо в контекст;
после 3–4 компакций они пропали, и модель восстанавливала их из журнала сессии
(inc-2026-10-20-13). Теперь каждый агент пишет свой JSON в файл `sweep/sweep-<батч>.json`,
а в чат возвращает одну строку. Этот скрипт читает файлы, проверяет формат и провенанс,
и отдаёт родителю короткую сводку: только события, списки «тихих», недопроверенных и
отброшенных строк, кандидатов на ярус 2 и блок покрытия для YAML. Файлы на диске
переживают компакцию; сводку можно перечитать в любой момент.

Вход:
  --rows rows.json        строки, которые родитель ОТПРАВИЛ агентам: [{"key","name",...}]
  --dir  sweep/           каталог с sweep-*.json (каждый — JSON-массив объектов по fanout-news.md)
  --mode 1|2              правила эскалации на ярус 2 (fanout-news.md)
  --today YYYY-MM-DD      дата прогона (accessed не может быть позже)
Выход: JSON {coverage (в т.ч. checked_dates: {ключ: дата проверки}), events, quiet, budget_exhausted, missing, rejected, escalate, ratings}
  в stdout; с --md — ещё и Markdown-сводка в файл.

Проверки (строка не проходит → rejected с причиной, в покрытие НЕ попадает):
  - key есть среди отправленных строк;
  - searched_as совпадает с отправленным name (без регистра/кавычек/ОПФ) — иначе агент искал
    другую компанию (кейсы BTBR «BitRiver», RU000A107AW3 «Аэрофьючерс», 15.08.2026);
  - status ∈ quiet|events|budget_exhausted; события с ISO event_date, kind из перечня и url;
  - accessed — ISO-дата не позже today.
Строка, отправленная агенту, но не вернувшаяся ни в одном файле, — missing (не проверена).
Зависимости: только stdlib.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from datetime import date

STATUSES = {"quiet", "events", "budget_exhausted"}
KINDS = {"report", "dividend", "rating", "offer", "default", "court", "sanction", "guidance", "other"}
ESCALATE_KINDS = {"2": {"rating", "offer", "default", "court", "sanction"}, "1": {"sanction", "court"}}
_LEGAL = re.compile(r"\b(пао|ао|ооо|мфк|зпиф|бпиф|ип|пк|гк|ltd|plc|inc|llc|jsc|pjsc)\b")


def _norm(name: str) -> str:
    s = str(name or "").lower().replace("ё", "е")
    s = re.sub(r"[«»\"'“”()\-–—.,]", " ", s)
    s = _LEGAL.sub(" ", s)
    return " ".join(s.split())


def _same_company(sent: str, searched: str) -> bool:
    a, b = _norm(sent), _norm(searched)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _iso(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def collect(rows: list[dict], files: list[str], mode: str, today: date) -> dict:
    sent = {r["key"]: r for r in rows}
    seen: dict[str, dict] = {}
    rejected, file_errors = [], []
    for path in sorted(files):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            file_errors.append({"file": os.path.basename(path), "error": str(exc)})
            continue
        if not isinstance(data, list):
            file_errors.append({"file": os.path.basename(path), "error": "ожидался JSON-массив"})
            continue
        for obj in data:
            key = obj.get("key") if isinstance(obj, dict) else None
            why = []
            if key not in sent:
                why.append("key не из отправленных строк")
            else:
                if not _same_company(sent[key].get("name"), obj.get("searched_as")):
                    why.append(f"searched_as «{obj.get('searched_as')}» ≠ name «{sent[key].get('name')}»")
            st = obj.get("status") if isinstance(obj, dict) else None
            if st not in STATUSES:
                why.append(f"status {st!r} вне {sorted(STATUSES)}")
            acc = _iso(obj.get("accessed")) if isinstance(obj, dict) else None
            if acc is None or acc > today:
                why.append(f"accessed {obj.get('accessed') if isinstance(obj, dict) else None!r} не ISO или в будущем")
            evs = obj.get("events") or [] if isinstance(obj, dict) else []
            if st == "events" and not evs:
                why.append("status events без событий")
            for e in evs:
                if not isinstance(e, dict) or e.get("kind") not in KINDS or _iso(e.get("event_date")) is None \
                        or not str(e.get("url") or "").startswith("http"):
                    why.append(f"событие без kind/ISO event_date/url: {str(e)[:80]}")
            if why:
                rejected.append({"key": key, "file": os.path.basename(path), "reasons": why})
                continue
            if key in seen:  # дубль из другого батча — оставляем более позднюю проверку
                if str(obj.get("accessed")) <= str(seen[key].get("accessed")):
                    continue
            seen[key] = {**obj, "_file": os.path.basename(path)}

    rejected_keys = {r["key"] for r in rejected} - set(seen)
    missing = [k for k in sent if k not in seen and k not in rejected_keys]
    quiet = sorted(k for k, o in seen.items() if o["status"] == "quiet")
    exhausted = sorted(k for k, o in seen.items() if o["status"] == "budget_exhausted")
    events, escalate, ratings = [], [], {}
    for k, o in seen.items():
        evs = o.get("events") or []
        for e in evs:
            events.append({"key": k, "name": sent[k].get("name"), **{f: e.get(f) for f in ("kind", "event_date", "fact", "url")}})
        kinds = {e.get("kind") for e in evs}
        if kinds & ESCALATE_KINDS[mode] or (mode == "2" and len(evs) >= 2):
            escalate.append({"key": k, "name": sent[k].get("name"), "kinds": sorted(kinds)})
        if o.get("ratings"):
            ratings[k] = o["ratings"]
    events.sort(key=lambda e: (e["event_date"] or "", e["key"]))
    checked = sorted(k for k, o in seen.items() if o["status"] in ("quiet", "events"))
    coverage = {
        "method": "sweep_collect",  # RPA-34: валидатор сохранения требует его при ≥5 бумагах/корп-эмитентах
        "tickers_total": len(sent),
        "checked_this_run": checked,
        "carried_over": [],
        # дата проверки по бумагам — только проверенные (MD-таблица покрытия показывает её)
        "checked_dates": {k: str(seen[k].get("accessed"))[:10] for k in checked},
        "not_checked": sorted(set(exhausted) | set(missing) | rejected_keys),
        "note": (f"sweep {today.isoformat()}: проверено {len(checked)} из {len(sent)}; "
                 f"budget_exhausted {len(exhausted)}, не вернулись {len(missing)}, отброшено {len(rejected_keys)} "
                 "(не проверены — проверить самому или перечислить в caveats)"),
    }
    return {"coverage": coverage, "events": events, "quiet": quiet, "budget_exhausted": exhausted,
            "missing": missing, "rejected": rejected, "file_errors": file_errors,
            "escalate": escalate, "ratings": ratings,
            "accessed_by_key": {k: str(o.get("accessed"))[:10] for k, o in seen.items()}}


def to_md(res: dict) -> str:
    c = res["coverage"]
    out = [f"# Sweep: проверено {len(c['checked_this_run'])} из {c['tickers_total']}", ""]
    if res["events"]:
        out += ["## События", ""] + [f"- {e['event_date']} · {e['key']} ({e['name']}) · {e['kind']}: {e['fact']} — {e['url']}"
                                     for e in res["events"]] + [""]
    if res["escalate"]:
        out += ["## На ярус 2", ""] + [f"- {x['key']} ({x['name']}): {', '.join(x['kinds'])}" for x in res["escalate"]] + [""]
    if res["ratings"]:
        out += ["## Действующие рейтинги (по ответам sweep)", ""]
        for k, rs in res["ratings"].items():
            out.append(f"- {k}: " + "; ".join(f"{r.get('agency')} {r.get('rating')} {r.get('outlook_or_status') or ''} "
                                              f"({r.get('action')}, {r.get('action_date')})".strip() for r in rs))
        out.append("")
    out += [f"Тихо: {', '.join(res['quiet']) or '—'}", ""]
    bad = c["not_checked"]
    out += [f"**НЕ проверены ({len(bad)}):** {', '.join(bad) or '—'}"]
    for r in res["rejected"]:
        out.append(f"- отброшено {r['key']} ({r['file']}): {'; '.join(r['reasons'])}")
    for fe in res["file_errors"]:
        out.append(f"- файл {fe['file']}: {fe['error']}")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rows", required=True)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--mode", choices=("1", "2"), required=True)
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--md", help="куда записать Markdown-сводку")
    a = ap.parse_args(argv)
    with open(a.rows, encoding="utf-8") as f:
        rows = json.load(f)
    if not isinstance(rows, list) or not all(isinstance(r, dict) and r.get("key") for r in rows):
        print("ERROR: rows.json — массив объектов с key и name", file=sys.stderr)
        return 2
    files = glob.glob(os.path.join(a.dir, "sweep-*.json"))
    if not files:
        print(f"ERROR: в {a.dir} нет sweep-*.json — агенты не записали результаты", file=sys.stderr)
        return 2
    res = collect(rows, files, a.mode, date.fromisoformat(a.today))
    if a.md:
        with open(a.md, "w", encoding="utf-8") as f:
            f.write(to_md(res))
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
