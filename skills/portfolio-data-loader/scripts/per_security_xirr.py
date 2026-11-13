#!/usr/bin/env python3
"""
Per-security XIRR — доходность отдельной бумаги (или нескольких) из портфеля.

Использует методологию portfolio_returns.py:
  cashflows = [
    -abs(amount_rub) для каждой Покупки,
    +abs(amount_rub) для каждой Продажи, Купона, Дивиденда, Амортизации,
    +market_value_rub на as_of (терминал),
  ]
  XIRR — тот же решатель, что в portfolio_returns (Newton + bisection).

Кроссвалютные позиции (TGLD: USD-покупка + RUB-покупки/продажи) обрабатываются
автоматически — reconstruct_positions + merge_cross_currency_positions дают
единый qty и total_cost в рублях.

Источники текущей цены (в порядке приоритета):
  1. MOEX: готовый quotes.json (--quotes, тот же, что у holdings снапшота) —
     по бумагам, которых там нет, добор через fetch_moex_prices (MOEX ISS);
     без --quotes — fetch_moex_prices по всем (облигации — грязная стоимость
     + НКД)
  2. --common — стоимость из «Общего баланса» / common_portfolio.xlsx (запасной
     вариант, пока нет котировки MOEX; всегда сохраняется в balance_value_rub)
  3. last_trade_price — последняя цена из trades
  4. cost_basis — если ничего не удалось
  (до 2026-10-13 порядок был обратным: баланс первым — «Цена» баланса бывает
  устаревшей, CNRU 671,4 против MOEX 661,8.)

Когда использовать:
  - Single Analysis режим скилла: «какая доходность у ГазКЗ-27Д2 с момента покупки»
  - Rebalance Opinion: обоснование удержания/продажи конкретной позиции
  - Returns Analysis: глубокий drill-down вопроса «что внутри тянет?»

Валидировано на 9 бумагах пользователя (2026-04-20): расхождение с
IntelInvest XIRR ≤ 0.25 п.п. по всем типам — акции, ОФЗ, корп. RUB, USD/CNY
замещайки, кроссвалютные фонды (TGLD), закрытые позиции, бумаги со сплитом
(PLZL 1:10). См. tests/test_per_security_xirr.py.

Использование:
  # Один тикер, MOEX для цены
  python3 scripts/per_security_xirr.py --trades /tmp/trades.xlsx --tickers SU26243RMFS4

  # Несколько тикеров с явными market value из common_portfolio
  python3 scripts/per_security_xirr.py --trades /tmp/trades.xlsx \\
      --common /tmp/common.xlsx --tickers TGLD,PLZL,RENI

  # Без MOEX (offline, fallback на last_trade_price)
  python3 scripts/per_security_xirr.py --trades /tmp/trades.xlsx \\
      --tickers SIBN --no-moex

  # JSON для обработки
  python3 scripts/per_security_xirr.py --trades /tmp/trades.xlsx \\
      --tickers RENI --format json --no-cashflows > /tmp/ret.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import defaultdict
from pathlib import Path

# Для запуска из scripts/ — добавляем свою директорию в path, чтобы
# импортировать portfolio_returns, независимо от того, где лежит скилл.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from portfolio_returns import (  # noqa: E402
    parse_trades, convert_trades_to_rub, apply_corrections,
    reconstruct_positions, classify_instrument_type, load_cbr_cache, load_types_cache, load_known_splits as pr_load_known_splits,
    fetch_moex_prices, moex_prices_from_quotes, last_known_trade_price, estimate_position_value_rub,
    xirr,
)


def _compute_recent_window(
    ticker_trades: list,
    as_of: dt.date,
    window_days: int,
) -> dict:
    """
    Свёртка недавних buy/sell-сделок по одной бумаге в скользящем окне
    [as_of − window_days; as_of] (обе границы включительно).

    Только для правила неразворота ru-portfolio-advisor (Rule 3): нужно
    направление и размер недавнего движения по позиции, а не история сделок.

    Что НЕ входит в net/n_buys/n_sells и почему (решения владельца):
      • Купон/Дивиденд/Амортизация — приток денег, не меняющий экспозицию;
        по деньгам неотличимы от продажи, но продажей не являются.
      • Корректировка (Korrektirovka) — синтетическая запись реконсиляции
        IntelInvest↔отчёт брокера (см. reconstruct_positions), а не решение
        владельца двигать позицию. Издержки, ради которых вводится правило
        неразворота (повторная комиссия, НДФЛ с реализованной прибыли,
        обнуление 3-летнего срока ЛДВ по новому лоту), к Корректировке не
        применимы — там нет ни комиссии, ни нового лота, ни воли владельца.
        Осознанно исключена; см. также docs skill'а-потребителя.

    Направление (buy/trim) здесь НЕ классифицируется — для этого нужен
    порог (акционная книга), которого на этом уровне нет. Классификация —
    забота assemble_snapshot.py (_derive_recent_net_threshold), у которого
    есть balance_summary/goals_matrix.
    """
    cutoff = as_of - dt.timedelta(days=window_days)
    net = 0.0
    n_buys = n_sells = 0
    last_date: dt.date | None = None
    for t in ticker_trades:
        if t.date > as_of or t.date < cutoff:
            continue
        if t.operation == "Покупка":
            amt = abs(t.rub_amount)
            net += amt
            n_buys += 1
            last_date = t.date if last_date is None else max(last_date, t.date)
        elif t.operation == "Продажа":
            amt = abs(t.rub_amount)
            net -= amt
            n_sells += 1
            last_date = t.date if last_date is None else max(last_date, t.date)
        # Купон/Дивиденд/Амортизация/Корректировка — намеренно пропущены (см. docstring).
    return {
        "recent_window_days": window_days,
        "recent_net_rub": round(net, 2),
        "recent_n_buys": n_buys,
        "recent_n_sells": n_sells,
        "recent_last_trade_date": last_date.isoformat() if last_date else None,
        "recent_round_trip": n_buys > 0 and n_sells > 0,
    }


# =============================================================================
# Public API
# =============================================================================


def per_security_xirr(
    tickers: list[str],
    trades_path: str,
    as_of: dt.date,
    use_moex: bool = True,
    verbose: bool = False,
    market_values_override: dict[str, float] | None = None,
    cbr_offline: bool = False,
    recent_window_days: int = 60,
    quotes: dict | None = None,
) -> dict[str, dict]:
    """
    Считает XIRR и связанные метрики отдельно по каждому тикеру.

    Аргументы:
      tickers: список тикеров для расчёта (например, ["TGLD", "PLZL"])
      trades_path: путь к trades_portfolio_*.xlsx из IntelInvest
      as_of: дата расчёта (обычно "сегодня")
      use_moex: тянуть ли LAST-цены из MOEX ISS. False = только fallback.
      market_values_override: {ticker: mv_rub} — ЗАПАСНОЙ вариант оценки
        (стоимость «Общего баланса» / common_portfolio.xlsx). MOEX first
        (инцидент 2026-10-13: «Цена» баланса бывает устаревшей — CNRU 671,4
        против MOEX 661,8): если по тикеру есть котировка MOEX, market value =
        qty × MOEX (облигации — грязная + НКД), override не используется;
        без котировки (нет сети / бумага не торгуется / use_moex=False) —
        берётся override. Значение баланса в любом случае сохраняется в
        результате как balance_value_rub (для сверки).
      quotes: {secid: Quote.to_dict()} из quotes.json (moex_quotes.py --json) —
        общий источник цен со снапшотом: цены берутся оттуда, в MOEX ISS идём
        только за бумагами, которых в quotes нет. Игнорируется при use_moex=False.
      cbr_offline: True — не ходим в ЦБ РФ, используем только bundled+/tmp кэш.
      recent_window_days: ширина скользящего окна для свёртки недавних
        buy/sell-сделок (см. recent_* поля ниже). Параметр, не константа —
        потребитель (ru-portfolio-advisor, правило неразворота) может
        запросить другое окно.

    Возвращает:
      {ticker: {
        "ticker": str, "inst_type": "stock"|"bond"|"fund"|"other", "name": str | None,
        "last_sell_date": ISO | None,  # последняя продажа/погашение (дата закрытия позиции)
        "qty_now": float, "first_trade_date": ISO, "last_trade_date": ISO,
        "n_buys": int, "n_sells": int, "n_coupons": int,
        "n_divs": int, "n_amorts": int, "n_corrections": int,
        "n_cashflows": int,
        "buy_total_rub": float, "sell_total_rub": float,
        "coupons_rub": float, "dividends_rub": float, "amortization_rub": float,
        "corr_buy_rub": float, "corr_sell_rub": float,
        # Korrektirovka (IntelInvest reconciliation с отчётом брокера) включается
        # в cashflow стрим симметрично reconstruct_positions: amt>0 → quasi-buy,
        # amt<0 → quasi-sell.
        "market_value_rub": float, "price_source": str,
        "balance_value_rub": float | None,  # стоимость из баланса (override) для сверки
        "pnl_rub": float, "xirr_frac": float (доля годовых, 0.2337) | None,
        "cashflows": [(date_iso, amount_rub), ...],
        # Свёртка окна [as_of − recent_window_days; as_of] (обе границы
        # включительно) — ТОЛЬКО Покупка/Продажа, см. _compute_recent_window.
        "recent_window_days": int,
        "recent_net_rub": float,     # покупки минус продажи в окне, знак сохранён
        "recent_n_buys": int, "recent_n_sells": int,
        "recent_last_trade_date": ISO | None,
        "recent_round_trip": bool,   # были и покупки, и продажи в окне
      }}
      Если тикер не найден в trades — {"error": "no trades found"}.
    """
    market_values_override = market_values_override or {}

    # 1. Парсинг сделок
    trades = parse_trades(trades_path)
    if verbose:
        print(f"[parse] {len(trades)} сделок", file=sys.stderr)

    # 2. Корректировки (TMF forced close и т.п.)
    trades, _ = apply_corrections(trades)

    # 3. RUB-конвертация (ЦБ РФ курсы на дату сделки)
    trades = convert_trades_to_rub(trades, verbose=verbose, cbr_offline=cbr_offline)

    # 4. Позиции на as_of — reconstruct_positions ВНУТРИ СЕБЯ вызывает
    #    merge_cross_currency_positions и сплиты (split_factor), повторно НЕ вызываем
    positions = reconstruct_positions(trades, as_of)

    # 5. MOEX ISS — batch по нужным тикерам (если use_moex и нет override)
    target_tickers = set(tickers)
    moex_last_prices: dict[str, float] = {}
    moex_face_values: dict[str, float] = {}
    moex_face_currencies: dict[str, str] = {}
    moex_accrued: dict[str, float] = {}
    if use_moex:
        secids = [
            tk for (tk, _cur), p in positions.items()
            if tk in target_tickers
            and p.qty > 1e-9
        ]
        if secids and quotes:
            moex_last_prices, moex_face_values, moex_face_currencies, _failed = \
                moex_prices_from_quotes(quotes, secids, accrued_out=moex_accrued)
            secids = [s_ for s_ in secids if s_ in _failed]
        if secids:
            _lp, _fv, _fc, _failed = \
                fetch_moex_prices(secids, verbose=verbose, accrued_out=moex_accrued)
            moex_last_prices.update(_lp)
            moex_face_values.update(_fv)
            moex_face_currencies.update(_fc)
            if verbose:
                print(
                    f"[moex] last={len(moex_last_prices)} "
                    f"face={len(moex_face_values)}",
                    file=sys.stderr,
                )

    # 6. Группировка сделок по (ticker, name_prefix(8)) — симметрично
    # merge_cross_currency_positions. Это разделяет омонимы под одним тикером
    # (T = AT&T USD + Т-Техно RUB) и одновременно объединяет один инструмент
    # в разных валютах сделок (TGLD: USD-покупки и RUB-продажи в один поток).
    def _instr_key(tr):
        return (tr.ticker, (tr.name or "").strip().lower()[:8])

    trades_by_instr: dict[tuple[str, str], list] = defaultdict(list)
    for t in trades:
        if t.ticker.startswith("Деньги"):
            continue
        trades_by_instr[_instr_key(t)].append(t)

    # Индекс позиций по тикеру → список (pos_key, pos, name_prefix).
    positions_by_ticker: dict[str, list] = defaultdict(list)
    for (tk, cur), p in positions.items():
        np = (p.name or "").strip().lower()[:8]
        positions_by_ticker[tk].append(((tk, cur), p, np))

    cur_priority = {"RUB": 0, "USD": 1, "EUR": 2, "CNY": 3}

    # 7. Расчёт по каждому тикеру
    cbr_cache = load_cbr_cache()
    results: dict[str, dict] = {}

    for ticker in tickers:
        # Выбор «основного» инструмента под тикером:
        #   1. Активная позиция (qty>0) предпочтительнее закрытой.
        #   2. Среди активных — каноническая валюта (RUB > USD > EUR > CNY).
        # Если активных нет — берём первую по той же priority. Если позиций
        # нет вообще — пытаемся найти любые сделки и считаем как закрытую.
        candidates = positions_by_ticker.get(ticker, [])
        active = [c for c in candidates if c[1].qty > 1e-9]
        pool = active if active else candidates
        if pool:
            pool_sorted = sorted(
                pool, key=lambda c: cur_priority.get(c[0][1], 10),
            )
            pos_key, primary_pos, instr_name_prefix = pool_sorted[0]
            ticker_trades = trades_by_instr.get(
                (ticker, instr_name_prefix), []
            )
        else:
            pos_key = None
            primary_pos = None
            instr_name_prefix = None
            # Закрытая или вообще без позиции — собираем все сделки тикера
            ticker_trades = [
                t for t in trades
                if t.ticker == ticker and not t.ticker.startswith("Деньги")
            ]

        if not ticker_trades:
            results[ticker] = {"error": "no trades found", "ticker": ticker}
            continue

        inst_type = classify_instrument_type(ticker_trades)

        # Cashflows из сделок — сливаются по всем валютам под тикером (RUB-суммы)
        cfs: list[tuple[dt.date, float]] = []
        buy_total = sell_total = coupons = divs = amorts = 0.0
        corr_buy = corr_sell = 0.0
        n_buys = n_sells = n_coupons = n_divs = n_amorts = n_corrections = 0

        for t in ticker_trades:
            if t.date > as_of:
                continue
            amt = abs(t.rub_amount)
            if t.operation == "Покупка":
                cfs.append((t.date, -amt)); buy_total += amt; n_buys += 1
            elif t.operation == "Продажа":
                cfs.append((t.date, +amt)); sell_total += amt; n_sells += 1
            elif t.operation == "Купон":
                cfs.append((t.date, +amt)); coupons += amt; n_coupons += 1
            elif t.operation == "Дивиденд":
                cfs.append((t.date, +amt)); divs += amt; n_divs += 1
            elif t.operation == "Амортизация":
                cfs.append((t.date, +amt)); amorts += amt; n_amorts += 1
            elif t.operation == "Корректировка":
                # IntelInvest синхронизирует позиции с отчётом брокера.
                # reconstruct_positions трактует Корректировку как синтетический
                # cash flow (amt>0 → quasi-buy, amt<0 → quasi-sell), меняя qty
                # и cost basis. XIRR должен учитывать ту же логику, иначе
                # terminal-MV рассчитан на одной qty, а cashflow-стрим — на другой,
                # и XIRR взрывается (см. кейс MDMG: −99% vs реальные +17%).
                amt_signed = t.rub_amount or 0.0
                if amt_signed > 0:
                    cfs.append((t.date, -amt)); corr_buy += amt; n_corrections += 1
                elif amt_signed < 0:
                    cfs.append((t.date, +amt)); corr_sell += amt; n_corrections += 1
                # amt == 0 — чисто информационная, не трогаем

        # Терминал: либо override, либо MOEX/last_trade/cost, либо 0 (закрыта).
        # Позиция уже выбрана выше (primary_pos) — post-split, post-merge.
        has_moex_quote = (
            primary_pos is not None and primary_pos.qty > 1e-9
            and moex_last_prices.get(ticker) is not None
        )
        if ticker in market_values_override and not has_moex_quote:
            qty_now = primary_pos.qty if primary_pos else 0.0
            market_value = float(market_values_override[ticker])
            price_source = "override"
        elif primary_pos is None or primary_pos.qty <= 1e-9:
            qty_now = 0.0
            market_value = 0.0
            price_source = "closed"
        else:
            pos = primary_pos
            qty_now = pos.qty
            moex_last = moex_last_prices.get(ticker)
            moex_face = moex_face_values.get(ticker)
            nominal_curr = moex_face_currencies.get(ticker)
            # last_known_trade_price теперь split-adjusts цену для RUB-сделок
            # (Т-Техно после 1:10 сплита 17.04.2026: 3342.80 → 334.28).
            last_trade = last_known_trade_price(
                pos.ticker, pos.currency, ticker_trades, as_of,
            )
            market_value, price_source = estimate_position_value_rub(
                pos, inst_type, last_trade, moex_last, moex_face,
                nominal_curr, as_of, cbr_cache,
                moex_accrued=(moex_accrued.get(ticker)
                              if inst_type == "bond" else None),
            )

        if market_value > 0:
            cfs.append((as_of, +market_value))
        cfs.sort(key=lambda x: x[0])

        # XIRR
        try:
            rate = xirr(cfs)
        except Exception as e:
            rate = None
            if verbose:
                print(f"[xirr] {ticker}: {e}", file=sys.stderr)

        # PnL: сумма всех притоков (с учётом терминала и Korrektirovka-как-sell)
        # минус все оттоки (включая Korrektirovka-как-buy).
        pnl_rub = (
            sell_total + coupons + divs + amorts + corr_sell + market_value
        ) - (buy_total + corr_buy)

        recent = _compute_recent_window(ticker_trades, as_of, recent_window_days)
        # дата закрытия позиции: последняя продажа (погашение облигации в выгрузке — тоже «Продажа») или
        # корректировка в минус; name — по последней сделке с названием
        sell_dates = [t.date for t in ticker_trades if t.date <= as_of and (
            t.operation == "Продажа" or (t.operation == "Корректировка" and (t.rub_amount or 0.0) < 0))]
        last_name = next((t.name for t in sorted(ticker_trades, key=lambda x: x.date, reverse=True)
                          if (t.name or "").strip()), None)

        results[ticker] = {
            "ticker": ticker,
            "inst_type": inst_type,
            "qty_now": qty_now,
            "first_trade_date": min(t.date for t in ticker_trades).isoformat(),
            "last_trade_date": max(t.date for t in ticker_trades).isoformat(),
            "last_sell_date": max(sell_dates).isoformat() if sell_dates else None,
            "name": last_name,
            "n_buys": n_buys, "n_sells": n_sells,
            "n_coupons": n_coupons, "n_divs": n_divs, "n_amorts": n_amorts,
            "n_corrections": n_corrections,
            "n_cashflows": len(cfs),
            "buy_total_rub": round(buy_total, 2),
            "sell_total_rub": round(sell_total, 2),
            "coupons_rub": round(coupons, 2),
            "dividends_rub": round(divs, 2),
            "amortization_rub": round(amorts, 2),
            "corr_buy_rub": round(corr_buy, 2),
            "corr_sell_rub": round(corr_sell, 2),
            "market_value_rub": round(market_value, 2),
            "price_source": price_source,
            "balance_value_rub": (
                round(float(market_values_override[ticker]), 2)
                if ticker in market_values_override else None
            ),
            "pnl_rub": round(pnl_rub, 2),
            "xirr_frac": round(rate, 4) if rate is not None else None,
            "cashflows": [(d.isoformat(), round(amt, 2)) for d, amt in cfs],
            **recent,
        }

    return results


# =============================================================================
# Вспомогательные утилиты для CLI
# =============================================================================


def _market_values_from_portfolio_json(path: str, tickers: set[str]) -> dict[str, float]:
    """Рыночная стоимость из portfolio.json (выход parse_portfolio.py).

    Берёт stocks[].Стоимость и bonds[].Текущая стоимость — это текущая стоимость
    из «Общий баланс.numbers», когда отдельного common_portfolio_*.xlsx нет.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    result: dict[str, float] = {}
    for s in data.get("stocks", []):
        t, v = s.get("Тикер"), s.get("Стоимость")
        if t in tickers and isinstance(v, (int, float)):
            result[str(t)] = float(v)
    for b in data.get("bonds", []):
        t, v = b.get("Тикер"), b.get("Текущая стоимость")
        if t in tickers and isinstance(v, (int, float)):
            result[str(t)] = float(v)
    return result


