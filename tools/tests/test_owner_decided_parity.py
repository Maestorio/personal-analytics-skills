#!/usr/bin/env python3
"""Сторож паритета правила R24 «владелец решил сам» (decision.md R24, шаг 13 цикла машиночитаемости).

Одно правило в трёх местах:
  * `notifier.owner_decided` (tools/hosting/notify/notifier.py) — уведомление о смене вердикта;
  * `ownerDecided` вьюера (tools/assets/viewer.js) — вкладка «Изменения»;
  * `decision_journal.owner_marked` (skills/portfolio-data-loader/scripts/decision_journal.py) — код `owner_decided`.

Правило: по условию бумаги (любая версия определения с key = бумага) событие `done` с `by: owner` или `owner_mark`
с `data.mark` ∈ {dismissed, deferred}; либо строка журнала плана `stocks|bonds|funds.<бумага>.user_status|user_plan|action`;
всё — в окне (момент прошлого обзора, момент нового]. `plan_pct`, справочные поля плана, `done by: price/site`,
`reopened`, чужая бумага (в том числе ключ-префикс: SBER против SBERP) — не решение владельца.

Тест гоняет три реализации на общих фикстурах (состояние, журнал плана, окна с границами) и требует одного ответа;
затем сверяет ответ с ожидаемым. Сделки обзора (`trades_since_prior`) — только у уведомителя и вьюера, журнал
считает сделки сам — в паритет не входят.

Как грузится JS: `viewer.js` целиком в node не исполняется (DOM, сеть), поэтому функции `_toDateStr`, `_ymd`,
`_mskIso`, `dsIso`, `_ddmmDot`, `_reviewMoment`, `ownerDecided` вырезаются из файла текстом (по сигнатуре
`function <имя>(` с начала строки и балансу фигурных скобок) и исполняются в node с подставленными `state`,
`condDefsAll()` и `condStateDoc()` (те же определения и события, что получают Python-реализации). Часовой пояс node —
Europe/Moscow (пояс владельца в браузере). Самопроверка: мутант вьюера без `deferred` обязан разойтись.

Нужен node; без node — честный пропуск, не зелёный.
Запуск: python3 tools/tests/test_owner_decided_parity.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "_shared-references"))
sys.path.insert(0, str(REPO / "tools/hosting/notify"))
sys.path.insert(0, str(REPO / "skills/portfolio-data-loader/scripts"))

import decision_journal as dj  # noqa: E402
import notifier as N  # noqa: E402

VIEWER = REPO / "tools/assets/viewer.js"
JS_FUNCS = ("_toDateStr", "_ymd", "_mskIso", "dsIso", "_ddmmDot", "_reviewMoment", "ownerDecided")

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}" + (f"\n    → {detail}" if detail else ""))


def js_function(src: str, name: str) -> str:
    """Текст функции верхнего уровня `function name(` до парной закрывающей скобки тела."""
    m = re.search(rf"^function {re.escape(name)}\(", src, re.M)
    if not m:
        raise SystemExit(f"нет function {name}( в viewer.js")
    i = src.index("{", src.index(")", m.end()))
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[m.start():j + 1]
    raise SystemExit(f"не закрыта function {name}")


# ---------------------------------------------------------------- фикстуры
def cdef(cid, key, version=1):
    return {"id": cid, "version": version, "key": key, "kind": "review",
            "trigger": {"type": "date", "value": "2026-12-01"}, "created_at": "2026-08-01T10:00:00+03:00",
            "withdrawn": None}


def ev(cid, event, at, by="owner", data=None):
    return {"condition_id": cid, "event": event, "at": at, "by": by, "data": data or {}}


def jr(path, ts):
    return {"ts": ts, "who": "site", "path": path, "was": None, "now": "x"}


LO = "2026-09-01T09:00:00+03:00"     # момент прошлого обзора (recorded_at)
HI = "2026-09-10T09:00:00+03:00"     # момент нового обзора
IN = "2026-09-05T10:00:00+03:00"

DEFS = [cdef("c-own", "OWN"), cdef("c-prc", "PRC"), cdef("c-site", "SITE"), cdef("c-dis", "DIS"),
        cdef("c-def", "DEF"), cdef("c-reo", "REO"), cdef("c-lo", "LOB"), cdef("c-hi", "HIB"), cdef("c-out", "OUT"),
        cdef("c-v", "VER", 1), cdef("c-v", "VER", 2), cdef("c-oth", "FOO"), cdef("c-fired", "FIR")]
EVENTS = [ev("c-own", "done", IN, data={"note": "сделал"}),
          ev("c-prc", "done", IN, by="price"),
          ev("c-site", "done", IN, by="site", data={"decision_id": "d"}),
          ev("c-dis", "owner_mark", IN, data={"mark": "dismissed"}),
          ev("c-def", "owner_mark", IN, data={"mark": "deferred", "until": "2026-10-01"}),
          ev("c-reo", "reopened", IN),
          ev("c-lo", "done", LO),                                    # ровно в момент прошлого — не в окне
          ev("c-hi", "owner_mark", HI, data={"mark": "dismissed"}),   # ровно в момент нового — в окне
          ev("c-out", "done", "2026-08-20T10:00:00+03:00"),          # до окна
          ev("c-v", "owner_mark", IN, data={"mark": "deferred", "until": "2026-10-01"}),
          ev("c-oth", "done", IN),                                   # условие чужой бумаги
          ev("c-fired", "fired", IN, by="notifier")]
JOURNAL = [jr("stocks.MTSS.user_plan", IN), jr("stocks.STAT.user_status", IN), jr("stocks.PCT.plan_pct", IN),
           jr("stocks.NOTE.note_ai", IN), jr("bonds.RU000A1.action", IN), jr("bonds.RU000A2.rating", IN),
           jr("funds.LQDT.class", IN), jr("funds.TMOS.user_plan", IN), jr("stocks.SBERP.user_plan", IN),
           jr("stocks.EDGE.user_plan", HI), jr("stocks.EDGE0.user_plan", LO),
           jr("stocks.UTC.user_plan", "2026-09-10T05:30:00Z"),        # 08:30 МСК — в окне
           jr("stocks.UTCL.user_plan", "2026-09-10T06:30:00Z"),       # 09:30 МСК — после окна
           jr("stocks.NOTZ.user_plan", "2026-09-10T05:30:00"),        # старая строка без пояса — UTC → 08:30 МСК
           jr("stocks.NOTZL.user_plan", "2026-09-10T07:30:00"),       # без пояса — UTC → 10:30 МСК, после окна
           jr("ie_model.SBER.share", IN), jr("matrix.MTSS.share", IN)]

# (бумага, ожидаемый ответ)
CASES = [("OWN", True), ("PRC", False), ("SITE", False), ("DIS", True), ("DEF", True), ("REO", False),
         ("LOB", False), ("HIB", True), ("OUT", False), ("VER", True), ("BAR", False), ("FIR", False),
         ("MTSS", True), ("STAT", True), ("PCT", False), ("NOTE", False), ("RU000A1", True), ("RU000A2", False),
         ("LQDT", False), ("TMOS", True), ("SBER", False), ("EDGE", True), ("EDGE0", False), ("UTC", True),
         ("UTCL", False), ("NOTZ", True), ("NOTZL", False), ("FOO", True)]
# окна: recorded_at обоих обзоров; только даты (конец дня МСК)
WINDOWS = [("recorded_at", {"review_date": "2026-09-01", "recorded_at": LO}, {"review_date": "2026-09-10", "recorded_at": HI}),
           ("review_date", {"review_date": "2026-08-31"}, {"review_date": "2026-09-04"})]


def py_notifier(key, prev, cur):
    return bool(N.owner_decided(key, cur, {"defs": DEFS, "events": EVENTS, "journal": JOURNAL}, prev))


CTX = dj.owner_context(defs=DEFS, events=EVENTS, journal=JOURNAL)


def py_journal(key, prev, cur):
    def m(r):
        return dj.moment(r["recorded_at"]) if r.get("recorded_at") else dj._day_end(r["review_date"])
    return bool(dj.owner_marked(CTX, key, m(prev), m(cur)))


JS_RUNNER = r"""
const fs = require('fs');
const inp = JSON.parse(fs.readFileSync(0, 'utf8'));
const state = { data: {}, planJournal: { entries: inp.journal } };
function condDefsAll() { return inp.defs; }
function condStateDoc() { return { schema_version: 'conditions-state@1', events: inp.events }; }
eval(inp.code);
const rec = (r) => ({ date: r.review_date, parsed: r });
process.stdout.write(JSON.stringify(inp.queries.map(q => !!ownerDecided(q.key, rec(q.cur), rec(q.prev)))));
"""


def js_answers(code, queries):
    p = subprocess.run(["node", "-e", JS_RUNNER], input=json.dumps(
        {"code": code, "defs": DEFS, "events": EVENTS, "journal": JOURNAL, "queries": queries}),
        capture_output=True, text=True, timeout=60, env={**os.environ, "TZ": "Europe/Moscow"})
    if p.returncode != 0:
        raise SystemExit("node: " + p.stderr[-800:])
    return json.loads(p.stdout)


src = VIEWER.read_text(encoding="utf-8")
code = "\n".join(js_function(src, n) for n in JS_FUNCS)
has_node = shutil.which("node") is not None

print("-- 1. Три реализации на общих фикстурах --")
if not has_node:
    print("  ПРОПУСК: нет node — JS-часть не проверена (не зелёный)")
for wname, prev, cur in WINDOWS:
    queries = [{"key": k, "prev": prev, "cur": cur} for k, _ in CASES]
    js = js_answers(code, queries) if has_node else [None] * len(CASES)
    for (key, want), j in zip(CASES, js):
        n, d = py_notifier(key, prev, cur), py_journal(key, prev, cur)
        if wname == "review_date":
            want = key in ("LOB", "EDGE0")   # окно (31.08 конец дня, 04.09 конец дня]: в нём только моменты 01.09 09:00
        check(f"[{wname}] {key}: уведомитель {n}, журнал {d}, вьюер {j}; ожидается {want}",
              n == d == want and (j is None or j == want))

print("-- 2. Сторожа текста --")
for f, needle in ((REPO / "tools/hosting/notify/notifier.py", "test_owner_decided_parity.py"),
                  (VIEWER, "test_owner_decided_parity.py"),
                  (REPO / "skills/portfolio-data-loader/scripts/decision_journal.py", "test_owner_decided_parity.py")):
    check(f"⚠ SYNC в {f.name} указывает на сторож паритета", needle in f.read_text(encoding="utf-8"))
check("наборы отметок и полей плана у Python-реализаций совпадают",
      tuple(N.OWNER_MARKS) == tuple(dj.OWNER_MARKS) and N.OWNER_PLAN_FIELDS == dj.OWNER_PLAN_FIELDS,
      f"{N.OWNER_MARKS} {dj.OWNER_MARKS} {N.OWNER_PLAN_FIELDS} {dj.OWNER_PLAN_FIELDS}")

print("-- 3. Самопроверка: вьюер без deferred обязан разойтись --")
if has_node:
    mut = code.replace("['dismissed', 'deferred']", "['dismissed']")
    prev, cur = WINDOWS[0][1], WINDOWS[0][2]
    r = js_answers(mut, [{"key": "DEF", "prev": prev, "cur": cur}])
    check("мутант (только dismissed) расходится с Python на DEF", mut != code and r == [False] and py_notifier("DEF", prev, cur))

print(f"\nowner_decided_parity: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
