#!/usr/bin/env python3
"""Тесты подготовки цикла «машиночитаемость»: валидаторы, объединение условий, миграция 1.2 -> 2.

Запуск: ~/.pyenv/versions/3.12.9/bin/python3 tools/data-structures/tests/test_ds_prep.py
Фикстуры синтетические (тикеры AAAA/BBBB, ISIN вида RU000A000AA0), реальных данных портфеля нет.
"""

import copy
import io
import json
import os
import random
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "migrations"))
sys.path.insert(0, os.path.normpath(os.path.join(ROOT, "..", "..", "_shared-references")))   # модуль (а) и валидаторы

import ds_schemas as ds  # noqa: E402
import conditions_merge as cm  # noqa: E402
import migrate_conditions_v2 as mg  # noqa: E402

TODAY = "2026-10-30"


def good_decision():
    return {
        "schema_version": "decision@1", "id": "2026-10-29T1740-AAAA", "key": "AAAA",
        "verdict": "HOLD", "target_pct": 2.0, "review_by": "2026-12-01",
        "note": "держим, фундамент нейтральный", "confidence": 0.6,
        "conditions_created": ["c-1"], "conditions_resolved": [],
        "source": {"kind": "report", "doc": "Portfolio/reports/2026-10-29-aaaa.md", "mode_codes": ["4a"],
                   "stress_id": None},
        "author": "model", "recorded_at": "2026-10-29T17:40:12+03:00",
    }


def good_cond(**over):
    c = {
        "id": "c-2026-10-29-aaaa-1", "version": 1, "key": "AAAA",
        "kind": "review", "trigger": {"type": "date", "value": "2026-12-01"}, "event_text": "отчёт",
        "while_pending": {"verdict": "HOLD", "text": "ждём"},
        "on_trigger": {"action": "run_analysis", "verdict": "HOLD", "text": "разобрать"},
        "not_before": None, "valid_until": "2026-12-31",
        "context": {"plan_pct": 2.0, "snapshot_id": "portfolio-2026-10-29.json", "as_of": "2026-10-29T17:40:12+03:00"},
        "source": {"kind": "report", "doc": "x.md"}, "created_at": "2026-10-29T17:40:12+03:00",
        "created_by": "mode_4", "withdrawn": None, "superseded_by": None,
    }
    c.update(over)
    return c


def good_file(*conds):
    return {"schema_version": "conditions@2", "conditions": list(conds) or [good_cond()]}


def good_state(*events):
    return {"schema_version": "conditions-state@1", "events": list(events)}


def ev(cid="c-1", event="fired", at="2026-10-29T12:00:00+03:00", by="notifier", version=1, **data):
    return {"condition_id": cid, "version": version, "event": event, "at": at, "by": by, "data": data}


class ErrCase(unittest.TestCase):
    def assertHasErr(self, errs, fragment):
        self.assertTrue(any(fragment in e for e in errs), f"нет ошибки с {fragment!r} в {errs}")

    def assertNoErr(self, errs):
        self.assertEqual(errs, [], errs)


class TestDecisionValidator(ErrCase):
    def test_valid(self):
        self.assertNoErr(ds.validate_decision(good_decision()))

    def test_rules(self):
        def mut(fn):
            d = good_decision()
            fn(d)
            return ds.validate_decision(d)
        cases = [
            ("schema_version", lambda d: d.update(schema_version="decision@2")),
            ("verdict", lambda d: d.update(verdict="BUY_MORE")),
            ("target_pct", lambda d: d.update(target_pct=120)),
            ("target_pct", lambda d: d.update(target_pct="2")),
            ("review_by", lambda d: d.update(review_by="01.12.2026")),
            ("conditions_created", lambda d: d.update(conditions_created="c-1")),                # не список
            ("conditions_created[0]", lambda d: d.update(conditions_created=[""])),
            ("conditions_resolved", lambda d: d.update(conditions_resolved=None)),
            ("review_by: вне окна 7–180", lambda d: d.update(review_by="2026-11-01")),            # +3 дня
            ("review_by: вне окна 7–180", lambda d: d.update(review_by="2027-05-17")),            # +200 дней
            ("source.stress_id", lambda d: d["source"].update(stress_id=5)),
            ("неизвестное", lambda d: d.update(triggers=["c-1"])),                                # убрано из схемы
            ("неизвестное", lambda d: d.update(gate=None)),
            ("неизвестное", lambda d: d.update(key_kind="ticker")),
            ("неизвестное", lambda d: d.update(supersedes=None)),
            ("обязательное", lambda d: d.pop("conditions_created")),
            ("обязательное", lambda d: d.pop("review_by")),
            ("note", lambda d: d.update(note="я" * 201)),
            ("note", lambda d: d.update(note="")),
            ("confidence", lambda d: d.update(confidence=1.5)),
            ("source.kind", lambda d: d["source"].update(kind="chat")),
            ("source.doc", lambda d: d["source"].update(doc=None)),
            ("source.mode_codes[0]", lambda d: d["source"].update(mode_codes=["режим4"])),
            ("source.mode_codes[0]", lambda d: d["source"].update(mode_codes=["4"])),           # нет в списке (есть 4a/4b)
            ("author", lambda d: d.update(author="bot")),
            ("recorded_at", lambda d: d.update(recorded_at="2026-10-29T17:40:12")),            # нет пояса
            ("recorded_at", lambda d: d.update(recorded_at="2026-10-29T17:40:12+00:00")),      # не МСК
            ("recorded_at", lambda d: d.update(recorded_at="2026-13-29T17:40:12+03:00")),      # нет такой даты
            ("id", lambda d: d.update(id="AAAA-2026-10-29")),
            ("id", lambda d: d.update(id="2026-10-29T1741-AAAA")),                              # минута не совпала
            ("id", lambda d: d.update(id="2026-10-28T1740-AAAA")),                              # дата не совпала
            ("id", lambda d: d.update(id="2026-10-29T1740-BBBB")),                              # ключ не совпал
            ("неизвестное", lambda d: d.update(extra=1)),
            ("обязательное", lambda d: d.pop("verdict")),
        ]
        for frag, fn in cases:
            with self.subTest(frag=frag):
                self.assertHasErr(mut(fn), frag)

    def test_isin_key(self):
        d = good_decision()
        d.update(key="RU000A000AA0", id="2026-10-29T1740-RU000A000AA0")
        self.assertNoErr(ds.validate_decision(d))
        self.assertEqual(ds.key_kind("RU000A000AA0"), "isin")
        self.assertEqual(ds.key_kind("AAAA"), "ticker")

    def test_optional_confidence_and_null_review_by(self):
        d = good_decision()
        del d["confidence"]
        d["review_by"] = None
        self.assertNoErr(ds.validate_decision(d))

    def test_review_by_window_edges(self):
        for rb in ("2026-11-05", "2027-04-27"):          # ровно 7 и 180 дней от 2026-10-29
            d = good_decision()
            d["review_by"] = rb
            self.assertNoErr(ds.validate_decision(d))

    def test_defaults_and_codelists(self):
        self.assertEqual(ds.DEFAULTS, {"review_days": 60, "add_cooldown_days": 21,
                                       "ipo_pause_quarters": 8, "report_window_days": 3, "plan_tolerance_pp": 1,
                                       "noai_gate_blocks": True, "no_reversal_days": 14,
                                       "known_dates_horizon_days": 7})
        self.assertNotIn("ticker_class", ds.CODELISTS)

    def test_error_format(self):
        for e in ds.validate_decision({"schema_version": "x"}):
            self.assertIn(": ", e)


