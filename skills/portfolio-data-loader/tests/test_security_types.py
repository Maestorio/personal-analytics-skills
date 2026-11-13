#!/usr/bin/env python3
"""Тип бумаги с Мосбиржи: security_types.py + переопределение классификатора + сверка типов при сборке.

Контракты:
  • разбор ответа ISS securities/{secid}.json (description): GROUP → stock/bond/fund/other; пустая
    description (бумаги на бирже нет: FINAMAR, внебиржевые, иностранные) → None;
  • refresh offline не ходит в сеть; online спрашивает только тикеры, которых нет в справочнике;
    ошибка одного тикера не ломает остальных; запись атомарна (нет *.tmp); «нет на бирже»
    перепроверяется через 90 дней, найденные — никогда;
  • set_type_overrides: fund из справочника перебивает эвристику «акция по дивидендам»; other и None —
    нет; use_overrides=False возвращает чистую эвристику; --types-cache есть у трёх скриптов;
  • compare_types: prev_vs_now (тип сменился против прошлого снапшота), moex_vs_heuristic (новая
    бумага, биржа и эвристика разошлись); облигация сопоставляется по ISIN; без расхождений — пусто;
  • сборка: справочник из пакета перебивает тип, type_check в снапшоте, флаг asset_type_changed,
    type_changes и types в build-summary.
Сеть не нужна: urlopen мокается. Запуск: python3 skills/portfolio-data-loader/tests/test_security_types.py
"""
import datetime as dt
import io
import json
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import security_types as st  # noqa: E402
import portfolio_returns as pr  # noqa: E402
import build_snapshot as bs  # noqa: E402


def iss(group, typ="x", isin="RU000A0JX0J2", secid="T"):
    rows = [["SECID", "Код", secid, "string", 1, 0, None], ["TYPE", "Тип", typ, "string", 2, 0, None],
            ["GROUP", "Группа", group, "string", 3, 0, None], ["ISIN", "ISIN", isin, "string", 4, 0, None]]
    return {"description": {"columns": ["name", "title", "value", "type", "sort_order", "is_hidden",
                                        "precision"], "data": rows}}


EMPTY = {"description": {"columns": ["name", "title", "value"], "data": []}}


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def fake_urlopen(table, calls):
    """table: secid -> dict ответа | Exception."""
    def _open(url, data=None, timeout=None, *a, **kw):
        secid = url.split("/securities/")[1].split(".json")[0]
        calls.append((secid, timeout))
        v = table[secid]
        if isinstance(v, Exception):
            raise v
        return FakeResp(json.dumps(v).encode())
    return _open


def T(ticker, op):
    return pr.Trade(ticker, ticker, op, dt.date(2026, 1, 1), 1, 1, None, None, 0, 1, 1, "RUB", "")


class Parse(unittest.TestCase):
    def test_groups(self):
        for g, want in (("stock_shares", "stock"), ("stock_dr", "stock"), ("stock_foreign_shares", "stock"),
                        ("stock_bonds", "bond"), ("stock_eurobond", "bond"),
                        ("stock_etf", "fund"), ("stock_ppif", "fund"), ("currency_selt", "other")):
            self.assertEqual(st.parse_description(iss(g))["type"], want, g)

    def test_fields(self):
        r = st.parse_description(iss("stock_etf", "etf_ppif", "RU000A1022Z1"))
        self.assertEqual((r["moex_type"], r["moex_group"], r["isin"]), ("etf_ppif", "stock_etf", "RU000A1022Z1"))

    def test_empty_is_none(self):
        self.assertIsNone(st.parse_description(EMPTY))
        self.assertIsNone(st.parse_description({}))

    def test_without_columns(self):
        js = {"description": {"data": [["GROUP", "Группа", "stock_bonds"]]}}
        self.assertEqual(st.parse_description(js)["type"], "bond")

    def test_timeout_capped(self):
        calls = []
        with mock.patch.object(urllib.request, "urlopen", fake_urlopen({"A": iss("stock_shares")}, calls)):
            st.fetch_type("A", timeout=60)
        self.assertLessEqual(calls[0][1], 10)


