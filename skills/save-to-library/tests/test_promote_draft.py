#!/usr/bin/env python3
"""Тесты promote_draft.py — приёмка черновика `_drafts/` в библиотеку одной командой (STL-42).

Корень Claude-Memory во временной папке с черновиками шести видов (прогноз, сценарии, стресс, интегрированный вид,
отчёт монитора, ретро-аудит). Для каждого вида: dry-run ничего не пишет; приёмка кладёт файлы, дописывает INDEX и
`_sync_log.md`, удаляет черновик; блокер валидатора — ничего не записано; занятое имя — отказ. Отдельно: `--replaces`
у прогноза (прежний `superseded` + `superseded_by` + промежуточный снимок outcome_log), `--keep-draft`, сборка
`.yaml` прогноза из блока Events YAML с недостающими полями из frontmatter, заморозка outcome_log.
"""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "promote_draft.py")
sys.path.insert(0, os.path.join(HERE, ".."))
from tests.test_assemble_artifact import _iv_fm, _v2_stress  # noqa: E402  валидные минимальные фикстуры

TODAY = "2026-11-04"

FORECAST_MD = """---
schema_version: 1
forecast_date: 2026-11-04
horizon_date: 2027-12-31
horizons: [2026-12-31, 2027-12-31]
review_interval_months: 3
topic: cpi-test
domain: ru-macro
method: fca
confidence: 0.4
---

# Инфляция: тестовый прогноз

## TL;DR

Текст отчёта.

## Что дальше

Пункты.

---

## Events YAML (для save-to-library)

```yaml
forecast:
  date: 2026-11-04
```
"""

FORECAST_EVENTS = """forecast:
  date: 2026-11-04
  horizon: 2027-12-31
  domain: ru-macro
  topic: cpi-test
  central_estimate: "CPI: 6.8% к 2026-12-31"   # комментарий модели переносится как есть
  confidence: 0.4

isolated: true
isolated_reason: "Type 1: без сценарной декомпозиции"

fca_stats:
  "2026-12-31":
    kind: level
    unit: percent_annual
    l1_weighted: 6.8
    l1_unweighted: 6.9
    l2_ev: null
    p10: 6.5
    p90: 7.1

reviews:
  interval_months: 3
  next_due: 2027-02-04

monitoring:
  - id: cpi-nov
    description: "Недельная инфляция"
    auto_checkable: false
"""

OLD_FORECAST_YAML = """schema_version: 1
type: forecast-events
forecast_ref: cpi-test-2026-09-01.md
status: active

forecast:
  date: 2026-09-01
  horizon: 2027-12-31
  topic: cpi-test
  method: fca
  confidence: 0.4   # прежняя версия

isolated: true
isolated_reason: "Type 1"

fca_stats:
  "2026-12-31":
    kind: level
    unit: percent_annual
    l1_weighted: 6.5
    l1_unweighted: 6.6
    l2_ev: null
    p10: 6.2
    p90: 6.9

reviews:
  interval_months: 3
  next_due: 2026-12-01
  last_completed: null
  history: []

final_audit:
  due: 2027-12-31
  status: pending
"""

SCENARIO_EVENTS = """matrix:
  date: 2026-11-04
  horizon: 2027-12-31
  domain: geopolitics
  topic: test-matrix
  axis_x: "X: a vs b"
  axis_y: "Y: c vs d"
  polarity: {stress_pole: A, detente_pole: D}

scenario_triggers:
  - scenario_id: A
    label: "Альфа"
    probability: 0.25
  - scenario_id: B
    label: "Бета"
    probability: 0.25
  - scenario_id: C
    label: "Гамма"
    probability: 0.25
  - scenario_id: D
    label: "Дельта"
    probability: 0.25

reviews:
  interval_months: 6
  next_due: 2027-05-04
"""

SCENARIO_MD = """# Сценарии: тест · 2026-11-04

## Матрица 2×2

Таблица.

## Events YAML (для save-to-library)

```yaml
matrix: {}
```
"""

