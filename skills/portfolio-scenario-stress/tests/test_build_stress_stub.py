#!/usr/bin/env python3
"""Тесты для skills/portfolio-scenario-stress/scripts/build_stress_stub.py.

Запуск: python3 skills/portfolio-scenario-stress/tests/test_build_stress_stub.py
Зависимости: stdlib + pyyaml (для SSOT-чтения скриптом).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "skills/portfolio-scenario-stress/scripts/build_stress_stub.py"


def fake_snapshot() -> dict:
    return {
        "schema_version": "2.0",
        "as_of_date": "2026-05-12",
        "holdings": [
            {"ticker": "SBER", "name": "Сбербанк", "asset_type": "stock",
             "qty": 100, "value_rub": 32414.0, "account": "main",
             "is_blocked": False, "current_price_source": "moex_iss"},
        ],
        "balance_summary": {"total_current_rub_excl_iis": 100000.0},
    }


def fake_scenarios_ssot() -> str:
    """SSOT scenarios-{slug}.yaml — минимальный, с scenario_triggers."""
    return """\
schema_version: 1
type: scenario-events
matrix:
  date: 2026-05-04
  axis_x: "axis x"
  axis_y: "axis y"
scenario_triggers:
  - scenario_id: A
    label: "Bull case"
    probability: 0.30
  - scenario_id: B
    label: "Base case"
    probability: 0.40
  - scenario_id: C
    label: "Bear case"
    probability: 0.30
"""


def fake_macro_scenarios() -> str:
    return """\
schema_version: 2
type: macro-scenarios
scenarios:
  A:
    horizon_2027_12_31:
      brent_usd: 70
      usdrub: 80
      cbr_rate_pct: 11
  B:
    horizon_2027_12_31:
      brent_usd: 60
      usdrub: 95
      cbr_rate_pct: 13