class Refresh(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "Portfolio" / "security-types.json"
        self.today = dt.date(2026, 10, 28)

    def test_offline_no_network(self):
        calls = []
        with mock.patch.object(urllib.request, "urlopen", fake_urlopen({}, calls)):
            data, f, fl = st.refresh_types(self.path, ["TMON"], False, self.today)
        self.assertEqual((calls, f, fl, data["by_ticker"]), ([], [], [], {}))
        self.assertFalse(self.path.exists())

    def test_online_asks_only_missing_and_survives_errors(self):
        st.save_types(self.path, {"by_ticker": {"SBER": {"type": "stock", "fetched_at": "2026-01-01",
                                                          "source": "moex_iss"}}})
        calls = []
        table = {"TMON": iss("stock_etf", "etf_ppif"), "BAD": urllib.error.URLError("down"),
                 "FINAMAR": EMPTY, "LKOH": iss("stock_shares", "common_share")}
        with mock.patch.object(urllib.request, "urlopen", fake_urlopen(table, calls)):
            data, fetched, failed = st.refresh_types(self.path, ["SBER", "TMON", "BAD", "FINAMAR", "LKOH", "TMON"],
                                                     True, self.today)
        self.assertEqual([c[0] for c in calls], ["TMON", "BAD", "FINAMAR", "LKOH"])      # SBER уже есть
        self.assertEqual(fetched, ["TMON", "FINAMAR", "LKOH"])
        self.assertEqual(failed, ["BAD"])
        saved = st.load_types(self.path)["by_ticker"]
        self.assertEqual(saved["TMON"]["type"], "fund")
        self.assertEqual(saved["TMON"]["fetched_at"], "2026-10-28")
        self.assertIsNone(saved["FINAMAR"]["type"])
        self.assertEqual(saved["FINAMAR"]["note"], "нет на Мосбирже")
        self.assertNotIn("BAD", saved)
        self.assertEqual(st.load_types(self.path)["schema_version"], "security-types@1.0")
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["security-types.json"])   # нет *.tmp

    def test_unwritable_cache_reports_error_not_crash(self):
        # 2026-10-28 на NAS: том /srv у hub-notify только на чтение — шаг падал с кодом 1, build_snapshot
        # терял вывод и считал все тикеры failed без причины. Теперь: всё в failed + текст в errors, код 0.
        calls, errors = [], []
        table = {"TMON": iss("stock_etf", "etf_ppif")}
        with mock.patch.object(urllib.request, "urlopen", fake_urlopen(table, calls)), \
                mock.patch.object(st, "save_types", side_effect=OSError(30, "Read-only file system")):
            data, fetched, failed = st.refresh_types(self.path, ["TMON"], True, self.today, errors=errors)
        self.assertEqual((fetched, failed), ([], ["TMON"]))
        self.assertEqual(len(errors), 1)
        self.assertIn("Read-only", errors[0])
        self.assertEqual(data["by_ticker"]["TMON"]["type"], "fund")     # в памяти тип есть, на диске — нет
        self.assertFalse(self.path.exists())

    def test_second_run_no_requests(self):
        table = {"TMON": iss("stock_etf"), "FINAMAR": EMPTY}
        with mock.patch.object(urllib.request, "urlopen", fake_urlopen(table, [])):
            st.refresh_types(self.path, ["TMON", "FINAMAR"], True, self.today)
        calls = []
        with mock.patch.object(urllib.request, "urlopen", fake_urlopen({}, calls)):
            _, f, _ = st.refresh_types(self.path, ["TMON", "FINAMAR"], True, self.today + dt.timedelta(days=89))
        self.assertEqual((calls, f), ([], []))

    def test_not_on_moex_rechecked_after_90_days(self):
        with mock.patch.object(urllib.request, "urlopen", fake_urlopen({"FINAMAR": EMPTY, "TMON": iss("stock_etf")}, [])):
            st.refresh_types(self.path, ["FINAMAR", "TMON"], True, self.today)
        calls = []
        with mock.patch.object(urllib.request, "urlopen",
                               fake_urlopen({"FINAMAR": iss("stock_ppif"), "TMON": iss("stock_etf")}, calls)):
            _, f, _ = st.refresh_types(self.path, ["FINAMAR", "TMON"], True, self.today + dt.timedelta(days=90))
        self.assertEqual(f, ["FINAMAR"])                       # найденный TMON не перепроверяется
        self.assertEqual(st.load_types(self.path)["by_ticker"]["FINAMAR"]["type"], "fund")

    def test_all_fail_stops_after_streak(self):
        tickers = [f"T{i}" for i in range(12)]
        calls = []
        table = {t: urllib.error.URLError("down") for t in tickers}
        with mock.patch.object(urllib.request, "urlopen", fake_urlopen(table, calls)):
            _, f, fl = st.refresh_types(self.path, tickers, True, self.today)
        self.assertEqual((f, fl), ([], tickers))
        self.assertEqual(len(calls), st.MAX_CONSECUTIVE_FAILS)
        self.assertFalse(self.path.exists())

    def test_cli_refresh_prints_json(self):
        buf = io.StringIO()
        with mock.patch.object(urllib.request, "urlopen", fake_urlopen({"TMON": iss("stock_etf")}, [])), \
                mock.patch("sys.stdout", buf):
            rc = st.main(["refresh", "--cache", str(self.path), "--tickers", "TMON", "--today", "2026-10-28"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(buf.getvalue()), {"online": True, "fetched": ["TMON"], "failed": [], "errors": []})

    def test_load_broken_file(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{oops", encoding="utf-8")
        self.assertEqual(st.load_types(self.path)["by_ticker"], {})

    def test_overrides_from(self):
        d = {"by_ticker": {"A": {"type": "fund"}, "B": {"type": None}, "C": {"type": "other"},
                           "D": {"type": "bond"}}}
        self.assertEqual(st.overrides_from(d), {"A": "fund", "D": "bond"})


class Overrides(unittest.TestCase):
    def tearDown(self):
        pr.set_type_overrides(None)

    def test_fund_beats_dividend_heuristic(self):
        tr = [T("ZZZ", "Покупка"), T("ZZZ", "Дивиденд")]
        self.assertEqual(pr.classify_instrument_type(tr), "stock")
        pr.set_type_overrides({"ZZZ": "fund"})
        self.assertEqual(pr.classify_instrument_type(tr), "fund")
        self.assertEqual(pr.classify_instrument_type(tr, use_overrides=False), "stock")

    def test_none_and_other_do_not_override(self):
        pr.set_type_overrides({"ZZZ": "other", "YYY": None})
        self.assertEqual(pr.classify_instrument_type([T("ZZZ", "Дивиденд")]), "stock")
        self.assertEqual(pr.classify_instrument_type([T("YYY", "Купон")]), "bond")

    def test_reset(self):
        pr.set_type_overrides({"ZZZ": "fund"})
        pr.set_type_overrides(None)
        self.assertEqual(pr.classify_instrument_type([T("ZZZ", "Покупка")]), "stock")

    def test_load_types_cache(self):
        tmp = Path(tempfile.mkdtemp()) / "t.json"
        self.assertEqual(pr.load_types_cache(str(tmp)), 0)              # нет файла — молча
        st.save_types(tmp, {"by_ticker": {"ZZZ": {"type": "fund"}, "N": {"type": None}}})
        self.assertEqual(pr.load_types_cache(str(tmp)), 1)
        self.assertEqual(pr.classify_instrument_type([T("ZZZ", "Дивиденд")]), "fund")
        self.assertEqual(pr.load_types_cache(None), 0)

    def test_three_scripts_accept_types_cache(self):
        for name in ("portfolio_returns.py", "per_security_xirr.py", "iis_returns.py"):
            p = subprocess.run([sys.executable, str(SCRIPTS / name), "--help"], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, name)
            self.assertIn("--types-cache", p.stdout, name)


def H(ticker, at, account="main", isin=None, name=None):
    return {"ticker": ticker, "asset_type": at, "account": account, "isin": isin, "name": name or ticker}


class Compare(unittest.TestCase):
    def test_prev_vs_now(self):
        ch = st.compare_types([H("TMON", "fund", name="Т-Капитал")], [H("TMON", "stock")],
                              {"TMON": "fund"}, {"TMON": "stock"})
        self.assertEqual(len(ch), 1)
        self.assertEqual((ch[0]["reason"], ch[0]["was"], ch[0]["now"], ch[0]["moex"], ch[0]["heur"]),
                         ("prev_vs_now", "stock", "fund", "fund", "stock"))
        self.assertIn("был акция, стал фонд (по бирже)", st.change_text(ch[0]))

    def test_moex_vs_heuristic_for_new(self):
        ch = st.compare_types([H("NEW", "fund")], [H("OLD", "stock")], {"NEW": "fund"}, {"NEW": "stock"})
        self.assertEqual([c["reason"] for c in ch], ["moex_vs_heuristic"])
        self.assertIsNone(ch[0]["was"])
        self.assertIn("по бирже фонд, по сделкам акция", st.change_text(ch[0]))

    def test_no_changes(self):
        self.assertEqual(st.compare_types([H("SBER", "stock"), H("NEW", "stock")], [H("SBER", "stock")],
                                          {"NEW": "stock"}, {"NEW": "stock"}), [])

    def test_known_ticker_does_not_trigger_moex_vs_heur(self):
        # бумага была в прошлом снапшоте с тем же типом → расхождение биржа/эвристика не шумит
        self.assertEqual(st.compare_types([H("TMON", "fund")], [H("TMON", "fund")],
                                          {"TMON": "fund"}, {"TMON": "stock"}), [])

    def test_bond_matched_by_isin(self):
        ch = st.compare_types([H("RU000A1", "bond", isin="RU000A1")], [H("OLDNAME", "stock", isin="RU000A1")],
                              {}, {})
        # прошлый тип не облигация → по ISIN сопоставление только облигаций, по тикеру — нет: новая бумага
        self.assertEqual(ch, [])
        ch = st.compare_types([H("NORNIK", "bond", isin="RU000A1")], [H("1P17", "stock", isin="RU000A1")], {}, {})
        self.assertEqual(ch, [])
        ch = st.compare_types([H("X", "fund", isin="RU000A1")], [H("X", "bond", isin="RU000A1")], {}, {})
        self.assertEqual(ch[0]["was"], "bond")

    def test_account_preferred(self):
        ch = st.compare_types([H("TMON", "fund", "iis_3")], [H("TMON", "stock", "main"), H("TMON", "fund", "iis_3")],
                              {}, {})
        self.assertEqual(ch, [])

    def test_other_moex_does_not_trigger(self):
        self.assertEqual(st.compare_types([H("NEW", "stock")], [], {}, {"NEW": "stock"}), [])


class BuildFlags(unittest.TestCase):
    def test_flags(self):
        tc = {"changes": [{"ticker": "TMON", "was": "stock", "now": "fund", "moex": "fund",
                           "heur": "stock", "reason": "prev_vs_now"}], "online": True,
              "failed": ["A", "B"], "fetched": []}
        codes = {f["code"]: f for f in bs.type_check_flags(tc, 2)}
        self.assertEqual(codes["asset_type_changed"]["severity"], "warn")
        self.assertIn("TMON: был акция, стал фонд (по бирже)", codes["asset_type_changed"]["message"])
        self.assertEqual(codes["moex_types_unavailable"]["severity"], "info")
        self.assertIn("asset_type_changed", bs.ATTENTION_FLAGS)

    def test_no_unavailable_flag_when_some_fetched_or_offline(self):
        base = {"changes": [], "online": True, "failed": ["A"], "fetched": ["B"]}
        self.assertEqual(bs.type_check_flags(base, 2), [])
        self.assertEqual(bs.type_check_flags({**base, "online": False}, 1), [])

    def test_type_lookup_tickers_filters(self):
        got = bs.type_lookup_tickers({"SBER": [], "Деньги (RUB)": [], "Si-9.23": []},
                                     {"holdings": [{"ticker": "TMON"}, {"ticker": None}]},
                                     {"holdings": [{"ticker": "FINAMAR"}]})
        self.assertEqual(got, ["FINAMAR", "SBER", "TMON"])


class NoTradesHeuristic(unittest.TestCase):
    """Бумаги без сделок (баланс, перенос): эвристика по одному тикеру против биржи."""

    def _tc(self, holdings, moex):
        with tempfile.TemporaryDirectory() as d:
            tp = Path(d) / "types.json"
            tp.write_text(json.dumps({"by_ticker": {k: {"type": v} for k, v in moex.items()}}), encoding="utf-8")
            with mock.patch.object(bs.st_mod, "overrides_from", return_value=moex):
                return bs.build_type_check({"holdings": holdings}, None, tp, {}, False, [], [])["changes"]

    def test_isin_ticker_bond_vs_moex_fund(self):
        ch = self._tc([H("RU000A10ABC1", "fund")], {"RU000A10ABC1": "fund"})
        self.assertEqual([(c["ticker"], c["heur"], c["reason"]) for c in ch], [("RU000A10ABC1", "bond", "moex_vs_heuristic")])

    def test_no_heuristic_no_noise(self):
        self.assertEqual(self._tc([H("NEWCO", "stock"), H("OTHR", "fund")], {"NEWCO": "stock", "OTHR": "fund"}), [])

    def test_known_fund_agrees(self):
        self.assertEqual(self._tc([H("SBGB", "fund")], {"SBGB": "fund"}), [])


class Build(unittest.TestCase):
    """Сборка через --replay: справочник пакета перебивает эвристику, type_check и флаг."""

    @classmethod
    def setUpClass(cls):
        import test_build_snapshot as tbs
        cls.tmp = Path(tempfile.mkdtemp())
        cls.bundle = tbs.make_bundle(cls.tmp)
        st.save_types(cls.bundle / "security-types.json",
                      {"by_ticker": {"SBER": {"type": "fund", "source": "moex_iss", "fetched_at": "2026-10-01"},
                                     "GAZP": {"type": "stock", "source": "moex_iss", "fetched_at": "2026-10-01"}}})
        cls.s = bs.build(bs.parse_args(["--replay", str(cls.bundle), "--out", str(cls.tmp / "w1")]))
        cls.snap = json.loads(Path(cls.s["snapshot_path"]).read_text(encoding="utf-8"))
        cls.plain = bs.build(bs.parse_args(["--replay", str(tbs.make_bundle(cls.tmp / "p")), "--out",
                                            str(cls.tmp / "w2")]))

    def test_override_applied_and_checked(self):
        by = {h["ticker"]: h for h in self.snap["holdings"]}
        self.assertEqual(by["SBER"]["asset_type"], "fund")
        self.assertEqual(by["GAZP"]["asset_type"], "stock")
        tc = self.snap["type_check"]
        self.assertFalse(tc["online"])
        self.assertEqual(tc["cache"], "bundle:caches/security-types.json")
        ch = {c["ticker"]: c for c in tc["changes"]}
        self.assertEqual(list(ch), ["SBER"])
        self.assertEqual((ch["SBER"]["reason"], ch["SBER"]["moex"], ch["SBER"]["heur"]),
                         ("moex_vs_heuristic", "fund", "stock"))

    def test_flag_and_summary(self):
        self.assertIn("asset_type_changed", [f["code"] for f in self.snap["data_quality_flags"]])
        self.assertEqual(self.s["type_changes"][0]["ticker"], "SBER")
        self.assertEqual(self.s["types"], {"online": False, "fetched": 0, "failed": 0})
        self.assertIn("asset_type_changed", [f["code"] for f in self.s["attention_flags"]])

    def test_children_get_types_cache(self):
        steps = {x["step"]: x["args"] for x in self.s["steps"]}
        for name in ("portfolio_returns", "per_security_xirr"):
            self.assertIn("--types-cache", steps[name])

    def test_without_cache_nothing_changes(self):
        tc = self.plain["type_changes"]
        self.assertEqual(tc, [])
        self.assertEqual(self.plain["types"]["online"], False)
        snap = json.loads(Path(self.plain["snapshot_path"]).read_text(encoding="utf-8"))
        self.assertNotIn("asset_type_changed", [f["code"] for f in snap["data_quality_flags"]])
        self.assertIsNone(snap["type_check"]["cache"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
