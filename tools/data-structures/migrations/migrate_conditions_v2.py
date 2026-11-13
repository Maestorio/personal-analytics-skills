#!/usr/bin/env python3
"""Миграция conditions@1.2 -> conditions@2 (определения) + conditions-state@1 (события).

Схема: docs/investment/_cross-cutting/data-structures/schema.md §3.2–§3.3 и §5 (строка про conditions.yaml).
Исходный файл не изменяется. Ничего не пишет в Claude-Memory (защита по пути, см. --allow-memory).

CLI:
  python3 migrate_conditions_v2.py --in conditions.yaml [--out <папка>] [--decisions <папка decisions/>]
  Без --out — сухой прогон: отчёт в stdout. С --out пишет conditions.yaml (v2), conditions-state.json,
  migration-report.md. В конце скрипт сам валидирует результат (ds_schemas) и печатает итог;
  код выхода 1, если результат не прошёл валидацию.

Правила (кратко; полный текст — в задании шага и в отчёте миграции):
  ticker -> key (вид ключа и класс бумаги не пишутся — считаются при чтении); created -> created_at = дата + T00:00:00+03:00 (time_estimated; начало дня — раньше любой живой записи того же дня);
  created_by -> actor (синоним user -> owner; неизвестные -> script); on_trigger.action (проза) -> text,
  код действия: kind == review или set_status == review_needed -> run_analysis, иначе target_pct ->
  set_target_pct, иначе verdict -> set_verdict, иначе notify_only; состояние и history -> события.
  Касание порога (touched{} и price_touched/touched истории) = событие fired (не дублируется).
  Условие 1.2 с непустым event и триггером date -> trigger report_published (value = текст event,
  window_end = прежняя дата + DEFAULTS["report_window_days"] (3) дня), converted_from_date: true; если valid_until
  раньше нового window_end, valid_until поднимается до window_end (таких случаев — отдельная строка отчёта);
  таблица таких условий (прежняя дата и новый window_end) — в отчёте.
  Связь «условие <-> решение» (R23, только с --decisions): в формате 1.2 отдельного поля источника нет — отчёт-источник
  записан путём `Portfolio/reports/<имя>.md` (или `reports/<имя>.md`) в заметке строки истории. Заметка строки
  `created` -> у определения source = {kind: report, doc: <отчёт>, decision_id}; заметка строки `closed_manual`
  (событие done by: owner) -> data.decision_id. Связь ставится только при ровно одном решении той же бумаги с
  source.doc == отчёт; нет пути, нет решения или решений несколько — строка в отчёте миграции (кандидаты по дате
  показываются, но не применяются). Функция чистая: повторный прогон даёт тот же результат.
"""

import argparse
import json
import os
import re
import sys
from datetime import date, timedelta
from collections import Counter, OrderedDict

# валидаторы целевой схемы — общий модуль `_shared-references/ds_schemas.py` (его же импортирует apply_condition.py)
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..",
                                                 "_shared-references")))
import ds_schemas  # noqa: E402

DAY_START = "T00:00:00+03:00"   # оценённое время: раньше любой живой записи того же дня
ACTOR_ALIASES = {"user": "owner"}
TRADE_VERDICTS = ("BUY", "SELL", "TRIM", "ADD")
KNOWN_TOP = {"id", "ticker", "created", "created_by", "trigger", "while_pending", "on_trigger", "state",
             "fired_date", "history", "kind", "event", "not_before", "valid_until", "on_expiry",
             "context", "touched"}
TOUCH_BY = {"notifier": "notifier", "site": "site", "review": "script"}
REPORT_RX = re.compile(r"(?:Portfolio/)?reports/([A-Za-z0-9._\-]+\.md)")


def report_docs(text):
    """Пути отчётов в тексте заметки, нормализованные к виду source.doc решения (`Portfolio/reports/<имя>.md`)."""
    return sorted({"Portfolio/reports/" + m for m in REPORT_RX.findall(text or "")})


