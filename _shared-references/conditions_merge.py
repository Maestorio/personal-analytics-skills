#!/usr/bin/env python3
"""Модуль (а) схемы данных: объединение «определение условия + состояние условия» (schema.md §1 п.3, §3.3).

Чистые функции без ввода-вывода: merge / select / orphan_event_ids / key_kind. I/O — только load_yaml и CLI внизу.
JS-близнец — `tools/assets/conditions-merge.js` (`window.CM`): та же выдача поле в поле и в том же порядке;
паритет держит `tools/tests/test_conditions_merge_parity.py`, он же сверяет текст правил ниже с шапкой JS.
Любое изменение правил — здесь и в шапке JS одновременно, иначе сторож красный.

Коды событий, отметок и типов триггера — из кодлистов (`codelists.py`, `condition_event`, `owner_mark`,
`condition_trigger_type`): модуль берёт их оттуда при загрузке и падает, если нужного кода нет; набор
обрабатываемых событий и отметок обязан совпадать с кодлистом (сторож в тесте паритета). Статусы выдачи
(pending, fired, expired, done, withdrawn) — словарь модуля, не кодлист. Время — через `time_msk.py`.
В репозитории модуль лежит в `_shared-references/`, в упакованном скилле — в `scripts/` (pack.sh кладёт его рядом
со скриптом, который делает `import conditions_merge`, вместе с codelists.py/.json и time_msk.py).

ПРАВИЛА (спецификация для JS)
 1. Время сравнивается как строка: везде формат YYYY-MM-DDTHH:MM:SS+03:00 (один пояс), даты —
    YYYY-MM-DD; лексикографический порядок = хронологический.
 2. Для каждого id берётся определение с наибольшим `version` («последняя версия»). Остальные версии
    в результат не попадают. При равной `version` остаётся первое по порядку в файле.
 3. События состояния по id берутся любой версии, сортируются по (`at`, порядок в файле) — устойчиво.
    Поле `version` события необязательно и модулем не читается (связь только по condition_id).
 4. Событие `reopened` (пишет сайт по кнопке владельца) сбрасывает всё: статус и отметки считаются
    только по событиям ПОСЛЕ последнего `reopened`; событий после него нет -> pending.
    Само `reopened` остаётся последним реальным событием (last_event), если после него ничего нет.
 5. Статус из событий (после правила 4) проходом по порядку, начиная с `pending`:
      fired        : pending -> fired (fired_at = первое fired). Пересечение ценового порога пишет
                     уведомитель как fired; находку монитора (event_found) задача на NAS переносит двумя
                     событиями: event_found и fired (с data.doc).
      expired      : pending -> expired (после fired/done игнорируется).
      done         : pending|fired -> done (после expired остаётся expired). done пишет сайт (кнопка
                     «сделал», by=owner; отдельной отметки «сделал» в owner_mark нет), либо задача на NAS:
                     новое решение в decisions/ с conditions_resolved[], содержащим id условия в статусе
                     fired -> done с data.decision_id; либо сделка (data.trade_date).
      owner_mark   : data.mark = dismissed («не актуально») -> как done, closed_as = dismissed;
                     deferred («отложить») -> при status fired запоминает until; статус остаётся fired.
      event_found  : даёт found_at и found_doc (data.doc), попадает в last_event; статус меняет только
                     отметка владельца (by = owner, кнопка «вышел» на сайте): pending -> fired, fired_at = её at;
                     от остальных авторов статус НЕ меняет (их находку переносят отдельным fired).
    Отсрочка (deferred) учитывается, если это последняя отметка deferred после первого fired
    (для вычисленного по сроку fired — любая отметка); deferred_until = её data.until.
 6. Вычисление при чтении (`today` — дата YYYY-MM-DD). Только если статус из событий pending:
      а) trigger.type == report_published и trigger.window_end < today (окно включает последний день) ->
         status = fired, fired_by_deadline = true, fired_at = window_end + "T23:59:59+03:00" (решение владельца);
      б) trigger.type == date и trigger.value <= today (дата срабатывает В ДЕНЬ события, как у notifier.py)
         -> fired, fired_by_deadline = true, fired_at = value + "T00:00:00+03:00";
      в) иначе, если valid_until < today -> status = expired (для price_* дедлайна нет, только это правило).
    Вычисленный статус помечается computed = true; last_event остаётся последним РЕАЛЬНЫМ событием.
    fired/expired/done из событий дедлайнами не перекрываются.
    ОГОВОРКА: событие fired от уведомителя первично; вычисление по сроку при чтении — страховка на случай,
    когда проход уведомителя ещё не записал событие. Расхождение fired_at между вычисленным и записанным
    допустимо; вычисленное помечено computed = true и исчезает, как только событие записано.
 7. state_status = статус по правилам 4–6 (до учёта снятия определения).
 8. Снятие: если последняя версия определения имеет withdrawn != null -> status = "withdrawn",
    withdrawn_at = withdrawn.at; state_status сохраняет живое состояние («снято, было fired»).
 9. active = определение не снято И status in {pending, fired}.
    waits_owner = active И status == fired И нет действующей отсрочки (deferred_until is null или today >= deferred_until).
    expired и done закрыты (active = false). Пока today < deferred_until, waits_owner = false, статус остаётся fired.
10. Если status == expired, в выдаче поле `on_expiry` (из определения целиком, иначе null): вьюер показывает
    «срок вышел: <действие>». Для остальных статусов on_expiry тоже отдаётся как есть.
11. Результат — плоские словари с полями: id, version, key, key_kind (isin | ticker — по ISIN-регулярке на всю
    строку ключа, в данных не хранится), kind, trigger, status, state_status, active, waits_owner, computed, fired_by_deadline, closed_as, deferred_until, last_event{event, at, by} | null,
    fired_at, found_at, found_doc, verdict_now (while_pending.verdict), verdict_on_trigger, target_pct_on_trigger,
    action_code, target (on_trigger.target), amount_source (on_trigger.amount_source), on_expiry, not_before,
    valid_until, window_end, withdrawn_at, text (on_trigger.text), note. Модуль их не считает: несёт как есть.
12. Порядок результата детерминирован: по (key, id).
13. События с condition_id, которого нет в определениях, в результат не попадают (см. orphan_event_ids).
14. Новая версия определения начинает состояние заново. Для статуса и отметок учитываются только события с `at` ≥
    `created_at` последней версии определения; события раньше остаются в истории прежних версий. Если у последней
    версии `created_at` отсутствует — учитываются все события. last_event, found_at и found_doc — тоже только по ним.

CLI (заготовка «скрипта-выборки» для контекста советника, C5):
  python3 conditions_merge.py --defs conditions.yaml --state conditions-state.json
         [--key GMKN,MDMG] [--today 2026-10-30] [--format json|table] [--all]
  По умолчанию показываются только действующие условия; --all — все; --today по умолчанию — сегодня по МСК.

Зависимости: stdlib (+ PyYAML только для load_yaml / CLI).
"""

