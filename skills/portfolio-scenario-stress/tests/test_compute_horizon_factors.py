#!/usr/bin/env python3
"""Тесты для compute_horizon_factors.py (Phase 4, D4-3).

Запуск: ~/.pyenv/versions/3.12.9/bin/python3 \
        skills/portfolio-scenario-stress/tests/test_compute_horizon_factors.py

Синтетические фикстуры, stdlib only. Никаких реальных тикеров/сценариев.
"""
from __future__ import annotations

import math
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "skills/portfolio-scenario-stress/scripts"))

import compute_horizon_factors as chf  # noqa: E402


def check(label: str, cond: bool, detail: str = "") -> bool:
    if cond:
        print(f"  ✓ {label}")
        return True
    print(f"  ✗ {label}{(' — ' + detail) if detail else ''}")
    return False


BASELINE = {"brent_usd": 94.11, "usdrub": 88.0, "cbr_rate_pct": 14.5, "cnyrub": 12.3}


def _payload(scenarios, horizons=(12, 20, 36), as_of="2026-06-15", horizon_ends=None):
    p = {
        "as_of": as_of,
        "horizons": list(horizons),
        "baseline_spot": BASELINE,
        "scenarios": scenarios,
    }
    if horizon_ends:
        p["horizon_ends"] = horizon_ends
    return p


def test_pct_from_spot_and_pp_diff():
    """brent (pct_from_spot) и cbr_rate (pp_diff) считаются по контракту §5.6."""
    print("\n[test_pct_from_spot_and_pp_diff]")
    sc = {"A": {"factors": {
        "brent": {"level_l1_2027": 72.0, "unit": "usd_per_bbl"},
        "cbr_rate": {"level_l1_2027": 9.5, "unit": "rate_pct"},
    }}}
    r = chf.run(_payload(sc, horizons=[12]))
    h = r["factors_by_horizon"]["A"]["h12"]
    ok = True
    expected_brent = (72.0 - 94.11) / 94.11 * 100
    ok &= check("brent move == (72-94.11)/94.11*100",
                abs(h["brent"] - round(expected_brent, 4)) < 1e-6, f"{h['brent']}")
    ok &= check("cbr_rate move == 9.5-14.5 == -5.0 (pp_diff)", abs(h["cbr_rate"] - (-5.0)) < 1e-9)
    return ok


def test_number_factor_copied_to_all_horizons():
    """Числовой фактор (sanctions) горизонт-инвариантен — копируется во все hNN."""
    print("\n[test_number_factor_copied_to_all_horizons]")
    sc = {"A": {"factors": {"sanctions": 0.3, "geopol": -0.2}}}
    r = chf.run(_payload(sc))
    fbh = r["factors_by_horizon"]["A"]
    ok = True
    for hk in ("h12", "h20", "h36"):
        ok &= check(f"{hk}.sanctions == 0.3", fbh[hk].get("sanctions") == 0.3)
        ok &= check(f"{hk}.geopol == -0.2", fbh[hk].get("geopol") == -0.2)
    # P0-2: поведение прежнее, но мультигоризонтный скаляр теперь помечается
    ok &= check("warning про горизонт-инвариантность (P0-2)",
                len([w for w in r["warnings"] if "P0-2" in w]) == 2,
                str(r["warnings"]))
    return ok


# ───────────────────────── P0-2: горизонтный путь дилов ─────────────────────────

def test_political_explicit_horizon_path():
    """Явный путь {h6/h12/h24} берётся как есть — «разрядка углубляется со временем»."""
    print("\n[test_political_explicit_horizon_path]")
    sc = {"D": {"factors": {"sanctions": {"h6": -0.3, "h12": -0.6, "h24": -0.9}}}}
    r = chf.run(_payload(sc, horizons=[6, 12, 24]))
    fbh = r["factors_by_horizon"]["D"]
    ok = True
    ok &= check("h6 == -0.3", fbh["h6"]["sanctions"] == -0.3)
    ok &= check("h12 == -0.6", fbh["h12"]["sanctions"] == -0.6)
    ok &= check("h24 == -0.9", fbh["h24"]["sanctions"] == -0.9)
    ok &= check("нет warning на полном пути", not r["warnings"], str(r["warnings"]))
    return ok


