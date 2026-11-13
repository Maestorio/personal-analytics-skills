#!/usr/bin/env python3
"""Валидаторы целевой схемы данных портфельного контура (цикл «машиночитаемость»).

Источник правил — docs/investment/_cross-cutting/data-structures/schema.md §3:
  decision@1          — решение по бумаге (§3.1)
  conditions@2        — определения условий, файл целиком (§3.2)
  conditions-state@1  — состояние условий, только дописываемые события (§3.3)
  report@1            — шапка отчёта советника Portfolio/reports/*.md и её блок `decisions:` (§4.3, §3.1)
  security-attrs@1    — справочник бумаг Portfolio/security-attrs.json: класс, дата листинга (§4.8)
  decision-journal-refusals@1 / -theses@1 / -incidents@1 — ручные входы журнала решений
                        Portfolio/decision-journal/*.yaml (§4.5; пишет save-to-library Workflow P)

Функции возвращают список ошибок; пустой список = валидно. Каждая ошибка — одна строка
«поле: что не так». Только stdlib (PyYAML нужен лишь CLI и load_yaml для YAML-файлов).

CLI:  python3 _shared-references/ds_schemas.py <decision|conditions|state|report|security-attrs|refusals|theses|incidents> <файл>
      (report — .md с шапкой)
      печатает ошибки по одной на строку; код выхода 1 при ошибках.

ПРАВИЛА ВАЛИДАТОРА СВЕРХ СХЕМЫ (добавлены при реализации; каждое можно убрать, не ломая схему)
 1. Неизвестные поля в любом объекте — ошибка (схема закрытая).
 2. trigger.window_end допустим только у report_published и не позже valid_until.
 3. branches и otherwise допустимы только внутри on_trigger; otherwise — только вместе с branches.
 4. on_trigger / then / otherwise / on_expiry: action=set_target_pct требует target_pct,
    action=set_verdict требует verdict.
 5. on_expiry допустим только вместе с valid_until.
 5а. review_by решения (если не null) — от 7 до 180 дней после даты recorded_at.
 6. decision.source.kind=report требует source.doc.
 7. Событие done требует data.decision_id, data.trade_date или data.note; у done by=owner («сделал» с сайта)
    data может быть пустым — опора сама отметка владельца.
 8. Событие owner_mark требует data.mark из перечня owner_mark (dismissed, deferred); deferred требует
    data.until (дата). «Сделал» с сайта — это событие done с by=owner, не owner_mark.
 9a. В conditions-state@1 нет last_checked_at (его хранит hub-notify в своём state.json); поле не допускается.
 9b. Поле version у события состояния необязательно (модуль объединения его не читает); если есть — целое ≥ 1.
 9. Событие reopened пишет только владелец (by=owner).
10. У датного триггера дата внутри окна [not_before, valid_until].
11. id решения согласован с recorded_at и key; вид ключа (isin/ticker) не хранится — key_kind(key) считает при чтении.
12. Версии условия: у не последней версии superseded_by указывает на существующую более позднюю версию того
    же id, у последней superseded_by = null; дубли id@version запрещены.
13. Шапка report@1: kind и mode_codes — без legacy-кодов; mode_codes непустой и без повторов; tickers — список
    непустых строк (может быть пустым); неизвестные поля шапки допускаются (шапка открытая: title, summary, mode…).
14. Блок `decisions:` шапки — только поля модели §3.1 (key, verdict, target_pct, review_by, note, confidence,
    keep_open); key — из tickers[] шапки и пригоден для имени файла, без повторов внутри блока. Окно review_by
    проверяет validate_decision при записи (от recorded_at решения, не отчёта).
15. Решение может нести служебную пометку миграции `recorded_at_estimated: true|false` (бэкфилл шага 9: время —
    оценка `set_date + T00:00`), по образцу `time_estimated` условий; поле необязательное, писатель новых решений
    (decision_write.py) его не ставит.
16. security-attrs@1: `by_key` — объект «ключ → запись», ключ пригоден для имени (KEY_RE); у каждой записи ровно
    пять полей ticker_class / listed_at / note / updated_at / updated_by; ticker_class и listed_at допускают null
    (запись есть у каждой бумаги, «нет класса» = null, а не отсутствие записи).
17. Ручные входы журнала решений (refusals / theses / incidents) — минимальная форма, схема открытая (лишние поля
    допускаются: файлы пишет модель через Workflow P, поля исторически росли): объект с `schema` и списком записей;
    у записи — идентификатор (refusals: `episode_id`; theses, incidents: `id`), дата (refusals: `answered`;
    theses: `opened` | `revised` | `closed`; incidents: `date`) и текст (refusals: `reason` — строка или null
    «пропустить»; theses: `event` | `note` | `owner_words`; incidents: `what`). Дата — `YYYY-MM-DD` строкой или
    датой YAML. Пустой файл (нет списка) — валиден.
18. Исход reinvest (R30): обязательны target (код кодлиста bond_bucket — корзина облигаций плана — или ключ бумаги,
    пригодный для имени, KEY_RE) и text; verdict и target_pct запрещены; amount_source необязателен, из кодлиста
    reinvest_source. target и amount_source допустимы только у reinvest.
19. Вердикт после погашения (R30, maturity_errors): у условия по облигации с датным триггером в день её погашения
    или позже исход set_verdict с вердиктом направления up/flat (on_trigger, ветки, otherwise) — ошибка: деньги
    уже пришли, бумаги нет, нужен reinvest. Даты погашения передаёт вызывающий ({ключ: дата}; apply_condition берёт
    их из снапшотов по корню); без них проверка не делается.
20. Корзина reinvest в плане (plan_bucket_errors): при известном корне target-корзина кодлиста bond_bucket обязана
    быть ключом `bond_buckets[].key` живого Portfolio/plan.json, иначе ошибка «корзины <код> нет в плане»; ключ
    бумаги не проверяется. Ключи плана передаёт вызывающий (apply_condition — из корня); без плана — правило 18.
"""

import json
import math
import os
import re
import sys
from datetime import date, datetime

