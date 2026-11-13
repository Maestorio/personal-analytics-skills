#!/usr/bin/env python3
"""Выгрузка CSV ZenMoney на сайте (этап «Деньги» 3.6, бэкенд): tools/hosting/notify/zm_csv.py, маршруты
hub-notify и зона /api/zm/* hub-api. Устройство — docs/zenmoney/csv-site.md.

Контракты:
  • parse_csv: разделитель «;», BOM, нет обязательной колонки → ValueError с перечнем;
  • completeness: норма; выгрузка с фильтром по датам (строк меньше прошлой >1 %) → стоп; месяц прошлой выгрузки пропал → стоп (пустой месяц сам по себе — нет);
    месяц последней операции не закончен → предупреждение (в «к записи» не идёт);
  • op_diff: добавлено / удалено / изменено (тот же ключ, другая категория/место/комментарий/дата), потерян
    тег поездки; разбивка по месяцам;
  • recompute: без aux — unavailable, месяцы пустые; с aux — месяцы add/replace/same; курсы из кэша
    aux/rates-cbr.json (GEL → ₽), сети нет; сеть ЦБ недоступна → стоп «нет курсов за …»; расхождение
    «объяснимо» удалённой/изменённой операцией, итог без операций → стоп «необъяснимое расхождение»;
  • apply: через заглушки read/save пишет spending.json/trips.json/facts.json и last.csv, помечает отчёт
    applied_at; отказ (409) при стопах, без confirm, при другом sha256, без отчёта, повторно;
  • hub-api: загрузка base64 → incoming/<id>.csv (id = дата-sha[:8]), колонки проверяются, state, прокси
    csv-report/csv-apply в hub-notify (urlopen подменён), whitelist зоны задач, /api/health.zm_csv.
Сеть не нужна. 403 без пароля проверяет Caddy (test_caddy_zones.py), не этот тест.
Запуск: python3 tools/tests/test_zm_csv.py
"""
import base64
import csv
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pages_stand import serve  # noqa: E402
sys.path.insert(0, str(REPO / "tools/hosting/api"))
sys.path.insert(0, str(REPO / "tools/hosting/notify"))

import server  # noqa: E402
import zm_csv  # noqa: E402

MSK = timezone(timedelta(hours=3))
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=MSK)
COLS = list(zm_csv.REQUIRED_COLUMNS)
_n = [0]


def row(date, cat, amount, acc="Карта", cur="RUB", payee="", comment="", income=False, changed="2026-07-01 00:00:00"):
    _n[0] += 1
    c = _n[0]
    r = {k: "" for k in COLS}
    r.update(date=date, categoryName=cat, payee=payee, comment=comment, changedDate=changed,
             createdDate=f"{date} {c // 3600 % 24:02d}:{c // 60 % 60:02d}:{c % 60:02d}")
    if income:
        r.update(incomeAccountName=acc, income=str(amount), incomeCurrencyShortTitle=cur)
    else:
        r.update(outcomeAccountName=acc, outcome=str(amount), outcomeCurrencyShortTitle=cur)
    return r


TRIP = "Путешествия / #Грузия'26"


def base_rows():
    _n[0] = 0
    return [
        row("2026-07-03", "Питание", 1000, payee="Магнит"),
        row("2026-07-10", "Транспорт", 500),
        row("2026-07-25", "Зарплата", 100000, income=True),
        row("2026-08-02", "Питание", 1200, payee="Магнит"),
        row("2026-08-12", f"Питание, {TRIP}", 100, acc="Лари", cur="GEL"),
        row("2026-08-14", f"Транспорт, {TRIP}", 50, acc="Лари", cur="GEL"),
        row("2026-08-25", "Зарплата", 100000, income=True),
        row("2026-09-04", "Питание", 900, payee="Магнит"),
        row("2026-09-18", "Транспорт", 700),
        row("2026-09-25", "Зарплата", 100000, income=True),
        row("2026-10-03", "Питание", 300, payee="Магнит"),          # октябрь не закончен
    ]


def to_text(rows, bom=False):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLS, delimiter=";", lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return ("﻿" if bom else "") + buf.getvalue()


def make_aux(aux, rates=True, rule_ops=True):
    aux.mkdir(parents=True, exist_ok=True)
    (aux / "accounts.json").write_text(json.dumps({"data": [
        {"name": "Карта", "instrument": "RUB", "type": "checking", "isInBalance": True},
        {"name": "Лари", "instrument": "GEL", "type": "checking", "isInBalance": True}]}), encoding="utf-8")
    (aux / "category-flags.json").write_text(json.dumps({"income_only": ["Зарплата"], "both": []}), encoding="utf-8")
    if rule_ops:
        (aux / "rule-ops.json").write_text(json.dumps({"ops": {}, "merchants": {}}), encoding="utf-8")
    (aux / "trip-ids.json").write_text(json.dumps({
        "ids": {"#Грузия'26": "trip-ge26"}, "dates": {"#Грузия'26": ["2026-08-10", "2026-08-20"]}, "skip": {}}),
        encoding="utf-8")
    if rates:       # ЦБ: 1 GEL = 35 ₽ в день поездки (сети нет — кэш из aux)
        (aux / "rates-cbr.json").write_text(json.dumps({"2026-08-12": {"GEL": 35.0}, "2026-08-14": {"GEL": 35.0}}),
                                            encoding="utf-8")


class Fs:
    """read/save как у jobs.py поверх папки (hub-api в тесте не нужен)."""

    def __init__(self, root):
        self.root, self.saved = Path(root), []

    def read(self, path):
        p = self.root / path
        if not p.is_file():
            return None, None
        b = p.read_bytes()
        return b.decode("utf-8"), hashlib.sha256(b).hexdigest()

    def save(self, path, content):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        self.saved.append(path)
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


def put_incoming(root, rows):
    text = to_text(rows)
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    i = f"2026-10-09-{sha[:8]}"
    p = Path(root) / zm_csv.CSV_DIR / "incoming" / f"{i}.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return i, p


class Parse(unittest.TestCase):
    def test_ok_bom(self):
        rows = zm_csv.parse_csv(to_text(base_rows(), bom=True))
        self.assertEqual(len(rows), 11)
        self.assertEqual(rows[0]["date"], "2026-07-03")

    def test_missing_column(self):
        text = to_text(base_rows()).replace("changedDate", "x").replace("payee", "y")
        with self.assertRaises(ValueError) as e:
            zm_csv.parse_csv(text)
        self.assertIn("changedDate", str(e.exception))
        self.assertIn("payee", str(e.exception))

    def test_bad_date(self):
        rows = base_rows()
        rows[0]["date"] = "03.07.2026"
        with self.assertRaises(ValueError):
            zm_csv.parse_csv(to_text(rows))


