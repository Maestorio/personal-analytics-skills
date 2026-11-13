#!/usr/bin/env python3
"""
concentration_limits.py

Проверка лимитов концентрации акционной книги — по эмитенту (с группировкой
привилегированных/обыкновенных акций и именованными исключениями из конфига) и,
опционально, по сектору. Постановка — `docs/investment/spec-gate-aware-sizing-trim-fix.md`
§9 (задача C). Конфиг значений — `references/concentration-limits.yaml`.

Ключевое отличие от сайзинга докупки (`gate_aware_sizing.py`): там знаменатель —
неподвижная точка T* (куда книга ИДЁТ, план); здесь знаменатель — фактическая
акционная книга L2_cur (какой риск несётся СЕГОДНЯ). Эти два знаменателя
НЕ унифицируются — это разные вопросы с разными ответами.

Проводка в `gate_aware_sizing.py` (§9/§11 «Волна 3» спеки) завершена: этот модуль
больше НЕ держит собственную копию фильтра активных holdings. `active_stock_holdings`
ниже делегирует `gate_aware_sizing.active_stock_holdings` — единственный источник
(книга акций у обоих модулей обязана совпадать буквально, не только по тесту-
регрессии). Импорт — ЛЕНИВЫЙ (внутри функции, не на верхнем уровне модуля): у пары
файлов циклическая зависимость (`gate_aware_sizing.py` импортирует этот модуль на
верхнем уровне ради `compute_concentration`/`load_limits_config`), и обратный импорт
на верхнем уровне здесь дал бы `ImportError` при том порядке первого импорта, где
`gate_aware_sizing.py` загружается раньше. При любом порядке первого импорта отложенный
`import` внутри функции срабатывает уже на полностью загруженном модуле —
см. `TestSingleSourceActiveStockHoldings` в тестах и отчёт по правке волны 3.

CLI:
    python3 concentration_limits.py \\
        --snapshot <путь к portfolio-<date>.json> \\
        --limits <путь к references/concentration-limits.yaml> \\
        [--sector] \\
        [--json]

Exit codes: 0 — успех; 2 — ошибка входа (снапшот/конфиг/данные), сообщение без
traceback.

Требует PyYAML для чтения конфига лимитов (`--limits`); без него скрипт
завершается exit 2 с понятным сообщением (в отличие от gate_aware_sizing.py,
где YAML опционален, здесь конфиг лимитов — обязательный вход, деградации нет).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from typing import Any

# ─────────────────────────── константы ───────────────────────────

_REQUIRED_EXCEPTION_FIELDS = ("issuer", "limit_pct", "basis", "review_date")


class ConcentrationLimitsError(Exception):
    """Понятная ошибка входа/конфига/данных — CLI ловит и завершается exit 2 без traceback."""


# ─────────────────────────── загрузка снапшота ───────────────────────────

def load_snapshot(path: str) -> dict[str, Any]:
    if not path or not os.path.exists(path):
        raise ConcentrationLimitsError(f"Снапшот не найден: {path!r}")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConcentrationLimitsError(f"Не удалось прочитать/распарсить снапшот {path!r}: {exc}")


def active_stock_holdings(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """holdings[] c asset_type == 'stock', за вычетом cost_basis (замороженные US),
    is_blocked и money-market фондов. Делегирует `gate_aware_sizing.active_stock_holdings`
    (единственный источник фильтра, см. docstring модуля) — импорт ленивый, чтобы не
    зациклить импорт с `gate_aware_sizing.py`. Ошибка входа транслируется в
    `ConcentrationLimitsError`, чтобы контракт ошибок этого модуля не зависел от того,
    что реализация теперь делегирует, а не дублирует."""
    import gate_aware_sizing as _gas
    try:
        return _gas.active_stock_holdings(snapshot)
    except _gas.GateAwareSizingError as exc:
        raise ConcentrationLimitsError(str(exc)) from exc


def compute_l2_cur(holdings: list[dict[str, Any]]) -> float:
    """Фактическая акционная книга — сумма value_rub активных holdings. Знаменатель
    ВСЕХ лимитов концентрации в этом модуле; НЕ T*."""
    return sum(float(h.get("value_rub") or 0.0) for h in holdings)


# ─────────────────────────── конфиг лимитов ───────────────────────────

def _parse_date(value: Any, *, field_name: str) -> date:
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ConcentrationLimitsError(f"Конфиг лимитов: {field_name} должно быть датой ISO (YYYY-MM-DD), получено {value!r}")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ConcentrationLimitsError(f"Конфиг лимитов: {field_name}={value!r} не парсится как дата ISO (YYYY-MM-DD)")


def _validate_limits_config(data: dict[str, Any], *, source: str) -> None:
    if "default_issuer_limit_pct" not in data or not isinstance(data["default_issuer_limit_pct"], (int, float)):
        raise ConcentrationLimitsError(f"{source}: нет числового default_issuer_limit_pct")
    if "sector_limit_pct" not in data or not isinstance(data["sector_limit_pct"], (int, float)):
        raise ConcentrationLimitsError(f"{source}: нет числового sector_limit_pct")

    issuer_groups = data.get("issuer_groups") or {}
    if not isinstance(issuer_groups, dict):
        raise ConcentrationLimitsError(f"{source}: issuer_groups должен быть словарём {{группа: [тикеры]}}")
    for group_key, tickers in issuer_groups.items():
        if not isinstance(tickers, list) or not all(isinstance(t, str) for t in tickers):
            raise ConcentrationLimitsError(f"{source}: issuer_groups.{group_key} должен быть списком тикеров")

    exceptions = data.get("issuer_exceptions") or {}
    if not isinstance(exceptions, dict):
        raise ConcentrationLimitsError(f"{source}: issuer_exceptions должен быть словарём {{id: {{...}}}}")

    seen_issuers: dict[str, str] = {}
    for exc_id, entry in exceptions.items():
        if not isinstance(entry, dict):
            raise ConcentrationLimitsError(f"{source}: issuer_exceptions.{exc_id} должен быть словарём")
        missing = [f for f in _REQUIRED_EXCEPTION_FIELDS if entry.get(f) in (None, "")]
        if missing:
            # Специально понятная формулировка про review_date — это самая опасная
            # молчаливая деградация (исключение без даты пересмотра = отмена лимита навсегда).
            raise ConcentrationLimitsError(
                f"{source}: issuer_exceptions.{exc_id} не хватает поля(ей) {missing} — "
                f"исключение без review_date конфиг не принимает (молчаливая отмена лимита)"
            )
        if not isinstance(entry["limit_pct"], (int, float)):
            raise ConcentrationLimitsError(f"{source}: issuer_exceptions.{exc_id}.limit_pct должен быть числом")
        _parse_date(entry["review_date"], field_name=f"issuer_exceptions.{exc_id}.review_date")

        issuer = entry["issuer"]
        if issuer in seen_issuers:
            raise ConcentrationLimitsError(
                f"{source}: два исключения ({seen_issuers[issuer]!r} и {exc_id!r}) ссылаются на один issuer={issuer!r} — неоднозначно"
            )
        seen_issuers[issuer] = exc_id


def load_limits_config(path: str) -> dict[str, Any]:
    if not path or not os.path.exists(path):
        raise ConcentrationLimitsError(f"Конфиг лимитов не найден: {path!r}")
    try:
        import yaml
    except ImportError:
        raise ConcentrationLimitsError("PyYAML недоступен — конфиг лимитов концентрации требует PyYAML (pip install pyyaml)")
    with open(path, encoding="utf-8") as f:
        try:
            data = yaml.safe_load(f)
        except Exception as exc:  # noqa: BLE001 — любая ошибка парсинга YAML понятна пользователю
            raise ConcentrationLimitsError(f"Не удалось распарсить YAML {path!r}: {exc}")
    if not isinstance(data, dict):
        raise ConcentrationLimitsError(f"Конфиг лимитов пуст или не словарь: {path!r}")
    _validate_limits_config(data, source=path)
    return data


# ─────────────────────────── группировка эмитента ───────────────────────────

def _group_key_for_ticker(ticker: str, issuer_groups: dict[str, list[str]]) -> str:
    """Группа эмитента ИЗ КОНФИГА, не эвристикой по суффиксу. Тикер, не упомянутый
    ни в одной группе, — сам себе группа."""
    for group_key, tickers in issuer_groups.items():
        if ticker in tickers:
            return group_key
    return ticker


def _exceptions_by_issuer(limits_config: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    """issuer -> (exception_id, entry). Уникальность issuer уже проверена при загрузке конфига."""
    out: dict[str, tuple[str, dict[str, Any]]] = {}
    for exc_id, entry in (limits_config.get("issuer_exceptions") or {}).items():
        out[entry["issuer"]] = (exc_id, entry)
    return out


# ─────────────────────────── по эмитенту ───────────────────────────

def _compute_by_issuer(
    holdings: list[dict[str, Any]],
    l2_cur: float,
    limits_config: dict[str, Any],
    today: date,
) -> tuple[dict[str, dict[str, Any]], list[str], set[str]]:
    issuer_groups = limits_config.get("issuer_groups") or {}
    default_limit = float(limits_config["default_issuer_limit_pct"])
    exceptions_by_issuer = _exceptions_by_issuer(limits_config)

    # group_key -> список holdings-тикеров в группе.
    members: dict[str, list[str]] = {}
    values: dict[str, float] = {}
    for h in holdings:
        ticker = h.get("ticker")
        if not ticker:
            continue
        group_key = _group_key_for_ticker(ticker, issuer_groups)
        members.setdefault(group_key, []).append(ticker)
        values[group_key] = values.get(group_key, 0.0) + float(h.get("value_rub") or 0.0)

    warnings: list[str] = []
    blocked_for_open: set[str] = set()
    by_issuer: dict[str, dict[str, Any]] = {}

    for group_key in sorted(values):
        value_rub = values[group_key]
        share_pct = (value_rub / l2_cur * 100.0) if l2_cur else 0.0

        limit_pct = default_limit
        limit_source = "default"

        exc = exceptions_by_issuer.get(group_key)
        if exc is not None:
            exc_id, entry = exc
            review_date = _parse_date(entry["review_date"], field_name=f"issuer_exceptions.{exc_id}.review_date")
            if review_date >= today:
                limit_pct = float(entry["limit_pct"])
                limit_source = f"exception:{exc_id}"
            else:
                # Истёкшее исключение НЕ применяется — деградация к лимиту по умолчанию + warning.
                warnings.append(f"exception_expired:{exc_id}")

        limit_rub = limit_pct / 100.0 * l2_cur
        headroom_pp = limit_pct - share_pct
        breach = (value_rub - limit_rub) > 1e-6
        trim_to_limit_rub = round(max(0.0, value_rub - limit_rub), 2)

        if breach:
            warnings.append(f"concentration_breach:{group_key}")
            blocked_for_open.update(members[group_key])

        by_issuer[group_key] = {
            "tickers": sorted(members[group_key]),
            "value_rub": round(value_rub, 2),
            "share_pct": share_pct,
            "limit_pct": limit_pct,
            "limit_source": limit_source,
            "headroom_pp": headroom_pp,
            "breach": breach,
            "trim_to_limit_rub": trim_to_limit_rub,
        }

    return by_issuer, warnings, blocked_for_open


# ─────────────────────────── по сектору ───────────────────────────

def _compute_by_sector(
    holdings: list[dict[str, Any]],
    l2_cur: float,
    limits_config: dict[str, Any],
    sector_enabled: bool,
) -> tuple[dict[str, Any], list[str], set[str]]:
    if not sector_enabled:
        return {"status": "disabled", "reason": "sector_flag_off"}, [], set()

    null_value = sum(float(h.get("value_rub") or 0.0) for h in holdings if h.get("sector") is None)
    null_share_pct = (null_value / l2_cur * 100.0) if l2_cur else 0.0
    threshold = float(limits_config.get("sector_null_share_threshold_pct", 5.0))

    if null_share_pct > threshold:
        return (
            {
                "status": "disabled",
                "reason": "sector_coverage_below_threshold",
                "null_share_pct": round(null_share_pct, 2),
            },
            ["sector_limit_disabled"],
            set(),
        )

    sector_limit = float(limits_config["sector_limit_pct"])
    members: dict[str, list[str]] = {}
    values: dict[str, float] = {}
    for h in holdings:
        sector = h.get("sector")
        if sector is None:
            continue
        ticker = h.get("ticker")
        members.setdefault(sector, []).append(ticker)
        values[sector] = values.get(sector, 0.0) + float(h.get("value_rub") or 0.0)

    warnings: list[str] = []
    blocked_for_open: set[str] = set()
    by_sector: dict[str, Any] = {}
    for sector in sorted(values):
        value_rub = values[sector]
        share_pct = (value_rub / l2_cur * 100.0) if l2_cur else 0.0
        limit_rub = sector_limit / 100.0 * l2_cur
        headroom_pp = sector_limit - share_pct
        breach = (value_rub - limit_rub) > 1e-6
        trim_to_limit_rub = round(max(0.0, value_rub - limit_rub), 2)
        if breach:
            warnings.append(f"concentration_breach:{sector}")
            blocked_for_open.update(members[sector])
        by_sector[sector] = {
            "tickers": sorted(members[sector]),
            "value_rub": round(value_rub, 2),
            "share_pct": share_pct,
            "limit_pct": sector_limit,
            "headroom_pp": headroom_pp,
            "breach": breach,
            "trim_to_limit_rub": trim_to_limit_rub,
        }

    return by_sector, warnings, blocked_for_open


# ─────────────────────────── публичная функция ───────────────────────────

def compute_concentration(
    snapshot: dict[str, Any],
    limits_config: dict[str, Any],
    *,
    sector_enabled: bool = False,
    today: str | date | None = None,
) -> dict[str, Any]:
    """Основная точка входа для импорта из другого скрипта (напр. будущая проводка
    в gate_aware_sizing.py). `today` — параметр (не date.today() внутри логики по
    умолчанию используется только когда явно не передан) — чтобы тесты не зависели
    от календаря.

    Возвращает:
        {
          "l2_cur": float,                     # фактическая акционная книга — знаменатель
          "concentration": {
              "by_issuer": {group_key: {...}},
              "by_sector": {sector: {...}} | {"status": "disabled", "reason": ..., ...},
          },
          "warnings": [str, ...],
          "blocked_for_open": [TICKER, ...],    # нельзя классифицировать Open — блокирует докупку
        }
    """
    if today is None:
        today_date = date.today()
    elif isinstance(today, date):
        today_date = today
    else:
        today_date = date.fromisoformat(today)

    holdings = active_stock_holdings(snapshot)
    l2_cur = compute_l2_cur(holdings)
    if l2_cur <= 0:
        raise ConcentrationLimitsError("Акционная книга (L2_cur) пуста или неположительна — проверить снапшот")

    by_issuer, issuer_warnings, issuer_blocked = _compute_by_issuer(holdings, l2_cur, limits_config, today_date)
    by_sector, sector_warnings, sector_blocked = _compute_by_sector(holdings, l2_cur, limits_config, sector_enabled)

    return {
        "l2_cur": round(l2_cur, 2),
        "concentration": {"by_issuer": by_issuer, "by_sector": by_sector},
        "warnings": issuer_warnings + sector_warnings,
        "blocked_for_open": sorted(issuer_blocked | sector_blocked),
    }


# ─────────────────────────── форматирование (CLI, текстовый режим) ───────────────────────────

def _fmt_rub(x: float) -> str:
    return f"{round(x):,}".replace(",", " ") + " ₽"


def _fmt_pct(x: float, nd: int = 2) -> str:
    s = f"{x:.{nd}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s.replace(".", ",")


def build_text_report(result: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"Акционная книга (L2_cur): {_fmt_rub(result['l2_cur'])}.")
    lines.append("")
    lines.append("По эмитенту:")
    for group_key, row in result["concentration"]["by_issuer"].items():
        mark = " — НАРУШЕНИЕ" if row["breach"] else ""
        lines.append(
            f"- {group_key} ({'+'.join(row['tickers'])}): {_fmt_rub(row['value_rub'])} "
            f"= {_fmt_pct(row['share_pct'])}% (лимит {_fmt_pct(row['limit_pct'])}%, {row['limit_source']}, "
            f"запас {_fmt_pct(row['headroom_pp'])} пп){mark}"
        )
        if row["breach"]:
            lines.append(f"  срез до лимита: {_fmt_rub(row['trim_to_limit_rub'])}")

    by_sector = result["concentration"]["by_sector"]
    lines.append("")
    if by_sector.get("status") == "disabled":
        lines.append(f"По сектору: не считается ({by_sector.get('reason')}).")
    else:
        lines.append("По сектору:")
        for sector, row in by_sector.items():
            mark = " — НАРУШЕНИЕ" if row["breach"] else ""
            lines.append(
                f"- {sector}: {_fmt_rub(row['value_rub'])} = {_fmt_pct(row['share_pct'])}% "
                f"(лимит {_fmt_pct(row['limit_pct'])}%, запас {_fmt_pct(row['headroom_pp'])} пп){mark}"
            )

    if result["warnings"]:
        lines.append("")
        lines.append("Предупреждения: " + "; ".join(result["warnings"]))
    if result["blocked_for_open"]:
        lines.append("")
        lines.append("Заблокировано для докупки (Open): " + ", ".join(result["blocked_for_open"]))

    return "\n".join(lines)


# ─────────────────────────── CLI ───────────────────────────

def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Лимиты концентрации акционной книги (по эмитенту / сектору).")
    ap.add_argument("--snapshot", required=True, help="Путь к portfolio-<date>.json")
    ap.add_argument("--limits", required=True, help="Путь к references/concentration-limits.yaml")
    ap.add_argument("--sector", action="store_true", help="Включить секторный лимит (гейт на sector=null coverage)")
    ap.add_argument("--json", action="store_true", help="JSON-выход вместо текстового отчёта")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_arg_parser()
    args = ap.parse_args(argv)

    try:
        snapshot = load_snapshot(args.snapshot)
        limits_config = load_limits_config(args.limits)
        result = compute_concentration(snapshot, limits_config, sector_enabled=args.sector)
    except ConcentrationLimitsError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(build_text_report(result))

    return 0


if __name__ == "__main__":
    sys.exit(main())
