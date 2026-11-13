#!/usr/bin/env python3
"""
Сборка portfolio-<date>.json (schema_version 2.0) из промежуточных файлов.

Принимает выходы предыдущих шагов pipeline:
  portfolio.json     ← parse_portfolio.py   (ключи на РУССКОМ языке!)
  returns.json       ← portfolio_returns.py (xirr как ДОЛЯ: 0.1234)
  per_security.json  ← per_security_xirr.py (ставки долями под ключами *_frac)
  quotes.json        ← moex_quotes.py       (цена в поле 'last', не 'price'!)

Все quirks (разные форматы xirr, имена полей, IIS-3 split, qty из returns)
обрабатываются здесь, чтобы модель не держала их в голове при оркестровке.

Usage:
    python3 assemble_snapshot.py \\
        --portfolio    /tmp/portfolio.json \\
        --returns      /tmp/returns.json \\
        --per-security /tmp/per_security.json \\
        --quotes       /tmp/quotes.json \\
        --output       /tmp/portfolio-2026-05-05.json \\
        --trades       /tmp/trades_portfolio_707160-7.xlsx \\
        --balance      "/tmp/Общий баланс.numbers"
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Any

# Для запуска из scripts/ — добавляем свою директорию в path, чтобы
# импортировать parse_portfolio независимо от того, где лежит скилл
# (тот же приём, что per_security_xirr.py использует для portfolio_returns).
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# Контракт подтипов облигаций (§4 bond-subtypes-plan.md) — SSOT-константы
# живут в parse_portfolio.py (PDL-3), здесь только используются для гейтов
# PDL-7, которым нужны свежие MOEX-данные (rating→bucket сверка).
# Время МСК (`time_msk.py`) — канон в _shared-references/; в упакованном .skill — рядом (pack.sh).
_SHARED = Path(__file__).resolve().parents[3] / "_shared-references"
if _SHARED.is_dir() and str(_SHARED) not in sys.path:
    sys.path.append(str(_SHARED))
import time_msk  # noqa: E402
from parse_portfolio import rating_to_corp_bucket  # noqa: E402
import bond_avg_price  # noqa: E402
import bond_bucket  # noqa: E402
import bond_locked  # noqa: E402


# Тикеры денежных фондов, которые пользователь считает кеш-эквивалентами.
# Используются для вычисления cash.cash_equiv_rub и cash.liquid_rub.
# FINAMAR сюда сознательно НЕ входит: ИПИФ «Финам – Алгоритм роста» неликвиден
# до плановой продажи и кэшем не является ни в каком смысле (владелец,
# 2026-07-08) — он остаётся обычной fund-позицией в holdings.
CASH_EQUIV_TICKERS: frozenset[str] = frozenset({"LQDT", "TMON", "TPAY"})

# Граница между подтипами ОФЗ «>10» и «<10», в годах до погашения.
# Ось — ТЕКУЩИЙ срок, не срок при выпуске (решение владельца Q2,
# bond-subtypes-plan.md §3). Меняется вместе с §4.3 плана: подтипы в
# «Общем балансе» названы по этому порогу, поэтому число нельзя двигать
# в коде, не переименовав корзины в файле владельца.
OFZ_MATURITY_SPLIT_YEARS: float = 10.0


# ── статус позиции (SSOT) ─────────────────────────────────────────────────────
# Реестр статусов позиций — единый источник правды для downstream
# (portfolio-scenario-stress, portfolio-integrated-view, coherence-audit §3).
# Поддерживается ВРУЧНУЮ, по аналогии с KNOWN_SPLITS в portfolio_returns.py:
# MOEX ISS статусы blocked/distressed автоматически НЕ отдаёт.
#
# Ключ — ticker ИЛИ ISIN (для облигаций ticker обычно совпадает с ISIN).
# Таксономия status:
#   normal     — дефолт; в реестр не вносится
#   blocked    — торги/распоряжение заблокированы (НРД, санкционная заморозка);
#                is_blocked производно становится True
#   distressed — бумага торгуется, но эмитент/денежные потоки под угрозой
#                (национализация, судебные меры, преддефолт); is_blocked False
# Каждая non-normal запись обязана иметь note: дата + причина + ссылка на источник.
POSITION_STATUSES = ("normal", "blocked", "distressed")

# История: БорецКЗО26 (RU000A105GN3) числился distressed с 2026-07 («национализация
# 27.03.2026, выплаты заблокированы» — записано со слов владельца, без верификации).
# Снят 2026-07-23: ревизия по первоисточникам (investfunds, bond-обзор 23.07) показала,
# что в снапшот попал НЕВЕРНЫЙ ГОД — национализация была в марте 2025 и урегулирована
# в том же году; бумага «в обращении», купон 06.07.2026 выплачен, оферта 21.07.2026
# исполнена, погашение 17.09.2026, дефолт-флагов нет. Урок: записи «со слов» без
# ссылки на раскрытие — источник ложных RED FLAG на всём downstream (weekly/IV/viewer).
KNOWN_POSITION_STATUS: dict[str, dict] = {}

# Замороженные иностранные акции (СПб-биржа): расчёты для российских
# инвесторов заблокированы санкциями с конца февраля 2022, позиции оценены
# по последней котировке 21.02.2022 (last_trade/cost_basis в снапшоте).
# Ручной список — MOEX/IntelInvest статус заморозки не отдают; совпадает с
# blocked_tickers stress-теста 2026-07-02.
# FINAMAR сюда НЕ входит — российский фонд, владелец ведёт его вручную.
# Замороженные иностранные ФОНДЫ (FX*/RSH*/TBIO) в реестр не вносятся:
# portfolio_returns сам помечает их is_blocked (classify_blocked), и они
# попадают в holdings через _build_blocked_positions с upstream-флагом.
_FROZEN_FOREIGN_NOTE = (
    "Иностранная акция (СПб-биржа), заморожена санкционной блокировкой "
    "НРД/Euroclear с февраля 2022; оценка зафиксирована по последней "
    "котировке 21.02.2022. Ручная пометка владельца."
)
for _t in ("BAC", "PEP", "KMB", "SYY", "RTX", "ABT", "EWBC", "EMR",
           "MS", "KO", "HBAN", "GD", "Z", "BMY", "PFE", "C"):
    KNOWN_POSITION_STATUS[_t] = {"status": "blocked", "note": _FROZEN_FOREIGN_NOTE}


def _apply_iis_accounts(
    holdings: list[dict] | None, portfolio: dict | None,
) -> None:
    """
    ИИС-3-позиции вне облигационного сплита (вкладка «Другое» с Тип
    «RUB - ИИС», например SBGB): трейды счетов не знают, и такие позиции
    приходят из returns с дефолтным account="main". Переназначаем по
    metrics.iis_other_tickers из balance-файла — SSOT принадлежности к ИИС.
    """
    iis_tickers = set(
        ((portfolio or {}).get("metrics") or {}).get("iis_other_tickers") or []
    )
    if not iis_tickers:
        return
    for h in holdings or []:
        if h.get("ticker") in iis_tickers and h.get("account") == "main":
            h["account"] = "iis_3"


def _apply_position_status(holdings: list[dict] | None) -> None:
    """In-place: канонический holdings[].status + производный is_blocked.

    Приоритет: KNOWN_POSITION_STATUS (по ticker, затем по ISIN) → upstream
    is_blocked=True → "normal". После вызова is_blocked — строго производное
    (status == "blocked"); downstream статус читает только из status.
    """
    for h in holdings or []:
        if not isinstance(h, dict):
            continue
        entry = (KNOWN_POSITION_STATUS.get(h.get("ticker"))
                 or KNOWN_POSITION_STATUS.get(h.get("isin")))
        if entry and entry.get("status") in POSITION_STATUSES:
            h["status"] = entry["status"]
            if entry.get("note"):
                h["status_note"] = entry["note"]
        elif h.get("is_blocked"):
            h["status"] = "blocked"
        else:
            h["status"] = "normal"
        h["is_blocked"] = h["status"] == "blocked"


def _build_status_summary(holdings: list[dict] | None) -> dict:
    """Сводка стоимости по статусам — канонические доли для downstream.

    pct — доля от суммарной стоимости holdings с известным value_rub.
    tickers перечисляются только для non-normal статусов (main+iis_3
    записи одного тикера не дублируются).
    """
    by: dict[str, dict] = {
        s: {"value_rub": 0.0, "pct": 0.0, "count": 0, "tickers": []}
        for s in POSITION_STATUSES
    }
    total = 0.0
    for h in holdings or []:
        if not isinstance(h, dict):
            continue
        s = h.get("status") or "normal"
        if s not in by:
            s = "normal"
        slot = by[s]
        slot["count"] += 1
        v = _f(h.get("value_rub"))
        if v:
            slot["value_rub"] += v
            total += v
        t = h.get("ticker")
        if s != "normal" and t and t not in slot["tickers"]:
            slot["tickers"].append(t)
    for s, slot in by.items():
        slot["value_rub"] = round(slot["value_rub"], 2)
        slot["pct"] = round(slot["value_rub"] / total * 100, 2) if total else 0.0
        if s == "normal":
            del slot["tickers"]
    return {"total_value_rub": round(total, 2), "by_status": by}


# ── first_appearance_date (METH-2) ────────────────────────────────────────────

def _apply_first_appearance(
    holdings: list[dict] | None,
    prev_snapshot: dict | None,
    today_iso: str,
) -> None:
    """In-place добавляет per-ticker first_appearance_date в holdings.

    Если тикер был в предыдущем snapshot → переносит first_appearance_date оттуда.
    Иначе (новый или re-entry после divest) → first_appearance_date = today.

    Для re-entry мы не отслеживаем «когда-то-был» — это намеренное упрощение
    (см. docs/investment/portfolio/new_met.md §3.7: новый цикл начинается с чистого листа).
    """
    if not holdings:
        return

    prev_lookup: dict[str, str] = {}
    if prev_snapshot:
        prev_holdings = prev_snapshot.get("holdings") or prev_snapshot.get("positions") or []
        if isinstance(prev_holdings, list):
            for ph in prev_holdings:
                if isinstance(ph, dict):
                    t = ph.get("ticker")
                    fa = ph.get("first_appearance_date")
                    if t and fa:
                        prev_lookup[t] = fa

    for h in holdings:
        if not isinstance(h, dict):
            continue
        ticker = h.get("ticker")
        if not ticker:
            continue
        h["first_appearance_date"] = prev_lookup.get(ticker, today_iso)


def _load_sector_overrides(path: str | None) -> dict[str, dict[str, str | None]]:
    """Загрузить sector-overrides.yaml → {ticker|isin: {"sector": ..., "sector_ru": ...}}.

    `sector` — ВСЕГДА машинный canon-ключ (словарь macro-forecast-chain/stress).
    `sector_ru` — отображаемый ярлык (словарь IntelInvest), если задан в записи,
    иначе None (переводов не выдумываем).

    PDL-I (2026-08-27): раньше функция схлопывала оба поля записи override в одно
    возвращаемое значение (`sector_ru or sector`), из-за чего в holdings[].sector
    записывался то машинный ключ, то русский ярлык — один и тот же сектор оказывался
    под двумя разными именами (см. docs/investment/TODO.md#pdl-i). Теперь оба поля
    возвращаются раздельно и НИКОГДА не подменяют друг друга у потребителя.
    Зеркало парсера — load_sector_overrides в build_weekly_stock_stub.py
    (ru-portfolio-advisor); при правке синхронизировать оба. При ошибке чтения — {}.
    """
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    import re as _re
    try:
        text = p.read_text(encoding="utf-8")
        rows: list[dict[str, str]] = []
        cur: dict[str, str] | None = None
        for line in text.splitlines():
            if line and not line[0].isspace() and not line.startswith("-"):
                # top-level ключ (version/overrides/fund_classification/…) —
                # закрыть текущую запись, чтобы хвостовые секции не «дозаполняли» её
                cur = None
                continue
            m = _re.match(r"\s*-\s+ticker:\s+(\S+)\s*(?:#.*)?$", line)
            if m:
                cur = {"ticker": m.group(1)}
                rows.append(cur)
                continue
            if cur is None:
                continue
            m = _re.match(r"\s+(sector|sector_ru):\s+(.+?)\s*$", line)
            if m:
                val = _re.sub(r"\s+#.*$", "", m.group(2)).strip().strip("\"'")
                if val:
                    cur[m.group(1)] = val
        return {
            r["ticker"]: {"sector": r["sector"], "sector_ru": r.get("sector_ru")}
            for r in rows
            if r.get("sector")
        }
    except Exception:
        return {}


def _apply_sector_overrides(
    holdings: list[dict] | None,
    overrides: dict[str, dict[str, str | None]],
) -> None:
    """In-place: устанавливает holdings[].sector (машинный ключ) и holdings[].sector_ru
    (отображаемый ярлык, если задан) из overrides по ticker (фоллбэк по ISIN).

    Оба поля заполняются независимо: нет sector в overrides → sector не трогается;
    нет sector_ru в записи (или записи вовсе нет) → sector_ru не заполняется (не
    выдумываем перевод). Уже заполненное upstream значение не перезаписывается —
    overrides только закрывают дыры.
    """
    if not holdings or not overrides:
        return
    for h in holdings:
        if not isinstance(h, dict):
            continue
        key = h.get("ticker") or h.get("isin")
        entry = overrides.get(key) if key else None
        if not entry:
            continue
        if not h.get("sector") and entry.get("sector"):
            h["sector"] = entry["sector"]
        if not h.get("sector_ru") and entry.get("sector_ru"):
            h["sector_ru"] = entry["sector_ru"]


# ── helpers ───────────────────────────────────────────────────────────────────

def _load(path: str | None) -> dict | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _f(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _price_ts(q: dict) -> str | None:
    """Время котировки → `ГГГГ-ММ-ДДTЧЧ:ММ:СС+03:00`. MOEX отдаёт SYSTIME «ГГГГ-ММ-ДД ЧЧ:ММ:СС» без пояса —
    это московское время; единственное место нормализации для всех холдингов."""
    v = q.get("timestamp")
    if not v:
        return None
    try:
        return time_msk.to_msk_iso(str(v), naive_is_msk=True)
    except ValueError:
        return str(v)


def _moex_price(q: dict) -> tuple[float | None, str | None]:
    """Цена MOEX: last, а без сделок сегодня — prev_close (2026-10-21: прогон в 08:13 МСК,
    до открытия торгов, дал 11 облигаций без last при живом TQCB — они ушли в implied из
    баланса). Источник остаётся moex_iss, основа цены — в current_price_basis."""
    last = _f(q.get("last"))
    if last is not None:
        return last, "last"
    prev = _f(q.get("prev_close"))
    return (prev, "prev_close") if prev is not None else (None, None)


def _price_source(raw: str | None) -> str:
    """Нормализовать price_source из returns.json к значениям схемы v2."""
    if not raw:
        return "unavailable"
    s = raw.lower()
    if "moex" in s:
        return "moex_iss"
    if "last_trade" in s:
        return "last_trade"
    if "cost_basis" in s or "blocked" in s:
        return "cost_basis"
    return "unavailable"


def _flag(step: str, severity: str, code: str, message: str) -> dict:
    return {"step": step, "severity": severity, "code": code, "message": message}


# Бумаги, у которых цены MOEX нет по природе (внебиржевые) — их фолбэк в доходности не ошибка
RETURNS_PRICE_MANUAL = frozenset({"FINAMAR"})


def _returns_price_fallbacks(returns: dict | None, holdings: list | None) -> list[dict]:
    """Акции, фонды и облигации, которые portfolio_returns оценил НЕ по MOEX (цена последней сделки /
    по стоимости покупки), хотя в holdings у той же бумаги котировка MOEX есть.

    Случай 2026-10-22 (скилл в окружении Claude, MOEX ISS отвечал не на всё): TGLD в доходности
    по 14,58 ₽ (последняя покупка 20.08) вместо 12,96 ₽ MOEX → +47,8 тыс. ₽ к стоимости, XIRR
    завышен на 0,26–0,31 п.п., кэш занижен — и ни одного предупреждения. Молчаливый фолбэк
    при живой котировке рядом — ошибка, а не оценка."""
    moex, bond_quoted = {}, set()
    for h in holdings or []:
        if h.get("current_price_source") != "moex_iss" or not h.get("current_price"):
            continue
        if h.get("asset_type") == "bond":
            # облигация: котировка в % номинала — сравнить с рублёвой ценой нельзя, ошибка — сам источник
            # (PDL-16, 27.10: юаневые облигации в доходности по цене последней сделки, −6 тыс. ₽ у ЕСЭГ)
            bond_quoted |= {h.get("ticker"), h.get("isin")} - {None}
        elif h.get("account", "main") == "main" and h.get("asset_type") in ("stock", "fund"):
            moex[h.get("ticker")] = float(h["current_price"])
    out = []
    for p in ((returns or {}).get("snapshot_current") or {}).get("positions") or []:
        t, q = p.get("ticker"), float(p.get("qty") or 0)
        if p.get("is_blocked") or q <= 0 or t in RETURNS_PRICE_MANUAL:
            continue
        if str(p.get("price_source") or "").startswith("moex"):
            continue
        used = float(p.get("value_rub") or 0) / q
        if p.get("type") == "bond" and t in bond_quoted:
            out.append({"ticker": t, "source": p.get("price_source"), "used_price": round(used, 4),
                        "moex_price": None, "diff_rub": None})
        elif p.get("type") in ("stock", "fund") and t in moex:
            out.append({"ticker": t, "source": p.get("price_source"), "used_price": round(used, 4),
                        "moex_price": moex[t], "diff_rub": round(float(p.get("value_rub") or 0) - q * moex[t], 2)})
    return out


def _per_instrument_price_check(
    per_instrument: dict | None, holdings: list | None,
) -> tuple[list[dict], list[dict]]:
    """Сверка цены per_instrument_xirr с MOEX-ценой holdings у акций и фондов.

    Возвращает (fallbacks, mismatches): fallbacks — оценка не по MOEX (price_source не
    moex*, хотя котировка MOEX в holdings есть); mismatches — источник moex*, но
    подразумеваемая цена market_value_rub/qty_now расходится с holdings более чем на 0,5%
    (у облигаций — стоимость одной бумаги в holdings основного счёта).

    Случай 2026-10-27 (скилл в облачной среде): per_security_xirr сам ходил в MOEX одной
    попыткой, при сбое молча взял цену последней сделки по всем 80 бумагам, а holdings шли
    по котировкам moex_quotes.py — NVTK 342 899,4 ₽ вместо 296 676 ₽ (82 шт × 1207), XIRR
    26,1% вместо 22,7%; сверки между двумя наборами не было. Облигации — только mismatches
    (источник в доходности по ним проверяет _returns_price_fallbacks); внебиржевые (FINAMAR) —
    без цены MOEX по природе."""
    moex, bond_unit = {}, {}
    for h in holdings or []:
        if h.get("account", "main") != "main" or h.get("current_price_source") != "moex_iss" \
                or not h.get("current_price"):
            continue
        if h.get("asset_type") in ("stock", "fund"):
            moex[h.get("ticker")] = float(h["current_price"])
        elif h.get("asset_type") == "bond" and h.get("qty") and h.get("value_rub"):
            # облигация: сверка стоимости одной бумаги (грязная, ₽) — бумага на двух счетах не мешает
            bond_unit[h.get("ticker")] = float(h["value_rub"]) / float(h["qty"])
    fallbacks: list[dict] = []
    mismatches: list[dict] = []
    for t, rec in (per_instrument or {}).items():
        if not isinstance(rec, dict) or rec.get("alias_of") or t in RETURNS_PRICE_MANUAL:
            continue
        q = float(rec.get("qty_now") or 0)
        mv = rec.get("market_value_rub")
        if q <= 0 or mv is None:
            continue
        mv = float(mv)
        used = mv / q
        bk = t if t in bond_unit else rec.get("isin")
        if t not in moex and bk in bond_unit:
            # PDL-16 (27.10): юаневые облигации — в holdings по цене последней сделки, ЕСЭГ1PC5 −4,1 %
            if str(rec.get("price_source") or "").startswith("moex") and abs(used / bond_unit[bk] - 1) > 0.005:
                mismatches.append({"ticker": t, "source": rec.get("price_source"), "used_price": round(used, 4),
                                   "moex_price": round(bond_unit[bk], 4),
                                   "diff_rub": round(mv - q * bond_unit[bk], 2),
                                   "diff_pct": round((used / bond_unit[bk] - 1) * 100, 2)})
            continue
        if t not in moex:
            continue
        item = {"ticker": t, "source": rec.get("price_source"), "used_price": round(used, 4),
                "moex_price": moex[t], "diff_rub": round(mv - q * moex[t], 2)}
        if not str(rec.get("price_source") or "").startswith("moex"):
            fallbacks.append(item)
        elif abs(used / moex[t] - 1) > 0.005:
            mismatches.append({**item, "diff_pct": round((used / moex[t] - 1) * 100, 2)})
    return fallbacks, mismatches


def _text_or_none(v: Any) -> str | None:
    """Строка или None. Локальный дубль parse_portfolio._text_or_none —
    не тянуть кросс-модульную зависимость ради одной строки."""
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _plan_bucket_key(typ: Any, subtype: Any) -> str | None:
    """Производный ключ плановой корзины (§4.1 bond-subtypes-plan.md):
    `"ОФЗ/>10"` для ОФЗ/КОРП, просто `"USD"` для валютных строк без
    подтипа. Локальный дубль parse_portfolio._bond_bucket_key."""
    t = _text_or_none(typ)
    if not t or t == "Итог":
        return None
    s = _text_or_none(subtype)
    return f"{t}/{s}" if s else t


def _moex_confirms_floater(name: str | None) -> bool:
    """Best-effort эвристика «MOEX/имя бумаги подтверждает плавающий
    купон» для гейта bond_floater_subtype_mismatch (info, PDL-7).

    ⚠️ НЕ путать с _is_floater в
    portfolio-scenario-stress/scripts/compute_bond_carry.py (PSS-12/13):
    там приоритет у holdings[].plan_subtype (потому что имя часто не несёт
    сигнала — «ОФЗ 29014» не содержит слова «флоатер»). Здесь, наоборот,
    мы сверяем заявленный Подтип=Флоат с независимым сигналом, поэтому
    вдобавок к подстроке проверяем домашнюю конвенцию нумерации выпусков
    ОФЗ: серия 29xxx = ОФЗ-ПК (плавающий купон)."""
    import re
    n = (name or "").lower()
    if "флоатер" in n or "floater" in n or "floating" in n:
        return True
    return bool(re.search(r"офз[\s\-]*29\d{3}", n))


def _coupon_freq(period_days: Any) -> int | None:
    """Частота купона в год из периода в днях (MOEX COUPONPERIOD).
    182→2, 91→4, 365→1, ~30→12. None/0 → None (не угадываем)."""
    p = _f(period_days)
    if not p or p <= 0:
        return None
    return max(1, round(365.0 / p))


def _norm_col(name: Any) -> str:
    """Нормализованное имя колонки: регистр, пробелы (в т.ч. неразрывные),
    точки, запятые и прочая пунктуация игнорируются. «Ср, Цена» == «Ср.Цена»."""
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


# Допустимые имена колонки средней цены (в нормализованном виде). «Цена» (текущая)
# и «Точка Входа» (цена входа модели IE, НЕ средняя) сюда НЕ входят.
_AVG_COST_COLS = frozenset(_norm_col(n) for n in (
    "Ср. Цена", "Ср, Цена", "Средняя цена", "avg_cost", "Цена входа",
))


def _avg_cost_from_row(row: dict) -> float | None:
    """Получить avg_cost из строки stocks. Имена колонок сравниваются
    нормализованно (регистр, пробелы, точки, запятые игнорируются): в реальном
    «Общем балансе» колонка называется «Ср, Цена» (инцидент 2026-10-13: точное
    сравнение не совпало, и во всех снапшотах с июня 2026 avg_cost_rub акций
    молча подменялся value/qty = текущей ценой)."""
    for key, raw in row.items():
        if _norm_col(key) in _AVG_COST_COLS:
            v = _f(raw)
            if v is not None:
                return v
    return None


# ── holdings: stocks ──────────────────────────────────────────────────────────

def _lot_size(q: dict) -> int | None:
    """LOTSIZE из moex_quotes (поле lot_size); не целое/≤0/нет — None (лоты не считаются)."""
    v = q.get("lot_size")
    try:
        v = int(v)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


# Дата сборки для повтора пакета прогона (assemble(as_of=…)); None — системные часы.
_AS_OF_OVERRIDE: "datetime.date | None" = None


def _listing_fields(q: dict, today: "datetime.date | None" = None) -> dict[str, Any]:
    """listing_date + возраст листинга в полных кварталах (IPO-гейт advisor,
    правило 23). Источник — moex_quotes weekly: listing_from = первый торговый
    день бумаги на MOEX (/history/.../dates.json)."""
    lf = q.get("listing_from")
    if not lf:
        return {"listing_date": None, "listing_age_quarters": None}
    try:
        today = today or _AS_OF_OVERRIDE or datetime.date.today()
        days = (today - datetime.date.fromisoformat(lf)).days
        return {"listing_date": lf, "listing_age_quarters": max(int(days // 91.3125), 0)}
    except ValueError:
        return {"listing_date": None, "listing_age_quarters": None}


def _build_stocks(
    portfolio: dict,
    returns: dict,
    quotes: dict,
) -> tuple[list[dict], list[dict]]:
    """
    Акции из returns.json (все позиции с qty > 0, не заблокированные),
    обогащённые данными из portfolio.json (balance-файл) и quotes.json.

    portfolio.json.stocks — только российские акции из Numbers-файла.
    US-акции приходят из returns.json.snapshot_current.positions.
    qty никогда не берётся из balance — только из returns.
    """
    flags: list[dict] = []
    snap = (returns or {}).get("snapshot_current", {})

    # Lookup: ticker → balance-строка (русские имена колонок)
    balance_lkp: dict[str, dict] = {}
    for row in (portfolio or {}).get("stocks", []):
        t = row.get("Тикер")
        val = _f(row.get("Стоимость"))
        if t and val and val > 0:
            balance_lkp[t] = row

    # Lookup: ticker → quote (поле 'last' — не 'price'!)
    q_lkp: dict[str, dict] = quotes or {}

    result: list[dict] = []
    no_quotes: list[str] = []
    avg_fallback: list[str] = []

    for pos in snap.get("positions", []):
        if pos.get("type") != "stock":
            continue
        if pos.get("is_blocked"):
            continue
        qty = _f(pos.get("qty"))
        if not qty or qty <= 0:
            continue

        ticker = pos["ticker"]
        bal = balance_lkp.get(ticker)

        # value_rub: balance-файл имеет приоритет (более актуальный)
        value_rub = _f(bal.get("Стоимость")) if bal else _f(pos.get("value_rub"))

        # avg_cost: из balance; fallback — value/qty
        avg_cost = _avg_cost_from_row(bal) if bal else None
        avg_src = "balance" if avg_cost is not None else None
        if avg_cost is None and qty and value_rub:
            avg_cost = round(value_rub / qty, 4)
            avg_src = "value_over_qty"
            avg_fallback.append(ticker)

        # Цена: quotes['last'] → расчёт из value/qty
        q = q_lkp.get(ticker, {})
        current_price, price_basis = _moex_price(q)
        if current_price is not None:
            price_src = "moex_iss"
        else:
            price_src = _price_source(pos.get("price_source"))
            current_price = round(value_rub / qty, 4) if value_rub and qty else None
            no_quotes.append(ticker)

        holding: dict[str, Any] = {
            "ticker": ticker,
            "isin": q.get("isin") or None,
            "name": (bal.get("Название") if bal else None) or pos.get("name"),
            "qty": qty,
            "avg_cost_rub": avg_cost,
            "avg_cost_source": avg_src,
            "current_price": current_price,
            "current_price_source": price_src,
            "current_price_ts": _price_ts(q),
            "current_price_basis": price_basis,
            "value_rub": value_rub,
            "currency": pos.get("currency", "RUB"),
            "asset_type": "stock",
            "account": "main",
            "is_blocked": False,
            "nominal_currency": None,
            "ytm_pct": None,
            "ytm_source": None,
            **_listing_fields(q),
            # лот MOEX (2026-10-13): вьюер считает «сейчас купить/продать N лотов» тем же
            # правилом, что gate_aware_sizing советника (округление покупки вниз, среза вверх)
            "lot_size": _lot_size(q),
        }
        result.append(holding)

    # Второй проход: stocks из balance-файла, которые не попали из returns
    # (blocked в IntelInvest или вовсе отсутствуют — например, T-Технологии).
    seen: set[str] = {h["ticker"] for h in result}
    for ticker, bal in balance_lkp.items():
        if ticker in seen:
            continue
        val = _f(bal.get("Стоимость"))
        if not val or val <= 0:
            continue
        matching = next(
            (p for p in snap.get("positions", []) if p["ticker"] == ticker),
            None,
        )
        qty = _f(matching.get("qty")) if matching else None
        avg_cost = _avg_cost_from_row(bal)
        q = q_lkp.get(ticker, {})
        current_price, price_basis = _moex_price(q)
        if current_price is not None:
            price_src = "moex_iss"
        else:
            price_src = "moex"
            current_price = round(val / qty, 4) if val and qty else None
            no_quotes.append(ticker)
        result.append({
            "ticker":               ticker,
            "isin":                 q.get("isin") or None,
            "name":                 bal.get("Название"),
            "qty":                  qty,
            "avg_cost_rub":         avg_cost,
            "avg_cost_source":      "balance" if avg_cost is not None else None,
            "current_price":        current_price,
            "current_price_source": price_src,
            "current_price_ts":     _price_ts(q),
            "current_price_basis":  price_basis,
            "value_rub":            val,
            "currency":             "RUB",
            "asset_type":           "stock",
            "account":              "main",
            "is_blocked":           False,
            "nominal_currency":     None,
            "ytm_pct":              None,
            "ytm_source":           None,
            **_listing_fields(q),
            # лот MOEX (2026-10-13): вьюер считает «сейчас купить/продать N лотов» тем же
            # правилом, что gate_aware_sizing советника (округление покупки вниз, среза вверх)
            "lot_size": _lot_size(q),
        })
        seen.add(ticker)

    if avg_fallback:
        flags.append(_flag(
            "assemble_stocks", "warning", "avg_cost_fallback_value_over_qty",
            f"Средняя цена не найдена в колонках баланса для {len(avg_fallback)} акций — "
            f"avg_cost_rub = value/qty (это ТЕКУЩАЯ цена, не средняя; holdings[].avg_cost_source="
            f"\"value_over_qty\"). Тикеры: {', '.join(avg_fallback[:10])}"
            + ("..." if len(avg_fallback) > 10 else ""),
        ))

    if no_quotes:
        flags.append(_flag(
            "moex_quotes", "info", "moex_unavailable_tickers",
            f"MOEX ISS не вернул данные для {len(no_quotes)} тикеров. "
            f"Использован last_trade_price. Тикеры: {', '.join(no_quotes[:5])}"
            + ("..." if len(no_quotes) > 5 else ""),
        ))

    return result, flags


# ── holdings: bonds ───────────────────────────────────────────────────────────

def _fx_rate_of(fx_rates: dict | None, currency: str | None) -> float | None:
    """Курс валюты номинала из fx_rates_asof (portfolio_returns). RUB/SUR → 1.0."""
    cur = (currency or "RUB").upper()
    if cur in ("RUB", "SUR", "RUR", ""):
        return 1.0
    entry = (fx_rates or {}).get(cur)
    if isinstance(entry, dict) and isinstance(entry.get("rate"), (int, float)):
        return float(entry["rate"])
    return None


def _implied_bond_price(
    value_rub: float | None, qty: float | None,
    nominal: float | None, accrued_rub: float | None, fx: float | None,
) -> tuple[float | None, bool]:
    """
    Implied чистая цена (% номинала) из стоимости позиции:
      value_rub/qty = price/100 × nominal × fx + НКД(RUB)
    Формула верифицирована на portfolio-2026-07-02: RUB-бумаги сходятся с
    MOEX-ценой ±0.1 п.п.; НКД в снапшоте ВСЕГДА в рублях за бумагу (для
    замещаек — валюта расчётов MOEX), спред implied-курса USD-бумаг 0.8%.
    Возвращает (price | None, dirty) — dirty=True если НКД неизвестен
    (цена «грязная», завышение до ~coupon/freq %).
    """
    if not value_rub or not qty or not nominal or not fx:
        return None, False
    per_bond = value_rub / qty
    dirty = accrued_rub is None
    clean = per_bond - (accrued_rub or 0.0)
    if clean <= 0:
        return None, False
    return round(clean / (nominal * fx) * 100, 4), dirty


def _build_bonds(
    portfolio: dict, quotes: dict, fx_rates: dict | None = None,
    as_of_iso: str | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    Облигации из portfolio.json.bonds с IIS-3 split-логикой:
      - Итого без ИИСа > 0  →  запись account="main",  qty = Всего − ИИС
      - Итого на ИИС > 0    →  запись account="iis_3", qty = ИИС
    Если обе > 0 — создаём ДВЕ записи с одним ticker и разными account/qty.
    """
    flags: list[dict] = []
    q_lkp: dict[str, dict] = quotes or {}
    result: list[dict] = []

    for bond in (portfolio or {}).get("bonds", []):
        ticker = bond.get("Тикер")
        if not ticker or ticker == "Итог":
            continue

        val_all  = _f(bond.get("Текущая стоимость"))
        val_main = _f(bond.get("Итого без ИИСа"))
        val_iis  = _f(bond.get("Итого на ИИС"))
        qty_all  = _f(bond.get("Всего"))
        qty_iis  = _f(bond.get("ИИС"))

        if not val_all and not val_main and not val_iis:
            continue

        q = q_lkp.get(ticker, {})
        current_price, price_basis = _moex_price(q)
        price_src = "moex_iss" if current_price is not None else "last_trade"

        # PDL-4: плановая корзина/подтип + рейтинг из файла (§4.1). Тип и
        # Подтип здесь — колонки таблицы «Облигации» (НЕ «План по
        # Облигациям», §1.2), Рейтинг — детальный, отдельно от Подтип.
        plan_bucket = _text_or_none(bond.get("Тип"))
        plan_subtype = _text_or_none(bond.get("Подтип"))
        credit_rating_file = _text_or_none(bond.get("Рейтинг"))

        base: dict[str, Any] = {
            "ticker": ticker,
            "isin": q.get("isin") or bond.get("ISIN"),
            "name": bond.get("Название"),
            "current_price": current_price,
            "current_price_source": price_src,
            "current_price_ts": _price_ts(q),
            "current_price_basis": price_basis,
            "currency": "RUB",
            "asset_type": "bond",
            "is_blocked": False,
            "nominal_currency": bond.get("Валюта номинала") or q.get("currency") or "RUB",
            "nominal": _f(q.get("face_value")) or _f(bond.get("Номинал")),
            "ytm_pct": _f(q.get("ytm_pct")),
            "ytm_source": "moex_iss" if q.get("ytm_pct") is not None else None,
            "ytm_to_offer_pct": _f(q.get("ytm_to_offer_pct")),
            "coupon_pct": _f(q.get("coupon_pct")),
            "coupon_freq_per_year": _coupon_freq(q.get("coupon_period_days")),
            "next_coupon_date": q.get("next_coupon_date"),
            "accrued_int": _f(q.get("accrued_interest")),
            "maturity_date": q.get("maturity_date") or bond.get("Дата погашения"),
            "offer_date": q.get("offer_date") or bond.get("Дата оферты"),
            "duration_days": q.get("duration_days"),
            "plan_bucket": plan_bucket,
            "plan_subtype": plan_subtype,
            "plan_bucket_key": _plan_bucket_key(plan_bucket, plan_subtype),
            "credit_rating_file": credit_rating_file,
        }

        # Implied-цена, когда MOEX не отдал котировку (замещайки с src=last_trade):
        # детерминированно из value/qty/НКД(RUB)/курса ЦБ — НЕ предполагаем par.
        # Без неё carry-слой (compute_bond_carry) теряет pull-to-par до ±10 п.п.
        if base["current_price"] is None:
            pair: tuple[float, float] | None = None
            if val_all and qty_all:
                pair = (val_all, qty_all)
            elif val_iis and qty_iis:
                pair = (val_iis, qty_iis)
            fx = _fx_rate_of(fx_rates, base["nominal_currency"])
            implied, dirty = _implied_bond_price(
                pair[0] if pair else None, pair[1] if pair else None,
                base["nominal"], base["accrued_int"], fx,
            )
            if implied is not None:
                base["current_price"] = implied
                base["current_price_source"] = "implied_from_value"
                if dirty:
                    base["current_price_implied_dirty"] = True
                flags.append(_flag(
                    "assemble_bonds", "info", "implied_bond_price",
                    f"{ticker}: цена не получена с MOEX — implied из стоимости "
                    f"позиции: {implied}%"
                    + (" (грязная: НКД неизвестен)" if dirty else "") + ".",
                ))
            elif fx is None:
                flags.append(_flag(
                    "assemble_bonds", "warn", "no_fx_for_implied_price",
                    f"{ticker}: нет котировки MOEX и нет курса "
                    f"{base['nominal_currency']} — current_price = null.",
                ))

        # PDL-H: живая стоимость при полном отсутствии рыночных данных MOEX и
        # даты погашения — признак погашенного/делистингованного выпуска
        # (РУСАЛ 1Р6, погашен 05.08.2026: MOEX перестал отдавать weekly-поля,
        # позиция в выгрузке ещё висела и прошла в снапшот 08-06 как живая).
        has_value = any(v and v > 0 for v in (val_all, val_main, val_iis))
        no_moex = not any(q.get(k) is not None
                          for k in ("last", "ytm_pct", "maturity_date",
                                    "duration_days"))
        mat = _pdate(base["maturity_date"])
        asof_d = _pdate(as_of_iso)
        if has_value and base["maturity_date"] is None and no_moex:
            flags.append(_flag(
                "assemble_bonds", "warn", "bond_possibly_redeemed",
                f"{ticker}: стоимость {round(val_all or val_main or val_iis or 0)} ₽ "
                f"без даты погашения и без каких-либо данных MOEX — возможно, "
                f"выпуск погашен или делистингован; сверить выгрузку, бумагу "
                f"живой не считать.",
            ))
        elif has_value and mat is not None and asof_d is not None and mat < asof_d:
            flags.append(_flag(
                "assemble_bonds", "warn", "bond_matured_but_valued",
                f"{ticker}: дата погашения {mat.isoformat()} в прошлом, а позиция "
                f"стоит {round(val_all or val_main or val_iis or 0)} ₽ — деньги от "
                f"погашения могли не отразиться в выгрузке.",
            ))

        # PDL-7: гейты подтип↔рынок, которым нужны свежие MOEX-данные
        # (maturity_date/имя из q) — поэтому живут здесь, а не в
        # parse_portfolio.py (bond-subtypes-plan.md §5.1).

        # bond_ofz_subtype_maturity_mismatch: Подтип «>10»/«<10» — текущий
        # срок до погашения (решение владельца Q2), не срок при выпуске.
        if plan_bucket == "ОФЗ" and plan_subtype in (">10", "<10") and mat is not None and asof_d is not None:
            years_to_mat = (mat - asof_d).days / 365.25
            mismatch = (
                (plan_subtype == ">10" and years_to_mat < OFZ_MATURITY_SPLIT_YEARS)
                or (plan_subtype == "<10" and years_to_mat >= OFZ_MATURITY_SPLIT_YEARS)
            )
            if mismatch:
                flags.append(_flag(
                    "assemble_bonds", "warn", "bond_ofz_subtype_maturity_mismatch",
                    f"{ticker}: Подтип={plan_subtype}, но до погашения "
                    f"{years_to_mat:.1f} года ({mat.isoformat()}) — не "
                    f"соответствует корзине срока (Q2: текущий срок).",
                ))

        # bond_floater_subtype_mismatch: Подтип=Флоат должен подтверждаться
        # именем бумаги (MOEX SHORTNAME или Numbers Название) — и наоборот.
        floater_name_signal = _moex_confirms_floater(q.get("short_name") or base["name"])
        if plan_subtype == "Флоат" and not floater_name_signal:
            flags.append(_flag(
                "assemble_bonds", "info", "bond_floater_subtype_mismatch",
                f"{ticker}: Подтип=Флоат, но имя бумаги ({base['name']}) не "
                f"похоже на плавающий купон (best-effort эвристика).",
            ))
        elif plan_subtype not in (None, "Флоат") and floater_name_signal:
            flags.append(_flag(
                "assemble_bonds", "info", "bond_floater_subtype_mismatch",
                f"{ticker}: имя бумаги ({base['name']}) похоже на плавающий "
                f"купон, но Подтип={plan_subtype} (не Флоат).",
            ))

        # bond_rating_bucket_mismatch / bond_rating_below_ladder — лестница §4.2.
        if credit_rating_file:
            expected_bucket = rating_to_corp_bucket(credit_rating_file)
            if expected_bucket is None:
                flags.append(_flag(
                    "assemble_bonds", "info", "bond_rating_below_ladder",
                    f"{ticker}: Рейтинг={credit_rating_file} ниже «B-» / вне "
                    f"лестницы §4.2.",
                ))
            elif plan_bucket == "КОРП" and plan_subtype and expected_bucket != plan_subtype:
                flags.append(_flag(
                    "assemble_bonds", "warn", "bond_rating_bucket_mismatch",
                    f"{ticker}: Рейтинг={credit_rating_file} → корзина "
                    f"{expected_bucket}, но Подтип={plan_subtype}.",
                ))

        has_main = val_main is not None and val_main > 0
        has_iis  = val_iis  is not None and val_iis  > 0

        if has_main:
            qty_m = (int(qty_all - qty_iis)
                     if qty_all is not None and qty_iis is not None
                     else (int(qty_all) if qty_all is not None else None))
            result.append({**base, "account": "main",  "qty": qty_m, "value_rub": round(val_main, 2)})

        if has_iis:
            qty_i = int(qty_iis) if qty_iis is not None else None
            result.append({**base, "account": "iis_3", "qty": qty_i, "value_rub": round(val_iis, 2)})

        if not has_main and not has_iis and val_all and val_all > 0:
            qty_m = int(qty_all) if qty_all is not None else None
            result.append({**base, "account": "main",  "qty": qty_m, "value_rub": round(val_all, 2)})

    return result, flags


# ── Этап 4b ухода от Numbers: факт по классам и матрице валюта × класс ────────

# Внутренние имена классов — как в матрице («Акция»); в class_plan_vs_fact — как в plan.classes («Акции»).
CLASS_ORDER: tuple[str, ...] = ("Кеш", "Акция", "Облигация", "Золото", "Другое")
_CLASS_CANON: dict[str, str] = {
    "кеш": "Кеш", "кэш": "Кеш", "акция": "Акция", "акции": "Акция", "облигация": "Облигация",
    "облигации": "Облигация", "золото": "Золото", "другое": "Другое",
}
_CLASS_PLAN_NAME: dict[str, str] = {c: c for c in CLASS_ORDER} | {"Акция": "Акции"}
# Названия ручных строк «Таблицы 1», не совпадающие с тикером фонда в holdings.
_MANUAL_NAME_ALIASES: dict[str, str] = {"ренат про": "XXXXXX", "рентал про": "XXXXXX"}
_CLASS_CELL_TOL_PCT = 1.0          # class_fact_mismatch: расхождение ячейки с Numbers
_CLASS_CELL_TOL_RUB = 1000.0


def _cur(v: Any) -> str:
    c = str(v or "RUB").strip().upper()
    return {"SUR": "RUB", "RUR": "RUB"}.get(c, c)


def _bond_cur(h: dict) -> str:
    """Валюта облигации в матрице: корзина плана (USD/EUR/CNY → своя валюта, ОФЗ/КОРП → RUB — так
    считает Numbers и так привязан план корзин); нет корзины — nominal_currency."""
    b = str(h.get("plan_bucket") or "").strip().upper()
    if b in ("USD", "EUR", "CNY"):
        return b
    if b in ("ОФЗ", "КОРП"):
        return "RUB"
    return _cur(h.get("nominal_currency") or h.get("currency"))


def _canon_class(v: Any) -> str | None:
    s = _text_or_none(v)
    return _CLASS_CANON.get(s.lower()) if s else None


def _manual_type(typ: Any) -> tuple[str | None, str | None]:
    """«USD - Облигации» → («USD», «Облигация»); «RUB - ИИС» и нераспознанное → (cur, None)."""
    parts = [p.strip() for p in str(typ or "").split(" - ", 1)]
    if len(parts) != 2:
        return None, None
    return parts[0].upper() or None, _canon_class(parts[1])


def _manual_ticker(name: Any, known: set[str], funds: dict) -> str | None:
    """Тикер фонда, к которому относится имя строки «Таблицы 1» (тикер, алиас карты или константа)."""
    s = _text_or_none(name)
    if not s:
        return None
    if s.upper() in {k.upper() for k in known}:
        return next(k for k in known if k.upper() == s.upper())
    for t, spec in (funds or {}).items():
        if isinstance(spec, dict) and s.lower() in [str(a).lower() for a in spec.get("aliases") or []]:
            return t
    return _MANUAL_NAME_ALIASES.get(s.lower())


def build_class_breakdown(
    holdings: list[dict] | None,
    cash: dict | None,
    plan: dict | None,
    *,
    other_positions: list[dict] | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Факт и план по классам и по ячейкам валюта × класс (этап 4b, numbers-exit-plan.md §3.2).

    База — брокерский счёт без ИИС-3 (account == "main"). Акции: stock с ценой не cost_basis
    (замороженные вне); облигации — по nominal_currency; фонды — по карте plan.funds[T], запасной
    путь — тип строки «Таблицы 1»; деньги — cash.by_account.main в «Кеш RUB»; строки «Таблицы 1» —
    только если такой бумаги нет в holdings с ценой. Фонд > 0 без класса — class None + fund_unmapped.
    Возвращает (class_plan_vs_fact, matrix_plan_vs_fact, flags). Чистая функция, без I/O.
    """
    flags: list[dict] = []
    plan = plan or {}
    funds_map = plan.get("funds") or {}
    cells: dict[tuple[str, str | None], float] = {}

    def add(cur: str, cls: str | None, v: float) -> None:
        cells[(cur, cls)] = cells.get((cur, cls), 0.0) + v

    manual = [m for m in (other_positions if other_positions is not None else plan.get("manual_positions")) or []
              if isinstance(m, dict)]

    def _mname(m: dict) -> Any:
        return m.get("name") if m.get("name") is not None else m.get("Бумага")

    def _mtype(m: dict) -> Any:
        return m.get("type") if m.get("type") is not None else m.get("Тип")

    def _mval(m: dict) -> float:
        return _f(m.get("value_rub") if m.get("value_rub") is not None else m.get("Стоимость")) or 0.0

    main = [h for h in (holdings or []) if h.get("account") == "main"]
    priced_tickers: set[str] = set()
    for h in main:
        v = _f(h.get("value_rub")) or 0.0
        if v <= 0 or not h.get("ticker"):
            continue
        at = h.get("asset_type")
        if at == "stock" and h.get("current_price_source") != "cost_basis":
            add(_cur(h.get("currency")), "Акция", v)
        elif at == "bond":
            add(_bond_cur(h), "Облигация", v)
        elif at == "fund":
            priced_tickers.add(h["ticker"])

    used_manual: set[int] = set()
    overridden: set[int] = set()
    for h in main:
        if h.get("asset_type") != "fund" or h.get("ticker") not in priced_tickers:
            continue
        t, v = h["ticker"], _f(h.get("value_rub")) or 0.0
        spec = funds_map.get(t) if isinstance(funds_map.get(t), dict) else None
        cls = _canon_class(spec.get("class")) if spec else None
        cur = _cur(spec.get("currency")) if spec and spec.get("currency") else ""
        # запасной путь: тип строки «Таблицы 1» с этим фондом
        for m in manual:
            if _manual_ticker(_mname(m), {t}, funds_map) == t:
                used_manual.add(id(m))
                mcur, mcls = _manual_type(_mtype(m))
                if h.get("current_price_source") in ("cost_basis", "last_trade") and _mval(m) > 0:
                    flags.append(_flag("class_breakdown", "info", "manual_position_override",
                                       f"{t}: ручная оценка {_mval(m):,.0f} ₽ вместо {v:,.0f} ₽ из holdings "
                                       f"(цена не биржевая: {h.get('current_price_source')})."))
                    v = _mval(m)
                    overridden.add(id(m))
                if not (cls and cur):
                    cls, cur = cls or mcls, cur or (mcur or "")
        if cls and cur:
            add(cur, cls, v)
        else:
            add(cur or "RUB", None, v)
            flags.append(_flag("class_breakdown", "warn", "fund_unmapped",
                               f"Фонд {t} ({v:,.0f} ₽) не отнесён к классу: нет записи в plan.funds и строки "
                               f"«Таблицы 1» — стоимость в строке «не отнесён»."))

    for m in manual:
        mcur, mcls = _manual_type(_mtype(m))
        if mcls is None or mcur is None:
            continue                                   # «RUB - ИИС» и нераспознанное — вне матрицы
        if id(m) in overridden:
            continue
        if id(m) in used_manual or _manual_ticker(_mname(m), priced_tickers, funds_map):
            flags.append(_flag("class_breakdown", "info", "manual_position_duplicate",
                               f"Строка «Таблицы 1» {_mname(m)} пропущена: бумага есть в holdings с ценой "
                               f"(holdings главнее, двойного счёта нет)."))
            continue
        if _mval(m) > 0:
            add(mcur, mcls, _mval(m))

    c = cash or {}
    ba = c.get("by_account") or {}
    if _f(ba.get("main")) is not None:
        cash_main = _f(ba.get("main"))
    elif _f(c.get("total_rub")) is not None:
        cash_main = _f(c.get("total_rub")) - (_f(ba.get("iis_3")) or 0.0)
    else:
        cash_main = 0.0
    if cash_main:
        add("RUB", "Кеш", cash_main)

    total = sum(cells.values())

    def pct(x: float) -> float | None:
        return round(x / total * 100, 4) if total else None

    def row(target_share: Any, actual: float) -> dict:
        tp = round(target_share * 100, 4) if _f(target_share) is not None else None
        trub = round(target_share * total, 2) if tp is not None else None
        ap = pct(actual)
        return {"target_pct": tp, "target_rub": trub, "actual_rub": round(actual, 2), "actual_pct": ap,
                "delta_pp": round(tp - ap, 4) if tp is not None and ap is not None else None,
                "delta_rub": round(trub - actual, 2) if trub is not None else None}

    plan_classes = {_canon_class(r.get("class")): _f(r.get("share")) for r in plan.get("classes") or []
                    if _canon_class(r.get("class"))}
    by_class: dict[str | None, float] = {}
    for (cur, cls), v in cells.items():
        by_class[cls] = by_class.get(cls, 0.0) + v
    class_rows = [{"class": _CLASS_PLAN_NAME[cl], **row(plan_classes.get(cl), by_class.get(cl, 0.0))}
                  for cl in CLASS_ORDER]
    if by_class.get(None):
        class_rows.append({"class": None, **row(None, by_class[None])})

    matrix_rows: list[dict] = []
    seen: set[tuple[str, str | None]] = set()
    for r in plan.get("matrix") or []:
        cls, cur = _canon_class(r.get("class")), str(r.get("currency") or "").upper()
        if not cls or not cur or (cur, cls) in seen:
            continue
        seen.add((cur, cls))
        matrix_rows.append({"currency": cur, "class": cls, **row(_f(r.get("share")), cells.get((cur, cls), 0.0))})
    for (cur, cls), v in sorted(cells.items(), key=lambda kv: (kv[0][0], CLASS_ORDER.index(kv[0][1])
                                                             if kv[0][1] in CLASS_ORDER else 99)):
        if (cur, cls) not in seen and abs(v) > 0:
            matrix_rows.append({"currency": cur, "class": cls, **row(None, v)})
    return class_rows, matrix_rows, flags


def _class_fact_mismatch(matrix_rows: list[dict], numbers_matrix: list[dict] | None) -> list[dict]:
    """Сверка ячеек с goals.matrix[].«Сейчас» из Numbers: ≥1 % и >1000 ₽ → info class_fact_mismatch.
    «Золото» сравнивается внутри «Другое» своей валюты (в Numbers золото — «Другое USD»)."""
    flags: list[dict] = []
    if not numbers_matrix:
        return flags
    ours: dict[tuple[str, str], float] = {}
    for r in matrix_rows:
        cls = "Другое" if r["class"] == "Золото" else r["class"]
        ours[(r["currency"], cls)] = ours.get((r["currency"], cls), 0.0) + (r["actual_rub"] or 0.0)
    for n in numbers_matrix:
        key = (str(n.get("Валюта") or "").upper(), _canon_class(n.get("Бумага")))
        num = _f(n.get("Сейчас")) or 0.0
        got = ours.get(key, 0.0)
        if num and abs(got - num) > _CLASS_CELL_TOL_RUB and abs(got - num) / abs(num) * 100 >= _CLASS_CELL_TOL_PCT:
            flags.append(_flag("class_breakdown", "info", "class_fact_mismatch",
                               f"{key[0]}/{key[1]}: расчёт {got:,.0f} ₽ против Numbers {num:,.0f} ₽ "
                               f"({(got - num) / num * 100:+.1f} %)."))
    return flags


# ── без баланса: факт-колонки, которые в Numbers считались формулами (этап 6 ухода от Numbers) ──

def _ie_facts_from_holdings(portfolio: dict, holdings: list[dict] | None) -> None:
    """ie_actual.per_ticker: «Доля реальная» и дельта IE — из holdings (акции основного счёта, без ИИС-3 и
    заблокированных; доля — от стоимости акционной книги, как «Доля Реальная» листа «Акции»); ie_summary —
    тем же кодом, что у parse_portfolio. План-поля уже в per_ticker (apply_plan_primary)."""
    ia = portfolio.setdefault("ie_actual", {})
    per = ia.setdefault("per_ticker", {})
    value: dict[str, float] = {}
    for h in holdings or []:
        if (h.get("asset_type") == "stock" and h.get("account") in (None, "main")
                and h.get("status") != "blocked" and h.get("ticker")):
            value[h["ticker"]] = value.get(h["ticker"], 0.0) + (_f(h.get("value_rub")) or 0.0)
    total = sum(value.values())
    fields = ("ie_new_pct", "ie_old_pct", "ie_delta_pct", "real_share_pct", "planned_share_pct",
              "user_plan", "user_status", "user_note_ie", "user_note_ai")
    for t in sorted(set(value) | set(per)):
        row = per.setdefault(t, {})
        for k in fields:
            row.setdefault(k, None)
        new, old = _f(row.get("ie_new_pct")), _f(row.get("ie_old_pct"))
        row["ie_delta_pct"] = round(new - old, 4) if new is not None and old is not None else None
        row["real_share_pct"] = round(value.get(t, 0.0) / total * 100, 4) if total else None
    model = portfolio.get("ie_model")
    if isinstance(model, dict):
        import parse_portfolio
        active = dict(model, positions=[p for p in model.get("positions") or []
                                        if isinstance(p, dict) and p.get("active_in_model") is not False])
        portfolio["ie_summary"] = parse_portfolio.compute_ie_summary(active, ia, sorted(value))
    else:
        portfolio["ie_summary"] = None


def _trades_plan_facts(portfolio: dict, holdings: list[dict] | None, bpvf: list[dict] | None,
                       class_rows: list[dict] | None, matrix_rows: list[dict] | None) -> None:
    """Заполняет факт-колонки строк целей (goals_matrix: «Сейчас», «Доля нынешняя», «Планы», «Изменение»;
    goals_bonds_breakdown: «План сумма», «Нынешняя Сумма», «Изменение») и цель корзины в рублях
    (bonds_plan_vs_fact.target_rub = доля корзины × цель класса «Облигация») по holdings."""
    _ie_facts_from_holdings(portfolio, holdings)
    goals = portfolio.setdefault("goals", {})
    bond_target = next((r.get("target_rub") for r in class_rows or [] if r.get("class") == "Облигация"), None)
    by_key: dict[str, dict] = {}
    for e in bpvf or []:
        if e.get("target_rub") is None and e.get("target_pct") is not None and bond_target is not None:
            e["target_rub"] = round(e["target_pct"] / 100 * bond_target, 2)
            e["delta_rub"] = round(e["target_rub"] - (e.get("actual_rub") or 0.0), 2)
        by_key[e.get("bucket_key")] = e
    for row in goals.get("bonds_breakdown") or []:
        e = by_key.get(row.get("_bucket_key"))
        if e:
            row["План сумма"], row["Нынешняя Сумма"] = e.get("target_rub"), e.get("actual_rub")
            row["Изменение"] = e.get("delta_rub")
    # матрица: золото считается в «Другое» своей валюты (как в Numbers)
    cells: dict[tuple[str, str], dict] = {}
    for r in matrix_rows or []:
        cls = "Другое" if r.get("class") == "Золото" else r.get("class")
        c = cells.setdefault((r.get("currency"), cls), {"now": 0.0, "plan": None})
        c["now"] += r.get("actual_rub") or 0.0
        if r.get("target_rub") is not None:
            c["plan"] = (c["plan"] or 0.0) + r["target_rub"]
    total = sum(c["now"] for c in cells.values())
    for row in goals.get("matrix") or []:
        c = cells.get((str(row.get("Валюта") or "").upper(), _canon_class(row.get("Бумага"))))
        if c is None:
            continue
        row["Сейчас"] = round(c["now"], 2)
        row["Доля нынешняя"] = round(c["now"] / total, 6) if total else None
        row["Планы"] = round(c["plan"], 2) if c["plan"] is not None else None
        row["Изменение"] = round(c["plan"] - c["now"], 2) if c["plan"] is not None else None


# ── PDL-6: план↔факт по плановым корзинам облигаций ──────────────────────────

def _build_bonds_plan_vs_fact(
    portfolio: dict | None,
    holdings: list[dict] | None,
    plan_funds: dict | None = None,
) -> tuple[list[dict] | None, list[dict], list[dict]]:
    """
    balance_summary.bonds_plan_vs_fact: на каждую строку «План по
    Облигациям» — план (target_pct/target_rub) и факт (actual_rub),
    пересчитанный заново по holdings (свежие цены MOEX), а не взятый из
    Numbers-файла напрямую (actual_rub_file — справочно).

    База — БЕЗ ИИС-3 (Q1, §3.1): actual_rub считается только по
    account == "main". actual_rub_incl_iis — то же + account == "iis_3",
    для справки.

    ⚠️ TLCB-кейс (§3.1): TLCB — фонд, его нет на вкладке «Облигации», он
    живёт в «Tаблица 1» со строкой Тип: "USD - Облигации". Без него
    корзина USD расходится с Numbers-файлом ровно на 166 800 ₽. Правило:
    для валютных корзин без подтипа actual_rub += Σ позиций «Tаблица 1» с
    Тип == "<корзина> - Облигации".

    Возвращает (bonds_plan_vs_fact | None, bonds_plan_vs_fact_iis, flags).
    bonds_plan_vs_fact_iis — параллельный факт по account == "iis_3" БЕЗ
    плана (ИИС-3 не участвует в «План по Облигациям», Q1).
    """
    flags: list[dict] = []
    bonds_breakdown = ((portfolio or {}).get("goals") or {}).get("bonds_breakdown") or []
    other_positions = (portfolio or {}).get("other_positions") or []
    plan_rows = [r for r in bonds_breakdown if _text_or_none(r.get("Тип")) not in (None, "Итог")]
    if not plan_rows:
        return None, [], flags

    bond_holdings = [h for h in (holdings or []) if h.get("asset_type") == "bond"]

    fund_bond_rows = [
        r for r in other_positions
        if str(r.get("Тип") or "").strip().endswith(" - Облигации")
    ]
    matched_fund_ids: set[int] = set()
    funds_map = {t: s for t, s in (plan_funds or {}).items() if isinstance(s, dict)}

    def _map_members(bucket_key: str | None) -> list[dict]:
        # Фонды-члены корзины по карте plan.funds[T].bucket (этап 4b): стоимость — из holdings.
        if not bucket_key:
            return []
        want = {t for t, s in funds_map.items() if s.get("bucket") == bucket_key}
        return [h for h in (holdings or []) if h.get("asset_type") == "fund" and h.get("account") == "main"
                and h.get("ticker") in want and (_f(h.get("value_rub")) or 0.0) > 0]

    def _fund_members(typ: str | None, subtype: str | None) -> list[dict]:
        # Только валютные корзины без подтипа (§3.1) — ОФЗ/КОРП-корзины
        # своих фондов в «Tаблица 1» не имеют.
        if not typ or subtype:
            return []
        prefix = f"{typ} - Облигации"
        return [r for r in fund_bond_rows if str(r.get("Тип") or "").strip() == prefix]

    result: list[dict] = []
    total_actual_excl_iis = 0.0

    for row in plan_rows:
        typ = _text_or_none(row.get("Тип"))
        subtype = _text_or_none(row.get("_subtype"))
        bucket_key = row.get("_bucket_key") or _plan_bucket_key(typ, subtype)
        target_pct = round((_f(row.get("Доля План")) or 0.0) * 100, 4)
        target_rub = _f(row.get("План сумма"))
        actual_rub_file = _f(row.get("Нынешняя Сумма"))

        main_bonds = [h for h in bond_holdings
                      if h.get("account") == "main" and h.get("plan_bucket_key") == bucket_key]
        iis_bonds = [h for h in bond_holdings
                     if h.get("account") == "iis_3" and h.get("plan_bucket_key") == bucket_key]
        fund_rows = _fund_members(typ, subtype) if not subtype else []
        map_members = _map_members(bucket_key)
        map_tickers = {h["ticker"] for h in map_members}
        for fr in fund_rows:
            matched_fund_ids.add(id(fr))
        # запасной путь «Таблица 1»: строку фонда, уже учтённого картой, не считать второй раз
        fund_rows = [fr for fr in fund_rows
                     if not _manual_ticker(fr.get("Бумага"), map_tickers, funds_map)]

        actual_main = sum(_f(h.get("value_rub")) or 0.0 for h in main_bonds)
        actual_fund = (sum(_f(fr.get("Стоимость")) or 0.0 for fr in fund_rows)
                       + sum(_f(h.get("value_rub")) or 0.0 for h in map_members))
        actual_rub = round(actual_main + actual_fund, 2)
        actual_iis = sum(_f(h.get("value_rub")) or 0.0 for h in iis_bonds)
        actual_rub_incl_iis = round(actual_rub + actual_iis, 2)

        total_actual_excl_iis += actual_rub

        result.append({
            "bucket_key": bucket_key,
            "type": typ,
            "subtype": subtype,
            "target_pct": target_pct,
            "target_rub": target_rub,
            "actual_rub": actual_rub,
            "actual_rub_incl_iis": actual_rub_incl_iis,
            "actual_rub_file": actual_rub_file,
        })

        # bond_plan_fact_stale: Numbers-файл разошёлся со свежими MOEX-ценами.
        if actual_rub_file is not None and actual_rub_file > 0:
            stale_pct = abs(actual_rub - actual_rub_file) / actual_rub_file
            if stale_pct > 0.01:
                flags.append(_flag(
                    "bonds_plan_vs_fact", "warn", "bond_plan_fact_stale",
                    f"{bucket_key}: факт по holdings {actual_rub:,.0f} ₽ "
                    f"разошёлся с Numbers-файлом {actual_rub_file:,.0f} ₽ на "
                    f"{stale_pct * 100:.1f}% — Numbers-файл устарел "
                    f"относительно текущих котировок MOEX.",
                ))

    # bond_bucket_not_in_plan: бумага основного счёта (облигация или фонд плана) в корзине, которой нет в плане, — её
    # стоимость выпала из корзин, сумма корзин меньше суммы облигаций основного счёта. ИИС-3 в план не входит.
    plan_keys = {e["bucket_key"] for e in result}
    for h in bond_holdings:
        if h.get("account") != "main":
            continue
        bk, val = h.get("plan_bucket_key"), _f(h.get("value_rub")) or 0.0
        if val > 0 and bk not in plan_keys:
            flags.append(_flag(
                "bonds_plan_vs_fact", "warn", "bond_bucket_not_in_plan",
                f"{h.get('name') or h.get('ticker')} ({h.get('ticker')}): корзина {bk or 'не задана'} "
                f"отсутствует в «План по Облигациям» — {val:,.0f} ₽ не попали ни в одну корзину "
                f"bonds_plan_vs_fact (проверь Тип/Подтип бумаги в plan.json bonds).",
            ))
    for t, spec in sorted(funds_map.items()):
        if spec.get("bucket") and spec.get("bucket") not in plan_keys:
            for h in (holdings or []):
                if h.get("asset_type") == "fund" and h.get("account") == "main" and h.get("ticker") == t \
                        and (_f(h.get("value_rub")) or 0.0) > 0:
                    flags.append(_flag(
                        "bonds_plan_vs_fact", "warn", "bond_bucket_not_in_plan",
                        f"Фонд {h.get('name') or t} ({t}): корзина {spec.get('bucket')} из plan.json funds "
                        f"отсутствует в «План по Облигациям» — {_f(h.get('value_rub')):,.0f} ₽ не попали в корзины.",
                    ))

    # delta_rub/delta_pp — после того, как известна общая факт-база (excl_iis).
    for entry in result:
        target_rub = entry["target_rub"]
        actual_rub = entry["actual_rub"]
        entry["delta_rub"] = (
            round(target_rub - actual_rub, 2) if target_rub is not None else None
        )
        actual_pct = (
            round(actual_rub / total_actual_excl_iis * 100, 4)
            if total_actual_excl_iis else None
        )
        entry["actual_pct"] = actual_pct
        entry["delta_pp"] = (
            round(entry["target_pct"] - actual_pct, 4)
            if entry["target_pct"] is not None and actual_pct is not None
            else None
        )

    # bucket_fund_member_missing: фонд «* - Облигации» в «Tаблица 1», не
    # попавший ни в одну плановую корзину (TLCB-кейс наоборот — «сирота»).
    for fr in fund_bond_rows:
        if id(fr) not in matched_fund_ids:
            flags.append(_flag(
                "bonds_plan_vs_fact", "info", "bucket_fund_member_missing",
                f"Позиция «Tаблица 1» {fr.get('Бумага', '?')} "
                f"(Тип={fr.get('Тип')}) не учтена ни в одной плановой "
                f"корзине bonds_plan_vs_fact.",
            ))

    # bonds_plan_vs_fact_iis — факт по подтипам ИИС-3, БЕЗ плана (Q1).
    iis_bucket_totals: dict[str, dict] = {}
    for h in bond_holdings:
        if h.get("account") != "iis_3":
            continue
        bk = h.get("plan_bucket_key")
        if not bk:
            continue
        slot = iis_bucket_totals.setdefault(bk, {
            "bucket_key": bk,
            "type": h.get("plan_bucket"),
            "subtype": h.get("plan_subtype"),
            "actual_rub": 0.0,
        })
        slot["actual_rub"] += _f(h.get("value_rub")) or 0.0
    iis_result = [
        {**v, "actual_rub": round(v["actual_rub"], 2)}
        for v in sorted(iis_bucket_totals.values(), key=lambda x: x["bucket_key"])
    ]

    return result, iis_result, flags


# PDL-14 (калибровка 2026-08-19): порог расхождения баланса и реконструкции
# ПОСЛЕ сведения баз. Не менять, не перемерив остаток — обоснование в docstring
# _check_balance_vs_trades_drift.
BALANCE_VS_TRADES_DRIFT_THRESHOLD = 0.01


def _check_balance_vs_trades_drift(
    portfolio: dict | None,
    returns: dict | None,
    holdings: list[dict] | None = None,
    actual_cash_rub: float | None = None,
    fx_rates: dict | None = None,
) -> dict | None:
    """balance_total_vs_trades_drift (info, PDL-7 → PDL-14): МОНИТОР
    реконструкции из трейдов, НЕ валидатор Numbers-файла.

    Базы сводятся ДО сравнения (PDL-14) — иначе гейт мерил не то, что называл:

    1. **Кэш.** Реконструированный из сделок кэш расходится с фактическим на
       постоянную историческую дыру (+357 048 ₽ на 19.08.2026 при baseline
       358 175 ₽). Её уже мониторит отдельный гейт `cash_drift_changed` — со
       своим baseline и порогом в рублях. Складывая её сюда, гейт удваивал
       учёт, и кассовый дрейф ДОМИНИРОВАЛ над позиционным сигналом (2.4 п.п.
       из 3.6). Поэтому в сравнение идёт фактический `cash.total_rub`, а не
       `snapshot_current.cash_balance_rub`.
    2. **НКД.** Реконструкция оценивает облигации по ЧИСТОЙ цене MOEX, а
       «Имеется» в файле владельца отражает IntelInvest, то есть ГРЯЗНУЮ
       (цена + НКД). На 19.08.2026 это 117 740 ₽ — 0.8% NAV, постоянный сдвиг,
       гуляющий по купонному циклу. НКД добавляется к реконструкции.
       С 2026-10-12 portfolio_returns сам оценивает облигации грязной ценой
       (`parameters.bond_value_basis: "dirty"`) — тогда НКД уже внутри
       `total_value_rub`, и второй раз его прибавлять нельзя (+≈130 тыс. ₽,
       ≈0.9% NAV при пороге 1% — ложные срабатывания). Без поля — старый
       returns.json с чистой оценкой, НКД добавляется как раньше.

    После сведения остаток — 62 630 ₽ (0.42% на файле, сохранённом в день
    прогона): чистая разница цен между выгрузкой владельца и живым MOEX.
    Отсюда порог 1%: ~2.4× запаса над измеренным шумом, ловит дыру от
    ~150 000 ₽ — меньше любой отдельной позиции портфеля, кроме хвоста.

    Старый порог 2% на несведённых базах давал ЛОЖНОЕ спокойствие: −1.56% в
    августе складывались из утечка необнулённых блокировок
    (PDL-12), кассовый дрейф и НКД, которые взаимно
    гасились. Дефект был, гейт молчал.

    Главный источник ЛОЖНЫХ срабатываний после калибровки — устаревший
    Numbers-файл: если владелец сохранил баланс несколько дней назад, цены в
    нём отстали от MOEX, и остаток растёт пропорционально движению рынка.
    Поэтому severity остаётся `info`, а вопрос свежести файла идёт в
    сообщении первым.

    Проверка молча пропускается, если не хватает любого из входов
    (portfolio / returns / holdings / фактический кэш): считать разницу на
    неполных базах хуже, чем не считать вовсе.
    """
    # holdings проверяется на `is None`, а не на пустоту: пустой список —
    # это «позиций нет», а не «данные не пришли».
    if (not portfolio or not returns or holdings is None
            or actual_cash_rub is None):
        return None
    summary = portfolio.get("summary") or {}
    balance_total = None
    for k, v in summary.items():
        if "имеется" in str(k).strip().lower() and isinstance(v, (int, float)):
            balance_total = float(v)
            break
    snap = (returns or {}).get("snapshot_current") or {}
    trades_total = _f(snap.get("total_value_rub"))
    recon_cash = _f(snap.get("cash_balance_rub"))
    if not balance_total or trades_total is None or recon_cash is None:
        return None

    positions_rub = trades_total - recon_cash
    already_dirty = (
        ((returns or {}).get("parameters") or {}).get("bond_value_basis") == "dirty"
    )

    # НКД котируется в валюте ТОРГОВ бумаги (holdings[].currency), не в валюте
    # номинала: замещайки с номиналом в USD торгуются на MOEX за рубли, и
    # ACCRUEDINT по ним приходит рублёвым.
    nkd_rub = 0.0
    nkd_missing: list[str] = []
    for h in holdings:
        if already_dirty:
            break
        if h.get("asset_type") != "bond" or h.get("status") == "blocked":
            continue
        ai, qty = h.get("accrued_int"), h.get("qty")
        if not isinstance(ai, (int, float)) or not isinstance(qty, (int, float)):
            continue
        rate = _fx_rate_of(fx_rates, h.get("currency"))
        if rate is None:
            nkd_missing.append(str(h.get("ticker") or "?"))
            continue
        nkd_rub += ai * qty * rate

    comparable = positions_rub + nkd_rub + float(actual_cash_rub)
    drift_rub = balance_total - comparable
    drift_pct = abs(drift_rub) / balance_total
    if drift_pct <= BALANCE_VS_TRADES_DRIFT_THRESHOLD:
        return None

    tail = ""
    if nkd_missing:
        tail = (f" НКД не учтён по {len(nkd_missing)} бумагам без курса: "
                f"{', '.join(nkd_missing[:5])} — остаток завышен на их НКД.")
    return _flag(
        "balance_vs_trades", "info", "balance_total_vs_trades_drift",
        f"Реконструкция из сделок разошлась с балансом на {drift_rub:+,.0f} ₽ "
        f"({drift_pct * 100:.2f}% при пороге "
        f"{BALANCE_VS_TRADES_DRIFT_THRESHOLD * 100:.1f}%): баланс "
        f"{balance_total:,.0f} ₽ против {comparable:,.0f} ₽ = позиции "
        f"{positions_rub:,.0f} + НКД {nkd_rub:,.0f} + фактический кэш "
        f"{actual_cash_rub:,.0f}. Кассовый дрейф в сравнение НЕ входит — его "
        f"мониторит cash_drift_changed. Сначала проверь дату сохранения "
        f"Numbers-файла: устаревшие цены в нём — самая частая причина. Если "
        f"файл свежий, ищи позицию, которой нет в реконструкции (или лишнюю "
        f"в ней), — проверять надо реконструкцию, не файл.{tail}",
    )


# ── bond cashflow calendar (контрактные потоки, не прогноз) ──────────────────

def _add_months_keep_day(d: datetime.date, months: int) -> datetime.date:
    idx = d.year * 12 + (d.month - 1) + months
    y, m = idx // 12, idx % 12 + 1
    import calendar as _cal
    return datetime.date(y, m, min(d.day, _cal.monthrange(y, m)[1]))


def _pdate(s: Any) -> datetime.date | None:
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.date.fromisoformat(s.strip()[:10])
    except ValueError:
        return None


def _build_bond_cashflow(
    holdings: list[dict],
    fx_rates: dict | None,
    as_of_iso: str,
    months: int = 12,
) -> dict:
    """
    Контрактный денежный поток по облигациям на ближайшие `months` месяцев:
    купоны (qty × nominal × coupon_pct/freq × курс ЦБ) + погашения по номиналу.
    Оферты — ОТДЕЛЬНОЙ строкой (пут держателя — потенциальный, не гарантированный
    приток; в carry-слое stress оферта консервативно трактуется как погашение,
    в кассовом календаре их смешивать нельзя).

    Честность: FX-потоки — по ТЕКУЩЕМУ курсу ЦБ (`fx_rate_used`; курс на дату
    выплаты неизвестен); флоатеры — по текущей ставке купона; амортизация
    (частичные гашения) v1 не покрыта. Потребитель — вкладка «Облигации»
    HTML-viewer (offline, из снапшота).
    """
    as_of = _pdate(as_of_iso) or datetime.date.today()
    window_end = _add_months_keep_day(as_of, months)

    # Агрегируем qty по тикеру (main + iis_3 — поток общий по портфелю)
    by_ticker: dict[str, dict] = {}
    for h in holdings or []:
        if (h.get("asset_type") or "") != "bond" or h.get("is_blocked"):
            continue
        t = h.get("ticker")
        if not t:
            continue
        slot = by_ticker.setdefault(t, {"holding": h, "qty": 0.0, "qty_known": True})
        if h.get("qty") is None:
            slot["qty_known"] = False
        else:
            slot["qty"] += float(h["qty"])

    detail: list[dict] = []
    by_month: dict[str, dict[str, float]] = {}
    flags: list[str] = []

    def _acc(d: datetime.date, kind: str, amount: float) -> None:
        key = d.isoformat()[:7]
        slot = by_month.setdefault(
            key, {"coupons_rub": 0.0, "redemptions_rub": 0.0, "offers_rub": 0.0})
        slot[kind] += amount

    for t, slot in sorted(by_ticker.items()):
        h = slot["holding"]
        if not slot["qty_known"] or slot["qty"] <= 0:
            flags.append(f"{t}: qty неизвестно — потоки не посчитаны")
            continue
        qty = slot["qty"]
        nominal = h.get("nominal")
        cur = (h.get("nominal_currency") or "RUB").upper()
        fx = _fx_rate_of(fx_rates, cur)
        if fx is None:
            flags.append(f"{t}: нет курса {cur} — потоки не посчитаны")
            continue
        if not nominal:
            flags.append(f"{t}: нет номинала — потоки не посчитаны")
            continue

        maturity = _pdate(h.get("maturity_date"))
        offer = _pdate(h.get("offer_date"))
        coupon_pct = h.get("coupon_pct")
        freq = int(h.get("coupon_freq_per_year") or 0)

        # купоны
        if coupon_pct and freq > 0:
            step = max(1, round(12 / freq))
            first = _pdate(h.get("next_coupon_date"))
            entry_flags: list[str] = []
            if first is None:
                first = _add_months_keep_day(as_of, step)
                entry_flags.append("schedule_estimated")
            d = first
            guard = 0
            while d <= as_of and guard < 60:
                d = _add_months_keep_day(d, step)
                guard += 1
            coupon_end = min(maturity, window_end) if maturity else window_end
            amount = round(qty * float(nominal) * (float(coupon_pct) / 100.0)
                           / freq * fx, 2)
            while d <= coupon_end and guard < 60:
                detail.append({
                    "ticker": t, "name": h.get("name"), "date": d.isoformat(),
                    "kind": "coupon", "amount_rub": amount, "currency": cur,
                    "fx_rate_used": fx if cur not in ("RUB", "SUR", "RUR") else None,
                    "flags": list(entry_flags),
                })
                _acc(d, "coupons_rub", amount)
                d = _add_months_keep_day(d, step)
                guard += 1
        elif coupon_pct:
            flags.append(f"{t}: неизвестна частота купона — купоны не посчитаны")

        # погашение по номиналу
        if maturity and as_of < maturity <= window_end:
            amount = round(qty * float(nominal) * fx, 2)
            detail.append({
                "ticker": t, "name": h.get("name"), "date": maturity.isoformat(),
                "kind": "redemption", "amount_rub": amount, "currency": cur,
                "fx_rate_used": fx if cur not in ("RUB", "SUR", "RUR") else None,
                "flags": [],
            })
            _acc(maturity, "redemptions_rub", amount)

        # оферта — потенциальный приток (пут держателя), отдельно от погашений
        if offer and as_of < offer <= window_end and offer != maturity:
            amount = round(qty * float(nominal) * fx, 2)
            detail.append({
                "ticker": t, "name": h.get("name"), "date": offer.isoformat(),
                "kind": "offer", "amount_rub": amount, "currency": cur,
                "fx_rate_used": fx if cur not in ("RUB", "SUR", "RUR") else None,
                "flags": ["optional_put"],
            })
            _acc(offer, "offers_rub", amount)

    detail.sort(key=lambda e: (e["date"], e["ticker"]))
    by_month = {k: {kk: round(vv, 2) for kk, vv in v.items()}
                for k, v in sorted(by_month.items())}
    totals = {
        "coupons_rub": round(sum(v["coupons_rub"] for v in by_month.values()), 2),
        "redemptions_rub": round(sum(v["redemptions_rub"] for v in by_month.values()), 2),
        "offers_rub": round(sum(v["offers_rub"] for v in by_month.values()), 2),
    }
    return {
        "horizon_months": months,
        "as_of": as_of.isoformat(),
        "by_month": by_month,
        "totals": totals,
        "detail": detail,
        "flags": flags,
        "notes": [
            "Контрактные потоки: купоны по текущей ставке (флоатеры — ориентировочно), "
            "FX — по текущему курсу ЦБ (fx_rate_used), амортизация не покрыта.",
            "offers_rub — потенциальный приток (пут держателя), НЕ гарантированный.",
        ],
    }


# ── holdings: funds / other ───────────────────────────────────────────────────

def _fund_avg_cost(row: dict | None, pos: dict | None) -> tuple[float | None, str | None]:
    """Средняя цена фонда: колонка баланса → сделки → None (без подмены value/qty)."""
    avg = _avg_cost_from_row(row) if row else None
    if avg is not None and avg > 0:
        return round(avg, 4), "balance"
    avg = _f((pos or {}).get("avg_cost_rub"))
    if avg is not None and avg > 0:
        return round(avg, 4), "trades"
    return None, None


def _build_funds(portfolio: dict, quotes: dict, returns: dict) -> list[dict]:
    """
    Фонды из portfolio.json.other_positions (не ИИС).
    Дополняется позициями из returns с type='fund', которых нет в balance.

    Средняя цена (2026-10-28): из колонки баланса («Ср, Цена» — avg_cost_source
    "balance"), иначе из сделок (reconstruct_positions, avg_cost_source "trades");
    нет ни того ни другого — None (вьюер считает «по покупкам» сам). Раньше поле
    фондам не писалось вовсе — карточка фонда была без средней и прибыли по сделкам.
    """
    q_lkp: dict[str, dict] = quotes or {}
    snap = (returns or {}).get("snapshot_current", {})

    # fund-позиции из returns
    returns_funds: dict[str, dict] = {
        pos["ticker"]: pos
        for pos in snap.get("positions", [])
        if pos.get("type") == "fund" and not pos.get("is_blocked")
        and _f(pos.get("qty")) and _f(pos.get("qty")) > 0
    }

    seen: set[str] = set()
    result: list[dict] = []

    for row in (portfolio or {}).get("other_positions", []):
        if "ИИС" in str(row.get("Тип") or "").upper():
            continue
        ticker = row.get("Тикер")
        val = _f(row.get("Стоимость"))
        if not ticker or not val or val <= 0:
            continue
        seen.add(ticker)

        q = q_lkp.get(ticker, {})
        current_price, price_basis = _moex_price(q)
        price_src = "moex_iss" if current_price is not None else "last_trade"
        qty = (_f(row.get("Кол-во")) or _f(row.get("Количество"))
               or (_f(returns_funds.get(ticker, {}).get("qty"))))
        avg_cost, avg_src = _fund_avg_cost(row, returns_funds.get(ticker))

        result.append({
            "ticker": ticker,
            "isin": q.get("isin"),
            "name": row.get("Название"),
            "qty": qty,
            "avg_cost_rub": avg_cost,
            "avg_cost_source": avg_src,
            "current_price": current_price,
            "current_price_source": price_src,
            "current_price_ts": _price_ts(q),
            "current_price_basis": price_basis,
            "value_rub": round(val, 2),
            "currency": "RUB",
            "asset_type": "fund",
            "account": "main",
            "is_blocked": False,
            "nominal_currency": None,
            "ytm_pct": None,
            "ytm_source": None,
        })

    # Фонды из returns, которых нет в balance
    for ticker, pos in returns_funds.items():
        if ticker in seen:
            continue
        qty = _f(pos.get("qty"))
        val = _f(pos.get("value_rub"))
        if not qty or qty <= 0:
            continue
        q = q_lkp.get(ticker, {})
        current_price, price_basis = _moex_price(q)
        avg_cost, avg_src = _fund_avg_cost(None, pos)
        result.append({
            "ticker": ticker,
            "isin": q.get("isin"),
            "name": pos.get("name"),
            "qty": qty,
            "avg_cost_rub": avg_cost,
            "avg_cost_source": avg_src,
            "current_price": current_price,
            "current_price_source": "moex_iss" if current_price is not None else _price_source(pos.get("price_source")),
            "current_price_ts": _price_ts(q),
            "current_price_basis": price_basis,
            "value_rub": round(val, 2) if val else None,
            "currency": pos.get("currency", "RUB"),
            "asset_type": "fund",
            "account": "main",
            "is_blocked": False,
        })

    return result


# ── holdings: заблокированные позиции из returns ─────────────────────────────

def _build_blocked_positions(
    returns: dict | None, seen_tickers: set[str],
) -> tuple[list[dict], list[dict]]:
    """
    Замороженные позиции (FinEx/RSH*/TBIO и пр.) из returns.snapshot_current.

    portfolio_returns помечает их is_blocked (classify_blocked) и оценивает по
    стратегии --blocked-value. Раньше эти позиции ВООБЩЕ выпадали из holdings
    (невидимы для снапшота, status_summary и downstream) — теперь эмитятся с
    is_blocked=True, статус blocked проставит _apply_position_status.

    qty достоверны: Корректировки-синхронизации IntelInvest («на основе
    указанного баланса в загружаемом отчёте») по замороженным бумагам
    фиктивны — бумаги лежат на счетах, чьи отчёты не грузятся (10.04.2026
    синхронизация массово списала их qty; позиции живы — подтверждено
    владельцем 2026-07-04, FXUS 1504 на ВКС). Фильтруются в
    portfolio_returns.apply_corrections (только blocked-бумаги).

    ⚠️ Оценка: default 'zero' (консервативно). Режим 'last_trade' для FinEx
    НЕ включать без починки: last_known_trade_price берёт sell-ногу сплит-пары
    (до-сплитовая цена × post-split qty → завышение до 100×, кейс FXRL
    4.36 млн vs реальных ~38 тыс. 2026-07) — value_rub=0 честнее выдуманной
    цифры, warning-флаг отражает.

    Коллизия тикеров: T (AT&T, USD) дедупом отбрасывается в пользу
    Т-Технологии (RUB) — снапшот ключует holdings по ticker без валюты.
    """
    flags: list[dict] = []
    snap = (returns or {}).get("snapshot_current", {})
    result: list[dict] = []
    zero_valued: list[str] = []

    for pos in snap.get("positions", []):
        if not pos.get("is_blocked"):
            continue
        ticker = pos.get("ticker")
        qty = _f(pos.get("qty"))
        if not ticker or ticker in seen_tickers or not qty or qty <= 0:
            continue
        value = _f(pos.get("value_rub"))
        at = pos.get("type")
        result.append({
            "ticker": ticker,
            "isin": None,
            "name": pos.get("name"),
            "qty": qty,
            "avg_cost_rub": (round(_f(pos.get("cost_basis_rub")) / qty, 4)
                             if _f(pos.get("cost_basis_rub")) and qty else None),
            "current_price": round(value / qty, 4) if value and qty else None,
            "current_price_source": _price_source(pos.get("price_source")),
            "current_price_ts": None,
            "value_rub": round(value, 2) if value is not None else None,
            "currency": pos.get("currency", "RUB"),
            "asset_type": at if at in ("stock", "bond", "fund") else "other",
            "account": "main",
            "is_blocked": True,
            "status_note": ("Заблокированная иностранная бумага (санкционная "
                            "заморозка 2022, не торгуется); оценка по "
                            "стратегии --blocked-value (default 0 — "
                            "консервативно, см. флаг снапшота)."),
            "nominal_currency": None,
            "ytm_pct": None,
            "ytm_source": None,
        })
        seen_tickers.add(ticker)
        if not value:
            zero_valued.append(ticker)

    if result:
        total = sum(h["value_rub"] or 0 for h in result)
        flags.append(_flag(
            "assemble_blocked", "info", "blocked_positions_included",
            f"Заблокированные позиции из returns включены в holdings: "
            f"{len(result)} шт., {total:,.0f} ₽ (status=blocked, "
            f"вне активных агрегатов downstream).",
        ))
    if zero_valued:
        flags.append(_flag(
            "assemble_blocked", "warning", "blocked_positions_zero_valued",
            f"{len(zero_valued)} заблокированных позиций оценены в 0 "
            f"(режим --blocked-value zero, консервативно): "
            f"{', '.join(zero_valued[:5])}"
            + ("..." if len(zero_valued) > 5 else "")
            + ". Оценка last_trade для FinEx ненадёжна (сплит-пары) — "
              "бумажную стоимость сверять с IntelInvest вручную.",
        ))
    return result, flags


# ── per_instrument_xirr ───────────────────────────────────────────────────────

def _secid_to_isin(
    holdings: list | None, returns: dict | None,
) -> dict[str, str]:
    """SECID (ключ per_security: код IntelInvest/MOEX) → ISIN из holdings.

    ОФЗ в «Общем балансе» стоят под ISIN (RU000A106E90), в выгрузке сделок и
    per_security — под биржевым кодом (SU26243RMFS4); корпоративные облигации и
    акции совпадают. Общего поля нет, мост — название бумаги («ОФЗ 26243»):
    returns.snapshot_current.positions[].name (SECID) ↔ holdings[].name (ISIN).
    Тот же мост, что trades_index в decision_journal.py. Название, которому
    соответствует >1 разных ISIN, не сопоставляется (честнее пропуск, чем ошибка).
    """
    by_name: dict[str, set[str]] = {}
    by_ticker: dict[str, str] = {}
    for h in holdings or []:
        if not isinstance(h, dict) or not h.get("isin"):
            continue
        by_ticker[str(h.get("ticker"))] = h["isin"]
        if h.get("asset_type") == "bond" and h.get("name"):
            by_name.setdefault(str(h["name"]).strip(), set()).add(h["isin"])
    out: dict[str, str] = dict(by_ticker)
    for pos in ((returns or {}).get("snapshot_current") or {}).get("positions") or []:
        if not isinstance(pos, dict) or pos.get("type") != "bond":
            continue
        t, nm = pos.get("ticker"), str(pos.get("name") or "").strip()
        isins = by_name.get(nm)
        if t and t not in out and isins and len(isins) == 1:
            out[str(t)] = next(iter(isins))
    return out


def _resolve_iis_flows(iis_returns: dict | None, carry_sources: list[dict] | None) -> dict:
    """Потоки ИИС-3 для разбивки по счетам: {source: export|carried|none, file_last_operation, flows}.

    export — из свежей выгрузки ИИС-3 (iis_returns.account_flows); carried — из последнего снапшота, где они
    есть (выгрузки ИИС-3 к сборке нет; сделки ИИС-3 после её даты неизвестны); none — нечего вычитать.
    """
    if iis_returns and iis_returns.get("account_flows") is not None:
        return {"source": "export", "file_last_operation": iis_returns.get("file_last_operation"),
                "flows": iis_returns["account_flows"]}
    if iis_returns is None:
        for src in carry_sources or []:
            blk = src.get("iis_account_flows") if isinstance(src, dict) else None
            if isinstance(blk, dict) and isinstance(blk.get("flows"), dict):
                return {"source": "carried", "file_last_operation": blk.get("file_last_operation"),
                        "flows": blk["flows"]}
    return {"source": "none", "file_last_operation": None, "flows": {}}


def _iis_qty_in_holdings(holdings: list | None, ticker: str, isin: str | None) -> float:
    return sum(float(h.get("qty") or 0.0) for h in holdings or []
               if isinstance(h, dict) and h.get("account") == "iis_3"
               and (h.get("ticker") == ticker or (isin and h.get("isin") == isin)))


_ACC_SUM_KEYS = ("buy_total_rub", "sell_total_rub", "coupons_rub", "dividends_rub", "amortization_rub",
                 "corr_buy_rub", "corr_sell_rub")


def _read_xirr_frac(data: dict) -> float | None:
    """Ставка записи per_security как доля: xirr_frac как есть; старый формат (xirr в процентах) делится на 100."""
    v = _f(data.get("xirr_frac"))
    if v is not None:
        return v
    old = _f(data.get("xirr"))
    return old / 100.0 if old is not None else None


def _split_by_account(data: dict, iis: dict, as_of: str | None) -> dict | None:
    """Разбивка записи per_security по счетам: {main, iis_3} или None (бумага не на обоих счетах / данных нет).

    Основная выгрузка несёт и сделки ИИС-3, поэтому суммарные потоки (per_security.cashflows) = основной +
    ИИС-3. Потоки ИИС-3 — из его выгрузки (iis_returns.account_flows): купоны и дивиденды берутся по фактическим
    зачислениям счёта, а не делятся по позиции на дату записи. Основной = суммарное минус ИИС-3.
    Терминальная стоимость делится по количеству на счёте (цена одна). Суммы счетов складываются в суммарные
    (pnl_rub — ровно). Любая нестыковка (потока ИИС-3 нет в суммарных, остаток основного < 0) → None.
    """
    from collections import Counter
    import datetime as dt
    import portfolio_returns as pr
    cfs, qty_now, mv, pnl = data.get("cashflows"), _f(data.get("qty_now")), _f(data.get("market_value_rub")), _f(data.get("pnl_rub"))
    if not cfs or not as_of or qty_now is None or mv is None or pnl is None or not iis.get("cashflows"):
        return None
    ctr = bond_locked.account_counters(cfs, mv, iis["cashflows"], as_of)     # потоки счетов без терминала
    if ctr is None:
        return None
    main_c, iis_c = ctr
    qty_iis = float(iis.get("qty_now") or 0.0)
    qty_main = qty_now - qty_iis
    if qty_main < -1e-6 or qty_iis < -1e-6:
        return None
    unit = mv / qty_now if qty_now > 1e-9 else 0.0
    mv_iis = round(min(max(qty_iis, 0.0), qty_now) * unit, 2)
    mv_main = round(mv - mv_iis, 2)
    iis_part = {k: _f(iis.get(k)) or 0.0 for k in _ACC_SUM_KEYS}
    main_part = {}
    for k in _ACC_SUM_KEYS:
        v = (_f(data.get(k)) or 0.0) - iis_part[k]
        if v < -1.0:
            return None
        main_part[k] = round(max(v, 0.0), 2)

    def _pnl(p: dict, v: float) -> float:
        return (p["sell_total_rub"] + p["coupons_rub"] + p["dividends_rub"] + p["amortization_rub"]
                + p["corr_sell_rub"] + v) - (p["buy_total_rub"] + p["corr_buy_rub"])

    pnl_iis = round(_pnl(iis_part, mv_iis), 2)
    asof_d = dt.date.fromisoformat(str(as_of)[:10])

    def _xirr(counter, v: float) -> float | None:
        flows = [(dt.date.fromisoformat(d), c / 100.0) for (d, c), n in counter.items() for _ in range(n)]
        if v > 0:
            flows.append((asof_d, v))
        try:
            r = pr.xirr(sorted(flows, key=lambda x: x[0]))
        except Exception:                                                           # noqa: BLE001
            return None
        return round(r, 6) if r is not None else None

    def _entry(part: dict, v: float, q: float, p: float, counter, first: str) -> dict:
        e = {"xirr": _xirr(counter, v), "pnl_rub": p, **part, "market_value_rub": v,
             "qty_now": round(max(q, 0.0), 6), "first_trade_date": first}
        return {k: x for k, x in e.items() if x is not None}

    first_main = min(d for (d, _c) in main_c)
    return {
        "main": _entry(main_part, mv_main, qty_main, round(pnl - pnl_iis, 2), main_c, first_main),
        "iis_3": _entry(iis_part, mv_iis, qty_iis, pnl_iis, iis_c, iis.get("first_trade_date") or first_main),
    }


def _build_per_instrument_xirr(
    per_security: dict, net_threshold_rub: float | None = None,
    holdings: list | None = None, returns: dict | None = None,
    iis_flows: dict | None = None, as_of: str | None = None,
    iis_carried: bool = False, stale_out: list | None = None,
) -> dict:
    """
    by_account (аддитивно): у бумаги на обоих счетах — разбивка {main, iis_3} (xirr, pnl_rub, потоки, остаток),
    см. _split_by_account; верхний уровень записи остаётся объединением счетов. Без account_flows ИИС-3 или
    без per_security.cashflows поля нет.

    ISIN-алиасы (2026-10-13): у каждой записи поле `isin` (если известно), а для
    бумаг, у которых SECID != ISIN (ОФЗ), та же запись добавляется и под ключом
    ISIN с `alias_of: "<SECID>"` — потребитель находит per_instrument_xirr[holding.ticker]
    напрямую. Агрегаты по ключам считать с пропуском записей с alias_of.

    Ставка в per_security.json — доля под ключом xirr_frac (_read_xirr_frac).
    Здесь конвертируем → decimal (0.2337) для соответствия схеме v2.

    RPA-правило неразворота (Rule 3 ru-portfolio-advisor): recent_net_rub /
    recent_n_buys / recent_n_sells / recent_last_trade_date / recent_round_trip —
    сырая свёртка недавних buy/sell-сделок из per_security_xirr.py (окно и
    buy/sell-фильтр — там, см. _compute_recent_window). recent_direction
    классифицируется ЗДЕСЬ, против net_threshold_rub — только здесь известна
    «акционная книга» (balance_summary/goals_matrix), см. _derive_recent_net_threshold.
    Старый per_security.json (без recent_*-полей) → все recent_* поля
    отсутствуют в записи (аддитивная деградация, как и остальные optional-поля
    этой функции).
    """
    result: dict[str, dict] = {}
    isin_of = _secid_to_isin(holdings, returns)
    for ticker, data in (per_security or {}).items():
        if not isinstance(data, dict) or "error" in data:
            continue
        xirr_f = _read_xirr_frac(data)
        recent_net = _f(data.get("recent_net_rub"))
        recent_n_buys = data.get("recent_n_buys")
        recent_n_sells = data.get("recent_n_sells")
        recent_direction = None
        if (
            recent_net is not None
            and net_threshold_rub is not None
            and isinstance(recent_n_buys, int)
            and isinstance(recent_n_sells, int)
            and (recent_n_buys > 0 or recent_n_sells > 0)
        ):
            if recent_net >= net_threshold_rub:
                recent_direction = "buy"
            elif recent_net <= -net_threshold_rub:
                recent_direction = "trim"
            # |recent_net| < net_threshold_rub → recent_direction остаётся None (шум)
        entry: dict[str, Any] = {
            "xirr": round(xirr_f, 6) if xirr_f is not None else None,
            "isin": isin_of.get(str(ticker)),
            "qty_now": data.get("qty_now"),
            "pnl_rub": data.get("pnl_rub"),
            "buy_total_rub": data.get("buy_total_rub"),
            "dividends_rub": data.get("dividends_rub"),
            # Разбивка результата (аддитивно): продажи, купоны, амортизации,
            # корректировки, число продаж. Старый per_security.json → отсутствуют.
            "sell_total_rub": data.get("sell_total_rub"),
            "coupons_rub": data.get("coupons_rub"),
            "amortization_rub": data.get("amortization_rub"),
            "corr_buy_rub": data.get("corr_buy_rub"),
            "corr_sell_rub": data.get("corr_sell_rub"),
            "n_sells": data.get("n_sells"),
            "market_value_rub": data.get("market_value_rub"),
            "balance_value_rub": data.get("balance_value_rub"),
            "price_source": _price_source(data.get("price_source")),
            "first_trade_date": data.get("first_trade_date"),
            "last_trade_date": data.get("last_trade_date"),
            "recent_net_rub": recent_net,
            "recent_n_buys": recent_n_buys,
            "recent_n_sells": recent_n_sells,
            "recent_round_trip": data.get("recent_round_trip"),
            "recent_last_trade_date": data.get("recent_last_trade_date"),
            "recent_direction": recent_direction,
        }
        by_acc = None
        iis_t = (iis_flows or {}).get(str(ticker)) or {}
        if iis_flows and iis_t:
            if iis_carried and holdings is not None and abs(
                    _iis_qty_in_holdings(holdings, str(ticker), isin_of.get(str(ticker))) - float(iis_t.get("qty_now") or 0.0)) > 1e-6:
                # остаток ИИС-3 по балансу разошёлся с перенесёнными сделками — новые сделки ИИС-3 не приписать
                if stale_out is not None:
                    stale_out.append(str(ticker))
            else:
                by_acc = _split_by_account(data, iis_t, as_of)
        if by_acc:
            entry["by_account"] = by_acc
        result[ticker] = {k: v for k, v in entry.items() if v is not None}
    bond_isins = {h.get("isin") for h in holdings or []
                  if isinstance(h, dict) and h.get("asset_type") == "bond"}
    for secid, rec in list(result.items()):
        isin = rec.get("isin")
        if isin and isin != secid and isin in bond_isins and isin not in result:
            result[isin] = {**rec, "alias_of": secid}
    return result


def _live_flows_by_ticker(per_security: dict | None, per_instrument: dict | None,
                          iis_flows: dict | None = None, as_of: str | None = None) -> tuple[dict, dict]:
    """Потоки XIRR по бумагам (по дням, без конечной стоимости) — ровно те, по которым per_security_xirr
    посчитал xirr записи: его `cashflows` без последнего элемента — конечной стоимости (as_of, +market_value;
    есть, если market_value > 0). Ключи — как в per_instrument_xirr (ISIN-алиасы без потоков: их находят по alias_of).
    Вьюер добавляет живую конечную стоимость и решает то же уравнение (returns.live_basis.flows_by_ticker).

    Второй результат — потоки счетов у бумаг с by_account ({tk: {main: [...], iis_3: [...]}}): те же счётчики
    bond_locked.account_counters, по которым посчитаны xirr счетов в _split_by_account."""
    import datetime as dt
    out: dict[str, list] = {}
    acc: dict[str, dict] = {}

    def by_day(pairs) -> list:
        agg: dict[str, float] = {}
        for d, a in pairs:
            agg[str(d)[:10]] = agg.get(str(d)[:10], 0.0) + float(a)
        return [[d, round(v, 2)] for d, v in sorted(agg.items()) if abs(v) > 0.005]

    for ticker in (per_instrument or {}):
        rec = (per_security or {}).get(ticker)
        if not isinstance(rec, dict) or not rec.get("cashflows") or (per_instrument[ticker] or {}).get("alias_of"):
            continue
        cfs = rec["cashflows"]
        mv = _f(rec.get("market_value_rub")) or 0.0
        rows = by_day(cfs[:-1] if mv > 0 else cfs)
        if rows:
            out[ticker] = rows
        iis_t = (iis_flows or {}).get(str(ticker)) or {}
        if (per_instrument[ticker] or {}).get("by_account") and iis_t.get("cashflows") and as_of:
            ctr = bond_locked.account_counters(cfs, mv, iis_t["cashflows"], as_of)
            if ctr is not None:
                acc[ticker] = {"main": by_day((d.isoformat(), a) for d, a in bond_locked.counter_flows(ctr[0])),
                               "iis_3": by_day((d.isoformat(), a) for d, a in bond_locked.counter_flows(ctr[1]))}
    return out, acc


def _build_closed_instrument_xirr(
    per_security_closed: dict | None, per_instrument: dict | None, holdings: list | None,
    iis_flows: dict | None = None, as_of: str | None = None, iis_carried: bool = False,
) -> dict:
    """Результат по проданным и погашенным бумагам (акции, облигации, фонды обоих счетов) — отдельный блок
    `per_instrument_xirr_closed`, не `per_instrument_xirr`: тот читают как «то, что держу» (доли, сортировка по XIRR,
    recent_* для неразворота), закрытые бумаги исказили бы эти свёртки.

    Запись — того же вида, что в per_instrument_xirr, плюс: closed=true, close_date (последняя продажа/погашение;
    нет продаж — последняя сделка), holding_days (первая сделка → close_date), name, asset_type; qty_now=0 и
    market_value_rub=0 — терминала нет, результат целиком из потоков. Бумага, проданная и купленная снова,
    держится и живёт одной записью в per_instrument_xirr — здесь её нет. xirr — доля (0.23 = 23 %).
    """
    import datetime as dt
    held = set(per_instrument or {})
    for h in holdings or []:
        if isinstance(h, dict):
            held.update(x for x in (h.get("ticker"), h.get("isin")) if x)
    out: dict[str, dict] = {}
    for ticker, data in (per_security_closed or {}).items():
        if not isinstance(data, dict) or "error" in data or ticker in held:
            continue
        if (_f(data.get("qty_now")) or 0.0) > 1e-9 or data.get("inst_type") == "future":
            continue                                    # деривативы (вариационная маржа) — не бумаги портфеля
        first = data.get("first_trade_date")
        close = data.get("last_sell_date") or data.get("last_trade_date")
        try:
            days = (dt.date.fromisoformat(close[:10]) - dt.date.fromisoformat(first[:10])).days
        except (TypeError, ValueError):
            days = None
        xirr_f = _read_xirr_frac(data)
        entry: dict[str, Any] = {
            "closed": True, "close_date": close, "name": data.get("name"), "asset_type": data.get("inst_type"),
            "qty_now": 0.0, "market_value_rub": 0.0, "price_source": "closed",
            "xirr": round(xirr_f, 6) if xirr_f is not None else None,
            "pnl_rub": data.get("pnl_rub"),
            "buy_total_rub": data.get("buy_total_rub"), "sell_total_rub": data.get("sell_total_rub"),
            "dividends_rub": data.get("dividends_rub"), "coupons_rub": data.get("coupons_rub"),
            "amortization_rub": data.get("amortization_rub"),
            "corr_buy_rub": data.get("corr_buy_rub"), "corr_sell_rub": data.get("corr_sell_rub"),
            "n_sells": data.get("n_sells"),
            "first_trade_date": first, "last_trade_date": data.get("last_trade_date"), "holding_days": days,
        }
        iis_t = (iis_flows or {}).get(str(ticker)) or {}
        if iis_t and not iis_carried:
            try:
                by_acc = _split_by_account(data, iis_t, as_of)
            except Exception:                                                       # noqa: BLE001
                by_acc = None
            if by_acc:
                entry["by_account"] = by_acc
        out[ticker] = {k: v for k, v in entry.items() if v is not None}
    return out


def _recent_window_days_from_per_security(per_security: dict | None) -> int | None:
    """
    Читает фактическую ширину окна из per_security_xirr.py — она уже
    посчитана и записана в каждый тикер (recent_window_days), одно значение
    на весь прогон. Берём из первой валидной записи, а не пере-декларируем
    отдельным CLI-параметром здесь: так «дни» в snapshot['recent_trades_window']
    гарантированно совпадают с тем, что реально использовано при свёртке
    (не могут разъехаться при рассинхроне CLI-вызовов пайплайна).
    None — если per_security.json ещё не несёт этих полей (старый прогон).
    """
    for data in (per_security or {}).values():
        if isinstance(data, dict) and "error" not in data:
            days = data.get("recent_window_days")
            if isinstance(days, int):
                return days
    return None


def _derive_recent_net_threshold(
    portfolio: dict | None,
    threshold_pct: float,
    explicit_rub: float | None,
) -> tuple[float | None, str]:
    """
    Порог RPA-правила неразворота (Rule 3 ru-portfolio-advisor, гистерезис):
    нетто buy/sell по бумаге за окно ниже порога — шум, recent_direction=null.

    Приоритет базы:
      1. explicit_rub (--recent-net-threshold-rub) — явный override в ₽.
      2. threshold_pct% от «акционной книги» — фактической RUB-стоимости
         акций (balance_summary.goals_matrix[Валюта=RUB,Бумага=Акция]['Сейчас']).
         База владельца: 1пп книги ≈ 47 441 ₽ на снапшоте 2026-08-21
         (книга 14 232 340,5 ₽) — сверено численно.
      3. Fallback, если goals_matrix недоступен (снапшот без «Общего баланса»
         или без плановой матрицы): threshold_pct% от NAV excl. ИИС
         (metrics.total_current_rub_excl_iis) — грубее (весь портфель, не
         только акции), но явно зафиксировано в threshold_basis.
      4. Если недоступно и это — порог не считается (None), recent_direction
         остаётся null для ВСЕХ инструментов; текст в threshold_basis это
         явно называет, ничего не выдумывается молча.
    """
    if explicit_rub is not None:
        return (
            round(float(explicit_rub), 2),
            f"явный override --recent-net-threshold-rub={explicit_rub:g} ₽",
        )

    matrix = (portfolio or {}).get("goals", {}).get("matrix")
    if isinstance(matrix, list):
        for row in matrix:
            if (
                isinstance(row, dict)
                and row.get("Валюта") == "RUB"
                and row.get("Бумага") == "Акция"
            ):
                book = row.get("Сейчас")
                if isinstance(book, (int, float)):
                    thr = round(book * threshold_pct / 100.0, 2)
                    return thr, (
                        f"{threshold_pct:g}пп акционной книги "
                        f"(goals_matrix RUB/Акция «Сейчас»={book:,.2f} ₽)"
                    )
                break

    metrics = (portfolio or {}).get("metrics", {})
    nav = metrics.get("total_current_rub_excl_iis")
    if isinstance(nav, (int, float)):
        thr = round(nav * threshold_pct / 100.0, 2)
        return thr, (
            f"{threshold_pct:g}пп NAV excl. ИИС — fallback: goals_matrix "
            f"RUB/Акция недоступен (NAV={nav:,.2f} ₽)"
        )

    return None, (
        "порог не рассчитан — нет ни goals_matrix (RUB/Акция), ни NAV excl. "
        "ИИС (снапшот без «Общего баланса»); recent_direction=null для всех "
        "инструментов"
    )


# ── cash ──────────────────────────────────────────────────────────────────────

def _build_cash(
    returns: dict | None,
    portfolio: dict | None,
    holdings: list[dict] | None,
) -> tuple[dict, list[dict]]:
    """
    Настоящий свободный кэш (семантика уточнена владельцем 2026-07-08):
    «Имеется» = весь портфель ВКЛЮЧАЯ ИИС-3, БЕЗ заблокированных активов →
    total_rub = «Имеется» − стоимость ВСЕХ незаблокированных holdings.

    Балансовый остаток из metrics.by_account здесь сознательно НЕ используется:
    он «грязный» — содержит позиции, которых нет во вкладках баланса
    (TPAY/TMON/FINAMAR приходят только из трейдов) и потому кэшем не являются.
    """
    flags: list[dict] = []
    snap = (returns or {}).get("snapshot_current", {})
    by_currency: dict[str, float] = {
        k: round(float(v), 4)
        for k, v in snap.get("cash_by_currency", {}).items()
        if isinstance(v, (int, float))
    }

    metrics = (portfolio or {}).get("metrics", {})
    incl_iis = _f(metrics.get("total_current_rub_incl_iis"))
    iis_balance = _f(metrics.get("iis_balance_rub")) or 0.0

    total_rub = main_cash = iis_cash = None
    if incl_iis is not None and holdings:
        securities_rub = sum(
            float(h["value_rub"]) for h in holdings
            if h.get("status") != "blocked"
            and isinstance(h.get("value_rub"), (int, float))
        )
        total_rub = round(incl_iis - securities_rub, 2)
        iis_securities_rub = sum(
            float(h["value_rub"]) for h in holdings
            if h.get("account") == "iis_3"
            and isinstance(h.get("value_rub"), (int, float))
        )
        iis_cash = round(iis_balance - iis_securities_rub, 2)
        main_cash = round(total_rub - iis_cash, 2)
        if total_rub < 0 or iis_cash < 0:
            flags.append(_flag(
                "assemble_cash", "warning", "cash_negative",
                f"Расчётный свободный кэш отрицательный "
                f"(total {total_rub:+,.0f} ₽, iis {iis_cash:+,.0f} ₽): строка "
                f"«Имеется» в балансе, вероятно, старее котировок MOEX или не "
                f"покрывает часть позиций. Обнови «Имеется» и перегони снапшот.",
            ))

    return {
        "total_rub": total_rub,
        "by_currency": by_currency,
        "by_account": {
            "main":  main_cash,
            "iis_3": iis_cash,
        } if total_rub is not None else None,
        "note": (
            "total_rub = «Имеется» (весь портфель вкл. ИИС, без blocked) − "
            "стоимость всех незаблокированных holdings; "
            "by_currency derived from trades"
        ),
    }, flags


# ── cash reconciliation (baseline-дрейф) ─────────────────────────────────────
# Реконструированный из трейдов кэш исторически расходится с фактическим
# (~340 тыс. ₽ на 2026-07: пополнения прошлых лет не попали в экспорт
# IntelInvest). До фикса семантики кэша 2026-07-08 baseline был ~2,2 млн —
# бо́льшая его часть оказалась артефактом двойного счёта ИИС и денежных
# фондов в «кэше»; после апгрейда старый baseline даст разовый
# cash_drift_changed — перегнать с --rebaseline-cash.
# Прошлое не чиним: расхождение фиксируется как baseline (едет из снапшота в
# снапшот через prev_snapshot) — warning только когда НОВОЕ расхождение
# отличается от зафиксированного больше порога. Осознанное изменение
# принимается перегоном с --rebaseline-cash.

CASH_DRIFT_THRESHOLD_RUB = 10_000.0

# Без «Общего баланса» кэш — оценка (реконструкция по сделкам + прошлое расхождение). Старше
# стольких дней с последнего факта (баланс или кэш, внесённый владельцем из IntelInvest) —
# флаг cash_fact_stale: владелец вносит свободные деньги основного портфеля, сборка берёт факт.
CASH_FACT_MAX_AGE_DAYS = 14


def _build_cash_reconciliation(
    returns: dict | None,
    actual_cash_rub: float | None,
    prev_snapshot: dict | None,
    today: str,
    *,
    rebaseline: bool = False,
) -> tuple[dict | None, dict | None]:
    """Возвращает (блок cash_reconciliation, флаг|None).

    actual_cash_rub — настоящий кэш из cash.total_rub (см. _build_cash),
    а не «грязный» балансовый остаток by_account.
    """
    recon = _f(((returns or {}).get("snapshot_current") or {}).get("cash_balance_rub"))
    actual = round(actual_cash_rub, 2) if actual_cash_rub is not None else None
    if recon is None or actual is None:
        return None, None

    drift = round(actual - recon, 2)
    prev = (prev_snapshot or {}).get("cash_reconciliation") or {}
    baseline = _f(prev.get("baseline_drift_rub"))
    baseline_date = prev.get("baseline_date")

    flag = None
    if baseline is None or rebaseline:
        baseline, baseline_date = drift, today
        flag = _flag(
            "cash_reconciliation", "info", "cash_baseline_set",
            f"Расхождение фактического кэша с реконструкцией из трейдов "
            f"зафиксировано как baseline: {drift:+,.0f} ₽. Историческая дыра "
            f"принята; сигналим только на новые изменения (> "
            f"{CASH_DRIFT_THRESHOLD_RUB:,.0f} ₽).",
        )
        delta = 0.0
    else:
        delta = round(drift - baseline, 2)
        if abs(delta) > CASH_DRIFT_THRESHOLD_RUB:
            flag = _flag(
                "cash_reconciliation", "warning", "cash_drift_changed",
                f"Кэш-расхождение изменилось: сейчас {drift:+,.0f} ₽ против "
                f"baseline {baseline:+,.0f} ₽ от {baseline_date} "
                f"(Δ {delta:+,.0f} ₽). Проверь полноту выгрузки trades "
                f"(пополнения/выводы с прошлого снапшота). Если изменение "
                f"осознанное — перегони с --rebaseline-cash.",
            )

    block = {
        "actual_cash_rub":        actual,
        "reconstructed_cash_rub": recon,
        "current_drift_rub":      drift,
        "baseline_drift_rub":     baseline,
        "baseline_date":          baseline_date,
        "delta_vs_baseline_rub":  delta,
        "threshold_rub":          CASH_DRIFT_THRESHOLD_RUB,
    }
    return block, flag


# ── returns ───────────────────────────────────────────────────────────────────

def _build_returns(returns: dict) -> dict:
    def _map_returns(src: dict) -> dict:
        return {
            "xirr":                  _f(src.get("xirr")),
            "roi":                   _f(src.get("roi")),
            "twr_dietz_annualized":  _f(src.get("twr_dietz_annualized")),
            "pnl_rub":               _f(src.get("pnl_rub")),
        }

    params   = (returns or {}).get("parameters", {})
    total    = (returns or {}).get("returns_total", {})
    restr    = (returns or {}).get("returns_restricted", {})
    by_type  = (returns or {}).get("returns_by_type_restricted", {})

    return {
        "parameters": {
            "as_of":        params.get("as_of") or total.get("period_end"),
            "start_date":   params.get("start_date") or total.get("period_start"),
            "trades_count": params.get("trades_count"),
            "use_moex":     params.get("use_moex", True),
            "cbr_offline":  params.get("cbr_offline", False),
            # "dirty" = облигации с НКД; отсутствие в returns.json → "clean"
            # (до 2026-10-12): XIRR облигаций таких снапшотов занижен.
            "bond_value_basis": params.get("bond_value_basis", "clean"),
        },
        "total": {
            **_map_returns(total),
            "comment": total.get("description"),
        },
        "restricted": {
            **_map_returns(restr),
            "comment":                restr.get("description"),
            "received_coupons_rub":   restr.get("received_coupons_rub"),
            "received_dividends_rub": restr.get("received_dividends_rub"),
        },
        "by_type": {
            asset_type: _map_returns(data)
            for asset_type, data in by_type.items()
            if isinstance(data, dict)
        },
        # Бенчмарк-гейт (PME): факт vs бенчмарк на тех же потоках — as-is из
        # portfolio_returns (stock vs MCFTR, bond vs вклад КС−1); null если
        # расчёт пропущен/сеть недоступна.
        "benchmarks": (returns or {}).get("benchmarks_restricted"),
        # Живая доходность во вьюере (2026-10-23): потоки XIRR и позиции конечной стоимости as-is
        # из portfolio_returns (нет в старом returns.json — null, вьюер показывает XIRR снапшота)
        "live_basis": (returns or {}).get("live_basis"),
    }


# ── corrections_log ───────────────────────────────────────────────────────────

def _build_corrections_log(returns: dict) -> list[dict]:
    result = []
    for c in (returns or {}).get("corrections_applied", []):
        if not isinstance(c, dict):
            continue
        entry: dict[str, Any] = {
            "type":        c.get("type"),
            "ticker":      c.get("ticker"),
            "date":        c.get("date"),
            "description": c.get("reason") or c.get("description"),
        }
        if "ratio" in c:
            entry["ratio"] = c["ratio"]
        result.append({k: v for k, v in entry.items() if v is not None})
    return result


# ── main assembly ─────────────────────────────────────────────────────────────

# Сверка файла ИИС-3 (iis_returns.py) с балансом: допуск по кэшу — максимум из
# 1 000 ₽ и 0.5% стоимости счёта (копейки округлений + купон в пути ±1 день).
IIS_CASH_TOLERANCE_RUB = 1000.0
IIS_CASH_TOLERANCE_PCT = 0.005
IIS_QTY_TOLERANCE = 0.5


def _build_iis_account_returns(
    iis: dict | None,
    holdings: list[dict] | None,
    portfolio: dict | None,
) -> tuple[dict | None, list[dict]]:
    """returns.by_account.iis_3 из выхода iis_returns.py + сверка с балансом.

    Контракт владельца (2026-10-12): покупка/продажа/взнос на БКС-ИИС-3 сразу
    влекут свежую выгрузку; нет файла — операций не было. Купоны после даты
    файла iis_returns достраивает по графику MOEX. Сверка ловит нарушение
    контракта: позиции файла против holdings `account == "iis_3"`, кэш файла
    против `metrics.by_account.iis_3.cash_rub` баланса. Расхождение → блок БЕЗ
    чисел (status: mismatch) + warn: считать доходность на базе, которая
    не совпадает с балансом, хуже, чем не считать.
    """
    if not iis:
        return None, []
    flags: list[dict] = []
    for f in iis.get("flags") or []:
        sev = "warn" if f.get("code") in (
            "iis_coupon_missing_in_file", "iis_redemption_not_in_file",
        ) else "info"
        flags.append(_flag("iis_returns", sev, f.get("code") or "iis_returns",
                           f.get("message") or ""))
    synth = iis.get("synthetic_coupons") or []
    if synth:
        total = sum(float(x.get("amount_rub") or 0) for x in synth)
        flags.append(_flag(
            "iis_returns", "info", "iis_synthetic_coupons",
            f"ИИС-3: {len(synth)} купон(ов) после даты файла "
            f"{iis.get('file_last_operation')} на {total:,.0f} ₽ — по графику MOEX, "
            f"не из выписки; заменятся реальными со следующим файлом.",
        ))

    head = {
        "broker": iis.get("broker"),
        "source_file": iis.get("source_file"),
        "file_last_operation": iis.get("file_last_operation"),
        "as_of": iis.get("as_of"),
    }
    if holdings is None:
        status, diffs = "unverified", []
        flags.append(_flag(
            "iis_returns", "info", "iis_returns_unverified",
            "ИИС-3: баланс не приложен — позиции файла не сверены.",
        ))
    else:
        hold = {}
        for h in holdings:
            if h.get("account") == "iis_3" and h.get("status") != "blocked":
                hold[str(h.get("ticker"))] = hold.get(str(h.get("ticker")), 0.0) + float(
                    h.get("qty") or 0.0)
        file_pos = {}
        for p in iis.get("positions") or []:
            key = p.get("isin") if p.get("isin") in hold else p.get("secid")
            file_pos[str(key)] = float(p.get("qty") or 0.0)
        diffs = []
        for k in sorted(set(hold) | set(file_pos)):
            a, b = file_pos.get(k, 0.0), hold.get(k, 0.0)
            if abs(a - b) > IIS_QTY_TOLERANCE:
                diffs.append({"ticker": k, "file_qty": a, "balance_qty": b})
        bal_cash = ((((portfolio or {}).get("metrics") or {}).get("by_account") or {})
                    .get("iis_3") or {}).get("cash_rub")
        file_cash = iis.get("cash_rub")
        if isinstance(bal_cash, (int, float)) and isinstance(file_cash, (int, float)):
            acc_value = sum(float(h.get("value_rub") or 0) for h in holdings
                            if h.get("account") == "iis_3")
            tol = max(IIS_CASH_TOLERANCE_RUB, IIS_CASH_TOLERANCE_PCT * acc_value)
            if abs(file_cash - bal_cash) > tol:
                diffs.append({"ticker": "cash_rub", "file_qty": round(file_cash, 2),
                              "balance_qty": round(bal_cash, 2)})
        status = "mismatch" if diffs else "ok"
        if diffs:
            listing = "; ".join(f"{d['ticker']}: файл {d['file_qty']:g} / баланс "
                                f"{d['balance_qty']:g}" for d in diffs[:6])
            flags.append(_flag(
                "iis_returns", "warn", "iis_returns_mismatch",
                f"ИИС-3: файл {iis.get('source_file')} (последняя операция "
                f"{iis.get('file_last_operation')}) не сходится с балансом — {listing}. "
                f"Похоже, была покупка/продажа/взнос без новой выгрузки (или баланс "
                f"устарел). Доходность ИИС-3 не посчитана.",
            ))
    block = {**head, "status": status, "reconciliation": diffs}
    if status == "mismatch":
        return block, flags
    infl = iis.get("inflation_assumption") or {}
    block.update({
        "fact": iis.get("fact"),
        "forward": iis.get("forward"),
        "locked": iis.get("locked"),
        "per_bond": iis.get("per_bond"),
        "other_positions": iis.get("other_positions"),
        "live_basis": iis.get("live_basis"),
        "inflation_assumption": {k: infl.get(k) for k in
                                 ("source", "path", "flat_pct", "note")},
        "synthetic_coupons": synth,
    })
    return block, flags


def _iis_qty_by_ticker(holdings: list[dict] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for h in holdings or []:
        if h.get("account") == "iis_3" and h.get("status") != "blocked":
            k = str(h.get("isin") or h.get("ticker"))
            out[k] = out.get(k, 0.0) + float(h.get("qty") or 0.0)
    return out


def _carry_iis_block(
    sources: list[dict] | None,
    holdings: list[dict] | None,
) -> tuple[dict | None, list[dict]]:
    """Нет новой выгрузки ИИС-3 → перенести returns.by_account.iis_3 из последнего
    снапшота, где блок есть и с числами (status != mismatch). sources — по
    убыванию свежести, ВКЛЮЧАЯ файл того же дня, который сейчас будет
    перезаписан (инцидент 13.10: прогон 15:10 с ИИС, прогон 16:56 без —
    блок пропал). Блок помечается carried_from / carried_reason. Состав ИИС-3
    сверяется по qty (ISIN) с holdings снапшота-источника: разошёлся → warn,
    блок всё равно переносится."""
    for src in sources or []:
        blk = (((src.get("returns") or {}).get("by_account") or {}).get("iis_3"))
        if not blk or blk.get("status") == "mismatch" or blk.get("fact") is None:
            continue
        carried = dict(blk)
        origin = blk.get("carried_from") or src.get("as_of_date")
        carried["carried_from"] = origin
        carried["carried_reason"] = "нет новой выгрузки ИИС-3"
        flags = [_flag(
            "iis_returns", "info", "iis_returns_carried",
            f"ИИС-3: новой выгрузки нет — блок returns.by_account.iis_3 перенесён из "
            f"снапшота {origin} (выгрузка {blk.get('source_file')}, последняя операция "
            f"{blk.get('file_last_operation')}).",
        )]
        if holdings is not None and src.get("holdings") is not None:
            cur, old = _iis_qty_by_ticker(holdings), _iis_qty_by_ticker(src.get("holdings"))
            diffs = [k for k in sorted(set(cur) | set(old))
                     if abs(cur.get(k, 0.0) - old.get(k, 0.0)) > IIS_QTY_TOLERANCE]
            if diffs:
                flags.append(_flag(
                    "iis_returns", "warn", "iis_composition_changed",
                    f"ИИС-3: состав изменился с расчёта ({origin}) — {', '.join(diffs[:8])}. "
                    f"Нужна свежая выгрузка trades_portfolio_838526*.xlsx; перенесённые "
                    f"числа могут не отражать текущий состав.",
                ))
        return carried, flags
    return None, []


# ── сверка «Общий баланс vs расчёт по сделкам» ────────────────────────────────

# Порог расхождения (доля): |Δ| > 1 % → флаг по бумаге.
BALANCE_VS_TRADES_THRESHOLD = 0.01
# Старт полугодового периода параллельного ведения двух источников
# (docs/investment/TODO.md, «Переход с „Общего баланса“ на расчёт по транзакциям»).
BALANCE_VS_TRADES_STARTED = "2026-10-13"


def _known_split_tickers() -> frozenset[str]:
    """Тикеры из KNOWN_SPLITS (portfolio_returns.py) — законная причина расхождения
    средней цены: баланс и сделки по-разному учитывают сплит. Нет модуля — пусто."""
    try:
        from portfolio_returns import KNOWN_SPLITS  # noqa: WPS433
        return frozenset(KNOWN_SPLITS)
    except Exception:  # pragma: no cover — сверка не должна ронять сборку
        return frozenset()


def _rel_diff(a: float | None, b: float | None) -> float | None:
    """(a − b) / b, None если нечего сравнивать."""
    if a is None or b is None or b == 0:
        return None
    return (a - b) / b


def _build_balance_vs_trades(
    holdings: list[dict] | None,
    returns: dict | None,
    known_split_tickers: frozenset[str] | None = None,
) -> tuple[dict | None, list[dict]]:
    """
    Сверка двух источников: «Общий баланс» (holdings: avg_cost_rub из колонки
    «Ср, Цена», value_rub = «Стоимость») против расчёта скриптами
    (средняя цена позиции из reconstruct_positions по сделкам; qty × MOEX).

    По каждой активной акции/фонду с котировкой MOEX (current_price_source ==
    "moex_iss"): avg_cost баланса vs сделок и value баланса vs qty×MOEX,
    относительные расхождения, mismatch при |Δ| > 1 %. Расхождение — НЕ ошибка
    загрузки: только флаг (severity info). Известные причины — только то, что код
    уже знает: тикер из KNOWN_SPLITS (known_split). Смену тикера / переезд между
    брокерами код не знает — такие бумаги идут в unexplained и разбираются руками.
    """
    if holdings is None:
        return None, []
    splits = _known_split_tickers() if known_split_tickers is None else known_split_tickers
    trade_pos: dict[str, list[dict]] = {}
    for p in ((returns or {}).get("snapshot_current", {}) or {}).get("positions", []) or []:
        if p.get("type") in ("stock", "fund") and not p.get("is_blocked"):
            trade_pos.setdefault(p.get("ticker"), []).append(p)

    rows: list[dict] = []
    for h in holdings:
        if h.get("asset_type") not in ("stock", "fund"):
            continue
        if h.get("is_blocked") or h.get("status") not in (None, "normal"):
            continue
        qty = _f(h.get("qty"))
        price = _f(h.get("current_price"))
        if not qty or qty <= 0 or price is None or h.get("current_price_source") != "moex_iss":
            continue
        ticker = h.get("ticker")

        # avg_cost: баланс (только настоящий, не fallback value/qty) vs сделки
        avg_bal = _f(h.get("avg_cost_rub")) if h.get("avg_cost_source") == "balance" else None
        cands = trade_pos.get(ticker, [])
        tp = min(cands, key=lambda c: abs((_f(c.get("qty")) or 0.0) - qty), default=None)
        avg_tr = _f(tp.get("avg_cost_rub")) if tp else None
        if avg_tr is not None and avg_tr <= 0:
            avg_tr = None
        avg_diff = _rel_diff(avg_bal, avg_tr)

        # value: баланс vs qty × MOEX
        val_bal = _f(h.get("value_rub"))
        val_moex = round(qty * price, 2)
        val_diff = _rel_diff(val_bal, val_moex)

        fields = [
            name for name, d in (("avg_cost", avg_diff), ("value", val_diff))
            if d is not None and abs(d) > BALANCE_VS_TRADES_THRESHOLD
        ]
        reasons = ["known_split"] if (fields and ticker in splits) else []
        rows.append({
            "ticker": ticker,
            "asset_type": h.get("asset_type"),
            "qty": qty,
            "avg_cost_balance": avg_bal,
            "avg_cost_trades": round(avg_tr, 4) if avg_tr is not None else None,
            "avg_cost_diff_pct": round(avg_diff * 100, 2) if avg_diff is not None else None,
            "value_balance_rub": val_bal,
            "value_moex_rub": val_moex,
            "value_diff_pct": round(val_diff * 100, 2) if val_diff is not None else None,
            "mismatch": bool(fields),
            "mismatch_fields": fields,
            "known_reasons": reasons,
        })

    mism = [r for r in rows if r["mismatch"]]
    unexpl = [r["ticker"] for r in mism if not r["known_reasons"]]
    block = {
        "started": BALANCE_VS_TRADES_STARTED,
        "threshold_pct": BALANCE_VS_TRADES_THRESHOLD * 100,
        "positions": rows,
        "summary": {
            "n_checked": len(rows),
            "n_mismatch": len(mism),
            "n_mismatch_unexplained": len(unexpl),
            "mismatch_tickers": [r["ticker"] for r in mism],
            "unexplained_tickers": unexpl,
        },
    }
    flags: list[dict] = []
    if mism:
        flags.append(_flag(
            "reconciliation", "info", "balance_vs_trades_mismatch",
            f"Сверка «Общий баланс vs сделки+MOEX»: {len(mism)} из {len(rows)} бумаг "
            f"расходятся более чем на {BALANCE_VS_TRADES_THRESHOLD * 100:g} % "
            f"(без известной причины: {len(unexpl)}). Тикеры: "
            f"{', '.join(r['ticker'] for r in mism[:10])}"
            + ("..." if len(mism) > 10 else "")
            + ". Это не ошибка загрузки — детали в reconciliation.balance_vs_trades.",
        ))
    return block, flags


def _build_bond_qty_vs_trades(
    holdings: list[dict] | None,
    per_instrument: dict | None,
) -> tuple[dict | None, list[dict]]:
    """
    Количество облигаций на основном счёте: «Общий баланс» (holdings.qty) против
    реконструкции по сделкам (per_instrument_xirr[*].qty_now). Сверка акций/фондов
    (_build_balance_vs_trades) облигации не покрывала, и расхождение НорНик1P17
    (RU000A10FC62: 24 шт в балансе при 34 по сделкам и стоимости ≈34 шт) три недели
    шло в обзоры без флага (PDL-RECON, 2026-10-20). ИИС-3 не сверяется: его сделки —
    в отдельной выгрузке, qty_now считается по основной. Порог 0 — количество целое.
    """
    if holdings is None or not per_instrument:
        return None, []
    trade_qty: dict[str, float] = {}
    for key, entry in per_instrument.items():
        if not isinstance(entry, dict):
            continue
        isin = entry.get("isin") or (key if str(key).startswith("RU") and len(str(key)) == 12 else None)
        q = _f(entry.get("qty_now"))
        if isin and q is not None:
            # одна бумага бывает под двумя ключами (SU-тикер и ISIN) — дубль, не сумма
            trade_qty[isin] = max(trade_qty.get(isin, 0.0), q)
    bal_qty: dict[str, float] = {}
    iis_qty: dict[str, float] = {}
    names: dict[str, str] = {}
    for h in holdings:
        if h.get("asset_type") != "bond" or h.get("status") not in (None, "normal"):
            continue
        isin = h.get("isin") or h.get("ticker")
        q = _f(h.get("qty")) or 0.0
        if h.get("account") in (None, "main"):
            bal_qty[isin] = bal_qty.get(isin, 0.0) + q
            names[isin] = h.get("name") or isin
        else:
            iis_qty[isin] = iis_qty.get(isin, 0.0) + q
    rows = []
    for isin, qb in sorted(bal_qty.items()):
        qt = trade_qty.get(isin)
        if qt is None:
            continue  # бумаги нет в сделках основного счёта (перевод, другой брокер) — не сверяем
        # бумага на двух счетах (ОФЗ 26238: 80 main + 130 ИИС-3): qty_now бывает по сумме — это не расхождение
        ok = {qb, qb + iis_qty.get(isin, 0.0)}
        rows.append({"isin": isin, "name": names[isin], "qty_balance": qb, "qty_trades": qt,
                     "qty_iis": iis_qty.get(isin, 0.0),
                     "mismatch": all(abs(v - qt) >= 1 for v in ok)})
    mism = [r for r in rows if r["mismatch"]]
    block = {"positions": rows, "summary": {"n_checked": len(rows), "n_mismatch": len(mism),
                                            "mismatch_isins": [r["isin"] for r in mism]}}
    flags: list[dict] = []
    if mism:
        flags.append(_flag(
            "reconciliation", "warning", "bond_qty_vs_trades_mismatch",
            "Количество облигаций в «Общем балансе» расходится со сделками: "
            + ", ".join(f"{r['name']} ({r['isin']}): баланс {r['qty_balance']:g}, сделки {r['qty_trades']:g}"
                        for r in mism[:10])
            + ". Стоимость позиции считается по балансу — проверь количество в Numbers.",
        ))
    return block, flags


# ── без «Общего баланса»: позиции из сделок (2026-10-21, сборка снапшота с сайта) ─────────

def _iis_export_positions(iis: dict | None) -> list[dict] | None:
    """Позиции ИИС-3 по сделкам выгрузки счёта (iis_returns.py): [{secid, isin, qty, kind, value_rub, name}].
    None — выгрузки ИИС-3 нет (позиции остаются переносом из прошлого снапшота). Бумага без сделок-остатка
    в список не входит: погашенная и проданная облигация уходит в ноль вместе с остатком."""
    if not isinstance(iis, dict) or not isinstance(iis.get("positions"), list):
        return None
    info: dict[str, dict] = {}
    for b in iis.get("per_bond") or []:
        info[b["secid"]] = {"kind": "bond", "value_rub": b.get("value_rub"), "name": b.get("name")}
    for o in iis.get("other_positions") or []:
        info.setdefault(o["secid"], {"kind": o.get("kind"), "value_rub": o.get("value_rub"), "name": None})
    out = []
    for p in iis["positions"]:
        qty = _f(p.get("qty"))
        if not p.get("secid") or not qty or qty <= 1e-9:
            continue
        i = info.get(p["secid"], {})
        out.append({"secid": p["secid"], "isin": p.get("isin"), "qty": qty, "kind": i.get("kind"),
                    "value_rub": _f(i.get("value_rub")), "name": i.get("name")})
    return out


def _portfolio_from_trades(
    returns: dict, prev_snapshot: dict | None, as_of: str, quotes: dict | None = None,
    cash_fact: float | None = None, cash_fact_iis: float | None = None,
    plan: dict | None = None, per_security: dict | None = None,
    iis_returns: dict | None = None,
) -> tuple[dict, dict]:
    """«Баланс из сделок» в формате parse_portfolio.py — дальше обычные _build_stocks/bonds/funds
    с теми же обогащениями MOEX и проверками.

    Решение владельца 2026-10-21: файл сделок обязателен, «Общий баланс» — нет; из баланса
    берётся то, что из сделок не вывести. Без него:
      • позиции основного счёта, количество, стоимость — returns.snapshot_current (сделки, цены
        MOEX, у облигаций — НКД и валюта номинала);
      • название, корзина/подтип/рейтинг облигаций, номинал — из прошлого снапшота (по тикеру);
      • ИИС-3: есть выгрузка счёта (iis_returns) — позиции по её сделкам (количество точное, основной
        счёт = выгрузка основного − ИИС-3); у облигации на обоих счетах цена за бумагу — как у основного.
        Выгрузки нет — позиции прошлого снапшота (перенос), qty основного — по близости к прошлому;
      • внебиржевые (FINAMAR: цены MOEX нет, в сделках — цена покупки) — стоимость за бумагу из
        прошлого снапшота;
      • кэш: «Имеется» неоткуда → реконструкция по сделкам + последнее известное расхождение
        «факт − реконструкция» (prev.cash_reconciliation.current_drift_rub), кэш ИИС-3 — прошлый;
        владелец внёс cash_fact (свободные деньги основного портфеля из IntelInvest) — кэш основного
        счёта = cash_fact, оценка не нужна; cash_fact_iis — то же для ИИС-3 (кэш только рублёвый):
        подменяет перенос из прошлого снапшота.
    plan (plan.json) — база сайта: типизация облигаций по ISIN (plan.bonds, применяется в
    apply_plan_primary), стоимость внебиржевой позиции (FINAMAR) — plan.manual_positions; из прошлого
    снапшота остаётся только то, чего в плане нет (meta.carried перечисляет, что именно).
    Облигация в сделках — код MOEX (SU26243RMFS4), в балансе и снапшотах — ISIN (RU000A106E90):
    сопоставление с прошлым снапшотом — по тикеру или ISIN из котировки, в «баланс» идёт ISIN
    (как у parse_portfolio), котировке добавляется ключ-ISIN (прогон 2026-10-22: без этого 10
    облигаций «пропали из позиций», названия и корзины не перенеслись).
    Возвращает (portfolio, meta): meta — дата прошлого снапшота и что перенесено (для флага)."""
    snap = returns.get("snapshot_current") or {}
    prev = prev_snapshot or {}
    prev_h = prev.get("holdings") or []
    prev_main: dict[str, dict] = {}
    for h in prev_h:
        if h.get("account") in (None, "main"):
            for k in (h.get("ticker"), h.get("isin")):
                if k:
                    prev_main.setdefault(k, h)
    prev_iis = [h for h in prev_h if h.get("account") == "iis_3" and h.get("status") != "blocked"]
    iis_by_ticker: dict[str, dict] = {}
    for h in prev_iis:
        for k in (h.get("ticker"), h.get("isin")):
            if k:
                iis_by_ticker.setdefault(k, h)
    iis_exp = _iis_export_positions(iis_returns)
    if iis_exp is not None:
        # позиции ИИС-3 — по сделкам его выгрузки; из прошлого снапшота берутся только атрибуты (название, корзина)
        attr_src = dict(iis_by_ticker)
        prev_iis, iis_by_ticker = [], {}
        for e in iis_exp:
            a = next((x for k in (e["secid"], e["isin"]) if k
                      for x in (attr_src.get(k), prev_main.get(k)) if x), {})
            ih = {"ticker": a.get("ticker") or e["isin"] or e["secid"], "isin": e["isin"] or a.get("isin"),
                  "asset_type": e["kind"], "qty": e["qty"], "value_rub": e["value_rub"],
                  "name": a.get("name") or e["name"], "status": "normal",
                  **{k: a.get(k) for k in ("plan_bucket", "plan_subtype", "credit_rating_file", "nominal",
                                            "nominal_currency")}}
            prev_iis.append(ih)
            for k in (e["secid"], e["isin"], ih["ticker"]):
                if k:
                    iis_by_ticker.setdefault(k, ih)
    iis_mark = "iis_from_export" if iis_exp is not None else "iis_from_prev"
    q_all = quotes if quotes is not None else {}
    # prev_date — снапшот, откуда взяты позиции/расхождение; balance_date — день последнего баланса
    # (у снапшота без баланса prev он уже перенесён: prev.balance_carried_from)
    is_trades_prev = prev.get("snapshot_type") == "trades_holdings"
    balance_date = (prev.get("balance_carried_from") if is_trades_prev else prev.get("as_of_date"))
    prev_fact_date = (prev.get("cash") or {}).get("fact_date") or (None if is_trades_prev else prev.get("as_of_date"))
    meta: dict[str, Any] = {"prev_date": prev.get("as_of_date"), "balance_date": balance_date,
                            "prev_fact_date": prev_fact_date, "otc_from_prev": [], "iis_from_prev": [],
                            "iis_from_export": [], "iis_unrepresented": [], "iis_exceeds_total": [],
                            "bond_qty_split": [], "otc_from_plan": [], "names_from_prev": [],
                            "nominal_from_prev": [], "bond_types_from_prev": [], "manual_stale": [],
                            "manual_stale_date": []}
    plan_manual: dict[str, float] = {}
    plan_manual_asof: dict[str, str] = {}
    for m in (plan or {}).get("manual_positions") or []:
        v = _f(m.get("value_rub"))
        if m.get("name") and v is not None and v > 0:
            plan_manual[str(m["name"]).strip()] = v
            if isinstance(m.get("value_as_of"), str) and len(m["value_as_of"]) >= 10:
                plan_manual_asof[str(m["name"]).strip()] = m["value_as_of"][:10]
    plan_bonds = (plan or {}).get("bonds") or {}

    stocks, bonds, other = [], [], []
    main_value: dict[str, tuple[float, float]] = {}       # ticker → (value, qty) для переоценки ИИС-3
    for pos in snap.get("positions") or []:
        if pos.get("is_blocked"):
            continue
        qty, val = _f(pos.get("qty")), _f(pos.get("value_rub"))
        if not qty or qty <= 0:
            continue
        t, kind = pos.get("ticker"), pos.get("type")
        isin = (q_all.get(t) or {}).get("isin")
        ph = prev_main.get(t) or (prev_main.get(isin) if isin else None) or {}
        if kind == "bond":
            canon = ph.get("ticker") or (iis_by_ticker.get(t) or iis_by_ticker.get(isin) or {}).get("ticker") or isin or t
            if canon != t and t in q_all:
                q_all.setdefault(canon, q_all[t])        # котировка доступна и по ISIN
            t = canon
        q_short = (q_all.get(t) or {}).get("short_name")
        name = ph.get("name") or q_short or pos.get("name") or t
        if ph.get("name") and not q_short:
            meta["names_from_prev"].append(t)                  # названия нет в котировках — только прошлый снапшот
        not_moex = "moex" not in str(pos.get("price_source") or "")
        if kind != "bond" and not_moex and plan_manual.get(t) is not None:
            val = plan_manual[t]                                # внебиржевой (FINAMAR): стоимость из базы сайта
            meta["otc_from_plan"].append(t)
            pq, pv = _f(ph.get("qty")), _f(ph.get("value_rub"))
            if pq and pv and abs(qty - pq) > 1e-6 * max(abs(pq), 1.0) and abs(val - pv) < 0.5:
                meta["manual_stale"].append((t, pq, qty, val))     # паёв стало иначе, а оценка в плане прежняя
            else:
                # вторая ветка: оценка датирована раньше последней сделки по бумаге (одна бумага — один флаг)
                v_asof = plan_manual_asof.get(t)
                last_tr = str((per_security or {}).get(t, {}).get("last_trade_date") or pos.get("last_trade_date") or "")[:10]
                if v_asof and last_tr and last_tr > v_asof:
                    meta["manual_stale_date"].append((t, v_asof, last_tr))
        elif (kind != "bond" and ph.get("current_price_source") in ("cost_basis", "balance")
                and ph.get("value_rub") and ph.get("qty") and not_moex):
            val = round(float(ph["value_rub"]) / float(ph["qty"]) * qty, 2)    # внебиржевой
            meta["otc_from_prev"].append(t)
        if kind != "bond" and iis_exp is not None and iis_by_ticker.get(t):
            # акция на ИИС-3 или фонд на двух счетах: делить по счетам нечем, фонд на одном ИИС-3 уходит целиком
            if kind == "stock" or qty - (_f(iis_by_ticker[t].get("qty")) or 0.0) > 0.5:
                meta["iis_unrepresented"].append(t)
        if kind == "stock":
            stocks.append({"Тикер": t, "Название": name, "Стоимость": val, "Ср. Цена": _f(pos.get("avg_cost_rub"))})
        elif kind == "bond":
            ih = iis_by_ticker.get(t)
            qty_iis = _f((ih or {}).get("qty")) or 0.0
            pm = _f(ph.get("qty"))
            qty_main = qty
            # Сделки основной выгрузки бывают по сумме двух счетов (ОФЗ 26238: 80 основной + 130 ИИС)
            # или целиком по ИИС-3 (ОФЗ 52004/26244/26247/26253: в выгрузке есть, на основном 0 —
            # прогон 2026-10-22 задвоил их на 462 тыс. ₽). Остаток основного — тот из «qty» и
            # «qty − ИИС», что ближе к основному счёту прошлого снапшота (нет там бумаги — к нулю).
            if iis_exp is not None:
                # количество ИИС-3 точное (сделки его выгрузки): основной = выгрузка основного − ИИС-3
                if qty_iis:
                    qty_main = round(max(qty - qty_iis, 0.0), 6)
                    meta["bond_qty_split"].append(t)
                    if qty - qty_iis < -0.5:
                        meta["iis_exceeds_total"].append(t)
            elif qty_iis and qty - qty_iis > -0.5 and abs(qty - qty_iis - (pm or 0.0)) < abs(qty - (pm or 0.0)):
                qty_main = round(qty - qty_iis, 6)
                meta["bond_qty_split"].append(t)
            unit = val / qty if val and qty else None
            v_main = round(unit * qty_main, 2) if unit else val
            if qty_main <= 0.5:
                v_main = None                                  # бумага только на ИИС-3
            v_iis = round(unit * qty_iis, 2) if unit and qty_iis else (_f((ih or {}).get("value_rub")) or 0.0)
            if ih:
                meta[iis_mark].append(t)
            main_value[t] = (v_main or 0.0, qty_main)
            typed_prev = ph.get("plan_bucket") or (ih or {}).get("plan_bucket")
            b_isin = ph.get("isin") or isin or (ih or {}).get("isin")
            if typed_prev and not (plan_bonds.get(b_isin) or plan_bonds.get(t)):
                meta["bond_types_from_prev"].append(t)          # в плане этой облигации нет
            if ph.get("nominal") and not _f((q_all.get(t) or {}).get("face_value")):
                meta["nominal_from_prev"].append(t)
            bonds.append({"Тикер": t, "Название": name, "Текущая стоимость": round((v_main or 0) + v_iis, 2),
                          "Итого без ИИСа": v_main, "Итого на ИИС": v_iis or None,
                          "Всего": qty_main + qty_iis, "ИИС": qty_iis or None,
                          "Тип": ph.get("plan_bucket") or (ih or {}).get("plan_bucket"),
                          "Подтип": ph.get("plan_subtype") or (ih or {}).get("plan_subtype"),
                          "Рейтинг": ph.get("credit_rating_file") or (ih or {}).get("credit_rating_file"),
                          "Валюта номинала": pos.get("nominal_currency"), "Номинал": ph.get("nominal"),
                          "ISIN": ph.get("isin")})
        else:
            other.append({"Тикер": t, "Название": name, "Стоимость": val, "Кол-во": qty,
                          "Тип": "RUB - ИИС" if t in iis_by_ticker else ""})
            if t in iis_by_ticker:
                meta[iis_mark].append(t)

    seen_bonds = {b["Тикер"] for b in bonds} | {b.get("ISIN") for b in bonds if b.get("ISIN")}
    seen_other = {o["Тикер"] for o in other}
    for ih in prev_iis:                                   # позиции только на ИИС-3
        t = ih.get("ticker")
        if ih.get("asset_type") == "bond" and t not in seen_bonds and ih.get("isin") not in seen_bonds:
            v = _f(ih.get("value_rub")) or 0.0
            bonds.append({"Тикер": t, "Название": ih.get("name"), "Текущая стоимость": v, "Итого без ИИСа": None,
                          "Итого на ИИС": v, "Всего": _f(ih.get("qty")), "ИИС": _f(ih.get("qty")),
                          "Тип": ih.get("plan_bucket"), "Подтип": ih.get("plan_subtype"),
                          "Рейтинг": ih.get("credit_rating_file"), "Валюта номинала": ih.get("nominal_currency"),
                          "Номинал": ih.get("nominal"), "ISIN": ih.get("isin")})
            meta[iis_mark].append(t)
        elif ih.get("asset_type") != "bond" and t not in seen_other:
            other.append({"Тикер": t, "Название": ih.get("name"), "Стоимость": _f(ih.get("value_rub")),
                          "Кол-во": _f(ih.get("qty")), "Тип": "RUB - ИИС"})
            meta[iis_mark].append(t)

    iis_sec = sum((b.get("Итого на ИИС") or 0.0) for b in bonds) + sum(
        (o.get("Стоимость") or 0.0) for o in other if "ИИС" in o["Тип"])
    securities = (sum((x.get("Стоимость") or 0.0) for x in stocks) + sum((b.get("Текущая стоимость") or 0.0) for b in bonds)
                  + sum((o.get("Стоимость") or 0.0) for o in other))
    recon = prev.get("cash_reconciliation") or {}
    drift = _f(recon.get("current_drift_rub"))
    reconstructed = _f(snap.get("cash_balance_rub"))
    cash_est = round(reconstructed + drift, 2) if reconstructed is not None and drift is not None else None
    iis_cash_prev = _f(((prev.get("cash") or {}).get("by_account") or {}).get("iis_3")) or 0.0
    iis_cash = iis_cash_prev if cash_fact_iis is None else cash_fact_iis      # факт ИИС-3 подменяет перенос
    if cash_fact is not None:
        cash_est = round(cash_fact + iis_cash, 2)       # факт основного счёта + ИИС-3 (факт или из прошлого)
    elif cash_fact_iis is not None and cash_est is not None:
        cash_est = round(cash_est - iis_cash_prev + cash_fact_iis, 2)   # оценка основного та же, ИИС-3 — факт
    meta["iis_source"] = ("trades_export" if iis_exp is not None else
                          "carried" if meta["iis_from_prev"] else "none")
    meta.update(iis_cash_prev=iis_cash_prev, cash_est=cash_est, drift=drift, reconstructed=reconstructed,
                cash_fact=cash_fact,
                cash_fact_iis=cash_fact_iis)
    metrics = {
        "total_current_rub_incl_iis": round(securities + cash_est, 2) if cash_est is not None else None,
        "iis_balance_rub": round(iis_sec + iis_cash, 2),
        "iis_other_tickers": sorted(o["Тикер"] for o in other if "ИИС" in o["Тип"]),
    }
    metrics["total_current_rub_excl_iis"] = (round(metrics["total_current_rub_incl_iis"] - metrics["iis_balance_rub"], 2)
                                             if metrics["total_current_rub_incl_iis"] is not None else None)
    metrics["total_current_rub"] = metrics["total_current_rub_excl_iis"]
    return {"stocks": stocks, "bonds": bonds, "other_positions": other, "metrics": metrics,
            "_from_trades": True}, meta


# ── Корзина облигации выводится; средняя цена покупки (bond-subtypes-plan.md §4.5) ─────────────

def _apply_bond_derivations(
    holdings: list[dict], plan: dict | None, as_of: str, trades_path: str | None,
    iis_returns: dict | None, carry_sources: list[dict] | None, plan_path: str | None,
    types_path: str | None, reviews_dir: str | None,
) -> tuple[dict | None, list[dict]]:
    """Вывод корзины (bond_bucket) и средняя цена покупки (bond_avg_price) для облигаций-холдингов.
    Источники лежат рядом с plan.json (security-types.json, weekly-reviews/), если не заданы флагами;
    нет справочника → корзина как в плане (bucket_source=plan). Ошибка вывода сборку не роняет."""
    flags: list[dict] = []
    base = Path(plan_path).parent if plan_path else None
    tp = Path(types_path) if types_path else (base / "security-types.json" if base else None)
    rd = Path(reviews_dir) if reviews_dir else (base / "weekly-reviews" if base else None)
    types_data = bond_bucket.read_types_cache(tp) if tp else {}
    attrs = bond_bucket.attrs_by_isin(types_data)
    reviews = bond_bucket.load_review_ratings(rd, as_of)
    check = None
    if any(h.get("asset_type") == "bond" for h in holdings):
        check, bflags = bond_bucket.apply_bond_buckets(
            holdings, (plan or {}).get("bonds"), attrs, reviews, as_of, attrs_missing=not attrs)
        for f in bflags:
            flags.append(_flag("assemble_bonds", f["severity"], f["code"], f["message"]))
        if not attrs:
            flags.append(_flag("assemble_bonds", "info", "bond_attrs_unavailable",
                               "Справочник типов Мосбиржи без блока bond — корзины облигаций взяты из плана, "
                               "вывод не выполнен."))
    # средняя цена покупки: основной счёт — сделки основной выгрузки без сделок ИИС-3; ИИС-3 — своя выгрузка
    main_avgs = iis_avgs = None
    iis_rows = (iis_returns or {}).get("bond_trades")
    try:
        if trades_path and Path(trades_path).is_file():
            import portfolio_returns as pr
            tr = pr.parse_trades(trades_path)
            tr = pr.convert_trades_to_rub(tr, cbr_offline=True)
            tr, _corr = pr.apply_corrections(tr)
            if iis_rows:
                tr = bond_avg_price.subtract_trades(tr, bond_avg_price.expand_trades(iis_rows))
            main_avgs = bond_avg_price.bond_avg_prices(tr)
        if iis_rows:
            iis_avgs = bond_avg_price.bond_avg_prices(bond_avg_price.expand_trades(iis_rows))
    except Exception as e:                                   # noqa: BLE001 — средняя не должна ронять сборку
        flags.append(_flag("assemble_bonds", "info", "bond_avg_price_failed",
                           f"Средняя цена покупки облигаций не посчитана: {type(e).__name__}: {e}"))
    bond_avg_price.apply_bond_avg(holdings, main_avgs, iis_avgs, types_data)
    # ИИС-3 без новой выгрузки: средняя переносится из последнего снапшота при том же количестве
    for h in holdings:
        if h.get("asset_type") != "bond" or h.get("account") != "iis_3" or h.get("avg_price_pct") is not None:
            continue
        for src in carry_sources or []:
            hit = next((x for x in (src.get("holdings") or [])
                        if x.get("asset_type") == "bond" and x.get("account") == "iis_3"
                        and x.get("isin") == h.get("isin") and x.get("avg_cost_source") in ("trades", "carried")
                        and abs(float(x.get("qty") or 0) - float(h.get("qty") or 0)) < 1e-6), None)
            if hit:
                h["avg_price_pct"], h["avg_cost_rub"] = hit.get("avg_price_pct"), hit.get("avg_cost_rub")
                h["avg_cost_source"] = "carried"
                h["avg_includes_accint"] = bool(hit.get("avg_includes_accint"))
                break
    return check, flags


def assemble(
    portfolio: dict | None,
    returns: dict | None,
    per_security: dict | None,
    quotes: dict | None,
    *,
    trades_path: str | None = None,
    balance_path: str | None = None,
    prev_snapshot: dict | None = None,
    sector_overrides_path: str | None = None,
    rebaseline_cash: bool = False,
    recent_net_threshold_pct: float = 1.0,
    recent_net_threshold_rub: float | None = None,
    iis_returns: dict | None = None,
    iis_carry_sources: list[dict] | None = None,
    as_of: str | None = None,
    holdings_from_trades: bool = False,
    plan_path: str | None = None,
    plan_primary: bool = False,
    cash_fact: float | None = None,
    cash_fact_iis: float | None = None,
    types_path: str | None = None,
    reviews_dir: str | None = None,
    bond_locked_fetch: Any = None,
    forecasts_dir: str | None = None,
    per_security_closed: dict | None = None,
) -> dict:
    def _cash_arg(name, v):
        if v is None:
            return None
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"{name}: нужно число, получено {v!r}") from None
        if v != v or v in (float("inf"), float("-inf")) or v < 0:
            raise ValueError(f"{name}: нужно неотрицательное число ₽, получено {v}")
        return v
    cash_fact = _cash_arg("cash_fact", cash_fact)
    cash_fact_iis = _cash_arg("cash_fact_iis", cash_fact_iis)
    # as_of — для повтора пакета прогона в другой день (build_snapshot.py --replay)
    global _AS_OF_OVERRIDE
    _AS_OF_OVERRIDE = datetime.date.fromisoformat(as_of) if as_of else None
    today = as_of or datetime.date.today().isoformat()
    now   = time_msk.now_iso()
    flags: list[dict] = []

    portfolio_from_numbers = portfolio is not None      # до подмены синтетическим из сделок
    numbers_portfolio = portfolio                       # для сверки plan_primary: Numbers как есть
    # Сделки без баланса + plan.json = штатная сборка: план главный без флага (--plan-primary нужен
    # лишь при наличии Numbers — переключение балансного режима — решение владельца, plan §5.6)
    trades_mode = portfolio is None and bool(returns) and holdings_from_trades
    plan_obj = _read_plan(plan_path) if (plan_path and (plan_primary or trades_mode)) else None

    # Накопить holdings
    fx_rates = (returns or {}).get("fx_rates_asof")
    trades_meta = None
    if portfolio is None and returns and holdings_from_trades:
        quotes = dict(quotes or {})                     # ключи-ISIN облигаций добавляются сюда
        portfolio, trades_meta = _portfolio_from_trades(returns, prev_snapshot, today, quotes,
                                                        cash_fact=cash_fact, cash_fact_iis=cash_fact_iis,
                                                        plan=plan_obj, per_security=per_security,
                                                        iis_returns=iis_returns)
    elif (cash_fact is not None or cash_fact_iis is not None) and portfolio is not None:
        given = [f"{v:,.0f} ₽" for v in (cash_fact, cash_fact_iis) if v is not None]
        flags.append(_flag("assemble_cash", "info", "cash_fact_ignored",
                           f"Кэш, внесённый владельцем ({', '.join(given)}), не использован: есть "
                           "«Общий баланс» — кэш взят из него."))

    if plan_obj is not None and portfolio:
        # plan.json — главный источник плана: подменяет куски до всех расчётов (Numbers остаётся для сверки)
        import numbers_to_plan
        portfolio = numbers_to_plan.apply_plan_primary(portfolio, plan_obj, trades_mode=trades_meta is not None)
        if trades_meta is not None:
            portfolio.setdefault("ie_actual", {})["source_sheet"] = "plan.json"

    bond_check = None
    if portfolio:
        stock_holdings, stock_flags = _build_stocks(portfolio, returns or {}, quotes or {})
        bond_holdings,  bond_flags  = _build_bonds(portfolio, quotes or {}, fx_rates,
                                                   as_of_iso=today)
        fund_holdings               = _build_funds(portfolio, quotes or {}, returns or {})
        holdings = stock_holdings + bond_holdings + fund_holdings
        # Заблокированные (FinEx/RSH*/TBIO из returns) — видимы в holdings
        # со status=blocked, не участвуют в активных агрегатах downstream.
        blocked_holdings, blocked_flags = _build_blocked_positions(
            returns, {h["ticker"] for h in holdings})
        holdings += blocked_holdings
        flags.extend(stock_flags)
        flags.extend(bond_flags)
        flags.extend(blocked_flags)
        # Флаги из parse_portfolio.py (IIS-split, ie_model warnings, etc.)
        flags.extend(portfolio.get("data_quality_flags", []))
        # ИИС-3-позиции из вкладки «Другое» (SBGB): account main → iis_3.
        _apply_iis_accounts(holdings, portfolio)
        # METH-2: per-ticker first_appearance_date — carry-over из предыдущего
        # snapshot, иначе today (re-entry/новый тикер).
        _apply_first_appearance(holdings, prev_snapshot, today)
        # A3: сектор из SSOT sector-overrides.yaml (фоллбэк по тикеру/ISIN).
        _apply_sector_overrides(holdings, _load_sector_overrides(sector_overrides_path))
        # Канонический status на каждую позицию (SSOT: KNOWN_POSITION_STATUS);
        # is_blocked после этого — производное от status.
        _apply_position_status(holdings)
        bond_check, bond_check_flags = _apply_bond_derivations(
            holdings, plan_obj if plan_obj is not None else (_read_plan(plan_path) if plan_path else None),
            today, trades_path, iis_returns, iis_carry_sources, plan_path, types_path, reviews_dir)
        flags.extend(bond_check_flags)
        distressed = sorted({
            h["ticker"] for h in holdings
            if h.get("status") == "distressed" and h.get("ticker")
        })
        if distressed:
            flags.append(_flag(
                "assemble_status", "info", "distressed_positions",
                f"Distressed-позиции из реестра KNOWN_POSITION_STATUS: "
                f"{', '.join(distressed)}. Причины — в holdings[].status_note, "
                f"доли — в status_summary.by_status.",
            ))
    else:
        holdings = None

    # plan_primary без portfolio (нет ни баланса, ни сделок): из плана — только его куски
    plan_frag = None
    if plan_obj is not None and not portfolio:
        import numbers_to_plan
        plan_frag = numbers_to_plan.apply_plan_primary(None, plan_obj)
    plan_src = portfolio or plan_frag or {}

    metrics = (portfolio or {}).get("metrics", {})

    # Настоящий кэш: считается по готовым holdings (после статусов и счетов).
    if returns or portfolio:
        cash_block, cash_flags = _build_cash(returns, portfolio, holdings)
        flags.extend(cash_flags)
        if trades_meta is None and cash_block.get("total_rub") is not None:
            cash_block["fact_date"] = today              # кэш из баланса — факт на дату снапшота
    else:
        cash_block = None

    # PDL-6: план↔факт по 9 плановым корзинам облигаций (база excl_iis,
    # TLCB-фонд из «Tаблица 1» учтён — §3.1 плана).
    plan_for_classes = plan_obj if plan_obj is not None else (_read_plan(plan_path) if plan_path else None)
    bonds_plan_vs_fact, bonds_plan_vs_fact_iis, bpvf_flags = _build_bonds_plan_vs_fact(
        portfolio, holdings, (plan_for_classes or {}).get("funds"),
    )
    flags.extend(bpvf_flags)

    # Этап 4b: факт по классам и матрице валюта × класс (только при --plan; без плана — null)
    class_plan_vs_fact = matrix_plan_vs_fact = None
    if plan_for_classes is not None and holdings is not None:
        class_plan_vs_fact, matrix_plan_vs_fact, cb_flags = build_class_breakdown(
            holdings, cash_block, plan_for_classes,
            other_positions=((portfolio or {}).get("other_positions")
                             if (portfolio or {}).get("other_positions") is not None else None),
        )
        flags.extend(cb_flags)
        if portfolio_from_numbers:
            flags.extend(_class_fact_mismatch(
                matrix_plan_vs_fact, ((numbers_portfolio or {}).get("goals") or {}).get("matrix")))

    if trades_meta is not None and plan_obj is not None and portfolio:
        # Без баланса колонки формул Numbers («Сейчас», «План сумма», …) считает загрузчик — из holdings
        _trades_plan_facts(portfolio, holdings, bonds_plan_vs_fact, class_plan_vs_fact, matrix_plan_vs_fact)

    # PDL-7/PDL-14: balance_total_vs_trades_drift — монитор реконструкции
    # (info) на сведённых базах: фактический кэш вместо реконструированного
    # + НКД к чистым ценам. Молчит при нехватке любого из входов.
    drift_flag = _check_balance_vs_trades_drift(
        portfolio, returns, holdings,
        (cash_block or {}).get("total_rub"), fx_rates,
    )
    if drift_flag:
        flags.append(drift_flag)

    # Правило неразворота ru-portfolio-advisor (Rule 3): окно берём из того,
    # что реально посчитал per_security_xirr.py (не пере-декларируем, чтобы
    # не разъезжалось); порог — от акционной книги/NAV, см. _derive_recent_net_threshold.
    recent_window_days = _recent_window_days_from_per_security(per_security)
    recent_threshold_rub, recent_threshold_basis = _derive_recent_net_threshold(
        portfolio, recent_net_threshold_pct, recent_net_threshold_rub,
    )

    # Отпечаток выгрузки сделок (trades_digest.py, PDL-RECON 2026-10-21): следующий прогон
    # сравнит его с новой выгрузкой на эту же дату — правки задним числом. Сбой разбора не
    # роняет сборку: отпечатка просто нет (сравнение на следующем прогоне промолчит).
    digest = None
    if trades_path:
        try:
            import trades_digest  # noqa: WPS433
            digest = trades_digest.from_trades_file(trades_path, today)
        except Exception as exc:  # noqa: BLE001
            flags.append(_flag("trades_digest", "warning", "trades_digest_failed",
                               f"Отпечаток выгрузки сделок не построен: {exc}"))

    iis_acc = _resolve_iis_flows(iis_returns, iis_carry_sources)
    iis_stale: list[str] = []
    per_instrument = (_build_per_instrument_xirr(
        per_security, recent_threshold_rub, holdings, returns, iis_acc["flows"], today,
        iis_carried=iis_acc["source"] == "carried", stale_out=iis_stale) if per_security else None)
    per_instrument_closed = (_build_closed_instrument_xirr(
        per_security_closed, per_instrument, holdings, iis_acc["flows"], today,
        iis_carried=iis_acc["source"] == "carried") if per_security_closed is not None else None)
    if per_instrument and (returns or {}).get("live_basis"):
        fl_t, fl_a = _live_flows_by_ticker(per_security, per_instrument, iis_acc["flows"], today)
        returns = {**returns, "live_basis": {**returns["live_basis"], "flows_by_ticker": fl_t,
                                             **({"flows_by_ticker_account": fl_a} if fl_a else {})}}
    if iis_stale:
        flags.append(_flag("assemble_xirr", "warn", "iis_trades_stale",
                           f"Доходность по счетам не посчитана для {len(iis_stale)} бумаг ({', '.join(sorted(iis_stale))}): "
                           f"остаток ИИС-3 по балансу расходится с перенесёнными сделками ИИС-3 — пришли свежую выгрузку ИИС-3."))

    snapshot: dict[str, Any] = {
        "schema_version": "2.0",
        "as_of_date":     today,
        "generated_at":   now,
        "input_files": {
            "trades":  Path(trades_path).name  if trades_path  else None,
            "balance": Path(balance_path).name if balance_path else None,
        },
        "holdings":           holdings,
        "status_summary":     _build_status_summary(holdings) if holdings is not None else None,
        "cash":               cash_block,
        "returns":            _build_returns(returns)                   if returns    else None,
        "per_instrument_xirr":per_instrument,
        # проданные и погашенные бумаги (closed=true) — отдельно: per_instrument_xirr читают как «что держу»
        "per_instrument_xirr_closed": per_instrument_closed,
        "iis_trades_source":  iis_acc["source"],
        # откуда позиции ИИС-3: trades_export (сделки выгрузки счёта) | balance («Общий баланс») | carried (прошлый снапшот)
        # | none (позиций ИИС-3 нет ни в одном источнике)
        "iis_positions_source": ((trades_meta or {}).get("iis_source") if trades_meta is not None
                                 else ("balance" if portfolio_from_numbers else None)),
        "iis_account_flows":  ({"file_last_operation": iis_acc["file_last_operation"], "flows": iis_acc["flows"]}
                               if iis_acc["flows"] else None),
        # Параметры окна/порога, применённые ко всем recent_*-полям per_instrument_xirr
        # (Rule 3 ru-portfolio-advisor, правило неразворота). None, если
        # per_security.json ещё не несёт recent_window_days (старый прогон без фичи).
        "recent_trades_window": (
            {
                "days": recent_window_days,
                "net_threshold_rub": recent_threshold_rub,
                "threshold_basis": recent_threshold_basis,
            } if recent_window_days is not None else None
        ),
        "ie_model":           plan_src.get("ie_model"),
        "ie_actual":          plan_src.get("ie_actual"),
        "ie_summary":         (portfolio or {}).get("ie_summary"),
        "balance_summary": {
            "total_current_rub":         metrics.get("total_current_rub"),
            "total_current_rub_excl_iis":metrics.get("total_current_rub_excl_iis"),
            "total_current_rub_incl_iis":metrics.get("total_current_rub_incl_iis"),
            "iis_balance_rub":           metrics.get("iis_balance_rub"),
            # PDL-5: закрывает дефект D — bonds_value_by_type_excl_iis уже
            # считался в metrics, но не докатывался до снапшота, хотя
            # bonds-methodology.md предписывает его читать отсюда.
            "bonds_value_by_type_excl_iis":    metrics.get("bonds_value_by_type_excl_iis"),
            "bonds_value_by_type_iis_only":    metrics.get("bonds_value_by_type_iis_only"),
            "bonds_value_by_subtype":          metrics.get("bonds_value_by_subtype"),
            "bonds_value_by_subtype_excl_iis": metrics.get("bonds_value_by_subtype_excl_iis"),
            "bonds_value_by_subtype_iis_only": metrics.get("bonds_value_by_subtype_iis_only"),
            # PDL-6: план↔факт по 9 плановым корзинам (см. _build_bonds_plan_vs_fact).
            "bonds_plan_vs_fact":        bonds_plan_vs_fact,
            "bonds_plan_vs_fact_iis":    bonds_plan_vs_fact_iis,
            # Этап 4b: факт по классам / валюта × класс (build_class_breakdown); null без --plan.
            "class_plan_vs_fact":        class_plan_vs_fact,
            "matrix_plan_vs_fact":       matrix_plan_vs_fact,
            "by_account":                metrics.get("by_account"),
            "summary":                   (portfolio or {}).get("summary"),
            "goals_overall":             (plan_src.get("goals") or {}).get("overall"),
            "goals_bonds_breakdown":     (plan_src.get("goals") or {}).get("bonds_breakdown"),
            # PDL-13 (RPA-17): матрица «Планы» (Валюта × Тип) и таблица «Проверка»
            # парсились в portfolio.json, но в снапшот не доезжали — из-за этого
            # раздел «Входные данные» rebalance-framework.md ссылался на пути
            # промежуточного файла (`goals.matrix`, `errors_check`), которых у
            # Mode 3 на руках не было. Валютная аллокация — вход ребалансировки,
            # без неё режим слеп к плану по валютам.
            "goals_matrix":              (plan_src.get("goals") or {}).get("matrix"),
            "goals_matrix_iis":          (portfolio or {}).get("goals", {}).get("matrix_iis"),
            "errors_check":              (portfolio or {}).get("errors_check"),
        } if portfolio else None,
        "corrections_log":    _build_corrections_log(returns) if returns else [],
        "fx_rates_used":      fx_rates,
        "bond_cashflow_calendar": (
            # 24 мес = максимальный горизонт анализа (6/12/24): viewer режет
            # календарь по выбранному горизонту, окно должно покрывать самый дальний.
            _build_bond_cashflow(holdings, fx_rates, today, months=24)
            if holdings is not None else None
        ),
        "data_quality_flags": flags,
        "trades_digest":      digest,
    }

    cash_recon, cash_flag = _build_cash_reconciliation(
        returns,
        # без баланса кэш — оценка через прошлое расхождение: сверять её с тем же расхождением
        # бессмысленно (решение cash_drift_changed было бы эхом прошлого снапшота)
        None if (trades_meta and trades_meta.get("cash_fact") is None) else (cash_block or {}).get("total_rub"),
        prev_snapshot, today, rebaseline=rebaseline_cash,
    )
    snapshot["cash_reconciliation"] = cash_recon
    # Провалы курса ЦБ в portfolio_returns (сделка → 0 ₽, бумага без курса → по стоимости покупки):
    # числа снапшота неверны. Флаг error — build_snapshot/checks запрещает запись.
    gaps = (returns or {}).get("fx_gaps") or []
    if gaps:
        def _gdesc(g):
            tk = ", ".join(g.get("tickers") or []) or "?"
            if g["kind"] == "trade_zeroed":
                return (f"нет курса ЦБ для {g['currency']} — сделки пересчитаны в 0 ₽ "
                        f"(бумаги {tk}; {g['n']} шт., {g['first']}…{g['last']})")
            return f"нет курса ЦБ для {g['currency']} — бумага {tk} оценена по стоимости покупки"
        desc = "; ".join(_gdesc(g) for g in gaps)
        snapshot["data_quality_flags"].append(_flag(
            "fx_rates", "error", "fx_rates_missing",
            f"{desc}. Доходности и стоимости неверны — нужен доступ к cbr.ru "
            "(VPN!) или свежий кэш курсов; если ЦБ валюту не публикует — бумагу не оценить; "
            "снапшот не сохранять."))
    if cash_flag:
        snapshot["data_quality_flags"].append(cash_flag)
    fb = _returns_price_fallbacks(returns, holdings)
    if fb:
        src = {"last_trade_price": "цена последней сделки", "cost_basis": "по стоимости покупки"}

        def _src(x):
            return src.get(str(x["source"]).split("+")[0], x["source"])
        desc = "; ".join(
            (f"{x['ticker']} — {_src(x)} {x['used_price']:g} ₽ вместо "
             f"{x['moex_price']:g} ₽ MOEX ({x['diff_rub']:+,.0f} ₽)".replace(",", " "))
            if x["moex_price"] is not None else
            f"{x['ticker']} (облигация) — {_src(x)}, {format(x['used_price'], ',.2f').replace(',', ' ')} ₽ "
            "за бумагу, хотя котировка MOEX есть"
            for x in fb)
        snapshot["data_quality_flags"].append(_flag(
            "returns_prices", "error", "returns_price_not_moex",
            f"Доходность посчитана не по цене MOEX: {desc}. XIRR, результат по типам и кэш неверны — "
            "MOEX ISS не отдал котировку при расчёте доходности. Перезапусти portfolio_returns.py, "
            "когда MOEX доступен (или собери на сайте); снапшот не сохранять."))
    pi_fb, pi_mm = _per_instrument_price_check(snapshot.get("per_instrument_xirr"), holdings)
    if pi_fb:
        src = {"last_trade": "цена последней сделки", "cost_basis": "по стоимости покупки"}
        desc = "; ".join(f"{x['ticker']} — {src.get(x['source'], x['source'])} {x['used_price']:g} ₽ вместо "
                         f"{x['moex_price']:g} ₽ MOEX ({x['diff_rub']:+,.0f} ₽)".replace(",", " ") for x in pi_fb)
        snapshot["data_quality_flags"].append(_flag(
            "per_instrument_prices", "error", "per_instrument_price_not_moex",
            f"XIRR и результат по бумагам посчитаны не по цене MOEX: {desc}. MOEX ISS не отдал "
            "котировку при расчёте per_security_xirr. Собери на сайте или повтори, когда MOEX "
            "доступен; снапшот не сохранять."))
    if pi_mm:
        desc = "; ".join(f"{x['ticker']} {x['used_price']:g} ₽ против {x['moex_price']:g} ₽ "
                         f"({x['diff_pct']:+.2f}%)" for x in pi_mm)
        snapshot["data_quality_flags"].append(_flag(
            "per_instrument_prices", "warning", "per_instrument_value_mismatch",
            f"Цена в per_instrument_xirr расходится с holdings более чем на 0,5%: {desc}. "
            "Источник MOEX и там и там — проверь, не разные ли моменты котировок."))

    # Сверка «Общий баланс vs расчёт по сделкам» (период параллельного ведения
    # с 2026-10-13): additive, только флаги — не ошибка загрузки.
    bvt, bvt_flags = _build_balance_vs_trades(holdings, returns)
    snapshot["reconciliation"] = {"balance_vs_trades": bvt}
    snapshot["data_quality_flags"].extend(bvt_flags)
    bqt, bqt_flags = _build_bond_qty_vs_trades(holdings, snapshot.get("per_instrument_xirr"))
    if bqt is not None:
        snapshot["reconciliation"]["bond_qty_vs_trades"] = bqt
    snapshot["data_quality_flags"].extend(bqt_flags)

    if trades_meta is not None:
        _finish_trades_mode(snapshot, prev_snapshot, trades_meta, plan=plan_obj)
    if not portfolio:
        snapshot["snapshot_type"] = "returns_only"
        snapshot["data_quality_flags"].append(_flag(
            "parse_balance", "info", "no_balance_file",
            "Общий баланс не приложен. holdings = null. IE-данные недоступны.",
        ))

    # Обогатить cash секцию cash_equiv_rub / liquid_rub из fund-позиций.
    # total_rub — настоящий кэш (без денежных фондов), поэтому
    # liquid_rub = total_rub + cash_equiv_rub двойного счёта не содержит.
    if holdings is not None and snapshot.get("cash") is not None:
        equiv: dict[str, float] = {
            h["ticker"]: float(h["value_rub"])
            for h in holdings
            if h.get("ticker") in CASH_EQUIV_TICKERS
            and isinstance(h.get("value_rub"), (int, float))
            and float(h.get("value_rub", 0)) > 0
        }
        cash_equiv_rub = round(sum(equiv.values()), 2)
        total_rub = snapshot["cash"].get("total_rub")
        snapshot["cash"]["cash_equiv_rub"] = cash_equiv_rub
        snapshot["cash"]["liquid_rub"] = (
            round((total_rub or 0.0) + cash_equiv_rub, 2)
            if total_rub is not None else None
        )
        if equiv:
            snapshot["cash"]["cash_equiv_tickers"] = {
                k: round(v, 2) for k, v in equiv.items()
            }

    # Доходность БКС-ИИС-3 из отдельной выгрузки (iis_returns.py) — additive.
    iis_block, iis_flags = _build_iis_account_returns(iis_returns, holdings, portfolio)
    if iis_block is not None:
        if snapshot.get("returns") is None:
            snapshot["returns"] = {}
        snapshot["returns"]["by_account"] = {"iis_3": iis_block}
        snapshot["data_quality_flags"].extend(iis_flags)
    elif iis_returns is None and iis_carry_sources:
        carried, carry_flags = _carry_iis_block(iis_carry_sources, holdings)
        if carried is not None:
            if snapshot.get("returns") is None:
                snapshot["returns"] = {}
            snapshot["returns"].setdefault("by_account", {})["iis_3"] = carried
            snapshot["data_quality_flags"].extend(carry_flags)

    # «При покупке» облигаций обоих счетов (bond_locked): ИИС-3 — из per_bond блока, основной — по графику MOEX
    if holdings is not None:
        try:
            infl = None
            if bond_locked_fetch is not None:
                import iis_returns as _ir
                infl = _ir.load_inflation(forecasts_dir)
            iis_pb = ((((snapshot.get("returns") or {}).get("by_account") or {}).get("iis_3")) or {}).get("per_bond")
            bond_locked.apply_locked(
                holdings, as_of=today, per_security=per_security, per_instrument=per_instrument,
                iis_flows=iis_acc["flows"], iis_per_bond=iis_pb, fetch=bond_locked_fetch, infl=infl)
        except Exception as e:                                                      # noqa: BLE001 — расчёт не роняет сборку
            snapshot["data_quality_flags"].append(_flag(
                "assemble_bonds", "info", "bond_locked_failed",
                f"«При покупке» облигаций не посчитано: {type(e).__name__}: {e}"))

    if bond_check is not None:
        snapshot["bond_bucket_check"] = bond_check

    # План из plan.json (этап 1 ухода от Numbers): сверка с планом из Numbers, снапшот не меняет
    if plan_path:
        snapshot["plan_check"] = _build_plan_check(
            plan_path, numbers_portfolio if portfolio_from_numbers else None, primary=plan_primary,
            applied=trades_meta is not None and plan_obj is not None)

    return snapshot


def _read_plan(plan_path: str) -> dict | None:
    """plan.json как объект; нечитаемый → None (сборка идёт по Numbers, plan_check скажет error)."""
    try:
        plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
        return plan if isinstance(plan, dict) else None
    except (OSError, ValueError):
        return None


def _build_plan_check(plan_path: str, portfolio: dict | None, primary: bool = False, applied: bool = False) -> dict:
    """plan_check {source, plan_file, plan_updated_at, n_diff, diff[]}: both — Numbers + plan.json
    (diff = numbers_to_plan.plan_diff); plan_only — Numbers нет: сравнивать не с чем (n_diff 0), applied=true —
    сборка без баланса взяла план из plan.json (этап 6); error — файл не читается, сборка не падает."""
    name = Path(plan_path).name
    try:
        plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
        if not isinstance(plan, dict):
            raise ValueError("корень plan.json не объект")
        updated = plan.get("updated_at")
        if portfolio is None:
            return {"source": "plan_only", "plan_file": name, "plan_updated_at": updated, "applied": applied,
                    "n_diff": 0, "diff": []}
        import numbers_to_plan
        diff = numbers_to_plan.plan_diff(portfolio, plan)
        return {"source": "plan_primary" if primary else "both", "plan_file": name, "plan_updated_at": updated,
                "n_diff": len(diff), "diff": diff}
    except (OSError, ValueError) as e:
        sys.stderr.write(f"WARNING: plan.json не прочитан ({plan_path}): {e}\n")
        return {"source": "error", "plan_file": name, "error": str(e)}


def _by_account_from_holdings(holdings: list[dict], bs: dict) -> dict:
    """balance_summary.by_account без «Общего баланса» — тот же смысл полей, что у сборки с баланса, но из holdings.

    main: stocks/bonds — по account=main; funds_rub — фонды «Таблицы 1» (без денежных CASH_EQUIV_TICKERS и без
    внебиржевых RETURNS_PRICE_MANUAL — их во вкладках баланса нет); cash_rub — «грязный» остаток
    total − stocks − bonds − funds (настоящий кэш + денежные фонды + FINAMAR), настоящий кэш — блок `cash`.
    iis_3: total = iis_balance_rub; funds_rub — реальные фонды счёта (у сборки с баланса там 0, а фонд вычтен из
    cash_rub); cash_rub = total − bonds − stocks − funds. Нет итога (кэш неизвестен) → total/cash_rub None."""
    def acc(account: str, kind: str, skip: frozenset = frozenset()) -> float:
        return round(sum(float(h["value_rub"]) for h in holdings
                         if h.get("account") == account and h.get("asset_type") == kind
                         and h.get("ticker") not in skip and h.get("status") != "blocked"
                         and isinstance(h.get("value_rub"), (int, float))), 2)
    out: dict[str, dict] = {}
    for account, total in (("main", bs.get("total_current_rub_excl_iis")), ("iis_3", bs.get("iis_balance_rub"))):
        skip = (CASH_EQUIV_TICKERS | RETURNS_PRICE_MANUAL) if account == "main" else frozenset()
        stocks, bonds, funds = acc(account, "stock"), acc(account, "bond"), acc(account, "fund", skip)
        out[account] = {
            "total_rub": total, "stocks_rub": stocks, "bonds_rub": bonds, "funds_rub": funds,
            "cash_rub": round(total - stocks - bonds - funds, 2) if total is not None else None,
        }
    return out


def _finish_trades_mode(snapshot: dict, prev: dict | None, meta: dict, plan: dict | None = None) -> None:
    """Без баланса: план, цели и доли (IE) — из plan.json (если он применён), иначе из прошлого снапшота
    с пометкой даты (запасной путь, флаг no_plan_for_trades_mode); из прошлого снапшота всегда — только то,
    чего нет ни в плане, ни в сделках, ни в котировках (meta.carried); итоги стоимости — по позициям."""
    prev = prev or {}
    d = meta.get("prev_date") or "—"
    snapshot["snapshot_type"] = "trades_holdings"
    snapshot["input_files"]["balance"] = None
    for h in snapshot.get("holdings") or []:
        if h.get("avg_cost_source") == "balance":
            h["avg_cost_source"] = "trades"          # «Ср. Цена» синтетического баланса — WACC сделок
    plan_date = (plan or {}).get("updated_at") if plan else None
    fact = meta.get("cash_fact")
    fact_iis = meta.get("cash_fact_iis")
    # Что взято из прошлого снапшота (balance_summary.carried): позиции ИИС-3 (сделок счёта нет), кэш по
    # прошлому расхождению, ИИС-3-кэш без факта, названия/номинал/корзины, которых нет в котировках и плане
    carried: list[str] = []
    if meta.get("iis_from_prev"):
        carried.append("iis_positions")
    if fact is None and meta.get("cash_est") is not None:
        carried.append("cash_drift")
    if fact_iis is None and (meta.get("iis_cash_prev") or 0.0):
        carried.append("iis_cash")
    if meta.get("names_from_prev"):
        carried.append("names")
    if meta.get("nominal_from_prev"):
        carried.append("nominal")
    if meta.get("bond_types_from_prev"):
        carried.append("bond_types")
    carried += [f"otc_price:{t}" for t in meta.get("otc_from_prev") or []]
    if plan is None:
        carried += ["ie_model", "goals", "plan_vs_fact"]        # запасной путь: цели и IE — прошлый снапшот
        bd = meta.get("balance_date") or meta.get("prev_date")
        for k in ("ie_model", "ie_actual", "ie_summary"):
            snapshot[k] = prev.get(k)
    else:
        bd = (meta.get("balance_date") or meta.get("prev_date")) if carried else None
    snapshot["balance_carried_from"] = bd
    # Без плана переносятся цели и план↔факт; «Имеется», стоимости по типам, «Проверка» прошлого баланса — нет
    # (прогон 2026-10-22: блок «позиции + кэш ≠ Имеется» сравнивал сегодняшние позиции с «Имеется» от 16.10).
    old = prev.get("balance_summary") or {}
    bs = dict(snapshot.get("balance_summary") or {})
    if plan is None:
        for k in ("goals_overall", "goals_bonds_breakdown", "goals_matrix", "goals_matrix_iis",
                  "bonds_plan_vs_fact", "bonds_plan_vs_fact_iis"):
            bs[k] = old.get(k)
    bs["summary"] = None
    bs["carried_from"] = bd
    bs["carried"] = carried
    if snapshot.get("holdings") is not None:
        bs["by_account"] = _by_account_from_holdings(snapshot["holdings"], bs)
    snapshot["balance_summary"] = bs
    cash = snapshot.get("cash") or {}
    as_of = snapshot.get("as_of_date")
    fact_date = as_of if (fact is not None or fact_iis is not None) else meta.get("prev_fact_date")
    if cash:
        cash["fact_date"] = fact_date
        cash["iis_source"] = "owner_intelinvest" if fact_iis is not None else "carried_from_prev"
        if fact is not None:
            cash["source"] = "owner_intelinvest"
            cash["note"] = (f"«Общий баланс» не приложен: кэш основного счёта внесён владельцем из "
                            f"IntelInvest {as_of}: {fact:,.0f} ₽; ИИС-3 — "
                            + (f"внесён владельцем: {fact_iis:,.0f} ₽." if fact_iis is not None else f"из снапшота {d}."))
        else:
            cash["source"] = "trades_plus_prev_drift"
            cash["note"] = (f"«Общий баланс» не приложен: кэш = реконструкция по сделкам "
                            f"{meta.get('reconstructed')} ₽ + расхождение факт−реконструкция "
                            f"{meta.get('drift')} ₽ из снапшота {d}. Оценка, не факт."
                            + (f" ИИС-3 внесён владельцем: {fact_iis:,.0f} ₽." if fact_iis is not None else ""))
    if fact is None:
        age = None
        fact_date = meta.get("prev_fact_date")          # возраст оценки основного счёта; факт ИИС-3 его не освежает
        try:
            if fact_date and as_of:
                age = (datetime.date.fromisoformat(as_of) - datetime.date.fromisoformat(fact_date)).days
        except ValueError:
            age = None
        if age is None or age > CASH_FACT_MAX_AGE_DAYS:
            since = (f"от {fact_date} ({age} дн.)" if age is not None else "(дата факта неизвестна)")
            snapshot["data_quality_flags"].append(_flag(
                "assemble_cash", "warning", "cash_fact_stale",
                f"Кэш — оценка по расхождению {since}. Внеси свободные деньги основного портфеля "
                "из IntelInvest (все валюты в рублях) — сборка возьмёт их фактом."))
    if plan is not None:
        parts = [f"названия — из котировок/прошлого снапшота {d}; корзины облигаций, доли и цели (IE), план — "
                 f"из базы сайта (plan.json от {plan_date or '—'})"]
        if meta.get("otc_from_plan"):
            parts.append("стоимость внебиржевых — из плана: " + ", ".join(meta["otc_from_plan"]))
        if meta.get("iis_from_export"):
            parts.append(f"ИИС-3 — позиции по сделкам выгрузки счёта ({len(set(meta['iis_from_export']))})")
        if meta.get("iis_from_prev"):
            parts.append(f"ИИС-3 — позиции снапшота {d} ({len(set(meta['iis_from_prev']))}), сделок счёта нет")
    else:
        parts = [f"позиции и стоимость — из сделок по ценам MOEX; названия, корзины облигаций, доли и цели (IE), "
                 f"план↔факт — из снапшота {d}"]
        if meta.get("iis_from_export"):
            parts.append(f"ИИС-3 — позиции по сделкам выгрузки счёта ({len(set(meta['iis_from_export']))})")
        if meta.get("iis_from_prev"):
            parts.append(f"ИИС-3 — позиции снапшота {d} ({len(set(meta['iis_from_prev']))})")
    if meta.get("iis_unrepresented"):
        snapshot["data_quality_flags"].append(_flag(
            "assemble_trades_mode", "warning", "iis_positions_not_split",
            "ИИС-3 по сделкам: акция на ИИС-3 или фонд на двух счетах сразу — делить по счетам нечем: "
            "акция остаётся на основном счёте, фонд целиком относится к ИИС-3: "
            + ", ".join(sorted(set(meta["iis_unrepresented"]))) + "."))
    if meta.get("iis_exceeds_total"):
        snapshot["data_quality_flags"].append(_flag(
            "assemble_trades_mode", "warning", "iis_qty_exceeds_total",
            "ИИС-3 по сделкам: количество на ИИС-3 больше, чем во всей выгрузке основного счёта — "
            "основной принят нулевым, выгрузки разошлись по дате: " + ", ".join(sorted(set(meta["iis_exceeds_total"]))) + "."))
    if meta.get("otc_from_prev"):
        parts.append("внебиржевые по цене снапшота " + d + ": " + ", ".join(meta["otc_from_prev"]))
    if meta.get("bond_qty_split"):
        parts.append("облигации, где сделки дали сумму двух счетов: " + ", ".join(meta["bond_qty_split"]))
    parts.append("кеш — факт, внесённый владельцем из IntelInvest" if fact is not None else
                 "кеш — оценка (реконструкция + прошлое расхождение)" if meta.get("cash_est") is not None
                 else "кеш неизвестен (в прошлом снапшоте нет расхождения)")
    snapshot["data_quality_flags"].append(_flag(
        "assemble_trades_mode", "warning", "balance_absent_holdings_from_trades",
        "«Общий баланс» не приложен: " + "; ".join(parts) + "."))
    def _ru(x: float, nd: int = 3) -> str:
        return f"{x:,.{nd}f}".replace(",", " ").replace(".", ",").rstrip("0").rstrip(",") if nd else f"{x:,.0f}".replace(",", " ")
    for t, pq, qty, val in meta.get("manual_stale") or []:
        snapshot["data_quality_flags"].append(_flag(
            "assemble_trades_mode", "warning", "manual_value_stale",
            f"{t}: количество по сделкам изменилось ({_ru(pq)} → {_ru(qty)} шт.), а оценка в базе сайта осталась "
            f"{_ru(val, 0)} ₽ — обнови «Оценку вручную» в карточке фонда."))
    def _dmy(iso: str) -> str:
        y, mo, d_ = iso.split("-")
        return f"{d_}.{mo}.{y}"
    for t, v_asof, last_tr in meta.get("manual_stale_date") or []:
        snapshot["data_quality_flags"].append(_flag(
            "assemble_trades_mode", "warning", "manual_value_stale",
            f"{t}: оценка в базе сайта от {_dmy(v_asof)}, последняя сделка {_dmy(last_tr)} — "
            "обнови «Оценку вручную» в карточке фонда."))
    if plan is None:
        snapshot["data_quality_flags"].append(_flag(
            "assemble_trades_mode", "warning", "no_plan_for_trades_mode",
            f"plan.json нет или он не читается: доли и цели (IE), план↔факт взяты из снапшота {d} — "
            "могут быть старше базы сайта."))
    if not prev:
        snapshot["data_quality_flags"].append(_flag(
            "assemble_trades_mode", "warning", "no_prev_snapshot_for_trades_mode",
            "Нет прошлого снапшота: названия, корзины облигаций (вне плана) и ИИС-3 не перенесены, "
            "кэш не оценён."))


# ── CLI ───────────────────────────────────────────────────────────────────────

def _fetch_schedule(secid: str) -> dict:
    import iis_returns
    return iis_returns.fetch_schedule(secid)


def main() -> None:
    p = argparse.ArgumentParser(description="Сборка portfolio snapshot v2 из промежуточных файлов")
    p.add_argument("--portfolio",    default="/tmp/portfolio.json",    help="Выход parse_portfolio.py")
    p.add_argument("--returns",      default="/tmp/returns.json",      help="Выход portfolio_returns.py")
    p.add_argument("--per-security", default="/tmp/per_security.json", help="Выход per_security_xirr.py")
    p.add_argument("--per-security-closed", default=None,
                   help="Выход per_security_xirr.py по закрытым бумагам → per_instrument_xirr_closed")
    p.add_argument("--quotes",       default="/tmp/quotes.json",       help="Выход moex_quotes.py")
    p.add_argument("--output",       default=None,                     help="Путь записи (default: stdout)")
    p.add_argument("--trades",       default=None,                     help="Путь к trades-файлу (метаданные)")
    p.add_argument("--balance",      default=None,                     help="Путь к balance-файлу (метаданные)")
    p.add_argument("--prev-snapshot", default=None,
                   help="Путь к предыдущему portfolio-<date>.json для carry-over first_appearance_date (METH-2)")
    p.add_argument("--sector-overrides", default=None,
                   help="Путь к sector-overrides.yaml (Claude-Memory/sector-overrides.yaml). "
                        "Обогащает holdings[].sector (машинный ключ) и holdings[].sector_ru "
                        "(отображаемый ярлык, если задан) по тикеру/ISIN; нет в файле → null.")
    p.add_argument("--cash-fact", type=float, default=None, metavar="RUB",
                   help="Свободные деньги ОСНОВНОГО портфеля из IntelInvest, ₽ (все валюты в рублях; без ИИС-3). "
                        "Только в режиме без баланса (--holdings-from-trades): становится фактом кэша и "
                        "опорой расхождения; с балансом игнорируется.")
    p.add_argument("--cash-fact-iis", type=float, default=None, metavar="RUB",
                   help="Свободные деньги ИИС-3, ₽ (только рублёвый кэш). Режим без баланса: подменяет перенос "
                        "кэша ИИС-3 из прошлого снапшота; с балансом игнорируется.")
    p.add_argument("--rebaseline-cash", action="store_true",
                   help="Принять текущее кэш-расхождение (факт − реконструкция из трейдов) "
                        "как новый baseline. Без флага baseline едет из prev-snapshot, "
                        "warning при изменении > 10 тыс. ₽.")
    p.add_argument(
        "--recent-net-threshold-pct", type=float, default=1.0,
        help="Порог recent_direction (правило неразворота ru-portfolio-advisor, "
             "Rule 3) в процентных пунктах «акционной книги» (goals_matrix "
             "RUB/Акция «Сейчас»); fallback — NAV excl. ИИС. По умолчанию 1.0.",
    )
    p.add_argument(
        "--recent-net-threshold-rub", type=float, default=None,
        help="Явный override порога recent_direction в ₽ — вместо расчёта "
             "от акционной книги/NAV.",
    )
    p.add_argument("--snapshots-dir", default=None,
                   help="Каталог Portfolio/snapshots/ (только чтение): если нет --iis-returns, "
                        "блок returns.by_account.iis_3 переносится из последнего снапшота, где он есть "
                        "(включая файл того же дня, который будет перезаписан), с carried_from.")
    p.add_argument("--as-of", default=None,
                   help="Дата снапшота YYYY-MM-DD (default: сегодня). Для повтора "
                        "пакета прогона build_snapshot.py --replay.")
    p.add_argument("--holdings-from-trades", action="store_true",
                   help="Нет --portfolio («Общий баланс» не приложен): позиции из сделок, остальное из "
                        "--prev-snapshot (build_snapshot.py включает сам, решение 2026-10-21).")
    p.add_argument("--iis-returns", default=None,
                   help="Выход iis_returns.py (доходность БКС-ИИС-3 по отдельной "
                        "выгрузке) → returns.by_account.iis_3. Нет файла — блока нет.")
    p.add_argument("--plan-primary", action="store_true",
                   help="plan.json — главный источник плана (с --plan): куски плана из него подменяют куски "
                        "portfolio.json; Numbers остаётся для сверки (plan_check.source=plan_primary). "
                        "По умолчанию выключен (решение владельца §5.6).")
    p.add_argument("--types-cache", default=None,
                   help="Portfolio/security-types.json (блок bond: эмитент, срок, флоатер, валюта номинала) — "
                        "вывод корзины облигации. Нет флага — рядом с --plan; нет и его — корзина как в плане.")
    p.add_argument("--splits-file", default=None,
                   help="Portfolio/known-splits.json — реестр сплитов (дополняет встроенный набор); "
                        "нужен для known_split в сверке баланса со сделками.")
    p.add_argument("--no-bond-locked", action="store_true",
                   help="не считать «При покупке» облигаций основного счёта (нет сети к MOEX ISS)")
    p.add_argument("--forecasts-dir", default=None,
                   help="Claude-Memory/forecasts — путь инфляции для линкеров («При покупке»); нет — 4%%")
    p.add_argument("--reviews-dir", default=None,
                   help="Portfolio/weekly-reviews/ (только чтение): рейтинг облигации из последнего обзора "
                        "облигаций. Нет флага — рядом с --plan.")
    p.add_argument("--plan", default=None,
                   help="Portfolio/plan.json: сверка плана с Numbers → snapshot.plan_check (этап 1 ухода от Numbers).")
    args = p.parse_args()
    if args.splits_file:
        from portfolio_returns import load_known_splits  # noqa: WPS433
        load_known_splits(args.splits_file)      # невалидный файл — исключение, сборка не идёт
    if args.cash_fact is not None and not (args.cash_fact >= 0 and args.cash_fact != float("inf")):
        sys.stderr.write(f"ERROR: --cash-fact: нужно неотрицательное число ₽, получено {args.cash_fact}\n")
        sys.exit(1)

    if args.cash_fact_iis is not None and not (args.cash_fact_iis >= 0 and args.cash_fact_iis != float("inf")):
        sys.stderr.write(f"ERROR: --cash-fact-iis: нужно неотрицательное число ₽, получено {args.cash_fact_iis}\n")
        sys.exit(1)

    portfolio    = _load(args.portfolio)
    returns      = _load(args.returns)
    per_security = _load(getattr(args, "per_security", None))
    quotes       = _load(args.quotes)
    # moex_quotes.py CLI выдаёт обёртку {source, profile, quotes:{ticker:…}, errors}.
    # assemble ожидает плоский {ticker: quote}. Разворачиваем, если это payload.
    if isinstance(quotes, dict) and isinstance(quotes.get("quotes"), dict):
        quotes = quotes["quotes"]
    prev_snap    = _load(args.prev_snapshot) if args.prev_snapshot else None

    if portfolio is None and returns is None:
        sys.stderr.write(
            "ERROR: нужен хотя бы один файл: --portfolio или --returns\n"
        )
        sys.exit(1)

    # Источники для переноса блока ИИС-3 (нет --iis-returns): файл --output, который
    # сейчас будет перезаписан (читаем ДО записи), prev-snapshot, затем соседи
    # portfolio-*.json по убыванию имени.
    carry_sources: list[dict] = []
    if not args.iis_returns:
        paths: list[Path] = []
        if args.output:
            paths.append(Path(args.output))
        if args.prev_snapshot:
            paths.append(Path(args.prev_snapshot))
        for d in ([Path(args.snapshots_dir)] if args.snapshots_dir else []) + (
                [Path(args.output).parent] if args.output else []):
            if d.is_dir():
                paths += sorted(d.glob("portfolio-*.json"), reverse=True)
        seen_paths: set[str] = set()
        for pth in paths:
            try:
                key = str(pth.resolve())
                if key in seen_paths or not pth.is_file():
                    continue
                seen_paths.add(key)
                carry_sources.append(json.loads(pth.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue

    snapshot = assemble(
        portfolio, returns, per_security, quotes,
        iis_carry_sources=carry_sources,
        trades_path=args.trades,
        balance_path=args.balance,
        prev_snapshot=prev_snap,
        sector_overrides_path=args.sector_overrides,
        rebaseline_cash=args.rebaseline_cash,
        recent_net_threshold_pct=args.recent_net_threshold_pct,
        recent_net_threshold_rub=args.recent_net_threshold_rub,
        iis_returns=_load(args.iis_returns) if args.iis_returns else None,
        as_of=args.as_of,
        holdings_from_trades=args.holdings_from_trades,
        plan_path=args.plan,
        plan_primary=args.plan_primary,
        cash_fact=args.cash_fact,
        cash_fact_iis=args.cash_fact_iis,
        types_path=args.types_cache,
        reviews_dir=args.reviews_dir,
        bond_locked_fetch=None if args.no_bond_locked else _fetch_schedule,
        forecasts_dir=args.forecasts_dir,
        per_security_closed=_load(args.per_security_closed) if args.per_security_closed else None,
    )

    out = json.dumps(snapshot, ensure_ascii=False, indent=2)

    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
        n_holdings  = len(snapshot.get("holdings") or [])
        n_flags     = len(snapshot.get("data_quality_flags") or [])
        xirr = (snapshot.get("returns") or {}).get("restricted", {}).get("xirr")
        xirr_str = f"{xirr * 100:.2f}%" if xirr is not None else "n/a"
        print(f"✓ {args.output}")
        print(f"  schema_version: 2.0 | holdings: {n_holdings} | "
              f"XIRR restricted: {xirr_str} | flags: {n_flags}")
    else:
        print(out)


if __name__ == "__main__":
    main()
