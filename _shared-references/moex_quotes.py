#!/usr/bin/env python3
"""
MOEX ISS quote fetcher — оптимизированный клиент для подгрузки котировок,
YTM и справочных данных по акциям, облигациям и БПИФ с Мосбиржи.

Оптимизации (в порядке убывания эффекта):

    1. Column filter (securities.columns=..., marketdata.columns=...)
       Сокращает размер ответа в 10–30 раз. Запрашиваем только поля,
       которые реально используются — профили minimal / weekly / full.
    2. gzip-компрессия (Accept-Encoding: gzip).
       Дополнительное сжатие x2.6, ускорение x1.8 на типичном ответе.
    3. JSON standard вместо XML.
       На 28% быстрее XML, числа приходят как числа (не строки),
       парсится stdlib json.
    4. Параллельные запросы по разным доскам через ThreadPoolExecutor.
       Для портфеля "акции + ОФЗ + корп + БПИФ" — один параллельный батч
       вместо 4 последовательных. ~3x ускорение на типичном портфеле.
    5. Пакетирование до 10 SECID на запрос (лимит MOEX).
    6. Опциональный kind_hint пропускает discovery (один запрос на тикер).

Бенчмарк (10 бумаг, marketdata): XML full 15 kB / 393 ms → JSON+cols+gzip 455 B / 215 ms.

CLI:
    python3 moex_quotes.py SBER GAZP LKOH
    python3 moex_quotes.py --fields minimal SBER       # только цена+статус
    python3 moex_quotes.py --fields weekly --from-portfolio /tmp/portfolio.json
    python3 moex_quotes.py --fields full SU26238RMFS4  # все детали облигации
    python3 moex_quotes.py --type bond --fields weekly RU000A105A95 SU26238RMFS4
    python3 moex_quotes.py --health

Python API:
    from moex_quotes import fetch_quotes, health_check

    quotes, errors = fetch_quotes(
        ["SBER", "SU26238RMFS4"],
        fields="weekly",   # minimal / weekly / full
        parallel=True,
    )

Зависимости: только stdlib.

Канон (с 2026-10-12): _shared-references/moex_quotes.py. Встраивается pack.sh в
scripts/ бандлов через `bundle_scripts: [moex_quotes.py]` — portfolio-data-loader
(portfolio_returns, iis_returns, Шаг 5) и ru-portfolio-advisor (iis_shortlist,
build_weekly_bond_stub, lot_size для gate_aware_sizing). Локальных копий в
skills/*/scripts/ не держать: до переноса копия advisor отстала от loader
(без listing_from, отделения yield-to-offer, CURRENCYID), а loader — без lot_size.
В репо импортёры ищут его в своей scripts/, затем здесь.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable

ISS_BASE = "https://iss.moex.com/iss"
DEFAULT_TIMEOUT = 15
MAX_BATCH = 10
USER_AGENT = "ru-portfolio-advisor/1.1 (+claude.ai skill)"

# Для бумаги с близкой офертой MOEX отдаёт YIELD как доходность-к-оферте: на коротком
# горизонте она раздувается до сотен % годовых (напр. цена 97.6→100 за 6 дней ≈ 414% год.).
# Такой YIELD — это yield-to-offer, а не YTM-к-погашению, и не должен попадать в ytm_pct
# (carry-базис). Выше этого порога при наличии оферты значение трактуем как yield-to-offer.
YIELD_TO_OFFER_SANITY_PCT = 60.0


# ============================================================================
# Профили полей (column filter). Каждый профиль — два списка:
# securities.* (статические поля выпуска) + marketdata.* (торговый срез).
# ============================================================================

# --- Акции и БПИФ/ETF (market=shares) ---------------------------------------

SHARE_STATIC_MINIMAL = ["SECID", "SHORTNAME", "PREVPRICE"]
SHARE_STATIC_WEEKLY = [
    "SECID", "BOARDID", "SHORTNAME", "ISIN", "LATNAME",
    "PREVPRICE", "PREVDATE", "LOTSIZE", "FACEVALUE", "CURRENCYID", "LISTLEVEL",
]
SHARE_STATIC_FULL = SHARE_STATIC_WEEKLY + ["ISSUESIZE", "SECTYPE", "PREVLEGALCLOSEPRICE"]

SHARE_MD_MINIMAL = ["SECID", "LAST", "TRADINGSTATUS", "SYSTIME"]
SHARE_MD_WEEKLY = [
    "SECID", "LAST", "LASTCHANGE", "LASTCHANGEPRCNT",
    "VALTODAY_RUR", "MARKETPRICE", "TRADINGSTATUS", "SYSTIME", "UPDATETIME",
]
SHARE_MD_FULL = SHARE_MD_WEEKLY + [
    "BID", "OFFER", "OPEN", "HIGH", "LOW", "WAPRICE",
    "ISSUECAPITALIZATION", "NUMTRADES", "VOLTODAY",
]

# --- Облигации (market=bonds) ------------------------------------------------
# Weekly-профиль специально оптимизирован под регулярный обзор:
# YTM, дюрация, оферта, цена, статус. Без лишних полей сделок.

BOND_STATIC_MINIMAL = ["SECID", "SHORTNAME", "MATDATE", "FACEUNIT"]
BOND_STATIC_WEEKLY = [
    "SECID", "BOARDID", "SHORTNAME", "ISIN", "LATNAME",
    "MATDATE", "OFFERDATE", "BUYBACKDATE", "FACEUNIT", "FACEVALUE",
    "COUPONVALUE", "COUPONPERCENT", "COUPONPERIOD", "NEXTCOUPON", "ACCRUEDINT",
    "PREVPRICE", "PREVDATE", "BONDTYPE", "LISTLEVEL",
    "CURRENCYID",  # валюта торгов: в ней номинирован ACCRUEDINT (у замещаек ≠ FACEUNIT)
]
BOND_STATIC_FULL = BOND_STATIC_WEEKLY + [
    "ISSUESIZEPLACED", "BONDSUBTYPE",
    "PREVLEGALCLOSEPRICE", "DATEYIELDFROMISSUER",
]

BOND_MD_MINIMAL = ["SECID", "LAST", "YIELD", "TRADINGSTATUS", "SYSTIME"]
BOND_MD_WEEKLY = [
    "SECID", "LAST", "YIELD", "YIELDTOOFFER", "DURATION",
    "LASTCHANGEPRCNT", "VALTODAY_RUR", "TRADINGSTATUS", "SYSTIME",
]
BOND_MD_FULL = BOND_MD_WEEKLY + [
    "YIELDATWAPRICE", "ZSPREAD", "BID", "OFFER", "WAPRICE",
    "LASTCHANGE", "NUMTRADES", "UPDATETIME",
]

FIELD_PROFILES = {
    "minimal": {
        "shares": (SHARE_STATIC_MINIMAL, SHARE_MD_MINIMAL),
        "bonds":  (BOND_STATIC_MINIMAL, BOND_MD_MINIMAL),
    },
    "weekly": {
        "shares": (SHARE_STATIC_WEEKLY, SHARE_MD_WEEKLY),
        "bonds":  (BOND_STATIC_WEEKLY, BOND_MD_WEEKLY),
    },
    "full": {
        "shares": (SHARE_STATIC_FULL, SHARE_MD_FULL),
        "bonds":  (BOND_STATIC_FULL, BOND_MD_FULL),
    },
}

BOARD_BY_TYPE = {
    "share":       ("stock", "shares", "TQBR"),
    "bond":        ("stock", "bonds",  "TQCB"),
    "ofz":         ("stock", "bonds",  "TQOB"),
    "etf":         ("stock", "shares", "TQTF"),
    "closed_fund": ("stock", "shares", "TQIF"),
}


# ============================================================================
# Выходная схема
# ============================================================================

@dataclass
class Quote:
    """Нормализованный срез по одной бумаге. None-поля = либо неприменимы,
    либо не запрошены в текущем профиле. fields_missing сигнализирует
    критические пустоты (cue для LLM идти на fallback)."""
    secid: str
    kind: str                       # share / bond / etf / unknown
    board: str | None = None
    short_name: str | None = None
    isin: str | None = None
    currency: str | None = None     # SUR / USD / EUR / CNY из FACEUNIT
    settle_currency: str | None = None  # CURRENCYID — валюта торгов/расчётов; в ней ACCRUEDINT

    last: float | None = None       # для акций ₽, для облигаций % номинала
    prev_close: float | None = None
    change_pct: float | None = None
    bid: float | None = None
    offer: float | None = None
    volume_rub_today: float | None = None

    # Облигации
    ytm_pct: float | None = None
    ytm_to_offer_pct: float | None = None
    duration_days: int | None = None
    z_spread_bps: float | None = None
    accrued_interest: float | None = None
    coupon_value: float | None = None
    coupon_pct: float | None = None
    coupon_period_days: int | None = None   # период купона в днях → частота = 365/период
    next_coupon_date: str | None = None
    maturity_date: str | None = None
    offer_date: str | None = None
    face_value: float | None = None
    bond_type: str | None = None

    # Акции
    market_cap_rub: float | None = None
    list_level: int | None = None
    lot_size: int | None = None       # LOTSIZE — лот для сайзинга докупки (gate_aware_sizing)
    listing_from: str | None = None   # первый торговый день на MOEX (IPO-гейт advisor)

    trading_status: str | None = None
    timestamp: str | None = None
    source: str = "moex_iss"
    profile: str = "weekly"
    fields_missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v not in (None, [], "")}


# ============================================================================
# HTTP с gzip
# ============================================================================

def _get_json(url: str, timeout: int = DEFAULT_TIMEOUT, retries: int = 2) -> dict[str, Any]:
    """GET c gzip и ретраем. Парсит JSON и возвращает dict."""
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept-Encoding": "gzip",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError,
                TimeoutError, OSError, json.JSONDecodeError) as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
            continue
    raise IOError(f"MOEX ISS request failed after {retries + 1} attempts: {url} ({last_exc})")


def _block_to_dict_by_secid(block: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """JSON-блок MOEX {columns:[...], data:[[...]]} → {secid: {col:val}}.
    Case-insensitive: discovery endpoint возвращает 'secid', а
    /engines/.../boards/.../securities.json — 'SECID'."""
    if not block:
        return {}
    cols = block.get("columns") or []
    # Ищем индекс SECID любым регистром
    idx = None
    for i, c in enumerate(cols):
        if c.upper() == "SECID":
            idx = i
            break
    if idx is None:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in block.get("data") or []:
        if len(row) <= idx or not row[idx]:
            continue
        out[str(row[idx])] = dict(zip(cols, row))
    return out


# ============================================================================
# Discovery
# ============================================================================

def discover_board(secid_or_isin: str, timeout: int = DEFAULT_TIMEOUT) -> dict[str, str] | None:
    """
    Через /iss/securities.json?q=... находим актуальный (is_traded=1)
    экземпляр. Column filter — ответ ~300 B.

    Returns: {secid, engine, market, boardid} или None.
    """
    quoted = urllib.parse.quote(secid_or_isin)
    url = (
        f"{ISS_BASE}/securities.json"
        f"?q={quoted}&iss.meta=off&limit=20"
        f"&securities.columns=secid,isin,is_traded,group,primary_boardid"
    )
    try:
        data = _get_json(url, timeout=timeout)
    except IOError:
        return None

    rows = _block_to_dict_by_secid(data.get("securities", {}))
    if not rows:
        return None

    traded = [
        r for r in rows.values()
        if r.get("is_traded") == 1 and str(r.get("group") or "").startswith("stock_")
        and r.get("primary_boardid")
    ]
    if not traded:
        return None

    exact = [r for r in traded if str(r.get("secid", "")).upper() == secid_or_isin.upper()]
    r = exact[0] if exact else traded[0]

    market = "bonds" if "bond" in str(r.get("group", "")) else "shares"
    return {
        "secid": str(r.get("secid") or secid_or_isin),
        "engine": "stock",
        "market": market,
        "boardid": str(r.get("primary_boardid", "")),
    }


# ============================================================================
# Пакетный запрос по одной доске
# ============================================================================

def _fetch_board_batch(
    engine: str,
    market: str,
    boardid: str,
    secids: list[str],
    profile: str,
    timeout: int = DEFAULT_TIMEOUT,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    if not secids:
        return {}, {}
    if len(secids) > MAX_BATCH:
        raise ValueError(f"Batch size {len(secids)} > {MAX_BATCH}")

    market_key = "bonds" if market == "bonds" else "shares"
    sec_cols, md_cols = FIELD_PROFILES[profile][market_key]

    qs = urllib.parse.urlencode({
        "securities": ",".join(secids),
        "iss.meta": "off",
        "iss.only": "securities,marketdata",
        "securities.columns": ",".join(sec_cols),
        "marketdata.columns": ",".join(md_cols),
    })
    url = (
        f"{ISS_BASE}/engines/{engine}/markets/{market}"
        f"/boards/{boardid}/securities.json?{qs}"
    )
    data = _get_json(url, timeout=timeout)
    sec_by_id = _block_to_dict_by_secid(data.get("securities", {}))
    md_by_id = _block_to_dict_by_secid(data.get("marketdata", {}))
    return sec_by_id, md_by_id


# ============================================================================
# Нормализация в Quote
# ============================================================================

def _f(x: Any) -> float | None:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _i(x: Any) -> int | None:
    v = _f(x)
    return int(v) if v is not None else None


def _clean_date(s: Any) -> str | None:
    if not s or s == "0000-00-00":
        return None
    return str(s)


def _normalize(
    secid: str,
    market: str,
    sec: dict[str, Any],
    md: dict[str, Any],
    profile: str,
) -> Quote:
    is_bond = market == "bonds"
    kind = "bond" if is_bond else ("etf" if sec.get("SECTYPE") == "E" else "share")

    change_pct = _f(md.get("LASTCHANGEPRCNT"))
    if change_pct is None:
        last, prev = _f(md.get("LAST")), _f(sec.get("PREVPRICE"))
        if last and prev and prev > 0:
            change_pct = round((last - prev) / prev * 100, 4)

    q = Quote(
        secid=secid,
        kind=kind,
        board=sec.get("BOARDID") or md.get("BOARDID"),
        short_name=sec.get("SHORTNAME"),
        isin=sec.get("ISIN"),
        currency=sec.get("FACEUNIT") or sec.get("CURRENCYID"),
        settle_currency=sec.get("CURRENCYID"),
        last=_f(md.get("LAST")) or _f(md.get("MARKETPRICE")),
        prev_close=_f(sec.get("PREVPRICE")) or _f(sec.get("PREVLEGALCLOSEPRICE")),
        change_pct=change_pct,
        bid=_f(md.get("BID")),
        offer=_f(md.get("OFFER")),
        volume_rub_today=_f(md.get("VALTODAY_RUR")),
        trading_status=md.get("TRADINGSTATUS"),
        timestamp=md.get("SYSTIME") or md.get("UPDATETIME"),
        profile=profile,
    )

    if is_bond:
        q.offer_date = _clean_date(sec.get("OFFERDATE")) or _clean_date(sec.get("BUYBACKDATE"))
        q.ytm_to_offer_pct = _f(md.get("YIELDTOOFFER"))
        raw_yield = _f(md.get("YIELD")) or _f(md.get("YIELDATWAPRICE"))
        # При наличии оферты MOEX YIELD = yield-to-offer; неправдоподобно высокое значение
        # → это доходность-к-оферте, а не YTM-к-погашению. Уводим её в ytm_to_offer_pct,
        # ytm_pct оставляем чистым (None — YTM-к-погашению часто недоступен для бумаг
        # «фикс с неизвестным купоном»). Downstream carry берёт coupon_pct.
        if (q.offer_date is not None and raw_yield is not None
                and raw_yield > YIELD_TO_OFFER_SANITY_PCT):
            if q.ytm_to_offer_pct is None:
                q.ytm_to_offer_pct = raw_yield
            q.ytm_pct = None
        else:
            q.ytm_pct = raw_yield
        q.duration_days = _i(md.get("DURATION"))
        z = _f(md.get("ZSPREAD"))
        q.z_spread_bps = round(z * 100, 2) if z is not None else None
        q.accrued_interest = _f(sec.get("ACCRUEDINT"))
        q.coupon_value = _f(sec.get("COUPONVALUE"))
        q.coupon_pct = _f(sec.get("COUPONPERCENT"))
        q.coupon_period_days = _i(sec.get("COUPONPERIOD"))
        q.next_coupon_date = _clean_date(sec.get("NEXTCOUPON"))
        q.maturity_date = _clean_date(sec.get("MATDATE"))
        q.face_value = _f(sec.get("FACEVALUE"))
        q.bond_type = sec.get("BONDTYPE")
    else:
        q.market_cap_rub = _f(md.get("ISSUECAPITALIZATION"))
        q.list_level = _i(sec.get("LISTLEVEL"))
        q.lot_size = _i(sec.get("LOTSIZE"))

    # Критичные поля по профилю — их отсутствие значимо
    critical = ["last", "prev_close"]
    if is_bond and profile in ("weekly", "full"):
        critical += ["ytm_pct"]
        if profile == "full":
            critical += ["duration_days"]
    q.fields_missing = [f_ for f_ in critical if getattr(q, f_) in (None, 0)]
    return q


# ============================================================================
# Главная точка входа
# ============================================================================

def fetch_quotes(
    secids: Iterable[str],
    fields: str = "weekly",
    kind_hint: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    parallel: bool = True,
    max_workers: int = 6,
) -> tuple[dict[str, Quote], dict[str, str]]:
    """
    Пакетный запрос к MOEX ISS с полным набором оптимизаций.

    Args:
        secids: тикеры или ISIN. Dedupe-нутся автоматически.
        fields: профиль — 'minimal' / 'weekly' (default) / 'full'.
        kind_hint: 'share'/'bond'/'ofz'/'etf'/'closed_fund' — пропуск discovery.
        parallel: параллельные HTTP по разным доскам.
        max_workers: потолок потоков.

    Returns:
        (quotes, errors) — оба keyed by исходный SECID/ISIN.
    """
    if fields not in FIELD_PROFILES:
        raise ValueError(f"fields must be one of {list(FIELD_PROFILES)}")

    secids_clean = list(dict.fromkeys(
        s.strip().upper() for s in secids if s and s.strip()
    ))
    if not secids_clean:
        return {}, {}

    quotes: dict[str, Quote] = {}
    errors: dict[str, str] = {}
    id_resolved: dict[str, str] = {}
    groups: dict[tuple[str, str, str], list[str]] = {}

    # Шаг 1. Группировка по доскам
    if kind_hint and kind_hint in BOARD_BY_TYPE:
        engine, market, boardid = BOARD_BY_TYPE[kind_hint]
        groups[(engine, market, boardid)] = list(secids_clean)
        for s in secids_clean:
            id_resolved[s] = s
    else:
        def _disc(s: str) -> tuple[str, dict[str, str] | None]:
            return s, discover_board(s, timeout=timeout)

        if parallel and len(secids_clean) > 1:
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                for s, info in ex.map(_disc, secids_clean):
                    if not info or not info["boardid"]:
                        errors[s] = "not_found_or_not_traded"
                        continue
                    key = (info["engine"], info["market"], info["boardid"])
                    groups.setdefault(key, []).append(info["secid"])
                    id_resolved[s] = info["secid"]
        else:
            for s in secids_clean:
                info = discover_board(s, timeout=timeout)
                if not info or not info["boardid"]:
                    errors[s] = "not_found_or_not_traded"
                    continue
                key = (info["engine"], info["market"], info["boardid"])
                groups.setdefault(key, []).append(info["secid"])
                id_resolved[s] = info["secid"]

    # Шаг 2. Пакетные запросы (параллельно)
    def _fetch_chunk(args: tuple[str, str, str, list[str]]) -> tuple[dict, dict, list[str]]:
        engine_, market_, boardid_, chunk_ = args
        try:
            sec, md = _fetch_board_batch(
                engine_, market_, boardid_, chunk_, fields, timeout=timeout
            )
            return sec, md, chunk_
        except IOError as exc:
            return {"__error__": str(exc)}, {}, chunk_

    tasks: list[tuple[str, str, str, list[str]]] = []
    for (engine, market, boardid), batch_ids in groups.items():
        for i in range(0, len(batch_ids), MAX_BATCH):
            tasks.append((engine, market, boardid, batch_ids[i:i + MAX_BATCH]))

    results: list[tuple[dict, dict, list[str], str]] = []
    if parallel and len(tasks) > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(_fetch_chunk, t): t for t in tasks}
            for fut in as_completed(futures):
                sec, md, chunk = fut.result()
                _, market_, _, _ = futures[fut]
                results.append((sec, md, chunk, market_))
    else:
        for t in tasks:
            sec, md, chunk = _fetch_chunk(t)
            results.append((sec, md, chunk, t[1]))

    for sec_by_id, md_by_id, chunk, market in results:
        if "__error__" in sec_by_id:
            for cid in chunk:
                errors[cid] = f"http_error: {sec_by_id['__error__']}"
            continue
        for cid in chunk:
            sec = sec_by_id.get(cid, {})
            md = md_by_id.get(cid, {})
            if not sec and not md:
                errors[cid] = "not_in_response"
                continue
            quotes[cid] = _normalize(cid, market, sec, md, fields)

    # Шаг 2a. Облигация, чья основная доска торгуется не в рублях (TQOY и т. п., CURRENCYID
    # CNY/USD...): ACCRUEDINT там в валюте торгов, а не в рублях. Цена и НКД берутся вместе
    # с рублёвой доски (TQOB, затем TQCB, CURRENCYID SUR) — иначе НКД теряется, стоимость занижена.
    def _is_ruble(cur: str | None) -> bool:
        return cur in ("SUR", "RUB")

    def _rebase_to_ruble_board(cid: str) -> None:
        for board in RUBLE_BOND_BOARDS:
            try:
                sec_b, md_b = _fetch_board_batch("stock", "bonds", board, [cid], fields, timeout=timeout)
            except IOError:
                continue
            sec_r, md_r = sec_b.get(cid, {}), md_b.get(cid, {})
            if not sec_r or not _is_ruble(sec_r.get("CURRENCYID")):
                continue
            q2 = _normalize(cid, "bonds", sec_r, md_r, fields)
            if q2.last or q2.prev_close:
                quotes[cid] = q2
                return

    for cid in [c for c, q in quotes.items()
                if q.kind == "bond" and q.settle_currency and not _is_ruble(q.settle_currency)]:
        _rebase_to_ruble_board(cid)

    # Шаг 2b. Дата листинга для акций (IPO-гейт advisor): первый торговый
    # день на MOEX из /history/.../{secid}/dates.json. Best-effort — сбой не
    # трогает котировку, поле остаётся None. Только weekly/full (не minimal).
    if fields in ("weekly", "full"):
        share_ids = [sid for sid, q in quotes.items() if q.kind == "share"]

        def _listing(sid: str) -> tuple[str, str | None]:
            url = (f"{ISS_BASE}/history/engines/stock/markets/shares/"
                   f"securities/{sid}/dates.json?iss.meta=off")
            try:
                data = _get_json(url, timeout=timeout, retries=1)
                rows = data.get("dates", {}).get("data") or []
                return sid, (rows[0][0] if rows and rows[0] else None)
            except IOError:
                return sid, None

        if share_ids:
            if parallel and len(share_ids) > 1:
                with ThreadPoolExecutor(max_workers=max_workers) as ex:
                    for sid, dt_from in ex.map(_listing, share_ids):
                        quotes[sid].listing_from = dt_from
            else:
                for sid in share_ids:
                    _, dt_from = _listing(sid)
                    quotes[sid].listing_from = dt_from

    # Шаг 3. Маппинг ISIN → SECID
    out: dict[str, Quote] = {}
    for original, canonical in id_resolved.items():
        if canonical in quotes:
            out[original] = quotes[canonical]
    for canonical, q in quotes.items():
        out.setdefault(canonical, q)

    return out, errors


# ============================================================================
# Health-check
# ============================================================================

def health_check(timeout: int = 5) -> dict[str, Any]:
    """Быстрая проверка ISS. Минимальный endpoint, gzip, ~200 B."""
    url = f"{ISS_BASE}/index.json?iss.meta=off&iss.only=engines"
    t0 = time.perf_counter()
    try:
        _get_json(url, timeout=timeout, retries=0)
        return {"ok": True, "latency_ms": round((time.perf_counter() - t0) * 1000, 1), "error": None}
    except IOError as exc:
        return {"ok": False, "latency_ms": None, "error": str(exc)}


# ============================================================================
# Интеграция с парсером портфеля
# ============================================================================

# Бумаги, чей MOEX secid не извлекается из тикера выгрузки (ЗПИФ торгуются по
# ISIN; в balance-файле могут лежать в «Другое» без колонки «Тикер»). Запрашиваем
# по ISIN — get_quotes вернёт котировку и под ISIN, и под резолвнутым secid, так
# что assemble найдёт её по тикеру холдинга. Ключ — нормализованное имя (вкл.
# опечатки в balance-файле), значение — ISIN.
NAME_ISIN_OVERRIDES: dict[str, str] = {
    "рентал про": "RU000A108157",   # ЗПИФ «Рентал ПРО» (ЦОД)
    "ренат про": "RU000A108157",    # частая опечатка в «Общий баланс.numbers»
}


def _norm_name(s: str) -> str:
    return " ".join(str(s).lower().split())


def _secids_from_snapshot_v2(data: dict) -> dict[str, list[str]]:
    """Снапшот v2 (`holdings`): активные позиции, blocked — мимо (у них нет цены MOEX).
    Акции и фонды — по тикеру, облигации — по ISIN (тикер облигации в снапшоте и есть ISIN)."""
    shares: list[str] = []
    bonds: list[str] = []
    other: list[str] = []
    for h in data.get("holdings", []):
        if h.get("status") == "blocked":
            continue
        kind = h.get("asset_type")
        if kind == "bond":
            secid = h.get("isin") or h.get("ticker")
            if secid:
                bonds.append(secid)
        elif kind == "stock":
            if h.get("ticker"):
                shares.append(h["ticker"])
        elif h.get("ticker") or h.get("isin"):
            other.append(h.get("ticker") or h["isin"])
    return {"shares": shares, "bonds": bonds, "other": other}


def secids_from_portfolio(portfolio_json_path: str) -> dict[str, list[str]]:
    """Список бумаг для запроса. Понимает два формата: снапшот v2 (`holdings`, его читает
    советник) и промежуточный portfolio.json загрузчика (`stocks`/`bonds`/`other_positions`).
    До 2026-10-20 понимал только второй: на снапшоте получался пустой список, и
    `--from-portfolio` выходил с кодом 2 в каждом обзоре (RPA-22)."""
    with open(portfolio_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "holdings" in data:
        return _secids_from_snapshot_v2(data)

    shares = [
        s["Тикер"] for s in data.get("stocks", [])
        if isinstance(s.get("Стоимость"), (int, float)) and s["Стоимость"] > 0
        and s.get("Тикер") and s["Тикер"] != "Итог"
    ]
    bonds = [
        b["Тикер"] for b in data.get("bonds", [])
        if isinstance(b.get("Текущая стоимость"), (int, float))
        and b["Текущая стоимость"] > 0
        and b.get("Тикер") and b["Тикер"] != "Итог"
    ]
    other = []
    for o in data.get("other_positions", []):
        for key in ("Тикер", "Название", "Ticker", "Бумага"):
            if o.get(key):
                raw = str(o[key]).strip()
                # ЗПИФ без распознаваемого secid → запрашиваем по ISIN
                other.append(NAME_ISIN_OVERRIDES.get(_norm_name(raw), raw.split()[0]))
                break
    return {"shares": shares, "bonds": bonds, "other": other}


# ============================================================================
# Целые доски → quotes@1 (живые цены для вьюера и советника, план live-prices-plan.md §2.1)
# ============================================================================

# Один запрос на доску: цена + лот всех бумаг доски, без состава портфеля в запросе.
QUOTES_BOARD_COLUMNS = (
    "iss.meta=off&iss.only=securities,marketdata"
    "&securities.columns=SECID,LOTSIZE,PREVPRICE,PREVDATE"
    "&marketdata.columns=SECID,LAST,MARKETPRICE,LCURRENTPRICE,UPDATETIME,SYSTIME,TRADINGSTATUS"
)
# Облигационные доски: к цене добавляются ISIN (холдинги ОФЗ ключатся ISIN, у ISS ключ — SECID),
# НКД, номинал и валюта номинала — для живой оценки позиции (цена в % номинала + НКД).
BOND_BOARDS = {"TQOB": "bonds", "TQCB": "bonds"}
RUBLE_BOND_BOARDS = ("TQOB", "TQCB")   # доски с расчётами в рублях: ACCRUEDINT в ₽ даже у валютных номиналов
QUOTES_BOND_COLUMNS = (
    "iss.meta=off&iss.only=securities,marketdata"
    "&securities.columns=SECID,ISIN,LOTSIZE,PREVPRICE,PREVDATE,ACCRUEDINT,FACEVALUE,FACEUNIT,CURRENCYID"
    "&marketdata.columns=SECID,LAST,MARKETPRICE,LCURRENTPRICE,UPDATETIME,SYSTIME,TRADINGSTATUS,YIELD,YIELDTOOFFER,DURATION"
)
QUOTES_DELAYED_MIN = 15  # бесплатный ISS отдаёт рынок с задержкой 15 мин


def board_to_quotes_items(board: str, iss_json: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Ответ ISS по доске → {secid: item quotes@1}. Чистая функция, без сети.

    Правило цены — то же, что у _normalize (last = LAST или MARKETPRICE; нулевое значение
    = нет цены) + запасной PREVPRICE: LAST → price_kind "last"; MARKETPRICE → "market";
    PREVPRICE → "prev_close". ts: SYSTIME для last/market, иначе PREVDATE. Бумага без
    цены в items не попадает. Доски облигаций (BOND_BOARDS) несут ещё isin, accrued_int
    (НКД одной бумаги, в рублях — валюта торгов SUR, не валюта номинала), face_value (текущий номинал), face_unit
    (SUR/RUB — рубли; прочее — валютные), currency_id (валюта торгов: в ней НКД; SUR — рубли);
    у акций этих полей нет. При цене last/market — ещё yield_pct (YIELD биржи, % годовых), yield_offer_pct
    (YIELDTOOFFER), duration_days (DURATION, дни); null/0 — нет данных.
    """
    sec_by = _block_to_dict_by_secid(iss_json.get("securities") or {})
    md_by = _block_to_dict_by_secid(iss_json.get("marketdata") or {})
    items: dict[str, dict[str, Any]] = {}
    for secid, sec in sec_by.items():
        md = md_by.get(secid) or {}
        prev = _f(sec.get("PREVPRICE")) or None
        last, market = _f(md.get("LAST")) or None, _f(md.get("MARKETPRICE")) or None
        if last is not None:
            price, kind = last, "last"
        elif market is not None:
            price, kind = market, "market"
        elif prev is not None:
            price, kind = prev, "prev_close"
        else:
            continue
        ts = _clean_date(sec.get("PREVDATE"))
        if kind != "prev_close":
            ts = md.get("SYSTIME") or ts
        items[secid] = {
            "price": price, "price_kind": kind, "lot_size": _i(sec.get("LOTSIZE")),
            "board": board, "ts": ts, "prev_close": prev,
        }
        if board in BOND_BOARDS:
            items[secid].update({
                "isin": sec.get("ISIN") or None, "accrued_int": _f(sec.get("ACCRUEDINT")),
                "face_value": _f(sec.get("FACEVALUE")) or None, "face_unit": sec.get("FACEUNIT") or None,
                "currency_id": sec.get("CURRENCYID") or None,
            })
            if kind != "prev_close":   # доходность/дюрация к цене того же момента; у вчерашней цены — устаревшие
                y, yo, dur = _f(md.get("YIELD")) or None, _f(md.get("YIELDTOOFFER")) or None, _f(md.get("DURATION")) or None
                items[secid].update({"yield_pct": y, "yield_offer_pct": yo,
                                     "duration_days": int(dur) if dur else None})
    return items


