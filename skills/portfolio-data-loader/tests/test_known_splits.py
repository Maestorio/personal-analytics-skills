#!/usr/bin/env python3
"""Реестр сплитов как данные: known_splits.py, подключение к расчёту, проверка split_suspected.

Контракты:
  • load: нет файла — встроенные четыре сплита; файл дополняет и перебивает по (тикер, дата);
    невалидный файл (битый JSON, чужая schema, ratio ≤ 0 или = 1, кривая дата, дубль) — KnownSplitsError,
    молчаливого отката на встроенный набор нет;
  • add / dismiss: файл создаётся, дубль — отказ, запись атомарна, перед перезаписью — копия в .backups/,
    CLI-коды 0 / 1 / 2;
  • pr.load_known_splits подменяет KNOWN_SPLITS, reconstruct_positions учитывает сплит из файла;
  • find_split_date на реальных закрытиях Мосбиржи (PLZL 2025-03-27, T 2026-04-17) даёт дату, N и дни без
    торгов, совпадающие со встроенным набором; обычное падение на 8 % — None; обратный сплит — ratio 0.1;
  • check_split_suspected: падение цены в целое число раз без записи в реестре — warning с датой и готовой
    записью; запись есть / отклонено / падение 30 % / не биржевая цена / облигация / нет прошлого — молчит;
    сбой сети — warning без даты;
  • build_snapshot: невалидный реестр — StepError до записи снапшота; поле known_splits в снапшоте.
Сеть не нужна. Запуск: python3 skills/portfolio-data-loader/tests/test_known_splits.py
"""
import datetime as dt
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import known_splits as ks  # noqa: E402
import portfolio_returns as pr  # noqa: E402
import checks as ch  # noqa: E402
import build_snapshot as bs  # noqa: E402
from test_snapshot_checks import H, SNAP  # noqa: E402
import test_build_snapshot as tbs  # noqa: E402

NOW = "2026-11-05T12:00:00+03:00"


def doc(splits=None, dismissed=None, schema="known-splits@1"):
    return {"schema": schema, "splits": splits or [], "dismissed": dismissed or []}


