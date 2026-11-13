#!/usr/bin/env python3
"""
test_compute_per_position.py — тесты для compute_per_position.py.

Фокус — SS-1: эмпирические факторные беты через OLS на MOEX/CBR истории.
Все сетевые fetch-функции мокаются → тесты офлайн, детерминированы.
priors-режим проверяется на неизменность поведения.

Зависимости: numpy (для OLS-тестов). Остальное — stdlib.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import compute_per_position as m  # noqa: E402

HAS_NUMPY = True
try:
    import numpy  # noqa: F401
except ImportError:
    HAS_NUMPY = False


# ───────────────────────── Чистые хелперы (без сети) ─────────────────────────

class TestMonthlyHelpers(unittest.TestCase):
    def test_monthly_last_level_picks_latest_in_month(self):
        pairs = [
            ("2026-01-05", 100.0), ("2026-01-28", 110.0),
            ("2026-02-03", 120.0), ("2026-02-27", 115.0),
        ]
        ml = m._monthly_last_level(pairs)
        self.assertEqual(ml["2026-01"], 110.0)  # последняя дата января
        self.assertEqual(ml["2026-02"], 115.0)

    def test_levels_to_returns(self):
        ml = {"2026-01": 100.0, "2026-02": 110.0, "2026-03": 99.0}
        r = m._levels_to_returns(ml)
        self.assertNotIn("2026-01", r)  # у первого месяца нет предыдущего
        self.assertAlmostEqual(r["2026-02"], 10.0)     # +10%
        self.assertAlmostEqual(r["2026-03"], -10.0)    # 110→99 = -10%

    def test_levels_to_diffs_pp(self):
        ml = {"2026-01": 16.0, "2026-02": 16.0, "2026-03": 14.5}
        d = m._levels_to_diffs(ml)
        self.assertAlmostEqual(d["2026-02"], 0.0)
        self.assertAlmostEqual(d["2026-03"], -1.5)  # п.п.

    def test_window_months(self):
        w = m._window_months(3, (2026, 2))
        self.assertEqual(w, [(2025, 12), (2026, 1), (2026, 2)])

    def test_window_months_wraps_year(self):
        w = m._window_months(2, (2026, 1))
        self.assertEqual(w, [(2025, 12), (2026, 1)])

    def test_brent_secid(self):
        self.assertEqual(m._brent_secid(2026, 6), "BRM6")   # M = июнь
        self.assertEqual(m._brent_secid(2026, 1), "BRF6")   # F = январь
        self.assertEqual(m._brent_secid(2025, 12), "BRZ5")  # Z = декабрь

    def test_next_month(self):
        self.assertEqual(m._next_month((2026, 6)), (2026, 7))
        self.assertEqual(m._next_month((2026, 12)), (2027, 1))

    def test_brent_front_for_month(self):
        # BR-X.YY гасится ~1-го числа месяца X → front в течение m = BR-(m+1)
        self.assertEqual(m._brent_front_for_month((2026, 6)), "BRN6")   # июнь → BR-7
        self.assertEqual(m._brent_front_for_month((2026, 12)), "BRF7")  # дек → BR-1.27
        self.assertEqual(m._brent_front_for_month((2026, 3)), "BRJ6")   # март → BR-4

    def test_month_end_str_is_next_month_first(self):
        self.assertEqual(m._month_end_str((2026, 6)), "2026-07-01")
        self.assertEqual(m._month_end_str((2026, 12)), "2027-01-01")

    def test_rows_to_pairs_filters_board_and_zeros(self):
        payload = {"history": {
            "columns": ["BOARDID", "TRADEDATE", "CLOSE"],
            "data": [
                ["TQBR", "2026-01-05", 100.0],
                ["SPEQ", "2026-01-05", 99.0],   # другая доска — отброс
                ["TQBR", "2026-01-06", 0],       # нулевая цена — отброс
                ["TQBR", "2026-01-07", 101.0],
            ],
        }}
        pairs = m._rows_to_pairs(payload, "history", "TRADEDATE", "CLOSE",
                                 board_col="BOARDID", board="TQBR")
        self.assertEqual(pairs, [("2026-01-05", 100.0), ("2026-01-07", 101.0)])


# ───────────────────────── OLS-движок ─────────────────────────

@unittest.skipUnless(HAS_NUMPY, "требует numpy")
class TestRunOLS(unittest.TestCase):
    def test_recovers_known_betas_no_noise(self):
        # y = 0.15·x1 − 0.1·x2 + 0.05·x3 (точно, без шума) + const 2.0
        n = 24
        x1 = [(i % 7) - 3 + 0.1 * i for i in range(n)]
        x2 = [(i % 5) - 2 - 0.07 * i for i in range(n)]
        x3 = [((i * i) % 11) - 5 for i in range(n)]
        y = [2.0 + 0.15 * x1[i] - 0.1 * x2[i] + 0.05 * x3[i] for i in range(n)]
        betas, r2 = m.run_ols(y, {"brent": x1, "usdrub": x2, "cnyrub": x3})
        self.assertAlmostEqual(betas["brent"], 0.15, places=4)
        self.assertAlmostEqual(betas["usdrub"], -0.1, places=4)
        self.assertAlmostEqual(betas["cnyrub"], 0.05, places=4)
        self.assertAlmostEqual(r2, 1.0, places=4)  # идеальная подгонка

    def test_units_beta_is_pct_stock_per_pct_factor(self):
        # При движении brent на +1% и β=0.5 акция должна двигаться на +0.5%
        n = 18
        x = [float(i - 9) for i in range(n)]  # −9..+8, ненулевая дисперсия
        y = [0.5 * v for v in x]
        betas, r2 = m.run_ols(y, {"brent": x})
        self.assertAlmostEqual(betas["brent"], 0.5, places=6)

    def test_low_r2_when_factors_dont_explain(self):
        # y альтернирует ±100, факторы — гладкие → низкий R²
        n = 24
        x1 = [float(i) for i in range(n)]
        x2 = [float(i * i) * 0.05 for i in range(n)]
        x3 = [float(24 - i) for i in range(n)]
        x4 = [float(i % 6) for i in range(n)]
        y = [100.0 if i % 2 == 0 else -100.0 for i in range(n)]
        betas, r2 = m.run_ols(y, {"brent": x1, "usdrub": x2, "cnyrub": x3, "cbr_rate": x4})
        self.assertLess(r2, 0.3)

    def test_empty_inputs(self):
        betas, r2 = m.run_ols([], {})
        self.assertEqual(betas, {})
        self.assertEqual(r2, 0.0)


# ───────────────────────── compute_regression_betas ─────────────────────────

def _synthetic_matrix(n=24, start=(2024, 6)):
    """Факторная матрица {factor: {YYYY-MM: движение}} на n месяцев."""
    months = [f"{y:04d}-{mo:02d}" for (y, mo) in m._window_months(n, (2026, 5))]
    x1 = {months[i]: (i % 7) - 3 + 0.1 * i for i in range(n)}
    x2 = {months[i]: (i % 5) - 2 - 0.07 * i for i in range(n)}
    x3 = {months[i]: ((i * i) % 11) - 5 for i in range(n)}
    x4 = {months[i]: (i % 3 - 1) * 0.5 for i in range(n)}
    return {"brent": x1, "usdrub": x2, "cnyrub": x3, "cbr_rate": x4}, months


@unittest.skipUnless(HAS_NUMPY, "требует numpy")
class TestComputeRegressionBetas(unittest.TestCase):
    def test_empirical_overrides_priors_keeps_sanctions(self):
        matrix, months = _synthetic_matrix()
        # Истинные беты, по которым сгенерим доходность акции
        true_b = {"brent": 0.2, "usdrub": -0.15, "cnyrub": 0.1, "cbr_rate": -0.3}
        stock = {
            mo: sum(true_b[f] * matrix[f][mo] for f in true_b)
            for mo in months
        }
        prior = {"factor_betas": {
            "sanctions": -40, "geopol": -25, "xauusd": 0.05,
            "brent": 0.01, "usdrub": 0.01, "cnyrub": 0.01, "cbr_rate": 0.01,
        }}
        res = m.compute_regression_betas(
            "TEST", matrix, prior, months=24, ref=(2026, 5),
            share_fetcher=lambda: stock,
        )
        self.assertIsNotNone(res)
        betas, r2, empirical, n_dropped = res
        # эмпирические перекрыли priors
        self.assertAlmostEqual(betas["brent"], 0.2, places=3)
        self.assertAlmostEqual(betas["cbr_rate"], -0.3, places=3)
        # sanctions/geopol/xauusd — из priors (D-C)
        self.assertEqual(betas["sanctions"], -40)
        self.assertEqual(betas["geopol"], -25)
        self.assertEqual(betas["xauusd"], 0.05)
        self.assertAlmostEqual(r2, 1.0, places=3)
        self.assertEqual(set(empirical), {"brent", "usdrub", "cnyrub", "cbr_rate"})
        self.assertEqual(n_dropped, 0)

    def test_drops_split_outlier_month(self):
        """Месяц-выброс (неадаптированный сплит) исключается, регрессия на чистых."""
        matrix, months = _synthetic_matrix()
        true_b = {"brent": 0.2, "usdrub": -0.15, "cnyrub": 0.1, "cbr_rate": -0.3}
        stock = {mo: sum(true_b[f] * matrix[f][mo] for f in true_b) for mo in months}
        # вставляем сплит-выброс в один месяц (как VTBR 2024-07: +462624%)
        stock[months[5]] = 462624.7
        prior = {"factor_betas": {"sanctions": -40}}
        res = m.compute_regression_betas(
            "SPLIT", matrix, prior, months=24, ref=(2026, 5),
            share_fetcher=lambda: stock,
        )
        self.assertIsNotNone(res)
        betas, r2, empirical, n_dropped = res
        self.assertEqual(n_dropped, 1)               # один месяц исключён
        self.assertAlmostEqual(betas["brent"], 0.2, places=2)   # беты восстановлены
        self.assertAlmostEqual(r2, 1.0, places=2)    # на чистых данных R²≈1
        self.assertLess(abs(betas["cbr_rate"]), m.MAX_ABS_BETA)

    def test_degenerate_betas_rejected(self):
        """Если после OLS |β| > MAX_ABS_BETA → None (откат на priors)."""
        n = 24
        months = [f"2024-{i+1:02d}" if i < 12 else f"2025-{i-11:02d}" for i in range(n)]
        stock = {months[i]: (10.0 if i % 2 else -10.0) for i in range(n)}
        # фактор — крошечная копия y → для подгонки нужна β ≈ 1e5 (взрыв)
        tiny = {months[i]: stock[months[i]] * 1e-5 for i in range(n)}
        matrix = {"cbr_rate": tiny}
        prior = {"factor_betas": {"brent": 0.1}}
        res = m.compute_regression_betas(
            "DEG", matrix, prior, months=24, ref=(2025, 12),
            share_fetcher=lambda: stock,
        )
        self.assertIsNone(res)  # β взрывается → backstop → None

    def test_returns_none_when_insufficient_obs(self):
        matrix, months = _synthetic_matrix(n=24)
        # акция только за 5 месяцев → < MIN_REGRESSION_OBS
        stock = {months[i]: 1.0 * i for i in range(5)}
        prior = {"factor_betas": {"brent": 0.1}}
        res = m.compute_regression_betas(
            "SHORT", matrix, prior, months=24, ref=(2026, 5),
            share_fetcher=lambda: stock,
        )
        self.assertIsNone(res)

    def test_empty_matrix_returns_none(self):
        res = m.compute_regression_betas(
            "X", {}, {"factor_betas": {}}, months=24, ref=(2026, 5),
            share_fetcher=lambda: {"2026-01": 1.0},
        )
        self.assertIsNone(res)


# ───────────────────────── resolve_betas ─────────────────────────

class TestResolveBetas(unittest.TestCase):
    def test_priors_mode_unchanged(self):
        prior = {"factor_betas": {"brent": 0.15, "cbr_rate": -0.2},
                 "factor_betas_method": "sector prior", "factor_betas_r2": None}
        warns = []
        betas, method, r2 = m.resolve_betas(
            "SBER", prior, "priors", None, 24, None, warns)
        self.assertEqual(betas["brent"], 0.15)
        self.assertEqual(method, "sector prior")
        self.assertIsNone(r2)
        self.assertEqual(warns, [])

    def test_moex_empty_matrix_falls_back(self):
        prior = {"factor_betas": {"brent": 0.15}, "factor_betas_method": "p",
                 "factor_betas_r2": None}
        warns = []
        betas, method, r2 = m.resolve_betas(
            "SBER", prior, "moex", None, 24, (2026, 5), warns)
        self.assertEqual(betas["brent"], 0.15)  # priors
        self.assertEqual(method, "p")

    @unittest.skipUnless(HAS_NUMPY, "требует numpy")
    def test_moex_success_path(self):
        matrix, months = _synthetic_matrix()
        true_b = {"brent": 0.2, "usdrub": -0.15, "cnyrub": 0.1, "cbr_rate": -0.3}
        stock = {mo: sum(true_b[f] * matrix[f][mo] for f in true_b) for mo in months}
        prior = {"factor_betas": {"sanctions": -40, "brent": 0.01},
                 "factor_betas_method": "p", "factor_betas_r2": None}
        warns = []
        orig = m.fetch_moex_share_history
        m.fetch_moex_share_history = lambda t, mo, ref: stock
        try:
            betas, method, r2 = m.resolve_betas(
                "TEST", prior, "moex", matrix, 24, (2026, 5), warns)
        finally:
            m.fetch_moex_share_history = orig
        self.assertAlmostEqual(betas["brent"], 0.2, places=3)
        self.assertEqual(betas["sanctions"], -40)
        self.assertIn("OLS MOEX", method)
        self.assertIsNotNone(r2)

    def test_moex_fetch_raises_falls_back(self):
        matrix = {"brent": {"2026-01": 1.0}}
        prior = {"factor_betas": {"brent": 0.15}, "factor_betas_method": "p",
                 "factor_betas_r2": None}
        warns = []
        orig = m.fetch_moex_share_history

        def _boom(*a, **k):
            raise IOError("network down")
        m.fetch_moex_share_history = _boom
        try:
            betas, method, r2 = m.resolve_betas(
                "TEST", prior, "moex", matrix, 24, (2026, 5), warns)
        finally:
            m.fetch_moex_share_history = orig
        self.assertEqual(betas["brent"], 0.15)  # priors
        self.assertTrue(any("OLS не удался" in w for w in warns))


# ───────────────────────── compute_per_position (moex e2e, мокнутая сеть) ─────

@unittest.skipUnless(HAS_NUMPY, "требует numpy")
class TestComputePerPositionMoex(unittest.TestCase):
    def setUp(self):
        self.matrix, self.months = _synthetic_matrix()
        self._orig_build = m.build_factor_matrix
        self._orig_share = m.fetch_moex_share_history

    def tearDown(self):
        m.build_factor_matrix = self._orig_build
        m.fetch_moex_share_history = self._orig_share

    def _run(self, stock_for):
        m.build_factor_matrix = lambda months, ref, fetchers=None: self.matrix
        m.fetch_moex_share_history = lambda t, mo, ref: stock_for(t)
        snap = {"as_of_date": "2026-06-15", "holdings": [
            {"ticker": "AAA", "asset_type": "stock", "value_rub": 100000},
        ]}
        scen = {"A": {"p": 0.5, "factors": {"brent": -10, "cbr_rate": -3.5}},
                "B": {"p": 0.5, "factors": {"brent": 5, "usdrub": 8}}}
        priors = {"AAA": {"factor_betas": {"sanctions": -30, "brent": 0.01},
                          "factor_betas_method": "prior"}}
        return m.compute_per_position(snap, scen, priors, "moex", ref_month=(2026, 5))

    def test_r2_filled_and_betas_empirical(self):
        true_b = {"brent": 0.2, "usdrub": -0.15, "cnyrub": 0.1, "cbr_rate": -0.3}
        stock = {mo: sum(true_b[f] * self.matrix[f][mo] for f in true_b)
                 for mo in self.months}
        pp, warns, unm = self._run(lambda t: stock)
        entry = pp["AAA"]
        self.assertIsNotNone(entry["factor_betas_r2"])       # не null (acceptance)
        self.assertAlmostEqual(entry["factor_betas"]["brent"], 0.2, places=2)
        self.assertEqual(entry["factor_betas"]["sanctions"], -30)  # priors сохранены
        self.assertIn("OLS MOEX", entry["factor_betas_method"])

    def test_macro_blindspot_auto_when_low_r2(self):
        # доходность акции не объясняется факторами → R² < 0.3 → blindspot авто
        stock = {self.months[i]: (100.0 if i % 2 == 0 else -100.0)
                 for i in range(len(self.months))}
        pp, warns, unm = self._run(lambda t: stock)
        entry = pp["AAA"]
        self.assertLess(entry["factor_betas_r2"], 0.3)
        self.assertTrue(entry.get("macro_blindspot"))
        self.assertIn("low R^2", entry.get("macro_blindspot_reason", ""))

    def test_graceful_fallback_when_share_fetch_fails(self):
        def _boom(t):
            raise IOError("ISS 503")
        pp, warns, unm = self._run(_boom)
        entry = pp["AAA"]
        # упали на priors: r2 остался null, бета brent из priors
        self.assertIsNone(entry["factor_betas_r2"])
        self.assertEqual(entry["factor_betas"]["brent"], 0.01)
        self.assertTrue(any("OLS не удался" in w for w in warns))

    def test_empty_factor_matrix_falls_back_all(self):
        m.build_factor_matrix = lambda months, ref, fetchers=None: {}
        m.fetch_moex_share_history = lambda t, mo, ref: {}
        snap = {"as_of_date": "2026-06-15", "holdings": [
            {"ticker": "AAA", "asset_type": "stock", "value_rub": 100000}]}
        scen = {"A": {"p": 1.0, "factors": {"brent": -10}}}
        priors = {"AAA": {"factor_betas": {"brent": 0.15}, "factor_betas_method": "prior"}}
        pp, warns, unm = m.compute_per_position(snap, scen, priors, "moex",
                                                ref_month=(2026, 5))
        self.assertEqual(pp["AAA"]["factor_betas"]["brent"], 0.15)
        self.assertTrue(any("Не удалось построить" in w for w in warns))


# ───────────────────── V2-A: multiple horizons (by_horizon) ─────────────────────

class TestComputePerPositionV2Horizons(unittest.TestCase):
    """priors-режим, синтетика. Беты общие на горизонты, дельты разные."""

    SNAP = {"as_of_date": "2026-06-15",
            "holdings": [{"ticker": "AAA", "asset_type": "stock", "value_rub": 100000}]}
    PRIORS = {"AAA": {"factor_betas": {"brent": 1.0}, "factor_betas_method": "prior"}}

    def test_v2_by_horizon_betas_shared_deltas_differ(self):
        scen = {
            "A": {"p": 0.5, "factors_by_horizon": {"h12": {"brent": -10}, "h36": {"brent": -30}}},
            "B": {"p": 0.5, "factors_by_horizon": {"h12": {"brent": 5}, "h36": {"brent": 15}}},
        }
        pp, warns, _ = m.compute_per_position(self.SNAP, scen, self.PRIORS, "priors")
        entry = pp["AAA"]
        # Беты плоские (общие на все горизонты)
        self.assertIn("by_horizon", entry)
        self.assertNotIn("delta_pct_by_scenario", entry)  # больше не на верхнем уровне
        self.assertEqual(set(entry["by_horizon"]), {"h12", "h36"})
        # brent beta = 1.0 → delta = factor
        bh = entry["by_horizon"]
        self.assertEqual(bh["h12"]["delta_pct_by_scenario"]["A"]["value"], -10.0)
        self.assertEqual(bh["h36"]["delta_pct_by_scenario"]["A"]["value"], -30.0)
        # expected pweighted: h12 = 0.5*-10+0.5*5 = -2.5; h36 = 0.5*-30+0.5*15 = -7.5
        self.assertEqual(bh["h12"]["expected_pct_pweighted"]["value"], -2.5)
        self.assertEqual(bh["h36"]["expected_pct_pweighted"]["value"], -7.5)
        # tail var — worst scenario A на обоих горизонтах
        self.assertEqual(bh["h12"]["tail_var_scenario_id"], "A")
        self.assertEqual(bh["h36"]["tail_var_pct"], -30.0)
        # v2-вход → нет warning про обёртку
        self.assertFalse(any("v1-вход" in w for w in warns))

    def test_v1_input_wrapped_into_h20(self):
        scen = {"A": {"p": 1.0, "factors": {"brent": -10}}}
        pp, warns, _ = m.compute_per_position(self.SNAP, scen, self.PRIORS, "priors")
        entry = pp["AAA"]
        self.assertEqual(set(entry["by_horizon"]), {"h20"})
        self.assertEqual(entry["by_horizon"]["h20"]["delta_pct_by_scenario"]["A"]["value"], -10.0)
        self.assertTrue(any("v1-вход" in w for w in warns))

    def test_v1_input_custom_horizons_arg(self):
        scen = {"A": {"p": 1.0, "factors": {"brent": -10}}}
        pp, _, _ = m.compute_per_position(self.SNAP, scen, self.PRIORS, "priors",
                                          horizons=[12, 24])
        self.assertEqual(set(pp["AAA"]["by_horizon"]), {"h12", "h24"})

    def test_ci_inflation_widens_horizon(self):
        scen = {"A": {"p": 1.0, "factors_by_horizon": {"h12": {"brent": -10}, "h36": {"brent": -10}}}}
        pp, _, _ = m.compute_per_position(
            self.SNAP, scen, self.PRIORS, "priors",
            horizon_ci_inflation={"h36": 2.0},
        )
        bh = pp["AAA"]["by_horizon"]
        ci12 = bh["h12"]["delta_pct_by_scenario"]["A"]["ci_pct"]
        ci36 = bh["h36"]["delta_pct_by_scenario"]["A"]["ci_pct"]
        w12 = ci12[1] - ci12[0]
        w36 = ci36[1] - ci36[0]
        # h36 CI вдвое шире (одинаковая дельта, inflation 2.0)
        self.assertAlmostEqual(w36, w12 * 2.0, places=2)

    def test_money_market_by_horizon(self):
        snap = {"as_of_date": "2026-06-15",
                "holdings": [{"ticker": "TMON", "asset_type": "stock", "value_rub": 50000}]}
        scen = {"A": {"p": 1.0, "factors_by_horizon": {"h12": {"brent": -10}, "h36": {"brent": -30}}}}
        pp, _, _ = m.compute_per_position(snap, scen, {}, "priors")
        bh = pp["TMON"]["by_horizon"]
        self.assertEqual(set(bh), {"h12", "h36"})
        # money-market нечувствителен → delta 0 на всех горизонтах
        self.assertEqual(bh["h12"]["delta_pct_by_scenario"]["A"]["value"], 0.0)
        self.assertEqual(bh["h36"]["delta_pct_by_scenario"]["A"]["value"], 0.0)


# ───────────────────────── CBR history (инъекция _get) ─────────────────────────

class TestCBRRateHistory(unittest.TestCase):
    def test_step_function_to_monthly_diffs(self):
        # ставка: 16.0 до марта, потом 14.5 → Δ для марта = −1.5
        def fake_get(frm, to):
            return [("2026-01-15", 16.0), ("2026-02-14", 16.0),
                    ("2026-03-20", 14.5), ("2026-04-25", 14.5)]
        d = m.fetch_cbr_rate_history(months=3, ref=(2026, 4), _get=fake_get)
        # окно: фев, мар, апр (+1 = янв старт)
        self.assertAlmostEqual(d.get("2026-03", 0.0), -1.5)
        self.assertAlmostEqual(d.get("2026-04", 0.0), 0.0)

    def test_empty_raises(self):
        with self.assertRaises(IOError):
            m.fetch_cbr_rate_history(months=3, ref=(2026, 4), _get=lambda f, t: [])


# ───────────────────────── Пагинация ISS history ─────────────────────────

class TestISSPagination(unittest.TestCase):
    def test_collects_all_pages(self):
        # эмулируем 2.5 страницы (250 строк) по 100
        def fake_get(url):
            start = int(url.split("start=")[1])
            page = [["TQBR", f"2026-01-{i:02d}", 100.0] for i in range(100)]
            if start >= 250:
                return {"history": {"columns": ["BOARDID", "TRADEDATE", "CLOSE"], "data": []}}
            n = min(100, 250 - start)
            return {"history": {"columns": ["BOARDID", "TRADEDATE", "CLOSE"],
                                "data": page[:n]}}
        out = m._iss_history_all("http://x?q=1", _get=fake_get)
        self.assertEqual(len(out["history"]["data"]), 250)

    def test_stops_on_short_page(self):
        def fake_get(url):
            return {"history": {"columns": ["BOARDID", "TRADEDATE", "CLOSE"],
                                "data": [["TQBR", "2026-01-01", 1.0]]}}  # < PAGESIZE
        out = m._iss_history_all("http://x", _get=fake_get)
        self.assertEqual(len(out["history"]["data"]), 1)


# ───────────────────────── CBR currency (инъекция _get) ─────────────────────

class TestCBRCurrencyHistory(unittest.TestCase):
    def test_monthly_returns_from_cbr(self):
        def fake_get(frm, to):
            return [("2026-02-26", 80.0), ("2026-02-27", 80.0),
                    ("2026-03-30", 88.0), ("2026-03-31", 88.0)]
        r = m.fetch_cbr_currency_history("R01235", months=2, ref=(2026, 3), _get=fake_get)
        self.assertAlmostEqual(r["2026-03"], 10.0)  # 80→88 = +10%

    def test_empty_raises(self):
        with self.assertRaises(IOError):
            m.fetch_cbr_currency_history("R01235", months=2, ref=(2026, 3),
                                        _get=lambda f, t: [])


# ───────────────────────── build_factor_matrix (мокнутые fetch'еры) ──────────

class TestBuildFactorMatrix(unittest.TestCase):
    def test_skips_failed_factor(self):
        def good():
            return {"2026-01": 1.0, "2026-02": 2.0}

        def bad():
            raise IOError("down")
        matrix = m.build_factor_matrix(24, (2026, 5), fetchers={
            "brent": good, "usdrub": bad, "cnyrub": good, "cbr_rate": bad,
        })
        self.assertIn("brent", matrix)
        self.assertIn("cnyrub", matrix)
        self.assertNotIn("usdrub", matrix)   # упал → пропущен
        self.assertNotIn("cbr_rate", matrix)

    def test_all_failed_returns_empty(self):
        def bad():
            raise IOError("down")
        matrix = m.build_factor_matrix(24, (2026, 5), fetchers={
            "brent": bad, "usdrub": bad, "cnyrub": bad, "cbr_rate": bad})
        self.assertEqual(matrix, {})


# ───────────────────────── priors-режим неизменность ─────────────────────────

class TestPriorsModeUnchanged(unittest.TestCase):
    def test_priors_mode_still_works(self):
        snap = {"as_of_date": "2026-05-28", "holdings": [
            {"ticker": "SBER", "asset_type": "stock", "value_rub": 100000}]}
        scen = {"A": {"p": 0.5, "factors": {"brent": -10, "cbr_rate": -3.5}},
                "B": {"p": 0.5, "factors": {"brent": 5}}}
        priors = {"SBER": {"factor_betas": {"brent": 0.15, "cbr_rate": -0.2},
                           "factor_betas_method": "sector prior"}}
        pp, warns, unm = m.compute_per_position(snap, scen, priors, "priors")
        self.assertIn("SBER", pp)
        self.assertIsNone(pp["SBER"]["factor_betas_r2"])  # priors → r2 null
        self.assertEqual(pp["SBER"]["factor_betas"]["brent"], 0.15)


# ───────────────────── Maturity guard (Слой 1 total-return) ─────────────────────

class TestMaturityGuard(unittest.TestCase):
    """price_delta облигаций, гасящихся/с офертой внутри горизонта, обнуляется
    (лайфцикл — Слой 2 compute_bond_carry); акции/длинные бумаги не трогаются."""

    SCEN = {
        "A": {"p": 0.5, "factors_by_horizon": {
            "h6": {"cbr_rate": -1.0}, "h12": {"cbr_rate": -2.0},
            "h24": {"cbr_rate": -4.0}}},
        "B": {"p": 0.5, "factors_by_horizon": {
            "h6": {"cbr_rate": 0.0}, "h12": {"cbr_rate": 0.0},
            "h24": {"cbr_rate": 0.0}}},
    }
    ENDS = {"h6": "2026-12-31", "h12": "2027-06-30", "h24": "2028-06-30"}
    PRIORS = {
        "SHORTB": {"factor_betas": {"cbr_rate": -3.0}, "factor_betas_method": "OFZ duration 3yr"},
        "OFFERB": {"factor_betas": {"cbr_rate": -3.0}, "factor_betas_method": "corp"},
        "LONGB": {"factor_betas": {"cbr_rate": -5.0}, "factor_betas_method": "OFZ duration 5yr"},
        "STK": {"factor_betas": {"cbr_rate": 0.3}, "factor_betas_method": "sector prior"},
    }

    def _snap(self, holdings, as_of="2026-07-02"):
        return {"as_of_date": as_of, "holdings": holdings}

    def _bond(self, ticker, maturity=None, offer=None, **kw):
        base = {"ticker": ticker, "asset_type": "bond", "value_rub": 100000,
                "maturity_date": maturity, "offer_date": offer}
        base.update(kw)
        return base

    def test_bond_maturing_inside_horizon_zeroed(self):
        """Гасится 2027-04-01: h6 живой (беты работают), h12/h24 — нули + флаг."""
        snap = self._snap([self._bond("SHORTB", maturity="2027-04-01")])
        pp, warns, _ = m.compute_per_position(
            snap, self.SCEN, self.PRIORS, "priors", horizon_ends=self.ENDS)
        bh = pp["SHORTB"]["by_horizon"]
        # h6: обычный расчёт (β=-3 × Δ=-1 → +3 в A)
        self.assertEqual(bh["h6"]["delta_pct_by_scenario"]["A"]["value"], 3.0)
        self.assertNotIn("price_delta_zeroed", bh["h6"])
        # h12/h24: нули + флаг + t_live
        for hk in ("h12", "h24"):
            self.assertEqual(bh[hk]["price_delta_zeroed"], "maturity_within_horizon")
            for sid in ("A", "B"):
                self.assertEqual(bh[hk]["delta_pct_by_scenario"][sid]["value"], 0.0)
                self.assertEqual(bh[hk]["delta_pct_by_scenario"][sid]["ci_pct"], [0.0, 0.0])
            self.assertEqual(bh[hk]["expected_pct_pweighted"]["value"], 0.0)
            self.assertEqual(bh[hk]["tail_var_pct"], 0.0)
        self.assertAlmostEqual(bh["h12"]["t_live_months"], 8.97, delta=0.05)
        self.assertTrue(any("Maturity guard" in w and "SHORTB" in w for w in warns))

    def test_offer_treated_as_event(self):
        """Оферта раньше погашения → guard по оферте (консервативно)."""
        snap = self._snap([self._bond("OFFERB", maturity="2031-01-01",
                                      offer="2026-12-15")])
        pp, _, _ = m.compute_per_position(
            snap, self.SCEN, self.PRIORS, "priors", horizon_ends=self.ENDS)
        bh = pp["OFFERB"]["by_horizon"]
        for hk in ("h6", "h12", "h24"):
            self.assertIn("price_delta_zeroed", bh[hk])

    def test_long_bond_and_stock_untouched(self):
        """Длинная облигация и акция (даже с maturity-полем) не обнуляются."""
        snap = self._snap([
            self._bond("LONGB", maturity="2031-01-01"),
            {"ticker": "STK", "asset_type": "stock", "value_rub": 100000,
             "maturity_date": "2026-08-01"},   # мусорное поле у акции
        ])
        pp, warns, _ = m.compute_per_position(
            snap, self.SCEN, self.PRIORS, "priors", horizon_ends=self.ENDS)
        for t in ("LONGB", "STK"):
            for hk in ("h6", "h12", "h24"):
                self.assertNotIn("price_delta_zeroed", pp[t]["by_horizon"][hk])
        self.assertFalse(any("Maturity guard:" in w for w in warns))

    def test_fallback_horizon_ends_from_as_of(self):
        """Без явных horizon_ends даты выводятся из as_of_date + NN (конец месяца)."""
        snap = self._snap([self._bond("SHORTB", maturity="2027-01-15")])
        pp, _, _ = m.compute_per_position(snap, self.SCEN, self.PRIORS, "priors")
        bh = pp["SHORTB"]["by_horizon"]
        # as_of 2026-07-02 + 6 мес → 2027-01-31 ≥ 2027-01-15 → h6 обнулён
        self.assertIn("price_delta_zeroed", bh["h6"])
        self.assertIn("price_delta_zeroed", bh["h12"])

    def test_guard_disabled_without_dates_warns(self):
        """Нет as_of_date и нет horizon_ends → guard отключён с явным warning."""
        snap = {"holdings": [self._bond("SHORTB", maturity="2027-01-15")]}
        pp, warns, _ = m.compute_per_position(snap, self.SCEN, self.PRIORS, "priors")
        self.assertNotIn("price_delta_zeroed", pp["SHORTB"]["by_horizon"]["h12"])
        self.assertTrue(any("Maturity guard ОТКЛЮЧЁН" in w for w in warns))

    def test_v1_wrapped_input_guard_applies(self):
        """v1-вход (плоский factors → обёртка h20): guard работает и там."""
        scen_v1 = {"A": {"p": 1.0, "factors": {"cbr_rate": -2.0}}}
        snap = self._snap([self._bond("SHORTB", maturity="2027-04-01")])
        pp, _, _ = m.compute_per_position(snap, scen_v1, self.PRIORS, "priors")
        # h20: as_of + 20 мес = 2028-03-31 ≥ 2027-04-01 → обнулён
        self.assertIn("price_delta_zeroed", pp["SHORTB"]["by_horizon"]["h20"])


HAS_YAML = True
try:
    import yaml  # noqa: F401
except ImportError:
    HAS_YAML = False


@unittest.skipUnless(HAS_YAML, "CLI-прогон читает scenarios через PyYAML")


class TestCLIExitCode(unittest.TestCase):
    """Отказ контракта — код 2, как остальные отказы main(), и без выходного файла."""

    def _run(self, priors_obj, tmp):
        import json as _json
        import subprocess
        snap = tmp / "snap.json"
        snap.write_text(_json.dumps({"as_of_date": "2026-07-02", "holdings": [
            {"ticker": "AAA", "asset_type": "stock", "value_rub": 100000}]}))
        scen = tmp / "scen.yaml"
        scen.write_text("scenarios:\n  D:\n    p: 1.0\n    factors:\n      sanctions: -0.9\n")
        pri = tmp / "priors.json"
        pri.write_text(_json.dumps(priors_obj))
        out = tmp / "frag.yaml"
        out.write_text("stale: true\n")
        script = os.path.join(os.path.dirname(__file__), "..", "scripts",
                              "compute_per_position.py")
        # encoding/PYTHONIOENCODING заданы явно: под LC_ALL=C дочерний процесс
        # падал бы на кириллице в сообщениях, а не на проверяемом поведении.
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        r = subprocess.run([sys.executable, script, "--snapshot", str(snap),
                            "--scenarios", str(scen), "--priors", str(pri),
                            "--output", str(out)], capture_output=True, text=True,
                           encoding="utf-8", env=env)
        return r, out

    def test_scale_refusal_returns_2_and_removes_stale_output(self):
        import tempfile
        from pathlib import Path as _P
        with tempfile.TemporaryDirectory() as d:
            tmp = _P(d)
            r, out = self._run(
                {"AAA": {"factor_betas": {"sanctions": -0.35}, "asset_type": "stock"}}, tmp)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("ШКАЛА", r.stderr)
            self.assertFalse(out.exists(), "устаревший фрагмент остался на диске")

    def test_output_colliding_with_input_refused(self):
        import tempfile
        from pathlib import Path as _P
        import json as _json
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            tmp = _P(d)
            snap = tmp / "snap.json"
            snap.write_text(_json.dumps({"as_of_date": "2026-07-02", "holdings": []}))
            scen = tmp / "scen.yaml"
            scen.write_text("scenarios:\n  D:\n    p: 1.0\n    factors: {}\n")
            pri = tmp / "priors.json"
            pri.write_text("{}")
            script = os.path.join(os.path.dirname(__file__), "..", "scripts",
                                  "compute_per_position.py")
            env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
            r = subprocess.run([sys.executable, script, "--snapshot", str(snap),
                                "--scenarios", str(scen), "--priors", str(pri),
                                "--output", str(pri)], capture_output=True, text=True,
                               encoding="utf-8", env=env)
            self.assertEqual(r.returncode, 2)
            self.assertIn("совпадает с --priors", r.stderr)
            self.assertEqual(pri.read_text(), "{}")   # входной файл цел

    def test_priors_not_dict_returns_2(self):
        import tempfile
        from pathlib import Path as _P
        with tempfile.TemporaryDirectory() as d:
            r, _ = self._run([{"AAA": {}}], _P(d))
            self.assertEqual(r.returncode, 2)
            self.assertIn("должен быть JSON-объектом", r.stderr)

    def test_valid_run_returns_0_and_writes_output(self):
        import tempfile
        from pathlib import Path as _P
        with tempfile.TemporaryDirectory() as d:
            tmp = _P(d)
            r, out = self._run(
                {"AAA": {"factor_betas": {"sanctions": -35}, "asset_type": "stock"}}, tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(out.exists())


class TestSplitAccountLegs(unittest.TestCase):
    """
    Бумага, разложенная по счетам (main + iis_3), — одна запись per_position.

    Регрессия 2026-08-04: `per_position[ticker] = entry` затирал первую ногу
    второй, и ОФЗ 26238 (80 шт main + 130 шт ИИС-3) публиковалась весом ноги
    ИИС — 0.5358% вместо 0.8656%. Гард покрытия молчал: он считал по членству
    тикера, а тикер был на месте.
    """

    SCEN = {"A": {"p": 1.0, "factors_by_horizon": {"h12": {"brent": 10.0}}}}
    PRIORS = {"OFZ": {"factor_betas": {"brent": 1.0}, "factor_betas_method": "prior"}}

    @staticmethod
    def _leg(account, value, **kw):
        leg = {"ticker": "OFZ", "isin": "RU000A1038V6", "asset_type": "bond",
               "value_rub": value, "account": account}
        leg.update(kw)
        return leg

    # ── merge_holding_legs: единица ──

    def test_legs_sum_into_one_record(self):
        merged, warns, dropped = m.merge_holding_legs([
            self._leg("main", 44255.2, qty=80),
            self._leg("iis_3", 71914.7, qty=130),
        ])
        self.assertEqual(len(merged), 1)
        self.assertAlmostEqual(merged[0]["value_rub"], 116169.9, places=2)
        self.assertEqual(merged[0]["qty"], 210)
        self.assertEqual(dropped, [])
        # Предупреждение обязано назвать полную сумму и обе ноги — иначе
        # схлопывание невидимо и его нельзя сверить с флагом загрузчика.
        self.assertEqual(len(warns), 1, warns)
        for part in (f"{116169.9:,.0f}", f"{44255.2:,.0f}", f"{71914.7:,.0f}",
                     "main", "iis_3"):
            self.assertIn(part, warns[0])

    def test_on_iis_true_when_any_leg_on_iis(self):
        merged, _, _ = m.merge_holding_legs([
            self._leg("main", 44255.2), self._leg("iis_3", 71914.7)])
        self.assertIs(merged[0]["on_iis"], True)
        # Поле account у объединённой записи было бы ложью — счёт больше не один.
        self.assertNotIn("account", merged[0])

    def test_on_iis_true_when_iis_leg_is_the_smaller_one(self):
        """
        Контракт — «хотя бы одна нога на ИИС-3» (output-template.md), а не «нога,
        попавшая в базу объединения». Основной счёт крупнее ИИС-транша чаще, чем
        наоборот, и тогда взгляд на одну ногу тихо снимает метку ❄ с позиции,
        которую нельзя продавать.
        """
        merged, _, _ = m.merge_holding_legs([
            self._leg("main", 900000.0), self._leg("iis_3", 1000.0)])
        self.assertAlmostEqual(merged[0]["value_rub"], 901000.0)
        self.assertIs(merged[0]["on_iis"], True)

    def test_on_iis_false_when_no_leg_on_iis(self):
        merged, _, _ = m.merge_holding_legs([
            self._leg("main", 1000.0), self._leg("broker_2", 2000.0)])
        self.assertIs(merged[0]["on_iis"], False)

    def test_single_leg_passes_through_unchanged(self):
        leg = self._leg("iis_3", 500.0, qty=5)
        merged, warns, dropped = m.merge_holding_legs([leg])
        self.assertEqual(merged, [leg])
        self.assertIs(merged[0], leg)          # не копия — ничего не переписано
        self.assertEqual((warns, dropped), ([], []))

    def test_blocked_leg_excluded_from_sum(self):
        merged, _, _ = m.merge_holding_legs([
            self._leg("main", 44255.2),
            self._leg("iis_3", 71914.7, is_blocked=True),
        ])
        self.assertEqual(len(merged), 1)
        self.assertAlmostEqual(merged[0]["value_rub"], 44255.2, places=2)
        self.assertIs(merged[0].get("on_iis", False), False)

    def test_qty_left_alone_when_a_leg_has_none(self):
        merged, _, _ = m.merge_holding_legs([
            self._leg("main", 100.0, qty=1), self._leg("iis_3", 200.0)])
        self.assertAlmostEqual(merged[0]["value_rub"], 300.0)
        self.assertNotEqual(merged[0].get("qty"), 1)   # не выдаём часть за целое

    def test_homonym_tickers_are_not_merged(self):
        big = {"ticker": "T", "isin": "RU000TTECH", "asset_type": "stock", "value_rub": 900.0}
        small = {"ticker": "T", "isin": "US00206R1023", "asset_type": "stock", "value_rub": 100.0}
        merged, warns, dropped = m.merge_holding_legs([small, big])
        self.assertEqual(len(merged), 1)
        self.assertAlmostEqual(merged[0]["value_rub"], 900.0)   # сложения не было
        self.assertEqual(len(dropped), 1)
        self.assertEqual(dropped[0]["ticker"], "T")
        self.assertIn("US00206R1023", dropped[0]["reason"])
        self.assertTrue(any("разные бумаги" in w for w in warns), warns)

    def test_order_of_first_leg_is_kept(self):
        other = {"ticker": "AAA", "asset_type": "stock", "value_rub": 10.0}
        merged, _, _ = m.merge_holding_legs([
            self._leg("main", 1.0), other, self._leg("iis_3", 2.0)])
        self.assertEqual([h["ticker"] for h in merged], ["OFZ", "AAA"])

    def test_record_without_ticker_survives_for_unmapped(self):
        anon = {"ticker": None, "asset_type": "stock", "value_rub": 7.0, "id": "x1"}
        merged, _, _ = m.merge_holding_legs([anon])
        self.assertEqual(merged, [anon])

    # ── e2e через compute_per_position ──

    def _snap(self):
        return {"as_of_date": "2026-08-04", "holdings": [
            self._leg("main", 44255.2, qty=80),
            self._leg("iis_3", 71914.7, qty=130),
            {"ticker": "AAA", "isin": "RU000AAA", "asset_type": "stock",
             "value_rub": 883830.1},
        ]}

    def test_weight_pct_covers_both_legs(self):
        priors = dict(self.PRIORS)
        priors["AAA"] = {"factor_betas": {"brent": 1.0}, "factor_betas_method": "prior"}
        pp, warns, unmapped = m.compute_per_position(
            self._snap(), self.SCEN, priors, "priors")
        # 116 169.9 из 1 000 000 → 11.617%, а не 7.191% (одна нога ИИС)
        self.assertAlmostEqual(pp["OFZ"]["weight_pct"], 11.617, places=2)
        self.assertIs(pp["OFZ"]["on_iis"], True)
        self.assertEqual(unmapped, [])
        # Суммарный вес не теряет ни рубля.
        self.assertAlmostEqual(
            sum(e["weight_pct"] for e in pp.values()), 100.0, places=2)

    def test_coverage_guard_counts_published_value(self):
        # У AAA нет priors → её стоимость в per_position не попадает.
        pp, warns, unmapped = m.compute_per_position(
            self._snap(), self.SCEN, self.PRIORS, "priors")
        self.assertNotIn("AAA", pp)
        cov = [w for w in warns if "Покрытие per_position" in w]
        self.assertTrue(cov, warns)
        self.assertIn("11.6%", cov[0])          # опубликовано 116 169.9 из 1 000 000

    def test_coverage_sees_value_lost_to_ticker_collision(self):
        """
        Ключ `per_position` один на тикер, поэтому вторая бумага-омоним в расчёт
        не идёт. Считая покрытие по ЧЛЕНСТВУ тикера, гард засчитывал бы её
        стоимость как покрытую — тикер-то в словаре есть — и молчал при 100%.
        """
        snap = {"as_of_date": "2026-08-04", "holdings": [
            {"ticker": "T", "isin": "RU000TTECH", "asset_type": "stock", "value_rub": 900.0},
            {"ticker": "T", "isin": "US00206R1023", "asset_type": "stock", "value_rub": 100.0},
        ]}
        priors = {"T": {"factor_betas": {"brent": 1.0}, "factor_betas_method": "prior"}}
        pp, warns, unmapped = m.compute_per_position(snap, self.SCEN, priors, "priors")
        self.assertAlmostEqual(pp["T"]["weight_pct"], 90.0, places=2)
        self.assertEqual(len(unmapped), 1)
        cov = [w for w in warns if "Покрытие per_position" in w]
        self.assertTrue(cov, warns)
        self.assertIn("90.0%", cov[0])

    def test_coverage_silent_when_split_position_merged(self):
        snap = {"as_of_date": "2026-08-04", "holdings": [
            self._leg("main", 44255.2, qty=80), self._leg("iis_3", 71914.7, qty=130)]}
        _, warns, _ = m.compute_per_position(snap, self.SCEN, self.PRIORS, "priors")
        self.assertFalse([w for w in warns if "Покрытие per_position" in w], warns)


class TestFactorAwareCI(unittest.TestCase):
    """
    P2-4: ширина CI зависит от того, КАКОЙ фактор двинул цену, а не только от величины
    движения. Санкционная бета откалибрована на одном эпизоде, ставочная — это дюрация
    и арифметика; давать им одинаковый относительный интервал неверно направленно.
    """

    def test_legacy_branch_unchanged(self):
        for delta in (0.0, 8.0, 45.86):
            self.assertEqual(m.ci_from_delta(delta, None),
                             m.ci_from_delta(delta, None, None))
        # пол работает: |delta|*0.4 < 5 при delta < 12.5
        self.assertEqual(m.ci_from_delta(8.0, None), (3.0, 13.0))
        self.assertEqual(m.ci_from_delta(45.86, None), (27.52, 64.2))

    def test_low_uncertainty_factor_gives_narrower_ci(self):
        wide = m.ci_from_delta(30.0, None, {"sanctions": 30.0})
        narrow = m.ci_from_delta(30.0, None, {"cbr_rate": 30.0})
        self.assertGreater(wide[1] - wide[0], narrow[1] - narrow[0])

    def test_quadratic_not_linear_sum(self):
        """
        [РАЗЛИЧИТЕЛЬ] Свёртка квадратичная, а не сумма модулей.
        Два вклада по 30 п.п. с u=0.6: sqrt(18^2+18^2) = 25.46 против 36.0 у суммы.
        """
        lo, hi = m.ci_from_delta(0.0, None, {"sanctions": 30.0, "geopol": 30.0})
        self.assertAlmostEqual((hi - lo) / 2, 25.46, places=2)

    def test_uncertainty_is_per_factor_not_per_cell(self):
        """
        [РАЗЛИЧИТЕЛЬ] u применяется К КАЖДОМУ вкладу, а не один множитель на ячейку.

        Вклады равны по величине, но u разные: sqrt((30*0.6)^2 + (30*0.2)^2) = 18.97.
        Фейк max(u)*sqrt(sum c^2) = 0.6*42.43 = 25.46 проходит все однофакторные тесты
        и тест выше (там оба u равны 0.6), а на живых данных расходится с верной
        формулой на 59% ячеек, до 14.93 п.п.
        """
        lo, hi = m.ci_from_delta(0.0, None, {"sanctions": 30.0, "cbr_rate": 30.0})
        self.assertAlmostEqual((hi - lo) / 2, 18.97, places=2)

    def test_sber_like_and_ofz_like(self):
        lo, hi = m.ci_from_delta(45.86, None, {"sanctions": 31.5, "geopol": 18.0})
        self.assertTrue(21.5 <= (hi - lo) / 2 <= 22.1, (hi - lo) / 2)
        lo, hi = m.ci_from_delta(17.6, None, {"cbr_rate": 17.15})
        self.assertAlmostEqual((hi - lo) / 2, 5.0, places=6)   # 3.43 -> пол

    def test_floor_on_zero_contributions(self):
        lo, hi = m.ci_from_delta(0.0, None, {"brent": 0.0})
        self.assertEqual((lo, hi), (-5.0, 5.0))

    def test_unknown_factor_uses_default_not_zero(self):
        lo, hi = m.ci_from_delta(0.0, None, {"unknown_factor": 100.0})
        self.assertAlmostEqual((hi - lo) / 2, 60.0, places=6)

    def test_contributions_sum_exactly_to_value(self):
        betas = {"sanctions": -35.0, "geopol": -20.0, "cbr_rate": -0.12,
                 "usdrub": -0.05, "brent": 0.1}
        factors = {"sanctions": -0.9, "geopol": -0.9, "cbr_rate": -2.85,
                   "usdrub": 44.95, "brent": -25.26}
        total, contrib = m.compute_delta_pct(betas, factors, 0.9,
                                             with_contributions=True)
        # Побитового равенства тут НЕТ и требовать его нельзя: sum() накапливает
        # float иначе, чем `+=` в цикле, даже при одинаковом порядке ключей
        # (45.0685 против 45.06849999999999). Расхождение ~1e-14 и на округление
        # центра до сотых не влияет — эталонный прогон не сдвинул ни одну из 632 ячеек.
        self.assertAlmostEqual(sum(contrib.values()), total, places=9)
        # А вот два пути самой функции обязаны совпасть побитово: это один и тот же
        # цикл накопления.
        self.assertEqual(m.compute_delta_pct(betas, factors, 0.9), total)

    def test_contribution_uses_clamped_move(self):
        """Вклад строится на состоявшемся ходе, а не на номинальной интенсивности."""
        _, contrib = m.compute_delta_pct({"sanctions": -35.0}, {"sanctions": 0.7},
                                         0.9, with_contributions=True)
        self.assertAlmostEqual(contrib["sanctions"], -3.5, places=9)

    SCEN = {"A": {"p": 1.0, "factors_by_horizon": {"h12": {"sanctions": -0.9,
                                                           "cbr_rate": -2.0}}}}
    PRIORS = {"BANK": {"factor_betas": {"sanctions": -35.0, "cbr_rate": -0.12},
                       "sanctions_position": 0.9, "asset_type": "stock",
                       "factor_betas_method": "prior"}}
    SNAP = {"as_of_date": "2026-08-04",
            "holdings": [{"ticker": "BANK", "asset_type": "stock", "value_rub": 1000}]}

    def test_wired_into_build_by_horizon(self):
        """
        [РАЗЛИЧИТЕЛЬ] Разложение реально доехало до расчёта ячейки.

        Реализация с идеальными ci_from_delta/compute_delta_pct и НЕТРОНУТОЙ строкой
        вызова проходит все юнит-тесты выше, не меняя ни одной ячейки артефакта.
        Здесь: вклад sanctions = -0.9*(-35) = +31.5, cbr = -2*(-0.12) = +0.24;
        факторный CI = sqrt((31.5*0.6)^2 + (0.24*0.2)^2) = 18.90.
        Легаси дал бы max(31.74*0.4, 5) = 12.70 — числа заведомо разные.
        """
        pp, _, _ = m.compute_per_position(self.SNAP, self.SCEN, self.PRIORS, "priors")
        cell = pp["BANK"]["by_horizon"]["h12"]["delta_pct_by_scenario"]["A"]
        self.assertAlmostEqual((cell["ci_pct"][1] - cell["ci_pct"][0]) / 2, 18.90,
                               places=1)

    def test_r2_present_falls_back_to_legacy(self):
        """
        [РАЗЛИЧИТЕЛЬ] При наличии r2 априорные множители НЕ накладываются поверх
        эмпирической 1/sqrt(r2): один источник неопределённости учтён бы дважды.
        """
        priors = {"BANK": dict(self.PRIORS["BANK"], factor_betas_r2=0.5)}
        pp, _, _ = m.compute_per_position(self.SNAP, self.SCEN, priors, "priors")
        cell = pp["BANK"]["by_horizon"]["h12"]["delta_pct_by_scenario"]["A"]
        half = (cell["ci_pct"][1] - cell["ci_pct"][0]) / 2
        legacy = max(abs(cell["value"]) * 0.4, 5.0) * min(1 / 0.5 ** 0.5, 3.0)
        self.assertAlmostEqual(half, legacy, places=1)

    def test_money_market_and_zeroed_cells_untouched(self):
        snap = {"as_of_date": "2026-08-04",
                "holdings": [{"ticker": "TMON", "asset_type": "stock", "value_rub": 100}]}
        pp, _, _ = m.compute_per_position(snap, self.SCEN, {}, "priors")
        self.assertEqual(pp["TMON"]["by_horizon"]["h12"]["delta_pct_by_scenario"]["A"]
                         ["ci_pct"], [-1.0, 1.0])

    def test_contributions_do_not_leak_into_output(self):
        pp, _, _ = m.compute_per_position(self.SNAP, self.SCEN, self.PRIORS, "priors")
        cell = pp["BANK"]["by_horizon"]["h12"]["delta_pct_by_scenario"]["A"]
        self.assertEqual(set(cell), {"value", "ci_pct"})


class TestIdiosyncraticListSync(unittest.TestCase):
    """Сторож: константа IDIOSYNCRATIC_TICKERS == таблица references/idiosyncratic-tickers.md."""

    def test_code_list_matches_reference_table(self):
        import re
        ref = os.path.join(os.path.dirname(__file__), "..", "references", "idiosyncratic-tickers.md")
        with open(ref, encoding="utf-8") as fh:
            text = fh.read()
        section = text.split("## Текущий список", 1)[1].split("\n---", 1)[0]
        in_doc = set(re.findall(r"^\|\s*\*\*([A-Z0-9]+)\*\*", section, re.M))
        self.assertTrue(in_doc, "таблица тикеров в references не распознана")
        self.assertEqual(in_doc, set(m.IDIOSYNCRATIC_TICKERS),
                         "списки разошлись: править references/idiosyncratic-tickers.md "
                         "и IDIOSYNCRATIC_TICKERS в compute_per_position.py вместе")


if __name__ == "__main__":
    unittest.main()