INDEXES = {
    "forecasts/INDEX.md": "# Forecasts — Index\n\n## Активные прогнозы\n\n"
                          "| File | Type | Topic | Forecast date | Horizon | Status | Central estimate / confidence |\n"
                          "|------|------|-------|---------------|---------|--------|-------------------------------|\n"
                          "| [cpi-test-2026-09-01.md](cpi-test-2026-09-01.md) | forecast | cpi-test | 2026-09-01 | 2027-12-31 | active | 6.5 |\n"
                          "| [cpi-test-2026-09-01.yaml](cpi-test-2026-09-01.yaml) | events Tier 1 | (см. ↑) | — | — | — | confidence: 0.4 |\n"
                          "\n## Сменённые версии (superseded)\n\n"
                          "| File | Type | Topic | Forecast date | Status | Superseded by |\n"
                          "|------|------|-------|---------------|--------|---------------|\n"
                          "| [old-2026-01-01.md](old-2026-01-01.md) | forecast | old | 2026-01-01 | superseded | old-2026-02-01 |\n"
                          "| [old-2026-02-01.md](old-2026-02-01.md) | forecast | old | 2026-02-01 | superseded | old-2026-03-01 |\n",
    "scenarios/INDEX.md": "# Scenarios — Index\n\n## Активные матрицы\n\n"
                          "| File | Type | Topic | Created | Horizon | Status | Axes |\n|---|---|---|---|---|---|---|\n",
    "Portfolio/INDEX.md": "# Portfolio · INDEX\n\n## Активные артефакты\n\n### stress/\n\n"
                          "| Файл | Дата | Macro input | Status |\n|---|---|---|---|\n\n### integrated-views/\n\n"
                          "| Файл | Тип | Дата | Inputs |\n|---|---|---|---|\n\n## Метаданные\n\n- Создано: 2026-05-04\n",
    "reports/INDEX.md": "# reports/INDEX.md\n\nАрхив.\n\n"
                        "| Файл | source | period | audit_date | domain | linked_forecast |\n|---|---|---|---|---|---|\n",
    "INDEX.md": "# Claude Memory — Master Index\n\n## Активные мониторинговые отчёты\n\n"
                "- `monitor-report-2026-10-29` · 0 HIGH → [monitor-reports/monitor-report-2026-10-29.yaml](x)\n\n"
                "## Архив monitor-reports\n",
    "domains/ru-macro/INDEX.md": "# RU Macro — Index\n\n## Файлы\n\n| Файл | Тип |\n|---|---|\n",
}

MONITOR = {"schema_version": 1, "type": "monitor-report", "generated_at": "2026-11-04T10:00:00+03:00",
           "producer": "forecast-monitor", "scope": "full",
           "alerts": [{"severity": "LOW", "category": "stale", "target": "cpi-test", "message": "m",
                       "detected_at": "2026-11-04"}],
           "freshness_audit": {}}

PROFILE = """---
source: "Тестовый банк"
period: "2022-2025"
audit_type: "Full"
audit_date: "2026-11-04"
trust:
  ru-inflation: HIGH
  ru-rates-forecast: MEDIUM
pin: false
linked_forecast: "fc-test-collection-2026-11-04.md"
---

## §7 Trust-вердикт

Текст.
"""

REPORT = PROFILE.replace("## §7 Trust-вердикт", "# Полный отчёт\n\n## §1 Тезисы")


def _iv_md(fm=None):
    fm = fm or _iv_fm()
    body = "\n".join(f"## {n}. Секция\n\nТекст.\n" for n in range(1, 7))
    return "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False) + "---\n\n# Вид\n\n" + body


DRAFTS = {
    "forecast": ("cpi-test-2026-11-04", {"cpi-test-2026-11-04.md": FORECAST_MD,
                                          "cpi-test-2026-11-04.events.yaml": FORECAST_EVENTS}),
    "scenario": ("scenario-test-matrix-2026-11-04", {"scenario-test-matrix-2026-11-04.md": SCENARIO_MD,
                                                     "scenario-test-matrix-2026-11-04.events.yaml": SCENARIO_EVENTS}),
    "stress": ("stress-2026-11-04-test", None),
    "integrated-view": ("integrated-view-2026-11-04", None),
    "monitor-report": ("monitor-report-2026-11-04", None),
    "retro-audit": ("2026-11-04-test-bank-2022-2025", {"2026-11-04-test-bank-2022-2025.md": REPORT,
                                                        "test-bank-2022-2025-profile.md": PROFILE}),
}

