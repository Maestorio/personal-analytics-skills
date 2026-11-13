#!/usr/bin/env python3
"""
apply_condition.py — писатель определений условий `Portfolio/conditions.yaml` (`conditions@2`, schema.md §3.2).

Скрипт сам читает и пишет файл определений на mount по `--root <корень Claude-Memory>` (schema.md §1 п.1):
весь документ проходит валидатор `ds_schemas.validate_conditions_file`, запись — временный файл рядом и
`os.replace`; при ошибке файл не меняется. Скрипт ничего не удаляет: ни файлов, ни записей. Состояние
`Portfolio/conditions-state.json` (`conditions-state@1`, §3.3) пишет только сайт — скрипт его только читает
модулем (а) `conditions_merge` для выборок. Модель видит только вывод скрипта.

Вызов:  python3 apply_condition.py <команда> --root <корень> [--today ГГГГ-ММ-ДД] [--by <actor>]
                                  [--plan <доля %>] [--snapshot <id снапшота>] [--key K1,K2] [--all]  < вход.json
Вход — JSON-объект в stdin (для list/digest/validate можно пусто). Выход — JSON в stdout.
Ошибка — код выхода 1 и JSON {"ok": false, "error": "...", ...}.

Команды:
  add        новое определение. Вход: key, kind, trigger{type, value, window_end?}, while_pending,
             on_trigger{action, verdict?, target_pct?, text, branches?, otherwise?}, source{kind, doc, decision_id?};
             необязательно: event_text, on_expiry, not_before, valid_until, note (почему создано, ≤ 200 знаков),
             expected (ожидаемая дата отчёта).
             Скрипт ставит id `c-ГГГГ-ММ-ДД-<ключ в нижнем регистре>-<n>` (дата — из created_at, n — следующий свободный),
             version 1, context{plan_pct, snapshot_id, as_of} из --plan/--snapshot (нет обоих — null и
             context_missing в выводе), created_at (time_msk.now_iso), created_by (--by), withdrawn/superseded_by null.
             report_published без window_end: window_end = expected + defaults.report_window_days;
             valid_until раньше window_end поднимается до окна (valid_until_raised в выводе).
  edit       новая версия: вход {id, <поля модели, кроме key>, note?, expected?}. Копия последней версии с правками,
             version+1, новые created_at/created_by; у прежней записи — superseded_by "<id>@<version+1>".
             context — из --plan/--snapshot, если переданы, иначе прежний. Правка без изменений — ошибка.
             Состояние по модулю (а) на --today: закрыто (done, dismissed, expired) — ошибка, нужно новое условие (add);
             сработало (fired) — только с флагом --state-reset: правка проходит, state_reset: true (правило 14: новая
             версия начинает состояние заново и стирает отметки владельца — отсрочку); без флага — ошибка.
             source новой версии: из входа, если передан; иначе по --by — owner → {kind: owner, doc: null},
             режим советника (mode_*) → {kind: report, doc: null} (кодлист condition_source); прочие авторы
             (скрипт, сайт, уведомитель) — source прежней версии.
  withdraw   снятие: вход {id, reason}; withdrawn{at, by, reason} на последней версии (кто снял — withdrawn.by;
             source версии не меняется, новой версии нет); состояние не трогается; повторное снятие — ошибка.
  Перештамповка (R33): после успешной записи add / edit / withdraw обзор недели того же дня (review_date = дата
  записи по МСК), в per_stock / per_bond которого есть ключ условия, перештамповывается
  (assemble_artifact.stamp_report — приоритет бумаг по новым условиям); в выводе `restamped: [{doc,
  priority_changed, stamped}]`. Обзора за этот день нет или бумаги в нём нет — ничего. Ошибка штампа правку
  условия не откатывает — `restamp_warnings`. В `_sync_log.md` скрипт не пишет (строку «перештамповано» —
  save-to-library, Workflow M).
  list,      выборка модулем (а): conditions_merge.select(merge(определения, состояние, --today), --key, только
  digest     действующие без --all). Вывод: items (плоские строки модуля), count, orphan_events, state_missing.
             Это контекст советника вместо чтения файлов (C5); list и digest — одна команда.
  crosscheck вердикты обзора против ждущих условий: вход {verdicts: {ключ: вердикт}, horizon_days?: 7,
             aliases?: {ключ: [обозначения]}}. Берутся действующие строки модуля (а) с датой триггера `date`
             или окном `report_published` не позже --today + horizon_days; бумага, упомянутая в тексте
             on_trigger.text ЧУЖОГО условия, с вердиктом против намерения ближайшего глагола слева — конфликт.
             Направления вердиктов — карта кодлистов verdict_direction (против продажи — up/flat, против
             покупки — down). Только флаг: решает советник.
  validate   файл определений целиком (код выхода 1 при ошибках); состояние, если есть, — предупреждениями;
             действующие условия по облигациям — правилом «вердикт после погашения» (даты — снапшоты корня).

Исход on_trigger: run_analysis, set_verdict (вердикт обязателен), set_target_pct (доля), notify_only, reinvest
(R30: деньги от погашения/оферты/купонов/продажи — в другую бумагу или корзину; target — корзина облигаций кодлиста
bond_bucket или ключ бумаги, amount_source — кодлист reinvest_source, verdict запрещён). add и edit проверяют
записываемое определение: у облигации с датным триггером в день погашения или позже вердикт «держать/докупать»
— ошибка (дата погашения — из снапшотов корня, в выводе `maturity`; нет даты — проверка пропущена, maturity: null);
корзина-цель reinvest, которой нет в `bond_buckets[].key` плана корня (Portfolio/plan.json), — ошибка «корзины <код>
нет в плане (есть: …)»; плана нет — цель сверяется только с кодлистом. validate проверяет то же у действующих.

Флаги записи (add / edit / withdraw):
  --no-restamp  не перештамповывать обзор недели (R33) — для сайта: у hub-notify `weekly-reviews/` вне записи;
  --emit        ничего не писать на mount: в выводе `emitted {path, text, base_digest}` — полный текст нового
                `conditions.yaml` (после валидатора) и sha256 прочитанных байтов; пишет вызывающий (сайт — через
                hub-api /api/job/save с base_hash). Перештамповки нет (писать нечего);
  --owner-only  withdraw: снимать только условия `source.kind: owner` (сайт — «снять своё»); чужое — ошибка.

Время записи (created_at, withdrawn.at, context.as_of и дата в id) — time_msk.now_iso(); скрытый аргумент
`--now <ГГГГ-ММ-ДДTЧЧ:ММ:СС+03:00>` подменяет его целиком (детерминизм тестов). --today — только дата оценки
модуля (а) (list/digest, crosscheck, проверка статуса в edit), по умолчанию — сегодня по МСК.

Зависимости: stdlib + PyYAML (чтение и запись YAML).
"""