import argparse
import json
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codelists  # noqa: E402  — codelists.py/codelists.json рядом (в .skill — тоже в scripts/)
import time_msk  # noqa: E402


def _code(list_name, code):
    """Код из кодлиста; нет такого кода (не-legacy) — ошибка при загрузке, а не тихий пропуск."""
    if code not in codelists.codes(list_name, legacy=False):
        raise RuntimeError(f"conditions_merge: в кодлисте {list_name} нет кода {code!r}")
    return code


EV_FIRED = _code("condition_event", "fired")
EV_EXPIRED = _code("condition_event", "expired")
EV_DONE = _code("condition_event", "done")
EV_OWNER_MARK = _code("condition_event", "owner_mark")
EV_EVENT_FOUND = _code("condition_event", "event_found")
EV_REOPENED = _code("condition_event", "reopened")
MARK_DISMISSED = _code("owner_mark", "dismissed")
MARK_DEFERRED = _code("owner_mark", "deferred")
TRIGGER_DATE = _code("condition_trigger_type", "date")
TRIGGER_REPORT = _code("condition_trigger_type", "report_published")
BY_OWNER = _code("actor", "owner")

HANDLED_EVENTS = (EV_FIRED, EV_EXPIRED, EV_DONE, EV_OWNER_MARK, EV_EVENT_FOUND, EV_REOPENED)
HANDLED_MARKS = (MARK_DISMISSED, MARK_DEFERRED)

# статусы выдачи (словарь модуля, правило 5–8)
PENDING, FIRED, EXPIRED, DONE, WITHDRAWN = "pending", "fired", "expired", "done", "withdrawn"
ACTIVE_STATUSES = (PENDING, FIRED)

ISIN_RE = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def key_kind(key):
    """Вид ключа: 'isin' по ISIN-регулярке (вся строка), иначе 'ticker'. Считается при чтении, в данных не хранится."""
    return "isin" if isinstance(key, str) and ISIN_RE.fullmatch(key) else "ticker"


def _last_defs(defs):
    """id -> определение с максимальной version (правило 2); при равной version остаётся первое в файле."""
    last = {}
    for d in defs or []:
        cur = last.get(d["id"])
        if cur is None or d["version"] > cur["version"]:
            last[d["id"]] = d
    return last


def _events_by_id(state):
    """id -> события, отсортированные по (at, позиция) устойчиво (правило 3)."""
    out = {}
    for idx, e in enumerate((state or {}).get("events") or []):
        out.setdefault(e["condition_id"], []).append((e["at"], idx, e))
    return {cid: [e for _, _, e in sorted(lst, key=lambda x: (x[0], x[1]))] for cid, lst in out.items()}