def load_decisions(folder):
    """Папка decisions/ -> список решений decision@1 (id, key, doc, дата). Нечитаемые файлы пропускаются."""
    out, skipped = [], []
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            skipped.append(name)
            continue
        if d.get("schema_version") != "decision@1" or not d.get("id") or not d.get("key"):
            skipped.append(name)
            continue
        out.append({"id": d["id"], "key": d["key"], "doc": (d.get("source") or {}).get("doc"),
                    "date": str(d.get("recorded_at") or "")[:10]})
    return out, skipped


class DecisionIndex:
    """Индекс решений по (бумага, отчёт) и (бумага, дата) — для однозначного сопоставления."""

    def __init__(self, decisions):
        self.by_doc, self.by_date = {}, {}
        for d in decisions:
            if d["doc"]:
                self.by_doc.setdefault((d["key"], d["doc"]), []).append(d["id"])
            self.by_date.setdefault((d["key"], d["date"]), []).append(d["id"])

    def match(self, key, note):
        """(decision_id | None, причина | None, отчёты из заметки)."""
        docs = report_docs(note)
        if not docs:
            return None, "в заметке нет пути отчёта", docs
        ids = sorted({i for doc in docs for i in self.by_doc.get((key, doc), [])})
        if len(ids) == 1:
            return ids[0], None, docs
        if not ids:
            return None, "нет решения этой бумаги с таким отчётом", docs
        return None, f"неоднозначно: {len(ids)} решений ({', '.join(ids)})", docs

    def candidates(self, key, day):
        return sorted(self.by_date.get((key, day), []))


def _s(v):
    """Даты/числа из YAML -> строки дат; прочее без изменений."""
    if hasattr(v, "isoformat") and not isinstance(v, str):
        return v.isoformat()[:10]
    return v


def derive_kind(cond):
    """Вид условия: явный `kind`, иначе по on_trigger.verdict (derive_kind из apply_condition.py)."""
    if cond.get("kind"):
        return cond["kind"], False
    verdict = (cond.get("on_trigger") or {}).get("verdict")
    return ("trade" if verdict in TRADE_VERDICTS else "review"), True


def action_code(kind, set_status, verdict, target_pct, top=True):
    """Код действия по правилам миграции. top=False — ветки/otherwise: исход разбора, не сам разбор."""
    if top and (kind == "review" or set_status == "review_needed"):
        return "run_analysis"
    if target_pct is not None:
        return "set_target_pct"
    if verdict:
        return "set_verdict"
    return "notify_only"


def _num(v):
    if isinstance(v, str):
        try:
            f = float(v.replace(",", "."))
            return int(f) if f == int(f) else f
        except ValueError:
            return v
    return v


def _join(action, note):
    parts = [p for p in (action, note) if p]
    return " — ".join(parts)


class _Ctx:
    """Накопитель отчёта."""

    def __init__(self):
        self.dropped = Counter()
        self.out_of_lists = []   # (id, путь, значение, перечень)
        self.notes = []          # информационные строки
        self.warnings = {}       # id -> [строки]
        self.unmapped = []       # (id, дата, событие)
        self.converted = []      # (id, key, event, прежняя дата, новый window_end) — date -> report_published
        self.valid_until_raised = []  # (id, прежний valid_until, новый)
        self.dec_index = None    # DecisionIndex при --decisions
        self.links = []          # (id, что, decision_id | None, причина | None, отчёты, кандидаты по дате)

    def link(self, cid, what, key, note, day):
        """Сопоставить заметку с решением; записать строку отчёта; вернуть (decision_id, отчёт) или (None, None)."""
        did, why, docs = self.dec_index.match(key, note)
        cands = [] if did else self.dec_index.candidates(key, day)
        self.links.append((cid, what, did, why, docs, cands))
        doc = next((d for d in docs if did in self.dec_index.by_doc.get((key, d), [])), None) if did else None
        return did, doc

    def warn(self, cid, text):
        self.warnings.setdefault(cid, []).append(text)

    def check_code(self, cid, path, value, codelist, allow_null=True):
        if value is None and allow_null:
            return
        if value not in ds_schemas.CODELISTS[codelist]:
            self.out_of_lists.append((cid, path, value, codelist))


