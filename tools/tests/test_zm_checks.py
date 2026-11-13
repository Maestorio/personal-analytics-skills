#!/usr/bin/env python3
"""Проверки выгрузки ZenMoney до записи месяца (3.7 «меньше ИИ»): tools/hosting/notify/zm_checks.py.

Синтетика: 12 месяцев 2025 — история, проверяемый месяц 2026-01. На каждую проверку — «срабатывает» и
«не срабатывает»; контракт run_checks (поля, класс из DEFAULTS, ≤ 5 примеров, переопределение cfg).
Запуск: python3 tools/tests/test_zm_checks.py
"""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools/hosting/notify"))
import zm_checks as ZC  # noqa: E402

AM = ZC.AM
M = "2026-01"
HIST = [f"2025-{m:02d}" for m in range(1, 13)]


def cats():
    c = lambda name, **kw: {"name": name, "parentId": None, "isIncome": False, "isExpense": True, "isArchived": False, **kw}
    return {"food": c("Еда"), "fun": c("Досуг"), "sal": c("Зарплата", isIncome=True, isExpense=False),
            "par": c("Родитель"), "kid": c("Ребёнок", parentId="par"), "trip": c("#Поездка"), "trip2": c("#Поездка2"),
            "xfer": c("Переводы")}


def refs():
    acc = lambda n, ins="RUB", **kw: {"name": n, "instrument": ins, "type": "checking", "isInBalance": True, **kw}
    return {"user": {"currency": "RUB"}, "categories": cats(),
            "accounts": {"a1": acc("Карта"), "a2": acc("Вторая"), "off": acc("Кошелёк", isInBalance=False),
                         "usd": acc("Карта", "USD")}, "merchants": {}}


class Gen:
    def __init__(self):
        self.ops, self.n = [], 0

    def add(self, date, amount, cat=None, payee=None, acc="a1", kind="expense", comment=None, tags=None):
        self.n += 1
        o = {"id": f"o{self.n}", "date": date, kind: {"accountId": acc, "amount": float(amount)}}
        if cat:
            o["categoryId"] = cat
        if payee:
            o["merchantId"] = "p:" + payee
        if comment:
            o["comment"] = comment
        if tags:
            o["tagIds"] = tags
        self.ops.append(o)
        return o

    def history(self, food=None, filler=20, accs=("a1", "a2")):
        food = food or [10000 + 300 * (i % 4) for i in range(12)]
        for i, m in enumerate(HIST):
            self.add(m + "-10", food[i], "food", "Магазин")
            self.add(m + "-11", 150000 + 100 * i, "sal", None, kind="income")
            for j in range(filler):
                self.add(m + f"-{12 + j % 15:02d}", 100 + j + i, "fun", f"Место{j}", acc=accs[j % len(accs)])

    def run(self, history=None, cfg=None, meta=None, months=(M,), ids=None):
        r = refs()
        ctx = AM.Ctx(self.ops, r, None, {}, {}, set())
        hits = ZC.collect(self.ops, r, ctx, history or {}, list(months), cfg, meta)
        return [h for h in hits if ids is None or h["id"] in ids]


def ids(hits):
    return sorted({h["id"] for h in hits})


class SkillChecks(unittest.TestCase):
    def base(self):
        g = Gen()
        g.history()
        return g

    def test_a3(self):
        g = self.base()
        self.assertNotIn("A3", ids(g.run()))
        g.add("2026-01-05", 700, None, "Лавка")
        self.assertIn("A3", ids(g.run()))

    def test_a4(self):
        g = self.base()
        g.add("2026-01-06", 700, "fun", "Лавка")
        self.assertNotIn("A4", ids(g.run()))
        g.add("2026-01-06", 800, "trip", "Лавка")
        self.assertIn("A4", ids(g.run()))

    def test_a5(self):
        g = self.base()
        g.add("2026-01-07", 555, "fun", "Лавка")
        self.assertNotIn("A5", ids(g.run()))
        g.add("2026-01-07", 555, "fun", "Лавка")
        self.assertIn("A5", ids(g.run()))

    def test_a1(self):
        g = self.base()
        g.add("2026-01-08", 12345, "fun", None, acc="a1")
        self.assertNotIn("A1", ids(g.run()))
        g.add("2026-01-08", 12345, "sal", None, acc="a2", kind="income")
        self.assertIn("A1", ids(g.run()))

    def test_b7(self):
        g = self.base()
        self.assertNotIn("B7", ids(g.run()))
        g.add("2026-01-09", 300, "fun", "Лавка", acc="off")
        self.assertIn("B7", ids(g.run()))

    def test_d13(self):
        g = self.base()
        g.add("2026-01-09", 300, "kid", "Лавка")
        self.assertNotIn("D13", ids(g.run()))
        g.add("2026-01-09", 310, "par", "Лавка")
        self.assertIn("D13", ids(g.run()))


