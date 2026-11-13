#!/usr/bin/env python3
"""Бэкфилл решений по бумаге `decision@1` из архива носителей гейта (шаг 9 цикла машиночитаемости).

Спецификация: docs/investment/_cross-cutting/data-structures/schema.md §3.1 (решение), §3.5 (гейт — проекция
новейшего решения), §4.4 (28 записей гейта → решения), §5 строка «Вывод разбора»; decision.md §4 строка 9.
Разовый скрипт: читает АРХИВНЫЕ копии (`_archive/data-structures/<…>-step1/`), пишет ТОЛЬКО в `--out <временный
корень>` (`<out>/Portfolio/decisions/*.json` + `backfill-report.md`). Путь `--out` внутри рабочей Claude-Memory
(кроме `_archive/`) — ошибка: в рабочую папку решения кладёт оркестратор при переключении (decision.md §4.2).

Команды:
  build   --archive <папка архива шага 1> --out <корень>   (или по отдельности --gates/--reports/--reviews)
  verify  --out <корень> --gates <архивный gate-reviews.yaml> --snapshot <portfolio-*.json> --today ГГГГ-ММ-ДД
          [--types <security-types.json>]

ПРАВИЛА БЭКФИЛЛА (build)
 1. Источник решений — строки гейта со статусом `reviewed_*`; вердикт — обратное отображение `verdict_to_gate`:
    reviewed_keep → HOLD, reviewed_buy_more → ADD, reviewed_reduce → TRIM, reviewed_under_review → WATCH.
    Статусы new_position, review_needed, review_aging, divested решений не порождают (review_needed — флаг обзора,
    не вердикт, §4.4).
 2. Текущая запись бумаги: `reviewed_*` → решение с `review_by = valid_until`, `note = trigger_reason`; она же
    обычно повторена последней строкой `history[]` (одна и та же дата, статус, автор) — дубль не создаётся. Иначе
    (статус без вердикта) — решением служит последняя строка `history[]` с `reviewed_*`; нет такой — бумага без
    решения, в отчёте с причиной.
 3. Строки `history[]` с `set_by` ≠ auto и статусом `reviewed_*` — по решению на строку. `review_by` = дата
    следующей строки истории этой бумаги; если следующая строка — авто-истечение `review_aging` с текстом
    «valid_until ГГГГ-ММ-ДД expired», берётся эта дата (настоящий срок записи; правило сверх постановки,
    помечается `aging`); последней строке — `date + defaults.review_days`.
 4. `review_by` вне окна 7–180 дней от `recorded_at` (валидатор §3.1) — сдвигается к границе, пометка `clamp`.
 5. `recorded_at` = дата строки + `T00:00:00+03:00`, `recorded_at_estimated: true`; вторая запись той же бумаги
    в тот же день — `T00:01`, третья — `T00:02` (пометка `minute`). Порядок внутри дня — порядок истории,
    решения только из отчётов — после.
 6. `note` = причина до 200 знаков (длиннее — обрезка с «…»); `author` = model при `set_by` mode_*, owner при user;
    `source = {kind: backfill, doc: null, mode_codes: [], stress_id: null}`; `target_pct: null`, условия пусты.
 7. Директивы отчётов (`gate_review_update`, `gate_review_bulk_update` в YAML-блоках тела) и обзоров
    (`gate_review_directives[]`, `proposed_gate_review_directives[]`, `per_stock.*.gate_review_directive`)
    сверяются с решениями по (бумага, дата): совпал статус — решение обогащается (`source.doc` = путь от корня,
    `source.mode_codes` — коды режима отчёта по таблице миграции шапок, у обзора — режим обзора); в истории
    нет — отдельное решение с `doc` (`review_by` = дата + `valid_days`, иначе + review_days); статус расходится —
    решение не создаётся, строка «конфликт» в отчёте; директива без вердикта (review_needed) — «флаг обзора».
 8. Смены вердикта в обзорах (`per_stock.*.advisor_verdict` и т. п.) НЕ читаются: обзор и так источник §3.5.
 9. Строки архива гейтов (`gate-reviews-archive-2026.yaml`, `entries[]`, вынесенные из `history[]`) возвращаются
    в историю своей бумаги по дате (пометка `из архива гейтов`) и дальше идут по правилу 3.
10. Решение без директивы (правило 7 не нашло) связывается с отчётом той же даты, если такой отчёт ровно один:
    бумага в его `tickers[]` и код режима отчёта соответствует `set_by` строки (mode_8 → 8, mode_4 → 4a/4b,
    mode_5a → 5a, mode_1 → 1); пометка `doc по дате и режиму` — связь выведена, директивы в отчёте нет.

ПРОВЕРКА (verify) — статус гейта модулем (б) `last_word.card` (см. `projection`). Гейт считается только для акций
(`type: stock` по реестру типов `--types`); фонды и облигации исключаются из сравнения («гейт не ведётся»).
Итог по записи архива: совпало / устаревшая запись архива (`stale_archive`: в архиве живой статус, а бумаги нет в
снапшоте — архив не обслуживался после продажи; не ошибка) / расхождение (бумага в снапшоте и базовый статус не
совпал, или у `reviewed_*` архива нет решения). Код выхода 1 — только при расхождениях или невалидных файлах.

Запуск: ~/.pyenv/versions/3.12.9/bin/python3 tools/data-structures/migrations/backfill_decisions.py build …
Зависимости: stdlib + PyYAML.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
for _p in (str(HERE), str(REPO / "skills" / "save-to-library" / "scripts"), str(REPO / "_shared-references")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import codelists  # noqa: E402
import conditions_merge as cm  # noqa: E402
import decision_write as dw  # noqa: E402  (форма решения и атомарная запись — не копируются)
import ds_schemas as ds  # noqa: E402
import last_word as lw  # noqa: E402  (модуль (б): статус гейта — проверка verify)
import migrate_report_frontmatter as mig  # noqa: E402  (коды режима отчёта по старой шапке)

LIVE_ROOT = Path.home() / "Library/CloudStorage/SynologyDrive-home/Claude-Memory"
VERDICT_TO_GATE = codelists.map_("verdict_to_gate")
# Обратное отображение (§3.1 «единый словарь»): из двух вердиктов на статус берётся слабейший — ADD и TRIM.
GATE_TO_VERDICT = {"reviewed_keep": "HOLD", "reviewed_buy_more": "ADD", "reviewed_reduce": "TRIM",
                   "reviewed_under_review": "WATCH"}
REVIEW_DAYS = ds.DEFAULTS["review_days"]
AGING_RE = re.compile(r"valid_until\s+(\d{4}-\d{2}-\d{2})\s+expired")
FENCE_RE = re.compile(r"^```ya?ml[ \t]*\n(.*?)^```", re.S | re.M)
WEEKLY_MODE = {"stock": ["1"], "bond": ["2"]}
LLM_KINDS = ("single_analysis", "tactical_rebalance", "quality_review")

assert all(VERDICT_TO_GATE[v] == g for g, v in GATE_TO_VERDICT.items()), "verdict_to_gate разошёлся с обратной картой"


class Fail(Exception):
    pass


# ----------------------------------------------------------------------------- утилиты

def _s(v):
    return None if v is None else str(v)


def _plus(d: str, days: int) -> str:
    return (date.fromisoformat(d) + timedelta(days=days)).isoformat()


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _note(text) -> str:
    t = " ".join(str(text or "").split()) or "без причины в записи гейта"
    return t if len(t) <= ds.NOTE_MAX else t[: ds.NOTE_MAX - 1] + "…"


def _author(set_by) -> str:
    return "owner" if set_by in ("user", "owner") else "model"


def _guard_out(out: Path):
    out = out.resolve()
    live = LIVE_ROOT.resolve() if LIVE_ROOT.exists() else LIVE_ROOT
    if out == live or live in out.parents:
        if (live / "_archive") not in [out, *out.parents]:
            raise Fail(f"--out {out} внутри рабочей Claude-Memory: бэкфилл пишет только во временный корень")
    return out


# ----------------------------------------------------------------------------- источники

def load_gates(path) -> dict:
    doc = cm.load_yaml(str(path))
    if not isinstance(doc, dict) or not isinstance(doc.get("tickers"), dict):
        raise Fail(f"{path}: нет раздела tickers (ожидается gate-reviews@1.0)")
    return doc["tickers"]


def _directive_rows(obj, default_date, default_by):
    """Строки директив из блока gate_review_update / gate_review_bulk_update (любая из исторических форм)."""
    out = []

    def one(d, ticker=None, sd=None, sb=None):
        if not isinstance(d, dict):
            return
        status = d.get("new_status") or d.get("status")
        if not status and "review_needed" in str(d.get("proposed_action") or ""):
            status = "review_needed"
        out.append({"ticker": _s(d.get("ticker") or ticker), "status": _s(status),
                    "date": _s(d.get("set_date") or sd or default_date), "set_by": _s(d.get("set_by") or sb or default_by),
                    "reason": d.get("reason"), "valid_days": d.get("valid_days")})

    if isinstance(obj, list):
        for d in obj:
            one(d)
    elif isinstance(obj, dict):
        if "tickers" in obj and isinstance(obj["tickers"], dict):       # bulk: {set_date, set_by, tickers: {T: {...}}}
            for t, d in obj["tickers"].items():
                one(d, t, obj.get("set_date"), obj.get("set_by"))
        elif "directives" in obj and isinstance(obj["directives"], list):  # bulk: {set_date, set_by, directives: [...]}
            for d in obj["directives"]:
                one(d, None, obj.get("set_date"), obj.get("set_by"))
        else:
            one(obj)
    return out


def load_report_directives(reports_dir):
    """(директивы, метаданные отчётов, ошибки разбора). Директивы — из YAML-блоков тела отчёта."""
    directives, meta, errors = [], {}, []
    for path in sorted(glob.glob(os.path.join(str(reports_dir), "*.md"))):
        name = os.path.basename(path)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        r = mig.migrate_text(name, text)
        m = mig.FRONT_RE.match(text)
        fm = {}
        if m:
            try:
                fm = yaml.load(m.group(1), Loader=yaml.BaseLoader) or {}
            except yaml.YAMLError:
                fm = {}
        rdate = _s(fm.get("date")) or (re.search(r"\d{4}-\d{2}-\d{2}", name) or [None])[0]
        doc = f"Portfolio/reports/{name}"
        meta[doc] = {"kind": r.kind_new or fm.get("kind"), "mode_codes": list(r.codes or []),
                     "tickers": [t for t in (r.tickers_new or []) if isinstance(t, str)], "date": rdate}
        for block in FENCE_RE.findall(text):
            if "gate_review_update" not in block and "gate_review_bulk_update" not in block:
                continue
            try:
                y = yaml.load(block, Loader=yaml.BaseLoader)
            except yaml.YAMLError as e:
                errors.append(f"{doc}: блок YAML не разобран ({str(e).splitlines()[0]})")
                continue
            if not isinstance(y, dict):
                continue
            for k in ("gate_review_update", "gate_review_bulk_update"):
                if k in y:
                    for row in _directive_rows(y[k], rdate, None):
                        row.update(doc=doc, mode_codes=meta[doc]["mode_codes"], src=k)
                        directives.append(row)
    return directives, meta, errors


def load_review_directives(reviews_dir):
    out = []
    for path in sorted(glob.glob(os.path.join(str(reviews_dir), "weekly-review*.yaml"))):
        name = os.path.basename(path)
        y = cm.load_yaml(path)
        if not isinstance(y, dict):
            continue
        kind = "bond" if "-bond-" in name else "stock"
        rdate = _s(y.get("review_date")) or (re.search(r"\d{4}-\d{2}-\d{2}", name) or [None])[0]
        doc = f"Portfolio/weekly-reviews/{name}"
        found = []
        for k in ("gate_review_directives", "proposed_gate_review_directives"):
            for row in _directive_rows(y.get(k) or [], rdate, "mode_1"):
                row["src"] = k
                found.append(row)
        ps = y.get("per_stock")
        items = ps.items() if isinstance(ps, dict) else ((p.get("ticker"), p) for p in (ps or []) if isinstance(p, dict))
        for t, p in items:
            if isinstance(p, dict) and isinstance(p.get("gate_review_directive"), dict):
                for row in _directive_rows(p["gate_review_directive"], rdate, "mode_1"):
                    row["ticker"] = row["ticker"] or t
                    row["src"] = "per_stock.gate_review_directive"
                    found.append(row)
        for row in found:
            row.update(doc=doc, mode_codes=WEEKLY_MODE[kind])
            out.append(row)
    return out


# ----------------------------------------------------------------------------- сборка

def load_gates_archive(path) -> dict:
    """{бумага: [строки истории]} из архива гейтов (entries[] с полем ticker)."""
    if not path or not Path(path).is_file():
        return {}
    doc = cm.load_yaml(str(path))
    out = {}
    for e in (doc or {}).get("entries") or []:
        if isinstance(e, dict) and e.get("ticker"):
            out.setdefault(_s(e["ticker"]), []).append(e)
    return out


def collect_rows(gates: dict, archived: dict | None = None):
    """Строки-кандидаты в решения по истории и текущей записи + бумаги без решения."""
    rows, without = [], []
    archived = archived or {}
    for key, rec in gates.items():
        hist = [dict(h, _archived=False) for h in (rec.get("history") or []) if isinstance(h, dict)]
        arch = [dict(h, _archived=True) for h in archived.get(key, [])]
        # архивные строки — в историю по дате; при равной дате — перед строками файла (они старше выноса)
        hist = sorted(arch + hist, key=lambda h: (_s(h.get("date")) or "", 0 if h["_archived"] else 1))
        seq = []  # вся последовательность строк бумаги (для «следующей строки»)
        for i, h in enumerate(hist):
            seq.append({"key": key, "date": _s(h.get("date")), "status": _s(h.get("status")),
                        "set_by": _s(h.get("set_by")), "reason": h.get("reason"), "origin": "history", "pos": i,
                        "archived": h["_archived"]})
        cur = {"key": key, "date": _s(rec.get("set_date")), "status": _s(rec.get("status")),
               "set_by": _s(rec.get("set_by")), "reason": rec.get("trigger_reason"), "origin": "current",
               "valid_until": _s(rec.get("valid_until"))}
        last = seq[-1] if seq else None
        if last and (last["date"], last["status"], last["set_by"]) == (cur["date"], cur["status"], cur["set_by"]):
            last.update(origin="current", valid_until=cur["valid_until"], reason=cur["reason"] or last["reason"])
        else:
            cur["pos"] = len(seq)
            seq.append(cur)
        for i, r in enumerate(seq):
            r["next"] = seq[i + 1] if i + 1 < len(seq) else None
        picked = [r for r in seq if r["status"] in GATE_TO_VERDICT
                  and (r["origin"] == "current" or r["set_by"] != "auto")]
        if cur["status"] not in GATE_TO_VERDICT:
            fb = [r for r in seq if r["status"] in GATE_TO_VERDICT]
            if fb and fb[-1] not in picked:
                picked.append(fb[-1])
            if fb:
                fb[-1]["fallback_for"] = cur["status"]
        if not picked:
            without.append({"key": key, "status": cur["status"],
                            "reason": "нет ни одной строки reviewed_* (ни в текущей записи, ни в истории)"})
        rows.extend(sorted(picked, key=lambda r: r["pos"]))
    return rows, without


def _review_by(row):
    """(review_by, пометки) по правилам 2–3 докстринга, до окна валидатора."""
    if row["origin"] == "current" and row.get("valid_until"):
        return row["valid_until"], []
    if row.get("valid_days") not in (None, ""):
        try:
            return _plus(row["date"], int(row["valid_days"])), ["valid_days"]
        except ValueError:
            pass
    nxt = row.get("next")
    if nxt:
        m = AGING_RE.search(str(nxt.get("reason") or "")) if nxt["status"] == "review_aging" else None
        if m:
            return m.group(1), ["aging"]
        return nxt["date"], []
    return _plus(row["date"], REVIEW_DAYS), ["default60"]


def _clamp(rb, rec_date):
    d = _days(rec_date, rb)
    if d < ds.REVIEW_BY_MIN_DAYS:
        return _plus(rec_date, ds.REVIEW_BY_MIN_DAYS), f"clamp {d}→{ds.REVIEW_BY_MIN_DAYS} дн."
    if d > ds.REVIEW_BY_MAX_DAYS:
        return _plus(rec_date, ds.REVIEW_BY_MAX_DAYS), f"clamp {d}→{ds.REVIEW_BY_MAX_DAYS} дн."
    return rb, None


def reconcile(rows, directives):
    """Сверка директив с решениями: обогащение / новое решение / конфликт / флаг. Возвращает (rows, сверка)."""
    by_kd = {}
    for r in rows:
        by_kd.setdefault((r["key"], r["date"]), []).append(r)
    table, extra = [], []
    for d in directives:
        k, dt, st = d["ticker"], d["date"], d["status"]
        entry = {"doc": d["doc"], "src": d["src"], "key": k, "date": dt, "status": st}
        if not k or not dt or not st:
            entry["result"] = "пропуск: нет бумаги, даты или статуса"
        elif st not in GATE_TO_VERDICT:
            entry["result"] = f"флаг обзора ({st}) — решения не порождает"
        else:
            cands = by_kd.get((k, dt), [])
            same = [r for r in cands if r["status"] == st]
            if same:
                r = same[0]
                if r.get("doc"):
                    r.setdefault("docs_also", []).append(d["doc"])
                    entry["result"] = "совпало; doc уже от другого источника"
                    entry["row"] = r
                else:
                    r["doc"], r["mode_codes"] = d["doc"], list(d["mode_codes"])
                    entry["result"] = "обогащено (doc, mode_codes)"
                    entry["row"] = r
            elif cands:
                entry["result"] = ("конфликт: в истории на эту дату " + ", ".join(c["status"] for c in cands)
                                   + " — решение не создано")
            else:
                dup = [x for x in extra if (x["key"], x["date"], x["status"]) == (k, dt, st)]
                if dup:
                    dup[0].setdefault("docs_also", []).append(d["doc"])
                    entry["result"] = "повтор директивы — к уже созданному решению"
                    entry["row"] = dup[0]
                else:
                    r = {"key": k, "date": dt, "status": st, "set_by": d["set_by"] or "mode_4",
                         "reason": d["reason"], "origin": "report", "valid_days": d.get("valid_days"),
                         "doc": d["doc"], "mode_codes": list(d["mode_codes"]), "next": None}
                    extra.append(r)
                    entry["result"] = "в истории нет — отдельное решение с doc"
                    entry["row"] = r
        table.append(entry)
    return rows + extra, table


SET_BY_CODES = {"mode_8": ("8",), "mode_4": ("4a", "4b", "4"), "mode_5a": ("5a",), "mode_1": ("1",)}


def link_by_date(rows, meta):
    """Правило 10: решение без doc ↔ единственный отчёт той же даты с бумагой и режимом строки."""
    n = 0
    for r in rows:
        if r.get("doc"):
            continue
        codes = SET_BY_CODES.get(r["set_by"])
        if not codes:
            continue
        hits = [doc for doc, m in meta.items() if m["date"] == r["date"] and r["key"] in m["tickers"]
                and any(c in m["mode_codes"] for c in codes)]
        if len(hits) == 1:
            r["doc"], r["mode_codes"] = hits[0], list(meta[hits[0]]["mode_codes"])
            r["linked_by_date"] = True
            n += 1
        elif len(hits) > 1:
            r["link_ambiguous"] = hits
    return n


def build_decisions(rows):
    """Решения decision@1 из строк; пометки — в row['flags']."""
    order = {"current": 0, "history": 0, "report": 1}
    rows = sorted(rows, key=lambda r: (r["key"], r["date"], order[r["origin"]], r.get("pos", 99)))
    minute = {}
    out = []
    for r in rows:
        flags = []
        n = minute.get((r["key"], r["date"]), 0)
        minute[(r["key"], r["date"])] = n + 1
        if n:
            flags.append(f"minute T00:{n:02d}")
        now = f"{r['date']}T00:{n:02d}:00+03:00"
        rb, rb_flags = _review_by(r)
        flags += rb_flags
        rb, cl = _clamp(rb, r["date"])
        if cl:
            flags.append(cl)
        if r.get("fallback_for"):
            flags.append(f"вместо текущего статуса {r['fallback_for']}")
        if r.get("archived"):
            flags.append("из архива гейтов")
        if r.get("linked_by_date"):
            flags.append("doc по дате и режиму")
        if r.get("link_ambiguous"):
            flags.append("несколько отчётов той же даты и режима: " + ", ".join(r["link_ambiguous"]))
        source = {"kind": "backfill", "doc": r.get("doc"), "mode_codes": list(r.get("mode_codes") or []),
                  "stress_id": None}
        entry = {"key": r["key"], "verdict": GATE_TO_VERDICT[r["status"]], "target_pct": None, "review_by": rb,
                 "note": _note(r.get("reason"))}
        d = dw._decision(now, entry, source, _author(r["set_by"]), [], [])
        d["recorded_at_estimated"] = True
        r["flags"], r["decision"] = flags, d
        out.append(d)
    return out, rows


def candidates_llm(meta, gates, directives, archived=None):
    """Отчёты kind ∈ LLM_KINDS с бумагами без записи гейта/директивы на ту же дату."""
    covered = {(d["ticker"], d["date"]) for d in directives}
    for key, lst in (archived or {}).items():
        covered.update((key, _s(e.get("date"))) for e in lst)
    for key, rec in gates.items():
        covered.add((key, _s(rec.get("set_date"))))
        for h in rec.get("history") or []:
            covered.add((key, _s(h.get("date"))))
    out = []
    for doc, m in sorted(meta.items()):
        if m["kind"] not in LLM_KINDS or not m["tickers"]:
            continue
        miss = [t for t in m["tickers"] if (t, m["date"]) not in covered]
        if miss:
            out.append({"doc": doc, "kind": m["kind"], "mode_codes": m["mode_codes"], "date": m["date"],
                        "uncovered": miss, "n_tickers": len(m["tickers"])})
    return out


def _md_cell(v):
    return str(v if v not in (None, "") else "—").replace("|", "\\|").replace("\n", " ")


def render_build_report(decisions, rows, without, table, cands, parse_errors, srcs, linked=0):
    by_origin = {}
    for r in rows:
        by_origin[r["origin"]] = by_origin.get(r["origin"], 0) + 1
    enriched = sum(1 for r in rows if r.get("doc") and r["origin"] != "report")
    L = ["# Бэкфилл решений (шаг 9) — отчёт", "",
         f"Источники: гейты `{srcs['gates']}`; отчёты `{srcs['reports']}`; обзоры `{srcs['reviews']}`.", "",
         "## Итог", "",
         f"- Решений записано: **{len(decisions)}** (`source.kind: backfill`, `recorded_at_estimated: true`).",
         f"- Из текущих записей гейта: {by_origin.get('current', 0)}; из строк истории: {by_origin.get('history', 0)}; "
         f"только из директив отчётов/обзоров: {by_origin.get('report', 0)}.",
         f"- Обогащено ссылкой на отчёт/обзор (`source.doc`): {enriched}, из них по дате и режиму без директивы "
         f"(правило 10): {linked}; без doc: {sum(1 for r in rows if not r.get('doc'))}.",
         f"- Бумаг в гейте: {len({r['key'] for r in rows} | {w['key'] for w in without})}; без решения: {len(without)}.",
         "- Смены вердикта в обзорах не читались (правило 8).", ""]
    L += ["## Бумаги без решения", ""]
    L += [f"- {w['key']} (статус {w['status']}): {w['reason']}" for w in without] or ["- нет"]
    L += ["", "## Спорные места (пометки)", "",
          "Пометки: `minute` — вторая запись бумаги за день; `aging` — срок взят из следующей строки авто-истечения;"
          " `clamp` — срок сдвинут к окну 7–180 дней; `default60` — следующей строки нет, + review_days;"
          " `valid_days` — срок из директивы отчёта; «вместо текущего статуса» — решение для бумаги со статусом"
          " без вердикта; «doc по дате и режиму» — правило 10.", "", "| id | вердикт | review_by | происхождение | doc | пометки |", "|---|---|---|---|---|---|"]
    for r in rows:
        if r["flags"] or r["origin"] == "report" or r.get("docs_also"):
            d = r["decision"]
            fl = list(r["flags"]) + ([f"ещё doc: {', '.join(r['docs_also'])}"] if r.get("docs_also") else [])
            L.append(f"| {d['id']} | {d['verdict']} | {d['review_by']} | {r['origin']} | {_md_cell(r.get('doc'))} | "
                     f"{_md_cell('; '.join(fl))} |")
    L += ["", "## Сверка «источник → решение»", "", "| источник | блок | бумага | дата | статус | итог | решение |",
          "|---|---|---|---|---|---|---|"]
    for e in table:
        rid = e["row"]["decision"]["id"] if e.get("row") and e["row"].get("decision") else "—"
        L.append(f"| {_md_cell(e['doc'])} | {e['src']} | {_md_cell(e['key'])} | {_md_cell(e['date'])} | "
                 f"{_md_cell(e['status'])} | {e['result']} | {rid} |")
    if parse_errors:
        L += ["", "## Блоки, которые не разобрались", ""] + [f"- {x}" for x in parse_errors]
    L += ["", "## Кандидаты на извлечение из прозы (`backfill_llm`, не в этом шаге)", "",
          f"Отчёты kind ∈ {{{', '.join(LLM_KINDS)}}} с бумагами без записи гейта/директивы на дату отчёта.", "",
          "| отчёт | kind | коды | бумаг | без записи |", "|---|---|---|---|---|"]
    for c in cands:
        L.append(f"| {c['doc']} | {c['kind']} | {','.join(c['mode_codes']) or '—'} | {c['n_tickers']} | "
                 f"{', '.join(c['uncovered'])} |")
    L += ["", "## Все решения", "", "| id | вердикт | review_by | автор | doc |", "|---|---|---|---|---|"]
    for d in sorted(decisions, key=lambda d: d["id"]):
        L.append(f"| {d['id']} | {d['verdict']} | {d['review_by']} | {d['author']} | {_md_cell(d['source']['doc'])} |")
    return "\n".join(L) + "\n"


def cmd_build(a):
    out = _guard_out(Path(a.out))
    gates_p = Path(a.gates or Path(a.archive) / "Portfolio/gate-reviews.yaml")
    reports_p = Path(a.reports or Path(a.archive) / "Portfolio/reports")
    reviews_p = Path(a.reviews or Path(a.archive) / "Portfolio/weekly-reviews")
    garch_p = Path(a.gates_archive) if a.gates_archive else (
        Path(a.archive) / "Portfolio/gate-reviews-archive-2026.yaml" if a.archive else None)
    gates = load_gates(gates_p)
    archived = load_gates_archive(garch_p)
    rows, without = collect_rows(gates, archived)
    rdirs, meta, perr = load_report_directives(reports_p) if reports_p.is_dir() else ([], {}, [])
    wdirs = load_review_directives(reviews_p) if reviews_p.is_dir() else []
    rows, table = reconcile(rows, rdirs + wdirs)
    linked = link_by_date(rows, meta)
    decisions, rows = build_decisions(rows)
    ddir = out / "Portfolio" / dw.DECISIONS_DIR
    if ddir.is_dir() and any(ddir.iterdir()):
        raise Fail(f"{ddir} не пуст — бэкфилл пишет в чистый временный корень")
    try:
        written = dw._write_all(str(out), decisions)
    except dw.CmdError as e:
        raise Fail(f"{e} {json.dumps(e.extra, ensure_ascii=False)[:2000]}")
    cands = candidates_llm(meta, gates, rdirs, archived)
    rep = render_build_report(decisions, rows, without, table, cands, perr,
                              {"gates": f"{gates_p} + {garch_p}", "reports": reports_p, "reviews": reviews_p},
                              linked)
    (out / "backfill-report.md").write_text(rep, encoding="utf-8")
    origin = {}
    for r in rows:
        origin[r["origin"]] = origin.get(r["origin"], 0) + 1
    return 0, {"ok": True, "written": len(written), "by_origin": origin,
               "enriched": sum(1 for r in rows if r.get("doc") and r["origin"] != "report"), "linked_by_date": linked,
               "no_doc": sum(1 for r in rows if not r.get("doc")),
               "without_decision": without, "directives": len(table),
               "llm_candidates": len(cands), "report": str(out / "backfill-report.md")}


# ----------------------------------------------------------------------------- проверка

def projection(decisions, snapshot_keys, today, is_stock=None, keys=()):
    """Статус гейта по решениям — модулем (б) `last_word.card` (schema.md §3.5), без второй реализации правил.

    Контекст модуля: все решения бэкфилла, ключи снапшота, акции — ключи решений, снапшота и `keys` (записи архива),
    для которых `is_stock(key)` истинно (`is_stock=None` — все); обзоров, справочника бумаг и первых покупок нет —
    review_needed, IPO-пауза и new_position в сравнении не участвуют (флаг обзора не сравнивается, §4.4).
    Возвращает {key: {status, base, review_by, decision_id, in_snapshot}} только для акций: base — проекция вердикта
    новейшего решения (`verdict_to_gate`), review_by — срок модуля (`gate.expires_on`).
    """
    stock = is_stock or (lambda k: True)
    every = {d["key"] for d in decisions} | set(snapshot_keys) | set(keys)
    ctx = {"today": today, "decisions": decisions, "snapshot_keys": sorted(snapshot_keys),
           "stock_keys": sorted(k for k in every if stock(k)), "first_buy": []}
    out = {}
    for c in lw.cards(ctx, ctx["stock_keys"]):
        g = c["gate"]
        out[c["key"]] = {"status": g["status"], "base": VERDICT_TO_GATE.get(c["decision_verdict"]),
                         "review_by": g["expires_on"], "decision_id": c["decision_id"],
                         "in_snapshot": c["key"] in snapshot_keys}
    return out


def snapshot_info(path):
    """(ключи держаний с qty > 0, {ключ: asset_type}, as_of_date)."""
    with open(path, encoding="utf-8") as f:
        snap = json.load(f)
    keys, types = set(), {}
    for h in snap.get("holdings") or []:
        if (h.get("qty") or 0) <= 0:
            continue
        k = h.get("ticker") or h.get("isin")
        keys.add(k)
        types[k] = h.get("asset_type")
    return keys, types, snap.get("as_of_date")


def stock_classifier(types_path, snap_types):
    """is_stock(key) по реестру типов (`type: stock`); нет в реестре — по asset_type снапшота; нет и там — акция."""
    reg = {}
    if types_path:
        with open(types_path, encoding="utf-8") as f:
            reg = (json.load(f) or {}).get("by_ticker") or {}

    def is_stock(k):
        if k in reg:
            return reg[k].get("type") == "stock"
        if k in snap_types:
            return snap_types[k] == "stock"
        return True
    return is_stock


# Итоги сравнения: ok — совпало; stale_archive — архив гейтов не обслуживался после продажи (бумаги нет в
# снапшоте, а в архиве живой статус) — не ошибка бэкфилла; not_tracked — не акция, гейт не ведётся;
# mismatch — бумага в снапшоте и базовый статус не совпал, либо у reviewed_* архива нет решения.
OK, STALE, NOT_TRACKED, MISMATCH = "ok", "stale_archive", "not_tracked", "mismatch"


def compare(gates, proj, is_stock=None):
    stock = is_stock or (lambda k: True)
    rows = []
    for key, rec in gates.items():
        s = _s(rec.get("status"))
        p = proj.get(key) or {"status": None, "base": None, "review_by": None, "decision_id": None,
                              "in_snapshot": None}
        hist_rev = [_s(h.get("status")) for h in rec.get("history") or [] if _s(h.get("status")) in GATE_TO_VERDICT]
        last_rev = hist_rev[-1] if hist_rev else None
        row = {"key": key, "archive": s, "projection": p["status"], "base": p["base"],
               "review_by": p["review_by"], "decision_id": p["decision_id"], "note": ""}
        if not stock(key):
            row.update(result=NOT_TRACKED, note="гейт не ведётся (не акция по реестру типов)")
        elif s in GATE_TO_VERDICT or s in ("review_aging", "review_needed"):
            want = s if s in GATE_TO_VERDICT else last_rev
            if want is None:      # review_needed без единого вердикта в истории — решения быть не должно
                ok = p["decision_id"] is None
                row.update(result=OK if ok else MISMATCH, note="" if ok else "решение есть, а вердикта в истории нет")
            elif p["decision_id"] is None:
                row.update(result=MISMATCH, note=f"нет решения (ожидался базовый {want})")
            elif not p["in_snapshot"]:
                row.update(result=STALE, note="архив гейтов не обслуживался после продажи: бумаги нет в снапшоте")
            elif p["base"] != want:
                row.update(result=MISMATCH, note=f"базовый статус {p['base']}, ожидался {want}")
            else:
                note = ""
                if s == "review_aging" and p["status"] != "review_aging":
                    note = f"в архиве истёк срок, в проекции срок {p['review_by']} ещё идёт"
                elif s in GATE_TO_VERDICT and p["status"] != s:
                    note = f"базовый совпал; в проекции {p['status']} (срок {p['review_by']})"
                elif s == "review_needed":
                    note = "флаг обзора не сравнивается"
                row.update(result=OK, note=note)
        elif s == "divested":
            ok = p["status"] == "divested"
            row.update(result=OK if ok else MISMATCH, note="" if ok else "в архиве продана, а бумага есть в снапшоте")
        elif s == "new_position":
            ok = p["decision_id"] is None
            row.update(result=OK if ok else MISMATCH, note="" if ok else "в архиве новая, а решение есть")
        else:
            row.update(result=MISMATCH, note=f"неизвестный статус архива {s!r}")
        rows.append(row)
    return rows


def load_decisions(out):
    items, invalid = [], []
    for path in sorted(glob.glob(os.path.join(str(out), "Portfolio", dw.DECISIONS_DIR, "*.json"))):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        errs = ds.validate_decision(d)
        (invalid.append({"file": os.path.basename(path), "errors": errs}) if errs else items.append(d))
    return items, invalid


RESULT_RU = {OK: "да", STALE: "устаревшая запись архива", NOT_TRACKED: "гейт не ведётся", MISMATCH: "РАСХОЖДЕНИЕ"}


def cmd_verify(a):
    if not ds.is_date(a.today):
        raise Fail(f"--today: ожидается ГГГГ-ММ-ДД, получено {a.today!r}")
    out = Path(a.out)
    decisions, invalid = load_decisions(out)
    gates = load_gates(a.gates)
    keys, snap_types, as_of = snapshot_info(a.snapshot)
    is_stock = stock_classifier(a.types, snap_types)
    rows = compare(gates, projection(decisions, keys, a.today, is_stock, gates.keys()), is_stock)
    cnt = {k: sum(r["result"] == k for r in rows) for k in RESULT_RU}
    L = ["# Проверка воспроизводимости гейта (шаг 9)", "",
         f"Решений: {len(decisions)} (невалидных файлов: {len(invalid)}); снапшот `{a.snapshot}` (as_of {as_of}); "
         f"сегодня {a.today}; гейт — только акции по реестру типов `{a.types or '— (asset_type снапшота)'}`.", "",
         f"**Итог: совпало {cnt[OK]} / устаревших записей архива {cnt[STALE]} / расхождений {cnt[MISMATCH]}** "
         f"(гейт не ведётся: {cnt[NOT_TRACKED]}; всего записей архива {len(rows)}).", "",
         "| бумага | архив | проекция | базовый | review_by | решение | итог | пояснение |",
         "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['key']} | {r['archive']} | {_md_cell(r['projection'])} | {_md_cell(r['base'])} | "
                 f"{_md_cell(r['review_by'])} | {_md_cell(r['decision_id'])} | {RESULT_RU[r['result']]} | "
                 f"{_md_cell(r['note'])} |")
    for x in invalid:
        L.append(f"\n- невалидный файл {x['file']}: {'; '.join(x['errors'])}")
    text = "\n".join(L) + "\n"
    (out / "verify-report.md").write_text(text, encoding="utf-8")
    print(text)
    return (0 if cnt[MISMATCH] == 0 and not invalid else 1), None


# ----------------------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(description="Бэкфилл решений decision@1 из архива гейта (шаг 9)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--archive", help="папка архива шага 1 (…/_archive/data-structures/<…>-step1)")
    b.add_argument("--gates")
    b.add_argument("--gates-archive", dest="gates_archive")
    b.add_argument("--reports")
    b.add_argument("--reviews")
    b.add_argument("--out", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--out", required=True)
    v.add_argument("--gates", required=True)
    v.add_argument("--snapshot", required=True)
    v.add_argument("--today", required=True)
    v.add_argument("--types", default=None,
                   help="Portfolio/security-types.json: гейт только у type: stock (без него — asset_type снапшота)")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "build":
            if not a.archive and not a.gates:
                raise Fail("build: нужен --archive или --gates")
            code, res = cmd_build(a)
        else:
            code, res = cmd_verify(a)
    except Fail as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False, indent=2))
        return 1
    if res is not None:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