def _migrate_outcome(ctx, cid, path, o, kind, set_status, top):
    """on_trigger / ветка then / otherwise / on_expiry -> исход v2."""
    verdict = o.get("verdict")
    target = o.get("target_pct")
    ctx.check_code(cid, path + ".verdict", verdict, "verdict")
    out = OrderedDict()
    out["action"] = action_code(kind, set_status, verdict, target, top=top)
    out["verdict"] = verdict
    if target is not None:
        out["target_pct"] = _num(target)
    out["text"] = _join(o.get("action"), None if top else o.get("note"))
    return out


def _check_unknown(ctx, cid, obj, known, path):
    for k in obj:
        if k not in known:
            ctx.dropped[f"{path}.{k} (неизвестное поле)"] += 1
            ctx.warn(cid, f"отброшено неизвестное поле {path}.{k}")


def migrate_condition(c, ctx):
    """Одно условие 1.2 -> (определение v2, список событий, служебные данные для отчёта)."""
    cid = c["id"]
    _check_unknown(ctx, cid, c, KNOWN_TOP, "условие")

    # --- ключ
    key = c["ticker"]

    # --- время создания
    created = _s(c.get("created"))
    if not created:
        hist_dates = [_s(h.get("date")) for h in (c.get("history") or []) if h.get("date")]
        created = hist_dates[0] if hist_dates else None
        ctx.warn(cid, "нет created — взята первая дата истории" if created else "нет created и истории")
    created_at = (created + DAY_START) if created else None

    # --- автор
    cb = c.get("created_by")
    if cb in ACTOR_ALIASES:
        ctx.notes.append(f"{cid}: created_by {cb!r} -> {ACTOR_ALIASES[cb]!r} (синоним)")
        cb = ACTOR_ALIASES[cb]
    if cb not in ds_schemas.CODELISTS["actor"]:
        ctx.notes.append(f"{cid}: created_by {cb!r} неизвестен -> 'script'")
        ctx.out_of_lists.append((cid, "created_by", cb, "actor"))
        cb = "script"

    # --- вид, триггер
    kind, kind_derived = derive_kind(c)
    if kind_derived:
        ctx.dropped["(выведено) kind отсутствовал — выведен из on_trigger.verdict"] += 1
    ctx.check_code(cid, "kind", kind, "condition_kind", allow_null=False)
    tr = c.get("trigger") or {}
    ctx.check_code(cid, "trigger.type", tr.get("type"), "condition_trigger_type", allow_null=False)
    _check_unknown(ctx, cid, tr, {"type", "value"}, "trigger")
    value = _s(tr.get("value"))
    if tr.get("type") in ("price_below", "price_above"):
        value = _num(value)
    trigger = OrderedDict([("type", tr.get("type")), ("value", value)])
    converted = False
    if tr.get("type") == "date" and isinstance(c.get("event"), str) and c["event"].strip():
        old_date = value
        window_end = old_date
        if ds_schemas.is_date(old_date):
            window_end = (date.fromisoformat(old_date)
                          + timedelta(days=ds_schemas.DEFAULTS["report_window_days"])).isoformat()
        trigger = OrderedDict([("type", "report_published"), ("value", c["event"]), ("window_end", window_end)])
        converted = True
        ctx.converted.append((cid, key, c["event"], old_date, window_end))

    # --- while_pending, on_trigger
    wp = c.get("while_pending") or {}
    _check_unknown(ctx, cid, wp, {"verdict", "note"}, "while_pending")
    ctx.check_code(cid, "while_pending.verdict", wp.get("verdict"), "verdict", allow_null=False)
    while_pending = OrderedDict([("verdict", wp.get("verdict")), ("text", wp.get("note") or "")])

    ot = c.get("on_trigger") or {}
    _check_unknown(ctx, cid, ot, {"action", "set_status", "verdict", "target_pct", "branches", "otherwise"}, "on_trigger")
    set_status = ot.get("set_status")
    if set_status is not None:
        ctx.dropped[f"on_trigger.set_status (значение {set_status})"] += 1
    on_trigger = _migrate_outcome(ctx, cid, "on_trigger", ot, kind, set_status, top=True)

    branches = None
    if ot.get("branches"):
        branches = []
        for i, b in enumerate(ot["branches"]):
            _check_unknown(ctx, cid, b, {"if", "then"}, "branches[]")
            th = b.get("then") or {}
            _check_unknown(ctx, cid, th, {"verdict", "action", "target_pct", "note"}, "branches[].then")
            branches.append(OrderedDict([
                ("if_text", b.get("if")),
                ("then", _migrate_outcome(ctx, cid, f"branches[{i}].then", th, kind, None, top=False)),
            ]))
    otherwise = None
    if ot.get("otherwise"):
        _check_unknown(ctx, cid, ot["otherwise"], {"verdict", "action", "target_pct", "note"}, "otherwise")
        otherwise = _migrate_outcome(ctx, cid, "otherwise", ot["otherwise"], kind, None, top=False)

    d = OrderedDict()
    d["id"] = cid
    d["version"] = 1
    d["key"] = key
    d["kind"] = kind
    d["trigger"] = trigger
    if converted:
        d["converted_from_date"] = True
    if c.get("event"):
        d["event_text"] = c["event"]
    d["while_pending"] = while_pending
    if branches:
        on_trigger["branches"] = branches
    if otherwise:
        on_trigger["otherwise"] = otherwise
    d["on_trigger"] = on_trigger
    if c.get("not_before"):
        d["not_before"] = _s(c["not_before"])
    if c.get("valid_until"):
        d["valid_until"] = _s(c["valid_until"])
    if converted and ds_schemas.is_date(d.get("valid_until")) and ds_schemas.is_date(trigger["window_end"]) \
            and d["valid_until"] < trigger["window_end"]:
        ctx.valid_until_raised.append((cid, d["valid_until"], trigger["window_end"]))
        d["valid_until"] = trigger["window_end"]
    oe = c.get("on_expiry")
    if oe:
        _check_unknown(ctx, cid, oe, {"action", "verdict", "set_status"}, "on_expiry")
        if oe.get("set_status") is not None:
            ctx.dropped[f"on_expiry.set_status (значение {oe['set_status']})"] += 1
        d["on_expiry"] = _migrate_outcome(ctx, cid, "on_expiry", oe, kind, oe.get("set_status"), top=True)
    if c.get("context"):
        cx = c["context"]
        _check_unknown(ctx, cid, cx, {"plan_pct", "snapshot"}, "context")
        d["context"] = OrderedDict([("plan_pct", cx.get("plan_pct")), ("snapshot_id", cx.get("snapshot")),
                                    ("as_of", created_at)])
    d["source"] = OrderedDict([("kind", "migration"), ("doc", None)])
    if ctx.dec_index is not None:
        hc = next((h for h in (c.get("history") or []) if h.get("event") == "created"), None)
        if hc is not None:
            did, doc = ctx.link(cid, "определение (created)", key, hc.get("note"), _s(hc.get("date")) or created)
            if did:
                d["source"] = OrderedDict([("kind", "report"), ("doc", doc), ("decision_id", did)])
    d["created_at"] = created_at
    d["time_estimated"] = True
    d["created_by"] = cb
    d["withdrawn"] = None
    d["superseded_by"] = None

    # --- события
    events = []

    def add(event, at, by, data=None, estimated=False):
        e = OrderedDict([("condition_id", cid), ("version", 1), ("event", event), ("at", at), ("by", by)])
        if estimated:
            e["time_estimated"] = True
        e["data"] = data or {}
        events.append(e)

    hist = c.get("history") or []
    hist_norm = []
    for h in hist:
        hn = dict(h)
        hn["date"] = _s(h.get("date")) or created
        hist_norm.append(hn)

    # --- сработавшее: одно событие fired. Приоритет источников: touched{} (точное время) >
    #     state=fired + fired_date > первая строка истории fired/price_touched/touched.
    th = c.get("touched")
    state = c.get("state")
    fired_date = _s(c.get("fired_date"))
    if th:
        _check_unknown(ctx, cid, th, {"date", "time", "price", "source"}, "touched")
        tdate = _s(th.get("date")) or created
        has_time = bool(th.get("time"))
        at = tdate + (f"T{th['time']}:00+03:00" if has_time else DAY_START)
        src = th.get("source")
        add("fired", at, TOUCH_BY.get(src, "script"),
            {k: v for k, v in (("price", th.get("price")), ("source", src)) if v is not None},
            estimated=not has_time)
    elif state == "fired":
        if not fired_date:
            for h in hist_norm:
                if h.get("event") in ("closed_manual", "closed", "fired"):
                    fired_date = h["date"]
                    break
            fired_date = fired_date or created
            ctx.warn(cid, f"state=fired без fired_date — дата взята ({fired_date}) из истории/создания")
        add("fired", fired_date + DAY_START, "script", estimated=True)
    elif state not in (None, "pending"):
        ctx.out_of_lists.append((cid, "state", state, "состояния 1.2 (pending|fired)"))
        ctx.warn(cid, f"неизвестный state {state!r} — событий не создано")
    elif fired_date:
        ctx.warn(cid, f"fired_date={fired_date} при state={state} — отброшено")
        ctx.dropped["fired_date при state=pending"] += 1

    lost = Counter()
    for h in hist_norm:
        ev, date_ = h.get("event"), h["date"]
        note = h.get("note")
        hat = date_ + (f"T{h['time']}:00+03:00" if h.get("time") else DAY_START)
        est = not h.get("time")
        if ev in ("fired", "price_touched", "touched"):
            if any(e["event"] == "fired" for e in events):
                continue  # дубль: условие срабатывает один раз
            data = {"note": note} if note else {}
            if h.get("price") is not None:
                data["price"] = h["price"]
            add("fired", hat, "script", data, estimated=est)
        elif ev in ("closed_manual", "closed"):
            fired_ev = next((e for e in events if e["event"] == "fired"), None)
            if fired_ev and hat < fired_ev["at"]:
                hat, est = fired_ev["at"], True   # done не раньше fired
            data = {"note": note or f"закрыто ({ev}, перенос из истории 1.2)"}
            if ev == "closed_manual" and ctx.dec_index is not None:
                did, _doc = ctx.link(cid, f"done by owner ({date_})", key, note, date_)
                if did:
                    data["decision_id"] = did
            add("done", hat, "owner" if ev == "closed_manual" else "script", data, estimated=est)
        elif ev == "reopened":
            add("reopened", hat, "owner", {"note": note} if note else {}, estimated=est)
        elif ev in ("created", "edited"):
            lost[ev] += 1
            ctx.dropped[f"history[event={ev}]"] += 1
            if h.get("changes"):
                ctx.dropped["history[].changes"] += 1
        else:
            lost["не отображено"] += 1
            ctx.unmapped.append((cid, date_, ev))
            ctx.dropped[f"history[event={ev}] (не отображено)"] += 1
            ctx.warn(cid, f"событие истории {ev!r} от {date_} не отображено")
    return d, events, lost