class Divergence(unittest.TestCase):
    def test_n2(self):
        g = Gen()
        g.history()
        g.add("2026-01-10", 10200, "food", "Магазин")
        self.assertNotIn("N2", ids(g.run()))
        g.add("2026-01-11", 40000, "food", "Магазин")
        h = g.run(ids={"N2"})
        self.assertEqual(len(h), 1)
        self.assertEqual(h[0]["detail"]["category"], "Еда")

    def test_n2_needs_six_months(self):
        g = Gen()
        for m in HIST[:5]:
            g.add(m + "-10", 10000, "food", "Магазин")
        g.add("2026-01-10", 90000, "food", "Магазин")
        self.assertNotIn("N2", ids(g.run()))

    def test_n2_k(self):
        g = Gen()
        g.history()
        g.add("2026-01-10", 14000, "food", "Магазин")
        n2 = lambda k: [h for h in g.run(cfg={"n2_k": k}, ids={"N2"}) if h["subject"] == "Еда"]
        self.assertTrue(n2(2.0))
        self.assertFalse(n2(5.0))

    def test_n2i(self):
        g = Gen()
        g.history()
        g.add("2026-01-11", 150000, "sal", None, kind="income")
        self.assertNotIn("N2i", ids(g.run()))
        g.add("2026-01-12", 900000, "sal", None, kind="income")
        self.assertIn("N2i", ids(g.run()))

    def test_n9(self):
        g = Gen()
        g.history()
        for j in range(22):
            g.add(f"2026-01-{1 + j % 28:02d}", 100, "fun", f"Место{j}")
        self.assertNotIn("N9", ids(g.run()))
        g2 = Gen()
        g2.history()
        for j in range(4):
            g2.add(f"2026-01-{1 + j:02d}", 100, "fun", f"Место{j}")
        self.assertIn("N9", ids(g2.run()))

    def test_b6(self):
        g = Gen()
        g.history()
        g.add("2026-01-12", 100, "fun", "Лавка", acc="a1")
        h = g.run(ids={"B6'"})
        self.assertEqual([x["subject"] for x in h], ["Вторая"])
        g.add("2026-01-13", 100, "fun", "Лавка", acc="a2")
        self.assertNotIn("B6'", ids(g.run()))

    def test_b6_rare_account(self):
        g = Gen()
        g.history(accs=("a1",))
        for m in HIST[:4]:
            g.add(m + "-20", 100, "fun", "Лавка", acc="a2")
        g.add("2026-01-12", 100, "fun", "Лавка", acc="a1")
        self.assertNotIn("B6'", ids(g.run()))


