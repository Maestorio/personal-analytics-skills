#!/usr/bin/env python3
"""Паритет модуля (а) схемы данных: объединение «определение условия + состояние условия».

Две реализации одних правил: `_shared-references/conditions_merge.py` (скрипты скиллов, уведомитель, советник) и
`tools/assets/conditions-merge.js` (`window.CM`, вьюер). Тест:

  1. гоняет обе на одних фикстурах (`tools/data-structures/tests/fixtures/merge_defs.yaml` + `merge_state.json`)
     при нескольких `today` — до дедлайна, в день дедлайна, после окна, после `valid_until` — и требует равенства
     JSON-дампа строк с сортировкой ключей байт в байт; YAML разбирает только Python (строки дат), node получает
     JSON — тест не зависит от JS-парсера YAML;
  2. проверяет на Python-выдаче случаи schema.md §9 (снятое определение с живым состоянием, конфликт версий,
     истёкший срок, `reopened`, `deferred` с `until` в прошлом и будущем, дедлайн `date` в день события,
     `report_published` с `window_end` вчера/сегодня/завтра, `fired` без закрытия, `done` после `fired`,
     `event_found` рядом с `fired`, `owner_mark: dismissed`) — паритет переносит их на JS;
  3. крайние входы вне валидатора (пустые/None, равные версии, `withdrawn: {}`, нет `data`/`by`/`window_end`);
  4. выход миграции `migrate_conditions_v2.py` на `conditions_v12.yaml`: проходит валидаторы, а merge (Python и JS)
     после окна даёт `fired_by_deadline` у `report_published`, остальные — по своим правилам;
  5. сторожа: текст правил 1–13 в докстринге Python = шапке JS; набор обрабатываемых событий и отметок = кодлисты;
     `?v=` у conditions-merge.js в странице = md5[:8] файла, подключён после codelists.js и до движка;
  6. самопроверка: JS с изменённым правилом (дата срабатывает на день позже) обязан разойтись.

Нужен node; без node — честный пропуск, не зелёный.
Запуск: python3 tools/tests/test_conditions_merge_parity.py
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DS = REPO / "tools/data-structures"
sys.path.insert(0, str(REPO / "_shared-references"))
sys.path.insert(0, str(DS / "migrations"))

import codelists  # noqa: E402
import conditions_merge as cm  # noqa: E402
import ds_schemas as ds  # noqa: E402
import migrate_conditions_v2 as mg  # noqa: E402

FIX = DS / "tests/fixtures"
JS = REPO / "tools/assets/conditions-merge.js"
CLJS = REPO / "tools/assets/codelists.js"
HTML = REPO / "tools/portfolio-integrated-viewer.html"

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}" + (f"\n    → {detail}" if detail else ""))


def dump(rows):
    return json.dumps(rows, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


JS_RUNNER = r"""
const fs = require('fs');
const [mod, inPath] = process.argv.slice(1);
const CM = require(mod);
function stable(v) {
  if (Array.isArray(v)) return '[' + v.map(stable).join(',') + ']';
  if (v && typeof v === 'object') return '{' + Object.keys(v).sort().map(k => JSON.stringify(k) + ':' + stable(v[k])).join(',') + '}';
  return JSON.stringify(v === undefined ? null : v);
}
const cases = JSON.parse(fs.readFileSync(inPath, 'utf8'));
const out = cases.map(c => c.select === undefined
  ? stable(CM.merge(c.defs, c.state, c.today))
  : stable(CM.select(CM.merge(c.defs, c.state, c.today), c.select, c.only_active)));
process.stdout.write(JSON.stringify({ out, orphans: CM.orphanEventIds(cases[0].defs, cases[0].state),
  events: CM.HANDLED_EVENTS, marks: CM.HANDLED_MARKS }));
