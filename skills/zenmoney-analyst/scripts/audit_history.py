#!/usr/bin/env python3
"""История аудитов учёта ZenMoney: единственный писатель `ZenMoney/audit/`.

Узкое исключение из D3 (решение 2026-10-05): скилл пишет в Claude-Memory только
файлы этой папки и только этим скриптом. Карту (`zenmoney-map.md`) не трогает.

  history.json   zenmoney-audit@1 — по записи на месяц (только агрегаты) + реестр
                 замечаний по ID (без сумм, названий, счетов и точек)
  accepted.json  zenmoney-audit-accepted@1 — принятые исключения («это норма»)
  spending.json  zenmoney-spending@1 — статистика месяца (month_stats.py): итоги, категории
                 верхнего уровня и подкатегории обычных трат, поездки, топ мест платежа
                 (решение 2026-10-05); без счетов и отдельных операций. `recomputed_at` —
                 дата, когда уже записанный месяц переписан с другими итогами (правка в
                 ZenMoney после закрытия); совпавший до рубля пересчёт её не ставит
  spending-rules.json  zenmoney-spending-rules@1 — ответы пользователя для статистики месяца:
                 разовые траты (ID операции) и группы, где крупная сумма — норма (ID категории)
  trips.json     zenmoney-trips@1 — статистика поездок (trip_stats.py): типы трат, фазы
                 «до / во время / после», предоплаты по сроку; без операций
  facts.json     zenmoney-facts@1 — факты «на что взглянуть» (history_query.compute_facts):
                 производный файл, пересчитывается сам после каждой записи spending.json и
                 history.json; руками — команда facts (после смены порогов в PARAMS)

Команды (по умолчанию dry-run — ничего не пишет, печатает сводку):
  apply    --run RUN.json --history history.json [--date YYYY-MM-DD] [--write]
           Слить результат audit_month.py (month|quarter) в историю. Дата аудита (as_of записи,
           first_seen/last_seen/closed_at замечаний) — день записи (--date, по умолчанию сегодня),
           если он позже as_of прогона: у перезакрытого прошлого месяца as_of прогона — конец его
           данных, и замечание, найденное сегодня, иначе «старше 3 месяцев», а закрытое — раньше,
           чем найдено.
  redate   --history history.json --month YYYY-MM [--month ...] --date YYYY-MM-DD [--write]
           Починка дат уже записанного: у записи месяца as_of → дата, и у замечаний этих месяцев
           каждая дата, равная прежнему as_of записи, → та же дата (только вперёд).
  accept   --accepted accepted.json --add ID CHECK "причина" [--add ...] [--kind KIND] --date D [--write]
           --kind — вид корректировки (только A2): transfer_out — перевод себе на счёт вне учёта
           (не трата, в долю незаписанного не входит), unrecorded — незаписанная трата, unknown —
           не помню / выравнивание (обе входят). С --kind повтор ID обновляет вид и причину.
  rules    --rules spending-rules.json --date YYYY-MM-DD [--one-off ID MONTH "что"]...
           [--op ID ДАТА "счёт" СУММА]... [--one-off-merchant MID "что" [--merchant-name MID "название"]...]
           [--regular-big CATEGORY_ID "что"]... [--remove ID]... [--write]
           --op — тройка операции (дата, название счёта, сумма) для --one-off: по ней CSV-пересчёт находит трату.
           Записать ответ пользователя на «это разовая?» — после его «да», без ручной правки карты.
  spending --run STATS.json --spending spending.json [--write]
           Слить результат month_stats.py (только закрытый месяц) в spending.json.
  trip     --run TRIP.json --trips trips.json --date YYYY-MM-DD [--write]
           Слить результат trip_stats.py report в trips.json (по поездке; повтор — замена).
  facts    --spending spending.json [--history history.json] [--facts facts.json] [--write]
           Пересчитать факты (по умолчанию facts.json рядом со spending.json).
  validate --history history.json [--accepted accepted.json]

Запись: перечитать файл перед записью и сравнить с прочитанным (изменился → стоп),
копия прежней версии в *.bak, атомарная замена. Только stdlib.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

# Общие модули — канон в _shared-references/; в упакованном .skill — в своей scripts/ (pack.sh кладёт по импорту).
_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (_HERE, os.path.normpath(os.path.join(_HERE, "..", "..", "..", "_shared-references"))):
    if _cand not in sys.path:
        sys.path.insert(0, _cand)
import hub_settings  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import history_query as hq  # noqa: E402

HISTORY_SCHEMA = "zenmoney-audit@1"
ACCEPTED_SCHEMA = "zenmoney-audit-accepted@1"
RUN_SCHEMA = "zenmoney-audit-run@1"
SPENDING_SCHEMA = "zenmoney-spending@1"
TRIPS_SCHEMA = "zenmoney-trips@1"
TRIP_RUN_SCHEMA = "zenmoney-trip-stats-run@1"
TRIP_KEYS = {"trip", "as_of", "period", "first_purchase", "totals", "by_type", "by_phase", "type_by_phase",
             "prepaid_by_lead", "currencies", "unconverted"}
STATS_RUN_SCHEMA = "zenmoney-month-stats-run@1"
RULES_SCHEMA = "zenmoney-spending-rules@1"
# one_off_merchants (2026-10-06): место платежа, все траты в котором разовые (VDSina — раз в год)
RULES_KEYS = {"schema", "updated", "one_off", "one_off_merchants", "regular_big"}
SPENDING_KEYS = {"month", "as_of", "totals", "excluded", "categories", "categories_regular", "income_categories", "trips",
                 "merchants", "one_off", "merchant_share_of_expense", "unconverted",
                 "subcategories_regular", "recomputed_at"}
TOTALS_KEYS = {"expense_rub", "income_rub", "refunds_rub", "expense_in_balance_rub", "income_in_balance_rub",
               "expense_off_balance_rub", "expense_trips_rub", "expense_one_off_rub", "expense_regular_rub",
               "operations"}
LIST_ITEM_KEYS = {"categories": {"name", "rub", "count", "share"}, "categories_regular": {"name", "rub", "count", "share"},
                  "income_categories": {"name", "rub"},
                  "trips": {"name", "rub", "count"}, "merchants": {"name", "rub", "count", "category", "sub", "kind", "rest"},
                  "one_off": {"name", "rub", "category", "note"},
                  "subcategories_regular": {"parent", "name", "rub", "count"}}
# что сравнивается, чтобы решить «месяц пересчитан с другими итогами» (поля есть в обеих записях)
RECOMPUTE_FIELDS = ("totals", "categories_regular", "subcategories_regular", "trips", "one_off")

RECORD_KEYS = {
    "month", "as_of", "mode", "operations", "flagged", "clean_share_count", "clean_share_rub",
    "expense_rub", "correction_rub", "correction_transfer_out_rub", "correction_share_of_expense", "by_check", "b6_count", "b7_count", "b7_rub",
    "c_counts", "fixed_count", "rechecked_count", "fixed_share", "not_rechecked_count",
    "open_by_age", "open_total", "unconverted", "places_counts",
}
# места платежа месяца (2.15.0, handoff 2.3): только числа по видам audit_month.places_check —
# названий и ID мест в истории нет; на странице — строка в «Качестве учёта»
PLACES_KINDS = {"twins", "split", "unlinked", "rename", "bank_text", "chains"}
ISSUE_KEYS = {"check", "month", "first_seen", "last_seen", "status", "closed_at"}
ISSUE_STATUSES = {"open", "fixed", "accepted"}
A2_KINDS = {"transfer_out", "unrecorded", "unknown"}
CHECKS = {"A1", "A2", "A3", "A4", "A5", "B6", "C9", "C10", "C11", "C12", "D13"}   # C10 — места платежа, D13 — трата прямо в категории с подкатегориями: только accept («так и задумано»)
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH = re.compile(r"^\d{4}-\d{2}$")


class Blocking(Exception):
    pass


FACTS_TOP_KEYS = {"schema", "updated", "month", "params", "facts", "flagged_categories", "not_enough_data"}
FACT_KINDS = {"jump", "growth", "acceleration", "minus_months", "unrecorded_rising"}
FACT_FORBIDDEN = {"id", "accountId", "merchantId", "categoryId", "operations"}


# ─── файлы ───────────────────────────────────────────────────────────────────

def read(path: Path, empty):
    """(объект, хеш байтов); нет файла — (empty, None)."""
    if not path.exists():
        return empty, None
    raw = path.read_bytes()
    return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()


def write_atomic(path: Path, obj, seen_hash):
    current = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    if current != seen_hash:
        raise Blocking(f"{path.name} изменился после чтения — перечитай и повтори, ничего не записано")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# ─── валидация ───────────────────────────────────────────────────────────────

def validate_history(h) -> list[str]:
    errs = []
    if h.get("schema") != HISTORY_SCHEMA:
        errs.append(f"schema ≠ {HISTORY_SCHEMA}")
    if set(h) - {"schema", "updated", "records", "issues"}:
        errs.append(f"лишние поля верхнего уровня: {sorted(set(h) - {'schema', 'updated', 'records', 'issues'})}")
    months = [r.get("month") for r in h.get("records", [])]
    if months != sorted(set(months)):
        errs.append("records: месяцы не по возрастанию или повторяются")
    for r in h.get("records", []):
        extra = set(r) - RECORD_KEYS
        if extra:
            errs.append(f"запись {r.get('month')}: недопустимые поля {sorted(extra)} — в истории только агрегаты")
        if not MONTH.match(str(r.get("month", ""))):
            errs.append(f"запись: плохой месяц {r.get('month')!r}")
        if not DATE.match(str(r.get("as_of", ""))):
            errs.append(f"запись {r.get('month')}: плохая дата as_of")
        pc = r.get("places_counts")
        if pc is not None and (not isinstance(pc, dict) or set(pc) - PLACES_KINDS
                               or any(v is not None and (not isinstance(v, int) or v < 0) for v in pc.values())):
            errs.append(f"запись {r.get('month')}: places_counts — только числа по видам {sorted(PLACES_KINDS)}")
    for key, it in (h.get("issues") or {}).items():
        extra = set(it) - ISSUE_KEYS
        if extra:
            errs.append(f"замечание {key}: недопустимые поля {sorted(extra)}")
        if it.get("check") not in CHECKS or not key.startswith(f"{it.get('check')}:"):
            errs.append(f"замечание {key}: проверка {it.get('check')!r} не совпадает с ключом")
        if it.get("status") not in ISSUE_STATUSES:
            errs.append(f"замечание {key}: статус {it.get('status')!r}")
        if it.get("status") != "open" and not it.get("closed_at"):
            errs.append(f"замечание {key}: закрыто без closed_at")
        fs, ls, ca = it.get("first_seen") or "", it.get("last_seen") or "", it.get("closed_at") or ""
        if (ls and fs and ls < fs) or (ca and fs and ca < fs):
            errs.append(f"замечание {key}: даты назад во времени (найдено {fs}, видено {ls}, закрыто {ca or '—'})")
    return errs


def validate_accepted(a) -> list[str]:
    errs = []
    if a.get("schema") != ACCEPTED_SCHEMA:
        errs.append(f"schema ≠ {ACCEPTED_SCHEMA}")
    seen = set()
    for it in a.get("items", []):
        if set(it) - {"id", "check", "reason", "date", "kind"} or not it.get("id") or it.get("check") not in CHECKS:
            errs.append(f"исключение {it}: нужны id, check из {sorted(CHECKS)}, reason, date")
        if "kind" in it and (it.get("check") != "A2" or it["kind"] not in A2_KINDS):
            errs.append(f"исключение {it.get('id')}: вид {it.get('kind')!r} — только для A2, один из {sorted(A2_KINDS)}")
        if (it.get("id"), it.get("check")) in seen:
            errs.append(f"исключение {it.get('id')}/{it.get('check')}: повтор")
        seen.add((it.get("id"), it.get("check")))
    return errs


def validate_spending(s) -> list[str]:
    errs = []
    if s.get("schema") != SPENDING_SCHEMA:
        errs.append(f"schema ≠ {SPENDING_SCHEMA}")
    months = [m.get("month") for m in s.get("months", [])]
    if months != sorted(set(months)):
        errs.append("months: не по возрастанию или повторяются")
    for m in s.get("months", []):
        tag = m.get("month")
        if set(m) - SPENDING_KEYS:
            errs.append(f"{tag}: недопустимые поля {sorted(set(m) - SPENDING_KEYS)} — без счетов и операций")
        if set(m.get("totals") or {}) - TOTALS_KEYS:
            errs.append(f"{tag}: недопустимые поля totals {sorted(set(m['totals']) - TOTALS_KEYS)}")
        for key, allowed in LIST_ITEM_KEYS.items():
            for it in m.get(key) or []:
                if set(it) - allowed:
                    errs.append(f"{tag}.{key}: недопустимые поля {sorted(set(it) - allowed)}")
                    break
        if "recomputed_at" in m and not DATE.match(str(m["recomputed_at"])):
            errs.append(f"{tag}: плохая дата recomputed_at")
        if not MONTH.match(str(tag or "")) or not DATE.match(str(m.get("as_of", ""))):
            errs.append(f"{tag}: плохой месяц или as_of")
    return errs


def validate_facts(f) -> list[str]:
    errs = []
    if f.get("schema") != hq.FACTS_SCHEMA:
        errs.append(f"schema ≠ {hq.FACTS_SCHEMA}")
    if set(f) - FACTS_TOP_KEYS:
        errs.append(f"недопустимые поля {sorted(set(f) - FACTS_TOP_KEYS)}")
    if f.get("month") is not None and not MONTH.match(str(f["month"])):
        errs.append("плохой month")
    for x in f.get("facts", []):
        if x.get("kind") not in FACT_KINDS:
            errs.append(f"неизвестный вид факта {x.get('kind')!r}")
        bad = {k for k in x if k.startswith("_")} | (set(x) & FACT_FORBIDDEN)
        if bad:
            errs.append(f"{x.get('kind')}: служебные или запрещённые поля {sorted(bad)}")
    return errs


def build_facts(audit_dir: Path, spending=None, history=None):
    """Факты по файлам папки audit/ (spending.json, history.json рядом)."""
    if spending is None:
        spending = read(audit_dir / "spending.json", {"schema": SPENDING_SCHEMA, "months": []})[0]
    if history is None:
        history = read(audit_dir / "history.json", None)[0]
    new = hq.compute_facts(spending, history)
    errs = validate_facts(new)
    if errs:
        raise Blocking("факты не прошли проверку: " + "; ".join(errs))
    return new


def refresh_facts(audit_dir: Path, spending=None, history=None, facts_path: Path | None = None):
    """Пересчитать и записать facts.json (производный файл). Вызывается после записи
    spending.json / history.json; ошибка фактов не отменяет основную запись."""
    fp = facts_path or audit_dir / "facts.json"
    try:
        new = build_facts(audit_dir, spending, history)
        _, h = read(fp, None)
        write_atomic(fp, new, h)
        return {"written": True, "month": new["month"], "facts": len(new["facts"]),
                "flagged": sorted(new["flagged_categories"])}
    except (Blocking, OSError, ValueError, KeyError) as e:
        return {"written": False, "error": str(e)}


def apply_spending(run, sp):
    if run.get("schema") != STATS_RUN_SCHEMA:
        raise Blocking("на входе не результат month_stats.py")
    if not run.get("closed"):
        raise Blocking(f"месяц {run.get('month')} не закрыт на {run.get('as_of')} — в историю пишутся только закрытые")
    rec = {k: run[k] for k in ("month", "as_of", "totals", "excluded", "categories", "categories_regular",
                               "income_categories", "trips", "merchants", "merchant_share_of_expense")}
    for k in ("one_off", "subcategories_regular"):
        if k in run:
            rec[k] = run[k]
    rec["unconverted"] = (run.get("coverage") or {}).get("unconverted") or {}
    old = next((m for m in sp.get("months", []) if m["month"] == rec["month"]), None)
    months = [m for m in sp.get("months", []) if m["month"] != rec["month"]]
    replaced = old is not None
    changed = replaced and _differs(old, rec)
    if changed:
        rec["recomputed_at"] = run["as_of"]
    elif old and old.get("recomputed_at"):
        rec["recomputed_at"] = old["recomputed_at"]
    new = {"schema": SPENDING_SCHEMA, "updated": run["as_of"],
           "months": sorted(months + [rec], key=lambda m: m["month"])}
    errs = validate_spending(new)
    if errs:
        raise Blocking("статистика не прошла проверку: " + "; ".join(errs))
    return new, {"month": rec["month"], "record": "заменена" if replaced else "добавлена",
                 "recomputed": changed, "months_total": len(new["months"])}


def _num_equal(a, b):
    """Равенство записей с допуском 1 ₽ на числах (округления курсов) и без учёта порядка списков."""
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= 1.0
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(_num_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        key = lambda x: json.dumps({k: v for k, v in x.items() if not isinstance(v, (int, float))},
                                   ensure_ascii=False, sort_keys=True) if isinstance(x, dict) else str(x)
        return len(a) == len(b) and all(_num_equal(x, y) for x, y in zip(sorted(a, key=key), sorted(b, key=key)))
    return a == b


def _differs(old, new):
    """Итоги месяца изменились? Сравниваются поля, которые есть в обеих записях: появление
    нового поля (подкатегории при пересчёте истории) пересчётом с другими итогами не считается."""
    for k in RECOMPUTE_FIELDS:
        if k not in old or k not in new:
            continue
        a, b = old[k], new[k]
        if k == "totals":   # число операций меняется и от правок вне трат — не итог
            a, b = ({x: v for x, v in t.items() if x != "operations"} for t in (a, b))
        if not _num_equal(a, b):
            return True
    return False


def _op_ok(op) -> bool:
    """Тройка операции для поиска в CSV: {date, account, amount} и ничего лишнего."""
    return (isinstance(op, dict) and set(op) == {"date", "account", "amount"}
            and bool(DATE.match(str(op["date"]))) and isinstance(op["account"], str) and bool(op["account"])
            and isinstance(op["amount"], (int, float)) and not isinstance(op["amount"], bool))


def validate_rules(r) -> list[str]:
    errs = []
    if r.get("schema") != RULES_SCHEMA:
        errs.append(f"schema ≠ {RULES_SCHEMA}")
    if set(r) - RULES_KEYS:
        errs.append(f"лишние поля: {sorted(set(r) - RULES_KEYS)}")
    for key, idf, allowed in (("one_off", "id", {"id", "month", "note", "date", "op"}),
                              ("one_off_merchants", "merchant_id", {"merchant_id", "note", "date", "names"}),
                              ("regular_big", "category_id", {"category_id", "note", "date"})):
        seen = set()
        for it in r.get(key, []):
            if set(it) - allowed or not it.get(idf) or not DATE.match(str(it.get("date", ""))):
                errs.append(f"{key}: запись {it} — нужны {sorted(allowed)}")
            if key == "one_off" and not MONTH.match(str(it.get("month", ""))):
                errs.append(f"one_off {it.get('id')}: плохой месяц {it.get('month')!r}")
            if "op" in it and not _op_ok(it["op"]):
                errs.append(f"one_off {it.get('id')}: op — нужны date ГГГГ-ММ-ДД, account (строка), amount (число)")
            if "names" in it and not (isinstance(it["names"], list) and it["names"]
                                      and all(isinstance(n, str) and n for n in it["names"])):
                errs.append(f"one_off_merchants {it.get('merchant_id')}: names — непустой список названий")
            if it.get(idf) in seen:
                errs.append(f"{key} {it.get(idf)}: повтор")
            seen.add(it.get(idf))
    return errs


def apply_rules(cur, one_off, regular_big, remove, today, one_off_merchants=None, ops=None, names=None):
    """Добавить ответы пользователя; повтор того же ID — замена заметки; --remove — снять ошибочное.
    ops — [(ID, дата, счёт, сумма)]: тройка операции правила «разовая» (без неё CSV-пересчёт не найдёт трату);
    names — [(merchant_id, название)]: написания места в выгрузке."""
    gone = set(remove or [])
    oo = {x["id"]: x for x in cur.get("one_off", []) if x["id"] not in gone}
    om = {x["merchant_id"]: x for x in cur.get("one_off_merchants", []) if x["merchant_id"] not in gone}
    rb = {x["category_id"]: x for x in cur.get("regular_big", []) if x["category_id"] not in gone}
    removed = (len(cur.get("one_off", [])) + len(cur.get("one_off_merchants", [])) + len(cur.get("regular_big", []))
               - len(oo) - len(om) - len(rb))
    if gone and not removed:
        raise Blocking(f"снимать нечего: {sorted(gone)} нет в правилах")
    old_ops = {x["id"]: x["op"] for x in cur.get("one_off", []) if "op" in x}
    for ident, month, note in one_off or []:
        if ident in rb:
            raise Blocking(f"{ident} уже в крупных обычных группах — это ID категории, а не операции")
        oo[ident] = {"id": ident, "month": month, "note": note, "date": today}
        if ident in old_ops:
            oo[ident]["op"] = old_ops[ident]
    for cid, note in regular_big or []:
        rb[cid] = {"category_id": cid, "note": note, "date": today}
    for mid, note in one_off_merchants or []:
        om[mid] = {"merchant_id": mid, "note": note, "date": today}
    for ident, d, acc, amount in ops or []:
        if ident not in oo:
            raise Blocking(f"--op для {ident}: такого правила «разовая» нет")
        try:
            amount = float(amount)
        except ValueError:
            raise Blocking(f"--op {ident}: сумма {amount!r} — не число")
        oo[ident]["op"] = {"date": d, "account": acc, "amount": int(amount) if amount == int(amount) else amount}
    for mid, nm in names or []:
        if mid not in om:
            raise Blocking(f"--merchant-name для {mid}: такого места в правилах нет")
        om[mid]["names"] = list(dict.fromkeys(om[mid].get("names", []) + [nm]))
    new = {"schema": RULES_SCHEMA, "updated": today,
           "one_off": sorted(oo.values(), key=lambda x: (x["month"], x["id"])),
           "one_off_merchants": sorted(om.values(), key=lambda x: x["merchant_id"]),
           "regular_big": sorted(rb.values(), key=lambda x: x["category_id"])}
    errs = validate_rules(new)
    if errs:
        raise Blocking("правила не прошли проверку: " + "; ".join(errs))
    return new, {"one_off_total": len(new["one_off"]), "one_off_merchants_total": len(new["one_off_merchants"]),
                 "regular_big_total": len(new["regular_big"]),
                 "removed": removed}


def validate_trips(s) -> list[str]:
    errs = []
    if s.get("schema") != TRIPS_SCHEMA:
        errs.append(f"schema ≠ {TRIPS_SCHEMA}")
    ids = [t.get("trip", {}).get("id") for t in s.get("trips", [])]
    if len(ids) != len(set(ids)) or None in ids:
        errs.append("trips: поездка без id или повторяется")
    for t in s.get("trips", []):
        if set(t) - TRIP_KEYS:
            errs.append(f"{t.get('trip', {}).get('name')}: недопустимые поля {sorted(set(t) - TRIP_KEYS)} — без операций")
    return errs


SITE_TRIP_PREFIX = "site:"      # id поездки, заведённой с сайта (aux/trip-ids.json), пока нет настоящего ID тега


def apply_trip(run, tr, as_of):
    if run.get("schema") != TRIP_RUN_SCHEMA:
        raise Blocking("на входе не результат trip_stats.py report")
    rec = {k: run[k] for k in TRIP_KEYS - {"as_of", "unconverted"}}
    rec["as_of"] = as_of
    rec["unconverted"] = (run.get("coverage") or {}).get("unconverted") or {}
    # запись сайта (id «site:…») и запись скилла (настоящий ID тега) об одной поездке — одна запись: пришла запись скилла —
    # сайтовая заменяется; пришла сайтовая, а настоящая уже есть, — обновляются её числа под настоящим id
    name, rid = rec["trip"]["name"], rec["trip"]["id"]
    same_name = [t for t in tr.get("trips", []) if t["trip"]["name"] == name and t["trip"]["id"] != rid]
    if rid.startswith(SITE_TRIP_PREFIX):
        real = [t for t in same_name if not t["trip"]["id"].startswith(SITE_TRIP_PREFIX)]
        if real:
            rec["trip"] = dict(rec["trip"], id=real[0]["trip"]["id"])
    else:
        same_name = [t for t in same_name if t["trip"]["id"].startswith(SITE_TRIP_PREFIX)]
    drop = {t["trip"]["id"] for t in same_name} | {rec["trip"]["id"]}
    trips = [t for t in tr.get("trips", []) if t["trip"]["id"] not in drop]
    replaced = len(trips) != len(tr.get("trips", []))
    new = {"schema": TRIPS_SCHEMA, "updated": as_of,
           "trips": sorted(trips + [rec], key=lambda t: (t["period"].get("start") or "", t["trip"]["name"]))}
    errs = validate_trips(new)
    if errs:
        raise Blocking("статистика поездок не прошла проверку: " + "; ".join(errs))
    return new, {"trip": rec["trip"]["name"], "record": "заменена" if replaced else "добавлена",
                 "trips_total": len(new["trips"])}


# ─── apply ───────────────────────────────────────────────────────────────────

def record_from_run(run) -> dict:
    s, c, h = run["stats"], run["checks"], run.get("history") or {}
    rec = {
        "month": run["month"], "as_of": run["as_of"], "mode": run["mode"],
        "operations": s["operations"], "flagged": s["flagged"],
        "clean_share_count": s["clean_share_count"], "clean_share_rub": s["clean_share_rub"],
        "expense_rub": s["expense_rub"], "correction_rub": s.get("correction_rub"),
        "correction_transfer_out_rub": s.get("correction_transfer_out_rub"),
        "correction_share_of_expense": s["correction_share_of_expense"],
        "by_check": s["by_check"],
        "b6_count": len(c.get("B6") or []),
        "b7_count": sum(x["count"] for x in c.get("B7") or []),
        "b7_rub": round(sum(x["rub"] for x in c.get("B7") or []), 2),
        "c_counts": ({k: (len(c[k]) if c.get(k) is not None else None) for k in ("C9", "C11", "C12")}
                     if run["mode"] == "quarter" else None),
        "fixed_count": h.get("fixed_count"), "rechecked_count": h.get("rechecked_count"),
        "fixed_share": h.get("fixed_share"), "not_rechecked_count": h.get("not_rechecked_count"),
        "open_by_age": h.get("open_by_age"),
        "unconverted": run["coverage"].get("unconverted") or {},
        "places_counts": ({k: v for k, v in ((run.get("places") or {}).get("counts") or {}).items() if k in PLACES_KINDS}
                          or None),
    }
    return rec


AGE_LT_1M, AGE_LE_3M = 31, 92   # как audit_month.age_bucket


def open_by_age(issues, stamp) -> dict:
    from datetime import date as _d
    o = {"lt_1m": 0, "1_3m": 0, "gt_3m": 0}
    for it in issues.values():
        if it["status"] == "open":
            days = (_d.fromisoformat(stamp) - _d.fromisoformat(it["first_seen"])).days
            o["lt_1m" if days < AGE_LT_1M else "1_3m" if days <= AGE_LE_3M else "gt_3m"] += 1
    return o


def apply(run, hist, today=None):
    if run.get("schema") != RUN_SCHEMA or run.get("mode") not in ("month", "quarter"):
        raise Blocking("на входе не результат audit_month.py month|quarter")
    has_open = any(it.get("status") == "open" for it in (hist.get("issues") or {}).values())
    if has_open and not run.get("history"):
        raise Blocking("в истории есть открытые замечания, а аудит запущен без --history — "
                       "перезапусти audit_month.py с --history, иначе исправленное не отличить от нового")
    as_of = max(run["as_of"], today) if today else run["as_of"]
    issues = dict(hist.get("issues") or {})
    keys = (run.get("history") or {}).get("keys") or {}
    summary = {"new": 0, "reopened": 0, "still_open": 0, "fixed": 0, "accepted": 0}
    for k in keys.get("fixed", []):
        if issues.get(k, {}).get("status") == "open":
            issues[k] = {**issues[k], "status": "fixed", "closed_at": as_of}
            summary["fixed"] += 1
    for k in keys.get("accepted", []):
        if issues.get(k, {}).get("status") == "open":
            issues[k] = {**issues[k], "status": "accepted", "closed_at": as_of}
            summary["accepted"] += 1
    for k, it in run.get("issues", {}).items():
        old = issues.get(k)
        if old is None:
            issues[k] = {"check": it["check"], "month": it["month"], "first_seen": as_of,
                         "last_seen": as_of, "status": "open"}
            summary["new"] += 1
        else:
            if old["status"] != "open":
                summary["reopened"] += 1
            else:
                summary["still_open"] += 1
            issues[k] = {k2: v for k2, v in old.items() if k2 != "closed_at"} | {"last_seen": as_of, "status": "open"}
    rec = record_from_run(run)
    rec["as_of"] = as_of
    rec["open_total"] = sum(1 for it in issues.values() if it["status"] == "open")
    if as_of != run["as_of"]:   # возраст прогона считан от его as_of — пересчитать от дня записи
        rec["open_by_age"] = open_by_age(issues, as_of)
    records = [r for r in hist.get("records", []) if r["month"] != rec["month"]]
    replaced = len(records) != len(hist.get("records", []))
    records = sorted(records + [rec], key=lambda r: r["month"])
    new = {"schema": HISTORY_SCHEMA, "updated": max(as_of, hist.get("updated") or as_of), "records": records,
           "issues": dict(sorted(issues.items()))}
    errs = validate_history(new)
    if errs:
        raise Blocking("история не прошла проверку: " + "; ".join(errs))
    summary.update({"month": rec["month"], "record": "заменена" if replaced else "добавлена",
                    "open_total": rec["open_total"], "records_total": len(records)})
    return new, summary


def accept(acc, adds, today, kind=None):
    """Повтор ID без вида — пропуск; с видом — обновить вид и причину (перепометка старых)."""
    items = list(acc.get("items", []))
    pos = {(i["id"], i["check"]): n for n, i in enumerate(items)}
    added = updated = 0
    for ident, chk, reason in adds:
        rec = {"id": ident, "check": chk, "reason": reason, "date": today}
        if kind:
            rec["kind"] = kind
        if (ident, chk) in pos:
            if kind:
                items[pos[(ident, chk)]] = rec
                updated += 1
            continue
        pos[(ident, chk)] = len(items)
        items.append(rec)
        added += 1
    new = {"schema": ACCEPTED_SCHEMA, "items": items}
    errs = validate_accepted(new)
    if errs:
        raise Blocking("; ".join(errs))
    return new, {"added": added, "updated": updated, "total": len(items)}


# ─── CLI ─────────────────────────────────────────────────────────────────────

def redate(hist, months, date_):
    """У записей месяцев as_of → date_; у замечаний этих месяцев даты, равные прежнему as_of, → date_."""
    if not DATE.match(date_):
        raise Blocking(f"плохая дата {date_!r}")
    recs = {r["month"]: r for r in hist.get("records", [])}
    miss = [m for m in months if m not in recs]
    if miss:
        raise Blocking(f"нет записей за {miss}")
    new = json.loads(json.dumps(hist))
    changes = []
    for r in new["records"]:
        if r["month"] not in months:
            continue
        old = r["as_of"]
        if old >= date_:
            changes.append(f"{r['month']}: as_of {old} — не раньше {date_}, оставлено")
            continue
        r["as_of"] = date_
        changes.append(f"{r['month']}: as_of {old} → {date_}")
        for k, it in new.get("issues", {}).items():
            if it["month"] != r["month"]:
                continue
            for f in ("first_seen", "last_seen", "closed_at"):
                if it.get(f) == old:
                    it[f] = date_
                    changes.append(f"  {k}: {f} {old} → {date_}")
        if r.get("open_by_age") is not None and r is new["records"][-1]:
            r["open_by_age"] = open_by_age(new["issues"], r["as_of"])
    new["updated"] = max(new.get("updated") or date_, date_)
    errs = validate_history(new)
    if errs:
        raise Blocking("история не прошла проверку: " + "; ".join(errs))
    return new, {"changes": changes}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("apply")
    a.add_argument("--run", required=True)
    a.add_argument("--history", required=True)
    a.add_argument("--date", help="день записи YYYY-MM-DD (по умолчанию сегодня)")
    a.add_argument("--write", action="store_true")
    rd = sp.add_parser("redate")
    rd.add_argument("--history", required=True)
    rd.add_argument("--month", action="append", required=True)
    rd.add_argument("--date", required=True)
    rd.add_argument("--write", action="store_true")
    b = sp.add_parser("accept")
    b.add_argument("--accepted", required=True)
    b.add_argument("--add", nargs=3, action="append", required=True, metavar=("ID", "CHECK", "REASON"))
    b.add_argument("--kind", choices=sorted(A2_KINDS), help="вид корректировки (только A2)")
    b.add_argument("--date", required=True, help="дата решения YYYY-MM-DD")
    b.add_argument("--write", action="store_true")
    ru = sp.add_parser("rules")
    ru.add_argument("--rules", required=True)
    ru.add_argument("--one-off", nargs=3, action="append", metavar=("ID", "MONTH", "NOTE"))
    ru.add_argument("--one-off-merchant", nargs=2, action="append", metavar=("MERCHANT_ID", "NOTE"),
                    help="место платежа, все траты в котором разовые (точный merchantId)")
    ru.add_argument("--op", nargs=4, action="append", metavar=("ID", "DATE", "ACCOUNT", "AMOUNT"),
                    help="тройка операции правила «разовая» (дата, название счёта, сумма) — без неё сайт не найдёт трату в CSV")
    ru.add_argument("--merchant-name", nargs=2, action="append", metavar=("MERCHANT_ID", "NAME"),
                    help="название места в выгрузке CSV (для --one-off-merchant; можно несколько)")
    ru.add_argument("--regular-big", nargs=2, action="append", metavar=("CATEGORY_ID", "NOTE"))
    ru.add_argument("--remove", action="append", metavar="ID")
    ru.add_argument("--date", required=True, help="дата решения YYYY-MM-DD")
    ru.add_argument("--write", action="store_true")
    s = sp.add_parser("spending")
    s.add_argument("--run", required=True)
    s.add_argument("--spending", required=True)
    s.add_argument("--write", action="store_true")
    fa = sp.add_parser("facts")
    fa.add_argument("--spending", required=True)
    fa.add_argument("--history")
    fa.add_argument("--facts", help="по умолчанию facts.json рядом со spending.json")
    fa.add_argument("--write", action="store_true")
    tp = sp.add_parser("trip")
    tp.add_argument("--run", required=True)
    tp.add_argument("--trips", required=True)
    tp.add_argument("--date", required=True, help="дата расчёта YYYY-MM-DD")
    tp.add_argument("--write", action="store_true")
    v = sp.add_parser("validate")
    v.add_argument("--history")
    v.add_argument("--accepted")
    v.add_argument("--spending")
    v.add_argument("--trips")
    v.add_argument("--rules")
    v.add_argument("--facts")
    args = p.parse_args(argv)
    if args.cmd in ("apply", "redate", "accept", "rules") and args.write:   # вход — находки аудита по MCP (вывод модели)
        hub_settings.require_ai(getattr(args, "history", None) or getattr(args, "accepted", None) or args.rules,
                                f"audit_history.py {args.cmd} --write", "история аудита ZenMoney", zones=("ZenMoney",))
    try:
        if args.cmd == "apply":
            hp = Path(args.history)
            hist, h = read(hp, {"schema": HISTORY_SCHEMA, "records": [], "issues": {}})
            if hp.exists() and validate_history(hist):
                raise Blocking("текущая история битая: " + "; ".join(validate_history(hist)))
            run = json.loads(Path(args.run).read_text(encoding="utf-8"))
            from datetime import date as _d
            new, summary = apply(run, hist, today=args.date or _d.today().isoformat())
            if args.write:
                write_atomic(hp, new, h)
                if (hp.parent / "spending.json").exists():
                    summary["facts"] = refresh_facts(hp.parent, history=new)
            summary["written"] = bool(args.write)
        elif args.cmd == "redate":
            hp = Path(args.history)
            hist, h = read(hp, None)
            new, summary = redate(hist, args.month, args.date)
            if args.write:
                write_atomic(hp, new, h)
            summary["written"] = bool(args.write)
        elif args.cmd == "accept":
            ap = Path(args.accepted)
            acc, h = read(ap, {"schema": ACCEPTED_SCHEMA, "items": []})
            new, summary = accept(acc, args.add, args.date, args.kind)
            if args.write:
                write_atomic(ap, new, h)
            summary["written"] = bool(args.write)
        elif args.cmd == "rules":
            if not (args.one_off or args.one_off_merchant or args.regular_big or args.remove or args.op or args.merchant_name):
                raise Blocking("нечего записывать: нужен --one-off, --one-off-merchant, --regular-big или --remove")
            rp = Path(args.rules)
            cur, h = read(rp, {"schema": RULES_SCHEMA, "one_off": [], "regular_big": []})
            if rp.exists() and validate_rules(cur):
                raise Blocking("текущие правила битые: " + "; ".join(validate_rules(cur)))
            new, summary = apply_rules(cur, args.one_off, args.regular_big, args.remove, args.date, args.one_off_merchant,
                                       args.op, args.merchant_name)
            if args.write:
                write_atomic(rp, new, h)
            summary["written"] = bool(args.write)
        elif args.cmd == "spending":
            spp = Path(args.spending)
            cur, h = read(spp, {"schema": SPENDING_SCHEMA, "months": []})
            if spp.exists() and validate_spending(cur):
                raise Blocking("текущая статистика битая: " + "; ".join(validate_spending(cur)))
            run = json.loads(Path(args.run).read_text(encoding="utf-8"))
            new, summary = apply_spending(run, cur)
            if args.write:
                write_atomic(spp, new, h)
                summary["facts"] = refresh_facts(spp.parent, spending=new)
            summary["written"] = bool(args.write)
        elif args.cmd == "facts":
            spp = Path(args.spending)
            fp = Path(args.facts) if args.facts else spp.parent / "facts.json"
            hist = read(Path(args.history), None)[0] if args.history else None
            new = build_facts(spp.parent, read(spp, {"schema": SPENDING_SCHEMA, "months": []})[0], hist)
            if args.write:
                _, h = read(fp, None)
                write_atomic(fp, new, h)
            summary = {"month": new["month"], "facts": [f["kind"] + (f" · {f['category']}" if f.get("category") else "")
                                                         for f in new["facts"]],
                       "not_enough_data": new["not_enough_data"], "written": bool(args.write)}
        elif args.cmd == "trip":
            tpp = Path(args.trips)
            cur, h = read(tpp, {"schema": TRIPS_SCHEMA, "trips": []})
            if tpp.exists() and validate_trips(cur):
                raise Blocking("текущая статистика поездок битая: " + "; ".join(validate_trips(cur)))
            run = json.loads(Path(args.run).read_text(encoding="utf-8"))
            new, summary = apply_trip(run, cur, args.date)
            if args.write:
                write_atomic(tpp, new, h)
            summary["written"] = bool(args.write)
        else:
            errs = []
            if args.history:
                errs += validate_history(read(Path(args.history), {})[0])
            if args.accepted:
                errs += validate_accepted(read(Path(args.accepted), {})[0])
            if args.spending:
                errs += validate_spending(read(Path(args.spending), {})[0])
            if args.trips:
                errs += validate_trips(read(Path(args.trips), {})[0])
            if args.rules:
                errs += validate_rules(read(Path(args.rules), {})[0])
            if args.facts:
                errs += validate_facts(read(Path(args.facts), {})[0])
            summary = {"ok": not errs, "errors": errs}
            print(json.dumps(summary, ensure_ascii=False, indent=1))
            return 0 if not errs else 1
    except Blocking as e:
        print(json.dumps({"blocking": str(e)}, ensure_ascii=False))
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