def test_intensity_unit_levels_by_year():
    """unit: intensity — уровень уже движение (baseline_spot не нужен)."""
    print("\n[test_intensity_unit_levels_by_year]")
    sc = {"D": {"factors": {"sanctions": {
        "level_l1_2027": -0.3, "level_l1_2028": -0.9, "unit": "intensity"}}}}
    p = _payload(sc, horizons=[12, 24], as_of="2026-06-15")
    p["baseline_spot"] = {}          # интенсивности спот не нужен
    r = chf.run(p)
    fbh = r["factors_by_horizon"]["D"]
    ok = True
    ok &= check("h12 (2027) == -0.3", fbh["h12"]["sanctions"] == -0.3)
    ok &= check("h24 (2028) == -0.9", fbh["h24"]["sanctions"] == -0.9)
    ok &= check("работает при пустом baseline_spot", "sanctions" in fbh["h12"])
    return ok


def test_political_scalar_zero_and_single_horizon_silent():
    """Статус-кво 0 и одногоризонтный прогон warning не дают."""
    print("\n[test_political_scalar_zero_and_single_horizon_silent]")
    r_zero = chf.run(_payload({"C": {"factors": {"sanctions": 0.0}}}, horizons=[6, 12]))
    r_one = chf.run(_payload({"C": {"factors": {"sanctions": -0.9}}}, horizons=[12]))
    ok = True
    ok &= check("0.0 на всех горизонтах — молчим",
                not [w for w in r_zero["warnings"] if "P0-2" in w], str(r_zero["warnings"]))
    ok &= check("один горизонт — молчим",
                not [w for w in r_one["warnings"] if "P0-2" in w], str(r_one["warnings"]))
    return ok


def test_mixed_forms_rejected():
    """
    Явный путь + уровни года для одного фактора — неоднозначная форма: для
    непокрытого путём горизонта нет правильного источника, а любой выбор молча
    даёт неверный политический фактор. Отказываемся считать.
    """
    print("\n[test_mixed_forms_rejected]")
    sc = {"D": {"factors": {"sanctions": {
        "h12": -0.55, "level_l1_2027": -0.1, "unit": "intensity"}}}}
    try:
        chf.run(_payload(sc, horizons=[12, 24]))
    except SystemExit as e:
        msg = str(e)
        return check("SystemExit называет обе формы поимённо",
                     "ОДНОВРЕМЕННО" in msg and "[12]" in msg and "[2027]" in msg, msg)
    return check("смешанная форма должна отвергаться", False)


def test_path_interpolates_inside_and_extrapolates_outside():
    """
    Горизонт между точками пути → интерполяция (брать ближайшую точку значило бы
    выбросить вторую известную); за пределами пути → плоская экстраполяция.
    """
    print("\n[test_path_interpolates_inside_and_extrapolates_outside]")
    sc = {"D": {"factors": {"sanctions": {"h6": -0.3, "h24": -0.9}}}}
    r = chf.run(_payload(sc, horizons=[3, 12, 24, 36]))
    fbh = r["factors_by_horizon"]["D"]
    ok = True
    ok &= check("h12 интерполирован: -0.3 + (-0.6)·(6/18) = -0.5",
                abs(fbh["h12"]["sanctions"] - (-0.5)) < 1e-9, str(fbh["h12"]))
    ok &= check("h3 (левее пути) == -0.3", fbh["h3"]["sanctions"] == -0.3)
    ok &= check("h36 (правее пути) == -0.9", fbh["h36"]["sanctions"] == -0.9)
    ok &= check("интерполяция помечена warning'ом",
                any("интерполяция" in w for w in r["warnings"]), str(r["warnings"]))
    ok &= check("экстраполяция помечена отдельно",
                any("экстраполяция" in w for w in r["warnings"]), str(r["warnings"]))
    return ok


def test_intensity_alias_from_live_artifacts():
    """
    Единица интенсивности пишется в живых артефактах тремя строками; все три
    должны считаться, иначе автор, скопировавший строку из factor_definitions,
    получит тихий пропуск фактора.
    """
    print("\n[test_intensity_alias_from_live_artifacts]")
    ok = True
    for unit in ("intensity", "intensity_-1_to_1", "ед. intensity-delta"):
        sc = {"D": {"factors": {"sanctions": {"level_l1_2027": -0.4, "unit": unit}}}}
        p = _payload(sc, horizons=[12], as_of="2026-06-15")
        p["baseline_spot"] = {}
        r = chf.run(p)
        ok &= check(f"unit={unit!r} → уровень взят как движение",
                    r["factors_by_horizon"]["D"]["h12"].get("sanctions") == -0.4)
    return ok


def test_intensity_alias_accepted():
    """`intensity_-1_to_1` — та же строка, что в factor_definitions вьюера."""
    print("\n[test_intensity_alias_accepted]")
    sc = {"D": {"factors": {"sanctions": {
        "level_l1_2027": -0.4, "unit": "intensity_-1_to_1"}}}}
    p = _payload(sc, horizons=[12], as_of="2026-06-15")
    p["baseline_spot"] = {}
    r = chf.run(p)
    return check("уровень взят как движение",
                 r["factors_by_horizon"]["D"]["h12"]["sanctions"] == -0.4)