class Places(unittest.TestCase):
    def shop(self, n=10, cat="food", amount=200):
        g = Gen()
        g.history()
        for i in range(n):
            g.add(f"2025-{1 + i % 12:02d}-20", amount, cat, "Булочная")
        return g

    def test_p1(self):
        g = self.shop()
        g.add("2026-01-15", 200, "food", "Булочная")
        self.assertNotIn("P1", ids(g.run()))
        g.add("2026-01-16", 200, "fun", "Булочная")
        self.assertIn("P1", ids(g.run()))

    def test_p1_few_ops(self):
        g = self.shop(n=3)
        g.add("2026-01-16", 200, "fun", "Булочная")
        self.assertNotIn("P1", ids(g.run()))

    def test_p2(self):
        g = self.shop()
        g.add("2026-01-15", 600, "food", "Булочная")
        self.assertNotIn("P2", ids(g.run()))
        g.add("2026-01-16", 5000, "food", "Булочная")
        self.assertIn("P2", ids(g.run()))

    def test_p2_min_rub(self):
        g = self.shop(amount=50)
        g.add("2026-01-16", 400, "food", "Булочная")
        self.assertNotIn("P2", ids(g.run()))

    def test_p3(self):
        g = Gen()
        g.history()
        g.add("2026-01-15", 100, "fun", "Булочная")
        self.assertNotIn("P3", ids(g.run()))
        g.add("2026-01-16", 100, "fun", "PYATEROCHKA 231")
        self.assertIn("P3", ids(g.run()))
        self.assertNotIn("P3", ids(g.run(history={"known_places": {"PYATEROCHKA 231"}})))

    def test_p3_known_by_history(self):
        g = Gen()
        g.history()
        for i in range(4):
            g.add(f"2025-0{1 + i}-20", 100, "fun", "KOFEJNYA AKTER")
        g.add("2026-01-16", 100, "fun", "KOFEJNYA AKTER")
        self.assertNotIn("P3", ids(g.run()))

    def test_p4(self):
        g = Gen()
        g.history()
        for i in range(4):
            g.add(f"2025-0{1 + i}-20", 100, "fun", "Старбакс")
        g.add("2026-01-15", 100, "fun", "старбакс ")
        self.assertIn("P4", ids(g.run()))
        g2 = Gen()
        g2.history()
        for i in range(4):
            g2.add(f"2025-0{1 + i}-20", 100, "fun", "Старбакс")
        g2.add("2026-01-15", 100, "fun", "Старбакк")
        self.assertIn("P4", ids(g2.run()))
        g2.add("2026-01-16", 100, "fun", "Совсем другое")
        self.assertEqual(len(g2.run(ids={"P4"})), 1)

    def test_p4_same_place_not_new(self):
        g = Gen()
        g.history()
        for i in range(4):
            g.add(f"2025-0{1 + i}-20", 100, "fun", "Старбакс")
        g.add("2026-01-15", 100, "fun", "Старбакс")
        self.assertNotIn("P4", ids(g.run()))