# Перечни кодов — из кодлистов (`codelists.json`, загрузчик `codelists.py`, модуль (в)
# схемы §1.3). Валидаторы целевой схемы принимают только не-legacy коды; `author` — поле решения, не кодлист §3.4.
# В репозитории модуль лежит в `_shared-references/` рядом с ними, в упакованном скилле — в `scripts/` (pack.sh кладёт
# его рядом со скриптом, который делает `import ds_schemas`, вместе с транзитивными codelists/conditions_merge/time_msk).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codelists  # noqa: E402
# вид ключа и загрузка YAML без дат-объектов — у модуля (а) (`_shared-references/conditions_merge.py`), копий нет
from conditions_merge import key_kind, load_yaml  # noqa: E402,F401

_DS_LISTS = ("verdict", "asset_class", "condition_kind", "condition_trigger_type", "condition_action",
             "condition_event", "owner_mark", "mode_codes", "decision_source", "actor", "condition_source",
             "report_kind", "reinvest_source", "bond_bucket")
CODELISTS = {name: tuple(codelists.codes(name, legacy=False)) for name in _DS_LISTS}
CODELISTS["author"] = ("model", "owner")
# Класс бумаги — только справочника бумаг (§4.8); в CODELISTS решения не входит (класс из решения удалён, §3.1).
TICKER_CLASSES = tuple(codelists.codes("ticker_class", legacy=False))

# Раздел `defaults` кодлистов (схема §3.4): константы сроков и пауз, считаются при чтении.
DEFAULTS = codelists.defaults()

REVIEW_BY_MIN_DAYS = 7
REVIEW_BY_MAX_DAYS = 180

TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+03:00$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DECISION_ID_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2})(\d{2})-(.+)$")
SUPERSEDED_RE = re.compile(r"^(.+)@(\d+)$")
COND_ID_RE = re.compile(r"^[^\s@]+$")

NOTE_MAX = 200
EVENT_TEXT_MAX = 200

DECISION_FIELDS = ("schema_version", "id", "key", "verdict", "target_pct", "review_by", "note", "confidence",
                   "conditions_created", "conditions_resolved", "source", "author", "recorded_at",
                   # служебная пометка миграции (бэкфилл шага 9): время записи — оценка
                   "recorded_at_estimated")
DECISION_OPTIONAL = ("confidence", "recorded_at_estimated")
DECISION_REQUIRED = tuple(f for f in DECISION_FIELDS if f not in DECISION_OPTIONAL)

# Справочник бумаг security-attrs@1 (§4.8): по записи на ключ, все поля обязательны (null допустим у двух).
SECURITY_ATTRS_SCHEMA_VERSION = "security-attrs@1"
SECURITY_ATTR_FIELDS = ("ticker_class", "listed_at", "note", "updated_at", "updated_by")

COND_FIELDS = ("id", "version", "key", "kind", "trigger", "event_text", "while_pending", "on_trigger",
               "not_before", "valid_until", "on_expiry", "note", "context", "source", "created_at", "created_by",
               "withdrawn", "superseded_by",
               # служебные пометки миграции 1.2 -> 2
               "time_estimated", "converted_from_date")
COND_REQUIRED = ("id", "version", "key", "kind", "trigger", "while_pending", "on_trigger", "source",
                 "created_at", "created_by", "withdrawn", "superseded_by")

# Шапка отчёта report@1 (§4.3): обязательные поля; остальные поля шапки — открытые (title, summary, mode, …).
REPORT_SCHEMA_VERSION = "report@1"
REPORT_REQUIRED = ("schema_version", "title", "date", "kind", "mode_codes", "tickers", "recorded_at")
# Блок `decisions:` шапки — поля, которые заполняет модель (§3.1); остальное ставит decision_write.py.
REPORT_DECISION_FIELDS = ("key", "verdict", "target_pct", "review_by", "note", "confidence", "keep_open")
REPORT_DECISION_REQUIRED = ("key", "verdict", "target_pct", "review_by", "note")
# Ключ решения идёт в имя файла `{время}-{KEY}.json`: только буквы, цифры, точка, дефис, подчёркивание.
KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

EVENT_FIELDS = ("condition_id", "version", "event", "at", "by", "data", "time_estimated")


# ----------------------------------------------------------------------------- примитивы

def is_time(v):
    """Строка вида YYYY-MM-DDTHH:MM:SS+03:00 и реальные дата/время."""
    if not isinstance(v, str) or not TIME_RE.match(v):
        return False
    try:
        datetime.fromisoformat(v)
    except ValueError:
        return False
    return True


def is_date(v):
    """Строка YYYY-MM-DD и реальная дата."""
    if not isinstance(v, str) or not DATE_RE.match(v):
        return False
    try:
        date.fromisoformat(v)
    except ValueError:
        return False
    return True


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _t(v):
    return type(v).__name__


def _short(v, n=40):
    s = repr(v)
    return s if len(s) <= n else s[: n - 1] + "…"


def _code(errs, path, v, codelist, allow_null=False):
    if v is None and allow_null:
        return
    allowed = CODELISTS[codelist]
    if not isinstance(v, str) or v not in allowed:
        errs.append(f"{path}: нет в перечне {codelist} ({', '.join(allowed)}): {_short(v)}")


def _time(errs, path, v, allow_null=False):
    if v is None and allow_null:
        return
    if not is_time(v):
        errs.append(f"{path}: ожидается время YYYY-MM-DDTHH:MM:SS+03:00 (пояс обязателен), получено {_short(v)}")


def _date(errs, path, v, allow_null=False):
    if v is None and allow_null:
        return
    if not is_date(v):
        errs.append(f"{path}: ожидается дата YYYY-MM-DD, получено {_short(v)}")


def _pct(errs, path, v, allow_null=True):
    if v is None:
        if not allow_null:
            errs.append(f"{path}: обязательное поле")
        return
    if not _is_num(v) or not 0 <= v <= 100:
        errs.append(f"{path}: ожидается число 0..100 или null, получено {_short(v)}")


def _str(errs, path, v, max_len=None, allow_empty=False):
    if not isinstance(v, str):
        errs.append(f"{path}: ожидается строка, получено {_t(v)}")
        return False
    if not allow_empty and not v.strip():
        errs.append(f"{path}: пустая строка")
        return False
    if max_len is not None and len(v) > max_len:
        errs.append(f"{path}: длиннее {max_len} символов ({len(v)})")
        return False
    return True


def _unknown_fields(errs, path, obj, allowed):
    for k in obj:
        if k not in allowed:
            errs.append(f"{path + '.' if path else ''}{k}: неизвестное поле")


def _required(errs, path, obj, names):
    for n in names:
        if n not in obj:
            errs.append(f"{path + '.' if path else ''}{n}: обязательное поле отсутствует")


