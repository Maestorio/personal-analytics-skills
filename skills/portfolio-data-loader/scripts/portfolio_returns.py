#!/usr/bin/env python3
"""
Portfolio Returns — анализатор доходности российского портфеля.

Считает XIRR / ROI / CAGR / TWR (Modified Dietz) по истории сделок из IntelInvest
(trades.xlsx) и текущему срезу портфеля (common.xlsx).

Ключевые особенности:
1. Корректно обрабатывает блокировку иностранных бумаг (февраль 2022): умеет
   выдать два набора метрик — общий (вся история) и "с 01.03.2022 без
   заблокированных". Первый показывает реальный финансовый результат
   (с учётом "мёртвого" капитала), второй — эффективность управления
   российской частью.

2. Конвертирует USD/EUR/CNY операции в RUB по курсу ЦБ РФ на дату сделки
   (с кэшированием).

3. Ведёт учёт позиций по паре (ticker, currency), что позволяет отличить
   омонимичные тикеры: "T" = Т-Технологии (RUB) и "T" = AT&T (USD) —
   разные бумаги с одинаковым тикером.

4. Корректирует ошибку в данных по TMF: виртуальная продажа остатка
   5 августа 2024 (реальная позиция закрыта в этот день).

5. Разделяет cashflows на external (депозиты/выводы) и internal
   (покупки/продажи/купоны/дивиденды/комиссии) через инвариант
   "наблюдаемое изменение cash = сумма внутренних операций + external".

Зависимости: openpyxl + stdlib.

CLI:
    python3 portfolio_returns.py \\
        --current /path/to/common.xlsx \\
        --trades  /path/to/trades.xlsx \\
        --output  /tmp/returns.json \\
        --format  json

    python3 portfolio_returns.py \\
        --current common.xlsx --trades trades.xlsx \\
        --format text                                   # человекочитаемый отчёт

    python3 portfolio_returns.py \\
        --current common.xlsx --trades trades.xlsx \\
        --snapshot 2022-03-01                           # только срез на дату

    python3 portfolio_returns.py --clear-cache          # сбросить кэш ЦБ
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable
# Время МСК (`time_msk.py`) — канон в _shared-references/; в упакованном .skill — рядом (pack.sh).
_HERE_TM = os.path.dirname(os.path.abspath(__file__))
for _cand in (_HERE_TM, os.path.normpath(os.path.join(_HERE_TM, "..", "..", "..", "_shared-references"))):
    if _cand not in sys.path:
        sys.path.insert(0, _cand)
import time_msk  # noqa: E402
import known_splits  # noqa: E402


# =============================================================================
# Константы
# =============================================================================

# Дата блокировки иностранных бумаг. Последняя торговая сессия Мосбиржи
# перед блокировкой — 25.02.2022. 28.02 торги не велись (часть инструментов).
# Пользователь просит "отсечку" 01.03.2022 — берём именно её, но при
# реконструкции используем позиции на конец дня 28.02.2022 (последний
# "доторговый" день по данным IntelInvest).
BLOCKING_CUTOFF = dt.date(2022, 3, 1)

# Известные префиксы/тикеры заблокированных инструментов.
# FX*  — FinEx ETF (все торговались на Мосбирже, но блокированы)
# RSH* — Росбанк ETF на зарубежные активы
# TBIO — Тинькофф БИО (зарубежные биотехи)
# TMF  — Direxion Daily 20+ Year Treasury Bull 3X (СПб биржа)
BLOCKED_PREFIXES_STRICT = ("FX", "RSH")
# RTX, Z — замороженные американские акции (Raytheon, Zillow) с единственной
# рублёвой сделкой-корректировкой брокера от 2024-08-12. Автоматическое правило
# «все сделки в USD/EUR» их не ловит: рублёвый вариант ключа выглядит живым.
# Отличить их эвристикой от тикера T нельзя — у T/RUB (Т-Технологии, живая
# российская бумага) та же форма ключа, но 12 сделок вплоть до 2026-08. Поэтому
# разделение — вручную, через этот реестр (PDL-12, разбор 2026-08-19).
BLOCKED_EXACT = {"TMF", "TBIO", "GOLD", "TLT", "SPXU", "SDS", "SH", "VIXY",
                 "RTX", "Z"}

# Белый список российских фондов: не блокируем даже при совпадении префиксов
RUSSIAN_FUND_WHITELIST = {
    "TPAY", "TGLD", "LQDT", "TLCB", "AKMB", "AKME", "AKMM",
    "EQMX", "SBMX", "SBCB", "SBGB", "SBRB", "SBLB",
    "FINAMAR",  # Финам Алгоритм Роста
    "WIMB",     # ВИМ
}

# Корректировки сырых trade-данных.
# TMF: пользователь указал, что реально позиция закрыта 05.08.2024.
# Мы добавляем виртуальную "Продажу" оставшегося количества, чтобы quantity
# = 0 после 2024-08-05.
TMF_FORCED_CLOSE_DATE = dt.date(2024, 8, 5)

# Коды валют в ЦБ РФ
CBR_CURRENCY_CODES = {
    "USD": "R01235",
    "EUR": "R01239",
    "CNY": "R01375",
    "KZT": "R01335",
}

CBR_DAILY_URL = "https://www.cbr.ru/scripts/XML_daily.asp"
_CBR_ID_CACHE: dict[str, str] = {}


def cbr_val_id(currency: str) -> str:
    """ID валюты в справочнике ЦБ (VAL_NM_RQ). Известные — из CBR_CURRENCY_CODES, прочие —
    по CharCode из XML_daily (один запрос на прогон). Нет у ЦБ → ValueError."""
    if currency in CBR_CURRENCY_CODES:
        return CBR_CURRENCY_CODES[currency]
    if currency not in _CBR_ID_CACHE:
        req = urllib.request.Request(CBR_DAILY_URL, headers={"User-Agent": CBR_USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
        try:
            text = raw.decode("cp1251")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
        for v in ET.fromstring(text).findall("Valute"):
            cc, vid = v.findtext("CharCode"), v.attrib.get("ID")
            if cc and vid:
                _CBR_ID_CACHE[cc.strip()] = vid
    if currency not in _CBR_ID_CACHE:
        raise ValueError(f"Нет валюты {currency} в справочнике ЦБ")
    return _CBR_ID_CACHE[currency]

CBR_URL_TEMPLATE = (
    "https://www.cbr.ru/scripts/XML_dynamic.asp"
    "?date_req1={start}&date_req2={end}&VAL_NM_RQ={code}"
)

CBR_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# PDL_CBR_CACHE — путь рабочего кэша курсов (build_snapshot.py --record/--replay держит
# его в пакете прогона, чтобы повтор начинался с того же состояния кэша, что и запись).
CBR_CACHE_PATH = Path(os.environ.get("PDL_CBR_CACHE") or "/tmp/cbr_rates_cache.json")

# Путь к bundled историческим курсам (часть дистрибутива скилла).
# Если рабочий кэш /tmp пуст или не содержит нужных дат — подмешиваем
# данные отсюда. Не перезаписываем — только добавляем недостающее.
# Это устраняет необходимость каждый раз долбить ЦБ РФ при свежей сессии.
CBR_BUNDLED_PATH = Path(__file__).resolve().parent.parent / "references" / "cbr_rates_bundled.json"

# Реестр известных сплитов / reverse-сплитов.
# {ticker: [{"date": date, "ratio": ratio, "note": ...}, ...]}
# ratio > 1 — прямой сплит (1 акция -> ratio акций).
# ratio < 1 — обратный сплит (10 акций -> 1 акция, т.е. ratio = 0.1).
# Применяется в reconstruct_positions через split_factor: количество каждой
# сделки, совершённой ДО split.date, приводится к постсплитовым единицам
# (умножается на ratio) в момент прохода — до расчёта себестоимости.
# Это позволяет сопоставить post-split qty с MOEX-ценой без правки trades.
# Дата — день возобновления торгов (когда позиции уже отражены по post-split qty).
KNOWN_SPLITS: dict[str, list[dict]] = known_splits.builtin_copy()


def load_known_splits(path: str | None) -> int:
    """--splits-file: заменить KNOWN_SPLITS действующим реестром (встроенный набор + файл).
    Нет пути/файла — встроенный набор. Невалидный файл — KnownSplitsError (не глотаем:
    пропущенный сплит меняет количество в 10–100 раз). Возвращает число сплитов в реестре."""
    registry, _dismissed = known_splits.load(path)
    KNOWN_SPLITS.clear()
    KNOWN_SPLITS.update(registry)
    return sum(len(v) for v in KNOWN_SPLITS.values())


# Реестр известных замещаек (fallback для nominal_currency, если MOEX ISS
# упал на discovery-фазе и не вернул FACEUNIT). Эти данные СТАТИЧНЫ —
# номинальная валюта облигации не меняется за её жизнь.
KNOWN_FX_BONDS: dict[str, str] = {
    # USD замещайки
    "RU000A105JH9": "USD",  # ГазКЗ-27Д2
    "RU000A105KU0": "USD",  # ГазКЗ-29Д
    "RU000A1056U0": "USD",  # ГазКЗ-27Д (иногда пропадает у MOEX)
    "RU000A105A95": "USD",
    "RU000A105146": "USD",
    "RU000A105SG2": "USD",
    "RU000A105GN3": "USD",
    "RU000A108G70": "USD",
    "RU000A10A869": "USD",  # РФ ЗО 28 Д
    "RU000A10C9Y2": "USD",
    # EUR замещайки
    "RU000A105RZ4": "EUR",
    # CNY замещайки
    "RU000A1054W1": "CNY",  # Полюс Б1P2
    "RU000A105104": "CNY",  # РУСАЛ БО05
    "RU000A105C44": "CNY",  # РУСАЛ 1Р1
    "RU000A108FX8": "CNY",  # ЕСЭГ1PC5
    "RU000A107RH8": "CNY",  # РУСАЛ 1Р6
}

# =============================================================================
# Типы данных
# =============================================================================


@dataclass
class Trade:
    ticker: str
    name: str
    operation: str
    date: dt.date
    qty: float | None
    price: float | None
    nominal: float | None
    nkd: float | None
    commission: float
    amount: float              # в валюте operation (sign как в исходнике)
    amount_no_comm: float      # сумма без комиссии
    currency: str
    note: str
    # Производные (заполняются позже)
    rub_amount: float = 0.0    # amount переведённый в RUB по курсу ЦБ на дату
    rub_rate: float = 1.0      # курс, использованный для конвертации
    is_synthetic: bool = False # искусственная корректирующая сделка


@dataclass
class Position:
    """Состояние позиции: (ticker, currency) — уникальный ключ."""
    ticker: str
    currency: str
    name: str = ""
    qty: float = 0.0
    # Cost basis — средневзвешенная цена покупки (в RUB, после конвертации)
    # с учётом комиссий.
    total_cost_rub: float = 0.0   # суммарно потрачено на покупки (RUB)
    total_sold_rub: float = 0.0   # суммарно получено от продаж (RUB)
    # Для расчёта средней цены при FIFO/WACC-учёте
    avg_cost_rub: float = 0.0     # текущая средняя цена 1 штуки в RUB
    # Доходы по бумаге
    coupons_rub: float = 0.0
    dividends_rub: float = 0.0
    amortization_rub: float = 0.0

    @property
    def key(self) -> tuple[str, str]:
        return (self.ticker, self.currency)


@dataclass
class CashFlow:
    """Внешний денежный поток для XIRR. Знак: + = приход в портфель (депозит),
    - = отток (вывод). Конечная стоимость портфеля добавляется как + в конце."""
    date: dt.date
    amount_rub: float
    kind: str  # 'deposit', 'withdrawal', 'terminal_value', 'initial_value'
    note: str = ""


# =============================================================================
# I. Парсинг файлов
# =============================================================================


def parse_trades(path: str) -> list[Trade]:
    """
    Читает trades.xlsx из IntelInvest.
    Колонки: Тикер, Название, Операция, Дата, Кол-во, Цена, Номинал,
             НКД, Комиссия, Сумма, Сумма без комиссии, Валюта, Заметка.
    Строка 0 — служебная ("intelinvest.ru"), строка 1 — заголовок.
    """
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True)
    ws = wb.active
    trades: list[Trade] = []

    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i < 2:
            continue
        if not row or all(v is None for v in row):
            continue
        ticker = row[0]
        if not ticker:
            continue

        date_val = row[3]
        if isinstance(date_val, dt.datetime):
            trade_date = date_val.date()
        elif isinstance(date_val, dt.date):
            trade_date = date_val
        elif isinstance(date_val, str):
            trade_date = dt.date.fromisoformat(date_val)
        else:
            continue

        trades.append(Trade(
            ticker=str(ticker).strip(),
            name=str(row[1] or "").strip(),
            operation=str(row[2] or "").strip(),
            date=trade_date,
            qty=_to_float(row[4]),
            price=_to_float(row[5]),
            nominal=_to_float(row[6]),
            nkd=_to_float(row[7]),
            commission=_to_float(row[8]) or 0.0,
            amount=_to_float(row[9]) or 0.0,
            amount_no_comm=_to_float(row[10]) or 0.0,
            currency=str(row[11] or "RUB").strip() or "RUB",
            note=str(row[12] or "").strip(),
        ))

    trades.sort(key=lambda t: t.date)
    return trades


def parse_current_portfolio(path: str) -> dict[tuple[str, str], dict[str, Any]]:
    """
    Читает common.xlsx (срез портфеля). Возвращает словарь
    {(ticker, currency_guess): {'qty': ..., 'current_value_rub': ..., ...}}.

    В common.xlsx нет столбца валюты. Валюту определим через trades позже.
    """
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True)
    ws = wb.active
    positions: dict[tuple[str, str], dict[str, Any]] = {}

    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i < 2:
            continue
        type_col = row[0]
        ticker = row[1]
        if not ticker or type_col == "Деньги":
            continue

        qty = _to_float(row[3]) or 0.0
        if qty == 0:
            continue

        positions[(str(ticker).strip(), "?")] = {
            "type": str(type_col or "").strip(),
            "name": str(row[2] or "").strip(),
            "qty": qty,
            "avg_price": _to_float(row[4]) or 0.0,
            "current_price": _to_float(row[5]) or 0.0,
            "cost_buys": _to_float(row[6]) or 0.0,
            "proceeds_sells": _to_float(row[7]) or 0.0,
            "current_value_rub": _to_float(row[8]) or 0.0,
            "income_accruals": _to_float(row[9]) or 0.0,
            "current_pl": _to_float(row[11]) or 0.0,
            "trade_pl": _to_float(row[13]) or 0.0,
            "total_pl": _to_float(row[17]) or 0.0,
        }
    return positions


def _to_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


# =============================================================================
# II. Загрузчик курсов ЦБ РФ с локальным кэшем
# =============================================================================


def load_cbr_cache() -> dict[str, dict[str, float]]:
    """
    {currency: {date_iso: rate}}

    Порядок загрузки:
      1. Сырой рабочий кэш из /tmp/cbr_rates_cache.json (если есть)
      2. Bundled исторический кэш references/cbr_rates_bundled.json
         (часть дистрибутива скилла — обновляется при релизах)
      3. Дополняем рабочий кэш недостающими датами из bundled
         (приоритет у рабочего — он свежее)

    Это решает проблему с 503 от ЦБ РФ для НОВЫХ сессий: почти все нужные
    курсы за 2019–<release_date> уже есть в bundled, live-запрос нужен
    только для последних нескольких дней.
    """
    # 1. Рабочий кэш
    working: dict[str, dict[str, float]] = {}
    if CBR_CACHE_PATH.exists():
        try:
            working = json.loads(CBR_CACHE_PATH.read_text())
        except (json.JSONDecodeError, IOError):
            working = {}

    # 2. Bundled кэш
    bundled: dict[str, dict[str, float]] = {}
    if CBR_BUNDLED_PATH.exists():
        try:
            bundled = json.loads(CBR_BUNDLED_PATH.read_text())
        except (json.JSONDecodeError, IOError):
            bundled = {}

    # 3. Подмешиваем bundled в working (working выигрывает при конфликтах)
    merged_something = False
    for cur, dates in bundled.items():
        w_cur = working.setdefault(cur, {})
        for d_iso, rate in dates.items():
            if d_iso not in w_cur:
                w_cur[d_iso] = rate
                merged_something = True

    # Сохраняем расширенный кэш, чтобы в следующий раз грузилось быстрее
    if merged_something and working:
        try:
            save_cbr_cache(working)
        except Exception:
            pass  # не критично

    return working


def save_cbr_cache(cache: dict[str, dict[str, float]]) -> None:
    CBR_CACHE_PATH.write_text(json.dumps(cache, indent=1, sort_keys=True))


def fetch_cbr_range(
    currency: str,
    start: dt.date,
    end: dt.date,
) -> dict[dt.date, float]:
    """Запрос к ЦБ РФ за диапазон. Возвращает {date: rate_per_unit}.
    Автоматически делит длинные диапазоны на куски по 364 дня
    (ЦБ не даёт больше)."""
    cbr_val_id(currency)  # ValueError, если у ЦБ нет такой валюты

    out: dict[dt.date, float] = {}
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(chunk_start + dt.timedelta(days=364), end)
        chunk = _fetch_cbr_chunk_with_retry(currency, chunk_start, chunk_end)
        out.update(chunk)
        chunk_start = chunk_end + dt.timedelta(days=1)
    return out


def _fetch_cbr_chunk_with_retry(
    currency: str, start: dt.date, end: dt.date,
    attempts: int = 4,
) -> dict[dt.date, float]:
    """Один HTTP-запрос с экспоненциальным backoff на 503."""
    import time as _time
    url = CBR_URL_TEMPLATE.format(
        start=start.strftime("%d/%m/%Y"),
        end=end.strftime("%d/%m/%Y"),
        code=cbr_val_id(currency),
    )
    last_exc: Exception | None = None
    for attempt in range(attempts):
        req = urllib.request.Request(url, headers={
            "User-Agent": CBR_USER_AGENT,
            "Accept": "text/xml,application/xml,*/*;q=0.9",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
            break
        except urllib.error.HTTPError as e:
            last_exc = e
            if e.code == 503 and attempt < attempts - 1:
                _time.sleep(2 ** attempt + 0.5)
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            last_exc = e
            if attempt < attempts - 1:
                _time.sleep(2 ** attempt + 0.5)
                continue
            raise
    else:
        if last_exc:
            raise last_exc
        return {}

    try:
        text = raw.decode("cp1251")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")

    root = ET.fromstring(text)
    out: dict[dt.date, float] = {}
    for record in root.findall("Record"):
        date_str = record.attrib.get("Date")
        if not date_str:
            continue
        d = dt.datetime.strptime(date_str, "%d.%m.%Y").date()
        nominal_el = record.find("Nominal")
        vunit_el = record.find("VunitRate")
        value_el = record.find("Value")
        if vunit_el is not None and vunit_el.text:
            rate = float(vunit_el.text.replace(",", "."))
        elif value_el is not None and value_el.text:
            value = float(value_el.text.replace(",", "."))
            nominal = 1.0
            if nominal_el is not None and nominal_el.text:
                nominal = float(nominal_el.text.replace(",", "."))
            rate = value / nominal
        else:
            continue
        out[d] = rate
    return out


def ensure_cbr_rates(
    currencies_dates: dict[str, set[dt.date]],
    cache: dict[str, dict[str, float]],
    verbose: bool = False,
) -> dict[str, dict[str, float]]:
    """
    Убеждаемся, что для каждой пары (currency, date) есть курс в кэше.
    Если какой-то даты нет — делаем один большой запрос за весь
    диапазон (min..max) нужных дат для этой валюты.

    Сохраняем кэш после КАЖДОЙ валюты, чтобы частичный успех не терялся.
    Если фетч упал — предупреждаем, но не падаем (будем fallback на ближайший
    кэшированный курс в rate_for).
    """
    errors: list[str] = []
    for currency, needed_dates in currencies_dates.items():
        if not needed_dates:
            continue
        if currency == "RUB" or currency == "POINT":
            continue
        cache_for_cur = cache.setdefault(currency, {})
        missing = [d for d in needed_dates if d.isoformat() not in cache_for_cur]
        if not missing:
            continue

        start = min(missing) - dt.timedelta(days=5)  # буфер для выходных
        end = max(missing) + dt.timedelta(days=2)
        if verbose:
            sys.stderr.write(
                f"[cbr] Fetching {currency} for {start}..{end} "
                f"({len(missing)} missing dates)\n"
            )
        try:
            fetched = fetch_cbr_range(currency, start, end)
            for d, rate in fetched.items():
                cache_for_cur[d.isoformat()] = rate
            save_cbr_cache(cache)  # save after each currency
        except Exception as e:
            msg = f"[cbr] WARN: failed to fetch {currency}: {e}"
            sys.stderr.write(msg + "\n")
            errors.append(msg)

    save_cbr_cache(cache)
    if errors:
        sys.stderr.write(
            f"[cbr] {len(errors)} fetch errors; "
            f"using nearest available cached rates where possible.\n"
        )
    return cache


def _cached_rate_ok(currency: str, date: dt.date, cache: dict[str, dict[str, float]]) -> bool:
    """Даст ли rate_for курс из кэша без похода в ЦБ."""
    try:
        rate_for(currency, date, cache)
        return True
    except RuntimeError:
        return False


def rate_for(
    currency: str,
    date: dt.date,
    cache: dict[str, dict[str, float]],
) -> float:
    """Возвращает курс на дату. Если выходной/праздник или сбой fetch'а —
    ближайший доступный кэшированный курс в пределах ±30 дней."""
    if currency == "RUB":
        return 1.0
    if currency == "POINT":
        return 0.0
    rates = cache.get(currency, {})
    if not rates:
        raise RuntimeError(f"No CBR cache for {currency}")
    iso = date.isoformat()
    if iso in rates:
        return rates[iso]
    # Ищем ближайший (сначала назад, т.к. ЦБ публикует курс на след. раб. день)
    for back in range(1, 31):
        prev = (date - dt.timedelta(days=back)).isoformat()
        if prev in rates:
            return rates[prev]
    # Если ничего не нашли назад — ищем вперёд (for out-of-range requests)
    for fwd in range(1, 31):
        nxt = (date + dt.timedelta(days=fwd)).isoformat()
        if nxt in rates:
            return rates[nxt]
    raise RuntimeError(f"No CBR rate for {currency} near {date} (±30 days)")


# Валюты, чьи текущие курсы кладутся в отчёт (fx_rates_asof) для снапшота:
# implied current_price замещаек и bond_cashflow_calendar в assemble_snapshot.py.
# Список — только валюты ДЕРЖИМЫХ бумаг (номинал облигаций + валюта позиций), без RUB/SUR/POINT;
# наполняет build_market_values (HELD_FX_CURRENCIES).
HELD_FX_CURRENCIES: set[str] = set()


def _is_foreign(cur) -> bool:
    return bool(cur) and cur not in ("RUB", "SUR", "RUR", "POINT")


def current_fx_rates(
    as_of: dt.date,
    cache: dict[str, dict[str, float]] | None = None,
    cbr_offline: bool = False,
    currencies=None,
) -> dict[str, dict | None]:
    """
    Курсы ЦБ на дату as_of для currencies (по умолчанию — валюты держимых бумаг,
    HELD_FX_CURRENCIES):
    {currency: {"rate": float, "rate_date": iso, "source": "cbr"} | None}.

    rate_date — фактическая дата курса (точная или ближайшая кэшированная
    в пределах ±30 дней, как в rate_for). Сбой по валюте → None, не падаем:
    потребитель (assemble_snapshot) обязан флагом отметить отсутствие курса.
    """
    cache = cache if cache is not None else load_cbr_cache()
    currencies = sorted(HELD_FX_CURRENCIES if currencies is None else set(currencies))
    if not cbr_offline:
        try:
            ensure_cbr_rates({c: {as_of} for c in currencies}, cache)
        except Exception:
            pass  # fallback на кэш ниже

    out: dict[str, dict | None] = {}
    for cur in currencies:
        rates = cache.get(cur, {})
        found: tuple[str, float] | None = None
        iso = as_of.isoformat()
        if iso in rates:
            found = (iso, rates[iso])
        else:
            # та же логика окрестности, что в rate_for: назад, потом вперёд
            for back in range(1, 31):
                d = (as_of - dt.timedelta(days=back)).isoformat()
                if d in rates:
                    found = (d, rates[d])
                    break
            if found is None:
                for fwd in range(1, 31):
                    d = (as_of + dt.timedelta(days=fwd)).isoformat()
                    if d in rates:
                        found = (d, rates[d])
                        break
        out[cur] = (
            {"rate": found[1], "rate_date": found[0], "source": "cbr"}
            if found else None
        )
    return out


# Провалы курса ЦБ за прогон (2026-10-21). Раньше молчали: сделка в USD/CNY без курса
# пересчитывалась в 0 ₽, валютная облигация — по курсу 1.0. На Mac через VPN (cbr.ru
# недоступен, кэш до 21.04) это дало XIRR −2,82% вместо 8,27% без единого флага.
# Попадает в отчёт как "fx_gaps" → assemble_snapshot ставит флаг fx_rates_missing.
FX_GAPS: dict[str, dict] = {}


def _fx_gap(kind: str, currency: str, date, ticker: str | None = None) -> None:
    g = FX_GAPS.setdefault(f"{kind}:{currency}", {"kind": kind, "currency": currency, "n": 0,
                                                  "first": None, "last": None, "tickers": []})
    if ticker and ticker not in g["tickers"]:
        g["tickers"].append(ticker)
    d = str(date)
    g["n"] += 1
    g["first"] = min(filter(None, [g["first"], d]))
    g["last"] = max(filter(None, [g["last"], d]))


def convert_trades_to_rub(
    trades: list[Trade],
    verbose: bool = False,
    cbr_offline: bool = False,
) -> list[Trade]:
    """Пополняет каждый Trade полями rub_amount и rub_rate.

    cbr_offline=True — пропускаем live-запросы к ЦБ РФ; пользуемся только
    тем, что есть в кэше (рабочем + bundled). Для недостающих дат
    rate_for найдёт ближайший кэшированный курс в пределах ±30 дней.
    """
    # Собираем все даты по валютам
    currencies_dates: dict[str, set[dt.date]] = defaultdict(set)
    for t in trades:
        if t.currency in ("RUB", "POINT"):
            continue
        currencies_dates[t.currency].add(t.date)

    cache = load_cbr_cache()
    if any(currencies_dates.values()) and not cbr_offline:
        cache = ensure_cbr_rates(currencies_dates, cache, verbose=verbose)
    elif cbr_offline and verbose:
        sys.stderr.write("[cbr] --cbr-offline: пропускаем live-запросы.\n")

    for t in trades:
        if t.currency in ("RUB", "POINT"):
            t.rub_rate = 1.0 if t.currency == "RUB" else 0.0
            t.rub_amount = t.amount if t.currency == "RUB" else 0.0
        else:
            try:
                t.rub_rate = rate_for(t.currency, t.date, cache)
                t.rub_amount = t.amount * t.rub_rate
            except RuntimeError as e:
                if verbose:
                    sys.stderr.write(
                        f"[cbr] WARN: no rate for {t.currency} {t.date}: {e}\n"
                    )
                t.rub_rate = 0.0
                t.rub_amount = 0.0
                _fx_gap("trade_zeroed", t.currency, t.date, t.ticker)
    return trades


# =============================================================================
# III. Корректировки (TMF forced close, и т.п.)
# =============================================================================


def apply_corrections(trades: list[Trade]) -> tuple[list[Trade], list[dict]]:
    """
    Применяет известные корректировки к сырым данным IntelInvest.
    Возвращает (новый список сделок, лог применённых корректировок).
    """
    log: list[dict] = []

    # ── Фиктивные Корректировки по ЗАМОРОЖЕННЫМ бумагам ──
    # IntelInvest синхронизирует количества с загружаемым отчётом брокера
    # («Корректировка количества на основе указанного баланса …»). Замороженные
    # иностранные бумаги (FinEx/RSH*/акции СПб) хранятся на счетах, чьи отчёты
    # в IntelInvest НЕ грузятся, — синхронизация ложно списывает/режет живые
    # позиции (10.04.2026 массово: FXRL/FXRU → 0, FXUS 1504 → 415; реального
    # выкупа не было — подтверждено владельцем 2026-07-04: ВКС держит 1504
    # FXUS, А-Инвестиции — TBIO). Поэтому Корректировки по blocked-бумагам
    # игнорируются; по обычным бумагам (MDMG, WUSH) и деньгам — применяются
    # как раньше. Реальная продажа замороженной бумаги приходит «Продажей»
    # (OTC-кейсы FXDE/FXCN 2024) и фильтром не затрагивается.
    _blocked_for_corr = classify_blocked(trades)
    _all_blocked_keys = (set().union(*_blocked_for_corr.values())
                         if _blocked_for_corr else set())
    fake_corr = [t for t in trades
                 if t.operation == "Корректировка"
                 and (t.ticker, t.currency) in _all_blocked_keys]
    if fake_corr:
        fake_ids = {id(t) for t in fake_corr}
        trades = [t for t in trades if id(t) not in fake_ids]
        tickers = sorted({t.ticker for t in fake_corr})
        log.append({
            "type": "ignored_blocked_corrections",
            "date": max(t.date for t in fake_corr).isoformat(),
            "reason": (f"Проигнорированы {len(fake_corr)} корректировок "
                       f"«на основе указанного баланса» по замороженным "
                       f"бумагам ({', '.join(tickers[:8])}"
                       + ("…" if len(tickers) > 8 else "")
                       + "): бумаги лежат на счетах, чьи отчёты не грузятся "
                         "в IntelInvest, — синхронизация ложно списывала "
                         "живые позиции (подтверждено владельцем 2026-07-04)."),
        })

    # Считаем текущий баланс TMF по сделкам
    tmf_trades = [t for t in trades if t.ticker == "TMF"]
    if tmf_trades:
        net_qty = 0.0
        # Учёт reverse split — TMF делал reverse split 10-to-1 8 июля 2024.
        # Предполагаем его по косвенным признакам (дивидендная запись от 08.07.2024
        # на 25 шт при теоретическом остатке ~336 шт).
        # Упрощённо: просто суммируем как есть и фиксируем остаток.
        for t in tmf_trades:
            if t.operation == "Покупка":
                net_qty += (t.qty or 0)
            elif t.operation == "Продажа":
                net_qty -= (t.qty or 0)

        if abs(net_qty) > 0.01:
            # Добавляем виртуальную продажу остатка на 05.08.2024.
            # Цена — по последней известной продаже (61.09 USD), курс — ЦБ.
            last_sell = [
                t for t in tmf_trades
                if t.operation == "Продажа" and t.date <= TMF_FORCED_CLOSE_DATE
            ]
            if last_sell:
                last_px = last_sell[-1].price or 61.09
            else:
                last_px = 61.09

            synthetic = Trade(
                ticker="TMF",
                name="Direxion Daily [synthetic close]",
                operation="Продажа",
                date=TMF_FORCED_CLOSE_DATE,
                qty=net_qty,
                price=last_px,
                nominal=None,
                nkd=None,
                commission=0.0,
                amount=-net_qty * last_px,  # знак "-" как у обычной продажи
                amount_no_comm=-net_qty * last_px,
                currency="USD",
                note="[synthetic] Вынужденное закрытие остатка согласно CLAUDE.md",
                is_synthetic=True,
            )
            trades.append(synthetic)
            trades.sort(key=lambda t: t.date)
            log.append({
                "type": "tmf_forced_close",
                "ticker": "TMF",
                "qty_closed": net_qty,
                "price": last_px,
                "date": TMF_FORCED_CLOSE_DATE.isoformat(),
                "reason": "В trades не хватает записей о финальной продаже "
                          "(возможно, связано с reverse split 1-к-10 в июле 2024 "
                          "и последующим полным закрытием позиции).",
            })

    return trades, log


# =============================================================================
# IV. Реконструкция позиций
# =============================================================================


def split_factor(
    ticker: str,
    currency: str,
    trade_date: dt.date,
    as_of: dt.date,
    splits_registry: dict[str, list[dict]] | None = None,
) -> float:
    """Во сколько раз количество из сделки от trade_date выросло к as_of из-за
    сплитов (цена одной бумаги — во столько же упала). Сплиты Мосбиржи — только
    у RUB-сделок; сделка в день сплита и позже уже в постсплитовых единицах."""
    if currency != "RUB":
        return 1.0
    if splits_registry is None:
        splits_registry = KNOWN_SPLITS
    factor = 1.0
    for split in splits_registry.get(ticker, []):
        if trade_date < split["date"] <= as_of:
            factor *= float(split["ratio"])
    return factor


def reconstruct_positions(
    trades: list[Trade],
    as_of: dt.date | None = None,
) -> dict[tuple[str, str], Position]:
    """
    Проходит по всем сделкам до as_of (включительно) и считает позиции.

    Идентификатор позиции = (ticker, currency), чтобы различать омонимы
    (T = AT&T USD vs T-Техно RUB).

    Cost basis — средневзвешенная цена покупки (weighted average) в RUB,
    с учётом комиссий. При продажах уменьшаем qty пропорционально.

    Количество каждой сделки сразу приводится к постсплитовым единицам на as_of
    (split_factor), поэтому себестоимость при продаже после сплита считается
    по средней в тех же единицах. Сплиты после прохода не применяются.
    """
    if as_of is None:
        as_of = dt.date(3000, 1, 1)

    positions: dict[tuple[str, str], Position] = {}

    for t in trades:
        if t.date > as_of:
            break
        if t.ticker.startswith("Деньги"):
            continue
        if t.currency == "POINT":
            # Фьючерсы — не фиксируем как позицию (маржа, не бумага)
            continue

        key = (t.ticker, t.currency)
        pos = positions.get(key)
        if pos is None:
            pos = Position(ticker=t.ticker, currency=t.currency, name=t.name)
            positions[key] = pos
        if not pos.name:
            pos.name = t.name

        op = t.operation
        qty = (t.qty or 0.0) * split_factor(t.ticker, t.currency, t.date, as_of)

        if op == "Покупка":
            # amount у IntelInvest для покупок положителен (это сумма сделки),
            # но "Списание" денежной позиции отрицательно. Используем amount.
            cost = abs(t.rub_amount)
            pos.qty += qty
            pos.total_cost_rub += cost
            # WACC для avg
            if pos.qty > 1e-9:
                pos.avg_cost_rub = pos.total_cost_rub / pos.qty
        elif op == "Продажа":
            proceeds = abs(t.rub_amount)
            # При продаже уменьшаем qty, cost basis списываем по среднему
            if pos.qty > 1e-9:
                avg = pos.total_cost_rub / pos.qty if pos.qty > 0 else 0.0
                sold_cost = avg * min(qty, pos.qty)
                pos.total_cost_rub -= sold_cost
            pos.qty -= qty
            pos.total_sold_rub += proceeds
        elif op == "Купон":
            pos.coupons_rub += t.rub_amount
        elif op == "Дивиденд":
            pos.dividends_rub += t.rub_amount
        elif op == "Амортизация":
            pos.amortization_rub += t.rub_amount
            # Амортизация уменьшает номинал облигации, но не qty.
            # Для cost basis: можно частично списать. Для простоты — нет.
        elif op == "Корректировка":
            # IntelInvest синхронизирует остатки с отчётом брокера. Записи с
            # ненулевой qty по бумагам (не cash) — это реальная дельта позиции.
            # Знак amount определяет направление: + = добавить qty, − = убрать.
            # qty в поле всегда ABS(delta).
            amt = t.rub_amount or 0.0
            if qty > 1e-9:
                if amt > 0:
                    # Виртуальная покупка: добавляем qty, cost basis растёт на amount
                    pos.qty += qty
                    pos.total_cost_rub += abs(amt)
                    if pos.qty > 1e-9:
                        pos.avg_cost_rub = pos.total_cost_rub / pos.qty
                elif amt < 0:
                    # Виртуальная продажа/списание: уменьшаем qty, списываем
                    # cost basis по среднему (как при продаже)
                    if pos.qty > 1e-9:
                        avg = pos.total_cost_rub / pos.qty
                        sold_cost = avg * min(qty, pos.qty)
                        pos.total_cost_rub -= sold_cost
                    pos.qty -= qty
                    pos.total_sold_rub += abs(amt)
                # amt == 0 — чисто информационная, не трогаем
        # Остальные операции (Внесение/Списание по cash) не меняют позицию.

    # Постпроцессинг: объединяем кроссвалютные позиции с одним name
    positions = merge_cross_currency_positions(positions)

    return positions


def merge_cross_currency_positions(
    positions: dict[tuple[str, str], Position],
) -> dict[tuple[str, str], Position]:
    """
    Объединяет позиции с одинаковым тикером и близким name (один инструмент
    в разных валютах сделок). Пример: TGLD куплен в USD, продан в RUB —
    это одна бумага, разные валюты сделок.

    НЕ объединяет явные омонимы типа 'T' (Т-Технологии RUB vs AT&T USD),
    потому что у них разные name.

    Алгоритм:
      1. Группировка по тикеру.
      2. Внутри группы: по prefix(name, 8) lowercased.
      3. Если в подгруппе ≥2 позиций — объединяем в одну с canonical_currency
         (RUB > USD > EUR > CNY > прочие).
    """
    by_ticker: dict[str, list[tuple[tuple[str, str], Position]]] = defaultdict(list)
    for key, pos in positions.items():
        by_ticker[key[0]].append((key, pos))

    result: dict[tuple[str, str], Position] = {}
    currency_priority = {"RUB": 0, "USD": 1, "EUR": 2, "CNY": 3}

    for ticker, items in by_ticker.items():
        if len(items) == 1:
            key, pos = items[0]
            result[key] = pos
            continue

        # Группируем по нормализованному name
        groups: dict[str, list[tuple[tuple[str, str], Position]]] = defaultdict(list)
        for key, pos in items:
            name_norm = (pos.name or "").strip().lower()[:8]
            groups[name_norm].append((key, pos))

        for name_key, group in groups.items():
            if len(group) == 1:
                k, p = group[0]
                result[k] = p
                continue
            # Объединяем
            canon_cur = min(
                (k[1] for k, _ in group),
                key=lambda c: currency_priority.get(c, 10),
            )
            merged = Position(
                ticker=ticker,
                currency=canon_cur,
                name=group[0][1].name,
            )
            for _, p in group:
                merged.qty += p.qty
                merged.total_cost_rub += p.total_cost_rub
                merged.total_sold_rub += p.total_sold_rub
                merged.coupons_rub += p.coupons_rub
                merged.dividends_rub += p.dividends_rub
                merged.amortization_rub += p.amortization_rub
            if merged.qty > 1e-9:
                merged.avg_cost_rub = merged.total_cost_rub / merged.qty
            result[(ticker, canon_cur)] = merged
    return result


# =============================================================================
# V. Классификация заблокированных бумаг
# =============================================================================


# Тип бумаги с Мосбиржи (Portfolio/security-types.json): тикер → stock|bond|fund. Перебивает
# эвристику ниже; other и None из справочника сюда не попадают (security_types.overrides_from).
_TYPE_OVERRIDES: dict[str, str] = {}


def set_type_overrides(by_ticker: dict[str, str] | None) -> None:
    """Задать переопределения типа (пусто/None — сбросить). Значения вне stock|bond|fund отбрасываются."""
    _TYPE_OVERRIDES.clear()
    for t, v in (by_ticker or {}).items():
        if v in ("stock", "bond", "fund"):
            _TYPE_OVERRIDES[t] = v


def load_types_cache(path: str | None) -> int:
    """--types-cache: загрузить справочник типов и включить переопределения.
    Пути нет / файл не читается — молча без переопределений. Возвращает число переопределений."""
    set_type_overrides(None)
    if not path or not Path(path).is_file():
        return 0
    import security_types
    set_type_overrides(security_types.overrides_from(security_types.load_types(path)))
    return len(_TYPE_OVERRIDES)


def classify_instrument_type(trades_for_ticker: list[Trade], use_overrides: bool = True) -> str:
    """
    Определяет тип инструмента: сначала справочник Мосбиржи (set_type_overrides), затем по
    истории операций.
      bond    — были купоны или амортизация
      stock   — были дивиденды (и не было купонов)
      fund    — известный фонд/ETF
      future  — фьючерс (тикер содержит дефис/точку и амплитуду)
      other   — всё остальное
    """
    if not trades_for_ticker:
        return "other"
    ticker = trades_for_ticker[0].ticker
    ops = {t.operation for t in trades_for_ticker}

    if use_overrides and ticker in _TYPE_OVERRIDES:
        return _TYPE_OVERRIDES[ticker]

    known_funds = {
        "TPAY", "TGLD", "LQDT", "TLCB", "AKMB", "AKME", "AKMM", "OBLG",
        "EQMX", "SBMX", "SBCB", "SBGB", "SBRB", "SBLB",
        "FINAMAR", "WIMB", "TBIO", "TBRU", "TRUR",
        "TMON",    # денежный фонд Т-Капитал: без дивидендов падал в default stock
        "XXXXXX",  # ЗПИФ Рентал ПРО: доходные выплаты классифицировались как дивиденды акции
    }
    if ticker in known_funds:
        return "fund"
    # FinEx / Rosbank ETF
    if any(ticker.startswith(p) and len(ticker) <= 6 for p in ("FX", "RSH")):
        return "fund"
    # Фьючерсы: тикеры вида "SI-3.23", "Si-9.23", "MXI-12.22"
    if "-" in ticker and any(c.isdigit() for c in ticker):
        return "future"

    if "Купон" in ops or "Амортизация" in ops:
        return "bond"
    if "Дивиденд" in ops:
        return "stock"

    # ISIN-тикер как признак облигации. Госбумаги — ЛЮБАЯ серия ОФЗ
    # (SU + 5 цифр + RMFS + цифра): 26xxx ПД, 52xxx ИН-линкеры, 29xxx ПК-флоатеры,
    # 46xxx амортизационные. Узкий `SU26` ловил только ПД: линкер SU52004RMFS7
    # без полученных купонов падал в default 'stock' (боевой кейс 2026-07-02).
    if ticker.startswith("RU000") or (
        len(ticker) == 12 and ticker.startswith("SU")
        and ticker[2:7].isdigit() and ticker[7:11] == "RMFS"
    ):
        return "bond"

    return "stock"  # по умолчанию


def unambiguous_blocked_tickers(
    trades: list[Trade], all_blocked: set[tuple[str, str]]
) -> set[str]:
    """Тикеры, у которых ЗАБЛОКИРОВАНЫ ВСЕ валютные варианты (PDL-12).

    Зачем: позиции реконструируются с приведением к рублю
    (`merge_cross_currency_positions` внутри `reconstruct_positions`), поэтому
    живой ключ американской бумаги — `(BAC, RUB)`. А `classify_blocked` ключует
    по валюте СДЕЛКИ и помечает `(BAC, USD)`. Ключевые пространства расходятся,
    пометка теряется, и заблокированная бумага оценивается по `cost_basis` /
    `last_trade_price` вместо нуля. На прогоне 19.08.2026 так утекли 17 позиций
    на 239 211 ₽ — при этом `blocked_value_rub` честно показывал 0, а
    `total_value_rub_excl_blocked` совпадал с `total_value_rub`.

    Почему нельзя просто сопоставлять по тикеру: `T/USD` — AT&T (заблокирован),
    `T/RUB` — Т-Технологии (живая позиция). Сопоставление по одному тикеру
    обнулило бы живую бумагу. Поэтому в набор попадают только тикеры без
    незаблокированного валютного варианта.
    """
    by_ticker: dict[str, set[str]] = defaultdict(set)
    for t in trades:
        if t.operation not in ("Покупка", "Продажа"):
            continue
        if t.ticker.startswith("Деньги") or t.currency == "POINT":
            continue
        by_ticker[t.ticker].add(t.currency)

    return {
        ticker
        for ticker, currencies in by_ticker.items()
        if currencies and all((ticker, c) in all_blocked for c in currencies)
    }


def classify_blocked(trades: list[Trade]) -> dict[str, set[tuple[str, str]]]:
    """
    Возвращает {reason: set of (ticker, currency)} — заблокированные позиции.
    Ключ позиции — (ticker, currency), чтобы T (USD) — AT&T был заблокирован,
    а T (RUB) — Т-Технологии — нет.
    """
    blocked: dict[str, set[tuple[str, str]]] = defaultdict(set)

    # Собираем уникальные (ticker, currency) со сделками покупки/продажи
    pairs: dict[tuple[str, str], list[Trade]] = defaultdict(list)
    for t in trades:
        if t.operation not in ("Покупка", "Продажа"):
            continue
        if t.ticker.startswith("Деньги"):
            continue
        if t.currency == "POINT":
            continue
        pairs[(t.ticker, t.currency)].append(t)

    for (ticker, currency), ticker_trades in pairs.items():
        # 1. Явный whitelist
        if ticker in RUSSIAN_FUND_WHITELIST:
            continue
        # 2. Явный blocklist
        if ticker in BLOCKED_EXACT:
            blocked["explicit_list"].add((ticker, currency))
            continue
        # 3. Тикер с точкой (европейские, etc.)
        if "." in ticker:
            blocked["foreign_suffix"].add((ticker, currency))
            continue
        # 4. Префиксы Finex/Росбанк
        if any(
            ticker.startswith(p) and len(ticker) <= 6
            for p in BLOCKED_PREFIXES_STRICT
        ):
            blocked["finex_rosbank"].add((ticker, currency))
            continue
        # 5. Все сделки в USD/EUR И нет сделок после блокировки
        currencies = set(t.currency for t in ticker_trades)
        if currencies.issubset({"USD", "EUR"}):
            last_trade = max(t.date for t in ticker_trades)
            if last_trade < BLOCKING_CUTOFF:
                blocked["foreign_stock_no_activity"].add((ticker, currency))
                continue
            # Ещё: если сделки были и после, но всё равно иностранный тикер —
            # смотрим на название. Если название на латинице (типа "AT&T Inc"),
            # то всё равно иностранный.
            # Эвристика: название не содержит кириллицы И все сделки в USD
            any_cyrillic = any(
                any('\u0400' <= ch <= '\u04FF' for ch in t.name)
                for t in ticker_trades if t.name
            )
            if not any_cyrillic:
                blocked["foreign_stock_usd_only"].add((ticker, currency))
                continue

    return blocked


# =============================================================================
# VI. Cashflows: извлечение внешних депозитов/выводов
# =============================================================================


def extract_external_cashflows(
    trades: list[Trade],
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
) -> list[CashFlow]:
    """
    Отделяет внешние cashflows (реальные депозиты и выводы) от внутренних
    (покупки/продажи/купоны/дивиденды/комиссии) через матч по заметке.

    Эвристика по IntelInvest-заметкам:
      - "Перечисление денежных средств"              → deposit (+)
      - "Вывод денежных средств"                      → withdrawal (-)
      - "Зачисление/Списание денег за сделку ..."    → internal (связана с trade)
      - "Зачисление купона ..." / "дивиденд..."      → internal (income)
      - "Вознаграждение брокера" / "Удержание налога" → internal (cost)
      - "Автоматическая корректировка остатка"       → internal (rebalance)
      - "Корректировка количества ..."               → internal

    Всё, что не распознано, считаем internal (консервативно).
    """
    cashflows: list[CashFlow] = []

    for t in trades:
        if not t.ticker.startswith("Деньги"):
            continue
        op = t.operation
        note = t.note

        if op == "Внесение":
            if "Перечисление денежных средств" in note:
                cashflows.append(CashFlow(
                    date=t.date,
                    amount_rub=t.rub_amount,  # положит.
                    kind="deposit",
                    note=note[:100],
                ))
            # elif "" — пустая заметка может быть внешним взносом, но мы
            # консервативны: оставляем internal.
        elif op == "Списание":
            if "Вывод денежных средств" in note:
                cashflows.append(CashFlow(
                    date=t.date,
                    amount_rub=t.rub_amount,  # отриц.
                    kind="withdrawal",
                    note=note[:100],
                ))
        elif op == "Вывод":
            # Редкая операция ввода/вывода бумаг между счетами (перенос
            # ценной бумаги). Деньгами не является, но если встречается как
            # cash — учтём.
            pass
        elif op == "Ввод":
            pass

    # Фильтр по датам
    if start_date or end_date:
        cashflows = [
            cf for cf in cashflows
            if (start_date is None or cf.date >= start_date)
            and (end_date is None or cf.date <= end_date)
        ]
    return cashflows


def infer_initial_investment(trades: list[Trade]) -> dict[str, float]:
    """
    Оценка общей суммы, которую пользователь фактически внёс в портфель,
    через инвариант "итоговое изменение cash = внутренние операции + external".

    Net cash change = Σ(Внесение) + Σ(Списание) в валюте
    Internal cash change = Σ(Продажа) + Σ(Купон) + Σ(Дивиденд) + Σ(Амортизация)
                         + Σ(Доход) - Σ(Покупка) - Σ(Расход)
                         + (ВМ фьючерсов)

    External cash change = Net - Internal   (то, что пользователь принёс со
                                             стороны или вывел)
    """
    # Агрегируем по валютам
    net_cash: dict[str, float] = defaultdict(float)
    internal: dict[str, float] = defaultdict(float)
    net_cash_rub: float = 0.0
    internal_rub: float = 0.0

    for t in trades:
        cur = t.currency if t.currency != "POINT" else "RUB"
        if t.ticker.startswith("Деньги"):
            # Это cash-позиция. Внесение/Списание — изменения баланса.
            net_cash[cur] += t.amount
            net_cash_rub += t.rub_amount
        else:
            # Это операция по бумаге. Вычисляем influence на cash.
            if t.operation == "Покупка":
                internal[cur] -= abs(t.amount)
                internal_rub -= abs(t.rub_amount)
            elif t.operation == "Продажа":
                internal[cur] += abs(t.amount)
                internal_rub += abs(t.rub_amount)
            elif t.operation in ("Купон", "Дивиденд", "Амортизация", "Доход"):
                internal[cur] += abs(t.amount)
                internal_rub += abs(t.rub_amount)
            elif t.operation == "Расход":
                # Расход — чистая комиссия без парной операции с бумагой
                internal[cur] -= abs(t.amount)
                internal_rub -= abs(t.rub_amount)
            elif t.operation in (
                "Начисление вариационной маржи",
                "Списание вариационной маржи",
            ):
                # Знак уже в amount
                internal[cur] += t.amount
                internal_rub += t.rub_amount
            elif t.operation == "Корректировка":
                internal[cur] += t.amount
                internal_rub += t.rub_amount

    # External = Net - Internal (по каждой валюте и total в RUB)
    external_by_cur = {
        cur: net_cash[cur] - internal[cur]
        for cur in set(list(net_cash.keys()) + list(internal.keys()))
    }
    external_rub = net_cash_rub - internal_rub

    return {
        "net_cash_by_currency": dict(net_cash),
        "internal_cash_by_currency": dict(internal),
        "external_by_currency": external_by_cur,
        "external_total_rub": external_rub,
        "note": (
            "External — суммарный приток извне за вычетом выводов. "
            "Положительное значение = чистые депозиты превысили выводы "
            "(столько денег пользователь реально вложил в брокерский счёт "
            "из кармана)."
        ),
    }


# =============================================================================
# VII. Cashflows по инварианту (более надёжный способ, чем эвристика по note)
# =============================================================================


def is_forex_conversion(t: Trade) -> bool:
    """
    Распознаёт операции валютной конверсии (обмен RUB ↔ USD/EUR/CNY внутри счёта).

    В IntelInvest такая конверсия фиксируется ДВУМЯ СТРОКАМИ:
      1) "Покупка/Продажа" на Деньги (USD/EUR/CNY) — изменение валютного остатка
      2) "Списание/Внесение" на Деньги (RUB) с заметкой
         "за покупку/продажу XXX [валюта]" — зеркальное изменение рублёвого остатка

    Обе части — внутренние движения, не external cashflows. Их надо исключить
    из инварианта, иначе разница курса ЦБ и курса брокера даст ложные
    "депозиты"/"выводы".
    """
    if not t.ticker.startswith("Деньги"):
        return False
    # Часть 1: "Покупка/Продажа" Деньги (USD/EUR/CNY)
    if t.operation in ("Покупка", "Продажа") and t.currency != "RUB":
        return True
    # Часть 2: "Списание/Внесение" Деньги (RUB) с заметкой о конверсии
    note = t.note or ""
    if t.currency == "RUB" and t.operation in ("Списание", "Внесение"):
        # Характерные признаки: "за покупку 2000 USD", "за продажу 1000 EUR"
        if ("за покупку" in note or "за продажу" in note):
            if any(c != "RUB" for c in re.findall(r"\b[A-Z]{3}\b", note)):
                return True
    return False


def extract_cashflows_by_invariant(
    trades: list[Trade],
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
) -> list[CashFlow]:
    """
    Выделяет внешние cashflows по дням через инвариант:
      external_today = (Внесение_today + Списание_today по cash)
                     - (net_internal_today от торговых операций)

    Исключает валютные конверсии (см. is_forex_conversion) из обеих сторон
    расчёта, чтобы курсовая разница ЦБ↔брокер не создавала ложных потоков.
    """
    by_date_net_cash: dict[dt.date, float] = defaultdict(float)
    by_date_internal: dict[dt.date, float] = defaultdict(float)

    for t in trades:
        if (start_date and t.date < start_date) or (end_date and t.date > end_date):
            continue
        if is_forex_conversion(t):
            continue  # обе стороны конверсии игнорируем
        if t.ticker.startswith("Деньги"):
            by_date_net_cash[t.date] += t.rub_amount
        else:
            op = t.operation
            if op == "Покупка":
                by_date_internal[t.date] -= abs(t.rub_amount)
            elif op == "Продажа":
                by_date_internal[t.date] += abs(t.rub_amount)
            elif op in ("Купон", "Дивиденд", "Амортизация", "Доход"):
                by_date_internal[t.date] += abs(t.rub_amount)
            elif op == "Расход":
                by_date_internal[t.date] -= abs(t.rub_amount)
            elif op in (
                "Начисление вариационной маржи",
                "Списание вариационной маржи",
            ):
                by_date_internal[t.date] += t.rub_amount
            elif op == "Корректировка":
                by_date_internal[t.date] += t.rub_amount

    cashflows: list[CashFlow] = []
    all_dates = sorted(set(by_date_net_cash.keys()) | set(by_date_internal.keys()))
    for d in all_dates:
        external = by_date_net_cash[d] - by_date_internal[d]
        # Шум округлений: игнорируем < 1 RUB
        if abs(external) < 1.0:
            continue
        cashflows.append(CashFlow(
            date=d,
            amount_rub=external,
            kind="deposit" if external > 0 else "withdrawal",
            note="invariant-based",
        ))
    return cashflows


# =============================================================================
# VIII. XIRR (Newton's method + bisection fallback)
# =============================================================================


def xirr(cashflows: list[tuple[dt.date, float]], guess: float = 0.1) -> float | None:
    """
    Money-weighted return. Решает: Σ cf_i / (1+r)^((d_i - d_0)/365) = 0.

    cashflows: список (date, amount). Должны быть и отрицательные (вложения),
    и положительные (финальная стоимость + дивиденды-выводы) для сходимости.
    Возвращает годовую ставку (0.15 = 15% годовых) или None, если не сошлось.
    """
    if len(cashflows) < 2:
        return None
    cfs = sorted(cashflows, key=lambda x: x[0])
    d0 = cfs[0][0]

    def npv(rate: float) -> float:
        total = 0.0
        for d, amt in cfs:
            years = (d - d0).days / 365.0
            total += amt / ((1.0 + rate) ** years)
        return total

    def dnpv(rate: float) -> float:
        total = 0.0
        for d, amt in cfs:
            years = (d - d0).days / 365.0
            if years == 0:
                continue
            total += -years * amt / ((1.0 + rate) ** (years + 1))
        return total

    # Newton
    r = guess
    for _ in range(100):
        try:
            f = npv(r)
            fp = dnpv(r)
            if abs(fp) < 1e-12:
                break
            r_new = r - f / fp
            if abs(r_new - r) < 1e-8:
                return r_new
            r = r_new
            if r < -0.999:
                r = -0.99
        except (ZeroDivisionError, OverflowError, ValueError):
            break

    # Bisection fallback
    lo, hi = -0.99, 10.0
    try:
        f_lo = npv(lo)
        f_hi = npv(hi)
        if f_lo * f_hi > 0:
            return None
        for _ in range(200):
            mid = (lo + hi) / 2.0
            f_mid = npv(mid)
            if abs(f_mid) < 1e-6:
                return mid
            if f_lo * f_mid < 0:
                hi = mid
                f_hi = f_mid
            else:
                lo = mid
                f_lo = f_mid
        return (lo + hi) / 2.0
    except (ValueError, OverflowError):
        return None


# =============================================================================
# VIII. Market prices: MOEX ISS + fallback на last trade price
# =============================================================================


def reconstruct_cash_balances(
    trades: list[Trade],
    as_of: dt.date | None = None,
) -> dict[str, float]:
    """
    Восстанавливает остатки денег по валютам на дату as_of.
    Из каждой Внесение/Списание в cash position (ticker 'Деньги (XXX)')
    копит баланс в родной валюте.
    Игнорирует валютные конверсии (is_forex_conversion) — они зеркально
    вычитают/прибавляют в разных валютах и не дают эффекта на общий баланс.
    Хотя постойте — как раз КОНВЕРСИИ нас и интересуют для cash balance:
    при покупке USD у нас реально появляется +USD и исчезает -RUB. Так что
    их НАДО учитывать.
    """
    if as_of is None:
        as_of = dt.date(3000, 1, 1)
    balances: dict[str, float] = defaultdict(float)
    for t in trades:
        if t.date > as_of:
            break
        if not t.ticker.startswith("Деньги"):
            continue
        cur = t.currency
        balances[cur] += t.amount
    return dict(balances)


def cash_balance_rub(
    balances: dict[str, float],
    as_of: dt.date,
    cbr_cache: dict[str, dict[str, float]],
) -> float:
    """Конвертирует cash-балансы в RUB."""
    total = 0.0
    for cur, amount in balances.items():
        if cur == "RUB":
            total += amount
        elif cur == "POINT":
            continue  # фьючерсные пункты игнорируем
        else:
            try:
                rate = rate_for(cur, as_of, cbr_cache)
                total += amount * rate
            except RuntimeError:
                pass  # нет курса — пропускаем (мелочь обычно)
    return total


def last_known_trade_price(
    ticker: str,
    currency: str,
    trades: list[Trade],
    as_of: dt.date,
    splits_registry: dict[str, list[dict]] | None = None,
) -> float | None:
    """Последняя цена Покупки/Продажи до as_of для (ticker, currency),
    скорректированная на сплиты, произошедшие МЕЖДУ датой сделки и as_of.

    Без коррекции возникает «pre-split цена × post-split qty» (T после 1:10
    сплита: 3342.80 × 1010 = 3.37M вместо 310K). После коррекции — делим
    цену сделки на кумулятивный ratio тех сплитов, что прошли уже после неё.

    splits_registry=None → используется KNOWN_SPLITS (см. split_factor).
    """
    candidates = [
        t for t in trades
        if t.ticker == ticker
        and t.currency == currency
        and t.date <= as_of
        and t.operation in ("Покупка", "Продажа")
        and t.price is not None
        and not t.is_synthetic
    ]
    if not candidates:
        return None

    last = candidates[-1]
    price = last.price

    # Цену сделки приводим к постсплитовой: делим на множитель сплитов после неё.
    return price / split_factor(ticker, currency, last.date, as_of, splits_registry)


def _accrued_rub_of(q: Any) -> float | None:
    """НКД одной облигации в рублях из Quote moex_quotes, или None.

    ACCRUEDINT номинирован в валюте торгов (CURRENCYID), не номинала:
    берём только рублёвые торги (SUR/RUB); иначе None — без догадок о курсе.
    """
    ai = getattr(q, "accrued_interest", None)
    if ai is None or getattr(q, "settle_currency", None) not in ("SUR", "RUB"):
        return None
    return float(ai)


def _absorb_moex_quote(
    sid: str, q: Any,
    last_prices: dict[str, float], face_values: dict[str, float],
    face_currencies: dict[str, str], failed: set[str],
    accrued_out: dict[str, float] | None,
) -> None:
    """Разбор одной котировки (Quote или объект с теми же атрибутами) в общие словари.

    last → prev_close; face_value; currency (SUR → RUB, MOEX исторически
    использует SUR для рубля); НКД — только рублёвый (_accrued_rub_of). Общий
    разбор для fetch_moex_prices (оба прохода) и moex_prices_from_quotes —
    одна цена в holdings и per_instrument_xirr (случай 2026-10-27).
    """
    last = getattr(q, "last", None) or getattr(q, "prev_close", None)
    fv = getattr(q, "face_value", None)
    fc = getattr(q, "currency", None)
    if last:
        last_prices[sid] = float(last)
        failed.discard(sid)
    if fv:
        face_values[sid] = float(fv)
    ai_rub = _accrued_rub_of(q)
    if ai_rub is not None and accrued_out is not None:
        accrued_out[sid] = ai_rub
    if fc:
        face_currencies[sid] = "RUB" if fc == "SUR" else fc


def moex_prices_from_quotes(
    quotes: dict[str, dict],
    secids: list[str],
    accrued_out: dict[str, float] | None = None,
) -> tuple[dict[str, float], dict[str, float], dict[str, str], set[str]]:
    """Тот же кортеж, что у fetch_moex_prices, но из готового quotes.json.

    quotes — {secid: Quote.to_dict()} (формат `moex_quotes.py --json`, ключ
    "quotes"); сеть не вызывается. Случай 2026-10-27: per_security_xirr сам
    ходил в MOEX одной попыткой и при сбое молча брал цену последней сделки,
    а holdings шли по котировкам moex_quotes.py — NVTK 342 899,4 ₽ против
    98 892 ₽. Бумаги, которых в quotes нет или у которых нет цены, остаются в
    failed — вызывающий добирает их через fetch_moex_prices.
    """
    from types import SimpleNamespace
    last_prices: dict[str, float] = {}
    face_values: dict[str, float] = {}
    face_currencies: dict[str, str] = {}
    failed: set[str] = set(secids)
    fields = ("last", "prev_close", "face_value", "currency", "settle_currency", "accrued_interest")
    for sid in secids:
        d = (quotes or {}).get(sid)
        if not isinstance(d, dict):
            continue
        q = SimpleNamespace(**{k: d.get(k) for k in fields})
        _absorb_moex_quote(sid, q, last_prices, face_values, face_currencies, failed, accrued_out)
    return last_prices, face_values, face_currencies, failed


def fetch_moex_prices(
    secids: list[str],
    verbose: bool = False,
    accrued_out: dict[str, float] | None = None,
) -> tuple[dict[str, float], dict[str, float], dict[str, str], set[str]]:
    """
    Пытается получить LAST цены + метаданные (FACEVALUE, FACEUNIT) через MOEX ISS.
    Возвращает (last_prices, face_values, face_currencies, failed_secids).

    accrued_out — если передан, заполняется SECID → НКД одной облигации
    В РУБЛЯХ. MOEX ACCRUEDINT номинирован в валюте торгов (CURRENCYID), а не
    номинала: у замещаек на TQCB номинал USD, а НКД уже в рублях (RU000A105146
    12.10.2026: 1923.09 при купоне 28.36 USD) — домножение на курс давало +2,8
    млн ₽ фантомной стоимости. Бумаги с нерублёвой валютой торгов в словарь не
    попадают (оценка остаётся чистой, без догадок). Отдельным out-параметром,
    а не пятым элементом кортежа, чтобы не ломать распаковку у вызывающих.

    face_currencies маппит SECID → 3-буквенный код валюты номинала
    (RUB/USD/EUR/CNY; SUR нормализуется в RUB). Заполняется ДАЖЕ если
    last price отсутствует — это критично для корректного пересчёта
    замещаек в рубли через last_trade_price fallback.

    Если moex_quotes.py недоступен или MOEX недоступен — возвращает пустые
    dict'ы и все secids в failed.
    """
    last_prices: dict[str, float] = {}
    face_values: dict[str, float] = {}
    face_currencies: dict[str, str] = {}
    failed: set[str] = set(secids)
    if not secids:
        return last_prices, face_values, face_currencies, failed

    try:
        # Попробуем найти moex_quotes.py рядом или в skills
        import importlib.util as _ilu
        # Бандл: pack.sh кладёт канон в scripts/ рядом; репо: _shared-references/.
        candidates = [
            Path(__file__).parent / "moex_quotes.py",
            Path(__file__).resolve().parents[3] / "_shared-references" / "moex_quotes.py",
        ]
        module = None
        for p in candidates:
            if p.exists():
                spec = _ilu.spec_from_file_location("moex_quotes", str(p))
                if spec and spec.loader:
                    module = _ilu.module_from_spec(spec)
                    # Нужно зарегистрировать в sys.modules до exec_module
                    # иначе @dataclass внутри модуля не работает
                    sys.modules["moex_quotes"] = module
                    spec.loader.exec_module(module)
                    break
        if module is None:
            if verbose:
                sys.stderr.write("[moex] moex_quotes.py not found; skipping\n")
            return last_prices, face_values, face_currencies, failed

        health = module.health_check()
        if not health.get("ok"):
            if verbose:
                sys.stderr.write(
                    f"[moex] health check failed: {health.get('error')}; "
                    f"will use last trade price fallback\n"
                )
            return last_prices, face_values, face_currencies, failed

        quotes, errs = module.fetch_quotes(
            secids, fields="weekly", parallel=True
        )
        for sid, q in quotes.items():
            # quotes — dict[str, Quote] (dataclass), не dict. Используем атрибуты.
            _absorb_moex_quote(sid, q, last_prices, face_values, face_currencies,
                               failed, accrued_out)

        # Retry для тех, кто ничего не вернул: возможно, discovery-фаза
        # потеряла их при большом батче. Повторяем с явным --type bond
        # (он пропускает discovery и идёт сразу на bond-доску TQCB).
        # Критично для замещаек: если MOEX не вернул currency, они
        # оцениваются как рублёвые → серьёзное искажение стоимости.
        missing = [s for s in secids if s not in face_currencies and s not in last_prices]
        if missing:
            if verbose:
                sys.stderr.write(
                    f"[moex] retry {len(missing)} missing as type=bond: "
                    f"{missing[:5]}{'...' if len(missing) > 5 else ''}\n"
                )
            try:
                quotes2, _errs2 = module.fetch_quotes(
                    missing, fields="weekly", parallel=True, kind_hint="bond"
                )
                for sid, q in quotes2.items():
                    _absorb_moex_quote(sid, q, last_prices, face_values, face_currencies,
                                       failed, accrued_out)
            except TypeError:
                # Старая версия moex_quotes.py без параметра kind_hint —
                # просто пропускаем retry, будет fallback в rate_for.
                if verbose:
                    sys.stderr.write(
                        "[moex] retry skipped: fetch_quotes не поддерживает kind_hint\n"
                    )
            except Exception as e:
                if verbose:
                    sys.stderr.write(f"[moex] retry failed: {e}\n")

        if verbose:
            sys.stderr.write(
                f"[moex] got {len(last_prices)}/{len(secids)} quotes; "
                f"{len(failed)} via fallback; "
                f"{len(face_currencies)} face currencies captured\n"
            )
    except Exception as e:
        if verbose:
            sys.stderr.write(f"[moex] error: {e}; all fallback\n")
    return last_prices, face_values, face_currencies, failed


def estimate_position_value_rub(
    pos: Position,
    inst_type: str,
    last_trade_price: float | None,
    moex_last: float | None,
    moex_face_value: float | None,
    nominal_currency: str | None,
    as_of: dt.date,
    cbr_cache: dict[str, dict[str, float]],
    moex_accrued: float | None = None,
) -> tuple[float, str]:
    """
    Оценивает текущую стоимость позиции в RUB.

    Облигации с ценой MOEX оцениваются ГРЯЗНОЙ стоимостью: + НКД
    (moex_accrued — НКД одной бумаги В РУБЛЯХ, прибавляется после пересчёта
    номинала по курсу; см. fetch_moex_prices). Покупки в trades
    IntelInvest записаны с уплаченным НКД («Сумма»), поэтому чистая
    конечная стоимость систематически занижала XIRR облигаций (на
    БКС-ИИС-3 12.10.2026: −4,7% вместо ≈ +0,7%). Fallback last_trade_price
    НКД не знает и остаётся чистым — это видно по price_source.

    Приоритет:
      1. MOEX ISS (если есть последняя цена)
      2. Last trade price (последняя цена сделки в trades)
      3. Cost basis (pos.total_cost_rub)

    Для облигаций: если цена в % от номинала (100 = par), умножаем на
    номинал. Распознаём по величине: если last < 10 → явно % от номинала;
    если last > 100 → скорее всего номинал 1000 и цена в %.

    ВАЖНО для замещаек: pos.currency = "RUB" (так зафиксировано в IntelInvest —
    пользователь платит рубли), но сам номинал бумаги в USD/EUR/CNY. Чтобы
    корректно пересчитать в рубли, используется nominal_currency из MOEX
    (FACEUNIT). Если nominal_currency задан и отличается от RUB — применяется
    именно он, независимо от pos.currency.
    """
    qty = pos.qty
    if qty <= 1e-9:
        return 0.0, "zero_qty"

    # Определяем эффективную валюту для конвертации в RUB.
    # Для облигаций: приоритет у nominal_currency (из MOEX FACEUNIT) — это
    # единственный надёжный источник для замещаек, где trade-валюта = RUB.
    # Для акций/фондов: используем pos.currency как раньше.
    if inst_type == "bond" and nominal_currency:
        effective_currency = nominal_currency
    else:
        effective_currency = pos.currency
    if effective_currency == "SUR":
        effective_currency = "RUB"

    try:
        rate = rate_for(effective_currency, as_of, cbr_cache) if effective_currency != "RUB" else 1.0
    except RuntimeError:
        # Курса 1.0 нет: стоимость в валюте как в рублях — молчаливая ошибка в ×N. Бумага
        # идёт по стоимости покупки, провал копится в FX_GAPS → блок-проверка сборки.
        _fx_gap("no_rate", effective_currency, as_of, pos.ticker)
        sys.stderr.write(f"[cbr] WARN: нет курса {effective_currency} около {as_of} — {pos.ticker} "
                         "оценена по стоимости покупки; сборка снапшота будет заблокирована\n")
        return pos.total_cost_rub, "fx_missing"

    # 1. MOEX first
    if moex_last is not None:
        if inst_type == "bond":
            # Цена в % от номинала. Номинал обычно 1000 (ОФЗ/корп RUB) или
            # 1000 USD/EUR/CNY (замещайки), иногда 100 (НОВАТЭК1Р2 и др.).
            face = moex_face_value or 1000.0
            value_native = qty * (moex_last / 100.0) * face
        else:
            # Акции/фонды: LAST — это цена 1 бумаги
            value_native = qty * moex_last
        accrued_rub = qty * moex_accrued if (inst_type == "bond" and moex_accrued) else 0.0
        return value_native * rate + accrued_rub, "moex"

    # 2. Last trade price
    if last_trade_price is not None:
        if inst_type == "bond":
            # Цена в trades тоже в % от номинала (для RU000-облигаций)
            # Если есть face из MOEX-метаданных (даже без last) — используем его.
            if moex_face_value:
                face = moex_face_value
            else:
                face = 1000.0  # самое частое значение для MOEX
                if last_trade_price < 10:
                    # Скорее всего цена уже в % от чего-то ОЧЕНЬ маленького
                    face = 100.0
            value_native = qty * (last_trade_price / 100.0) * face
        else:
            value_native = qty * last_trade_price
        return value_native * rate, "last_trade_price"

    # 3. Cost basis (уже в RUB)
    return pos.total_cost_rub, "cost_basis"


def build_market_values(
    positions: dict[tuple[str, str], Position],
    trades: list[Trade],
    trades_by_ticker: dict[str, list[Trade]],
    as_of: dt.date,
    cbr_cache: dict,
    use_moex: bool = True,
    blocked_keys: set[tuple[str, str]] | None = None,
    blocked_tickers: set[str] | None = None,
    blocked_value: str = "zero",  # 'zero' | 'last_trade' | 'cost_basis'
    verbose: bool = False,
    cbr_offline: bool = False,
    bond_meta_out: dict | None = None,
) -> dict[tuple[str, str], dict]:
    """
    Для каждой позиции с qty > 0 возвращает rub-стоимость на as_of
    плюс источник цены.

    bond_meta_out (если передан): {(ticker, cur): {face, face_ccy, accrued_rub}} для облигаций
    с ценой MOEX — из чего сложена их оценка (номинал, валюта номинала, НКД одной бумаги в ₽);
    вьюер по ним пересчитывает стоимость по живой цене (live_basis.positions).

    Для заблокированных (key в blocked_keys) применяет стратегию blocked_value:
      - 'zero':       0 (реалистичная оценка — они не торгуются)
      - 'last_trade': последняя цена сделки (как в IntelInvest)
      - 'cost_basis': стоимость по средней цене покупки
    """
    blocked_keys = blocked_keys or set()
    # PDL-12: страховка от расхождения ключей (ticker, currency) между
    # classify_blocked (валюта сделки) и reconstruct_positions (валюта после
    # merge_cross_currency_positions) — см. unambiguous_blocked_tickers.
    blocked_tickers = blocked_tickers or set()
    active_positions = {k: p for k, p in positions.items() if p.qty > 1e-9}

    # Разделим: которые можно попытаться получить с MOEX — RUB-тикеры и российские бумаги
    # (ISIN RU…), купленные за валюту: юаневые облигации (RU000A108FX8 и др.) без запроса
    # уходили в цену последней сделки — 27.10 три бумаги на 626 тыс. ₽ (PDL-16).
    moex_last: dict[str, float] = {}
    moex_face: dict[str, float] = {}
    moex_face_curr: dict[str, str] = {}
    moex_accrued: dict[str, float] = {}
    if use_moex:
        moex_candidates = [
            tk for (tk, cur), p in active_positions.items()
            if (cur == "RUB" or tk.startswith("RU")) and not p.ticker.startswith("Деньги")
            and "-" not in tk  # исключаем фьючерсы
            and (tk, cur) not in blocked_keys  # заблокированные тоже не запрашиваем
        ]
        moex_candidates = list(dict.fromkeys(moex_candidates))   # тикер в двух валютах — один запрос
        if moex_candidates:
            ml, mf, mfc, _failed = fetch_moex_prices(
                moex_candidates, verbose=verbose, accrued_out=moex_accrued,
            )
            moex_last.update(ml)
            moex_face.update(mf)
            moex_face_curr.update(mfc)

    # Догружаем CBR-курсы на as_of для всех валют номинала, которые MOEX
    # вернул для активных позиций. Это критично для замещаек: в кеше после
    # convert_trades_to_rub лежат только даты, по которым были сделки;
    # если у пользователя нет свежих EUR/USD/CNY сделок, rate_for(as_of) упадёт
    # в RuntimeError и fallback на rate=1.0 — итог: FX-облигация оценивается
    # как рублёвая. См. регресс-тест tests/test_fx_bond_valuation.py.
    nominal_currencies_needed = {
        cur for cur in moex_face_curr.values()
        if cur and cur not in ("RUB", "SUR")
    }
    # Добавляем валюты из fallback-реестра замещаек, которые есть
    # в активных позициях, но MOEX не вернул FACEUNIT
    for (ticker, _), pos in active_positions.items():
        if ticker in KNOWN_FX_BONDS and not moex_face_curr.get(ticker):
            nominal_currencies_needed.add(KNOWN_FX_BONDS[ticker])
    HELD_FX_CURRENCIES.update(nominal_currencies_needed)
    HELD_FX_CURRENCIES.update(
        c for (_t, c) in active_positions if _is_foreign(c))
    if cbr_offline:
        # Офлайн: в ЦБ только за тем, чего кэш не даёт (rate_for ±30 дней). Иначе
        # rate_for ниже упадёт и замещайка уйдёт в rate=1.0 — оценка как рублёвой.
        nominal_currencies_needed = {c for c in nominal_currencies_needed
                                     if not _cached_rate_ok(c, as_of, cbr_cache)}
    if nominal_currencies_needed:
        # Буфер ±5 дней для выходных / праздников
        buffer_dates = {
            as_of + dt.timedelta(days=d) for d in range(-5, 3)
        }
        currencies_dates = {cur: buffer_dates for cur in nominal_currencies_needed}
        try:
            ensure_cbr_rates(currencies_dates, cbr_cache, verbose=verbose)
        except Exception as e:
            if verbose:
                sys.stderr.write(
                    f"[cbr] WARN: failed to ensure rates for "
                    f"{nominal_currencies_needed} at {as_of}: {e}\n"
                )

    result: dict[tuple[str, str], dict] = {}
    for key, pos in active_positions.items():
        ticker, cur = key
        inst_type = classify_instrument_type(trades_by_ticker.get(ticker, []))
        is_blocked = key in blocked_keys or ticker in blocked_tickers

        if is_blocked:
            if blocked_value == "zero":
                value_rub = 0.0
                src = "blocked_zero"
            elif blocked_value == "cost_basis":
                value_rub = pos.total_cost_rub
                src = "blocked_cost_basis"
            else:  # last_trade
                last_tp = last_known_trade_price(ticker, cur, trades, as_of)
                value_rub, src = estimate_position_value_rub(
                    pos, inst_type, last_tp, None, None, None, as_of, cbr_cache
                )
                src = f"blocked_{src}"
        else:
            last_tp = last_known_trade_price(ticker, cur, trades, as_of)
            mlast = moex_last.get(ticker)
            mface = moex_face.get(ticker)
            mface_curr = moex_face_curr.get(ticker)

            # Fallback: если MOEX не вернул FACEUNIT (discovery-фаза упала
            # или MOEX полностью недоступен), смотрим в статический реестр
            # KNOWN_FX_BONDS. Номинальная валюта замещайки — неизменяемая
            # характеристика, её можно зашить.
            if inst_type == "bond" and not mface_curr and ticker in KNOWN_FX_BONDS:
                mface_curr = KNOWN_FX_BONDS[ticker]
                # Для face оставляем 1000 по умолчанию (замещайки всегда
                # имеют номинал 1000 валюты) — estimate_position_value_rub
                # применит это корректно.
                if not mface:
                    mface = 1000.0
                if verbose:
                    sys.stderr.write(
                        f"[fx-fallback] {ticker}: MOEX без FACEUNIT, "
                        f"использую реестр KNOWN_FX_BONDS → {mface_curr}\n"
                    )

            value_rub, src = estimate_position_value_rub(
                pos, inst_type, last_tp, mlast, mface, mface_curr, as_of, cbr_cache,
                moex_accrued=moex_accrued.get(ticker) if inst_type == "bond" else None,
            )
            # Помечаем источник, если сработал fallback
            if inst_type == "bond" and ticker in KNOWN_FX_BONDS \
               and not moex_face_curr.get(ticker):
                src = f"{src}+fx_registry"
            if bond_meta_out is not None and inst_type == "bond" and mlast is not None:
                ccy = mface_curr or cur
                bond_meta_out[key] = {
                    "face": float(mface or 1000.0),
                    "face_ccy": "RUB" if ccy == "SUR" else ccy,
                    "accrued_rub": float(moex_accrued.get(ticker) or 0.0),
                }

        result[key] = {
            "ticker": ticker,
            "currency": cur,
            "nominal_currency": (
                moex_face_curr.get(ticker)
                or (KNOWN_FX_BONDS.get(ticker) if inst_type == "bond" else None)
                or cur
            ),
            "name": pos.name,
            "type": inst_type,
            "qty": pos.qty,
            "cost_basis_rub": pos.total_cost_rub,
            # Средняя цена 1 бумаги по сделкам (WACC после сплитов/корректировок) —
            # для сверки «Общий баланс vs расчёт по сделкам» (reconciliation.balance_vs_trades)
            "avg_cost_rub": (
                pos.avg_cost_rub if pos.avg_cost_rub
                else (pos.total_cost_rub / pos.qty if pos.qty > 1e-9 else 0.0)
            ),
            "value_rub": value_rub,
            "price_source": src,
        }
    return result


# =============================================================================
# IX. Per-type подпортфель: cashflows и метрики
# =============================================================================


def subportfolio_cashflows(
    trades: list[Trade],
    trades_by_ticker: dict[str, list[Trade]],
    type_filter: set[str],
    start_date: dt.date,
    end_date: dt.date,
    excluded_keys: set[tuple[str, str]] | None = None,
) -> list[tuple[dt.date, float]]:
    """
    Возвращает cashflows подпортфеля выбранных типов (stock/bond/fund/...).

    Convention для XIRR:
      отрицательный cf = отток из "инвестора" в подпортфель (покупка)
      положительный cf = приток инвестору (продажа, купон, дивиденд, амортизация)

    Не включает:
      - начальную стоимость (она добавляется вызывающим кодом)
      - конечную стоимость (market_value, тоже вызывающим)
      - заблокированные позиции, если excluded_keys заданы
    """
    excluded_keys = excluded_keys or set()
    cfs: list[tuple[dt.date, float]] = []
    for t in trades:
        if t.date < start_date or t.date > end_date:
            continue
        if t.ticker.startswith("Деньги"):
            continue
        key = (t.ticker, t.currency)
        if key in excluded_keys:
            continue
        inst_type = classify_instrument_type(
            trades_by_ticker.get(t.ticker, [])
        )
        if type_filter and inst_type not in type_filter:
            continue

        op = t.operation
        if op == "Покупка":
            cfs.append((t.date, -abs(t.rub_amount)))
        elif op == "Продажа":
            cfs.append((t.date, +abs(t.rub_amount)))
        elif op in ("Купон", "Дивиденд", "Амортизация"):
            cfs.append((t.date, +abs(t.rub_amount)))
    return cfs


def subportfolio_metrics(
    trades: list[Trade],
    trades_by_ticker: dict[str, list[Trade]],
    type_filter: set[str],
    start_date: dt.date,
    end_date: dt.date,
    start_positions: dict[tuple[str, str], Position],
    end_market_values: dict[tuple[str, str], dict],
    excluded_keys: set[tuple[str, str]] | None = None,
) -> dict:
    """
    Считает XIRR, ROI, TWR (Modified Dietz) для подпортфеля заданных типов.
    """
    excluded_keys = excluded_keys or set()

    # Стартовое значение подпортфеля — cost basis позиций типов в start_positions
    initial_value = 0.0
    for key, pos in start_positions.items():
        if key in excluded_keys:
            continue
        if pos.qty <= 1e-9:
            continue
        inst_type = classify_instrument_type(
            trades_by_ticker.get(pos.ticker, [])
        )
        if type_filter and inst_type not in type_filter:
            continue
        initial_value += pos.total_cost_rub

    # Конечное значение — market value позиций типов
    end_value = 0.0
    for key, mv in end_market_values.items():
        if key in excluded_keys:
            continue
        if type_filter and mv["type"] not in type_filter:
            continue
        end_value += mv["value_rub"]

    # Внутренние cashflows подпортфеля
    sub_cfs = subportfolio_cashflows(
        trades, trades_by_ticker, type_filter,
        start_date, end_date, excluded_keys,
    )

    # Полученные купоны и дивиденды (для отчёта — информационно)
    received_coupons = sum(
        t.rub_amount for t in trades
        if t.operation == "Купон"
        and start_date <= t.date <= end_date
        and (t.ticker, t.currency) not in excluded_keys
        and (not type_filter or classify_instrument_type(
            trades_by_ticker.get(t.ticker, [])) in type_filter)
    )
    received_dividends = sum(
        t.rub_amount for t in trades
        if t.operation == "Дивиденд"
        and start_date <= t.date <= end_date
        and (t.ticker, t.currency) not in excluded_keys
        and (not type_filter or classify_instrument_type(
            trades_by_ticker.get(t.ticker, [])) in type_filter)
    )

    # XIRR: -initial_value на start, внутренние cf, +end_value на end
    xirr_cfs = [(start_date, -initial_value)] if initial_value > 0 else []
    xirr_cfs.extend(sub_cfs)
    xirr_cfs.append((end_date, end_value))
    xirr_val = xirr(xirr_cfs) if len(xirr_cfs) >= 2 else None
    live_flows = xirr_cfs[:-1] if len(xirr_cfs) >= 2 else []    # те же потоки без конечной стоимости

    # ROI: (end - initial - net_cf) / (initial + net_buys)
    # net_cf = сумма всех cashflows подпортфеля (положительные — выход, отриц — вход)
    net_cf = sum(c[1] for c in sub_cfs)
    net_buys = -sum(c[1] for c in sub_cfs if c[1] < 0)  # |покупки|
    pnl = end_value - initial_value - (-net_cf)  # pnl = end - initial + (net cash from subport)
    # ROI определяем как pnl / invested, где invested = initial + new buys
    invested = initial_value + net_buys
    roi = pnl / invested if invested > 0 else None

    # TWR Dietz
    period_days = (end_date - start_date).days
    twr_dietz = None
    twr_annualized = None
    if period_days > 0 and initial_value > 0:
        weighted_cf = 0.0
        for d, amt in sub_cfs:
            # Convention для Dietz: amt с тем же знаком что и XIRR cf
            # (покупка в подпортфель = новый взнос, +; продажа/купон = выход, -)
            # Наш XIRR-convention: покупка -, выход +. Переворачиваем.
            w = (end_date - d).days / period_days
            weighted_cf += -amt * w  # переворот
        # net_cf с точки зрения Dietz (новые деньги в подпортфель, положит.)
        net_cf_dietz = -net_cf  # с учётом знака
        denom = initial_value + weighted_cf
        if abs(denom) > 1e-9:
            twr_dietz = (end_value - initial_value - net_cf_dietz) / denom
            years = period_days / 365.25
            if years > 0:
                try:
                    twr_annualized = (1 + twr_dietz) ** (1 / years) - 1
                except (ValueError, OverflowError):
                    pass

    return {
        "_live_flows": live_flows,      # служебное: build_report убирает его в live_basis.flows_by_type
        "types": sorted(type_filter) if type_filter else ["all"],
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "years": round(period_days / 365.25, 2),
        "initial_value_rub": round(initial_value, 2),
        "end_value_rub": round(end_value, 2),
        "net_inflow_rub": round(-net_cf, 2),
        "n_subport_cashflows": len(sub_cfs),
        "received_coupons_rub": round(received_coupons, 2),
        "received_dividends_rub": round(received_dividends, 2),
        "pnl_rub": round(pnl, 2),
        "xirr": round(xirr_val, 4) if xirr_val is not None else None,
        "xirr_pct": f"{xirr_val*100:.2f}%" if xirr_val is not None else None,
        "roi": round(roi, 4) if roi is not None else None,
        "roi_pct": f"{roi*100:.2f}%" if roi is not None else None,
        "twr_dietz_period": round(twr_dietz, 4) if twr_dietz is not None else None,
        "twr_dietz_annualized": (
            round(twr_annualized, 4) if twr_annualized is not None else None
        ),
        "twr_dietz_annualized_pct": (
            f"{twr_annualized*100:.2f}%" if twr_annualized is not None else None
        ),
    }



# =============================================================================
# IX-b. Бенчмарк-гейт (PME) — «те же потоки, но в бенчмарк»
# =============================================================================
# Ретро-разбор 2026-07 показал: проигрыш бенчмарку был виден только через
# годы ручного анализа. Гейт считает Public-Market-Equivalent на ТЕХ ЖЕ
# потоках и конвенциях, что subportfolio_metrics (start = cost basis на
# 2022-03-01, внутренние cf, терминал на as_of):
#   акции     → MCFTR (индекс Мосбиржи полной доходности, с дивидендами)
#   облигации → вклад по КС − 1 пп (ежедневная капитализация)
# Серии инжектируются (тестируемо офлайн); сеть — best-effort, при сбое
# блок None + флаг, отчёт не падает.

BENCH_DEPOSIT_SPREAD_PP = 1.0


def _ssl_context():
    """SSL-контекст с certifi-бандлом, если доступен (macOS без системных CA)."""
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def fetch_key_rate_history(
    from_date: dt.date, to_date: dt.date, timeout: int = 20,
) -> list[tuple[str, float]] | None:
    """История КС ЦБ (рабочие дни) через DailyInfoWebServ SOAP. None при сбое."""
    body = f"""<?xml version="1.0" encoding="utf-8"?>
