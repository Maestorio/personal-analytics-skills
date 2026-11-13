#!/usr/bin/env python3
"""Тесты для skills/ru-portfolio-advisor/scripts/build_weekly_bond_stub.py.

Запуск: python3 skills/ru-portfolio-advisor/tests/test_build_weekly_bond_stub.py
Использует --no-moex-fetch для offline-тестирования (без сетевых зависимостей).

Зависимости: stdlib only.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "skills/ru-portfolio-advisor/scripts/build_weekly_bond_stub.py"


def make_fake_snapshot() -> dict:
    """Snapshot v2 с 4 bonds: 2 RU (один split main+iis_3) + 1 USD + 1 EUR.

    plan_bucket/plan_subtype/plan_bucket_key/credit_rating_file — как их
    кладёт portfolio-data-loader (PDL-4, волна 1, RPA-13/14)."""
    return {
        "schema_version": "2.0",
        "as_of_date": "2026-05-12",
        "generated_at": "2026-05-12T10:00:00Z",
        "holdings": [
            # OFZ split: main + iis_3
            {
                "ticker": "RU000A1038V6", "name": "ОФЗ 78714",
                "asset_type": "bond", "qty": 80.0, "value_rub": 180000.0,
                "account": "main", "is_blocked": False,
                "nominal_currency": "RUB", "ytm_pct": None,
                "current_price_source": "moex_iss",
                "plan_bucket": "ОФЗ", "plan_subtype": ">10",
                "plan_bucket_key": "ОФЗ/>10", "credit_rating_file": None,
            },
            {
                "ticker": "RU000A1038V6", "name": "ОФЗ 78714",
                "asset_type": "bond", "qty": 130.0, "value_rub": 300000.0,
                "account": "iis_3", "is_blocked": False,
                "nominal_currency": "RUB", "ytm_pct": None,
                "plan_bucket": "ОФЗ", "plan_subtype": ">10",
                "plan_bucket_key": "ОФЗ/>10", "credit_rating_file": None,
            },
            # Корпоративная RUB
            {
                "ticker": "RU000A106E90", "name": "ОФЗ 78729",
                "asset_type": "bond", "qty": 700.0, "value_rub": 1590000.0,
                "account": "main", "is_blocked": False,
                "nominal_currency": "RUB",
                "plan_bucket": "ОФЗ", "plan_subtype": "<10",
                "plan_bucket_key": "ОФЗ/<10", "credit_rating_file": None,
            },
            # FX replacement USD
            {
                "ticker": "RU000A105KU0", "name": "ГазКЗ-29Д",
                "asset_type": "bond", "qty": 9.0, "value_rub": 1795770.0,
                "account": "main", "is_blocked": False,
                "nominal_currency": "USD",
                "current_price_source": "moex_iss",
                "plan_bucket": "USD", "plan_subtype": None,
                "plan_bucket_key": "USD", "credit_rating_file": None,
            },
            # FX replacement EUR
            {
                "ticker": "RU000A105RZ4", "name": "ГазКЗ-27Е",
                "asset_type": "bond", "qty": 5.0, "value_rub": 1440000.0,
                "account": "main", "is_blocked": False,
                "nominal_currency": "EUR",
                "plan_bucket": "EUR", "plan_subtype": None,
                "plan_bucket_key": "EUR", "credit_rating_file": None,
            },
            # Stock — не должен попасть
            {
                "ticker": "SBER", "name": "Сбербанк",
                "asset_type": "stock", "qty": 100.0, "value_rub": 97242.0,
                "current_price_source": "moex_iss",
                "account": "main", "is_blocked": False,
            },
        ],
        "returns": {
            "by_type": {"bond": {"xirr": 0.0936, "pnl_rub": 3919632.78, "roi": 0.1233}},
        },
        "ie_model": {"positions": []},
        "ie_actual": {"per_ticker": {}},
        "ie_summary": {},
        "balance_summary": {
            "total_current_rub_excl_iis": 15000000.0,
            "iis_balance_rub": 1500000.0,
            "by_account": {
                "main": {
                    "total_rub": 15000000.0,
                    "stocks_rub": 300000.0,
                    "bonds_rub": 5005770.0,
                    "cash_rub": 9694230.0,
                },
                "iis_3": {
                    "total_rub": 1500000.0,
                    "bonds_rub": 300000.0,
                    "cash_rub": 1200000.0,
                },
            },
            "goals_overall": [
                {"Тип": "Облигация", "Доля": 0.5},
                {"Тип": "Акции", "Доля": 0.4},
            ],
        },
    }


def run_script(snapshot: Path, output: Path, today: str = "2026-05-12",
               extra: list[str] | None = None) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT),
         "--snapshot", str(snapshot),
         "--output", str(output),
         "--today", today,
         "--no-moex-fetch", *(extra or [])],
        capture_output=True, text=True,
    )
    return result.returncode, result.stdout + result.stderr


# ============================================================
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
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        code, log = run_script(snap, out)
        if not check("exit code == 0", code == 0, log[:200]):
            return False
        if not check("output exists", out.exists()):
            return False
        return check("output non-empty", out.stat().st_size > 500)


def test_top_level_canonical_types():
    print("\n[test_top_level_canonical_types]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        ok = True
        ok &= check("schema_version: 2 (число)", re.search(r"^schema_version: 2$", text, re.MULTILINE) is not None)
        ok &= check("type: weekly-bonds-review", "type: weekly-bonds-review" in text)
        ok &= check('review_date: "2026-05-12" в кавычках', 'review_date: "2026-05-12"' in text)
        ok &= check("primary_horizon: 12", re.search(r"^primary_horizon: 12\b", text, re.MULTILINE) is not None)
        return ok


def test_horizon_v2_fields():
    """v2 default 6-12-24: horizons список + horizon_ends (конец месяца)."""
    print("\n[test_horizon_v2_fields]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        run_script(snap, out)  # review_date=2026-05-12, default [6,12,24]
        text = out.read_text()
        ok = True
        ok &= check("horizons: [6, 12, 24]", "horizons: [6, 12, 24]" in text)
        ok &= check("h6 → 2026-11-30", 'h6: "2026-11-30"' in text)
        ok &= check("h12 → 2027-05-31", 'h12: "2027-05-31"' in text)
        ok &= check("h24 → 2028-05-31", 'h24: "2028-05-31"' in text)
        return ok


def test_no_v1_horizon_fields():
    """v2 НЕ содержит v1-полей horizon_months / horizon / in_horizon."""
    print("\n[test_no_v1_horizon_fields]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        ok = True
        ok &= check("нет horizon_months", "horizon_months" not in text)
        # v1 top-level bond поле было `horizon:` (не horizon_end). horizon_ends: (v2) — OK.
        ok &= check("нет horizon: (v1, не horizon_ends)",
                    re.search(r"^horizon:", text, re.MULTILINE) is None)
        ok &= check("нет in_horizon (catalyst)", "in_horizon" not in text)
        ok &= check("date_window остался в catalyst", "date_window: TODO_LLM" in text)
        return ok


def test_anchor_dates_mode():
    """--anchor-dates: N = месяцы до цели (review_date=2026-05-12, цель 2028-05-31 → 24 мес)."""
    print("\n[test_anchor_dates_mode]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        code, log = run_script(snap, out, extra=["--anchor-dates", "2028-05-31"])
        if not check("exit 0", code == 0, log[:200]):
            return False
        text = out.read_text()
        ok = True
        ok &= check("horizons: [24]", "horizons: [24]" in text)
        ok &= check("horizon_ends.h24 = 2028-05-31", 'h24: "2028-05-31"' in text)
        ok &= check("primary_horizon 24", re.search(r"^primary_horizon: 24\b", text, re.MULTILINE) is not None)
        return ok


def test_per_bond_population():
    print("\n[test_per_bond_population]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        # ISINs
        isins = re.findall(r"^  ([A-Z]{2}[A-Z0-9]{8,12}):\s*$", text, re.MULTILINE)
        ok = True
        ok &= check("RU000A1038V6 присутствует", "RU000A1038V6" in isins)
        ok &= check("RU000A106E90 присутствует", "RU000A106E90" in isins)
        ok &= check("RU000A105KU0 присутствует", "RU000A105KU0" in isins)
        ok &= check("RU000A105RZ4 присутствует", "RU000A105RZ4" in isins)
        ok &= check("SBER (stock) отсутствует", "SBER" not in isins)
        ok &= check("4 уникальных bond entries (split merged)", len(isins) == 4, f"got {isins}")
        return ok


def test_split_merge_iis():
    """ОФЗ 78714 main + iis_3 → один merged entry с qty_main/qty_iis/iis_share_pct."""
    print("\n[test_split_merge_iis]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        m = re.search(r"^  RU000A1038V6:\n((?:    .+\n)+)", text, re.MULTILINE)
        if not check("split OFZ block found", bool(m)):
            return False
        block = m.group(1)
        ok = True
        # qty = 80 + 130 = 210
        ok &= check("qty == 210 (merged)", "qty: 210" in block)
        ok &= check("qty_main == 80", "qty_main: 80" in block)
        ok &= check("qty_iis == 130", "qty_iis: 130" in block)
        # value_rub = 180000 + 300000 = 480000
        ok &= check("value_rub == 480000", "value_rub: 480000" in block)
        ok &= check("value_rub_main == 180000", "value_rub_main: 180000" in block)
        ok &= check("value_rub_iis == 300000", "value_rub_iis: 300000" in block)
        # on_iis: false (qty_main>0) + iis_share_pct: 100000/160000=62.5%
        ok &= check("on_iis == false (есть main часть)", "on_iis: false" in block)
        ok &= check("iis_share_pct == 62.50", "iis_share_pct: 62.50" in block)
        return ok


def test_bond_type_heuristic():
    print("\n[test_bond_type_heuristic]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        ok = True
        # ОФЗ → ofz (по name)
        m_ofz = re.search(r"^  RU000A106E90:\n((?:    .+\n)+)", text, re.MULTILINE)
        if m_ofz:
            ok &= check("ОФЗ 78729 → bond_type: ofz", "bond_type: ofz" in m_ofz.group(1))
        # USD ГазКЗ → fx_replacement
        m_usd = re.search(r"^  RU000A105KU0:\n((?:    .+\n)+)", text, re.MULTILINE)
        if m_usd:
            ok &= check("USD bond → bond_type: fx_replacement",
                        "bond_type: fx_replacement" in m_usd.group(1))
        return ok


def test_bond_type_sur_is_rub():
    """Регрессия 2026-07-31: MOEX ISS отдаёт рубль кодом SUR — рублёвый корпорат
    обязан классифицироваться corp_rub, а не fx_replacement (до фикса ветка
    corp_rub была недостижима и все 22 рублёвых корпората уходили в замещайки)."""
    print("\n[test_bond_type_sur_is_rub]")
    import importlib.util
    spec = importlib.util.spec_from_file_location("bond_stub", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    f = mod.derive_bond_type
    ok = True
    ok &= check("SUR корпорат → corp_rub", f("Атомэнпр08", "SUR", None) == "corp_rub")
    ok &= check("RUB корпорат → corp_rub", f("Атомэнпр08", "RUB", None) == "corp_rub")
    ok &= check("USD → fx_replacement", f("ГазКЗ-29Д", "USD", None) == "fx_replacement")
    ok &= check("SUR + «замещ» в имени → fx_replacement",
                f("Замещающая X", "SUR", None) == "fx_replacement")
    ok &= check("SUR флоатер → floater", f("Бумага плав. купон", "SUR", None) == "floater")
    ok &= check("ОФЗ приоритетнее валюты", f("ОФЗ 78729", "SUR", None) == "ofz")
    return ok


def test_summary_aggregates():
    print("\n[test_summary_aggregates]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        # positions_reviewed: 4 unique ISIN, position_lines: 5 (split = 2 lines)
        ok = True
        ok &= check("positions_reviewed: 4", "positions_reviewed: 4" in text)
        ok &= check("position_lines: 5 (split-aware)", "position_lines: 5" in text)
        ok &= check("positions_on_iis: 1 (только split-OFZ имеет iis-долю)",
                    "positions_on_iis: 1" in text)
        # bonds_total_rub: 180000+300000+1590000+1795770+1440000 = 5305770
        ok &= check("bonds_total_rub: 5305770.00", "bonds_total_rub: 5305770.00" in text)
        ok &= check("total_value_rub alias", "total_value_rub: 5305770.00" in text)
        ok &= check("target_share_pct: 50.00", "target_share_pct: 50.00" in text)
        return ok


def test_anti_drift_naming():
    """Нет drift-имён в bond stub."""
    print("\n[test_anti_drift_naming]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        ok = True
        # bonds_total_rub: present at top (legit; also has alias total_value_rub)
        # но в per_bond entries — share_actual_pct etc. не должно быть
        ok &= check("нет share_actual_pct: в per_bond",
                    not re.search(r"^    share_actual_pct:", text, re.MULTILINE))
        ok &= check("нет delta_pct: в per_bond",
                    not re.search(r"^    delta_pct:", text, re.MULTILINE))
        ok &= check("нет 'catalysts:' (с s) ключа",
                    "catalysts:" not in text)
        ok &= check("есть 'catalyst:' (правильный)",
                    "catalyst:" in text)
        return ok


def test_todo_llm_placeholders():
    print("\n[test_todo_llm_placeholders]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        ok = True
        ok &= check("credit_rating TODO_LLM", "credit_rating: TODO_LLM" in text)
        ok &= check("credit_rating_checked_at: null у каждой бумаги",
                    text.count("credit_rating_checked_at: null") == text.count("credit_rating_agency:"))
        ok &= check("credit_quality TODO_LLM", "credit_quality: TODO_LLM" in text)
        ok &= check("issuer TODO_LLM", "issuer: TODO_LLM" in text)
        ok &= check("advisor_verdict TODO_LLM", "advisor_verdict: TODO_LLM" in text)
        # R28: приоритет ставит stamp-report, не модель; копии гейта в стабе нет
        ok &= check("verification_priority: null (ставит штамп), не TODO_LLM",
                    "verification_priority: null" in text and "verification_priority: TODO_LLM" not in text)
        ok &= check("gate_status_snapshot в стабе нет", "gate_status_snapshot" not in text)
        # MOEX data placeholders при --no-moex-fetch
        ok &= check("ytm_pct: null или число (без MOEX → null)",
                    re.search(r"^    ytm_pct: (null|TODO|[\d\.\-]+)", text, re.MULTILINE) is not None)
        return ok


def test_yaml_parses_via_pyyaml_if_available():
    print("\n[test_yaml_parses_via_pyyaml_if_available]")
    try:
        import yaml  # type: ignore
    except ImportError:
        print("  ⊘ PyYAML not installed — skip")
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
            print(f"  ✗ YAML parse: {e}")
            return False
        ok = True
        ok &= check("schema_version == 2 int", d.get("schema_version") == 2)
        ok &= check("horizons == [6,12,24]", d.get("horizons") == [6, 12, 24])
        ok &= check("primary_horizon == 12", d.get("primary_horizon") == 12)
        ok &= check("type == weekly-bonds-review", d.get("type") == "weekly-bonds-review")
        ok &= check("per_bond has 4 unique entries", len(d.get("per_bond", {})) == 4)
        # Split merge
        ofz = d["per_bond"].get("RU000A1038V6")
        ok &= check("OFZ.qty == 210", ofz and ofz.get("qty") == 210)
        ok &= check("OFZ.qty_iis == 130", ofz and ofz.get("qty_iis") == 130)
        return ok


def test_missing_snapshot_rejected():
    print("\n[test_missing_snapshot_rejected]")
    with tempfile.TemporaryDirectory() as td:
        code, _ = run_script(Path(td) / "missing.json", Path(td) / "out.yaml")
        return check("exit 1 для missing snapshot", code == 1)


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


def make_full_snapshot() -> dict:
    """Снапшот с полными облигационными полями — как их кладёт portfolio-data-loader.

    Нужен для проверки fallback MOEX→снапшот: с --no-moex-fetch единственным
    источником ytm/duration/maturity остаётся снапшот. Валюта рублёвых выпусков
    записана как SUR — ровно так её отдаёт загрузчик (см. norm_currency).

    ОФЗ 78714 разложена main 180 000 + ИИС-3 300 000, чтобы срез main-only
    отличался от полного (прецедент 15.08: рублёвая доходность считалась
    main-only, валютная — по всей корзине, и числа сравнивались между собой).
    """
    snap = make_fake_snapshot()
    fields = {
        "RU000A1038V6": {"ytm_pct": 15.0, "duration_days": 1000,
                         "maturity_date": "2041-05-15", "coupon_pct": 7.1,
                         "nominal_currency": "SUR"},
        "RU000A106E90": {"ytm_pct": 21.0, "duration_days": 1400,
                         "maturity_date": "2038-05-19", "coupon_pct": 9.8,
                         "nominal_currency": "SUR"},
        "RU000A105KU0": {"ytm_pct": 8.0, "duration_days": 600,
                         "maturity_date": "2029-11-24", "coupon_pct": 4.6,
                         "nominal_currency": "USD"},
        "RU000A105RZ4": {"ytm_pct": 6.0, "duration_days": 180,
                         "maturity_date": "2027-02-17", "coupon_pct": 3.5,
                         "nominal_currency": "EUR"},
    }
    for h in snap["holdings"]:
        extra = fields.get(h.get("ticker"))
        if extra and h.get("asset_type") == "bond":
            h.update(extra)
    return snap


def _summary_block(text: str) -> str:
    start = text.index("  weighted_ytm_pct:")
    end = text.index("  returns:", start)
    return text[start:end]


def test_snapshot_fallback_fills_bond_fields():
    print("\n[test_snapshot_fallback_fills_bond_fields]")
    with tempfile.TemporaryDirectory() as td:
        snap, out = Path(td) / "snap.json", Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_full_snapshot()))
        run_script(snap, out)  # --no-moex-fetch: только снапшот
        text = out.read_text()
        ok = True
        ok &= check("maturity_date взят из снапшота (нет TODO)",
                    "maturity_date: TODO_LLM" not in text)
        ok &= check("ytm_pct заполнен", re.search(r"^    ytm_pct: 21\.0", text, re.M) is not None)
        ok &= check("duration_days заполнен",
                    re.search(r"^    duration_days: 1400", text, re.M) is not None)
        ok &= check("ytm_source помечен как snapshot, не moex_iss",
                    re.search(r'^    ytm_source: "?(snapshot|moex_iss)"?', text, re.M) is not None
                    and "moex_iss" not in _summary_block(text))
        return ok


def test_sur_normalized_to_rub():
    print("\n[test_sur_normalized_to_rub]")
    with tempfile.TemporaryDirectory() as td:
        snap, out = Path(td) / "snap.json", Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_full_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        ok = True
        ok &= check("nominal_currency: SUR не попал в стаб",
                    not re.search(r"^    nominal_currency: \"?SUR", text, re.M))
        ok &= check("рублёвый срез назван rub, не sur",
                    "weighted_ytm_rub_pct:" in text and "weighted_ytm_sur_pct:" not in text)
        return ok


def test_summary_aggregates_computed():
    print("\n[test_summary_aggregates_computed]")
    with tempfile.TemporaryDirectory() as td:
        snap, out = Path(td) / "snap.json", Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_full_snapshot()))
        run_script(snap, out)
        block = _summary_block(out.read_text())
        ok = True
        ok &= check("weighted_ytm_pct.value посчитан",
                    re.search(r"value: \d+\.\d+", block) is not None)
        ok &= check("weighted_duration_days посчитан",
                    re.search(r"weighted_duration_days: \d+", block) is not None)
        ok &= check("by_type_pct раскрыт словарём", "by_type_pct: TODO_LLM" not in block)
        ok &= check("maturity_ladder_pct раскрыт", "maturity_ladder_pct: TODO_LLM" not in block)
        ok &= check("ci_pct остаётся за LLM", "ci_pct: TODO_LLM" in block)
        ok &= check("by_credit_quality_pct остаётся за LLM",
                    "by_credit_quality_pct: TODO_LLM" in block)
        # Ручной контроль: RUB-срез по всей корзине = (15.0×480000 + 21.0×1590000)/690000
        expected = (15.0 * 480000 + 21.0 * 1590000) / 2070000
        m = re.search(r"weighted_ytm_rub_pct: ([\d.]+)", block)
        ok &= check(f"RUB-срез совпал с ручным счётом ({expected:.4f})",
                    m is not None and abs(float(m.group(1)) - expected) < 0.001,
                    detail=m.group(1) if m else "не найден")
        return ok


def test_main_only_scope_differs_from_all():
    print("\n[test_main_only_scope_differs_from_all]")
    with tempfile.TemporaryDirectory() as td:
        snap, out = Path(td) / "snap.json", Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_full_snapshot()))
        run_script(snap, out)
        block = _summary_block(out.read_text())
        ok = True
        ok &= check("main-only срез присутствует", "weighted_ytm_pct_main_only:" in block)
        ok &= check("по-валютный main-only присутствует",
                    "weighted_ytm_rub_pct_main_only:" in block)
        # main-only исключает 300 000 ₽ ОФЗ 78714 на ИИС-3:
        # (15.0×180000 + 21.0×1590000)/590000 ≠ полному срезу
        expected_main = (15.0 * 180000 + 21.0 * 1590000) / 1770000
        m = re.search(r"weighted_ytm_rub_pct_main_only: ([\d.]+)", block)
        ok &= check(f"main-only RUB совпал с ручным счётом ({expected_main:.4f})",
                    m is not None and abs(float(m.group(1)) - expected_main) < 0.001,
                    detail=m.group(1) if m else "не найден")
        m_all = re.search(r"weighted_ytm_rub_pct: ([\d.]+)", block)
        ok &= check("срезы действительно различаются (иначе тест бессмыслен)",
                    m and m_all and abs(float(m.group(1)) - float(m_all.group(1))) > 0.01)
        ok &= check("предупреждение о сравнении разных срезов на месте",
                    "сравнивать между собой только числа ОДНОГО среза" in block)
        ok &= check("срез назван в комментарии (иначе рамка остаётся неявной)",
                    "_main_only — без ИИС-3" in block)
        return ok


def test_ofz_fields_prefilled():
    print("\n[test_ofz_fields_prefilled]")
    with tempfile.TemporaryDirectory() as td:
        snap, out = Path(td) / "snap.json", Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_full_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        ofz = text[text.index("  RU000A106E90:"):]
        ofz = ofz[:ofz.index("\n  RU000") if "\n  RU000" in ofz[1:] else len(ofz)]
        ok = True
        ok &= check("ОФЗ: issuer = Минфин России", "Минфин России" in ofz)
        ok &= check("ОФЗ: credit_quality HIGH", "credit_quality: HIGH" in ofz)
        ok &= check("ОФЗ: verification_priority не задан правилом стаба (ставит штамп, R28)",
                    "verification_priority: null" in ofz)
        ok &= check("корпоративные по-прежнему TODO_LLM",
                    "credit_quality: TODO_LLM" in text and "issuer: TODO_LLM" in text)
        return ok


def test_maturity_ladder_has_no_unknown_bucket():
    print("\n[test_maturity_ladder_has_no_unknown_bucket]")
    with tempfile.TemporaryDirectory() as td:
        snap, out = Path(td) / "snap.json", Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_full_snapshot()))
        run_script(snap, out)
        block = _summary_block(out.read_text())
        ok = check("нет корзины unknown при известных датах погашения",
                   "'unknown':" not in block)
        ok &= check("покрытие 100%", "покрытие 100.0%" in block)
        return ok


# ============================================================
# RPA-13/14: plan_bucket/plan_subtype/credit_rating_file/is_floater
# ============================================================

def make_floater_snapshot() -> dict:
    """Снапшот для RPA-14: ОФЗ-ПК (флоатер по plan_subtype, bond_type должен
    остаться ofz), корп-бумага-флоатер по имени (эвристика-fallback, без
    plan_subtype=Флоат), обычный корп с рейтингом из файла (не флоатер)."""
    return {
        "schema_version": "2.0",
        "as_of_date": "2026-08-19",
        "generated_at": "2026-08-19T10:00:00Z",
        "holdings": [
            # ОФЗ-ПК: plan_subtype=Флоат → is_floater true, но bond_type
            # выводится по имени «офз» раньше floater-ветки → остаётся ofz.
            {
                "ticker": "RU000A1052T1", "name": "ОФЗ 87042",
                "asset_type": "bond", "qty": 100.0, "value_rub": 300000.0,
                "account": "main", "is_blocked": False,
                "nominal_currency": "RUB",
                "plan_bucket": "ОФЗ", "plan_subtype": "Флоат",
                "plan_bucket_key": "ОФЗ/Флоат", "credit_rating_file": None,
            },
            # Корп-флоатер без plan_subtype=Флоат — ловится только эвристикой
            # имени («плав.»), она же существующая floater-ветка derive_bond_type.
            {
                "ticker": "RU000A100XX1", "name": "КорпБО1 плав. купон",
                "asset_type": "bond", "qty": 10.0, "value_rub": 150000.0,
                "account": "main", "is_blocked": False,
                "nominal_currency": "RUB",
                "plan_bucket": "КОРП", "plan_subtype": "B+",
                "plan_bucket_key": "КОРП/B+", "credit_rating_file": "BBB",
            },
            # Обычная корп-бумага: ни plan_subtype=Флоат, ни «плав»/floater в имени.
            {
                "ticker": "RU000A200YY2", "name": "ОбычнБО1",
                "asset_type": "bond", "qty": 20.0, "value_rub": 600000.0,
                "account": "main", "is_blocked": False,
                "nominal_currency": "RUB",
                "plan_bucket": "КОРП", "plan_subtype": "AA+",
                "plan_bucket_key": "КОРП/AA+", "credit_rating_file": "AAA",
            },
        ],
        "returns": {"by_type": {"bond": {"xirr": 0.1, "pnl_rub": 1000.0, "roi": 0.05}}},
        "balance_summary": {
            "total_current_rub_excl_iis": 2100000.0,
            "by_account": {
                "main": {"total_rub": 2100000.0, "stocks_rub": 0.0,
                         "bonds_rub": 1050000.0, "cash_rub": 1050000.0},
            },
            "goals_overall": [{"Тип": "Облигация", "Доля": 0.5}],
        },
    }


def test_plan_fields_passthrough():
    """RPA-13: plan_bucket/plan_subtype/credit_rating_file прокинуты из снапшота
    в per_bond без переклассификации моделью."""
    print("\n[test_plan_fields_passthrough]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_fake_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        ok = True
        m = re.search(r"^  RU000A106E90:\n((?:    .+\n)+)", text, re.MULTILINE)
        if not check("ОФЗ 78729 block found", bool(m)):
            return False
        block = m.group(1)
        ok &= check('ОФЗ: plan_bucket: "ОФЗ"', 'plan_bucket: "ОФЗ"' in block)
        ok &= check('ОФЗ: plan_subtype: "<10"', 'plan_subtype: "<10"' in block)
        ok &= check("ОФЗ: credit_rating_file: null (справки в файле нет)",
                    "credit_rating_file: null" in block)

        m_usd = re.search(r"^  RU000A105KU0:\n((?:    .+\n)+)", text, re.MULTILINE)
        if not check("USD bond block found", bool(m_usd)):
            return False
        block_usd = m_usd.group(1)
        ok &= check('USD: plan_bucket: "USD"', 'plan_bucket: "USD"' in block_usd)
        ok &= check("USD: plan_subtype: null (валютная корзина без подтипа)",
                    "plan_subtype: null" in block_usd)
        return ok


def test_is_floater_ofz_pk():
    """RPA-14 (обязательный кейс плана): ОФЗ-ПК — is_floater true, а bond_type
    по-прежнему ofz (суверенность/credit_quality НЕ переопределяются)."""
    print("\n[test_is_floater_ofz_pk]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_floater_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        m = re.search(r"^  RU000A1052T1:\n((?:    .+\n)+)", text, re.MULTILINE)
        if not check("ОФЗ 87042 block found", bool(m)):
            return False
        block = m.group(1)
        ok = True
        ok &= check("bond_type: ofz (НЕ floater — RPA-14)", "bond_type: ofz" in block)
        ok &= check("is_floater: true (по plan_subtype)", "is_floater: true" in block)
        ok &= check("credit_quality остаётся HIGH (суверен)", "credit_quality: HIGH" in block)
        ok &= check("issuer остаётся Минфин России", "Минфин России" in block)
        return ok


def test_is_floater_by_name_fallback():
    """RPA-14: корп-бумага без plan_subtype=Флоат, но с «плав.» в имени —
    is_floater true через существующую (derive_bond_type) эвристику имени."""
    print("\n[test_is_floater_by_name_fallback]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_floater_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        m = re.search(r"^  RU000A100XX1:\n((?:    .+\n)+)", text, re.MULTILINE)
        if not check("КорпБО1 block found", bool(m)):
            return False
        block = m.group(1)
        return check("is_floater: true (по имени, plan_subtype=B+ не Флоат)",
                     "is_floater: true" in block)


def test_is_floater_false_default():
    """RPA-14: обычная корп-бумага без плав-сигналов — is_floater false;
    credit_rating_file прокинут, credit_rating остаётся TODO_LLM (Q5)."""
    print("\n[test_is_floater_false_default]")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.json"
        out = Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_floater_snapshot()))
        run_script(snap, out)
        text = out.read_text()
        m = re.search(r"^  RU000A200YY2:\n((?:    .+\n)+)", text, re.MULTILINE)
        if not check("ОбычнБО1 block found", bool(m)):
            return False
        block = m.group(1)
        ok = check("is_floater: false", "is_floater: false" in block)
        ok &= check('credit_rating_file: "AAA" (справка прокинута)',
                    'credit_rating_file: "AAA"' in block)
        ok &= check("credit_rating остаётся TODO_LLM (Q5 — модель сверяет по агентствам)",
                    "credit_rating: TODO_LLM" in block)
        return ok


def test_by_plan_bucket_pct_summary():
    """RPA-13: summary.by_plan_bucket_pct — веса по plan_bucket_key рядом с
    by_type_pct; сверка с ручным счётом по value_rub (все 4 бумаги = всей корзине)."""
    print("\n[test_by_plan_bucket_pct_summary]")
    with tempfile.TemporaryDirectory() as td:
        snap, out = Path(td) / "snap.json", Path(td) / "stub.yaml"
        snap.write_text(json.dumps(make_full_snapshot()))
        run_script(snap, out)
        block = _summary_block(out.read_text())
        ok = True
        ok &= check("by_plan_bucket_pct присутствует рядом с by_type_pct",
                    "by_plan_bucket_pct:" in block and "by_type_pct:" in block)
        # scope_total = 480000(ОФЗ/>10)+1590000(ОФЗ/<10)+1795770(USD)+1440000(EUR) = 5305770
        ok &= check('"ОФЗ/>10": 9.0468', '"ОФЗ/>10": 9.0468' in block, block)
        ok &= check('"ОФЗ/<10": 29.9674', '"ОФЗ/<10": 29.9674' in block, block)
        ok &= check('"USD": 33.8456', '"USD": 33.8456' in block, block)
        ok &= check('"EUR": 27.1403', '"EUR": 27.1403' in block, block)
        return ok


def _write_prior_review(root: Path, date: str, per_bond: dict) -> Path:
    import yaml
    d = root / "weekly-reviews"
    d.mkdir(exist_ok=True)
    f = d / f"weekly-review-bond-{date}.yaml"
    f.write_text(yaml.safe_dump({"review_date": date, "per_bond": per_bond}, allow_unicode=True), encoding="utf-8")
    return f


def test_rating_carried_from_prior_review():
    """Рейтинг прошлого обзора переносится в заготовку блоком rating (корп) и не появляется у ОФЗ; без прошлого
    обзора у корпоративной — rating: null; ISIN, которого нет в заготовке, игнорируется."""
    print("\n[test_rating_carried_from_prior_review]")
    import yaml
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "snapshots").mkdir()
        snap = root / "snapshots" / "portfolio-2026-08-19.json"
        snap.write_text(json.dumps(make_floater_snapshot()))
        rating = {"value": "AA-", "agency": "АКРА", "date": "2026-07-01", "source": "https://acra-ratings.ru/x"}
        _write_prior_review(root, "2026-08-12", {"RU000A200YY2": {"rating": rating},
                                                 "RU000A1052T1": {"rating": {"value": "AAA"}},
                                                 "ZZZ": {"rating": rating}})
        out = root / "stub.yaml"
        subprocess.run([sys.executable, str(SCRIPT), "--snapshot", str(snap), "--output", str(out),
                        "--today", "2026-08-19", "--no-moex-fetch"], check=True, capture_output=True, text=True)
        text = out.read_text()
        doc = yaml.safe_load(text.replace("TODO_LLM", "TODO"))
        ok = True
        ok &= check("корп: rating перенесён целиком",
                    doc["per_bond"]["RU000A200YY2"].get("rating") == rating)
        ok &= check("ОФЗ: блока rating нет", "rating" not in doc["per_bond"]["RU000A1052T1"])
        ok &= check("корп без прошлого рейтинга: rating null",
                    "rating" in doc["per_bond"]["RU000A100XX1"] and doc["per_bond"]["RU000A100XX1"]["rating"] is None)
        # явный --prior-review и более поздний файл (не раньше даты обзора) не берутся автоматически
        _write_prior_review(root, "2026-08-19", {"RU000A200YY2": {"rating": {"value": "A", "agency": "НКР",
                                                                              "date": "2026-08-18", "source": "x"}}})
        subprocess.run([sys.executable, str(SCRIPT), "--snapshot", str(snap), "--output", str(out),
                        "--today", "2026-08-19", "--no-moex-fetch"], check=True, capture_output=True, text=True)
        doc2 = yaml.safe_load(out.read_text().replace("TODO_LLM", "TODO"))
        ok &= check("обзор того же дня не считается «прошлым»",
                    doc2["per_bond"]["RU000A200YY2"]["rating"]["value"] == "AA-")
        explicit = root / "weekly-reviews" / "weekly-review-bond-2026-08-19.yaml"
        subprocess.run([sys.executable, str(SCRIPT), "--snapshot", str(snap), "--output", str(out),
                        "--today", "2026-08-19", "--no-moex-fetch", "--prior-review", str(explicit)],
                       check=True, capture_output=True, text=True)
        doc3 = yaml.safe_load(out.read_text().replace("TODO_LLM", "TODO"))
        ok &= check("--prior-review берёт указанный файл", doc3["per_bond"]["RU000A200YY2"]["rating"]["value"] == "A")
        return ok


TESTS = [
    test_smoke_run,
    test_top_level_canonical_types,
    test_horizon_v2_fields,
    test_no_v1_horizon_fields,
    test_anchor_dates_mode,
    test_per_bond_population,
    test_split_merge_iis,
    test_bond_type_heuristic,
    test_bond_type_sur_is_rub,
    test_summary_aggregates,
    test_anti_drift_naming,
    test_todo_llm_placeholders,
    test_snapshot_fallback_fills_bond_fields,
    test_sur_normalized_to_rub,
    test_summary_aggregates_computed,
    test_main_only_scope_differs_from_all,
    test_ofz_fields_prefilled,
    test_maturity_ladder_has_no_unknown_bucket,
    test_yaml_parses_via_pyyaml_if_available,
    test_missing_snapshot_rejected,
    test_horizon_mode_rolling_present,
    test_horizon_mode_anchored_present,
    test_plan_fields_passthrough,
    test_is_floater_ofz_pk,
    test_is_floater_by_name_fallback,
    test_is_floater_false_default,
    test_by_plan_bucket_pct_summary,
    test_rating_carried_from_prior_review,
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