# ----------------------------------------------------------------------------- решение

def validate_decision(obj):
    """Решение по бумаге decision@1 (схема §3.1). Пустой список = валидно."""
    errs = []
    if not isinstance(obj, dict):
        return [f"(корень): ожидается объект, получено {_t(obj)}"]
    _unknown_fields(errs, "", obj, DECISION_FIELDS)
    _required(errs, "", obj, DECISION_REQUIRED)

    if "schema_version" in obj and obj["schema_version"] != "decision@1":
        errs.append(f"schema_version: ожидается 'decision@1', получено {_short(obj['schema_version'])}")

    if "key" in obj:
        _str(errs, "key", obj["key"])
    if "verdict" in obj:
        _code(errs, "verdict", obj["verdict"], "verdict")
    if "target_pct" in obj:
        _pct(errs, "target_pct", obj["target_pct"])
    if "review_by" in obj:
        _date(errs, "review_by", obj["review_by"], allow_null=True)
        rb, ra = obj["review_by"], obj.get("recorded_at")
        if is_date(rb) and is_time(ra):
            delta = (date.fromisoformat(rb) - date.fromisoformat(ra[:10])).days
            if not REVIEW_BY_MIN_DAYS <= delta <= REVIEW_BY_MAX_DAYS:
                errs.append(f"review_by: вне окна {REVIEW_BY_MIN_DAYS}–{REVIEW_BY_MAX_DAYS} дней от recorded_at "
                            f"({delta} дн.)")
    for name in ("conditions_created", "conditions_resolved"):
        if name in obj:
            lst = obj[name]
            if not isinstance(lst, list):
                errs.append(f"{name}: ожидается список id условий, получено {_t(lst)}")
            else:
                for i, t in enumerate(lst):
                    if not isinstance(t, str) or not t.strip():
                        errs.append(f"{name}[{i}]: ожидается непустой id условия")
    if "note" in obj:
        _str(errs, "note", obj["note"], NOTE_MAX)
    if "confidence" in obj and obj["confidence"] is not None:
        c = obj["confidence"]
        if not _is_num(c) or not 0 <= c <= 1:
            errs.append(f"confidence: ожидается число 0..1 или null, получено {_short(c)}")

    if "source" in obj:
        s = obj["source"]
        if not isinstance(s, dict):
            errs.append(f"source: ожидается объект, получено {_t(s)}")
        else:
            _unknown_fields(errs, "source", s, ("kind", "doc", "mode_codes", "stress_id"))
            _required(errs, "source", s, ("kind", "doc", "mode_codes"))
            if "kind" in s:
                _code(errs, "source.kind", s["kind"], "decision_source")
            if s.get("doc") is not None and not isinstance(s.get("doc"), str):
                errs.append(f"source.doc: ожидается строка (путь отчёта) или null, получено {_t(s['doc'])}")
            if s.get("kind") == "report" and not s.get("doc"):
                errs.append("source.doc: у source.kind=report путь отчёта обязателен")
            if s.get("stress_id") is not None and not isinstance(s.get("stress_id"), str):
                errs.append(f"source.stress_id: ожидается строка или null, получено {_t(s['stress_id'])}")
            mc = s.get("mode_codes")
            if "mode_codes" in s:
                if not isinstance(mc, list):
                    errs.append(f"source.mode_codes: ожидается список кодов режима, получено {_t(mc)}")
                else:
                    for i, m in enumerate(mc):
                        _code(errs, f"source.mode_codes[{i}]", m, "mode_codes")
    if "author" in obj:
        _code(errs, "author", obj["author"], "author")
    if "recorded_at" in obj:
        _time(errs, "recorded_at", obj["recorded_at"])
    if "recorded_at_estimated" in obj and not isinstance(obj["recorded_at_estimated"], bool):
        errs.append(f"recorded_at_estimated: ожидается true/false, получено {_t(obj['recorded_at_estimated'])}")
    # id = {дата}T{ЧЧММ}-{KEY}, согласован с recorded_at и key
    if "id" in obj:
        did = obj["id"]
        m = DECISION_ID_RE.match(did) if isinstance(did, str) else None
        if not m:
            errs.append(f"id: ожидается {{дата}}T{{ЧЧММ}}-{{KEY}} (например 2026-10-29T1740-GMKN), получено {_short(did)}")
        else:
            d, hh, mm, k = m.groups()
            if not is_date(d) or int(hh) > 23 or int(mm) > 59:
                errs.append(f"id: некорректные дата или время в {did!r}")
            ra = obj.get("recorded_at")
            if is_time(ra):
                if ra[:10] != d:
                    errs.append(f"id: дата {d} не совпадает с recorded_at ({ra[:10]})")
                if ra[11:13] != hh or ra[14:16] != mm:
                    errs.append(f"id: время {hh}{mm} не совпадает с recorded_at ({ra[11:13]}{ra[14:16]})")
            if isinstance(obj.get("key"), str) and obj["key"] and k != obj["key"]:
                errs.append(f"id: ключ {k!r} не совпадает с key {obj['key']!r}")
    return errs


# ----------------------------------------------------------------------------- справочник бумаг

def validate_security_attrs(obj):
    """Справочник бумаг security-attrs@1 (схема §4.8). Пустой список = валидно."""
    errs = []
    if not isinstance(obj, dict):
        return [f"(корень): ожидается объект, получено {_t(obj)}"]
    _unknown_fields(errs, "", obj, ("schema_version", "by_key"))
    _required(errs, "", obj, ("schema_version", "by_key"))
    if "schema_version" in obj and obj["schema_version"] != SECURITY_ATTRS_SCHEMA_VERSION:
        errs.append(f"schema_version: ожидается {SECURITY_ATTRS_SCHEMA_VERSION!r}, получено {_short(obj['schema_version'])}")
    by_key = obj.get("by_key")
    if "by_key" in obj and not isinstance(by_key, dict):
        errs.append(f"by_key: ожидается объект «ключ → запись», получено {_t(by_key)}")
        return errs
    for key, rec in (by_key or {}).items():
        p = f"by_key.{key}"
        if not isinstance(key, str) or not KEY_RE.match(key):
            errs.append(f"{p}: ключ не пригоден (буквы, цифры, точка, дефис, подчёркивание)")
        if not isinstance(rec, dict):
            errs.append(f"{p}: ожидается объект, получено {_t(rec)}")
            continue
        _unknown_fields(errs, p, rec, SECURITY_ATTR_FIELDS)
        _required(errs, p, rec, SECURITY_ATTR_FIELDS)
        tc = rec.get("ticker_class")
        if tc is not None and (not isinstance(tc, str) or tc not in TICKER_CLASSES):
            errs.append(f"{p}.ticker_class: нет в перечне ticker_class ({', '.join(TICKER_CLASSES)}): {_short(tc)}")
        if "listed_at" in rec:
            _date(errs, p + ".listed_at", rec["listed_at"], allow_null=True)
        if "note" in rec and rec["note"] is not None:
            _str(errs, p + ".note", rec["note"], NOTE_MAX)
        if "updated_at" in rec:
            _time(errs, p + ".updated_at", rec["updated_at"])
        if "updated_by" in rec:
            _code(errs, p + ".updated_by", rec["updated_by"], "actor")
    return errs


