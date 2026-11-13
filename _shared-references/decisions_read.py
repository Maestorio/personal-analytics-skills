#!/usr/bin/env python3
"""Чтение решений по бумаге `Portfolio/decisions/*.json` (`decision@1`, schema.md §3.1) — файлы и выборки.

Правил гейта здесь НЕТ: статус, срок, паузу докупки и IPO-паузу считает модуль (б) `last_word.py` (schema.md §3.5);
`gate()` — тонкая обёртка: собирает контекст модуля из решений ключа и отдаёт `gate` его карточки. Обёртка не видит
обзоров недели, снапшота и справочника бумаг, если их не передать: по умолчанию бумага считается держимой акцией без
строк обзора (review_needed, divested и IPO-пауза тогда не появятся) — полное правило с этими входами даёт
`last_word.card`, им пользуются движок «Сейчас» и проверка бэкфилла.

Гейт считается только для акций (решение владельца 28.10): тип ключа — по реестру типов `Portfolio/security-types.json`
(`key_types`; ключ-ISIN без записи — облигация), вызывающий спрашивает гейт только у `stock`.

Здесь же — одна реализация выборки `decisions_digest` (`digest`: команда `decision_write.py digest` и блок решений
`security_digest.py`), чтение условий модулем (а) по корню (`conditions_rows`) и входы модуля (б) из снапшотов корня:
`holding_keys` / `held_keys` («есть в портфеле» — уведомитель, правило 14), `maturities` (даты погашения — правило 14
и проверка «вердикт после погашения» в `apply_condition.py`) и `trade_times` (сделки по истории снапшотов — правила 7,
10, 13; движок «Сейчас» советника).

Читают: `decision_write.py digest`, `security_digest.py`, `prior_digest.py --decisions`,
`assemble_artifact.py` (контекст приоритета). Только чтение; файлы решений пишет только `decision_write.py`.

Зависимости: stdlib (+ codelists.py, ds_schemas.py, conditions_merge.py, last_word.py рядом).
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codelists  # noqa: E402
import conditions_merge as cm  # noqa: E402
import ds_schemas as ds  # noqa: E402
import last_word as lw  # noqa: E402

DECISIONS_REL = ("Portfolio", "decisions")
DEFS_REL = ("Portfolio", "conditions.yaml")
STATE_REL = ("Portfolio", "conditions-state.json")
CONDITIONS_SCHEMA = "conditions@2"
DIGEST_LIMIT = 5
TYPES_REL = ("Portfolio", "security-types.json")
ATTRS_REL = ("Portfolio", "security-attrs.json")
SNAPSHOTS_REL = ("Portfolio", "snapshots")
_SNAP_RE = re.compile(r"^portfolio-(\d{4}-\d{2}-\d{2}).*\.json$")
_ISIN_RE = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")


def decisions_dir(root: str) -> str:
    return os.path.join(root, *DECISIONS_REL)


def load_dir(path: str) -> tuple[list[dict], list[dict]]:
    """Все решения каталога: (валидные, [{file, errors}] — нечитаемые и не прошедшие validate_decision)."""
    items, invalid = [], []
    for p in sorted(glob.glob(os.path.join(path, "*.json"))):
        name = os.path.basename(p)
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError) as exc:
            invalid.append({"file": name, "errors": [f"не читается: {exc}"]})
            continue
        errs = ds.validate_decision(d)
        if errs:
            invalid.append({"file": name, "errors": errs})
            continue
        items.append(d)
    return items, invalid


def load(root: str) -> tuple[list[dict], list[dict]]:
    return load_dir(decisions_dir(root))


def for_key(items: list[dict], key: str) -> list[dict]:
    """Решения ключа, новые первыми («что новее» — только по recorded_at)."""
    return sorted((d for d in items if d.get("key") == key), key=lambda d: d["recorded_at"], reverse=True)


def latest_by_key(items: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for d in items:
        cur = out.get(d["key"])
        if cur is None or d["recorded_at"] > cur["recorded_at"]:
            out[d["key"]] = d
    return out


def gate(decision: dict | None, today: str, *, key: str | None = None, decisions: list[dict] | None = None,
         reviews: list[dict] | None = None, attrs: dict | None = None, in_snapshot: bool = True,
         trades: dict | None = None) -> dict | None:
    """Гейт карточки модуля (б) по ключу решения на дату today (ГГГГ-ММ-ДД) + `status_ru` и `decision_id`.
    decisions — все решения ключа (по умолчанию только это; пауза докупки берётся от новейшего BUY/ADD среди них),
    reviews — строки обзоров ключа, attrs — справочник бумаг, in_snapshot — бумага держится. Решения нет: без `key`
    — None; с `key` — гейт держимой бумаги без решения (статус null или review_needed от строки обзора).
    trades — входы о сделках (`trade_times`): пауза докупки идёт от первой покупки после решения BUY/ADD (правило 7
    модуля (б)); без них паузы нет."""
    if not decision and not key:
        return None
    key = decision["key"] if decision else key
    ctx = {"today": today, "decisions": decisions if decisions is not None else ([decision] if decision else []),
           "reviews": {key: reviews or []}, "security_attrs": attrs, "snapshot_keys": [key] if in_snapshot else [],
           "stock_keys": [key], "first_buy": []}
    ctx.update(trades or {})
    c = lw.card(ctx, key)
    g = dict(c["gate"])
    g["status_ru"] = codelists.ru("gate_status", g["status"], g["status"]) if g["status"] else None
    g["decision_id"] = c["decision_id"]
    return g


def load_attrs(root: str) -> dict | None:
    """Справочник бумаг `security-attrs@1` по корню; нет файла — None."""
    path = os.path.join(root, *ATTRS_REL)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def key_types(root: str) -> dict[str, str | None]:
    """Тип бумаги по реестру типов: {ключ: stock | bond | fund | None}; нет файла — пусто."""
    path = os.path.join(root, *TYPES_REL)
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    by = (doc or {}).get("by_ticker") if isinstance(doc, dict) else None
    return {str(k): (v or {}).get("type") for k, v in (by or {}).items() if isinstance(v, dict)}


def key_type(types: dict, key: str) -> str | None:
    """stock | bond | fund | None: запись реестра; без записи ключ-ISIN — облигация, иначе неизвестно."""
    t = types.get(key)
    if t:
        return t
    return "bond" if _ISIN_RE.fullmatch(str(key or "")) else None


def snapshot_files(root: str) -> list[tuple[str, str]]:
    """Снапшоты портфеля `Portfolio/snapshots/portfolio-ГГГГ-ММ-ДД*.json`: [(дата из имени, путь)] по возрастанию
    (внутри дня — по имени). Нет папки — пусто."""
    d = os.path.join(root, *SNAPSHOTS_REL)
    try:
        names = os.listdir(d)
    except OSError:
        return []
    out = [(m.group(1), os.path.join(d, n)) for n in names for m in [_SNAP_RE.match(n)] if m]
    return sorted((x for x in out if os.path.isfile(x[1])), key=lambda x: (x[0], os.path.basename(x[1])))


def _qty_pos(h: dict) -> bool:
    try:
        return float(h.get("qty")) > 0
    except (TypeError, ValueError):
        return False


def holding_keys(snapshot: dict | None) -> list[str]:
    """Вход `snapshot_keys` модуля (б) из снапшота: тикер и ISIN каждой бумаги с количеством > 0, кроме кандидатов
    первой покупки (`first_buy`). Та же форма, что `lwCtx` вьюера: бумаги нет в списке — её нет в портфеле
    (правило 14 модуля (б): held)."""
    out = set()
    for h in (snapshot or {}).get("holdings") or [] if isinstance(snapshot, dict) else []:
        if isinstance(h, dict) and not h.get("first_buy") and _qty_pos(h):
            out.update(k for k in (h.get("ticker"), h.get("isin")) if k)
    return sorted(out)


def held_keys(root: str) -> set[str] | None:
    """Ключи бумаг портфеля по последнему снапшоту корня (`holding_keys`); снапшота нет или он не читается — None
    (вызывающий тогда не фильтрует по портфелю)."""
    files = snapshot_files(root)
    if not files:
        return None
    try:
        with open(files[-1][1], encoding="utf-8") as f:
            snap = json.load(f)
    except (OSError, ValueError):
        return None
    return set(holding_keys(snap)) if isinstance(snap, dict) else None


def trade_times(paths: list[str], upto: str | None = None) -> dict[str, dict]:
    """Входы модуля (б) о сделках из истории снапшотов (ЗЕРКАЛО `dsLastTradeAt` вьюера): количество по ключу (тикер и
    ISIN, сумма по всем записям) сравнивается с предыдущим снапшотом; изменение — сделка в день снапшота
    (`ГГГГ-ММ-ДДT00:00:00+03:00`, as_of_date, иначе дата из имени). paths — файлы снапшотов в любом порядке (сортируются
    по дате из имени, внутри дня — по имени); upto — не позже этой даты. Выход: {last_trade_at, last_sell_at,
    last_buy_at: {ключ: время}, buys_at: {ключ: [время по возрастанию]}} — для правил 7, 10, 13 модуля (б).
    Нечитаемый файл пропускается."""
    items = []
    for p in paths:
        m = _SNAP_RE.match(os.path.basename(p))
        if m and (upto is None or m.group(1) <= upto):
            items.append((m.group(1), os.path.basename(p), p))
    trade: dict[str, str] = {}
    sell: dict[str, str] = {}
    buy: dict[str, str] = {}
    buys: dict[str, list[str]] = {}
    prev = None
    for name_day, _, path in sorted(items):
        try:
            with open(path, encoding="utf-8") as f:
                snap = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(snap, dict):
            continue
        q: dict[str, float] = {}
        for h in snap.get("holdings") or []:
            if not isinstance(h, dict):
                continue
            try:
                qty = float(h.get("qty") or 0)
            except (TypeError, ValueError):
                qty = 0.0
            for k in (h.get("ticker"), h.get("isin")):
                if k:
                    q[k] = q.get(k, 0.0) + qty
        day = str(snap.get("as_of_date") or "")[:10] or name_day
        if prev is not None:
            at = f"{day}T00:00:00+03:00"
            for k in set(q) | set(prev):
                dq = q.get(k, 0.0) - prev.get(k, 0.0)
                if abs(dq) >= 1:
                    trade[k] = at
                if dq <= -1:
                    sell[k] = at
                if dq >= 1:
                    buy[k] = at
                    if at not in buys.setdefault(k, []):
                        buys[k].append(at)
        prev = q
    return {"last_trade_at": trade, "last_sell_at": sell, "last_buy_at": buy, "buys_at": buys}


_PLAN_PATH_RE = re.compile(r"^stocks\.([^.]+)\.(user_plan|plan_pct)$")


def plan_changed_at(path: str) -> dict[str, str]:
    """Время последней правки плана по бумаге из журнала плана `Portfolio/plan-journal.jsonl` (строки с path
    `stocks.<ключ>.user_plan` или `stocks.<ключ>.plan_pct`; статус исполнения и заметки — не правка плана): {ключ: ts}.
    Вход `plan_changed_at` неразворота «Сейчас» (§10.6 п.6). Нет файла — пусто; битая строка пропускается."""
    out: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return out
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        m = _PLAN_PATH_RE.match(str((e or {}).get("path") or "")) if isinstance(e, dict) else None
        ts = str(e.get("ts") or "") if m else ""
        if m and ts and ts > out.get(m.group(1), ""):
            out[m.group(1)] = ts
    return out


def maturities(root: str, keys=None) -> dict[str, str]:
    """Даты погашения облигаций `{ключ: ГГГГ-ММ-ДД}` (вход `maturities` модуля (б), проверка «вердикт после
    погашения» валидатора условий): `maturity_date` записей снапшотов корня — от новейшего к старому, первое
    найденное по ключу (тикер и ISIN). keys — нужные ключи: чтение останавливается, когда найдены все."""
    want = set(keys) if keys is not None else None
    out: dict[str, str] = {}
    for _, path in reversed(snapshot_files(root)):
        try:
            with open(path, encoding="utf-8") as f:
                snap = json.load(f)
        except (OSError, ValueError):
            continue
        for h in (snap.get("holdings") or []) if isinstance(snap, dict) else []:
            m = h.get("maturity_date") if isinstance(h, dict) else None
            if not ds.is_date(str(m)[:10] if m else None):
                continue
            for k in (h.get("ticker"), h.get("isin")):
                if k and k not in out and (want is None or k in want):
                    out[k] = str(m)[:10]
        if want is not None and want <= set(out):
            break
    return out


def conditions_rows(root: str, today: str) -> tuple[list[dict], bool]:
    """Плоские строки модуля (а) на today по корню: (строки, нет файла определений). Формат не conditions@2 — ValueError."""
    defs_path, state_path = os.path.join(root, *DEFS_REL), os.path.join(root, *STATE_REL)
    if not os.path.isfile(defs_path):
        return [], True
    doc = cm.load_yaml(defs_path)
    if not isinstance(doc, dict) or doc.get("schema_version") != CONDITIONS_SCHEMA:
        sv = doc.get("schema_version") if isinstance(doc, dict) else None
        raise ValueError(f"{defs_path}: формат {sv!r}, нужен {CONDITIONS_SCHEMA}")
    state = {"events": []}
    if os.path.isfile(state_path):
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
    return cm.merge(doc.get("conditions") or [], state, today), False


def _digest_row(d: dict) -> dict:
    src = d["source"]
    return {
        "id": d["id"], "recorded_at": d["recorded_at"], "verdict": d["verdict"],
        "verdict_ru": codelists.ru("verdict", d["verdict"]), "target_pct": d["target_pct"],
        "review_by": d["review_by"], "note": d["note"], "confidence": d.get("confidence"),
        "author": d["author"], "source": src["kind"], "doc": src["doc"], "mode_codes": src["mode_codes"],
        "stress_id": src.get("stress_id"), "conditions_created": d["conditions_created"],
        "conditions_resolved": d["conditions_resolved"],
    }


def digest(root: str, key: str, today: str, limit: int = DIGEST_LIMIT) -> dict:
    """Выборка решений по ключу: items — последние решения (новые первыми); latest — последнее решение строкой
    с гейтом (только акции; модуль (б) через `gate`, справочник бумаг корня — для IPO-паузы) и статусами его
    conditions_created/resolved по модулю (а) на today; invalid_files — файлы, не прошедшие валидатор."""
    all_items, invalid = load(root)
    mine = for_key(all_items, key)
    out = {"key": key, "today": today, "count": len(mine), "shown": min(len(mine), limit),
           "items": [_digest_row(d) for d in mine[:limit]], "latest": None, "invalid_files": invalid}
    if mine:
        last = mine[0]
        rows, missing = conditions_rows(root, today)
        status = {r["id"]: r["status"] for r in rows}
        ktype = key_type(key_types(root), key)
        out["latest"] = {
            "id": last["id"], "recorded_at": last["recorded_at"], "verdict": last["verdict"],
            "verdict_ru": codelists.ru("verdict", last["verdict"]), "target_pct": last["target_pct"],
            "review_by": last["review_by"], "note": last["note"], "key_type": ktype,
            "gate": gate(last, today, decisions=mine, attrs=load_attrs(root),
                         trades=trade_times([p for _, p in snapshot_files(root)], today)) if ktype == "stock" else None,
            "conditions_created": [{"id": c, "status": status.get(c)} for c in last["conditions_created"]],
            "conditions_resolved": [{"id": c, "status": status.get(c)} for c in last["conditions_resolved"]],
        }
        if missing:
            out["latest"]["conditions_missing"] = True
    return out