class Completeness(unittest.TestCase):
    def test_norm_and_open_month(self):
        r = base_rows()
        c = zm_csv.completeness(r, r, NOW)
        self.assertTrue(c["ok"], c)
        self.assertEqual((c["first"], c["last"], c["open_month"]), ("2026-07-03", "2026-10-03", "2026-10"))
        self.assertTrue(any("не закончен" in w for w in c["warnings"]))
        self.assertEqual(c["prev_rows"], 11)

    def test_date_filter_stops(self):
        r = base_rows()
        c = zm_csv.completeness([x for x in r if x["date"] >= "2026-08-01"], r, NOW)
        self.assertFalse(c["ok"])
        self.assertTrue(any("фильтр по датам" in s for s in c["stops"]))

    def test_older_export_than_recorded_stops(self):
        """Реальная пара выгрузок 01.11: более ранняя против записанной поздней давала «необъяснимое расхождение
        2024-07» — причина названа прямо: выгрузка старее записанной (по последней правке операций)."""
        old, new = base_rows(), base_rows()
        for x in new:
            x["changedDate"] = "2026-10-08 10:00:00"
        for x in old:
            x["changedDate"] = "2026-10-01 10:00:00"
        c = zm_csv.completeness(old, new, NOW)
        self.assertTrue(any("старее записанной" in s for s in c["stops"]))
        self.assertFalse(any("старее" in s for s in zm_csv.completeness(new, old, NOW)["stops"]))
        self.assertFalse(any("старее" in s for s in zm_csv.completeness(new, new, NOW)["stops"]))

    def test_gap_stops_only_if_month_was_in_prev(self):
        """Реальная история владельца (2026-11-10): июль 2015 без единой операции — пустой месяц законен и стопом
        не считается; стоп — месяц, бывший в прошлой выгрузке и пропавший целиком."""
        full = base_rows()
        r = [x for x in full if x["date"][:7] != "2026-08"]
        c = zm_csv.completeness(r, None, NOW)                     # прошлой выгрузки нет → только предупреждение
        self.assertTrue(c["ok"])
        self.assertEqual(c["months_missing"], [])
        self.assertTrue(any("2026-08" in w for w in c["warnings"]))
        c = zm_csv.completeness(r, r, NOW)                        # месяца не было и раньше → чисто
        self.assertTrue(c["ok"])
        self.assertFalse(any("2026-08" in w for w in c["warnings"]))
        c = zm_csv.completeness(r + full[:0], full + full[:1], NOW)   # в прошлой был → стоп (строк меньше ≤1 % не при чём)
        self.assertEqual(c["months_missing"], ["2026-08"])
        self.assertTrue(any("2026-08" in s for s in c["stops"]))

    def test_closed_last_month_no_warning(self):
        r = [x for x in base_rows() if x["date"] < "2026-10-01"]
        c = zm_csv.completeness(r, None, NOW)
        self.assertIsNone(c["open_month"])
        self.assertTrue(c["ok"])

    def test_small_drop_ok(self):
        r = base_rows() * 20          # 220 строк; −1 строка < 1 %
        self.assertTrue(zm_csv.completeness(r[:-1], r, NOW)["ok"])


class OpDiff(unittest.TestCase):
    def test_diff(self):
        old = base_rows()
        new = [dict(x) for x in old]
        gone = new.pop(1)                                   # удалена (июль)
        new[0]["categoryName"] = "Одежда"                   # изменена категория
        new.append(row("2026-09-30", "Питание", 10))        # добавлена
        d = zm_csv.op_diff(new, old)
        self.assertEqual((d["added"], d["deleted"], d["changed"]), (1, 1, 1))
        self.assertEqual(d["by_month"]["2026-07"], {"added": 0, "deleted": 1, "changed": 1})
        self.assertEqual(d["by_month"]["2026-09"]["added"], 1)
        self.assertEqual(d["samples"]["deleted"][0]["amount"], gone["outcome"])
        self.assertEqual(d["samples"]["changed"][0]["was"], {"categoryName": "Питание"})
        self.assertEqual(d["lost_trip_tags"], [])

    def test_lost_trip_tag(self):
        old = base_rows()
        new = [dict(x) for x in old]
        i = next(i for i, x in enumerate(new) if TRIP in x["categoryName"])
        new[i]["categoryName"] = "Питание"
        d = zm_csv.op_diff(new, old)
        self.assertEqual(len(d["lost_trip_tags"]), 1)
        self.assertEqual(d["lost_trip_tags"][0]["tag"], TRIP)
        self.assertEqual(d["lost_trip_tags"][0]["date"], "2026-08-12")

    def test_no_prev(self):
        d = zm_csv.op_diff(base_rows(), None)
        self.assertEqual((d["added"], d["deleted"], d["changed"], d["by_month"]), (0, 0, 0, {}))