def load_market_values_from_common(path: str, tickers: set[str]) -> dict[str, float]:
    """
    Возвращает {ticker: текущая рыночная стоимость в RUB} для честной сверки с
    IntelInvest (та же точка price-fix). Поддерживает два формата:
      • common_portfolio_*.xlsx (экспорт IntelInvest): тикер = колонка B, стоимость = колонка I;
      • portfolio.json (выход parse_portfolio.py из «Общий баланс.numbers»).
    """
    if path.lower().endswith(".json"):
        return _market_values_from_portfolio_json(path, tickers)
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True)
    ws = wb.active
    result: dict[str, float] = {}
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i < 2:
            continue
        if not row or len(row) < 9:
            continue
        ticker = row[1]
        if not ticker or ticker not in tickers:
            continue
        value = row[8]  # "Текущая стоимость"
        if isinstance(value, (int, float)):
            result[str(ticker)] = float(value)
    return result


def render_text_report(results: dict[str, dict]) -> str:
    """Человекочитаемый отчёт для CLI."""
    lines = []
    header = (
        f"{'TICKER':<14} {'TYPE':<6} {'QTY':>10} {'BUY ₽':>12} {'SELL ₽':>12} "
        f"{'CPN+DIV ₽':>12} {'MV ₽':>12} {'PnL ₽':>12} {'XIRR %':>8}"
    )
    lines.append(header)
    lines.append("─" * len(header))
    for ticker, r in results.items():
        if "error" in r:
            lines.append(f"{ticker:<14} {'[ERROR]'} {r['error']}")
            continue
        xirr_s = f"{r['xirr_frac'] * 100:.2f}" if r.get('xirr_frac') is not None else "—"
        cpn_div = r['coupons_rub'] + r['dividends_rub'] + r['amortization_rub']
        lines.append(
            f"{ticker:<14} {r['inst_type'][:5]:<6} {r['qty_now']:>10,.2f} "
            f"{r['buy_total_rub']:>12,.0f} {r['sell_total_rub']:>12,.0f} "
            f"{cpn_div:>12,.0f} {r['market_value_rub']:>12,.0f} "
            f"{r['pnl_rub']:>12,.0f} {xirr_s:>8}"
        )
    return "\n".join(lines)