CBR_DAILY_URL = "https://www.cbr.ru/scripts/XML_daily.asp"


def cbr_xml_to_fx(xml_text: str, currencies: Iterable[str] | None = None) -> dict[str, Any] | None:
    """XML_daily ЦБ → {"USD": руб/ед, "KZT": …, "date": "YYYY-MM-DD"} или None (нет даты / ни одной валюты).

    Курс = Value / Nominal (запятая десятичная; KZT — за 100). currencies=None — все валюты ответа,
    иначе только перечисленные (не найденных у ЦБ в результате нет). Чистая функция; зеркало —
    tools/hosting/api/server.py::cbr_xml_to_fx (блок fx в quotes@1: курс ЦБ для живой оценки валютных облигаций).
    """
    import re
    m = re.search(r'<ValCurs[^>]*\bDate="(\d{2})\.(\d{2})\.(\d{4})"', xml_text or "")
    if not m:
        return None
    want = None if currencies is None else set(currencies)
    out: dict[str, Any] = {}
    for v in re.finditer(r"<CharCode>([A-Z]{3})</CharCode>\s*<Nominal>(\d+)</Nominal>.*?<Value>([\d,\.]+)</Value>",
                         xml_text, re.S):
        code = v.group(1)
        if want is not None and code not in want:
            continue
        rate = float(v.group(3).replace(",", ".")) / int(v.group(2))
        if rate > 0:
            out[code] = rate
    if not out:
        return None
    out["date"] = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return out


