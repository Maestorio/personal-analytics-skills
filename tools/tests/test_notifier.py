#!/usr/bin/env python3
"""hub-notify — push-уведомления вьюера портфеля (tools/hosting/notify/notifier.py, v3-B).

Что держит тест (без сети, без контейнера, без Synology):
  1. условия — только через модуль (а) `conditions_merge` (шаг 7 цикла машиночитаемости) на фикстуре формата 2
     (выход миграции `tools/data-structures/tests/fixtures/conditions_v12.yaml` + дополнения): каталог общих модулей
     (pdl/_shared-references → репозиторий); сроки → fired (by_deadline, «не найдено» у окна отчёта) / expired с версией
     последнего определения; находки монитора condition_findings[] → event_found + fired с doc; решения → done
     (by: decision, decision_id; только ждущие владельца); push «ждёт владельца» — один на условие (cond:<id>@<version>:fired, тот же у цены);
     цена — pending и не раньше not_before; документ не conditions@2 — пропуск; owner_decided — по событиям
     состояния и журналу плана (stocks.*.user_status|user_plan, bonds.<ISIN>.*, funds.<тикер>.*; моменты разбором); сторож grep против собственной оценки 1.2;
  2. пороги свежести = STALE_THRESHOLDS_DAYS («пора обновить») и STALE_FAIL_DAYS вьюера (viewer.js);
  3. события на фикстуре Claude-Memory: находка монитора под условие, ждущее владельца условие,
     смена вердикта акций и облигаций (решения владельца — по событиям состояния и журналу плана, проза
     основания не читается), новое HIGH монитора (а старое — нет), ценовое условие с окном not_before;
     просроченные отчёты — оба уровня, уровень сообщается один раз;
     утро 08:30 — не больше двух уведомлений: события сводкой (одно — как есть) и просрочки сводкой;
  4. без спама: ключ отрабатывается один раз; одинаковое по бумаге — не чаще 7 дней; тихий режим
     пишет журнал и считает событие отработанным; недоставленное — повтор; >4 — сводкой; нет устройств;
     выключенный во вьюере вид — «off», отработан, включение не вываливает накопленное;
  5. Web Push: шифрование aes128gcm расшифровывается по RFC 8291 стороной браузера; подпись VAPID
     проверяется открытым ключом, aud — источник адреса подписки;
  6. HTTP: key / subscribe / status / mode / settings / test / prune / unsubscribe (push-сервис подменён);
  7. расписание: утренняя 08:30 (события + просрочки) — раз в день, догоняет после перезапуска; ценовая — будни
     10–18 MSK раз в час;
  8. контракты хостинга: Caddy шлёт /api/push/* в hub-notify только с паролем (и из LAN), фоновый
     скрипт публичен в обоих матчерах; compose поднимает hub-notify с томами; deploy.zsh выкладывает
     notifier.py и portfolio-sw.js.

Запуск:
    python3 tools/tests/test_notifier.py
Требует cryptography и PyYAML (как и контейнер).
"""
import base64
import json
import re
import shutil
import sys
import tempfile
import threading
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "tools/hosting/notify"))

passed = failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}")


try:
    import yaml  # noqa: F401
    import cryptography  # noqa: F401
except ImportError as e:
    print(f"notifier: пропуск — нет зависимости ({e.name})")
    sys.exit(0)

TMP = Path(tempfile.mkdtemp(prefix="notify-"))
import os  # noqa: E402
os.environ["NOTIFY_DATA"] = str(TMP / "data")
import notifier as N  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pages_stand import serve  # noqa: E402  (стенд — _pages_stand, keep-alive)
N.COND_URL = "http://127.0.0.1:1/api/pv/cond/event/internal"      # hub-api в тесте нет: события остаются в очереди


MSK = N.MSK

# ── 1. условия через модуль (а): фикстура формата 2 = выход миграции фикстуры 1.2 ─────────────
print("conditions (модуль а, conditions@2)")
sys.path.insert(0, str(REPO / "tools/data-structures/migrations"))
import migrate_conditions_v2 as MIG  # noqa: E402
import conditions_merge as CMRG  # noqa: E402
import ds_schemas as DSS  # noqa: E402

check("модуль (а) и кодлисты — из одного каталога общих модулей (_shared_dir), в репозитории — _shared-references",
      Path(N.CMRG.__file__).resolve().parent == N._shared_dir() == (REPO / "_shared-references").resolve()
      and Path(N.codelists.__file__).resolve().parent == N._shared_dir())
_app = TMP / "app"
(_app / "pdl/_shared-references").mkdir(parents=True)
for _f in ("conditions_merge.py", "codelists.json"):
    shutil.copy2(REPO / "_shared-references" / _f, _app / "pdl/_shared-references" / _f)
_nf = N.__file__
N.__file__ = str(_app / "notifier.py")
check("в контейнере (pdl/_shared-references рядом с notifier.py) — он первым",
      N._shared_dir() == (_app / "pdl/_shared-references").resolve())
(_app / "pdl/_shared-references/conditions_merge.py").unlink()
try:   # без модуля в pdl — откат на ../../../_shared-references; во временной папке его нет
    N._shared_dir()
    check("нет ни pdl, ни репозитория — FileNotFoundError", False)
except FileNotFoundError:
    check("нет ни pdl, ни репозитория — FileNotFoundError", True)
N.__file__ = _nf

_DD, _SD, _, _ = MIG.migrate(CMRG.load_yaml(REPO / "tools/data-structures/tests/fixtures/conditions_v12.yaml"))
_DD, _SD = json.loads(json.dumps(_DD)), json.loads(json.dumps(_SD))
_BASE = next(d for d in _DD["conditions"] if d["id"] == "ffff-trade-notify")


def cdef(cid, key, trigger, version=1, **kw):
    d = json.loads(json.dumps(_BASE))
    d.update(id=cid, key=key, trigger=trigger, version=version)
    d.update(kw)
    return d


EXTRA = [
    cdef("gggg-exp", "GGGG", {"type": "price_below", "value": 100}, valid_until="2026-11-30",
         on_expiry={"action": "notify_only", "text": "снять условие"}),
    cdef("hhhh-nb", "HHHH", {"type": "price_below", "value": 50}, not_before="2026-12-10"),
    cdef("iiii-rep", "IIII", {"type": "report_published", "value": "МСФО 9М IIII", "window_end": "2026-12-20"},
         event_text="МСФО 9М IIII", on_trigger={"action": "run_analysis", "text": "разбор после отчёта"}),
    cdef("jjjj-v2", "JJJJ", {"type": "date", "value": "2026-10-01"}, version=1, created_at="2026-09-01T10:00:00+03:00",
         superseded_by="jjjj-v2@2"),
    cdef("jjjj-v2", "JJJJ", {"type": "date", "value": "2026-12-01"}, version=2, created_at="2026-11-01T10:00:00+03:00"),
]
DEFS = _DD["conditions"] + EXTRA
STATE = {"schema_version": "conditions-state@1", "events": _SD["events"] + [
    {"condition_id": "jjjj-v2", "version": 1, "event": "fired", "at": "2026-10-01T00:00:00+03:00", "by": "notifier", "data": {}}]}
check(f"фикстура: выход миграции 1.2 + дополнения проходит валидаторы conditions@2 и conditions-state@1 "
      f"({DSS.validate_conditions_file({'schema_version': 'conditions@2', 'conditions': DEFS})[:2]})",
      DSS.validate_conditions_file({"schema_version": "conditions@2", "conditions": DEFS}) == []
      and DSS.validate_conditions_state(STATE) == [])
T = "2026-12-04"
ROWS = CMRG.merge(DEFS, STATE, T)
_dl = N.cond_deadline_events(ROWS)
check(f"дедлайны: дата ≤ сегодня → fired by_deadline; окно отчёта закрылось → fired by_deadline + «не найдено»; "
      f"valid_until прошёл → expired; версия — последняя ({_dl})",
      _dl == [
          {"condition_id": "aaaa-branches", "version": 1, "event": "fired", "by": "notifier",
           "data": {"by_deadline": True, "note": "не найдено"}},
          {"condition_id": "gggg-exp", "version": 1, "event": "expired", "by": "notifier", "data": {}},
          {"condition_id": "jjjj-v2", "version": 2, "event": "fired", "by": "notifier", "data": {"by_deadline": True}},
          {"condition_id": "ru000a000aa0-date", "version": 1, "event": "fired", "by": "notifier", "data": {"by_deadline": True}}])
check("закрытое (done), сработавшее событием (fired) и ждущие — без событий срока",
      not {b["condition_id"] for b in _dl} & {"bbbb-fired", "aaaa-below-100", "ffff-trade-notify", "hhhh-nb", "iiii-rep",
                                              "bbbb-trade-review-status"})
check("правило 14: fired прежней версии не закрывает новую — новая сработала по своей дате",
      next(r for r in ROWS if r["id"] == "jjjj-v2")["version"] == 2
      and next(r for r in ROWS if r["id"] == "jjjj-v2")["computed"] is True)
check("на следующий день после записи событий — событий срока нет (событие первично, computed снят)",
      N.cond_deadline_events(CMRG.merge(DEFS, {"events": STATE["events"] + [{**b, "at": "2026-12-04T08:30:00+03:00"} for b in _dl]},
                                        "2026-12-05")) == [])

# находки монитора → event_found + fired с data.doc
_MON = {"condition_findings": [
    {"condition_id": "iiii-rep", "version": 1, "doc": "https://e-disclosure.ru/iiii", "found_at": "2026-12-02", "note": "вышел"},
    {"condition_id": "jjjj-v2", "version": 1, "doc": "https://x/old", "found_at": "2026-10-02"},
    {"condition_id": "bbbb-fired", "version": 1, "doc": "https://x/b", "found_at": "2026-11-02"},
    {"condition_id": "ffff-trade-notify", "version": 1, "doc": None, "found_at": None, "note": "не найдено"},
    {"condition_id": "nope", "version": 1, "doc": "https://x/n", "found_at": "2026-11-02"}],
    "condition_events": [{"condition_id": "hhhh-nb", "status": "published", "event_date": "2026-12-01", "url": "https://x/h"}]}
_fe = N.cond_finding_events(ROWS, _MON)
check(f"находка → два события (event_found и fired, data.doc, версия); прежняя версия, закрытое, «не найдено», "
      f"неизвестное и старое condition_events — мимо ({_fe})",
      _fe == [("mf:iiii-rep@1:https://e-disclosure.ru/iiii", [
          {"condition_id": "iiii-rep", "version": 1, "event": "event_found", "by": "notifier", "data": {"doc": "https://e-disclosure.ru/iiii"}},
          {"condition_id": "iiii-rep", "version": 1, "event": "fired", "by": "notifier", "data": {"doc": "https://e-disclosure.ru/iiii"}}])])
check("перенесённая находка (метка в cond_seen) второй раз не переносится",
      N.cond_finding_events(ROWS, _MON, {"mf:iiii-rep@1:https://e-disclosure.ru/iiii": "x"}) == [])


def decision(key, hhmm, resolved, day="2026-12-03"):
    did = f"{day}T{hhmm}-{key}"
    return {"schema_version": "decision@1", "id": did, "key": key, "verdict": "HOLD", "target_pct": None, "review_by": None,
            "note": "разобрано", "conditions_created": [], "conditions_resolved": resolved,
            "source": {"kind": "owner", "doc": None, "mode_codes": ["4a"]}, "author": "owner",
            "recorded_at": f"{day}T{hhmm[:2]}:{hhmm[2:]}:00+03:00"}


_DECS = [decision("AAAA", "1740", ["aaaa-below-100", "bbbb-fired"]), decision("JJJJ", "1000", ["jjjj-v2"], "2026-10-15"),
         decision("BBBB", "1200", ["aaaa-branches"])]
check("решения фикстуры валидны (decision@1)", all(DSS.validate_decision(d) == [] for d in _DECS))
_de = N.cond_done_events(ROWS, CMRG._last_defs(DEFS), _DECS)
check(f"решение → done (by: decision, data.decision_id) по ждущему владельца условию своего ключа; закрытое, чужой ключ и решение "
      f"старше последней версии определения — мимо ({_de})",
      _de == [("dec:2026-12-03T1740-AAAA:aaaa-below-100", [
          {"condition_id": "aaaa-below-100", "version": 1, "event": "done", "by": "decision",
           "data": {"decision_id": "2026-12-03T1740-AAAA"}}])])
_dd = TMP / "dec-root/Portfolio/decisions"
_dd.mkdir(parents=True)
check("решений нет (папки нет) — пустой проход без ошибок", N.load_decisions(TMP / "nowhere") == [])
(_dd / "2026-12-03T1740-AAAA.json").write_text(json.dumps(_DECS[0]), encoding="utf-8")
(_dd / "broken.json").write_text("{не json", encoding="utf-8")
(_dd / "2026-12-03T1741-AAAA.json").write_text(json.dumps({**_DECS[0], "verdict": "MAYBE"}), encoding="utf-8")
check("load_decisions: валидное читается, битое и не прошедшее схему — пропуск", N.load_decisions(TMP / "dec-root") == [_DECS[0]])

# ежедневный план целиком: события → строки после них → push «ждёт владельца»
_posts, _rows2 = N.plan_conditions_daily(DEFS, STATE, T, _MON, _DECS, {}, "2026-12-04T08:30:00+03:00")
check("plan_conditions_daily: сроки, находка, решение — в одном списке, метки только у задач",
      [m for m, _ in _posts] == [None, None, None, None, "mf:iiii-rep@1:https://e-disclosure.ru/iiii",
                                 "mf:iiii-rep@1:https://e-disclosure.ru/iiii", "dec:2026-12-03T1740-AAAA:aaaa-below-100"])
_wait = {r["id"] for r in _rows2 if r["waits_owner"]}
check(f"после событий ждут владельца: сработавшие по сроку и по находке; закрытое решением — нет ({sorted(_wait)})",
      _wait == {"aaaa-branches", "iiii-rep", "jjjj-v2", "ru000a000aa0-date"})
_W = N.check_conditions_waiting(_rows2, {}, CMRG._last_defs(DEFS))
_wk = {e["key"]: e for e in _W}
check(f"push: одно событие на условие, ключ cond:<id>@<version>:fired ({sorted(_wk)})",
      set(_wk) == {"cond:aaaa-branches@1:fired", "cond:iiii-rep@1:fired", "cond:jjjj-v2@2:fired", "cond:ru000a000aa0-date@1:fired"})
check("текст: причина словами + действие кодлиста + on_trigger.text; нажатие — «Действия»",
      _wk["cond:aaaa-branches@1:fired"]["title"] == "AAAA: условие сработало"
      and _wk["cond:aaaa-branches@1:fired"]["body"].startswith("окно до 03.12 закрылось, отчёт не найден — разобрать: Разбор Mode 4")
      and _wk["cond:aaaa-branches@1:fired"]["body"].endswith("\nДействия → «Сделать»")
      and _wk["cond:jjjj-v2@2:fired"]["body"].endswith("\nДействия → «Проверить»")
      and _wk["cond:iiii-rep@1:fired"]["body"].startswith("вышло: МСФО 9М IIII — разобрать: разбор после отчёта")
      and _wk["cond:jjjj-v2@2:fired"]["body"].startswith("дата 01.12 — только сообщить")
      and all(e["url"].endswith("#tab=actions") for e in _W))
check("вид: находка монитора — cond_date (сводка событий), остальное — cond_open",
      _wk["cond:iiii-rep@1:fired"]["kind"] == "cond_date" and _wk["cond:aaaa-branches@1:fired"]["kind"] == "cond_open")
check("облигация в условии — именем, не ISIN", _wk["cond:ru000a000aa0-date@1:fired"]["title"] == "облигация: условие сработало"
      and N.check_conditions_waiting([r for r in _rows2 if r["id"] == "ru000a000aa0-date"],
                                     {"RU000A000AA0": "ОФЗ 26250"})[0]["title"] == "26250: условие сработало")
_ws = N.new_state()
_ws["mode"] = "live"
_wp = []
N.process(_W, _ws, datetime(2026, 12, 4, 8, 30, tzinfo=N.MSK), lambda e: _wp.append(e) or True, combine=N.cond_summary)
N.process(N.check_conditions_waiting(_rows2, {}, CMRG._last_defs(DEFS)), _ws, datetime(2026, 12, 5, 8, 30, tzinfo=N.MSK),
          lambda e: _wp.append(e) or True, combine=N.cond_summary)
check(f"«ждёт владельца»: одно уведомление на переход (несколько — сводкой), назавтра — тишина ({[p['title'] for p in _wp]})",
      len(_wp) == 1 and _wp[0]["title"] == "Ждут решения: 4 условия" and _wp[0]["body"].count("\n") == 3)
_def = CMRG.merge(DEFS, {"events": STATE["events"] + [{"condition_id": "aaaa-below-100", "version": 1, "event": "owner_mark",
                                                        "at": "2026-12-01T10:00:00+03:00", "by": "owner",
                                                        "data": {"mark": "deferred", "until": "2026-12-20"}}]}, T)
check("отложенное владельцем (deferred до даты) не ждёт и не шлётся",
      not any(e["key"].startswith("cond:aaaa-below-100@") for e in N.check_conditions_waiting(_def)))
check("отложенное владельцем условие новое решение не закрывает (cond_done_events пуст)",
      N.cond_done_events(_def, CMRG._last_defs(DEFS), [_DECS[0]]) == [])

# часовая цена: pending, не раньше not_before, ключ тот же, что у «ждёт владельца»
_hv = N.check_conditions_price(ROWS, T, {"FFFF": 13, "HHHH": 40, "GGGG": 90, "AAAA": 50})
check(f"цена: pending с пересечённым порогом; not_before в будущем, истёкшее и уже сработавшее — молчат ({[e['key'] for e in _hv]})",
      [e["key"] for e in _hv] == ["cond:ffff-trade-notify@1:fired"])