TARGETS = {
    "forecast": ["forecasts/cpi-test-2026-11-04.md", "forecasts/cpi-test-2026-11-04.yaml"],
    "scenario": ["scenarios/scenario-test-matrix-2026-11-04.md", "scenarios/scenario-test-matrix-2026-11-04.yaml"],
    "stress": ["Portfolio/stress/stress-2026-11-04-test.md", "Portfolio/stress/stress-2026-11-04-test.yaml"],
    "integrated-view": ["Portfolio/integrated-views/integrated-view-2026-11-04.md"],
    "monitor-report": ["monitor-reports/monitor-report-2026-11-04.yaml"],
    "retro-audit": ["domains/ru-macro/test-bank-2022-2025.md", "reports/2026-11-04-test-bank-2022-2025.md"],
}

INDEX_OF = {"forecast": "forecasts/INDEX.md", "scenario": "scenarios/INDEX.md", "stress": "Portfolio/INDEX.md",
            "integrated-view": "Portfolio/INDEX.md", "monitor-report": "INDEX.md", "retro-audit": "reports/INDEX.md"}


def _draft_files(kind):
    name, files = DRAFTS[kind]
    if files is not None:
        return name, dict(files)
    if kind == "stress":
        return name, {f"{name}.md": "# Стресс-тест\n\nТекст.\n",
                      f"{name}.yaml": yaml.safe_dump(_v2_stress(), allow_unicode=True, sort_keys=False)}
    if kind == "integrated-view":
        return name, {f"{name}.md": _iv_md()}
    return name, {f"{name}.yaml": yaml.safe_dump(MONITOR, allow_unicode=True, sort_keys=False)}


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="promote-")
        for rel, text in INDEXES.items():
            self._put(rel, text)
        self._put("_sync_log.md", "# _sync_log\n\n2026-11-03 | save-to-library | x | Workflow B\n")
        self._put("forecasts/cpi-test-2026-09-01.yaml", OLD_FORECAST_YAML)
        self._put("forecasts/cpi-test-2026-09-01.md", "---\ntopic: cpi-test\n---\n\n# Старый\n")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _put(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def _get(self, rel):
        with open(os.path.join(self.root, rel), encoding="utf-8") as fh:
            return fh.read()

    def _exists(self, rel):
        return os.path.exists(os.path.join(self.root, rel))

    def _draft(self, kind, override=None):
        name, files = _draft_files(kind)
        files.update(override or {})
        for fn, text in files.items():
            self._put(f"_drafts/{fn}", text)
        return name, sorted(f"_drafts/{fn}" for fn in files)

    def _run(self, kind, name, *args, stdin=None):
        cmd = [sys.executable, SCRIPT] if stdin is not None else \
            [sys.executable, SCRIPT, "--root", self.root, "--draft", name, "--kind", kind, "--today", TODAY, *args]
        p = subprocess.run(cmd, capture_output=True, text=True, input=stdin)
        self.assertIn(p.returncode, (0, 1), p.stderr)
        return p.returncode, json.loads(p.stdout)

    def _snapshot(self):
        out = {}
        for dp, _, fns in os.walk(self.root):
            for fn in fns:
                path = os.path.join(dp, fn)
                with open(path, "rb") as fh:
                    out[os.path.relpath(path, self.root)] = fh.read()
        return out


class TestEachKind(Base):
    """Для каждого из шести видов: dry-run, приёмка, блокер, занятое имя."""

    def test_dry_run_writes_nothing(self):
        for kind in DRAFTS:
            with self.subTest(kind=kind):
                name, _ = self._draft(kind)
                before = self._snapshot()
                code, out = self._run(kind, name, "--dry-run")
                self.assertEqual(code, 0, out["issues"])
                self.assertTrue(out["ok"] and out["dry_run"])
                self.assertEqual(sorted(out["written"]), TARGETS[kind])
                self.assertEqual(self._snapshot(), before, "dry-run изменил файлы")

    def test_promote_writes_registers_and_removes_draft(self):
        for kind in DRAFTS:
            with self.subTest(kind=kind):
                name, drafts = self._draft(kind)
                log_before = self._get("_sync_log.md")
                code, out = self._run(kind, name)
                self.assertEqual(code, 0, out["issues"])
                for rel in TARGETS[kind]:
                    self.assertTrue(self._exists(rel), rel)
                self.assertEqual(out["draft_removed"], drafts)
                for rel in drafts:
                    self.assertFalse(self._exists(rel), rel)
                log = self._get("_sync_log.md")
                self.assertTrue(log.startswith(log_before))
                line = log[len(log_before):].strip()
                self.assertEqual(line, out["sync_log_line"])
                self.assertTrue(line.startswith(f"{TODAY} | save-to-library | "))
                self.assertIn("(promote-draft)", line)
                idx = self._get(INDEX_OF[kind])
                self.assertIn(os.path.basename(TARGETS[kind][0]).split(".")[0] if kind != "retro-audit"
                              else "2026-11-04-test-bank-2022-2025.md", idx)

    def test_blocking_validator_writes_nothing(self):
        broken = {
            "forecast": {"cpi-test-2026-11-04.events.yaml": FORECAST_EVENTS.replace("isolated: true\n", "")},
            "scenario": {"scenario-test-matrix-2026-11-04.events.yaml":
                         SCENARIO_EVENTS.replace("label: \"Дельта\"\n    probability: 0.25", "label: \"Дельта\"\n    probability: четверть")},
            "stress": {"stress-2026-11-04-test.yaml": "schema_version: 2\ntype: portfolio-stress-test\n"},
            "integrated-view": {"integrated-view-2026-11-04.md": _iv_md({**_iv_fm(), "primary_horizon": 99})},
            "monitor-report": {"monitor-report-2026-11-04.yaml": yaml.safe_dump({**MONITOR, "alerts": [
                {"severity": "LOUD", "category": "stale", "target": "x", "message": "m", "detected_at": "2026-11-04"}]})},
            "retro-audit": {"test-bank-2022-2025-profile.md": PROFILE.replace('source: "Тестовый банк"\n', "")},
        }
        for kind in DRAFTS:
            with self.subTest(kind=kind):
                name, drafts = self._draft(kind, broken[kind])
                before = self._snapshot()
                code, out = self._run(kind, name)
                self.assertEqual(code, 1)
                self.assertFalse(out["ok"])
                self.assertTrue(any(i["severity"] == "blocking" for i in out["issues"]))
                self.assertEqual(out["written"], [])
                self.assertEqual(self._snapshot(), before)
                for rel in drafts:
                    os.remove(os.path.join(self.root, rel))

    def test_taken_name_refused_without_force(self):
        for kind in DRAFTS:
            with self.subTest(kind=kind):
                name, drafts = self._draft(kind)
                self._put(TARGETS[kind][0], "занято\n")
                before = self._snapshot()
                code, out = self._run(kind, name)
                self.assertEqual(code, 1)
                self.assertTrue(any(i.get("field") == "target" for i in out["issues"]))
                self.assertEqual(self._snapshot(), before)
                code, out = self._run(kind, name, "--force")
                self.assertEqual(code, 0, out["issues"])
                self.assertNotEqual(self._get(TARGETS[kind][0]), "занято\n")


class TestForecast(Base):
    def test_yaml_assembled_from_events_and_frontmatter(self):
        name, _ = self._draft("forecast")
        code, out = self._run("forecast", name)
        self.assertEqual(code, 0, out["issues"])
        y = self._get("forecasts/cpi-test-2026-11-04.yaml")
        self.assertTrue(y.startswith("schema_version: 1\ntype: forecast-events\n"
                                     "forecast_ref: cpi-test-2026-11-04.md\nstatus: active\n\nforecast:\n"))
        self.assertIn("# комментарий модели переносится как есть", y)   # текст блока — байт в байт
        d = yaml.safe_load(y)
        fc = d["forecast"]
        self.assertEqual(fc["method"], "fca")
        self.assertEqual([str(h) for h in fc["horizons"]], ["2026-12-31", "2027-12-31"])
        self.assertEqual(fc["upstream_snapshot"], [])
        self.assertEqual(d["reviews"]["last_completed"], None)
        self.assertEqual(d["reviews"]["history"], [])
        self.assertEqual(d["final_audit"], {"due": __import__("datetime").date(2027, 12, 31), "status": "pending"})
        ol = d["outcome_log"]
        self.assertEqual(len(ol), 1)
        self.assertEqual(str(ol[0]["resolve_date"]), "2026-12-31")
        self.assertEqual(ol[0]["record_type"], "horizon_resolve")
        self.assertEqual(ol[0]["forecast_l1_weighted"], 6.8)
        self.assertEqual(ol[0]["p10_p90"], [6.5, 7.1])
        self.assertEqual(ol[0]["confidence_at_forecast"], 0.4)
        md = self._get("forecasts/cpi-test-2026-11-04.md")
        self.assertNotIn("Events YAML", md)
        self.assertTrue(md.endswith("## Что дальше\n\nПункты.\n"))
        idx = self._get("forecasts/INDEX.md")
        self.assertIn("| [cpi-test-2026-11-04.md](cpi-test-2026-11-04.md) | forecast | cpi-test | 2026-11-04 | "
                      "2027-12-31 | active | CPI: 6.8% к 2026-12-31 |", idx)

    def test_no_outcome_log_flag(self):
        name, _ = self._draft("forecast")
        code, out = self._run("forecast", name, "--no-outcome-log")
        self.assertEqual(code, 0, out["issues"])
        self.assertNotIn("outcome_log", yaml.safe_load(self._get("forecasts/cpi-test-2026-11-04.yaml")))

    def test_outcome_resolve_must_be_in_fca_stats(self):
        name, _ = self._draft("forecast")
        code, out = self._run("forecast", name, "--outcome-resolve", "2027-06-30")
        self.assertEqual(code, 1)
        self.assertTrue(any(i.get("field") == "outcome_resolve" for i in out["issues"]))

    def test_replaces_marks_previous_superseded(self):
        name, _ = self._draft("forecast")
        code, out = self._run("forecast", name, "--replaces", "cpi-test-2026-09-01.yaml",
                              "--actual", "7.0", "--actual-source", "https://example.org/cpi")
        self.assertEqual(code, 0, out["issues"])
        self.assertEqual(out["replaced"], "forecasts/cpi-test-2026-09-01.yaml")
        old_text = self._get("forecasts/cpi-test-2026-09-01.yaml")
        self.assertIn("status: superseded\nsuperseded_by: cpi-test-2026-11-04.yaml\n", old_text)
        self.assertIn("confidence: 0.4   # прежняя версия", old_text)   # остальное не переформатировано
        old = yaml.safe_load(old_text)
        snap = old["outcome_log"][-1]
        self.assertEqual(snap["record_type"], "interim_supersession")
        self.assertEqual(str(snap["resolve_date"]), "2026-11-04")
        self.assertEqual(snap["forecast_l1_weighted"], 6.5)
        self.assertEqual(snap["actual"], 7.0)
        self.assertEqual(snap["in_p10_p90"], False)
        self.assertAlmostEqual(snap["error_pct"], 7.6923, places=3)
        self.assertEqual(snap["actual_source"], "https://example.org/cpi")
        new = yaml.safe_load(self._get("forecasts/cpi-test-2026-11-04.yaml"))
        self.assertEqual(new["replaces"], ["cpi-test-2026-09-01"])
        self.assertIn("replaces: cpi-test-2026-09-01.yaml", self._get("forecasts/cpi-test-2026-11-04.md"))
        idx = self._get("forecasts/INDEX.md")
        active, sup = idx.split("## Сменённые версии (superseded)")
        self.assertNotIn("cpi-test-2026-09-01", active)          # строка ушла из активных
        self.assertIn("| [cpi-test-2026-09-01.md](cpi-test-2026-09-01.md) | forecast | cpi-test | 2026-09-01 | "
                      "superseded | cpi-test-2026-11-04 |", sup)
        self.assertIn("| [cpi-test-2026-09-01.yaml](cpi-test-2026-09-01.yaml) | events Tier 1 | (см. ↑) | — | "
                      "superseded | cpi-test-2026-11-04.yaml |", sup)
        rows = [ln for ln in sup.split("\n") if ln.startswith("| [")]
        self.assertTrue(rows[0].startswith("| [old-2026-01-01.md]") and rows[1].startswith("| [old-2026-02-01.md]")
                        and rows[2].startswith("| [cpi-test-2026-09-01.md]"))  # даты растут вниз — в конец
        self.assertIn("cpi-test-2026-09-01 → superseded", out["sync_log_line"])
        backups = os.listdir(os.path.join(self.root, ".backups", "forecasts"))
        self.assertTrue(any(b.startswith("cpi-test-2026-09-01.yaml.bak-") for b in backups), backups)

    def test_replaces_missing_file_refused(self):
        name, _ = self._draft("forecast")
        before = self._snapshot()
        code, out = self._run("forecast", name, "--replaces", "nope-2026-01-01.yaml")
        self.assertEqual(code, 1)
        self.assertEqual(self._snapshot(), before)

    def test_keep_draft(self):
        name, drafts = self._draft("forecast")
        code, out = self._run("forecast", name, "--keep-draft")
        self.assertEqual(code, 0, out["issues"])
        self.assertFalse(out["draft_removed"])
        for rel in drafts:
            self.assertTrue(self._exists(rel))

    def test_as_name_and_json_stdin(self):
        name, _ = self._draft("forecast")
        payload = {"root": self.root, "draft": name, "kind": "forecast", "as": "cpi-test-2026-11-04-v2",
                   "today": TODAY}
        code, out = self._run("forecast", name, stdin=json.dumps(payload))
        self.assertEqual(code, 0, out["issues"])
        self.assertTrue(self._exists("forecasts/cpi-test-2026-11-04-v2.yaml"))
        self.assertIn("forecast_ref: cpi-test-2026-11-04-v2.md",
                      self._get("forecasts/cpi-test-2026-11-04-v2.yaml"))

    def test_missing_draft_refused(self):
        code, out = self._run("forecast", "nothing-2026-11-04")
        self.assertEqual(code, 1)
        self.assertIn("нет файлов черновика", out["issues"][0]["actual"])


class TestIndexPlacement(Base):
    """Перенос в «Сменённые версии», направление вставки по таблице, создание отсутствующего INDEX."""

    SC_OLD = ("schema_version: 1\ntype: scenario-events\nscenario_ref: scenario-test-matrix-2026-05-01.md\n"
              "status: active\n\nmatrix:\n  date: 2026-05-01\n  topic: test-matrix\n")

    def test_scenario_superseded_section_created_at_end(self):
        self._put("scenarios/scenario-test-matrix-2026-05-01.yaml", self.SC_OLD)
        self._put("scenarios/INDEX.md", INDEXES["scenarios/INDEX.md"]
                  + "| [scenario-test-matrix-2026-05-01.md](scenario-test-matrix-2026-05-01.md) | scenario-matrix | "
                    "test-matrix | 2026-05-01 | 2027-12-31 | active | X × Y |\n"
                  + "| [scenario-test-matrix-2026-05-01.yaml](scenario-test-matrix-2026-05-01.yaml) | "
                    "[events scenarios] | (см. ↑) | — | — | — | 4 сценария |\n")
        name, _ = self._draft("scenario")
        code, out = self._run("scenario", name, "--replaces", "scenario-test-matrix-2026-05-01.yaml")
        self.assertEqual(code, 0, out["issues"])
        idx = self._get("scenarios/INDEX.md")
        active, sup = idx.split("## Сменённые версии (superseded)")
        self.assertNotIn("2026-05-01", active)
        self.assertIn("| [scenario-test-matrix-2026-05-01.md](scenario-test-matrix-2026-05-01.md) | test-matrix | "
                      "2026-05-01 | superseded | → scenario-test-matrix-2026-11-04 |", sup)
        self.assertIn("| [scenario-test-matrix-2026-05-01.yaml](scenario-test-matrix-2026-05-01.yaml) | test-matrix | "
                      "2026-05-01 | superseded | → scenario-test-matrix-2026-11-04 |", sup)
        self.assertIn("| File | Topic | Created | Status | Superseded by |", sup)
        self.assertIn("scenario-test-matrix-2026-11-04.md", active)

    def test_stress_and_view_appended_at_end(self):
        self._put("Portfolio/INDEX.md", INDEXES["Portfolio/INDEX.md"].replace(
            "| Файл | Дата | Macro input | Status |\n|---|---|---|---|\n",
            "| Файл | Дата | Macro input | Status |\n|---|---|---|---|\n"
            "| stress-2026-05-04-a.md/.yaml | 2026-05-04 | m | active |\n").replace(
            "| Файл | Тип | Дата | Inputs |\n|---|---|---|---|\n",
            "| Файл | Тип | Дата | Inputs |\n|---|---|---|---|\n| integrated-view-2026-05-06.md | integrated-view | "
            "2026-05-06 | — |\n"))
        for kind in ("stress", "integrated-view"):
            name, _ = self._draft(kind)
            code, out = self._run(kind, name)
            self.assertEqual(code, 0, out["issues"])
        lines = self._get("Portfolio/INDEX.md").split("\n")
        i = lines.index("| stress-2026-05-04-a.md/.yaml | 2026-05-04 | m | active |")
        self.assertTrue(lines[i + 1].startswith("| stress-2026-11-04-test.md/.yaml | "))
        j = lines.index("| integrated-view-2026-05-06.md | integrated-view | 2026-05-06 | — |")
        self.assertTrue(lines[j + 1].startswith("| integrated-view-2026-11-04.md | "))

    def _reports(self, dates):
        rows = "".join(f"| {d}-x-2020.md | X | 2020 | {d} | ru-macro | — |\n" for d in dates)
        self._put("reports/INDEX.md", INDEXES["reports/INDEX.md"] + rows)

    def test_auto_direction_follows_table(self):
        for dates, at_end in ((["2026-01-01", "2026-02-01"], True), (["2026-02-01", "2026-01-01"], False)):
            with self.subTest(dates=dates):
                self._reports(dates)
                name, _ = self._draft("retro-audit")
                code, out = self._run("retro-audit", name)
                self.assertEqual(code, 0, out["issues"])
                rows = [ln for ln in self._get("reports/INDEX.md").split("\n") if ln.startswith("| 20")]
                self.assertEqual(len(rows), 3)
                self.assertTrue((rows[-1] if at_end else rows[0]).startswith("| 2026-11-04-test-bank-2022-2025.md"))
                for rel in ("reports/2026-11-04-test-bank-2022-2025.md", "domains/ru-macro/test-bank-2022-2025.md"):
                    os.remove(os.path.join(self.root, rel))

    def test_missing_index_created_from_template(self):
        os.remove(os.path.join(self.root, "reports/INDEX.md"))
        os.remove(os.path.join(self.root, "domains/ru-macro/INDEX.md"))
        name, _ = self._draft("retro-audit")
        code, out = self._run("retro-audit", name, "--dry-run")
        self.assertEqual(code, 0, out["issues"])
        self.assertEqual(out["index_created"], ["reports/INDEX.md"])
        self.assertFalse(self._exists("reports/INDEX.md"))          # dry-run не создаёт
        code, out = self._run("retro-audit", name)
        self.assertEqual(code, 0, out["issues"])
        idx = self._get("reports/INDEX.md")
        self.assertTrue(idx.startswith("# reports/INDEX.md\n"))
        self.assertIn("| Файл | source | period | audit_date | domain | linked_forecast |", idx)
        self.assertIn("| 2026-11-04-test-bank-2022-2025.md | Тестовый банк |", idx)
        self.assertFalse(self._exists("domains/ru-macro/INDEX.md"))  # формат доменов скрипту не известен
        self.assertTrue(any(p.startswith("domains/ru-macro/INDEX.md") for p in out["index_pending"]))

    def test_missing_forecast_and_root_index_created(self):
        for rel in ("forecasts/INDEX.md", "INDEX.md"):
            os.remove(os.path.join(self.root, rel))
        for kind in ("forecast", "monitor-report"):
            name, _ = self._draft(kind)
            code, out = self._run(kind, name)
            self.assertEqual(code, 0, out["issues"])
            self.assertEqual(out["index_pending"], [])
        fc = self._get("forecasts/INDEX.md")
        self.assertIn("## Активные прогнозы", fc)
        self.assertIn("## Сменённые версии (superseded)", fc)
        self.assertIn("[cpi-test-2026-11-04.md](cpi-test-2026-11-04.md)", fc.split("## Сменённые")[0])
        self.assertIn("- `monitor-report-2026-11-04` ·", self._get("INDEX.md"))


class TestOtherKinds(Base):
    def test_scenario_frontmatter_built_from_matrix(self):
        name, _ = self._draft("scenario")
        code, out = self._run("scenario", name)
        self.assertEqual(code, 0, out["issues"])
        md = self._get("scenarios/scenario-test-matrix-2026-11-04.md")
        fm = yaml.safe_load(md.split("---\n")[1])
        self.assertEqual(fm["type"], "scenario-matrix")
        self.assertEqual(fm["scenarios"], ["Альфа", "Бета", "Гамма", "Дельта"])
        self.assertNotIn("Events YAML", md)
        d = yaml.safe_load(self._get("scenarios/scenario-test-matrix-2026-11-04.yaml"))
        self.assertEqual((d["type"], d["status"], d["scenario_ref"]),
                         ("scenario-events", "active", "scenario-test-matrix-2026-11-04.md"))
        self.assertEqual(d["final_audit"]["status"], "pending")

    def test_retro_domain_from_trust_and_profile_suffix_dropped(self):
        name, _ = self._draft("retro-audit")
        code, out = self._run("retro-audit", name)
        self.assertEqual(code, 0, out["issues"])
        self.assertTrue(self._exists("domains/ru-macro/test-bank-2022-2025.md"))
        self.assertTrue(any("domains/ru-macro/INDEX.md" in p for p in out["index_pending"]))
        self.assertIn("| 2026-11-04-test-bank-2022-2025.md | Тестовый банк | 2022-2025 | 2026-11-04 | ru-macro | "
                      "fc-test-collection-2026-11-04.md |", self._get("reports/INDEX.md"))

    def test_retro_ambiguous_domain_needs_flag(self):
        prof = PROFILE.replace("  ru-inflation: HIGH\n  ru-rates-forecast: MEDIUM\n", "  something-new: HIGH\n")
        name, _ = self._draft("retro-audit", {"test-bank-2022-2025-profile.md": prof})
        code, out = self._run("retro-audit", name)
        self.assertEqual(code, 1)
        code, out = self._run("retro-audit", name, "--domain", "ru-macro")
        self.assertEqual(code, 0, out["issues"])

    def test_retro_index_rows_from_model(self):
        name, _ = self._draft("retro-audit")
        payload = {"root": self.root, "draft": name, "kind": "retro-audit", "today": TODAY,
                   "index_rows": {"domains/ru-macro/INDEX.md": {
                       "section": "## Файлы", "rows": ["| [test-bank-2022-2025.md](test-bank-2022-2025.md) | full |"]}}}
        code, out = self._run("retro-audit", name, stdin=json.dumps(payload))
        self.assertEqual(code, 0, out["issues"])
        self.assertEqual(out["index_pending"], [])
        self.assertIn("test-bank-2022-2025.md](test-bank-2022-2025.md) | full |", self._get("domains/ru-macro/INDEX.md"))

    def test_monitor_bullet_newest_first(self):
        name, _ = self._draft("monitor-report")
        code, out = self._run("monitor-report", name)
        self.assertEqual(code, 0, out["issues"])
        idx = self._get("INDEX.md").split("\n")
        i = idx.index("## Активные мониторинговые отчёты")
        self.assertTrue(idx[i + 2].startswith("- `monitor-report-2026-11-04` · 0 HIGH · 0 MEDIUM · 1 LOW"))
        self.assertTrue(idx[i + 3].startswith("- `monitor-report-2026-10-29`"))

    def test_mojibake_blocks(self):
        name, _ = self._draft("stress", {"stress-2026-11-04-test.md": "# Ð¿Ñ€Ð¸Ð²ÐµÑ‚\n"})
        code, out = self._run("stress", name)
        self.assertEqual(code, 1)
        self.assertTrue(any(i["source"] == "encoding" for i in out["issues"]))


if __name__ == "__main__":
    unittest.main(verbosity=1)
