#!/usr/bin/env python3
"""
Состояние условий в hub-api (шаг 4 цикла машиночитаемости, schema.md §3.3): файл
`Portfolio/conditions-state.json` (`conditions-state@1`), только дописывание событий.

Что держит тест (временный корень, живой сервер на эфемерном порту, File Station не настроен):
  - первое событие создаёт файл, следующие дописываются в конец; `at` ставит сервер, с поясом `+03:00`;
  - сайт (`/api/pv/cond/event`): owner_mark (dismissed/deferred; у deferred обязателен until), done (by: owner),
    reopened; чужие события (fired…), неизвестные event/mark, пустой condition_id → 400 с причиной;
  - кнопка «вышел» (R32): event_found от владельца — только у ждущего условия с триггером report_published/event
    (последняя версия в conditions.yaml, построчное чтение без PyYAML); датное, прошедшее окно, снятое, неизвестное,
    устаревшая версия, уже сработавшее → 400 без записи; после reopened — снова; fired уведомителя после — дубль;
  - внутренний маршрут: fired/expired/event_found/done(by: decision с decision_id — решение; by: site с decision_id|trade_date — сделка; иной by → 400); by из кодлиста actor;
  - защита от дублей внутреннего маршрута (`_cstate_dup`, шаг 7): для пары id+version повтор незакрытого fired,
    любое событие после терминального (done, dismissed, expired), повтор expired/done, event_found с тем же doc —
    200 {"duplicate": true}, без записи; после reopened цепочка с нуля; версии считаются раздельно;
  - GET /api/pv/cond/state: все события и фильтр since=; без Authorization — 403;
  - удалённые маршруты GET /api/pv/cond и POST /api/pv/cond/save отвечают 404;
  - pv_scan видит conditions-state.json, conditions-archive-ГГГГ.yaml, security-attrs.json и Portfolio/decisions/;
  - две записи подряд: оба события в файле, доставка в зеркало (фоновый носитель) идёт по актуальному содержимому.

Запуск:  python3 tools/tests/test_cond_state_api.py      Только stdlib.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pages_stand import serve  # noqa: E402  (стенд — _pages_stand, keep-alive)
sys.path.insert(0, str(REPO / "tools/hosting/api"))

import server  # noqa: E402
sys.path.insert(0, str(REPO / "_shared-references"))
import ds_schemas  # noqa: E402

passed = failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}")


tmp = tempfile.mkdtemp(prefix="hub-api-cstate-")
try:
    root = Path(tmp)
    server.ROOT = tmp
    httpd = serve(server.Handler, quiet=False)[0]   # _pages_stand: очередь 128, keep-alive
    BASE = f"http://127.0.0.1:{httpd.server_address[1]}"

    def call(method, url, body=None, auth=True):
        data = json.dumps(body).encode() if body is not None else None
        h = {"Content-Type": "application/json", **({"Authorization": "Basic eA=="} if auth else {})}
        rq = urllib.request.Request(BASE + url, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(rq) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    SITE, INT = "/api/pv/cond/event", "/api/pv/cond/event/internal"
    F = root / "Portfolio/conditions-state.json"

    def disk():
        return json.loads(F.read_text(encoding="utf-8"))

    def wait_idle():
        t_end = time.time() + 5
        while time.time() < t_end and server._cstate_state["running"]:
            time.sleep(0.02)
        return not server._cstate_state["running"]

    print("cond-state: запись")
    st, b = call("GET", "/api/pv/cond/state")
    check(f"файла нет → GET 200, events пуст ({st})", st == 200 and b["events"] == [] and not F.exists())
    st, b = call("POST", SITE, {"condition_id": "c-a", "event": "owner_mark", "data": {"mark": "dismissed"}})
    check(f"первое событие создаёт файл ({st})", st == 200 and b["events"] == 1 and F.exists())
    ev = b["event"]
    check("событие: condition_id, event, by=owner, data; at с поясом +03:00",
          ev["condition_id"] == "c-a" and ev["event"] == "owner_mark" and ev["by"] == "owner"
          and ev["data"] == {"mark": "dismissed"} and ev["at"].endswith("+03:00") and len(ev["at"]) == 25)
    d = disk()
    check("файл: schema_version и events[0] = ответу", d["schema_version"] == "conditions-state@1" and d["events"] == [ev])
    st, b = call("POST", SITE, {"condition_id": "c-b", "event": "done", "data": {"note": "сделал"}})
    check(f"done с сайта: by=owner, дописано в конец ({st})", st == 200 and b["events"] == 2 and b["event"]["by"] == "owner"
          and disk()["events"][0] == ev and disk()["events"][1]["condition_id"] == "c-b")
    st, b = call("POST", SITE, {"condition_id": "c-b", "event": "reopened", "version": 2})
    check(f"reopened с версией ({st})", st == 200 and b["event"]["version"] == 2 and b["events"] == 3)
    st, b = call("POST", SITE, {"condition_id": "c-c", "event": "owner_mark", "data": {"mark": "deferred", "until": "2026-12-01"}})
    check(f"deferred с until ({st})", st == 200 and b["event"]["data"]["until"] == "2026-12-01")
    # паритет с кнопкой «сделал» (viewer.js condOwnerButtons шлёт done без data): что принял сайт-маршрут,
    # проходит схему ds_schemas — иначе падают digest и apply_condition на всём файле состояния
    st, b = call("POST", SITE, {"condition_id": "c-own", "event": "done"})
    errs = ds_schemas.validate_conditions_state({"schema_version": "conditions-state@1", "events": [b.get("event")]})
    check(f"done кнопкой без data → 200 и проходит ds_schemas ({st}, {errs})", st == 200 and not errs)
    check("в событиях нет version, когда не задана", "version" not in disk()["events"][1])

    print("cond-state: отказы сайта")
    n = len(disk()["events"])
    bad = {
        "deferred без until": {"condition_id": "c", "event": "owner_mark", "data": {"mark": "deferred"}},
        "deferred с кривой датой": {"condition_id": "c", "event": "owner_mark", "data": {"mark": "deferred", "until": "завтра"}},
        "неизвестный mark": {"condition_id": "c", "event": "owner_mark", "data": {"mark": "later"}},
        "owner_mark без mark": {"condition_id": "c", "event": "owner_mark"},
        "неизвестный event": {"condition_id": "c", "event": "exploded"},
        "fired с сайта": {"condition_id": "c", "event": "fired", "data": {"price": 1}},
        "expired с сайта": {"condition_id": "c", "event": "expired"},
        "event_found с сайта у неизвестного условия": {"condition_id": "c", "event": "event_found"},
        "пустой condition_id": {"condition_id": " ", "event": "done"},
        "нет condition_id": {"event": "done"},
        "data не объект": {"condition_id": "c", "event": "done", "data": [1]},
        "version не целое": {"condition_id": "c", "event": "done", "version": "2"},
    }
    for name, body in bad.items():
        st, b = call("POST", SITE, body)
        check(f"{name} → 400 с причиной ({st})", st == 400 and b.get("message"))
    st, b = call("POST", SITE, {"condition_id": "c", "event": "done", "by": "notifier"})
    check("by из тела на сайтовом маршруте игнорируется (всегда owner)", st == 200 and b["event"]["by"] == "owner")
    check("после отказов файл не тронут (+1 только от последнего успеха)", len(disk()["events"]) == n + 1)
    st, _ = call("POST", SITE, {"condition_id": "c", "event": "done"}, auth=False)
    check(f"без Authorization → 403 ({st})", st == 403)
    # отказ до чтения тела: сервер дочитывает тело и только потом отвечает — иначе при большом теле клиент видит
    # обрыв соединения (RemoteDisconnected) вместо 403 (моргание этого теста до 04.11)
    big = {"condition_id": "c", "event": "done", "note": "x" * 1_500_000}
    st, _ = call("POST", SITE, big, auth=False)
    check(f"без Authorization при теле 1,5 МБ → 403, не обрыв ({st})", st == 403)

    print("cond-state: внутренний маршрут и дубли fired")
    st, b = call("POST", INT, {"condition_id": "c-p", "event": "fired", "by": "notifier", "data": {"price": 1207}})
    check(f"internal: fired by notifier ({st})", st == 200 and b["event"]["by"] == "notifier" and b["event"]["data"] == {"price": 1207})
    n = len(disk()["events"])
    st, b = call("POST", INT, {"condition_id": "c-p", "event": "fired", "by": "notifier", "data": {"price": 1250}})
    check(f"повтор незакрытого fired → 200 duplicate без записи ({st})", st == 200 and b.get("duplicate") is True
          and len(disk()["events"]) == n)
    st, b = call("POST", INT, {"condition_id": "c-p", "version": 2, "event": "fired", "by": "notifier"})
    check("другая версия условия — своя цепочка, пишется", st == 200 and "duplicate" not in b)
    for closer, body in (
            ("done", {"event": "done", "by": "site", "data": {"decision_id": "2026-10-29T1740-GMKN"}}),
            ("dismissed", None), ("expired", {"event": "expired", "by": "notifier"}), ("reopened", None)):
        cid = f"c-{closer}"
        call("POST", INT, {"condition_id": cid, "event": "fired", "by": "notifier"})
        if closer == "dismissed":
            call("POST", SITE, {"condition_id": cid, "event": "owner_mark", "data": {"mark": "dismissed"}})
        elif closer == "reopened":
            call("POST", SITE, {"condition_id": cid, "event": "reopened"})
        else:
            call("POST", INT, {"condition_id": cid, **body})
        st, b = call("POST", INT, {"condition_id": cid, "event": "fired", "by": "notifier"})
        if closer == "reopened":
            check(f"после reopened fired снова пишется ({st})", st == 200 and "duplicate" not in b)
        else:
            check(f"после терминального {closer} fired — дубль без записи ({st})", st == 200 and b.get("duplicate") is True)
    call("POST", SITE, {"condition_id": "c-def", "event": "owner_mark", "data": {"mark": "deferred", "until": "2026-12-01"}})
    call("POST", INT, {"condition_id": "c-def", "event": "fired", "by": "notifier"})
    st, b = call("POST", INT, {"condition_id": "c-def", "event": "fired", "by": "notifier"})
    check("deferred не закрывает fired — повтор остаётся дублем", b.get("duplicate") is True)

    print("cond-state: дубли expired, done, event_found (уведомитель и задачи NAS шлют их на каждом проходе)")
    n = len(disk()["events"])
    st, b = call("POST", INT, {"condition_id": "c-exp", "version": 1, "event": "expired", "by": "notifier"})
    check(f"первый expired пишется ({st})", st == 200 and "duplicate" not in b and len(disk()["events"]) == n + 1)
    st, b = call("POST", INT, {"condition_id": "c-exp", "version": 1, "event": "expired", "by": "notifier"})
    check("повтор expired той же версии — дубль без записи", b.get("duplicate") is True and len(disk()["events"]) == n + 1)
    st, b = call("POST", INT, {"condition_id": "c-exp", "version": 1, "event": "fired", "by": "notifier"})
    check("fired после expired той же версии — дубль (состояние терминально)", b.get("duplicate") is True)
    st, b = call("POST", INT, {"condition_id": "c-exp", "version": 2, "event": "expired", "by": "notifier"})
    check("expired другой версии — пишется (правило 14: новая версия — новое состояние)", st == 200 and "duplicate" not in b)
    call("POST", INT, {"condition_id": "c-dn", "version": 1, "event": "fired", "by": "notifier"})
    st, b = call("POST", INT, {"condition_id": "c-dn", "version": 1, "event": "done", "by": "site", "data": {"decision_id": "d1"}})
    check("done по решению пишется", st == 200 and "duplicate" not in b)
    st, b = call("POST", INT, {"condition_id": "c-dn", "version": 1, "event": "done", "by": "site", "data": {"decision_id": "d2"}})
    check("второй done той же версии — дубль", b.get("duplicate") is True)
    st, b = call("POST", INT, {"condition_id": "c-dd", "version": 1, "event": "done", "by": "decision", "data": {"decision_id": "d3"}})
    check(f"done by: decision с decision_id → 200, by записан ({st})", st == 200 and b["event"]["by"] == "decision"
          and disk()["events"][-1]["by"] == "decision")
    n = len(disk()["events"])
    st, b = call("POST", INT, {"condition_id": "c-dd2", "version": 1, "event": "done", "by": "decision", "data": {"trade_date": "2026-10-29"}})
    check(f"done by: decision без decision_id → 400 без записи ({st})", st == 400 and len(disk()["events"]) == n)
    st, b = call("POST", INT, {"condition_id": "c-dd2", "version": 1, "event": "done", "by": "notifier", "data": {"decision_id": "d4"}})
    check(f"done by: notifier → 400 без записи ({st})", st == 400 and len(disk()["events"]) == n)
    st, b = call("POST", INT, {"condition_id": "c-dd3", "version": 1, "event": "done", "by": "site", "data": {"trade_date": "2026-10-29"}})
    check(f"done by: site с trade_date → 200 ({st})", st == 200 and b["event"]["by"] == "site")
    st, b = call("POST", INT, {"condition_id": "c-dn", "version": 1, "event": "expired", "by": "notifier"})
    check("expired после done — дубль", b.get("duplicate") is True)
    n = len(disk()["events"])
    st, b = call("POST", INT, {"condition_id": "c-ef", "version": 1, "event": "event_found", "by": "site", "data": {"doc": "https://x/1"}})
    st2, b2 = call("POST", INT, {"condition_id": "c-ef", "version": 1, "event": "event_found", "by": "site", "data": {"doc": "https://x/1"}})
    st3, b3 = call("POST", INT, {"condition_id": "c-ef", "version": 1, "event": "event_found", "by": "site", "data": {"doc": "https://x/2"}})
    check("event_found: тот же doc — дубль, другой doc — пишется",
          "duplicate" not in b and b2.get("duplicate") is True and "duplicate" not in b3 and len(disk()["events"]) == n + 2)
    call("POST", SITE, {"condition_id": "c-ef", "version": 1, "event": "owner_mark", "data": {"mark": "dismissed"}})
    st, b = call("POST", INT, {"condition_id": "c-ef", "version": 1, "event": "event_found", "by": "site", "data": {"doc": "https://x/3"}})
    check("event_found после dismissed той же версии — дубль", b.get("duplicate") is True)
    call("POST", SITE, {"condition_id": "c-ef", "version": 1, "event": "reopened"})
    st, b = call("POST", INT, {"condition_id": "c-ef", "version": 1, "event": "event_found", "by": "site", "data": {"doc": "https://x/1"}})
    check("после reopened находка с прежним doc пишется снова (цепочка с нуля)", st == 200 and "duplicate" not in b)
    check("_cstate_dup: без событий — не дубль ни для одного события",
          not any(server._cstate_dup([], "z", 1, e) for e in ("fired", "expired", "done", "event_found")))

    print("cond-state: ограничения внутреннего маршрута")
    for name, body in {
        "owner_mark по внутреннему": {"condition_id": "c", "event": "owner_mark", "data": {"mark": "dismissed"}},
        "reopened по внутреннему": {"condition_id": "c", "event": "reopened"},
        "by вне списка": {"condition_id": "c", "event": "fired", "by": "owner"},
        "by неизвестный": {"condition_id": "c", "event": "fired", "by": "кто-то"},
        "done без decision_id/trade_date": {"condition_id": "c", "event": "done", "by": "site"},
        "done by notifier": {"condition_id": "c", "event": "done", "by": "notifier", "data": {"trade_date": "2026-10-30"}},
    }.items():
        st, b = call("POST", INT, body)
        check(f"{name} → 400 ({st})", st == 400)
    st, b = call("POST", INT, {"condition_id": "c-t", "event": "done", "data": {"trade_date": "2026-10-30"}})
    check("done по сделке: by по умолчанию site", st == 200 and b["event"]["by"] == "site")
    st, b = call("POST", INT, {"condition_id": "c-m", "event": "event_found", "by": "script", "data": {"doc": "x.md"}})
    check("event_found by script", st == 200 and b["event"]["by"] == "script")

    print("cond-state: кнопка «вышел» — event_found владельца (R32)")
    (root / "Portfolio").mkdir(parents=True, exist_ok=True)
    (root / "Portfolio/conditions.yaml").write_text("""schema_version: conditions@2
