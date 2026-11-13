#!/usr/bin/env python3
"""Отпечаток выгрузки сделок и правки задним числом (trades_digest.py, checks.check_backdated).

Зачем: кэш-дрейф 13→16.10 (+169 тыс ₽) разбирали вручную по двум выгрузкам. Итоги
per_instrument_xirr двух снапшотов для этого не годятся — их смысл менялся между версиями
загрузчика (13→16.10 «расходятся» 65 итогов на сотни тысяч). Отпечаток — сырые строки,
сгруппированные (тикер, операция) → [строк, сумма, количество], поэтому от версии расчёта
не зависит. Живая калибровка -46 → -48 (чистка владельца 21.10): удалены фантом Борца
(продажа + корректировка), дубли ПГК и TPAY → warning; дивиденды BTBR 14.10 и GMKN 16.10,
внесённые позже, → info; денежные строки −170 859 / +174 939 при итоге +4 080 → warning
(порог по ячейке, не по итогу).
Сделка в день прошлого снапшота (OZON 03.11: снапшот собран в 13:42, продажа и её денежные строки
датированы тем же 03.11 и пришли позже) — не правка задним числом: одна info
trades_on_prev_snapshot_day вместо двух warning. Времени сделки в выгрузке нет, поэтому признак —
снапшот собран в свой день и по ячейке прошлая выгрузка равна строкам строго до этого дня; иначе
(снапшот собран позже своего дня, строки этого дня уже были в ячейке, строка дня удалена) — warning.
Запуск: python3 skills/portfolio-data-loader/tests/test_trades_digest.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import checks as ch  # noqa: E402
import trades_digest as td  # noqa: E402

BASE = [
    ("2026-09-01", "Деньги (RUB)", "Внесение", None, 200000.0),
    ("2026-09-02", "RU000A105GN3", "Покупка", 2, 168000.0),
    ("2026-09-18", "RU000A105GN3", "Продажа", 2, -168951.0),
    ("2026-10-08", "TPAY", "Дивиденд", 5000, 5544.17),
    ("2026-10-10", "SBER", "Покупка", 10, 3000.0),
]


def info(rows):
    t = ch.TradesInfo(n_rows=len(rows))
    t.rows = list(rows)
    t.first_date, t.last_date = min(r[0] for r in rows), max(r[0] for r in rows)
    return t


def run(old_rows, new_rows, upto="2026-10-13", built=None):
    prev = {"as_of_date": upto, "trades_digest": td.from_rows(old_rows, upto)}
    if built:
        prev["generated_at"] = built
    return ch.check_backdated(ch.Ctx(snap={}, prev=prev, trades=info(new_rows), as_of="2026-10-16"))


def ids(res, level=None):
    return sorted(r["id"] for r in res if level is None or r["level"] == level)


class Digest(unittest.TestCase):
    def test_groups_and_cutoff(self):
        d = td.from_rows(BASE, "2026-10-08")
        self.assertEqual(d["rows"], 4)
        self.assertEqual(d["by_ticker"]["RU000A105GN3"]["Покупка"], [1, 168000.0, 2.0])
        self.assertNotIn("SBER", d["by_ticker"])          # 10.10 позже upto

    def test_diff_empty_on_same_rows(self):
        self.assertEqual(td.diff(td.from_rows(BASE, "2026-10-13"), td.from_rows(BASE, "2026-10-13")), [])


class Backdated(unittest.TestCase):
    def test_unchanged_is_info(self):
        self.assertEqual(ids(run(BASE, BASE + [("2026-10-15", "SBER", "Дивиденд", 10, 33.0)])),
                         ["trades_unchanged_before_prev"])

    def test_removed_phantom_and_dup_warns(self):                # чистка 21.10
        old = BASE + [("2026-09-18", "RU000A105GN3", "Продажа", 1.992045846, -168346.4),
                      ("2026-10-08", "TPAY", "Дивиденд", 5000, 5544.17)]
        self.assertIn("trades_changed_before_prev", ids(run(old, BASE), "warning"))

    def test_backdated_sale_warns(self):                         # ЭталонФин5, продажа от 28.09
        new = BASE + [("2026-09-28", "RU000A10EST2", "Продажа", 26, -23141.14)]
        self.assertIn("trades_changed_before_prev", ids(run(BASE, new), "warning"))

    def test_late_payout_is_info(self):                          # BTBR 14.10 внесён позже
        new = BASE + [("2026-10-12", "BTBR", "Дивиденд", 600, 2406.0)]
        res = run(BASE, new)
        self.assertEqual(ids(res, "warning"), [])
        self.assertIn("payouts_recorded_late", ids(res, "info"))

    def test_money_threshold_per_cell_not_net(self):
        old = BASE + [("2026-09-18", "Деньги (RUB)", "Внесение", None, 170859.37),
                      ("2026-10-01", "Деньги (RUB)", "Корректировка", None, -183510.39)]
        new = BASE + [("2026-10-01", "Деньги (RUB)", "Корректировка", None, -8571.02)]
        res = run(old, new)
        m = next(r for r in res if r["id"] == "money_rows_changed_before_prev")
        self.assertEqual(m["level"], "warning")
        self.assertAlmostEqual(m["details"]["total"], 4080.0, places=2)

    def test_no_prev_digest_is_silent(self):                     # первый снапшот с отпечатком
        res = ch.check_backdated(ch.Ctx(snap={}, prev={"as_of_date": "2026-10-13"}, trades=info(BASE),
                                        as_of="2026-10-16"))
        self.assertEqual(res, [])


DAY = "2026-10-13"
BUILT = DAY + "T13:42:54+03:00"
SALE = [(DAY, "SBER", "Продажа", 4, -1200.0), (DAY, "Деньги (RUB)", "Внесение", None, 1200.0),
        (DAY, "Деньги (RUB)", "Расход", None, -3.5)]


class SameDay(unittest.TestCase):
    def test_sale_on_snapshot_day_after_build_is_one_info(self):     # OZON 03.11
        res = run(BASE, BASE + SALE, built=BUILT)
        self.assertEqual(ids(res), ["trades_on_prev_snapshot_day"])
        r = res[0]
        self.assertEqual(r["level"], "info")
        self.assertIn("собран в 13:42", r["message_ru"])
        self.assertEqual(len(r["details"]["cells"]), 3)
        self.assertAlmostEqual(r["details"]["money_total"], 1196.5, places=2)

    def test_snapshot_built_on_later_day_keeps_warning(self):
        res = run(BASE, BASE + SALE, built="2026-10-14T09:00:00+03:00")
        self.assertIn("trades_changed_before_prev", ids(res, "warning"))
        self.assertNotIn("trades_on_prev_snapshot_day", ids(res))

    def test_no_build_time_keeps_warning(self):
        self.assertIn("trades_changed_before_prev", ids(run(BASE, BASE + SALE), "warning"))

    def test_cell_with_day_rows_in_prev_export_keeps_warning(self):  # строки дня уже были — не разделить
        old = BASE + [(DAY, "SBER", "Продажа", 1, -300.0)]
        res = run(old, old + SALE[:1], built=BUILT)
        self.assertIn("trades_changed_before_prev", ids(res, "warning"))
        self.assertNotIn("trades_on_prev_snapshot_day", ids(res))

    def test_day_row_removed_warns(self):
        old = BASE + [(DAY, "SBER", "Продажа", 1, -300.0)]
        self.assertIn("trades_changed_before_prev", ids(run(old, BASE, built=BUILT), "warning"))

    def test_same_day_and_backdated_split(self):
        new = BASE + SALE + [("2026-09-28", "RU000A10EST2", "Продажа", 26, -23141.14)]
        res = run(BASE, new, built=BUILT)
        self.assertIn("trades_on_prev_snapshot_day", ids(res, "info"))
        w = next(r for r in res if r["id"] == "trades_changed_before_prev")
        self.assertEqual([c["ticker"] for c in w["details"]["cells"]], ["RU000A10EST2"])
        self.assertNotIn("money_rows_changed_before_prev", ids(res))

    def test_backdated_row_in_same_cell_keeps_warning(self):         # продажа дня + продажа задним числом
        new = BASE + SALE + [("2026-10-01", "SBER", "Продажа", 1, -300.0)]
        res = run(BASE, new, built=BUILT)
        w = next(r for r in res if r["id"] == "trades_changed_before_prev")
        self.assertEqual([c["ticker"] for c in w["details"]["cells"]], ["SBER"])
        self.assertEqual([c["ticker"] for c in next(r for r in res if r["id"] == "trades_on_prev_snapshot_day")
                          ["details"]["cells"]], ["Деньги (RUB)", "Деньги (RUB)"])


# ── подача сообщений сборки 11.11 (интеграция IntelInvest дала дубли) ──

D10 = "2026-11-10"
NV_BASE = [("2026-01-10", "NVTK", "Покупка", 82, 90000.0), ("2026-11-09", "NVTK", "Дивиденд", 82, 2533.0)]
CASH_OLD = {"current_drift_rub": 369418.19, "baseline_drift_rub": 375731.44}


def run_full(old_rows, new_rows, upto=D10, snap=None, prev_extra=None, as_of="2026-11-11", holdings=None):
    prev = {"as_of_date": upto, "trades_digest": td.from_rows(old_rows, upto), "cash_reconciliation": CASH_OLD}
    prev.update(prev_extra or {})
    snap = snap or {"holdings": holdings if holdings is not None else [{"ticker": "NVTK", "name": "Новатэк", "qty": 82}],
                    "cash_reconciliation": {"current_drift_rub": 369418.19, "threshold_rub": 10000.0},
                    "cash": {"source": "owner_intelinvest"}}
    t = info(new_rows)
    return ch.run_all(snap, prev, trades_info=t, as_of=as_of)


def one(res, id_):
    return next(r for r in res if r["id"] == id_)


class Messages(unittest.TestCase):
    DUP = NV_BASE + [("2026-11-09", "NVTK", "Дивиденд", 82, 2911.0)]

    def test_duplicate_dividend_table_and_new_mark(self):       # NVTK 2533 + 2911 при 82 шт., 2911 — новая
        res = run_full(NV_BASE, self.DUP)
        r = one(res, "payout_exceeds_holding")
        self.assertEqual(r["level"], "warning")
        self.assertIn("NVTK (Новатэк) · 09.11 · дивиденд · на руках 82 шт, выплачено на 164 шт: "
                      "2 533 ₽ × 82 шт; 2 911 ₽ × 82 шт (новая с прошлой сборки)", r["message_ru"])
        it = r["details"]["items"][0]
        self.assertEqual(it["name"], "Новатэк")
        self.assertEqual([x["amount"] for x in it["rows"]], [2533.0, 2911.0])
        self.assertEqual([x["new"] for x in it["rows"]], [False, True])

    def test_new_mark_for_row_dated_after_prev_snapshot(self):
        rows = NV_BASE[:1] + [("2026-11-11", "NVTK", "Дивиденд", 82, 2533.0), ("2026-11-11", "NVTK", "Дивиденд", 82, 2911.0)]
        r = one(run_full(NV_BASE[:1], rows), "payout_exceeds_holding")
        self.assertEqual([x["new"] for x in r["details"]["items"][0]["rows"]], [True, True])

    def test_new_mark_skipped_when_rows_indistinguishable(self):   # две одинаковые строки, одна новая — какая, не знаем
        rows = NV_BASE + [("2026-11-09", "NVTK", "Дивиденд", 82, 2533.0)]
        r = one(run_full(NV_BASE, rows), "payout_exceeds_holding")
        self.assertEqual([x["new"] for x in r["details"]["items"][0]["rows"]], [None, None])
        self.assertNotIn("новая с прошлой сборки", r["message_ru"])

    def test_old_year_date_has_year(self):
        old = [("2025-05-10", "NVTK", "Покупка", 82, 90000.0)]
        rows = old + [("2025-12-20", "NVTK", "Дивиденд", 82, 100.0), ("2025-12-20", "NVTK", "Дивиденд", 82, 100.0)]
        r = one(run_full(old, rows, upto="2026-01-05", as_of="2026-01-10"), "payout_exceeds_holding")
        self.assertIn("20.12.2025", r["message_ru"])

    MONEY_OLD = [("2026-11-01", "Деньги (RUB)", "Внесение", None, 5000.0),
                 ("2026-11-02", "Деньги (RUB)", "Расход", None, -1850.0),
                 ("2026-11-02", "Деньги (RUB)", "Списание", None, -1850.0),
                 ("2026-11-03", "Деньги (RUB)", "Корректировка", None, 100.0)]

    def money_new(self):   # внесение −378, корректировка −1 472, расход и списание удалены, добавлен доход 1 850
        return [("2026-11-01", "Деньги (RUB)", "Внесение", None, 4622.0),
                ("2026-11-03", "Деньги (RUB)", "Корректировка", None, 100.0 - 1472.0),
                ("2026-11-05", "Деньги (RUB)", "Доход", None, 1850.0)]

    def test_money_rows_added_removed_changed_and_cash_answer(self):
        res = run_full(self.MONEY_OLD, self.money_new())
        r = one(res, "money_rows_changed_before_prev")
        m = r["message_ru"]
        self.assertTrue(m.startswith("В истории денежных операций (до прошлой сборки, 10.11) появились или исчезли строки:"))
        self.assertIn("добавлено: доход — 1 стр. на 1 850 ₽", m)
        self.assertIn("удалено: расход — 1 стр. на 1 850 ₽; списание — 1 стр. на 1 850 ₽", m)
        self.assertIn("изменено: внесение — −378 ₽; корректировка — −1 472 ₽", m)
        self.assertNotIn("в валюте строк", m)
        self.assertNotIn("+0,00", m)
        last = m.splitlines()[-1]
        self.assertEqual(last, "Кэш после правок сходится с вашим фактом так же, как раньше: расхождение "
                               "+369 418,19 ₽ (было +369 418,19 ₽) — ничего не сломалось.")
        self.assertEqual(r["details"]["cash"]["delta_rub"], 0.0)

    def test_money_cash_answer_changed_over_threshold(self):
        snap = {"holdings": [], "cash_reconciliation": {"current_drift_rub": 359000.0, "threshold_rub": 10000.0},
                "cash": {"source": "owner_intelinvest"}}
        m = one(run_full(self.MONEY_OLD, self.money_new(), snap=snap), "money_rows_changed_before_prev")["message_ru"]
        self.assertIn("расхождение с вашим фактом изменилось на −10 418,19 ₽", m.splitlines()[-1])
        self.assertIn("проверьте", m.splitlines()[-1])

    def test_money_cash_answer_estimate_is_not_claimed_as_fact(self):
        snap = {"holdings": [], "cash_reconciliation": {"current_drift_rub": 369418.19, "threshold_rub": 10000.0},
                "cash": {"source": "trades_plus_prev_drift"}}
        m = one(run_full(self.MONEY_OLD, self.money_new(), snap=snap), "money_rows_changed_before_prev")["message_ru"]
        self.assertIn("Кэш — оценка", m.splitlines()[-1])
        self.assertNotIn("ничего не сломалось", m)

    def test_money_without_cash_reconciliation_has_no_cash_line(self):
        m = one(run_full(self.MONEY_OLD, self.money_new(), snap={"holdings": []}), "money_rows_changed_before_prev")
        self.assertNotIn("Кэш", m["message_ru"])

    def test_dup_cleanup_is_info_when_prev_build_flagged_it(self):    # удалили лишнюю 2911 — «чистка дублей»
        prev_extra = {"build_suspects": [["NVTK", "Дивиденд"]]}
        res = run_full(self.DUP, NV_BASE, prev_extra=prev_extra)
        r = one(res, "trades_changed_before_prev")
        self.assertEqual(r["level"], "info")
        self.assertTrue(r["message_ru"].startswith("Удалено/изменено задним числом (с прошлой сборки"))
        self.assertIn("NVTK (Новатэк) · дивиденд: удалено 1 стр. на 2 911 ₽", r["message_ru"])
        self.assertIn("Если это чистка дублей — всё правильно.", r["message_ru"])

    def test_dup_removal_without_prev_suspect_stays_warning(self):
        self.assertEqual(one(run_full(self.DUP, NV_BASE), "trades_changed_before_prev")["level"], "warning")

    def test_cleanup_with_other_change_stays_warning(self):          # чистка + продажа задним числом
        new = NV_BASE + [("2026-11-01", "SBER", "Продажа", 4, -1200.0)]
        r = one(run_full(self.DUP, new, prev_extra={"build_suspects": [["NVTK", "Дивиденд"]]}), "trades_changed_before_prev")
        self.assertEqual(r["level"], "warning")

    def test_changed_sum_same_rows_is_described_in_words(self):      # NVTK: строки те же, −378
        new = NV_BASE[:1] + [("2026-11-09", "NVTK", "Дивиденд", 82, 2155.0)]
        r = one(run_full(NV_BASE, new), "trades_changed_before_prev")
        self.assertEqual(r["level"], "warning")
        self.assertIn("сумма строк изменилась на −378 ₽ (число строк то же)", r["message_ru"])

    def test_late_payout_text(self):
        new = NV_BASE + [("2026-11-09", "NVTK", "Дивиденд", 40, 500.0)]
        r = one(run_full(NV_BASE, new), "payouts_recorded_late")
        self.assertIn("внесены после прошлой сборки: NVTK (Новатэк) · дивиденд: добавлено 1 стр. на 500 ₽", r["message_ru"])

    def test_suspects_for_snapshot(self):
        res = run_full(NV_BASE, self.DUP)
        self.assertEqual(ch.suspects_for_snapshot(res), [["NVTK", "Дивиденд"]])


if __name__ == "__main__":
    unittest.main(verbosity=1)
