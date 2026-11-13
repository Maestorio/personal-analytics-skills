#!/usr/bin/env python3
"""
test_security_digest.py — выборки советника вместо чтения файлов (C5, schema.md §6): `security_digest.py` (одна бумага)
и `journal_digest.py` (журнал решений). Фикстура — временный корень Claude-Memory «в натуральную величину»: 30 обзоров
недели, снапшот, 10 отчётов по 20 КБ, решения, условия conditions@2 + состояние, справочник бумаг, журнал решений.
Живой mount не трогается.

Замер C5: выдача `security_digest.py` по бумаге ≤ 6 000 токенов (байты/4) — `build_fixture` переиспользует сторож
`tools/tests/test_skill_instructions_ds.py`.

Запуск: python3 skills/ru-portfolio-advisor/tests/test_security_digest.py
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE.parents[2] / "_shared-references"))

import journal_digest as JD  # noqa: E402
import security_digest as SD  # noqa: E402

KEY = "AAAA"
TODAY = "2026-11-02"
TOKEN_TARGET = 6000
LONG = ("Длинное обоснование вердикта с цифрами и ссылками на отчётность эмитента. " * 40).strip()


def _decision(key, verdict, rec, review_by=None, doc=None, created=(), resolved=()):
    did = f"{rec[:10]}T{rec[11:13]}{rec[14:16]}-{key}"
    return did, {"schema_version": "decision@1", "id": did, "key": key, "verdict": verdict, "target_pct": 5.0,
                 "review_by": review_by, "note": "одна фраза почему", "conditions_created": list(created),
                 "conditions_resolved": list(resolved),
                 "source": {"kind": "report" if doc else "owner", "doc": doc, "mode_codes": ["4a"] if doc else [],
                            "stress_id": None},
                 "author": "model" if doc else "owner", "recorded_at": rec}


def _cond(cid, key, ttype, value, kind="trade", created_at="2026-10-01T10:00:00+03:00"):
    return {"id": cid, "version": 1, "key": key, "kind": kind, "trigger": {"type": ttype, "value": value},
            "event_text": None, "while_pending": {"verdict": "HOLD", "text": "ждём"},
            "on_trigger": {"action": "set_verdict", "verdict": "TRIM", "text": "срезать до плана"},
            "on_expiry": None, "not_before": None, "valid_until": None, "note": "почему создано",
            "context": None, "source": {"kind": "owner", "doc": None}, "created_at": created_at,
            "created_by": "owner", "withdrawn": None, "superseded_by": None}


def build_fixture(root: str) -> None:
    port = Path(root) / "Portfolio"
    for d in ("weekly-reviews", "snapshots", "reports", "decisions", "decision-journal"):
        (port / d).mkdir(parents=True, exist_ok=True)
    start = date(2026, 4, 6)
    for i in range(30):
        d = (start + timedelta(days=7 * i)).isoformat()
        per = {k: {"advisor_verdict": "HOLD", "advisor_verdict_confidence": 0.7, "advisor_verdict_basis": LONG,
                   "fundamental_score": "MEDIUM", "price_rub": 100 + i, "weight_real_pct": 5.0,
                   "catalyst": [{"id": f"c{j}", "trigger": LONG} for j in range(5)]}
               for k in (KEY, "BBBB", "CCCC")}
        doc = {"schema_version": 2, "type": "weekly-stocks-review", "review_date": d, "per_stock": per}
        if i >= 28:
            doc["recorded_at"] = f"{d}T19:00:00+03:00"
        (port / "weekly-reviews" / f"weekly-review-stock-{d}.yaml").write_text(
            yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    snap = {"as_of_date": "2026-10-30", "holdings": [
        {"ticker": KEY, "isin": "RU000AAAA001", "name": "Эмитент А", "asset_type": "stock", "account": "main",
         "qty": 10, "current_price": 120.5, "value_rub": 1205.0, "listing_date": "2024-12-18",
         "listing_age_quarters": 7, "sector_ru": "Тест"},
        {"ticker": "BBBB", "asset_type": "stock", "account": "main", "qty": 1, "current_price": 1, "value_rub": 1}],
        "ie_actual": {"per_ticker": {KEY: {"real_share_pct": 4.1, "planned_share_pct": 5.0, "user_plan": "держать",
                                           "user_note_ie": LONG}}},
        # KEY: цель есть, цены IE нет, потенциал IE на дату модели — заведомо чужое число; BBBB: цели нет — из цены IE;
        # CCCC: вне портфеля — цены в снапшоте нет
        "ie_model": {"extraction_date": "2026-10-27", "positions": [
            {"ticker": KEY, "active_in_model": False, "current_price_rub": None, "growth_potential_12m_pct": 99.0,
             "growth_potential_lt_pct": 199.0, "target_price_rub": 144.6, "target_price_lt_rub": 180.75},
            {"ticker": "BBBB", "active_in_model": True, "current_price_rub": 2.0, "growth_potential_12m_pct": 50.0,
             "growth_potential_lt_pct": None, "target_price_rub": None, "target_price_lt_rub": None},
            {"ticker": "CCCC", "active_in_model": True, "current_price_rub": 10.0, "growth_potential_12m_pct": 30.0,
             "target_price_rub": 13.0}]}}
    (port / "snapshots" / "portfolio-2026-10-30.json").write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    # история сделок для паузы докупки (правило 7 модуля (б), 11.11: от первой покупки после решения): покупка KEY 28.10
    for day, qty in (("2026-10-27", 5), ("2026-10-28", 10)):
        (port / "snapshots" / f"portfolio-{day}.json").write_text(json.dumps(
            {"as_of_date": day, "holdings": [{"ticker": KEY, "asset_type": "stock", "qty": qty}]}), encoding="utf-8")
    for i in range(10):
        d = (date(2026, 9, 1) + timedelta(days=5 * i)).isoformat()
        body = "# Отчёт\n\n" + ("Абзац разбора бумаги с цифрами. " * 700)
        fm = (f'---\ntitle: "Разбор {i}"\ndate: "{d}"\nkind: single_analysis\nmode_codes: ["4a"]\n'
              f'tickers: ["{KEY}"]\nschema_version: report@1\nrecorded_at: "{d}T12:00:00+03:00"\n'
              f'created_at: "{d}T12:00"\nsummary: "{LONG[:400]}"\n---\n\n')
        (port / "reports" / f"{d}-single-analysis-r{i}.md").write_text(fm + body, encoding="utf-8")
    for did, d in (_decision(KEY, "HOLD", "2026-09-10T12:00:00+03:00", "2026-10-20",
                             "Portfolio/reports/2026-09-10-single-analysis-x.md"),
                   _decision(KEY, "WATCH", "2026-10-05T12:00:00+03:00", None, None, resolved=["c-old"]),
                   _decision(KEY, "ADD", "2026-10-28T18:30:00+03:00", "2026-12-15",
                             "Portfolio/reports/2026-10-28-single-analysis-a.md",
                             created=["c-2026-10-28-aaaa-1"], resolved=["px-fired"]),
                   _decision("BBBB", "SELL", "2026-10-28T18:30:00+03:00", None, None)):
        (port / "decisions" / f"{did}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    defs = [_cond("c-2026-10-28-aaaa-1", KEY, "date", "2026-12-01", kind="review",
                  created_at="2026-10-28T18:30:00+03:00"),
            _cond("px-fired", KEY, "price_below", 90),
            _cond("c-old", KEY, "date", "2026-09-01"),
            _cond("bbbb-1", "BBBB", "price_above", 200)]
    (port / "conditions.yaml").write_text(yaml.safe_dump({"schema_version": "conditions@2", "conditions": defs},
                                                         allow_unicode=True, sort_keys=False), encoding="utf-8")
    state = {"schema_version": "conditions-state@1", "events": [
        {"condition_id": "px-fired", "event": "fired", "at": "2026-10-27T11:00:00+03:00", "by": "notifier", "data": {}},
        {"condition_id": "px-fired", "event": "done", "at": "2026-10-28T18:31:00+03:00", "by": "script",
         "data": {"decision_id": "2026-10-28T1830-AAAA"}},
        {"condition_id": "c-old", "event": "done", "at": "2026-10-05T12:01:00+03:00", "by": "owner", "data": {}}]}
    (port / "conditions-state.json").write_text(json.dumps(state), encoding="utf-8")
    attrs = {"schema_version": "security-attrs@1", "by_key": {
        KEY: {"ticker_class": "ipo", "listed_at": "2024-12-18", "note": "листинг на Мосбирже",
              "updated_at": "2026-10-31T12:00:00+03:00", "updated_by": "script"}}}
    (port / "security-attrs.json").write_text(json.dumps(attrs, ensure_ascii=False), encoding="utf-8")
    (port / "security-types.json").write_text(json.dumps({"schema_version": "security-types@1.0", "by_ticker": {
        KEY: {"type": "stock"}, "BBBB": {"type": "stock"}}}), encoding="utf-8")
    eps = []
    for i in range(60):
        k = KEY if i % 3 == 0 else "BBBB"
        d = (date(2026, 5, 1) + timedelta(days=3 * i)).isoformat()
        eps.append({"episode_id": f"stock:{k}:{d}:+", "class": "stock", "position": k, "position_name": k,
                    "direction": "+", "verdict": "BUY", "first_date": d, "last_date": d, "reviews": 1,
                    "concordance": "ignored" if i % 2 else "followed",
                    "owner_reason": "забыл" if i % 2 else None,
                    "outcome": {"rel_1m": 1.0, "rel_3m": -2.5, "rel_12m": None, "hit_3m": False},
                    "revised_post_hoc": False, "decision_ids": [f"weekly-review-{d}/{k}"] * 20})
    journal = {"schema": "decision-journal@1", "as_of": "2026-10-30",
               "summary": {"stock": {"episodes": 60}, "bond": {"episodes": 0}},
               "pending_questions": [{"episode_id": eps[-1]["episode_id"], "class": "stock", "position": "BBBB",
                                      "verdict": "BUY", "first_date": "2026-10-27",
                                      "question": "2026-10-27 предлагал BUY BBBB — не сделано. Сознательно?"},
                                     {"episode_id": "bond:RU000A0:2026-10-27:-", "class": "bond", "position": "RU000A0",
                                      "verdict": "SELL", "first_date": "2026-10-27", "question": "облигация?"}],
               "episodes": eps, "records": [{"pad": LONG}] * 300,
               "theses": [{"id": "t1", "opened": "2026-10-08", "check_date": "2027-10-08", "event": "USD/RUB ≥ 100",
                           "p": 0.8, "status": "open"}, {"id": "t0", "status": "closed"}]}
    (port / "decision-journal" / "journal.json").write_text(json.dumps(journal, ensure_ascii=False), encoding="utf-8")


def measure(root: str, key: str = KEY) -> int:
    """Байты/4 выдачи security_digest по бумаге — замер C5."""
    buf, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
        code = SD.main(["--root", root, "--key", key, "--today", TODAY, "--measure"])
    assert code == 0, buf.getvalue()
    return len(buf.getvalue().rstrip("\n").encode("utf-8")) // 4


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="security-digest-")
        build_fixture(cls.root)
        cls.out = SD.build(cls.root, KEY, TODAY)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)


class TestSecurityDigest(Base):
    def test_snapshot_row(self):
        s = self.out["snapshot"]
        self.assertEqual((s["file"], s["in_portfolio"]), ("portfolio-2026-10-30.json", True))
        self.assertEqual(s["holdings"][0]["listing_date"], "2024-12-18")
        self.assertEqual(s["plan"]["planned_share_pct"], 5.0)
        self.assertNotIn("user_note_ie", s["plan"])                    # длинные заметки IE — не в выборке

    def test_ie_goals_from_current_price(self):
        g = self.out["snapshot"]["ie_goals"]                           # цель 144,6 при цене снапшота 120,5 → +20 %
        self.assertEqual((g["target_12m_rub"], g["target_lt_rub"], g["price_rub"], g["price_date"]),
                         (144.6, 180.75, 120.5, "2026-10-30"))
        self.assertEqual((g["potential_12m_pct"], g["potential_lt_pct"], g["in_model"], g["model_date"]),
                         (20.0, 50.0, False, "2026-10-27"))
        self.assertNotIn("99", json.dumps(g))                          # потенциал IE на дату модели в выдачу не попадает
        b = SD.build(self.root, "BBBB", TODAY)["snapshot"]["ie_goals"]  # цели нет: цена IE 2,0 × 1,5 = 3,0; от цены 1 → +200 %
        self.assertEqual((b["target_12m_rub"], b["potential_12m_pct"], b["in_model"]), (3.0, 200.0, True))
        self.assertNotIn("target_lt_rub", b)
        c = SD.build(self.root, "CCCC", TODAY)["snapshot"]["ie_goals"]  # вне портфеля: цель есть, цены нет → потенциала нет
        self.assertEqual(c["target_12m_rub"], 13.0)
        self.assertNotIn("potential_12m_pct", c)
        self.assertIn("--quotes", c["note"])
        # живые цены quotes@1: бумага без позиции получает потенциал (13 ÷ 10,4 − 1 = +25 %), у бумаги портфеля
        # котировка заменяет цену снапшота (144,6 ÷ 131,45 − 1 = +10 %)
        q = {"schema": "quotes@1", "fetched_at": "2026-11-06T12:00:00+03:00",
             "items": {"CCCC": {"price": 10.4, "ts": "2026-11-06T11:45:00+03:00"}, KEY: {"price": 131.45}}}
        c2 = SD.build(self.root, "CCCC", TODAY, q)["snapshot"]["ie_goals"]
        self.assertEqual((c2["price_rub"], c2["price_date"], c2["price_source"], c2["potential_12m_pct"]),
                         (10.4, "2026-11-06", "котировка Мосбиржи", 25.0))
        self.assertNotIn("note", c2)
        k2 = SD.build(self.root, KEY, TODAY, q)["snapshot"]["ie_goals"]
        self.assertEqual((k2["price_rub"], k2["price_date"], k2["potential_12m_pct"]), (131.45, "2026-11-06", 10.0))
        self.assertEqual(g["price_source"], "снапшот")
        qf = Path(self.root) / "q.json"
        qf.write_text(json.dumps(q), encoding="utf-8")
        self.assertEqual(SD.load_quotes(str(qf))["schema"], "quotes@1")
        qf.write_text(json.dumps({"schema": "other"}), encoding="utf-8")
        with self.assertRaises(SD.CmdError):
            SD.load_quotes(str(qf))
        self.assertIsNone(SD.build(self.root, "ZZZZ", TODAY)["snapshot"].get("ie_goals"))   # нет в списке IE

    def test_last_three_reviews_with_recorded_at(self):
        r = self.out["reviews"]
        self.assertEqual([x["date"] for x in r], ["2026-10-26", "2026-10-19", "2026-10-12"])
        self.assertEqual(r[0]["recorded_at"], "2026-10-26T19:00:00+03:00")
        self.assertIsNone(r[2]["recorded_at"])
        self.assertLessEqual(len(r[0]["basis_first"]), 200)

    def test_decisions_latest_gate_and_conditions(self):
        d = self.out["decisions"]
        self.assertEqual((d["count"], len(d["items"])), (3, 3))
        lt = d["latest"]
        self.assertEqual((lt["id"], lt["verdict"]), ("2026-10-28T1830-AAAA", "ADD"))
        self.assertEqual(lt["gate"]["status"], "reviewed_buy_more")
        self.assertEqual(lt["gate"]["add_cooldown_until"], "2026-11-18")
        self.assertEqual(lt["conditions_created"], [{"id": "c-2026-10-28-aaaa-1", "status": "pending"}])
        self.assertEqual(lt["conditions_resolved"], [{"id": "px-fired", "status": "done"}])

    def test_active_conditions_only(self):
        c = self.out["conditions"]
        self.assertEqual([x["id"] for x in c["items"]], ["c-2026-10-28-aaaa-1"])
        self.assertFalse(c["missing"])

    def test_attrs_and_reports(self):
        self.assertEqual(self.out["attrs"]["record"]["ticker_class"], "ipo")
        reps = self.out["reports"]
        self.assertEqual(len(reps), 3)
        self.assertEqual(reps[0]["path"], "Portfolio/reports/2026-10-16-single-analysis-r9.md")
        self.assertLessEqual(len(reps[0]["head"]), 300)
        self.assertTrue(reps[0]["head"].startswith("# Отчёт"))

    def test_measure_within_c5_target(self):
        tokens = measure(self.root)
        self.assertLessEqual(tokens, TOKEN_TARGET, f"выдача по бумаге {tokens} токенов > {TOKEN_TARGET}")

    def test_bad_root_and_cli(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(SD.main(["--root", "/nonexistent-root", "--key", KEY]), 1)
        r = subprocess.run([sys.executable, str(SCRIPTS / "security_digest.py"), "--root", self.root, "--key", KEY,
                            "--today", TODAY, "--measure"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("токенов", r.stderr)
        self.assertTrue(json.loads(r.stdout)["ok"])


class TestJournalDigest(Base):
    def test_class_questions_summary_theses(self):
        out = JD.build(self.root, "stock", None, None, 10)
        self.assertEqual([q["question"] for q in out["pending_questions"]],
                         ["2026-10-27 предлагал BUY BBBB — не сделано. Сознательно?"])
        self.assertEqual(list(out["summary"]), ["stock"])
        self.assertEqual([t["id"] for t in out["theses"]], ["t1"])
        self.assertNotIn("episodes", out)

    def test_key_and_since(self):
        out = JD.build(self.root, None, KEY, None, 5)
        self.assertEqual(out["episodes_total"], 20)
        self.assertEqual(len(out["episodes"]), 5)
        self.assertTrue(all(e["episode_id"].startswith(f"stock:{KEY}:") for e in out["episodes"]))
        self.assertNotIn("decision_ids", out["episodes"][0])
        out = JD.build(self.root, None, None, "2026-10-01", 50)
        self.assertTrue(all(e["last_date"] >= "2026-10-01" for e in out["episodes"]))

    def test_small_and_missing(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(JD.main(["--root", self.root, "--key", KEY]), 0)
        self.assertLess(len(buf.getvalue().encode()) // 4, 2000)       # против ~1,5 МБ журнала целиком
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(JD.build(d, None, None, None, 10), {"ok": True, "missing": True,
                                                                  "path": "Portfolio/decision-journal/journal.json"})
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(JD.main(["--root", self.root, "--since", "02.11.2026"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=1)