class TestConditionValidator(ErrCase):
    def test_valid(self):
        self.assertNoErr(ds.validate_condition_def(good_cond()))

    def test_rules(self):
        def mut(fn):
            c = good_cond()
            fn(c)
            return ds.validate_condition_def(c)
        cases = [
            ("version", lambda c: c.update(version=0)),
            ("id", lambda c: c.update(id="c 1")),
            ("kind", lambda c: c.update(kind="sell")),
            ("неизвестное", lambda c: c.update(asset_class="stock")),
            ("неизвестное", lambda c: c.update(key_kind="ticker")),
            ("неизвестное", lambda c: c.update(branches=[{"if_text": "x", "then": {"action": "notify_only", "text": "t"}}])),
            ("неизвестное", lambda c: c.update(otherwise={"action": "notify_only", "text": "t"})),   # вне on_trigger
            ("trigger.type", lambda c: c["trigger"].update(type="manual")),
            ("trigger.value", lambda c: c["trigger"].update(value="завтра")),
            ("trigger.value", lambda c: c.update(trigger={"type": "price_below", "value": "90"})),
            ("trigger.window_end", lambda c: c.update(trigger={"type": "report_published", "value": "МСФО"})),
            ("trigger.window_end", lambda c: c["trigger"].update(window_end="2026-12-01")),     # не у report_published
            ("trigger.window_end", lambda c: c.update(trigger={"type": "report_published", "value": "МСФО", "window_end": "2027-01-01"})),
            ("event_text", lambda c: c.update(event_text="я" * 201)),
            ("while_pending.verdict", lambda c: c["while_pending"].update(verdict="KEEP")),
            ("on_trigger.action", lambda c: c["on_trigger"].update(action="Разбор после отчёта")),
            ("on_trigger.target_pct", lambda c: c.update(on_trigger={"action": "set_target_pct", "verdict": "BUY", "text": "t"})),
            ("on_trigger.verdict", lambda c: c.update(on_trigger={"action": "set_verdict", "verdict": None, "text": "t"})),
            ("on_trigger.text", lambda c: c["on_trigger"].pop("text")),
            ("on_trigger.branches[0].if_text", lambda c: c["on_trigger"].update(branches=[{"then": {"action": "notify_only", "text": "t"}}])),
            ("on_trigger.branches[0].then.action", lambda c: c["on_trigger"].update(branches=[{"if_text": "x", "then": {"action": "?", "text": "t"}}])),
            ("on_trigger.otherwise", lambda c: c["on_trigger"].update(otherwise={"action": "notify_only", "text": "t"})),   # без branches
            ("not_before", lambda c: c.update(not_before="2027-01-01")),
            ("valid_until", lambda c: c.update(valid_until="31.12.2026")),
            ("valid_until", lambda c: c.update(valid_until="2026-11-01")),                       # триггер вне окна
            ("on_expiry", lambda c: c.update(valid_until=None, on_expiry={"action": "notify_only", "text": "t"})),
            ("context.plan_pct", lambda c: c["context"].update(plan_pct=101)),
            ("context.as_of", lambda c: c["context"].update(as_of="2026-10-29")),
            ("source.kind", lambda c: c["source"].update(kind="chat")),
            ("created_at", lambda c: c.update(created_at="2026-10-29T17:40:12")),
            ("created_by", lambda c: c.update(created_by="user")),
            ("withdrawn.reason", lambda c: c.update(withdrawn={"at": "2026-10-29T17:40:12+03:00", "by": "owner"})),
            ("withdrawn.at", lambda c: c.update(withdrawn={"at": "вчера", "by": "owner", "reason": "x"})),
            ("superseded_by", lambda c: c.update(superseded_by="c-1")),
            ("неизвестное", lambda c: c.update(state="pending")),                                # поле из 1.2
            ("обязательное", lambda c: c.pop("trigger")),
        ]
        for frag, fn in cases:
            with self.subTest(frag=frag):
                self.assertHasErr(mut(fn), frag)

    def test_branches_inside_on_trigger_ok(self):
        c = good_cond()
        c["on_trigger"]["branches"] = [{"if_text": "x", "then": {"action": "set_verdict", "verdict": "HOLD", "text": "t"}}]
        c["on_trigger"]["otherwise"] = {"action": "notify_only", "text": "t"}
        self.assertNoErr(ds.validate_condition_def(c))

    def test_report_published_ok(self):
        c = good_cond(trigger={"type": "report_published", "value": "МСФО 9М", "window_end": "2026-12-20"})
        self.assertNoErr(ds.validate_condition_def(c))