def events_since(events, created_at):
    """Правило 14: события не раньше created_at последней версии; нет created_at — все."""
    if not created_at:
        return events
    return [e for e in events if e["at"] >= created_at]


def fold_events(events):
    """Правила 4–5: статус и отметки из последовательности событий."""
    last_real = ({"event": events[-1]["event"], "at": events[-1]["at"], "by": events[-1].get("by")}
                 if events else None)
    for i in range(len(events) - 1, -1, -1):
        if events[i]["event"] == EV_REOPENED:
            events = events[i + 1:]
            break
    status = PENDING
    fired_at = found_at = found_doc = closed_as = None
    defer_after_fire = defer_any = None
    for e in events:
        ev, data = e["event"], e.get("data") or {}
        if ev == EV_FIRED:
            if status == PENDING:
                status, fired_at = FIRED, e["at"]
        elif ev == EV_EXPIRED:
            if status == PENDING:
                status = EXPIRED
        elif ev == EV_DONE:
            if status in (PENDING, FIRED):
                status, closed_as = DONE, EV_DONE
        elif ev == EV_OWNER_MARK:
            mark = data.get("mark")
            if mark == MARK_DISMISSED:
                if status in (PENDING, FIRED):
                    status, closed_as = DONE, mark
            elif mark == MARK_DEFERRED:
                # отсрочку запоминаем; применится, только если итоговый статус fired (правило 5)
                defer_any = data.get("until")
                if status == FIRED:
                    defer_after_fire = data.get("until")
        elif ev == EV_EVENT_FOUND:
            if found_at is None:
                found_at, found_doc = e["at"], data.get("doc")
            if e.get("by") == BY_OWNER and status == PENDING:
                status, fired_at = FIRED, e["at"]
    return {"status": status, "fired_at": fired_at, "found_at": found_at, "found_doc": found_doc,
            "defer_after_fire": defer_after_fire, "defer_any": defer_any,
            "closed_as": closed_as, "last_event": last_real}


def apply_deadlines(folded, trigger, valid_until, today):
    """Правило 6: выход срока при чтении. Возвращает (status, fired_at, computed, fired_by_deadline)."""
    status, fired_at = folded["status"], folded["fired_at"]
    if status == PENDING:
        trigger = trigger or {}
        tt = trigger.get("type")
        if tt == TRIGGER_REPORT and trigger.get("window_end") and trigger["window_end"] < today:
            return FIRED, time_msk.day_end_iso(trigger["window_end"]), True, True
        if tt == TRIGGER_DATE and trigger.get("value") and trigger["value"] <= today:
            return FIRED, time_msk.day_start_iso(trigger["value"]), True, True
        if valid_until and valid_until < today:
            return EXPIRED, fired_at, True, False
    return status, fired_at, False, False


def merge(defs, state, today):
    """Объединить определения (любые версии) и состояние в плоский список условий (правила 1–13)."""
    ev_by_id = _events_by_id(state)
    result = []
    for cid, d in _last_defs(defs).items():
        folded = fold_events(events_since(ev_by_id.get(cid, []), d.get("created_at")))
        trigger = d.get("trigger") or {}
        live, fired_at, computed, by_deadline = apply_deadlines(folded, trigger, d.get("valid_until"), today)
        # отсрочка имеет смысл только у сработавшего (из событий или по сроку)
        deferred_until = None
        if live == FIRED:
            deferred_until = folded["defer_any"] if computed else folded["defer_after_fire"]
        wd = d.get("withdrawn")
        status = WITHDRAWN if wd else live
        active = (not wd) and live in ACTIVE_STATUSES
        deferred_now = bool(deferred_until) and today < deferred_until
        on_trigger = d.get("on_trigger") or {}
        result.append({
            "id": cid,
            "version": d["version"],
            "key": d["key"],
            "key_kind": key_kind(d["key"]),
            "kind": d.get("kind"),
            "trigger": trigger,
            "status": status,
            "state_status": live,
            "active": active,
            "waits_owner": active and live == FIRED and not deferred_now,
            "computed": computed,
            "fired_by_deadline": by_deadline,
            "closed_as": folded["closed_as"] if live == DONE else None,
            "deferred_until": deferred_until,
            "last_event": folded["last_event"],
            "fired_at": fired_at,
            "found_at": folded["found_at"],
            "found_doc": folded["found_doc"],
            "verdict_now": (d.get("while_pending") or {}).get("verdict"),
            "verdict_on_trigger": on_trigger.get("verdict"),
            "target_pct_on_trigger": on_trigger.get("target_pct"),
            "action_code": on_trigger.get("action"),
            "target": on_trigger.get("target"),
            "amount_source": on_trigger.get("amount_source"),
            "on_expiry": d.get("on_expiry"),
            "not_before": d.get("not_before"),
            "valid_until": d.get("valid_until"),
            "window_end": trigger.get("window_end"),
            "withdrawn_at": wd.get("at") if wd else None,
            "text": on_trigger.get("text"),
            "note": d.get("note"),
        })
    result.sort(key=lambda r: (r["key"], r["id"]))
    return result