def fetch_fx(currencies: Iterable[str] | None = None, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any] | None:
    """Курсы ЦБ на сегодня только по currencies; сбой сети → None (облигации остаются по снапшоту)."""
    try:
        req = urllib.request.Request(CBR_DAILY_URL, headers={"User-Agent": "moex_quotes/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return cbr_xml_to_fx(r.read().decode("windows-1251", errors="replace"), currencies)
    except Exception:
        return None


def fetch_boards(boards: Iterable[str] = ("TQBR",), timeout: int = DEFAULT_TIMEOUT,
                 fx: Iterable[str] | None = None) -> dict[str, Any]:
    """Живые цены целых досок → quotes@1 (один запрос на доску). Ошибка доски — IOError."""
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    items: dict[str, dict[str, Any]] = {}
    meta: dict[str, Any] = {}
    for b in boards:
        market = BOND_BOARDS.get(b, "shares")
        cols = QUOTES_BOND_COLUMNS if b in BOND_BOARDS else QUOTES_BOARD_COLUMNS
        url = f"{ISS_BASE}/engines/stock/markets/{market}/boards/{b}/securities.json?{cols}"
        data = _get_json(url, timeout=timeout)
        items.update(board_to_quotes_items(b, data))
        meta[b] = {"fetched_at": now, "stale": False}
    out = {
        "schema": "quotes@1", "fetched_at": now, "source": "moex_iss",
        "delayed_min": QUOTES_DELAYED_MIN, "stale": False, "boards": meta, "items": items,
    }
    if fx:  # без fx блока нет; только запрошенные валюты
        blk = fetch_fx(list(fx), timeout=timeout)
        if blk:
            out["fx"] = blk
    return out


# ============================================================================
# CLI
# ============================================================================

def _main() -> int:
    ap = argparse.ArgumentParser(
        description="MOEX ISS quote fetcher (JSON+gzip+col-filter+parallel)"
    )
    ap.add_argument("secids", nargs="*", help="Тикеры или ISIN")
    ap.add_argument("--fields", choices=list(FIELD_PROFILES),
                    default="weekly",
                    help="Профиль полей: minimal / weekly (default) / full")
    ap.add_argument("--type", choices=list(BOARD_BY_TYPE),
                    help="Подсказка типа — пропускает discovery")
    ap.add_argument("--from-portfolio", metavar="PATH",
                    help="Прочитать SECID из выхода parse_portfolio.py")
    ap.add_argument("--isin", nargs="+", help="Явно указать ISIN-ы")
    ap.add_argument("--no-parallel", action="store_true",
                    help="Отключить параллельные HTTP-запросы")
    ap.add_argument("--health", action="store_true", help="Только health-check")
    ap.add_argument("--json", action="store_true", help="JSON-выдача")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    ap.add_argument("--bench", action="store_true",
                    help="Показать тайминг в stderr")
    ap.add_argument("--emit", choices=["quotes@1"],
                    help="Цены целых досок в формате quotes@1 (JSON в stdout); доски — --boards")
    ap.add_argument("--fx", default="",
                    help="Валюты блока fx для --emit через запятую (USD,EUR,KZT); пусто — без блока")
    ap.add_argument("--boards", default="TQBR",
                    help="Доски для --emit через запятую (по умолчанию TQBR)")
    args = ap.parse_args()

    if args.emit:
        try:
            q1 = fetch_boards([b.strip() for b in args.boards.split(",") if b.strip()], timeout=args.timeout,
                             fx=[c.strip().upper() for c in args.fx.split(",") if c.strip()] or None)
        except IOError as exc:
            print(f"Ошибка: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(q1, ensure_ascii=False, indent=2))
        return 0

    if args.health:
        print(json.dumps(health_check(timeout=args.timeout), ensure_ascii=False, indent=2))
        return 0

    secids: list[str] = list(args.secids)
    if args.isin:
        secids.extend(args.isin)
    if args.from_portfolio:
        grp = secids_from_portfolio(args.from_portfolio)
        secids.extend(grp["shares"])
        secids.extend(grp["bonds"])
        secids.extend(grp["other"])

    secids = list(dict.fromkeys(secids))
    if not secids:
        ap.print_help()
        return 2

    t0 = time.perf_counter()
    quotes, errors = fetch_quotes(
        secids,
        fields=args.fields,
        kind_hint=args.type,
        timeout=args.timeout,
        parallel=not args.no_parallel,
    )
    elapsed = (time.perf_counter() - t0) * 1000

    if args.bench:
        print(
            f"# {len(secids)} SECID, profile={args.fields}, "
            f"parallel={not args.no_parallel}, elapsed={elapsed:.0f} ms, "
            f"ok={len(quotes)} err={len(errors)}",
            file=sys.stderr,
        )

    payload = {
        "source": "moex_iss",
        "profile": args.fields,
        "fetched_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_ms": round(elapsed, 1),
        "count_ok": len(quotes),
        "count_err": len(errors),
        "quotes": {k: q.to_dict() for k, q in quotes.items()},
        "errors": errors,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        for sec, q in quotes.items():
            miss = f" MISSING={q.fields_missing}" if q.fields_missing else ""
            if q.kind == "bond":
                print(
                    f"{sec:20}  {q.short_name or '':26}  "
                    f"price={q.last}%  YTM={q.ytm_pct}%  dur={q.duration_days}d  "
                    f"{q.currency}  {q.timestamp}{miss}"
                )
            else:
                print(
                    f"{sec:20}  {q.short_name or '':26}  "
                    f"last={q.last}  Δ={q.change_pct}%  vol={q.volume_rub_today}  "
                    f"{q.timestamp}{miss}"
                )
        for sec, err in errors.items():
            print(f"[ERROR] {sec}: {err}", file=sys.stderr)

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(_main())