class Other(unittest.TestCase):
    def test_n1(self):
        g = Gen()
        g.history()
        g.add("2026-01-10", 777, "fun", "Лавка")
        g.add("2026-01-11", 777, "fun", "Кафе")
        self.assertIn("N1", ids(g.run()))
        g2 = Gen()
        g2.history()
        g2.add("2026-01-05", 777, "fun", "Лавка")
        g2.add("2026-01-11", 777, "fun", "Кафе")
        self.assertNotIn("N1", ids(g2.run()))

    def test_n1_not_duplicated_with_a5(self):
        g = Gen()
        g.history()
        g.add("2026-01-10", 777, "fun", "Лавка")
        g.add("2026-01-10", 777, "fun", "Лавка")
        got = ids(g.run())
        self.assertIn("A5", got)
        self.assertNotIn("N1", got)

    def test_n3(self):
        g = Gen()
        g.history()
        g.add("2026-01-10", 777, "fun", "Лавка")
        self.assertNotIn("N3", ids(g.run()))
        g.add("2026-01-10", 3000, "xfer", "Иван")
        self.assertIn("N3", ids(g.run()))

    def trip_base(self):
        g = Gen()
        g.history()
        for d in range(1, 8):
            g.add(f"2025-03-{d:02d}", 500, "food", "Кафе", tags=["trip"])
        g.add("2025-03-09", 500, "food", "Кафе")           # мимо: тег потерян в истории, доля 7/8 ≥ 70 %
        hist = {"trip_dates": {"#Поездка": ["2025-03-01", "2025-03-09"], "#Поездка2": ["2026-01-05", "2026-01-10"]}}
        return g, hist

    def test_n5(self):
        g, hist = self.trip_base()
        g.add("2026-01-06", 500, "food", "Кафе", tags=["trip2"])
        self.assertNotIn("N5", ids(g.run(history=hist)))
        g.add("2026-01-07", 500, "food", "Кафе")
        self.assertIn("N5", ids(g.run(history=hist)))

    def test_n5_outside_dates_and_other_category(self):
        g, hist = self.trip_base()
        g.add("2026-01-20", 500, "food", "Кафе")
        g.add("2026-01-07", 500, "fun", "Кафе")
        self.assertNotIn("N5", ids(g.run(history=hist)))

    def test_n6(self):
        g = Gen()
        g.history()
        cfg = {"today": "2026-02-15"}
        self.assertNotIn("N6", ids(g.run(cfg=cfg, months=[M, "2026-03"])))
        g.add("2026-03-01", 100, "fun", "Лавка")
        self.assertIn("N6", ids(g.run(cfg=cfg, months=[M, "2026-03"])))

    def test_n6_old_created_recently(self):
        g = Gen()
        g.history()
        o = g.add("2020-01-05", 100, "fun", "Лавка")
        cfg = {"today": "2026-02-15"}
        self.assertNotIn("N6", ids(g.run(cfg=cfg, months=["2020-01"], meta={o["id"]: ("2020-01-05 10:00:00", "")})))
        self.assertIn("N6", ids(g.run(cfg=cfg, months=["2020-01"], meta={o["id"]: ("2026-02-10 10:00:00", "")})))

    def test_n7(self):
        g = Gen()
        g.history()
        g.add("2026-01-10", 100, "fun", "Лавка", acc="a1")
        self.assertNotIn("N7", ids(g.run()))
        g.add("2026-01-10", 100, "fun", "Лавка", acc="usd")
        self.assertIn("N7", ids(g.run(history={"account_currencies": {"Карта": {"RUB"}}})))
        self.assertNotIn("N7", ids(g.run(history={"account_currencies": {"Карта": {"RUB", "USD"}}})))

    def test_n10(self):
        g = Gen()
        g.history()
        g.add("2026-01-10", 10000, "food", "Магазин", comment="ок")
        g.add("2026-01-10", 45000, "food", "Магазин", comment="подарок")
        self.assertNotIn("N10", ids(g.run()))
        g.add("2026-01-12", 45000, "food", "Магазин")
        self.assertIn("N10", ids(g.run()))


class Contract(unittest.TestCase):
    def test_run_checks_shape(self):
        g = Gen()
        g.history()
        for i in range(8):
            g.add(f"2026-01-{10 + i}", 700 + i, None, "Лавка")
        r = refs()
        ctx = AM.Ctx(g.ops, r, None, {}, {}, set())
        out = ZC.run_checks(g.ops, r, ctx, {}, [M])
        a3 = [x for x in out if x["id"] == "A3"][0]
        self.assertEqual(set(a3), {"id", "cls", "month", "text", "count", "sample"})
        self.assertEqual((a3["count"], len(a3["sample"]), a3["month"]), (8, 5, M))
        self.assertEqual(a3["cls"], ZC.DEFAULTS["cls"]["A3"])
        out2 = ZC.run_checks(g.ops, r, ctx, {}, [M], {"cls": {"A3": "stop"}})
        self.assertEqual([x["cls"] for x in out2 if x["id"] == "A3"], ["stop"])

    def test_defaults_cover_all_checks(self):
        self.assertEqual(set(ZC.DEFAULTS["cls"]), set(ZC.TEXTS))
        self.assertTrue(set(ZC.DEFAULTS["cls"].values()) <= {"stop", "warn", "hint"})

    def test_clean_month_is_quiet(self):
        g = Gen()
        g.history()
        g.add("2026-01-10", 10100, "food", "Магазин")
        g.add("2026-01-11", 150500, "sal", None, kind="income")
        for j in range(20):
            g.add(f"2026-01-{12 + j % 15:02d}", 100 + j, "fun", f"Место{j}", acc=("a1", "a2")[j % 2])
        r = refs()
        ctx = AM.Ctx(g.ops, r, None, {}, {}, set())
        self.assertEqual(ZC.run_checks(g.ops, r, ctx, {}, [M]), [])


if __name__ == "__main__":
    unittest.main()