def select(items, keys=None, only_active=False):
    """Фильтр результата merge: по ключам бумаг и/или только действующие. Порядок сохраняется."""
    ks = set(keys) if keys else None
    return [r for r in items
            if (ks is None or r["key"] in ks) and (not only_active or r["active"])]


def orphan_event_ids(defs, state):
    """id условий, на которые ссылаются события, но которых нет в определениях (правило 13)."""
    known = {d["id"] for d in defs or []}
    return sorted({e["condition_id"] for e in (state or {}).get("events") or []} - known)


def load_yaml(path):
    """YAML без автоматического превращения дат во время/дату: все даты остаются строками (правило 1)."""
    import yaml

    class _StrLoader(yaml.SafeLoader):
        pass

    _StrLoader.yaml_implicit_resolvers = {
        k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:timestamp"]
        for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }
    with open(path, encoding="utf-8") as f:
        return yaml.load(f, Loader=_StrLoader)


def _is_date(v):
    if not isinstance(v, str) or not _DATE_RE.fullmatch(v):
        return False
    try:
        date.fromisoformat(v)
    except ValueError:
        return False
    return True


# ----------------------------------------------------------------------------- вывод и CLI

def _trigger_str(t):
    tt, v = t.get("type"), t.get("value")
    s = f"{tt} {v}"
    if t.get("window_end"):
        s += f" (окно до {t['window_end']})"
    return s


def format_table(items):
    """Одна строка на условие."""
    if not items:
        return "(условий нет)"
    rows = [("КЛЮЧ", "ID", "ВИД", "ТРИГГЕР", "СТАТУС", "ДО", "ЗАМЕТКА")]
    for r in items:
        note = []
        if r["waits_owner"]:
            note.append("ждёт владельца")
        if r["deferred_until"] and r["status"] == FIRED and not r["waits_owner"]:
            note.append(f"отложено до {r['deferred_until']}")
        if r["fired_by_deadline"]:
            note.append("по сроку, не найдено" if r["trigger"].get("type") == TRIGGER_REPORT else "по сроку")
        if r["status"] == EXPIRED:
            oe = r["on_expiry"]
            note.append("срок вышел" + (f": {oe.get('action')}" if oe else ""))
        if r["closed_as"] == MARK_DISMISSED:
            note.append("не актуально")
        if r["status"] == WITHDRAWN:
            note.append(f"снято, было {r['state_status']}")
        if r["found_at"] and r["active"]:
            note.append("найдено монитором")
        rows.append((r["key"], r["id"], r["kind"] or "-", _trigger_str(r["trigger"]), r["status"],
                     r["valid_until"] or "-", "; ".join(note)))
    widths = [max(len(str(row[i])) for row in rows) for i in range(len(rows[0]) - 1)]
    return "\n".join("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(row[:-1])) + "  " + row[-1]
                     for row in rows).rstrip()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Объединение определений и состояния условий")
    ap.add_argument("--defs", required=True, help="conditions.yaml (conditions@2)")
    ap.add_argument("--state", required=True, help="conditions-state.json (conditions-state@1)")
    ap.add_argument("--key", default="", help="ключи бумаг через запятую")
    ap.add_argument("--today", default=time_msk.today_iso(), help="дата YYYY-MM-DD (по умолчанию сегодня, МСК)")
    ap.add_argument("--format", choices=("json", "table"), default="table")
    ap.add_argument("--all", action="store_true", help="показать и закрытые/снятые")
    a = ap.parse_args(argv)

    defs_doc = load_yaml(a.defs)
    with open(a.state, encoding="utf-8") as f:
        state = json.load(f)
    defs = defs_doc.get("conditions") or []
    if not _is_date(a.today):
        print(f"--today: ожидается YYYY-MM-DD, получено {a.today!r}", file=sys.stderr)
        return 2
    keys = [k.strip() for k in a.key.split(",") if k.strip()]
    items = select(merge(defs, state, a.today), keys=keys, only_active=not a.all)
    orphans = orphan_event_ids(defs, state)
    if orphans:
        print(f"Предупреждение: события без определения: {', '.join(orphans)}", file=sys.stderr)
    if a.format == "json":
        print(json.dumps(items, ensure_ascii=False, indent=2))
    else:
        print(format_table(items))
    return 0


if __name__ == "__main__":
    sys.exit(main())
