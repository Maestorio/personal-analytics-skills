#!/usr/bin/env python3
"""
Тесты write-API sidecar (tools/hosting/api/server.py) Personal Hub.

Юнит-слой: norm_path (traversal/абсолютные/бэкслэши), whitelist путей,
save_file (409-конфликт по base_hash, бэкап в .versions/, атомарная запись),
validate_health (схемы health-meds@1 / health-vaccinations@1 / health-vitals@1).
E2E-слой: живой сервер (_pages_stand.serve) на эфемерном порту — health / file / save
/ конфликт / не-whitelist / битое тело; health-зона /api/hd/* на ВТОРОМ корне
(изоляция от Claude-Memory, отказ на битую схему без порчи файла).

Запуск:
    python3 tools/tests/test_write_api.py
Только stdlib.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "tools/hosting/api"))

import server  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pages_stand import serve  # noqa: E402  (стенд — _pages_stand, keep-alive)

passed = 0
failed = 0


def check(name: str, cond: bool) -> None:
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}")


# ── norm_path ────────────────────────────────────────────────────────────────
print("norm_path")
check("простой путь", server.norm_path("travel-planner/trips/x/3_a.md") == "travel-planner/trips/x/3_a.md")
check("ведущий слэш срезается", server.norm_path("/travel-planner/trips/x/3_a.md") == "travel-planner/trips/x/3_a.md")
check("нормализация ./", server.norm_path("travel-planner/./trips/x/3_a.md") == "travel-planner/trips/x/3_a.md")
check("traversal ..", server.norm_path("../etc/passwd") is None)
check("traversal внутри", server.norm_path("Gaming/../../etc/passwd") is None)
check("пустой", server.norm_path("") is None)
check("None", server.norm_path(None) is None)
check("бэкслэш", server.norm_path("Gaming\\recommendations\\a.md") is None)
check("NUL", server.norm_path("Gaming/a\x00.md") is None)
check("голая точка", server.norm_path(".") is None)

# ── whitelist ────────────────────────────────────────────────────────────────
print("whitelist")
check("stage 3 md разрешён", server.is_allowed("travel-planner/trips/регион_a_2027/3_poi_v2.md"))
check("stage 4 md разрешён", server.is_allowed("travel-planner/trips/вьетнам/4_variants.md"))
check("stage 3 big-story разрешён", server.is_allowed("travel-planner/trips/x/3_big-story.md"))
check("Gaming/recommendations больше не в whitelist (кнопки «итог» нет)", not server.is_allowed("Gaming/recommendations/x.md"))
# Stage 5/6 открыты с 2026-08 — навигационный слой экспорта пишет туда отметки
# подготовки («- [x] Выкупить билеты»): состояние живёт в строке плана, поэтому
# переживает пересборку HTML и попадает в PDF. Правится только символ в скобках.
check("stage 5 md разрешён (отметки подготовки)",
      server.is_allowed("travel-planner/trips/x/5_final_plan_v4.md"))
check("stage 6 md разрешён", server.is_allowed("travel-planner/trips/x/6_final_v1.md"))
check("stage 0 по-прежнему запрещён",
      not server.is_allowed("travel-planner/trips/x/0_scope.md"))
check("stage 2 по-прежнему запрещён",
      not server.is_allowed("travel-planner/trips/x/2_similarity.md"))
check("_archive запрещён (глубина)", not server.is_allowed("travel-planner/trips/x/_archive/3_old.md"))
check("Portfolio запрещён", not server.is_allowed("Portfolio/snapshots/portfolio-2026-07-01.json"))
# зона задач сайта (JOB_WHITELIST): сплиты, веса сценариев стресса и пересчёт стресса с сайта — ровно три пути
_jok = lambda p: server.is_allowed(p, server.JOB_WHITELIST)   # noqa: E731
check("job: known-splits.json разрешён", _jok("Portfolio/known-splits.json"))
check("job: веса стресса разрешены", _jok("scenarios/stress-weights-scenario-geopolitics-ru-west-2026-07-01.json"))
check("job: пересчёт стресса в auto/ разрешён", _jok("Portfolio/stress/auto/recalc-stress-2026-11-04-geopol-ru-west-shell-d1.yaml"))
check("job: справочник бумаг разрешён, соседи нет", _jok("Portfolio/security-attrs.json")
      and not _jok("Portfolio/security-attrs.json.tmp") and not _jok("Portfolio/sub/security-attrs.json"))
check("job: сроки сайта разрешены", _jok("scenarios/horizons.json"))
check("job: соседи файла сроков запрещены", not _jok("scenarios/horizons.json.tmp") and not _jok("scenarios/sub/horizons.json")
      and not _jok("scenarios/horizons.yaml"))
def _raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False


# дневной ряд цен закрытия (prices_job): один файл на год, только hub-notify
check("job: ряд цен daily-ГГГГ.jsonl разрешён", _jok("Portfolio/prices/daily-2026.jsonl"))
check("job: ряд цен — соседи и чужие имена запрещены",
      not _jok("Portfolio/prices/daily-26.jsonl") and not _jok("Portfolio/prices/daily-2026.json")
      and not _jok("Portfolio/prices/daily-2026.jsonl.tmp") and not _jok("Portfolio/prices/sub/daily-2026.jsonl")
      and not _jok("Portfolio/prices/daily-2026-11.jsonl") and not _jok("Portfolio/prices/index.jsonl"))
check("job: ряд цен — каждая строка обязана быть JSON",
      server.validate_job("Portfolio/prices/daily-2026.jsonl", '{"date":"2026-11-11"}\n{"date":"2026-11-12"}\n') is None
      and _raises(lambda: server.validate_job("Portfolio/prices/daily-2026.jsonl", '{"a":1}\nне json\n')))
# решение владельца с карточки бумаги (decision_job): файл-запись {дата}T{ЧЧММ}-{KEY}.json — только в Portfolio/decisions/
check("job: решение владельца разрешено", _jok("Portfolio/decisions/2026-11-11T1015-GMKN.json")
      and _jok("Portfolio/decisions/2026-11-11T1015-RU000A10AFA3.json") and _jok("Portfolio/decisions/2026-11-11T1015-X5.json")
      and _jok("Portfolio/decisions/2026-11-11T1015-BRK.B.json"))
check("job: решение — соседи и чужие имена запрещены",
      not _jok("Portfolio/decisions/2026-11-11T1015-gmkn.json") and not _jok("Portfolio/decisions/2026-11-11T1015-.json")
      and not _jok("Portfolio/decisions/2026-11-11T101-GMKN.json") and not _jok("Portfolio/decisions/2026-11-11-GMKN.json")
      and not _jok("Portfolio/decisions/sub/2026-11-11T1015-GMKN.json") and not _jok("Portfolio/decisions/2026-11-11T1015-GMKN.json.tmp")
      and not _jok("Portfolio/decisions/2026-11-11T1015-GM_KN.json") and not _jok("Portfolio/decisions/index.json")
      and not _jok("Portfolio/decisions.json") and not _jok("Portfolio/decisions/../conditions.yaml"))
# условие-напоминание владельца (condition_job, POST /api/pf/condition): файл условий — только этот путь, с base_hash
check("job: файл условий Portfolio/conditions.yaml разрешён", _jok("Portfolio/conditions.yaml"))
check("job: файл условий — соседи запрещены (состояние пишет только hub-api, архивы и бэкапы — никто)",
      not _jok("Portfolio/conditions-state.json") and not _jok("Portfolio/conditions-archive-2026.yaml")
      and not _jok("Portfolio/conditions.yaml.bak") and not _jok("Portfolio/conditions.yml")
      and not _jok("Portfolio/sub/conditions.yaml") and not _jok("conditions.yaml"))
check("job: стресс скилла запрещён", not _jok("Portfolio/stress/stress-2026-11-04-x.yaml"))
check("job: матрица сценариев запрещена", not _jok("scenarios/scenario-x.yaml")
      and not _jok("scenarios/scenario-geopolitics-ru-west-2026-07-01.yaml"))
check("job: соседи новых путей запрещены", not _jok("Portfolio/known-splits.json.tmp")
      and not _jok("Portfolio/stress/auto/other.yaml") and not _jok("Portfolio/stress/auto/recalc-x.yaml")
      and not _jok("scenarios/stress-weights-x.yaml") and not _jok("scenarios/sub/stress-weights-x.json"))
check("taste-profile запрещён", not server.is_allowed("Gaming/taste-profile.yaml"))
check("html запрещён", not server.is_allowed("travel-planner/trips/x/3_poi.html"))
check("корень trips запрещён", not server.is_allowed("travel-planner/trips/3_poi.md"))

# health-whitelist — отдельный корень, отдельный список
HW = server.HEALTH_WHITELIST
check("meds.json разрешён", server.is_allowed("meds.json", HW))
check("vaccinations.json разрешён", server.is_allowed("vaccinations.json", HW))
check("vitals.json разрешён", server.is_allowed("vitals.json", HW))
check("labs.json разрешён (главный файл анализов; ручные точки — только при ai_mode off, см. блок «labs»)", server.is_allowed("labs.json", HW))
check("biomarkers-info.json разрешён (справка маркера: страница и скилл пишут через merge)", server.is_allowed("biomarkers-info.json", HW))
check("reports/ГГГГ-ММ-ДД-тема.md разрешён", server.is_allowed("reports/2026-09-29-липиды.md", HW))
check("reports/: не-.md, имя не по образцу и подпапки запрещены",
      not any(server.is_allowed(x, HW) for x in ("reports/a.md", "reports/2026-09-29-x.json", "reports/sub/2026-09-29-x.md", "reports/2026-09-29-A B.md")))
check("meds.json в подпапке запрещён", not server.is_allowed("sub/meds.json", HW))
check("health-путь не проходит по основному whitelist", not server.is_allowed("meds.json"))
check("travel-путь не проходит по health-whitelist",
      not server.is_allowed("travel-planner/trips/x/3_poi.md", HW))

# food-whitelist. «Еда» переехала в НЕСИНХРОНИЗИРУЕМОЕ дерево к здоровью
# (2026-07-20), поэтому у зоны свой корень /srv-food — сам каталог Food, а не
# его родитель. Путь в запросе идёт без префикса, ровно как у здоровья.
# Изоляция от безсхемной зоны /api/* проверяется в обе стороны: иначе страница
# запишет JSON еды мимо валидатора.
FW = server.FOOD_WHITELIST
check("products.json разрешён", server.is_allowed("products.json", FW))
check("рецепт в подкаталоге разрешён", server.is_allowed("recipes/bolognese.json", FW))
# Общий recipes.json больше НЕ пишется: он был бы вторым местом правды рядом
# с каталогом, и они разъехались бы на первой же правке.
check("общий recipes.json запрещён", not server.is_allowed("recipes.json", FW))
check("рецепт с заглавными в имени запрещён (имя = id, id в нижнем регистре)",
      not server.is_allowed("recipes/Bolognese.json", FW))
check("вложенность глубже одного уровня запрещена",
      not server.is_allowed("recipes/2026/x.json", FW))
check("shopping.json разрешён", server.is_allowed("shopping.json", FW))
check("inbox рецепт запрещён (кладёт человек, страница только читает)",
      not server.is_allowed("inbox/pasta.md", FW))
# Старый префикс — теперь путь ВНЕ корня зоны и обязан отлетать. Иначе после
# переезда сайдкар молча писал бы в /srv-food/Food/, создав второй каталог.
check("старый путь с префиксом Food/ запрещён",
      not server.is_allowed("Food/products.json", FW))
check("подпапка запрещена", not server.is_allowed("sub/products.json", FW))
check("food-файл не проходит по основному whitelist",
      not server.is_allowed("products.json"))
check("food-файл не проходит по health-whitelist",
      not server.is_allowed("products.json", HW))
check("travel-путь не проходит по food-whitelist",
      not server.is_allowed("travel-planner/trips/x/3_poi.md", FW))
check("health-путь не проходит по food-whitelist", not server.is_allowed("meds.json", FW))

# ── validate_health ──────────────────────────────────────────────────────────
print("validate_health")
MEDS_OK = json.dumps({"schema": "health-meds@1", "updated": "2026-07-17", "meds": [
    {"id": "m1", "name": "Препарат А", "taking": True, "affects": ["ldl"]}]}, ensure_ascii=False)


def invalid(path, content):
    """True, если валидатор отклонил."""
    try:
        server.validate_health(path, content)
        return False
    except ValueError:
        return True


check("meds валидный проходит", not invalid("meds.json", MEDS_OK))
check("не-JSON отклонён", invalid("meds.json", "{битый"))
check("корень-массив отклонён (формат дизайна)", invalid("meds.json", '[{"id":"m1"}]'))
check("чужая schema отклонена", invalid("meds.json", '{"schema":"health-meds@2","meds":[]}'))
check("нет schema — отклонено", invalid("meds.json", '{"meds":[]}'))
check("meds не список — отклонено", invalid("meds.json", '{"schema":"health-meds@1","meds":{}}'))
check("пустой meds — валиден (каркас)", not invalid("meds.json", '{"schema":"health-meds@1","meds":[]}'))
check("meds без id — отклонено", invalid(
    "meds.json", '{"schema":"health-meds@1","meds":[{"name":"X","taking":true}]}'))
check("meds с повтором id — отклонено", invalid(
    "meds.json", '{"schema":"health-meds@1","meds":['
    '{"id":"m1","name":"A","taking":true},{"id":"m1","name":"B","taking":false}]}'))
check("meds с пустым name — отклонено", invalid(
    "meds.json", '{"schema":"health-meds@1","meds":[{"id":"m1","name":"  ","taking":true}]}'))
check("meds taking не bool — отклонено", invalid(
    "meds.json", '{"schema":"health-meds@1","meds":[{"id":"m1","name":"X","taking":"да"}]}'))
check("meds affects не список строк — отклонено", invalid(
    "meds.json", '{"schema":"health-meds@1","meds":[{"id":"m1","name":"X","taking":true,"affects":[1]}]}'))
check("meds без affects — валиден (поле опционально)", not invalid(
    "meds.json", '{"schema":"health-meds@1","meds":[{"id":"m1","name":"X","taking":true}]}'))

check("прививки валидные", not invalid(
    "vaccinations.json",
    '{"schema":"health-vaccinations@1","vaccinations":[{"id":"v1","date":"2025-04-12"}]}'))
check("прививки с чужой схемой отклонены", invalid(
    "vaccinations.json", '{"schema":"health-meds@1","vaccinations":[]}'))

check("vitals валидные", not invalid(
    "vitals.json", '{"schema":"health-vitals@1","height_cm":180,"weight":[{"date":"2025-10-18","kg":80.0}]}'))
check("vitals height null — валидно", not invalid(
    "vitals.json", '{"schema":"health-vitals@1","height_cm":null,"weight":[]}'))
check("vitals height строкой — отклонено", invalid(
    "vitals.json", '{"schema":"health-vitals@1","height_cm":"180","weight":[]}'))
check("vitals kg строкой — отклонено", invalid(
    "vitals.json", '{"schema":"health-vitals@1","height_cm":180,"weight":[{"date":"2025-10-18","kg":"80"}]}'))
check("vitals weight не список — отклонено", invalid(
    "vitals.json", '{"schema":"health-vitals@1","height_cm":180,"weight":{}}'))

# bp[] (контракт §12) и anamnesis.json (контракт §11)
def _vit(bp):
    return json.dumps({"schema": "health-vitals@1", "height_cm": 180, "weight": [], "bp": bp})
_B = {"id": "bp_20261102_0800", "date": "2026-11-02", "time": "08:00",
      "sys": 120, "dia": 80, "pulse": 64, "note": ""}
check("vitals bp валидный", not invalid("vitals.json", _vit([_B])))
check("vitals bp: time/pulse null — валидно", not invalid(
    "vitals.json", _vit([dict(_B, time=None, pulse=None)])))
check("vitals bp: sys <= dia — отклонено", invalid("vitals.json", _vit([dict(_B, sys=80, dia=80)])))
check("vitals bp: sys вне диапазона — отклонено", invalid("vitals.json", _vit([dict(_B, sys=300)])))
check("vitals bp: pulse вне диапазона — отклонено", invalid("vitals.json", _vit([dict(_B, pulse=10)])))
check("vitals bp: повтор id — отклонено", invalid("vitals.json", _vit([_B, dict(_B)])))
check("vitals bp не список — отклонено", invalid("vitals.json", _vit({})))
check("anamnesis.json разрешён", server.is_allowed("anamnesis.json", HW))

def _an(fam):
    return json.dumps({"schema": "health-anamnesis@1", "updated": "2026-11-02", "family": fam})
_P = {"id": "mother", "relation": "mother", "side": None, "name": "Мама", "born": 1960,
      "died": None, "unknown": False,
      "conditions": [{"name": "Гипертония", "group": "cardio", "kind": "disease",
                      "onset_age": 50, "certainty": "known"}]}
_C = _P["conditions"][0]
check("anamnesis валидный", not invalid("anamnesis.json", _an([_P])))
check("anamnesis пустой family — валидно", not invalid("anamnesis.json", _an([])))
check("anamnesis family не список — отклонено", invalid("anamnesis.json", _an({})))
check("anamnesis повтор id — отклонено", invalid("anamnesis.json", _an([_P, dict(_P)])))
check("anamnesis пустой id — отклонено", invalid("anamnesis.json", _an([dict(_P, id="")])))
check("anamnesis relation вне перечня — отклонено", invalid("anamnesis.json", _an([dict(_P, relation="friend")])))
check("anamnesis side вне перечня — отклонено", invalid("anamnesis.json", _an([dict(_P, side="left")])))
check("anamnesis born строкой — отклонено", invalid("anamnesis.json", _an([dict(_P, born="1960")])))
check("anamnesis unknown не bool — отклонено", invalid("anamnesis.json", _an([dict(_P, unknown="no")])))
check("anamnesis group вне перечня — отклонено", invalid("anamnesis.json", _an([dict(_P, conditions=[dict(_C, group="x")])])))
check("anamnesis kind вне перечня — отклонено", invalid("anamnesis.json", _an([dict(_P, conditions=[dict(_C, kind="x")])])))
check("anamnesis onset_age 200 — отклонено", invalid("anamnesis.json", _an([dict(_P, conditions=[dict(_C, onset_age=200)])])))
check("anamnesis certainty вне перечня — отклонено", invalid("anamnesis.json", _an([dict(_P, conditions=[dict(_C, certainty="sure")])])))
check("anamnesis пустое name записи — отклонено", invalid("anamnesis.json", _an([dict(_P, conditions=[dict(_C, name=" ")])])))

# раздел self (контракт §13): необязателен; файл без self валиден
def _ans(sf):
    d = json.loads(_an([_P])); d["self"] = sf
    return json.dumps(d)
_A = {"id": "alg1", "substance": "Пенициллин", "kind": "drug", "reaction": "сыпь",
      "severity": "moderate", "certainty": "known", "since": 2015, "note": ""}
_H = {"id": "ev1", "name": "Пневмония", "kind": "illness", "group": "other", "start": "2026-10-01",
      "end": "2026-10-05", "status": "resolved", "treatment": "", "certainty": "known", "study": None, "note": ""}
def _sf(**kw):
    return _ans({"allergies_checked": True, "allergies": [_A], "history": [_H], **kw})
check("anamnesis self валидный", not invalid("anamnesis.json", _sf()))
check("anamnesis без self — валиден", not invalid("anamnesis.json", _an([_P])))
check("anamnesis self пустой — валиден", not invalid("anamnesis.json", _ans({})))
check("anamnesis self не объект — отклонено", invalid("anamnesis.json", _ans([])))
check("anamnesis allergies_checked не bool — отклонено", invalid("anamnesis.json", _sf(allergies_checked="yes")))
check("anamnesis аллергия: пустое substance — отклонено", invalid("anamnesis.json", _sf(allergies=[dict(_A, substance=" ")])))
check("anamnesis аллергия: повтор id — отклонено", invalid("anamnesis.json", _sf(allergies=[_A, dict(_A)])))
check("anamnesis аллергия: severity вне перечня — отклонено", invalid("anamnesis.json", _sf(allergies=[dict(_A, severity="x")])))
check("anamnesis аллергия: kind вне перечня — отклонено", invalid("anamnesis.json", _sf(allergies=[dict(_A, kind="x")])))
check("anamnesis аллергия: since строкой — отклонено", invalid("anamnesis.json", _sf(allergies=[dict(_A, since="2015")])))
check("anamnesis аллергия: since null — валидно", not invalid("anamnesis.json", _sf(allergies=[dict(_A, since=None)])))
check("anamnesis событие: повтор id — отклонено", invalid("anamnesis.json", _sf(history=[_H, dict(_H)])))
check("anamnesis событие: пустое name — отклонено", invalid("anamnesis.json", _sf(history=[dict(_H, name="")])))
check("anamnesis событие: kind вне перечня — отклонено", invalid("anamnesis.json", _sf(history=[dict(_H, kind="cold")])))
check("anamnesis событие: status вне перечня — отклонено", invalid("anamnesis.json", _sf(history=[dict(_H, status="x")])))
check("anamnesis событие: start неверного формата — отклонено", invalid("anamnesis.json", _sf(history=[dict(_H, start="10.2026")])))
check("anamnesis событие: start YYYY и YYYY-MM — валидно", not invalid("anamnesis.json", _sf(history=[dict(_H, start="2024", end=None), dict(_H, id="e2", start="2024-03", end="2024-04")])))
check("anamnesis событие: end раньше start — отклонено", invalid("anamnesis.json", _sf(history=[dict(_H, end="2026-09-30")])))
check("anamnesis событие: end раньше start при разной точности — отклонено", invalid("anamnesis.json", _sf(history=[dict(_H, start="2026-10-01", end="2025")])))
check("anamnesis событие: study число — отклонено", invalid("anamnesis.json", _sf(history=[dict(_H, study=5)])))
check("anamnesis событие: окно 0..365 — валидно", not invalid("anamnesis.json", _sf(history=[dict(_H, window_before=0, window_after=365)])))
check("anamnesis событие: окно без полей — валидно", not invalid("anamnesis.json", _sf(history=[dict(_H)])))
check("anamnesis событие: window_before 366 — отклонено", invalid("anamnesis.json", _sf(history=[dict(_H, window_before=366)])))
check("anamnesis событие: window_after -1 — отклонено", invalid("anamnesis.json", _sf(history=[dict(_H, window_after=-1)])))
check("anamnesis событие: окно строкой — отклонено", invalid("anamnesis.json", _sf(history=[dict(_H, window_before="3")])))
check("anamnesis событие: окно дробью/bool/null — отклонено", invalid("anamnesis.json", _sf(history=[dict(_H, window_after=1.5)]))
      and invalid("anamnesis.json", _sf(history=[dict(_H, window_after=True)]))
      and invalid("anamnesis.json", _sf(history=[dict(_H, window_before=None)])))
check("anamnesis событие: markers — валидно", not invalid("anamnesis.json", _sf(history=[dict(_H, kind="chronic", markers=["glucose", "vitals_weight"])])))
check("anamnesis событие: markers — дубль отклонён", invalid("anamnesis.json", _sf(history=[dict(_H, markers=["a", "a"])])))
check("anamnesis событие: markers — не строка/пустая/длинная отклонены", invalid("anamnesis.json", _sf(history=[dict(_H, markers=[5])]))
      and invalid("anamnesis.json", _sf(history=[dict(_H, markers=[""])]))
      and invalid("anamnesis.json", _sf(history=[dict(_H, markers=["x" * 81])])))
check("anamnesis событие: markers — не список / больше 30 отклонены", invalid("anamnesis.json", _sf(history=[dict(_H, markers="glucose")]))
      and invalid("anamnesis.json", _sf(history=[dict(_H, markers=["m%d" % i for i in range(31)])]))
      and not invalid("anamnesis.json", _sf(history=[dict(_H, markers=["m%d" % i for i in range(30)])])))
check("нездоровый путь валидатор пропускает", not invalid(
    "travel-planner/trips/x/3_poi.md", "# любой markdown"))

# ── save_file / read_file ────────────────────────────────────────────────────
print("validate_food")
PRODUCTS_OK = json.dumps({"schema": "food-products@1", "updated": "2026-07-20", "products": [
    {"id": "farsh", "name": "Говяжий фарш", "aliases": ["фарш говяжий"],
     "category": "мясо", "pack_size": 400, "staple": False}]}, ensure_ascii=False)
# Один рецепт = один файл (2026-07-20). Имя файла = id: два файла с одним
# именем невозможны физически, поэтому id уникален по построению.
RECIPE_PATH = "recipes/bolognese.json"


def recipe_doc(**over):
    d = {"schema": "food-recipe@1", "id": "bolognese", "title": "Паста Болоньезе",
         "servings": 6,
         "ingredients": [{"name": "Говяжий фарш", "qty": 600, "unit": "г"},
                         {"name": "Соль", "qty": None, "unit": None}],
         "steps": [{"title": "Шаг 1. Нарезка (5 мин)", "text": "Нарезать."}],
         "nutrition": {"kcal": 690, "protein_g": 42}}
    d.update(over)
    # id=None → файл без поля id (идентичность = имя файла)
    if d.get("id") is None:
        d.pop("id", None)
    return json.dumps(d, ensure_ascii=False)


RECIPES_OK = recipe_doc()
SHOPPING_OK = json.dumps({"schema": "food-shopping@1", "updated": "2026-07-20", "items": [
    {"id": "i1", "product_id": "farsh", "name": "Говяжий фарш", "qty": 1000,
     "unit": "г", "bought": False, "from": [{"recipe_id": "bolognese", "qty": 1000}]}]},
    ensure_ascii=False)


def bad_food(path, content):
    """True, если валидатор отклонил."""
    try:
        server.validate_food(path, content)
        return False
    except ValueError:
        return True


check("products валидный проходит", not bad_food("products.json", PRODUCTS_OK))
check("рецепт-файл валидный проходит", not bad_food(RECIPE_PATH, RECIPES_OK))
check("shopping валидный проходит", not bad_food("shopping.json", SHOPPING_OK))
check("не-JSON отклонён", bad_food("products.json", "{битый"))
check("корень-массив отклонён", bad_food("products.json", '[{"id":"p1"}]'))
check("чужая schema отклонена",
      bad_food("products.json", '{"schema":"food-products@2","products":[]}'))
check("products не список — отклонено",
      bad_food("products.json", '{"schema":"food-products@1","products":"нет"}'))
check("повтор id отклонён", bad_food("products.json", json.dumps(
    {"schema": "food-products@1", "products": [{"id": "a", "name": "A"}, {"id": "a", "name": "B"}]})))
check("пустой name продукта отклонён", bad_food("products.json", json.dumps(
    {"schema": "food-products@1", "products": [{"id": "a", "name": "  "}]})))
check("aliases не список строк — отклонено", bad_food("products.json", json.dumps(
    {"schema": "food-products@1", "products": [{"id": "a", "name": "A", "aliases": [1]}]})))
# Страница делит на pack_size → строка даёт «NaN уп.» на экране в магазине.
check("pack_size строкой отклонён", bad_food("products.json", json.dumps(
    {"schema": "food-products@1", "products": [{"id": "a", "name": "A", "pack_size": "400"}]})))
check("pack_size null допустим (товар на вес)", not bad_food("products.json", json.dumps(
    {"schema": "food-products@1", "products": [{"id": "a", "name": "A", "pack_size": None}]})))

# servings — делитель пересчёта порций. Ноль или строка тихо разносит NaN по
# каждой строке списка покупок, произошедшей от рецепта.
check("servings=0 отклонён", bad_food(RECIPE_PATH, json.dumps(
    {"schema": "food-recipes@1", "recipes": [
        {"id": "r", "title": "R", "servings": 0, "ingredients": [], "steps": []}]})))
check("servings отрицательный отклонён", bad_food(RECIPE_PATH, json.dumps(
    {"schema": "food-recipes@1", "recipes": [
        {"id": "r", "title": "R", "servings": -2, "ingredients": [], "steps": []}]})))
check("servings строкой отклонён", bad_food(RECIPE_PATH, json.dumps(
    {"schema": "food-recipes@1", "recipes": [
        {"id": "r", "title": "R", "servings": "6", "ingredients": [], "steps": []}]})))
check("servings отсутствует — отклонено", bad_food(RECIPE_PATH, json.dumps(
    {"schema": "food-recipes@1", "recipes": [
        {"id": "r", "title": "R", "ingredients": [], "steps": []}]})))
# "600"+"400" = "600400" при суммировании — тихо и катастрофично.
check("qty строкой отклонён", bad_food(RECIPE_PATH, recipe_doc(servings=6, steps=[], ingredients=[{"name": "Фарш", "qty": "600"}])))
check("qty null допустим («по вкусу»)", not bad_food(RECIPE_PATH, recipe_doc(ingredients=[{"name": "Соль", "qty": None}], steps=[])))
check("пустое имя ингредиента отклонено", bad_food(RECIPE_PATH, recipe_doc(servings=6, steps=[], ingredients=[{"name": "", "qty": 100}])))
check("nutrition строкой отклонён", bad_food(RECIPE_PATH, json.dumps(
    {"schema": "food-recipes@1", "recipes": [{"id": "r", "title": "R", "servings": 6,
     "ingredients": [], "steps": [], "nutrition": {"kcal": "690"}}]})))
check("nutrition null допустим (источник ещё не отдаёт КБЖУ)",
      not bad_food(RECIPE_PATH, recipe_doc(ingredients=[], steps=[], nutrition=None)))
# True — подкласс int в Python; без явной проверки bool прошёл бы как число.
check("qty=true отклонён (bool не число)", bad_food(RECIPE_PATH, recipe_doc(servings=6, steps=[], ingredients=[{"name": "Фарш", "qty": True}])))
# measure — свободный текст для показа человеку («1 стакан»); в КБЖУ и список
# идёт qty (STD в г/мл/шт). Строкой — норма, числом — отклоняем (это показ).
check("measure строкой принят", not bad_food(RECIPE_PATH, recipe_doc(
    servings=6, steps=[], ingredients=[{"name": "Рис", "qty": 180, "unit": "г", "measure": "1 стакан"}])))
check("measure числом отклонён (показ, не расчёт)", bad_food(RECIPE_PATH, recipe_doc(
    servings=6, steps=[], ingredients=[{"name": "Рис", "qty": 180, "measure": 1}])))
check("bought строкой отклонён", bad_food("shopping.json", json.dumps(
    {"schema": "food-shopping@1", "items": [{"id": "i", "bought": "да"}]})))
check("from не список объектов — отклонено", bad_food("shopping.json", json.dumps(
    {"schema": "food-shopping@1", "items": [{"id": "i", "from": ["bolognese"]}]})))

# ВАЖНО: валидатор не имеет мнения о содержании. Эти проверки стоят здесь,
# чтобы никто потом «услужливо» не добавил enum и не начал ронять сохранение
# на новом магазине или на слове «грибы» в заметке о заменах.
# Разваривание: варёный вес рецепта делится на cooked_ratio продукта.
check("cooked_ratio числом принят", not bad_food("products.json", json.dumps(
    {"schema": "food-products@1", "products": [
        {"id": "a", "name": "Гречка", "cooked_ratio": 2.5}]})))
check("cooked_ratio строкой отклонён", bad_food("products.json", json.dumps(
    {"schema": "food-products@1", "products": [
        {"id": "a", "name": "Гречка", "cooked_ratio": "2.5"}]})))
check("cooked_ratio=0 отклонён (деление на ноль)", bad_food("products.json", json.dumps(
    {"schema": "food-products@1", "products": [
        {"id": "a", "name": "Гречка", "cooked_ratio": 0}]})))
# piece_g — вес одной штуки, связывает «3 шт» с граммами. Строка или ноль дали
# бы NaN в пересчёте штук прямо в списке покупок.
check("piece_g числом принят", not bad_food("products.json", json.dumps(
    {"schema": "food-products@1", "products": [
        {"id": "a", "name": "Яйца", "unit": "шт", "piece_g": 55}]})))
check("piece_g строкой отклонён", bad_food("products.json", json.dumps(
    {"schema": "food-products@1", "products": [
        {"id": "a", "name": "Яйца", "piece_g": "55"}]})))
check("piece_g=0 отклонён", bad_food("products.json", json.dumps(
    {"schema": "food-products@1", "products": [
        {"id": "a", "name": "Яйца", "piece_g": 0}]})))
# g_per_100ml — плотность жидкого продукта. Страница ДЕЛИТ на неё (qty*d/100),
# строка/ноль дали бы NaN/ноль прямо в КБЖУ. Это не глобальная таблица — цифра
# у конкретного продукта; нет её → мл≈г.
check("g_per_100ml числом принят", not bad_food("products.json", json.dumps(
    {"schema": "food-products@1", "products": [
        {"id": "a", "name": "Молоко", "unit": "л", "g_per_100ml": 103}]})))
check("g_per_100ml строкой отклонён", bad_food("products.json", json.dumps(
    {"schema": "food-products@1", "products": [
        {"id": "a", "name": "Молоко", "g_per_100ml": "103"}]})))
check("g_per_100ml=0 отклонён (деление на ноль)", bad_food("products.json", json.dumps(
    {"schema": "food-products@1", "products": [
        {"id": "a", "name": "Молоко", "g_per_100ml": 0}]})))
check("g_per_100ml null допустим (мл≈г откат)", not bad_food("products.json", json.dumps(
    {"schema": "food-products@1", "products": [
        {"id": "a", "name": "Вода", "g_per_100ml": None}]})))
# Пищевая ценность сырого продукта на 100 г — только КБЖУ (минералы вне scope,
# и вместе с ними отпадают коэффициенты удержания USDA).
check("nutrition_100g принят", not bad_food("products.json", json.dumps(
    {"schema": "food-products@1", "products": [
        {"id": "a", "name": "Творог 5%", "nutrition_100g": {
            "kcal": 121, "protein_g": 17.2, "fat_g": 5, "carb_g": 1.8,
            "source": "этикетка Вкусвилл"}}]})))
check("nutrition_100g строкой отклонён", bad_food("products.json", json.dumps(
    {"schema": "food-products@1", "products": [
        {"id": "a", "name": "Творог", "nutrition_100g": {"kcal": "121"}}]})))
check("nutrition_100g null допустим (продукт ещё не заполнен)",
      not bad_food("products.json", json.dumps(
          {"schema": "food-products@1", "products": [
              {"id": "a", "name": "Творог", "nutrition_100g": None}]})))
check("source в nutrition_100g — строка, а не число", bad_food("products.json", json.dumps(
    {"schema": "food-products@1", "products": [
        {"id": "a", "name": "Творог", "nutrition_100g": {"kcal": 121, "source": 5}}]})))

check("state=cooked принят", not bad_food(RECIPE_PATH, recipe_doc(servings=2, steps=[],
               ingredients=[{"name": "Гречка", "qty": 390, "unit": "г", "state": "cooked"}])))
# Опечатка тут ТИХО отключила бы пересчёт: в список уехало бы 390 г вместо 156 г.
check("state с опечаткой отклонён", bad_food(RECIPE_PATH, recipe_doc(servings=2, steps=[], ingredients=[{"name": "Гречка", "qty": 390, "state": "cookd"}])))

check("незнакомая category принята", not bad_food("products.json", json.dumps(
    {"schema": "food-products@1", "products": [
        {"id": "a", "name": "A", "category": "чай и кофе"}]})))
check("незнакомый store принят", not bad_food("products.json", json.dumps(
    {"schema": "food-products@1", "products": [
        {"id": "a", "name": "A", "store": "Магнит"}]})))
check("стоп-лист НЕ кодируется в сайдкаре (грибы в рецепте проходят)",
      not bad_food(RECIPE_PATH, recipe_doc(title="Суп", servings=4, steps=[],
               ingredients=[{"name": "Грибы", "qty": 200, "unit": "г"}])))
# Идентичность рецепта — ИМЯ ФАЙЛА, оно же путь записи: файл с чужим id внутри
# пишется в СВОЙ путь и оригинал не перетирает. Поэтому расхождение id с именем
# НЕ отклоняем (2026-07-23) — страница откроет по имени и покажет предупреждение
# (док food/instruction.md). По новому формату id в файле нет вовсе.
check("файл БЕЗ поля id принимается (имя файла — идентичность)",
      not bad_food("recipes/bolognese.json", recipe_doc(id=None)))
check("id, не совпадающий с именем файла, ТЕПЕРЬ принимается (страница предупредит)",
      not bad_food("recipes/bolognese.json", recipe_doc(id="other")))
check("совпадающий id проходит (обратная совместимость)",
      not bad_food("recipes/bolognese.json", recipe_doc(id="bolognese")))
# schema — единственный признак, по которому файл опознаётся как рецепт.
check("чужая schema отклонена", bad_food(RECIPE_PATH, recipe_doc(schema="food-recipes@1")))
check("рецепт списком, а не объектом, отклонён", bad_food(RECIPE_PATH, "[]"))
check("пустой title отклонён", bad_food(RECIPE_PATH, recipe_doc(title="  ")))
# Масса готового блюда — делитель для «на 100 г».
check("finished_g строкой отклонён", bad_food(RECIPE_PATH, recipe_doc(finished_g="700")))
check("finished_g числом принят", not bad_food(RECIPE_PATH, recipe_doc(finished_g=700)))

check("чужой файл в зоне не валидируется", not bad_food("Food/inbox/pasta.md", "какой угодно текст"))

print("save_file")
tmp = tempfile.mkdtemp(prefix="hub-api-test-")
try:
    root = Path(tmp)
    rel = "travel-planner/trips/тест_2026/3_poi_v1.md"
    full = root / rel
    full.parent.mkdir(parents=True)
    full.write_text("# POI v1\n", encoding="utf-8")

    content, h1 = server.read_file(tmp, rel)
    check("read_file контент", content == "# POI v1\n")
    check("read_file hash = sha256", h1 == server.file_hash(b"# POI v1\n"))

    h2 = server.save_file(tmp, rel, "# POI v2\n", h1)
    check("save: файл перезаписан", full.read_text(encoding="utf-8") == "# POI v2\n")
    check("save: новый hash", h2 == server.file_hash("# POI v2\n".encode()))
    versions = list((root / ".versions").rglob("*_3_poi_v1.md"))
    check("save: бэкап в .versions/", len(versions) == 1)
    check("save: бэкап = старый контент", versions[0].read_text(encoding="utf-8") == "# POI v1\n")
    check("save: бэкап зеркалит путь", "travel-planner/trips/тест_2026" in str(versions[0].parent))
    check("save: tmp-файла не осталось", not list(full.parent.glob("*.hub-api-tmp")))

    try:
        server.save_file(tmp, rel, "# POI v3\n", h1)  # устаревший base_hash
        check("конфликт: исключение", False)
    except server.Conflict as c:
        check("конфликт: current_hash актуален", c.current_hash == h2)
    check("конфликт: файл не тронут", full.read_text(encoding="utf-8") == "# POI v2\n")

    try:
        server.save_file(tmp, "travel-planner/trips/тест_2026/3_нет.md", "x", h1)
        check("несуществующий файл: исключение", False)
    except FileNotFoundError:
        check("несуществующий файл → FileNotFoundError", True)

    try:
        server.save_file(tmp, rel, "x" * (server.MAX_BYTES + 1), h2)
        check("превышение размера: исключение", False)
    except ValueError:
        check("превышение размера → ValueError", True)
finally:
    shutil.rmtree(tmp)

# ── e2e через живой сервер ───────────────────────────────────────────────────
print("e2e")
tmp = tempfile.mkdtemp(prefix="hub-api-e2e-")
server.ROOT = tmp
httpd, _ = serve(server.Handler, quiet=False)
port = httpd.server_address[1]
BASE = f"http://127.0.0.1:{port}"


def api(method, path, body=None):
    """→ (status, json)"""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


try:
    root = Path(tmp)
    rel = "travel-planner/trips/x/3_big-story.md"
    full = root / rel
    full.parent.mkdir(parents=True)
    full.write_text("итог: —\n", encoding="utf-8")

    st, body = api("GET", "/api/health")
    check("health 200", st == 200)
    check("health ok+writable", body.get("ok") is True and body.get("writable") is True)
    # hub-notify в тесте нет: ключ есть, значение null — deploy.zsh скажет «не отвечает», а не «старый код»
    check("health: notify — версия hub-notify для deploy.zsh (нет контейнера → null)",
          "notify" in body and body["notify"] is None)
    import hashlib as _hl
    _want = _hl.sha256((REPO / "tools/hosting/api/server.py").read_bytes()).hexdigest()[:16]
    check("health: api.code — отпечаток server.py работающего процесса (sha256[:16] файла), сверяется deploy.zsh",
          (body.get("api") or {}).get("code") == _want)

    st, body = api("GET", "/api/file?path=" + urllib.request.quote(rel))
    check("file 200", st == 200)
    check("file контент", body.get("content") == "итог: —\n")
    h = body.get("hash")

    st, body = api("POST", "/api/save", {"path": rel, "content": "итог: восторг\n", "base_hash": h})
    check("save 200", st == 200)
    check("save применён", full.read_text(encoding="utf-8") == "итог: восторг\n")

    st, body = api("POST", "/api/save", {"path": rel, "content": "итог: брошено\n", "base_hash": h})
    check("save устаревший hash → 409", st == 409)
    check("409 несёт current_hash", body.get("current_hash") == server.file_hash("итог: восторг\n".encode()))

    st, body = api("GET", "/api/file?path=Portfolio/snapshots/x.json")
    check("не-whitelist file → 403", st == 403)
    st, body = api("POST", "/api/save", {"path": "Portfolio/x.json", "content": "", "base_hash": "0"})
    check("не-whitelist save → 403", st == 403)

    st, body = api("GET", "/api/file?path=" + urllib.request.quote("../etc/passwd"))
    check("traversal → 400", st == 400)

    st, body = api("GET", "/api/file?path=" + urllib.request.quote("travel-planner/trips/x/3_нет.md"))
    check("нет файла → 404", st == 404)
    st, body = api("GET", "/api/file?path=" + urllib.request.quote("Gaming/recommendations/x.md"))
    check("Gaming/recommendations → 403 (пути нет в whitelist)", st == 403)

    st, body = api("POST", "/api/save", {"path": rel})  # нет content/base_hash
    check("битое тело → 400", st == 400)

    st, body = api("GET", "/api/unknown")
    check("неизвестный endpoint → 404", st == 404)

    # ── health-зона: второй корень, /api/hd/* ────────────────────────────────
    hroot = tempfile.mkdtemp(prefix="hub-api-health-")
    server.HEALTH_ROOT = hroot
    try:
        hpath = Path(hroot) / "meds.json"
        hpath.write_text(MEDS_OK, encoding="utf-8")

        st, body = api("GET", "/api/hd/file?path=meds.json")
        check("hd file 200", st == 200)
        check("hd file контент", json.loads(body["content"])["meds"][0]["name"] == "Препарат А")
        hh = body["hash"]

        good = json.dumps({"schema": "health-meds@1", "updated": "2026-07-17", "meds": [
            {"id": "m1", "name": "Препарат А", "taking": False, "affects": ["ldl"]}]},
            ensure_ascii=False)
        st, body = api("POST", "/api/hd/save", {"path": "meds.json", "content": good, "base_hash": hh})
        check("hd save 200", st == 200)
        check("hd save применён (галочка снята)",
              json.loads(hpath.read_text(encoding="utf-8"))["meds"][0]["taking"] is False)
        hh2 = body["hash"]

        # битая схема не должна испортить существующий файл
        st, body = api("POST", "/api/hd/save",
                       {"path": "meds.json", "content": '{"schema":"health-meds@1","meds":"не список"}',
                        "base_hash": hh2})
        check("hd битая схема → 400", st == 400)
        check("hd 400 объясняет причину", "meds" in (body.get("detail") or ""))
        check("hd битая схема: файл НЕ тронут",
              json.loads(hpath.read_text(encoding="utf-8"))["meds"][0]["id"] == "m1")

        st, body = api("POST", "/api/hd/save",
                       {"path": "meds.json", "content": "{сломанный json", "base_hash": hh2})
        check("hd не-JSON → 400", st == 400)

        st, body = api("POST", "/api/hd/save", {"path": "meds.json", "content": good, "base_hash": hh})
        check("hd устаревший hash → 409 (гонка со скиллом)", st == 409)

        # изоляция корней в обе стороны — главное свойство разделения томов
        st, body = api("GET", "/api/hd/file?path=labs.json")
        check("hd: labs.json в whitelist, но файла нет → 404 (не 403)", st == 404)
        st, body = api("GET", "/api/hd/file?path=intake-log.json")
        check("hd: intake-log.json вне whitelist → 403", st == 403)
        st, body = api("GET", "/api/hd/file?path=" + urllib.request.quote(
            "travel-planner/trips/x/3_big-story.md"))
        check("hd: путь Claude-Memory → 403", st == 403)
        st, body = api("GET", "/api/file?path=meds.json")
        check("основная зона: health-путь → 403", st == 403)
        st, body = api("GET", "/api/hd/file?path=" + urllib.request.quote("../etc/passwd"))
        check("hd traversal → 400", st == 400)

        st, body = api("GET", "/api/health")
        check("healthcheck сообщает про оба корня", body.get("health_writable") is True)

        # ── запись со страницы (этап «без ИИ», здоровье 3.1): отчёт .md и справка маркера ───────────
        # модули health-labs сервер берёт из репозитория (в контейнере — смонтированы рядом с server.py)
        st, body = api("GET", "/api/health")
        check("health: признаки записи со страницы — health_report / health_marker_info / health_upload",
              body.get("health_report") is True and body.get("health_marker_info") is True and body.get("health_upload") is True)
        (Path(hroot) / "labs.json").write_text(json.dumps({"biomarkers": [{"id": "ldl", "category": "lipids"}, {"id": "hgb", "category": "blood"}]}),
                                               encoding="utf-8")
        REP = ("---\nschema: health-report@1\ntitle: Синтетический отчёт\ndate: 2026-09-29\nsummary: Острых отклонений нет.\n"
               "flags:\n  - ok | Липиды | всё в норме\nmarkers: ldl\n---\n\n# Синтетический отчёт\n\nТекст.\n")
        rp = Path(hroot) / "reports" / "2026-09-29-липиды.md"
        st, body = api("POST", "/api/hd/report", {"topic": "Липиды", "content": REP})
        check("report: новый отчёт — 200 created, имя из даты шапки и темы", st == 200 and body.get("status") == "created"
              and body.get("name") == "2026-09-29-липиды.md")
        check("report: файл лёг в reports/ байт в байт", rp.read_text(encoding="utf-8") == REP)
        st, body = api("POST", "/api/hd/report", {"topic": "Липиды", "content": REP})
        check("report: тот же текст повторно — 200 same, ничего не меняется", st == 200 and body.get("status") == "same")
        REP2 = REP.replace("Текст.", "Другой текст.")
        st, body = api("POST", "/api/hd/report", {"topic": "Липиды", "content": REP2})
        check("report: то же имя, другой текст — 409 exists без перезаписи", st == 409 and body.get("error") == "exists")
        check("report: 409 не тронул файл", rp.read_text(encoding="utf-8") == REP)
        st, body = api("POST", "/api/hd/report", {"name": "2026-09-29-липиды.md", "content": REP2, "overwrite": True})
        check("report: overwrite: true — 200 replaced", st == 200 and body.get("status") == "replaced"
              and rp.read_text(encoding="utf-8") == REP2)
        check("report: прежняя версия — копией в .versions/reports/",
              any(p.read_text(encoding="utf-8") == REP for p in (Path(hroot) / ".versions" / "reports").glob("*")))
        st, body = api("POST", "/api/hd/report", {"topic": "x", "content": REP.replace("title: Синтетический отчёт\n", "")})
        check("report: ошибка формата (нет title) — 400 со списком errors", st == 400 and body.get("errors") and "title" in " ".join(body["errors"]))
        st, body = api("POST", "/api/hd/report", {"topic": "x", "content": REP.replace("markers: ldl", "markers: nope")})
        check("report: маркер не из labs.json — 400 (сверка с labs.json раздела)", st == 400 and "nope" in (body.get("detail") or ""))
        st, body = api("POST", "/api/hd/report", {"topic": "x", "content": REP.replace("date: 2026-09-29\n", "")})
        check("report: нет даты в шапке — 400 с ошибками формата, а не «плохое имя»", st == 400 and body.get("error") == "report invalid")
        st, body = api("POST", "/api/hd/report", {"name": "../evil.md", "content": REP})
        check("report: имя не по образцу — 400 bad name", st == 400 and body.get("error") == "bad name")
        st, body = api("POST", "/api/hd/report", {"name": "2026-09-29-липиды.md"})
        check("report: нет content — 400", st == 400)
        check("report: за пределы reports/ ничего не легло",
              sorted(p.name for p in Path(hroot).glob("*.md")) == [] and not (Path(hroot).parent / "evil.md").exists())
        st, body = api("GET", "/api/hd/file?path=" + urllib.request.quote("reports/2026-09-29-липиды.md"))
        check("hd file: reports/*.md читается через whitelist", st == 200 and body["content"] == REP2)
        st, body = api("POST", "/api/hd/save", {"path": "reports/2026-09-30-тест.md", "content": "не отчёт", "base_hash": None})
        check("hd save: reports/*.md — форма проверяется и на общей ручке (400)", st == 400)
        st, body = api("GET", "/api/hd/file?path=" + urllib.request.quote("reports/подпапка/a.md"))
        check("hd file: вложенная папка в reports/ вне whitelist → 403", st == 403)

        # справка маркера: слияние validate_labs_info.merge_info(manual=True)
        ip = Path(hroot) / "biomarkers-info.json"
        st, body = api("POST", "/api/hd/marker-info", {"id": "ldl", "what": ["Синт. абзац"], "up": "вверх", "down": "вниз", "base_hash": None})
        check("marker-info: файла нет, base_hash null — 200, файл создан", st == 200 and ip.exists())
        doc = json.loads(ip.read_text(encoding="utf-8"))
        check("marker-info: запись помечена manual, схема справки", doc["schema"] == "health-biomarkers-info@1"
              and doc["info"]["ldl"] == {"what": ["Синт. абзац"], "up": "вверх", "down": "вниз", "manual": True})
        h1 = body["hash"]
        st, body = api("POST", "/api/hd/marker-info", {"id": "hgb", "what": ["Другой"], "up": "u", "down": "d", "base_hash": h1})
        check("marker-info: второй маркер — 200, первый на месте", st == 200 and set(json.loads(ip.read_text(encoding="utf-8"))["info"]) == {"ldl", "hgb"})
        st, body = api("POST", "/api/hd/marker-info", {"id": "ldl", "what": ["Новый"], "up": "u", "down": "d", "base_hash": h1})
        check("marker-info: устаревший base_hash — 409 с текущим хэшем", st == 409 and body.get("current_hash"))
        st, body = api("POST", "/api/hd/marker-info", {"id": "ghost", "what": ["x"], "up": "u", "down": "d", "base_hash": body["current_hash"]})
        check("marker-info: id нет в labs.json — 400", st == 400)
        cur = server.file_hash(ip.read_bytes())
        st, body = api("POST", "/api/hd/marker-info", {"id": "ldl", "what": [], "up": "u", "down": "d", "base_hash": cur})
        check("marker-info: пустое what — 400, файл не тронут", st == 400 and server.file_hash(ip.read_bytes()) == cur)
        st, body = api("POST", "/api/hd/marker-info", {"id": "ldl", "what": ["x"], "up": "u", "down": "d"})
        check("marker-info: без base_hash — 400", st == 400)
        st, body = api("GET", "/api/hd/file?path=biomarkers-info.json")
        check("hd file: biomarkers-info.json читается (хэш для правки)", st == 200 and body.get("hash") == cur)
        st, body = api("POST", "/api/hd/save", {"path": "biomarkers-info.json", "content": '{"schema":"health-biomarkers-info@1","info":{"x":{"what":[]}}}', "base_hash": cur})
        check("hd save: biomarkers-info.json — битая запись справки отклоняется (400)", st == 400)
        # скилл справку человека не затирает, наоборот — ручная правка заменяет запись скилла
        vl = server._health_skill_mods()[1]
        d_skill, rep_skill = vl.merge_info(json.loads(ip.read_text(encoding="utf-8")),
                                           {"ldl": {"what": ["скилл"], "up": "u", "down": "d"}}, today="2026-11-10", overwrite=True)
        check("скилл с overwrite не затирает ручную справку (skip_manual)", rep_skill[0]["action"] == "skip_manual")

        # ── загрузка файла исследования (этап «без ИИ», здоровье 3.3): POST /api/hd/upload → studies/ ──────────
        import base64 as _b64
        PDF = "%PDF-1.4\n% синтетика\n%%EOF\n".encode()
        JPG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00synthetic"
        PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
        HEIC = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic"
        up = lambda raw, **kw: api("POST", "/api/hd/upload", {"kind": kw.get("kind", "МРТ"), "date": kw.get("date", "2026-05-12"),
                                                              "b64": _b64.b64encode(raw).decode()})
        sdir = Path(hroot) / "studies"
        st, body = up(PDF)
        check("upload: PDF — 200 created, имя ГГГГ-ММ-ДД-вид.ext (вид строчными)", st == 200 and body.get("name") == "2026-05-12-мрт.pdf"
              and body.get("status") == "created" and body.get("type") == "pdf")
        check("upload: файл лёг в Health/studies/ байт в байт", (sdir / "2026-05-12-мрт.pdf").read_bytes() == PDF)
        st, body = up(PDF)
        check("upload: тот же файл повторно — 200 same, второй копии нет", st == 200 and body.get("status") == "same"
              and sorted(p.name for p in sdir.glob("*")) == ["2026-05-12-мрт.pdf"])
        st, body = up(PDF + "второе прочтение".encode())
        check("upload: другой файл с тем же именем не перезаписывает — суффикс -2",
              st == 200 and body.get("name") == "2026-05-12-мрт-2.pdf" and (sdir / "2026-05-12-мрт.pdf").read_bytes() == PDF)
        for raw, ext in ((JPG, "jpg"), (PNG, "png"), (HEIC, "heic")):
            st, body = up(raw, kind="УЗИ брюшной полости", date="2026-05-13")
            check(f"upload: {ext} распознан по первым байтам", st == 200 and body.get("type") == ext
                  and body.get("name").startswith("2026-05-13-узи-брюшной-полости") and body["name"].endswith("." + ext))
        st, body = up(b"MZ\x90\x00 exe, not a document")
        check("upload: чужой формат (исполняемый) — 400, ничего не записано", st == 400 and "формат" in (body.get("detail") or ""))
        st, body = up("x-1.4 заголовок не PDF".encode(), kind="МРТ", date="2026-05-14")
        check("upload: расширение и заголовок из запроса не учитываются — только байты", st == 400)
        st, body = up(b"")
        check("upload: пустой файл — 400", st == 400)
        st, body = up(PDF, date="12.05.2026")
        check("upload: дата не ГГГГ-ММ-ДД — 400", st == 400)
        st, body = api("POST", "/api/hd/upload", {"kind": "МРТ", "date": "2026-05-12", "b64": "не base64!"})
        check("upload: битый base64 — 400", st == 400 and body.get("error") == "bad file")
        st, body = up(PDF, kind="../../etc/passwd")
        check("upload: вид с обходом пути — только слаг, файл в studies/", st == 200 and "/" not in body["name"]
              and (sdir / body["name"]).exists() and not (Path(hroot).parent / "etc").exists())
        st, body = up(PDF, kind="!!!")
        check("upload: вид без букв — «файл»", st == 200 and body["name"].startswith("2026-05-12-файл"))
        big = b"%PDF-" + b"\x00" * server.HD_UPLOAD_MAX_BYTES
        st, body = up(big)
        check(f"upload: файл больше 20 МБ — 413 ({st})", st == 413)
        check("upload: после отказов в studies/ только принятые файлы",
              all(not p.name.endswith(".exe") for p in sdir.glob("*")) and len(list(sdir.glob("*"))) == 7)
        import http.client as _hcu
        _cu = _hcu.HTTPConnection("127.0.0.1", port)
        _cu.putrequest("POST", "/api/hd/upload")            # заявленная длина без тела: ответ до чтения
        _cu.putheader("Content-Length", str(server.HD_UPLOAD_BODY_MAX + 10))
        _cu.endheaders()
        check("upload: тело больше HD_UPLOAD_BODY_MAX — 413", _cu.getresponse().status == 413)
        _cu.close()
        check("upload: общий MAX_BYTES не поднят (8 МБ), отдельный лимит тела ≥ 20 МБ в base64",
              server.MAX_BYTES == 8 * 1024 * 1024 and server.HD_UPLOAD_BODY_MAX >= server.HD_UPLOAD_MAX_BYTES * 4 // 3 + 4096)
        st, body = api("GET", "/api/hd/upload")
        check("upload: GET не поддерживается (404)", st == 404)
    finally:
        shutil.rmtree(hroot)

    # ── оверлей игр (gaming-user@1): зона /api/gm/*, корень основной ──────────
    GM = "Gaming/user-state.json"
    groot = Path(server.ROOT)
    gpath = groot / GM
    gpath.unlink(missing_ok=True)

    def gdoc(items=None, **kw):
        d = {"schema": "gaming-user@1", "updated": "2026-11-09", "items": items if items is not None else []}
        d.update(kw)
        return json.dumps(d, ensure_ascii=False)

    def git(**kw):
        it = {"title": "Hades", "state": "хочу"}
        it.update(kw)
        return gdoc([it])

    def gsave(content, bh=None):
        return api("POST", "/api/gm/save", {"path": GM, "content": content, "base_hash": bh})

    def gbad(name, content, frag=None):
        st, body = gsave(content, None)
        check(f"gm: {name} → 400", st == 400)
        if frag:
            check(f"gm: {name}: текст ошибки", frag in (body.get("detail") or ""))

    st, body = api("GET", "/api/gm/file?path=" + GM)
    check("gm: GET без файла → 404", st == 404)

    G1 = gdoc([
        {"title": "Hollow Knight", "platform": "switch2", "state": "на-карандаш", "rating": None,
         "note": "ждать скидку", "price_target_usd": 7.5, "discount_target_pct": 50, "nsuid_us": "70010000003208",
         "eshop_url": "https://www.nintendo.com/us/store/products/hollow-knight/"},
        {"title": "Baldur's Gate 3", "platform": "steam_deck", "state": "играю", "rating": "восторг",
         "cover_url": "https://example.com/bg3.jpg"}])
    st, body = gsave(G1, None)
    check("gm: создание (base_hash null) → 200", st == 200)
    check("gm: файл появился в Gaming/user-state.json", gpath.is_file())
    st, body = api("GET", "/api/gm/file?path=" + GM)
    check("gm: GET → 200 с hash", st == 200 and bool(body.get("hash")))
    check("gm: GET содержимое", json.loads(body["content"])["items"][0]["title"] == "Hollow Knight")
    gh1 = body["hash"]

    G2 = json.loads(G1)
    G2["items"][0]["state"] = "куплена"
    st, body = gsave(json.dumps(G2, ensure_ascii=False), gh1)
    check("gm: сохранение с актуальным hash → 200", st == 200)
    check("gm: состояние применено", json.loads(gpath.read_text(encoding="utf-8"))["items"][0]["state"] == "куплена")
    st, body = api("GET", "/api/gm/file?path=" + GM)
    G3 = json.loads(G1)
    G3["items"][0]["state"] = "демо"
    st, body = gsave(json.dumps(G3, ensure_ascii=False), body["hash"])
    check("gm: старое состояние «демо» принимается → 200", st == 200)
    _it0 = json.loads(gpath.read_text(encoding="utf-8"))["items"][0]
    check("gm: старое «демо» приведено при сохранении: demo true + на-карандаш", _it0["state"] == "на-карандаш" and _it0["demo"] is True)
    st, body = api("GET", "/api/gm/file?path=" + GM)
    G3["items"][0].update(state="демо", rating="не понравилось")
    st, body = gsave(json.dumps(G3, ensure_ascii=False), body["hash"])
    _it0 = json.loads(gpath.read_text(encoding="utf-8"))["items"][0]
    check("gm: старое «демо» + «не понравилось» → не-интересно + demo true", st == 200 and _it0["state"] == "не-интересно" and _it0["demo"] is True)
    st, body = api("GET", "/api/gm/file?path=" + GM)
    G3["items"][0].update(state="куплена", demo=True, rating=None)
    st, body = gsave(json.dumps(G3, ensure_ascii=False), body["hash"])
    _it0 = json.loads(gpath.read_text(encoding="utf-8"))["items"][0]
    check("gm: demo у «куплена» снимается сервером при сохранении", st == 200 and _it0["state"] == "куплена" and "demo" not in _it0)
    st, body = api("GET", "/api/gm/file?path=" + GM)
    G3["items"][0].update(state="на-карандаш", demo=True, progress="играю", hours=2)
    st, body = gsave(json.dumps(G3, ensure_ascii=False), body["hash"])
    _it0 = json.loads(gpath.read_text(encoding="utf-8"))["items"][0]
    check("gm: игра с demo true хранит прохождение и часы", st == 200 and _it0["demo"] is True and _it0["progress"] == "играю" and _it0["hours"] == 2)
    st, body = api("GET", "/api/gm/file?path=" + GM)
    check("gm: копия в .versions/Gaming/", len(list((groot / ".versions" / "Gaming").glob("*user-state*"))) >= 1)
    st, body = gsave(json.dumps(G2, ensure_ascii=False), gh1)
    check("gm: устаревший hash → 409", st == 409)

    gbad("не JSON", "{сломан", "JSON")
    gbad("другая schema", gdoc(schema="gaming-user@2"), "schema")
    gbad("updated не дата", gdoc(updated="вчера"), "updated")
    gbad("items не список", json.dumps({"schema": "gaming-user@1", "updated": "2026-11-09", "items": {}}), "items")
    gbad("state вне enum", git(state="неизвестно"), "state")
    gbad("platform вне enum", git(platform="ps5"), "platform")
    gbad("rating вне enum", git(rating="супер"), "rating")
    gbad("note > 500", git(note="я" * 501), "note")
    gbad("price_target_usd = 0", git(price_target_usd=0), "price_target_usd")
    gbad("price_target_usd < 0", git(price_target_usd=-5), "price_target_usd")
    gbad("price_target_usd строкой", git(price_target_usd="10"), "price_target_usd")
    gbad("discount_target_pct = 0", git(discount_target_pct=0), "discount_target_pct")
    gbad("discount_target_pct = 100", git(discount_target_pct=100), "discount_target_pct")
    gbad("discount_target_pct = 50.5", git(discount_target_pct=50.5), "discount_target_pct")
    st, _b = gsave(git(discount_target_pct=50), None)
    check("gm: discount_target_pct = 50 валиден", st in (200, 409))
    gbad("nsuid_us с буквами", git(nsuid_us="7001abc000320"), "nsuid_us")
    gbad("eshop_url с http://", git(eshop_url="http://nintendo.com/x"), "eshop_url")
    gbad("deleted строкой", git(deleted="true"), "deleted")
    gbad("дубль названия (регистр/пробелы)",
         gdoc([{"title": "Hollow Knight", "state": "хочу"}, {"title": "hollow  knight", "state": "хочу"}]), "дважды")
    gbad("неизвестное поле", git(foo=1), "неизвестные поля")
    # запись со ВСЕМИ разрешёнными полями: валидатор обязан пройти по каждой ветке (2026-11-10: проверка cover_tried
    # ссылалась на несуществующее имя → NameError → 502 на «Подобрать обложки»; ни один тест поле не слал)
    _full = {"title": "Full", "platform": "steam_deck", "state": "куплена", "rating": "нормально", "progress": "играю", "note": "n", "hours": 3,
             "price_target_usd": 10, "discount_target_pct": 50, "nsuid_us": "70010000003208", "steam_appid": "367520",
             "eshop_url": "https://www.nintendo.com/us/store/products/x/", "cover_url": "https://example.com/c.jpg",
             "store_title": "Full™", "cover_tried": "2026-11-10", "deleted": False, "demo": False, "updated": "2026-11-10", "added": "2026-11-01"}
    check("gm: тест «все поля» покрывает весь белый список полей записи",
          set(_full) == set(server.GAMING_ITEM_KEYS) if hasattr(server, "GAMING_ITEM_KEYS") else True)
    st, _b = gsave(gdoc([_full]), None)
    check(f"gm: запись со всеми полями (вкл. cover_tried) проходит валидатор ({st})", st in (200, 409))
    gbad("cover_tried не дата", git(cover_tried="вчера"), "cover_tried")
    # три оси: прохождение — null или живой код game_progress, не-null только у куплена/демо; legacy state/rating принимаются
    gbad("progress вне enum", git(state="куплена", progress="почти"), "progress")
    gbad("progress у state «хочу»", git(state="хочу", progress="играю"), "progress")
    gbad("progress у state «не-интересно»", git(state="не-интересно", progress="брошена"), "progress")
    gbad("demo не булево", git(state="хочу", demo="да"), "demo")
    for _st, _pr, _dm in (("куплена", "пройдена", False), ("демо", "отложена", False), ("на-карандаш", "отложена", True), ("куплена", None, False), ("хочу", None, False)):
        st, _b = gsave(git(state=_st, progress=_pr, demo=_dm), None)
        check(f"gm: state {_st} + demo {_dm} + progress {_pr} валидны ({st})", st in (200, 409))
    check("gm: нормализатор — старое «демо» и demo у «куплена» (чистая функция)",
          json.loads(server.normalize_gaming(git(state="демо")))["items"][0]["state"] == "на-карандаш"
          and "demo" not in json.loads(server.normalize_gaming(git(state="куплена", demo=True)))["items"][0]
          and server.normalize_gaming("{сломан") == "{сломан")
    with_validate_err = None
    try:
        server.validate_gaming(GM, git(state="куплена", demo=True))
    except ValueError as _e:
        with_validate_err = str(_e)
    check("gm: валидатор без нормализации отвергает demo у «куплена»", with_validate_err is not None and "demo" in with_validate_err)
    for _leg in ({"state": "играю"}, {"state": "пройдена"}, {"state": "куплена", "rating": "брошено"}):
        st, _b = gsave(git(**_leg), None)
        check(f"gm: legacy {_leg} пока принимается ({st})", st in (200, 409))

    check("gaming_key: двоеточие", server.gaming_key("Zelda: Tears of the Kingdom") == server.gaming_key("zelda tears of the kingdom"))
    check("gaming_key: апостроф", server.gaming_key("Baldur's Gate") == server.gaming_key("baldurs gate"))

    for _gp in ("Gaming/taste-profile.yaml", "Gaming/watchlist.yaml", "Gaming/eshop-prices.json"):
        st, _b = api("POST", "/api/gm/save", {"path": _gp, "content": "x: 1\n", "base_hash": None})
        check(f"gm: {_gp} вне whitelist → 403", st == 403)
    check("общий whitelist не пускает Gaming/user-state.json", not server.is_allowed(GM))
    st, _b = api("POST", "/api/save", {"path": GM, "content": G1, "base_hash": None})
    check("общая зона /api/save: Gaming/user-state.json → 403", st == 403)
    st, body = api("GET", "/api/health")
    check("healthcheck: gaming_files == ['user-state']", body.get("gaming_files") == ["user-state"])
    shutil.rmtree(groot / ".versions" / "Gaming", ignore_errors=True)
    gpath.unlink(missing_ok=True)

    # проброс массового подбора nsuid: маршрут есть (не 404), hub-notify в тесте нет → 502
    st, body = api("POST", "/api/games/nsuid-fill", {"items": [{"title": "Hades"}]})
    check("games: POST /api/games/nsuid-fill — маршрут есть, без hub-notify → 502", st == 502)

    # ── зона «Еда»: тот же корень, что travel/games, но своя схема ────────────
    froot = tempfile.mkdtemp(prefix="hub-api-food-")
    server.FOOD_ROOT = froot
    (Path(froot) / "recipes").mkdir()
    fpath = Path(froot) / RECIPE_PATH
    fpath.write_text(RECIPES_OK, encoding="utf-8")

    st, body = api("GET", "/api/fd/file?path=recipes/bolognese.json")
    check("fd file 200", st == 200)
    check("fd file контент", json.loads(body["content"])["servings"] == 6)
    fh = body["hash"]

    scaled = json.loads(RECIPES_OK)
    scaled["servings"] = 10
    st, body = api("POST", "/api/fd/save",
                   {"path": RECIPE_PATH,
                    "content": json.dumps(scaled, ensure_ascii=False), "base_hash": fh})
    check("fd save 200", st == 200)
    check("fd save применён",
          json.loads(fpath.read_text(encoding="utf-8"))["servings"] == 10)
    fh2 = body["hash"]

    # servings=0 разнёс бы NaN по всему списку покупок — файл трогать нельзя
    broken = json.loads(RECIPES_OK)
    broken["servings"] = 0
    st, body = api("POST", "/api/fd/save",
                   {"path": RECIPE_PATH,
                    "content": json.dumps(broken, ensure_ascii=False), "base_hash": fh2})
    check("fd servings=0 → 400", st == 400)
    check("fd 400 объясняет причину", "servings" in (body.get("detail") or ""))
    check("fd битая схема: файл НЕ тронут",
          json.loads(fpath.read_text(encoding="utf-8"))["servings"] == 10)

    st, body = api("POST", "/api/fd/save",
                   {"path": RECIPE_PATH, "content": RECIPES_OK, "base_hash": fh})
    check("fd устаревший hash → 409 (правка со второго устройства)", st == 409)

    # ── создание НОВОГО файла (рецепт по файлу) ──────────────────────────────
    # base_hash=null означает «файла ещё нет, создать». Без этого редактор не
    # мог бы сохранить новый рецепт — сайдкар отвечал «bad request body».
    newdoc = recipe_doc(id="novyy", title="Новый")
    st, body = api("POST", "/api/fd/save",
                   {"path": "recipes/novyy.json", "content": newdoc, "base_hash": None})
    check("fd создание нового файла (base_hash=null) → 200", st == 200)
    check("новый файл появился на диске",
          (Path(froot) / "recipes/novyy.json").exists())
    # Повторное создание того же имени — гонка, а не тихая перезапись.
    st, body = api("POST", "/api/fd/save",
                   {"path": "recipes/novyy.json", "content": newdoc, "base_hash": None})
    check("повторное создание существующего → 409", st == 409)
    # Битый новый файл валидатор всё так же отклоняет.
    st, body = api("POST", "/api/fd/save",
                   {"path": "recipes/krivoy.json",
                    "content": recipe_doc(id="krivoy", servings=0), "base_hash": None})
    check("новый файл с servings=0 → 400 (валидатор работает и на создании)", st == 400)
    check("кривой новый файл не создан", not (Path(froot) / "recipes/krivoy.json").exists())

    # изоляция зон в обе стороны
    st, body = api("GET", "/api/fd/file?path=" + urllib.request.quote(
        "travel-planner/trips/x/3_big-story.md"))
    check("fd: путь travel/games → 403", st == 403)
    st, body = api("GET", "/api/fd/file?path=inbox/pasta.md")
    check("fd: inbox вне whitelist → 403", st == 403)
    st, body = api("GET", "/api/file?path=recipes/bolognese.json")
    check("основная зона: food-путь → 403 (иначе запись мимо валидатора)", st == 403)
    st, body = api("GET", "/api/fd/file?path=" + urllib.request.quote("../etc/passwd"))
    check("fd traversal → 400", st == 400)

    st, body = api("GET", "/api/health")
    check("healthcheck объявляет food_files", body.get("food_files") == list(server.FOOD_FILES))
    check("healthcheck объявляет food_delete", body.get("food_delete") is True)

    # ── оценка «понравилось»: 1..3 или поля нет ─────────────────────────────
    # Карточка рисует звёзды по этому числу. Строка "3" молча дала бы пустую
    # шкалу, а 0 путал бы «не понравилось» с «не пробовали» — неоценённое
    # блюдо это ОТСУТСТВИЕ поля.
    for _rt, _ok in ((1, True), (3, True), (None, True),
                     (0, False), ("3", False), (4, False), (2.5, False), (True, False)):
        _doc = json.loads(recipe_doc(id="ocenka", title="Оценка"))
        if _rt is None:
            _doc.pop("rating", None)
        else:
            _doc["rating"] = _rt
        try:
            server.validate_food("recipes/ocenka.json", json.dumps(_doc, ensure_ascii=False))
            _got = True
        except ValueError:
            _got = False
        check(f"validate_food: rating={_rt!r} → {'принят' if _ok else 'отклонён'}", _got == _ok)

    # ── удаление файла рецепта ──────────────────────────────────────────────
    # Кнопка «Удалить рецепт» на странице. Опасное действие, поэтому проверяем
    # три вещи: удаляется то и только то, что разрешено; удаление невозможно
    # вслепую; удалённое лежит в .versions/.
    delpath = "recipes/novyy.json"
    st, body = api("GET", "/api/fd/file?path=" + urllib.request.quote(delpath))
    delhash = body["hash"]

    # Хэш от старой версии — файл уже поменяли с другого устройства.
    st, body = api("POST", "/api/fd/delete", {"path": delpath, "base_hash": "0" * 64})
    check("fd delete с чужим hash → 409", st == 409)
    check("после 409 файл на месте", (Path(froot) / delpath).exists())

    # base_hash обязателен строкой: «сотри, что там лежит» невозможно.
    st, body = api("POST", "/api/fd/delete", {"path": delpath, "base_hash": None})
    check("fd delete без base_hash → 400 (удаления вслепую нет)", st == 400)
    check("после 400 файл на месте", (Path(froot) / delpath).exists())

    st, body = api("POST", "/api/fd/delete", {"path": delpath, "base_hash": delhash})
    check("fd delete → 200", st == 200)
    check("файл удалён", not (Path(froot) / delpath).exists())
    _bak = list((Path(froot) / ".versions/recipes").glob("*_novyy.json"))
    check("удалённый рецепт лежит в .versions/", len(_bak) == 1)
    check("бэкап содержит прежний файл",
          _bak and json.loads(_bak[0].read_text(encoding="utf-8"))["title"] == "Новый")

    st, body = api("POST", "/api/fd/delete", {"path": delpath, "base_hash": delhash})
    check("повторное удаление → 404", st == 404)

    # Живое состояние раздела веб-кнопкой не стирается: whitelist на удаление
    # УЖЕ, чем на запись (products.json писать можно, удалять — нет).
    (Path(froot) / "products.json").write_text(
        '{"schema":"food-products@1","products":[]}', encoding="utf-8")
    st, body = api("GET", "/api/fd/file?path=products.json")
    _phash = body["hash"]
    st, body = api("POST", "/api/fd/delete", {"path": "products.json", "base_hash": _phash})
    check("fd delete products.json → 403", st == 403)
    check("products.json на месте", (Path(froot) / "products.json").exists())
    st, body = api("POST", "/api/fd/delete", {"path": "shopping.json", "base_hash": _phash})
    check("fd delete shopping.json → 403", st == 403)

    # Удаление есть ТОЛЬКО у зоны еды: ни здоровье, ни travel/games его не знают.
    for _p in ("/api/delete", "/api/hd/delete"):
        st, body = api("POST", _p, {"path": "meds.json", "base_hash": "x"})
        check(f"{_p} → 404 (удаление только у еды)", st == 404)

    # ── /api/fd/shop-add: шорткат iPhone, только продукты каталога ─────────────
    print("shop-add")
    sys.path.insert(0, str(REPO / "tools/food"))
    import match_products  # noqa: E402
    for s in ("Говяжий фарш (80/20)", "Сметана 20%", "Жёлтый лук", "молоко варёное", "  Индейка, филе "):
        check(f"shop_normalize == match_products.normalize: {s!r}",
              server.shop_normalize(s) == match_products.normalize(s))

    check("parse: хвостовое число", server.shop_parse("молоко 2") == ("молоко", 2.0, None))
    check("parse: 20% — не количество", server.shop_parse("сметана 20%") == ("сметана 20%", None, None))
    check("parse: число в начале + единица", server.shop_parse("2 кг гречки") == ("гречки", 2.0, "кг"))
    check("parse: жирность + литры", server.shop_parse("молоко 3,2% 1 л") == ("молоко 3,2%", 1.0, "л"))
    check("parse: точка в конце диктовки", server.shop_parse("гречка 500 г.") == ("гречка", 500.0, "г"))
    for _t, _want in (("молоко 2 литра", ("молоко", 2.0, "л")),
                      ("индейка 500 грамм", ("индейка", 500.0, "г")),
                      ("картошка 2 килограмма", ("картошка", 2.0, "кг")),
                      ("яйца 10 штук", ("яйца", 10.0, "шт")),
                      ("гречка 1 кило", ("гречка", 1.0, "кг")),
                      ("200 миллилитров сливок", ("сливок", 200.0, "мл")),
                      ("сметана 20 граммов", ("сметана", 20.0, "г"))):
        check(f"parse: единица словом {_t!r}", server.shop_parse(_t) == _want)
    check("parse: «грамм» не режется на «г»+«рамм»",
          server.shop_parse("индейка 500 грамм")[0] == "индейка")
    _p = {"name": "X"}
    check("qty: кг к продукту в г", server.shop_qty(1.5, "кг", "г", _p) == (1500.0, None))
    check("qty: г к продукту в кг", server.shop_qty(500, "г", "кг", _p) == (0.5, None))
    check("qty: голое число для шт — штуки", server.shop_qty(10, None, "шт", _p) == (10, None))
    check("qty: голое число для г без фасовки — переспросить",
          server.shop_qty(2, None, "г", _p)[0] is None)
    check("qty: голое число для мл с фасовкой — упаковки",
          server.shop_qty(2, None, "мл", {"name": "M", "pack_size": 930}) == (1860, None))
    check("qty: разные базы — отказ", server.shop_qty(2, "л", "г", _p)[0] is None)

    (Path(froot) / "products.json").write_text(json.dumps({
        "schema": "food-products@1", "products": [
            {"id": "moloko", "name": "Молоко 3,2%", "aliases": ["молоко"], "unit": "мл"},
            {"id": "smetana-20", "name": "Сметана 20%", "aliases": [], "unit": "г"},
            {"id": "smetana-10", "name": "Сметана 10%", "aliases": [], "unit": "г"},
            {"id": "grechka", "name": "Гречка", "aliases": [], "unit": "г"},
            {"id": "grech-yogurt", "name": "Греческий йогурт", "aliases": [], "unit": "г"},
            {"id": "kefir", "name": "Кефир", "aliases": [], "unit": "мл", "pack_size": 900},
            {"id": "yaytsa", "name": "Яйца", "aliases": [], "unit": "шт"},
        ]}, ensure_ascii=False), encoding="utf-8")
    shop_file = Path(froot) / "shopping.json"
    shop_file.write_text('{"schema":"food-shopping@1","updated":"2026-09-01","items":[]}',
                         encoding="utf-8")

    def shop_items():
        return json.loads(shop_file.read_text(encoding="utf-8"))["items"]

    st, body = api("POST", "/api/fd/shop-add", {"text": "Сметана 20%"})
    check("shop-add: точное имя → added", st == 200 and body.get("status") == "added")
    it = shop_items()[0]
    check("shop-add: строка по контракту страницы",
          it["product_id"] == "smetana-20" and it["qty"] is None and it["unit"] == "г"
          and it["extra"] == 0 and it["bought"] is False and it["from"] == []
          and it["id"].startswith("i") and it["name"] == "Сметана 20%")
    check("shop-add: 20% не ушло в количество", it["qty"] is None)
    check("shop-add: бэкап в .versions/",
          len(list((Path(froot) / ".versions").glob("*_shopping.json"))) >= 1)

    st, body = api("POST", "/api/fd/shop-add", {"text": "сметана 20%"})
    check("shop-add: повтор без количества → exists", body.get("status") == "exists")
    check("shop-add: exists ничего не пишет", len(shop_items()) == 1)

    st, body = api("POST", "/api/fd/shop-add", {"text": "Сметана 20% 400 г"})
    check("shop-add: повтор с количеством → merged", body.get("status") == "merged")
    check("shop-add: прибавка ушла в extra", shop_items()[0]["extra"] == 400 and len(shop_items()) == 1)

    st, body = api("POST", "/api/fd/shop-add", {"text": "молоко 1 л"})
    check("shop-add: алиас + литры → мл", body.get("status") == "added"
          and shop_items()[-1]["qty"] == 1000 and shop_items()[-1]["unit"] == "мл")

    st, body = api("POST", "/api/fd/shop-add", {"text": "гречка 2"})
    check("shop-add: голое число к весовому без фасовки → need_unit", body.get("status") == "need_unit")
    st, body = api("POST", "/api/fd/shop-add", {"text": "кефир 2"})
    check("shop-add: голое число с фасовкой → упаковки",
          body.get("status") == "added" and shop_items()[-1]["qty"] == 1800)
    shop_file.write_text(json.dumps(dict(json.loads(shop_file.read_text(encoding="utf-8")),
                         items=shop_items()[:-1]), ensure_ascii=False), encoding="utf-8")
    st, body = api("POST", "/api/fd/shop-add", {"text": "гречка 2 шт"})
    check("shop-add: чужая единица → unit_mismatch", body.get("status") == "unit_mismatch")
    check("shop-add: unit_mismatch ничего не пишет", len(shop_items()) == 2)

    st, body = api("POST", "/api/fd/shop-add", {"text": "сметана 300 г"})
    check("shop-add: неоднозначно → choose", body.get("status") == "choose")
    cands = body.get("candidates") or []
    check("shop-add: кандидаты — обе сметаны с количеством",
          sorted(c for c in cands if c != server.SHOP_SKIP)
          == ["Сметана 10% 300 г", "Сметана 20% 300 г"])
    check("shop-add: последний вариант — пропустить", cands[-1] == server.SHOP_SKIP)
    check("shop-add: количество в заголовке выбора", "300 г" in body.get("message", ""))
    check("shop-add: choose ничего не пишет", len(shop_items()) == 2)
    st, body = api("POST", "/api/fd/shop-add", {"text": "Сметана 10% 300 г"})
    check("shop-add: выбранный кандидат → added с тем же количеством",
          body.get("status") == "added" and shop_items()[-1]["product_id"] == "smetana-10"
          and shop_items()[-1]["qty"] == 300)

    st, body = api("POST", "/api/fd/shop-add", {"text": "гречки"})
    check("shop-add: падеж с единственным продуктом по основе → добавлено",
          body.get("status") in ("added", "exists") and "Гречка" in body.get("message", ""))
    check("основа: разное число слов — не совпадение",
          server.shop_stem_exact("йогурта", [{"name": "Греческий йогурт"}]) == [])
    check("основа: числа сравниваются точно",
          server.shop_stem_exact("сметаны 20", [{"name": "Сметана 15%"}]) == [])
    check("основа: два продукта с одной основой — не автоприменение",
          len(server.shop_stem_exact("сметаны", [{"name": "Сметана"}, {"name": "Сметаны", "aliases": []}])) == 2)
    check("основа: разные слова не сближаются",
          server.shop_stem_exact("картошки", [{"name": "Картофель"}]) == [])
    check("основа: «хлебца» не превращается в «Хлеб»",
          server.shop_stem_exact("хлебца", [{"name": "Хлеб"}]) == [])
    st, body = api("POST", "/api/fd/shop-add", {"text": "сметаны"})
    check("падеж, но продуктов по основе нет, а похожих два → choose",
          body.get("status") == "choose")
    st, body = api("POST", "/api/fd/shop-add", {"text": "молоко 5%"})
    check("shop-add: число само по себе кандидата не тянет",
          all("Сметана" not in c for c in body.get("candidates") or []))

    st, body = api("POST", "/api/fd/shop-add", {"text": "ананас 2"})
    check("shop-add: нет в каталоге → not_found", body.get("status") == "not_found")
    check("shop-add: продукт в каталог НЕ заводится",
          "ананас" not in (Path(froot) / "products.json").read_text(encoding="utf-8").lower())

    st, body = api("POST", "/api/fd/shop-add", {"text": "   "})
    check("shop-add: пустой ввод → empty", body.get("status") == "empty")
    st, body = api("POST", "/api/fd/shop-add", {"txt": "молоко"})
    check("shop-add: битое тело → 400", st == 400)

    # ── несколько позиций одной фразой ──
    _prods = json.loads((Path(froot) / "products.json").read_text(encoding="utf-8"))["products"]
    _prods.append({"id": "gov-sup", "name": "Говядина, суповой набор", "aliases": [], "unit": "г"})
    (Path(froot) / "products.json").write_text(json.dumps(
        {"schema": "food-products@1", "products": _prods}, ensure_ascii=False), encoding="utf-8")
    _prods.append({"id": "kur-farsh", "name": "Куриный фарш", "aliases": [], "unit": "г"})
    _prods.append({"id": "gov-farsh", "name": "Говяжий фарш", "aliases": [], "unit": "г"})
    (Path(froot) / "products.json").write_text(json.dumps(
        {"schema": "food-products@1", "products": _prods}, ensure_ascii=False), encoding="utf-8")
    _prods2 = _prods
    sp = lambda t: server.shop_split(t, _prods)  # noqa: E731
    check("split: запятые и «и»", sp("молоко 2 литра, яйца 10 и гречка 500 г")
          == ["молоко 2 литра", "яйца 10", "гречка 500 г"])
    check("split: без запятых — граница после единицы",
          sp("молоко 2 литра гречка 500 г") == ["молоко 2 литра", "гречка 500 г"])
    check("split: десятичная запятая не режет", sp("молоко 3,2% 1 л, яйца") == ["молоко 3,2% 1 л", "яйца"])
    check("split: связки речи срезаются",
          sp("мне нужно молока 900 мл, и ещё яйца") == ["молока 900 мл", "яйца"])
    check("split: запятая в названии каталога сохраняется",
          sp("Говядина, суповой набор 500 г, яйца") == ["Говядина, суповой набор 500 г", "яйца"])
    check("split: голое число не режет", sp("сметана 20 молоко") == ["сметана 20 молоко"])

    shop_file.write_text('{"schema":"food-shopping@1","updated":"2026-09-01","items":[]}',
                         encoding="utf-8")
    _bk_before = len(list((Path(froot) / ".versions").glob("*_shopping.json")))
    st, body = api("POST", "/api/fd/shop-add",
                   {"text": "мне нужно молока 900 мл, яйца 10, сметана 300 г, гречка 2 и ананас"})
    check("batch: status", st == 200 and body.get("status") == "batch")
    _its = shop_items()
    check("batch: добавлены однозначные позиции одной записью (молока — по основе)",
          sorted(i["product_id"] for i in _its) == ["moloko", "yaytsa"])
    check("batch: id уникальны", len({i["id"] for i in _its}) == len(_its))
    check("batch: ровно один бэкап на запрос",
          len(list((Path(froot) / ".versions").glob("*_shopping.json"))) - _bk_before <= 1)
    _ch = body.get("choose") or []
    check("batch: неоднозначные — в choose с количеством",
          any("Сметана 20% 300 г" in c["candidates"] for c in _ch))
    _m = body.get("message", "")
    check("batch: сводка — итоги, без «Уточните» (их доспрашивает цикл)",
          "Добавлено: " in _m and "Яйца — 10 шт" in _m and "Уточните" not in _m
          and "Нет в каталоге: ананас" in _m and "Нужна единица" in _m)
    check("batch: неоднозначные видны только в choose", len(_ch) >= 1)
    st, body = api("POST", "/api/fd/shop-add", {"text": "яйца 5, яйца 5"})
    check("batch: одна позиция дважды — прибавка к той же строке",
          body.get("status") == "batch"
          and [i["extra"] for i in shop_items() if i["product_id"] == "yaytsa"] == [10])
    # Модель (в облаке) склеивает число с названием и переставляет слова —
    # промту верить нельзя, разбор обязан это переживать (случай 22.09).
    check("склейка: буква↔цифра", server.shop_unglue("молоко300мл") == "молоко 300 мл")
    check("склейка: процент↔цифра", server.shop_unglue("сметана20%200г") == "сметана 20% 200 г")
    check("склейка: парсинг склеенного", server.shop_parse("хлеб100г") == ("хлеб", 100.0, "г"))
    check("склейка: нормальный текст не трогается", server.shop_unglue("хлеб 100 г") == "хлеб 100 г")
    check("порядок слов не значим",
          [p["id"] for p in server.shop_stem_exact("фарш куриный", _prods2)] == ["kur-farsh"])
    check("склеенные слова разрезаются по каталогу",
          [p["id"] for p in server.shop_stem_exact("фаршкуриный", _prods2)] == ["kur-farsh"])
    check("склеенное слово с двумя разрезами — не автоприменение",
          server.shop_stem_exact("фаршговяжийкуриный", _prods2) == [])
    check("неизвестное длинное слово не режется",
          server.shop_stem_exact("творожноезерно", _prods2) == [])
    _n_before = len(shop_items())
    st, body = api("POST", "/api/fd/shop-add", {"text": server.SHOP_SKIP})
    check("пропуск: ничего не пишется и не ищется в каталоге",
          body.get("status") == "skipped" and len(shop_items()) == _n_before)
    st, body = api("POST", "/api/fd/shop-add", {"text": "молоко300мл|фаршкуриный1кг"})
    check("e2e: склеенный ответ модели разбирается",
          body.get("status") == "batch" and body.get("choose") == []
          and sorted(i["product_id"] for i in shop_items() if i["product_id"] in ("moloko", "kur-farsh"))
          == ["kur-farsh", "moloko"])
    check("split: «я хочу купить в магазине» срезается",
          sp("я хочу купить в магазине 300 г хлеба") == ["300 г хлеба"])
    check("split: число впереди не отрезается от названия",
          sp("хлеб, предположим 500 гр гречки") == ["хлеб", "500 гр гречки"])
    check("split: число впереди после позиции с единицей",
          sp("молоко 2 литра 500 гр гречки") == ["молоко 2 литра", "500 гр гречки"])
    check("split: разделитель модели «|»",
          sp("Молоко 3,2% 900 мл | Гречка 500 г|яйца") == ["Молоко 3,2% 900 мл", "Гречка 500 г", "яйца"])
    shop_file.write_text('{"schema":"food-shopping@1","updated":"2026-09-01","items":[]}',
                         encoding="utf-8")
    st, body = api("POST", "/api/fd/shop-add", {
        "text": "Молоко 3,2% 900 мл | Гречка 900 г | Яйца 10",
        "source": "мне нужно молока 900 мл, 500 гр гречки и десяток яиц"})
    _m = body.get("message", "")
    check("source: число из фразы — добавлено", "Молоко 3,2% — 900 мл" in _m)
    check("source: искажённое число (500→900) — не добавлено",
          "Проверьте число" in _m and "Гречка 900 г" in _m
          and all(i["product_id"] != "grechka" for i in shop_items()))
    check("source: «десяток» → 10 модель вывела сама — не добавлено",
          all(i["product_id"] != "yaytsa" for i in shop_items()))
    st, body = api("POST", "/api/fd/shop-add", {"text": "сметана 700 г", "source": "сметаны 300 г"})
    check("source: выдуманное число у неоднозначной позиции — не в кандидаты",
          body.get("status") == "suspect" and body.get("choose") == [])
    shop_file.write_text('{"schema":"food-shopping@1","updated":"2026-09-01","items":[]}',
                         encoding="utf-8")
    st, body = api("POST", "/api/fd/shop-add", {
        "items": ["Говядина, суповой набор 500 г", "яйца 10", " ", "гречка 700 г"],
        "source": "говядины суповой набор 500 грамм, 10 яиц и гречки 300 г"})
    _m = body.get("message", "")
    check("items: запятая внутри элемента не режется",
          any(i["product_id"] == "gov-sup" and i["qty"] == 500 for i in shop_items()))
    check("items: пустой элемент пропущен, остальные обработаны",
          body.get("status") == "batch" and len(body.get("items") or []) == 3)
    check("items: source сверяется и для списка", "Проверьте число: гречка 700 г" in _m)
    st, body = api("POST", "/api/fd/shop-add", {"items": ["яйца"]})
    check("items из одного элемента — одиночный ответ", body.get("status") in ("added", "merged", "exists"))
    st, body = api("POST", "/api/fd/shop-add", {"items": []})
    check("items пустой → empty", body.get("status") == "empty")
    st, body = api("POST", "/api/fd/shop-add", {"text": "хлеб", "items": ["хлеб"]})
    check("text и items вместе → 400", st == 400)
    st, body = api("POST", "/api/fd/shop-add", {"items": ["хлеб", 5]})
    check("items не из строк → 400", st == 400)
    st, body = api("POST", "/api/fd/shop-add", {"text": "яйца|гречка триста",
                                                 "source": "10 яиц и 300 г гречки"})
    check("source: потерянные моделью числа — предупреждение",
          sorted(body.get("lost_numbers") or []) == ["10", "300"] and "Не учтены числа" in body.get("message", ""))
    st, body = api("POST", "/api/fd/shop-add", {"text": "Сметана 20% 200 г", "source": "сметаны 20% 200 г"})
    check("source: жирность во фразе — не «потерянное» число",
          not body.get("lost_numbers") and "Не учтены" not in body.get("message", ""))
    st, body = api("POST", "/api/fd/shop-add", {"text": "хлеб", "source": 5})
    check("source не строкой → 400", st == 400)
    st, body = api("POST", "/api/fd/shop-add", {"text": "Говядина, суповой набор"})
    check("одна позиция с запятой в названии — не batch", body.get("status") in ("added", "exists"))
    check("одиночный ответ несёт пустой choose", body.get("choose") == [])
    st, body = api("POST", "/api/fd/shop-add", {"text": "сметана"})
    check("одиночный choose: candidates и сверху, и в choose",
          body.get("status") == "choose" and body["choose"][0]["candidates"] == body["candidates"])

    doc = json.loads(shop_file.read_text(encoding="utf-8"))
    check("shop-add: схема и updated на месте",
          doc["schema"] == "food-shopping@1" and doc["updated"] != "2026-09-01")
    try:
        server.validate_food("shopping.json", shop_file.read_text(encoding="utf-8"))
        check("shop-add: файл проходит validate_food", True)
    except ValueError:
        check("shop-add: файл проходит validate_food", False)
    st, body = api("GET", "/api/health")
    check("health сообщает food_shop_add", body.get("food_shop_add") is True)
finally:
    httpd.shutdown()
    shutil.rmtree(tmp)

# ── MOEX: котировки quotes@1 (GET /api/moex/quotes) ──────────────────────────
# Без сети: ISS подменяется фикстурой tools/tests/fixtures/iss/tqbr.json (живой
# срез 13.10) и синтетикой. Правило цены — то же, что у загрузчика
# (_shared-references/moex_quotes.py::_normalize): LAST → MARKETPRICE → PREVPRICE.
print("moex")
from datetime import datetime  # noqa: E402

_iss = json.loads((REPO / "tools/tests/fixtures/iss/tqbr.json").read_text(encoding="utf-8"))
_items = server.iss_board_to_items("TQBR", _iss)
check("moex: фикстура даёт сотни бумаг", len(_items) > 300)
for _t in ("SBER", "TMON", "XXXXXX"):
    check(f"moex: {_t} есть в items фикстуры", _t in _items)
_sb = _items["SBER"]
check("moex: SBER — поля quotes@1",
      set(_sb) == {"price", "price_kind", "lot_size", "board", "ts", "prev_close"}
      and _sb["board"] == "TQBR")
check("moex: SBER lot_size — целое > 0", isinstance(_sb["lot_size"], int) and _sb["lot_size"] > 0)
check("moex: price_kind только из трёх значений",
      all(v["price_kind"] in ("last", "market", "prev_close") for v in _items.values()))
check("moex: у всех items цена > 0", all(v["price"] > 0 for v in _items.values()))


def _iss_rows(sec_rows, md_rows):
    return {"securities": {"columns": ["SECID", "LOTSIZE", "PREVPRICE", "PREVDATE"], "data": sec_rows},
            "marketdata": {"columns": ["SECID", "LAST", "MARKETPRICE", "LCURRENTPRICE", "UPDATETIME",
                                       "SYSTIME", "TRADINGSTATUS"], "data": md_rows}}


_syn = server.iss_board_to_items("TQBR", _iss_rows(
    [["AAA", 10, 100.0, "2026-10-12"], ["BBB", 1, 200.0, "2026-10-12"], ["CCC", 100, 300.0, "2026-10-12"],
     ["DDD", 1, None, None], ["EEE", 0, 50.0, "2026-10-12"], ["FFF", None, 60.0, "2026-10-12"]],
    [["AAA", 101.5, 100.7, 101.5, "14:00:00", "2026-10-13 14:01:00", "T"],
     ["BBB", None, 201.2, None, "", "2026-10-13 14:01:00", "T"],
     ["CCC", None, None, None, "", "2026-10-13 14:01:00", "N"],
     ["DDD", None, None, None, "", "", "N"],
     ["EEE", 0, 0, 0, "", "", "N"],
     ["FFF", None, None, None, "", "", "N"]]))
check("moex: LAST есть → last, ts = SYSTIME",
      _syn["AAA"]["price"] == 101.5 and _syn["AAA"]["price_kind"] == "last"
      and _syn["AAA"]["ts"] == "2026-10-13 14:01:00" and _syn["AAA"]["prev_close"] == 100.0)
check("moex: только MARKETPRICE → market",
      _syn["BBB"]["price"] == 201.2 and _syn["BBB"]["price_kind"] == "market")
check("moex: только PREVPRICE → prev_close, ts = PREVDATE",
      _syn["CCC"]["price"] == 300.0 and _syn["CCC"]["price_kind"] == "prev_close"
      and _syn["CCC"]["ts"] == "2026-10-12")
check("moex: нет никакой цены → бумаги нет в items", "DDD" not in _syn)
check("moex: LOTSIZE 0 → lot_size null (цена при этом есть)",
      _syn["EEE"]["lot_size"] is None and _syn["EEE"]["price_kind"] == "prev_close")
check("moex: LOTSIZE null → lot_size null", _syn["FFF"]["lot_size"] is None)
check("moex: lot_size из LOTSIZE", _syn["AAA"]["lot_size"] == 10 and _syn["CCC"]["lot_size"] == 100)
check("moex: пустой/битый ответ ISS → пустые items",
      server.iss_board_to_items("TQBR", {}) == {} and server.iss_board_to_items("TQBR", None) == {})

# торговые часы MSK: будни 07:00–23:50
_msk = server.MSK
check("moex: будний день 12:00 — торговые часы",
      server.moex_is_trading(datetime(2026, 10, 13, 12, 0, tzinfo=_msk)))
check("moex: 06:59 — вне торговых", not server.moex_is_trading(datetime(2026, 10, 13, 6, 59, tzinfo=_msk)))
check("moex: 07:00 — торговые", server.moex_is_trading(datetime(2026, 10, 13, 7, 0, tzinfo=_msk)))
check("moex: 23:50 — вне торговых", not server.moex_is_trading(datetime(2026, 10, 13, 23, 50, tzinfo=_msk)))
check("moex: суббота 12:00 — вне торговых", not server.moex_is_trading(datetime(2026, 10, 17, 12, 0, tzinfo=_msk)))
check("moex: TTL 5 мин в торговые, 30 мин вне",
      server.moex_ttl(datetime(2026, 10, 13, 12, 0, tzinfo=_msk)) == 300
      and server.moex_ttl(datetime(2026, 10, 17, 12, 0, tzinfo=_msk)) == 1800)

# кэш: подменяем выборку
_fetch_saved = server.moex_fetch_board
_calls = []
_mode = {"fail": False}


def _fake_fetch(board):
    _calls.append(board)
    if _mode["fail"]:
        raise OSError("ISS down")
    return _iss_rows([["AAA", 10, 100.0, "2026-10-12"]],
                     [["AAA", 101.5, 100.7, 101.5, "14:00:00", "2026-10-13 14:01:00", "T"]])


server.moex_fetch_board = _fake_fetch
server._MOEX_CACHE.clear()
_t0 = datetime(2026, 10, 13, 12, 0, 0, tzinfo=_msk)
try:
    q = server.moex_quotes(["TQBR"], now=_t0)
    check("moex: quotes@1 — шапка",
          q["schema"] == "quotes@1" and q["source"] == "moex_iss" and q["delayed_min"] == 15
          and q["stale"] is False and "AAA" in q["items"])
    check("moex: fetched_at с +03:00", q["fetched_at"].endswith("+03:00")
          and q["boards"]["TQBR"]["fetched_at"] == q["fetched_at"] and q["boards"]["TQBR"]["stale"] is False)
    check("moex: первый вызов ходит в сеть", _calls == ["TQBR"])
    server.moex_quotes(["TQBR"], now=_t0 + timedelta(minutes=4))
    check("moex: второй вызов в TTL не ходит в сеть", _calls == ["TQBR"])
    server.moex_quotes(["TQBR"], now=_t0 + timedelta(minutes=6))
    check("moex: после TTL (5 мин) — новая выборка", _calls == ["TQBR", "TQBR"])
    # вне торговых часов TTL длиннее
    _calls.clear(); server._MOEX_CACHE.clear()
    _sat = datetime(2026, 10, 17, 12, 0, 0, tzinfo=_msk)
    server.moex_quotes(["TQBR"], now=_sat)
    server.moex_quotes(["TQBR"], now=_sat + timedelta(minutes=20))
    check("moex: вне торговых часов 20 мин — ещё кэш", len(_calls) == 1)
    server.moex_quotes(["TQBR"], now=_sat + timedelta(minutes=31))
    check("moex: вне торговых часов 31 мин — новая выборка", len(_calls) == 2)

    # ISS упал, кэш есть → stale
    _mode["fail"] = True
    q = server.moex_quotes(["TQBR"], now=_sat + timedelta(hours=2))
    check("moex: ISS упал при кэше → stale:true и в boards[B].stale",
          q["stale"] is True and q["boards"]["TQBR"]["stale"] is True and "AAA" in q["items"])
    check("moex: stale — fetched_at старый (время исходной выборки)",
          q["fetched_at"] == (_sat + timedelta(minutes=31)).isoformat(timespec="seconds"))
    # кэш старше 24 ч → ошибка
    try:
        server.moex_quotes(["TQBR"], now=_sat + timedelta(hours=25))
        check("moex: кэш старше 24 ч при падении ISS → ошибка", False)
    except server.MoexError:
        check("moex: кэш старше 24 ч при падении ISS → ошибка", True)
    # кэша нет → MoexError
    server._MOEX_CACHE.clear()
    try:
        server.moex_quotes(["TQOB"], now=_t0)
        check("moex: ISS упал, кэша нет → MoexError", False)
    except server.MoexError:
        check("moex: ISS упал, кэша нет → MoexError", True)
    # пустой ответ ISS не затирает кэш
    _mode["fail"] = False
    server._MOEX_CACHE.clear()
    server.moex_quotes(["TQBR"], now=_t0)
    server.moex_fetch_board = lambda b: _iss_rows([], [])
    q = server.moex_quotes(["TQBR"], now=_t0 + timedelta(minutes=10))
    check("moex: пустая доска от ISS не затирает кэш (stale)", q["stale"] and "AAA" in q["items"])

    # склейка параллельных запросов одной доски: одна выборка
    server._MOEX_CACHE.clear()
    _calls.clear()
    _gate = threading.Event()

    def _slow_fetch(board):
        _calls.append(board)
        _gate.wait(2)
        return _fake_iss_ok()

    def _fake_iss_ok():
        return _iss_rows([["AAA", 10, 100.0, "2026-10-12"]],
                         [["AAA", 101.5, 100.7, 101.5, "14:00:00", "2026-10-13 14:01:00", "T"]])

    server.moex_fetch_board = _slow_fetch
    _res = []
    _ths = [threading.Thread(target=lambda: _res.append(server.moex_quotes(["TQBR"], now=_t0)))
            for _ in range(5)]
    for _th in _ths:
        _th.start()
    time.sleep(0.3)
    _gate.set()
    for _th in _ths:
        _th.join(5)
    check("moex: 5 параллельных запросов одной доски → одна выборка",
          len(_calls) == 1 and len(_res) == 5 and all("AAA" in r["items"] for r in _res))
finally:
    server.moex_fetch_board = _fetch_saved
    server._MOEX_CACHE.clear()

# e2e по HTTP: 400 / 200 / 502 (выборка подменена, сеть не нужна)
_mx, _ = serve(server.Handler, quiet=False)
_mbase = f"http://127.0.0.1:{_mx.server_address[1]}"


def _mget(path):
    try:
        with urllib.request.urlopen(_mbase + path) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


_fetch_calls = []


def _board_fetch(board):
    _fetch_calls.append(board)
    return _iss_rows([[board[:3], 1, 10.0, "2026-10-12"]], [])


server.moex_fetch_board = _board_fetch
server._MOEX_CACHE.clear()
try:
    st, body = _mget("/api/moex/quotes?boards=TQXX")
    check("moex e2e: неизвестная доска → 400", st == 400 and "error" in body)
    st, body = _mget("/api/moex/quotes?boards=TQBR,NOPE")
    check("moex e2e: одна неизвестная среди известных → 400", st == 400)
    check("moex e2e: 400 не ходит в сеть", _fetch_calls == [])
    st, body = _mget("/api/moex/quotes")
    check("moex e2e: по умолчанию TQBR → 200 quotes@1",
          st == 200 and body["schema"] == "quotes@1" and list(body["boards"]) == ["TQBR"])
    st, body = _mget("/api/moex/quotes?boards=tqbr,TQOB,TQCB")
    check("moex e2e: несколько досок (регистр не важен) → 200, board у items",
          st == 200 and set(body["boards"]) == {"TQBR", "TQOB", "TQCB"}
          and {v["board"] for v in body["items"].values()} == {"TQBR", "TQOB", "TQCB"})
    check("moex e2e: TQBR из кэша — не перезапрошена", _fetch_calls.count("TQBR") == 1)
    _cbr_saved = server.cbr_fetch_xml
    server._FX_CACHE.clear()
    server.cbr_fetch_xml = lambda: ('<ValCurs Date="11.11.2026"><Valute ID="R01235"><CharCode>USD</CharCode><Nominal>1</Nominal>'
                                    '<Value>80,0</Value></Valute><Valute ID="R01335"><CharCode>KZT</CharCode><Nominal>100</Nominal>'
                                    '<Value>15,9</Value></Valute></ValCurs>')
    try:
        st, body = _mget("/api/moex/quotes?boards=TQOB&fx=kzt")
        check("moex e2e: fx=kzt → блок fx только с KZT, Nominal 100 учтён",
              st == 200 and body["fx"] == {"KZT": 0.159, "date": "2026-11-11"})
        st, body = _mget("/api/moex/quotes?boards=TQOB")
        check("moex e2e: без fx блока нет", st == 200 and "fx" not in body)
        for bad in ("US", "USDD", "U1D", "", ",".join(f"A{c}{d}" for c in "ABCDEF" for d in "AB")):
            st, body = _mget("/api/moex/quotes?boards=TQOB&fx=" + bad)
            check(f"moex e2e: fx={bad[:12]!r} → 400", st == 400 and "error" in body)
    finally:
        server.cbr_fetch_xml = _cbr_saved
        server._FX_CACHE.clear()
    server._MOEX_CACHE.clear()
    server.moex_fetch_board = lambda b: (_ for _ in ()).throw(OSError("down"))
    st, body = _mget("/api/moex/quotes?boards=TQBR")
    check("moex e2e: ISS упал и кэша нет → 502 {error}", st == 502 and "error" in body)
finally:
    server.moex_fetch_board = _fetch_saved
    server._MOEX_CACHE.clear()
    _mx.shutdown()

# ── File Station гибрид (_place / _remove) ───────────────────────────────────
# Вотчер Synology Drive слеп к записям контейнера, поэтому файл на место ставит
# File Station (host-событие). Здесь — фейковый DSM: проверяем, что содержимое
# оказывается на месте через FS-move, что перелогин по 119 работает, и что при
# ЛЮБОЙ поломке DSM сайдкар молча откатывается на локальную запись — контракт
# «запись обязана пройти всегда» важнее скорости доставки в зеркала.
print("file station гибрид")


class _FakeDSM(BaseHTTPRequestHandler):
    """Фейковый DSM: auth.cgi + entry.cgi (CopyMove start/status, Delete).

    fs_map транслирует FS-пути («/fsroot/...») в реальные; move выполняется
    настоящим os.replace — как это делает DSM на хосте.
    """
    fs_map = {}
    logins = 0
    fail_next_with_119 = False   # первый entry.cgi-вызов → 119 (протухший sid)
    start_fails = False          # CopyMove start отвечает success:false
    status_never_finishes = False  # polling не дожидается finished:true
    delete_fails = False

    def log_message(self, *a):  # тишина в тестовом выводе
        pass

    def _json(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @classmethod
    def _real(cls, fs_path):
        for base, root in cls.fs_map.items():
            if fs_path == base or fs_path.startswith(base + "/"):
                return root + fs_path[len(base):]
        raise ValueError(f"нет маппинга для {fs_path}")

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        cls = _FakeDSM   # состояние на базовом классе: serve() оборачивает обработчик подклассом
        if url.path == "/webapi/auth.cgi":
            cls.logins += 1
            self._json({"success": True, "data": {"sid": f"sid-{cls.logins}"}})
            return
        if cls.fail_next_with_119:
            cls.fail_next_with_119 = False
            self._json({"success": False, "error": {"code": 119}})
            return
        api_name, method = q.get("api"), q.get("method")
        if api_name == "SYNO.FileStation.CopyMove" and method == "start":
            if cls.start_fails:
                self._json({"success": False, "error": {"code": 1000}})
                return
            src = self._real(q["path"])
            dst = self._real(q["dest_folder_path"])
            os.replace(src, os.path.join(dst, os.path.basename(src)))
            self._json({"success": True, "data": {"taskid": "FS_task_1"}})
            return
        if api_name == "SYNO.FileStation.CopyMove" and method == "status":
            self._json({"success": True,
                        "data": {"finished": not cls.status_never_finishes}})
            return
        if api_name == "SYNO.FileStation.Delete" and method == "delete":
            if cls.delete_fails:
                self._json({"success": False, "error": {"code": 1000}})
                return
            os.remove(self._real(q["path"]))
            self._json({"success": True})
            return
        self._json({"success": False, "error": {"code": 101}})


tmp = tempfile.mkdtemp(prefix="hub-api-fs-test-")
fake, _ = serve(_FakeDSM, quiet=False)
_fs_saved = (server._FS, dict(server.FS_BASES))
try:
    root = Path(tmp)
    rel = "travel-planner/trips/тест_2026/3_poi_v1.md"
    (root / rel).parent.mkdir(parents=True)

    _FakeDSM.fs_map = {"/fsroot": tmp}
    server._FS = server._FileStation(
        f"http://127.0.0.1:{fake.server_address[1]}", "acc", "pw")
    server.FS_BASES[tmp] = "/fsroot"

    # Успешный путь: создание нового файла через FS-move.
    h = server.save_file(tmp, rel, "# POI v1\n", None)
    check("fs: файл на месте", (root / rel).read_text(encoding="utf-8") == "# POI v1\n")
    check("fs: hash верный", h == server.file_hash("# POI v1\n".encode()))
    check("fs: staging пуст",
          list((root / server.STAGING_DIR).iterdir()) == [])
    check("fs: .hub-api-tmp не создавался",
          not (root / (rel + ".hub-api-tmp")).exists())
    check("fs: был ровно один логин", _FakeDSM.logins == 1)

    # Перезапись существующего (overwrite) + перелогин по 119.
    _FakeDSM.fail_next_with_119 = True
    h2 = server.save_file(tmp, rel, "# POI v2\n", h)
    check("fs: перезапись через FS", (root / rel).read_text(encoding="utf-8") == "# POI v2\n")
    check("fs: перелогин по 119 случился", _FakeDSM.logins == 2)
    check("fs: бэкап в .versions создан",
          len(list((root / ".versions").rglob("*_3_poi_v1.md"))) == 1)

    # Polling не дождался finished — но контент на месте, второй записи нет.
    _FakeDSM.status_never_finishes = True
    server.save_file(tmp, rel, "# POI v3\n", h2)
    check("fs: успех по факту содержимого при опоздавшем статусе",
          (root / rel).read_text(encoding="utf-8") == "# POI v3\n")
    _FakeDSM.status_never_finishes = False

    # CopyMove start падает → локальный откат, запись проходит.
    _FakeDSM.start_fails = True
    h3 = server.read_file(tmp, rel)[1]
    server.save_file(tmp, rel, "# POI v4\n", h3)
    check("fs: откат на os.replace при отказе start",
          (root / rel).read_text(encoding="utf-8") == "# POI v4\n")
    check("fs: откат посчитан в FS_STATS (виден в /api/health)",
          server.FS_STATS["fallbacks"] >= 1 and server.FS_STATS["last_path"] == rel and server.FS_STATS["last"])
    _FakeDSM.start_fails = False

    # Удаление через FS (+ откат при отказе).
    frel = "recipes/fs-del.json"
    (root / "recipes").mkdir()
    doc = '{"schema":"food-recipe@1","title":"T","servings":1,"ingredients":[],"steps":[]}'
    server.save_file(tmp, frel, doc, None, validate=server.validate_food)
    server.delete_file(tmp, frel, server.file_hash(doc.encode()))
    check("fs: удаление через FS", not (root / frel).exists())
    check("fs: бэкап перед удалением есть",
          len(list((root / ".versions" / "recipes").glob("*_fs-del.json"))) == 1)

    _FakeDSM.delete_fails = True
    server.save_file(tmp, frel, doc, None, validate=server.validate_food)
    server.delete_file(tmp, frel, server.file_hash(doc.encode()))
    check("fs: откат удаления на os.remove", not (root / frel).exists())
    _FakeDSM.delete_fails = False

    # DSM целиком недоступен (мёртвый порт) → всё работает локально.
    server._FS = server._FileStation("http://127.0.0.1:1", "acc", "pw")
    h5 = server.read_file(tmp, rel)[1]
    server.save_file(tmp, rel, "# POI v5\n", h5)
    check("fs: DSM лежит — запись прошла локально",
          (root / rel).read_text(encoding="utf-8") == "# POI v5\n")

    # Корень без FS-маппинга → чистое старое поведение (не трогаем staging).
    other = tempfile.mkdtemp(prefix="hub-api-nofs-")
    try:
        os.makedirs(os.path.join(other, "travel-planner/trips/x"))
        server.save_file(other, "travel-planner/trips/x/3_a.md", "x", None)
        check("fs: без маппинга staging не создаётся",
              not os.path.exists(os.path.join(other, server.STAGING_DIR)))
    finally:
        shutil.rmtree(other)
finally:
    server._FS, fbases = _fs_saved[0], _fs_saved[1]
    server.FS_BASES.clear()
    server.FS_BASES.update(fbases)
    fake.shutdown()
    shutil.rmtree(tmp)


# ── .versions: ретенция (2026-10-23) ─────────────────────────────────────────
# Копии копились без предела (копия на каждую галочку «куплено»). Держим VERSIONS_KEEP последних
# на файл, старше VERSIONS_DAYS — удаляем, но VERSIONS_MIN свежих остаются всегда.
print("versions retention")
from datetime import datetime as _dt  # noqa: E402
tmp = tempfile.mkdtemp(prefix="hub-api-ver-")
try:
    root = Path(tmp)
    rel = "travel-planner/trips/x/3_a.md"
    (root / rel).parent.mkdir(parents=True)
    (root / rel).write_text("v0\n", encoding="utf-8")
    t0 = _dt(2026, 10, 1, 12, 0, 0)
    h = server.file_hash(b"v0\n")
    for i in range(1, 36):
        h = server.save_file(tmp, rel, f"v{i}\n", h, now=t0 + timedelta(minutes=i))
    vdir = root / ".versions/travel-planner/trips/x"
    kept = sorted(os.listdir(vdir))
    check(f"35 правок → {server.VERSIONS_KEEP} копий ({len(kept)})", len(kept) == server.VERSIONS_KEEP)
    check("остались самые свежие", kept[-1].startswith("20261001-123500") and kept[0].startswith("20261001-120600"))
    check("последняя копия — предпоследняя версия", (vdir / kept[-1]).read_text(encoding="utf-8") == "v34\n")
    # старые: 10 копий 200-дневной давности + 3 свежие → 3 свежие + 2 старые (VERSIONS_MIN = 5)
    other = "travel-planner/trips/x/3_b.md"
    (root / other).write_text("x\n", encoding="utf-8")
    for i in range(10):
        (vdir / f"202603{10 + i:02d}-120000_3_b.md").write_text("old\n", encoding="utf-8")
    for i in range(3):
        (vdir / f"2026100{1 + i}-120000_3_b.md").write_text("new\n", encoding="utf-8")
    (vdir / "20260101-120000_3_bb.md").write_text("чужой\n", encoding="utf-8")
    server.save_file(tmp, other, "y\n", server.file_hash(b"x\n"), now=_dt(2026, 10, 23, 12, 0, 0))
    b = sorted(n for n in os.listdir(vdir) if n.endswith("_3_b.md"))
    check(f"старые сверх минимума удалены: 4 свежие + 1 старая ({len(b)}: {b[:2]}…)",
          len(b) == server.VERSIONS_MIN and sum(n.startswith("202603") for n in b) == 1)
    check("копии другого файла (bb.md) не тронуты", (vdir / "20260101-120000_3_bb.md").exists())
    check("копии a.md не тронуты чисткой b.md", len([n for n in os.listdir(vdir) if n.endswith("_a.md")])
          == server.VERSIONS_KEEP)
    # удаление рецепта тоже чистит
    fr = root / "Food"
    fr.mkdir()
    check("prune_versions: нет папки — 0, не падает", server.prune_versions(str(fr / "нет"), "x.json") == 0)
    # дописываемый ряд цен (11.11): у daily-ГГГГ.jsonl держим APPEND_VERSIONS_KEEP копий, у соседнего файла — обычное правило
    pdir = root / "pv"
    pdir.mkdir()
    for i in range(10):
        (pdir / f"202611{10 + i:02d}-190000_daily-2026.jsonl").write_text("x\n", encoding="utf-8")
        (pdir / f"202611{10 + i:02d}-190000_other.json").write_text("x\n", encoding="utf-8")
    server.prune_versions(str(pdir), "daily-2026.jsonl", now=_dt(2026, 11, 20, 12, 0, 0))
    server.prune_versions(str(pdir), "other.json", now=_dt(2026, 11, 20, 12, 0, 0))
    dl = sorted(n for n in os.listdir(pdir) if n.endswith("_daily-2026.jsonl"))
    check(f"дневной ряд цен: {server.APPEND_VERSIONS_KEEP} последние копии ({dl})",
          len(dl) == server.APPEND_VERSIONS_KEEP and dl[-1].startswith("20261119"))
    check("соседний файл — по обычному правилу (все 10 свежих целы)", len([n for n in os.listdir(pdir) if n.endswith("_other.json")]) == 10)
finally:
    shutil.rmtree(tmp)

# ── /api/pv/sync — вьюер портфеля одним запросом (2026-10-23) ─────────────────
print("pv sync")
tmp = tempfile.mkdtemp(prefix="hub-api-pv-")
try:
    root = Path(tmp)
    files = {
        "Portfolio/integrated-views/integrated-view-2026-10-01.md": "iv\n",
        "Portfolio/snapshots/portfolio-2026-10-22.json": "{\"a\": 1}",
        "Portfolio/snapshots/portfolio-2026-10-08.json": "{\"a\": 0}",
        "Portfolio/snapshots/notes.txt": "не снапшот",
        "Portfolio/gate-reviews.yaml": "g: 1\n",
        "Portfolio/conditions.yaml": "c: 1\n",
        "Portfolio/other.yaml": "не вьюера",
        "Portfolio/reports/2026-10-01 отчёт по ОФЗ.md": "кириллица и пробел\n",
        "Portfolio/.versions/Portfolio/snapshots/20261001-120000_portfolio-2026-10-08.json": "копия",
        "Portfolio/snapshots/@eaDir/portfolio-2026-10-08.json": "служебное Synology",
        "Portfolio/stress/auto/recalc-stress-2026-10-04-x.yaml": "recalc: 1\n",
        "Portfolio/stress/auto/notes.txt": "не пересчёт",
        "Portfolio/prices/daily-2026.jsonl": '{"date":"2026-11-02","items":{"SBER":{"close":1}}}\n',
        "Portfolio/prices/notes.txt": "не ряд",
        "macro-snapshots/ru-2026-10-16.md": "m\n",
        "macro-snapshots/auto/ru-2026-10-21.json": "{}",
        "domains/geopolitics/csis.md": "d\n",
    }
    for r, t in files.items():
        (root / r).parent.mkdir(parents=True, exist_ok=True)
        (root / r).write_text(t, encoding="utf-8")
    res = server.pv_sync(tmp, {})
    got = set(res["files"])
    want = {r if "отчёт" not in r else "Portfolio/reports/2026-10-01%20%D0%BE%D1%82%D1%87%D1%91%D1%82%20%D0%BF%D0%BE%20%D0%9E%D0%A4%D0%97.md"
            for r in files if not any(x in r for x in ("notes.txt", "other.yaml", ".versions", "@eaDir", "gate-reviews"))}
    check(f"pv: без have — все файлы вьюера ({len(got)})", got == want and res["schema"] == "pv-sync@1" and not res["more"])
    check("pv: имя с пробелом и кириллицей — как в листинге Caddy (url.PathEscape)",
          "Portfolio/reports/2026-10-01%20%D0%BE%D1%82%D1%87%D1%91%D1%82%20%D0%BF%D0%BE%20%D0%9E%D0%A4%D0%97.md" in got)
    check("pv: служебное (.versions, @eaDir) и чужие имена — мимо",
          not any(".versions" in r or "@eaDir" in r or "notes" in r or "other" in r for r in got))
    check("pv: содержимое как есть", res["files"]["Portfolio/conditions.yaml"] == "c: 1\n")
    check("pv: слой gate-reviews упразднён — /api/pv/sync его не отдаёт",
          not any("gate-reviews" in r for r in got) and "gate-reviews.yaml" not in [n for n, _ in res["dirs"]["Portfolio/"]])
    check("pv: файл пересчёта стресса (Portfolio/stress/auto/) отдаётся, чужое имя в папке — мимо",
          res["files"].get("Portfolio/stress/auto/recalc-stress-2026-10-04-x.yaml") == "recalc: 1\n"
          and not any("stress/auto/notes" in r for r in got))
    check("pv: дневной ряд цен Portfolio/prices/daily-ГГГГ.jsonl отдаётся текстом, чужое имя в папке — мимо",
          res["files"].get("Portfolio/prices/daily-2026.jsonl", "").startswith('{"date":"2026-11-02"')
          and not any("prices/notes" in r for r in got)
          and [n for n, _ in res["dirs"]["Portfolio/prices/"]] == ["daily-2026.jsonl"])
    check("pv: папка Portfolio/ — только conditions",
          sorted(n for n, _ in res["dirs"]["Portfolio/"]) == ["conditions.yaml"])
    have = {f + n: v for f, items in res["dirs"].items() for n, v in items}
    res2 = server.pv_sync(tmp, have)
    check("pv: всё есть у вьюера — содержимого нет, список тот же", res2["files"] == {} and res2["dirs"] == res["dirs"])
    time.sleep(0.01)
    (root / "Portfolio/snapshots/portfolio-2026-10-22.json").write_text("{\"a\": 2}", encoding="utf-8")
    res3 = server.pv_sync(tmp, have)
    check("pv: изменился один файл — пришёл только он", list(res3["files"]) == ["Portfolio/snapshots/portfolio-2026-10-22.json"])
    (root / "Portfolio/snapshots/portfolio-2026-10-08.json").unlink()
    res4 = server.pv_sync(tmp, have)
    check("pv: удалённого нет в списке", "portfolio-2026-10-08.json" not in [n for n, _ in res4["dirs"]["Portfolio/snapshots/"]])
    shutil.rmtree(root / "domains")
    shutil.rmtree(root / "Portfolio/stress")
    check("pv: папки Portfolio/stress/auto/ нет — не ошибка, её нет в dirs",
          "Portfolio/stress/auto/" not in server.pv_sync(tmp, {})["dirs"])
    check("pv: папки нет — её нет в dirs", "domains/geopolitics/" not in server.pv_sync(tmp, have)["dirs"])
    small = server.pv_sync(tmp, {}, max_bytes=1)
    check(f"pv: предел размера — первый файл всегда, остальное more ({len(small['files'])})",
          len(small["files"]) == 1 and small["more"])
    acc, loops = {}, 0
    while True:
        loops += 1
        r = server.pv_sync(tmp, acc, max_bytes=1)
        acc.update({k: v for f, items in r["dirs"].items() for n, v in items for k in [f + n] if k in r["files"]})
        if not r["more"] or loops > 50:
            break
    check(f"pv: повторами с have собирается всё ({loops} запросов)", not r["more"] and len(acc) == len(want) - 3)

    # e2e: зона и тело
    server.ROOT = tmp
    _pv, _ = serve(server.Handler, quiet=False)
    PVB = f"http://127.0.0.1:{_pv.server_address[1]}"

    def pv_post(body, auth=True, raw=None):
        data = raw if raw is not None else json.dumps(body).encode()
        h = {"Content-Type": "application/json", **({"Authorization": "Basic eA=="} if auth else {})}
        rq = urllib.request.Request(PVB + "/api/pv/sync", data=data, method="POST", headers=h)
        try:
            with urllib.request.urlopen(rq) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")
    st, b = pv_post({"have": {}})
    check(f"pv e2e: с Authorization → 200 pv-sync@1 ({st})", st == 200 and b.get("schema") == "pv-sync@1")
    st, _ = pv_post({"have": {}}, auth=False)
    check(f"pv e2e: без Authorization → 403 (вторая линия за Caddy) ({st})", st == 403)
    for label, raw in (("не JSON", b"{"), ("have не словарь", b'{"have": [1]}'), ("версия не строка", b'{"have": {"a": 1}}')):
        st, _ = pv_post(None, raw=raw)
        check(f"pv e2e: {label} → 400 ({st})", st == 400)
    with urllib.request.urlopen(PVB + "/api/health") as r:
        hj = json.loads(r.read())
    check("health: pv_sync, fs_mode, fs_fallbacks, versions_keep",
          hj.get("pv_sync") is True and hj.get("fs_mode") in ("filestation", "local")
          and isinstance(hj.get("fs_fallbacks"), int) and hj.get("versions_keep") == server.VERSIONS_KEEP)
    _pv.shutdown()
finally:
    shutil.rmtree(tmp)

# ── /api/pv/plan — план портфеля (этап 2 numbers-exit-plan.md) ────────────────
print("pv plan")
tmp = tempfile.mkdtemp(prefix="hub-api-plan-")
try:
    root = Path(tmp)
    server.ROOT = tmp
    _pp, _ = serve(server.Handler, quiet=False)
    PPB = f"http://127.0.0.1:{_pp.server_address[1]}"

    def pp(method, url, body=None, auth=True):
        data = json.dumps(body).encode() if body is not None else None
        h = {"Content-Type": "application/json", **({"Authorization": "Basic eA=="} if auth else {})}
        rq = urllib.request.Request(PPB + url, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(rq) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    st, b = pp("GET", "/api/pv/plan")
    check(f"plan: файла нет → GET 404 ({st})", st == 404 and b == {"error": "not found"})
    st, b = pp("POST", "/api/pv/plan/set", {"path": "stocks.YDEX.plan_pct", "value": 1, "reason": None, "base_hash": "x"})
    check(f"plan: файла нет → set 404 ({st})", st == 404)
    st, b = pp("GET", "/api/pv/plan/journal")
    check(f"plan: журнала нет → {{entries: []}} ({st})", st == 200 and b == {"entries": []})

    plan0 = {"schema_version": "plan@1.0", "updated_at": "2026-10-27", "updated_by": "numbers_to_plan.py",
             "classes": [{"class": "Акции", "share": 0.4}],
             "stocks": {"YDEX": {"plan_pct": 5.0, "user_plan": "KEEP", "user_status": None, "note_ie": "заметка",
                                 "note_ai": None, "ie_new_pct": 4.0, "ie_old_pct": 3.0},
                        "SBER": {"plan_pct": 10.0, "user_plan": None, "user_status": None, "note_ie": None,
                                 "note_ai": None, "ie_new_pct": None, "ie_old_pct": None}}}
    (root / "Portfolio").mkdir()
    (root / "Portfolio/plan.json").write_text(server.plan_dump(plan0), encoding="utf-8")
    st, b = pp("GET", "/api/pv/plan")
    h0 = b.get("hash")
    check(f"plan: GET → path, hash, plan ({st})", st == 200 and b["path"] == "Portfolio/plan.json"
          and h0 == server.file_hash((root / "Portfolio/plan.json").read_bytes()) and b["plan"] == plan0)
    st, _ = pp("GET", "/api/pv/plan", auth=False)
    check(f"plan: GET без Authorization → 403 ({st})", st == 403)
    st, _ = pp("POST", "/api/pv/plan/set", {"path": "stocks.YDEX.plan_pct", "value": 1, "base_hash": h0}, auth=False)
    check(f"plan: set без Authorization → 403 ({st})", st == 403)

    st, b = pp("POST", "/api/pv/plan/set", {"path": "stocks.YDEX.plan_pct", "value": 8.5, "reason": "пересмотр IE", "base_hash": h0})
    h1 = b.get("hash")
    disk = json.loads((root / "Portfolio/plan.json").read_text(encoding="utf-8"))
    check(f"plan: set plan_pct → 200, файл изменён, updated_by hub-api ({st})",
          st == 200 and disk["stocks"]["YDEX"]["plan_pct"] == 8.5 and disk["updated_by"] == "hub-api"
          and __import__("re").match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+03:00$", disk["updated_at"]) and disk["updated_at"][:10] == datetime.now(server.MSK).strftime("%Y-%m-%d") and b["plan"] == disk and h1 != h0
          and h1 == server.file_hash((root / "Portfolio/plan.json").read_bytes()))
    check("plan: формат файла — как у numbers_to_plan (indent=2, sort_keys, \\n в конце)",
          (root / "Portfolio/plan.json").read_text(encoding="utf-8") == server.plan_dump(disk))
    jl = [json.loads(x) for x in (root / "Portfolio/plan-journal.jsonl").read_text(encoding="utf-8").splitlines()]
    check("plan: журнал получил строку was/now/reason/who/path/ts",
          len(jl) == 1 and jl[0]["was"] == 5.0 and jl[0]["now"] == 8.5 and jl[0]["reason"] == "пересмотр IE"
          and jl[0]["who"] == "site" and jl[0]["path"] == "stocks.YDEX.plan_pct"
          and __import__("re").match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+03:00$", jl[0]["ts"]) and jl[0]["decision_id"] is None and b["entry"] == jl[0])
    vers = list((root / ".versions/Portfolio").glob("*_plan.json"))
    check(f"plan: .versions/ получил копию прежней версии ({len(vers)})",
          len(vers) == 1 and json.loads(vers[0].read_text(encoding="utf-8")) == plan0)

    st, b = pp("POST", "/api/pv/plan/set", {"path": "stocks.YDEX.plan_pct", "value": 9, "reason": None, "base_hash": h0})
    check(f"plan: чужой base_hash → 409 + current_hash + plan ({st})",
          st == 409 and b["current_hash"] == h1 and b["plan"] == disk)
    check("plan: после 409 файл не тронут", json.loads((root / "Portfolio/plan.json").read_text(encoding="utf-8")) == disk)

    st, b = pp("POST", "/api/pv/plan/set", {"path": "stocks.LKOH.note_ai", "value": "  новая заметка  ", "reason": None, "base_hash": h1})
    h2 = b.get("hash")
    check(f"plan: новый тикер → запись с null-полями, поле выставлено ({st})",
          st == 200 and b["plan"]["stocks"]["LKOH"] == {"plan_pct": None, "user_plan": None, "user_status": None,
                                                         "note_ie": None, "note_ai": "новая заметка",
                                                         "ie_new_pct": None, "ie_old_pct": None}
          and b["entry"]["was"] is None and b["entry"]["reason"] is None)
    st, b = pp("POST", "/api/pv/plan/set", {"path": "stocks.LKOH.note_ai", "value": "   ", "reason": "", "base_hash": h2})
    check(f"plan: пустая строка → null ({st})", st == 200 and b["plan"]["stocks"]["LKOH"]["note_ai"] is None)
    h3 = b["hash"]
    st, b = pp("POST", "/api/pv/plan/set", {"path": "stocks.YDEX.user_plan", "value": "BUY", "reason": None, "base_hash": h3})
    check(f"plan: user_plan BUY → 200 ({st})", st == 200 and b["plan"]["stocks"]["YDEX"]["user_plan"] == "BUY")
    h4 = b["hash"]

    for label, body, want in (
            ("user_plan FOO", {"path": "stocks.YDEX.user_plan", "value": "FOO"}, "bad value"),
            ("plan_pct 150", {"path": "stocks.YDEX.plan_pct", "value": 150}, "bad value"),
            ("plan_pct строкой", {"path": "stocks.YDEX.plan_pct", "value": "5"}, "bad value"),
            ("plan_pct true", {"path": "stocks.YDEX.plan_pct", "value": True}, "bad value"),
            ("заметка > 500", {"path": "stocks.YDEX.note_ie", "value": "я" * 501}, "bad value"),
            ("заметка числом", {"path": "stocks.YDEX.note_ie", "value": 5}, "bad value"),
            ("classes.0.share", {"path": "classes.0.share", "value": 0.5}, "bad path"),
            ("тикер в нижнем регистре", {"path": "stocks.ydex.plan_pct", "value": 5}, "bad path"),
            ("поле ie_new_pct (этап 2 не разрешает)", {"path": "stocks.YDEX.ie_new_pct", "value": 5}, "bad path")):
        st, b = pp("POST", "/api/pv/plan/set", {**body, "reason": None, "base_hash": h4})
        check(f"plan: {label} → 400 {want} ({st})", st == 400 and b.get("error") == want)
    check("plan: отказы файл не меняли",
          server.file_hash((root / "Portfolio/plan.json").read_bytes()) == h4)
    for label, body in (("нет base_hash", {"path": "stocks.YDEX.plan_pct", "value": 1}),
                        ("нет value", {"path": "stocks.YDEX.plan_pct", "base_hash": h4}),
                        ("base_hash не строка", {"path": "stocks.YDEX.plan_pct", "value": 1, "base_hash": 5}),
                        ("массив", [1])):
        st, b = pp("POST", "/api/pv/plan/set", body)
        check(f"plan: {label} → 400 bad request body ({st})", st == 400 and b.get("error") == "bad request body")
    import http.client as _hc
    _c = _hc.HTTPConnection("127.0.0.1", _pp.server_address[1])
    _c.putrequest("POST", "/api/pv/plan/set")      # заявленная длина без тела: сервер отвечает до чтения
    _c.putheader("Authorization", "Basic eA==")
    _c.putheader("Content-Length", str(server.MAX_BYTES + 10))
    _c.endheaders()
    st = _c.getresponse().status
    _c.close()
    check(f"plan: слишком большое тело → 413 ({st})", st == 413)

    st, b = pp("GET", "/api/pv/plan/journal")
    es = b["entries"]
    check(f"plan: журнал — новые первыми ({len(es)})", st == 200 and len(es) == 4
          and es[0]["path"] == "stocks.YDEX.user_plan" and es[-1]["path"] == "stocks.YDEX.plan_pct")
    st, b = pp("GET", "/api/pv/plan/journal?limit=2")
    check("plan: limit=2 — две последние", len(b["entries"]) == 2 and b["entries"][0]["now"] == "BUY")
    st, b = pp("GET", "/api/pv/plan/journal?limit=abc")
    check("plan: limit не число → по умолчанию", st == 200 and len(b["entries"]) == 4)

    # since=: только строки новее (ts строго больше); «+» в query приходит пробелом — сервер возвращает его на место
    _cut = b["entries"][1]["ts"]
    _all = [e["ts"] for e in b["entries"]]
    st, b2 = pp("GET", "/api/pv/plan/journal?since=" + urllib.parse.quote(_cut))
    check(f"plan: since — только строки с ts > since ({st})", st == 200
          and [e["ts"] for e in b2["entries"]] == [t for t in _all if t > _cut])
    st, b2 = pp("GET", "/api/pv/plan/journal?since=" + urllib.parse.quote("2099-01-01T00:00:00+03:00"))
    check("plan: since в будущем → пусто", st == 200 and b2["entries"] == [])
    st, b2 = pp("GET", "/api/pv/plan/journal?since=" + urllib.parse.quote("2000-01-01T00:00:00+03:00") + "&limit=2")
    check("plan: since + limit — limit остаётся", st == 200 and len(b2["entries"]) == 2)

    # фоновая доставка журнала: три append подряд во время «медленного» переноса не теряют строк
    def _wait_delivery():
        t_end = time.time() + 10
        while time.time() < t_end and server._journal_state["running"]:
            time.sleep(0.02)
        return not server._journal_state["running"]

    check("plan: доставка журнала после обычных записей завершена", _wait_delivery())
    _n0 = len((root / "Portfolio/plan-journal.jsonl").read_text(encoding="utf-8").splitlines())
    _placed = []
    _orig_place = server._place

    def _slow_place(r, rel, full, data):
        time.sleep(0.3)                                  # перенос через DSM: перезаписывает файл содержимым «до переноса»
        _placed.append(data.count(b"\n"))
        with open(full, "wb") as f:
            f.write(data)
    server._place = _slow_place
    try:
        _t0 = time.time()
        for i in range(3):
            server.append_plan_journal(tmp, {"ts": server._now_iso(), "who": "site", "path": f"t.{i}", "was": i, "now": i + 1,
                                              "reason": None, "decision_id": None})
            time.sleep(0.05)
        _dt_app = time.time() - _t0
        check(f"plan: append не ждёт перенос (3 записи за {_dt_app:.2f} с при переносе 0,3 с на каждый)", _dt_app < 0.3)
        ok = _wait_delivery()
    finally:
        server._place = _orig_place
    _lines = (root / "Portfolio/plan-journal.jsonl").read_text(encoding="utf-8").splitlines()
    check(f"plan: три append во время переноса — все строки в файле ({len(_lines) - _n0}), доставка догнала ({_placed})",
          ok and len(_lines) == _n0 + 3 and [json.loads(x)["path"] for x in _lines[-3:]] == ["t.0", "t.1", "t.2"]
          and _placed[-1] == _n0 + 3 and len(_placed) <= 3)
    check("plan: все ts журнала — …+03:00, у каждой новой строки decision_id: null",
          all(__import__("re").match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+03:00$", json.loads(x)["ts"]) for x in _lines[-4:])
          and all(json.loads(x)["decision_id"] is None for x in _lines[-3:]))

    (root / "Portfolio/plan.json").write_text("{битый", encoding="utf-8")
    st, b = pp("GET", "/api/pv/plan")
    check(f"plan: битый JSON → 500 plan invalid ({st})", st == 500 and b.get("error") == "plan invalid" and b.get("detail"))

    # журнал не пишется → правка прошла, journal_error
    (root / "Portfolio/plan.json").write_text(server.plan_dump(plan0), encoding="utf-8")
    _orig = server.append_plan_journal
    server.append_plan_journal = lambda *a, **k: (_ for _ in ()).throw(OSError("диск"))
    try:
        st, b = pp("GET", "/api/pv/plan")
        st, b = pp("POST", "/api/pv/plan/set", {"path": "stocks.SBER.plan_pct", "value": 11, "reason": None, "base_hash": b["hash"]})
    finally:
        server.append_plan_journal = _orig
    check(f"plan: журнал не записался → 200 + journal_error ({st})", st == 200 and "диск" in b.get("journal_error", ""))

    # ── пакетная запись ──
    def _plan_state():
        return (root / "Portfolio/plan.json").read_bytes(), (root / "Portfolio/plan-journal.jsonl").read_bytes() \
            if (root / "Portfolio/plan-journal.jsonl").exists() else b""

    def _nver():
        return len(list((root / ".versions/Portfolio").glob("*_plan.json")))

    st, b = pp("GET", "/api/pv/plan")
    hb = b["hash"]
    j0 = len(server.plan_journal(tmp, 500))
    time.sleep(1.1)   # имя копии в .versions/ — с точностью до секунды
    n0 = _nver()
    st, b = pp("POST", "/api/pv/plan/set", {"changes": [
        {"path": "stocks.YDEX.plan_pct", "value": 6},
        {"path": "stocks.SBER.user_status", "value": "ORDER"},
        {"path": "stocks.SBER.note_ie", "value": "пакет"}], "reason": "пакет", "base_hash": hb})
    hb2 = b.get("hash")
    check(f"plan batch: 3 поля → 200, entries=3, entry==entries[0] ({st})",
          st == 200 and len(b["entries"]) == 3 and b["entry"] == b["entries"][0]
          and b["plan"]["stocks"]["YDEX"]["plan_pct"] == 6 and b["plan"]["stocks"]["SBER"]["user_status"] == "ORDER"
          and b["plan"]["stocks"]["SBER"]["note_ie"] == "пакет")
    check(f"plan batch: файл записан один раз (+1 копия в .versions: {n0} → {_nver()})", _nver() == n0 + 1)
    tail = server.plan_journal(tmp, 500)[:3][::-1]
    check("plan batch: три строки журнала в порядке пакета",
          len(server.plan_journal(tmp, 500)) == j0 + 3
          and [e["path"] for e in tail] == ["stocks.YDEX.plan_pct", "stocks.SBER.user_status", "stocks.SBER.note_ie"]
          and all(e["reason"] == "пакет" for e in tail))

    snap = (root / "Portfolio/plan.json").read_bytes()
    jn = len(server.plan_journal(tmp, 500))
    n1 = _nver()
    st, b = pp("POST", "/api/pv/plan/set", {"changes": [
        {"path": "stocks.YDEX.plan_pct", "value": 7},
        {"path": "stocks.YDEX.plan_pct2", "value": 1}], "base_hash": hb2})
    check(f"plan batch: плохой путь → 400 bad path, index 1 ({st})", st == 400 and b.get("error") == "bad path" and b.get("index") == 1)
    st, b = pp("POST", "/api/pv/plan/set", {"changes": [
        {"path": "stocks.YDEX.plan_pct", "value": 7},
        {"path": "stocks.SBER.plan_pct", "value": 500}], "base_hash": hb2})
    check(f"plan batch: плохое значение → 400 bad value, index 1, detail ({st})",
          st == 400 and b.get("error") == "bad value" and b.get("index") == 1 and b.get("detail"))
    check("plan batch: после отказов файл, журнал и .versions не тронуты",
          (root / "Portfolio/plan.json").read_bytes() == snap and len(server.plan_journal(tmp, 500)) == jn and _nver() == n1)
    st, b = pp("POST", "/api/pv/plan/set", {"changes": [
        {"path": "stocks.YDEX.plan_pct", "value": 7}, {"path": "stocks.YDEX.plan_pct", "value": 8}], "base_hash": hb2})
    check(f"plan batch: дубль пути → 400 duplicate path ({st})", st == 400 and b.get("error") == "duplicate path" and b.get("index") == 1)
    st, b = pp("POST", "/api/pv/plan/set", {"changes": [], "base_hash": hb2})
    check(f"plan batch: пустой changes → 400 ({st})", st == 400)
    st, b = pp("POST", "/api/pv/plan/set", {"changes": [
        {"path": f"stocks.T{i}.plan_pct", "value": 1} for i in range(51)], "base_hash": hb2})
    check(f"plan batch: 51 элемент → 400 ({st})", st == 400)
    st, b = pp("POST", "/api/pv/plan/set", {"changes": [{"path": "stocks.YDEX.plan_pct", "value": 1}], "base_hash": "чужой"})
    check(f"plan batch: чужой base_hash → 409 ({st})", st == 409 and b["current_hash"] == hb2)
    check("plan batch: после 409 файл не тронут", (root / "Portfolio/plan.json").read_bytes() == snap)

    st, b = pp("POST", "/api/pv/plan/set", {"path": "stocks.YDEX.plan_pct", "value": 4, "reason": None, "base_hash": hb2})
    check(f"plan batch: старая одиночная форма → 200, entries=1 ({st})",
          st == 200 and len(b["entries"]) == 1 and b["entry"] == b["entries"][0])
    hs = b["hash"]
    for label, val, want in (("ORDER", "ORDER", 200), ("Продал", "Продал", 200), ("null", None, 200),
                             ("121 символ", "я" * 121, 400), ("число", 5, 400)):
        st, b = pp("POST", "/api/pv/plan/set", {"path": "stocks.YDEX.user_status", "value": val, "reason": None, "base_hash": hs})
        check(f"plan: user_status {label} → {want} ({st})", st == want)
        if st == 200:
            hs = b["hash"]

    # ── этап 4: классы, матрица, корзины, облигации, фонды, ручные позиции ──
    print("pv plan этап 4")
    (root / "Portfolio/plan.json").write_text(server.plan_dump(plan0), encoding="utf-8")   # plan0: без matrix/bond_buckets/bonds/funds/manual_positions
    st, b = pp("GET", "/api/pv/plan")
    h = b["hash"]
    jn4 = len(server.plan_journal(tmp, 500))

    def s4(changes, reason="этап 4"):
        global h
        st, b = pp("POST", "/api/pv/plan/set", {"changes": changes, "reason": reason, "base_hash": h})
        if st == 200:
            h = b["hash"]
        return st, b

    st, b = s4([{"path": "classes.Акции.share", "value": 0.45}])
    check(f"plan4: classes существующая строка обновлена ({st})",
          st == 200 and b["plan"]["classes"] == [{"class": "Акции", "share": 0.45}] and b["entry"]["was"] == 0.4
          and b["entry"]["now"] == 0.45 and b["entry"]["path"] == "classes.Акции.share"
          and h == server.file_hash((root / "Portfolio/plan.json").read_bytes()))
    st, b = s4([{"path": "classes.Золото.share", "value": 0.1}, {"path": "classes.Кеш.share", "value": 0},
                {"path": "classes.Другое.share", "value": None}])
    check(f"plan4: classes новые строки созданы {{class, share}}, 0 и null допустимы, сумма ≠ 1 не запрещена ({st})",
          st == 200 and b["plan"]["classes"][1:] == [{"class": "Золото", "share": 0.1}, {"class": "Кеш", "share": 0},
                                                   {"class": "Другое", "share": None}]
          and [e["was"] for e in b["entries"]] == [None, None, None])
    st, b = s4([{"path": "matrix.USD/Золото.share", "value": 0.02}, {"path": "matrix.RUB/Акция.share", "value": 1}])
    check(f"plan4: matrix — раздела не было, строки созданы (currency, class, share) ({st})",
          st == 200 and b["plan"]["matrix"] == [{"currency": "USD", "class": "Золото", "share": 0.02},
                                                {"currency": "RUB", "class": "Акция", "share": 1}])
    st, b = s4([{"path": "matrix.USD/Золото.share", "value": 0.03}])
    check(f"plan4: matrix — существующая строка обновлена, дубля нет ({st})",
          st == 200 and len(b["plan"]["matrix"]) == 2 and b["entry"]["was"] == 0.02 and b["plan"]["matrix"][0]["share"] == 0.03)
    st, b = s4([{"path": "bond_buckets.ОФЗ/>10.share", "value": 0.2}, {"path": "bond_buckets.USD.share", "value": 0.3},
                {"path": "bond_buckets.КОРП/AA+.share", "value": 0.1}])
    check(f"plan4: bond_buckets — type/subtype из ключа, у валютных subtype null ({st})",
          st == 200 and b["plan"]["bond_buckets"] == [
              {"key": "ОФЗ/>10", "type": "ОФЗ", "subtype": ">10", "share": 0.2},
              {"key": "USD", "type": "USD", "subtype": None, "share": 0.3},
              {"key": "КОРП/AA+", "type": "КОРП", "subtype": "AA+", "share": 0.1}])
    for k in ("EUR", "CNY", "ОФЗ/<10", "ОФЗ/Флоат", "КОРП/A", "КОРП/B+"):
        st, b = s4([{"path": f"bond_buckets.{k}.share", "value": 0.05}])
        if st != 200:
            check(f"plan4: корзина {k} принята ({st})", False)
    check("plan4: все девять ключей корзин приняты", len(b["plan"]["bond_buckets"]) == 9)

    isin = "RU000A0JX0J2"
    st, b = s4([{"path": f"bonds.{isin}.type", "value": "ОФЗ"}, {"path": f"bonds.{isin}.subtype", "value": "Флоат"},
                {"path": f"bonds.{isin}.rating", "value": "  ruAAA "}, {"path": f"bonds.{isin}.action", "value": "я" * 200},
                {"path": f"bonds.{isin}.iis_qty", "value": 12}])
    check(f"plan4: bonds — запись создана {{name: null, ...}}, rating обрезан по краям ({st})",
          st == 200 and b["plan"]["bonds"][isin] == {"name": None, "type": "ОФЗ", "subtype": "Флоат", "rating": "ruAAA",
                                                    "action": "я" * 200, "iis_qty": 12})
    st, b = s4([{"path": f"bonds.{isin}.type", "value": None}, {"path": f"bonds.{isin}.iis_qty", "value": 0},
                {"path": f"bonds.{isin}.action", "value": "  "}])
    check(f"plan4: bonds — null, 0 и пустая строка→null ({st})",
          st == 200 and b["plan"]["bonds"][isin]["type"] is None and b["plan"]["bonds"][isin]["iis_qty"] == 0
          and b["plan"]["bonds"][isin]["action"] is None and b["entries"][0]["was"] == "ОФЗ")
    st, b = s4([{"path": "bonds.RU000A0JX0J2.subtype", "value": "AA+"}, {"path": "bonds.XS1234567890.type", "value": "USD"}])
    check(f"plan4: bonds — сочетание type/subtype сервер не проверяет, соседняя запись цела ({st})",
          st == 200 and b["plan"]["bonds"][isin]["subtype"] == "AA+" and b["plan"]["bonds"]["XS1234567890"]["type"] == "USD"
          and b["plan"]["bonds"][isin]["rating"] == "ruAAA")

    st, b = s4([{"path": "funds.TGLD.class", "value": "Золото"}, {"path": "funds.TGLD.currency", "value": "USD"},
                {"path": "funds.TGLD.in_rebalance", "value": True}, {"path": "funds.TLCB.bucket", "value": "USD"},
                {"path": "funds.TLCB.note", "value": " корзина USD "}])
    check(f"plan4: funds — раздел создан, записи с null-полями ({st})",
          st == 200 and b["plan"]["funds"] == {
              "TGLD": {"class": "Золото", "currency": "USD", "in_rebalance": True, "bucket": None, "note": None, "fee_pct": None, "spread_pct": None},
              "TLCB": {"class": None, "currency": None, "in_rebalance": None, "bucket": "USD", "note": "корзина USD", "fee_pct": None, "spread_pct": None}})
    st, b = s4([{"path": "funds.TGLD.fee_pct", "value": 0.79}, {"path": "funds.TGLD.spread_pct", "value": 0}])
    check(f"plan4: funds.fee_pct / spread_pct — число ≥ 0 принимается ({st})",
          st == 200 and b["plan"]["funds"]["TGLD"]["fee_pct"] == 0.79 and b["plan"]["funds"]["TGLD"]["spread_pct"] == 0)
    st, b = s4([{"path": "funds.TGLD.fee_pct", "value": None}])
    check(f"plan4: funds.fee_pct = null — сброс ({st})", st == 200 and b["plan"]["funds"]["TGLD"]["fee_pct"] is None and b["entries"][0]["was"] == 0.79)
    st, b = s4([{"path": "funds.SBGB.bucket", "value": "ОФЗ/>10"}])
    check(f"plan4: funds.SBGB.bucket = «ОФЗ/>10» принимается ({st})",
          st == 200 and b["plan"]["funds"]["SBGB"]["bucket"] == "ОФЗ/>10")
    st, b = s4([{"path": "funds.TGLD.in_rebalance", "value": False}, {"path": "funds.TGLD.bucket", "value": None}])
    check(f"plan4: funds — false и null принимаются ({st})",
          st == 200 and b["plan"]["funds"]["TGLD"]["in_rebalance"] is False and b["entries"][0]["was"] is True)

    st, b = s4([{"path": "manual_positions.Фонд/FINAMAR.value_rub", "value": 123456.5}])
    check(f"plan4: manual_positions — раздела не было, строка создана ({st})",
          st == 200 and [{k: v for k, v in r.items() if k != "value_as_of"} for r in b["plan"]["manual_positions"]]
          == [{"type": "Фонд", "name": "FINAMAR", "value_rub": 123456.5}])
    import datetime as _dt
    _today = _dt.datetime.now(server.MSK).strftime("%Y-%m-%d")
    check(f"plan4: запись суммы ставит value_as_of = сегодня (дата сервера = updated_at), в ответе и на диске ({b['plan']['manual_positions'][0].get('value_as_of')})",
          b["plan"]["manual_positions"][0].get("value_as_of") == _today == b["plan"]["updated_at"][:10]
          and json.loads((root / "Portfolio/plan.json").read_text(encoding="utf-8"))["manual_positions"][0]["value_as_of"] == _today)
    st, b = s4([{"path": "manual_positions.Фонд/FINAMAR.value_rub", "value": 0}, {"path": "manual_positions.Кеш/Наличные.value_rub", "value": None}])
    check(f"plan4: manual_positions — обновление по (type, name), 0 и null ({st})",
          st == 200 and len(b["plan"]["manual_positions"]) == 2 and b["plan"]["manual_positions"][0]["value_rub"] == 0
          and b["entries"][0]["was"] == 123456.5)

    jl4 = server.plan_journal(tmp, 500)
    check("plan4: журнал — строки {ts, who, path, was, now, reason} по каждому изменению",
          len(jl4) > jn4 and set(jl4[0]) == {"ts", "who", "path", "was", "now", "reason", "decision_id"} and jl4[0]["reason"] == "этап 4"
          and jl4[0]["path"] == "manual_positions.Кеш/Наличные.value_rub")
    disk4 = json.loads((root / "Portfolio/plan.json").read_text(encoding="utf-8"))
    check("plan4: stocks и прочие разделы плана не тронуты записью этапа 4",
          disk4["stocks"] == plan0["stocks"] and disk4["schema_version"] == "plan@1.0")

    # отказы: ни файл, ни журнал не меняются
    snap4, jn4 = (root / "Portfolio/plan.json").read_bytes(), len(server.plan_journal(tmp, 500))
    for label, ch, want in (
            ("доля 1.5", {"path": "classes.Акции.share", "value": 1.5}, "bad value"),
            ("доля -0.1", {"path": "matrix.RUB/Кеш.share", "value": -0.1}, "bad value"),
            ("доля процентами строкой", {"path": "bond_buckets.USD.share", "value": "0.5"}, "bad value"),
            ("доля true", {"path": "classes.Акции.share", "value": True}, "bad value"),
            ("класс вне словаря", {"path": "classes.Крипта.share", "value": 0.1}, "bad path"),
            ("в classes — класс матрицы «Акция»", {"path": "classes.Акция.share", "value": 0.1}, "bad path"),
            ("в matrix — «Акции» вместо «Акция»", {"path": "matrix.RUB/Акции.share", "value": 0.1}, "bad path"),
            ("валюта вне словаря", {"path": "matrix.JPY/Кеш.share", "value": 0.1}, "bad path"),
            ("ключ корзины вне девяти", {"path": "bond_buckets.КОРП/C.share", "value": 0.1}, "bad path"),
            ("ISIN из 11 символов", {"path": "bonds.RU000A0JX0J.type", "value": "ОФЗ"}, "bad path"),
            ("ISIN из 13 символов", {"path": "bonds.RU000A0JX0J22.type", "value": "ОФЗ"}, "bad path"),
            ("ISIN в нижнем регистре", {"path": "bonds.ru000a0jx0j2.type", "value": "ОФЗ"}, "bad path"),
            ("type вне словаря", {"path": f"bonds.{isin}.type", "value": "МУНИЦ"}, "bad value"),
            ("subtype вне словаря", {"path": f"bonds.{isin}.subtype", "value": "AAA"}, "bad value"),
            ("rating > 40", {"path": f"bonds.{isin}.rating", "value": "x" * 41}, "bad value"),
            ("action > 200", {"path": f"bonds.{isin}.action", "value": "я" * 201}, "bad value"),
            ("action числом", {"path": f"bonds.{isin}.action", "value": 5}, "bad value"),
            ("iis_qty дробное", {"path": f"bonds.{isin}.iis_qty", "value": 2.5}, "bad value"),
            ("iis_qty отрицательное", {"path": f"bonds.{isin}.iis_qty", "value": -1}, "bad value"),
            ("iis_qty true", {"path": f"bonds.{isin}.iis_qty", "value": True}, "bad value"),
            ("поле bonds.name не разрешено", {"path": f"bonds.{isin}.name", "value": "x"}, "bad path"),
            ("fund class вне словаря", {"path": "funds.TGLD.class", "value": "Крипта"}, "bad value"),
            ("fund class «Акция» (форма матрицы)", {"path": "funds.TGLD.class", "value": "Акция"}, "bad value"),
            ("fund currency вне словаря", {"path": "funds.TGLD.currency", "value": "JPY"}, "bad value"),
            ("fund in_rebalance строкой", {"path": "funds.TGLD.in_rebalance", "value": "true"}, "bad value"),
            ("fund in_rebalance числом", {"path": "funds.TGLD.in_rebalance", "value": 1}, "bad value"),
            ("fund bucket вне девяти ключей", {"path": "funds.TLCB.bucket", "value": "ОФЗ/XX"}, "bad value"),
            ("fund fee_pct отрицательная", {"path": "funds.TGLD.fee_pct", "value": -0.1}, "bad value"),
            ("fund spread_pct строкой", {"path": "funds.TGLD.spread_pct", "value": "0,1"}, "bad value"),
            ("fund note > 500", {"path": "funds.TGLD.note", "value": "я" * 501}, "bad value"),
            ("fund неизвестное поле", {"path": "funds.TGLD.weight", "value": 1}, "bad path"),
            ("fund тикер в нижнем регистре", {"path": "funds.tgld.class", "value": "Кеш"}, "bad path"),
            ("manual value отрицательная", {"path": "manual_positions.Фонд/FINAMAR.value_rub", "value": -1}, "bad value"),
            ("manual value строкой", {"path": "manual_positions.Фонд/FINAMAR.value_rub", "value": "5"}, "bad value"),
            ("manual без имени", {"path": "manual_positions.Фонд.value_rub", "value": 1}, "bad path"),
            ("manual с точкой в имени", {"path": "manual_positions.Фонд/А.Б.value_rub", "value": 1}, "bad path")):
        st, b = pp("POST", "/api/pv/plan/set", {"changes": [{"path": "classes.Кеш.share", "value": 0.2}, ch],
                                                 "reason": None, "base_hash": h})
        check(f"plan4: {label} → 400 {want}, index 1 ({st})", st == 400 and b.get("error") == want and b.get("index") == 1
              and (want == "bad path" or b.get("detail")))
    check("plan4: отказы не тронули файл и журнал",
          (root / "Portfolio/plan.json").read_bytes() == snap4 and len(server.plan_journal(tmp, 500)) == jn4)
    st, b = pp("POST", "/api/pv/plan/set", {"changes": [{"path": "classes.Кеш.share", "value": 0.2},
                                                         {"path": "classes.Кеш.share", "value": 0.3}], "base_hash": h})
    check(f"plan4: дубль пути → 400 duplicate path ({st})", st == 400 and b.get("error") == "duplicate path" and b.get("index") == 1)

    # смесь со старыми путями в одном пакете и порядок журнала
    st, b = s4([{"path": "stocks.SBER.plan_pct", "value": 12}, {"path": "classes.Кеш.share", "value": 0.2},
                {"path": "funds.LQDT.class", "value": "Кеш"}])
    check(f"plan4: пакет stocks + этап 4 — одна запись, порядок журнала сохранён ({st})",
          st == 200 and [e["path"] for e in b["entries"]] == ["stocks.SBER.plan_pct", "classes.Кеш.share", "funds.LQDT.class"]
          and b["plan"]["stocks"]["SBER"]["plan_pct"] == 12 and b["plan"]["funds"]["LQDT"]["class"] == "Кеш")

    # разделы неверного типа → 500 plan invalid, файл не тронут
    bad_plan = dict(plan0, funds=[1], classes={"x": 1}, bonds="x", manual_positions={"a": 1}, matrix=[1], bond_buckets="y")
    (root / "Portfolio/plan.json").write_text(server.plan_dump(bad_plan), encoding="utf-8")
    st, b = pp("GET", "/api/pv/plan")
    hbad, snapbad = b["hash"], (root / "Portfolio/plan.json").read_bytes()
    for path, val in (("funds.TGLD.class", "Кеш"), ("classes.Кеш.share", 0.1), ("bonds.RU000A0JX0J2.type", "ОФЗ"),
                      ("manual_positions.a/b.value_rub", 1), ("matrix.RUB/Кеш.share", 0.1), ("bond_buckets.USD.share", 0.1)):
        st, b = pp("POST", "/api/pv/plan/set", {"changes": [{"path": path, "value": val}], "base_hash": hbad})
        check(f"plan4: раздел неверного типа ({path}) → 500 plan invalid ({st})", st == 500 and b.get("error") == "plan invalid")
    check("plan4: после 500 файл не тронут", (root / "Portfolio/plan.json").read_bytes() == snapbad)

    with urllib.request.urlopen(PPB + "/api/health") as r:
        check("health: pv_plan", json.loads(r.read()).get("pv_plan") is True)
    _pp.shutdown()
finally:
    shutil.rmtree(tmp)

# ── /api/pv/plan/ie-import, ie-set — модель IE (этап 3) ──────────────────────
print("pv ie")
import base64 as _b64  # noqa: E402
import plistlib as _plist  # noqa: E402

_ie_before = passed + failed
_IE_DIR = REPO / "tools/tests/fixtures/ie-pages"
_ie_model_html = (_IE_DIR / "model.html").read_bytes()
_ie_general_html = (_IE_DIR / "general.html").read_bytes()


def _ie_wa(html_bytes):
    """webarchive Safari: бинарный plist с WebMainResource."""
    return _plist.dumps({"WebMainResource": {
        "WebResourceData": html_bytes, "WebResourceURL": "https://invest-era.ru/portfolio-test",
        "WebResourceMIMEType": "text/html", "WebResourceTextEncodingName": "UTF-8", "WebResourceFrameName": ""}},
        fmt=_plist.FMT_BINARY)


def _ie_b64(raw):
    return _b64.b64encode(raw).decode("ascii")


tmp = tempfile.mkdtemp(prefix="hub-api-ie-")
try:
    root = Path(tmp)
    server.ROOT = tmp
    _pi, _ = serve(server.Handler, quiet=False)
    PIB = f"http://127.0.0.1:{_pi.server_address[1]}"

    def pi(method, url, body=None, auth=True):
        data = json.dumps(body).encode() if body is not None else None
        h = {"Content-Type": "application/json", **({"Authorization": "Basic eA=="} if auth else {})}
        rq = urllib.request.Request(PIB + url, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(rq) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def imp(raw, tickers=None, name="страница"):
        return pi("POST", "/api/pv/plan/ie-import", {"name": name, "b64": _ie_b64(raw), "tickers": tickers or []})

    PL = root / "Portfolio/plan.json"

    def disk():
        return json.loads(PL.read_text(encoding="utf-8"))

    def cur_hash():
        return server.file_hash(PL.read_bytes())

    def nver():
        d = root / ".versions/Portfolio"
        return len(list(d.glob("*_plan.json"))) if d.exists() else 0

    def jlen():
        return len(server.plan_journal(tmp, 500))

    def ies(changes, source="site", **kw):
        kw.setdefault("base_hash", cur_hash() if PL.exists() else "x")
        return pi("POST", "/api/pv/plan/ie-set", {"source": source, "changes": changes, **kw})

    st, _ = pi("POST", "/api/pv/plan/ie-import", {"b64": ""}, auth=False)
    check(f"ie: import без Authorization → 403 ({st})", st == 403)
    st, _ = pi("POST", "/api/pv/plan/ie-set", {"base_hash": "x", "source": "site", "changes": []}, auth=False)
    check(f"ie: set без Authorization → 403 ({st})", st == 403)
    st, b = imp(_ie_model_html)
    check(f"ie: плана нет → import 404 ({st})", st == 404)
    st, b = ies([{"ticker": "SBER", "share_pct": 1}], base_hash="x")
    check(f"ie: плана нет → set 404 ({st})", st == 404)

    def _pos(t, share, active=True, **kw):
        return {"ticker": t, "name": t, "target_share_pct": share, "active_in_model": active, **kw}

    def _st(new=None, old=None):
        return {"plan_pct": None, "user_plan": None, "user_status": None, "note_ie": None, "note_ai": None,
                "ie_new_pct": new, "ie_old_pct": old}

    plan1 = {"schema_version": "plan@1.0", "updated_at": "2026-10-01", "updated_by": "numbers_to_plan.py",
             "stocks": {"SBER": _st(5.0, 4.0), "T": _st(6.0), "YDEX": _st(8.0, 7.0), "GLRX": _st(2.0), "CNRU": _st(4.0),
                        "ENPG": _st()},
             "ie_model": {"extraction_date": "2026-10-01", "model_total_pct": 25.0, "positions": [
                 _pos("SBER", 5.0), _pos("T", 6.0),
                 _pos("YDEX", 8.0, growth_potential_12m_pct=20.5, risk_level="Средний"),
                 _pos("GLRX", 2.0), _pos("CNRU", 4.0),
                 _pos("ENPG", None, False, sector="Добывающий", industry="Медь и алюминий", risk_level="Высокий",
                      current_price_rub=335.15, entry_price_rub=360.0, target_price_rub=450.0, target_price_lt_rub=500.0,
                      growth_potential_12m_pct=34.27, growth_potential_lt_pct=49.19, div_yield_2024_pct=None)]}}
    (root / "Portfolio").mkdir()
    PL.write_text(server.plan_dump(plan1), encoding="utf-8")
    h0 = cur_hash()

    # ── ie-import: плохие входы ──
    st, b = pi("POST", "/api/pv/plan/ie-import", {"b64": "###не base64###"})
    check(f"ie: мусор в b64 → 400 ({st})", st == 400 and b.get("error") == "bad page")
    st, b = imp(b"bplist00 not a plist")
    check(f"ie: битый plist → 400 ({st})", st == 400)
    st, b = imp(b"<html><body><p>no tables</p></body></html>")
    check(f"ie: HTML без таблицы → 400 ({st})", st == 400 and b.get("error") == "bad page")
    st, b = imp(b"<table><tr><td>a</td></tr><tr><td>b</td></tr></table>")
    check(f"ie: таблица без колонки «Тикер» → 400 ({st})", st == 400)
    st, b = pi("POST", "/api/pv/plan/ie-import", {"name": "x"})
    check(f"ie: нет b64 → 400 bad request body ({st})", st == 400 and b.get("error") == "bad request body")
    import http.client as _hc2
    _c = _hc2.HTTPConnection("127.0.0.1", _pi.server_address[1])
    _c.putrequest("POST", "/api/pv/plan/ie-import")    # заявленная длина без тела: ответ до чтения
    _c.putheader("Authorization", "Basic eA==")
    _c.putheader("Content-Length", str(server.IE_IMPORT_MAX_BYTES + 10))
    _c.endheaders()
    st = _c.getresponse().status
    _c.close()
    check(f"ie: тело больше IE_IMPORT_MAX_BYTES → 413 ({st})", st == 413)
    big = _ie_model_html + b"<!--" + b"x" * (3 * 1024 * 1024) + b"-->"   # >2 МБ общего лимита, но в пределах 16 МБ
    st, b = imp(_ie_wa(big))
    check(f"ie: webarchive > MAX_BYTES (2 МБ) принимается ({st})", st == 200 and b.get("kind") == "model")

    # ── модельная страница ──
    st, b = imp(_ie_wa(_ie_model_html), tickers=["YDEX"])
    check(f"ie: модельная webarchive → kind=model, rows=6, hash, url ({st})",
          st == 200 and b["kind"] == "model" and b["rows"] == 6 and b["hash"] == h0
          and b["url"] == "https://invest-era.ru/portfolio-test" and b["title"])
    check("ie: cash_pct 7, cash_ticker LQDT, кэш не в positions",
          b["cash_pct"] == 7.0 and b["cash_ticker"] == "LQDT" and [p["ticker"] for p in b["positions"]]
          == ["SBER", "T", "GLRX", "YDEX", "DATA"])
    pg = {p["ticker"]: p for p in b["positions"]}
    check("ie: колонки по заголовкам (доля, цены, потенциалы, риск, дивиденды «за 2026» → div_yield_2024_pct, «-» → null)",
          pg["YDEX"]["target_share_pct"] == 10.0 and pg["YDEX"]["current_price_rub"] == 3469.5
          and pg["YDEX"]["entry_price_rub"] == 4000.0 and pg["YDEX"]["risk_level"] == "Средний"
          and pg["YDEX"]["growth_potential_12m_pct"] == 64.29 and pg["YDEX"]["growth_potential_lt_pct"] == 87.35
          and pg["YDEX"]["div_yield_2024_pct"] == 6.34 and pg["GLRX"]["div_yield_2024_pct"] is None
          and pg["YDEX"]["sector"] == "Коммуникации и развлечения" and "industry" not in pg["YDEX"])
    dm = {d["ticker"]: d for d in b["diff"]}
    check("ie: diff — статусы changed/same/new/removed",
          dm["SBER"]["status"] == "changed" and dm["YDEX"]["status"] == "changed" and dm["T"]["status"] == "same"
          and dm["GLRX"]["status"] == "same" and dm["DATA"]["status"] == "new" and dm["CNRU"]["status"] == "removed"
          and "ENPG" not in dm)
    check("ie: diff — share was/now",
          dm["SBER"]["share"] == {"was": 5.0, "now": 6.0} and dm["YDEX"]["share"] == {"was": 8.0, "now": 10.0}
          and dm["DATA"]["share"] == {"was": None, "now": 3.0} and dm["CNRU"]["share"] == {"was": 4.0, "now": None})
    check("ie: diff — fields только по изменившимся полям",
          dm["YDEX"]["fields"]["growth_potential_12m_pct"] == {"was": 20.5, "now": 64.29}
          and "risk_level" not in dm["YDEX"]["fields"] and dm["SBER"]["fields"].get("current_price_rub") == {"was": None, "now": 295.91}
          and dm["CNRU"]["fields"] == {})
    check("ie: import ничего не пишет", cur_hash() == h0 and nver() == 0 and not (root / "Portfolio/plan-journal.jsonl").exists())
    st, b = imp(_ie_model_html)
    check(f"ie: голый HTML (не plist) принимается ({st})", st == 200 and b["kind"] == "model" and b["url"] is None and b["rows"] == 6)

    # ── общая страница ──
    st, b = imp(_ie_wa(_ie_general_html), tickers=["YDEX", "OZON"])
    check(f"ie: общая webarchive → kind=general, rows=5 ({st})", st == 200 and b["kind"] == "general" and b["rows"] == 5
          and b["cash_pct"] is None)
    dg = {d["ticker"]: d for d in b["diff"]}
    check("ie: general — share null у всех, все 5 строк в diff, ignored всегда [], held только у переданных",
          all(d["share"] is None for d in b["diff"]) and b["ignored"] == [] and len(b["diff"]) == 5
          and set(dg) == {"ENPG", "OZON", "GLRX", "YDEX", "POSI"}
          and {t for t, d in dg.items() if d["held"]} == {"YDEX", "OZON"})
    check("ie: model — held у каждой строки diff",
          all(isinstance(d.get("held"), bool) for d in imp(_ie_model_html, tickers=["YDEX"])[1]["diff"]))
    check("ie: general — new для тикера без позиции, same при совпадении, changed + fields",
          dg["OZON"]["status"] == "new" and dg["ENPG"]["status"] == "same" and dg["GLRX"]["status"] == "changed"
          and dg["YDEX"]["status"] == "changed" and dg["GLRX"]["fields"]["industry"] == {"was": None, "now": "Девелоперы"}
          and dg["YDEX"]["fields"]["target_price_rub"] == {"was": None, "now": 5700.0})
    gpos = {p["ticker"]: p for p in b["positions"]}
    check("ie: general — industry и целевые цены в positions, запятая как разделитель",
          gpos["OZON"]["industry"] == "Электронная коммерция" and gpos["OZON"]["target_price_rub"] == 3200.0
          and gpos["OZON"]["target_price_lt_rub"] == 5200.0 and gpos["POSI"]["div_yield_2024_pct"] == 5.06
          and gpos["OZON"]["growth_potential_12m_pct"] == -9.32 and "target_share_pct" not in gpos["OZON"])

    # ── ie-set: валидация (файл не меняется) ──
    for label, body, want_err in (
            ("плохой тикер", {"changes": [{"ticker": "ydex", "share_pct": 1}]}, "bad ticker"),
            ("тикер не строка", {"changes": [{"ticker": 5, "share_pct": 1}]}, "bad ticker"),
            ("доля 500", {"changes": [{"ticker": "SBER", "share_pct": 500}]}, "bad value"),
            ("доля строкой", {"changes": [{"ticker": "SBER", "share_pct": "5"}]}, "bad value"),
            ("note_ie > 500", {"changes": [{"ticker": "SBER", "note_ie": "я" * 501}]}, "bad value"),
            ("reason числом", {"changes": [{"ticker": "SBER", "share_pct": 1, "reason": 5}]}, "bad value"),
            ("position не объект", {"changes": [{"ticker": "SBER", "position": 5}]}, "bad value"),
            ("position: строка вместо числа", {"changes": [{"ticker": "SBER", "position": {"current_price_rub": "5"}}]}, "bad value"),
            ("position: чужой ключ", {"changes": [{"ticker": "SBER", "position": {"foo": 1}}]}, "bad value"),
            ("дубль тикера", {"changes": [{"ticker": "SBER", "share_pct": 1}, {"ticker": "SBER", "share_pct": 2}]}, "duplicate ticker"),
            ("cash_pct 150", {"changes": [{"ticker": "SBER", "share_pct": 1}], "cash_pct": 150}, "bad value")):
        st, b = pi("POST", "/api/pv/plan/ie-set", {"base_hash": h0, "source": "site", **body})
        check(f"ie: {label} → 400 {want_err} ({st})", st == 400 and b.get("error") == want_err
              and ("index" in b or "cash" in label) and b.get("detail"))
    st, b = pi("POST", "/api/pv/plan/ie-set", {"base_hash": h0, "source": "site",
                                               "changes": [{"ticker": "SBER", "share_pct": 1}, {"ticker": "T", "share_pct": 500}]})
    check(f"ie: ошибка во втором элементе → index 1 ({st})", st == 400 and b.get("index") == 1)
    for label, body in (("пустой пакет", {"changes": []}), ("только тикер без операций", {"changes": [{"ticker": "SBER"}]}),
                        ("плохой source", {"source": "ftp", "changes": [{"ticker": "SBER", "share_pct": 1}]}),
                        ("нет source", {"source": None, "changes": [{"ticker": "SBER", "share_pct": 1}]}),
                        ("плохая extraction_date", {"extraction_date": "27.10.2026", "changes": [{"ticker": "SBER", "share_pct": 1}]}),
                        ("401 изменение", {"changes": [{"ticker": f"T{i}", "share_pct": 1} for i in range(401)]}),
                        ("плохой page", {"page": "other", "changes": [{"ticker": "SBER", "share_pct": 1}]}),
                        ("changes не список", {"changes": {}})):
        st, b = pi("POST", "/api/pv/plan/ie-set", {"base_hash": h0, "source": "site", **body})
        check(f"ie: {label} → 400 ({st})", st == 400)
    st, b = pi("POST", "/api/pv/plan/ie-set", {"source": "site", "changes": [{"ticker": "SBER", "share_pct": 1}]})
    check(f"ie: нет base_hash → 400 ({st})", st == 400)
    check("ie: после отказов файл, журнал и .versions не тронуты",
          cur_hash() == h0 and nver() == 0 and not (root / "Portfolio/plan-journal.jsonl").exists())
    st, b = pi("POST", "/api/pv/plan/set", {"path": "stocks.SBER.ie_new_pct", "value": 5, "reason": None, "base_hash": h0})
    check(f"ie: set с путём stocks.T.ie_new_pct по-прежнему 400 bad path ({st})", st == 400 and b.get("error") == "bad path")
    st, b = pi("POST", "/api/pv/plan/set", {"path": "stocks.SBER.ie_old_pct", "value": 5, "reason": None, "base_hash": h0})
    check(f"ie: set с путём stocks.T.ie_old_pct → 400 bad path ({st})", st == 400 and b.get("error") == "bad path")

    # ── ie-set: изменение доли с сайта ──
    time.sleep(1.1)   # имя копии в .versions/ — с точностью до секунды
    st, b = ies([{"ticker": "YDEX", "share_pct": 12.0, "reason": "пересмотр IE"}])
    d = disk()
    h1 = b.get("hash")
    check(f"ie: смена доли → 200, ie_old/ie_new, hash новый ({st})",
          st == 200 and d["stocks"]["YDEX"]["ie_old_pct"] == 8.0 and d["stocks"]["YDEX"]["ie_new_pct"] == 12.0
          and h1 == cur_hash() != h0 and b["plan"] == d)
    ypos = next(x for x in d["ie_model"]["positions"] if x["ticker"] == "YDEX")
    check("ie: позиция — target_share_pct и active_in_model, прочие поля целы",
          ypos["target_share_pct"] == 12.0 and ypos["active_in_model"] is True and ypos["growth_potential_12m_pct"] == 20.5)
    check("ie: model_total_pct пересчитан (25 − 8 + 12 = 29), updated_by hub-api",
          d["ie_model"]["model_total_pct"] == 29.0 and d["updated_by"] == "hub-api"
          and d["updated_at"][:10] == datetime.now(server.MSK).strftime("%Y-%m-%d"))
    check("ie: extraction_date при source=site не меняется", d["ie_model"]["extraction_date"] == "2026-10-01")
    hist = d["ie_history"]
    check("ie: ie_history — строка date/source/reason/was/now/ts",
          len(hist) == 1 and hist[0]["ticker"] == "YDEX" and hist[0]["was"] == 8.0 and hist[0]["now"] == 12.0
          and hist[0]["source"] == "site" and hist[0]["reason"] == "пересмотр IE"
          and hist[0]["date"] == datetime.now(server.MSK).strftime("%Y-%m-%d")
          and __import__("re").match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+03:00$", hist[0]["ts"]))
    jl = [json.loads(x) for x in (root / "Portfolio/plan-journal.jsonl").read_text(encoding="utf-8").splitlines()]
    check("ie: журнал — одна строка stocks.T.ie_new_pct (без ie_old_pct)",
          len(jl) == 1 and jl[0]["path"] == "stocks.YDEX.ie_new_pct" and jl[0]["was"] == 8.0 and jl[0]["now"] == 12.0
          and jl[0]["reason"] == "пересмотр IE" and jl[0]["who"] == "site" and b["entries"] == jl)
    check(f"ie: копия прежней версии в .versions/ (+1 → {nver()})", nver() == 1)
    check("ie: формат файла — plan_dump", PL.read_text(encoding="utf-8") == server.plan_dump(d))

    n_v, n_j = nver(), jlen()
    st, b = ies([{"ticker": "YDEX", "share_pct": 12.0, "reason": "то же"}])
    check(f"ie: доля не изменилась → 200, entries пусто, файл/журнал/.versions не тронуты ({st})",
          st == 200 and b["entries"] == [] and b["hash"] == h1 and cur_hash() == h1 and nver() == n_v and jlen() == n_j
          and len(disk()["ie_history"]) == 1)
    st, b = ies([{"ticker": "YDEX", "share_pct": 12.003}])
    check("ie: изменение меньше допуска 0.005 — не доля", st == 200 and b["entries"] == [] and cur_hash() == h1)

    # ── причина пуста — разрешено; новая запись stocks для неизвестного тикера ──
    time.sleep(1.1)
    st, b = ies([{"ticker": "DATA", "share_pct": 3.0}])
    d = disk()
    check(f"ie: новая бумага без причины → stocks создан, ie_old null, позиция создана, reason null ({st})",
          st == 200 and d["stocks"]["DATA"]["ie_new_pct"] == 3.0 and d["stocks"]["DATA"]["ie_old_pct"] is None
          and d["stocks"]["DATA"]["plan_pct"] is None and b["entries"][0]["reason"] is None
          and d["ie_history"][-1]["reason"] is None and d["ie_history"][-1]["was"] is None
          and next(x for x in d["ie_model"]["positions"] if x["ticker"] == "DATA")["active_in_model"] is True
          and d["ie_model"]["model_total_pct"] == 32.0)

    # ── удаление из модели ──
    time.sleep(1.1)
    st, b = ies([{"ticker": "CNRU", "share_pct": None, "reason": "убрали"}])
    d = disk()
    check(f"ie: share_pct null у чисто модельной бумаги → позиция удалена, ie_new null, ie_old прежняя ({st})",
          st == 200 and all(x["ticker"] != "CNRU" for x in d["ie_model"]["positions"])
          and d["stocks"]["CNRU"]["ie_new_pct"] is None and d["stocks"]["CNRU"]["ie_old_pct"] == 4.0
          and d["ie_model"]["model_total_pct"] == 28.0
          and d["ie_history"][-1]["now"] is None and d["ie_history"][-1]["was"] == 4.0
          and b["entries"][0]["now"] is None)
    time.sleep(1.1)
    st, b = ies([{"ticker": "ENPG", "share_pct": 3.0, "reason": "в модель"}])
    d = disk()
    epos = next(x for x in d["ie_model"]["positions"] if x["ticker"] == "ENPG")
    check(f"ie: бумага из общего портфеля получила долю → active, target 3 ({st})",
          st == 200 and epos["active_in_model"] is True and epos["target_share_pct"] == 3.0
          and d["ie_model"]["model_total_pct"] == 31.0 and epos["industry"] == "Медь и алюминий")
    time.sleep(1.1)
    st, b = ies([{"ticker": "ENPG", "share_pct": None, "reason": "вышла"}])
    d = disk()
    epos = next((x for x in d["ie_model"]["positions"] if x["ticker"] == "ENPG"), None)
    check(f"ie: убрана бумага из общего портфеля → остаётся, active_in_model false, target null ({st})",
          st == 200 and epos is not None and epos["active_in_model"] is False and epos["target_share_pct"] is None
          and d["stocks"]["ENPG"]["ie_new_pct"] is None and d["stocks"]["ENPG"]["ie_old_pct"] == 3.0
          and d["ie_model"]["model_total_pct"] == 28.0)

    # ── только note_ie ──
    time.sleep(1.1)
    n_j = jlen()
    h_before = cur_hash()
    st, b = ies([{"ticker": "T", "note_ie": "  держим  ", "reason": "заметка"}])
    d = disk()
    check(f"ie: только note_ie → stocks.T.note_ie, журнал одной строкой, ie_history не растёт ({st})",
          st == 200 and d["stocks"]["T"]["note_ie"] == "держим" and len(b["entries"]) == 1
          and b["entries"][0]["path"] == "stocks.T.note_ie" and b["entries"][0]["was"] is None
          and jlen() == n_j + 1 and len(d["ie_history"]) == 5 and d["stocks"]["T"]["ie_new_pct"] == 6.0)
    st, b = ies([{"ticker": "T", "note_ie": "держим"}])
    check("ie: та же заметка — без записей", st == 200 and b["entries"] == [] and jlen() == n_j + 1)
    st, b = ies([{"ticker": "T", "note_ie": ""}])
    check("ie: пустая заметка → null", st == 200 and disk()["stocks"]["T"]["note_ie"] is None)

    # ── только position ──
    time.sleep(1.1)
    n_j = jlen()
    st, b = ies([{"ticker": "GLRX", "reason": "обновление цен", "position": {
        "current_price_rub": 39.92, "growth_potential_12m_pct": 87.88, "sector": "Потребительский цикличный"}}],
        source="webarchive")
    d = disk()
    check(f"ie: только position → одна строка ie_model.positions.T с was/now по изменившимся полям ({st})",
          st == 200 and len(b["entries"]) == 1 and b["entries"][0]["path"] == "ie_model.positions.GLRX"
          and b["entries"][0]["was"] == {"current_price_rub": None, "growth_potential_12m_pct": None, "sector": None}
          and b["entries"][0]["now"] == {"current_price_rub": 39.92, "growth_potential_12m_pct": 87.88,
                                         "sector": "Потребительский цикличный"}
          and b["entries"][0]["reason"] == "обновление цен" and jlen() == n_j + 1)
    st, b = ies([{"ticker": "GLRX", "position": {"current_price_rub": 40.5, "growth_potential_12m_pct": 87.88}}])
    check("ie: второй импорт — в журнале только изменившееся поле",
          st == 200 and b["entries"][0]["was"] == {"current_price_rub": 39.92} and b["entries"][0]["now"] == {"current_price_rub": 40.5})
    n_j, h_before = jlen(), cur_hash()
    st, b = ies([{"ticker": "GLRX", "position": {"current_price_rub": 40.5}}])
    check("ie: position без изменений — без строки журнала и без записи файла",
          st == 200 and b["entries"] == [] and jlen() == n_j and cur_hash() == h_before)
    time.sleep(1.1)
    st, b = ies([{"ticker": "NEWT", "position": {"name": "Новая", "industry": "Прочее", "target_price_rub": 10,
                                                  "growth_potential_12m_pct": 5.5}}])
    d = disk()
    npos = next((x for x in d["ie_model"]["positions"] if x["ticker"] == "NEWT"), None)
    check(f"ie: position новой бумаги → upsert, active_in_model false без доли ({st})",
          st == 200 and npos is not None and npos["active_in_model"] is False and npos["target_share_pct"] is None
          and npos["industry"] == "Прочее" and d["ie_model"]["model_total_pct"] == 28.0
          and "NEWT" not in d["stocks"])
    time.sleep(1.1)
    st, b = ies([{"ticker": "SBER", "share_pct": 6.0, "reason": "импорт", "position": {
        "target_share_pct": 6.0, "current_price_rub": 295.91}}], source="webarchive")
    d = disk()
    check(f"ie: position+share_pct в одном изменении — доля одной строкой журнала, без дубля target_share_pct ({st})",
          st == 200 and [e["path"] for e in b["entries"]] == ["ie_model.positions.SBER", "stocks.SBER.ie_new_pct"]
          and b["entries"][0]["now"] == {"current_price_rub": 295.91} and d["stocks"]["SBER"]["ie_old_pct"] == 5.0
          and d["ie_history"][-1]["source"] == "webarchive")

    # ── кэш и extraction_date ──
    time.sleep(1.1)
    n_j = jlen()
    st, b = ies([], cash_pct=7.0)
    d = disk()
    check(f"ie: cash_pct → ie_model.cash_pct 7, cash_ticker LQDT, журнал ie_model.cash_pct ({st})",
          st == 200 and d["ie_model"]["cash_pct"] == 7.0 and d["ie_model"]["cash_ticker"] == "LQDT"
          and [e["path"] for e in b["entries"]] == ["ie_model.cash_pct"] and b["entries"][0]["was"] is None
          and jlen() == n_j + 1)
    st, b = ies([], cash_pct=7.0)
    check("ie: тот же кэш — без записей", st == 200 and b["entries"] == [])
    time.sleep(1.1)
    st, b = ies([{"ticker": "T", "position": {}}], source="webarchive", extraction_date="2026-10-20")
    check(f"ie: явная extraction_date принимается ({st})", st == 200 and disk()["ie_model"]["extraction_date"] == "2026-10-20")
    time.sleep(1.1)
    st, b = ies([{"ticker": "T", "position": {}}], source="webarchive", extraction_date=None)
    check(f"ie: webarchive без даты → сегодня (локально) ({st})",
          st == 200 and disk()["ie_model"]["extraction_date"] == datetime.now().strftime("%Y-%m-%d"))
    st, b = ies([{"ticker": "T", "note_ie": "ещё"}], source="site")
    check("ie: source=site дату модели не меняет", st == 200 and disk()["ie_model"]["extraction_date"] == datetime.now().strftime("%Y-%m-%d"))
    time.sleep(1.1)
    st, b = ies([{"ticker": "T", "note_ie": "дата"}], source="site", extraction_date="2026-09-09")
    check("ie: source=site с явной датой — ставится", st == 200 and disk()["ie_model"]["extraction_date"] == "2026-09-09")

    # ── ie-set: page=general → general_date, extraction_date модели не трогается ──
    time.sleep(1.1)
    ext_before = disk()["ie_model"]["extraction_date"]
    st, b = ies([{"ticker": "T", "position": {}}], source="webarchive", page="general")
    d = disk()["ie_model"]
    check(f"ie: webarchive+page=general → general_date сегодня, extraction_date не тронута ({st})",
          st == 200 and d.get("general_date") == datetime.now().strftime("%Y-%m-%d") and d["extraction_date"] == ext_before)
    time.sleep(1.1)
    st, b = ies([{"ticker": "T", "note_ie": "ген"}], source="webarchive", page="general", extraction_date="2026-10-02")
    d = disk()["ie_model"]
    check("ie: page=general с явной датой → general_date, extraction_date прежняя",
          st == 200 and d["general_date"] == "2026-10-02" and d["extraction_date"] == ext_before)
    time.sleep(1.1)
    st, b = ies([{"ticker": "T", "note_ie": "мод"}], source="webarchive", page="model", extraction_date="2026-10-03")
    d = disk()["ie_model"]
    check("ie: page=model ставит extraction_date, general_date прежняя",
          st == 200 and d["extraction_date"] == "2026-10-03" and d["general_date"] == "2026-10-02")
    time.sleep(1.1)
    st, b = ies([{"ticker": f"B{i}", "position": {"current_price_rub": float(i + 1)}} for i in range(300)],
                source="webarchive", page="general")
    check(f"ie: пакет из 300 изменений принимается ({st})",
          st == 200 and len(disk()["ie_model"]["positions"]) >= 300)

    # ── конфликт ──
    snap = PL.read_bytes()
    st, b = pi("POST", "/api/pv/plan/ie-set", {"base_hash": h0, "source": "site", "changes": [{"ticker": "T", "share_pct": 9}]})
    check(f"ie: чужой base_hash → 409 + current_hash + свежий plan ({st})",
          st == 409 and b["current_hash"] == cur_hash() and b["plan"] == disk() and PL.read_bytes() == snap)

    # ── журнал не пишется → правка прошла, journal_error ──
    _orig = server.append_plan_journal
    server.append_plan_journal = lambda *a, **k: (_ for _ in ()).throw(OSError("диск"))
    try:
        time.sleep(1.1)
        st, b = ies([{"ticker": "T", "share_pct": 7.0}])
    finally:
        server.append_plan_journal = _orig
    check(f"ie: журнал не записался → 200 + journal_error ({st})", st == 200 and "диск" in b.get("journal_error", "")
          and disk()["stocks"]["T"]["ie_new_pct"] == 7.0)

    # ── вызов напрямую: now задаёт ts и дату ──
    st, b = server.plan_ie_set(tmp, {"base_hash": cur_hash(), "source": "site",
                                     "changes": [{"ticker": "T", "share_pct": 8.0}]},
                               now=datetime(2026, 10, 27, 12, 0, 0, tzinfo=server.timezone.utc))
    check("ie: plan_ie_set(now=…) → ts из now", st == 200 and b["entries"][0]["ts"] == "2026-10-27T15:00:00+03:00"
          and disk()["ie_history"][-1]["ts"] == "2026-10-27T15:00:00+03:00")

    with urllib.request.urlopen(PIB + "/api/health") as r:
        hj = json.loads(r.read())
    check("health: pv_ie и pv_plan", hj.get("pv_ie") is True and hj.get("pv_plan") is True)

    # ── живые файлы IE (необязательно): IE_WEBARCHIVE_DIR=…/modelny.webarchive, obshchiy.webarchive ──
    _live = os.environ.get("IE_WEBARCHIVE_DIR")
    _lm, _lg = (Path(_live) / "modelny.webarchive", Path(_live) / "obshchiy.webarchive") if _live else (None, None)
    if _lm and _lm.exists() and _lg.exists():
        st, b = imp(_lm.read_bytes(), tickers=["SBER"])
        check(f"ie live: модельный webarchive → model, 16 позиций, кэш 7 ({st}, {len(b.get('positions', []))})",
              st == 200 and b["kind"] == "model" and len(b["positions"]) == 16 and b["cash_pct"] == 7.0)
        st, b = imp(_lg.read_bytes(), tickers=["GLRX", "YDEX"])
        check(f"ie live: общий webarchive → general, 158 строк все в diff, ignored [], held только из tickers "
              f"({st}, {b.get('rows')}, diff {len(b.get('diff', []))})",
              st == 200 and b["kind"] == "general" and b["rows"] == 158 and b["cash_pct"] is None
              and len(b["diff"]) == 158 and b["ignored"] == []
              and {d["ticker"] for d in b["diff"] if d["held"]} <= {"GLRX", "YDEX"}
              and all(d["share"] is None for d in b["diff"]))
    else:
        print("  skip: живые webarchive IE (IE_WEBARCHIVE_DIR не задан или файлов нет)")
    _pi.shutdown()
finally:
    shutil.rmtree(tmp)
print(f"  pv ie: проверок {passed + failed - _ie_before}")

# ── /api/pv/plan/export, import — файл плана целиком (этап 5 numbers-exit-plan.md) ──
print("pv export/import")
import io as _io  # noqa: E402
import zipfile as _zip  # noqa: E402
import xml.etree.ElementTree as _ET  # noqa: E402

_xi_before = passed + failed
tmp = tempfile.mkdtemp(prefix="hub-api-ximp-")
try:
    root = Path(tmp)
    server.ROOT = tmp
    _px, _ = serve(server.Handler, quiet=False)
    PXB = f"http://127.0.0.1:{_px.server_address[1]}"

    def px(method, url, body=None, auth=True, raw=False):
        data = json.dumps(body).encode() if body is not None else None
        h = {"Content-Type": "application/json", **({"Authorization": "Basic eA=="} if auth else {})}
        rq = urllib.request.Request(PXB + url, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(rq) as r:
                return (r.status, r.read(), r.headers) if raw else (r.status, json.loads(r.read()))
        except urllib.error.HTTPError as e:
            return (e.code, e.read(), e.headers) if raw else (e.code, json.loads(e.read() or b"{}"))

    PLX = root / "Portfolio/plan.json"
    st, _b = px("GET", "/api/pv/plan/export?format=json")
    check(f"export: файла нет → 404 ({st})", st == 404)
    st, _b = px("POST", "/api/pv/plan/import", {"base_hash": "x", "plan": {"schema_version": "plan@1.0"}})
    check(f"import: файла нет → 404 ({st})", st == 404)

    planx = {"schema_version": "plan@1.0", "generated_at": "2026-10-20", "updated_at": "2026-10-26",
             "updated_by": "numbers_to_plan.py", "source": {"file": None, "extraction_date": "2026-10-20"},
             "stocks": {"SBER": {"plan_pct": 10.0, "user_plan": "KEEP", "user_status": "DONE", "note_ie": "заметка & <IE>",
                                 "note_ai": "моя", "ie_new_pct": 6.0, "ie_old_pct": 5.0},
                        "YDEX": {"plan_pct": 5.0, "user_plan": None, "user_status": None, "note_ie": None,
                                 "note_ai": None, "ie_new_pct": None, "ie_old_pct": None}},
             "classes": [{"class": "Акции", "share": 0.4}, {"class": "Кеш", "share": 0.1}],
             "matrix": [{"currency": "RUB", "class": "Акция", "share": 0.4}],
             "bond_buckets": [{"key": "ОФЗ/>10", "type": "ОФЗ", "subtype": ">10", "share": 0.2}],
             "bonds": {"RU000A0JS3W6": {"name": "ОФЗ 26207", "type": "ОФЗ", "subtype": "<10", "rating": None,
                                         "action": None, "iis_qty": 5.0}},
             "funds": {"SBGB": {"class": "Облигация", "currency": "RUB", "in_rebalance": False, "bucket": "ОФЗ/<10", "note": None, "fee_pct": 0.79, "spread_pct": 0.1}},
             "manual_positions": [{"type": "RUB - Другое", "name": "Ренат ПРО", "value_rub": 270000.0, "value_as_of": "2026-10-20"}],
             "ie_model": {"extraction_date": "2026-10-20", "general_date": "2026-10-20", "cash_pct": 7.0, "cash_ticker": "LQDT",
                          "model_total_pct": 6.0,
                          "positions": [{"ticker": "SBER", "name": "Сбербанк", "active_in_model": True, "target_share_pct": 6.0,
                                         "current_price_rub": 295.83, "target_price_rub": 345, "target_price_lt_rub": 430,
                                         "growth_potential_12m_pct": 16.62, "growth_potential_lt_pct": 45.35,
                                         "div_yield_2024_pct": 15.21, "risk_level": "Низкий", "sector": "Финансовый",
                                         "industry": "Банки", "entry_price_rub": 285}]},
             "ie_history": [{"ts": "2026-10-20T10:00:00Z", "date": "2026-10-20", "ticker": "SBER", "was": 5.0, "now": 6.0,
                             "reason": None, "source": "site"}]}
    (root / "Portfolio").mkdir()
    PLX.write_text(server.plan_dump(planx), encoding="utf-8")

    def xhash():
        return server.file_hash(PLX.read_bytes())

    def xj():
        return len(server.plan_journal(tmp, 500))

    # ── экспорт ──
    st, _b, _h = px("GET", "/api/pv/plan/export?format=json", auth=False, raw=True)
    check(f"export: без Authorization → 403 ({st})", st == 403)
    st, body, hd = px("GET", "/api/pv/plan/export?format=json", raw=True)
    st2, gb = px("GET", "/api/pv/plan")
    check(f"export json: байты файла как есть, X-Plan-Hash = hash из GET plan, вложение ({st})",
          st == 200 and body == PLX.read_bytes() and hd["X-Plan-Hash"] == gb["hash"]
          and hd["Content-Type"].startswith("application/json")
          and hd["Content-Disposition"] == 'attachment; filename="site-db-2026-10-26.json"')
    st, _b = px("GET", "/api/pv/plan/export?format=csv")
    check(f"export: неизвестный format → 400 ({st})", st == 400)
    st, body, hd = px("GET", "/api/pv/plan/export?format=xlsx", raw=True)
    check(f"export xlsx: mime и имя файла ({st})", st == 200 and hd["Content-Type"] == server.PLAN_XLSX_MIME
          and hd["Content-Disposition"] == 'attachment; filename="site-db-2026-10-26.xlsx"' and hd["X-Plan-Hash"] == gb["hash"])
    zf = _zip.ZipFile(_io.BytesIO(body))
    check("export xlsx: части пакета на месте", {"[Content_Types].xml", "_rels/.rels", "xl/workbook.xml",
                                                  "xl/_rels/workbook.xml.rels"} <= set(zf.namelist()) and zf.testzip() is None)
    _ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    wb = _ET.fromstring(zf.read("xl/workbook.xml"))
    names = [s.get("name") for s in wb.find("m:sheets", _ns)]
    check(f"export xlsx: девять листов {names}", names == ["Акции", "Классы", "Матрица", "Корзины", "Облигации", "Фонды",
                                                            "Ручные позиции", "Модель IE", "История IE"]
          and all(len(n) <= 31 for n in names))

    def sheet(i):
        out = []
        for row in _ET.fromstring(zf.read(f"xl/worksheets/sheet{i}.xml")).iter("{%s}row" % _ns["m"]):
            cells = {}
            for c in row:
                v = c.find("m:v", _ns)
                t = c.find("m:is/m:t", _ns)
                cells[c.get("r").rstrip("0123456789")] = (c.get("t"), float(v.text) if v is not None else t.text)
            out.append(cells)
        return out

    s1 = sheet(1)
    check("export xlsx: «Акции» — заголовки русские, тикер SBER, число — t=n, слова плана и статуса",
          s1[0]["A"] == ("inlineStr", "Тикер") and s1[1]["A"] == ("inlineStr", "SBER") and s1[1]["B"] == ("n", 10.0)
          and s1[1]["C"] == ("inlineStr", "держать") and s1[1]["D"] == ("inlineStr", "сделал")
          and s1[1]["G"] == ("inlineStr", "заметка & <IE>") and s1[2]["A"] == ("inlineStr", "YDEX") and "C" not in s1[2])
    check("export xlsx: «Классы» — доли в процентах", sheet(2)[1] == {"A": ("inlineStr", "Акции"), "B": ("n", 40.0)})
    check("export xlsx: «Облигации» — ISIN, количество на ИИС числом", sheet(5)[1]["A"] == ("inlineStr", "RU000A0JS3W6")
          and sheet(5)[1]["G"] == ("n", 5.0))
    s8 = sheet(8)
    check("export xlsx: «Модель IE» — шапка (даты, кэш) и позиции", s8[0]["B"] == ("inlineStr", "2026-10-20")
          and s8[2]["B"] == ("n", 7.0) and s8[4]["A"] == ("inlineStr", "SBER") and s8[4]["B"] == ("inlineStr", "Сбербанк")
          and s8[4]["D"] == ("n", 6.0) and len(s8) == 5)
    sf = sheet(6)
    check("export xlsx: «Фонды» — «Комиссия, % в год» и «Спред, %» после «В балансировке»",
          sf[0]["F"] == ("inlineStr", "Комиссия, % в год") and sf[0]["G"] == ("inlineStr", "Спред, %") and sf[0]["H"] == ("inlineStr", "Заметка")
          and sf[1]["F"] == ("n", 0.79) and sf[1]["G"] == ("n", 0.1))
    s9 = sheet(9)
    check("export xlsx: «История IE» — запись построчно", len(s9) == 2 and ("inlineStr", "SBER") in s9[1].values())

    # таблицы Excel: dimension по реальным размерам, закреплённая шапка, ListObject, openpyxl открывает
    import openpyxl
    wbk = openpyxl.load_workbook(_io.BytesIO(body))
    check("export xlsx: openpyxl открывает книгу, девять листов", len(wbk.sheetnames) == 9)
    check("export xlsx: таблицы на всех листах с данными, ref и закрепление",
          {ws.title: (list(ws.tables.values())[0].ref, ws.freeze_panes) for ws in wbk.worksheets if ws.tables}
          == {"Акции": ("A1:H3", "A2"), "Классы": ("A1:B3", "A2"), "Матрица": ("A1:C2", "A2"),
              "Корзины": ("A1:D2", "A2"), "Облигации": ("A1:G2", "A2"), "Фонды": ("A1:H2", "A2"),
              "Ручные позиции": ("A1:D2", "A2"), "Модель IE": ("A5:M6", "A6"), "История IE": ("A1:G2", "A2")})
    for ws in wbk.worksheets:
        tb = list(ws.tables.values())
        check(f"export xlsx: «{ws.title}» — размеры {ws.max_row}x{ws.max_column}, одна таблица, фильтр, закрепление под шапкой",
              len(tb) == 1 and tb[0].autoFilter is not None and ws.freeze_panes == f"A{int(tb[0].ref.split(':')[0][1:]) + 1}"
              and tb[0].ref.endswith(str(ws.max_row)) and ws.dimensions == f"A1:{openpyxl.utils.get_column_letter(ws.max_column)}{ws.max_row}")
    check("export xlsx: «Ручные позиции» — колонка «Оценка на дату» после «Стоимость, ₽», значение из плана",
          [c.value for c in wbk["Ручные позиции"][1]] == ["Тип", "Название", "Стоимость, ₽", "Оценка на дату"]
          and [c.value for c in wbk["Ручные позиции"][2]][3] == "2026-10-20")
    check("export xlsx: «Модель IE» — таблица от шапки «Тикер», мета-строки над ней",
          list(wbk["Модель IE"].tables.values())[0].ref.startswith("A5:") and wbk["Модель IE"]["A5"].value == "Тикер"
          and wbk["Модель IE"]["A3"].value == "Кэш, %")
    check("export xlsx: displayName уникальны и латиницей",
          len({t.displayName for ws in wbk.worksheets for t in ws.tables.values()}) == 9
          and all(t.displayName.isascii() and " " not in t.displayName for ws in wbk.worksheets for t in ws.tables.values()))
    # без кеша и истории: строки «Кэш, %» нет, листов восемь; пустые разделы — лист без таблицы
    _p2 = dict(planx)
    _p2["ie_model"] = {k: v for k, v in planx["ie_model"].items() if k != "cash_pct"}
    _p2["ie_history"] = []
    _p2["classes"] = []
    wb2 = openpyxl.load_workbook(_io.BytesIO(server.plan_xlsx(_p2)))
    check("export xlsx: без cash_pct и истории — нет «Кэш, %», листов восемь, пустой раздел без таблицы",
          len(wb2.sheetnames) == 8 and "История IE" not in wb2.sheetnames
          and all(r[0].value != "Кэш, %" for r in wb2["Модель IE"].iter_rows())
          and wb2["Модель IE"]["A3"].value is None and wb2["Модель IE"]["A4"].value == "Тикер"
          and not wb2["Классы"].tables and wb2["Модель IE"].freeze_panes == "A5")

    # ── импорт: проверка ──
    h0 = xhash()
    j0 = xj()

    def imp(plan, **kw):
        kw.setdefault("base_hash", xhash())
        return px("POST", "/api/pv/plan/import", {"plan": plan, **kw})

    st, _b = px("POST", "/api/pv/plan/import", {"base_hash": h0, "plan": planx}, auth=False)
    check(f"import: без Authorization → 403 ({st})", st == 403)
    for label, body in (("нет plan", {"base_hash": h0}), ("plan — массив", {"base_hash": h0, "plan": []}),
                        ("нет base_hash", {"plan": planx}), ("reason > 300", {"base_hash": h0, "plan": planx, "reason": "я" * 301}),
                        ("dry_run строкой", {"base_hash": h0, "plan": planx, "dry_run": "yes"})):
        st, _b = px("POST", "/api/pv/plan/import", body)
        check(f"import: {label} → 400 ({st})", st == 400)
    st, b = imp({**planx, "schema_version": "plan@2.0"})
    check(f"import: чужой schema_version → 400 bad plan ({st})", st == 400 and b["error"] == "bad plan"
          and b["problems"][0]["path"] == "schema_version")
    bad = json.loads(json.dumps(planx))
    bad["stocks"]["SBER"]["plan_pct"] = 150
    bad["classes"][0]["share"] = 1.5
    bad["stocks"]["YDEX"]["zzz"] = 1
    bad["лишний"] = 1
    bad["bonds"]["RU000A0JS3W6"]["type"] = "НЕТ"
    bad["ie_model"]["positions"][0]["target_share_pct"] = "6"
    st, b = imp(bad)
    paths = {p["path"] for p in b.get("problems", [])}
    check(f"import: plan_pct 150, share 1.5, чужие поля и типы → 400 с путями ({st}, {sorted(paths)})",
          st == 400 and {"stocks.SBER.plan_pct", "classes.Акции.share", "stocks.YDEX.zzz", "лишний",
                         "bonds.RU000A0JS3W6.type", "ie_model.positions.SBER.target_share_pct"} <= paths)
    many = json.loads(json.dumps(planx))
    many["stocks"] = {f"T{i}": {"plan_pct": 999} for i in range(80)}
    st, b = imp(many)
    check(f"import: проблем не больше 50 ({st}, {len(b.get('problems', []))})", st == 400 and len(b["problems"]) == 50)
    dup = json.loads(json.dumps(planx))
    dup["classes"].append({"class": "Акции", "share": 0.1})
    st, b = imp(dup)
    check(f"import: дубль строки списка → 400 ({st})", st == 400 and any(p["detail"] == "дубль строки" for p in b["problems"]))
    check("import: отказы ничего не записали", xhash() == h0 and xj() == j0)

    bad_asof = json.loads(json.dumps(planx)); bad_asof["manual_positions"][0]["value_as_of"] = "20.10.2026"
    st, b = imp(bad_asof, dry_run=True)
    check(f"import: value_as_of «20.10.2026» → 400 с путём поля ({st})",
          st == 400 and any(p.get("path") == "manual_positions.RUB - Другое/Ренат ПРО.value_as_of" for p in b["problems"]))
    ok_asof = json.loads(json.dumps(planx)); ok_asof["manual_positions"][0]["value_as_of"] = "2026-10-21"
    st, b = imp(ok_asof, dry_run=True)
    check(f"import dry_run: value_as_of «2026-10-21» принят, в diff как обычное поле ({st})",
          st == 200 and [d for d in b["diff"]] == [{"path": "manual_positions.RUB - Другое/Ренат ПРО.value_as_of", "old": "2026-10-20", "new": "2026-10-21"}])
    nul_asof = json.loads(json.dumps(planx)); nul_asof["manual_positions"][0]["value_as_of"] = None
    st, b = imp(nul_asof, dry_run=True)
    check(f"import dry_run: value_as_of null принят ({st})", st == 200)

    # ── dry_run ──
    ch = json.loads(json.dumps(planx))
    ch["stocks"]["SBER"]["plan_pct"] = 12.5
    ch["funds"]["NEWF"] = {"class": "Акции", "currency": "USD", "in_rebalance": True, "bucket": None, "note": "новый"}
    ch["updated_by"] = "кто-то"                      # метаданные в diff не входят
    st, b = imp(ch, dry_run=True)
    dp = {d["path"]: d for d in b.get("diff", [])}
    check(f"import dry_run: diff ровно изменённые и новые пути ({st}, {sorted(dp)})",
          st == 200 and set(dp) == {"stocks.SBER.plan_pct", "funds.NEWF.class", "funds.NEWF.currency",
                                    "funds.NEWF.in_rebalance", "funds.NEWF.note"}
          and dp["stocks.SBER.plan_pct"] == {"path": "stocks.SBER.plan_pct", "old": 10.0, "new": 12.5})
    check("import dry_run: counts (1 изменено, 4 добавлено, по разделам), hash текущий, без unchanged",
          b["counts"]["changed"] == 1 and b["counts"]["added"] == 4 and b["counts"]["removed"] == 0
          and b["counts"]["by_section"] == {"stocks": 1, "funds": 4} and b["hash"] == h0 and "unchanged" not in b)
    check("import dry_run: файл и журнал не тронуты", xhash() == h0 and xj() == j0)
    ch2 = json.loads(json.dumps(planx)); ch2["funds"]["SBGB"]["fee_pct"] = 1.2
    st, b = imp(ch2, dry_run=True)
    check(f"import dry_run: fee_pct — известное поле, в diff funds.SBGB.fee_pct 0.79 → 1.2 ({st})",
          st == 200 and [d for d in b["diff"] if d["path"] == "funds.SBGB.fee_pct"] == [{"path": "funds.SBGB.fee_pct", "old": 0.79, "new": 1.2}])
    ch2["funds"]["SBGB"]["spread_pct"] = -1
    st, b = imp(ch2, dry_run=True)
    check(f"import: spread_pct < 0 → 400 ({st})", st == 400 and any("funds.SBGB.spread_pct" in p.get("path", "") for p in b["problems"]))
    st, b = imp(ch, dry_run=True, base_hash="чужой")
    check(f"import dry_run: чужой base_hash → 409 + current_hash ({st})", st == 409 and b["current_hash"] == h0)
    rm = json.loads(json.dumps(planx))
    del rm["funds"]["SBGB"]
    rm["classes"][1]["share"] = 0.15
    st, b = imp(rm, dry_run=True)
    check(f"import dry_run: удалённая запись — removed, изменённая доля — changed ({st}, {b.get('counts')})",
          st == 200 and b["counts"]["removed"] == 6 and b["counts"]["changed"] == 1)
    near = json.loads(json.dumps(planx))
    near["stocks"]["SBER"]["plan_pct"] = 10.0 + 1e-12
    st, b = imp(near, dry_run=True)
    check(f"import dry_run: числа с допуском 1e-9 равны ({st})", st == 200 and b["diff"] == [])

    # ── запись ──
    st, b = imp(ch, reason="правка из файла", name="plan-ch.json")
    d = json.loads(PLX.read_text(encoding="utf-8"))
    check(f"import: запись — hash сменился, файл содержит новое, updated_by hub-api, source сохранён ({st})",
          st == 200 and b["hash"] != h0 and b["hash"] == xhash() and d["stocks"]["SBER"]["plan_pct"] == 12.5
          and d["funds"]["NEWF"]["note"] == "новый" and d["updated_by"] == "hub-api"
          and d["updated_at"] != "2026-10-26" and d["source"] == planx["source"] and b["plan"] == d
          and b["counts"]["total"] == 5 and set(b["timing_ms"]) == {"save", "journal"})
    jr = server.plan_journal(tmp, 500)
    check(f"import: журнал — одна запись kind=import с причиной, именем и n_changes ({len(jr)})",
          len(jr) == j0 + 1 and jr[0]["kind"] == "import" and jr[0]["reason"] == "правка из файла"
          and jr[0]["name"] == "plan-ch.json" and jr[0]["n_changes"] == 5 and jr[0]["counts"]["changed"] == 1
          and "stocks.SBER.plan_pct" in jr[0]["paths"] and len(jr[0]["paths"]) <= 50)
    st, b2 = imp(ch, base_hash=h0, reason="устарел")
    check(f"import: устаревший base_hash → 409, файл не тронут ({st})", st == 409 and xhash() == b["hash"])

    # ── круг: экспорт → импорт того же тела = тот же plan.json ──
    st, body, hd = px("GET", "/api/pv/plan/export?format=json", raw=True)
    h1, j1, bytes1 = xhash(), xj(), PLX.read_bytes()
    st, b = px("POST", "/api/pv/plan/import", {"base_hash": hd["X-Plan-Hash"], "plan": json.loads(body), "reason": "круг"})
    check(f"круг: экспорт → импорт = unchanged, hash тот же, файл и журнал не тронуты ({st})",
          st == 200 and b.get("unchanged") is True and b["hash"] == h1 and b["diff"] == []
          and xhash() == h1 and PLX.read_bytes() == bytes1 and xj() == j1)
    n_versions = len(list((root / ".versions/Portfolio").glob("*_plan.json"))) if (root / ".versions/Portfolio").exists() else 0
    st, b = imp(json.loads(body))
    check("круг: повтор без причины тоже ничего не пишет",
          st == 200 and b.get("unchanged") is True and xhash() == h1
          and (len(list((root / ".versions/Portfolio").glob("*_plan.json"))) if (root / ".versions/Portfolio").exists() else 0) == n_versions)

    # «поля нет» ≡ null: старые записи без fee_pct/spread_pct против экспорта с null — не изменение в обе стороны
    cur0 = json.loads(body)
    nulls = [(sec, k, f) for sec in ("funds",) for k, r in cur0.get(sec, {}).items() for f, v in r.items() if v is None]
    sec, k, f = nulls[0]
    wo = json.loads(body); del wo[sec][k][f]
    st, b = imp(wo, dry_run=True)
    check(f"import dry_run: из файла убран ключ со значением null ({sec}.{k}.{f}) — unchanged, diff пуст ({st})",
          st == 200 and b.get("unchanged") is True and b["diff"] == [] and b["counts"]["total"] == 0)
    st, b = imp(wo)
    check(f"import (запись): то же — unchanged, файл не тронут ({st})", st == 200 and b.get("unchanged") is True and xhash() == h1)
    wn = json.loads(body); wn["funds"][k]["fee_pct"] = None; wn["funds"][k]["spread_pct"] = None
    for x in ("fee_pct", "spread_pct"):
        if x in cur0["funds"][k] and cur0["funds"][k][x] is not None:
            wn["funds"][k][x] = cur0["funds"][k][x]
    st, b = imp(wn, dry_run=True)
    check(f"import dry_run: добавлен ключ со значением null (отсутствовал в плане) — unchanged ({st})",
          st == 200 and b.get("unchanged") is True and b["diff"] == [])
    wc = json.loads(body); wc["funds"][k]["note"] = "реальное изменение"
    st, b = imp(wc, dry_run=True)
    check(f"import dry_run: реальное изменение значения по-прежнему в diff, unchanged нет ({st})",
          st == 200 and [x["path"] for x in b["diff"]] == [f"funds.{k}.note"] and "unchanged" not in b)

    # ── большой diff ──
    big = json.loads(json.dumps(d))
    big["ie_history"] = [{"ts": f"t{i}", "ticker": "SBER", "was": 1, "now": 2} for i in range(1000)]
    st, b = imp(big, dry_run=True)
    check(f"import: diff > 2000 строк → усечён, diff_truncated, counts полные ({st}, {len(b.get('diff', []))}, {b.get('counts', {}).get('total')})",
          st == 200 and b.get("diff_truncated") is True and len(b["diff"]) == 2000 and b["counts"]["total"] > 2000)
    st, b = imp(big, reason="ok")
    check(f"import: журнал — не больше 50 путей при тысячах изменений ({st})",
          st == 200 and server.plan_journal(tmp, 1)[0]["n_changes"] > 2000 and len(server.plan_journal(tmp, 1)[0]["paths"]) == 50)

    with urllib.request.urlopen(PXB + "/api/health") as r:
        check("health: pv_import", json.loads(r.read()).get("pv_import") is True)
    _px.shutdown()
finally:
    shutil.rmtree(tmp)
print(f"  pv export/import: проверок {passed + failed - _xi_before}")

# ── режим сайта (hub-settings@1) — GET/POST /api/hub/settings ─────────────────
print("режим сайта (hub-settings@1)")
_hs_before = passed + failed
import re as _re  # noqa: E402
import datetime as _dt  # noqa: E402
tmp = tempfile.mkdtemp(prefix="hub-api-hubset-")
try:
    root = Path(tmp)
    sfile = root / "_hub/settings.json"
    # чистые функции
    _d = server.hub_settings_default()
    _t1, _t2, _t3 = "2026-11-09T10:00:00+03:00", "2026-11-09T11:00:00+03:00", "2026-11-09T12:00:00+03:00"
    check("apply: константы и умолчание on", server.HUB_SETTINGS_FILE == "_hub/settings.json"
          and server.HUB_SETTINGS_SCHEMA == "hub-settings@1" and _d["ai_mode"] == "on")
    _off = server.hub_settings_apply(_d, {"ai_mode": "off", "note": "x"}, _t1)
    check("apply: on→off ставит off_since, returned_at null, by site",
          _off["off_since"] == _t1 and _off["returned_at"] is None and _off["by"] == "site" and _off["updated_at"] == _t1)
    _on = server.hub_settings_apply(_off, {"ai_mode": "on"}, _t2)
    check("apply: off→on ставит returned_at, off_since прежний", _on["returned_at"] == _t2 and _on["off_since"] == _t1)
    _same = server.hub_settings_apply(_on, {"ai_mode": "on", "note": "н", "by": "mac"}, _t3)
    check("apply: тот же режим — только by/note/updated_at",
          _same["off_since"] == _t1 and _same["returned_at"] == _t2 and _same["note"] == "н"
          and _same["by"] == "mac" and _same["updated_at"] == _t3)
    _re_off = server.hub_settings_apply(_on, {"ai_mode": "off"}, _t3)
    check("apply: повторное on→off обнуляет returned_at", _re_off["off_since"] == _t3 and _re_off["returned_at"] is None)
    for label, inc in (("не объект", "off"), ("режим maybe", {"ai_mode": "maybe"}),
                       ("лишнее поле", {"ai_mode": "off", "off_since": _t1}), ("note 201", {"ai_mode": "off", "note": "я" * 201})):
        try:
            server.hub_settings_apply(_d, inc, _t1)
            check(f"apply: {label} → ValueError", False)
        except ValueError:
            check(f"apply: {label} → ValueError", True)
    check("apply: note ровно 200 — можно", server.hub_settings_apply(_d, {"ai_mode": "on", "note": "я" * 200}, _t1)["note"] == "я" * 200)

    # e2e
    server.ROOT = tmp
    _hs, _ = serve(server.Handler, quiet=False)
    HSB = f"http://127.0.0.1:{_hs.server_address[1]}"

    def hs(method, body=None, auth=True):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        h = {"Content-Type": "application/json", **({"Authorization": "Basic eA=="} if auth else {})}
        rq = urllib.request.Request(HSB + "/api/hub/settings", data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(rq) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    st, b = hs("GET")
    check(f"hub-settings: GET без файла → 200, hash null, ai_mode on ({st})",
          st == 200 and b["hash"] is None and b["settings"]["ai_mode"] == "on" and b["path"] == "_hub/settings.json")
    st, _b = hs("GET", auth=False)
    check(f"hub-settings: GET без Authorization → 403 ({st})", st == 403)
    st, _b = hs("POST", {"settings": {"ai_mode": "off"}, "base_hash": None}, auth=False)
    check(f"hub-settings: POST без Authorization → 403 ({st})", st == 403 and not sfile.exists())

    st, b = hs("POST", {"settings": {"ai_mode": "off", "note": "блокировка"}, "base_hash": None})
    s1 = b.get("settings", {})
    check(f"hub-settings: POST off с base_hash null → 200 ({st})", st == 200 and b.get("hash") and s1.get("ai_mode") == "off")
    check("hub-settings: файл _hub/settings.json создан", sfile.is_file())
    check("hub-settings: off_since — МСК «…+03:00», returned_at null, by site, updated_at есть",
          bool(_re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+03:00$", s1.get("off_since") or ""))
          and s1.get("returned_at") is None and s1.get("by") == "site" and bool(s1.get("updated_at"))
          and s1.get("note") == "блокировка" and s1.get("schema") == "hub-settings@1")
    check("hub-settings: на диске то же, что в ответе", json.loads(sfile.read_text(encoding="utf-8")) == s1)
    h1 = b["hash"]
    st, b = hs("POST", {"settings": {"ai_mode": "off"}, "base_hash": None})
    check(f"hub-settings: повтор с base_hash null при существующем файле → 409 с current_hash ({st})",
          st == 409 and b.get("error") == "conflict" and b.get("current_hash") == h1 and b["settings"]["ai_mode"] == "off")
    st, b = hs("GET")
    check("hub-settings: GET после записи — hash и настройки", st == 200 and b["hash"] == h1 and b["settings"] == s1)

    time.sleep(1.1)   # updated_at с точностью до секунды
    st, b = hs("POST", {"settings": {"ai_mode": "on"}, "base_hash": h1})
    s2 = b.get("settings", {})
    check(f"hub-settings: off→on с актуальным хэшем → 200, returned_at заполнен, off_since прежний ({st})",
          st == 200 and s2.get("ai_mode") == "on" and bool(s2.get("returned_at")) and s2.get("off_since") == s1["off_since"])
    h2 = b.get("hash")
    check("hub-settings: хэш сменился", bool(h2) and h2 != h1)
    time.sleep(1.1)
    st, b = hs("POST", {"settings": {"ai_mode": "on", "note": "новая заметка"}, "base_hash": h2})
    s3 = b.get("settings", {})
    check(f"hub-settings: тот же режим с новой note → 200 ({st})", st == 200 and s3.get("note") == "новая заметка")
    check("hub-settings: тот же режим — off_since/returned_at прежние, меняются note/updated_at",
          s3.get("off_since") == s2["off_since"] and s3.get("returned_at") == s2["returned_at"]
          and s3.get("updated_at") != s2["updated_at"])
    st, b = hs("POST", {"settings": {"ai_mode": "off"}, "base_hash": h1})
    check(f"hub-settings: устаревший хэш → 409 ({st})", st == 409 and b.get("current_hash") != h1
          and b["settings"]["note"] == "новая заметка")
    h3 = hs("GET")[1]["hash"]
    before = sfile.read_text(encoding="utf-8")
    st, b = hs("POST", {"settings": {"ai_mode": "maybe"}, "base_hash": h3})
    check(f"hub-settings: ai_mode maybe → 400 ({st})", st == 400)
    st, b = hs("POST", {"settings": {"ai_mode": "off", "off_since": "2026-01-01T00:00:00+03:00"}, "base_hash": h3})
    check(f"hub-settings: лишнее поле off_since во входе → 400 ({st})", st == 400)
    st, b = hs("POST", {"settings": {"ai_mode": "off", "note": "я" * 201}, "base_hash": h3})
    check(f"hub-settings: note длиннее 200 → 400 ({st})", st == 400)
    st, b = hs("POST", {"settings": {"ai_mode": "off"}})
    check(f"hub-settings: нет base_hash → 400 ({st})", st == 400)
    check("hub-settings: отклонённое не меняет файл", sfile.read_text(encoding="utf-8") == before)

    vdir = root / ".versions/_hub"
    check("hub-settings: копии в .versions/_hub/ (по одной на перезапись, не на создание)",
          vdir.is_dir() and len([n for n in os.listdir(vdir) if n.endswith("_settings.json")]) >= 2)

    # битый файл: 500 на GET и POST, не перезаписан
    sfile.write_text("это не JSON", encoding="utf-8")
    st, b = hs("GET")
    check(f"hub-settings: битый файл → GET 500 ({st})", st == 500)
    st, b = hs("POST", {"settings": {"ai_mode": "on"}, "base_hash": h3})
    check(f"hub-settings: битый файл → POST 500 ({st})", st == 500)
    check("hub-settings: битый файл не перезаписан", sfile.read_text(encoding="utf-8") == "это не JSON")

    with urllib.request.urlopen(HSB + "/api/health") as r:
        check("health: hub_settings true", json.loads(r.read()).get("hub_settings") is True)
    _hs.shutdown()
finally:
    shutil.rmtree(tmp)
print(f"  hub-settings: проверок {passed + failed - _hs_before}")

# ── правки на NAS за период — GET /api/hub/changes?since= (сверка зеркала Mac, noai_return.py) ──
print("правки на NAS за период (/api/hub/changes)")
_hc_before = passed + failed
import hashlib as _hl  # noqa: E402
tmp = tempfile.mkdtemp(prefix="hub-api-hubchg-")
try:
    root = Path(tmp)
    _zoned = ["Portfolio/decisions/d1.json", "Gaming/user-state.json", "Health/labs.json",
             "ZenMoney/audit/m.json", "_hub/settings.json", "scenarios/s.yaml", "travel-planner/trips/x/3_a.md"]
    _junk = [".versions/x", "Portfolio/.backups/y", "Portfolio/a.tmp", "Health/.intake-backups/z.json",
             "Gaming/__pycache__/c.pyc", "Gaming/.hidden", "forecasts/z.yaml"]
    for _r in _zoned + _junk:
        _p = root / _r
        _p.parent.mkdir(parents=True, exist_ok=True)
        _p.write_text("данные " + _r, encoding="utf-8")
    st, b = server.hub_changes(str(root))
    check(f"changes: без since → 200, ровно файлы зон (7), мусор и чужое отброшены ({st})",
          st == 200 and sorted(f["path"] for f in b["files"]) == sorted(_zoned) and not b["truncated"])
    check("changes: без since — без ключа sha256", all("sha256" not in f for f in b["files"]))
    check("changes: зоны в ответе", b["zones"] == list(server.HUB_CHANGE_ZONES) and b["since"] is None)
    st, b = server.hub_changes(str(root), "2020-01-01T00:00:00+03:00")
    check(f"changes: since в прошлом → файлы зон ({st})", st == 200 and len(b["files"]) == 7)
    check("changes: sha256 совпадает с hashlib",
          all(f["sha256"] == _hl.sha256((root / f["path"]).read_bytes()).hexdigest() for f in b["files"]))
    check("changes: size как у файла", all(f["size"] == (root / f["path"]).stat().st_size for f in b["files"]))
    _f0 = b["files"][0]
    _mt = datetime.fromtimestamp((root / _f0["path"]).stat().st_mtime, server.MSK)
    check("changes: mtime в формате …+03:00 и соответствует os.stat",
          _f0["mtime"].endswith("+03:00") and abs(datetime.fromisoformat(_f0["mtime"]).timestamp() - _mt.timestamp()) < 1.5)
    st, b = server.hub_changes(str(root), "2099-01-01T00:00")
    check(f"changes: since в будущем → пусто ({st})", st == 200 and b["files"] == [] and not b["truncated"])
    st, b = server.hub_changes(str(root), "вчера")
    check(f"changes: since=вчера → 400 bad since ({st})", st == 400 and b.get("error") == "bad since")
    st, b = server.hub_changes(str(root), max_files=2)
    check(f"changes: max_files=2 → truncated и ровно 2 файла ({st})",
          st == 200 and b["truncated"] is True and len(b["files"]) == 2)

    # e2e
    server.ROOT = tmp
    _hcs, _ = serve(server.Handler, quiet=False)
    HCB = f"http://127.0.0.1:{_hcs.server_address[1]}"

    def hcg(path, auth=True):
        rq = urllib.request.Request(HCB + path, headers={"Authorization": "Basic eA=="} if auth else {})
        try:
            with urllib.request.urlopen(rq) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    _q = "/api/hub/changes?since=" + urllib.parse.quote("2020-01-01T00:00:00+03:00")
    st, _b = hcg(_q, auth=False)
    check(f"changes: GET без Authorization → 403 ({st})", st == 403)
    st, b = hcg(_q)
    _st2, _direct = server.hub_changes(str(root), "2020-01-01T00:00:00+03:00")
    check(f"changes: GET с Authorization → 200, тело как у прямого вызова ({st})",
          st == 200 and b["files"] == _direct["files"] and b["since"] == "2020-01-01T00:00:00+03:00")
    st, b = hcg("/api/hub/changes")
    check(f"changes: GET без since → 200, без хэшей ({st})",
          st == 200 and len(b["files"]) == 7 and all("sha256" not in f for f in b["files"]))
    st, _b = hcg("/api/hub/changes?since=" + urllib.parse.quote("вчера"))
    check(f"changes: GET since=вчера → 400 ({st})", st == 400)
    with urllib.request.urlopen(HCB + "/api/health") as r:
        check("health: hub_changes true", json.loads(r.read()).get("hub_changes") is True)
    _hcs.shutdown()
finally:
    shutil.rmtree(tmp)
print(f"  hub-changes: проверок {passed + failed - _hc_before}")

# ── сторож: папки /api/pv/sync = папки вьюера (loadHttpMode1), строка в строку ──
print("pv ↔ viewer")
import re as _re  # noqa: E402
_vjs = (REPO / "tools/assets/viewer.js").read_text(encoding="utf-8")
_body = _vjs[_vjs.index("async function loadHttpMode1()"):]
_body = _body[:_body.index("const full = consumeFullReload()")]
_v = _re.findall(r"\{ url: base \+ '([^']+)', pattern: /(.+?)/, folder: '([^']+)' \}", _body)
_doms = _re.search(r"DOMAIN_FOLDERS = \[([^\]]+)\]", _body).group(1)
_vd = [(f, pat) for _u, pat, f in _v] + [(f"domains/{d}/", r"\.md$") for d in _re.findall(r"'([^']+)'", _doms)]
# Шаг 12 цикла машиночитаемости: вьюер читает новые носители (decisions/, conditions-state, архивы условий, справочник бумаг);
# gate-reviews упразднён: ни вьюер, ни сервер его не берут — корень Portfolio/ сверяется по именам файлов.
_srv = list(server.PV_DIRS)
_ROOT_NAMES = ("conditions.yaml", "conditions-archive-2026.yaml", "conditions-state.json", "security-attrs.json",
               "gate-reviews.yaml", "gate-reviews-archive-2026.yaml", "plan.json", "conditions.yaml.bak")
_vroot = dict(_vd).get("Portfolio/")
_sroot = dict(_srv).get("Portfolio/")
check(f"папки вьюера = папки PV_DIRS в том же порядке ({len(_vd)} ↔ {len(_srv)})", [f for f, _ in _vd] == [f for f, _ in _srv])
check("шаблоны вьюера = PV_DIRS (кроме корня Portfolio/)", [x for x in _vd if x[0] != "Portfolio/"] == [x for x in _srv if x[0] != "Portfolio/"])
check("корень Portfolio/: вьюер берёт условия, их состояние и архивы, справочник бумаг — и не берёт gate-reviews",
      [n for n in _ROOT_NAMES if _re.search(_vroot, n)] == ["conditions.yaml", "conditions-archive-2026.yaml", "conditions-state.json", "security-attrs.json"]
      and all(_re.search(_sroot, n) for n in ("conditions.yaml", "conditions-archive-2026.yaml", "conditions-state.json", "security-attrs.json"))
      and not any(_re.search(_sroot, n) for n in ("gate-reviews.yaml", "gate-reviews-archive-2026.yaml")))
if _vd != _srv:
    print("    вьюер:", _vd)
    print("    сервер:", _srv)


# ── labs.json: ручная точка анализа со страницы (только при ai_mode: off) ────────────────────────────────
print("labs: ручная точка")
check("HEALTH_FILES содержит labs", "labs" in server.HEALTH_FILES)
_lr = server._labs_rules()
check("labs_rules.py находится сервером (рядом с server.py или в каноне скилла)", _lr is not None)
_lt = tempfile.mkdtemp(prefix="hub-api-labs-")
_lh = tempfile.mkdtemp(prefix="hub-api-labs-h-")
try:
    server.ROOT, server.HEALTH_ROOT = _lt, _lh
    _SK = {"date": "2026-01-10", "value": 5.0, "text": None, "unit": "ед", "ref": {"low": 1, "high": 10},
           "status": "norm", "lab": "Лаб", "study": None, "src": "doc1.pdf"}
    _LABS0 = {"schema": "health-labs@1", "generated": "2026-01-01", "person": {"sex": "x"},
              "categories": [{"key": "cat1", "name": "Категория"}],
              "biomarkers": [{"id": "aa", "name": "Показатель А", "category": "cat1", "kind": "num", "unit": "ед",
                              "ref": {"low": 1, "high": 10}, "series": [dict(_SK)]}], "updated": "2026-01-10"}
    (Path(_lh) / "labs.json").write_text(json.dumps(_LABS0, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    _srv2, _ = serve(server.Handler, quiet=False)
    _B = f"http://127.0.0.1:{_srv2.server_address[1]}"

    def lapi(method, path, body=None):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        rq = urllib.request.Request(_B + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(rq) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def set_mode(mode):
        sf = Path(_lt) / "_hub/settings.json"
        sf.parent.mkdir(exist_ok=True)
        cur = server.hub_settings_default()
        new = server.hub_settings_apply(cur, {"ai_mode": mode}, "2026-11-09T10:00:00+03:00") if mode == "off" else cur
        sf.write_text(json.dumps(new, ensure_ascii=False), encoding="utf-8")

    def lget():
        return lapi("GET", "/api/hd/file?path=labs.json")

    def mk(mut):
        d = json.loads(json.dumps(_LABS0))
        mut(d)
        return json.dumps(d, ensure_ascii=False)

    def man(date, value, **kw):
        return {"date": date, "value": value, "text": None, "unit": "ед", "ref": {"low": 1, "high": 10},
                "status": "norm", "lab": None, "source": "manual", **kw}

    st, b = lget()
    check("labs: GET через /api/hd/file с хэшем", st == 200 and b.get("hash") and json.loads(b["content"])["schema"] == "health-labs@1")
    h0 = b["hash"]
    add = mk(lambda d: d["biomarkers"][0]["series"].append(man("2026-02-01", 12)))

    set_mode("on")
    st, b = lapi("POST", "/api/hd/save", {"path": "labs.json", "content": add, "base_hash": h0})
    check("labs: ai_mode on → 403 с понятным текстом", st == 403 and "ИИ" in (b.get("detail") or ""))
    check("labs: при 403 файл не тронут", lget()[1]["hash"] == h0)
    (Path(_lt) / "_hub/settings.json").unlink()
    st, b = lapi("POST", "/api/hd/save", {"path": "labs.json", "content": add, "base_hash": h0})
    check("labs: нет файла настроек (= on) → 403", st == 403)
    (Path(_lt) / "_hub/settings.json").write_text("{не json", encoding="utf-8")
    st, b = lapi("POST", "/api/hd/save", {"path": "labs.json", "content": add, "base_hash": h0})
    check("labs: битый файл настроек → 403 (закрыто по умолчанию)", st == 403)

    set_mode("off")
    lie = mk(lambda d: d["biomarkers"][0]["series"].append(man("2026-02-01", 12, status="norm")))
    st, b = lapi("POST", "/api/hd/save", {"path": "labs.json", "content": lie, "base_hash": h0})
    check("labs: off + ручная точка → 200, normalized", st == 200 and b.get("normalized") is True)
    st, g = lget()
    doc = json.loads(g["content"])
    pts = doc["biomarkers"][0]["series"]
    check("labs: точка с source=manual; страница прислала status=norm, сервер посчитал high (12 > 10)",
          len(pts) == 2 and pts[1]["source"] == "manual" and pts[1]["status"] == "high")
    check("labs: точка скилла байт-в-байт та же", pts[0] == _SK)
    check("labs: ref маркера = ref последней точки (recompute_marker на сервере)", doc["biomarkers"][0]["ref"] == {"low": 1, "high": 10})
    h1 = g["hash"]
    st, b = lapi("POST", "/api/hd/save", {"path": "labs.json", "content": add, "base_hash": h0})
    check("labs: устаревший base_hash → 409", st == 409 and b.get("current_hash") == h1)

    def cur_with(mut):
        d = json.loads(lget()[1]["content"])
        mut(d)
        return json.dumps(d, ensure_ascii=False)

    def post(content):
        return lapi("POST", "/api/hd/save", {"path": "labs.json", "content": content, "base_hash": lget()[1]["hash"]})

    st, b = post(cur_with(lambda d: d["biomarkers"][0]["series"][1].update(status="norm", value=0.5)))
    check("labs: правка своей ручной точки → 200, статус пересчитан (0.5 < 1 → low)",
          st == 200 and json.loads(lget()[1]["content"])["biomarkers"][0]["series"][1]["status"] == "low")
    st, b = post(cur_with(lambda d: d["biomarkers"][0]["series"][1].update(value=4)))
    check("labs: правка значения ручной точки → 200", st == 200)

    def bad(name, mut, frag=""):
        h = lget()[1]["hash"]
        st, b = post(cur_with(mut))
        check(f"labs: {name} → 400", st == 400 and frag in (b.get("detail") or ""))
        check(f"labs: {name} — файл не тронут", lget()[1]["hash"] == h)

    def newmk(**kw):
        return {"id": "bb", "name": "Б", "category": "cat1", "kind": "num", "unit": "", "ref": None,
                "series": [man("2026-02-02", 1)], **kw}

    bad("правка значения точки скилла", lambda d: d["biomarkers"][0]["series"][0].update(value=7), "точки скилла")
    bad("удаление точки скилла", lambda d: d["biomarkers"][0]["series"].pop(0), "точки скилла")
    bad("превращение точки скилла в manual", lambda d: d["biomarkers"][0]["series"][0].update(source="manual"), "точки скилла")
    bad("ручная точка на дату точки скилла", lambda d: d["biomarkers"][0]["series"].append(man("2026-01-10", 3)), "уже есть точка")
    bad("две ручные точки на одну дату", lambda d: d["biomarkers"][0]["series"].append(man("2026-02-01", 3)), "больше одной")
    bad("смена имени маркера", lambda d: d["biomarkers"][0].update(name="Другое"), "name")
    bad("смена категории маркера", lambda d: d["biomarkers"][0].update(category="cat1x"), "category")
    bad("правка категорий", lambda d: d["categories"].append({"key": "z", "name": "Z"}), "категории")
    bad("правка person", lambda d: d["person"].update(sex="y"), "person")
    bad("единица ≠ единице показателя", lambda d: d["biomarkers"][0]["series"][1].update(unit="мг"), "единиц")
    bad("битый референс", lambda d: d["biomarkers"][0]["series"][1].update(ref={"low": 9, "high": 2}), "ref")
    bad("ни числа, ни текста", lambda d: d["biomarkers"][0]["series"][1].update(value=None, text=None), "число")
    bad("ручная точка с привязкой к исследованию", lambda d: d["biomarkers"][0]["series"][1].update(study="s1"), "исследован")
    bad("новый маркер с точкой скилла", lambda d: d["biomarkers"].append(newmk(series=[dict(_SK)])), "source=manual")
    bad("новый маркер: чужая категория", lambda d: d["biomarkers"].append(newmk(category="нет")), "категория")
    bad("новый маркер: имя занято", lambda d: d["biomarkers"].append(newmk(name="Показатель А")), "занято")
    bad("новый маркер: плохой id", lambda d: d["biomarkers"].append(newmk(id="Б б")), "id")
    bad("удаление маркера с точками скилла", lambda d: d["biomarkers"].clear(), "не удаляет")
    bad("лишний ключ на маркере", lambda d: d["biomarkers"][0].update(extra=1), "служебные")
    bad("правка kind без правки точек", lambda d: d["biomarkers"][0].update(kind="qual"), "производные")

    newm = newmk(id="nm", name="Новый показатель", kind="qual", unit="мг",
                 series=[man("2026-03-01", 3, unit="мг", ref=None, status="high")])
    st, b = post(cur_with(lambda d: d["biomarkers"].append(newm)))
    nm = [m for m in json.loads(lget()[1]["content"])["biomarkers"] if m["id"] == "nm"]
    check("labs: новый показатель → 200, kind=num и статус na пересчитаны сервером",
          st == 200 and nm and nm[0]["kind"] == "num" and nm[0]["series"][0]["status"] == "na" and nm[0]["unit"] == "мг")
    st, b = post(cur_with(lambda d: d["biomarkers"].__setitem__(slice(None), [m for m in d["biomarkers"] if m["id"] != "nm"])))
    check("labs: удаление целиком ручного показателя → 200",
          st == 200 and all(m["id"] != "nm" for m in json.loads(lget()[1]["content"])["biomarkers"]))
    st, b = post(cur_with(lambda d: d["biomarkers"][0]["series"].pop(1)))
    check("labs: удаление своей ручной точки → 200, точка скилла осталась",
          st == 200 and json.loads(lget()[1]["content"])["biomarkers"][0]["series"] == [_SK])
    st, b = lapi("POST", "/api/hd/save", {"path": "labs.json", "content": lget()[1]["content"], "base_hash": None})
    check("labs: base_hash null → 400 (создавать labs.json со страницы нельзя)", st == 400)
    st, b = post('{"schema":"health-labs@1"}')
    check("labs: подмена всего файла → 400", st == 400)
    check("labs: копии в .versions/ пишутся", (Path(_lh) / ".versions").is_dir())
    _srv2.shutdown()
finally:
    server.ROOT, server.HEALTH_ROOT = tmp, hroot
    shutil.rmtree(_lt, ignore_errors=True)
    shutil.rmtree(_lh, ignore_errors=True)

# ── /api/pv/macro/inflation — недельная инфляция владельца (форма вьюера; файл owner.jsonl — один писатель hub-api) ──
print("pv macro inflation")
import importlib.util as _ilu  # noqa: E402
_si_spec = _ilu.spec_from_file_location("save_inflation", REPO / "skills/macro-ru-watcher/scripts/save_inflation.py")
_si = _ilu.module_from_spec(_si_spec)
sys.path.insert(0, str(REPO / "_shared-references"))
_si_spec.loader.exec_module(_si)
tmp = tempfile.mkdtemp(prefix="hub-api-infl-")
try:
    root = Path(tmp)
    server.ROOT = tmp
    _pi, _ = serve(server.Handler, quiet=False)
    PIB = f"http://127.0.0.1:{_pi.server_address[1]}"

    def ip(body, auth=True, raw=None):
        data = raw if raw is not None else json.dumps(body).encode()
        h = {"Content-Type": "application/json", **({"Authorization": "Basic eA=="} if auth else {})}
        rq = urllib.request.Request(PIB + "/api/pv/macro/inflation", data=data, method="POST", headers=h)
        try:
            with urllib.request.urlopen(rq) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    _today = datetime.now(server.MSK).date()
    _d0 = (_today - timedelta(days=2)).isoformat()
    REC = {"date": _d0, "week_pct": 0.11, "week_period": "03–09.11", "yoy_pct": 6.4, "yoy_as_of": _d0,
           "source_name": "Росстат", "source_url": "https://rosstat.gov.ru/x"}
    F = root / "macro-snapshots/inflation/owner.jsonl"
    check("infl: в списке папок pv-sync, только model|owner.jsonl",
          ("macro-snapshots/inflation/", r"^(model|owner)\.jsonl$") in server.PV_DIRS)
    st, _ = ip({"record": REC}, auth=False)
    check(f"infl: без Authorization → 403 ({st})", st == 403)
    st, b = ip({"record": REC, "base_hash": server.file_hash(b"")})
    check(f"infl: первая запись, base_hash пустого файла → 200, файл создан ({st})",
          st == 200 and b["records"] == 1 and F.is_file() and server.infl_owner_hash(tmp) == b["hash"])
    row = json.loads(F.read_text(encoding="utf-8").splitlines()[0])
    check("infl: строка — author owner, recorded_at МСК, порядок ключей как у скилла",
          row["author"] == "owner" and row["recorded_at"].endswith("+03:00") and list(row) == list(_si.FIELDS)
          and row["date"] == _d0 and row["week_pct"] == 0.11 and row["source_name"] == "Росстат")
    st, b2 = ip({"record": REC})
    check(f"infl: тот же вход — duplicate, без записи ({st})", st == 200 and b2.get("duplicate") is True
          and len(F.read_text(encoding="utf-8").splitlines()) == 1)
    st, b3 = ip({"record": REC, "base_hash": "чужой"})
    check(f"infl: base_hash не совпал → 409 с current_hash ({st})", st == 409 and b3["current_hash"] == b["hash"])
    st, b4 = ip({**REC, "week_pct": 0.2, "base_hash": b["hash"]})                  # поля без обёртки record
    check(f"infl: другая запись без обёртки → 200, вторая строка ({st})", st == 200 and b4["records"] == 2)
    n_before = F.read_bytes()
    for label, ch in (("week_pct вне границ", {"week_pct": 9}), ("week_pct строка", {"week_pct": "0.1"}), ("yoy_pct пусто", {"yoy_pct": None}),
                      ("дата из будущего", {"date": (_today + timedelta(days=1)).isoformat()}), ("дата старше года", {"date": "2020-01-01"}),
                      ("week_period короткий", {"week_period": "а"}), ("source_name пусто", {"source_name": ""}),
                      ("ссылка не http", {"source_url": "javascript:1"}), ("bool вместо числа", {"week_pct": True})):
        st, b5 = ip({"record": {**REC, **ch}})
        check(f"infl: {label} → 400 bad record ({st})", st == 400 and b5.get("error") == "bad record" and b5.get("problems"))
    st, _ = ip(None, raw=b"{")
    check(f"infl: не JSON → 400 ({st})", st == 400)
    st, _ = ip(None, raw=b"[1]")
    check(f"infl: не объект → 400 ({st})", st == 400)
    st, _ = ip({"record": REC, "base_hash": 5})
    check(f"infl: base_hash не строка → 400 ({st})", st == 400)
    check("infl: отказы файл не меняют", F.read_bytes() == n_before)
    check("infl: model.jsonl сервер не создаёт (один файл — один писатель)", not (root / "macro-snapshots/inflation/model.jsonl").exists())
    # сторож: проверка сервера = проверка скрипта скилла (границы, поля, отказы)
    _rt = "2026-11-12T10:00:00+03:00"
    _t = date(2026, 11, 12)
    base = {"date": "2026-11-12", "week_pct": 0.11, "week_period": "03–09.11", "yoy_pct": 6.4, "yoy_as_of": "2026-11-09",
            "source_url": "https://x.y/z", "source_name": "Росстат"}
    cases = [{}, {"week_pct": 5.1}, {"week_pct": -3.1}, {"week_pct": 5}, {"week_pct": -3}, {"yoy_pct": 100.5}, {"yoy_pct": -5.1},
             {"yoy_pct": 100}, {"date": "2026-11-13"}, {"date": "2025-11-12"}, {"date": "2025-11-11"}, {"date": "bad"},
             {"yoy_as_of": None}, {"yoy_as_of": "2026-12-01"}, {"week_period": "ab"}, {"week_period": "abc"}, {"week_period": "x" * 41},
             {"source_name": "R"}, {"source_name": "RR"}, {"source_name": "R" * 81}, {"source_url": None}, {"source_url": ""},
             {"source_url": "ftp://x"}, {"source_url": "http://a b"}, {"source_url": "https://" + "a" * 300}, {"week_pct": float("nan")}]
    same_all = True
    for ch in cases:
        a, ea = server.infl_validate({**base, **ch}, _t, _rt)
        b_, eb = _si.validate({**base, **ch}, _t, "owner", _rt)
        if (a, bool(ea)) != (b_, bool(eb)):
            same_all = False
            print("    расхождение сервера и скрипта:", ch, a, ea, b_, eb)
    check(f"infl: сервер и save_inflation.py решают одинаково на {len(cases)} входах", same_all)
    check("infl: поля сервера = поля скрипта", server.INFL_FIELDS == _si.FIELDS)
    _pi.shutdown()
finally:
    shutil.rmtree(tmp)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
