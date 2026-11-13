#!/usr/bin/env python3
"""Аудит качества учёта ZenMoney (режим D скилла zenmoney-analyst).

Детерминированные проверки над сохранёнными ответами MCP: числа считает код,
модель только объясняет и предлагает правки. Правила проверок — references/audit.md.

Вход — файлы с ответами MCP как есть (`{data, references, nextCursor}`) или
обёрнутые средой (`[{"type": "text", "text": "<json>"}]`):
  --tx         страницы list_transactions (можно несколько; окно ≥ 90 дней до --as-of
               для проверки B6; для квартала — 12 месяцев)
  --categories ответ list_categories (нужен для C-проверок и D13)
  --rates      ответы get_instrument_rates (необязательно; без них валютные суммы
               не пересчитываются и считаются отдельно)
  --config     JSON с решениями из карты (необязательно, см. load_config)
  --accepted   принятые исключения: accepted.json или список [{"id": ..., "check": ...}]
  --history    history.json — перепроверка прошлых замечаний, доля исправленного, тренд

Режимы:
  needs-rates  какие валюты и даты нужны для пересчёта (вызвать get_instrument_rates)
  month        проверки A + B за --month, статистика
  quarter      то же + проверки C за окно всех переданных операций
  places       только места платежа за всё окно (вместе с филиалами сетей) —
               «проверь места платежа»

Места платежа (`places`, 2026-10-07) — подсказки, а не замечания: в долю «без
замечаний» и в реестр истории не входят. В month — места, по которым были траты
в месяце; в quarter и places — всё окно; филиалы сетей — только в quarter/places.

Только stdlib. Ничего не пишет, результат — JSON в stdout.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

CORRECTION_NAMES = {"корректировка"}
SYNC_WINDOW_DAYS = 90
SYNC_SILENT_DAYS = 7
SYNC_MIN_OPS = 5
TRIP_GRACE_DAYS = 30
INACTIVE_DAYS = 365


# ─── загрузка ────────────────────────────────────────────────────────────────

def load_mcp(path: str | Path):
    """JSON ответа MCP; снимает обёртку среды [{"type":"text","text":...}]."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, list) and raw and isinstance(raw[0], dict) and "text" in raw[0]:
        raw = json.loads("".join(part.get("text", "") for part in raw))
    return raw


def merge_pages(paths):
    """Операции всех страниц (дубли по id убираются) + объединённые references."""
    ops, refs = {}, {"accounts": {}, "categories": {}, "merchants": {}, "user": {}}
    for p in paths:
        page = load_mcp(p)
        for op in page.get("data", []):
            ops[op["id"]] = op
        r = page.get("references") or {}
        for key in ("accounts", "categories", "merchants"):
            refs[key].update(r.get(key) or {})
        if r.get("user"):
            refs["user"] = r["user"]
    return sorted(ops.values(), key=lambda o: (o["date"], o["id"])), refs


def load_categories(path):
    if not path:
        return None
    data = load_mcp(path)
    items = data.get("data", data) if isinstance(data, dict) else data
    return {c["id"]: c for c in items}


def load_rates(paths):
    """{(инструмент, дата): курс к RUB}; null-курсы пропускаются."""
    rates = {}
    for p in paths or []:
        for r in load_mcp(p).get("data", []):
            if r.get("rate") is not None:
                rates[(r["instrument"], r["date"])] = float(r["rate"])
    return rates


def load_config(path):
    """Решения пользователя из карты (всё необязательно):
    {
      "correction_ids": [...],        # «Корректировка» (иначе — по названию)
      "project_ids": [...],           # проекты-теги (иначе — категории с «#» в начале)
      "travel_parent_id": "...",      # «Путешествия» (иначе — по названию)
      "trip_end": {"<id>": "YYYY-MM-DD"},
      "rare_category_ids": [...],     # «Редкие категории» карты: C11 их не предлагает
      "off_balance_ok_account_ids": [...],           # счета вне баланса, где это норма (B7)
      "known_account_prefixes": ["1a2b3c4d", ...],   # реестр карты (B8)
      "accounts_file": "list_accounts.json"          # для B8, иначе B8 пропускается
    }"""
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_accepted(path):
    """Принятые исключения: список или {"items": [...]} (формат accepted.json, audit_history.py)."""
    if not path or not Path(path).exists():
        return set()
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    items = raw.get("items", []) if isinstance(raw, dict) else raw
    return {(a["id"], a["check"]) for a in items}


def load_a2_kinds(path):
    """Вид принятых корректировок {id: transfer_out|unrecorded|unknown} из accepted.json."""
    if not path or not Path(path).exists():
        return {}
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    items = raw.get("items", []) if isinstance(raw, dict) else raw
    return {a["id"]: a["kind"] for a in items if a.get("check") == "A2" and a.get("kind")}


def load_history(path):
    """history.json (audit_history.py) или None, если файла нет."""
    if not path or not Path(path).exists():
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ─── вспомогательное ────────────────────────────────────────────────────────

def d(s: str) -> date:
    return date.fromisoformat(s)


def kind(op) -> str:
    e, i = op.get("expense"), op.get("income")
    if e and i:
        return "transfer"
    return "expense" if e else "income"


def side(op):
    return op.get("expense") or op.get("income")


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower().replace("ё", "е")
    return re.sub(r"[^\w#]+", "", s)


