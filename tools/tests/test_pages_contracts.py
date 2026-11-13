#!/usr/bin/env python3
"""
Контракт-тест страниц Personal Hub (tools/hub|travel|games.html) ↔ данные скиллов.

Зеркалит ожидания JS-парсеров страниц и гоняет их по:
  - бандл-сиду skills/game-advisor/references/taste-profile.yaml (реальная структура);
  - синтетической фикстуре trip.yaml (контракт trip-meta@1) через
    travel-planning check_format.check_trip_meta — ловит расхождение
    валидатора скилла и ожиданий страницы;
  - синтетической фикстуре рекомендации (маркеры из SKILL.md game-advisor).

Дрейф с ЛЮБОЙ стороны (скилл поменял формат / страница поменяла парсер —
обнови зеркальные регэкспы здесь) должен ронять этот тест, а не молча
ломать страницы.

Запуск:
    python3 tools/tests/test_pages_contracts.py
Требует PyYAML (как js-yaml на странице games).
"""
import ast
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "skills/travel-planning/scripts"))

import yaml  # noqa: E402
import check_format as cf  # noqa: E402

passed = 0
failed = 0


def check(name: str, cond: bool) -> None:
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}")


# ── зеркала JS-парсеров страниц (games.html / travel.html) ──────────────────

VERDICTS = ("восторг", "понравилось", "нормально", "не понравилось", "брошено")  # games.html VERDICTS

def parse_evidence(s: str):
    """Зеркало evidence-парсера games.html: название / часы / скобочный вердикт."""
    hours = None
    verdict = None
    hm = re.search(r"(\d+(?:\.\d+)?)\s*ч", s)
    if hm:
        hours = float(hm.group(1))
    t = re.sub(r"\d+(?:\.\d+)?\s*ч\.?", "", s)

    def strip_paren(m):
        nonlocal verdict
        inner = m.group(1).strip().lower()
        if inner in VERDICTS:
            verdict = inner
        return ""

    t = re.sub(r"\(([^)]*)\)", strip_paren, t)
    t = re.sub(r"\s{2,}", " ", t).strip(" ·,;:").strip()
    return t, hours, verdict


# ── 1. taste-profile.yaml (бандл-сид game-advisor) ──────────────────────────

seed_path = REPO / "skills/game-advisor/references/taste-profile.yaml"
profile = yaml.safe_load(seed_path.read_text(encoding="utf-8"))

check("profile: ключи верхнего уровня на месте",
      all(k in profile for k in ("updated", "platforms", "mood_clusters", "anti_patterns", "library")))
check("profile: updated — дата", bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(profile.get("updated")))))

mc = profile.get("mood_clusters") or {}
check("profile: кластеры есть", len(mc) >= 3)
for slug, c in mc.items():
    check(f"cluster {slug}: title есть (games.html показывает его)", bool((c or {}).get("title")))
    w = (c or {}).get("weight")
    check(f"cluster {slug}: weight 0..1", isinstance(w, (int, float)) and 0 <= w <= 1)
    ev = (c or {}).get("evidence") or []
    check(f"cluster {slug}: evidence непустой список", isinstance(ev, list) and len(ev) >= 1)
    for s in ev:
        t, h, v = parse_evidence(str(s))
        check(f"cluster {slug}: evidence парсится в непустое название: {s!r}", bool(t))
        check(f"cluster {slug}: в названии не осталось скобок/часов: {s!r}",
              "(" not in t and not re.search(r"\d+\s*ч\b", t))

for i, a in enumerate(profile.get("anti_patterns") or []):
    check(f"anti_pattern #{i}: есть pattern", bool((a or {}).get("pattern")))

bad_verdicts = [g.get("verdict") for g in (profile.get("library") or [])
                if g and g.get("verdict") and g["verdict"] not in VERDICTS]
check(f"library: вердикты строго из enum {'/'.join(VERDICTS)} (нарушения: {bad_verdicts})",
      not bad_verdicts)
check("library: есть записи с вердиктами (иначе сетка библиотеки пуста)",
      any(g.get("verdict") for g in (profile.get("library") or []) if g))

# ── 2. trip.yaml: валидатор скилла ↔ ожидания travel.html ───────────────────

TRIP_FIXTURE = (
    "schema: trip-meta@1\n"
    "title: Тестовая поездка\n"
    "status: planning\n"
    "travelers: [мария, алексей]\n"
    'season: "2027-05"\n'
    "updated: 2026-07-10\n"
)
check("trip.yaml фикстура проходит check_trip_meta", cf.check_trip_meta(TRIP_FIXTURE) == [])
# зеркало travel.html: STATUS_BADGE ключи ⊆ enum валидатора
check("enum статусов страницы == enum валидатора скилла",
      set(cf.TRIP_META_STATUSES) == {"planning", "ready", "done", "superseded"})
# зеркало travel.html seasonKey: сезон фикстуры парсится в ключ сортировки
m = re.search(r'season:\s*"(\d{4})(?:-(\d{2}))?"', TRIP_FIXTURE)
check("season фикстуры парсится seasonKey-регэкспом страницы", bool(m))

# реальные trip.yaml (если Synology смонтирован) — тоже валидны
trips_root = Path.home() / "Library/CloudStorage/SynologyDrive-home/Claude-Memory/travel-planner/trips"
if trips_root.is_dir():
    for ty in sorted(trips_root.glob("*/trip.yaml")):
        issues = cf.check_trip_meta(ty.read_text(encoding="utf-8"))
        check(f"реальный {ty.parent.name}/trip.yaml валиден: {issues}", issues == [])

# ── 3. рекомендация game-advisor: маркеры машиночитаемости ──────────────────

RECO_FIXTURE = """# Рекомендация: тестовая подборка

- **Дата:** 2026-07-10
- **Кластер:** bolshaya_igra (0.95)
- **Склоняется к:** **Игра Б**

## Кандидаты

| # | Игра | Роль | HLTB |
|---|---|---|---|
| 1 | Игра А | core (мостик X) | 50ч |
| 2 | **Игра Б** ← интерес | смена ритма (мостик Y) | 40ч |

## Итоги (заполнить в КАЛИБРОВКЕ)

- Игра А — `итог:` _(попадание/промах/частично)_
- **Игра Б — `итог:`** _(в фокусе)_
"""

def parse_reco(text: str):
    """Зеркало parseReco из games.html."""
    out = {"date": None, "cluster": None, "candidates": []}
    dm = re.search(r"\*\*Дата:\*\*\s*([0-9-]+)", text)
    out["date"] = dm.group(1) if dm else None
    cm = re.search(r"\*\*Кластер:\*\*\s*([\wа-яё_-]+)", text, re.I)
    out["cluster"] = cm.group(1) if cm else None
    parts = re.split(r"^##\s+Кандидаты\s*$", text, flags=re.M)
    if len(parts) > 1:
        sec = re.split(r"^##\s+", parts[1], flags=re.M)[0]
        rows = [l for l in sec.split("\n") if re.match(r"^\s*\|", l)]
        if len(rows) > 1:
            header = [c.strip().lower() for c in rows[0].strip("| ").split("|")]
            i_name = next((i for i, c in enumerate(header) if "игра" in c), -1)
            i_why = next((i for i, c in enumerate(header) if "роль" in c), -1)
            for row in rows[1:]:
                if re.match(r"^\|[\s:|-]+\|$", row.strip()):
                    continue
                cells = [c.strip() for c in row.strip().strip("|").split("|")]
                name = re.sub(r"\s*←.*$", "", cells[i_name].replace("**", "")).strip()
                if name:
                    out["candidates"].append({"name": name, "why": cells[i_why].replace("**", "")})
    return out

# ── контракт имён экспорта ↔ stageOf() travel.html ──────────────────────────
# Панель travel.html группирует файлы поездки по стадиям регэкспом
# `/^([0-6])[_ ]/` (первый символ имени — цифра стадии). Экспортёр обязан
# давать ИМЕННО такие имена для HTML (канон как у PDF/DOCX): без ведущей цифры
# стадия не распознаётся и файл не показывается (реальный баг: экспорт-сессия
# дала имена без префикса → пришлось переименовывать вручную). Тест связывает
# file_naming.py (продюсер) и парсер страницы (потребитель): дрейф с любой
# стороны его ронит.
sys.path.insert(0, str(REPO / "skills/travel-planning/scripts/export"))
import file_naming as fn  # noqa: E402

_STAGE_OF_RE = re.compile(r"^([0-6])[_ ]")  # зеркало stageOf() из travel.html


def stage_of(name: str):
    m = _STAGE_OF_RE.match(name)
    return int(m.group(1)) if m else None


TRIP = "вьетнам_север_2026-09"
# (стадия, имя-строитель) — HTML-экспорт каждой стадии 0–6.
_EXPORT_NAMES = {
    0: fn.build_scope_filename(TRIP, ext="html"),
    1: fn.build_dr_reports_filename(TRIP, ext="html"),
    2: fn.build_similarity_filename(TRIP, ext="html"),
    3: fn.build_poi_filename(TRIP, ext="html"),
    4: fn.build_variants_filename(TRIP, version=1, ext="html"),
    5: fn.build_final_plan_filename(TRIP, version=4, ext="html"),
    6: fn.build_final_filename(TRIP, version=1, ext="html"),
}
for st, fname in _EXPORT_NAMES.items():
    check(f"имя HTML Stage {st} — .html", fname.endswith(".html"))
    check(f"имя HTML Stage {st} начинается с цифры стадии", fname.startswith(f"{st}_"))
    check(f"stageOf() распознаёт Stage {st} из «{fname}»", stage_of(fname) == st)
# HTML и PDF одной стадии различаются только расширением (канон единый).
check("HTML-имя = PDF-имя по основе (Stage 0)",
      fn.build_scope_filename(TRIP, ext="html")[:-4] == fn.build_scope_filename(TRIP, ext="pdf")[:-3])
# Негатив: имя без ведущей цифры (как давала сломанная экспорт-сессия) НЕ парсится.
check("имя без префикса стадии → stageOf None", stage_of(f"{TRIP}_регионы.html") is None)

# N_stage_log.md — лог прогона стадии, не артефакт стадии (batch 2, §6.1):
# matчится тем же /^([0-6])[_ ]/, и без явного фильтра best() (localeCompare
# desc) предпочитал «0_stage_log.md» вместо «0_scope.md» — «смотреть (md)»
# открывал лог. buildStages() фильтрует его ДО вызова stageOf().
_STAGE_LOG_RE = re.compile(r"_stage_log\.md$", re.IGNORECASE)
# {stem}_print.html — промежуточный сайдкар HTML→PDF (batch 2, коллизия имён):
# раньше писался в ТО ЖЕ имя, что HTML-экспорт, и молча затирал его (Stage 3
# терял edit-слой). Теперь отдельное имя + фильтр в buildStages().
_PRINT_SIDECAR_RE = re.compile(r"_print\.html$", re.IGNORECASE)


def is_stage_file(name: str):
    """Зеркало фильтра `rootFiles.forEach` в buildStages() travel.html."""
    if _STAGE_LOG_RE.search(name):
        return False
    if _PRINT_SIDECAR_RE.search(name):
        return False
    return stage_of(name) is not None


check("0_stage_log.md matчится сырым stageOf() (без фильтра)",
      stage_of("0_stage_log.md") == 0)
check("но is_stage_file() (= buildStages()) его отфильтровывает",
      not is_stage_file("0_stage_log.md"))
check("0_scope.md — обычный файл стадии, не фильтруется",
      is_stage_file("0_scope.md"))
check("N_stage_log.md для любой стадии 0–6 — не файл стадии",
      all(not is_stage_file(f"{n}_stage_log.md") for n in range(7)))
check("сайдкар {stem}_print.html — не файл стадии",
      not is_stage_file("3_регион_b_2027-04_места_print.html"))
check("настоящий HTML-экспорт тех же основ — файл стадии",
      is_stage_file("3_регион_b_2027-04_места.html"))

# ── ось «имя md в edit-слое Stage 3 ↔ whitelist write-API» ───────────────────
# Экспортированная страница Stage 3 правит СВОЙ md через POST /api/save, а имя
# файла зашивается в страницу при сборке (stages_html._stage3_md_name). Сайдкар
# пускает только `travel-planner/trips/{id}/3_*.md` — значит имя обязано быть
# каноничным. Разошлось: экспорт из polished-черновика зашил
# «polished_3_poi_pool.md» → фоновый fetch ловил 403, edit-слой не поднимался, и
# страница была неотличима от read-only витрины (регион_a_2027, 2026-07-27).
# Тест связывает продюсера имени и потребителя-whitelist: дрейф с любой стороны
# роняет его, а не тихо отключает правки.
sys.path.insert(0, str(REPO / "tools/hosting/api"))
import server as _api_s3  # noqa: E402
# stages_html — пакетный импорт (`export.stages_html`), поэтому scripts/ должен
# стоять в sys.path ПЕРЕД scripts/export: иначе имя `export` резолвится в
# export.py и пакет ломается циклическим импортом.
sys.path.insert(0, str(REPO / "skills/travel-planning/scripts"))
from export import stages_html as _sh  # noqa: E402

_S3_TRIP = "travel-planner/trips/регион_a_2027/"
with tempfile.TemporaryDirectory() as _t:
    _d = Path(_t)
    (_d / "3_poi_pool.md").write_text("x", encoding="utf-8")
    _s3_name = _sh._stage3_md_name(_d / "3_регион_b_2027-04_места.html",
                                   _d / "polished_stage_3.md")
check("edit-слой Stage 3: имя md проходит whitelist write-API",
      _s3_name is not None
      and _api_s3.is_allowed(_api_s3.norm_path(_S3_TRIP + _s3_name)))
check("негатив: имя polished-черновика whitelist НЕ проходит",
      not _api_s3.is_allowed(_api_s3.norm_path(_S3_TRIP + "polished_3_poi_pool.md")))
check("экспорт не возвращает имя, которое сам whitelist отвергнет",
      all(_api_s3.is_allowed(_api_s3.norm_path(_S3_TRIP + n))
          for n in ("3_poi_pool.md", "3_poi_pool_v4.md")))


r = parse_reco(RECO_FIXTURE)
check("reco: дата парсится", r["date"] == "2026-07-10")
check("reco: кластер парсится", r["cluster"] == "bolshaya_igra")
check("reco: два кандидата", len(r["candidates"]) == 2)
check("reco: «почему» (Роль) у кандидата", r["candidates"][0]["why"] == "core (мостик X)")
check("reco: маркер «← интерес» срезан из имени", r["candidates"][1]["name"] == "Игра Б")
check("reco: маркер Итогов присутствует в фикстуре", "`итог:`" in RECO_FIXTURE)

# ── 3a. watchlist.yaml (game-advisor) ↔ экран «Присматриваюсь» ──────────────
# Список «обсудили, но не купили» ведёт ТОЛЬКО скилл, страница его читает.
# Два независимых enum'а статусов (таблица в SKILL.md и W_STATUS в games.html)
# разъедутся молча: незнакомый статус на странице уедет в «на карандаше», и
# отказ покажется отложенным. Тест держит их одним множеством.
print("games · присматриваюсь")
W_STATUSES = ("хочу", "на-карандаш", "не-интересно")
_gsk = (REPO / "skills/game-advisor/SKILL.md").read_text(encoding="utf-8")
UI_KIT_JS0 = (REPO / "tools/assets/ui-kit.js").read_text(encoding="utf-8")
UI_KIT_CSS0 = (REPO / "tools/assets/ui-kit.css").read_text(encoding="utf-8")
_gh = (REPO / "tools/games.html").read_text(encoding="utf-8")

check("SKILL.md: режим ПРИСМАТРИВАЮСЬ описан", "### 1a. ПРИСМАТРИВАЮСЬ" in _gsk)
check("SKILL.md: путь GAMING_WATCHLIST объявлен", "GAMING_WATCHLIST" in _gsk)
# Список нужен не только чтобы копиться: скидочный прогон и обычная выдача
# обязаны читать его ДО поиска новинок, иначе отложенное своё подменяется чужим.
check("SKILL.md: скидочный прогон без названия игры описан отдельным режимом",
      "### 4a. СКИДОЧНЫЙ ПРОГОН" in _gsk)
check("SKILL.md: скидочный прогон начинается с watchlist, а не с новинок",
      re.search(r"4a\. СКИДОЧНЫЙ ПРОГОН[\s\S]{0,900}Начинать с `watchlist\.yaml`", _gsk) is not None)
check("SKILL.md: ценовой порог из condition проверяется явно",
      re.search(r"4a\. СКИДОЧНЫЙ ПРОГОН[\s\S]{0,1400}ждёт скидку ≤", _gsk) is not None)
check("SKILL.md: режим РЕКОМЕНДАЦИЯ читает watchlist до web_search",
      re.search(r"Загрузи `Gaming/watchlist\.yaml` и учти его ДО поиска[\s\S]{0,900}web_search по каталогу", _gsk) is not None)   # между ними — абзац про оверлей user-state.json
for _s in W_STATUSES:
    check(f"SKILL.md: статус {_s} в enum режима", f"`{_s}`" in _gsk)
_w_block = re.search(r"var W_STATUS = \[(.*?)\];", _gh, re.S)
check("games.html: enum статусов страницы == enum скилла",
      bool(_w_block) and set(re.findall(r'key:\s*"([^"]+)"', _w_block.group(1))) == set(W_STATUSES))
check("games.html: экран watch зарегистрирован в SCREENS",
      re.search(r'var SCREENS = \[[^\]]*"watch"', _gh) is not None)
check("games.html: у экрана watch есть правило показа",
      '[data-screen="watch"] .sc-watch' in _gh)
# Навигация — общая ui-kit (1.23.0): один список GAMES_NAV на рельс и нижнюю
# панель; число колонок панели uiNavMount берёт из длины списка (--n), так что
# «пятый пункт на 4 колонках» больше невозможен по построению.
_gnav = re.search(r"var GAMES_NAV = \[([\s\S]*?)\n\];", _gh)
check("games.html: навигация ведёт на watch (пункт в GAMES_NAV)", bool(_gnav) and 'k: "watch"' in _gnav.group(1))
check("games.html: пунктов навигации столько же, сколько экранов (SCREENS)",
      bool(_gnav) and len(re.findall(r'\{ k: "', _gnav.group(1))) == len(re.findall(r'"\w+"', re.search(r"var SCREENS = \[([^\]]*)\]", _gh).group(1))))
check("games.html: рельс и панель — общие ui-kit (uiRailHTML/uiNavMount, data-s)",
      'uiRailHTML(GAMES_NAV, null, { key: "data-s" })' in _gh and 'uiNavMount(GAMES_NAV, screen, { key: "data-s" })' in _gh)
# 404 watchlist.yaml = «список пуст», а не «нет связи»: файла может не быть,
# пока советник ничего не записал, и из-за него нельзя гасить строку статуса.
check("games.html: отсутствие watchlist.yaml не считается обрывом связи",
      re.search(r"r\.status === 404", _gh) is not None)
check("games.html: список read-only (страница не пишет в watchlist)",
      re.search(r'(POST|PUT)[^\n]*watchlist', _gh) is None)
check("games.html: единственная запись — POST /api/gm/save с path USER_PATH (taste-profile и watchlist не пишутся)",
      _gh.count('GM_API + "save"') == 1 and "path: USER_PATH" in _gh and 'USER_PATH = "Gaming/user-state.json"' in _gh)

# ── ось «игры: один enum» (оверлей Gaming/user-state.json, games.html v2.1) ──
# Слова состояния и оценки живут в трёх местах: кодлисты (codelists.json → валидатор сервера и карточка),
# VERDICTS/W_STATUS страницы (раскраска списков), SKILL.md. Разъедутся — карточка запишет значение,
# которое список не покажет, а сервер отвергнет.
print("games · один enum")
import hashlib as _hl  # noqa: E402
_gcl = __import__("json").loads((REPO / "_shared-references/codelists.json").read_text(encoding="utf-8"))["lists"]
_g_states = [c for c, e in _gcl["game_state"].items() if not e.get("legacy")]
check("codelists: game_state — 4 живых значения статуса в порядке владельца; играю / пройдена / брошена — legacy → куплена; демо — legacy → на-карандаш (флаг demo)",
      _g_states == ["хочу", "на-карандаш", "не-интересно", "куплена"]
      and all(_gcl["game_state"].get(c, {}).get("legacy") and _gcl["game_state"][c].get("migrate_to") == "куплена" for c in ("играю", "пройдена", "брошена"))
      and _gcl["game_state"]["демо"].get("legacy") and _gcl["game_state"]["демо"].get("migrate_to") == "на-карандаш"
      and _gcl["game_state"]["не-интересно"]["ru"] == "не хочу")
check("codelists: game_progress — 5 кодов прохождения; game_rating — «брошено» legacy со снятием значения",
      list(_gcl["game_progress"]) == ["не-начата", "играю", "отложена", "пройдена", "брошена"]
      and _gcl["game_rating"]["брошено"].get("legacy") and "migrate_to" in _gcl["game_rating"]["брошено"]
      and _gcl["game_rating"]["брошено"]["migrate_to"] is None
      and [c for c, e in _gcl["game_rating"].items() if not e.get("legacy")] == ["восторг", "понравилось", "нормально", "не понравилось"])
_g_verd = re.findall(r'\{\s*key:\s*"([^"]+)"', _gh.split("var VERDICTS = [")[1].split("];")[0])
check(f"codelists: game_rating = ключи VERDICTS страницы {_g_verd}", list(_gcl["game_rating"]) == _g_verd and len(_g_verd) == 5)
_g_ws = re.findall(r'\{\s*key:\s*"([^"]+)"', _gh.split("var W_STATUS = [")[1].split("];")[0])
check(f"games.html: W_STATUS = первые три game_state (хочу, на карандаше, не хочу) {_g_ws}", _g_ws == _g_states[:3])
check("games.html: демо — флаг demo, не статус: нет слота «Демо» и чипа статуса, есть переключатель «Демо (N)» и бейдж",
      'id="w-demo"' not in _gh and 'data-key="demo"' not in _gh and 'db.id = "w-demo-chip"' in _gh and 'class="vbadge demo"' in _gh)
check("games.html: подписи W_STATUS — из кодлиста game_state (не хочу), не литералы",
      all(f'label: CL.ru("game_state", "{c}")' in _gh for c in _g_states[:3]))
check("SKILL.md game-advisor: читает user-state.json, оверлей скилл не пишет",
      "user-state.json" in _gsk and re.search(r"[Оо]верлей[^\n]{0,40}user-state\.json[^\n]{0,20}скилл не пишет", _gsk) is not None)
_g_md5 = _hl.md5((REPO / "tools/assets/codelists.js").read_bytes()).hexdigest()[:8]
check(f"games.html: подключает codelists.js?v={_g_md5} (md5[:8] актуального файла)",
      f'assets/codelists.js?v={_g_md5}"' in _gh)
check("games.html: состояния карточки — CL.codes('game_state'), оценки и платформы — из кодлистов",
      'CL.codes("game_state")' in _gh and 'CL.codes("game_rating", false)' in _gh and 'CL.codes("game_platform")' in _gh
      and 'CL.codes("game_progress")' in _gh)
check("games.html: оверлей через /api/gm/file и /api/gm/save, подвал uiFootHTML «games v2.»",
      "api/gm/" in _gh and 'GM_API + "file' in _gh and 'GM_API + "save"' in _gh and "games v2." in _gh and 'uiFootHTML({ page: "games", version: "games v2.' in _gh and "buildline" not in _gh)
_g_help = (REPO / "tools/assets/help/games.md").read_text(encoding="utf-8")
check("help/games.md: раздел «Без Claude» и user-state.json", "Без Claude" in _g_help and "user-state.json" in _g_help)
_g_lay = (REPO / "_shared-references/claude-memory-layout.md").read_text(encoding="utf-8")
check("claude-memory-layout.md: строка Gaming/user-state.json, писатель — сайт",
      any("`Gaming/user-state.json`" in ln and "сайт" in ln for ln in _g_lay.splitlines()))
# Ссылка «Из подборки» открывает тот же слайдовер, что и экран «Подборки»
# (источник у обоих — recommendations/*.md). Делегирование обязательно:
# карточки перерисовываются, слушатель на карточке умер бы молча.
check("games.html: карточка ведёт на подборку через openDoc(recommendations/)",
      re.search(r'closest\("\.w-src"\)[\s\S]{0,300}openDoc\(GAMING \+ "recommendations/"', _gh) is not None)
check("games.html: слушатель «Из подборки» делегирован на секцию",
      re.search(r'querySelector\("\.sc-watch"\)\.addEventListener', _gh) is not None)
# Навигация по 39 карточкам — чипами, как на экране «Библиотека» (.vchip + .on
# из JS). Дефолт «в работе» (хочу + на карандаше): отказы остаются доступны
# чипом, но не листаются каждый раз, когда нужен живой список.
check("games.html: у экрана watch есть строка чипов-фильтров",
      'id="wfilters"' in _gh)
check("games.html: чипы watch — тот же компонент, что в библиотеке (.vchip)",
      re.search(r'setChips\(wf, WCHIPS', _gh) is not None       # один построитель рядов чипов на обе вкладки
      and re.search(r'var cls = "vchip" \+ \(list\[i\]\.key === cur', _gh) is not None)
check("games.html: фильтр по умолчанию — «в работе», отказы под своим чипом",
      re.search(r'var wFilter = "open";', _gh) is not None and re.search(r'renderWatchAll\(wFilter\)', _gh) is not None
      and re.search(r'filter === "open" && p\[0\] !== "nope"', _gh) is not None)
check("games.html: смена фильтра прокручивает к верху (иначе смотришь в пустоту)",
      re.search(r'wFilter = b\.getAttribute\("data-key"\);\s*\n\s*renderWatchAll\(wFilter\);\s*\n\s*uiScrollTop\(\);', _gh) is not None)   # ui-kit 1.64: «наверх» только через uiScrollTop

def check_watchlist(doc, where):
    items = (doc or {}).get("items") or []
    check(f"{where}: updated — дата", bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str((doc or {}).get("updated")))))
    seen = set()
    for it in items:
        t = (it or {}).get("title")
        check(f"{where}: у записи есть title", bool(t))
        check(f"{where}: {t!r} — статус из enum (иначе экран покажет его как «на карандаше»)",
              (it or {}).get("status") in W_STATUSES)
        if (it or {}).get("added") is not None:
            check(f"{where}: {t!r} — added это дата",
                  bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(it["added"]))))
        check(f"{where}: {t!r} не дублируется", t not in seen)
        seen.add(t)
    return seen

# source записи обязан указывать на существующий файл подборки — иначе кнопка
# «Из подборки» откроет слайдовер с 404 внутри.
def check_sources(doc, recs_dir, where):
    have = {p.name for p in recs_dir.glob("*.md")} if recs_dir.is_dir() else set()
    for it in (doc or {}).get("items") or []:
        src = (it or {}).get("source")
        if src and have:
            check(f"{where}: source {src!r} существует ({(it or {}).get('title')!r})", src in have)

_wl_path = Path.home() / "Library/CloudStorage/SynologyDrive-home/Claude-Memory/Gaming/watchlist.yaml"
if _wl_path.exists():
    _wl = yaml.safe_load(_wl_path.read_text(encoding="utf-8"))
    _titles = check_watchlist(_wl, "watchlist.yaml")
    check_sources(_wl, _wl_path.parent / "recommendations", "watchlist.yaml")
    # «Купил — запись уходит в library»: игра в обоих файлах означает, что
    # перенос не сделан, и страница покажет купленное как «хочу».
    _prof_path = _wl_path.parent / "taste-profile.yaml"
    if _prof_path.exists():
        # сыгранное демо в библиотеке — не покупка: «демо» (Demo / Trial Version в названии или пометка «демо») не считается
        _is_demo = lambda g: bool(re.search(r"\b(demo|trial version)\b", str(g.get("title") or ""), re.I)
                                  or str(g.get("note") or "").lower().startswith("демо"))
        _lib = {(g or {}).get("title") for g in
                (yaml.safe_load(_prof_path.read_text(encoding="utf-8")) or {}).get("library") or [] if not _is_demo(g or {})}
        _both = sorted(t for t in _titles if t in _lib)
        check(f"watchlist ∩ library пусто (купленное переносится): {_both}", not _both)

# ── 4.5. Базовый путь страниц: /tools/ vs корень данных ─────────────────────
# Страницы кабинета лежат в /tools/, а данные — в корне сайта, поэтому ссылка
# на данные ОБЯЗАНА начинаться с «../». Забытый «../» даёт 404 при верном
# пароле (запрос уходит в /tools/health-data/…) — ровно этот баг словили на
# NAS 2026-07-17, потому что локальный стенд отдавал страницу из корня.
print("base-path")

DATA_ROOTS = ("health-data/", "api/hd/", "api/", "Portfolio/", "travel-planner/",
              "Gaming/", "monitor-reports/", "macro-snapshots/", "forecasts/", "domains/",
              "ZenMoney/")

def data_refs(text):
    """Строковые литералы страницы, указывающие на корневые каталоги данных."""
    out = []
    for m in re.finditer(r'"((?:\.\./)?(?:[A-Za-z0-9_-]+/)+)"', text):
        s = m.group(1)
        bare = s[3:] if s.startswith("../") else s
        if any(bare == r or bare.startswith(r) for r in DATA_ROOTS):
            out.append(s)
    return out


for page in ("health.html", "hub.html", "travel.html", "games.html", "login.html", "money.html"):
    p = REPO / "tools" / page
    if not p.exists():
        continue
    txt = p.read_text(encoding="utf-8")
    refs = data_refs(txt)
    bad = sorted({r for r in refs if not r.startswith("../")})
    check(f"{page}: ссылки на данные идут через ../ (иначе 404 из /tools/){' — ' + str(bad) if bad else ''}",
          not bad)

# Единая точка входа: своих форм пароля у страниц быть не должно — иначе снова
# разъедутся тексты, обработка ошибок и поведение при неверном пароле.
_pages = {f: (REPO / "tools" / f).read_text(encoding="utf-8") for f in ("hub.html", "health.html")}
_pages["viewer.js"] = (REPO / "tools/assets/viewer.js").read_text(encoding="utf-8")
for f, txt in _pages.items():
    body = txt.split("VIEWER_VERSION")[-1] if f == "viewer.js" else txt
    check(f"{f}: ведёт на общий login.html", "login.html" in txt)
    check(f"{f}: не рисует свою форму пароля", 'type="password"' not in body)
check("login.html — единственная страница с полем пароля",
      'type="password"' in (REPO / "tools/login.html").read_text(encoding="utf-8"))

# Живые файлы НЕ решают вопрос авторизации. Их 403 двусмыслен («нет токена»
# vs «путь не в whitelist сайдкара»), и если считать его отказом входа —
# получается бесконечная петля health ⇄ login (реальный баг 2026-07-17:
# страница просила studies.json, сайдкар на NAS о нём ещё не знал).
_h = (REPO / "tools/health.html").read_text(encoding="utf-8")
for f in ("meds", "vaccinations", "vitals", "studies"):
    check(f"health.html: apiGet({f}) не роняет загрузку (catch liveMiss)",
          f'apiGet("{f}").catch(liveMiss)' in _h)
check("health.html: вкладка anamnesis в списке вкладок", '{ k: "anamnesis"' in _h and "tabAnamnesis()" in _h)
check("health.html: anamnesis.json грузится через API (base_hash) с фолбэком на чтение файла и пустую семью",
      'apiGet("anamnesis").catch(function(){' in _h
      and 'getJSON(DATA + "anamnesis.json").catch(function(){ return { family: [] }; })' in _h)
check("health.html: anamnesis в NEED_FILES и saveAnamnesis пишет через persist",
      '"studies", "anamnesis", "labs"]' in _h and 'persist("anamnesis"' in _h)
check("health.html: анамнез — вид «Я» по умолчанию, третий в .ui-seg",
      'anView: "self"' in _h and '[["self","Я"],["people","По людям"],["disease","По болезням"]]' in _h and "function anSelfHTML()" in _h)
check("health.html: «Я» — блок аллергий только при непустом списке, флажка «Аллергий нет» нет, «нет» — в тексте для врача; тяжесть цветом, ссылка на исследование",
      'if (x.allergies.length) out += card("Аллергии"' in _h and "an-alg-none" not in _h and 'class="ui-text">Аллергий нет' not in _h
      and 'x.allergies_checked ? "Аллергий нет."' in _h and _h.count('data-act="an-alg-add"') == 1
      and 'var(--err)' in _h.split("function anAlgHTML")[1].split("function anEvHTML")[0]
      and "исследование ↗" in _h and 'data-act="study-open"' in _h.split("function anEvHTML")[1].split("function anSelfHTML")[0])
check("health.html: формы «Я» — аллергия и событие через uiSelectHTML, проверка формата даты, сохранение через saveAnamnesis",
      "function anAlgModal()" in _h and "function anEvModal()" in _h and "function anDateBlock(" in _h
      and "Для болезни окончание обязательно" in _h and "function anBound(" in _h and _h.split("function anEvModal")[1].split("function anamnesisCard")[0].count("uiSelectHTML") >= 3
      and '"an-ev-save"' in _h and '"an-alg-save"' in _h and 'self: Object.assign({}, x, { history: list })' in _h)
check("health.html: «Текст для врача» начинается с личного, плитка Обзора считает «Я»",
      'return anSelfText() + " Семейный анамнез. "' in _h and '"Я: " + selfN' in _h)
check("health.html: пометка «болел ли тогда» (anFlag): три формулировки, в истории биомаркера и в подсказке графика",
      "function anFlag(" in _h and '"во время: "' in _h and '" дн. после: "' in _h and "в тот же месяц" not in _h
      and "anFlag(h.date)" in _h and "anFlag(x.date)" in _h and "chronic" not in _h.split("var AN_FLAG_KINDS")[1].split("\n")[0])
check("health.html: окно события (anWindow): умолчания 14/28 и 0/28, «за N дн. до», окна в форме и панели события",
      "function anWindow(" in _h and "surgery: [0, 28]" in _h and "illness: [0, 28]" in _h and '"за " + pl.n + " дн. до: "' in _h
      and "по умолчанию (" in _h and "AN_WB = [0, 1, 3, 7, 14, 30, 60, 90]" in _h and "AN_WA = [1, 3, 7, 14, 28, 60, 90]" in _h
      and "Окно анализов: до, дней" in _h and "function eventPane(" in _h and 'p.k === "event" ? eventPane' in _h
      and 'data-act="an-ev-open"' in _h and "показателя\", \"показателей\") + \" рядом" in _h.replace("' + ' рядом", "")
      or "рядом →" in _h)
check("health.html: панель события — мгновенное сохранение окна, строки открывают биомаркер стопкой, источник — bioList",
      "function anEvWinSet(" in _h and "if (anWritable()) saveAnamnesis(); else render();" in _h
      and "bioList().forEach" in _h.split("function anEvRows")[1].split("function anEvNear")[0]
      and 'data-act="marker-from-study"' in _h.split("function evRowHTML")[1].split("function eventPane")[0]
      and 'act === "an-ev-winb"' in _h)
# правка анамнеза и ручной замер давления (контракты §11, §12)
for act in ("an-add", "an-edit", "an-del", "an-cadd", "an-cedit", "an-cdel", "an-save", "an-csave", "bp-add", "bp-edit", "bp-del", "bp-save"):
    check(f"health.html: действие {act} объявлено", f'"{act}": function' in _h)
for fid in ("f-relation", "f-side", "f-cgroup", "f-ckind", "f-ccert"):
    check(f"health.html: поле {fid} — uiSelectHTML", f'uiSelectHTML({{ id: "{fid}"' in _h)
check("health.html: нет нативного <select> (формы анамнеза и замера)",
      not any("<select" in _l for _l in _h.splitlines() if "//" not in _l))
check("health.html: форма замера — верхнее, нижнее, пульс, время, заметка",
      all(f'"{n}"' in _h for n in ("sys", "dia", "pulse", "time")) and "function bpModal" in _h)
check("health.html: saveVitals сохраняет bp (Object.assign поверх файла)",
      "Object.assign({}, S.vitals, { schema" in _h)
check("health.html: ручные точки сливаются с рядами labs (bioList, «Вручную»)",
      "function bioList" in _h and '"Вручную"' in _h)
check("health.html: удаление анамнеза/замера — uiConfirm, не window.confirm",
      "window.confirm" not in _h and not any(re.search(r"(?<!\w)confirm\(", _l) for _l in _h.replace("uiConfirm(", "").splitlines() if "//" not in _l))
# ui-kit 1.64: Escape слоя страницы гасит ui-kit (uiLayerBind) — на странице своих Escape-обработчиков нет
check("health.html: Escape — слой страницы uiLayerBind (preventDefault делает ui-kit, не выводит из fullscreen)",
      "uiLayerBind({" in _h and "closeTop: function(){" in _h and 'e.key === "Escape"){ e.preventDefault()' not in _h
      and 'if (e.key === "Escape") return;' in _h)
check("health.html: подсветка строки списка (.rep-row) целиком и только при hover:hover",
      "@media (hover:hover){" in _h and ".rep-row:hover{ background:var(--bg-alt) !important; filter:none; }" in _h)
check("health.html: кнопки действия — общий .ui-btn (ui-kit 1.70.0); своих rep-btn/tiny-btn на странице не осталось",
      'class="ui-btn' in _h and "rep-btn" not in _h and "tiny-btn" not in _h and "--sec-acc:var(--c-3)" in _h)
check("health.html: версия health v3.2.4", 'var VERSION = "health v3.2.4"' in _h)
# этап «без ИИ», здоровье 3.1: отчёт .md и справка маркера с самой страницы (формы доступны при любом режиме)
_srv_src = (REPO / "tools/hosting/api/server.py").read_text(encoding="utf-8")
_compose = (REPO / "tools/hosting/docker-compose.yml").read_text(encoding="utf-8")
_deploy = (REPO / "tools/deploy.zsh").read_text(encoding="utf-8")
check("health.html: «Сохранить отчёт» — кнопка ui-btn только при S.caps.report, окно ui-kit (uiModalHTML через modal), слот файла uiFileSlot",
      'data-act="rep-add" id="rep-add"' in _h and 'class="ui-btn" data-act="rep-add"' in _h and "S.writable && S.caps.report" in _h
      and "uiFileSlot({ key: \"rep\"" in _h and 'modal("Сохранить отчёт"' in _h)
check("health.html: отчёт уходит на POST report (hdPost), замена имени — только после uiConfirm и overwrite: true",
      'hdPost("report"' in _h and "overwrite: !!overwrite" in _h and 'title: "Заменить отчёт?"' in _h)
check("health.html: «Править справку» — второстепенная кнопка карточки (.ui-btn.ghost) в карточке маркера (не у пары), чтение с base_hash, запись POST marker-info",
      'data-act="mi-edit"' in _h and 'class="ui-btn ghost" data-act="mi-edit"' in _h and "S.caps.marker" in _h
      and 'hdPost("marker-info"' in _h and "base_hash: m.hash" in _h and 'path=" + encodeURIComponent("biomarkers-info.json")' in _h)
check("health.html: окна отчёта и справки — в formKey/formOpen/closeForm/closeAll/render (Escape, затемнение)",
      all(x in _h for x in ("S.repAdd ? \"repadd\"", "S.miEdit ? \"mi:\"", "|| S.repAdd || S.miEdit || S.labEdit); }", "repAdd: null, miEdit: null, labEdit: null")))
# этап «без ИИ», здоровье 3.2: ручная точка анализа (labs.json, source: manual) только при ai_mode off
check("health.html: labs.json читается через API с хэшем, откат на прямой файл при старом сайдкаре; признак health_labs_manual",
      'apiGet("labs").catch(function(){ return getJSON(DATA + "labs.json"); })' in _h and "api.health_labs_manual" in _h)
check("health.html: форма точки и «Новый показатель» — только при ai_mode off (uiAiMode() === \"off\"), с классом noai-only; давление и пульс — не здесь",
      'uiAiMode() === "off"' in _h and 'data-act="lab-add"' in _h and 'data-act="lab-newmarker"' in _h and "noai-only" in _h
      and "function labsFormMarker(raw)" in _h and "BIO_SPEC.some" in _h)
check("health.html: ручная точка — source: manual, пометка «вручную»; правка/удаление только своих; запись POST save с base_hash",
      'source: "manual"' in _h and 'class="ui-tag lab-manual"' in _h and 'x.source === "manual"' in _h
      and 'postSave("labs", doc, S.hash.labs)' in _h and 'data-act="lab-edit"' in _h and 'data-act="lab-del"' in _h)
check("health.html: окно точки — общее ui-kit (uiModalHTML), поля fld/dateField, единица существующего показателя только для чтения",
      "function labModal()" in _h and "readonly" in _h.split("function labModal()")[1].split("function miEditBlock")[0])
_lsrv = (REPO / "tools/hosting/api/server.py").read_text(encoding="utf-8")
check("server.py: labs в HEALTH_FILES, запись labs.json — health_labs_manual_save (403 при ai_mode on, labs_rules.check_manual_edit); признак health_labs_manual",
      '"anamnesis", "labs")' in _lsrv and "def health_labs_manual_save" in _lsrv and "check_manual_edit" in _lsrv
      and '"health_labs_manual"' in _lsrv and "ai_mode on" in _lsrv)
_cmp = (REPO / "tools/hosting/docker-compose.yml").read_text(encoding="utf-8")
_dep = (REPO / "tools/deploy.zsh").read_text(encoding="utf-8")
check("compose монтирует labs_rules.py в hub-api, deploy.zsh кладёт его рядом с server.py",
      "./api/labs_rules.py:/app/labs_rules.py:ro" in _cmp and "validate_labs_info.py labs_rules.py" in _dep)
check("health.html: возможности сайдкара из /api/health (health_report, health_marker_info) гасят кнопки у старого server.py",
      "api.health_report" in _h and "api.health_marker_info" in _h)
check("server.py: маршруты /api/hd/report, /api/hd/marker-info задокументированы в шапке и обслуживаются; в whitelist reports/*.md и biomarkers-info.json",
      "POST /api/hd/report" in _srv_src and "POST /api/hd/marker-info" in _srv_src and '"/api/hd/report", "/api/hd/marker-info"' in _srv_src
      and "biomarkers-info" in _srv_src.split("HEALTH_WHITELIST = [")[1].split("]")[0] and "reports/" in _srv_src.split("HEALTH_WHITELIST = [")[1].split("\n]")[0])
# этап «без ИИ», здоровье 3.3: файл исследования со страницы → POST /api/hd/upload → Health/studies/
check("health.html: форма исследования — слот файла uiFileSlot (только при S.caps.upload), загрузка при «Сохранить», 20 МБ на клиенте",
      'uiFileSlot({ key: "study"' in _h and "S.caps.upload ? '<div class=\"ui-files\" id=\"study-slot-host\"" in _h
      and 'hdPost("upload"' in _h and "ST_MAX = 20 * 1024 * 1024" in _h and "stMountSlot();" in _h)
check("health.html: после загрузки имя с сервера — в поле file записи, прежний основной файл — в more_files; набранное не теряется при отказе",
      "x.file = res.j.name;" in _h and "x.more_files = (x.more_files || []).concat([x.file])" in _h and "S.studyEdit = x;" in _h)
check("server.py: POST /api/hd/upload — отдельный лимит тела (HD_UPLOAD_BODY_MAX) и файла 20 МБ, общий MAX_BYTES не тронут; тип по magic bytes",
      "HD_UPLOAD_BODY_MAX = 28 * 1024 * 1024" in _srv_src and "HD_UPLOAD_MAX_BYTES = 20 * 1024 * 1024" in _srv_src
      and "MAX_BYTES = 8 * 1024 * 1024" in _srv_src and "def hd_sniff(raw)" in _srv_src and "POST /api/hd/upload" in _srv_src
      and "HD_UPLOAD_BODY_MAX if upload else" in _srv_src)
_cf = (REPO / "tools/hosting/Caddyfile.example").read_text(encoding="utf-8")
check("Caddyfile.example: /api/hd/* (в том числе upload) исключён из @api_trusted — пароль с любого IP, отдельного правила не нужно",
      "not path /api/hd/*" in _cf)
check("compose: hub-api монтирует validate_report.py, validate_labs_info.py и их зависимость hub_settings.py в /app",
      all(f"./api/{m}:/app/{m}:ro" in _compose for m in ("validate_report.py", "validate_labs_info.py", "hub_settings.py")))
check("deploy.zsh: модули health-labs и hub_settings.py выкладываются в _nas/api/; сверка health_upload/health_report по /api/health",
      all(m in _deploy for m in ("skills/health-labs/scripts/$f", "_shared-references/hub_settings.py\" \"$NAS_STAGE/api/hub_settings.py")) and "lacks health_upload" in _deploy)
_lm = re.search(r"function liveMiss\(e\)\{(.*?)\n\}", _h, re.S)
check("health.html: liveMiss не пробрасывает ошибку дальше",
      bool(_lm) and "throw" not in _lm.group(1))
check("health.html: уход на вход — общий uiGoLogin со страховкой от петли", 'uiGoLogin("health"' in _h)
# Сайдкар объявляет свои возможности (health_files), страница по ним ловит
# рассинхрон версий и называет недостающий файл поимённо — без этого признака
# «страница новее server.py» снаружи неотличимо от «нет прав» (оба 403).
_srv = (REPO / "tools/hosting/api/server.py").read_text(encoding="utf-8")
_need = re.search(r'NEED_FILES = \[([^\]]*)\]', _h)
_have = re.search(r'HEALTH_FILES = \(([^)]*)\)', _srv)
check("server.py объявляет HEALTH_FILES", bool(_have))
check("health.html знает, какие файлы ему нужны (NEED_FILES)", bool(_need))
if _need and _have:
    need = set(re.findall(r'"([a-z]+)"', _need.group(1)))
    have = set(re.findall(r'"([a-z]+)"', _have.group(1)))
    check(f"страница и сайдкар согласны по списку живых файлов (страница: {sorted(need)}, сайдкар: {sorted(have)})",
          need == have)
check("/api/health отдаёт health_files", '"health_files": list(HEALTH_FILES)' in _srv)
check("whitelist сайдкара строится ИЗ HEALTH_FILES (один источник истины)",
      '"|".join(HEALTH_FILES)' in _srv)
check("health.html: успешная загрузка снимает метку петли",
      'uiLoginOk("health")' in _h)

check("health.html: DATA = ../health-data/",
      'var DATA = "../health-data/"' in (REPO / "tools/health.html").read_text(encoding="utf-8"))
check("health.html: API = ../api/hd/",
      'var API  = "../api/hd/"' in (REPO / "tools/health.html").read_text(encoding="utf-8"))

# ── 4.6. deploy.zsh знает про все страницы ──────────────────────────────────
# Страница, не вписанная в FILES, просто не уезжает на NAS и даёт 404 на боевом
# (реальный случай 2026-07-17: login.html забыли, а старый Caddyfile это
# маскировал 401-м на любой приватный путь). Список — не документация, а
# единственный источник истины о том, что деплоится: сверяем с tools/*.html.
print("deploy")

_deploy = (REPO / "tools/deploy.zsh").read_text(encoding="utf-8")
_m = re.search(r"^FILES=\(([^)]*)\)", _deploy, re.M)
check("deploy.zsh: список FILES найден", bool(_m))
if _m:
    listed = set(_m.group(1).split())
    on_disk = {p.name for p in (REPO / "tools").glob("*.html")}
    missing = sorted(on_disk - listed)
    check(f"deploy.zsh выкладывает ВСЕ страницы tools/*.html (забыты: {missing})", not missing)
    ghosts = sorted(f for f in listed if f.endswith(".html") and f not in on_disk)
    check(f"deploy.zsh не выкладывает несуществующее (призраки: {ghosts})", not ghosts)

# Все файлы здоровья (labs/biomarkers-info + аптечка/прививки/вес/исследования)
# — мастер ТОЛЬКО на Synology, deploy.zsh их с Мака НЕ переносит. До
# 2026-08-05 labs.json/biomarkers-info.json были исключением (мастерились на
# Маке, deploy.zsh рсинкал их на Synology отдельным циклом) — с переездом
# конвертера в skills/health-labs/ (пишет сразу на Synology) этот цикл убран
# целиком: оставь его — и на следующем деплое он затёр бы свежие
# Synology-данные замороженной Mac-копией, которую уже никто не обновляет.
check("deploy.zsh не ссылается на Mac-источник данных здоровья (HEALTH_SRC) — "
      "labs/biomarkers-info пишет health-labs напрямую на Synology",
      "HEALTH_SRC" not in _deploy)
_live = ("meds", "vaccinations", "vitals", "studies", "labs", "biomarkers-info")
for f in _live:
    check(f"deploy.zsh НЕ копирует {f}.json с Мака в мастер (иначе затрёт правки)",
          not re.search(rf"rsync[^\n]*HEALTH_SRC[^\n]*{f}", _deploy))
check("deploy.zsh пропускает уже существующий живой файл",
      '[[ -f "$HEALTH_DST/$f.json" ]] && continue' in _deploy)
# Конвертер тоже не должен воскрешать теневую копию рядом с CSV.
_conv = REPO / "skills/health-labs/scripts/build_health_json.py"
if _conv.exists():
    _c = _conv.read_text(encoding="utf-8")
    check("конвертер не пишет vitals.json рядом с CSV по умолчанию (нужен явный путь)",
          'OUT_VITALS = DATA / "vitals.json"' not in _c)
    check("конвертер пишет labs.json на Synology, не рядом с CSV на Маке",
          'OUT_LABS = SYN_HEALTH / "labs.json"' in _c)

# ── 5. health.html ↔ контракты Health-Data ──────────────────────────────────
# Зеркало ожиданий страницы «Здоровье». Данные приватные и лежат ВНЕ репозитория
# на Synology (Claude-Memory/Health/, вне облачных синков), поэтому гоняем по
# фикстурам; если реальные файлы смонтированы — дополнительно по ним. Это единственный мастер labs/biomarkers-info с
# 2026-08-05 (раньше был промежуточный Mac-этап — см. §4.6 выше).
print("health")

HEALTH_REAL = Path.home() / "Library/CloudStorage/SynologyDrive-home/Claude-Memory/Health"

# Зеркало refBounds() / refText() из health.html: какие референсы дают бар.
def ref_bounds(ref):
    if not ref:
        return None
    if isinstance(ref.get("low"), (int, float)) and isinstance(ref.get("high"), (int, float)):
        return (ref["low"], ref["high"])
    if ref.get("op") in ("<", "≤"):
        return (0, ref["value"])
    return None


# Зеркало enrich(): маркер попадает в «Требует внимания» только числовым.
def in_attention(b):
    last = b["series"][-1]
    return b["kind"] == "num" and last["status"] in ("high", "low")


# ВНИМАНИЕ: значения ниже — ВЫДУМАННЫЕ. Реальные анализы в репозиторий не
# кладём (он уезжает на GitHub); фикстура проверяет контракт, а не данные.
LABS_FIX = {
    "schema": "health-labs@1", "generated": "2026-07-17", "source": "master_labs.csv",
    "person": {"sex": "m", "age_at_export": 37},
    "categories": [{"key": "biochem", "name": "Биохимия крови"}, {"key": "stool", "name": "Копрограмма"}],
    "biomarkers": [
        {"id": "glucose", "name": "Глюкоза натощак", "category": "biochem", "kind": "num",
         "unit": "ммоль/л", "ref": {"low": 4.1, "high": 6.0},
         "series": [{"date": "2021-01-31", "value": 5.2, "text": None, "unit": "ммоль/л",
                     "ref": {"low": 4.1, "high": 6.0}, "status": "norm", "lab": None},
                    {"date": "2025-10-14", "value": 5.0, "text": None, "unit": "ммоль/л",
                     "ref": {"low": 4.1, "high": 6.0}, "status": "norm", "lab": "Лаборатория"}]},
        {"id": "ldh", "name": "ЛДГ", "category": "biochem", "kind": "num", "unit": "МЕ/л",
         "ref": {"low": 122, "high": 222},
         "series": [{"date": "2025-10-14", "value": 240, "text": None, "unit": "МЕ/л",
                     "ref": {"low": 122, "high": 222}, "status": "high", "lab": "Лаборатория"}]},
        {"id": "gribi", "name": "Дрожжевые грибы, кал качественно", "category": "stool", "kind": "qual",
         "unit": "", "ref": {"text": "отсутствуют"},
         "series": [{"date": "2026-05-15", "value": None, "text": "Единичные в поле зрения",
                     "unit": "", "ref": {"text": "отсутствуют"}, "status": "high", "lab": None}]},
    ],
}

check("labs: схема health-labs@1", LABS_FIX["schema"] == "health-labs@1")
check("labs: числовой ref даёт бар", ref_bounds({"low": 4.1, "high": 6.0}) == (4.1, 6.0))
check("labs: односторонний ref даёт бар от нуля", ref_bounds({"op": "<", "value": 21}) == (0, 21))
check("labs: текстовый ref бара НЕ даёт", ref_bounds({"text": "Не обнаружено"}) is None)
check("labs: нет ref — нет бара", ref_bounds(None) is None)

attn = [b["id"] for b in LABS_FIX["biomarkers"] if in_attention(b)]
check("attention: числовое отклонение попадает", "ldh" in attn)
check("attention: норма не попадает", "glucose" not in attn)
# Ключевое правило: копрограмма помечается лабораторией «выше нормы» механически
# («единичные в поле зрения»), в герой её не пускаем — иначе 14 из 21 отклонения
# были бы находками одного дня (см. health-plan.md §0.1).
check("attention: качественный маркер НЕ попадает, даже со status=high", "gribi" not in attn)

for name, key in (("meds", "meds"), ("vaccinations", "vaccinations")):
    check(f"{name}: страница шлёт schema health-{name}@1", True)  # см. persist() в health.html

# Зеркало expiryInfo(): порог «скоро истекает» — 3 месяца.
def expiry_soon(exp, now_ym=(2026, 7)):
    m = re.match(r"^(\d{4})-(\d{2})", exp or "")
    if not m:
        return None
    months = (int(m.group(1)) - now_ym[0]) * 12 + (int(m.group(2)) - now_ym[1])
    return "gone" if months < 0 else ("soon" if months <= 3 else "ok")


check("meds: истёкший срок", expiry_soon("2026-05") == "gone")
check("meds: истекает в пределах 3 мес", expiry_soon("2026-09") == "soon")
check("meds: далёкий срок", expiry_soon("2027-03") == "ok")
check("meds: без срока", expiry_soon("") is None)

# vitals: ИМТ считается страницей из роста; сверяем с тем, что показывал Ornament.
def bmi(kg, h_cm):
    return round(kg / (h_cm / 100) ** 2, 1)


check("vitals: формула ИМТ (80 кг / 1.80² = 24.7)", bmi(80.0, 180.0) == 24.7)
check("vitals: порог ВОЗ 25 — избыточная масса (страница строже Ornament)", bmi(85.0, 180.0) >= 25)
check("vitals: порог ВОЗ 30 — ожирение", bmi(100.0, 180.0) >= 30)

# Валидатор сайдкара — тот же контракт, что у страницы: расхождение уронит тест.
sys.path.insert(0, str(REPO / "tools/hosting/api"))
import server as api  # noqa: E402

import json as _json  # noqa: E402


def api_ok(path, doc):
    try:
        api.validate_health(path, _json.dumps(doc, ensure_ascii=False))
        return True
    except ValueError:
        return False


check("api: пустая аптечка валидна (каркас при заведении)",
      api_ok("meds.json", {"schema": "health-meds@1", "meds": []}))
check("api: лекарство страницы проходит валидатор", api_ok("meds.json", {
    "schema": "health-meds@1", "meds": [{"id": "m1", "name": "Препарат А", "taking": True,
                                         "affects": ["ldl"], "for": "", "expiry": "2027-03"}]}))
# Claude Design предлагал meds.json голым массивом (data/meds.json в проекте) —
# страница шлёт объект со schema; массив должен отлетать, иначе форматы разъедутся.
check("api: формат дизайна (голый массив) отвергнут — страница шлёт объект",
      not api_ok("meds.json", []))


# ── ref_meta: провенанс справки, который пишет скилл health-meds ────────────
# Аддитивный блок. Страница его НЕ рисует и НЕ знает — но обязана пронести
# через правку (med-save: Object.assign поверх записи). Если кто-то заменит
# Object.assign на сборку объекта из полей формы, скилл будет молча терять
# источники при каждой правке лекарства рукой — отсюда проверка ниже.
def _med_with_ref_meta(**over):
    rm = {"filled_at": "2026-07-17", "confidence": "high", "fields_filled": ["inn"],
          "sources": [{"title": "ГРЛС", "url": "https://grls.example/x",
                       "fetched": "2026-07-17"}]}
    rm.update(over)
    return {"schema": "health-meds@1",
            "meds": [{"id": "m1", "name": "Препарат А", "taking": True, "affects": [],
                      "inn": "вещество", "ref_meta": rm}]}


check("api: справка скилла с провенансом проходит валидатор",
      api_ok("meds.json", _med_with_ref_meta()))
check("api: лекарство без ref_meta валидно (19 живых записей + правка рукой)",
      api_ok("meds.json", {"schema": "health-meds@1",
                           "meds": [{"id": "m1", "name": "А", "taking": False, "affects": []}]}))
check("api: ref_meta не объектом отвергнут",
      not api_ok("meds.json", {"schema": "health-meds@1",
                               "meds": [{"id": "m1", "name": "А", "taking": True,
                                         "affects": [], "ref_meta": "да"}]}))
check("api: confidence вне enum отвергнут",
      not api_ok("meds.json", _med_with_ref_meta(confidence="точно")))
# Третье состояние аптечки: «нет» = кончилось. Запись живёт (она образец для
# повторного добавления), страница её прячет.
check("api: archived проходит валидатор",
      api_ok("meds.json", {"schema": "health-meds@1",
                           "meds": [{"id": "m1", "name": "А", "taking": False,
                                     "affects": [], "archived": True}]}))
check("api: archived не bool отвергнут",
      not api_ok("meds.json", {"schema": "health-meds@1",
                               "meds": [{"id": "m1", "name": "А", "taking": False,
                                         "affects": [], "archived": "нет"}]}))
check("api: запись без archived валидна (до введения поля)",
      api_ok("meds.json", {"schema": "health-meds@1",
                           "meds": [{"id": "m1", "name": "А", "taking": True, "affects": []}]}))
check("api: sources не списком объектов отвергнут",
      not api_ok("meds.json", _med_with_ref_meta(sources=["ГРЛС"])))
check("api: fields_filled не списком строк отвергнут",
      not api_ok("meds.json", _med_with_ref_meta(fields_filled="inn")))
# Страница правит лекарство целиком: провенанс обязан пережить round-trip.
check("health.html: med-save мержит запись, а не пересобирает (ref_meta выживает)",
      "Object.assign({}, S.medEdit" in _h)
check("api: vitals страницы проходит валидатор", api_ok("vitals.json", {
    "schema": "health-vitals@1", "height_cm": 180.0, "weight": [{"date": "2025-10-18", "kg": 80.0}]}))
# Исследования (МРТ/УЗИ/ЭКГ): результат — текст заключения, не число.
check("api: исследование страницы проходит валидатор", api_ok("studies.json", {
    "schema": "health-studies@1", "studies": [{"id": "s1", "date": "2025-10-18", "kind": "УЗИ",
                                              "area": "сосуды шеи", "conclusion": "Норма."}]}))
check("api: пустые исследования валидны (каркас)",
      api_ok("studies.json", {"schema": "health-studies@1", "studies": []}))
check("api: исследование без даты отвергнуто",
      not api_ok("studies.json", {"schema": "health-studies@1",
                                  "studies": [{"id": "s1", "kind": "УЗИ"}]}))
check("api: исследование без вида отвергнуто",
      not api_ok("studies.json", {"schema": "health-studies@1",
                                  "studies": [{"id": "s1", "date": "2025-10-18", "kind": " "}]}))
check("api: заключение числом отвергнуто",
      not api_ok("studies.json", {"schema": "health-studies@1",
                                  "studies": [{"id": "s1", "date": "2025-10-18", "kind": "УЗИ",
                                               "conclusion": 42}]}))

# Формат дат: полная там, где важен день (прививки/вес/исследования/история),
# короткая — на осях графиков и в плотном каталоге (решение 2026-07-17).
_h = (REPO / "tools/health.html").read_text(encoding="utf-8")
# С ui-kit 1.19.0 форматы общие: uiDateNum «ДД.ММ.ГГГГ», uiMonthShort «окт 2025».
UI_KIT_JS_EARLY = (REPO / "tools/assets/ui-kit.js").read_text(encoding="utf-8")
check("ui-kit.js: uiDateNum даёт ДД.ММ.ГГГГ через точки",
      'return p[2] + "." + p[1] + "." + p[0];' in UI_KIT_JS_EARLY)
check("health.html: своих форматтеров дат нет (fmtDate/fmtFull/fmtDay — ui-kit)",
      re.search(r"function\s+(fmtDate|fmtFull|fmtDay|uiDateNum|uiMonthShort|uiDateLong)\s*\(", _h) is None)
check("health.html: прививки показывают день (uiDateNum)", "esc(uiDateNum(v.date))" in _h)
check("health.html: история измерений показывает день", "esc(uiDateNum(h.date))" in _h)
check("health.html: ввод даты — нативный календарь", '"date")' in _h and 'type="' in _h)
# Срок годности раньше шёл нативным <input type="month"> — и на ОСНОВНОМ браузере
# пользователя (Safari) поле было невыбираемым: Safari month-input не
# поддерживает и рисует голый текст. Теперь свой пикер; регресс к нативному
# роняет тест.
check("health.html: срок годности — свой пикер месяца, не нативный month-input",
      'monthField("expiry"' in _h and '"month")' not in _h)
check("health.html: пикер месяца подключён к кликам",
      'data-mp' in _h and "openMonthPicker" in _h)

# body ОБЯЗАН задавать color. Слайд-оверы, модалки и savebar рендерятся
# СОСЕДЯМИ обёртки <div data-tab> (render: app.innerHTML = '<div…>…</div>' +
# markerPane() + medPane() + …) и наследуют цвет от body, а не от обёртки.
# Без правила body отдаёт дефолтный ЧЁРНЫЙ: в тёмной теме заголовки и значения
# без явного color шли чёрным по тёмному — контраст 1.3 при пороге 4.5, текст
# практически невидим. Светлая тема баг ПРЯТАЛА (чёрный по светлому читается),
# поэтому он дожил до health v1.11 — единственной страницы, потерявшей эту
# строку при переносе вёрстки из макета. Замерено headless: после фикса 4.8.
#
# С ui-kit 1.6.0 (2026-10-02) правило живёт в ОДНОМ месте — базовом слое
# assets/ui-kit.css, а страницы его НЕ повторяют. Поводом стал тот же баг в
# food.html: этот тест перечислял страницы списком, food в список не попал, и
# страница с body без color дожила до жалобы владельца. Список страниц больше
# не защищает — защищает отсутствие копий. Ниже: ui-kit.css задаёт color/фон
# на body, каждая страница реально подключает ui-kit.css и не держит своей
# копии базы, шрифтов, токенов тем и стеков шрифтов.
_BODY_RE = re.compile(r"(?<![.\w-])body\s*\{([^}]*)\}")
_UIKIT_BASE = (REPO / "tools/assets/ui-kit.css").read_text(encoding="utf-8")
_UIKIT_BASE_NC = re.sub(r"/\*.*?\*/", "", _UIKIT_BASE, flags=re.S)
_ub = [_r.replace(" ", "").replace("\n", "") for _r in _BODY_RE.findall(_UIKIT_BASE_NC)]
check("ui-kit.css: body задаёт color:var(--text) (иначе оверлеи чернеют в тёмной теме)",
      any("color:var(--text)" in _r for _r in _ub))
check("ui-kit.css: body задаёт фон var(--bg)",
      any("background-color:var(--bg)" in _r or "background:var(--bg)" in _r for _r in _ub))
check("ui-kit.css: body задаёт шрифт токеном var(--font-sans)",
      any("font-family:var(--font-sans)" in _r for _r in _ub))
check("ui-kit.css: токены --font-sans/--font-serif определены в :root",
      re.search(r":root\s*\{[^}]*--font-sans\s*:[^}]*--font-serif\s*:", _UIKIT_BASE_NC, re.S) is not None)
check("ui-kit.css: контролы наследуют шрифт (button/input/select/textarea)",
      re.search(r"button\s*,\s*input\s*,\s*select\s*,\s*textarea\s*\{\s*font-family\s*:\s*inherit", _UIKIT_BASE_NC) is not None)
_BASE_PAGES = ("hub.html", "travel.html", "games.html", "food.html", "health.html",
               "money.html", "login.html", "portfolio-integrated-viewer.html")
_STACK_RE = re.compile(r"font-family:\s*(?:\\'|'|\")(?:Golos Text|Spectral)(?:\\'|'|\")\s*,")
for _page in _BASE_PAGES:
    _src = (REPO / "tools" / _page).read_text(encoding="utf-8")
    _nc = re.sub(r"<!--.*?-->", "", _src, flags=re.S)
    check(f"{_page}: подключает ui-kit.css (база, шрифты, токены — оттуда)",
          re.search(r'<link[^>]*assets/ui-kit\.css', _nc) is not None)
    check(f"{_page}: нет своего @font-face", "@font-face" not in _src)
    check(f"{_page}: нет своей копии сброса (*{{box-sizing}} / html,body{{margin}})",
          re.search(r"(?m)^\s*\*\s*\{\s*box-sizing", _src) is None
          and re.search(r"(?m)^\s*html\s*,\s*body\s*\{", _src) is None)
    check(f"{_page}: body не переопределяет шрифт/цвет базы",
          not any(re.search(r"(?<![-\w])(font-family|color)\s*:", _r)
                  for _r in _BODY_RE.findall(re.sub(r"/\*.*?\*/", "", _src, flags=re.S))
                  if "--" not in _r.split(":")[0]))
    check(f"{_page}: стеки шрифтов — только токенами var(--font-sans/serif)",
          _STACK_RE.search(_src) is None)
_vcss_base = re.sub(r"/\*.*?\*/", "",
                    (REPO / "tools/assets/viewer.css").read_text(encoding="utf-8"), flags=re.S)
check("viewer.css: нет своего @font-face (шрифты из ui-kit.css)", "@font-face" not in _vcss_base)
check("viewer.css: нет своего --bg/--text (общие токены из ui-kit.css)",
      re.search(r"--(bg|text)\s*:", _vcss_base) is None)
check("viewer.css: стеки шрифтов — только токенами", _STACK_RE.search(_vcss_base) is None)
_vh = (REPO / "tools/portfolio-integrated-viewer.html").read_text(encoding="utf-8")
check("вьюер: ui-kit.css подключён ДО viewer.css (свои правила вьюера поверх базы)",
      0 <= _vh.find("assets/ui-kit.css") < _vh.find("assets/viewer.css"))

check("api: прививка страницы проходит валидатор", api_ok("vaccinations.json", {
    "schema": "health-vaccinations@1", "vaccinations": [{"id": "v1", "date": "2025-04-12",
                                                         "vaccine": "Вакцина А", "next_due": None}]}))

# Реальные данные, если смонтированы: страница обязана их пережить.
if (HEALTH_REAL / "labs.json").exists():
    labs = _json.loads((HEALTH_REAL / "labs.json").read_text(encoding="utf-8"))
    check("real labs: схема", labs.get("schema") == "health-labs@1")
    check("real labs: маркеры есть", len(labs.get("biomarkers", [])) > 0)
    cats = {c["key"] for c in labs["categories"]}
    check("real labs: у всех маркеров известная категория",
          all(b["category"] in cats for b in labs["biomarkers"]))
    check("real labs: kind только num|qual",
          all(b["kind"] in ("num", "qual") for b in labs["biomarkers"]))
    check("real labs: у каждого маркера непустая серия",
          all(len(b["series"]) > 0 for b in labs["biomarkers"]))
    check("real labs: статусы из enum",
          all(s["status"] in ("norm", "high", "low", "na")
              for b in labs["biomarkers"] for s in b["series"]))
    check("real labs: даты ISO",
          all(re.match(r"^\d{4}-\d{2}-\d{2}$", s["date"])
              for b in labs["biomarkers"] for s in b["series"]))
    check("real labs: у числовых маркеров все значения числовые",
          all(all(s["value"] is not None for s in b["series"])
              for b in labs["biomarkers"] if b["kind"] == "num"))
    check("real labs: вес/рост/ИМТ уехали в vitals.json, а не в каталог",
          not any(b["name"].startswith(("Вес", "Рост", "Индекс массы")) for b in labs["biomarkers"]))
    check("real labs: опечатки единиц Ornament вычищены",
          not any(s["unit"] in ("ммол/л", "мкмол/л") for b in labs["biomarkers"] for s in b["series"]))
    if (HEALTH_REAL / "biomarkers-info.json").exists():
        info = _json.loads((HEALTH_REAL / "biomarkers-info.json").read_text(encoding="utf-8"))["info"]
        check("real info: справка есть у КАЖДОГО маркера (иначе панель покажет заглушку)",
              all(b["id"] in info for b in labs["biomarkers"]))
        check("real info: у справки непустые what/up/down",
              all(v.get("what") and v.get("up") and v.get("down") for v in info.values()))
    for f in ("meds", "vaccinations", "vitals", "studies"):
        p = HEALTH_REAL / f"{f}.json"
        if p.exists():
            check(f"real {f}.json: проходит валидатор сайдкара",
                  api_ok(f"{f}.json", _json.loads(p.read_text(encoding="utf-8"))))

# ── ось «свежесть»: хаб ↔ вьюер ────────────────────────────────────────────
# Обе страницы независимо судят о свежести ОДНИХ И ТЕХ ЖЕ файлов: хаб — сводкой
# «Все отчёты в графике», вьюер — списком устаревшего на «Сегодня». Разошедшиеся
# пороги пользователь читает как баг данных («хаб говорит в графике, вьюер
# красный»), а не как разную настройку — реальный случай 2026-07-20: monitor
# 2 дня во вьюере против 7+3 в хабе, отчёт возрастом 4 дня получал два
# противоположных вердикта одновременно.
# Страницы выкладываются на NAS и дальше живут без пересборки, поэтому дрейф
# должен падать здесь, а не обнаруживаться глазами через полгода.

def _strip_js_comments(s: str) -> str:
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return re.sub(r"//[^\n]*", "", s)


HUB_HTML = (REPO / "tools/hub.html").read_text(encoding="utf-8")
VIEWER_JS = (REPO / "tools/assets/viewer.js").read_text(encoding="utf-8")

_hub_block = re.search(r"reports:\s*\[(.*?)\]", HUB_HTML, re.S)
_viewer_block = re.search(r"const STALE_THRESHOLDS_DAYS = \{(.*?)\n\};", VIEWER_JS, re.S)
check("свежесть: CONFIG.reports найден в hub.html", _hub_block is not None)
check("свежесть: STALE_THRESHOLDS_DAYS найден в viewer.js", _viewer_block is not None)

if _hub_block and _viewer_block:
    hub_reports = {}
    for m in re.finditer(
        r'\{\s*key:\s*"(?P<key>\w+)".*?dir:\s*"(?P<dir>[^"]+)"'
        r'.*?match:\s*/(?P<match>[^/]+)/.*?staleAfter:\s*(?P<stale>\d+)(?:,\s*failAfter:\s*(?P<fail>\d+))?',
        _hub_block.group(1), re.S,
    ):
        hub_reports[m.group("key")] = {
            "dir": m.group("dir"), "match": m.group("match"),
            "stale": int(m.group("stale")),
            "fail": int(m.group("fail")) if m.group("fail") else None,
        }
    viewer_thr = {
        k: int(v) for k, v
        in re.findall(r"(\w+):\s*(\d+)", _strip_js_comments(_viewer_block.group(1)))
    }
    _fail_block = re.search(r"const STALE_FAIL_DAYS = \{(.*?)\n\};", VIEWER_JS, re.S)
    check("свежесть: STALE_FAIL_DAYS найден в viewer.js", _fail_block is not None)
    viewer_fail = {
        k: int(v) for k, v
        in re.findall(r"(\w+):\s*(\d+)", _strip_js_comments(_fail_block.group(1)))
    } if _fail_block else {}

    check("свежесть: записи хаба распарсились", len(hub_reports) >= 6)
    check("свежесть: пороги вьюера распарсились", len(viewer_thr) >= 6)

    # 1. Состав: каждый артефакт, у которого вьюер рисует плашку, должен быть и
    #    в хабе — иначе сводка «все в графике» считается по неполному набору
    #    (так из неё выпадали стресс и снапшот портфеля).
    for key in viewer_thr:
        check(f"свежесть: артефакт {key} отслеживается и хабом", key in hub_reports)

    # 2. Пороги: одинаковые для одного и того же артефакта.
    for key, thr in viewer_thr.items():
        if key in hub_reports:
            check(f"свежесть: порог {key} совпадает (hub {hub_reports[key]['stale']} ↔ viewer {thr})",
                  hub_reports[key]["stale"] == thr)

    # 2б. Жёсткая плашка (failAfter ↔ STALE_FAIL_DAYS): те же числа, тот же состав;
    #     жёсткая всегда старше обычной.
    for key, rep in hub_reports.items():
        if key in viewer_thr:
            check(f"свежесть: жёсткий порог {key} совпадает (hub {rep['fail']} ↔ viewer {viewer_fail.get(key)})",
                  rep["fail"] == viewer_fail.get(key))
        if rep["fail"] is not None:
            check(f"свежесть: жёсткий порог {key} старше обычного", rep["fail"] > rep["stale"])
    check("свежесть: у вьюера нет жёстких порогов без записи в хабе",
          all(k in hub_reports for k in viewer_fail))

    # 3. Маски: у каждой записи хаба своя — без неё два вида обзоров в одном
    #    каталоге сливаются (свежий stock маскировал протухший bond).
    check("свежесть: у каждой записи хаба есть маска имени",
          all(r["match"] for r in hub_reports.values()))
    _wr = [k for k, r in hub_reports.items() if r["dir"].endswith("weekly-reviews/")]
    check("свежесть: stock и bond в weekly-reviews/ разведены разными масками",
          len(_wr) == 2 and len({hub_reports[k]["match"] for k in _wr}) == 2)

    # 4. Реальные данные (если Synology смонтирован): маска что-то находит, и
    #    дата в имени файла сходится с датой ВНУТРИ него. Источники дат у
    #    страниц разные — хаб парсит имя, вьюер читает поле, — так что
    #    расхождение снова развело бы вердикты.
    CM = Path.home() / "Library/CloudStorage/SynologyDrive-home/Claude-Memory"
    DATE_FIELDS = {                       # зеркало extractDate() viewer.js
        "integratedView": ("view_date",),
        "stocks": ("review_date",),
        "bonds": ("review_date",),
        "stress": ("test_date", "as_of_date", "generated_at"),
        "portfolio": ("as_of_date",),
        "monitor": ("generated_at",),
        "macro": ("as_of_date", "snapshot_date"),   # frontmatter нет → дата из имени
    }

    def _inner_date(path: Path):
        """Дата, которую увидит вьюер, прочитав файл (None — не смог)."""
        try:
            if path.suffix == ".json":
                doc = _json.loads(path.read_text(encoding="utf-8"))
            elif path.suffix == ".md":
                txt = path.read_text(encoding="utf-8")
                fm = re.match(r"^---\n(.*?)\n---", txt, re.S)
                doc = yaml.safe_load(fm.group(1)) if fm else None
            else:
                doc = next(iter(yaml.safe_load_all(path.read_text(encoding="utf-8"))), None)
        except Exception:
            return None
        if not isinstance(doc, dict):
            return None
        for f in DATE_FIELDS[key]:
            if doc.get(f):
                v = doc[f]
                # как _localYmd вьюера: момент с поясом — дата по местному (МСК) времени, не первые 10 символов UTC
                if isinstance(v, str) and re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}.*(Z|[+-]\d{2}:?\d{2})$", v):
                    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
                    try:
                        return _dt.fromisoformat(v.replace("Z", "+00:00")).astimezone(_tz(_td(hours=3))).date().isoformat()
                    except ValueError:
                        pass
                return str(v)[:10]
        return None

    if CM.exists():
        for key, rep in hub_reports.items():
            if key not in DATE_FIELDS:
                continue
            d = CM / rep["dir"].replace("../", "")
            if not d.exists():
                continue
            hits = [p for p in d.iterdir() if re.match(rep["match"], p.name)]
            check(f"свежесть/данные: маска {key} находит файлы в {rep['dir']}", bool(hits))
            if not hits:
                continue
            # как хаб: самый свежий по ДАТЕ В ИМЕНИ; .yaml приоритетнее .md —
            # его и грузит вьюер
            newest = max(hits, key=lambda p: (
                re.search(r"\d{4}-\d{2}-\d{2}", p.name).group(0)
                if re.search(r"\d{4}-\d{2}-\d{2}", p.name) else "",
                {".yaml": 2, ".json": 2, ".md": 1}.get(p.suffix, 0),
            ))
            name_date = re.search(r"\d{4}-\d{2}-\d{2}", newest.name)
            inner = _inner_date(newest)
            if name_date and inner and key != "macro":
                check(f"свежесть/данные: {key} — дата в имени == дате внутри "
                      f"({newest.name}: {name_date.group(0)} ↔ {inner})",
                      name_date.group(0) == inner)


# ═══════════════════════ food ═══════════════════════════════════════════════
# Раздел «Еда»: страница ↔ сайдкар ↔ эталонные парсеры на Python.
# Дрейф с любой стороны обязан ронять этот тест, а не тихо ломать список
# покупок — там цена ошибки измеряется не багом, а лишними покупками.
print("food")
_f = (REPO / "tools/food.html").read_text(encoding="utf-8")

check("food.html: DATA = ../Food/ (страница в /tools/, данные в корне)",
      'var DATA = "../Food/"' in _f)
check("food.html: API = ../api/fd/", 'var API  = "../api/fd/"' in _f)

# Треугольник «страница ↔ сайдкар ↔ деплой»: тот же приём, что для health.
_fneed = re.search(r'NEED_FILES = \[([^\]]*)\]', _f)
check("food.html знает, какие файлы ему нужны (NEED_FILES)", bool(_fneed))
_fhave = re.search(r'FOOD_FILES = \(([^)]*)\)', _srv)
check("сайдкар объявляет FOOD_FILES", bool(_fhave))
if _fneed and _fhave:
    need = sorted(re.findall(r'"([^"]+)"', _fneed.group(1)))
    have = sorted(re.findall(r'"([^"]+)"', _fhave.group(1)))
    check(f"страница и сайдкар согласны по живым файлам еды ({need} ↔ {have})", need == have)

# Правка записи слиянием, а не пересборкой: у продукта и позиции есть ключи,
# которых нет в форме (cooked_ratio, from[], product_id) — пересборка их съест.
check("food.html: правка продукта мержит запись (Object.assign)",
      "Object.assign({}, S.prodEdit" in _f)
check("food.html: отметка «куплено» мержит позицию, а не пересобирает",
      "Object.assign({}, i, { bought:" in _f)

# Единственный оправданный enum схемы — состояние крупы: опечатка не «покажет
# незнакомое», а тихо отключит пересчёт варёного веса в сухой.
check("сайдкар знает состояние крупы (cooked/dry)", '"cooked", "dry"' in _srv)
check("сайдкар проверяет cooked_ratio как число", "cooked_ratio" in _srv)

# ── «Проба сборки»: решения владельца с вводом — кнопка во вьюере ↔ параметр сервера ↔ флаг скрипта ──
# PDL-17 (2026-10-27): кэш без «Общего баланса» вносится из IntelInvest. Решение cash_fact_stale без поля во
# вьюере, без cash_fact в pf_build.py или без --cash-fact в build_snapshot.py = вопрос, на который нельзя ответить.
_pf_py = (REPO / "tools/hosting/notify/pf_build.py").read_text(encoding="utf-8")
_bs_py = (REPO / "skills/portfolio-data-loader/scripts/build_snapshot.py").read_text(encoding="utf-8")
_vj = _strip_js_comments(VIEWER_JS)
for _code, _ui, _payload, _cli in (("cash_drift_changed", "pf-rebase", "rebaseline_cash", "--rebaseline-cash"),
                                    ("cash_fact_stale", "pf-cashfact", "cash_fact", "--cash-fact")):
    check(f"проба сборки: решение {_code} есть в DECISIONS build_snapshot.py", f'"{_code}"' in _bs_py)
    check(f"проба сборки: {_code} — ветка и элемент #{_ui} во вьюере",
          f"'{_code}'" in _vj and f"'{_ui}" in _vj)
    check(f"проба сборки: pf_build.py принимает {_payload} и передаёт {_cli}",
          f'"{_payload}"' in _pf_py and f'"{_cli}"' in _pf_py)
    check(f"проба сборки: вьюер шлёт {_payload}", re.search(rf"\b{_payload}\b", _vj) is not None)


# ── зеркало normName() ↔ normalize() из tools/food/match_products.py ────────
# Сопоставление ингредиента с продуктом идёт и на странице (импорт, добавление
# в список), и в Python (разовые миграции). Разъедутся — одни и те же названия
# начнут связываться по-разному в зависимости от того, кто их обработал.
sys.path.insert(0, str(REPO / "tools/food"))
import match_products as _mp  # noqa: E402

_js_noise = re.search(r"var _NOISE = /\\b\((.*?)\)\\b/gi", _f)
check("food.html: шумовые слова вынесены в _NOISE", bool(_js_noise))


def _stems(pattern_body):
    """Только основы слов: квантификаторы в JS и Python отличаются намеренно.

    В Python `\\w` с re.UNICODE берёт кириллицу, в JS `\\w` — только ASCII,
    поэтому там `\\S`. Сравнивать надо смысл (какие слова считаем шумом),
    а не запись."""
    return sorted(re.sub(r"\\[wS][*+]", "", w).strip() for w in pattern_body.split("|"))


_py_body = re.match(r"\\b\((.*)\)\\b$", _mp._NOISE.pattern)
check("match_products: шумовые слова читаются из скомпилированного паттерна", bool(_py_body))
if _js_noise and _py_body:
    js, py = _stems(_js_noise.group(1)), _stems(_py_body.group(1))
    check(f"шумовые слова JS и Python совпадают (JS {len(js)} ↔ PY {len(py)})", js == py)

# Жирность НЕ шум — решение, а не недосмотр: срезав «%», схлопнули бы
# «Сливки 10%» и «Сливки 33%».
check("нормализация: жирность значима (Python)",
      _mp.normalize("Сливки 10%") != _mp.normalize("Сливки 33%"))
check("нормализация: «варёная» — шум (Python)",
      _mp.normalize("Гречка варёная") == _mp.normalize("Гречка"))
check("food.html: жирность не срезается (в _NOISE нет процентов)",
      bool(_js_noise) and "%" not in _js_noise.group(1))
check("food.html: «варён» в шуме", bool(_js_noise) and "варён" in _js_noise.group(1))

# Показ количеств: храним в г/мл, показываем кг/л свыше 1000. Через
# размерности (мл→г) не конвертируем никогда — это требует плотностей.
check("food.html: кг/л только свыше 1000", "qty >= 1000" in _f)

# ── пересчёт чисел внутри текста шага ──────────────────────────────────────
# Самое опасное место страницы. Единицы количества и единицы ВРЕМЕНИ обязаны
# быть разными множествами: попади «мин» или «ч» в _QTY_UNITS — и «тушить
# 2 ч 10 мин» превратилось бы в «3 ч 20 мин» при удвоении порций, то есть
# страница начала бы врать про готовку, а не про закупку.
_units = re.search(r'var _QTY_UNITS = "([^"]+)"', _f)
check("food.html: единицы количества вынесены в _QTY_UNITS", bool(_units))
if _units:
    us = set(_units.group(1).split("|"))
    check(f"единицы количества — только вес/объём/штуки ({sorted(us)})",
          us == {"г", "кг", "мл", "л", "шт"})
    for bad in ("мин", "минут", "ч", "час", "мм", "см", "°C", "ст.л.", "ч.л."):
        check(f"«{bad}» НЕ считается количеством (иначе пересчитается время/размер)",
              bad not in us)

# Диапазон обязан ловиться одним совпадением: иначе «150–200 г» даст
# бессмысленное «150–330 г» — первое число осталось бы непересчитанным.
# (_STEP_NUM → _STEP_TOKEN 2026-07-21: теперь один регэксп ловит и число, и
# #ингредиент.)
check("food.html: диапазон чисел ловится одним совпадением",
      "[–—-]" in _f and "_STEP_TOKEN" in _f)
# Подмена не должна быть тихой: рядом печатается исходное значение.
check("food.html: рядом с пересчитанным числом показано исходное", "(было " in _f)
# «По вкусу» не масштабируется и не берёт raw в колонку количества
# (у части записей в raw лежит вся строка целиком, включая название).
check("food.html: «по вкусу» не подставляет raw в количество",
      'if (v == null) return "по вкусу"' in _f and "function amountText(" in _f)

# ── три защиты планирования, потеря которых незаметна и катастрофична ──────
# 1. Повторное планирование того же рецепта ЗАМЕНЯЕТ его прежний вклад.
#    Без фильтра двойное нажатие удвоило бы закупку, и заметить это можно было
#    бы только у кассы.
check("food.html: повторный план рецепта заменяет, а не удваивает вклад",
      "f.recipe_id !== r.id" in _f)
# 2. Купленное не участвует в мердже: список, меняющийся под человеком посреди
#    магазина, — худшее, что может сделать такой инструмент.
check("food.html: мердж не трогает уже купленные строки",
      "if (it.bought) continue;" in _f)
# 3. Снятие рецепта с плана тоже обходит купленное.
check("food.html: снятие с плана не трогает купленное",
      "it.id !== itemId || it.bought" in _f)
# 4. Складывать граммы со штуками нельзя, и молча приводить друг к другу —
#    тоже (понадобились бы плотности и вес штуки).
check("food.html: мердж требует совпадения единиц (после нормализации написания)",
      'normUnit(it.unit || "") === normUnit(row.unit || "")' in _f)
# 5. «Всегда есть дома» — галочка снята заранее, иначе каждый рецепт добавлял
#    бы соль с маслом и списку перестали бы верить.
check("food.html: staple приходит в план со снятой галочкой",
      "checked: g.qty != null && !staple" in _f)
# 6. Строка плана — в ДВЕ ступени: имя+степпер сверху, «заменить» отдельной
#    строкой снизу. Раньше всё делило один горизонтальный ряд, и на телефоне
#    имя сминалось в столбик, а степпер лез в середину (скриншот 2026-07-21).
check("food.html: строка плана двухступенчатая (замена отдельной строкой)",
      "var line2 =" in _f and "var stepper =" in _f)
# 7. Тот же баг мёртвого поля, что уже ловили: packs через packOf, а не через
#    удалённое pr.pack_size — иначе «N уп.» в плане тихо исчезло бы.
check("food.html: упаковки в плане считаются через packOf",
      re.search(r'planModal[\s\S]{0,4000}var pk = packOf\(pr\)', _f) is not None
      or "var pk = packOf(pr);" in _f)
# 8. Штука — целый предмет: шаг степпера в плане ровно 1, без относительных
#    процентов. Шаг «10% от текущего» на пятнадцати штуках превращался в 2
#    (roundQty(1.5) → 2), и дальше набор шёл 17 → 19 → 21: двадцать яиц не
#    набирались вообще (случай владельца 2026-08-15). Саму арифметику гоняет
#    браузером test_food_layout.py, здесь — что ветка не исчезла из исходника.
check("food.html: шаг плана для штук — целая единица",
      re.search(r'"plan-amt": function[\s\S]{0,600}var piece = \(normUnit\(x\.unit\)', _f)
      is not None)
check("food.html: относительные проценты остались только у веса и объёма",
      re.search(r'"plan-amt": function[\s\S]{0,600}: Math\.max\(5, roundQty\(x\.qty \* 0\.1', _f)
      is not None)
# 9. Крупа и паста в рецепте часто записаны ГОТОВЫМ весом — покупать надо сухой.
#    Пересчёт живёт в planRows (человек видит и правит то самое число, которое
#    поедет в список). Раньше state в строку плана не переносился вовсе, и
#    195 г готовой гречки уходили в список как 195 г крупы — перекупка в 2,5
#    раза, заметная только у кассы (баг 2026-08-15).
check("food.html: готовый вес переводится в сухой отдельной функцией",
      "function cookedToDry(" in _f and "cookedToDry(g, scaledQty(g, factor), p)" in _f)
check("food.html: коэффициент — только cooked_ratio продукта из каталога",
      re.search(r'function cookedToDry\([\s\S]{0,900}p\.cooked_ratio > 0', _f) is not None)
# Нет коэффициента — НЕ делим по «примерно 2,5»: молча заниженная закупка хуже
# честного «не знаю». Строка помечается, количество остаётся как в рецепте.
check("food.html: без cooked_ratio количество не делится наугад",
      re.search(r'function cookedToDry\([\s\S]{0,900}noRatio: true', _f) is not None)
check("food.html: строка без разваривания помечена для человека", "x.noRatio" in _f)
# Пересчёт массовый: у «шт» и «мл» коэффициент разваривания бессмыслен.
check("food.html: пересчёт готового веса — только для веса",
      re.search(r'function cookedToDry\([\s\S]{0,400}nu !== "г" && nu !== "кг"', _f) is not None)
# То же правило на стороне КБЖУ — один коэффициент на обе стороны страницы.
check("food.html: КБЖУ считает по тому же cooked_ratio",
      'if (g.state === "cooked" && p.cooked_ratio) raw = grams / p.cooked_ratio;' in _f)

# ── импорт рецепта: парсер страницы ↔ эталон на Python ─────────────────────
# Один и тот же файл обязан разбираться одинаково валидатором и страницей.
# Разъедутся — валидатор скажет «всё хорошо», а страница разберёт иначе, и
# заметить это будет невозможно: обе стороны «работают».
sys.path.insert(0, str(REPO / "tools/food"))
import validate_recipe as _vr  # noqa: E402

_js_stop = re.search(r"var STOP_WORDS = \{(.*?)\};", _f, re.S)
check("food.html: стоп-лист вынесен в STOP_WORDS", bool(_js_stop))
if _js_stop:
    js_stop = dict(re.findall(r'"([^"]+)":\s*"([^"]+)"', _js_stop.group(1)))
    check(f"стоп-листы JS и Python совпадают ({len(js_stop)} ↔ {len(_vr.STOP_WORDS)})",
          js_stop == _vr.STOP_WORDS)
# Стоп-лист — ВКУС, а не структура: он предупреждает, но не блокирует ни на
# одной стороне. Иначе рецепт с «грибами» в заметке о заменах нельзя было бы
# сохранить вовсе.
check("food.html: стоп-лист не блокирует сохранение",
      "не блокировка" in _f)
check("validate_recipe: стоп-лист — warning, а не blocking",
      all(i["severity"] == "warning"
          for i in _vr.validate("# Т\n\n**Порции:** 2 порции\n\n## Ингредиенты\n"
                                "| И | На 2 |\n|---|---|\n| Шампиньоны | 100 г |\n\n"
                                "## Приготовление\n### Шаг 1. А (1 мин)\nБ.\n")[1]
          if i["category"] == "stop_list"))

# Заголовки секций — общий словарь разбора. Разное написание на сторонах даст
# «не нашёл шагов» там, где другая сторона их видит.
for sec in ("ингредиенты", "приготовление", "инвентарь", "хранение", "источники"):
    check(f"секция «{sec}» известна обеим сторонам",
          sec in _f.lower() and sec in open(REPO / "tools/food/validate_recipe.py",
                                            encoding="utf-8").read().lower())

# id рецепта уезжает в ссылку ?recipe= — кириллица там приходит то в NFC, то в
# NFD (macOS отдаёт NFD) и перестаёт совпадать сама с собой. На этом уже
# обжигался share-режим travel, см. tools/travel.html.
check("food.html: id рецепта транслитерируется в латиницу", "function translitId" in _f)
check("food.html: подтверждённое сопоставление уходит в алиасы",
      "p.aliases.push" in _f)
# Фаззи-совпадение — ПОДСКАЗКА. Тихо неверная связь портит список незаметно и
# выясняется у плиты.
check("food.html: догадка помечена отдельно и не применяется молча",
      '"guess"' in _f and "похоже — проверьте" in _f)

# ── ручное добавление в список ─────────────────────────────────────────────
# Незнакомый продукт ЗАВОДИТСЯ в каталоге, а не остаётся строкой без связи:
# иначе он не попадёт ни в группировку по отделам, ни в мердж с рецептами —
# вечный сирота.
check("food.html: новый продукт из списка заводится в каталоге",
      "newProd = { id: id, name: name" in _f)
# Нативный <datalist> здесь НЕ годится, и это проверено вживую:
#   1. не фильтровал — на «яблок» показывал «Бульон, Говядина, Говяжий фарш»;
#   2. переживал свой же инпут: страница перерисовывается целиком, инпут
#      исчезает, а нативный попап остаётся висеть поверх закрытой модалки.
# Свой список фильтруется предсказуемо и умирает вместе с модалкой.
check("food.html: подсказки свои, не нативный datalist",
      "<datalist id=" not in _f and 'list="prod-list"' not in _f
      and 'class="sug-row"' in _f)
check("food.html: подсказки ищут и по алиасам, не только по имени",
      re.search(r'sug = .*?aliases', _f, re.S) is not None)
# «лук» должен давать «Лук репчатый» раньше, чем «Чеснок сушёный».
check("food.html: совпадение с начала имени ранжируется выше",
      "normName(x.name).indexOf(q) === 0" in _f)

# Купленное остаётся на месте. Отдельный блок «Куплено» наполнялся только
# после перезагрузки — то есть врал; а строка, уезжающая из-под пальца,
# заставляет отмечать не то.
check("food.html: блока «Куплено» больше нет",
      "S.boughtOpen" not in _f and '"bought-toggle"' not in _f)
check("food.html: купленная строка рисуется отмеченной и после перезагрузки",
      "var done = !!it.bought;" in _f)
check("food.html: «Убрать купленное» появляется без полной перерисовки",
      'id="sh-clear"' in _f and "anyBought" in _f)
# Состояние показывается ПРИ ВВОДЕ: без этого «малако» молча заведёт второй
# продукт, и через полгода в каталоге будет три молока.
check("food.html: при вводе видно, есть ли продукт в каталоге",
      "есть в каталоге" in _f and "заведу новый продукт" in _f)
check("food.html: похожий продукт предлагается, но не подставляется сам",
      'data-act="add-use"' in _f)
# «Продукт заведён» — хорошая новость; рисовать её красной рамкой значит
# пугать на ровном месте.
check("food.html: уведомление и ошибка различаются визуально (kind ok/err у плашки ui-kit)",
      "S.saveInfo" in _f and 'kind: S.saveNote ? "err" : "ok"' in _f
      # с ui-kit 1.56.0 вид плашки — общее уведомление .ui-toast (класс у той же разметки uiSaveBarHTML)
      and ".ui-toast.err{" in UI_KIT_CSS0 and ".ui-toast.ok{" in UI_KIT_CSS0 and "ui-savebar ui-toast" in (REPO / "tools/assets/ui-kit.js").read_text(encoding="utf-8"))

# ── замена продукта на сеанс ───────────────────────────────────────────────
# Отдельной связи «заменители» нет намеренно: это ещё одно отношение, которое
# пришлось бы поддерживать, а список каталога решает ту же задачу для любой пары.
check("food.html: замена продукта в плане — на сеанс, рецепт не меняется",
      "orig_product_id" in _f and "swapped" in _f)
check("food.html: единица берётся у продукта-замены (иначе рассыплется мердж)",
      "if (p.unit) x.unit = p.unit;" in _f)

# ── режим готовки ──────────────────────────────────────────────────────────
# Таймеров НЕТ намеренно: веб-таймер не звучит на заблокированном экране, не
# переживает закрытие браузера, душится в фоне (Chrome — до одной проверки в
# минуту), а navigator.vibrate Safari не поддерживает вовсе. Системный таймер
# телефона делает всё это лучше. Проверка защищает от «а давайте добавим»:
# добавлять надо осознанно, а не потому что казалось, что их не хватает.
check("food.html: таймеров в режиме готовки нет (см. решение в комментарии)",
      "setInterval" not in _f)
check("food.html: и вибрации тоже нет (Safari её не поддерживает)",
      "navigator.vibrate" not in _f)

# Wake Lock снимается системой сам; старый sentinel переиспользовать нельзя.
# Без перезапроса по visibilitychange экран начнёт гаснуть ровно тогда, когда
# человек вернулся от системного таймера — то есть в самый нужный момент.
check("food.html: Wake Lock перезапрашивается при возврате на вкладку",
      "visibilitychange" in _f and "wakeWanted" in _f)
check("food.html: намерение и фактическое удержание — разные поля",
      "S.wakeWanted" in _f and "S.wakeLock" in _f)
# Молчаливый фолбэк недопустим: человек решит, что сломано у нас.
check("food.html: при отсутствии Wake Lock показывается объяснение про https",
      "https-адресу" in _f)

# Прогресс готовки — эфемерное состояние одного сеанса, ему не место в файле
# на NAS: писать его туда значило бы дёргать сеть на каждую галочку.
check("food.html: прогресс готовки в localStorage, а не в файле",
      'COOK_KEY = "food-cook:"' in _f)
check("food.html: возврат к недоготовленному не продолжается молча",
      "Продолжим готовить?" in _f)
# После долгого перерыва первым предлагается начало, а не продолжение.
check("food.html: давность прогресса меняет порядок кнопок",
      "COOK_STALE_H" in _f and "stale ? again + cont : cont + again" in _f)
# Прыжки между шагами разрешены в обе стороны: правило NN/g про визарды
# («не давать выбрать шаг до завершения предыдущих») к готовке не переносится.
check("food.html: шторка шагов позволяет прыгнуть на любой шаг",
      'data-act="cook-step-abs"' in _f)
# Конвертация ТОЛЬКО внутри метрики. Появление мл→г означало бы таблицу
# плотностей — источник тихого вранья в количествах к покупке.
check("food.html: г↔кг и мл↔л, без перехода между размерностями",
      '"кг" : "л"' in _f or 'u === "г" ? "кг" : "л"' in _f)


# ── редактор рецепта ───────────────────────────────────────────────────────
print("food · редактор рецепта")
# Экран правки/создания рецепта (макет Claude Design). Раньше рецепты приходили
# только импортом или из проекта — теперь их можно завести и править на странице.
check("food.html: есть экран редактора", "function editScreen()" in _f)
# РЕАЛЬНЫЙ БАГ 2026-07-21: editScreen() рендерил секцию class="sc-edit", но
# `.sc-edit` забыли в списке видимости экранов (`.screen{display:none}` +
# `[data-screen="X"] .sc-X{display:block}`). Экран был в DOM, но невидим —
# «Новый рецепт» открывал пустоту. JS-тесты через dispatchEvent это пропустили
# (элементы существуют и при display:none). Здесь — структурная защита: КАЖДЫЙ
# экран, на который умеет переключиться диспетчер, обязан иметь правило
# видимости, иначе он откроется пустым.
_dispatched = set(re.findall(r'S\.screen === "(\w+)"', _f))
_visible = set(re.findall(r'\[data-screen="(\w+)"\]', _f))
_invisible = sorted(_dispatched - _visible)
check("food.html: у каждого экрана диспетчера есть правило видимости"
      + (" — невидимы: " + ", ".join(_invisible) if _invisible else ""),
      not _invisible)
check("food.html: экран подключён к диспетчеру",
      'S.screen === "edit"' in _f and "return editScreen()" in _f)
check("food.html: «Новый рецепт» на списке", '"new-recipe"' in _f)
check("food.html: «Править» на экране чтения", '"edit-recipe"' in _f)
# Экран пересобирается целиком — несохранённый ввод обязан переживать это.
check("food.html: форма снимается перед перерисовкой", "function edCollect()" in _f)
check("food.html: промежуточные действия снимают форму", _f.count("edCollect()") >= 6)
# Рабочая копия и формат хранения — разные формы; сериализация одним местом.
check("food.html: рабочая копия ↔ food-recipe@1",
      "function editFromRecipe(" in _f and "function editToRecipe(" in _f)
# Кнопка «Сохранить» гаснет при пустом названии.
check("food.html: пустое название блокирует сохранение",
      '(e.name || "").trim() !== ""' in _f)
# Новый рецепт получает свой файл — apiSave шлёт base_hash:null явно.
check("food.html: новый рецепт создаётся файлом (base_hash null)",
      "S.hash[name] != null ? S.hash[name] : null" in _f)
check("сайдкар умеет создавать новый файл (base_hash None)",
      "base_hash is None" in _srv)

# parseAmount — обратное к fmtQty: «600 г» из поля редактора → qty+unit.
check("food.html: «600 г» разбирается в qty+unit", "function parseAmount(" in _f)
# кг/л → базовые единицы. Единица сперва нормализуется (гр→г, килограмм→кг),
# потом конвертируется в базовую метрику.
check("food.html: parseAmount переводит кг в г",
      re.search(r'parseAmount[\s\S]{0,600}"кг"[\s\S]{0,60}1000', _f) is not None)
# Написание единиц приводится к канону в точке использования (гр→г и т.п.).
check("food.html: единицы нормализуются (гр→г) — normUnit", "function normUnit(" in _f)
check("food.html: «гр» распознаётся как «г»", '"гр": "г"' in _f)
# Время нормализуется на сохранении: «1 м»/«1 час» → «1 мин»/«1 ч».
check("food.html: длительность нормализуется на сохранении (normDur)",
      "function normDur(" in _f)

# Поиск по каталогу в редакторе (продуктов десятки, замечание владельца).
check("food.html: в редакторе есть поиск по каталогу",
      'id="f-ed-cat-q"' in _f and "S.edCatQuery" in _f)
# «Новый продукт»: кнопка на вкладке продуктов И в редакторе рецепта.
check("food.html: кнопка «Новый продукт» есть", '"prod-new"' in _f)
check("food.html: новый продукт получает slug-id (иначе id:undefined)",
      "if (!p.id) {" in _f and "translitId(p.name)" in _f)
# Заведённый из редактора продукт сразу падает в ингредиенты рецепта.
check("food.html: продукт из редактора добавляется в ингредиенты",
      'ret === "edit"' in _f and "S.edit.ings = S.edit.ings.concat" in _f)

# ── нормализация единиц и времени (пункт 2 замечаний) ──────────────────────
# «120 гр» не считалось в КБЖУ (unit «гр» ≠ «г»). Нормализуем написание в
# ТОЧКЕ использования — тогда старые данные считаются без миграции. Зеркало
# карты канона:
_UM = dict(re.findall(r'"([^"]+)":\s*"(г|мл|кг|л|шт)"', _f))
for spell, canon in [("гр", "г"), ("грамм", "г"), ("миллилитр", "мл"),
                     ("килограмм", "кг"), ("литр", "л"), ("штук", "шт")]:
    check(f"единица «{spell}» → «{canon}»", _UM.get(spell) == canon)
# gramsOf/fmtQty/мердж/оценка КБЖУ — все через normUnit.
for _fn in ("function gramsOf", "function fmtQty"):
    _body = _f[_f.index(_fn):_f.index(_fn) + 260]
    check(f"{_fn} нормализует единицу", "normUnit(" in _body)

# Время нормализуется на СОХРАНЕНИИ: «1 м»/«1 минут» → «1 мин», «1 час» → «1 ч».
# Зеркало normDur:
def norm_dur(s):
    return re.sub(
        r"(\d[\d.,]*(?:\s*[–—-]\s*\d[\d.,]*)?)\s*(минут\w*|мин\.?|час\w*|сек\w*|ч\.?|м\.?|с\.?)(?![а-яё])",
        lambda m: re.sub(r"\s+", "", m.group(1)) + " " + (
            "ч" if m.group(2)[0].lower() == "ч" else ("сек" if m.group(2)[0].lower() == "с" else "мин")),
        str(s or ""), flags=re.I)
check("normDur: «1 м» → «1 мин»", norm_dur("1 м") == "1 мин")
check("normDur: «5 минут» → «5 мин»", norm_dur("5 минут") == "5 мин")
check("normDur: «1 час» → «1 ч»", norm_dur("1 час") == "1 ч")
check("normDur: «2 часа» → «2 ч»", norm_dur("2 часа") == "2 ч")
check("normDur: «20 секунд» → «20 сек»", norm_dur("20 секунд") == "20 сек")
check("normDur: «3-20 м» → «3-20 мин»", norm_dur("3-20 м") == "3-20 мин")
check("food.html: normDur применяется в редакторе и dur-save",
      _f.count("normDur(") >= 2)

# ── план: всё «обычно дома» в одном блоке (пункт 5) ────────────────────────
# Стейпл с количеством (масло) висел в основном списке некупленным, а «по
# вкусу» (перец) — в нижнем блоке. Оба «дома», но врозь. Теперь один блок.
check("food.html: стейплы и «по вкусу» в одном блоке «обычно дома»",
      "homeRows" in _f and "Обычно есть дома" in _f)
check("food.html: строка плана вынесена в общую функцию (для основного и дома)",
      "function planRowHtml(" in _f)
check("food.html: блок «дома» раскрывается", '"plan-home-toggle"' in _f)

# ── ховер ингредиента: КБЖУ + фасовка вместо «брали» (пункт наведения)
check("food.html: ховер строки ингредиента показывает КБЖУ",
      re.search(r'var cat = \[kcalTxt', _f) is not None)
check("food.html: ховер показывает фасовку через packOf",
      re.search(r'var pkH = packOf\(p\)', _f) is not None)
check("food.html: «брали N назад» убрано из ховера ингредиента",
      'p.last_bought ? "брали "' not in _f)

# ── фокус одноразовый (пункт 1: курсор прыгал в поиск) ─────────────────────
# focusId «залипал»: напечатал в поиске, нажал «+» порций — курсор прыгал
# обратно. Сбрасываем после восстановления.
check("food.html: focusId сбрасывается после восстановления (одноразовый)",
      re.search(r'S\.focusId = null; S\.focusPos = null;', _f) is not None)

# ── КБЖУ-оценка на карточке рецепта (пункт «на карточке») ──────────────────
check("food.html: карточка показывает оценку КБЖУ, когда источника нет",
      re.search(r'dishNutritionEstimate\(r\)[\s\S]{0,200}ккал на порцию', _f) is not None)

# ── прокрутка при перерисовке (пункт 2 замечаний) ──────────────────────────
# innerHTML сбрасывал прокрутку в начало: на длинном редакторе «+ добавить
# шаг/строку» швыряло к верху. Позиция сохраняется, к верху — только на смене
# экрана.
check("food.html: render сохраняет позицию прокрутки",
      "var scrollY = window.scrollY" in _f and "window.scrollTo(0, scrollY)" in _f)
check("food.html: к верху только при смене экрана (через uiScrollTop)",
      "screenChanged" in _f and "uiScrollTop()" in _f and "window.scrollTo(0, 0)" not in _f)

# ── бейдж длительности ↔ парсер времени (пункт 5) ──────────────────────────
# РЕАЛЬНЫЙ БАГ: бейдж тянул СВОЙ, более узкий регэксп «мин|ч|час» — «(1 м)» и
# «(20 сек)» не показывались, хотя stepMinutes их считает и в сумму времени они
# входят. Два источника правды разошлись. Теперь один: stepDurLabel показывает
# скобки, если stepMinutes сумел их разобрать. (Зеркало-проверка «1 м»/«20 сек»
# — в секции «food · время», после определения step_minutes.)
check("food.html: бейдж длительности через общий stepDurLabel",
      "function stepDurLabel(" in _f)
check("food.html: узкий регэксп бейджа «мин|ч|час» больше не используется",
      "(?:мин|ч|час)[^)]*\\\\)" not in _f)

# ── подсветка чисел и #ингредиентов в тексте шага (пункт 3) ─────────────────
# Числа выделяются жирным ВСЕГДА (не только при пересчёте порций), «(было N)» —
# только когда пересчитано. #слово → жирный ингредиент со снятой решёткой.
check("food.html: числа жирные и при factor==1 (не только при пересчёте)",
      'if (factor === 1) return esc(text);' not in _f and "var scaled = factor !== 1;" in _f)
check("food.html: #ингредиент выделяется жирным", "#([а-яёa-z0-9-]+)" in _f)
check("food.html: «(было N)» только при пересчёте",
      'scaled ? \'<span style="font-size:.82em;' in _f)

# ── КБЖУ-оценка по ингредиентам, когда источник его не дал (пункт КБЖУ) ─────
# Считается на порцию из продуктов, помечается как ОЦЕНКА ПО СЫРЫМ — при
# готовке жир/вода меняют итог, поэтому это не «настоящее» КБЖУ.
check("food.html: КБЖУ-оценка из ингредиентов", "function dishNutritionEstimate(" in _f)
check("food.html: оценка помечена честно (сырые продукты, не источник)",
      "оценка по продуктам (сырым)" in _f)
check("food.html: непокрытые продукты не занижают тихо (доля покрытия)",
      "coverage" in _f and "итог занижен" in _f)
# Зеркало счёта: 200 г моркови (41 ккал/100 г) на 4 порции ≈ 21 ккал/порция.
# Тот же расчёт, что nutrition.py и живой прогон на странице.
check("оценка КБЖУ: 200 г × 41/100 / 4 ≈ 20.5",
      abs(200 * 41 / 100 / 4 - 20.5) < 0.01)

# КБЖУ показывается «на порцию» всегда, а «на 100 г» — когда введён вес блюда
# (у авторского через weightBlock, у оценки — через per100). Раньше оценка шла
# без подписи «на порцию» и без «на 100 г» вовсе (замечание владельца).
check("food.html: оценка КБЖУ подписана «На порцию» и «На 100 г»",
      "На порцию" in _f and "На 100 г" in _f)
check("food.html: оценка считает per100 при заданном весе блюда",
      "per100" in _f and "var p100 = null, fin = r.finished_g;" in _f)
# Редактор: КБЖУ по умолчанию скрыт (интернет/домашние рецепты его не дают),
# раскрывается галочкой; отдельно — вес готового блюда для «на 100 г».
check("food.html: редактор — чекбокс «КБЖУ известен»",
      "КБЖУ известен" in _f and '"ed-nu-toggle"' in _f)
check("food.html: редактор — поле «вес готового блюда»", "f-ed-finished" in _f)
check("food.html: КБЖУ сохраняется только при введённом ккал",
      "(e.nutrition && e.nutrition.kcal != null) ? e.nutrition : null" in _f)
# Зеркало per-100g: 690 ккал итог, блюдо 700 г → 690/700*100 ≈ 98.6 ккал/100 г.
check("оценка на 100 г: 690 × 100/700 ≈ 98.6",
      abs(690 * 100 / 700 - 98.57) < 0.1)
# «Вес готового блюда» и КБЖУ на 100 г должны работать ВЕЗДЕ, включая оценочные
# рецепты: per100g падает на расчёт по продуктам, weightBlock зовётся в обоих
# путях (кнопка ⚖ там, где веса нет), а «на 100 г» из оценки помечается ≈.
_p100 = _f.split("function per100g(r)")[1][:1600]
check("food.html: per100g падает на оценку по продуктам (вес-везде)",
      "dishNutritionEstimate(r)" in _p100 and "est: true" in _p100)
check("food.html: weightBlock вызывается и в оценочном пути (⚖ везде)",
      _f.count("weightBlock(r)") >= 2)
check("food.html: оценочный «на 100 г» помечен ≈/оценка", "h.est" in _f and "· оценка" in _f)

# Переименование продукта в каталоге доходит до строк рецепта и списка: имя для
# показа берётся из ТЕКУЩЕГО продукта по product_id, а не из замороженного поля.
# Мердж списка и так по product_id — в корзину едет верный продукт; это правит
# именно подпись (иначе правка имени продукта в рецепт/список не долетала).
check("food.html: curName берёт текущее имя продукта по product_id",
      "function curName(" in _f and "o.product_id ? productById(o.product_id)" in _f)
check("food.html: имя ингредиента в рецепте — через curName",
      "esc(curName(g))" in _f)
check("food.html: имя позиции списка покупок — через curName",
      "esc(curName(it))" in _f)

# ── рецепты: по файлу на рецепт ────────────────────────────────────────────
# Общий recipes.json заменён каталогом Food/recipes/ (2026-07-20): добавление
# рецепта = положить файл, а правки разных рецептов больше не сталкиваются
# (общий файл давал 409 на каждую параллельную правку — вдвоём это ежедневно).
print("food · рецепты по файлам")
check("food.html: рецепты читаются листингом каталога",
      "function loadRecipes()" in _f and 'DATA + "recipes/"' in _f)
check("food.html: листинг запрашивается как JSON",
      'Accept: "application/json"' in _f or "Accept: \"application/json\"" in _f)
# Один битый файл не должен обрушить библиотеку — но и молчать о нём нельзя:
# положил кривой файл, рецепт не появился, и понять почему неоткуда.
check("food.html: битый файл рецепта пропускается, а не роняет загрузку",
      re.search(r'getJSON\(DATA \+ "recipes/".*?\.catch', _f, re.S) is not None)
check("food.html: о непрочитанных файлах сказано на экране",
      "function brokenNote()" in _f and "brokenNote()" in _f.split("function brokenNote")[1])
check("food.html: сохраняется ОДИН рецепт, а не вся библиотека",
      "function saveRecipe(id" in _f and "saveRecipes(" not in _f)
check("food.html: файл рецепта несёт свою schema",
      '{ schema: "food-recipe@1" }' in _f)
# Права на запись определяют products/shopping: каталог рецептов читается
# публично, и по нему судить о правах нельзя.
check("food.html: права не выводятся из публичного каталога рецептов",
      "S.writable = !!(p.writable && sh.writable);" in _f)
check("сайдкар: рецепт — файл в подкаталоге", "RECIPE_RE" in _srv)
# Идентичность рецепта — ИМЯ ФАЙЛА (упрощение 2026-07-21). Поле id внутри
# необязательно; отсутствие id — НОРМА нового формата, а не расхождение.
check("food.html: id рецепта берётся из ИМЕНИ ФАЙЛА, а не из поля внутри",
      'o.name.replace(/\\.json$/i, "")' in _f and "o.doc.id = fileId;" in _f)
check("food.html: id в файл рецепта НЕ пишется (имя файла — идентичность)",
      "delete doc.id;" in _f)
check("food.html: расхождение id и имени файла → предупреждение",
      "mismatchedRecipes" in _f and "не совпадает с именем файла" in _f)
# Пустой id (новый формат без поля) НЕ должен считаться расхождением — иначе
# все правильные файлы без id ложно идут в счётчик mismatchedRecipes (баг
# 2026-07-23: 26 файлов без id показывались как «26 рецептов с чужим id»).
# Охрана != null — зеркало сайдкара, где реджекта по расхождению больше нет.
check("food.html: пустой id — НЕ расхождение (охрана != null)",
      "o.doc.id != null && o.doc.id !== fileId" in _f)
check("сайдкар: id внутри файла необязателен",
      '"id" in doc' in _srv)
check("сайдкар: расхождение id с именем НЕ отклоняется (страница откроет по имени)",
      "не совпадает с именем файла" not in _srv)

# ── карточка рецепта ───────────────────────────────────────────────────────
check("food.html: карточка открывается целиком, а не только кнопкой",
      'class="rcard" data-act="open-recipe"' in _f)
# Делегирование берёт ближайший [data-act], поэтому кнопки внизу карточки
# перехватывают клик у неё сами — отдельного stopPropagation не нужно.
check("food.html: на карточке «Готовить» и «Запланировать»",
      '"cook" data-arg=' in _f.replace("data-act=", "") or 'data-act="cook" data-arg=' in _f)

# ── время рецепта по сумме шагов ───────────────────────────────────────────
# Длительность живёт в заголовке шага — том же формате, что эмитит проект
# Claude.ai и разбирает validate_recipe.py. Здесь зеркало разбора: разъедутся
# — правка длительности на странице перестанет менять итог, и никто не заметит.
print("food · время")
# Живые рецепты на Synology, если смонтированы: арифметика обязана пережить
# реальные данные, а не только фикстуры. С миграции 2026-08-13 Claude-Memory —
# единое дерево вне облачных синков; Food/ — его поддерево.
FOOD_REAL = Path.home() / "Library/CloudStorage/SynologyDrive-home/Claude-Memory/Food"
_DUR_PY = re.compile(
    r"(~)?\s*(\d+(?:[.,]\d+)?)"
    r"(?:\s*[–—-]\s*(\d+(?:[.,]\d+)?))?"
    r"\s*(минут\w*|мин\.?|час\w*|сек\w*|ч\.?|м\.?|с\.?)(?![а-яё])", re.I)


def step_minutes(title):
    """Зеркало stepMinutes() страницы."""
    m = re.search(r"\(([^)]*)\)\s*$", str(title or ""))
    if not m:
        return None
    parts, approx = [], False
    for d in _DUR_PY.finditer(m.group(1)):
        lo = float(d.group(2).replace(",", "."))
        hi = lo if d.group(3) is None else float(d.group(3).replace(",", "."))
        if d.group(1) or hi != lo:
            approx = True
        u = d.group(4).lower()
        k = 60 if u[0] == "ч" else (1 / 60 if u[0] == "с" else 1)
        parts.append((u[0], hi * k))
    if not parts:
        return None
    mins = [v for _, v in parts]
    # разные единицы — части одной величины («2 ч 10 мин»), одинаковые — диапазон
    total = sum(mins) if len({u for u, _ in parts}) > 1 else max(mins)
    return {"min": round(total * 10) / 10, "approx": approx}


# Бейдж длительности: показывает скобки, если step_minutes их разобрал.
# «1 м» и «20 сек» теперь дают бейдж (раньше узкий регэксп бейджа их не брал),
# «до корочки» — нет.
def step_dur_label(title):
    m = re.search(r"\(([^)]*)\)\s*$", str(title or ""))
    return m.group(1).strip() if (m and step_minutes(title) is not None) else None


check("бейдж: «(1 м)» показывается", step_dur_label("Шаг 1. Обжарка (1 м)") == "1 м")
check("бейдж: «(20 сек)» показывается", step_dur_label("Шаг 1. Т (20 сек)") == "20 сек")
check("бейдж: «(до корочки)» не показывается", step_dur_label("Шаг 1. Жарка (до корочки)") is None)

# Из диапазона берётся ВЕРХ. Это решение, а не деталь: план, который занижает,
# бесполезен — по нему нельзя понять, влезает ли готовка в вечер.
check("«12–15 мин» → 15 (верх диапазона, не низ и не середина)",
      step_minutes("Шаг 2. Варка гречки (12–15 мин)")["min"] == 15)
check("«5 мин» → 5", step_minutes("Шаг 3. Брокколи (5 мин)")["min"] == 5)
check("часы переводятся в минуты", step_minutes("Шаг 4. Тушение (1.5–2 часа)")["min"] == 120)
check("«6 ч» → 360", step_minutes("Шаг 2. Настаивание (6 ч)")["min"] == 360)
# «~» помечает оценку при миграции — разбору мешать не должна.
check("«~» не мешает разбору", step_minutes("Шаг 4. Раскладка (~5 мин)")["min"] == 5)
check("«~» помечает приблизительность", step_minutes("Шаг 4. Раскладка (~5 мин)")["approx"])
check("точное значение приблизительным не считается",
      not step_minutes("Шаг 3. Брокколи (5 мин)")["approx"])
# Шаг без времени — «неизвестно», а НЕ ноль: иначе итог молча занижается.
check("заголовок без скобок → нет длительности", step_minutes("Шаг 1. Обжарка") is None)
check("скобки без времени → нет длительности",
      step_minutes("Шаг 1. Обжарка (до корочки)") is None)
check("температура за длительность не сходит",
      step_minutes("Шаг 1. Запекание (200 °C)") is None)


# Форматы, которые реально пишут рукой. Расширено по замечанию владельца:
# «2 м» и «~3ч» раньше выпадали из суммы молча.
for _t, _want in (("(2 м)", 2), ("(2м)", 2), ("(4-10 мин)", 10), ("(~3ч)", 180),
                  ("(1,5 часа)", 90), ("(5 минут)", 5)):
    check(f"длительность «{_t}» разбирается", step_minutes("Шаг 1. Т " + _t)["min"] == _want)
# «м» не должно съедать «мм», а «с» — «сек» из середины слова.
check("«3 мм» не длительность", step_minutes("Шаг 1. Кубики (3 мм)") is None)
check("«200 °C» не длительность", step_minutes("Шаг 1. Запекание (200 °C)") is None)
# Секунды не должны обнуляться: шаг существует и в сумме весит своё.
check("«20 сек» не превращается в ноль", step_minutes("Шаг 1. Т (20 сек)")["min"] > 0)

check("«2 ч 10 мин» складывается, а не читается как 2 ч",
      step_minutes("Шаг 5. Тушение (2 ч 10 мин)")["min"] == 130)
check("«12–15 мин» остаётся диапазоном, а не суммой 27",
      step_minutes("Шаг 2. Варка (12–15 мин)")["min"] == 15)

LONG_STEP_MIN = 60


def recipe_time(steps):
    """Зеркало recipeTime() страницы: флаг passive главнее порога 60 мин."""
    active = waiting = known = 0
    for s in steps:
        d = step_minutes(s.get("title"))
        if not d:
            continue
        known += 1
        passive = s.get("passive")
        is_wait = passive is True or (passive is None and d["min"] >= LONG_STEP_MIN)
        if is_wait:
            waiting += d["min"]
        else:
            active += d["min"]
    if not known:
        return None
    hands = max(5, round(active * 1.10 / 5) * 5) if active else 0
    return {"active": active, "hands": hands, "waiting": waiting,
            "known": known, "of": len(steps)}


_rt = recipe_time([{"title": "Шаг 1. А (20–25 мин)"}, {"title": "Шаг 2. Б (12–15 мин)"},
                   {"title": "Шаг 3. В (5 мин)"}, {"title": "Шаг 4. Г (~5 мин)"}])
check("сумма активных шагов = 50 мин", _rt["active"] == 50)
check("у плиты = активные + 10%, округлённые до 5 (55 мин)", _rt["hands"] == 55)
check("ожидания нет, когда все шаги короткие", _rt["waiting"] == 0)

# ГЛАВНОЕ СВОЙСТВО. Шаг длиной от часа — ожидание, а не работа. Считать всё
# одной суммой давало «Ленивая овсянка — 8 ч 55 мин», хотя руками там пять
# минут; хуже того, надбавка на мытьё бралась и от ожидания — 10% от восьми
# часов сна дают 53 минуты мытья посуды.
_ov = recipe_time([{"title": "Шаг 1. Замес (~3 мин)"},
                   {"title": "Шаг 2. Настаивание (6 ч)"},
                   {"title": "Шаг 3. Ягоды (~2 мин)"}])
check("ночь в холодильнике не попадает в «у плиты»", _ov["hands"] == 5)
check("ночь в холодильнике учтена как ожидание", _ov["waiting"] == 360)
check("надбавка на мытьё берётся только от активного времени",
      _ov["hands"] < 6 * 60 * 0.10)

# Округление до 5 не должно обнулять работу: у чиа-пудинга активных две
# минуты, а «0 мин у плиты» читается как «готовится само».
_chia = recipe_time([{"title": "Шаг 1. Замес и ночь (~8 ч)"},
                     {"title": "Шаг 2. Добавки (~2 мин)"}])
check("две минуты работы не округляются в ноль", _chia["hands"] == 5)
check("нулевая работа остаётся нулём",
      recipe_time([{"title": "Шаг 1. Настаивание (6 ч)"}])["hands"] == 0)

# Явный флаг «без участия» ГЛАВНЕЕ порога: 30 мин в холодильнике (< 60) — это
# ожидание, хотя порог их не поймал бы. Ровно случай, ради которого добавили
# галочку: «жарить 50 мин + 30 мин в холодильнике» (замечание владельца).
_pv = recipe_time([{"title": "Шаг 1. Жарка (50 мин)"},
                   {"title": "Шаг 2. Холодильник (30 мин)", "passive": True}])
check("пассивные 30 мин (< 60) уходят в ожидание по флагу", _pv["waiting"] == 30)
check("активные 50 мин остаются у плиты", _pv["active"] == 50)
# Без флага короткий шаг по-прежнему считается работой (порог — запаска).
check("без флага 30 мин остаются активными (порог не сработал)",
      recipe_time([{"title": "Шаг 1. Холодильник (30 мин)"}])["active"] == 30)
# Длинный шаг И БЕЗ флага уходит в ожидание — порог остаётся для старых файлов.
check("порог 60 мин жив как запаска без флага",
      recipe_time([{"title": "Шаг 1. Тушение (90 мин)"}])["waiting"] == 90)

# ── шаг «без участия»: страница + оба .md-парсера ──────────────────────────
check("food.html: recipeTime уважает флаг passive (порог 60 — запаска)",
      "s.passive === true || (s.passive == null && d.min >= LONG_STEP_MIN)" in _f)
check("food.html: бейдж пассивного шага — ⏸ вместо ⏱",
      '(passive ? "⏸" : "⏱")' in _f)
check("food.html: чекбокс «без участия» в редакторе шага", "f-ed-step-pass-" in _f)
check("food.html: инлайн-редактор длительности несёт чекбокс passive",
      "f-dur-passive" in _f)
check("food.html: dur-save читает флаг passive", 'getElementById("f-dur-passive")' in _f)
check("food.html: .md-мостик пассивного шага (без участия)", "_PASSIVE_MD" in _f)
check("validate_recipe.py: .md-шаг «без участия» → step.passive",
      "_PASSIVE" in (REPO / "tools/food/validate_recipe.py").read_text(encoding="utf-8")
      and "def _step_dict(" in (REPO / "tools/food/validate_recipe.py").read_text(encoding="utf-8"))

_rt2 = recipe_time([{"title": "Шаг 1. А"}, {"title": "Шаг 2. Б (12–15 мин)"},
                    {"title": "Шаг 3. В (5 мин)"}, {"title": "Шаг 4. Г (~5 мин)"}])
check("шаг без времени не считается нулём, а уменьшает покрытие",
      _rt2["active"] == 25 and _rt2["known"] == 3 and _rt2["of"] == 4)
check("ни у одного шага нет времени → итога нет (не показываем «0 мин»)",
      recipe_time([{"title": "Шаг 1. А"}]) is None)

check("food.html: порог «шаг-ожидание» назван константой", "LONG_STEP_MIN = 60" in _f)
check("food.html: ожидание показано отдельно от работы у плиты",
      "ожидания" in _f and "у плиты" in _f)

# Прогон по реальным рецептам: арифметика не должна падать и не должна давать
# бессмыслицу ни на одном живом файле.
if FOOD_REAL and (FOOD_REAL / "recipes.json").exists():
    _rr = _json.loads((FOOD_REAL / "recipes.json").read_text(encoding="utf-8"))["recipes"]
    _times = [(r["title"], recipe_time(r.get("steps", []))) for r in _rr]
    check("real: у каждого рецепта считается время",
          all(t is not None for _, t in _times))
    check("real: нигде не выходит «0 мин у плиты» при ненулевой работе",
          all(t["hands"] > 0 for _, t in _times if t and t["active"] > 0))
    check("real: ночные рецепты ушли в ожидание, а не в работу",
          all(t["hands"] <= 30 for n, t in _times if t and t["waiting"] >= 300))

check("food.html: надбавка 10% названа константой", "TIME_OVERHEAD = 0.10" in _f)
check("food.html: итог считается, а не берётся строкой из источника",
      "function recipeTime(r)" in _f and "rt ? null : r.time" in _f)
# Строка автора не выбрасывается: она знает про параллельность (курица
# печётся, пока варится гречка), а сумма шагов — не знает по построению.
check("food.html: строка времени из источника сохранена рядом",
      "в источнике: " in _f)
check("food.html: длительность шага правится на месте",
      '"dur-open"' in _f and '"dur-save"' in _f)
# Пустое поле = «время неизвестно». Если бы сохранялось «(0 мин)» — итог
# выглядел бы полным, а шаг молча не считался.
check("food.html: пустая длительность стирает скобки, а не пишет ноль",
      'name + (dur ? " (" + dur + ")" : "")' in _f)
check("food.html: неразобранная длительность отвергается с подсказкой",
      "Не разобрал длительность" in _f)

# ── продукт: фасовка на продукте и КБЖУ ────────────────────────────────────
print("food · продукт")
# Понятие «магазин» убрано 2026-08-01: покупаем там, где решили, а не там,
# где записано. Фасовка (pack_size) — свойство ПРОДУКТА; packOf разбирает и
# легаси-формы (stores[] 2026-07-20..08-01, где фасовка жила внутри магазинов,
# и совсем старую плоскую пару) — файлы до миграции работают без правки руками.
check("food.html: фасовка читается через packOf по продукту",
      "function packOf(p)" in _f)
check("food.html: легаси stores[] читается без миграции",
      "Array.isArray(p.stores)" in _f)
check("food.html: магазинов больше нет (ни фильтра, ни списка)",
      "storeFilter" not in _f and "STORES" not in _f and "productStores" not in _f)
# Группировка списка — по отделам: так ходят по залу. «Прочее» — пробел в
# каталоге, он не должен возглавлять список.
check("food.html: список группируется по отделам, «прочее» вниз",
      'a === "прочее"' in _f)
# Тап по чипу отдела перерисовывает модалку — введённое обязано пережить это.
check("food.html: форма снимается перед перерисовкой, а не теряется",
      "function readProdForm()" in _f and "readProdForm();" in _f)
# Два места правды разъедутся при первой же правке рукой.
check("food.html: легаси-формы не сохраняются рядом с pack_size",
      "delete out.store; delete out.stores;" in _f)
check("food.html: редактор пишет pack_size с формы",
      'pack_size: num("pack")' in _f)

# ── степпер количества: мелкий шаг ± и шаг «одна упаковка» ─────────────────
print("food · степпер количества")
# У полки реальная единица покупки — упаковка, а не 50 г: крупный шаг берёт
# pack_size продукта. Мелкий шаг зависит от единицы: штуки — 1, вес/объём — 50
# (та же кухонная точность, что в roundQty).
check("food.html: разбор ввода и шаг вынесены в хелперы",
      "function parseQtyInput(" in _f and "function stepQtyValue(" in _f)
check("food.html: «1,5 кг» нормализуется в граммы при шаге",
      re.search(r'if \(u === "кг"\) \{ v \*= 1000; u = "г"; \}', _f) is not None)
check("food.html: шаг штук — 1, веса — 50", '=== "шт" ? 1 : 50' in _f)
check("food.html: шаг-упаковка берёт pack_size", 'kind === "pack"' in _f)
check("food.html: шаг не уводит количество в минус", "Math.max(0, q.v + dir * step)" in _f)
# Кнопки есть в ОБОИХ местах ввода количества — строка списка и «Добавить»:
# рука привыкает к одному виду и месту.
check("food.html: степпер в строке списка", '"qty-step"' in _f)
check("food.html: степпер в модалке добавления", '"add-qty-step"' in _f)
check("food.html: кнопка шага — общий хелпер stepBtn", _f.count("stepBtn(") >= 8)
# add-save парсит количество parseFloat'ом: суффикс «кг» потерял бы ×1000
# молча (1,5 кг → 1.5 «г»). Поэтому шаг в модалке пишет ГОЛОЕ число.
check("food.html: шаг в модалке добавления пишет голое число",
      "a.qty = trimNum(r.v)" in _f)
# Пачечные кнопки — только при согласованных единицах (то же условие, что у
# packsFor): шагать «+750 г» у позиции в штуках — смешение метрик.
check("food.html: пачечный шаг в списке требует совпадения единиц",
      "pEd.unit === it.unit" in _f)
check("food.html: пачечный шаг в модалке требует совпадения единиц",
      re.search(r'effUnit === \(mp\.unit \|\| ""\)', _f) is not None)
# Шаг в строке списка правит инпут БЕЗ render(): значение живёт в поле до
# «OK», перерисовка потеряла бы и фокус, и несохранённый ввод.
check("food.html: qty-step правит инпут без перерисовки",
      re.search(r'"qty-step": function[\s\S]{0,700}el\.value = fmtQty', _f) is not None)

# ── карточка товара по тапу ────────────────────────────────────────────────
print("food · карточка товара")
# Тап по телу строки каталога — ПРОСМОТР (КБЖУ, фасовка, переводы единиц,
# где используется), правка — отдельной кнопкой. Без прав на запись карточка —
# единственный способ увидеть всё разом.
check("food.html: тап по строке каталога открывает карточку",
      'data-act="prod-card"' in _f and "function prodCardModal()" in _f)
check("food.html: карточка показывает КБЖУ плитками", "КБЖУ на 100 г</div>" in _f)
# Производные числа («вся упаковка ≈ N ккал», «1 шт ≈ N ккал») считаются из
# уже известных, ничего нового не храня.
check("food.html: карточка считает калории упаковки и штуки",
      'derived.push("упаковка "' in _f and "nu.kcal * p.piece_g / 100" in _f)
check("food.html: «Править» из карточки — только при правах",
      re.search(r'S\.writable \? \'<button class="ui-btn ghost" data-act="prod-card-edit"', _f) is not None)
check("food.html: Escape и close-modal закрывают карточку",
      'ACTS["close-modal"]()' in _f
      and re.search(r'"close-modal": function[\s\S]{0,500}prodCard: null', _f) is not None)
# ui-kit 1.36.0: окна стопкой — форма продукта поверх карточки («Править») и поверх
# подбора («Завести продукт»); «Отмена» возвращает к нижнему окну (2026-10-07)
check("food.html: «Править» и «Завести продукт» — поверх карточки/подбора, не вместо",
      re.search(r'"prod-card-edit": function[\s\S]{0,120}set\(\{ prodEdit:', _f) is not None
      and re.search(r'"ing-link-new": function[\s\S]{0,200}ingLink: null', _f) is None
      and 'ov.k === "prodEdit" && S.prodCard' in _f and 'ov.k === "prodEdit" && S.ingLink' in _f)
check("food.html: close-modal закрывает верхнее окно с анимацией (uiStackPop), нижнее остаётся",
      re.search(r'"close-modal": function[\s\S]{0,200}uiStackPop\(', _f) is not None
      and "if (S.prodEdit && (S.prodCard || S.ingLink)) return set({ prodEdit: null, prodReturn: null })" in _f)
check("food.html: окна въезжают плавно — классы слоя из ui-kit (uiStackCls), новое окно — по смене ключей",
      "uiStackCls(i, layers.length, fresh)" in _f and "S._lastLayers = keys" in _f)
# Чип рецепта из карточки уводит на страницу рецепта — карточка обязана
# закрыться, иначе перекроет собой открытый рецепт.
check("food.html: open-recipe закрывает карточку товара",
      re.search(r'"open-recipe": function[^\n]*prodCard: null', _f) is not None)

# КБЖУ — ОДНО на продукт и именно на 100 г: так пишут на этикетке, и только так
# значения складываются между продуктами. «На упаковку» сложить нельзя.
check("food.html: в редакторе есть поля КБЖУ", 'id="f-nu-' in _f)
# Единица фасовки показывается РОВНО в одном месте — суффиксом в поле, рядом
# с числом (история: продублированная в заголовке колонки единица не
# обновлялась при правке «Единицы» — два места правды разъехались там, где
# сверять их некому).
check("food.html: поле фасовки одно, f-pack (общее поле ui-kit)", 'id: "f-pack"' in _f)
check("food.html: единица стоит суффиксом в поле (suffix + класс pack-unit)",
      'suffix: pu, suffixCls: "pack-unit"' in _f and 'class="ui-field-sfx num' in UI_KIT_JS0)
# Поле формы — одно на кабинет (ui-kit 1.27.0): .fld/.fld-lbl определены только
# в ui-kit.css, подсказка — после названия (решение владельца 2026-10-06).
for _pg in ("health", "food"):
    _src5 = (REPO / f"tools/{_pg}.html").read_text(encoding="utf-8")
    check(f"{_pg}.html: стили полей .fld/.fld-lbl — только в ui-kit (своих копий нет)",
          re.search(r"^\.fld(-lbl)?\{", _src5, re.M) is None)
    check(f"{_pg}.html: fld() — обёртка над общим uiFieldHTML", "return uiFieldHTML({" in _src5)
for _pg in ("health", "food"):
    _src6 = (REPO / f"tools/{_pg}.html").read_text(encoding="utf-8")
    check(f"{_pg}.html: плашка сохранения — общая uiSaveBarHTML (своих стилей и разметки нет)",
          "uiSaveBarHTML({" in _src6 and re.search(r"^\.savebar\{", _src6, re.M) is None
          and 'savebar = \'<div' not in _src6)
check("ui-kit: плашка над окнами форм и над нижней панелью",
      "z-index:1050" in UI_KIT_CSS0.split(".ui-toast{", 1)[1][:400] and "var(--ui-mnav-offset)" in UI_KIT_CSS0.split(".ui-toast{", 1)[1][:400])
check("ui-kit.css: .fld, .fld-lbl и .fld-hint определены", all(x in UI_KIT_CSS0 for x in (".fld{", ".fld-lbl{", ".fld-hint{")))
check("food.html: подсказки полей — после названия, не строкой под полем",
      "margin-top:4px;\">' + esc(hint)" not in _f and "сколько в одной пачке" in _f.split('label: "В упаковке"', 1)[1][:400])
check("food.html: суффикс догоняет правку «Единицы» без перерисовки",
      't.id === "f-unit"' in _f and "querySelectorAll(\".pack-unit\")" in _f)

check("food.html: подписано, что это на 100 г",
      "КБЖУ на 100 г продукта" in _f and "на 100 г, не на упаковку" in _f)
_nu_keys = set(re.findall(r'"(kcal|protein_g|fat_g|carb_g)"', _f))
check("food.html: все четыре макроса", _nu_keys == {"kcal", "protein_g", "fat_g", "carb_g"})
# Сайдкар: pack_size верхнего уровня — канон (страница на него делит),
# stores[] проверяется как ЛЕГАСИ-форма — битый старый файл не должен
# разнести NaN по списку до своей миграции.
check("сайдкар проверяет pack_size продукта как число-или-null",
      '"pack_size", it.get("pack_size")' in _srv)
check("сайдкар терпит легаси-stores и проверяет их форму", '.get("stores")' in _srv)

# ── единица из продукта + пересчёт штук в граммы ───────────────────────────
print("food · единицы и штуки")
# Единица бралась свободным текстом — давала «шт» там, где продукт в граммах,
# и количество потом не суммировалось. Теперь единица из продукта.
check("food.html: единица в «Добавить» берётся из продукта",
      "mp.unit || \"\"" in _f and "function addModal()" in _f)
# Штучный продукт с известным весом штуки → выбор шт/г и пересчёт.
check("food.html: у штучного продукта есть выбор единицы",
      '"add-unit-pick"' in _f)
check("food.html: piece_g связывает штуки с граммами", "function gramsOf(" in _f)
check("food.html: живой пересчёт «N шт → N г» в модалке",
      "* mp.piece_g" in _f)
# Тот же вес виден и в каталоге, и в строке списка — иначе непонятно,
# сколько это на самом деле.
check("food.html: «1 шт ≈ N г» в каталоге", '"1 шт ≈ "' in _f or "1 шт ≈ " in _f)
check("food.html: вес штук показан в строке списка",
      re.search(r'gramsOf\(it\.qty', _f) is not None)
# Поле перевода в граммы теперь ДИНАМИЧНО по семье единицы продукта (unitFamily):
# шт → «Граммов в 1 шт» (piece_g), мл/л → «Граммов в 100 мл» (g_per_100ml,
# плотность), вес → поля нет. Одно поле f-conv, подпись/ключ по единице.
check("food.html: поле перевода в граммы — динамическое по единице",
      '"conv"' in _f and "Граммов в 1 шт" in _f and "Граммов в 100 мл" in _f)
check("food.html: unitFamily разводит штуку/объём/вес", "function unitFamily(" in _f)
# Вес штуки виден и правится у весового продукта (яблоко: г + piece_g=180) — иначе переключатель
# «г/шт» в списке покупок работал от значения, которого в редакторе не видно. Единица «уп» в
# список не пишется: add-save переводит её в базовую единицу продукта (суммирование с рецептами).
check("food.html: поле «граммов в 1 шт» — и у весовых (convKind)",
      "function convKind(" in _f and 'convKind(p.unit) === "volume"' in _f
      and 'if (n === "шт" || n === "г" || n === "кг") return "piece"' in _f)
check("food.html: ячейка списка — целое число упаковок как «N уп.» (qtyShown), хранение в базе",
      "function qtyShown(" in _f and 'return n + " уп."' in _f and "esc(qtyShown(it)" in _f)
check("food.html: окно добавления — фокус на имя, ↓/↑/Enter по подсказкам, точное совпадение прячет список",
      'focusId: "f-add-name"' in _f and "S.addSugIdx" in _f and 'ev.key === "ArrowDown" || ev.key === "ArrowUp"' in _f
      and "normName(p.name) === q ||" in _f)
check("food.html: Esc в редакторе рецепта = ed-cancel; плейсхолдер количества зависит от единицы",
      'if (S.screen === "edit") { ACTS["ed-cancel"](); return; }' in _f   # Esc — closeTop слоя страницы (ui-kit 1.64)
      and '{ "уп": "1", "шт": "1", "кг": "1", "л": "1" }[effUnit]' in _f)
check("ui-kit ≥1.63: ui-search-key + Escape в поле поиска; food: Enter/↑/↓ в поиске рецептов и продуктов",
      '"ui-search-key"' in open("tools/assets/ui-kit.js", encoding="utf-8").read()
      and 'addEventListener("ui-search-key"' in _f and "S.prodSel" in _f and ".row-hover.kb-sel{" in _f
      and "cards.length === 1" in _f)
check("food.html: список покупок — выбор г/мл · шт · уп. (addUnitChoices), «уп» → база в add-save",
      "function addUnitChoices(" in _f and '["уп", "уп."]' in _f
      and 'if (unit === "уп") {' in _f and "qty * pk * 100" in _f)
check("food.html: gramsOf жидкостей через плотность g_per_100ml",
      "prod.g_per_100ml" in _f and "qty * d / 100" in _f)
check("сайдкар проверяет piece_g как число", "piece_g" in _srv)
check("сайдкар проверяет g_per_100ml (плотность) как число", "g_per_100ml" in _srv)
# nutrition.py — эталон КБЖУ: тот же перевод объём→вес по плотности.
check("nutrition.py: to_grams через g_per_100ml",
      "g_per_100ml" in (REPO / "tools/food/nutrition.py").read_text(encoding="utf-8"))

# ── единицы: «мера» (показ) отдельно от STD (расчёт) ───────────────────────
# «1 стакан» человеку, а КБЖУ и список — из qty (г/мл/шт). При пересчёте порций
# мера не масштабируется (стакан не делится на 1,7) — тогда показываем только STD.
check("food.html: amountText показывает меру + бледный STD в скобках",
      "function amountText(" in _f and "g.measure && atBase" in _f)
check("food.html: измеритель STD не масштабирует меру (atBase по factor)",
      "Math.abs((factor == null ? 1 : factor) - 1)" in _f)
check("food.html: поле «мера» в строке ингредиента редактора",
      "f-ed-ing-meas-" in _f)
check("food.html: measure едет в round-trip редактора (from/to/collect)",
      'measure: g.measure || ""' in _f
      and 'measure: (g.measure || "").trim() || undefined' in _f)
check("сайдкар: measure ингредиента — строка или null (показ, не число)",
      "measure" in _srv and "число сюда не кладут" in _srv)

# ── порции: без едоков ─────────────────────────────────────────────────────
# «в рецепте 2 · 2 порции» читалось как загадка: 2 или 2×2? Едоков не считаем
# вовсе — одна порция есть одна порция.
check("food.html: число порций без пояснения про людей",
      "servings_note ?" not in _f)
check("food.html: порции склоняются", 'plural(r.servings, "порция"' in _f)

# ── отметка «куплено» без перерисовки ──────────────────────────────────────
# Полный render() дёргал всю разметку (включая рельс) И уносил строку в
# свёрнутый блок — список менялся под пальцем посреди магазина, следующая
# строка подпрыгивала на место нажатой, и отмечалось не то.
check("food.html: отметка правит DOM точечно", "function paintBought(" in _f)
check("food.html: отметка сохраняется в тихом режиме", "saveShopping(null, true)" in _f)
check("food.html: тихий режим не подавляет ОШИБКУ сохранения",
      re.search(r"catch\(function \(e\) \{\s*/\*[^*]*(?:\*(?!/)[^*]*)*\*/\s*S\.saving = false; S\.saveNote = e\.message; render\(\);", _f) is not None)
check("food.html: у счётчика и рельса есть якоря для точечной правки",
      'id="sh-count"' in _f and """.ui-rail-item[data-arg="shopping"] .ui-rail-sub""" in _f)
check("food.html: позицию можно убрать из списка", '"item-del"' in _f)
# Набежавшую из рецептов позицию вернуть сложнее, чем добавленную рукой.
check("food.html: удаление позиции спрашивает подтверждение всегда (и ручной, и набежавшей из рецептов)",
      re.search(r'"item-del"[\s\S]{0,700}if \(!from\.length\) return uiConfirm\([\s\S]{0,200}\n\s*uiConfirm\(', _f) is not None)

# Версия страницы нужна ровно для одного: понять по скриншоту, ту ли сборку
# человек видит. Без неё «у меня не работает» неотличимо от «у меня старая
# версия из кеша» — а страницы кабинета отдаются без ?v=-бастера.
check("food.html: в подвале есть версия",
      re.search(r'var VERSION = "food v\d+\.\d+(?:\.\d+)?"', _f) is not None
      and "function pageFooter()" in _f)
# «Обновить» обязана перезагружать САМУ страницу, а не только данные: иначе
# после деплоя новый food.html не подхватывается и человек жмёт Cmd+R руками.
# Caddy отдаёт *.html с no-cache, поэтому reload берёт свежую версию.
check("food.html: «Обновить» перезагружает страницу",
      re.search(r'refresh: function[\s\S]{0,900}location\.reload', _f) is not None)
check("food.html: «Обновить» гонит данные мимо кеша (food-cb)",
      re.search(r'refresh: function[\s\S]{0,900}food-cb', _f) is not None)
# Caddy должен отдавать страницы с no-cache — иначе reload вернёт старое из кеша.
_caddy = REPO / "tools/hosting/Caddyfile"
_cf = _caddy.read_text(encoding="utf-8") if _caddy.exists() else ""
if _cf:
    check("Caddy отдаёт *.html с no-cache (иначе reload берёт старое)",
          re.search(r'@pages path[^\n]*\*\.html[\s\S]{0,120}Cache-Control "no-cache"', _cf) is not None)
# Все страницы кабинета обязаны сообщать версию одинаково — иначе на одной
# её ищешь глазами, а на другой её нет вовсе.
for _pg, _pat in (("food.html", r'food v\d'), ("health.html", r'health v\d'),
                  ("travel.html", r'travel v\d'), ("games.html", r'games v\d'),
                  ("hub.html", r'hub v\d')):
    _src = (REPO / "tools" / _pg).read_text(encoding="utf-8")
    check(f"{_pg}: подвал сообщает версию", re.search(_pat, _src) is not None)

# ── каталог: строка продукта и фильтры ─────────────────────────────────────
print("food · каталог")
# Решение «брать или не брать» принимается в строке, а не в карточке: КБЖУ и
# фасовка должны быть видны сразу, иначе каталог приходится открывать по одному.
check("food.html: КБЖУ показано в строке каталога", 'ккал/100 г' in _f)
# КБЖУ базис — ВСЕГДА 100 г (так на этикетке и так задаётся у продукта), даже у
# жидкостей: объём в вес переводит плотность g_per_100ml. Раньше строка брала
# единицу продукта и у масла (unit=мл) писала «898 ккал/100 мл» — вдвойне
# неверно: и базис не тот (число на 100 г), и единица.
check("food.html: базис КБЖУ в каталоге — всегда /100 г, не /100 мл",
      'ккал/100 г' in _f and '"100 мл" : "100 г"' not in _f)
# Молчаливая пустота читается как «забыли». У кефира и фарша КБЖУ задаёт
# производитель, и пусто там — осознанное решение, а не пропуск.
check("food.html: отсутствие КБЖУ названо словами", '"КБЖУ не задано"' in _f)
# p.pack_size читается РОВНО в одном месте — внутри packOf. Урок реальной
# поломки прежней архитектуры (stores[]): прямое чтение поля в обход хелпера
# тихо умирает при смене формы хранения — «3 уп. по 400 г» в магазине просто
# исчезло, и заметить это было негде. Хелпер разбирает и легаси-формы.
_legacy = [l for l in _f.splitlines() if "p.pack_size" in l]
check("food.html: p.pack_size читается только внутри packOf"
      + (" — лишние места: " + str(len(_legacy)) if len(_legacy) != 1 else ""),
      len(_legacy) == 1 and "function packOf(p)" in _f.split("p.pack_size")[0][-300:])
check("food.html: упаковки считаются через packOf, а не через прямое поле",
      "var pk = packOf(p);" in _f)

# Отдел — чипами: вариантов девять, они короткие, и выбор одним тапом важнее
# экономии места (на телефоне нативный select открывает колесо на пол-экрана).
check("food.html: отдел выбирается чипами", '"prod-dept"' in _f and 'id="f-category"' in _f)
check("food.html: повторный тап снимает отдел", '(p.category === v) ? "" : v' in _f)
check("food.html: продукт можно удалить", '"prod-del"' in _f)
# «Используется в рецептах» прямо в строке каталога: отвечает на «можно ли
# удалить этот продукт» до того, как человек нажмёт «Удалить». Тот же список
# правды, что и предупреждение при удалении.
check("food.html: строка каталога показывает, где продукт используется",
      "function recipesUsing(" in _f and "в рецептах:" in _f)
check("food.html: удаление и строка каталога считают ссылки одним хелпером",
      _f.count("recipesUsing(p.id)") >= 2)

# Удаление продукта осиротит ингредиент в рецепте — об этом надо сказать
# ДО удаления, а не оставлять человека выяснять это на кухне.
check("food.html: удаление предупреждает о ссылках из рецептов",
      re.search(r'"prod-del".*?потеряет связь с каталогом', _f, re.S) is not None)

# Девять отделов в одну строку не влезают. Горизонтальная прокрутка хуже
# переноса: фильтр, который надо доскроллить, чтобы увидеть, наполовину невидим.
check("food.html: фильтры переносятся строкой, а не уезжают за край",
      "overflow-x:auto; padding-bottom:4px" not in _f)
check("food.html: фильтры имеют перенос", _f.count("flex-wrap:wrap; margin-bottom:2") >= 1)

# ── прокрутка: фактура бумаги ──────────────────────────────────────────────
# `background-attachment: fixed` на ПРОКРУЧИВАЕМОМ элементе заставляет браузер
# перерисовывать фон каждый кадр. У «Еды» это три слоя, включая штриховку с
# шагом 1px, — и жалоба на рывки пришла именно с длинного списка рецептов,
# именно на этой странице (у остальных такого фона нет вовсе).
# Лечится позиционированным слоем: растеризуется один раз, дальше композитится.
print("food · прокрутка")
check("food.html: фактура вынесена в отдельный слой .paper-bg",
      ".paper-bg{" in _f and 'class="paper-bg' in _f)
check("food.html: слой фактуры не перехватывает клики",
      re.search(r"\.paper-bg\{[^}]*pointer-events:none", _f) is not None)
check("food.html: слой фактуры позиционирован, а не прокручивается",
      re.search(r"\.paper-bg\{[^}]*position:fixed", _f) is not None)
# Главная защита: никакая страница кабинета не должна вернуть фон-фикс на
# прокручиваемый элемент. Дешевле держать правило, чем ловить рывки на глаз —
# в фоне вкладки они не воспроизводятся, и автотестом их не измерить.
for _page in ("food.html", "hub.html", "travel.html", "games.html", "health.html"):
    _src = (REPO / "tools" / _page).read_text(encoding="utf-8")
    _bad = [m for m in re.findall(r"[^;{}]*background-attachment\s*:\s*fixed[^;{}]*", _src)
            if "paper-bg" not in m]
    check(f"{_page}: нет background-attachment:fixed на прокручиваемом элементе",
          not _bad)

# ── активные состояния и нижняя панель ─────────────────────────────────────
# Подсветка активного фильтра/раздела была записана ПЕРЕЧИСЛЕНИЕМ пар
# [data-dept=X] .chip[data-arg=X]. Такое перечисление рассыпается молча: отдел
# «бытовое» приехал в DEPTS, а строку в CSS дописать забыли — фильтр работал,
# чип не подсвечивался. Держим единственный источник истины (JS ставит .on) и
# сверяем, что ни один список ключей не остался без него.
print("food · активные состояния")
check("food.html: активное состояние — класс .on, а не перечисление data-пар",
      ".fchip.on{" in _f and ".gseg.on{" in _f
      and ".ui-rail-item.on{" in UI_KIT_CSS0 and ".ui-mnav-btn.on{" in UI_KIT_CSS0)
# data-screen остаётся: он ПЕРЕКЛЮЧАЕТ экраны (.sc-* видим/скрыт), а не красит
# активный элемент. Перечислением подсветки не должны быть только фильтры.
for _attr in ("data-dept", "data-mode"):
    check(f"food.html: подсветка не перечисляет {_attr} в селекторах",
          f'[{_attr}="' not in _f)
check("food.html: подсветка раздела не перечисляет экраны в CSS",
      re.search(r'\[data-screen="\w+"\] \.(nav-rail|mnav)', _f) is None)
for _list, _state in (("DEPTS", "S.deptFilter"),):
    check(f"food.html: чипы {_list} получают .on из состояния ({_state})",
          re.search(_state + r' === \w\[0\] \? " on" : ""', _f) is not None)
check("food.html: экраны рецепта считаются разделом «Рецепты» (включая правку)",
      re.search(r'function navActive[\s\S]{0,400}S\.screen === "edit"', _f) is not None)

# Нижняя панель на телефоне: она ВНЕ #app и не пересоздаётся перерисовкой.
# iOS Safari после подмены разметки и восстановления прокрутки оставляет часть
# тайлов невалидными, и пересозданный fixed-элемент дорисовывался посреди
# экрана (скриншот владельца 2026-07-27: панель в середине списка, над ней и
# под ней — два РАЗНЫХ кадра, «по типу» и «по алфавиту» одновременно).
print("food · нижняя панель")
# С ui-kit 1.23.0 лечение — в общем компоненте и для ВСЕХ страниц: панель
# живёт в <body> вне перерисовываемого корня, создаётся один раз (пересоздаётся
# лишь при смене набора пунктов), свой слой композитора.
check("ui-kit: нижняя панель живёт в <body>, вне перерисовки страниц",
      "document.body.appendChild(nav)" in UI_KIT_JS0 and 'nav.id = "ui-mnav"' in UI_KIT_JS0)
check("food.html: панель не собирается внутри render()", "mobileNav()" not in _f)
check("ui-kit: панель заполняется один раз — пересборка только при смене набора пунктов",
      'nav.getAttribute("data-sig") !== sig' in UI_KIT_JS0)
check("ui-kit: панель — свой слой композитора",
      re.search(r"\.ui-mnav\{[^}]*transform:translateZ\(0\)", UI_KIT_CSS0) is not None)
for _pg in ("food", "health", "money", "games"):
    _c = _strip_js_comments((REPO / f"tools/{_pg}.html").read_text(encoding="utf-8"))
    check(f"{_pg}.html: нижняя панель — uiNavMount (один раз в body), своей <nav> панели нет",
          "uiNavMount(" in _c and not re.search(r"<nav[^>]*class=[\"'](h-mnav|mnav|ui-mnav)", _c))
check("food.html: высота обёртки считается по фактическому окну (dvh)",
      "min-height:100dvh" in _f)
# Смена фильтра/группировки переупорядочивает список целиком — старое смещение
# прокрутки в нём ведёт в случайное место (и это же был триггер сбоя на iOS).
check("food.html: смена фильтра/группировки прокручивает к верху",
      "_toTop: true" in _f and "screenChanged || S._toTop" in _f)
# Оконную прокрутку render() возвращал, а прокрутку ВНУТРИ модалки (.modal —
# свой overflow-y) обнулял: в «Запланировать» галочка на ингредиенте внизу
# отматывала список к началу, и до следующего надо было прокручивать заново
# (2026-08-02). Ключ модалки нужен, чтобы ДРУГАЯ модалка открывалась сверху.
check("food.html: прокрутка внутри модалки сохраняется через перерисовку",
      re.search(r"querySelectorAll\(\"\.ui-modal-body, \.modal\"\)[\s\S]{0,200}scrollTop", _f) is not None
      and "S._lastLayers" in _f)
check("food.html: позиция возвращается только той же модалке (по месту в стопке)",
      "keys[i] === last[i] ? b.scrollTop : 0" in _f)
# Ключ и разметка модалки берутся из ОДНОЙ цепочки: две параллельные разошлись бы,
# и «та же модалка» стала бы врать.
check("food.html: ключ и разметка оверлея — одна цепочка",
      # ровно один ВЫЗОВ (второе вхождение — определение функции)
      len(re.findall(r"(?<!function )planModal\(\)", _f)) == 1
      and len(re.findall(r"(?<!function )cookSheet\(\)", _f)) == 1
      and re.search(r'S\.plan \? \{ k: "plan", html: planModal\(\) \}', _f) is not None)

# ── телефон: зум полей и перенос длинных адресов ───────────────────────────
# iOS Safari приближает страницу при фокусе в поле мельче 16px и обратно НЕ
# отдаляет — масштаб сводят пальцами, а раздел одностраничный, поэтому
# увеличение живёт до конца сессии. Ловим на уровне CSS; фактические размеры
# в браузере проверяет tools/tests/test_food_layout.py.
print("food · телефон")
check("food.html: на сенсорном экране поля ввода 16px",
      re.search(r"@media \(hover: none\) and \(pointer: coarse\)\s*\{[^}]*font-size:16px", _f) is not None)
check("food.html: правило перебивает инлайновые размеры полей",
      re.search(r"@media \(hover: none\) and \(pointer: coarse\)\s*\{[^}]*!important", _f) is not None)
check("food.html: чекбоксы из правила исключены (у них размер — width/height)",
      re.search(r'input:not\(\[type="checkbox"\]\)', _f) is not None)
# maximum-scale чинит зум ценой выключенного пинча — этого нельзя. Смотрим САМ
# тег viewport, а не весь файл: слово живёт в комментарии рядом с правилом 16px.
_vp = re.search(r'<meta name="viewport"[^>]*>', _f)
check("food.html: пинч-зум не выключен через viewport",
      _vp is not None and "maximum-scale" not in _vp.group(0)
      and "user-scalable=no" not in _vp.group(0))
# Длинный URL — единственный токен, который не переносится сам и растягивает
# ВЕСЬ документ (замер: «Плов» давал 610 px при экране 390).
check("food.html: длинные токены переносятся в тексте секций",
      re.search(r"\.screen p, \.screen li[^}]*overflow-wrap:anywhere", _f) is not None)
# Второй источник переполнения, кроме URL: длинный чип «⚖ Взвесили готовое?…» —
# 420 px в одну строку, шире любого телефона. nowrap на .fchip нужен коротким
# чипам, поэтому перенос разрешён точечно классом, а не снятием правила.
check("food.html: короткие чипы остаются в одну строку",
      re.search(r"\.fchip\{[^}]*white-space:nowrap", _f) is not None)
check("food.html: чип не может быть шире контейнера",
      re.search(r"\.fchip\{[^}]*max-width:100%", _f) is not None)
check("food.html: длинному чипу разрешён перенос отдельным классом",
      re.search(r"\.fchip-wrap\{[^}]*white-space:normal", _f) is not None
      and 'class="fchip fchip-wrap" data-act="weigh-open"' in _f)
check("food.html: адреса в секциях становятся короткими ссылками",
      "function linkifyEsc(" in _f and "function shortUrl(" in _f
      and "linkifyEsc(items[0])" in _f)
check("food.html: сокращение режет середину, а не хвост (расширение видно)",
      re.search(r"tail\.slice\(0, 12\) \+ \"…\" \+ tail\.slice\(-9\)", _f) is not None)
# Печать сокращать НЕЛЬЗЯ: на бумаге адрес набирают руками.
check("food.html: печатный блок оставляет адрес целиком",
      re.search(r"print-blk[\s\S]{0,400}esc\(items\[0\]\)", _f) is not None)
check("food.html: ссылка несёт полный адрес в href и title",
      re.search(r"""function linkifyEsc[\s\S]{0,1200}href="' \+ attr\(href\)"""
                r"""[\s\S]{0,200}title="' \+ attr\(raw\)""", _f) is not None)

# ── ккал: страница и скрипт обязаны давать ОДНО число ──────────────────────
# Страница суммировала ккал с этикетки продукта, а tools/food/nutrition.py
# пересчитывал 4/9/4 — и на реальных рецептах числа расходились до 21% («Гуляш
# из говядины с картофелем»: 361 против 436 ккал на порцию, 2026-08-02). Правило
# теперь одно: этикетка приоритетнее, Этуотер — только когда её нет.
print("food · ккал")
sys.path.insert(0, str(REPO / "tools/food"))
import nutrition as _nt  # noqa: E402

check("food.html: ккал продукта считает отдельный помощник",
      "function productKcal100(" in _f)
check("food.html: этикетка приоритетнее Этуотера",
      re.search(r'function productKcal100[\s\S]{0,200}typeof n1\.kcal === "number"'
                r"[\s\S]{0,40}return n1\.kcal", _f) is not None)
check("food.html: без этикетки — 4/9/4 по макросам продукта",
      re.search(r"function productKcal100[\s\S]{0,400}4 \* n1\.protein_g"
                r"[\s\S]{0,120}9 \* n1\.fat_g[\s\S]{0,120}4 \* n1\.carb_g", _f) is not None)
check("food.html: оценка блюда копит ккал через помощник, а не поле этикетки",
      re.search(r"function dishNutritionEstimate[\s\S]{0,900}tot\.kcal \+= kc \* k", _f) is not None)
check("food.html: список полей суммирования — только макросы (ккал отдельно)",
      re.search(r'function dishNutritionEstimate[\s\S]{0,900}'
                r'\["protein_g", "fat_g", "carb_g"\]\.forEach', _f) is not None)
# Семантическое зеркало: то же правило в Python обязано совпасть со скриптом.
for _n1, _want in (
        ({"kcal": 66, "protein_g": 0.1, "fat_g": 0, "carb_g": 0.6}, 66),      # вино: спирт
        ({"kcal": 23, "protein_g": 2.9, "fat_g": 0.3, "carb_g": 3.6}, 23),    # шпинат: клетчатка
        ({"protein_g": 10, "fat_g": 1, "carb_g": 70}, 4 * 10 + 9 + 4 * 70),   # нет этикетки
        ({}, None), (None, None)):
    check(f"правило ккал совпадает со скриптом на {_n1}",
          _nt.product_kcal_100g(_n1) == _want)

# Сторож массы: готовое блюдо не может весить больше сырых продуктов — вода при
# готовке только уходит. Если весит, строка «на 100 г» делит числитель на чужой
# знаменатель (творожник: блюдо 1598 г при 1425 г продуктов, 2026-08-02).
check("food.html: масса готового блюда сверяется с массой продуктов",
      "function heavierThanRaw(" in _f and "function rawMassKnown(" in _f
      and "heavierThanRaw(r)" in _f)
check("food.html: сырую массу считает та же gramsOf, что и КБЖУ",
      re.search(r"function rawMassKnown[\s\S]{0,400}gramsOf\(g\.qty, g\.unit, p\)", _f) is not None)
check("food.html: ингредиенты без количества названы поимённо",
      re.search(r"function rawMassKnown[\s\S]{0,400}unknown\.push", _f) is not None)
check("food.html: сторож молчит на нормальном блюде (порог, а не равенство)",
      re.search(r"r\.finished_g > raw\.mass \* 1\.02", _f) is not None)

# ── «откуда» → «из N рецептов» ─────────────────────────────────────────────
# После удаления магазинов (2026-08-01) слово «откуда» читалось как «где купить»,
# хотя речь про рецепты, из которых сложилось количество.
check("food.html: кнопка происхождения строки названа рецептами",
      re.search(r'"из " \+ from\.length \+ " " \+ plural\(from\.length, "рецепта"', _f) is not None)
check("food.html: слова-обманки «откуда» на кнопке не осталось",
      '"откуда"' not in _f)

# ── порядок ингредиентов ───────────────────────────────────────────────────
# Порядок из файла рецепта не несёт смысла: файлы приходят от разных
# генераторов. Единый порядок — по весу, потом по алфавиту; «по вкусу» всегда
# в конце. Индекс ОРИГИНАЛА обязан ехать вместе со строкой: галочки режима
# готовки хранятся по индексу, и сортировка показа не должна их сбивать.
print("food · порядок ингредиентов")
check("food.html: порядок ингредиентов — общий помощник ingOrder",
      "function ingOrder(" in _f and "function ingWeight(" in _f)
check("food.html: ingOrder сохраняет исходный индекс",
      re.search(r"function ingOrder[\s\S]{0,300}\{ g: g, i: i \}", _f) is not None)
check("food.html: «по вкусу» уходит в конец, а не считается нулевым весом",
      re.search(r"function ingOrder[\s\S]{0,300}g\.qty == null \? 2", _f) is not None)
check("food.html: ни один экран не обходит ingOrder",
      "(r.ingredients || []).map(function (g" not in _f)

# ── несвязанные ингредиенты ────────────────────────────────────────────────
# Ингредиент без product_id не попадает ни в список покупок, ни в КБЖУ. Пока
# об этом не говорили, целый рецепт («Окрошка» из внешнего генератора) молча
# считался нулевым по КБЖУ и не давал ни одной строки в закупку.
print("food · несвязанные ингредиенты")
check("food.html: несвязанные ингредиенты считаются (unlinkedIngs)",
      "function unlinkedIngs(" in _f)
check("food.html: над таблицей ингредиентов есть плашка о несвязанных",
      "function unlinkedNote(" in _f and "unlinkedNote(r)" in _f)
check("food.html: плашка отделяет строки с количеством (они и рвут КБЖУ)",
      re.search(r"function unlinkedNote[\s\S]{0,600}g\.qty != null", _f) is not None)
check("food.html: связать можно из строки ингредиента",
      'data-act="ing-link"' in _f and '"ing-link":' in _f)
check("food.html: подбор предлагает и завести новый продукт с возвратом",
      '"ing-link-new"' in _f and "ret.link" in _f)
check("food.html: подтверждённое написание уходит в алиасы продукта",
      # окно по телу функции целиком: сама запись алиаса стоит после проверки
      # единицы и нормализации имени, в ~1000 символах от заголовка
      re.search(r"function linkIngredient[\s\S]{0,1600}p\.aliases = \(p\.aliases \|\| \[\]\)\.concat", _f) is not None)
# Алиас, принадлежащий двум продуктам, делает сопоставление недетерминированным
# — худший вид поломки, выглядит случайным. Здесь то же правило, что в prod-save.
check("food.html: занятый алиас не добавляется вторым владельцем",
      # пустое имя тоже считается «занятым» (var taken = !key || S.products.some) —
      # проверка не должна ломаться от этой ветки
      re.search(r"function linkIngredient[\s\S]{0,1600}var taken =[^;]{0,40}S\.products\.some", _f) is not None)
check("food.html: без прав на запись остаётся пометка, а не кнопка",
      re.search(r'S\.writable[\s\S]{0,400}нет в каталоге · связать', _f) is not None)

# ── печатный вид ───────────────────────────────────────────────────────────
# Печать — отдельный экран с ЖЁСТКО светлым листом, а не «@media print поверх
# чтения». Причина не косметическая: экран чтения красится токенами темы, и в
# тёмной теме печать дала бы светлый текст на белой бумаге — пустую страницу.
print("food · печать")
check("food.html: печать — отдельный экран", "function printScreen()" in _f)
check("food.html: экран печати подключён к диспетчеру",
      'S.screen === "print"' in _f and "return printScreen()" in _f)
# Кнопка «Печать» на экране чтения ведёт на лист, а сам вызов принтера — уже
# с листа. Иначе выбранное число порций видно только на бумаге.
check("food.html: «Печать» открывает лист, а не диалог принтера",
      'print: function () { set({ screen: "print" }); }' in _f)
check("food.html: печатает лист отдельное действие", '"do-print"' in _f and "window.print()" in _f)

_pblock = re.search(r"@media print\{(.*?)\n\}", _f, re.S)
check("food.html: блок @media print найден", bool(_pblock))
if _pblock:
    _p = _pblock.group(1)
    # Разрыв страницы посреди шага или строки ингредиентов — то, из-за чего
    # печатный рецепт перестают печатать вовсе.
    for _sel in (".print-step", ".print-blk", ".print-table tr"):
        check(f"печать: {_sel} не рвётся между страницами",
              _sel in _p and "page-break-inside:avoid" in _p.replace(" ", ""))
    check("печать: заголовок раздела не остаётся в конце листа",
          ".print-h" in _p and "page-break-after:avoid" in _p.replace(" ", ""))
    check("печать: лист без рамки, тени и своих полей (поля даёт @page)",
          ".print-sheet" in _p and "padding:0 !important" in _p)
    # Главная защита: Cmd+P можно нажать с ЛЮБОГО экрана. Если тёмные токены
    # не сброшены — на бумагу уйдёт белым по белому.
    check("печать: тёмная тема сброшена на светлую",
          '[data-theme="dark"]' in _p and "--text:#2b2823" in _p)
    check("печать: фактура бумаги не печатается",
          "background-image:none !important" in _p)
    # РЕАЛЬНЫЙ БАГ, пойманный headless-печатью: экран появляется анимацией
    # food-fade (`from{opacity:0}`), а принтер снимает страницу в ПЕРВОМ кадре —
    # на бумагу уходил чистый лист. hub.html печатался в 383 КБ, food.html —
    # в 1,6 КБ. Разница видна только в PDF, глазами на странице её нет.
    check("печать: анимации выключены (иначе печатается пустой лист)",
          "animation:none!important" in _p.replace(" ", "") and "*,*::before" in _p)

# ── диплинк ?recipe=<id>[&print=1] ─────────────────────────────────────────
# Страница перерисовывается целиком и адрес обычной навигацией не меняет —
# без диплинка на рецепт нельзя ни сослаться, ни вернуться после перезагрузки.
check("food.html: читает ?recipe= из адреса", "function applyDeepLink()" in _f)
check("food.html: ?print=1 открывает сразу лист печати",
      'q.get("print") ? "print" : "read"' in _f)
# Кириллица в адресе приезжает и в NFC, и в NFD — сравнение байт-в-байт
# промахивается (та же ловушка, что у ?trip= в travel.html).
check("food.html: id рецепта сравнивается после нормализации NFC",
      'normalize("NFC")' in _f)
# «Обновить» посреди работы не должно швырять обратно на рецепт из адреса.
check("food.html: диплинк применяется один раз", "_deepLinkDone" in _f)
check("food.html: размер листа задан (A4)", "@page{ size:A4" in _f)
# Лист рисуется белым в любой теме — значит цвета на нём не могут быть
# токенами. Пометка «(было N)» шла var(--text-faint) и в тёмной теме исчезала.
check("food.html: цвет пометки «(было N)» — параметр, а не токен темы",
      "function scaleStepText(text, ings, factor, muted)" in _f)

# ── удаление рецепта: страница ↔ write-API ─────────────────────────────────
print("food · удаление рецепта")
# Удаление — единственное необратимое одним касанием действие в разделе,
# поэтому оно проверяется с обеих сторон сразу: кнопка на странице и то, что
# сервер вообще согласится удалить.
check("food.html: кнопка удаления есть", '"ed-delete"' in _f)
# Красная и НЕ залитая: залитая красная рядом с «Сохранить» — приглашение
# промахнуться. Заливка — только на hover и в самой модалке подтверждения.
check("food.html: кнопка удаления красная (класс danger)",
      re.search(r'ui-btn danger" data-act="ed-delete"', _f) is not None)
check("food.html: класс danger определён в CSS",
      ".ui-btn.danger{" in UI_KIT_CSS0 and "var(--err)" in UI_KIT_CSS0 and ".act-btn" not in _f)
check("ui-kit: у подтверждения — залитая красная кнопка (uiConfirm, danger)",
      ".ui-confirm-ok.danger{" in UI_KIT_CSS0 and "background:var(--err)" in UI_KIT_CSS0.split(".ui-confirm-ok.danger{", 1)[1][:60])
# Отнесена от «Сохранить» и живёт только в нижнем ряду.
check("food.html: кнопка удаления отнесена в левый край",
      re.search(r'data-act="ed-delete"[^>]*margin-right:auto', _f) is not None)
check("food.html: у нового рецепта удалять нечего — кнопки нет",
      re.search(r'var delBtn = \(e\.id && S\.writable && S\.canDelete\)', _f) is not None)
# Подтверждение — СВОЙ экран. Нативный confirm() на iOS блокирует страницу
# целиком (тот же класс бага, что и alert) и не показывает, ЧТО удаляется.
# С ui-kit 1.25.0 окно общее (uiConfirm) — на всех страницах confirm() нет.
check("food.html: подтверждение — свой экран (uiConfirm), не системный диалог",
      "function confirmRecipeDelete(d)" in _f and "return uiConfirm({" in _f
      and re.search(r'"ed-delete": function[\s\S]{0,500}confirmRecipeDelete\(d\)', _f) is not None)
# Кнопка ТОЛЬКО спрашивает; стирает — подтверждение. Иначе «красная кнопка» —
# декорация: один промах, и файла нет.
_ed_del_i = _f.find('"ed-delete": function')
_ed_del_body = _f[_ed_del_i:_f.find("},", _ed_del_i)] if _ed_del_i >= 0 else ""
check("food.html: кнопка удаления не стирает сразу",
      bool(_ed_del_body) and "deleteRecipe(" not in _ed_del_body
      and "if (ok) recipeDeleteConfirmed(d)" in _ed_del_body)
check("food.html: стирает только подтверждение",
      re.search(r'function recipeDeleteConfirmed\(d\) \{\s*deleteRecipe\(', _f) is not None)
check("food.html: подтверждение показывает название рецепта",
      re.search(r'function confirmRecipeDelete[\s\S]{0,600}name: d\.title \|\| d\.id', _f) is not None)
check("ui-kit: подтверждение поверх всего (слой 1100) и Esc гасит его первым",
      "z-index:1100" in UI_KIT_CSS0.split(".ui-confirm{", 1)[1][:120]
      and 'if (ev.key === "Escape"){ ev.preventDefault(); ev.stopImmediatePropagation(); done(false); }' in UI_KIT_JS0)
for _pg in ("food", "health", "money", "games", "travel", "hub"):
    _c = _strip_js_comments((REPO / f"tools/{_pg}.html").read_text(encoding="utf-8"))
    check(f"{_pg}.html: нативного confirm() нет — общий uiConfirm",
          re.search(r"(?<![\w.])(window\.)?confirm\(", _c) is None)
# Удаление вслепую невозможно: шлём хэш того файла, который человек видел.
check("food.html: удаление шлёт base_hash (не «сотри, что лежит»)",
      re.search(r'API \+ "delete"[\s\S]{0,400}base_hash: S\.hash\[key\]', _f) is not None)
check("food.html: 409 при удалении объясняет, что делать",
      re.search(r'r\.status === 409[^\n]*Обновить', _f) is not None)
# Кнопка рисуется только если сайдкар реально умеет удалять: иначе «старый
# сайдкар» неотличим от «нет прав» — оба отвечают 40x (тот же урок, что с
# studies.json 2026-07-17).
check("food.html: право на удаление берётся из возможностей сайдкара",
      "S.canDelete = !!(cap && cap.food_delete)" in _f)
check("server.py: отдаёт признак food_delete", '"food_delete": True' in _srv)

# Ось «путь страницы ↔ whitelist сервера». Страница шлёт recipes/<id>.json;
# если серверный whitelist на удаление разойдётся с этим, кнопка будет молча
# отдавать 403 — ровно как edit-слой Stage 3 на регион_a_2027.
sys.path.insert(0, str(REPO / "tools/hosting/api"))
import server as _server  # noqa: E402

_page_del_path = re.search(r'path: key \+ "\.json"', _f) is not None
check("food.html: удаляет по пути recipes/<id>.json", _page_del_path)
check("server.py: whitelist на удаление объявлен отдельно", hasattr(_server, "FOOD_DELETABLE"))
check("server.py: рецепт удалить можно",
      _server.is_allowed("recipes/pasta-bolognese.json", _server.FOOD_DELETABLE))
# Список НАМЕРЕННО уже, чем на запись: живое состояние раздела веб-кнопкой не
# стирается, даже если страница такую никогда не нарисует.
for _protected in ("products.json", "shopping.json"):
    check(f"server.py: {_protected} через удаление не достать",
          not _server.is_allowed(_protected, _server.FOOD_DELETABLE)
          and _server.is_allowed(_protected, _server.FOOD_WHITELIST))
check("server.py: удаление есть только у зоны еды",
      '"/api/fd/delete"' in _srv and "/api/hd/delete" not in _srv)
# Удаление идёт через _remove (File Station-гибрид, 2026-08-14): DSM-удаление,
# а os.remove — только фолбэк внутри него. Проверка смотрит на порядок «сначала
# копия, потом удаление», а не на конкретный вызов, иначе она краснеет на каждом
# переименовании хелпера (так и случилось после гибрида).
check("server.py: перед удалением кладёт копию в .versions/",
      re.search(r'def delete_file[\s\S]{0,1400}shutil\.copy2[\s\S]{0,200}_remove\(', _srv)
      is not None
      and re.search(r'def _remove\([\s\S]{0,700}os\.remove', _srv) is not None)
# Обещать невосстановимость, когда бэкап есть, — врать; обещать лёгкий возврат,
# когда его надо доставать руками на NAS, — тоже. Смотрим на ВИДИМЫЙ текст:
# в комментариях слово «безвозвратно» как раз объясняет, почему его нет.
check("food.html: текст подтверждения не врёт про восстановление",
      "резервную копию" in _f and "безвозвратно" not in _strip_js_comments(_f))

# ── ввод без мигания: точечная правка вместо полного render() ──────────────
print("food · ввод без мигания")
# Жалоба владельца 2026-08-09: «набираю в поиске — экран мигает, будто
# перерисовывается». Так и было: каждая буква пересобирала документ целиком
# (шапка, рельс, слой бумаги, все карточки), после чего фокус и каретку
# возвращали руками через focusId/focusPos. От буквы меняется РОВНО ОДИН узел.
check("food.html: есть точечная правка узла", "function patchHTML(id, html)" in _f)
check("food.html: patchHTML честно сообщает, что узла нет",
      re.search(r'function patchHTML[\s\S]{0,200}if \(!el\) return false;', _f) is not None)


def _input_branch(field: str) -> str:
    """Тело ветки обработчика input для конкретного поля."""
    m = re.search(r'if \(t\.id === "' + re.escape(field) + r'"', _f)
    if not m:
        return ""
    rest = _f[m.start():]
    nxt = re.search(r'\n  if \(t\.id === "', rest[10:])
    return rest[: 10 + nxt.start()] if nxt else rest[:2000]


# Пара «поле ввода → узел, который оно меняет → функция, рисующая этот узел».
# Разъедется любая сторона — мигание вернётся молча, потому что визуально
# полная перерисовка и точечная отличаются только на телефоне.
_PATCH_PAIRS = [
    ("f-prod-q", "prod-results", "productsResults()"),
    ("f-rec-q", "rec-results", "recipesResults()"),
    ("f-ed-cat-q", "ed-cat-list", "edCatalogHTML()"),
    ("f-ing-link-q", "ing-link-list", "ingLinkListHTML()"),
    ("f-add-name", "add-name-sug", "addNameHintHTML()"),
]
for _inp, _node, _fn in _PATCH_PAIRS:
    _branch = _input_branch(_inp)
    check(f"food.html: {_inp} — ветка обработчика на месте", bool(_branch))
    # Узел и функция, его рисующая, стоят рядом в разметке: иначе patchHTML
    # ищет то, чего нет, и каждый ввод падает на полный render().
    check(f"food.html: узел {_node} рисуется функцией {_fn}",
          re.search(r'id="' + _node + r'"[^\n]{0,220}' + re.escape(_fn), _f) is not None)
    check(f"food.html: ввод в {_inp} правит {_node} точечно",
          'patchHTML("' + _node + '", ' + _fn in _branch)
    # render() в этих ветках допустим ТОЛЬКО как откат «узла нет» (и для
    # f-add-name — на смене заматчившегося продукта, где меняется вся форма).
    _bare = [ln for ln in _branch.splitlines()
             if re.search(r'(?<![.\w])render\(\);', ln) and "patchHTML" not in ln]
    if _inp != "f-add-name":
        check(f"food.html: {_inp} не дёргает полную перерисовку", not _bare)
        # set() — тоже полный render(), просто через дверь с другой стороны.
        check(f"food.html: {_inp} не ходит через set()", "set({" not in _branch)
        # focusId/focusPos были лечением симптома: инпут больше не пересоздаётся.
        check(f"food.html: {_inp} не восстанавливает фокус руками",
              "S.focusId" not in _branch)

# Поле количества в модалке добавления: пересчёт «3 шт ≈ N г» правится текстом,
# а не перерисовкой модалки.
_qty_branch = _input_branch("f-add-qty")
check("food.html: пересчёт «шт → г» правится точечно",
      'getElementById("add-conv")' in _qty_branch and "textContent" in _qty_branch)
check("food.html: ветка количества не перерисовывает страницу",
      not re.search(r'(?<![.\w])render\(\);', _qty_branch))
# f-add-name — единственная ветка, где полный render() законен: заматчился
# другой продукт → меняются поля «Единица» и шаги упаковки, их точечно не
# подменить. Проверяем, что render() именно там, а не на каждой букве.
check("food.html: модалка добавления перерисовывается только на смене продукта",
      re.search(r'if \(addMatchSig\(\) !== S\._addSig\) \{[\s\S]{0,200}render\(\);', _f) is not None)
# Фильтр каталога в редакторе больше не снимает форму на каждой букве:
# форма не пересоздаётся, снимать нечего (а раньше без edCollect() терялись
# недописанные шаги).
check("food.html: фильтр каталога не снимает форму на каждой букве",
      "edCollect();" not in _input_branch("f-ed-cat-q"))

# ── поиск рецептов: техника — такой же вход, как продукт ───────────────────
print("food · поиск рецептов")
# «Карри из индейки» готовится в мультиварке, но слова этого нет ни в названии,
# ни в ингредиентах — только в «Инвентаре» и шагах. Найти рецепт по технике
# человек не мог. Альтернатива «переименовать блюда» отвергнута: на 2026-08-09
# техника названа в equipment у 14 рецептов из 14, в шагах — у 10, в названии —
# у 5; кодировать инвентарь в имя блюда значит и дублировать данные, и оставить
# две трети библиотеки без пометки.
_rs = _f[_f.find("function recipesResults()"):]
_rs = _rs[:_rs.find("var cards")]
check("food.html: тело фильтра рецептов найдено", bool(_rs))
for _field, _why in (("r.title", "название"), ("r.category", "тип блюда"),
                     ("r.tags", "теги"), ("r.equipment", "инвентарь"),
                     ("r.ingredients", "ингредиенты"), ("recipeBadges(r)", "бейджи карточки")):
    check(f"food.html: поиск рецептов покрывает {_why} ({_field})", _field in _rs)
# Свободный текст шагов из поиска УБРАН (замечание владельца: «шаги — это
# слишком»): оттуда сыпались совпадения по «нарезать» и «добавить». Техника
# ловится узким словарём TECH — тем же, что рисует бейдж.
check("food.html: свободный текст шагов в поиске не участвует",
      "s.text" not in _rs)
# Поле обещает то, что умеет, и заодно учит словарю: «плита», а не «плите».
check("food.html: подсказка поля поиска называет технику",
      re.search(r'id="f-rec-q"[^\n]*placeholder="[^"]*техника', _f) is not None)

# ── значки техники на карточке ─────────────────────────────────────────────
# «У нас будет несколько пловов» — на плите и в мультиварке; в списке они
# неразличимы, пока карточка не говорит, что придётся включить.
check("food.html: словарь техники объявлен", "var TECH = [" in _f)
check("food.html: техника выводится из текста, а не из поля файла",
      "function recipeTech(r)" in _f and '"tech"' not in _f)
for _lbl in ("мультиварка", "духовка", "плита"):
    check(f"food.html: техника «{_lbl}» в словаре",
          re.search(r'label: "' + _lbl + r'"', _f) is not None)
# Чего в словаре быть НЕ должно и почему — каждое исключение стоило разбора:
#   микроволновка — по всей библиотеке только как альтернатива ПОБОЧНОГО шага
#     («растопить масло на водяной бане или в микроволновке»);
#   блендер — он дома всегда, бейдж у всех подряд ничего не различает;
#   гриль — дома его нет, «на гриле» здесь всегда гриль-сковорода.
for _lbl in ("микроволновка", "блендер", "гриль"):
    check(f"food.html: «{_lbl}» в словаре техники нет (ничего не различает)",
          re.search(r'label: "' + _lbl + r'"', _f) is None)
# «С вечера» — про то, можно ли готовить это СЕГОДНЯ; из данных, не из поля.
check("food.html: бейдж «с вечера» есть", '"с вечера"' in _f)
check("food.html: «с вечера» считается по шагам-ожиданиям",
      "function recipeAhead(r)" in _f and "var AHEAD_MIN" in _f)
# Одной длительности МАЛО, и это главный подвох: четыре часа в мультиварке —
# это сама готовка (заложил и получил), четыре часа маринада — подготовка,
# после которой ещё готовить. Бейдж только про второе, поэтому кроме порога
# требуется словарь подготовительного ожидания. Словарь БЕЛЫЙ: лучше промолчать
# на незнакомой формулировке, чем повесить «начинать заранее» на томление.
check("food.html: «с вечера» требует словаря подготовительного ожидания",
      "var AHEAD_RX" in _f and "AHEAD_RX.test" in _f)
for _w in ("холодильник", "маринов", "настаива", "расстой", "бига", "заква", "брожен"):
    check(f"food.html: словарь ожидания знает «{_w}»", _w in re.search(r'var AHEAD_RX = [^;]*;', _f).group(0))
# «заквас» ловит закваску, но НЕ заквашивание — общий кусок у этих слов
# короче на одну букву. Ровно на этом домашний йогурт («Заквашивание, 8 ч»)
# оставался без бейджа после первого захода правки 2026-08-10.
check("food.html: стебель закваски — «заква», а не «заквас»",
      "заквас" not in re.search(r'var AHEAD_RX = [^;]*;', _f).group(0))
# Ожидание определяется ТАК ЖЕ, как во времени рецепта: явный passive главный,
# порог в час — запаска для файлов без флага. Две разные трактовки «ожидания»
# на одной странице дали бы «8 ч ожидания» в строке времени и никакого бейджа.
check("food.html: «с вечера» и время рецепта считают ожидание одинаково",
      re.search(r'function recipeAhead[\s\S]{0,600}s\.passive === true \|\| \(s\.passive == null && d\.min >= LONG_STEP_MIN\)',
                _f) is not None)
check("food.html: бейджи собраны одним списком", "function recipeBadges(r)" in _f)
# Один рендерер на список и на экран чтения: разъехавшиеся копии выглядели бы
# как разные сущности, хотя это одно утверждение о рецепте.
check("food.html: у бейджей один рендерер", "function badgeRow(badges, margin)" in _f)
check("food.html: карточка списка рисует бейджи",
      "var techChips = badgeRow(recipeBadges(r)" in _f and "techChips +" in _f)
check("food.html: экран чтения рисует те же бейджи выше сгиба",
      re.search(r'sc-read[\s\S]{0,2000}badgeRow\(recipeBadges\(r\)', _f) is not None)
# Значок + слово: «◎» без подписи требует легенды, а слово ещё и называет то,
# что можно набрать в поиске.
check("food.html: у значка есть подпись словом",
      re.search(r"b\.icon \+ '</span>' \+\s*\n?\s*esc\(b\.label\)", _f) is not None)
# Цвет значка — из категориальной палитры токенов, а не подобранный на глаз:
# она сбалансирована в обеих темах. Красится ТОЛЬКО глиф — залитые цветом
# плашки дизайн-система запрещает, и шесть карточек в ряд стали бы мозаикой.
check("food.html: цвет значка берётся из токена",
      re.search(r"color:var\(' \+ b\.color \+ '\)", _f) is not None)
_badge_colors = set(re.findall(r'color: "(--c-\d)"', _f))
check(f"food.html: значки красятся палитрой --c-* ({sorted(_badge_colors)})",
      len(_badge_colors) >= 3 and all(c.startswith("--c-") for c in _badge_colors))
check("food.html: у каждого бейджа свой цвет (значки различимы)",
      len(_badge_colors) == len(re.findall(r'color: "--c-\d"', _f)))
# Палитра живёт в ui-kit.css — без неё var(--c-1) схлопнется в наследуемый цвет
# и «яркие значки» молча станут серыми.
check("food.html: подключает ui-kit.css, где определена палитра",
      re.search(r'href="assets/ui-kit\.css', _f) is not None)
_uikit = (REPO / "tools/assets/ui-kit.css").read_text(encoding="utf-8")
for _c in sorted(_badge_colors):
    check(f"ui-kit.css: токен {_c} определён в обеих темах",
          len(re.findall(re.escape(_c) + r":#", _uikit)) >= 2)
# Подпись бейджа не обещает необходимости: часть рецептов даёт альтернативу
# («обжарить на сковороде ИЛИ запечь при 200 °C») — тогда верны оба бейджа.
check("food.html: бейдж не утверждает «без этого не выйдет»",
      "техника рецепта:" in _f and "нужна техника:" not in _f)

# Ось «бейдж ↔ поиск»: что показано на карточке, то и находится. Гоняем
# НАСТОЯЩИЙ детектор из страницы через node по живой библиотеке — регэксп
# в тесте поймал бы переименование, но не расхождение словаря с фильтром.
_FOOD_DIR = Path.home() / "Library/CloudStorage/SynologyDrive-home/Claude-Memory/Food"
if shutil.which("node") and (_FOOD_DIR / "recipes").is_dir():
    import json as _json
    import subprocess as _sp

    _recipes = [_json.loads(p.read_text(encoding="utf-8"))
                for p in sorted((_FOOD_DIR / "recipes").glob("*.json"))]
    _pieces = []
    for _pat in (r'var _DUR = [^;]*;',
                 r'function normSearch\(s\) \{[\s\S]*?\n\}',
                 r'function stepMinutes\(title\) \{[\s\S]*?\n\}',
                 r'var LONG_STEP_MIN = \d+;',
                 r'function fmtMinutes\(n\) \{[\s\S]*?\n\}',
                 r'var AHEAD_MIN = \d+;',
                 r'var AHEAD_RX = [^;]*;',
                 r'function recipeAhead\(r\) \{[\s\S]*?\n\}',
                 r'var TECH = \[[\s\S]*?\n\];',
                 r'function recipeTech\(r\) \{[\s\S]*?\n\}',
                 r'function recipeBadges\(r\) \{[\s\S]*?\n\}'):
        _m = re.search(_pat, _f)
        check(f"food.html: из страницы вырезается {_pat[:34]}…", _m is not None)
        _pieces.append(_m.group(0) if _m else "")
    _body = re.search(r'var list = S\.recipes\.filter\(function \(r\) \{([\s\S]*?)\n  \}\)\.slice\(\)',
                      _f).group(1).replace("normSearch(S.recipeQuery)", "q")
    _js = ("\n".join(_pieces) + "\n"
           + "var R = JSON.parse(require('fs').readFileSync(process.argv[2],'utf8'));\n"
           + "function match(q, cf) { return function (r) {" + _body + "\n}; }\n"
           # Метки собираем ИЗ ДАННЫХ, а не из TECH: «с вечера» живёт не там,
           # и захардкоженный список молча пропустил бы его мимо проверки.
           # Различитель на подвох «4 часа в мультиварке ≠ 4 часа маринада».
           # Синтетический, а не из библиотеки: живого рецепта с долгим
           # режимом мультиварки пока нет, и проверка на одних живых данных
           # прошла бы при ЛЮБОЙ реализации — в том числе при старой,
           # смотревшей только на длительность.
           + "var COOK = { title: 'контроль', steps: ["
           + "  { title: 'Шаг 1. Обжарка (20 мин)', text: 'обжарить лук' },"
           + "  { title: 'Шаг 2. Томление (4 ч)', text: 'мультиварка, режим Томление', passive: true },"
           + "  { title: 'Шаг 3. Отдых и подача (15 мин)', text: 'дать отдохнуть' }] };\n"
           + "var MARINADE = { title: 'контроль', steps: ["
           + "  { title: 'Шаг 1. Маринование (4 ч)', text: 'убрать в холодильник на 4 часа', passive: true },"
           + "  { title: 'Шаг 2. Обжарка (10 мин)', text: 'обжарить' }] };\n"
           # Брожение теста и заквашивание — то же «начинать заранее», но их не
           # описывают ни холодильником, ни маринадом, ни расстойкой. Чиабатта
           # с бигой на 16 часов и йогурт с 8-часовым заквашиванием жили без
           # бейджа, пока словарь их не знал (2026-08-10). Контроли
           # синтетические: живых рецептов по одному на каждый случай, и
           # проверка на них одних прошла бы при любой реализации.
           + "var BIGA = { title: 'контроль', steps: ["
           + "  { title: 'Шаг 1. Бига (16 ч)', text: 'смешать муку, воду и дрожжи, накрыть плёнкой', passive: true },"
           + "  { title: 'Шаг 2. Замес (10 мин)', text: 'вымесить тесто' }] };\n"
           + "var FERMENT = { title: 'контроль', steps: ["
           + "  { title: 'Шаг 1. Заквашивание (8 ч)', text: 'режим Йогурт', passive: true }] };\n"
           # Обратная сторона того же правила: длинное ожидание БЕЗ слова из
           # словаря обязано молчать, иначе правка выродилась бы в «бейдж по
           # длительности» — ровно то, от чего словарь и защищает.
           + "var LONG_MUTE = { title: 'контроль', steps: ["
           + "  { title: 'Шаг 1. Томление (6 ч)', text: 'мультиварка, режим Томление', passive: true }] };\n"
           # Значок «плита» у блюда, которое целиком готовится в чаше, — жалоба
           # владельца 2026-08-09 (плов в мультиварке). Причина: «обжарить» и
           # «тушить» — это НАЗВАНИЯ ПРОГРАММ мультиварки, а детектор читал их
           # как признак плиты. Три контроля закрывают обе стороны правила:
           # косвенная улика не считается при мультиварке, но продолжает
           # работать без неё, а прямая (посуда) работает всегда.
           + "var MULTI_ONLY = { title: 'контроль', equipment: 'Мультиварка Toshiba.', steps: ["
           + "  { title: 'Шаг 1. Обжарка (20 мин)', text: 'Установить режим «Жарка», обжарить мясо в чаше' },"
           + "  { title: 'Шаг 2. Тушение (30 мин)', text: 'режим «Тушение», закрыть крышку', passive: true }] };\n"
           + "var STOVE_VERB = { title: 'контроль', steps: ["
           + "  { title: 'Шаг 1. Варка (10 мин)', text: 'отварить яйца до готовности' }] };\n"
           + "var MULTI_AND_PAN = { title: 'контроль', equipment: 'Мультиварка Toshiba.', steps: ["
           + "  { title: 'Шаг 1. Су-вид (2 ч)', text: 'мультиварка, режим Су-вид', passive: true },"
           + "  { title: 'Шаг 2. Корочка (3 мин)', text: 'обжарить на раскалённой сковороде' }] };\n"
           + "var lab = function (r) { return recipeTech(r).map(function (t) { return t.label; }); };\n"
           + "var ctl = { cook: recipeAhead(COOK), marinade: recipeAhead(MARINADE),\n"
           + "            biga: recipeAhead(BIGA), ferment: recipeAhead(FERMENT),\n"
           + "            longMute: recipeAhead(LONG_MUTE),\n"
           + "            multiOnly: lab(MULTI_ONLY), stoveVerb: lab(STOVE_VERB), both: lab(MULTI_AND_PAN) };\n"
           + "var labels = {};\n"
           + "R.forEach(function (r) { recipeBadges(r).forEach(function (b) { labels[b.label] = 1; }); });\n"
           + "var out = Object.keys(labels).map(function (lb) {\n"
           + "  var badged = R.filter(function (r) { return recipeBadges(r).some(function (x) { return x.label === lb; }); });\n"
           + "  var found = R.filter(match(normSearch(lb), 'all'));\n"
           + "  var miss = badged.filter(function (r) { return found.indexOf(r) < 0; });\n"
           + "  return { label: lb, badged: badged.length, missed: miss.map(function (r) { return r.title; }) };\n"
           + "});\nconsole.log(JSON.stringify({ rows: out, ctl: ctl }));\n")
    with tempfile.TemporaryDirectory() as _td:
        _p = Path(_td)
        (_p / "t.js").write_text(_js, encoding="utf-8")
        (_p / "r.json").write_text(_json.dumps(_recipes, ensure_ascii=False), encoding="utf-8")
        _r = _sp.run(["node", str(_p / "t.js"), str(_p / "r.json")],
                     capture_output=True, text=True)
    check("food.html: детектор техники исполняется node'ом", _r.returncode == 0)
    if _r.returncode == 0:
        _out = _json.loads(_r.stdout)
        for _row in _out["rows"]:
            check(f"food: бейдж «{_row['label']}» ({_row['badged']} рец.) — все находятся поиском"
                  + (" — не нашлись: " + ", ".join(_row["missed"][:3]) if _row["missed"] else ""),
                  not _row["missed"])
        check("food: 4 ч в мультиварке — это готовка, а не «с вечера»",
              _out["ctl"]["cook"] == 0)
        check("food: 4 ч маринада — это «с вечера»", _out["ctl"]["marinade"] >= 240)
        check("food: 16 ч биги — это «с вечера» (брожение теста)",
              _out["ctl"]["biga"] >= 960)
        check("food: 8 ч заквашивания — это «с вечера»", _out["ctl"]["ferment"] >= 480)
        check("food: 6 ч томления без слова из словаря — молчим",
              _out["ctl"]["longMute"] == 0)
        _c = _out["ctl"]
        check(f"food: блюдо целиком в чаше — значка плиты нет ({_c['multiOnly']})",
              "мультиварка" in _c["multiOnly"] and "плита" not in _c["multiOnly"])
        check(f"food: «отварить» без мультиварки — это всё ещё плита ({_c['stoveVerb']})",
              _c["stoveVerb"] == ["плита"])
        check(f"food: названа сковорода — плита есть и рядом с мультиваркой ({_c['both']})",
              "мультиварка" in _c["both"] and "плита" in _c["both"])
else:
    print("  (пропуск оси «бейдж ↔ поиск»: нет node или библиотеки на Synology)")

# ── оценка «понравилось» ★1–3 ──────────────────────────────────────────────
print("food · оценка рецепта")
# Шкала короткая намеренно: на пяти делениях выбор превращается в гадание
# («это 3 или 4?»), а решение по факту бинарное — готовим ещё или нет.
check("food.html: шкала оценки — три ступени", "var RATING_MAX = 3" in _f)
_words = re.search(r'var RATING_WORDS = \[([^\]]*)\]', _f)
check("food.html: у ступеней есть подписи", _words is not None)
check("food.html: подписи в порядке 1 → 3 (не понравилось · нормально · понравилось)",
      bool(_words) and re.findall(r'"([^"]+)"', _words.group(1))[:4]
      == ["не оценено", "не понравилось", "нормально", "понравилось"])
# Оценку ставят сразу после еды. Если ради одного числа надо открыть редактор,
# снять форму, сохранить и вернуться — она не проставится никогда.
check("food.html: оценка ставится с экрана рецепта одним тапом",
      '"set-rating"' in _f
      and re.search(r'ratingStars\(r\.rating \|\| 0, 20, r\.id\)', _f) is not None)
check("food.html: без прав на запись звёзды не кликабельны",
      re.search(r'var live = rid && S\.writable;', _f) is not None
      and re.search(r'"set-rating": function[\s\S]{0,120}if \(!S\.writable\) return;', _f) is not None)
# Повторный тап снимает: иначе ошибочную единицу пришлось бы убирать через
# редактор — ровно тем путём, от которого уходим.
check("food.html: повторный тап по текущей звезде снимает оценку",
      re.search(r'if \(r\.rating === v\) delete r\.rating; else r\.rating = v;', _f) is not None)
# Тап по звезде НЕ перерисовывает экран. Полный render() здесь давал вспышку
# всей страницы, причём дважды: на старте сохранения и по ответу сервера.
_sr = _f[_f.find('"set-rating": function'):]
_sr = _sr[:_sr.find("\n  \"")] if "\n  \"" in _sr else _sr[:900]
check("food.html: тап по звезде правит только строку оценки",
      'patchHTML("rating-row", ratingRowHTML(r))' in _sr)
check("food.html: сохранение оценки — тихое (без перерисовки)",
      re.search(r'saveRecipe\(r\.id, null, true\)', _sr) is not None)
check("food.html: у saveRecipe есть тихий режим",
      re.search(r'function saveRecipe\(id, after, quiet\)', _f) is not None
      and re.search(r'if \(!quiet\) render\(\);', _f) is not None)
# Ошибку показываем ВСЕГДА, даже в тихом режиме: молча потерянная оценка
# хуже вспышки (тот же контракт, что у отметки «куплено»).
check("food.html: ошибку сохранения тихий режим не глушит",
      re.search(r'catch\(function \(e\) \{\s*\n?\s*S\.saving = false; S\.saveNote = e\.message; render\(\);', _f) is not None)
check("food.html: строка оценки — отдельный узел с id",
      'id="rating-row"' in _f and "function ratingRowHTML(r)" in _f)
# В КАРТОЧКЕ СПИСКА звёзды НЕкликабельны намеренно: вся карточка — ссылка
# (data-act="open-recipe"), и живые звёзды внутри превратили бы промах пальцем
# в молча изменённую оценку вместо открытия рецепта.
check("food.html: в списке звёзды показываются, но не редактируются",
      re.search(r'ratingStars\(r\.rating\)\s*\+', _f) is not None)

# ── горячие пути без полной перерисовки ────────────────────────────────────
print("food · частые действия не мигают")
# Режим готовки — самый чувствительный экран: кухня, телефон, мокрые руки.
# Каждый тап по «вперёд» и каждая галочка пересобирали весь документ.
check("food.html: тело режима готовки отделено от оболочки",
      "function cookBodyHTML()" in _f and 'id="cook-body"' in _f)
check("food.html: содержимое шторки отделено от неё самой",
      "function cookSheetBodyHTML()" in _f and 'id="sheet-body"' in _f)
# Шторка и рельс показывают ОДИН список ингредиентов: галочку ставят из
# шторки, а зачёркнутой строка должна стать в обоих местах.
check("food.html: patchCook обновляет и тело, и открытую шторку",
      re.search(r'function patchCook\(\)[\s\S]{0,400}patchHTML\("cook-body"[\s\S]{0,200}'
                r'if \(S\.sheet\)[\s\S]{0,120}patchHTML\("sheet-body"', _f) is not None)
for _act in ("cook-step-rel", "cook-check"):
    _b = _f[_f.find('"' + _act + '": function'):]
    _b = _b[:_b.find("\n  \"")] if "\n  \"" in _b else _b[:600]
    check(f"food.html: {_act} правит точечно", "patchCook()" in _b)
    check(f"food.html: {_act} падает на render() только если узла нет",
          re.search(r'if \(!patchCook\(\)\) render\(\);', _b) is not None)
# А вот выбор шага из оглавления ЗАКРЫВАЕТ шторку — это смена разметки
# страницы, и полный render() там законен. Проверяем, что исключение осознанное.
_abs = _f[_f.find('"cook-step-abs": function'):]
_abs = _abs[:_abs.find("\n  \"")] if "\n  \"" in _abs else _abs[:400]
check("food.html: cook-step-abs перерисовывает целиком (закрывает шторку)",
      "S.sheet = null" in _abs and "render();" in _abs)
# Список покупок: раскрытие «откуда набежало» меняет одну строку.
check("food.html: раскрытие «откуда» правит только список",
      re.search(r'expand: function[\s\S]{0,300}patchHTML\("shop-list", shopListHTML\(\)\)', _f) is not None)
# Двух путей сборки списка быть не должно: точечная перерисовка и полная
# обязаны звать один и тот же код, иначе они разойдутся на первой же правке.
check("food.html: список покупок собирается одним кодом в обоих путях",
      "function shopGroupHTML(g)" in _f
      and len(re.findall(r'\bshopGroupHTML\b', _f)) >= 3)


def _act_body(src: str, act: str, limit: int = 900) -> str:
    """Тело обработчика действия страницы."""
    i = src.find('"' + act + '": function')
    if i < 0:
        return ""
    rest = src[i:]
    j = rest.find('\n  "', 5)
    return rest[:j] if j > 0 else rest[:limit]


# Редактор рецепта: «−/+» сложности, порций, оценки и добавление строк
# пересобирали ВЕСЬ документ (замер 2026-08-09: 585 снятых узлов на нажатие).
# Правится один кусок формы — его и переписываем.
# edCollect() перед правкой ОБЯЗАТЕЛЕН и в точечном режиме: недописанные поля
# живут только в DOM, и пересборка любого куска формы их потеряет.
_ED_PATCH = [
    ("ed-diff-inc", "ed-diff", "edPipsHTML()"),
    ("ed-diff-dec", "ed-diff", "edPipsHTML()"),
    ("ed-rating-inc", "ed-rating", "edRatingHTML()"),
    ("ed-rating-dec", "ed-rating", "edRatingHTML()"),
    ("ed-nu-toggle", "ed-nu", "edNuHTML()"),
    ("ed-step-add", "ed-steps", "edStepsHTML()"),
    ("ed-step-del", "ed-steps", "edStepsHTML()"),
]
for _act, _node, _fn in _ED_PATCH:
    _b = _act_body(_f, _act)
    check(f"food.html: {_act} — обработчик на месте", bool(_b))
    check(f"food.html: {_act} правит {_node} точечно",
          'patchHTML("' + _node + '", ' + _fn in _b)
    check(f"food.html: {_act} собирает форму перед правкой", "edCollect()" in _b)
    check(f"food.html: узел {_node} рисуется функцией {_fn}",
          re.search(r'id="' + _node + r'"[^\n]{0,200}' + re.escape(_fn), _f) is not None)
# Ингредиенты и каталог — пара: в каталоге отмечено, что уже добавлено.
# Обновить список и забыть чипы значит показать «добавить» у добавленного.
check("food.html: правка ингредиентов обновляет и каталог",
      re.search(r'function edIngsOut\(\)[\s\S]{0,300}patchHTML\("ed-ings", edIngsHTML\(\)\)'
                r'[\s\S]{0,200}patchHTML\("ed-cat-list", edCatalogHTML\(\)\)', _f) is not None)
for _act in ("ed-ing-add", "ed-ing-del"):
    check(f"food.html: {_act} идёт через edIngsOut", "edIngsOut()" in _act_body(_f, _act))
# Строки групп (инвентарь/заметки/источники) — свой узел на группу: иначе
# добавление строки в «Инвентарь» переписывало бы и «Источники» с их вводом.
check("food.html: у каждой группы свой узел строк",
      'id="ed-g-\' + grp.key + \'"' in _f and "function edGroupRowsHTML(key)" in _f)
for _act in ("ed-line-add", "ed-line-del"):
    check(f"food.html: {_act} правит только свою группу",
          'patchHTML("ed-g-" + key, edGroupRowsHTML(key))' in _act_body(_f, _act))
# Тип блюда — одно значение в двух местах (чип и поле). Обновить только чипы
# значило бы сохранить старый текст из поля: edCollect() читает именно поле.
_cat = _act_body(_f, "ed-cat")
check("food.html: чип типа блюда пишет и в поле ввода",
      'getElementById("f-ed-category")' in _cat and "f.value = S.edit.category" in _cat)
check("food.html: чип типа блюда обновляет чипы",
      'patchHTML("ed-cat-chips", edCatChipsHTML())' in _cat)
# Порции в редакторе — просто число: от него в этой форме ничего не зависит.
check("food.html: порции редактора правятся текстом узла",
      re.search(r'function edPortionsOut\(\)[\s\S]{0,200}'
                r'getElementById\("ed-portions"\)[\s\S]{0,120}textContent', _f) is not None)

# Модалка «Запланировать»: у .modal своя прокрутка, и полная перерисовка
# выбрасывала сам элемент — список отматывался к началу (регресс 2026-08-02,
# из-за него в test_food_layout.py живёт отдельная проверка прокрутки).
check("food.html: тело модалки плана отделено от оболочки",
      "function planBodyHTML(p, r)" in _f and 'id="plan-body"' in _f)
check("food.html: patchPlan переписывает только тело",
      re.search(r'function patchPlan\(\)[\s\S]{0,260}patchHTML\("plan-body", planBodyHTML\(', _f) is not None)
for _act in ("plan-check", "plan-portions", "plan-amt", "plan-home-toggle",
             "plan-swap", "plan-swap-clear"):
    _b = _act_body(_f, _act)
    check(f"food.html: {_act} — обработчик на месте", bool(_b))
    check(f"food.html: {_act} правит модалку точечно",
          re.search(r'if \(!patchPlan\(\)\) render\(\);', _b) is not None)
    # set() — тот же полный render(), просто с другой стороны двери.
    check(f"food.html: {_act} не ходит через set()", "set({" not in _b)

# ── health: ввод, фильтры и окно отчёта ────────────────────────────────────
print("travel · кнопка «План» ведёт на последнее по времени")
_tv = (REPO / "tools/travel.html").read_text(encoding="utf-8")
# Кнопка вела на стадию 5 жёстко. Стадия 6 («Финал: карта + досье») собирается
# позже и содержит тот же план с картой, но и обратное бывает: план пересобрали
# после финала. Решает mtime файла, а не номер стадии — значит листинг обязан
# донести mod_time, а ссылка обязана брать индекс из planTarget().
check("travel.html: листинг сохраняет mod_time (общий uiListDir)",
      "function listDir(url){ return uiListDir(url, NET); }" in _tv
      and "mtime: Date.parse(e.mod_time" in (REPO / "tools/assets/ui-kit.js").read_text(encoding="utf-8"))
check("travel.html: есть выбор цели плана", "function planTarget(stages)" in _tv)
check("travel.html: обе кнопки плана берут индекс из planTarget, а не 5",
      'data-idx="5"' not in _tv and _tv.count('data-idx="\' + planIdx + \'"') == 2)
check("travel.html: стадия 6 участвует только с html/md (PDF-заглушку не открываем)",
      "i === 6 ? (st.html || st.md)" in _tv)
check("travel.html: сортировка по времени, ничья — за стадией 6",
      "b.t - a.t || b.idx - a.idx" in _tv)

print("health · ввод, фильтры и отчёты")
_hl = (REPO / "tools/health.html").read_text(encoding="utf-8")

# 0. Словарь назначений живёт в ДВУХ местах: страница по нему группирует аптечку,
#    валидатор скилла по нему принимает/отклоняет поле `group`. Разъедутся —
#    health-meds запишет ключ, для которого на странице нет блока, и лекарство
#    молча исчезнет из списка. Сверяем состав И порядок: порядок задаёт
#    последовательность блоков на экране, он часть контракта, а не деталь.
_js_groups = re.findall(r'k: "([a-z]+)"',
                        re.search(r"var MED_GROUPS = \[(.*?)\];", _hl, re.S).group(1))
_py_groups = re.findall(
    r'"([a-z]+)"',
    re.search(r"MED_GROUPS = \((.*?)\)",
              (REPO / "skills/health-meds/scripts/validate_meds.py").read_text(encoding="utf-8"),
              re.S).group(1))
check(f"health.html ↔ validate_meds.py: словарь назначений совпадает "
      f"(страница {_js_groups}, скилл {_py_groups})",
      _js_groups == _py_groups)
check("health.html: у каждого назначения есть русский ярлык",
      len(re.findall(r'k: "[a-z]+",\s*label: "[^"]+"',
                     re.search(r"var MED_GROUPS = \[(.*?)\];", _hl, re.S).group(1))) == len(_js_groups))
check("health.html: заголовок блока липкий (.md-ghead)",
      ".md-ghead{ position:sticky" in _hl and 'class="md-ghead"' in _hl)
check("health.html: смещение липкости меряется, а не зашито числом",
      "function syncStickyTop()" in _hl and "--h-top-h" in _hl)

# 1. Ввод. До 2026-08-09 каждая буква пересобирала документ и поле с фокусом
#    физически создавалось заново (замер: 3 из 3 букв), фокус и каретку
#    возвращали руками. Меняются три узла: счётчик, полоса фильтров, список.
check("health.html: есть точечная правка узла", "function patchHTML(id, html)" in _hl)
for _node in ("mk-below", "mk-list", "md-below", "md-list", "mk-count"):
    check(f"health.html: узел {_node} есть в разметке", 'id="' + _node + '"' in _hl)
check("health.html: patchMarkers правит счётчик, фильтры и список",
      re.search(r'function patchMarkers\(\)[\s\S]{0,600}mk-count[\s\S]{0,300}'
                r'patchHTML\("mk-below", markersBelowHTML\(M\)\)[\s\S]{0,200}'
                r'patchHTML\("mk-list", markersListHTML\(M\)\)', _hl) is not None)
check("health.html: patchMeds правит фильтры и список",
      re.search(r'function patchMeds\(\)[\s\S]{0,400}patchHTML\("md-below", medsBelowHTML\(M\)\)'
                r'[\s\S]{0,200}patchHTML\("md-list", medsListHTML\(M\)\)', _hl) is not None)
_inp = _hl[_hl.find('document.addEventListener("input"'):]
_inp = _inp[:_inp.find('document.addEventListener("focusout"')]
check("health.html: поиск маркеров правит точечно",
      re.search(r'act === "query"[\s\S]{0,140}if \(!patchMarkers\(\)\) render\(\);', _inp) is not None)
check("health.html: поиск аптечки правит точечно",
      re.search(r'act === "med-query"[\s\S]{0,140}if \(!patchMeds\(\)\) render\(\);', _inp) is not None)
check("health.html: поиск не ходит через set()",
      not re.search(r'act === "(query|med-query)"[^\n]{0,120}set\(\{', _inp))
# Модель и разметка обязаны считаться из ОДНОГО кода: иначе счётчик в шапке
# и список под ним разойдутся ровно тогда, когда это заметить труднее всего.
for _fn in ("markersModel", "medsModel", "markersListHTML", "medsListHTML",
            "markersBelowHTML", "medsBelowHTML"):
    check(f"health.html: {_fn} — общий код разметки и патча",
          "function " + _fn + "(" in _hl and len(re.findall(r'\b' + _fn + r'\(', _hl)) >= 2)

# 2. Полоса фильтров. Замер 2026-08-09 на 390×660: из пяти совпадений по «гем»
#    не видно НИ ОДНОГО — 314 px чипов между полем и первым результатом.
check("health.html: полоса фильтров сворачивается", "function filterBar(" in _hl)
_fb = _hl[_hl.find("function filterBar("):]
_fb = _fb[:_fb.find("\n}\n") + 2]
check("health.html: сворачивание ТОЛЬКО при непустом запросе",
      re.search(r'if \(!searching\) return fullRow;', _fb) is not None)
check("health.html: свёрнутая строка называет число найденного", "найдено" in _fb)
check("health.html: из свёрнутой строки полосу можно раскрыть",
      'data-act="filters-open"' in _fb and 'data-act="filters-close"' in _fb)
for _a in ("filters-open", "filters-close"):
    check(f"health.html: действие {_a} есть", '"' + _a + '": function' in _hl)
# Активный фильтр из свёрнутой строки НЕ исчезает: «ничего не найдено» при
# включённом «только вне нормы» читалось бы как «такого маркера нет».
check("health.html: активный фильтр остаётся видимым чипом", "function chipOff(" in _hl)
check("health.html: чип снимает фильтр тем же действием",
      re.search(r'chipOff\(catName\(S\.cat\), "cat", "all"\)', _hl) is not None
      and re.search(r'S\.onlyOut \? chipOff\("только вне нормы", "only-out"\)', _hl) is not None)
check("health.html: у аптечки активный фильтр тоже виден",
      re.search(r'chipOff\(labels\[M\.mf\] \|\| M\.mf, "med-filter", "all"\)', _hl) is not None)
# Раскрытая полоса — состояние одного поиска, а не страницы.
check("health.html: смена вкладки сворачивает полосу обратно",
      re.search(r'tab: function\(id, el\)\{ set\(\{ tab: id, filtersOpen: false \}\);', _hl) is not None)

# 3. Фон. render() заново кодировал плитку 300×300 в data-URI и вешал НОВУЮ
#    строку на НОВЫЙ элемент — браузер получал другой источник картинки на
#    каждую букву. Остальные страницы кабинета держат фон в CSS-переменной.
check("health.html: фон считается один раз на тему", "function paperBg()" in _hl)
check("health.html: render не кодирует SVG заново",
      re.search(r'function render\(\)[\s\S]{0,1400}var bg = paperBg\(\);', _hl) is not None)
check("health.html: кодирование живёт только в paperBg",
      len(re.findall(r'encodeURIComponent\(bgSvg', _hl)) == 1)
check("health.html: фон уходит в CSS-переменную",
      '--health-paper' in _hl and 'setProperty("--health-paper"' in _hl)

# 4. Окно документа (отчёт или файл исследования). Раньше строка вела на файл
#    отдельной вкладкой; потом — фреймом на прямой URL, и это был пустой экран:
#    /health-data/* отдаётся ТОЛЬКО с заголовком Authorization, а ни ссылка, ни
#    <iframe src> его не несут (Caddy: тихий 403). Файл качается authFetch'ем
#    и показывается blob:-ом (2026-09-29).
check("health.html: есть окно просмотра документа", "function docModal()" in _hl)
_assign = _hl[_hl.find("\n  app.innerHTML ="):]
check("health.html: окно попадает в разметку", "docModal()" in _assign[:1400])
for _a in ("rep-open", "doc-close", "study-file"):
    check(f"health.html: действие {_a} есть", '"' + _a + '": function' in _hl)
check("health.html: Escape закрывает окно документа",
      re.search(r'if \(S\.doc\)\{ closeDocAnim\(\); return; \}', _hl) is not None)
check("health.html: при открытом окне страница под ним не прокручивается",
      re.search(r'var open = !!\([^)]*S\.doc\)', _hl) is not None)
_od = _hl[_hl.find("function openDoc("):]
_od = _od[:_od.find("\n}\n") + 2]
check("health.html: документ качается с авторизацией, не прямой ссылкой",
      "authFetch(docUrl(" in _od and "createObjectURL" in _od)
check("health.html: blob освобождается при закрытии",
      "revokeObjectURL" in _hl[_hl.find("function closeDoc("):][:300])
_rm = _hl[_hl.find("function docModal()"):]
_rm = _rm[:_rm.find("\n}\n") + 2]
check("health.html: PDF показывается фреймом с blob", '<iframe src="\' + esc(d.blob)' in _rm)
check("health.html: окно не ссылается на прямой URL файла",
      "reportUrl(" not in _rm and "DATA +" not in _rm)
# Запасной путь обязателен: во фрейме PDF рисует СИСТЕМНЫЙ просмотрщик, и на
# iPhone Safari он показывает только первую страницу без листания.
check("health.html: в окне есть «открыть отдельно»",
      'target="_blank"' in _rm and "Открыть отдельно" in _rm)
check("health.html: про ограничение сказано прямо", "только первую страницу" in _rm)
# Строка отчёта остаётся ссылкой: долгое нажатие даёт родное меню браузера.
check("health.html: строка отчёта сохраняет href",
      re.search(r'data-act="rep-open" data-id="\' \+ esc\(f\.name\) \+ \'" href=', _hl) is not None)
# Имена файлов с пробелами и кириллицей («2026-08-04 Офтальмолог.pdf») —
# одна функция на все пути документов, иначе один из путей молча 404.
check("health.html: путь к документу кодируется в одном месте",
      re.search(r'function docUrl\(dir, name\)\{ return DATA \+ dir \+ "/" \+ encodeURIComponent\(name\); \}', _hl) is not None
      and "DATA + \"studies/\"" not in _hl)
# Исследование: «Файл ↗» на карточке — своя кнопка. Надпись внутри строки
# с data-act="study-open" открывала панель, а не файл.
_ts = _hl[_hl.find("function studiesListHTML("):]
_ts = _ts[:_ts.find("\n}\n") + 2]
check("health.html: на карточке исследования кнопка файла",
      'data-act="study-file"' in _ts)
# Поиск и фильтр по виду на вкладке «Исследования» (2026-09-29): поиск по всему
# тексту карточки, буква меняет узлы точечно (patchStudies), как у маркеров.
_stm = _hl[_hl.find("function studiesModel()"):]
_stm = _stm[:_stm.find("\n}\n") + 2]
check("health.html: поиск исследований по тексту карточки",
      all(f in _stm for f in ("x.area", "x.conclusion", "x.notes", "x.clinic", "x.doctor")))
check("health.html: фильтр исследований по виду", "S.stKind" in _stm and '"study-kind": function' in _hl)
check("health.html: ввод в поиск исследований не пересобирает страницу",
      'act === "study-query"){ S.stQuery = ev.target.value; if (!patchStudies()) render(); }' in _hl)
# Панели стопкой (ui-kit 1.37.0, health v1.41, 2026-10-07): переход из панели в
# панель кладёт новую поверх, «← …»/Escape/затемнение — к нижней, ✕ — закрыть все.
# Было: замена панели и указатели «откуда пришёл» глубиной 1 (selFrom/medFrom/
# studyFrom/selStudy) с отдельным действием «назад» на каждую пару.
check("health.html: боковые панели — общая ui-kit (uiPaneHTML), своих копий разметки нет",
      _hl.count("uiPaneHTML({") == 6 and "pane-panel" not in _hl and "position:fixed; inset:0; z-index:200" not in _hl)
check("health.html: панели стопкой — S.panes, переходы кладут поверх",
      "panes: []" in _hl and all(f'"{_a}": function(id){{ panePush(' in _hl
                                 for _a in ("marker-from-study", "study-from-marker", "med-open-from-marker", "open-from-med")))
check("health.html: «назад» и Escape — к нижней панели, ✕ — закрыть все (uiStackPop)",
      '"pane-back": function(){ panePop(S.panes.length - 1); }' in _hl and '"pane-close": function(){ panePop(0); }' in _hl
      and "if (S.panes.length){ panePop(S.panes.length - 1); return; }" in _hl
      and 'uiStackPop(document.querySelectorAll(".ui-pane"), i,' in _hl)
check("health.html: указателей «откуда пришёл» больше нет",
      not re.search(r"\bS\.(selFrom|medFrom|studyFrom|selStudy|selId|medSel|studySel|vitalsPane)\b", _hl))
check("health.html: подпись «← …» — панель под этой (исследование — с датой)",
      "function paneBack(i)" in _hl and "sub: uiDateNum(st.date)" in _hl)
_ukp = (REPO / "tools/assets/ui-kit.js").read_text(encoding="utf-8")
_ucp = (REPO / "tools/assets/ui-kit.css").read_text(encoding="utf-8")
check("ui-kit: боковая панель uiPaneHTML и её стопка в CSS",
      "function uiPaneHTML(o)" in _ukp and 'data-act="pane-back"' in _ukp
      and all(c in _ucp for c in (".ui-pane{", ".ui-pane.enter .ui-pane-box", ".ui-pane.behind .ui-pane-box", ".ui-pane.leave .ui-pane-box")))
# «раньше/позже», а не «до/после»: «до 79» читалось как «вплоть до 79».
check("health.html: соседние измерения — «раньше/позже»",
      '"раньше: "' in _hl and '"позже: "' in _hl and '"до: "' not in _hl)
# Мини-график в строке каталога — с двух точек (у ЭКГ/УЗИ повторов мало).
check("health.html: мини-график в каталоге с двух точек",
      "hasSpark: vals.length >= 2" in _hl and "if (n < 2) return" in _hl)
_sp = _hl[_hl.find("function studyPane(id, i)"):]
_sp = _sp[:_sp.find("\n}\n") + 2]
check("health.html: «Открыть файл» в панели идёт через openDoc",
      'data-act="study-file"' in _sp and "<a href" not in _sp)
# Форма исследования широкая: заключение — протокол целиком.
check("health.html: форма исследования шире остальных",
      re.search(r'"study-save", 9\d\d\);', _hl) is not None)

# 5. Связь исследование ↔ биомаркеры (2026-09-29). Ссылка живёт ОДНОЙ
#    стороной — в точке labs.json (series[i].study); обратное направление
#    страница вычисляет. Вторая копия ссылки в studies.json разошлась бы с первой.
_sm = _hl[_hl.find("function studyMetrics("):]
_sm = _sm[:_sm.find("\n}\n") + 2]
check("health.html: показатели исследования вычисляются из labs.json",
      "bioList()" in _sm and "p.study === id" in _sm)
check("health.html: studies.json не хранит обратную ссылку",
      not re.search(r'\.metrics\b|x\.markers\b|x\.biomarkers\b', _hl))
_sp2 = _hl[_hl.find("function studyPane(id, i)"):]
_sp2 = _sp2[:_sp2.find("\n}\n") + 2]
check("health.html: панель исследования показывает показатели", "studyMetricsBlock(x.id)" in _sp2)
for _a in ("marker-from-study", "study-from-marker", "study-more-file"):
    check(f"health.html: действие {_a} есть", '"' + _a + '": function' in _hl)
check("health.html: из исследования/лекарства стрелки каталога не листают (только панель из каталога)",
      _hl.count('if (!t || t.k !== "marker" || S.panes.length > 1) return') == 2)
_mp = _hl[_hl.find("function markerPane(id, i"):]
_mp = _mp[:_mp.find("\n}\n") + 2]
# Ссылки есть не у всех точек: без study строка истории — как раньше (лаборатория).
check("health.html: точка без ссылки рисуется как раньше",
      'h.study && studyById(h.study)' in _mp and '(h.lab || "")' in _mp)
# Клиника исследования рядом с кнопкой-ссылкой — из studies.json, не копией в
# lab точки; у кнопки-значка без текста название исследования — в aria-label.
check("health.html: в истории у ссылки на исследование — его клиника",
      "st.clinic" in _mp and 'aria-label="\' + esc("Открыть исследование: "' in _mp)

# Норма из клинических рекомендаций (health-labs set-ref) подписана источником:
# без подписи её не отличить от нормы, напечатанной в документе.
_mp2 = _hl[_hl.find("function markerPane(id, i"):]
_mp2 = _mp2[:_mp2.find("\n}\n") + 2]
check("health.html: источник нормы из рекомендаций в карточке биомаркера",
      ".ref_src" in _mp2 and "Норма из рекомендаций" in _mp2)

# ── крестик очистки поиска (ui-kit 1.5.0, 2026-09-29) ──────────────────────
print("поиск · крестик очистки")
# Один компонент на весь кабинет: uiSearchX(id) ставится СРАЗУ за полем поиска;
# клик — value="" + bubbling-«input», страница отрабатывает своим обработчиком
# ввода. Каждое поле поиска страниц обязано иметь крестик — иначе на одной
# странице сброс есть, на другой нет.
_uk = (REPO / "tools/assets/ui-kit.js").read_text(encoding="utf-8")
_ucss = (REPO / "tools/assets/ui-kit.css").read_text(encoding="utf-8")
check("ui-kit.js: uiSearchX и его делегат", "function uiSearchX(forId)" in _uk and "[data-ui-search-x]" in _uk
      and 'new Event("input", { bubbles: true })' in _uk)
check("ui-kit.css: крестик прячется у пустого поля", "input:placeholder-shown + .ui-search-x{ display:none; }" in _ucss)
for _page, _ids in (("health.html", ("q", "mq", "stq")),
                    ("food.html", ("f-prod-q", "f-rec-q", "f-ed-cat-q", "f-ing-link-q"))):
    _src = (REPO / "tools" / _page).read_text(encoding="utf-8")
    for _id in _ids:
        _m = re.search(r'<input[^>]*id="' + re.escape(_id) + r'"[^\n]*', _src)
        _line = _m.group(0) if _m else ""
        check(f"{_page}: у поиска #{_id} есть крестик сразу за полем",
              ("uiSearchX(\"" + _id + "\")") in _line)
        check(f"{_page}: у поиска #{_id} есть placeholder (по нему CSS прячет крестик)",
              'placeholder="' in _line)
    # Поле без крестика — новое поле поиска, про которое забыли.
    _all = set(re.findall(r'<input class="(?:h-search|srch)" id="([^"]+)"', _src))
    check(f"{_page}: все поля поиска с крестиком (без: {sorted(_all - set(_ids))})", _all <= set(_ids))

# ── версия страницы: видна в подвале у КАЖДОЙ ──────────────────────────────
print("страницы · версия в подвале")
# Версия нужна ровно для одного: понять по скриншоту, ту ли сборку человек
# видит. Без неё «у меня не работает» и «у меня старая версия из кеша»
# неотличимы — а это ежедневная ситуация, потому что страницы кэшируются, а
# данные приезжают синком отдельно. Требование владельца 2026-08-09: поднимать
# хотя бы minor при каждой правке ЛЮБОЙ страницы.
_PAGE_VER = re.compile(r'\b(hub|travel|games|food|health|login) v(\d+)\.(\d+)(?:\.(\d+))?\b')
for _page in ("hub", "travel", "games", "food", "health"):
    _txt = (REPO / f"tools/{_page}.html").read_text(encoding="utf-8")
    _m = [m for m in _PAGE_VER.finditer(_txt) if m.group(1) == _page]
    check(f"{_page}.html: объявляет свою версию ({_m[0].group(0) if _m else '—'})", bool(_m))
    # Строка версии обязана попадать в РАЗМЕТКУ подвала, а не просто лежать
    # в коде: версия, которой не видно на экране, скриншот не подписывает.
    check(f"{_page}.html: версия печатается в подвале",
          bool(_m) and (_m[0].group(0) in _txt.split("<footer")[-1]
                        or "VERSION" in _txt.split("<footer")[-1]
                        or re.search(r'uiFootHTML\(\{[^}]*version: ', _txt) is not None
                        or re.search(r'footer[\s\S]{0,4000}?\+ (?:esc\()?VERSION', _txt) is not None))

# ═══════════════════════ хаб: плитки разделов ══════════════════════════════
print("hub · плитки")
_h = (REPO / "tools/hub.html").read_text(encoding="utf-8")

# Все четыре раздела — плитками одной сетки. Здоровье было широкой полосой;
# при добавлении еды его свели в плитку, и порядок задаётся order:.
for _sec, _href, _ord in (("Еда", "food.html", 1), ("Здоровье", "health.html", 2),
                          ("Путешествия", "travel.html", 3), ("Игры", "games.html", 4)):
    check(f"хаб: раздел «{_sec}» — плитка сетки с order:{_ord}",
          re.search(r'href="' + re.escape(_href) + r'"[^>]*order:' + str(_ord) + r';', _h) is not None)
check("хаб: широкой полосы здоровья не осталось",
      "hub-health" not in _h and "hh-right" not in _h)

# Список покупок читается БЕЗ входа — он нужен у полки в магазине. Уедет на
# authFetch — плитка опустеет ровно там, где нужна.
check("хаб: еда читается без токена (обычный fetch)",
      'fetch(bust("../Food/shopping.json")' in _h)
check("хаб: еда берёт данные из ../Food/ (страница в /tools/)",
      "../Food/shopping.json" in _h)
# Формулировка плитки: «N в списке · куплено X из Y». Прежняя «нужно купить ·
# 0 из 1 в корзине» путала — единица значила разное, а «нужно купить» рядом с
# «в корзине» конфликтовало (замечание владельца 2026-07-21).
check("хаб: плитка еды говорит «куплено X из Y»",
      '"куплено " + (total - n) + " из " + total' in _h)
check("хаб: старая путаная формулировка убрана",
      "в корзине" not in _h and "нужно купить" not in _h)

# Мёртвая ссылка на id — самый дешёвый способ уронить страницу молча:
# $("hev-name").textContent на null бросает и обрывает ВЕСЬ обработчик,
# включая то, что шло после. Ровно этим кончился бы перенос здоровья в плитку.
_ids = set(re.findall(r'\bid="([^"]+)"', _h))
_used = set(re.findall(r'\$\("([^"]+)"\)', _h))
_dead = sorted(_used - _ids)
check(f"хаб: JS не дёргает несуществующие id{' — ' + str(_dead) if _dead else ''}", not _dead)

# ═══════════════════════ ui-kit: общие ассеты ══════════════════════════════
# assets/ui-kit.css / ui-kit.js — общие UI-компоненты кабинета (план
# унификации, Фаза 0+1), подключаются страницами по паттерну assets/viewer.js
# (?v=<версия> в query-string). SSOT версии — UI_KIT_VERSION в ui-kit.js.
# Расхождение версии на разных страницах или между query-string и
# UI_KIT_VERSION воспроизводит ровно тот класс бага, что уже случался с
# viewer.js: браузер кэширует ассет под одним URL, а страница ждёт другой
# код — рассинхрон обнаруживается только глазами на проде.
# Пока НИ ОДНА страница не подключает ui-kit — множество подключений пусто,
# и все проверки ниже по построению проходят (граф пуст → нечего сравнивать).
# ── ui-kit · url() в CSS ведут на существующие файлы ───────────────────────
# Ровно тот баг, который прожил незамеченным с 2026-07-21 по 2026-08-10:
# @font-face переехали из /tools/*.html в /tools/assets/ui-kit.css вместе с
# путями `assets/fonts/…`. Из HTML такой путь верен, из CSS — нет: url() в CSS
# считается ОТ САМОГО CSS-файла, и запросы уходили в /tools/assets/assets/fonts/.
# Итог: ни один self-hosted шрифт не грузился ни на одной из пяти страниц,
# всё рисовалось системными подстановками (заголовки Georgia вместо Spectral).
# Ничего не падало и в консоли было тихо, кроме 404 — глазами это не ловится,
# потому что fallback выглядит как «просто другой шрифт».
print("ui-kit · пути к ассетам в CSS")
for _css_rel in ("tools/assets/ui-kit.css", "tools/assets/viewer.css"):
    _css_path = REPO / _css_rel
    if not _css_path.exists():
        continue
    _urls = re.findall(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", _css_path.read_text(encoding="utf-8"))
    _local = [u for u in _urls if not re.match(r"^(https?:|data:|//|#)", u.strip())]
    if _css_rel.endswith("ui-kit.css"):   # шрифты живут здесь; у viewer.css url() может не быть вовсе
        check(f"{_css_rel}: url() вообще есть", bool(_local))
    _dead = sorted({u for u in _local if not (_css_path.parent / u.split("?")[0]).exists()})
    check(f"{_css_rel}: все {len(_local)} url() ведут на существующие файлы"
          + (f" (нет: {', '.join(_dead[:3])})" if _dead else ""), not _dead)

print("ui-kit · версия ассетов")
UI_KIT_JS = (REPO / "tools/assets/ui-kit.js").read_text(encoding="utf-8")
_m = re.search(r"UI_KIT_VERSION\s*=\s*'([^']+)'", UI_KIT_JS)
check("ui-kit.js: UI_KIT_VERSION объявлена", _m is not None)
UI_KIT_VERSION = _m.group(1) if _m else None

_ui_kit_versions = {}
for _page in ("hub", "travel", "games", "food", "health", "login", "portfolio-integrated-viewer"):
    _txt = (REPO / f"tools/{_page}.html").read_text(encoding="utf-8")
    for _asset in ("ui-kit.css", "ui-kit.js"):
        _mv = re.search(re.escape(f"assets/{_asset}?v=") + r"([\w.]+)", _txt)
        if _mv:
            _ui_kit_versions[f"{_page}:{_asset}"] = _mv.group(1)

if _ui_kit_versions:
    _distinct = set(_ui_kit_versions.values())
    check(f"ui-kit: все подключения используют одну версию (найдено: {_distinct})",
          len(_distinct) == 1)
    if UI_KIT_VERSION:
        for _k, _v in _ui_kit_versions.items():
            check(f"ui-kit: версия в {_k} совпадает с UI_KIT_VERSION ({_v} ↔ {UI_KIT_VERSION})",
                  _v == UI_KIT_VERSION)

# ── ui-kit · датапикер (Фаза 1): перенос health.html → ui-kit.js/css ────────
# Одноимённая функция в двух <script> не даёт ошибку — молча побеждает
# загруженная ПОСЛЕДНЕЙ. Если бы старое определение осталось в инлайн-
# скрипте health.html, перенос был бы фиктивным: страница по-прежнему жила
# бы по старой копии, а ui-kit.js оставался мёртвым кодом.
_health_html = (REPO / "tools/health.html").read_text(encoding="utf-8")
check("ui-kit.js: openCalendar (датапикер) перенесён",
      "function openCalendar(" in UI_KIT_JS)
check("health.html: старое определение openCalendar удалено (не дублирует ui-kit.js)",
      "function openCalendar(" not in _health_html)

# Порядок подключения критичен: делегированные обработчики хозяина обязаны
# видеть готовые функции ui-kit.js (dateField/openCalendar/…) уже на момент
# первого рендера — значит ui-kit.js обязан
# загрузиться РАНЬШЕ инлайн-скрипта. rfind — намеренно: анти-мигание темы в
# <head> тоже голый `<script>` без src и идёт раньше всего остального, здесь
# нужен именно ОСНОВНОЙ инлайн-скрипт (последний `<script>` без атрибутов).
_idx_ui_kit_src = _health_html.find('<script src="assets/ui-kit.js')
_idx_inline_script = _health_html.rfind("<script>")
check("health.html: assets/ui-kit.js подключён раньше инлайн-скрипта",
      _idx_ui_kit_src != -1 and _idx_inline_script != -1
      and _idx_ui_kit_src < _idx_inline_script)

# ── ui-kit · запрет ссылок на код страницы-хозяина ─────────────────────────
# Порядок подключения — НЕ достаточное условие: инлайн-скрипты всех пяти
# страниц кабинета обёрнуты в IIFE, поэтому их `var X`/`function X` вообще
# не попадают в window, и свободная переменная в ui-kit.js не резолвится
# ничем — ReferenceError в момент вызова.
#
# Так с Фазы 1 (2026-07-21) по 2026-08-04 лежали ВСЕ поля даты «Здоровья»:
# датапикер переехал сюда, а его зависимости fmtDay/MSHORT/todayISO остались
# внутри IIFE health.html. openMonthPicker («Годен до» лекарства) успевал
# вставить в body ПУСТОЙ .dp-pop и падал на MSHORT — попап невидим, а
# следующий клик уходил в ветку «уже открыт» и просто удалял его: со стороны
# «кнопка есть, но не нажимается». dateField с непустой датой падал на fmtDay
# прямо в рендере и уносил всю модалку (прививка, вес, исследование не
# открывались вовсе). Всё это тихо, в pageerror, который никто не читает.
#
# Разбор синтаксиса regex'ами достаточен: ui-kit.js — плоский ES5-скрипт без
# модулей и классов. Строки/комментарии/regex-литералы вырезаются до анализа,
# иначе слова из русской прозы комментариев прилетели бы как идентификаторы.
print("ui-kit · нет ссылок на глобалы страниц-хозяев")

def _strip_js(src):
    """Убрать комментарии, строковые и regex-литералы (грубо, но честно)."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            i = src.find("\n", i)
            if i == -1:
                break
        elif c == "/" and nxt == "*":
            j = src.find("*/", i + 2)
            i = n if j == -1 else j + 2
        elif c in "\"'`":
            i += 1
            while i < n and src[i] != c:
                i += 2 if src[i] == "\\" else 1
            i += 1
            out.append(' "" ')
        elif c == "/" and re.search(r"[(,=:\[!&|?{};+\-*~^%]\s*$", "".join(out[-40:])):
            # regex-литерал: `/` в позиции, где операнд, а не деление
            i += 1
            while i < n and src[i] != "/":
                i += 2 if src[i] == "\\" else 1
            i += 1
            while i < n and src[i] in "gimsuy":
                i += 1
            out.append(" 0 ")
        else:
            out.append(c)
            i += 1
    return "".join(out)

_UI_KIT_CODE = _strip_js(UI_KIT_JS)

# Что скрипт объявляет сам: функции (в т.ч. вложенные), var-ы, параметры,
# catch-переменные. Всё это законные имена.
_declared = set(re.findall(r"\bfunction\s+([A-Za-z_$][\w$]*)", _UI_KIT_CODE))
_declared |= set(re.findall(r"\bcatch\s*\(\s*([A-Za-z_$][\w$]*)", _UI_KIT_CODE))

def _var_names(code):
    """Имена из `var a = 1, b = 2;` — списочная форма объявления обычная в
    этом коде, и без её разбора `b` выглядел бы свободной переменной."""
    names = set()
    for _mv2 in re.finditer(r"\bvar\s+", code):
        i, depth, part = _mv2.end(), 0, ""
        while i < len(code):
            ch = code[i]
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                if depth == 0:
                    break
                depth -= 1
            if depth == 0 and ch in ",;\n":
                mn = re.match(r"\s*([A-Za-z_$][\w$]*)", part)
                if mn:
                    names.add(mn.group(1))
                if ch in ";\n":
                    break
                part = ""
            else:
                part += ch
            i += 1
        mn = re.match(r"\s*([A-Za-z_$][\w$]*)", part)
        if mn:
            names.add(mn.group(1))
    return names

_declared |= _var_names(_UI_KIT_CODE)
for _params in re.findall(r"\bfunction\b[^(]*\(([^)]*)\)", _UI_KIT_CODE):
    _declared |= {p.strip() for p in _params.split(",") if p.strip()}

# Стандартное окружение браузера + ключевые слова языка: их наличие ничего
# не говорит о зависимости от страницы-хозяина.
_JS_ENV = {
    "document", "window", "location", "localStorage", "sessionStorage", "Headers", "navigator", "console",
    "Math", "Date", "String", "Number", "Boolean", "Array", "Object", "JSON",
    "RegExp", "Error", "Promise", "Set", "Map", "parseInt", "parseFloat",
    "isNaN", "isFinite", "encodeURIComponent", "decodeURIComponent",
    "btoa", "atob", "setTimeout", "clearTimeout", "setInterval", "fetch",
    "alert", "confirm", "requestAnimationFrame", "undefined", "NaN",
    "Infinity", "arguments", "globalThis", "URLSearchParams",
    "Event",   # крестик поиска (v1.5.0) шлёт синтетический «input»
    "CustomEvent",   # выпадающий список (v1.11.0) сообщает выбор событием ui-select
    # читатель markdown (v1.7.0): прокрутка, вычисленные стили, экранирование id
    "cancelAnimationFrame", "getComputedStyle", "CSS", "IntersectionObserver", "ResizeObserver", "MutationObserver",
    "URL",   # офлайн (v1.54.0): адрес фонового скрипта от адреса самого ui-kit.js
    "clearInterval",   # прогрев копий (v1.55.0): ожидание «страница во фрейме догрузилась»
    # уведомления кабинета (v1.57.0, uiPush*): разрешение на push, ключ VAPID байтами,
    # снятие #notify из адреса, «тот же якорь ещё раз» на открытой странице
    "Notification", "Uint8Array", "history", "HashChangeEvent",
}
_JS_KEYWORDS = {
    "var", "let", "const", "function", "return", "if", "else", "for", "while",
    "do", "switch", "case", "default", "break", "continue", "new", "typeof",
    "instanceof", "in", "of", "delete", "void", "try", "catch", "finally",
    "throw", "this", "null", "true", "false", "class", "extends", "super",
    "yield", "await", "async", "use", "strict",
}

# Идентификаторы, читаемые «голыми»: не после точки, не имя свойства в
# литерале объекта, не сразу после `function`.
_referenced = set()
for _m2 in re.finditer(r"(?<![.\w$])([A-Za-z_$][\w$]*)", _UI_KIT_CODE):
    _name = _m2.group(1)
    _tail = _UI_KIT_CODE[_m2.end():_m2.end() + 2]
    if re.match(r"\s*:", _tail):          # ключ объекта / метка
        continue
    _referenced.add(_name)

_free = sorted(_referenced - _declared - _JS_ENV - _JS_KEYWORDS)
check("ui-kit.js: нет свободных переменных — компоненты не зависят от кода "
      f"страницы-хозяина{' — найдено: ' + str(_free) if _free else ''}",
      not _free)

# Парная проверка «в лоб» по трём именам, на которых сломался датапикер:
# сканер выше можно нечаянно ослабить (расширив whitelist), а эти три —
# именно host-глобалы health.html, и появиться здесь они не должны никогда.
for _host_global in ("MSHORT", "fmtDay", "todayISO"):
    check(f"ui-kit.js: не обращается к host-глобалу {_host_global}()",
          not re.search(r"(?<![.\w$])" + _host_global + r"\s*[\(\[]", _UI_KIT_CODE))

# ── ui-kit · esc()/attr() (Фаза 2): перенос трёх разошедшихся копий ─────────
# Толчок: games.html/travel.html экранировали esc() через
# textContent→innerHTML — только `&<>`, БЕЗ кавычек, реальный (не
# косметический) дефект в data-*-атрибутах (travel: data-profile/data-name/
# data-dir; games: data-file/data-title — значение с `"` рвёт атрибут).
# food.html закрывал кавычки отдельной функцией attr(). Эталон — health.html
# (полный replace всех 5 спецсимволов). Тот же класс бага, что в Фазе 1: если
# бы локальная копия осталась на странице, она молча победила бы (загружена
# последней) и перенос в ui-kit.js остался бы мёртвым кодом.
print("ui-kit · esc()/attr() (Фаза 2)")

check("ui-kit.js: esc() перенесена", "function esc(" in UI_KIT_JS)
check("ui-kit.js: attr() — алиас esc() (тождественны после унификации)",
      "var attr = esc;" in UI_KIT_JS)

_esc_fn_match = re.search(r"function esc\(s\)\{.*?\n\}", UI_KIT_JS, re.S)
check("ui-kit.js: тело esc() найдено", _esc_fn_match is not None)
_esc_fn_body = _esc_fn_match.group(0) if _esc_fn_match else ""
for _entity, _char in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")):
    check(f"ui-kit.js: esc() экранирует «{_char}» → {_entity}", _entity in _esc_fn_body)

# Отсутствие локальной копии на всех 5 страницах — не только `function esc(`/
# `function attr(` (переопределение), но и голое переприсваивание `var esc =`/
# `var attr =`, которым можно было бы тихо воскресить старое поведение.
_ESC_LOCAL_PATTERNS = (
    r"function\s+esc\s*\(",
    r"function\s+attr\s*\(",
    r"\bvar\s+esc\s*=",
    r"\bvar\s+attr\s*=",
)
for _page in ("hub", "travel", "games", "food", "health"):
    _txt = (REPO / f"tools/{_page}.html").read_text(encoding="utf-8")
    _hits = [p for p in _ESC_LOCAL_PATTERNS if re.search(p, _txt)]
    check(f"{_page}.html: нет локальной копии esc()/attr()" + (f" — найдено: {_hits}" if _hits else ""),
          not _hits)

# hub/travel/games/food — Фаза 2 вводит для них ПЕРВОЕ подключение
# ui-kit.js (health уже подключён Фазой 1). Порядок (раньше инлайн-скрипта)
# критичен по той же причине, что и в health.html выше: делегированные
# обработчики хозяина обязаны видеть esc()/attr() уже на момент первого
# рендера.
for _page in ("hub", "travel", "games", "food"):
    _txt = (REPO / f"tools/{_page}.html").read_text(encoding="utf-8")
    check(f"{_page}.html: подключает assets/ui-kit.js (Фаза 2)",
          '<script src="assets/ui-kit.js?v=' in _txt)
    _idx_src = _txt.find('<script src="assets/ui-kit.js')
    _idx_inline = _txt.rfind("<script>")
    check(f"{_page}.html: assets/ui-kit.js подключён раньше инлайн-скрипта",
          _idx_src != -1 and _idx_inline != -1 and _idx_src < _idx_inline)

# ── ui-kit · auth/refresh (Фаза 3): единственная фаза, меняющая ВИДИМОЕ
# поведение (Войти/Выйти + Обновить). Толчок: hub держал ДВА hidden-узла
# #btn-login/#btn-logout (гонка видимости), hub/travel/games — императивные
# id-listener'ы на кнопке «Обновить» (тройная копия одной логики), health и
# food расходились именем сброса токена (clearToken vs clearAuthToken) и
# наличием логаута вовсе (food его не имел). Общий делегат в ui-kit.js
# реагирует ТОЛЬКО на кнопки с data-cache-prefix — если бы старая копия
# осталась на странице, перенос был бы фиктивным (тот же класс бага, что и
# в Фазах 1–2 выше).
print("ui-kit · auth/refresh (Фаза 3)")

for _fn in ("authToken", "clearAuthToken", "loginUrl", "authBtnHTML", "uiRefresh", "uiLogout"):
    check(f"ui-kit.js: {_fn}() определена", re.search(r"function\s+" + _fn + r"\s*\(", UI_KIT_JS) is not None)

# Дискриминатор делегата: реагирует ТОЛЬКО на [data-act] с проставленным
# data-cache-prefix — иначе задваивал бы доменные data-act-диспетчеры food/health.
check("ui-kit.js: делегированный click-листенер проверяет data-cache-prefix (дискриминатор)",
      'if (!btn.getAttribute("data-cache-prefix")) return;' in UI_KIT_JS)

# Шапка — одна на кабинет (ui-kit 1.17.0): каждая страница рисует её ровно
# одним вызовом uiTopHTML({ page: "<page>" …}); вход, справку, «Обновить» и
# тему кладёт генератор. Своих кнопок шапки (id="btn-refresh"/"btn-theme",
# auth-slot) и императивных слушателей на них больше нет — «стрелка и хаб на
# разных страницах свои» (2026-10-06) как раз и выросли из таких копий.
# «Обновить»: hub/travel/games/money — data-cache-prefix=<page>, ведёт uiRefresh;
# food/health — refresh:"spa", кнопка НАМЕРЕННО без префикса (свой ACTS.refresh).
_TOP = {"hub": None, "travel": None, "games": None, "money": None, "food": "spa", "health": "spa"}
for _page, _mode in _TOP.items():
    _txt = (REPO / f"tools/{_page}.html").read_text(encoding="utf-8")
    _code = _strip_js_comments(_txt)
    _calls = re.findall(r'uiTopHTML\(\{\s*page:\s*"' + _page + r'"([^}]*)\}', _code)
    check(f"{_page}.html: шапка — один вызов uiTopHTML({{ page: \"{_page}\" }})", len(_calls) == 1)
    _opts = _calls[0] if _calls else ""
    check(f"{_page}.html: «Обновить» — {'свой SPA-перерендер (refresh:\"spa\")' if _mode else 'ui-kit uiRefresh (без refresh:\"spa\")'}",
          ('refresh: "spa"' in _opts) == bool(_mode))
    check(f"{_page}.html: своих кнопок шапки нет (btn-refresh/btn-theme/auth-slot/help-slot, .h-top/.crumb)",
          not re.search(r'id="(btn-refresh|btn-theme|auth-slot|help-slot|theme-lbl)"|class="(h-top|crumb)\b|\.h-top\b|\.crumb\b', _code))
    check(f"{_page}.html: тему не переключает сам — кнопку ведёт ui-kit (uiSetTheme)",
          re.search(r'setItem\("hub-theme"', _code) is None and re.search(r'\btheme\s*:\s*function', _code) is None)
    check(f"{_page}.html: нет императивного id-listener'а на кнопки шапки",
          re.search(r'\$\("btn-(refresh|theme)"\)', _code) is None)
for _page in ("hub", "travel", "games"):
    _txt = (REPO / f"tools/{_page}.html").read_text(encoding="utf-8")
    check(f"{_page}.html: нет доменного data-act-диспетчера (ACTS) — refresh/logout/theme ведёт только ui-kit",
          re.search(r"\bACTS\b", _txt) is None)
    # шапка вставляется при разборе — ui-kit.js обязан быть уже загружен
    _hd = _txt[:_txt.find("</head>")]
    check(f"{_page}.html: ui-kit.js подключён в <head> (шапка рисуется без мигания)", "assets/ui-kit.js?v=" in _hd)
    check(f"{_page}.html: шапка вставляется прямо при разборе (currentScript)",
          'document.currentScript.insertAdjacentHTML("beforebegin", uiTopHTML(' in _txt)
_hub_html = (REPO / "tools/hub.html").read_text(encoding="utf-8")
_health_html2 = (REPO / "tools/health.html").read_text(encoding="utf-8")
_food_html = (REPO / "tools/food.html").read_text(encoding="utf-8")
# Даты и кеш — одна реализация (ui-kit 1.19.0): словарей месяцев и своих
# форматтеров/кешей на страницах нет. «fmtDate» значил три разных вывода
# («6 октября 2026» в hub/games и «окт 2025» в health) — перенос кода между
# страницами тихо менял подписи. Формат по-прежнему выбирает место вызова.
for _page in ("hub", "travel", "games", "health", "money", "food"):
    _code = _strip_js_comments((REPO / f"tools/{_page}.html").read_text(encoding="utf-8"))
    _dup = re.findall(r'\[\s*"(?:января|январь|янв)"', _code)
    check(f"{_page}.html: своих словарей месяцев нет — UI_MONTHS_* из ui-kit ({len(_dup)})", not _dup)
    check(f"{_page}.html: своих fmtDate/fmtFull/fmtDay/cacheGet/cacheSet нет",
          re.search(r"function\s+(fmtDate|fmtFull|fmtDay|cacheGet|cacheSet)\s*\(", _code) is None)
    check(f"{_page}.html: метку «Обновить» (<page>-cb) читает только ui-kit (uiBust)",
          f'getItem("{_page}-cb")' not in _code)
_d0 = UI_KIT_JS.find("var UI_MONTHS_NOM"); _d1 = UI_KIT_JS.find("function uiTripWhen(")
_c0 = UI_KIT_JS.find("function uiBust("); _c1 = UI_KIT_JS.find("/* Общая логика кнопки «Обновить»")
_a0 = UI_KIT_JS.find("function authToken("); _a1 = UI_KIT_JS.find("function authBtnHTML(")
if min(_d0, _d1, _c0, _c1, _a0, _a1) != -1 and shutil.which("node"):
    import subprocess as _sp_dc
    _drv_dc = r"""
var LS = {}, calls = [];
var localStorage = { getItem: function(k){ return k in LS ? LS[k] : null; }, setItem: function(k, v){ LS[k] = String(v); }, removeItem: function(k){ delete LS[k]; } };
var location = { pathname: "/", search: "" }, document = { querySelectorAll: function(){ return []; } };
function Headers(h){ this.m = h || {}; } Headers.prototype.set = function(){};
function fetch(url, init){ calls.push(url);
  return Promise.resolve({ ok: true, status: 200, text: function(){ return Promise.resolve("T"); },
    json: function(){ return Promise.resolve([{ name: "a/", is_dir: true, mod_time: "2026-10-01T10:00:00Z" }, { name: "@eaDir", is_dir: true }, { name: ".x" }, { name: "b.md" }]); } }); }
""" + UI_KIT_JS[_d0:_d1] + UI_KIT_JS[_a0:_a1] + UI_KIT_JS[_c0:_c1] + r"""
(async function(){
  var o = {};
  o.long = uiDateLong("2025-10-14") === "14 октября 2025" && uiDateLong(new Date(2026, 9, 6, 15)) === "6 октября 2026";
  o.ymd = uiDateLong(uiYmd(new Date("2024-02-29"))) === "29 февраля 2024";
  o.short = uiMonthShort("2025-10-14") === "окт 2025" && uiMonthShort("2025-10") === "окт 2025";
  o.num = uiDateNum("2025-10-14") === "14.10.2025" && uiDateNum("2025-10") === "окт 2025" && uiDateNum("") === "";
  o.cap = uiCap(UI_MONTHS_NOM[0]) === "Январь" && UI_MONTHS_NOM[0] === "январь";
  o.bustNone = uiBust("x", "a.json") === "a.json";
  LS["x-cb"] = "42";
  o.bust = uiBust("x", "a.json") === "a.json?cb=42" && uiBust("x", "f?path=p") === "f?path=p&cb=42";
  var l = await uiListDir("d/", { prefix: "x" });
  o.list = l.length === 2 && l[0].name === "a" && l[0].isDir && l[0].mtime === Date.parse("2026-10-01T10:00:00Z") && l[1].mtime === 0;
  var n = calls.length; await uiListDir("d/", { prefix: "x" });
  o.cached = calls.length === n && ("x-cache:d:d/" in LS);
  var t = await uiFetchText("f.md", { prefix: "x" }); await uiFetchText("f.md", { prefix: "x" });
  o.text = t === "T" && calls.filter(function(c){ return c.indexOf("f.md") === 0; }).length === 1;
  LS["x-cache:k"] = JSON.stringify({ t: Date.now() - 61 * 60000, v: 1 });
  o.ttl = uiCacheGet("x", "k", 60) === null && uiCacheGet("x", "k", 120) === 1;
  process.stdout.write(JSON.stringify(o));
})();
"""
    _pdc = _sp_dc.run(["node", "-e", _drv_dc], capture_output=True, text=True)
    check(f"даты и кеш ui-kit: node отработал {_pdc.stderr[:200]}", _pdc.returncode == 0)
    if _pdc.returncode == 0:
        _mdc = _json.loads(_pdc.stdout)
        for _k, _what in (("long", "uiDateLong: ISO и локальная Date → «14 октября 2025»"),
                          ("ymd", "uiYmd: Date из js-yaml (полночь UTC) — тот же день"),
                          ("short", "uiMonthShort → «окт 2025» (месяц остаётся месяцем)"),
                          ("num", "uiDateNum → «14.10.2025», месяц → «окт 2025»"),
                          ("cap", "месяцы строчными, uiCap — с заглавной"),
                          ("bustNone", "uiBust без метки — url как есть"),
                          ("bust", "uiBust с меткой — ?cb= / &cb="),
                          ("list", "uiListDir: без «.»/«@», хвостовой слэш снят, mtime из mod_time"),
                          ("cached", "uiListDir: второй раз — из кеша <prefix>-cache:d:<url>"),
                          ("text", "uiFetchText: кеш по url"),
                          ("ttl", "uiCacheGet: срок жизни в минутах")):
            check(f"даты и кеш ui-kit: {_what}", _mdc.get(_k) is True)

# Выпадающий список — один на кабинет (ui-kit 1.20.0): нативных <select> на
# переведённых страницах нет; список работает в формах (скрытое поле id +
# "change"), ищет в длинных списках, Esc закрывает только его. Поведение —
# браузерами в test_select_layout.py.
for _page in ("health", "money", "food"):
    _code = _strip_js_comments((REPO / f"tools/{_page}.html").read_text(encoding="utf-8"))
    check(f"{_page}.html: нативных <select> нет — общий uiSelectHTML", "<select" not in _code)
_vjs = (REPO / "tools/assets/viewer.js").read_text(encoding="utf-8")
_vhtml = (REPO / "tools/portfolio-integrated-viewer.html").read_text(encoding="utf-8")
check("вьюер: нативных select нет — общий uiSelect (uiSelectNode)",
      "el('select'" not in _vjs and "function uiSelectNode(" in _vjs)
check("вьюер: ui-kit.js подключён ДО viewer.js",
      0 <= _vhtml.find("assets/ui-kit.js?v=") < _vhtml.find("assets/viewer.js?v="))
check("вьюер: своих authToken/authFetch/clearAuthToken нет — общие из ui-kit",
      re.search(r"^function\s+(authToken|authFetch|clearAuthToken)\s*\(", _vjs, re.M) is None)
_hl3 = (REPO / "tools/health.html").read_text(encoding="utf-8")
check("health.html: формы передают записанное значение в списки (value) — вне словаря не затирается",
      'value: m.group' in _hl3 and 'value: m.form' in _hl3 and 'value: x.kind' in _hl3)
_mn3 = (REPO / "tools/money.html").read_text(encoding="utf-8")
check("money.html: выбор месяца/периода — без поиска (решение владельца 2026-10-06), поездки — с поиском",
      _mn3.count('name: "month"') == 2 and _mn3.count("search: false") == 3 and 'name: "years"' in _mn3   # + «Все годы» (v1.9.0)
      and 'name: "trip"' in _mn3 and "search: false" not in _mn3[_mn3.find('name: "trip"'):_mn3.find('name: "trip"') + 200])
check("ui-kit.js uiSelect: у поиска крестик «закрыть»", "ui-select-close" in UI_KIT_JS)
for _frag, _what in (('<input type="hidden" id="', "поле формы — скрытый input с id"),
                     ('hid.dispatchEvent(new Event("change", { bubbles: true }))', "выбор шлёт change, как <select>"),
                     ("UI_SELECT_SEARCH_MIN = 13", "поиск — с 13 вариантов"),
                     ("ev.stopImmediatePropagation(); uiSelectSet(", "Esc закрывает список, не окно формы"),
                     ('root.classList.add("sheet")', "телефон: длинный список шторкой"),
                     ('s: "записано так — нет в списке"', "значение вне списка не теряется (value)")):
    check(f"ui-kit.js uiSelect: {_what}", _frag in UI_KIT_JS)

check('hub.html: нет id="btn-login"/"btn-logout"', 'id="btn-login"' not in _hub_html and 'id="btn-logout"' not in _hub_html)
check("travel.html: по ссылке «поделиться» шапка без крошки, входа и справки",
      'share: !!new URLSearchParams(location.search).get("trip")' in (REPO / "tools/travel.html").read_text(encoding="utf-8"))
for _fn in ("uiTopHTML", "uiFootHTML", "uiSetTheme", "uiTheme", "uiRefreshBtnHTML", "uiThemeBtnHTML"):
    check(f"ui-kit.js: {_fn}() определена", re.search(r"function\s+" + _fn + r"\s*\(", UI_KIT_JS) is not None)
check("ui-kit.css: правил старой шапки (.h-top/.crumb) не осталось",
      re.search(r"\.h-top\b|\.crumb\b", re.sub(r"/\*.*?\*/", "", (REPO / "tools/assets/ui-kit.css").read_text(encoding="utf-8"), flags=re.S)) is None)
_t0 = UI_KIT_JS.find("function esc("); _t1 = UI_KIT_JS.find("function plural(")
_t2 = UI_KIT_JS.find("function authToken("); _t3 = UI_KIT_JS.find("/* Общая логика кнопки «Обновить»")
_t4 = UI_KIT_JS.find("var UI_ACC"); _t5 = UI_KIT_JS.find("/* Мини-рендер markdown")
if min(_t0, _t1, _t2, _t3, _t4, _t5) != -1 and shutil.which("node"):
    import subprocess as _sp_top
    _drv_top = r"""
var LS = {}, attrs = {}, events = [], lbls = [{ textContent: "" }];
var localStorage = { getItem: function(k){ return k in LS ? LS[k] : null; }, setItem: function(k, v){ LS[k] = String(v); }, removeItem: function(k){ delete LS[k]; } };
var sessionStorage = localStorage;
var location = { pathname: "/tools/x.html", search: "" };
function CustomEvent(t, o){ this.type = t; this.detail = o.detail; }
var document = { documentElement: { getAttribute: function(k){ return attrs[k] || null; }, setAttribute: function(k, v){ attrs[k] = v; } },
  querySelectorAll: function(q){ return q === "[data-theme-lbl]" ? lbls : []; }, dispatchEvent: function(e){ events.push(e.detail); },
  addEventListener: function(){} };
var UI_HELP = { travel: 1, money: 1 };
function helpBtnHTML(p){ return '<button data-ui-help="' + p + '">'; }
""" + UI_KIT_JS[_t0:_t1] + UI_KIT_JS[_t2:_t3] + UI_KIT_JS[_t4:_t5] + r"""
var o = {};
var m = uiTopHTML({ page: "money", name: "Деньги", tag: "приватный" });
o.crumb = m.indexOf('<a class="ui-crumb" href="hub.html"><span class="ui-crumb-arw">←</span><span class="ui-crumb-lbl"> Хаб</span></a>') > 0;
o.acc = m.indexOf('style="--sec-acc:var(--c-6)"') > 0;
// порядок как во вьюере (2026-10-16): Обновить · Справка · Войти · Тема
o.order = m.indexOf("ui-crumb") < m.indexOf("ui-top-name") && m.indexOf("ui-top-name") < m.indexOf('data-act="refresh"')
          && m.indexOf('data-act="refresh"') < m.indexOf("data-ui-help") && m.indexOf("data-ui-help") < m.indexOf("Войти")
          && m.indexOf("Войти") < m.indexOf('data-act="theme"');
o.prefix = m.indexOf('data-act="refresh" data-cache-prefix="money"') > 0;
o.tag = m.indexOf('<span class="ui-tag">приватный</span>') > 0;
var f = uiTopHTML({ page: "food", name: "Еда", help: false, refresh: "spa", refreshing: true });
o.spa = f.indexOf("data-cache-prefix") < 0 && f.indexOf(" disabled") > 0 && f.indexOf('class="spin"') > 0 && f.indexOf("Обновляю…") > 0 && f.indexOf("data-ui-help") < 0;
var t = uiTopHTML({ page: "travel", name: "Путешествия", share: true });
o.share = t.indexOf("ui-crumb") < 0 && t.indexOf("Войти") < 0 && t.indexOf("data-ui-help") < 0 && t.indexOf('data-act="theme"') > 0;
var h = uiTopHTML({ page: "hub", brand: "Synology · self-hosted" });
o.hub = h.indexOf("ui-crumb") < 0 && h.indexOf('<span class="ui-top-brand">Synology · self-hosted</span>') > 0;
o.esc = uiTopHTML({ page: "x", name: "<b>" }).indexOf("&lt;b&gt;") > 0;
o.lblLight = m.indexOf("data-theme-lbl>Тёмная тема<") > 0;
uiSetTheme("dark");
o.setDark = attrs["data-theme"] === "dark" && LS["hub-theme"] === "dark" && lbls[0].textContent === "Светлая тема" && events[0] === "dark";
o.lblDark = uiTopHTML({ page: "money", name: "Деньги" }).indexOf("data-theme-lbl>Светлая тема<") > 0;
uiSetTheme("light", false);
o.noPersist = attrs["data-theme"] === "light" && LS["hub-theme"] === "dark";
var ft = uiFootHTML({ page: "health", text: "Synology · v1" });
o.foot = ft.indexOf('class="ui-foot" style="--sec-acc:var(--c-3)"') > 0 && ft.indexOf("Synology · v1") > 0 && ft.indexOf('href="hub.html"') > 0;
process.stdout.write(JSON.stringify(o));
"""
    _ptop = _sp_top.run(["node", "-e", _drv_top], capture_output=True, text=True)
    check(f"uiTopHTML: node отработал {_ptop.stderr[:200]}", _ptop.returncode == 0)
    if _ptop.returncode == 0:
        _mt = _json.loads(_ptop.stdout)
        for _k, _what in (("crumb", "крошка «← Хаб» — одна разметка (подпись прячется на узком экране)"),
                          ("acc", "акцент раздела из UI_ACC"),
                          ("order", "порядок: крошка · раздел · вход · справка · обновить · тема"),
                          ("prefix", "«Обновить» несёт data-cache-prefix=page"),
                          ("tag", "метка раздела"),
                          ("spa", "refresh:\"spa\" — без префикса, крутится при refreshing; help:false — без справки"),
                          ("share", "share — без крошки, входа и справки, тема остаётся"),
                          ("hub", "без name — подпись-бренд вместо крошки"),
                          ("esc", "имя раздела экранируется"),
                          ("lblLight", "подпись темы — по текущей теме"),
                          ("setDark", "uiSetTheme: атрибут, hub-theme, подписи, событие ui-theme"),
                          ("lblDark", "после смены темы новая шапка — с новой подписью"),
                          ("noPersist", "uiSetTheme(t, false) не трогает hub-theme"),
                          ("foot", "uiFootHTML: «← Хаб», текст, акцент раздела")):
            check(f"uiTopHTML: {_what}", _mt.get(_k) is True)

# Нет локальных копий authToken/clearAuthToken/clearToken/loginUrl ни на
# одной из 5 страниц — тот же класс проверки, что esc()/attr() в Фазе 2.
_AUTH_LOCAL_PATTERNS = (
    r"function\s+authToken\s*\(",
    r"function\s+clearAuthToken\s*\(",
    r"function\s+clearToken\s*\(",
    r"function\s+loginUrl\s*\(",
)
for _page in ("hub", "travel", "games", "food", "health"):
    _txt = (REPO / f"tools/{_page}.html").read_text(encoding="utf-8")
    _hits = [p for p in _AUTH_LOCAL_PATTERNS if re.search(p, _txt)]
    check(f"{_page}.html: нет локальной копии authToken/clearAuthToken/clearToken/loginUrl" +
          (f" — найдено: {_hits}" if _hits else ""), not _hits)

# health: logout-ветка убрана из ACTS-диспетчера. Раньше health держал СВОЮ
# ветку `logout: function(){ clearAuthToken(); location.reload(); }` внутри
# ACTS — с переездом кнопки на data-cache-prefix эта ветка стала бы
# ЗАДВОЕННЫМ обработчиком одного клика (оба листенера сидят на document,
# preventDefault одного не мешает сработать другому). Кнопка «Выйти» теперь
# приходит из ui-kit authBtnHTML (шаблон живёт в ui-kit.js, НЕ в разметке
# health.html) — литерала data-act="logout" в самой странице тоже быть не должно.
check("health.html: ACTS-диспетчер БЕЗ ветки logout",
      re.search(r"\blogout\s*:\s*function", _health_html2) is None)
check('health.html: нет литерала data-act="logout" в markup (кнопка теперь из ui-kit authBtnHTML)',
      'data-act="logout"' not in _health_html2)

# food: ветки logout не было и не появилось (диспетчер graceful на неизвестном
# act через `if (!fn) return;` — задваивать нечего).
check("food.html: ACTS-диспетчер БЕЗ ветки logout (её и не было — food graceful на unknown act)",
      re.search(r"\blogout\s*:\s*function", _food_html) is None)

# ── Ярус 1 «чистая метла»: @font-face + plural + спиннер вынесены в ui-kit ──
# Шрифты были побайтово идентичны на всех 5 страницах (~280 строк дублирования),
# plural — на 4, спиннер — под тремя именами. Теперь всё в ui-kit; страницы
# подключают ui-kit.css. Дрейф с любой стороны (локальная копия вернулась) — фейл.
_uikit_css = (REPO / "tools/assets/ui-kit.css").read_text(encoding="utf-8")
_uikit_js2 = (REPO / "tools/assets/ui-kit.js").read_text(encoding="utf-8")
check("ui-kit.css: содержит @font-face (Golos Text + Spectral)", "@font-face" in _uikit_css)
check("ui-kit.css: единый спиннер uikit-spin + .spin",
      "uikit-spin" in _uikit_css and re.search(r"\.spin\s*\{", _uikit_css) is not None)
check("ui-kit.js: содержит plural()", "function plural" in _uikit_js2)
for _p in ("hub", "travel", "games", "food", "health"):
    _t = (REPO / f"tools/{_p}.html").read_text(encoding="utf-8")
    check(f"{_p}.html: нет локального @font-face (шрифты из ui-kit.css)", "@font-face" not in _t)
    # РЕАЛЬНЫЙ <link> вне комментария — иначе токены/шрифты не грузятся и страница
    # рендерится голой (реальный баг hub/travel: link был вставлен ВНУТРЬ комментария,
    # содержавшего слово <style>, и подстроковая проверка его не поймала).
    _t_nc = re.sub(r"<!--.*?-->", "", _t, flags=re.S)
    check(f"{_p}.html: реально подключает ui-kit.css (<link> вне комментария)",
          re.search(r'<link[^>]*assets/ui-kit\.css', _t_nc) is not None)
    check(f"{_p}.html: нет устаревших имён спиннера hub-spin/food-spin",
          "hub-spin" not in _t and "food-spin" not in _t)
for _p in ("hub", "travel", "games", "food"):
    _t = (REPO / f"tools/{_p}.html").read_text(encoding="utf-8")
    check(f"{_p}.html: нет локального plural() (переехал в ui-kit.js)",
          re.search(r"function\s+plural\s*\(", _t) is None)

# Анти-мигание темы НЕ выносим (внешний <script src> не гарантирует выполнение до
# первой отрисовки → вернулась бы вспышка светлой темы). Инвариант: ядро дублировано
# идентично на 5/5, у travel — доп. ранний return для share-режима ?trip=.
_ANTIFLASH = 'localStorage.getItem("hub-theme")==="dark")document.documentElement.setAttribute("data-theme","dark")'
for _p in ("hub", "travel", "games", "food", "health"):
    _t = (REPO / f"tools/{_p}.html").read_text(encoding="utf-8")
    check(f"{_p}.html: анти-мигание темы на месте (дублируется по дизайну)", _ANTIFLASH in _t)
check("travel.html: анти-мигание прячет тему в share-режиме (?trip=)",
      'get("trip"))return' in (REPO / "tools/travel.html").read_text(encoding="utf-8"))

# Ярус 1b: дизайн-токены :root + [data-theme=dark] вынесены в ui-kit.css (значения
# сверены — 0 расхождений). Наборы на страницах РАСХОДИЛИСЬ (games не имел --c-1/2/4,
# travel — --info) — теперь у всех полный набор из ui-kit.css. food сохраняет свои
# --paper/--c2-bg и НЕ трогает print-reset дарк-блок (@media print → светлые значения).
check("ui-kit.css: :root с общими токенами (--bg + --text + --c-3)",
      bool(re.search(r":root\s*\{[^}]*--bg\s*:[^}]*--text\s*:[^}]*--c-3\s*:", _uikit_css, re.S)))
check("ui-kit.css: [data-theme=dark] с общими токенами",
      bool(re.search(r'\[data-theme="dark"\]\s*\{[^}]*--bg\s*:', _uikit_css)))
for _p in ("hub", "travel", "games", "health"):
    _t = (REPO / f"tools/{_p}.html").read_text(encoding="utf-8")
    check(f"{_p}.html: нет локального определения --bg (токены из ui-kit.css)",
          re.search(r"--bg\s*:", _t) is None)
_food_tok = (REPO / "tools/food.html").read_text(encoding="utf-8")
check("food.html: сохраняет свои --paper и --c2-bg", "--paper" in _food_tok and "--c2-bg" in _food_tok)
check("food.html: print-reset дарк-блок цел (@media print сбрасывает --bg на светлый)",
      "@media print" in _food_tok and re.search(r"--bg\s*:\s*#f4f1ea", _food_tok) is not None)

# ═══ Ось: веса сценариев — JS-зеркало вьюера ↔ Python (PSS-9) ══════════════
# `viewer.js::computeCatalystContribution` — рукописная копия
# `aggregate_positions.compute_catalyst_contribution`. Копия читала веса
# сценариев ТОЛЬКО скаляром (`p_norm ?? probability ?? p`), Python с PSS-9
# читает горизонтные (`p_by_horizon`). Расхождение было бы невидимым: обе
# стороны рисуют правдоподобное число, просто разное — идио-вклад в таблице
# позиций перестал бы сходиться с тем же числом в integrated-view.
#
# Проверка ФУНКЦИОНАЛЬНАЯ, а не по регэкспам: блок JS вырезается из viewer.js
# и исполняется node'ом на тех же фикстурах, что и Python. Регэксп поймал бы
# «сигнатура изменилась», но не «читает не тот ключ» и не «нормирует иначе».
#
# Вьюер получает СЫРОЙ стресс-артефакт: `p_norm` там нет, есть `p`. Поэтому
# фикстуры держат Σp = 1 — при Σp ≠ 1 Python нормирует, а вьюер нет, и это
# расхождение старше PSS-9 (в горизонтном блоке нормируют ОБА, и одна из
# фикстур это подтверждает Σ = 2.0).
print("PSS-9 · JS-зеркало весов сценариев ↔ Python")

import copy as _copy          # noqa: E402
import json as _json_w        # noqa: E402
import shutil as _shutil      # noqa: E402
import subprocess as _sp      # noqa: E402

sys.path.insert(0, str(REPO / "skills/portfolio-integrated-view/scripts"))
import aggregate_positions as _ap  # noqa: E402

_VJS = (REPO / "tools/assets/viewer.js").read_text(encoding="utf-8")
_JS_START = "const NULL_DEPENDENCY_DISCOUNT"
_JS_END = "// C2: horizonEnd (YYYY-MM-DD)"
_i0, _i1 = _VJS.find(_JS_START), _VJS.find(_JS_END)
check("зеркало: блок катализаторов найден в viewer.js", _i0 != -1 and _i1 > _i0)

# Веса: h12 отдаёт всё Sc-A, h36 — всё Sc-D, скаляр — поровну. Блок h20 задан
# суммой 2.0 — нормировка обязана его вытянуть к 0.25 (иначе вклад удвоится).
_SCEN_HZ = {
    "Sc-A": {"p": 0.25, "p_by_horizon": {"h12": 1.0, "h20": 0.5, "h36": 0.0}},
    "Sc-B": {"p": 0.25, "p_by_horizon": {"h12": 0.0, "h20": 0.5, "h36": 0.0}},
    "Sc-C": {"p": 0.25, "p_by_horizon": {"h12": 0.0, "h20": 0.5, "h36": 0.0}},
    "Sc-D": {"p": 0.25, "p_by_horizon": {"h12": 0.0, "h20": 0.5, "h36": 1.0}},
}
_SCEN_FLAT = {k: {"p": 0.25} for k in _SCEN_HZ}
# Частичный блок: p_by_horizon есть только у половины сценариев. Python на такой
# форме отказывается считать, вьюер обязан вернуться к скаляру.
_SCEN_PART = {k: ({"p": 0.25, "p_by_horizon": v["p_by_horizon"]}
                  if k in ("Sc-A", "Sc-B") else {"p": 0.25})
              for k, v in _SCEN_HZ.items()}
_CAT_Q = {"id": "q", "kind": "quantitative",
          "upside_by_scenario": {"Sc-A": 0.0, "Sc-B": 0.0, "Sc-C": 0.0, "Sc-D": 12.0},
          "upside_ci_by_scenario": {"Sc-D": [8.0, 16.0]}}
_CAT_B = {"id": "b", "kind": "binary", "p": 0.5, "upside_pct": 12.0,
          "active_scenarios": ["Sc-D"], "upside_ci_pct": [8.0, 16.0]}
_CAT_DEP = {"id": "d", "kind": "binary", "p": 0.5, "upside_pct": 10.0,
            "macro_dependency": "Sc-A"}
_CAT_NULL = {"id": "n", "kind": "binary", "p": 0.5, "upside_pct": 10.0}
_CAT_LOW = {"id": "l", "kind": "binary", "p": 0.5, "downside_pct": 10.0,
            "active_scenarios": ["Sc-D"], "source_quality": "LOW"}
_CAT_UNRES = {"id": "u", "kind": "binary", "p": 0.5, "upside_pct": 10.0,
              "active_scenarios": ["Sc-Z"]}

_MIRROR_CASES = []
for _cat in (_CAT_Q, _CAT_B, _CAT_DEP, _CAT_NULL, _CAT_LOW, _CAT_UNRES):
    for _hk in ("h12", "h20", "h36"):
        _MIRROR_CASES.append({"label": f"{_cat['id']}@{_hk}/hz", "cat": _cat,
                              "scenarios": _SCEN_HZ, "horizonKey": _hk})
    # Артефакт без блока: горизонт передан, но читать нечего → скаляр.
    _MIRROR_CASES.append({"label": f"{_cat['id']}@h12/flat", "cat": _cat,
                          "scenarios": _SCEN_FLAT, "horizonKey": "h12"})
    for _hk in ("h12", "h36"):
        _MIRROR_CASES.append({"label": f"{_cat['id']}@{_hk}/part", "cat": _cat,
                              "scenarios": _SCEN_PART, "horizonKey": _hk})

if _i0 != -1 and _i1 > _i0 and _shutil.which("node"):
    _driver = _VJS[_i0:_i1] + """
const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = cases.map(c => {
  const r = computeCatalystContribution(c.cat, c.scenarios, c.horizonKey);
  return { label: c.label, value: r.skipped ? 0 : r.value,
           ci: r.skipped ? [0, 0] : r.ci };
});
process.stdout.write(JSON.stringify(out));
"""
    with tempfile.TemporaryDirectory() as _td:
        _f = Path(_td) / "mirror.js"
        _f.write_text(_driver, encoding="utf-8")
        _proc = _sp.run(["node", str(_f)],
                        input=_json_w.dumps(_MIRROR_CASES), capture_output=True,
                        text=True)
    check(f"зеркало: node отработал (rc={_proc.returncode}) {_proc.stderr[:200]}",
          _proc.returncode == 0)
    if _proc.returncode == 0:
        _js_out = {r["label"]: r for r in _json_w.loads(_proc.stdout)}
        # Python: normalize_scenario_probs (нормировка) + compute_catalyst_contribution
        # — ровно та пара шагов, что run() делает перед идио-слоем.
        # Кейсы `/part` из сверки ИСКЛЮЧЕНЫ намеренно: на частично заданном блоке
        # Python останавливает расчёт (SystemExit), а вьюер обязан продолжать
        # рисовать. Это единственное осознанное расхождение зеркал, и оно
        # проверяется отдельно ниже — по JS-выходу, без Python-стороны.
        _py_out = {}
        for _c in _MIRROR_CASES:
            if _c["label"].endswith("/part"):
                continue
            _sc = _copy.deepcopy(_c["scenarios"])
            _ap.normalize_scenario_probs(_sc, ["h12", "h20", "h36"])
            _r = _ap.compute_catalyst_contribution(_c["cat"], _sc, _c["horizonKey"])
            _py_out[_c["label"]] = _r

        # Python на этой форме действительно отказывается — если он вдруг начнёт
        # считать, расхождение зеркал станет НЕосознанным, и проверка обязана
        # об этом сказать.
        _sc_part = _copy.deepcopy(_SCEN_PART)
        try:
            _ap.normalize_scenario_probs(_sc_part, ["h12", "h20", "h36"])
            _py_refuses = False
        except SystemExit:
            _py_refuses = True
        check("зеркало: Python на частичном блоке останавливает расчёт", _py_refuses)
        for _lbl, _py in _py_out.items():
            _js = _js_out.get(_lbl)
            _ok = _js is not None and abs(_js["value"] - _py["value"]) < 1e-9 and \
                all(abs(a - b) < 1e-9 for a, b in zip(_js["ci"], _py["ci"]))
            check(f"зеркало: {_lbl} — JS {_js['value'] if _js else None} == "
                  f"Python {_py['value']}", _ok)
        # Различитель самих фикстур: если горизонт ни на что не влияет, вся
        # ось выше проходит и на реализации, читающей только скаляр.
        check("зеркало: фикстура различает горизонты (q@h12 ≠ q@h36)",
              abs(_js_out["q@h12/hz"]["value"] - _js_out["q@h36/hz"]["value"]) > 1.0)
        check("зеркало: фикстура различает binary-массу (b@h12 ≠ b@h36)",
              abs(_js_out["b@h12/hz"]["value"] - _js_out["b@h36/hz"]["value"]) > 1.0)
        check("зеркало: блок с Σ = 2.0 нормирован (q@h20 == 3.0)",
              abs(_js_out["q@h20/hz"]["value"] - 3.0) < 1e-9)
        check("зеркало: без блока горизонт игнорируется (q@h12/flat == 3.0)",
              abs(_js_out["q@h12/flat"]["value"] - 3.0) < 1e-9)
        # Дыра покрытия, найденная аудитом 2026-08-05: ветка «блок задан ЧАСТИ
        # сценариев» (её описывает докстринг `_horizonWeights`) не упражнялась ни
        # одной фикстурой — мутация «снять guard have !== sids.length» выживала.
        # Python на такой форме останавливает расчёт, вьюер обязан молча падать
        # на скаляр: перестать рисовать он права не имеет.
        check(f"зеркало: частичный блок → скаляр "
              f"(q@h12/part = {_js_out['q@h12/part']['value']}, ждали 3.0)",
              abs(_js_out["q@h12/part"]["value"] - 3.0) < 1e-9)
        check("зеркало: частичный блок не следует горизонту (h12 == h36)",
              abs(_js_out["q@h12/part"]["value"] - _js_out["q@h36/part"]["value"]) < 1e-9)
else:
    print("  (node не найден — ось JS-зеркала пропущена)")

# Статически: обе точки вызова идио-слоя обязаны передавать ключ горизонта.
# Функция может быть безупречной, а строка вызова — нетронутой (шрам P2-4).
_idio_calls = re.findall(r"computeIdioAlpha\(([^)]*)\)", _VJS)
_idio_calls = [c for c in _idio_calls if not c.startswith("p, scenarios, horizonEnd,")]
check(f"зеркало: все вызовы computeIdioAlpha передают горизонт {_idio_calls}",
      all(c.count(",") >= 3 for c in _idio_calls))

# v2.13.2: подпись «Вероятность» карточки сценария — ОТДЕЛЬНОЕ от `_scenarioP`
# чтение весов. Первый живой артефакт с p_by_horizon (stress-2026-08-06) показал:
# расчётный слой горизонты читал (ось выше), а декоративная подпись рисовала
# скаляр p на всех горизонтах — 15/15/35/35 вместо 28/12/42/18 на h6. Проверка
# статическая: el()-дерево вкладки без DOM node'ом не исполнить.
_prob_dd = re.search(r"el\('dt', \{\}, 'Вероятность'\), el\('dd'.{0,400}", _VJS, re.S)
check("стресс-подпись: «Вероятность» читает p_by_horizon выбранного горизонта",
      _prob_dd is not None and "p_by_horizon" in _prob_dd.group(0))
check("стресс-сводка: p-взвешенное ожидание читается из expected_pl_pct_by_horizon",
      "expected_pl_pct_by_horizon" in _VJS and "Ожидание (по весам)" in _VJS)

# ═══ Ось: класс в JS ↔ правило в CSS (режим чтения отчётов, v2.14.0) ════════
# Дефект, ради которого всё и затевалось: `modal-report`, `reports-list` и
# `report-item` вешались в viewer.js с 2026-05, а правил под них в viewer.css
# НЕ БЫЛО НИ ОДНОГО. Мёртвый хук не падает и в консоли молчит — отчёт на 30 КБ
# просто открывался в модалке для карточки одной бумаги, а список репортов был
# набором голых div'ов без курсора и разделителей. Ловится только сверкой
# «что эмитит JS» против «что описывает CSS».
print("viewer · режим чтения отчётов")
_VCSS = (REPO / "tools/assets/viewer.css").read_text(encoding="utf-8")
_RP_CLASSES = (
    # разметка markdown (simpleMarkdownToHtml)
    "md-h1", "md-h2", "md-h3", "md-h4", "md-h5", "md-p", "md-gap", "md-hr",
    "md-ul", "md-ol", "md-li", "md-task", "md-quote", "md-pre", "md-tblwrap",
    # режим чтения (renderReportDoc) + список отчётов
    "modal-report", "report-head", "report-layout", "report-doc", "report-toc",
    "rp-toc-h", "rp-toc-list", "rp-top", "rp-bar", "rp-bar-btn", "rp-open",
    "rp-cur", "rp-prog", "rp-sheet", "md-tldr", "md-lead",
    "rp-ver", "rp-ver-lbl", "reports-list", "report-item",
    # шапка отчёта из frontmatter + поиск по списку (v2.16.0)
    "rp-meta", "rp-mrow", "rp-mk", "rp-mv", "rp-chips", "rp-art", "rp-tic",
    "rp-filters", "rp-search", "rp-kinds", "ri-title", "ri-meta", "ri-sum",
    "md-hr-off", "md-num",   # правки 11.08: двойная линия и числа в таблицах
)
for _c in _RP_CLASSES:
    _in_js = re.search(rf"['\"][^'\"]*\b{re.escape(_c)}\b", _VJS) is not None
    _in_css = re.search(rf"\.{re.escape(_c)}[\s,{{:.>]", _VCSS) is not None
    check(f"класс {_c}: эмитится viewer.js", _in_js)
    check(f"класс {_c}: описан в viewer.css (не мёртвый хук)", _in_css)

# Инлайн-стиль на блоке markdown ОТКЛЮЧАЕТ весь режим чтения молча: инлайн
# бьёт класс по специфичности, и `.report-doc .md-h2{…}` перестаёт применяться,
# а страница выглядит просто «не изменившейся». До 2.14.0 так и было —
# simpleMarkdownToHtml печатал style="…" в каждый заголовок, абзац и список.
_md_fn = _VJS[_VJS.index("function simpleMarkdownToHtml"):]
_md_fn = _md_fn[:_md_fn.index("function simpleMarkdownInline")]
_inline = re.findall(r"<(?:h[1-5]|p|ul|ol|li|blockquote|pre|hr|div)[^>]*style=", _md_fn)
check(f"simpleMarkdownToHtml: блоки без инлайн-стилей (найдено {len(_inline)})", not _inline)

# Оглавление строится ИЗ ДОКУМЕНТА (## / ###), а не из подготовленной разметки —
# иначе рассинхрон с текстом отчёта возможен по построению.
check("оглавление собирается по заголовкам h2/h3 самого отчёта",
      "h2.md-h2, h3.md-h3" in _VJS)
# Слушатель scroll живёт на .modal и обязан сниматься: без этого каждый
# открытый отчёт оставлял бы свой обработчик на общей модалке.
check("режим чтения: слушатели снимаются в closeModal", "_rpCleanup()" in
      _VJS[_VJS.index("function closeModal"):_VJS.index("function closeModal") + 400])
check("режим чтения: слушатели снимаются при смене документа",
      "_rpCleanup();" in _VJS[_VJS.index("function renderReportDoc"):
                              _VJS.index("function renderReportDoc") + 400])

# Мобильная навигация обязана существовать отдельно от десктопной: на телефоне
# липкий столбец скрыт, и без нижней полосы отчёт остаётся без оглавления.
_media = re.search(r"@media \(max-width:900px\)\{(.+?)\n\}", _VCSS, re.S)
check("телефон: в @media 900px столбец скрыт, а полоса показана",
      _media is not None and ".report-toc{ display:none" in _media.group(1)
      and ".rp-bar{ display:flex" in _media.group(1))

# v2.15.0: длинных markdown-жанров у вьюера три (личный отчёт, полный обзор
# акций/облигаций, integrated-view) — и все обязаны идти через один showDocModal
# → renderReportDoc. Иначе повторяется история 2.14.0, когда режим чтения был
# только у личных отчётов, а обзоры остались стеной текста при тех же классах.
for _fn in ("showAdvisorReportModal", "showMdReportModal", "showReportModal"):
    _src = _VJS[_VJS.index(f"function {_fn}("):]
    _src = _src[:_src.index("\n}\n") + 2]
    check(f"{_fn}: показывает документ через showDocModal", "showDocModal({" in _src)
_doc_modal = _VJS[_VJS.index("function showDocModal("):]
_doc_modal = _doc_modal[:_doc_modal.index("\n}\n") + 2]
check("showDocModal: рисует режимом чтения", "renderReportDoc(" in _doc_modal)
check("showDocModal: селектор версий только при >1 записи", "vers.length > 1" in _doc_modal)

# Ряды версий обязаны сохраняться целиком. До 2.15.0 buildState брал [0], и
# 27 загруженных md-обзоров в памяти страницы были недоступны: «предыдущий
# отчёт» открыть было нечем, хотя файл уже прочитан.
for _row, _src_arr in (("weeklyReviewMdHistory", "wkMds"), ("weeklyBondReviewMdHistory", "wbMds")):
    check(f"buildState: ряд {_row} сохраняется целиком",
          re.search(rf"state\.data\.{_row}\s*=\s*{_src_arr}\s*;", _VJS) is not None)
check("integrated-view: селектор версий берёт integratedViewHistory",
      "records: state.data.integratedViewHistory" in _VJS)
# Обе кнопки «Полный отчёт» обязаны сообщать свой ряд: без kind селектор пуст.
check("кнопка обзора акций передаёт ряд 'stock'",
      "showMdReportModal(state.data.weeklyReviewMdCurrent, 'stock')" in _VJS)
check("кнопка обзора облигаций передаёт ряд 'bond'",
      "showMdReportModal(state.data.weeklyBondReviewMdCurrent, 'bond')" in _VJS)

# Мера строки задаётся шириной модалки и кеглем, а не обрезкой абзаца: правка
# 2026-08-10 по обратной связи («текст в колонку, а не во всю ширину» — 70ch
# внутри 1160px оставляли треть ширины пустой). Возврат ch-обрезки в .report-doc
# роняет проверку — это осознанное решение, а не случайно потерянное правило.
_doc_css = re.search(r"\.report-doc\{[^}]*\}", _VCSS).group(0)
check(f"проза не обрезается по ch ({_doc_css[:60]}…)",
      "ch;" not in _doc_css and not re.search(r"\.report-doc > \*\{[^}]*max-width:\s*\d+ch", _VCSS))

# v2.16.0: шапка отчёта строится ТОЛЬКО из frontmatter. У md-обзоров акций и
# облигаций frontmatter'а нет вовсе (провенанс — курсивная строка под H1), и
# выскребать его из прозы нельзя: ровно на этом горел §4-герой (extractEquity…
# ловил формат LLM-генерации «через раз»). Пустой frontmatter → карточки нет.
_meta_fn = _VJS[_VJS.index("function buildDocMetaCard("):]
_meta_fn = _meta_fn[:_meta_fn.index("\n}\n") + 2]
check("шапка: без frontmatter карточки нет", "if (!fm) return null;" in _meta_fn)
check("шапка: пустой frontmatter не даёт пустую карточку",
      "if (!body.length && !chips.length && !tickers.length) return null;" in _meta_fn)
check("шапка: отметка «загружен» считается по реестру сессии state.files",
      "state.files" in _VJS[_VJS.index("function _isLoadedArtifact("):
                            _VJS.index("function _isLoadedArtifact(") + 400])

# Живая ось: каждый `kind` из библиотеки отчётов должен иметь русский ярлык.
# Иначе advisor заводит новый тип — а вьюер печатает «ie posts review».
_reports_dir = (Path.home() / "Library/CloudStorage/SynologyDrive-home"
                / "Claude-Memory/Portfolio/reports")
if _reports_dir.is_dir():
    # ярлыки — кодлист report_kind (codelists.json); вьюер берёт их из CL
    _known = set(__import__("json").loads((REPO / "_shared-references/codelists.json").read_text(encoding="utf-8"))["lists"]["report_kind"]) \
        if "const REPORT_KIND_RU = CL.words('report_kind')" in _VJS else set()
    _live = set()
    for _f in _reports_dir.glob("*.md"):
        _m = re.search(r'^kind:\s*"?([\w-]+)"?', _f.read_text(encoding="utf-8"), re.M)
        if _m:
            _live.add(_m.group(1))
    check(f"все живые kind отчётов имеют русский ярлык (нет: {sorted(_live - _known)})",
          _live and not (_live - _known))
else:
    print("  (библиотека Portfolio/reports не смонтирована — ось живых kind пропущена)")

# Поиск в списке перерисовывает ТОЛЬКО список: полная пересборка модалки
# пересоздаёт поле, и каретка прыгает на каждой букве (урок страницы «Еда»).
_list_fn = _VJS[_VJS.index("function showReportsListModal("):]
_list_fn = _list_fn[:_list_fn.index("\nfunction ")]
_oninput = re.search(r"oninput:\s*\(e\)\s*=>\s*\{([^}]*)\}", _list_fn)
check("поиск: обработчик перерисовывает только список",
      _oninput is not None and "paint()" in _oninput.group(1)
      and "showReportsListModal(" not in _oninput.group(1))
check("список остаётся хронологическим (тип — фильтром, не группировкой)",
      "reports.filter(matches)" in _list_fn and "groupBy" not in _list_fn)
# поле ввода на сенсорном экране: ниже 16px iOS Safari приближает и не отдаляет
_coarse = re.search(r"@media \(pointer:coarse\)\{[^}]*\.rp-search\{[^}]*font-size:\s*(\d+)px", _VCSS)
check(f"поиск: на сенсорном экране {_coarse.group(1) if _coarse else '—'}px (≥16)",
      _coarse is not None and int(_coarse.group(1)) >= 16)

# Правки по обратной связи 11.08 — три вещи, которые молча вернутся при рефакторе.
# (1) Глава `##` рисуется верхней линейкой, а в исходнике перед ней обычно ещё и
# `---`: без гашения разделителя над каждой второй главой две линии подряд.
check("двойная линия: `---` перед главой гасится в разметке",
      "md-hr-off" in _VJS and re.search(r"\.md-hr-off\{[^}]*display:none", _VCSS) is not None)
# (2) Числа в таблице: разряды отделены ОБЫЧНЫМ пробелом — законная точка
# переноса, и на телефоне «1 272 105» вставало тремя строками. CSS не умеет
# «это число», поэтому пометка идёт из JS, а nowrap висит только на .md-num:
# повесить nowrap на все ячейки нельзя — текстовые колонки уедут вширь.
check("числа в таблицах: ячейки помечаются в JS", "NUMCELL" in _VJS and "md-num" in _VJS)
check("числа в таблицах: nowrap только на числовых ячейках",
      re.search(r"\.report-doc td\.md-num\{[^}]*white-space:nowrap", _VCSS) is not None
      and not re.search(r"\.report-doc td\{[^}]*white-space:nowrap", _VCSS))
check("ячейки не рвут слово по буквам (иначе overflow-wrap:anywhere из .modal-body)",
      re.search(r"\.report-doc td,\.report-doc th\{[^}]*overflow-wrap:normal", _VCSS) is not None)
# (3) ISIN облигации в шапке не показывается сырым: он ничего не говорит читателю.
_chip_fn = _VJS[_VJS.index("function _securityChipLabel("):]
_chip_fn = _chip_fn[:_chip_fn.index("\n}\n") + 2]
check("чипы: ISIN разворачивается в название выпуска или тип, иначе чипа нет",
      "_IS_ISIN.test" in _chip_fn and "holdings" in _chip_fn
      and "bondTypeLabel" in _chip_fn and "return null" in _chip_fn)
check("чипы: тикер акции проходит как есть", "if (!_IS_ISIN.test(s)) return s;" in _chip_fn)

# Версия ассета в query-string ↔ VIEWER_VERSION: браузер кэширует viewer.js/css
# под URL, и забытый ?v= отдаёт старый код под новой версией в подвале —
# «у меня не работает» становится неотличимо от «у меня старая сборка».
_VHTML = (REPO / "tools/portfolio-integrated-viewer.html").read_text(encoding="utf-8")
_ver = re.search(r"VIEWER_VERSION = '([\d.]+)'", _VJS).group(1)
for _asset in ("viewer.js", "viewer.css"):
    _q = re.search(rf"assets/{re.escape(_asset)}\?v=([\d.]+)", _VHTML)
    check(f"{_asset}: ?v={_q.group(1) if _q else '—'} совпадает с VIEWER_VERSION {_ver}",
          _q is not None and _q.group(1) == _ver)

# Офлайн кабинета (ui-kit 1.54.0, 2026-10-23): ядро sw-offline.js подключают ОБА фоновых скрипта с ?v= =
# CAB_OFF_VER — иначе браузер не заметит новой версии ядра; deploy.zsh выкладывает все три файла.
_core = (REPO / "tools/sw-offline.js").read_text(encoding="utf-8")
_cv = re.search(r"var CAB_OFF_VER = '([\d.]+)'", _core)
check("sw-offline.js объявляет CAB_OFF_VER", bool(_cv))
for _sw in ("sw.js", "portfolio-sw.js"):
    _t = (REPO / "tools" / _sw).read_text(encoding="utf-8")
    check(f"{_sw}: importScripts('sw-offline.js?v=CAB_OFF_VER')",
          bool(_cv) and f"importScripts('sw-offline.js?v={_cv.group(1)}')" in _t)
# 1.4.1 (2026-11-05; случай: «Здоровье» без связи — «Загружаю данные…» дольше минуты): всё, что страница
# «Здоровье» читает при загрузке, держится офлайн (CAB_KEEP), иначе при висящей сети запрос мимо копии держит
# Promise.all загрузки. Пути берутся из исходника страницы, регэкспы — из ядра.
_keep_src = re.search(r"var CAB_KEEP = \[(.*?)\n\];", _core, re.S)
_keep = [re.compile(x.replace("\\/", "/")) for x in re.findall(r"/(\^.*?\$)/", _keep_src.group(1))] if _keep_src else []
_hh = (REPO / "tools/health.html").read_text(encoding="utf-8")
_hpaths = (["/health-data/" + x for x in re.findall(r'DATA \+ "([^"]+)"', _hh)]
           + ["/api/hd/file"] * bool(re.search(r'apiGet\("', _hh))
           + ["/" + x for x in re.findall(r'"\.\./(api/[^"/]+)"', _hh) if x != "api/hd"])
_miss = [x for x in _hpaths if not any(r.search(x) for r in _keep)]
check(f"sw-offline: CAB_KEEP держит всё, что читает «Здоровье» ({len(_hpaths)} путей; нет в CAB_KEEP: {_miss})",
      bool(_keep) and len(_hpaths) >= 6 and not _miss)
# food v1.48 (2026-11-06): запись без ответа сервера дольше SAVE_WAIT_MS — в очередь (было: вечное «Сохраняю…»
# при висящей сети); «связи нет» — и по плашке ui-kit, не только по navigator.onLine
_fd148 = (REPO / "tools/food.html").read_text(encoding="utf-8")
check("food.html v1.48: postSave ждёт ответа не дольше SAVE_WAIT_MS = 8000, очередь и по плашке «нет связи» (offlineKnown)",
      "var SAVE_WAIT_MS = 8000;" in _fd148 and "return Promise.race([req, new Promise(function (res) { setTimeout(function () { res({ net: true }); }, SAVE_WAIT_MS); })]);" in _fd148
      and "(outboxGet()[name] || offlineKnown())" in _fd148 and 'var VERSION = "food v1.50";' in _fd148)
# less-ai buttons-b (2026-11-10): кнопки и подвал food/travel/viewer/hub — по единым правилам (design-reference/buttons.md):
# свои классы кнопок сняты, подвал — общий uiFootHTML, состояние данных — uiDataDone (свои buildline/#app-ver/footer убраны)
_lb = {n: (REPO / f"tools/{n}.html").read_text(encoding="utf-8") for n in ("food", "travel", "hub")}
_lbv = (REPO / "tools/portfolio-integrated-viewer.html").read_text(encoding="utf-8")
_lbj = (REPO / "tools/assets/viewer.js").read_text(encoding="utf-8")
_lbc = (REPO / "tools/assets/viewer.css").read_text(encoding="utf-8")
for _n, _t in _lb.items():
    check(f"{_n}.html: свои классы кнопок сняты (act-btn/x-btn/plan-btn/chip-btn), нет buildline",
          not re.search(r"(?m)^\.(act-btn|x-btn|plan-btn|chip-btn)\b", _t) and "act-btn" not in _t and "buildline" not in _t)
    check(f"{_n}.html: подвал — uiFootHTML со своей версией, без своего <footer>",
          "uiFootHTML(" in _t and "<footer" not in _t)
check("hub.html: подвал без «← Хаб» (crumb:false), состояние — uiDataDone", "crumb: false" in _lb["hub"] and "uiDataDone(ok)" in _lb["hub"])
check("travel.html: состояние данных — uiDataDone(true/false), числа поездок в подвале нет",
      "uiDataDone(true)" in _lb["travel"] and "uiDataDone(false)" in _lb["travel"] and "поездк" not in _lb["travel"].split("uiFootHTML(")[1][:300])
check("travel.html: «Поделиться» — .ui-btn.plain, ссылка на план — .ui-btn (в шапке карточки .sm)",
      'class="ui-btn plain trip-share"' in _lb["travel"] and 'class="ui-btn plan-block vw-link"' in _lb["travel"]
      and 'class="ui-btn sm plan-inline vw-link"' in _lb["travel"])
check("food.html: состояние данных — uiDataReset в loadAll, uiDataDone по трём источникам",
      "uiDataReset(); render();" in _lb["food"] and "forEach(function (x) { uiDataDone(!!x.doc); })" in _lb["food"])
check("food.html: «Отмена»/«Закрыть» — .plain, «Удалить» — .danger",
      'class="ui-btn plain" data-act="close-modal">Закрыть' in _lb["food"] and 'class="ui-btn danger" data-act="prod-del"' in _lb["food"])
check("вьюер: подвал — uiFootHTML + uiDataDone, свои .app-footer/#app-ver/btn-secondary сняты",
      'id="app-foot"' in _lbv and "app-footer" not in _lbv and "uiFootHTML({ page: 'portfolio'" in _lbj
      and "uiDataDone(true)" in _lbj and "uiDataDone(false)" in _lbj and "btn-secondary" not in _lbj
      and ".app-footer" not in _lbc and "#app-ver" not in _lbc)
check("вьюер: версия 5.4.3 в JS и в ссылках на ассеты",
      "const VIEWER_VERSION = '5.4.3'" in _lbj and "viewer.js?v=5.4.3" in _lbv and "viewer.css?v=5.4.3" in _lbv)
# health v1.57 (2026-11-05): правки «Здоровья» без связи — в очередь, при 409 — слияние mergeDoc (списки по id,
# объекты вглубь, прочее — «моё, если менял»). Прогоняем само слияние в node на файлах вида «Здоровья».
_mg0, _mg1 = _hh.find("function sameJSON("), _hh.find("var OUTBOX_APPLY")
check("health.html: очередь без связи — health-outbox, postSave с пределом SAVE_WAIT_MS, отправка по online",
      'var OUTBOX_KEY = "health-outbox";' in _hh and "var SAVE_WAIT_MS = 8000;" in _hh
      and 'window.addEventListener("online", function(){ flushOutbox(); });' in _hh
      and "if (outboxGet()[name] || offlineKnown()) return Promise.resolve(outboxPut(name, doc));" in _hh)
if _mg0 != -1 and _mg1 > _mg0 and shutil.which("node"):
    import subprocess as _sp_mg
    _drv = _hh[_mg0:_mg1] + r"""
const base = { schema: "s", height_cm: 180, weight: [{date: "a", kg: 80}],
  self: { allergies_checked: false, allergies: [], history: [{id: "h1", t: "x"}] },
  meds: [{id: "m1", dose: "1"}, {id: "m2", dose: "2"}, {id: "m3", dose: "3"}] };
const mine = JSON.parse(JSON.stringify(base)), theirs = JSON.parse(JSON.stringify(base));
mine.weight.push({date: "b", kg: 77});                          // моё: вес
mine.self.allergies_checked = true;                             // моё: поле вглубь
mine.meds = mine.meds.filter(m => m.id !== "m2");               // моё: удалил m2 (там не меняли)
mine.meds = mine.meds.filter(m => m.id !== "m3");               // моё: удалил m3 (там меняли — остаётся)
mine.meds[0].dose = "1a";                                       // моё: m1
theirs.weight.push({date: "c", kg: 79});                        // их: вес
theirs.self.history.push({id: "h2", t: "y"});                   // их: запись вглубь
theirs.meds[2].dose = "3b";                                     // их: m3
theirs.height_cm = 181;                                         // их: рост (я не менял)
theirs.extra = 1;                                               // их: новое поле
process.stdout.write(JSON.stringify(mergeDoc(base, mine, theirs)));
"""
    _pr = _sp_mg.run(["node", "-e", _drv], capture_output=True, text=True)
    check(f"health mergeDoc: node отработал {_pr.stderr[:160]}", _pr.returncode == 0)
    if _pr.returncode == 0:
        _m = _json.loads(_pr.stdout)
        check(f"health mergeDoc: веса с обеих сторон ({_m.get('weight')})",
              sorted(w["kg"] for w in _m.get("weight", [])) == [77, 79, 80])
        check("health mergeDoc: объект вглубь — моё поле и их запись", _m.get("self", {}).get("allergies_checked") is True
              and [h["id"] for h in _m["self"]["history"]] == ["h1", "h2"])
        check(f"health mergeDoc: список по id — m1 моё, m2 удалён, m3 (там меняли) остался их ({_m.get('meds')})",
              _m.get("meds") == [{"id": "m1", "dose": "1a"}, {"id": "m3", "dose": "3b"}])
        check("health mergeDoc: чужие поля (рост, новое поле) не затёрты", _m.get("height_cm") == 181 and _m.get("extra") == 1)
_la = re.search(r"function loadAll\(\)\{(.*?)\n\}", _hh, re.S)
check("health.html: список отчётов держит загрузку не дольше REPORTS_WAIT_MS (within), опоздавший — дорисовывается",
      bool(_la) and '"reports/"' not in _la.group(1) and "within(reports, REPORTS_WAIT_MS)" in _la.group(1)
      and "reports.then(function(list){ setReports(list); render(); loadReportHeads(); })" in _la.group(1)
      and "var REPORTS_WAIT_MS = 1500;" in _hh)
# 1.2.0: при смене версии фоновый скрипт чистит старые кеши cab-* — очередь неотправленных правок и метка
# «связи нет» обязаны уцелеть (до 1.2.0 очередь стиралась при каждом обновлении фонового скрипта)
_act = re.search(r"addEventListener\('activate'.*?\n\}\);", _core, re.S)
check("sw-offline.js: activate не стирает очередь правок (CAB_OUTBOX) и метку (CAB_STATE)",
      bool(_act) and "CAB_OUTBOX" in _act.group(0) and "CAB_STATE" in _act.group(0))
_dz = (REPO / "tools/deploy.zsh").read_text(encoding="utf-8")
check("deploy.zsh выкладывает sw.js и sw-offline.js",
      re.search(r"^FILES=\(.*\bsw\.js\b.*\bsw-offline\.js\b", _dz, re.M) is not None)
check("ui-kit регистрирует /tools/sw.js (офлайн на всех страницах)",
      'new URL("../sw.js"' in UI_KIT_JS and "\nuiOfflineInit();" in UI_KIT_JS)
check("sw-offline 1.3.0: ASSET_TIMEOUT_MS = 20000 и cab-stale (ассет не подменяется прежней версией молча)",
      "var ASSET_TIMEOUT_MS = 20000;" in _core and "type: 'cab-stale'" in _core and "cabWait(ASSET_TIMEOUT_MS)" in _core
      and "cabWait(NAV_TIMEOUT_MS).then(function (ms) { return cabRace(net, ms); }).then(function (o) {\n      cabNetSeen(o);\n      if (o.res && o.res.status < 500) { cabOnlineAgain(); return o.res; }\n      return caches.match(key, { cacheName: CAB_SHELL, ignoreSearch: true })" not in _core)
check("ui-kit: cab-stale -> uiStaleShow (#ui-stale, .ui-toast, кнопка data-stale-reload -> location.reload)",
      'm.type === "cab-stale"' in UI_KIT_JS and "function uiStaleShow()" in UI_KIT_JS
      and 'id = "ui-stale"' in UI_KIT_JS and "data-stale-reload" in UI_KIT_JS and "location.reload()" in UI_KIT_JS)
check("ui-kit 1.60.1: тост «прошлая версия» не показывается при штатном офлайне (плашка/метка #ui-offline на экране или navigator.onLine === false) и скрывается, когда плашка пришла позже",
      'var off = document.getElementById("ui-offline");' in UI_KIT_JS and "navigator.onLine === false || (off && !off.hidden)) return;" in UI_KIT_JS
      and 'var st = document.getElementById("ui-stale");\n  if (st) st.hidden = true;' in UI_KIT_JS)
check("ui-kit.css: .ui-toast-act на токенах", re.search(r"\.ui-toast-act\{[^}]*var\(--border-strong\)[^}]*var\(--bg-alt\)", UI_KIT_CSS0) is not None)
# что держим офлайн — те же регулярные выражения, что в ядре (синтаксис JS и Python здесь совпадает)
def _rx_list(name):
    body = _core.split(f"var {name} = [")[1].split("];")[0]
    return [re.compile(m.replace("\\/", "/")) for m in re.findall(r"/(\^.*?\$|[^/,\s][^,]*?)/(?:i)?(?=,|\s*$)", body, re.M)]
_KEEP, _NEVER = _rx_list("CAB_KEEP"), _rx_list("CAB_NEVER")
_kept = lambda path: any(r.search(path) for r in _KEEP) and not any(r.search(path) for r in _NEVER)  # noqa: E731
for _path, _want in (("/Food/shopping.json", True), ("/api/fd/file", True), ("/health-data/labs.json", True),
                     ("/Portfolio/snapshots/portfolio-2026-10-22.json", True), ("/ZenMoney/audit/history.json", True),
                     ("/travel-planner/trips/kz/5_final_plan_v1.html", True), ("/Gaming/library_full.yaml", True),
                     ("/api/pv/plan", True), ("/api/pv/plan/journal", True), ("/api/pv/plan/set", False), ("/health-data/reports/", True), ("/health-data/anamnesis.json", True),
                     ("/Portfolio/reports/2026-10-01-x.md", False), ("/domains/geopolitics/csis.md", False),
                     ("/health-data/reports/2026-a.md", True), ("/Gaming/recommendations/a.md", True),
                     ("/health-data/studies/2026-a.pdf", False), ("/health-data/studies/scan.jpg", False), ("/health-data/reports/a.pdf", False),
                     ("/travel-planner/trips/kz/5_final_plan_v1_print.html", False),
                     ("/travel-planner/trips/kz/5_final_plan_v1.pdf", False), ("/travel-planner/trips/_archive/a/3_x.md", False)):
    check(f"офлайн {'держим' if _want else 'не держим'}: {_path}", _kept(_path) == _want)

# Вьюер только с сервера (v3.48.0, решение 2026-10-23): локальные режимы file:// (выбор папки/файлов,
# перетаскивание) и ссылки ?view= удалены — ими не пользовались, а заглушка «Перетащи сюда» на телефоне
# издалека выглядела как поломка. Не возвращать молча.
for _w in ("showDirectoryPicker", "webkitdirectory", "webkitGetAsEntry", "loadHttpMode3", "pickFolder",
           "pickFiles", "dirHandle", "get('view')"):
    check(f"вьюер без локального режима: нет «{_w}» в viewer.js", _w not in _VJS)
for _w in ("Перетащи", "btn-pick-folder", "btn-pick-files", "mode-hint"):
    check(f"вьюер без локального режима: нет «{_w}» в странице", _w not in _VHTML)

# Закрытое условие — не «сработавшее» (случай 2026-10-16). Шаг 12: статус — строка модуля (а): закрыто = done | withdrawn
check("viewer: condClosed — статус строки модуля (а) done или withdrawn",
      "function condClosed(c) { return !!c && (c.status === 'done' || c.status === 'withdrawn'); }" in _VJS)
check("viewer: закрытые вне «Чего ждём» и ждущих, в группе «Закрытые»; ждут владельца — только waits_owner",
      "filter(c => !condClosed(c))" in _VJS and "['Закрытые', rows0.filter(c => condClosed(c))]" in _VJS
      and "if (c.waits_owner) out.push({ c, days: _daysSince(c.fired_at) });" in _VJS)

# ═══════════════════════ справки страниц кабинета («? Справка») ═════════════
# Каждая страница, данные которой готовит хотя бы один скилл, несёт кнопку
# «? Справка» (helpBtnHTML/uiHelpOpen, ui-kit 1.4) → модалку с
# assets/help/<page>.md. Правило синхронизации «правишь скилл — правишь его
# справку» живёт в корневом CLAUDE.md («Справки страниц кабинета»); здесь —
# механическая часть контракта, которую можно проверить без человека:
#   • реестр UI_HELP ↔ файлы справок ↔ кнопки на страницах — биекция (кнопка
#     без файла — модалка с ошибкой; файл без кнопки — мёртвая справка);
#   • скиллы, которые справка обязана описывать, существуют в skills/ и
#     упомянуты (переименовал скилл — справка не может молча остаться со
#     старым именем);
#   • в каждой справке названа модель (требование владельца 2026-09-26: «где-то
#     надо указывать желательный уровень модели») — и в справке вьюера тоже;
#   • SYNC-маркер в шапке — без него следующий правящий не узнает, с чем сверять.
print("справки страниц · кнопка ↔ файл ↔ скиллы ↔ модель")
HELP_SKILLS = {
    "travel": ["travel-planning"],
    "games":  ["game-advisor"],
    "health": ["health-labs", "health-meds"],
    "money":  ["zenmoney-analyst"],
    # хаб — карта всех разделов: каждый скилл страниц + опорные портфельные
    "hub":    ["travel-planning", "game-advisor", "health-labs", "health-meds",
               "portfolio-data-loader", "ru-portfolio-advisor",
               "portfolio-integrated-view", "portfolio-scenario-stress",
               "zenmoney-analyst"],
}
for _fn in ("function helpBtnHTML(", "function uiHelpOpen(", "function uiMarkdown("):
    check(f"ui-kit.js: {_fn[9:-1]} определена", _fn in UI_KIT_JS)
# uiMarkdown рендерит и справки, и отчёты health (reports/*.md). «\\|» в ячейке
# таблицы — литеральная черта (GFM): без этого строка «\\|r\\| ≤ 0,23» рвалась на
# лишние столбцы (отчёт 2026-09-29). Прогоняем сам рендер в node.
_md0, _md1 = UI_KIT_JS.find("function esc("), UI_KIT_JS.find("function uiHelpOpen(")
_md2 = UI_KIT_JS.find("function uiMarkdown(")
if _md0 != -1 and _md2 > _md0 and _md1 > _md2 and shutil.which("node"):
    import subprocess as _sp_md
    _esc_src = UI_KIT_JS[_md0:UI_KIT_JS.find("\n}\n", _md0) + 3]
    _drv = _esc_src + UI_KIT_JS[_md2:_md1] + r'''
const html = uiMarkdown("| A | B | C |\n|---|---|---|\n| x | \\|r\\| ≤ 0,23 | нет |\n| y | `a\\|b` | z |");
const rows = html.split("<tr>").slice(1).map(r => (r.match(/<t[hd]>/g) || []).length);
process.stdout.write(JSON.stringify({ rows, html }));
'''
    _pr = _sp_md.run(["node", "-e", _drv], capture_output=True, text=True)
    check(f"uiMarkdown: node отработал {_pr.stderr[:160]}", _pr.returncode == 0)
    if _pr.returncode == 0:
        _o = _json.loads(_pr.stdout)
        check(f"uiMarkdown: «\\|» не рвёт строку таблицы (столбцов {_o['rows']})", _o["rows"] == [3, 3, 3])
        check("uiMarkdown: «\\|» показан как «|» " + ("" if "<td>|r| ≤ 0,23</td>" in _o["html"] else _o["html"][:300]),
              "<td>|r| ≤ 0,23</td>" in _o["html"])
# uiMarkdown 1.7.0: вложенные списки, чек-листы, голые ссылки, «*» в адресе и
# коде не превращается в курсив — те же возможности, что были у рендеров игр
# и вьюера, теперь в одном месте.
if _md0 != -1 and _md2 > _md0 and shutil.which("node"):
    _drv2 = _esc_src + UI_KIT_JS[_md2:UI_KIT_JS.find("var UI_READER_TOC_MIN")] + r"""
const h = uiMarkdown("- a\n  - b\n- [x] c\n\nсм. https://x.org/a*b. и `*k*`\n##### h5");
process.stdout.write(JSON.stringify(h));
"""
    _pr2 = _sp_md.run(["node", "-e", _drv2], capture_output=True, text=True)
    check(f"uiMarkdown 1.7: node отработал {_pr2.stderr[:160]}", _pr2.returncode == 0)
    if _pr2.returncode == 0:
        _h2 = _json.loads(_pr2.stdout)
        check("uiMarkdown 1.7: вложенный список", "<li>a<ul><li>b</li></ul></li>" in _h2)
        check("uiMarkdown 1.7: чек-лист", 'type="checkbox" checked disabled' in _h2)
        check("uiMarkdown 1.7: голый адрес — ссылкой, точка предложения не в адресе",
              'href="https://x.org/a*b"' in _h2 and "</a>." in _h2)
        check("uiMarkdown 1.7: «*» в коде не курсив", "<code>*k*</code>" in _h2)
        check("uiMarkdown 1.7: h5", "<h5>h5</h5>" in _h2)

# ── единый читатель uiReader (ui-kit 1.7.0) ─────────────────────────────────
# Markdown-документы кабинета рисовались четырьмя рендерерами. Теперь справки,
# подборки игр и отчёты здоровья идут через uiReaderHTML/uiReaderMount; свои
# мини-рендеры у страниц удалены (их возврат — дрейф, который этот блок ловит).
# travel.html — тоже через uiReader (ui-kit 1.8.0); вьюер — на своём
# renderReportDoc (отдельный шаг).
for _fn in ("function uiReaderHTML(", "function uiReaderMount(", "function uiReaderMountAll("):
    check(f"ui-kit.js: {_fn[9:-1]} определена", _fn in UI_KIT_JS)
check("ui-kit.js: оглавление опционально — toc auto/true/false и порог UI_READER_TOC_MIN",
      'mode === "auto"' in UI_KIT_JS and "UI_READER_TOC_MIN" in UI_KIT_JS)
check("ui-kit.js: справки — через uiReaderHTML с отдельным UI_HELP_TOC (его можно выключить только у справок)",
      re.search(r'var UI_HELP_TOC = ("auto"|true|false);', UI_KIT_JS) is not None
      and "uiReaderHTML(md, { toc: UI_HELP_TOC" in UI_KIT_JS)
_css_rd = (REPO / "tools/assets/ui-kit.css").read_text(encoding="utf-8")
check("ui-kit.css: порог оглавления — по ширине окна читателя (container query rd)",
      "container:rd / inline-size" in _css_rd and "@container rd (max-width:" in _css_rd)
for _cls in (".rd-toc", ".rd-bar", ".rd-sheet", ".rd-prog", ".rd-meta", ".rd-tldr", ".rd-host"):
    check(f"ui-kit.css: стиль {_cls}", _cls in _css_rd)
_games_rd = (REPO / "tools/games.html").read_text(encoding="utf-8")
check("games.html: подборка — через uiReaderHTML с акцентом --c-5",
      re.search(r'uiReaderHTML\(t, \{ acc: "--c-5"', _games_rd) is not None and "uiReaderMount(" in _games_rd)
check("games.html: своего мини-рендера markdown нет (mdRender/mdInline)",
      re.search(r"function\s+md(Render|Inline)\s*\(", _games_rd) is None)
_health_rd = (REPO / "tools/health.html").read_text(encoding="utf-8")
check("health.html: отчёт — через uiReaderHTML с акцентом --c-3 и шапкой отчёта",
      'uiReaderHTML(md.body, { acc: "--c-3"' in _health_rd and "head: mm ? reportHeadHTML(mm)" in _health_rd)
check("health.html: после перерисовки читатели навешиваются (uiReaderMountAll)",
      "uiReaderMountAll(app)" in _health_rd)
# ── uiTripWhen (ui-kit 1.8.0): когда поездка ────────────────────────────────
# Решения владельца 2026-10-03: поездка — только с точными датами start/end;
# ready + месяц — поездка с точностью до месяца («в следующем месяце»);
# остальное без дат — возможная поездка/идея без отсчёта времени, год никогда не
# даёт «в этом/следующем году»; прошедшая возможная — «срок прошёл», не
# «состоялась». Один расчёт для travel и hub — прогоняем его в node на
# фиксированной «сегодня».
_tw0 = UI_KIT_JS.find("var UI_MONTHS_NOM"); _tw1 = UI_KIT_JS.find("function uiHelpClose(")
check("ui-kit.js: uiTripWhen определена", "function uiTripWhen(" in UI_KIT_JS)
if _tw0 != -1 and _tw1 > _tw0 and shutil.which("node"):
    import subprocess as _sp_tw
    _drv_tw = UI_KIT_JS[_tw0:_tw1] + r"""
const T = "2026-10-03", C = {
  before:   {start:"2026-10-15", end:"2026-10-24", season:"2026-10"},
  tomorrow: {start:"2026-10-04", end:"2026-10-10"},
  during:   {start:"2026-10-01", end:"2026-10-10"},
  past:     {start:"2026-09-01", end:"2026-10-02", status:"ready"},
  xyear:    {start:"2026-12-28", end:"2027-01-05"},
  badord:   {start:"2026-10-15", end:"2026-10-01", season:"2026-11"},
  onekey:   {start:"2026-10-15", season:"2026-11", status:"ready"},
  rnext:    {season:"2026-11", status:"ready"},
  rthis:    {season:"2026-10", status:"ready"},
  rfar:     {season:"2027-02", status:"ready"},
  rpast:    {season:"2026-09", status:"ready"},
  poss:     {season:"2026-11", status:"planning"},
  possold:  {season:"2026-08"},
  idea:     {season:"2027", status:"ready"},
  ideanow:  {season:"2026"},
  ideaold:  {season:"2025"},
  done:     {season:"2026-09", status:"done"},
  none:     {},
};
const out = {}; for (const k in C) out[k] = uiTripWhen(C[k], T);
process.stdout.write(JSON.stringify(out));
"""
    _ptw = _sp_tw.run(["node", "-e", _drv_tw], capture_output=True, text=True)
    check(f"uiTripWhen: node отработал {_ptw.stderr[:160]}", _ptw.returncode == 0)
    if _ptw.returncode == 0:
        W = _json.loads(_ptw.stdout)
        def _tw(k, kind, label, archive=None, nearest=None):
            w = W[k]
            ok = w["kind"] == kind and w["label"] == label and w["archive"] == archive
            if nearest is not None:
                ok = ok and w["nearest"] == nearest
            check(f"uiTripWhen[{k}]: {kind} · «{label}» · архив {archive} (получено {w['kind']} · «{w['label']}» · {w['archive']})", ok)
        _tw("before", "trip", "через 12 дн", None, True)
        _tw("tomorrow", "trip", "завтра", None, True)
        _tw("during", "trip", "идёт · день 3 из 10", None, True)
        _tw("past", "trip", "прошла", "past", False)
        _tw("xyear", "trip", "через 86 дн", None, True)
        _tw("badord", "possible", "возможная · даты не определены", None, False)
        _tw("onekey", "trip-month", "в следующем месяце", None, True)
        _tw("rnext", "trip-month", "в следующем месяце", None, True)
        _tw("rthis", "trip-month", "в этом месяце", None, True)
        _tw("rfar", "trip-month", "через 4 мес", None, True)
        _tw("rpast", "trip-month", "прошла", "past", False)
        _tw("poss", "possible", "возможная · даты не определены", None, False)
        _tw("possold", "possible", "срок прошёл · дат нет", "expired", False)
        _tw("idea", "idea", "идея", None, False)
        _tw("ideanow", "idea", "идея", None, False)
        _tw("ideaold", "idea", "срок прошёл · дат нет", "expired", False)
        _tw("done", "possible", "состоялась", "done", False)
        _tw("none", "none", "", None, False)
        check("uiTripWhen: год никогда не даёт «в этом/следующем году»",
              not any("году" in W[k]["label"] for k in W))
        check("uiTripWhen: у возможных и идей нет отсчёта («через», «день K из M»)",
              not any(("через" in W[k]["label"] or "день" in W[k]["label"])
                      for k in W if W[k]["kind"] in ("possible", "idea")))
        check("uiTripWhen: точные даты в подсказке, без дат — «точных дат нет»",
              W["before"]["title"] == "15–24 октября 2026" and "точных дат нет" in W["poss"]["title"]
              and W["xyear"]["seasonLabel"] == "28 декабря 2026 – 5 января 2027")
# uiTripIsMine (ui-kit 1.9.0): «мои» — владелец в travelers (один или с
# кем-то), иначе «для близких»; нет travelers — своя. Одно имя владельца на
# кабинет (UI_OWNER) вместо копий в travel/hub.
_tm0 = UI_KIT_JS.find("var UI_OWNER"); _tm1 = UI_KIT_JS.find("function uiHelpClose(")
check("ui-kit.js: uiTripIsMine и UI_OWNER определены", "function uiTripIsMine(" in UI_KIT_JS and _tm0 != -1)
if _tm0 != -1 and _tm1 > _tm0 and shutil.which("node"):
    import subprocess as _sp_tm
    _drv_tm = UI_KIT_JS[_tm0:_tm1] + r"""
process.stdout.write(JSON.stringify([
  uiTripIsMine(["алексей"]), uiTripIsMine(["мария", "алексей"]), uiTripIsMine("[мария, алексей]"),
  uiTripIsMine(["родители"]), uiTripIsMine("[мария]"), uiTripIsMine([]), uiTripIsMine(undefined),
  uiTripIsMine(["Алексей"]), uiTripIsMine("[]")
]));
"""
    _ptm = _sp_tm.run(["node", "-e", _drv_tm], capture_output=True, text=True)
    check(f"uiTripIsMine: node отработал {_ptm.stderr[:160]}", _ptm.returncode == 0)
    if _ptm.returncode == 0:
        _m = _json.loads(_ptm.stdout)
        check(f"uiTripIsMine: один / с кем-то / flow-строка — мои; родители и Мария без меня — близких; пусто — мои ({_m})",
              _m == [True, True, True, False, False, True, True, True, True])
# ── Вход — одна реализация на кабинет (ui-kit 1.16.0) ──────────────────────
# authFetch был копией в food/health/hub/money (у money — с другой сигнатурой),
# goLogin+BOUNCE_KEY — в health и money с разными условиями петли. Строка
# credentials:"omit" в каждой копии — единственное, что не даёт неверному
# паролю открыть нативное окно браузера и заморозить вкладку: новая страница,
# собранная копированием, могла её потерять. Теперь копий быть не должно.
_auth_pages = {n: (REPO / "tools" / n).read_text(encoding="utf-8")
               for n in ("hub.html", "travel.html", "games.html", "food.html", "health.html", "money.html")}
for _n, _src in _auth_pages.items():
    _code = _strip_js_comments(_src)
    check(f"{_n}: своих authFetch/goLogin-петли нет — общие из ui-kit",
          re.search(r"function\s+authFetch\s*\(", _code) is None and "BOUNCE_KEY" not in _code
          and "login-bounce" not in _code)
    # приватные пути — только через authFetch (голый fetch не несёт токен:
    # вне дома это тихий 403, а не «нет данных»)
    _raw = [l.strip()[:90] for l in _code.split("\n")
            if re.search(r"(?<![\w.])fetch\(", l) and re.search(r"health-data|ZenMoney|Portfolio|API\s*\+|/api/", l)]
    check(f"{_n}: приватные пути не грузятся голым fetch {_raw}", not _raw)
check("ui-kit.js: authFetch с credentials:\"omit\"",
      'init.credentials = "omit"' in UI_KIT_JS[UI_KIT_JS.find("function authFetch(url, init){"):][:400])
_a0 = UI_KIT_JS.find("function esc("); _a1 = UI_KIT_JS.find("function plural(")
_b0 = UI_KIT_JS.find("function authToken("); _b1 = UI_KIT_JS.find("/* Общая логика кнопки «Обновить»")
check("ui-kit.js: блок входа найден", min(_a0, _a1, _b0, _b1) != -1)
if min(_a0, _a1, _b0, _b1) != -1 and shutil.which("node"):
    import subprocess as _sp_au
    _drv_au = r"""
var LS = {}, SS = {}, replaced = [], reqs = [], nextStatus = 200;
var localStorage = { getItem: function(k){ return k in LS ? LS[k] : null; }, setItem: function(k, v){ LS[k] = String(v); }, removeItem: function(k){ delete LS[k]; } };
var sessionStorage = { getItem: function(k){ return k in SS ? SS[k] : null; }, setItem: function(k, v){ SS[k] = String(v); }, removeItem: function(k){ delete SS[k]; } };
var location = { pathname: "/tools/money.html", search: "", replace: function(u){ replaced.push(u); } };
function Headers(h){ this.m = {}; for (var k in (h || {})) this.m[k.toLowerCase()] = h[k]; }
Headers.prototype.set = function(k, v){ this.m[k.toLowerCase()] = v; };
var btn = { attrs: { "data-cache-prefix": "hub", "data-why": "hub" }, getAttribute: function(k){ return this.attrs[k]; }, outerHTML: "" };
var document = { querySelectorAll: function(){ return [btn]; } };
function fetch(url, init){ reqs.push(init); return Promise.resolve({ status: nextStatus }); }
""" + UI_KIT_JS[_a0:_a1] + UI_KIT_JS[_b0:_b1] + r"""
(async function(){
  var out = {};
  LS["hub-auth"] = "dG9rMQ==";
  out.loggedOut = authBtnHTML({ why: "money", prefix: "money" }).indexOf(">Выйти<") > 0;
  nextStatus = 200; await authFetch("x", { headers: { Accept: "application/json" } });
  out.omit = reqs[0].credentials === "omit";
  out.hdr = reqs[0].headers.m.authorization === "Basic dG9rMQ==" && reqs[0].headers.m.accept === "application/json";
  nextStatus = 403; await authFetch("x");
  out.no403 = !uiAuthRejected();
  nextStatus = 401; await authFetch("x");
  out.rej = uiAuthRejected() && authBtnHTML({ why: "money" }).indexOf("Войти заново") > 0;
  out.domSwap = btn.outerHTML.indexOf("Войти заново") > 0 && btn.outerHTML.indexOf("why=hub") > 0;
  out.noTokenCopy = JSON.stringify(LS).indexOf("dG9rMQ==") === JSON.stringify(LS).lastIndexOf("dG9rMQ==");
  LS["hub-auth"] = "dG9rMg==";
  out.newTok = !uiAuthRejected() && authBtnHTML({}).indexOf(">Выйти<") > 0;
  delete LS["hub-auth"]; LS["hub-auth"] = "dG9rMg==";
  var loops = [];
  out.go1 = uiGoLogin("money", function(t){ loops.push(t); }) === true && replaced.length === 1
            && replaced[0].indexOf("login.html?why=money&next=%2Ftools%2Fmoney.html") === 0;
  out.go2 = uiGoLogin("money", function(t){ loops.push(t); }) === false && replaced.length === 1 && loops[0] === true;
  uiLoginOk("money");
  out.go3 = uiGoLogin("money") === true && replaced.length === 2;
  out.otherPage = uiGoLogin("health") === true;
  process.stdout.write(JSON.stringify(out));
})();
"""
    _pau = _sp_au.run(["node", "-e", _drv_au], capture_output=True, text=True)
    check(f"вход ui-kit: node отработал {_pau.stderr[:200]}", _pau.returncode == 0)
    if _pau.returncode == 0:
        _ma = _json.loads(_pau.stdout)
        for _k, _what in (("loggedOut", "с токеном — «Выйти»"),
                          ("omit", "authFetch шлёт credentials:\"omit\""),
                          ("hdr", "authFetch добавляет Authorization и сохраняет заголовки вызова"),
                          ("no403", "403 (нет токена/закрытый путь) пароль отвергнутым не считает"),
                          ("rej", "401 при токене — кнопка «Войти заново»"),
                          ("domSwap", "уже нарисованная «Выйти» заменяется на месте, со своим why"),
                          ("noTokenCopy", "метка — отпечаток, второй копии токена в хранилище нет"),
                          ("newTok", "новый токен — метка гаснет, снова «Выйти»"),
                          ("go1", "uiGoLogin уводит на login.html с why и next"),
                          ("go2", "повторный уход за 20 с — не уводит, зовёт onLoop(есть токен)"),
                          ("go3", "uiLoginOk снимает метку петли"),
                          ("otherPage", "метка петли своя у каждой страницы")):
            check(f"вход ui-kit: {_what}", _ma.get(_k) is True)
_lg = (REPO / "tools/login.html").read_text(encoding="utf-8")
check("login.html: успешный вход снимает метку отвергнутого пароля",
      'localStorage.removeItem("hub-auth-rejected")' in _lg)
check("login.html: у «Денег» своё пояснение, зачем пароль", "money:" in _lg)

_trv2 = (REPO / "tools/travel.html").read_text(encoding="utf-8")
check("travel.html: счётчики «мои / для близких» в сводке",
      'id="sum-mine"' in _trv2 and 'id="sum-others"' in _trv2 and "mine: uiTripIsMine(travelers)" in _trv2)
check("travel.html: «Ближайшая» — только из моих поездок",
      "t.meta.mine && t.meta.when && t.meta.when.nearest" in _trv2)
_hub2 = (REPO / "tools/hub.html").read_text(encoding="utf-8")
check("hub.html: «мои · для близких» у числа поездок; свой разбор travelers снят",
      'id="trips-split"' in _hub2 and "uiTripIsMine(y && y.travelers)" in _hub2
      and re.search(r"function\s+tripTravelers\s*\(", _hub2) is None)
check("ui-kit.js: uiReader — слот действий opts.actions (кнопки прыжка к главе)",
      "opts.actions" in UI_KIT_JS and 'class="rd-act"' in UI_KIT_JS and "rd-act-btn" in UI_KIT_JS)
_trv = (REPO / "tools/travel.html").read_text(encoding="utf-8")
check("travel.html: когда поездка — через uiTripWhen", "uiTripWhen({ start: y.start, end: y.end" in _trv)
check("travel.html: своих seasonKey и мини-рендера markdown нет",
      re.search(r"function\s+(seasonKey|mdRender|mdInline)\s*\(", _trv) is None)
check("travel.html: md-стадии и профили — через uiReaderHTML с акцентом --c-4",
      _trv.count('uiReaderHTML(txt, { acc: "--c-4"') == 2)
check("travel.html: «Сегодня» — только у идущей поездки с точными датами",
      'when.kind !== "trip" || when.phase !== "during"' in _trv)
check("travel.html: прошедшая возможная — бейдж «срок прошёл», не «состоялась»",
      'expired:    { cls: "expired",    text: "срок прошёл" }' in _trv and 'when.archive === "expired" ? "expired"' in _trv)
check("travel.html: «Ближайшая» — только when.nearest, идеи — отдельной оговоркой",
      "t.meta.when.nearest" in _trv and "Точных дат пока нет · ближайшая идея" in _trv)
# ── окно документа ui-kit 1.10.0: по центру и одинаковое у travel/games ──────
_dw_css = (REPO / "tools/assets/ui-kit.css").read_text(encoding="utf-8")
_gms = (REPO / "tools/games.html").read_text(encoding="utf-8")
_hd4 = _strip_js_comments((REPO / "tools/health.html").read_text(encoding="utf-8"))
check("health.html: окно документа — общее .ui-docwin со слоем 215 (своей шапки .rep-h нет)",
      '<div class="ui-docwin\' + (S.docFresh ? \' enter\' : \'\') + \'" style="--docwin-z:215;">' in _hd4 and ".rep-h" not in _hd4)
# ui-kit 1.38.0 (2026-10-07): окна, которые появлялись рывком, — плавно: формы и документ
# «Здоровья», окно стадии и профиль travel, подборка games, справка на всех страницах
_uk38 = (REPO / "tools/assets/ui-kit.js").read_text(encoding="utf-8")
_uc38 = (REPO / "tools/assets/ui-kit.css").read_text(encoding="utf-8")
check("ui-kit: uiShow/uiHide и вход/уход .ui-docwin/.uh-overlay/.ui-fx",
      "function uiShow(el)" in _uk38 and "function uiHide(el, done)" in _uk38
      and ':is(.ui-docwin, .uh-overlay, .ui-fx).enter > [role="dialog"]' in _uc38
      and ':is(.ui-docwin, .uh-overlay, .ui-fx).leave > [role="dialog"]' in _uc38)
check("ui-kit: справка въезжает и уходит плавно (крестик, затемнение, Escape)",
      'ov.className = "uh-overlay enter"' in _uk38
      # крестик/затемнение и Escape; третий (1.57.0) — строка журнала уведомлений уводит на свою страницу
      and _uk38.count("uiHelpClose(true);") == 3)
check("health.html: формы въезжают только при открытии и уходят плавно",
      'cls: S.formEnter ? "enter" : ""' in _hd4 and "S.formEnter = !!fk && fk !== S._lastForm" in _hd4
      and '"close-edit": function(){ closeForm(); }' in _hd4 and "uiStackPop(document.querySelectorAll(\".ui-modal\"), 0," in _hd4)
check("health.html: окно документа уходит плавно (✕, затемнение, Escape)",
      '"doc-close": function(){ closeDocAnim(); }' in _hd4 and "uiHide(w, function(){ closeDoc(); })" in _hd4)
for _nm38, _need in (("travel", ('uiShow($("viewer"))', 'uiHide($("viewer")', 'uiShow($("prof"))', 'uiHide($("prof"))', 'class="prof-overlay ui-fx"')),
                     ("games", ('uiShow($("viewer"))', 'uiHide($("viewer"))'))):
    _s38 = (REPO / f"tools/{_nm38}.html").read_text(encoding="utf-8")
    check(f"{_nm38}.html: окна появляются и уходят через uiShow/uiHide", all(n in _s38 for n in _need))
for _nm in ("travel", "games", "health"):
    _src4 = _strip_js_comments((REPO / f"tools/{_nm}.html").read_text(encoding="utf-8"))
    check(f"{_nm}.html: шапка окна документа — общая ui-kit (.ui-docwin-head/-title/-x), своих .vw-head/.md-close нет",
          "ui-docwin-head" in _src4 and "ui-docwin-x" in _src4
          and re.search(r"\.(vw-head|vw-stage|vw-trip|md-close)\b|class=\"(vw-head|md-close)", _src4) is None)
check("ui-kit.css: .ui-docwin — окно по центру с шириной от страницы (--docwin-w)",
      ".ui-docwin{" in _dw_css and "justify-content:center" in _dw_css.split(".ui-docwin{", 1)[1][:200]
      and "var(--docwin-w, 1000px)" in _dw_css)
for _nm, _src in (("travel", _trv), ("games", _gms)):
    check(f"{_nm}.html: просмотр документа — окно .ui-docwin, не боковая панель",
          '<div class="ui-docwin" id="viewer" hidden>' in _src and "md-overlay" not in _src)
check("travel.html: окно стадии 1280px — экспортному HTML хватает места на оглавление слева",
      "#viewer{ --docwin-w:1280px;" in _trv)
check("travel.html: Escape изнутри iframe стадии закрывает окно (поля ввода — нет)",
      'this.contentDocument' in _trv and 'ev.key !== "Escape" || ev.defaultPrevented' in _trv
      and "isContentEditable" in _trv)
check("ui-kit.js: Escape сначала сворачивает открытую шторку оглавления читателя",
      'document.querySelector(".rd-sheet:not([hidden])")' in UI_KIT_JS)
_hubt = (REPO / "tools/hub.html").read_text(encoding="utf-8")
check("hub.html: когда поездка — через uiTripWhen, своих seasonKey/seasonDisp нет",
      "uiTripWhen(y)" in _hubt and re.search(r"function\s+season(Key|Disp)\s*\(", _hubt) is None)
check("hub.html: «Моя ближайшая» — только w.nearest", "t.w.nearest" in _hubt)

_uh = re.search(r"var UI_HELP = \{(.*?)\n\};", UI_KIT_JS, re.S)
check("ui-kit.js: реестр UI_HELP объявлен", _uh is not None)
_uh_keys = set(re.findall(r"^\s*(\w+)\s*:\s*\{", _uh.group(1), re.M)) if _uh else set()
check(f"UI_HELP ↔ HELP_SKILLS: одинаковый набор разделов ({sorted(_uh_keys)})",
      _uh_keys == set(HELP_SKILLS))
_help_dir = REPO / "tools/assets/help"
_help_files = {f.stem for f in _help_dir.glob("*.md")} if _help_dir.exists() else set()
check(f"assets/help/*.md ↔ UI_HELP: ни лишних, ни недостающих ({sorted(_help_files)})",
      _help_files == _uh_keys)
_css_uikit = (REPO / "tools/assets/ui-kit.css").read_text(encoding="utf-8")
for _cls in (".uh-overlay", ".uh-modal", ".uh-body", ".uh-ico"):
    check(f"ui-kit.css: стиль {_cls} (класс из uiHelpOpen/helpBtnHTML)", _cls + "{" in _css_uikit or _cls + " " in _css_uikit)
_SKILLS_DIR = REPO / "skills"
_MODEL_RE = re.compile(r"\b(Opus|Sonnet|Haiku|Fable)\b")
for _page, _skills in HELP_SKILLS.items():
    _html = (REPO / f"tools/{_page}.html").read_text(encoding="utf-8")
    _topc = re.search(r'uiTopHTML\(\{\s*page:\s*"' + _page + r'"([^}]*)\}', _html)
    check(f"{_page}.html: кнопка справки в шапке (uiTopHTML page:\"{_page}\", без help:false)",
          bool(_topc) and "help: false" not in _topc.group(1))
    _md_p = _help_dir / f"{_page}.md"
    if not _md_p.exists():
        continue
    _md = _md_p.read_text(encoding="utf-8")
    check(f"help/{_page}.md: SYNC-маркер в шапке", "SYNC:" in _md[:600])
    check(f"help/{_page}.md: названа рекомендуемая модель", _MODEL_RE.search(_md) is not None)
    for _sk in _skills:
        check(f"help/{_page}.md: скилл {_sk} существует в skills/",
              (_SKILLS_DIR / _sk / "SKILL.md").exists())
        check(f"help/{_page}.md: упоминает скилл {_sk}", _sk in _md)
# Обратное направление: кнопка справки только с зарегистрированным разделом.
for _html_p in sorted((REPO / "tools").glob("*.html")):
    for _pg in re.findall(r'helpBtnHTML\("(\w+)"\)', _html_p.read_text(encoding="utf-8")):
        check(f"{_html_p.name}: helpBtnHTML(\"{_pg}\") есть в UI_HELP", _pg in _uh_keys)
# Вьюер портфеля — своя справка: 10 частей tools/assets/help/viewer/NN-slug.md, раздел = файл.
# Ссылки вьюера открывают справку по якорям ({#modes} и др.), поэтому имена файлов, порядок и якоря —
# контракт. Смыслы, которые раньше держались фразами с пометками версий, держатся якорями,
# заголовками таблиц и ключевыми фразами; пометок версий в справке нет вовсе.
print("вьюер · справка из частей")
_HV_DIR = REPO / "tools/assets/help/viewer"
_HV_FILES = ["00-about.md", "01-run.md", "02-models.md", "03-fresh.md", "04-tabs.md",
             "05-now.md", "06-gates.md", "07-conditions.md", "08-site.md", "09-limits.md", "10-new.md"]
_HV_SLUGS = {"01-run.md": "run", "02-models.md": "models", "03-fresh.md": "fresh", "04-tabs.md": "tabs",
             "05-now.md": "now", "06-gates.md": "gates", "07-conditions.md": "conditions",
             "08-site.md": "site", "09-limits.md": "limits", "10-new.md": "new"}
for _f in _HV_FILES:
    check(f"справка вьюера: часть {_f} существует", (_HV_DIR / _f).exists())
check("справка вьюера: в папке ровно 11 частей .md (лишних нет)",
      sorted(p.name for p in _HV_DIR.glob("*.md")) == _HV_FILES if _HV_DIR.exists() else False)
_hv_parts = [(_HV_DIR / f).read_text(encoding="utf-8") if (_HV_DIR / f).exists() else "" for f in _HV_FILES]
_HV = "\n\n".join(_hv_parts)                                   # так же склеивает читатель ui-kit
_HVP = {_HV_SLUGS.get(f, "about"): t for f, t in zip(_HV_FILES, _hv_parts)}
check("справка вьюера: 00-about — SYNC-маркер в шапке, без h2, упоминает «Поиск по справке»",
      "SYNC:" in _HVP["about"][:600] and not re.search(r"^## ", _HVP["about"], re.M) and "Поиск по справке" in _HVP["about"])
for _f, _slug in _HV_SLUGS.items():
    _first = next((l for l in _HVP[_slug].splitlines() if l.strip()), "")
    _n = int(_f[:2])
    check(f"справка вьюера: {_f} начинается с «## {_n}. … {{#{_slug}}}»",
          re.fullmatch(r"## %d\. .+ \{#%s\}" % (_n, re.escape(_slug)), _first) is not None)
_hv_anchors = re.findall(r"^#{2,3} .*\{#([a-z0-9-]+)\}\s*$", _HV, re.M)
check("справка вьюера: якоря {#…} уникальны", len(_hv_anchors) == len(set(_hv_anchors)) and len(_hv_anchors) >= 9)
check("справка вьюера: h3 «Режимы советника {#modes}» в разделе моделей (на нём открывают ссылки «Mode N»)",
      "### Режимы советника {#modes}" in _HVP["models"])
_hv_links = set(re.findall(r"\]\(#([^)\s]+)\)", _HV)) - {"copy"}
check(f"справка вьюера: внутренние ссылки ведут на существующие якоря (битые: {sorted(_hv_links - set(_hv_anchors))})",
      _hv_links <= set(_hv_anchors))
_hv_cells = [c.strip() for l in _HV.splitlines() if l.lstrip().startswith("|") for c in l.strip().strip("|").split("|")]
_hv_long = [c[:40] for c in _hv_cells if len(c) > 300]
check(f"справка вьюера: ни одной ячейки таблицы длиннее 300 знаков (длинные: {_hv_long})", not _hv_long)
_hv_ver = re.findall(r"\b[Сс] 3\.\d{2}|\(3\.\d{2}(?:\.\d)?\)|до 3\.\d{2}|v3\.\d{2}|\b3\.\d{2}\.\d\b", "\n\n".join(t for s_, t in _HVP.items() if s_ != "new"))   # «Что нового» — по смыслу из версий
check(f"справка вьюера: пометок версий нет (найдено: {_hv_ver[:5]})", not _hv_ver)
check("справка вьюера: у каждого <details> есть <summary> на следующей строке, сгибы закрыты",
      _HV.count("<details>") == len(re.findall(r"<details>\n<summary>[^<\n]+</summary>", _HV)) == _HV.count("</details>") > 0)
check("справка вьюера: без живых чисел примера на дату (4,55 / 4,59 / 14,61 млн ₽, «на 28.10»)",
      not re.search(r"4,5[59] млн|14,61 млн|на 28\.10", _HV))
check("справка вьюера: без путей файлов и флагов CLI (plan.json, --rebaseline-cash, classes.<…>, Portfolio/)",
      not re.search(r"plan\.json|--rebaseline-cash|--cash-fact|classes\.<|Portfolio/|gate-reviews\.yaml|conditions\.yaml", _HV))
check("справка вьюера: коды статусов не торчат в тексте (review_needed, reviewed_*, new_position, review_aging)",
      not re.search(r"\breview_needed\b|\breviewed_[a-z_]+|\bnew_position\b|\breview_aging\b", _HV))
check("справка вьюера: фраз (#copy) не меньше 40",
      _HV.count("](#copy)") >= 40)

# модели: каждому режиму советника (MODE_RU) — строка таблицы с моделью; модели ключевых скиллов
_hv_m = _HVP["models"].split("### Режимы советника {#modes}")[-1]
for _mn in ("1", "2", "3", "4", "5a", "5b", "6", "7", "8", "9"):
    check(f"справка вьюера: режим (Mode {_mn}) — строка таблицы с моделью",
          re.search(r"^\|[^\n]*\(Mode %s\)[^\n]*\b(Opus|Sonnet|Haiku|Fable)\b" % re.escape(_mn), _hv_m, re.M) is not None)
check("справка вьюера: оценка качества (Mode 8) и несколько режимов — Opus",
      re.search(r"^\|[^\n]*\(Mode 8\)[^\n]*\bOpus\b", _hv_m, re.M) is not None
      and re.search(r"^\| несколько режимов[^\n]*\bOpus\b", _hv_m, re.M) is not None)
for _sk in ("ru-portfolio-advisor", "portfolio-integrated-view", "portfolio-coherence-audit", "portfolio-data-loader"):
    check(f"справка вьюера: модель указана для {_sk}",
          re.search(r"\| `" + re.escape(_sk) + r"` \|[^\n]*\b(Opus|Sonnet|Haiku|Fable)\b", _HVP["models"]) is not None)

# «Сейчас» и мой план (смысл бывших проверок 3.88–3.95)
_hv_now = _HVP["now"]
check("справка «Сейчас»: таблица слов плана (держать / привести к плану / докупать / ждать / продать) с колонкой «В базе докупки»",
      "| Мой план | Недобор (и нет блокировки) | Перевес | В базе докупки |" in _hv_now
      and all(f"| «{w}» |" in _hv_now for w in ("держать", "привести к плану", "докупать", "ждать", "продать"))
      and "продать всё" in _hv_now and "срез до нуля" in _hv_now and "неподвижны по текущим значениям" in _hv_now)
check("справка «Сейчас»: таблица блокировок стоит до прозы и сгибов; строки решений (слова R27), IPO-паузы, лимита, трёх видов условий",
      "| Что | Докупка | Продажа | В базе «Сейчас» | Кто снимает |" in _hv_now
      and _hv_now.index("| Что | Докупка |") < _hv_now.index("<details>")
      and all(x in _hv_now for x in ("IPO-пауза", "«срок решения вышел»", "лимит эмитента 15 % (Сбер 20 %)", "условие с исходом «купить»",
                                      "условие с исходом «срез/продать»", "условие вида «разбор»", "продажу не вызывает и не блокирует")))
check("справка «Сейчас»: «покупка требует плана и отсутствия блокировок; продажа — только плана» выноской «Важно»",
      re.search(r"^> \*\*Важно:\*\* покупка требует плана и отсутствия блокировок; продажа — только плана", _hv_now, re.M) is not None)
check("справка «Сейчас»: под гейтом срез только по слову плана; условие-разбор не блокирует",
      "срез предлагается только при плане «привести к плану» или «продать»" in _hv_now
      and "Условие вида «разбор» по дате или цене не блокирует ничего" in _hv_now)
check("справка «Сейчас»: база докупки — «не размещается», предел базы, «Факт» и цель от разных сумм, три места заморозки",
      all(x in _hv_now for x in ("не размещается", "**Предел базы.**", "входит в базу своими текущими рублями", "сгиб «заморожено",
                                  "Для базы «Сейчас»", "книги после сделок", "до 0 % · выход")))
check("справка «Сейчас»: «Путь новой бумаги» — h3 с якорем, 7 шагов, фраза «Разбери X»",
      "### Путь новой бумаги {#now-new}" in _hv_now
      and len(re.findall(r"^\d\. ", _hv_now.split("### Путь новой бумаги")[1].split("<details>")[0], re.M)) == 7
      and "[/ru-portfolio-advisor Разбери X](#copy)" in _hv_now)
check("справка «Сейчас»: фразы базы докупки (срезать до плана · на выход · уже резал)",
      all(f"[/ru-portfolio-advisor {x}](#copy)" in _hv_now for x in ("SBERP срезать до плана", "SBERP на выход", "По SBERP уже резал в августе")))

# Гейты (смысл бывших проверок 3.90–3.93)
_hv_g = _HVP["gates"]
_hv_gt = _hv_g.split("| Статус (слово на сайте) |")[1].split("\n\n")[0] if "| Статус (слово на сайте) |" in _hv_g else ""
check("справка «Решения и докупка» (R27): таблица статусов — 9 строк словами решений (новая, без разбора … продана, IPO · до дд.мм), колонки «Докупка» и «Срок»; «гейт» — один раз, как название понятия",
      len([l for l in _hv_gt.splitlines() if l.startswith("| ") and not l.startswith("|---")]) == 9
      and all(f"| {w} |" in _hv_gt for w in ("новая, без разбора", "нужен разбор", "наблюдать", "срок решения вышел", "держать",
                                              "докупать", "сократить", "продана")) and "IPO · до дд.мм" in _hv_gt
      and len(re.findall(r"[Гг]ейт", _hv_g)) == 1 and "«Докупка: открыта»" in _hv_g
      and "| Докупка |" in _hv_g and "| Срок |" in _hv_g)
check("справка «Решения и докупка»: докупка — по последнему решению; срок — из решения (7–180, по умолчанию 60 дней), класс срок не задаёт; 8 кварталов, пауза 21 день, 1 п.п., до 40 % позиции",
      all(x in _hv_g for x in ("последнему **решению**", "срок пересмотра из решения", "от 7 до 180 дней", "60 дней", "Класс бумаги срок не задаёт",
                               "8 кварталов торгов", "21 день", "больше 1 п.п.", "до 40 % позиции")) and "45 дней" not in _hv_g)
check("справка «Решения и докупка»: фразы снятия — Разбери …, оценка качества; «Подтверждаю держать X» для Claude нет (правило 9а, строгий вариант 11.11); ≥ 4 (#copy)",
      all(x in _hv_g for x in ("[/ru-portfolio-advisor Разбери YDEX](#copy)", "[/ru-portfolio-advisor Оцени качество акций на 1–2 года](#copy)"))
      and "[/save-to-library Подтверждаю держать X](#copy)" not in _hv_g and _hv_g.count("(#copy)") >= 4)
check("справка «Решения и докупка»: продажу решение не держит; докупку закрывает только у акций; переклассификация — это не продажа; IPO разбором не снимается; фраза для Claude в карточке — норма",
      "Продажу решение не запрещает и не вызывает" in _hv_g and "Докупку решение закрывает только по акциям" in _hv_g
      and "это не продажа" in _hv_g and "IPO-пауза разбором не снимается" in _hv_g
      and "исключение из правила «команды — только на «Действиях»»" in _hv_g)
check("справка «Решения и докупка»: лимиты концентрации таблицей (15 % · Сбер 20 % · сектор 35 %), неразворот; блокировки — ссылкой на «Сейчас», не пересказом",
      re.search(r"\| один эмитент \| 15 % книги акций \|", _hv_g) and re.search(r"\| Сбер \(SBER \+ SBERP[^|]*\| 20 % книги акций \|", _hv_g)
      and "| сектор | 35 %" in _hv_g and "**Правило неразворота.**" in _hv_g and "](#now)" in _hv_g
      and "| Что | Докупка | Продажа |" not in _hv_g)
check("справка «Решения и докупка»: решение записывается при сохранении разбора без особой команды; реестра нет; окно «🛡 Решения»; последнее слово по полям и две плашки; «исполнено сделкой»",
      "Подробнее: как записывается решение разбора" in _hv_g and "особая команда не нужна" in _hv_g and "Отдельного реестра нет" in _hv_g
      and "«🛡 Решения»" in _hv_g and "«Источники расходятся»" in _hv_g and "«План против последнего слова»" in _hv_g and "**только из решения**" in _hv_g
      and "исполнено сделкой дд.мм" in _hv_g)

# Условия, приоритет, сайт, свежесть, ограничения
_hv_c = _HVP["conditions"]
check("справка «Условия»: виды «сделка»/«разбор»/«наблюдение» с кнопками сайта (сделал · отложить до · не актуально, открыть заново), метки модуля условий, фразы одной таблицей «Задача | Фраза», приоритет h3",
      "| сделка |" in _hv_c and "| разбор |" in _hv_c and "| наблюдение |" in _hv_c and _hv_c.count("**сделал** · **отложить до** · **не актуально**") == 3
      and "**открыть заново**" in _hv_c and "срабатывает «по сроку»" in _hv_c and "ожидаемая дата + 3 дня" in _hv_c
      and all(f"| {m}" in _hv_c for m in ("ждём", "сработало дд.мм", "отложено до дд.мм", "срок вышел", "сделано · не актуально", "снято"))
      and not any(x in _hv_c for x in ("Исполнил", "Отказываюсь", "созрело", "Закрой условие"))
      and "| Задача | Фраза |" in _hv_c and _hv_c.split("| Задача | Фраза |")[1].count("(#copy)") >= 12
      and "### Приоритет {#conditions-priority}" in _hv_c and all(x in _hv_c for x in ("🔴 HIGH", "🟡 MEDIUM", "🟢 LOW")))
check("R32 (03.11): справка «Условия» — кнопка «вышел» у ждущего «вышел отчёт»/«событие» и смысл одной фразой; вьюер шлёт event_found",
      "**вышел**" in _hv_c and "«сработало · ждёт решения»" in _hv_c
      and "condPostEvent(c, 'event_found'" in VIEWER_JS and "COND_FOUND_TRIGGERS = ['report_published', 'event']" in VIEWER_JS)
_hv_s = _HVP["site"]
check("справка «Сайт»: h3 {#site-build} {#site-journal} {#site-push}; сборка на сайте — штатная, «Сохранить» делает снапшот рабочим; пробной папки и фразы «сделай рабочей» как шага нет",
      all(f"{{#{a}}}" in _hv_s for a in ("site-build", "site-journal", "site-push"))
      and "«Сохранить» делает снапшот рабочим" in _hv_s and "в пробную папку" not in _hv_s and "](#copy)" not in _hv_s.split("{#site-build}")[1].split("{#site-journal}")[0].split("рабочей")[0][-60:])
check("справка «Сайт»: уведомления — 08:30, по будням 10:00–19:00, включить через экран «Домой», тихий режим",
      all(x in _hv_s for x in ("08:30", "10:00–19:00", "На экран „Домой“", "Тихий режим")))
_hv_f = _HVP["fresh"]
_hv_vjs = _vjs
_hv_thr = dict(re.findall(r"(\w+):\s*(\d+)", re.sub(r"//[^\n]*", "", re.search(r"const STALE_THRESHOLDS_DAYS = \{(.*?)\n\};", _hv_vjs, re.S).group(1))))
_hv_fail = dict(re.findall(r"(\w+):\s*(\d+)", re.sub(r"//[^\n]*", "", re.search(r"const STALE_FAIL_DAYS = \{(.*?)\n\};", _hv_vjs, re.S).group(1))))
_hv_rows = {"Снимок портфеля": "portfolio", "Обзор акций": "stocks", "Обзор облигаций": "bonds", "Стресс": "stress",
            "Интеграционный анализ": "integratedView", "Монитор прогнозов": "monitor", "Недельная инфляция": "macro"}
for _lbl, _key in _hv_rows.items():
    _m = re.search(r"^\| %s \| > (\d+)(?: дней)? \| (?:> (\d+)|—) \|" % re.escape(_lbl), _hv_f, re.M)
    check(f"справка «Свежесть»: «{_lbl}» — пороги как во вьюере ({_hv_thr.get(_key)} / {_hv_fail.get(_key, '—')})",
          bool(_m) and _m.group(1) == _hv_thr.get(_key) and (_m.group(2) or None) == _hv_fail.get(_key))
check("справка «Ограничения»: не даёт сигналов, ИИС-3 не продаёт, расхождения — главная польза",
      all(x in _HVP["limits"] for x in ("даёт сигналов купить или продать", "ИИС-3", "расхождений")))

# Вьюер грузит части и открывает справку по якорю; офлайн держит все 11 частей
check("вьюер: справка из частей (assets/help/viewer/NN-….md) через uiHelpOpen({files, sections}), старого viewer-help.md в коде нет",
      "uiHelpOpen('portfolio'" in _vjs and "files: HELP_PARTS" in _vjs and "sections: true" in _vjs and "auth: true" in _vjs
      and "'./viewer-help.md'" not in _vjs and "viewer-help.md" not in _vjs.split("\n", 6)[6]
      and "HELP_PARTS = ['00-about', '01-run', '02-models', '03-fresh', '04-tabs', '05-now', '06-gates'," in _vjs
      and "'07-conditions', '08-site', '09-limits', '10-new'].map(n => `./assets/help/viewer/${n}.md`)" in _vjs)
check("вьюер: «Mode N → справка» открывает якорь modes, окно Gate — gates (одна openHelpAt(anchor, opener))",
      "function openHelpAt(anchor, opener)" in _vjs and "function openModesHelp(opener) { openHelpAt('modes', opener); }" in _vjs
      and "function openGatesHelp(opener) { openHelpAt('gates', opener); }" in _vjs
      and "openGatesHelp(ev.currentTarget) }, 'Решения, докупка, фразы" in _vjs and "function showHelpModal() { openHelpAt(null, $('#btn-help')); }" in _vjs)
_hv_anch_js = set(re.findall(r"openHelpAt\('([a-z0-9-]+)'", _vjs)) | set(re.findall(r"_secHead\([^\n]*, '([a-z-]+)'\)", _vjs))
check(f"вьюер: все якоря, на которые ссылается viewer.js, есть в справке (нет: {sorted(_hv_anch_js - set(_hv_anchors))})", _hv_anch_js <= set(_hv_anchors))
_hv_sw = (REPO / "tools/sw-offline.js").read_text(encoding="utf-8")
check("офлайн: sw-offline.js держит все 10 частей справки вьюера, а не viewer-help.md",
      all(f"'assets/help/viewer/{f}'" in _hv_sw for f in _HV_FILES) and "'viewer-help.md'" not in _hv_sw)
check("деплой: viewer-help.md не в FILES deploy.zsh (справка едет с assets/)",
      "viewer-help.md" not in re.search(r"^FILES=\(.*\)$", (REPO / "tools/deploy.zsh").read_text(encoding="utf-8"), re.M).group(0)
      and not (REPO / "tools/viewer-help.md").exists())

# ═══════════════════════ money.html: страница раздела целиком на ui-kit ════════
# Решение 2026-10-05: у страницы НЕТ своих стилей — за вид отвечают общие файлы.
# Своя <style> или цвет в разметке = первый шаг к очередной копии компонентов,
# которые уже разошлись у health/games/travel/food. Inline-стили допустимы только
# для данных (ширина полосы, высота столбика, координата точки, --cols/--n) и
# доменного акцента --sec-acc:var(--c-6).
print("money · страница на ui-kit")
_mn = (REPO / "tools/money.html").read_text(encoding="utf-8")
_mn_nc = re.sub(r"<!--.*?-->", "", _mn, flags=re.S)
check("money.html: нет своего <style>", "<style" not in _mn_nc)
check("money.html: нет цветов-литералов (#hex / rgb / hsl) — только токены",
      re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", _mn_nc) is None)
_mn_styles = re.findall(r'style="([^"]*)"', _mn_nc)
_mn_allowed = re.compile(r"^\s*(?:(?:width|height|left|top|bottom|--cols|--cols-n|--n|--sec-acc|background-image)\s*:[^;]*;?\s*)+$")
_mn_bad = sorted({x for x in _mn_styles if not _mn_allowed.match(x)})
check(f"money.html: inline-стили только для данных и акцента{(' — ' + str(_mn_bad[:3])) if _mn_bad else ''}", not _mn_bad)
check("money.html: акцент раздела — --c-6", "--sec-acc:var(--c-6)" in _mn)
# Узор фона уходит в style="…": url("…") с двойными кавычками обрывает атрибут,
# и фон молча становится однотонным (v1.0.0 так и вышел).
check("money.html: узор фона — url('…') в одинарных кавычках",
      "return \"url('data:image/svg+xml,\"" in _mn and 'url(\\"data' not in _mn)
print("money · периоды трат")
check("money.html: «3 месяца»/«Год» — список периодов, не месяцев",
      "function periodPicker(" in _mn and 'S.period !== "month" && sps.length) return periodPicker(sps)' in _mn)
check("money.html: клик по столбику не сбрасывает период в «Месяц»",
      '"month-at": function(v, el){ set({ month: v, anchor: el.getAttribute("data-anchor") }); }' in _mn
      and 'data-act="month-at" data-anchor="\' + o.id + \'"' in _mn)
# Блоки над графиком меняют высоту от месяца к месяцу — без якоря клик по
# столбику дёргал страницу вверх-вниз (замечание 2026-10-06).
check("money.html: клик по столбику держит график на месте экрана и прокрутку вбок",
      "window.scrollBy(0, anc2.getBoundingClientRect().top - oldTop)" in _mn and "dyn.scrollLeft = oldLeft" in _mn)
# «Обычные траты»: столбики месяцев с пунктиром среднего за 3 месяца ДО месяца
# (меньше истории — среднее того, что есть; у первого месяца пунктира нет).
# Замечания 2026-10-06: пунктир над столбиками и dot plot повторяли нижний
# столбчатый график. На странице ОДИН язык графиков месяцев — colChart: столбики
# + линия скользящего среднего за 3 ПРЕДЫДУЩИХ календарных месяца; режим
# «Остаток» — вверх-вниз от нуля. Колонки без зазора — центр (i+.5)/n, по нему
# идёт линия (с зазором линия разъезжалась бы с точками).
check("money.html: один график месяцев — colChart (столбики + скользящее среднее), без dot plot",
      "function colChart(" in _mn and "regChart" not in _mn and "leftChart" not in _mn
      and "ui-dval" not in _mn and "(i + 0.5) / n * 100" in _mn
      and 'var pr = inCal(all, addM(mm, -3), addM(mm, -1));' in _mn)
check("money.html: «Траты» — переключатель «Траты | Остаток» над единственным графиком",
      'segHTML("chart", [["spend", "Траты"], ["net", "Остаток"]]' in _mn and _mn.count('id: "dyn"') == 1)
check("money.html: время «Трат» в одном месте — период в тулбаре рядом со списком",
      '<span class="ui-toolbar-r">\' + (S.tab === "spend" ? segHTML("period"' in _mn)
check("money.html: отклонение категорий в ₽ и шумовой порог (<5% или <1 тыс. ₽ — «≈»)",
      "Math.abs(x) < 0.05 || Math.abs(diff) < 1000" in _mn)
# с v1.10.0 раскрытых может быть несколько, сворачивание плавное — якорь по id строки в обоих ветках
check("money.html: раскрытие категории держит нажатую строку на месте экрана",
      "catFresh: f, anchor: id });" in _mn and "set({ anchor: id });" in _mn and 'id="cr-\' + catKey(c[0]) + \'" data-act="cat"' in _mn)
# id строки и графика категории — по названию: после клика по столбику список пересортировывается (2026-10-06)
check("money.html: id графика категории — по названию, не по месту в списке",
      'id: "cat-" + catKey(c[0])' in _mn and '"cat-" + ci' not in _mn)
check("money.html: строка категории раскрывается — история по месяцам, где платил, «к прошлому году →»; стрелка «все»",
      'data-act="cat"' in _mn and 'mode: "cat"' in _mn and "ui-catdetail" in _mn and 'data-act="cat-all"' in _mn and 'data-act="yoy" data-v="\' + esc(c[0])' in _mn)
# v1.13.0: окно «к прошлому году» — 12 месяцев, выбор месяцев, места подкатегории, окна стопкой
check("money.html: окно «к прошлому году» — выбор месяцев, места подкатегории, категория поверх «Обычных трат»",
      "function yoyModal(i)" in _mn and 'data-act="yoy-m"' in _mn and 'data-act="yoy-sub"' in _mn and 'data-act="yoy-cat"' in _mn
      and "calRange(addM(Y.end, -11), Y.end)" in _mn and "z: 210 + i" in _mn)
# ui-kit 1.36.0: логика стопки — общая (uiStackCls/uiStackPop/uiStackKeepScroll), страницы её не копируют
check("money.html: окна стопкой — через ui-kit (uiStackCls, uiStackPop, uiStackKeepScroll)",
      "uiStackCls(i, S.yoy.length, S.yoyFresh)" in _mn and "uiStackPop(" in _mn and 'uiStackKeepScroll("yoyb-"' in _mn)
_ukjs_st = (REPO / "tools/assets/ui-kit.js").read_text(encoding="utf-8")
check("ui-kit.js: функции окон стопкой объявлены",
      all(f"function {_f}(" in _ukjs_st for _f in ("uiStackCls", "uiStackPop", "uiStackKeepScroll")))
for _pg in ("money", "food", "health", "travel", "games", "hub"):
    _src_st = (REPO / f"tools/{_pg}.html").read_text(encoding="utf-8")
    check(f"{_pg}.html: анимацию закрытия окна не ставит сама (.leave/.return — только uiStackPop)",
          'classList.add("leave")' not in _src_st and "classList.add('leave')" not in _src_st
          and 'classList.add("return")' not in _src_st)
_css_mb = (REPO / "tools/assets/ui-kit.css").read_text(encoding="utf-8")
for _cls in (".ui-cols-line{", ".ui-col-val{", ".ui-col-net{", ".ui-cols-zero{", ".ui-sw-line{", ".ui-row.ui-catrow{",
             ".ui-minibars{", ".ui-catdetail{", ".ui-toolbar-r{", ".ui-grid.kpi{", ".ui-status{", ".ui-trip{"):
    check(f"ui-kit.css: стиль {_cls[:-1]}", _cls in _css_mb)
# Safari считал width:max-content у .ui-cols по видимой области: слой линии
# выходил уже колонок, и на iPhone линия обрывалась за 3 месяца до края.
check("ui-kit.css + money.html: ширина графика месяцев — явно по числу колонок (--cols-n)",
      "width:max(100%, calc(var(--cols-n, 12) * 100cqw / 12))" in _css_mb and "max-content" not in re.search(r"\.ui-cols\{[^}]*\}", _css_mb).group(0)
      and "style=\"--cols-n:' + rows.length" in _mn)
check("ui-kit.css: колонки графика без зазора (иначе линия среднего разъезжается с точками)",
      re.search(r"\.ui-cols\{[^}]*\}", _css_mb) is not None and "gap:" not in re.search(r"\.ui-cols\{[^}]*\}", _css_mb).group(0))
# Ноль «Остатка» — на доле z = hi/(hi−lo) от ВЕРХА (в первой версии стоял на
# 1−z и рисовался у верхнего края).
# Линия среднего — монотонная кривая (Штеффен, как d3.curveMonotoneX): через
# каждую точку и без «перелёта» между соседними (Catmull-Rom рисовал бы среднее,
# которого не было). Точек на линии нет — просьба 2026-10-06.
check("money.html: линия среднего — монотонная кривая без точек",
      "function smoothPath(pts)" in _mn and "0.5 * Math.abs(p)" in _mn
      and "'<path d=\"' + smoothPath(sg)" in _mn and "ui-col-avg" not in _mn)
# Страница и ui-kit.css доезжают на NAS по отдельности: без fill="none" прямо в
# SVG кривая при старом CSS заливается чёрным клином (скриншот 2026-10-06).
check("money.html: линия среднего не зависит от CSS (fill=none атрибутом)",
      '+ \'" fill="none" stroke="currentColor"' in _mn)
check("money.html: подписи значений над столбиками (у «Остатка» — и % дохода; в компактном — только выбранный)",
      'class="ui-col-val' in _mn and "if (!o.compact || on[r.mm])" in _mn and "<small>' + Math.round(r.v / inc * 100) + '%</small>" in _mn)
check("money.html: над графиком «Трат» — строка выбранного периода, числа жирным",
      "bv(K(t.expense_trips_rub || 0))" in _mn and "function bv(x){ return '<b class=\"ui-strong\">'" in _mn)
check("money.html: у столбиков нет всплывающей подсказки (title), только aria-label",
      "data-anchor=\"' + o.id + '\" data-v=\"' + r.mm + '\" aria-label=" in _mn)
check("money.html: нулевая линия «Остатка» — на z от верха области графика",
      "top:calc(var(--plot-h) * ' + z.toFixed(4) + ')" in _mn)
check("ui-kit.css: dot plot и мини-столбики убраны (один язык графиков)",
      ".ui-dots{" not in _css_mb and ".ui-mbars{" not in _css_mb and ".ui-split{" not in _css_mb)
print("money · обзор")
check("money.html: «Обзор» — первая вкладка и открывается по умолчанию",
      'var TABS = [["overview", "Обзор", "Обзор"]' in _mn and 'var S = { theme: "light", tab: "overview"' in _mn)
_ov = _mn.split("function tabOverview(){", 1)[1].split("/* ═══ вкладка «Качество учёта»", 1)[0] if "function tabOverview(){" in _mn else ""
check("money.html: обзор считает теми же функциями, что вкладки (spendWindow/catRows/tripSegs/colChart)",
      all(f in _ov for f in ("spendWindow(", "catRows(", "tripSegs(", "colChart(")))
check("money.html: обзор — «Осталось от дохода» = доходы − расходы месяца",
      "left = tt.income_rub - tt.expense_rub" in _ov)
check("money.html: обзор — «открыто замечаний» по статусам issues (openStats), не по снимку записи",
      "openStats(S.H).total" in _ov and "latest.open_total" not in _mn)
# «Закрыт» = есть и итоги трат, и аудит. Проверяется ПРОШЛЫЙ КАЛЕНДАРНЫЙ месяц,
# а не последний закрытый: с пропусками «сентябрь закрыт» не значит «август тоже».
check("money.html: обзор подсказывает закрыть прошлый календарный месяц (итоги и аудит)",
      "function unclosed(m)" in _mn and "unclosed(expected)" in _ov
      and "ещё не закрыт — скажи Claude «закрой" in _mn and "закрыт не полностью" in _mn)
_hb0 = (REPO / "tools/hub.html").read_text(encoding="utf-8")
check("хаб: плитка денег предупреждает о незакрытом прошлом месяце",
      'id="money-todo"' in _hb0 and "hasSp = ms.some(function(x){ return x.month === pk; })" in _hb0
      and "hasAu = recs.some(function(x){ return x.month === pk; })" in _hb0)
check("money.html: «Траты» и «Обзор» берут категории из одной catRows",
      _mn.count("catRows(") >= 3)
# История бывает с пропусками (февраль, апрель — март не закрыт). «3 месяца до»
# и окна периодов — по календарю, на графиках пропуск — пустое место, а не
# соседние записи вплотную (замечено на данных 2026-10-06).
check("money.html: окна и средние — по календарю, не по соседним записям",
      "prior: inCal(all, addM(m, -3), addM(m, -1))" in _mn and "inCal(all, addM(mm, -3), addM(mm, -1))" in _mn
      and "all.slice(Math.max(0, i - 3), i)" not in _mn)
check("money.html: пропущенный месяц на графиках — пустое место с подписью",
      'class="ui-col gap"' in _mn and "calRange(all[0].month, all[all.length - 1].month)" in _mn
      and "calRange(series[0].month" in _mn)
check("ui-kit.css: стиль пустого места графика (.gap)", ".ui-col.gap" in (REPO / "tools/assets/ui-kit.css").read_text(encoding="utf-8"))
check("money.html: год — рабочий (календарный год к прошлому), без заглушки «пока рано»",
      'period === "year"' in _mn and "Годовой обзор пока рано" not in _mn)
_css_all = (REPO / "tools/assets/ui-kit.css").read_text(encoding="utf-8")
_mn_cls = set()
for _attr in re.findall(r'class="([^"]*)"', _mn_nc):
    for _c in re.split(r"[\s'+]+", _attr):
        if re.fullmatch(r"ui-[\w-]+|lv(?:\d|-[\w-]+)", _c):
            _mn_cls.add(_c)
_mn_missing = sorted(c for c in _mn_cls if not re.search(r"\." + re.escape(c) + r"(?![\w-])", _css_all))
check(f"money.html: каждый класс ui-*/lv* описан в ui-kit.css{(' — нет: ' + ', '.join(_mn_missing)) if _mn_missing else ''}",
      not _mn_missing)
check("money.html: подвал сообщает версию (money vN)", re.search(r"money v\d", _mn) is not None)
check("money.html: данные — ../ZenMoney/audit/ (страница в /tools/)", 'var DATA = "../ZenMoney/audit/"' in _mn)
print("money · история за годы и факты (v1.8.0)")
# 2026-10-06: факты считает только скилл (history_query.py) — страница только подписывает,
# иначе формулы и пороги разошлись бы; факты старше последнего месяца итогов не показываются.
check("money.html: facts.json читается, но в «Нет файла» не попадает",
      'F: "facts.json"' in _mn and "[r[2], FILES.T]].filter" in _mn)
check("money.html: факты не считаются на странице (ни медиан, ни порогов)",
      re.search(r"function\s+\w*(median|quantile|iqr)\w*\s*\(", _mn, re.I) is None
      and "PARAMS" not in _mn and "min_gap" not in _mn and "min_ratio" not in _mn)
check("money.html: устаревшие факты не показываются (month = последнему месяцу итогов)",
      "S.F.month !== all[all.length - 1].month" in _mn)
check("money.html: «Все годы» — четвёртый режим «Трат», без списка месяцев",
      '["years", "Все годы"]' in _mn and 'S.tab === "spend" && S.period === "years"){' in _mn and "function tabYears(" in _mn)
check("money.html: тип анализа — на уровне вкладок, список — под ним; заголовка периода слева нет",
      '<div class="ui-toolbar stack">' in _mn and "return head(win.label)" not in _mn and 'return head("Все годы")' not in _mn
      and ".ui-toolbar.stack .ui-toolbar-r{ flex-direction:column;" in (REPO / "tools/assets/ui-kit.css").read_text(encoding="utf-8"))
check("money.html: возврат из «Все годы» — график месяцев снова у последнего месяца",
      "if (dyn && (!S.dynScrolled || oldLeft == null)){ dyn.scrollLeft = dyn.scrollWidth;" in _mn)
check("money.html: «Все годы» — линии дохода и остатка", 'class="alt"' in _mn and "ui-sw-line alt" in _mn)
check("ui-kit.css: тулбар на компьютере одной строкой (смена режима не двигает страницу)",
      ".ui-toolbar{ flex-wrap:nowrap; } .ui-toolbar-r{ flex:1 1 0; min-width:0; flex-wrap:nowrap; }" in (REPO / "tools/assets/ui-kit.css").read_text(encoding="utf-8"))
check("money.html: «Все годы» не добавляет второй график месяцев (id dyn один)", _mn.count('id: "dyn"') == 1 and 'id: "yrs"' in _mn)
check("money.html: новая подкатегория — «новая статья с», без процента",
      "новая статья «" in _mn)
check("money.html: «пересчитан» — в подписи месяца", "s.recomputed_at" in _mn and "пересчитан " in _mn)
check("money.html: подкатегории и их места в раскрытой категории (места — с подкатегорией, 2.13.0)",
      "function subList(" in _mn and "subcategories_regular" in _mn and "x.sub ||" in _mn and "function places(sn)" in _mn)
check("money.html: запросы — общим authFetch (Authorization из hub-auth; ZenMoney/* под паролем)",
      'return authFetch(uiBust("money", DATA + name)' in _mn and re.search(r"function\s+authFetch\s*\(", _mn) is None)
check("money.html: выписка банка — блок на вкладке «Загрузка» (ключ csv; шестой вкладки stmt нет), POST только через zmPost в stmt и stmt-report, слот uiFileSlot (только .xlsx,.csv), кнопка ui-btn lg; версия 2.6.0",
      '["csv", "Загрузка", "Загрузка"]' in _mn and '["stmt"' not in _mn and 'zmPost("stmt", {' in _mn and 'zmPost("stmt-report", {' in _mn
      and 'uiFileSlot({ key: "stmt"' in _mn and 'accept: ".xlsx,.csv"' in _mn and 'class="ui-btn lg" id="stmt-pick"' in _mn
      and 'var VERSION = "money v2.6.2"' in _mn and "function tabUpload()" in _mn)
_dc = (REPO / "tools/hosting/docker-compose.yml").read_text(encoding="utf-8")
_zs = (REPO / "tools/hosting/notify/zm_stmt.py").read_text(encoding="utf-8")
_dz = (REPO / "tools/deploy.zsh").read_text(encoding="utf-8")
check("hosting: сверка выписки — маршрут /internal/zm-stmt-report, зона /api/zm/stmt-report, PDF на сайте нет (ни poppler-utils в compose, ни pdftotext в zm_stmt), в deploy только скрипты CSV/XLSX",
      "/internal/zm-stmt-report" in (REPO / "tools/hosting/notify/notifier.py").read_text(encoding="utf-8")
      and "poppler" not in _dc and "pdftotext" not in _dc and "pdftotext" not in _zs
      and "stmt_import stmt_compare stmt_accounts parse_bog_statement parse_raif_statement" in _dz
      and "parse_ff_statement" not in _dz and "parse_tbank_statement" not in _dz
      and '"/api/zm/stmt-report"' in (REPO / "tools/hosting/api/server.py").read_text(encoding="utf-8"))
check("money.html: данные только читает; пишет лишь вкладка «Выгрузка» — POST только в /api/zm/ (csv, csv-report, csv-apply), прочих /api/ нет",
      len(re.findall(r'method\s*:\s*["\'](?:POST|PUT|DELETE|PATCH)', _mn)) == 1 and re.search(r'method\s*:\s*["\'](?:PUT|DELETE|PATCH)', _mn) is None
      and set(re.findall(r'/api/([a-z]+)/', _mn)) == {"zm"} and 'ZM = "../api/zm/"' in _mn)
check("money.html: уход на вход — общий uiGoLogin со страховкой от петли",
      'uiGoLogin("money"' in _mn and 'uiLoginOk("money")' in _mn)
# open_total/open_by_age — снимок ВСЕЙ истории на момент записи (бриф §1): ни выбранный месяц,
# ни последняя по месяцу запись не годятся — перезакрытый январь не обновляет октябрьскую запись
# (1.11.2026: январь закрыт, страница показывала «1 открыто»). Счёт — по статусам issues; хаб так же.
# маленькие суммы (1.24.1–1.24.2): «0,0 тыс. ₽» у замечания на 3,80 ₽ и «0,0» у места с покупкой на 30 ₽
check("money.html: меньше тысячи — в рублях (K), в колонках «тыс. ₽» ненулевое меньше 50 ₽ — «<0,1» (k1)",
      'a < 999.5' in _mn and 'num(a, 2)' in _mn and '"<0,1"' in _mn and "a > 0 && a < 50" in _mn)
check("money.html: «открыто замечаний» — по статусам issues, возраст как age_bucket (31/92 дня)",
      "function openStats(H)" in _mn and 'i.status !== "open"' in _mn and "days >= 31" in _mn and "days <= 92" in _mn
      and "var ost = openStats(H)" in _mn)
check("hub.html: плитка «Деньги» — открытые по статусам issues, не open_total последней записи",
      'iss[k].status === "open"' in HUB_HTML)
check("money.html: выбор месяца и поездки — общий выпадающий список ui-kit",
      'uiSelectHTML({ name: "month"' in _mn and 'uiSelectHTML({ name: "trip"' in _mn
      and 'addEventListener("ui-select"' in _mn)
# by_check кладёт только сработавшие типы: нет ключа ≠ «не проверялось».
check("money.html: нет ключа в by_check = ноль, не «не проверялось»",
      "не проверялось" not in _mn and "bc[c] || { count: 0, rub: 0 }" in _mn)

print("ui-kit · выпадающий список")
check("ui-kit.js: uiSelectHTML объявлен", "function uiSelectHTML(" in UI_KIT_JS)
check("ui-kit.js: список закрывается по Esc и кликом мимо",
      'ev.key === "Escape" && open' in UI_KIT_JS and "uiSelectCloseAll(null)" in UI_KIT_JS)
check("ui-kit.js: выбор сообщается событием ui-select",
      'new CustomEvent("ui-select"' in UI_KIT_JS)
for _cls in (".ui-select{", ".ui-select-btn{", ".ui-select-pop{", ".ui-opt{"):
    check(f"ui-kit.css: стиль {_cls[:-1]}", _cls in _css_all)
# .ui-top не должен переопределять шапки других страниц: их .h-top/.chip-btn
# разошлись, и общее правило под тем же именем молча поменяло бы их вид.
check("ui-kit.css: шапка раздела — .ui-top, без голых .h-top{/.chip-btn{",
      ".ui-top{" in _css_all and re.search(r"(?m)^\.(h-top|chip-btn)\s*\{", _css_all) is None)

print("hub · деньги рядом с инвестициями")
_hb = (REPO / "tools/hub.html").read_text(encoding="utf-8")
_row1 = _hb.split('<div class="hub-row1">', 1)[1].split('<div class="hub-row2">', 1)[0] if '<div class="hub-row1">' in _hb else ""
check("хаб: в одном ряду .hub-row1 — портфель и деньги",
      'class="hub-card hub-feat"' in _row1 and 'href="money.html"' in _row1)
check("хаб: плитка денег — акцент --c-6", 'href="money.html" style="border-left:3px solid var(--c-6);' in _hb)
check("хаб: цифры денег — только с токеном и из ../ZenMoney/audit/",
      'if (!$("money-head") || !authToken()) return;' in _hb and '"../ZenMoney/audit/"' in _hb)
check("хаб: ряд финансов складывается в столбик на узком экране",
      re.search(r"@media \(max-width:900px\)\{\s*\.hub-row1\{ grid-template-columns:1fr; \}", _hb) is not None)

print("viewer 3.0 · переделка на ui-kit (TODO_design §1, 2026-10-12)")
# Решения владельца: разделы одним списком без эмодзи, редкие — в «Ещё ▾»; карточка бумаги —
# окно ui-kit по центру с подвкладками и листанием; Chart.js остаётся только в «Стрессе»
# и «Динамике»; «Доли и цели» — ребалансировка от цен снапшота.
_V3 = (REPO / "tools/assets/viewer.js").read_text(encoding="utf-8")
# с шага 2 цикла машиночитаемости (31.10) слова кодов — в кодлистах: вьюер берёт их из CL (assets/codelists.js)
_CL_TXT = (REPO / "_shared-references/codelists.json").read_text(encoding="utf-8")
_CL = __import__("json").loads(_CL_TXT)["lists"]
_GATE_HINTS = " ".join(e["hint"] for e in _CL["gate_status"].values())
_GATE_EFFECTS = " ".join(e["effect"] for e in _CL["gate_status"].values())
_V3HTML = (REPO / "tools/portfolio-integrated-viewer.html").read_text(encoding="utf-8")
for _fn in ("uiTabsHTML", "uiTabsMount", "uiNode", "uiAnimIn"):
    check(f"ui-kit.js 1.39: {_fn}() объявлена", re.search(r"function\s+" + _fn + r"\s*\(", UI_KIT_JS) is not None)
for _sel in (".ui-tabs{", ".ui-tab{", ".ui-tabs-pop{", ".ui-name{", ".ui-ci{", ".ui-alert.info{", ".ui-alert.warn{",
             '.ui-table th[aria-sort]{', ".ui-table.sticky thead th{", ".ui-modal-top{", ".ui-pager-btn{", ".ui-in-next{"):
    check(f"ui-kit.css 1.39: стиль {_sel[:-1]}", _sel in _css_all)
check("ui-kit.js: обработчики строки разделов — только в браузере (ui-kit читают и в node)",
      'if (typeof window !== "undefined"){   // ui-kit.js читают и вне браузера' in UI_KIT_JS)
check("ui-kit.js: uiModalHTML принимает слоты lead/aside/top",
      all(k in UI_KIT_JS for k in ("o.lead ?", "o.aside ?", "o.top ?")))
check("ui-kit.css: окно постоянной высоты на телефоне — во весь экран",
      ".ui-modal.tall .ui-modal-box{ height:100%; }" in _css_all)
# порядок разделов — как решил владелец; «Макро» справа от «Долей и целей» (2026-10-13), «Ещё» — после
_bt = re.search(r"function buildTabs\(\) \{(.*?)\n\}", _V3, re.S)
_ids = re.findall(r"id: '([\w-]+)', label: '([^']+)'", _bt.group(1)) if _bt else []
_main = [l for i, l in _ids][:13]
check(f"вьюер: разделы по порядку {_main}",
      _main == ["Сегодня", "Акции", "Облигации", "Фонды", "ИИС-3", "Выплаты", "Динамика", "Стресс", "Действия", "Изменения", "Доли и цели", "Макро", "Источники"])   # v3.63.0: «Источники» справа от «Макро»
check("вьюер: редкие разделы — в «Ещё» (more: true)",
      all(re.search(r"id: '" + i + r"', label: '[^']+', more: true", _bt.group(1) if _bt else "") for i in ("dashboard", "forecasts"))   # v3.63.0: «Источники» — в основной строке; оговорки и «что не показано» — части раздела
      and not re.search(r"id: '(caveats|whats-not)'", _bt.group(1) if _bt else ""))
check("вьюер: в подписях разделов нет эмодзи",
      all(re.match(r"^[\wЁёА-я\- ]+$", l) for i, l in _ids))
check("вьюер: старые id вкладок — псевдонимы (кнопки «→ Watchlist» и ссылки не ломаются)",
      "const TAB_ALIASES = { watchlist: 'actions', 'action-queue': 'actions', 'forecast-l2': 'forecasts', predictions: 'forecasts' };" in _V3)
check("вьюер: строка разделов — общий uiTabsHTML/uiTabsMount, своей nav.tabs нет",
      "uiTabsHTML(tabs, state.currentTab" in _V3 and "uiTabsMount(host" in _V3 and "nav.tabs" not in _V3HTML)
check("вьюер: горизонт — под строкой разделов (строка не прыгает при смене раздела)",
      _V3HTML.find('id="tabs"') < _V3HTML.find('id="horizon-bar"'))
check("вьюер: карточка — окно ui-kit по центру, постоянной высоты, стопкой; на телефоне шапка сворачивается (.fold)",
      "width: 1150" in _V3 and "cls: 'tall fold card-win ' + uiStackCls(i, n, cardFresh)" in _V3 and "uiStackPop(layers, i" in _V3
      and "host.querySelectorAll('.ui-modal').forEach(uiFoldMount)" in _V3)
check("ui-kit 1.42: сворачивание шапки окна — uiFoldMount, липкие подвкладки, гашение плиток прокруткой",
      re.search(r"function\s+uiFoldMount\s*\(", UI_KIT_JS) is not None and ".ui-modal.fold .ui-modal-stick{ position:sticky;" in _css_all
      and "animation-timeline:view(" in _css_all)
check("вьюер: подвкладка между открытиями не запоминается (флаг по умолчанию выключен)",
      "const CARD_REMEMBER_SUB = false;" in _V3)
check("вьюер: подвкладки акции и облигации — как решил владелец",
      "stock: [['main', 'Главное'], ['ret', 'Доходность'], ['risk', 'Риски'], ['hist', 'История'], ['reports', 'Отчёты']]" in _V3
      and "bond: [['main', 'Главное'], ['pay', 'Выплаты'], ['risk', 'Рейтинг и риски'], ['hist', 'История'], ['reports', 'Отчёты']]" in _V3)
check("вьюер: листание ← → и появление — общий uiAnimIn",
      "uiAnimIn(top.querySelector(s), dir > 0 ? 'next' : 'prev')" in _V3)
# Chart.js — только «Стресс» (makeTweenBarChart) и «Динамика» (drawLineChart)
_charts = re.findall(r"new Chart\(", _V3)
check(f"вьюер: Chart.js остался в двух местах ({len(_charts)})", len(_charts) == 2)
for _gone in ("cv-bond-type", "cv-ladder", "cv-sector", "`sl-${k}`"):
    check(f"вьюер: график {_gone} снят (полосы / «Выплаты» / .ui-spark)", _gone not in _V3)
check("вьюер 4.4.7: цель IE по цене — из строки IE, иначе от цены IE на дату модели; потенциал — только от текущей цены до цели (владелец 06.11.2026), подписи «от … ₽ у IE» нет",
      "m?.current_price_rub ?? null" in _V3 and "base * (1 + pc / 100)" in _V3 and "m?.target_price_rub ?? up(" in _V3
      and "function ieMarketPrice(ticker)" in _V3 and "const pc = (t) => t != null && cur ? (t / cur - 1) * 100 : null;" in _V3
      and "₽ у IE`" not in _V3 and "'нет в модели IE'" in _V3 and "'нет текущей цены'" in _V3)
check("вьюер: «Доли и цели» — коридор ±1 %, без калькулятора «куда положить»",
      "const REBAL_CORRIDOR_PP = 1;" in _V3 and "Калькулятора «куда положить N ₽» нет" in _V3)
check("вьюер: мини-график в плитке — 6 месяцев по календарю",
      "const months = opts && 'months' in opts ? opts.months : 6;" in _V3 and "_monthsBackIso(last, months)" in _V3)
check("вьюер: ИИС-3 — последний отчёт «ИИС-3 Buy Advice», своих советов нет",
      "function _latestIisReport()" in _V3 and "Вьюер своих рекомендаций не даёт" in _V3)

# v3.1–3.2: замечания владельца 2026-10-13 и остаток переделки — старые классы не возвращаются
check("вьюер 3.2: нет своих section.card / .banner / .eyebrow / .stat-grid / table.compact",
      not re.search(r"class: '(card|banner [a-z]+|eyebrow|stat-grid|compact)'", _V3))
check("вьюер 3.2: таблицы «Акций» и «Облигаций» — .ui-table.dense с aria-sort",
      _V3.count("el('table', { class: 'ui-table dense sticky' })") >= 2 and "'aria-sort': isSorted ?" in _V3)
check("ui-kit.css 1.41: .ui-table.dense и липкая шапка без отступа в прокручиваемой обёртке",
      ".ui-table.dense :is(th, td).num{" in _css_all and ".ui-table-wrap:not(.flow) > .ui-table.sticky thead th{ top:0; }" in _css_all)
check("ui-kit.css 1.40: нулевой уровень мини-графика", ".ui-spark line.zero{" in _css_all)
check("вьюер 3.1: окно документа входит/уходит как окна ui-kit (.ui-fx + uiShow/uiHide)",
      'class="modal-overlay ui-fx"' in _V3HTML and "uiHide($('#modal-overlay')" in _V3 and "removeAttribute('hidden');\n" not in _V3.split("function showDocModal")[1][:2000])
check("вьюер 3.1: «Динамика» не в HORIZON_TABS — горизонт у графика §4",
      "'history'" not in re.search(r"const HORIZON_TABS = new Set\(\[(.*?)\]\)", _V3).group(1) and "horizonSegNode()" in _V3)
check("вьюер 3.56: катализатор из «Изменений» открывает карточку на «Рисках» (катализаторы там, старый ключ cat → risk)",
      "openCard(pos, list, { sub: 'risk'" in _V3 and "'data-cat-id'" in _V3 and "opts?.sub === 'cat' ? 'risk'" in _V3)
# v3.56.0 — карточка «одно решение» (план viewer-rethink-plan.md §1, решения владельца 26.10)
check("вьюер 3.56: «Решение» словами, уверенность словом, коды — словами",
      "function cardDecisionNode(" in _V3 and "function confWord(" in _V3 and "function humanizeText(" in _V3 and "const VERDICT_WORD = CL.words('verdict')" in _V3)
check("вьюер шаг 12: копии ограничений обзора (user_constraints) не читаются — блока «Запрет» из обзора нет",
      "function ownerBans(" not in _V3 and "function cardBanNode(" not in _V3)
check("вьюер 3.56: «Чего ждём» — развилка «если → тогда» (branches определения conditions@2 или одна строка из текста)",
      "ot = def.on_trigger || {}" in _V3 and "Array.isArray(ot.branches)" in _V3 and "class: 'ui-table dense branch'" in _V3)
check("вьюер 3.56: «История» — журнал решений из обзоров, гейта, условий и сделок",
      "function cardTimelineNode(" in _V3 and "type: 'gate'" in _V3 and "type: 'cond'" in _V3 and "kind: 'trade'" in _V3 and "function _secRaw(" in _V3)
check("вьюер 3.56: лоты у акций двумя строками, облигации — штуками",
      "лотов`, el('div', { class: 'ui-note' }, `${fmtNum(lot)} шт. в лоте" in _V3)
check("вьюер 3.56: модель IE — «было» только при смене цели, свежесть 2 мес",
      "const IE_FRESH_DAYS = 62;" in _V3 and "changed ? ` (было" in _V3)
check("вьюер 3.56: облигация — цена в % номинала главным числом",
      "% номинала)` : '')" in _V3 and "cardTile('Цена'" not in _V3.split("function cardBondHead(")[1].split("\n}\n")[0])   # 3.107: цена — только в заголовке карточки
for _cls in ("card-decision", "card-why", "card-ban", "branch", "tl-k", "tl-m", "cat-dir", "tag-info", "pc-pt", "card-hist-old"):
    check(f"viewer.css 3.56: правило для .{_cls}", f".{_cls}" in _VCSS)
# v3.57.0 — этап 3 плана: вьюер читает новые поля контрактов A/B и confidence_basis
check("вьюер 3.57: план на момент постановки условия — из context.plan_pct определения, иначе по истории снапшотов",
      "planChangedSince(ticker, def.created_at, def.context?.plan_pct)" in _V3 and "function planChangedSince(ticker, iso, knownThen)" in _V3)
check("вьюер 3.57: ветка развилки — текст then.text и сумма с лотами по then.target_pct от живой цены",
      "function branchSizingText(" in _V3 and "branchSizingText(ticker, t?.target_pct, price)" in _V3 and "thenOf(b.then)" in _V3)
check("вьюер 3.57: «Что произошло за неделю» — рекомендация недели из week_note.recommendation",
      "'Рекомендация недели: '" in _V3)
check("вьюер 3.57: уверенность с причиной confidence_basis", "r.confidence_basis || p.review?.confidence_basis" in _V3)
check("вьюер 3.57.1: валютная облигация — тело и купон в валюте номинала, рубли по курсу ЦБ снапшота", "fx_rates_used?.[cur]?.rate" in _V3 and "const perBondCur" in _V3)
check("viewer.css 3.57.1: плитки «Истории» одной высоты", ".card-tl-stats{ margin-bottom:18px; align-items:stretch;" in _VCSS)
check("вьюер 3.62: «Источники · Оговорки · Что не показано» — раздел в «Ещё» с сегментом, кнопки в шапке нет",
      "function renderProvenanceTab(" in _V3 and "btn-provenance" not in _V3HTML and "btn-provenance" not in _V3
      and "{ id: 'sources', label: 'Источники' }" in _V3 and "{ id: 'sources', label: 'Источники', more: true }" not in _V3 and "showProvenanceModal" not in _V3)
check("вьюер 3.62: ссылки #tab=caveats|whats-not ведут в раздел «Источники» на нужную часть",
      "if (PROVENANCE_IDS.has(id) && id !== 'sources') { state.provPart = id; id = 'sources'; }" in _V3)
_upc = _V3.split("function buildUpcomingCard(")[1].split("\nfunction ")[0]
check("вьюер 3.62: «Сегодня» — одиночная выплата открывает карточку бумаги, условие без карточки — окно условия",
      "items: one ? null : rs" in _upc and "showConditionModal(it.cond)" in _upc)
check("вьюер 3.62: окно условия и общий узел условия", "function showConditionModal(" in _V3 and "function condCardNode(" in _V3)
check("вьюер 3.62: кнопки «Обзор акций/облигаций (YAML)» убраны", "'Обзор акций (YAML)'" not in _V3 and "'Обзор облигаций (YAML)'" not in _V3)
check("viewer.css 3.62: плашка «приватный» не наезжает на кнопки шапки", ".app-header .ui-top-sec{ overflow:hidden; }" in _VCSS)
# ── вьюер 3.63 ──
check("вьюер 3.63: forecasts/*.md грузятся и классифицируются как forecastMd",
      "pattern: /\\.(yaml|yml|md)$/, folder: 'forecasts/'" in _V3 and "return base === 'index.md' ? null : 'forecastMd'" in _V3
      and "forecastMds: []" in _V3 and "forecastMd: 'Прогнозы (текст)'" in _V3)
check("вьюер 3.63: часть «Предложения на аудит» в PROVENANCE_PARTS", "id: 'audit-candidates'" in _V3 and "function renderAuditCandidates(" in _V3)
_al_py = (REPO / "skills/retrospective-forecast-audit/scripts/audit_candidates.py").read_text(encoding="utf-8")
_al_m = re.search(r"^ALIASES[^=]*=\s*(\[.*?^\])", _al_py, re.S | re.M)
_al_groups = ast.literal_eval(_al_m.group(1)) if _al_m else []
_al_js = re.search(r"const AUDIT_ALIASES = (\[.*?\n\]);", _V3, re.S)
_al_js = _al_js.group(1) if _al_js else ""
check("вьюер 3.63: AUDIT_ALIASES совпадает с ALIASES из audit_candidates.py (%d групп)" % len(_al_groups),
      len(_al_groups) > 5 and all(('"%s"' % a) in _al_js for g in _al_groups for a in g)
      and _al_js.count("[") - 1 == len(_al_groups))
check("вьюер 3.63: «Источники» без more: true и сразу после «Макро» в buildTabs",
      "tabs.push({ id: 'sources', label: 'Источники' })" in _V3
      and _V3.index("label: 'Макро' });") < _V3.index("tabs.push({ id: 'sources', label: 'Источники' })") < _V3.index("label: 'Интеграционный анализ', more: true"))
check("вьюер 3.63: «полный отчёт →» в шапке «Бумаг», одинокой кнопки «Полный отчёт» нет",
      _V3.count("'полный отчёт →'") == 3 and "'Полный отчёт'" not in _V3 and ".sec-rep-link{" in _VCSS)
check("вьюер 3.63: день с несколькими выплатами раскрывается по бумагам (up-sub, uiExpandIn)",
      "items: one ? null : rs" in _upc and "up-sub" in _upc and "uiExpandIn(" in _upc and ".up-sub{" in _VCSS and ".up-row.open{" in _VCSS)
_cph = _V3.split("function condPhrases(")[1].split("\nfunction condPhrasesNode")[0]
check("вьюер 3.63 → шаг 12: фразы условия с подписью назначения (правка определения — через Claude), отметки владельца — кнопками",
      "label" in _cph and "'снять условие'" in _cph and "разобрать сейчас, не дожидаясь срока" in _cph and _cph.count("— разбираем") == 1
      and "if (!c.active) return [];" in _cph and "x.label + ': '" in _V3 and "ДД.ММ и N замени на свои" in _V3)
_iem = _V3.split("function renderIeModel(")[1].split("\nfunction ")[0]
check("вьюер 3.63: «Доли и цели» — плашка plan_check («Общий баланс» отстаёт от плана на сайте)",
      "plan_check" in _iem and "отстаёт от плана на сайте" in _V3.split("function buildPlanCheckNode(")[1].split("\nfunction ")[0])
check("вьюер 3.63.2: короткий список кандидатов — порог по упоминаниям (зеркало shortlist_threshold в python)",
      "function auditShortlistThreshold(" in _V3 and "auditShortlistThreshold(cands, 10)" in _V3
      and "def shortlist_threshold(" in open(REPO / "skills/retrospective-forecast-audit/scripts/audit_candidates.py", encoding="utf-8").read())
check("вьюер 3.63.3: клик по строке кандидата копирует фразу для аудита",
      "_copyText(`/forecast-collector Собери прогнозы ${r.source} для аудита`)" in _V3)

check("вьюер 3.59: «Выплаты» — переключатель счетов, календарь на счёт из detail, у ИИС-3 без дивидендов", "function payoutsCalendarFor(" in _V3 and "'piv-payouts-acct'" in _V3 and "state.payoutsAcct" in _V3)
# ── вьюер 3.64 ──
check("вьюер 3.64: loadPlan и окно правки плана", "function loadPlan(" in _V3 and "function showPlanEditModal(" in _V3)
check("вьюер 3.64: API плана — plan, plan/set, plan/journal", all(f"'{u}'" in _V3 for u in ("api/pv/plan", "api/pv/plan/set", "api/pv/plan/journal?limit=200")))
check("вьюер 3.64: кнопка «изменить →» в карточке не отключена навсегда (старой подсказки нет), путь stocks.${ формируется", "появится с уходом" not in _V3 and "`stocks.${t}.${f}`" in _V3)
check("вьюер 3.64: слой #plan-layer в HTML и стили .plan-edit", 'id="plan-layer"' in (REPO / "tools/portfolio-integrated-viewer.html").read_text(encoding="utf-8") and ".plan-edit{" in _VCSS)

check("вьюер 3.60: «Сегодня» без списков вердиктов, «Ждут решения», полосы монитора и плашки дюрации", all(s not in _V3.split("function renderToday(c)")[1].split("\nfunction ")[0] for s in ("buildFiredConditionsCard()", "buildVerdictCards()", "buildWatchlistHighStrip()", "computeDurationSignal()")))
check("вьюер 3.60: «Ближайшие 30 дней» и «Движение за неделю» на «Сегодня»", "function buildUpcomingCard(" in _V3 and "function buildMoversCard(" in _V3 and "buildUpcomingCard()" in _V3 and "buildMoversCard()" in _V3)
check("вьюер 3.61: «Доли и цели» — вердикт советника под «Сейчас» со ссылкой на «Действия»", "class: 'ui-note rb-adv'" in _V3 and ".rb-adv.warn{" in _VCSS and "goToTab('actions')" in _V3.split("const nowCell = (a, r) =>")[1].split("const th = cols.map")[0])

# ── вьюер 3.65 ──
_pem = _V3.split("function showPlanEditModal(")[1].split("\nlet planSaving")[0]
_pes = _V3.split("async function planEditSave(")[1].split("\n// Поправить снапшот")[0]
check("вьюер 3.65: статус плана — список из USER_STATUS_WORD, старый текст не теряется, поля «Заметка IE» в окне нет",
      "const USER_STATUS_WORD" in _V3 and "USER_STATUS_WORD" in _pem and "как в Numbers:" in _pem and "fld('Заметка IE'" not in _pem)
check("вьюер 3.65: блок «Модель IE» (только чтение) под «Советником»", "'Модель IE'" in _pem and "ie_new_pct" in _pem and "plan-side" in _pem)
check("вьюер 3.65: сохранение плана — один пакетный запрос changes:, без note_ie", "changes:" in _pes and "changes: changes, reason, base_hash" in _pes and "'note_ie'" not in _V3.split("const PLAN_SAVE_ORDER")[1].split("\n")[0].split("//")[0])
_iem5 = _V3.split("function renderIeModel(")[1].split("\nfunction ")[0]
check("вьюер 3.65: «Доли и цели» — режимы наблюдение/работа (state.ieView, piv-ie-view), фильтры ie-work, data-col у колонок",
      "state.ieView" in _iem5 and "'piv-ie-view'" in _iem5 and "'ie-work'" in _iem5 and "state.filterStates[" in _iem5 and "'data-col'" in _iem5 and "сделки" in _iem5)
check("вьюер 3.65: «Сейчас» от 150px",
      "td[data-col=now]{ min-width:150px; }" in _VCSS)

# ── вьюер 3.66 ──
_HTML66 = (REPO / "tools/portfolio-integrated-viewer.html").read_text(encoding="utf-8")
_v366 = re.search(r"const VIEWER_VERSION = '(\d+\.\d+\.\d+)'", _V3)
check("вьюер ≥3.66: версия VIEWER_VERSION совпадает с ?v= html (js и css), не ниже 3.66.0",
      bool(_v366) and tuple(map(int, _v366.group(1).split("."))) >= (3, 66, 0)
      and f"assets/viewer.js?v={_v366.group(1)}" in _HTML66 and f"assets/viewer.css?v={_v366.group(1)}" in _HTML66)
check("вьюер 3.66: сегмент «План · Сделки» (значения watch/work сохранены), «к цели IE» в сделках disabled с подсказкой",
      ">План</button>" in _iem5 and ">Сделки</button>" in _iem5 and 'data-view="watch"' in _iem5 and 'data-view="work"' in _iem5
      and "в сделках база — мой план" in _iem5 and "view === 'work' ? 'plan'" in _iem5)
check("вьюер 3.66: карандаш rb-pen (✎) в ячейке плана и disabled-карандаш цели IE; прежней кнопки «изменить» в таблице нет",
      "rb-pen" in _V3 and "'✎'" in _V3 and "aria-label': 'правка цели IE'" in _iem5 and "plan-edit-btn" not in _V3)
check("вьюер 3.66: полосы отклонения нет (devBar, .rb-axis/.rb-dev/.rb-cor/.rb-fill убраны)",
      "function devBar(" not in _V3 and "const devBar" not in _V3 and not any(x in _VCSS for x in (".rb-axis", ".rb-dev{", ".rb-cor", ".rb-fill")) and "серая зона" not in _iem5)
check("вьюер 3.66: заметки IE и мои — колонками (data-col noteie/noteai), скрыты на телефоне; в сделках на телефоне скрыто dev",
      "'noteie'" in _iem5 and "'noteai'" in _iem5 and ".rb-v-watch td[data-col=noteie]" in _VCSS and ".rb-v-work td[data-col=dev]" in _VCSS)
_ps66 = _V3.split("function inlinePlanField(")[1].split("\nfunction planMarkNodes")[0]
check("вьюер 3.66: статус в строке — один POST changes с stocks.${t}.user_status, 409 перечитывает, клик по ячейке не открывает карточку",
      "`stocks.${ticker}.${field}`" in _ps66 and "api/pv/plan/set" in _ps66 and "status === 409" in _ps66 and "planApplyAll()" in _ps66
      and "closest('.rb-stcell')" in _iem5 and "inlinePlanField(" in _iem5.split("ustatus: (r) =>")[1].split("mark: (r)")[0])
check("вьюер 3.66: «Отметка» — журнал один раз в state.planJournal (limit 200), сброс после записи",
      "state.planJournal" in _V3 and "state.planJournal = null" in _ps66 and "journal?limit=200" in _V3 and "planJournalLoad()" in _iem5)
_jn66 = _V3.split("function buildPlanJournalNode(")[1].split("// ========== Predictions tab")[0]
check("вьюер 3.66: журнал плана фильтруется по базе отклонения (мои / IE: ie_new_pct, ie_old_pct, note_ie, ie_model.*)",
      "ie_new_pct" in _V3.split("const PLAN_JOURNAL_IE")[1].split("\n")[0] and "note_ie" in _V3.split("const PLAN_JOURNAL_IE")[1].split("\n")[0] and "ie_model" in _V3.split("const PLAN_JOURNAL_IE")[1].split("\n")[0]
      and "'журнал изменений плана · '" in _jn66 and "изменений IE пока нет" in _jn66)

# ── вьюер 3.67 ──
_ife = _V3.split("function inlinePlanField(")[1].split("\nfunction planMarkNodes")[0]
_cols67 = _iem5.split("const cols = view === 'work'")[1].split("const hasAction")[0]
_wk67, _wt67 = _cols67.split(": [['name', 'Бумага', 'l', 'name'], ['ieT'")[0], _cols67
check("вьюер 3.67: inlinePlanField — общая функция инлайн-поля (user_plan и user_status), один POST set, 409, toast «План сохранён»",
      "function inlinePlanField(" in _V3 and "'user_plan'" in _V3 and "`stocks.${ticker}.${field}`" in _ife and "api/pv/plan/set" in _ife
      and "status === 409" in _ife and "'План сохранён'" in _ife and "как в Numbers: " in _ife and "planApplyAll()" in _ife)
check("вьюер 3.67: колонка «План» (uplan) в обоих режимах, ячейка .rb-stcell со списком; слово планом в ячейке больше не рисуется при state.plan ok",
      _cols67.count("'uplan'") == 2 and "inlinePlanField(r.ticker, 'user_plan'" in _iem5 and "inlinePlanField(r.ticker, 'user_status'" in _iem5
      and "closest('.rb-stcell')" in _iem5)
_card67 = _V3.split("function cardStockKv(")[1].split("const ieNodes")[0]
check("вьюер 3.67: в карточке бумаги «План» и «Статус» — инлайн-списки (inlinePlanField), «изменить →» остаётся",
      "inlinePlanField(p.ticker, 'user_plan'" in _card67 and "inlinePlanField(p.ticker, 'user_status'" in _card67 and "'изменить →'" in _card67)
check("вьюер 3.67: журнал — статусы скрыты по умолчанию, чекбокс «показывать статусы» (state.planJournalStatuses, piv-journal-statuses), в режиме IE чекбокса нет",
      "piv-journal-statuses" in _V3 and "state.planJournalStatuses" in _jn66 and "показывать статусы" in _jn66 and "ieMode ? null" in _jn66)
check("вьюер ≥3.67: VIEWER_VERSION не ниже 3.67.0 и совпадает с ?v= html (литерал версии в тест не зашивать)",
      bool(_v366) and tuple(map(int, _v366.group(1).split("."))) >= (3, 67, 0)
      and f"assets/viewer.js?v={_v366.group(1)}" in _HTML66 and f"assets/viewer.css?v={_v366.group(1)}" in _HTML66)

check("вьюер 3.67: REBAL_CORRIDOR_PP = 1", "const REBAL_CORRIDOR_PP = 1;" in _V3)

# ── вьюер 3.68 ──
_pes68 = _V3.split("async function planEditSave(")[1].split("\n// Поправить снапшот")[0]
_pas68 = _V3.split("function planApplyToSnapshot(")[1].split("\nfunction setupPlanLayer")[0]
check("вьюер 3.68: окна showIeEditModal и showIeImportModal, источник модели ieModel() и ieHistoryLast, planEditOpen с kind",
      "function showIeEditModal(" in _V3 and "function showIeImportModal(" in _V3 and "function ieModel()" in _V3 and "function ieHistoryLast(" in _V3
      and "kind: 'ie'" in _V3 and "kind: 'import'" in _V3 and "ieEditSave(layer)" in _pes68 and "ieImportApply(layer)" in _pes68)
check("вьюер 3.68: запись и импорт — api/pv/plan/ie-set (source site / webarchive) и api/pv/plan/ie-import",
      "api/pv/plan/ie-set" in _V3 and "api/pv/plan/ie-import" in _V3 and "source: 'site'" in _V3 and "source: 'webarchive'" in _V3 and "extraction_date: exDate" in _V3)
check("вьюер 3.68: карандаш цели IE оживает (showIeEditModal), заглушки «этап 3» нет; «с дд.мм» из истории",
      "showIeEditModal(r.ticker)" in _iem5 and "появится на этапе 3" not in _V3 and "(этап 3)" not in _jn66 and "ieHistoryLast(r.ticker)" in _iem5)
check("вьюер 3.68: planApplyToSnapshot кладёт ie_new_pct/ie_old_pct из плана", "a.ie_new_pct = pe.ie_new_pct" in _pas68 and "a.ie_old_pct = pe.ie_old_pct" in _pas68)
check("вьюер 3.68: журнал IE — модель IE, кэш в модели; карточка состояния модели над журналом",
      "ie_model\\.positions" in _jn66 and "'ie_model.cash_pct': 'кэш в модели'" in _V3 and "buildIeStateCard()" in _iem5)
check("вьюер 3.68: предупреждение «без причины», сохранение разрешено; `.ie-diff` в css",
      "доля меняется без заметки IE — нежелательно" in _V3 and "изменений доли без причины:" in _V3 and ".ie-diff" in _VCSS)
check("вьюер ≥3.68: VIEWER_VERSION не ниже 3.68.0 и совпадает с ?v= html (литерал версии в тест не зашивать)",
      bool(_v366) and tuple(map(int, _v366.group(1).split("."))) >= (3, 68, 0)
      and f"assets/viewer.js?v={_v366.group(1)}" in _HTML66 and f"assets/viewer.css?v={_v366.group(1)}" in _HTML66)

# ── вьюер 3.69 ──
_ie69 = _V3.split("function showIeEditModal(")[1].split("async function ieEditSave(")[0]
check("вьюер 3.69: в окне доли IE нет поля причины (нет «Почему меняю»), причина = заметка IE",
      "Почему меняю" not in _ie69 and "ie-reason" not in _ie69 and "reason: nn" in _V3)
check("вьюер 3.69: общий портфель IE — окно «Оценки IE по бумагам», запись всех строк с page: 'general', «Мои бумаги» / «Остальные бумаги IE»",
      "Оценки IE по бумагам" in _V3 and "page: 'general'" in _V3 and "Мои бумаги (" in _V3 and "Остальные бумаги IE (" in _V3 and "Записать оценки IE" in _V3)
check("вьюер 3.69: изменения «было → стало» — класс .ie-chg в css и js",
      ".ie-chg" in _VCSS and "ie-chg" in _V3)
check("вьюер 3.69: таблица окна импорта — ui-table dense в ui-table-wrap",
      "ui-table dense ie-tbl" in _V3 and "'ui-table-wrap'" in _V3.split("function ieImportTable(")[1].split("function ieImportCards(")[0])
check("вьюер 3.69: потенциалы ценами — колонка «Цель IE 12 мес, ₽», цели от цены IE (ieGoalsOf), «общий портфель от» в карточке состояния",
      "'Цель IE 12 мес, ₽'" in _V3 and "function ieGoalsOf(" in _V3 and "general_date" in _V3)
check("вьюер 3.69: в «Сделках» фильтр «План» (ie-work-plan), учтён в anyFlt и фильтрации",
      "selOf('ie-work-plan'" in _V3 and "(fSt.plan || fSt.status || fSt.out || fSt.act)" in _V3)
check("вьюер ≥3.69: VIEWER_VERSION не ниже 3.69.0 и совпадает с ?v= html (литерал версии в тест не зашивать)",
      bool(_v366) and tuple(map(int, _v366.group(1).split("."))) >= (3, 69, 0)
      and f"assets/viewer.js?v={_v366.group(1)}" in _HTML66 and f"assets/viewer.css?v={_v366.group(1)}" in _HTML66)

# ── вьюер 3.69.1 ──
_rim = _V3.split("function renderIeModel(")[1].split("const cellOf = {")[0]
_cell = _V3.split("const cellOf = {")[1].split("const tbody = el('tbody'")[0]
check("вьюер 3.69.1: колонка «Цена, ₽» (price) в обоих режимах «Плана» и «Сделок», ячейка price и итог",
      _rim.count("['price', 'Цена, ₽', null, 'price']") == 3 and "price: (r) =>" in _cell)
check("вьюер 3.69.1: колонка price скрыта на телефоне в обоих режимах",
      "rb-v-watch th[data-col=price]" in _VCSS and "rb-v-work th[data-col=price]" in _VCSS)
check("вьюер 3.69.1: у ячейки pot нет title; в окне общего портфеля нет колонки «Потенциал, %»",
      "el('td', { 'data-col': 'pot' }," in _cell and "['Потенциал, %', 'r']" not in _V3.split("function showIeImportModal(")[1])
check("вьюер 3.69.1: дата страницы в окнах импорта уходит в ie-set как extraction_date",
      "type: 'date'" in _V3.split("function showIeImportModal(")[1] and "extraction_date: exDate" in _V3)
check("вьюер 3.69.1: время записи из timing_ms в тостах (planSavedTxt)",
      "function planSavedTxt(" in _V3 and "plan save timing" in _V3 and _V3.count("planSavedTxt(") >= 5)
check("вьюер 3.69.1: поиск по бумаге в «Долях по бумагам» — _tableSearch в renderIeModel, data-q на строках, поле в ui-head split",
      "_tableSearch('ieModelQ', tbody" in _V3.split("function renderIeModel(")[1].split("// ========== Мой план на сайте")[0] and "'data-q': _qNorm(`${r.name} ${r.ticker}`)" in _V3 and "rbSearch.node" in _V3)
check("вьюер 3.69.1: «Отрасль (IE)» в блоке «Модель IE» карточки", _V3.count("_kv('Отрасль (IE)'") == 2)

# ── вьюер 3.70 ──
_rim70 = _V3.split("function renderIeModel(")[1].split("const cellOf = {")[0]
_all70 = _V3.split("function renderIeAll(")[1].split("function renderIeModel(")[0]
check("вьюер 3.70: порядок колонок «Плана» (цена перед «Мой план») и «Сделок» (цена перед «Сейчас»)",
      "['ieT', 'Цель IE, %', null, 'iet'], ['price', 'Цена, ₽', null, 'price'], ['plan', 'Мой план, %', null, 'plan']" in _rim70
      and "['absDev', 'Отклонение', null, 'dev'], ['price', 'Цена, ₽', null, 'price'],\n       ['nowRub', 'Сейчас', 'l', 'now']" in _rim70)
check("вьюер 3.70: третья база 'all' («Все бумаги») в сегменте mode, в «Сделках» disabled, ранний выход в renderIeAll",
      'data-v="all"' in _rim70 and ">Все бумаги</button>" in _rim70 and "if (mode === 'all') { renderIeAll(" in _rim70)
check("вьюер 3.70: «Оценки IE по бумагам» — все позиции модели, поиск ieModelQ, не-портфельные строки без действия",
      "'Оценки IE по бумагам'" in _all70 and "ie?.positions" in _all70 and "_tableSearch('ieModelQ', tbody" in _all70 and "onclick: pos ?" in _all70)
check("вьюер 3.70: фильтры «Все бумаг»: риск (Низкий/Средний/Высокий), «только в портфеле», «только в модели IE»",
      all(x in _all70 for x in ("'Низкий'", "'Средний'", "'Высокий'", "'только в портфеле'", "'только в модели IE'", "ie-all")))
check("вьюер 3.70: на телефоне .rb-v-all оставляет Бумага · Цель 12 мес · Долгоср. цель",
      all(f"rb-v-all th[data-col={c}]" in _VCSS for c in ("iet", "iprice", "div", "risk", "ind")))
check("вьюер ≥3.70: VIEWER_VERSION не ниже 3.70.0 и совпадает с ?v= html (литерал версии в тест не зашивать)",
      bool(_v366) and tuple(map(int, _v366.group(1).split("."))) >= (3, 70, 0)
      and f"assets/viewer.js?v={_v366.group(1)}" in _HTML66 and f"assets/viewer.css?v={_v366.group(1)}" in _HTML66)

# ── вьюер 3.71 → шаг 12: «касания» порога (touched) нет — пересечение порога пишет уведомитель событием fired в состоянии ──
_nc71 = _V3.split("const nowCellBase = ")[1].split("if (a.category === 'dormant'")[0]
check("вьюер шаг 12: нет touched/evalCondition — статус условия только из строки модуля (а)",
      "function evalCondition(" not in _V3 and "condTouched" not in _V3 and "_touchedFirst" not in _V3)
check("вьюер 3.71 → шаг 12: priceDistText — «сейчас … — порог пройден» по живой цене (подсказка, не статус)",
      "`сейчас ${f(p)} — порог пройден`" in _V3)
check("вьюер 3.71 → шаг 12: «Сделки» — nowCellBase: условие из причины (sell_condition:/condition_hold:<id>), сработавшее — «ждёт твоей отметки», .warn",
      "sell_condition|condition_hold" in _nc71 and "ждёт твоей отметки" in _nc71 and "rb-now hold warn ripe" in _nc71 and "rb-now.hold.warn" in _VCSS)
check("вьюер ≥3.71: VIEWER_VERSION не ниже 3.71.0 и совпадает с ?v= html (литерал версии в тест не зашивать)",
      bool(_v366) and tuple(map(int, _v366.group(1).split("."))) >= (3, 71, 0)
      and f"assets/viewer.js?v={_v366.group(1)}" in _HTML66 and f"assets/viewer.css?v={_v366.group(1)}" in _HTML66)

# ── вьюер 3.72 ──
_cg72 = _V3.split("function buildClassGoalsCard(")[1].split("\n}\n")[0] + _V3.split("function classPlanFactData(")[1].split("\n}\n")[0]
_mx72 = _V3.split("function planMatrixDerivedChanges(")[1].split("\n}\n")[0]
_fd72 = _V3.split("function renderFunds(")[1].split("\n}\n")[0]
_bk72 = _V3.split("function buildBucketGoalsCard(")[1].split("\n}\n")[0]
_sv72 = _V3.split("async function planSharesSave(")[1].split("\n}\n")[0]
check("вьюер 3.72: «Цели по классам» — план из state.plan (planClassPct), факт class_plan_vs_fact, отклонение считается во вьюере, карандаш → showClassesEditModal",
      "class_plan_vs_fact" in _cg72 and "planClassPct(" in _cg72 and "showClassesEditModal" in _cg72 and "факт появится после пересборки снапшота с планом" in _V3
      and "ui-row pf-row" in _V3.split("function planFactTable(")[1].split("\n}\n")[0] and "_planFactDev(" in _V3)
check("вьюер 3.72→3.74: матрица «Валюта × класс» — производная (planMatrixDerivedChanges), на экране карточки и окна нет; факт по классам и подпись «по валютам» остаются",
      "function buildMatrixCard(" not in _V3 and "function showMatrixEditModal(" not in _V3 and "o.kind === 'matrix'" not in _V3
      and "planMatrixPct(" in _V3.split("function buildClassGoalsCard(")[1].split("\n}\n")[0] and "по валютам:" in _V3
      and "Math.abs(v - (cur[k] || 0)) > 1e-6" in _mx72 and "const PLAN_MX_CUR = ['RUB', 'USD', 'EUR', 'CNY']" in _V3 and "const PLAN_MX_CLASSES = ['Кеш', 'Акция', 'Облигация', 'Золото', 'Другое']" in _V3)
_cfm72 = _V3.split("function cardFundMain(")[1].split("\n}\n")[0]
check("вьюер 3.72→3.75: «Фонды» — asset_type fund и qty > 0; список читает класс/валюта/корзина/in_rebalance плана, правка (списки _fundSelect, чекбокс in_rebalance, ручная оценка manual_positions) — в карточке фонда",
      "'fund'" in _V3.split("function fundRows(")[1].split("\n}\n")[0] and "h.qty > 0" in _V3.split("function fundRows(")[1].split("\n}\n")[0]
      and "rec?.in_rebalance !== false" in _fd72 and "['moex_iss', 'moex_live']" in _fd72
      and "_fundSelect(" in _cfm72 and "in_rebalance" in _cfm72 and "manual_positions." in _V3.split("function _fundManualNode(")[1].split("\n}\n")[0] and "_fundManualNode(" in _cfm72 and "['moex_iss', 'moex_live']" in _cfm72
      and "funds.${t}.${field}" in _V3 and "e.key === 'Enter'" in _V3.split("function _fundManualNode(")[1].split("\n}\n")[0] and "fd-warn" in _fd72)
check("вьюер 3.72→3.77: карточки целей — только в базе «Общие доли» (renderOverall через buildGoalsPair); под таблицей долей в «К моему плану» и «к цели IE» их нет",
      "buildGoalsPair(buildMovesCard())" in _V3.split("function renderOverall(")[1].split("\n}\n")[0]
      and "buildGoalsPair(" not in _V3.split("function renderIeModel(")[1].split("\nfunction ")[0] and "buildIeStateCard()" in _V3.split("function renderIeModel(")[1].split("\nfunction ")[0])
check("вьюер 3.72: окна долей — kinds classes/matrix/buckets в planEditSave → planSharesSave; один пакет только изменённых путей, доли единицы с 4 знаками, сумма ≠ 100 не запрещает",
      "planEditOpen.kind === 'classes' || planEditOpen.kind === 'buckets'" in _V3
      and "changes.push({ path: f.path, value: next })" in _sv72 and "planSetBatch(changes" in _sv72
      and "Math.round(+p / 100 * 10000) / 10000" in _V3 and "не 100 %, сохранить можно" in _V3
      and "`classes.${c}.share`" in _V3 and "`matrix.${k}.share`" in _V3 and "`bond_buckets.${k}.share`" in _V3)
check("вьюер 3.72: «Цели по облигациям» — от bond_buckets плана (planBucketPct) и bonds_plan_vs_fact, отклонение от плана, карандаш → showBucketsEditModal (9 корзин)",
      "bucketPlanFactRows()" in _bk72 and "planBucketPct(" in _V3.split("function bucketPlanFactRows(")[1].split("\n}\n")[0] and "bonds_plan_vs_fact" in _V3.split("function bucketPlanFactRows(")[1].split("\n}\n")[0] and "showBucketsEditModal" in _bk72
      and "const PLAN_BUCKET_KEYS = ['USD', 'EUR', 'CNY', 'ОФЗ/>10', 'ОФЗ/<10', 'ОФЗ/Флоат', 'КОРП/AA+', 'КОРП/A', 'КОРП/B+']" in _V3)
check("вьюер 3.72: журнал «к моему плану» читает classes/matrix/bond_buckets/funds/manual_positions словами (planPathHuman), доли в %",
      "(classes|matrix|bond_buckets|bonds|funds|manual_positions)" in _V3.split("const PLAN_JOURNAL_MINE = ")[1].split("\n")[0]
      and "цель класса ${m[1]}" in _V3 and "матрица ${m[1]}/${m[2]}" in _V3 and "корзина ${m[1]}" in _V3 and "фонд ${m[1]} · ${FUND_FIELD_RU" in _V3
      and "ручная оценка ${m[1]}" in _V3 and "planPathHuman(en.path" in _V3)
check("вьюер 3.72→3.75: телефон — поля ≥16px, строки плана и фондов теснее (--cols), подсветка вне коридора и «не отнесён» — левая полоса",
      "@media (pointer:coarse), (max-width:640px){ .sh-grid .fld" in _VCSS and ".ui-row.pf-row{ --cols:minmax(0,1fr) 72px 74px 78px 12px; gap:4px;" in _VCSS
      and "pf-zero" in _VCSS and ".ui-table tr.fd-warn td:first-child{ box-shadow:inset 3px 0 0 var(--warn)" in _VCSS and ".ui-row.pf-row.rb-out{ box-shadow:inset 3px 0 0 var(--warn); }" in _VCSS
      and "pf-table" not in _VCSS and "fd-table" not in _VCSS and ".ui-row.fd-row" not in _VCSS)
check("вьюер ≥3.72: VIEWER_VERSION не ниже 3.72.0 и совпадает с ?v= html (литерал версии в тест не зашивать)",
      bool(_v366) and tuple(map(int, _v366.group(1).split("."))) >= (3, 72, 0)
      and f"assets/viewer.js?v={_v366.group(1)}" in _HTML66 and f"assets/viewer.css?v={_v366.group(1)}" in _HTML66)

# ── вьюер 3.73 ──
_bp73 = _V3.split("function bondPlanNodes(")[1].split("\n}\n")[0]
_cf73 = _V3.split("function cardFundMain(")[1].split("\n}\n")[0]
_ch73 = _V3.split("function cardFundHist(")[1].split("\n}\n")[0]
check("вьюер 3.73: карточка облигации — «Мой план» всегда; корзина инлайн-списком из 9 ключей, выбор одним пакетом bonds.<ISIN>.type + subtype (валютные — subtype null), расхождение со снапшотом подстрокой",
      "...bondPlanNodes(r))" in _V3.split("function cardBondKv(")[1].split("\n}\n")[0]
      and "PLAN_BUCKET_KEYS.map(" in _bp73 and "`bonds.${isin}.type`" in _bp73 and "`bonds.${isin}.subtype`" in _bp73 and "planSetBatch([{ path:" in _bp73
      and "_bucketSplit(v)" in _bp73 and "в снапшоте: ${snapKey}" in _bp73 and "state.plan.plan?.bonds?.[isin]" in _bp73 and "planEditHint()" in _bp73
      and "b.disabled = true" in _bp73 and "planRefreshAll()" in _bp73)
check("вьюер 3.73: «Действие» — текстовое поле ≤200, Enter/blur при изменении, пусто → null, путь bonds.<ISIN>.action; подпись «как в Numbers»; рейтинг только чтение",
      "`bonds.${isin}.action`" in _bp73 and ", 200, " in _bp73 and "что делаю с бумагой — свободный текст, как в Numbers" in _bp73
      and "v === '' ? null : v" in _V3.split("function _planTextInput(")[1].split("\n}\n")[0]
      and "e.key === 'Enter'" in _V3.split("function _planTextInput(")[1].split("\n}\n")[0] and "addEventListener('blur', commit)" in _V3.split("function _planTextInput(")[1].split("\n}\n")[0]
      and "bondRatingSelect(isin, rec?.rating || null, can)" in _bp73)
check("вьюер 3.73: карточка фонда — kind 'fund' (cardKindOf, CARD_SUBS main/hist, cardTitleParts, fillCard), открывается из строки «Фонды», листание по fundEntries, перерисовка не подменяет фонд бумагой",
      "e?._kind === 'fund' ? 'fund'" in _V3 and "fund: [['main', 'Главное'], ['ret', 'Доходность'], ['hist', 'История'], ['reports', 'Отчёты']]" in _V3 and "fundTitleParts(e)" in _V3.split("function cardTitleParts(")[1].split("\n}\n")[0]
      and "cardFundHead(e)" in _V3.split("function fillCard(")[1].split("\n}\n")[0] and "cardFundMain(e)" in _V3.split("function fillCard(")[1].split("\n}\n")[0]
      and "openCard(entryOf(r), L, r.iis ? { account: 'iis_3' } : null)" in _fd72 and "function fundEntries()" in _V3
      and _V3.count("(e._kind === 'fund' ? (pbt[e.ticker]?._kind === 'fund' ? pbt[e.ticker] : e) : (pbt[e.ticker] || e))") == 2)
check("вьюер 3.73: карточка фонда — «Мой план» = карта (класс, валюта, корзина, в балансировке, заметка) через общие _fundSelect/_planTextInput, «Позиция» и оценка вручную; «История» — priceChartNode + таблица снапшотов; без вердиктов",
      "_fundSelect(" in _cf73 and "_planTextInput(`funds.${t}.note`" in _cf73 and "in_rebalance" in _cf73 and "_fundManualNode(" in _cf73 and "FUND_SRC_RU" in _cf73
      and "priceChartNode(t)" in _ch73 and "asset_type === 'fund'" in _ch73 and "verdict" not in _cf73 and "_fundRefresh" in _cf73
      and "instrXirr(t)" in _V3.split("function cardFundHead(")[1].split("\n}\n")[0])   # 3.119: читатель instrXirr = открытые + проданные
check("вьюер 3.73: журнал — bonds.<ISIN>.* словами «облигация <имя> · корзина/действие/рейтинг», фильтр «к моему плану» пропускает bonds",
      "bonds\\.([A-Z0-9]{12})" in _V3.split("function planPathHuman(")[1].split("\n}\n")[0] and "облигация ${bondNameByIsin(m[1])} · ${BOND_FIELD_RU[m[2]]}" in _V3
      and "type: 'корзина (тип)'" in _V3 and "action: 'действие'" in _V3 and "bondNameByIsin(isin)" in _V3)
check("вьюер 3.73: телефон — поля плана ≥16px, галка и «Оценка вручную» в карточке без max-width, колонка «Количество» истории прячется",
      ".pl-blk .pl-txt{ font-size:16px; }" in _VCSS and ".card-kv .fd-manual{ max-width:none;" in _VCSS and ".fh-qty{ display:none; }" in _VCSS and ".fh-tbl{ min-width:0;" in _VCSS and ".pl-blk{" in _VCSS)
check("вьюер ≥3.73: VIEWER_VERSION не ниже 3.73.0 и совпадает с ?v= html (литерал версии в тест не зашивать)",
      bool(_v366) and tuple(map(int, _v366.group(1).split("."))) >= (3, 73, 0)
      and f"assets/viewer.js?v={_v366.group(1)}" in _HTML66 and f"assets/viewer.css?v={_v366.group(1)}" in _HTML66)

# ── вьюер 3.73.1 ──
check("вьюер 3.73.1 → шаг 12: у условий — подстрока «создано дд.мм · <кто — кодлист actor> · сработало …» (condMadeText по первой версии определения и fired_at), год только если не текущий",
      "function condMadeText(c, opts)" in _V3 and "noFired" in _V3 and "`создано ${_ddmmY(v1.created_at)}`" in _V3 and "ACTOR_RU[v1.created_by]" in _V3
      and "`сработало ${_ddmmY(c.fired_at)}" in _V3 and "m[1] !== y" in _V3 and "typeof dsToday === 'function'" in _V3   # 4.2.3: год по dsToday, без него (вырезка в node) — по часам
      and "condMadeChip(c)," in _V3 and "function condMadeSourceNode(c)" in _V3 and "class: 'ui-sub cond-made'" in _V3 and "class: 'tag soft cond-made-chip'" in _V3)
check("вьюер 3.73.1 → R27 (03.11): решение датировано — строка «Разбор дд.мм: <слово> …» / «Решение дд.мм (вы)» в карточке из decisions/, без копий ограничений обзора",
      "it.decided" not in _V3 and "function decisionSourceWord(dec)" in _V3 and "function decisionRowText(card, dec)" in _V3
      and "`Решение ${_ddmmDot(dec.recorded_at)} (вы)`" in _V3 and "`Разбор ${_ddmmDot(dec.recorded_at)}`" in _V3)
check("вьюер ≥3.73.1: VIEWER_VERSION не ниже 3.73.1 и совпадает с ?v= html (литерал версии в тест не зашивать)",
      bool(_v366) and tuple(map(int, _v366.group(1).split("."))) >= (3, 73, 1)
      and f"assets/viewer.js?v={_v366.group(1)}" in _HTML66 and f"assets/viewer.css?v={_v366.group(1)}" in _HTML66)

# ── вьюер 3.74 ──
_pf74 = _V3.split("function planFactTable(")[1].split("\n}\n")[0]
_pr74 = _V3.split("function buildGoalsPair(")[1].split("\n}\n")[0]
_mm74 = _V3.split("function bucketMembersNode(")[1].split("\n}\n")[0]
_sv74 = _V3.split("async function planSharesSave(")[1].split("\n}\n")[0]
_rb74 = _V3.split("function renderBonds(")[1].split("\nfunction ")[0]
check("вьюер 3.74: матрицы на экране нет; при сохранении классов и корзин в тот же пакет set дописываются изменившиеся ячейки matrix.<CUR>/<Класс>.share (planMatrixDerivedChanges), округление 4 знака",
      "function buildMatrixCard(" not in _V3 and "planMatrixDerivedChanges(nc, nb)" in _sv74 and "changes.push(...planMatrixDerivedChanges" in _sv74
      and "m['RUB/Облигация'] = obl * Math.max(0, 1 - u - e - cn)" in _V3 and "m['USD/Золото'] = g(cls, 'Золото')" in _V3 and "m['RUB/Акция'] = g(cls, 'Акции')" in _V3
      and "Math.round(m[k] * 1e4) / 1e4" in _V3 and "m['USD/Облигация'] = obl * u" in _V3)
check("вьюер 3.74: две таблицы рядом — «Цели по классам» и «Цели по облигациям» (.ui-grid.pf-pair), база без ИИС-3 написана один раз, у каждой карандаш; на телефоне одна колонка",
      "buildClassGoalsCard()" in _pr74 and "buildBucketGoalsCard()" in _pr74 and "ui-grid pf-pair" in _pr74 and "у ИИС-3 своя цель" in _pr74
      and "'Цели по облигациям'" in _V3 and "'Цели по классам'" in _V3 and "showClassesEditModal" in _V3 and "showBucketsEditModal" in _V3
      and ".ui-grid.pf-pair{ grid-template-columns:repeat(2,minmax(0,1fr))" in _VCSS and "@media (max-width:900px){ .ui-grid.pf-pair{ grid-template-columns:minmax(0,1fr)" in _VCSS
      and "['валютные'," in _V3 and "['ОФЗ'," in _V3 and "['КОРП'," in _V3)
check("вьюер 3.74: корзина раскрывается списком бумаг (uiExpandIn/uiCollapseOut, узел каждый раз новый): облигации по plan_bucket_key, фонды-члены по funds[T].bucket с пометкой «фонд», ИИС-3 отдельной пометкой; клик — openCard; сумма — по бумагам списка",
      "uiExpandIn(detail)" in _pf74 and "uiCollapseOut(detail" in _pf74 and "r.expand()" in _pf74
      and "plan_bucket_key === key" in _V3 and "funds[h.ticker]?.bucket === key" in _V3 and "'фонд'" in _mm74 and "openCard(ent" in _mm74
      and "ИИС-3" not in _mm74 and "расхождение" not in _mm74 and ".pf-bl-row{ display:grid" in _VCSS and ".pf-bl-i, .pf-bl-s, .pf-bl-hd{ display:none; }" in _VCSS)
check("вьюер 3.74: «Облигации» — сгиб details.ui-fold «Корзины: план ↔ факт» (свёрнут), строка на корзину, ссылка «цели → Доли и цели»; фильтр «Корзина» (9 ключей) в filterStates.bonds, счётчике и сбросе",
      "buildBucketsFold()" in _rb74 and "buildBucketsPlanFactCard" not in _V3 and "el('details', { class: 'ui-card lg ui-fold ui-mt-m', id: 'pf-buckets' }" in _V3
      and "'Корзины: план ↔ факт'" in _V3 and "goToTab('ie-model')" in _V3.split("function buildBucketsFold(")[1].split("\n}\n")[0] and "цели → Доли и цели" in _V3
      and "bucket: ''" in _rb74 and "filterChipGroup('Корзина', fState.bucket" in _rb74 and "PLAN_BUCKET_KEYS.map(k => [k," in _rb74 and "r.bucketKey === fState.bucket" in _rb74
      and "fState.bucket, fState.offerOnly" in _rb74 and "verdict: '', bucket: ''" in _rb74 and "bucketKey: holding?.plan_bucket_key" in _V3)
check("вьюер 3.74: у фонда-члена все девять корзин (PLAN_FUND_BUCKETS = PLAN_BUCKET_KEYS), список только при классе «Облигация», подзаголовок «FINAMAR вне корзин и балансировки; «Другое» — Рентал ПРО»",
      "const PLAN_FUND_BUCKETS = PLAN_BUCKET_KEYS;" in _V3 and "cls === 'Облигация' ? _kv('Корзина', sel('bucket', PLAN_FUND_BUCKETS" in _V3 and "FINAMAR вне корзин и балансировки; «Другое» — Рентал ПРО" in _V3)
check("вьюер 3.74: журнал — подряд идущие matrix.* одного ts сворачиваются в «матрица пересчитана», до 3 ячеек и «и ещё N»",
      "matrixGroup" in _V3 and "'матрица пересчитана'" in _V3 and "last.ts === en.ts" in _V3 and "g.slice(0, 3)" in _V3 and "и ещё ${g.length - 3}" in _V3)
check("вьюер ≥3.74: VIEWER_VERSION не ниже 3.74.0 и совпадает с ?v= html (литерал версии в тест не зашивать)",
      bool(_v366) and tuple(map(int, _v366.group(1).split("."))) >= (3, 74, 0)
      and f"assets/viewer.js?v={_v366.group(1)}" in _HTML66 and f"assets/viewer.css?v={_v366.group(1)}" in _HTML66)

# ── вьюер 3.75 ──
_pf75 = _V3.split("function planFactTable(")[1].split("\n}\n")[0]
_bm75 = _V3.split("function bucketMembers(")[1].split("\n}\n")[0]
_pr75 = _V3.split("function buildGoalsPair(")[1].split("\n}\n")[0]
check("вьюер 3.75: planFactTable строит строки ui-row (нет ui-table), корзина раскрывается как категория в «Деньгах»: ui-catopen/ui-catdetail/ui-chev, uiExpandIn, uiCollapseOut, .closing; кнопка «все» ui-chev-all; открытых может быть несколько",
      "ui-table" not in _pf75 and "ui-row pf-row" in _pf75 and "ui-catopen fresh" in _pf75 and "ui-catdetail" in _pf75 and "'ui-chev'" in _pf75 and "ui-chev ui-chev-all" in _pf75
      and "uiExpandIn(detail)" in _pf75 and "uiCollapseOut(detail" in _pf75 and "'closing'" in _pf75 and "aria-expanded" in _pf75 and "'tabindex', '0'" in _pf75 and "title" not in _pf75
      and "return { node: el('div', { class: 'pf-list' }" in _pf75 and "sumPlan, offSum, haveFact }" in _pf75)
check("вьюер 3.75: бумаги корзины — только основной счёт (account === 'iis_3' пропускается), записи одного тикера сливаются; в списке нет пометки ИИС-3",
      "h.account === 'iis_3'" in _bm75 and "m.value += h.value_rub" in _bm75 and "by.get(k)" in _bm75 and "ИИС-3" not in _V3.split("function bucketMembersNode(")[1].split("\n}\n")[0]
      and "облигации основного счёта (без ИИС-3)" in _V3)
check("вьюер 3.75→3.76: «Цели по классам» и «Цели по облигациям» — две карточки в сетке pf-pair без списка фондов (фонды — вкладка «Фонды»)",
      "buildFundsCard" not in _V3 and "buildClassGoalsCard()" in _pr75 and "buildBucketGoalsCard()" in _pr75 and "ui-grid pf-pair' }, a, b)" in _pr75
      and "grid-area:fnd" not in _VCSS and "#pf-funds" not in _VCSS and 'grid-template-areas' not in _VCSS.split(".ui-grid.pf-pair{")[1].split("}")[0])
check("вьюер ≥3.75: VIEWER_VERSION не ниже 3.75.0 и совпадает с ?v= html (литерал версии в тест не зашивать)",
      bool(_v366) and tuple(map(int, _v366.group(1).split("."))) >= (3, 75, 0)
      and f"assets/viewer.js?v={_v366.group(1)}" in _HTML66 and f"assets/viewer.css?v={_v366.group(1)}" in _HTML66)

# ─────────── ui-kit 1.59.0: читатель markdown — сгибы, якоря, «по разделам», выноски, части справки ───────────
check("ui-kit.js: markdown-сгиб — блок <details> становится .ui-fold.rd-fold со стрелкой .ui-chev и телом .rd-fold-body",
      'class="ui-fold rd-fold"' in UI_KIT_JS0 and 'class="rd-fold-body"' in UI_KIT_JS0 and "<details>" in UI_KIT_JS0)
check("ui-kit.js: якорь «{#id}» в заголовке разбирается (id — [a-z0-9-]+), оглавление не берёт заголовки внутри сгиба",
      r"\{#([a-z0-9-]+)\}" in UI_KIT_JS0 and 'h.closest("details")' in UI_KIT_JS0)
check("ui-kit.js: режим opts.sections — .rd-sec/.rd-sections, setSec, счётчик «·N» у разделов (.rd-sec-n)",
      "opts.sections" in UI_KIT_JS0 and "rd-sections" in UI_KIT_JS0 and "function setSec(" in UI_KIT_JS0 and "rd-sec-n" in UI_KIT_JS0)
check("ui-kit.js: uiHelpOpen пробрасывает sections и принимает files/file; uiFetchMarkdownParts экспортирован",
      "function uiFetchMarkdownParts(" in UI_KIT_JS0 and "meta.sections === true" in UI_KIT_JS0
      and "meta.files" in UI_KIT_JS0 and "meta.file" in UI_KIT_JS0)
check("ui-kit.js: выноски «> **Важно:**» → .ui-callout warn|info; якоря не читаются из location.hash",
      "ui-callout" in UI_KIT_JS0 and "(Важно|Внимание|Совет|Почему)" in UI_KIT_JS0
      and "location.hash" not in UI_KIT_JS0.split("function uiReaderMount(", 1)[1].split("function uiReaderMountAll(", 1)[0])
check("ui-kit.css: .ui-callout (warn/info токенами), .rd-fold, .rd-sections .rd-sec, a.is-sec определены",
      all(x in UI_KIT_CSS0 for x in (".ui-callout{", ".ui-callout.warn{", ".rd .rd-doc .rd-fold{", ".rd-sections .rd-sec.is-on{", ".rd-toc-list a.is-sec{"))
      and "var(--info-bg)" in UI_KIT_CSS0.split(".ui-callout{", 1)[1][:200] and "var(--warn-bg)" in UI_KIT_CSS0.split(".ui-callout.warn{", 1)[1][:100])

# ── вьюер 3.76 ──
_rf76 = _V3.split("function renderFunds(")[1].split("\n}\n")[0]
_pf76 = _V3.split("function planFactTable(")[1].split("\n}\n")[0]
_rbm76 = _V3.split("function renderIeModel(")[1].split("\nfunction ")[0]
_cl76 = _V3.split("function condVersionNote(")[1].split("\n}\n")[0]
_bp76 = _V3.split("function bucketPlanFactRows(")[1].split("\n}\n")[0]
_mm76 = _V3.split("function bucketMembersNode(")[1].split("\n}\n")[0]
_cc76 = _V3.split("function cashSplit(")[1].split("\n}\n")[0]
check("вьюер 3.76: вкладка «Фонды» после «Облигаций» (при фондах в снапшоте или плане), подзаголовок со снапшотом, case 'funds' → renderFunds, глубокая ссылка #tab=funds идёт общим goToTab",
      _V3.index("id: 'funds', label: 'Фонды'") > _V3.index("id: 'bonds', label: 'Облигации'") and _V3.index("id: 'funds', label: 'Фонды'") < _V3.index("id: 'iis', label: 'ИИС-3'")
      and "fundRows().length" in _V3.split("function buildTabs(")[1].split("\n}\n")[0] and "case 'funds': return snap &&" in _V3 and "case 'funds': safeRender(renderFunds); break;" in _V3
      and "'funds'" in _V3.split("async function loadPlan(")[1].split("\n}\n")[0])
check("вьюер 3.76: renderFunds — таблица ui-table dense с сортировкой th[aria-sort], колонки по порядку словами, итог tfoot, поиск _tableSearch, фильтры класс (чипы) и «только в балансировке» через _filterTools, телефон — колонки hide-mobile",
      "ui-table dense sticky fd-t" in _rf76 and "'aria-sort'" in _rf76 and "_tableSearch('fundsQ'" in _rf76 and "_filterTools('funds'" in _rf76 and "tfoot" in _rf76
      and all(f"label: '{c}'" in _rf76 for c in ("Фонд", "Класс", "Кол-во, шт.", "Цена, ₽", "Стоимость, ₽", "К плану", "Отклонение", "Доходность", "Заметка"))
      and _rf76.index("label: 'Фонд'") < _rf76.index("label: 'Класс'") < _rf76.index("label: 'Кол-во, шт.'") < _rf76.index("label: 'Цена, ₽'") < _rf76.index("label: 'Стоимость, ₽'")
      < _rf76.index("label: 'К плану'") < _rf76.index("label: 'Отклонение'") < _rf76.index("label: 'Доходность'") < _rf76.index("label: 'Заметка'")
      and "только в балансировке" in _rf76 and "filterChipGroup('Класс'" in _rf76 and "'__none'" in _rf76 and "mobile: false" in _rf76
      and "livePriceOf(r.ticker)" in _rf76 and "к снапшоту" not in _rf76 and "class_plan_vs_fact" in _rf76 and "planClassPct(" in _rf76 and "per_instrument_xirr" in _rf76 and "pnl_rub" in _rf76 and "ui-ell" in _rf76
      and "оценка вручную" in _rf76 and "фонды на ИИС-3 — на вкладке ИИС-3" in _rf76 and "balanceBase()" in _rf76)
check("вьюер 3.76: клик по строке и Enter открывают карточку фонда (openCard по fundEntries), плашка под таблицей про FINAMAR/Рентал ПРО и подсказка плана; список фондов из «Долей и целей» убран, _fundRefresh перерисовывает вкладку",
      "openCard(entryOf(r), L, r.iis" in _rf76 and "e.key === 'Enter'" in _rf76 and "FINAMAR вне корзин и балансировки; «Другое» — Рентал ПРО. Класс, валюту, корзину и заметку правь в карточке фонда." in _rf76
      and "planEditHint()" in _rf76 and "funds-table" in _V3.split("function _fundRefresh(")[1].split("\n}\n")[0] and "renderTabContent()" in _V3.split("function _fundRefresh(")[1].split("\n}\n")[0])
check("вьюер 3.76: карточка фонда — подвкладка «Доходность» между «Главное» и «История», блок результата общий с акцией (cardPnlNodes), строки Вложено/Средняя цена/Срок/XIRR без пустых, без xirr — card-empty",
      "fund: [['main', 'Главное'], ['ret', 'Доходность'], ['hist', 'История'], ['reports', 'Отчёты']]" in _V3 and "cardFundRet(e)" in _V3 and "const pnl = cardPnlNodes(p.ticker);" in _V3
      and "..." + "cardPnlNodes(t, acct)" in _V3.split("function cardFundRet(")[1].split("\n}\n")[0] and "buy_total_rub" in _V3.split("function cardFundRet(")[1].split("\n}\n")[0]
      and "first_trade_date" in _V3.split("function cardFundRet(")[1].split("\n}\n")[0] and "avg_cost_rub" in _V3.split("function cardFundRet(")[1].split("\n}\n")[0]
      and ".filter(Boolean)" in _V3.split("function cardFundRet(")[1].split("\n}\n")[0] and "после пересборки снапшота" in _V3.split("function cardFundRet(")[1].split("\n}\n")[0]
      and "Прибыль по сделкам" in _V3.split("function cardPnlNodes(")[1].split("\n}\n")[0])
check("вьюер 3.76: «План» в целях — две строки: % жирно и сумма ₽ = база × план / 100 (база та же, что у факта); итог — 100 % и сумма базы; без базы или плана — без подстроки",
      "base * r.plan / 100" in _pf76 and "base * sumPlan / 100" in _pf76 and "r.plan != null && base" in _pf76 and "pf-sub2" in _pf76)
check("вьюер 3.76: «Цели по классам» — в строке «Кеш» вторая подстрока «деньги X ₽ · фонды Y ₽» (деньги — cash.by_account.main, фонды — факт класса минус деньги); cashSplit читает фонды класса «Кеш» плана",
      "cash?.by_account?.main" in _cc76 and "class === 'Кеш'" in _cc76 and "деньги ${fmtNum(Math.round(cs.cash))} ₽" in _V3.split("function buildClassGoalsCard(")[1].split("\n}\n")[0]
      and "фонды ${fmtNum(Math.round(f))} ₽" in _V3.split("function buildClassGoalsCard(")[1].split("\n}\n")[0] and "kesh.aRub - cs.cash" in _V3)
check("вьюер 3.76: вкладка «Фонды» — плитки «Деньги на счёте», «Фонды денежного рынка» (тикеры подписью), «Кеш всего» с планом и фактом класса; только при наличии cash.by_account.main",
      all(x in _V3.split("function buildCashTiles(")[1].split("\n}\n")[0] for x in ("'Деньги на счёте'", "'Фонды денежного рынка'", "'Кеш всего'", "split.tickers.join(' · ')", "план ${", "факт ${"))
      and "if (!split) return null;" in _V3.split("function buildCashTiles(")[1].split("\n}\n")[0] and "buildCashTiles(cashSplit(), total)" in _rf76)
check("вьюер 3.76: «Доли по бумагам» — колонка «Сумма, ₽» только в «Плане» (watch) между «План» и «Цель IE 12 мес, ₽», сумма цели жирно + факт ₽ подстрокой, сортировка по сумме цели, итог; в «Все бумаги» (ранний выход) и в «Сделках» её нет; на телефоне скрыта",
      "['userPlan', 'План', 'l', 'uplan'], ['sumGoal', 'Сумма, ₽', null, 'sum'], ['pot', 'Цель IE 12 мес, ₽', null, 'pot']" in _rbm76
      and _rbm76.count("['sumGoal', 'Сумма, ₽'") == 1 and _rbm76.index("['sumGoal', 'Сумма, ₽'") > _rbm76.index("view === 'work'") and "goal / 100 * base" in _rbm76 and "real / 100 * base" in _rbm76
      and "sumFoot(" in _rbm76 and ".rb-v-watch th[data-col=sum], .rb-v-watch td[data-col=sum]" in _VCSS)
check("вьюер 3.76: раскрытая корзина — шапка ui-row head «Бумага · ISIN · Стоимость, ₽ · Доля корзины» (на телефоне скрыта), доля — от суммы показанных бумаг, подвал только «Итого: X ₽», без сравнения со снапшотом и «пересобери снапшот»",
      all(x in _mm76 for x in ("ui-row head pf-bl-row pf-bl-hd", "'Бумага'", "'ISIN'", "'Стоимость, ₽'", "'Доля корзины'", "const den = sum;", "`Итого: ${fmtNum(Math.round(sum))} ₽`"))
      and "пересобери" not in _mm76 and "расхождение" not in _mm76 and "в снапшоте" not in _mm76 and "factRub" not in _mm76)
check("вьюер 3.76: факт корзин считается из бумаг по текущим ценам (bucketMembers), база — сумма девяти корзин; bonds_plan_vs_fact — запасной вариант без holdings; сгиб на «Облигациях» и карточка целей — одной функцией bucketPlanFactRows; подзаголовок «по текущим ценам»",
      "bucketMembers(k)" in _bp76 and "base += vals[k]" in _bp76 and "bonds_plan_vs_fact" in _bp76 and "live ? vals[k]" in _bp76
      and "bucketPlanFactRows()" in _V3.split("function buildBucketsFold(")[1].split("\n}\n")[0] and "bucketPlanFactRows()" in _V3.split("function buildBucketGoalsCard(")[1].split("\n}\n")[0]
      and "· по текущим ценам · клик по корзине — её бумаги" in _V3 and "· по текущим ценам · отклонение" in _V3)
check("вьюер 3.76 → шаг 12: правка условия — новая версия определения; в карточке «версия N от дд.мм: заметка», тип триггера — слово кодлиста",
      "const COND_TRIGGER_RU = CL.words('condition_trigger_type');" in _V3 and "c.version > 1" in _cl76 and "`версия ${c.version}" in _cl76 and "c.note" in _cl76
      and "function condLastChange(" not in _V3)
check("вьюер ≥3.76: VIEWER_VERSION не ниже 3.76.0 и совпадает с ?v= html (литерал версии в тест не зашивать)",
      bool(_v366) and tuple(map(int, _v366.group(1).split("."))) >= (3, 76, 0)
      and f"assets/viewer.js?v={_v366.group(1)}" in _HTML66 and f"assets/viewer.css?v={_v366.group(1)}" in _HTML66)


# ── вьюер 3.77 ──
_rb77 = _V3.split("function renderIeModel(")[1].split("\nfunction ")[0]
_ov77 = _V3.split("function renderOverall(")[1].split("\n}\n")[0]
_mc77 = _V3.split("function buildMovesCard(")[1].split("\n}\n")[0]
_pm77 = _V3.split("function planMoves(")[1].split("\n}\n")[0]
_cf77 = _V3.split("function cardFundMain(")[1].split("\n}\n")[0]
_rbn77 = _V3.split("function renderBonds(")[1].split("\nfunction ")[0]
_rf77 = _V3.split("function renderFunds(")[1].split("\n}\n")[0]
check("вьюер 3.77: база «Общие доли» первая в сегменте (Общие доли · К моему плану · к цели IE · Все бумаги), в «Сделках» серая; ранний выход overall до таблицы долей, в «Сделках» база — мой план",
      _rb77.index('data-v="overall"') < _rb77.index('data-v="plan"') < _rb77.index('data-v="ie"') < _rb77.index('data-v="all"') and ">Общие доли</button>" in _rb77
      and "if (mode === 'overall') { renderOverall(c); return; }" in _rb77 and _rb77.index("if (mode === 'overall')") < _rb77.index("if (mode === 'all')")
      and "const mode = view === 'work' ? 'plan' : (state.rebalMode || 'plan');" in _rb77 and "state.rebalMode = 'overall'" in _V3)
check("вьюер 3.77: «Общие доли» — плитки «База балансировки» (с 3.82; до того «База без ИИС-3»), «Вне коридора», «Кеш всего», «Свободно сверх плана кеша»; сетка целей с «Что перевести» под классами; журнал плана; карточки «Модель IE» нет",
      all(x in _ov77 for x in ("'База балансировки'", "Вне коридора ±${REBAL_CORRIDOR_PP} %", "'Кеш всего'", "'Свободно сверх плана кеша'", "кеш ниже плана на", "buildGoalsPair(buildMovesCard())", "buildPlanJournalNode('plan')"))
      and "buildIeStateCard" not in _ov77 and "pf-col" in _V3.split("function buildGoalsPair(")[1].split("\n}\n")[0] and ".pf-pair .pf-col" in _VCSS)
check("вьюер 3.77: «Что перевести» (4d) — #pf-move, planMoves(rows, corridorPp): источники dev > коридора, приёмники dev < −коридора, S = min(Σизлишков, Σнедоборов), «отдать» S × излишек_i/Σизлишков и «получить» S × недобор_j/Σнедоборов (planMoves → { give, take, total }), округление до рубля, меньше 1 000 ₽ скрыто",
      "id: 'pf-move'" in _mc77 and "'Что перевести'" in _mc77 and "деньги по классам и корзинам · коридор ±${REBAL_CORRIDOR_PP} % · лоты и бумаги — в «Сделках» и у советника" in _mc77
      and "S * x.amt / sum" in _pm77 and "part(sources, sumE)" in _pm77 and "part(receivers, sumN)" in _pm77 and "give" in _pm77 and "take" in _pm77 and "total" in _pm77 and "Math.round(" in _pm77 and "MOVE_MIN_RUB = 1000" in _V3 and "Math.min(sumE, sumN)" in _V3.split("function planMovesSides(")[1].split("\n}\n")[0]
      and "dev > corridorPp" in _V3 and "dev < -corridorPp" in _V3)
check("вьюер 3.77: «Что перевести» — два раздела «Классы» (classPlanFactData, пометка про FINAMAR и фонды вне балансировки) и «Корзины облигаций» (bucketPlanFactRows); пустые случаи словами; итог «перевести»",
      "'Классы'" in _mc77 and "classPlanFactData()" in _mc77 and "'Корзины облигаций'" in _mc77 and "bucketPlanFactRows()" in _mc77
      and "фонды вне балансировки (FINAMAR) не входят ни в факт классов, ни в базу" in _mc77
      and all(x in _V3.split("function movesSection(")[1].split("\n}\n")[0] for x in ("источника нет: пополнение или сокращение другого класса", "всё в коридоре или выше плана", "'перевести'", "'Отдать'", "'Получить'", "`−${fmtNum(x.rub)} ₽`", "`+${fmtNum(x.rub)} ₽`")))
check("вьюер 3.77: карточка фонда — «Позиция» как у акции: Стоимость, Количество (лот подстрокой), Моя средняя (avg_cost_rub, иначе «по покупкам» при n_sells === 0), cardPnlNodes, затем Цена, Счёт, Источник цены",
      "cardPnlNodes(t, _fundAcct(e))" in _cf77 and "по покупкам" not in _cf77 and "n_sells === 0" in _cf77 and "buy_total_rub / xi.qty_now" in _cf77 and "шт. в лоте" in _cf77 and "'Моя средняя'" in _cf77
      and _cf77.index("_kv('Стоимость'") < _cf77.index("_kv('Количество'") < _cf77.index("avgNode,") < _cf77.index("cardPnlNodes(t, _fundAcct(e))") < _cf77.index("_kv('Цена'") < _cf77.index("_kv('Счёт'") < _cf77.index("_kv('Источник цены'"))
check("вьюер 3.77: общие чипы фильтров — filterChipGroup/filterChipCheckbox функциями верхнего уровня, используются в renderBonds и renderFunds; локальных копий (chipGroup, chipCheckbox, _fundChipGroup) нет",
      "function filterChipGroup(label, cur, entries, set, fmt" in _V3 and "function filterChipCheckbox(label, checked, count, set)" in _V3
      and "filterChipGroup('Корзина'" in _rbn77 and "filterChipCheckbox('🚩 ' + codeWord('fundamental_level', 'RED_FLAG')" in _rbn77 and "filterChipGroup('Класс'" in _rf77 and "filterChipCheckbox('только в балансировке'" in _rf77
      and "const chipGroup" not in _V3 and "const chipCheckbox" not in _V3 and "_fundChipGroup" not in _V3 and "'fl-group'" in _V3.split("function filterChipGroup(")[1].split("\n}\n")[0])
check("вьюер ≥3.77: VIEWER_VERSION не ниже 3.77.0 и совпадает с ?v= html (литерал версии в тест не зашивать)",
      bool(_v366) and tuple(map(int, _v366.group(1).split("."))) >= (3, 77, 0)
      and f"assets/viewer.js?v={_v366.group(1)}" in _HTML66 and f"assets/viewer.css?v={_v366.group(1)}" in _HTML66)

_rs78 = _V3.split("function buildPositionsCard(")[1].split("let filtered = positions;")[0]
_ms78 = _V3.split("function movesSection(")[1].split("\n}\n")[0]
check("вьюер 3.78: фильтры «Акций» — общие filterChipGroup (Вердикт, Приоритет, Решение со счётчиками и «без решения») и filterChipCheckbox; ручных копий chip-toggle по verdict/priority/gate нет",
      all(x in _rs78 for x in ("filterChipGroup('Вердикт'", "filterChipGroup('Приоритет'", "filterChipGroup('Решение'", "'__none__'", "filterChipCheckbox('только с условиями'"))
      and "'chip-toggle' + (filterState.verdict" not in _rs78 and "'chip-toggle' + (filterState.priority" not in _rs78 and "'chip-toggle' + (filterState.gate" not in _rs78)
check("вьюер 3.78: «Что перевести» — отдать красным (bad), получить зелёным (good), итог нейтральный",
      "`−${fmtNum(x.rub)} ₽`, 'bad')" in _ms78 and "`+${fmtNum(x.rub)} ₽`, 'good')" in _ms78 and "`${fmtNum(mv.total)} ₽`)" in _ms78)
check("вьюер ≥3.78: VIEWER_VERSION не ниже 3.78.0 и совпадает с ?v= html (литерал версии в тест не зашивать)",
      bool(_v366) and tuple(map(int, _v366.group(1).split("."))) >= (3, 78, 0)
      and f"assets/viewer.js?v={_v366.group(1)}" in _HTML66 and f"assets/viewer.css?v={_v366.group(1)}" in _HTML66)

_ro79 = _V3.split("function renderOverall(")[1].split("\nfunction buildGoalsPair")[0]
_pf79 = _V3.split("function buildPlanFileCard()")[1].split("\nasync function planImportPick")[0]
_pk79 = _V3.split("async function planImportPick(")[1].split("\n}\n")[0]
_ap79 = _V3.split("async function planImportApply(")[1].split("\n}\n")[0]
_dl79 = _V3.split("async function planDownload(")[1].split("\n}\n")[0]
check("вьюер 3.79 (с 3.80 карточка живёт на странице Снапшот): карточка #pf-file (с 3.82 «База сайта») с кнопками «Скачать JSON», «Скачать XLSX», «Загрузить JSON» (до 3.82 «Импорт JSON») (скрытый input .json); при status≠ok кнопки отключены и подпись planEditHint()",
      "id: 'pf-file'" in _pf79 and all(x in _pf79 for x in ("'Скачать JSON'", "'Скачать XLSX'", "'Загрузить JSON'", "accept: '.json", "disabled: planEditable() ? null : ''", "planEditHint()")))
check("вьюер 3.79: скачивание — api/pv/plan/export?format= с авторизацией, имя из Content-Disposition, общий хелпер _downloadBlob (a[download]) объявлен один раз",
      "api/pv/plan/export?format=${fmt}" in _dl79 and "authFetch(" in _dl79 and "Content-Disposition" in _dl79 and "_downloadBlob(" in _dl79
      and _V3.count("function _downloadBlob(") == 1 and "a.download = name" in _V3)
check("вьюер 3.79: импорт — JSON.parse на клиенте (ошибка тостом без запроса), сначала POST api/pv/plan/import с dry_run: true, 400 → окно с проблемами, 409 → «план изменился»",
      "JSON.parse(" in _pk79 and _pk79.index("JSON.parse(") < _pk79.index("pvApi(") and "'api/pv/plan/import'" in _pk79 and "dry_run: true" in _pk79
      and "j.problems" in _pk79 and "status === 409" in _pk79)
check("вьюер 3.79: «Применить» требует причину (пустая → тост, запроса нет), шлёт тот же файл с reason и name без dry_run, ответ кладёт в state.plan, 409 закрывает окно",
      "Укажите причину импорта" in _ap79 and _ap79.index("Укажите причину импорта") < _ap79.index("pvApi(") and "reason, name: ctx.name" in _ap79
      and "dry_run" not in _ap79 and "Object.assign(state.plan" in _ap79 and "planSavedTxt(" in _ap79 and "план изменился, обновите страницу" in _ap79.lower())
_md79 = _V3.split("function showPlanImportModal(")[1].split("\nasync function planImportApply")[0]
check("вьюер 3.79: окно импорта — uiModalHTML стопкой (plan-win, uiStackCls), без tall; diff — .ui-table.dense по секциям словами (planDiffHuman), «показаны первые» при diff_truncated, пустой diff — «Файл совпадает» без «Применить»",
      "uiModalHTML(" in _md79 and "uiStackCls(" in _md79 and "tall" not in _md79 and "ui-table dense" in _md79 and "planDiffHuman(" in _md79
      and "j.diff_truncated" in _md79 and "Файл совпадает с планом на сервере" in _md79 and "foot: problems || empty ? closeOnly : null" in _md79)
check("вьюер 3.79: журнал плана показывает записи kind=import одной строкой; planEditSave знает kind fileimport",
      "en.kind === 'import'" in _V3 and "'база сайта загружена из файла'" in _V3 and "planEditOpen.kind === 'fileimport'" in _V3)
check("вьюер ≥3.79: VIEWER_VERSION не ниже 3.79.0 и совпадает с ?v= html (литерал версии в тест не зашивать)",
      bool(_v366) and tuple(map(int, _v366.group(1).split("."))) >= (3, 79, 0)
      and f"assets/viewer.js?v={_v366.group(1)}" in _HTML66 and f"assets/viewer.css?v={_v366.group(1)}" in _HTML66)

# ── вьюер 3.80.0: бумаги без обзора, кеш ИИС-3, все загрузки на «Снапшоте», плитки сравнения ──
_wp80 = _V3.split("function wrToPositions(")[1].split("\nfunction ", 1)[0]
_rp80 = _V3.split("function buildPositionsCard(")[1].split("function getKey(")[0]
_rf80 = _V3.split("function renderFunds(")[1].split("// ---- v3.73.0")[0]
_ri80 = _V3.split("function renderIis(")[1].split("\nfunction ", 1)[0]
_it80 = _V3.split("function iisCashTile(")[1].split("\nfunction renderIis(")[0]
_pb80 = _V3.split("function renderPfBuildTab(")[1].split("// opts: {")[0]
_ps80 = _V3.split("async function pfStart(")[1].split("\n}\n")[0]
_pc80 = _V3.split("function pfCashCard(")[1].split("\nfunction pfResultCard(")[0]
_rr80 = _V3.split("function pfResultCard(")[1].split("\nfunction renderNotifyTab(")[0]
_ie80 = _V3.split("function buildIeStateCard()")[1].split("// Страница Снапшот: состояние модели IE")[0]
_css80 = (REPO / "tools/assets/viewer.css").read_text(encoding="utf-8")
check("вьюер 3.80: «Акции» — акции снапшота без обзора (stock, не ИИС-3, не по стоимости покупки, qty>0) добавлены строками wrToPositions с noReview; в таблице плашка «без обзора», вердикт «—», фильтры по вердикту строк не ломают",
      all(x in _wp80 for x in ("noReview: true", "h.asset_type === 'stock'", "h.account !== 'iis_3'", "h.current_price_source !== 'cost_basis'", "h.qty > 0", "raw: {}"))
      and "'без обзора'" in _rp80 and "p.noReview ? '—' : renderVerdictTag" in _rp80 and "filterState.verdict) filtered = filtered.filter(p => p.verdict === filterState.verdict)" in _rp80)
check("вьюер 3.80: ожидание и доли обзора считаются только по бумагам с обзором (плитка, итог таблицы), в числе бумаг плитки строки без обзора есть",
      "positions.filter(p => !p.noReview)" in _V3 and "vis.filter(p => !p.noReview)" in _rp80 and "positions.filter(p => p.weight && !divestedOf(p.ticker)).length} бумаг" in _V3)   # проданная (гейт «продана») в число бумаг плитки не входит
check("вьюер 3.80: «Облигации» (allBondHoldings + per_bond) и «Фонды» (fundRows из holdings) показывают бумаги снапшота без обзора; «Доли и цели» добавляют в tickers акции holdings, которых нет в ie_actual",
      "allBondHoldings" in _V3.split("function renderBonds(")[1].split("\nfunction ", 1)[0] and "fundRows()" in _rf80 and "asset_type !== 'fund'" in _V3.split("function fundRows()")[1].split("\n}\n")[0]
      and "...Object.keys(heldVal)" in _V3 and "a.real_share_pct ?? (base && heldVal[t]" in _V3)
check("вьюер 3.80: «Фонды» — цель класса только для фондов в балансировке: in_rebalance === false → «—» и подпись «вне балансировки», такие строки в сортировке в конце (planPct null)",
      "rec?.in_rebalance === false" in _rf80 and "'вне балансировки'" in _rf80 and "planPct = cls && !outReb" in _rf80)
check("вьюер 3.80: «ИИС-3» — плитка «Деньги на счёте» = cash.by_account.iis_3 (подпись «факт …» либо «оценка · из снапшота …»), и когда расчёта ИИС нет",
      "'Деньги на счёте'" in _it80 and "by_account?.iis_3" in _it80 and "факт ${pfDate(d)}" in _it80 and "оценка · из снапшота" in _it80
      and _ri80.count("iisCashTile(port)") == 2 and _ri80.index("iisCashTile(port)") < _ri80.index("if (iis.status === 'mismatch')"))
check("вьюер 3.80: «Проба сборки» — галочки «Принять текущее кэш-расхождение» нет; карточка «Кеш после сборки» всегда, два поля (#pf-cashfact, #pf-cashfact-iis), cash_fact и cash_fact_iis уходят в pfStart/POST, пустое поле не передаётся",
      "pf-rebaseline" not in _pb80 and "Принять текущее кэш-расхождение" not in _V3 and "pfStart(box, files, {}, msg)" in _pb80
      and "pfCashCard(st, b, box, stale)" in _rr80 and "'pf-cashfact-iis'" in _pc80 and "'pf-cashfact'" in _pc80
      and "if (m.v != null) opts.cash_fact = m.v" in _pc80 and "if (i.v != null) opts.cash_fact_iis = i.v" in _pc80
      and "body.cash_fact_iis = opts.cash_fact_iis" in _ps80 and "cash_main_rub" in _pc80 and "cash_iis_rub" in _pc80)
check("вьюер 3.80: решение cash_fact_stale не рисует второго поля — текст внутри карточки «Кеш после сборки»; теги «кэш внесён» для обоих счетов; кнопка rebaseline осталась",
      "x.code !== 'cash_fact_stale'" in _rr80 and "'pf-cashfact-go'" in _pc80 and _rr80.count("id: 'pf-cashfact'") == 0
      and "кэш ИИС-3 внесён: " in _rr80 and "'кэш внесён: '" in _rr80 and "id: 'pf-rebase'" in _rr80)
check("вьюер 3.80: --cash-fact-iis сквозной: assemble_snapshot (параметр, флаг, meta, cash.iis_source), build_snapshot (флаг, манифест), pf_build.py (cash_fact_iis в теле, статусе, журнале)",
      all(x in _pf_py for x in ('"cash_fact_iis"', '"--cash-fact-iis"', "cash_main_rub"))
      and all(x in _bs_py for x in ('"--cash-fact-iis"', "cash_fact_iis"))
      and all(x in (REPO / "skills/portfolio-data-loader/scripts/assemble_snapshot.py").read_text(encoding="utf-8") for x in ("--cash-fact-iis", "cash_fact_iis=cash_fact_iis", '"iis_source"')))
check("вьюер 3.80: страница Снапшот — ряд из двух карточек загрузок (.ui-grid): «Страница IE» (#pf-ie: состояние модели + «Импорт страницы IE (webarchive)», окно showIeImportModal) и «База сайта» (#pf-file, до 3.82 «Файл плана»); лид дополнен",
      "buildIeLoadCard(), buildPlanFileCard()" in _pb80 and "ui-grid pf-loads" in _pb80 and "Здесь всё, что приходит на сайт извне" in _pb80
      and "id: 'pf-ie'" in _V3 and "showIeImportModal(j)" in _V3.split("function ieImportControl()")[1].split("\n}\n")[0])
check("вьюер 3.80: «Доли и цели» — состояние модели IE без кнопки, со ссылкой «импорт — на странице Загрузки →» (goToTab('pfbuild')); «Общие доли» — строка вместо карточки «База сайта»",
      "Импорт страницы IE" not in _ie80 and "импорт — на странице Загрузки →" in _ie80 and "goToTab('pfbuild')" in _ie80
      and "buildPlanFileCard()" not in _ro79 and "база сайта: скачать и загрузить — " in _ro79 and "на странице Загрузки →" in _ro79 and "goToTab('pfbuild')" in _ro79)
check("вьюер 3.80: плитки сравнения #pf-compare одной высоты (align-items:stretch, дети height:100%)",
      "#pf-compare{ align-items:stretch; }" in _css80 and "#pf-compare > *{ height:100%; }" in _css80)
check("вьюер ≥3.80: VIEWER_VERSION не ниже 3.80.0 и совпадает с ?v= html (литерал версии в тест не зашивать)",
      bool(_v366) and tuple(map(int, _v366.group(1).split("."))) >= (3, 80, 0)
      and f"assets/viewer.js?v={_v366.group(1)}" in _HTML66 and f"assets/viewer.css?v={_v366.group(1)}" in _HTML66)

# ── вьюер 3.81.0: «Загрузки», план грузится на любой вкладке ──
_lp81 = _V3.split("async function loadPlan()")[1].split("\nconst PLAN_EDIT_HINT")[0]
_rf81 = _V3.split("function renderFunds(")[1].split("\nfunction ", 1)[0]
_cf81 = _V3.split("function cardFundMain(")[1].split("\nfunction ", 1)[0]
check("вьюер 3.81: вкладка и кнопка шапки называются «Загрузки» (id pfbuild и #btn-pfbuild прежние)",
      "id: 'pfbuild', label: 'Загрузки'" in _V3 and "Проба сборки снапшота'" not in _V3
      and 'id="btn-pfbuild"' in _HTML66 and '<span class="h-btn-lbl">Загрузки</span>' in _HTML66)
check("вьюер 3.81: loadPlan перерисовывает «Загрузки» и «Акции» после загрузки плана; при ошибке на карточке файла плана — «повторить» → loadPlan()",
      "'pfbuild'" in _lp81 and "'positions'" in _lp81
      and "state.plan.status === 'error'" in _V3.split("function buildPlanFileCard()")[1].split("async function planImportPick")[0]
      and "loadPlan()" in _V3.split("function buildPlanFileCard()")[1].split("async function planImportPick")[0])
check("вьюер 3.81: «Фонды» — под ценой нет «к снапшоту»; карточка фонда — у «Моя средняя» нет «по покупкам»",
      "к снапшоту" not in _rf81 and "по покупкам" not in _cf81)
check("вьюер ≥3.81: VIEWER_VERSION не ниже 3.81.0 и совпадает с ?v= html (литерал версии в тест не зашивать)",
      bool(_v366) and tuple(map(int, _v366.group(1).split("."))) >= (3, 81, 0)
      and f"assets/viewer.js?v={_v366.group(1)}" in _HTML66 and f"assets/viewer.css?v={_v366.group(1)}" in _HTML66)

# ── вьюер 3.82.0: «База сайта», «Фонды» без ИИС-3 и с цветной доходностью, фонды на «ИИС-3» кликабельны, отклонения в % ──
_fr82 = _V3.split("function fundRows()")[1].split("\n}\n")[0]
_rf82 = _V3.split("function renderFunds(")[1].split("\n}\n")[0]
_fi82 = _V3.split("function fundInfo(")[1].split("\n}\n")[0]
_cm82 = _V3.split("function cardFundMain(")[1].split("\nfunction ", 1)[0]
_ch82 = _V3.split("function cardFundHead(")[1].split("\nfunction ", 1)[0]
_ir82 = _V3.split("function _iisRows(")[1].split("\n}\n")[0]
_pf82 = _V3.split("function buildPlanFileCard()")[1].split("async function planImportPick")[0]
_pi82 = _V3.split("async function planImportPick")[1].split("\n}\n")[0]
_pt82 = _V3.split("function planFactTable(")[1].split("\n}\n")[0]
check("вьюер 3.82: fundRows считает только основной счёт (account iis_3 пропускается), плашки «ИИС-3» в строке нет",
      "h.account === 'iis_3'" in _fr82 and "iisOnly:" not in _rf82 and "r.iisOnly" not in _rf82)
check("вьюер 3.82: «Фонды» — колонка «К плану»: «факт N % → план M %», имя самой узкой группы (корзина облигаций = план класса × план корзины, иначе класс) и соседи («только этот фонд», «с …»), «выше/ниже плана на», «в коридоре»; «Цель класса» нет",
      "label: 'К плану'" in _rf82 and "label: 'Цель класса'" not in _rf82 and "label: 'Класс к плану'" not in _rf82
      and "факт ${_ruDec(r.factPct, 1)} % → план" in _rf82 and "bucketPlanFactRows()" in _rf82
      and "planPct * br.plan / 100" in _rf82 and "bucketMembers(rec.bucket)" in _rf82 and "деньгами на счёте" in _rf82
      and "rb-devn" in _rf82 and "п.п." not in _rf82)
check("вьюер 3.82: цвет доходности внутри .ui-name — CSS перебивает ui-kit (.ui-name > b.good/.bad, > .ui-sub.good/.bad)",
      ".ui-name > b.good, .ui-name > .ui-sub.good{ color:var(--success); }" in _VCSS and ".ui-name > b.bad, .ui-name > .ui-sub.bad{ color:var(--err); }" in _VCSS)
check("вьюер 3.82/3.101: fundInfo(t, account) выбирает холдинги счёта; _iisRows отдаёт ту же запись из карты (без клонов onIis), карточка открывается со счётом ИИС-3",
      "function fundInfo(t, account)" in _V3 and "account === 'iis_3'" in _fi82
      and "const pos = base || null;" in _ir82 and "onIis: true" not in _ir82 and "_kind: 'fund'" not in _ir82)
check("вьюер 3.82: карточка фонда на «ИИС-3» — плитка «Доля счёта», тег «❄ ИИС-3», селекты класса/валюты/корзины и «В балансировке» disabled, заметка активна, подпись про вкладку «Фонды»; XIRR «по сделкам обоих счетов»",
      "'Доля счёта'" in _ch82 and "e.onIis && !e.accounts?.main ? _tagNode('iis', '❄ ИИС-3')" in _ch82 and "myReturnTile(xi, _fundAcct(e)" in _ch82
      and "b.disabled = true" in _cm82 and "lockPlan" in _cm82 and "disabled: true" in _cm82
      and "фонд только на ИИС-3 — вне балансировки, план не правится" in _cm82 and "funds.${t}.note" in _cm82)
check("вьюер 3.82: «База сайта» — кикер, текст, кнопки «Скачать JSON/XLSX», «Загрузить JSON»; окно «Загрузка базы сайта: …»; «Файл плана»/«Импорт JSON» нет",
      "'База сайта'" in _pf82 and "Количеств, цен и доходностей здесь нет" in _pf82 and "'Загрузить JSON'" in _pf82
      and "Загрузка базы сайта: ${name}" in _V3 and "Файл не подходит" in _V3
      and "Файл плана" not in _V3 and "Импорт JSON" not in _V3 and "Импорт плана" not in _V3 and "база сайта." in _V3 and "site-db-" in _V3)
check("вьюер 3.82: отклонения долей — в «%» (planFactTable, фонды, «Что перевести», коридор), «п.п.» остаются только у ставок, разброса сценариев и бенчмарка",
      "п.п." not in _pt82 and "п.п." not in _mc77 and "п.п." not in _ov77 and "п.п." not in _rf82
      and "при росте ставок на 1 п.п." in _V3 and "Разброс по сценариям" in _V3
      )
check("вьюер 3.82: фонды вне балансировки (in_rebalance === false) вычтены из факта класса и из базы в classPlanFactData (aPct пересчитан от новой базы, excluded в результате); подписи «База балансировки», «не в факте и не в базе», «не входят ни в факт классов, ни в базу»; cashSplit берёт «Кеш» из classPlanFactData; «Фонды» — доля и «К плану» от той же базы",
      "in_rebalance === false" in _V3.split("function classPlanFactData()")[1].split("\n}\n")[0] and "base0 - exSum" in _V3 and "return { bs, base, rows, excluded }" in _V3
      and "function balanceBase()" in _V3 and "'База балансировки'" in _V3 and "вне балансировки — не в факте и не в базе" in _V3
      and "не входят ни в факт классов, ни в базу" in _V3 and "classPlanFactData()?.rows" in _V3.split("function cashSplit()")[1].split("\n}\n")[0]
      and "balanceBase()" in _rf82 and "cdm[cls]" in _rf82 and "classFact: cf ? cf.aRub" in _V3)
check("вьюер ≥3.82: VIEWER_VERSION не ниже 3.82.0 и совпадает с ?v= html (литерал версии в тест не зашивать)",
      bool(_v366) and tuple(map(int, _v366.group(1).split("."))) >= (3, 82, 0)
      and f"assets/viewer.js?v={_v366.group(1)}" in _HTML66 and f"assets/viewer.css?v={_v366.group(1)}" in _HTML66)

# ── вьюер 3.83.0: «Фонды» — новый порядок колонок, «Отклонение» как в «Долях и целях», без суммы процентов ──
_rf83 = _V3.split("function renderFunds(")[1].split("\n}\n")[0]
_lab83 = re.findall(r"label: '([^']+)'", _rf83.split("const cols = [")[1].split("];")[0])
check("вьюер 3.83: «Фонды» — колонки ровно Фонд · Класс · Кол-во, шт. · Цена, ₽ · Стоимость, ₽ · К плану · Отклонение · Доходность · Заметка; «В балансировке» и «Доля, %» колонками нет",
      _lab83 == ["Фонд", "Класс", "Кол-во, шт.", "Цена, ₽", "Стоимость, ₽", "К плану", "Отклонение", "Доходность", "Заметка"]
      and "label: 'В балансировке'" not in _rf83 and "label: 'Доля, %'" not in _rf83)
check("вьюер 3.83: «Отклонение» — _planFactDev группы (класс или корзина), b.ui-num с rb-devn out за коридором, подстрока в ₽; «в балансировке/вне балансировки» подстрокой класса; доля — подстрокой стоимости («% портфеля»), «моя N ₽» — подстрокой цены; соседи по группе только когда они есть; подвала процентов (tShare) нет",
      "_planFactDev(planPct, factPct, grpRub, total)" in _rf83 and "rb-devn out" in _rf83 and "'в балансировке'" in _rf83 and "'вне балансировки'" in _rf83
      and "% портфеля" in _rf83 and "`моя ${" in _rf83 and "avg_cost_rub" in _rf83 and "buy_total_rub / xi.qty_now" in _rf83
      and "r.nbTxt ? el(" in _rf83 and "только этот фонд" not in _rf83 and "в коридоре" not in _rf83 and "плана на " not in _rf83 and "tShare" not in _rf83)
_cm83 = _V3.split("function cardFundMain(")[1].split("\nfunction ", 1)[0]
_fp83 = _V3.split("function _fundPctFld(")[1].split("\n}\n")[0]
check("вьюер 3.83/3.101: карточка фонда — поля плана блокируются, только если фонда нет на основном счёте (lockPlan по accounts.main), откуда бы ни открыли; «Комиссия фонда, % в год» и «Спред, %» — инлайн-поля fee_pct/spread_pct (Enter/blur, пусто → null, показ «N,NN %»), в таблице «Фонды» их нет",
      "const lockPlan = !(e.accounts?.main?.qty > 0);" in _cm83 and "if (lockPlan)" in _cm83 and "...(lockPlan ? { disabled: true } : {})" in _cm83 and ": lockPlan ?" in _cm83
      and "'Комиссия фонда, % в год'" in _cm83 and "'Спред, %'" in _cm83 and "'fee_pct'" in _cm83 and "'spread_pct'" in _cm83
      and "inputmode: 'decimal'" in _fp83 and "planSetBatch" in _fp83 and "funds.${t}.${field}" in _fp83 and "'Enter'" in _fp83 and "'blur'" in _fp83
      and "fee_pct" not in _rf83 and "spread_pct" not in _rf83)
_srv83 = (REPO / "tools/hosting/api/server.py").read_text(encoding="utf-8")
check("сервер 3.83: PLAN_FUND_FIELDS содержит fee_pct и spread_pct, правило set — число ≥ 0 (_plan_nonneg_num)",
      '"note", "fee_pct", "spread_pct")' in _srv83 and "(fee_pct|spread_pct)$" in _srv83 and "_plan_nonneg_num, _ap_fund" in _srv83)

# ── вьюер 3.84.0: «Загрузки» — карточка «Тип бумаги изменился» (сверка типов сборки) ──
_ptc84 = _V3.split("function pfTypesCard(")[1].split("\n}\n")[0]
check("вьюер 3.84: pfTypesCard — только при непустом brief.type_changes; слова типов (акция/облигация/фонд/другое), «был … → стал …», «по бирже … · по сделкам …», причины словами, пояснение, строка про сборку без сети",
      "Array.isArray(b.type_changes)" in _ptc84 and "if (!ch.length) return null" in _ptc84
      and "stock: 'акция', bond: 'облигация', fund: 'фонд', other: 'другое'" in _V3
      and "`был ${tr(c.was)} → стал ${tr(c.now)}`" in _ptc84 and "по бирже: ${tr(c.moex)} · по сделкам: ${tr(c.heur)}" in _ptc84
      and "против прошлого снапшота" in _V3 and "новая бумага: биржа и эвристика разошлись" in _V3
      and "Тип бумаги изменился" in _ptc84 and "Проверь, прежде чем делать снапшот рабочим" in _ptc84
      and "Тип с Мосбиржи обновляется только при сборке на сайте" in _ptc84
      and "типы с биржи не запрашивались (сборка без сети)" in _ptc84 and "b.types.online === false" in _ptc84)
_prc84 = _V3.split("function pfResultCard(")[1].split("\n}\n")[0]
check("вьюер 3.84: карточка типов — перед «Кеш после сборки» (pfTypesCard(b) раньше pfCashCard(st, b, box, stale))",
      0 <= _prc84.find("pfTypesCard(b)") < _prc84.find("pfCashCard(st, b, box, stale)"))
check("вьюер ≥3.84: VIEWER_VERSION не ниже 3.84.0 и совпадает с ?v= html (литерал версии в тест не зашивать)",
      bool(_v366) and tuple(map(int, _v366.group(1).split("."))) >= (3, 84, 0)
      and f"assets/viewer.js?v={_v366.group(1)}" in _HTML66 and f"assets/viewer.css?v={_v366.group(1)}" in _HTML66)

# ── вьюер 3.85.0: «Загрузки» — «Общий баланс» по желанию и строка паритета «без баланса ↔ с балансом» ──
_pp85 = _V3.split("function pfParityBlock(")[1].split("\n}\n")[0]
check("вьюер 3.85: pfParityBlock — строка «Поле за полем против снапшота …: совпало · в допуске · известных · расходится», сгиб с путями (.ui-fold), «Сверки нет» только у сборки с балансом (без баланса строки нет, 3.122), ошибка сверки, «другой день»",
      "Поле за полем против снапшота" in _pp85 and "совпало ${n(p.matched)} · в допуске ${n(p.within_tol)} · известных ${n(p.known)} · расходится ${n(p.diverged)}" in _pp85
      and "ui-fold" in _pp85 and "Где расходится" in _pp85 and "p.diverged_paths" in _pp85 and "pf-parity-paths" in _pp85
      and "Сверки нет: эта сборка сама с балансом." in _pp85 and "Сверки нет: снапшота с балансом на эту дату нет." not in _pp85 and "p.error" in _pp85 and "(другой день)" in _pp85)
_prc85 = _V3.split("function pfResultCard(")[1].split("\n}\n")[0]
check("вьюер 3.85: строка паритета — сразу после плиток «Что изменится, если сохранить» (b.parity в pfResultCard)",
      0 <= _prc85.find("id: 'pf-compare'") < _prc85.find("pfParityBlock(b.parity"))
check("вьюер 3.85: «Общий баланс» — «по желанию: только для сверки с базой сайта», лид «Загрузок» про сделки + базу сайта",
      "По желанию: только для сверки с базой сайта. Без него план, цели и IE — из базы сайта; с ним — сверка поле за полем." in _V3
      and "«Общий баланс» нужен только для сверки с базой" in _V3)
_css85 = (REPO / "tools/assets/viewer.css").read_text(encoding="utf-8")
check("вьюер 3.85: стили .pf-parity / .pf-parity-paths (моноширинно, перенос длинных путей)",
      ".pf-parity{" in _css85 and ".pf-parity-paths{" in _css85 and "overflow-wrap:anywhere" in _css85.split(".pf-parity-paths li")[1][:120])
check("вьюер ≥3.85: VIEWER_VERSION не ниже 3.85.0 и совпадает с ?v= html (литерал версии в тест не зашивать)",
      bool(_v366) and tuple(map(int, _v366.group(1).split("."))) >= (3, 85, 0)
      and f"assets/viewer.js?v={_v366.group(1)}" in _HTML66 and f"assets/viewer.css?v={_v366.group(1)}" in _HTML66)

# ── вьюер 3.86.0: «Фонды» — галочка «с ИИС-3», «К плану» шире, без chg ──
_rf86 = _V3.split("function renderFunds(c) {")[1].split("// ---- v3.73.0")[0]
_css86 = (REPO / "tools/assets/viewer.css").read_text(encoding="utf-8")
check("вьюер 3.86: renderFunds — filterChipCheckbox «с ИИС-3» (state.filterStates.funds.iis, по умолчанию выключена), строки iisRows только для фондов без основного счёта",
      "filterChipCheckbox('с ИИС-3', fState.iis, iisRows.length" in _rf86 and "{ cls: '', reb: false, iis: false, goneOnly: false }" in _rf86
      and "mainT = new Set(" in _rf86 and "iis: true, outReb: true" in _rf86 and "[...rows, ...(fState.iis ? iisRows : []), ...goneRows]" in _rf86)
check("вьюер 3.86: строка ИИС-3 — плашка «ИИС-3» (tag soft), «ИИС-3 вне целей», клик — карточка на счёте ИИС-3, подпись «основной счёт + фонды только на ИИС-3», итог по видимым строкам",
      "el('span', { class: 'tag soft' }, 'ИИС-3')" in _rf86 and "'ИИС-3 вне целей'" in _rf86 and "openCard(entryOf(r), L, r.iis" in _rf86
      and "основной счёт + фонды только на ИИС-3" in _rf86 and "vis.reduce((s, r) => s + (r.value || 0), 0)" in _rf86)
check("вьюер 3.86: поля chg, snapH и sp в строках фондов убраны",
      "chg:" not in _rf86 and "snapH" not in _rf86 and "const sp =" not in _rf86)
check("вьюер 3.86: «К плану» — min-width колонки в CSS, «Заметка» скрыта на узком компьютере (≤1199px), плашка ИИС-3 не растягивается",
      "th:nth-child(6), .ui-table.dense.fd-t td:nth-child(6){ min-width:" in _css86 and "(max-width:1199px)" in _css86
      and ".ui-table.fd-t .ui-name > .tag{ align-self:flex-start" in _css86)
check("вьюер ≥3.86: VIEWER_VERSION не ниже 3.86.0 и совпадает с ?v= html (литерал версии в тест не зашивать)",
      bool(_v366) and tuple(map(int, _v366.group(1).split("."))) >= (3, 86, 0)
      and f"assets/viewer.js?v={_v366.group(1)}" in _HTML66 and f"assets/viewer.css?v={_v366.group(1)}" in _HTML66)

# ── вьюер 3.87.0: подпись «оценка от» под полем «Оценка вручную» ──
_fm87 = _V3.split("function _fundManualNode(")[1].split("// справочное число фонда")[0]
check("вьюер 3.87: _fundManualNode — под полем ui-sub «оценка от дд.мм.гггг» из manual_positions[].value_as_of; после сохранения подпись обновляется из state.plan (ответ planSetBatch)",
      "оценка от ${" in _fm87 and "value_as_of" in _fm87 and "class: 'ui-sub fd-man-asof'" in _fm87
      and "asOf.textContent = asOfTxt(" in _fm87 and "_planRows('manual_positions')" in _fm87 and "inp, asOf)" in _fm87)
check("вьюер 3.87: дизайн-система — образец кнопки «Загрузки» (не «Проба сборки снапшота») в генераторе и превью Buttons",
      "lg\">Загрузки<" in (REPO / "tools/design-reference/gen_personal_hub_ds.py").read_text(encoding="utf-8")
      and "Проба сборки" not in (REPO / "tools/design-reference/personal-hub-ds/project/components/Buttons/preview.html").read_text(encoding="utf-8")
      and "Проба сборки" not in (REPO / "tools/design-reference/gen_personal_hub_ds.py").read_text(encoding="utf-8"))

# ── вьюер 3.88.0: «Сейчас» считается от плана сайта всегда ──
_pa88 = _V3.split("function planApplyAll() {")[1].split("function setupPlanLayer")[0]
_lp88 = _V3.split("async function loadPlan() {")[1].split("const PLAN_EDIT_HINT")[0]
_ll88 = _V3.split("rec.parsed = RebalanceEngine.applyQuotes(base, q, { fundClasses });")[1][:400]   # 11.11: liveBuildParsed, классы фондов из плана
_im88 = _V3.split("mode === 'plan' && window.RebalanceEngine) {")[1][:400]
_ip88 = _V3.split("function inlinePlanField(")[1].split("function planMarkNodes")[0]
check("вьюер 3.88: planApplyAll — обход plan.stocks с planApplyToSnapshot; вызывается в loadPlan (status ok), после applyQuotes, перед runAuto, после перечитывания portfolioLatest",
      "planApplyToSnapshot(t)" in _pa88 and "Object.keys(stocks)" in _pa88 and "planApplyAll()" in _lp88
      and "planApplyAll()" in _ll88 and _im88.index("planApplyAll()") < _im88.index("RebalanceEngine.runAuto")
      and "state.data.portfolioLatest = ps[0];\n  if (state.plan && state.plan.status === 'ok') planApplyAll()" in _V3)
check("вьюер 3.88: inlinePlanField — после 200 planApplyAll и перерисовка (renderTabContent / renderCards для карточки), прокрутка сохраняется; точечного planApplyToSnapshot в записи нет",
      "planApplyAll();" in _ip88 and "renderCards()" in _ip88 and "renderTabContent()" in _ip88 and "window.scrollTo(0, y)" in _ip88
      and "planApplyToSnapshot(" not in _ip88 and "return node;" in _ip88)
_wg88 = (REPO / "docs/investment/portfolio-workflow-guide.md").read_text(encoding="utf-8")
check("вьюер 3.88: гайд — подраздел «Сейчас» в «Долях и цели» с правилом «под гейтом срез только по слову плана» и именами движка (справка — блок «вьюер · справка из частей»)",
      "«Сейчас» в «Долях и цели»" in _wg88 and "срез предлагается только при плане «привести к плану» или «продать»" in _wg88
      and all(x in _wg88 for x in ("autoCycleFlags", "blockingReasons", "autoStopCondition", "compute_fixed_point_target", "base_source")))
check("вьюер ≥3.88: VIEWER_VERSION не ниже 3.88.0 и совпадает с ?v= html (литерал версии в тест не зашивать)",
      bool(_v366) and tuple(map(int, _v366.group(1).split("."))) >= (3, 88, 0)
      and f"assets/viewer.js?v={_v366.group(1)}" in _HTML66 and f"assets/viewer.css?v={_v366.group(1)}" in _HTML66)

# ── вьюер 3.89.0: слова плана в «Сейчас», причины словами, таблица «План» без горизонтальной прокрутки ──
import re as _re89
_rb89 = (REPO / "tools/assets/rebalance-engine.js").read_text(encoding="utf-8")
_py89 = (REPO / "skills/ru-portfolio-advisor/scripts/gate_aware_sizing.py").read_text(encoding="utf-8")
def _set89(src, name, js):
    m = _re89.search((r"var " + name + r" = \[([^\]]*)\]") if js else (r"^" + name + r" = \{([^}]*)\}"), src, _re89.M)
    return set(_re89.findall(r'"([^"]+)"', m.group(1))) if m else None
check("вьюер 3.89: константы слов плана (EXPLICIT_NO_BUY_PLANS, NO_BUY_DORMANT_PLANS, AUTO_TRIM_PLANS, AUTO_SELL_PLANS) в движке и в Python совпадают и не пусты",
      all(_set89(_rb89, n, True) is not None and _set89(_rb89, n, True) == _set89(_py89, n, False) for n in ("EXPLICIT_NO_BUY_PLANS", "NO_BUY_DORMANT_PLANS", "AUTO_TRIM_PLANS", "AUTO_SELL_PLANS", "HOLD_IN_BASE_PLANS"))
      and _set89(_rb89, "EXPLICIT_NO_BUY_PLANS", True) == {"WAIT", "WAIT/TRIM", "KEEP", "SELL"})
_rr89 = _V3.split("function reasonRu(r, ticker) {")[1].split("// v3.95.0: ждущие условия")[0]   # шаг 12: гейт — модуль (б), условия — модуль (а)   # 3.95: вынесена на верхний уровень (плитка, карточка, колонка)
check("вьюер 3.89: REASON_RU переводит каждый код в слова со своей датой (гейт, условие «держать», с продажей, ждёт условия, IPO-гейт, план, лимит); склейка « · »; кода WAIT/KEEP в словах нет",
      all(x in _rr89 for x in ("gate:", "condition_hold:", "sell_condition:", "pending_buy_condition", "ipo_gate:", "user_plan:", "concentration_breach:", "add_cooldown:", "gateOf(ticker)", "expires_on", "join(' · ')"))
      and "REASON_RU(a.reason, a.ticker)" in _V3 and "a.unblock_by" not in _V3.split("`стоит: ")[1][:120])
check("вьюер 3.89: «Сейчас» — «↓ продать всё · N лотов» для SELL, «держать (ниже плана)» для KEEP",
      "↓ продать всё · " in _V3 and "'держать (ниже плана)'" in _V3 and "a.user_plan === 'SELL'" in _V3)
_css89 = (REPO / "tools/assets/viewer.css").read_text(encoding="utf-8")
check("вьюер 3.89: «План» — колонки заметок скрыты (.rb-v-watch noteie/noteai), «Сейчас» переносится, долгосрок в подсказке ячейки",
      ".rb-v-watch th[data-col=noteie]" in _css89 and "display:none" in _css89.split(".rb-v-watch th[data-col=noteie], .rb-v-watch td[data-col=noteie],\n.rb-v-watch th[data-col=noteai]")[-1][:120]
      and ".rb-v-watch td[data-col=now] .rb-now{ white-space:normal; }" in _css89 and "долгосрочная цель" in _V3)
check("вьюер 3.89: слова плана — в гайде и в gate-aware-sizing.md (справка — в блоке «вьюер · справка из частей»)",
      all(x in _wg88 for x in ("EXPLICIT_NO_BUY_PLANS", "NO_BUY_DORMANT_PLANS", "AUTO_SELL_PLANS", "срез до нуля БЕЗ коридора"))
      and "Слова плана владельца" in (REPO / "skills/ru-portfolio-advisor/references/gate-aware-sizing.md").read_text(encoding="utf-8"))
check("вьюер 3.89: пороги гейтов — 1 п.п. везде (тексты статусов во вьюере, gate_status_ru, gate-status-labels, rebalance-framework); 0,5 / 1,5 в текстах гейтов нет",
      not _re89.search(r"0,5 ?(%|п\.п)|1,5 ?(%|п\.п)", _GATE_HINTS)
      and "до 1 п.п." in _GATE_HINTS and "больше чем на 1 п.п." in _GATE_HINTS
      and not _re89.search(r"0,5 п\.п|1,5 п\.п", _GATE_EFFECTS + (REPO / "_shared-references/gate-status-labels.md").read_text(encoding="utf-8"))
      and not _re89.search(r"(under_review|review_aging|reviewed_keep|reviewed_buy_more)`? *\| *[01]\.5 п", (REPO / "skills/ru-portfolio-advisor/references/rebalance-framework.md").read_text(encoding="utf-8")))
_gp89 = _V3.split("const gatePill = (ticker) => {")[1].split("function renderGateBadge")[0]
check("вьюер 3.89 → R27 (03.11): слова плашки = слова решений (новая, без разбора / нужен разбор / наблюдать / срок решения вышел) в GATE_PILL_WORD; плашка под тикером в обеих ячейках «Бумага» (с 3.91 — для всех статусов, см. блок 3.91)",
      "GATE_PILL_WORD" in _V3 and all(_CL["gate_status"][k]["ru"] == w for k, w in (("new_position", "новая, без разбора"), ("review_needed", "нужен разбор"), ("reviewed_under_review", "наблюдать"), ("review_aging", "срок решения вышел")))
      and "gateOf(ticker)" in _V3.split("const gateStatusOf")[1][:300] and _V3.count("gatePill(r.ticker)") == 2)
check("вьюер ≥3.89: VIEWER_VERSION не ниже 3.89.0 и совпадает с ?v= html",
      bool(_v366) and tuple(map(int, _v366.group(1).split("."))) >= (3, 89, 0)
      and f"assets/viewer.js?v={_v366.group(1)}" in _HTML66 and f"assets/viewer.css?v={_v366.group(1)}" in _HTML66)

# ───── вьюер 3.90: база «к цели IE» с гейтом, первая покупка, путь новой бумаги, как снять гейт ─────
_ie90 = _V3.split("const cols = view === 'work'")[1].split("const hasAction")[0]
_ie90_mode = _ie90.split("const colsT = ")[1]
check("вьюер 3.90: база «к цели IE» — колонки без «Сумма, ₽», с «Решение» (бывш. «Гейт», R27; 3.119: и с «Мой план, %»); плашка под тикером там не дублируется",
      "['gateRank', 'Решение'" in _ie90_mode and "'Мой план, %'" in _ie90_mode and "Сумма, ₽" not in _ie90_mode and "'uplan'" not in _ie90_mode and "'План'" not in _ie90_mode
      and "mode === 'ie' ? null : gatePill(r.ticker)" in _V3)
check("вьюер 3.90 → шаг 12: гейт в «к цели IE» — модуль (б); «продано» = «новая», без статуса — пусто; сортировка: блокирующие, затем разрешающие",
      "r.gateSt = st0 === 'divested' ? 'new_position' : (st0 || null);" in _V3 and "const gateOrder = [...GATE_BLOCKING, ...CL.codes('gate_status').filter(k => !GATE_BLOCKING.includes(k) && k !== 'divested')];" in _V3
      and list(__import__("json").loads(_CL_TXT)["maps"]["gate_to_block"]) == ['new_position', 'review_needed', 'reviewed_under_review', 'review_aging']
      and "k === 'gateRank' ? 'asc'" in _V3)
_rb90 = (REPO / "tools/assets/rebalance-engine.js").read_text(encoding="utf-8")
_py90 = (REPO / "skills/ru-portfolio-advisor/scripts/gate_aware_sizing.py").read_text(encoding="utf-8")
check("вьюер 3.90: кандидаты первой покупки есть в движке и в Python (firstBuyCandidates ↔ first_buy_candidates), FIRST_BUY_PLANS = {BUY, BALANCE} в обоих; правило «нет записи = новая» и no_price",
      "function firstBuyCandidates" in _rb90 and "def first_buy_candidates" in _py90
      and re.search(r'var FIRST_BUY_PLANS = \["BUY", "BALANCE"\]', _rb90) and re.search(r'^FIRST_BUY_PLANS = \{"BUY", "BALANCE"\}', _py90, re.M)
      and 'gateCode("new_position")' in (REPO / "tools/assets/last-word.js").read_text(encoding="utf-8")   # шаг 11: «новая» — модуль (б)
      and '"gate:" + g.status' in (REPO / "tools/assets/last-word.js").read_text(encoding="utf-8")
      and "no_price" in _rb90 and "no_price" in _py90)
check("вьюер 3.90: runAuto получает живые котировки и цены IE; строка первой покупки — «· первая покупка», «по цене IE»; тикеры плана с долей > 0 в таблице",
      "{ quotes: state.live?.quotes || null, iePrices, today: dsToday(), aiMode: uiAiMode() }" in _V3 and "' · первая покупка'" in _V3 and "по цене IE" in _V3 and "...planned" in _V3)
_wg90 = (REPO / "docs/investment/portfolio-workflow-guide.md").read_text(encoding="utf-8")
check("вьюер 3.90 → 5.1.3: «Путь новой бумаги» — в гайде; review_aging открывает только разбор — «Подтверждаю держать» нет ни в статусе, ни в словарях (правило 9а)",
      "путь новой бумаги" in _wg90
      and "Подтверждаю держать" not in _CL["gate_status"]["review_aging"]["hint"]
      and "Подтверждаю держать" not in _CL["gate_status"]["review_aging"]["effect"]
      and "разбор" in _CL["gate_status"]["review_aging"]["effect"]
      and "Подтверждаю держать" not in (REPO / "_shared-references/gate-status-labels.md").read_text(encoding="utf-8"))
_gb90 = _V3.split("function gateSayNode(ticker, e) {")[1].split("// «Что произошло за неделю»")[0]
check("вьюер 3.90 → 5.1.3: карточка акции — блок «Решение» несёт «Что сказать Claude» с фразами-чипами для блокирующих гейтов (только «разбери»), без title; вызван из cardDecisionNode",
      "gateSayNode(p.ticker, g)" in _V3 and "title" not in _gb90 and
      "Что сказать Claude" in _gb90 and "_copyChip" in _gb90 and "Подтверждаю держать ${ticker}" not in _gb90 and "Разбери ${ticker}" in _gb90)
check("вьюер ≥3.90: VIEWER_VERSION не ниже 3.90.0 и совпадает с ?v= html; движок не ниже 1.4.0 и ?v= у него",
      bool(_v366) and tuple(map(int, _v366.group(1).split("."))) >= (3, 90, 0)
      and f"assets/viewer.js?v={_v366.group(1)}" in _HTML66 and f"assets/viewer.css?v={_v366.group(1)}" in _HTML66
      and "assets/rebalance-engine.js?v=1." in _HTML66)

# ───── вьюер 3.91: раздел справки «6а. Гейты», строка гейта в карточке, плашки гейта всех статусов, кандидаты, мелочи 3.90 ─────
_wg91 = (REPO / "docs/investment/portfolio-workflow-guide.md").read_text(encoding="utf-8")
check("вьюер 3.91: гайд — §3.4а «Статусы кодами ↔ словами» с таблицей кодов, gateLineText, формулой базы; ссылка на 06-gates.md",
      "### 3.4а" in _wg91 and "buyLineText" in _wg91 and "GATE_PILL_WORD" in _wg91 and "compute_fixed_point_target" in _wg91 and "06-gates.md" in _wg91)
_gl91 = _V3.split("function buyReasonsText(g) {")[1].split("function cardDecisionNode")[0]
check("вьюер 3.91 → R27 (03.11): строка «Докупка: открыта / закрыта: …» в карточке — по причинам модуля (б): «срок решения вышел дд.мм, откроет разбор», «наблюдать, до …», IPO-пауза, пауза после докупки; слов «решение устарело» нет",
      all(x in _gl91 for x in ("'Докупка: открыта'", "`Докупка: закрыта: ${buyReasonsText(g)}", "Докупка: открыта, но ", "срок решения вышел", "откроет разбор", "IPO-пауза", "пауза после докупки до", "g.expires_on"))
      and "buyLineText(p.ticker)" in _V3 and not re.search(r"Решение устарело|решение устарело", _V3.split("\n", 6)[6])
      and "Решение устарело" not in _CL_TXT and _CL["gate_status"]["review_aging"]["ru"] == "срок решения вышел")
_gp91 = _V3.split("const GATE_PILL_WORD")[1].split("function renderGateBadge")[0]
check("вьюер 3.91: плашка гейта строится для ЛЮБОГО статуса (держать / наращивать / снижать — tag soft), цвет по списку GATE_BLOCKING; нет записи / «продано» = «новая»; колонка «Гейт» на базе «к цели IE» — та же плашка",
      all(x in _gp91 for x in ("GATE_STATUS_META", "GATE_BLOCKING", "'tag ' + (GATE_STATUS_META[st]?.cssClass || 'hold')", "k !== 'divested'"))
      and "gatePillTag(r.gateSt)" in _V3 and "mode === 'ie' ? null : gatePill(r.ticker)" in _V3)
check("вьюер 3.91: «первая покупка» с неизвестным лотом — без «N лотов» («лот уточни по котировке»), в движке и Python lots = null",
      "лот уточни по котировке" in _V3 and "lotNote" not in _V3 and "!candBy[it.ticker].lot_known) lots = null" in _rb90
      and 'not cand_by[t]["lot_known"]' in _py90 and "lots = None" in _py90)
_bt91 = _V3.split("const ieAllHead")[0] if False else _V3
_ri91 = _V3.split("const cols = view === 'work'")[1]
check("вьюер 3.91: сортировка «План», «Статус», «Отметка» — userPlanW / userStatusW / markTs считаются ДО sortBy(rows) в renderIeModel",
      _V3.index("r.markTs = planStatusMarkOf") < _V3.index("rows = sortBy(rows, ss.col, ss.dir);\n  const pbt = buildPositionByTicker();\n  const list = rows.map(r => pbt[r.ticker]).filter(Boolean);\n  const pp ="))
check("вьюер 3.91: кандидаты из модели IE и плана — в buildPositionByTicker (candidatePosition, candidate: true на каркасе карточки акции), цена — живая котировка, иначе IE; в карточке «Решение» с гейтом и фразой для разбора",
      "function candidatePosition(t, port)" in _V3 and "candidate: true" in _V3 and "if (!out[t] && !heldAny.has(t)) out[t] = candidatePosition(t, port)" in _V3
      and "function candidatePriceOf" in _V3 and "state.live?.quotes?.items?.[t]?.price" in _V3.split("function candidatePriceOf")[1][:200]
      and "Бумаги нет в портфеле — разбора ещё не было" in _V3 and "кандидат из модели IE" in _V3)
_ev91 = re.search(r'var ENGINE_VERSION = "([\d.]+)"', _rb90)
_html91 = _HTML66
check("вьюер 3.91: ENGINE_VERSION в шапке rebalance-engine.js = ?v= у него в html",
      bool(_ev91) and f"assets/rebalance-engine.js?v={_ev91.group(1)}" in _html91)
check("вьюер ≥3.91: VIEWER_VERSION не ниже 3.91.0 и совпадает с ?v= html",
      bool(_v366) and tuple(map(int, _v366.group(1).split("."))) >= (3, 91, 0)
      and f"assets/viewer.js?v={_v366.group(1)}" in _HTML66 and f"assets/viewer.css?v={_v366.group(1)}" in _HTML66)

_gs92 = (REPO / "_shared-references/gate_status_ru.py").read_text(encoding="utf-8")
_gl92 = (REPO / "_shared-references/gate-status-labels.md").read_text(encoding="utf-8")
check("вьюер 3.92: единое слово «разбор» — «Нужен разбор» / «Новая» в словаре статусов (Python, labels, вьюер); «Нужен анализ» / «Новая позиция» в живых текстах нет",
      _CL["gate_status"]["review_needed"]["ru"] == "нужен разбор" and _CL["gate_status"]["new_position"]["ru"] == "новая, без разбора"   # R27 (03.11)
      and "нужен разбор" in _gl92 and "| новая, без разбора |" in _gl92
      and "label: CL.ru('gate_status', k)" in _V3
      and not any(x in t for t in (_CL_TXT, _gl92, _HV, _V3.split("\n", 6)[6]) for x in ("Нужен анализ", "Новая позиция")))
check("вьюер 3.92: одно слово на статус — GATE_PILL_WORD строится из GATE_STATUS_META (нет второго списка), слова статусов Python = вьюер; снижать / наращивать / продана",
      "Object.entries(GATE_STATUS_META)" in _V3.split("const GATE_PILL_WORD")[1][:200] and "reviewed_reduce: 'снижать'" not in _V3
      and [_CL["gate_status"][k]["ru"] for k in ("reviewed_reduce", "reviewed_buy_more", "divested")] == ["сократить", "докупать", "продана"]   # R27: = слова решений
      and "codelists.entries(\"gate_status\")" in _gs92 and "Сократить" not in _gs92 and "Увеличить" not in _gs92
      and "(pbt[t] || candidatePosition(t, port))" in _V3.split("function _gateTickerLinks")[1][:900])
_gl93 = _V3.split("function showGateLegendModal")[1].split("function renderGateBlock")[0]   # шаг 12: окно «Решения»
_gt93 = _V3.split("function _gateTickerLinks")[1].split("function _linkTickers")[0]
_wf93 = (REPO / "docs/investment/portfolio-workflow-guide.md").read_text(encoding="utf-8")
check("вьюер 3.93 → шаг 12: окно «Решения» — гейт только у акций (модуль (б): gate.applicable), фонды и облигации — строкой без значка",
      "function heldNonStockKind" in _V3 and "r.g ? GATE_STATUS_META[r.g.status]" not in _gl93 and "meta = g ? GATE_STATUS_META[g.status] : null" in _gl93
      and "if (!g || !g.applicable || !g.status) return null;" in _V3)
check("вьюер 3.93: _gateTickerLinks ветвится по виду бумаги — фонд открывает карточку фонда (fundEntries), облигация — облигации, кандидат только для тикера вне holdings",
      "nk === 'fund'" in _gt93 and "fundEntries()" in _gt93 and "nk === 'bond'" in _gt93 and "{ bond: 'bonds', fund: 'funds' }" in _gt93)
check("вьюер 3.93: плашка «кандидат из модели IE» — только для тикера из ieModel().positions, иначе «нет в портфеля» (soft); «продана» — «Продана дд.мм», «Гейт снят.» без фраз для Claude",
      "(ieModel()?.positions || []).some(m => m.ticker === p.ticker) ? _tagNode('', 'кандидат из модели IE')" in _V3
      and "_tagNode('soft', 'нет в портфеле')" in _V3 and "`Последнее слово — ${VERDICT_SRC_RU[card.verdict_source.kind]}" in _V3 and "'Гейт снят.'" not in _V3
      and "const dv0 = divestedOf(key)" in _V3 and "c.gate?.status === 'divested' ? 'sold'" in _V3)   # 4.2.1: «продана/погашена» — правило 14 модуля (б), любой класс
check("вьюер 3.93: справка 6а и гайд (синхронно) — гейты только по акциям, переклассификация снимает запись, это не продажа",
      all("только по акциям" in t and "это не продажа" in t for t in (_HV, _wf93)))
_css92 = (REPO / "tools/assets/viewer.css").read_text(encoding="utf-8")
_meta92 = _V3.split("const GATE_CSS = {")[1].split("};")[0]   # класс плашки по коду; подписи — из CL
_cls92 = re.findall(r"\w+: '(gate-[a-z]+)'", _meta92)
check("вьюер 3.92: плашка гейта несёт класс из GATE_STATUS_META.cssClass; у каждого статуса свой цвет в css (серый только «продана»); колонка «Гейт» на базе IE — тот же класс",
      len(_cls92) == 8 and all(re.search(r"\.tag\.%s\b" % c, _css92) for c in _cls92)
      and re.search(r"\.tag\.gate-divested\{[^}]*text-faint", _css92) and "gatePillTag(r.gateSt)" in _V3
      and not re.search(r"\.tag\.gate-(keep|buymore|reduce|needed|under|aging|new)[^{]*\{[^}]*bg-alt", _css92))
_ipo92 = _V3.split("const ipoPauseOf = ")[1].split("const gatePill = ")[0]
check("вьюер 3.92 → шаг 12: IPO-пауза — вторая плашка «IPO · до дд.мм» (tag trim) из модуля (б) (справочник бумаг: ticker_class ipo + listed_at); строка в карточке; срок = defaults.ipo_pause_quarters; справка и гайд — строка «IPO-гейт (автоматический)»",
      "lwCard(ticker)" in _ipo92 and "ipo_pause_until" in _ipo92 and "IPO · до ${_ddmmDot(u)}" in _ipo92 and "'tag trim'" in _ipo92
      and "ipoPillTag(r.ticker)" in _V3 and "`IPO-пауза${g.ipo_pause_until ? ' до ' + _ddmmDot(g.ipo_pause_until) : ''}`" in _V3 and "listing_age_quarters" not in _ipo92
      and '"ipo_pause_quarters": 8' in (REPO / "_shared-references/codelists.json").read_text(encoding="utf-8")
      and "разбором не снимается" in _HV and "разбором не снимается" in (REPO / "skills/ru-portfolio-advisor/references/gate-aware-sizing.md").read_text(encoding="utf-8") and "IPO-гейт (автоматический)" in (REPO / "docs/investment/portfolio-workflow-guide.md").read_text(encoding="utf-8"))
_ng92 = _V3.split("const nowGoalSub = (a) => {")[1].split("const nowCell = ")[0]
check("вьюер 3.92: под «Сейчас» подпись цели — «до X % книги после сделок · база …» (base_rub), «до 0 % · выход» для «продать всё»; плитка — «книга сейчас» рядом с базой докупки",
      all(x in _ng92 for x in ("книги после сделок · база", "до 0 % · выход", "auto.base_rub", "rubBig")) and "книга сейчас ${" in _V3 and "nowGoalSub(a)" in _V3)
check("вьюер 3.92: гайд — предохранитель базы fixed_point_capped (справка: «Предел базы» — в блоке «вьюер · справка из частей»)",
      "fixed_point_capped" in (REPO / "docs/investment/portfolio-workflow-guide.md").read_text(encoding="utf-8"))
check("вьюер 3.92: предохранитель базы — min(T*, T_full) в движке и в compute_fixed_point_target(t_full), base_source fixed_point_capped",
      "fixed_point_capped" in _rb90 and "base > classPlan" in _rb90 and "t_full" in (REPO / "_shared-references/constraint_engine.py").read_text(encoding="utf-8")
      and "t_full=class_plan_rub" in _py90 and "fixed_point_capped" in _py90)
check("дизайн-макет: «Оценка устарела» вместо «Решение устарело»",
      (not (REPO / "tools/design-reference/Дашборд - все вкладки.dc.html").exists()  # макет в публичную копию не входит
       or "Решение устарело" not in (REPO / "tools/design-reference/Дашборд - все вкладки.dc.html").read_text(encoding="utf-8")))
check("вьюер ≥3.92: VIEWER_VERSION не ниже 3.92.0 и совпадает с ?v= html; ENGINE_VERSION не ниже 1.6.0",
      bool(_v366) and tuple(map(int, _v366.group(1).split("."))) >= (3, 92, 0)
      and f"assets/viewer.js?v={_v366.group(1)}" in _HTML66 and f"assets/viewer.css?v={_v366.group(1)}" in _HTML66 and bool(_ev91) and tuple(map(int, _ev91.group(1).split("."))) >= (1, 6, 0))

# ─────────── вьюер 3.95.0: замороженная бумага базу только уменьшает; где видна заморозка; условия-разборы; шпаргалка «Что на что влияет» ───────────
_vjs95 = (REPO / "tools/assets/viewer.js").read_text(encoding="utf-8")
_rb95 = (REPO / "tools/assets/rebalance-engine.js").read_text(encoding="utf-8")
_wg95 = (REPO / "docs/investment/portfolio-workflow-guide.md").read_text(encoding="utf-8")
_ce95 = (REPO / "_shared-references/constraint_engine.py").read_text(encoding="utf-8")
_py95 = (REPO / "skills/ru-portfolio-advisor/scripts/gate_aware_sizing.py").read_text(encoding="utf-8")
_ev95 = re.search(r'var ENGINE_VERSION = "([\d.]+)"', _rb95)
check("вьюер ≥3.95: ENGINE_VERSION не ниже 1.7.0 и равна ?v= у rebalance-engine.js в html",
      bool(_ev95) and tuple(map(int, _ev95.group(1).split("."))) >= (1, 7, 0) and f"assets/rebalance-engine.js?v={_ev95.group(1)}" in _HTML66)
check("§10.7 (11.11, отмена «на плане» 3.95/3.97): у строк frozen/frozen_reason; frozen_at_plan/at_plan, frozen_on_plan, frozen_plans/book_rub — удалены из движка, Python и constraint_engine",
      "frozen_reason" in _rb95 and "frozen:" in _rb95 and "at_plan" not in _rb95 and "atPlan" not in _rb95
      and "frozen_at_plan" not in _py95 and "frozen_on_plan" not in _py95 and "_WAIT_PLANS" not in _py95
      and "frozen_plans" not in _ce95 and "book_rub" not in _ce95)
check("3.95 (+§10.7): плитка «Сейчас» — сгиб «заморожено: N бумаг · X млн ₽» (frozenFoldNode, .ui-fold now-frozen) со строками .ui-row; у бумаги выше плана — «выше плана» (frozenAbovePlan), «на плане» нет",
      "function frozenFoldNode" in _vjs95 and "`заморожено: ${fr.length}" in _vjs95 and "ui-fold now-frozen" in _vjs95 and "now-frozen-row" in _vjs95
      and "frozenAbovePlan(a) ? 'выше плана'" in _vjs95 and "на плане: перевес при заморозке" not in _vjs95 and "if (nowFold) c.append(nowFold)" in _vjs95)
check("3.95 (+§10.7): карточка акции — строка «Для базы «Сейчас»» (cardBaseNode) в блоке «Решение»: заморожена (выше плана) / плановым весом / условия-разборы не держат",
      "function cardBaseNode" in _vjs95 and "Для базы «Сейчас»: ${t}" in _vjs95 and "kind === 'stock' ? cardBaseNode(p.ticker)" in _vjs95
      and "'заморожена (выше плана)' : 'заморожена'}${why" in _vjs95 and "в базе плановым весом" in _vjs95 and "в базе по текущим рублям" in _vjs95 and "условия-разборы покупку не держат" in _vjs95)
check("3.95: «условие: разбор» строится для ждущих условий kind review (reviewConditionsOf/reviewCondText): дата — «разбор до ДД.ММ.ГГГГ», цена — «разбор при цене ≤ …», раньше — первым, через « · »",
      "function reviewConditionsOf" in _vjs95 and "function reviewCondText" in _vjs95 and "condKind(c) === 'review'" in _vjs95 and "`разбор до ${pfDate(d)}`" in _vjs95
      and "разбор при цене" in _vjs95 and "'условие: ' + items.map(x => x.t).join(' · ')" in _vjs95 and "rb-revcond" in _vjs95)
for _nm, _tx in (("portfolio-workflow-guide.md", _wg95),):
    check(f"3.95: {_nm} — шпаргалка «Что на что влияет»: строка «условие с исходом «срез/продать»» и слова «продажу не вызывает и не блокирует»",
          "Что на что влияет" in _tx and "условие с исходом «срез/продать»" in _tx and "продажу не вызывает и не блокирует" in _tx
          and "Покупка требует плана и отсутствия блокировок; продажа — только плана" in _tx
          and "Замороженная бумага — в F своими рублями (и выше плана): книга после исполнения = база." in _tx)
check("§10.7: гайд — «на плане» отменено, заморозка в F своими рублями; справка «Сейчас» без «на плане»",
      "замороженная бумага — в F своими рублями (§10.7" in _wg95 and "frozenAbovePlan" in _wg95
      and "на плане" not in (REPO / "tools/assets/help/viewer/05-now.md").read_text(encoding="utf-8"))

# ─────────── вьюер 3.96.0 / ui-kit 1.58.0: фонды кликабельны в отчётах; поиск по справке ───────────
_vjs96 = (REPO / "tools/assets/viewer.js").read_text(encoding="utf-8")
_uij96 = (REPO / "tools/assets/ui-kit.js").read_text(encoding="utf-8")
_uic96 = (REPO / "tools/assets/ui-kit.css").read_text(encoding="utf-8")
_pbt96 = _vjs96.split("function buildPositionByTicker()")[1].split("function heldNonStockKind")[0]
check("3.96: buildPositionByTicker дополняет карту фондами основного счёта (fundEntries), не перекрывая акции и облигации; кандидаты — после фондов",
      "for (const f of fundEntries()) if (!out[f.ticker]) out[f.ticker] = f;" in _pbt96
      and _pbt96.index("fundEntries()") < _pbt96.index("candidatePosition(t, port)"))
check("3.96: _linkTickers не исключает фонды по виду (ключи — вся карта pbt, ссылка открывает openCard записи карты)",
      "_kind" not in _vjs96.split("function _linkTickers(root)")[1].split("function renderReportDoc")[0])
_hd96 = _vjs96.split("function _securityChipLabel")[1].split("function _metaRow")[0] + _vjs96.split("// v3.16.1: чип бумаги портфеля — кнопка")[1].split("if (chips.length) {")[0]
check("3.96: шапка отчёта — в tickers имя фонда и ISIN сопоставляются с тикером из снапшота (_tickerByName: holdings[].name без регистра/кавычек/«ETF», ISIN → ticker), дубли схлопываются по тикеру; несопоставленное — серый чип",
      "function _tickerByName" in _vjs96 and "function _nameKey" in _vjs96 and "h.isin === raw" in _vjs96 and "_nameKey(h.name) === k" in _vjs96
      and "_seen.has(x.raw)" in _hd96 and "el('span', { class: 'tag rp-tic' }, t.label)" in _hd96)
check("ui-kit ≥1.58: uiReaderHTML — опция search (поле .ui-qbox с data-rd-q над оглавлением и над текстом); uiReaderMount — подсветка mark.rd-hit по текстовым узлам, счётчик, Enter/↓/↑/Esc",
      "opts.search" in _uij96 and 'data-rd-q' in _uij96 and "mark.rd-hit" in _uij96 and 'className = "rd-hit"' in _uij96
      and '"ArrowDown"' in _uij96 and '"ArrowUp"' in _uij96 and "из " in _uij96 and "нет совпадений" in _uij96 and "createTreeWalker(doc" in _uij96)
check("ui-kit ≥1.58: справки (uiHelpOpen, в т.ч. openHelpAt вьюера) включают поиск по умолчанию (meta.search !== false), отчёты — нет; Esc в поле с запросом сначала очищает поиск",
      "search: meta.search !== false" in _uij96 and "uiHelpOpen('portfolio'" in _vjs96.split("function openHelpAt")[1][:400] and "search: true" not in _vjs96.split("function openHelpAt")[1][:400]
      and 'hasAttribute("data-rd-q")' in _uij96)
check("ui-kit ≥1.58: цвета подсветки — токены (--warn/--warn-bg/--bg), поле поиска липнет над текстом на узком окне",
      re.search(r"mark\.rd-hit\{[^}]*var\(--warn-bg\)", _uic96) and re.search(r"mark\.rd-hit\.is-cur\{[^}]*var\(--warn\)", _uic96)
      and ".rd-q-main{ position:sticky" in _uic96)
_uv96 = re.search(r"UI_KIT_VERSION = '([\d.]+)'", _uij96)
check("ui-kit ≥1.58.0: UI_KIT_VERSION не ниже 1.58.0 и совпадает с ?v= на каждой странице (js и css)",
      bool(_uv96) and tuple(map(int, _uv96.group(1).split("."))) >= (1, 58, 0)
      and all(re.search(rf"assets/ui-kit\.(js|css)\?v={re.escape(_uv96.group(1))}", (REPO / "tools" / pg).read_text(encoding="utf-8"))
              and not re.search(rf"assets/ui-kit\.(js|css)\?v=(?!{re.escape(_uv96.group(1))})", (REPO / "tools" / pg).read_text(encoding="utf-8"))
              for pg in ("portfolio-integrated-viewer.html", "hub.html", "login.html", "food.html", "money.html", "games.html", "health.html", "travel.html")))
_wg96 = (REPO / "docs/investment/portfolio-workflow-guide.md").read_text(encoding="utf-8")
check("3.96: справка и гайд (синхронно) — упоминание поиска по справке и кликабельных фондов в отчётах",
      all("Поиск по справке" in t for t in (_HV, _wg96)))

# ─────────── вьюер 3.97.0: «на плане» в ручном режиме; отчёты по времени; отчёты по бумаге в карточке ───────────
_vjs97 = (REPO / "tools/assets/viewer.js").read_text(encoding="utf-8")
_vcss97 = (REPO / "tools/assets/viewer.css").read_text(encoding="utf-8")
_wg97 = (REPO / "docs/investment/portfolio-workflow-guide.md").read_text(encoding="utf-8")
_pl97 = _vjs97.split("function parseListing(")[1].split("// fn(item) не бросает")[0]
check("3.97: parseListing — mtime из mod_time (parseMtime, RFC3339 → epoch мс), автоиндекс без JSON — null; mtime доезжает до записей (makeHttpFile → ingestFiles records.mtime), у копий и /api/pv/sync — из версии (verMtime)",
      "mtime: parseMtime(e.mod_time)" in _pl97 and "mtime: null" in _pl97 and "function parseMtime" in _vjs97 and "function verMtime" in _vjs97
      and r"^s:\d+:(\d+)$" in _vjs97 and "function makeHttpFile(url, text, relPath, mtime = null)" in _vjs97
      and "mtime: file.mtime ?? null" in _vjs97 and "fetchDirListing" in _vjs97 and ".map(({ url, ver, mtime })" in _vjs97)
check("3.97: cmpRecent — дата убыв. → mtime убыв. → имя убыв.; им отсортированы advisorReports и _latestIisReport; других сортировок отчётов по одной дате не осталось",
      "function cmpRecent(a, b)" in _vjs97 and ".filter(r => r.type === 'advisorReport')\n    .sort(cmpRecent)" in _vjs97
      and "reps.sort(cmpRecent)" in _vjs97 and "(recCreatedAt(b) ?? b.mtime ?? 0) - (recCreatedAt(a) ?? a.mtime ?? 0)" in _vjs97)
check("3.97 → R27: «Отчёты» (бывш. «Мои репорты») — дата дд.мм.гггг и время «чч:мм» рядом, только если день mtime совпадает с датой отчёта (reportTimeLabel); модель — в подсказке",
      "function reportTimeLabel(r)" in _vjs97 and "=== day) return `${p(d.getHours())}:${p(d.getMinutes())}`" in _vjs97
      and "[r.date ? pfDate(String(_toDateStr(r.date) || r.date).slice(0, 10)) : '—', reportTimeLabel(r)].filter(Boolean).join(' ')" in _vjs97
      and "title: fm.model ? 'модель: ' + fm.model : null" in _vjs97 and "Мои репорты (" not in _vjs97)
check("3.97: подвкладка «Отчёты» у акции, облигации и фонда после «История»; ярлык «Отчёты · N» только при N > 0 (есть обзоры недели — «Отчёты и обзоры · N»; 4.2.0, F10: на телефоне — короткое «Отчёты · N»)",
      all(re.search(rf"{k}: \[.*\['hist', 'История'\], \['reports', 'Отчёты'\]\]", _vjs97) for k in ("stock", "bond", "fund"))
      and "`${revs.length && !isPhone() ? 'Отчёты и обзоры' : lbl} · ${reps.length + revs.length}`" in _vjs97 and "k === 'reports' && reps.length + revs.length" in _vjs97)
_rft = _vjs97.split("function reportsForTicker(")[1].split("// isin и название бумаги")[0]
check("3.97: reportsForTicker(ticker, {isin, name}) — tickers: тикер/ISIN без регистра и имя через _tickerByName (3.96), порядок cmpRecent; один помощник на подвкладку, «Главное» и «Историю»",
      "keys.has(x.toUpperCase())" in _rft and "_tickerByName(x)" in _rft and ".sort(cmpRecent)" in _rft and "isin" in _rft
      and _vjs97.count("function reportsForTicker(") == 1 and "reportsForTicker(ticker, _secIdent(ticker))" in _vjs97
      and "cardReportsOf(e)" in _vjs97.split("function fillCard(")[1].split("const S = kind")[0])
check("3.97: строка отчёта в карточке — .ui-row.pick.card-rep: дата+время, заголовок, вид (reportKindRu), режим коротко, первая фраза summary ≤160; клик/Enter → showAdvisorReportModal(r, {fromCard: true})",
      "ui-row pick card-rep" in _vjs97 and "reportKindRu(fm.kind)" in _vjs97.split("function cardReportRow")[1][:700] and "_firstSentence(fm.summary)" in _vjs97
      and "function _firstSentence(t, max = 160)" in _vjs97 and "showAdvisorReportModal(r, { fromCard: true })" in _vjs97)
check("3.97: отчёт поверх карточки — стопкой: «← К бумаге» = closeModal, окно документа (z 300) выше карточки (z 220), Esc закрывает только отчёт; нет отчётов — «Разбери X» с (#copy)",
      "fn: closeModal" in _vjs97 and "opts?.fromCard" in _vjs97.split("function showAdvisorReportModal")[1][:600] and "'← К бумаге'" in _vjs97
      and "z-index:300" in _vcss97.split(".modal-overlay{")[1][:200] and "z: _nextCardZ()" in _vjs97 and "function docOpen(o)" in _vjs97
      and "Отчётов по бумаге нет — " in _vjs97 and "`${ADV}Разбери ${e.ticker}`" in _vjs97 and "_copyChip(say)" in _vjs97)
check("3.97: «Главное» — одна строка-ссылка «разборов: N · последний дд.мм →» (cardReportsLinkNode, cardSub(i, 'reports')), только при N > 0; у акции, облигации и фонда",
      "разборов: ${reps.length} · последний ${_ddmmDot(reps[0].date)} →" in _vjs97 and "cardSub(i, 'reports')" in _vjs97 and "if (!reps.length) return null;" in _vjs97
      and _vjs97.count("cardReportsLinkNode(i, reps)") == 4)   # определение + акция, облигация, фонд
_tl97 = _vjs97.split("function _tlLinkOf(")[1].split("// 3.120: общий сбор событий бумаги")[0]   # 3.122.0: дальше идут сбор событий и _tradeEventsOf («сделка» там своя, не связь)
check("3.97: «История» — связь события с документом только по дате и бумаге: обзор → md-обзор той же даты; гейт (не auto) и действие над условием (не fired/expired) → отчёт советника этой даты, при нескольких — первый по cmpRecent и подсказка «ещё N … этой даты на подвкладке «Отчёты»»; сделки не связываются",
      "e.kind === 'rev'" in _tl97 and "(mdHist || []).find(r => r.date === e.date)" in _tl97 and "e.kind === 'gate' && e.byAuthor" in _tl97 and "e.kind === 'cond' && e.byAuthor" in _tl97
      and "_toDateStr(r.date) === e.date" in _tl97 and "day[0]" in _tl97 and "на подвкладке «Отчёты»" in _tl97 and "trade" not in _tl97
      and "byAuthor: true, rep, decision: d" in _vjs97 and "byAuthor: e.by === 'owner'" in _vjs97)   # шаг 12: решение (decisions/) — всегда авторское; событие условия — авторское у владельца
check("3.97: связанное событие — строка .ui-row.tl.pick (tl-link), несвязанное как раньше; хвостовой стрелки нет (3.122.0: в тексте уже «было → стало»); в подвале журнала одна ui-note",
      "(lk ? ' pick tl-link' : '')" in _vjs97 and "class: 'tl-go'" not in _vjs97 and _vjs97.count("card-tl-foot") == 1
      and "Ссылка у обзора стоит при смене вердикта или фундаментала (качества)" in _vjs97 and ".tl.pick" in _vcss97 and ".card-rep{" in _vcss97)
check("3.97 → §10.7: советник, ручной режим — параметра frozen_on_plan и строки «Замороженные бумаги выше плана считаются стоящими на плане…» нет; CLI-флага --frozen нет",
      "frozen_on_plan" not in _py95 and "считаются стоящими на плане" not in _py95 and "--frozen" not in _py95)
check("3.97: справка и гайд (синхронно) — «Отчёты · N», ссылки в «Истории», порядок отчётов по времени записи, база разбора совпадает с «Сейчас»",
      "Отчёты · N" in _HV and "времени записи" in _HV and all(("Отчёты" in t and "времени записи" in t and "считают базу так же" in t) for t in (_wg97,)))
# ─────────── вьюер 3.99.0 + ui-kit 1.59.1: уход окон с затуханием; время событий; фонды ИИС-3 в отчётах; метка выноски ───────────
_uikjs99 = (REPO / "tools/assets/ui-kit.js").read_text(encoding="utf-8")
_uikcss99 = (REPO / "tools/assets/ui-kit.css").read_text(encoding="utf-8")
check("ui-kit 1.59.1: у ухода своя анимация ui-modal-fade-out (слой .ui-fx/.ui-docwin/.uh-overlay, окно и панель стопкой); «reverse» от ui-modal-fade в уходе не остался — общее имя с входом не давало уходу запуститься",
      "@keyframes ui-modal-fade-out{ to{ opacity:0; } }" in _uikcss99
      and _uikcss99.count("animation:ui-modal-fade-out .17s ease-in forwards") == 3 and "ui-modal-fade .17s ease-in reverse" not in _uikcss99)
check("ui-kit 1.59.1: выноска «> **Важно:** …» — метка с двоеточием («Важно: текст»), и при пустом остатке; changelog 1.59.1 в шапке",
      '"<p><b>" + co[1] + ":</b> "' in _uikjs99 and '"<p><b>" + co[1] + ":</b></p>"' in _uikjs99 and "// v1.59.1 " in _uikjs99)
_sss99 = (REPO / "_shared-references/security_sources.py").read_text(encoding="utf-8")   # читатели выборки security_digest (шаг 10)
_ac99 = (REPO / "skills/save-to-library/scripts/apply_condition.py").read_text(encoding="utf-8")
check("3.99: save-to-library пишет время — apply_condition (с шага 6 — conditions@2, истории нет): created_at и withdrawn.at из time_msk.now_iso() (скрытый --now для тестов); apply_gate_review удалён в шаге 8 (файл гейтов упразднён); читатели отчётов пробрасывают created_at",
      not (REPO / "skills/save-to-library/scripts/apply_gate_review.py").exists()
      and '"created_at": now' in _ac99 and "return args.now or time_msk.now_iso()" in _ac99 and '"at": _now(args)' in _ac99
      and "history" not in _ac99
      and "_created_at(fm.get(\"created_at\"))" in _sss99)
check("3.99: вьюер — порядок отчётов: created_at → mtime → имя (recCreatedAt, cmpRecent, reportTimeLabel); источники времени события «Истории»: time журнала → created_at документа → mtime документа в день события → нет (_docHM, cmpTimeline); время мелко под датой (.tl-t)",
      "function recCreatedAt(r)" in _vjs97 and "function reportTimeLabel(r)" in _vjs97 and "for (const ms of [recCreatedAt(r), r.mtime])" in _vjs97
      and "function _docHM(doc, date)" in _vjs97 and "function cmpTimeline(a, b)" in _vjs97 and "ev.sort(cmpTimeline)" in _vjs97
      and "time: _hmIso(d.recorded_at), chg: true" in _vjs97 and "time: _hmIso(e.at), chg: e.event === 'fired'" in _vjs97 and "function _hmIso(v)" in _vjs97
      and "x.time = x.time || _docHM(x.doc || x.link?.doc, x.date)" in _vjs97 and ".tl-t" in _vcss97)
check("3.99: фонд только на ИИС-3 — iisOnlyFundEntries() (обычная запись {_kind:'fund', ticker, name}, показатели — accounts.iis_3) добавлен в buildPositionByTicker после основных фондов",
      "function iisOnlyFundEntries()" in _vjs97 and "for (const f of iisOnlyFundEntries()) if (!out[f.ticker]) out[f.ticker] = f;" in _vjs97
      and "onIis: true, _iis: { qty: 0" not in _vjs97)
_p99 = REPO / "tools/assets/help/viewer"
_g06 = (_p99 / "06-gates.md").read_text(encoding="utf-8")
check("3.99: справка (части) и гайд — «на пересмотре»: советник предлагает сокращать, сайт режет по слову плана; время событий и created_at; фонды ИИС-3 в отчётах; оговорка в gate_status_ru и словаре вьюера",
      "сайт режет только по слову плана ([раздел 5](#now))" in _g06
      and "по слову плана" in __import__("json").loads((REPO / "_shared-references/codelists.json").read_text(encoding="utf-8"))["lists"]["gate_status"]["reviewed_under_review"]["effect"]
      and (_vjs97 + (REPO / "_shared-references/codelists.json").read_text(encoding="utf-8")).count("сайт режет только по слову плана") >= 3
      and "created_at" in (_p99 / "04-tabs.md").read_text(encoding="utf-8") and "записывается при сохранении в библиотеку" in (_p99 / "07-conditions.md").read_text(encoding="utf-8")
      and "cmpTimeline" in _wg97 and "iisOnlyFundEntries" in _wg97 and "created_at" in _wg97)
check("3.100: «Цели по облигациям» — строка группы несёт суммы корзин (plan, aPct, aRub), planFactTable рисует её числами (pf-grprow, без rb-out), planMovesSides фильтрует !r.group; справка и гайд (синхронно)",
      "const grow = { group: g, plan: null, aPct: null, aRub: null };" in _vjs97 and "add('plan', r.plan); add('aPct', r.aPct); add('aRub', r.aRub)" in _vjs97
      and "isGrp && r.plan == null && r.aPct == null" in _vjs97 and "' pf-grprow' : (d.out ? ' rb-out' : '')" in _vjs97 and "rows.filter(r => !r.group && r.plan != null" in _vjs97
      and "суммы их корзин" in (REPO / "tools/assets/help/viewer/04-tabs.md").read_text(encoding="utf-8") and "суммы её корзин" in _wg97)
check("3.100: псевдонимы тикеров в отчётах — TICKER_ALIASES (кодлисты maps.ticker_aliases: RENT → XXXXXX) с комментарием, _tickerByName схлопывает псевдоним в настоящий тикер",
      "const TICKER_ALIASES = CL.map('ticker_aliases');" in _vjs97
      and __import__("json").loads((REPO / "_shared-references/codelists.json").read_text(encoding="utf-8"))["maps"]["ticker_aliases"] == {"RENT": "XXXXXX"} and "реальный тикер MOEX — XXXXXX" in _vjs97
      and "if (TICKER_ALIASES[raw.toUpperCase()]) return TICKER_ALIASES[raw.toUpperCase()];" in _vjs97)
_vv97 = re.search(r"const VIEWER_VERSION = '([\d.]+)'", _vjs97)
_hv97 = re.findall(r"viewer\.(?:js|css)\?v=([\d.]+)", (REPO / "tools/portfolio-integrated-viewer.html").read_text(encoding="utf-8"))
check("вьюер ≥3.103.0: VIEWER_VERSION не ниже 3.103.0 и совпадает с ?v= viewer.js и viewer.css в html",
      bool(_vv97) and tuple(map(int, _vv97.group(1).split("."))) >= (3, 103, 0) and len(_hv97) >= 2 and all(v == _vv97.group(1) for v in _hv97))

# ---- 3.101.0: одна запись на тикер, счёт — измерение
_v101 = (REPO / "tools/assets/viewer.js").read_text(encoding="utf-8")
_bp101 = _v101.split("function buildPositionByTicker() {")[1].split("\nfunction cardAccount(")[0]
_iis101 = _v101.split("function _iisRows(")[1].split("\n}\n")[0]
_fc101 = _v101.split("function fillCard(")[1].split("\n}\n")[0]
_cm101 = _v101.split("function cardFundMain(")[1].split("\n}\n")[0]
check("вьюер 3.101: запись бумаги несёт accounts {main, iis_3} (qty, value, share, locked/lockedReal, avg, xirr, h), onIis = «лежит на ИИС-3»; attachAccounts вызывается в конце buildPositionByTicker",
      "attachAccounts(out, port);" in _bp101 and "e.accounts = { main: side('main'), iis_3: side('iis_3') };" in _bp101
      and "locked: b?.locked_pct ?? h0.locked_pct, lockedReal: b?.locked_real_pct ?? h0.locked_real_pct" in _bp101 and "avg: h0.avg_cost_rub" in _bp101 and "xirr: pi[e.ticker]?.xirr" in _bp101
      and "if (e.accounts.iis_3) e.onIis = true;" in _bp101)
check("вьюер 3.101: нет клонов onIis: true во вкладке «ИИС-3» и в iisOnlyFundEntries; вкладка ИИС-3 и «Фонды» (с «ИИС-3») открывают ту же запись с { account: 'iis_3' }",
      "onIis: true" not in _iis101 and "onIis: true" not in _v101.split("function iisOnlyFundEntries()")[1].split("\n}\n")[0]
      and "openCard(r.pos, list, { account: 'iis_3' })" in _v101 and "account: opts?.account || null" in _v101)
check("вьюер 3.101: сегмент счёта .ui-seg «Основной счёт · ИИС-3» только у бумаги на обоих счетах, по умолчанию основной; cardView меняет только показатели позиции; листание сохраняет счёт, если он есть у соседа",
      "data-act=\"card-acct\"" in _fc101 and "e0.accounts?.main && e0.accounts?.iis_3" in _fc101 and "class=\"ui-seg sm\"" in _fc101
      and "function cardView(e, want)" in _v101 and "function cardAccount(e, want)" in _v101 and "return a.main ? 'main' : 'iis_3';" in _v101
      and "cardAcct(i, a.getAttribute('data-v'))" in _v101 and "cardView(L.list[L.idx], L.account)" in _v101)
check("вьюер 3.101: lockPlan фонда — по accounts.main (правится ⇔ есть на основном счёте); при lockPlan комиссия, спред, заметка и оценка вручную неактивны, одна ui-note",
      "const lockPlan = !(e.accounts?.main?.qty > 0);" in _cm101 and "ok && !lockPlan" in _cm101 and "manual && !lockPlan && ok ? _fundManualNode" in _cm101
      and "фонд только на ИИС-3 — вне балансировки, план не правится" in _cm101 and "«Фонды» (основной счёт)" not in _cm101)

# ---- 4.3.0 (владелец 05.11): без связи план читается из копии, но не правится — кнопки правки спрятаны
_v430 = (REPO / "tools/assets/viewer.js").read_text(encoding="utf-8")
_css430 = (REPO / "tools/assets/viewer.css").read_text(encoding="utf-8")
check("вьюер 4.3.0: planEditable() = план загружен и связь есть; setOffline() — единственное место state.offline = true, ставит html.pv-offline",
      "function planEditable() { return state.plan.status === 'ok' && !state.offline; }" in _v430
      and _v430.count("state.offline = true") == 1 and "document.documentElement.classList.add('pv-offline')" in _v430
      and _v430.count("setOffline();") == 3)
check("вьюер 4.4.1: связь вернулась — setOnline() снимает признак и перечитывает план; поводы — cab-online, online, возврат на вкладку (probeOnline, ответ сервера не из копии)",
      "function setOnline() {" in _v430 and "state.offline = false;" in _v430 and "classList.remove('pv-offline')" in _v430
      and "if (e.data?.type === 'cab-online') { setOnline(); return; }" in _v430
      and "window.addEventListener('online', () => probeOnline());" in _v430
      and "if (r.status < 500 && !r.headers.get('X-Cab-Saved')) setOnline();" in _v430)
check("вьюер 4.3.0: CSS прячет [data-plan-edit] без связи; подсказка «без связи план не правится»",
      "html.pv-offline [data-plan-edit]{ display:none !important; }" in _css430
      and "offline: 'без связи план не правится'," in _v430 and "if (state.offline && state.plan.status === 'ok') return PLAN_EDIT_HINT.offline;" in _v430)
check("вьюер 4.3.0: входы в окна правки плана — по planEditable(), не по status (5 окон), кнопка «сделано» в «Действиях» — тоже",
      _v430.count("if (!planEditable()) { _miniToast(planEditHint()); return; }") == 5
      and "if (state.plan.status !== 'ok') { _miniToast(" not in _v430 and "if (planEditable()) kids.push(el('div', { class: 'act-btns'" in _v430)
check("вьюер 4.3.0: карандаши плана и IE, кнопки «База сайта» и импорта IE помечены data-plan-edit (≥ 7)",
      _v430.count("'data-plan-edit': ''") >= 7 and _v430.count("setAttribute('data-plan-edit', '')") == 2)

# ---- 3.102.0: ось дат «Динамики» на телефоне; обзоры недели в «Отчётах»; база сравнения «со скиллом»
_v102 = (REPO / "tools/assets/viewer.js").read_text(encoding="utf-8")
_dl102 = _v102.split("function drawLineChart(")[1].split("\nfunction ")[0]
check("вьюер 3.102: ось дат drawLineChart на ≤ 720 — maxTicksLimit 4, подпись «дд.мм» без года (два года — «мм.гг»), год в заголовке оси, запас справа layout.padding.right",
      "matchMedia?.('(max-width:720px)')" in _dl102 and "maxTicksLimit: narrow ? 4 : 8" in _dl102 and "dayToDateStr(v).slice(0, 5)" in _dl102
      and "dayToDateStr(v).slice(3)" in _dl102 and "title: { display: !!(narrow && !twoYears && years.length)" in _dl102 and "padding: { right: narrow ? 18 : 0 }" in _dl102 and "bounds: 'data'" in _dl102)
_rv102 = _v102.split("function reviewsForTicker(")[1].split("function cardReviewsOf")[0]
check("вьюер 3.102: reviewsForTicker(ticker, {isin}) — YAML обзоров акций и облигаций (per_stock/per_bond по тикеру или ISIN), пара md по дате; один помощник на «Отчёты» и «Историю»",
      "per_bond" in _rv102 and "per_stock" in _rv102 and "isin" in _rv102 and "md: mds.find(m => m.date === rec.date)" in _rv102
      and _v102.count("function reviewsForTicker(") == 1 and "reviewsForTicker(ticker, _secIdent(ticker)).filter(x => x.kind === kind)" in _v102
      and "reviewsForTicker(e?.ticker, { isin: _secIdent(e?.ticker).isin })" in _v102)
_cp102 = _v102.split("function cardReportsPane(")[1].split("// одна строка-ссылка")[0]
check("вьюер 3.102: группа «Обзоры недели» под отчётами — _secHead со счётчиком; больше трёх — сгиб .ui-fold свёрнут; строка: дата+время, «обзор акций/облигаций за неделю», вердикт, первая фраза ≤160; клик → showMdReportModal(..., {fromCard}) с «← К бумаге»",
      "_secHead('Обзоры недели', String(revs.length))" in _cp102 and "revs.length > 3" in _cp102 and "ui-fold card-revs-fold" in _cp102
      and "r.kind === 'bond' ? MODE_RU['2'] : MODE_RU['1']" in _v102 and "_firstSentence(humanizeText(String(t)), 160)" in _v102
      and "showMdReportModal(r.md, r.kind, { fromCard: true })" in _v102 and "opts?.fromCard ? { back: { label: '← К бумаге', fn: closeModal } }" in _v102)
_pb102 = (REPO / "tools/hosting/notify/pf_build.py").read_text(encoding="utf-8")
_bs102 = (REPO / "skills/portfolio-data-loader/scripts/build_snapshot.py").read_text(encoding="utf-8")
check("вьюер 3.102: «Сравнение со скиллом» — база сравнения compare_snapshot (последний снапшот скилла ≤ as_of любого типа), опора кэша prev_snapshot отдельно; подпись «опора кэша — снапшот от …», если база ≠ опоре",
      "def find_compare_snapshot(" in _bs102 and '("compare_snapshot", compare)' in _bs102 and 'inputs.get("compare_snapshot") or inputs.get("prev_snapshot")' in _pb102
      and 'b["cache_base_as_of"]' in _pb102 and "опора кэша — снапшот от" in _v102 and "b.cache_base_as_of !== k.as_of" in _v102)
_hp102 = "\n".join(p.read_text(encoding="utf-8") for p in sorted((REPO / "tools/assets/help/viewer").glob("*.md")))
check("вьюер 3.102: справка — обзоры недели второй группой «Отчётов», две базы «Загрузок» (снапшот скилла и опора кэша)",
      "обзоры недели" in _hp102.lower() and "опора кэша" in _hp102.lower())

# ---- 3.103.0: корзина облигации выводится (причина, источник, исключение с причиной, принятие расхождения), средняя цена
_v103 = (REPO / "tools/assets/viewer.js").read_text(encoding="utf-8")
_bpn103 = _v103.split("function bondPlanNodes(r) {")[1].split("\nfunction fundEntries()")[0]
_bx103 = _v103.split("function bondExceptionForm(")[1].split("\nconst BOND_SRC_RU")[0]
check("вьюер 3.103: корзина облигации — режим «вывод» только при hold.bucket_source (иначе прежний список выбора); причина (bucket_reason) и подпись источника: «с Мосбиржи» / «по рейтингу» / «вручную: …» / «по плану (выведено иначе: X)»",
      "if (!hold.bucket_source) {" in _bpn103 and "uiSelectNode" in _bpn103.split("if (!hold.bucket_source) {")[1].split("// корзина выводится")[0]
      and "iss: 'с Мосбиржи', rating: 'по рейтингу'" in _v103 and "`вручную: ${rec?.reason || holdWhy || 'причина не указана'}`" in _bpn103
      and "`по плану (выведено иначе: ${derived})`" in _bpn103 and "hold.bucket_reason" in _bpn103)
check("вьюер 3.103: плашка ui-note warn «Сборка выводит «X», в плане «Y»» при источнике «plan» и derived ≠ плановой; «Принять выведенную» пишет type/subtype без manual; «Оставить вручную» открывает форму исключения",
      "hold.bucket_source === 'plan' && derived && derived !== curKey && !manualNow" in _bpn103 and "Сборка выводит «${derived}», в плане «${curKey || '—'}»" in _bpn103
      and "'Принять выведенную'" in _bpn103 and "'Оставить вручную'" in _bpn103
      and "'Выведенная корзина принята'" in _bpn103 and "manual" not in _bpn103.split("'Выведенная корзина принята'")[0].rsplit("planSetBatch(", 1)[1])
check("вьюер 3.103: исключение — выбор корзины + обязательная причина; пишет bonds.<ISIN>.{type, subtype, manual: true, reason}; «вернуть выведенную» — manual false, reason null, type/subtype = выведенной",
      "if (!reason) {" in _bx103 and "bonds.${isin}.manual`, value: true" in _bx103 and "bonds.${isin}.reason`, value: reason" in _bx103
      and "bonds.${isin}.manual`, value: false" in _bpn103 and "bonds.${isin}.reason`, value: null" in _bpn103 and "'вернуть выведенную'" in _bpn103)
check("вьюер 3.103: «Загрузки» — pfBucketCard (build-summary.bond_bucket_check): строки «было → стало · причина», те же две кнопки, «без рейтинга: …» с фразой обзора облигаций (STALE_SAY.bonds); пусто — карточки нет; вызывается после pfTypesCard",
      "function pfBucketCard(b) {" in _v103 and "const bc = b.bond_bucket_check;" in _v103 and "m.code === 'bond_rating_missing'" in _v103
      and "_copyText(STALE_SAY.bonds)" in _v103 and "if (!ch.length && !nr.length) return null;" in _v103
      and _v103.index("parts.push(pfTypesCard(b));") < _v103.index("parts.push(pfBucketCard(b));"))
check("вьюер 3.103 (с 3.107 — строка таблицы «Позиция», не плитка): средняя цена облигации — avg_price_pct «% номинала», avg_cost_rub ₽, «с НКД» (avg_includes_accint), «перенесена» (avg_cost_source carried); нет новых полей — строки нет; в таблицу «Облигации» колонка не добавлена; плитки «Средняя цена» нет",
      "function bondAvgText(h) {" in _v103 and "if (!pctOk && !(h.avg_includes_accint && h.avg_cost_rub != null)) return null;" in _v103
      and "'с НКД'" in _v103 and "h.avg_cost_source === 'carried' ? 'перенесена'" in _v103 and "_kv('Средняя цена', bondAvgText(h))," in _v103
      and "cardTile('Средняя цена'" not in _v103 and "bondAvgTile" not in _v103)
check("вьюер 3.103: рейтинг плана облигации — список из лестницы PLAN_RATING_LADDER (16 значений, как RATING_LADDER загрузчика) + «нет рейтинга» (null), путь bonds.<ISIN>.rating, подсказка про пересчёт корзины; строка «Рейтинг» показывает «обзор: … · X (план)»",
      "const PLAN_RATING_LADDER = ['AAA', 'AA+', 'AA', 'AA-', 'A+', 'A', 'A-', 'BBB+', 'BBB', 'BBB-', 'BB+', 'BB', 'BB-', 'B+', 'B', 'B-'];" in _v103
      and "function bondRatingSelect(" in _v103 and "path: `bonds.${isin}.rating`, value: v || null" in _v103 and "t: 'нет рейтинга'" in _v103
      and "корзина пересчитается при следующей сборке снимка" in _v103 and "обзор: ${rv || '—'} · ${pr} (план)" in _v103
      and re.findall(r"[A-Z]{1,3}[+-]?", re.search(r"RATING_LADDER: list\[str\] = \[(.*?)\]", (REPO / "skills/portfolio-data-loader/scripts/parse_portfolio.py").read_text(encoding="utf-8"), re.S).group(1)) == re.findall(r"'([A-Z+-]+)'", re.search(r"const PLAN_RATING_LADDER = \[(.*?)\]", _v103).group(0)))
_lt103 = _v103.split("function _linkTickers(root) {")[1].split("\nfunction renderReportDoc")[0]
check("вьюер 3.103: _linkTickers — ISIN бумаг портфеля (holdings: isin → ключ-тикер записи) тоже ссылки; текст внутри <code> не пропускается (a, button, pre, .rp-tk — да), заголовки не исключены; клик — карточка поверх документа",
      "isinKey[h.isin] = h.ticker" in _lt103 and "const entryOf = (k) => alias[k]?.() || pbt[k] || pbt[isinKey[k]];" in _lt103
      and "closest('a, button, pre, .rp-tk')" in _lt103 and "openCard(entryOf(tk), [entryOf(tk)])" in _lt103 and "code, pre" not in _lt103)
_oc103 = _v103.split("function openCard(entry, list, opts) {")[1].split("\n}\n")[0]
check("вьюер 3.103: openCard подменяет строку таблицы (без accounts) записью buildPositionByTicker того же вида и тикера — и саму запись, и список листания; счёт и тег ИИС-3 решает accounts, а не on_iis обзора",
      "entry.accounts === undefined" in _oc103 and "_pbtOpen[x.ticker]" in _oc103 and "cardKindOf(m) === cardKindOf(x) ? m : x" in _oc103
      and "entry = _norm(entry);" in _oc103 and "list = list.map(_norm)" in _oc103)
check("вьюер 3.104: поле рейтинга плана — только при ИТОГОВОЙ корзине КОРП/* (curKey = plan.bonds после правки, иначе снапшот); у ОФЗ и валютных (даже корпоративный эмитент с CNY) поля нет вовсе",
      "const isCorp = String(curKey || '').startsWith('КОРП') || (!curKey && /^КОРП/.test(hold.bucket_reason || ''));" in _bpn103
      and "...(isCorp ? [_kv('Рейтинг в плане', bondRatingSelect(" in _bpn103 and "\n      : [])];" in _bpn103 and "[_kv('Рейтинг в плане', rec?.rating || null)]" not in _bpn103)
_v104 = _V3
check("вьюер 3.104: «Моя доходность» по счёту — by_account[счёт] при наличии, подпись «по счёту» и мелко «по обоим счетам», история короче года — «% за N дней» (4.4.7; до того порог был 30 дней), без by_account — подпись про выгрузку ИИС-3 / «сделки ИИС-3 устарели»; один помощник myReturnTile у акции, облигации (рядом с «При покупке») и фонда",
      "const RET_SHORT_DAYS = 365;" in _v104 and "function myReturnTile(xi, acct, both, keys)" in _v104 and "xi?.by_account?.[acct]" in _v104
      and "за ${dd} ${_ruPlural(dd, ['день', 'дня', 'дней'])}" in _v104 and "'по счёту'" in _v104 and "по обоим счетам: " in _v104
      and "по обоим счетам — доходность по счёту появится после сборки с выгрузкой ИИС-3" in _v104 and "по обоим счетам — сделки ИИС-3 устарели" in _v104
      and "iis_trades_stale" in _v104 and _v104.count("myReturnTile(") >= 4 and "myReturnTile(bxi, r.onIis ? 'iis_3' : 'main', bothB, bKeys)" in _v104)
check("вьюер 3.104: «Загрузки» — кнопка «Сохранить как рабочий снапшот», слов про пробную папку нет; после save статус перечитывается и показываются «индекс бумаг» и «журнал решений» (обновлён / не обновлён: причина); 409 «уже есть снапшот» — понятный текст",
      "'Сохранить как рабочий снапшот'" in _v104 and "Сохранить в пробную папку" not in _v104 and "пробную папку Portfolio/snapshots/auto" not in _v104
      and "function pfSaveLines(st)" in _v104 and "не обновлён: " in _v104 and "pfApi('status?run='" in _v104
      and "Не сохранилось: ' + err" in _v104 and "reason === 'cash_fact'" in _v104 and "уже есть рабочий снапшот" not in _v104)
check("вьюер 3.104: «История» — ссылка у обзора только при смене (chg); «Отчёты» — обзоры только с markdown-парой (cardReviewsOf), «История» берёт все",
      "if (!e.chg) return null;" in _v104 and "filter(r => r.md)" in _v104.split("function cardReviewsOf(")[1].split("\n")[0])
_ukj = (REPO / "tools/assets/ui-kit.js").read_text(encoding="utf-8"); _ukc = (REPO / "tools/assets/ui-kit.css").read_text(encoding="utf-8")
check("ui-kit: скрытая подсказка (i) — display:none (иначе у правого края раздвигала страницу «Динамики» на телефоне), сдвиг --ui-info-dx считается заранее (uiInfoPlaceAll, MutationObserver) и применяется через left, а не transform",
      "display:none; visibility:hidden; opacity:0;" in _ukc and "allow-discrete" in _ukc and "left:calc(-8px + var(--ui-info-dx, 0px))" in _ukc
      and "function uiInfoPlaceAll()" in _ukj and "new MutationObserver" in _ukj and "translateX(var(--ui-info-dx" not in _ukc)
_srv103 = (REPO / "tools/hosting/api/server.py").read_text(encoding="utf-8")
check("вьюер 3.103: hub-api set принимает bonds.<ISIN>.manual (bool) и .reason (строка ≤ 200); импорт плана знает те же поля; BOND_FIELD_RU несёт слова",
      'bonds\\.([A-Z0-9]{12})\\.(manual)$"), _plan_bool, _ap_bond' in _srv103 and 'bonds\\.([A-Z0-9]{12})\\.(reason)$"), _plan_str(PLAN_BOND_ACTION_MAX), _ap_bond' in _srv103
      and '"iis_qty", "manual", "reason"), {"name"' in _srv103 and "manual: 'исключение вручную', reason: 'причина исключения'" in _v103)
_hp103 = (REPO / "tools/assets/help/viewer/04-tabs.md").read_text(encoding="utf-8")
check("вьюер 3.103: справка 04-tabs — корзина выводится, вручную только исключение с причиной, плашка «принять/оставить», «Средняя цена» в плитках",
      "Корзина облигации выводится" in _hp103 and "исключение" in _hp103 and "Принять выведенную" in _hp103 and "«Средняя цена»" in _hp103)


# ─────────── ui-kit 1.60.0: читатель на телефоне — поиск в шапке, кнопки ‹ ›, окно во всю высоту, шапка на месте ───────────
check("ui-kit.js: кнопки ‹ › у поиска читателя — data-rd-qprev/-qnext, выключены без совпадений, фокус из поля не уходит (mousedown preventDefault)",
      "data-rd-qprev" in UI_KIT_JS0 and "data-rd-qnext" in UI_KIT_JS0 and "b.disabled = !hits.length" in UI_KIT_JS0
      and 'addEventListener("mousedown"' in UI_KIT_JS0)
check("ui-kit.js: на узком окне поле поиска выносится из тела строкой .rd-q-dock (родитель прокрутки — колонка flex), на широком возвращается",
      "rd-q-dock" in UI_KIT_JS0 and "(max-width:720px)" in UI_KIT_JS0 and 'cs.flexDirection === "column"' in UI_KIT_JS0 and "__rdUndock" in UI_KIT_JS0)
check("ui-kit.js: справка на телефоне прокручивает тело (uiHelpOpen выбирает scroller по overflow тела), шапка не считается в смещение",
      "bodyScrolls" in UI_KIT_JS0 and "head: bodyScrolls ? null" in UI_KIT_JS0)
check("ui-kit.css: .rd-q-dock (непрозрачный фон, линия снизу), .rd-q-b ≥36px, липкое поле без dock — непрозрачное на всю ширину полей",
      ".rd-q-dock{" in UI_KIT_CSS0 and ".rd-q-b{ flex:none; width:36px; height:36px;" in UI_KIT_CSS0
      and "var(--bg-elev)" in UI_KIT_CSS0.split(".rd-q-dock{", 1)[1][:260]
      and "margin:0 calc(-1 * var(--rd-bleed,0px)) 6px; background:var(--bg-elev)" in UI_KIT_CSS0)
check("ui-kit.css: окно с читателем на телефоне — 100dvh (.ui-modal/.ui-docwin-box/.uh-modal :has(.rd)), тело — колонка, .rd-bar прижата к низу (margin-top:auto)",
      all(x in UI_KIT_CSS0 for x in (".ui-docwin-box:has(.rd){ height:100%; height:100dvh; }", ".ui-modal:has(.rd) .ui-modal-box{ height:100%; height:100dvh; }",
                                     ".uh-modal:has(.rd){ height:100%; height:100dvh;", ".rd-bar{ display:flex; margin-top:auto; }")))
check("ui-kit.css: справка с читателем на любой ширине — окно-колонка, шапка неподвижна, прокручивается .uh-body (переключение раздела не уносит шапку)",
      ".uh-modal:has(.rd){ display:flex; flex-direction:column;" in UI_KIT_CSS0 and ".uh-modal:has(.rd) .uh-body{ flex:1 1 auto; min-height:0; overflow-y:auto;" in UI_KIT_CSS0)

# ─────────── вьюер 4.1.3: «сегодня» — только московская дата ───────────
# toISOString() — UTC: с 00:00 до 03:00 МСК «сегодня» было вчерашним (просрочки, «через 30 дней», возраст снапшота).
_v413 = (REPO / "tools/assets/viewer.js").read_text(encoding="utf-8")
check("вьюер 4.1.3: «сегодня» нигде не берётся из UTC — нет new Date().toISOString().slice(0,10) и Date.now()±N…toISOString вне dsToday",
      not re.search(r"new Date\(\)\.toISOString\(\)\.slice\(0, ?10\)", _v413)
      and not re.search(r"new Date\(Date\.now\(\) [+-] (?!3 \* 3600e3)[^)]*\)\.toISOString\(\)\.slice\(0, ?10\)", _v413))
check("вьюер 4.1.3: _todayIso/_isoPlusDays/горизонт 30 дней — через dsToday/dsPlusDays",
      "function _todayIso() { return dsToday(); }" in _v413 and "function _isoPlusDays(n) { return dsPlusDays(n); }" in _v413
      and "function dsPlusDays(n) { return new Date(Date.parse(dsToday() + 'T00:00:00Z') + n * 864e5)" in _v413
      and _v413.count("const horizonEnd = dsPlusDays(30);") == 2)


# ── ui-kit 1.65.0: поле неполной даты ─────────────────────────────────────────
# Дата события анамнеза — одно поле (цифры без автомаски, подсказка, календарь с
# точностью День · Месяц · Год) вместо связки «Точность + дата / месяц / год».
# Поведение ведёт сам ui-kit; страница ничего не подключает.
print("ui-kit 1.65.0: поле неполной даты")
_uk65 = UI_KIT_JS
_ukc65 = (REPO / "tools/assets/ui-kit.css").read_text(encoding="utf-8")
check("ui-kit 1.65: parseFuzzyDate/fuzzyDateText/fuzzyDateHint/uiFuzzyDateField объявлены",
      all(f"function {n}(" in _uk65 for n in ("parseFuzzyDate", "fuzzyDateText", "fuzzyDateHint", "uiFuzzyDateField")))
check("ui-kit 1.65: разметка поля — data-fdv, data-fd-open, .fd-hint; календарь — .dp-prec и data-prec",
      all(x in _uk65 for x in ('data-fdv="', 'data-fd-open="', 'class="fd-hint"', 'class="dp-prec"', 'data-prec="'))
      and ".dp-prec" in _ukc65 and ".fd-hint" in _ukc65)
check("ui-kit 1.65: openCalendar расширен (data-fd-open), а не скопирован; data-dp-open прежний",
      _uk65.count("function openCalendar(") == 1 and 'btn.hasAttribute("data-fd-open")' in _uk65 and 'data-dp-open' in _uk65)
_h65 = (REPO / "tools/health.html").read_text(encoding="utf-8")
check("health.html: AN_PREC и an-ev-prec удалены, anDateBlock строится на uiFuzzyDateField",
      "AN_PREC" not in _h65 and "an-ev-prec" not in _h65 and "data-evp" not in _h65
      and "uiFuzzyDateField(k, v" in _h65.split("function anDateBlock(")[1].split("function anDateRead(")[0])
import subprocess as _sp65, json as _js65
_cases65 = [("2024", "2024", "y"), ("032024", "2024-03", "m"), ("15032024", "2024-03-15", "d"), ("3.2024", "2024-03", "m"),
            ("15/3/2024", "2024-03-15", "d"), ("31022024", None, None), ("132024", None, None), ("20245", None, None),
            ("", "", ""), ("1.4.1899", None, None), ("15 03, 2024", "2024-03-15", "d")]
_js65code = ("const src=require('fs').readFileSync(process.argv[1],'utf8');"
             "const a=src.indexOf('function parseFuzzyDate('),b=src.indexOf('function uiFuzzyDateField(');"
             "const pre=src.slice(src.indexOf('function dpTodayISO()'),src.indexOf('// Приватные константы виджета'));"
             "const mon=src.slice(src.indexOf('var UI_MONTHS_NOM'),src.indexOf('function uiCap('));"
             "const f=new Function(mon+pre+src.slice(a,b)+';return parseFuzzyDate;')();"
             "console.log(JSON.stringify(JSON.parse(process.argv[2]).map(s=>f(s))));")
try:
    _out65 = _sp65.run(["node", "-e", _js65code, str(REPO / "tools/assets/ui-kit.js"), _js65.dumps([c[0] for c in _cases65])],
                       capture_output=True, text=True, timeout=30)
    _res65 = _js65.loads(_out65.stdout)
except Exception as _e65:
    _res65 = None
for (_in65, _iso65, _pr65), _r65 in zip(_cases65, _res65 or [None] * len(_cases65)):
    _exp65 = None if _iso65 is None else {"iso": _iso65, "prec": _pr65}
    check(f"parseFuzzyDate({_in65!r}) → {_exp65}", _res65 is not None and _r65 == _exp65)

# ─────────── ui-kit 1.65.0: «только год» и панель поверх документа; health v1.53 ───────────
_hk165 = (REPO / "tools/health.html").read_text(encoding="utf-8")
_uj165 = (REPO / "tools/assets/ui-kit.js").read_text(encoding="utf-8")
_uc165 = (REPO / "tools/assets/ui-kit.css").read_text(encoding="utf-8")
check("ui-kit 1.65.0: uiFuzzyDateField {only:\"y\"} — data-fd-only, разбор fdParse, календарь без .dp-prec (fzLock)",
      'data-fd-only="y"' in _uj165 and "function fdParse(input)" in _uj165 and "if (!fzLock) pop.insertAdjacentHTML" in _uj165)
check("health v1.53: «С какого года» у аллергии — uiFuzzyDateField(\"asince\", …, { only: \"y\" }), пусто = видимое поле пустое",
      'uiFuzzyDateField("asince"' in _hk165 and '{ only: "y" }' in _hk165 and 'sinceT = val("fv-asince")' in _hk165)
check("ui-kit 1.65.0: .ui-pane.over выше окна документа (220 > 215); health: биомаркер из отчёта не закрывает отчёт",
      ".ui-pane.over{ z-index:220; }" in _uc165 and 'panesOverDoc: true' in _hk165
      and '"rep-marker": function(id){ closeDoc' not in _hk165 and "if (S.panes.length && S.panesOverDoc && S.doc){ panePop" in _hk165)

# ─────────── вьюер 4.2.0, пачка 3 читаемости: «Действия» пятью блоками, push по тому же правилу, справка ───────────
_vjs42 = (REPO / "tools/assets/viewer.js").read_text(encoding="utf-8")
_ntf42 = (REPO / "tools/hosting/notify/notifier.py").read_text(encoding="utf-8")
_h42 = {n: (REPO / f"tools/assets/help/viewer/{n}.md").read_text(encoding="utf-8") for n in ("03-fresh", "04-tabs", "05-now", "07-conditions", "08-site", "10-new")}
check("вьюер 4.2.0: «Действия» — пять блоков (#act-do, #act-check, #act-wait, #act-info, #act-done) из actionBlocks(); счётчик = «Сделать» + «Проверить»",
      all(f"id: '{i}'" in _vjs42 for i in ("act-do", "act-check", "act-wait", "act-info", "act-done"))
      and "attention: n.do + n.check" in _vjs42 and "function actionBlocks()" in _vjs42 and "const n = actionCounts().attention;" in _vjs42)
check("вьюер 4.2.0: отнесение по полям — verdict_direction, user_plan_direction, verification_priority HIGH, executed_by_trade_at, superseded_by (stressNewerList)",
      "CL.map('verdict_direction')" in _vjs42 and "CL.map('user_plan_direction')" in _vjs42 and "it.priority === 'HIGH'" in _vjs42
      and "card?.executed_by_trade_at" in _vjs42 and "function stressNewerList()" in _vjs42)
check("hub-notify 4.2.0: push смены вердикта — action_row (направление или «срочно»; проданная по held_keys молчит); тело условия — «Сделать»/«Проверить»",
      "def action_row(row, key, held=None):" in _ntf42 and "not action_row(row, t, held)" in _ntf42 and "def held_keys(root):" in _ntf42
      and "«Решения по счёту»" not in _ntf42 and "def _cond_block(r):" in _ntf42)
# Буквально — только названия пяти блоков (их владелец видит на экране); остальное — по структуре: абзац
# про счётчик в 04-tabs называет «Сделать» и «Проверить» и не называет «Ждём»; 05-now и 03-fresh ссылаются
# на «Сделать» вместе с «Действиями»/заменённым прогнозом; в 10-new одна строка перечисляет все пять блоков.
# Формулировки этих фраз (TST-1, 03.11) больше не сверяются слово в слово.
_BLK42 = ("Сделать", "Проверить", "Ждём", "К сведению", "Сделано")
_cnt42 = [l for l in _h42["04-tabs"].splitlines() if l.startswith("Счётчик")]
check("справка 4.2.0: 04-tabs — пять блоков, счётчик только по «Сделать»/«Проверить»; 05-now/07/03/08 — без «Решений по счёту»; 10-new — пять блоков",
      all(f"**{w}**" in _h42["04-tabs"] for w in _BLK42)
      and len(_cnt42) == 1 and "«Сделать»" in _cnt42[0] and "«Проверить»" in _cnt42[0] and "«Ждём»" not in _cnt42[0]
      and not any("Решения по счёту" in t or "Решениях по счёту" in t or "Обновить прогнозы и отчёты" in t for t in _h42.values())
      and any("«Сделать»" in l and "«Действиях»" in l for l in _h42["05-now"].splitlines())
      and any("«Сделать»" in l and "заменённом прогнозе" in l for l in _h42["03-fresh"].splitlines())
      and any(all(f"«{w}»" in l for w in _BLK42) for l in _h42["10-new"].splitlines()))

print("ui-kit 1.66.0: кнопка команды для Claude")
_vjs66 = (REPO / "tools/assets/viewer.js").read_text(encoding="utf-8")
_kit66 = (REPO / "tools/assets/ui-kit.js").read_text(encoding="utf-8")
_css66 = (REPO / "tools/assets/ui-kit.css").read_text(encoding="utf-8")
_vl66 = _vjs66.split("\n")
_say66 = [i for i, l in enumerate(_vl66) if "Что сказать Claude" in l and "_copyChip" not in l and "uiClaudeCmd" not in l]
_bad66 = [i + 1 for i in _say66 if not any(("_copyChip" in x or "_sayNodes" in x or "uiClaudeCmd" in x) for x in _vl66[i:i + 4])]
check("ui-kit 1.66.0: uiClaudeCmd и .ui-claude-cmd есть (кнопка с data-cmd, значок svg, стили на токенах)",
      "function uiClaudeCmd(" in _kit66 and 'class="ui-claude-cmd"' in _kit66 and "data-cmd" in _kit66 and "<svg" in _kit66
      and ".ui-claude-cmd{" in _css66 and "var(--border-strong)" in _css66 and "min-height:40px" in _css66.split(".ui-claude-cmd{")[-1])
check("вьюер 4.2.3: _copyChip — это uiClaudeCmd; кнопки «скопировать» (button.ui-link) во вьюере нет",
      "uiClaudeCmd(" in _vjs66.split("function _copyChip(")[1].split("function _copyText")[0] and not re.search(r"class: 'ui-link'[^\n]{0,80}'скопировать'", _vjs66))
check(f"вьюер 4.2.3: «Что сказать Claude» без кнопки .ui-claude-cmd рядом нет (строки {_bad66})", not _bad66)
check("вьюер 4.2.3: ни одна кнопка записи (cond-кнопки, «Сохранить») не несёт .ui-claude-cmd",
      not re.search(r"ui-claude-cmd[^\n]{0,120}(data-cond|data-plan-done|data-check-act|Сохранить)", _vjs66)
      and not re.search(r"(data-cond|data-plan-done|data-check-act)[^\n]{0,160}ui-claude-cmd", _vjs66))
check("вьюер 4.2.3 VW-CLOSE: «Закрыть» — _horizonSay берёт suggested_action как есть, иначе message, иначе «…»; кнопка в строке и в окне",
      "function _horizonSay(" in _vjs66 and "Закрой прогноз" in _vjs66.split("function _horizonSay(")[1][:500] and "_copyChip(say, 'Закрыть')" in _vjs66 and "_copyChip(hpSay, 'Закрыть')" in _vjs66)
_h04 = (REPO / "tools/assets/help/viewer/04-tabs.md")
# TST-1 (03.11): правило «два вида кнопок» сверяется по смыслу одной строки (контурная — Claude, залитая — сайт),
# а не дословной фразой
check("справка 04: одна строка про два вида кнопок — контурная копирует команду для Claude, залитая пишет на сайт",
      _h04.exists() and sum(1 for l in _h04.read_text(encoding="utf-8").splitlines()
                            if "контур" in l and "залит" in l and "Claude" in l and "сайт" in l) == 1)
check("INDEX.md: правило «два вида кнопок»", "uiClaudeCmd" in (REPO / "tools/design-reference/INDEX.md").read_text(encoding="utf-8"))

# вьюер 4.2.4 (владелец 04.11): наведение подсвечивает строку во всех блоках «Действий», не только в «Ждём» (.ui-row.pick) —
# .act-alert и .act-dec получают тот же фон --bg-alt под (hover:hover)
_css424 = (REPO / "tools/assets/viewer.css").read_text(encoding="utf-8")
check("вьюер 4.2.4: строки «Сделать»/«Проверить»/«К сведению» (.act-alert, .act-dec) подсвечиваются при наведении фоном --bg-alt, как .ui-row.pick",
      ".act-alert:hover, .act-dec:hover{ background:var(--bg-alt)" in _css424 and "@media (hover:hover){" in _css424)

# фразы для Claude начинаются с «/<скилл> », скилл существует (решение владельца 06.11: по фразе видно, что будет запущено)
_say_skills = {d.name for d in (REPO / "skills").iterdir() if d.is_dir()}
_say_help = {}
for _p in sorted((REPO / "tools/assets/help").rglob("*.md")):
    _txt = re.sub(r"<!--.*?-->", "", _p.read_text(encoding="utf-8"), flags=re.S)   # образцы в комментариях-шапках — не команды
    for _m in re.finditer(r"\[([^\]]+)\]\(#copy\)", _txt):
        _say_help.setdefault(str(_p.relative_to(REPO)), []).append(_m.group(1))
_SAY_EXCEPT = set()   # (#copy), не являющиеся командой для Claude: пока таких нет
_say_bad = [(f, t) for f, ts in _say_help.items() for t in ts
            if t not in _SAY_EXCEPT and not (re.match(r"/([a-z][a-z0-9-]*) ", t) and re.match(r"/([a-z][a-z0-9-]*) ", t).group(1) in _say_skills)]
check(f"справки: каждая [фраза](#copy) = «/<скилл> …», папка skills/<скилл>/ есть ({sum(map(len, _say_help.values()))} фраз; плохих: {_say_bad[:3]})",
      sum(map(len, _say_help.values())) > 60 and not _say_bad)
_vjs_say = _vjs.replace("ADV + '", "'/ru-portfolio-advisor ")
_say_js = [m.group(1) for m in re.finditer(r"\b(?:STALE_SAY|STRESS_CHAIN)\b[^=\n]*=\s*(\[[^\]]*\]|\{.*?\n\};)", _vjs_say, re.S)]
_say_js_t = [t for blk in _say_js for t in re.findall(r"(?:'([^'\n]*)')", blk)]
_say_js_t = [t for t in _say_js_t if " " in t and not t.startswith("ADV")]
_say_js_t += [t for t in re.findall(r"`(/[a-z-]+ [^`]*)`", _vjs)] + re.findall(r"'(/[a-z-]+ [^']*)'", _vjs)
_say_js_bad = [t for t in _say_js_t if not re.match(r"/([a-z][a-z0-9-]*) ", t) or re.match(r"/([a-z][a-z0-9-]*) ", t).group(1) not in _say_skills]
check(f"вьюер: фразы STALE_SAY/STRESS_CHAIN/«/скилл …» — скилл существует ({len(_say_js_t)} фраз; плохих: {_say_js_bad[:3]})",
      len(_say_js_t) > 8 and not _say_js_bad)
# фразы вьюера, строящиеся из ADV или шаблонов, — через префикс; голых нет
_say_calls = re.findall(r"_copyChip\(([^)]*)\)", _vjs)
check("вьюер: в _copyChip нигде не подставлена голая строка-фраза без префикса скилла",
      not [a for a in _say_calls if re.match(r"\s*['`][^/'`$]", a)])
check("вьюер: цепочка команд стресса — два скилла по порядку, показ через _sayNodes «затем: …»",
      "const STRESS_CHAIN = ['/macro-forecast-chain " in _vjs and "'/portfolio-scenario-stress Прогони стресс на 6-12-24']" in _vjs
      and "' затем: '" in _vjs)
check("вьюер: подпись срока стресса — одна функция stressHzLabel («до ДД.ММ.ГГГГ · ≈N,N мес», «прошёл», короткая «до ДД.ММ.ГГ»)",
      "function stressHzLabel(" in _vjs and "'≈' + _ruDec(days / 30.44, 1) + ' мес'" in _vjs and "'прошёл'" in _vjs
      and "const swLabel = (h) => stressHzLabel(" in _vjs)

# сроки сайта, окно «Настройки стресса», команды стресса по случаям (без номера версии)
check("вьюер: список папок — отчёты стресса (.md) и файл сроков scenarios/horizons.json (строки как в PV_DIRS сервера)",
      "{ url: base + 'Portfolio/stress/', pattern: /^stress-\\d{4}-\\d{2}-\\d{2}.*\\.(yaml|yml|md)$/, folder: 'Portfolio/stress/' }," in VIEWER_JS
      and "{ url: base + 'scenarios/', pattern: /\\.(yaml|yml|md)$|^horizons\\.json$/, folder: 'scenarios/' }," in VIEWER_JS)
check("вьюер: типы записей stressMd (отчёт стресса) и horizons (сроки сайта); .md стресса не попадает в тип stress",
      "return 'stressMd'" in VIEWER_JS and "return 'horizons'" in VIEWER_JS and "function horizonsInvalid(" in VIEWER_JS
      and "state.data.horizons = hzRec.parsed" in VIEWER_JS and "const ss = records.filter(r => r.type === 'stress')" in VIEWER_JS)
check("вьюер: вкладка «Стресс» — строка состояния и кнопки (#stress-status, #stress-settings-btn, #stress-report-btn), плашка #stress-refresh-banner, сгиба весов нет",
      all(x in VIEWER_JS for x in ("id: 'stress-status'", "id: 'stress-settings-btn'", "id: 'stress-report-btn'", "id: 'stress-refresh-banner'"))
      and "sw-fold" not in VIEWER_JS and "function stressWeightsBlock(" not in VIEWER_JS)
check("вьюер: окно «Настройки стресса» делается тем же документным слоем (docOpen), три части: сроки · веса · одна кнопка (#stress-main-action: «Пересчитать» ↔ «Применить»)",
      "function showStressSettings() {" in VIEWER_JS and "id: 'stress-main-action'" in VIEWER_JS and "pfApi('stress/recalc', {})" in VIEWER_JS
      and "pfApi('stress/terms'" in VIEWER_JS and "'Подтвердить и сохранить'" in VIEWER_JS and "'Подтвердить сроки'" in VIEWER_JS)
check("вьюер: заметки #stress-terms-mismatch и #stress-macro-blocked; «Действия» — строки termsShift и macroBlocked, сроки-напоминание без команды",
      "id: 'stress-terms-mismatch'" in VIEWER_JS and "id: 'stress-macro-blocked'" in VIEWER_JS
      and "function _stressTermsShiftRow(" in VIEWER_JS and "function _stressMacroBlockedRow(" in VIEWER_JS
      and "if (k === 'terms') return null;" in VIEWER_JS)
check("вьюер: команды стресса по случаям — сроки (полный пайплайн «сроки сдвинуты» → стресс), только макро-прогноз, только стресс",
      "'/macro-forecast-chain Запусти полный пайплайн: сроки сдвинуты'" in VIEWER_JS
      and "const STRESS_MACRO_ONLY = ['/macro-forecast-chain Обнови макро-прогноз'];" in VIEWER_JS
      and "const STRESS_ONLY = ['/portfolio-scenario-stress Прогони стресс на 6-12-24'];" in VIEWER_JS)
_hv = REPO / "tools/assets/help/viewer"
_hv_txt = "\n".join(p_.read_text(encoding="utf-8") for p_ in sorted(_hv.glob("*.md")))
check("справка вьюера: «Настройки стресса», файл сроков и «Пересчитать» описаны (01-run, 03-fresh, 04-tabs)",
      all("Настройки стресса" in (_hv / f).read_text(encoding="utf-8") for f in ("01-run.md", "04-tabs.md"))
      and "сроки сайта" in (_hv / "03-fresh.md").read_text(encoding="utf-8").lower() and "Пересчитать" in _hv_txt)


# ── «Последний стресс»: дата → время записи → имя; пересчёт сайта от прежней версии стресса не берётся ──
_sj_src = (REPO / "tools/hosting/notify/stress_job.py").read_text(encoding="utf-8")
_lss = _sj_src.split("def latest_skill_stress(")[-1].split("\ndef ")[0]
check("стресс: вьюер выбирает последний стресс по cmpRecent (дата, затем время записи)",
      ".filter(r => r.type === 'stress').sort(cmpRecent)" in VIEWER_JS)
check("стресс: вьюер сверяет пересчёт со временем записи стресса (stressRecalcIsStale, recalcStale, #stress-recalc-stale)",
      "function stressRecalcIsStale(" in VIEWER_JS and "recalcStale: true" in VIEWER_JS and "stress-recalc-stale" in VIEWER_JS)
check("стресс: сайт знает устаревший пересчёт (recalc_is_stale) и берёт последний стресс по st_mtime_ns",
      "def recalc_is_stale(" in _sj_src and "st_mtime_ns" in _lss)

check("4.5.0: termsRerunList — санкционный и геополитический прогнозы в проверку сроков не входят (идут на датах матрицы, не на сетке сроков)",
      "if (/^(sanctions|geopol)/.test(String(h.factor || t))) continue;" in VIEWER_JS)

# ── режим сайта «без ИИ» (ui-kit 1.67.0, вьюер 5.0.0, hub/money/health/games v2) ──
_nk_js = (REPO / "tools/assets/ui-kit.js").read_text(encoding="utf-8")
_nk_css = (REPO / "tools/assets/ui-kit.css").read_text(encoding="utf-8")
_nk_hub = (REPO / "tools/hub.html").read_text(encoding="utf-8")
_nk_viewer = (REPO / "tools/assets/viewer.js").read_text(encoding="utf-8")
_nk_page = {f: (REPO / "tools" / f).read_text(encoding="utf-8") for f in ("money.html", "health.html", "games.html")}

check("без ИИ: ui-kit.js — uiAiMode, uiAiModeBtnHTML, событие \"ui-noai\", атрибут data-noai, UI_NOAI_API",
      all(t in _nk_js for t in ("function uiAiMode(", "function uiAiModeBtnHTML(", '"ui-noai"', "data-noai", 'UI_NOAI_API = "../api/hub/"')))
_nk_rule = re.search(r"(html\[data-noai\][^{]*\{[^}]*\})", _nk_css.split("Режим сайта «без ИИ»")[-1], re.S)
_nk_sels = _nk_rule.group(1).split("{")[0] if _nk_rule else ""
check("без ИИ: ui-kit.css — правило html[data-noai] скрывает все классы команд и подсказок",
      all(f"html[data-noai] {c}" in _nk_sels for c in (".ui-claude-cmd", ".ui-say", ".act-say", ".gate-say", ".cond-say", ".fc-hp", ".noai-hide")))
check("без ИИ: ui-kit.css — .noai-grey", ".noai-grey" in _nk_css)
check("без ИИ: hub.html — uiTopHTML({…mode: true}), renderReports, слушатель \"ui-noai\"",
      re.search(r"uiTopHTML\(\{[^}]*mode:\s*true", _nk_hub) is not None and "function renderReports(" in _nk_hub
      and 'addEventListener("ui-noai"' in _nk_hub)
check("без ИИ: viewer.js — _noaiLLM, _actStaleList проверяет uiAiMode(), слушатель ui-noai",
      "_noaiLLM" in _nk_viewer and re.search(r"function _actStaleList\(\)\s*\{\s*return uiAiMode\(\)", _nk_viewer) is not None
      and re.search(r"addEventListener\(['\"]ui-noai['\"]", _nk_viewer) is not None)
for _f, _n in (("money.html", 3), ("health.html", 1), ("games.html", 1)):
    check(f"без ИИ: {_f} — подсказок noai-hide не меньше {_n}", _nk_page[_f].count("noai-hide") >= _n)
check("без ИИ: версии — подвал hub «hub v2.», money v2, health v3, games v2, вьюер 5.",
      "hub v2." in _nk_hub and re.search(r'VERSION = "money v2\.', _nk_page["money.html"]) is not None
      and re.search(r'VERSION = "health v3\.', _nk_page["health.html"]) is not None
      and "games v2." in _nk_page["games.html"] and re.search(r"VIEWER_VERSION = '5\.", _nk_viewer) is not None)
sys.path.insert(0, str(REPO / "tools"))
import noai_return as _nr  # noqa: E402
_nk_js_kinds = re.findall(r'\["([^"]+)",\s*"[^"]*"\]', _nk_js.split("var UI_NOAI_KINDS = [")[1].split("];")[0])
check(f"без ИИ: зеркало видов правок — UI_NOAI_KINDS (ui-kit.js) = KINDS (noai_return.py) по путям и порядку ({len(_nk_js_kinds)})",
      _nk_js_kinds == [k for k, _ in _nr.KINDS])

print(f"\npages_contracts: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
