#!/usr/bin/env python3
"""Загрузчик дневных рядов рынка (MOEX ISS / ЦБ РФ) с локальным кэшем.

Назначение — теневые базы B0–B2 плана AIR-1
(docs/investment/portfolio/air-1-decision-journal-plan.md §2). Скрипт ТОЛЬКО загружает
и кэширует ряды; математики баз здесь нет. Дивиденды не грузятся (ISS-эндпоинт
/securities/{t}/dividends блока dividends не отдаёт) — они приходят из выгрузки сделок.

Виды рядов (kind):
  index       индекс MOEX, CLOSE в пунктах (MCFTR, RGBITR, RUCBTRNS, RUCNYTR);
              валюта ряда (CURRENCYID, у RUCNYTR — CNY) сохраняется в метаданных
  rate_index  RUSFAR: CLOSE — это СТАВКА, % годовых (unit="pct_annual"), не индекс доходности
  share       акция на TQBR, CLOSE в руб.
  currency    валютная пара на CETS (GLDRUB_TOM), CLOSE в руб. за грамм
  key_rate    ключевая ставка ЦБ, % годовых (через portfolio_returns.fetch_key_rate_history)
  fx_cbr      курс ЦБ, руб. за 1 ед. валюты (USD, CNY, EUR; через кэш портфельного лоадера)

Кэш: ~/.cache/claude-skills/market-series/{kind}__{secid}.json (не Synology и не /tmp).
Инкрементальность: запрос внутри покрытого диапазона сеть не трогает; иначе догружаются
только недостающие хвосты, при этом последние 7 дней до covered_to перезапрашиваются
(ISS правит свежие закрытия). Слияние по дате — новое значение побеждает.
Сбой сети не роняет вызов: возвращается кэш (если есть) + флаг «сеть: …».

CLI:
  python3 market_series.py --series index:MCFTR,rate_index:RUSFAR,fx_cbr:USD \\
      --from 2026-05-01 --to 2026-10-07 [--cache-dir DIR] [--offline]
Код выхода: 0 — все ряды непустые, 2 — какой-то ряд пуст.

Только stdlib.
"""
from __future__ import annotations

import argparse
import bisect
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from portfolio_returns import (  # noqa: E402
    _ssl_context, fetch_key_rate_history, load_cbr_cache, ensure_cbr_rates,
)

# PDL_MARKET_SERIES_CACHE — как PDL_CBR_CACHE в portfolio_returns (пакет прогона build_snapshot.py).
DEFAULT_CACHE_DIR = Path(os.environ.get("PDL_MARKET_SERIES_CACHE")
                         or Path.home() / ".cache" / "claude-skills" / "market-series")
REFRESH_DAYS = 7          # хвост до covered_to, который всегда перезапрашивается
ISS_PAGE = 100            # размер страницы ISS history

# kind → (ISS-путь history без .json | None, единица, валюта по умолчанию, источник)
KINDS: dict[str, dict] = {
    "index": {"path": "engines/stock/markets/index/securities/{secid}",
              "unit": "points", "currency": None, "source": "moex_iss", "cols": True},
    "rate_index": {"path": "engines/stock/markets/index/securities/{secid}",
                   "unit": "pct_annual", "currency": None, "source": "moex_iss", "cols": True},
    "share": {"path": "engines/stock/markets/shares/boards/TQBR/securities/{secid}",
              "unit": "rub", "currency": "RUB", "source": "moex_iss", "cols": False},
    "currency": {"path": "engines/currency/markets/selt/boards/CETS/securities/{secid}",
                 "unit": "rub", "currency": "RUB", "source": "moex_iss", "cols": False},
    "key_rate": {"path": None, "unit": "pct_annual", "currency": None,
                 "source": "cbr", "cols": False},
    "fx_cbr": {"path": None, "unit": "rub_per_unit", "currency": "RUB",
               "source": "cbr", "cols": False},
    # облигация (secid = ISIN): «грязная» цена одной бумаги в валюте номинала = CLOSE%·FACEVALUE + НКД;
    # доска — основная из /securities/{isin}.json (TQOB/TQCB/TQIR/TQOD…)
    "bond": {"path": None, "unit": "dirty_per_bond", "currency": None,
             "source": "moex_iss", "cols": False},
    # выплаты по облигации на одну бумагу (купоны + амортизации) по дате выплаты, из bondization
    "bond_cf": {"path": None, "unit": "cash_per_bond", "currency": None,
                "source": "moex_iss", "cols": False},
}


