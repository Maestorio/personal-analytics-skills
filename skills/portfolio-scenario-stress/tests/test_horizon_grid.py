#!/usr/bin/env python3
"""Тесты сетки дат макро-цепочки в compute_horizon_factors.py: grid_move, validate_macro,
factors_from_macro и CLI --check-macro. Синтетика, без сети и Synology.

Запуск: ~/.pyenv/versions/3.12.9/bin/python3 skills/portfolio-scenario-stress/tests/test_horizon_grid.py
"""
from __future__ import annotations

import copy
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
SCRIPTS = REPO / "skills/portfolio-scenario-stress/scripts"
CHF = SCRIPTS / "compute_horizon_factors.py"
sys.path.insert(0, str(SCRIPTS))

import compute_horizon_factors as chf  # noqa: E402


def check(label: str, cond: bool, detail: str = "") -> bool:
    if cond:
        print(f"  ✓ {label}")
        return True
    print(f"  ✗ {label}{(' — ' + detail) if detail else ''}")
    return False


AS_OF = "2026-11-04"
ENDS = {"h6": "2027-03-31", "h12": "2027-09-30", "h24": "2028-09-30"}


def _e(v, p=None):
    d = {"value": v}
    if p is not None:
        d["pct_vs_spot"] = p
    return d


def macro() -> dict:
    """Макро-файл по образцу живых: A, B; brent/usdrub/cnyrub/cbr по сценариям, xauusd — на все."""
    brent_a = {"2026-12-31": _e(96.8, -5.91), "2027-06-30": _e(93.5, -9.12), "2027-12-31": _e(83.3, -19.03)}
    cbr_a = {"2026-12-31": _e(15.1), "2027-06-30": _e(14.875), "2027-12-31": _e(13.95), "2028-12-31": _e(12.4)}
    rub = {"2026-12-31": _e(82.8), "2027-12-31": _e(88.8)}
    cny = {"2026-12-31": _e(12.0), "2027-12-31": _e(12.6)}
    return {
        "baseline_spot": {"brent_price": 102.88, "usdrub_rate": 80.9734, "cnyrub_rate": 12.1714, "cbr_rate": 14.0,
                          "xauusd_price": 3950},
        "factors": {
            "brent_price": {"unit": "usd_per_bbl", "by_scenario": {"A": brent_a, "B": copy.deepcopy(brent_a)}},
            "usdrub_rate": {"unit": "rub_per_usd", "by_scenario": {"A": rub, "B": copy.deepcopy(rub)}},
            "cnyrub_rate": {"unit": "rub_per_cny", "by_scenario": {"A": cny, "B": copy.deepcopy(cny)}},
            "cbr_rate": {"unit": "rate_pct", "by_scenario": {"A": cbr_a, "B": copy.deepcopy(cbr_a)}},
            "xauusd_price": {"unit": "usd_per_troy_oz",
                             "level_all_scenarios": {"2026-12-31": _e(4500, 13.92), "2027-12-31": _e(5400, 36.71)}},
            "sanctions_russia": {"unit": "qualitative", "by_scenario": {"A": "x"}},
        },
    }


