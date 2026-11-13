#!/usr/bin/env python3
"""
test_concentration_limits.py — тесты для scripts/concentration_limits.py.

Постановка — docs/investment/spec-gate-aware-sizing-trim-fix.md §9 (задача C).
Покрывает: группировку эмитента из конфига (не эвристикой по суффиксу "P"),
именованные исключения (запись, а не число; истёкшая review_date деградирует
к лимиту по умолчанию + warning; отсутствие review_date конфиг не принимает),
знаменатель L2_cur (фактическая книга, НЕ T*), реакцию на нарушение (срез до
лимита), секторный лимит (гейт на sector=null coverage), и exit 2 без traceback
на битом конфиге/снапшоте.

Два слоя:
  - синтетические фикстуры (детерминированно, без Synology) — основная регрессия;
  - живой прогон на portfolio-2026-08-21.json + шипованном concentration-limits.yaml
    (skipTest, если файл/PyYAML недоступны) — сверка эталонных чисел C-T1..C-T6
    из §9.4 спеки.

Запуск:
    ~/.pyenv/versions/3.12.9/bin/python3 skills/ru-portfolio-advisor/tests/test_concentration_limits.py
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SKILL_DIR = os.path.join(REPO, "skills", "ru-portfolio-advisor")
SCRIPT_PATH = os.path.join(SKILL_DIR, "scripts", "concentration_limits.py")
SHIPPED_LIMITS_YAML = os.path.join(SKILL_DIR, "references", "concentration-limits.yaml")

sys.path.insert(0, os.path.join(SKILL_DIR, "scripts"))
import concentration_limits as cl  # noqa: E402

PY = sys.executable

SYNOLOGY_SNAPSHOT = os.path.expanduser(
    "~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/Portfolio/snapshots/portfolio-2026-08-21.json"
)

try:
    import yaml  # noqa: F401
    HAVE_YAML = True
except ImportError:
    HAVE_YAML = False


# ─────────────────────────── синтетические фикстуры ───────────────────────────

def mk_stock(ticker, value_rub, *, sector=None, is_blocked=False, price_source="moex_iss"):
    return {
        "ticker": ticker, "asset_type": "stock", "value_rub": value_rub,
        "sector": sector, "is_blocked": is_blocked, "current_price_source": price_source,
    }


def mk_bond(ticker, value_rub):
    return {"ticker": ticker, "asset_type": "bond", "value_rub": value_rub, "sector": None}


def mk_snapshot(holdings):
    return {"holdings": holdings}


def mk_config(*, default_limit=15.0, sector_limit=35.0, null_threshold=5.0,
              issuer_groups=None, exceptions=None):
    return {
        "default_issuer_limit_pct": default_limit,
        "sector_limit_pct": sector_limit,
        "sector_null_share_threshold_pct": null_threshold,
        "issuer_groups": issuer_groups or {},
        "issuer_exceptions": exceptions or {},
    }


# Базовая корзина: L2_cur = 10 000 ровно.
#   FOO+FOOP (группа "FOO") = 1 300 + 600 = 1 900 → 19% книги
#   BAR (своя группа)       = 1 077            → 10,77% книги
#   BAZ, QUX — заполняют остаток, разные секторы.
def _base_holdings():
    return [
        mk_stock("FOO", 1_300, sector=None),
        mk_stock("FOOP", 600, sector="Финансовый"),
        mk_stock("BAR", 1_077, sector=None),
        mk_stock("BAZ", 2_023, sector="IT"),
        mk_stock("QUX", 5_000, sector="IT"),
    ]


def _base_config(*, with_exception=True, review_date="2027-01-01"):
    exceptions = {}
    if with_exception:
        exceptions["foo"] = {
            "issuer": "FOO", "limit_pct": 20.0,
            "basis": "тестовое исключение", "review_date": review_date,
        }
    return mk_config(issuer_groups={"FOO": ["FOO", "FOOP"]}, exceptions=exceptions)


class TestIssuerGroupingAndException(unittest.TestCase):
    """Аналог C-T1/C-T2 на синтетике: группировка из конфига + именованное исключение."""

    def test_group_within_exception_limit_no_breach(self):
        snap = mk_snapshot(_base_holdings())
        config = _base_config(with_exception=True)
        result = cl.compute_concentration(snap, config, today="2026-08-26")

        self.assertEqual(result["l2_cur"], 10_000.0)
        foo = result["concentration"]["by_issuer"]["FOO"]
        self.assertEqual(foo["tickers"], ["FOO", "FOOP"])
        self.assertAlmostEqual(foo["value_rub"], 1_900.0, delta=0.01)
        self.assertAlmostEqual(foo["share_pct"], 19.0, delta=0.01)
        self.assertEqual(foo["limit_pct"], 20.0)
        self.assertEqual(foo["limit_source"], "exception:foo")
        self.assertAlmostEqual(foo["headroom_pp"], 1.0, delta=0.01)
        self.assertFalse(foo["breach"])
        self.assertEqual(foo["trim_to_limit_rub"], 0.0)

    def test_other_group_default_limit_no_breach(self):
        snap = mk_snapshot(_base_holdings())
        config = _base_config(with_exception=True)
        result = cl.compute_concentration(snap, config, today="2026-08-26")

        bar = result["concentration"]["by_issuer"]["BAR"]
        self.assertAlmostEqual(bar["value_rub"], 1_077.0, delta=0.01)
        self.assertAlmostEqual(bar["share_pct"], 10.77, delta=0.01)
        self.assertEqual(bar["limit_pct"], 15.0)
        self.assertEqual(bar["limit_source"], "default")
        self.assertFalse(bar["breach"])

        # FOO (с исключением) и BAR (10,77% < 15%) — не в нарушении. BAZ/QUX в этой
        # фикстуре намеренно крупные (20,23% и 50% книги) и без исключения — они
        # breach'ат default-лимит 15%, это отдельная проверка (не «ни одна группа»,
        # как в реальном портфеле C-T2, — здесь фикстура сконструирована иначе).
        self.assertFalse(result["concentration"]["by_issuer"]["FOO"]["breach"])
        self.assertFalse(bar["breach"])
        self.assertNotIn("FOO", result["blocked_for_open"])
        self.assertNotIn("BAR", result["blocked_for_open"])

    def test_grouping_is_config_driven_not_suffix_heuristic(self):
        """Тикер с суффиксом P, НЕ упомянутый в issuer_groups, — своя отдельная группа."""
        holdings = [mk_stock("ABCD", 1_000), mk_stock("ABCDP", 1_000)]
        config = mk_config(issuer_groups={})  # пусто — суффиксная эвристика не должна сработать
        result = cl.compute_concentration(mk_snapshot(holdings), config, today="2026-08-26")
        by_issuer = result["concentration"]["by_issuer"]
        self.assertIn("ABCD", by_issuer)
        self.assertIn("ABCDP", by_issuer)
        self.assertEqual(by_issuer["ABCD"]["tickers"], ["ABCD"])
        self.assertEqual(by_issuer["ABCDP"]["tickers"], ["ABCDP"])


class TestExceptionRemovedOrExpired(unittest.TestCase):
    """Аналог C-T3/C-T4."""

    def test_exception_removed_breach_at_default_limit(self):
        snap = mk_snapshot(_base_holdings())
        config = _base_config(with_exception=False)
        result = cl.compute_concentration(snap, config, today="2026-08-26")

        foo = result["concentration"]["by_issuer"]["FOO"]
        self.assertEqual(foo["limit_pct"], 15.0)
        self.assertEqual(foo["limit_source"], "default")
        self.assertTrue(foo["breach"])
        # 1900 − 0.15×10000 = 400
        self.assertAlmostEqual(foo["trim_to_limit_rub"], 400.0, delta=0.01)
        self.assertIn("concentration_breach:FOO", result["warnings"])
        self.assertIn("FOO", result["blocked_for_open"])
        self.assertIn("FOOP", result["blocked_for_open"])

    def test_expired_exception_degrades_to_default_with_warning(self):
        snap = mk_snapshot(_base_holdings())
        config = _base_config(with_exception=True, review_date="2020-01-01")  # в прошлом
        result = cl.compute_concentration(snap, config, today="2026-08-26")

        foo = result["concentration"]["by_issuer"]["FOO"]
        self.assertEqual(foo["limit_pct"], 15.0)
        self.assertEqual(foo["limit_source"], "default")
        self.assertTrue(foo["breach"])
        self.assertIn("exception_expired:foo", result["warnings"])

    def test_exception_not_yet_expired_on_boundary_date_applies(self):
        """review_date == today — ещё действует (правило: истекает СТРОГО после даты)."""
        snap = mk_snapshot(_base_holdings())
        config = _base_config(with_exception=True, review_date="2026-08-26")
        result = cl.compute_concentration(snap, config, today="2026-08-26")
        foo = result["concentration"]["by_issuer"]["FOO"]
        self.assertEqual(foo["limit_source"], "exception:foo")
        self.assertFalse(foo["breach"])


class TestSectorLimit(unittest.TestCase):
    """Аналог C-T5: секторный лимит отключается на грязных данных."""

    def test_sector_disabled_flag_off_by_default(self):
        snap = mk_snapshot(_base_holdings())
        config = _base_config()
        result = cl.compute_concentration(snap, config, today="2026-08-26", sector_enabled=False)
        by_sector = result["concentration"]["by_sector"]
        self.assertEqual(by_sector["status"], "disabled")
        self.assertEqual(by_sector["reason"], "sector_flag_off")
        self.assertNotIn("sector_limit_disabled", result["warnings"])

    def test_sector_disabled_on_null_coverage_above_threshold(self):
        snap = mk_snapshot(_base_holdings())  # null: FOO(1300)+BAR(1077)=2377 → 23,77% книги
        config = _base_config()
        result = cl.compute_concentration(snap, config, today="2026-08-26", sector_enabled=True)
        by_sector = result["concentration"]["by_sector"]
        self.assertEqual(by_sector["status"], "disabled")
        self.assertEqual(by_sector["reason"], "sector_coverage_below_threshold")
        self.assertAlmostEqual(by_sector["null_share_pct"], 23.77, delta=0.01)
        self.assertIn("sector_limit_disabled", result["warnings"])

    def test_sector_computed_when_coverage_ok(self):
        """Полная секторная разметка → кластер считается и может нарушить лимит."""
        holdings = [
            mk_stock("A", 3_000, sector="IT"),
            mk_stock("B", 4_000, sector="IT"),
            mk_stock("C", 3_000, sector="Финансовый"),
        ]
        config = mk_config(sector_limit=35.0, null_threshold=5.0)
        result = cl.compute_concentration(mk_snapshot(holdings), config, today="2026-08-26", sector_enabled=True)
        by_sector = result["concentration"]["by_sector"]
        self.assertNotIn("status", by_sector)
        it = by_sector["IT"]
        self.assertAlmostEqual(it["value_rub"], 7_000.0, delta=0.01)
        self.assertAlmostEqual(it["share_pct"], 70.0, delta=0.01)
        self.assertTrue(it["breach"])
        self.assertIn("concentration_breach:IT", result["warnings"])
        self.assertIn("A", result["blocked_for_open"])
        self.assertIn("B", result["blocked_for_open"])


class TestDenominatorIsL2CurNotTStar(unittest.TestCase):
    """C-T6: знаменатель — фактическая книга L2_cur, не зависит от постороннего контекста
    (тримов/докупок/T*), которого этот модуль вообще не принимает на вход."""

    def test_irrelevant_holdings_excluded_from_l2_cur(self):
        holdings = _base_holdings() + [
            mk_bond("OFZ26238", 50_000),                      # не акция
            mk_stock("FROZEN", 100_000, price_source="cost_basis"),  # заморожена
            mk_stock("BLOCKED", 100_000, is_blocked=True),     # заблокирована
            mk_stock("LQDT", 100_000),                         # money-market
        ]
        config = _base_config(with_exception=True)
        result = cl.compute_concentration(mk_snapshot(holdings), config, today="2026-08-26")

        self.assertEqual(result["l2_cur"], 10_000.0)  # ровно как в базовой корзине
        foo = result["concentration"]["by_issuer"]["FOO"]
        self.assertAlmostEqual(foo["share_pct"], 19.0, delta=0.01)

    def test_share_pct_stable_across_sector_flag_toggle(self):
        """Переключение --sector не должно менять долю по эмитенту — разные вопросы,
        разные знаменатели/расчёты, но по одному и тому же L2_cur."""
        snap = mk_snapshot(_base_holdings())
        config = _base_config(with_exception=True)
        r_off = cl.compute_concentration(snap, config, today="2026-08-26", sector_enabled=False)
        r_on = cl.compute_concentration(snap, config, today="2026-08-26", sector_enabled=True)
        self.assertEqual(
            r_off["concentration"]["by_issuer"]["FOO"]["share_pct"],
            r_on["concentration"]["by_issuer"]["FOO"]["share_pct"],
        )


class TestConfigValidation(unittest.TestCase):
    """Исключение без review_date конфиг не принимает — молчаливая отмена лимита."""

    def test_exception_without_review_date_rejected(self):
        config = mk_config(exceptions={
            "foo": {"issuer": "FOO", "limit_pct": 20.0, "basis": "нет даты"}
        })
        with self.assertRaises(cl.ConcentrationLimitsError):
            cl._validate_limits_config(config, source="<test>")

    def test_exception_missing_basis_rejected(self):
        config = mk_config(exceptions={
            "foo": {"issuer": "FOO", "limit_pct": 20.0, "review_date": "2027-01-01"}
        })
        with self.assertRaises(cl.ConcentrationLimitsError):
            cl._validate_limits_config(config, source="<test>")

    def test_two_exceptions_same_issuer_rejected(self):
        config = mk_config(exceptions={
            "a": {"issuer": "FOO", "limit_pct": 20.0, "basis": "x", "review_date": "2027-01-01"},
            "b": {"issuer": "FOO", "limit_pct": 25.0, "basis": "y", "review_date": "2027-01-01"},
        })
        with self.assertRaises(cl.ConcentrationLimitsError):
            cl._validate_limits_config(config, source="<test>")

    def test_missing_default_limit_rejected(self):
        config = {"sector_limit_pct": 35.0}
        with self.assertRaises(cl.ConcentrationLimitsError):
            cl._validate_limits_config(config, source="<test>")

    @unittest.skipUnless(HAVE_YAML, "PyYAML недоступен")
    def test_load_limits_config_rejects_bad_review_date_via_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(
                "default_issuer_limit_pct: 15.0\n"
                "sector_limit_pct: 35.0\n"
                "issuer_exceptions:\n"
                "  foo:\n"
                "    issuer: FOO\n"
                "    limit_pct: 20.0\n"
                "    basis: x\n"
            )
            path = f.name
        try:
            with self.assertRaises(cl.ConcentrationLimitsError):
                cl.load_limits_config(path)
        finally:
            os.unlink(path)


class TestEmptyOrInvalidSnapshot(unittest.TestCase):

    def test_no_holdings_key_raises(self):
        with self.assertRaises(cl.ConcentrationLimitsError):
            cl.active_stock_holdings({})

    def test_zero_l2_cur_raises(self):
        config = _base_config()
        with self.assertRaises(cl.ConcentrationLimitsError):
            cl.compute_concentration(mk_snapshot([]), config, today="2026-08-26")


# ─────────────────────────── CLI: exit codes без traceback ───────────────────────────

class TestCliExitCodes(unittest.TestCase):

    def test_missing_snapshot_exit_2_no_traceback(self):
        proc = subprocess.run(
            [PY, SCRIPT_PATH, "--snapshot", "/tmp/does-not-exist.json", "--limits", SHIPPED_LIMITS_YAML],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("Снапшот не найден", proc.stderr)

    def test_missing_limits_config_exit_2_no_traceback(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(mk_snapshot(_base_holdings()), f, ensure_ascii=False)
            snap_path = f.name
        try:
            proc = subprocess.run(
                [PY, SCRIPT_PATH, "--snapshot", snap_path, "--limits", "/tmp/does-not-exist-limits.yaml"],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertIn("Конфиг лимитов не найден", proc.stderr)
        finally:
            os.unlink(snap_path)

    def test_broken_snapshot_json_exit_2_no_traceback(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write("{не валидный json")
            snap_path = f.name
        try:
            proc = subprocess.run(
                [PY, SCRIPT_PATH, "--snapshot", snap_path, "--limits", SHIPPED_LIMITS_YAML],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertNotIn("Traceback", proc.stderr)
        finally:
            os.unlink(snap_path)

    @unittest.skipUnless(HAVE_YAML, "PyYAML недоступен")
    def test_full_cli_json_round_trip_success(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(mk_snapshot(_base_holdings()), f, ensure_ascii=False)
            snap_path = f.name
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(
                "default_issuer_limit_pct: 15.0\n"
                "sector_limit_pct: 35.0\n"
                "issuer_groups:\n"
                "  FOO: [FOO, FOOP]\n"
                "issuer_exceptions:\n"
                "  foo:\n"
                "    issuer: FOO\n"
                "    limit_pct: 20.0\n"
                "    basis: тест\n"
                "    review_date: \"2027-01-01\"\n"
            )
            limits_path = f.name
        try:
            proc = subprocess.run(
                [PY, SCRIPT_PATH, "--snapshot", snap_path, "--limits", limits_path, "--json"],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertAlmostEqual(out["concentration"]["by_issuer"]["FOO"]["share_pct"], 19.0, delta=0.01)
            self.assertEqual(out["concentration"]["by_issuer"]["FOO"]["limit_source"], "exception:foo")
        finally:
            os.unlink(snap_path)
            os.unlink(limits_path)


# ───────────────── единственный источник active_stock_holdings (§11 задача 3) ─────────────────
#
# До волны 3 проводки concentration_limits.py держал СОЗНАТЕЛЬНЫЙ твин фильтра
# active_stock_holdings (и копию MONEY_MARKET_TICKERS) — параллельная правка обоих файлов
# не позволяла сцепиться напрямую. Параллельной работы больше нет: твин сведён к импорту
# (gate_aware_sizing.active_stock_holdings — единственный источник, см. docstring модуля).
# Тест ниже проверяет ДЕЛЕГИРОВАНИЕ (что копии больше нет и логика вызывается из одного
# места), а не поведенческое совпадение двух независимых копий — сравнивать копии друг с
# другом больше не нужно, копия одна.

class TestSingleSourceActiveStockHoldings(unittest.TestCase):
    """§11 «Волна 3» spec-gate-aware-sizing-trim-fix.md — твин сведён к импорту."""

    def test_no_local_money_market_tickers_copy(self):
        """Список тикеров money-market фондов больше не дублируется в этом модуле —
        фильтр целиком делегирован gate_aware_sizing.py, вести список дважды незачем."""
        self.assertFalse(hasattr(cl, "MONEY_MARKET_TICKERS"))

    def test_active_stock_holdings_delegates_to_gate_aware_sizing(self):
        import gate_aware_sizing as gas
        import unittest.mock as mock

        snap = mk_snapshot(_base_holdings())
        with mock.patch.object(gas, "active_stock_holdings", wraps=gas.active_stock_holdings) as spy:
            result = cl.active_stock_holdings(snap)
        spy.assert_called_once_with(snap)
        self.assertEqual(result, gas.active_stock_holdings(snap))

    def test_error_type_translated_to_concentration_limits_error(self):
        """Делегирование не должно менять публичный контракт ошибок этого модуля —
        gate_aware_sizing.GateAwareSizingError транслируется в ConcentrationLimitsError."""
        with self.assertRaises(cl.ConcentrationLimitsError):
            cl.active_stock_holdings({})


# ─────────────────────────── живой прогон на реальном снапшоте ───────────────────────────

if __name__ == "__main__":
    unittest.main()