check("цена: событие несёт cid, version и price для fired в состоянии; вид cond_price; текст по-русски",
      _hv[0]["cid"] == "ffff-trade-notify" and _hv[0]["version"] == 1 and _hv[0]["price"] == 13
      and _hv[0]["kind"] == "cond_price" and _hv[0]["title"] == "FFFF: цена 13 ≥ 12,5 ₽")
check("not_before: в день not_before порог уже срабатывает",
      [e["cid"] for e in N.check_conditions_price(CMRG.merge(DEFS, STATE, "2026-12-10"), "2026-12-10", {"HHHH": 40})] == ["hhhh-nb"])
check("нет цены или кривой порог — нет события", N.check_conditions_price(ROWS, T, {}) == []
      and N.check_conditions_price(CMRG.merge([cdef("x", "X", {"type": "price_above", "value": "много"})], {}, T), T, {"X": 1}) == [])
_ps = N.new_state()
_ps["mode"] = "live"
_pp = []
N.process(_hv, _ps, datetime(2026, 12, 4, 11, 5, tzinfo=N.MSK), lambda e: _pp.append(e) or True)
_after = CMRG.merge(DEFS, {"events": STATE["events"] + [{"condition_id": "ffff-trade-notify", "version": 1, "event": "fired",
                                                          "at": "2026-12-04T11:05:00+03:00", "by": "notifier", "data": {"price": 13}}]},
                    "2026-12-05")
N.process(N.check_conditions_waiting([r for r in _after if r["id"] == "ffff-trade-notify"]), _ps,
          datetime(2026, 12, 5, 8, 30, tzinfo=N.MSK), lambda e: _pp.append(e) or True, combine=N.cond_summary)
check("цена сработала днём — утром второго push по тому же условию нет (один ключ)", len(_pp) == 1)

# документ другого формата — предупреждение и пропуск блока условий
_r12 = TMP / "cm-12"
(_r12 / "Portfolio").mkdir(parents=True)
shutil.copy2(REPO / "tools/data-structures/tests/fixtures/conditions_v12.yaml", _r12 / "Portfolio/conditions.yaml")
check("conditions.yaml 1.2 → (None, None): блок условий пропускается без падения", N.load_conditions(_r12) == (None, None))
_e12, _p12 = N.collect_daily(_r12, T)
check("collect_daily на 1.2 — без событий условий и без записей", _p12 == [] and not any(e["key"].startswith("cond:") for e in _e12))
check("нет файла определений — пусто, без предупреждения", N.load_conditions(TMP / "nowhere") == ([], {"events": []}))
(_r12 / "Portfolio/conditions.yaml").write_text(yaml.safe_dump({"schema_version": "conditions@2", "conditions": DEFS},
                                                                allow_unicode=True), encoding="utf-8")
check("conditions@2 без файла состояния — пустое состояние", N.load_conditions(_r12)[1] == {"events": []}
      and len(N.load_conditions(_r12)[0]) == len(DEFS))
check("даты определений — строками (load_yaml модуля), не date", all(isinstance(d["created_at"], str) for d in N.load_conditions(_r12)[0]))
(_r12 / "Portfolio/conditions-state.json").write_text("{битый", encoding="utf-8")
check("битое состояние — пропуск блока", N.load_conditions(_r12) == (None, None))

# owner_decided: события состояния, журнал плана (моменты разбираются), trades_since_prior
_PREV, _CUR = {"review_date": "2026-09-01"}, {"review_date": "2026-09-10"}
_OD = [cdef("swap-1", "RU000A0JVW48", {"type": "date", "value": "2026-09-05"}),
       cdef("x-done", "RU000A108EH4", {"type": "date", "value": "2026-09-05"}),
       cdef("x-site", "SITE1", {"type": "date", "value": "2026-09-05"}),
       cdef("x-def", "DEF1", {"type": "date", "value": "2026-09-05"})]
_OE = [{"condition_id": "swap-1", "event": "owner_mark", "at": "2026-09-05T10:00:00+03:00", "by": "owner", "data": {"mark": "dismissed"}},
       {"condition_id": "x-done", "event": "done", "at": "2026-09-06T10:00:00+03:00", "by": "owner", "data": {"note": "сделал"}},
       {"condition_id": "x-site", "event": "done", "at": "2026-09-06T10:00:00+03:00", "by": "site", "data": {"decision_id": "d"}},
       {"condition_id": "x-def", "event": "owner_mark", "at": "2026-09-06T10:00:00+03:00", "by": "owner",
        "data": {"mark": "deferred", "until": "2026-10-01"}}]
_OJ = [{"ts": "2026-09-05T07:00:00", "who": "site", "path": "stocks.MTSS.user_plan", "was": "KEEP", "now": "SELL"},
       {"ts": "2026-09-10T22:30:00Z", "who": "site", "path": "stocks.LATE.user_status", "was": None, "now": "DONE"},
       {"ts": "2026-09-05T10:00:00+03:00", "who": "site", "path": "stocks.PCT.plan_pct", "was": 1, "now": 2}]
_O = {"defs": _OD, "events": _OE, "journal": _OJ}
check("owner_decided: dismissed и done by owner по условию бумаги между обзорами — решение владельца",
      N.owner_decided("RU000A0JVW48", _CUR, _O, _PREV) and N.owner_decided("RU000A108EH4", _CUR, _O, _PREV))
check("owner_decided: done by site (решение советника) — не решение владельца; owner_mark deferred — решение (R24)",
      not N.owner_decided("SITE1", _CUR, _O, _PREV) and N.owner_decided("DEF1", _CUR, _O, _PREV))
check("owner_decided: событие вне интервала обзоров — не в счёт",
      not N.owner_decided("RU000A0JVW48", {"review_date": "2026-09-04"}, _O, _PREV))
check("owner_decided: журнал плана stocks.<бумага>.user_plan между обзорами (строка без пояса — UTC) — в счёт; plan_pct — нет",
      N.owner_decided("MTSS", _CUR, _O, _PREV) and not N.owner_decided("PCT", _CUR, _O, _PREV))
_OJB = [{"ts": "2026-09-05T10:00:00+03:00", "who": "site", "path": "bonds.RU000A108EF8.action", "was": None, "now": "держать до погашения"},
        {"ts": "2026-09-05T10:00:00+03:00", "who": "site", "path": "funds.LQDT.class", "was": "cash", "now": "bond"},
        {"ts": "2026-09-05T10:00:00+03:00", "who": "site", "path": "funds.TMOS.user_plan", "was": None, "now": "BUY"},
        {"ts": "2026-09-05T10:00:00+03:00", "who": "site", "path": "bonds.RU000A100EF5.rating", "was": "A", "now": "AA"},
        {"ts": "2026-08-01T10:00:00+03:00", "who": "site", "path": "bonds.RU000A100EF5.action", "was": None, "now": "x"}]
_pvb = {"review_date": "2026-09-01", "per_bond": {"RU000A108EF8": {"advisor_verdict": "ADD"}, "RU000A100EF5": {"advisor_verdict": "HOLD"}}}
_cvb = {"review_date": "2026-09-10", "per_bond": {"RU000A108EF8": {"advisor_verdict": "HOLD"}, "RU000A100EF5": {"advisor_verdict": "SELL"}}}
_vbj = N.check_verdicts(_pvb, _cvb, "bond", {"RU000A100EF5": "ОФЗ 26240"}, {"defs": [], "events": [], "journal": _OJB})
check(f"облигация: строка журнала bonds.<ISIN>.action между обзорами — смена вердикта не считается; строка до прошлого обзора — "
      f"считается ({_vbj and _vbj[0]['body']})",
      len(_vbj) == 1 and _vbj[0]["title"] == "Облигации: смена вердикта" and _vbj[0]["body"].startswith("26240:"))
check("R24: funds.<тикер>.user_plan между обзорами — решение владельца; справочное поле (funds.*.class, bonds.*.rating) — нет",
      N.owner_decided("TMOS", _CUR, {"journal": _OJB}, _PREV) and not N.owner_decided("LQDT", _CUR, {"journal": _OJB}, _PREV)
      and not N.owner_decided("RU000A100EF5", _CUR, {"journal": _OJB}, _PREV))
check("owner_decided: момент сравнивается разбором — 22:30Z 10.09 это 01:30 МСК 11.09, позже обзора 10.09 (строкой было бы «раньше»)",
      not N.owner_decided("LATE", _CUR, _O, _PREV) and N.owner_decided("LATE", {"review_date": "2026-09-11"}, _O, _PREV))
check("owner_decided: recorded_at обзора точнее даты (правка в 07:00Z = 10:00 МСК после обзора 09:00 того же дня)",
      N.owner_decided("MTSS", _CUR, _O, {"review_date": "2026-09-05", "recorded_at": "2026-09-05T09:00:00+03:00"})
      and not N.owner_decided("MTSS", _CUR, _O, {"review_date": "2026-09-05"}))
check("owner_decided: trades_since_prior — как раньше; без дат обзоров — только сделки",
      N.owner_decided("Z", {"trades_since_prior": [{"isin": "Z"}]}, None, None)
      and not N.owner_decided("RU000A0JVW48", {}, _O, None))

# сторож: собственной оценки 1.2 и чтения её полей в notifier.py нет
_src = (REPO / "tools/hosting/notify/notifier.py").read_text(encoding="utf-8")
_code = "\n".join(ln.split("#", 1)[0] for ln in _src.splitlines())
_bad = re.findall(r"\b(evaluate_condition|_cond_action|_OWNER_RX|check_conditions_open|_closed_manual|remember_price_hits)\b", _code) + \
    re.findall(r"""get\(\s*["'](touched|history|state|conditions_state|fired_date|condition_events)["']""", _code) + \
    re.findall(r"""\[\s*["'](touched|history|conditions_state|fired_date|condition_events)["']\s*\]""", _code)
check(f"сторож: в notifier.py нет evaluate_condition/_cond_action/_OWNER_RX и чтения touched/history/state/"
      f"conditions_state/condition_events ({_bad})", not _bad)
check("сторож: условия читаются модулем (а) — CMRG.merge и load_yaml модуля", "CMRG.merge(" in _code and "CMRG.load_yaml(" in _code)

# ── 2. пороги свежести = вьюер ───────────────────────────────────────────────
print("stale thresholds")
_vj = (REPO / "tools/assets/viewer.js").read_text(encoding="utf-8")
_m = re.search(r"const STALE_FAIL_DAYS = \{([^}]*)\}", _vj)
_viewer = {k: int(v) for k, v in re.findall(r"(\w+):\s*(\d+)", _m.group(1))} if _m else {}
check(f"STALE_FAIL_DAYS проверяльщика = вьюера ({N.STALE_FAIL_DAYS} vs {_viewer})", _viewer == N.STALE_FAIL_DAYS)
_m = re.search(r"const STALE_THRESHOLDS_DAYS = \{([^}]*)\}", _vj)
_warn = {k: int(v) for k, v in re.findall(r"^\s*(\w+):\s*(\d+)", _m.group(1), re.M)} if _m else {}
check(f"STALE_WARN_DAYS проверяльщика = STALE_THRESHOLDS_DAYS вьюера ({N.STALE_WARN_DAYS} vs {_warn})", _warn == N.STALE_WARN_DAYS)
check("у каждого вида свежести есть файл и подпись", set(N.STALE_WARN_DAYS) == set(N.STALE_FILES) == set(N.STALE_LABEL))

# ── 3. события на фикстуре ───────────────────────────────────────────────────
print("events")
CM = TMP / "cm"
for d in ("Portfolio/weekly-reviews", "Portfolio/stress", "Portfolio/snapshots", "monitor-reports",
          "macro-snapshots", "Portfolio/integrated-views"):
    (CM / d).mkdir(parents=True)
TODAY = "2026-10-16"


def wyaml(rel, obj):
    (CM / rel).write_text(yaml.safe_dump(obj, allow_unicode=True), encoding="utf-8")


# условия формата 2: фикстура секции 1 + условия облигаций, закрытые владельцем между обзорами
_C3 = DEFS + [cdef("swap-1", "RU000A0JVW48", {"type": "date", "value": "2026-12-30"}),
              cdef("eh4-done", "RU000A108EH4", {"type": "date", "value": "2026-12-30"})]
wyaml("Portfolio/conditions.yaml", {"schema_version": "conditions@2", "conditions": _C3})
(CM / "Portfolio/conditions-state.json").write_text(json.dumps({"schema_version": "conditions-state@1", "events": STATE["events"] + [
    {"condition_id": "swap-1", "event": "owner_mark", "at": "2026-08-26T10:00:00+03:00", "by": "owner", "data": {"mark": "dismissed"}},
    {"condition_id": "eh4-done", "event": "done", "at": "2026-09-06T10:00:00+03:00", "by": "owner", "data": {"note": "сделал"}}]},
    ensure_ascii=False), encoding="utf-8")
(CM / "Portfolio/plan-journal.jsonl").write_text(
    json.dumps({"ts": "2026-10-05T09:00:00+03:00", "who": "site", "path": "stocks.MTSS.user_plan", "was": "KEEP", "now": "BUY"}) + "\n"
    + "не json\n", encoding="utf-8")
wyaml("Portfolio/weekly-reviews/weekly-review-stock-2026-10-01.yaml",
      {"review_date": "2026-10-01", "per_stock": {"GLRX": {"advisor_verdict": "HOLD"}, "SBER": {"advisor_verdict": "HOLD"},
                                                  "MTSS": {"advisor_verdict": "HOLD"}}})
wyaml("Portfolio/weekly-reviews/weekly-review-stock-2026-10-08.yaml",
      {"review_date": "2026-10-08", "per_stock": {"GLRX": {"advisor_verdict": "SELL"}, "SBER": {"advisor_verdict": "HOLD"},
                                                  "NEWCO": {"advisor_verdict": "BUY"}, "MTSS": {"advisor_verdict": "BUY"}}})
wyaml("Portfolio/weekly-reviews/weekly-review-bond-2026-08-01.yaml",
      {"review_date": "2026-08-01", "per_bond": {
          "RU000A1": {"name": "ОФЗ 26243", "advisor_verdict": "HOLD", "weight_real_pct": 5.0},
          "RU000A100EF5": {"name": "ОФЗ 26240", "advisor_verdict": "HOLD", "weight_real_pct": 3.0},
          "RU000A108EF8": {"name": "ОФЗ 26247", "advisor_verdict": "ADD"},
          "RU000A0JVW48": {"name": "ОФЗ 26218", "advisor_verdict": "SELL"},
          "RU000A108EH4": {"name": "ОФЗ 26248", "advisor_verdict": "BUY"},
          "RU000A1ZZZ91": {"name": "Эмитент 1Р1", "advisor_verdict": "HOLD"}}})
wyaml("Portfolio/weekly-reviews/weekly-review-bond-2026-09-10.yaml",
      {"review_date": "2026-09-10", "per_bond": {
          "RU000A1": {"name": "ОФЗ 26243", "advisor_verdict": "TRIM", "weight_real_pct": 5.0},
          "RU000A100EF5": {"name": "ОФЗ 26240", "advisor_verdict": "SELL", "weight_real_pct": 3.0},
          # проза основания («владелец купил») больше не читается — смена 26247 считается; решения владельца —
          # dismissed по swap-1 и done по eh4-done в состоянии, сделка из trades_since_prior
          "RU000A108EF8": {"name": "ОФЗ 26247", "advisor_verdict": "HOLD",
                           "advisor_verdict_basis": "ADD исполнен: 26.10 владелец купил 149 шт"},
          "RU000A0JVW48": {"name": "ОФЗ 26218", "advisor_verdict": "HOLD",
                           "advisor_verdict_basis": "SELL → HOLD: своп владелец отклонил 26.10 (условие закрыто вручную)"},
          "RU000A108EH4": {"name": "ОФЗ 26248", "advisor_verdict": "HOLD",
                           "advisor_verdict_basis": "условие swap-1 больше не действует"},
          "RU000A1ZZZ91": {"name": "Эмитент 1Р1", "advisor_verdict": "SELL", "advisor_verdict_basis": "рейтинг снижен"}},
       "trades_since_prior": [{"isin": "RU000A1ZZZ91", "action": "sold"}],
       "conditions_state": [{"id": "swap-1", "state": "closed_manual 26.10 (владелец)"}]})
wyaml("Portfolio/stress/stress-2026-10-04-x.yaml", {"x": 1})
(CM / "Portfolio/snapshots/portfolio-2026-10-13.json").write_text(
    json.dumps({"holdings": [{"ticker": "GLRX", "name": "Glorax", "qty": 10}, {"ticker": "MTSS", "qty": 5},
                             {"ticker": "SOLD", "qty": 0}, {"ticker": "RU000A1", "isin": "RU000A1", "qty": 2}, {"ticker": "NOQTY"},
                             {"ticker": "RU000A100EF5", "isin": "RU000A100EF5", "qty": 3}, {"ticker": "RU000A108EF8", "isin": "RU000A108EF8", "qty": 3},
                             {"ticker": "RU000A0JVW48", "isin": "RU000A0JVW48", "qty": 1}, {"ticker": "RU000A108EH4", "isin": "RU000A108EH4", "qty": 1}]}),
    encoding="utf-8")
(CM / "macro-snapshots/ru-2026-10-01.md").write_text("макро", encoding="utf-8")   # срез скилла: свежесть макро им больше не меряется
(CM / "macro-snapshots/inflation").mkdir(parents=True, exist_ok=True)
(CM / "macro-snapshots/inflation/model.jsonl").write_text(json.dumps(
    {"date": "2026-10-01", "week_pct": 0.1, "week_period": "22–28.09", "yoy_pct": 7.0, "yoy_as_of": "2026-09-28", "source_url": None,
     "source_name": "Росстат", "recorded_at": "2026-10-01T12:00:00+03:00", "author": "model"}, ensure_ascii=False) + "\n", encoding="utf-8")
(CM / "Portfolio/integrated-views/integrated-view-2026-10-04.md").write_text("iv", encoding="utf-8")
wyaml("monitor-reports/monitor-report-2026-10-01.yaml", {"alerts": [
    {"severity": "HIGH", "category": "stale", "target": "brent", "message": "старое"}]})
