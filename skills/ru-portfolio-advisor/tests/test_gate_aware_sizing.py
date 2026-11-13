#!/usr/bin/env python3
"""
test_gate_aware_sizing.py — тесты для scripts/gate_aware_sizing.py.

Покрывает §T1 плана `docs/investment/portfolio/gate-aware-sizing-rollout-plan.md`:
классификацию Open/Blocked/Dormant/Selling, делегирование арифметики
constraint_engine.compute_fixed_point_target (не дублируется здесь), деградацию
degenerate/near_degenerate/S>=1, контракт report_block (§1.2/§1.3/§1.4 плана —
термины «база докупки» и «остаток, закрытый для покупок гейтами» дословно),
--lint-draft (ровно две проверки), лоты (floor-округление, деградация без данных),
read-only гарантию скрипта и (TestDocsGuard) размещение правок T2–T6 в референсах
скилла — этот класс ожидаемо красный до конца волны 1 (T1 сдаётся раньше T2–T6).

Запуск:
    ~/.pyenv/versions/3.12.9/bin/python3 skills/ru-portfolio-advisor/tests/test_gate_aware_sizing.py
"""
from __future__ import annotations

import copy
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SKILL_DIR = os.path.join(REPO, "skills", "ru-portfolio-advisor")
SCRIPT_PATH = os.path.join(SKILL_DIR, "scripts", "gate_aware_sizing.py")

sys.path.insert(0, os.path.join(SKILL_DIR, "scripts"))
sys.path.insert(1, os.path.join(REPO, "_shared-references"))  # канон moex_quotes
import gate_aware_sizing as gas  # noqa: E402
import build_weekly_stock_stub as bwss  # noqa: E402
import moex_quotes  # noqa: E402
import last_word as lw  # noqa: E402  — модуль (б): add_months для справочника бумаг фикстур

PY = sys.executable

SYNOLOGY_SNAPSHOT = os.path.expanduser(
    "~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/Portfolio/snapshots/portfolio-2026-08-19.json"
)
SYNOLOGY_CONDITIONS = os.path.expanduser(
    "~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/Portfolio/conditions.yaml"
)
# Реальные решения, справочник бумаг и условия — рабочая папка после переключения 31.10 (decision.md §4.2), только чтение.
_CM_PORTFOLIO = os.path.expanduser("~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/Portfolio")
SYNOLOGY_DECISIONS = os.path.join(_CM_PORTFOLIO, "decisions")
SYNOLOGY_ATTRS = os.path.join(_CM_PORTFOLIO, "security-attrs.json")
SYNOLOGY_CONDITIONS_STATE = os.path.join(_CM_PORTFOLIO, "conditions-state.json")


def live_gate_args():
    """CLI-аргументы гейта и условий из рабочей папки (decisions/, security-attrs.json, conditions@2 + состояние)."""
    return ["--decisions", SYNOLOGY_DECISIONS, "--security-attrs", SYNOLOGY_ATTRS,
            "--conditions", SYNOLOGY_CONDITIONS, "--conditions-state", SYNOLOGY_CONDITIONS_STATE]


# ─────────────────────────── синтетические фикстуры ───────────────────────────

def mk_stock(ticker, value_rub, *, is_blocked=False, price_source="moex_iss",
             listing_age_quarters=40):
    return {
        "ticker": ticker, "asset_type": "stock", "value_rub": value_rub,
        "is_blocked": is_blocked, "current_price_source": price_source,
        "listing_age_quarters": listing_age_quarters,
    }


def mk_ie_row(*, planned=None, ie=None, real=None, user_plan=None):
    return {
        "planned_share_pct": planned, "ie_new_pct": ie,
        "real_share_pct": real, "user_plan": user_plan,
    }


def mk_snapshot(holdings, per_ticker, class_plan_rub, class_fact_rub, nav, as_of="2026-08-19"):
    return {
        "as_of_date": as_of,
        "balance_summary": {
            "total_current_rub_excl_iis": nav,
            "goals_matrix": [
                {"Валюта": "RUB", "Бумага": "Акция", "Планы": class_plan_rub, "Сейчас": class_fact_rub},
                {"Валюта": "RUB", "Бумага": "Облигация", "Планы": 3000000.0, "Сейчас": 2700000.0},
            ],
        },
        "holdings": holdings,
        "ie_actual": {"per_ticker": per_ticker},
    }


def mk_decision(ticker, verdict, recorded, review_by=None):
    return {"schema_version": "decision@1", "id": f"{recorded}T1000-{ticker}", "key": ticker, "verdict": verdict,
            "target_pct": None, "review_by": review_by, "note": "фикстура", "confidence": None,
            "conditions_created": [], "conditions_resolved": [],
            "source": {"kind": "backfill", "doc": None, "mode_codes": [], "stress_id": None},
            "author": "owner", "recorded_at": f"{recorded}T10:00:00+03:00"}


# статус гейта → решение, которое модуль (б) проецирует в этот статус на любую дату 2026 года
_STATUS_DECISION = {"reviewed_keep": "HOLD", "reviewed_buy_more": "ADD", "reviewed_reduce": "TRIM",
                    "reviewed_under_review": "WATCH"}


def ipo_attrs(holdings, as_of):
    """Справочник бумаг: акция с listing_age_quarters < 8 в фикстуре → ticker_class ipo, listed_at = as_of − 3q мес.
    (IPO-пауза модуля (б) даёт тот же код ipo_gate:<q>q, что раньше давал возраст листинга снапшота)."""
    out = {}
    for h in holdings or []:
        q = h.get("listing_age_quarters")
        if isinstance(q, int) and q < 8:
            out[h["ticker"]] = {"ticker_class": "ipo", "listed_at": lw.add_months(as_of, -3 * q), "note": None,
                                "updated_at": "2026-10-31T00:00:00+03:00", "updated_by": "owner"}
    return out


def mk_gate_inputs(statuses, valid_until=None, *, ipo_from=None, as_of="2026-08-19"):
    """statuses: {ticker: status} → входы гейта модуля (б) (решения, строки обзоров, справочник бумаг).
    reviewed_* — решение давно (пауза докупки прошла) со сроком valid_until (нет — далёкий срок); review_aging —
    решение с истёкшим сроком; review_needed — строка обзора с флагом без решения. ipo_from — холдинги фикстуры,
    из listing_age_quarters которых строится справочник бумаг (ipo_attrs)."""
    decisions, reviews = [], {}
    for t, status in statuses.items():
        if status in _STATUS_DECISION:
            decisions.append(mk_decision(t, _STATUS_DECISION[status], "2026-01-05", valid_until or "2030-01-01"))
        elif status == "review_aging":
            decisions.append(mk_decision(t, "HOLD", "2025-01-05", "2025-03-01"))
        elif status == "review_needed":
            reviews[t] = [{"review_date": "2026-01-06", "recorded_at": "2026-01-06T00:00:00+03:00",
                           "advisor_verdict": "HOLD", "gate_review_required": True}]
        else:
            raise ValueError(f"mk_gate_inputs: статус {status!r} решением не задаётся")
    return {"decisions": decisions, "reviews": reviews,
            "security_attrs": {"schema_version": "security-attrs@1", "by_key": ipo_attrs(ipo_from, as_of)}}


def mk_conditions(entries):
    """entries: [(ticker, verdict, state), ...] — условия conditions@2 (state fired — событием состояния)."""
    defs, events = [], []
    for ticker, verdict, state in entries:
        cid = f"c-{ticker.lower()}-{verdict.lower()}"
        defs.append({"id": cid, "version": 1, "key": ticker, "kind": "trade",
                     "trigger": {"type": "date", "value": "2026-10-31"},
                     "on_trigger": {"action": "set_verdict", "verdict": verdict, "text": "фикстура"},
                     "created_at": "2026-01-01T10:00:00+03:00", "created_by": "owner"})
        if state == "fired":
            events.append({"condition_id": cid, "event": "fired", "at": "2026-01-02T10:00:00+03:00", "by": "notifier"})
    return {"defs": defs, "state": {"schema_version": "conditions-state@1", "events": events}}


