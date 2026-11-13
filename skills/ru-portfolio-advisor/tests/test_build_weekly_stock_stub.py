#!/usr/bin/env python3
"""Тесты для skills/ru-portfolio-advisor/scripts/build_weekly_stock_stub.py.

Запуск: python3 skills/ru-portfolio-advisor/tests/test_build_weekly_stock_stub.py
Возвращает exit 0 при успехе, 1 при провале хотя бы одной проверки.

Зависимости: stdlib only (json, subprocess, tempfile). Парсит YAML минимальным
heuristic-парсером (тот же подход, что в самом скрипте — без PyYAML).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "skills/ru-portfolio-advisor/scripts/build_weekly_stock_stub.py"


def make_fake_snapshot() -> dict:
    """Минимальный snapshot v2 с 4 stocks: 2 active RU + 1 money-market + 1 frozen US."""
    return {
        "schema_version": "2.0",
        "as_of_date": "2026-05-12",
        "generated_at": "2026-05-12T10:00:00Z",
        "holdings": [
            {
                "ticker": "SBER", "name": "Сбербанк",
                "asset_type": "stock", "qty": 1800.0,
                "avg_cost_rub": 324.14, "current_price": 324.14,
                "current_price_source": "moex_iss",
                "value_rub": 1750356.0, "currency": "RUB",
                "account": "main", "is_blocked": False,
            },
            {
                "ticker": "T", "name": "Т-Технологии",
                "asset_type": "stock", "qty": 1010.0,
                "avg_cost_rub": 300.0, "current_price": 311.52,
                "current_price_source": "moex_iss",
                "value_rub": 943905.0, "currency": "RUB",
                "account": "main", "is_blocked": False,
            },
            {
                # asset_type=fund — как в снапшотах 2026-07-08+ (фикс классификации);
                # MM-гейт обязан включить TMON в per_stock независимо от типа.
                "ticker": "TMON", "name": "Тинькофф Money Market",
                "asset_type": "fund", "qty": 1743.0,
                "avg_cost_rub": 157.0, "current_price": 157.08,
                "current_price_source": "moex_iss",
                "value_rub": 821370.0, "currency": "RUB",
                "account": "main", "is_blocked": False,
            },
            {
                "ticker": "BAC", "name": "Bank of America",
                "asset_type": "stock", "qty": 9.0,
                "avg_cost_rub": 3065.96, "current_price": 3065.96,
                "current_price_source": "cost_basis",
                "value_rub": 27593.61, "currency": "RUB",
                "account": "main", "is_blocked": False,
            },
            {
                # Заморожена в феврале 2022: is_blocked вместе с cost_basis — как все 32 такие
                # бумаги живого снапшота (RPA-21: раньше выпадала из счётчика skipped_frozen_us).
                "ticker": "KO", "name": "Coca-Cola",
                "asset_type": "stock", "qty": 5.0,
                "current_price_source": "cost_basis",
                "value_rub": 0.0, "currency": "RUB",
                "account": "main", "is_blocked": True,
            },
            # Bond — не должен попасть в per_stock
            {
                "ticker": "RU000A105KU0", "name": "ГазКЗ-29Д",
                "asset_type": "bond", "qty": 9.0,
                "value_rub": 1795770.0, "account": "main", "is_blocked": False,
                "current_price_source": "moex_iss",
            },
        ],
        "cash": {"total_rub": 4500000.0},
        "returns": {
            "total": {"xirr": 0.0166, "pnl_rub": 1774036.35},
            "restricted": {"xirr": 0.0791},
            "by_type": {
                "stock": {"xirr": 0.0575, "pnl_rub": 1774036.35, "roi": 0.0429},
                "bond": {"xirr": 0.0936, "pnl_rub": 3919632.78},
            },
        },
        "per_instrument_xirr": {
            "SBER": {"xirr": 0.2383, "pnl_rub": 655524.99, "qty_now": 1800.0},
            "T": {"xirr": -0.1, "pnl_rub": -50000.0, "qty_now": 1010.0},
            "TMON": {"xirr": 0.15, "pnl_rub": 12000.0, "qty_now": 1743.0},
        },
        "ie_model": {
            "model_total_pct": 100.0,
            "positions": [
                {"ticker": "SBER", "name": "Сбербанк", "sector": "Финансовый",
                 "target_share_pct": 6.0, "active_in_model": True},
                {"ticker": "T", "name": "Т-Технологии", "sector": "IT",
                 "target_share_pct": 6.0, "active_in_model": True},
            ],
        },
        "ie_actual": {
            "per_ticker": {
                "SBER": {
                    "ie_new_pct": 6.0, "ie_old_pct": 6.0, "ie_delta_pct": 0.0,
                    "real_share_pct": 12.0015, "planned_share_pct": 10.0,
                    "user_plan": None, "user_status": None,
                    "user_note_ie": None,
                    "user_note_ai": "Держать",
                },
                "T": {
                    "ie_new_pct": 6.0, "ie_old_pct": 6.0, "ie_delta_pct": 0.0,
                    "real_share_pct": 6.4731,
                    "user_plan": "TRIM", "user_status": None,
                    "user_note_ai": "Сократить на 20% при росте выше 350",
                },
                # Доля MM-фонда в книге акций — как в снапшотах с балансом Numbers.
                "TMON": {"real_share_pct": 5.7716},
            },
        },
        "ie_summary": {
            "tickers_in_portfolio_active": 22,
            "tickers_in_ie_model": 19,
            "tickers_in_both": 18,
            "ie_changes_count": 0,
        },
        "balance_summary": {
            "total_current_rub_excl_iis": 15000000.0,
            "total_current_rub_incl_iis": 16500000.0,
            "iis_balance_rub": 1500000.0,
            "by_account": {
                "main": {
                    "total_rub": 15000000.0,
                    "stocks_rub": 3600000.0,
                    "bonds_rub": 6000000.0,
                    "funds_rub": 900000.0,
                    "cash_rub": 4500000.0,
                },
            },
            "goals_overall": [
                {"Тип": "Акции", "Доля": 0.4},
                {"Тип": "Облигация", "Доля": 0.5},
            ],
        },
    }


def parse_yaml_min(text: str) -> dict:
    """Минимальный YAML-парсер (только то, что нужно для тестов).

    Поддерживает: nested dicts, scalar values (int/float/bool/null/string),
    quoted strings, простые списки `- item`.
    НЕ поддерживает: anchors, multi-line strings (|), flow style ([1,2,3]).
    """
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except ImportError:
        pass
    # Fallback heuristic parser
    return _parse_yaml_fallback(text)


def _parse_yaml_fallback(text: str) -> dict:
    """Stdlib-only YAML fallback. Используется если PyYAML недоступен."""
    # Достаточно для smoke-проверок в тестах, не для production.
    result: dict = {}
    stack: list[tuple[int, dict]] = [(-1, result)]
    lines = text.split("\n")
    for raw in lines:
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        # Strip inline comments (not in quoted strings — naive)
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        # Pop stack to match indent
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        # List item
        m_li = re.match(r"^-\s+(.+)$", stripped)
        if m_li:
            # Parent must already be a list; convert if it's a dict expecting a list value
            continue  # tests don't depend on list parsing for now
        # key: value
        m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_\-]*):\s*(.*)$", stripped)
        if not m:
            continue
        key, val = m.group(1), m.group(2).rstrip()
        if val == "":
            # Nested
            sub: dict = {}
            if isinstance(parent, dict):
                parent[key] = sub
            stack.append((indent, sub))
        else:
            # Strip inline `# comment`
            if "#" in val and not (val.startswith('"') or val.startswith("'")):
                val = val.split("#", 1)[0].rstrip()
            parsed_val: object
            if val.startswith('"') and val.endswith('"'):
                parsed_val = val[1:-1]
            elif val == "true":
                parsed_val = True
            elif val == "false":
                parsed_val = False
            elif val == "null":
                parsed_val = None
            else:
                try:
                    parsed_val = int(val) if val.lstrip("-").isdigit() else float(val)
                except ValueError:
                    parsed_val = val
            if isinstance(parent, dict):
                parent[key] = parsed_val
    return result


def run_script(snapshot_path: Path, output_path: Path, today: str = "2026-05-12",
               extra: list[str] | None = None) -> tuple[int, str]:
    """Запустить скрипт, вернуть (exit_code, stdout)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT),
         "--snapshot", str(snapshot_path),
         "--output", str(output_path),
         "--today", today, *(extra or [])],
        capture_output=True, text=True,
    )
    return result.returncode, result.stdout + result.stderr