wyaml("monitor-reports/monitor-report-2026-10-08.yaml", {"alerts": [
    {"severity": "HIGH", "category": "stale", "target": "brent", "message": "старое"},
    {"severity": "HIGH", "category": "factor_breach", "target": "usdrub", "message": "рубль за порогом"},
    {"severity": "MEDIUM", "category": "x", "target": "y", "message": "не важно"}],
    "condition_findings": [{"condition_id": "iiii-rep", "version": 1, "doc": "https://e-disclosure.ru/iiii", "found_at": "2026-10-15"}],
    "condition_events": [{"condition_id": "ffff-trade-notify", "status": "published", "event_date": "2026-10-15", "url": "https://x"}]})

ev, POSTS = N.collect_daily(CM, TODAY)
keys = {e["key"] for e in ev}
check(f"утро: находка свежего отчёта монитора → в очередь состояния event_found + fired с doc, сроков нет ({POSTS})",
      [(m, b["event"], b["data"].get("doc")) for m, b in POSTS]
      == [("mf:iiii-rep@1:https://e-disclosure.ru/iiii", "event_found", "https://e-disclosure.ru/iiii"),
          ("mf:iiii-rep@1:https://e-disclosure.ru/iiii", "fired", "https://e-disclosure.ru/iiii")])
check(f"ждут владельца: сработавшее ранее (касание порога из миграции) и сработавшее по находке ({sorted(k for k in keys if k.startswith('cond:'))})",
      {k for k in keys if k.startswith("cond:")} == {"cond:aaaa-below-100@1:fired", "cond:iiii-rep@1:fired"})
check("старое поле монитора condition_events не читается (ffff молчит)", not any("ffff" in k for k in keys))
check("монитор: нажатие — «Действия» с окном новых", any(e["key"] == "monitor:2026-10-08"
      and e["url"].endswith("#tab=actions&new=usdrub") for e in ev))
check("монитор нашёл событие условия → «вышло», вид cond_date",
      any(e["key"] == "cond:iiii-rep@1:fired" and e["kind"] == "cond_date" and e["body"].startswith("вышло: МСФО 9М IIII") for e in ev))
check("закрытое (done) условие молчит", not any(k.startswith("cond:bbbb-fired") for k in keys))
_vs = {e["key"]: e for e in ev if e["kind"] == "verdict"}
check(f"смены вердикта — по ОДНОМУ уведомлению на обзор и вид ({sorted(_vs)})",
      set(_vs) == {"verdicts:stock:2026-10-08", "verdicts:bond:2026-09-10"})
check("смена вердикта акций HOLD → SELL: заголовок отвечает сам, слова вместо кодов",
      _vs["verdicts:stock:2026-10-08"]["title"] == "Акции: смена вердикта"
      and _vs["verdicts:stock:2026-10-08"]["body"] == "GLRX: держать → продать\nСмотри «Изменения»")
check("нажатие — «Изменения» нужного вида и даты обзора",
      _vs["verdicts:bond:2026-09-10"]["url"].endswith("#tab=diff&kind=bond&date=2026-09-10")
      and _vs["verdicts:stock:2026-10-08"]["url"].endswith("#tab=diff&kind=stock&date=2026-10-08"))
check("без смены и новые бумаги — молчат", not any(":SBER:" in k or ":NEWCO:" in k for k in keys))
check("акции: смена MTSS — после строки журнала плана stocks.MTSS.user_plan между обзорами — не считается",
      "MTSS" not in _vs["verdicts:stock:2026-10-08"]["body"])
_vb = _vs["verdicts:bond:2026-09-10"]
check(f"облигации: решения владельца (dismissed и done в состоянии, trades_since_prior) не считаются; ADD → HOLD без «срочно» — «К сведению», не пушим ({_vb['title']} | {_vb['body']})",
      _vb["title"] == "Облигации: 2 смены вердикта" and _vb["body"] == "Обзор 10.09: 26243, 26240\nСмотри «Изменения»")
check("в тексте смен нет ISIN и кодов вердиктов",
      not any(N._ISIN_RX.search(e["title"] + e["body"]) or N._VCODE_RX.search(e["title"] + e["body"]) for e in _vs.values()))
_pv = {"review_date": "2026-09-01", "per_bond": {"RU000A108EF8": {"advisor_verdict": "ADD"}}}
_cv = {"review_date": "2026-09-10", "per_bond": {"RU000A108EF8": {"advisor_verdict": "HOLD", "verification_priority": "HIGH",
                                                                   "verification_checklist": ["проверить оферту"]}}}
check("только решения владельца — уведомления нет", N.check_verdicts(_pv, {**_cv, "trades_since_prior": [{"isin": "RU000A108EF8"}]}, "bond") == [])
_own = lambda at: {"defs": [cdef("ef8", "RU000A108EF8", {"type": "date", "value": "2026-12-30"})],  # noqa: E731
                    "events": [{"condition_id": "ef8", "event": "done", "at": at, "by": "owner", "data": {"note": "x"}}]}
check("условие по бумаге закрыто владельцем (done by owner) между обзорами — смена не считается; раньше прошлого обзора — считается",
      N.check_verdicts(_pv, _cv, "bond", None, _own("2026-09-05T10:00:00+03:00")) == []
      and len(N.check_verdicts(_pv, _cv, "bond", None, _own("2026-08-05T10:00:00+03:00"))) == 1)
# пачка 3 читаемости: push — только по «Сделать»/«Проверить» (вердикт с направлением, проверка «срочно»); проданная и «к сведению» — нет
_p3 = {"review_date": "2026-09-01", "per_stock": {"A": {"advisor_verdict": "SELL"}, "B": {"advisor_verdict": "SELL"}, "C": {"advisor_verdict": "SELL"},
                                                  "D": {"advisor_verdict": "HOLD"}, "E": {"advisor_verdict": "HOLD"},
                                                  "F": {"advisor_verdict": "SELL"}}}
_c3 = {"review_date": "2026-09-10", "per_stock": {"A": {"advisor_verdict": "HOLD", "verification_priority": "MEDIUM"},
                                                  "B": {"advisor_verdict": "HOLD", "verification_priority": "HIGH",
                                                        "verification_checklist": ["проверить дивиденд"]},
                                                  "F": {"advisor_verdict": "HOLD", "verification_priority": "HIGH",
                                                        "verification_checklist": []},   # R28: «срочно» без пунктов — не push
                                                  "C": {"advisor_verdict": "HOLD_TO_MAT", "verification_priority": "LOW"},
                                                  "D": {"advisor_verdict": "SELL", "verification_priority": "HIGH"},
                                                  "E": {"advisor_verdict": "TRIM", "verification_priority": "MEDIUM"}}}
_r3 = N.check_verdicts(_p3, _c3, "stock", None, None, {"A", "B", "C", "E", "F"})
check(f"push: HOLD «желательно» и HOLD_TO_MAT «не срочно» молчат, HOLD «срочно» с пунктами и TRIM — да, «срочно» без пунктов — нет (R28), SELL по бумаге не из снапшота (продана) — нет ({_r3 and _r3[0]['body']!r})",
      len(_r3) == 1 and _r3[0]["title"] == "Акции: 2 смены вердикта" and _r3[0]["body"] == "Обзор 10.09: B, E\nСмотри «Изменения»")
check("action_row: продажа уже проданной — нет; покупка бумаги не из портфеля — да; без снапшота фильтра по портфелю нет",
      not N.action_row({"advisor_verdict": "SELL"}, "X", {"Y"}) and N.action_row({"advisor_verdict": "BUY"}, "X", {"Y"})
      and N.action_row({"advisor_verdict": "SELL"}, "X", None) and not N.action_row({"advisor_verdict": "HOLD", "verification_priority": "MEDIUM"}, "X", None))
check("held_keys = snapshot_keys модуля (б) (decisions_read, правило 14): количество 0 и поля нет — не в портфеле, ISIN облигации — ключ",
      (lambda h: "GLRX" in h and "SOLD" not in h and "NOQTY" not in h and "RU000A1" in h and "RU000A108EF8" in h)(N.held_keys(CM)))
check("held_keys — одна функция decisions_read, не копия: в notifier нет своего разбора holdings",
      "decisions_read.held_keys" in Path(N.__file__).read_text(encoding="utf-8")
      and "for h in snap.get(\"holdings\")" not in Path(N.__file__).read_text(encoding="utf-8"))
check("ключ один на обзор и вид (повтор не отправляется)",
      N.check_verdicts(_pv, _cv, "bond")[0]["key"] == "verdicts:bond:2026-09-10")
_vst = N.new_state()
_vst["mode"] = "live"
_vp = []
N.process(N.check_verdicts({"review_date": "1", "per_stock": {"A": {"advisor_verdict": "HOLD"}}},
                           {"review_date": "2", "per_stock": {"A": {"advisor_verdict": "SELL"}}}, "stock"), _vst, MSK_NOW := datetime(2026, 10, 16, 8, 30, tzinfo=N.MSK),
          lambda e: _vp.append(e) or True)
N.process(N.check_verdicts({"review_date": "1", "per_stock": {"A": {"advisor_verdict": "HOLD"}}},
                           {"review_date": "2", "per_stock": {"A": {"advisor_verdict": "SELL"}}}, "stock"), _vst, MSK_NOW + timedelta(days=1),
          lambda e: _vp.append(e) or True)
check("тот же обзор на следующий день — молчит", len(_vp) == 1)
check("монитор: только НОВОЕ HIGH, одним уведомлением",
      [e["body"] for e in ev if e["key"] == "monitor:2026-10-08"] == ["рубль за порогом\nДействия → полный текст в окне"]
      and [e["title"] for e in ev if e["key"] == "monitor:2026-10-08"] == ["Монитор: важный сигнал"])
check("в событиях утра просрочек нет (они вторым уведомлением)", not any(k.startswith("stale") for k in keys))
check("виды событий условий: находка — cond_date, ждёт владельца — cond_open",
      {e["key"]: e["kind"] for e in ev if e["key"].startswith("cond:")} == {"cond:iiii-rep@1:fired": "cond_date",
                                                                          "cond:aaaa-below-100@1:fired": "cond_open"})
sv = N.check_stale(CM, TODAY)
skeys = {e["key"] for e in sv}
check(f"просрочки: облигации 36 дн. > 30 — fail, инфляция 15 дн. > 9 — warn, свежие молчат ({sorted(skeys)})",
      skeys == {"stale:bonds:2026-09-10:fail", "stale:macro:2026-10-01:warn"})
# режим сайта «без ИИ» (этап D): LLM-файлы не напоминаются, снапшот — с подсказкой про сайт
_sv_off = N.check_stale(CM, TODAY, "off")
check(f"stale при off: виды LLM-файлов (облигации, макро) пропущены ({[e['key'] for e in _sv_off]})",
      not any(e["key"].split(":")[1] in N.STALE_LLM for e in _sv_off))
check("stale при on: текст несёт «Сказать Claude»", all("Сказать Claude" in e["body"] for e in sv))
_sv_pf = N.check_stale(CM, "2027-06-01", "off")
check("stale при off: снапшот напоминается с подсказкой про сайт, без «Сказать Claude»",
      any(e["key"].startswith("stale:portfolio") and "Загрузки" in e["body"] and "Сказать Claude" not in e["body"] for e in _sv_pf)
      and not any(e["key"].split(":")[1] in N.STALE_LLM for e in _sv_pf))
_ev_off, _p_off = N.collect_daily(CM, TODAY, mode="off")
check("утро при off: смен вердиктов и монитора нет, условия и «ждёт владельца» — как обычно",
      not any(e["key"].startswith(("verdicts:", "monitor:")) for e in _ev_off)
      and {e["key"] for e in _ev_off if e["key"].startswith("cond:")} == {e["key"] for e in ev if e["key"].startswith("cond:")}
      and len(_p_off) == len(POSTS))
_hub = CM / "_hub"; _hub.mkdir(exist_ok=True)
check("ai_mode: нет файла → on", N.ai_mode(CM) == "on")
(_hub / "settings.json").write_text(json.dumps({"schema": "hub-settings@1", "ai_mode": "off", "off_since": "2026-10-15T10:00:00+03:00",
                                                "returned_at": None, "by": "site", "note": None, "updated_at": "2026-10-15T10:00:00+03:00"}), encoding="utf-8")
check("ai_mode: файл off → off", N.ai_mode(CM) == "off")
(_hub / "settings.json").write_text("{битый", encoding="utf-8")
check("ai_mode: битый файл → on", N.ai_mode(CM) == "on")
(_hub / "settings.json").unlink()

MORN = datetime(2026, 10, 16, 8, 30, tzinfo=N.MSK)
st_s = N.new_state()
st_s["mode"] = "live"
pushed = []
out = N.process(sv, st_s, MORN, lambda e: pushed.append(e) or True, combine=N.stale_summary)
check("просрочки — одним уведомлением, «скиллы не работают» первыми",
      len(pushed) == 1 and pushed[0]["title"] == "Просрочено 2 отчёта"
      and pushed[0]["body"] == "• обзор облигаций — 36 дн., скиллы не работают\n• инфляция — 15 дн."
      and pushed[0]["url"].endswith("#tab=actions")
      and all(o["status"] == "sent" and o.get("grouped") for o in out))
pushed.clear()
N.process(N.check_stale(CM, "2026-10-17"), st_s, MORN + timedelta(days=1), lambda e: pushed.append(e) or True, combine=N.stale_summary)
check("сообщённый уровень не повторяется на следующий день", pushed == [])
N.process(N.check_stale(CM, "2026-11-01"), st_s, MORN + timedelta(days=16), lambda e: pushed.append(e) or True, combine=N.stale_summary)
check(f"новые просрочки — снова одним, уже сообщённые — нет; инфляция 31 дн. > 16 — новый уровень fail ({[p['title'] for p in pushed]})",
      len(pushed) == 1 and pushed[0]["title"] == "Просрочено 4 отчёта"
      and all(x in pushed[0]["body"] for x in ("обзор акций", "снапшот портфеля", "монитор", "инфляция — 31 дн., срок вышел"))
      and "облигаций" not in pushed[0]["body"])
pushed.clear()
N.process(N.check_stale(CM, "2026-11-10"), st_s, MORN + timedelta(days=25), lambda e: pushed.append(e) or True, combine=N.stale_summary)
check(f"переход warn → fail того же файла сообщается отдельно, первым ({[p['body'] for p in pushed]})",
      len(pushed) == 1 and pushed[0]["body"].startswith("• обзор акций — 33 дн., скиллы не работают\n"))
_f1 = N.stale_summary([e for e in N.check_stale(CM, "2026-11-10") if e["key"].startswith("stale:stocks")])
check("одна критичная просрочка: заголовок «Обзор акций: старше 30 дн.», в теле команда Claude",
      _f1["title"] == "Обзор акций: старше 30 дн."
      and _f1["body"] == "Файл от 08.10 (33 дн.) — скиллы на нём не работают\nСказать Claude: «обнови недельный обзор акций»")
one = N.stale_summary([sv[1]])
check("одна просрочка — заголовок сам говорит, что делать; тело — команда Claude",
      one["title"] == "Пора обновить инфляцию" and one["body"] == "Последняя от 01.10, 15 дн.\nСказать Claude: «обнови инфляцию»")
_mf = N.stale_summary([e for e in N.check_stale(CM, "2026-11-01") if e["key"].startswith("stale:macro")])
check("инфляция старше 16 дн.: «срок вышел», а не «скиллы не работают»",
      _mf["title"] == "Инфляция: старше 16 дн." and _mf["body"].startswith("Последняя от 01.10 (31 дн.) — срок вышел")
      and "скиллы" not in _mf["body"])
ev_s = N.new_state()
ev_s["mode"] = "live"
pushed = []
N.process(ev, ev_s, MORN, lambda e: pushed.append(e) or True, combine=N.events_summary)
check(f"утренние события — ОДНИМ уведомлением на журнал ({[p['title'] for p in pushed]})",
      len(pushed) == 1 and pushed[0]["title"] == f"Портфель: {len(ev)} событий" and pushed[0]["url"].endswith("#tab=notify"))
pushed.clear()
N.process([{**_E, "key": "solo"} for _E in ev[:1]], N.new_state() | {"mode": "live"}, MORN, lambda e: pushed.append(e) or True,
          combine=N.events_summary)
check("одно утреннее событие — как есть", len(pushed) == 1 and pushed[0]["key"] == "solo" and pushed[0]["url"] == ev[0]["url"])
check("склонение: 1 событие, 2 события, 5 событий, 21 событие",
      [N._plural(n, "событие", "события", "событий") for n in (1, 2, 5, 21, 12)] == ["событие", "события", "событий", "событие", "событий"])
check("ценовые условия в утренней проверке не смотрятся", not any("ffff" in k for k in keys))


hv = N.collect_hourly(CM, TODAY, {"FFFF": 1250.0, "HHHH": 40})
check("ценовое условие созрело по живой цене", [e["key"] for e in hv] == ["cond:ffff-trade-notify@1:fired"])
check("вид ценовых условий — cond_price", hv[0]["kind"] == "cond_price")
check("в окне not_before пройденный порог ещё молчит", not any("hhhh" in e["key"] for e in hv))
check("текст цены по-русски", "1 250 ≥ 12,5" in hv[0]["title"])
check("нет цены — нет события", N.collect_hourly(CM, TODAY, {}) == [])
check("битое состояние — часовой проход пуст без падения", N.collect_hourly(_r12, TODAY, {"AAAA": 1}) == [])

# условие владельца на бумагу ВНЕ портфеля (задача 2.4 «без ИИ», решение 11.11): ценовой проход держание не проверяет —
# цену берёт из всей доски (TQBR + TQOB + TQCB, QUOTES_URL), снапшота портфеля у корня может не быть вовсе
check("QUOTES_URL — три доски: акции TQBR, ОФЗ TQOB, корпоративные TQCB",
      all(b in N.QUOTES_URL for b in ("TQBR", "TQOB", "TQCB")))
