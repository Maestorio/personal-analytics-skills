"""Выгрузка CSV ZenMoney на сайте (этап «Деньги» «меньше ИИ», задача 3.6): полнота, diff операций,
пересчёт месяцев и поездок без Claude, запись по «да» владельца. Устройство — docs/zenmoney/csv-site.md,
политика — docs/zenmoney/csv-checks-research.md §2.

Только stdlib. Расчёт — теми же скриптами скилла zenmoney-analyst (`audit_month`, `month_stats`, `trip_stats`,
`audit_history`) и разбором CSV из `tools/zenmoney_csv_backfill.py`: в контейнере их копии лежат в `pdl/` с
раскладкой репозитория (`pdl/skills/zenmoney-analyst/scripts/`, `pdl/tools/`), в репозитории — на своих местах
(так их находят и тесты). Корень Claude-Memory в hub-notify — только чтение; пишет hub-api через `jobs.save`
(`ZenMoney/audit/*.json`, `ZenMoney/csv/last.csv`, отчёты, кэш курсов `aux/rates-cbr.json`).

Поток: `route_report` (POST /internal/zm-csv-report) → `build_report` → отчёт `reports/<id>.json` и рядом
`reports/<id>-runs.json` (результаты month_stats/trip_stats для записи; в отчёт они не попадают, он уходит на
страницу). `route_apply` (POST /internal/zm-csv-apply) → `check_apply` → `apply_report`.

Ограничение: `jobs.save` не умеет удалять файлы, поэтому после записи `incoming/<id>.csv` остаётся на диске, а в
отчёте появляются `applied_at` и `written`; hub-api стирает записанные выгрузки при следующей загрузке файла
(`/api/zm/csv`). Выгрузка и `last.csv` не больше 8 МБ (MAX_BYTES зоны задач) — иначе стоп до записи.
"""
import csv
import hashlib
import io
import json
import re
import shutil
import sys
import tempfile
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

MSK = timezone(timedelta(hours=3))
HERE = Path(__file__).resolve().parent

# скрипты скилла и разбор CSV: контейнер (pdl/…), иначе репозиторий (tools/hosting/notify → корень на 3 уровня выше)
_ROOTS = [HERE / "pdl"]
if len(HERE.parents) > 2:
    _ROOTS.append(HERE.parents[2])
for _r in _ROOTS:
    for _p in (_r / "skills/zenmoney-analyst/scripts", _r / "tools"):
        if _p.is_dir() and str(_p) not in sys.path:
            sys.path.append(str(_p))

REQUIRED_COLUMNS = ("date", "categoryName", "payee", "comment", "outcomeAccountName", "outcome",
                    "outcomeCurrencyShortTitle", "incomeAccountName", "income", "incomeCurrencyShortTitle",
                    "createdDate", "changedDate")