def test_check_numbers():
    fbh, cov, warns = chf.factors_from_macro(macro(), ["A", "B"], AS_OF, ENDS)
    a = fbh["A"]
    ok = check("brent h6 ≈ −7.505 (допуск 0.01 к живому −7.5061)", abs(a["h6"]["brent"] - (-7.505)) < 0.01, str(a["h6"]["brent"]))
    ok &= check("brent h24 ≈ −19.03 (flat hold; точно −19.0319)", abs(a["h24"]["brent"] - (-19.03)) < 0.01, str(a["h24"]["brent"]))
    ok &= check("ci_inflation h24 = 1.2842, статус extrapolated",
                cov["h24"]["ci_inflation"] == 1.2842 and cov["h24"]["status"] == "extrapolated", str(cov["h24"]))
    ok &= check("cbr_rate h6 = 0.9881, h24 = −1.2104 (интерполяция, п.п.)",
                abs(a["h6"]["cbr_rate"] - 0.9881) < 1e-4 and abs(a["h24"]["cbr_rate"] - (-1.2104)) < 1e-4,
                f"{a['h6']['cbr_rate']} {a['h24']['cbr_rate']}")
    ok &= check("текст предупреждения flat hold по brent",
                "brent: сетка прогноза заканчивается 2027-12-31, горизонт 2028-09-30 — flat hold (×1.2842 CI)"
                in cov["h24"]["warnings"], str(cov["h24"]["warnings"]))
    ok &= check("cbr без предупреждения (сетка доходит до 2028-12-31)",
                not any(w.startswith("cbr_rate:") for w in cov["h24"]["warnings"]))
    ok &= check("h6 и h12 covered, ci 1.0, target_date из срока",
                cov["h6"]["status"] == "covered" and cov["h6"]["ci_inflation"] == 1.0
                and cov["h12"]["status"] == "covered" and cov["h12"]["target_date"] == "2027-09-30"
                and cov["h24"]["target_date"] == "2028-09-30", str(cov))
    ok &= check("level_all_scenarios: одинаковые значения всем сценариям",
                all(fbh["A"][h]["xauusd"] == fbh["B"][h]["xauusd"] for h in ENDS)
                and abs(fbh["A"]["h24"]["xauusd"] - 36.7089) < 1e-3, str(fbh["A"]["h24"]["xauusd"]))
    ok &= check("пять числовых факторов в каждом сроке", all(set(fbh["A"][h]) == {"brent", "usdrub", "cnyrub", "cbr_rate", "xauusd"} for h in ENDS))
    ok &= check("pct_vs_spot из образца согласован — предупреждений нет", warns == [], str(warns))
    ok &= check("ключи coverage читаются recalc/validate", all({"status", "ci_inflation", "warnings", "target_date"} <= set(v) for v in cov.values()))
    return ok


def test_grid_move_cases():
    lv = {"2026-12-31": 100.0, "2027-12-31": 120.0}
    # на точке
    m, ex, ci, w = chf.grid_move(lv, 100.0, "pct_from_spot", AS_OF, "2027-12-31")
    ok = check("срок ровно на точке: её уровень, без предупреждения", (m, ex, ci, w) == (20.0, False, 1.0, None), str((m, ex, ci, w)))
    # раньше первой точки
    m, ex, ci, w = chf.grid_move(lv, 90.0, "pct_from_spot", "2026-11-01", "2026-11-16", "brent")
    days = (chf.date.fromisoformat("2026-12-31") - chf.date.fromisoformat("2026-11-01")).days  # 60
    exp = round((90 + (100 - 90) * 15 / days - 90) / 90 * 100, 4)
    ok &= check("раньше первой точки: интерполяция от спота, covered", m == exp and not ex and ci == 1.0, f"{m} {exp}")
    ok &= check("предупреждение «раньше первой точки … интерполяция от спота»",
                w is not None and "раньше первой точки сетки" in w and "интерполяция от спота" in w and w.startswith("brent:"), str(w))
    # п.п.
    m, *_ = chf.grid_move({"2027-01-01": 12.0}, 14.0, "pp_diff", "2026-01-01", "2027-01-01")
    ok &= check("п.п.: уровень − спот", m == -2.0, str(m))
    # flat hold и верхняя граница CI
    m, ex, ci, w = chf.grid_move({"2026-12-31": 110.0}, 100.0, "pct_from_spot", "2026-11-04", "2040-01-01", "x")
    ok &= check("flat hold: уровень последней точки, CI не больше MAX", m == 10.0 and ex and ci == chf.MAX_CI_INFLATION, f"{m} {ci}")
    return ok


def test_validate_refusals():
    m = macro()
    del m["factors"]["usdrub_rate"]                                   # нет фактора
    m["factors"]["cnyrub_rate"] = {"unit": "x"}                       # ни by_scenario, ни level_all
    del m["factors"]["brent_price"]["by_scenario"]["B"]               # нет сценария
    m["factors"]["cbr_rate"]["by_scenario"]["A"] = {"2026-12-31": {"value": "n/a"}}   # нет числового value
    m["factors"]["xauusd_price"]["level_all_scenarios"]["не-дата"] = _e(1)            # плохой ключ даты
    m["baseline_spot"]["brent_price"] = 0                             # спот ≤ 0
    del m["baseline_spot"]["cbr_rate"]                                # нет спота
    errs, _ = chf.validate_macro(m, ["A", "B"])
    txt = "\n".join(errs)
    ok = check("нет фактора", "usdrub_rate: фактор отсутствует" in txt, txt)
    ok &= check("нет by_scenario/level_all", "cnyrub_rate: нет ни by_scenario, ни level_all_scenarios" in txt, txt)
    ok &= check("нет сценария матрицы", "brent_price, сценарий B: сценария нет в by_scenario" in txt, txt)
    ok &= check("нет числового value", "cbr_rate, сценарий A: нет ни одной даты с числовым value" in txt, txt)
    ok &= check("ключ даты не ISO", "xauusd_price, сценарий A: ключ даты 'не-дата' не ISO-дата" in txt, txt)
    ok &= check("спот ≤ 0 и нет спота", "brent_price: спот в baseline_spot 0 не положительное" in txt
                and "cbr_rate: нет спота в baseline_spot" in txt, txt)
    ok &= check("все проблемы одним списком (не по первой)", len(errs) >= 7, str(len(errs)))
    errs2, _ = chf.validate_macro({"factors": macro()["factors"]}, ["A", "B"])
    ok &= check("нет baseline_spot", any("нет baseline_spot" in e for e in errs2), str(errs2))
    try:
        chf.factors_from_macro(m, ["A", "B"], AS_OF, ENDS)
        ok &= check("factors_from_macro отказывает", False)
    except ValueError as e:
        ok &= check("factors_from_macro: ValueError с перечнем", "usdrub_rate" in str(e) and "cnyrub_rate" in str(e))
    return ok