conditions:
- id: r-lsng
  version: 1
  key: LSNG
  trigger:
    type: report_published
    value: РСБУ 9М
    window_end: '2999-11-06'
  note: 'старая версия'
  created_at: '2026-10-01T10:00:00+03:00'
  withdrawn: null
- id: r-lsng
  version: 2
  key: LSNG
  kind: review
  trigger:
    type: report_published
    value: 'РСБУ 9М: выручка'
    window_end: '2999-11-06'
  on_trigger:
    action: run_analysis
    text: >-
      длинный текст
      type: date
  created_at: '2026-11-01T10:00:00+03:00'
  withdrawn: null
- id: r-ev
  version: 1
  trigger:
    type: event
    value: ГОСА
  created_at: '2026-11-01T10:00:00+03:00'
  withdrawn: null
- id: r-date
  version: 1
  trigger:
    type: date
    value: '2999-01-01'
  withdrawn: null
- id: r-past
  version: 1
  trigger:
    type: report_published
    window_end: '2026-01-10'
  withdrawn: null
- id: r-wd
  version: 1
  trigger:
    type: report_published
    window_end: '2999-11-06'
  withdrawn:
    at: '2026-11-02T10:00:00+03:00'
    by: owner
    reason: не нужно
""", encoding="utf-8")
    brief = server.cond_def_brief((root / "Portfolio/conditions.yaml").read_text(encoding="utf-8"), "r-lsng")
    check("построчное чтение определения: последняя версия, тип, окно, created_at; текст не путается с триггером",
          brief and (brief["version"], brief["type"], brief["window_end"], brief["created_at"], brief["withdrawn"])
          == (2, "report_published", "2999-11-06", "2026-11-01T10:00:00+03:00", False))
    check("построчное чтение: снятое — withdrawn true",
          server.cond_def_brief((root / "Portfolio/conditions.yaml").read_text(encoding="utf-8"), "r-wd")["withdrawn"] is True)
    st, b = call("POST", SITE, {"condition_id": "r-lsng", "version": 2, "event": "event_found", "data": {"note": "РСБУ 02.11"}})
    check(f"«вышел» у ждущего report_published: пишется by=owner ({st})",
          st == 200 and b["event"]["event"] == "event_found" and b["event"]["by"] == "owner"
          and b["event"]["data"] == {"note": "РСБУ 02.11"})
    st, b = call("POST", SITE, {"condition_id": "r-ev", "event": "event_found"})
    check(f"«вышел» у триггера event без data и version — пишется ({st})", st == 200)
    n = len(disk()["events"])
    for name, body in {
        "повтор «вышел» (уже сработало)": {"condition_id": "r-lsng", "version": 2, "event": "event_found"},
        "датное условие": {"condition_id": "r-date", "event": "event_found"},
        "окно прошло (сработало по сроку)": {"condition_id": "r-past", "event": "event_found"},
        "снятое условие": {"condition_id": "r-wd", "event": "event_found"},
        "неизвестное условие": {"condition_id": "r-nope", "event": "event_found"},
        "устаревшая версия": {"condition_id": "r-lsng", "version": 1, "event": "event_found"},
    }.items():
        st, b = call("POST", SITE, body)
        check(f"«вышел»: {name} → 400 с причиной ({st})", st == 400 and b.get("message"))
    check("после отказов «вышел» файл не тронут", len(disk()["events"]) == n)
    call("POST", SITE, {"condition_id": "r-lsng", "version": 2, "event": "reopened"})
    st, b = call("POST", SITE, {"condition_id": "r-lsng", "version": 2, "event": "event_found"})
    check(f"после «открыть заново» «вышел» снова пишется ({st})", st == 200)
    st, b = call("POST", INT, {"condition_id": "r-lsng", "version": 2, "event": "fired", "by": "notifier"})
    check("fired уведомителя после «вышел» владельца — дубль (уже сработало)", b.get("duplicate") is True)

    print("cond-state: всё принятое сервером проходит ds_schemas (паритет hub-api ↔ валидатор digest/apply_condition)")
    evs = disk()["events"]
    errs = ds_schemas.validate_conditions_state(disk())
    check(f"файл состояния после всех принятых событий — 0 ошибок ds_schemas ({len(evs)} событий; {errs[:3]})", not errs)
    kinds = {(e["event"], e["by"], (e.get("data") or {}).get("mark")) for e in evs}
    need = {("owner_mark", "owner", "dismissed"), ("owner_mark", "owner", "deferred"), ("done", "owner", None),
            ("reopened", "owner", None), ("event_found", "owner", None),
            ("fired", "notifier", None), ("expired", "notifier", None), ("done", "site", None),
            ("event_found", "site", None), ("event_found", "script", None)}
    check(f"паритет покрывает все события обоих маршрутов (нет: {sorted(map(str, need - kinds))})", need <= kinds)
    for (event, by, mark) in sorted(need, key=str):
        one = [e for e in evs if (e["event"], e["by"], (e.get("data") or {}).get("mark")) == (event, by, mark)][:1]
        errs = ds_schemas.validate_conditions_state({"schema_version": "conditions-state@1", "events": one})
        check(f"  {event} by {by}{' ' + mark if mark else ''}: проходит схему", one and not errs)

    print("cond-state: чтение since=")
    st, b = call("GET", "/api/pv/cond/state")
    allev = b["events"]
    check(f"GET без since — все события, как в файле ({st})", st == 200 and allev == disk()["events"] and len(allev) > 10)
    cut = allev[3]["at"]
    st, b = call("GET", "/api/pv/cond/state?since=" + cut.replace("+", "%2B"))
    check("since: только at > since", all(e["at"] > cut for e in b["events"]))
    st, b = call("GET", "/api/pv/cond/state?since=2999-01-01T00:00:00%2B03:00")
    check("since в будущем → пусто", b["events"] == [])
    st, _ = call("GET", "/api/pv/cond/state", auth=False)
    check(f"GET без Authorization → 403 ({st})", st == 403)

    print("cond-state: две записи подряд, доставка")
    wait_idle()
    before = len(disk()["events"])
    call("POST", SITE, {"condition_id": "c-x1", "event": "done"})
    call("POST", SITE, {"condition_id": "c-x2", "event": "done"})
    ids = [e["condition_id"] for e in disk()["events"]]
    check("оба события в файле, порядок сохранён", ids[-2:] == ["c-x1", "c-x2"] and len(ids) == before + 2)
    check("носитель отпущен после доставки", wait_idle())
    check("после доставки файл тот же (оба события)", [e["condition_id"] for e in disk()["events"]][-2:] == ["c-x1", "c-x2"])
    # запись во время «переноса»: база — содержимое в памяти, а не файл
    gate = threading.Event()
    real_place = server._place

    def slow_place(r, rel, full, data):
        gate.wait(3)
        return real_place(r, rel, full, data)

    server._place = slow_place
    try:
        call("POST", SITE, {"condition_id": "c-y1", "event": "done"})
        call("POST", SITE, {"condition_id": "c-y2", "event": "done"})
        call("POST", SITE, {"condition_id": "c-y3", "event": "done"})
        gate.set()
        wait_idle()
    finally:
        server._place = real_place
    ids = [e["condition_id"] for e in disk()["events"]]
    check("три записи во время переноса — ни одна не потеряна", ids[-3:] == ["c-y1", "c-y2", "c-y3"])

    print("cond-state: битый файл не затирается")
    (root / "Portfolio/conditions-state.json").write_text("{не json", encoding="utf-8")
    st, b = call("POST", SITE, {"condition_id": "c", "event": "done"})
    check(f"битый файл → 500, содержимое не тронуто ({st})", st == 500 and F.read_text(encoding="utf-8") == "{не json")
    F.unlink()

    print("удалённые маршруты и sync")
    st, _ = call("GET", "/api/pv/cond")
    check(f"GET /api/pv/cond → 404 ({st})", st == 404)
    st, _ = call("POST", "/api/pv/cond/save", {"content": "schema_version: conditions@1\nconditions:\n", "base_hash": "x"})
    check(f"POST /api/pv/cond/save → 404 ({st})", st == 404)
    check("health: pv_cond_state, нет pv_cond", (lambda h: h.get("pv_cond_state") is True and "pv_cond" not in h)(call("GET", "/api/health")[1]))
    (root / "Portfolio/decisions").mkdir(parents=True, exist_ok=True)
    for rel in ("Portfolio/conditions-state.json", "Portfolio/conditions-archive-2026.yaml", "Portfolio/security-attrs.json",
                "Portfolio/decisions/2026-10-29T1740-GMKN.json", "Portfolio/conditions.yaml",
                "Portfolio/decisions/readme.md", "Portfolio/conditions-archive-26.yaml", "Portfolio/other.json"):
        (root / rel).write_text("{}", encoding="utf-8")
    seen = {f + n for f, n, _v, _p in server.pv_scan(tmp)}
    check("pv_scan видит новые пути и прежние условия",
          {"Portfolio/conditions-state.json", "Portfolio/conditions-archive-2026.yaml", "Portfolio/security-attrs.json",
           "Portfolio/decisions/2026-10-29T1740-GMKN.json", "Portfolio/conditions.yaml"} <= seen)
    check("pv_scan не берёт лишнего", not seen & {"Portfolio/decisions/readme.md", "Portfolio/conditions-archive-26.yaml",
                                                   "Portfolio/other.json"})
    httpd.shutdown()
finally:
    shutil.rmtree(tmp)

print(f"\nИтого: {passed} из {passed + failed}")
sys.exit(1 if failed else 0)