def migrate(doc, decisions=None):
    """conditions@1.2 (dict) -> (defs_doc, state_doc, ctx, rows). Чистая функция.

    decisions — список решений из load_decisions (или None: связь «условие <-> решение» не восстанавливается)."""
    ctx = _Ctx()
    if decisions is not None:
        ctx.dec_index = DecisionIndex(decisions)
    if doc.get("schema_version") != "conditions@1.2":
        ctx.notes.append(f"schema_version исходника {doc.get('schema_version')!r} (ожидалось conditions@1.2)")
    defs, events, rows = [], [], []
    for c in doc.get("conditions") or []:
        d, evs, lost = migrate_condition(c, ctx)
        defs.append(d)
        events.extend(evs)
        rows.append({
            "id": d["id"], "key": d["key"], "kind": d["kind"], "trigger_type": d["trigger"]["type"],
            "action": d["on_trigger"]["action"], "events": len(evs),
            "lost": sum(lost.values()), "lost_detail": dict(lost),
            "warnings": list(ctx.warnings.get(d["id"], [])),
        })
    # устойчиво: порядок внутри условия сохраняется; при равном времени reopened раньше остальных
    events.sort(key=lambda e: (e["at"], 0 if e["event"] == "reopened" else 1))
    defs_doc = OrderedDict([("schema_version", "conditions@2"), ("conditions", defs)])
    state_doc = OrderedDict([("schema_version", "conditions-state@1"), ("events", events)])
    return defs_doc, state_doc, ctx, rows


