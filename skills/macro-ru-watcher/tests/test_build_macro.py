#!/usr/bin/env python3
"""build_macro.py — макросрез без LLM (API-1c, 2026-10-21).

Контракты:
  • разбор прошлых срезов ru-*.md: второй столбец «Текущее», первое число ячейки
    («14.00% (на 16.10)», «$105.92 (закрытие 15.10)», «83.995 (внутри дня 16.10)»), ❓ — пропуск;
  • Δ: % для уровней, п.п. для ставок и инфляции; срез без значения выпадает из ряда;
  • z-score по anomaly-detection.md: окно до 12 Δ, μ и выборочное σ; σ=0 или <2 Δ — без z;
    флаги 1/2/3σ, ≥3σ при истории <8 — ❓; ставка ЦБ — бинарный маркер, без z;
  • Brent: Δ на ОДНОМ контракте BR к дате прошлого среза. Живой случай 16.10: скилл дал
    +5,31% (ICE 15.10 к ICE 06.10 — не те даты), BRX6 к 08.10 — +1,57%;
  • инфляция — вход; нет входа — «нет данных», без подстановок. С --infl-cbr (ежедневная
    задача сайта, 2026-10-21) — месячная г/г из таблицы cbr.ru/hd_base/infl/ с пометкой, что она
    не сопоставима с недельной оценкой срезов скилла; недельная — по-прежнему «нет данных».
Сеть не нужна. Запуск: python3 skills/macro-ru-watcher/tests/test_build_macro.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import build_macro as bm  # noqa: E402

MD = """# Макропанель РФ · 16.10.2026