import argparse
import copy
import hashlib
import io
import json
import os
import re
import sys
from datetime import date, timedelta

# Общие модули — канон в _shared-references/; в упакованном .skill — в своей scripts/ (pack.sh кладёт их по
# импортам вместе с транзитивными). Как у assemble_artifact: сначала каталог скрипта.
_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (_HERE, os.path.normpath(os.path.join(_HERE, "..", "..", "..", "_shared-references"))):
    if _cand not in sys.path:
        sys.path.insert(0, _cand)
import codelists  # noqa: E402
import glob  # noqa: E402
import conditions_merge as cm  # noqa: E402
import decisions_read as dr  # noqa: E402  — даты погашения из снапшотов корня (проверка «вердикт после погашения»)
import ds_schemas as ds  # noqa: E402
import hub_settings  # noqa: E402
import time_msk  # noqa: E402

SCHEMA_VERSION = "conditions@2"
STATE_SCHEMA_VERSION = "conditions-state@1"
DEFS_REL = ("Portfolio", "conditions.yaml")
STATE_REL = ("Portfolio", "conditions-state.json")
PLAN_REL = ("Portfolio", "plan.json")

# Поля, которые даёт модель; остальное ставит скрипт (schema.md §3.2, колонка «Кто ставит»).
MODEL_FIELDS = ("key", "kind", "trigger", "event_text", "while_pending", "on_trigger", "on_expiry",
                "not_before", "valid_until", "note", "source")
ADD_REQUIRED = ("key", "kind", "trigger", "while_pending", "on_trigger", "source")
EDIT_FIELDS = tuple(f for f in MODEL_FIELDS if f != "key")
OPTIONAL_FIELDS = ("event_text", "on_expiry", "not_before", "valid_until", "note")
SCRIPT_FIELDS = ("id", "version", "context", "created_at", "created_by", "withdrawn", "superseded_by",
                 "time_estimated", "converted_from_date")
FIELD_ORDER = ds.COND_FIELDS
WINDOW_DAYS = ds.DEFAULTS["report_window_days"]
TRIGGER_DATE = cm.TRIGGER_DATE
TRIGGER_REPORT = cm.TRIGGER_REPORT
ACTORS = ds.CODELISTS["actor"]
WEEKLY_REL = ("Portfolio", "weekly-reviews")
_WEEKLY_FILE = re.compile(r"^weekly-review-(stock|bond)-(\d{4}-\d{2}-\d{2})[^/]*\.ya?ml$")
# Терминальные статусы модуля (а): правка закрытого условия запрещена — нужно новое (add).
TERMINAL = (cm.DONE, cm.EXPIRED)