@dataclass
class Series:
    kind: str
    secid: str
    unit: str
    currency: str | None
    points: list[tuple[str, float]] = field(default_factory=list)  # (iso, значение), по возрастанию
    source: str = "moex_iss"                                       # "moex_iss" | "cbr"
    fetched_at: str | None = None
    flags: list[str] = field(default_factory=list)


# =============================================================================
# Сетевые фетчеры
# =============================================================================


def _http_json(url: str, timeout: int = 20, attempts: int = 2):
    """GET → JSON; один повтор при сбое (ISS иногда рвёт соединение)."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=timeout, context=_ssl_context()) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001 — сетевой слой, любая ошибка = повтор/выброс
            last = e
            if i < attempts - 1:
                time.sleep(1.0)
    assert last is not None
    raise last


def fetch_iss_history(kind: str, secid: str, from_date: dt.date, to_date: dt.date,
                      timeout: int = 20) -> tuple[list[tuple[str, float]], dict]:
    """Дневные CLOSE из ISS history (с пагинацией по 100 строк).

    Для index/rate_index запрашивается ещё CURRENCYID — валюта ряда уходит в meta.
    Строки с CLOSE=None отбрасываются. Бросает исключение при сетевом сбое."""
    spec = KINDS[kind]
    cols = "TRADEDATE,CLOSE,CURRENCYID" if spec["cols"] else "TRADEDATE,CLOSE"
    base = "https://iss.moex.com/iss/history/" + spec["path"].format(secid=secid) + ".json"
    rows: list[tuple[str, float]] = []
    currency: str | None = None
    start = 0
    while True:
        url = (f"{base}?from={from_date.isoformat()}&till={to_date.isoformat()}"
               f"&start={start}&iss.meta=off&history.columns={cols}")
        batch = _http_json(url, timeout=timeout)["history"]["data"]
        if not batch:
            break
        for row in batch:
            if row[1] is None:
                continue
            rows.append((row[0], float(row[1])))
            if spec["cols"] and currency is None and len(row) > 2 and row[2]:
                currency = row[2]
        start += len(batch)
        if len(batch) < ISS_PAGE:
            break
    meta: dict = {}
    if currency:
        meta["currency"] = currency
    return rows, meta


_BOARD_CACHE: dict[str, str] = {}


def bond_board(isin: str, timeout: int = 20) -> str:
    """Основная торговая доска облигации (is_primary=1, рынок bonds)."""
    if isin in _BOARD_CACHE:
        return _BOARD_CACHE[isin]
    url = (f"https://iss.moex.com/iss/securities/{isin}.json?iss.meta=off&iss.only=boards"
           "&boards.columns=boardid,market,is_primary")
    rows = _http_json(url, timeout=timeout)["boards"]["data"]
    prim = [r[0] for r in rows if r[1] == "bonds" and r[2] == 1] or [r[0] for r in rows if r[1] == "bonds"]
    if not prim:
        raise RuntimeError(f"ISS: у {isin} нет доски рынка bonds")
    _BOARD_CACHE[isin] = prim[0]
    return prim[0]


def fetch_bond_history(isin: str, from_date: dt.date, to_date: dt.date,
                       timeout: int = 20) -> tuple[list[tuple[str, float]], dict]:
    """Грязная цена одной бумаги в валюте номинала: CLOSE (или LEGALCLOSEPRICE)·FACEVALUE/100 + ACCINT."""
    board = bond_board(isin, timeout)
    base = (f"https://iss.moex.com/iss/history/engines/stock/markets/bonds/boards/{board}"
            f"/securities/{isin}.json")
    rows: list[tuple[str, float]] = []
    faceunit = None
    start = 0
    while True:
        url = (f"{base}?from={from_date.isoformat()}&till={to_date.isoformat()}&start={start}"
               "&iss.meta=off&history.columns=TRADEDATE,CLOSE,LEGALCLOSEPRICE,ACCINT,FACEVALUE,FACEUNIT")
        batch = _http_json(url, timeout=timeout)["history"]["data"]
        if not batch:
            break
        for d, close, legal, ai, face, fu in batch:
            px = close if close is not None else legal
            if px is None or face is None:
                continue
            rows.append((d, float(px) * float(face) / 100 + float(ai or 0)))
            faceunit = faceunit or fu
        start += len(batch)
        if len(batch) < ISS_PAGE:
            break
    meta = {"board": board}
    if faceunit:
        meta["currency"] = "RUB" if faceunit in ("SUR", "RUB") else faceunit
    return rows, meta


def fetch_bond_cashflows(isin: str, from_date: dt.date, to_date: dt.date,
                         timeout: int = 20) -> tuple[list[tuple[str, float]], dict]:
    """Купоны + амортизации на одну бумагу по дате выплаты (будущие купоны флоатеров без значения — пропуск)."""
    url = (f"https://iss.moex.com/iss/securities/{isin}/bondization.json?iss.meta=off&limit=unlimited"
           "&iss.only=coupons,amortizations&coupons.columns=coupondate,value,faceunit"
           "&amortizations.columns=amortdate,value,faceunit,data_source")
    js = _http_json(url, timeout=timeout)
    by_day: dict[str, float] = {}
    fu = None
    for d, v, unit in js.get("coupons", {}).get("data", []):
        if d and v is not None:
            by_day[d] = by_day.get(d, 0.0) + float(v)
            fu = fu or unit
    for d, v, unit, src in js.get("amortizations", {}).get("data", []):
        if d and v is not None:
            by_day[d] = by_day.get(d, 0.0) + float(v)   # включая погашение номинала в дату погашения
            fu = fu or unit
    lo, hi = from_date.isoformat(), to_date.isoformat()
    pts = sorted((d, round(v, 6)) for d, v in by_day.items() if lo <= d <= hi)
    meta = {"currency": "RUB" if fu in ("SUR", "RUB") else fu} if fu else {}
    return pts, meta


def _weekdays(from_date: dt.date, to_date: dt.date) -> set[dt.date]:
    out, d = set(), from_date
    while d <= to_date:
        if d.weekday() < 5:
            out.add(d)
        d += dt.timedelta(days=1)
    return out


def fetch_fx_cbr(secid: str, from_date: dt.date, to_date: dt.date) -> list[tuple[str, float]]:
    """Курс ЦБ через рабочий/bundled кэш лоадера (ensure_cbr_rates догружает пропуски).

    ensure_cbr_rates глотает сетевые ошибки, поэтому провал определяем сами: если
    ряд пуст или последняя точка отстаёт от to_date больше чем на 5 дней (праздники
    ЦБ короче) — бросаем исключение, чтобы get_series не расширил покрытие вхолостую."""
    cache = load_cbr_cache()
    needed = _weekdays(from_date, to_date)
    if needed:
        cache = ensure_cbr_rates({secid: needed}, cache)
    lo, hi = from_date.isoformat(), to_date.isoformat()
    pts = sorted((d, float(v)) for d, v in cache.get(secid, {}).items() if lo <= d <= hi)
    if needed:
        if not pts:
            raise RuntimeError(f"ЦБ: нет курсов {secid} за {lo}..{hi}")
        last = dt.date.fromisoformat(pts[-1][0])
        if to_date <= dt.date.today() and (to_date - last).days > 5:
            raise RuntimeError(f"ЦБ: курсы {secid} кончаются {last}, запрошено до {to_date}")
    return pts


def fetch_key_rate(from_date: dt.date, to_date: dt.date) -> list[tuple[str, float]]:
    """КС ЦБ; fetch_key_rate_history возвращает None и при сбое, и при пустоте."""
    res = fetch_key_rate_history(from_date, to_date)
    if not res:
        raise RuntimeError(f"ЦБ: КС за {from_date}..{to_date} не получена (сбой или пусто)")
    return res


def default_fetcher(kind: str, secid: str, from_date: dt.date, to_date: dt.date):
    """Сетевой фетчер по умолчанию: (points, meta)."""
    if kind in ("index", "rate_index", "share", "currency"):
        return fetch_iss_history(kind, secid, from_date, to_date)
    if kind == "key_rate":
        return fetch_key_rate(from_date, to_date), {}
    if kind == "fx_cbr":
        return fetch_fx_cbr(secid, from_date, to_date), {}
    if kind == "bond":
        return fetch_bond_history(secid, from_date, to_date)
    if kind == "bond_cf":
        return fetch_bond_cashflows(secid, from_date, to_date)
    raise ValueError(f"неизвестный kind: {kind}")


# =============================================================================
# Кэш
# =============================================================================


def _cache_path(cache_dir: Path, kind: str, secid: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", secid)
    return cache_dir / f"{kind}__{safe}.json"


def _read_cache(path: Path) -> dict | None:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(d, dict) or not d.get("covered_from") or not d.get("covered_to"):
            return None
        d["points"] = [[p[0], float(p[1])] for p in d.get("points", [])]
        return d
    except (OSError, ValueError, TypeError, IndexError):
        return None


def _write_cache(path: Path, data: dict) -> None:
    """Атомарная запись: tmp в том же каталоге + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _normalize(res) -> tuple[list[tuple[str, float]], dict]:
    """Результат фетчера: список или (список, meta)."""
    if isinstance(res, tuple) and len(res) == 2 and isinstance(res[1], dict):
        pts, meta = res
    else:
        pts, meta = res, {}
    return [(str(d), float(v)) for d, v in (pts or []) if v is not None], dict(meta)


