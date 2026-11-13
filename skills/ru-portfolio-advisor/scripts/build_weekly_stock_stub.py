#!/usr/bin/env python3
"""
build_weekly_stock_stub.py — детерминированный stub-генератор для weekly-review-stock-{date}.yaml.

Читает portfolio JSON snapshot (schema v2), выдаёт YAML-стаб с пре-заполненными:
- Top-level метаданными (schema_version: 2 как ЧИСЛО, type, review_date в КАВЫЧКАХ,
  horizons/horizon_ends/primary_horizon — Phase 4 multiple horizons, snapshot_id, ...)
- per_stock[ticker] детерминированными полями: weight_real_pct, weight_user_planned_pct,
  weight_ie_target_pct, weight_divergence_vs_planned_pp (primary), weight_divergence_vs_ie_pp
  (secondary, + deprecated алиас weight_divergence_pp), on_iis, sector, sector_ru, price_rub,
  xirr, pnl_rub, ie_divergence_*

PDL-I (2026-08-27): `sector` — ВСЕГДА машинный canon-ключ (macro-forecast-chain/stress);
`sector_ru` — отдельное поле для отображаемого ярлыка (словарь IntelInvest), None, если
ярлыка нет ни в snapshot.holdings, ни в overrides (переводов не выдумываем). Раньше
sector_ru схлопывался в sector — исправлено, поля разведены (см. TODO.md#pdl-i).
- TODO_LLM плейсхолдерами (строки вида `TODO_LLM_<hint>`) для аналитических полей
  (fundamental_score, div_yield_12m_pct, catalyst[], advisor_verdict)
- verification_priority: null — приоритет проверки ставит `assemble_artifact.py stamp-report` функцией движка
  после записи обзора (R28); статус гейта в обзор не копируется (его даёт модуль (б) через security_digest)

LLM должна заменить TODO_LLM значения, НЕ переименовывать поля, НЕ удалять ключи,
НЕ менять структуру. Validator в save-to-library (validate_weekly_review_stock_detailed)
блокирует запись, если остался хотя бы один TODO_LLM.

CLI:
  python3 build_weekly_stock_stub.py \\
    --snapshot /path/to/portfolio-{date}.json \\
    --output /tmp/weekly-review-stock-{date}.stub.yaml

Stdout: путь к сгенерированному файлу или JSON-сводка.
Exit codes: 0 — успех, 1 — ошибка чтения snapshot / неподдерживаемая версия.
"""

from __future__ import annotations

import argparse
import calendar
import json
import sys
from datetime import date as date_t
from pathlib import Path
from typing import Any

# Фонды денежного рынка. В per_stock — только если у них есть доля в книге акций
# (ie_actual.real_share_pct; так было в снапшотах с балансом Numbers), с пометкой
# asset_type_actual: fund_money_market. Без доли — не пишутся: в книгу акций не входят,
# а weight_real_pct: null валидатор обзора блокирует.
MONEY_MARKET_TICKERS = {"TMON", "TPAY", "LQDT", "SBMM"}


