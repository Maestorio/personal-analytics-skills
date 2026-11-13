#!/usr/bin/env python3
"""API-1b PR-2: build_snapshot.py — оркестратор Шагов 1–7 SKILL.md без LLM.

Контракты:
  • сквозная сборка на синтетической выгрузке IntelInvest через --replay пакета с
    пустым net/index.json: сеть не трогается, MOEX «недоступен» → фолбэк --no-moex с
    флагом moex_unavailable (как Шаг 3/5 SKILL.md), снапшот собирается;
  • повтор детерминирован: два --replay одного пакета → одинаковый snapshot_sha256;
    as_of_date и extraction_date — из manifest.json, не из часов (PDL_AS_OF, --as-of);
  • per_security_xirr идёт ПОСЛЕ котировок и получает --quotes quotes.json (одна цена в holdings и
    per_instrument_xirr, случай 27.10); при недоступном MOEX — --no-moex без --quotes;
  • --commit с --replay запрещён (повтор не пишет в Claude-Memory); шаг securities_index упразднён (нет ни шага, ни флага);
  • commit_snapshot: атомарная запись; снапшот того же дня сначала уходит в .versions/
    (archive_snapshot.py, PDL-SNAPV), потом перезапись под тем же именем;
  • --commit без --working пишет в snapshots/auto/portfolio-ДАТА-ЧЧММ-skill.json (+ build-summary с тем же суффиксом),
    рабочую папку, .versions/, журнал и индекс не трогает; --commit --working — рабочая папка (commit_guarded, журнал, индекс);
  • --working-коммит не ухудшает снапшот дня (как «Сохранить» на сайте): «только сделки» поверх сохранённого с балансом или
    с внесённым кэшем → StepError (код 1) до архивации и записи; --allow-downgrade — осознанная перезапись;
  • find_prev_snapshot: самый свежий portfolio-*.json с балансом и датой ≤ as_of (без баланса — пропуск);
    find_compare_snapshot: самый свежий снапшот скилла ≤ as_of любого типа (база сравнения сайта);
    find_iis_trades: самая свежая выгрузка ИИС-3; active_tickers: без blocked и qty ≤ 0;
  • decisions: cash_drift_changed / iis_* из флагов снапшота → вопросы владельцу;
  • moex_quotes.py --health выходит с кодом 0 и при недоступном ISS (признак — "ok" в
    JSON): здоровье MOEX читается из JSON, не из кода выхода (найдено этим тестом).
Сеть не нужна (≈10 с: несколько подпроцессов загрузчика).
Запуск: python3 skills/portfolio-data-loader/tests/test_build_snapshot.py
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import build_snapshot as bs  # noqa: E402

HEADER = ("Тикер", "Название", "Операция", "Дата", "Кол-во", "Цена", "Номинал", "НКД", "Комиссия",
          "Сумма", "Сумма без комиссии", "Валюта", "Заметка")
ROWS = [
    ("Деньги (RUB)", "Российский рубль", "Внесение", "2026-01-12", None, None, None, None, 0.0,
     100000.0, 100000.0, "RUB", "зачисление"),
    ("SBER", "Сбербанк", "Покупка", "2026-01-13", 100.0, 280.0, None, None, 14.0, 28014.0, 28000.0, "RUB", None),
    ("Деньги (RUB)", "Российский рубль", "Списание", "2026-01-13", None, None, None, None, 0.0,
     -28014.0, -28014.0, "RUB", "за сделку"),
    ("GAZP", "Газпром", "Покупка", "2026-02-02", 200.0, 130.0, None, None, 13.0, 26013.0, 26000.0, "RUB", None),
    ("Деньги (RUB)", "Российский рубль", "Списание", "2026-02-02", None, None, None, None, 0.0,
     -26013.0, -26013.0, "RUB", "за сделку"),
    ("SBER", "Сбербанк", "Дивиденд", "2026-07-20", 100.0, None, None, None, 0.0, 3300.0, 3300.0, "RUB", None),
    ("Деньги (RUB)", "Российский рубль", "Внесение", "2026-07-20", None, None, None, None, 0.0,
     3300.0, 3300.0, "RUB", "дивиденд"),
    ("SBER", "Сбербанк", "Продажа", "2026-10-01", 20.0, 300.0, None, None, 3.0, -5997.0, -6000.0, "RUB", None),
    ("Деньги (RUB)", "Российский рубль", "Внесение", "2026-10-01", None, None, None, None, 0.0,
     5997.0, 5997.0, "RUB", "за сделку"),
]


def write_trades(path: Path) -> None:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(("intelinvest.ru",) + (None,) * 12)
    ws.append(HEADER)
    for r in ROWS:
        ws.append(r)
    wb.save(path)


def make_bundle(root: Path, as_of="2026-10-16") -> Path:
    b = root / "bundle"
    (b / "inputs").mkdir(parents=True)
    (b / "net").mkdir()
    (b / "net" / "index.json").write_text("{}", encoding="utf-8")
    write_trades(b / "inputs" / "trades_portfolio_1-1.xlsx")
    (b / "manifest.json").write_text(json.dumps({
        "kind": "pdl-run-bundle@1", "as_of": as_of,
        "inputs": {"trades": "trades_portfolio_1-1.xlsx"}, "decisions": {}}), encoding="utf-8")
    return b


class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.bundle = make_bundle(cls.tmp)
        t0 = time.monotonic()
        cls.s1 = bs.build(bs.parse_args(["--replay", str(cls.bundle), "--out", str(cls.tmp / "w1")]))
        cls.s2 = bs.build(bs.parse_args(["--replay", str(cls.bundle), "--out", str(cls.tmp / "w2")]))
        cls.seconds = time.monotonic() - t0
        cls.snap = json.loads(Path(cls.s1["snapshot_path"]).read_text(encoding="utf-8"))

    def test_builds_snapshot_without_balance(self):
        # Только сделки → позиции из сделок (решение 2026-10-21: «Общий баланс» необязателен);
        # до него здесь был returns-only снапшот без позиций (holdings = null)
        self.assertEqual(self.snap["schema_version"], "2.0")
        self.assertEqual(self.snap["as_of_date"], "2026-10-16")
        self.assertEqual(self.snap["snapshot_type"], "trades_holdings")
        by = {h["ticker"]: h for h in self.snap["holdings"]}
        self.assertEqual((by["SBER"]["qty"], by["GAZP"]["qty"]), (80, 200))
        self.assertEqual(by["SBER"]["avg_cost_source"], "trades")
        pix = self.snap["per_instrument_xirr"]
        self.assertEqual(pix["SBER"]["qty_now"], 80)
        codes = [f["code"] for f in self.snap["data_quality_flags"]]
        self.assertIn("balance_absent_holdings_from_trades", codes)
        self.assertIn("no_prev_snapshot_for_trades_mode", codes)     # в пакете прошлого снапшота нет
        self.assertNotIn("no_balance_file", codes)

    def test_moex_fallback_flagged(self):
        self.assertTrue(self.s1["fallbacks"]["moex_down"])
        self.assertIn("moex_unavailable", [f["code"] for f in self.snap["data_quality_flags"]])

    def test_replay_is_deterministic(self):
        self.assertEqual(self.s1["snapshot_sha256"], self.s2["snapshot_sha256"])

    def test_replay_does_not_wait_for_retries(self):
        self.assertLess(self.seconds, 90)

    def test_summary_shape(self):
        for k in ("as_of", "mode", "holdings", "checks", "decisions", "steps", "blocked", "committed"):
            self.assertIn(k, self.s1)
        self.assertEqual(self.s1["mode"], "replay")
        self.assertFalse(self.s1["committed"])
        self.assertTrue((self.tmp / "w1" / "build-summary.json").exists())
        self.assertIn("portfolio-2026-10-16.json", bs.render(self.s1))

    def test_per_security_after_quotes_with_quotes_arg(self):
        steps = [x["step"] for x in self.s1["steps"]]
        self.assertGreater(steps.index("per_security_xirr"), steps.index("moex_health"))
        ps = next(x for x in self.s1["steps"] if x["step"] == "per_security_xirr")
        self.assertIn("--no-moex", ps["args"])           # MOEX лежит → без --quotes
        self.assertNotIn("--quotes", ps["args"])

    def test_quotes_passed_when_moex_up(self):
        import subprocess
        orig_run, orig_health = bs.Runner.run, bs._health_ok
        seen = []

        def fake_run(self_, name, script, args, stdout=None, check=True):
            if name == "moex_quotes":
                stdout.write_text(json.dumps({"quotes": {"SBER": {"last": 290.0}, "GAZP": {"last": 125.0}}}),
                                  encoding="utf-8")
                self_.log.append({"step": name, "script": script.name, "args": args, "rc": 0, "seconds": 0})
                return subprocess.CompletedProcess([], 0, "", "")
            if name == "per_security_xirr":
                seen.append((len(self_.log), list(args)))
            return orig_run(self_, name, script, args, stdout=stdout, check=check)
        bs.Runner.run, bs._health_ok = fake_run, lambda p: True
        try:
            s = bs.build(bs.parse_args(["--replay", str(self.bundle), "--out", str(self.tmp / "w4")]))
        finally:
            bs.Runner.run, bs._health_ok = orig_run, orig_health
        steps = [x["step"] for x in s["steps"]]
        self.assertLess(steps.index("moex_quotes"), steps.index("per_security_xirr"))
        args = seen[0][1]
        self.assertEqual(args[args.index("--quotes") + 1], str(self.tmp / "w4" / "quotes.json"))
        self.assertNotIn("--no-moex", args)

    def test_commit_with_replay_refused(self):
        with self.assertRaises(bs.StepError):
            bs.build(bs.parse_args(["--replay", str(self.bundle), "--out", str(self.tmp / "w3"),
                                    "--commit", "--memory", str(self.tmp / "cm")]))
        self.assertFalse((self.tmp / "cm").exists())

    def test_no_securities_index_step(self):
        # индекс бумаги упразднён (шаг 15): ни шага, ни флага; скрипта нет
        self.assertFalse(hasattr(bs.parse_args(["--commit"]), "skip_index"))
        self.assertFalse((bs.HERE / "securities_index.py").exists())
        src = Path(bs.__file__).read_text(encoding="utf-8")
        self.assertNotIn("securities_index", src)


class PlanFlag(unittest.TestCase):
    """--plan (этап 1 ухода от Numbers): аргумент, проброс в assemble, строка сводки."""

    def test_arg_and_wiring(self):
        self.assertIsNone(bs.parse_args([]).plan)
        self.assertEqual(bs.parse_args(["--plan", "/x/plan.json"]).plan, "/x/plan.json")
        self.assertFalse(bs.parse_args([]).plan_primary)
        self.assertTrue(bs.parse_args(["--plan-primary"]).plan_primary)
        src = Path(bs.__file__).read_text(encoding="utf-8")
        self.assertIn('a += ["--plan", str(plan_file)]', src)
        self.assertIn('a.append("--plan-primary")', src)
        self.assertIn('"Portfolio" / "plan.json"', src)          # автоподхват из --memory

    def test_render_line(self):
        base = {"as_of": "2026-10-27", "mode": "live", "holdings": 1, "xirr_restricted": None,
                "flags_by_severity": {}, "decisions": [], "checks": [], "snapshot_path": "/w/p.json"}
        out = bs.render({**base, "plan_check": {"source": "both", "plan_file": "plan.json",
                                                "plan_updated_at": "2026-10-27", "n_diff": 3}})
        self.assertIn("План: plan.json от 2026-10-27, расхождений 3", out)
        self.assertNotIn("главный источник", out)
        out = bs.render({**base, "plan_check": {"source": "plan_primary", "plan_file": "plan.json",
                                                "plan_updated_at": "2026-10-27", "n_diff": 1}})
        self.assertIn("План: главный источник — plan.json", out)
        self.assertNotIn("План:", bs.render({**base, "plan_check": None}))


class ParityWiring(unittest.TestCase):
    """--parity-against и авто-сверка (этап 6 ухода от Numbers): replay без сети, расхождения не блокируют."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.bundle = make_bundle(cls.tmp)
        cls.first = bs.build(bs.parse_args(["--replay", str(cls.bundle), "--out", str(cls.tmp / "w0")]))
        snap = json.loads(Path(cls.first["snapshot_path"]).read_text(encoding="utf-8"))
        snap["input_files"]["balance"] = "Общий баланс.numbers"           # «снапшот с балансом» того же дня
        cls.ref = cls.tmp / "ref.json"
        cls.ref.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")

    def test_no_reference_means_null(self):
        self.assertIsNone(self.first["parity"])
        snap = json.loads(Path(self.first["snapshot_path"]).read_text(encoding="utf-8"))
        self.assertIn("parity", snap)
        self.assertIsNone(snap["parity"])

    def test_parity_against_in_snapshot_and_summary(self):
        s = bs.build(bs.parse_args(["--replay", str(self.bundle), "--out", str(self.tmp / "w1"),
                                    "--parity-against", str(self.ref)]))
        p = s["parity"]
        self.assertEqual((p["same_day"], p["auto"], p["against_date"]), (True, False, "2026-10-16"))
        self.assertEqual(p["diverged"], 0)                                 # input_files.balance — в известных
        self.assertGreater(p["known"], 0)
        self.assertTrue(Path(p["report_path"]).is_file())
        self.assertEqual(Path(p["report_path"]).name, "parity-report.md")
        snap = json.loads(Path(s["snapshot_path"]).read_text(encoding="utf-8"))
        self.assertEqual(snap["parity"]["diverged"], 0)
        self.assertNotIn("report_path", snap["parity"])                    # путь рабочей папки в снапшот не идёт
        self.assertFalse(s["blocked"])
        self.assertIn("Сверка с балансом (2026-10-16): совпало", bs.render(s))

    def test_divergence_does_not_block(self):
        ref = json.loads(self.ref.read_text(encoding="utf-8"))
        ref["holdings"][0]["qty"] += 5
        bad = self.tmp / "ref-bad.json"
        bad.write_text(json.dumps(ref, ensure_ascii=False), encoding="utf-8")
        s = bs.build(bs.parse_args(["--replay", str(self.bundle), "--out", str(self.tmp / "w2"),
                                    "--parity-against", str(bad)]))
        self.assertEqual(s["parity"]["diverged"], 1)
        self.assertTrue(s["parity"]["diverged_paths"][0].endswith(".qty"))
        self.assertFalse(s["blocked"])
        self.assertIn("расходится 1", bs.render(s))

    def test_auto_picks_same_day_snapshot_with_balance(self):
        mem = self.tmp / "mem"
        (mem / "Portfolio" / "snapshots").mkdir(parents=True)
        (mem / "Portfolio" / "snapshots" / "portfolio-2026-10-16.json").write_text(
            self.ref.read_text(encoding="utf-8"), encoding="utf-8")
        s = bs.build(bs.parse_args(["--replay", str(self.bundle), "--out", str(self.tmp / "w3"),
                                    "--memory", str(mem)]))
        self.assertTrue(s["parity"]["auto"])
        self.assertEqual(s["parity"]["diverged"], 0)

    def test_hash_stable_with_parity(self):
        a = bs.build(bs.parse_args(["--replay", str(self.bundle), "--out", str(self.tmp / "w4"),
                                    "--parity-against", str(self.ref)]))
        b = bs.build(bs.parse_args(["--replay", str(self.bundle), "--out", str(self.tmp / "w5"),
                                    "--parity-against", str(self.ref)]))
        self.assertEqual(a["snapshot_sha256"], b["snapshot_sha256"])

    def test_arg_default(self):
        self.assertIsNone(bs.parse_args([]).parity_against)
        self.assertEqual(bs.parse_args(["--parity-against", "/x.json"]).parity_against, "/x.json")