_own_root = TMP / "cm-owner"
(_own_root / "Portfolio").mkdir(parents=True)
_own = [cdef("c-2026-11-11-zzzz-1", "ZZZZ", {"type": "price_below", "value": 250}, kind="watch",
             while_pending={"verdict": None, "text": ""}, on_trigger={"action": "notify_only", "text": "Пора смотреть покупку ZZZZ"},
             source={"kind": "owner", "doc": None}, created_by="owner", created_at="2026-11-11T10:00:00+03:00", context=None),
        cdef("c-2026-11-11-ru000a0zzz99-1", "RU000A0ZZZ99", {"type": "price_above", "value": 101.5}, kind="watch",
             while_pending={"verdict": None, "text": ""}, on_trigger={"action": "notify_only", "text": "Облигация подорожала"},
             source={"kind": "owner", "doc": None}, created_by="owner", created_at="2026-11-11T10:00:00+03:00", context=None)]
(_own_root / "Portfolio/conditions.yaml").write_text(
    __import__("yaml").safe_dump({"schema_version": "conditions@2", "conditions": _own}, allow_unicode=True, sort_keys=False), encoding="utf-8")
check("снапшота портфеля нет — бумага вне портфеля (held_keys → None)", N.held_keys(_own_root) is None)
_oh = N.collect_hourly(_own_root, "2026-11-12", {"ZZZZ": 240.0, "RU000A0ZZZ99": 102.0, "SBER": 300.0})
check(f"цена бумаги вне портфеля дошла до порога — событие cond_price по обоим (акция TQBR, облигация TQOB/TQCB) ({[e['key'] for e in _oh]})",
      sorted(e["key"] for e in _oh) == ["cond:c-2026-11-11-ru000a0zzz99-1@1:fired", "cond:c-2026-11-11-zzzz-1@1:fired"]
      and all(e["kind"] == "cond_price" for e in _oh))
check("порог не пройден — тишина, чужая цена в доске ни при чём",
      N.collect_hourly(_own_root, "2026-11-12", {"ZZZZ": 260.0, "RU000A0ZZZ99": 100.0, "SBER": 1.0}) == [])
check("«дата» владельца тоже читается без держания (утренний проход: ждёт отметки по сроку)",
      [r["status"] for r in CMRG.merge([cdef("c-d", "ZZZZ", {"type": "date", "value": "2026-11-12"}, kind="watch",
                                             while_pending={"verdict": None, "text": ""}, source={"kind": "owner", "doc": None})],
                                       {"events": []}, "2026-11-13")] == ["fired"])

# ── 3а. читаемость на экране блокировки ──────────────────────────────────────
print("readable")
import eshop as ES  # noqa: E402
sys.path.insert(0, str(REPO / "_shared-references"))
import codelists  # noqa: E402
check("слова вердиктов уведомлений = кодлист verdict (codelists.json) в нижнем регистре",
      N.VERDICT_WORD == {k: v.lower() for k, v in codelists.words("verdict").items()})
_it = {"nsuid_us": "1", "title": "The Legend of Zelda: Tears of the Kingdom", "price_usd": 39.99, "sale_usd": 39.99,
       "regular_usd": 69.99, "discount_pct": 43, "sale_end": "2026-11-01T00:00:00Z", "price_target_usd": 40, "target_met": True}
_it2 = {"nsuid_us": "2", "title": "Undertale", "price_usd": 9.89, "sale_usd": 9.89, "regular_usd": 14.99, "discount_pct": 34,
        "sale_end": "2026-11-01T00:00:00Z"}
_tg = ES.target_events({"items": []}, {"items": [_it]})
_sl = ES.sale_events({"items": []}, {"items": [_it2]})
_ss = ES.sale_summary(ES.sale_events({"items": []}, {"items": [_it2, {**_it2, "nsuid_us": "3", "title": "Hades"}]}))
check(f"eshop: длинное имя обрезается, цена остаётся ({_tg[0]['title']})",
      len(_tg[0]["title"]) <= 32 and _tg[0]["title"].endswith(" −43%: $39.99") and "…" in _tg[0]["title"]
      and _sl[0]["title"] == "Undertale −34%: $9.89")
check("eshop: тело — две строки, где смотреть", _tg[0]["body"].count("\n") == 1 and _tg[0]["body"].endswith("Игры → Присматриваюсь")
      and _sl[0]["body"].splitlines()[0] == "Скидка в US eShop · было $14.99 · до 01.11")
check(f"eshop: сводка скидок — короткий заголовок и пункт на строку ({_ss['title']})",
      _ss["title"] == "Скидки на 2 игры" and _ss["body"] == "• Undertale −34% · $9.89\n• Hades −34% · $9.89")
# каждый вид: заголовок ≤ 32, тело ≤ 2 строк, без ISIN и кодов вердиктов
_names = {"RU000A108EH4": "ОФЗ 26248"}
_all = {
    "ждёт решения (одно)": N.check_conditions_waiting(CMRG.merge([cdef("x5", "X5", {"type": "date", "value": TODAY})], {}, TODAY)),
    "ждёт решения (одно, ISIN)": N.check_conditions_waiting(CMRG.merge(
        [cdef("b", "RU000A108EH4", {"type": "date", "value": "2026-10-20"}, on_trigger={"action": "set_verdict", "verdict": "SELL",
                                                                                     "text": "SELL RU000A108EH4 целиком"})],
        {"events": [{"condition_id": "b", "event": "fired", "at": "2026-10-13T11:00:00+03:00", "by": "notifier", "data": {}}]}, TODAY), _names),
    "реинвест (R30)": N.check_conditions_waiting(CMRG.merge(
        [cdef("pik", "RU000A105146", {"type": "date", "value": TODAY},
              on_trigger={"action": "reinvest", "target": "ОФЗ/>10", "amount_source": "redemption",
                          "text": "погашение RU000A105146 → реинвест в ОФЗ, в USD не возвращать"})], {}, TODAY),
        {"RU000A105146": "ПИК К 1P5"}),
    "отчёт под условие": [e for e in ev if e["kind"] == "cond_date"],
    "«вышел» владельца (R32)": N.check_conditions_waiting(CMRG.merge(
        [cdef("lsng", "LSNG", {"type": "report_published", "value": "РСБУ 9М", "window_end": "2026-12-20"})],
        {"events": [{"condition_id": "lsng", "event": "event_found", "at": "2026-10-16T10:00:00+03:00", "by": "owner",
                     "data": {}}]}, TODAY)),
    "ценовое": hv,
    "смена вердиктов": list(_vs.values()),
    "монитор": [e for e in ev if e["kind"] == "monitor"],
    "просрочка": sv,
    "eshop": _tg + _sl,
}
for _k, _evs in _all.items():
    check(f"{_k}: событие есть", bool(_evs))
    for _e in _evs:
        _txt = _e["title"] + "\n" + _e["body"]
        check(f"{_k}: заголовок ≤ 32 ({len(_e['title'])}: {_e['title']}), тело ≤ 2 строк, нет ISIN и кодов",
              len(_e["title"]) <= N.TITLE_MAX and _e["body"].count("\n") <= 1
              and not N._ISIN_RX.search(_txt) and not N._VCODE_RX.search(_txt))
_o1 = _all["ждёт решения (одно)"][0]
check(f"одно условие: заголовок отвечает сам, тело — причина, действие, где решать ({_o1['body']!r})",
      _o1["title"] == "X5: условие сработало"
      and _o1["body"] == "дата 16.10 — только сообщить: известить владельца\nДействия → «Проверить»")
check("облигация в условии — по имени, не по ISIN; в тексте ISIN → имя, код → слово",
      _all["ждёт решения (одно, ISIN)"][0]["title"] == "26248: условие сработало"
      and "продать ОФЗ 26248 целиком" in _all["ждёт решения (одно, ISIN)"][0]["body"])
check("plain(): ISIN → имя, BUY/HOLD → слова",
      N.plain("свап RU000A108EH4: BUY → HOLD, TRIM 30%", _names) == "свап ОФЗ 26248: докупать → держать, сократить 30%"
      and N.plain("RU000A1ZZZ91") == "бумага")
_ri = _all["реинвест (R30)"][0]
check(f"R30: сработавший reinvest — «Сделать: реинвестировать погашение → корзина», без вердикта ({_ri['body']!r})",
      _ri["body"] == "дата 16.10 — Сделать: реинвестировать погашение → ОФЗ длиннее 10 лет\nДействия → «Сделать»")
_of = _all["«вышел» владельца (R32)"][0]
check(f"R32: «вышел» владельца — как по сроку: cond_open, «сработало: вышел отчёт … — ждёт владельца» ({_of['body']!r})",
      _of["kind"] == "cond_open" and _of["key"] == "cond:lsng@1:fired"
      and _of["body"] == "сработало: вышел отчёт РСБУ 9М — ждёт владельца\nДействия → «Проверить»")
_sv = N.check_conditions_waiting(CMRG.merge([cdef("trim", "X5", {"type": "date", "value": TODAY},
                                                  on_trigger={"action": "set_verdict", "verdict": "TRIM", "text": ""})], {}, TODAY))
check(f"R30: у set_verdict — слово вердикта, не «сменить вердикт» ({_sv[0]['body']!r})",
      _sv[0]["body"].startswith("дата 16.10 — сократить") and "сменить вердикт" not in _sv[0]["body"])
_many = N.cond_summary(N.check_conditions_waiting(ROWS))
check(f"несколько условий: заголовок «Ждут решения: N», пункт на строку, переносы ({_many['body']!r})",
      _many["title"] == "Ждут решения: 4 условия" and _many["body"].split("\n") == [
          "• AAAA — цена ниже порога 100 ₽", "• AAAA — окно до 03.12 закрылось, отчёт не найд…",
          "• JJJJ — дата 01.12", "• облигация — дата 19.11"])
_sum = N.events_summary(ev)
check(f"сводка событий: «Портфель: N событий», пункты «• …» по строкам ({_sum['body']!r})",
      _sum["title"] == f"Портфель: {len(ev)} событий" and all(ln.startswith("• ") for ln in _sum["body"].split("\n"))
      and len(_sum["body"].split("\n")) <= 5 and ";" not in _sum["body"])
_g = N.new_state()
_g["mode"] = "live"
_gp = []
N.process([{"key": f"g{i}", "title": f"Событие {i}", "body": "", "url": "/u", "kind": "monitor", "line": f"пункт {i}"} for i in range(8)],
          _g, MORN, lambda e: _gp.append(e) or True)
check("группа «И ещё N»: пункты по строкам", _gp[-1]["title"] == "И ещё 5 событий" and _gp[-1]["body"].startswith("• пункт 3\n• пункт 4"))
_mon5 = N.check_monitor(None, {"alerts": [{"severity": "HIGH", "category": "c", "target": f"t{i}", "message": f"сообщение {i}"} for i in range(5)]}, "2026-10-16")[0]
check("монитор, 5 сигналов: короткий заголовок, три пункта и «и ещё 2»",
      _mon5["title"] == "Монитор: 5 важных сигналов" and _mon5["body"].endswith("• и ещё 2") and _mon5["body"].count("\n") == 3)
def _hi(t, f=None, sev="HIGH"):
    return {"severity": sev, "category": "stale", "target": t, "target_file": f or f"forecasts/{t}-2026-04-30.yaml", "message": f"сообщение {t}"}


_cm2 = TMP / "cm-mon-sameday"
(_cm2 / "monitor-reports").mkdir(parents=True, exist_ok=True)
(_cm2 / "monitor-reports/monitor-report-2026-10-26.yaml").write_text('generated_at: "2026-10-25T21:40:00Z"\nalerts: [{severity: HIGH, target: old}]\n', encoding="utf-8")
(_cm2 / "monitor-reports/monitor-report-2026-10-26-v2.yaml").write_text('generated_at: "2026-10-26T11:25:00Z"\nalerts: [{severity: HIGH, target: new}]\n', encoding="utf-8")
_mr2 = [r for _, r in N.monitor_reports(_cm2)]
check("два отчёта монитора одного дня: порядок по generated_at — «-v2» (11:25) после исходного (21:40 накануне), база сводки — v2",
      [a["target"] for r in _mr2 for a in r["alerts"]] == ["old", "new"] and N.merge_monitor(_mr2)["alerts"][0]["target"] == "new")
_full = {"alerts": [_hi(f"t{i}") for i in range(1, 9)]}
_part = {"scope": "partial", "checked": ["forecasts/t9-2026-04-30.yaml"], "alerts": [_hi("t9")]}
_m = N.merge_monitor([_full, _part])
check("сводка монитора: 8 полных + частичный по другому файлу = 9", sorted(a["target"] for a in _m["alerts"]) == sorted([f"t{i}" for i in range(1, 10)]))
_ev9 = N.check_monitor(N.merge_monitor([_full]), _m, "2026-10-29")
check("частичный: новым считается только t9, а не все 9", len(_ev9) == 1 and "t9" in _ev9[0]["url"] and "t1" not in _ev9[0]["url"].replace("t9", ""))
_quiet = {"scope": "partial", "checked": ["forecasts/t3-2026-04-30.yaml"], "alerts": []}
check("частичный по checked без предупреждения: t3 пропадает из сводки, остальные на месте",
      sorted(a["target"] for a in N.merge_monitor([_full, _quiet])["alerts"]) == sorted(f"t{i}" for i in (1, 2, 4, 5, 6, 7, 8)))
check("частичный без новых важных — уведомления нет (8 прежних не «возвращаются»)",
      N.check_monitor(N.merge_monitor([_full]), N.merge_monitor([_full, _quiet]), "2026-10-29") == [])
_old = {"alerts": [], "caveats": [{"severity": "INFO", "message": "Запуск по одному файлу (t5): остальные прогнозы не проверялись"}]}
check("без scope, но с оговоркой «Запуск по одному файлу (t5)» — частичный по t5",
      sorted(a["target"] for a in N.merge_monitor([_full, _old])["alerts"]) == sorted(f"t{i}" for i in (1, 2, 3, 4, 6, 7, 8)))
check("отчёт без scope и без оговорки — полный: заменяет картину",
      [a["target"] for a in N.merge_monitor([_full, {"alerts": [_hi("t9")]}])["alerts"]] == ["t9"])
check("полный после частичного снова база", [a["target"] for a in N.merge_monitor([_full, _part, {"alerts": [_hi("z")]}])["alerts"]] == ["z"])
_tp = N.merge_monitor([_full, {"scope": "partial", "checked": ["t2"], "alerts": [_hi("t2", "scenarios/scenario-t2-2026-10-29.yaml")]}])
check("checked по теме (t2) заменяет предупреждение, даже если файл в базе другой даты", [a["target_file"] for a in _tp["alerts"] if a["target"] == "t2"] == ["scenarios/scenario-t2-2026-10-29.yaml"])
check("merge_monitor: пусто → None", N.merge_monitor([]) is None and N.merge_monitor([None]) is None)
_root0 = N.ROOT
N.ROOT = CM
(TMP / "data").mkdir(exist_ok=True)
(TMP / "data/state.json").write_text(json.dumps({**N.new_state(), "mode": "live", "sent": {"verdict:stock:GLRX:2026-10-08": "2026-10-09T08:30:00+03:00"}}))
_tp = []
N.tick(datetime(2026, 10, 16, 8, 30, tzinfo=N.MSK), send=lambda e: _tp.append(e) or True, prices_fn=lambda: {})
check(f"tick: обзор, о котором уже сообщали по бумаге (ключ до сводки), сводкой не дублируется ({[e['title'] for e in _tp]})",
      not any(e["title"].startswith("Акции: смена") for e in _tp) and any(e["title"] == "Портфель: 3 события" or e["title"].startswith("Облигации") for e in _tp))
(TMP / "data/state.json").unlink(missing_ok=True)
# FM-21: итог ежедневного прохода — строка notify-daily в журнале прогонов; сбой — ok=false
_jl = []
_jlog0 = N.jobs.log
N.jobs.log = lambda job, status, started, **x: _jl.append({"job": job, "status": status, **x})
(TMP / "data/state.json").write_text(json.dumps({**N.new_state(), "mode": "live"}))
N.tick(datetime(2026, 10, 17, 8, 30, tzinfo=N.MSK), send=lambda e: True, prices_fn=lambda: {})
_nd = [r for r in _jl if r["job"] == "notify-daily"]
check(f"tick: ежедневный проход пишет одну строку notify-daily с числами ({_nd})",
      len(_nd) == 1 and _nd[0]["ok"] is True and all(isinstance(_nd[0][k], int) for k in ("conds", "events", "pushed", "stale")))
N.tick(datetime(2026, 10, 17, 8, 31, tzinfo=N.MSK), send=lambda e: True, prices_fn=lambda: {})
check("tick: повторный тик в тот же день строку не добавляет", len([r for r in _jl if r["job"] == "notify-daily"]) == 1)
(TMP / "data/state.json").write_text(json.dumps({**N.new_state(), "mode": "live"}))
_cd0 = N.collect_daily
def _boom(*a, **k):
    raise RuntimeError("сбой\nпрохода")
N.collect_daily = _boom
_jl.clear()
try:
    N.tick(datetime(2026, 10, 18, 8, 30, tzinfo=N.MSK), send=lambda e: True, prices_fn=lambda: {})
    _raised = False
except RuntimeError:
    _raised = True
_nd = [r for r in _jl if r["job"] == "notify-daily"]
check(f"tick: сбой collect_daily → строка ok=false с error в одну строку, исключение не глотается ({_nd})",
      _raised and len(_nd) == 1 and _nd[0]["ok"] is False and "RuntimeError" in _nd[0]["error"] and "\n" not in _nd[0]["error"])
try:
    N.tick(datetime(2026, 10, 18, 8, 31, tzinfo=N.MSK), send=lambda e: True, prices_fn=lambda: {})
except RuntimeError:
    pass
check("tick: повтор сбоя в тот же день — в журнал раз в сутки", len([r for r in _jl if r["job"] == "notify-daily"]) == 1)
N.collect_daily = _cd0
N.jobs.log = _jlog0
(TMP / "data/state.json").unlink(missing_ok=True)
N.ROOT = _root0