# ============================================================
# Тесты
# ============================================================

def check(label: str, cond: bool, detail: str = "") -> bool:
    if cond:
        print(f"  ✓ {label}")
        return True
    print(f"  ✗ {label}{(' — ' + detail) if detail else ''}")
    return False


def test_smoke_run():
    """Скрипт запускается, выходит с кодом 0, генерирует файл."""
    print("\n[test_smoke_run]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        code, log = run_script(snap, out)
        if not check("exit code == 0", code == 0, log[:200]):
            return False
        if not check("output file exists", out.exists()):
            return False
        text = out.read_text()
        if not check("output non-empty", len(text) > 500):
            return False
    return True


def test_top_level_fields():
    """Top-level поля v2: schema_version=2 (int), review_date в кавычках (str)."""
    print("\n[test_top_level_fields]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        d = parse_yaml_min(text)
        ok = True
        ok &= check("schema_version == 2", d.get("schema_version") == 2)
        ok &= check("schema_version is int (not '2')", isinstance(d.get("schema_version"), int) and not isinstance(d.get("schema_version"), bool))
        ok &= check("type == weekly-stocks-review", d.get("type") == "weekly-stocks-review")
        ok &= check("review_date == '2026-05-12'", d.get("review_date") == "2026-05-12")
        # В тексте YAML — review_date в кавычках
        ok &= check('review_date в кавычках в файле', 'review_date: "2026-05-12"' in text)
        ok &= check("primary_horizon == 12", d.get("primary_horizon") == 12)
        ok &= check("snapshot_id matches", d.get("snapshot_id") == "portfolio-2026-05-12.json")
        return ok


def test_review_date_is_run_date_when_snapshot_older():
    """Обзор 26.10.2026 шёл по снапшоту 23.10: review_date — день прогона, snapshot_* — снапшота;
    горизонты считаются от даты обзора. Раньше снапшота дата обзора не бывает."""
    print("\n[test_review_date_is_run_date_when_snapshot_older]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))   # as_of_date 2026-05-12
        run_script(snap, out, today="2026-05-15")
        d = parse_yaml_min(out.read_text())
        ok = True
        ok &= check("review_date == '2026-05-15'", d.get("review_date") == "2026-05-15")
        ok &= check("snapshot_date == '2026-05-12'", d.get("snapshot_date") == "2026-05-12")
        ok &= check("snapshot_id по снапшоту", d.get("snapshot_id") == "portfolio-2026-05-12.json")
        run_script(snap, out, today="2026-05-10")            # «сегодня» раньше снапшота
        d = parse_yaml_min(out.read_text())
        ok &= check("не раньше снапшота", d.get("review_date") == "2026-05-12")
        return ok


def test_horizon_v2_fields():
    """v2 default 6-12-24: horizons список + horizon_ends (конец месяца) + primary_horizon."""
    print("\n[test_horizon_v2_fields]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        run_script(snap, out)  # today=2026-05-12 → review_date=2026-05-12, default [6,12,24]
        text = out.read_text()
        ok = True
        ok &= check("horizons: [6, 12, 24]", "horizons: [6, 12, 24]" in text)
        # review_date 2026-05-12 + 6 мес = конец 2026-11 = 2026-11-30
        ok &= check("h6 → 2026-11-30 (конец месяца)", 'h6: "2026-11-30"' in text)
        # +12 мес = конец 2027-05 = 2027-05-31
        ok &= check("h12 → 2027-05-31", 'h12: "2027-05-31"' in text)
        # +24 мес = конец 2028-05 = 2028-05-31
        ok &= check("h24 → 2028-05-31", 'h24: "2028-05-31"' in text)
        ok &= check("primary_horizon: 12", re.search(r"^primary_horizon: 12\b", text, re.MULTILINE) is not None)
        return ok


def test_no_v1_horizon_fields():
    """v2 НЕ содержит v1-полей horizon_months / horizon_end / in_horizon."""
    print("\n[test_no_v1_horizon_fields]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        ok = True
        ok &= check("нет horizon_months", "horizon_months" not in text)
        # horizon_end: (v1) ≠ horizon_ends: (v2) — проверяем точное v1-поле
        ok &= check("нет horizon_end: (v1)", re.search(r"^horizon_end:", text, re.MULTILINE) is None)
        ok &= check("нет in_horizon (catalyst)", "in_horizon" not in text)
        ok &= check("date_window остался в catalyst", "date_window: TODO_LLM" in text)
        return ok


def test_custom_horizons():
    """--horizons 6,18 --primary-horizon 18 → horizon_ends c h6/h18."""
    print("\n[test_custom_horizons]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        code, log = run_script(snap, out, extra=["--horizons", "6,18", "--primary-horizon", "18"])
        if not check("exit 0", code == 0, log[:200]):
            return False
        text = out.read_text()
        ok = True
        ok &= check("horizons: [6, 18]", "horizons: [6, 18]" in text)
        # 2026-05-12 + 6 = конец 2026-11 = 2026-11-30
        ok &= check("h6 → 2026-11-30", 'h6: "2026-11-30"' in text)
        # +18 = конец 2027-11 = 2027-11-30
        ok &= check("h18 → 2027-11-30", 'h18: "2027-11-30"' in text)
        ok &= check("primary_horizon: 18", re.search(r"^primary_horizon: 18\b", text, re.MULTILINE) is not None)
        ok &= check("нет h12/h20/h36", "h12:" not in text and "h20:" not in text)
        return ok


def test_anchor_dates_mode():
    """--anchor-dates: N = месяцы до цели; на поздней дате обзора N меньше (срок сжимается)."""
    print("\n[test_anchor_dates_mode]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        snap.write_text(json.dumps(make_fake_snapshot()))
        # Прогон 1: review_date=2026-05-12, цель 2027-06-30 → N = 13 мес
        out1 = Path(td) / "stub1.yaml"
        code1, log1 = run_script(snap, out1, today="2026-05-12",
                                 extra=["--anchor-dates", "2027-06-30"])
        if not check("прогон 1 exit 0", code1 == 0, log1[:200]):
            return False
        t1 = out1.read_text()
        ok = True
        ok &= check("прогон 1: h13 (13 мес до цели)", "horizons: [13]" in t1)
        ok &= check("прогон 1: horizon_ends.h13 = 2027-06-30", 'h13: "2027-06-30"' in t1)
        ok &= check("прогон 1: primary_horizon 13", re.search(r"^primary_horizon: 13\b", t1, re.MULTILINE) is not None)
        # Прогон 2: тот же snapshot, но review_date 2026-09-12 (3 мес позже) → N=9 к той же цели
        # Подменяем as_of через отдельный snapshot
        snap2 = Path(td) / "snap2.json"
        s2 = make_fake_snapshot()
        s2["as_of_date"] = "2026-09-12"
        snap2.write_text(json.dumps(s2))
        out2 = Path(td) / "stub2.yaml"
        code2, log2 = run_script(snap2, out2, today="2026-09-12",
                                 extra=["--anchor-dates", "2027-06-30"])
        if not check("прогон 2 exit 0", code2 == 0, log2[:200]):
            return False
        t2 = out2.read_text()
        ok &= check("прогон 2: h9 (срок сжался до 9 мес)", "horizons: [9]" in t2)
        ok &= check("прогон 2: та же дата-цель 2027-06-30", 'h9: "2027-06-30"' in t2)
        return ok


def test_anchor_date_in_past_rejected():
    """Якорная дата в прошлом → exit != 0."""
    print("\n[test_anchor_date_in_past_rejected]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        code, log = run_script(snap, out, extra=["--anchor-dates", "2025-01-31"])
        return check("exit != 0 для даты в прошлом", code != 0, log[:200])


def test_per_stock_population():
    """per_stock содержит SBER, T, TMON; не содержит BAC и RU000A105KU0 (bond)."""
    print("\n[test_per_stock_population]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        # Используем regex т.к. fallback YAML-парсер не парсит per_stock корректно
        # (там вложенные структуры, списки катализаторов)
        tickers = re.findall(r"^  ([A-Z][A-Z0-9]*):\s*$", text, re.MULTILINE)
        ok = True
        ok &= check("SBER присутствует", "SBER" in tickers)
        ok &= check("T присутствует", "T" in tickers)
        ok &= check("TMON присутствует (money-market)", "TMON" in tickers)
        ok &= check("BAC отсутствует (frozen US, cost_basis)", "BAC" not in tickers)
        ok &= check("RU000A105KU0 отсутствует (это bond)", "RU000A105KU0" not in tickers)
        ok &= check("Всего 3 stock-тикера", len(tickers) == 3, f"got {tickers}")
        return ok


def test_weight_real_pct_from_ie_actual():
    """weight_real_pct = ie_actual.real_share_pct (каноническая интерпретация)."""
    print("\n[test_weight_real_pct_from_ie_actual]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        ok = True
        # SBER: weight_real_pct: 12.0015
        m = re.search(r"^  SBER:\n((?:    .+\n)+)", text, re.MULTILINE)
        if not check("SBER block found", bool(m)):
            return False
        sber_block = m.group(1)
        ok &= check("SBER.weight_real_pct == 12.0015",
                    "weight_real_pct: 12.0015" in sber_block)
        ok &= check("SBER.weight_ie_target_pct == 6.00",
                    "weight_ie_target_pct: 6.00" in sber_block)
        ok &= check("SBER.weight_divergence_pp == 6.0015",
                    "weight_divergence_pp: 6.0015" in sber_block)
        ok &= check("SBER.on_iis == false",
                    "on_iis: false" in sber_block)
        return ok


def test_weight_user_planned_from_ie_actual_planned_share():
    """RPA-19: weight_user_planned_pct = ie_actual.per_ticker[t].planned_share_pct (PRIMARY)."""
    print("\n[test_weight_user_planned_from_ie_actual_planned_share]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        m = re.search(r"^  SBER:\n((?:    .+\n)+)", text, re.MULTILINE)
        if not check("SBER block found", bool(m)):
            return False
        sber_block = m.group(1)
        # SBER.planned_share_pct == 10.0 в фикстуре ie_actual
        return check("SBER.weight_user_planned_pct == 10.0000",
                    "weight_user_planned_pct: 10.0000" in sber_block)


def test_weight_divergence_vs_planned_is_real_minus_planned():
    """RPA-19: weight_divergence_vs_planned_pp = weight_real_pct − weight_user_planned_pct."""
    print("\n[test_weight_divergence_vs_planned_is_real_minus_planned]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        m = re.search(r"^  SBER:\n((?:    .+\n)+)", text, re.MULTILINE)
        if not check("SBER block found", bool(m)):
            return False
        sber_block = m.group(1)
        # 12.0015 - 10.0 = 2.0015
        return check("SBER.weight_divergence_vs_planned_pp == 2.0015",
                    "weight_divergence_vs_planned_pp: 2.0015" in sber_block)


def test_deprecated_alias_equals_weight_divergence_vs_ie():
    """RPA-19: deprecated weight_divergence_pp равен weight_divergence_vs_ie_pp (SBER и T)."""
    print("\n[test_deprecated_alias_equals_weight_divergence_vs_ie]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        ok = True
        for ticker, expected in (("SBER", "6.0015"), ("T", "0.4731")):
            m = re.search(rf"^  {ticker}:\n((?:    .+\n)+)", text, re.MULTILINE)
            if not check(f"{ticker} block found", bool(m)):
                ok = False
                continue
            block = m.group(1)
            ok &= check(f"{ticker}.weight_divergence_vs_ie_pp == {expected}",
                        f"weight_divergence_vs_ie_pp: {expected}" in block)
            ok &= check(f"{ticker}.weight_divergence_pp == {expected} (deprecated алиас == vs_ie)",
                        f"weight_divergence_pp: {expected}" in block)
        return ok


def test_ticker_without_plan_still_has_ie_divergence():
    """RPA-19: T без planned_share_pct в ie_actual → weight_user_planned_pct и
    weight_divergence_vs_planned_pp оба null; weight_divergence_vs_ie_pp остаётся
    числом (T есть в модели IE) — обратный случай к бумаге вне модели IE."""
    print("\n[test_ticker_without_plan_still_has_ie_divergence]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        m = re.search(r"^  T:\n((?:    .+\n)+)", text, re.MULTILINE)
        if not check("T block found", bool(m)):
            return False
        block = m.group(1)
        ok = True
        ok &= check("T.weight_user_planned_pct == null (плана нет в ie_actual)",
                    "weight_user_planned_pct: null" in block)
        ok &= check("T.weight_divergence_vs_planned_pp == null (нет плана)",
                    "weight_divergence_vs_planned_pp: null" in block)
        ok &= check("T.weight_divergence_vs_ie_pp == 0.4731 (T есть в модели IE)",
                    "weight_divergence_vs_ie_pp: 0.4731" in block)
        return ok


def test_ticker_outside_ie_model_with_plan():
    """RPA-19: тикер вне модели IE (не в ie_model.positions), но план владельца задан
    в ie_actual — weight_ie_target_pct/weight_divergence_vs_ie_pp/deprecated-алиас
    null, а weight_divergence_vs_planned_pp остаётся числом. До 20.08.2026 такая
    бумага теряла расхождение целиком (схема несла только цель IE)."""
    print("\n[test_ticker_outside_ie_model_with_plan]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        s = make_fake_snapshot()
        s["holdings"].append({
            "ticker": "FLOT", "name": "Совкомфлот",
            "asset_type": "stock", "qty": 1000.0,
            "current_price": 100.0, "current_price_source": "moex_iss",
            "value_rub": 300000.0, "currency": "RUB",
            "account": "main", "is_blocked": False,
        })
        # FLOT: реальная доля + план владельца в ie_actual, но НЕ в ie_model.positions
        s["ie_actual"]["per_ticker"]["FLOT"] = {
            "real_share_pct": 3.5, "planned_share_pct": 4.0,
            "user_plan": None, "user_status": None,
        }
        snap.write_text(json.dumps(s))
        code, log = run_script(snap, out)
        if not check("exit 0", code == 0, log[:200]):
            return False
        text = out.read_text()
        m = re.search(r"^  FLOT:\n((?:    .+\n)+)", text, re.MULTILINE)
        if not check("FLOT block found", bool(m)):
            return False
        block = m.group(1)
        ok = True
        ok &= check("FLOT.weight_user_planned_pct == 4.0000",
                    "weight_user_planned_pct: 4.0000" in block)
        ok &= check("FLOT.weight_divergence_vs_planned_pp == -0.5000 (3.5 − 4.0)",
                    "weight_divergence_vs_planned_pp: -0.5000" in block)
        ok &= check("FLOT.weight_ie_target_pct == null (вне модели IE)",
                    "weight_ie_target_pct: null" in block)
        ok &= check("FLOT.weight_divergence_vs_ie_pp == null (вне модели IE)",
                    "weight_divergence_vs_ie_pp: null" in block)
        ok &= check("FLOT.weight_divergence_pp == null (deprecated алиас, вне модели IE)",
                    "weight_divergence_pp: null" in block)
        return ok


def test_canonical_field_names_no_drift():
    """В стабе только канонические имена; нет share_actual_pct, ie_share_pct, delta_pct, catalysts."""
    print("\n[test_canonical_field_names_no_drift]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        ok = True
        # share_actual_pct в per_stock — drift; portfolio_summary.stocks_share_actual_pct — OK
        ok &= check("нет 'share_actual_pct:' в per_stock entry (drift)",
                    not re.search(r"^    share_actual_pct:", text, re.MULTILINE))
        ok &= check("нет 'ie_share_pct:' ключа",
                    "ie_share_pct:" not in text)
        # delta_pct: специфично для stress YAML; в stock YAML не должно быть
        ok &= check("нет 'delta_pct:' ключа (это stress-поле)",
                    not re.search(r"^\s+delta_pct:", text, re.MULTILINE))
        # catalysts: (с «s») — drift; должно быть catalyst:
        ok &= check("нет 'catalysts:' ключа (drift; должно быть 'catalyst:')",
                    "catalysts:" not in text)
        ok &= check("есть 'catalyst:' ключ (правильное имя)",
                    "catalyst:" in text)
        return ok


def test_todo_llm_placeholders_present():
    """Аналитические поля имеют TODO_LLM плейсхолдеры."""
    print("\n[test_todo_llm_placeholders_present]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        ok = True
        # Каждый из аналитических ключей должен быть с TODO_LLM
        ok &= check("fundamental_score: TODO_LLM",
                    "fundamental_score: TODO_LLM" in text)
        ok &= check("advisor_verdict: TODO_LLM",
                    "advisor_verdict: TODO_LLM" in text)
        ok &= check("advisor_verdict_confidence: TODO_LLM",
                    "advisor_verdict_confidence: TODO_LLM" in text)
        ok &= check("advisor_verdict_basis: TODO_LLM",
                    "advisor_verdict_basis: TODO_LLM" in text)
        # R28: приоритет ставит stamp-report, не модель; копии гейта в стабе нет
        ok &= check("verification_priority: null (ставит штамп), не TODO_LLM",
                    "verification_priority: null" in text and "verification_priority: TODO_LLM" not in text)
        ok &= check("gate_status_snapshot в стабе нет", "gate_status_snapshot" not in text)
        ok &= check("div_yield_12m_pct содержит TODO_LLM",
                    "div_yield_12m_pct:" in text and "TODO_LLM_float_pct" in text)
        ok &= check("catalyst.trigger: TODO_LLM",
                    "trigger: TODO_LLM" in text)
        ok &= check("catalyst.p: TODO_LLM",
                    re.search(r"\bp: TODO_LLM", text) is not None)
        ok &= check("catalyst.source_quality: TODO_LLM",
                    "source_quality: TODO_LLM" in text)
        return ok


def test_money_market_marker():
    """TMON помечен asset_type_actual: fund_money_market и sector: cash-equivalent."""
    print("\n[test_money_market_marker]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        m = re.search(r"^  TMON:\n((?:    .+\n)+)", text, re.MULTILINE)
        if not check("TMON block found", bool(m)):
            return False
        block = m.group(1)
        ok = True
        ok &= check('TMON.sector == "cash-equivalent"',
                    'sector: "cash-equivalent"' in block)
        ok &= check("TMON.asset_type_actual == fund_money_market",
                    "asset_type_actual: fund_money_market" in block)
        return ok


def test_summary_counts_match_written_blocks():
    """summary.stocks_written == число блоков per_stock.

    Дефект (найден 20.08.2026): счётчик пересчитывал holdings фильтром
    `asset_type != "stock" → continue`, а money-market фонды со снапшотов 2026-07-08+
    несут asset_type == "fund" и при этом пишутся в per_stock. TMON/TPAY попадали в
    обзор и молча выпадали из счётчика — на живом снапшоте 19.08 он показывал 21 при
    23 записанных бумагах.
    """
    print("\n[test_summary_counts_match_written_blocks]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        code, stdout = run_script(snap, out)
        if not check("exit 0", code == 0, stdout):
            return False
        summary = json.loads([ln for ln in stdout.splitlines() if ln.startswith("{")][-1])
        blocks = len(re.findall(r"^  [A-Z0-9.]+:$", out.read_text(), re.MULTILINE))
        ok = check(f"stocks_written == блоков per_stock ({summary['stocks_written']} == {blocks})",
                   summary["stocks_written"] == blocks,
                   f"summary={summary}")
        ok &= check("TMON учтён в счётчике (asset_type=fund, но пишется в per_stock)",
                    "TMON" in out.read_text())
        return ok


def _summary(stdout: str) -> dict:
    return json.loads([ln for ln in stdout.splitlines() if ln.startswith("{")][-1])


def test_frozen_us_counted_even_when_blocked():
    """RPA-21: замороженные (cost_basis) считаются в skipped_frozen_us и с is_blocked.

    Дефект: проверка is_blocked стояла раньше проверки цены, а у всех 32 замороженных
    бумаг живого снапшота is_blocked: true — сводка печатала «пропущено 0».
    """
    print("\n[test_frozen_us_counted_even_when_blocked]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        code, stdout = run_script(snap, out)
        if not check("exit 0", code == 0, stdout):
            return False
        summary = _summary(stdout)
        text = out.read_text()
        ok = check("skipped_frozen_us == 2 (BAC + заблокированный KO)",
                   summary.get("skipped_frozen_us") == 2, f"summary={summary}")
        ok &= check("skipped_blocked == 0", summary.get("skipped_blocked") == 0, f"summary={summary}")
        ok &= check("KO и BAC не в per_stock", "\n  KO:" not in text and "\n  BAC:" not in text)
        return ok


def test_money_market_without_share_skipped():
    """RPA-21: MM-фонд без доли в книге акций не пишется в per_stock (null блокирует сохранение обзора)."""
    print("\n[test_money_market_without_share_skipped]")
    with tempfile.TemporaryDirectory() as td:
        snap_d = make_fake_snapshot()
        del snap_d["ie_actual"]["per_ticker"]["TMON"]
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(snap_d))
        code, stdout = run_script(snap, out)
        if not check("exit 0", code == 0, stdout):
            return False
        summary = _summary(stdout)
        text = out.read_text()
        blocks = len(re.findall(r"^  [A-Z0-9.]+:$", text, re.MULTILINE))
        ok = check("TMON не в per_stock", "\n  TMON:" not in text)
        ok &= check("skipped_money_market == ['TMON']",
                    summary.get("skipped_money_market") == ["TMON"], f"summary={summary}")
        ok &= check(f"stocks_written == блоков ({summary.get('stocks_written')} == {blocks})",
                    summary.get("stocks_written") == blocks)
        ok &= check("нет weight_real_pct: null", "weight_real_pct: null" not in text)
        return ok


def test_ie_divergence_intent():
    """T имеет user_plan: TRIM → ie_divergence_intentional: true с basis из user_note_ai."""
    print("\n[test_ie_divergence_intent]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        m = re.search(r"^  T:\n((?:    .+\n)+)", text, re.MULTILINE)
        if not check("T block found", bool(m)):
            return False
        block = m.group(1)
        ok = True
        ok &= check("T.ie_divergence_intentional == true",
                    "ie_divergence_intentional: true" in block)
        ok &= check("T.ie_divergence_basis содержит user_note_ai",
                    "Сократить" in block)
        return ok


def test_yaml_parses_via_pyyaml_if_available():
    """Файл парсится через PyYAML без ошибок (если установлен)."""
    print("\n[test_yaml_parses_via_pyyaml_if_available]")
    try:
        import yaml  # type: ignore
    except ImportError:
        print("  ⊘ PyYAML не установлен — skip")
        return True
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        try:
            d = yaml.safe_load(text)
        except yaml.YAMLError as e:
            print(f"  ✗ YAML parse error: {e}")
            return False
        ok = True
        ok &= check("parsed.schema_version == 2", d.get("schema_version") == 2)
        ok &= check("parsed.review_date == '2026-05-12'", d.get("review_date") == "2026-05-12")
        ok &= check("parsed.horizons == [6,12,24]", d.get("horizons") == [6, 12, 24])
        ok &= check("parsed.horizon_ends.h12 == 2027-05-31",
                    (d.get("horizon_ends") or {}).get("h12") == "2027-05-31")
        ok &= check("per_stock has 3 entries", len(d.get("per_stock", {})) == 3)
        sber = d.get("per_stock", {}).get("SBER", {})
        ok &= check("SBER.weight_real_pct == 12.0015", sber.get("weight_real_pct") == 12.0015)
        return ok


def test_portfolio_summary_numbers():
    """portfolio_summary имеет корректные числа из balance_summary."""
    print("\n[test_portfolio_summary_numbers]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        ok = True
        ok &= check("total_excl_iis_rub: 15000000",
                    "total_excl_iis_rub: 15000000" in text)
        # stocks_rub = 3600000, total_excl_iis = 15000000 → 24%
        ok &= check("stocks_share_actual_pct: 24.00",
                    "stocks_share_actual_pct: 24.00" in text)
        ok &= check("stocks_share_target_pct: 40.00",
                    "stocks_share_target_pct: 40.00" in text)
        # undershoot = 24 - 40 = -16
        ok &= check("stocks_undershoot_pct: -16.00",
                    "stocks_undershoot_pct: -16.00" in text)
        return ok


def test_invalid_schema_version_rejected():
    """Snapshot с schema_version != 2.x → exit 1."""
    print("\n[test_invalid_schema_version_rejected]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        bad = make_fake_snapshot()
        bad["schema_version"] = "1.0"
        snap.write_text(json.dumps(bad))
        code, log = run_script(snap, out)
        return check("exit code == 1 для v1.0 snapshot", code == 1, log[:200])


def test_missing_snapshot_rejected():
    """Несуществующий snapshot → exit 1."""
    print("\n[test_missing_snapshot_rejected]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "does_not_exist.json"
        out = Path(td) / "stub.yaml"
        code, log = run_script(snap, out)
        return check("exit code == 1", code == 1)


def make_sector_overrides_yaml(ticker: str, sector: str, sector_ru: str | None = None) -> str:
    """Минимальный sector-overrides.yaml для теста."""
    ru_line = f'    sector_ru: "{sector_ru}"\n' if sector_ru else ""
    return (
        f"version: 1\nlast_updated: '2026-06-11'\noverrides:\n"
        f"  - ticker: {ticker}\n    sector: {sector}\n{ru_line}    note: test\n"
    )


def test_sector_overrides_fallback_chain():
    """A2: fallback-цепочка ie_model → snapshot.holdings → overrides → unknown."""
    print("\n[test_sector_overrides_fallback_chain]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        overrides = Path(td) / "sector-overrides.yaml"

        # SBER: ie_model.sector = 'Финансовый' → ie_model wins
        # T: ie_model.sector = 'IT' → ie_model wins
        # TMON: money_market → cash-equivalent (not overridden)
        # Add NVTK (no ie_model, has override → overrides win)
        s = make_fake_snapshot()
        s["holdings"].append({
            "ticker": "NVTK", "name": "НОВАТЭК",
            "asset_type": "stock", "qty": 100.0,
            "current_price_source": "moex_iss",
            "value_rub": 300000.0, "account": "main", "is_blocked": False,
        })
        # VTBR: no ie_model, has sector in snapshot holding (snapshot wins over unknown)
        s["holdings"].append({
            "ticker": "VTBR", "name": "ВТБ",
            "asset_type": "stock", "qty": 500.0,
            "current_price_source": "moex_iss",
            "value_rub": 50000.0, "account": "main", "is_blocked": False,
            "sector": "banks_finance",
        })
        snap.write_text(json.dumps(s))
        overrides.write_text(make_sector_overrides_yaml("NVTK", "oil_gas"))
        code, log = run_script(snap, out, extra=["--sector-overrides", str(overrides)])
        if not check("exit 0", code == 0, log[:200]):
            return False
        text = out.read_text()
        ok = True
        # NVTK gets sector from overrides (no ie_model entry)
        nvtk_block = re.search(r"NVTK:.*?(?=\n  \w|\Z)", text, re.DOTALL)
        ok &= check("NVTK sector=oil_gas (из overrides)",
                    nvtk_block is not None and
                    re.search(r'sector:.*oil_gas', nvtk_block.group() or "") is not None)
        # VTBR gets sector from snapshot.holdings (no ie_model, no override)
        vtbr_block = re.search(r"VTBR:.*?(?=\n  \w|\Z)", text, re.DOTALL)
        ok &= check("VTBR sector=banks_finance (из holdings)",
                    vtbr_block is not None and
                    re.search(r'sector:.*banks_finance', vtbr_block.group() or "") is not None)
        # SBER: ie_model wins (не unknown)
        sber_block = re.search(r"SBER:.*?(?=\n  \w|\Z)", text, re.DOTALL)
        ok &= check("SBER sector не unknown (из ie_model)",
                    sber_block is not None and
                    re.search(r'sector:\s*"?unknown"?', sber_block.group() or "") is None and
                    re.search(r'sector:\s*\S', sber_block.group() or "") is not None)
        return ok


def test_sector_ru_and_holdings_priority():
    """PDL-I (2026-08-27): sector — ВСЕГДА машинный ключ (даже когда overrides несёт только
    sector_ru); sector_ru — отдельное поле отображаемого ярлыка. holdings побеждает overrides
    для sector (как раньше, включая устаревший текст напрямую из старого снапшота — backward
    compat); для sector_ru используется holdings.sector_ru, а без него — overrides.sector_ru."""
    print("\n[test_sector_ru_and_holdings_priority]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        overrides = Path(td) / "sector-overrides.yaml"

        s = make_fake_snapshot()
        # NVTK: нет ie_model, нет sector в holdings → sector и sector_ru оба из overrides
        s["holdings"].append({
            "ticker": "NVTK", "name": "НОВАТЭК",
            "asset_type": "stock", "qty": 100.0,
            "current_price_source": "moex_iss",
            "value_rub": 300000.0, "account": "main", "is_blocked": False,
        })
        # VTBR: sector в holdings — устаревший русский текст (backward-compat старого снапшота
        # до PDL-I) + запись в overrides с машинным ключом → holdings побеждает для sector
        # (as-is, не падаем), sector_ru остаётся null (ни holdings, ни override его не несут)
        s["holdings"].append({
            "ticker": "VTBR", "name": "ВТБ",
            "asset_type": "stock", "qty": 500.0,
            "current_price_source": "moex_iss",
            "value_rub": 50000.0, "account": "main", "is_blocked": False,
            "sector": "Финансовый",
        })
        snap.write_text(json.dumps(s))
        overrides.write_text(
            make_sector_overrides_yaml("NVTK", "oil_gas", sector_ru="Энергетический")
            + "  - ticker: VTBR\n    sector: banks_finance\n    note: test\n"
        )
        code, log = run_script(snap, out, extra=["--sector-overrides", str(overrides)])
        if not check("exit 0", code == 0, log[:200]):
            return False
        text = out.read_text()
        ok = True
        nvtk_block = re.search(r"NVTK:.*?(?=\n  \w|\Z)", text, re.DOTALL)
        ok &= check('NVTK sector="oil_gas" (машинный ключ из overrides)',
                    nvtk_block is not None and
                    re.search(r'sector:\s*"oil_gas"', nvtk_block.group() or "") is not None)
        ok &= check('NVTK sector_ru="Энергетический" (ярлык из overrides)',
                    nvtk_block is not None and
                    re.search(r'sector_ru:\s*"Энергетический"', nvtk_block.group() or "") is not None)
        vtbr_block = re.search(r"VTBR:.*?(?=\n  \w|\Z)", text, re.DOTALL)
        ok &= check('VTBR sector="Финансовый" (holdings выше overrides, legacy-текст as-is)',
                    vtbr_block is not None and
                    re.search(r'sector:\s*"Финансовый"', vtbr_block.group() or "") is not None and
                    "banks_finance" not in (vtbr_block.group() or ""))
        ok &= check("VTBR sector_ru=null (ни holdings, ни override не несут ярлык)",
                    vtbr_block is not None and
                    re.search(r'sector_ru:\s*null', vtbr_block.group() or "") is not None)
        return ok


def test_sector_without_overrides_file():
    """A2: без --sector-overrides поведение прежнее (ie_model → unknown)."""
    print("\n[test_sector_without_overrides_file]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        s = make_fake_snapshot()
        s["holdings"].append({
            "ticker": "NVTK", "name": "НОВАТЭК",
            "asset_type": "stock", "qty": 100.0,
            "current_price_source": "moex_iss",
            "value_rub": 300000.0, "account": "main", "is_blocked": False,
        })
        snap.write_text(json.dumps(s))
        code, log = run_script(snap, out)
        if not check("exit 0", code == 0, log[:200]):
            return False
        text = out.read_text()
        nvtk_block = re.search(r"NVTK:.*?(?=\n  \w|\Z)", text, re.DOTALL)
        return check("NVTK sector=unknown без overrides-файла",
                     nvtk_block is not None and
                     re.search(r'sector:.*unknown', nvtk_block.group() or "") is not None)


def test_sector_no_cyrillic_leaks_into_machine_field():
    """PDL-I: сторож на смешение словарей — для тикеров, чей sector целиком идёт из
    overrides (нет ie_model, нет holdings.sector), значение `sector:` не может быть
    кириллическим ярлыком: override даёт sector (машинный ключ) и sector_ru (ярлык)
    раздельно, и они не должны меняться местами. Не проверяем тикеры с ie_model —
    там sector исторически несёт произвольный текст из «Invest Era» (вне PDL-I)."""
    print("\n[test_sector_no_cyrillic_leaks_into_machine_field]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        overrides = Path(td) / "sector-overrides.yaml"

        s = make_fake_snapshot()
        s["holdings"].append({
            "ticker": "NVTK", "name": "НОВАТЭК",
            "asset_type": "stock", "qty": 100.0,
            "current_price_source": "moex_iss",
            "value_rub": 300000.0, "account": "main", "is_blocked": False,
        })
        s["holdings"].append({
            "ticker": "BTBR", "name": "В2В-РТС",
            "asset_type": "stock", "qty": 200.0,
            "current_price_source": "moex_iss",
            "value_rub": 20000.0, "account": "main", "is_blocked": False,
        })
        snap.write_text(json.dumps(s))
        overrides.write_text(
            make_sector_overrides_yaml("NVTK", "oil_gas", sector_ru="Энергетический")
            + "  - ticker: BTBR\n    sector: it_telecom\n    sector_ru: \"IT\"\n    note: test\n"
        )
        code, log = run_script(snap, out, extra=["--sector-overrides", str(overrides)])
        if not check("exit 0", code == 0, log[:200]):
            return False
        text = out.read_text()
        leaks = {}
        for ticker in ("NVTK", "BTBR"):
            block = re.search(rf"{ticker}:.*?(?=\n  \w|\Z)", text, re.DOTALL)
            m = re.search(r'^\s+sector:\s*"([^"\n]+)"\s*$', block.group() or "", re.MULTILINE)
            value = m.group(1) if m else None
            if value and any("а" <= ch.lower() <= "я" for ch in value):
                leaks[ticker] = value
        return check(f"NVTK/BTBR sector: — машинный ключ, не ярлык (нашли утечки: {leaks})",
                     not leaks, f"утечки: {leaks}")


def test_sector_overrides_parsers_mirror_each_other():
    """Зеркальность двух парсеров overrides (PDL-I): load_sector_overrides
    (build_weekly_stock_stub.py, ru-portfolio-advisor) и _load_sector_overrides
    (assemble_snapshot.py, portfolio-data-loader) должны отдавать одинаковый
    {ticker: {"sector":..., "sector_ru":...}} на одном и том же файле — расхождение
    парсеров не должно проходить незамеченным."""
    print("\n[test_sector_overrides_parsers_mirror_each_other]")
    import importlib.util

    def _load_module(name: str, path: Path):
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    rpa_mod = _load_module("_mirror_rpa_stub", SCRIPT)
    pdl_mod = _load_module(
        "_mirror_pdl_assemble",
        REPO / "skills/portfolio-data-loader/scripts/assemble_snapshot.py",
    )

    yaml_text = make_sector_overrides_yaml("NVTK", "oil_gas", sector_ru="Энергетический") + (
        "  - ticker: T\n    sector: banks_finance\n    note: test\n"
    )
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "sector-overrides.yaml"
        path.write_text(yaml_text, encoding="utf-8")
        result_rpa = rpa_mod.load_sector_overrides(path)
        result_pdl = pdl_mod._load_sector_overrides(str(path))
    return check("оба парсера overrides отдают одинаковый результат",
                 result_rpa == result_pdl,
                 f"rpa={result_rpa} pdl={result_pdl}")


def test_horizon_mode_rolling_present():
    """A4: стаб --horizons выдаёт horizon_mode: rolling."""
    print("\n[test_horizon_mode_rolling_present]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        return check("horizon_mode: rolling присутствует",
                     re.search(r"^horizon_mode: rolling\b", text, re.MULTILINE) is not None)


def test_horizon_mode_anchored_present():
    """A4: стаб --anchor-dates выдаёт horizon_mode: anchored."""
    print("\n[test_horizon_mode_anchored_present]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        code, log = run_script(snap, out, extra=["--anchor-dates", "2027-06-30"])
        if not check("exit 0", code == 0, log[:200]):
            return False
        text = out.read_text()
        return check("horizon_mode: anchored присутствует",
                     re.search(r"^horizon_mode: anchored\b", text, re.MULTILINE) is not None)


# ============================================================
# Main
# ============================================================

def test_issuer_name_from_holdings():
    """name эмитента — из snapshot.holdings[].name; нет name в holdings — поля нет (аддитивно)."""
    print("\n[test_issuer_name_from_holdings]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        data = make_fake_snapshot()
        for h in data["holdings"]:
            if h["ticker"] == "T":
                del h["name"]
        snap.write_text(json.dumps(data))
        run_script(snap, out)
        text = out.read_text()
        sber = text.split("\n  SBER:")[1].split("\n  T:")[0]
        t_blk = text.split("\n  T:")[1].split("\n  TMON:")[0]
        ok = check("SBER: name из holdings", re.search(r"^    name: .*Сбербанк", sber, re.M) is not None)
        ok &= check("T без name в holdings — поля нет", not re.search(r"^    name:", t_blk, re.M))
        try:
            import yaml
            ok &= check("YAML парсится, name строкой",
                        yaml.safe_load(text)["per_stock"]["SBER"]["name"] == "Сбербанк")
        except ImportError:
            pass
        return ok


TESTS = [
    test_smoke_run,
    test_top_level_fields,
    test_horizon_v2_fields,
    test_no_v1_horizon_fields,
    test_custom_horizons,
    test_anchor_dates_mode,
    test_anchor_date_in_past_rejected,
    test_per_stock_population,
    test_weight_real_pct_from_ie_actual,
    test_weight_user_planned_from_ie_actual_planned_share,
    test_weight_divergence_vs_planned_is_real_minus_planned,
    test_deprecated_alias_equals_weight_divergence_vs_ie,
    test_ticker_without_plan_still_has_ie_divergence,
    test_ticker_outside_ie_model_with_plan,
    test_canonical_field_names_no_drift,
    test_todo_llm_placeholders_present,
    test_money_market_marker,
    test_summary_counts_match_written_blocks,
    test_frozen_us_counted_even_when_blocked,
    test_money_market_without_share_skipped,
    test_ie_divergence_intent,
    test_yaml_parses_via_pyyaml_if_available,
    test_portfolio_summary_numbers,
    test_invalid_schema_version_rejected,
    test_missing_snapshot_rejected,
    test_horizon_mode_rolling_present,
    test_horizon_mode_anchored_present,
    test_sector_overrides_fallback_chain,
    test_sector_ru_and_holdings_priority,
    test_sector_without_overrides_file,
    test_sector_no_cyrillic_leaks_into_machine_field,
    test_sector_overrides_parsers_mirror_each_other,
    test_issuer_name_from_holdings,
    test_review_date_is_run_date_when_snapshot_older,
]


def main() -> int:
    if not SCRIPT.exists():
        print(f"ERROR: script not found: {SCRIPT}", file=sys.stderr)
        return 1
    passed = 0
    failed = 0
    for t in TESTS:
        try:
            ok = t()
        except Exception as e:
            print(f"  ✗ {t.__name__}: EXCEPTION {type(e).__name__}: {e}")
            ok = False
        if ok:
            passed += 1
        else:
            failed += 1
    print(f"\n{'=' * 50}")
    print(f"Passed: {passed}/{len(TESTS)}; Failed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