# =============================================================================
# Публичный API
# =============================================================================


def get_series(kind: str, secid: str, from_date: dt.date, to_date: dt.date, *,
               cache_dir: Path | None = None, offline: bool = False,
               fetcher=None) -> Series:
    """Ряд [from_date, to_date] из кэша с догрузкой недостающих хвостов.

    fetcher(kind, secid, from_date, to_date) -> list[(iso, float)] | (list, meta).
    Неизвестный kind → ValueError. Сетевой сбой не поднимается наружу — флаг «сеть: …»."""
    if kind not in KINDS:
        raise ValueError(f"неизвестный kind: {kind!r} (допустимо: {', '.join(KINDS)})")
    spec = KINDS[kind]
    fetcher = fetcher or default_fetcher
    cdir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
    path = _cache_path(cdir, kind, secid)
    flags: list[str] = []

    cache = _read_cache(path)
    if cache is None and path.exists():
        flags.append("кэш: файл повреждён, ряд будет перекачан")
    pts: dict[str, float] = {d: v for d, v in cache["points"]} if cache else {}
    cov_from = dt.date.fromisoformat(cache["covered_from"]) if cache else None
    cov_to = dt.date.fromisoformat(cache["covered_to"]) if cache else None
    unit = cache.get("unit") if cache else None
    currency = cache.get("currency") if cache else None
    fetched_at = cache.get("fetched_at") if cache else None

    if cache is None:
        unit, currency = spec["unit"], spec["currency"]

    # какие диапазоны нужно скачать
    ranges: list[tuple[str, dt.date, dt.date]] = []
    if cache is None:
        ranges.append(("all", from_date, to_date))
    else:
        if from_date < cov_from:
            ranges.append(("left", from_date, cov_from - dt.timedelta(days=1)))
        if to_date > cov_to:
            ranges.append(("right", max(cov_from, cov_to - dt.timedelta(days=REFRESH_DAYS)), to_date))

    if offline:
        if ranges:
            if cache is None:
                flags.append("offline: кэша нет, покрытие меньше запроса")
            else:
                flags.append(f"offline: покрытие {cov_from}..{cov_to} меньше запроса")
    else:
        changed = False
        for part, a, b in ranges:
            try:
                new, meta = _normalize(fetcher(kind, secid, a, b))
            except Exception as e:  # noqa: BLE001 — любой сбой фетчера = флаг, не падение
                flags.append(f"сеть: {type(e).__name__}: {e}")
                continue
            for d, v in new:
                pts[d] = v                       # новое значение побеждает
            if meta.get("currency"):
                currency = meta["currency"]
            if meta.get("unit"):
                unit = meta["unit"]
            if part == "all":
                cov_from, cov_to = a, b
            elif part == "left":
                cov_from = a
            else:
                cov_to = b
            fetched_at = dt.datetime.now().isoformat(timespec="seconds")
            changed = True
        if changed:
            _write_cache(path, {
                "kind": kind, "secid": secid, "unit": unit, "currency": currency,
                "source": spec["source"],
                "points": [[d, pts[d]] for d in sorted(pts)],
                "covered_from": cov_from.isoformat(), "covered_to": cov_to.isoformat(),
                "fetched_at": fetched_at,
            })

    lo, hi = from_date.isoformat(), to_date.isoformat()
    out = [(d, pts[d]) for d in sorted(pts) if lo <= d <= hi]
    return Series(kind=kind, secid=secid, unit=unit or spec["unit"], currency=currency,
                  points=out, source=spec["source"], fetched_at=fetched_at, flags=flags)