def render_report(src_name, defs_doc, state_doc, ctx, rows, validation):
    """migration-report.md (без реальных значений: только счётчики и идентификаторы)."""
    L = []
    n_events = len(state_doc["events"])
    lost_total = sum(r["lost"] for r in rows)
    L.append("# Отчёт миграции conditions 1.2 -> conditions@2 + conditions-state@1\n")
    L.append(f"Источник: `{src_name}`. Условий: **{len(rows)}**. Событий состояния: **{n_events}**. "
             f"Потеряно строк истории: **{lost_total}**.\n")
    L.append("## Условия\n")
    L.append("| id | key | kind | trigger.type | action | событий | потеряно строк | предупреждения |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in rows:
        det = ", ".join(f"{k}: {v}" for k, v in r["lost_detail"].items())
        L.append(f"| {r['id']} | {r['key']} | {r['kind']} | {r['trigger_type']} | {r['action']} | "
                 f"{r['events']} | {r['lost']}" + (f" ({det})" if det else "") + f" | {'; '.join(r['warnings']) or '-'} |")
    L.append("\n## Сводка\n")
    L.append("- action-коды: " + ", ".join(f"{k} {v}" for k, v in sorted(Counter(r["action"] for r in rows).items())))
    L.append(f"- trigger.type после миграции: " + ", ".join(f"{k} {v}" for k, v in sorted(Counter(r["trigger_type"] for r in rows).items())))
    L.append(f"- конвертировано date -> report_published: {len(ctx.converted)}")
    L.append("- kind: " + ", ".join(f"{k} {v}" for k, v in sorted(Counter(r["kind"] for r in rows).items())))
    L.append(f"- поднят valid_until до нового window_end: {len(ctx.valid_until_raised)}")
    L.append("- события по типам: " + (", ".join(f"{k} {v}" for k, v in sorted(Counter(e["event"] for e in state_doc["events"]).items())) or "нет"))
    L.append("\n## Условия date -> report_published (проверить владельцем)\n")
    if ctx.converted:
        L.append("| id | key | event | прежняя дата | новый window_end |")
        L.append("|---|---|---|---|---|")
        for cid, key, event, old, we in ctx.converted:
            L.append(f"| {cid} | {key} | {event} | {old} | {we} |")
        if ctx.valid_until_raised:
            L.append("\nvalid_until поднят до нового window_end (окно не должно выходить за срок действия):\n")
            for cid, old, new in ctx.valid_until_raised:
                L.append(f"- {cid}: valid_until {old} -> {new}")
    else:
        L.append("- нет")
    L.append("\n## Отброшенные поля и потери (счётчики)\n")
    if ctx.dropped:
        for k, v in sorted(ctx.dropped.items()):
            L.append(f"- {k}: {v}")
    else:
        L.append("- нет")
    L.append("\n## Значения вне перечней\n")
    if ctx.out_of_lists:
        for cid, path, val, lst in ctx.out_of_lists:
            L.append(f"- {cid}: {path} = {val!r} (перечень {lst})")
    else:
        L.append("- нет")
    L.append("\n## События истории, не отображённые в состоянии\n")
    if ctx.unmapped:
        for cid, d, ev in ctx.unmapped:
            L.append(f"- {cid}: {ev} от {d} — не отображено")
    else:
        L.append("- нет")
    if ctx.dec_index is not None:
        ok = [x for x in ctx.links if x[2]]
        L.append("\n## Связь «условие <-> решение» (R23, --decisions)\n")
        L.append(f"Сопоставлено: **{len(ok)}** из {len(ctx.links)} "
                 f"(определений {sum(1 for x in ok if x[1].startswith('определение'))}, "
                 f"событий done by owner {sum(1 for x in ok if x[1].startswith('done'))}). "
                 "Связь ставится только при ровно одном решении той же бумаги с этим отчётом.\n")
        if ctx.links:
            L.append("| id | что | решение | причина, если нет | отчёты в заметке | кандидаты по дате (не применены) |")
            L.append("|---|---|---|---|---|---|")
            for cid, what, did, why, docs, cands in ctx.links:
                L.append(f"| {cid} | {what} | {did or '-'} | {why or '-'} | {', '.join(docs) or '-'} | "
                         f"{', '.join(cands) or '-'} |")
    L.append("\n## Примечания\n")
    L.extend([f"- {n}" for n in ctx.notes] or ["- нет"])
    L.append("\n## Валидация результата\n")
    L.extend([f"- {v}" for v in validation])
    return "\n".join(L) + "\n"


def validate_result(defs_doc, state_doc):
    """Валидация ds_schemas + перекрёстные ссылки; возвращает (ошибки, строки итога)."""
    e1 = ds_schemas.validate_conditions_file(defs_doc)
    e2 = ds_schemas.validate_conditions_state(state_doc)
    e3 = ds_schemas.validate_state_refs(state_doc, defs_doc)
    lines = [f"validate_conditions_file: {'OK' if not e1 else f'{len(e1)} ошибок'}",
             f"validate_conditions_state: {'OK' if not e2 else f'{len(e2)} ошибок'}",
             f"ссылки событий на определения: {'OK' if not e3 else f'{len(e3)} ошибок'}"]
    lines += [f"ОШИБКА {e}" for e in e1 + e2 + e3]
    return e1 + e2 + e3, lines


def _dump_yaml(obj):
    import yaml

    def plain(o):
        if isinstance(o, dict):
            return {k: plain(v) for k, v in o.items()}
        if isinstance(o, list):
            return [plain(v) for v in o]
        return o

    return yaml.safe_dump(plain(obj), allow_unicode=True, sort_keys=False, width=1000, default_flow_style=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Миграция conditions@1.2 -> conditions@2 + conditions-state@1")
    ap.add_argument("--in", dest="src", required=True, help="conditions.yaml (1.2)")
    ap.add_argument("--out", help="папка результата; без неё — сухой прогон (отчёт в stdout)")
    ap.add_argument("--allow-memory", action="store_true", help="разрешить --out внутри Claude-Memory")
    ap.add_argument("--decisions", dest="decisions_dir", help="папка decisions/ (decision@1): восстановить связь условие <-> решение (R23)")
    a = ap.parse_args(argv)

    if a.out and "Claude-Memory" in os.path.abspath(a.out) and not a.allow_memory:
        print("--out внутри Claude-Memory запрещён без --allow-memory", file=sys.stderr)
        return 2
    doc = ds_schemas.load_yaml(a.src)
    decisions = None
    if a.decisions_dir:
        decisions, skipped = load_decisions(a.decisions_dir)
        if skipped:
            print(f"пропущено нечитаемых/не decision@1 файлов решений: {len(skipped)}", file=sys.stderr)
    defs_doc, state_doc, ctx, rows = migrate(doc, decisions)
    errors, vlines = validate_result(defs_doc, state_doc)
    report = render_report(os.path.basename(a.src), defs_doc, state_doc, ctx, rows, vlines)

    if a.out:
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, "conditions.yaml"), "w", encoding="utf-8") as f:
            f.write(_dump_yaml(defs_doc))
        with open(os.path.join(a.out, "conditions-state.json"), "w", encoding="utf-8") as f:
            json.dump(state_doc, f, ensure_ascii=False, indent=2)
            f.write("\n")
        with open(os.path.join(a.out, "migration-report.md"), "w", encoding="utf-8") as f:
            f.write(report)
        print(f"Записано в {a.out}: conditions.yaml, conditions-state.json, migration-report.md")
    else:
        print(report)
    print(f"ИТОГ: условий {len(rows)}, событий {len(state_doc['events'])}, "
          f"потеряно строк истории {sum(r['lost'] for r in rows)}, "
          f"валидация {'пройдена' if not errors else 'НЕ пройдена (' + str(len(errors)) + ' ошибок)'}")
    if ctx.dec_index is not None:
        defs_l = [x for x in ctx.links if x[1].startswith("определение")]
        done_l = [x for x in ctx.links if x[1].startswith("done")]
        print(f"СВЯЗЬ С РЕШЕНИЯМИ: определений {sum(1 for x in defs_l if x[2])} из {len(defs_l)}, "
              f"событий done by owner {sum(1 for x in done_l if x[2])} из {len(done_l)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