# crosscheck: направления вердиктов из кодлистов. Вердикты обзора берутся с legacy-кодами: словарь вердиктов
# облигаций переводит шаг 8, до него обзор пишет и их.
_VERDICT_DIRECTION = codelists.map_("verdict_direction")
_REVIEW_VERDICTS = set(codelists.codes("verdict"))
_CONFLICT_IF_SELL = {v for v in _REVIEW_VERDICTS if _VERDICT_DIRECTION.get(v) in ("up", "flat")}
_CONFLICT_IF_BUY = {v for v in _REVIEW_VERDICTS if _VERDICT_DIRECTION.get(v) == "down"}
# Глаголы намерения в тексте действия. Бумага в тексте получает намерение ближайшего глагола СЛЕВА от неё
# («продать 26245 + 26218 → купить 26248»).
_SELL_WORDS = ("продать", "продаж", "сократить", "срезать", "срез", "выйти", "выход",
               "зафиксировать", "sell", "trim")
_BUY_WORDS = ("купить", "покупк", "докуп", "добор", "добрать", "нарастить", "buy", "add")


class CmdError(Exception):
    """Ошибка команды: код выхода 1, JSON {"ok": false, "error": ..., **extra}."""

    def __init__(self, message, **extra):
        super().__init__(message)
        self.extra = extra


# ----------------------------------------------------------------------------- файлы

def _paths(root):
    if not root:
        raise CmdError("--root обязателен: корень Claude-Memory (в Cowork — $HOME/mnt/Claude-Memory)")
    root = os.path.abspath(os.path.expanduser(root))
    if not os.path.isdir(os.path.join(root, DEFS_REL[0])):
        raise CmdError(f"в корне {root} нет папки {DEFS_REL[0]}/ — неверный --root или mount не подключён")
    return os.path.join(root, *DEFS_REL), os.path.join(root, *STATE_REL)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _read_defs(path):
    """(документ, хеш байтов). Только conditions@2: формат 1.2 переводит migrate_conditions_v2.py."""
    if not os.path.isfile(path):
        raise CmdError(f"нет файла определений {path}")
    with open(path, "rb") as f:
        digest = _sha(f.read())
    doc = cm.load_yaml(path)
    if not isinstance(doc, dict):
        raise CmdError(f"{path}: ожидается YAML-объект")
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise CmdError(f"{path}: формат {doc.get('schema_version')!r}, скрипт работает только с {SCHEMA_VERSION} "
                       f"(перевод — tools/data-structures/migrations/migrate_conditions_v2.py)")
    if not isinstance(doc.get("conditions"), list):
        raise CmdError(f"{path}: conditions — не список")
    return doc, digest


def _read_state(path):
    """Состояние только на чтение. Нет файла — пустой список событий и state_missing."""
    if not os.path.isfile(path):
        return {"schema_version": STATE_SCHEMA_VERSION, "events": []}, True
    with open(path, encoding="utf-8") as f:
        state = json.load(f)
    errs = ds.validate_conditions_state(state)
    if errs:
        raise CmdError(f"{path}: состояние не проходит валидатор", errors=errs)
    return state, False


def _dump_yaml(doc):
    import yaml
    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=1000, default_flow_style=False)


def _write_defs(path, doc, digest, emit=None):
    """Валидатор на весь документ → временный файл рядом → os.replace. Ошибка — файл не меняется.
    emit — словарь (флаг --emit): файл не пишется, в него кладутся path, text и base_digest."""
    errs = ds.validate_conditions_file(doc)
    if errs:
        raise CmdError("валидация не пройдена — файл не изменён", errors=errs)
    text = _dump_yaml(doc)
    if emit is not None:
        emit.update({"path": "/".join(DEFS_REL), "text": text, "base_digest": digest})
        return
    with open(path, "rb") as f:
        if _sha(f.read()) != digest:
            raise CmdError("файл определений изменился после чтения — файл не изменён, повтори команду")
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# ----------------------------------------------------------------------------- помощники определений

def _check_payload(payload, allowed, required=()):
    script_owned = sorted(k for k in payload if k in SCRIPT_FIELDS and k not in allowed)
    if script_owned:
        raise CmdError(f"поля ставит скрипт, во входе их быть не должно: {', '.join(script_owned)}")
    unknown = sorted(k for k in payload if k not in allowed)
    if unknown:
        raise CmdError(f"неизвестные поля входа: {', '.join(unknown)} (допустимы: {', '.join(allowed)})")
    missing = [k for k in required if k not in payload]
    if missing:
        raise CmdError(f"нет обязательных полей входа: {', '.join(missing)}")