# ── 3б. «Напоминать заранее»: срок решения, оферта, погашение, конец паузы (по держимым бумагам) ──
print("ahead")
AH = TMP / "ahead"
for d in ("Portfolio/snapshots", "Portfolio/decisions"):
    (AH / d).mkdir(parents=True)


def adec(key, verdict, day, review_by=None):
    return {"schema_version": "decision@1", "id": f"{day}T1000-{key}", "key": key, "verdict": verdict, "target_pct": None,
            "review_by": review_by, "note": "разобрано", "conditions_created": [], "conditions_resolved": [],
            "source": {"kind": "owner", "doc": None, "mode_codes": ["4a"]}, "author": "owner",
            "recorded_at": f"{day}T10:00:00+03:00"}


_adecs = [adec("STK1", "HOLD", "2026-11-01", "2026-11-20"),      # срок 20.11
          adec("STK2", "HOLD", "2026-09-14"),                     # review_by нет: +60 дн. = 13.11
          adec("STK3", "BUY", "2026-10-22", "2026-12-20"),        # пауза докупки 21 дн. от покупки 22.10 → 12.11
          adec("GONE", "HOLD", "2026-09-14", "2026-11-13")]       # решение есть, бумаги в портфеле нет
for _d in _adecs:
    check(f"ahead: решение {_d['key']} проходит схему", DSS.validate_decision(_d) == [])
    (AH / "Portfolio/decisions" / f"{_d['id']}.json").write_text(json.dumps(_d), encoding="utf-8")
(AH / "Portfolio/security-types.json").write_text(json.dumps({"by_ticker": {
    k: {"type": "stock"} for k in ("STK1", "STK2", "STK3", "IPOCO", "GONE")}}), encoding="utf-8")
(AH / "Portfolio/security-attrs.json").write_text(json.dumps({"schema_version": "security-attrs@1", "by_key": {
    "IPOCO": {"ticker_class": "ipo", "listed_at": "2024-11-12"}}}), encoding="utf-8")   # 8 кварталов → 12.11.2026
# история сделок (правило 7 модуля (б), 11.11: пауза — от первой покупки после решения): STK3 куплена 22.10
for _day, _q in (("2026-10-21", 0), ("2026-10-22", 5)):
    (AH / f"Portfolio/snapshots/portfolio-{_day}.json").write_text(json.dumps({"as_of_date": _day, "holdings": [
        {"ticker": "STK3", "qty": _q}]}), encoding="utf-8")
(AH / "Portfolio/snapshots/portfolio-2026-11-01.json").write_text(json.dumps({"holdings": [
    {"ticker": "STK1", "qty": 5}, {"ticker": "STK2", "qty": 5}, {"ticker": "STK3", "qty": 5}, {"ticker": "IPOCO", "qty": 5},
    {"ticker": "RU000B1", "isin": "RU000B1", "name": "ОФЗ 26243", "qty": 10, "offer_date": "2026-11-25", "maturity_date": "2026-11-30"},
    {"ticker": "RU000B2", "isin": "RU000B2", "name": "Эмитент 1Р2", "qty": 3, "maturity_date": "2026-11-15"},
    {"ticker": "RU000B3", "isin": "RU000B3", "name": "Продана", "qty": 0, "offer_date": "2026-11-13", "maturity_date": "2026-11-13"},
    {"ticker": "NEWB", "qty": 5, "first_buy": True}]}), encoding="utf-8")


def ahead(day):
    return {e["key"]: e for e in N.check_ahead(AH, day)}


check("ahead: за 16+ дней молчит всё", ahead("2026-11-04") == {})
_a12 = ahead("2026-11-12")
check(f"ahead 12.11: решение без review_by (срок 13.11) — за 7 дн.; пауза докупки и IPO-пауза — в день окончания; "
      f"оферта 25.11 — за 14; погашение 15.11 — за 7 ({sorted(_a12)})",
      set(_a12) == {"ahead:ahead_review:STK2:2026-11-13:7", "ahead:ahead_pause:STK3:2026-11-12:0",
                    "ahead:ahead_pause:IPOCO:2026-11-12:0", "ahead:ahead_offer:RU000B1:2026-11-25:14",
                    "ahead:ahead_maturity:RU000B2:2026-11-15:7"})
check("ahead: срок STK1 (20.11) на 12.11 ещё не пришёл (8 дн.); не держимые (GONE, qty 0, кандидат первой покупки) молчат",
      not any(k.split(":")[2] in ("STK1", "GONE", "RU000B3", "NEWB") for k in _a12))
check("ahead: вид события и переход — на карточку бумаги",
      {e["kind"] for e in _a12.values()} == {"ahead_review", "ahead_pause", "ahead_offer", "ahead_maturity"}
      and _a12["ahead:ahead_review:STK2:2026-11-13:7"]["url"] == N._card("STK2")
      and _a12["ahead:ahead_offer:RU000B1:2026-11-25:14"]["url"] == N._card("RU000B1"))
check("ahead: пауза докупки накануне ещё не закончилась (11.11 — молчит), на следующий день — тоже",
      not any(e["kind"] == "ahead_pause" for e in ahead("2026-11-11").values())
      and not any(e["kind"] == "ahead_pause" for e in ahead("2026-11-13").values()))
_a13 = ahead("2026-11-13")
check(f"ahead 13.11: STK1 — за 7 дн., STK2 — в день срока (новый порог), оферта 14 — тот же ключ ({sorted(_a13)})",
      "ahead:ahead_review:STK1:2026-11-20:7" in _a13 and "ahead:ahead_review:STK2:2026-11-13:0" in _a13
      and "ahead:ahead_offer:RU000B1:2026-11-25:14" in _a13)
check("ahead: оферта — второй порог за 3 дня (не раньше: на 21.11 ещё 4 дн. — порог 14)",
      "ahead:ahead_offer:RU000B1:2026-11-25:3" in ahead("2026-11-22")
      and "ahead:ahead_offer:RU000B1:2026-11-25:3" not in ahead("2026-11-21"))
check("ahead: погашение — за 7 дн. и не раньше (23.11 — 7 дн. до 30.11; 22.11 — 8)",
      "ahead:ahead_maturity:RU000B1:2026-11-30:7" in ahead("2026-11-23")
      and "ahead:ahead_maturity:RU000B1:2026-11-30:7" not in ahead("2026-11-22"))
check("ahead: после события (оферта прошла) молчит", not any(k.startswith("ahead:ahead_offer") for k in ahead("2026-11-26")))
check("ahead: пороги — в одном словаре AHEAD_DAYS, подмена меняет поведение",
      N.AHEAD_DAYS == {"ahead_review": (7, 0), "ahead_offer": (14, 3), "ahead_maturity": (7,)}
      and not [e for e in N.check_ahead(AH, "2026-11-12", {"ahead_review": (0,), "ahead_offer": (0,), "ahead_maturity": (0,)})
               if e["kind"] in ("ahead_review", "ahead_offer", "ahead_maturity")])
check("ahead: нет снапшота — пусто", N.check_ahead(TMP / "no-such", "2026-11-12") == [])

_ast = N.new_state()
_ast["mode"] = "live"
_ap = []
_arec = N.process(list(_a12.values()), _ast, datetime(2026, 11, 12, 8, 30, tzinfo=MSK), lambda e: _ap.append(e) or True, combine=N.ahead_summary)
check(f"ahead: пять событий — ОДНО уведомление «Напоминания заранее: 5» со списком строк ({[e['title'] for e in _ap]})",
      len(_ap) == 1 and _ap[0]["title"] == "Напоминания заранее: 5" and _ap[0]["body"].count("•") == 5
      and _ap[0]["url"].endswith("#tab=notify"))
check("ahead: в журнале пять записей, каждая со своим видом, сводкой и переходом на бумагу",
      len(_arec) == 5 and {r["kind"] for r in _arec} == {"ahead_review", "ahead_pause", "ahead_offer", "ahead_maturity"}
      and all(r["grouped"] and r["status"] == "sent" and r["url"].startswith(N.VIEWER + "#card=") for r in _arec))
check("ahead: строки сводки — человеческие (бумага, событие, срок)",
      "ОФЗ 26243 — оферта 25.11 (через 13 дн.)" in _ap[0]["body"] and "STK2 — срок решения 13.11 (через 1 дн.)" in _ap[0]["body"]
      and "STK3 — пауза докупки закончилась" in _ap[0]["body"] and "IPOCO — IPO-пауза закончилась" in _ap[0]["body"])
_ap.clear()
N.process(list(ahead("2026-11-12").values()), _ast, datetime(2026, 11, 12, 20, 0, tzinfo=MSK), lambda e: _ap.append(e) or True, combine=N.ahead_summary)
N.process(list(_a13.values()), _ast, datetime(2026, 11, 13, 8, 30, tzinfo=MSK), lambda e: _ap.append(e) or True, combine=N.ahead_summary)
check(f"ahead: дедуп — повтор того же дня молчит, на 13.11 приходят только новые пороги, оферта 14 не повторяется ({[e['title'] for e in _ap]})",
      len(_ap) == 1 and _ap[0]["title"] == "Напоминания заранее: 2" and "оферта" not in _ap[0]["body"])
_ap.clear()
_ast2 = N.new_state()
_ast2["mode"] = "live"
_ast2["off"] = ["ahead_offer", "ahead_pause"]
_arec2 = N.process(list(_a12.values()), _ast2, datetime(2026, 11, 12, 8, 30, tzinfo=MSK), lambda e: _ap.append(e) or True, combine=N.ahead_summary)
check("ahead: выключенные виды не попадают в сводку (остаются «off» в журнале)",
      len(_ap) == 1 and _ap[0]["title"] == "Напоминания заранее: 2" and "оферта" not in _ap[0]["body"] and "IPO" not in _ap[0]["body"]
      and sorted(r["status"] for r in _arec2) == ["off", "off", "off", "sent", "sent"])
_ap.clear()
N.process([_a12["ahead:ahead_review:STK2:2026-11-13:7"]], N.new_state() | {"mode": "live"}, datetime(2026, 11, 12, 8, 30, tzinfo=MSK),
          lambda e: _ap.append(e) or True, combine=N.ahead_summary)
check("ahead: одно событие — как есть, нажатие ведёт на карточку бумаги",
      len(_ap) == 1 and _ap[0]["title"] == "STK2: срок решения" and _ap[0]["url"] == N._card("STK2"))
_tk = TMP / "tickdata"
_data0, _root0 = N.DATA, N.ROOT
N.DATA, N.ROOT = _tk, AH
_ap.clear()
try:
    N.tick(datetime(2026, 11, 12, 8, 30, tzinfo=MSK), send=lambda e: _ap.append(e) or True, prices_fn=lambda: {})
finally:
    N.DATA, N.ROOT = _data0, _root0
check("ahead: утренний tick присылает сводку напоминаний (режим сервера «тихий» — только в журнал)",
      any(r["kind"] == "ahead_pause" for r in json.loads((_tk / "state.json").read_text(encoding="utf-8"))["log"]))


# ── 3в. «Бумага без решения» (no_decision): акции без единого решения, только при «без ИИ» ──
print("no_decision")
ND = TMP / "nodec"
for d in ("Portfolio/snapshots", "Portfolio/decisions"):
    (ND / d).mkdir(parents=True)
_nd = adec("S1", "HOLD", "2026-10-01", "2027-01-01")
(ND / "Portfolio/decisions" / f"{_nd['id']}.json").write_text(json.dumps(_nd), encoding="utf-8")
(ND / "Portfolio/security-types.json").write_text(json.dumps({"by_ticker": {
    k: {"type": t} for k, t in (("S1", "stock"), ("S2", "stock"), ("S3", "stock"), ("S4", "stock"), ("S5", "stock"),
                                ("FND", "fund"), ("RU000N1", "bond"))}}), encoding="utf-8")
(ND / "Portfolio/snapshots/portfolio-2026-11-01.json").write_text(json.dumps({"holdings": [
    {"ticker": "S1", "qty": 5}, {"ticker": "S2", "qty": 5, "name": "Вторая"}, {"ticker": "S3", "qty": 2},
    {"ticker": "S4", "qty": 3, "is_blocked": True, "current_price_source": "cost_basis"},      # заморожена
    {"ticker": "S5", "qty": 3, "current_price_source": "cost_basis"},
    {"ticker": "FND", "qty": 9}, {"ticker": "RU000N1", "isin": "RU000N1", "qty": 4, "asset_type": "bond"},
    {"ticker": "S6", "qty": 0}, {"ticker": "NEWB", "qty": 5, "first_buy": True}]}), encoding="utf-8")
_n_on = N.check_no_decision(ND, "2026-11-12", "on")
_n_off = N.check_no_decision(ND, "2026-11-12", "off")
check("no_decision: при «с ИИ» молчит", _n_on == [])
check(f"no_decision: при «без ИИ» — только акции без решения: S2, S3 ({[e['key'] for e in _n_off]})",
      [e["key"] for e in _n_off] == ["no_decision:S2:2026-11-12", "no_decision:S3:2026-11-12"])
check("no_decision: с решением (S1), заморожённые (S4, S5), облигация/фонд, qty 0, первая покупка — молчат",
      not any(t in e["key"] for e in _n_off for t in ("S1", "S4", "S5", "FND", "RU000N1", "S6", "NEWB")))
check("no_decision: вид, раздел, переход на карточку, без «Сказать Claude»",
      all(e["kind"] == "no_decision" and e["url"] == N._card(e["ticker"]) and "Claude" not in e["body"] for e in _n_off)
      and N.KIND_SECTION["no_decision"] == "portfolio" and "no_decision" in N.KIND_IDS)
_ndp = []
_nst = N.new_state()
_nst["mode"] = "live"
_t0 = datetime(2026, 11, 12, 8, 30, tzinfo=MSK)
N.process(_n_off, _nst, _t0, lambda e: _ndp.append(e) or True, combine=N.no_decision_summary)
check(f"no_decision: две бумаги — ОДНО уведомление со списком ({[e['title'] for e in _ndp]})",
      len(_ndp) == 1 and _ndp[0]["title"] == "Без решения: 2 акции" and _ndp[0]["body"].count("•") == 2
      and "Вторая — нет решения" in _ndp[0]["body"] and _ndp[0]["url"].endswith("#tab=actions"))
_ndp.clear()
_ev1 = N.check_no_decision(ND, "2026-11-15", "off")        # через 3 дня — те же бумаги, но неделя не прошла
_r = N.process(_ev1, _nst, _t0 + timedelta(days=3), lambda e: _ndp.append(e) or True, combine=N.no_decision_summary)
check("no_decision: дедуп — через 3 дня та же бумага не напоминает (suppressed)",
      _ndp == [] and [r["status"] for r in _r] == ["suppressed", "suppressed"])
_ev8 = N.check_no_decision(ND, "2026-11-20", "off")
N.process(_ev8, _nst, _t0 + timedelta(days=8), lambda e: _ndp.append(e) or True, combine=N.no_decision_summary)
check("no_decision: через 8 дней — снова напоминает", len(_ndp) == 1 and _ndp[0]["title"] == "Без решения: 2 акции")
_ndp.clear()
_nst2 = N.new_state() | {"mode": "live", "off": ["no_decision"]}
_r2 = N.process(_n_off, _nst2, _t0, lambda e: _ndp.append(e) or True, combine=N.no_decision_summary)
check("no_decision: выключенный вид молчит (off в журнале)", _ndp == [] and [r["status"] for r in _r2] == ["off", "off"])
(ND / "Portfolio/security-types.json").write_text(json.dumps({"by_ticker": {"S3": {"type": "stock"}}}), encoding="utf-8")
(ND / "Portfolio/snapshots/portfolio-2026-11-01.json").write_text(json.dumps({"holdings": [{"ticker": "S3", "qty": 2}]}), encoding="utf-8")
_ndp.clear()
N.process(N.check_no_decision(ND, "2026-11-12", "off"), N.new_state() | {"mode": "live"}, _t0, lambda e: _ndp.append(e) or True,
          combine=N.no_decision_summary)
check("no_decision: одна бумага — как есть, нажатие ведёт на карточку",
      len(_ndp) == 1 and _ndp[0]["title"] == "S3: нет решения" and _ndp[0]["url"] == N._card("S3"))
check("no_decision: нет снапшота — пусто", N.check_no_decision(TMP / "no-such", "2026-11-12", "off") == [])
_ap.clear()
_data0, _root0 = N.DATA, N.ROOT
N.DATA, N.ROOT = TMP / "tickdata2", ND
_h0 = N.ai_mode
N.ai_mode = lambda root: "off"
try:
    N.tick(datetime(2026, 11, 12, 8, 30, tzinfo=MSK), send=lambda e: True, prices_fn=lambda: {})
finally:
    N.DATA, N.ROOT, N.ai_mode = _data0, _root0, _h0
check("no_decision: утренний tick при «без ИИ» пишет бумагу без решения в журнал",
      any(r["kind"] == "no_decision" for r in json.loads((TMP / "tickdata2/state.json").read_text(encoding="utf-8"))["log"]))


# ── 3г. недельная инфляция (macro): свежее из двух файлов, «Пора внести инфляцию» только при «без ИИ», раз в неделю ──
print("macro_infl")
IN = TMP / "infl"
(IN / "macro-snapshots/inflation").mkdir(parents=True)
(IN / "macro-snapshots").joinpath("ru-2026-01-05.md").write_text("старый срез скилла", encoding="utf-8")


def _il(date_, who, rec_at="2026-11-01T10:00:00+03:00"):
    return json.dumps({"date": date_, "week_pct": 0.1, "week_period": "01–07.11", "yoy_pct": 6.4, "yoy_as_of": date_,
                       "source_url": None, "source_name": "Росстат", "recorded_at": rec_at, "author": who}, ensure_ascii=False)