def write_gate_cli_inputs(tmpdir, gate_inputs, conditions):
    """Входы гейта и условий файлами для CLI: папка решений, справочник бумаг, conditions@2 + состояние."""
    import yaml
    ddir = os.path.join(tmpdir, "decisions")
    os.makedirs(ddir, exist_ok=True)
    for d in (gate_inputs or {}).get("decisions") or []:
        with open(os.path.join(ddir, d["id"] + ".json"), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    attrs = os.path.join(tmpdir, "security-attrs.json")
    with open(attrs, "w", encoding="utf-8") as f:
        json.dump((gate_inputs or {}).get("security_attrs") or {"schema_version": "security-attrs@1", "by_key": {}}, f)
    args = ["--decisions", ddir, "--security-attrs", attrs]
    if conditions:
        cpath, spath = os.path.join(tmpdir, "conditions.yaml"), os.path.join(tmpdir, "conditions-state.json")
        with open(cpath, "w", encoding="utf-8") as f:
            yaml.safe_dump({"schema_version": "conditions@2", "conditions": conditions["defs"]}, f, allow_unicode=True)
        with open(spath, "w", encoding="utf-8") as f:
            json.dump(conditions["state"], f)
        args += ["--conditions", cpath, "--conditions-state", spath]
    return args


# ───────────────── синтетическая фикстура §5 spec-gate-aware-sizing-trim-fix.md ─────────────────
#
# 21 акция книги, детерминированная копия реальных значений portfolio-2026-08-21.json
# (NAV без ИИС-3 = 42 839 550 ₽, факт. книга = 14 232 340,5 ₽, план класса = 17 135 820 ₽,
# решения RENI/MOEX/OZON с истёкшим сроком (review_aging), condition OZON pending BUY) — воспроизводит
# эталонные числа §5 без обращения к Synology. Проверено ручным прогоном CLI на живом
# снапшоте перед написанием тестов (см. отчёт по задаче A).
_TRIM_FIX_ROWS = [
    # ticker, value_rub, listing_age_quarters, planned_pct, real_pct, ie_new_pct, user_plan
    ("RENI", 1533528.0, 19, 12.0, 10.775, 12.0, "BUY"),
    ("SBER", 1535404.5, 58, 10.0, 10.7881, 6.0, "KEEP"),
    ("YDEX", 1440414.0, 8, 10.0, 10.1207, 10.0, "KEEP"),
    ("SBERP", 1225626.12, 58, 8.0, 8.6116, None, "BALANCE"),
    ("MOEX", 1121976.0, 54, 8.0, 7.8833, None, "KEEP"),
    ("T", 908256.48, 117, 6.0, 6.3816, 6.0, "KEEP"),
    ("MDMG", 846866.7, 23, 5.0, 5.9503, 5.0, "KEEP"),
    ("OZON", 776214.0, 22, 5.5, 5.4539, None, "KEEP"),
    ("X5", 766545.0, 117, 6.0, 5.3859, 6.0, "BALANCE"),
    ("PLZL", 646136.4, 81, 4.5, 4.5399, 10.0, "KEEP"),
    ("MBNK", 502060.5, 9, 4.0, 3.5276, 4.0, "KEEP"),
    ("CNRU", 493200.0, 6, 3.0, 3.4653, 5.0, "BALANCE"),
    ("PRMD", 451500.0, 8, 3.0, 3.1724, None, "KEEP"),
    ("GMKN", 380702.4, 78, 2.0, 2.6749, None, "KEEP"),
    ("MRKP", 309480.0, 73, 2.0, 2.1745, 7.0, "BALANCE"),
    ("DATA", 300960.0, 7, 2.0, 2.1146, 3.0, "KEEP"),
    ("LSNGP", 233358.0, 92, 3.0, 1.6396, 4.0, "BUY"),
    ("NVTK", 234167.4, 58, 2.0, 1.6453, None, "KEEP"),
    ("BTBR", 215298.0, 1, 1.5, 1.5127, None, "KEEP"),
    ("GLRX", 164284.5, 3, 1.0, 1.1543, 2.0, "KEEP"),
    ("LENT", 146362.5, 18, 1.0, 1.0284, 4.0, "KEEP"),
]


def trim_fix_holdings_and_ie():
    holdings = [mk_stock(t, v, listing_age_quarters=q) for (t, v, q, *_rest) in _TRIM_FIX_ROWS]
    per_ticker = {
        t: mk_ie_row(planned=p, real=r, ie=ie, user_plan=up)
        for (t, v, q, p, r, ie, up) in _TRIM_FIX_ROWS
    }
    return holdings, per_ticker


def trim_fix_snapshot(cash_rub=None):
    holdings, per_ticker = trim_fix_holdings_and_ie()
    snap = mk_snapshot(
        holdings, per_ticker,
        class_plan_rub=17_135_820.0, class_fact_rub=14_232_340.5, nav=42_839_550.0,
        as_of="2026-08-21",
    )
    if cash_rub is not None:
        snap["cash"] = {"total_rub": cash_rub}
    return snap


def trim_fix_gate_inputs():
    return mk_gate_inputs({"RENI": "review_aging", "MOEX": "review_aging", "OZON": "review_aging"},
                           ipo_from=trim_fix_holdings_and_ie()[0], as_of="2026-08-21")


def trim_fix_conditions():
    return mk_conditions([("OZON", "BUY", "pending")])


# ─────────────────────────── 1. Калибровка спеки §7 ───────────────────────────

class TestSpecCaseSevenCalibration(unittest.TestCase):
    """gate-aware-sizing-spec.md §7: F=11 357 871, Open RENI 11%/MBNK 4%/X5 5.5% (S=0.205).

    С 28.10 ручной режим применяет правило «замороженная перевешенная бумага — на плане»
    (frozen_on_plan=True по умолчанию). Оригинальная фикстура (BLK с плановой долей 20% при
    11 357 871 ₽ против 20% × книга 14 065 335 = 2 813 067 ₽) теперь перевешена и уходит в S: база
    вырождается в план класса, неподвижной точки нет — это по правилу верно (см.
    TestFrozenOnPlanManualDefault.test_spec7_original_fixture_under_new_rule). Чтобы тест
    продолжал проверять саму неподвижную точку, у BLK убрана плановая доля (planned=None, вес
    цели берётся из ie_new_pct=20): бумага без плановой доли «на план» не переводится, её рубли
    остаются в F — числа эталона §7 (14 286 630 ₽, 1 571 529 / 571 464 / 785 766, 221 295 ₽) прежние."""

    def test_base_targets_and_total_buy(self):
        holdings = [
            mk_stock("BLK", 11_357_871),
            mk_stock("RENI", 1_524_012), mk_stock("MBNK", 441_702), mk_stock("X5", 741_750),
        ]
        per_ticker = {
            "BLK": mk_ie_row(planned=None, ie=20.0, real=5.0),   # без плановой доли — остаётся в F
            "RENI": mk_ie_row(planned=11.0, real=8.0),
            "MBNK": mk_ie_row(planned=4.0, real=2.5),
            "X5": mk_ie_row(planned=5.5, real=4.0),
        }
        snap = mk_snapshot(holdings, per_ticker, class_plan_rub=17_314_827, class_fact_rub=14_065_335, nav=45_000_000)
        gate_inputs = mk_gate_inputs({"BLK": "review_needed"}, valid_until="2026-12-01")

        result = gas.run_sizing(
            snapshot=snap, gate_inputs=gate_inputs, conditions=None,
            open_arg="RENI,MBNK,X5", selling_arg=None, blocked_arg=None,
            extra_cash_from_sales=0.0, quotes=None, yaml_warnings=[],
        )
        self.assertEqual(result["base_source"], "fixed_point")
        self.assertAlmostEqual(result["base_rub"], 11_357_871 / 0.795, delta=5)
        self.assertAlmostEqual(result["s_open"], 0.205, places=6)

        targets = {o["ticker"]: o["target_rub"] for o in result["classification"]["open"]}
        self.assertAlmostEqual(targets["RENI"], 1_571_529, delta=5)
        self.assertAlmostEqual(targets["MBNK"], 571_464, delta=5)
        self.assertAlmostEqual(targets["X5"], 785_766, delta=5)

        total_buy = sum(o["buy_rub"] for o in result["classification"]["open"])
        self.assertAlmostEqual(total_buy, 221_295, delta=5)


# ─────────────────────────── 2/3/4. degenerate / near_degenerate / S>=1 ───────────────────────────

class TestDegenerateAndGuards(unittest.TestCase):

    def test_degenerate_no_blocked_base_equals_t_full(self):
        holdings = [mk_stock("DORM", 2_700_000), mk_stock("OPEN1", 300_000)]
        per_ticker = {
            "DORM": mk_ie_row(planned=15.0, real=15.0),
            "OPEN1": mk_ie_row(planned=10.0, real=7.0),
        }
        snap = mk_snapshot(holdings, per_ticker, class_plan_rub=3_600_000, class_fact_rub=3_000_000, nav=15_000_000)
        result = gas.run_sizing(
            snapshot=snap, gate_inputs=None, conditions=None,
            open_arg="OPEN1", selling_arg=None, blocked_arg=None,
            extra_cash_from_sales=0.0, quotes=None, yaml_warnings=[],
        )
        # непрерывная база (§10.6, 11.11): блокировок нет — та же неподвижная точка, «спящий» DORM в F своими рублями;
        # база = 2 700 000 / (1 − 0,10) = 3 000 000 (книга после исполнения), не план класса 3 600 000
        self.assertEqual(result["base_source"], "fixed_point")
        self.assertAlmostEqual(result["base_rub"], 3_000_000)
        self.assertAlmostEqual(result["blocked_gap_rub"], 600_000)
        self.assertAlmostEqual(result["gap_gated_rub"], 0.0)

    def test_nothing_frozen_base_equals_t_full(self):
        # в F ничего нет (все бумаги двигаются к плану) — база = план класса (t_full_no_gates)
        holdings = [mk_stock("OPEN1", 300_000), mk_stock("OPEN2", 900_000)]
        per_ticker = {"OPEN1": mk_ie_row(planned=10.0, real=25.0), "OPEN2": mk_ie_row(planned=60.0, real=75.0)}
        snap = mk_snapshot(holdings, per_ticker, class_plan_rub=3_600_000, class_fact_rub=1_200_000, nav=15_000_000)
        result = gas.run_sizing(
            snapshot=snap, gate_inputs=None, conditions=None,
            open_arg="OPEN1,OPEN2", selling_arg=None, blocked_arg=None,
            extra_cash_from_sales=0.0, quotes=None, yaml_warnings=[],
        )
        self.assertEqual(result["base_source"], "t_full_no_gates")
        self.assertAlmostEqual(result["base_rub"], 3_600_000)
        self.assertAlmostEqual(result["blocked_gap_rub"], 0.0)

    def test_near_degenerate_s_close_to_one_no_number_invented(self):
        holdings = [mk_stock("BLK", 300_000), mk_stock("OPEN1", 150_000)]
        per_ticker = {
            "BLK": mk_ie_row(planned=1.0, real=0.1),
            "OPEN1": mk_ie_row(planned=99.5, real=10.0),
        }
        snap = mk_snapshot(holdings, per_ticker, class_plan_rub=6_000_000, class_fact_rub=450_000, nav=15_000_000)
        gate_inputs = mk_gate_inputs({"BLK": "review_needed"})
        result = gas.run_sizing(
            snapshot=snap, gate_inputs=gate_inputs, conditions=None,
            open_arg="OPEN1", selling_arg=None, blocked_arg=None,
            extra_cash_from_sales=0.0, quotes=None, yaml_warnings=[],
        )
        self.assertEqual(result["base_source"], "manual_check_required")
        self.assertIsNone(result["base_rub"])
        self.assertIn("near_degenerate_manual_check", result["warnings"])
        for o in result["classification"]["open"]:
            self.assertIsNone(o["target_rub"])
            self.assertIsNone(o["buy_rub"])

    def test_s_gte_one_clean_error_no_traceback(self):
        holdings = [mk_stock("BLK", 300_000), mk_stock("A", 180_000), mk_stock("B", 150_000)]
        per_ticker = {
            "BLK": mk_ie_row(planned=5.0, real=1.0),
            "A": mk_ie_row(planned=60.0, real=10.0),
            "B": mk_ie_row(planned=50.0, real=10.0),
        }
        snap = mk_snapshot(holdings, per_ticker, class_plan_rub=3_000_000, class_fact_rub=630_000, nav=15_000_000)
        gate_inputs = mk_gate_inputs({"BLK": "review_needed"})
        with self.assertRaises(gas.GateAwareSizingError):
            gas.run_sizing(
                snapshot=snap, gate_inputs=gate_inputs, conditions=None,
                open_arg="A=60,B=50", selling_arg=None, blocked_arg=None,
                extra_cash_from_sales=0.0, quotes=None, yaml_warnings=[],
            )

    def test_cli_s_gte_one_exit_2_no_traceback(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            holdings = [mk_stock("BLK", 300_000), mk_stock("A", 180_000), mk_stock("B", 150_000)]
            per_ticker = {
                "BLK": mk_ie_row(planned=5.0, real=1.0),
                "A": mk_ie_row(planned=60.0, real=10.0),
                "B": mk_ie_row(planned=50.0, real=10.0),
            }
            json.dump(mk_snapshot(holdings, per_ticker, 3_000_000, 630_000, 15_000_000), f)
            path = f.name
        try:
            # --concentration-limits на заведомо отсутствующий файл: этот тест — про S>=1,
            # а не про лимиты концентрации, но CLI по умолчанию подхватывает шипованный
            # references/concentration-limits.yaml (§9/§11 «Волна 3»), и на этой крошечной
            # синтетической книге (L2_cur=630 000) A/B (60%/50% книги) нарушают дефолтный
            # лимит 15% по эмитенту — оба уходят в Blocked, S падает до 0, и S>=1 просто не
            # наступает. Отключаем проверку явно, чтобы тест остался про то, что заявлен.
            proc = subprocess.run(
                [PY, SCRIPT_PATH, "--snapshot", path, "--open", "A=60,B=50",
                 "--concentration-limits", "/tmp/does-not-exist-concentration-for-s-gte-one-test.yaml"],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertNotIn("Traceback", proc.stderr)
        finally:
            os.unlink(path)


# ─────────────────────────── 5. Веса ───────────────────────────

class TestWeightResolution(unittest.TestCase):

    def _snap(self, per_ticker):
        holdings = [mk_stock("T1", 300_000), mk_stock("DORM", 2_700_000)]
        per_ticker = dict(per_ticker)
        per_ticker.setdefault("DORM", mk_ie_row(planned=10.0, real=10.0))
        return mk_snapshot(holdings, per_ticker, class_plan_rub=4_500_000, class_fact_rub=3_000_000, nav=15_000_000)

    def test_planned_primary(self):
        snap = self._snap({"T1": mk_ie_row(planned=8.0, ie=20.0, real=5.0)})
        result = gas.run_sizing(snap, None, None, "T1", None, None, 0.0, None, [])
        o = result["classification"]["open"][0]
        self.assertEqual(o["weight_source"], "planned")
        self.assertEqual(o["weight_pct"], 8.0)

    def test_planned_null_falls_back_to_ie_with_warning(self):
        snap = self._snap({"T1": mk_ie_row(planned=None, ie=20.0, real=5.0)})
        result = gas.run_sizing(snap, None, None, "T1", None, None, 0.0, None, [])
        o = result["classification"]["open"][0]
        self.assertEqual(o["weight_source"], "ie")
        self.assertEqual(o["weight_pct"], 20.0)
        self.assertIn("weight_fallback_ie:T1", result["warnings"])

    def test_both_null_is_error(self):
        snap = self._snap({"T1": mk_ie_row(planned=None, ie=None, real=5.0)})
        with self.assertRaises(gas.GateAwareSizingError):
            gas.run_sizing(snap, None, None, "T1", None, None, 0.0, None, [])

    def test_open_explicit_weight_overrides(self):
        snap = self._snap({"T1": mk_ie_row(planned=8.0, ie=20.0, real=5.0)})
        result = gas.run_sizing(snap, None, None, "T1=11", None, None, 0.0, None, [])
        o = result["classification"]["open"][0]
        self.assertEqual(o["weight_source"], "override")
        self.assertEqual(o["weight_pct"], 11.0)


# ─────────────────────────── 6. Selling / extra_cash_from_sales ───────────────────────────

class TestSellingAndExtraCash(unittest.TestCase):

    def test_selling_excluded_from_f_and_s(self):
        holdings = [mk_stock("DORM", 1_500_000), mk_stock("SOLD", 6_000_000), mk_stock("OPEN1", 300_000)]
        per_ticker = {
            "DORM": mk_ie_row(planned=10.0, real=10.0),
            "SOLD": mk_ie_row(planned=30.0, real=30.0),
            "OPEN1": mk_ie_row(planned=10.0, real=5.0),
        }
        with_selling = mk_snapshot(holdings, per_ticker, class_plan_rub=3_000_000, class_fact_rub=1_800_000, nav=15_000_000)
        without_selling_holdings = [h for h in holdings if h["ticker"] != "SOLD"]
        without_selling = mk_snapshot(without_selling_holdings, per_ticker, class_plan_rub=3_000_000, class_fact_rub=1_800_000, nav=15_000_000)

        r_with = gas.run_sizing(with_selling, None, None, "OPEN1", "SOLD", None, 0.0, None, [])
        r_without = gas.run_sizing(without_selling, None, None, "OPEN1", None, None, 0.0, None, [])

        self.assertAlmostEqual(r_with["base_rub"], r_without["base_rub"], delta=5)
        self.assertEqual(len(r_with["classification"]["selling"]), 1)
        self.assertEqual(r_with["classification"]["selling"][0]["ticker"], "SOLD")
        blocked_dormant_tickers = {x["ticker"] for x in r_with["classification"]["blocked"] + r_with["classification"]["dormant"]}
        self.assertNotIn("SOLD", blocked_dormant_tickers)

    def test_extra_cash_from_sales_does_not_move_base_but_fills_cash_available(self):
        holdings = [mk_stock("DORM", 2_700_000), mk_stock("OPEN1", 300_000)]
        per_ticker = {
            "DORM": mk_ie_row(planned=15.0, real=15.0),
            "OPEN1": mk_ie_row(planned=10.0, real=5.0),
        }
        snap = mk_snapshot(holdings, per_ticker, class_plan_rub=3_600_000, class_fact_rub=3_000_000, nav=15_000_000)
        r0 = gas.run_sizing(snap, None, None, "OPEN1", None, None, 0.0, None, [])
        r1 = gas.run_sizing(snap, None, None, "OPEN1", None, None, 750_000.0, None, [])
        self.assertAlmostEqual(r0["base_rub"], r1["base_rub"], delta=5)
        self.assertEqual(r0["cash_available_for_open"], 0.0)
        self.assertEqual(r1["cash_available_for_open"], 750_000.0)


# ─────────────────────────── 7. Фильтры активной книги ───────────────────────────

class TestActiveBookFilters(unittest.TestCase):

    def test_cost_basis_is_blocked_and_money_market_excluded(self):
        holdings = [
            mk_stock("OPEN1", 300_000),
            mk_stock("FROZEN_US", 1_500_000, price_source="cost_basis"),
            mk_stock("BLOCKED_POS", 1_200_000, is_blocked=True),
            mk_stock("TMON", 900_000),
        ]
        per_ticker = {"OPEN1": mk_ie_row(planned=10.0, real=5.0)}
        snap = mk_snapshot(holdings, per_ticker, class_plan_rub=3_000_000, class_fact_rub=300_000, nav=15_000_000)
        result = gas.run_sizing(snap, None, None, "OPEN1", None, None, 0.0, None, [])
        all_tickers = {o["ticker"] for o in result["classification"]["open"]}
        all_tickers |= {x["ticker"] for x in result["classification"]["blocked"]}
        all_tickers |= {x["ticker"] for x in result["classification"]["dormant"]}
        all_tickers |= {x["ticker"] for x in result["classification"]["selling"]}
        self.assertNotIn("FROZEN_US", all_tickers)
        self.assertNotIn("BLOCKED_POS", all_tickers)
        self.assertNotIn("TMON", all_tickers)
        self.assertIn("OPEN1", all_tickers)

    def test_money_market_tickers_matches_build_weekly_stock_stub(self):
        self.assertEqual(gas.MONEY_MARKET_TICKERS, bwss.MONEY_MARKET_TICKERS)


# ─────────────────────────── 8. Автоклассификация ───────────────────────────

class TestAutoClassification(unittest.TestCase):

    def _base_holdings_pt(self):
        holdings = [mk_stock("DORM", 2_700_000)]
        per_ticker = {"DORM": mk_ie_row(planned=10.0, real=10.0)}
        return holdings, per_ticker

    def test_review_needed_status_blocks(self):
        holdings, per_ticker = self._base_holdings_pt()
        holdings.append(mk_stock("GATE1", 300_000))
        per_ticker["GATE1"] = mk_ie_row(planned=10.0, real=2.0)
        snap = mk_snapshot(holdings, per_ticker, 3_000_000, 3_000_000, 15_000_000)
        gate_inputs = mk_gate_inputs({"GATE1": "review_needed"}, valid_until="2026-11-12")
        result = gas.run_sizing(snap, gate_inputs, None, None, None, None, 0.0, None, [])
        blocked_tickers = {x["ticker"]: x for x in result["classification"]["blocked"]}
        self.assertIn("GATE1", blocked_tickers)
        self.assertIn("gate:review_needed", blocked_tickers["GATE1"]["reason"])
        self.assertEqual(blocked_tickers["GATE1"]["unblock_by"], "после разбора бумаги")   # флаг обзора: снимет разбор

    def test_ai_mode_off_gate_blocks_like_on(self):
        """Режим «без ИИ» (решение 11.11): срок решения и статусы гейта блокируют, как при on (снимает решение владельца); пауза докупки — тоже блок."""
        holdings, per_ticker = self._base_holdings_pt()
        for t in ("AGEX", "NEEDX"):
            holdings.append(mk_stock(t, 300_000))
            per_ticker[t] = mk_ie_row(planned=10.0, real=2.0)
        snap = mk_snapshot(holdings, per_ticker, 3_000_000, 3_000_000, 15_000_000)
        gi = mk_gate_inputs({"AGEX": "review_aging", "NEEDX": "review_needed"})
        on = gas.run_sizing(snap, gi, None, None, None, None, 0.0, None, [])
        off = gas.run_sizing(snap, gi, None, None, None, None, 0.0, None, [], ai_mode="off")
        self.assertEqual({x["ticker"] for x in on["classification"]["blocked"]}, {"AGEX", "NEEDX"})
        self.assertEqual({x["ticker"] for x in off["classification"]["blocked"]}, {"AGEX", "NEEDX"})
        self.assertEqual([(x["ticker"], x["reason"]) for x in off["classification"]["blocked"]],
                         [(x["ticker"], x["reason"]) for x in on["classification"]["blocked"]])
        gi["decisions"].append(mk_decision("AGEX", "ADD", "2026-08-10", "2030-01-01"))   # пауза докупки 21 день от покупки 10.08 — к 19.08 идёт
        gi["last_buy_at"] = {"AGEX": "2026-08-10T00:00:00+03:00"}                       # правило 7 (11.11): пауза — от покупки после решения
        off2 = gas.run_sizing(snap, gi, None, None, None, None, 0.0, None, [], ai_mode="off")
        b2 = {x["ticker"]: x for x in off2["classification"]["blocked"]}
        self.assertIn("AGEX", b2)
        self.assertIn("add_cooldown:", b2["AGEX"]["reason"])
        self.assertNotIn("gate:", b2["AGEX"]["reason"])   # свежее решение сняло статус срока; остаётся только пауза

    def test_cli_ai_mode_flag_default_on(self):
        ap = gas.build_arg_parser()
        self.assertEqual(ap.parse_args(["--snapshot", "x"]).ai_mode, "on")
        self.assertEqual(ap.parse_args(["--snapshot", "x", "--ai-mode", "off"]).ai_mode, "off")

    def test_pending_buy_condition_blocks(self):
        holdings, per_ticker = self._base_holdings_pt()
        holdings.append(mk_stock("COND1", 300_000))
        per_ticker["COND1"] = mk_ie_row(planned=10.0, real=2.0)
        snap = mk_snapshot(holdings, per_ticker, 3_000_000, 3_000_000, 15_000_000)
        conditions = mk_conditions([("COND1", "BUY", "pending")])
        result = gas.run_sizing(snap, None, conditions, None, None, None, 0.0, None, [])
        blocked_tickers = {x["ticker"]: x for x in result["classification"]["blocked"]}
        self.assertIn("COND1", blocked_tickers)
        self.assertIn("pending_buy_condition", blocked_tickers["COND1"]["reason"])

    def test_owner_watch_conditions_do_not_block_and_nonheld_ignored(self):
        """Условие-напоминание владельца (kind watch, notify_only, while_pending.verdict null): у держимой бумаги докупку
        не закрывает (нет verdict_now → не condition_hold), условие на не держимую бумагу в классификацию не попадает
        и ничего не ломает (нечего размерять: бумаги нет в снапшоте)."""
        holdings, per_ticker = self._base_holdings_pt()
        holdings.append(mk_stock("OWN1", 300_000))
        per_ticker["OWN1"] = mk_ie_row(planned=10.0, real=2.0)
        snap = mk_snapshot(holdings, per_ticker, 3_000_000, 3_000_000, 15_000_000)
        conds = mk_conditions([])
        for key in ("OWN1", "NOTHELD"):
            conds["defs"].append({"id": f"c-{key.lower()}-w", "version": 1, "key": key, "kind": "watch",
                                  "trigger": {"type": "price_below", "value": 100},
                                  "while_pending": {"verdict": None, "text": ""},
                                  "on_trigger": {"action": "notify_only", "text": "посмотреть"},
                                  "source": {"kind": "owner", "doc": None},
                                  "created_at": "2026-11-11T10:00:00+03:00", "created_by": "owner"})
        result = gas.run_sizing(snap, None, conds, None, None, None, 0.0, None, [])
        base = gas.run_sizing(snap, None, mk_conditions([]), None, None, None, 0.0, None, [])
        self.assertEqual(result["classification"]["blocked"], [])
        self.assertEqual(result["classification"], base["classification"])   # те же классы, что без условий
        self.assertEqual(result["warnings"], base["warnings"])

    def test_listing_age_under_8_quarters_blocks(self):
        holdings, per_ticker = self._base_holdings_pt()
        holdings.append(mk_stock("IPO1", 300_000, listing_age_quarters=3))
        per_ticker["IPO1"] = mk_ie_row(planned=10.0, real=2.0)
        snap = mk_snapshot(holdings, per_ticker, 3_000_000, 3_000_000, 15_000_000)
        # IPO-пауза — из справочника бумаг (модуль (б)), не из возраста листинга снапшота
        self.assertEqual(gas.run_sizing(snap, None, None, None, None, None, 0.0, None, [])["classification"]["blocked"], [])
        result = gas.run_sizing(snap, mk_gate_inputs({}, ipo_from=holdings), None, None, None, None, 0.0, None, [])
        blocked_tickers = {x["ticker"]: x for x in result["classification"]["blocked"]}
        self.assertIn("IPO1", blocked_tickers)
        self.assertIn("ipo_gate:3q", blocked_tickers["IPO1"]["reason"])

    def test_open_wins_over_auto_blocked_with_manual_unblock_warning(self):
        holdings, per_ticker = self._base_holdings_pt()
        holdings.append(mk_stock("GATE1", 300_000))
        per_ticker["GATE1"] = mk_ie_row(planned=10.0, real=2.0)
        snap = mk_snapshot(holdings, per_ticker, 3_000_000, 3_000_000, 15_000_000)
        gate_inputs = mk_gate_inputs({"GATE1": "reviewed_under_review"})
        result = gas.run_sizing(snap, gate_inputs, None, "GATE1", None, None, 0.0, None, [])
        open_tickers = {o["ticker"] for o in result["classification"]["open"]}
        blocked_tickers = {x["ticker"] for x in result["classification"]["blocked"]}
        self.assertIn("GATE1", open_tickers)
        self.assertNotIn("GATE1", blocked_tickers)
        self.assertIn("manual_unblock:GATE1", result["warnings"])

    def test_yaml_unavailable_skips_auto_classification_but_manual_blocked_works(self):
        with unittest.mock.patch.dict(sys.modules, {"yaml": None}):
            data, warn = gas.load_conditions_inputs(SYNOLOGY_CONDITIONS, None)
            self.assertIsNone(data)
            self.assertEqual(warn, ["yaml_unavailable"])

        holdings, per_ticker = self._base_holdings_pt()
        holdings.append(mk_stock("MAN1", 300_000))
        per_ticker["MAN1"] = mk_ie_row(planned=10.0, real=2.0)
        snap = mk_snapshot(holdings, per_ticker, 3_000_000, 3_000_000, 15_000_000)
        result = gas.run_sizing(snap, None, None, None, None, "MAN1", 0.0, None, ["yaml_unavailable"])
        blocked_tickers = {x["ticker"]: x for x in result["classification"]["blocked"]}
        self.assertIn("MAN1", blocked_tickers)
        self.assertIn("manual:--blocked", blocked_tickers["MAN1"]["reason"])
        self.assertIn("yaml_unavailable", result["warnings"])


# ─────────────────────────── 9. report_block контракт ───────────────────────────

class TestReportBlockContract(unittest.TestCase):

    def _result(self):
        holdings = [mk_stock("BLK", 11_357_871), mk_stock("RENI", 1_524_012), mk_stock("MBNK", 441_702), mk_stock("X5", 741_750)]
        per_ticker = {
            "BLK": mk_ie_row(planned=20.0, real=5.0),
            "RENI": mk_ie_row(planned=11.0, real=8.0),
            "MBNK": mk_ie_row(planned=4.0, real=2.5),
            "X5": mk_ie_row(planned=5.5, real=4.0),
        }
        snap = mk_snapshot(holdings, per_ticker, class_plan_rub=17_314_827, class_fact_rub=14_065_335, nav=45_000_000)
        gate_inputs = mk_gate_inputs({"BLK": "review_needed"}, valid_until="2026-12-01")
        result = gas.run_sizing(snap, gate_inputs, None, "RENI,MBNK,X5", None, None, 0.0, None, [])
        report = gas.build_report_block(
            as_of=result["as_of"], nav=result["nav_excl_iis"],
            class_plan_rub=result["class_plan_rub"], class_fact_rub=result["class_fact_rub"],
            classification=result["_classification_raw"], sizing=result["_sizing_raw"], quotes=None,
        )
        return report

    def test_contains_mandatory_terms_and_numbers(self):
        report = self._result()
        self.assertIn("База докупки", report)
        self.assertIn("Остаток, закрытый для покупок гейтами", report)
        self.assertIn("Доли к базе", report)
        self.assertIn("RENI", report)
        self.assertIn("факт", report)
        self.assertIn("цель", report)
        self.assertIn("%", report)

    def test_does_not_leak_internal_notation(self):
        report = self._result()
        for pattern in (r"T\*", r"T_full", r"F\s*/\s*\(\s*1\s*[−-]\s*S\s*\)",
                        r"1\s*/\s*\(\s*1\s*[−-]", r"неподвижн", r"compute_fixed_point_target"):
            self.assertIsNone(re.search(pattern, report), f"report_block содержит запрещённую нотацию: {pattern}")


# ─────────────────────────── 10. --lint-draft ───────────────────────────

class TestLintDraft(unittest.TestCase):
    STOCK_TICKERS = {"RENI", "X5", "MBNK"}

    def test_formula_is_a_violation(self):
        text = "T* = F/(1-S) = 2782500/(1-0.205) = 3500000"
        violations = gas.lint_draft(text, self.STOCK_TICKERS)
        self.assertTrue(violations)

    def test_purchase_without_base_line_is_a_violation_with_line_number(self):
        text = "Разбор недели.\nДокупить RENI на 47 400 ₽ по текущим ценам.\n"
        violations = gas.lint_draft(text, self.STOCK_TICKERS)
        self.assertTrue(violations)
        self.assertEqual(violations[0][0], 2)

    def test_same_text_with_base_line_is_clean(self):
        text = "**База докупки акций — 14 654 112 ₽ (34% NAV).**\nДокупить RENI на 47 400 ₽ по текущим ценам.\n"
        violations = gas.lint_draft(text, self.STOCK_TICKERS)
        self.assertEqual(violations, [])

    def test_bond_purchase_without_base_is_clean_lint_ignores_non_stocks(self):
        text = "Купить облигацию ОФЗ26243 на 300 000 ₽."
        violations = gas.lint_draft(text, self.STOCK_TICKERS)
        self.assertEqual(violations, [])

    def test_cli_exit_codes(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as sf:
            holdings = [mk_stock("RENI", 1_500_000)]
            per_ticker = {"RENI": mk_ie_row(planned=10.0, real=5.0)}
            json.dump(mk_snapshot(holdings, per_ticker, 3_000_000, 1_500_000, 15_000_000), sf)
            snap_path = sf.name
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as df:
            df.write("T* = F/(1-S)\n")
            bad_path = df.name
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as df2:
            df2.write("Ничего подозрительного здесь нет.\n")
            good_path = df2.name
        try:
            proc_bad = subprocess.run(
                [PY, SCRIPT_PATH, "--snapshot", snap_path, "--lint-draft", bad_path],
                capture_output=True, text=True,
            )
            self.assertEqual(proc_bad.returncode, 1)
            proc_good = subprocess.run(
                [PY, SCRIPT_PATH, "--snapshot", snap_path, "--lint-draft", good_path],
                capture_output=True, text=True,
            )
            self.assertEqual(proc_good.returncode, 0)
        finally:
            os.unlink(snap_path)
            os.unlink(bad_path)
            os.unlink(good_path)


# ─────────────────────────── 11. Лоты ───────────────────────────

class TestLots(unittest.TestCase):

    def test_floor_rounding_with_remainder(self):
        lots, remainder, price = gas.compute_lots(47_517.0, {"last": 655.6, "lot_size": 1})
        self.assertEqual(lots, 72)
        self.assertAlmostEqual(price, 655.6)
        self.assertAlmostEqual(remainder, 47_517.0 - 72 * 655.6, places=4)

    def test_missing_quote_degrades_silently(self):
        self.assertEqual(gas.compute_lots(47_517.0, None), (None, None, None))

    def test_missing_lot_size_degrades_silently(self):
        self.assertEqual(gas.compute_lots(47_517.0, {"last": 655.6}), (None, None, None))

    def test_missing_price_degrades_silently(self):
        self.assertEqual(gas.compute_lots(47_517.0, {"lot_size": 10}), (None, None, None))

    def test_run_sizing_emits_lots_unavailable_warning_without_quotes(self):
        holdings = [mk_stock("DORM", 2_700_000), mk_stock("OPEN1", 300_000)]
        per_ticker = {
            "DORM": mk_ie_row(planned=15.0, real=15.0),
            "OPEN1": mk_ie_row(planned=20.0, real=5.0),   # база 2 700 000 / 0,8 → цель 675 000 > 300 000
        }
        snap = mk_snapshot(holdings, per_ticker, class_plan_rub=3_600_000, class_fact_rub=3_000_000, nav=15_000_000)
        result = gas.run_sizing(snap, None, None, "OPEN1", None, None, 0.0, None, [])
        self.assertIn("lots_unavailable:OPEN1", result["warnings"])

    def test_moex_quotes_lot_size_field_present_and_additive(self):
        q = moex_quotes.Quote(secid="RENI", kind="share")
        self.assertIsNone(q.lot_size)
        self.assertNotIn("lot_size", q.to_dict())  # None отбрасывается to_dict()
        q.lot_size = 10
        d = q.to_dict()
        self.assertEqual(d["lot_size"], 10)
        self.assertEqual(d["secid"], "RENI")  # существующие поля не задеты


# ─────────────────────────── 12. Живая сверка (опционально) ───────────────────────────

# ─────────────────────────── 13. TestDocsGuard (ожидаемо красный до конца волны 1) ───────────────────────────

class TestDocsGuard(unittest.TestCase):
    """Сторож размещения правок T2–T6 в референсах скилла. Пишется вместе с T1 (§T1 п.13
    плана), но T2–T6 исполняются параллельно другими агентами — на момент сдачи T1 этот
    класс ожидаемо КРАСНЫЙ (полностью или частично). Финальный зелёный прогон — приёмка T7."""

    REFS = os.path.join(SKILL_DIR, "references")

    def _read(self, name):
        path = os.path.join(self.REFS, name)
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_skill_md_has_rule_24_and_no_old_inline_summary(self):
        text = open(os.path.join(SKILL_DIR, "SKILL.md"), encoding="utf-8").read()
        self.assertIn("gate_aware_sizing.py", text)
        self.assertTrue(
            re.search(r"баз[ыа] докупки", text, re.IGNORECASE),
            "SKILL.md не содержит правила про базу докупки",
        )
        self.assertNotIn("Краткая структура: 0 →", text)

    def test_analysis_process_step_6_1_uses_cli_not_manual_snippet(self):
        text = self._read("analysis-process.md")
        self.assertIn("gate_aware_sizing.py", text)
        self.assertNotIn("python3 -c", text)

    def test_output_templates_has_naming_contract_anchor(self):
        text = self._read("output-templates.md")
        self.assertIn("Как называть базу докупки", text)

    def test_bonds_and_funds_methodology_state_non_applicability(self):
        bonds = self._read("bonds-methodology.md")
        funds = self._read("funds-methodology.md")
        self.assertIn("докупка считается от плана корзины", bonds)
        # У фондов формулировка причины своя (корзин с планом по подтипам там нет),
        # поэтому сторож проверяет сам факт неприменимости и ссылку на правило акций.
        self.assertIn("**не применяется**", funds)
        self.assertIn("gate-aware-sizing.md", funds)  # раздел вынесен из stocks-methodology 2026-10-26

    def test_rebalance_framework_describes_goals_matrix_trap(self):
        text = self._read("rebalance-framework.md")
        self.assertIn("goals_matrix", text)
        self.assertIn("разрыв до полного плана", text)


# ─────────────────────────── 14. trim-to-target (задача A, spec-gate-aware-sizing-trim-fix.md) ───────────────────────────
#
# Пятая категория Rebalancing (срез до ОПРЕДЕЛЁННОЙ плановой доли — вне F, но в S) и её
# отличие от Selling (полный выход/срез без целевого веса — вне F и вне S). Числа §5 спеки
# проверены и на фикстуре ниже, и живым прогоном на реальном снапшоте (TestLiveCalibrationTrim).

class TestTrim51SellingRegression(unittest.TestCase):
    """5.1 — --selling (полный выход) не меняется правкой: побайтово то же поведение,
    что до введения --trim."""

    def test_full_exit_matches_reference_numbers(self):
        result = gas.run_sizing(
            trim_fix_snapshot(), trim_fix_gate_inputs(), trim_fix_conditions(),
            "X5,MBNK,LSNGP", "SBERP", None, 0.0, None, [],
        )
        self.assertEqual(result["base_source"], "fixed_point")
        self.assertAlmostEqual(result["base_rub"], 13_223_853, delta=5)
        self.assertAlmostEqual(result["base_pct_nav"], 30.87, places=2)
        self.assertAlmostEqual(result["s_open"], 0.13, places=6)
        self.assertEqual(result["classification"]["rebalancing"], [])

        by_ticker = {o["ticker"]: o for o in result["classification"]["open"]}
        self.assertAlmostEqual(by_ticker["X5"]["buy_rub"], 26_886, delta=6)
        self.assertAlmostEqual(by_ticker["MBNK"]["buy_rub"], 26_895, delta=6)
        self.assertAlmostEqual(by_ticker["LSNGP"]["buy_rub"], 163_359, delta=6)
        total_buy = sum(o["buy_rub"] for o in result["classification"]["open"])
        self.assertAlmostEqual(total_buy, 217_137, delta=6)


class TestTrim52MainCase(unittest.TestCase):
    """5.2 — основной кейс trim-to-target: SBERP срезается до плановых 8,0% вместо
    полного исключения из F/S. T* растёт (F не теряет неподвижную часть SBERP), S растёт
    на вес SBERP."""

    def _result(self):
        return gas.run_sizing(
            trim_fix_snapshot(cash_rub=171_247.47), trim_fix_gate_inputs(), trim_fix_conditions(),
            "X5,MBNK,LSNGP", None, None, 0.0, None, [], "SBERP=8.0",
        )

    def test_base_and_s(self):
        result = self._result()
        self.assertEqual(result["base_source"], "fixed_point")
        self.assertAlmostEqual(result["s_open"], 0.21, places=6)
        self.assertAlmostEqual(result["base_rub"], 14_562_975, delta=6)
        self.assertAlmostEqual(result["base_pct_nav"], 34.00, places=1)
        f_implied = result["base_rub"] * (1 - result["s_open"])
        self.assertAlmostEqual(f_implied, 11_504_751, delta=5)

    def test_sberp_is_rebalancing_with_trim_direction(self):
        result = self._result()
        self.assertEqual(len(result["classification"]["rebalancing"]), 1)
        sberp = result["classification"]["rebalancing"][0]
        self.assertEqual(sberp["ticker"], "SBERP")
        self.assertAlmostEqual(sberp["target_rub"], 1_165_038, delta=6)
        self.assertAlmostEqual(sberp["current_rub"], 1_225_626.12, delta=5)
        self.assertAlmostEqual(sberp["buy_rub"], -60_588, delta=6)
        self.assertEqual(sberp["direction"], "trim")
        # SBERP не должен появляться среди Selling/Blocked/Dormant — ушёл в Rebalancing.
        other_tickers = {x["ticker"] for x in result["classification"]["selling"]}
        other_tickers |= {x["ticker"] for x in result["classification"]["blocked"]}
        other_tickers |= {x["ticker"] for x in result["classification"]["dormant"]}
        self.assertNotIn("SBERP", other_tickers)

    def test_open_targets_and_deltas(self):
        result = self._result()
        by_ticker = {o["ticker"]: o for o in result["classification"]["open"]}
        self.assertAlmostEqual(by_ticker["X5"]["target_rub"], 873_780, delta=6)
        self.assertAlmostEqual(by_ticker["X5"]["buy_rub"], 107_235, delta=6)
        self.assertAlmostEqual(by_ticker["MBNK"]["target_rub"], 582_519, delta=6)
        self.assertAlmostEqual(by_ticker["MBNK"]["buy_rub"], 80_457, delta=6)
        self.assertAlmostEqual(by_ticker["LSNGP"]["target_rub"], 436_890, delta=6)
        self.assertAlmostEqual(by_ticker["LSNGP"]["buy_rub"], 203_532, delta=6)
        for o in by_ticker.values():
            self.assertEqual(o["direction"], "buy")

    def test_money_reconciliation(self):
        result = self._result()
        mr = result["money_reconciliation"]
        self.assertAlmostEqual(mr["buys_rub"], 391_224, delta=6)
        self.assertAlmostEqual(mr["trim_proceeds_rub"], 60_588, delta=6)
        self.assertAlmostEqual(mr["net_trading_need_rub"], 330_636, delta=6)
        self.assertEqual(mr["extra_cash_from_sales_rub"], 0.0)
        self.assertAlmostEqual(mr["cash_rub"], 171_247.47, delta=5)
        self.assertTrue(mr["is_deficit"])  # покупки (391 224) больше выручки+кэша (231 834)


class TestTrim53DefaultWeight(unittest.TestCase):
    """5.3 — --trim без явного веса берёт planned_share_pct из снапшота (8,0 для SBERP) и
    даёт результат, идентичный 5.2."""

    def test_trim_without_weight_uses_planned_share_pct(self):
        with_weight = gas.run_sizing(
            trim_fix_snapshot(), trim_fix_gate_inputs(), trim_fix_conditions(),
            "X5,MBNK,LSNGP", None, None, 0.0, None, [], "SBERP=8.0",
        )
        without_weight = gas.run_sizing(
            trim_fix_snapshot(), trim_fix_gate_inputs(), trim_fix_conditions(),
            "X5,MBNK,LSNGP", None, None, 0.0, None, [], "SBERP",
        )
        sberp_no_w = without_weight["classification"]["rebalancing"][0]
        self.assertEqual(sberp_no_w["weight_pct"], 8.0)
        self.assertEqual(sberp_no_w["weight_source"], "planned")
        self.assertAlmostEqual(without_weight["base_rub"], with_weight["base_rub"], delta=5)
        self.assertAlmostEqual(
            sberp_no_w["buy_rub"], with_weight["classification"]["rebalancing"][0]["buy_rub"], delta=1
        )

    def test_trim_both_weights_null_is_error(self):
        """Симметрично TestWeightResolution.test_both_null_is_error для --open: если у
        тикера в --trim нет ни override, ни planned_share_pct, ни ie_new_pct — понятная
        ошибка, а не подстановка нуля."""
        holdings = [mk_stock("DORM", 2_700_000), mk_stock("T1", 300_000)]
        per_ticker = {
            "DORM": mk_ie_row(planned=10.0, real=10.0),
            "T1": mk_ie_row(planned=None, ie=None, real=9.0),
        }
        snap = mk_snapshot(holdings, per_ticker, class_plan_rub=3_000_000, class_fact_rub=3_000_000, nav=15_000_000)
        with self.assertRaises(gas.GateAwareSizingError):
            gas.run_sizing(snap, None, None, None, None, None, 0.0, None, [], "T1")


class TestTrim54SellingVsTrimDiffer(unittest.TestCase):
    """5.4 — --selling и --trim того же тикера дают РАЗНЫЕ T*; тикер в обоих множествах
    одновременно → Selling (полный выход старше частичного) + warning."""

    def test_selling_and_trim_give_different_t_star(self):
        selling_result = gas.run_sizing(
            trim_fix_snapshot(), trim_fix_gate_inputs(), trim_fix_conditions(),
            "X5,MBNK,LSNGP", "SBERP", None, 0.0, None, [],
        )
        trim_result = gas.run_sizing(
            trim_fix_snapshot(), trim_fix_gate_inputs(), trim_fix_conditions(),
            "X5,MBNK,LSNGP", None, None, 0.0, None, [], "SBERP=8.0",
        )
        self.assertAlmostEqual(selling_result["base_rub"], 13_223_853, delta=5)
        self.assertAlmostEqual(trim_result["base_rub"], 14_562_975, delta=6)
        self.assertGreater(abs(trim_result["base_rub"] - selling_result["base_rub"]), 300_000)

    def test_ticker_in_both_selling_and_trim_becomes_selling_with_warning(self):
        result = gas.run_sizing(
            trim_fix_snapshot(), trim_fix_gate_inputs(), trim_fix_conditions(),
            "X5,MBNK,LSNGP", "SBERP", None, 0.0, None, [], "SBERP=8.0",
        )
        self.assertEqual(result["classification"]["rebalancing"], [])
        selling_tickers = {x["ticker"] for x in result["classification"]["selling"]}
        self.assertIn("SBERP", selling_tickers)
        self.assertIn("trim_overridden_by_selling:SBERP", result["warnings"])


class TestTrimS5OpenNegativeDeltaNeverTrims(unittest.TestCase):
    """S5 (решение владельца) — direction: "trim" присваивается ТОЛЬКО категории
    Rebalancing. Open-тикер с отрицательной дельтой сохраняет старую формулировку и НЕ
    получает direction "trim" — продажу для него аналитик не заказывал."""

    def test_open_ticker_already_above_target_gets_hold_not_trim(self):
        holdings = [mk_stock("DORM", 2_700_000), mk_stock("RICH", 600_000)]
        per_ticker = {
            "DORM": mk_ie_row(planned=15.0, real=15.0),
            # RICH: план 10% книги, но факт уже 60 000 / 3 300 000 = ~18% — выше цели.
            "RICH": mk_ie_row(planned=10.0, real=18.0),
        }
        snap = mk_snapshot(holdings, per_ticker, class_plan_rub=3_600_000, class_fact_rub=3_300_000, nav=15_000_000)
        result = gas.run_sizing(snap, None, None, "RICH=10", None, None, 0.0, None, [])
        rich = result["classification"]["open"][0]
        self.assertLess(rich["buy_rub"], 0)
        self.assertEqual(rich["direction"], "hold")
        report = gas.build_report_block(
            as_of=result["as_of"], nav=result["nav_excl_iis"],
            class_plan_rub=result["class_plan_rub"], class_fact_rub=result["class_fact_rub"],
            classification=result["_classification_raw"], sizing=result["_sizing_raw"], quotes=None,
        )
        self.assertIn("уже на цели или выше, докупка не требуется", report)
        self.assertNotIn("срезать", report)


class TestTrimS3DirectionFlip(unittest.TestCase):
    """S3 (решение владельца) — в вырожденной ветке (degenerate, blocked_sum <= 0) цели
    считаются от T_full; срез может развернуться в докупку. Молчаливый разворот
    недопустим: warning trim_direction_flipped:TICKER + явная строка в отчёте."""

    def test_no_gates_continuous_base_keeps_trim(self):
        # Непрерывная база (§10.6, 11.11): без решений/условий блокировок нет, но спящие бумаги в F своими рублями —
        # база та же неподвижная точка, что с гейтами (14 562 975 ₽, эталон §5.2), срез SBERP −60 588 ₽ без разворота.
        # Раньше ветка «нет блокировок → база = план класса 17 135 820 ₽» разворачивала срез в докупку +145 239 ₽.
        result = gas.run_sizing(
            trim_fix_snapshot(), None, None,
            "X5,MBNK,LSNGP", None, None, 0.0, None, [], "SBERP=8.0",
        )
        self.assertEqual(result["base_source"], "fixed_point")
        self.assertAlmostEqual(result["base_rub"], 14_562_975, delta=5)
        sberp = result["classification"]["rebalancing"][0]
        self.assertAlmostEqual(sberp["buy_rub"], -60_588, delta=6)
        self.assertEqual(sberp["direction"], "trim")
        self.assertNotIn("trim_direction_flipped:SBERP", result["warnings"])

    def test_nothing_frozen_flips_trim_to_buy_with_warning(self):
        # В F ничего нет → база = план класса 3 000 000 ₽; цель среза SBP 18 % × 3 000 000 = 540 000 > 300 000 →
        # разворот в докупку с предупреждением (S3)
        holdings = [mk_stock("SBP", 300_000), mk_stock("A", 1_200_000)]
        per = {"SBP": mk_ie_row(planned=18.0, real=20.0), "A": mk_ie_row(planned=70.0, real=80.0)}
        snap = mk_snapshot(holdings, per, class_plan_rub=3_000_000, class_fact_rub=1_500_000, nav=15_000_000)
        result = gas.run_sizing(snap, None, None, "A", None, None, 0.0, None, [], "SBP=18")
        self.assertEqual(result["base_source"], "t_full_no_gates")
        sbp = result["classification"]["rebalancing"][0]
        self.assertAlmostEqual(sbp["target_rub"], 540_000, delta=5)
        self.assertEqual(sbp["direction"], "buy")
        self.assertIn("trim_direction_flipped:SBP", result["warnings"])

        report = gas.build_report_block(
            as_of=result["as_of"], nav=result["nav_excl_iis"],
            class_plan_rub=result["class_plan_rub"], class_fact_rub=result["class_fact_rub"],
            classification=result["_classification_raw"], sizing=result["_sizing_raw"], quotes=None,
        )
        self.assertIn("развернулся в докупку", report)


class TestTrimS7ExtraCashDoubleCountRisk(unittest.TestCase):
    """S7 (решение владельца) — --trim TICKER одновременно с ненулевым
    --extra-cash-from-sales — риск двойного счёта выручки от продаж."""

    def _snap(self):
        holdings = [mk_stock("BLK", 1_200_000), mk_stock("TRIM1", 300_000)]
        per_ticker = {
            "BLK": mk_ie_row(planned=20.0, real=5.0),
            "TRIM1": mk_ie_row(planned=5.0, real=9.0),
        }
        return mk_snapshot(holdings, per_ticker, class_plan_rub=3_000_000, class_fact_rub=1_500_000, nav=15_000_000)

    def test_warning_present_with_nonzero_extra_cash(self):
        gate_inputs = mk_gate_inputs({"BLK": "review_needed"})
        result = gas.run_sizing(
            self._snap(), gate_inputs, None, None, None, None,
            150_000.0, None, [], "TRIM1=5.0",
        )
        self.assertIn("extra_cash_from_sales_double_count_risk", result["warnings"])

    def test_no_warning_without_extra_cash(self):
        gate_inputs = mk_gate_inputs({"BLK": "review_needed"})
        result = gas.run_sizing(
            self._snap(), gate_inputs, None, None, None, None,
            0.0, None, [], "TRIM1=5.0",
        )
        self.assertNotIn("extra_cash_from_sales_double_count_risk", result["warnings"])


class TestTrim55DegenerateGuardBreakdown(unittest.TestCase):
    """5.5 — guard на вырожденность (S >= 0,99) с участием Rebalancing: расчёт не
    досчитывается, near_degenerate_manual_check в warnings (плоский токен сохранён для
    совместимости), и s_breakdown раскладывает вклад в S по open/rebalancing."""

    def test_guard_fires_with_rebalancing_contribution_and_breakdown(self):
        holdings = [mk_stock("BLK", 300_000), mk_stock("A", 120_000), mk_stock("TRIM1", 165_000)]
        per_ticker = {
            "BLK": mk_ie_row(planned=5.0, real=1.0),
            "A": mk_ie_row(planned=60.0, real=10.0),
            "TRIM1": mk_ie_row(planned=39.5, real=55.0),
        }
        snap = mk_snapshot(holdings, per_ticker, class_plan_rub=3_000_000, class_fact_rub=585_000, nav=15_000_000)
        gate_inputs = mk_gate_inputs({"BLK": "review_needed"})
        result = gas.run_sizing(snap, gate_inputs, None, "A=60", None, None, 0.0, None, [], "TRIM1=39.5")

        self.assertEqual(result["base_source"], "manual_check_required")
        self.assertIsNone(result["base_rub"])
        self.assertAlmostEqual(result["s_open"], 0.995, places=6)
        self.assertIn("near_degenerate_manual_check", result["warnings"])
        self.assertEqual(result["s_breakdown"]["open"], [{"ticker": "A", "weight_pct": 60.0}])
        self.assertEqual(result["s_breakdown"]["rebalancing"], [{"ticker": "TRIM1", "weight_pct": 39.5}])

        report = gas.build_report_block(
            as_of=result["as_of"], nav=result["nav_excl_iis"],
            class_plan_rub=result["class_plan_rub"], class_fact_rub=result["class_fact_rub"],
            classification=result["_classification_raw"], sizing=result["_sizing_raw"], quotes=None,
        )
        self.assertIn("A", report)
        self.assertIn("TRIM1", report)


class TestTrim56LotsAndDirection(unittest.TestCase):
    """5.6 — направление округления по лотам: покупка floor (lots × lot_rub <= delta),
    срез ceil (lots × lot_rub >= |delta|); без price/lot_size — lots=None + warning
    (существующее поведение)."""

    def test_ceil_rounding_for_trim_with_signed_remainder(self):
        lots, remainder, price = gas.compute_lots(-60_588.06, {"last": 3000.0, "lot_size": 1})
        self.assertEqual(lots, 21)
        self.assertAlmostEqual(price, 3000.0)
        self.assertLessEqual(21 * 3000.0, 60_588.06 + 3000.0)  # ceil — как минимум один лот сверху
        self.assertGreaterEqual(21 * 3000.0, 60_588.06)  # дорезано не меньше запрошенного
        self.assertLess(remainder, 0)  # remainder со знаком, соответствующим направлению (срез)

    def test_floor_rounding_for_buy_unchanged_sign(self):
        lots, remainder, price = gas.compute_lots(26_886.09, {"last": 3000.0, "lot_size": 1})
        self.assertEqual(lots, 8)
        self.assertLessEqual(8 * 3000.0, 26_886.09)
        self.assertGreater(remainder, 0)

    def test_end_to_end_buy_and_trim_directions_with_quotes(self):
        quotes = {"X5": {"last": 3000.0, "lot_size": 1}, "SBERP": {"last": 3000.0, "lot_size": 1}}
        result = gas.run_sizing(
            trim_fix_snapshot(), trim_fix_gate_inputs(), trim_fix_conditions(),
            "X5,MBNK,LSNGP", None, None, 0.0, quotes, [], "SBERP=8.0",
        )
        x5 = next(o for o in result["classification"]["open"] if o["ticker"] == "X5")
        sberp = result["classification"]["rebalancing"][0]
        lots_x5, _, _ = gas.compute_lots(x5["buy_rub"], quotes["X5"])
        lots_sberp, _, _ = gas.compute_lots(sberp["buy_rub"], quotes["SBERP"])
        self.assertLessEqual(lots_x5 * 3000.0, x5["buy_rub"])
        self.assertGreaterEqual(lots_sberp * 3000.0, abs(sberp["buy_rub"]))
        # MBNK/LSNGP без котировок в quotes-словаре ключом — тоже без цены → lots_unavailable.
        self.assertIn("lots_unavailable:MBNK", result["warnings"])
        self.assertIn("lots_unavailable:LSNGP", result["warnings"])


class TestTrim57PostTradeWeights(unittest.TestCase):
    """5.7 — weight_after_pct считается от ФАКТИЧЕСКОЙ пост-трейд книги (не от T*, S4);
    после округления по лотам ни один тикер не должен превышать w_i больше чем на
    0,25 пп — при превышении тикер попадает в cap_breach_after_rounding.

    Механизм: округление лотами уменьшает знаменатель (сумму пост-трейд книги) сильнее,
    чем числитель конкретного тикера, если у ДРУГИХ sized-тикеров лот крупный
    относительно их дельты — тогда относительный вес этого тикера растёт выше плана,
    хотя сам он ни на йоту не докуплен сверх цели.

    Пересчёт 28.10 (правило «на плане» в ручном режиме). Старая фикстура: BLK 2 100 000 ₽ с
    плановой долей 15% при книге 2 400 000 ₽ (15% × книга = 360 000 ₽) перевешена и ушла бы в S:
    база 3 000 000 ₽ (план класса), A и B садятся на 300 000 ₽ — число 2 625 000 ₽ исчезает, а с
    ним и сам сценарий «неподвижная точка + грубый лот». Фикстура подправлена: у BLK нет плановой
    доли (planned=None, ie=15) — рубли остаются в F, база прежняя 2 625 000 ₽ и механизм
    общего знаменателя проверяется как раньше."""

    def test_coarse_lot_on_one_ticker_breaches_another_via_shared_denominator(self):
        holdings = [mk_stock("BLK", 2_100_000), mk_stock("A", 150_000), mk_stock("B", 150_000)]
        per_ticker = {
            "BLK": mk_ie_row(planned=None, ie=15.0, real=5.0),
            "A": mk_ie_row(planned=10.0, real=5.0),
            "B": mk_ie_row(planned=10.0, real=5.0),
        }
        snap = mk_snapshot(holdings, per_ticker, class_plan_rub=3_000_000, class_fact_rub=2_400_000, nav=15_000_000)
        gate_inputs = mk_gate_inputs({"BLK": "review_needed"})
        # Лот A — 240 000 ₽ (лот 80 по 3000 ₽), сильно грубее дельты 112 500 ₽ → floor даёт 0
        # лотов, A остаётся почти на месте. B без quote — цель достигается точно.
        quotes = {"A": {"last": 3000.0, "lot_size": 80}}
        result = gas.run_sizing(snap, gate_inputs, None, "A=10,B=10", None, None, 0.0, quotes, [])

        self.assertAlmostEqual(result["base_rub"], 2_625_000, delta=5)
        by_ticker = {o["ticker"]: o for o in result["classification"]["open"]}
        self.assertLess(by_ticker["A"]["weight_after_pct"], 10.0)
        self.assertGreater(by_ticker["B"]["weight_after_pct"] - 10.0, 0.25)
        self.assertEqual(result["cap_breach_after_rounding"], ["B"])

        report = gas.build_report_block(
            as_of=result["as_of"], nav=result["nav_excl_iis"],
            class_plan_rub=result["class_plan_rub"], class_fact_rub=result["class_fact_rub"],
            classification=result["_classification_raw"], sizing=result["_sizing_raw"], quotes=quotes,
        )
        self.assertIn("Округление по лотам", report)
        self.assertIn("B", report)


class TestStructuralOffsetNotReportedAsRoundingBreach(unittest.TestCase):
    """Регрессия ревью 26.08.2026: `cap_breach_after_rounding` срабатывал на 100% sized-тикеров
    в ветке `t_full_no_gates` при полностью отсутствующих котировках — то есть когда округлять
    было нечего. Причина не в лотности: цели там считаются от полного плана класса, а книга
    ниже него, поэтому каждый тикер садится выше своего веса относительно факта (цена
    варианта B, `gate-aware-sizing.md` §«Три варианта денежной базы»).

    Предупреждение, срабатывающее на всех, — шум, из-за которого пропускают настоящее
    нарушение. Структурное отклонение уходит в `structural_cap_offset` и в отчёт одной
    строкой; `cap_breach_after_rounding` реагирует только на вклад округления.

    Контраст «fixed_point ↔ t_full_no_gates» (28.10): с правилом «на плане» перевешенный BLK
    (2 100 000 ₽ против 15% × 2 400 000 ₽ = 360 000 ₽) ушёл бы в S и дал t_full_no_gates с
    структурным отклонением и в «gated»-ветке — контраст исчез бы. В фикстуре у BLK нет плановой
    доли (planned=None, ie=15): рубли в F, ветка fixed_point сохранена."""

    def _degenerate_result(self, quotes=None):
        # В F ничего нет (D тоже двигается, --trim) → ветка t_full_no_gates (непрерывная база §10.6: только так).
        holdings = [mk_stock("D", 2_100_000), mk_stock("A", 150_000), mk_stock("B", 150_000)]
        per_ticker = {
            "D": mk_ie_row(planned=15.0, real=15.0),
            "A": mk_ie_row(planned=10.0, real=5.0),
            "B": mk_ie_row(planned=10.0, real=5.0),
        }
        snap = mk_snapshot(holdings, per_ticker, class_plan_rub=3_000_000, class_fact_rub=2_400_000, nav=15_000_000)
        return gas.run_sizing(snap, None, None, "A=10,B=10", None, None, 0.0, quotes, [], "D=15")

    def test_no_quotes_means_no_rounding_breach(self):
        result = self._degenerate_result()
        self.assertEqual(result["base_source"], "t_full_no_gates")
        self.assertEqual(
            result["cap_breach_after_rounding"], [],
            "без котировок округления не было — нарушения от округления быть не может",
        )
        self.assertEqual(sorted(result["structural_cap_offset"]), ["A", "B", "D"])

    def test_structural_offset_rendered_once_not_per_ticker(self):
        result = self._degenerate_result()
        report = gas.build_report_block(
            as_of=result["as_of"], nav=result["nav_excl_iis"],
            class_plan_rub=result["class_plan_rub"], class_fact_rub=result["class_fact_rub"],
            classification=result["_classification_raw"], sizing=result["_sizing_raw"], quotes=None,
        )
        self.assertIn("Пока класс недобран", report)
        self.assertNotIn("Округление по лотам", report)
        self.assertEqual(report.count("Пока класс недобран"), 1)

    def test_fixed_point_branch_has_no_structural_offset(self):
        """Контраст: с гейтом база равна пост-трейд книге, веса ложатся ровно в план."""
        holdings = [mk_stock("BLK", 2_100_000), mk_stock("A", 150_000), mk_stock("B", 150_000)]
        per_ticker = {
            "BLK": mk_ie_row(planned=None, ie=15.0, real=5.0),
            "A": mk_ie_row(planned=10.0, real=5.0),
            "B": mk_ie_row(planned=10.0, real=5.0),
        }
        snap = mk_snapshot(holdings, per_ticker, class_plan_rub=3_000_000, class_fact_rub=2_400_000, nav=15_000_000)
        result = gas.run_sizing(snap, mk_gate_inputs({"BLK": "review_needed"}), None,
                                "A=10,B=10", None, None, 0.0, None, [])
        self.assertEqual(result["base_source"], "fixed_point")
        self.assertEqual(result["structural_cap_offset"], [])
        self.assertEqual(result["cap_breach_after_rounding"], [])
        for o in result["classification"]["open"]:
            self.assertAlmostEqual(o["weight_after_pct"], o["weight_pct"], places=6)


class TestCashBufferRule(unittest.TestCase):
    """Правило кэша (`gate-aware-sizing.md` §«Сколько кэша считать нормальным...»):

        ожидаемый_кэш = buffer_pct% × NAV + (полный план класса − база докупки)

    Вынесено из чистого текста в код намеренно: 19.08.2026 методика сайзинга уже была
    записана в референсы и в тот же день не сработала (ошибка ×14 на `goals_matrix.Изменение`).
    «Не выдумывай цифры» распространяется и на арифметику.

    Пересчёт 28.10 (правило «на плане» в ручном режиме): в фикстуре BLK 2 100 000 ₽ при плановой
    доле 15% и книге 2 250 000 ₽ перевешен (15% × 2 250 000 = 337 500 ₽) и ушёл бы в S: база =
    план класса 3 000 000 ₽, «закрытый гейтами» компонент 0, ожидаемый кэш 600 000 ₽ вместо
    1 266 666 ₽ (тогда любой кэш выше 600 000 ₽ — тревога, и тест «тревога односторонняя» с
    кэшем 900 000 ₽ ожидаемо красный). Чтобы формула проверялась на ветке fixed_point
    (разрыв 666 666 ₽ — реальный кейс), у BLK нет плановой доли (planned=None, ie=15); число
    для нового правила закреплено в TestFrozenOnPlanManualDefault.test_cash_buffer_original_fixture."""

    # 11.11 (§10.6 п.4): в ожидаемый кэш идёт только слагаемое гейтов разрыва «план − база» — недобор BLK до своей доли
    # плана; недобор спящих (D) и нераспределённая доля плана места не бронируют. Фикстура: BLK 300 000 (план 15%, под
    # гейтом), A 150 000 (план 10%, открыта), D 1 800 000 (план 70%, спящая); база = 2 100 000 / 0,9 = 2 333 334, разрыв 666 666 =
    # гейты (450 000 − 300 000)/0,9 = 166 668 + спящие (2 100 000 − 1 800 000)/0,9 = 333 333 + нераспределённые 5% 166 668.
    def _snap(self, liquid=None, total=171_247.47):
        holdings = [mk_stock("BLK", 300_000), mk_stock("A", 150_000), mk_stock("D", 1_800_000)]
        per_ticker = {"BLK": mk_ie_row(planned=15.0, real=13.3), "A": mk_ie_row(planned=10.0, real=6.7),
                      "D": mk_ie_row(planned=70.0, real=80.0)}
        snap = mk_snapshot(holdings, per_ticker, class_plan_rub=3_000_000,
                           class_fact_rub=2_250_000, nav=15_000_000)
        cash = {"total_rub": total}
        if liquid is not None:
            cash["liquid_rub"] = liquid
        snap["cash"] = cash
        return snap

    def _run(self, snap, buffer_pct=4.0):
        return gas.run_sizing(snap, mk_gate_inputs({"BLK": "review_needed"}), None,
                              "A=10", None, None, 0.0, None, [], None, None, None, 1.0,
                              None, False, None, buffer_pct)

    def test_formula_components(self):
        r = self._run(self._snap(liquid=2_700_000))
        cb = r["cash_buffer"]
        self.assertAlmostEqual(r["base_rub"], 2_333_334, delta=5)
        self.assertAlmostEqual(r["blocked_gap_rub"], 666_666, delta=5)
        self.assertAlmostEqual(r["gap_gated_rub"], 166_668, delta=5)
        self.assertAlmostEqual(r["gap_in_corridor_rub"], 333_333, delta=5)
        self.assertAlmostEqual(r["gap_unallocated_rub"], 166_668, delta=5)
        self.assertAlmostEqual(r["gap_gated_rub"] + r["gap_in_corridor_rub"] + r["gap_unallocated_rub"],
                               r["blocked_gap_rub"], delta=0.01)
        self.assertAlmostEqual(cb["buffer_component_rub"], 600_000, delta=5)   # 4% × 15 000 000
        self.assertAlmostEqual(cb["gated_component_rub"], 166_668, delta=6)     # только гейты
        self.assertAlmostEqual(cb["expected_cash_rub"], 766_668, delta=6)

    def test_uses_liquid_not_total(self):
        """cash.liquid_rub и cash.total_rub — РАЗНЫЕ величины. На живых данных 21.08.2026
        разрыв между ними 3 785 988 ₽ (money-market), и по total_rub правило показывало бы
        вечную нехватку 96% и при односторонней тревоге молчало бы всегда."""
        r = self._run(self._snap(liquid=2_700_000, total=3_000))
        self.assertEqual(r["cash_buffer"]["liquid_cash_rub"], 2_700_000)

    def test_no_liquid_field_means_no_number_invented(self):
        """Фолбэка на total_rub нет намеренно — подмена похожего поля запрещена."""
        r = self._run(self._snap(liquid=None))
        self.assertIsNone(r["cash_buffer"])
        self.assertNotIn("cash_above_expected", r["warnings"])

    def test_alarm_is_one_sided_excess_only(self):
        above = self._run(self._snap(liquid=2_700_000))
        self.assertTrue(above["cash_buffer"]["above_expected"])
        self.assertIn("cash_above_expected", above["warnings"])
        below = self._run(self._snap(liquid=600_000))
        self.assertFalse(below["cash_buffer"]["above_expected"])
        self.assertNotIn("cash_above_expected", below["warnings"],
                         "кэш ниже ожидаемого — рабочее состояние, тревоги быть не должно")

    def test_buffer_pct_is_parameter(self):
        r4 = self._run(self._snap(liquid=2_700_000), buffer_pct=4.0)
        r8 = self._run(self._snap(liquid=2_700_000), buffer_pct=8.0)
        self.assertAlmostEqual(
            r8["cash_buffer"]["expected_cash_rub"] - r4["cash_buffer"]["expected_cash_rub"],
            600_000, delta=5)

    def test_not_computed_when_base_not_resolved(self):
        """near_degenerate: базы нет — ожидаемый кэш не выдумывается."""
        holdings = [mk_stock("BLK", 2_100_000), mk_stock("A", 150_000)]
        per_ticker = {"BLK": mk_ie_row(planned=15.0, real=5.0), "A": mk_ie_row(planned=99.5, real=5.0)}
        snap = mk_snapshot(holdings, per_ticker, 3_000_000, 2_250_000, 15_000_000)
        snap["cash"] = {"total_rub": 3_000.0, "liquid_rub": 2_700_000.0}
        r = gas.run_sizing(snap, mk_gate_inputs({"BLK": "review_needed"}), None,
                           "A=99.5", None, None, 0.0, None, [])
        self.assertIsNone(r["base_rub"])
        self.assertIsNone(r["cash_buffer"])


class TestTrimCandidateHint(unittest.TestCase):
    """§6 задания — `--trim` остаётся РУЧНЫМ флагом, автоклассификации нет. Но снапшот несёт
    сигнал с определённой целевой долей (`user_plan: BALANCE` + `planned_share_pct`), на
    котором дискриминатор §4.1 выполним, — значит подсказать можно, ничего не выдумывая.

    Порог намеренно НЕ гистерезис Rule 3: флаг решает, попадёт ли ВСЯ позиция в `S` или
    останется в `F`, поэтому цена ошибки зависит от размера позиции, а не перевеса. Кейс
    21.08.2026: перевес SBERP 0,61 пп (внутри гистерезиса), позиция 1 225 626 ₽, занижение
    базы 1 339 122 ₽."""

    def _snap(self, user_plan, real, planned=8.0):
        holdings = [mk_stock("BLK", 2_100_000), mk_stock("SBERP", 1_200_000), mk_stock("A", 150_000)]
        per_ticker = {
            "BLK": mk_ie_row(planned=15.0, real=5.0),
            "SBERP": {"planned_share_pct": planned, "real_share_pct": real, "user_plan": user_plan},
            "A": mk_ie_row(planned=10.0, real=5.0),
        }
        return mk_snapshot(holdings, per_ticker, 3_000_000, 2_400_000, 15_000_000)

    def _hints(self, snap, trim_arg=None, selling_arg=None):
        r = gas.run_sizing(snap, mk_gate_inputs({"BLK": "review_needed"}), None,
                           "A=10", selling_arg, None, 0.0, None, [], trim_arg)
        return r, {h["ticker"] for h in r["trim_candidate_hints"]}

    def test_balance_with_excess_inside_hysteresis_still_hinted(self):
        """Главный кейс: перевес 0,61 пп меньше гистерезиса 1,0 — подсказка обязана быть."""
        r, hinted = self._hints(self._snap("BALANCE", real=8.61))
        self.assertIn("SBERP", hinted)
        self.assertIn("trim_candidate_hint:SBERP", r["warnings"])
        hint = r["trim_candidate_hints"][0]
        self.assertAlmostEqual(hint["excess_pp"], 0.61, places=2)

    def test_no_hint_when_flag_already_passed(self):
        _, hinted = self._hints(self._snap("BALANCE", real=8.61), trim_arg="SBERP=8.0")
        self.assertNotIn("SBERP", hinted)

    def test_no_hint_when_selling(self):
        """Полный выход — не кандидат на трим, подсказка была бы вредной."""
        _, hinted = self._hints(self._snap("BALANCE", real=8.61), selling_arg="SBERP")
        self.assertNotIn("SBERP", hinted)

    def test_no_hint_without_excess(self):
        _, hinted = self._hints(self._snap("BALANCE", real=7.4))
        self.assertNotIn("SBERP", hinted)

    def test_no_hint_for_other_user_plans(self):
        """KEEP/BUY/SELL целевой доли после сокращения не задают — дискриминатор §4.1
        на них не выполним, подсказка невозможна."""
        for plan in ("KEEP", "BUY", "SELL", None):
            _, hinted = self._hints(self._snap(plan, real=8.61))
            self.assertNotIn("SBERP", hinted, f"user_plan={plan!r} не должен давать подсказку")

    def test_hint_is_not_autoclassification(self):
        """Подсказка НЕ переводит тикер в Rebalancing — §6 это прямо запрещает."""
        r, _ = self._hints(self._snap("BALANCE", real=8.61))
        self.assertEqual([o["ticker"] for o in r["classification"]["rebalancing"]], [])
        self.assertIn("SBERP", [d["ticker"] for d in r["classification"]["dormant"]]
                                + [b["ticker"] for b in r["classification"]["blocked"]])


class TestTrimLintDraftIgnoresSrezat(unittest.TestCase):
    """`--lint-draft` не должен считать отрицательные суммы (срез) нарушением —
    `_PURCHASE_VERB_RE` не матчит «срезать»/«срез» (проверено вручную, закрепляем тестом)."""

    def test_purchase_verb_regex_does_not_match_trim_words(self):
        for word in ("срезать", "срез", "срезал", "сократить"):
            self.assertIsNone(
                gas._PURCHASE_VERB_RE.search(word),
                f"_PURCHASE_VERB_RE неожиданно матчит {word!r}",
            )

    def test_trim_only_draft_without_base_line_is_clean(self):
        text = "Разбор недели.\nСрезать SBERP на 60 600 ₽ до плановых 8%.\n"
        violations = gas.lint_draft(text, {"SBERP"})
        self.assertEqual(violations, [])

    def test_cli_lint_draft_clean_for_trim_only_text(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as sf:
            json.dump(trim_fix_snapshot(), sf)
            snap_path = sf.name
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as df:
            df.write("Срезать SBERP на 60 600 ₽ до плановых 8%.\n")
            draft_path = df.name
        try:
            proc = subprocess.run(
                [PY, SCRIPT_PATH, "--snapshot", snap_path, "--lint-draft", draft_path],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        finally:
            os.unlink(snap_path)
            os.unlink(draft_path)


# ─── 15. Правило неразворота (задача B, §8/§10.3 spec-gate-aware-sizing-trim-fix.md) ───
#
# §8.2 B3 из постановки ОТМЕНЁН поправкой §10.3 (26.08.2026): признак «сделка уже была»
# не замораживает бумагу независимо от направления — запрещён только РАЗВОРОТ. B-T5 ниже
# написан под §10.3, а не под §8.4 (тот записан под отменённую редакцию).
#
# Пять состояний цикла C1..C5 — та же фикстура trim_fix_snapshot()/_TRIM_FIX_ROWS, что и у
# задачи A: базы и цели SBERP, воспроизводимые ниже, совпадают с числами §8.4/§11 спеки
# (проверено владельцем лично на реальном снапшоте portfolio-2026-08-21.json).

B_CYCLES = [
    {"label": "C1", "open": {"SBERP": 8.0}},
    {"label": "C2", "open": {"SBERP": 8.0, "MBNK": 4.0}},
    {"label": "C3", "open": {"SBERP": 8.0, "MBNK": 4.0, "X5": 6.0, "LSNGP": 3.0}},
    {"label": "C4", "open": {"SBERP": 8.0, "MBNK": 4.0, "X5": 6.0, "LSNGP": 3.0, "MOEX": 8.0}},
    {"label": "C5", "open": {"SBERP": 8.0, "MBNK": 4.0, "X5": 6.0, "LSNGP": 3.0, "MOEX": 8.0, "RENI": 12.0}},
]

# Немонотонный список: после сегодняшнего состояния появляется НОВЫЙ гейт (RENI уходит из
# открытых). §8.1 задания называет это симметричной половиной проблемы — база падает, и
# недавно докупленная бумага оказывается в перевесе.
B_CYCLES_NEW_GATE = [
    {"label": "NOW", "open": {"SBERP": 8.0, "MBNK": 4.0, "X5": 6.0, "LSNGP": 3.0, "MOEX": 8.0, "RENI": 12.0}},
    {"label": "NEWGATE", "open": {"SBERP": 8.0, "MBNK": 4.0, "X5": 6.0, "LSNGP": 3.0, "MOEX": 8.0}},
]


class TestB2NewGateReversalIsDetected(unittest.TestCase):
    """Регрессия ревью 27.08.2026. Первая редакция фильтра будущих состояний требовала,
    чтобы состав открытых тикеров состояния был НАДмножеством сегодняшнего, и потому
    отбрасывала целиком любое состояние, где открытых МЕНЬШЕ, — то есть ровно случай
    «появился новый гейт». На живом снапшоте цель X5 падала 899 922 → 877 419 ₽
    (22 503 ₽), и разворот не показывался даже при гистерезисе 0,01 пп.

    Фильтр переведён на ПОРЯДОК в списке: сравниваются состояния после сегодняшнего."""

    def _risk(self, hysteresis_pp):
        result = gas.run_sizing(
            trim_fix_snapshot(), trim_fix_gate_inputs(), trim_fix_conditions(),
            "X5=6,MBNK=4,LSNGP=3,MOEX=8,RENI=12", None, None, 0.0, None, [],
            "SBERP=8.0", None, B_CYCLES_NEW_GATE, hysteresis_pp,
        )
        return {r["ticker"]: r for r in result["reversal_risk"]}

    def test_new_gate_shrinking_open_set_is_flagged(self):
        flagged = self._risk(0.1)
        self.assertIn("X5", flagged, "падение цели при новом гейте обязано попасть в reversal_risk")
        self.assertEqual(flagged["X5"]["cycle"], "NEWGATE")
        self.assertAlmostEqual(flagged["X5"]["amount_rub"], 22_506, delta=3)

    def test_default_hysteresis_still_silent(self):
        """Отклонение 22 506 ₽ = 0,16 пп — ниже штатного порога 1,0 пп, флаг молчит.
        Проверка, что правка не превратила механизм в источник ложных тревог."""
        self.assertEqual(self._risk(1.0), {})

    def test_warning_when_today_state_absent_from_cycles(self):
        """Сегодняшний состав не описан ни одним состоянием списка → положение во времени
        неизвестно, сравнение идёт против всех состояний. Пользователь должен узнать об
        этом из warnings[], а не гадать по числу записей в reversal_risk."""
        absent = gas.run_sizing(
            trim_fix_snapshot(), trim_fix_gate_inputs(), trim_fix_conditions(),
            "X5,MBNK,LSNGP", None, None, 0.0, None, [], "SBERP=8.0", None,
            B_CYCLES_NEW_GATE, 1.0,
        )
        self.assertIn("cycles_today_state_not_listed", absent["warnings"])

        present = gas.run_sizing(
            trim_fix_snapshot(), trim_fix_gate_inputs(), trim_fix_conditions(),
            "X5,MBNK,LSNGP", None, None, 0.0, None, [], "SBERP=8.0", None,
            B_CYCLES, 1.0,
        )
        self.assertNotIn("cycles_today_state_not_listed", present["warnings"])


class TestB1TargetRangeCheck(unittest.TestCase):
    """B-T1 — диапазон целей по 5 состояниям цикла. Базы 14 137 734 / 14 209 833 /
    14 562 975 / 14 623 626 / 14 998 725 ₽ и цели SBERP 1 131 018 / 1 136 787 / 1 165 038 /
    1 169 889 / 1 199 898 ₽, допуск ±2 ₽ (числа проверены владельцем лично)."""

    EXPECTED_TARGETS = {
        "C1": 1_131_018, "C2": 1_136_787, "C3": 1_165_038, "C4": 1_169_889, "C5": 1_199_898,
    }

    def test_sberp_target_by_cycle_matches_reference(self):
        holdings = gas.active_stock_holdings(trim_fix_snapshot())
        ranges, total_book = gas.compute_cycle_targets(holdings, B_CYCLES)
        self.assertAlmostEqual(total_book, 14_232_340.5, delta=5)
        sberp = ranges["SBERP"]
        for label, expected in self.EXPECTED_TARGETS.items():
            self.assertAlmostEqual(sberp["target_by_cycle"][label], expected, delta=6)
        self.assertAlmostEqual(sberp["target_min"], 1_131_018, delta=6)
        self.assertAlmostEqual(sberp["target_max"], 1_199_898, delta=6)
        self.assertAlmostEqual(sberp["current_rub"], 1_225_626.12, delta=5)

    def test_bases_by_cycle_match_reference(self):
        """База каждого состояния воспроизводится через отношение T*=target/w — независимая
        проверка тех же чисел без опоры на внутренний total_book."""
        holdings = gas.active_stock_holdings(trim_fix_snapshot())
        ranges, _ = gas.compute_cycle_targets(holdings, B_CYCLES)
        expected_bases = {
            "C1": 14_137_734, "C2": 14_209_833, "C3": 14_562_975,
            "C4": 14_623_626, "C5": 14_998_725,
        }
        sberp = ranges["SBERP"]
        for label, expected_base in expected_bases.items():
            base = sberp["target_by_cycle"][label] / 0.08
            self.assertAlmostEqual(base, expected_base, delta=6)

    def test_run_sizing_exposes_target_ranges_via_cycles_arg(self):
        """--cycles подключён в CLI-цепочке (run_sizing), не только в отдельной функции."""
        result = gas.run_sizing(
            trim_fix_snapshot(), trim_fix_gate_inputs(), trim_fix_conditions(),
            None, None, None, 0.0, None, [], "SBERP=8.0", None, B_CYCLES, 1.0,
        )
        self.assertIn("SBERP", result["target_ranges"])
        self.assertAlmostEqual(result["target_ranges"]["SBERP"]["target_max"], 1_199_898, delta=6)

    def test_cli_end_to_end_with_cycles_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as sf:
            json.dump(trim_fix_snapshot(), sf)
            snap_path = sf.name
        gdir = tempfile.mkdtemp(prefix="gas-cli-")
        gate_args = write_gate_cli_inputs(gdir, trim_fix_gate_inputs(), trim_fix_conditions())
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as clf:
            json.dump(B_CYCLES, clf)
            cycles_path = clf.name
        try:
            proc = subprocess.run(
                [PY, SCRIPT_PATH, "--snapshot", snap_path] + gate_args + [
                 "--trim", "SBERP=8.0", "--cycles", cycles_path, "--json"],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertAlmostEqual(payload["target_ranges"]["SBERP"]["target_max"], 1_199_898, delta=6)
        finally:
            for p in (snap_path, cycles_path):
                os.unlink(p)
            import shutil
            shutil.rmtree(gdir, ignore_errors=True)

    def test_load_cycles_file_missing_raises(self):
        with self.assertRaises(gas.GateAwareSizingError):
            gas.load_cycles_file("/tmp/does-not-exist-cycles-xyz.json")

    def test_load_cycles_file_malformed_raises(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"not": "a list"}, f)
            path = f.name
        try:
            with self.assertRaises(gas.GateAwareSizingError):
                gas.load_cycles_file(path)
        finally:
            os.unlink(path)

    def test_load_cycles_file_missing_label_or_open_raises(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump([{"label": "C1"}], f)
            path = f.name
        try:
            with self.assertRaises(gas.GateAwareSizingError):
                gas.load_cycles_file(path)
        finally:
            os.unlink(path)


class TestB2ReversalRiskFlag(unittest.TestCase):
    """B-T2/B-T3/B-T4 — флаг разворота: предупреждение (не блокировка), гистерезис —
    параметр (не константа), знак не путает продолжение движения с разворотом."""

    def _run(self, hysteresis_pp):
        return gas.run_sizing(
            trim_fix_snapshot(), trim_fix_gate_inputs(), trim_fix_conditions(),
            None, None, None, 0.0, None, [], "SBERP=8.0", None, B_CYCLES, hysteresis_pp,
        )

    def test_bt2_no_reversal_at_default_hysteresis(self):
        """Действие «срезать SBERP до 1 131 018» при hysteresis=1,0 (Rule 3, дефолт) —
        максимальное последующее отклонение 68 880 ₽ = 0,48 пп < 1,0 пп → пусто."""
        result = self._run(gas._DEFAULT_HYSTERESIS_PP)
        self.assertEqual(result["hysteresis_pp"], 1.0)
        self.assertEqual(result["reversal_risk"], [])
        # Расчёт всё равно досчитан — предупреждение не блокирует (пусто здесь, но и
        # база, и цель по SBERP обязаны быть на месте).
        self.assertAlmostEqual(result["base_rub"], 14_137_734, delta=6)

    def test_bt3_reversal_detected_at_lower_hysteresis(self):
        result = self._run(0.4)
        self.assertEqual(len(result["reversal_risk"]), 1)
        risk = result["reversal_risk"][0]
        self.assertEqual(risk["ticker"], "SBERP")
        self.assertEqual(risk["cycle"], "C5")
        self.assertAlmostEqual(risk["amount_rub"], 68_880, delta=5)
        self.assertAlmostEqual(risk["deviation_pp"], 0.48, delta=0.01)

    def test_bt3_reported_in_text_block(self):
        result = self._run(0.4)
        report = gas.build_report_block(
            as_of=result["as_of"], nav=result["nav_excl_iis"],
            class_plan_rub=result["class_plan_rub"], class_fact_rub=result["class_fact_rub"],
            classification=result["_classification_raw"], sizing=result["_sizing_raw"], quotes=None,
        )
        self.assertIn("Риск разворота", report)
        self.assertIn("SBERP", report)
        self.assertIn("предупреждение, не блокировка", report.lower())

    def test_bt4_monotonic_buys_never_flagged_at_any_hysteresis(self):
        """MBNK/X5/LSNGP растут по циклам монотонно (S5/B-T4 в задании — самая вероятная
        ошибка: перепутанный знак помечает разворотом продолжение той же покупки).
        Проверяем на боевом сценарии («сегодня» = C3: --open X5,MBNK,LSNGP --trim
        SBERP=8.0) при гистерезисе, близком к нулю, — только SBERP (реальный трим) может
        попасть в reversal_risk, MBNK/X5/LSNGP — никогда."""
        result = gas.run_sizing(
            trim_fix_snapshot(), trim_fix_gate_inputs(), trim_fix_conditions(),
            "X5,MBNK,LSNGP", None, None, 0.0, None, [], "SBERP=8.0", None, B_CYCLES, 0.0001,
        )
        flagged = {r["ticker"] for r in result["reversal_risk"]}
        self.assertNotIn("MBNK", flagged)
        self.assertNotIn("X5", flagged)
        self.assertNotIn("LSNGP", flagged)

    def test_bt4_direct_unit_check_via_compute_reversal_risk(self):
        """То же самое, но напрямую через compute_reversal_risk/compute_cycle_targets,
        без похода через run_sizing — изолирует B2 от классификации задачи A."""
        holdings = gas.active_stock_holdings(trim_fix_snapshot())
        ranges, total_book = gas.compute_cycle_targets(holdings, B_CYCLES)
        current_by_ticker = {h["ticker"]: h["value_rub"] for h in holdings}
        sized_items = []
        # «Сегодня» = C3, а его состав — SBERP + MBNK + X5 + LSNGP. SBERP включён намеренно:
        # состояние сопоставляется со списком по ПОЛНОМУ составу подвижных бумаг, и без него
        # сегодняшнее состояние в списке не нашлось бы (правка ревью 27.08.2026 — фильтр
        # будущих состояний перешёл с надмножества состава на порядок в списке).
        for ticker in ("SBERP", "MBNK", "X5", "LSNGP"):
            target = ranges[ticker]["target_by_cycle"]["C3"]
            current = current_by_ticker[ticker]
            sized_items.append({
                "ticker": ticker, "current_rub": current, "target_rub": target,
                "direction": "buy" if target > current else ("trim" if target < current else "hold"),
            })
        risk = gas.compute_reversal_risk(sized_items, B_CYCLES, ranges, total_book, hysteresis_pp=0.0001)
        flagged = {r["ticker"] for r in risk}
        self.assertNotIn("MBNK", flagged)
        self.assertNotIn("X5", flagged)
        self.assertNotIn("LSNGP", flagged)
        # SBERP флагуется законно и это ожидаемо: срез сегодня до C3-цели 1 165 038 ₽, а в C5
        # цель поднимается до 1 199 898 ₽ — разворот на 34 860 ₽ (0,24 пп). При штатном
        # гистерезисе 1,0 пп он молчит (B-T2), при 0,3 обязан сработать. Прежняя редакция
        # фильтра прятала и его тоже — ассерт `risk == []` был зелёным по неверной причине.
        sberp = next((r for r in risk if r["ticker"] == "SBERP"), None)
        self.assertIsNotNone(sberp, "реальный разворот SBERP не должен теряться")
        self.assertEqual(sberp["cycle"], "C5")
        self.assertAlmostEqual(sberp["amount_rub"], 34_860, delta=6)


class TestB3ActedDirectionalGuard(unittest.TestCase):
    """B-T5, переписан под §10.3 (правило НАПРАВЛЕННОЕ — запрещён разворот, не движение).
    §8.4 записан под отменённую редакцию §8.2 B3 и не воспроизводится буквально."""

    def test_acted_trim_plus_arithmetic_buy_is_suppressed(self):
        """--acted SBERP=trim + арифметика предписывает ДОКУПКУ (в F ничего нет — база = план класса,
        S3-сценарий задачи A) → подавлено: SBERP уходит в dormant, warning с причиной, база пересчитана без него.
        С непрерывной базой (§10.6) живая фикстура trim_fix без гейтов разворота больше не даёт — синтетика."""
        holdings = [mk_stock("SBERP", 300_000), mk_stock("A", 1_200_000)]
        per = {"SBERP": mk_ie_row(planned=18.0, real=20.0), "A": mk_ie_row(planned=70.0, real=80.0)}
        snap = mk_snapshot(holdings, per, class_plan_rub=3_000_000, class_fact_rub=1_500_000, nav=15_000_000)
        result = gas.run_sizing(snap, None, None, "A", None, None, 0.0, None, [], "SBERP=18", "SBERP=trim")
        self.assertEqual(result["classification"]["rebalancing"], [])
        dormant_tickers = {x["ticker"] for x in result["classification"]["dormant"]}
        self.assertIn("SBERP", dormant_tickers)
        self.assertIn("acted_reversal_suppressed:SBERP", result["warnings"])
        self.assertEqual(result["acted_reversal_iterations"], 1)

        report = gas.build_report_block(
            as_of=result["as_of"], nav=result["nav_excl_iis"],
            class_plan_rub=result["class_plan_rub"], class_fact_rub=result["class_fact_rub"],
            classification=result["_classification_raw"], sizing=result["_sizing_raw"], quotes=None,
        )
        self.assertIn("неразворота", report.lower())
        self.assertIn("SBERP", report)

    def test_acted_trim_plus_arithmetic_further_trim_is_allowed(self):
        """--acted SBERP=trim + арифметика предписывает ДАЛЬНЕЙШИЙ СРЕЗ (fixed_point,
        с решениями/условиями) → разрешено, ничего не подавляется."""
        result = gas.run_sizing(
            trim_fix_snapshot(), trim_fix_gate_inputs(), trim_fix_conditions(),
            "X5,MBNK,LSNGP", None, None, 0.0, None, [], "SBERP=8.0", "SBERP=trim",
        )
        sberp = next(x for x in result["classification"]["rebalancing"] if x["ticker"] == "SBERP")
        self.assertEqual(sberp["direction"], "trim")
        self.assertAlmostEqual(sberp["buy_rub"], -60_588, delta=6)
        self.assertNotIn("acted_reversal_suppressed:SBERP", result["warnings"])
        self.assertEqual(result["acted_reversal_iterations"], 0)

    def test_acted_buy_plus_arithmetic_buy_is_allowed(self):
        """--acted MBNK=buy + арифметика предписывает докупку → разрешено."""
        result = gas.run_sizing(
            trim_fix_snapshot(), trim_fix_gate_inputs(), trim_fix_conditions(),
            "X5,MBNK,LSNGP", None, None, 0.0, None, [], "SBERP=8.0", "MBNK=buy",
        )
        mbnk = next(x for x in result["classification"]["open"] if x["ticker"] == "MBNK")
        self.assertEqual(mbnk["direction"], "buy")
        self.assertNotIn("acted_reversal_suppressed:MBNK", result["warnings"])

    def test_selling_overrides_acted_full_exit_always_proceeds(self):
        """--acted SBERP=trim + --selling SBERP → полный выход исполняется, признак
        --acted игнорируется (§10.3: «срочная продажа проходит всегда»)."""
        result = gas.run_sizing(
            trim_fix_snapshot(), trim_fix_gate_inputs(), trim_fix_conditions(),
            "X5,MBNK,LSNGP", "SBERP", None, 0.0, None, [], None, "SBERP=trim",
        )
        selling_tickers = {x["ticker"] for x in result["classification"]["selling"]}
        self.assertIn("SBERP", selling_tickers)
        self.assertAlmostEqual(result["base_rub"], 13_223_853, delta=6)  # как в 5.1 (полный выход)
        self.assertNotIn("acted_reversal_suppressed:SBERP", result["warnings"])
        self.assertEqual(result["acted_reversal_iterations"], 0)

    def test_bare_ticker_without_direction_is_a_clean_error(self):
        """Голый '--acted SBERP' без направления — понятная ошибка, exit 2 без traceback,
        не молчаливое игнорирование."""
        with self.assertRaises(gas.GateAwareSizingError):
            gas.run_sizing(
                trim_fix_snapshot(), trim_fix_gate_inputs(), trim_fix_conditions(),
                None, None, None, 0.0, None, [], None, "SBERP",
            )

    def test_invalid_direction_is_a_clean_error(self):
        with self.assertRaises(gas.GateAwareSizingError):
            gas.run_sizing(
                trim_fix_snapshot(), trim_fix_gate_inputs(), trim_fix_conditions(),
                None, None, None, 0.0, None, [], None, "SBERP=sell",
            )

    def test_cli_bare_acted_exit_2_no_traceback(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(trim_fix_snapshot(), f)
            path = f.name
        try:
            proc = subprocess.run(
                [PY, SCRIPT_PATH, "--snapshot", path, "--acted", "SBERP"],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertNotIn("Traceback", proc.stderr)
        finally:
            os.unlink(path)


class TestB3ActedIterationConvergence(unittest.TestCase):
    """Сходимость итерации правила неразворота: вход, где подавление одного тикера
    (C) меняет базу настолько, что арифметика по второму тикеру (D) тоже разворачивается
    только ПОСЛЕ первого подавления — то есть требуется минимум 2 прохода. Итог должен
    сойтись, счётчик не должен упереться в предохранитель, предупреждения о недостижении
    неподвижной точки быть не должно.

    Пересчёт 28.10 (правило «на плане» в ручном режиме): BLK 1 500 000 ₽ при плановой доле 20% и
    книге 2 505 000 ₽ (20% × книга = 501 000 ₽) перевешен и ушёл бы в S_eff = 0,1 + 0,1 + 0,2 = 0,4 из F;
    после подавления D (F = DORM 600 000 + D 255 000 = 855 000 ₽) база = 855 000 / (1 − 0,3) =
    1 221 429 ₽, цель C = 122 142 ₽ < текущих 150 000 ₽ — C срез, как заявлено, разворота нет и
    каскад кончается за ОДИН проход. Двухпроходный каскад здесь возможен только если замороженная
    бумага не уходит «на план»; фикстура подправлена (BLK без плановой доли: planned=None, ie=20 —
    рубли в F), числа прежние (2 прохода, база 2 505 000 ₽). Новое число закреплено в
    TestFrozenOnPlanManualDefault.test_cascade_original_fixture_one_pass."""

    def _snapshot(self):
        holdings = [
            mk_stock("BLK", 1_500_000), mk_stock("DORM", 600_000),
            mk_stock("C", 150_000), mk_stock("D", 255_000),
        ]
        per_ticker = {
            "BLK": mk_ie_row(planned=None, ie=20.0, real=5.0),
            "DORM": mk_ie_row(planned=10.0, real=10.0),
            "C": mk_ie_row(planned=10.0, real=6.0),
            "D": mk_ie_row(planned=10.0, real=10.0),
        }
        return mk_snapshot(holdings, per_ticker, class_plan_rub=6_000_000, class_fact_rub=2_505_000, nav=15_000_000)

    def test_cascading_suppression_converges_in_two_passes(self):
        gate_inputs = mk_gate_inputs({"BLK": "review_needed"})
        result = gas.run_sizing(
            self._snapshot(), gate_inputs, None, None, None, None, 0.0, None, [],
            "C=10,D=10", "C=trim,D=buy",
        )
        self.assertEqual(result["classification"]["rebalancing"], [])
        self.assertEqual(result["classification"]["open"], [])
        dormant_tickers = {x["ticker"] for x in result["classification"]["dormant"]}
        self.assertIn("C", dormant_tickers)
        self.assertIn("D", dormant_tickers)
        self.assertEqual(result["acted_reversal_iterations"], 2)
        self.assertIn("acted_reversal_suppressed:C", result["warnings"])
        self.assertIn("acted_reversal_suppressed:D", result["warnings"])
        self.assertFalse(
            any(w.startswith("acted_reversal_iteration_limit_exceeded:") for w in result["warnings"])
        )
        # F после подавления обоих = вся книга (S=0) — ничего не размывается.
        self.assertAlmostEqual(result["base_rub"], 2_505_000.0, delta=5)

    def test_apply_acted_guard_direct_iteration_count(self):
        """То же самое напрямую через apply_acted_guard — изолирует правило неразворота
        от остальной оркестрации run_sizing."""
        classification = {
            "open": [], "blocked": [{"ticker": "BLK", "current_rub": 1_500_000.0, "reason": "gate:review_needed", "unblock_by": "бессрочно"}],
            "dormant": [{"ticker": "DORM", "current_rub": 600_000.0}],
            "selling": [],
            "rebalancing": [
                {"ticker": "C", "weight_pct": 10.0, "weight_source": "override", "current_rub": 150_000.0},
                {"ticker": "D", "weight_pct": 10.0, "weight_source": "override", "current_rub": 255_000.0},
            ],
        }
        final_classification, sizing, warnings, iterations = gas.apply_acted_guard(
            classification, {"C": "trim", "D": "buy"}, class_plan_rub=6_000_000.0, extra_cash_from_sales=0.0,
        )
        self.assertEqual(iterations, 2)
        self.assertEqual(final_classification["rebalancing"], [])
        self.assertEqual(
            {x["ticker"] for x in final_classification["dormant"]}, {"DORM", "C", "D"},
        )
        self.assertEqual(
            sorted(warnings), ["acted_reversal_suppressed:C", "acted_reversal_suppressed:D"],
        )


class TestRecentTradeHint(unittest.TestCase):
    """«Полезное сверх задания» (§10.4) — подсказка по recent_direction, НЕ решение:
    признак --acted никогда не выставляется автоматически. На старых снапшотах (без
    группы recent_*) деградирует молча."""

    def test_old_snapshot_without_recent_group_degrades_silently(self):
        result = gas.run_sizing(
            trim_fix_snapshot(), trim_fix_gate_inputs(), trim_fix_conditions(),
            "X5,MBNK,LSNGP", None, None, 0.0, None, [], "SBERP=8.0",
        )
        self.assertEqual(result["recent_trade_hints"], [])
        self.assertFalse(any(w.startswith("recent_trade_hint:") for w in result["warnings"]))

    def test_recent_direction_without_acted_produces_hint(self):
        snap = trim_fix_snapshot()
        snap["per_instrument_xirr"] = {
            "MBNK": {"recent_direction": "buy", "recent_last_trade_date": "2026-08-19"},
        }
        result = gas.run_sizing(
            snap, trim_fix_gate_inputs(), trim_fix_conditions(),
            "X5,MBNK,LSNGP", None, None, 0.0, None, [], "SBERP=8.0",
        )
        self.assertEqual(len(result["recent_trade_hints"]), 1)
        hint = result["recent_trade_hints"][0]
        self.assertEqual(hint["ticker"], "MBNK")
        self.assertEqual(hint["direction"], "buy")
        self.assertIn("recent_trade_hint:MBNK", result["warnings"])

        report = gas.build_report_block(
            as_of=result["as_of"], nav=result["nav_excl_iis"],
            class_plan_rub=result["class_plan_rub"], class_fact_rub=result["class_fact_rub"],
            classification=result["_classification_raw"], sizing=result["_sizing_raw"], quotes=None,
        )
        self.assertIn("--acted MBNK=buy", report)

    def test_recent_direction_with_acted_passed_suppresses_hint(self):
        """Если --acted по тикеру УЖЕ передан — подсказка избыточна, не выводится."""
        snap = trim_fix_snapshot()
        snap["per_instrument_xirr"] = {
            "MBNK": {"recent_direction": "buy", "recent_last_trade_date": "2026-08-19"},
        }
        result = gas.run_sizing(
            snap, trim_fix_gate_inputs(), trim_fix_conditions(),
            "X5,MBNK,LSNGP", None, None, 0.0, None, [], "SBERP=8.0", "MBNK=buy",
        )
        self.assertEqual(result["recent_trade_hints"], [])

    def test_recent_direction_absent_or_null_is_no_hint(self):
        snap = trim_fix_snapshot()
        snap["per_instrument_xirr"] = {"MBNK": {"xirr": 0.1}}  # без recent_* вовсе
        result = gas.run_sizing(
            snap, trim_fix_gate_inputs(), trim_fix_conditions(),
            "X5,MBNK,LSNGP", None, None, 0.0, None, [], "SBERP=8.0",
        )
        self.assertEqual(result["recent_trade_hints"], [])


# ───────────── 16. Лимиты концентрации — проводка (задача 1, §9/§11 spec-gate-aware-sizing-trim-fix.md) ─────────────
#
# concentration_limits.compute_concentration подключён к classify_stocks/run_sizing.
# Синтетический конфиг с ЛИМИТОМ НИЖЕ факта — на живом снапшоте (portfolio-2026-08-21.json,
# SBER+SBERP 19,40% при исключении 20%) нарушений нет ни в одной из 20 групп (проверено
# вручную), поэтому сценарий блокировки проверяется здесь конфигом с 15% по умолчанию БЕЗ
# исключения (тот же C-T3 concentration_limits.py) — SBER+SBERP = 19,40% > 15% нарушает.

def mk_breach_limits_config():
    return {
        "default_issuer_limit_pct": 15.0,
        "sector_limit_pct": 35.0,
        "issuer_groups": {"SBER": ["SBER", "SBERP"]},
        "issuer_exceptions": {},
    }


class TestConcentrationWiring(unittest.TestCase):
    """Задача 1 проводки — Open заблокирован лимитом концентрации сильнее ручного
    --open; Rebalancing (срез) этому правилу не подчиняется — лечит нарушение."""

    def test_open_request_for_breached_group_moves_to_blocked(self):
        result = gas.run_sizing(
            snapshot=trim_fix_snapshot(), gate_inputs=trim_fix_gate_inputs(), conditions=trim_fix_conditions(),
            open_arg="SBERP,X5,MBNK,LSNGP", selling_arg=None, blocked_arg=None,
            extra_cash_from_sales=0.0, quotes=None, yaml_warnings=[],
            limits_config=mk_breach_limits_config(), concentration_today="2026-08-26",
        )
        self.assertNotIn("SBERP", {x["ticker"] for x in result["classification"]["open"]})
        blocked_sberp = next(x for x in result["classification"]["blocked"] if x["ticker"] == "SBERP")
        self.assertEqual(blocked_sberp["reason"], "concentration_breach:SBER")
        self.assertEqual(blocked_sberp["unblock_by"], "после среза до лимита концентрации")
        self.assertIn("open_override_blocked_by_concentration:SBERP", result["warnings"])
        self.assertIn("concentration_breach:SBER", result["warnings"])

        conc = result["concentration"]
        self.assertIsNotNone(conc)
        sber_row = conc["by_issuer"]["SBER"]
        self.assertTrue(sber_row["breach"])
        self.assertAlmostEqual(sber_row["share_pct"], 19.40, delta=0.1)

        report = gas.build_report_block(
            as_of=result["as_of"], nav=result["nav_excl_iis"],
            class_plan_rub=result["class_plan_rub"], class_fact_rub=result["class_fact_rub"],
            classification=result["_classification_raw"], sizing=result["_sizing_raw"], quotes=None,
        )
        self.assertIn("SBERP", report)
        self.assertIn("лимитом концентрации", report)
        self.assertIn("SBER", report)  # сводка нарушений

    def test_trim_request_for_breached_group_not_blocked_remains_rebalancing(self):
        """Срез (--trim) той же нарушающей лимит группы НЕ блокируется — это и есть
        лечение нарушения (§9.2)."""
        result = gas.run_sizing(
            snapshot=trim_fix_snapshot(), gate_inputs=trim_fix_gate_inputs(), conditions=trim_fix_conditions(),
            open_arg="X5,MBNK,LSNGP", selling_arg=None, blocked_arg=None,
            extra_cash_from_sales=0.0, quotes=None, yaml_warnings=[],
            trim_arg="SBERP=8.0",
            limits_config=mk_breach_limits_config(), concentration_today="2026-08-26",
        )
        rebalancing_tickers = {x["ticker"] for x in result["classification"]["rebalancing"]}
        self.assertIn("SBERP", rebalancing_tickers)
        self.assertNotIn("SBERP", {x["ticker"] for x in result["classification"]["blocked"]})
        sberp = next(x for x in result["classification"]["rebalancing"] if x["ticker"] == "SBERP")
        self.assertEqual(sberp["direction"], "trim")
        self.assertAlmostEqual(sberp["buy_rub"], -60_588, delta=6)

    def test_rebalancing_flip_to_buy_is_capped_not_executed(self):
        """§9.2 «важное следствие» — срез, требуемый лимитом, не может развернуться в
        докупку даже там, где обычный S3-флип разрешил бы её (в F ничего нет — база = план
        класса, TestTrimS3DirectionFlip). Капается на current_rub, не на плановую цель.
        Фикстура §10.7 (11.11): у A — исключение лимита (90%), иначе A заблокирован лимитом и стоит в F
        своими рублями (раньше его выводило из F правило «на плане», отменённое §10.7) — тогда база
        1 463 415 ₽ и SBERP режется обычным срезом, флипа нет."""
        holdings = [mk_stock("SBERP", 300_000), mk_stock("A", 1_200_000)]
        per = {"SBERP": mk_ie_row(planned=18.0, real=20.0), "A": mk_ie_row(planned=70.0, real=80.0)}
        snap = mk_snapshot(holdings, per, class_plan_rub=3_000_000, class_fact_rub=1_500_000, nav=15_000_000)
        snap["as_of_date"] = "2026-08-26"
        cfg = mk_breach_limits_config()
        cfg["issuer_exceptions"] = {"a_exc": {"issuer": "A", "limit_pct": 90.0, "basis": "тест",
                                              "review_date": "2027-01-01"}}
        result = gas.run_sizing(
            snapshot=snap, gate_inputs=None, conditions=None,
            open_arg="A", selling_arg=None, blocked_arg=None,
            extra_cash_from_sales=0.0, quotes=None, yaml_warnings=[],
            trim_arg="SBERP=18",
            limits_config=cfg, concentration_today="2026-08-26",
        )
        self.assertEqual(result["base_source"], "t_full_no_gates")
        sberp = result["classification"]["rebalancing"][0]
        self.assertEqual(sberp["ticker"], "SBERP")
        self.assertAlmostEqual(sberp["target_rub"], 300_000, delta=6)
        self.assertAlmostEqual(sberp["buy_rub"], 0.0, delta=6)
        self.assertEqual(sberp["direction"], "hold")
        self.assertNotIn("trim_direction_flipped:SBERP", result["warnings"])
        self.assertIn("concentration_blocks_rebalancing_buy:SBERP", result["warnings"])

        report = gas.build_report_block(
            as_of=result["as_of"], nav=result["nav_excl_iis"],
            class_plan_rub=result["class_plan_rub"], class_fact_rub=result["class_fact_rub"],
            classification=result["_classification_raw"], sizing=result["_sizing_raw"], quotes=None,
        )
        self.assertIn("не может", report)
        self.assertIn("SBERP", report)

    def test_sector_flag_forwarded_and_disabled_on_missing_sector_field(self):
        """--sector доходит до compute_concentration; на этой фикстуре (mk_stock без
        поля sector) секторный расчёт гейтится 100%-й долей sector=null — рабочий гейт,
        не падение проводки."""
        result = gas.run_sizing(
            snapshot=trim_fix_snapshot(), gate_inputs=trim_fix_gate_inputs(), conditions=trim_fix_conditions(),
            open_arg="X5,MBNK,LSNGP", selling_arg=None, blocked_arg=None,
            extra_cash_from_sales=0.0, quotes=None, yaml_warnings=[],
            limits_config={
                "default_issuer_limit_pct": 15.0, "sector_limit_pct": 35.0,
                "issuer_groups": {}, "issuer_exceptions": {},
            },
            sector_enabled=True, concentration_today="2026-08-26",
        )
        by_sector = result["concentration"]["by_sector"]
        self.assertEqual(by_sector["status"], "disabled")
        self.assertIn("sector_limit_disabled", result["warnings"])

    def test_no_limits_config_means_no_concentration_effect_at_all(self):
        """Базовое поведение (limits_config=None, дефолт) — концентрация не считается
        вообще, ни одного нового warning'а/ключа не добавляется поверх старого поведения."""
        result = gas.run_sizing(
            snapshot=trim_fix_snapshot(), gate_inputs=trim_fix_gate_inputs(), conditions=trim_fix_conditions(),
            open_arg="X5,MBNK,LSNGP", selling_arg=None, blocked_arg=None,
            extra_cash_from_sales=0.0, quotes=None, yaml_warnings=[],
            trim_arg="SBERP=8.0",
        )
        self.assertIsNone(result["concentration"])
        self.assertFalse(any("concentration" in w for w in result["warnings"]))
        report = gas.build_report_block(
            as_of=result["as_of"], nav=result["nav_excl_iis"],
            class_plan_rub=result["class_plan_rub"], class_fact_rub=result["class_fact_rub"],
            classification=result["_classification_raw"], sizing=result["_sizing_raw"], quotes=None,
        )
        self.assertNotIn("концентрац", report.lower())

    def test_report_shows_clean_status_when_no_breach(self):
        """Конфиг загружен успешно и нарушений нет — отчёт явно говорит, что проверка
        выполнена и чиста, а не молчит (проверка реально шла, а не была пропущена)."""
        result = gas.run_sizing(
            snapshot=trim_fix_snapshot(), gate_inputs=trim_fix_gate_inputs(), conditions=trim_fix_conditions(),
            open_arg="X5,MBNK,LSNGP", selling_arg=None, blocked_arg=None,
            extra_cash_from_sales=0.0, quotes=None, yaml_warnings=[],
            limits_config={
                "default_issuer_limit_pct": 25.0, "sector_limit_pct": 35.0,
                "issuer_groups": {"SBER": ["SBER", "SBERP"]}, "issuer_exceptions": {},
            },
            concentration_today="2026-08-26",
        )
        report = gas.build_report_block(
            as_of=result["as_of"], nav=result["nav_excl_iis"],
            class_plan_rub=result["class_plan_rub"], class_fact_rub=result["class_fact_rub"],
            classification=result["_classification_raw"], sizing=result["_sizing_raw"], quotes=None,
        )
        self.assertIn("нарушений нет", report)


class TestConcentrationConfigDegradation(unittest.TestCase):
    """Отказ загрузки конфига лимитов не должен ронять весь сайзинг — деградация с
    warning'ом, exit 0 (не 2). Решение и обоснование — отчёт по правке волны 3."""

    def test_cli_missing_concentration_limits_file_degrades_not_exit2(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(trim_fix_snapshot(), f)
            path = f.name
        try:
            proc = subprocess.run(
                [PY, SCRIPT_PATH, "--snapshot", path,
                 "--concentration-limits", "/tmp/does-not-exist-concentration.yaml",
                 "--json"],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertIsNone(payload["concentration"])
            self.assertTrue(
                any(w.startswith("concentration_check_unavailable:") for w in payload["warnings"])
            )
        finally:
            os.unlink(path)

    def test_cli_concentration_limits_and_sector_flags_end_to_end(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML недоступен")
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(trim_fix_snapshot(), f)
            snap_path = f.name
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(
                "default_issuer_limit_pct: 15.0\n"
                "sector_limit_pct: 35.0\n"
                "issuer_groups:\n  SBER: [SBER, SBERP]\n"
                "issuer_exceptions: {}\n"
            )
            limits_path = f.name
        try:
            proc = subprocess.run(
                [PY, SCRIPT_PATH, "--snapshot", snap_path,
                 "--open", "X5,MBNK,LSNGP",
                 "--concentration-limits", limits_path, "--sector", "--json"],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            sber = payload["concentration"]["by_issuer"]["SBER"]
            self.assertTrue(sber["breach"])
            self.assertEqual(payload["concentration"]["by_sector"]["status"], "disabled")
        finally:
            os.unlink(snap_path)
            os.unlink(limits_path)


# ───────────── 17. Лимиты концентрации × правило неразворота (задача 2, §9.2) ─────────────

class TestConcentrationActedPriority(unittest.TestCase):
    """§9.2 spec-gate-aware-sizing-trim-fix.md — нарушение лимита концентрации СТАРШЕ
    правила неразворота: --acted TICKER=buy не подавляет срез, которого требует лимит."""

    def _run(self, limits_config):
        return gas.run_sizing(
            snapshot=trim_fix_snapshot(), gate_inputs=trim_fix_gate_inputs(), conditions=trim_fix_conditions(),
            open_arg="X5,MBNK,LSNGP", selling_arg=None, blocked_arg=None,
            extra_cash_from_sales=0.0, quotes=None, yaml_warnings=[],
            trim_arg="SBERP=8.0", acted_arg="SBERP=buy",
            limits_config=limits_config, concentration_today="2026-08-26",
        )

    def test_baseline_without_concentration_acted_buy_suppresses_trim(self):
        """Контроль: без нарушения лимита обычное правило неразворота подавляет срез,
        конфликтующий с --acted SBERP=buy (переводит в dormant) — это устоявшееся
        поведение §10.3, проверяется здесь как базовая линия для контраста."""
        result = self._run(limits_config=None)
        self.assertEqual(result["classification"]["rebalancing"], [])
        dormant_tickers = {x["ticker"] for x in result["classification"]["dormant"]}
        self.assertIn("SBERP", dormant_tickers)
        self.assertIn("acted_reversal_suppressed:SBERP", result["warnings"])

    def test_concentration_breach_trim_survives_acted_buy(self):
        """С конфигом, где SBER+SBERP нарушает лимит (15% без исключения), срез НЕ
        подавляется — риск-лимит старше правила неразворота."""
        result = self._run(limits_config=mk_breach_limits_config())
        rebalancing_tickers = {x["ticker"] for x in result["classification"]["rebalancing"]}
        self.assertIn("SBERP", rebalancing_tickers)
        self.assertNotIn("acted_reversal_suppressed:SBERP", result["warnings"])
        sberp = next(x for x in result["classification"]["rebalancing"] if x["ticker"] == "SBERP")
        self.assertEqual(sberp["direction"], "trim")
        self.assertAlmostEqual(sberp["buy_rub"], -60_588, delta=6)


# ─────────────────── --auto: гистерезис на докупку, условия с продажей / «держать» ───────────────────
#
# 2026-10-26: «Сейчас» предложил ≈67 тыс. ₽ мелких докупок вопреки решениям (RENI «без добора до
# МСФО 9М», NVTK в 1,1% от sell-гейта, шум 0,1–0,4 п.п.). Правила: недобор > гистерезиса;
# pending on_trigger TRIM/SELL → sell_condition; pending while_pending HOLD/TRIM/SELL (не BUY-условие)
# → condition_hold; окно not_before/valid_until; только state: pending.

def _auto_cond(cid, ticker, *, on, while_=None, state="pending", **extra):
    """Определение conditions@2 (+ состояние полем _events: fired — сработало, done — сработало и закрыто)."""
    c = {"id": cid, "version": 1, "key": ticker, "kind": "trade",
         "trigger": {"type": "date", "value": "2026-11-30"},
         "on_trigger": {"action": "set_verdict", "verdict": on, "text": "фикстура"},
         "created_at": "2026-10-01T10:00:00+03:00", "created_by": "owner"}
    if while_:
        c["while_pending"] = {"verdict": while_}
    c.update(extra)
    ev = []
    if state in ("fired", "done"):
        ev.append({"condition_id": cid, "event": "fired", "at": "2026-10-20T10:00:00+03:00", "by": "notifier"})
    if state == "done":
        ev.append({"condition_id": cid, "event": "done", "at": "2026-10-21T10:00:00+03:00", "by": "owner"})
    c["_events"] = ev
    return c


def _conds(defs):
    """Вход условий движка: определения conditions@2 + состояние из _events."""
    defs = defs or []
    return {"defs": [{k: v for k, v in d.items() if k != "_events"} for d in defs],
            "state": {"schema_version": "conditions-state@1", "events": [e for d in defs for e in d.get("_events", [])]}}


def _auto_stock(ticker, value_rub):
    h = mk_stock(ticker, value_rub)
    h.update({"current_price": 100.0, "lot_size": 1})
    return h


class TestAutoStopRules(unittest.TestCase):
    AS_OF = "2026-10-26"

    def _auto(self, plan_real, conds=None, hysteresis=1.0):
        """plan_real: {ticker: (plan, real)}; книга 3 000 000 ₽, доли реальные = стоимость."""
        holdings = [_auto_stock(t, real / 100 * 3_000_000) for t, (plan, real) in plan_real.items()]
        per = {t: mk_ie_row(planned=plan, real=real, user_plan="BUY") for t, (plan, real) in plan_real.items()}
        snap = mk_snapshot(holdings, per, 3_600_000, 3_000_000, 15_000_000, as_of=self.AS_OF)
        res = gas.run_auto(snap, None, _conds(conds), None, hysteresis)
        return {r["ticker"]: r for r in res["rows"]}, res

    def _pair(self, **kw):  # бумага с недобором 2 п.п. (докупается по умолчанию) + «остальное»
        d = {"TT": (10.0, 8.0), "REST": (90.0, 92.0)}
        d.update(kw)
        return d

    def test_buy_when_gap_above_hysteresis(self):
        rows, res = self._auto(self._pair())
        self.assertEqual(rows["TT"]["direction"], "buy")
        self.assertGreater(res["buy_rub"], 0)

    def test_gap_inside_hysteresis_no_buy_with_reason(self):
        rows, res = self._auto({"TT": (10.0, 9.5), "REST": (90.0, 90.5)})
        self.assertIsNone(rows["TT"]["direction"])
        self.assertEqual(rows["TT"]["category"], "dormant")
        self.assertEqual(rows["TT"]["reason"], "below_hysteresis:0.50pp")
        self.assertEqual(res["buy_rub"], 0)

    def test_gap_exactly_at_hysteresis_no_buy(self):
        rows, _ = self._auto({"TT": (10.0, 9.0), "REST": (90.0, 91.0)})
        self.assertIsNone(rows["TT"]["direction"])

    def test_hysteresis_param_lowers_threshold(self):
        rows, _ = self._auto({"TT": (10.0, 9.5), "REST": (90.0, 90.5)}, hysteresis=0.3)
        self.assertEqual(rows["TT"]["direction"], "buy")

    def test_sell_condition_blocks_buy(self):
        rows, res = self._auto(self._pair(), [_auto_cond("tt-sell", "TT", on="TRIM", while_="HOLD")])
        self.assertEqual(rows["TT"]["category"], "blocked")
        self.assertIsNone(rows["TT"]["direction"])
        self.assertEqual(rows["TT"]["reason"], "sell_condition:tt-sell")
        self.assertEqual(res["buy_rub"], 0)

    def test_sell_verdict_blocks_buy_too(self):
        rows, _ = self._auto(self._pair(), [_auto_cond("tt-sell", "TT", on="SELL")])
        self.assertEqual(rows["TT"]["reason"], "sell_condition:tt-sell")

    def test_hold_condition_blocks_buy(self):
        rows, _ = self._auto(self._pair(), [_auto_cond("tt-hold", "TT", on="HOLD", while_="HOLD")])
        self.assertEqual(rows["TT"]["category"], "blocked")
        self.assertEqual(rows["TT"]["reason"], "condition_hold:tt-hold")
        self.assertEqual(rows["TT"]["unblock_by"], "2026-11-30")

    def test_sell_condition_older_than_hold(self):
        rows, _ = self._auto(self._pair(), [_auto_cond("h", "TT", on="HOLD", while_="HOLD"),
                                            _auto_cond("s", "TT", on="TRIM", while_="HOLD")])
        self.assertEqual(rows["TT"]["reason"], "sell_condition:s")

    def test_buy_condition_stays_pending_buy_condition(self):
        # BUY-условие (LSNGP) — прежняя причина pending_buy_condition, не condition_hold
        rows, _ = self._auto(self._pair(), [_auto_cond("tt-buy", "TT", on="BUY", while_="HOLD")])
        self.assertEqual(rows["TT"]["reason"], "pending_buy_condition")

    def test_hold_condition_without_while_pending_does_not_block(self):
        rows, _ = self._auto(self._pair(), [_auto_cond("x", "TT", on="HOLD")])
        self.assertEqual(rows["TT"]["direction"], "buy")

    def test_fired_condition_waits_owner_blocks(self):
        # строка модуля (а): сработавшее без отметки — «ждёт владельца», докупку держит
        rows, _ = self._auto(self._pair(), [_auto_cond("x", "TT", on="TRIM", while_="HOLD", state="fired")])
        self.assertEqual((rows["TT"]["reason"], rows["TT"]["unblock_by"]), ("sell_condition:x", "после отметки владельца"))

    def test_fired_and_done_condition_does_not_block(self):
        rows, _ = self._auto(self._pair(), [_auto_cond("x", "TT", on="TRIM", while_="HOLD", state="done")])
        self.assertEqual(rows["TT"]["direction"], "buy")

    def test_other_ticker_condition_does_not_block(self):
        rows, _ = self._auto(self._pair(), [_auto_cond("x", "REST", on="TRIM", while_="HOLD")])
        self.assertEqual(rows["TT"]["direction"], "buy")

    def test_window_expired_condition_does_not_block(self):
        rows, _ = self._auto(self._pair(), [_auto_cond("x", "TT", on="TRIM", while_="HOLD", valid_until="2026-10-25")])
        self.assertEqual(rows["TT"]["direction"], "buy")

    def test_window_last_day_still_blocks(self):
        rows, _ = self._auto(self._pair(), [_auto_cond("x", "TT", on="TRIM", while_="HOLD", valid_until="2026-10-26")])
        self.assertEqual(rows["TT"]["reason"], "sell_condition:x")

    def test_window_not_started_does_not_block(self):
        rows, _ = self._auto(self._pair(), [_auto_cond("x", "TT", on="HOLD", while_="HOLD", not_before="2026-10-27")])
        self.assertEqual(rows["TT"]["direction"], "buy")

    def test_window_dates_stay_strings_from_yaml(self):
        # conditions@2 читается load_conditions_inputs (conditions_merge.load_yaml): даты без кавычек — строки
        d = tempfile.mkdtemp(prefix="gas-cond-")
        args = write_gate_cli_inputs(d, None, _conds([_auto_cond("x", "TT", on="TRIM", while_="HOLD",
                                                                  not_before="2026-10-01", valid_until="2026-11-01")]))
        with open(args[args.index("--conditions") + 1], encoding="utf-8") as f:
            text = f.read().replace("'2026-10-01'", "2026-10-01").replace("'2026-11-01'", "2026-11-01")
        with open(args[args.index("--conditions") + 1], "w", encoding="utf-8") as f:
            f.write(text)
        cond, warn = gas.load_conditions_inputs(args[args.index("--conditions") + 1], args[args.index("--conditions-state") + 1])
        self.assertEqual((cond["defs"][0]["not_before"], cond["defs"][0]["valid_until"], warn), ("2026-10-01", "2026-11-01", []))
        holdings = [_auto_stock("TT", 240_000), _auto_stock("REST", 2_760_000)]
        per = {"TT": mk_ie_row(planned=10.0, real=8.0, user_plan="BUY"), "REST": mk_ie_row(planned=90.0, real=92.0, user_plan="BUY")}
        res = gas.run_auto(mk_snapshot(holdings, per, 3_600_000, 3_000_000, 15_000_000, as_of=self.AS_OF), None, cond, None)
        self.assertEqual(next(r for r in res["rows"] if r["ticker"] == "TT")["reason"], "sell_condition:x")

    def test_conditions_do_not_touch_trim(self):
        # срез перевеса BALANCE условием не закрывается
        holdings = [_auto_stock("TT", 390_000), _auto_stock("REST", 2_610_000)]
        per = {"TT": mk_ie_row(planned=10.0, real=13.0, user_plan="BALANCE"),
               "REST": mk_ie_row(planned=80.0, real=87.0, user_plan="KEEP")}
        snap = mk_snapshot(holdings, per, 3_600_000, 3_000_000, 15_000_000, as_of=self.AS_OF)
        res = gas.run_auto(snap, None, _conds([_auto_cond("x", "TT", on="TRIM", while_="HOLD")]), None)
        tt = next(r for r in res["rows"] if r["ticker"] == "TT")
        self.assertEqual(tt["direction"], "trim")

    def test_manual_mode_not_affected(self):
        # ручной режим: --open TT докупает вопреки pending-условию с продажей
        holdings, per = [mk_stock("TT", 240_000), mk_stock("REST", 2_760_000)], {
            "TT": mk_ie_row(planned=10.0, real=8.0), "REST": mk_ie_row(planned=90.0, real=92.0)}
        snap = mk_snapshot(holdings, per, 3_600_000, 3_000_000, 15_000_000, as_of=self.AS_OF)
        res = gas.run_sizing(snap, None, _conds([_auto_cond("x", "TT", on="TRIM", while_="HOLD")]),
                             "TT", None, None, 0.0, None, [])
        self.assertIn("TT", {o["ticker"] for o in res["classification"]["open"]})


# ─────────────── Перевешенная заморозка — в F своими рублями (§10.7, 11.11) ───────────────

class TestFrozenAbovePlanInF(unittest.TestCase):
    """§10.7 (решение владельца 11.11): правило «на плане» §10.3а (28.10) отменено в пользу инварианта
    «база = книга после исполнения». Замороженная бумага выше своей плановой доли — в F своими рублями, как
    любая неторгуемая; параметра frozen_on_plan и полей frozen_at_plan/at_plan больше нет. Здесь —
    оригинальные «перевешенные» фикстуры шести калибровочных тестов, пересчитанные вручную (числа
    совпадают с эталонами до 28.10, кроме кэша: ветки «блокировок нет → план класса» больше нет, §10.6 п.2)."""

    def test_parameter_and_fields_removed(self):
        import inspect
        for fn in (gas.compute_sizing, gas.apply_acted_guard, gas.run_sizing):
            self.assertNotIn("frozen_on_plan", inspect.signature(fn).parameters, fn.__name__)
        r = self._spec7()
        self.assertNotIn("frozen_at_plan", r)

    def _spec7(self, **kw):
        holdings = [
            mk_stock("BLK", 11_357_871),
            mk_stock("RENI", 1_524_012), mk_stock("MBNK", 441_702), mk_stock("X5", 741_750),
        ]
        per_ticker = {
            "BLK": mk_ie_row(planned=20.0, real=5.0),
            "RENI": mk_ie_row(planned=11.0, real=8.0),
            "MBNK": mk_ie_row(planned=4.0, real=2.5),
            "X5": mk_ie_row(planned=5.5, real=4.0),
        }
        snap = mk_snapshot(holdings, per_ticker, class_plan_rub=17_314_827, class_fact_rub=14_065_335, nav=45_000_000)
        return gas.run_sizing(
            snapshot=snap, gate_inputs=mk_gate_inputs({"BLK": "review_needed"}, valid_until="2026-12-01"),
            conditions=None, open_arg="RENI,MBNK,X5", selling_arg=None, blocked_arg=None,
            extra_cash_from_sales=0.0, quotes=None, yaml_warnings=[], **kw,
        )

    def test_spec7_original_fixture(self):
        """§7: BLK 11 357 871 ₽ (20% плана, перевешена против книги 14 065 335 ₽) в F; S = 0,205 →
        база 11 357 871 / 0,795 = 14 286 630 ₽ (fixed_point). Цели: RENI 1 571 529, MBNK 571 464, X5 785 766;
        докупка 221 295 ₽. Книга после идеального исполнения = F + S·база = база."""
        r = self._spec7()
        self.assertEqual(r["base_source"], "fixed_point")
        self.assertAlmostEqual(r["base_rub"], 11_357_871 / 0.795, delta=5)
        targets = {o["ticker"]: o["target_rub"] for o in r["classification"]["open"]}
        self.assertAlmostEqual(targets["RENI"], 1_571_529, delta=5)
        self.assertAlmostEqual(targets["MBNK"], 571_464, delta=5)
        self.assertAlmostEqual(targets["X5"], 785_766, delta=5)
        self.assertAlmostEqual(sum(o["buy_rub"] for o in r["classification"]["open"]), 221_295, delta=3)
        self.assertAlmostEqual(11_357_871 + sum(targets.values()), r["base_rub"], delta=6)

    def test_cascade_original_fixture_two_passes(self):
        """Каскад B3 на оригинальной фикстуре (BLK планом 20%): BLK 1 500 000 ₽ в F → база 2 625 000 ₽,
        C разворачивается в докупку (подавлен), затем D — в срез (подавлен): 2 прохода, база = книга 2 505 000 ₽."""
        holdings = [mk_stock("BLK", 1_500_000), mk_stock("DORM", 600_000),
                    mk_stock("C", 150_000), mk_stock("D", 255_000)]
        per_ticker = {
            "BLK": mk_ie_row(planned=20.0, real=5.0), "DORM": mk_ie_row(planned=10.0, real=10.0),
            "C": mk_ie_row(planned=10.0, real=6.0), "D": mk_ie_row(planned=10.0, real=10.0),
        }
        snap = mk_snapshot(holdings, per_ticker, class_plan_rub=6_000_000, class_fact_rub=2_505_000, nav=15_000_000)
        r = gas.run_sizing(snap, mk_gate_inputs({"BLK": "review_needed"}), None, None, None, None,
                           0.0, None, [], "C=10,D=10", "C=trim,D=buy")
        self.assertEqual(r["acted_reversal_iterations"], 2)
        self.assertAlmostEqual(r["base_rub"], 2_505_000, delta=5)
        self.assertIn("acted_reversal_suppressed:C", r["warnings"])
        self.assertIn("acted_reversal_suppressed:D", r["warnings"])

    def _cash_snap(self, liquid):
        holdings = [mk_stock("BLK", 2_100_000), mk_stock("A", 150_000)]
        per_ticker = {"BLK": mk_ie_row(planned=15.0, real=5.0), "A": mk_ie_row(planned=10.0, real=5.0)}
        snap = mk_snapshot(holdings, per_ticker, class_plan_rub=3_000_000, class_fact_rub=2_250_000, nav=15_000_000)
        snap["cash"] = {"total_rub": 171_247.47, "liquid_rub": liquid}
        return snap

    def test_cash_buffer_original_fixture(self):
        """BLK 2 100 000 ₽ в F, база 2 100 000 / 0,9 = 2 333 334 ₽. Недобора заблокированных нет (BLK выше своих
        15% плана) → закрытый гейтами компонент 0, ожидаемый кэш = 4% × 15 000 000 = 600 000 ₽."""
        for liquid, above in ((2_700_000, True), (900_000, True), (450_000, False)):
            r = gas.run_sizing(self._cash_snap(liquid), mk_gate_inputs({"BLK": "review_needed"}), None,
                               "A=10", None, None, 0.0, None, [], None, None, None, 1.0, None, False, None, 4.0)
            cb = r["cash_buffer"]
            self.assertEqual(r["base_source"], "fixed_point")
            self.assertAlmostEqual(r["base_rub"], 2_100_000 / 0.9, delta=5)
            self.assertAlmostEqual(cb["gated_component_rub"], 0.0, delta=5)
            self.assertAlmostEqual(cb["expected_cash_rub"], 600_000, delta=5)
            self.assertEqual(cb["above_expected"], above)

    def test_shared_denominator_original_fixture(self):
        """BLK 2 100 000 ₽ в F, S = 0,2 → база 2 625 000 ₽, A и B докупаются по 112 500 ₽ до 262 500 ₽."""
        holdings = [mk_stock("BLK", 2_100_000), mk_stock("A", 150_000), mk_stock("B", 150_000)]
        per_ticker = {"BLK": mk_ie_row(planned=15.0, real=5.0),
                      "A": mk_ie_row(planned=10.0, real=5.0), "B": mk_ie_row(planned=10.0, real=5.0)}
        snap = mk_snapshot(holdings, per_ticker, class_plan_rub=3_000_000, class_fact_rub=2_400_000, nav=15_000_000)
        r = gas.run_sizing(snap, mk_gate_inputs({"BLK": "review_needed"}), None, "A=10,B=10",
                           None, None, 0.0, None, [])
        self.assertEqual(r["base_source"], "fixed_point")
        self.assertAlmostEqual(r["base_rub"], 2_625_000, delta=5)
        self.assertEqual([round(o["buy_rub"]) for o in r["classification"]["open"]], [112_500, 112_500])

    def test_report_block_has_no_on_plan_line(self):
        r = self._spec7()
        report = gas.build_report_block(
            as_of=r["as_of"], nav=r["nav_excl_iis"], class_plan_rub=r["class_plan_rub"],
            class_fact_rub=r["class_fact_rub"], classification=r["_classification_raw"],
            sizing=r["_sizing_raw"], quotes=None)
        self.assertNotIn("считаются стоящими на плане", report)

    def test_parity_manual_and_auto_same_base_on_same_classification(self):
        """Одна классификация (BLK — gate review_needed, перевешена; A — докупка) → ручной run_sizing и
        run_auto называют одну базу: BLK в F, 1 500 000 / 0,9 = 1 666 668 ₽."""
        holdings = [_auto_stock("BLK", 1_500_000), _auto_stock("A", 150_000)]
        per = {"BLK": mk_ie_row(planned=20.0, real=5.0, user_plan="KEEP"),
               "A": mk_ie_row(planned=10.0, real=5.0, user_plan="BUY")}
        snap = mk_snapshot(holdings, per, 3_000_000, 1_650_000, 15_000_000, as_of="2026-10-26")
        gr = mk_gate_inputs({"BLK": "review_needed"})
        auto = gas.run_auto(snap, gr, {"conditions": []}, None)
        manual = gas.run_sizing(snap, gr, None, "A=10", None, None, 0.0, None, [])
        self.assertNotIn("frozen_at_plan", auto)
        self.assertFalse(any("at_plan" in row for row in auto["rows"]))
        self.assertEqual(manual["base_source"], auto["base_source"])
        self.assertAlmostEqual(manual["base_rub"], auto["base_rub"], delta=0.01)
        self.assertAlmostEqual(auto["base_rub"], 1_500_000 / 0.9, delta=5)


# ─────────────────────────── read-only гарантия ───────────────────────────

class TestReadOnly(unittest.TestCase):
    """Скрипт не пишет на диск (кроме stdout) — статическая проверка исходника:
    ни одного открытия файла в текстовом/бинарном режиме записи."""

    def test_no_write_mode_file_opens_in_source(self):
        with open(SCRIPT_PATH, encoding="utf-8") as f:
            src = f.read()
        forbidden = re.findall(r"""open\([^)]*["']([wxa]b?\+?)["']""", src)
        self.assertEqual(forbidden, [], f"gate_aware_sizing.py открывает файл(ы) на запись: {forbidden}")



class TestCliReviewsFlag(unittest.TestCase):
    """--reviews <yaml обзора акций>: строки бумаг обзора идут в модуль (б) — флаг gate_review_required обзора НОВЕЕ
    решения даёт review_needed (блок докупки «после разбора бумаги»); обзор старше решения статус не меняет."""

    def _run(self, review_recorded_at, flag=True):
        import yaml
        holdings = [mk_stock("DORM", 2_700_000), mk_stock("GATE1", 300_000)]
        per_ticker = {"DORM": mk_ie_row(planned=10.0, real=10.0), "GATE1": mk_ie_row(planned=10.0, real=2.0, user_plan="BUY")}
        snap = mk_snapshot(holdings, per_ticker, 3_000_000, 3_000_000, 15_000_000)
        gi = {"decisions": [mk_decision("GATE1", "HOLD", "2026-01-05", "2026-06-01")], "reviews": {},
              "security_attrs": {"schema_version": "security-attrs@1", "by_key": {}}}
        with tempfile.TemporaryDirectory() as tmp:
            args = write_gate_cli_inputs(tmp, gi, None)
            sp, rp = os.path.join(tmp, "snap.json"), os.path.join(tmp, "weekly-review-stock-2026-01-10.yaml")
            with open(sp, "w", encoding="utf-8") as f:
                json.dump(snap, f)
            with open(rp, "w", encoding="utf-8") as f:
                yaml.safe_dump({"review_date": review_recorded_at[:10], "recorded_at": review_recorded_at,
                                "per_stock": {"GATE1": {"advisor_verdict": "HOLD", "flags": {"gate_review_required": flag}}}},
                               f, allow_unicode=True)
            proc = subprocess.run([PY, SCRIPT_PATH, "--snapshot", sp, *args, "--reviews", rp, "--today", "2026-02-01",
                                   "--json"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        payload = json.loads(proc.stdout)
        return {x["ticker"]: x for x in payload["classification"]["blocked"]}

    def test_review_newer_than_decision_gives_review_needed(self):
        blocked = self._run("2026-01-10T12:00:00+03:00")
        self.assertIn("GATE1", blocked)
        self.assertIn("gate:review_needed", blocked["GATE1"]["reason"])

    def test_review_older_than_decision_keeps_decision_status(self):
        blocked = self._run("2026-01-04T12:00:00+03:00")
        self.assertNotIn("gate:review_needed", (blocked.get("GATE1") or {}).get("reason", ""))

    def test_without_flag_no_review_needed(self):
        blocked = self._run("2026-01-10T12:00:00+03:00", flag=False)
        self.assertNotIn("gate:review_needed", (blocked.get("GATE1") or {}).get("reason", ""))

# ─────────────── Инвариант базы «Сейчас»: рубли «держать» — в F, вес — не в S (11.11) ───────────────

class TestBaseInvariantHoldInF(unittest.TestCase):
    """Бумага, которую цикл не торгует («держать»/KEEP в коридоре или без операции), входит в F своими
    рублями, а её плановый вес в S не кладётся. Тогда книга после идеального исполнения = база, и доля
    торгуемой бумаги после сделок = её плану. Прежнее правило (вес «держать» в S, рубли мимо F) занижало
    базу у «держать» с перевесом и раздувало у «держать» с недобором."""

    AS_OF = "2026-11-11"
    ROWS = {  # ticker: (рубли, план %, слово плана)
        "W": (300_000, 20.0, "WAIT"),      # заблокирована ниже плана
        "K1": (375_000, 10.0, "KEEP"),     # «держать», перевес
        "K2": (225_000, 10.0, "KEEP"),      # «держать», недобор
        "R": (1_380_000, 30.0, "BUY"),       # перевес, докупка не нужна
        "B": (420_000, 10.0, "BALANCE"),   # «привести к плану», перевес → срез
        "O": (300_000, 20.0, "BUY"),       # недобор → докупка
    }

    def _auto(self, plan_rub=4_500_000):
        book = sum(v for v, _, _ in self.ROWS.values())
        holdings = []
        for t, (v, _p, _w) in self.ROWS.items():
            h = mk_stock(t, v)
            h.update({"current_price": 100.0, "lot_size": 1})
            holdings.append(h)
        per = {t: mk_ie_row(planned=p, real=v / book * 100, user_plan=w) for t, (v, p, w) in self.ROWS.items()}
        snap = mk_snapshot(holdings, per, plan_rub, book, 15_000_000, as_of=self.AS_OF)
        res = gas.run_auto(snap, None, _conds([]), None, 1.0)
        return {r["ticker"]: r for r in res["rows"]}, res

    def test_base_is_fixed_money_plus_traded_targets(self):
        rows, res = self._auto()
        traded = [t for t, r in rows.items() if r["target_rub"] is not None]
        self.assertEqual(sorted(traded), ["B", "O"])
        fixed = sum(r["current_rub"] for t, r in rows.items() if t not in traded)
        self.assertEqual(fixed, 2_280_000)
        self.assertEqual(res["base_source"], "fixed_point")
        self.assertAlmostEqual(res["base_rub"], 2_280_000 / 0.7, delta=5)
        self.assertAlmostEqual(res["base_rub"], fixed + sum(rows[t]["target_rub"] for t in traded), delta=5)
        self.assertEqual(rows["B"]["direction"], "trim")
        self.assertEqual(rows["O"]["direction"], "buy")
        for t in ("K1", "K2", "R"):
            self.assertIsNone(rows[t]["direction"])

    def test_share_after_execution_equals_plan(self):
        rows, res = self._auto()
        after = {t: r["current_rub"] + (r["trade_rub"] or 0) * (1 if r["direction"] == "buy" else -1 if r["direction"] == "trim" else 0)
                 for t, r in rows.items()}
        book_after = sum(after.values())
        self.assertAlmostEqual(book_after, res["base_rub"], delta=200)
        self.assertAlmostEqual(after["B"] / book_after * 100, 10.0, delta=0.01)
        self.assertAlmostEqual(after["O"] / book_after * 100, 20.0, delta=0.01)

    def test_calibration_2026_11_11_cnru(self):
        """Калибровка по живым числам 11.11 (синтетика с теми же суммами): заблокировано 3 941 565 ₽,
        «держать» и бумаги в коридоре 9 898 485 ₽, срезаемая CNRU 678 000 ₽ (план 3 %, цена 904).
        База = 13 840 050 / 0,97 = 14 268 093 ₽, цель CNRU = 428 043 ₽ (3,0 % книги после сделок),
        срез 93 лота. Прежнее правило клало «держать» в S плановым весом и давало базу 4,388 млн,
        цель 2,77 % и 103 лота."""
        rows = {"BLK": (3_941_565, 30.0, "WAIT"), "H1": (5_400_000, 20.0, "KEEP"),
                "H2": (4_498_485, 25.0, "KEEP"), "CNRU": (678_000, 3.0, "BALANCE")}
        book = sum(v for v, _, _ in rows.values())
        holdings = []
        for t, (v, _p, _w) in rows.items():
            h = mk_stock(t, v)
            h.update({"current_price": 904.0 if t == "CNRU" else 100.0, "lot_size": 1})
            holdings.append(h)
        per = {t: mk_ie_row(planned=p, real=v / book * 100, user_plan=w) for t, (v, p, w) in rows.items()}
        snap = mk_snapshot(holdings, per, 17_656_764, book, 20_000_000, as_of="2026-11-11")
        res = gas.run_auto(snap, None, _conds([]), None, 1.0)
        c = next(r for r in res["rows"] if r["ticker"] == "CNRU")
        self.assertEqual(res["base_source"], "fixed_point")
        self.assertAlmostEqual(res["base_rub"], 13_840_050 / 0.97, delta=5)
        self.assertAlmostEqual(c["target_rub"], 428_043, delta=5)
        self.assertEqual((c["direction"], c["lots"]), ("trim", 277))

    def test_no_gates_same_formula_no_jump(self):
        """Блокировок нет → та же формула (непрерывная база §10.6, 11.11): «держать», перевес BUY в F своими рублями,
        база = 1 980 000 / (1 − 0,30) = 2 828 571, а не план класса 4 500 000 (раньше — скачок на ветку t_full_no_gates)."""
        rows = dict(self.ROWS)
        rows.pop("W")
        saved, self.ROWS = self.ROWS, rows
        try:
            _r, res = self._auto()
        finally:
            self.ROWS = saved
        self.assertEqual(res["base_source"], "fixed_point")
        self.assertAlmostEqual(res["base_rub"], 1_980_000 / 0.7, delta=5)



class TestManualClassifiesLikeAuto(unittest.TestCase):
    """§10.6 п.3 (11.11, фикстура аудита manual_cf): ручной режим (--open/--trim) классифицирует бумаги вне --open как авто —
    условие «держать»/с продажей (_auto_stop_condition) и лимит эмитента блокируют недобранную бумагу. Раньше такие бумаги
    в ручном режиме были dormant, а при отсутствии других блокировок ручная база уходила на план класса — сайт и разбор
    называли разные базы. Ручная база = run_auto."""

    AS_OF = "2026-11-11"

    def _snap(self):
        rows = {"H1": (900_000, 30.0, "KEEP"), "H2": (750_000, 25.0, "KEEP"), "C": (180_000, 3.0, "BALANCE"),
                "N": (180_000, 8.0, "KEEP"), "SBER": (600_000, 20.0, "KEEP"), "SBERP": (240_000, 9.0, "KEEP")}
        book = sum(v for v, _, _ in rows.values())
        holdings = [_auto_stock(t, v) for t, (v, _p, _w) in rows.items()]
        per = {t: mk_ie_row(planned=p, real=v / book * 100, user_plan=w) for t, (v, p, w) in rows.items()}
        return mk_snapshot(holdings, per, 3_600_000, book, 15_000_000, as_of=self.AS_OF)

    def _cond(self):
        # N: условие «держать» до отчёта (while_pending HOLD) — закрывает докупку
        return _conds([{"id": "n-hold", "version": 1, "key": "N", "kind": "trade",
                        "trigger": {"type": "report_published", "value": "МСФО", "window_end": "2026-12-03"},
                        "on_trigger": {"action": "set_verdict", "verdict": "HOLD", "text": "фикстура"},
                        "while_pending": {"verdict": "HOLD"},
                        "created_at": "2026-10-01T10:00:00+03:00", "created_by": "owner"}])

    def test_manual_base_equals_auto(self):
        snap, cond = self._snap(), self._cond()
        lim = gas.load_limits_config(gas._DEFAULT_CONCENTRATION_LIMITS_PATH)
        auto = gas.run_auto(snap, None, cond, lim, 1.0)
        trims = ",".join(f"{r['ticker']}={r['plan_pct']}" for r in auto["rows"] if r["category"] == "rebalancing")
        man = gas.run_sizing(snapshot=snap, gate_inputs=None, conditions=cond, open_arg=None, selling_arg=None,
                             blocked_arg=None, extra_cash_from_sales=0.0, quotes=None, yaml_warnings=[], trim_arg=trims,
                             limits_config=lim, concentration_today=self.AS_OF)
        blocked = {x["ticker"]: x["reason"] for x in man["classification"]["blocked"]}
        self.assertIn("condition_hold:n-hold", blocked.get("N") or "")
        self.assertIn("concentration_breach:", blocked.get("SBERP") or "")
        self.assertEqual(trims, "C=3.0")
        self.assertAlmostEqual(man["base_rub"], auto["base_rub"], delta=0.01)
        self.assertEqual(man["base_source"], auto["base_source"])
        c_man = man["classification"]["rebalancing"][0]
        c_auto = next(r for r in auto["rows"] if r["ticker"] == "C")
        self.assertAlmostEqual(c_man["target_rub"], c_auto["target_rub"], delta=0.01)


if __name__ == "__main__":
    unittest.main(verbosity=2)