def _ordered(d):
    """Поля в порядке схемы (ds.COND_FIELDS); неизвестные — в конце (их поймает валидатор)."""
    out = {k: d[k] for k in FIELD_ORDER if k in d}
    out.update({k: v for k, v in d.items() if k not in out})
    return out


def _context(args, now):
    if args.plan is None and args.snapshot is None:
        return None
    return {"plan_pct": args.plan, "snapshot_id": args.snapshot, "as_of": now}


def _apply_window(d, expected):
    """report_published: окно от ожидаемой даты и подъём valid_until до окна. Возвращает пометки для вывода."""
    notes = {}
    tr = d.get("trigger")
    if not (isinstance(tr, dict) and tr.get("type") == TRIGGER_REPORT):
        if expected is not None:
            raise CmdError("expected допустим только у trigger.type = report_published")
        return notes
    if tr.get("window_end") is None:
        if expected is None:
            raise CmdError("у report_published нужен trigger.window_end или expected (ожидаемая дата ГГГГ-ММ-ДД)")
        if not ds.is_date(expected):
            raise CmdError(f"expected: ожидается дата ГГГГ-ММ-ДД, получено {expected!r}")
        tr["window_end"] = (date.fromisoformat(expected) + timedelta(days=WINDOW_DAYS)).isoformat()
        notes["window_end_computed"] = {"expected": expected, "window_end": tr["window_end"], "days": WINDOW_DAYS}
    elif expected is not None:
        raise CmdError("либо trigger.window_end, либо expected — не оба")
    vu, we = d.get("valid_until"), tr.get("window_end")
    if ds.is_date(vu) and ds.is_date(we) and vu < we:
        d["valid_until"] = we
        notes["valid_until_raised"] = {"from": vu, "to": we}
    return notes


def _new_id(conds, key, today):
    prefix = f"c-{today}-{str(key).lower()}-"
    used = [0]
    for c in conds:
        cid = c.get("id") if isinstance(c, dict) else None
        if isinstance(cid, str) and cid.startswith(prefix) and cid[len(prefix):].isdigit():
            used.append(int(cid[len(prefix):]))
    return f"{prefix}{max(used) + 1}"


def _last_version(conds, cid):
    """Последняя версия id (максимальная version) — объект из списка файла, не копия."""
    best = None
    for c in conds:
        if isinstance(c, dict) and c.get("id") == cid and isinstance(c.get("version"), int):
            if best is None or c["version"] > best["version"]:
                best = c
    if best is None:
        raise CmdError(f"нет условия с id {cid!r}")
    return best


def _check_maturity(args, d):
    """Правило 19 валидатора (R30): у записываемого определения по облигации с датным триггером в день погашения или
    позже вердикт «держать/докупать» невозможен — ошибка, файл не меняется. Дата погашения — из снапшотов корня;
    нет даты (не облигация или её нет ни в одном снапшоте) — проверка пропущена, в выводе maturity: null."""
    key = d.get("key")
    m = dr.maturities(os.path.abspath(os.path.expanduser(args.root)), [key]).get(key) if key else None
    errs = ds.maturity_errors(d, {key: m} if m else {}) + ds.plan_bucket_errors(d, _plan_buckets(args.root))
    if errs:
        raise CmdError("валидация не пройдена — файл не изменён", errors=errs, maturity=m)
    return m


def _plan_buckets(root):
    """Ключи корзин облигаций живого плана (`bond_buckets[].key` в Portfolio/plan.json корня) — цель reinvest
    сверяется с ними (правило 20 валидатора). Плана нет или он не читается — None: проверка по кодлисту."""
    path = os.path.join(os.path.abspath(os.path.expanduser(root)), *PLAN_REL)
    try:
        with open(path, encoding="utf-8") as f:
            plan = json.load(f)
    except (OSError, ValueError):
        return None
    rows = plan.get("bond_buckets") if isinstance(plan, dict) else None
    if not isinstance(rows, list):
        return None
    return [r["key"] for r in rows if isinstance(r, dict) and isinstance(r.get("key"), str)]


def _now(args):
    return args.now or time_msk.now_iso()


def _need_by(args):
    if not args.by:
        raise CmdError(f"--by обязателен для записи (кодлист actor: {', '.join(ACTORS)})")


def _source_for(args, prev):
    """source новой версии при правке без source во входе: владелец — owner, режим советника — report,
    прочие авторы — прежний source (кодлист condition_source)."""
    kinds = codelists.codes("condition_source", legacy=False)
    if args.by == "owner" and "owner" in kinds:
        return {"kind": "owner", "doc": None}
    if str(args.by or "").startswith("mode_") and "report" in kinds:
        return {"kind": "report", "doc": None}
    return copy.deepcopy(prev)