class TestReinvest(ErrCase):
    """R30 (03.11): исход «реинвестировать» и запрет вердикта после погашения (правила 18–19 валидатора)."""

    def reinvest(self, **over):
        ot = {"action": "reinvest", "target": "ОФЗ/>10", "amount_source": "redemption", "text": "реинвест в ОФЗ"}
        ot.update(over)
        return good_cond(key="RU000A105146", kind="trade", trigger={"type": "date", "value": "2026-11-19"},
                         while_pending={"verdict": "HOLD_TO_MAT", "text": "держим"}, on_trigger=ot)

    def test_valid(self):
        self.assertNoErr(ds.validate_condition_def(self.reinvest()))
        self.assertNoErr(ds.validate_condition_def(self.reinvest(target="RU000A10FC62")))   # цель — ключ бумаги
        c = self.reinvest()
        c["on_trigger"].pop("amount_source")
        self.assertNoErr(ds.validate_condition_def(c))

    def test_rules(self):
        cases = [
            ("on_trigger.verdict", self.reinvest(verdict="BUY")),
            ("on_trigger.target_pct", self.reinvest(target_pct=3.0)),
            ("on_trigger.target", self.reinvest(target=None)),
            ("on_trigger.target", self.reinvest(target="ОФЗ длинные")),
            ("on_trigger.amount_source", self.reinvest(amount_source="dividend")),
            ("on_trigger.text", self.reinvest(text="")),
            ("on_trigger.target: допустим только у action=reinvest",
             good_cond(on_trigger={"action": "set_verdict", "verdict": "BUY", "target": "CNY", "text": "t"})),
            ("on_trigger.amount_source: допустим только",
             good_cond(on_trigger={"action": "notify_only", "amount_source": "coupon", "text": "t"})),
        ]
        for frag, c in cases:
            with self.subTest(frag=frag):
                self.assertHasErr(ds.validate_condition_def(c), frag)

    def test_verdict_after_maturity(self):
        mat = {"RU000A105146": "2026-11-19"}
        bad = self.reinvest()
        bad["on_trigger"] = {"action": "set_verdict", "verdict": "BUY", "text": "реинвест"}
        self.assertNoErr(ds.validate_condition_def(bad))                   # схема без дат погашения пропускает
        self.assertHasErr(ds.maturity_errors(bad, mat), "после погашения 2026-11-19")
        self.assertHasErr(ds.maturity_errors(bad, {"RU000A105146": "2026-11-01"}), "используй action=reinvest")
        self.assertEqual(ds.maturity_errors(bad, {"RU000A105146": "2026-11-20"}), [])   # триггер до погашения
        self.assertEqual(ds.maturity_errors(bad, {}), [])                               # даты нет — пропуск
        self.assertEqual(ds.maturity_errors(self.reinvest(), mat), [])                  # reinvest — можно
        sell = self.reinvest()
        sell["on_trigger"] = {"action": "set_verdict", "verdict": "SELL", "text": "продать"}
        self.assertEqual(ds.maturity_errors(sell, mat), [])
        br = self.reinvest()
        br["on_trigger"] = {"action": "run_analysis", "text": "разобрать",
                            "branches": [{"if_text": "x", "then": {"action": "set_verdict", "verdict": "HOLD_TO_MAT", "text": "t"}}],
                            "otherwise": {"action": "set_verdict", "verdict": "ADD", "text": "t"}}
        errs = ds.maturity_errors(br, mat)
        self.assertEqual(len(errs), 2, errs)
        price = self.reinvest()
        price["trigger"] = {"type": "price_below", "value": 90}
        price["on_trigger"] = {"action": "set_verdict", "verdict": "BUY", "text": "t"}
        self.assertEqual(ds.maturity_errors(price, mat), [])                            # не датный триггер


class TestFileValidator(ErrCase):
    def test_valid_with_versions(self):
        v1 = good_cond(superseded_by="c-2026-10-29-aaaa-1@2")
        v2 = good_cond(version=2)
        self.assertNoErr(ds.validate_conditions_file(good_file(v1, v2)))

    def test_rules(self):
        self.assertHasErr(ds.validate_conditions_file({"schema_version": "conditions@1.2", "conditions": []}), "schema_version")
        self.assertHasErr(ds.validate_conditions_file(good_file(good_cond(), good_cond())), "дубль")
        # не последняя версия без superseded_by
        self.assertHasErr(ds.validate_conditions_file(good_file(good_cond(), good_cond(version=2))), "не последней версии")
        # у последней версии superseded_by
        self.assertHasErr(ds.validate_conditions_file(good_file(good_cond(superseded_by="c-2026-10-29-aaaa-1@2"))),
                          "должно быть null")
        # ссылка на несуществующую версию
        v1 = good_cond(superseded_by="c-2026-10-29-aaaa-1@5")
        self.assertHasErr(ds.validate_conditions_file(good_file(v1, good_cond(version=2))), "не указывает")
        # ошибка записи получает путь с индексом
        self.assertHasErr(ds.validate_conditions_file(good_file(good_cond(kind="x"))), "conditions[0].kind")
        self.assertNoErr(ds.validate_conditions_file(good_file(good_cond(converted_from_date=True))))
        self.assertHasErr(ds.validate_conditions_file({"schema_version": "conditions@2", "conditions": {}}), "conditions")


class TestStateValidator(ErrCase):
    def test_valid(self):
        st = good_state(ev(event="fired", price=1.5), ev(event="done", trade_date="2026-10-30"),
                        ev(event="reopened", by="owner"), ev(event="owner_mark", mark="deferred", until="2026-11-10"),
                        ev(event="owner_mark", mark="dismissed"), ev(event="event_found", by="monitor", doc="x"))
        self.assertNoErr(ds.validate_conditions_state(st))

    def test_rules(self):
        def mut(fn):
            s = good_state(ev())
            fn(s)
            return ds.validate_conditions_state(s)
        cases = [
            ("schema_version", lambda s: s.update(schema_version="conditions-state@2")),
            ("last_checked_at", lambda s: s.update(last_checked_at=None)),                      # поле не допускается
            ("events[0].event", lambda s: s["events"][0].update(event="definition_withdrawn")),
            ("events[0].data.mark", lambda s: s["events"][0].update(event="owner_mark", data={"mark": "done"})),
            ("events", lambda s: s.update(events={})),
            ("events[0].event", lambda s: s["events"][0].update(event="checked")),
            ("events[0].at", lambda s: s["events"][0].update(at="2026-10-29T12:00:00")),
            ("events[0].by", lambda s: s["events"][0].update(by="user")),
            ("events[0].version", lambda s: s["events"][0].update(version="1")),
            ("events[0].condition_id", lambda s: s["events"][0].update(condition_id="")),
            ("events[0].data", lambda s: s["events"][0].update(event="done", data={})),       # done без опоры (by: notifier)
            ("events[0].data", lambda s: s["events"][0].update(event="done", by="site", data={})),  # сайт-маршрут — с опорой
            ("events[0].event", lambda s: s["events"][0].update(event="touched")),              # убран из кодлиста
            ("events[0].data.mark", lambda s: s["events"][0].update(event="owner_mark", data={"mark": "later"})),
            ("events[0].data.until", lambda s: s["events"][0].update(event="owner_mark", data={"mark": "deferred"})),
            ("events[0].by", lambda s: s["events"][0].update(event="reopened", by="notifier")),
            ("events[0].data.price", lambda s: s["events"][0].update(data={"price": "много"})),
            ("events[0].data.trade_date", lambda s: s["events"][0].update(event="done", data={"trade_date": "вчера"})),
            ("неизвестное", lambda s: s["events"][0].update(extra=1)),
            ("обязательное", lambda s: s.pop("events")),
        ]
        for frag, fn in cases:
            with self.subTest(frag=frag):
                self.assertHasErr(mut(fn), frag)

    def test_owner_done_without_data(self):
        # «сделал» с сайта шлёт done без data — отметка владельца сама опора
        self.assertNoErr(ds.validate_conditions_state(good_state(ev(event="done", by="owner"))))
        e = ev(event="done", by="owner")
        e.pop("data")
        self.assertNoErr(ds.validate_conditions_state(good_state(e)))

    def test_version_optional(self):
        e = ev()
        e.pop("version")
        self.assertNoErr(ds.validate_conditions_state(good_state(e)))

    def test_refs(self):
        f = good_file(good_cond(id="c-1"))
        self.assertHasErr(ds.validate_state_refs(good_state(ev(cid="c-zzz")), f), "нет в определениях")
        self.assertHasErr(ds.validate_state_refs(good_state(ev(cid="c-1", version=3)), f), "больше последней")
        self.assertEqual(ds.validate_state_refs(good_state(ev(cid="c-1")), f), [])


