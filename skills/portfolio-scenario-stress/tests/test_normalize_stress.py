#!/usr/bin/env python3
"""Тесты для normalize_stress.py (Задача 4, контракт баз расчёта архива).

Запуск: ~/.pyenv/versions/3.12.9/bin/python3 \
        skills/portfolio-scenario-stress/tests/test_normalize_stress.py

Синтетические юнит-тесты — stdlib only (dict напрямую). Регрессия по 17
архивным файлам — живой артефакт Claude-Memory опционально (пропускается с
пометкой, если Synology mount недоступен), сверяет три известных ориентира
§4.2 задачи (stress-2026-09-03 A/h12, stress-2026-09-18 A/h12) и требование
«не unknown там, где база выводится однозначно».
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "skills/portfolio-scenario-stress/scripts"))

import normalize_stress as ns  # noqa: E402

ARCHIVE_DIR = Path(
    "/Users/you/Library/CloudStorage/SynologyDrive-home/Claude-Memory/Portfolio/stress")
SNAPSHOTS_DIR = ARCHIVE_DIR.parent / "snapshots"


def check(label: str, cond: bool, detail: str = "") -> bool:
    if cond:
        print(f"  ✓ {label}")
        return True
    print(f"  ✗ {label}{(' — ' + detail) if detail else ''}")
    return False


def snapshot_no_cash() -> dict:
    return {
        "holdings": [
            {"ticker": "TICK1", "value_rub": 600000.0, "is_blocked": False},
            {"ticker": "TICK2", "value_rub": 400000.0, "is_blocked": False},
        ],
        "cash": {"total_rub": 0.0},
    }


def doc_price_only(delta_rub: float) -> dict:
    return {
        "date": "2026-01-01", "run_id": "test",
        "scenarios": {"A": {"portfolio_level_by_horizon": {
            "h6": {"delta_rub": delta_rub}}}},
        "per_position": {
            "TICK1": {"weight_pct": 60, "by_horizon": {
                "h6": {"delta_pct_by_scenario": {"A": -10.0}}}},
            "TICK2": {"weight_pct": 40, "by_horizon": {
                "h6": {"delta_pct_by_scenario": {"A": 5.0}}}},
        },
    }


def test_price_only_no_bond_carry() -> bool:
    """Нет bond_carry вовсе → delta_rub тривиально price (Layer 2 не существует)."""
    print("\n[test_price_only_no_bond_carry]")
    # price_sum = 0.6*1e6*(-0.10) + 0.4*1e6*0.05 = -60000+20000 = -40000
    doc = doc_price_only(delta_rub=-40000)
    res = ns.normalize(doc, snapshot_no_cash())
    ok = True
    ok &= check("file_basis == price", res["file_basis"] == "price", res["file_basis"])
    ok &= check("метод 2", res["cells"]["A"]["h6"]["method"] == 2)
    ok &= check("total_return_rub отмечен как отсутствующий безвозвратно",
                any("total_return_rub" in m for m in res["missing_fields"]),
                str(res["missing_fields"]))
    return ok


def test_total_return_with_bond_carry() -> bool:
    """delta_rub = price_sum + carry_sum → basis total_return, метод 3."""
    print("\n[test_total_return_with_bond_carry]")
    doc = doc_price_only(delta_rub=-40000 + 15000)  # price_sum=-40000, carry=15000
    doc["bond_carry"] = {"per_position": {
        "TICK1": {"by_horizon": {"h6": {"by_scenario": {"A": {"carry_pct": 2.5}}}}},  # 600000*0.025=15000
    }}
    res = ns.normalize(doc, snapshot_no_cash())
    cell = res["cells"]["A"]["h6"]
    ok = True
    ok &= check("basis == total_return", cell["basis"] == "total_return", cell["basis"])
    ok &= check("метод 3", cell["method"] == 3)
    ok &= check("carry_sum_recomputed == 15000", cell["carry_sum_recomputed"] == 15000,
                str(cell["carry_sum_recomputed"]))
    ok &= check("normalized.total_return_rub == -25000",
                cell["normalized"]["total_return_rub"] == -25000, str(cell["normalized"]))
    return ok


def test_unknown_when_neither_matches() -> bool:
    """delta_rub не сходится ни с price, ни с price+carry → unknown, не угадываем."""
    print("\n[test_unknown_when_neither_matches]")
    doc = doc_price_only(delta_rub=999999)  # далеко от -40000 и от любого +carry
    res = ns.normalize(doc, snapshot_no_cash())
    cell = res["cells"]["A"]["h6"]
    ok = True
    ok &= check("basis == unknown", cell["basis"] == "unknown", cell["basis"])
    ok &= check("метод 4", cell["method"] == 4)
    ok &= check("reason непустой", bool(cell.get("reason")))
    return ok


def test_l1_price_only_alias_and_crosscheck() -> bool:
    """l1_price_only_delta_rub → расшифровывается и сверяется с независимым пересчётом."""
    print("\n[test_l1_price_only_alias_and_crosscheck]")
    doc = doc_price_only(delta_rub=-25000)  # total_return (=price+carry)
    doc["scenarios"]["A"]["portfolio_level_by_horizon"]["h6"]["l1_price_only_delta_rub"] = -40000
    doc["bond_carry"] = {"per_position": {
        "TICK1": {"by_horizon": {"h6": {"by_scenario": {"A": {"carry_pct": 2.5}}}}},
    }}
    res = ns.normalize(doc, snapshot_no_cash())
    cell = res["cells"]["A"]["h6"]
    ok = True
    ok &= check("basis == total_return", cell["basis"] == "total_return")
    ok &= check("l1_price_only_matches_recomputed_price == True",
                cell.get("l1_price_only_matches_recomputed_price") is True)
    return ok


def test_diagnostic_flags_wrong_base_multiplier() -> bool:
    """Регрессия: delta_rub, посчитанный по weight_pct×base_value_rub (с кэшем)
    вместо positions_value_rub, даёт unknown + диагностическую пометку —
    находка reproduces баг из архива stress-2026-06-28 (см. память проекта)."""
    print("\n[test_diagnostic_flags_wrong_base_multiplier]")
    snap = {
        "holdings": [
            {"ticker": "TICK1", "value_rub": 600000.0, "is_blocked": False},
            {"ticker": "TICK2", "value_rub": 300000.0, "is_blocked": False},
        ],
        "cash": {"total_rub": 100000.0},  # positions=900000, base=1000000
    }
    # Правильный price_sum (positions_value_rub=900000): 0.6667*900000*(-0.1)+0.3333*900000*0.05=-45000
    # "Ошибочный" delta_rub, как если бы considered base_value_rub=1000000: -50000
    doc = {
        "date": "x", "run_id": "x",
        "scenarios": {"A": {"portfolio_level_by_horizon": {"h6": {"delta_rub": -50000}}}},
        "per_position": {
            "TICK1": {"weight_pct": 600000 / 900000 * 100, "by_horizon": {
                "h6": {"delta_pct_by_scenario": {"A": -10.0}}}},
            "TICK2": {"weight_pct": 300000 / 900000 * 100, "by_horizon": {
                "h6": {"delta_pct_by_scenario": {"A": 5.0}}}},
        },
    }
    res = ns.normalize(doc, snap)
    cell = res["cells"]["A"]["h6"]
    ok = True
    ok &= check("basis == unknown (не price, не total_return)", cell["basis"] == "unknown")
    ok &= check("reason называет независимый исторический дефект",
                "независимый исторический дефект" in cell.get("reason", ""),
                cell.get("reason"))
    return ok


def test_archive_regression() -> bool:
    """Регрессия по всем 17 архивным файлам — живой Synology-артефакт
    опционально (см. env_python_for_tests / claude-memory-layout)."""
    print("\n[test_archive_regression]")
    if not ARCHIVE_DIR.exists():
        print("  ⚠ SKIP — Synology mount недоступен (нужен живой архив Claude-Memory)")
        return True

    paths = sorted(ARCHIVE_DIR.glob("stress-*.yaml"))
    ok = True
    # Архив растёт с каждым прогоном стресса: 17 — сколько было при постановке
    # задачи (2026-09-30), меньше — значит, файлы пропали; больше — норма.
    ok &= check(f"найдено ≥ 17 архивных файлов (было на момент постановки задачи)",
                len(paths) >= 17, f"найдено {len(paths)}")

    results: dict[str, dict] = {}
    for p in paths:
        loaded = ns._load_for_file(p, SNAPSHOTS_DIR)
        if loaded is None:
            ok &= check(f"{p.name}: снапшот найден", False)
            continue
        data, snapshot = loaded
        try:
            results[p.name] = ns.normalize(data, snapshot)
        except Exception as e:  # noqa: BLE001
            ok &= check(f"{p.name}: normalize() не падает", False, f"{type(e).__name__}: {e}")

    # Ориентиры §4.2: известные референсные точки.
    r0903 = results.get("stress-2026-09-03-geopol-ru-west-shell-d1.yaml")
    if not r0903:
        print("  ⊘ 09-03 shell-d1: эталона нет в архиве — 3 проверки пропущены")
    if r0903:
        cell = r0903["cells"]["A"]["h12"]
        ok &= check("09-03 A/h12: basis == total_return", cell["basis"] == "total_return")
        ok &= check("09-03 A/h12: l1_price_only_delta_rub == -94362",
                    cell.get("l1_price_only_delta_rub") == -94362)
        ok &= check("09-03 A/h12: пересчитанный price_sum ≈ l1_price_only_delta_rub",
                    cell.get("l1_price_only_matches_recomputed_price") is True)

    r0918 = results.get("stress-2026-09-18-geopol-ru-west-macro-d.yaml")
    if not r0918:
        # Эталон §4.2 не в архиве Portfolio/stress (на 2026-09-30 лежит в
        # «Claude outputs/»): три проверки не выполнялись молча — говорим вслух.
        print("  ⊘ 09-18 macro-d: эталона нет в архиве — 3 проверки пропущены")
    if r0918:
        cell = r0918["cells"]["A"]["h12"]
        ok &= check("09-18 A/h12: basis == price", cell["basis"] == "price")
        ok &= check("09-18 A/h12: total_return_by_horizon_rub == 986451",
                    cell.get("total_return_by_horizon_rub") == 986451)
        ok &= check("09-18 A/h12: пересчёт price+carry ≈ total_return_by_horizon_rub",
                    cell.get("total_return_by_horizon_rub_matches_recomputed") is True)

    # Файлы 2026-05-11..06-08 (нет bond_carry) обязаны тривиально дать price.
    for fname in ("stress-2026-05-11-mfc-shell-d1.yaml", "stress-2026-06-08-mfc-shell-d1-6-12-24.yaml"):
        r = results.get(fname)
        if r:
            ok &= check(f"{fname}: basis == price (нет bond_carry)", r["file_basis"] == "price",
                        r["file_basis"])

    print(f"  Итого обработано: {len(results)}/{len(paths)}; "
          f"basis=unknown у: {[f for f, r in results.items() if r['file_basis'] == 'unknown']}")
    return ok


TESTS = [
    test_price_only_no_bond_carry,
    test_total_return_with_bond_carry,
    test_unknown_when_neither_matches,
    test_l1_price_only_alias_and_crosscheck,
    test_diagnostic_flags_wrong_base_multiplier,
    test_archive_regression,
]


def main() -> int:
    passed = failed = 0
    for t in TESTS:
        try:
            ok = t()
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"  ✗ {t.__name__}: {type(e).__name__}: {e}")
            ok = False
        passed += ok
        failed += not ok
    print(f"\n{'=' * 50}\nPassed: {passed}/{len(TESTS)}; Failed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