def _restamp(args, key, now):
    """R33: обзор недели того же дня (по МСК), где есть ключ, — перештамповать (приоритет по новым условиям).
    → (restamped, warnings). Ошибка штампа не откатывает правку условия."""
    root = os.path.abspath(os.path.expanduser(args.root))
    day = now[:10]
    folder = os.path.join(root, *WEEKLY_REL)
    done, warns = [], []
    for path in sorted(glob.glob(os.path.join(folder, f"weekly-review-*-{day}*.y*ml"))):
        name = os.path.basename(path)
        m = _WEEKLY_FILE.match(name)
        if not m or m.group(2) != day:
            continue
        doc_rel = "/".join(WEEKLY_REL + (name,))
        try:
            data = cm.load_yaml(path)
            items = (data or {}).get("per_stock") if m.group(1) == "stock" else (data or {}).get("per_bond")
            if str((data or {}).get("review_date") or "")[:10] != day or not isinstance(items, dict) or key not in items:
                continue
            import assemble_artifact as aa  # noqa: E402 — штамп обзора (R28); тяжёлый модуль — только по нужде
            code, out = aa.stamp_report(["--root", root, "--doc", doc_rel, "--now", now])
        except Exception as exc:  # noqa: BLE001 — правка условия уже записана; штамп — предупреждением
            warns.append(f"{doc_rel}: перештамповка не удалась: {type(exc).__name__}: {exc}")
            continue
        if code != 0 or not out.get("ok"):
            warns.append(f"{doc_rel}: перештамповка не удалась: {out.get('error')}")
            continue
        done.append({"doc": doc_rel, "priority_changed": out.get("priority_changed") or [],
                     "stamped": out.get("stamped") or []})
    return done, warns


def _emit_of(args):
    return {} if getattr(args, "emit", False) else None


def _finish(args, out, key, emit):
    """Хвост команд записи: --emit — текст в выводе; иначе перештамповка обзора (если не --no-restamp)."""
    if emit is not None:
        out["emitted"] = emit
        return out
    if getattr(args, "no_restamp", False):
        return out
    return _with_restamp(args, out, key)


def _with_restamp(args, out, key):
    restamped, warns = _restamp(args, key, _now(args))
    out["restamped"] = restamped
    if warns:
        out["restamp_warnings"] = warns
    return out


# ----------------------------------------------------------------------------- команды записи

def cmd_add(args, payload):
    _need_by(args)
    _check_payload(payload, MODEL_FIELDS + ("expected",), ADD_REQUIRED)
    defs_path, _ = _paths(args.root)
    doc, digest = _read_defs(defs_path)
    conds = doc["conditions"]
    now = _now(args)
    d = {"id": _new_id(conds, payload["key"], now[:10]), "version": 1}
    d.update({k: copy.deepcopy(payload[k]) for k in MODEL_FIELDS if k in payload})
    notes = _apply_window(d, payload.get("expected"))
    d["context"] = _context(args, now)
    d.update({"created_at": now, "created_by": args.by, "withdrawn": None, "superseded_by": None})
    d = _ordered(d)
    maturity = _check_maturity(args, d)
    conds.append(d)
    emit = _emit_of(args)
    _write_defs(defs_path, doc, digest, emit)
    out = {"ok": True, "command": "add", "id": d["id"], "version": 1, "maturity": maturity, "condition": d}
    if d["context"] is None:
        out["context_missing"] = True
    out.update(notes)
    return _finish(args, out, d["key"], emit)