# =============================================================================
# CLI
# =============================================================================


def main():
    ap = argparse.ArgumentParser(
        description="XIRR и метрики доходности отдельной бумаги (или нескольких)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "--trades", required=True,
        help="путь к trades_portfolio_*.xlsx из IntelInvest",
    )
    ap.add_argument(
        "--tickers", required=True,
        help="тикеры через запятую (например 'TGLD,PLZL,SU26243RMFS4')",
    )
    ap.add_argument(
        "--as-of", default=dt.date.today().isoformat(),
        help="дата расчёта (YYYY-MM-DD), по умолчанию сегодня",
    )
    ap.add_argument(
        "--common", default=None,
        help="опционально: common_portfolio_*.xlsx ИЛИ portfolio.json (выход "
             "parse_portfolio.py) — ЗАПАСНАЯ оценка (MOEX first: при наличии "
             "котировки MOEX стоимость = qty×MOEX, баланс идёт в balance_value_rub "
             "для сверки)",
    )
    ap.add_argument("--quotes", default=None,
                    help="quotes.json (moex_quotes.py --json; допускается и голый словарь "
                         "secid → котировка): цены оттуда, MOEX ISS — только за бумагами "
                         "вне файла. С --no-moex игнорируется")
    ap.add_argument("--no-moex", action="store_true",
                    help="не ходить в MOEX ISS (только last_trade_price fallback)")
    ap.add_argument("--cbr-offline", action="store_true",
                    help="не ходить в ЦБ РФ (только bundled+/tmp кэш)")
    ap.add_argument(
        "--recent-window-days", type=int, default=60,
        help="ширина окна свёртки недавних buy/sell-сделок (recent_* поля), "
             "по умолчанию 60 дней",
    )
    ap.add_argument("--types-cache", default=None, metavar="PATH",
                    help="справочник типов Portfolio/security-types.json (тип с Мосбиржи "
                         "перебивает эвристику); нет файла — без переопределений")
    ap.add_argument("--splits-file", default=None, metavar="PATH",
                    help="реестр сплитов Portfolio/known-splits.json (дополняет встроенный набор)")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    ap.add_argument("--no-cashflows", action="store_true",
                    help="JSON: убрать cashflows из ответа (компактнее)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    load_types_cache(args.types_cache)
    pr_load_known_splits(args.splits_file)

    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    as_of = dt.date.fromisoformat(args.as_of)

    mv_override: dict[str, float] = {}
    if args.common:
        mv_override = load_market_values_from_common(args.common, set(tickers))
        if args.verbose:
            print(
                f"[common] market values override для {len(mv_override)}/{len(tickers)} тикеров",
                file=sys.stderr,
            )

    quotes = None
    if args.quotes:
        qd = json.loads(Path(args.quotes).read_text(encoding="utf-8"))
        quotes = qd.get("quotes") if isinstance(qd, dict) and isinstance(qd.get("quotes"), dict) else qd

    results = per_security_xirr(
        tickers=tickers,
        trades_path=args.trades,
        as_of=as_of,
        use_moex=not args.no_moex,
        verbose=args.verbose,
        market_values_override=mv_override,
        cbr_offline=args.cbr_offline,
        recent_window_days=args.recent_window_days,
        quotes=quotes,
    )

    if args.format == "text":
        print(render_text_report(results))
    else:
        if args.no_cashflows:
            for v in results.values():
                v.pop("cashflows", None)
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
