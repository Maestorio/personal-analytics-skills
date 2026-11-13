#!/usr/bin/env python3
"""
test_input_contract.py — гарды контракта входа стресс-теста (PSS-7).

Предмет: `input_contract.py` — канонические константы, отбор holdings,
классификация класса актива и шесть гардов (структура priors, числовая
валидность бет, шкала политических бет, позиция на санкционной шкале,
горизонтный путь дилов, веса сценариев).

Классы перенесены из `test_compute_per_position.py` ЦЕЛИКОМ, вместе с теми
методами, что проверяют подключение гарда к движку через
`compute_per_position` — гард без проводки бесполезен, и разделять эти
проверки по файлам значило бы резать связный класс пополам. Поэтому здесь
импортируются оба модуля: `g` — предмет тестов, `m` — движок для проводки.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import compute_per_position as m  # noqa: E402  (проводка гардов в движок)
import input_contract as g  # noqa: E402  (предмет тестов)

HAS_YAML = True
try:
    import yaml  # noqa: F401
except ImportError:
    HAS_YAML = False


class TestPoliticalBetaScaleGuard(unittest.TestCase):
    """P0-1: контракт единиц политических бет (β — п.п. на 1.0 интенсивности).

    Реальный дефект: прогоны 2026-07-15/23 записали SBER β_sanctions=-0.35
    (долевая шкала) → полная разрядка дала +0.32 п.п. вместо +31.5, и порядок
    сценариев перевернулся (эскалация «лучше» большой сделки). Прогон 2026-07-02
    на тех же данных стоял в п.п.-шкале (-12.0). Гард ловит обе стороны.
    """

    SNAP = {"as_of_date": "2026-07-02", "holdings": [
        {"ticker": "AAA", "asset_type": "stock", "value_rub": 100000},
    ]}
    SCEN = {"A": {"p": 1.0, "factors": {"sanctions": -0.9, "cbr_rate": -2.0}}}

    @staticmethod
    def _priors(sanctions, geopol=0.0, asset_type="stock"):
        return {"AAA": {"factor_betas": {"sanctions": sanctions, "geopol": geopol,
                                         "cbr_rate": -0.2},
                        "factor_betas_method": "sector prior",
                        "asset_type": asset_type}}

    def test_fraction_scale_rejected(self):
        with self.assertRaises(SystemExit) as cm:
            m.compute_per_position(self.SNAP, self.SCEN, self._priors(-0.35, -0.20),
                                   "priors")
        msg = str(cm.exception)
        self.assertIn("ШКАЛА ПОЛИТИЧЕСКИХ БЕТ", msg)
        self.assertIn("умножь ИХ на 100", msg)

    def test_pp_scale_accepted(self):
        pp, warns, _ = m.compute_per_position(
            self.SNAP, self.SCEN, self._priors(-35, -20), "priors")
        self.assertEqual(pp["AAA"]["factor_betas"]["sanctions"], -35)
        self.assertFalse([w for w in warns if "ШКАЛА" in w])

    def test_pp_scale_moves_position_materially(self):
        """Смысл гарда: в п.п.-шкале дил -0.9 реально двигает бумагу."""
        pp, _, _ = m.compute_per_position(
            self.SNAP, self.SCEN, self._priors(-35), "priors")
        delta = pp["AAA"]["by_horizon"]["h20"]["delta_pct_by_scenario"]["A"]["value"]
        # -35 × -0.9 = +31.5 плюс cbr_rate (-0.2 × -2.0 = +0.4)
        self.assertAlmostEqual(delta, 31.9, places=2)

    def test_warn_mode_computes_and_flags(self):
        pp, warns, _ = m.compute_per_position(
            self.SNAP, self.SCEN, self._priors(-0.35), "priors",
            political_scale_check="warn")
        self.assertIn("AAA", pp)
        self.assertTrue([w for w in warns if "ШКАЛА ПОЛИТИЧЕСКИХ БЕТ" in w])

    def test_off_mode_silent(self):
        pp, warns, _ = m.compute_per_position(
            self.SNAP, self.SCEN, self._priors(-0.35), "priors",
            political_scale_check="off")
        self.assertIn("AAA", pp)
        self.assertFalse([w for w in warns if "ШКАЛА" in w])

    def test_all_zero_political_is_warning_not_error(self):
        """Нулевой политический канал — законный (но подозрительный) выбор."""
        pp, warns, _ = m.compute_per_position(
            self.SNAP, self.SCEN, self._priors(0.0, 0.0), "priors")
        self.assertIn("AAA", pp)
        self.assertTrue([w for w in warns if "полностью нулевой" in w])

    def test_absurdly_large_beta_rejected(self):
        with self.assertRaises(SystemExit) as cm:
            m.compute_per_position(self.SNAP, self.SCEN, self._priors(-3500),
                                   "priors")
        self.assertIn("> 200", str(cm.exception))

    # ── ключевое: проверка ПОКАЗНАЯ, одна верная запись не разоружает гард ──

    def test_partial_migration_caught(self):
        """
        Реальный сценарий ошибки: домножили банки, забыли экспортёров. Раньше гард
        смотрел на максимум по портфелю и такую миграцию пропускал целиком.
        """
        priors = {
            "BANK": {"factor_betas": {"sanctions": -35}, "asset_type": "stock"},
            "EXPO": {"factor_betas": {"sanctions": -0.25}, "asset_type": "stock"},
        }
        errors, _ = m.check_political_beta_scale(priors)
        self.assertTrue(errors)
        self.assertIn("EXPO", errors[0])
        self.assertNotIn("BANK", errors[0])

    def test_bond_small_beta_is_legitimate(self):
        """
        У облигации β = −duration × Δspread/100 законно дробная
        (references/bonds-sensitivity.md §4) — нижний порог к ней не применяется.
        """
        priors = {
            "SU26243": {"factor_betas": {"sanctions": -0.35}, "asset_type": "bond"},
            "RU000A1": {"factor_betas": {"sanctions": -0.30}, "asset_type": "bond_fx"},
        }
        self.assertEqual(m.check_political_beta_scale(priors)[0], [])

    def test_bond_beta_rescaled_by_100_is_caught(self):
        """
        Зеркало нижнего порога: ×100 применяется к долевым, но НЕ к облигациям
        (у них β выводится формулой). Механический пересчёт всего подряд завышает
        долговой канал в ~20 раз, и ни нижний порог, ни общий потолок 200 этого
        не видят.
        """
        priors = {"RU000A105KU0": {"factor_betas": {"sanctions": -8.0},
                                   "asset_type": "bond"}}
        errors, _ = m.check_political_beta_scale(priors)
        self.assertTrue([e for e in errors if "долговых" in e])

    def test_bond_beta_within_formula_range_passes(self):
        for b in (-0.3, -0.4, -3.15, -5.25):
            with self.subTest(beta=b):
                priors = {"SU": {"factor_betas": {"sanctions": b}, "asset_type": "bond"}}
                self.assertEqual(m.check_political_beta_scale(priors)[0], [])

    def test_equity_is_not_subject_to_bond_ceiling(self):
        priors = {"SBER": {"factor_betas": {"sanctions": -35}, "asset_type": "stock"}}
        self.assertEqual(m.check_political_beta_scale(priors)[0], [])

    def test_bond_only_portfolio_runs(self):
        """Облигационный портфель не должен упираться в гард (был ложный отказ)."""
        snap = {"as_of_date": "2026-07-02", "holdings": [
            {"ticker": "SU26243", "asset_type": "bond", "value_rub": 100000}]}
        priors = {"SU26243": {"factor_betas": {"sanctions": -0.35, "cbr_rate": -3.0},
                              "factor_betas_method": "OFZ duration 3yr",
                              "asset_type": "bond"}}
        pp, _, _ = m.compute_per_position(snap, self.SCEN, priors, "priors")
        self.assertIn("SU26243", pp)

    def test_asset_type_from_snapshot_when_absent_in_priors(self):
        holdings = [{"ticker": "SU26243", "asset_type": "bond"}]
        priors = {"SU26243": {"factor_betas": {"sanctions": -0.35}}}
        self.assertEqual(m.check_political_beta_scale(priors, holdings)[0], [])

    def test_unknown_asset_class_warns_not_errors(self):
        priors = {"XXX": {"factor_betas": {"sanctions": -0.35}}}
        errors, warns = m.check_political_beta_scale(priors)
        self.assertEqual(errors, [])
        self.assertTrue([w for w in warns if "Класс актива неоднозначен" in w])

    def test_only_portfolio_tickers_checked(self):
        """Бумага вне снапшота не должна ни ломать прогон, ни фигурировать в тексте."""
        priors = {
            "BONDX": {"factor_betas": {"sanctions": -0.30}, "asset_type": "bond"},
            "GHOST": {"factor_betas": {"sanctions": -0.35}, "asset_type": "stock"},
        }
        holdings = [{"ticker": "BONDX", "asset_type": "bond"}]
        errors, warns = m.check_political_beta_scale(priors, holdings)
        self.assertEqual(errors, [])
        self.assertFalse([x for x in errors + warns if "GHOST" in x])

    def test_nan_beta_rejected(self):
        """nan проходил обе границы и бесшумно отключал проверку шкалы."""
        priors = {"AAA": {"factor_betas": {"sanctions": float("nan")},
                          "asset_type": "stock"}}
        errors = m.check_betas_numeric(priors)
        self.assertTrue([e for e in errors if "не конечное число" in e])

    def test_nan_does_not_mask_other_records(self):
        priors = {
            "NANX": {"factor_betas": {"sanctions": float("nan")}, "asset_type": "stock"},
            "BADS": {"factor_betas": {"sanctions": -0.35}, "asset_type": "stock"},
        }
        errors, _ = m.check_political_beta_scale(priors)
        self.assertTrue([e for e in errors if "BADS" in e])
        self.assertTrue([e for e in m.check_betas_numeric(priors) if "NANX" in e])

    def test_non_numeric_beta_is_error_not_silence(self):
        """Раньше гард молчал, а движок падал трейсбеком на float(beta)."""
        priors = {"AAA": {"factor_betas": {"sanctions": True, "geopol": "high"},
                          "asset_type": "stock"}}
        errors = m.check_betas_numeric(priors)
        self.assertEqual(len(errors), 2)
        self.assertTrue(all("не число" in e for e in errors))
        # владелец числовой проверки один: гард шкалы её не дублирует
        self.assertEqual(m.check_political_beta_scale(priors)[0], [])

    def test_non_numeric_market_beta_stops_run(self):
        priors = {"AAA": {"factor_betas": {"sanctions": -35, "brent": "high"},
                          "factor_betas_method": "x", "asset_type": "stock"}}
        with self.assertRaises(SystemExit) as cm:
            m.compute_per_position(self.SNAP, self.SCEN, priors, "priors")
        self.assertIn("brent", str(cm.exception))

    def test_non_dict_factor_betas_is_error(self):
        errors = m.check_priors_structure({"AAA": {"factor_betas": [["s", -35]]}})
        self.assertTrue([e for e in errors if "не dict" in e])

    def test_errors_aggregated_in_one_stop(self):
        """Обе проблемы предъявляются разом, а не по одной за прогон."""
        priors = {"AAA": {"factor_betas": {"sanctions": -0.35}, "asset_type": "stock",
                          "sanctions_position": 2.0}}
        with self.assertRaises(SystemExit) as cm:
            m.compute_per_position(self.SNAP, self.SCEN, priors, "priors")
        msg = str(cm.exception)
        self.assertIn("ШКАЛА ПОЛИТИЧЕСКИХ БЕТ", msg)
        self.assertIn("вне [0,1]", msg)


    # ── реальные значения asset_type из живого снапшота ──

    def test_live_snapshot_asset_types(self):
        """
        В снапшоте asset_type — ровно stock / bond / fund, и под `fund` лежат
        ОБЛИГАЦИОННЫЕ фонды (TLCB, SBGB). Классифицировать голый `fund` как
        долевой значило бы жёстко отказывать на реальном портфеле.
        """
        self.assertIs(m._is_equity_like("SBER", "stock"), True)
        self.assertIs(m._is_equity_like("SU26243", "bond"), False)
        self.assertIsNone(m._is_equity_like("TLCB", "fund"))     # неоднозначно
        self.assertIsNone(m._is_equity_like("XXX", "other"))     # незнакомое
        self.assertIsNone(m._is_equity_like("YYY", "future"))
        self.assertIs(m._is_equity_like("TMON", "money_market"), False)
        # уточнение в priors снимает неоднозначность в обе стороны
        self.assertIs(m._is_equity_like("TLCB", "bond_fund"), False)
        self.assertIs(m._is_equity_like("SBMX", "fund_equity"), True)

    def test_bond_fund_in_portfolio_does_not_stop_run(self):
        """Облигационный фонд с дробной бетой не должен ронять прогон."""
        snap = {"as_of_date": "2026-07-02", "holdings": [
            {"ticker": "TLCB", "asset_type": "fund", "value_rub": 156000},
            {"ticker": "SBER", "asset_type": "stock", "value_rub": 100000}]}
        priors = {
            "TLCB": {"factor_betas": {"sanctions": -0.15}, "factor_betas_method": "bond fund"},
            "SBER": {"factor_betas": {"sanctions": -35}, "factor_betas_method": "banks"},
        }
        pp, warns, _ = m.compute_per_position(snap, self.SCEN, priors, "priors")
        self.assertIn("TLCB", pp)
        self.assertTrue([w for w in warns if "неоднозначен" in w and "TLCB" in w])

    def test_prior_asset_type_wins_over_snapshot(self):
        """Аналитик, разложивший фонд, должен иметь возможность это объявить."""
        holdings = [{"ticker": "TLCB", "asset_type": "fund", "value_rub": 1}]
        priors = {"TLCB": {"factor_betas": {"sanctions": -0.15},
                           "asset_type": "bond_fund"}}
        errors, warns = m.check_political_beta_scale(priors, holdings)
        self.assertEqual(errors, [])
        self.assertFalse([w for w in warns if "неоднозначен" in w])

    def test_excluded_positions_do_not_gate_run(self):
        """Заблокированная бумага в per_position не идёт — и гейтить не должна."""
        holdings = [{"ticker": "FXGD", "asset_type": "fund", "value_rub": 1000,
                     "is_blocked": True},
                    {"ticker": "SBER", "asset_type": "stock", "value_rub": 100000}]
        priors = {"FXGD": {"factor_betas": {"sanctions": -0.05}, "asset_type": "stock"},
                  "SBER": {"factor_betas": {"sanctions": -35}}}
        errors, _ = m.check_political_beta_scale(priors, holdings)
        self.assertEqual(errors, [])

    def test_empty_holdings_is_not_none(self):
        """holdings=[] — пустой портфель, а не «фильтра нет»."""
        priors = {"AAA": {"factor_betas": {"sanctions": -0.35}, "asset_type": "stock"}}
        self.assertEqual(m.check_political_beta_scale(priors, [])[0], [])
        self.assertTrue(m.check_political_beta_scale(priors, None)[0])

    def test_record_without_political_keys_flagged_per_record(self):
        """Ключи потерялись при переносе — видно поимённо, а не глобально."""
        priors = {"AAA": {"factor_betas": {"brent": 0.5}},
                  "BBB": {"factor_betas": {"sanctions": -35}}}
        _, warns = m.check_political_beta_scale(priors)
        self.assertTrue([w for w in warns if "AAA" in w and "нет вовсе" in w])

    def test_structure_checked_regardless_of_scale_flag(self):
        """Форма priors — не про шкалу: флаг её гейтить не должен."""
        snap = self.SNAP
        bad = {"AAA": {"factor_betas": [["sanctions", -35]]}}
        for mode in ("error", "warn", "off"):
            with self.subTest(mode=mode):
                with self.assertRaises(SystemExit) as cm:
                    m.compute_per_position(snap, self.SCEN, bad, "priors",
                                           political_scale_check=mode)
                self.assertIn("не dict", str(cm.exception))

    def test_hint_about_flag_only_when_flag_helps(self):
        """Подсказка про --political-scale-check не должна висеть на чужих ошибках."""
        priors = {"AAA": {"factor_betas": {"sanctions": -35},
                          "asset_type": "stock", "sanctions_position": 2.0}}
        with self.assertRaises(SystemExit) as cm:
            m.compute_per_position(self.SNAP, self.SCEN, priors, "priors")
        self.assertNotIn("--political-scale-check", str(cm.exception))

    def test_warnings_survive_in_refusal_text(self):
        """Ради этого и делалась агрегация: warnings не должны теряться при отказе."""
        snap = {"as_of_date": "2026-07-02", "holdings": [
            {"ticker": "AAA", "asset_type": "stock", "value_rub": 100000}]}
        scen = {"D": {"p": 1.0, "factors_by_horizon": {
            "h6": {"sanctions": -0.9}, "h12": {"sanctions": -0.9}}}}
        priors = {"AAA": {"factor_betas": {"sanctions": -0.35}, "asset_type": "stock"}}
        with self.assertRaises(SystemExit) as cm:
            m.compute_per_position(snap, scen, priors, "priors")
        self.assertIn("Собранные предупреждения", str(cm.exception))
        self.assertIn("одинаков на", str(cm.exception))

class TestScenarioWeightsByHorizon(unittest.TestCase):
    """
    Убеждение о том, какой сценарий реализуется, зависит от срока: на полгода
    вперёд модальным может быть один мир, на два года — другой. Скаляр `p` этого
    не выражает.
    """

    SNAP = {"as_of_date": "2026-07-02", "holdings": [
        {"ticker": "AAA", "asset_type": "stock", "value_rub": 100000}]}
    PRIORS = {"AAA": {"factor_betas": {"sanctions": -35}, "asset_type": "stock",
                      "factor_betas_method": "banks"}}

    @staticmethod
    def _scen(p_by_horizon=None, p=None):
        def sc(dial, w):
            out = {"factors_by_horizon": {
                "h6": {"sanctions": dial}, "h24": {"sanctions": dial}}}
            out.update(w)
            return out
        if p_by_horizon:
            # скаляр обязателен рядом: его читают carry и integrated-view
            return {"A": sc(+0.5, {"p_by_horizon": p_by_horizon["A"], "p": 0.5}),
                    "D": sc(-0.5, {"p_by_horizon": p_by_horizon["D"], "p": 0.5})}
        return {"A": sc(+0.5, {"p": p[0]}), "D": sc(-0.5, {"p": p[1]})}

    def _expected(self, scen, hk):
        pp, _, _ = m.compute_per_position(self.SNAP, scen, self.PRIORS, "priors")
        return pp["AAA"]["by_horizon"][hk]["expected_pct_pweighted"]["value"]

    def test_weight_differs_by_horizon(self):
        """h6 — почти весь вес на ужесточении, h24 — на разрядке."""
        scen = self._scen({"A": {"h6": 0.9, "h24": 0.2},
                           "D": {"h6": 0.1, "h24": 0.8}})
        # A: -35 × +0.5 = -17.5 ; D: -35 × -0.5 = +17.5
        self.assertAlmostEqual(self._expected(scen, "h6"), -14.0, places=2)
        self.assertAlmostEqual(self._expected(scen, "h24"), +10.5, places=2)

    def test_scalar_path_unchanged(self):
        scen = self._scen(p=(0.5, 0.5))
        self.assertAlmostEqual(self._expected(scen, "h6"), 0.0, places=2)
        self.assertAlmostEqual(self._expected(scen, "h24"), 0.0, places=2)

    def test_partial_block_refused(self):
        """Смешивать веса по горизонтам со скалярными нельзя."""
        scen = self._scen({"A": {"h6": 0.5, "h24": 0.5}, "D": {"h6": 0.5, "h24": 0.5}})
        del scen["D"]["p_by_horizon"]
        scen["D"]["p"] = 0.5
        errors, _ = m.check_scenario_weights(scen, ["h6", "h24"])
        self.assertTrue([e for e in errors if "смешивать" in e])

    def test_sum_not_one_on_one_horizon_refused(self):
        scen = self._scen({"A": {"h6": 0.9, "h24": 0.2},
                           "D": {"h6": 0.9, "h24": 0.8}})
        errors, _ = m.check_scenario_weights(scen, ["h6", "h24"])
        self.assertTrue([e for e in errors if "h6" in e and "!= 1" in e])

    def test_scalar_required_alongside_per_horizon(self):
        """
        Веса по горизонтам читает только ценовой слой. Без скаляра bond carry
        уходит на равные веса, а integrated-view получает p_norm = 0 и схлопывает
        макро-ожидание в ноль под мягким флагом.
        """
        scen = self._scen({"A": {"h6": 0.9, "h24": 0.2},
                           "D": {"h6": 0.1, "h24": 0.8}})
        del scen["A"]["p"]
        errors, _ = m.check_scenario_weights(scen, ["h6", "h24"])
        self.assertTrue([e for e in errors if "без скалярного" in e and "A" in e])

    def test_mixed_beliefs_are_declared_not_silent(self):
        scen = self._scen({"A": {"h6": 0.9, "h24": 0.2},
                           "D": {"h6": 0.1, "h24": 0.8}})
        _, warns = m.check_scenario_weights(scen, ["h6", "h24"])
        self.assertTrue([w for w in warns if "bond carry" in w])

    def test_missing_scalar_weight_is_error_not_silent_zero(self):
        """Сценарий без веса раньше молча получал 0.0 и выпадал из ожидания."""
        scen = self._scen(p=(0.5, 0.5))
        del scen["D"]["p"]
        errors, _ = m.check_scenario_weights(scen, ["h6", "h24"])
        self.assertTrue([e for e in errors if "вес не задан числом" in e])

    def test_none_weight_is_error_not_traceback(self):
        scen = self._scen(p=(0.5, 0.5))
        scen["D"]["p"] = None
        errors, _ = m.check_scenario_weights(scen, ["h6", "h24"])
        self.assertTrue([e for e in errors if "вес не задан числом" in e])

    def test_empty_scenarios_refused_contractually(self):
        errors, _ = m.check_scenario_weights({}, ["h6"])
        self.assertTrue([e for e in errors if "пуст" in e])

    def test_weight_out_of_range_refused(self):
        """Сумма может сойтись при весах вне [0,1] — спасает только диапазон."""
        scen = self._scen({"A": {"h6": 1.5, "h24": 0.5},
                           "D": {"h6": -0.5, "h24": 0.5}})
        errors, _ = m.check_scenario_weights(scen, ["h6", "h24"])
        self.assertTrue([e for e in errors if "вне [0,1]" in e])

    def test_non_numeric_weight_refused(self):
        scen = self._scen({"A": {"h6": "много", "h24": 0.2},
                           "D": {"h6": 0.1, "h24": 0.8}})
        errors, _ = m.check_scenario_weights(scen, ["h6", "h24"])
        self.assertTrue([e for e in errors if "не число" in e])

    def test_missing_horizon_in_block_refused(self):
        scen = self._scen({"A": {"h6": 0.5}, "D": {"h6": 0.5}})
        errors, _ = m.check_scenario_weights(scen, ["h6", "h24"])
        self.assertTrue([e for e in errors if "h24" in e])

    def test_bad_weights_stop_the_run(self):
        scen = self._scen({"A": {"h6": 0.9, "h24": 0.2},
                           "D": {"h6": 0.9, "h24": 0.8}})
        with self.assertRaises(SystemExit) as cm:
            m.compute_per_position(self.SNAP, scen, self.PRIORS, "priors")
        self.assertIn("!= 1", str(cm.exception))

    def test_scalar_sum_not_one_is_warning_not_error(self):
        """Pure Shell даёт 0.25×4; отклонение скаляров — повод посмотреть, не стоп."""
        scen = self._scen(p=(0.5, 0.9))
        errors, warns = m.check_scenario_weights(scen, ["h6", "h24"])
        self.assertEqual(errors, [])
        self.assertTrue([w for w in warns if "Сумма вероятностей" in w])

class TestPoliticalHorizonPathGuard(unittest.TestCase):
    """P0-2: политический дил, одинаковый на всех горизонтах, — почти всегда дефект."""

    @staticmethod
    def _scen(h6, h12, h24, factor="sanctions"):
        return {"D": {"p": 1.0, "factors_by_horizon": {
            "h6": {factor: h6, "cbr_rate": -1.0},
            "h12": {factor: h12, "cbr_rate": -2.0},
            "h24": {factor: h24, "cbr_rate": -4.0}}}}

    def test_constant_dial_warns(self):
        warns = m.check_political_horizon_path(self._scen(-0.9, -0.9, -0.9))
        self.assertEqual(len(warns), 1)
        self.assertIn("одинаков на h6/h12/h24", warns[0])

    def test_rising_path_silent(self):
        self.assertEqual(m.check_political_horizon_path(self._scen(-0.3, -0.6, -0.9)), [])

    def test_zero_dial_silent(self):
        """Статус-кво 0 на всех горизонтах — законно, не шумим."""
        self.assertEqual(m.check_political_horizon_path(self._scen(0.0, 0.0, 0.0)), [])

    def test_single_horizon_silent(self):
        scen = {"D": {"p": 1.0, "factors_by_horizon": {"h12": {"sanctions": -0.9}}}}
        self.assertEqual(m.check_political_horizon_path(scen), [])

    def test_geopol_checked_too(self):
        warns = m.check_political_horizon_path(self._scen(0.8, 0.8, 0.8, factor="geopol"))
        self.assertEqual(len(warns), 1)
        self.assertIn("D.geopol", warns[0])

    def test_v1_flat_factors_silent(self):
        """v1-вход без factors_by_horizon — один горизонт по определению."""
        self.assertEqual(
            m.check_political_horizon_path({"A": {"p": 1.0, "factors": {"sanctions": -0.9}}}),
            [])

    def test_broken_scenario_value_does_not_crash(self):
        """Битая структура сценария должна давать warning, а не AttributeError."""
        for bad in ({"A": [{"h6": {}}]}, {"A": "текст"}, {"A": None}):
            with self.subTest(bad=bad):
                warns = m.check_political_horizon_path(bad)
                self.assertTrue(all(isinstance(w, str) for w in warns))

    def test_wired_into_compute(self):
        pp, warns, _ = m.compute_per_position(
            {"as_of_date": "2026-07-02", "holdings": [
                {"ticker": "AAA", "asset_type": "stock", "value_rub": 100000}]},
            self._scen(-0.9, -0.9, -0.9),
            {"AAA": {"factor_betas": {"sanctions": -35}, "factor_betas_method": "banks"}},
            "priors")
        self.assertTrue([w for w in warns if "одинаков на" in w])

class TestSanctionsPosition(unittest.TestCase):
    """P1-3: асимметрия из позиции бумаги на санкционной шкале, а не из двух бет."""

    def test_clamp_math(self):
        f = m.effective_sanctions_move
        # уже заблокирована: ужесточать почти некуда, снимать — всё
        self.assertAlmostEqual(f(+0.7, 0.9), +0.1, places=9)
        self.assertAlmostEqual(f(-0.9, 0.9), -0.9, places=9)
        # не тронута: ужесточение проходит целиком, снимать нечего
        self.assertAlmostEqual(f(+0.7, 0.0), +0.7, places=9)
        self.assertAlmostEqual(f(-0.9, 0.0), 0.0, places=9)
        # середина шкалы: ход есть в обе стороны
        self.assertAlmostEqual(f(+0.7, 0.5), +0.5, places=9)
        self.assertAlmostEqual(f(-0.9, 0.5), -0.5, places=9)
        # backstop: позиция вне [0,1] клампится, а не ломает расчёт. В движок такие
        # значения не доходят — их раньше отвергает check_sanctions_positions
        # (см. test_bad_position_stops_run), это защита прямых вызовов функции.
        self.assertAlmostEqual(f(-0.5, 1.4), -0.5, places=9)
        self.assertAlmostEqual(f(+0.5, -0.3), +0.5, places=9)

    def test_backward_compat_none(self):
        """Позиция не задана → прежнее поведение (полная интенсивность)."""
        betas = {"sanctions": -35.0}
        self.assertAlmostEqual(
            m.compute_delta_pct(betas, {"sanctions": -0.9}), 31.5, places=6)
        self.assertAlmostEqual(
            m.compute_delta_pct(betas, {"sanctions": -0.9}, None), 31.5, places=6)

    def test_geopol_never_clamped(self):
        """geopol — страновая премия, позиции на санкционной шкале не имеет."""
        betas = {"sanctions": -35.0, "geopol": -20.0}
        d = m.compute_delta_pct(betas, {"sanctions": -0.9, "geopol": -0.9}, 0.0)
        # sanctions обнулён позицией 0, geopol прошёл целиком
        self.assertAlmostEqual(d, 18.0, places=6)

    def test_asymmetry_from_position_not_two_betas(self):
        betas = {"sanctions": -35.0}
        tighten = m.compute_delta_pct(betas, {"sanctions": +0.7}, 0.9)
        relief = m.compute_delta_pct(betas, {"sanctions": -0.9}, 0.9)
        self.assertAlmostEqual(tighten, -3.5, places=6)
        self.assertAlmostEqual(relief, +31.5, places=6)

    def test_path_independence_of_position_moves(self):
        """
        Свойство модели: последовательные ходы по шкале дают тот же итог, что
        один прямой ход в конечную позицию. Кейс Rusal (0 → 0.9 → 0.37) как
        сюжет; ходы подобраны так, что кламп реально срабатывает на первом.
        """
        betas = {"sanctions": -37.4}
        # ход 1: с нуля ужесточение с запасом за границу — кламп режет 1.2 до 1.0
        leg1 = m.compute_delta_pct(betas, {"sanctions": +1.2}, 0.0)
        # ход 2: из полученной позиции 1.0 откат до 0.37
        leg2 = m.compute_delta_pct(betas, {"sanctions": -0.63}, 1.0)
        direct = m.compute_delta_pct(betas, {"sanctions": +0.37}, 0.0)
        self.assertAlmostEqual(leg1 + leg2, direct, places=6)
        # проверка не вырождена: без клампа первый ход дал бы -44.88, а не -37.4
        self.assertAlmostEqual(leg1, -37.4, places=2)
        self.assertAlmostEqual(
            m.compute_delta_pct(betas, {"sanctions": +1.2}, None), -44.88, places=2)

    def test_clamp_actually_binds_on_tightening(self):
        """Заблокированная бумага почти не реагирует на новое ужесточение."""
        betas = {"sanctions": -37.4}
        clamped = m.compute_delta_pct(betas, {"sanctions": +0.7}, 0.9)
        unclamped = m.compute_delta_pct(betas, {"sanctions": +0.7}, None)
        self.assertAlmostEqual(clamped, -3.74, places=2)
        self.assertAlmostEqual(unclamped, -26.18, places=2)

    def test_validation_rejects_out_of_range_and_non_numeric(self):
        e1, _ = m.check_sanctions_positions({"A": {"sanctions_position": 1.4}})
        self.assertTrue([x for x in e1 if "вне [0,1]" in x])
        e2, _ = m.check_sanctions_positions({"A": {"sanctions_position": "high"}})
        self.assertTrue([x for x in e2 if "не число" in x])
        e3, _ = m.check_sanctions_positions({"A": {"sanctions_position": True}})
        self.assertTrue([x for x in e3 if "не число" in x])

    def test_validation_warns_on_strong_beta_without_position(self):
        _, w = m.check_sanctions_positions(
            {"BANK": {"factor_betas": {"sanctions": -35}},
             "UTIL": {"factor_betas": {"sanctions": -5}}})
        self.assertEqual(len(w), 1)
        self.assertIn("BANK", w[0])
        self.assertNotIn("UTIL", w[0])

    def test_validation_silent_when_position_given(self):
        e, w = m.check_sanctions_positions(
            {"BANK": {"factor_betas": {"sanctions": -35}, "sanctions_position": 0.9}})
        self.assertEqual(e, [])
        self.assertEqual(w, [])

    def _snap(self):
        return {"as_of_date": "2026-07-02", "holdings": [
            {"ticker": "BANK", "asset_type": "stock", "value_rub": 100000}]}

    SCEN = {"D": {"p": 1.0, "factors": {"sanctions": -0.9}}}

    def test_wired_into_compute_and_echoed_to_output(self):
        """Позиция 0.6 при диле -0.9 — кламп режет ход до -0.6, результат отличим."""
        priors = {"BANK": {"factor_betas": {"sanctions": -35},
                           "factor_betas_method": "banks",
                           "asset_type": "stock", "sanctions_position": 0.6}}
        pp, _, _ = m.compute_per_position(self._snap(), self.SCEN, priors, "priors")
        self.assertEqual(pp["BANK"]["sanctions_position"], 0.6)
        self.assertAlmostEqual(
            pp["BANK"]["by_horizon"]["h20"]["delta_pct_by_scenario"]["D"]["value"],
            21.0, places=2)   # -35 × (-0.6), а не × (-0.9) = 31.5

    def test_untouched_name_gets_no_relief_gift(self):
        """Бумага без санкционного дисконта в цене на разрядке почти не растёт."""
        priors = {"BANK": {"factor_betas": {"sanctions": -35},
                           "factor_betas_method": "utility", "sanctions_position": 0.05}}
        pp, _, _ = m.compute_per_position(self._snap(), self.SCEN, priors, "priors")
        self.assertAlmostEqual(
            pp["BANK"]["by_horizon"]["h20"]["delta_pct_by_scenario"]["D"]["value"],
            1.75, places=2)   # −35 × (−0.05), а не −35 × (−0.9)

    def test_bad_position_stops_run(self):
        priors = {"BANK": {"factor_betas": {"sanctions": -35},
                           "factor_betas_method": "banks", "sanctions_position": 2.0}}
        with self.assertRaises(SystemExit) as cm:
            m.compute_per_position(self._snap(), self.SCEN, priors, "priors")
        self.assertIn("вне [0,1]", str(cm.exception))

    def test_absent_position_unchanged_output(self):
        """Старые priors без поля считаются ровно как раньше, поля в выводе нет."""
        priors = {"BANK": {"factor_betas": {"sanctions": -35},
                           "factor_betas_method": "banks"}}
        pp, warns, _ = m.compute_per_position(self._snap(), self.SCEN, priors, "priors")
        self.assertNotIn("sanctions_position", pp["BANK"])
        self.assertAlmostEqual(
            pp["BANK"]["by_horizon"]["h20"]["delta_pct_by_scenario"]["D"]["value"],
            31.5, places=2)
        self.assertTrue([w for w in warns if "sanctions_position не задан" in w])


if __name__ == "__main__":
    unittest.main()