class PlanInBundle(unittest.TestCase):
    """--record кладёт plan.json в caches-start/, --replay без --plan берёт его оттуда: штатный путь «сделки + план»."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.trades = cls.tmp / "trades_portfolio_1-1.xlsx"
        write_trades(cls.trades)
        cls.plan = cls.tmp / "plan.json"
        cls.plan.write_text(json.dumps({
            "schema_version": "plan@1.0", "updated_at": "2026-10-15", "updated_by": "hub-api",
            "source": {"kind": "site"}, "classes": [{"class": "Акции", "share": 1.0}],
            "stocks": {}, "bonds": {}, "funds": {}, "manual_positions": [],
            "ie_model": {"extraction_date": "2026-10-15", "positions": []}}, ensure_ascii=False), encoding="utf-8")
        cls.bundle = cls.tmp / "rec"
        cls.rec = bs.build(bs.parse_args(["--trades", str(cls.trades), "--plan", str(cls.plan), "--as-of", "2026-10-16",
                                          "--no-moex", "--cbr-offline", "--no-iis-search",
                                          "--record", str(cls.bundle), "--out", str(cls.tmp / "wr")]))

    def _codes(self, s):
        snap = json.loads(Path(s["snapshot_path"]).read_text(encoding="utf-8"))
        return snap, [f["code"] for f in snap["data_quality_flags"]]

    def test_record_stores_plan(self):
        self.assertTrue((self.bundle / "caches-start" / "plan.json").is_file())
        self.assertEqual((self.bundle / "caches-start" / "plan.json").read_bytes(), self.plan.read_bytes())

    def test_replay_without_plan_arg_uses_bundle_plan(self):
        r1 = bs.build(bs.parse_args(["--replay", str(self.bundle), "--out", str(self.tmp / "w1")]))
        r2 = bs.build(bs.parse_args(["--replay", str(self.bundle), "--out", str(self.tmp / "w2")]))
        snap, codes = self._codes(r1)
        self.assertTrue(snap["plan_check"]["applied"])
        self.assertNotIn("no_plan_for_trades_mode", codes)
        self.assertEqual(r1["snapshot_sha256"], r2["snapshot_sha256"])

    def test_bundle_without_plan_keeps_old_behaviour(self):
        b = make_bundle(self.tmp / "noplan_root") if (self.tmp / "noplan_root").mkdir() is None else None
        r = bs.build(bs.parse_args(["--replay", str(b), "--out", str(self.tmp / "w3")]))
        snap, codes = self._codes(r)
        self.assertIn("no_plan_for_trades_mode", codes)
        self.assertFalse((snap.get("plan_check") or {}).get("applied"))


class BondBucketWiring(unittest.TestCase):
    """Сайт: план — копия в папке прогона, справочник типов — в /data. Рядом с --plan его нет, поэтому build_snapshot
    передаёт assemble `--types-cache` явно (29.10: attrs_missing=true, у всех облигаций bucket_source=plan)."""

    def test_types_cache_outside_plan_folder_derives_bucket(self):
        tmp = Path(tempfile.mkdtemp())
        rows = ROWS + [
            ("SU26238RMFS4", "ОФЗ 26238", "Покупка", "2026-03-02", 10.0, 70.0, 1000.0, 5.0, 1.0, 7000.0, 6999.0, "RUB", None),
            ("Деньги (RUB)", "Российский рубль", "Списание", "2026-03-02", None, None, None, None, 0.0,
             -7000.0, -7000.0, "RUB", "за сделку")]
        global_rows = list(ROWS)
        ROWS[:] = rows
        try:
            trades = tmp / "trades_portfolio_1-1.xlsx"
            write_trades(trades)
        finally:
            ROWS[:] = global_rows
        site = tmp / "site"
        site.mkdir()
        (site / "plan.json").write_text(json.dumps({
            "schema_version": "plan@1.0", "updated_at": "2026-10-15", "updated_by": "hub-api",
            "source": {"kind": "site"}, "classes": [{"class": "Акции", "share": 1.0}], "stocks": {},
            "bonds": {"RU000A1038V6": {"type": "ОФЗ", "subtype": "<10"}}, "funds": {}, "manual_positions": [],
            "ie_model": {"extraction_date": "2026-10-15", "positions": []}}, ensure_ascii=False), encoding="utf-8")
        types = tmp / "data" / "security-types.json"
        types.parent.mkdir()
        types.write_text(json.dumps({"by_ticker": {"SU26238RMFS4": {
            "type": "bond", "isin": "RU000A1038V6",
            "bond": {"issuer_type": "ofz", "matdate": "2041-05-15", "faceunit": "SUR", "is_floater": False}}}}),
            encoding="utf-8")
        s = bs.build(bs.parse_args(["--trades", str(trades), "--plan", str(site / "plan.json"),
                                    "--types-cache", str(types), "--as-of", "2026-10-16", "--no-moex",
                                    "--cbr-offline", "--no-iis-search", "--out", str(tmp / "w")]))
        snap = json.loads(Path(s["snapshot_path"]).read_text(encoding="utf-8"))
        bonds = [h for h in snap["holdings"] if h.get("asset_type") == "bond"]
        self.assertTrue(bonds)
        self.assertEqual({h.get("bucket_source") for h in bonds}, {"iss"})
        self.assertFalse(snap["bond_bucket_check"]["attrs_missing"])


class Helpers(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_find_prev_snapshot(self):
        d = self.tmp / "snapshots"
        d.mkdir()
        for name in ("portfolio-2026-10-13.json", "portfolio-2026-10-16.json", "portfolio-2026-10-20.json",
                     "portfolio-2026-10-15.json.tmp", "notes.md"):
            (d / name).write_text("{}")
        self.assertEqual(bs.find_prev_snapshot(d, "2026-10-17").name, "portfolio-2026-10-16.json")
        self.assertEqual(bs.find_prev_snapshot(d, "2026-10-16").name, "portfolio-2026-10-16.json")
        self.assertIsNone(bs.find_prev_snapshot(d, "2026-01-01"))
        self.assertIsNone(bs.find_prev_snapshot(self.tmp / "nope", "2026-10-17"))

    def test_find_prev_snapshot_skips_trades_only(self):
        # 27.10: сборка без баланса поверх снапшота без баланса теряла кэш (drift = null) и метку переноса
        d = self.tmp / "snapshots"
        d.mkdir()
        (d / "portfolio-2026-10-23.json").write_text(json.dumps({"snapshot_type": None}))
        (d / "portfolio-2026-10-27.json").write_text(json.dumps({"snapshot_type": "trades_holdings"}))
        (d / "portfolio-2026-10-26.json").write_text("{битый")
        self.assertEqual(bs.find_prev_snapshot(d, "2026-10-27").name, "portfolio-2026-10-23.json")

    def test_find_compare_snapshot_ignores_cache_anchor_rule(self):
        # 28.10: свежий снапшот скилла без баланса (trades_holdings, без кэша) — опора кэша 23.10, база сравнения 28.10
        d = self.tmp / "snapshots"
        d.mkdir()
        (d / "portfolio-2026-10-23.json").write_text(json.dumps({"snapshot_type": None}))
        (d / "portfolio-2026-10-28.json").write_text(json.dumps({"snapshot_type": "trades_holdings"}))
        (d / "portfolio-2026-10-30.json").write_text("{}")
        self.assertEqual(bs.find_prev_snapshot(d, "2026-10-28").name, "portfolio-2026-10-23.json")
        self.assertEqual(bs.find_compare_snapshot(d, "2026-10-28").name, "portfolio-2026-10-28.json")
        self.assertEqual(bs.find_compare_snapshot(d, "2026-10-27").name, "portfolio-2026-10-23.json")
        self.assertIsNone(bs.find_compare_snapshot(d, "2026-01-01"))
        self.assertIsNone(bs.find_compare_snapshot(self.tmp / "nope", "2026-10-28"))

    def test_find_iis_trades_latest_by_date_folder(self):
        # Portfolio/inputs/<дата>/ — свежесть по папке-дате, а не по mtime (Drive переписывает mtime)
        inputs = self.tmp / "inputs"
        old = inputs / "2026-10-13" / "trades_portfolio_838526-3.xlsx"
        new = inputs / "2026-10-21" / "trades_portfolio_838526-4.xlsx"
        for p in (old, new):
            p.parent.mkdir(parents=True)
            p.write_text("x")
        (inputs / "2026-10-21" / "trades_portfolio_707160-48.xlsx").write_text("z")
        os.utime(new, (1, 1))                      # старый mtime у свежего файла
        self.assertEqual(bs.find_iis_trades([inputs]), new)
        self.assertIsNone(bs.find_iis_trades([self.tmp / "nope"]))

    def test_no_iis_search_outside_memory(self):
        # без --memory и --iis-dir не ищем нигде — блок ИИС-3 перенесётся из прошлого снапшота
        self.assertFalse(hasattr(bs, "DEFAULT_IIS_DIRS"))

    def test_active_tickers(self):
        r = {"snapshot_current": {"positions": [
            {"ticker": "SBER", "qty": 10}, {"ticker": "FXUS", "qty": 5, "is_blocked": True},
            {"ticker": "OLD", "qty": 0}]}}
        self.assertEqual(bs.active_tickers(r), ["SBER"])

    def test_commit_snapshot_archives_then_overwrites(self):          # PDL-SNAPV
        src = self.tmp / "s.json"
        src.write_text('{"v": 2, "generated_at": "2026-10-16T18:21:16"}')
        d = self.tmp / "cm" / "Portfolio" / "snapshots"
        d.mkdir(parents=True)
        (d / "portfolio-2026-10-16.json").write_text('{"v": 1, "generated_at": "2026-10-16T00:45:47"}')
        dest, arc = bs.commit_snapshot(src, d, "2026-10-16")
        self.assertEqual(json.loads(dest.read_text())["v"], 2)
        self.assertTrue(arc["archived"])
        self.assertEqual(sorted(p.name for p in d.iterdir()), [".versions", "portfolio-2026-10-16.json"])
        self.assertEqual(json.loads(Path(arc["to"]).read_text())["v"], 1)

    def test_commit_snapshot_first_of_day_no_archive(self):
        src = self.tmp / "s.json"
        src.write_text('{"v": 1}')
        d = self.tmp / "snaps"
        dest, arc = bs.commit_snapshot(src, d, "2026-10-16")
        self.assertFalse(arc["archived"])
        self.assertEqual(sorted(p.name for p in d.iterdir()), ["portfolio-2026-10-16.json"])

    def _guard_setup(self, old: dict):
        d = self.tmp / "g" / "snapshots"
        d.mkdir(parents=True, exist_ok=True)
        (d / "portfolio-2026-10-30.json").write_text(json.dumps(old))
        return d

    def _guard_commit(self, d, new, allow=False):
        src = self.tmp / "g" / "new.json"
        src.write_text(json.dumps(new))
        return bs.commit_guarded(new, src, d, "2026-10-30", allow)

    TRADES = {"snapshot_type": "trades_holdings", "v": "new"}
    WITH_BAL = {"snapshot_type": "full", "v": "old", "input_files": {"balance": "b.numbers"}}
    WITH_CASH = {"snapshot_type": "trades_holdings", "v": "old", "cash_reconciliation": {"current_drift_rub": 1234.0}}

    def test_guard_trades_only_over_balance_refused(self):         # сайт: 409 balance
        d = self._guard_setup(self.WITH_BAL)
        before = (d / "portfolio-2026-10-30.json").read_text()
        with self.assertRaises(bs.StepError) as cm:
            self._guard_commit(d, self.TRADES)
        self.assertIn("с балансом", str(cm.exception))
        self.assertEqual((d / "portfolio-2026-10-30.json").read_text(), before)
        self.assertEqual(sorted(p.name for p in d.iterdir()), ["portfolio-2026-10-30.json"])   # без .versions/

    def test_guard_trades_only_over_cash_refused(self):            # сайт: 409 cash_fact
        d = self._guard_setup(self.WITH_CASH)
        before = (d / "portfolio-2026-10-30.json").read_text()
        with self.assertRaises(bs.StepError) as cm:
            self._guard_commit(d, self.TRADES)
        self.assertIn("кэш", str(cm.exception))
        self.assertEqual((d / "portfolio-2026-10-30.json").read_text(), before)
        self.assertFalse((d / ".versions").exists())

    def test_guard_trades_over_trades_without_cash_writes(self):
        d = self._guard_setup({"snapshot_type": "trades_holdings", "v": "old",
                               "cash_reconciliation": {"current_drift_rub": None}})
        dest, _ = self._guard_commit(d, self.TRADES)
        self.assertEqual(json.loads(dest.read_text())["v"], "new")

    def test_guard_balance_build_over_anything_writes(self):
        for old in (self.WITH_BAL, self.WITH_CASH):
            d = self._guard_setup(old)
            dest, _ = self._guard_commit(d, {"snapshot_type": "full", "v": "new"})
            self.assertEqual(json.loads(dest.read_text())["v"], "new")

    def test_guard_allow_downgrade_writes_and_archives(self):
        d = self._guard_setup(self.WITH_BAL)
        dest, arc = self._guard_commit(d, self.TRADES, allow=True)
        self.assertEqual(json.loads(dest.read_text())["v"], "new")
        self.assertTrue(arc["archived"])
        self.assertEqual(json.loads(Path(arc["to"]).read_text())["v"], "old")

    def test_commit_probe_writes_to_auto_and_leaves_working_alone(self):
        src = self.tmp / "p.json"
        src.write_text('{"v": 3}')
        d = self.tmp / "pr" / "snapshots"
        d.mkdir(parents=True)
        (d / "portfolio-2026-10-30.json").write_text('{"v": "working"}')
        now = __import__("datetime").datetime(2026, 10, 30, 14, 7)
        dest, summ = bs.commit_probe(src, d, "2026-10-30", now)
        self.assertEqual(dest, d / "auto" / "portfolio-2026-10-30-1407-skill.json")
        self.assertEqual(summ, d / "auto" / "build-summary-2026-10-30-1407-skill.json")
        self.assertEqual(json.loads(dest.read_text())["v"], 3)
        self.assertEqual(json.loads((d / "portfolio-2026-10-30.json").read_text())["v"], "working")   # рабочий цел
        self.assertFalse((d / ".versions").exists())                                                   # без архивации
        self.assertEqual(sorted(p.name for p in d.iterdir()), ["auto", "portfolio-2026-10-30.json"])
        # «последний рабочий» не видит пробу: SNAP_RE и поиск смотрят только snapshots/
        self.assertIsNone(bs.SNAP_RE.match(dest.name))
        (d / "portfolio-2026-10-30.json").unlink()
        self.assertIsNone(bs.find_compare_snapshot(d, "2026-10-31"))

    def test_working_flag(self):
        self.assertFalse(bs.parse_args(["--commit"]).working)
        self.assertTrue(bs.parse_args(["--commit", "--working"]).working)

    def test_guard_flag_and_exit_code(self):
        self.assertFalse(bs.parse_args([]).allow_downgrade)
        self.assertTrue(bs.parse_args(["--allow-downgrade"]).allow_downgrade)

    def test_snapshot_hash_ignores_generated_at(self):
        a = {"generated_at": "1", "x": 1}
        self.assertEqual(bs.snapshot_hash(a), bs.snapshot_hash({"generated_at": "2", "x": 1}))
        self.assertNotEqual(bs.snapshot_hash(a), bs.snapshot_hash({"generated_at": "1", "x": 2}))

    def test_health_ok_reads_json_not_exit_code(self):
        import subprocess
        mk = lambda rc, out: subprocess.CompletedProcess([], rc, out, "")
        self.assertFalse(bs._health_ok(mk(0, '{"ok": false, "error": "x"}')))
        self.assertTrue(bs._health_ok(mk(0, '{"ok": true}')))
        self.assertFalse(bs._health_ok(mk(1, '{"ok": true}')))
        self.assertFalse(bs._health_ok(mk(0, "not json")))

    def test_quotes_ok(self):                                         # сбой котировок 2026-10-21
        q = self.tmp / "q.json"
        for text, want in (('{"quotes": {"SBER": {"last": 1}}}', True), ('{"quotes": {}, "count_err": 65}', False),
                           ("", False), ("not json", False), ("[]", False)):
            q.write_text(text)
            self.assertEqual(bs.quotes_ok(q), want, text)
        self.assertFalse(bs.quotes_ok(self.tmp / "nope.json"))

    def test_decisions_cover_owner_flags(self):
        self.assertEqual(set(bs.DECISIONS), {"cash_drift_changed", "cash_fact_stale", "iis_returns_mismatch",
                                             "iis_composition_changed", "split_suspected"})


if __name__ == "__main__":
    unittest.main(verbosity=1)