"""


def run_script(snapshot: Path, scenarios: Path, output: Path,
               macro: Path | None = None, extra: list[str] | None = None) -> tuple[int, str]:
    args = [sys.executable, str(SCRIPT),
            "--snapshot", str(snapshot),
            "--scenarios", str(scenarios),
            "--output", str(output),
            "--today", "2026-05-12",
            "--slug", "test-shell"]
    if macro:
        args.extend(["--macro-scenarios", str(macro)])
    if extra:
        args.extend(extra)
    r = subprocess.run(args, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def check(label: str, cond: bool, detail: str = "") -> bool:
    if cond:
        print(f"  ✓ {label}")
        return True
    print(f"  ✗ {label}{(' — ' + detail) if detail else ''}")
    return False


def test_smoke_run():
    print("\n[test_smoke_run]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        sc = Path(td) / "scenarios.yaml"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(fake_snapshot()))
        sc.write_text(fake_scenarios_ssot())
        code, log = run_script(snap, sc, out)
        if not check("exit 0", code == 0, log[:200]):
            return False
        return check("output exists", out.exists())


def test_top_level_canonical():
    """schema_version: 1 (число), type: portfolio-stress-test (НЕ scenario), date в кавычках."""
    print("\n[test_top_level_canonical]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        sc = Path(td) / "scenarios.yaml"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(fake_snapshot()))
        sc.write_text(fake_scenarios_ssot())
        run_script(snap, sc, out)
        text = out.read_text()
        ok = True
        ok &= check("schema_version: 2 (число)",
                    re.search(r"^schema_version: 2$", text, re.MULTILINE) is not None)
        ok &= check("type: portfolio-stress-test (НЕ portfolio-scenario-stress)",
                    "type: portfolio-stress-test" in text and "type: portfolio-scenario-stress" not in text)
        ok &= check('date: "2026-05-12" в кавычках',
                    'date: "2026-05-12"' in text)
        ok &= check("scenario_source declared",
                    "scenario_source:" in text)
        ok &= check("weight_type declared",
                    "weight_type:" in text)
        return ok


def test_horizon_v2_fields():
    """v2: horizons/horizon_ends/primary_horizon; нет horizon_months/horizon."""
    print("\n[test_horizon_v2_fields]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        sc = Path(td) / "scenarios.yaml"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(fake_snapshot()))
        sc.write_text(fake_scenarios_ssot())
        run_script(snap, sc, out, extra=["--horizons", "12,20,36"])
        text = out.read_text()
        ok = True
        ok &= check("horizons: [12, 20, 36]", "horizons: [12, 20, 36]" in text)
        # date 2026-05-12 + 20 мес = конец 2028-01 = 2028-01-31
        ok &= check("horizon_ends.h20 == 2028-01-31", 'h20: "2028-01-31"' in text)
        # primary по умолчанию = 12 (в наборе [12,20,36])
        ok &= check("primary_horizon: 12", re.search(r"^primary_horizon: 12\b", text, re.MULTILINE) is not None)
        ok &= check("нет horizon_months", "horizon_months" not in text)
        ok &= check("нет horizon: (v1)", re.search(r"^horizon:", text, re.MULTILINE) is None)
        return ok


def test_factors_by_horizon_structure():
    """scenarios[X].factors_by_horizon.{hNN}.{factor} + portfolio_level_by_horizon."""
    print("\n[test_factors_by_horizon_structure]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        sc = Path(td) / "scenarios.yaml"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(fake_snapshot()))
        sc.write_text(fake_scenarios_ssot())
        run_script(snap, sc, out, extra=["--horizons", "12,20"])
        text = out.read_text()
        import yaml  # type: ignore
        d = yaml.safe_load(text)
        ok = True
        a = d["scenarios"]["A"]
        ok &= check("A.factors_by_horizon keys == h12,h20",
                    set(a.get("factors_by_horizon", {})) == {"h12", "h20"})
        ok &= check("A.factors_by_horizon.h12 содержит brent",
                    "brent" in (a.get("factors_by_horizon", {}).get("h12") or {}))
        ok &= check("A.portfolio_level_by_horizon keys == h12,h20",
                    set(a.get("portfolio_level_by_horizon", {})) == {"h12", "h20"})
        ok &= check("нет flat factors: (v1) на уровне сценария",
                    "factors" in a and "factors_by_horizon" in a and a.get("factors") is None
                    or "factors" not in a)
        return ok


def test_scenarios_name_p_not_label_probability():
    """В stub использованы name/p, НЕ label/probability (drift-anti-rename)."""
    print("\n[test_scenarios_name_p_not_label_probability]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        sc = Path(td) / "scenarios.yaml"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(fake_snapshot()))
        sc.write_text(fake_scenarios_ssot())
        run_script(snap, sc, out)
        text = out.read_text()
        ok = True
        # Scenarios block: name + p
        ok &= check("есть name: с Bull case",
                    re.search(r"^\s+name: \"Bull case\"", text, re.MULTILINE) is not None)
        ok &= check("есть p: 0.3 (НЕ probability:)",
                    re.search(r"^\s+p: 0\.3", text, re.MULTILINE) is not None)
        # No label/probability fields (только в комментариях допустимо)
        # Считаем только key occurrences вне комментариев
        non_comment_lines = "\n".join(
            line for line in text.split("\n")
            if not line.strip().startswith("#")
        )
        ok &= check("нет 'label:' ключа (drift)",
                    not re.search(r"^\s+label:", non_comment_lines, re.MULTILINE))
        ok &= check("нет 'probability:' ключа (drift)",
                    not re.search(r"^\s+probability:", non_comment_lines, re.MULTILINE))
        return ok


def test_portfolio_level_structure():
    """scenarios[X].portfolio_level_by_horizon.{hNN}: контракт баз расчёта
    (price_delta_rub/pct, carry_rub/pct, total_return_rub/pct) — не старая
    форма {delta_rub, expected_pct_pweighted}."""
    print("\n[test_portfolio_level_structure]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        sc = Path(td) / "scenarios.yaml"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(fake_snapshot()))
        sc.write_text(fake_scenarios_ssot())
        run_script(snap, sc, out)
        text = out.read_text()
        import yaml  # type: ignore
        data = yaml.safe_load(text)
        ok = True
        ok &= check("portfolio_level_by_horizon: блок присутствует",
                    "portfolio_level_by_horizon:" in text)
        for field in ("price_delta_rub", "price_delta_pct", "carry_rub", "carry_pct",
                      "total_return_rub", "total_return_pct"):
            ok &= check(f"{field} плейсхолдер",
                        re.search(rf"^\s+{field}: TODO_LLM", text, re.MULTILINE) is not None)
        # Скоуп на сам блок portfolio_level_by_horizon.
        cell = data["scenarios"]["A"]["portfolio_level_by_horizon"]["h6"]
        ok &= check("старое имя delta_rub (deprecated) отсутствует внутри portfolio_level_by_horizon",
                    "delta_rub" not in cell)
        ok &= check("старое имя expected_pct_pweighted (deprecated) отсутствует внутри portfolio_level_by_horizon",
                    "expected_pct_pweighted" not in cell)
        ok &= check("нет flat 'pnl_rub:' на уровне сценария (drift)",
                    not re.search(r"^    pnl_rub:", text, re.MULTILINE))
        return ok


def test_basis_contract_top_level_fields():
    """Контракт баз расчёта (§11.2a yaml-schemas.md): basis_contract,
    layers_included, per_position_basis, base_value_rub (реально посчитан,
    не TODO_LLM), base_value_note, p_basis — присутствуют физически."""
    print("\n[test_basis_contract_top_level_fields]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        sc = Path(td) / "scenarios.yaml"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(fake_snapshot()))
        sc.write_text(fake_scenarios_ssot())
        run_script(snap, sc, out)
        import yaml  # type: ignore
        data = yaml.safe_load(out.read_text())
        ok = True
        ok &= check("basis_contract == 1", data.get("basis_contract") == 1)
        ok &= check("layers_included.dividends is False",
                    data.get("layers_included", {}).get("dividends") is False)
        ok &= check("layers_included.price/bond_carry — True",
                    data["layers_included"]["price"] is True
                    and data["layers_included"]["bond_carry"] is True)
        ok &= check("per_position_basis == price", data.get("per_position_basis") == "price")
        ok &= check("base_value_rub == 32414 (SBER — единственный holding, кэша нет)",
                    data.get("base_value_rub") == 32414, str(data.get("base_value_rub")))
        ok &= check("base_value_note непустая строка", bool(data.get("base_value_note")))
        ok &= check("p_basis == primary_horizon (дефолт)", data.get("p_basis") == "primary_horizon")
        return ok


def test_portfolio_aggregates_and_robustness_carcasses():
    """portfolio_aggregates и robustness — каркасы с обеими базами и всеми
    горизонтами; deprecated-скаляры portfolio_pl_range_rub/expected_pl_rub
    (top-level) отсутствуют."""
    print("\n[test_portfolio_aggregates_and_robustness_carcasses]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        sc = Path(td) / "scenarios.yaml"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(fake_snapshot()))
        sc.write_text(fake_scenarios_ssot())
        run_script(snap, sc, out)
        text = out.read_text()
        import yaml  # type: ignore
        data = yaml.safe_load(text)
        ok = True
        for block_name in ("portfolio_aggregates", "robustness"):
            block = data.get(block_name)
            ok &= check(f"{block_name} присутствует и это dict", isinstance(block, dict))
            for basis in ("price", "total_return"):
                sub = (block or {}).get(basis)
                ok &= check(f"{block_name}.{basis}.basis == {basis}",
                            isinstance(sub, dict) and sub.get("basis") == basis)
        ok &= check("robustness.modal_scenario == none (соответствует modal_flag: no_modal)",
                    data.get("robustness", {}).get("modal_scenario") == "none")
        ok &= check("deprecated 'portfolio_pl_range_rub:' (top-level) отсутствует",
                    not re.search(r"^portfolio_pl_range_rub:", text, re.MULTILINE))
        ok &= check("deprecated 'expected_pl_rub:' (top-level) отсутствует",
                    not re.search(r"^expected_pl_rub:", text, re.MULTILINE))
        return ok


def test_factor_definitions_present():
    """factor_definitions содержит все 7 canonical факторов."""
    print("\n[test_factor_definitions_present]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        sc = Path(td) / "scenarios.yaml"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(fake_snapshot()))
        sc.write_text(fake_scenarios_ssot())
        run_script(snap, sc, out)
        text = out.read_text()
        canonical = ["sanctions", "geopol", "cbr_rate", "usdrub", "cnyrub", "brent", "xauusd"]
        ok = True
        # factor_definitions блок
        ok &= check("factor_definitions: блок",
                    "factor_definitions:" in text)
        for f in canonical:
            ok &= check(f"factor_definitions содержит {f}",
                        re.search(rf"^  {f}:\s*$", text, re.MULTILINE) is not None)
        # U3 (Фаза 4.1 Блок D): display_label у каждого фактора + человекочитаемая
        # шкала у sanctions; машинный unit intensity_-1_to_1 сохранён.
        ok &= check("display_label у всех 7 факторов",
                    len(re.findall(r"^    display_label: ", text, re.MULTILINE)) == 7)
        ok &= check("sanctions: unit intensity_-1_to_1",
                    re.search(r"^  sanctions:\n    unit: intensity_-1_to_1", text, re.MULTILINE) is not None)
        ok &= check("sanctions: display_label с шкалой −1…+1",
                    'display_label: "усл. шкала −1…+1"' in text)
        return ok


def test_no_portfolio_summary_block():
    """Стаб блок portfolio_summary не несёт: вьюер собирает худший/лучший сценарий из чисел сценариев."""
    print("\n[test_no_portfolio_summary_block]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        sc = Path(td) / "scenarios.yaml"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(fake_snapshot()))
        sc.write_text(fake_scenarios_ssot())
        run_script(snap, sc, out)
        text = out.read_text()
        ok = check("portfolio_summary в стабе нет", "portfolio_summary" not in text)
        ok &= check("sector_breakdown_pct остаётся плейсхолдером", "sector_breakdown_pct: TODO_LLM" in text)
        return ok


def test_macro_scenarios_hints_when_provided():
    """Когда --macro-scenarios передан, abs values попадают в комментарии."""
    print("\n[test_macro_scenarios_hints_when_provided]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        sc = Path(td) / "scenarios.yaml"
        macro = Path(td) / "macro.yaml"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(fake_snapshot()))
        sc.write_text(fake_scenarios_ssot())
        macro.write_text(fake_macro_scenarios())
        run_script(snap, sc, out, macro)
        text = out.read_text()
        # Comments under A scenario should mention brent_usd: 70 etc
        a_section = re.search(r"^  A:\n((?:    .+\n)+)", text, re.MULTILINE)
        if not check("A: scenario block found", bool(a_section)):
            return False
        block = a_section.group(1)
        ok = True
        ok &= check("brent_usd_absolute hint в комментарии для A",
                    "brent_usd_absolute: 70" in block)
        ok &= check("usdrub_absolute hint в комментарии для A",
                    "usdrub_absolute: 80" in block)
        return ok


def test_macro_input_link():
    """Шаг 14 (R22): ссылка стресс → макросценарии — поле macro_input = имя файла --macro-scenarios;
    без него — null («ссылка не записана»); второго поля macro_scenarios_file нет, версии прогнозов не копируются."""
    print("\n[test_macro_input_link]")
    import yaml  # type: ignore
    ok = True
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        sc = Path(td) / "scenarios.yaml"
        macro = Path(td) / "macro-scenarios-2026-10-04.yaml"
        snap.write_text(json.dumps(fake_snapshot()))
        sc.write_text(fake_scenarios_ssot())
        macro.write_text(fake_macro_scenarios())
        for anchored in (False, True):          # оба режима горизонтов
            out = Path(td) / f"stub-{anchored}.yaml"
            extra = ["--anchor-dates", "2027-06-30,2027-12-31"] if anchored else None
            code, log = run_script(snap, sc, out, macro, extra)
            d = yaml.safe_load(out.read_text())
            ok &= check(f"macro_input = имя файла (anchored={anchored})",
                        code == 0 and d.get("macro_input") == "macro-scenarios-2026-10-04.yaml", log[:200])
            ok &= check("нет macro_scenarios_file (R22)", "macro_scenarios_file" not in d)
            ok &= check("нет копий прогнозов (forecast_files/forecast_versions)",
                        "forecast_files" not in d and "forecast_versions" not in d)
        out = Path(td) / "stub-nomacro.yaml"
        run_script(snap, sc, out)
        d = yaml.safe_load(out.read_text())
        ok &= check("без --macro-scenarios — macro_input: null", "macro_input" in d and d["macro_input"] is None)
    return ok


def test_yaml_parses_via_pyyaml():
    print("\n[test_yaml_parses_via_pyyaml]")
    try:
        import yaml  # type: ignore
    except ImportError:
        print("  ⊘ PyYAML not installed — skip")
        return True
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        sc = Path(td) / "scenarios.yaml"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(fake_snapshot()))
        sc.write_text(fake_scenarios_ssot())
        run_script(snap, sc, out)
        text = out.read_text()
        try:
            d = yaml.safe_load(text)
        except yaml.YAMLError as e:
            print(f"  ✗ YAML parse: {e}")
            return False
        ok = True
        ok &= check("schema_version == 2 int", d.get("schema_version") == 2)
        ok &= check("horizons == [6,12,24] (default)", d.get("horizons") == [6, 12, 24])
        ok &= check("type == portfolio-stress-test", d.get("type") == "portfolio-stress-test")
        ok &= check("scenarios has A/B/C", set(d["scenarios"].keys()) == {"A", "B", "C"})
        ok &= check("A.name == Bull case", d["scenarios"]["A"]["name"] == "Bull case")
        ok &= check("A.p == 0.30", d["scenarios"]["A"]["p"] == 0.3)
        return ok


def test_horizon_mode_rolling_present():
    """A4: стаб --horizons выдаёт horizon_mode: rolling."""
    print("\n[test_horizon_mode_rolling_present]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        sc = Path(td) / "scenarios.yaml"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(fake_snapshot()))
        sc.write_text(fake_scenarios_ssot())
        run_script(snap, sc, out)
        text = out.read_text()
        return check("horizon_mode: rolling присутствует",
                     re.search(r"^horizon_mode: rolling\b", text, re.MULTILINE) is not None)


def test_horizon_mode_anchored_present():
    """A4: стаб --anchor-dates выдаёт horizon_mode: anchored."""
    print("\n[test_horizon_mode_anchored_present]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        sc = Path(td) / "scenarios.yaml"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(fake_snapshot()))
        sc.write_text(fake_scenarios_ssot())
        code, log = run_script(snap, sc, out, extra=["--anchor-dates", "2027-06-30"])
        if not check("exit 0", code == 0, log[:200]):
            return False
        text = out.read_text()
        return check("horizon_mode: anchored присутствует",
                     re.search(r"^horizon_mode: anchored\b", text, re.MULTILINE) is not None)


def _ssot_with_pbh(cover: tuple[str, ...] = ("h6", "h12", "h24")) -> str:
    """SSOT с горизонтными весами. `cover` — какие горизонты покрыты блоком."""
    w = {"A": {"h6": 0.28, "h12": 0.15, "h24": 0.24},
         "B": {"h6": 0.12, "h12": 0.15, "h24": 0.16},
         "C": {"h6": 0.60, "h12": 0.70, "h24": 0.60}}
    scal = {"A": 0.15, "B": 0.15, "C": 0.70}
    out = ["schema_version: 1", "type: scenario-events", "matrix:",
           "  date: 2026-05-04", '  axis_x: "axis x"', '  axis_y: "axis y"',
           "scenario_triggers:"]
    for sid in ("A", "B", "C"):
        out += [f"  - scenario_id: {sid}", f'    label: "Case {sid}"',
                f"    probability: {scal[sid]}"]
        if cover:
            out.append("    p_by_horizon:")
            out += [f"      {hk}: {w[sid][hk]}" for hk in cover]
    return "\n".join(out) + "\n"


def test_p_by_horizon_carried_from_ssot():
    """
    [РАЗЛИЧИТЕЛЬ] PSS-9: горизонтные веса доезжают из SSOT в стресс-стаб.

    До 2026-08-05 `extract_scenarios_from_ssot` брала только скаляр
    `probability`. Веса можно было записать в матрицу, но на числа они не
    влияли: стресс считал ВСЕ горизонты по скаляру — на h6 применялось
    убеждение с h12, и это выглядело как нормальный прогон.

    Реализация без проводки даёт стаб без `p_by_horizon` и падает здесь.
    """
    print("\n[test_p_by_horizon_carried_from_ssot]")
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "snap.json").write_text(json.dumps(fake_snapshot()), encoding="utf-8")
        (d / "sc.yaml").write_text(_ssot_with_pbh(), encoding="utf-8")
        rc, log = run_script(d / "snap.json", d / "sc.yaml", d / "out.yaml",
                             extra=["--horizons", "6,12,24"])
        ok &= check("exit 0", rc == 0, log[-300:])
        import yaml  # type: ignore
        doc = yaml.safe_load((d / "out.yaml").read_text(encoding="utf-8"))
        scen = doc.get("scenarios") or {}
        ok &= check("p_by_horizon перенесён всем сценариям",
                    all(isinstance(scen.get(s, {}).get("p_by_horizon"), dict)
                        for s in ("A", "B", "C")), str(scen.get("A")))
        ok &= check("значения совпадают с SSOT",
                    scen["A"]["p_by_horizon"] == {"h6": 0.28, "h12": 0.15, "h24": 0.24},
                    str(scen["A"].get("p_by_horizon")))
        ok &= check("скаляр p сохранён рядом (деградация + диагностика)",
                    scen["A"]["p"] == 0.15, str(scen["A"].get("p")))
        # Суммы по горизонтам — 1.0, иначе гард контракта остановит прогон.
        for hk in ("h6", "h12", "h24"):
            s = round(sum(scen[x]["p_by_horizon"][hk] for x in ("A", "B", "C")), 6)
            ok &= check(f"Σ весов на {hk} = 1", s == 1.0, str(s))
    return ok


def test_p_by_horizon_absent_stays_scalar():
    """Обратная совместимость: SSOT без блока → стаб как раньше, без поля."""
    print("\n[test_p_by_horizon_absent_stays_scalar]")
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "snap.json").write_text(json.dumps(fake_snapshot()), encoding="utf-8")
        (d / "sc.yaml").write_text(fake_scenarios_ssot(), encoding="utf-8")
        rc, _ = run_script(d / "snap.json", d / "sc.yaml", d / "out.yaml")
        ok &= check("exit 0", rc == 0)
        import yaml  # type: ignore
        doc = yaml.safe_load((d / "out.yaml").read_text(encoding="utf-8"))
        ok &= check("поля p_by_horizon нет",
                    all("p_by_horizon" not in (doc["scenarios"].get(s) or {})
                        for s in doc["scenarios"]))
    return ok


def test_p_by_horizon_partial_coverage_refused():
    """
    Блок, покрывающий не все горизонты прогона, НЕ переносится — вместо весов
    в стаб идёт предупреждение.

    Движок на смешанном входе останавливается (смешивать горизонтные веса со
    скаляром нельзя), поэтому перенести половину значило бы выдать заведомо
    неработающий стаб. Молча уронить блок — тоже нельзя: пользователь записал
    веса в SSOT и вправе узнать, почему они не доехали.
    """
    print("\n[test_p_by_horizon_partial_coverage_refused]")
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "snap.json").write_text(json.dumps(fake_snapshot()), encoding="utf-8")
        (d / "sc.yaml").write_text(_ssot_with_pbh(cover=("h6", "h12")), encoding="utf-8")
        rc, _ = run_script(d / "snap.json", d / "sc.yaml", d / "out.yaml",
                           extra=["--horizons", "6,12,24"])
        ok &= check("exit 0", rc == 0)
        import yaml  # type: ignore
        text = (d / "out.yaml").read_text(encoding="utf-8")
        doc = yaml.safe_load(text)
        ok &= check("веса не перенесены",
                    all("p_by_horizon" not in (doc["scenarios"].get(s) or {})
                        for s in doc["scenarios"]))
        ok &= check("причина названа в стабе, а не проглочена",
                    "p_by_horizon в SSOT есть, но не покрывает" in text
                    and "h24" in text)
    return ok


def test_plan_bucket_key_traceability_comment():
    """PSS-14: plan_bucket_key прокинут в комментарий-подсказку рядом с
    per_position (traceability, необязательное поле — НЕ часть схемы стаба)."""
    print("\n[test_plan_bucket_key_traceability_comment]")
    with tempfile.TemporaryDirectory() as td:
        snap_data = fake_snapshot()
        snap_data["holdings"].append({
            "ticker": "RU000A1038V6", "name": "ОФЗ 26238", "asset_type": "bond",
            "qty": 80, "value_rub": 60000.0, "account": "main",
            "is_blocked": False, "plan_bucket_key": "ОФЗ/>10",
        })
        snap = Path(td) / "snap.json"
        sc = Path(td) / "scenarios.yaml"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(snap_data))
        sc.write_text(fake_scenarios_ssot())
        run_script(snap, sc, out)
        text = out.read_text()
        ok = True
        ok &= check("комментарий-подсказка присутствует",
                    "plan_bucket_key по облигациям снапшота" in text)
        ok &= check("тикер + корзина в комментарии",
                    "#   RU000A1038V6 (ОФЗ 26238): ОФЗ/>10" in text)

        # Без облигаций в снапшоте — блока-подсказки нет (не мусорит стаб).
        out2 = Path(td) / "stub2.yaml"
        snap2 = Path(td) / "snap2.json"
        snap2.write_text(json.dumps(fake_snapshot()))
        run_script(snap2, sc, out2)
        text2 = out2.read_text()
        ok &= check("нет облигаций в снапшоте → комментарий-подсказка отсутствует",
                    "plan_bucket_key по облигациям снапшота" not in text2)
        return ok


TESTS = [
    test_smoke_run,
    test_top_level_canonical,
    test_horizon_v2_fields,
    test_factors_by_horizon_structure,
    test_scenarios_name_p_not_label_probability,
    test_portfolio_level_structure,
    test_basis_contract_top_level_fields,
    test_portfolio_aggregates_and_robustness_carcasses,
    test_factor_definitions_present,
    test_no_portfolio_summary_block,
    test_macro_scenarios_hints_when_provided,
    test_macro_input_link,
    test_yaml_parses_via_pyyaml,
    test_horizon_mode_rolling_present,
    test_horizon_mode_anchored_present,
    test_p_by_horizon_carried_from_ssot,
    test_p_by_horizon_absent_stays_scalar,
    test_p_by_horizon_partial_coverage_refused,
    test_plan_bucket_key_traceability_comment,
]


def main() -> int:
    if not SCRIPT.exists():
        print(f"ERROR: {SCRIPT} not found")
        return 1
    passed = failed = 0
    for t in TESTS:
        try:
            ok = t()
        except Exception as e:
            print(f"  ✗ {t.__name__}: {type(e).__name__}: {e}")
            ok = False
        if ok:
            passed += 1
        else:
            failed += 1
    print(f"\n{'=' * 50}\nPassed: {passed}/{len(TESTS)}; Failed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