<soap12:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">
  <soap12:Body>
    <KeyRate xmlns="http://web.cbr.ru/">
      <fromDate>{from_date.isoformat()}</fromDate>
      <ToDate>{to_date.isoformat()}</ToDate>
    </KeyRate>
  </soap12:Body>
</soap12:Envelope>"""
    try:
        import xml.etree.ElementTree as ET
        req = urllib.request.Request(
            "https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx",
            data=body.encode(),
            headers={"Content-Type": "application/soap+xml; charset=utf-8"},
        )
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:
            root = ET.fromstring(r.read().decode())
        rates = []
        for kr in root.iter():
            if kr.tag.endswith("KR"):
                d = kr.find("DT").text[:10]
                rates.append((d, float(kr.find("Rate").text)))
        rates.sort()
        return rates or None
    except Exception:
        return None


def fetch_index_history(
    from_date: dt.date, to_date: dt.date, secid: str = "MCFTR", timeout: int = 20,
) -> list[tuple[str, float]] | None:
    """Дневные закрытия индекса через MOEX ISS (с пагинацией). None при сбое."""
    try:
        rows: list[tuple[str, float]] = []
        start = 0
        while True:
            url = (f"https://iss.moex.com/iss/history/engines/stock/markets/index/"
                   f"securities/{secid}.json?from={from_date.isoformat()}"
                   f"&till={to_date.isoformat()}&start={start}"
                   f"&iss.meta=off&history.columns=TRADEDATE,CLOSE")
            with urllib.request.urlopen(url, timeout=timeout, context=_ssl_context()) as r:
                batch = json.load(r)["history"]["data"]
            if not batch:
                break
            rows.extend((d, c) for d, c in batch if c is not None)
            start += len(batch)
            if len(batch) < 100:
                break
        return rows or None
    except Exception:
        return None


def _rate_lookup(series: list[tuple[str, float]]):
    """date → ставка (forward-fill по календарным дням до 30 дней назад)."""
    m = dict(series)
    def look(d: dt.date) -> float | None:
        for back in range(31):
            v = m.get((d - dt.timedelta(days=back)).isoformat())
            if v is not None:
                return v
        return None
    return look


def _index_lookup(series: list[tuple[str, float]]):
    """date → close: 'next' (первый торговый день >= d) / 'prev' (<= d)."""
    dates = [d for d, _ in series]
    closes = dict(series)
    def look(d: dt.date, direction: str = "next") -> float | None:
        iso = d.isoformat()
        if direction == "next":
            for x in dates:
                if x >= iso:
                    return closes[x]
            return closes[dates[-1]] if dates else None
        for x in reversed(dates):
            if x <= iso:
                return closes[x]
        return None
    return look


def replay_deposit_pme(
    initial_value: float,
    start_date: dt.date,
    flows: list[tuple[dt.date, float]],
    end_date: dt.date,
    rate_look,
    spread_pp: float = BENCH_DEPOSIT_SPREAD_PP,
) -> tuple[float, bool]:
    """Вклад по (КС − spread): initial на start, входы/выходы по знаковой
    конвенции subportfolio_cashflows (cf < 0 = вход в стратегию на |cf|,
    cf > 0 = вывод). Возвращает (терминал, баланс уходил в минус)."""
    events: dict[dt.date, float] = defaultdict(float)
    events[start_date] += initial_value
    for d, cf in flows:
        events[d] += -cf
    bal = 0.0
    went_negative = False
    d = start_date
    while d <= end_date:
        if d != start_date:
            rate = rate_look(d)
            if rate is not None and bal > 0:
                bal *= 1 + max(rate - spread_pp, 0.1) / 100 / 365
        bal += events.get(d, 0.0)
        if bal < -1e-6:
            went_negative = True
        d += dt.timedelta(days=1)
    return bal, went_negative


def replay_index_pme(
    initial_value: float,
    start_date: dt.date,
    flows: list[tuple[dt.date, float]],
    end_date: dt.date,
    index_look,
) -> tuple[float, bool] | None:
    """Классический PME (Long-Nickels): вход покупает юниты индекса по
    ближайшему следующему закрытию, выход продаёт на ту же сумму в рублях.
    Юниты могут уйти в минус (выходы больше накопленного) — флагуется."""
    px0 = index_look(start_date, "next")
    if px0 is None:
        return None
    units = initial_value / px0
    went_negative = False
    for d, cf in sorted(flows, key=lambda x: x[0]):
        px = index_look(d, "next")
        if px is None:
            continue
        units += (-cf) / px
        if units < -1e-12:
            went_negative = True
    px_end = index_look(end_date, "prev")
    if px_end is None:
        return None
    return units * px_end, went_negative


def compute_benchmarks(
    trades: list[Trade],
    trades_by_ticker: dict[str, list[Trade]],
    start_date: dt.date,
    as_of: dt.date,
    per_type_reports: dict[str, dict],
    all_blocked: set[tuple[str, str]],
    key_rate_series: list[tuple[str, float]] | None,
    index_series: list[tuple[str, float]] | None,
) -> dict:
    """Блок benchmarks_restricted: stock vs MCFTR, bond vs вклад КС−1.
    actual_* копируется из per_type_reports (та же математика), bench_* —
    реплей тех же потоков в бенчмарк."""
    out: dict[str, Any] = {
        "note": ("PME: те же потоки и конвенции, что returns_by_type_restricted "
                 f"(start {start_date} по cost basis). stock → MCFTR (полная доходность), "
                 f"bond → вклад КС − {BENCH_DEPOSIT_SPREAD_PP:g} пп."),
        "window": {"start": start_date.isoformat(), "end": as_of.isoformat()},
        "flags": [],
    }

    def one(ptype: str, bench_name: str, replay) -> dict | None:
        m = per_type_reports.get(ptype) or {}
        initial = m.get("initial_value_rub")
        actual_end = m.get("end_value_rub")
        actual_xirr = m.get("xirr")
        if initial is None or actual_end is None:
            return None
        flows = subportfolio_cashflows(
            trades, trades_by_ticker, {ptype}, start_date, as_of, all_blocked,
        )
        res = replay(initial, flows)
        if res is None:
            return None
        bench_end, went_negative = res
        cfs = ([(start_date, -initial)] if initial > 0 else []) + flows
        bench_xirr = xirr(cfs + [(as_of, bench_end)])
        gap = (round((actual_xirr - bench_xirr) * 100, 2)
               if actual_xirr is not None and bench_xirr is not None else None)
        if went_negative:
            out["flags"].append(
                f"{ptype}: реплей-баланс бенчмарка уходил в минус (выходы > накопленного) — PME-условность")
        return {
            "benchmark": bench_name,
            "actual_xirr": actual_xirr,
            "bench_xirr": round(bench_xirr, 4) if bench_xirr is not None else None,
            "gap_pp": gap,
            "actual_terminal_rub": actual_end,
            "bench_terminal_rub": round(bench_end, 2),
        }

    if index_series:
        ilook = _index_lookup(index_series)
        out["stock_vs_mcftr"] = one(
            "stock", "MCFTR",
            lambda init, fl: replay_index_pme(init, start_date, fl, as_of, ilook))
    else:
        out["stock_vs_mcftr"] = None
        out["flags"].append("MCFTR: история индекса недоступна (MOEX ISS)")

    if key_rate_series:
        rlook = _rate_lookup(key_rate_series)
        out["bond_vs_deposit"] = one(
            "bond", f"вклад КС−{BENCH_DEPOSIT_SPREAD_PP:g}пп",
            lambda init, fl: replay_deposit_pme(init, start_date, fl, as_of, rlook))
    else:
        out["bond_vs_deposit"] = None
        out["flags"].append("КС: история ставки недоступна (ЦБ SOAP)")

    out["sources"] = {
        "key_rate_points": len(key_rate_series) if key_rate_series else 0,
        "index_points": len(index_series) if index_series else 0,
    }
    return out


# =============================================================================
# X. Отчёт по режимам
# =============================================================================


def build_report(
    trades: list[Trade],
    corrections_log: list[dict],
    as_of: dt.date | None = None,
    start_date: dt.date | None = None,
    use_moex: bool = True,
    blocked_value: str = "zero",
    verbose: bool = False,
    with_benchmarks: bool = True,
    cbr_offline: bool = False,
) -> dict:
    """
    Главная функция: строит отчёт о доходности.

    cbr_offline=True — в ЦБ РФ не ходим вовсе: курсы номинала замещаек только из
    кэша, история КС для бенчмарка не запрашивается (блок вклада — null с флагами).
    До 2026-10-21 флаг сюда не передавался, и два запроса шли в обход --cbr-offline:
    при недоступном cbr.ru (VPN) шаг ждал таймауты ≈5 мин.

    Больше не требует common.xlsx — текущая стоимость получается
    из trades + MOEX ISS + fallback на last trade price.

    Параметры:
      as_of        — дата, на которую считаем (default: today)
      start_date   — старт "ограниченного" режима (default: 2022-03-01)
      use_moex     — пытаться ли запрашивать MOEX ISS (default: True)
    """
    if as_of is None:
        as_of = dt.date.today()
    if start_date is None:
        start_date = BLOCKING_CUTOFF
    today = as_of

    cbr_cache = load_cbr_cache()

    # Группировка trades по тикеру (для classify_instrument_type и для
    # classify_blocked, и для market prices)
    trades_by_ticker: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        if not t.ticker.startswith("Деньги"):
            trades_by_ticker[t.ticker].append(t)

    # Классификация заблокированных
    blocked_map = classify_blocked(trades)
    all_blocked: set[tuple[str, str]] = set()
    for pairs in blocked_map.values():
        all_blocked.update(pairs)
    # PDL-12: тикеры, заблокированные во ВСЕХ своих валютах — по ним пометка
    # переживает приведение позиции к рублю (см. unambiguous_blocked_tickers).
    all_blocked_tickers = unambiguous_blocked_tickers(trades, all_blocked)

    # === Реконструкция позиций на начало периода (start_date - 1 день) ===
    snapshot_date = start_date - dt.timedelta(days=1)
    positions_at_start = reconstruct_positions(trades, as_of=snapshot_date)

    snapshot_positions_list: list[dict] = []
    snapshot_blocked_list: list[dict] = []
    snapshot_total_excl_blocked = 0.0
    snapshot_blocked_total = 0.0
    snapshot_by_type: dict[str, float] = defaultdict(float)
    snapshot_blocked_by_type: dict[str, float] = defaultdict(float)

    for key, pos in positions_at_start.items():
        if pos.qty <= 1e-9:
            continue
        inst_type = classify_instrument_type(
            trades_by_ticker.get(pos.ticker, [])
        )
        entry = {
            "ticker": pos.ticker,
            "currency": pos.currency,
            "name": pos.name,
            "type": inst_type,
            "qty": round(pos.qty, 6),
            "cost_basis_rub": round(pos.total_cost_rub, 2),
            "is_blocked": key in all_blocked,
        }
        if key in all_blocked:
            snapshot_blocked_list.append(entry)
            snapshot_blocked_total += pos.total_cost_rub
            snapshot_blocked_by_type[inst_type] += pos.total_cost_rub
        else:
            snapshot_positions_list.append(entry)
            snapshot_total_excl_blocked += pos.total_cost_rub
            snapshot_by_type[inst_type] += pos.total_cost_rub

    snapshot_positions_list.sort(key=lambda x: -x["cost_basis_rub"])
    snapshot_blocked_list.sort(key=lambda x: -x["cost_basis_rub"])

    # Cash на начало периода
    cash_start = reconstruct_cash_balances(trades, as_of=snapshot_date)
    cash_start_rub = cash_balance_rub(cash_start, snapshot_date, cbr_cache)

    # === Реконструкция позиций на as_of ===
    positions_now = reconstruct_positions(trades, as_of=as_of)

    # Market values на as_of
    if verbose:
        sys.stderr.write(f"[market] Building market values for {as_of}...\n")
    bond_meta: dict = {}
    market_values = build_market_values(
        positions_now, trades, trades_by_ticker, as_of, cbr_cache,
        use_moex=use_moex, blocked_keys=all_blocked,
        blocked_tickers=all_blocked_tickers,
        blocked_value=blocked_value, verbose=verbose, cbr_offline=cbr_offline,
        bond_meta_out=bond_meta,
    )

    # Cash на as_of
    cash_now = reconstruct_cash_balances(trades, as_of=as_of)
    cash_now_rub = cash_balance_rub(cash_now, as_of, cbr_cache)

    current_total_rub = sum(mv["value_rub"] for mv in market_values.values())
    current_total_excl_blocked_rub = sum(
        mv["value_rub"] for k, mv in market_values.items()
        if k not in all_blocked and mv["ticker"] not in all_blocked_tickers
    )
    current_blocked_rub = current_total_rub - current_total_excl_blocked_rub

    # Плюс cash
    current_total_rub += cash_now_rub
    current_total_excl_blocked_rub += cash_now_rub

    # Breakdown по типам
    current_by_type: dict[str, float] = defaultdict(float)
    current_by_type_excl_blocked: dict[str, float] = defaultdict(float)
    for key, mv in market_values.items():
        current_by_type[mv["type"]] += mv["value_rub"]
        if key not in all_blocked and mv["ticker"] not in all_blocked_tickers:
            current_by_type_excl_blocked[mv["type"]] += mv["value_rub"]
    current_by_type["cash"] = cash_now_rub
    current_by_type_excl_blocked["cash"] = cash_now_rub

    # Источники цен (для прозрачности)
    price_sources = defaultdict(int)
    for mv in market_values.values():
        price_sources[mv["price_source"]] += 1

    # === External cashflows (по инварианту) ===
    cf_all = extract_cashflows_by_invariant(trades, end_date=as_of)
    first_trade_date = min(t.date for t in trades)

    # === TOTAL режим: вся история, включая заблокированные ===
    xirr_cfs_total = [(cf.date, -cf.amount_rub) for cf in cf_all]
    xirr_cfs_total.append((today, current_total_rub))
    xirr_total = xirr(xirr_cfs_total)

    net_deposits_total = sum(cf.amount_rub for cf in cf_all)
    pnl_total = current_total_rub - net_deposits_total
    roi_total = pnl_total / net_deposits_total if net_deposits_total > 0 else None
    years_total = (today - first_trade_date).days / 365.25

    # TWR total (Dietz)
    first_deposit = next((cf for cf in cf_all if cf.amount_rub > 0), None)
    twr_total_annualized = None
    if first_deposit:
        mv_start_total = first_deposit.amount_rub
        cf_after_first = [cf for cf in cf_all if cf.date > first_deposit.date]
        period_days = (today - first_deposit.date).days
        if period_days > 0 and mv_start_total > 0:
            weighted = 0.0
            for cf in cf_after_first:
                w = (today - cf.date).days / period_days
                weighted += w * cf.amount_rub
            net_cf = sum(cf.amount_rub for cf in cf_after_first)
            denom = mv_start_total + weighted
            if abs(denom) > 1e-9:
                tot = (current_total_rub - mv_start_total - net_cf) / denom
                yrs = period_days / 365.25
                try:
                    twr_total_annualized = (1 + tot) ** (1 / yrs) - 1
                except (ValueError, OverflowError):
                    pass

    total_coupons_all = sum(t.rub_amount for t in trades
                            if t.operation == "Купон" and t.date <= as_of)
    total_dividends_all = sum(t.rub_amount for t in trades
                              if t.operation == "Дивиденд" and t.date <= as_of)

    # === RESTRICTED режим: с start_date, без заблокированных ===
    cf_restricted = extract_cashflows_by_invariant(
        trades, start_date=start_date, end_date=as_of
    )
    # Для чистоты: исключаем из internal сделки по заблокированным
    # (их обычно после 01.03.2022 нет, но на всякий случай)
    cf_restricted_clean = _cashflows_excluding_keys(
        trades, start_date, as_of, all_blocked
    )

    initial_value_restricted = snapshot_total_excl_blocked + cash_start_rub

    xirr_cfs_r = [(snapshot_date, -initial_value_restricted)]
    xirr_cfs_r.extend((cf.date, -cf.amount_rub) for cf in cf_restricted_clean)
    xirr_cfs_r.append((today, current_total_excl_blocked_rub))
    xirr_restricted = xirr(xirr_cfs_r)

    net_deposits_restricted = sum(cf.amount_rub for cf in cf_restricted_clean)
    pnl_restricted = (
        current_total_excl_blocked_rub - initial_value_restricted - net_deposits_restricted
    )
    invested_restricted = initial_value_restricted + max(net_deposits_restricted, 0)
    roi_restricted = (
        pnl_restricted / invested_restricted if invested_restricted > 0 else None
    )
    years_restricted = (today - snapshot_date).days / 365.25

    # TWR restricted (Dietz)
    period_days_r = (today - snapshot_date).days
    twr_restricted_annualized = None
    if period_days_r > 0 and initial_value_restricted > 0:
        weighted = 0.0
        for cf in cf_restricted_clean:
            w = (today - cf.date).days / period_days_r
            weighted += w * cf.amount_rub
        net_cf = sum(cf.amount_rub for cf in cf_restricted_clean)
        denom = initial_value_restricted + weighted
        if abs(denom) > 1e-9:
            t_r = (current_total_excl_blocked_rub - initial_value_restricted - net_cf) / denom
            yrs = period_days_r / 365.25
            try:
                twr_restricted_annualized = (1 + t_r) ** (1 / yrs) - 1
            except (ValueError, OverflowError):
                pass

    total_coupons_restricted = sum(
        t.rub_amount for t in trades
        if t.operation == "Купон" and start_date <= t.date <= as_of
        and (t.ticker, t.currency) not in all_blocked
    )
    total_dividends_restricted = sum(
        t.rub_amount for t in trades
        if t.operation == "Дивиденд" and start_date <= t.date <= as_of
        and (t.ticker, t.currency) not in all_blocked
    )

    # === Per-type подпортфели с start_date (stock / bond / fund / other) ===
    per_type_reports: dict[str, dict] = {}
    for ptype in ("stock", "bond", "fund", "other"):
        per_type_reports[ptype] = subportfolio_metrics(
            trades, trades_by_ticker, {ptype},
            start_date, as_of,
            positions_at_start, market_values,
            excluded_keys=all_blocked,
        )
    flows_by_type = {pt: r.pop("_live_flows") for pt, r in per_type_reports.items()}

    # === Бенчмарк-гейт (PME): факт vs бенчмарк на тех же потоках ===
    benchmarks = None
    if with_benchmarks:
        if verbose:
            sys.stderr.write("[bench] Fetching KeyRate (CBR) + MCFTR (MOEX ISS)...\n")
        kr_series = None if cbr_offline else fetch_key_rate_history(start_date, as_of)
        idx_series = fetch_index_history(start_date, as_of)
        benchmarks = compute_benchmarks(
            trades, trades_by_ticker, start_date, as_of,
            per_type_reports, all_blocked, kr_series, idx_series,
        )

    # === Сборка отчёта ===
    return {
        "generated_at": time_msk.now_iso(),
        "parameters": {
            "as_of": as_of.isoformat(),
            "start_date": start_date.isoformat(),
            "use_moex": use_moex,
            "trades_count": len(trades),
            "first_trade": first_trade_date.isoformat(),
            # Облигации с ценой MOEX — цена + НКД (с 2026-10-12; раньше чистая,
            # XIRR облигаций был занижен). Снапшоты без поля — "clean".
            "bond_value_basis": "dirty",
        },
        "corrections_applied": corrections_log,
        "blocked_positions": {
            reason: [{"ticker": tk, "currency": cu} for tk, cu in sorted(pairs)]
            for reason, pairs in blocked_map.items()
        },
        "blocked_count": sum(len(s) for s in blocked_map.values()),
        "price_sources_summary": dict(price_sources),
        "snapshot_start": {
            "as_of": snapshot_date.isoformat(),
            "method": "cost_basis (weighted average buy price in RUB, "
                      "converted via CBR rates at trade date)",
            "cash_balance_rub": round(cash_start_rub, 2),
            "total_cost_basis_rub_excl_blocked": round(snapshot_total_excl_blocked, 2),
            "total_cost_basis_rub_blocked_only": round(snapshot_blocked_total, 2),
            "grand_total_with_cash_excl_blocked": round(initial_value_restricted, 2),
            "breakdown_by_type_excl_blocked": {
                k: round(v, 2) for k, v in snapshot_by_type.items()
            },
            "breakdown_by_type_blocked": {
                k: round(v, 2) for k, v in snapshot_blocked_by_type.items()
            },
            "positions_included": snapshot_positions_list,
            "positions_blocked_excluded": snapshot_blocked_list,
        },
        # Живая доходность во вьюере (2026-10-23): потоки XIRR без конечной стоимости + из чего она
        # сложена. Вьюер подставляет живые цены MOEX акций и фондов, решает то же уравнение и видит
        # доходность на сегодня; на ценах снапшота обязан получить ровно returns_total/restricted.xirr
        # (сторож — tests/test_live_basis.py). Облигации и заблокированные — по оценке снапшота.
        "live_basis": _live_basis(xirr_cfs_total[:-1], xirr_cfs_r[:-1], market_values,
                                  all_blocked, all_blocked_tickers, cash_now_rub, today,
                                  flows_by_type=flows_by_type, bond_meta=bond_meta),
        "snapshot_current": {
            "as_of": as_of.isoformat(),
            "cash_balance_rub": round(cash_now_rub, 2),
            "cash_by_currency": {k: round(v, 4) for k, v in cash_now.items()},
            "total_value_rub": round(current_total_rub, 2),
            "total_value_rub_excl_blocked": round(current_total_excl_blocked_rub, 2),
            "blocked_value_rub": round(current_blocked_rub, 2),
            "breakdown_by_type": {
                k: round(v, 2) for k, v in current_by_type.items()
            },
            "breakdown_by_type_excl_blocked": {
                k: round(v, 2) for k, v in current_by_type_excl_blocked.items()
            },
            "positions": sorted(
                [
                    {**mv, "value_rub": round(mv["value_rub"], 2),
                     "cost_basis_rub": round(mv["cost_basis_rub"], 2),
                     "avg_cost_rub": round(mv.get("avg_cost_rub") or 0.0, 4),
                     "qty": round(mv["qty"], 6),
                     "is_blocked": ((mv["ticker"], mv["currency"]) in all_blocked
                                    or mv["ticker"] in all_blocked_tickers)}
                    for mv in market_values.values()
                ],
                key=lambda x: -x["value_rub"],
            ),
        },
        "returns_total": {
            "description": ("Вся история портфеля с первой операции. Заблокированные "
                            "иностранные бумаги оцениваются " + {
                                "zero": "в 0 ₽ (консервативно: как если бы потеряны целиком).",
                                "cost_basis": "по цене покупки.",
                                "last_trade": "по последней известной цене сделки "
                                              "(замороженная бумажная стоимость).",
                            }.get(blocked_value, f"в режиме {blocked_value}.")),
            "period_start": first_trade_date.isoformat(),
            "period_end": today.isoformat(),
            "years": round(years_total, 2),
            "net_external_deposits_rub": round(net_deposits_total, 2),
            "current_value_rub": round(current_total_rub, 2),
            "pnl_rub": round(pnl_total, 2),
            "received_coupons_rub": round(total_coupons_all, 2),
            "received_dividends_rub": round(total_dividends_all, 2),
            "xirr": round(xirr_total, 4) if xirr_total is not None else None,
            "xirr_pct": (
                f"{xirr_total*100:.2f}%" if xirr_total is not None else None
            ),
            "roi": round(roi_total, 4) if roi_total is not None else None,
            "roi_pct": f"{roi_total*100:.2f}%" if roi_total is not None else None,
            "twr_dietz_annualized": (
                round(twr_total_annualized, 4)
                if twr_total_annualized is not None else None
            ),
            "twr_dietz_annualized_pct": (
                f"{twr_total_annualized*100:.2f}%"
                if twr_total_annualized is not None else None
            ),
        },
        "returns_restricted": {
            "description": f"С {start_date}, только незаблокированные позиции. "
                           f"Отражает эффективность управления активной частью.",
            "period_start": snapshot_date.isoformat(),
            "period_end": today.isoformat(),
            "years": round(years_restricted, 2),
            "initial_value_rub_cost_basis": round(initial_value_restricted, 2),
            "net_external_deposits_after_rub": round(net_deposits_restricted, 2),
            "total_invested_rub": round(invested_restricted, 2),
            "current_value_rub": round(current_total_excl_blocked_rub, 2),
            "pnl_rub": round(pnl_restricted, 2),
            "received_coupons_rub": round(total_coupons_restricted, 2),
            "received_dividends_rub": round(total_dividends_restricted, 2),
            "xirr": round(xirr_restricted, 4) if xirr_restricted is not None else None,
            "xirr_pct": (
                f"{xirr_restricted*100:.2f}%"
                if xirr_restricted is not None else None
            ),
            "roi": round(roi_restricted, 4) if roi_restricted is not None else None,
            "roi_pct": (
                f"{roi_restricted*100:.2f}%"
                if roi_restricted is not None else None
            ),
            "twr_dietz_annualized": (
                round(twr_restricted_annualized, 4)
                if twr_restricted_annualized is not None else None
            ),
            "twr_dietz_annualized_pct": (
                f"{twr_restricted_annualized*100:.2f}%"
                if twr_restricted_annualized is not None else None
            ),
        },
        "returns_by_type_restricted": per_type_reports,
        "benchmarks_restricted": benchmarks,
    }


def _live_basis(flows_total, flows_restricted, market_values, all_blocked, all_blocked_tickers,
                cash_rub, terminal_date, flows_by_type=None, bond_meta=None) -> dict:
    """Вход живого XIRR вьюера: потоки по дням (знак XIRR: вложение < 0) и позиции конечной стоимости.

    Терминал total = cash + Σ value всех позиций (заблокированные — как в отчёте, обычно 0);
    restricted = cash + Σ value незаблокированных.

    flows_by_type: {stock|bond|fund: [[день, сумма], …]} — потоки подпортфеля типа (первый — стоимость
    начала окна), терминал типа = Σ value его незаблокированных позиций; те же потоки, по которым
    посчитан returns_by_type_restricted.xirr. Типы без XIRR (меньше двух потоков) не включаются.
    bond_meta: см. build_market_values; облигациям с ценой MOEX в positions добавляются номинал `face`,
    валюта номинала `face_ccy` и НКД одной бумаги `accrued_rub` — вьюер оценивает позицию по живой
    цене (% номинала): qty × (цена/100 × face + accrued_rub), только при face_ccy RUB."""
    def by_day(cfs):
        agg: dict[str, float] = defaultdict(float)
        for d, amt in cfs:
            agg[d.isoformat()] += amt
        return [[d, round(v, 2)] for d, v in sorted(agg.items()) if abs(v) > 0.005]

    pos = []
    for k, mv in market_values.items():
        if abs(mv.get("qty") or 0) < 1e-9 and not mv.get("value_rub"):
            continue
        pos.append({"ticker": mv["ticker"], "type": mv["type"], "qty": round(mv["qty"], 6),
                    "value_rub": round(mv["value_rub"], 2), "price_source": mv["price_source"],
                    "blocked": k in all_blocked or mv["ticker"] in all_blocked_tickers})
        bm = (bond_meta or {}).get(k)
        if bm and mv["type"] == "bond":
            pos[-1].update({"face": round(bm["face"], 4), "face_ccy": bm["face_ccy"],
                            "accrued_rub": round(bm["accrued_rub"], 4)})
    out = {"terminal_date": terminal_date.isoformat(), "cash_rub": round(cash_rub, 2),
           "flows_total": by_day(flows_total), "flows_restricted": by_day(flows_restricted),
           "positions": sorted(pos, key=lambda x: x["ticker"])}
    if flows_by_type is not None:
        out["flows_by_type"] = {t: by_day(f) for t, f in flows_by_type.items()
                                if t in ("stock", "bond", "fund") and f}
    return out


def _cashflows_excluding_keys(
    trades: list[Trade],
    start: dt.date,
    end: dt.date,
    excluded_keys: set[tuple[str, str]],
) -> list[CashFlow]:
    """Invariant-based external cashflows, но internal-часть пересчитывается
    без сделок по excluded бумагам."""
    by_date_net: dict[dt.date, float] = defaultdict(float)
    by_date_int: dict[dt.date, float] = defaultdict(float)
    for t in trades:
        if t.date < start or t.date > end:
            continue
        if is_forex_conversion(t):
            continue
        key = (t.ticker, t.currency)
        if t.ticker.startswith("Деньги"):
            by_date_net[t.date] += t.rub_amount
        else:
            if key in excluded_keys:
                continue
            op = t.operation
            if op == "Покупка":
                by_date_int[t.date] -= abs(t.rub_amount)
            elif op == "Продажа":
                by_date_int[t.date] += abs(t.rub_amount)
            elif op in ("Купон", "Дивиденд", "Амортизация", "Доход"):
                by_date_int[t.date] += abs(t.rub_amount)
            elif op == "Расход":
                by_date_int[t.date] -= abs(t.rub_amount)
            elif op in (
                "Начисление вариационной маржи",
                "Списание вариационной маржи",
            ):
                by_date_int[t.date] += t.rub_amount
            elif op == "Корректировка":
                by_date_int[t.date] += t.rub_amount
    out = []
    dates = sorted(set(by_date_net.keys()) | set(by_date_int.keys()))
    for d in dates:
        ext = by_date_net[d] - by_date_int[d]
        if abs(ext) < 1.0:
            continue
        out.append(CashFlow(
            date=d,
            amount_rub=ext,
            kind="deposit" if ext > 0 else "withdrawal",
            note="invariant-based (excl. blocked)",
        ))
    return out


# =============================================================================
# XI. Текстовый отчёт
# =============================================================================


def render_text_report(report: dict) -> str:
    L = []
    L.append("=" * 78)
    L.append("ОТЧЁТ О ДОХОДНОСТИ ПОРТФЕЛЯ")
    L.append("=" * 78)
    p = report["parameters"]
    L.append(f"Сгенерирован: {report['generated_at']}")
    L.append(f"Дата расчёта (as_of): {p['as_of']}")
    L.append(f"Старт ограниченного режима: {p['start_date']}")
    L.append(f"Всего сделок в истории: {p['trades_count']}")
    L.append(f"Источник цен: {'MOEX ISS + fallback' if p['use_moex'] else 'last trade price only'}")
    src = report["price_sources_summary"]
    if src:
        L.append(f"  → Цены получены из: " + ", ".join(
            f"{k}={v}" for k, v in src.items()
        ))
    L.append("")

    if report["corrections_applied"]:
        L.append("--- ПРИМЕНЁННЫЕ КОРРЕКТИРОВКИ ---")
        for c in report["corrections_applied"]:
            # Не все корректировки позиционные: `ignored_blocked_corrections`
            # относится к пачке бумаг сразу и не несёт ticker/qty_closed/price.
            # Обращение по ключу здесь роняло весь текстовый отчёт (KeyError).
            head = f"  • {c['type']}"
            if c.get("ticker"):
                head += f" для {c['ticker']}"
            head += f" на {c.get('date', '?')}"
            qty, price = c.get("qty_closed"), c.get("price")
            if qty is not None and price is not None:
                head += f": закрыто {qty:.4f} шт @ {price}"
            L.append(head)
            L.append(f"    Причина: {c.get('reason', '—')}")
        L.append("")

    L.append(f"--- ЗАБЛОКИРОВАННЫЕ ПОЗИЦИИ ({report['blocked_count']}) ---")
    for reason, positions in report["blocked_positions"].items():
        if not positions:
            continue
        L.append(f"  [{reason}] ({len(positions)}):")
        tickers = [f"{p['ticker']}({p['currency']})" for p in positions]
        for chunk_start in range(0, len(tickers), 10):
            L.append("    " + ", ".join(tickers[chunk_start:chunk_start + 10]))
    L.append("")

    s = report["snapshot_start"]
    L.append(f"--- СРЕЗ НА {s['as_of']} (cost basis, начало ограниченного периода) ---")
    L.append(f"Cash-остатки:                      {s['cash_balance_rub']:>15,.0f} ₽")
    L.append(f"Незаблокированные позиции:         {s['total_cost_basis_rub_excl_blocked']:>15,.0f} ₽")
    L.append(f"Заблокированные (исключаются):     {s['total_cost_basis_rub_blocked_only']:>15,.0f} ₽")
    L.append(f"Итого активная часть + cash:       {s['grand_total_with_cash_excl_blocked']:>15,.0f} ₽")
    L.append("")
    L.append(f"Разбивка активной части по типам на {s['as_of']}:")
    for t, v in sorted(s["breakdown_by_type_excl_blocked"].items(), key=lambda x: -x[1]):
        L.append(f"  {t:8} {v:>15,.0f} ₽")
    L.append("")
    L.append(f"Топ-10 незаблокированных позиций на {s['as_of']}:")
    for pos in s["positions_included"][:10]:
        L.append(
            f"  {pos['ticker']:14} ({pos['currency']:3}) "
            f"[{pos['type']:5}] qty={pos['qty']:>10.2f} "
            f"cost={pos['cost_basis_rub']:>14,.2f} ₽"
        )
    L.append("")

    cs = report["snapshot_current"]
    L.append(f"--- ТЕКУЩИЙ СРЕЗ НА {cs['as_of']} ---")
    L.append(f"Cash-остатки:                      {cs['cash_balance_rub']:>15,.0f} ₽")
    cash_details = ", ".join(f"{k}={v:,.2f}" for k, v in cs["cash_by_currency"].items())
    L.append(f"  ({cash_details})")
    L.append(f"Всего портфель:                    {cs['total_value_rub']:>15,.0f} ₽")
    L.append(f"  из них заблокированных:          {cs['blocked_value_rub']:>15,.0f} ₽")
    L.append(f"Активная часть:                    {cs['total_value_rub_excl_blocked']:>15,.0f} ₽")
    L.append("")
    L.append("Разбивка активной части по типам сейчас:")
    for t, v in sorted(cs["breakdown_by_type_excl_blocked"].items(), key=lambda x: -x[1]):
        L.append(f"  {t:8} {v:>15,.0f} ₽")
    L.append("")

    rt = report["returns_total"]
    L.append(f"=== ДОХОДНОСТЬ: ВСЯ ИСТОРИЯ ({rt['period_start']} → {rt['period_end']}) ===")
    L.append(f"  Период: {rt['years']} лет")
    L.append(f"  Чистые депозиты извне:       {rt['net_external_deposits_rub']:>15,.0f} ₽")
    L.append(f"  Купоны получено:             {rt['received_coupons_rub']:>15,.0f} ₽")
    L.append(f"  Дивиденды получено:          {rt['received_dividends_rub']:>15,.0f} ₽")
    L.append(f"  Текущая стоимость:           {rt['current_value_rub']:>15,.0f} ₽")
    L.append(f"  P&L:                         {rt['pnl_rub']:>15,.0f} ₽")
    L.append(f"  XIRR (годовая):              {rt.get('xirr_pct') or 'N/A':>15}")
    L.append(f"  ROI (суммарная):             {rt.get('roi_pct') or 'N/A':>15}")
    L.append(f"  TWR Dietz (годовая):         {rt.get('twr_dietz_annualized_pct') or 'N/A':>15}")
    L.append("")

    rr = report["returns_restricted"]
    L.append(f"=== ДОХОДНОСТЬ: С {rr['period_start']} БЕЗ ЗАБЛОКИРОВАННЫХ ===")
    L.append(f"  Период: {rr['years']} лет")
    L.append(f"  Стартовая стоимость (cost):  {rr['initial_value_rub_cost_basis']:>15,.0f} ₽")
    L.append(f"  Чистые депозиты после:       {rr['net_external_deposits_after_rub']:>15,.0f} ₽")
    L.append(f"  Купоны с начала периода:     {rr['received_coupons_rub']:>15,.0f} ₽")
    L.append(f"  Дивиденды с начала периода:  {rr['received_dividends_rub']:>15,.0f} ₽")
    L.append(f"  Текущая стоимость:           {rr['current_value_rub']:>15,.0f} ₽")
    L.append(f"  P&L:                         {rr['pnl_rub']:>15,.0f} ₽")
    L.append(f"  XIRR (годовая):              {rr.get('xirr_pct') or 'N/A':>15}")
    L.append(f"  ROI (суммарная):             {rr.get('roi_pct') or 'N/A':>15}")
    L.append(f"  TWR Dietz (годовая):         {rr.get('twr_dietz_annualized_pct') or 'N/A':>15}")
    L.append("")

    # Per-type breakdown
    L.append(f"=== ДОХОДНОСТЬ ПО ТИПАМ АКТИВОВ (с {rr['period_start']}) ===")
    L.append(f"{'Тип':<8} {'Start':>14} {'End':>14} {'PnL':>14} "
             f"{'XIRR':>8} {'ROI':>8} {'TWR/yr':>8}")
    L.append("-" * 78)
    for ptype, m in report["returns_by_type_restricted"].items():
        if m["initial_value_rub"] == 0 and m["end_value_rub"] == 0:
            continue
        L.append(
            f"{ptype:<8} "
            f"{m['initial_value_rub']:>14,.0f} "
            f"{m['end_value_rub']:>14,.0f} "
            f"{m['pnl_rub']:>14,.0f} "
            f"{m.get('xirr_pct') or 'N/A':>8} "
            f"{m.get('roi_pct') or 'N/A':>8} "
            f"{m.get('twr_dietz_annualized_pct') or 'N/A':>8}"
        )
    L.append("")
    L.append("Детали по типам:")
    for ptype, m in report["returns_by_type_restricted"].items():
        if m["initial_value_rub"] == 0 and m["end_value_rub"] == 0:
            continue
        L.append(f"  [{ptype}] за {m['years']} лет:")
        L.append(f"    Купоны: {m['received_coupons_rub']:>12,.0f} ₽, "
                 f"Дивиденды: {m['received_dividends_rub']:>12,.0f} ₽, "
                 f"Чистый приток (внутри подпортфеля): {m['net_inflow_rub']:>14,.0f} ₽")
    L.append("")
    L.append("Примечания:")
    L.append("  • XIRR (money-weighted): учитывает timing ваших движений, отражает реальный результат.")
    L.append("  • TWR Dietz (time-weighted approx): для сравнения с фондами/индексами.")
    L.append("  • Per-type расчёт: каждый тип как изолированная инвестиция.")
    L.append("    Покупка в тип X = отток (-), продажа/купон/дивиденд = приток (+).")
    L.append("  • Бенчмарки: IMOEX full return (stocks), RGBITR (bonds), RUCBITR (corp bonds).")
    return "\n".join(L)


# =============================================================================
# XII. Main / CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Portfolio returns calculator (XIRR/ROI/TWR) с per-type breakdown.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--trades", help="Path to trades.xlsx (IntelInvest)")
    parser.add_argument(
        "--as-of", help="Дата расчёта в ISO (default: today). Влияет на "
                        "позиции и рыночные цены.",
    )
    parser.add_argument(
        "--start-date",
        default=BLOCKING_CUTOFF.isoformat(),
        help=f"Начало 'ограниченного' периода (default: {BLOCKING_CUTOFF}).",
    )
    parser.add_argument(
        "--no-moex", action="store_true",
        help="Не ходить в MOEX ISS; использовать только last trade price "
             "из trades как источник рыночных цен.",
    )
    parser.add_argument(
        "--no-benchmarks", action="store_true",
        help="Пропустить бенчмарк-гейт (PME: акции vs MCFTR, облигации vs "
             "вклад КС−1). Без флага считается best-effort: при сбое сети "
             "блок benchmarks_restricted частично/полностью null + флаги.",
    )
    parser.add_argument(
        "--blocked-value",
        choices=["zero", "last_trade", "cost_basis"],
        default="zero",
        help="Как оценивать заблокированные позиции: "
             "'zero' (реалистично, т.к. они не торгуются — default), "
             "'last_trade' (как IntelInvest показывает), "
             "'cost_basis' (по сумме покупок).",
    )
    parser.add_argument("--output", help="Output path (default: stdout)")
    parser.add_argument("--format", choices=["json", "text"], default="text")
    parser.add_argument("--types-cache", default=None, metavar="PATH",
                        help="справочник типов бумаг Portfolio/security-types.json (тип с Мосбиржи "
                             "перебивает эвристику); нет файла — без переопределений")
    parser.add_argument("--splits-file", default=None, metavar="PATH",
                        help="реестр сплитов Portfolio/known-splits.json (дополняет встроенный набор); "
                             "нет файла — только встроенный")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--clear-cache", action="store_true",
                        help="Clear CBR rate cache and exit")
    parser.add_argument(
        "--cbr-offline", action="store_true",
        help="Не ходить в ЦБ РФ за свежими курсами (использовать только "
             "кэш + bundled исторические курсы). Полезно при 503/падениях "
             "ЦБ — для прошлых дат курс не меняется, а для as_of в пределах "
             "bundled-периода обычно тоже есть.",
    )
    args = parser.parse_args()
    load_types_cache(args.types_cache)
    load_known_splits(args.splits_file)

    if args.clear_cache:
        if CBR_CACHE_PATH.exists():
            CBR_CACHE_PATH.unlink()
            print(f"Cache cleared: {CBR_CACHE_PATH}")
        else:
            print("No cache to clear")
        return

    if not args.trades:
        parser.error("--trades is required (or --clear-cache)")

    as_of = dt.date.fromisoformat(args.as_of) if args.as_of else dt.date.today()
    start_date = dt.date.fromisoformat(args.start_date)

    if args.verbose:
        sys.stderr.write(f"[1/4] Parsing trades: {args.trades}\n")
    trades = parse_trades(args.trades)
    if args.verbose:
        sys.stderr.write(f"      {len(trades)} trades loaded.\n")

    if args.verbose:
        sys.stderr.write(f"[2/4] Converting trades to RUB via CBR rates...\n")
    trades = convert_trades_to_rub(
        trades, verbose=args.verbose, cbr_offline=args.cbr_offline
    )

    if args.verbose:
        sys.stderr.write(f"[3/4] Applying corrections (TMF forced close, etc.)\n")
    trades, corrections = apply_corrections(trades)

    if args.verbose:
        sys.stderr.write(f"[4/4] Building report (as_of={as_of}, start={start_date})...\n")
    report = build_report(
        trades, corrections,
        as_of=as_of, start_date=start_date,
        use_moex=not args.no_moex,
        blocked_value=args.blocked_value,
        verbose=args.verbose,
        with_benchmarks=not args.no_benchmarks,
        cbr_offline=args.cbr_offline,
    )
    # Текущие курсы ЦБ → в отчёт: assemble_snapshot кладёт их в снапшот как
    # fx_rates_used (implied-цена замещаек + рублёвый bond_cashflow_calendar).
    report["fx_rates_asof"] = current_fx_rates(as_of, cbr_offline=args.cbr_offline)
    report["fx_gaps"] = list(FX_GAPS.values())

    if args.format == "json":
        out = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    else:
        out = render_text_report(report)

    if args.output:
        Path(args.output).write_text(out)
        if args.verbose:
            sys.stderr.write(f"Output written to: {args.output}\n")
    else:
        print(out)


if __name__ == "__main__":
    main()