def cmd_edit(args, payload):
    _need_by(args)
    if "key" in payload:
        raise CmdError("key не меняется правкой: снять условие (withdraw) и поставить новое (add)")
    _check_payload(payload, ("id",) + EDIT_FIELDS + ("expected",), ("id",))
    changes = {k: payload[k] for k in EDIT_FIELDS if k in payload}
    defs_path, state_path = _paths(args.root)
    doc, digest = _read_defs(defs_path)
    conds = doc["conditions"]
    last = _last_version(conds, payload["id"])
    if last.get("withdrawn"):
        raise CmdError(f"условие {payload['id']} снято {last['withdrawn'].get('at')} — правка невозможна, "
                       f"поставь новое (add)")
    state, _ = _read_state(state_path)
    row = cm.merge([last], state, args.today)[0]
    if row["state_status"] in TERMINAL:
        closed = row["closed_as"] or row["state_status"]
        raise CmdError(f"условие {payload['id']} закрыто ({closed}); нужно новое условие (add)",
                       status=row["state_status"], closed_as=row["closed_as"])
    if row["state_status"] == cm.FIRED and not getattr(args, "state_reset", False):
        raise CmdError(f"условие {payload['id']} сработало{' и отложено владельцем до ' + row['deferred_until'] if row.get('deferred_until') else ''}: "
                       f"правка начнёт состояние заново и сотрёт отметки владельца — повтори с --state-reset "
                       f"или сними условие (withdraw) и заведи новое (add)",
                       status=row["state_status"], deferred_until=row.get("deferred_until"))
    new = copy.deepcopy(last)
    new.pop("time_estimated", None)          # оценённое время миграции относится к прежней записи
    changed = []
    for k, v in changes.items():
        if new.get(k) != v:
            changed.append(k)
        if v is None and k in OPTIONAL_FIELDS:
            new.pop(k, None)
        else:
            new[k] = copy.deepcopy(v)
    if "trigger" in changed:
        new.pop("converted_from_date", None)  # пометка миграции — про прежний триггер
    notes = _apply_window(new, payload.get("expected"))
    if not changed and not notes:
        raise CmdError(f"правка {payload['id']} ничего не меняет — новая версия не создана")
    if "source" not in changes:
        new["source"] = _source_for(args, last.get("source"))
        if new["source"] != last.get("source"):
            changed.append("source")
    now = _now(args)
    v = last["version"] + 1
    ctx = _context(args, now)
    if ctx is not None:
        new["context"] = ctx
        changed.append("context")
    new.update({"version": v, "created_at": now, "created_by": args.by, "withdrawn": None, "superseded_by": None})
    new = _ordered(new)
    maturity = _check_maturity(args, new)
    last["superseded_by"] = f"{last['id']}@{v}"
    conds.append(new)
    emit = _emit_of(args)
    _write_defs(defs_path, doc, digest, emit)
    out = {"ok": True, "command": "edit", "id": new["id"], "version": v,
           "previous": f"{new['id']}@{v - 1}", "changed": changed,
           "state_reset": row["state_status"] == cm.FIRED, "maturity": maturity, "condition": new}
    out.update(notes)
    return _finish(args, out, new["key"], emit)


def cmd_withdraw(args, payload):
    _need_by(args)
    _check_payload(payload, ("id", "reason"), ("id", "reason"))
    if not isinstance(payload["reason"], str) or not payload["reason"].strip():
        raise CmdError("reason: нужна причина снятия словами")
    defs_path, _ = _paths(args.root)
    doc, digest = _read_defs(defs_path)
    last = _last_version(doc["conditions"], payload["id"])
    if last.get("withdrawn"):
        raise CmdError(f"условие {payload['id']} уже снято {last['withdrawn'].get('at')}")
    if getattr(args, "owner_only", False) and (last.get("source") or {}).get("kind") != "owner":
        raise CmdError(f"условие {payload['id']} поставил не ты (источник: {(last.get('source') or {}).get('kind')}) — "
                       f"снять можно только своё условие; чужое снимает советник")
    last["withdrawn"] = {"at": _now(args), "by": args.by, "reason": payload["reason"]}
    emit = _emit_of(args)
    _write_defs(defs_path, doc, digest, emit)
    return _finish(args, {"ok": True, "command": "withdraw", "id": last["id"], "version": last["version"],
                          "withdrawn": last["withdrawn"]}, last["key"], emit)


# ----------------------------------------------------------------------------- команды чтения

def _merged(args):
    defs_path, state_path = _paths(args.root)
    doc, _ = _read_defs(defs_path)
    state, state_missing = _read_state(state_path)
    defs = doc["conditions"]
    return cm.merge(defs, state, args.today), cm.orphan_event_ids(defs, state), state_missing


def cmd_digest(args, payload):
    _check_payload(payload, ())
    rows, orphans, state_missing = _merged(args)
    keys = [k.strip() for k in (args.key or "").split(",") if k.strip()]
    items = cm.select(rows, keys=keys or None, only_active=not args.all)
    return {"ok": True, "command": args.command, "today": args.today, "keys": keys, "all": bool(args.all),
            "count": len(items), "items": items, "orphan_events": orphans, "state_missing": state_missing}


def _intent_positions(text_lower):
    out = []
    for words, intent in ((_SELL_WORDS, "sell"), (_BUY_WORDS, "buy")):
        for w in words:
            start = 0
            while True:
                i = text_lower.find(w, start)
                if i < 0:
                    break
                out.append((i, intent))
                start = i + len(w)
    return sorted(out)


def _mentions(text, names):
    """{обозначение: намерение} для обозначений (тикер/ISIN/псевдоним), встреченных в тексте отдельным словом."""
    low = text.lower()
    marks = _intent_positions(low)
    found = {}
    for name in names:
        m = re.search(r"(?<![0-9A-Za-zА-Яа-я])" + re.escape(name.lower()) + r"(?![0-9A-Za-zА-Яа-я])", low)
        if not m:
            continue
        prev = [intent for pos, intent in marks if pos < m.start()]
        found[name] = prev[-1] if prev else None
    return found


