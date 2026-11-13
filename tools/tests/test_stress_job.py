#!/usr/bin/env python3
"""Стресс и сплиты на сайте (hub-notify stress_job.py): пересчёт после «Сохранить», веса по осям, сплиты.

Контракты:
  • latest_skill_stress — самый свежий Portfolio/stress/stress-ДАТА*.yaml по дате в имени; auto/ не считается;
  • recalc — отдельный процесс stress_recalc.py через runner; код 0 + write → Portfolio/stress/auto/recalc-<имя>.yaml;
    нет стресса → skipped; код ≠ 0 → error с текстом и без записи; write=False ничего не сохраняет; сбой не бросает;
  • weights_from_beliefs — через scenario_axis_weights (ρ = 0, полярность из матрицы): суммы 1, A = оба HIGH;
  • POST /api/pf/stress/weights (post_weights): чужие горизонты / вне [0,1] / нет reason при apply → 400;
    apply=false не пишет ничего; apply=true пишет файл весов (прежний уходит в weight_history) и пересчитывает;
    ошибка пересчёта после записи — 200 с recalc.state=error (веса сохранены);
  • POST /api/pf/splits (post_splits): add / dismiss, дубль → 409, невалидное → 400, первый файл создаётся;
  • сроки (scenarios/horizons.json): read_terms, post_terms (проверка без записи, запись с историей на 20, отказы);
  • макро-таблица: latest_macro, macro_state, --macro-scenarios в команде, повтор без макро при отказе;
  • refresh_if_needed (stress_replaced / macro, повторы), post_recalc (200 / 409 / 502);
  • сквозной тест с НАСТОЯЩИМ stress_recalc.py на маленькой синтетике — стык «уведомитель → скрипт».
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "tools/hosting/notify"))
sys.path.insert(0, str(REPO / "skills/portfolio-scenario-stress/tests"))
import stress_job as sj  # noqa: E402
import test_stress_recalc as tsr  # noqa: E402  (построитель синтетики)

MSK = timezone(timedelta(hours=3))
NOW = datetime(2026, 11, 5, 22, 0, tzinfo=MSK)
HE = {"h6": "2027-03-31", "h12": "2027-09-30", "h24": "2028-09-30"}
MATRIX = {"matrix": {"polarity": {"stress_pole": "A", "detente_pole": "D"},
                     "scenario_triggers": [{"scenario_id": s} for s in "ABCD"]}}
BEL = {h: {"ev_x": 0.3, "ev_y": 0.6} for h in HE}
STRESS_NAME = "stress-2026-11-04-geopol-test.yaml"


def fake_tree():
    """Выход stress_recalc.py в миниатюре: блок recalc и агрегаты."""
    pa = {b: {"expected_pl_pct_by_horizon": {h: 1.5 for h in HE}, "expected_pl_rub_by_horizon": {h: 1000 for h in HE}}
          for b in ("price", "total_return")}
    return {"portfolio_aggregates": pa,
            "recalc": {"snapshot_id": "portfolio-2026-11-05.json", "reason": "snapshot", "weights_source": "stress",
                       "needs_judgment": [{"ticker": "X"}], "dropped": []}}


class Runner:
    """Подмена subprocess.run: кладёт готовый выход в --output; запоминает команду и содержимое файла весов."""

    def __init__(self, rc=0, stderr="", tree=None, refuse_macro=None):
        self.rc, self.stderr, self.tree = rc, stderr, tree or fake_tree()
        self.refuse_macro = refuse_macro          # текст отказа скрипта, если в команде есть --macro-scenarios
        self.calls, self.weights_seen, self.macro_seen = [], [], []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if "--macro-scenarios" in cmd:
            self.macro_seen.append(cmd[cmd.index("--macro-scenarios") + 1])
            if self.refuse_macro:
                return subprocess.CompletedProcess(cmd, 1, "", self.refuse_macro)
        if "--weights-json" in cmd:
            self.weights_seen.append(json.loads(Path(cmd[cmd.index("--weights-json") + 1]).read_text(encoding="utf-8")))
        if self.rc == 0:
            Path(cmd[cmd.index("--output") + 1]).write_text(yaml.safe_dump(self.tree, allow_unicode=True), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, self.rc, "", self.stderr)


class Base(unittest.TestCase):
    def setUp(self):
        sj.clear_cache()
        sj.PREWARM = False
        sj._refresh_tried.clear()
        sj._refreshing.clear()
        sj._refresh_state.clear()
        sj._macro_errors.clear()
        self.tmp = Path(tempfile.mkdtemp())
        self.root, self.work = self.tmp / "cm", self.tmp / "work"
        self.saved = {}
        (self.root / "Portfolio/snapshots").mkdir(parents=True)
        (self.root / "Portfolio/stress/auto").mkdir(parents=True)
        (self.root / "scenarios").mkdir()
        self.snap = self.root / "Portfolio/snapshots/portfolio-2026-11-05.json"
        self.snap.write_text("{}", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def save(self, path, content):
        self.saved[path] = content

    def put_stress(self, name=STRESS_NAME, ref="scenarios/scenario-test-2026-07-01.yaml", macro=None):
        doc = {"horizon_ends": HE, "scenario_matrix_ref": ref, "primary_horizon": 12}
        if macro:
            doc["macro_input"] = macro
        (self.root / "Portfolio/stress" / name).write_text(yaml.safe_dump(doc), encoding="utf-8")

    def touch(self, path, when):
        """Время записи файла = when (datetime с поясом)."""
        ts = when.timestamp()
        os.utime(path, (ts, ts))

    def put_matrix(self, name="scenario-test-2026-07-01"):
        (self.root / "scenarios" / f"{name}.yaml").write_text(yaml.safe_dump(MATRIX), encoding="utf-8")


class Latest(Base):
    def test_latest_by_date_and_auto_ignored(self):
        self.assertIsNone(sj.latest_skill_stress(self.root))
        for n in ("stress-2026-09-18-x.yaml", "stress-2026-11-04-x.yaml", "stress-2026-10-04-x.yaml", "stress-2026-11-04-x.md"):
            (self.root / "Portfolio/stress" / n).write_text("a: 1", encoding="utf-8")
        (self.root / "Portfolio/stress/auto/stress-2026-12-01-x.yaml").write_text("a: 1", encoding="utf-8")
        self.assertEqual(sj.latest_skill_stress(self.root).name, "stress-2026-11-04-x.yaml")

    def test_matrix_name_from_path(self):
        self.assertEqual(sj.matrix_name({"scenario_matrix_ref": "scenarios/scenario-a-1.yaml"}), "scenario-a-1")
        self.assertEqual(sj.matrix_name({"scenario_matrix_ref": "scenario-a-1"}), "scenario-a-1")
        self.assertIsNone(sj.matrix_name({}))
        self.assertIsNone(sj.matrix_name({"scenario_matrix_ref": "scenarios/Bad Name.yaml"}))


class Recalc(Base):
    def go(self, runner, **kw):
        return sj.recalc(self.root, self.work, self.snap, self.save, runner, NOW, **kw)

    def test_success_saves_to_auto(self):
        self.put_stress()
        r = Runner()
        res = self.go(r)
        self.assertEqual(res["state"], "done")
        self.assertEqual(res["source_stress"], STRESS_NAME)
        self.assertEqual(res["path"], "Portfolio/stress/auto/recalc-stress-2026-11-04-geopol-test.yaml")
        self.assertEqual((res["needs_judgment"], res["dropped"], res["reason"]), (1, 0, "snapshot"))
        self.assertEqual(list(self.saved), [res["path"]])
        self.assertIn("recalc:", self.saved[res["path"]])
        self.assertNotIn("--weights-json", r.calls[0])
        self.assertEqual(r.calls[0][r.calls[0].index("--today") + 1], "2026-11-05")

    def test_existing_weights_file_is_passed(self):
        self.put_stress()
        w = self.root / "scenarios/stress-weights-scenario-test-2026-07-01.json"
        w.write_text(json.dumps({"schema": "stress-weights@1", "horizon_ends": HE}), encoding="utf-8")
        r = Runner()
        res = self.go(r)
        self.assertEqual(r.calls[0][r.calls[0].index("--weights-json") + 1], str(w))
        self.assertNotIn("weights_ignored", res)

    def test_weights_for_other_horizons_are_not_passed(self):
        # новый стресс скилла посчитан на другие сроки: веса владельца заданы на прежние — не подставляются,
        # пересчёт идёт на весах самого стресса и говорит об этом, а не падает
        self.put_stress()
        w = self.root / "scenarios/stress-weights-scenario-test-2026-07-01.json"
        other = dict(HE, **{next(iter(HE)): "2099-01-31"})
        w.write_text(json.dumps({"schema": "stress-weights@1", "horizon_ends": other}), encoding="utf-8")
        r = Runner()
        res = self.go(r)
        self.assertEqual(res["state"], "done")
        self.assertNotIn("--weights-json", r.calls[0])
        self.assertEqual(res["weights_ignored"], "horizons_changed")

    def test_unreadable_weights_file_is_not_passed(self):
        self.put_stress()
        (self.root / "scenarios/stress-weights-scenario-test-2026-07-01.json").write_text("{не json", encoding="utf-8")
        r = Runner()
        res = self.go(r)
        self.assertEqual(res["state"], "done")
        self.assertNotIn("--weights-json", r.calls[0])
        self.assertEqual(res["weights_ignored"], "unreadable")

    def test_no_stress_skipped(self):
        r = Runner()
        res = self.go(r)
        self.assertEqual(res["state"], "skipped")
        self.assertIn("нет стресс-файла", res["reason"])
        self.assertEqual((r.calls, self.saved), ([], {}))

    def test_script_refusal_is_error_and_nothing_saved(self):
        self.put_stress()
        res = self.go(Runner(rc=1, stderr="ОТКАЗ: горизонты стресса изменились: веса заданы на {…}"))
        self.assertEqual(res["state"], "error")
        self.assertIn("горизонты стресса изменились", res["error"])
        self.assertEqual(self.saved, {})

    def test_write_false_saves_nothing(self):
        self.put_stress()
        res = self.go(Runner(), write=False)
        self.assertEqual((res["state"], res["path"], self.saved), ("done", None, {}))

    def test_exceptions_do_not_propagate(self):
        self.put_stress()

        def boom(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 1)
        res = self.go(boom)
        self.assertEqual(res["state"], "error")
        self.assertIn("TimeoutExpired", res["error"])

        def bad_save(p, c):
            raise OSError("диск")
        res = sj.recalc(self.root, self.work, self.snap, bad_save, Runner(), NOW)
        self.assertEqual(res["state"], "error")
        self.assertIn("OSError", res["error"])


class Weights(Base):
    def test_from_beliefs_polarity_and_sums(self):
        w = sj.weights_from_beliefs(MATRIX, BEL)
        for row in w.values():
            self.assertAlmostEqual(sum(row.values()), 1.0, places=5)
        # ev_x — P(война), ev_y — P(жёсткие санкции); A = оба HIGH, D = оба LOW (шапка scenario_axis_weights)
        self.assertEqual(w["h6"], {"A": 0.18, "D": 0.28, "B": 0.12, "C": 0.42})
        hi = sj.weights_from_beliefs(MATRIX, {"h6": {"ev_x": 1.0, "ev_y": 1.0}})
        self.assertEqual(hi["h6"]["A"], 1.0)

    def test_matrix_without_polarity_refused(self):
        with self.assertRaises(sj.StressJobError):
            sj.weights_from_beliefs({"matrix": {}}, BEL)

    def test_check_body(self):
        ok, apply, reason = sj.check_body({"axis_beliefs": BEL, "apply": True, "reason": " новости "}, HE)
        self.assertEqual((apply, reason), (True, "новости"))
        bad = [
            {"axis_beliefs": {"h6": BEL["h6"], "h12": BEL["h12"]}},                      # не хватает горизонта
            {"axis_beliefs": {**BEL, "h36": BEL["h6"]}},                                 # лишний
            {"axis_beliefs": {**BEL, "h6": {"ev_x": 1.2, "ev_y": 0.5}}},                 # вне [0, 1]
            {"axis_beliefs": {**BEL, "h6": {"ev_x": True, "ev_y": 0.5}}},                # bool
            {"axis_beliefs": {**BEL, "h6": {"ev_x": 0.5}}},                              # нет ev_y
            {"axis_beliefs": BEL, "apply": True},                                        # нет reason
            {"axis_beliefs": BEL, "apply": True, "reason": "  "},
            {"axis_beliefs": BEL, "apply": True, "reason": "я" * 301},
            {"axis_beliefs": BEL, "apply": "yes"},
        ]
        for b in bad:
            with self.assertRaises(sj.StressJobError, msg=str(b)) as cm:
                sj.check_body(b, HE)
            self.assertEqual(cm.exception.code, 400)
        sj.check_body({"axis_beliefs": BEL}, HE)    # apply=false: reason не нужен

    def post(self, body, runner=None):
        return sj.post_weights(self.root, self.work, body, self.save, runner or Runner(), NOW)

    def ready(self):
        self.put_stress()
        self.put_matrix()

    def test_http_400_cases(self):
        self.ready()
        code, j = self.post({"axis_beliefs": {"h6": BEL["h6"]}})
        self.assertEqual(code, 400)
        self.assertIn("горизонты", j["error"])
        code, j = self.post({"axis_beliefs": BEL, "apply": True})
        self.assertEqual(code, 400)
        self.assertIn("reason", j["error"])
        self.assertEqual(self.saved, {})

    def test_no_stress_409(self):
        self.assertEqual(self.post({"axis_beliefs": BEL})[0], 409)

    def test_what_if_writes_nothing(self):
        self.ready()
        r = Runner()
        code, j = self.post({"axis_beliefs": BEL, "apply": False}, r)
        self.assertEqual(code, 200)
        self.assertEqual(self.saved, {})
        self.assertNotIn("saved", j)
        self.assertEqual(j["weights"]["h12"]["C"], 0.42)
        self.assertEqual(r.weights_seen[0]["weights"], j["weights"])           # пересчёт шёл на временных весах
        h6 = j["summary"]["horizons"]["h6"]
        self.assertEqual(h6["modal"], {"scenario": "C", "weight": 0.42})
        self.assertEqual(h6["price"], {"expected_pl_pct": 1.5, "expected_pl_rub": 1000})
        self.assertEqual(j["summary"]["needs_judgment"], 1)
        self.assertEqual(list(self.work.glob("stress-weights-*")), [])          # временный файл убран

    def test_apply_writes_weights_with_history_and_recalcs(self):
        self.ready()
        r = Runner()
        code, j = self.post({"axis_beliefs": BEL, "apply": True, "reason": "первое"}, r)
        wpath = "scenarios/stress-weights-scenario-test-2026-07-01.json"
        recalc_path = "Portfolio/stress/auto/recalc-stress-2026-11-04-geopol-test.yaml"
        self.assertEqual(code, 200)
        self.assertEqual(j["saved"], [wpath, recalc_path])
        doc = json.loads(self.saved[wpath])
        self.assertEqual((doc["schema"], doc["matrix"], doc["horizon_ends"]), ("stress-weights@1", "scenario-test-2026-07-01", HE))
        self.assertEqual((doc["reason"], doc["weight_history"], doc["set_at"]), ("первое", [], "2026-11-05T22:00:00+03:00"))
        self.assertEqual(doc["axis_beliefs"], BEL)
        self.assertEqual(j["recalc"]["state"], "done")
        # второй apply: прежняя запись уходит в weight_history
        (self.root / wpath).write_text(self.saved[wpath], encoding="utf-8")
        new = {h: {"ev_x": 0.5, "ev_y": 0.5} for h in HE}
        code, j = self.post({"axis_beliefs": new, "apply": True, "reason": "второе"}, r)
        doc2 = json.loads(self.saved[wpath])
        self.assertEqual(len(doc2["weight_history"]), 1)
        self.assertEqual((doc2["weight_history"][0]["reason"], doc2["weight_history"][0]["axis_beliefs"]), ("первое", BEL))
        self.assertEqual(doc2["weights"]["h6"], {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25})

    def test_recalc_failure_after_apply_keeps_weights(self):
        self.ready()
        code, j = self.post({"axis_beliefs": BEL, "apply": True, "reason": "r"}, Runner(rc=1, stderr="ОТКАЗ: сценарии не совпадают"))
        self.assertEqual(code, 200)
        self.assertEqual(j["recalc"]["state"], "error")
        self.assertIn("не совпадают", j["recalc"]["error"])
        self.assertEqual(j["saved"], ["scenarios/stress-weights-scenario-test-2026-07-01.json"])
        self.assertIn("веса сохранены", j["note"])

    def test_what_if_recalc_failure_is_502_and_writes_nothing(self):
        self.ready()
        code, j = self.post({"axis_beliefs": BEL}, Runner(rc=1, stderr="ОТКАЗ"))
        self.assertEqual((code, self.saved), (502, {}))

    def test_get_weights_and_horizons_changed(self):
        self.ready()
        code, j = sj.get_weights(self.root)
        self.assertEqual((code, j["weights"], j["horizons_changed"], j["horizon_ends"]), (200, None, False, HE))
        w = {"schema": "stress-weights@1", "horizon_ends": HE, "weights": {}}
        p = self.root / "scenarios/stress-weights-scenario-test-2026-07-01.json"
        p.write_text(json.dumps(w), encoding="utf-8")
        self.assertFalse(sj.get_weights(self.root)[1]["horizons_changed"])
        p.write_text(json.dumps({**w, "horizon_ends": {**HE, "h6": "2027-04-30"}}), encoding="utf-8")
        self.assertTrue(sj.get_weights(self.root)[1]["horizons_changed"])
        self.assertEqual(sj.get_weights(self.tmp / "пусто")[1]["weights"], None)

    def test_get_weights_axes_and_scenario_names(self):
        """Ответ несёт полюса осей из polarity матрицы и названия сценариев из стресс-файла."""
        self.ready()
        stress = self.root / "Portfolio/stress" / STRESS_NAME
        doc = yaml.safe_load(stress.read_text(encoding="utf-8"))
        doc["scenarios"] = {"A": {"name": "Эскалация"}, "B": {"label": "Война без санкций"}, "C": {"name": " "}}
        stress.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
        j = sj.get_weights(self.root)[1]
        self.assertEqual(j["axes"]["x"], {"high": ["A", "B"], "low": ["C", "D"]})
        self.assertEqual(j["axes"]["y"], {"high": ["A", "C"], "low": ["B", "D"]})
        self.assertEqual(j["scenario_names"], {"A": "Эскалация", "B": "Война без санкций"})
        self.assertIs(type(j["yaml_c"]), bool)      # диагностика выкладки: есть ли в контейнере быстрый разбор YAML
        (self.root / "scenarios/scenario-test-2026-07-01.yaml").unlink()          # матрицы нет — осей нет, ответ цел
        j = sj.get_weights(self.root)[1]
        self.assertIsNone(j["axes"])
        self.assertEqual(j["horizon_ends"], HE)


class Splits(Base):
    BODY = {"action": "add", "ticker": "ZZZ", "date": "2026-10-01", "ratio": 10}

    def post(self, body):
        return sj.post_splits(self.root, body, self.save, NOW)

    def test_add_creates_first_file(self):
        code, j = self.post(self.BODY)
        self.assertEqual((code, j), (200, {"saved": "Portfolio/known-splits.json", "splits": 1, "dismissed": 0}))
        doc = json.loads(self.saved["Portfolio/known-splits.json"])
        e = doc["splits"][0]
        self.assertEqual((doc["schema"], e["ticker"], e["ratio"], e["added_by"], e["added_at"]),
                         ("known-splits@1", "ZZZ", 10.0, "site", "2026-11-05T22:00:00+03:00"))

    def test_duplicate_409_and_invalid_400(self):
        self.post(self.BODY)
        (self.root / "Portfolio/known-splits.json").write_text(self.saved["Portfolio/known-splits.json"], encoding="utf-8")
        self.saved.clear()
        code, j = self.post(self.BODY)
        self.assertEqual(code, 409)
        self.assertIn("уже есть", j["error"])
        self.assertEqual(self.post({**self.BODY, "ticker": "T", "date": "2026-04-17"})[0], 409)    # встроенный набор
        self.assertEqual(self.post({**self.BODY, "ratio": 1})[0], 400)
        self.assertEqual(self.post({**self.BODY, "date": "01.10.2026"})[0], 400)
        self.assertEqual(self.post({"action": "x"})[0], 400)
        self.assertEqual(self.saved, {})

    def test_dismiss(self):
        code, j = self.post({**self.BODY, "action": "dismiss", "note": "не сплит"})
        self.assertEqual((code, j["splits"], j["dismissed"]), (200, 0, 1))
        d = json.loads(self.saved["Portfolio/known-splits.json"])["dismissed"][0]
        self.assertEqual((d["ticker"], d["note"], d["dismissed_at"]), ("ZZZ", "не сплит", "2026-11-05T22:00:00+03:00"))
        (self.root / "Portfolio/known-splits.json").write_text(self.saved["Portfolio/known-splits.json"], encoding="utf-8")
        self.assertEqual(self.post({**self.BODY, "action": "dismiss"})[0], 409)

    def test_read_fn_is_authoritative(self):
        doc = {"schema": "known-splits@1", "splits": [], "dismissed": []}
        code, j = sj.post_splits(self.root, self.BODY, self.save, NOW, read_fn=lambda p: (json.dumps(doc), "h"))
        self.assertEqual(code, 200)
        code, _ = sj.post_splits(self.root, self.BODY, self.save, NOW, read_fn=lambda p: (self.saved[p], "h"))
        self.assertEqual(code, 409)


class Cache(Base):
    """Кэш разобранных файлов: ключ (путь, mtime_ns, размер)."""

    def counted(self):
        calls = []
        orig = sj._parse_yaml

        def counting(text):
            calls.append(1)
            return orig(text)
        sj._parse_yaml = counting
        self.addCleanup(setattr, sj, "_parse_yaml", orig)
        return calls

    def test_second_load_does_not_parse(self):
        self.put_stress()
        calls = self.counted()
        p = self.root / "Portfolio/stress" / STRESS_NAME
        a = sj.cached_load(p)
        b = sj.cached_load(p)
        self.assertEqual((len(calls), a is b), (1, True))
        sj.get_weights(self.root)
        sj.get_weights(self.root)
        self.assertEqual(len(calls), 1)             # стресс не разбирался заново (матрицы нет — не в счёт)

    def test_change_invalidates(self):
        self.put_stress()
        calls = self.counted()
        p = self.root / "Portfolio/stress" / STRESS_NAME
        self.assertEqual(sj.cached_load(p)["horizon_ends"], HE)
        p.write_text(yaml.safe_dump({"horizon_ends": {"h3": "2027-01-01"}}), encoding="utf-8")
        self.assertEqual(sj.cached_load(p)["horizon_ends"], {"h3": "2027-01-01"})
        self.assertEqual(len(calls), 2)

    def test_eviction_is_bounded(self):
        calls = self.counted()
        paths = []
        for i in range(sj.CACHE_MAX + 2):
            q = self.tmp / f"f{i}.yaml"
            q.write_text(f"a: {i}\n", encoding="utf-8")
            paths.append(q)
            sj.cached_load(q)
        self.assertLessEqual(len(sj._CACHE), sj.CACHE_MAX)
        n = len(calls)
        sj.cached_load(paths[-1])                  # свежий — из кэша
        self.assertEqual(len(calls), n)
        sj.cached_load(paths[0])                   # вытесненный — разбор заново
        self.assertEqual(len(calls), n + 1)

    def test_json_kind_cached_separately(self):
        q = self.tmp / "w.json"
        q.write_text('{"a": 1}', encoding="utf-8")
        self.assertEqual(sj.cached_load(q, "json"), {"a": 1})
        self.assertIs(sj.cached_load(q, "json"), sj.cached_load(q, "json"))

    def test_c_loader_gives_same_tree_as_pure_python(self):
        text = yaml.safe_dump({"s": {"A": {"name": "Эскалация", "p": 0.25, "d": [1, 2.5, None, True], "t": "2026-11-05"}},
                               "x": "ё: \"кавычки\"", "he": HE}, allow_unicode=True)
        text += "z: 2026-11-04\nq: 1e3\n"
        self.assertEqual(sj._parse_yaml(text), yaml.load(text, Loader=yaml.SafeLoader))
        if not hasattr(yaml, "CSafeLoader"):
            self.skipTest("нет libyaml: загрузчик и так чистый Python")

    def test_warm_after_recalc_avoids_parse(self):
        self.put_stress()
        r = Runner()
        res = sj.recalc(self.root, self.work, self.snap, self.save, r, NOW)
        dest = self.root / res["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(self.saved[res["path"]], encoding="utf-8")       # как сделал бы hub-api: тот же текст, позже
        calls = self.counted()
        tree = sj.cached_load(dest)
        self.assertEqual((len(calls), tree["recalc"]["snapshot_id"]), (0, "portfolio-2026-11-05.json"))
        dest.write_text(self.saved[res["path"]] + "extra: 1\n", encoding="utf-8")   # другой размер — прогрев не применим
        self.assertEqual(sj.cached_load(dest)["extra"], 1)
        self.assertEqual(len(calls), 1)


class DumpEq(Base):
    def test_c_dumper_tree_equals_pure_python(self):
        sys.path.insert(0, str(REPO / "skills/portfolio-scenario-stress/scripts"))
        import stress_recalc as srx
        stress = tsr.build_skill_stress(self.tmp, tsr.snapshot())
        tree = yaml.safe_load(stress.read_text(encoding="utf-8"))
        pure = yaml.safe_dump(tree, allow_unicode=True, sort_keys=False, default_flow_style=False)
        fast = srx._dump_yaml(tree)
        self.assertEqual(yaml.load(fast, Loader=yaml.SafeLoader), yaml.load(pure, Loader=yaml.SafeLoader))
        self.assertEqual(sj._parse_yaml(fast), tree)
        self.assertEqual(list(yaml.safe_load(fast)), list(tree))        # порядок ключей сохранён
        self.assertEqual(fast, srx._dump_yaml(tree))                    # детерминизм


class WhatIf(Base):
    """Быстрое «а что если»: без runner и записи; числа равны полному пересчёту (та же формула, cpa.expected_pl)."""

    W1 = {"h6": {"A": 0.9, "B": 0.1}, "h12": {"A": 0.35, "B": 0.65}}
    W2 = {"h6": {"A": 0.2, "B": 0.8}, "h12": {"A": 0.5, "B": 0.5}}

    def setUp(self):
        super().setUp()
        snap0 = tsr.snapshot()
        stress = tsr.build_skill_stress(self.tmp, snap0)
        self.sdoc = yaml.safe_load(stress.read_text(encoding="utf-8"))
        self.sdoc["scenario_matrix_ref"] = "scenarios/scenario-test-2026-07-01.yaml"
        self.name = f"stress-{self.sdoc['date']}-t.yaml"
        (self.root / "Portfolio/stress" / self.name).write_text(yaml.safe_dump(self.sdoc, allow_unicode=True), encoding="utf-8")
        self.put_matrix()
        # стресс записан до времени пересчёта (NOW): иначе пересчёт сайта считался бы от прежней версии
        self.touch(self.root / "Portfolio/stress" / self.name, NOW - timedelta(days=1))
        self.snap0 = snap0
        self.snap.write_text(json.dumps(snap0), encoding="utf-8")
        self.cur = self.W1
        orig = sj.weights_from_beliefs
        sj.weights_from_beliefs = lambda m, b: {h: dict(r) for h, r in self.cur.items()}
        self.addCleanup(setattr, sj, "weights_from_beliefs", orig)
        self.beliefs = {h: {"ev_x": 0.5, "ev_y": 0.5} for h in self.sdoc["horizon_ends"]}

    def post(self, apply, runner, weights):
        self.cur = weights
        body = {"axis_beliefs": self.beliefs, "apply": apply}
        if apply:
            body["reason"] = "тест"
        return sj.post_weights(self.root, self.work, body, self.save, runner, NOW)

    def put_recalc(self, text):
        d = self.root / sj.STRESS_AUTO_DIR / f"recalc-{Path(self.name).stem}.yaml"
        d.write_text(text, encoding="utf-8")

    def test_fast_path_equals_full_recalc_on_stress_source(self):
        # числа берутся из стресса скилла; снапшот тот же, на котором он посчитан → равны полному пересчёту
        class NoRun:
            calls = 0

            def __call__(self, *a, **k):
                NoRun.calls += 1
                raise AssertionError("runner не должен вызываться")
        for W in (self.W1, self.W2):
            code, fast = self.post(False, NoRun(), W)
            self.assertEqual((code, NoRun.calls, self.saved), (200, 0, {}), fast)
            self.assertEqual(fast["summary"]["snapshot_id"], self.sdoc["portfolio_snapshot_id"])
            code, full = self.post(True, subprocess.run, W)
            self.assertEqual(code, 200, full)
            for h in W:
                self.assertEqual(fast["summary"]["horizons"][h]["modal"], full["summary"]["horizons"][h]["modal"])
                for b in ("price", "total_return"):
                    self.assertIsNotNone(full["summary"]["horizons"][h][b]["expected_pl_rub"])
                    self.assertEqual(fast["summary"]["horizons"][h][b], full["summary"]["horizons"][h][b], (W, h, b))
            self.saved.clear()

    def test_source_is_recalc_file_for_fresh_snapshot_else_stress(self):
        snap1 = tsr.snapshot(qty1=700000.0, as_of="2026-11-05")
        self.snap.write_text(json.dumps(snap1), encoding="utf-8")
        # файла пересчёта нет → числа стресса скилла, snapshot_id — его собственный
        code, j = self.post(False, Runner(), self.W1)
        self.assertEqual(j["summary"]["snapshot_id"], self.sdoc["portfolio_snapshot_id"])
        # полный пересчёт на свежем снапшоте → файл пересчёта; быстрый путь берёт его и равен новому полному
        code, full = self.post(True, subprocess.run, self.W1)
        self.assertEqual(full["recalc"]["state"], "done", full)
        self.put_recalc(self.saved[full["recalc"]["path"]])
        r = Runner()
        code, fast = self.post(False, r, self.W2)
        self.assertEqual((code, r.calls, fast["summary"]["snapshot_id"]), (200, [], "portfolio-2026-11-05.json"))
        code, full2 = self.post(True, subprocess.run, self.W2)
        for h in self.W2:
            for b in ("price", "total_return"):
                self.assertEqual(fast["summary"]["horizons"][h][b], full2["summary"]["horizons"][h][b], (h, b))
        # файл пересчёта на другом снапшоте → снова стресс скилла
        stale = yaml.safe_load(self.saved[full["recalc"]["path"]])
        stale["recalc"]["snapshot_id"] = "portfolio-2026-10-01.json"
        self.put_recalc(yaml.safe_dump(stale, allow_unicode=True))
        code, j = self.post(False, Runner(), self.W1)
        self.assertEqual(j["summary"]["snapshot_id"], self.sdoc["portfolio_snapshot_id"])

    def test_fallback_to_full_when_scenarios_differ(self):
        r = Runner()
        code, j = self.post(False, r, {"h6": {"A": 0.5, "B": 0.3, "C": 0.2}, "h12": {"A": 0.5, "B": 0.3, "C": 0.2}})
        self.assertEqual(len(r.calls), 1)          # быстрый путь неприменим → прежний полный пересчёт

    def test_stale_recalc_file_is_not_a_source(self):
        # пересчёт на том же снапшоте, но стресс записан позже пересчёта → числа берутся из стресса скилла
        snap1 = tsr.snapshot(qty1=700000.0, as_of="2026-11-05")
        self.snap.write_text(json.dumps(snap1), encoding="utf-8")
        code, full = self.post(True, subprocess.run, self.W1)
        self.put_recalc(self.saved[full["recalc"]["path"]])
        r = Runner()
        code, fresh = self.post(False, r, self.W2)
        self.assertEqual(fresh["summary"]["snapshot_id"], "portfolio-2026-11-05.json")
        self.touch(self.root / "Portfolio/stress" / self.name, NOW + timedelta(hours=1))
        sj.clear_cache()
        code, j = self.post(False, r, self.W2)
        self.assertEqual((code, r.calls), (200, []))
        self.assertEqual(j["summary"]["snapshot_id"], self.sdoc["portfolio_snapshot_id"])


class Freshness(Base):
    """Выбор последнего стресса по времени записи и устаревший пересчёт сайта."""

    def stress(self, name, when=None):
        p = self.root / "Portfolio/stress" / name
        p.write_text("a: 1", encoding="utf-8")
        if when is not None:
            self.touch(p, when)
        return p

    def test_same_date_later_written_wins_any_name(self):
        a = self.stress("stress-2026-11-04-b.yaml", NOW - timedelta(hours=2))
        b = self.stress("stress-2026-11-04-a.yaml", NOW)             # имя «меньше», но записан позже
        self.assertEqual(sj.latest_skill_stress(self.root), b)
        self.touch(a, NOW + timedelta(hours=1))
        self.assertEqual(sj.latest_skill_stress(self.root), a)

    def test_same_mtime_falls_back_to_name(self):
        self.stress("stress-2026-11-04-a.yaml", NOW)
        b = self.stress("stress-2026-11-04-b.yaml", NOW)
        self.assertEqual(sj.latest_skill_stress(self.root), b)

    def test_old_date_with_later_mtime_does_not_win(self):
        self.stress("stress-2026-10-01-x.yaml", NOW + timedelta(days=5))
        new = self.stress("stress-2026-11-04-x.yaml", NOW - timedelta(days=5))
        self.assertEqual(sj.latest_skill_stress(self.root), new)

    def test_recalc_is_stale(self):
        p = self.stress(STRESS_NAME, NOW)                            # запись ровно в NOW
        f = lambda at: sj.recalc_is_stale(p, {"at": at})
        self.assertTrue(f((NOW - timedelta(minutes=5)).isoformat()))
        self.assertFalse(f((NOW + timedelta(minutes=5)).isoformat()))
        self.assertFalse(f(NOW.isoformat()))                         # та же секунда
        self.assertFalse(sj.recalc_is_stale(p, {}))
        self.assertFalse(sj.recalc_is_stale(p, {"at": "мусор"}))
        self.assertFalse(sj.recalc_is_stale(p, None))
        # без пояса — московское: 21:00 без пояса = 21:00 МСК < 22:00 МСК; а как UTC было бы позже записи
        self.assertTrue(f("2026-11-05T21:00:00"))
        self.assertFalse(f("2026-11-05T22:30:00"))
        self.assertTrue(f("2026-11-05T20:00:00"))

    def put_recalc_at(self, at):
        d = self.root / sj.STRESS_AUTO_DIR / f"recalc-{Path(STRESS_NAME).stem}.yaml"
        d.write_text(f"recalc:\n  snapshot_id: portfolio-2026-11-05.json\n  at: '{at}'\n", encoding="utf-8")

    def test_stale_recalc(self):
        p = self.stress(STRESS_NAME, NOW)
        self.assertFalse(sj.stale_recalc(self.root, p))              # файла пересчёта нет
        self.put_recalc_at((NOW + timedelta(hours=1)).isoformat())
        self.assertFalse(sj.stale_recalc(self.root, p))
        self.put_recalc_at((NOW - timedelta(hours=1)).isoformat())
        self.assertTrue(sj.stale_recalc(self.root, p))

    def ready_stale(self):
        self.put_stress()
        self.put_matrix()
        p = self.root / "Portfolio/stress" / STRESS_NAME
        self.touch(p, NOW)
        self.put_recalc_at((NOW - timedelta(hours=1)).isoformat())
        return p

    def test_get_weights_flags_and_no_refresh_without_arg(self):
        self.ready_stale()
        r = Runner()
        j = sj.get_weights(self.root)[1]
        self.assertEqual((j["recalc_stale"], j["recalc_refreshing"], r.calls, self.saved), (True, False, [], {}))
        self.put_recalc_at((NOW + timedelta(hours=1)).isoformat())
        j = sj.get_weights(self.root)[1]
        self.assertEqual((j["recalc_stale"], j["recalc_refreshing"]), (False, False))

    def test_refresh_stale_runs_once_per_stress_version(self):
        self.ready_stale()
        r = Runner()
        self.assertTrue(sj.refresh_stale(self.root, self.work, self.save, r, wait=True))
        self.assertEqual(len(r.calls), 1)
        self.assertEqual(list(self.saved), ["Portfolio/stress/auto/recalc-stress-2026-11-04-geopol-test.yaml"])
        # повтор для той же версии стресса в пределах REFRESH_RETRY_S не запускает пересчёт (файл на диске всё ещё старый)
        self.assertFalse(sj.refresh_stale(self.root, self.work, self.save, r, wait=True))
        self.assertEqual(len(r.calls), 1)

    def test_refresh_stale_fresh_recalc_does_nothing(self):
        self.ready_stale()
        self.put_recalc_at((NOW + timedelta(hours=1)).isoformat())
        r = Runner()
        self.assertFalse(sj.refresh_stale(self.root, self.work, self.save, r, wait=True))
        self.assertEqual((r.calls, self.saved), ([], {}))

    def test_get_weights_with_refresh_starts_recalc(self):
        self.ready_stale()
        r = Runner()
        j = sj.get_weights(self.root, refresh=(self.work, self.save, r))[1]
        self.assertTrue(j["recalc_stale"])
        self.assertTrue(j["recalc_refreshing"])
        for _ in range(100):                                          # фоновый поток
            if not sj._refreshing:
                break
            time.sleep(0.05)
        self.assertEqual(len(r.calls), 1)


TERMS = {"horizon_ends": {"h6": "2027-05-06", "h12": "2027-11-06", "h24": "2028-11-06"}, "primary_horizon": 12}


class Terms(Base):
    """Файл сроков scenarios/horizons.json (horizons@1): чтение, проверка и запись с сайта."""

    def put_terms(self, text=None, **over):
        doc = {"schema": "horizons@1", **TERMS, "set_at": "2026-11-01T10:00:00+03:00", "reason": "было", "history": []}
        doc.update(over)
        (self.root / "scenarios/horizons.json").write_text(text if text is not None else json.dumps(doc), encoding="utf-8")

    def post(self, body):
        return sj.post_terms(self.root, body, self.save, NOW)

    def test_read_terms_valid_missing_and_invalid(self):
        self.assertEqual(sj.read_terms(self.root), (None, None))
        self.put_terms()
        doc, warn = sj.read_terms(self.root)
        self.assertEqual((doc["horizon_ends"], doc["primary_horizon"], warn), (TERMS["horizon_ends"], 12, None))
        bad = [
            "{не json",
            json.dumps({**TERMS}),                                                         # нет schema
            json.dumps({"schema": "horizons@2", **TERMS}),
            json.dumps({"schema": "horizons@1", "horizon_ends": {}, "primary_horizon": 12}),
            json.dumps({"schema": "horizons@1", "horizon_ends": {"six": "2027-05-06"}, "primary_horizon": 6}),
            json.dumps({"schema": "horizons@1", "horizon_ends": {"h6": "06.05.2027"}, "primary_horizon": 6}),
            json.dumps({"schema": "horizons@1", "horizon_ends": {"h6": "2027-02-30"}, "primary_horizon": 6}),
            json.dumps({"schema": "horizons@1", "horizon_ends": {"h6": "2027-05-06", "h12": "2027-05-06"}, "primary_horizon": 12}),
            json.dumps({"schema": "horizons@1", "horizon_ends": {"h6": "2027-05-06", "h12": "2027-01-01"}, "primary_horizon": 12}),
            json.dumps({"schema": "horizons@1", "horizon_ends": {"h6": "2027-05-06"}, "primary_horizon": 12}),
            json.dumps({"schema": "horizons@1", "horizon_ends": {"h6": "2027-05-06"}, "primary_horizon": True}),
            json.dumps({"schema": "horizons@1", "horizon_ends": {f"h{i}": f"2027-0{i}-01" for i in range(1, 8)}, "primary_horizon": 1}),
        ]
        for t in bad:
            sj.clear_cache()
            self.put_terms(t)
            doc, warn = sj.read_terms(self.root)       # невалидный файл = файла нет + предупреждение, без падения
            self.assertIsNone(doc, t)
            self.assertTrue(warn, t)

    def test_check_does_not_write(self):
        code, j = self.post({**TERMS, "confirm": False})
        self.assertEqual(code, 200)
        c = j["check"]
        self.assertEqual((c["ok"], c["horizon_ends"], c["primary_horizon"], c["same_as_current"]),
                         (True, TERMS["horizon_ends"], 12, False))
        self.assertEqual(c["months"], {"h6": 6.0, "h12": 12.0, "h24": 24.0})
        self.assertEqual(self.saved, {})

    def test_same_as_current_by_file_and_by_stress(self):
        self.put_stress()
        he = dict(HE)
        code, j = self.post({"horizon_ends": he, "primary_horizon": 12, "confirm": False})
        self.assertTrue(j["check"]["same_as_current"])                 # файла нет — сравнение со сроками стресса
        self.put_terms()
        code, j = self.post({"horizon_ends": he, "primary_horizon": 12, "confirm": False})
        self.assertFalse(j["check"]["same_as_current"])                # файл есть — сравнение с ним
        code, j = self.post({**TERMS, "primary_horizon": 6, "confirm": False})
        self.assertTrue(j["check"]["same_as_current"])                 # основной срок в сравнение не входит

    def test_refusals_400_with_clear_text(self):
        cases = [
            ({"horizon_ends": {"h6": "2027-05-06"}, "primary_horizon": 12}, "primary_horizon"),
            ({"horizon_ends": {"h6": "2026-11-05"}, "primary_horizon": 6}, "не позже сегодняшней"),
            ({"horizon_ends": {"h6": "2026-11-01"}, "primary_horizon": 6}, "h6"),
            ({"horizon_ends": {"h6": "2027-13-01"}, "primary_horizon": 6}, "h6"),
            ({"horizon_ends": {"h6": "2027-05-06", "h12": "2027-05-06"}, "primary_horizon": 6}, "должен быть позже"),
            ({"horizon_ends": {"x": "2027-05-06"}, "primary_horizon": 6}, "метка"),
            ({"horizon_ends": "нет", "primary_horizon": 6}, "horizon_ends"),
            ({**TERMS, "confirm": "да"}, "confirm"),
        ]
        for body, txt in cases:
            code, j = self.post(body)
            self.assertEqual(code, 400, body)
            self.assertIn(txt, j["error"], body)
        self.assertEqual(self.post([])[0], 400)
        self.assertEqual(self.saved, {})

    def test_confirm_needs_reason(self):
        for reason in (None, "  ", "я" * 301, 5):
            code, j = self.post({**TERMS, "confirm": True, "reason": reason})
            self.assertEqual(code, 400, reason)
        self.assertEqual(self.saved, {})

    def test_confirm_writes_file_and_history(self):
        code, j = self.post({"horizon_ends": {"h24": "2028-11-06", "h6": "2027-05-06", "h12": "2027-11-06"},
                             "primary_horizon": 12, "reason": " новый цикл ", "confirm": True})
        self.assertEqual((code, j["saved"]), (200, ["scenarios/horizons.json"]))
        doc = json.loads(self.saved["scenarios/horizons.json"])
        self.assertEqual(j["terms"], doc)
        self.assertEqual((doc["schema"], doc["reason"], doc["set_at"], doc["history"]),
                         ("horizons@1", "новый цикл", "2026-11-05T22:00:00+03:00", []))
        self.assertEqual(list(doc["horizon_ends"]), ["h6", "h12", "h24"])         # порядок по N
        self.assertEqual(list(self.saved), ["scenarios/horizons.json"])            # ни весов, ни стресса, ни пересчёта
        # второй раз: прежнее состояние уходит в history
        (self.root / "scenarios/horizons.json").write_text(self.saved["scenarios/horizons.json"], encoding="utf-8")
        code, j = self.post({"horizon_ends": {"h6": "2027-06-30"}, "primary_horizon": 6, "reason": "сдвиг", "confirm": True})
        doc2 = json.loads(self.saved["scenarios/horizons.json"])
        self.assertEqual(len(doc2["history"]), 1)
        self.assertEqual(doc2["history"][0], {"set_at": doc["set_at"], "horizon_ends": doc["horizon_ends"],
                                              "primary_horizon": 12, "reason": "новый цикл"})

    def test_history_keeps_last_20(self):
        hist = [{"set_at": f"2026-01-{i:02d}T10:00:00+03:00", "horizon_ends": {"h6": "2027-05-06"},
                 "primary_horizon": 6, "reason": str(i)} for i in range(1, 21)]
        self.put_terms(history=hist)
        self.post({**TERMS, "reason": "ещё", "confirm": True})
        doc = json.loads(self.saved["scenarios/horizons.json"])
        self.assertEqual((len(doc["history"]), doc["history"][0]["reason"], doc["history"][-1]["reason"]), (20, "2", "было"))

    def test_invalid_old_file_is_not_put_to_history(self):
        self.put_terms("{не json")
        self.post({**TERMS, "reason": "первый", "confirm": True})
        self.assertEqual(json.loads(self.saved["scenarios/horizons.json"])["history"], [])

    def test_get_weights_terms_block(self):
        self.put_stress()
        self.put_matrix()
        j = sj.get_weights(self.root)[1]
        self.assertEqual(j["terms"], {"horizon_ends": HE, "primary_horizon": 12, "set_at": None, "reason": None, "source": "stress"})
        self.assertEqual((j["terms_mismatch"], j["terms_history"]), (False, []))
        self.put_terms(history=[{"reason": "ранее"}])
        j = sj.get_weights(self.root)[1]
        self.assertEqual(j["terms"], {"horizon_ends": TERMS["horizon_ends"], "primary_horizon": 12,
                                      "set_at": "2026-11-01T10:00:00+03:00", "reason": "было", "source": "site"})
        self.assertTrue(j["terms_mismatch"])
        self.assertEqual(j["terms_history"], [{"reason": "ранее"}])
        self.put_terms(horizon_ends=HE)
        sj.clear_cache()
        self.assertFalse(sj.get_weights(self.root)[1]["terms_mismatch"])
        self.put_terms("{не json")
        sj.clear_cache()
        j = sj.get_weights(self.root)[1]
        self.assertEqual((j["terms"]["source"], j["terms_mismatch"]), ("stress", False))


class Macro(Base):
    """Подхват новой макро-таблицы: macro_state, _run с --macro-scenarios, повтор без неё при отказе."""

    def put_macro(self, name, matrix="scenario-test-2026-07-01", when=None):
        d = self.root / "macro-chain"
        d.mkdir(exist_ok=True)
        p = d / name
        p.write_text(f"scenario_matrix:\n  type: scenario_matrix\n  source_file: scenarios/{matrix}.yaml\n  x: 1\n", encoding="utf-8")
        # по умолчанию макро-файл записан раньше стресса (NOW − 1 день): «новее» он только по дате в имени;
        # перезапись под прежним именем после расчёта чисел задаётся явным when
        self.touch(p, when if when is not None else NOW - timedelta(days=2))
        return p

    def ready(self, used="macro-scenarios-2026-11-04.yaml"):
        sj.clear_cache()
        self.put_stress(macro=used)
        self.put_matrix()
        self.touch(self.root / "Portfolio/stress" / STRESS_NAME, NOW - timedelta(days=1))

    def state(self):
        return sj.macro_state(self.root, sj.latest_skill_stress(self.root))

    def test_latest_macro_by_date_then_mtime_then_name(self):
        self.assertIsNone(sj.latest_macro(self.root))
        self.put_macro("macro-scenarios-2026-11-04.yaml", when=NOW + timedelta(days=9))
        b = self.put_macro("macro-scenarios-2026-11-06.yaml", when=NOW - timedelta(days=9))
        self.assertEqual(sj.latest_macro(self.root), b)                       # дата первее времени записи
        c = self.put_macro("macro-scenarios-2026-11-06-b.yaml", when=NOW)
        self.assertEqual(sj.latest_macro(self.root), c)                       # одна дата — позже записанный
        (self.root / "macro-chain/macro-scenarios-2026-12-01.md").write_text("x", encoding="utf-8")
        self.assertEqual(sj.latest_macro(self.root), c)

    def test_state_newer_same_older_and_none(self):
        self.ready()
        self.assertEqual(self.state(), {"used": "macro-scenarios-2026-11-04.yaml", "latest": None, "newer": False, "blocked": None,
                                        "apply": False})
        self.put_macro("macro-scenarios-2026-11-04.yaml")
        self.assertFalse(self.state()["newer"])                                # тот же файл
        self.put_macro("macro-scenarios-2026-11-06.yaml")
        s = self.state()
        self.assertEqual((s["latest"], s["newer"], s["blocked"]), ("macro-scenarios-2026-11-06.yaml", True, None))
        # применённый — самый свежий (использован новее): не новее
        self.ready(used="macro-scenarios-2026-11-06.yaml")
        self.assertFalse(self.state()["newer"])

    def test_state_other_matrix_blocks(self):
        self.ready()
        self.put_macro("macro-scenarios-2026-11-06.yaml", matrix="scenario-other-2026-11-06")
        s = self.state()
        self.assertEqual((s["newer"], s["blocked"]), (True, "matrix"))

    def test_same_name_macro_rewritten_after_numbers_is_newer(self):
        """Макро-таблицу пересобрали под прежним именем после расчёта чисел — сайт видит её как новую;
        записанная до расчёта — нет."""
        self.ready(used="macro-scenarios-2026-11-04.yaml")          # стресс записан NOW − 1 день
        m = self.put_macro("macro-scenarios-2026-11-04.yaml", when=NOW - timedelta(days=2))
        self.assertFalse(self.state()["newer"])
        self.touch(m, NOW)
        st = self.state()
        self.assertEqual((st["used"], st["latest"], st["newer"]), (m.name, m.name, True))
        # ошибка подстановки привязана к версии файла: после перезаписи — новая попытка
        stress = sj.latest_skill_stress(self.root)
        sj._macro_errors[sj._macro_err_key(self.root, stress, m.name)] = "отказ"
        self.assertIsNone(sj.refresh_reason(self.root, stress))
        self.touch(m, NOW + timedelta(hours=1))
        self.assertEqual(sj.refresh_reason(self.root, stress), "macro")

    def test_used_is_recalc_macro_when_recalc_fresh(self):
        self.ready()
        self.put_macro("macro-scenarios-2026-11-06.yaml")
        rp = self.root / sj.STRESS_AUTO_DIR / f"recalc-{Path(STRESS_NAME).stem}.yaml"
        rp.write_text(f"recalc:\n  at: '{(NOW + timedelta(hours=1)).isoformat()}'\n  macro_input: macro-scenarios-2026-11-06.yaml\n",
                      encoding="utf-8")
        s = self.state()
        self.assertEqual((s["used"], s["newer"]), ("macro-scenarios-2026-11-06.yaml", False))
        # устаревший пересчёт (сделан до записи стресса) в счёт не идёт: берётся macro_input стресса
        rp.write_text(f"recalc:\n  at: '{(NOW - timedelta(days=3)).isoformat()}'\n  macro_input: macro-scenarios-2026-11-06.yaml\n",
                      encoding="utf-8")
        s = self.state()
        self.assertEqual((s["used"], s["newer"]), ("macro-scenarios-2026-11-04.yaml", True))

    def go(self, runner, **kw):
        return sj.recalc(self.root, self.work, self.snap, self.save, runner, NOW, **kw)

    def test_run_passes_macro_when_newer(self):
        self.ready()
        m = self.put_macro("macro-scenarios-2026-11-06.yaml")
        r = Runner()
        res = self.go(r)
        self.assertEqual((res["state"], res["macro_input"], r.macro_seen), ("done", m.name, [str(m)]))
        self.assertNotIn("macro_error", res)

    def test_run_without_macro_when_not_newer_or_blocked(self):
        self.ready()
        self.put_macro("macro-scenarios-2026-11-04.yaml")
        r = Runner()
        self.assertEqual(self.go(r)["state"], "done")
        self.put_macro("macro-scenarios-2026-11-06.yaml", matrix="scenario-other-2026-11-06")
        self.assertEqual(self.go(r)["state"], "done")
        self.assertEqual((r.macro_seen, len(r.calls)), ([], 2))

    def test_macro_is_passed_in_every_recalc_not_only_first(self):
        """Источник пересчёта — всегда стресс скилла со своей макро-таблицей: новая таблица подставляется и во второй,
        и в третий пересчёт (по снапшоту, по весам), иначе числа вернулись бы на прежнюю."""
        self.ready()
        m = self.put_macro("macro-scenarios-2026-11-06.yaml")
        r = Runner()
        self.assertEqual(self.go(r)["macro_input"], m.name)
        # файл пересчёта теперь на новой таблице: «новее» больше нет, но подставлять по-прежнему надо
        rp = self.root / sj.STRESS_AUTO_DIR / f"recalc-{Path(STRESS_NAME).stem}.yaml"
        rp.write_text(f"recalc:\n  at: '{(NOW + timedelta(hours=1)).isoformat()}'\n  macro_input: {m.name}\n", encoding="utf-8")
        st = self.state()
        self.assertEqual((st["used"], st["newer"], st["apply"]), (m.name, False, True))
        self.assertIsNone(sj.refresh_reason(self.root, sj.latest_skill_stress(self.root)))   # сам сайт повторно не запускает
        self.assertEqual(self.go(r)["macro_input"], m.name)
        self.assertEqual(r.macro_seen, [str(m), str(m)])

    def test_manual_recalc_retries_macro_after_refusal(self):
        """Версия макро-файла, давшая отказ, в обычные пересчёты не идёт; «Пересчитать» пробует её снова."""
        self.ready()
        m = self.put_macro("macro-scenarios-2026-11-06.yaml")
        self.go(Runner(refuse_macro="ОТКАЗ: макро-файл не прошёл проверку"))
        r = Runner()
        self.assertNotIn("macro_input", self.go(r))
        self.assertEqual(r.macro_seen, [])
        code, j = sj.post_recalc(self.root, self.work, self.save, r, NOW)
        self.assertEqual((code, j["recalc"]["macro_input"], r.macro_seen), (200, m.name, [str(m)]))
        self.assertIsNone(sj.get_weights(self.root)[1]["macro"]["error"])

    def test_run_retries_without_macro_on_refusal(self):
        self.ready()
        m = self.put_macro("macro-scenarios-2026-11-06.yaml")
        r = Runner(refuse_macro="ОТКАЗ: макро-файл не прошёл проверку")
        res = self.go(r)
        self.assertEqual(res["state"], "done")
        self.assertIn("не прошёл проверку", res["macro_error"])
        self.assertEqual(len(r.calls), 2)
        self.assertNotIn("--macro-scenarios", r.calls[1])
        self.assertEqual(list(self.saved), ["Portfolio/stress/auto/recalc-stress-2026-11-04-geopol-test.yaml"])
        j = sj.get_weights(self.root)[1]
        self.assertEqual((j["macro"]["latest"], j["macro"]["newer"], j["macro"]["blocked"]), (m.name, True, None))
        self.assertIn("не прошёл проверку", j["macro"]["error"])

    def test_refusal_not_caused_by_macro_stays_error(self):
        self.ready()
        self.put_macro("macro-scenarios-2026-11-06.yaml")
        res = self.go(Runner(rc=1, stderr="ОТКАЗ: нет данных"))
        self.assertEqual(res["state"], "error")
        self.assertIn("нет данных", res["error"])

    def test_macro_error_is_per_pair(self):
        self.ready()
        self.put_macro("macro-scenarios-2026-11-06.yaml")
        self.go(Runner(refuse_macro="ОТКАЗ"))
        self.put_macro("macro-scenarios-2026-11-07.yaml")
        self.assertIsNone(sj.get_weights(self.root)[1]["macro"]["error"])       # для другого макро-файла ошибки нет


class RefreshIfNeeded(Base):
    """Сайт пересчитывает сам: причины stress_replaced и macro, ограничение повторов, состояние для GET."""

    def put_macro(self, name):
        (self.root / "macro-chain").mkdir(exist_ok=True)
        (self.root / "macro-chain" / name).write_text(
            "scenario_matrix:\n  source_file: scenarios/scenario-test-2026-07-01.yaml\n", encoding="utf-8")

    def ready(self):
        self.put_stress(macro="macro-scenarios-2026-11-04.yaml")
        self.put_matrix()
        self.touch(self.root / "Portfolio/stress" / STRESS_NAME, NOW - timedelta(days=1))

    def go(self, r):
        return sj.refresh_if_needed(self.root, self.work, self.save, r, wait=True)

    def test_nothing_to_do(self):
        self.ready()
        r = Runner()
        self.assertIsNone(self.go(r))
        self.assertEqual((r.calls, sj.refresh_state(self.root)["state"]), ([], "idle"))

    def test_macro_reason_runs_once_per_pair(self):
        self.ready()
        self.put_macro("macro-scenarios-2026-11-06.yaml")
        r = Runner()
        self.assertEqual(self.go(r), "macro")
        self.assertEqual((len(r.calls), len(r.macro_seen)), (1, 1))
        st = sj.refresh_state(self.root)
        self.assertEqual((st["state"], st["reason"], st["error"]), ("idle", "macro", None))
        self.assertTrue(st["at"].endswith("+03:00"))
        self.assertIsNone(self.go(r))                      # файл на диске прежний, повтор в пределах REFRESH_RETRY_S не идёт
        self.assertEqual(len(r.calls), 1)
        self.put_macro("macro-scenarios-2026-11-07.yaml")  # другая пара — снова можно
        self.assertEqual(self.go(r), "macro")

    def test_macro_error_blocks_further_macro_refresh(self):
        self.ready()
        self.put_macro("macro-scenarios-2026-11-06.yaml")
        r = Runner(refuse_macro="ОТКАЗ")
        self.assertEqual(self.go(r), "macro")
        sj._refresh_tried.clear()
        self.assertIsNone(self.go(r))                      # для этой пары ошибка записана — сам не повторяет
        self.assertEqual(len(r.calls), 2)

    def test_blocked_matrix_is_not_a_reason(self):
        self.ready()
        (self.root / "macro-chain").mkdir()
        (self.root / "macro-chain/macro-scenarios-2026-11-06.yaml").write_text(
            "scenario_matrix:\n  source_file: scenarios/scenario-other.yaml\n", encoding="utf-8")
        self.assertIsNone(self.go(Runner()))

    def test_stress_replaced_has_priority(self):
        self.ready()
        self.put_macro("macro-scenarios-2026-11-06.yaml")
        p = self.root / "Portfolio/stress" / STRESS_NAME
        self.touch(p, NOW)
        d = self.root / sj.STRESS_AUTO_DIR / f"recalc-{Path(STRESS_NAME).stem}.yaml"
        d.write_text(f"recalc:\n  at: '{(NOW - timedelta(hours=1)).isoformat()}'\n", encoding="utf-8")
        self.assertEqual(self.go(Runner()), "stress_replaced")

    def test_error_state(self):
        self.ready()
        self.put_macro("macro-scenarios-2026-11-06.yaml")
        r = Runner(rc=1, stderr="ОТКАЗ: нет данных")
        self.assertEqual(self.go(r), "macro")
        st = sj.refresh_state(self.root)
        self.assertEqual((st["state"], st["reason"]), ("error", "macro"))
        self.assertIn("нет данных", st["error"])

    def test_get_weights_reports_running_and_refresh(self):
        self.ready()
        self.put_macro("macro-scenarios-2026-11-06.yaml")
        j = sj.get_weights(self.root)[1]
        self.assertEqual(j["refresh"], {"state": "idle", "reason": None, "error": None, "at": None})
        self.assertTrue(j["macro"]["newer"])
        r = Runner()
        j = sj.get_weights(self.root, refresh=(self.work, self.save, r))[1]
        self.assertFalse(j["recalc_refreshing"])            # причина не stress_replaced: прежнее поле не трогаем
        for _ in range(100):
            if not sj._refreshing:
                break
            time.sleep(0.05)
        self.assertEqual(len(r.calls), 1)
        self.assertEqual(sj.get_weights(self.root)[1]["refresh"]["reason"], "macro")


class PostRecalc(Base):
    def go(self, runner):
        return sj.post_recalc(self.root, self.work, self.save, runner, NOW)

    def test_409_without_stress_or_snapshot(self):
        self.assertEqual(self.go(Runner())[0], 409)
        self.put_stress()
        self.snap.unlink()
        r = Runner()
        self.assertEqual((self.go(r)[0], r.calls), (409, []))

    def test_success_writes_only_recalc_file(self):
        self.put_stress()
        self.put_matrix()
        tree = fake_tree()
        tree["scenarios"] = {"A": {"p_by_horizon": {"h6": 0.7, "h12": 0.7}}, "B": {"p_by_horizon": {"h6": 0.3, "h12": 0.3}}}
        code, j = self.go(Runner(tree=tree))
        self.assertEqual(code, 200)
        self.assertEqual(list(self.saved), ["Portfolio/stress/auto/recalc-stress-2026-11-04-geopol-test.yaml"])
        self.assertEqual((j["recalc"]["state"], j["summary"]["snapshot_id"]), ("done", "portfolio-2026-11-05.json"))
        self.assertEqual(j["summary"]["horizons"]["h6"]["modal"], {"scenario": "A", "weight": 0.7})
        self.assertEqual(j["summary"]["horizons"]["h6"]["price"], {"expected_pl_pct": 1.5, "expected_pl_rub": 1000})
        self.assertEqual(sj.refresh_state(self.root)["reason"], "manual")
        self.assertEqual(sj.refresh_state(self.root)["state"], "idle")

    def test_picks_up_newer_macro(self):
        self.put_stress(macro="macro-scenarios-2026-11-04.yaml")
        (self.root / "macro-chain").mkdir()
        m = self.root / "macro-chain/macro-scenarios-2026-11-06.yaml"
        m.write_text("scenario_matrix:\n  source_file: scenarios/scenario-test-2026-07-01.yaml\n", encoding="utf-8")
        r = Runner()
        self.assertEqual(self.go(r)[0], 200)
        self.assertEqual(r.macro_seen, [str(m)])

    def test_failure_is_502_and_error_state(self):
        self.put_stress()
        code, j = self.go(Runner(rc=1, stderr="ОТКАЗ: плохо"))
        self.assertEqual(code, 502)
        self.assertIn("плохо", j["error"])
        self.assertEqual(j["recalc"]["state"], "error")
        self.assertEqual(self.saved, {})
        st = sj.refresh_state(self.root)
        self.assertEqual((st["state"], st["reason"]), ("error", "manual"))


class RealScript(Base):
    """Настоящий stress_recalc.py: стык «уведомитель → скрипт» не только заглушкой."""

    def test_end_to_end(self):
        snap0 = tsr.snapshot()
        stress = tsr.build_skill_stress(self.tmp, snap0)              # 2 сценария (A, B), горизонты h6/h12
        sdoc = yaml.safe_load(stress.read_text(encoding="utf-8"))
        name = f"stress-{sdoc['date']}-t.yaml"
        (self.root / "Portfolio/stress" / name).write_text(stress.read_text(encoding="utf-8"), encoding="utf-8")
        snap1 = tsr.snapshot(qty1=700000.0, as_of="2026-11-05")
        self.snap.write_text(json.dumps(snap1), encoding="utf-8")
        res = sj.recalc(self.root, self.work, self.snap, self.save, subprocess.run, NOW)
        self.assertEqual(res["state"], "done", res)
        self.assertEqual(res["reason"], "snapshot")
        self.assertEqual(res["snapshot_id"], "portfolio-2026-11-05.json")
        out = yaml.safe_load(self.saved[res["path"]])
        self.assertEqual(out["recalc"]["source_stress"], name)
        self.assertEqual(out["recalc"]["at"], "2026-11-05T22:00:00+03:00")
        # веса из файла: A=0.9/B=0.1 на обоих горизонтах
        he = sdoc["horizon_ends"]
        w = {"schema": "stress-weights@1", "horizon_ends": he, "weights": {h: {"A": 0.9, "B": 0.1} for h in he},
             "set_at": "2026-11-05T21:00:00+03:00"}
        wf = self.tmp / "w.json"
        wf.write_text(json.dumps(w), encoding="utf-8")
        res = sj.recalc(self.root, self.work, self.snap, self.save, subprocess.run, NOW, weights_path=wf, write=False)
        self.assertEqual(res["state"], "done", res)
        self.assertTrue(res["weights_source"].startswith("stress-weights:"))
        # веса с чужими сроками — отказ скрипта (код 1) доходит как error
        w["horizon_ends"] = {**he, "h6": "2030-01-01"}
        wf.write_text(json.dumps(w), encoding="utf-8")
        res = sj.recalc(self.root, self.work, self.snap, self.save, subprocess.run, NOW, weights_path=wf)
        self.assertEqual(res["state"], "error")
        self.assertIn("горизонты стресса изменились", res["error"])
        self.assertEqual(len(self.saved), 1)                          # второй и третий вызовы ничего не записали


if __name__ == "__main__":
    unittest.main(verbosity=1)
