#!/usr/bin/env python3
"""
numbers_to_plan.py — конвертер «Общий баланс (Numbers) → plan.json» и сверка плана
(этап 1 ухода от Numbers, docs/investment/portfolio/numbers-exit-plan.md §3.1).

Чистое переложение `portfolio.json` (выход parse_portfolio.py) в `plan.json` (`plan@1.0`) без
интерпретации и обратно. Ничего не пишет в Claude-Memory сам: `--out` — путь, который указал вызывающий.

    build_plan(portfolio, source_file=…)        portfolio.json → plan.json
    plan_to_portfolio_fragments(plan)           plan.json → куски portfolio.json (русские ключи)
    plan_diff(portfolio, plan)                  [{path, numbers, plan}] — расхождения, по path

Единицы — как отдаёт парсер: классы/матрица/корзины — доли единицы (0.4), поля акций
`plan_pct`/`ie_new_pct`/`ie_old_pct` и `ie_model` — проценты (2.0 = 2 %). Ничего не пересчитывается.

CLI:
    numbers_to_plan.py --portfolio portfolio.json [--out plan.json] [--source-file NAME]
    numbers_to_plan.py --portfolio portfolio.json --diff plan.json   # сверка; код выхода 0 даже при расхождениях

Защита правок сайта (этап 2): `--out` не перезаписывает существующий PLAN, если его `updated_by` ≠
"numbers_to_plan.py" (правили на сайте: "hub-api"). Печатает расхождения Numbers против файла и выходит
кодом 3. `--force` перезаписывает всё равно, оставив рядом копию `plan.json.bak-<YYYYMMDD-HHMMSS>`.
Файл, записанный самим конвертером, перезаписывается молча. Без `--source-file` имя источника
берётся из `source.file` существующего plan.json.

`apply_plan_primary(portfolio, plan)` — переключатель «главный источник — plan.json» (assemble_snapshot
`--plan-primary`): куски плана из plan.json подменяют куски portfolio.json, факт-поля Numbers
(«Сейчас», «Всего» и т. п.) остаются.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from parse_portfolio import _bond_bucket_key  # noqa: E402

SCHEMA_VERSION = "plan@1.0"
UPDATED_BY = "numbers_to_plan.py"
TOL = 1e-9

# Поля акции: ключ plan.json ← ключ ie_actual.per_ticker (имена парсера)
STOCK_FIELDS = (
    ("plan_pct", "planned_share_pct"),
    ("user_plan", "user_plan"),
    ("user_status", "user_status"),
    ("note_ie", "user_note_ie"),
    ("note_ai", "user_note_ai"),
    ("ie_new_pct", "ie_new_pct"),
    ("ie_old_pct", "ie_old_pct"),
)
# Верхнеуровневые ключи, которые сверка не сравнивает (метаданные и разделы, которых в Numbers нет)
DIFF_IGNORE_TOP = {"schema_version", "generated_at", "updated_at", "updated_by", "source", "ie_history"}
# дата разбора и кэш модели (строка «Кэш LQDT» с сайта IE) — не данные Numbers
DIFF_IGNORE_PATHS = {"ie_model.extraction_date", "ie_model.cash_pct", "ie_model.cash_ticker"}
# ключи позиций модели, которых Numbers не даёт (приходят из импорта «общего портфеля» IE)
DIFF_IGNORE_POSITION_KEYS = {"industry", "target_price_rub", "target_price_lt_rub"}


def _clean(v: Any) -> Any:
    """Пустая строка → None; строки без пробелов по краям; остальное как есть."""
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def _sorted_deep(o: Any) -> Any:
    """Ключи всех словарей — по алфавиту (стабильный файл); порядок списков сохраняется."""
    if isinstance(o, dict):
        return {k: _sorted_deep(o[k]) for k in sorted(o)}
    if isinstance(o, list):
        return [_sorted_deep(x) for x in o]
    return o


def _is_total_row(row: dict) -> bool:
    return _clean(row.get("Тип")) in (None, "Итог")


def build_plan(portfolio: dict, *, source_file: str | None, now: str | None = None) -> dict:
    """portfolio.json → plan.json по §3.1. Даты — extraction_date из ie_actual/ie_model, иначе now/сегодня."""
    ie_actual = portfolio.get("ie_actual") or {}
    ie_model = portfolio.get("ie_model") or {}
    date = (ie_actual.get("extraction_date") or ie_model.get("extraction_date")
            or now or dt.date.today().isoformat())
    date = str(date)[:10]
    goals = portfolio.get("goals") or {}

    classes = [{"class": _clean(r.get("Тип")), "share": r.get("Доля")}
               for r in goals.get("overall") or [] if _clean(r.get("Тип"))]

    matrix = [{"currency": _clean(r.get("Валюта")), "class": _clean(r.get("Бумага")), "share": r.get("Доля план")}
              for r in goals.get("matrix") or []]

    buckets = []
    for r in goals.get("bonds_breakdown") or []:
        if _is_total_row(r):
            continue
        typ = _clean(r.get("Тип"))
        sub = _clean(r.get("_subtype")) if "_subtype" in r else _clean(r.get("Подтип") or r.get("Рейтинг"))
        key = r.get("_bucket_key") if r.get("_bucket_key") else _bond_bucket_key(typ, sub)
        buckets.append({"key": key, "type": typ, "subtype": sub, "share": r.get("Доля План")})

    stocks: dict[str, dict] = {}
    for t, row in (ie_actual.get("per_ticker") or {}).items():
        item = {new: _clean(row.get(old)) for new, old in STOCK_FIELDS}
        if any(v is not None for v in item.values()):
            stocks[t] = item

    model = None
    if ie_model:
        model = {k: v for k, v in ie_model.items() if k != "source_sheet"}

    bonds: dict[str, dict] = {}
    for b in portfolio.get("bonds") or []:
        isin = _clean(b.get("Тикер"))
        if not isin:
            continue
        item = {
            "name": _clean(b.get("Название")),
            "type": _clean(b.get("Тип")),
            "subtype": _clean(b.get("Подтип")),
            "rating": _clean(b.get("Рейтинг")),
            "action": _clean(b.get("Действие")),
            "iis_qty": b.get("ИИС"),
        }
        total = b.get("Всего")
        active = isinstance(total, (int, float)) and not isinstance(total, bool) and total > 0
        filled = any(item[k] is not None for k in ("subtype", "rating", "action", "iis_qty"))
        if active or filled:
            bonds[isin] = item

    manual = [{"type": _clean(r.get("Тип")), "name": _clean(r.get("Бумага")), "value_rub": r.get("Стоимость")}
              for r in portfolio.get("other_positions") or []]

    plan = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": date,
        "updated_at": date,
        "updated_by": UPDATED_BY,
        "source": {"kind": "numbers", "file": os.path.basename(source_file) if source_file else None,
                   "extraction_date": date},
        "classes": classes,
        "matrix": matrix,
        "bond_buckets": buckets,
        "stocks": stocks,
        "ie_model": model,
        "bonds": bonds,
        "manual_positions": manual,
    }
    return _sorted_deep(plan)


def plan_to_portfolio_fragments(plan: dict) -> dict:
    """plan.json → куски portfolio.json в его форме и с русскими ключами."""
    overall = [{"Тип": c.get("class"), "Доля": c.get("share")} for c in plan.get("classes") or []]
    matrix = [{"Валюта": m.get("currency"), "Бумага": m.get("class"), "Доля план": m.get("share")}
              for m in plan.get("matrix") or []]
    breakdown = [{"Тип": b.get("type"), "Подтип": b.get("subtype"), "Доля План": b.get("share"),
                  "_subtype": b.get("subtype"), "_bucket_key": _bond_bucket_key(b.get("type"), b.get("subtype"))}
                 for b in plan.get("bond_buckets") or []]
    per_ticker = {t: {old: s.get(new) for new, old in STOCK_FIELDS}
                  for t, s in (plan.get("stocks") or {}).items()}
    model = plan.get("ie_model")
    if model is not None:
        model = {"source_sheet": "Invest Era", **model}
    return {
        "goals": {"overall": overall, "matrix": matrix, "bonds_breakdown": breakdown},
        "ie_model": model,
        "ie_actual": {"extraction_date": (plan.get("source") or {}).get("extraction_date"),
                      "per_ticker": per_ticker},
        "other_positions": [{"Тип": m.get("type"), "Бумага": m.get("name"), "Стоимость": m.get("value_rub")}
                            for m in plan.get("manual_positions") or []],
        "bonds_typing": {isin: {"Тип": b.get("type"), "Подтип": b.get("subtype"), "Рейтинг": b.get("rating"),
                                "Действие": b.get("action"), "ИИС": b.get("iis_qty")}
                         for isin, b in (plan.get("bonds") or {}).items()},
    }


def apply_plan_primary(portfolio: dict | None, plan: dict, *, trades_mode: bool = False) -> dict:
    """Копия `portfolio` с планом из plan.json: goals.overall/matrix/bonds_breakdown (план-поля), ie_model,
    ie_actual.per_ticker (поля плана), other_positions, а у bonds[] — Тип/Подтип/Рейтинг/Действие/ИИС по ISIN.
    Строки сливаются по ключу (класс; валюта+класс; ключ корзины; тип+бумага), остальные поля строк Numbers
    (факт, формулы) не трогаются. Строки Numbers, которых нет в плане, остаются как есть; тикер без записи
    в plan.stocks теряет поля плана (build_plan кладёт в plan тех, у кого что-то задано).
    portfolio=None → куски собираются из плана целиком (без полей Numbers).
    trades_mode=True — «баланс» собран из сделок (`_portfolio_from_trades`): типизация облигаций ищется по Тикер
    или ISIN, количество на ИИС-3 («ИИС») и пустые поля плана строку не затирают, ручные позиции плана в
    other_positions не вливаются (стоимость внебиржевых берёт сама сборка из сделок, FINAMAR — из плана)."""
    fr = plan_to_portfolio_fragments(plan)
    out = copy.deepcopy(portfolio) if portfolio else {}
    goals = out.setdefault("goals", {})

    def merge(rows, plan_rows, keyf, plan_field):
        rows = list(rows or [])
        index = {keyf(r): r for r in rows}
        for pr in plan_rows:
            k = keyf(pr)
            if k in index:
                index[k][plan_field] = pr.get(plan_field)
            else:
                rows.append(dict(pr))
        return rows

    goals["overall"] = merge(goals.get("overall"), fr["goals"]["overall"], lambda r: _clean(r.get("Тип")), "Доля")
    goals["matrix"] = merge(goals.get("matrix"), fr["goals"]["matrix"],
                            lambda r: (_clean(r.get("Валюта")), _clean(r.get("Бумага"))), "Доля план")
    bkey = lambda r: r.get("_bucket_key") or _bond_bucket_key(_clean(r.get("Тип")), _clean(r.get("_subtype", r.get("Подтип"))))  # noqa: E731
    goals["bonds_breakdown"] = merge(goals.get("bonds_breakdown"), fr["goals"]["bonds_breakdown"], bkey, "Доля План")

    if fr["ie_model"] is not None:
        out["ie_model"] = fr["ie_model"]
    ia = out.setdefault("ie_actual", {})
    if not ia.get("extraction_date"):
        ia["extraction_date"] = fr["ie_actual"]["extraction_date"]
    per = ia.setdefault("per_ticker", {})
    for t, row in per.items():
        if t not in fr["ie_actual"]["per_ticker"]:
            for _, old in STOCK_FIELDS:
                row[old] = None
    for t, fields in fr["ie_actual"]["per_ticker"].items():
        per.setdefault(t, {}).update(fields)

    if not trades_mode:
        others = list(out.get("other_positions") or [])
        idx = {(_clean(r.get("Тип")), _clean(r.get("Бумага"))): r for r in others}
        for r in fr["other_positions"]:
            k = (_clean(r.get("Тип")), _clean(r.get("Бумага")))
            if k in idx:
                idx[k]["Стоимость"] = r["Стоимость"]
            else:
                others.append(dict(r))
        out["other_positions"] = others

    typing = fr["bonds_typing"]
    for b in out.get("bonds") or []:
        t = typing.get(_clean(b.get("Тикер"))) or (typing.get(_clean(b.get("ISIN"))) if trades_mode else None)
        if t:
            if trades_mode:
                upd = {k: v for k, v in t.items() if k != "ИИС" and v is not None}
                if t.get("Тип") is not None:
                    upd["Подтип"] = t.get("Подтип")   # корзина плана — пара: пустой подтип плана тоже затирает перенесённый
                b.update(upd)
            else:
                b.update(t)
    return out


# ── сверка ──────────────────────────────────────────────────────────────────────

# как называть элементы списков в path (иначе — индекс)
_LIST_KEYS = {
    "classes": lambda x: x.get("class"),
    "matrix": lambda x: f"{x.get('currency')}/{x.get('class')}",
    "bond_buckets": lambda x: x.get("key"),
    "manual_positions": lambda x: f"{x.get('type')}/{x.get('name')}",
    "ie_model.positions": lambda x: x.get("ticker"),
}


def _flatten(o: Any, path: str, out: dict) -> None:
    if isinstance(o, dict):
        for k, v in o.items():
            _flatten(v, f"{path}.{k}" if path else str(k), out)
    elif isinstance(o, list):
        keyfn = _LIST_KEYS.get(path)
        seen: dict[str, int] = {}
        for i, x in enumerate(o):
            name = keyfn(x) if keyfn and isinstance(x, dict) else None
            name = str(i) if name is None else str(name)
            seen[name] = seen.get(name, 0) + 1
            if seen[name] > 1:
                name = f"{name}#{seen[name]}"
            _flatten(x, f"{path}.{name}", out)
    else:
        out[path] = o


def _same(a: Any, b: Any) -> bool:
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)  # noqa: E731
    if num(a) and num(b):
        if math.isnan(a) and math.isnan(b):
            return True
        return abs(a - b) <= TOL
    return a == b


def plan_diff(portfolio: dict, plan: dict) -> list[dict]:
    """Расхождения между планом из Numbers (`build_plan(portfolio)`) и `plan`: [{path, numbers, plan}] по path."""
    left, right = {}, {}
    # позиции с active_in_model == False — импорт общего портфеля IE, в Numbers их нет; файл плана не меняем
    plan = copy.deepcopy(plan)
    model = plan.get("ie_model")
    if isinstance(model, dict) and isinstance(model.get("positions"), list):
        model["positions"] = [x for x in model["positions"]
                              if not (isinstance(x, dict) and x.get("active_in_model") is False)]
    for src, dst in ((build_plan(portfolio, source_file=None), left), (plan, right)):
        _flatten({k: v for k, v in src.items() if k not in DIFF_IGNORE_TOP}, "", dst)
    out = []
    for path in sorted(set(left) | set(right)):
        if path in DIFF_IGNORE_PATHS or (path.startswith("ie_model.positions.")
                                         and path.rsplit(".", 1)[-1] in DIFF_IGNORE_POSITION_KEYS):
            continue
        a, b = left.get(path), right.get(path)
        if not _same(a, b):
            out.append({"path": path, "numbers": a, "plan": b})
    return out


def format_diff(diff: list[dict]) -> str:
    if not diff:
        return "Расхождений нет."
    w = max(len(d["path"]) for d in diff)
    rows = [f"{'путь'.ljust(w)}  {'Numbers':<20}  plan.json"]
    rows += [f"{d['path'].ljust(w)}  {json.dumps(d['numbers'], ensure_ascii=False):<20}  "
             f"{json.dumps(d['plan'], ensure_ascii=False)}" for d in diff]
    rows.append(f"Расхождений: {len(diff)}")
    return "\n".join(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Общий баланс (portfolio.json) → plan.json; сверка с plan.json")
    ap.add_argument("--portfolio", required=True, help="выход parse_portfolio.py (portfolio.json)")
    ap.add_argument("--out", help="куда записать plan.json (нет — в stdout)")
    ap.add_argument("--diff", metavar="PLAN", help="сверить с этим plan.json и напечатать расхождения (код выхода 0)")
    ap.add_argument("--source-file", help="имя файла-источника для source.file (default: из существующего "
                                          "plan.json по --out, иначе —)")
    ap.add_argument("--force", action="store_true",
                    help="--out: перезаписать plan.json, правленный на сайте (старый файл → plan.json.bak-<время>)")
    args = ap.parse_args(argv)

    portfolio = json.loads(Path(args.portfolio).read_text(encoding="utf-8"))
    if args.diff:
        plan = json.loads(Path(args.diff).read_text(encoding="utf-8"))
        print(format_diff(plan_diff(portfolio, plan)))
        return 0
    existing = None
    if args.out and Path(args.out).is_file():
        try:
            existing = json.loads(Path(args.out).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = None
    source_file = args.source_file
    if source_file is None and isinstance(existing, dict):
        source_file = (existing.get("source") or {}).get("file")
    plan = build_plan(portfolio, source_file=source_file)
    text = json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.out:
        out = Path(args.out)
        if isinstance(existing, dict) and existing.get("updated_by") != UPDATED_BY:
            if not args.force:
                print(f"plan.json правился на сайте ({existing.get('updated_by')}, {existing.get('updated_at')}) "
                      f"— не перезаписываю; расхождения:")
                print(format_diff(plan_diff(portfolio, existing)))
                return 3
            bak = out.with_name(f"{out.name}.bak-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}")
            bak.write_bytes(out.read_bytes())
            print(f"копия прежнего файла: {bak}")
        out.write_text(text, encoding="utf-8")
        print(f"✓ {args.out}: классов {len(plan['classes'])}, корзин {len(plan['bond_buckets'])}, "
              f"акций {len(plan['stocks'])}, облигаций {len(plan['bonds'])}, "
              f"ручных позиций {len(plan['manual_positions'])}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