def test_market_factor_path_also_supported():
    """Путь по горизонтам — общий механизм, не только для политики."""
    print("\n[test_market_factor_path_also_supported]")
    sc = {"A": {"factors": {"brent": {"h12": -12.0, "h24": -20.0}}}}
    r = chf.run(_payload(sc, horizons=[12, 24]))
    fbh = r["factors_by_horizon"]["A"]
    ok = True
    ok &= check("h12 == -12.0", fbh["h12"]["brent"] == -12.0)
    ok &= check("h24 == -20.0", fbh["h24"]["brent"] == -20.0)
    return ok


def test_year_selection_nearest():
    """Выбор года: точный для h12 (2027), ближайший (2027) для h36 (target 2029)."""
    print("\n[test_year_selection_nearest]")
    sc = {"A": {"factors": {
        "brent": {"level_l1_2026": 68.0, "level_l1_2027": 72.0, "unit": "usd_per_bbl"},
    }}}
    r = chf.run(_payload(sc))
    cov = r["horizon_coverage"]
    ok = True
    ok &= check("h12 target_year == 2027", cov["h12"]["target_year"] == 2027)
    ok &= check("h12 covered (есть точный 2027)", cov["h12"]["status"] == "covered")
    ok &= check("h36 target_year == 2029", cov["h36"]["target_year"] == 2029)
    ok &= check("h36 extrapolated (нет 2029)", cov["h36"]["status"] == "extrapolated")
    ok &= check("h36 source_years.brent == 2027", cov["h36"]["source_years"].get("brent") == 2027)
    return ok


def test_ci_inflation_formula():
    """ci_inflation = √(h_target / h_source), h_source = h + (src-target)*12."""
    print("\n[test_ci_inflation_formula]")
    sc = {"A": {"factors": {
        "brent": {"level_l1_2027": 72.0, "unit": "usd_per_bbl"},
    }}}
    r = chf.run(_payload(sc))
    cov = r["horizon_coverage"]
    ok = True
    # h20: target 2028, src 2027 → h_source = 20 + (2027-2028)*12 = 8 → √(20/8) = 1.5811
    ok &= check("h20 ci_inflation == √(20/8)",
                abs(cov["h20"]["ci_inflation"] - round(math.sqrt(20 / 8), 4)) < 1e-4,
                f"{cov['h20']['ci_inflation']}")
    # h36: target 2029, src 2027 → h_source = 36 - 24 = 12 → √(36/12) = √3
    ok &= check("h36 ci_inflation == √3",
                abs(cov["h36"]["ci_inflation"] - round(math.sqrt(3), 4)) < 1e-4,
                f"{cov['h36']['ci_inflation']}")
    ok &= check("covered горизонт → ci_inflation 1.0", cov["h12"]["ci_inflation"] == 1.0)
    return ok


def test_ci_inflation_capped():
    """Очень дальний gap → ci_inflation клампится в MAX_CI_INFLATION."""
    print("\n[test_ci_inflation_capped]")
    # target h36 → 2029, доступен только 2026 → h_source = 36 + (2026-2029)*12 = 0 → clamp ≥1
    sc = {"A": {"factors": {"brent": {"level_l1_2026": 68.0, "unit": "usd_per_bbl"}}}}
    r = chf.run(_payload(sc, horizons=[36]))
    infl = r["horizon_coverage"]["h36"]["ci_inflation"]
    return check("ci_inflation ≤ MAX (3.0)", infl <= chf.MAX_CI_INFLATION and infl > 1.0, f"{infl}")


def test_qualitative_without_level_skipped():
    """dict без level_l1/unit → пропуск + warning, не падает."""
    print("\n[test_qualitative_without_level_skipped]")
    sc = {"A": {"factors": {
        "geopol": {"note": "эскалация"},          # dict без level → skip
        "brent": "качественно вверх",              # строка → skip
        "usdrub": {"level_l1_2027": 95.0, "unit": "rub_per_usd"},
    }}}
    r = chf.run(_payload(sc, horizons=[12]))
    h = r["factors_by_horizon"]["A"]["h12"]
    ok = True
    ok &= check("geopol пропущен (нет в h12)", "geopol" not in h)
    ok &= check("brent-строка пропущена", "brent" not in h)
    ok &= check("usdrub посчитан", "usdrub" in h)
    ok &= check("есть warnings про пропуск", len(r["warnings"]) >= 2, str(r["warnings"]))
    return ok


