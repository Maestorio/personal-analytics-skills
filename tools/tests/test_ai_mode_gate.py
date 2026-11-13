#!/usr/bin/env python3
"""
Гейт «без ИИ» писателей Claude-Memory по происхождению входа (hub_settings.require_ai, задача 1.3 no-ai-mode).

Что держит тест (временный корень Claude-Memory, subprocess с HUB_URL="" HUB_AUTH=""):
  - hub_settings напрямую: find_root по маркерам (`_hub/`, `Portfolio/`+INDEX.md, имя Claude-Memory, путь из файла);
    read(): нет файла → on/default; файл off → off/file; битый файл → on + предупреждение; старый updated_at → stale;
    сеть (локальная заглушка http.server) главнее файла, 403 → падаем на файл; require_ai при off → SystemExit(3);
  - группа А (писатели с входом от модели; 15 команд): при off — код 3, текст гейта в stderr, дерево файлов
    (пути + sha256) не изменилось; без флага — проходят дальше гейта (запись или деловая ошибка, не 3);
  - группа Б (вход от владельца или производные данные): при off НЕ блокируются — код ≠ 3, текста гейта нет;
  - сторож полноты: каждый скрипт группы А содержит `hub_settings.require_ai(`, скрипты группы Б — нет.

Запуск:  python3 tools/tests/test_ai_mode_gate.py      Только stdlib.
"""
import contextlib
import hashlib
import http.server
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "_shared-references"))
import hub_settings as HS  # noqa: E402

SK = REPO / "skills"
GATE_MSG = "сайт в режиме «без ИИ»"
MSK = timezone(timedelta(hours=3))

passed = failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}")


def now_iso(days_ago=0):
    return (datetime.now(MSK) - timedelta(days=days_ago)).isoformat(timespec="seconds")


def settings(mode="off", updated_at=None):
    return {"schema": "hub-settings@1", "ai_mode": mode, "off_since": now_iso() if mode == "off" else None,
            "returned_at": None, "by": "site", "note": None, "updated_at": updated_at or now_iso()}


def write_flag(root, mode="off", updated_at=None):
    os.makedirs(os.path.join(root, "_hub"), exist_ok=True)
    with open(os.path.join(root, "_hub", "settings.json"), "w", encoding="utf-8") as f:
        json.dump(settings(mode, updated_at), f, ensure_ascii=False)


def snap(root):
    h = {}
    for dp, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(dp, f)
            if os.sep + "_hub" + os.sep in p:
                continue
            with open(p, "rb") as fh:
                h[os.path.relpath(p, root)] = hashlib.sha256(fh.read()).hexdigest()
    return h