def cmd_crosscheck(args, payload):
    _check_payload(payload, ("verdicts", "horizon_days", "aliases"), ("verdicts",))
    if not isinstance(payload["verdicts"], dict):
        raise CmdError("verdicts: ожидается объект {ключ: вердикт}")
    horizon = payload.get("horizon_days", 7)
    if not isinstance(horizon, int) or isinstance(horizon, bool) or horizon < 0:
        raise CmdError(f"horizon_days: ожидается целое ≥ 0, получено {horizon!r}")
    verdicts = {str(k): str(v).upper() for k, v in payload["verdicts"].items()}
    unknown = sorted({v for v in verdicts.values() if v not in _REVIEW_VERDICTS})
    key_of = {}
    for k in verdicts:
        key_of[k] = k
        for a in (payload.get("aliases") or {}).get(k, []) or []:
            key_of[str(a)] = k
    rows, _, state_missing = _merged(args)
    today = date.fromisoformat(args.today)
    conflicts, checked = [], []
    for r in rows:
        if not r["active"]:
            continue
        tt = (r["trigger"] or {}).get("type")
        due = r["trigger"].get("value") if tt == TRIGGER_DATE else r["window_end"] if tt == TRIGGER_REPORT else None
        if not ds.is_date(due):
            continue  # ценовые и прочие условия срабатывают в любой день — их ведёт уведомитель
        days_left = (date.fromisoformat(due) - today).days
        if days_left > horizon:
            continue
        checked.append(r["id"])
        for name, intent in _mentions(r["text"] or "", key_of).items():
            key = key_of[name]
            if key == r["key"]:
                continue  # свою бумагу условие ведёт само (while_pending до срока — норма)
            v = verdicts.get(key)
            if (intent == "sell" and v in _CONFLICT_IF_SELL) or (intent == "buy" and v in _CONFLICT_IF_BUY):
                conflicts.append({
                    "condition_id": r["id"], "days_left": days_left, "due": due, "status": r["status"],
                    "security": key, "mentioned_as": name, "intent": intent, "verdict": v,
                    "message": (f"Условие `{r['id']}` ({'через ' + str(days_left) + ' дн.' if days_left > 0 else 'срок наступил'}, "
                                f"{due}) предлагает {'продать' if intent == 'sell' else 'купить'} {name}, а вердикт "
                                f"обзора по {key} — {v}. Исправить вердикт или условие (edit) и записать "
                                f"резолюцию в отчёт."),
                })
    return {"ok": True, "command": "crosscheck", "today": args.today, "horizon_days": horizon,
            "checked": checked, "conflicts": conflicts, "unknown_verdicts": unknown, "state_missing": state_missing}


def cmd_validate(args, payload):
    _check_payload(payload, ())
    defs_path, state_path = _paths(args.root)
    if not os.path.isfile(defs_path):
        raise CmdError(f"нет файла определений {defs_path}")
    doc = cm.load_yaml(defs_path)
    errs = ds.validate_conditions_file(doc)
    warnings = []
    if os.path.isfile(state_path):
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
        warnings = ds.validate_conditions_state(state) + ds.validate_state_refs(state, doc)
    conds = (doc or {}).get("conditions") if isinstance(doc, dict) else None
    conds = conds if isinstance(conds, list) else []
    if not errs:
        # правило 19 (R30): действующие условия по облигациям — вердикт после погашения невозможен
        state = {"events": []}
        if os.path.isfile(state_path):
            with open(state_path, encoding="utf-8") as f:
                state = json.load(f)
        active = {r["id"] for r in cm.merge(conds, state, args.today) if r["active"]}
        last = cm._last_defs(conds)
        mats = dr.maturities(os.path.abspath(os.path.expanduser(args.root)),
                             sorted({last[i]["key"] for i in active if isinstance(last[i].get("key"), str)}))
        buckets = _plan_buckets(args.root)
        for cid in sorted(active):
            errs += ds.maturity_errors(last[cid], mats, f"{cid}@{last[cid]['version']}: ")
            errs += ds.plan_bucket_errors(last[cid], buckets, f"{cid}@{last[cid]['version']}: ")
    return {"ok": not errs, "command": "validate", "errors": errs, "definitions": len(conds),
            "ids": len({c.get("id") for c in conds if isinstance(c, dict)}),
            "state_warnings": warnings, "state_missing": not os.path.isfile(state_path)}


COMMANDS = {"add": cmd_add, "edit": cmd_edit, "withdraw": cmd_withdraw, "list": cmd_digest,
            "digest": cmd_digest, "crosscheck": cmd_crosscheck, "validate": cmd_validate}


# ----------------------------------------------------------------------------- CLI

class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CmdError(f"аргументы: {message}")