class TestCli(unittest.TestCase):
    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as t:
            good = os.path.join(t, "d.json")
            bad = os.path.join(t, "bad.json")
            with open(good, "w") as fh:
                json.dump(good_decision(), fh)
            d = good_decision()
            d["verdict"] = "X"
            with open(bad, "w") as fh:
                json.dump(d, fh)
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(ds.main(["decision", good]), 0)
                self.assertEqual(ds.main(["decision", bad]), 1)
            self.assertIn("verdict", buf.getvalue())


# ---------------------------------------------------------------- объединение

class TestMerge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        doc = ds.load_yaml(os.path.join(FIX, "merge_defs.yaml"))
        cls.defs = doc["conditions"]
        with open(os.path.join(FIX, "merge_state.json"), encoding="utf-8") as f:
            cls.state = json.load(f)
        cls.out = {r["id"]: r for r in cm.merge(cls.defs, cls.state, TODAY)}

    def test_fixtures_valid(self):
        self.assertEqual(ds.validate_conditions_file({"schema_version": "conditions@2", "conditions": self.defs}), [])
        self.assertEqual(ds.validate_conditions_state(self.state), [])

    def test_pending(self):
        r = self.out["c-pending"]
        self.assertEqual((r["status"], r["active"], r["waits_owner"], r["last_event"]), ("pending", True, False, None))

    def test_price_cross_is_fired(self):
        r = self.out["c-price-fired"]
        self.assertEqual((r["status"], r["active"], r["waits_owner"]), ("fired", True, True))
        self.assertEqual(r["fired_at"], "2026-10-15T11:00:00+03:00")
        self.assertEqual(r["last_event"]["event"], "fired")
        self.assertNotIn("touched_at", r)

    def test_fired_waits_owner(self):
        r = self.out["c-fired"]
        self.assertEqual((r["status"], r["active"], r["waits_owner"]), ("fired", True, True))
        self.assertEqual(r["fired_at"], "2026-10-20T09:00:00+03:00")
        self.assertFalse(r["fired_by_deadline"])

    def test_done_closed(self):
        # события в файле идут в обратном порядке (done раньше fired) — порядок решает `at`
        r = self.out["c-done"]
        self.assertEqual((r["status"], r["active"], r["waits_owner"]), ("done", False, False))
        self.assertEqual(r["fired_at"], "2026-10-20T09:00:00+03:00")

    def test_withdrawn_with_live_fired(self):
        r = self.out["c-withdrawn"]
        self.assertEqual((r["status"], r["state_status"], r["active"], r["waits_owner"]), ("withdrawn", "fired", False, False))
        self.assertEqual(r["withdrawn_at"], "2026-10-28T09:00:00+03:00")
        self.assertEqual(r["version"], 2)

    def test_expired_computed_with_on_expiry(self):
        r = self.out["c-expired"]
        self.assertEqual((r["status"], r["active"], r["computed"]), ("expired", False, True))
        self.assertEqual(r["on_expiry"], {"action": "set_verdict", "verdict": "TRIM", "text": "срезать часть"})
        self.assertIsNone(self.out["c-pending"]["on_expiry"])

    def test_date_deadline(self):
        r = self.out["c-date-deadline"]
        self.assertEqual((r["status"], r["fired_by_deadline"], r["waits_owner"], r["computed"]), ("fired", True, True, True))
        self.assertEqual(r["fired_at"], "2026-10-20T00:00:00+03:00")
        # дата срабатывает В ДЕНЬ события; накануне ещё pending
        r = {x["id"]: x for x in cm.merge(self.defs, self.state, "2026-10-20")}["c-date-deadline"]
        self.assertEqual((r["status"], r["fired_by_deadline"], r["fired_at"]), ("fired", True, "2026-10-20T00:00:00+03:00"))
        r = {x["id"]: x for x in cm.merge(self.defs, self.state, "2026-10-19")}["c-date-deadline"]
        self.assertEqual(r["status"], "pending")
        # дедлайна у price_* нет: expired только по valid_until
        self.assertEqual(self.out["c-price-fired"]["fired_by_deadline"], False)

    def test_reopened_resets(self):
        r = self.out["c-reopened"]            # fired, done, reopened -> заново pending
        self.assertEqual((r["status"], r["active"], r["fired_at"]), ("pending", True, None))
        self.assertEqual(r["last_event"]["event"], "reopened")
        r = self.out["c-reopened-fired"]      # после reopened снова сработало
        self.assertEqual((r["status"], r["waits_owner"], r["fired_at"]), ("fired", True, "2026-10-25T09:00:00+03:00"))

    def test_owner_marks(self):
        r = self.out["c-mark-done"]            # «сделал» с сайта = done, by owner
        self.assertEqual((r["status"], r["active"], r["closed_as"]), ("done", False, "done"))
        self.assertEqual(r["last_event"]["by"], "owner")
        r = self.out["c-mark-dismissed"]
        self.assertEqual((r["status"], r["active"], r["closed_as"]), ("done", False, "dismissed"))

    def test_deferred(self):
        r = self.out["c-deferred"]
        self.assertEqual((r["status"], r["active"], r["waits_owner"], r["deferred_until"]), ("fired", True, False, "2026-11-10"))
        # после until снова ждёт владельца
        r = {x["id"]: x for x in cm.merge(self.defs, self.state, "2026-11-10")}["c-deferred"]
        self.assertTrue(r["waits_owner"])
        r = self.out["c-deferred-past"]
        self.assertEqual((r["status"], r["waits_owner"], r["deferred_until"]), ("fired", True, "2026-10-25"))
        # отсрочка у вычисленного по сроку fired
        r = self.out["c-deferred-deadline"]
        self.assertEqual((r["status"], r["fired_by_deadline"], r["waits_owner"]), ("fired", True, False))

    def test_event_found_is_info_only(self):
        r = self.out["c-found"]
        self.assertEqual((r["status"], r["found_at"], r["found_doc"]), ("pending", "2026-10-28T09:00:00+03:00", "https://example.test/report"))
        self.assertEqual(r["last_event"]["event"], "event_found")

    def test_expired_by_event(self):
        r = self.out["c-expired-event"]
        self.assertEqual((r["status"], r["active"], r["computed"]), ("expired", False, False))

    def test_report_window_passed_fires_by_deadline(self):
        r = self.out["c-report-passed"]
        self.assertEqual((r["status"], r["active"], r["waits_owner"], r["fired_by_deadline"]), ("fired", True, True, True))
        self.assertEqual(r["fired_at"], "2026-10-20T23:59:59+03:00")
        self.assertEqual(r["window_end"], "2026-10-20")

    def test_report_window_future_pending(self):
        r = self.out["c-report-future"]
        self.assertEqual((r["status"], r["fired_by_deadline"]), ("pending", False))

    def test_window_boundary(self):
        # window_end == today: окно ещё не прошло
        self.assertEqual({r["id"]: r for r in cm.merge(self.defs, self.state, "2026-10-20")}["c-report-passed"]["status"], "pending")
        self.assertEqual({r["id"]: r for r in cm.merge(self.defs, self.state, "2026-10-21")}["c-report-passed"]["status"], "fired")

    def test_last_version_resets_state(self):
        # правило 14: fired версии 1 (10.10) раньше created_at версии 2 (12.10) — не засчитан;
        # 30.10 условие сработало заново по сроку новой даты (25.10)
        r = self.out["c-multi"]
        self.assertEqual((r["version"], r["verdict_now"], r["text"]), (2, "WATCH", "новая"))
        self.assertEqual((r["status"], r["computed"], r["last_event"]), ("fired", True, None))
        r = self.out["c-multi-after"]
        self.assertEqual((r["status"], r["fired_at"], r["closed_as"]), ("fired", "2026-10-15T09:00:00+03:00", None))

    def test_flat_fields(self):
        r = self.out["c-price-fired"]
        self.assertEqual(r["key_kind"], "ticker")
        self.assertNotIn("asset_class", r)
        self.assertEqual((r["verdict_on_trigger"], r["target_pct_on_trigger"], r["action_code"], r["verdict_now"]),
                         ("BUY", 5, "set_target_pct", "HOLD"))
        for k in ("id", "version", "key", "key_kind", "kind", "trigger", "status", "active", "waits_owner",
                  "last_event", "fired_at", "verdict_now", "verdict_on_trigger",
                  "target_pct_on_trigger", "action_code", "valid_until", "window_end", "withdrawn_at", "text"):
            self.assertIn(k, r)

    def test_terminal_events_not_overridden_by_deadline(self):
        # fired в прошлом при истёкшем valid_until остаётся fired (ждёт владельца)
        defs = copy.deepcopy(self.defs)
        for d in defs:
            if d["id"] == "c-fired":
                d["valid_until"] = "2026-10-01"
        r = {x["id"]: x for x in cm.merge(defs, self.state, TODAY)}["c-fired"]
        self.assertEqual((r["status"], r["waits_owner"]), ("fired", True))

    def test_deterministic_order(self):
        base = cm.merge(self.defs, self.state, TODAY)
        self.assertEqual([(r["key"], r["id"]) for r in base], sorted((r["key"], r["id"]) for r in base))
        rnd = random.Random(7)
        for _ in range(5):
            defs = list(self.defs)
            rnd.shuffle(defs)
            # события перемешиваются между условиями; внутри одного условия порядок файла сохраняется —
            # он решает при равном `at` (event_found и fired одной секундой, правило 3)
            groups = {}
            for e in self.state["events"]:
                groups.setdefault(e["condition_id"], []).append(e)
            tags = [cid for cid, lst in groups.items() for _ in lst]
            rnd.shuffle(tags)
            pos = {cid: 0 for cid in groups}
            events = []
            for cid in tags:
                events.append(groups[cid][pos[cid]])
                pos[cid] += 1
            again = cm.merge(defs, {**self.state, "events": events}, TODAY)
            self.assertEqual(json.dumps(again, sort_keys=True), json.dumps(base, sort_keys=True))

    def test_orphans_and_select(self):
        self.assertEqual(cm.orphan_event_ids(self.defs, self.state), ["c-orphan"])
        allr = cm.merge(self.defs, self.state, TODAY)
        self.assertTrue(all(r["id"] != "c-orphan" for r in allr))
        self.assertEqual({r["key"] for r in cm.select(allr, keys=["AAAA"])}, {"AAAA"})
        self.assertTrue(all(r["active"] for r in cm.select(allr, only_active=True)))

    def test_cli(self):
        buf = io.StringIO()
        args = ["--defs", os.path.join(FIX, "merge_defs.yaml"), "--state", os.path.join(FIX, "merge_state.json"),
                "--today", TODAY]
        with redirect_stdout(buf):
            self.assertEqual(cm.main(args + ["--key", "BBBB", "--all"]), 0)
        lines = buf.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 1 + 3)    # шапка + c-done, c-expired-event, c-fired
        self.assertIn("ждёт владельца", buf.getvalue())
        buf = io.StringIO()
        with redirect_stdout(buf):
            cm.main(args + ["--format", "json", "--key", "DDDD"])
        self.assertEqual(len(json.loads(buf.getvalue())), 2)