# ----------------------------------------------------------------------------- шапка отчёта report@1

def _iso_scalar(v):
    """Дата/время, которые PyYAML разобрал в объекты (неквотированные в шапке), — обратно в ISO-строку."""
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return v


def validate_report_decisions(block, tickers=None):
    """Блок `decisions:` шапки отчёта (поля модели §3.1). tickers — список ключей шапки или None (не сверять)."""
    errs = []
    if not isinstance(block, list) or not block:
        return [f"decisions: ожидается непустой список записей по бумагам, получено {_short(block)}"]
    seen = set()
    for i, d in enumerate(block):
        p = f"decisions[{i}]"
        if not isinstance(d, dict):
            errs.append(f"{p}: ожидается объект, получено {_t(d)}")
            continue
        _unknown_fields(errs, p, d, REPORT_DECISION_FIELDS)
        _required(errs, p, d, REPORT_DECISION_REQUIRED)
        k = d.get("key")
        if "key" in d and _str(errs, f"{p}.key", k):
            if not KEY_RE.match(k):
                errs.append(f"{p}.key: только буквы, цифры, «.», «-», «_» (ключ идёт в имя файла): {_short(k)}")
            elif k in seen:
                errs.append(f"{p}.key: повтор ключа {k!r} в блоке (одно решение на бумагу в отчёте)")
            elif isinstance(tickers, list) and k not in tickers:
                errs.append(f"{p}.key: {k!r} нет в tickers[] шапки")
            seen.add(k)
        if "verdict" in d:
            _code(errs, f"{p}.verdict", d["verdict"], "verdict")
        if "target_pct" in d:
            _pct(errs, f"{p}.target_pct", d["target_pct"])
        if "review_by" in d:
            _date(errs, f"{p}.review_by", _iso_scalar(d["review_by"]), allow_null=True)
        if "note" in d:
            _str(errs, f"{p}.note", d["note"], NOTE_MAX)
        c = d.get("confidence")
        if c is not None and (not _is_num(c) or not 0 <= c <= 1):
            errs.append(f"{p}.confidence: ожидается число 0..1 или null, получено {_short(c)}")
        if "keep_open" in d:
            ko = d["keep_open"]
            if not isinstance(ko, list) or not all(isinstance(x, str) and x.strip() for x in ko):
                errs.append(f"{p}.keep_open: ожидается список id условий, получено {_short(ko)}")
    return errs


def validate_report(fm):
    """Шапка отчёта report@1 (схема §4.3) и её блок `decisions:` (§3.1). Пустой список = валидно."""
    if not isinstance(fm, dict):
        return [f"(шапка): ожидается объект, получено {_t(fm)}"]
    errs = []
    _required(errs, "", fm, REPORT_REQUIRED)
    if "schema_version" in fm and fm["schema_version"] != REPORT_SCHEMA_VERSION:
        errs.append(f"schema_version: ожидается {REPORT_SCHEMA_VERSION!r}, получено {_short(fm['schema_version'])}")
    if "title" in fm:
        _str(errs, "title", fm["title"])
    if "date" in fm:
        _date(errs, "date", _iso_scalar(fm["date"]))
    if "kind" in fm:
        _code(errs, "kind", fm["kind"], "report_kind")
    if "mode_codes" in fm:
        mc = fm["mode_codes"]
        if not isinstance(mc, list) or not mc:
            errs.append(f"mode_codes: ожидается непустой список кодов режима (главный первым), получено {_short(mc)}")
        else:
            for i, m in enumerate(mc):
                _code(errs, f"mode_codes[{i}]", m, "mode_codes")
            if len(set(map(str, mc))) != len(mc):
                errs.append(f"mode_codes: повтор кода {_short(mc)}")
    tickers = fm.get("tickers")
    if "tickers" in fm:
        if not isinstance(tickers, list):
            errs.append(f"tickers: ожидается список ключей бумаг, получено {_t(tickers)}")
            tickers = None
        else:
            for i, t in enumerate(tickers):
                if not isinstance(t, str) or not t.strip():
                    errs.append(f"tickers[{i}]: ожидается непустая строка (тикер или ISIN), получено {_short(t)}")
    if "recorded_at" in fm:
        _time(errs, "recorded_at", _iso_scalar(fm["recorded_at"]))
    if "decisions" in fm:
        errs.extend(validate_report_decisions(fm["decisions"], tickers if isinstance(tickers, list) else None))
    return errs


def report_frontmatter(text):
    """Шапка .md как словарь (даты и время остаются строками) или None, если шапки нет."""
    import yaml

    m = re.match(r"\A---\n(.*?)\n---[ \t]*(?:\n|\Z)", text, re.S)
    if not m:
        return None

    class _StrLoader(yaml.SafeLoader):
        pass

    _StrLoader.yaml_implicit_resolvers = {
        k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:timestamp"]
        for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }
    return yaml.load(m.group(1), Loader=_StrLoader)


# ----------------------------------------------------------------------------- определение условия

