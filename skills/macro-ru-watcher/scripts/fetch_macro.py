#!/usr/bin/env python3
"""
fetch_macro.py — детерминированный сбор 5 макроиндикаторов RU через публичные API.

Покрывает:
  - IMOEX, RGBI — MOEX ISS engines/stock/markets/index
  - USD/RUB, CNY/RUB — MOEX ISS engines/currency/markets/selt
  - Ключевая ставка ЦБ — CBR DailyInfoWebServ/KeyRateXML

Все 5 запросов идут параллельно через ThreadPoolExecutor. Stdlib only:
urllib, json, xml.etree.ElementTree, gzip, concurrent.futures.

Не покрывает (остаются на web_search в SKILL.md):
  - Инфляция г/г и недельная (Росстат — нет чистого API)
  - Brent (источник вне периметра RU)

CLI:
    python3 fetch_macro.py            # JSON в stdout, exit 0 если все ok
    python3 fetch_macro.py --pretty   # с отступами
    python3 fetch_macro.py --no-parallel
    python3 fetch_macro.py --timeout 30

Output schema:
    {
      "fetched_at_utc": "2026-05-09T12:34:56Z",
      "indicators": {
        "imoex":   {"status": "ok", "value": 2650.41, "prev_close": 2645.10,
                    "change_pct": 0.20, "as_of": "2026-05-08", "source": "moex_iss/index"},
        ...
      },
      "errors": {"<name>": "<message>"}  # только если что-то упало
    }

Exit codes:
  0 — все 5 индикаторов получены
  1 — частичный сбор (есть errors)
  2 — все упало (например, нет сети)
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Any, Callable

ISS_BASE = "https://iss.moex.com/iss"
CBR_KEYRATE_URL = "https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx/KeyRateXML"
USER_AGENT = "macro-ru-watcher/1.0 (+claude_skills)"
DEFAULT_TIMEOUT = 15
RETRIES = 2


# ============================================================================
# SSL context — Python 3.14 framework на macOS не имеет встроенного CA bundle.
# Ищем верифицируемый источник в порядке: certifi → системный keychain → дефолт.
# ============================================================================

def _build_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if ctx.get_ca_certs():
        return ctx
    candidates: list[str] = []
    try:
        import certifi  # type: ignore
        candidates.append(certifi.where())
    except ImportError:
        pass
    candidates += [
        "/etc/ssl/cert.pem",
        "/opt/homebrew/etc/openssl@3/cert.pem",
        "/usr/local/etc/openssl@3/cert.pem",
        "/etc/ssl/certs/ca-certificates.crt",
    ]
    for path in candidates:
        if path and os.path.exists(path):
            try:
                ctx.load_verify_locations(cafile=path)
                if ctx.get_ca_certs():
                    return ctx
            except (ssl.SSLError, OSError):
                continue
    return ctx


_SSL_CTX = _build_ssl_context()


# ============================================================================
# HTTP с gzip и ретраем
# ============================================================================

def _http_request(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = RETRIES,
) -> bytes:
    base_headers = {
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "gzip",
    }
    if headers:
        base_headers.update(headers)
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                url, data=body, method=method, headers=base_headers,
            )
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw
        except (urllib.error.URLError, urllib.error.HTTPError,
                TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
    raise IOError(f"HTTP failed after {retries + 1} attempts: {url} ({last_exc})")


def _http_get(url: str, timeout: int = DEFAULT_TIMEOUT, retries: int = RETRIES) -> bytes:
    return _http_request(url, timeout=timeout, retries=retries)


def _f(x: Any) -> float | None:
    if x is None or x == "":
        return None
    try:
        v = float(x)
        return v if v != 0 else None
    except (TypeError, ValueError):
        return None


# ============================================================================
# MOEX ISS — обобщённый fetcher для индексов и валют
# ============================================================================

def _pick_row(cols: list[str], rows: list[list[Any]],
              prefer_board: str | None = None) -> dict[str, Any]:
    """Выбрать строку из ISS-блока. Для multi-board ответов берём prefer_board.
    Иначе — первую строку, у которой есть осмысленные значения (не all-null)."""
    if not rows:
        return {}
    if prefer_board:
        idx = cols.index("BOARDID") if "BOARDID" in cols else -1
        if idx >= 0:
            for r in rows:
                if len(r) > idx and r[idx] == prefer_board:
                    return dict(zip(cols, r))
    for r in rows:
        d = dict(zip(cols, r))
        if any(v not in (None, "", 0) for v in d.values()):
            return d
    return dict(zip(cols, rows[0]))


def _fetch_iss_security(
    engine: str,
    market: str,
    secid: str,
    *,
    board: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """
    Запрос к ISS. Если задан board — используем board-specific endpoint
    (одна строка в ответе, без неоднозначностей). Иначе — markets-level.

    Для индексов (market=index): CURRENTVALUE = текущее, LASTVALUE = previous close.
    Для валют (market=selt): LAST / WAPRICE / CLOSEPRICE; PREVPRICE из securities.
    """
    if board:
        url = (
            f"{ISS_BASE}/engines/{engine}/markets/{market}/boards/{board}"
            f"/securities/{secid}.json?iss.meta=off&iss.only=securities,marketdata"
        )
    else:
        url = (
            f"{ISS_BASE}/engines/{engine}/markets/{market}/securities/{secid}.json"
            f"?iss.meta=off&iss.only=securities,marketdata"
        )
    raw = _http_get(url, timeout=timeout)
    data = json.loads(raw.decode("utf-8"))

    sec_block = data.get("securities", {}) or {}
    md_block = data.get("marketdata", {}) or {}

    sec = _pick_row(
        sec_block.get("columns") or [],
        sec_block.get("data") or [],
        prefer_board=board,
    )
    md = _pick_row(
        md_block.get("columns") or [],
        md_block.get("data") or [],
        prefer_board=board,
    )

    # value: специфичное для индексов → специфичное для валют → fallback на close
    value = (
        _f(md.get("CURRENTVALUE"))
        or _f(md.get("LAST"))
        or _f(md.get("LASTVALUE"))
        or _f(md.get("MARKETPRICE"))
        or _f(md.get("WAPRICE"))
        or _f(md.get("CLOSEPRICE"))
        or _f(sec.get("PREVPRICE"))      # last resort: вчерашний close
    )
    # prev_close
    prev_close = (
        _f(sec.get("PREVPRICE"))
        or _f(md.get("LASTVALUE"))
        or _f(sec.get("PREVLEGALCLOSEPRICE"))
        or _f(sec.get("PREVWAPRICE"))
    )
    change_pct = (
        _f(md.get("LASTCHANGEPRCNT"))
        or _f(md.get("LASTCHANGEPRC"))
    )
    if change_pct is None and value is not None and prev_close:
        change_pct = round((value - prev_close) / prev_close * 100, 4)

    as_of = (
        md.get("SYSTIME")
        or md.get("UPDATETIME")
        or md.get("TRADEDATE")
        or sec.get("PREVDATE")
    )
    if value is None:
        raise IOError(f"ISS {engine}/{market}/{secid}: no value in marketdata or securities")

    return {
        "value": value,
        "prev_close": prev_close,
        "change_pct": change_pct,
        "as_of": str(as_of) if as_of else None,
    }


def fetch_imoex(timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    return _fetch_iss_security("stock", "index", "IMOEX", timeout=timeout)


def fetch_rgbi(timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """RGBI — price index гособлигаций (без купонов, ~120). Для совместимости
    с историческими snapshot'ами и публикациями в RU-прессе. RGBITR (total
    return, ~780) — параллельный ряд, не используем во избежание разрыва.
    """
    return _fetch_iss_security("stock", "index", "RGBI", timeout=timeout)


def fetch_usdrub(timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    # CETS — основная биржевая доска для валют (FX-спот через ЦК)
    return _fetch_iss_security("currency", "selt", "USD000UTSTOM",
                               board="CETS", timeout=timeout)


def fetch_cnyrub(timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    return _fetch_iss_security("currency", "selt", "CNYRUB_TOM",
                               board="CETS", timeout=timeout)


# ============================================================================
# CBR — ключевая ставка через DailyInfoWebServ/KeyRateXML
# ============================================================================

_CBR_SOAP_ENDPOINT = "https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx"
_CBR_SOAP_ENVELOPE = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
    ' xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
    ' xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
    '<soap:Body>'
    '<KeyRate xmlns="http://web.cbr.ru/">'
    '<fromDate>{from_date}</fromDate>'
    '<ToDate>{to_date}</ToDate>'
    '</KeyRate>'
    '</soap:Body>'
    '</soap:Envelope>'
)


def _local_tag(elem: ET.Element) -> str:
    """Имя тега без XML namespace."""
    return elem.tag.rsplit("}", 1)[-1] if "}" in elem.tag else elem.tag


def fetch_cbr_keyrate(timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """
    Ключевая ставка ЦБ через SOAP-метод KeyRate (DailyInfoWebServ).

    HTTP GET-binding на /KeyRateXML не принимает query-параметры на текущем
    конфиге сервера — приходит редирект на error-страницу. Поэтому используем
    SOAP 1.1 POST с явным envelope.

    Окно: 400 дней (между заседаниями СД может быть >180 дней при паузе).
    Берём самую свежую запись.
    """
    today = date.today()
    from_date = today - timedelta(days=400)
    body = _CBR_SOAP_ENVELOPE.format(
        from_date=from_date.isoformat(),
        to_date=today.isoformat(),
    ).encode("utf-8")

    raw = _http_request(
        _CBR_SOAP_ENDPOINT,
        method="POST",
        body=body,
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "http://web.cbr.ru/KeyRate",
        },
        timeout=timeout,
    )

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise IOError(f"CBR KeyRate SOAP: malformed XML ({exc})")

    # Ответ обёрнут в SOAP envelope + DataSet schema. Достаём KR-элементы по
    # local-name, игнорируя namespace разных уровней.
    parsed: list[tuple[str, float]] = []
    for elem in root.iter():
        if _local_tag(elem) != "KR":
            continue
        dt_text: str | None = None
        rate_text: str | None = None
        for child in elem:
            tag = _local_tag(child)
            if tag == "DT":
                dt_text = (child.text or "").strip()
            elif tag == "Rate":
                rate_text = (child.text or "").strip()
        if not dt_text or not rate_text:
            continue
        try:
            parsed.append((dt_text, float(rate_text)))
        except ValueError:
            continue

    if not parsed:
        raise IOError("CBR KeyRate SOAP: no parseable KR rows in response")

    parsed.sort(key=lambda x: x[0], reverse=True)
    latest_dt, latest_rate = parsed[0]
    return {
        "value": latest_rate,
        "as_of": latest_dt[:10],
        "prev_close": None,
        "change_pct": None,
    }


# ============================================================================
# Оркестратор
# ============================================================================

INDICATORS: dict[str, dict[str, Any]] = {
    "imoex":     {"fn": fetch_imoex,       "source": "moex_iss/index"},
    "rgbi":      {"fn": fetch_rgbi,        "source": "moex_iss/index"},
    "usd_rub":   {"fn": fetch_usdrub,      "source": "moex_iss/currency"},
    "cny_rub":   {"fn": fetch_cnyrub,      "source": "moex_iss/currency"},
    "cbr_key":   {"fn": fetch_cbr_keyrate, "source": "cbr.ru/dailyinfo/KeyRate"},
}


def _run_one(name: str, fn: Callable[..., dict[str, Any]],
             source: str, timeout: int) -> tuple[str, dict[str, Any], str | None]:
    try:
        res = fn(timeout=timeout)
        res["source"] = source
        res["status"] = "ok"
        return name, res, None
    except Exception as exc:  # noqa: BLE001 — наружу даём строкой
        return name, {
            "status": "error",
            "error": str(exc),
            "value": None,
            "source": source,
        }, str(exc)


def fetch_all(parallel: bool = True, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    results: dict[str, Any] = {}
    errors: dict[str, str] = {}

    if parallel:
        with ThreadPoolExecutor(max_workers=len(INDICATORS)) as ex:
            futs = {
                ex.submit(_run_one, name, spec["fn"], spec["source"], timeout): name
                for name, spec in INDICATORS.items()
            }
            for fut in as_completed(futs):
                name, res, err = fut.result()
                results[name] = res
                if err:
                    errors[name] = err
    else:
        for name, spec in INDICATORS.items():
            name, res, err = _run_one(name, spec["fn"], spec["source"], timeout)
            results[name] = res
            if err:
                errors[name] = err

    return {
        "fetched_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "indicators": results,
        "errors": errors,
    }


# ============================================================================
# CLI
# ============================================================================

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Fetch RU macro indicators (MOEX ISS + CBR KeyRateXML)"
    )
    ap.add_argument("--pretty", action="store_true", help="JSON с отступами")
    ap.add_argument("--no-parallel", action="store_true",
                    help="Отключить параллельные HTTP-запросы")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                    help=f"Per-request timeout, sec (default {DEFAULT_TIMEOUT})")
    args = ap.parse_args()

    payload = fetch_all(parallel=not args.no_parallel, timeout=args.timeout)
    indent = 2 if args.pretty else None
    print(json.dumps(payload, ensure_ascii=False, indent=indent, default=str))

    n_total = len(INDICATORS)
    n_err = len(payload["errors"])
    if n_err == 0:
        return 0
    if n_err < n_total:
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
