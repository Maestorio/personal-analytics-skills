#!/usr/bin/env python3
"""
Генератор shortlist облигаций для докупки на ИИС-3 (long-only buy advice).

Использование:
    python3 iis_shortlist.py --snapshot Portfolio/snapshots/portfolio-2026-06-28.json --deposit 50000
    python3 iis_shortlist.py --snapshot portfolio-2026-06-28.json --deposit 100000 --json

Загрузка файлов — зона portfolio-data-loader. Этот скрипт читает уже готовый
снапшот portfolio-{date}.json (schema v2). Если снапшота за сегодня нет —
сначала сгенерируй его через скилл portfolio-data-loader.

Что делает:
  1. Читает текущие позиции ИИС-3 из снапшота (holdings c account=iis_3 +
     balance_summary.by_account.iis_3).
  2. Подтягивает свежие цены, YTM, дюрацию с MOEX ISS для:
     - Текущих бумаг на ИИС-3 (для докупки до круглого числа)
     - Shortlist длинных ОФЗ (матуритет 2034+)
     - Shortlist длинных AAA-корпоратов (5+ лет)
     - Фондов облигаций (SBGB, OBLG, TPAY, AKMB, LQDT, SBCB, SBRB)
  3. Для каждой бумаги считает:
     - сколько лотов можно купить на deposit
     - остаток денег после покупки
     - текущая цена лота (для бондов — с учётом NKD)
     - текущая доля этой бумаги в ИИС-3 (до и после покупки)

Выходной JSON — база для модели, которая добавляет макро-контекст и
формирует конкретную рекомендацию.

ВАЖНО: скрипт не даёт финальную рекомендацию — только цифры. Модель сама
решает, что докупать, в зависимости от макроконтекста (ставка ЦБ, инфляция,
санкционный риск).

Зависимости: moex_quotes.py (из того же каталога). Парсинг исходных файлов
не нужен — состояние ИИС-3 берётся из снапшота portfolio-data-loader.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent


# =============================================================================
# Кураторский shortlist — обновляется при релизах скилла
# =============================================================================
# ВАЖНО для модели: shortlist — это проверенный список тикеров, которые точно
# торгуются на MOEX и имеют данные для анализа. НЕ финальная рекомендация.
# Модель должна сверить YTM/дюрацию/рейтинг с актуальными раскрытиями и
# брокерскими обзорами перед выдачей рекомендации пользователю.

# Длинные ОФЗ с матуритетом 2034+ (для долгосрочного ИИС-3).
# Отобраны по критериям: ликвидность на MOEX (объём >1 млрд ₽/день),
# дюрация ≥5 лет, фиксированный купон (не флоатеры). Цены — в % от номинала.
# Соответствие плановой корзине (bond-subtypes-plan.md §4): «длинные ОФЗ 2034+»
# из этого shortlist — это подтип `>10` (`plan_bucket_key = "ОФЗ/>10"`) в
# `holdings[]`/`balance_summary.bonds_plan_vs_fact` снапшота data-loader. Ось
# подтипа — текущий срок до погашения, не срок при выпуске, поэтому список
# может периодически требовать пересмотра по мере приближения матуритета
# к 10-летней границе; сам список ниже курируется вручную, не из плана.
SHORTLIST_OFZ_LONG = [
    "SU26238RMFS4",  # ОФЗ 26238, погашение 2041-05-15, купон 7.10%
    "SU26244RMFS2",  # ОФЗ 26244, погашение 2034-03-15, купон 11.25%
    "SU26247RMFS5",  # ОФЗ 26247, погашение 2039-05-11, купон 12.25%
    "SU26248RMFS3",  # ОФЗ 26248, погашение 2040-05-16, купон 12.25%
    "SU26230RMFS1",  # ОФЗ 26230, погашение 2039-03-16, купон 7.70%
    "SU26253RMFS3",  # ОФЗ 26253, погашение 2038-10-06, купон 13.00%
]

# Ликвидные корпоративные облигации 1-го эшелона (рейтинг AAA/AA+ от АКРА/ЭРА).
# ВАЖНО: по оценке БКС (октябрь 2025) длинных AAA корпоратов со сроком >5 лет
# практически нет — рынок их пересчитал, и спред к ОФЗ минимален. Этот список —
# средне-длинные (1.5–3 года) с высоким YTM, полезны для дополнительной
# диверсификации, но НЕ как полная замена ОФЗ для долгого ИИС-3.
# Модель: перед рекомендацией — перепроверить текущий рейтинг через АКРА / Эксперт РА.
SHORTLIST_CORP_AAA_MID = [
    "RU000A10D3C0",  # РусГидро БО-002Р-08, AAA, дюрация ~2.4 года (на 10.2025)
    "RU000A108L81",  # Полюс ПБО-04, AAA
    "RU000A1068R1",  # РСХБ БО-02-002Р, AAA
]

# БПИФ на облигации — альтернатива прямым бумагам для пассивного ИИС-3.
# SBLB — отдельно выделен как самый близкий к long-only ОФЗ 5+ лет.
SHORTLIST_BOND_FUNDS = [
    "SBLB",    # Сбер — Долгосрочные гособлигации (RUGBITR5+), TER ~0.90%
    "SBGB",    # Сбер — Государственные облигации (ОФЗ ETF), TER ~0.80%
    "OBLG",    # Доходъ — Индекс корп. облигаций МосБиржи, TER ~0.95%
    "TPAY",    # Т-Капитал — дивидендные/пассив (квазибонды)
    "AKMB",    # Альфа-Капитал Управляемые облигации, TER ~0.85%
    "SBRB",    # Сбер — Индекс корпоративных рублёвых облигаций
    "SBCB",    # Сбер — Корп. облигации в CNY (валютная диверсификация)
    "LQDT",    # ВИМ Ликвидность — денежный рынок / РЕПО (кэш-замена)
    "AKMM",    # Альфа-Капитал Денежный рынок
]


# =============================================================================
# Загрузка текущего состояния ИИС-3
# =============================================================================

def _is_iis_account(holding: dict[str, Any]) -> bool:
    return str(holding.get("account", "")).lower().replace("-", "_") in ("iis3", "iis_3")


def _bond_type(holding: dict[str, Any]) -> str | None:
    """Best-effort тип облигации из снапшота (в нём нет колонки «Тип»)."""
    name = str(holding.get("name") or "").upper()
    return "ОФЗ" if "ОФЗ" in name else "КОРП"


def load_iis_state(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Извлекает состояние ИИС-3 из снапшота portfolio-{date}.json (schema v2).

    Загрузка исходных файлов — зона portfolio-data-loader; ИИС-3 Buy Advice
    читает готовый снапшот: облигации/фонды с account=iis_3 в holdings и
    агрегаты из balance_summary.by_account.iis_3.
    """
    bs = snapshot.get("balance_summary", {}) or {}
    iis_acc = (bs.get("by_account", {}) or {}).get("iis_3", {}) or {}
    holdings = snapshot.get("holdings", []) or []

    # main-позиции по тикеру — чтобы восстановить qty_total / value_main_rub
    # для бумаг, разделённых между основным счётом и ИИС-3 (IIS-split).
    main_by_ticker: dict[str, dict[str, Any]] = {}
    for h in holdings:
        if not _is_iis_account(h):
            main_by_ticker.setdefault(h.get("ticker"), h)

    iis_bonds: list[dict[str, Any]] = []
    iis_other: list[dict[str, Any]] = []
    for h in holdings:
        if not _is_iis_account(h):
            continue
        ticker = h.get("ticker")
        if h.get("asset_type") == "bond":
            main = main_by_ticker.get(ticker)
            qty_iis = h.get("qty")
            qty_main = main.get("qty") if main else None
            qty_total = None
            if qty_iis is not None or qty_main is not None:
                qty_total = (qty_iis or 0) + (qty_main or 0)
            iis_bonds.append({
                "ticker": ticker,
                "name": h.get("name"),
                "type": _bond_type(h),
                "qty_iis": qty_iis,
                "qty_total": qty_total,
                "value_iis_rub": h.get("value_rub"),
                "value_main_rub": main.get("value_rub") if main else None,
            })
        else:
            iis_other.append({
                "ticker": ticker,
                "type": h.get("asset_type"),
                "value_rub": h.get("value_rub"),
            })

    return {
        "iis_balance_rub": bs.get("iis_balance_rub") or iis_acc.get("total_rub"),
        "total_current_rub_excl_iis": bs.get("total_current_rub_excl_iis"),
        "total_current_rub_incl_iis": bs.get("total_current_rub_incl_iis"),
        "total_bonds_iis_rub": iis_acc.get("bonds_rub"),
        "iis_bonds": iis_bonds,
        "iis_other": iis_other,
    }