def _check_outcome(errs, path, o, text_required=True, nested=False):
    """Исход: on_trigger / ветка then / otherwise / on_expiry — действие кодом + текст.
    nested=True (только on_trigger): допустимы branches[] и otherwise{} (схема §3.2)."""
    if not isinstance(o, dict):
        errs.append(f"{path}: ожидается объект, получено {_t(o)}")
        return
    _unknown_fields(errs, path, o, ("action", "verdict", "target_pct", "target", "amount_source", "text")
                    + (("branches", "otherwise") if nested else ()))
    _required(errs, path, o, ("action",) + (("text",) if text_required else ()))
    if "action" in o:
        _code(errs, f"{path}.action", o["action"], "condition_action")
    if "verdict" in o:
        _code(errs, f"{path}.verdict", o["verdict"], "verdict", allow_null=True)
    if "target_pct" in o:
        _pct(errs, f"{path}.target_pct", o["target_pct"])
    if "text" in o:
        _str(errs, f"{path}.text", o["text"], allow_empty=not text_required)
    if o.get("action") == "set_target_pct" and o.get("target_pct") is None:
        errs.append(f"{path}.target_pct: у action=set_target_pct целевая доля обязательна")
    if o.get("action") == "set_verdict" and o.get("verdict") is None:
        errs.append(f"{path}.verdict: у action=set_verdict вердикт обязателен")
    _check_reinvest(errs, path, o)
    if nested:
        _check_branches(errs, path, o)


def _check_reinvest(errs, path, o):
    """Правило 18: исход reinvest — куда (target) и откуда (amount_source) деньги; вердикта нет."""
    if o.get("action") != REINVEST:
        for f in ("target", "amount_source"):
            if f in o:
                errs.append(f"{path}.{f}: допустим только у action=reinvest")
        return
    if o.get("verdict") is not None:
        errs.append(f"{path}.verdict: у action=reinvest вердикта нет (деньги идут в другую бумагу или корзину)")
    if o.get("target_pct") is not None:
        errs.append(f"{path}.target_pct: у action=reinvest доли нет")
    t = o.get("target")
    if t is None:
        errs.append(f"{path}.target: у action=reinvest обязательна цель — корзина облигаций (кодлист bond_bucket) "
                    f"или ключ бумаги")
    elif not isinstance(t, str) or not (t in CODELISTS["bond_bucket"] or KEY_RE.match(t)):
        errs.append(f"{path}.target: ожидается корзина облигаций ({', '.join(CODELISTS['bond_bucket'])}) или ключ "
                    f"бумаги, получено {_short(t)}")
    if "amount_source" in o:
        _code(errs, f"{path}.amount_source", o["amount_source"], "reinvest_source", allow_null=True)


REINVEST = "reinvest"
# «держать/докупать» после погашения: вердикты с направлением up и flat (карта verdict_direction кодлистов)
VERDICTS_AFTER_MATURITY = tuple(v for v in CODELISTS["verdict"]
                                if codelists.map_("verdict_direction").get(v) in ("up", "flat"))


def maturity_errors(obj, maturities, p=""):
    """Правило 19: вердикт «держать/докупать» у условия, срабатывающего в день погашения облигации или позже.

    obj — определение условия, maturities — {ключ: 'ГГГГ-ММ-ДД'} (считает вызывающий). Пустой список = нет ошибок
    (в том числе когда даты погашения ключа нет или триггер не датный)."""
    if not isinstance(obj, dict) or not isinstance(maturities, dict):
        return []
    m, tr = maturities.get(obj.get("key")), obj.get("trigger")
    if not is_date(m) or not isinstance(tr, dict) or tr.get("type") != "date" or not is_date(tr.get("value")):
        return []
    if tr["value"] < m:
        return []
    ot = obj.get("on_trigger") if isinstance(obj.get("on_trigger"), dict) else {}
    outs = [("on_trigger", ot)]
    for i, b in enumerate(ot.get("branches") or []):
        if isinstance(b, dict) and isinstance(b.get("then"), dict):
            outs.append((f"on_trigger.branches[{i}].then", b["then"]))
    if isinstance(ot.get("otherwise"), dict):
        outs.append(("on_trigger.otherwise", ot["otherwise"]))
    return [f"{p}{path}.verdict: после погашения {m} (триггер {tr['value']}) вердикт {o.get('verdict')} невозможен — "
            f"бумаги уже нет, используй action=reinvest с target"
            for path, o in outs if o.get("action") == "set_verdict" and o.get("verdict") in VERDICTS_AFTER_MATURITY]


def _outcomes(obj):
    """Все исходы определения условия: (путь, исход) — on_trigger, его ветки и otherwise, on_expiry."""
    ot = obj.get("on_trigger") if isinstance(obj.get("on_trigger"), dict) else {}
    outs = [("on_trigger", ot)]
    for i, b in enumerate(ot.get("branches") or []):
        if isinstance(b, dict) and isinstance(b.get("then"), dict):
            outs.append((f"on_trigger.branches[{i}].then", b["then"]))
    if isinstance(ot.get("otherwise"), dict):
        outs.append(("on_trigger.otherwise", ot["otherwise"]))
    if isinstance(obj.get("on_expiry"), dict):
        outs.append(("on_expiry", obj["on_expiry"]))
    return outs


def plan_bucket_errors(obj, plan_buckets, p=""):
    """Правило 20: цель reinvest — корзина кодлиста bond_bucket, которой нет в плане владельца, — ошибка.

    plan_buckets — ключи `bond_buckets[].key` живого plan.json (читает вызывающий); None — плана нет, проверка не
    делается (остаётся кодлист правила 18). Ключ бумаги (target вне кодлиста) не проверяется."""
    if not isinstance(obj, dict) or plan_buckets is None:
        return []
    have = ", ".join(plan_buckets) or "пусто"
    return [f"{p}{path}.target: корзины {o['target']} нет в плане (есть: {have})"
            for path, o in _outcomes(obj)
            if o.get("action") == REINVEST and o.get("target") in CODELISTS["bond_bucket"]
            and o["target"] not in plan_buckets]


def _check_branches(errs, path, o):
    """branches[] и otherwise{} внутри on_trigger."""
    if "branches" in o:
        br = o["branches"]
        if not isinstance(br, list) or not br:
            errs.append(f"{path}.branches: ожидается непустой список или отсутствие поля")
        else:
            for i, b in enumerate(br):
                bp = f"{path}.branches[{i}]"
                if not isinstance(b, dict):
                    errs.append(f"{bp}: ожидается объект, получено {_t(b)}")
                    continue
                _unknown_fields(errs, bp, b, ("if_text", "then"))
                _required(errs, bp, b, ("if_text", "then"))
                if "if_text" in b:
                    _str(errs, f"{bp}.if_text", b["if_text"])
                if "then" in b:
                    _check_outcome(errs, f"{bp}.then", b["then"])
    if "otherwise" in o:
        if "branches" not in o:
            errs.append(f"{path}.otherwise: допустимо только вместе с branches")
        _check_outcome(errs, f"{path}.otherwise", o["otherwise"])