def lev1(a: str, b: str) -> bool:
    """Расстояние Левенштейна ≤ 1."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


def month_bounds(month: str, start_day: int = 1):
    """Финансовый месяц «YYYY-MM» с учётом monthStartDay."""
    y, m = map(int, month.split("-"))
    start = date(y, m, min(start_day, 28))
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return start, date(ny, nm, min(start_day, 28)) - timedelta(days=1)


class Ctx:
    def __init__(self, ops, refs, cats, rates, cfg, accepted):
        self.ops, self.refs, self.rates, self.cfg, self.accepted = ops, refs, rates, cfg, accepted
        self.a2_kinds = {}             # вид принятых корректировок (load_a2_kinds)
        # полный список категорий дополняет references, а не заменяет: категория, которой нет
        # в файле (неполный или устаревший список), иначе теряет isExpense — и возврат покупки
        # молча становится «компенсацией» (Вьетнам'26: 2 500 ₽ за такси, 2026-10-05)
        self.cats = {**(refs.get("categories") or {}), **(cats or {})}
        self.main = (refs.get("user") or {}).get("currency", "RUB")
        self.missing = set()           # (операция, счёт, валюта) без курса

        def by_name(names):
            return {cid for cid, c in self.cats.items() if norm_name(c.get("name", "")) in names}

        self.correction_ids = set(cfg.get("correction_ids") or by_name(CORRECTION_NAMES))
        self.project_ids = set(cfg.get("project_ids") or
                               {cid for cid, c in self.cats.items() if c.get("name", "").lstrip().startswith("#")})
        tp = cfg.get("travel_parent_id")
        self.travel_parent = tp or next(iter(sorted(by_name({"путешествия"}))), None)

    def acc(self, acc_id):
        return self.refs["accounts"].get(acc_id, {})

    def rub(self, op, s=None):
        """Сумма стороны в основной валюте; None — нет курса."""
        s = s or side(op)
        inst = self.acc(s["accountId"]).get("instrument", self.main)
        amt = float(s["amount"])
        if inst == self.main:
            return amt
        r_from = self.rates.get((inst, op["date"]))
        r_main = 1.0 if self.main == "RUB" else self.rates.get((self.main, op["date"]))
        if r_from is None or r_main is None:
            self.missing.add((op["id"], s["accountId"], inst))
            return None
        return amt * r_from / r_main

    def ok(self, op_id, check):
        return (op_id, check) not in self.accepted

    def cat_name(self, cid):
        return (self.cats.get(cid) or {}).get("name", cid)


# ─── needs-rates ─────────────────────────────────────────────────────────────

def needs_rates(ctx, start, end):
    need = defaultdict(set)
    for op in ctx.ops:
        if not (start <= d(op["date"]) <= end):
            continue
        for s in (op.get("expense"), op.get("income")):
            if s:
                inst = ctx.acc(s["accountId"]).get("instrument", ctx.main)
                if inst != ctx.main:
                    need[inst].add(op["date"])
    return {inst: sorted(ds) for inst, ds in sorted(need.items())}


# ─── проверки A ──────────────────────────────────────────────────────────────

def a1_transfer_pairs(ctx, ops):
    """Перевод между своими счетами, записанный расходом + доходом."""
    own = lambda a: ctx.acc(a).get("type") not in ("debt", "loan") and not ctx.acc(a).get("isOtherUser")
    exp = [o for o in ops if kind(o) == "expense" and own(o["expense"]["accountId"])]
    inc = [o for o in ops if kind(o) == "income" and own(o["income"]["accountId"])]
    used, found = set(), []
    for e in exp:
        ea, ev = e["expense"]["accountId"], float(e["expense"]["amount"])
        if ev <= 0:
            continue
        for i in inc:
            ia = i["income"]["accountId"]
            if i["id"] in used or ia == ea:
                continue
            if ctx.acc(ia).get("instrument") != ctx.acc(ea).get("instrument"):
                continue
            if abs(float(i["income"]["amount"]) - ev) > 0.005:
                continue
            if abs((d(i["date"]) - d(e["date"])).days) > 1:
                continue
            if not (ctx.ok(e["id"], "A1") and ctx.ok(i["id"], "A1")):
                continue
            used.add(i["id"])
            found.append({"expense_id": e["id"], "income_id": i["id"], "date": e["date"],
                          "amount": ev, "rub": ctx.rub(e),
                          "from": ctx.acc(ea).get("name"), "to": ctx.acc(ia).get("name"),
                          "categories": [ctx.cat_name(e.get("categoryId")), ctx.cat_name(i.get("categoryId"))]})
            break
    return found


def a2_corrections(ctx, ops):
    """Замечания — только непринятые корректировки; `all_*` — все, включая принятые: доля
    незаписанного в тратах — факт учёта, и он не должен зависеть от того, когда нажали «принять».
    Исключение — принятые с видом transfer_out (перевод себе на счёт вне учёта): это не трата,
    они в `transfer_out_rub`, а не в `all_expense_rub`."""
    every = [o for o in ops if kind(o) != "transfer" and o.get("categoryId") in ctx.correction_ids]
    rows = [o for o in every if ctx.ok(o["id"], "A2")]
    exp = [o for o in every if kind(o) == "expense"]
    out_ = [o for o in exp if ctx.a2_kinds.get(o["id"]) == "transfer_out"]
    out = {"count": len(rows), "expense_rub": 0.0, "income_rub": 0.0, "in_trips": 0, "in_trips_rub": 0.0, "ids": [],
           "all_count": len(every),
           "all_expense_rub": sum(ctx.rub(o) or 0.0 for o in exp if o not in out_),
           "transfer_out_rub": sum(ctx.rub(o) or 0.0 for o in out_)}
    for o in rows:
        v = ctx.rub(o) or 0.0
        out["expense_rub" if kind(o) == "expense" else "income_rub"] += v
        if set(o.get("tagIds") or []) & ctx.project_ids:
            out["in_trips"] += 1
            out["in_trips_rub"] += v
        out["ids"].append(o["id"])
    out["items"] = [a2_item(ctx, o) for o in rows]
    return out


def a2_item(ctx, o):
    """Карточка корректировки для вопроса «что это было»: признаки, а не вердикт. Вид решает
    пользователь (accept --kind); подсказки на метрику не влияют."""
    s = side(o)
    acc, amt, d0 = s["accountId"], float(s["amount"]), d(o["date"])
    hints = []
    bank = o.get("source") == "plugin"
    if kind(o) == "expense":
        if bank and not o.get("merchantId") and o.get("comment"):
            hints.append("из банка, без места платежа, с получателем в комментарии — похоже на перевод "
                         "(себе на счёт вне учёта или человеку)")
        if not o.get("source"):
            hints.append("внесена вручную — похоже на выравнивание остатка")
        for x in ctx.ops:
            if x["id"] == o["id"]:
                continue
            gap = (d0 - d(x["date"])).days
            xi, xe = x.get("income"), x.get("expense")
            if (0 <= gap <= 3 and kind(x) == "income" and xi["accountId"] == acc
                    and abs(float(xi["amount"]) - amt) < 0.01):
                hints.append(f"за {gap} дн. до этого на этот счёт пришло столько же ({x['date']}, "
                             f"{ctx.cat_name(x.get('categoryId'))}) — деньги ушли целиком дальше")
            if (abs(gap) <= 1 and kind(x) == "transfer" and xe["accountId"] != acc
                    and abs(float(xe["amount"]) - amt) < 0.01):
                hints.append(f"{x['date']} перевод на ту же сумму с другого счёта "
                             f"({ctx.acc(xe['accountId']).get('name')}) — возможно, записан не на тот счёт")
    if set(o.get("tagIds") or []) & ctx.project_ids:
        hints.append("с тегом поездки — похоже на незаписанные траты в поездке")
    return {"id": o["id"], "date": o["date"], "kind": kind(o), "rub": round(ctx.rub(o) or 0.0, 2),
            "account": ctx.acc(acc).get("name"), "source": "банк" if bank else "вручную",
            "comment": o.get("comment"), "hints": hints}


def a3_no_category(ctx, ops):
    return [{"id": o["id"], "date": o["date"], "rub": ctx.rub(o), "account": ctx.acc(side(o)["accountId"]).get("name")}
            for o in ops if kind(o) != "transfer" and not o.get("categoryId") and ctx.ok(o["id"], "A3")]


def suggest_category(ctx, op, history):
    """Статья для операции, у которой проект стоит основной категорией."""
    mid = op.get("merchantId")
    if mid:
        c = Counter(h["categoryId"] for h in history
                    if h.get("merchantId") == mid and h.get("categoryId")
                    and h["categoryId"] not in ctx.project_ids and h["categoryId"] not in ctx.correction_ids)
        if c:
            cid, n = c.most_common(1)[0]
            return {"categoryId": cid, "name": ctx.cat_name(cid), "basis": f"та же точка, {n} операций"}
    return None


def a4_project_as_category(ctx, ops, history):
    out = []
    for o in ops:
        if kind(o) == "transfer" or o.get("categoryId") not in ctx.project_ids or not ctx.ok(o["id"], "A4"):
            continue
        m = o.get("merchantId")
        out.append({"id": o["id"], "date": o["date"], "rub": ctx.rub(o), "project": ctx.cat_name(o["categoryId"]),
                    "merchant": (ctx.refs["merchants"].get(m) or {}).get("name") if m else None,
                    "comment": o.get("comment"), "suggest": suggest_category(ctx, o, history)})
    return out


def a5_duplicates(ctx, ops):
    groups = defaultdict(list)
    for o in ops:
        if kind(o) == "transfer":
            continue
        s = side(o)
        groups[(o["date"], s["accountId"], float(s["amount"]), kind(o), o.get("merchantId"))].append(o)
    out = []
    for (dt, acc, amt, _k, mid), g in groups.items():
        ids = [o["id"] for o in g]
        if len(g) < 2 or not all(ctx.ok(i, "A5") for i in ids):
            continue
        out.append({"ids": ids, "date": dt, "amount": amt, "account": ctx.acc(acc).get("name"),
                    "merchant": (ctx.refs["merchants"].get(mid) or {}).get("name") if mid else None})
    return out


# ─── проверки B ──────────────────────────────────────────────────────────────

def b6_silent_sync(ctx, as_of):
    """Синхронизируемый счёт замолчал.

    Учитываются только расходы и доходы из банка (`source: plugin`), без переводов:
    у перевода пометка общая на обе стороны, и молчащим выглядел бы счёт-получатель.
    Порог свой у каждого счёта: тишина дольше max(7 дней, самой длинной паузы между
    его операциями в окне). Нужно ≥ SYNC_MIN_OPS операций — редкие счета не судим.
    """
    dates = defaultdict(set)
    for o in ctx.ops:
        if o.get("source") != "plugin" or kind(o) == "transfer":
            continue
        dt = d(o["date"])
        if dt > as_of or (as_of - dt).days > SYNC_WINDOW_DAYS:
            continue
        a = side(o)["accountId"]
        if ctx.acc(a).get("type") not in ("debt", "loan"):
            dates[a].add(dt)
    out = []
    for a, ds in dates.items():
        ds = sorted(ds)
        if len(ds) < SYNC_MIN_OPS:
            continue
        max_gap = max((y - x).days for x, y in zip(ds, ds[1:]))
        silent = (as_of - ds[-1]).days
        if silent > max(SYNC_SILENT_DAYS, max_gap) and ctx.ok(a, "B6"):
            out.append({"account": ctx.acc(a).get("name"), "accountId": a, "last_plugin_date": ds[-1].isoformat(),
                        "silent_days": silent, "usual_max_gap": max_gap, "ops_in_window": len(ds)})
    return sorted(out, key=lambda x: -x["silent_days"])


def b7_off_balance(ctx, ops):
    """Траты со счетов вне баланса — их нет в отчёте ZenMoney. Не считаются: траты с тегом
    поездки (кошелёк поездки вне баланса — норма), инвестиции, займы, расчёты с партнёром
    (группы исключений статистики) и счета из `off_balance_ok_account_ids` карты."""
    from month_stats import Stats      # month_stats импортирует этот модуль — импорт здесь
    st = Stats(ctx)
    ok_accounts = set(ctx.cfg.get("off_balance_ok_account_ids") or [])
    agg = defaultdict(lambda: {"count": 0, "rub": 0.0})
    for o in ops:
        if kind(o) != "expense" or o["expense"]["accountId"] in ok_accounts:
            continue
        if set(o.get("tagIds") or []) & ctx.project_ids or o.get("categoryId") in ctx.project_ids:
            continue
        if st.group(o.get("categoryId")) not in (None, "corrections"):
            continue
        a = ctx.acc(o["expense"]["accountId"])
        if a.get("isInBalance") is False and a.get("type") not in ("debt", "loan"):
            r = agg[a.get("name", o["expense"]["accountId"])]
            r["count"] += 1
            r["rub"] += ctx.rub(o) or 0.0
    return [{"account": k, "count": v["count"], "rub": round(v["rub"], 2)} for k, v in sorted(agg.items())]


def b8_new_accounts(ctx):
    path = ctx.cfg.get("accounts_file")
    known = ctx.cfg.get("known_account_prefixes")
    if not path or known is None:
        return None   # нет данных — проверка пропущена
    accounts = load_mcp(path).get("data", [])
    known = {k[:8] for k in known}
    return [{"name": a["name"], "instrument": a.get("instrument"), "type": a.get("type"), "prefix": a["id"][:8]}
            for a in accounts if a["id"][:8] not in known and a.get("type") not in ("debt",)]


# ─── проверки C и D ──────────────────────────────────────────────────────────

def c9_name_twins(ctx):
    live = [(cid, c) for cid, c in ctx.cats.items() if not c.get("isArchived")]
    out = []
    for i, (a, ca) in enumerate(live):
        for b, cb in live[i + 1:]:
            na, nb = norm_name(ca["name"]), norm_name(cb["name"])
            if na == nb or (min(len(na), len(nb)) >= 5 and lev1(na, nb)):
                out.append({"a": ca["name"], "a_parent": ctx.cat_name(ca.get("parentId")) if ca.get("parentId") else None,
                            "b": cb["name"], "b_parent": ctx.cat_name(cb.get("parentId")) if cb.get("parentId") else None,
                            "ids": [a, b], "exact": na == nb})
    return out


def used_categories(ops):
    """{id: последняя дата} — как основная категория и как тег."""
    last = {}
    for o in ops:
        for cid in [o.get("categoryId")] + list(o.get("tagIds") or []):
            if cid:
                last[cid] = max(last.get(cid, o["date"]), o["date"])
    return last


def c11_inactive(ctx, as_of, window_start):
    """Кандидаты без операций в окне. Окно короче года — проверка не делается."""
    if (as_of - window_start).days < INACTIVE_DAYS - 1:
        return None
    last = used_categories(ctx.ops)
    active_parents = {(ctx.cats.get(c) or {}).get("parentId") for c in last}
    rare = set(ctx.cfg.get("rare_category_ids") or [])
    return [{"id": cid, "name": c["name"], "parent": ctx.cat_name(c["parentId"]) if c.get("parentId") else None}
            for cid, c in sorted(ctx.cats.items(), key=lambda kv: kv[1]["name"])
            if not c.get("isArchived") and cid not in last and cid not in active_parents and cid not in rare
            and ctx.ok(cid, "C11")]


def c12_trips_not_moved(ctx, as_of):
    last = used_categories(ctx.ops)
    ends = ctx.cfg.get("trip_end") or {}
    out = []
    for cid in ctx.project_ids:
        c = ctx.cats.get(cid) or {}
        if c.get("isArchived") or c.get("parentId") or not ctx.ok(cid, "C12"):
            continue
        end = ends.get(cid) or last.get(cid)
        if end and (as_of - d(end)).days > TRIP_GRACE_DAYS:
            out.append({"id": cid, "name": c.get("name"), "end": end, "end_basis": "карта" if cid in ends else "последняя операция",
                        "days_since": (as_of - d(end)).days})
    return out


def d13_parent_with_children(ctx, ops):
    parents = {c.get("parentId") for c in ctx.cats.values() if c.get("parentId") and not c.get("isArchived")}
    n = Counter(ctx.cat_name(o["categoryId"]) for o in ops
                if kind(o) != "transfer" and o.get("categoryId") in parents)
    return dict(n.most_common())


def parent_direct(ctx, month_ops):
    """Траты месяца прямо в категории, у которой есть подкатегории (решение 2026-10-07:
    у такой категории трат в ней самой быть не должно — иначе «без подкатегории» мешает
    сравнивать подкатегории и места по годам). Подсказка «закрой месяц», как места
    платежа: в долю «без замечаний» и в историю не входит. «Так и задумано» —
    accepted.json, проверка D13, по id операции."""
    parents = {c.get("parentId") for c in ctx.cats.values() if c.get("parentId") and not c.get("isArchived")}
    items = []
    for o in month_ops:
        if kind(o) != "expense" or o.get("categoryId") not in parents or not ctx.ok(o["id"], "D13"):
            continue
        v = ctx.rub(o)
        items.append({"id": o["id"], "date": o["date"], "rub": round(v, 2) if v is not None else None,
                      "category": ctx.cat_name(o["categoryId"]),
                      "merchant": (ctx.refs["merchants"].get(o.get("merchantId")) or {}).get("name") if o.get("merchantId") else None,
                      "comment": o.get("comment") or None})
    items.sort(key=lambda x: (x["date"], x["category"]))
    return {"count": len(items), "items": items}


# ─── статистика ──────────────────────────────────────────────────────────────

def spending_with_corrections(ctx, ops):
    """Траты месяца на той же базе, что `month_stats.py` (без инвестиций, кешбэка, партнёра,
    займов, категории «Возврат»; минус возвраты покупок), но С корректировками — знаменатель
    доли незаписанного: «траты месяца» в истории аудита и в spending.json не расходятся
    больше, чем на сами корректировки. Переводы себе вне учёта (transfer_out) — не траты."""
    from month_stats import Stats      # month_stats импортирует этот модуль — импорт здесь
    st = Stats(ctx)
    total = 0.0
    for o in ops:
        k, g = kind(o), st.group(o.get("categoryId"))
        if g not in (None, "corrections") or (g == "corrections" and k != "expense"):
            continue
        if k == "expense":
            if g == "corrections" and ctx.a2_kinds.get(o["id"]) == "transfer_out":
                continue
            total += ctx.rub(o) or 0.0
        elif st.is_refund(o):
            total -= ctx.rub(o) or 0.0
    return total


def stats(ctx, ops, res):
    """Доля чистых операций и итоги по типам. Транзиты (переводы) не считаются."""
    base = [o for o in ops if kind(o) != "transfer"]
    flagged = defaultdict(set)
    for p in res["A1"]:
        flagged["A1"].update([p["expense_id"], p["income_id"]])
    flagged["A2"].update(res["A2"]["ids"])
    flagged["A3"].update(x["id"] for x in res["A3"])
    flagged["A4"].update(x["id"] for x in res["A4"])
    for g in res["A5"]:
        flagged["A5"].update(g["ids"])
    any_flag = set().union(*flagged.values()) if flagged else set()
    by_id = {o["id"]: o for o in base}
    total_abs = sum(abs(ctx.rub(o) or 0.0) for o in base)
    flag_abs = sum(abs(ctx.rub(by_id[i]) or 0.0) for i in any_flag if i in by_id)
    expense_rub = spending_with_corrections(ctx, base)
    by_check = {k: {"count": len(v), "rub": round(sum(abs(ctx.rub(by_id[i]) or 0.0) for i in v if i in by_id), 2)}
                for k, v in sorted(flagged.items())}
    return {
        "operations": len(base),
        "flagged": len(any_flag),
        "clean_share_count": round(1 - len(any_flag) / len(base), 4) if base else None,
        "clean_share_rub": round(1 - flag_abs / total_abs, 4) if total_abs else None,
        "expense_rub": round(expense_rub, 2),
        "correction_rub": round(res["A2"]["all_expense_rub"], 2),
        "correction_transfer_out_rub": round(res["A2"]["transfer_out_rub"], 2),
        "correction_share_of_expense": round(res["A2"]["all_expense_rub"] / expense_rub, 4) if expense_rub else None,
        "by_check": by_check,
    }


# ─── замечания как ключи и история ───────────────────────────────────────────

def a_checks(ctx, month_ops, ops):
    return {
        "A1": a1_transfer_pairs(ctx, month_ops),
        "A2": a2_corrections(ctx, month_ops),
        "A3": a3_no_category(ctx, month_ops),
        "A4": a4_project_as_category(ctx, month_ops, ops),
        "A5": a5_duplicates(ctx, month_ops),
    }


def issue_keys(res):
    """{ключ «проверка:id»: проверка}. Только ID — ни сумм, ни названий (это уходит в историю)."""
    keys = {}
    for p in res.get("A1") or []:
        keys[f"A1:{p['expense_id']}"] = keys[f"A1:{p['income_id']}"] = "A1"
    for i in (res.get("A2") or {}).get("ids", []):
        keys[f"A2:{i}"] = "A2"
    for chk in ("A3", "A4"):
        for x in res.get(chk) or []:
            keys[f"{chk}:{x['id']}"] = chk
    for g in res.get("A5") or []:
        for i in g["ids"]:
            keys[f"A5:{i}"] = "A5"
    for x in res.get("B6") or []:
        keys[f"B6:{x['accountId']}"] = "B6"
    for x in res.get("C9") or []:
        keys[f"C9:{'|'.join(sorted(x['ids']))}"] = "C9"
    for chk in ("C11", "C12"):
        for x in res.get(chk) or []:
            keys[f"{chk}:{x['id']}"] = chk
    return keys


def age_bucket(first_seen: str, as_of: date) -> str:
    days = (as_of - d(first_seen)).days
    return "lt_1m" if days < 31 else ("1_3m" if days <= 92 else "gt_3m")


def recheck_history(ctx, hist, args, as_of, window_start, cur_keys, start_day):
    """Что стало с замечаниями, открытыми на прошлых аудитах.

    Замечание A-группы перепроверяется прогоном A-проверок по ЕГО месяцу, если месяц
    целиком в окне операций; иначе — not_rechecked (не «исправлено»: отсутствие
    в текущем месяце ничего не доказывает). B6 — по текущему прогону; C — только в quarter.
    """
    issues = (hist or {}).get("issues", {})
    by_month, out = {}, {"fixed": [], "still_open": [], "not_rechecked": [], "accepted": []}
    for key, it in sorted(issues.items()):
        if it.get("status") != "open":
            continue
        chk, ident = it["check"], key.split(":", 1)[1]
        if (ident, chk) in ctx.accepted:
            out["accepted"].append(key)
            continue
        if chk.startswith("A"):
            m = it["month"]
            if m == args.month:
                out["still_open" if key in cur_keys else "fixed"].append(key)
                continue
            ms, me = month_bounds(m, start_day)
            if ms < window_start or me > as_of:
                out["not_rechecked"].append(key)
                continue
            if m not in by_month:
                mops = [o for o in ctx.ops if ms <= d(o["date"]) <= me]
                by_month[m] = issue_keys(a_checks(ctx, mops, ctx.ops))
            out["still_open" if key in by_month[m] else "fixed"].append(key)
        elif chk == "B6" or (chk.startswith("C") and args.mode == "quarter"):
            out["still_open" if key in cur_keys else "fixed"].append(key)
        else:
            out["not_rechecked"].append(key)
    # открытые = перепроверенные и не исправленные + НЕ перепроверенные (месяц вне окна): они тоже открыты и входят
    # в open_total истории — без них разбивка по возрасту «0 · 0 · 0» противоречит «Открыто: 1» на странице
    open_now = {k: it for k, it in issues.items() if k in set(out["still_open"]) | set(out["not_rechecked"])}
    for k in cur_keys:
        if k not in open_now:
            open_now[k] = {"first_seen": as_of.isoformat()}
    ages = Counter(age_bucket(it.get("first_seen", as_of.isoformat()), as_of) for it in open_now.values())
    prev = [r for r in (hist or {}).get("records", []) if r["month"] < args.month]
    prev = prev[-1] if prev else None
    # Доля исправленного — только по замечаниям ПРОШЛЫХ месяцев. Повторный аудит того же
    # месяца считается отдельно: «0 из 9 исправлено» за час между прогонами — не метрика.
    is_prev = lambda k: issues[k]["month"] < args.month
    fixed_p = [k for k in out["fixed"] if is_prev(k)]
    open_p = [k for k in out["still_open"] if is_prev(k)]
    rechecked = len(fixed_p) + len(open_p)
    same = [k for k in out["fixed"] + out["still_open"] if not is_prev(k)]
    return {
        "previous_month": prev["month"] if prev else None,
        "rerun_of_month": any(r["month"] == args.month for r in (hist or {}).get("records", [])),
        "rerun_fixed_count": len([k for k in out["fixed"] if not is_prev(k)]),
        "rerun_rechecked_count": len(same),
        "fixed_count": len(fixed_p),
        "rechecked_count": rechecked,
        "fixed_share": round(len(fixed_p) / rechecked, 4) if rechecked else None,
        "not_rechecked_count": len(out["not_rechecked"]),
        "open_by_age": {b: ages.get(b, 0) for b in ("lt_1m", "1_3m", "gt_3m")},
        "keys": out,
        "trend": [{k: r.get(k) for k in ("month", "clean_share_count", "clean_share_rub", "correction_share_of_expense", "flagged")}
                  for r in (hist or {}).get("records", []) if r["month"] < args.month][-6:],
    }


# ─── места платежа ───────────────────────────────────────────────────────────
# Что видит пользователь — МЕСТО (merchantId → references.merchants[id].name), а не
# сырой текст банка (originalPayee: «PYATEROCHKA 231»): его пишет плагин, изменить
# нельзя. Поэтому все проверки — по местам; текст банка — только улика.
_TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
               ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "i", "k", "l", "m", "n", "o", "p", "r", "s",
                "t", "u", "f", "h", "c", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))
# слова, по которым сеть не узнать («Кафе …», «ООО …», «Магазин …»)
PLACE_GENERIC = {"kafe", "cafe", "kofeinia", "kofeina", "kofe", "kofi", "apteka", "magazin", "o", "oo", "ip", "lc", "ltd",
                 "ao", "pao", "zao", "pos", "restoran", "bar", "shop", "market", "produkti", "stolovaia", "pekarnia",
                 "bistro", "salon", "vending", "the", "gastronom", "torgovii", "obekt", "ekspres", "moskva", "rest",
                 # 2026-10-07, прогон за 12 месяцев: «QSR» — код, под которым банк передаёт разные сети фастфуда;
                 # «Аноним», «Coffee …», «Павильон …», «Доставка …», «ALFA-BANK*…» — не название места
                 "qsr", "anonim", "cofe", "kofee", "pavilon", "dostavka", "alfa", "bank", "servis", "uslugi", "oplata"}
PLACE_MIN_KEY = 4          # ключ короче (QSR, SPA) — не основание для «одно место»
PERSON_RX = re.compile(r"^[А-ЯЁA-Z][а-яёa-z]+ [А-ЯЁA-Z]\.?$")            # «Сергей К.» — перевод человеку
CARD_RX = re.compile(r"\d{4,}\*{2,}\d{2,}|\*{4,}")                          # маскированный номер карты
RENAME_RULES = [   # (вид, что сказать, признак) — по названию МЕСТА
    ("symbols", "служебные символы", re.compile(r"[*_#\\|`~^]")),
    ("code", "номер точки или код", re.compile(r"\d{3,}|\d+[-_.]\d+")),
    ("punct", "лишняя пунктуация или пробелы", re.compile(r"^[^\wА-Яа-яЁё\"«]|[.,;:\-]$|\.\.|,,|--|\s{2,}|^\s|\s$")),
    ("broker", "платёжный посредник в названии", re.compile(r"(^|[^a-z])(ym|sbp|paypal|cloudpayments|robokassa|yookassa|xplat|moneta|alfa-bank|sber|yandex)\s*\*", re.I)),
    ("legal", "юрлицо (ООО, ИП…)", re.compile(r"(^|[\s\"«])(ооо|ип|ао|пао|ooo|ip|llc|ltd|ao|pao|pos ip)(\s|$|[\"»])", re.I)),
    ("site", "адрес сайта", re.compile(r"\.(ru|com|net|org|io|рф)\b", re.I)),
]
# место названо текстом банка: без логотипа (не бренд ZenMoney) и название — ВСЁ ЗАГЛАВНОЙ латиницей
# или буква в букву текст банка без кириллицы («Kofejnya Akter»; «МосЭнергоСбыт» — нормальное
# название, банк прислал его сам). Так приложение называет новое место по тексту плагина
# («ROSTICS SCHELKOVSKA», «PO CHESNOKU»). Решение пользователя 2026-10-07: показывать всегда —
# в сентябре 2026 таких было 13 из 57 мест месяца
BANK_CAPS_RX = re.compile(r"^(?=.*[A-Z])[^a-zа-яё]+$")
CYR_RX = re.compile(r"[А-Яа-яЁё]")
PLACE_MIN_OPS = 2          # переименование и сети — только для мест хотя бы с двумя тратами
PLACE_OPS_MAX = 40       # операций «лишнего» места с тем же названием — датами в ответе


def _lat(s):
    s = unicodedata.normalize("NFKC", s or "").lower()
    return "".join(_TR.get(ch, ch) for ch in s)


def _canon(t):
    t = t.replace("kh", "h").replace("w", "v").replace("x", "ks").replace("y", "i").replace("j", "i").replace("q", "k")
    return re.sub(r"(.)\1+", r"\1", t)


def place_tokens(s):
    """Слова названия латиницей, без цифр и знаков: «ПЯТЁРОЧКА 231» и «Pyaterochka» — одно."""
    return [_canon(t) for t in re.split(r"[^a-z]+", _lat(s)) if t]


def place_key(s):
    return "".join(place_tokens(s))


def chain_key(s):
    ts = [t for t in place_tokens(s) if t not in PLACE_GENERIC]
    return ts[0] if ts and len(ts[0]) >= 4 else ""


def has_own_word(s):
    """Есть ли в названии слово, кроме общих («APTEKA», «QSR 11001», «PRODUKTY» — нет)."""
    return any(t not in PLACE_GENERIC for t in place_tokens(s))


def places_check(ctx, month_ops, mode):
    """Подсказки по местам платежа. month — только места, где были траты в месяце."""
    spend = [o for o in ctx.ops if kind(o) == "expense"]
    st = {}
    unlinked = defaultdict(lambda: {"count": 0, "payees": Counter(), "last": ""})
    for o in spend:
        mid, pay = o.get("merchantId"), (o.get("originalPayee") or "").strip()
        if pay and CARD_RX.search(pay):
            pay = ""                                   # номер карты не показываем (принцип 8)
        if mid:
            x = st.setdefault(mid, {"count": 0, "payees": Counter(), "last": "", "ops": []})
            x["count"] += 1
            x["last"] = max(x["last"], o["date"])
            x["ops"].append(o)
            if pay:
                x["payees"][pay] += 1
        elif pay and place_key(pay) and not PERSON_RX.match(pay):
            u = unlinked[place_key(pay)]
            u["count"] += 1
            u["payees"][pay] += 1
            u["last"] = max(u["last"], o["date"])
    name = lambda mid: (ctx.refs.get("merchants", {}).get(mid) or {}).get("name") or mid
    in_month = {o.get("merchantId") for o in month_ops if o.get("merchantId")} if mode == "month" else None
    in_scope = lambda mids: in_month is None or any(m in in_month for m in mids)
    item = lambda kind_, mids, **kw: {"kind": kind_, "ids": sorted(mids), "names": [name(m) for m in sorted(mids)],
                                      "count": sum(st[m]["count"] for m in mids),
                                      "payees": [p for m in sorted(mids) for p, _ in st[m]["payees"].most_common(2)],
                                      "last": max(st[m]["last"] for m in mids), **kw}
    out = {"twins": [], "split": [], "unlinked": [], "rename": [], "bank_text": [], "chains": None}

    # 1. разные места с одним названием (после нормализации, кириллица↔латиница) или опечаткой
    groups = defaultdict(set)
    for mid in st:
        k = place_key(name(mid))
        if len(k) >= PLACE_MIN_KEY and has_own_word(name(mid)) and not PERSON_RX.match(name(mid)):
            groups[k].add(mid)
    keys = sorted(groups)
    for i, a in enumerate(keys):                       # опечатка: длинные ключи на расстоянии 1
        for b in keys[i + 1:]:
            if len(a) >= 6 and len(b) >= 6 and a[:2] == b[:2] and lev1(a, b):
                groups[a] |= groups[b]
                groups[b] = set()
    twin_sets = []
    for k, mids in groups.items():
        if len(mids) > 1:
            twin_sets.append(frozenset(mids))
    # 2. один и тот же текст банка — у разных мест (одни покупки в одной точке, другие — в другой)
    by_pay = defaultdict(set)
    for mid, x in st.items():
        for p in x["payees"]:
            k = place_key(p)
            # общий текст банка («APTEKA», «PRODUKTY», «QSR 11001») — разные места, не дубль
            if len(k) >= PLACE_MIN_KEY and has_own_word(p):
                by_pay[k].add(mid)
    for k, mids in by_pay.items():
        if len(mids) > 1 and not any(mids <= t for t in twin_sets):
            out["split"].append(item("split", mids, payee_key=k))
    out["twins"] = [item("twins", t, exact=len({place_key(name(m)) for m in t}) == 1) for t in twin_sets]
    # одно и то же название (регистр и «ё» не в счёт): в приложении места не различить по
    # имени — пользователю нужны даты операций «лишнего» места (решение 2026-10-07). Лишние —
    # все, кроме основного: фирменного (с логотипом — его ставит приложение новым операциям),
    # затем со свежей тратой, затем с большим числом трат; до PLACE_OPS_MAX операций.
    acc = ctx.refs.get("accounts", {})
    same = lambda s_: s_.lower().replace("ё", "е").strip()
    for t in out["twins"]:
        if len({same(n) for n in t["names"]}) != 1:
            continue
        logo = lambda m: bool((ctx.refs.get("merchants", {}).get(m) or {}).get("logoUrl"))
        keep_mid = max(t["ids"], key=lambda m: (logo(m), st[m]["last"], st[m]["count"]))
        rest = sorted((o for m in t["ids"] if m != keep_mid for o in st[m]["ops"]), key=lambda o: o["date"])
        t["same_name"] = True
        t["keep"] = keep_mid
        t["ops"] = [{"id": o["id"], "date": o["date"], "amount": (o.get("expense") or {}).get("amount"),
                     "account": (acc.get((o.get("expense") or {}).get("accountId")) or {}).get("name")} for o in rest[:PLACE_OPS_MAX]]
        t["ops_more"] = max(0, len(rest) - PLACE_OPS_MAX)
    # 3. траты без места, хотя такой текст банка у другой операции привязан к месту
    pay_to_mid = {}
    for mid, x in st.items():
        for p in x["payees"]:
            pay_to_mid.setdefault(place_key(p), Counter())[mid] += x["payees"][p]
    for k, u in unlinked.items():
        if k in pay_to_mid:
            mid = pay_to_mid[k].most_common(1)[0][0]
            out["unlinked"].append({"kind": "unlinked", "ids": ["payee:" + k], "count": u["count"],
                                    "payees": [p for p, _ in u["payees"].most_common(2)], "last": u["last"],
                                    "suggest": {"id": mid, "name": name(mid)}})
    # 4. названия мест, которые стоит переименовать (пользователь видит их в приложении)
    for mid, x in st.items():
        nm = name(mid)
        if x["count"] < PLACE_MIN_OPS or PERSON_RX.match(nm):
            continue
        why = [w for w, _t, rx in RENAME_RULES if rx.search(nm)]
        if why:
            out["rename"].append({"kind": "rename", "ids": [mid], "names": [nm], "count": x["count"], "why": why,
                                  "payees": [p for p, _ in x["payees"].most_common(2)], "last": x["last"]})
    # 5. место названо текстом банка — «как назвать?» (у переименования своя причина — не дублировать)
    renamed = {x["ids"][0] for x in out["rename"]}
    merchants = ctx.refs.get("merchants", {})
    for mid, x in st.items():
        nm = name(mid)
        if mid in renamed or (merchants.get(mid) or {}).get("logoUrl") or PERSON_RX.match(nm) or CARD_RX.search(nm):
            continue
        if BANK_CAPS_RX.match(nm) or (nm in x["payees"] and not CYR_RX.search(nm)):
            out["bank_text"].append({"kind": "bank_text", "ids": [mid], "names": [nm], "count": x["count"],
                                     "why": [w for w, _t, rx in RENAME_RULES if rx.search(nm)],
                                     "payees": [p for p, _ in x["payees"].most_common(2)], "last": x["last"]})
    # 6. филиалы одной сети — решает пользователь (сводить или нет); в month шумят — не показываем
    if mode != "month":
        ch = defaultdict(set)
        for mid, x in st.items():
            k = chain_key(name(mid))
            if k and x["count"] >= 1 and not PERSON_RX.match(name(mid)):
                ch[k].add(mid)
        # уже показанное выше (одно название, один текст банка) — не повторять сетью
        shown = [frozenset(t) for t in twin_sets] + [frozenset(x["ids"]) for x in out["split"]]
        out["chains"] = [item("chains", mids, chain=k) for k, mids in ch.items()
                         if len(mids) > 1 and len({place_key(name(m)) for m in mids}) > 1 and not any(mids <= t for t in shown)
                         and sum(st[m]["count"] for m in mids) >= PLACE_MIN_OPS]
    for k in ("twins", "split", "unlinked", "rename", "bank_text", "chains"):
        if out[k] is None:
            continue
        # «это разные места» / «так и задумано» — accepted.json, проверка C10, ID через «|»
        keep = lambda x: ctx.ok("|".join(x["ids"]), "C10") and (x["kind"] == "unlinked" or in_scope(x["ids"]))
        out[k] = sorted([x for x in out[k] if keep(x)], key=lambda x: -x["count"])
    if in_month is not None:   # без места — только траты этого месяца
        mk = {place_key(o.get("originalPayee") or "") for o in month_ops if not o.get("merchantId")}
        out["unlinked"] = [x for x in out["unlinked"] if x["ids"][0][6:] in mk]
    out["counts"] = {k: (len(v) if v is not None else None) for k, v in out.items() if k != "counts"}
    return out


# ─── сборка ──────────────────────────────────────────────────────────────────

def run(args):
    ops, refs = merge_pages(args.tx)
    ctx = Ctx(ops, refs, load_categories(args.categories), load_rates(args.rates),
              load_config(args.config), load_accepted(args.accepted))
    ctx.a2_kinds = load_a2_kinds(args.accepted)
    start_day = int((refs.get("user") or {}).get("monthStartDay") or 1)
    start, end = month_bounds(args.month, start_day)
    as_of = d(args.as_of) if args.as_of else max(end, max((d(o["date"]) for o in ops), default=end))
    if args.mode == "needs-rates":
        return {"main_currency": ctx.main, "needs": needs_rates(ctx, start, end)}
    if args.mode == "places":
        window_start = d(args.window_from) if args.window_from else (d(min(o["date"] for o in ops)) if ops else start)
        return {"schema": "zenmoney-audit-places@1", "mode": "places", "as_of": as_of.isoformat(),
                "window": [window_start.isoformat(), as_of.isoformat()], "accepted_applied": len(ctx.accepted),
                "places": places_check(ctx, [], "places")}

    month_ops = [o for o in ops if start <= d(o["date"]) <= end]
    # окно — запрошенное у MCP (--window-from), а не дата первой операции: тихие дни в начале окна
    # не должны делать месяц «не покрытым»
    window_start = d(args.window_from) if args.window_from else (d(ops[0]["date"]) if ops else start)
    res = a_checks(ctx, month_ops, ops)
    res.update({
        "B6": b6_silent_sync(ctx, as_of),
        "B7": b7_off_balance(ctx, month_ops),
        "B8": b8_new_accounts(ctx),
    })
    out = {
        "schema": "zenmoney-audit-run@1",
        "mode": args.mode,
        "month": args.month,
        "period": [start.isoformat(), end.isoformat()],
        "as_of": as_of.isoformat(),
        "window": [window_start.isoformat(), as_of.isoformat()],
        "main_currency": ctx.main,
        "coverage": {
            "b6_window_ok": (as_of - window_start).days >= SYNC_WINDOW_DAYS,
            "categories_full_list": args.categories is not None,
            "accepted_applied": len(ctx.accepted),
        },
        "checks": res,
        "stats": stats(ctx, month_ops, res),
        "D13_parent_with_children": d13_parent_with_children(ctx, month_ops) if args.categories else None,
    }
    if args.mode == "quarter":
        out["checks"]["C9"] = c9_name_twins(ctx) if args.categories else None
        out["checks"]["C11"] = c11_inactive(ctx, as_of, window_start) if args.categories else None
        out["checks"]["C12"] = c12_trips_not_moved(ctx, as_of)
    # места платежа — подсказки: вне checks, в долю «без замечаний» и в историю не входят
    out["places"] = places_check(ctx, month_ops, args.mode)
    # траты прямо в категории с подкатегориями — подсказка только «закрой месяц» (2026-10-07)
    if args.mode == "month":
        out["parent_direct"] = parent_direct(ctx, month_ops) if args.categories else None
    for k in ("expense_rub", "income_rub", "in_trips_rub", "all_expense_rub", "transfer_out_rub"):
        res["A2"][k] = round(res["A2"][k], 2)
    out["coverage"]["unconverted"] = dict(Counter(inst for _o, _a, inst in ctx.missing))
    keys = issue_keys(res)
    out["issues"] = {k: {"check": c, "month": args.month} for k, c in sorted(keys.items())}
    hist = load_history(args.history)
    out["coverage"]["history"] = "есть" if hist else "нет истории"
    # перепроверка прошлых месяцев может звать пересчёт валют — охват выше уже снят
    out["history"] = recheck_history(ctx, hist, args, as_of, window_start, keys, start_day) if hist else None
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", choices=["needs-rates", "month", "quarter", "places"])
    p.add_argument("--month", required=True, help="аудируемый финансовый месяц YYYY-MM")
    p.add_argument("--as-of", help="дата аудита YYYY-MM-DD (по умолчанию — последняя дата данных)")
    p.add_argument("--tx", nargs="+", required=True)
    p.add_argument("--window-from", help="начало окна, запрошенного у list_transactions (YYYY-MM-DD)")
    p.add_argument("--categories")
    p.add_argument("--rates", nargs="*")
    p.add_argument("--config")
    p.add_argument("--accepted")
    p.add_argument("--history", help="history.json (только чтение; запись — audit_history.py)")
    args = p.parse_args(argv)
    json.dump(run(args), sys.stdout, ensure_ascii=False, indent=1)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