# =============================================================================
# Получение данных с MOEX ISS
# =============================================================================

def fetch_moex_data(tickers: list[str]) -> dict[str, dict]:
    """
    Вызывает moex_quotes.py --fields full для списка тикеров и возвращает
    результат в виде {ticker: {...}}.

    Формат ответа moex_quotes.py:
      {"quotes": {ticker: {secid, kind, last, ytm_pct, duration_days,
                           accrued_interest, face_value, maturity_date, ...}}}
    """
    # Бандл: канон лежит в scripts/ (pack.sh, bundle_scripts); репо: _shared-references/.
    candidates = [SCRIPT_DIR / "moex_quotes.py",
                  SCRIPT_DIR.parents[2] / "_shared-references" / "moex_quotes.py"]
    moex_script = next((p for p in candidates if p.exists()), None)
    if moex_script is None:
        raise FileNotFoundError(f"moex_quotes.py not found: {', '.join(map(str, candidates))}")

    cmd = [
        sys.executable, str(moex_script),
        "--fields", "full",
        "--json",
        *tickers,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        sys.stderr.write("[moex] timeout after 60s\n")
        return {}

    # moex_quotes.py возвращает exit=1 если есть хоть одна ошибка по тикеру,
    # но основной ответ в stdout всё равно валидный JSON. Не полагаемся на
    # returncode — парсим stdout безусловно.
    if not result.stdout:
        sys.stderr.write(f"[moex] empty stdout (exit={result.returncode}): {result.stderr[:500]}\n")
        return {}

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"[moex] bad JSON: {e}\n{result.stdout[:500]}\n")
        return {}

    quotes = data.get("quotes", {}) if isinstance(data, dict) else {}
    # quotes — это dict {ticker: {...}}
    if isinstance(quotes, dict):
        return quotes
    return {}