def _validate_condition_def(obj, p):
    """Определение условия conditions@2 (схема §3.2); p — префикс пути ошибок."""
    errs = []
    if not isinstance(obj, dict):
        return [f"{p.rstrip('.') or '(корень)'}: ожидается объект, получено {_t(obj)}"]
    _unknown_fields(errs, p.rstrip("."), obj, COND_FIELDS)
    _required(errs, p.rstrip("."), obj, COND_REQUIRED)

    if "id" in obj:
        if not isinstance(obj["id"], str) or not COND_ID_RE.match(obj["id"]):
            errs.append(f"{p}id: ожидается непустая строка без пробелов и '@', получено {_short(obj['id'])}")
    if "version" in obj and (not _is_int(obj["version"]) or obj["version"] < 1):
        errs.append(f"{p}version: ожидается целое ≥ 1, получено {_short(obj['version'])}")
    if "key" in obj:
        _str(errs, p + "key", obj["key"])
    if "kind" in obj:
        _code(errs, p + "kind", obj["kind"], "condition_kind")

    nb = obj.get("not_before")
    vu = obj.get("valid_until")
    if "not_before" in obj:
        _date(errs, p + "not_before", nb, allow_null=True)
    if "valid_until" in obj:
        _date(errs, p + "valid_until", vu, allow_null=True)
    if is_date(nb) and is_date(vu) and nb > vu:
        errs.append(f"{p}not_before: позже valid_until ({nb} > {vu})")

    # trigger
    tr = obj.get("trigger")
    if "trigger" in obj:
        if not isinstance(tr, dict):
            errs.append(f"{p}trigger: ожидается объект, получено {_t(tr)}")
        else:
            _unknown_fields(errs, p + "trigger", tr, ("type", "value", "window_end"))
            _required(errs, p + "trigger", tr, ("type", "value"))
            tt = tr.get("type")
            if "type" in tr:
                _code(errs, p + "trigger.type", tt, "condition_trigger_type")
            val = tr.get("value")
            if tt == "date":
                _date(errs, p + "trigger.value", val)
                if is_date(val):
                    if is_date(nb) and val < nb:
                        errs.append(f"{p}not_before: у датного триггера не позже даты ({nb} > {val})")
                    if is_date(vu) and val > vu:
                        errs.append(f"{p}valid_until: дата триггера вне окна ({val} > {vu})")
            elif tt in ("price_below", "price_above"):
                if not _is_num(val) or val <= 0:
                    errs.append(f"{p}trigger.value: ожидается положительное число (цена), получено {_short(val)}")
            elif tt in CODELISTS["condition_trigger_type"]:
                if "value" in tr and not (isinstance(val, str) and val.strip()) and not _is_num(val):
                    errs.append(f"{p}trigger.value: ожидается непустая строка или число, получено {_short(val)}")
            we = tr.get("window_end")
            if tt == "report_published":
                if we is None:
                    errs.append(f"{p}trigger.window_end: у report_published обязателен (дата, к которой событие считается наступившим)")
                else:
                    _date(errs, p + "trigger.window_end", we)
                    if is_date(we) and is_date(vu) and we > vu:
                        errs.append(f"{p}trigger.window_end: позже valid_until ({we} > {vu})")
            elif "window_end" in tr:
                errs.append(f"{p}trigger.window_end: допустим только у report_published")

    if "event_text" in obj and obj["event_text"] is not None:
        _str(errs, p + "event_text", obj["event_text"], EVENT_TEXT_MAX)
    if "note" in obj and obj["note"] is not None:
        _str(errs, p + "note", obj["note"], NOTE_MAX)   # почему создано или изменено (пишет модель)

    # while_pending
    if "while_pending" in obj:
        wp = obj["while_pending"]
        if not isinstance(wp, dict):
            errs.append(f"{p}while_pending: ожидается объект, получено {_t(wp)}")
        else:
            _unknown_fields(errs, p + "while_pending", wp, ("verdict", "target_pct", "text"))
            _required(errs, p + "while_pending", wp, ("verdict",))
            if "verdict" in wp:
                # kind: watch (наблюдение, напоминание владельца) вердикт бумаги не закрепляет — verdict: null
                _code(errs, p + "while_pending.verdict", wp["verdict"], "verdict", allow_null=obj.get("kind") == "watch")
            if "target_pct" in wp:
                _pct(errs, p + "while_pending.target_pct", wp["target_pct"])
            if wp.get("text") is not None:
                _str(errs, p + "while_pending.text", wp["text"], allow_empty=True)

    if "on_trigger" in obj:
        _check_outcome(errs, p + "on_trigger", obj["on_trigger"], nested=True)

    if "on_expiry" in obj and obj["on_expiry"] is not None:
        _check_outcome(errs, p + "on_expiry", obj["on_expiry"])
        if vu is None:
            errs.append(f"{p}on_expiry: допустим только вместе с valid_until")

    if "context" in obj and obj["context"] is not None:
        c = obj["context"]
        if not isinstance(c, dict):
            errs.append(f"{p}context: ожидается объект или null, получено {_t(c)}")
        else:
            _unknown_fields(errs, p + "context", c, ("plan_pct", "snapshot_id", "as_of"))
            _required(errs, p + "context", c, ("as_of",))
            if "plan_pct" in c:
                _pct(errs, p + "context.plan_pct", c["plan_pct"])
            if c.get("snapshot_id") is not None:
                _str(errs, p + "context.snapshot_id", c["snapshot_id"])
            if "as_of" in c:
                _time(errs, p + "context.as_of", c["as_of"])

    if "source" in obj:
        s = obj["source"]
        if not isinstance(s, dict):
            errs.append(f"{p}source: ожидается объект, получено {_t(s)}")
        else:
            _unknown_fields(errs, p + "source", s, ("kind", "doc", "decision_id"))
            _required(errs, p + "source", s, ("kind", "doc"))
            if "kind" in s:
                _code(errs, p + "source.kind", s["kind"], "condition_source")
            if s.get("doc") is not None and not isinstance(s.get("doc"), str):
                errs.append(f"{p}source.doc: ожидается строка или null, получено {_t(s['doc'])}")
            if s.get("decision_id") is not None and not isinstance(s.get("decision_id"), str):
                errs.append(f"{p}source.decision_id: ожидается строка или null, получено {_t(s['decision_id'])}")

    if "created_at" in obj:
        _time(errs, p + "created_at", obj["created_at"])
    if "created_by" in obj:
        _code(errs, p + "created_by", obj["created_by"], "actor")
    for flag in ("time_estimated", "converted_from_date"):
        if flag in obj and not isinstance(obj[flag], bool):
            errs.append(f"{p}{flag}: ожидается true/false, получено {_t(obj[flag])}")

    if "withdrawn" in obj and obj["withdrawn"] is not None:
        w = obj["withdrawn"]
        if not isinstance(w, dict):
            errs.append(f"{p}withdrawn: ожидается объект или null, получено {_t(w)}")
        else:
            _unknown_fields(errs, p + "withdrawn", w, ("at", "by", "reason"))
            _required(errs, p + "withdrawn", w, ("at", "by", "reason"))
            if "at" in w:
                _time(errs, p + "withdrawn.at", w["at"])
            if "by" in w:
                _code(errs, p + "withdrawn.by", w["by"], "actor")
            if "reason" in w:
                _str(errs, p + "withdrawn.reason", w["reason"])

    if "superseded_by" in obj and obj["superseded_by"] is not None:
        sb = obj["superseded_by"]
        if not isinstance(sb, str) or not SUPERSEDED_RE.match(sb):
            errs.append(f"{p}superseded_by: ожидается 'id@версия' или null, получено {_short(sb)}")
    return errs