check("infl_latest: файлов нет — None", N.infl_latest(IN) is None)
(IN / "macro-snapshots/inflation/model.jsonl").write_text(_il("2026-10-28", "model") + "\nне json\n" + _il("2026-11-04", "model") + "\n", encoding="utf-8")
(IN / "macro-snapshots/inflation/owner.jsonl").write_text(_il("2026-10-30", "owner") + "\n", encoding="utf-8")
check("infl_latest: самая свежая по date из двух файлов, битая строка не мешает", N.infl_latest(IN) == ("2026-11-04", "model"))
(IN / "macro-snapshots/inflation/owner.jsonl").write_text(_il("2026-11-04", "owner", "2026-11-05T09:00:00+03:00") + "\n", encoding="utf-8")
check("infl_latest: одна дата в двух файлах — побеждает поздний recorded_at (владелец)", N.infl_latest(IN) == ("2026-11-04", "owner"))
check("infl: при «с ИИ» «Пора внести» молчит даже при просрочке", N.check_inflation_due(IN, "2026-12-01", "on") == [])
check("infl: свежее (9 дн. — граница, не больше порога) — молчит", N.check_inflation_due(IN, "2026-11-13", "off") == [])
_iv = N.check_inflation_due(IN, "2026-11-14", "off")
check("infl: 10 дн. при «без ИИ» — одно событие macro_infl, нажатие — «Макро», без «Сказать Claude»",
      len(_iv) == 1 and _iv[0]["kind"] == "macro_infl" and _iv[0]["title"] == "Пора внести инфляцию"
      and _iv[0]["url"].endswith("#tab=macro") and "Claude" not in _iv[0]["body"] and _iv[0]["rate"] == "macro_infl"
      and "04.11" in _iv[0]["body"] and N.KIND_SECTION["macro_infl"] == "portfolio")
check("infl: записей нет совсем — молчит", N.check_inflation_due(TMP / "no-such", "2026-12-01", "off") == [])
_ip = []
_ist = N.new_state() | {"mode": "live"}
_t = datetime(2026, 11, 14, 8, 30, tzinfo=MSK)
N.process(N.check_inflation_due(IN, "2026-11-14", "off"), _ist, _t, lambda e: _ip.append(e["key"]) or True)
N.process(N.check_inflation_due(IN, "2026-11-17", "off"), _ist, _t + timedelta(days=3), lambda e: _ip.append(e["key"]) or True)
check("infl: раз в неделю — через 3 дня молчит", _ip == ["macro_infl:2026-11-14"])
N.process(N.check_inflation_due(IN, "2026-11-22", "off"), _ist, _t + timedelta(days=8), lambda e: _ip.append(e["key"]) or True)
check("infl: через 8 дней — снова", _ip == ["macro_infl:2026-11-14", "macro_infl:2026-11-22"])
_ip.clear()
N.process(N.check_inflation_due(IN, "2026-11-14", "off"), N.new_state() | {"mode": "live", "off": ["macro_infl"]}, _t, lambda e: _ip.append(e) or True)
check("infl: выключенный вид молчит", _ip == [])
# stale macro: при «с ИИ» — вид stale с командой Claude и «срок вышел»; при «без ИИ» — не stale (его место — macro_infl); ru-*.md не шумит
_sm_on = [e for e in N.check_stale(IN, "2026-11-30", "on") if e["key"].startswith("stale:macro")]
check("stale macro при «с ИИ»: 26 дн. > 16 — fail по инфляции, дата записи, команда Claude",
      len(_sm_on) == 1 and _sm_on[0]["key"] == "stale:macro:2026-11-04:fail" and "обнови инфляцию" in _sm_on[0]["body"] and "срок вышел" in _sm_on[0]["body"])
check("stale macro при «без ИИ»: не stale", not any(e["key"].startswith("stale:macro") for e in N.check_stale(IN, "2026-11-30", "off")))
_old = TMP / "infl-old"
(_old / "macro-snapshots").mkdir(parents=True)
(_old / "macro-snapshots/ru-2026-01-05.md").write_text("старый срез", encoding="utf-8")
check("stale macro: срез скилла ru-*.md больше не считается — молчит, даже когда ему год",
      not any(e["key"].startswith("stale:macro") for e in N.check_stale(_old, "2026-11-30", "on")))
check("infl: пороги — те же 9/16 (SYNC с вьюером и хабом)", N.STALE_WARN_DAYS["macro"] == 9 and N.STALE_FAIL_DAYS["macro"] == 16)
# утренний tick при «без ИИ» пишет «Пора внести инфляцию» в журнал; при «с ИИ» — нет
for _mode in ("off", "on"):
    _d = TMP / f"tickinfl-{_mode}"
    _data0, _root0, _h0 = N.DATA, N.ROOT, N.ai_mode
    N.DATA, N.ROOT = _d, IN
    N.ai_mode = lambda root, m=_mode: m
    try:
        N.tick(datetime(2026, 11, 20, 8, 30, tzinfo=MSK), send=lambda e: True, prices_fn=lambda: {})
    finally:
        N.DATA, N.ROOT, N.ai_mode = _data0, _root0, _h0
    _kinds = [r.get("kind") for r in json.loads((_d / "state.json").read_text(encoding="utf-8"))["log"]]
    check(f"infl: утренний tick при «{'без ИИ' if _mode == 'off' else 'с ИИ'}» — macro_infl в журнале: {_mode == 'off'}",
          ("macro_infl" in _kinds) == (_mode == "off"))


# ── 4. без спама ─────────────────────────────────────────────────────────────
print("dispatch")
now = datetime(2026, 10, 16, 8, 30, tzinfo=MSK)
E = lambda k, t=None: {"key": k, "title": k, "body": "", "url": "/u", "ticker": t, "rate": f"r:{t}" if t else None}  # noqa: E731
sent = []
st = N.new_state()
st["mode"] = "live"
out = N.process([E("a", "SBER"), E("b")], st, now, lambda e: sent.append(e["key"]) or True)
check("отправлено по одному разу", sent == ["a", "b"] and [o["status"] for o in out] == ["sent", "sent"])
out = N.process([E("a", "SBER"), E("b")], st, now + timedelta(hours=1), lambda e: sent.append(e["key"]) or True)
check("повтор ключа не отправляется и не пишется", out == [] and sent == ["a", "b"])
out = N.process([E("a2", "SBER")], st, now + timedelta(days=3), lambda e: sent.append(e["key"]) or True)
check("одинаковое по бумаге за неделю — пропуск", [o["status"] for o in out] == ["suppressed"] and "a2" not in sent)
out = N.process([E("a3", "SBER")], st, now + timedelta(days=8), lambda e: sent.append(e["key"]) or True)
check("через неделю — снова отправляется", [o["status"] for o in out] == ["sent"])
out = N.process([E("f")], st, now, lambda e: False)
check("недоставленное не отработано — повтор", out[0]["status"] == "failed" and "f" not in st["sent"])
out = N.process([E("f")], st, now, lambda e: None)
check("устройств нет — отработано без повторов", out[0]["status"] == "no_devices" and "f" in st["sent"])
sent.clear()
out = N.process([E(f"g{i}") for i in range(7)], st, now, lambda e: sent.append(e["key"]) or True)
check(f"7 событий: 3 по одному + сводка ({sent})", sent == ["g0", "g1", "g2", "group"]
      and sum(1 for o in out if o.get("grouped")) == 4 and all(o["status"] == "sent" for o in out))
q = N.new_state()
sent.clear()
out = N.process([E("q", "SBER")], q, now, lambda e: sent.append(e["key"]) or True)
check("тихий режим (дефолт): журнал, без отправки, отработано", q["mode"] == "quiet" and not sent
      and out[0]["status"] == "quiet" and "q" in q["sent"])
q["mode"] = "live"
out = N.process([E("q", "SBER")], q, now, lambda e: sent.append(e["key"]) or True)
check("включение отправки не вываливает отработанное в тишине", out == [] and not sent)
o = N.new_state()
o["mode"], o["off"] = "live", ["verdict"]
sent.clear()
out = N.process([{**E("v", "GLRX"), "kind": "verdict"}, {**E("m"), "kind": "monitor"}], o, now,
                lambda e: sent.append(e["key"]) or True)
check("выключенный вид — «off», не отправлен, отработан; остальные уходят",
      [x["status"] for x in out] == ["off", "sent"] and sent == ["m"] and "v" in o["sent"])
o["off"] = []
check("включение вида не вываливает накопленное", N.process([{**E("v", "GLRX"), "kind": "verdict"}], o, now, lambda e: True) == [])
check("вид пишется в журнал", out[0]["kind"] == "verdict")
check("виды уведомлений: id, раздел, подпись, пояснение; все виды событий в каталоге",
      all(k.get("id") and k.get("section") in {x["id"] for x in N.SECTIONS} and k.get("label") and k.get("desc") for k in N.KINDS)
      and {"cond_open", "cond_date", "cond_price", "verdict", "monitor", "stale", "eshop", "eshop_sale",
                                                                   "ahead_review", "ahead_offer", "ahead_maturity", "ahead_pause", "no_decision", "macro_infl"} == set(N.KIND_IDS))
check("«Напоминать заранее»: четыре вида портфеля с group ahead, остальные без группы",
      {k["id"] for k in N.KINDS if k.get("group") == "ahead"} == {"ahead_review", "ahead_offer", "ahead_maturity", "ahead_pause"}
      and all(k["section"] == "portfolio" for k in N.KINDS if k.get("group") == "ahead")
      and not any(k.get("group") for k in N.KINDS if not k["id"].startswith("ahead_")))

# ── 5. Web Push ──────────────────────────────────────────────────────────────
print("webpush")
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature  # noqa: E402
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402
from cryptography.hazmat.primitives.kdf.hkdf import HKDF  # noqa: E402

ua = ec.generate_private_key(ec.SECP256R1())
ua_pub = ua.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
auth = b"0123456789abcdef"
msg = json.dumps({"title": "SBER: вердикт HOLD → TRIM"}, ensure_ascii=False).encode()
blob = N.encrypt(msg, N.b64u(ua_pub), N.b64u(auth))


def decrypt(blob):   # сторона браузера, RFC 8291 §3.4 / RFC 8188
    salt, rs, idlen = blob[:16], int.from_bytes(blob[16:20], "big"), blob[20]
    as_pub = blob[21:21 + idlen]
    ct = blob[21 + idlen:]
    shared = ua.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_pub))
    ikm = HKDF(hashes.SHA256(), 32, auth, b"WebPush: info\x00" + ua_pub + as_pub).derive(shared)
    cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
    pt = AESGCM(cek).decrypt(nonce, ct, None)
    return rs, pt


rs, pt = decrypt(blob)
check("aes128gcm расшифровывается по RFC 8291, rs=4096, разделитель последней записи \\x02",
      rs == 4096 and pt == msg + b"\x02")
priv, pub = N.vapid_keys()
priv2, pub2 = N.vapid_keys()
check("ключ VAPID создаётся один раз и переживает перезапуск", pub == pub2 and (TMP / "data/vapid.json").exists())
hdr = N.vapid_header("https://web.push.apple.com/QGx…", priv, pub)
m = re.match(r"^vapid t=([^.]+)\.([^.]+)\.([^,]+), k=(.+)$", hdr)
check("заголовок VAPID: vapid t=…, k=…", bool(m) and m.group(4) == pub)
if m:
    claims = json.loads(N.b64u_dec(m.group(2)))
    sig = N.b64u_dec(m.group(3))
    ok = True
    try:
        pk = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), N.b64u_dec(pub))
        pk.verify(encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")),
                  (m.group(1) + "." + m.group(2)).encode(), ec.ECDSA(hashes.SHA256()))
    except Exception:
        ok = False
    check("подпись ES256 проверяется открытым ключом", ok and len(sig) == 64)
    check("aud — источник подписки, sub — не почта", claims["aud"] == "https://web.push.apple.com"
          and claims["sub"].startswith("https://") and "@" not in claims["sub"])

# ── 6. HTTP ──────────────────────────────────────────────────────────────────
print("http")
pushes = []
N.push_one = lambda sub, message, urgency="normal": pushes.append((sub["endpoint"], message)) or 201
srv, _ = serve(N.Handler, quiet=False)
BASE = f"http://127.0.0.1:{srv.server_address[1]}/api/push/"


def call(path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


SUB = {"endpoint": "https://web.push.apple.com/abc", "keys": {"p256dh": N.b64u(ua_pub), "auth": N.b64u(auth)}}
c, j = call("key")
check("key: открытый ключ и тихий режим по умолчанию", c == 200 and j["public_key"] == pub and j["mode"] == "quiet")
check("subscribe: битая подписка → 400", call("subscribe", {"subscription": {"endpoint": "http://x"}})[0] == 400)
c, j = call("subscribe", {"subscription": SUB, "label": "iPhone"})
c2, j2 = call("subscribe", {"subscription": SUB, "label": "iPhone"})
check("subscribe: повтор того же устройства не дублирует", c == 200 and j2["devices"] == 1)
c, j = call("status?endpoint=" + urllib.parse.quote(SUB["endpoint"]))
check("status: устройство подписано, имя видно", c == 200 and j["subscribed"] and j["devices"][0]["label"] == "iPhone")
check("status: ключей подписки наружу не отдаёт", "keys" not in json.dumps(j) and "p256dh" not in json.dumps(j))
check("status: виды с разделом, разделы со ссылками на журналы (ui-kit uiPushMount)",
      all(k.get("section") in ("portfolio", "games") for k in j["kinds"])
      and [x["id"] for x in j["sections"]] == ["portfolio", "games"])
_lg = [{"ts": "1", "kind": "verdict", "title": "a"}, {"ts": "2", "kind": "eshop_sale", "title": "b"},
       {"ts": "3", "title": "c"}, {"ts": "4", "kind": "eshop", "title": "d"}]
check("журнал по разделу: игры — только виды игр, новые первыми; запись без вида — портфель",
      [r["title"] for r in N.log_for(_lg, "games")] == ["d", "b"]
      and [r["title"] for r in N.log_for(_lg, "portfolio")] == ["c", "a"] and len(N.log_for(_lg)) == 4)
_st = N._read("state.json", None) or N.new_state()
_st["log"] = _st["log"] + [{"ts": "2026-10-26T08:30:00+03:00", "status": "quiet", "title": "Undertale −34%", "body": "",
                            "url": "/tools/games.html#sale", "key": "eshop-sale:x", "kind": "eshop_sale"}]
N._write("state.json", _st)
check("status?section=games: в журнале только игры",
      [r["title"] for r in call("status?section=games")[1]["log"]] == ["Undertale −34%"]
      and all(r.get("kind") != "eshop_sale" for r in call("status?section=portfolio")[1]["log"]))
_h = urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/internal/health", timeout=5)
_hj = json.loads(_h.read())
import codehash  # noqa: E402
check("/internal/health: версия и отпечаток кода — тот же, что считает deploy.zsh (codehash.py по папке)",
      _hj["version"] == N.VERSION and _hj["code"] == codehash.code_hash(REPO / "tools/hosting/notify"))
SUB2 = {**SUB, "endpoint": "https://fcm.googleapis.com/fcm/send/mac"}
call("subscribe", {"subscription": SUB2, "label": "Mac"})
pushes.clear()
c, j = call("test", {"endpoint": SUB["endpoint"]})
check("test: пробное уходит сразу на ВСЕ устройства (и в тихом режиме)",
      c == 200 and sorted(p[0] for p in pushes) == sorted([SUB["endpoint"], SUB2["endpoint"]]) and pushes[-1][1]["tag"] == "test")
check("test: итог по каждому устройству, «это» помечено",
      [(r["label"], r["ok"], r["this"]) for r in j["results"]] == [("iPhone", True, True), ("Mac", True, False)])
_orig = N.push_one
N.push_one = lambda sub, message, urgency="normal": 410 if "mac" in sub["endpoint"] else 201
c, j = call("test", {"endpoint": SUB["endpoint"]})
check("test: отозванная подписка (410) — не ок и удаляется", not j["ok"] and j["removed"] == 1
      and call("status")[1]["devices"] == [{"label": "iPhone", "added": call("status")[1]["devices"][0]["added"]}])
N.push_one = _orig
call("subscribe", {"subscription": SUB2, "label": "Mac"})
call("subscribe", {"subscription": {**SUB, "endpoint": "https://web.push.apple.com/old"}, "label": "iPhone"})
c, j = call("prune", {"keep": SUB["endpoint"]})
check("prune: осталось только это устройство", c == 200 and j["devices"] == 1
      and call("status?endpoint=" + urllib.parse.quote(SUB["endpoint"]))[1]["subscribed"])
c, j = call("prune", {})
check("prune без keep: убраны все", c == 200 and j["devices"] == 0)
call("subscribe", {"subscription": SUB, "label": "iPhone"})
check("mode: мусор → 400", call("mode", {"mode": "loud"})[0] == 400)
check("settings: неизвестный вид → 400", call("settings", {"off": ["spam"]})[0] == 400)
c, j = call("settings", {"off": ["stale", "verdict"]})
c2, j2 = call("status")
check("settings: выключенные виды сохраняются в порядке каталога и видны в status с каталогом",
      c == 200 and j2["off"] == ["verdict", "stale"] and [k["id"] for k in j2["kinds"]] == N.KIND_IDS)
call("settings", {"off": []})
c, j = call("mode", {"mode": "live"})
check("mode: live сохраняется", c == 200 and call("key")[1]["mode"] == "live")
c, j = call("unsubscribe", {"endpoint": SUB["endpoint"]})
check("unsubscribe: устройство удалено", c == 200 and j["devices"] == 0)
check("неизвестный путь → 404", call("nope")[0] == 404)
# ── 7. eShop: оверлей, поиск nsuid ───────────────────────────────────────────
print("eshop overlay + nsuid lookup")
import eshop_lookup as EL  # noqa: E402
_orig_steam = EL.steam_fetch
EL.steam_fetch = lambda t, timeout=15: {"items": []}   # сеть закрыта: Steam по умолчанию — пусто
_wl = {"items": [
    {"title": "Undertale", "status": "хочу", "nsuid_us": 111, "price_target_usd": 10, "store_title": "UT"},
    {"title": "Hades", "status": "на-карандаш", "nsuid_us": "222", "discount_target_pct": -40},
    {"title": "Celeste", "status": "хочу", "nsuid_us": "333"},
    {"title": "Без nsuid", "status": "хочу"}]}
_t0, _s0 = ES.targets(_wl)
check("targets без оверлея как раньше: 3 цели, source watchlist, 1 пропуск",
      len(_t0) == 3 and {t["source"] for t in _t0} == {"watchlist"} and len(_s0) == 1)
_ov = {"items": [
    {"title": "UNDERTALE ", "state": "хочу", "price_target_usd": 7.5},
    {"title": "Hades", "state": "не-интересно"},
    {"title": "Celeste", "state": "хочу", "deleted": True},
    {"title": "Новая игра", "state": "на-карандаш", "nsuid_us": "444", "discount_target_pct": 50, "store_title": "New"},
    {"title": "Куплено", "state": "куплена", "nsuid_us": "555"},
    {"title": "Без nsuid 2", "state": "хочу"}]}
_t1, _s1 = ES.targets(_wl, _ov)
_by = {t["nsuid_us"]: t for t in _t1}
check("оверлей переопределяет порог, nsuid и название берутся из watchlist, source overlay",
      _by["111"]["price_target_usd"] == 7.5 and _by["111"]["source"] == "overlay" and _by["111"]["store_title"] == "UT")
check("оверлей: «не-интересно» и deleted убирают игру из целей", "222" not in _by and "333" not in _by)
check("оверлей добавляет игру вне watchlist (порог −50 → 50), «куплена» не добавляет",
      _by["444"]["discount_target_pct"] == 50 and _by["444"]["source"] == "overlay" and "555" not in _by)
check("пропущенные: без nsuid из оверлея и из watchlist", {s["title"] for s in _s1} == {"Без nsuid", "Без nsuid 2"})
check("targets: нет оверлея/мусор → как без него", ES.targets(_wl, {"items": "x"}) == _t0 or len(ES.targets(_wl, {"items": []})[0]) == 3)

_np = {"urlKey": "hades-switch", "nsuid": 70010000012345, "name": "Hades",
       "platform": {"code": "NINTENDO_SWITCH"}, "productImage": {"publicId": "ncom/en_US/games/hades", "url": "https://x/y"}}
_html = '<html><script id="__NEXT_DATA__" type="application/json">' + json.dumps(
    {"props": {"related": [{"urlKey": "other", "nsuid": 1, "name": "O"}], "product": _np}}) + "</script></html>"
_r = EL.extract(_html, "hades-switch")
check("eshop_lookup.extract: nsuid только своего urlKey, обложка из publicId",
      _r["nsuid_us"] == "70010000012345" and _r["store_title"] == "Hades" and _r["platform"] == "NINTENDO_SWITCH"
      and _r["cover_url"] == "https://assets.nintendo.com/image/upload/f_auto/q_auto/c_scale,w_400/ncom/en_US/games/hades"
      and _r["eshop_url"] == EL.BASE + "hades-switch/")
_np2 = {"urlKey": "g", "nsuid": "7", "name": "G", "productImage": "https://assets.nintendo.com/a.jpg"}
check("cover: строка-URL берётся как есть; нет поля → None; чужой slug → None",
      EL.cover_of(_np2) == "https://assets.nintendo.com/a.jpg" and EL.cover_of({}) is None
      and EL.extract(_html, "nope") is None and EL.extract("<html></html>", "x") is None)
_pages = {"hades-switch": _html}
check("lookup по названию: варианты -switch-2, -switch; по ссылке; нет страницы → None",
      EL.lookup("Hades", lambda s: _pages.get(s))["nsuid_us"] == "70010000012345"
      and EL.lookup("https://www.nintendo.com/us/store/products/hades-switch/?x=1", lambda s: _pages.get(s))["store_title"] == "Hades"
      and EL.lookup("Zzz Game", lambda s: None) is None and EL.lookup("  ") is None)
check("nsuid_lookup: 200 / 404 / 502 / 400",
      N.nsuid_lookup({"title": "Hades"}, lambda s: _pages.get(s))[0] == 200
      and N.nsuid_lookup({"title": "Zzz"}, lambda s: None) == (404, {"error": "не найдено в US eShop"})
      and N.nsuid_lookup({"title": "Hades"}, lambda s: (_ for _ in ()).throw(urllib.error.URLError("down")))[0] == 502
      and N.nsuid_lookup({})[0] == 400)
_orig_fetch = EL.fetch
EL.fetch = lambda s, timeout=15: _pages.get(s)
req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/internal/nsuid-lookup",
                             data=json.dumps({"title": "Hades"}).encode(), method="POST",
                             headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=5) as _rr:
    _jj = json.loads(_rr.read())
    check("HTTP POST /internal/nsuid-lookup → 200 с nsuid и cover_url", _rr.status == 200 and _jj["nsuid_us"] == "70010000012345" and _jj["cover_url"])