def S(ticker="XSPL", date="2026-01-15", ratio=10.0, note="т"):
    return {"ticker": ticker, "date": date, "ratio": ratio, "note": note,
            "added_at": NOW, "added_by": "owner"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.f = self.tmp / "Portfolio" / "known-splits.json"

    def write(self, obj):
        self.f.parent.mkdir(parents=True, exist_ok=True)
        self.f.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")


class Load(Base):
    def test_no_file_is_builtin(self):
        reg, dis = ks.load(self.f)
        self.assertEqual(set(reg), {"T", "PLZL", "GMKN", "TRNFP"})
        self.assertEqual(dis, [])
        self.assertEqual(ks.load(None)[0].keys(), reg.keys())

    def test_builtin_copy_is_independent(self):
        reg, _ = ks.load(None)
        reg["T"].clear()
        self.assertEqual(len(ks.BUILTIN["T"]), 1)

    def test_file_extends_and_sorts(self):
        self.write(doc([S("XSPL", "2026-03-01", 2.0), S("XSPL", "2025-01-10", 5.0), S("PLZL", "2026-01-01", 2.0)]))
        reg, _ = ks.load(self.f)
        self.assertEqual([e["date"] for e in reg["XSPL"]], [dt.date(2025, 1, 10), dt.date(2026, 3, 1)])
        self.assertEqual(len(reg["PLZL"]), 2)
        self.assertEqual(reg["PLZL"][0]["date"], dt.date(2025, 3, 27))

    def test_file_overrides_builtin_same_key(self):
        self.write(doc([S("PLZL", "2025-03-27", 20.0, "иначе")]))
        reg, _ = ks.load(self.f)
        self.assertEqual(len(reg["PLZL"]), 1)
        self.assertEqual(reg["PLZL"][0]["ratio"], 20.0)
        self.assertEqual(reg["PLZL"][0]["note"], "иначе")

    def test_dismissed_returned(self):
        self.write(doc(dismissed=[{"ticker": "AAA", "date": "2026-10-01", "ratio": 10.0,
                                   "dismissed_at": NOW, "note": ""}]))
        self.assertEqual(ks.load(self.f)[1][0]["ticker"], "AAA")

    def test_invalid_files_raise(self):
        bad = {
            "битый JSON": "{not json",
            "чужая schema": doc(schema="other@1"),
            "ratio ноль": doc([S(ratio=0)]),
            "ratio минус": doc([S(ratio=-2)]),
            "ratio один": doc([S(ratio=1)]),
            "ratio строка": doc([S(ratio="10")]),
            "кривая дата": doc([S(date="15.01.2026")]),
            "дата не строка": doc([S(date=20260115)]),
            "пустой тикер": doc([S(ticker=" ")]),
            "дубль": doc([S(), S()]),
            "корень не объект": [],
            "splits не список": {"schema": "known-splits@1", "splits": {}},
            "дубль отклонения": doc(dismissed=[S(), S()]),
        }
        for name, content in bad.items():
            with self.subTest(name):
                self.write(content)
                with self.assertRaises(ks.KnownSplitsError):
                    ks.load(self.f)

    def test_error_text_names_file(self):
        self.write("{")
        with self.assertRaises(ks.KnownSplitsError) as cm:
            ks.load(self.f)
        self.assertIn("known-splits.json", str(cm.exception))


class AddDismiss(Base):
    def test_add_creates_file(self):
        e = ks.add(self.f, "XSPL", "2026-01-15", 10, "тест", "site", now=NOW)
        d = json.loads(self.f.read_text(encoding="utf-8"))
        self.assertEqual(d["schema"], "known-splits@1")
        self.assertEqual(d["splits"][0], e)
        self.assertEqual((e["added_at"], e["added_by"], e["ratio"]), (NOW, "site", 10.0))
        self.assertFalse((self.f.parent / ".backups").exists())     # нечего резервировать

    def test_duplicate_refused_file_and_builtin(self):
        ks.add(self.f, "XSPL", "2026-01-15", 10, now=NOW)
        with self.assertRaises(ks.KnownSplitsError):
            ks.add(self.f, "XSPL", "2026-01-15", 5, now=NOW)
        with self.assertRaises(ks.KnownSplitsError):
            ks.add(self.f, "PLZL", "2025-03-27", 10, now=NOW)

    def test_invalid_entry_leaves_file_intact(self):
        ks.add(self.f, "XSPL", "2026-01-15", 10, now=NOW)
        before = self.f.read_bytes()
        for args in (("XSPL", "2026-02-01", 1), ("XSPL", "2026-02-01", -3), ("XSPL", "февраль", 2), ("", "2026-02-01", 2)):
            with self.assertRaises(ks.KnownSplitsError):
                ks.add(self.f, *args, now=NOW)
        self.assertEqual(self.f.read_bytes(), before)
        self.assertEqual([p.name for p in self.f.parent.iterdir() if p.suffix == ".tmp"], [])

    def test_corrupt_existing_file_not_overwritten(self):
        self.write("{oops")
        with self.assertRaises(ks.KnownSplitsError):
            ks.add(self.f, "XSPL", "2026-01-15", 10, now=NOW)
        self.assertEqual(self.f.read_text(encoding="utf-8"), "{oops")

    def test_atomic_replace_failure_keeps_original(self):
        ks.add(self.f, "XSPL", "2026-01-15", 10, now=NOW)
        before = self.f.read_bytes()
        with mock.patch.object(ks.os, "replace", side_effect=OSError("диск")):
            with self.assertRaises(OSError):
                ks.add(self.f, "YYY", "2026-02-01", 2, now=NOW)
        self.assertEqual(self.f.read_bytes(), before)
        self.assertEqual([p.name for p in self.f.parent.iterdir() if p.suffix == ".tmp" or p.name.startswith(".known")], [])

    def test_backup_before_overwrite(self):
        ks.add(self.f, "XSPL", "2026-01-15", 10, now=NOW)
        before = self.f.read_bytes()
        ks.add(self.f, "YYY", "2026-02-01", 2, now="2026-11-05T12:34:00+03:00")
        b = self.f.parent / ".backups" / "known-splits-2026-11-05-1234.json"
        self.assertEqual(b.read_bytes(), before)
        self.assertEqual(len(json.loads(self.f.read_text(encoding="utf-8"))["splits"]), 2)

    def test_load_or_new_digest_is_sha256(self):
        ks.add(self.f, "XSPL", "2026-01-15", 10, now=NOW)
        _, digest = ks._load_or_new(self.f)
        self.assertEqual(digest, hashlib.sha256(self.f.read_bytes()).hexdigest())
        new_doc, new_digest = ks._load_or_new(self.tmp / "nowhere.json")
        self.assertIsNone(new_digest)                      # файла нет — digest None
        self.assertEqual(new_doc["splits"], [])

    def test_write_atomic_stale_digest_refused(self):
        ks.add(self.f, "XSPL", "2026-01-15", 10, now=NOW)
        before = self.f.read_bytes()
        with self.assertRaises(ks.KnownSplitsError):
            ks._write_atomic(self.f, doc(), NOW, expected_digest="deadbeef")
        self.assertEqual(self.f.read_bytes(), before)
        self.assertFalse((self.f.parent / ".backups").exists())

    def test_write_atomic_matching_digest_and_add_write(self):
        ks.add(self.f, "XSPL", "2026-01-15", 10, now=NOW)
        _, digest = ks._load_or_new(self.f)
        ks._write_atomic(self.f, doc(splits=[S()]), NOW, expected_digest=digest)
        self.assertEqual(len(json.loads(self.f.read_text(encoding="utf-8"))["splits"]), 1)
        ks.add(self.f, "YYY", "2026-02-01", 2, now=NOW)        # add по-прежнему пишет при совпадении
        ks.dismiss(self.f, "AAA", "2026-10-01", 10, now=NOW)
        self.assertEqual(len(json.loads(self.f.read_text(encoding="utf-8"))["splits"]), 2)

    def test_dismiss(self):
        ks.dismiss(self.f, "AAA", "2026-10-01", 10, "не сплит", now=NOW)
        self.assertEqual(ks.load(self.f)[1][0]["ratio"], 10.0)
        with self.assertRaises(ks.KnownSplitsError):
            ks.dismiss(self.f, "AAA", "2026-10-01", 10, now=NOW)
        self.assertNotIn("AAA", ks.load(self.f)[0])       # реестр сплитов не затронут

    def test_cli_codes(self):
        run = lambda *a: ks.main(["--file", str(self.f), *a][:0] + list(a[:1]) + ["--file", str(self.f), *a[1:]])  # noqa: E731
        with mock.patch("builtins.print"):
            self.assertEqual(run("list"), 0)
            self.assertEqual(run("add", "--ticker", "XSPL", "--date", "2026-01-15", "--ratio", "10"), 0)
            self.assertEqual(run("add", "--ticker", "XSPL", "--date", "2026-01-15", "--ratio", "10"), 1)
            self.assertEqual(run("add", "--ticker", "XSPL", "--date", "2026-02-15", "--ratio", "1"), 1)
            self.assertEqual(run("dismiss", "--ticker", "AAA", "--date", "2026-10-01", "--ratio", "10"), 0)
            self.assertEqual(run("add", "--ticker", "XSPL"), 2)              # не хватает аргументов
            self.assertEqual(ks.main(["bogus", "--file", str(self.f)]), 2)   # неизвестная команда
            self.assertEqual(ks.main(["list"]), 2)                           # нет --file


class PureFunctions(Base):
    """apply_add / apply_dismiss — чистые: исходный документ цел, результат равен тому, что пишут add / dismiss."""

    def test_apply_add_pure_and_equal_to_file(self):
        src = doc()
        before = json.loads(json.dumps(src))
        out = ks.apply_add(src, {"ticker": "XSPL", "date": "2026-01-15", "ratio": 10, "note": "н", "added_by": "site"}, NOW)
        self.assertEqual(src, before)
        ks.add(self.f, "XSPL", "2026-01-15", 10, "н", "site", now=NOW)
        self.assertEqual(out, json.loads(self.f.read_text(encoding="utf-8")))
        self.assertEqual(len(out["splits"]), 1)

    def test_apply_add_refusals(self):
        out = ks.apply_add(doc(), {"ticker": "XSPL", "date": "2026-01-15", "ratio": 10}, NOW)
        with self.assertRaises(ks.DuplicateSplitError):
            ks.apply_add(out, {"ticker": "XSPL", "date": "2026-01-15", "ratio": 5}, NOW)
        with self.assertRaises(ks.DuplicateSplitError):                       # встроенный набор
            ks.apply_add(doc(), {"ticker": "PLZL", "date": "2025-03-27", "ratio": 10}, NOW)
        with self.assertRaises(ks.KnownSplitsError):
            ks.apply_add(doc(), {"ticker": "XSPL", "date": "2026-01-15", "ratio": 1}, NOW)
        with self.assertRaises(ks.KnownSplitsError):
            ks.apply_add(doc(), {"ticker": "XSPL", "date": "2026-01-15", "ratio": 2, "added_by": "кто-то"}, NOW)

    def test_apply_dismiss_pure_and_equal_to_file(self):
        src = doc()
        before = json.loads(json.dumps(src))
        out = ks.apply_dismiss(src, {"ticker": "XSPL", "date": "2026-01-15", "ratio": 10, "note": "н"}, NOW)
        self.assertEqual(src, before)
        ks.dismiss(self.f, "XSPL", "2026-01-15", 10, "н", now=NOW)
        self.assertEqual(out, json.loads(self.f.read_text(encoding="utf-8")))
        with self.assertRaises(ks.DuplicateSplitError):
            ks.apply_dismiss(out, {"ticker": "XSPL", "date": "2026-01-15", "ratio": 10}, NOW)


class Wiring(Base):
    def tearDown(self):
        pr.load_known_splits(None)

    def test_load_known_splits_end_to_end(self):
        self.write(doc([S("XSPL", "2026-01-15", 10.0)]))
        n = pr.load_known_splits(str(self.f))
        self.assertEqual(n, 5)
        t = tbs_trade = pr.Trade(ticker="XSPL", name="x", operation="Покупка", date=dt.date(2025, 6, 1), qty=10.0,
                                 price=3000.0, nominal=None, nkd=None, commission=0.0, amount=-30000.0,
                                 amount_no_comm=-30000.0, currency="RUB", note="")
        t.rub_amount = -30000.0
        p = pr.reconstruct_positions([tbs_trade], dt.date(2026, 6, 1))[("XSPL", "RUB")]
        self.assertAlmostEqual(p.qty, 100)
        pr.load_known_splits(None)                       # сброс: тикера в реестре больше нет
        self.assertNotIn("XSPL", pr.KNOWN_SPLITS)
        p = pr.reconstruct_positions([tbs_trade], dt.date(2026, 6, 1))[("XSPL", "RUB")]
        self.assertAlmostEqual(p.qty, 10)

    def test_no_file_keeps_builtin(self):
        pr.load_known_splits(str(self.f))
        self.assertEqual(set(pr.KNOWN_SPLITS), {"T", "PLZL", "GMKN", "TRNFP"})

    def test_invalid_file_not_swallowed(self):
        self.write("{")
        with self.assertRaises(ks.KnownSplitsError):
            pr.load_known_splits(str(self.f))

    def test_module_registry_equals_builtin(self):
        self.assertEqual(pr.KNOWN_SPLITS, ks.BUILTIN)

    def test_assemble_sees_loaded_registry(self):
        import assemble_snapshot as asm
        self.write(doc([S("XSPL", "2026-01-15", 10.0)]))
        pr.load_known_splits(str(self.f))
        self.assertIn("XSPL", asm._known_split_tickers())


PLZL = [("2025-03-17", 19406.5), ("2025-03-18", 19001), ("2025-03-19", 19054.5), ("2025-03-20", 19039.5),
        ("2025-03-21", 19017), ("2025-03-24", None), ("2025-03-25", None), ("2025-03-26", None),
        ("2025-03-27", 1867.6), ("2025-03-28", 1880), ("2025-03-31", 1863.6)]
TCS = [("2026-04-07", 3186.8), ("2026-04-08", 3197.6), ("2026-04-09", 3185), ("2026-04-10", 3196),
       ("2026-04-13", None), ("2026-04-14", None), ("2026-04-15", None), ("2026-04-16", None),
       ("2026-04-17", 326.26), ("2026-04-20", 325.7)]


def fx(rows):
    return lambda tk, a, b: rows


class FindDate(unittest.TestCase):
    def test_plzl_real_data_matches_builtin(self):
        r = ks.find_split_date("PLZL", "2025-03-01", "2025-04-01", fetch=fx(PLZL))
        self.assertEqual((r["date"], r["ratio"], r["halt_days"]), ("2025-03-27", 10.0, 3))
        self.assertEqual((r["prev_close"], r["new_close"]), (19017.0, 1867.6))
        b = ks.BUILTIN["PLZL"][0]
        self.assertEqual((dt.date.fromisoformat(r["date"]), r["ratio"]), (b["date"], b["ratio"]))

    def test_t_real_data_matches_builtin(self):
        r = ks.find_split_date("T", "2026-04-01", "2026-04-30", fetch=fx(TCS))
        self.assertEqual((r["date"], r["ratio"], r["halt_days"]), ("2026-04-17", 10.0, 4))
        b = ks.BUILTIN["T"][0]
        self.assertEqual((dt.date.fromisoformat(r["date"]), r["ratio"]), (b["date"], b["ratio"]))

    def test_ordinary_drop_is_none(self):
        rows = [("2026-10-01", 100.0), ("2026-10-02", 92.0), ("2026-10-03", 85.0)]
        self.assertIsNone(ks.find_split_date("X", "2026-10-01", "2026-10-05", fetch=fx(rows)))

    def test_reverse_split(self):
        rows = [("2026-10-01", 5.0), ("2026-10-02", 5.1), ("2026-10-05", 50.4)]
        r = ks.find_split_date("X", "2026-10-01", "2026-10-06", fetch=fx(rows))
        self.assertAlmostEqual(r["ratio"], 0.1)
        self.assertEqual(r["date"], "2026-10-05")

    def test_ratio_filter(self):
        self.assertIsNone(ks.find_split_date("PLZL", "2025-03-01", "2025-04-01", ratio=5.0, fetch=fx(PLZL)))
        self.assertIsNotNone(ks.find_split_date("PLZL", "2025-03-01", "2025-04-01", ratio=10.0, fetch=fx(PLZL)))

    def test_first_pair_wins_and_unsorted_input(self):
        rows = list(reversed(PLZL))
        self.assertEqual(ks.find_split_date("PLZL", "2025-03-01", "2025-04-01", fetch=fx(rows))["date"], "2025-03-27")

    def test_suspect_ratio(self):
        self.assertEqual(ks.suspect_ratio(1000, 101), 10.0)
        self.assertAlmostEqual(ks.suspect_ratio(100, 1000), 0.1)
        self.assertIsNone(ks.suspect_ratio(100, 70))
        self.assertIsNone(ks.suspect_ratio(100, 100))
        self.assertIsNone(ks.suspect_ratio(0, 100))


def PX(ticker, price, **kw):
    return H(ticker, current_price=price, **kw)


def run(prev_h, cur_h, *, splits=None, dismissed=None, fetch=None, as_of="2026-10-16", prev_as_of="2026-10-09"):
    prev = SNAP(prev_h, as_of=prev_as_of)
    cur = SNAP(cur_h, as_of=as_of)
    ctx = ch.Ctx(snap=cur, prev=prev, trades=None, as_of=as_of, splits=splits, dismissed=dismissed, fetch=fetch)
    return ch.check_split_suspected(ctx)


NEWS = [("2026-10-09", 1000.0), ("2026-10-12", 1010.0), ("2026-10-13", None), ("2026-10-14", 101.0),
        ("2026-10-15", 100.0)]


class Suspected(unittest.TestCase):
    def test_drop_tenfold_warns_with_date_and_entry(self):
        calls = []

        def fetch(tk, a, b):
            calls.append((tk, a, b))
            return NEWS
        r = run([PX("XSPL", 1000.0)], [PX("XSPL", 100.0)], fetch=fetch)
        self.assertEqual(len(r), 1)
        self.assertEqual((r[0]["id"], r[0]["level"]), ("split_suspected", "warning"))
        d = r[0]["details"]
        self.assertEqual((d["ticker"], d["ratio"], d["date"]), ("XSPL", 10.0, "2026-10-14"))
        self.assertEqual((d["prev_price"], d["cur_price"]), (1000.0, 100.0))
        self.assertEqual(d["evidence"]["halt_days"], 1)
        self.assertEqual(d["entry"]["date"], "2026-10-14")
        self.assertEqual(d["entry"]["ratio"], 10.0)
        m = r[0]["message_ru"]
        for part in ("сплит XSPL 1:10", "1 000 → 100", "14.10.2026", "после 1 дн. без торгов", "known-splits.json"):
            self.assertIn(part, m)
        self.assertEqual(calls, [("XSPL", dt.date(2026, 10, 9), dt.date(2026, 10, 16))])
        # найденная запись принимается реестром и гасит подозрение
        reg = {"XSPL": [{"date": dt.date(2026, 10, 14), "ratio": 10.0, "note": ""}]}
        self.assertEqual(run([PX("XSPL", 1000.0)], [PX("XSPL", 100.0)], splits=reg, fetch=fetch), [])

    def test_reverse_split_wording(self):
        r = run([PX("XSPL", 10.0)], [PX("XSPL", 100.0)], fetch=fx([("2026-10-09", 10.0), ("2026-10-14", 100.0)]))
        self.assertIn("обратный сплит XSPL 10:1", r[0]["message_ru"])
        self.assertAlmostEqual(r[0]["details"]["ratio"], 0.1)

    def test_registry_split_in_window_is_silent(self):
        reg = {"XSPL": [{"date": dt.date(2026, 10, 13), "ratio": 10.0, "note": ""}]}
        self.assertEqual(run([PX("XSPL", 1000.0)], [PX("XSPL", 100.0)], splits=reg, fetch=fx(NEWS)), [])

    def test_registry_split_outside_window_does_not_silence(self):
        reg = {"XSPL": [{"date": dt.date(2025, 1, 13), "ratio": 10.0, "note": ""}]}
        self.assertEqual(len(run([PX("XSPL", 1000.0)], [PX("XSPL", 100.0)], splits=reg, fetch=fx(NEWS))), 1)

    def test_dismissed_is_silent(self):
        dis = [{"ticker": "XSPL", "date": "2026-10-14", "ratio": 10.0, "dismissed_at": NOW, "note": ""}]
        self.assertEqual(run([PX("XSPL", 1000.0)], [PX("XSPL", 100.0)], dismissed=dis, fetch=fx(NEWS)), [])
        other = [dict(dis[0], ticker="OTHER")]
        self.assertEqual(len(run([PX("XSPL", 1000.0)], [PX("XSPL", 100.0)], dismissed=other, fetch=fx(NEWS))), 1)

    def test_ordinary_moves_are_silent(self):
        for p1 in (700.0, 930.0, 1100.0, 600.0):
            with self.subTest(p1):
                self.assertEqual(run([PX("XSPL", 1000.0)], [PX("XSPL", p1)], fetch=fx(NEWS)), [])

    def test_non_exchange_price_is_silent(self):
        for src in ("cost_basis", "last_trade", "balance"):
            self.assertEqual(run([PX("XSPL", 1000.0)], [PX("XSPL", 100.0, current_price_source=src)], fetch=fx(NEWS)), [])
            self.assertEqual(run([PX("XSPL", 1000.0, current_price_source=src)], [PX("XSPL", 100.0)], fetch=fx(NEWS)), [])

    def test_bond_is_silent(self):
        self.assertEqual(run([PX("RU000A0JX0J2", 1000.0, asset="bond")], [PX("RU000A0JX0J2", 100.0, asset="bond")],
                             fetch=fx(NEWS)), [])

    def test_no_prev_or_new_position_is_silent(self):
        ctx = ch.Ctx(snap=SNAP([PX("XSPL", 100.0)]), prev=None, trades=None, as_of="2026-10-16", fetch=fx(NEWS))
        self.assertEqual(ch.check_split_suspected(ctx), [])
        self.assertEqual(run([PX("OTHER", 1000.0)], [PX("XSPL", 100.0)], fetch=fx(NEWS)), [])

    def test_blocked_is_silent(self):
        self.assertEqual(run([PX("XSPL", 1000.0)], [PX("XSPL", 100.0, status="blocked")], fetch=fx(NEWS)), [])

    def test_fetch_failure_still_warns_without_date(self):
        def boom(tk, a, b):
            raise OSError("нет сети")
        r = run([PX("XSPL", 1000.0)], [PX("XSPL", 100.0)], fetch=boom)
        self.assertEqual(len(r), 1)
        self.assertIsNone(r[0]["details"]["date"])
        self.assertIsNone(r[0]["details"]["evidence"])
        self.assertNotIn("возобновились", r[0]["message_ru"])

    def test_history_without_one_day_jump_is_not_a_split(self):
        # история получена, но цена дошла до нового уровня постепенно — скачка между соседними днями нет
        hist = fx([("2026-10-09", 1000.0), ("2026-10-12", 520.0), ("2026-10-13", 260.0), ("2026-10-15", 100.0)])
        self.assertEqual(run([PX("XSPL", 1000.0)], [PX("XSPL", 100.0)], fetch=hist), [])

    def test_halving_without_jump_is_not_a_split(self):
        # падение вдвое за период между снапшотами — не сплит 1:2, если в истории нет однодневного скачка
        hist = fx([("2026-10-09", 1000.0), ("2026-10-12", 800.0), ("2026-10-14", 620.0), ("2026-10-15", 500.0)])
        self.assertEqual(run([PX("XSPL", 1000.0)], [PX("XSPL", 500.0)], fetch=hist), [])

    def test_garbage_price_ratio_is_not_a_split(self):
        # живой случай: снапшот 06.05.2026 нёс цену T 104 104 ₽ против 303,58 — отношение 343 «близко»
        # к любому целому при относительном допуске; кратность выше 10 принимается только круглая
        def boom(*a, **k):
            raise RuntimeError("сеть недоступна")
        self.assertEqual(run([PX("T", 104104.0667)], [PX("T", 311.52)], fetch=boom), [])
        self.assertEqual(run([PX("T", 303.58)], [PX("T", 104104.0667)], fetch=boom), [])

    def test_round_ratios_above_ten(self):
        self.assertEqual(ks.suspect_ratio(13000.0, 131.0), 100.0)      # GMKN, TRNFP — 1:100
        self.assertEqual(ks.suspect_ratio(5000.0, 201.0), 25.0)
        self.assertIsNone(ks.suspect_ratio(1000.0, 1000.0 / 343))
        self.assertIsNone(ks.suspect_ratio(1000.0, 1000.0 / 13))
        self.assertEqual(ks.suspect_ratio(100.0, 1010.0), 0.1)         # обратный 10:1

    def test_in_checks_registry(self):
        self.assertIn(ch.check_split_suspected, ch.CHECKS)
        res = ch.run_all(SNAP([PX("XSPL", 100.0)]), SNAP([PX("XSPL", 1000.0)], as_of="2026-10-09"), fetch=fx(NEWS))
        self.assertIn("split_suspected", [r["id"] for r in res])


class BuildSnapshotRegistry(unittest.TestCase):
    def bundle_with(self, content):
        tmp = Path(tempfile.mkdtemp())
        b = tbs.make_bundle(tmp)
        if content is not None:
            (b / "caches-start").mkdir()
            (b / "caches-start" / "known-splits.json").write_text(content, encoding="utf-8")
        return tmp, b

    def test_invalid_registry_stops_build_no_snapshot(self):
        tmp, b = self.bundle_with("{не json")
        with self.assertRaises(bs.StepError) as cm:
            bs.build(bs.parse_args(["--replay", str(b), "--out", str(tmp / "w")]))
        self.assertIn("реестра сплитов", str(cm.exception))
        self.assertEqual(list((tmp / "w").glob("portfolio-*.json")) if (tmp / "w").exists() else [], [])

    def test_invalid_explicit_file_live_mode(self):
        tmp = Path(tempfile.mkdtemp())
        trades = tmp / "trades_portfolio_1-1.xlsx"
        tbs.write_trades(trades)
        bad = tmp / "known-splits.json"
        bad.write_text(json.dumps(doc([S(ratio=1)])), encoding="utf-8")
        with self.assertRaises(bs.StepError):
            bs.build(bs.parse_args(["--trades", str(trades), "--splits-file", str(bad), "--as-of", "2026-10-16",
                                    "--no-moex", "--cbr-offline", "--no-iis-search", "--out", str(tmp / "w")]))
        self.assertFalse((tmp / "w" / "portfolio-2026-10-16.json").exists())

    def test_replay_takes_registry_from_bundle(self):
        tmp, b = self.bundle_with(json.dumps(doc([S("XSPL", "2026-01-15", 10.0)])))
        s = bs.build(bs.parse_args(["--replay", str(b), "--out", str(tmp / "w")]))
        snap = json.loads(Path(s["snapshot_path"]).read_text(encoding="utf-8"))
        self.assertEqual(snap["known_splits"], {"source": "file", "file": "known-splits.json", "count": 5})
        pr.load_known_splits(None)

    def test_no_registry_is_builtin(self):
        tmp, b = self.bundle_with(None)
        s = bs.build(bs.parse_args(["--replay", str(b), "--out", str(tmp / "w")]))
        snap = json.loads(Path(s["snapshot_path"]).read_text(encoding="utf-8"))
        self.assertEqual(snap["known_splits"], {"source": "builtin", "file": None, "count": 4})

    def test_split_suspected_is_a_decision(self):
        self.assertIn("split_suspected", bs.DECISIONS)
        self.assertIn("known-splits.json", bs.DECISIONS["split_suspected"])


if __name__ == "__main__":
    unittest.main()