def _parser():
    ap = _Parser(description="Определения условий conditions@2: add / edit / withdraw / list / digest / "
                             "crosscheck / validate")
    ap.add_argument("command", choices=sorted(COMMANDS))
    ap.add_argument("--root", required=True, help="корень Claude-Memory")
    ap.add_argument("--today", default=None, help="дата ГГГГ-ММ-ДД (по умолчанию сегодня, МСК)")
    ap.add_argument("--by", default=None, help="кто пишет (кодлист actor), обязателен для add/edit/withdraw")
    ap.add_argument("--plan", type=float, default=None, help="план владельца по бумаге, % (context.plan_pct)")
    ap.add_argument("--snapshot", default=None, help="id снапшота (context.snapshot_id)")
    ap.add_argument("--key", default="", help="list/digest: ключи бумаг через запятую")
    ap.add_argument("--all", action="store_true", help="list/digest: и закрытые/снятые")
    ap.add_argument("--state-reset", dest="state_reset", action="store_true",
                    help="edit: править сработавшее условие, начав состояние заново (стирает отсрочку владельца)")
    ap.add_argument("--no-restamp", dest="no_restamp", action="store_true",
                    help="add/edit/withdraw: не перештамповывать обзор недели (сайт)")
    ap.add_argument("--emit", action="store_true",
                    help="add/edit/withdraw: файл не писать — текст нового conditions.yaml и base_digest в выводе (сайт)")
    ap.add_argument("--owner-only", dest="owner_only", action="store_true",
                    help="withdraw: только условия source.kind owner (сайт)")
    ap.add_argument("--now", default=None, help=argparse.SUPPRESS)  # подмена time_msk.now_iso() для тестов
    return ap


def run(argv, stdin_text):
    """(код выхода, объект вывода). Без побочных эффектов, кроме записи файла определений командами записи."""
    try:
        args = _parser().parse_args(argv)
        args.today = args.today or time_msk.today_iso()
        if not ds.is_date(args.today):
            raise CmdError(f"--today: ожидается ГГГГ-ММ-ДД, получено {args.today!r}")
        if args.now is not None and not ds.is_time(args.now):
            raise CmdError(f"--now: ожидается ГГГГ-ММ-ДДTЧЧ:ММ:СС+03:00, получено {args.now!r}")
        if args.by is not None and args.by not in ACTORS:
            raise CmdError(f"--by: нет в кодлисте actor ({', '.join(ACTORS)}): {args.by!r}")
        text = (stdin_text or "").strip()
        try:
            payload = json.loads(text) if text else {}
        except json.JSONDecodeError as exc:
            raise CmdError(f"вход: не JSON ({exc})")
        if not isinstance(payload, dict):
            raise CmdError("вход: ожидается JSON-объект")
        if args.command in ("add", "edit", "withdraw") and args.by != "owner":
            # гейт по происхождению входа: определение от модели (советник, скрипт) при «без ИИ» не пишется;
            # условие владельца (--by owner) проходит в обоих режимах
            hub_settings.require_ai(args.root, f"apply_condition.py {args.command}", "запись определения условия", zones=("Portfolio", "scenarios"))
        out = COMMANDS[args.command](args, payload)
    except CmdError as exc:
        return 1, {"ok": False, "error": str(exc), **exc.extra}
    except Exception as exc:  # noqa: BLE001 — нечитаемый YAML/JSON, ввод-вывод: модель получает JSON, не трассу
        return 1, {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return (0 if out.get("ok") else 1), out


# команды, которым вход не нужен: stdin читается, только если в нём уже есть данные — иначе вызов из subprocess
# без `</dev/null` ждал бы закрытия входа вечно
OPTIONAL_INPUT = {"list": 0.0, "digest": 0.0, "validate": 1.0}   # сколько ждать данных во входе, с


def _stdin_ready(stream, timeout=0.0):
    """Есть ли во входе данные (или конец потока) за `timeout` секунд. POSIX — select; `validate` ждёт секунду,
    чтобы конвейер `генератор | validate` не ушёл с пустым входом до того, как генератор что-то записал; где select
    с потоком не работает (не POSIX, подменённый поток) — True, вход читается как раньше."""
    try:
        import select
        return bool(select.select([stream], [], [], timeout)[0])
    except (ImportError, OSError, ValueError, AttributeError, io.UnsupportedOperation):
        return True


def _read_stdin(argv):
    if sys.stdin is None or sys.stdin.isatty():
        return ""
    try:
        cmd = _parser().parse_args(argv).command
    except CmdError:
        cmd = None   # ошибку аргументов сообщит run()
    if cmd in OPTIONAL_INPUT and not _stdin_ready(sys.stdin, OPTIONAL_INPUT[cmd]):
        return ""
    return sys.stdin.read()


def main():
    code, out = run(sys.argv[1:], _read_stdin(sys.argv[1:]))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