# =============================================================================
# Расчёт "сколько можно купить"
# =============================================================================

def compute_lot_estimation(
    moex_data: dict,
    deposit_rub: float,
    is_bond: bool | None = None,
) -> dict:
    """
    Для одной бумаги считает, сколько лотов можно купить на deposit_rub.

    Возвращает: {cost_per_lot, max_lots, spent, remainder, ytm_pct, duration}.
    Если данных недостаточно — возвращает частичный dict с флагом 'incomplete'.

    Ожидаемые поля moex_data (формат из moex_quotes.py):
      secid, kind, last, ytm_pct, duration_days, accrued_interest,
      face_value, maturity_date, short_name, currency, coupon_pct.
    """
    ticker = moex_data.get("secid") or moex_data.get("ticker")
    kind = moex_data.get("kind")  # 'bond' | 'share' | 'etf'
    last = moex_data.get("last") or moex_data.get("price")
    face = moex_data.get("face_value") or moex_data.get("facevalue") or 1000.0
    nkd = moex_data.get("accrued_interest") or moex_data.get("nkd") or 0.0
    # Для фондов/акций на MOEX лот обычно = 1, для бондов = 1
    lot_size = moex_data.get("lotsize") or moex_data.get("lot") or 1
    ytm_pct = moex_data.get("ytm_pct")
    duration_days = moex_data.get("duration_days")
    duration_years = (duration_days / 365.25) if duration_days else None
    matdate = moex_data.get("maturity_date") or moex_data.get("matdate")
    short_name = moex_data.get("short_name") or moex_data.get("shortname")
    faceunit = moex_data.get("currency") or moex_data.get("faceunit")
    coupon_pct = moex_data.get("coupon_pct")

    if is_bond is None:
        is_bond = (kind == "bond")

    result = {
        "ticker": ticker,
        "short_name": short_name,
        "kind": kind,
        "is_bond": is_bond,
        "matdate": matdate,
        "faceunit": faceunit,
        "ytm_pct": ytm_pct,
        "duration_years": round(duration_years, 2) if duration_years else None,
        "coupon_pct": coupon_pct,
        "lot_size": lot_size,
        "last_price": last,
    }

    if not last:
        result["incomplete"] = "no_last_price"
        return result

    if is_bond:
        # Цена бумаги в рублях = last (% от face) + NKD
        cost_per_unit = last * face / 100.0 + (nkd or 0)
    else:
        cost_per_unit = last

    cost_per_lot = cost_per_unit * lot_size
    result["cost_per_lot_rub"] = round(cost_per_lot, 2)

    if cost_per_lot > 0:
        max_lots = int(deposit_rub // cost_per_lot)
        spent = max_lots * cost_per_lot
        remainder = deposit_rub - spent
        result["max_lots_on_deposit"] = max_lots
        result["spent_rub"] = round(spent, 2)
        result["remainder_rub"] = round(remainder, 2)
    else:
        result["incomplete"] = "zero_cost"

    return result


# =============================================================================
# Main
# =============================================================================

def build_shortlist(
    snapshot: dict[str, Any],
    deposit_rub: float,
    verbose: bool = False,
) -> dict:
    """
    Собирает полный отчёт: текущее состояние ИИС-3 + оценка каждой
    бумаги-кандидата для покупки на заданную сумму.
    """
    iis_state = load_iis_state(snapshot)

    # Собираем список тикеров для MOEX-запроса
    tickers = set()
    # 1. Текущие позиции ИИС-3 (для докупки)
    for b in iis_state["iis_bonds"]:
        if b["ticker"]:
            tickers.add(b["ticker"])
    for p in iis_state["iis_other"]:
        if p["ticker"]:
            tickers.add(p["ticker"])
    # 2. Shortlist кандидатов
    tickers.update(SHORTLIST_OFZ_LONG)
    tickers.update(SHORTLIST_CORP_AAA_MID)
    tickers.update(SHORTLIST_BOND_FUNDS)

    if verbose:
        sys.stderr.write(f"[iis] Запрашиваю MOEX для {len(tickers)} тикеров...\n")

    moex_data = fetch_moex_data(sorted(tickers))

    # Сохраняем тикеры, для которых MOEX вернул пусто — модель должна знать
    missing = sorted(t for t in tickers if t not in moex_data)

    # Оцениваем каждую бумагу
    def evaluate_category(tks, category_name, is_bond_hint=None):
        out = []
        for tk in tks:
            if tk not in moex_data:
                continue
            est = compute_lot_estimation(moex_data[tk], deposit_rub, is_bond_hint)
            est["category"] = category_name
            out.append(est)
        return out

    # Текущие позиции ИИС-3 — для докупки
    current_iis_tickers = {b["ticker"] for b in iis_state["iis_bonds"] if b["ticker"]}
    current_iis_tickers.update(p["ticker"] for p in iis_state["iis_other"] if p["ticker"])

    current_positions_for_buy = []
    for tk in sorted(current_iis_tickers):
        if tk in moex_data:
            est = compute_lot_estimation(moex_data[tk], deposit_rub)
            est["category"] = "current_iis_position"
            # Добавляем информацию о текущей позиции
            for b in iis_state["iis_bonds"]:
                if b["ticker"] == tk:
                    est["current_qty_on_iis"] = b["qty_iis"]
                    est["current_value_iis_rub"] = b["value_iis_rub"]
                    break
            for p in iis_state["iis_other"]:
                if p["ticker"] == tk:
                    est["current_value_iis_rub"] = p["value_rub"]
                    break
            current_positions_for_buy.append(est)

    # Ранжируем по YTM (убывание) — для удобства модели
    def sort_by_ytm(items):
        return sorted(
            items,
            key=lambda x: (x.get("ytm_pct") or -1),
            reverse=True,
        )

    return {
        "parameters": {
            "snapshot_date": snapshot.get("as_of_date"),
            "deposit_rub": deposit_rub,
        },
        "iis_state": iis_state,
        "moex_missing_tickers": missing,
        "shortlist": {
            "docupka_to_existing": sort_by_ytm(current_positions_for_buy),
            "ofz_long": sort_by_ytm(
                evaluate_category(SHORTLIST_OFZ_LONG, "ofz_long", is_bond_hint=True)
            ),
            "corp_aaa_mid": sort_by_ytm(
                evaluate_category(SHORTLIST_CORP_AAA_MID, "corp_aaa_mid", is_bond_hint=True)
            ),
            "bond_funds": evaluate_category(
                SHORTLIST_BOND_FUNDS, "bond_fund", is_bond_hint=False
            ),
        },
        "notes": [
            "Данные YTM/duration — с MOEX ISS на момент запроса. Могут отличаться "
            "от брокерских на 0.1–0.5 п.п. из-за разной методологии (бид/офер/вапс).",
            "ВАЖНО: длинных (5+ лет) AAA-корпоратов на рынке РФ практически нет — "
            "рынок их пересчитал, спред к ОФЗ минимален. Для ленивого ИИС-3 длинные "
            "ОФЗ + SBLB/SBGB обычно логичнее, чем корпораты.",
            "corp_aaa_mid — это средне-длинные (1.5–3 года) ликвидные бумаги 1-го "
            "эшелона. Подходят для добавки доходности на часть капитала с низким "
            "дюрационным риском, но не заменят длинные ОФЗ для долгого ИИС-3.",
            "Модель должна перепроверить кредитные рейтинги AAA-корпоратов по актуальным "
            "раскрытиям АКРА/Эксперт РА перед рекомендацией — рейтинг может быть "
            "понижен между релизами скилла.",
            "Пользователь держит ИИС-3 пассивно — продажи не рассматриваются. "
            "Только докупка или новые покупки. При выборе приоритет — матуритет "
            "за пределами закрытия ИИС (3+ года от даты открытия) и надёжность.",
            "Shortlist — это кандидаты, не финальный портфель. Модель выбирает "
            "бумаги с учётом макроконтекста (ставка ЦБ, инфляция, цикл смягчения/"
            "ужесточения, санкционный риск для конкретных эмитентов).",
        ],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Shortlist облигаций для пассивного докупания на ИИС-3."
    )
    parser.add_argument(
        "--snapshot", required=True,
        help="Путь к снапшоту portfolio-{date}.json (от portfolio-data-loader)",
    )
    parser.add_argument(
        "--deposit", type=float, required=True,
        help="Сумма пополнения ИИС-3 в рублях",
    )
    parser.add_argument(
        "--json", dest="output_json", action="store_true",
        help="Вывести JSON (по умолчанию — текст)",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not os.path.exists(args.snapshot):
        parser.error(f"Снапшот не найден: {args.snapshot}. "
                     f"Сгенерируй его через portfolio-data-loader.")
    try:
        with open(args.snapshot, encoding="utf-8") as f:
            snapshot = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        parser.error(f"Не удалось прочитать снапшот {args.snapshot}: {e}")

    sv = str(snapshot.get("schema_version", "1.0"))
    if sv < "2.0":
        parser.error(f"Снапшот schema_version={sv!r}; нужен v2.0+. "
                     f"Перегенерируй через portfolio-data-loader.")

    report = build_shortlist(snapshot, args.deposit, verbose=args.verbose)

    if args.output_json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        # Текстовый краткий отчёт
        s = report["iis_state"]
        print(f"=== ИИС-3: текущее состояние ===")
        print(f"  Всего на ИИС-3: {s['iis_balance_rub']:,.0f} ₽")
        print(f"  Из них облигации: {s['total_bonds_iis_rub']:,.0f} ₽")
        print(f"  Позиций: {len(s['iis_bonds'])} облигаций + {len(s['iis_other'])} фондов/другое")
        print()
        print(f"=== Пополнение: {args.deposit:,.0f} ₽ ===")
        print()
        for cat, items in report["shortlist"].items():
            print(f"-- {cat} --")
            for it in items:
                ytm = it.get("ytm_pct")
                ytm_s = f"{ytm:.2f}%" if ytm else "N/A"
                dur = it.get("duration_years")
                dur_s = f"{dur:.1f}y" if dur else "?"
                cost = it.get("cost_per_lot_rub")
                lots = it.get("max_lots_on_deposit")
                rem = it.get("remainder_rub")
                if cost and lots is not None:
                    print(f"  {it['ticker']:16s} YTM={ytm_s:7s} dur={dur_s:6s} "
                          f"lot={cost:>9,.0f}₽ max={lots:3d} шт, ост={rem:>9,.0f}₽")
                else:
                    print(f"  {it['ticker']:16s} (нет данных: {it.get('incomplete','?')})")
            print()

        if report["moex_missing_tickers"]:
            print(f"⚠ MOEX не вернул данные для: {', '.join(report['moex_missing_tickers'])}")


if __name__ == "__main__":
    main()