| Индикатор | Текущее | Прошлый snapshot (08.10) | Месяц назад | Δ | z | Источник |
|---|---|---|---|---|---|---|
| Ключевая ставка ЦБ | 14.00% (на 16.10) | 14.00% | 14.00% | — | — | x |
| Инфляция (г/г) | 7.22% (на 12.10) | 7.08% | 6.3% | +0.14 п.п. | +0.18σ | x |
| Инфляция (нед) | ❓ | 0.96% | 0.05% | — | — | x |
| USD/RUB | 83.995 (внутри дня 16.10) | 86.01 | 84.8325 | −2.34% | −1.63σ ⚠️ | x |
| Brent | $105.92 (закрытие 15.10) | $100.58 | $105.91 | +5.31% | +0.29σ | x |
| IMOEX | 2399.47 (внутри дня 16.10) | 2327.14 | 2284.84 | +3.11% | +0.59σ | x |
"""


def fetched(**vals):
    return {"indicators": {k: {"status": "ok", "value": v, "as_of": "2026-10-16"} for k, v in vals.items()}}


class Parse(unittest.TestCase):
    def test_cells(self):
        self.assertEqual(bm.parse_number("14.00% (на 16.10)"), 14.0)
        self.assertEqual(bm.parse_number("$105.92 (закрытие 15.10)"), 105.92)
        self.assertEqual(bm.parse_number("−0.01%"), -0.01)
        self.assertEqual(bm.parse_number("12,5115"), 12.5115)
        self.assertIsNone(bm.parse_number("❓"))
        self.assertIsNone(bm.parse_number("—"))

    def test_table(self):
        v = bm.parse_snapshot_md(MD)
        self.assertEqual((v["cbr_key"], v["usd_rub"], v["brent"], v["imoex"]), (14.0, 83.995, 105.92, 2399.47))
        self.assertIsNone(v["infl_week"])
        self.assertNotIn("rgbi", v)


class Stats(unittest.TestCase):
    def test_deltas_skip_missing(self):
        self.assertEqual([round(x, 6) for x in bm.deltas([100, None, 110, 99], "pct")], [10.0, -10.0])
        self.assertEqual([round(x, 6) for x in bm.deltas([7.0, 7.2, None, 7.1], "pp")], [0.2, -0.1])

    def test_zscore_and_flags(self):
        z, mu, sd, n = bm.zscore(3.0, [1.0, -1.0, 1.0, -1.0])
        self.assertEqual(n, 4)
        self.assertAlmostEqual(mu, 0.0)
        self.assertAlmostEqual(z, 3.0 / sd)
        self.assertEqual(bm.zscore(1.0, [0.5, 0.5])[0], None)        # σ = 0
        self.assertEqual(bm.zscore(1.0, [0.5])[0], None)             # < 2 Δ
        self.assertEqual(bm.flag(1.2, 12), "⚠️")
        self.assertEqual(bm.flag(-2.5, 12), "⚠️⚠️")
        self.assertEqual(bm.flag(3.4, 12), "⚠️⚠️⚠️")
        self.assertEqual(bm.flag(3.4, 5), "❓")                      # короткая история
        self.assertEqual(bm.flag(0.4, 12), "")
        self.assertEqual(bm.flag(5.0, 1), "")                        # история < 2


class Build(unittest.TestCase):
    HIST = [("2026-09-16", {"usd_rub": 84.8325, "brent": 105.91, "cbr_key": 14.0}),
            ("2026-10-04", {"usd_rub": 84.41, "brent": 101.61, "cbr_key": 14.0}),
            ("2026-10-08", {"usd_rub": 86.01, "brent": 100.58, "cbr_key": 14.0})]

    def rep(self, brent=None, infl=None):
        brent = brent or {"status": "ok", "value": 107.22, "as_of": "2026-10-16", "contract": "BRX6",
                          "prev_same_contract": {"value": 105.56, "as_of": "2026-10-08"}}
        return bm.build("2026-10-16", self.HIST, fetched(usd_rub=83.995, cbr_key=14.0), brent, infl or {})

    def row(self, rep, key):
        return next(r for r in rep["rows"] if r["key"] == key)

    def test_brent_delta_on_same_contract(self):            # 16.10: +1,57%, не +5,31%
        r = self.row(self.rep(), "brent")
        self.assertAlmostEqual(r["delta"], (107.22 - 105.56) / 105.56 * 100, places=6)
        self.assertIn("BRX6", r["note"])

    def test_pct_delta_vs_prev_snapshot(self):
        r = self.row(self.rep(), "usd_rub")
        self.assertAlmostEqual(r["delta"], (83.995 - 86.01) / 86.01 * 100, places=6)
        self.assertEqual(r["month_ago"], ("2026-09-16", 84.8325))

    def test_key_rate_binary(self):
        r = self.row(self.rep(), "cbr_key")
        self.assertEqual((r["delta"], r["z"], r["flag"]), (0.0, None, ""))
        self.assertIn("— (бинарный маркер)", bm.render_md(self.rep(), "x"))

    def test_inflation_missing_is_no_data(self):
        rep = self.rep()
        self.assertIsNone(self.row(rep, "infl_yoy")["value"])
        self.assertIn("Инфляция:** вход не передан", bm.render_md(rep, "x"))

    def test_brent_error_is_no_data(self):
        rep = self.rep(brent={"status": "error", "error": "DNS"})
        self.assertIsNone(self.row(rep, "brent")["value"])
        self.assertIn("**Brent:** нет данных — DNS", bm.render_md(rep, "x"))

    def test_render_parses_back(self):                      # свой срез читается как история
        vals = bm.parse_snapshot_md(bm.render_md(self.rep(infl={"yoy": 7.22, "yoy_asof": "на 12.10"}), "x"))
        self.assertEqual((vals["usd_rub"], vals["brent"], vals["infl_yoy"]), (83.995, 107.22, 7.22))


class CbrInflation(unittest.TestCase):
    FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "cbr-infl-2026-10-20.html")

    def test_parse_latest_month(self):                      # живая таблица ЦБ 20.10.2026
        r = bm.parse_cbr_infl(open(self.FIX, encoding="utf-8").read())
        self.assertEqual((r["yoy"], r["yoy_asof"]), (6.35, "за 09.2026"))

    def test_changed_layout_is_none(self):
        self.assertIsNone(bm.parse_cbr_infl("<table><tr><td>нет</td></tr></table>"))

    def test_make_uses_cbr_only_without_input(self):
        html = open(self.FIX, encoding="utf-8").read()
        orig = (bm.fetch_macro.fetch_all, bm.fetch_brent, bm.fetch_cbr_infl)
        bm.fetch_macro.fetch_all = lambda: fetched(usd_rub=84.0)
        bm.fetch_brent = lambda d, p: {"status": "error", "error": "offline"}
        bm.fetch_cbr_infl = lambda: bm.parse_cbr_infl(html)
        try:
            md, rep = bm.make("2026-10-21", None, {}, infl_cbr=True)
            self.assertEqual(rep["infl_kind"], "cbr_monthly")
            self.assertIn("6.35% (за 09.2026)", md)
            self.assertIn("только по прежним месячным", md)
            md, rep = bm.make("2026-10-21", None, {"yoy": 7.0, "yoy_asof": "на 19.10"}, infl_cbr=True)
            self.assertEqual(rep["infl_kind"], "input")      # вход важнее таблицы
        finally:
            bm.fetch_macro.fetch_all, bm.fetch_brent, bm.fetch_cbr_infl = orig


class InflationOneSource(unittest.TestCase):
    """z-флаг инфляции — только по значениям одного источника (11.11: смесь недельных оценок скилла
    и месячных ЦБ давала ложный z=−2,6)."""

    def setUp(self):
        import json
        import tempfile
        from pathlib import Path
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "auto").mkdir()
        # недельные оценки скилла: 7.0–7.6; последний срез скилла — 7.4
        for d, v in (("2026-09-01", 7.0), ("2026-09-08", 7.6), ("2026-09-15", 7.1), ("2026-09-22", 7.5), ("2026-09-29", 7.4)):
            (self.tmp / f"ru-{d}.md").write_text(MD.replace("7.22% (на 12.10)", f"{v}% (на {d})"), encoding="utf-8")
        # месячные ЦБ из автосрезов: 6.9, 6.6, 6.5, 6.2
        for d, v in (("2026-07-20", 6.9), ("2026-08-20", 6.6), ("2026-09-20", 6.5), ("2026-10-20", 6.2)):
            (self.tmp / "auto" / f"ru-{d}.json").write_text(json.dumps(
                {"kind": "macro-ru@1", "date": d, "infl_kind": "cbr_monthly",
                 "rows": [{"key": "infl_yoy", "value": v}]}), encoding="utf-8")
        # автосрез с инфляцией «вход» (не ЦБ) в историю ЦБ не входит
        (self.tmp / "auto" / "ru-2026-10-10.json").write_text(json.dumps(
            {"kind": "macro-ru@1", "date": "2026-10-10", "infl_kind": "input", "rows": [{"key": "infl_yoy", "value": 9.9}]}),
            encoding="utf-8")
        self.cbr = {"yoy": 6.0, "yoy_asof": "за 10.2026"}

    def run_make(self):
        orig = (bm.fetch_macro.fetch_all, bm.fetch_brent, bm.fetch_cbr_infl)
        bm.fetch_macro.fetch_all = lambda: fetched(usd_rub=84.0)
        bm.fetch_brent = lambda d, p: {"status": "error", "error": "offline"}
        bm.fetch_cbr_infl = lambda: dict(self.cbr, source="ЦБ")
        try:
            return bm.make("2026-11-20", self.tmp, {}, infl_cbr=True)
        finally:
            bm.fetch_macro.fetch_all, bm.fetch_brent, bm.fetch_cbr_infl = orig

    def test_history_from_auto_only(self):
        self.assertEqual(bm.load_auto_infl(self.tmp, "2026-11-20"),
                         [("2026-07-20", 6.9), ("2026-08-20", 6.6), ("2026-09-20", 6.5), ("2026-10-20", 6.2)])
        self.assertEqual(bm.load_auto_infl(self.tmp, "2026-09-20"), [("2026-07-20", 6.9), ("2026-08-20", 6.6)])

    def test_z_uses_monthly_series_not_weekly_mix(self):
        _, rep = self.run_make()
        r = next(x for x in rep["rows"] if x["key"] == "infl_yoy")
        self.assertEqual(r["prev"], 6.2)                    # прошлое значение — ЦБ, не скилла (7.4)
        self.assertAlmostEqual(r["delta"], -0.2)
        self.assertEqual(r["n_hist"], 3)                    # три месячные Δ
        self.assertEqual(r["flag"], "")                     # смесь дала бы Δ=−1,4 п.п. и флаг
        self.assertLess(abs(r["z"]), 1.0)

    def test_mixed_history_would_flag(self):                # контроль: прежнее поведение (история из ru-*.md) флагует
        hist = bm.load_history(self.tmp, "2026-11-20")
        rep = bm.build("2026-11-20", hist, fetched(usd_rub=84.0), {}, dict(self.cbr))
        r = next(x for x in rep["rows"] if x["key"] == "infl_yoy")
        self.assertNotEqual(r["flag"], "")

    def test_input_inflation_keeps_skill_history(self):     # инфляция «вход» (скилл) — история срезов скилла, как раньше
        hist = bm.load_history(self.tmp, "2026-11-20")
        rep = bm.build("2026-11-20", hist, fetched(usd_rub=84.0), {}, {"yoy": 7.5})
        r = next(x for x in rep["rows"] if x["key"] == "infl_yoy")
        self.assertEqual(r["prev"], 7.4)

class HistoryFromAuto(unittest.TestCase):
    """История z остальных индикаторов — по одному источнику: автосрезы auto/ru-*.json, срезы скилла ru-*.md —
    только пока автосрезов не хватает (< AUTO_MIN_DELTAS Δ). 11.11: без запусков скилла окно z не росло."""

    def mk(self, n_auto):
        import json
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mkdtemp())
        (tmp / "auto").mkdir()
        # скилл: USD/RUB около 70, Brent (ICE) около 100 — другой уровень, чем в автосрезе
        for i in range(10):
            d = f"2026-09-{i + 1:02d}"
            (tmp / f"ru-{d}.md").write_text(MD.replace("83.995 (внутри дня 16.10)", f"{70 + (i % 2) * 0.3}")
                                            .replace("$105.92 (закрытие 15.10)", f"${100 + (i % 2)}"), encoding="utf-8")
        # автосрез: USD/RUB около 83 (шум ±0.2), Brent BR около 90, смена контракта на 6-м срезе (+6%)
        for i in range(n_auto):
            d = f"2026-10-{i + 1:02d}"
            br = (90 + (i % 2) * 0.5) * (1.06 if i >= 6 else 1.0)
            (tmp / "auto" / f"ru-{d}.json").write_text(json.dumps({"kind": "macro-ru@1", "rows": [
                {"key": "usd_rub", "value": 83 + (i % 2) * 0.2},
                {"key": "brent", "value": br, "contract": "BRX6" if i < 6 else "BRZ6"}]}), encoding="utf-8")
        return tmp

    def rows(self, tmp, usd=83.1, brent_prev=None):
        orig = (bm.fetch_macro.fetch_all, bm.fetch_brent)
        bm.fetch_macro.fetch_all = lambda: fetched(usd_rub=usd)
        bm.fetch_brent = lambda d, p: {"value": 95.4, "as_of": "x", "contract": "BRZ6", "prev_same_contract": brent_prev}
        try:
            _, rep = bm.make("2026-11-01", tmp, {})
        finally:
            bm.fetch_macro.fetch_all, bm.fetch_brent = orig
        return rep, {r["key"]: r for r in rep["rows"]}

    def test_auto_is_primary(self):
        rep, r = self.rows(self.mk(12))
        u = r["usd_rub"]
        self.assertEqual(u["prev"], 83.2)                    # прошлое значение — автосрез, не скилл (70.3)
        self.assertEqual(u["n_hist"], 11)
        self.assertEqual(u["flag"], "")                      # на смене источника ложного флага нет
        self.assertIn("usd_rub", rep["history_auto"])

    def test_no_false_flag_on_source_boundary(self):        # контроль: смесь md→auto даёт скачок +18% и ❓/⚠️
        tmp = self.mk(12)
        hist = bm.load_history(tmp, "2026-11-01")
        mixed = bm.build("2026-11-01", hist, fetched(usd_rub=83.1), {}, {})
        mu = next(x for x in mixed["rows"] if x["key"] == "usd_rub")
        self.assertEqual(mu["prev"], 70.3)                   # прежнее поведение: прошлое значение из ru-*.md
        self.assertNotEqual(mu["flag"], "")

    def test_brent_window_skips_contract_roll(self):
        _, r = self.rows(self.mk(12), brent_prev={"value": 95.0, "as_of": "y"})
        b = r["brent"]
        self.assertEqual(b["n_hist"], 10)                    # 11 Δ минус одна через смену контракта
        self.assertLess(abs(b["mu"]), 1.0)                   # скачок +6% в σ не попал
        self.assertEqual(b["flag"], "")

    def test_brent_not_mixed_with_ice(self):
        _, r = self.rows(self.mk(12))
        self.assertGreater(r["brent"]["prev"], 90)           # BR автосреза, не ICE скилла (100–101)
        self.assertNotIn(r["brent"]["prev"], (100.0, 101.0))

    def test_fallback_to_skill_snapshots_when_auto_short(self):
        rep, r = self.rows(self.mk(5), usd=70.2)
        u = r["usd_rub"]
        self.assertNotIn("usd_rub", rep["history_auto"])
        self.assertEqual(u["prev"], 70.3)                    # целиком срезы скилла
        self.assertEqual(u["n_hist"], 9)
        self.assertEqual(u["flag"], "")                      # автосрез в окно не подмешан

    def test_auto_threshold(self):                          # 8 Δ нужны: 9 точек хватает, 8 — нет
        self.assertIn("usd_rub", bm.pick_auto(bm.load_auto_series(self.mk(9), "2026-11-01")))
        self.assertNotIn("usd_rub", bm.pick_auto(bm.load_auto_series(self.mk(8), "2026-11-01")))


if __name__ == "__main__":
    unittest.main(verbosity=1)