req.add_header("X-Forwarded-For", "1.2.3.4")
try:
    urllib.request.urlopen(req, timeout=5)
    check("nsuid-lookup: X-Forwarded-For → 403", False)
except urllib.error.HTTPError as e:
    check("nsuid-lookup: X-Forwarded-For → 403", e.code == 403)
EL.fetch = _orig_fetch

# nsuid_fill: массовый подбор
def _pg(slug, name, nsuid):
    return ('<html><script id="__NEXT_DATA__" type="application/json">' + json.dumps(
        {"props": {"product": {"urlKey": slug, "nsuid": nsuid, "name": name,
                               "productImage": "https://assets.nintendo.com/" + slug + ".jpg"}}}) + "</script></html>")

_fp = {"hades-switch": _pg("hades-switch", "Hades", 1), "celeste-switch": _pg("celeste-switch", "Celeste", 2),
       "mario-switch-2": _pg("mario-switch-2", "Mario", 3)}
_calls = []
def _fg(slug):
    _calls.append(slug)
    if slug.startswith("neterr"):
        raise urllib.error.URLError("down")
    return _fp.get(slug)
_naps = []
_c, _r = N.nsuid_fill({"items": [{"title": "Hades"}, {"title": "Celeste"}, {"title": "Нет такой"}, {"title": "Neterr"}]},
                      _fg, sleep=_naps.append)
check("nsuid_fill: две найдены, 404 → «не найдено», сеть → «сеть», done true",
      _c == 200 and _r["done"] is True and [x.get("nsuid_us") for x in _r["results"][:2]] == ["1", "2"]
      and _r["results"][0]["cover_url"] and _r["results"][2] == {"title": "Нет такой", "error": "не найдено"}
      and _r["results"][3] == {"title": "Neterr", "error": "сеть"})
check("nsuid_fill: пауза 0,7 с между запросами (3 паузы на 4 записи)", _naps == [0.7, 0.7, 0.7])
check("nsuid_fill: лимит 40 → 400, пустой список → 400",
      N.nsuid_fill({"items": [{"title": "x"}] * 41}, _fg, sleep=_naps.append)[0] == 400
      and N.nsuid_fill({"items": [{"title": "x"}] * 40}, lambda s: None, sleep=lambda t: None)[0] == 200
      and N.nsuid_fill({"items": []})[0] == 400 and N.nsuid_fill({})[0] == 400)
_t = [0.0]
def _nap(x): _t[0] += 10
_c, _r = N.nsuid_fill({"items": [{"title": "Hades"}, {"title": "Celeste"}, {"title": "Hades"}, {"title": "Celeste"}]},
                      _fg, sleep=_nap, budget=15, clock=lambda: _t[0])
check("nsuid_fill: бюджет истёк → done false и часть результатов", _c == 200 and _r["done"] is False and 0 < len(_r["results"]) < 4)
_calls.clear()
_c, _r = N.nsuid_fill({"items": [{"title": "Что-то другое", "eshop_url": "https://www.nintendo.com/us/store/products/hades-switch/"}]},
                      _fg, sleep=lambda t: None)
check("nsuid_fill: eshop_url главнее названия (названия не пробуем)", _r["results"][0]["nsuid_us"] == "1" and _calls == ["hades-switch"])
_calls.clear()
N.nsuid_fill({"items": [{"title": "Mario", "platform": "switch2"}]}, _fg, sleep=lambda t: None)
_c2 = list(_calls); _calls.clear()
N.nsuid_fill({"items": [{"title": "Nope", "platform": "switch2"}]}, _fg, sleep=lambda t: None)
check("nsuid_fill: switch2 → slug -switch-2 первым, затем -switch", _c2 == ["mario-switch-2"] and _calls == ["nope-switch-2", "nope-switch"])

EL.fetch = lambda s, timeout=15: _fp.get(s)
req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/internal/nsuid-fill",
                             data=json.dumps({"items": [{"title": "Hades"}, {"title": "Zzz"}]}).encode(), method="POST",
                             headers={"Content-Type": "application/json"})
_orig_pause = N.NSUID_FILL_PAUSE
N.NSUID_FILL_PAUSE = 0
with urllib.request.urlopen(req, timeout=5) as _rr:
    _jj = json.loads(_rr.read())
    check("HTTP POST /internal/nsuid-fill → 200, results и done",
          _rr.status == 200 and _jj["done"] is True and _jj["results"][0]["nsuid_us"] == "1" and _jj["results"][1]["error"] == "не найдено")
req.add_header("X-Forwarded-For", "1.2.3.4")
try:
    urllib.request.urlopen(req, timeout=5)
    check("nsuid-fill: X-Forwarded-For → 403", False)
except urllib.error.HTTPError as e:
    check("nsuid-fill: X-Forwarded-For → 403", e.code == 403)
N.NSUID_FILL_PAUSE = _orig_pause

def _raises(f):
    try:
        f()
    except OSError:
        return True
    return False

# Steam: синтетический ответ storesearch (формат по документации — ПРОВЕРИТЬ НА NAS)
_ss_items = {"total": 3, "items": [
    {"type": "app", "id": 1145350, "name": "Hades II", "tiny_image": "https://x/1.jpg"},
    {"type": "app", "id": 1145360, "name": "Hades", "tiny_image": "https://x/2.jpg"},
    {"type": "app", "id": 504230, "name": "Celeste: Definitive Edition", "tiny_image": "https://x/3.jpg"}]}
_sg = lambda t: _ss_items
_h = EL.steam_lookup("hades", _sg)
check("steam_lookup: точное совпадение имени (не первый «Hades II»), обложка 600x900 и запасной header",
      _h["steam_appid"] == "1145360" and _h["store_title"] == "Hades" and _h["platform"] == "steam"
      and _h["store_url"] == "https://store.steampowered.com/app/1145360/"
      and _h["cover_url"].endswith("/steam/apps/1145360/library_600x900.jpg")
      and _h["cover_fallback_url"].endswith("/steam/apps/1145360/header.jpg"))
check("steam_lookup: суффикс издания и пунктуация не мешают («Celeste» ↔ «Celeste: Definitive Edition»)",
      EL.steam_lookup("CELESTE!", _sg)["steam_appid"] == "504230")
check("steam_lookup: подстрока — первый результат, запрос длиннее имён → None",
      EL.steam_lookup("ades", _sg) is None and EL.steam_lookup("Hades I", lambda t: {"items": _ss_items["items"][:1]}) is None
      and EL.steam_lookup("Hades", lambda t: {"items": _ss_items["items"][:1]})["steam_appid"] == "1145350")
check("steam_lookup: пустой ответ / пустой запрос / битый JSON → None",
      EL.steam_lookup("Hades", lambda t: {"items": []}) is None and EL.steam_lookup("", _sg) is None
      and EL.steam_lookup("Hades", lambda t: {}) is None and EL.steam_lookup("Hades", lambda t: ["x"]) is None)
check("steam_lookup: сеть → None",
      EL.steam_lookup("Hades", lambda t: (_ for _ in ()).throw(urllib.error.URLError("down"))) is None
      and EL.steam_lookup("Hades", lambda t: (_ for _ in ()).throw(ValueError("json"))) is None)

# lookup_any: маршрутизация по платформе
_ecalls, _scalls = [], []
def _eg(slug):
    _ecalls.append(slug)
    return _fp.get(slug)
def _sg2(t):
    _scalls.append(t)
    return _ss_items
_KEYS = {"title", "platform", "store", "nsuid_us", "steam_appid", "store_title", "eshop_url", "store_url",
         "cover_url", "cover_fallback_url"}
_r = EL.lookup_any({"title": "Hades", "platform": "steam_deck"}, _eg, _sg2)
check("lookup_any: steam_deck → только Steam, единый вид",
      set(_r) == _KEYS and _r["store"] == "steam" and _r["steam_appid"] == "1145360" and _r["nsuid_us"] is None
      and _r["eshop_url"] is None and _ecalls == [] and _r["cover_fallback_url"])
for _pl in ("steam", "pc", "xbox"):
    _scalls.clear()
    EL.lookup_any({"title": "Hades", "platform": _pl}, _eg, _sg2)
    check(f"lookup_any: {_pl} → Steam", _scalls == ["Hades"] and _ecalls == [])
_scalls.clear()
_r = EL.lookup_any({"title": "Hades", "platform": "switch"}, _eg, _sg2)
check("lookup_any: switch → eShop (nsuid, store eshop), Steam не трогаем",
      set(_r) == _KEYS and _r["store"] == "eshop" and _r["nsuid_us"] == "1" and _r["steam_appid"] is None
      and _r["store_url"] == _r["eshop_url"] == EL.BASE + "hades-switch/" and _r["cover_url"] and _scalls == [])
_ecalls.clear()
check("lookup_any: switch2 и нет в eShop → None без отката на Steam",
      EL.lookup_any({"title": "Hades", "platform": "switch2"}, lambda s: None, _sg2) is None and _scalls == [])
_ecalls.clear(); _scalls.clear()
_r = EL.lookup_any({"title": "Celeste"}, _eg, _sg2)
check("lookup_any: платформы нет, eShop нашёл → eShop", _r["store"] == "eshop" and _r["nsuid_us"] == "2" and _scalls == [])
_scalls.clear()
_r = EL.lookup_any({"title": "Hades", "platform": None}, lambda s: None, _sg2)
check("lookup_any: платформы нет, eShop пуст → откат на Steam", _r["store"] == "steam" and _r["steam_appid"] == "1145360")
_r = EL.lookup_any({"title": "Hades", "platform": "ps5"}, lambda s: None, _sg2)
check("lookup_any: неизвестная платформа → eShop, затем Steam", _r["store"] == "steam")
check("lookup_any: нигде нет → None; сеть eShop → исключение",
      EL.lookup_any({"title": "Zzz"}, lambda s: None, lambda t: {"items": []}) is None
      and _raises(lambda: EL.lookup_any({"title": "Hades"}, lambda s: (_ for _ in ()).throw(urllib.error.URLError("x")), _sg2)))

# nsuid_fill со смесью платформ
_naps = []
_c, _r = N.nsuid_fill({"items": [{"title": "Hades", "platform": "switch"}, {"title": "Hades", "platform": "pc"},
                                 {"title": "Celeste"}, {"title": "Hades II"}, {"title": "Нет такой", "platform": "steam"}]},
                      _fg, sleep=_naps.append, steam_getter=_sg)
_rs = _r["results"]
check("nsuid_fill: смесь платформ — eShop, Steam, eShop без платформы, откат на Steam, не найдено",
      _c == 200 and _r["done"] is True and len(_naps) == 4 and _naps[0] == 0.7
      and [x.get("store") for x in _rs[:4]] == ["eshop", "steam", "eshop", "steam"]
      and _rs[0]["nsuid_us"] == "1" and _rs[1]["steam_appid"] == "1145360" and _rs[1]["cover_url"]
      and _rs[2]["nsuid_us"] == "2" and _rs[3]["steam_appid"] == "1145350" and _rs[3]["title"] == "Hades II"
      and _rs[4] == {"title": "Нет такой", "error": "не найдено"})
_t = [0.0]
def _nap2(x): _t[0] += 10
_c, _r = N.nsuid_fill({"items": [{"title": "Hades", "platform": "pc"}] * 4}, _fg, sleep=_nap2, budget=15,
                      clock=lambda: _t[0], steam_getter=_sg)
check("nsuid_fill: Steam-запросы тоже идут под бюджет", _r["done"] is False and 0 < len(_r["results"]) < 4)
_c, _r = N.nsuid_lookup({"title": "Hades", "platform": "pc"}, _eg, _sg)
check("nsuid_lookup: platform pc → 200 со Steam (+ старые поля store_title/cover_url)",
      _c == 200 and _r["store"] == "steam" and _r["store_title"] == "Hades" and _r["cover_url"])
EL.steam_fetch = lambda t, timeout=15: _ss_items
req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/internal/nsuid-fill",
                             data=json.dumps({"items": [{"title": "Hades", "platform": "pc"}, {"title": "Hades", "platform": "switch"}]}).encode(),
                             method="POST", headers={"Content-Type": "application/json"})
N.NSUID_FILL_PAUSE = 0
with urllib.request.urlopen(req, timeout=5) as _rr:
    _jj = json.loads(_rr.read())
    check("HTTP POST /internal/nsuid-fill: смесь платформ → steam_appid и nsuid_us",
          _rr.status == 200 and _jj["results"][0]["steam_appid"] == "1145360" and _jj["results"][1]["nsuid_us"] == "1")
N.NSUID_FILL_PAUSE = _orig_pause
EL.steam_fetch = _orig_steam
EL.fetch = _orig_fetch

srv.shutdown()