def validate_condition_def(obj):
    """Одно определение условия (схема §3.2). Пустой список = валидно."""
    return _validate_condition_def(obj, "")


def validate_conditions_file(obj):
    """Файл conditions@2 целиком: схема каждой записи, уникальность id@version,
    у не последней версии есть superseded_by (ссылка на существующую более позднюю версию того же id),
    у последней версии superseded_by = null."""
    errs = []
    if not isinstance(obj, dict):
        return [f"(корень): ожидается объект, получено {_t(obj)}"]
    _unknown_fields(errs, "", obj, ("schema_version", "conditions", "last_updated"))
    if obj.get("schema_version") != "conditions@2":
        errs.append(f"schema_version: ожидается 'conditions@2', получено {_short(obj.get('schema_version'))}")
    if "last_updated" in obj:
        _time(errs, "last_updated", obj["last_updated"], allow_null=True)
    conds = obj.get("conditions")
    if not isinstance(conds, list):
        errs.append(f"conditions: ожидается список, получено {_t(conds)}")
        return errs

    seen = {}
    by_id = {}
    for i, c in enumerate(conds):
        errs.extend(_validate_condition_def(c, f"conditions[{i}]."))
        if not isinstance(c, dict) or not isinstance(c.get("id"), str) or not _is_int(c.get("version")):
            continue
        k = (c["id"], c["version"])
        if k in seen:
            errs.append(f"conditions[{i}]: дубль {c['id']}@{c['version']} (первое вхождение conditions[{seen[k]}])")
        else:
            seen[k] = i
        by_id.setdefault(c["id"], []).append((c["version"], i, c))

    for cid, vers in by_id.items():
        vers.sort(key=lambda x: x[0])
        last_v = vers[-1][0]
        have = {v for v, _, _ in vers}
        for v, i, c in vers:
            sb = c.get("superseded_by")
            if v < last_v:
                if not sb:
                    errs.append(f"conditions[{i}].superseded_by: у не последней версии {cid}@{v} обязательно (последняя — {last_v})")
                else:
                    m = SUPERSEDED_RE.match(sb) if isinstance(sb, str) else None
                    if m:
                        if m.group(1) != cid or int(m.group(2)) <= v or int(m.group(2)) not in have:
                            errs.append(f"conditions[{i}].superseded_by: {sb!r} не указывает на существующую более позднюю версию {cid}")
            elif sb:
                errs.append(f"conditions[{i}].superseded_by: у последней версии {cid}@{v} должно быть null, получено {sb!r}")
    return errs


# ----------------------------------------------------------------------------- состояние условий

def _validate_event(e, p):
    errs = []
    if not isinstance(e, dict):
        return [f"{p}: ожидается объект, получено {_t(e)}"]
    _unknown_fields(errs, p, e, EVENT_FIELDS)
    _required(errs, p, e, ("condition_id", "event", "at", "by"))
    if "condition_id" in e:
        _str(errs, f"{p}.condition_id", e["condition_id"])
    if "version" in e and (not _is_int(e["version"]) or e["version"] < 1):
        errs.append(f"{p}.version: ожидается целое ≥ 1, получено {_short(e['version'])}")
    if "event" in e:
        _code(errs, f"{p}.event", e["event"], "condition_event")
    if "at" in e:
        _time(errs, f"{p}.at", e["at"])
    if "by" in e:
        _code(errs, f"{p}.by", e["by"], "actor")
    if "time_estimated" in e and not isinstance(e["time_estimated"], bool):
        errs.append(f"{p}.time_estimated: ожидается true/false, получено {_t(e['time_estimated'])}")
    data = e.get("data", {})
    if data is None:
        data = {}
    if not isinstance(data, dict):
        errs.append(f"{p}.data: ожидается объект, получено {_t(data)}")
        return errs
    if e.get("event") == "done" and e.get("by") != "owner" \
            and not any(data.get(k) for k in ("decision_id", "trade_date", "note")):
        errs.append(f"{p}.data: у события done (кроме by: owner) нужен decision_id, trade_date или note")
    if e.get("event") == "owner_mark":
        mk = data.get("mark")
        if mk not in CODELISTS["owner_mark"]:
            errs.append(f"{p}.data.mark: нет в перечне owner_mark ({', '.join(CODELISTS['owner_mark'])}): {_short(mk)}")
        elif mk == "deferred" and not is_date(data.get("until")):
            errs.append(f"{p}.data.until: у mark=deferred обязательна дата YYYY-MM-DD, получено {_short(data.get('until'))}")
    if e.get("event") == "reopened" and e.get("by") != "owner":
        errs.append(f"{p}.by: событие reopened пишет только владелец (owner), получено {_short(e.get('by'))}")
    if "doc" in data and data["doc"] is not None and not isinstance(data["doc"], str):
        errs.append(f"{p}.data.doc: ожидается строка или null, получено {_t(data['doc'])}")
    if "price" in data and data["price"] is not None and not _is_num(data["price"]):
        errs.append(f"{p}.data.price: ожидается число, получено {_short(data['price'])}")
    if data.get("trade_date") is not None and not is_date(data["trade_date"]):
        errs.append(f"{p}.data.trade_date: ожидается дата YYYY-MM-DD, получено {_short(data['trade_date'])}")
    return errs


