#!/usr/bin/env python3
"""Разовое заполнение справочника бумаг `security-attrs@1` (шаг 9 цикла машиночитаемости, schema.md §4.8).

Пишет ТОЛЬКО в `--out <временный корень>`: `<out>/Portfolio/security-attrs.json` (временный файл + os.replace,
проверка `ds_schemas.validate_security_attrs` до записи) и `<out>/security-attrs-report.md`. Путь `--out` внутри
рабочей Claude-Memory (кроме `_archive/`) — ошибка; в рабочую папку файл кладёт оркестратор при переключении.
Постоянный писатель справочника — `security_attrs.py` в save-to-library (шаг 10), не этот скрипт.

Правила:
 1. Ключи `by_key` — все ключи `Portfolio/security-types.json` (`by_ticker`) плюс ключи держаний снапшота
    (`ticker`, иначе `isin`). У каждого ключа запись из пяти полей; «нет класса» = `ticker_class: null`.
 2. `ticker_class` — из архивного `gate-reviews.yaml` (`tickers.<T>.ticker_class`; пусто → null); класс вне
    кодлиста `ticker_class` — ошибка (новый код не придумывается — остановка).
 3. `listed_at` — только акциям (`type: stock` в реестре типов), которые есть в снапшоте или имеют класс: первая
    дата торгов на Мосбирже на ЛЮБОЙ доске из ISS `history/engines/stock/markets/shares/securities/{secid}.json?
    from=1990-01-01&limit=1` (первая строка, поле TRADEDATE). TQBR не берётся: для старых бумаг он даёт запуск
    режима 2013–2014, а не листинг. Переезды под новым тикером (T, X5, YDEX, HEAD, GLRX) истории старше
    2024–2025 не имеют — попадают в «проверить владельцу». Таймаут 10 с и один повтор; ответа нет — null и
    пометка в отчёте. `--offline` — сеть не трогается, всем null с пометкой. Остальным бумагам — null.
 4. `note: null`, `updated_at` = time_msk.now_iso(), `updated_by: script`.
 5. Отчёт: бумаги класса `ipo` с `listed_at`, возрастом в кварталах (дни // 91.3125, как в сборке снапшота) и
    `listing_age_quarters`/`post_ipo_guard` из последнего обзора акций и датой из снапшота; акции с `listed_at`
    2024–2026 и классом не `ipo` (переезды вроде X5, HEAD, YDEX) — «проверить владельцу»; расхождение `listed_at`
    с `holdings[].listing_date` снапшота — отдельной таблицей.

Запуск: ~/.pyenv/versions/3.12.9/bin/python3 tools/data-structures/migrations/init_security_attrs.py \\
          --types <security-types.json> --snapshot <portfolio-*.json> --gates <архивный gate-reviews.yaml> \\
          --reviews <архивная папка weekly-reviews> --out <корень> [--offline] [--today ГГГГ-ММ-ДД]
Зависимости: stdlib + PyYAML.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
for _p in (str(HERE), str(REPO / "_shared-references")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import conditions_merge as cm  # noqa: E402
import ds_schemas as ds  # noqa: E402
import time_msk  # noqa: E402
from backfill_decisions import Fail, _guard_out  # noqa: E402

ISS_ANY = ("https://iss.moex.com/iss/history/engines/stock/markets/shares/securities/{secid}.json"
           "?from=1990-01-01&limit=1&history.columns=SECID,TRADEDATE,BOARDID")
TIMEOUT = 10
QUARTER_DAYS = 91.3125
RECENT_YEARS = ("2024", "2025", "2026")


def _get(url):
    """JSON ISS: таймаут 10 с, один повтор. Ошибка — None."""
    for attempt in (1, 2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "claude-skills/init_security_attrs"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            if attempt == 1:
                time.sleep(1)
    return None


def _first_date(payload):
    try:
        h = payload["history"]
        cols, data = h["columns"], h["data"]
        if data:
            v = data[0][cols.index("TRADEDATE")]
            return v if ds.is_date(v) else None
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    return None


def iss_listed_at(secid, fetch=_get):
    """(дата, доска | причина null): первая строка истории на любой доске."""
    p = fetch(ISS_ANY.format(secid=secid))
    if p is None:
        return None, "ISS не ответил"
    d = _first_date(p)
    if not d:
        return None, "нет истории на ISS"
    try:
        h = p["history"]
        board = h["data"][0][h["columns"].index("BOARDID")]
    except (KeyError, ValueError, IndexError, TypeError):
        board = "?"
    return d, board


def _quarters(listed_at, today):
    return max(int((date.fromisoformat(today) - date.fromisoformat(listed_at)).days // QUARTER_DAYS), 0)


def last_stock_review(reviews_dir):
    files = sorted(glob.glob(os.path.join(str(reviews_dir), "weekly-review-stock-*.yaml")))
    if not files:
        return None, {}
    y = cm.load_yaml(files[-1]) or {}
    ps = y.get("per_stock")
    rows = ps if isinstance(ps, dict) else {p.get("ticker"): p for p in (ps or []) if isinstance(p, dict)}
    return os.path.basename(files[-1]), rows


def build(types, snapshot, gates, today, now, offline=False, fetch=_get):
    """(документ security-attrs@1, сведения для отчёта)."""
    by_ticker = types.get("by_ticker") or {}
    holdings = [h for h in snapshot.get("holdings") or [] if (h.get("qty") or 0) > 0]
    snap_keys = {(h.get("ticker") or h.get("isin")) for h in holdings}
    classes = {}
    for t, rec in (gates or {}).items():
        c = rec.get("ticker_class") if isinstance(rec, dict) else None
        c = None if c in (None, "") else str(c)
        if c is not None and c not in ds.TICKER_CLASSES:
            raise Fail(f"класс {c!r} у {t} вне кодлиста ticker_class — новый код не вводится, нужно решение")
        classes[t] = c
    keys = sorted(set(by_ticker) | snap_keys | set(classes))
    fetched, notes = {}, {}
    for k in keys:
        is_stock = (by_ticker.get(k) or {}).get("type") == "stock"
        if not is_stock or not (k in snap_keys or classes.get(k)):
            continue
        if offline:
            fetched[k], notes[k] = None, "offline — дата не запрашивалась"
        else:
            fetched[k], notes[k] = iss_listed_at(k, fetch)
    doc = {"schema_version": ds.SECURITY_ATTRS_SCHEMA_VERSION, "by_key": {
        k: {"ticker_class": classes.get(k), "listed_at": fetched.get(k), "note": None, "updated_at": now,
            "updated_by": "script"} for k in keys}}
    info = {"keys": len(keys), "from_types": len(by_ticker), "snap_only": sorted(snap_keys - set(by_ticker)),
            "gates_only": sorted(set(classes) - set(by_ticker) - snap_keys), "classes": classes,
            "fetched": fetched, "fetch_notes": notes, "snap_listing": {
                (h.get("ticker") or h.get("isin")): h.get("listing_date") for h in holdings}, "today": today}
    return doc, info


def render_report(doc, info, review_name, review_rows, offline):
    bk, today = doc["by_key"], info["today"]
    n_cls = sum(1 for r in bk.values() if r["ticker_class"])
    n_dt = sum(1 for r in bk.values() if r["listed_at"])
    cls_count = {}
    for r in bk.values():
        if r["ticker_class"]:
            cls_count[r["ticker_class"]] = cls_count.get(r["ticker_class"], 0) + 1
    L = ["# Справочник бумаг security-attrs@1 — разовое заполнение (шаг 9)", "",
         f"- Записей: **{info['keys']}** (реестр типов {info['from_types']}; только в снапшоте: "
         f"{', '.join(info['snap_only']) or 'нет'}; только в гейтах: {', '.join(info['gates_only']) or 'нет'}).",
         f"- С классом: {n_cls} ({', '.join(f'{k} {v}' for k, v in sorted(cls_count.items()))}); остальные — null.",
         f"- Акций, для которых запрошена дата листинга: {len(info['fetched'])}; дата получена: {n_dt}."
         + (" **Режим --offline: сеть не трогалась, все даты null.**" if offline else ""), ""]
    nulls = [(k, info["fetch_notes"][k]) for k, v in sorted(info["fetched"].items()) if v is None]
    if nulls:
        L += ["Без даты: " + "; ".join(f"{k} ({why})" for k, why in nulls), ""]
    L += [f"## Класс `ipo` (последний обзор акций: `{review_name or '—'}`)", "",
          "| бумага | listed_at (ISS, любая доска) | доска | кварталов на сегодня | дата в снапшоте | "
          "listing_age_quarters (обзор) | post_ipo_guard (обзор) |",
          "|---|---|---|---|---|---|---|"]
    for k, r in sorted(bk.items()):
        if r["ticker_class"] != "ipo":
            continue
        pr = review_rows.get(k) or {}
        q = _quarters(r["listed_at"], today) if r["listed_at"] else "—"
        L.append(f"| {k} | {r['listed_at'] or '—'} | {info['fetch_notes'].get(k) or '—'} | {q} | "
                 f"{info['snap_listing'].get(k) or '—'} | {pr.get('listing_age_quarters', '—')} | "
                 f"{pr.get('post_ipo_guard', '—')} |")
    L += ["", "## Проверить владельцу: дата листинга 2024–2026, класс не `ipo`", "",
          "| бумага | listed_at (ISS, любая доска) | класс | дата в снапшоте |", "|---|---|---|---|"]
    for k, r in sorted(bk.items()):
        if r["listed_at"] and r["listed_at"][:4] in RECENT_YEARS and r["ticker_class"] != "ipo":
            L.append(f"| {k} | {r['listed_at']} | {r['ticker_class'] or 'null'} | {info['snap_listing'].get(k) or '—'} |")
    diff = [(k, v, info["snap_listing"].get(k)) for k, v in sorted(info["fetched"].items())
            if v and info["snap_listing"].get(k) and info["snap_listing"][k] != v]
    L += ["", "## Расхождение с `holdings[].listing_date` снапшота", "",
          "Снапшот берёт `listing_from` из `/history/.../dates.json`, справочник — первую строку истории на любой доске.",
          "", "| бумага | справочник | снапшот |", "|---|---|---|"]
    L += [f"| {k} | {v} | {s} |" for k, v, s in diff] or ["| — | — | — |"]
    return "\n".join(L) + "\n"


def _write_atomic(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Разовое заполнение справочника бумаг security-attrs@1 (шаг 9)")
    ap.add_argument("--types", required=True, help="Portfolio/security-types.json (читается, не пишется)")
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--gates", required=True, help="архивный gate-reviews.yaml")
    ap.add_argument("--reviews", default=None, help="папка weekly-reviews (последний обзор акций — для отчёта)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--today", default=None)
    ap.add_argument("--now", default=None, help=argparse.SUPPRESS)  # детерминизм тестов
    a = ap.parse_args(argv)
    try:
        out = _guard_out(Path(a.out))
        with open(a.types, encoding="utf-8") as f:
            types = json.load(f)
        with open(a.snapshot, encoding="utf-8") as f:
            snapshot = json.load(f)
        gdoc = cm.load_yaml(a.gates)
        gates = (gdoc or {}).get("tickers") or {}
        now = a.now or time_msk.now_iso()
        today = a.today or now[:10]
        doc, info = build(types, snapshot, gates, today, now, a.offline)
        errs = ds.validate_security_attrs(doc)
        if errs:
            raise Fail("справочник не проходит validate_security_attrs: " + "; ".join(errs[:20]))
        target = out / "Portfolio" / "security-attrs.json"
        _write_atomic(target, doc)
        review_name, review_rows = last_stock_review(a.reviews) if a.reviews else (None, {})
        (out / "security-attrs-report.md").write_text(
            render_report(doc, info, review_name, review_rows, a.offline), encoding="utf-8")
    except Fail as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"ok": True, "written": str(target), "keys": info["keys"],
                      "with_class": sum(1 for r in doc["by_key"].values() if r["ticker_class"]),
                      "listed_at": sum(1 for r in doc["by_key"].values() if r["listed_at"]),
                      "requested": len(info["fetched"]), "offline": a.offline,
                      "report": str(out / "security-attrs-report.md")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