AUX_REQUIRED = ("accounts.json", "category-flags.json", "trip-ids.json")   # rule-ops.json — необязательный запасной
SCHEMA = "zm-csv-report@1"
RUNS_SCHEMA = "zm-csv-runs@1"
CHECK_MONTHS = 6                      # проверки «на что взглянуть» — не больше стольких последних месяцев к записи
# выключены по бэктесту 2026-11-10 (0 подтверждений при 4–15 срабатываниях; A5 — 38 «это норма» в реестре аудита):
# шум без пользы. Код проверок остаётся в zm_checks; вернуть — убрать отсюда после нового бэктеста.
CHECKS_OFF = frozenset({"A5", "N1", "N5", "P2", "B7", "B6'"})
MAX_SAVE = 8 * 1024 * 1024          # MAX_BYTES hub-api: больше last.csv через /api/job/save не сохранить
DROP_SHARE = 0.01                   # строк меньше прошлой выгрузки больше чем на 1 % → «похоже на фильтр по датам»
STALE_DAYS = 10                     # последняя операция старше — выгрузка, вероятно, устарела (предупреждение)
TRIP = "Путешествия"
ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[0-9a-f]{8}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CSV_DIR = "ZenMoney/csv"
AUDIT_DIR = "ZenMoney/audit"
CHANGE_FIELDS = ("date", "categoryName", "payee", "comment")
RULES_PATH = f"{AUDIT_DIR}/spending-rules.json"
SITE_AUDIT_PATH = f"{AUDIT_DIR}/site-audit.json"
SITE_AUDIT_SCHEMA = "zenmoney-site-audit@1"
SITE_RULE_RE = re.compile(r"^site-[0-9a-f]{12}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
MAX_CANDIDATES = 15                   # кандидатов в разовые на месяц в отчёте


class ApplyRefused(Exception):
    """Запись отклонена (нет отчёта, стопы, нет подтверждения, не тот файл)."""


def _iso(now):
    return now.astimezone(MSK).strftime("%Y-%m-%dT%H:%M:%S+03:00")


def _d(x):
    if isinstance(x, datetime):
        return x.astimezone(MSK).date()
    if isinstance(x, date):
        return x
    return date.fromisoformat(str(x)[:10])


# ─── разбор ──────────────────────────────────────────────────────────────────

def parse_csv(text):
    """Текст выгрузки → список строк-словарей. Разделитель `;`, BOM срезается. Нет обязательной колонки или
    дата строки не ГГГГ-ММ-ДД → ValueError с перечнем."""
    if text.startswith("﻿"):
        text = text[1:]
    rd = csv.DictReader(io.StringIO(text, newline=""), delimiter=";")
    missing = [c for c in REQUIRED_COLUMNS if c not in (rd.fieldnames or [])]
    if missing:
        raise ValueError("в выгрузке нет колонок: " + ", ".join(missing))
    rows = []
    for n, r in enumerate(rd, start=2):
        if not DATE_RE.match(r.get("date") or ""):
            raise ValueError(f"строка {n}: дата «{r.get('date')}» не ГГГГ-ММ-ДД")
        rows.append({k: (v if v is not None else "") for k, v in r.items() if k is not None})
    return rows


def read_csv(path):
    return parse_csv(Path(path).read_bytes().decode("utf-8-sig"))


def _months(a, b):
    y, m = map(int, a.split("-"))
    while f"{y}-{m:02d}" <= b:
        yield f"{y}-{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _prev_month(m):
    y, mo = map(int, m.split("-"))
    return f"{y - 1}-12" if mo == 1 else f"{y}-{mo - 1:02d}"


# ─── полнота ─────────────────────────────────────────────────────────────────

def completeness(rows, prev_rows, today):
    """Проверки до всего остального. → {ok, stops, warnings, prev_rows, months_missing, first, last, open_month}.

    Стоп: пусто; строк меньше прошлой выгрузки больше чем на 1 % или период начинается позже прошлого (фильтр
    по датам иначе выглядит как массовые удаления); месяц, бывший в прошлой выгрузке, пропал целиком. Предупреждение: месяц
    последней операции не закончен (он не пишется; `open_month`), выгрузка старше 10 дней."""
    today = _d(today)
    stops, warnings = [], []
    if not rows:
        return {"ok": False, "stops": ["выгрузка пустая"], "warnings": [], "prev_rows": len(prev_rows or []),
                "months_missing": [], "first": None, "last": None, "open_month": None}
    dates = [r["date"] for r in rows]
    first, last = min(dates), max(dates)
    have = {x[:7] for x in dates}
    # пустой месяц сам по себе законен (2015-07 в истории владельца — ни одной операции); неполнота — месяц,
    # который в прошлой выгрузке был, а в этой пропал целиком
    gaps = [m for m in _months(first[:7], last[:7]) if m not in have]
    prev_have = {r["date"][:7] for r in (prev_rows or [])}
    missing = [m for m in gaps if m in prev_have]
    if missing:
        stops.append("неполная выгрузка: пропали месяцы, бывшие в прошлой выгрузке, — " + ", ".join(missing))
    elif gaps and not prev_rows:
        warnings.append("месяцы без операций: " + ", ".join(gaps[:12]) + (" …" if len(gaps) > 12 else ""))
    if prev_rows:
        if len(rows) < len(prev_rows) * (1 - DROP_SHARE):
            stops.append(f"строк {len(rows)} против {len(prev_rows)} в прошлой выгрузке — "
                         "похоже на фильтр по датам, выгрузите весь период")
        newest, pnewest = (max((r.get("changedDate") or "") for r in x) for x in (rows, prev_rows))
        if newest and pnewest and newest < pnewest:
            stops.append(f"выгрузка старее записанной: последняя правка {newest[:16]}, в записанной — {pnewest[:16]}")
        pfirst = min(r["date"] for r in prev_rows)
        if first[:7] > pfirst[:7]:
            stops.append(f"период начинается с {first}, в прошлой выгрузке — с {pfirst}: похоже на фильтр по датам")
    open_month = None
    if today.isoformat()[:7] <= last[:7]:
        open_month = last[:7]
        warnings.append(f"последняя операция {last} — месяц {open_month} не закончен, к записи не идёт")
    elif (today - date.fromisoformat(last)).days > STALE_DAYS:
        warnings.append(f"последняя операция {last}, сегодня {today.isoformat()}: выгрузка могла устареть")
    return {"ok": not stops, "stops": stops, "warnings": warnings, "prev_rows": len(prev_rows or []),
            "months_missing": missing, "first": first, "last": last, "open_month": open_month}


# ─── diff операций ───────────────────────────────────────────────────────────

def _key(x):
    """Ключ операции как в zenmoney_csv_diff.load: время суток создания, счета, суммы (дата правкой меняется)."""
    return (x["createdDate"][11:], x["outcomeAccountName"], x["outcome"], x["incomeAccountName"], x["income"])


def _index(rows):
    out = {}
    for x in rows:
        out.setdefault(_key(x), x)
    return out


def trip_tags(cat):
    return [p.strip() for p in (cat or "").split(",") if p.strip().startswith(TRIP)]


def _brief(x):
    return {"date": x["date"], "amount": x["outcome"] or x["income"],
            "account": x["outcomeAccountName"] or x["incomeAccountName"],
            "payee": x["payee"], "category": x["categoryName"]}


def op_diff(rows, prev_rows):
    """Что изменилось между выгрузками. → {added, deleted, changed, lost_trip_tags[], by_month{}, samples{},
    deleted_trip_tags{}}. `changed` — тот же ключ, другая дата/категория/место/комментарий. Без прошлой
    выгрузки — нули (сравнивать не с чем)."""
    out = {"added": 0, "deleted": 0, "changed": 0, "lost_trip_tags": [], "by_month": {},
           "samples": {"deleted": [], "changed": []}, "deleted_trip_tags": {}}
    if prev_rows is None:
        return out
    new, old = _index(rows), _index(prev_rows)
    by = {}

    def bump(month, what):
        by.setdefault(month, {"added": 0, "deleted": 0, "changed": 0})[what] += 1

    for k in new.keys() - old.keys():
        out["added"] += 1
        bump(new[k]["date"][:7], "added")
    deleted = []
    for k in old.keys() - new.keys():
        x = old[k]
        out["deleted"] += 1
        bump(x["date"][:7], "deleted")
        deleted.append(x)
        for t in trip_tags(x["categoryName"]):
            out["deleted_trip_tags"][t] = out["deleted_trip_tags"].get(t, 0) + 1
    changed = []
    for k in new.keys() & old.keys():
        x, y = old[k], new[k]
        if tuple(x[f] for f in CHANGE_FIELDS) != tuple(y[f] for f in CHANGE_FIELDS):
            out["changed"] += 1
            for m in {x["date"][:7], y["date"][:7]}:
                bump(m, "changed")
            changed.append((x, y))
        lost = [t for t in trip_tags(x["categoryName"]) if t not in trip_tags(y["categoryName"])]
        if lost:
            out["lost_trip_tags"].append({**_brief(y), "tag": ", ".join(lost)})
    out["lost_trip_tags"].sort(key=lambda r: (r["date"], r["amount"]))
    out["by_month"] = dict(sorted(by.items()))
    out["samples"]["deleted"] = [_brief(x) for x in sorted(deleted, key=lambda r: r["date"])[:20]]
    out["samples"]["changed"] = [
        {**_brief(y), "was": {f: x[f] for f in CHANGE_FIELDS if x[f] != y[f]},
         "now": {f: y[f] for f in CHANGE_FIELDS if x[f] != y[f]}}
        for x, y in sorted(changed, key=lambda p: p[1]["date"])[:20]]
    return out


# ─── пересчёт ────────────────────────────────────────────────────────────────

def _scripts():
    """Модули расчёта (ленивый импорт: без них hub-notify стартует, а пересчёт отвечает понятной ошибкой)."""
    import audit_history as AH
    import audit_month as AM
    import month_stats as MS
    import trip_stats as TS
    import zenmoney_csv_backfill as B
    import zenmoney_payee_map as PM
    return AH, AM, MS, TS, B, PM


def _jload(path, default):
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else default


def match_by_record(rule, written, ops):
    """Операции выгрузки, подходящие правилу «разовая» по записи его месяца в spending.json: место и сумма
    разовой траты с той же заметкой (ровно одна запись); пусто — не нашлось. `written` — {месяц: запись}."""
    rec = [i for i in (written.get(rule.get("month")) or {}).get("one_off") or [] if i.get("note") == rule.get("note")]
    if len(rec) != 1:
        return []
    return [o for o in ops if o["date"][:7] == rule["month"] and o.get("expense") and not o.get("income")
            and o.get("merchantId") == "p:" + str(rec[0].get("name"))
            and abs(float(o["expense"]["amount"]) - float(rec[0].get("rub") or 0)) <= 1.0]


def site_rule_id(date_, account, amount):
    """ID правила, заведённого с сайта: sha1(дата|счёт|сумма)[:12]; сумма — с двумя знаками, как в тройке op."""
    raw = f"{date_}|{account}|{float(amount):.2f}"
    return "site-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _amt(x):
    x = float(x)
    return int(x) if x == int(x) else x


def month_candidates(run, by_id):
    """Крупные обычные траты месяца (outlier_candidates) → [{date, account, amount, rub, category, payee, comment}]
    с тройкой операции из CSV (счёт и сумма в валюте счёта), по которой сайт заводит правило «разовая»."""
    out = []
    for it in ((run.get("outlier_candidates") or {}).get("items") or [])[:MAX_CANDIDATES]:
        op = by_id.get(it["id"])
        if not op:
            continue
        d_, acc, amount = op["_key"]
        out.append({"date": d_, "account": acc, "amount": _amt(amount), "rub": it["rub"], "category": it["category"],
                    "payee": it.get("merchant") or "", "comment": it.get("comment") or ""})
    return out


def check_aux(aux_dir):
    missing = [n for n in AUX_REQUIRED if not (aux_dir and (Path(aux_dir) / n).is_file())]
    return not missing, missing


def new_trip(ctx, TS, cid, name, tids, clean):
    """Поездка с тегом, но без ID в trip-ids.json → кандидат на «Добавить поездку»: число операций, первая и
    последняя дата с тегом, предложенный период (trip_stats.infer_period: самая плотная серия трат «на месте»)."""
    sel = [o for o in clean if o["id"] in set(tids)]
    first, last = min(o["date"] for o in sel), max(o["date"] for o in sel)
    start, end = first, last
    try:
        ctx.missing = set()
        per = (TS.report(ctx, cid, None).get("period") or {})
        if per.get("start") and per.get("end"):
            start, end = per["start"], per["end"]
    except Exception:  # noqa: BLE001 — предложение дат не обязано получиться (нет курса и т. п.): берём первую и последнюю
        pass
    return {"name": name, "ops": len(sel), "first": first, "last": last, "start": start, "end": end}


def recompute(csv_path, aux_dir, audit_dir, prev_csv_path, today, diff=None, comp=None, cache_save=None):
    """Месяцы и поездки из выгрузки теми же скриптами скилла. → {months[], trips[], aux{ok, missing,
    payee_unmapped}, stops[], warnings[], unavailable}.

    months — все с первой операции по последний законченный; на месяц {month, action add|replace|same,
    explained, explained_by, changes[], ops_changed_after, run}. «Объяснимое» расхождение: у месяца есть
    добавленные/изменённые (по diff с прошлой выгрузкой, без неё — по changedDate позже as_of записи) или
    удалённые операции, либо расхождение целиком из разовых по правилу новее записи; иначе — стоп.
    Нет aux или курсов ЦБ → months/trips пустые, `unavailable` с причиной. `cache_save(text)` — сохранить
    дополненный кэш курсов (`aux/rates-cbr.json`; том hub-notify на чтение)."""
    today = _d(today)
    out = {"months": [], "trips": [], "aux": {"ok": False, "missing": [], "payee_unmapped": 0},
           "stops": [], "warnings": [], "unavailable": None, "checks": [], "checks_months": [], "new_trips": []}
    ok, missing = check_aux(aux_dir)
    out["aux"]["missing"] = missing
    if not ok:
        out["unavailable"] = "нет вспомогательных файлов: " + ", ".join(missing)
        return out
    if not (Path(aux_dir) / "rates-zm.json").is_file():
        out["warnings"].append("нет aux/rates-zm.json — курсов валют, которых нет у ЦБ; месяцы и поездки с такими "
                               "валютами не посчитаются")
    rows = read_csv(csv_path)
    prev_rows = read_csv(prev_csv_path) if prev_csv_path else None
    comp = comp or completeness(rows, prev_rows, today)
    diff = diff or op_diff(rows, prev_rows)
    if comp["stops"]:
        out["unavailable"] = "выгрузка не прошла проверку полноты — пересчёт не выполнялся"
        out["aux"]["ok"] = True
        return out
    AH, AM, MS, TS, B, PM = _scripts()
    aux_dir, audit_dir = Path(aux_dir), Path(audit_dir)
    with tempfile.TemporaryDirectory(prefix="zm-csv-") as tmp:
        work = Path(tmp)
        for f in aux_dir.glob("*.json"):
            shutil.copy2(f, work / f.name)
        rules_src = audit_dir / "spending-rules.json"
        (work / "spending-rules-src.json").write_text(rules_src.read_text(encoding="utf-8") if rules_src.is_file()
                                                      else "{}", encoding="utf-8")
        pmap = PM.load(work / "payee-map.json")
        ops, refs, notes = B.build(csv_path, work, pmap)
        for n, c in notes.items():
            out["warnings"].append(f"{n}: {c}")
        if pmap:
            to = ((pmap.meta.get("pages") or {}).get("to")) or ""
            out["aux"]["payee_unmapped"] = sum(1 for o in ops if o.get("merchantId") and o["date"] > to)
        else:
            out["aux"]["payee_unmapped"] = sum(1 for o in ops if o.get("merchantId"))
        if out["aux"]["payee_unmapped"]:
            out["warnings"].append(f"мест без словаря: {out['aux']['payee_unmapped']} — на странице тексты банка")
        ro = work / "rule-ops.json"
        rule_ops = json.loads(ro.read_text(encoding="utf-8")) if ro.is_file() else None
        rules, miss = B.rules_for_csv(work / "spending-rules-src.json", rule_ops, ops,
                                      pmap.meta["by_text"] if pmap else None)
        sp = _jload(audit_dir / "spending.json", {"months": []})
        written = {m["month"]: m for m in sp.get("months", [])}
        # правило «разовая» без тройки `op` и без записи в rule-ops.json: операцию находим по
        # записи месяца — место и сумма разовой траты из spending.json; ровно одна такая трата в месяце → правило её
        src_rules = _jload(work / "spending-rules-src.json", {})
        have = {(x.get("month"), x.get("note")) for x in rules["one_off"]}
        found = set()
        for x in src_rules.get("one_off", []):
            if (x.get("month"), x.get("note")) in have or x.get("month") not in written:
                continue
            hits = [o["id"] for o in match_by_record(x, written, ops)]
            if len(hits) == 1:
                rules["one_off"].append(dict(x, id=hits[0]))
                found.add(x["id"])
                out["warnings"].append(f"разовая «{x.get('note')}» ({x['month']}) найдена по записи месяца — "
                                       "у правила нет тройки операции (op) и записи в rule-ops.json")
        for m in miss:
            if not any(m.startswith(i) for i in found):
                out["warnings"].append(f"правило не найдено в выгрузке: {m}")
        rule_dates = {x["note"]: x["date"] for x in rules["one_off"] + rules["one_off_merchants"] if x.get("date")}
        rules_path = work / "_rules-csv.json"
        rules_path.write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")
        tr_written = {t["trip"]["id"]: t for t in _jload(audit_dir / "trips.json", {"trips": []}).get("trips", [])}
        tr_by_name = {t["trip"]["name"]: t for t in tr_written.values()}
        site_rules = [x for x in src_rules.get("one_off", []) if SITE_RULE_RE.match(str(x.get("id")))]
        by_id = {o["id"]: o for o in ops}

        first_m, last_op_m = comp["first"][:7], comp["last"][:7]
        last_closed = _prev_month(comp["open_month"]) if comp["open_month"] else last_op_m
        # курсы — по всем месяцам и по месяцу последней операции (поездка может ещё идти)
        cache_path = work / "rates-cbr.json"
        before = cache_path.read_bytes() if cache_path.is_file() else b""
        failed = {}
        orig_cbr = B.cbr_day

        def cbr_logged(d):
            try:
                return orig_cbr(d)
            except (OSError, ValueError) as e:        # URLError/HTTPError/таймаут — OSError; разбор XML — ValueError
                failed["day"], failed["err"] = d, f"{type(e).__name__}: {e}"[:120]
                raise
        B.cbr_day = cbr_logged
        try:
            rates, _fetched = B.rates_for(ops, refs, cache_path, first_m, last_op_m)
        except (OSError, ValueError, KeyError, IndexError):
            out["unavailable"] = f"нет курсов за {failed.get('day', '?')}: {failed.get('err', 'ЦБ не ответил')}"
            out["stops"].append(out["unavailable"])
            return out
        finally:
            B.cbr_day = orig_cbr
        if cache_save and cache_path.is_file() and cache_path.read_bytes() != before:
            cache_save(cache_path.read_text(encoding="utf-8"))

        # признак «после записи»: с прошлой выгрузкой — строка новая или изменённая; без неё — changedDate позже записи
        if prev_rows is not None:
            prev = Counter(tuple(r[k] for k in B.ROW_KEYS) for r in prev_rows)
            for o in ops:
                o["_new"] = prev[o["_row"]] <= 0
                prev[o["_row"]] -= 1
        late_ids = {o["id"] for o in ops if o.get("_new")}
        changed_at = {o["id"]: o["_changed"][:10] for o in ops}
        clean = [{k: v for k, v in o.items() if not k.startswith("_")} for o in ops]
        cfg = MS.load_rules(str(rules_path), {}, clean, refs)
        ctx = AM.Ctx(clean, refs, None, rates, cfg, set())

        def late_count(pred_ids, as_of):
            if prev_rows is not None:
                return sum(1 for i in pred_ids if i in late_ids)
            return sum(1 for i in pred_ids if changed_at.get(i, "") > (as_of or "9999"))

        # ── месяцы ── история ведётся с первого записанного месяца: более ранние операции выгрузки (у владельца —
        # с 2011 года при истории с 2020-01) не добавляются сами; расширить историю назад — рецепт csv-recompute.md
        start_m = max(first_m, min(written)) if written else first_m
        if start_m > first_m:
            out["skipped_before"] = start_m
            out["warnings"].append(f"история ведётся с {start_m}: более ранние месяцы выгрузки не пересчитываются")
        for month in _months(start_m, last_closed):
            start, end = AM.month_bounds(month, 1)
            ctx.missing = set()
            cur = MS.compute(ctx, month, start, end, 0)
            if not cur["totals"]["operations"]:
                continue
            run = {"schema": "zenmoney-month-stats-run@1", "month": month,
                   "period": [start.isoformat(), end.isoformat()], "as_of": today.isoformat(),
                   "closed": today > end, "main_currency": "RUB", **cur, "compare": None,
                   "coverage": {"unconverted": dict(Counter(i for _o, _a, i in ctx.missing)), "history": "csv-site"}}
            if run["coverage"]["unconverted"]:
                # операции без курса дают 0 ₽ — итог месяца неверен, писать нельзя (первая загрузка владельца 2026-11-10:
                # на NAS не было rates-zm.json, 20 месяцев «объяснимо» расходились на суммы поездок в MKD/GEL/ARS/LAK)
                out["stops"].append(f"{month}: операции без курса {run['coverage']['unconverted']} — нет курсов этих валют "
                                    "(aux/rates-zm.json: валюты, которых нет у ЦБ)")
            old = written.get(month)
            ids = [o["id"] for o in clean if o["date"][:7] == month]
            deleted = (diff["by_month"].get(month) or {}).get("deleted", 0)
            ent = {"month": month, "action": "add", "explained": True, "explained_by": None, "changes": [],
                   "ops_changed_after": 0, "run": run}
            ent["site_rules"] = [{"id": x["id"], "note": x.get("note") or "", **(x.get("op") or {})}
                                 for x in site_rules if x.get("month") == month]
            if old:
                ent["changes"] = B.diff_month(cur, old)
                ent["ops_changed_after"] = late_count(ids, old.get("as_of")) + deleted
                ent["action"] = "replace" if ent["changes"] else "same"
                if ent["changes"]:
                    if ent["ops_changed_after"]:
                        ent["explained_by"] = "ops"
                    else:
                        new_rules = [x["name"] for x in cur["one_off"]
                                     if x["note"] in rule_dates and rule_dates[x["note"]] > old["as_of"]]
                        if new_rules:       # прежняя запись + разовые по правилу новее неё: прочее обязано сойтись
                            shifted = json.loads(json.dumps(old))
                            for x in cur["one_off"]:
                                if x["name"] in new_rules:
                                    shifted["totals"]["expense_regular_rub"] -= x["rub"]
                                    shifted["totals"]["expense_one_off_rub"] += x["rub"]
                                    for c in shifted["categories_regular"]:
                                        if c["name"] == x["category"]:
                                            c["rub"] -= x["rub"]
                            if not B.diff_month(cur, shifted):
                                ent["explained_by"] = "rules"
                    ent["explained"] = ent["explained_by"] is not None
                    if not ent["explained"]:
                        out["stops"].append(f"необъяснимое расхождение {month}")
            ent["candidates"] = month_candidates(run, by_id) if ent["action"] in ("add", "replace") else []
            out["months"].append(ent)

        # ── поездки ──
        ti = json.loads((work / "trip-ids.json").read_text(encoding="utf-8"))
        # ── «на что взглянуть»: проверки месяцев, идущих в запись (zm_checks; не стопы — классы по бэктесту) ──
        try:
            import zm_checks
            chk_months = [m["month"] for m in out["months"] if m["action"] in ("add", "replace")][-CHECK_MONTHS:]
            if chk_months:
                hist = {"known_places": set((pmap.meta.get("by_text") or {}).values()) if pmap else set(),
                        "trip_dates": ti.get("dates") or {}}
                meta = {o["id"]: (o.get("_created", ""), o.get("_changed", "")) for o in ops}
                out["checks_months"] = chk_months
                found = zm_checks.run_checks(clean, refs, ctx, hist, chk_months, {"today": today}, meta)
                out["checks"] = [c for c in found if c["id"] not in CHECKS_OFF]
        except Exception as e:  # noqa: BLE001 — подсказки не должны ронять отчёт и запись
            out["warnings"].append(f"проверки «на что взглянуть» не выполнены: {type(e).__name__}: {e}"[:200])
        by_name = {c["name"]: cid for cid, c in ctx.cats.items() if c["name"].startswith("#")}
        ctx.cfg = dict(ctx.cfg, trip_dates={by_name[n]: d for n, d in (ti.get("dates") or {}).items() if n in by_name})
        for name, cid in sorted(by_name.items(), key=lambda kv: kv[0][-2:] + kv[0]):
            if name in (ti.get("skip") or {}):
                continue
            real = (ti.get("ids") or {}).get(name)
            tids = [o["id"] for o in clean if o.get("categoryId") == cid or cid in (o.get("tagIds") or [])]
            if not tids:
                continue
            if max(o["date"] for o in clean if o["id"] in set(tids))[:7] < start_m:
                continue            # поездка целиком до начала истории — как и месяцы, не пересчитывается и не шумит
            if not real:
                out["warnings"].append(f"поездка {name}: нет ID в trip-ids.json — пропущена")
                out.setdefault("new_trips", []).append(new_trip(ctx, TS, cid, name, tids, clean))
                continue
            ctx.missing = set()
            r = TS.report(ctx, cid, None)
            r["trip"] = {"id": real, "name": name}
            w = tr_written.get(real) or (tr_by_name.get(name) if real.startswith("site:") else None)
            ent = {"name": name, "id": real, "action": "add", "changes": [], "explained": True, "run": r}
            unc = (r.get("coverage") or {}).get("unconverted")
            if w:
                a, b = r["totals"]["spent_rub"], w["totals"]["spent_rub"]
                if not B.close(a, b):
                    ent["changes"].append(f"spent_rub: было {b:,.0f}, CSV {a:,.0f}")
                ent["action"] = "replace" if ent["changes"] else "same"
                if ent["changes"]:
                    late = late_count(tids, w.get("as_of"))
                    gone = sum(v for t, v in diff["deleted_trip_tags"].items() if t.endswith(name))
                    ent["explained"] = bool(late or gone)
                    if not ent["explained"]:
                        out["stops"].append(f"необъяснимое расхождение поездки {name}")
            if unc and ent["action"] != "same":
                out["stops"].append(f"поездка {name}: операции без курса {unc}")
            out["trips"].append(ent)
    out["aux"]["ok"] = True
    return out


# ─── отчёт ───────────────────────────────────────────────────────────────────

def build_report(id_, csv_path, aux_dir, audit_dir, prev_csv_path, today, now=None, cache_save=None):
    """→ (отчёт zm-csv-report@1, runs). Отчёт уходит на страницу и на диск; runs — месяцы/поездки для записи
    (`reports/<id>-runs.json`), в отчёт их класть нельзя: это сотни килобайт на месяц."""
    raw = Path(csv_path).read_bytes()
    rows = parse_csv(raw.decode("utf-8-sig"))
    prev_rows = read_csv(prev_csv_path) if prev_csv_path else None
    comp = completeness(rows, prev_rows, today)
    diff = op_diff(rows, prev_rows)
    stops = list(comp["stops"])
    if len(raw) > MAX_SAVE:
        stops.append(f"выгрузка {len(raw) // 1024 // 1024} МБ больше 8 МБ — last.csv на сайте не сохранить")
    if diff["lost_trip_tags"]:
        stops.append(f"потерян тег поездки у {len(diff['lost_trip_tags'])} операций — верните его в ZenMoney")
    rec = recompute(csv_path, aux_dir, audit_dir, prev_csv_path, today, diff=diff, comp=comp, cache_save=cache_save)
    stops += rec["stops"]
    runs = {"schema": RUNS_SCHEMA, "id": id_,
            "months": {m["month"]: m["run"] for m in rec["months"] if m["action"] in ("add", "replace")},
            "trips": {t["name"]: t["run"] for t in rec["trips"] if t["action"] in ("add", "replace")}}
    report = {
        "schema": SCHEMA, "id": id_, "sha256": hashlib.sha256(raw).hexdigest(),
        "built_at": _iso(now or datetime.now(MSK)), "as_of": _d(today).isoformat(),
        "rows": len(rows), "first": comp["first"], "last": comp["last"],
        "completeness": {k: comp[k] for k in ("ok", "stops", "warnings", "prev_rows", "months_missing")},
        "diff": {"prev": "last.csv" if prev_rows is not None else None,
                 **{k: diff[k] for k in ("added", "deleted", "changed", "lost_trip_tags", "by_month", "samples")}},
        "months": [{k: v for k, v in m.items() if k != "run"} for m in rec["months"]],
        "trips": [{k: v for k, v in t.items() if k != "run"} for t in rec["trips"]],
        "stops": stops, "warnings": rec["warnings"], "unavailable": rec["unavailable"], "aux": rec["aux"],
        "checks": rec.get("checks") or [], "checks_months": rec.get("checks_months") or [],
        "new_trips": rec.get("new_trips") or [],
    }
    return report, runs


def _jdump(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def check_apply(report, file_sha256, confirm):
    """→ текст отказа или None. Запись только по отчёту без стопов, с «да» и тем же файлом, что в отчёте."""
    if not report:
        return "нет отчёта — сначала постройте его"
    if report.get("applied_at"):
        return f"выгрузка уже записана {report['applied_at']}"
    if report.get("stops"):
        return "в отчёте есть стопы: " + "; ".join(report["stops"][:5])
    if report.get("unavailable"):
        return "нечего записывать: " + str(report["unavailable"])
    if confirm is not True:
        return "нужно явное подтверждение (confirm: true)"
    if file_sha256 != report.get("sha256"):
        return "файл выгрузки не совпадает с отчётом (sha256) — постройте отчёт заново"
    return None


def _facts(read, save, spending):
    """Эквивалент audit_history.refresh_facts через read/save: ошибка фактов запись месяцев не отменяет."""
    AH = _scripts()[0]
    try:
        hist_raw, _ = read(f"{AUDIT_DIR}/history.json")
        new = AH.hq.compute_facts(spending, json.loads(hist_raw) if hist_raw else None)
        errs = AH.validate_facts(new)
        if errs:
            raise AH.Blocking("; ".join(errs))
        save(f"{AUDIT_DIR}/facts.json", json.dumps(new, ensure_ascii=False, indent=1) + "\n")
        return {"written": True, "facts": len(new["facts"])}
    except Exception as e:  # noqa: BLE001
        return {"written": False, "error": f"{type(e).__name__}: {e}"[:200]}


def validate_site_audit(obj):
    """Форма site-audit.json (`zenmoney-site-audit@1`): только агрегаты — id проверки, класс, число, текст проверки;
    ни примеров, ни названий, ни сумм. → список ошибок."""
    errs = []
    if not isinstance(obj, dict) or obj.get("schema") != SITE_AUDIT_SCHEMA:
        return [f"schema ≠ {SITE_AUDIT_SCHEMA}"]
    if set(obj) != {"schema", "updated", "months"}:
        errs.append(f"поля файла: {sorted(obj)}")
    if not DATE_RE.match(str(obj.get("updated", ""))):
        errs.append("updated — не дата")
    months = obj.get("months")
    if not isinstance(months, dict):
        return errs + ["months — не словарь"]
    for m, e in months.items():
        if not MONTH_RE.match(str(m)) or not isinstance(e, dict) or set(e) != {"as_of", "export_id", "checks", "stops_overridden"}:
            errs.append(f"{m}: нужны as_of, export_id, checks, stops_overridden")
            continue
        if not DATE_RE.match(str(e["as_of"])) or not ID_RE.match(str(e["export_id"])):
            errs.append(f"{m}: as_of — дата, export_id — id выгрузки")
        if not (isinstance(e["stops_overridden"], list) and all(isinstance(x, str) for x in e["stops_overridden"])):
            errs.append(f"{m}: stops_overridden — список строк")
        for c in e["checks"] if isinstance(e["checks"], list) else [None]:
            if not (isinstance(c, dict) and set(c) == {"id", "cls", "count", "text"} and isinstance(c["id"], str)
                    and isinstance(c["cls"], str) and isinstance(c["text"], str)
                    and isinstance(c["count"], int) and not isinstance(c["count"], bool)):
                errs.append(f"{m}: проверка — только id, cls, count (число), text")
                break
    return errs


def site_audit_update(cur, report, written_months):
    """Записи месяцев, у которых сайт гонял проверки (checks_months отчёта) → новый site-audit.json."""
    months = dict((cur or {}).get("months") or {})
    for m in written_months:
        if m not in (report.get("checks_months") or []):
            continue            # проверки не гонялись — «аудит сайта» месяцу не ставим
        months[m] = {"as_of": report["as_of"], "export_id": report["id"],
                     "checks": [{"id": c["id"], "cls": c["cls"], "count": c["count"], "text": c["text"]}
                                for c in report.get("checks") or [] if c.get("month") == m],
                     "stops_overridden": []}
    return {"schema": SITE_AUDIT_SCHEMA, "updated": report["as_of"], "months": dict(sorted(months.items()))}


def _site_audit(read, save, report, written_months):
    """Аудит сайта по записанным месяцам; ошибка месяцев не отменяет (страница без него считает месяц незакрытым)."""
    try:
        done = [m for m in written_months if m in (report.get("checks_months") or [])]
        if not done:
            return {"written": False, "months": 0}
        raw, _ = read(SITE_AUDIT_PATH)
        new = site_audit_update(json.loads(raw) if raw else None, report, written_months)
        errs = validate_site_audit(new)
        if errs:
            raise ValueError("; ".join(errs))
        save(SITE_AUDIT_PATH, json.dumps(new, ensure_ascii=False, indent=1) + "\n")
        return {"written": True, "months": len(done)}
    except Exception as e:  # noqa: BLE001
        return {"written": False, "error": f"{type(e).__name__}: {e}"[:200]}


def apply_report(report, runs, read, save, now):
    """Запись месяцев и поездок отчёта. read(path) → (текст|None, хэш|None); save(path, текст) → хэш.
    Порядок: spending.json → trips.json → facts.json → last.csv := incoming → отчёт (`applied_at`).
    Пишутся только месяцы/поездки с action add|replace. incoming не удаляется (см. докстринг модуля).
    Сбой на середине — отчёт без applied_at, повторная запись идемпотентна (замена тех же записей)."""
    err = check_apply(report, report.get("sha256"), True)
    if err:
        raise ApplyRefused(err)
    AH = _scripts()[0]
    as_of = report["as_of"]
    versions, written = [], {"months": [], "trips": []}

    def put(path, text):
        old, _ = read(path)
        save(path, text)
        if old is not None:
            versions.append(path)

    raw, _ = read(f"{AUDIT_DIR}/spending.json")
    sp = json.loads(raw) if raw else {"schema": AH.SPENDING_SCHEMA, "months": []}
    for m in report["months"]:
        if m["action"] in ("add", "replace"):
            sp, _info = AH.apply_spending(runs["months"][m["month"]], sp)
            written["months"].append(m["month"])
    if written["months"]:
        put(f"{AUDIT_DIR}/spending.json", json.dumps(sp, ensure_ascii=False, indent=1) + "\n")
    raw, _ = read(f"{AUDIT_DIR}/trips.json")
    tr = json.loads(raw) if raw else {"schema": AH.TRIPS_SCHEMA, "trips": []}
    for t in report["trips"]:
        if t["action"] in ("add", "replace"):
            tr, _info = AH.apply_trip(runs["trips"][t["name"]], tr, as_of)
            written["trips"].append(t["name"])
    if written["trips"]:
        put(f"{AUDIT_DIR}/trips.json", json.dumps(tr, ensure_ascii=False, indent=1) + "\n")
    facts = _facts(read, save, sp) if written["months"] else None
    site_audit = _site_audit(read, save, report, written["months"]) if written["months"] else None
    inc, _ = read(f"{CSV_DIR}/incoming/{report['id']}.csv")
    if inc is None:
        raise ApplyRefused("файл выгрузки пропал из incoming")
    put(f"{CSV_DIR}/last.csv", inc)
    report = dict(report, applied_at=_iso(now), written=written)
    save(f"{CSV_DIR}/reports/{report['id']}.json", json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    return {"written": written, "versions": versions, "facts": facts, "site_audit": site_audit}


# ─── маршруты hub-notify (без HTTP — тестируются напрямую) ───────────────────

def _id_ok(body):
    i = (body or {}).get("id")
    return i if isinstance(i, str) and ID_RE.match(i) else None


def route_report(root, body, now, read, save, log=None):
    """POST /internal/zm-csv-report {id} → (код, тело). root — корень Claude-Memory (только чтение)."""
    t0 = time.monotonic()
    i = _id_ok(body)
    if not i:
        return 400, {"error": "bad id"}
    root = Path(root)
    csv_path = root / CSV_DIR / "incoming" / f"{i}.csv"
    if not csv_path.is_file():
        return 404, {"error": "нет такой выгрузки", "id": i}
    old = _jload(root / CSV_DIR / "reports" / f"{i}.json", None)
    if old and old.get("applied_at"):
        return 409, {"error": "выгрузка уже записана", "applied_at": old["applied_at"]}
    last = root / CSV_DIR / "last.csv"
    try:
        report, runs = build_report(
            i, csv_path, root / CSV_DIR / "aux", root / AUDIT_DIR, last if last.is_file() else None,
            _d(now), now, cache_save=lambda text: save(f"{CSV_DIR}/aux/rates-cbr.json", text))
        save(f"{CSV_DIR}/reports/{i}.json", json.dumps(report, ensure_ascii=False, indent=1) + "\n")
        save(f"{CSV_DIR}/reports/{i}-runs.json", _jdump(runs))
    except ValueError as e:
        if log:
            log("zm-csv", "error", t0, op="report", id=i, error=str(e)[:200])
        return 400, {"error": "bad csv", "detail": str(e)[:300]}
    except Exception as e:  # noqa: BLE001
        if log:
            log("zm-csv", "error", t0, op="report", id=i, error=f"{type(e).__name__}: {e}"[:300])
        return 500, {"error": f"{type(e).__name__}: {str(e)[:300]}"}
    if log:
        log("zm-csv", "ok", t0, op="report", id=i, rows=report["rows"], stops=len(report["stops"]),
            months=len(report["months"]), trips=len(report["trips"]))
    return 200, report


def route_apply(root, body, now, read, save, log=None):
    """POST /internal/zm-csv-apply {id, confirm:true} → (код, тело). 409 — нет отчёта, стопы, нет confirm, файл ≠ отчёту."""
    t0 = time.monotonic()
    i = _id_ok(body)
    if not i:
        return 400, {"error": "bad id"}
    root = Path(root)
    report = _jload(root / CSV_DIR / "reports" / f"{i}.json", None)
    csv_path = root / CSV_DIR / "incoming" / f"{i}.csv"
    sha = hashlib.sha256(csv_path.read_bytes()).hexdigest() if csv_path.is_file() else None
    err = check_apply(report, sha, (body or {}).get("confirm"))
    if err:
        if log:
            log("zm-csv", "refused", t0, op="apply", id=i, reason=err[:200])
        return 409, {"error": err}
    runs = _jload(root / CSV_DIR / "reports" / f"{i}-runs.json", None)
    if not runs or runs.get("id") != i:
        return 409, {"error": "нет файла расчёта месяцев (runs) — постройте отчёт заново"}
    try:
        res = apply_report(report, runs, read, save, now)
    except ApplyRefused as e:
        return 409, {"error": str(e)}
    except Exception as e:  # noqa: BLE001
        if log:
            log("zm-csv", "error", t0, op="apply", id=i, error=f"{type(e).__name__}: {e}"[:300])
        return 502, {"error": f"{type(e).__name__}: {str(e)[:300]}"}
    if log:
        log("zm-csv", "ok", t0, op="apply", id=i, months=len(res["written"]["months"]),
            trips=len(res["written"]["trips"]))
    return 200, res


# ─── правка с сайта: «Разовая» и «Добавить поездку» ──────────────────────────

def _report_for_edit(root, body):
    """→ (id, отчёт, None) или (None, None, (код, тело)). Правки идут по отчёту, который ещё не записан."""
    i = _id_ok(body)
    if not i:
        return None, None, (400, {"error": "bad id"})
    rep = _jload(Path(root) / CSV_DIR / "reports" / f"{i}.json", None)
    if not rep:
        return None, None, (409, {"error": "нет отчёта — сначала постройте его"})
    if rep.get("applied_at"):
        return None, None, (409, {"error": f"выгрузка уже записана {rep['applied_at']}"})
    return i, rep, None


def route_rule(root, body, now, read, save, log=None):
    """POST /internal/zm-rule {id, month, date, account, amount, payee?, note} — «Это разовая»; с `remove: true` —
    снять отметку (`rule_id` или та же тройка; только правила с id `site-…`). Правило `one_off` с тройкой `op`
    пишется в ZenMoney/audit/spending-rules.json через audit_history.apply_rules; отчёт пересчитывается и
    возвращается (с полем `rule`). 403 — чужое правило или трата не из кандидатов отчёта; 409 — нет отчёта, уже записан."""
    t0 = time.monotonic()
    body = body or {}
    i, rep, err = _report_for_edit(root, body)
    if err:
        return err
    AH = _scripts()[0]
    remove = body.get("remove") is True
    if remove:
        rid = body.get("rule_id")
        if rid is None and all(k in body for k in ("date", "account", "amount")):
            try:
                rid = site_rule_id(body["date"], body["account"], body["amount"])
            except (TypeError, ValueError):
                return 400, {"error": "amount — не число"}
        if not isinstance(rid, str) or not SITE_RULE_RE.match(rid):
            return 403, {"error": "снять можно только отметку, поставленную с сайта (id site-…)"}
        args = dict(one_off=None, remove=[rid], ops=None)
    else:
        month, date_, account, note = (body.get(k) for k in ("month", "date", "account", "note"))
        amount = body.get("amount")
        if not (isinstance(month, str) and MONTH_RE.match(month) and isinstance(date_, str) and DATE_RE.match(date_)
                and date_[:7] == month and isinstance(account, str) and account.strip()
                and isinstance(amount, (int, float)) and not isinstance(amount, bool)):
            return 400, {"error": "нужны month, date (того же месяца), account, amount"}
        if not (isinstance(note, str) and note.strip()):
            return 400, {"error": "note обязателен: что это за трата"}
        if len(note) > 200:
            return 400, {"error": "note длиннее 200 знаков"}
        mrow = next((m for m in rep.get("months") or [] if m["month"] == month), None)
        if not any(c["date"] == date_ and c["account"] == account and abs(float(c["amount"]) - float(amount)) <= 0.01
                   for c in (mrow or {}).get("candidates") or []):
            return 403, {"error": "такой траты нет среди кандидатов отчёта"}
        rid = site_rule_id(date_, account, amount)
        args = dict(one_off=[(rid, month, note.strip())], remove=None, ops=[(rid, date_, account, amount)])
    raw, _ = read(RULES_PATH)
    today = _d(now).isoformat()
    cur = json.loads(raw) if raw else {"schema": AH.RULES_SCHEMA, "updated": today, "one_off": [],
                                       "one_off_merchants": [], "regular_big": []}
    try:
        new, _info = AH.apply_rules(cur, args["one_off"], [], args["remove"], today, ops=args["ops"])
    except AH.Blocking as e:
        return 409, {"error": str(e)[:300]}
    try:
        save(RULES_PATH, json.dumps(new, ensure_ascii=False, indent=1) + "\n")
    except Exception as e:  # noqa: BLE001
        return 502, {"error": f"{type(e).__name__}: {str(e)[:300]}"}
    if log:
        log("zm-csv", "ok", t0, op="rule-remove" if remove else "rule-add", id=i)
    code, out = route_report(root, {"id": i}, now, read, save, log)
    if code == 200:
        out = dict(out, rule={"id": rid, "action": "removed" if remove else "added"})
    return code, out


def route_trip(root, body, now, read, save, log=None):
    """POST /internal/zm-trip {id, name, start, end} — «Добавить поездку»: aux/trip-ids.json получает
    `ids[name] = "site:" + name` и `dates[name] = [start, end]`; отчёт пересчитывается. Только поездка из блока
    «Новые поездки» отчёта (403 иначе); 409 — нет отчёта, уже записан."""
    t0 = time.monotonic()
    body = body or {}
    i, rep, err = _report_for_edit(root, body)
    if err:
        return err
    name, start, end = body.get("name"), body.get("start"), body.get("end")
    if not (isinstance(name, str) and name.startswith("#") and len(name) <= 80
            and all(isinstance(x, str) and DATE_RE.match(x) for x in (start, end))):
        return 400, {"error": "нужны name (#…), start и end (ГГГГ-ММ-ДД)"}
    try:
        date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        return 400, {"error": "start/end — не даты"}
    if start > end:
        return 400, {"error": "начало поездки позже конца"}
    if name not in {t["name"] for t in rep.get("new_trips") or []}:
        return 403, {"error": "такой поездки нет среди новых в отчёте"}
    path = f"{CSV_DIR}/aux/trip-ids.json"
    raw, _ = read(path)
    if not raw:
        return 409, {"error": "нет aux/trip-ids.json"}
    ti = json.loads(raw)
    ti.setdefault("ids", {})[name] = "site:" + name
    ti.setdefault("dates", {})[name] = [start, end]
    try:
        save(path, json.dumps(ti, ensure_ascii=False, indent=1) + "\n")
    except Exception as e:  # noqa: BLE001
        return 502, {"error": f"{type(e).__name__}: {str(e)[:300]}"}
    if log:
        log("zm-csv", "ok", t0, op="trip-add", id=i)
    code, out = route_report(root, {"id": i}, now, read, save, log)
    if code == 200:
        out = dict(out, trip={"name": name, "id": "site:" + name})
    return code, out