# ---------------------------------------------------------------- миграция

class TestMigration(ErrCase):
    @classmethod
    def setUpClass(cls):
        cls.src = ds.load_yaml(os.path.join(FIX, "conditions_v12.yaml"))
        cls.defs, cls.state, cls.ctx, cls.rows = mg.migrate(cls.src)
        cls.d = {c["id"]: c for c in cls.defs["conditions"]}
        cls.events = cls.state["events"]

    def ev_of(self, cid):
        return [e for e in self.events if e["condition_id"] == cid]

    def test_result_valid(self):
        self.assertNoErr(ds.validate_conditions_file(self.defs))
        self.assertNoErr(ds.validate_conditions_state(self.state))
        self.assertNoErr(ds.validate_state_refs(self.state, self.defs))

    def test_rule14_keeps_all_migrated_events(self):
        # правило 14 модуля (а): события раньше created_at последней версии не засчитываются; миграция ставит
        # определениям created_at = день создания 00:00, событиям — 00:00 того же дня или позже, — ничего не теряется
        self.assertTrue(self.events)
        for cid, d in self.d.items():
            evs = self.ev_of(cid)
            self.assertEqual(cm.events_since(evs, d["created_at"]), evs, cid)

    def test_basic_mapping(self):
        d = self.d["aaaa-branches"]
        self.assertEqual((d["key"], d["version"]), ("AAAA", 1))
        for gone in ("key_kind", "asset_class", "asset_class_guessed"):
            self.assertNotIn(gone, d)
        self.assertEqual((d["created_at"], d["time_estimated"], d["created_by"]), ("2026-06-01T00:00:00+03:00", True, "mode_4"))
        self.assertEqual(d["event_text"], "Отчётность 9М AAAA")
        # event + date -> report_published (проверка владельцем), прежняя дата -> window_end
        self.assertEqual(d["trigger"], {"type": "report_published", "value": "Отчётность 9М AAAA", "window_end": "2026-12-03"})
        self.assertTrue(d["converted_from_date"])
        # прежняя дата 2026-11-30 + 3 дня = 2026-12-03
        self.assertEqual(self.ctx.converted, [("aaaa-branches", "AAAA", "Отчётность 9М AAAA", "2026-11-30", "2026-12-03")])
        self.assertEqual(self.d["bbbb-fired"]["trigger"]["type"], "date")        # без event остаётся датой
        self.assertNotIn("converted_from_date", self.d["bbbb-fired"])
        self.assertEqual(d["while_pending"], {"verdict": "HOLD", "text": "ждём отчёт"})
        self.assertEqual(d["source"], {"kind": "migration", "doc": None})
        self.assertEqual((d["withdrawn"], d["superseded_by"]), (None, None))
        self.assertEqual(d["context"], {"plan_pct": 2.0, "snapshot_id": "portfolio-2026-10-20.json",
                                        "as_of": "2026-06-01T00:00:00+03:00"})
        for gone in ("ticker", "created", "state", "fired_date", "history", "touched"):
            self.assertNotIn(gone, d)

    def test_isin_key(self):
        d = self.d["ru000a000aa0-date"]
        self.assertEqual(ds.key_kind(d["key"]), "isin")
        self.assertNotIn("asset_class", self.d["ffff-trade-notify"])

    def test_action_codes(self):
        expect = {
            "aaaa-branches": "run_analysis",            # kind == review
            "aaaa-below-100": "set_target_pct",         # target_pct, kind выведен = trade (BUY)
            "bbbb-fired": "run_analysis",               # kind выведен = review (verdict null)
            "ru000a000aa0-date": "set_verdict",         # TRIM -> trade, verdict без target
            "ffff-trade-notify": "notify_only",         # trade без verdict
            "bbbb-trade-review-status": "run_analysis",  # trade, но set_status == review_needed
        }
        for cid, code in expect.items():
            with self.subTest(cid=cid):
                self.assertEqual(self.d[cid]["on_trigger"]["action"], code)
        self.assertEqual(self.d["aaaa-below-100"]["kind"], "trade")
        self.assertEqual(self.d["bbbb-fired"]["kind"], "review")

    def test_on_trigger_text_and_set_status_dropped(self):
        d = self.d["aaaa-branches"]
        self.assertEqual(d["on_trigger"]["text"], "Разбор Mode 4 после отчёта")
        self.assertNotIn("set_status", d["on_trigger"])
        self.assertIn("on_trigger.set_status (значение review_needed)", self.ctx.dropped)

    def test_branches(self):
        d = self.d["aaaa-branches"]
        self.assertNotIn("branches", d)                 # ветки только внутри on_trigger
        self.assertNotIn("otherwise", d)
        b0, b1 = d["on_trigger"]["branches"]
        self.assertEqual(b0["if_text"], "показатель не ниже порога")
        self.assertEqual((b0["then"]["action"], b0["then"]["verdict"]), ("set_verdict", "HOLD"))
        self.assertEqual(b0["then"]["text"], "держать — порог продажи отдельным условием")
        self.assertEqual((b1["then"]["action"], b1["then"]["target_pct"]), ("set_target_pct", 1.5))
        ow = d["on_trigger"]["otherwise"]
        self.assertEqual(ow["action"], "set_verdict")
        self.assertEqual(ow["text"], "держать — решение владельца")

    def test_trigger_value_types(self):
        self.assertEqual(self.d["aaaa-below-100"]["trigger"], {"type": "price_below", "value": 100})
        self.assertEqual(self.d["ffff-trade-notify"]["trigger"]["value"], 12.5)

    def test_on_expiry_preserved(self):
        oe = self.d["ru000a000aa0-date"]["on_expiry"]
        self.assertEqual((oe["action"], oe["verdict"], oe["text"]), ("set_verdict", "HOLD", "ничего не делать"))

    def test_actor(self):
        self.assertEqual(self.d["aaaa-below-100"]["created_by"], "owner")       # синоним user
        self.assertEqual(self.d["ru000a000aa0-date"]["created_by"], "script")   # неизвестный
        self.assertTrue(any(o[1] == "created_by" and o[2] == "robot" for o in self.ctx.out_of_lists))

    def test_fired_and_closed_manual(self):
        evs = self.ev_of("bbbb-fired")
        self.assertEqual([e["event"] for e in evs], ["fired", "done"])
        self.assertEqual(evs[0]["at"], "2026-10-29T00:00:00+03:00")
        self.assertTrue(evs[0]["time_estimated"])
        self.assertEqual(evs[0]["by"], "script")
        self.assertEqual(evs[1]["data"]["note"], "закрыто владельцем")
        self.assertEqual(evs[1]["by"], "owner")

    def test_touched_struct_becomes_fired_no_dup(self):
        evs = self.ev_of("aaaa-below-100")
        self.assertEqual([e["event"] for e in evs], ["fired"])        # price_touched из истории не задублирован
        self.assertEqual(evs[0]["at"], "2026-10-10T14:35:00+03:00")
        self.assertEqual(evs[0]["by"], "notifier")
        self.assertEqual(evs[0]["data"]["price"], 99.5)
        self.assertNotIn("time_estimated", evs[0])

    def test_history_loss_counts(self):
        rows = {r["id"]: r for r in self.rows}
        self.assertEqual(rows["aaaa-branches"]["lost"], 2)             # created + edited
        self.assertEqual(rows["aaaa-below-100"]["lost"], 1)            # created (price_touched дубль, не потеря)
        self.assertEqual(rows["ru000a000aa0-date"]["lost"], 1)         # reopened теперь событие, не потеря
        self.assertEqual([e["event"] for e in self.ev_of("ru000a000aa0-date")], ["reopened"])
        self.assertEqual(self.ev_of("ru000a000aa0-date")[0]["by"], "owner")
        self.assertEqual(rows["ffff-trade-notify"]["lost_detail"].get("не отображено"), 1)
        self.assertEqual(self.ctx.unmapped, [("ffff-trade-notify", "2026-09-12", "weird_event")])
        self.assertEqual(self.ctx.dropped["history[event=created]"], 6)
        self.assertEqual(self.ctx.dropped["history[event=edited]"], 1)

    def test_events_sorted_and_state_meta(self):
        ats = [e["at"] for e in self.events]
        self.assertEqual(ats, sorted(ats))
        self.assertNotIn("last_checked_at", self.state)
        self.assertNotIn("definition_withdrawn", {e["event"] for e in self.events})

    def test_fired_without_date_warns(self):
        src = copy.deepcopy(self.src)
        for c in src["conditions"]:
            if c["id"] == "bbbb-fired":
                c["fired_date"] = None
        defs, state, ctx, rows = mg.migrate(src)
        self.assertNoErr(ds.validate_conditions_state(state))
        self.assertTrue(any("fired_date" in w for ws in ctx.warnings.values() for w in ws))

    def test_valid_until_raised_to_window_end(self):
        src = copy.deepcopy(self.src)
        for c in src["conditions"]:
            if c["id"] == "aaaa-branches":
                c["valid_until"] = "2026-12-01"          # раньше нового window_end 2026-12-03
        defs, state, ctx, _ = mg.migrate(src)
        d = {c["id"]: c for c in defs["conditions"]}["aaaa-branches"]
        self.assertEqual(d["valid_until"], "2026-12-03")
        self.assertEqual(ctx.valid_until_raised, [("aaaa-branches", "2026-12-01", "2026-12-03")])
        self.assertNoErr(ds.validate_conditions_file(defs))
        # valid_until позже окна не трогается
        for c in src["conditions"]:
            if c["id"] == "aaaa-branches":
                c["valid_until"] = "2026-12-31"
        defs, _, ctx, _ = mg.migrate(src)
        self.assertEqual({c["id"]: c for c in defs["conditions"]}["aaaa-branches"]["valid_until"], "2026-12-31")
        self.assertEqual(ctx.valid_until_raised, [])

    def test_report_shows_old_date_and_new_window(self):
        defs, state, ctx, rows = mg.migrate(self.src)
        rep = mg.render_report("x.yaml", defs, state, ctx, rows, [])
        self.assertIn("| aaaa-branches | AAAA | Отчётность 9М AAAA | 2026-11-30 | 2026-12-03 |", rep)
        self.assertIn("поднят valid_until до нового window_end: 0", rep)
        self.assertNotIn("asset_class", rep)

    def test_unknown_field_reported(self):
        src = copy.deepcopy(self.src)
        src["conditions"][0]["mystery"] = 1
        _, _, ctx, _ = mg.migrate(src)
        self.assertIn("условие.mystery (неизвестное поле)", ctx.dropped)

    def test_cli_dry_run_and_out(self):
        path = os.path.join(FIX, "conditions_v12.yaml")
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(mg.main(["--in", path]), 0)
        self.assertIn("| id | key | kind |", buf.getvalue())
        self.assertIn("валидация пройдена", buf.getvalue())
        with tempfile.TemporaryDirectory() as t:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(mg.main(["--in", path, "--out", t]), 0)
            self.assertEqual(sorted(os.listdir(t)), ["conditions-state.json", "conditions.yaml", "migration-report.md"])
            # записанные файлы читаются обратно и проходят валидаторы
            back = ds.load_yaml(os.path.join(t, "conditions.yaml"))
            self.assertEqual(ds.validate_conditions_file(back), [])
            with open(os.path.join(t, "conditions-state.json"), encoding="utf-8") as fh:
                st = json.load(fh)
            self.assertEqual(ds.validate_conditions_state(st), [])
            # и объединяются
            merged = cm.merge(back["conditions"], st, TODAY)
            self.assertEqual(len(merged), len(self.defs["conditions"]))
            self.assertEqual({r["id"]: r["status"] for r in merged}["bbbb-fired"], "done")
            self.assertEqual({r["id"]: r["status"] for r in merged}["aaaa-below-100"], "fired")
            self.assertEqual({r["id"]: r["status"] for r in merged}["ru000a000aa0-date"], "pending")   # после reopened

    def test_memory_guard(self):
        with redirect_stdout(io.StringIO()), io.StringIO() as err:
            old, sys.stderr = sys.stderr, err
            try:
                code = mg.main(["--in", os.path.join(FIX, "conditions_v12.yaml"), "--out", "/x/Claude-Memory/y"])
            finally:
                sys.stderr = old
        self.assertEqual(code, 2)