"""


def run_js(cases, mod=JS):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(cases, fh, ensure_ascii=False)
        p = fh.name
    try:
        r = subprocess.run([NODE, "-e", JS_RUNNER, str(mod), p], capture_output=True, text=True, timeout=60)
    finally:
        Path(p).unlink(missing_ok=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:600])
    return json.loads(r.stdout)


def first_diff(a, b):
    i = next((k for k in range(min(len(a), len(b))) if a[k] != b[k]), min(len(a), len(b)))
    return f"с символа {i}: py «{a[max(0, i - 60):i + 60]}» / js «{b[max(0, i - 60):i + 60]}»"


def compare(label, cases, mod=JS):
    """Python и JS на одних входах; возвращает число расхождений."""
    js = run_js(cases, mod)["out"]
    bad = 0
    for c, j in zip(cases, js):
        rows = cm.merge(c["defs"], c["state"], c["today"])
        if "select" in c:
            keys = c["select"] if isinstance(c["select"], list) else ([c["select"]] if c["select"] else None)
            rows = cm.select(rows, keys=keys, only_active=bool(c.get("only_active")))
        py = dump(rows)
        if mod is JS:
            check(f"{label} today={c['today']}{' select=' + str(c['select']) if 'select' in c else ''}: "
                  f"Python = JS ({len(rows)} строк)", py == j, first_diff(py, j))
        bad += py != j
    return bad


# ── входы ──
DEFS = cm.load_yaml(FIX / "merge_defs.yaml")["conditions"]
with open(FIX / "merge_state.json", encoding="utf-8") as f:
    STATE = json.load(f)
# до дедлайна (окно завтра), в день дедлайна (дата сегодня, окно сегодня), после окна (окно вчера), «сегодня» тестов,
# день окончания отсрочки, после valid_until всех pending
TODAYS = ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-30", "2026-11-10", "2026-11-20", "2027-01-01"]

NODE = shutil.which("node")

print("-- 0. Фикстуры проходят валидаторы --")
check("merge_defs.yaml — conditions@2, merge_state.json — conditions-state@1",
      ds.validate_conditions_file({"schema_version": "conditions@2", "conditions": DEFS}) == []
      and ds.validate_conditions_state(STATE) == [])

print("-- 2. Случаи schema.md §9 на выдаче Python --")


def at(today):
    return {r["id"]: r for r in cm.merge(DEFS, STATE, today)}


T = {d: at(d) for d in TODAYS}
r30 = T["2026-10-30"]
CASES = [
    ("снятое определение с живым состоянием: withdrawn, state_status fired, не действует",
     (r30["c-withdrawn"]["status"], r30["c-withdrawn"]["state_status"], r30["c-withdrawn"]["active"]) == ("withdrawn", "fired", False)),
    ("правило 14: fired версии 1, потом новая версия — pending (событие до created_at версии 2 не засчитано)",
     (T["2026-10-19"]["c-multi"]["version"], T["2026-10-19"]["c-multi"]["verdict_now"], T["2026-10-19"]["c-multi"]["status"],
      T["2026-10-19"]["c-multi"]["last_event"]) == (2, "WATCH", "pending", None)),
    ("правило 14: после сброса новая дата версии 2 срабатывает по сроку",
     (r30["c-multi"]["status"], r30["c-multi"]["fired_by_deadline"], r30["c-multi"]["fired_at"])
     == ("fired", True, "2026-10-25T00:00:00+03:00")),
    ("правило 14: fired и done версии 1 сброшены, fired после новой версии засчитан; note несётся",
     (r30["c-multi-after"]["status"], r30["c-multi-after"]["fired_at"], r30["c-multi-after"]["waits_owner"],
      r30["c-multi-after"]["closed_as"], r30["c-multi-after"]["note"])
     == ("fired", "2026-10-15T09:00:00+03:00", True, None, "порог поднят после закрытия первой версии")),
    ("истёкший срок по valid_until: expired, computed, on_expiry отдан",
     (r30["c-expired"]["status"], r30["c-expired"]["computed"], r30["c-expired"]["on_expiry"]["action"]) == ("expired", True, "set_verdict")),
    ("после valid_until: триггер date с наступившей датой срабатывает по сроку (6б раньше 6в), не истекает",
     (T["2027-01-01"]["c-pending"]["status"], T["2027-01-01"]["c-pending"]["fired_by_deadline"]) == ("fired", True)),
    ("после valid_until: ценовой триггер без события — expired по сроку и в любой день после",
     all((T[d]["c-expired"]["status"], T[d]["c-expired"]["computed"]) == ("expired", True) for d in TODAYS)),
    ("expired из событий: done после него не закрывает (остаётся expired)",
     (r30["c-expired-then-done"]["status"], r30["c-expired-then-done"]["closed_as"]) == ("expired", None)),
    ("reopened без новых событий: pending, last_event = reopened",
     (r30["c-reopened"]["status"], r30["c-reopened"]["last_event"]["event"]) == ("pending", "reopened")),
    ("reopened, затем fired: снова ждёт владельца",
     (r30["c-reopened-fired"]["status"], r30["c-reopened-fired"]["waits_owner"]) == ("fired", True)),
    ("deferred с until в будущем: fired, не ждёт владельца до until",
     (r30["c-deferred"]["status"], r30["c-deferred"]["waits_owner"], r30["c-deferred"]["deferred_until"]) == ("fired", False, "2026-11-10")),
    ("deferred: в день until снова ждёт владельца",
     T["2026-11-10"]["c-deferred"]["waits_owner"] is True),
    ("deferred с until в прошлом: ждёт владельца",
     (r30["c-deferred-past"]["waits_owner"], r30["c-deferred-past"]["deferred_until"]) == (True, "2026-10-25")),
    ("deferred ДО fired из событий не действует",
     (r30["c-defer-before-fire"]["waits_owner"], r30["c-defer-before-fire"]["deferred_until"]) == (True, None)),
    ("deferred у fired по сроку — любая отметка; после until ждёт",
     (r30["c-deferred-deadline"]["waits_owner"], T["2026-11-10"]["c-deferred-deadline"]["waits_owner"]) == (False, True)),
    ("дедлайн date в день события: fired_by_deadline, fired_at T00:00; накануне pending",
     (T["2026-10-20"]["c-date-deadline"]["status"], T["2026-10-20"]["c-date-deadline"]["fired_by_deadline"],
      T["2026-10-20"]["c-date-deadline"]["fired_at"], T["2026-10-19"]["c-date-deadline"]["status"])
     == ("fired", True, "2026-10-20T00:00:00+03:00", "pending")),
    ("report_published, window_end завтра — pending",
     T["2026-10-19"]["c-report-passed"]["status"] == "pending"),
    ("report_published, window_end сегодня — pending (окно включает последний день)",
     T["2026-10-20"]["c-report-passed"]["status"] == "pending"),
    ("report_published, window_end вчера — fired_by_deadline, fired_at T23:59:59 дня окна",
     (T["2026-10-21"]["c-report-passed"]["status"], T["2026-10-21"]["c-report-passed"]["fired_by_deadline"],
      T["2026-10-21"]["c-report-passed"]["fired_at"]) == ("fired", True, "2026-10-20T23:59:59+03:00")),
    ("fired без закрытия: действует и ждёт владельца",
     (r30["c-fired"]["active"], r30["c-fired"]["waits_owner"], r30["c-fired"]["computed"]) == (True, True, False)),
    ("done после fired (в файле done раньше): закрыто, closed_as done, fired_at сохранён",
     (r30["c-done"]["status"], r30["c-done"]["closed_as"], r30["c-done"]["fired_at"]) == ("done", "done", "2026-10-20T09:00:00+03:00")),
    ("event_found рядом с fired одной секундой: fired, found_doc, last_event — последнее по файлу (fired)",
     (r30["c-found-fired"]["status"], r30["c-found-fired"]["found_doc"], r30["c-found-fired"]["last_event"]["event"],
      r30["c-found-fired"]["fired_by_deadline"]) == ("fired", "https://example.test/rsbu", "fired", False)),
    ("event_found без fired: статус не меняет",
     (r30["c-found"]["status"], r30["c-found"]["found_at"]) == ("pending", "2026-10-28T09:00:00+03:00")),
    ("owner_mark dismissed: закрыто, closed_as dismissed",
     (r30["c-mark-dismissed"]["status"], r30["c-mark-dismissed"]["closed_as"], r30["c-mark-dismissed"]["active"]) == ("done", "dismissed", False)),
    ("key_kind считается при чтении: ISIN — isin, тикер — ticker",
     (r30["ru000a000aa0-bond"]["key_kind"], r30["c-pending"]["key_kind"]) == ("isin", "ticker")),
    ("событие без определения в выдачу не попадает",
     "c-orphan" not in r30 and cm.orphan_event_ids(DEFS, STATE) == ["c-orphan"]),
]
for name, ok in CASES:
    check(name, ok)

if not NODE:
    print("conditions_merge_parity: пропуск JS-части — нет node (JS-близнец нечем запустить)")
    print(f"\nconditions_merge_parity: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)

print("-- 1. Паритет на фикстурах при нескольких today --")
compare("фикстуры", [{"defs": DEFS, "state": STATE, "today": d} for d in TODAYS])
compare("select", [{"defs": DEFS, "state": STATE, "today": "2026-10-30", "select": "FFFF"},
                   {"defs": DEFS, "state": STATE, "today": "2026-10-30", "select": ["AAAA", "BBBB"], "only_active": True},
                   {"defs": DEFS, "state": STATE, "today": "2026-10-30", "select": None, "only_active": True}])
js_meta = run_js([{"defs": DEFS, "state": STATE, "today": "2026-10-30"}])
check("orphanEventIds = orphan_event_ids", js_meta["orphans"] == cm.orphan_event_ids(DEFS, STATE), js_meta["orphans"])

print("-- 3. Крайние входы вне валидатора --")
base = {"id": "x", "version": 1, "key": "ZZZZ", "kind": "review", "trigger": {"type": "date", "value": "2026-10-20"},
        "while_pending": {"verdict": "HOLD"}, "on_trigger": {"action": "run_analysis", "text": "т"},
        "withdrawn": None}
eq_ver = [dict(base, on_trigger={"action": "run_analysis", "text": "первое"}),
          dict(base, on_trigger={"action": "run_analysis", "text": "второе"})]
edge = [
    {"defs": None, "state": None, "today": "2026-10-30"},
    {"defs": [], "state": {"events": None}, "today": "2026-10-30"},
    {"defs": eq_ver, "state": {}, "today": "2026-10-10"},
    {"defs": [dict(base, withdrawn={})], "state": {"events": []}, "today": "2026-10-10"},
    {"defs": [dict(base, trigger=None, on_trigger=None, while_pending=None, valid_until="2026-10-01")], "state": None,
     "today": "2026-10-30"},
    {"defs": [dict(base, trigger={"type": "report_published", "value": "отчёт"}, valid_until="2026-10-25")],
     "state": None, "today": "2026-10-30"},
    {"defs": [dict(base, trigger={"type": "date", "value": ""})], "state": None, "today": "2026-10-30"},
    {"defs": [base], "state": {"events": [
        {"condition_id": "x", "event": "owner_mark", "at": "2026-10-21T09:00:00+03:00"},
        {"condition_id": "x", "event": "fired", "at": "2026-10-20T09:00:00+03:00", "data": None},
        {"condition_id": "x", "event": "owner_mark", "at": "2026-10-22T09:00:00+03:00", "data": {"mark": "deferred"}},
        {"condition_id": "x", "event": "event_found", "at": "2026-10-22T09:00:00+03:00", "by": "monitor", "data": {}}]},
     "today": "2026-10-30"},
    {"defs": [dict(base, key="RU000A000AA0\n"), dict(base, id="y", key="RU000A000AA0")], "state": None, "today": "2026-10-30"},
    # правило 14: created_at последней версии — граница (равное время засчитано), пустой created_at — все события
    {"defs": [dict(base, trigger={"type": "price_above", "value": 1}, created_at="2026-10-20T09:00:00+03:00", note="н")],
     "state": {"events": [
        {"condition_id": "x", "event": "done", "at": "2026-10-19T09:00:00+03:00", "data": {"note": "до"}},
        {"condition_id": "x", "event": "fired", "at": "2026-10-20T09:00:00+03:00"}]}, "today": "2026-10-30"},
    {"defs": [dict(base, trigger={"type": "price_above", "value": 1}, created_at="")],
     "state": {"events": [{"condition_id": "x", "event": "fired", "at": "2026-10-19T09:00:00+03:00"}]}, "today": "2026-10-30"},
]
compare("крайние", edge)
check("правило 14: событие в момент created_at засчитано, раньше — нет; без created_at — все",
      (cm.merge(edge[-2]["defs"], edge[-2]["state"], "2026-10-30")[0]["status"],
       cm.merge(edge[-1]["defs"], edge[-1]["state"], "2026-10-30")[0]["status"]) == ("fired", "fired"))
check("равные version: остаётся первое по файлу", cm.merge(eq_ver, {}, "2026-10-10")[0]["text"] == "первое")
# правило 5 (R32): event_found от владельца (кнопка «вышел») — pending -> fired; после «сделал» и от монитора — нет
rep = dict(base, trigger={"type": "report_published", "value": "РСБУ", "window_end": "2026-11-06"})
EVF = {"condition_id": "x", "event": "event_found", "at": "2026-11-03T10:00:00+03:00", "by": "owner", "data": {}}
ev5 = [
    {"defs": [rep], "state": {"events": [EVF]}, "today": "2026-11-03"},
    {"defs": [rep], "state": {"events": [dict(EVF, by="monitor")]}, "today": "2026-11-03"},
    {"defs": [rep], "state": {"events": [{"condition_id": "x", "event": "done", "at": "2026-11-02T10:00:00+03:00",
                                          "by": "owner"}, EVF]}, "today": "2026-11-03"},
]
compare("event_found от владельца", ev5)
_o, _m, _d = (cm.merge(c["defs"], c["state"], c["today"])[0] for c in ev5)
check("правило 5: event_found от владельца — сработало, ждёт владельца, fired_at = время отметки, не по сроку",
      (_o["status"], _o["waits_owner"], _o["fired_at"], _o["found_at"], _o["fired_by_deadline"])
      == ("fired", True, "2026-11-03T10:00:00+03:00", "2026-11-03T10:00:00+03:00", False))
check("правило 5: event_found от монитора статус не меняет; после «сделал» — тоже",
      (_m["status"], _d["status"]) == ("pending", "done"))
check("ISIN с переводом строки — не isin (fullmatch, как JS /^…$/)",
      cm.key_kind("RU000A000AA0\n") == "ticker" and cm.key_kind("RU000A000AA0") == "isin")

print("-- 4. Выход миграции conditions@1.2 → @2 --")
with tempfile.TemporaryDirectory() as t:
    with redirect_stdout(StringIO()):
        code = mg.main(["--in", str(FIX / "conditions_v12.yaml"), "--out", t])
    mdefs = cm.load_yaml(Path(t) / "conditions.yaml")
    with open(Path(t) / "conditions-state.json", encoding="utf-8") as f:
        mstate = json.load(f)
check("миграция записала файлы, определения и состояние проходят валидаторы",
      code == 0 and ds.validate_conditions_file(mdefs) == [] and ds.validate_conditions_state(mstate) == [],
      ds.validate_conditions_file(mdefs)[:3] + ds.validate_conditions_state(mstate)[:3])
mc = mdefs["conditions"]
reports = [c for c in mc if c["trigger"]["type"] == "report_published"]
check("в выходе миграции есть report_published с window_end", bool(reports) and all(c["trigger"].get("window_end") for c in reports))
if reports:
    we = min(c["trigger"]["window_end"] for c in reports)
    from datetime import date, timedelta
    after = (date.fromisoformat(we) + timedelta(days=1)).isoformat()
    compare("миграция", [{"defs": mc, "state": mstate, "today": we}, {"defs": mc, "state": mstate, "today": after}])
    on_day = {r["id"]: r for r in cm.merge(mc, mstate, we)}
    nxt = {r["id"]: r for r in cm.merge(mc, mstate, after)}
    rep_ids = {c["id"] for c in reports if c["trigger"]["window_end"] == we}
    check("правило 14 не отбрасывает событий миграции: каждое не раньше created_at последней версии",
      all(len(cm.events_since([e for e in mstate["events"] if e["condition_id"] == c["id"]], c["created_at"]))
          == sum(1 for e in mstate["events"] if e["condition_id"] == c["id"]) for c in mc))
    check(f"в день окна ({we}) report_published ещё pending, на следующий — fired_by_deadline",
          all(on_day[i]["status"] == "pending" for i in rep_ids)
          and all((nxt[i]["status"], nxt[i]["fired_by_deadline"], nxt[i]["computed"]) == ("fired", True, True) for i in rep_ids))
    # остальные: без событий и без наступившей даты — обычный pending; date с наступившей датой — fired по сроку (правило 6б)
    others = [c for c in mc if c["id"] not in rep_ids]
    no_ev = {e["condition_id"] for e in mstate["events"]}
    plain = [c["id"] for c in others if c["id"] not in no_ev and not (c["trigger"]["type"] == "date" and c["trigger"]["value"] <= after)]
    check(f"остальные без событий и без наступившей даты — обычный pending ({', '.join(plain)})",
          bool(plain) and all((nxt[i]["status"], nxt[i]["fired_by_deadline"], nxt[i]["computed"]) == ("pending", False, False) for i in plain))
    check("fired_by_deadline у остальных — только от триггера date (окно отчётности их не трогает)",
          all(next(c for c in mc if c["id"] == i)["trigger"]["type"] == "date" for i in nxt
              if i not in rep_ids and nxt[i]["fired_by_deadline"]))

print("-- 5. Сторожа --")
src_py = (REPO / "_shared-references/conditions_merge.py").read_text(encoding="utf-8")
src_js = JS.read_text(encoding="utf-8")
HEAD = "ПРАВИЛА (спецификация для JS)"
py_rules = src_py[src_py.index(HEAD):src_py.index("CLI (заготовка")].rstrip()
js_head = src_js[:src_js.index("*/")]
js_rules = "\n".join(l[3:] if l.startswith(" * ") else l[2:] for l in js_head[js_head.index(HEAD) - 3:].splitlines()).rstrip()
check("текст правил 1–14: докстринг Python = шапка JS", py_rules == js_rules and "14. " in py_rules,
      first_diff(py_rules, js_rules))
ev = codelists.codes("condition_event", legacy=False)
mk = codelists.codes("owner_mark", legacy=False)
check("обрабатываемые события и отметки = кодлисты condition_event и owner_mark (Python и JS)",
      set(cm.HANDLED_EVENTS) == set(ev) and set(cm.HANDLED_MARKS) == set(mk)
      and set(js_meta["events"]) == set(ev) and set(js_meta["marks"]) == set(mk),
      f"кодлист {ev} / {mk}; Python {cm.HANDLED_EVENTS}; JS {js_meta['events']}")
html = HTML.read_text(encoding="utf-8")
md5 = hashlib.md5(JS.read_bytes()).hexdigest()[:8]
pos = [html.find("assets/codelists.js?v="), html.find(f"assets/conditions-merge.js?v={md5}\""),
       html.find("assets/rebalance-engine.js?v=")]
check("вьюер подключает conditions-merge.js?v=<md5[:8]> после codelists.js и до движка",
      0 <= pos[0] < pos[1] < pos[2],
      f"<script src=\"assets/conditions-merge.js?v={md5}\"></script> между codelists.js и rebalance-engine.js")
check("JS-близнец без DOM и сети", not any(x in src_js for x in ("document.", "fetch(", "XMLHttpRequest", "localStorage")))

print("-- 6. Самопроверка: изменённое правило в JS обязано разойтись --")
with tempfile.TemporaryDirectory() as t:
    shutil.copy(CLJS, Path(t) / "codelists.js")
    mut = src_js.replace("trigger.value <= today", "trigger.value < today")
    (Path(t) / "conditions-merge.js").write_text(mut, encoding="utf-8")
    bad = compare("мутант", [{"defs": DEFS, "state": STATE, "today": "2026-10-20"}], mod=Path(t) / "conditions-merge.js")
    check("JS с «дата срабатывает на день позже» расходится с Python", mut != src_js and bad == 1)
    mut2 = src_js.replace('if (get(e, "by") === BY_OWNER && status === PENDING) { status = FIRED; firedAt = e.at; }', '')
    (Path(t) / "conditions-merge.js").write_text(mut2, encoding="utf-8")
    bad2 = compare("мутант 5", [ev5[0]], mod=Path(t) / "conditions-merge.js")
    check("JS без «event_found от владельца = сработало» расходится с Python", mut2 != src_js and bad2 == 1)

print(f"\nconditions_merge_parity: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