def validate_conditions_state(obj):
    """Состояние условий conditions-state@1 (схема §3.3). Пустой список = валидно."""
    errs = []
    if not isinstance(obj, dict):
        return [f"(корень): ожидается объект, получено {_t(obj)}"]
    _unknown_fields(errs, "", obj, ("schema_version", "events"))
    _required(errs, "", obj, ("schema_version", "events"))
    if "schema_version" in obj and obj["schema_version"] != "conditions-state@1":
        errs.append(f"schema_version: ожидается 'conditions-state@1', получено {_short(obj['schema_version'])}")
    ev = obj.get("events")
    if "events" in obj:
        if not isinstance(ev, list):
            errs.append(f"events: ожидается список, получено {_t(ev)}")
        else:
            for i, e in enumerate(ev):
                errs.extend(_validate_event(e, f"events[{i}]"))
    return errs


def validate_state_refs(state, conditions_file):
    """Перекрёстная проверка (не часть §3): каждое событие ссылается на существующее id@version."""
    errs = []
    maxv = {}
    for c in (conditions_file or {}).get("conditions", []) or []:
        if isinstance(c, dict) and isinstance(c.get("id"), str) and _is_int(c.get("version")):
            maxv[c["id"]] = max(maxv.get(c["id"], 0), c["version"])
    for i, e in enumerate((state or {}).get("events", []) or []):
        if not isinstance(e, dict):
            continue
        cid, v = e.get("condition_id"), e.get("version")
        if cid not in maxv:
            errs.append(f"events[{i}].condition_id: условия {cid!r} нет в определениях")
        elif _is_int(v) and v > maxv[cid]:
            errs.append(f"events[{i}].version: {v} больше последней версии {cid}@{maxv[cid]}")
    return errs


# ----------------------------------------------------------------------------- ручные входы журнала решений

# правило 17: имя → (schema, ключ списка, поле идентификатора, поля даты (хотя бы одно), поля текста (хотя бы одно),
# текст может быть null)
JOURNAL_MANUAL = {
    "refusals": ("decision-journal-refusals@1", "refusals", "episode_id", ("answered",), ("reason",), True),
    "theses": ("decision-journal-theses@1", "theses", "id", ("opened", "revised", "closed"),
               ("event", "note", "owner_words"), False),
    "incidents": ("decision-journal-incidents@1", "incidents", "id", ("date",), ("what",), False),
}


def _manual_date(v):
    if isinstance(v, date):          # датой YAML (yaml.safe_load) — тоже дата
        return True
    return is_date(v)


def validate_journal_manual(kind, obj):
    """Ручной вход журнала решений (правило 17): kind ∈ refusals | theses | incidents. Пустой список = валидно."""
    schema, list_key, id_field, date_fields, text_fields, text_null = JOURNAL_MANUAL[kind]
    if obj is None:
        return []
    if not isinstance(obj, dict):
        return [f"(корень): ожидается объект со списком {list_key}, получено {_t(obj)}"]
    errs = []
    if obj.get("schema") not in (None, schema):
        errs.append(f"schema: ожидается {schema!r}, получено {_short(obj.get('schema'))}")
    items = obj.get(list_key)
    if items is None:
        return errs
    if not isinstance(items, list):
        return errs + [f"{list_key}: ожидается список записей, получено {_t(items)}"]
    for i, e in enumerate(items):
        p = f"{list_key}[{i}]"
        if not isinstance(e, dict):
            errs.append(f"{p}: ожидается объект, получено {_t(e)}")
            continue
        v = e.get(id_field)
        if not isinstance(v, str) or not v.strip():
            errs.append(f"{p}.{id_field}: обязательное поле — непустая строка, получено {_short(v)}")
        dates = [f for f in date_fields if e.get(f) is not None]
        if not dates:
            errs.append(f"{p}: нет даты ({' | '.join(date_fields)})")
        for f in dates:
            if not _manual_date(e[f]):
                errs.append(f"{p}.{f}: ожидается дата YYYY-MM-DD, получено {_short(e[f])}")
        texts = [f for f in text_fields if f in e]
        if not texts:
            errs.append(f"{p}: нет текста ({' | '.join(text_fields)})")
        for f in texts:
            t = e[f]
            if t is None and text_null:
                continue
            if not isinstance(t, str) or not t.strip():
                if not (t is None and len(texts) > 1):
                    errs.append(f"{p}.{f}: ожидается непустая строка, получено {_short(t)}")
    return errs


def validate_refusals(obj):
    return validate_journal_manual("refusals", obj)


def validate_theses(obj):
    return validate_journal_manual("theses", obj)


def validate_incidents(obj):
    return validate_journal_manual("incidents", obj)


# ----------------------------------------------------------------------------- загрузка и CLI

def load_any(path):
    if str(path).endswith(".md"):
        with open(path, encoding="utf-8") as f:
            fm = report_frontmatter(f.read())
        if fm is None:
            raise ValueError("нет YAML-шапки")
        return fm
    if str(path).endswith((".yaml", ".yml")):
        return load_yaml(path)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    kinds = {"decision": validate_decision, "conditions": validate_conditions_file,
             "state": validate_conditions_state, "report": validate_report,
             "security-attrs": validate_security_attrs, "refusals": validate_refusals,
             "theses": validate_theses, "incidents": validate_incidents}
    if len(argv) != 2 or argv[0] not in kinds:
        print("Использование: ds_schemas.py <decision|conditions|state|report|security-attrs|refusals|theses|"
              "incidents> <файл>",
              file=sys.stderr)
        return 2
    try:
        obj = load_any(argv[1])
    except (OSError, ValueError) as e:
        print(f"(файл): не читается: {e}")
        return 1
    errs = kinds[argv[0]](obj)
    for e in errs:
        print(e)
    if errs:
        print(f"Ошибок: {len(errs)}")
        return 1
    print("OK: ошибок нет")
    return 0


if __name__ == "__main__":
    sys.exit(main())