class TestMigrationDecisionLinks(ErrCase):
    """R23 (шаг 14 п.0): --decisions восстанавливает связь «условие <-> решение» по отчёту-источнику из заметки."""

    @staticmethod
    def cond(cid, key, created_note, closed_note=None):
        hist = [{"date": "2026-10-23", "event": "created", "note": created_note}]
        if closed_note is not None:
            hist.append({"date": "2026-10-29", "event": "closed_manual", "note": closed_note})
        return {"id": cid, "ticker": key, "created": "2026-10-23", "created_by": "mode_4",
                "trigger": {"type": "price_above", "value": 100}, "while_pending": {"verdict": "HOLD"},
                "on_trigger": {"action": "разбор", "verdict": "HOLD"},
                "state": "fired" if closed_note is not None else "pending",
                "fired_date": "2026-10-29" if closed_note is not None else None, "history": hist}

    @staticmethod
    def dec(did, key, doc, day):
        return {"id": did, "key": key, "doc": doc, "date": day}

    def setUp(self):
        self.src = {"schema_version": "conditions@1.2", "conditions": [
            self.cond("aaaa-linked", "AAAA", "Mode 4 от 23.10 (Portfolio/reports/2026-10-23-single-analysis-aaaa.md): HOLD"),
            self.cond("bbbb-done", "BBBB", "без отчёта",
                      "исполнено: разбор (Mode 4, reports/2026-10-29-single-analysis-bbbb.md)"),
            self.cond("cccc-ambig", "CCCC", "Portfolio/reports/2026-10-23-multi.md"),
            self.cond("dddd-other-key", "DDDD", "Portfolio/reports/2026-10-23-single-analysis-aaaa.md"),
            self.cond("eeee-nodoc", "EEEE", "Mode 4 от 23.10.2026: без пути"),
        ]}
        self.decisions = [
            self.dec("2026-10-23T0000-AAAA", "AAAA", "Portfolio/reports/2026-10-23-single-analysis-aaaa.md", "2026-10-23"),
            self.dec("2026-10-29T0000-BBBB", "BBBB", "Portfolio/reports/2026-10-29-single-analysis-bbbb.md", "2026-10-29"),
            self.dec("2026-10-23T0000-CCCC", "CCCC", "Portfolio/reports/2026-10-23-multi.md", "2026-10-23"),
            self.dec("2026-10-23T0001-CCCC", "CCCC", "Portfolio/reports/2026-10-23-multi.md", "2026-10-23"),
            self.dec("2026-10-23T0000-EEEE", "EEEE", "Portfolio/reports/2026-10-23-x.md", "2026-10-23"),
        ]

    def run_mg(self):
        defs, state, ctx, rows = mg.migrate(copy.deepcopy(self.src), self.decisions)
        self.assertNoErr(ds.validate_conditions_file(defs))
        self.assertNoErr(ds.validate_conditions_state(state))
        return {c["id"]: c for c in defs["conditions"]}, state["events"], ctx

    def test_definition_linked_by_report(self):
        d, _, _ = self.run_mg()
        self.assertEqual(dict(d["aaaa-linked"]["source"]), {
            "kind": "report", "doc": "Portfolio/reports/2026-10-23-single-analysis-aaaa.md",
            "decision_id": "2026-10-23T0000-AAAA"})
        self.assertIn("report", ds.CODELISTS["condition_source"])

    def test_done_by_owner_gets_decision_id(self):
        d, evs, _ = self.run_mg()
        done = [e for e in evs if e["condition_id"] == "bbbb-done" and e["event"] == "done"]
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0]["by"], "owner")
        self.assertEqual(done[0]["data"]["decision_id"], "2026-10-29T0000-BBBB")   # путь reports/… нормализован
        self.assertEqual(d["bbbb-done"]["source"]["kind"], "migration")             # у определения пути нет

    def test_no_guessing(self):
        d, _, ctx = self.run_mg()
        for cid in ("cccc-ambig", "dddd-other-key", "eeee-nodoc"):
            self.assertEqual(d[cid]["source"]["kind"], "migration", cid)
            self.assertNotIn("decision_id", d[cid]["source"], cid)
        why = {x[0]: x[3] for x in ctx.links if not x[2]}
        self.assertIn("неоднозначно: 2", why["cccc-ambig"])
        self.assertIn("нет решения", why["dddd-other-key"])                      # решение чужой бумаги не годится
        self.assertIn("нет пути", why["eeee-nodoc"])
        cands = {x[0]: x[5] for x in ctx.links}
        self.assertEqual(cands["eeee-nodoc"], ["2026-10-23T0000-EEEE"])           # кандидат по дате — только в отчёт

    def test_idempotent_and_report(self):
        a = self.run_mg()
        b = self.run_mg()
        self.assertEqual(json.dumps(a[0], ensure_ascii=False), json.dumps(b[0], ensure_ascii=False))
        self.assertEqual(json.dumps(a[1], ensure_ascii=False), json.dumps(b[1], ensure_ascii=False))
        defs, state, ctx, rows = mg.migrate(copy.deepcopy(self.src), self.decisions)
        rep = mg.render_report("x.yaml", defs, state, ctx, rows, [])
        self.assertIn("Сопоставлено: **2** из 6", rep)

    def test_without_decisions_unchanged(self):
        defs, state, ctx, rows = mg.migrate(copy.deepcopy(self.src))
        self.assertTrue(all(c["source"]["kind"] == "migration" for c in defs["conditions"]))
        self.assertFalse(any("decision_id" in e["data"] for e in state["events"]))
        self.assertNotIn("Связь «условие", mg.render_report("x.yaml", defs, state, ctx, rows, []))

    def test_cli_decisions_folder(self):
        with tempfile.TemporaryDirectory() as t:
            src = os.path.join(t, "conditions.yaml")
            import yaml
            with open(src, "w", encoding="utf-8") as f:
                yaml.safe_dump(self.src, f, allow_unicode=True)
            dd = os.path.join(t, "decisions")
            os.makedirs(dd)
            for x in self.decisions:
                with open(os.path.join(dd, x["id"] + ".json"), "w", encoding="utf-8") as f:
                    json.dump({"schema_version": "decision@1", "id": x["id"], "key": x["key"],
                               "source": {"kind": "backfill", "doc": x["doc"]},
                               "recorded_at": x["date"] + "T00:00:00+03:00"}, f)
            with open(os.path.join(dd, "broken.json"), "w") as f:
                f.write("{")
            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(io.StringIO()):
                self.assertEqual(mg.main(["--in", src, "--out", os.path.join(t, "out"), "--decisions", dd]), 0)
            self.assertIn("СВЯЗЬ С РЕШЕНИЯМИ: определений 1 из 5, событий done by owner 1 из 1", buf.getvalue())

if __name__ == "__main__":
    unittest.main(verbosity=1)