def wjson(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def wtext(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ---------- 1. hub_settings напрямую ----------

class Stub(http.server.BaseHTTPRequestHandler):
    code = 200
    mode = "on"

    files = None          # ответ /api/hub/changes: список файлов с sha256 (None — без ключа files)

    def do_GET(self):
        if Stub.code != 200:
            self.send_response(Stub.code)
            self.end_headers()
            return
        if self.path.startswith("/api/hub/changes"):
            body = json.dumps({"files": Stub.files, "truncated": False} if Stub.files is not None else {}).encode()
        else:
            body = json.dumps({"settings": settings(Stub.mode)}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def captured(fn, *a):
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        try:
            res = fn(*a)
        except SystemExit as e:
            res = e
    return res, buf.getvalue()


def test_module():
    print("hub_settings")
    saved = {k: os.environ.get(k) for k in ("HUB_URL", "HUB_AUTH")}
    os.environ["HUB_URL"] = ""
    os.environ["HUB_AUTH"] = ""
    base = Path(tempfile.mkdtemp(prefix="ai-gate-mod-")).resolve()
    try:
        # find_root
        r1 = base / "a" / "root1"
        (r1 / "_hub").mkdir(parents=True)
        (r1 / "Deep" / "er").mkdir(parents=True)
        check("find_root: маркер _hub/", HS.find_root(r1) == r1)
        check("find_root: из подпапки", HS.find_root(r1 / "Deep" / "er") == r1)
        r2 = base / "b" / "root2"
        (r2 / "Portfolio").mkdir(parents=True)
        (r2 / "INDEX.md").write_text("x", encoding="utf-8")
        check("find_root: Portfolio/ + INDEX.md", HS.find_root(r2 / "Portfolio") == r2)
        r3 = base / "c" / "Claude-Memory"
        (r3 / "Sub").mkdir(parents=True)
        check("find_root: имя Claude-Memory", HS.find_root(r3 / "Sub") == r3)
        f = r1 / "Deep" / "file.md"
        f.write_text("x", encoding="utf-8")
        check("find_root: из файла внутри", HS.find_root(f) == r1)

        # read без файла / с файлом
        rd = base / "d" / "Claude-Memory"
        rd.mkdir(parents=True)
        i = HS.read(rd)
        check("read: нет файла → on/default", i["ai_mode"] == "on" and i["source"] == "default")
        write_flag(rd, "off")
        i = HS.read(rd)
        check("read: файл off → off/file", i["ai_mode"] == "off" and i["source"] == "file" and not i["stale"])
        check("ai_mode() совпадает", HS.ai_mode(rd) == "off")

        # битый файл
        (rd / "_hub" / "settings.json").write_text("{не json", encoding="utf-8")
        i, err = captured(HS.read, rd)
        check("read: битый файл → on", i["ai_mode"] == "on")
        check("read: битый файл → предупреждение", "не читается" in err)

        # stale
        write_flag(rd, "off", updated_at=now_iso(days_ago=10))
        i, err = captured(HS.read, rd)
        check("read: старше 7 дней → stale", i["stale"] is True and i["ai_mode"] == "off")
        check("read: stale → предупреждение", "старше 7" in err)

        # сеть
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Stub)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            os.environ["HUB_URL"] = f"http://127.0.0.1:{httpd.server_port}"
            os.environ["HUB_AUTH"] = "Bearer t"
            write_flag(rd, "off")
            Stub.code, Stub.mode = 200, "on"
            i = HS.read(rd)
            check("сеть: source network", i["source"] == "network")
            check("сеть главнее файла (сеть on, файл off)", i["ai_mode"] == "on")
            Stub.code = 403
            i = HS.read(rd)
            check("403 → падаем на файл", i["source"] == "file" and i["ai_mode"] == "off")
            Stub.code = 200
            # сверка зеркала перед записью (mirror_lag / guard_mirror в require_ai)
            import hashlib
            (rd / "Portfolio" / "decisions").mkdir(parents=True, exist_ok=True)
            fpath = rd / "Portfolio" / "decisions" / "d1.json"
            fpath.write_text('{"a": 1}', encoding="utf-8")
            good = hashlib.sha256(fpath.read_bytes()).hexdigest()
            write_flag(rd, "on")
            Stub.files = [{"path": "Portfolio/decisions/d1.json", "sha256": good}]
            lag = HS.mirror_lag(rd)
            check("mirror_lag: файл совпал — behind пуст", lag == {"checked": 1, "behind": [], "truncated": False})
            res, err = captured(HS.require_ai, rd, "x.py")
            check("require_ai при совпавшем зеркале → read()", isinstance(res, dict) and res["ai_mode"] == "on")
            Stub.files = [{"path": "Portfolio/decisions/d1.json", "sha256": "0" * 64},
                          {"path": "Gaming/user-state.json", "sha256": "1" * 64}]
            lag = HS.mirror_lag(rd)
            check("mirror_lag: отличие и отсутствие файла → behind из двух", sorted(lag["behind"]) == ["Gaming/user-state.json", "Portfolio/decisions/d1.json"])
            Stub.files = [{"path": "Portfolio/decisions/d1.json", "sha256": "0" * 64},
                          {"path": "Health/labs.json", "sha256": "1" * 64}]
            check("mirror_lag zones=(Health,) → behind только Health/labs.json",
                  HS.mirror_lag(rd, zones=("Health",))["behind"] == ["Health/labs.json"])
            check("mirror_lag zones=(Gaming,) → behind пуст", HS.mirror_lag(rd, zones=("Gaming",))["behind"] == [])
            check("mirror_lag без zones → оба файла", sorted(HS.mirror_lag(rd)["behind"]) == ["Health/labs.json", "Portfolio/decisions/d1.json"])
            res, err = captured(HS.require_ai, rd, "x.py")
            check("require_ai при отстающем зеркале → SystemExit(4)", isinstance(res, SystemExit) and res.code == 4)
            check("require_ai: текст «зеркало Mac отстаёт» с числом файлов", "зеркало Mac отстаёт" in err and "2 файл" in err)
            res, err = captured(HS.guard_mirror, rd, "x.py")
            check("guard_mirror отдельно → SystemExit(4)", isinstance(res, SystemExit) and res.code == 4)
            Stub.files = None
            check("mirror_lag: ответ без files → None (проверить нельзя)", HS.mirror_lag(rd) is None)
            res, err = captured(HS.require_ai, rd, "x.py")
            check("require_ai без сверки (нет files) → read()", isinstance(res, dict))
            Stub.code = 403
            check("mirror_lag: 403 → None", HS.mirror_lag(rd) is None)
            Stub.code = 200
            os.environ["HUB_URL"] = ""
            check("mirror_lag: без HUB_URL → None", HS.mirror_lag(rd) is None)
            write_flag(rd, "off")
        finally:
            httpd.shutdown()
            httpd.server_close()

        # require_ai
        (res, err) = captured(HS.require_ai, rd, "x.py")
        check("require_ai off → SystemExit(3)", isinstance(res, SystemExit) and res.code == 3)
        check("require_ai off → текст в stderr", GATE_MSG in err and "x.py" in err)
        write_flag(rd, "on")
        res, err = captured(HS.require_ai, rd, "x.py")
        check("require_ai on → read()", isinstance(res, dict) and res["ai_mode"] == "on" and GATE_MSG not in err)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(base, ignore_errors=True)


# ---------- фикстуры корня ----------

REPORT_MD = "---\ntype: x\n---\nbody\n"
INDEX_MD = "# I\n\n### weekly-reviews/\n\n| a | b |\n|---|---|\n| x | y |\n\n## Метаданные\n\n- Обновлено: z\n"
MAP_MD = "# map\n\n## Поездки\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n## Мета\n\n- Обновлено: x\n- Предыдущая версия: -\n"
DRAFT_MD = ("---\nschema: health-report@1\ntitle: Общий отчёт\ndate: 2026-09-29\ndata_asof: 2026-09-20\n"
            "summary: Острых отклонений нет.\nflags:\n  - ok | Щитовидная железа | ТТГ в норме\ntodo:\n  - Сдать липидограмму\n"
            "markers: ldl\n---\n\n# Общий отчёт\n\nТекст.\n")
MEDS = {"schema": "health-meds@1", "updated": "2026-07-17", "meds": [{
    "id": "atorvastatin", "name": "Аторвастатин", "inn": "", "for": "", "class": "", "dose": "20 мг", "regimen": "",
    "timing": "", "form": "", "taking": True, "prescribedBy": "", "expiry": "", "affects": [], "indications": "",
    "interactions": "", "notes": ""}]}
ENRICH_MEDS = {"atorvastatin": {"fields": {"inn": "аторвастатин", "class": "статин"}, "confidence": "high",
                                "sources": [{"title": "ГРЛС", "url": "https://g/1", "fetched": "2026-11-09"}]}}
ENRICH_LABS = {"ldl": {"what": ["Что измеряет."], "up": "Причины.", "down": "Причины."}}
LABS = {"schema": "health-labs@1", "biomarkers": [{"id": "ldl", "name": "ldl", "category": "lipid", "kind": "num",
                                                    "unit": "", "ref": None, "series": []}]}
INFO = {"schema": "health-biomarkers-info@1", "generated": "2026-01-01", "info": {}}
HISTORY = {"schema": "zenmoney-audit@1", "updated": "2026-11-01",
           "records": [{"month": "2026-01", "as_of": "2026-02-01"}], "issues": {}}


def mk_root(t):
    for d in ("Portfolio/reports", "ZenMoney/audit", "Health", "travel-planner"):
        os.makedirs(os.path.join(t, *d.split("/")))
    wtext(t + "/Portfolio/reports/r.md", REPORT_MD)
    wtext(t + "/Portfolio/INDEX.md", INDEX_MD)
    wtext(t + "/_sync_log.md", "log\n")
    wtext(t + "/ZenMoney/zenmoney-map.md", MAP_MD)
    wjson(t + "/ZenMoney/audit/history.json", HISTORY)
    wjson(t + "/ZenMoney/audit/run.json", {})
    wjson(t + "/Health/meds.json", MEDS)
    wjson(t + "/Health/enrich_meds.json", ENRICH_MEDS)
    wjson(t + "/Health/enrich.json", ENRICH_LABS)
    wjson(t + "/Health/labs.json", LABS)
    wjson(t + "/Health/biomarkers-info.json", INFO)
    wtext(t + "/Health/draft.md", DRAFT_MD)
    wtext(t + "/travel-planner/main.md", "## КАРТОЧКА 1\n\n1. **URL:** https://a.com\n")
    wtext(t + "/travel-planner/add.md", "## КАРТОЧКА 2\n\n1. **URL:** https://b.com\n")
    wjson(t + "/ZenMoney/stmt-places.json", {"orders": []})


def sc(rel, *a):
    return [sys.executable, str(SK / rel)] + list(a)


# (имя, argv, stdin-шаблон, [файлы, которые обязаны появиться/измениться без флага], только_код_3_при_off)
GROUP_A = [
    ("assemble_artifact stamp-report", sc("save-to-library/scripts/assemble_artifact.py", "stamp-report", "--root", "{T}",
                                          "--doc", "Portfolio/reports/r.md"), None, 0),
    ("update_index add-meta", sc("save-to-library/scripts/update_index.py", "add-meta"),
     json.dumps({"index_path": "{T}/Portfolio/INDEX.md", "line": "2026-11-09 test"}), 0),
    ("update_index sync-log", sc("save-to-library/scripts/update_index.py", "sync-log"),
     json.dumps({"log_path": "{T}/_sync_log.md", "entries": ["2026-11-09 | t"]}), 0),
    ("build_snapshot --commit --working", sc("portfolio-data-loader/scripts/build_snapshot.py", "--commit", "--working",
                                             "--memory", "{T}", "--as-of", "2026-11-09", "--no-iis-search"), None, 1),
    ("validate_meds merge --apply", sc("health-meds/scripts/validate_meds.py", "merge", "--meds", "{T}/Health/meds.json",
                                       "--enrich", "{T}/Health/enrich_meds.json", "--apply"), None, 0),
    ("validate_labs_info merge --apply", sc("health-labs/scripts/validate_labs_info.py", "merge", "--info",
                                            "{T}/Health/biomarkers-info.json", "--enrich", "{T}/Health/enrich.json",
                                            "--labs", "{T}/Health/labs.json", "--today", "2026-11-09", "--apply"), None, 0),
    ("validate_report save --apply", sc("health-labs/scripts/validate_report.py", "save", "{T}/Health/draft.md", "--health",
                                        "{T}/Health", "--topic", "Общий отчёт", "--apply"), None, 0),
    ("map_edit add-row --write", sc("zenmoney-analyst/scripts/map_edit.py", "add-row", "--map", "{T}/ZenMoney/zenmoney-map.md",
                                    "--section", "Поездки", "--row", "| 3 | 4 |", "--expect", "{SHA}", "--write"), None, 0),
    ("stmt_propose places-add", sc("zenmoney-analyst/scripts/stmt_propose.py", "places-add", "--file",
                                   "{T}/ZenMoney/stmt-places.json", "--key", "КАФЕ", "--category", "Кафе"), None, 0),
    ("audit_history rules --write", sc("zenmoney-analyst/scripts/audit_history.py", "rules", "--rules",
                                       "{T}/ZenMoney/audit/rules.json", "--one-off", "id1", "2026-10", "note",
                                       "--date", "2026-11-09", "--write"), None, 0),
    ("audit_history accept --write", sc("zenmoney-analyst/scripts/audit_history.py", "accept", "--accepted",
                                        "{T}/ZenMoney/audit/accepted.json", "--add", "id1", "A1", "reason",
                                        "--date", "2026-11-09", "--write"), None, 0),
    ("audit_history redate --write", sc("zenmoney-analyst/scripts/audit_history.py", "redate", "--history",
                                        "{T}/ZenMoney/audit/history.json", "--month", "2026-01", "--date", "2026-11-09",
                                        "--write"), None, 0),
    ("audit_history apply --write", sc("zenmoney-analyst/scripts/audit_history.py", "apply", "--run",
                                       "{T}/ZenMoney/audit/run.json", "--history", "{T}/ZenMoney/audit/history.json",
                                       "--date", "2026-11-09", "--write"), None, 2),
    ("merge_dr_additions --inplace", sc("travel-planning/scripts/merge_dr_additions.py", "{T}/travel-planner/main.md",
                                        "{T}/travel-planner/add.md", "--inplace"), None, 0),
    ("save_inflation --apply", sc("macro-ru-watcher/scripts/save_inflation.py", "--root", "{T}", "--date", "2026-11-09",
                                  "--week-pct", "0.11", "--week-period", "03–09.11", "--yoy-pct", "6.4", "--source-name",
                                  "Росстат", "--today", "2026-11-12", "--apply"), None, 0),
]
# build_snapshot без флага: код 1 (нет --trades/--balance); audit_history apply: пустой run — деловая ошибка (≠ 3)
BUSINESS_RC = {"build_snapshot --commit --working": 1}


def run_case(argv, stdin, T, env_extra=None):
    sha = hashlib.sha256(Path(T, "ZenMoney", "zenmoney-map.md").read_bytes()).hexdigest()
    a = [x.replace("{T}", T).replace("{SHA}", sha) for x in argv]
    env = {**os.environ, "HUB_URL": "", "HUB_AUTH": ""}
    return subprocess.run(a, input=(stdin.replace("{T}", T) if stdin else ""), capture_output=True, text=True,
                          env=env, timeout=120)


def test_group_a():
    print("группа А: off блокирует, без флага проходит")
    for name, argv, stdin, _ in GROUP_A:
        T = tempfile.mkdtemp(prefix="ai-gate-a-")
        try:
            mk_root(T)
            write_flag(T, "off")
            before = snap(T)
            r = run_case(argv, stdin, T)
            check(f"{name}: off → код 3", r.returncode == 3)
            check(f"{name}: off → текст гейта в stderr", GATE_MSG in r.stderr)
            check(f"{name}: off → дерево не изменилось", snap(T) == before)
        finally:
            shutil.rmtree(T, ignore_errors=True)
        T = tempfile.mkdtemp(prefix="ai-gate-a-")
        try:
            mk_root(T)
            before = snap(T)
            r = run_case(argv, stdin, T)
            check(f"{name}: без флага → не код 3", r.returncode != 3 and GATE_MSG not in r.stderr)
            if name == "build_snapshot --commit --working":
                check(f"{name}: без флага → код 1 про --trades/--balance",
                      r.returncode == 1 and ("--trades" in r.stderr + r.stdout and "--balance" in r.stderr + r.stdout))
            elif name == "audit_history apply --write":
                check(f"{name}: без флага → деловой отказ (пустой run), не гейт", r.returncode != 0)
            else:
                check(f"{name}: без флага → код 0 (stderr: {r.stderr[-120:].strip()!r})", r.returncode == 0)
                check(f"{name}: без флага → файл записан", snap(T) != before)
        finally:
            shutil.rmtree(T, ignore_errors=True)


# ---------- группа Б ----------

def mk_conditions_root(t):
    sys.path.insert(0, str(REPO / "tools" / "data-structures" / "migrations"))
    import ds_schemas as ds
    import migrate_conditions_v2 as mg
    port = os.path.join(t, "Portfolio")
    os.makedirs(os.path.join(port, "reports"), exist_ok=True)
    defs, state, _, _ = mg.migrate(ds.load_yaml(str(REPO / "tools/data-structures/tests/fixtures/conditions_v12.yaml")))
    wtext(os.path.join(port, "conditions.yaml"), mg._dump_yaml(defs))
    wjson(os.path.join(port, "conditions-state.json"), state)


PRICE_ADD = {
    "key": "GGGG", "kind": "trade", "trigger": {"type": "price_below", "value": 100},
    "while_pending": {"verdict": "HOLD"},
    "on_trigger": {"action": "set_target_pct", "verdict": "BUY", "target_pct": 4, "text": "докупить до плана"},
    "source": {"kind": "report", "doc": "Portfolio/reports/r.md", "decision_id": "2026-10-31T1200-GGGG"},
}
SA_DOC = {"schema_version": "security-attrs@1", "by_key": {
    "MDMG": {"ticker_class": "ipo", "listed_at": "2024-12-18", "note": "x", "updated_at": "2026-10-31T12:00:00+03:00",
             "updated_by": "script"}}}
NOW = "2026-12-31T17:40:00+03:00"


def test_group_b():
    print("группа Б: off не блокирует")
    cases = []

    def case(name, build, argv_fn, stdin=None, expect0=True):
        cases.append((name, build, argv_fn, stdin, expect0))

    case("decision_write owner",
         mk_conditions_root,
         lambda T: sc("save-to-library/scripts/decision_write.py", "owner", "--key", "AAAA", "--verdict", "BUY",
                      "--target-pct", "5", "--review-by", "2027-03-01", "--note", "владелец решил докупить",
                      "--keep-open", "aaaa-branches", "--root", T, "--now", NOW))
    case("apply_condition add --by owner",
         mk_conditions_root,
         lambda T: sc("save-to-library/scripts/apply_condition.py", "add", "--root", T, "--today", "2026-10-31",
                      "--by", "owner", "--now", "2026-10-31T12:00:00+03:00"),
         json.dumps(PRICE_ADD, ensure_ascii=False))
    case("security_attrs set",
         lambda T: (os.makedirs(T + "/Portfolio", exist_ok=True), wjson(T + "/Portfolio/security-attrs.json", SA_DOC)),
         lambda T: sc("save-to-library/scripts/security_attrs.py", "set", "--key", "MDMG", "--class", "mid_cap",
                      "--by", "owner", "--root", T, "--now", "2026-10-31T12:00:00+03:00"))
    case("known_splits add",
         lambda T: None,
         lambda T: sc("portfolio-data-loader/scripts/known_splits.py", "add", "--file", T + "/known-splits.json",
                      "--ticker", "XSPL", "--date", "2026-01-15", "--ratio", "10"))
    case("audit_history facts --write",
         lambda T: (os.makedirs(T + "/ZenMoney/audit", exist_ok=True),
                    wjson(T + "/ZenMoney/audit/spending.json", {"schema": "zenmoney-spending@1", "months": []})),
         lambda T: sc("zenmoney-analyst/scripts/audit_history.py", "facts", "--spending",
                      T + "/ZenMoney/audit/spending.json", "--write"), expect0=False)
    case("intake mark --apply",
         lambda T: (os.makedirs(T + "/Health", exist_ok=True), os.makedirs(T + "/src", exist_ok=True),
                    wjson(T + "/Health/labs.json", LABS), wjson(T + "/Health/studies.json", {"studies": []}),
                    Path(T, "src", "2023-03-14 Общий белок.pdf").write_bytes(b"%PDF-1.4 x")),
         lambda T: sc("health-labs/scripts/intake.py", "--health", T + "/Health", "--src", T + "/src",
                      "--today", "2026-09-30", "mark", "2023-03-14 Общий белок.pdf", "--note", "Ornament/CSV", "--apply"))
    for name, build, argv_fn, stdin, expect0 in cases:
        T = tempfile.mkdtemp(prefix="ai-gate-b-")
        try:
            build(T)
            write_flag(T, "off")
            before = snap(T)
            env = {**os.environ, "HUB_URL": "", "HUB_AUTH": ""}
            r = subprocess.run(argv_fn(T), input=stdin or "", capture_output=True, text=True, env=env, timeout=120)
            check(f"{name}: off → не код 3 (rc={r.returncode}, {r.stderr[-100:].strip()!r})", r.returncode != 3)
            check(f"{name}: off → нет текста гейта", GATE_MSG not in r.stderr + r.stdout)
            if expect0:
                check(f"{name}: off → код 0", r.returncode == 0)
                check(f"{name}: off → запись произошла", snap(T) != before)
        finally:
            shutil.rmtree(T, ignore_errors=True)


# ---------- сторож полноты ----------

A_FILES = ["save-to-library/scripts/assemble_artifact.py", "save-to-library/scripts/update_index.py",
           "save-to-library/scripts/promote_draft.py", "save-to-library/scripts/decision_write.py",
           "save-to-library/scripts/apply_condition.py", "portfolio-data-loader/scripts/build_snapshot.py",
           "health-meds/scripts/validate_meds.py", "health-labs/scripts/validate_labs_info.py",
           "health-labs/scripts/validate_report.py", "zenmoney-analyst/scripts/map_edit.py",
           "zenmoney-analyst/scripts/stmt_propose.py", "zenmoney-analyst/scripts/audit_history.py",
           "travel-planning/scripts/merge_dr_additions.py", "macro-ru-watcher/scripts/save_inflation.py"]
B_NAMES = ["intake.py", "apple_health_bp.py", "build_health_json.py", "zenmoney_csv_backfill.py", "security_attrs.py",
           "numbers_to_plan.py", "known_splits.py"]


def test_watchdog():
    print("сторож полноты")
    for rel in A_FILES:
        p = SK / rel
        check(f"А: {rel} содержит require_ai", p.is_file() and "hub_settings.require_ai(" in p.read_text(encoding="utf-8"))
    for rel in A_FILES:
        t = (SK / rel).read_text(encoding="utf-8")
        calls = [t[i:i + 400] for i in [m.start() for m in __import__("re").finditer(r"hub_settings\.require_ai\(", t)]]
        check(f"А: {rel} — каждый require_ai с zones=", bool(calls) and all("zones=" in c.split("\n\n")[0][:400] for c in calls))
    for name in B_NAMES:
        found = [p for root in (SK, REPO / "tools") for p in root.rglob(name) if "tests" not in p.parts]
        check(f"Б: {name} найден", bool(found))
        for p in found:
            check(f"Б: {p.relative_to(REPO)} без require_ai", "hub_settings.require_ai(" not in p.read_text(encoding="utf-8"))


test_module()
test_group_a()
test_group_b()
test_watchdog()

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