# ── 7. расписание ────────────────────────────────────────────────────────────
print("schedule")
s0 = N.new_state()
check("утренняя: до 08:30 — нет", not N.daily_due(s0, datetime(2026, 10, 16, 8, 29, tzinfo=MSK)))
check("утренняя: после 08:30 — да (догоняет после перезапуска)", N.daily_due(s0, datetime(2026, 10, 16, 14, 0, tzinfo=MSK)))
check("утренняя: второй раз за день — нет", not N.daily_due({**s0, "last_daily": "2026-10-16"}, datetime(2026, 10, 16, 20, 0, tzinfo=MSK)))
check("ценовая: будни 10:05 — да", N.hourly_due(s0, datetime(2026, 10, 16, 10, 5, tzinfo=MSK)))
check("ценовая: тот же час второй раз — нет", not N.hourly_due({**s0, "last_hourly": "2026-10-16T10"}, datetime(2026, 10, 16, 10, 40, tzinfo=MSK)))
check("ценовая: 19:05 и 09:30 — нет", not N.hourly_due(s0, datetime(2026, 10, 16, 19, 5, tzinfo=MSK))
      and not N.hourly_due(s0, datetime(2026, 10, 16, 9, 30, tzinfo=MSK)))
check("ценовая: суббота — нет", not N.hourly_due(s0, datetime(2026, 10, 17, 12, 5, tzinfo=MSK)))
N.ROOT = CM
N.COND_URL = "http://127.0.0.1:1/api/pv/cond/event/internal"      # hub-api в тесте нет: касание тихо не записывается
for f in ("state.json",):
    (TMP / "data" / f).unlink(missing_ok=True)
got = []
N.tick(datetime(2026, 10, 16, 12, 5, tzinfo=MSK), send=lambda e: got.append(e) or True, prices_fn=lambda: {"FFFF": 13})
st = json.loads((TMP / "data/state.json").read_text())
check(f"tick: hub-api недоступен — события состояния остались в очереди по порядку ({[(b['condition_id'], b['event']) for b in st.get('cond_outbox', [])]})",
      [(b["condition_id"], b["event"]) for b in st.get("cond_outbox", [])]
      == [("iiii-rep", "event_found"), ("iiii-rep", "fired"), ("ffff-trade-notify", "fired")]
      and st["cond_outbox"][-1] == {"condition_id": "ffff-trade-notify", "version": 1, "event": "fired", "by": "notifier",
                                    "data": {"price": 13}}
      and "mf:iiii-rep@1:https://e-disclosure.ru/iiii" in st.get("cond_seen", {}))
check("tick: утренняя и ценовая прошли, отметки поставлены", st["last_daily"] == "2026-10-16"
      and st["last_hourly"] == "2026-10-16T12" and "last_stale" not in st)
check("tick: тихий режим — ничего не ушло, в журнале всё (и сводка просрочек)", not got and len(st["log"]) >= 7
      and all(r["status"] == "quiet" for r in st["log"]) and any(r["kind"] == "stale" for r in st["log"]))
N.tick(datetime(2026, 10, 16, 12, 30, tzinfo=MSK), send=lambda e: got.append(e) or True, prices_fn=lambda: {"FFFF": 13})
check("tick: повторный вызов в тот же час ничего не добавляет",
      len(json.loads((TMP / "data/state.json").read_text())["log"]) == len(st["log"]))

# ── 7б. касание порога = событие fired на внутреннем маршруте hub-api (заглушка) ────
print("touch_condition")
from http.server import BaseHTTPRequestHandler  # noqa: E402

_CF = {"posts": [], "auth": [], "dup": False, "code": 200}


class _Cond(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _CF["posts"].append((self.path, body))
        _CF["auth"].append(self.headers.get("Authorization"))
        out = json.dumps({"duplicate": True} if _CF["dup"] else {"event": body, "events": 1}).encode()
        self.send_response(_CF["code"])
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


_cs, _ = serve(_Cond, quiet=False)
N.COND_URL = f"http://127.0.0.1:{_cs.server_address[1]}/api/pv/cond/event/internal"
_now = datetime(2026, 10, 27, 14, 35, tzinfo=MSK)

check("touch: событие записано → True", N.touch_condition("nvtk-sellgate", 1207, _now, 3) is True)
check("touch: fired, by notifier, цена в data, версия, условие по id; Authorization передан",
      _CF["posts"] == [("/api/pv/cond/event/internal", {"condition_id": "nvtk-sellgate", "event": "fired",
                                                         "by": "notifier", "data": {"price": 1207}, "version": 3})]
      and _CF["auth"] == [N.COND_AUTH])
_CF["dup"] = True
check("touch: сервер ответил duplicate → False (повтор не считается записью)",
      N.touch_condition("nvtk-sellgate", 1250, _now) is False and N.cond_post({"condition_id": "x", "event": "fired"}) == "dup")
_CF.update(dup=False, code=500)
check("touch: сбой сервера → False, без исключения; cond_post → retry", N.touch_condition("nvtk-sellgate", 1, _now) is False
      and N.cond_post({"condition_id": "x", "event": "fired"}) == "retry")
_CF.update(code=400)
check("cond_post: 400 — drop (тело не примут и потом)", N.cond_post({"condition_id": "x", "event": "fired"}) == "drop")
_CF.update(code=200)
_ob = {"cond_outbox": [{"condition_id": "a", "event": "fired"}, {"condition_id": "b", "event": "fired"}]}
_seq = iter(["retry"])
check("очередь: после первого сбоя дальше не идёт (порядок событий важен), всё остаётся",
      N.flush_cond(_ob, lambda b: next(_seq)) == ["retry", "retry"] and len(_ob["cond_outbox"]) == 2)
_CF["posts"].clear()
check("очередь: сервер ожил — отправлено по порядку, очередь пуста",
      N.flush_cond(_ob) == ["ok", "ok"] and _ob["cond_outbox"] == [] and [b["condition_id"] for _, b in _CF["posts"]] == ["a", "b"])

# сквозной утренний проход на T (ждут и сроки, находка, решение) с заглушкой внутреннего маршрута
_CM2 = TMP / "cm2"
for _d in ("Portfolio/decisions", "monitor-reports"):
    (_CM2 / _d).mkdir(parents=True)
(_CM2 / "Portfolio/conditions.yaml").write_text(yaml.safe_dump({"schema_version": "conditions@2", "conditions": DEFS},
                                                                 allow_unicode=True), encoding="utf-8")
(_CM2 / "Portfolio/conditions-state.json").write_text(json.dumps(STATE, ensure_ascii=False), encoding="utf-8")
(_CM2 / "monitor-reports/monitor-report-2026-12-03.yaml").write_text(yaml.safe_dump(
    {"generated_at": "2026-12-03T09:00:00+03:00", "alerts": [], "condition_findings": _MON["condition_findings"]},
    allow_unicode=True), encoding="utf-8")
(_CM2 / "Portfolio/decisions/2026-12-03T1740-AAAA.json").write_text(json.dumps(_DECS[0]), encoding="utf-8")
N.ROOT = _CM2
(TMP / "data/state.json").write_text(json.dumps({**N.new_state(), "mode": "live"}))
_CF["posts"].clear()
_tp2 = []
N.tick(datetime(2026, 12, 4, 8, 30, tzinfo=MSK), send=lambda e: _tp2.append(e) or True, prices_fn=lambda: {})
_b = [b for _, b in _CF["posts"]]
check(f"сквозной: во внутренний маршрут ушли сроки (fired/expired), находка (event_found + fired), решение (done) — все с версией "
      f"({[(b['condition_id'], b['event']) for b in _b]})",
      [(b["condition_id"], b["event"], b["version"]) for b in _b] == [
          ("aaaa-branches", "fired", 1), ("gggg-exp", "expired", 1), ("jjjj-v2", "fired", 2), ("ru000a000aa0-date", "fired", 1),
          ("iiii-rep", "event_found", 1), ("iiii-rep", "fired", 1), ("aaaa-below-100", "done", 1)]
      and _b[-1]["by"] == "decision" and _b[-1]["data"] == {"decision_id": "2026-12-03T1740-AAAA"})
check(f"сквозной: push — «Ждут решения: 3 условия» своим уведомлением, находка — в событиях ({[e['title'] for e in _tp2]})",
      [e["title"] for e in _tp2 if e.get("key") == "cond_open"] == ["Ждут решения: 3 условия"]
      and any(e.get("key") == "cond:iiii-rep@1:fired" for e in _tp2))
_day1 = [b for _, b in _CF["posts"]]
_CF["posts"].clear()
_tp2.clear()
N.tick(datetime(2026, 12, 5, 8, 30, tzinfo=MSK), send=lambda e: _tp2.append(e) or True, prices_fn=lambda: {})
_b = [b for _, b in _CF["posts"]]
check(f"сквозной, назавтра без записи сервера (файл тот же): находка и решение второй раз не шлются (cond_seen), сроки — "
      f"шлются (дубли гасит сервер) ({[(b['condition_id'], b['event']) for b in _b]})",
      [(b["condition_id"], b["event"]) for b in _b] == [(b["condition_id"], b["event"]) for b in _day1[:4]])
(_CM2 / "Portfolio/conditions-state.json").write_text(json.dumps(
    {**STATE, "events": STATE["events"] + [{**b, "at": "2026-12-04T08:30:05+03:00"} for b in _day1]}, ensure_ascii=False), encoding="utf-8")
(TMP / "data/state.json").write_text(json.dumps({**json.loads((TMP / "data/state.json").read_text()), "last_daily": None}))
_CF["posts"].clear()
_tp2.clear()
N.tick(datetime(2026, 12, 6, 8, 30, tzinfo=MSK), send=lambda e: _tp2.append(e) or True, prices_fn=lambda: {})
check(f"сквозной, после записи сервера: событий нет, push по условиям нет ({_CF['posts']} | {[e['title'] for e in _tp2]})",
      _CF["posts"] == [] and not any(str(e.get("key", "")).startswith("cond") for e in _tp2))
(TMP / "data/state.json").unlink(missing_ok=True)
_seen_posts = []
N.tick(datetime(2026, 12, 7, 14, 5, tzinfo=MSK), send=lambda e: True, prices_fn=lambda: {"FFFF": 13, "HHHH": 40},
       post_fn=lambda b: _seen_posts.append(b) or "ok")
check("tick: цена — событие fired с ценой и версией через post_fn; not_before ещё впереди — молчит",
      {"condition_id": "ffff-trade-notify", "version": 1, "event": "fired", "by": "notifier", "data": {"price": 13}} in _seen_posts
      and not any(b["condition_id"] == "hhhh-nb" for b in _seen_posts))
_cs.shutdown()
N.COND_URL = "http://127.0.0.1:1/api/pv/cond/event/internal"
check("touch: hub-api недоступен → False, без исключения", N.touch_condition("nvtk-sellgate", 1, _now) is False)
N.ROOT = CM

# ── 8. контракты хостинга ────────────────────────────────────────────────────
print("hosting contracts")
for name in ("Caddyfile.example", "Caddyfile"):
    p = REPO / "tools/hosting" / name
    if not p.exists():
        continue
    cf = p.read_text(encoding="utf-8")
    check(f"{name}: /api/push/* — в hub-notify:8001", "reverse_proxy @api_push hub-notify:8001" in cf)
    tr = re.search(r"@api_trusted \{(.*?)\}", cf, re.S)
    check(f"{name}: /api/push/* не входит в доверенные IP (пароль и из LAN)", bool(tr) and "/api/push/*" in tr.group(1))
    check(f"{name}: push только после проверки пароля", cf.index("basic_auth @api_auth") < cf.index("reverse_proxy @api_push"))
    pm = re.findall(r"^    @private_(?:auth|noauth) \{(.*?)\}", cf, re.S | re.M)
    check(f"{name}: фоновый скрипт публичен в обоих приватных матчерах",
          len(pm) == 2 and all("/tools/portfolio-sw.js" in b for b in pm))
dc = (REPO / "tools/hosting/docker-compose.yml").read_text(encoding="utf-8")
check("compose: сервис hub-notify с notifier.py, томами данных и зависимостей",
      # с 2026-10-21 папка целиком: notifier.py + задачи сайта (jobs/eshop/macro_job, macro/)
      "container_name: hub-notify" in dc and "./notify:/app:ro" in dc
      and "notify_data:/data" in dc and "notify_deps:/deps" in dc)
check("compose: у hub-notify предел памяти (сборка снапшота не уводит NAS 2 ГБ в своп)",
      re.search(r"container_name: hub-notify.*?mem_limit: \d+m", dc, re.S) is not None)
check("compose: Claude-Memory у hub-notify — только чтение",
      re.search(r"hub-notify:.*?/volume1/homes/hubuser/Claude-Memory:/srv:ro", dc, re.S) is not None)
_pins = re.search(r"cryptography==([\d.]+) pyyaml==([\d.]+)", dc)
check("compose: версии зависимостей зашиты и совпадают с меткой установки",
      bool(_pins) and f".ok-c{_pins.group(1)}-y{_pins.group(2)}" in dc)
_pf = re.search(r"openpyxl==([\d.]+) numbers-parser==([\d.]+)", dc)
check("compose: openpyxl и numbers-parser (сборка снапшота с вьюера) зашиты в метку установки",
      bool(_pf) and f"-ox{_pf.group(1)}-np{_pf.group(2)}" in dc)
dz = (REPO / "tools/deploy.zsh").read_text(encoding="utf-8")
# каждый модуль notify/, который импортирует сервер уведомлений, должен уехать на NAS: zm_stmt.py не выкладывался —
# hub-notify падал при старте на import, страница писала «Сервер уведомлений не отвечает (502)» (2026-11-10)
_ship = set(re.search(r"for f in (notifier\.py[^;]*); do", dz).group(1).replace(".py", "").split())
_local = {q.stem for q in (REPO / "tools/hosting/notify").glob("*.py")}
_need = {"notifier"} | {m for q in (REPO / "tools/hosting/notify").glob("*.py")
                        for m in re.findall(r"^\s*(?:import|from)\s+([a-z_0-9]+)", q.read_text(encoding="utf-8"), re.M) if m in _local}
check("deploy.zsh выкладывает все модули notify/, которые импортирует hub-notify (иначе он не стартует): не хватает "
      + (", ".join(sorted(_need - _ship)) or "—"), not (_need - _ship))
check("deploy.zsh выкладывает notifier.py и фоновый скрипт",
      re.search(r"for f in notifier\.py jobs\.py eshop\.py eshop_lookup\.py macro_job\.py prices_job\.py pf_build\.py stress_job\.py decision_job\.py condition_job\.py codehash\.py zm_csv\.py zm_checks\.py zm_stmt\.py; do", dz) is not None
      and '"$NAS_STAGE/notify/$f"' in dz and re.search(r"^FILES=\(.*portfolio-sw\.js", dz, re.M) is not None)
check("deploy.zsh сверяет отпечаток hub-notify (codehash.py) с /api/health → notify.code и зовёт restart hub-notify",
      'codehash.py" "$NAS_STAGE/notify"' in dz and "sudo docker restart hub-notify" in dz and '"notify"' in dz)
sw = (REPO / "tools/portfolio-sw.js").read_text(encoding="utf-8")
check("фоновый скрипт: уведомление другого раздела (игры) ведёт на свою страницу, не во вьюер",
      "const toViewer = url.includes('/portfolio-integrated-viewer.html')" in sw and "c.navigate(url)" in sw)
vh = (REPO / "tools/portfolio-integrated-viewer.html").read_text(encoding="utf-8")
check("вьюер: манифест, иконка экрана «Домой», кнопка «Уведомления»",
      'rel="manifest"' in vh and 'rel="apple-touch-icon"' in vh and 'id="btn-notify"' in vh)
man = json.loads((REPO / "tools/assets/portfolio-manifest.json").read_text(encoding="utf-8"))
check("манифест: standalone, start_url — вьюер, иконки существуют",
      man["display"] == "standalone" and man["start_url"] == N.VIEWER
      and all((REPO / i["src"].lstrip("/")).exists() for i in man["icons"]))

shutil.rmtree(TMP, ignore_errors=True)
# lookup_any: вставленный адрес страницы Steam → appid из адреса, поиск не зовётся; platform входа сохраняется
_r = EL.lookup_any({"title": "Hades", "platform": "steam_deck",
                    "eshop_url": "https://store.steampowered.com/app/1145360/Hades/"}, getter=None, steam_getter=None)
check("lookup_any: адрес Steam → appid из адреса", _r and _r["steam_appid"] == "1145360" and _r["store"] == "steam")
check("lookup_any: platform входа (steam_deck) сохраняется", _r and _r["platform"] == "steam_deck")
_r2 = EL.lookup_any({"title": "ELDEN RING", "platform": "xbox"},
                    steam_getter=lambda q: {"items": [{"id": 1245620, "name": "ELDEN RING", "tiny_image": ""}]})
check("lookup_any: xbox → Steam-поиск, platform остаётся xbox", _r2 and _r2["steam_appid"] == "1245620" and _r2["platform"] == "xbox")

# lookup_any: код платформы со страницы Nintendo (switch_2) → код кодлиста switch2; явная платформа входа главнее
_e = {"nsuid_us": "70010000099999", "store_title": "X", "eshop_url": "https://www.nintendo.com/us/store/products/x-switch-2/",
      "cover_url": None, "platform": "switch_2"}
_r3 = EL.lookup_any({"title": "X"}, getter=None) if False else None
check("_eshop_plat: switch_2 → switch2, NINTENDO_SWITCH → switch, пусто → None",
      EL._eshop_plat("switch_2") == "switch2" and EL._eshop_plat("NINTENDO_SWITCH") == "switch" and EL._eshop_plat(None) is None)

# ценовой проход: облигация в quotes@1 отдаётся и по SECID, и по ISIN — условия советника по облигации ключуются ISIN (11.11)
_qd = tempfile.mkdtemp()
try:
    _qp = Path(_qd) / "q.json"
    _qp.write_text(json.dumps({"schema": "quotes@1", "items": {
        "SBER": {"price": 300.0}, "SU26243RMFS4": {"price": 67.5, "isin": "RU000A106E90"}, "NOPX": {"price": None}}}), encoding="utf-8")
    _pr = N.fetch_prices(_qp.as_uri())
    check(f"fetch_prices: облигация по SECID и по ISIN, акция по SECID, без цены — нет ({_pr})",
          _pr == {"SBER": 300.0, "SU26243RMFS4": 67.5, "RU000A106E90": 67.5})
finally:
    shutil.rmtree(_qd, ignore_errors=True)

print(f"\nnotifier: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