def test_unit_not_in_baseline_skipped():
    """unit без ключа в baseline_spot → фактор пропущен + warning."""
    print("\n[test_unit_not_in_baseline_skipped]")
    sc = {"A": {"factors": {"xau": {"level_l1_2027": 3000.0, "unit": "usd_per_troy_oz"}}}}
    # baseline без xauusd_usd
    r = chf.run(_payload(sc, horizons=[12]))
    ok = True
    ok &= check("xau не посчитан (нет xauusd_usd в baseline)",
                "xau" not in r["factors_by_horizon"]["A"]["h12"])
    ok &= check("warning про отсутствие в baseline_spot",
                any("baseline_spot" in w for w in r["warnings"]))
    return ok


def test_anchored_horizon_ends_year():
    """horizon_ends (якорный режим) задаёт целевой год вместо as_of+h."""
    print("\n[test_anchored_horizon_ends_year]")
    sc = {"A": {"factors": {
        "brent": {"level_l1_2027": 72.0, "level_l1_2028": 70.0, "unit": "usd_per_bbl"},
    }}}
    # Скользящий h20 → target 2028. Якорим h20 на дату 2027-06-30 → target 2027.
    r = chf.run(_payload(sc, horizons=[20], horizon_ends={"h20": "2027-06-30"}))
    cov = r["horizon_coverage"]["h20"]
    ok = True
    ok &= check("target_year из horizon_ends == 2027", cov["target_year"] == 2027)
    ok &= check("covered (2027 доступен)", cov["status"] == "covered")
    # move использует level_2027 = 72
    move = r["factors_by_horizon"]["A"]["h20"]["brent"]
    ok &= check("move по 2027 уровню", abs(move - round((72 - 94.11) / 94.11 * 100, 4)) < 1e-6)
    return ok


def test_multi_scenario_independent():
    """Несколько сценариев обрабатываются независимо."""
    print("\n[test_multi_scenario_independent]")
    sc = {
        "A": {"factors": {"brent": {"level_l1_2027": 72.0, "unit": "usd_per_bbl"}}},
        "D": {"factors": {"brent": {"level_l1_2027": 110.0, "unit": "usd_per_bbl"}}},
    }
    r = chf.run(_payload(sc, horizons=[12]))
    ok = True
    a = r["factors_by_horizon"]["A"]["h12"]["brent"]
    d = r["factors_by_horizon"]["D"]["h12"]["brent"]
    ok &= check("A.brent < 0 (72 < spot)", a < 0)
    ok &= check("D.brent > 0 (110 > spot)", d > 0)
    return ok


def test_missing_as_of_errors():
    """Без as_of → SystemExit."""
    print("\n[test_missing_as_of_errors]")
    try:
        chf.run({"horizons": [12], "scenarios": {}, "baseline_spot": BASELINE})
    except SystemExit:
        return check("SystemExit без as_of", True)
    return check("SystemExit без as_of", False, "не выброшен")


def test_helpers():
    """Юнит-проверки хелперов."""
    print("\n[test_helpers]")
    ok = True
    ok &= check("_add_months конец года", chf._add_months(date(2026, 6, 15), 8).year == 2027)
    ok &= check("_level_to_move pp_diff", chf._level_to_move(9.5, "rate_pct", BASELINE) == -5.0)
    ok &= check("_pick_nearest_year тай-брейк меньший год",
                chf._pick_nearest_year({2026: 1, 2028: 2}, 2027) == 2026)
    ok &= check("_ci_inflation same year == 1.0", chf._ci_inflation(20, 2027, 2027) == 1.0)
    return ok


TESTS = [
    test_pct_from_spot_and_pp_diff,
    test_number_factor_copied_to_all_horizons,
    test_year_selection_nearest,
    test_ci_inflation_formula,
    test_ci_inflation_capped,
    test_qualitative_without_level_skipped,
    test_unit_not_in_baseline_skipped,
    test_anchored_horizon_ends_year,
    test_multi_scenario_independent,
    test_missing_as_of_errors,
    test_helpers,
    # P0-2
    test_political_explicit_horizon_path,
    test_intensity_unit_levels_by_year,
    test_political_scalar_zero_and_single_horizon_silent,
    test_mixed_forms_rejected,
    test_path_interpolates_inside_and_extrapolates_outside,
    test_intensity_alias_accepted,
    test_intensity_alias_from_live_artifacts,
    test_market_factor_path_also_supported,
]


def main() -> int:
    passed = failed = 0
    for t in TESTS:
        try:
            ok = t()
        except Exception as e:
            print(f"  ✗ {t.__name__}: {type(e).__name__}: {e}")
            ok = False
        passed += ok
        failed += not ok
    print(f"\n{'=' * 50}\nPassed: {passed}/{len(TESTS)}; Failed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