def select_stocks(snapshot: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Отбор бумаг для per_stock — один для стаба и для сводки stdout.

    → (активные бумаги, пропущенные по причинам):
      frozen_us     — цена по себестоимости (cost_basis: заморожены в феврале 2022, в т.ч. с is_blocked);
      blocked       — прочие заблокированные (is_blocked без cost_basis);
      no_moex_price — не заблокированы, но цены MOEX нет (зависшие last_trade и т.п.);
      money_market  — фонд денежного рынка без доли в книге акций.
    """
    ie_actual = (snapshot.get("ie_actual") or {}).get("per_ticker", {}) or {}
    active: list[dict[str, Any]] = []
    skipped: dict[str, list[str]] = {"frozen_us": [], "blocked": [], "no_moex_price": [], "money_market": []}
    for h in snapshot.get("holdings", []):
        t = h.get("ticker")
        if not t:
            continue
        is_mm = t in MONEY_MARKET_TICKERS
        # MM-фонды с 2026-07-08 несут честный asset_type=fund — гейт по списку, не по типу.
        if h.get("asset_type") != "stock" and not is_mm:
            continue
        price_source = h.get("current_price_source")
        if price_source == "cost_basis":
            skipped["frozen_us"].append(t)
        elif h.get("is_blocked"):
            skipped["blocked"].append(t)
        elif is_mm:
            if (ie_actual.get(t) or {}).get("real_share_pct") is None:
                skipped["money_market"].append(t)
            else:
                active.append(h)
        elif price_source == "moex_iss":
            active.append(h)
        else:
            skipped["no_moex_price"].append(t)
    # По стоимости убыв. — для удобства чтения
    active.sort(key=lambda h: h.get("value_rub") or 0, reverse=True)
    return active, skipped

# ── Phase 4 (schema v2): multiple horizons ──
# Одна константа на producer/consumer, перекрывается CLI (D4-9).
DEFAULT_HORIZONS = [6, 12, 24]
DEFAULT_PRIMARY_HORIZON = 12


def parse_horizons(spec: str | None) -> list[int]:
    """'12,20,36' → [12, 20, 36] (отсортировано, уникально). None → DEFAULT_HORIZONS."""
    if not spec:
        return list(DEFAULT_HORIZONS)
    out = sorted({int(tok) for tok in spec.split(",") if tok.strip()})
    if not out:
        raise ValueError("пустой список горизонтов")
    return out


def add_months_eom(d: date_t, months: int) -> date_t:
    """d + months месяцев, округлённое до КОНЦА месяца (детерминированно, без хардкода)."""
    idx = d.year * 12 + (d.month - 1) + months
    year, month = idx // 12, idx % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date_t(year, month, last_day)


def compute_horizon_ends(review_date: str, horizons: list[int]) -> dict[str, str]:
    """{hNN: 'YYYY-MM-DD'} — конец месяца (review_date + NN мес). 29 февраля корректно."""
    base = date_t.fromisoformat(review_date[:10])
    return {f"h{h}": add_months_eom(base, h).isoformat() for h in horizons}


def parse_anchor_dates(spec: str | None) -> list[str] | None:
    """'2027-06-30,2028-06-30' → ['2027-06-30', '2028-06-30']. None → None."""
    if not spec:
        return None
    return [tok.strip() for tok in spec.split(",") if tok.strip()]


def anchor_dates_to_horizons(review_date: str, dates: list[str]) -> tuple[list[int], dict[str, str]]:
    """
    Якорный режим: даты-цели → (horizons N, horizon_ends). N = календарных
    месяцев между review_date и целью (без ручной арифметики у пользователя).
    На следующем прогоне с той же датой N меньше → consumer пересчитает доходность.
    """
    base = date_t.fromisoformat(review_date[:10])
    seen: dict[int, str] = {}
    for ds in dates:
        d = date_t.fromisoformat(ds[:10])
        n = (d.year - base.year) * 12 + (d.month - base.month)
        if n <= 0:
            raise ValueError(
                f"якорная дата {ds} не в будущем относительно {review_date} (N={n})"
            )
        if n in seen and seen[n] != d.isoformat():
            raise ValueError(
                f"две якорные даты дают один горизонт h{n}: {seen[n]} и {d.isoformat()}"
            )
        seen[n] = d.isoformat()
    horizons = sorted(seen)
    return horizons, {f"h{n}": seen[n] for n in horizons}


def load_snapshot(path: Path) -> dict[str, Any]:
    """Загрузить и валидировать portfolio JSON snapshot v2."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        sys.stderr.write(f"ERROR: snapshot not found: {path}\n")
        sys.exit(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"ERROR: snapshot is not valid JSON: {e}\n")
        sys.exit(1)
    sv = str(data.get("schema_version", ""))
    if not sv.startswith("2."):
        sys.stderr.write(f"ERROR: snapshot schema_version={sv!r}; expected 2.x\n")
        sys.exit(1)
    return data


def y_str(value: str) -> str:
    """YAML-quoted string (double quotes). Экранирует только обратные слэши и кавычки."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def y_num(value: float | int | None, decimals: int | None = None) -> str:
    """YAML-число или null. decimals=None → repr; иначе фиксированная точность."""
    if value is None:
        return "null"
    if isinstance(value, bool):  # bool is a subclass of int — exclude explicitly
        return "true" if value else "false"
    if decimals is not None:
        return f"{value:.{decimals}f}"
    # Без принудительного округления — float по умолчанию
    if isinstance(value, float):
        # Срезать «грязный хвост» 0.6446999999999999
        formatted = f"{value:.6f}".rstrip("0").rstrip(".")
        return formatted if formatted else "0"
    return str(value)


def y_bool(value: Any) -> str:
    """YAML-boolean."""
    return "true" if bool(value) else "false"


def build_per_stock_entry(
    ticker: str,
    holding: dict[str, Any],
    ie_actual_record: dict[str, Any] | None,
    ie_model_record: dict[str, Any] | None,
    xirr_record: dict[str, Any] | None,
    today_iso: str,
    sector_overrides: dict[str, dict[str, str | None]] | None = None,
) -> list[str]:
    """Сгенерировать YAML-блок для одного тикера. Возвращает список строк (без \\n)."""
    lines: list[str] = []
    lines.append(f"  {ticker}:")

    is_money_market = ticker in MONEY_MARKET_TICKERS

    # === Sector: цепочка ie_model → snapshot.holdings → overrides → unknown ===
    # holdings выше overrides сознательно: сектор из IntelInvest («Общий баланс») —
    # факт в отображаемом словаре; overrides только закрывают дыры (SBERP/MOEX/NVTK/
    # BTBR и новые бумаги), не перекрашивая уже размеченные тикеры.
    override_entry = (sector_overrides.get(ticker) if sector_overrides else None) or {}
    if is_money_market:
        sector = "cash-equivalent"
        sector_ru = None
    else:
        sector = (
            (ie_model_record.get("sector") if ie_model_record else None)
            or holding.get("sector")
            or override_entry.get("sector")
            or "unknown"
        )
        # sector_ru (PDL-I) — отображаемый ярлык. Только из holdings.sector_ru (снапшот,
        # уже прошедший override в assemble_snapshot) или напрямую из overrides; НЕ из
        # ie_model/machine-кода — не выдумываем перевод там, где ярлыка нет.
        sector_ru = holding.get("sector_ru") or override_entry.get("sector_ru")
    lines.append(f"    sector: {y_str(sector)}")
    lines.append(f"    sector_ru: {y_str(sector_ru) if sector_ru else 'null'}")
    # Название эмитента — из snapshot.holdings[].name; нет — поле не ставим (MD обзора тогда
    # берёт название из маркера модели). Аддитивное поле: старые обзоры без name работают как раньше.
    if holding.get("name"):
        lines.append(f"    name: {y_str(holding['name'])}")

    # === Weight ===
    # Canonical schema: weight_real_pct = ie_actual.real_share_pct — «Доля Реальная» из Numbers,
    # доля в АКЦИОННОЙ книге (сумма по тикерам = 100%), а не во всём портфеле (PDL-RECON 2026-10-20).
    # Стаб и проверка divergence — из ОДНОГО снапшота: пересобранный снапшот + старые target/divergence
    # дают блок валидатора (CNRU 16.10).
    # Без ie_actual бумага сюда не доходит: загрузчик даёт долю каждой акции основного счёта,
    # MM-фонд без доли отсекает select_stocks() (null заблокировал бы сохранение обзора).
    real_share = None
    if ie_actual_record:
        real_share = ie_actual_record.get("real_share_pct")
    lines.append(f"    weight_real_pct: {y_num(real_share, 4)}")

    # Плановая доля владельца (RPA-19) — PRIMARY target. До 20.08.2026 схема несла
    # только IE-цель, и артефакт структурно кодировал IE как единственный таргет:
    # у 7 из 22 бумаг обзора 15.08 расхождения не было вовсе (нет в модели IE), при
    # том что план владельца есть у всех. null — если тикера нет в ie_actual или
    # план по нему не задан.
    user_planned = ie_actual_record.get("planned_share_pct") if ie_actual_record else None
    lines.append(f"    weight_user_planned_pct: {y_num(user_planned, 4)}")

    # IE target (null если тикера нет в IE-модели)
    ie_target = ie_model_record.get("target_share_pct") if ie_model_record else None
    lines.append(f"    weight_ie_target_pct: {y_num(ie_target, 2)}")

    # Расхождение с планом владельца — PRIMARY (null, если нет real или плана).
    if real_share is not None and user_planned is not None:
        div_planned = round(real_share - user_planned, 4)
        lines.append(f"    weight_divergence_vs_planned_pp: {y_num(div_planned, 4)}")
    else:
        lines.append("    weight_divergence_vs_planned_pp: null  # нет плановой доли или real_share_pct")

    # Расхождение с целью IE — SECONDARY. `weight_divergence_pp` — историческое имя
    # того же числа, оставлено для обратной совместимости (вьюер и обзоры до 20.08).
    if real_share is not None and ie_target is not None:
        divergence = round(real_share - ie_target, 4)
        lines.append(f"    weight_divergence_vs_ie_pp: {y_num(divergence, 4)}")
        lines.append(f"    weight_divergence_pp: {y_num(divergence, 4)}  # deprecated алиас weight_divergence_vs_ie_pp")
    else:
        lines.append("    weight_divergence_vs_ie_pp: null  # нет в IE-модели или нет real_share_pct")
        lines.append("    weight_divergence_pp: null  # deprecated алиас weight_divergence_vs_ie_pp")

    # === IPO-гейт (ретро-разбор 2026-07: пост-IPO хайпы — главный источник
    # проигрыша индексу). Механически из снапшота: < 8 полных кварталов
    # публичной торговли на MOEX → post_ipo_guard, вердикт капится (не BUY/ADD).
    laq = holding.get("listing_age_quarters")
    if laq is not None:
        lines.append(f"    listing_age_quarters: {laq}")
        lines.append(f"    post_ipo_guard: {y_bool(laq < 8)}"
                     + ("  # < 8 кварталов на MOEX — BUY/ADD запрещён без явного user-override" if laq < 8 else ""))
    else:
        lines.append("    listing_age_quarters: null  # snapshot без listing_date (старый data-loader)")
        lines.append("    post_ipo_guard: null")

    # === Account / IIS ===
    on_iis = (holding.get("account") == "iis_3")
    lines.append(f"    on_iis: {y_bool(on_iis)}")

    # === Money-market marker ===
    if is_money_market:
        lines.append(f"    asset_type_actual: fund_money_market")

    # === Price / XIRR / P&L (детерминированные числа из snapshot) ===
    price = holding.get("current_price")
    lines.append(f"    price_rub: {y_num(price, 4)}")
    if xirr_record:
        lines.append(f"    xirr: {y_num(xirr_record.get('xirr'), 4)}")
        lines.append(f"    pnl_rub: {y_num(xirr_record.get('pnl_rub'), 2)}")
    else:
        lines.append(f"    xirr: null  # нет per_instrument_xirr записи")
        lines.append(f"    pnl_rub: null")

    # === IE divergence intent (из user_plan / user_status / user_note_*) ===
    if ie_actual_record:
        plan = ie_actual_record.get("user_plan")
        status = ie_actual_record.get("user_status")
        intentional = any(
            v is not None and str(v).strip() != "" for v in (plan, status)
        )
        lines.append(f"    ie_divergence_intentional: {y_bool(intentional)}")
        # Concat non-empty user_plan / user_status / user_note_* fields для basis
        notes = []
        for k in ("user_plan", "user_status", "user_note_ie", "user_note_ai"):
            v = ie_actual_record.get(k)
            if v and str(v).strip():
                notes.append(f"[{k}] {v}")
        if notes:
            basis = " | ".join(notes)
            lines.append(f"    ie_divergence_basis: {y_str(basis)}")
        else:
            lines.append(f"    ie_divergence_basis: null")
    else:
        lines.append(f"    ie_divergence_intentional: false")
        lines.append(f"    ie_divergence_basis: null")

    # === Аналитические поля — заполнить LLM ===
    lines.append(f"    # === Аналитические поля ниже — заполнить LLM (НЕ переименовывать ключи) ===")
    lines.append(f"    fundamental_score: TODO_LLM_HIGH_MEDIUM_LOW_RED_FLAG")
    lines.append(f"    fundamental_score_basis: TODO_LLM_2_to_5_lines_with_facts")
    lines.append(f"    fundamental_score_sources:")
    lines.append(f"      - url: TODO_LLM_url")
    lines.append(f"        label: TODO_LLM_short_label")
    lines.append(f"        accessed_date: {y_str(today_iso)}")
    lines.append(f"    div_yield_12m_pct:")
    lines.append(f"      value: TODO_LLM_float_pct")
    lines.append(f"      ci_pct: TODO_LLM_list_lo_hi")
    lines.append(f"    div_confidence: TODO_LLM_HIGH_MEDIUM_LOW")
    lines.append(f"    div_basis: TODO_LLM_2_to_5_lines_with_facts")
    lines.append(f"    div_sources:")
    lines.append(f"      - url: TODO_LLM_url")
    lines.append(f"        label: TODO_LLM_short_label")
    lines.append(f"        accessed_date: {y_str(today_iso)}")
    lines.append(f"    # dividend_forward — Слой 3 total-return (2-летняя forward-проекция).")
    lines.append(f"    # Гейт policy_state: вклад дают ТОЛЬКО declared/expected;")
    lines.append(f"    # suspended/none/uncertain → year*_yield_pct НЕ заполнять (вклад 0).")
    lines.append(f"    # НЕ брать backward div_yield_2024 из IE-модели как forward!")
    lines.append(f"    dividend_forward:")
    lines.append(f"      policy_state: TODO_LLM_declared_expected_suspended_none_uncertain")
    lines.append(f"      year1_yield_pct: TODO_LLM_float_or_remove_if_not_declared_expected")
    lines.append(f"      year2_yield_pct: TODO_LLM_float_or_remove_if_year2_basis_none")
    lines.append(f"      year2_basis: TODO_LLM_analyst_carry_forward_none")
    lines.append(f"      source: TODO_LLM_div_calendar_or_board_decision_or_analyst")
    lines.append(f"      as_of: {y_str(today_iso)}")
    lines.append(f"      confidence: TODO_LLM_HIGH_MEDIUM_LOW  # declared=HIGH, expected=MEDIUM, carry_forward=LOW")
    lines.append(f"      note: TODO_LLM_one_line_projection_basis")
    lines.append(f"    catalyst:")
    lines.append(f"      # Минимум 1 catalyst. Удалить этот placeholder и заменить реальными.")
    lines.append(f"      # Каждый catalyst — full structure (см. Pre-emit checklist в SKILL.md).")
    lines.append(f"      - id: TODO_LLM_slug")
    lines.append(f"        trigger: TODO_LLM_free_text_event_or_milestone")
    lines.append(f"        date_window: TODO_LLM_YYYY-MM_or_YYYY-Qx_or_YYYY_or_range  # ОБЯЗАТЕЛЬНО (v2): consumer вычисляет горизонт из него")
    lines.append(f"        p: TODO_LLM_float_0_to_1_probability")
    lines.append(f"        upside_pct: TODO_LLM_float_or_null_if_downside_only")
    lines.append(f"        upside_ci_pct: TODO_LLM_list_lo_hi_or_null")
    lines.append(f"        downside_pct: TODO_LLM_float_or_null_if_upside_only")
    lines.append(f"        downside_ci_pct: TODO_LLM_list_lo_hi_or_null")
    lines.append(f"        source: TODO_LLM_url_or_advisor_estimate_with_basis")
    lines.append(f"        source_quality: TODO_LLM_HIGH_MEDIUM_LOW")
    lines.append(f"        macro_dependency: TODO_LLM_A_B_C_D_or_null")
    lines.append(f"    advisor_verdict: TODO_LLM_BUY_HOLD_TRIM_SELL")
    lines.append(f"    advisor_verdict_confidence: TODO_LLM_float_0_to_1")
    lines.append(f"    confidence_basis: TODO_LLM_what_lowers_confidence_one_phrase_or_null")
    lines.append(f"    advisor_verdict_basis: TODO_LLM_2_to_5_lines_with_actionable_thesis")
    lines.append(f"    verification_priority: null  # ставит stamp-report save-to-library (R28), модель не заполняет")

    return lines


def load_sector_overrides(path: Path | None) -> dict[str, dict[str, str | None]]:
    """Загрузить sector-overrides.yaml → {ticker: {"sector": ..., "sector_ru": ...}}.

    `sector` — ВСЕГДА машинный canon-ключ (словарь macro-forecast-chain/stress).
    `sector_ru` — отображаемый ярлык (словарь IntelInvest), если задан в записи,
    иначе None (переводов не выдумываем).

    PDL-I (2026-08-27): раньше функция схлопывала оба поля записи override в одно
    возвращаемое значение (`sector_ru or sector`), из-за чего в per_stock[ticker].sector
    писался то машинный ключ, то русский ярлык — один и тот же сектор оказывался под
    двумя разными именами (см. docs/investment/TODO.md#pdl-i). Теперь оба поля
    возвращаются раздельно и НИКОГДА не подменяют друг друга у потребителя.
    Зеркало парсера — _load_sector_overrides в assemble_snapshot.py
    (portfolio-data-loader); при правке синхронизировать оба. При ошибке — {}.
    """
    if not path or not path.exists():
        return {}
    try:
        import re as _re
        text = path.read_text(encoding="utf-8")
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


def build_stub(
    snapshot: dict[str, Any],
    today_iso: str,
    horizons: list[int] | None = None,
    primary_horizon: int = DEFAULT_PRIMARY_HORIZON,
    anchor_dates: list[str] | None = None,
    sector_overrides: dict[str, dict[str, str | None]] | None = None,
) -> str:
    """Сгенерировать полный YAML-стаб как строку."""
    as_of = snapshot.get("as_of_date") or today_iso
    snapshot_id = f"portfolio-{as_of}.json"
    # Дата обзора — день прогона, а не снапшота (снапшот бывает на несколько дней старше: 26.10.2026
    # обзор шёл по снапшоту 23.10, модель правила review_date руками). Раньше снапшота — не бывает.
    review = max(today_iso[:10], str(as_of)[:10])
    if anchor_dates:
        # Якорный режим: горизонты выводятся из дат-целей (§11.6).
        horizons, h_ends = anchor_dates_to_horizons(review, anchor_dates)
        if primary_horizon not in horizons:
            primary_horizon = horizons[0]  # ближайшая цель
    else:
        horizons = horizons or list(DEFAULT_HORIZONS)
        if primary_horizon not in horizons:
            raise ValueError(
                f"primary_horizon={primary_horizon} не входит в horizons={horizons}"
            )
        h_ends = compute_horizon_ends(review, horizons)

    holdings = snapshot.get("holdings", [])
    ie_actual = (snapshot.get("ie_actual") or {}).get("per_ticker", {}) or {}
    ie_model_positions = (snapshot.get("ie_model") or {}).get("positions") or []
    # ie_model.positions is a list of dicts — index by ticker
    ie_model: dict[str, dict[str, Any]] = {}
    if isinstance(ie_model_positions, list):
        for p in ie_model_positions:
            t = p.get("ticker")
            if t:
                ie_model[t] = p
    elif isinstance(ie_model_positions, dict):
        ie_model = ie_model_positions
    xirr_map = snapshot.get("per_instrument_xirr", {}) or {}

    # Отбор — select_stocks(): торгуемые на MOEX акции + MM-фонды с долей в книге акций.
    active_stocks, _skipped = select_stocks(snapshot)

    out: list[str] = []
    # === Top-level ===
    out.append(f"# weekly-review-stock-{review}.yaml")
    out.append(f"# Generated by build_weekly_stock_stub.py from {snapshot_id}.")
    out.append(f"# LLM должна заменить TODO_LLM плейсхолдеры. Имена полей фиксированы — НЕ переименовывать.")
    out.append(f"# Validator save-to-library (validate-weekly-review-stock) блокирует запись с TODO_LLM.")
    out.append("")
    out.append("schema_version: 2")
    out.append("type: weekly-stocks-review")
    out.append(f"review_date: {y_str(review)}")
    # v2 (Phase 4): multiple horizons — horizon_ends детерминированы от review_date
    # (конец месяца review_date + NN мес). horizon_months/horizon_end удалены.
    out.append(f"horizons: [{', '.join(str(h) for h in horizons)}]")
    out.append("horizon_ends:")
    for h in horizons:
        out.append(f"  h{h}: {y_str(h_ends[f'h{h}'])}")
    out.append(f"primary_horizon: {primary_horizon}  # advisor_verdict привязан к нему")
    out.append(f"horizon_mode: {'anchored' if anchor_dates else 'rolling'}  # rolling=скользящий (default), anchored=якорный (--anchor-dates)")
    out.append(f"snapshot_id: {y_str(snapshot_id)}")
    out.append(f"snapshot_date: {y_str(as_of)}")
    out.append(f'advisor_version: "ru-portfolio-advisor@2.x"')
    out.append("producer: TODO_LLM_model_name  # пример: claude-<семейство>-<версия>")
    out.append(f"macro_input: TODO_LLM_macro_marginal_filename_or_null  # пример: macro-marginal-{as_of}.yaml")
    out.append("")
    out.append("# === Portfolio summary (числа из snapshot, детерминировано) ===")
    bs = snapshot.get("balance_summary", {})
    by_acc = bs.get("by_account", {})
    main = by_acc.get("main", {})
    total_excl_iis = bs.get("total_current_rub_excl_iis") or main.get("total_rub")
    stocks_rub = main.get("stocks_rub")
    target_share_pct = None
    for g in (bs.get("goals_overall") or []):
        if g.get("Тип") in ("Акции", "Stocks"):
            target_share_pct = round((g.get("Доля") or 0) * 100, 2)
            break
    stocks_share_actual_pct = None
    if total_excl_iis and stocks_rub is not None:
        stocks_share_actual_pct = round(stocks_rub / total_excl_iis * 100, 2)
    out.append("portfolio_summary:")
    out.append(f"  total_excl_iis_rub: {y_num(total_excl_iis, 2)}")
    out.append(f"  total_stocks_value_rub: {y_num(stocks_rub, 2)}")
    out.append(f"  stocks_share_actual_pct: {y_num(stocks_share_actual_pct, 2)}")
    out.append(f"  stocks_share_target_pct: {y_num(target_share_pct, 2)}")
    if target_share_pct is not None and stocks_share_actual_pct is not None:
        undershoot = round(stocks_share_actual_pct - target_share_pct, 2)
        undershoot_rub = (
            round((stocks_share_actual_pct - target_share_pct) / 100 * total_excl_iis, 2)
            if total_excl_iis else None
        )
        out.append(f"  stocks_undershoot_pct: {y_num(undershoot, 2)}")
        out.append(f"  stocks_undershoot_rub: {y_num(undershoot_rub, 2)}")
    else:
        out.append("  stocks_undershoot_pct: null")
        out.append("  stocks_undershoot_rub: null")
    ie_summary = snapshot.get("ie_summary", {})
    out.append(f"  active_ru_tickers: {y_num(ie_summary.get('tickers_in_portfolio_active'), 0)}")
    out.append(f"  ie_model_tickers: {y_num(ie_summary.get('tickers_in_ie_model'), 0)}")
    out.append(f"  ie_overlap: {y_num(ie_summary.get('tickers_in_both'), 0)}")
    out.append(f"  ie_changes_count: {y_num(ie_summary.get('ie_changes_count'), 0)}")
    # Frozen US-stocks / non-active share (исключены из per_stock — нет moex_iss-цены)
    frozen_value = sum(
        (h.get("value_rub") or 0) for h in holdings
        if h.get("asset_type") == "stock"
        and h.get("ticker")
        and h.get("current_price_source") != "moex_iss"
        and h["ticker"] not in MONEY_MARKET_TICKERS
        and not h.get("is_blocked")
    )
    frozen_pct = round(frozen_value / total_excl_iis * 100, 2) if total_excl_iis else None
    out.append(f"  flagged_frozen_us_share_pct: {y_num(frozen_pct, 2)}  # US-stocks в snapshot, исключённые из IE-анализа")
    # Returns (если есть)
    returns_obj = snapshot.get("returns") or {}
    by_type = returns_obj.get("by_type") or {}
    stock_ret = by_type.get("stock") or {}
    restricted = returns_obj.get("restricted") or {}
    total_ret = returns_obj.get("total") or {}
    out.append("  returns:")
    out.append(f"    portfolio_xirr_total: {y_num(total_ret.get('xirr'), 4)}")
    out.append(f"    portfolio_xirr_restricted: {y_num(restricted.get('xirr'), 4)}")
    out.append(f"    stocks_xirr: {y_num(stock_ret.get('xirr'), 4)}")
    out.append(f"    stocks_pnl_rub: {y_num(stock_ret.get('pnl_rub'), 2)}")
    out.append("")

    # === per_stock ===
    out.append(f"# === per_stock: {len(active_stocks)} active position(s). ===")
    out.append("# Сортировка по value_rub desc для удобства чтения. Имена ключей и порядок —")
    out.append("# каноническая схема (weekly-review-schema.md). НЕ переименовывать.")
    out.append("per_stock:")
    out.append("")
    for h in active_stocks:
        t = h["ticker"]
        out.extend(build_per_stock_entry(
            ticker=t,
            holding=h,
            ie_actual_record=ie_actual.get(t),
            ie_model_record=ie_model.get(t),
            xirr_record=xirr_map.get(t),
            today_iso=today_iso,
            sector_overrides=sector_overrides,
        ))
        out.append("")

    # === Дополнительные верхнеуровневые блоки (LLM-content) ===
    out.append("# === Risks / caveats / sources — заполнить LLM ===")
    out.append("key_risks:")
    out.append("  - id: TODO_LLM_slug")
    out.append("    severity: TODO_LLM_HIGH_MEDIUM_LOW")
    out.append("    note: TODO_LLM_short_description")
    out.append("")
    out.append("caveats:")
    out.append("  - severity: TODO_LLM_HIGH_MEDIUM_LOW")
    out.append("    message: TODO_LLM_assessment_or_warning")
    out.append("")
    out.append("sources:")
    out.append(f"  snapshot: {y_str(f'Portfolio/snapshots/{snapshot_id}')}")
    out.append("  macro_input: TODO_LLM_macro_filename_or_null")
    out.append("  moex_quotes: TODO_LLM_provenance_text")

    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--snapshot", required=True, type=Path, help="Path to portfolio-{date}.json")
    parser.add_argument("--output", required=True, type=Path, help="Output YAML stub path")
    parser.add_argument("--today", default=None, help="Override today's date (ISO YYYY-MM-DD) for tests")
    parser.add_argument("--horizons", default=None,
                        help="Скользящий режим: список горизонтов в месяцах через запятую (default: 6,12,24)")
    parser.add_argument("--anchor-dates", default=None,
                        help="Якорный режим (§11.6): даты-цели через запятую (YYYY-MM-DD). "
                             "Переопределяет --horizons: N вычисляется как месяцы до цели.")
    parser.add_argument("--primary-horizon", type=int, default=DEFAULT_PRIMARY_HORIZON,
                        help="Горизонт, к которому привязан advisor_verdict (default: 12)")
    parser.add_argument("--sector-overrides", default=None, type=Path,
                        help="Путь к sector-overrides.yaml (Claude-Memory/sector-overrides.yaml). "
                             "Если не передан — только ie_model.sector и holdings[].sector.")
    args = parser.parse_args()

    snapshot = load_snapshot(args.snapshot)
    today_iso = args.today or date_t.today().isoformat()
    anchor = parse_anchor_dates(args.anchor_dates)
    horizons = None if anchor else parse_horizons(args.horizons)
    overrides = load_sector_overrides(args.sector_overrides)
    stub = build_stub(snapshot, today_iso=today_iso, horizons=horizons,
                      primary_horizon=args.primary_horizon, anchor_dates=anchor,
                      sector_overrides=overrides or None)

    args.output.write_text(stub, encoding="utf-8")
    # Сводка для caller (LLM в SKILL.md прочитает stdout)
    # Счётчики — тем же отбором, что стаб (select_stocks), а не повтором фильтра.
    active, skipped = select_stocks(snapshot)
    summary = {
        "output": str(args.output),
        "snapshot": str(args.snapshot),
        "snapshot_date": snapshot.get("as_of_date"),
        "stocks_written": len(active),
        "skipped_frozen_us": len(skipped["frozen_us"]),
        "skipped_blocked": len(skipped["blocked"]),
        "skipped_no_moex_price": skipped["no_moex_price"],
        "skipped_money_market": skipped["money_market"],
    }
    sys.stdout.write(json.dumps(summary, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
