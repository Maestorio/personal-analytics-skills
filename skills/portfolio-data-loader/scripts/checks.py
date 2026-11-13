#!/usr/bin/env python3
"""
checks.py — проверки целостности и качества снапшота портфеля (API-1b, PR-3).

Вызывается из build_snapshot.py после сборки; можно и отдельно:
    python3 checks.py portfolio-2026-10-16.json --prev portfolio-2026-10-13.json \\
        [--trades trades.xlsx] [--as-of 2026-10-16]

Уровни (план docs/api-migration/deterministic-plan.md §A.5):
    block   — снапшот не записывается (--commit отказывает);
    warning — записывается с отметкой, показывается владельцу;
    info    — в сводке.

Флаги, которые уже ставит assemble_snapshot (avg_cost_fallback_value_over_qty,
balance_vs_trades_mismatch, cash_drift_changed, iis_*), здесь не дублируются —
они в data_quality_flags снапшота, а решения по ним — в build-summary.decisions.

Каждая проверка — функция `check_*(ctx) -> list[dict]`; результат —
{"id", "level", "message_ru", "details"}. Тесты — tests/test_snapshot_checks.py.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import known_splits  # noqa: E402

# Операции и валюты выгрузки IntelInvest, которые понимает portfolio_returns.py
# (сверено с реальной выгрузкой 2026-10-15: 10 286 строк). Новая операция или
# валюта — блок: расчёт мог её молча пропустить.
KNOWN_OPERATIONS = frozenset({
    "Покупка", "Продажа", "Купон", "Дивиденд", "Амортизация", "Доход", "Расход",
    "Внесение", "Списание", "Ввод", "Вывод", "Корректировка",
    "Начисление вариационной маржи", "Списание вариационной маржи",
})
KNOWN_CURRENCIES = frozenset({"RUB", "USD", "EUR", "CNY", "POINT"})

# Пороги
TRADES_STALE_WARN_DAYS = 10      # последняя операция старше — выгрузка, похоже, не свежая
QUOTE_STALE_DAYS = 4             # котировка старше as_of − N дней (выходные + праздник)
FX_STALE_DAYS = 4
NON_MOEX_SHARE_WARN = 0.10       # доля активных позиций без котировки MOEX
VALUE_JUMP_WARN = 0.25           # изменение стоимости позиции без сделок и смены qty
CASH_EQ_TOL_RUB = 1.0
INVARIANT_TOL_RUB = 1.0
XIRR_SANE = (-0.9, 3.0)
# Ручная оценка владельца (parsing-numbers.md, Edge cases) — без котировки MOEX законно
MANUAL_VALUATION = frozenset({"FINAMAR"})
REQUIRED_KEYS = ("schema_version", "as_of_date", "generated_at", "holdings", "cash",
                 "returns", "data_quality_flags")
SALE_OPS = frozenset({"Продажа"})
PAYOUT_OPS = frozenset({"Купон", "Дивиденд", "Амортизация"})
QTY_OPS = frozenset({"Покупка", "Продажа", "Корректировка"})
BOND_TICKER = re.compile(r"^(RU000|SU\d)")
MONEY_CORRECTION_RUB = 10_000      # денежная корректировка IntelInvest крупнее — показать
MONEY_CORRECTION_DAYS = 30
PAYOUT_LOOKBACK_DAYS = 120
FLOW_OPS = frozenset({"Покупка", "Продажа", "Корректировка"})


@dataclass
class TradesInfo:
    """Сводка выгрузки сделок для проверок (inspect_trades)."""
    n_rows: int = 0
    first_date: str | None = None
    last_date: str | None = None
    operations: Counter = field(default_factory=Counter)
    currencies: Counter = field(default_factory=Counter)
    # (date, ticker, operation, qty, amount) — для дубликатов и движений по бумаге
    rows: list[tuple] = field(default_factory=list)
    # Сделки после apply_corrections — для held_qty (сплиты, корректировки, валютные ключи)
    trades: list = field(default_factory=list, repr=False)


def inspect_trades(path) -> TradesInfo:
    sys.path.insert(0, str(HERE))
    from portfolio_returns import apply_corrections, parse_trades  # noqa: WPS433
    trades = parse_trades(str(path))
    info = TradesInfo(n_rows=len(trades))
    if trades:
        info.first_date = min(t.date for t in trades).isoformat()
        info.last_date = max(t.date for t in trades).isoformat()
    for t in trades:
        info.operations[t.operation] += 1
        info.currencies[t.currency] += 1
        info.rows.append((t.date.isoformat(), t.ticker, t.operation, t.qty,
                          round(t.amount, 2) if t.amount is not None else None))
    info.trades = apply_corrections(trades)[0]
    return info


@dataclass
class Ctx:
    snap: dict
    prev: dict | None
    trades: TradesInfo | None
    as_of: str
    returns: dict | None = None
    splits: dict | None = None       # действующий реестр сплитов {ticker: [{date, ratio, note}]}; None — встроенный
    dismissed: list | None = None    # отклонённые подозрения на сплит (known-splits.json → dismissed)
    fetch: object = None             # fetch(ticker, from_date, to_date) -> [(дата, close)]; None — ISS

    @property
    def prev_date(self) -> str | None:
        return (self.prev or {}).get("as_of_date")


def _r(id_, level, msg, **details) -> dict:
    return {"id": id_, "level": level, "message_ru": msg, "details": details}


def _days(a: str, b: str) -> int:
    return (dt.date.fromisoformat(b[:10]) - dt.date.fromisoformat(a[:10])).days


def _active(snap: dict) -> list[dict]:
    return [h for h in snap.get("holdings") or [] if h.get("status") != "blocked"]


def _key(h: dict) -> tuple:
    return (h.get("ticker"), h.get("account"))


def _fmt_list(xs, n=8) -> str:
    xs = list(xs)
    return ", ".join(map(str, xs[:n])) + (f" и ещё {len(xs) - n}" if len(xs) > n else "")


# ── подача сообщений: даты ДД.ММ, суммы «1 234,50 ₽», бумага «TICKER (Название)» ──

CUR_WORD = {"RUB": "₽", "USD": "долл.", "EUR": "евро", "CNY": "юаней", "POINT": "пт."}


def _dm(iso, ref=None) -> str:
    """ДД.ММ; с годом (ДД.ММ.ГГГГ), если год не совпадает с годом ref (дата сборки)."""
    d = dt.date.fromisoformat(str(iso)[:10])
    ref_year = int(str(ref)[:4]) if ref else dt.date.today().year
    return d.strftime("%d.%m") if d.year == ref_year else d.strftime("%d.%m.%Y")


def _num(x: float, signed: bool = False) -> str:
    """1234.5 → «1 234,50»; целое — без копеек. Знак — «−» (минус), «+» только при signed."""
    s = f"{abs(x):,.2f}".replace(",", " ").replace(".", ",")
    if s.endswith(",00"):
        s = s[:-3]
    sign = "−" if x < 0 else ("+" if signed else "")
    return sign + s


def _amt(x: float, cur: str = "RUB", signed: bool = False) -> str:
    return f"{_num(x, signed)} {CUR_WORD.get(cur, cur)}"


def _money_cur(ticker: str) -> str:
    m = re.search(r"\((\w+)\)", str(ticker))
    return m.group(1) if m else "RUB"


def _ticker_cur(ctx, ticker: str) -> str:
    if str(ticker).startswith("Деньги"):
        return _money_cur(ticker)
    for x in (ctx.trades.trades if ctx.trades else []):
        if x.ticker == ticker:
            return x.currency or "RUB"
    return "RUB"


def _label(ctx, ticker: str) -> str:
    if str(ticker).startswith("Деньги"):
        return "деньги"
    for h in ctx.snap.get("holdings") or []:
        if h.get("ticker") == ticker and h.get("name") and h["name"] != ticker:
            return f"{ticker} ({h['name']})"
    return str(ticker)


# ───────────────────────────── входные файлы ─────────────────────────────

def check_trades(ctx: Ctx) -> list[dict]:
    t = ctx.trades
    if t is None:
        return []
    out = []
    if t.n_rows == 0:
        return [_r("trades_empty", "block", "Выгрузка сделок пустая — не тот файл или сломан формат.")]
    unknown_ops = {k: v for k, v in t.operations.items() if k not in KNOWN_OPERATIONS}
    if unknown_ops:
        out.append(_r("trades_unknown_operation", "block",
                      f"Неизвестные типы операций в выгрузке: {_fmt_list(unknown_ops)}. Расчёт мог их "
                      "пропустить — проверить формат IntelInvest и portfolio_returns.py.",
                      operations=unknown_ops))
    unknown_cur = {k: v for k, v in t.currencies.items() if k not in KNOWN_CURRENCIES}
    if unknown_cur:
        out.append(_r("trades_unknown_currency", "block",
                      f"Неизвестные валюты в выгрузке: {_fmt_list(unknown_cur)}.", currencies=unknown_cur))
    future = [r for r in t.rows if r[0] > ctx.as_of]
    if future:
        out.append(_r("trades_future_date", "block",
                      f"{len(future)} операций датированы позже даты снапшота {_dm(ctx.as_of, ctx.as_of)} "
                      f"(первая: {_dm(future[0][0], ctx.as_of)} {future[0][1]} {future[0][2].lower()}).",
                      n=len(future)))
    if t.last_date:
        age = _days(t.last_date, ctx.as_of)
        if age > TRADES_STALE_WARN_DAYS:
            out.append(_r("trades_stale", "warning",
                          f"Последняя операция в выгрузке — {_dm(t.last_date, ctx.as_of)} ({age} дн. до снапшота). "
                          "Выгрузка свежая? Купоны и дивиденды обычно идут чаще.",
                          last_date=t.last_date, age_days=age))
        else:
            out.append(_r("trades_freshness", "info",
                          f"Выгрузка сделок: {t.n_rows} строк, {_dm(t.first_date, ctx.as_of)} … {_dm(t.last_date, ctx.as_of)}.",
                          last_date=t.last_date))
    if ctx.prev_date:
        recent = Counter(r for r in t.rows if r[0] > ctx.prev_date)
        dups = [r for r, c in recent.items() if c > 1]
        if dups:
            out.append(_r("trades_duplicates_recent", "warning",
                          f"Одинаковые операции после прошлого снапшота ({len(dups)}): "
                          f"{_fmt_list(f'{_dm(d[0], ctx.as_of)} {d[1]} {d[2].lower()}' for d in dups)}. Двойная выгрузка или "
                          "законные одинаковые сделки — проверить.", rows=[list(d) for d in dups]))
    return out


def check_trade_integrity(ctx: Ctx) -> list[dict]:
    """Ошибки данных IntelInvest, найденные разбором кэш-дрейфа 13→16.10 (PDL-RECON):
    фантомное погашение дробным количеством, автокорректировка денег, задвоенные выплаты."""
    t = ctx.trades
    if t is None:
        return []
    out = []
    # 1. Облигация не бывает дробной: Борец 18.09 — «Продажа» 1,992045846 шт (фантом
    #    двойного погашения). Дробные купоны замещаек (RU000A10A869) — норма: только QTY_OPS.
    frac = [r for r in t.rows if r[2] in QTY_OPS and BOND_TICKER.match(r[1] or "")
            and r[3] and abs(r[3] - round(r[3])) > 1e-9]
    if frac:
        out.append(_r("bond_fractional_qty", "block",
                      "Дробное количество облигации в сделке: "
                      + _fmt_list(f"{_dm(r[0], ctx.as_of)} {r[1]} {r[2].lower()} {_num(r[3])} шт" for r in frac)
                      + ". Похоже на фантомную запись IntelInvest (кейс Борца 18.09) — удалить и выгрузить заново.",
                      rows=[list(r) for r in frac]))
    # 2. Автокорректировка денег при импорте отчёта брокера: −183 510 ₽ от 01.10 «на основе
    #    указанного баланса». Сама по себе законна, но крупная — повод сверить с брокером.
    lo = (dt.date.fromisoformat(ctx.as_of) - dt.timedelta(days=MONEY_CORRECTION_DAYS)).isoformat()
    corr = [r for r in t.rows if r[2] == "Корректировка" and str(r[1]).startswith("Деньги")
            and r[0] >= lo and r[4] is not None and abs(r[4]) >= MONEY_CORRECTION_RUB]
    if corr:
        out.append(_r("money_correction_recent", "warning",
                      f"Крупные денежные корректировки IntelInvest за {MONEY_CORRECTION_DAYS} дней: "
                      + _fmt_list(f"{_dm(r[0], ctx.as_of)} {_amt(r[4], _money_cur(r[1]), signed=True)}" for r in corr)
                      + ". Обычно — автосверка с отчётом брокера: значит, в выгрузке не хватает операций "
                      "или есть лишние (фантомы, дубли).", rows=[list(r) for r in corr]))
    # 3. Выплачено на больше бумаг, чем держали: дубли выплат (TPAY 08.10, ПГК 09.10) и
    #    амортизация, записанная ещё раз купоном. Две выплаты в день на разные счета — норма,
    #    поэтому сравнивается сумма количества с позицией, а не повтор строки.
    lo = (dt.date.fromisoformat(ctx.as_of) - dt.timedelta(days=PAYOUT_LOOKBACK_DAYS)).isoformat()
    groups: dict[tuple, list[tuple]] = {}
    fractional: set[tuple] = set()
    for r in t.rows:
        if r[2] in PAYOUT_OPS and r[0] >= lo and r[3]:
            k = (r[0], r[1], r[2])
            groups.setdefault(k, []).append((r[3], r[4]))
            if abs(r[3] - round(r[3])) > 1e-9:
                fractional.add(k)   # замещайки: «количество» в купоне — не штуки (RU000A10A869)
    over = []
    for (d, tk, op), qs in sorted(groups.items()):
        if (d, tk, op) in fractional:
            continue
        held, q = _held_before(t, tk, d), sum(x[0] for x in qs)
        if q > held + 1e-6:
            # Каждая строка в пределах позиции и суммы разные (DATA 24.06: 1200 + 1200 при
            # 1200, 2 488 и 309 ₽) — может быть выплата частями; одинаковые строки (TPAY
            # 08.10) — похоже на дубль. Подсказка в details.kind, не вердикт.
            kind = "single" if len(qs) == 1 else (
                "same_rows" if len(set(qs)) == 1 else
                "parts_possible" if max(x[0] for x in qs) <= held + 1e-6 else "differing")
            fresh = _new_flags(ctx, tk, op, d, qs)
            cur = _ticker_cur(ctx, tk)
            over.append({"ticker": tk, "name": _holding_name(ctx, tk), "date": d, "operation": op,
                         "held": round(held, 6), "paid_qty": round(q, 6), "currency": cur, "kind": kind,
                         "rows": [{"amount": x[1], "qty": x[0], "new": f} for x, f in zip(qs, fresh)]})
    if over:
        out.append(_r("payout_exceeds_holding", "warning", _payout_message(ctx, over), items=over))
    return out


def _holding_name(ctx: Ctx, ticker: str) -> str | None:
    for h in ctx.snap.get("holdings") or []:
        if h.get("ticker") == ticker and h.get("name") and h["name"] != ticker:
            return h["name"]
    return None


PAYOUT_FIX_RU = ("Что сделать: в IntelInvest оставить одну строку на дату, лишнюю удалить и пересобрать. "
                 "Если брокер платил частями — сумма строк должна равняться пришедшему на счёт.")


def _payout_message(ctx: Ctx, over: list[dict], n=8) -> str:
    lines = ["Похоже на дубли выплат: выплачено на больше бумаг, чем было на руках — обычно повторный импорт "
             f"(за последние {PAYOUT_LOOKBACK_DAYS} дн.)."]
    for it in over[:n]:
        rows = "; ".join(_amt(r["amount"], it["currency"]) + f" × {_num(r['qty'])} шт"
                         + (" (новая с прошлой сборки)" if r["new"] else "") if r["amount"] is not None
                         else f"{_num(r['qty'])} шт" for r in it["rows"])
        lab = it["ticker"] + (f" ({it['name']})" if it["name"] else "")
        lines.append(f"{lab} · {_dm(it['date'], ctx.as_of)} · {it['operation'].lower()} · "
                     f"на руках {_num(it['held'])} шт, выплачено на {_num(it['paid_qty'])} шт: {rows}")
    if len(over) > n:
        lines.append(f"и ещё {len(over) - n}")
    lines.append(PAYOUT_FIX_RU)
    return "\n".join(lines)


def _new_flags(ctx: Ctx, ticker: str, op: str, date: str, group: list[tuple]) -> list:
    """Для строк выплаты за дату: True — появилась после прошлой сборки, False — была, None — не определить.
    Опора — отпечаток выгрузки прошлого снапшота (trades_digest): по ячейке (бумага, операция) он даёт
    Δ строк, Δ суммы и Δ количества; строка «новая», если она входит в КАЖДЫЙ набор строк ячейки с такой
    разницей (одинаковые строки не различить — пометки нет). Строки после даты прошлого снапшота — новые."""
    import itertools
    import trades_digest as td  # noqa: WPS433
    none = [None] * len(group)
    old = (ctx.prev or {}).get("trades_digest")
    if not ctx.trades or not old or old.get("schema") != td.SCHEMA:
        return none
    upto = old["upto"]
    if date > upto:
        return [True] * len(group)
    cell = [(i, r) for i, r in enumerate(x for x in ctx.trades.rows
                                         if x[1] == ticker and x[2] == op and x[0] <= upto)]
    oc = (old.get("by_ticker") or {}).get(ticker, {}).get(op, [0, 0.0, 0.0])
    d_rows = len(cell) - oc[0]
    d_sum = round(sum(r[4] or 0.0 for _, r in cell) - oc[1], 2)
    d_qty = round(sum(r[3] or 0.0 for _, r in cell) - oc[2], 6)
    if d_rows == 0:
        return [False] * len(group) if abs(d_sum) <= 0.01 and abs(d_qty) <= 1e-6 else none
    if d_rows < 0 or len(cell) > 60:
        return none
    combos = [c for c in itertools.combinations(cell, d_rows)
              if abs(sum(r[4] or 0.0 for _, r in c) - d_sum) <= 0.01
              and abs(sum(r[3] or 0.0 for _, r in c) - d_qty) <= 1e-6]
    if not combos or len(combos) > 5000:
        return none
    sets = [{i for i, _ in c} for c in combos]
    always, ever = set.intersection(*sets), set.union(*sets)
    idx = [i for i, r in cell if r[0] == date and r[3]]
    if len(idx) != len(group):
        return none
    return [True if i in always else (False if i not in ever else None) for i in idx]


def _held_before(t: TradesInfo, ticker: str, date: str) -> float:
    """Сколько бумаг было накануне выплаты. Есть сделки — штатный reconstruct_positions
    (сплиты KNOWN_SPLITS, корректировки, валютные ключи: T 1:10, PLZL — без них счёт врёт);
    только строки (синтетика тестов) — покупки минус продажи."""
    if t.trades:
        from portfolio_returns import reconstruct_positions  # noqa: WPS433
        day = dt.date.fromisoformat(date) - dt.timedelta(days=1)
        # Валюта выплаты отделяет омонимы: T/RUB — Т-Технологии, T/USD — AT&T (заблокирован)
        cur = next((x.currency for x in t.trades if x.ticker == ticker and x.date.isoformat() == date
                    and x.operation in PAYOUT_OPS), None)
        by_cur = {k[1]: p.qty for k, p in reconstruct_positions(t.trades, day).items() if k[0] == ticker}
        # Позиция в валюте выплаты, если она есть; иначе сумма (облигация куплена в CNY,
        # купон в RUB — RU000A107RH8: строгий фильтр дал бы 0)
        if cur in by_cur and by_cur[cur] > 1e-9:
            return by_cur[cur]
        return sum(by_cur.values())
    q = 0.0
    for r in t.rows:
        if r[1] == ticker and r[0] < date and r[3]:
            if r[2] == "Покупка":
                q += r[3]
            elif r[2] == "Продажа":
                q -= r[3]
    return q


def check_backdated(ctx: Ctx) -> list[dict]:
    """Правки задним числом: отпечаток выгрузки прошлого снапшота против текущей выгрузки на ту
    же дату (trades_digest.py). Ловит то, что разбирали вручную 13→16.10: удалённые фантомы
    и дубли, автокорректировки, продажу ЭталонФин5, внесённую после снапшота."""
    import trades_digest as td  # noqa: WPS433
    old = (ctx.prev or {}).get("trades_digest")
    if not ctx.trades or not old or old.get("schema") != td.SCHEMA:
        return []
    new = td.from_rows(ctx.trades.rows, old["upto"])
    cells = td.diff(old, new)
    if not cells:
        return [_r("trades_unchanged_before_prev", "info",
                   f"Строки выгрузки до {_dm(old['upto'], ctx.as_of)} не менялись с прошлого снапшота.")]
    same_day = _same_day_cells(ctx)
    cells = [c for c in cells if c not in same_day]
    money = [c for c in cells if c["ticker"].startswith("Деньги")]
    papers = [c for c in cells if not c["ticker"].startswith("Деньги")]
    # Поздно внесённая выплата (дивиденд BTBR 14.10 появился после снапшота 16.10) — норма
    # импорта отчёта брокера; удаление строк, сделки и корректировки задним числом — нет.
    late_payouts = [c for c in papers if c["operation"] in td.PAYOUT_OPS and c["rows"] > 0 and c["sum"] > 0]
    other = [c for c in papers if c not in late_payouts]

    ref = ctx.as_of
    upto = _dm(old["upto"], ref)

    def fmt(c, verb=True):
        """Ячейка отпечатка → «NVTK (Новатэк) · дивиденд: удалено 1 стр. на 2 911 ₽»."""
        cur = _ticker_cur(ctx, c["ticker"])
        n, op = c["rows"], c["operation"].lower()
        head = f"{_label(ctx, c['ticker'])} · {op}"
        qty = f" ({_num(abs(c['qty']))} шт)" if c["qty"] and c["operation"] in QTY_OPS else ""
        if n > 0:
            return f"{head}: добавлено {n} стр.{qty} на {_amt(abs(c['sum']), cur)}"
        if n < 0:
            return f"{head}: удалено {-n} стр.{qty} на {_amt(abs(c['sum']), cur)}"
        return f"{head}: сумма строк изменилась на {_amt(c['sum'], cur, signed=True)} (число строк то же)"

    out = []
    if same_day:
        # Сделки дня прошлого снапшота, появившиеся после его сборки, — не правка задним числом:
        # снапшот собран днём, отчёт брокера за этот день пришёл позже (OZON 03.11: сборка 13:42)
        built = str(ctx.prev.get("generated_at") or "")[11:16]
        day_money = round(sum(c["sum"] for c in same_day if c["ticker"].startswith("Деньги")), 2)
        out.append(_r("trades_on_prev_snapshot_day", "info",
                      f"В день прошлого снапшота ({upto}"
                      + (f", собран в {built}" if built else "") + ") после его сборки внесены: "
                      + "; ".join(fmt(c) for c in sorted(same_day, key=lambda c: c["ticker"].startswith("Деньги")))
                      + ". Это строки того же дня, а не правки задним числом; прошлый снапшот их не содержит.",
                      cells=same_day, money_total=day_money))
    if other:
        # Чистка дублей: всё, что изменилось, — удаление строк тех бумаг и операций, что прошлая сборка
        # пометила как подозрительные (build_suspects снапшота) — это ожидаемый результат правки владельца
        suspects = {tuple(x) for x in (ctx.prev or {}).get("build_suspects") or []}
        cleanup = all(c["rows"] < 0 and (c["ticker"], c["operation"]) in suspects for c in other)
        tail = ("Если это чистка дублей — всё правильно." if cleanup
                else "Удаление, сделка или корректировка задним числом — прошлые снапшоты считались на других данных.")
        out.append(_r("trades_changed_before_prev", "info" if cleanup else "warning",
                      f"Удалено/изменено задним числом (с прошлой сборки, строки до {upto}): "
                      + "; ".join(fmt(c) for c in other) + ". " + tail,
                      cells=other, cleanup=cleanup))
    if late_payouts:
        out.append(_r("payouts_recorded_late", "info",
                      f"Выплаты, датированные до {upto}, внесены после прошлой сборки: "
                      + "; ".join(fmt(c) for c in late_payouts) + ".", cells=late_payouts))
    if money:
        total = round(sum(c["sum"] for c in money), 2)
        # Порог — по каждой ячейке, не по итогу: 16→21.10 итог +4 080, а внутри −170 859
        # (удалённые внесения фантома и дублей) и +174 939 (сжатая автокорректировка).
        big = any(abs(c["sum"]) >= MONEY_CORRECTION_RUB for c in money)

        def mfmt(c):
            cur = _money_cur(c["ticker"])
            if c["rows"]:
                return f"{c['operation'].lower()} — {abs(c['rows'])} стр. на {_amt(abs(c['sum']), cur)}"
            return f"{c['operation'].lower()} — {_amt(c['sum'], cur, signed=True)}"
        added = [mfmt(c) for c in money if c["rows"] > 0]
        removed = [mfmt(c) for c in money if c["rows"] < 0]
        changed = [mfmt(c) for c in money if c["rows"] == 0]
        parts = [f"{name}: " + "; ".join(xs) for name, xs in
                 (("добавлено", added), ("удалено", removed), ("изменено", changed)) if xs]
        lines = [f"В истории денежных операций (до прошлой сборки, {upto}) появились или исчезли строки:"] + parts
        cash_line, cash_det = _cash_answer(ctx)
        if cash_line:
            lines.append(cash_line)
        out.append(_r("money_rows_changed_before_prev", "warning" if big else "info", "\n".join(lines),
                      cells=money, total=total, cash=cash_det))
    return out


def _cash_answer(ctx: Ctx) -> tuple[str | None, dict | None]:
    """Прямой ответ «кэш сломался?»: расхождение «факт − реконструкция» этого снапшота против прошлого.
    Порог — тот же, что у проверки кэша (cash_reconciliation.threshold_rub). Нет расхождения — нет строки."""
    cur = (ctx.snap.get("cash_reconciliation") or {})
    was = ((ctx.prev or {}).get("cash_reconciliation") or {})
    x, y = cur.get("current_drift_rub"), was.get("current_drift_rub")
    if x is None or y is None:
        return None, None
    thr = cur.get("threshold_rub") or 10000.0
    delta = round(x - y, 2)
    det = {"drift_rub": x, "prev_drift_rub": y, "delta_rub": delta, "threshold_rub": thr}
    if (ctx.snap.get("cash") or {}).get("source") == "trades_plus_prev_drift":
        return (f"Кэш — оценка (факт из IntelInvest не вносился): расхождение взято из прошлой сборки, "
                f"{_amt(y, signed=True)}; чтобы проверить, внесите кэш из IntelInvest.", det)
    if abs(delta) <= thr:
        return (f"Кэш после правок сходится с вашим фактом так же, как раньше: расхождение "
                f"{_amt(x, signed=True)} (было {_amt(y, signed=True)}) — ничего не сломалось.", det)
    return (f"Кэш: расхождение с вашим фактом изменилось на {_amt(delta, signed=True)} "
            f"(было {_amt(y, signed=True)}, стало {_amt(x, signed=True)}) — проверьте.", det)


def suspects_for_snapshot(results: list[dict]) -> list[list[str]]:
    """Бумаги и операции, помеченные подозрительными в этой сборке (дубли выплат, выплаты, внесённые
    позже): пишутся в снапшот (build_suspects), чтобы следующая сборка узнала в удалении строк чистку."""
    out: list[list[str]] = []
    for r in results:
        d = r.get("details") or {}
        if r["id"] == "payout_exceeds_holding":
            out += [[i["ticker"], i["operation"]] for i in d.get("items") or []]
        elif r["id"] == "payouts_recorded_late":
            out += [[c["ticker"], c["operation"]] for c in d.get("cells") or []]
    return [list(x) for x in dict.fromkeys(tuple(x) for x in out)]


# ───────────────────────────── позиции ─────────────────────────────

def check_positions(ctx: Ctx) -> list[dict]:
    snap, out = ctx.snap, []
    neg = [h.get("ticker") for h in snap.get("holdings") or [] if (h.get("qty") or 0) < 0]
    if neg:
        out.append(_r("holdings_negative_qty", "block",
                      f"Отрицательное количество: {_fmt_list(neg)}.", tickers=neg))
    no_value = [h.get("ticker") for h in _active(snap) if h.get("value_rub") is None]
    if no_value:
        out.append(_r("holdings_no_value", "warning",
                      f"Активные позиции без стоимости: {_fmt_list(no_value)}.", tickers=no_value))
    no_sector = [h.get("ticker") for h in _active(snap)
                 if h.get("asset_type") == "stock" and not h.get("sector")]
    if no_sector:
        out.append(_r("stock_no_sector", "warning",
                      f"Акции без сектора: {_fmt_list(no_sector)} — дополнить sector-overrides.yaml.",
                      tickers=no_sector))
    if ctx.prev is None:
        return out

    moved = _moved_since(ctx)
    prev_h = {_key(h): h for h in _active(ctx.prev)}
    cur_h = {_key(h): h for h in _active(snap)}

    gone = [k for k in prev_h if k not in cur_h]
    gone_ok, gone_stale, gone_bad = [], [], []
    for k in gone:
        tk = k[0]
        if tk in moved:
            gone_ok.append(tk)
        elif ctx.trades and _sold_before(ctx.trades, tk, ctx.prev_date):
            gone_stale.append(tk)
        else:
            gone_bad.append(tk)
    if gone_bad:
        out.append(_r("holding_gone_without_trade", "warning" if ctx.trades else "info",
                      f"Пропали из позиций без продажи после {_dm(ctx.prev_date, ctx.as_of)}: {_fmt_list(gone_bad)}. "
                      "Погашение, перевод между счетами или неполная выгрузка?", tickers=gone_bad))
    if gone_stale:
        # ЭталонФин5 (RU000A10EST2): продажа от 28.09 появилась в выгрузке после снапшота 13.10,
        # который ещё держал бумагу, — сделка внесена задним числом (inc-2026-10-21-1)
        out.append(_r("holding_gone_sold_earlier", "warning",
                      f"Пропали из позиций, но продажа датирована раньше прошлого снапшота "
                      f"{_dm(ctx.prev_date, ctx.as_of)}, который их ещё держал: {_fmt_list(gone_stale)}. Сделка внесена "
                      "задним числом — кэш и доходность прошлых снапшотов были неточны.", tickers=gone_stale))
    if gone_ok:
        out.append(_r("holding_gone_sold", "info",
                      f"Закрыты после прошлого снапшота ({_dm(ctx.prev_date, ctx.as_of)}): {_fmt_list(gone_ok)}.", tickers=gone_ok))

    new = [k[0] for k in cur_h if k not in prev_h]
    if new:
        out.append(_r("holding_new", "info", f"Новые позиции: {_fmt_list(new)}.", tickers=new))

    qty_odd, splitlike, jumps = [], [], []
    for k, h in cur_h.items():
        p = prev_h.get(k)
        if not p:
            continue
        q0, q1 = p.get("qty") or 0, h.get("qty") or 0
        if q0 != q1 and k[0] not in moved and ctx.trades:
            ratio = q1 / q0 if q0 else None
            if ratio and ratio >= 2 and abs(ratio - round(ratio)) < 1e-9:
                splitlike.append(f"{k[0]} ×{int(round(ratio))}")
            else:
                qty_odd.append(f"{k[0]} {q0:g}→{q1:g}")
        v0, v1 = p.get("value_rub"), h.get("value_rub")
        if q0 == q1 and v0 and v1 is not None and k[0] not in moved and abs(v1 / v0 - 1) > VALUE_JUMP_WARN:
            jumps.append(f"{k[0]} {100 * (v1 / v0 - 1):+.0f}%")
    if splitlike:
        out.append(_r("qty_split_like", "warning",
                      f"Количество выросло в целое число раз без сделок: {_fmt_list(splitlike)} — похоже "
                      "на сплит; проверить KNOWN_SPLITS в portfolio_returns.py.", items=splitlike))
    if qty_odd:
        out.append(_r("qty_changed_without_trade", "warning",
                      f"Количество изменилось без сделок после прошлого снапшота ({_dm(ctx.prev_date, ctx.as_of)}): {_fmt_list(qty_odd)}.",
                      items=qty_odd))
    if jumps:
        out.append(_r("value_jump", "warning",
                      f"Стоимость позиции изменилась более чем на {VALUE_JUMP_WARN:.0%} без сделок: "
                      f"{_fmt_list(jumps)}.", items=jumps))
    return out


def _moved_since(ctx: Ctx) -> set[str]:
    """Бумаги с покупкой/продажей/корректировкой после прошлого снапшота."""
    if not ctx.trades or not ctx.prev_date:
        return set()
    moved = {r[1] for r in ctx.trades.rows if r[0] > ctx.prev_date and r[2] in FLOW_OPS}
    return moved | {c["ticker"] for c in _same_day_cells(ctx) if c["operation"] in FLOW_OPS}


def _same_day_cells(ctx: Ctx) -> list[dict]:
    """Ячейки (тикер, операция), где вся разница с отпечатком прошлого снапшота — строки, датированные
    его же днём и внесённые после сборки. Времени сделки в выгрузке нет, поэтому условий два: снапшот
    собран в свой день (`generated_at`), и его отпечаток по ячейке равен строкам текущей выгрузки строго
    до этого дня. Ячейка, где строки этого дня уже были в прошлой выгрузке или менялось что-то раньше,
    сюда не попадает и остаётся правкой задним числом."""
    import trades_digest as td  # noqa: WPS433
    prev = ctx.prev or {}
    old = prev.get("trades_digest")
    if not ctx.trades or not old or old.get("schema") != td.SCHEMA:
        return []
    day = old["upto"]
    if str(prev.get("generated_at") or "")[:10] != day:
        return []
    before = td.from_rows([r for r in ctx.trades.rows if r[0] < day], day)
    changed_before = {(c["ticker"], c["operation"]) for c in td.diff(old, before)}
    return [c for c in td.diff(old, td.from_rows(ctx.trades.rows, day))
            if (c["ticker"], c["operation"]) not in changed_before]


def _sold_before(t: TradesInfo, ticker: str, date: str) -> bool:
    return any(r[1] == ticker and r[2] in SALE_OPS and r[0] <= date for r in t.rows)


# ───────────────────────────── кэш ─────────────────────────────

def check_cash(ctx: Ctx) -> list[dict]:
    cash, out = ctx.snap.get("cash") or {}, []
    total = cash.get("total_rub")
    if total is not None and total < 0:
        out.append(_r("cash_negative", "block", f"Кэш отрицательный: {total:,.0f} ₽.", total_rub=total))
    neg_acc = {k: v for k, v in (cash.get("by_account") or {}).items() if v is not None and v < 0}
    if neg_acc:
        out.append(_r("cash_negative_account", "warning",
                      "Отрицательный кэш по счёту: " + ", ".join(f"{k} {v:,.0f} ₽" for k, v in neg_acc.items()),
                      by_account=neg_acc))
    ce, liq = cash.get("cash_equiv_rub"), cash.get("liquid_rub")
    if None not in (total, ce, liq) and abs(liq - (total + ce)) > CASH_EQ_TOL_RUB:
        out.append(_r("cash_liquid_mismatch", "warning",
                      f"liquid_rub {liq:,.0f} ≠ кэш {total:,.0f} + фонды ликвидности {ce:,.0f}.",
                      liquid_rub=liq, total_rub=total, cash_equiv_rub=ce))
    bad_eq = [t for t in (cash.get("cash_equiv_tickers") or {}) if t in MANUAL_VALUATION]
    if bad_eq:
        out.append(_r("cash_equiv_wrong_ticker", "block",
                      f"{_fmt_list(bad_eq)} попал в фонды ликвидности — это не кэш (SKILL.md, Шаг 6).",
                      tickers=bad_eq))
    return out


# ───────────────────────────── котировки и курсы ─────────────────────────────

def check_quotes(ctx: Ctx) -> list[dict]:
    out, act = [], [h for h in _active(ctx.snap) if h.get("ticker") not in MANUAL_VALUATION]
    if not act:
        return out
    non_moex = [h.get("ticker") for h in act if h.get("current_price_source") != "moex_iss"]
    share = len(non_moex) / len(act)
    if non_moex:
        out.append(_r("quotes_non_moex", "warning" if share > NON_MOEX_SHARE_WARN else "info",
                      f"Без котировки MOEX {len(non_moex)} из {len(act)} позиций ({share:.0%}): "
                      f"{_fmt_list(non_moex)}.", tickers=non_moex, share=round(share, 4)))
    lo = (dt.date.fromisoformat(ctx.as_of) - dt.timedelta(days=QUOTE_STALE_DAYS)).isoformat()
    stale = [f"{h.get('ticker')} ({_dm(h['current_price_ts'], ctx.as_of)})" for h in act
             if h.get("current_price_source") == "moex_iss" and h.get("current_price_ts")
             and h["current_price_ts"][:10] < lo]
    if stale:
        out.append(_r("quotes_stale", "warning",
                      f"Котировки старше {_dm(lo, ctx.as_of)}: {_fmt_list(stale)}.", items=stale))
    moex_bonds = [h for h in act if h.get("asset_type") == "bond"
                  and h.get("current_price_source") == "moex_iss"]
    no_nkd = [h.get("ticker") for h in moex_bonds if h.get("accrued_int") is None]
    if no_nkd:
        out.append(_r("bonds_missing_accrued", "warning",
                      f"Облигации без НКД от MOEX (стоимость занижена): {_fmt_list(no_nkd)}.", tickers=no_nkd))
    # Ставку флоатера MOEX до фиксации купона не отдаёт (ОФЗ 29027, 2026-10-16) — не ошибка
    no_cpn = [h.get("ticker") + (" (флоатер)" if h.get("plan_subtype") == "Флоат" else "")
              for h in moex_bonds if h.get("accrued_int") is not None and h.get("coupon_pct") is None]
    if no_cpn:
        out.append(_r("bonds_missing_coupon_pct", "info",
                      f"Облигации без ставки купона от MOEX: {_fmt_list(no_cpn)}.", tickers=no_cpn))
    fx = ctx.snap.get("fx_rates_used") or {}
    lo_fx = (dt.date.fromisoformat(ctx.as_of) - dt.timedelta(days=FX_STALE_DAYS)).isoformat()
    fx_stale = [f"{c} {_dm(v['rate_date'], ctx.as_of)}" for c, v in fx.items()
                if isinstance(v, dict) and v.get("rate_date") and v["rate_date"] < lo_fx]
    if fx_stale:
        out.append(_r("fx_stale", "warning", f"Курсы ЦБ старше {_dm(lo_fx, ctx.as_of)}: {_fmt_list(fx_stale)}.",
                      items=fx_stale))
    return out


# ───────────────────────────── итоговый снапшот ─────────────────────────────

def _non_finite(obj, path="$", acc=None):
    acc = [] if acc is None else acc
    if isinstance(obj, float) and not math.isfinite(obj):
        acc.append(path)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _non_finite(v, f"{path}.{k}", acc)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _non_finite(v, f"{path}[{i}]", acc)
    return acc


def check_snapshot(ctx: Ctx) -> list[dict]:
    snap, out = ctx.snap, []
    missing = [k for k in REQUIRED_KEYS if k not in snap]
    if missing or snap.get("schema_version") != "2.0":
        out.append(_r("schema", "block",
                      f"Схема снапшота: нет ключей {missing or '—'}, schema_version="
                      f"{snap.get('schema_version')!r} (ожидается '2.0').", missing=missing))
    if snap.get("as_of_date") != ctx.as_of:
        out.append(_r("as_of_mismatch", "block",
                      f"Дата снапшота {_dm(snap.get('as_of_date'), ctx.as_of) if snap.get('as_of_date') else '—'} ≠ дата сборки {_dm(ctx.as_of, ctx.as_of)}."))
    bad = _non_finite(snap)
    if bad:
        out.append(_r("non_finite", "block", f"NaN/бесконечность в полях: {_fmt_list(bad)}.", paths=bad))
    # Инвариант баланса (SKILL.md Шаг 6): незаблокированные позиции + кэш = «Имеется (RUB)»
    have = ((snap.get("balance_summary") or {}).get("summary") or {}).get("Имеется (RUB)")
    total = (snap.get("cash") or {}).get("total_rub")
    if have is not None and total is not None:
        hold = sum(h.get("value_rub") or 0 for h in _active(snap))
        if abs(hold + total - have) > INVARIANT_TOL_RUB:
            out.append(_r("balance_invariant", "block",
                          f"Позиции {hold:,.0f} + кэш {total:,.0f} ≠ «Имеется» {have:,.0f} ₽.",
                          holdings_rub=hold, cash_rub=total, have_rub=have))
    # флаги severity error сборки — числа снапшота неверны, запись запрещена
    for code, default in (("fx_rates_missing", "Нет курсов ЦБ."),
                          ("returns_price_not_moex", "Доходность посчитана не по цене MOEX."),
                          ("per_instrument_price_not_moex", "XIRR по бумагам посчитан не по цене MOEX.")):
        hit = [f for f in snap.get("data_quality_flags") or [] if f.get("code") == code]
        if hit:
            out.append(_r(code, "block", hit[0].get("message", default), flag=hit[0]))
    by_status = (snap.get("status_summary") or {}).get("by_status") or {}
    pct = sum(v.get("pct") or 0 for v in by_status.values() if isinstance(v, dict))
    if by_status and abs(pct - 100) > 0.1:
        out.append(_r("status_pct_sum", "warning", f"Доли по статусам в сумме {pct:.2f}%, а не 100%."))
    x = ((snap.get("returns") or {}).get("restricted") or {}).get("xirr")
    if isinstance(x, (int, float)) and not XIRR_SANE[0] <= x <= XIRR_SANE[1]:
        out.append(_r("xirr_out_of_range", "warning", f"XIRR (restricted) {x:.2%} вне разумных границ."))
    if ctx.prev:
        x0 = ((ctx.prev.get("returns") or {}).get("restricted") or {}).get("xirr")
        if isinstance(x, (int, float)) and isinstance(x0, (int, float)):
            out.append(_r("xirr_vs_prev", "info",
                          f"XIRR (restricted): {x0:.2%} → {x:.2%} (Δ {100 * (x - x0):+.2f} п.п.).",
                          prev=x0, cur=x))
    unm = [f for f in snap.get("data_quality_flags") or [] if f.get("code") == "fund_unmapped"]
    if unm:
        out.append(_r("fund_unmapped", "warning",
                      "Фонд без класса в plan.funds: " + " ".join(f.get("message", "") for f in unm),
                      n=len(unm)))
    pc = snap.get("plan_check") or {}
    if pc.get("source") == "error":
        out.append(_r("plan_unreadable", "warning",
                      f"plan.json не прочитан: {pc.get('error')}. "
                      + ("Доли и цели взяты из прошлого снапшота." if snap.get("snapshot_type") == "trades_holdings"
                         else "План проверен только по Numbers."),
                      plan_file=pc.get("plan_file")))
    elif (pc.get("n_diff") or 0) > 0:
        paths = [d.get("path") for d in pc.get("diff") or []]
        if pc.get("source") == "plan_primary":
            out.append(_r("numbers_stale", "warning",
                          f"Numbers отстаёт от плана на сайте по {pc['n_diff']} полям: {_fmt_list(paths, 8)}.",
                          n_diff=pc["n_diff"], paths=paths))
            return out
        out.append(_r("plan_mismatch", "warning",
                      f"план в plan.json расходится с Numbers по {pc['n_diff']} полям: {_fmt_list(paths, 8)}.",
                      n_diff=pc["n_diff"], paths=paths))
    return out


def _fmt_date(iso: str) -> str:
    return dt.date.fromisoformat(iso[:10]).strftime("%d.%m.%Y")


def _fmt_price(x: float) -> str:
    return f"{x:,.2f}".replace(",", " ").rstrip("0").rstrip(".") if abs(x) < 1000 else f"{x:,.0f}".replace(",", " ")


def check_split_suspected(ctx: Ctx) -> list[dict]:
    """Биржевая цена бумаги без сделок изменилась в целое число раз против прошлого снапшота, а сплита
    в реестре нет — вероятный сплит. Сеть — только для уточнения даты у подозреваемых."""
    if ctx.prev is None or not ctx.prev_date:
        return []
    registry = ctx.splits if ctx.splits is not None else known_splits.BUILTIN
    dismissed = ctx.dismissed or []
    lo, hi = ctx.prev_date[:10], ctx.as_of[:10]

    def in_window(d) -> bool:
        d = d.isoformat() if isinstance(d, dt.date) else str(d)[:10]
        return lo < d <= hi

    prev_h = {_key(h): h for h in _active(ctx.prev)}
    out, seen = [], set()
    for h in _active(ctx.snap):
        tk = h.get("ticker")
        p = prev_h.get(_key(h))
        if not tk or tk in seen or not p or h.get("asset_type") not in ("stock", "fund"):
            continue
        if h.get("current_price_source") != "moex_iss" or p.get("current_price_source") != "moex_iss":
            continue
        p0, p1 = p.get("current_price"), h.get("current_price")
        if not isinstance(p0, (int, float)) or not isinstance(p1, (int, float)) or p0 <= 0 or p1 <= 0:
            continue
        ratio = known_splits.suspect_ratio(p0, p1)
        if ratio is None:
            continue
        if any(in_window(e["date"]) for e in registry.get(tk, [])):
            continue
        if any(e.get("ticker") == tk and in_window(e.get("date", "")) and e.get("ratio")
               and abs(float(e["ratio"]) / ratio - 1) <= known_splits.DETECT_TOL for e in dismissed):
            continue
        seen.add(tk)
        # История цен — подтверждение: сплит виден как скачок между СОСЕДНИМИ торговыми днями.
        # История получена, а такого скачка нет — цена дошла до нового уровня постепенно, это не сплит.
        try:
            found = known_splits.find_split_date(tk, lo, hi, ratio=ratio, fetch=ctx.fetch)
        except Exception:  # noqa: BLE001 — сеть не должна ронять проверки: подозрение выдаём без даты
            found = None
        else:
            if found is None:
                continue
        date = found["date"] if found else None
        n = round(ratio) if ratio > 1 else round(1 / ratio)
        kind = f"сплит {tk} 1:{n}" if ratio > 1 else f"обратный сплит {tk} {n}:1"
        extra = ""
        if found:
            extra = f", торги возобновились {_fmt_date(found['date'])}"
            if found["halt_days"]:
                extra += f" после {found['halt_days']} дн. без торгов"
        evidence = ({k: found[k] for k in ("prev_close", "new_close", "halt_days")} if found else None)
        out.append(_r("split_suspected", "warning",
                      f"Похоже на {kind}: цена {_fmt_price(p0)} → {_fmt_price(p1)}{extra}. Количество и "
                      "стоимость бумаги в этой сборке неверны, пока сплит не внесён в реестр. Подтверди — "
                      "запись в Portfolio/known-splits.json.",
                      ticker=tk, ratio=ratio, date=date, prev_price=p0, cur_price=p1, evidence=evidence,
                      entry={"ticker": tk, "date": date, "ratio": ratio,
                             "note": f"Сплит {tk} " + (f"1:{n}" if ratio > 1 else f"{n}:1 (обратный)")}))
    return out


CHECKS = (check_trades, check_trade_integrity, check_backdated, check_positions, check_cash, check_quotes,
          check_snapshot, check_split_suspected)
ORDER = {"block": 0, "warning": 1, "info": 2}


def run_all(snap: dict, prev: dict | None, *, trades_info: TradesInfo | None = None,
            as_of: str | None = None, returns: dict | None = None,
            splits: dict | None = None, dismissed: list | None = None, fetch=None) -> list[dict]:
    ctx = Ctx(snap=snap, prev=prev, trades=trades_info,
              as_of=as_of or snap.get("as_of_date") or dt.date.today().isoformat(), returns=returns,
              splits=splits, dismissed=dismissed, fetch=fetch)
    res = [r for fn in CHECKS for r in fn(ctx)]
    return sorted(res, key=lambda r: ORDER[r["level"]])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Проверки целостности снапшота портфеля.")
    ap.add_argument("snapshot")
    ap.add_argument("--prev")
    ap.add_argument("--trades")
    ap.add_argument("--as-of")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    snap = json.loads(Path(a.snapshot).read_text(encoding="utf-8"))
    prev = json.loads(Path(a.prev).read_text(encoding="utf-8")) if a.prev else None
    res = run_all(snap, prev, trades_info=inspect_trades(a.trades) if a.trades else None, as_of=a.as_of)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        for r in res:
            print(f"[{r['level']}] {r['id']}: {r['message_ru']}")
    return 2 if any(r["level"] == "block" for r in res) else 0


if __name__ == "__main__":
    sys.exit(main())