def test_pct_mismatch_warning():
    m = macro()
    m["factors"]["brent_price"]["by_scenario"]["A"]["2026-12-31"]["pct_vs_spot"] = -3.0   # по value −5.91
    errs, warns = chf.validate_macro(m, ["A", "B"])
    ok = check("расхождение > 0.5 п.п. — предупреждение, не отказ", errs == [] and len(warns) == 1
               and "brent_price, сценарий A, 2026-12-31" in warns[0] and "несогласован" in warns[0], str(warns))
    m["factors"]["brent_price"]["by_scenario"]["A"]["2026-12-31"]["pct_vs_spot"] = -5.5   # расхождение 0.41
    ok &= check("в пределах 0.5 п.п. — тихо", chf.validate_macro(m, ["A", "B"])[1] == [])
    return ok


def test_check_macro_cli():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        good = d / "good.yaml"
        good.write_text(yaml.safe_dump(macro(), allow_unicode=True), encoding="utf-8")
        r = subprocess.run([sys.executable, str(CHF), "--check-macro", str(good), "--scenarios", "A,B"],
                           capture_output=True, text=True)
        ok = check("годный файл: код 0 и «ок»", r.returncode == 0 and "ок" in r.stdout, r.stdout + r.stderr)
        r = subprocess.run([sys.executable, str(CHF), "--check-macro", str(good), "--scenarios", "A,B,C,D"],
                           capture_output=True, text=True)
        ok &= check("сценарии C, D отсутствуют: код 1 и перечень", r.returncode == 1 and "сценарий C" in r.stdout
                    and "сценарий D" in r.stdout, r.stdout)
        m = macro()
        m["factors"]["brent_price"]["by_scenario"]["A"]["2026-12-31"]["pct_vs_spot"] = 10
        bad = d / "w.yaml"
        bad.write_text(yaml.safe_dump(m, allow_unicode=True), encoding="utf-8")
        r = subprocess.run([sys.executable, str(CHF), "--check-macro", str(bad)], capture_output=True, text=True)
        ok &= check("предупреждения печатаются и при коде 0 (сценарии — из файла)",
                    r.returncode == 0 and "ПРЕДУПРЕЖДЕНИЕ" in r.stdout and "ок" in r.stdout, r.stdout)
        # дата без кавычек: YAML-парсер отдаёт date, не строку
        raw = good.read_text(encoding="utf-8").replace("'2026-12-31'", "2026-12-31")
        unq = d / "u.yaml"
        unq.write_text(raw, encoding="utf-8")
        r = subprocess.run([sys.executable, str(CHF), "--check-macro", str(unq), "--scenarios", "A,B"],
                           capture_output=True, text=True)
        ok &= check("ключи дат без кавычек принимаются", r.returncode == 0, r.stdout)
        return ok


TESTS = [test_check_numbers, test_grid_move_cases, test_validate_refusals, test_pct_mismatch_warning, test_check_macro_cli]


def main() -> int:
    passed = failed = 0
    for t in TESTS:
        print(f"\n[{t.__name__}]")
        try:
            ok = t()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            print(f"  ✗ {t.__name__}: {type(e).__name__}: {e}")
            ok = False
        passed += ok
        failed += not ok
    print(f"\n{'=' * 50}\nPassed: {passed}/{len(TESTS)}; Failed: {failed}")
    print(f"Итого: {passed} из {len(TESTS)}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