def get_many(specs: list[tuple[str, str]], from_date: dt.date, to_date: dt.date,
             **kw) -> dict[str, Series]:
    """Несколько рядов; ключ результата — "kind:secid"."""
    return {f"{k}:{s}": get_series(k, s, from_date, to_date, **kw) for k, s in specs}


def lookup(series: Series, d: dt.date, direction: str = "prev") -> float | None:
    """Значение в ближайшей точке <= d ("prev") или >= d ("next"); None, если такой нет."""
    if direction not in ("prev", "next"):
        raise ValueError(f"direction должен быть 'prev' или 'next', получено {direction!r}")
    dates = [p[0] for p in series.points]
    iso = d.isoformat()
    if direction == "prev":
        i = bisect.bisect_right(dates, iso) - 1
        return series.points[i][1] if i >= 0 else None
    i = bisect.bisect_left(dates, iso)
    return series.points[i][1] if i < len(dates) else None


# =============================================================================
# CLI
# =============================================================================


def _summary(s: Series) -> dict:
    return {
        "points": len(s.points),
        "first": s.points[0][0] if s.points else None,
        "last": s.points[-1][0] if s.points else None,
        "last_value": s.points[-1][1] if s.points else None,
        "unit": s.unit, "currency": s.currency, "flags": s.flags,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Дневные ряды MOEX ISS / ЦБ с локальным кэшем")
    ap.add_argument("--series", required=True, help="kind:secid через запятую")
    ap.add_argument("--from", dest="from_date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--to", dest="to_date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--cache-dir", type=Path, default=None)
    ap.add_argument("--offline", action="store_true", help="только кэш, без сети")
    a = ap.parse_args(argv)

    specs: list[tuple[str, str]] = []
    for item in a.series.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            ap.error(f"ожидается kind:secid, получено {item!r}")
        k, s = item.split(":", 1)
        specs.append((k, s))
    res = get_many(specs, dt.date.fromisoformat(a.from_date), dt.date.fromisoformat(a.to_date),
                   cache_dir=a.cache_dir, offline=a.offline)
    summary = {key: _summary(s) for key, s in res.items()}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 2 if any(not s.points for s in res.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