class Recompute(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.aux, self.audit = self.tmp / "aux", self.tmp / "audit"
        self.audit.mkdir()
        self.csv = self.tmp / "in.csv"

    def write(self, rows, name="in.csv"):
        p = self.tmp / name
        p.write_text(to_text(rows), encoding="utf-8")
        return p

    def test_no_aux_unavailable(self):
        p = self.write(base_rows())
        r = zm_csv.recompute(p, self.aux, self.audit, None, NOW)
        self.assertFalse(r["aux"]["ok"])
        self.assertEqual(r["months"], [])
        self.assertEqual(r["trips"], [])
        self.assertIn("нет вспомогательных файлов", r["unavailable"])
        self.assertIn("accounts.json", r["aux"]["missing"])

    def test_months_trips_and_rates(self):
        make_aux(self.aux)
        p = self.write(base_rows())
        r = zm_csv.recompute(p, self.aux, self.audit, None, NOW)
        self.assertTrue(r["aux"]["ok"])
        self.assertIsNone(r["unavailable"])
        self.assertEqual(r["stops"], [])
        self.assertEqual([m["month"] for m in r["months"]], ["2026-07", "2026-08", "2026-09"])   # октябрь не закончен
        self.assertTrue(all(m["action"] == "add" and m["explained"] for m in r["months"]))
        aug = next(m for m in r["months"] if m["month"] == "2026-08")["run"]
        # 1200 ₽ + 150 GEL × 35 = 6450 ₽ (поездка: 5250 ₽ вне обычных)
        self.assertAlmostEqual(aug["totals"]["expense_rub"], 1200 + 150 * 35, places=0)
        self.assertEqual(len(r["trips"]), 1)
        t = r["trips"][0]
        self.assertEqual((t["name"], t["id"], t["action"]), ("#Грузия'26", "trip-ge26", "add"))
        self.assertAlmostEqual(t["run"]["totals"]["spent_rub"], 150 * 35, places=0)

    def test_rates_unavailable_stops(self):
        make_aux(self.aux, rates=False)
        p = self.write(base_rows())
        B = zm_csv._scripts()[4]
        orig = B.cbr_day

        def boom(d):
            raise urllib.error.URLError("нет сети")
        B.cbr_day = boom
        try:
            r = zm_csv.recompute(p, self.aux, self.audit, None, NOW)
        finally:
            B.cbr_day = orig
        self.assertEqual(r["months"], [])
        self.assertIn("нет курсов за 2026-08-12", r["unavailable"])
        self.assertTrue(any("нет курсов" in s for s in r["stops"]))

    def test_incomplete_skips_recompute(self):
        make_aux(self.aux)
        prev = self.write(base_rows(), "prev.csv")
        p = self.write([x for x in base_rows() if x["date"][:7] != "2026-08"])
        r = zm_csv.recompute(p, self.aux, self.audit, prev, NOW)
        self.assertEqual(r["months"], [])
        self.assertIn("проверку полноты", r["unavailable"])

    def _record(self, r, months):
        """Записать в audit/spending.json месяцы из результата recompute (как это делает apply)."""
        AH = zm_csv._scripts()[0]
        sp = {"schema": AH.SPENDING_SCHEMA, "months": []}
        for m in r["months"]:
            if m["month"] in months:
                sp, _ = AH.apply_spending(m["run"], sp)
        (self.audit / "spending.json").write_text(json.dumps(sp, ensure_ascii=False), encoding="utf-8")

    def test_checks_in_report_nonblocking(self):
        """Проверки «на что взглянуть» идут в отчёт по месяцам к записи, стопов не добавляют; выключенные по
        бэктесту (CHECKS_OFF) в отчёт не попадают; сбой модуля проверок отчёт не роняет."""
        make_aux(self.aux)
        rows = base_rows() + [row("2026-09-06", "", 250)]            # без категории → A3
        r = zm_csv.recompute(self.write(rows), self.aux, self.audit, None, NOW)
        self.assertEqual(r["stops"], [])
        ids = {c["id"] for c in r["checks"]}
        self.assertIn("A3", ids)
        self.assertFalse(ids & zm_csv.CHECKS_OFF)
        self.assertTrue(all(c["month"] in ("2026-07", "2026-08", "2026-09") for c in r["checks"]))
        import zm_checks
        orig = zm_checks.run_checks
        zm_checks.run_checks = lambda *a, **k: 1 / 0
        try:
            r = zm_csv.recompute(self.write(rows), self.aux, self.audit, None, NOW)
        finally:
            zm_checks.run_checks = orig
        self.assertEqual(len(r["months"]), 3)
        self.assertTrue(any("не выполнены" in w for w in r["warnings"]))

    def test_month_without_rates_stops(self):
        """Первая загрузка владельца: не было курсов валют вне ЦБ — траты поездок считались нулём, а расхождение
        месяцев выглядело «объяснимым». Месяц с операциями без курса — стоп."""
        make_aux(self.aux)
        rows = base_rows() + [row("2026-09-07", "Питание", 500, acc="Кипы", cur="LAK")]
        acc = json.loads((self.aux / "accounts.json").read_text(encoding="utf-8"))
        acc["data"].append({"name": "Кипы", "instrument": "LAK", "type": "checking", "isInBalance": True})
        (self.aux / "accounts.json").write_text(json.dumps(acc, ensure_ascii=False), encoding="utf-8")
        (self.aux / "rates-cbr.json").write_text(json.dumps({"2026-08-12": {"GEL": 35.0}, "2026-08-14": {"GEL": 35.0},
                                                             "2026-09-07": {}}), encoding="utf-8")
        r = zm_csv.recompute(self.write(rows), self.aux, self.audit, None, NOW)
        self.assertTrue(any(s.startswith("2026-09: операции без курса") and "LAK" in s for s in r["stops"]), r["stops"])
        self.assertTrue(any("rates-zm.json" in w for w in r["warnings"]))

    def test_history_starts_at_first_recorded_month(self):
        """Реальная выгрузка владельца идёт с 2011 года, история — с 2020-01: сайт предлагал «добавить» 99 месяцев.
        Месяцы раньше первого записанного не пересчитываются и не пишутся."""
        make_aux(self.aux)
        p = self.write(base_rows())
        self._record(zm_csv.recompute(p, self.aux, self.audit, None, NOW), {"2026-08", "2026-09"})
        r = zm_csv.recompute(p, self.aux, self.audit, None, NOW)
        self.assertEqual([m["month"] for m in r["months"]], ["2026-08", "2026-09"])
        self.assertTrue(all(m["action"] == "same" for m in r["months"]))
        self.assertEqual(r["skipped_before"], "2026-08")
        self.assertTrue(any("история ведётся с 2026-08" in w for w in r["warnings"]))

    def test_one_off_rule_found_by_recorded_month(self):
        """Реальный случай 2026-10: разовую «ЕНП» завёл скилл, её операции нет в rule-ops.json — месяц расходился
        необъяснимо (стоп). Операция находится по записи месяца: место и сумма разовой из spending.json."""
        make_aux(self.aux)
        rules = {"schema": "zenmoney-spending-rules@1", "updated": "2026-10-01", "regular_big": [], "one_off_merchants": [],
                 "one_off": [{"id": "mcp-1", "month": "2026-07", "note": "разовая-тест", "date": "2026-07-31"}]}
        (self.audit / "spending-rules.json").write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")
        ro = self.aux / "rule-ops.json"
        ro.write_text(json.dumps({"ops": {"mcp-1": ["2026-07-03", "Карта", 1000]}, "merchants": {}}), encoding="utf-8")
        p = self.write(base_rows())
        r0 = zm_csv.recompute(p, self.aux, self.audit, None, NOW)
        july = next(m for m in r0["months"] if m["month"] == "2026-07")["run"]
        self.assertEqual([x["note"] for x in july["one_off"]], ["разовая-тест"])       # с rule-ops правило работает
        self._record(r0, {"2026-07", "2026-08", "2026-09"})
        ro.write_text(json.dumps({"ops": {}, "merchants": {}}), encoding="utf-8")       # копия aux отстала от правил
        r = zm_csv.recompute(p, self.aux, self.audit, None, NOW)
        self.assertEqual(r["stops"], [])
        self.assertEqual({m["month"]: m["action"] for m in r["months"]}["2026-07"], "same")
        self.assertTrue(any("найдена по записи месяца" in w for w in r["warnings"]))
        self.assertFalse(any("правило не найдено" in w for w in r["warnings"]))

    def _rules(self, one_off=(), merchants=()):
        rules = {"schema": "zenmoney-spending-rules@1", "updated": "2026-11-10", "regular_big": [],
                 "one_off_merchants": list(merchants), "one_off": list(one_off)}
        (self.audit / "spending-rules.json").write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")

    def test_one_off_found_by_op_in_rule_without_rule_ops(self):
        """Тройка операции лежит в правиле (op) — rule-ops.json не нужен: ни файла, ни предупреждений."""
        make_aux(self.aux, rule_ops=False)
        self.assertTrue(zm_csv.check_aux(self.aux)[0])
        self._rules([{"id": "mcp-1", "month": "2026-07", "note": "разовая-тест", "date": "2026-07-31",
                      "op": {"date": "2026-07-03", "account": "Карта", "amount": 1000}}])
        r = zm_csv.recompute(self.write(base_rows()), self.aux, self.audit, None, NOW)
        july = next(m for m in r["months"] if m["month"] == "2026-07")["run"]
        self.assertEqual([x["note"] for x in july["one_off"]], ["разовая-тест"])
        self.assertFalse(any("правило" in w or "найдена по записи" in w for w in r["warnings"]))

    def test_op_in_rule_wins_over_rule_ops(self):
        make_aux(self.aux)
        (self.aux / "rule-ops.json").write_text(json.dumps(
            {"ops": {"mcp-1": ["2026-07-10", "Карта", 500]}, "merchants": {}}), encoding="utf-8")
        self._rules([{"id": "mcp-1", "month": "2026-07", "note": "разовая-тест", "date": "2026-07-31",
                      "op": {"date": "2026-07-03", "account": "Карта", "amount": 1000}}])
        r = zm_csv.recompute(self.write(base_rows()), self.aux, self.audit, None, NOW)
        july = next(m for m in r["months"] if m["month"] == "2026-07")["run"]
        self.assertEqual([x["rub"] for x in july["one_off"]], [1000])

    def test_rule_without_op_and_rule_ops_warns(self):
        """Ни тройки в правиле, ни записи в rule-ops, месяц не записан — поиска по записи нет: предупреждение."""
        make_aux(self.aux, rule_ops=False)
        self._rules([{"id": "mcp-1", "month": "2026-07", "note": "разовая-тест", "date": "2026-07-31"}])
        r = zm_csv.recompute(self.write(base_rows()), self.aux, self.audit, None, NOW)
        self.assertTrue(any("правило не найдено в выгрузке" in w and "нет тройки" in w for w in r["warnings"]))
        july = next(m for m in r["months"] if m["month"] == "2026-07")["run"]
        self.assertEqual(july["one_off"], [])

    def test_rules_for_csv_op_names_and_fallbacks(self):
        B = zm_csv._scripts()[4]
        ops = [{"id": "o1", "_key": ("2026-07-03", "Карта", 1000.0)}, {"id": "o2", "_key": ("2026-07-04", "Карта", 5.0)},
               {"id": "o3", "_key": ("2026-07-04", "Карта", 5.0)}]
        rp = self.tmp / "r.json"
        rp.write_text(json.dumps({"schema": "zenmoney-spending-rules@1", "one_off": [
            {"id": "a", "month": "2026-07", "note": "с op", "date": "d", "op": {"date": "2026-07-03", "account": "Карта", "amount": 1000}},
            {"id": "b", "month": "2026-07", "note": "из rule-ops", "date": "d"},
            {"id": "c", "month": "2026-07", "note": "дубль", "date": "d", "op": {"date": "2026-07-04", "account": "Карта", "amount": 5}},
            {"id": "d", "month": "2026-07", "note": "нигде", "date": "d"}],
            "one_off_merchants": [{"merchant_id": "m1", "note": "x", "date": "d", "names": ["Имя А", "Имя Б"]},
                                  {"merchant_id": "m2", "note": "y", "date": "d"},
                                  {"merchant_id": "m3", "note": "z", "date": "d"}]}), encoding="utf-8")
        ro = {"ops": {"b": ["2026-07-03", "Карта", 1000]}, "merchants": {"m2": "Имя В"}}
        out, miss = B.rules_for_csv(rp, ro, ops)
        self.assertEqual([x["id"] for x in out["one_off"]], ["o1", "o1"])
        self.assertEqual([x["merchant_id"] for x in out["one_off_merchants"]], ["p:Имя А", "p:Имя Б", "p:Имя В"])
        self.assertEqual(len(miss), 3)                                   # дубль, «нигде», место m3
        out, miss = B.rules_for_csv(rp, None, ops)                        # rule-ops.json нет совсем
        self.assertEqual([x["id"] for x in out["one_off"]], ["o1"])
        self.assertEqual(len(miss), 5)

    def test_explained_by_deleted_op_and_unexplained_stop(self):
        make_aux(self.aux)
        rows = base_rows() + [row("2026-09-05", "Питание", 1) for _ in range(300)]   # одно удаление < 1 % строк
        # 1) запись первой выгрузки через apply (read/save поверх tmp/ZenMoney/…)
        root = self.tmp / "root"
        shutil_aux = root / "ZenMoney/csv/aux"
        shutil.copytree(self.aux, shutil_aux)
        i, p = put_incoming(root, rows)
        fs = Fs(root)
        code, rep = zm_csv.route_report(root, {"id": i}, NOW, fs.read, fs.save)
        self.assertEqual(code, 200, rep)
        code, res = zm_csv.route_apply(root, {"id": i, "confirm": True}, NOW, fs.read, fs.save)
        self.assertEqual(code, 200, res)
        self.assertEqual(res["written"]["months"], ["2026-07", "2026-08", "2026-09"])
        self.assertEqual(res["written"]["trips"], ["#Грузия'26"])
        sp = json.loads((root / "ZenMoney/audit/spending.json").read_text(encoding="utf-8"))
        self.assertEqual([m["month"] for m in sp["months"]], ["2026-07", "2026-08", "2026-09"])
        self.assertTrue((root / "ZenMoney/audit/facts.json").is_file())
        self.assertEqual((root / "ZenMoney/csv/last.csv").read_text(encoding="utf-8"), p.read_text(encoding="utf-8"))
        applied = json.loads((root / f"ZenMoney/csv/reports/{i}.json").read_text(encoding="utf-8"))
        self.assertTrue(applied["applied_at"].endswith("+03:00"))
        # 2) та же выгрузка ещё раз: всё same, ничего не пишется
        report, _ = zm_csv.build_report("2026-10-09-aaaaaaaa", p, root / "ZenMoney/csv/aux", root / "ZenMoney/audit",
                                        root / "ZenMoney/csv/last.csv", NOW, NOW)
        self.assertEqual([m["action"] for m in report["months"]], ["same"] * 3)
        self.assertEqual([t["action"] for t in report["trips"]], ["same"])
        self.assertEqual(report["stops"], [])
        # 3) в августе удалена операция (1200 ₽): объяснимо diff'ом → replace, без стопов
        new = [dict(x) for x in rows if not (x["date"] == "2026-08-02")]
        p2 = self.tmp / "new.csv"
        p2.write_text(to_text(new), encoding="utf-8")
        report, runs = zm_csv.build_report("2026-10-09-bbbbbbbb", p2, root / "ZenMoney/csv/aux", root / "ZenMoney/audit",
                                           root / "ZenMoney/csv/last.csv", NOW, NOW)
        aug = next(m for m in report["months"] if m["month"] == "2026-08")
        self.assertEqual((aug["action"], aug["explained"], aug["explained_by"]), ("replace", True, "ops"))
        self.assertTrue(aug["changes"])
        self.assertGreaterEqual(aug["ops_changed_after"], 1)
        self.assertEqual(report["stops"], [])
        self.assertEqual(report["diff"]["deleted"], 1)
        self.assertEqual(sorted(runs["months"]), ["2026-08"])         # runs — только add|replace
        self.assertNotIn("run", aug)
        # 4) итог записанного месяца изменён «руками» без единой изменённой операции → необъяснимо → стоп
        sp["months"][0]["totals"]["expense_rub"] += 5000
        (root / "ZenMoney/audit/spending.json").write_text(json.dumps(sp), encoding="utf-8")
        report, _ = zm_csv.build_report("2026-10-09-cccccccc", p, root / "ZenMoney/csv/aux", root / "ZenMoney/audit",
                                        root / "ZenMoney/csv/last.csv", NOW, NOW)
        jul = next(m for m in report["months"] if m["month"] == "2026-07")
        self.assertEqual((jul["action"], jul["explained"]), ("replace", False))
        self.assertIn("необъяснимое расхождение 2026-07", report["stops"])

    def test_explained_by_changed_date_without_prev(self):
        """Без прошлой выгрузки «после записи» — по changedDate позже as_of записи."""
        make_aux(self.aux)
        rows = base_rows()
        p = self.write(rows)
        report, runs = zm_csv.build_report("2026-10-09-dddddddd", p, self.aux, self.audit, None, NOW, NOW)
        sp = {"schema": "zenmoney-spending@1", "months": []}
        AH = zm_csv._scripts()[0]
        for m in report["months"]:
            sp, _ = AH.apply_spending(runs["months"][m["month"]], sp)
        sp["months"][0]["totals"]["expense_rub"] += 100        # запись «устарела»
        sp["months"][0]["as_of"] = "2026-09-01"
        (self.audit / "spending.json").write_text(json.dumps(sp), encoding="utf-8")
        r = zm_csv.recompute(p, self.aux, self.audit, None, NOW)
        self.assertTrue(any(m["action"] == "replace" and not m["explained"] for m in r["months"]))   # правок не было
        for x in rows:
            if x["date"] == "2026-07-10":
                x["changedDate"] = "2026-09-20 10:00:00"      # правка в ZenMoney позже as_of записи
        p = self.write(rows)
        r = zm_csv.recompute(p, self.aux, self.audit, None, NOW)
        jul = next(m for m in r["months"] if m["month"] == "2026-07")
        self.assertEqual((jul["action"], jul["explained"], jul["ops_changed_after"]), ("replace", True, 1))

    def test_cache_saved(self):
        make_aux(self.aux, rates=False)
        p = self.write(base_rows())
        B = zm_csv._scripts()[4]
        orig = B.cbr_day
        B.cbr_day = lambda d: {"GEL": 36.0}
        B.time.sleep = lambda s: None
        saved = []
        try:
            r = zm_csv.recompute(p, self.aux, self.audit, None, NOW, cache_save=saved.append)
        finally:
            B.cbr_day = orig
        self.assertEqual(r["stops"], [])
        self.assertEqual(len(saved), 1)
        self.assertIn("2026-08-12", json.loads(saved[0]))


class Routes(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        make_aux(self.root / "ZenMoney/csv/aux")
        self.fs = Fs(self.root)
        self.i, self.p = put_incoming(self.root, base_rows())
        self.log = []

    def lg(self, *a, **k):
        self.log.append((a[0], a[1], k.get("op")))

    def report(self):
        return zm_csv.route_report(self.root, {"id": self.i}, NOW, self.fs.read, self.fs.save, self.lg)

    def apply(self, **body):
        return zm_csv.route_apply(self.root, {"id": self.i, **body}, NOW, self.fs.read, self.fs.save, self.lg)

    def test_report_saved_and_shape(self):
        code, rep = self.report()
        self.assertEqual(code, 200)
        self.assertEqual(rep["schema"], "zm-csv-report@1")
        self.assertEqual(rep["sha256"], hashlib.sha256(self.p.read_bytes()).hexdigest())
        self.assertEqual((rep["rows"], rep["first"], rep["last"]), (11, "2026-07-03", "2026-10-03"))
        self.assertEqual(rep["diff"]["prev"], None)
        self.assertEqual(rep["stops"], [])
        self.assertTrue(rep["aux"]["ok"])
        self.assertFalse(any("run" in m for m in rep["months"]))
        saved = json.loads((self.root / f"ZenMoney/csv/reports/{self.i}.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["id"], self.i)
        runs = json.loads((self.root / f"ZenMoney/csv/reports/{self.i}-runs.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(runs["months"]), ["2026-07", "2026-08", "2026-09"])
        self.assertIn(("zm-csv", "ok", "report"), self.log)

    def test_report_without_aux(self):
        shutil.rmtree(self.root / "ZenMoney/csv/aux")
        code, rep = self.report()
        self.assertEqual(code, 200)
        self.assertEqual(rep["months"], [])
        self.assertIn("нет вспомогательных файлов", rep["unavailable"])
        self.assertEqual(rep["completeness"]["ok"], True)
        code, body = self.apply(confirm=True)           # писать нечего → отказ
        self.assertEqual(code, 409)
        self.assertIn("нечего записывать", body["error"])

    def test_report_errors(self):
        self.assertEqual(zm_csv.route_report(self.root, {"id": "../x"}, NOW, self.fs.read, self.fs.save)[0], 400)
        self.assertEqual(zm_csv.route_report(self.root, {"id": "2026-10-09-00000000"}, NOW, self.fs.read, self.fs.save)[0], 404)

    def test_apply_refusals(self):
        self.assertEqual(self.apply(confirm=True)[0], 409)        # нет отчёта
        self.report()
        c, b = self.apply()
        self.assertEqual(c, 409)
        self.assertIn("confirm", b["error"])
        c, b = self.apply(confirm="yes")
        self.assertEqual(c, 409)
        self.assertEqual(self.fs.saved.count("ZenMoney/audit/spending.json"), 0)

    def test_apply_other_sha(self):
        self.report()
        self.p.write_text(self.p.read_text(encoding="utf-8") + "\n", encoding="utf-8")   # файл ≠ отчёту
        c, b = self.apply(confirm=True)
        self.assertEqual(c, 409)
        self.assertIn("sha256", b["error"])
        self.assertFalse((self.root / "ZenMoney/audit/spending.json").exists())

    def test_apply_refused_on_stops(self):
        rows = base_rows()
        last = self.root / zm_csv.CSV_DIR / "last.csv"               # месяц был в прошлой выгрузке и пропал → стоп
        last.parent.mkdir(parents=True, exist_ok=True)
        last.write_text(to_text(rows), encoding="utf-8")
        rows = [x for x in rows if x["date"][:7] != "2026-08"]
        self.i, self.p = put_incoming(self.root, rows)
        code, rep = self.report()
        self.assertEqual(code, 200)
        self.assertTrue(rep["stops"])
        c, b = self.apply(confirm=True)
        self.assertEqual(c, 409)
        self.assertIn("стопы", b["error"])
        self.assertFalse((self.root / "ZenMoney/audit/spending.json").exists())

    def test_apply_once(self):
        self.report()
        c, b = self.apply(confirm=True)
        self.assertEqual(c, 200, b)
        self.assertEqual(b["versions"], [])                        # прежних файлов не было
        self.assertEqual(b["written"]["trips"], ["#Грузия'26"])
        c, b = self.apply(confirm=True)                           # повторно — уже записано
        self.assertEqual(c, 409)
        self.assertIn("уже записана", b["error"])
        self.assertEqual(zm_csv.route_report(self.root, {"id": self.i}, NOW, self.fs.read, self.fs.save)[0], 409)
        tr = json.loads((self.root / "ZenMoney/audit/trips.json").read_text(encoding="utf-8"))
        self.assertEqual(tr["trips"][0]["trip"], {"id": "trip-ge26", "name": "#Грузия'26"})
        self.assertEqual(tr["updated"], "2026-10-09")

    def test_apply_nothing_to_write_sets_base(self):
        """Первая загрузка владельца: всё «без изменений», кнопка была неактивна — и last.csv не появлялся, следующая
        выгрузка сравнивалась бы с пустотой. Чистый отчёт без изменений принимается: история цела, last.csv записан."""
        self.report()
        self.apply(confirm=True)                                  # история записана первой выгрузкой
        (self.root / zm_csv.CSV_DIR / "last.csv").unlink()        # как у владельца: история есть, базы сравнения нет
        rows = base_rows() + [row("2026-10-05", "Питание", 111, payee="Магнит")]     # новая операция в незаконченном месяце
        self.i, self.p = put_incoming(self.root, rows)
        code, rep = self.report()
        self.assertEqual((code, rep["stops"]), (200, []))
        self.assertTrue(all(m["action"] == "same" for m in rep["months"]) and all(t["action"] == "same" for t in rep["trips"]))
        before = (self.root / "ZenMoney/audit/spending.json").read_bytes()
        c, b = self.apply(confirm=True)
        self.assertEqual(c, 200, b)
        self.assertEqual(b["written"], {"months": [], "trips": []})
        self.assertEqual((self.root / "ZenMoney/audit/spending.json").read_bytes(), before)
        self.assertEqual((self.root / zm_csv.CSV_DIR / "last.csv").read_text(encoding="utf-8"), self.p.read_text(encoding="utf-8"))

    def test_lost_trip_tag_stops(self):
        self.report()
        self.apply(confirm=True)                                  # last.csv := первая выгрузка
        rows = base_rows()
        for x in rows:
            if TRIP in x["categoryName"]:
                x["categoryName"] = "Питание"
        self.i, self.p = put_incoming(self.root, rows)
        code, rep = self.report()
        self.assertEqual(code, 200)
        self.assertEqual(len(rep["diff"]["lost_trip_tags"]), 2)
        self.assertTrue(any("тег поездки" in s for s in rep["stops"]))
        self.assertEqual(self.apply(confirm=True)[0], 409)


def _req(port, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


class SiteEdit(unittest.TestCase):
    """Правки с сайта: «Разовая», «Добавить поездку», аудит сайта при записи (3.6/3.7, 2026-11-10)."""
    NEW_TRIP = "Путешествия / #Тбилиси'26"

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        make_aux(self.root / "ZenMoney/csv/aux")
        self.fs = Fs(self.root)
        rows = base_rows()
        rows += [row("2026-07-15", "Покупки", 50000, payee="Магазин-Х", comment="тест"),
                 row("2026-09-05", f"Питание, {self.NEW_TRIP}", 700),
                 row("2026-09-07", f"Транспорт, {self.NEW_TRIP}", 300)]
        self.i, self.p = put_incoming(self.root, rows)

    def report(self):
        return zm_csv.route_report(self.root, {"id": self.i}, NOW, self.fs.read, self.fs.save)

    def rule(self, **body):
        return zm_csv.route_rule(self.root, {"id": self.i, **body}, NOW, self.fs.read, self.fs.save)

    def trip(self, **body):
        return zm_csv.route_trip(self.root, {"id": self.i, **body}, NOW, self.fs.read, self.fs.save)

    def july(self, rep):
        return next(m for m in rep["months"] if m["month"] == "2026-07")

    def cand(self):
        code, rep = self.report()
        self.assertEqual(code, 200, rep)
        c = self.july(rep)["candidates"]
        self.assertEqual(len(c), 1)
        return rep, c[0]

    def rules_file(self):
        return json.loads((self.root / "ZenMoney/audit/spending-rules.json").read_text(encoding="utf-8"))

    def test_candidates_in_report(self):
        rep, c = self.cand()
        self.assertEqual((c["date"], c["account"], c["amount"], c["rub"]), ("2026-07-15", "Карта", 50000, 50000))
        self.assertEqual((c["payee"], c["comment"]), ("Магазин-Х", "тест"))
        self.assertEqual(self.july(rep)["site_rules"], [])
        self.assertNotIn("run", self.july(rep))

    def test_rule_add_recalc_remove(self):
        _rep, c = self.cand()
        body = dict(month="2026-07", date=c["date"], account=c["account"], amount=c["amount"], note="разовая-с-сайта")
        code, out = self.rule(**body)
        self.assertEqual(code, 200, out)
        rid = out["rule"]["id"]
        self.assertRegex(rid, r"^site-[0-9a-f]{12}$")
        self.assertEqual(rid, zm_csv.site_rule_id(c["date"], c["account"], c["amount"]))
        self.assertEqual(self.rules_file()["one_off"], [
            {"id": rid, "month": "2026-07", "note": "разовая-с-сайта", "date": "2026-10-09",
             "op": {"date": "2026-07-15", "account": "Карта", "amount": 50000}}])
        self.assertEqual(self.july(out)["candidates"], [])                       # трата ушла из кандидатов
        self.assertEqual([x["id"] for x in self.july(out)["site_rules"]], [rid])
        runs = json.loads((self.root / f"ZenMoney/csv/reports/{self.i}-runs.json").read_text(encoding="utf-8"))
        t = runs["months"]["2026-07"]["totals"]
        self.assertEqual((t["expense_one_off_rub"], t["expense_regular_rub"]), (50000, 1500))   # разовая вышла из регулярных
        self.assertEqual(runs["months"]["2026-07"]["one_off"][0]["note"], "разовая-с-сайта")
        code, out = self.rule(remove=True, rule_id=rid)                           # снять ту же отметку
        self.assertEqual(code, 200, out)
        self.assertEqual(self.rules_file()["one_off"], [])
        self.assertEqual(len(self.july(out)["candidates"]), 1)
        self.assertEqual(self.rule(remove=True, rule_id=rid)[0], 409)             # повторное снятие — нечего

    def test_rule_remove_by_triple(self):
        _rep, c = self.cand()
        self.rule(month="2026-07", date=c["date"], account=c["account"], amount=c["amount"], note="н")
        code, out = self.rule(remove=True, date=c["date"], account=c["account"], amount=c["amount"])
        self.assertEqual(code, 200, out)
        self.assertEqual(out["rule"]["action"], "removed")

    def test_rule_refusals(self):
        _rep, c = self.cand()
        ok = dict(month="2026-07", date=c["date"], account=c["account"], amount=c["amount"], note="н")
        self.assertEqual(self.rule(**{**ok, "note": "  "})[0], 400)                     # «что это» обязательно
        self.assertEqual(self.rule(**{k: v for k, v in ok.items() if k != "note"})[0], 400)
        self.assertEqual(self.rule(**{**ok, "month": "2026-08"})[0], 400)               # дата не того месяца
        self.assertEqual(self.rule(**{**ok, "amount": "50000"})[0], 400)
        self.assertEqual(self.rule(**{**ok, "amount": 51})[0], 403)                      # траты нет среди кандидатов
        self.assertEqual(self.rule(**{**ok, "account": "Чужой"})[0], 403)
        # чужие правила (скилла: mcp-…, uuid) с сайта не снимаются
        self.assertEqual(self.rule(remove=True, rule_id="mcp-1")[0], 403)
        self.assertEqual(self.rule(remove=True, rule_id="0123abcd-0000-0000-0000-000000000000")[0], 403)
        self.assertEqual(self.rule(remove=True)[0], 403)
        self.assertEqual(zm_csv.route_rule(self.root, {"id": "../x"}, NOW, self.fs.read, self.fs.save)[0], 400)
        self.assertFalse((self.root / "ZenMoney/audit/spending-rules.json").exists())
        # правило скилла в файле остаётся при добавлении и снятии отметки сайта
        (self.root / "ZenMoney/audit").mkdir(parents=True, exist_ok=True)
        (self.root / "ZenMoney/audit/spending-rules.json").write_text(json.dumps({
            "schema": "zenmoney-spending-rules@1", "updated": "2026-10-01", "regular_big": [], "one_off_merchants": [],
            "one_off": [{"id": "mcp-1", "month": "2026-07", "note": "скилл", "date": "2026-10-01"}]}), encoding="utf-8")
        code, out = self.rule(**ok)
        self.assertEqual(code, 200, out)
        self.assertEqual(self.rule(remove=True, rule_id=out["rule"]["id"])[0], 200)
        self.assertEqual([x["id"] for x in self.rules_file()["one_off"]], ["mcp-1"])

    def test_rule_refused_without_report_and_after_apply(self):
        self.assertEqual(self.rule(month="2026-07", date="2026-07-15", account="Карта", amount=1, note="н")[0], 409)
        _rep, c = self.cand()
        self.assertEqual(zm_csv.route_apply(self.root, {"id": self.i, "confirm": True}, NOW, self.fs.read, self.fs.save)[0], 200)
        code, out = self.rule(month="2026-07", date=c["date"], account=c["account"], amount=c["amount"], note="н")
        self.assertEqual(code, 409)
        self.assertIn("уже записана", out["error"])

    def test_new_trip_candidate_and_add(self):
        code, rep = self.report()
        self.assertEqual(code, 200, rep)
        self.assertEqual([t["name"] for t in rep["trips"]], ["#Грузия'26"])
        nt = rep["new_trips"]
        self.assertEqual(len(nt), 1)
        self.assertEqual((nt[0]["name"], nt[0]["ops"], nt[0]["first"], nt[0]["last"]),
                         ("#Тбилиси'26", 2, "2026-09-05", "2026-09-07"))
        self.assertEqual((nt[0]["start"], nt[0]["end"]), ("2026-09-05", "2026-09-07"))
        self.assertTrue(any("нет ID" in w for w in rep["warnings"]))
        code, out = self.trip(name="#Тбилиси'26", start="2026-09-04", end="2026-09-08")
        self.assertEqual(code, 200, out)
        self.assertEqual(out["trip"]["id"], "site:#Тбилиси'26")
        self.assertEqual(out["new_trips"], [])
        self.assertEqual({t["name"]: t["id"] for t in out["trips"]}["#Тбилиси'26"], "site:#Тбилиси'26")
        ti = json.loads((self.root / "ZenMoney/csv/aux/trip-ids.json").read_text(encoding="utf-8"))
        self.assertEqual(ti["ids"]["#Тбилиси'26"], "site:#Тбилиси'26")
        self.assertEqual(ti["dates"]["#Тбилиси'26"], ["2026-09-04", "2026-09-08"])
        self.assertEqual(ti["ids"]["#Грузия'26"], "trip-ge26")                       # прежнее не тронуто
        runs = json.loads((self.root / f"ZenMoney/csv/reports/{self.i}-runs.json").read_text(encoding="utf-8"))
        r = runs["trips"]["#Тбилиси'26"]
        self.assertEqual((r["trip"]["id"], r["period"]["start"], r["period"]["end"]),
                         ("site:#Тбилиси'26", "2026-09-04", "2026-09-08"))
        self.assertEqual(r["totals"]["spent_rub"], 1000)
        self.assertEqual(zm_csv.route_apply(self.root, {"id": self.i, "confirm": True}, NOW, self.fs.read, self.fs.save)[0], 200)
        tr = json.loads((self.root / "ZenMoney/audit/trips.json").read_text(encoding="utf-8"))
        self.assertIn("site:#Тбилиси'26", [t["trip"]["id"] for t in tr["trips"]])

    def test_trip_refusals(self):
        self.report()
        ok = dict(name="#Тбилиси'26", start="2026-09-05", end="2026-09-07")
        self.assertEqual(self.trip(**{**ok, "name": "Тбилиси"})[0], 400)
        self.assertEqual(self.trip(**{**ok, "start": "2026-9-5"})[0], 400)
        self.assertEqual(self.trip(**{**ok, "start": "2026-13-05"})[0], 400)
        self.assertEqual(self.trip(**{**ok, "start": "2026-09-09"})[0], 400)
        self.assertEqual(self.trip(**{**ok, "name": "#Чужая"})[0], 403)                # нет среди новых
        self.assertEqual(self.trip(**{**ok, "name": "#Грузия'26"})[0], 403)            # у неё уже есть ID
        ti = json.loads((self.root / "ZenMoney/csv/aux/trip-ids.json").read_text(encoding="utf-8"))
        self.assertNotIn("#Тбилиси'26", ti["ids"])

    def test_site_audit_written_on_apply(self):
        code, rep = self.report()
        self.assertEqual(rep["checks_months"], ["2026-07", "2026-08", "2026-09"])
        code, res = zm_csv.route_apply(self.root, {"id": self.i, "confirm": True}, NOW, self.fs.read, self.fs.save)
        self.assertEqual(code, 200, res)
        self.assertEqual(res["site_audit"], {"written": True, "months": 3})
        raw = (self.root / "ZenMoney/audit/site-audit.json").read_text(encoding="utf-8")
        sa = json.loads(raw)
        self.assertEqual(sa["schema"], "zenmoney-site-audit@1")
        self.assertEqual(sorted(sa["months"]), ["2026-07", "2026-08", "2026-09"])
        e = sa["months"]["2026-07"]
        self.assertEqual((e["as_of"], e["export_id"], e["stops_overridden"]), ("2026-10-09", self.i, []))
        self.assertEqual(zm_csv.validate_site_audit(sa), [])
        for m in sa["months"].values():
            for c in m["checks"]:
                self.assertEqual(set(c), {"id", "cls", "count", "text"})                 # без sample, названий и сумм
        self.assertNotIn("Магазин-Х", raw)
        self.assertNotIn("sample", raw)

    def test_site_audit_merges_and_skips_unchecked(self):
        rep = {"id": self.i, "as_of": "2026-10-09", "checks_months": ["2026-09"],
               "checks": [{"id": "P1", "cls": "hint", "month": "2026-09", "text": "т", "count": 2, "sample": [{"x": 1}]}]}
        cur = {"schema": "zenmoney-site-audit@1", "updated": "2026-09-01", "months": {
            "2026-08": {"as_of": "2026-09-01", "export_id": self.i, "checks": [], "stops_overridden": []}}}
        new = zm_csv.site_audit_update(cur, rep, ["2026-08", "2026-09", "2026-07"])
        self.assertEqual(sorted(new["months"]), ["2026-08", "2026-09"])               # июль без проверок — не пишется
        self.assertEqual(new["months"]["2026-09"]["checks"], [{"id": "P1", "cls": "hint", "count": 2, "text": "т"}])
        self.assertEqual(zm_csv.validate_site_audit(new), [])

    def test_site_audit_validator_rejects(self):
        good = {"schema": "zenmoney-site-audit@1", "updated": "2026-10-09", "months": {
            "2026-09": {"as_of": "2026-10-09", "export_id": "2026-10-09-1a2b3c4d",
                        "checks": [{"id": "P1", "cls": "hint", "count": 1, "text": "т"}], "stops_overridden": []}}}
        self.assertEqual(zm_csv.validate_site_audit(good), [])
        for mut in (lambda g: g["months"]["2026-09"]["checks"][0].update(sample=[{"payee": "X"}]),
                    lambda g: g["months"]["2026-09"]["checks"][0].update(count="1"),
                    lambda g: g["months"].update({"2026-9": g["months"].pop("2026-09")})):
            bad = json.loads(json.dumps(good))
            mut(bad)
            self.assertTrue(zm_csv.validate_site_audit(bad))
        self.assertTrue(zm_csv.validate_site_audit({"schema": "x"}))


class HubApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.old_root = server.ROOT
        server.ROOT = cls.tmp
        cls.httpd = serve(server.Handler, quiet=False)[0]
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        server.ROOT = cls.old_root
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def upload(self, text=None, name="zenmoney.csv"):
        raw = (text if text is not None else to_text(base_rows(), bom=True)).encode("utf-8")
        return raw, _req(self.port, "POST", "/api/zm/csv", {"name": name, "b64": base64.b64encode(raw).decode()})

    def test_upload_and_state(self):
        raw, (c, b) = self.upload()
        self.assertEqual(c, 200, b)
        sha = hashlib.sha256(raw).hexdigest()
        today = datetime.now(MSK).strftime("%Y-%m-%d")
        self.assertEqual(b["id"], f"{today}-{sha[:8]}")
        self.assertEqual((b["rows"], b["first"], b["last"], b["sha256"]), (11, "2026-07-03", "2026-10-03", sha))
        self.assertEqual(Path(self.tmp, f"ZenMoney/csv/incoming/{b['id']}.csv").read_bytes(), raw)   # байты как есть (BOM)
        c, st = _req(self.port, "GET", "/api/zm/csv-state")
        self.assertEqual(c, 200)
        self.assertIn(b["id"], st["incoming"])
        self.assertFalse(st["aux_ok"])
        self.assertEqual(self.upload()[1][0], 200)                 # тот же файл — тот же id, не ошибка

    def test_upload_rejects(self):
        c, b = self.upload(text=to_text(base_rows()).replace("income;", "inc;", 1))[1]
        self.assertEqual(c, 400)
        self.assertIn("income", b["detail"])
        self.assertEqual(_req(self.port, "POST", "/api/zm/csv", {"name": "x", "b64": "!!!"})[0], 400)
        self.assertEqual(_req(self.port, "POST", "/api/zm/csv", {"name": "x"})[0], 400)
        raw = "\xff\xfe".encode("latin-1")
        self.assertEqual(_req(self.port, "POST", "/api/zm/csv",
                              {"name": "x", "b64": base64.b64encode(raw).decode()})[0], 400)

    def test_columns_match_notify(self):
        self.assertEqual(tuple(server.ZM_REQUIRED), tuple(zm_csv.REQUIRED_COLUMNS))
        self.assertEqual(tuple(server.ZM_AUX), tuple(zm_csv.AUX_REQUIRED))

    def test_applied_dropped_on_next_upload_and_state_last(self):
        _, (c, b) = self.upload(text=to_text(base_rows()[:3]))
        i = b["id"]
        inc = Path(self.tmp, f"ZenMoney/csv/incoming/{i}.csv")
        sha = hashlib.sha256(inc.read_bytes()).hexdigest()
        rep = Path(self.tmp, f"ZenMoney/csv/reports/{i}.json")
        rep.parent.mkdir(parents=True, exist_ok=True)
        rep.write_text(json.dumps({"id": i, "sha256": sha, "applied_at": "2026-10-09T12:00:00+03:00", "rows": 11, "last": "2026-10-03"}), encoding="utf-8")
        Path(self.tmp, "ZenMoney/csv/last.csv").write_bytes(inc.read_bytes())
        c, st = _req(self.port, "GET", "/api/zm/csv-state")
        self.assertNotIn(i, st["incoming"])                        # записанная выгрузка не «ждёт»
        self.assertEqual(st["last"], {"name": i, "sha256": sha, "written_at": "2026-10-09T12:00:00+03:00",
                                      "rows": 11, "last_op": "2026-10-03"})          # число операций и последняя — для подписи на странице
        self.upload()                                              # очистка записанных при загрузке
        self.assertFalse(inc.exists())

    def test_proxy_to_notify(self):
        calls = []
        orig = urllib.request.urlopen

        class Resp:
            status = 200

            def __init__(self, body):
                self._b = body

            def read(self):
                return self._b

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else req
            if url.startswith(server.NOTIFY_URL):
                calls.append((url[len(server.NOTIFY_URL):], json.loads(req.data)))
                if url.endswith("zm-csv-apply"):
                    raise urllib.error.HTTPError(url, 409, "x", {}, io.BytesIO(json.dumps({"error": "в отчёте есть стопы"}, ensure_ascii=False).encode("utf-8")))
                return Resp(b'{"schema": "zm-csv-report@1"}')
            return orig(req, timeout=timeout)
        urllib.request.urlopen = fake
        try:
            i = "2026-10-09-1a2b3c4d"
            c, b = _req(self.port, "POST", "/api/zm/csv-report", {"id": i, "лишнее": 1})
            self.assertEqual((c, b["schema"]), (200, "zm-csv-report@1"))
            c, b = _req(self.port, "POST", "/api/zm/csv-apply", {"id": i, "confirm": True})
            self.assertEqual((c, b["error"]), (409, "в отчёте есть стопы"))     # код notify доходит до страницы
            self.assertEqual(_req(self.port, "POST", "/api/zm/csv-apply", {"id": "../../x"})[0], 400)
        finally:
            urllib.request.urlopen = orig
        self.assertEqual(calls, [("/internal/zm-csv-report", {"id": i}),
                                 ("/internal/zm-csv-apply", {"id": i, "confirm": True})])

    def test_proxy_rule_trip_fields(self):
        calls = []
        orig = urllib.request.urlopen

        class Resp:
            status = 200

            def read(self):
                return b'{"schema": "zm-csv-report@1"}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else req
            if url.startswith(server.NOTIFY_URL):
                calls.append((url[len(server.NOTIFY_URL):], json.loads(req.data)))
                return Resp()
            return orig(req, timeout=timeout)
        urllib.request.urlopen = fake
        try:
            i = "2026-10-09-1a2b3c4d"
            rule = {"id": i, "month": "2026-07", "date": "2026-07-15", "account": "Карта", "amount": 50000,
                    "payee": "М", "note": "н"}
            self.assertEqual(_req(self.port, "POST", "/api/zm/rule", {**rule, "лишнее": 1, "confirm": True})[0], 200)
            self.assertEqual(_req(self.port, "POST", "/api/zm/rule",
                                  {"id": i, "remove": True, "rule_id": "site-0123456789ab"})[0], 200)
            self.assertEqual(_req(self.port, "POST", "/api/zm/trip",
                                  {"id": i, "name": "#Т", "start": "2026-09-05", "end": "2026-09-07"})[0], 200)
            self.assertEqual(_req(self.port, "POST", "/api/zm/rule", {**rule, "amount": "50000"})[0], 400)   # тип поля
            self.assertEqual(_req(self.port, "POST", "/api/zm/rule", {**rule, "amount": True})[0], 400)
            self.assertEqual(_req(self.port, "POST", "/api/zm/trip", {"id": i, "name": 5})[0], 400)
            self.assertEqual(_req(self.port, "POST", "/api/zm/rule", {**rule, "id": "../x"})[0], 400)
        finally:
            urllib.request.urlopen = orig
        self.assertEqual([c[0] for c in calls], ["/internal/zm-rule", "/internal/zm-rule", "/internal/zm-trip"])
        self.assertEqual(calls[0][1], rule)                                       # лишнее и confirm отброшены
        self.assertEqual(calls[1][1], {"id": i, "remove": True, "rule_id": "site-0123456789ab"})

    def test_proxy_notify_down(self):
        c, b = _req(self.port, "POST", "/api/zm/csv-report", {"id": "2026-10-09-1a2b3c4d"})
        self.assertIn(c, (502,))
        self.assertIn("hub-notify", b["error"])

    def test_job_whitelist(self):
        i = "2026-10-09-1a2b3c4d"
        for p in (f"ZenMoney/csv/incoming/{i}.csv", f"ZenMoney/csv/reports/{i}.json", f"ZenMoney/csv/reports/{i}-runs.json",
                  "ZenMoney/csv/last.csv", "ZenMoney/csv/aux/rates-cbr.json", "ZenMoney/audit/spending.json",
                  "ZenMoney/audit/trips.json", "ZenMoney/audit/facts.json", "ZenMoney/audit/spending-rules.json",
                  "ZenMoney/audit/site-audit.json"):
            self.assertTrue(server.is_allowed(p, server.JOB_WHITELIST), p)
        for p in ("ZenMoney/audit/history.json", "ZenMoney/audit/accepted.json", "ZenMoney/audit/site-audit.json.bak", "ZenMoney/zenmoney-map.md",
                  "ZenMoney/csv/incoming/x.csv", "ZenMoney/csv/aux/../audit/history.json", "ZenMoney/csv/aux/a.csv"):
            self.assertFalse(server.is_allowed(p, server.JOB_WHITELIST), p)
        c, _ = _req(self.port, "GET", "/api/job/file?path=ZenMoney/csv/aux/accounts.json")
        self.assertEqual(c, 404)                                   # разрешён (404 = файла нет, не 403)
        c, _ = _req(self.port, "GET", "/api/job/file?path=ZenMoney/audit/history.json")
        self.assertEqual(c, 403)

    def test_health_flag(self):
        c, b = _req(self.port, "GET", "/api/health")
        self.assertEqual(c, 200)
        self.assertTrue(b["zm_csv"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
