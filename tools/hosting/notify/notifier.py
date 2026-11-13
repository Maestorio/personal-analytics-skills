#!/usr/bin/env python3
"""hub-notify — push-уведомления вьюера портфеля на телефон (v3-B, план — docs/investment/TODO_design.md §6).

Третий контейнер рядом с Caddy и hub-api. Два дела:

1. HTTP :8001 (наружу не публикуется; Caddy проксирует /api/push/* — с паролем с ЛЮБОГО IP,
   как здоровье: события портфеля приватны, подписаться без пароля нельзя):

     GET  /api/push/key                  → {"public_key", "mode", "devices"} — ключ VAPID для подписки
     POST /api/push/subscribe            → тело {"subscription": PushSubscription.toJSON(), "label"?}
     POST /api/push/unsubscribe          → тело {"endpoint"}
     POST /api/push/test                 → пробное уведомление сразу на ВСЕ подписанные устройства (и в тихом
                                            режиме) → {"ok", "results": [{"label", "ok", "push_status"}]}
     POST /api/push/mode                 → тело {"mode": "quiet" | "live"}
     POST /api/push/prune                → тело {"keep"?: endpoint} — убрать все подписки, кроме keep
                                            (накопленные пересозданием ярлыка и тестами)
     POST /api/push/settings             → тело {"off": [вид, …]} — какие виды уведомлений выключены (KINDS)
     GET  /api/push/status?endpoint=…&section=… → {"mode", "off", "kinds" (с section), "sections", "subscribed",
                                            "devices", "last_daily", "last_hourly", "log": [...]} — section
                                            (portfolio | games): журнал только этого раздела
     GET  /internal/health               → {"version", "code"} — отпечаток кода при старте (codehash.py);
                                            наружу не проброшен, читает hub-api для /api/health → deploy.zsh
     POST /api/pf/condition — условие-напоминание владельца, add / withdraw (condition_job.py) → Portfolio/conditions.yaml (conditions@2, source owner)
     POST /api/pf/decision — решение владельца с карточки бумаги (decision_job.py) → Portfolio/decisions/ (decision@1, owner)
     POST /api/pf/build, GET /api/pf/status, POST /api/pf/save, POST /api/pf/cancel — сборка снапшота с вьюера (п. 3, pf_build.py;
                                            Caddy проксирует /api/pf/* сюда с паролем с любого IP, как /api/push/*)

2. Проверяльщик (без Claude; читает те же файлы, что вьюер, том /srv только на чтение):
   * раз в день (NOTIFY_DAILY_AT, по умолчанию 08:30 MSK; пропущенный из-за перезапуска — догоняется),
     НЕ БОЛЬШЕ ТРЁХ уведомлений (решения владельца 2026-10-16 и 2026-10-26):
       0) состояние условий (шаг 7 цикла машиночитаемости; условия читаются ТОЛЬКО модулем (а)
          `conditions_merge` — определения `conditions@2` + состояние `conditions-state.json`): срок, вычисленный
          модулем при чтении, пишется событием во внутренний маршрут hub-api (дата наступила / окно отчёта
          закрылось → fired с data.by_deadline, valid_until прошёл → expired); находки последнего отчёта
          монитора (condition_findings[]) → event_found + fired с data.doc; новые решения Portfolio/decisions/
          с conditions_resolved[] → done (by: site, data.decision_id). Очередь событий — в state.json
          (cond_outbox), повторы гасит сервер; done по сделке — не делается (отложено);
       1) события — смены вердикта в свежем обзоре акций/облигаций (ОДНО уведомление на обзор и вид,
          нажатие — «Изменения»; смены по решению владельца — сделки обзора, done/dismissed по условиям бумаги,
          строки журнала плана stocks.*.user_status|user_plan, bonds.<ISIN>.*, funds.<тикер>.* между обзорами — не считаются), новое HIGH монитора
          (нажатие — «Действия» и окно с полным текстом новых), находка монитора по условию; одно событие —
          как есть, несколько — сводкой (нажатие — журнал);
       1а) «Ждут решения» — ОДНО сообщение на условие при переходе в «ждёт владельца» (waits_owner модуля;
          ключ cond:<id>@<version>:fired — тот же у часовой цены), несколько — сводкой; нажатие — «Действия»;
       2) просроченные отчёты — файл старше порога «пора обновить» (жёлтая плашка вьюера) или
          «скиллы не работают» (красная) — те же числа, что STALE_THRESHOLDS_DAYS / STALE_FAIL_DAYS
          вьюера; каждый уровень по каждому файлу — один раз; макро — недельная инфляция
          (macro-snapshots/inflation/*.jsonl, дата записи внутри; пороги 9/16 дней), автосрез не меряется;
       2а) «Пора внести инфляцию» (macro_infl) — только при «без ИИ»: недельная инфляция старше 9 дней, раз в неделю,
          нажатие — «Макро» (форма «Внести инфляцию»); при «с ИИ» то же просроченное идёт видом stale с командой для Claude;
   * раз в час в будни 10:00–18:59 MSK — ценовые условия (pending, не раньше not_before) по ценам MOEX
     из hub-api (/api/moex/quotes — тот же источник и кэш, что «живые цены» вьюера); порог пересечён —
     событие fired (data.price, version) и push.

3. Задачи сайта без Claude (API-1, пробный месяц с 2026-10-21; модули jobs.py, eshop.py, macro_job.py):
   * цены US eShop для «Присматриваюсь» — каждый день в NOTIFY_DAILY_AT → Gaming/eshop-prices.json;
     порог цены выполнен впервые — push вида «eshop», игра ушла в скидку — «eshop_sale» (сводкой); кнопка games.html «Обновить цены» —
     POST /internal/eshop-refresh (только из docker-сети, через hub-api), не чаще раза в 10 минут;
   * макросрез РФ (build_macro.py скилла macro-ru-watcher) — по будням в то же время →
     macro-snapshots/auto/ru-<дата>.md + .json;
   * дневной ряд цен закрытия держимых бумаг и курсов ЦБ (prices_job.py, только вперёд, с 2026-11-11) — по будням
     в 19:00 (повтор 20:00 при сбое) → Portfolio/prices/daily-ГГГГ.jsonl, одна строка на торговую дату;
   * сборка снапшота портфеля с вьюера (pf_build.py, PR-6, пробный режим) — POST /api/pf/build
     (файлы base64) → build_snapshot.py скилла portfolio-data-loader в фоне, GET /api/pf/status,
     POST /api/pf/save → Portfolio/snapshots/auto/ (не в рабочую папку снапшотов);
   * выгрузка CSV ZenMoney (zm_csv.py, этап «Деньги» 3.6) — POST /internal/zm-csv-report {id} (отчёт: полнота, diff,
     месяцы и поездки к записи) и POST /internal/zm-csv-apply {id, confirm:true} (запись истории и last.csv; 409 —
     нет отчёта, стопы, нет confirm, файл ≠ отчёту), POST /internal/zm-rule (правило «разовая» с сайта) и
     POST /internal/zm-trip (поездка без ID из отчёта); только из docker-сети через hub-api; журнал job=zm-csv;
   * сверка выписки банка (zm_stmt.py, задача 3.8) — POST /internal/zm-stmt-report {id}: разбор файла из
     ZenMoney/csv/stmt-incoming/ скриптами скилла, отчёт zm-stmt-report@1 ответом; ничего не пишет; журнал job=zm-stmt
     (только числа и банк);
   * неудача — один повтор в JOBS_RETRY_AT (09:00); каждый прогон — строка в _jobs/log-ГГГГ-ММ.jsonl;
     ежедневный проход самого уведомителя — строка job=notify-daily (conds, events, pushed, stale; сбой — ok=false, error);
     пишет hub-api (/api/job/*, копия прежней версии в .versions/); выключатель — JOBS_OFF.

Виды уведомлений (KINDS) выключаются во вьюере («Ещё → Уведомления»): выключенное пишется в журнал
как «выключено» и считается отработанным — включение не вываливает накопленное.

Без спама: событие — ключ; ключ отрабатывается ОДИН раз (state.json, «уже сообщено»).
Одинаковые события по одной бумаге — не чаще раза в 7 дней (rate-ключ). В тихом режиме
(дефолт, первую неделю) событие пишется в журнал «было бы отправлено» и считается отработанным:
включение отправки не вываливает накопленное.

Шифрование Web Push (RFC 8291, aes128gcm) и подпись VAPID (RFC 8292) — на `cryptography`;
PyYAML — для conditions/обзоров; модуль (а), кодлисты, время и валидаторы схемы — из pdl/_shared-references. Обе ставятся при первом старте в том /deps (см. docker-compose.yml).
Логика проверок — чистые функции (tools/tests/test_notifier.py гоняет их без сети и без контейнера).
"""
import base64
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import codehash
import eshop
import eshop_lookup
import jobs
import macro_job
import prices_job
import pf_build
import stress_job
import decision_job
import condition_job
import zm_csv
import zm_stmt


def _shared_dir():
    """Каталог общих модулей схемы данных (conditions_merge, codelists, time_msk, ds_schemas): в контейнере —
    `pdl/_shared-references/` рядом с notifier.py (deploy.zsh), в репозитории — `../../../_shared-references`.
    Нет ни одного — ошибка при старте: без модуля (а) условия не читаются."""
    here = Path(__file__).resolve().parent
    for cand in (here / "pdl" / "_shared-references", here.parent.parent.parent / "_shared-references"):
        if (cand / "conditions_merge.py").is_file() and (cand / "codelists.json").is_file():
            return cand
    raise FileNotFoundError("notifier: нет conditions_merge.py и codelists.json ни в pdl/_shared-references, ни в _shared-references/")


sys.path.insert(0, str(_shared_dir()))
import codelists  # noqa: E402
import conditions_merge as CMRG  # noqa: E402 — модуль (а): объединение определений и состояния условий
import decisions_read  # noqa: E402 — «есть в портфеле» (held_keys = snapshot_keys модуля (б), правило 14)
import ds_schemas  # noqa: E402
import hub_settings  # noqa: E402 — режим сайта «с ИИ / без ИИ» (_hub/settings.json)
import time_msk  # noqa: E402

VERSION = "1.12.1"
MSK = timezone(timedelta(hours=3))

ROOT = Path(os.environ.get("NOTIFY_ROOT", "/srv"))            # Claude-Memory (ro)
DATA = Path(os.environ.get("NOTIFY_DATA", "/data"))           # ключи, подписки, состояние, журнал
PORT = int(os.environ.get("NOTIFY_PORT", "8001"))
QUOTES_URL = os.environ.get("NOTIFY_QUOTES_URL", "http://hub-api:8000/api/moex/quotes?boards=TQBR,TQOB,TQCB")
# события условий пишет только hub-api (внутренний маршрут, состояние conditions-state.json); определения conditions.yaml
# уведомлятель читает с тома /srv (только чтение) и не правит
COND_URL = os.environ.get("NOTIFY_COND_URL", "http://hub-api:8000/api/pv/cond/event/internal")
COND_AUTH = os.environ.get("NOTIFY_COND_AUTH", "Basic bm90aWZ5Og==")   # hub-api требует лишь наличие заголовка (сеть compose)
DAILY_AT = os.environ.get("NOTIFY_DAILY_AT", "08:30")
# sub VAPID уходит в push-сервис (Apple/Google): адрес кабинета, не почта
VAPID_SUB = os.environ.get("NOTIFY_VAPID_SUB", "https://hub.example.com")
DEFAULT_MODE = os.environ.get("NOTIFY_MODE", "quiet")
VIEWER = "/tools/portfolio-integrated-viewer.html"

TRADING_HOURS = range(10, 19)      # основная сессия MOEX, MSK
RATE_DAYS = 7                       # одинаковые события по бумаге — не чаще
MAX_PUSH_PER_RUN = 4                # больше — последние сворачиваются в одно «и ещё N»
LOG_KEEP = 300
SENT_KEEP_DAYS = 400

# Виды уведомлений — их можно выключать во вьюере. ⚠ SYNC: подписи живут только здесь
# (вьюер берёт их из /api/push/status), id — в событиях ниже.
KINDS = [
    {"id": "cond_open", "section": "portfolio", "label": "Ждут решения",
     "desc": "условие сработало и ждёт твоего решения: наступила дата, закрылось окно отчёта — один раз на условие"},
    {"id": "cond_date", "section": "portfolio", "label": "Отчёт под условие", "desc": "вышел отчёт или событие, которого ждёт условие"},
    {"id": "cond_price", "section": "portfolio", "label": "Ценовые условия", "desc": "цена дошла до порога условия (раз в час в торговые часы)"},
    {"id": "verdict", "section": "portfolio", "label": "Смена вердикта", "desc": "в свежем обзоре акций или облигаций сменились вердикты — одним уведомлением на обзор; смены по твоему решению не в счёт"},
    {"id": "monitor", "section": "portfolio", "label": "Монитор", "desc": "новое важное (HIGH) предупреждение монитора прогнозов"},
    {"id": "stale", "section": "portfolio", "label": "Просроченные отчёты",
     "desc": "отдельным уведомлением утром — обзор, стресс, снапшот, монитор, интеграционный анализ или недельная инфляция старше своего порога"},
    # «Напоминать заранее» (group ahead): даты по держимым бумагам, утренний проход, одной сводкой (check_ahead)
    {"id": "ahead_review", "section": "portfolio", "group": "ahead", "label": "Срок решения",
     "desc": "подходит срок пересмотра решения или гейта акции — за 7 дней и в день срока"},
    {"id": "ahead_offer", "section": "portfolio", "group": "ahead", "label": "Оферта облигации",
     "desc": "у облигации в портфеле скоро оферта — за 14 и за 3 дня"},
    {"id": "ahead_maturity", "section": "portfolio", "group": "ahead", "label": "Погашение облигации",
     "desc": "облигация в портфеле скоро погашается — за 7 дней"},
    {"id": "ahead_pause", "section": "portfolio", "group": "ahead", "label": "Конец паузы докупки",
     "desc": "закончилась пауза докупки или IPO-пауза — в день окончания: снова можно докупать"},
    # Только при ai_mode off (при on «акция без разбора» — работа обзора советника): акция без единого решения закрыта
    # для докупки, снимает блок решение владельца (кнопка «Записать решение»). Не «заранее» — группы нет.
    {"id": "no_decision", "section": "portfolio", "label": "Бумага без решения",
     "desc": "только в режиме «без ИИ»: акция в портфеле без единого решения — докупка закрыта, пока не запишешь решение; одной сводкой утром, по бумаге не чаще раза в неделю"},
    # Только при ai_mode off (при on просроченную инфляцию сообщает вид stale с командой для Claude): недельная инфляция старше 9 дней
    {"id": "macro_infl", "section": "portfolio", "label": "Пора внести инфляцию",
     "desc": "только в режиме «без ИИ»: недельная инфляция не вносилась больше 9 дней — раз в неделю, нажатие ведёт к форме «Внести инфляцию» на вкладке «Макро»"},
    {"id": "eshop", "section": "games", "label": "Цены игр",
     "desc": "у игры из «Присматриваюсь» впервые выполнен порог — цена ≤ $X или скидка ≥ N% (US eShop, утренняя загрузка цен)"},
    {"id": "eshop_sale", "section": "games", "label": "Скидки на игры",
     "desc": "игра из «Присматриваюсь» ушла в скидку — любая, с порогом и без (US eShop, утренняя загрузка цен); несколько — одним уведомлением"},
]
KIND_IDS = [k["id"] for k in KINDS]
CODE_HASH = codehash.code_hash(Path(__file__).parent)   # код, с которым контейнер стартовал
# Разделы кабинета: переключатели видов и журнал — на странице раздела (ui-kit uiPushMount),
# устройства и режим — в hub. Запись журнала без вида (старые) — портфель.
SECTIONS = [{"id": "portfolio", "label": "Портфель", "url": "/tools/portfolio-integrated-viewer.html#tab=notify"},
            {"id": "games", "label": "Игры", "url": "/tools/games.html#notify"}]
KIND_SECTION = {k["id"]: k["section"] for k in KINDS}


def log_for(log, section=None, n=40):
    """Последние n записей журнала (новые первыми); section — только этого раздела."""
    if section:
        log = [r for r in log if KIND_SECTION.get(r.get("kind") or "", "portfolio") == section]
    return log[-n:][::-1]

# ⚠ SYNC: те же числа — STALE_THRESHOLDS_DAYS и STALE_FAIL_DAYS в tools/assets/viewer.js
# (сторож — test_notifier.py). Первый — «пора обновить», второй — «скиллы на нём не работают».
STALE_WARN_DAYS = {"stocks": 14, "bonds": 14, "stress": 30, "portfolio": 7, "monitor": 10,
                   "integratedView": 30, "macro": 9}
STALE_FAIL_DAYS = {"stocks": 30, "bonds": 30, "stress": 60, "portfolio": 30, "macro": 16}   # macro: красная плашка, не «скиллы не работают»
STALE_LABEL = {"stocks": "обзор акций", "bonds": "обзор облигаций", "stress": "стресс-тест",
               "portfolio": "снапшот портфеля", "monitor": "монитор", "integratedView": "интеграционный анализ",
               "macro": "недельная инфляция"}
STALE_FILES = {   # kind → (папка, шаблон имени); дата — из имени, как у вьюера
    "stocks": ("Portfolio/weekly-reviews", r"^weekly-review-stock-(\d{4}-\d{2}-\d{2}).*\.ya?ml$"),
    "bonds": ("Portfolio/weekly-reviews", r"^weekly-review-bond-(\d{4}-\d{2}-\d{2}).*\.ya?ml$"),
    "stress": ("Portfolio/stress", r"^stress-(\d{4}-\d{2}-\d{2}).*\.ya?ml$"),
    "portfolio": ("Portfolio/snapshots", r"^portfolio-(\d{4}-\d{2}-\d{2}).*\.json$"),
    "monitor": ("monitor-reports", r"^monitor-report-(\d{4}-\d{2}-\d{2}).*\.ya?ml$"),
    "integratedView": ("Portfolio/integrated-views", r"^integrated-view-(\d{4}-\d{2}-\d{2}).*\.md$"),
    "macro": ("macro-snapshots/inflation", r"^(model|owner)\.jsonl$"),   # дата — внутри строк (infl_latest), не в имени
}


# ─────────────────────────── чтение файлов ───────────────────────────
def _yaml():
    import yaml   # noqa: E402 — из /deps, ставится при старте контейнера
    return yaml


def dated_files(root, folder, pattern):
    """[(дата 'YYYY-MM-DD', Path)] по возрастанию даты из имени."""
    d = Path(root) / folder
    rx = re.compile(pattern)
    out = []
    try:
        for p in d.iterdir():
            m = rx.match(p.name)
            if m and p.is_file():
                out.append((m.group(1), p))
    except FileNotFoundError:
        return []
    return sorted(out, key=lambda x: (x[0], x[1].name))


def load_yaml(path):
    try:
        with open(path, encoding="utf-8") as f:
            return _yaml().safe_load(f)
    except (OSError, Exception):   # битый файл не роняет проверку остальных
        return None


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _s(v):
    """YAML-даты (date) и числа → строка 'YYYY-MM-DD' / как есть."""
    if isinstance(v, (date, datetime)):
        return v.isoformat()[:10]
    return None if v is None else str(v)


def _ddmm(s):
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(s or ""))
    return f"{m.group(3)}.{m.group(2)}" if m else str(s or "")


def _short(t, n=150):
    t = re.sub(r"\s+", " ", str(t or "")).strip()
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def _num(x):
    v = float(x)
    s = f"{v:,.2f}".rstrip("0").rstrip(".") if v < 10 else f"{v:,.1f}".rstrip("0").rstrip(".")
    return s.replace(",", " ").replace(".", ",")


def _card(ticker):
    return f"{VIEWER}#card={urllib.parse.quote(str(ticker))}"


# ─────────────── читаемость на экране блокировки ───────────────
# Правила для ВСЕХ видов: заголовок ≤ TITLE_MAX знаков и сам отвечает «что случилось» (в свёрнутом
# уведомлении телефона видна только его первая строка); тело — не больше двух коротких строк
# (что сделать и где) или по пункту «• …» на строку у сводки; без ISIN и кодов вердиктов.
TITLE_MAX = 32


def _load_codelists():
    """Кодлисты (`codelists.json`, schema.md §3.4) — загрузчиком codelists.py из того же каталога общих модулей
    (_shared_dir), что и модуль (а). Нет файла — ошибка при старте: без словаря вердиктов текст нечитаем."""
    return codelists.load(str(_shared_dir() / "codelists.json"))


_CODELISTS = _load_codelists()
# Вердикты словами в нижнем регистре — кодлист verdict (с legacy-кодами облигаций).
VERDICT_WORD = {c: e["ru"].lower() for c, e in _CODELISTS["lists"]["verdict"].items()}
# Направление вердикта (кодлист maps.verdict_direction): up/down — сделка, flat — без направления.
VERDICT_DIR = dict(_CODELISTS["maps"]["verdict_direction"])
_ISIN_RX = re.compile(r"\b[A-Z]{2}[0-9A-Z]{9}[0-9]\b")
# длинные коды раньше коротких (HOLD_TO_MAT раньше HOLD)
_VCODE_RX = re.compile(r"\b(" + "|".join(sorted(map(re.escape, VERDICT_WORD), key=len, reverse=True)) + r")\b")


def _fit(t, n=TITLE_MAX):
    t = re.sub(r"[ \t\r\n]+", " ", str(t or "")).strip()   # неразрывные пробелы в числах остаются
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def _clip(text, n=180):
    """Тело: строки сохраняются (в отличие от _short), общий предел n знаков."""
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in str(text or "").split("\n")]
    t = "\n".join(ln for ln in lines if ln)
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def plain(text, names=None):
    """Текст для человека: ISIN → имя бумаги (нет имени — «бумага»), BUY/HOLD/… → «докупать/держать»."""
    names = names or {}
    t = _ISIN_RX.sub(lambda m: names.get(m.group(0)) or "бумага", str(text or ""))
    return _VCODE_RX.sub(lambda m: VERDICT_WORD[m.group(1)], t)


def _is_isin(t):
    return bool(_ISIN_RX.fullmatch(str(t or "")))


def _lab(t, names=None):
    """Как назвать бумагу в заголовке: тикер или короткое имя; ISIN — только именем."""
    nm = (names or {}).get(t)
    if _is_isin(t):
        return _fit(re.sub(r"^ОФЗ\s+(?=\d)", "", nm), 16) if nm else "облигация"
    return nm if nm and len(nm) <= 14 else str(t)


def _unit(t):
    return "%" if _is_isin(t) or str(t).startswith("SU") else "₽"


def _bullets(lines, cap=4, width=46):
    lines = [ln for ln in lines if ln]
    out = ["• " + _fit(ln, width) for ln in lines[:cap]]
    if len(lines) > cap:
        out.append(f"• и ещё {len(lines) - cap}")
    return "\n".join(out)


def _ev(key, title, body, url, ticker=None, rate=None, kind="", line=None):
    return {"key": key, "title": _fit(title), "body": _clip(body, 180), "url": url,
            "ticker": ticker, "rate": rate, "kind": kind, "line": line or title}


# ─────────────── условия: только через модуль (а) `conditions_merge` (schema.md §3.2–3.3) ───────────────
# Определения (`conditions@2`) — только чтение; состояние (`conditions-state@1`) пишет hub-api, уведомитель шлёт
# события во внутренний маршрут (COND_URL). Статус, «ждёт владельца», сроки — из строк модуля, своей оценки нет.
COND_DEFS = "Portfolio/conditions.yaml"
COND_STATE = "Portfolio/conditions-state.json"
DECISIONS_DIR = "Portfolio/decisions"
PLAN_JOURNAL = "Portfolio/plan-journal.jsonl"
COND_SCHEMA = "conditions@2"
EV_FIRED, EV_EXPIRED, EV_DONE = CMRG.EV_FIRED, CMRG.EV_EXPIRED, CMRG.EV_DONE
EV_FOUND, EV_MARK, MARK_DISMISSED = CMRG.EV_EVENT_FOUND, CMRG.EV_OWNER_MARK, CMRG.MARK_DISMISSED
PRICE_TRIGGERS = tuple(t for t in codelists.codes("condition_trigger_type", legacy=False) if t.startswith("price_"))
NOT_FOUND_NOTE = "не найдено"                  # data.note у fired по концу окна отчёта (schema.md §3.2)
OUTBOX_MAX = 300                               # неотправленные события состояния (hub-api недоступен) — не больше


def load_conditions(root):
    """→ (определения, состояние) для модуля (а) или (None, None) — блок условий пропускается.
    Нет файла определений — условий нет ([], пусто); документ не `conditions@2` или битое состояние —
    предупреждение в лог и пропуск (без падения). Нет файла состояния — пустое состояние."""
    root = Path(root)
    p = root / COND_DEFS
    if not p.is_file():
        return [], {"events": []}
    try:
        doc = CMRG.load_yaml(p)                # даты остаются строками (правило 1 модуля)
    except Exception as e:  # noqa: BLE001 — битый YAML не роняет проход
        print(f"notifier: {COND_DEFS} не читается ({type(e).__name__}) — условия пропущены", flush=True)
        return None, None
    if not isinstance(doc, dict) or doc.get("schema_version") != COND_SCHEMA:
        sv = doc.get("schema_version") if isinstance(doc, dict) else type(doc).__name__
        print(f"notifier: {COND_DEFS}: schema_version {sv!r}, ожидался {COND_SCHEMA} — условия пропущены", flush=True)
        return None, None
    errs = ds_schemas.validate_conditions_file(doc)
    if errs:
        print(f"notifier: {COND_DEFS}: {len(errs)} замечаний схемы, первое: {errs[0]}", flush=True)
    defs = [d for d in doc.get("conditions") or [] if isinstance(d, dict) and isinstance(d.get("id"), str)
            and isinstance(d.get("version"), int) and not isinstance(d.get("version"), bool) and isinstance(d.get("key"), str)]
    sp = root / COND_STATE
    if not sp.is_file():
        return defs, {"events": []}
    state = load_json(sp)
    if not isinstance(state, dict) or not isinstance(state.get("events"), list):
        print(f"notifier: {COND_STATE} не читается — условия пропущены", flush=True)
        return None, None
    events = [e for e in state["events"] if isinstance(e, dict) and isinstance(e.get("condition_id"), str)
              and isinstance(e.get("event"), str) and isinstance(e.get("at"), str)]
    return defs, {"events": events}


def _moment(v):
    """Время с поясом → datetime для сравнения (строки разных поясов не сравниваются): `+03:00`, `Z` и строка без
    пояса (старый журнал плана — UTC) через time_msk; дата без времени — конец дня МСК. Не разобрать — None."""
    s = _s(v)
    if not s:
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            s = time_msk.day_end_iso(s)
        return datetime.fromisoformat(time_msk.to_msk_iso(s))
    except (ValueError, TypeError):
        return None


def _cev(row, event, data, by="notifier"):
    """Тело события для внутреннего маршрута: id и версия последнего определения (правило 14, дедуп по версии)."""
    return {"condition_id": row["id"], "version": row["version"], "event": event, "by": by, "data": data}


def cond_deadline_events(rows):
    """Ежедневный проход: срок, вычисленный модулем при чтении, — событием (событие уведомителя первично).
    Триггер date с value ≤ сегодня → fired {by_deadline}; report_published с window_end < сегодня → fired
    {by_deadline, note: «не найдено»}; valid_until < сегодня без терминального статуса → expired."""
    out = []
    for r in rows:
        if not r["computed"]:
            continue
        if r["status"] == CMRG.FIRED and r["fired_by_deadline"]:
            data = {"by_deadline": True}
            if (r["trigger"] or {}).get("type") == CMRG.TRIGGER_REPORT:
                data["note"] = NOT_FOUND_NOTE
            out.append(_cev(r, EV_FIRED, data))
        elif r["status"] == CMRG.EXPIRED:
            out.append(_cev(r, EV_EXPIRED, {}))
    return out


def cond_finding_events(rows, report, seen=None):
    """Находки монитора (`condition_findings[]` свежего отчёта) → [(метка, [event_found, fired])] с data.doc.
    Только находка с doc и found_at, той же версии, что последнее определение (находка прежней версии новую не
    поджигает — правило 14), по действующему условию; уже перенесённая (метка в seen) — пропуск."""
    seen = seen or {}
    by_id = {r["id"]: r for r in rows}
    out = []
    for f in (report or {}).get("condition_findings") or []:
        if not isinstance(f, dict):
            continue
        r = by_id.get(f.get("condition_id"))
        doc = f.get("doc")
        if not r or not r["active"] or not doc or not f.get("found_at") or f.get("version") != r["version"]:
            continue
        mark = f"mf:{r['id']}@{r['version']}:{doc}"
        if mark in seen:
            continue
        out.append((mark, [_cev(r, EV_FOUND, {"doc": str(doc)}), _cev(r, EV_FIRED, {"doc": str(doc)})]))
    return out


def load_decisions(root):
    """Решения `decision@1` из Portfolio/decisions/*.json (schema.md §3.1); нет папки — []. Не прошедшее
    валидатор схемы — предупреждение и пропуск."""
    d = Path(root) / DECISIONS_DIR
    out = []
    for p in sorted(d.glob("*.json")) if d.is_dir() else []:
        obj = load_json(p)
        errs = ds_schemas.validate_decision(obj) if isinstance(obj, dict) else ["не объект"]
        if errs:
            print(f"notifier: решение {p.name} пропущено: {errs[0]}", flush=True)
            continue
        out.append(obj)
    return out


def cond_done_events(rows, latest, decisions, seen=None):
    """Новое решение с `conditions_resolved[]` → [(метка, [done by: decision, data.decision_id])] по каждому id,
    если условие **ждёт владельца** (waits_owner: сработало и не отложено им — отложенное владельцем решение не
    закрывает), ключ решения = ключ условия и решение не старше последней версии определения (иначе закрыло бы
    новую версию решением о прежней). `done` по сделке не делается (отложено)."""
    seen = seen or {}
    by_id = {r["id"]: r for r in rows}
    out = []
    for dec in decisions or []:
        rec = _moment(dec.get("recorded_at"))
        for cid in dec.get("conditions_resolved") or []:
            r = by_id.get(cid)
            mark = f"dec:{dec.get('id')}:{cid}"
            if mark in seen or not r or not r["waits_owner"] or r["key"] != dec.get("key"):
                continue
            created = _moment((latest.get(cid) or {}).get("created_at"))
            if created and rec and rec < created:
                continue
            out.append((mark, [_cev(r, EV_DONE, {"decision_id": dec["id"]}, by="decision")]))
    return out


def plan_conditions_daily(defs, state, today, monitor=None, decisions=(), seen=None, at=None):
    """Чистая часть ежедневного прохода → (posts, rows): posts — [(метка | None, тело события)] по срокам,
    находкам монитора и решениям; rows — строки модуля после этих событий (дописаны в копию состояния с
    временем at), по ним считается push «ждёт владельца»."""
    rows = CMRG.merge(defs, state, today)
    latest = CMRG._last_defs(defs)
    posts = [(None, b) for b in cond_deadline_events(rows)]
    posts += [(m, b) for m, bs in cond_finding_events(rows, monitor, seen) for b in bs]
    posts += [(m, b) for m, bs in cond_done_events(rows, latest, decisions, seen) for b in bs]
    if posts:
        at = at or time_msk.now_iso()
        events = list((state or {}).get("events") or []) + [{**b, "at": at} for _, b in posts]
        rows = CMRG.merge(defs, {"events": events}, today)
    return posts, rows


def _owner_found(r):
    """Сработало по кнопке «вышел» владельца (R32): последнее событие — event_found от владельца."""
    le = r.get("last_event") or {}
    return bool(r["found_at"]) and le.get("event") == EV_FOUND and le.get("by") == "owner"


def _cond_reason(r, event_text=None):
    """Почему условие ждёт владельца — словами (кодлист condition_trigger_type и сроки строки модуля)."""
    tr = r["trigger"] or {}
    tt = tr.get("type")
    what = _short(plain(event_text or tr.get("value")), 40)
    if _owner_found(r):   # «вышел» владельцем — как по сроку: «сработало: вышел отчёт …»
        word = codelists.word("condition_trigger_type", tt, default="событие")
        return f"сработало: {word}" + (f" {what}" if what else "")
    if r["found_at"]:
        return f"вышло: {what}" if what else codelists.word("condition_trigger_type", CMRG.TRIGGER_REPORT)
    if tt == CMRG.TRIGGER_REPORT:
        return f"окно до {_ddmm(r['window_end'])} закрылось, отчёт не найден"
    if tt == CMRG.TRIGGER_DATE:
        return f"дата {_ddmm(tr.get('value'))}"
    if tt in PRICE_TRIGGERS:
        return f"{codelists.word('condition_trigger_type', tt)} {_num(tr.get('value'))} {_unit(r['key'])}"
    return codelists.word("condition_trigger_type", tt, default="условие сработало")


def _cond_block(r):
    """Блок «Действий», где стоит сработавшее условие (зеркало actionBlocks вьюера): «только сообщить» и «наблюдение» —
    «Проверить», остальное — «Сделать»."""
    return "Проверить" if r.get("kind") == "watch" or r.get("action_code") == "notify_only" else "Сделать"


def cond_act_word(r, names=None):
    """Что сделать по сработавшему условию — словами (R27/R30): у set_verdict — слово вердикта («сократить»), не
    «сменить вердикт»; у reinvest — «реинвестировать <откуда> → <куда>» (кодлисты reinvest_source и bond_bucket,
    цель-ключ бумаги — именем); остальное — слово кодлиста condition_action."""
    a = r.get("action_code")
    if a == "set_verdict":
        return VERDICT_WORD.get(r.get("verdict_on_trigger") or "", "")
    if a == "reinvest":
        src = codelists.word("reinvest_source", r.get("amount_source"), default="") if r.get("amount_source") else ""
        tgt = r.get("target") or ""
        tw = codelists.word("bond_bucket", tgt, default="") or plain(tgt, names)
        return "реинвестировать" + (f" {src}" if src else "") + (f" → {tw}" if tw else "")
    return codelists.word("condition_action", a, default="") if a else ""


def check_conditions_waiting(rows, names=None, latest=None):
    """Условие перешло в «ждёт владельца» (waits_owner модуля) — одно сообщение на условие: ключ
    cond:<id>@<version>:fired (тот же у часовой цены — второго push утром нет). Текст — on_trigger.text,
    event_text и слова кодлистов (действие, тип триггера); нажатие — «Действия». Вид: находка монитора —
    cond_date («Отчёт под условие», в сводке утренних событий), остальное — cond_open (своим уведомлением);
    «вышел» владельца (R32) — как по сроку: cond_open, «сработало: вышел отчёт … — ждёт владельца»."""
    latest = latest or {}
    evs = []
    for r in rows:
        if not r["waits_owner"]:
            continue
        lab = _lab(r["key"], names)
        reason = _cond_reason(r, (latest.get(r["id"]) or {}).get("event_text"))
        act = cond_act_word(r, names)
        text = plain(r["text"], names)
        if _owner_found(r):    # R32: «сработало: вышел отчёт РСБУ 9М — ждёт владельца»
            line1 = _short(f"{reason} — ждёт владельца", 110)
        elif r.get("action_code") == "reinvest":    # R30: «Сделать: реинвестировать погашение → ОФЗ длиннее 10 лет»
            line1 = _short(f"{reason} — Сделать: {act}", 110)
        else:
            line1 = _short(reason + (f" — {act}" if act else "") + (f": {text}" if text else ""), 110)
        evs.append(_ev(f"cond:{r['id']}@{r['version']}:fired", f"{lab}: условие сработало",
                       f"{line1}\nДействия → «{_cond_block(r)}»", f"{VIEWER}#tab=actions", r["key"], None,
                       "cond_date" if r["found_at"] and not _owner_found(r) else "cond_open", line=f"{lab} — {reason}"))
    return evs


def cond_summary(evs):
    """Несколько условий ждут владельца — одним уведомлением «Ждут решения: N условий», пункт на строку."""
    if len(evs) == 1:
        return None
    n = len(evs)
    return {"key": "cond_open", "title": f"Ждут решения: {n} {_plural(n, 'условие', 'условия', 'условий')}",
            "body": _bullets([e.get("line") or e["title"] for e in evs]), "url": f"{VIEWER}#tab=actions"}


def check_conditions_price(rows, today, prices, names=None):
    """Ежечасно: price_below / price_above по строкам модуля со статусом pending; не раньше not_before
    (проверяет писатель, модуль not_before не трактует). Порог пересечён — событие с ключом
    cond:<id>@<version>:fired (push) и полями cid / version / price для события fired в состоянии."""
    events = []
    for r in rows:
        tr = r["trigger"] or {}
        if r["status"] != CMRG.PENDING or tr.get("type") not in PRICE_TRIGGERS:
            continue
        nb = _s(r["not_before"])
        if nb and today < nb[:10]:
            continue
        price = (prices or {}).get(r["key"])
        try:
            p, val = float(price), float(tr.get("value"))
        except (TypeError, ValueError):
            continue
        if not (p >= val if tr["type"] == "price_above" else p <= val):
            continue
        t = r["key"]
        sign = "≥" if tr["type"] == "price_above" else "≤"
        act = _short(plain(r["text"], names), 90)
        e = _ev(f"cond:{r['id']}@{r['version']}:fired", f"{_lab(t, names)}: цена {_num(price)} {sign} {_num(tr.get('value'))} {_unit(t)}",
                (act + "\n" if act else "") + f"Действия → «{_cond_block(r)}»", _card(t), t, f"cond:{t}", "cond_price",
                line=f"{_lab(t, names)} — цена дошла до порога")
        e.update(cid=r["id"], version=r["version"], price=price)
        events.append(e)
    return events


def load_plan_journal(root):
    """Строки журнала плана Portfolio/plan-journal.jsonl; нет файла или битая строка — пропуск."""
    out = []
    try:
        with open(Path(root) / PLAN_JOURNAL, encoding="utf-8") as f:
            for ln in f:
                try:
                    row = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    out.append(row)
    except OSError:
        return []
    return out


def _review_moment(review):
    """Момент обзора: recorded_at, иначе конец дня review_date (прежнее правило «после даты прошлого обзора,
    не позже даты нового» по датам)."""
    r = review or {}
    return _moment(r.get("recorded_at")) or _moment(_s(r.get("review_date")))


# Решение владельца между обзорами (сделка, закрытое или отложенное им условие, смена плана) — не «смена мнения советника».
# ⚠ SYNC: правило R24 «владелец решил сам» — одно в трёх местах: здесь (owner_decided), ownerDecided() в
# tools/assets/viewer.js (вкладка «Изменения») и owner_marked() в skills/portfolio-data-loader/scripts/decision_journal.py;
# сторож паритета — tools/tests/test_owner_decided_parity.py.
OWNER_MARKS = (CMRG.MARK_DISMISSED, CMRG.MARK_DEFERRED)   # отложить — тоже решение владельца (R24)
OWNER_PLAN_FIELDS = ("user_status", "user_plan", "action")  # action — план владельца по облигации; plan_pct и справочные поля — нет


def owner_plan_path(path, key):
    """Строка журнала плана — решение владельца по бумаге key: stocks|bonds|funds.<key>.<поле из OWNER_PLAN_FIELDS>."""
    return isinstance(path, str) and any(path == f"{s}.{key}.{f}" for s in ("stocks", "bonds", "funds")
                                         for f in OWNER_PLAN_FIELDS)


def owner_decided(isin, review, owner=None, prev_review=None):
    """Смену вердикта бумаги вызвало решение владельца, если между обзорами (после момента прошлого, не позже
    момента нового; моменты разбираются, не сравниваются строкой): (в) бумага в сделках обзора
    (trades_since_prior); (а) по условию этой бумаги (любая версия определения с key = бумага) в состоянии
    есть done by: owner или owner_mark с mark dismissed/deferred; (б) в журнале плана строка
    stocks|bonds|funds.<бумага>.user_status|user_plan|action (owner_plan_path) — бумага сопоставляется по ключу
    строки обзора. owner = {"defs", "events", "journal"}."""
    if any(isinstance(x, dict) and isin in (x.get("isin"), x.get("ticker")) for x in (review or {}).get("trades_since_prior") or []):
        return True
    owner = owner or {}
    lo, hi = _review_moment(prev_review), _review_moment(review)
    if not lo or not hi:
        return False

    def between(v):
        m = _moment(v)
        return bool(m) and lo < m <= hi

    ids = {d.get("id") for d in owner.get("defs") or [] if isinstance(d, dict) and d.get("key") == isin}
    for e in owner.get("events") or []:
        if not isinstance(e, dict) or e.get("condition_id") not in ids:
            continue
        ev = e.get("event")
        if ((ev == EV_DONE and e.get("by") == "owner")
                or (ev == EV_MARK and (e.get("data") or {}).get("mark") in OWNER_MARKS)) and between(e.get("at")):
            return True
    return any(isinstance(j, dict) and owner_plan_path(j.get("path"), isin) and between(j.get("ts"))
               for j in owner.get("journal") or [])


def _bond_label(name, t):
    return re.sub(r"^ОФЗ\s+(?=\d)", "", name) if name and name != t else (t if not _is_isin(t) else "облигация")


def held_keys(root):
    """Ключи бумаг портфеля (тикер и ISIN) по последнему снапшоту — `decisions_read.held_keys`: тот же вход
    `snapshot_keys`, что у модуля (б) (правило 14 «есть в портфеле», количество > 0, без кандидатов первой покупки);
    снапшота нет — None (фильтр по портфелю не применяется)."""
    return decisions_read.held_keys(str(root))


def action_row(row, key, held=None):
    """Строка обзора попадает в «Сделать»/«Проверить» «Действий» (зеркало actionBlocks вьюера): вердикт с направлением
    (verdict_direction up/down) или пункты проверки `verification_checklist` при приоритете «срочно» (R28: одно лишь
    «срочно» без пунктов — подпись строки, не push). Бумаги нет в портфеле (held — ключи последнего снапшота, правило 14
    модуля (б)) и вердикт не «вверх» — продана или погашена, не пушим. Без направления и без пунктов — «К сведению»."""
    if not isinstance(row, dict):
        return False
    d = VERDICT_DIR.get(row.get("advisor_verdict"))
    if held is not None and key not in held and d != "up":
        return False                               # бумаги нет в портфеле: продана/погашена или проверять нечего
    pts = [x for x in (row.get("verification_checklist") or []) if str(x or "").strip()]
    return d in ("up", "down") or (row.get("verification_priority") == "HIGH" and bool(pts))


def check_verdicts(prev, cur, kind, names=None, owner=None, held=None):
    """Смена вердикта между двумя последними обзорами — ОДНИМ уведомлением на обзор (ключ
    verdicts:{kind}:{дата обзора}): «Облигации: 3 смены вердикта», нажатие — «Изменения» этого вида
    и этого обзора. Смены по решению владельца (owner_decided: сделки обзора, события состояния условий,
    журнал плана — owner = {"defs", "events", "journal"}) не считаются; push — только если новая строка обзора
    стоит в «Сделать»/«Проверить» (action_row: вердикт с направлением или проверка «срочно», проданная — нет);
    других нет — уведомления нет. kind: stock | bond."""
    if not prev or not cur:
        return []
    field = "per_stock" if kind == "stock" else "per_bond"
    a, b = prev.get(field) or {}, cur.get(field) or {}
    rdate, pdate = _s(cur.get("review_date")) or "", _s(prev.get("review_date")) or ""
    rows = []
    for t, row in b.items():
        if not isinstance(row, dict) or t not in a or not isinstance(a[t], dict):
            continue
        v0, v1 = a[t].get("advisor_verdict"), row.get("advisor_verdict")
        if not v0 or not v1 or v0 == v1 or owner_decided(t, cur, owner, prev) or not action_row(row, t, held):
            continue
        name = row.get("name") or (names or {}).get(t) or t
        rows.append((-(row.get("weight_real_pct") or 0), _bond_label(name, t) if kind == "bond" else t, v0, v1))
    if not rows:
        return []
    rows.sort(key=lambda r: r[0])
    n = len(rows)
    who = "Облигации" if kind == "bond" else "Акции"
    title = f"{who}: " + (f"{n} {_plural(n, 'смена', 'смены', 'смен')} вердикта" if n > 1 else "смена вердикта")
    if n == 1:
        body = f"{rows[0][1]}: {VERDICT_WORD.get(rows[0][2], rows[0][2])} → {VERDICT_WORD.get(rows[0][3], rows[0][3])}\nСмотри «Изменения»"
    else:
        shown = ", ".join(r[1] for r in rows[:4]) + (f" и ещё {n - 4}" if n > 4 else "")
        body = f"Обзор {_ddmm(rdate)}: {shown}\nСмотри «Изменения»"
    return [_ev(f"verdicts:{kind}:{rdate}", title, body, f"{VIEWER}#tab=diff&kind={kind}&date={rdate}",
                rate=None, kind="verdict", line=title)]


def _mr_topic(x):
    """Тема файла прогноза/сценариев: имя без расширения, префикса scenario- и даты в конце."""
    b = re.sub(r"\.(ya?ml|md)$", "", str(x or "").split("/")[-1])
    return re.sub(r"-\d{4}-\d{2}-\d{2}$", "", re.sub(r"^scenario-", "", b))


def _mr_keys(x):
    f = str(x or "").strip()
    return {f.split("/")[-1], _mr_topic(f)} if f else set()


def _mr_partial(rep):
    """(частичный?, проверенные файлы). Без scope отчёт полный, кроме явной оговорки о запуске по файлу."""
    caveats = rep.get("caveats") or []
    cav = next((t for t in (str(c.get("message", "") if isinstance(c, dict) else c) for c in caveats)
                if re.search(r"запуск по одному файлу|частичн\w+ прогон", t, re.I)), None)
    scope = str(rep.get("scope") or "").lower()
    if scope == "partial" or (not scope and cav):
        checked = list(rep.get("checked") or [])
        if not checked:
            m = re.search(r"\(([^)]+)\)", cav or "")
            checked = ([t.strip() for t in re.split(r"[,;]", m.group(1))] if m else []) + \
                [a.get("target_file") or a.get("target") for a in rep.get("alerts") or [] if isinstance(a, dict)]
        return True, [c for c in checked if c]
    return False, []


def merge_monitor(reports):
    """Отчёты монитора по порядку → одна картина (зеркало mergeMonitorReports во вьюере): база — последний
    полный, поверх частичные новее него; предупреждения по проверенным файлам частичного заменяются его
    собственными, прочие остаются. Находки по условиям (condition_findings[]) здесь не сводятся — их переносит
    в состояние ежедневный проход (cond_finding_events) из последнего отчёта."""
    reps = [r for r in reports if isinstance(r, dict)]
    if not reps:
        return None
    sc = [_mr_partial(r) for r in reps]
    bi = max((i for i, (part, _) in enumerate(sc) if not part), default=0)
    out = dict(reps[bi])
    alerts = [a for a in reps[bi].get("alerts") or [] if isinstance(a, dict)]
    for i in range(bi + 1, len(reps)):
        part, checked = sc[i]
        if not part:
            continue
        ks = set().union(*(_mr_keys(f) for f in checked)) if checked else set()
        alerts = [a for a in alerts if not (_mr_keys(a.get("target_file")) | _mr_keys(a.get("target"))) & ks]
        alerts += [a for a in reps[i].get("alerts") or [] if isinstance(a, dict)]
    out["alerts"] = alerts
    return out


def _high(report):
    out = {}
    for a in (report or {}).get("alerts") or []:
        if isinstance(a, dict) and a.get("severity") == "HIGH":
            out[(a.get("category") or "", a.get("target") or "")] = a
    return out


def check_monitor(prev, cur, cur_date):
    """HIGH-предупреждения свежего отчёта монитора, которых не было в предыдущем, — одним уведомлением."""
    if not cur:
        return []
    old = set(_high(prev)) if prev else set()
    new = [a for k, a in _high(cur).items() if k not in old]
    if not new:
        return []
    n = len(new)
    title = "Монитор: важный сигнал" if n == 1 else f"Монитор: {n} важных {_plural(n, 'сигнала', 'сигнала', 'сигналов')}"
    msgs = [_short(plain(a.get("message") or a.get("target")), 90) for a in new]
    body = (msgs[0] + "\nДействия → полный текст в окне") if n == 1 else _bullets(msgs, cap=3)
    # нажатие — «Действия» и окно с полным текстом новых предупреждений (вьюер 3.52.0)
    new_q = urllib.parse.quote("|".join(str(a.get("target") or "") for a in new), safe="")
    return [_ev(f"monitor:{cur_date}", title, body, f"{VIEWER}#tab=actions&new={new_q}", kind="monitor", line=title)]


# Заголовок и команда Claude по виду отчёта (уведомление об устаревшем отчёте)
STALE_SHORT = {"stocks": "обзор акций", "bonds": "обзор облигаций", "stress": "стресс-тест", "portfolio": "снапшот портфеля",
               "monitor": "монитор", "integratedView": "интегр. анализ", "macro": "инфляция"}
STALE_ACC = {"macro": "инфляцию"}     # «Пора обновить …» — винительный падеж там, где он отличается
STALE_CMD = {"stocks": "обнови недельный обзор акций", "bonds": "обнови обзор облигаций", "stress": "обнови стресс-тест",
             "portfolio": "загрузи свежий снапшот портфеля", "monitor": "запусти монитор прогнозов",
             "integratedView": "собери интеграционный анализ", "macro": "обнови инфляцию"}


# Виды stale, которые без модели не обновляются (LLM-файлы): при ai_mode off о них не напоминаем — это шум,
# обновляемое без ИИ (снапшот портфеля) напоминается как обычно, без фразы для Claude.
STALE_LLM = ("stocks", "bonds", "stress", "monitor", "integratedView", "macro")
STALE_NOAI_HINT = {"portfolio": "Собрать снапшот — вьюер → «Загрузки»"}


def ai_mode(root):
    """Режим сайта по файлу _hub/settings.json (hub-notify читает NAS напрямую); нет файла или битый — on."""
    try:
        return hub_settings.read(Path(root))["ai_mode"]
    except Exception:
        return "on"


def infl_latest(root):
    """Самая свежая запись недельной инфляции из model.jsonl и owner.jsonl → (дата 'YYYY-MM-DD', автор) или None.
    Битые строки и записи без даты пропускаются; одна дата в обоих файлах — побеждает более поздний recorded_at."""
    folder, rx = STALE_FILES["macro"]
    best = None
    for _, p in dated_files_any(root, folder, rx):
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for ln in lines:
            try:
                o = json.loads(ln)
            except ValueError:
                continue
            d = o.get("date") if isinstance(o, dict) else None
            if not (isinstance(d, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d)):
                continue
            key = (d, str(o.get("recorded_at") or ""))
            if best is None or key > best[0]:
                best = (key, "owner" if o.get("author") == "owner" else "model")
    return (best[0][0], best[1]) if best else None


def dated_files_any(root, folder, pattern):
    """[(имя, Path)] файлов папки по маске имени (без даты в имени)."""
    rx = re.compile(pattern)
    try:
        return sorted((p.name, p) for p in (Path(root) / folder).iterdir() if rx.match(p.name) and p.is_file())
    except FileNotFoundError:
        return []


def check_stale(root, today, mode="on"):
    """Просроченные отчёты: по самому свежему файлу каждого вида — уровень warn («пора обновить»)
    или fail («скиллы не работают»). Событие на файл и уровень; в уведомление склеивает stale_summary.
    mode off — только виды, обновляемые без ИИ, и подсказка про сайт вместо фразы для Claude."""
    events = []
    td = date.fromisoformat(today)
    for kind, (folder, rx) in STALE_FILES.items():
        if mode == "off" and kind in STALE_LLM:
            continue
        if kind == "macro":                      # дата — внутри файлов моделей и владельца
            lat = infl_latest(root)
            if not lat:
                continue
            d = lat[0]
        else:
            files = dated_files(root, folder, rx)
            if not files:
                continue
            d = files[-1][0]
        age = (td - date.fromisoformat(d)).days
        fail = STALE_FAIL_DAYS.get(kind)
        if fail is not None and age > fail:
            level = "fail"
            title = f"{STALE_SHORT[kind].capitalize()}: старше {fail} дн."
            detail = (f"Последняя от {_ddmm(d)} ({age} дн.) — срок вышел" if kind == "macro"
                      else f"Файл от {_ddmm(d)} ({age} дн.) — скиллы на нём не работают")
        elif age > STALE_WARN_DAYS[kind]:
            level = "warn"
            title = f"Пора обновить {STALE_ACC.get(kind, STALE_SHORT[kind])}"
            detail = f"Последняя от {_ddmm(d)}, {age} дн." if kind == "macro" else f"Файл от {_ddmm(d)}, {age} дн."
        else:
            continue
        hint = STALE_NOAI_HINT.get(kind, "") if mode == "off" else f"Сказать Claude: «{STALE_CMD[kind]}»"
        e = _ev(f"stale:{kind}:{d}:{level}", title, detail + (f"\n{hint}" if hint else ""),
                f"{VIEWER}#tab=actions", kind="stale",   # там команды для Claude (вьюер 3.44.2)
                line=f"{STALE_SHORT[kind]} — {age} дн." + ((", срок вышел" if kind == "macro" else ", скиллы не работают") if level == "fail" else ""))
        e["level"] = level
        events.append(e)
    return events


# ─────────────── «Напоминать заранее»: даты по держимым бумагам ───────────────
# Пороги — дни до события; событие приходит один раз на порог (окно «от порога вниз»): 7 → за 1..7 дн.,
# 0 → в день срока. Решения/гейт — модуль (б) last_word (как вьюер), облигации — последний снапшот.
AHEAD_DAYS = {"ahead_review": (7, 0), "ahead_offer": (14, 3), "ahead_maturity": (7,)}
AHEAD_WORD = {"ahead_review": "срок решения", "ahead_offer": "оферта", "ahead_maturity": "погашение"}


def _ahead_stage(left, thresholds):
    """Порог, в окно которого попало событие (наименьший порог ≥ left); до события вне окон или после него — None."""
    if left < 0:
        return None
    cand = [t for t in thresholds if left <= t]
    return min(cand) if cand else None


def _ahead_day(v):
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _ahead_ev(kind, key, label, ticker, d, left, stage, text):
    when = "сегодня" if left == 0 else f"через {left} дн."
    ds = _ddmm(d.isoformat())
    if kind == "ahead_pause":
        title, line = f"{label}: можно докупать", f"{label} — {text}"
        body = f"{text[:1].upper()}{text[1:]}"
    else:
        title = f"{label}: {AHEAD_WORD[kind]} {ds}" if kind != "ahead_review" else f"{label}: срок решения"
        line = f"{label} — {AHEAD_WORD[kind]} {ds} ({when})"
        body = f"{AHEAD_WORD[kind].capitalize()} {ds} — {when}.\nПосмотреть бумагу во вьюере."
    return _ev(f"ahead:{kind}:{key}:{d.isoformat()}:{stage}", title, body, _card(ticker), ticker=ticker, kind=kind, line=line)


def check_ahead(root, today, thresholds=None):
    """Напоминания заранее по держимым бумагам (qty > 0, без кандидатов первой покупки): срок решения/гейта,
    оферта, погашение, конец паузы докупки/IPO-паузы. Событие на (вид, бумага, дата, порог); в уведомление
    склеивает ahead_summary."""
    th = thresholds or AHEAD_DAYS
    root = str(root)
    td = date.fromisoformat(today)
    snaps = decisions_read.snapshot_files(root)
    snap = load_json(snaps[-1][1]) if snaps else None
    holds = [h for h in (snap or {}).get("holdings") or []
             if isinstance(h, dict) and not h.get("first_buy") and decisions_read._qty_pos(h)]
    if not holds:
        return []
    lw = decisions_read.lw
    decisions, _ = decisions_read.load(root)
    types = decisions_read.key_types(root)
    attrs = decisions_read.load_attrs(root)
    held = decisions_read.holding_keys(snap)
    # сделки по истории снапшотов: пауза докупки — от первой покупки после решения BUY/ADD (правило 7 модуля (б))
    trades = decisions_read.trade_times([p for _, p in snaps], today)

    def ctx(day):
        return {"today": day, "decisions": decisions, "reviews": {}, "security_attrs": attrs, "snapshot_keys": held,
                "stock_keys": [k for k in held if decisions_read.key_type(types, k) == "stock"], "first_buy": [], **trades}

    cx_today, cx_prev = ctx(today), ctx((td - timedelta(days=1)).isoformat())
    events = []
    for h in holds:
        keys = [k for k in (h.get("ticker"), h.get("isin")) if k]
        if not keys:
            continue
        ticker = keys[0]
        label = _lab(ticker, {ticker: h.get("name")} if h.get("name") else None)
        found = {}                                    # вид → (дата, текст): по бумаге один раз, даже если ключей два
        for k in keys:
            c = lw.card(cx_today, k)
            g = c["gate"]
            due = g["expires_on"] if g["applicable"] else c["review_by"]
            if c["decision_id"] and due:
                found.setdefault("ahead_review", (due, ""))
            # конец паузы: на вчерашнюю дату пауза ещё действует и кончается ровно сегодня
            g1 = lw.card(cx_prev, k)["gate"]
            if g1["add_cooldown_until"] == today:
                found.setdefault("ahead_pause", (today, "пауза докупки закончилась — снова можно докупать"))
            elif g1["ipo_pause_until"] == today:
                found.setdefault("ahead_pause", (today, "IPO-пауза закончилась — снова можно докупать"))
        for kind, field in (("ahead_offer", "offer_date"), ("ahead_maturity", "maturity_date")):
            if h.get(field):
                found[kind] = (str(h[field])[:10], "")
        for kind, (dstr, text) in found.items():
            d = _ahead_day(dstr)
            if d is None:
                continue
            left = (d - td).days
            stage = 0 if kind == "ahead_pause" else _ahead_stage(left, th[kind])
            if stage is None or (kind == "ahead_pause" and left != 0):
                continue
            events.append(_ahead_ev(kind, ticker, label, ticker, d, left, stage, text))
    order = {k: i for i, k in enumerate(("ahead_pause", "ahead_review", "ahead_offer", "ahead_maturity"))}
    return sorted(events, key=lambda e: (order[e["kind"]], e["key"]))


def ahead_summary(evs):
    """Напоминания заранее — одним уведомлением со списком строк; одно событие — как есть."""
    n = len(evs)
    if n == 1:
        return None
    return {"key": "ahead", "title": f"Напоминания заранее: {n}",
            "body": _bullets([e.get("line") or e["title"] for e in evs]), "url": f"{VIEWER}#tab=notify"}


def check_no_decision(root, today, mode="on"):
    """Акции в портфеле без единого решения (модуль (б): decision_id пуст по всем ключам бумаги) — только при mode off.
    Акции — потому что у них гейт: без решения докупка закрыта. Облигации и фонды гейта не имеют (решение — для журнала,
    а десятки бумаг без него дали бы еженедельную простыню), замороженные (is_blocked / оценка по себестоимости) —
    не анализируются. Событие на (бумага, день); раз в RATE_DAYS по бумаге — rate; в уведомление склеивает no_decision_summary."""
    if mode != "off":
        return []
    root = str(root)
    snaps = decisions_read.snapshot_files(root)
    snap = load_json(snaps[-1][1]) if snaps else None
    holds = [h for h in (snap or {}).get("holdings") or []
             if isinstance(h, dict) and not h.get("first_buy") and decisions_read._qty_pos(h)
             and not h.get("is_blocked") and h.get("current_price_source") != "cost_basis"]
    if not holds:
        return []
    lw = decisions_read.lw
    decisions, _ = decisions_read.load(root)
    types = decisions_read.key_types(root)
    attrs = decisions_read.load_attrs(root)
    held = decisions_read.holding_keys(snap)
    cx = {"today": today, "decisions": decisions, "reviews": {}, "security_attrs": attrs, "snapshot_keys": held,
          "stock_keys": [k for k in held if decisions_read.key_type(types, k) == "stock"], "first_buy": []}
    events = []
    for h in holds:
        keys = [k for k in (h.get("ticker"), h.get("isin")) if k]
        if not keys or not (h.get("asset_type") == "stock" or any(decisions_read.key_type(types, k) == "stock" for k in keys)):
            continue
        if any(lw.card(cx, k)["decision_id"] for k in keys):
            continue
        t = keys[0]
        label = _lab(t, {t: h.get("name")} if h.get("name") else None)
        events.append(_ev(f"no_decision:{t}:{today}", f"{label}: нет решения",
                          "В портфеле, а решения нет — докупка закрыта. Запиши решение в карточке.", _card(t),
                          ticker=t, rate=f"no_decision:{t}", kind="no_decision", line=f"{label} — нет решения"))
    return sorted(events, key=lambda e: e["key"])


def check_inflation_due(root, today, mode="on"):
    """«Пора внести инфляцию»: только при mode off (при on просроченную инфляцию сообщает check_stale с командой для Claude).
    Самая свежая запись недельной инфляции (модель или владелец) старше STALE_WARN_DAYS["macro"] дней → одно событие на день;
    раз в RATE_DAYS (rate-ключ) — не чаще раза в неделю. Записей нет вовсе — молчит (нечего считать просроченным).
    Нажатие — «Макро» (форма «Внести инфляцию»); без «Сказать Claude» (при «без ИИ» команд нет)."""
    if mode != "off":
        return []
    lat = infl_latest(root)
    if not lat:
        return []
    age = (date.fromisoformat(today) - date.fromisoformat(lat[0])).days
    if age <= STALE_WARN_DAYS["macro"]:
        return []
    return [_ev(f"macro_infl:{today}", "Пора внести инфляцию",
                f"Последняя — от {_ddmm(lat[0])}, {age} дн. Форма — вьюер → «Макро».", f"{VIEWER}#tab=macro",
                rate="macro_infl", kind="macro_infl", line=f"недельная инфляция — {age} дн.")]


def no_decision_summary(evs):
    """Акции без решения — одним уведомлением; одна бумага — как есть (нажатие — карточка)."""
    n = len(evs)
    if n == 1:
        return None
    return {"key": "no_decision", "title": f"Без решения: {n} {_plural(n, 'акция', 'акции', 'акций')}",
            "body": _bullets([e.get("line") or e["title"] for e in evs]), "url": f"{VIEWER}#tab=actions"}


def _plural(n, one, few, many):
    return one if n % 10 == 1 and n % 100 != 11 else few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


def events_summary(evs):
    """Утренние события — одним уведомлением; одно — как есть (нажатие — карточка бумаги)."""
    if len(evs) == 1:
        return None
    n = len(evs)
    return {"key": "events", "title": f"Портфель: {n} {_plural(n, 'событие', 'события', 'событий')}",
            "body": _bullets([e.get("line") or e["title"] for e in evs]), "url": f"{VIEWER}#tab=notify"}


def stale_summary(evs):
    """Просроченные отчёты — одним уведомлением, «скиллы не работают» первыми."""
    fails = [e for e in evs if e["key"].endswith(":fail")]
    rest = [e for e in evs if not e["key"].endswith(":fail")]
    n = len(evs)
    if n == 1:
        return {"key": "stale", "title": evs[0]["title"], "body": evs[0]["body"], "url": evs[0]["url"]}
    return {"key": "stale", "title": f"Просрочено {n} {_plural(n, 'отчёт', 'отчёта', 'отчётов')}",
            "body": _bullets([e.get("line") or e["title"] for e in fails + rest]), "url": f"{VIEWER}#tab=actions"}


def stock_names(root):
    snaps = dated_files(root, "Portfolio/snapshots", STALE_FILES["portfolio"][1])
    snap = load_json(snaps[-1][1]) if snaps else None
    out = {h.get("ticker"): h.get("name") for h in (snap or {}).get("holdings") or []
           if isinstance(h, dict) and h.get("ticker") and h.get("name")}
    bonds = dated_files(root, STALE_FILES["bonds"][0], STALE_FILES["bonds"][1])
    for t, r in ((load_yaml(bonds[-1][1]) or {}).get("per_bond") or {}).items() if bonds else []:
        if isinstance(r, dict) and r.get("name") and t not in out:
            out[t] = r["name"]
    return out


def _gen_key(rep):
    """generated_at отчёта как момент (старые отчёты — с `Z`, новые — `+03:00`; строки разных форматов не сравнивать)."""
    v = rep.get("generated_at") if isinstance(rep, dict) else None
    try:
        s = str(v).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()
    except (ValueError, TypeError):
        return 0.0


def monitor_reports(root):
    """Отчёты монитора по порядку создания: дата из имени, внутри дня — generated_at (не имя файла:
    «…-10-26-v2» по имени встаёт раньше «…-10-26», дефис < точки, и базой стал бы старый отчёт)."""
    mons = dated_files(root, "monitor-reports", r"^monitor-report-(\d{4}-\d{2}-\d{2}).*\.ya?ml$")
    rows = [(d, load_yaml(f)) for d, f in mons]
    rows.sort(key=lambda x: (x[0], _gen_key(x[1])))
    return rows                                  # [(дата из имени, отчёт)]


def collect_daily(root, today, seen=None, at=None, mode="on"):
    """Утренний проход → (события для push, события состояния [(метка | None, тело)]).
    mode off — смены вердиктов и монитор (LLM-файлы) не проверяются; условия и «ждёт владельца» — как обычно.
    Условия — только через модуль (а): сроки → fired/expired, находки свежего отчёта монитора → event_found + fired,
    новые решения → done; push «ждёт владельца» — по строкам после этих событий. Смены вердикта — с
    owner_decided по событиям состояния и журналу плана."""
    root = Path(root)
    mons = monitor_reports(root)
    mon_all = [r for _, r in mons]
    mon_cur = merge_monitor(mon_all)
    mon_prev = merge_monitor(mon_all[:-1])
    names = stock_names(root)
    defs, state = load_conditions(root)
    posts, waiting = [], []
    if defs is not None:
        posts, rows = plan_conditions_daily(defs, state, today, mon_all[-1] if mon_all else None,
                                            load_decisions(root), seen, at)
        waiting = check_conditions_waiting(rows, names, CMRG._last_defs(defs))
    owner = {"defs": defs or [], "events": (state or {}).get("events") or [], "journal": load_plan_journal(root)}
    held = held_keys(root)
    events = []
    if mode != "off":
        for kind, key in (("stock", "stocks"), ("bond", "bonds")):
            files = dated_files(root, STALE_FILES[key][0], STALE_FILES[key][1])
            if len(files) >= 2:
                events += check_verdicts(load_yaml(files[-2][1]), load_yaml(files[-1][1]), kind, names, owner, held)
        if mons:
            events += check_monitor(mon_prev, mon_cur, mons[-1][0])
    return events + waiting, posts


def collect_hourly(root, today, prices):
    """Часовой проход: ценовые условия по строкам модуля (pending, не раньше not_before)."""
    defs, state = load_conditions(root)
    if defs is None:
        return []
    rows = CMRG.merge(defs, state, today)
    evs = check_conditions_price(rows, today, prices)
    if evs:                                    # имена бумаг — только когда есть что показать
        evs = check_conditions_price(rows, today, prices, stock_names(root))
    return evs


def fetch_prices(url=QUOTES_URL):
    """quotes@1 из hub-api → {SECID: цена} плюс {ISIN: цена} у облигаций (условия советника по облигации ключуются
    ISIN, доски отдают SECID — без второго ключа такое условие не срабатывало никогда). Ошибка — пустой словарь."""
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            q = json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for k, v in (q.get("items") or {}).items():
        if isinstance(v, dict) and v.get("price"):
            out[k] = v["price"]
            if v.get("isin") and v["isin"] != k:
                out.setdefault(v["isin"], v["price"])
    return out


# ─────────────────────────── состояние ───────────────────────────
_lock = threading.RLock()


def _read(name, default):
    p = DATA / name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(name, obj):
    DATA.mkdir(parents=True, exist_ok=True)
    p = DATA / name
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def new_state():
    return {"mode": DEFAULT_MODE if DEFAULT_MODE in ("quiet", "live") else "quiet", "off": [],
            "sent": {}, "rate": {}, "last_daily": None, "last_hourly": None, "log": []}


def process(events, st, now, send, combine=None):
    """Дедуп + частота + тихий режим. send(event) → True (принято хоть одним устройством) /
    False (не принято — повтор на следующем прогоне) / None (устройств нет — отработано).
    combine(события к отправке) → одно сводное уведомление (или None — отправить как есть):
    утренние прогоны так шлют не больше одного уведомления на группу. Без combine больше
    MAX_PUSH_PER_RUN — три по одному и сводка. Меняет st на месте; возвращает записи журнала."""
    ts = jobs.now_iso(now)
    plan = []                                   # (событие, статус до отправки)
    off = set(st.get("off") or [])
    for e in events:
        if e["key"] in st["sent"]:
            continue
        status = "send"
        if e.get("kind") in off:
            status = "off"
        if status == "send" and e.get("rate"):
            last = st["rate"].get(e["rate"])
            if last and now - datetime.fromisoformat(last) < timedelta(days=RATE_DAYS):
                status = "suppressed"
        if status == "send" and st["mode"] != "live":
            status = "quiet"
        plan.append([e, status])
    to_send = [p for p in plan if p[1] == "send"]
    summary = combine([p[0] for p in to_send]) if combine and to_send else None
    if summary:
        grouped = to_send
    else:
        grouped = to_send[MAX_PUSH_PER_RUN - 1:] if len(to_send) > MAX_PUSH_PER_RUN else []
        n = len(grouped)
        summary = {"key": "group", "title": f"И ещё {n} {_plural(n, 'событие', 'события', 'событий')}",
                   "body": _bullets([p[0].get("line") or p[0]["title"] for p in grouped]),
                   "url": f"{VIEWER}#tab=notify"} if grouped else None
    gid = {id(p) for p in grouped}
    for p in to_send:
        if id(p) not in gid:
            r = send(p[0])
            p[1] = "sent" if r else "no_devices" if r is None else "failed"
    if grouped:
        r = send(summary)
        for p in grouped:
            p[1] = "sent" if r else "no_devices" if r is None else "failed"
    out = []
    for e, status in plan:
        if status in ("sent", "quiet") and e.get("rate"):
            st["rate"][e["rate"]] = ts
        if status != "failed":
            st["sent"][e["key"]] = ts
        rec = {"ts": ts, "status": status, "title": e["title"], "body": e["body"], "url": e["url"], "key": e["key"],
               "kind": e.get("kind")}
        if any(id(p) in gid and p[0] is e for p in plan):
            rec["grouped"] = True
        out.append(rec)
    st["log"] = (st["log"] + out)[-LOG_KEEP:]
    cutoff = (now - timedelta(days=SENT_KEEP_DAYS)).isoformat()
    st["sent"] = {k: v for k, v in st["sent"].items() if v >= cutoff}
    return out


# ─────────────────────────── Web Push ───────────────────────────
def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def b64u_dec(s):
    s = s.encode() if isinstance(s, str) else s
    return base64.urlsafe_b64decode(s + b"=" * (-len(s) % 4))


def vapid_keys():
    """Ключ VAPID: создаётся при первом старте, живёт в /data/vapid.json. Смена ключа = переподписка устройств."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    with _lock:
        k = _read("vapid.json", None)
        if not k:
            priv = ec.generate_private_key(ec.SECP256R1())
            pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption()).decode()
            k = {"private_pem": pem, "created": jobs.now_iso()}
            _write("vapid.json", k)
        priv = serialization.load_pem_private_key(k["private_pem"].encode(), None)
        pub = priv.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        return priv, b64u(pub)


def vapid_header(endpoint, priv, pub_b64, now=None):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    u = urlparse(endpoint)
    exp = int((now or time.time()) + 12 * 3600)
    seg = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode()) + "." + \
        b64u(json.dumps({"aud": f"{u.scheme}://{u.netloc}", "exp": exp, "sub": VAPID_SUB}, separators=(",", ":")).encode())
    r, s = decode_dss_signature(priv.sign(seg.encode(), ec.ECDSA(hashes.SHA256())))
    jwt = seg + "." + b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={jwt}, k={pub_b64}"


def encrypt(payload, p256dh, auth, salt=None, as_priv=None):
    """RFC 8291 (aes128gcm): тело запроса к push-сервису."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    ua_pub = b64u_dec(p256dh)
    auth_secret = b64u_dec(auth)
    as_priv = as_priv or ec.generate_private_key(ec.SECP256R1())
    as_pub = as_priv.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    shared = as_priv.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub))
    ikm = HKDF(hashes.SHA256(), 32, auth_secret, b"WebPush: info\x00" + ua_pub + as_pub).derive(shared)
    salt = salt or os.urandom(16)
    cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
    ct = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + struct.pack("!I", 4096) + bytes([len(as_pub)]) + as_pub + ct


def push_one(sub, message, urgency="normal"):
    """→ HTTP-код push-сервиса (201 — принято; 404/410 — подписка умерла)."""
    priv, pub = vapid_keys()
    body = encrypt(json.dumps(message, ensure_ascii=False).encode("utf-8"),
                   sub["keys"]["p256dh"], sub["keys"]["auth"])
    req = urllib.request.Request(sub["endpoint"], data=body, method="POST", headers={
        "Authorization": vapid_header(sub["endpoint"], priv, pub),
        "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream",
        "TTL": "86400", "Urgency": urgency})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except OSError:
        return 0


def send_all(event):
    """На все подписанные устройства; умершие подписки (404/410) удаляются."""
    msg = {"title": event["title"], "body": event["body"], "url": event["url"], "tag": event["key"]}
    with _lock:
        subs = _read("subscriptions.json", [])
    if not subs:
        return None
    ok, dead = False, []
    for s in subs:
        code = push_one(s, msg)
        if 200 <= code < 300:
            ok = True
        elif code in (404, 410):
            dead.append(s["endpoint"])
    if dead:
        with _lock:
            _write("subscriptions.json", [s for s in _read("subscriptions.json", []) if s["endpoint"] not in dead])
    return ok


# ─────────────────────────── расписание ───────────────────────────
def _at(st, now, field, at):
    hh, mm = (int(x) for x in at.split(":"))
    return st.get(field) != now.date().isoformat() and (now.hour, now.minute) >= (hh, mm)


def daily_due(st, now):
    return _at(st, now, "last_daily", DAILY_AT)


def hourly_due(st, now):
    slot = now.strftime("%Y-%m-%dT%H")
    return now.weekday() < 5 and now.hour in TRADING_HOURS and now.minute >= 5 and st.get("last_hourly") != slot


def _cond_req(body):
    """POST события условия на внутренний маршрут hub-api → (код, тело)."""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    rq = urllib.request.Request(COND_URL, data=data, method="POST", headers={
        "Authorization": COND_AUTH, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(rq, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")
        except ValueError:
            return e.code, {}


def cond_post(body):
    """Событие состояния → hub-api. → "ok" (записано) | "dup" (сервер: повтор, без записи) | "drop" (4xx: тело
    не примут и потом) | "retry" (сеть, 5xx — остаётся в очереди). Без исключений."""
    try:
        code, res = _cond_req(body)
    except Exception as e:  # noqa: BLE001 — сбой записи не роняет проход
        print(f"cond_post {body.get('condition_id')} {body.get('event')}: {e}", flush=True)
        return "retry"
    if code == 200:
        return "dup" if (res or {}).get("duplicate") else "ok"
    print(f"cond_post {body.get('condition_id')} {body.get('event')}: {code} {res}", flush=True)
    return "drop" if 400 <= code < 500 else "retry"


def touch_condition(cid, price, now, version=None):
    """Порог пересечён: событие fired (by: notifier, data.price, version) в conditions-state.json через hub-api.
    → True, если записано; повтор сервер отбрасывает ({"duplicate": true}) — False; сбой — False."""
    body = {"condition_id": cid, "event": EV_FIRED, "by": "notifier", "data": {"price": price}}
    if version is not None:
        body["version"] = version
    return cond_post(body) == "ok"


def queue_cond(st, posts, now):
    """События состояния — в очередь state.json (переживает сбой hub-api и перезапуск); метки задач
    (находка монитора, решение) — в cond_seen: поставленное в очередь второй раз не ставится."""
    box = st.setdefault("cond_outbox", [])
    seen = st.setdefault("cond_seen", {})
    ts = jobs.now_iso(now)
    for mark, body in posts:
        box.append(body)
        if mark:
            seen[mark] = ts
    st["cond_outbox"] = box[-OUTBOX_MAX:]
    cutoff = (now - timedelta(days=SENT_KEEP_DAYS)).isoformat()
    st["cond_seen"] = {k: v for k, v in seen.items() if v >= cutoff}


def flush_cond(st, post=None):
    """Отправить очередь по порядку; «retry» остаётся (порядок сохраняется), остальное снимается. → итоги."""
    post = post or cond_post
    keep, out = [], []
    for body in st.get("cond_outbox") or []:
        r = post(body) if not keep else "retry"     # после первого сбоя — не дальше: порядок событий важен
        out.append(r)
        if r == "retry":
            keep.append(body)
    st["cond_outbox"] = keep
    return out


_daily_err_logged = {}                  # день, за который сбой ежедневного прохода уже записан в журнал


def tick(now=None, send=send_all, prices_fn=fetch_prices, post_fn=None):
    now = now or datetime.now(MSK)
    today = now.date().isoformat()
    with _lock:
        st = _read("state.json", None) or new_state()
        st.pop("price_hits", None)              # до шага 7: касания для сводки «Ждут решения» — теперь событие fired
        if daily_due(st, now):
            st["last_daily"] = today
            t0 = time.monotonic()
            mode = ai_mode(ROOT)
            try:
                evs, posts = collect_daily(ROOT, today, st.get("cond_seen"), jobs.now_iso(now), mode)
            except Exception as e:
                if _daily_err_logged.get("day") != today:       # сбой повторяется каждую минуту — в журнал раз в сутки
                    _daily_err_logged["day"] = today
                    jobs.log("notify-daily", "error", t0, ok=False, error=f"{type(e).__name__}: {e}"[:300].replace("\n", " "))
                raise
            queue_cond(st, posts, now)
            flush_cond(st, post_fn)
            # до 1.8.0 смена вердикта шла по бумаге (verdict:{вид}:{тикер}:{дата}); обзор, по которому так уже
            # сообщали, второй раз сводкой не сообщается
            evs = [e for e in evs if not (e["key"].startswith("verdicts:") and any(
                k.startswith("verdict:" + e["key"].split(":")[1] + ":") and k.endswith(":" + e["key"].split(":")[2])
                for k in st["sent"]))]
            opn = [e for e in evs if e.get("kind") == "cond_open"]
            r1 = process([e for e in evs if e not in opn], st, now, send, combine=events_summary)
            r2 = process(opn, st, now, send, combine=cond_summary)   # «ждёт владельца» — своим уведомлением
            stale = check_stale(ROOT, today, mode)
            r3 = process(stale, st, now, send, combine=stale_summary)
            try:
                ahead = check_ahead(ROOT, today)
            except Exception as e:                 # сбой напоминаний не должен ронять остальные проверки
                print(f"notifier: напоминания заранее: {type(e).__name__}: {e}", flush=True)
                ahead = []
            r4 = process(ahead, st, now, send, combine=ahead_summary)
            try:
                nodec = check_no_decision(ROOT, today, mode)
            except Exception as e:
                print(f"notifier: бумаги без решения: {type(e).__name__}: {e}", flush=True)
                nodec = []
            r4 += process(nodec, st, now, send, combine=no_decision_summary)
            try:
                infl = check_inflation_due(ROOT, today, mode)
            except Exception as e:
                print(f"notifier: пора внести инфляцию: {type(e).__name__}: {e}", flush=True)
                infl = []
            r4 += process(infl, st, now, send)
            defs, _ = load_conditions(ROOT)
            jobs.log("notify-daily", "ok", t0, ok=True, conds=len(defs or []), events=len(posts),
                     pushed=sum(1 for r in r1 + r2 + r3 + r4 if r["status"] == "sent"), stale=len(stale), ai_mode=mode,
                     ahead=len(ahead), no_decision=len(nodec), macro_infl=len(infl))
        if hourly_due(st, now):
            st["last_hourly"] = now.strftime("%Y-%m-%dT%H")
            prices = prices_fn()
            if prices:
                hv = collect_hourly(ROOT, today, prices)
                queue_cond(st, [(None, {"condition_id": e["cid"], "version": e["version"], "event": EV_FIRED,
                                        "by": "notifier", "data": {"price": e["price"]}}) for e in hv], now)
                process(hv, st, now, send)
            if st.get("cond_outbox"):
                flush_cond(st, post_fn)
        _write("state.json", st)


# ─────────────────────────── задачи сайта (API-1) ───────────────────────────
# Цены US eShop — каждый день в DAILY_AT (08:30 MSK), неудача — один повтор в RETRY_AT;
# макросрез — по будням в то же время, тот же повтор. Результат пишет hub-api (jobs.py),
# журнал прогонов — Claude-Memory/_jobs/log-ГГГГ-ММ.jsonl. Кнопка «Обновить цены» —
# /internal/eshop-refresh (через hub-api), не чаще раза в ESHOP_MANUAL_MIN минут.
RETRY_AT = os.environ.get("JOBS_RETRY_AT", "09:00")
ESHOP_MANUAL_MIN = 10
WEEKDAY_JOBS = ("macro", "prices")     # по выходным не запускаются
# цены закрытия держимых бумаг: после основной сессии MOEX (19:00 MSK), повтор при сбое — 20:00; пропущенные дни не догоняем
JOB_TIMES = {"prices": (os.environ.get("PRICES_AT", "19:00"), os.environ.get("PRICES_RETRY_AT", "20:00"))}
_jobs_lock = threading.Lock()          # задача не идёт дважды разом (расписание и кнопка)


def job_due(js, now, job):
    """Пора ли запускать: сегодня ещё не было успеха и попытка по расписанию не сделана."""
    if job in jobs.JOBS_OFF or (job in WEEKDAY_JOBS and now.weekday() >= 5):
        return False
    j = js.get(job) or {}
    today = now.date().isoformat()
    if j.get("ok_date") == today:
        return False
    tries = j.get("tries", 0) if j.get("date") == today else 0
    hm = (now.hour, now.minute)
    first, retry = JOB_TIMES.get(job, (DAILY_AT, RETRY_AT))
    if tries == 0:
        return hm >= tuple(int(x) for x in first.split(":"))
    return tries == 1 and hm >= tuple(int(x) for x in retry.split(":"))


def _mark(js, job, now, ok):
    today = now.date().isoformat()
    j = js.setdefault(job, {})
    j["tries"] = (j.get("tries", 0) if j.get("date") == today else 0) + 1
    j["date"] = today
    j["last_try"] = jobs.now_iso(now)
    if ok:
        j["ok_date"] = today


def run_eshop(now, send=None, opener=None):
    """Прогон цен + push «порог выполнен» и «ушла в скидку» (скидки — одной сводкой). → итог для журнала."""
    started = time.monotonic()
    kw = {"opener": opener} if opener else {}
    try:
        _, evs, summ = eshop.run(lambda: load_yaml(ROOT / "Gaming/watchlist.yaml") or {},
                                 jobs.read, jobs.save, now, **kw)
    except Exception as e:  # noqa: BLE001 — запись/чтение через hub-api; журнал обязателен
        return jobs.log("eshop", "error", started, error=f"{type(e).__name__}: {e}"[:300])
    if evs:
        with _lock:
            st = _read("state.json", None) or new_state()
            process([e for e in evs if e["kind"] != "eshop_sale"], st, now, send or send_all)
            process([e for e in evs if e["kind"] == "eshop_sale"], st, now, send or send_all,
                    combine=eshop.sale_summary)
            _write("state.json", st)
    return jobs.log("eshop", summ.pop("status"), started, **summ)


def run_macro(now, make=None):
    started = time.monotonic()
    try:
        summ = macro_job.run(ROOT, jobs.save, now.date().isoformat(), make=make)
    except Exception as e:  # noqa: BLE001
        return jobs.log("macro", "error", started, error=f"{type(e).__name__}: {e}"[:300])
    return jobs.log("macro", summ.pop("status"), started, **summ)


def run_prices(now, fetch=None, read=None, save=None):
    """Дневной ряд цен закрытия → Portfolio/prices/daily-ГГГГ.jsonl (prices_job). Не торговый день — skip, не ошибка."""
    started = time.monotonic()
    try:
        summ = prices_job.run(ROOT, QUOTES_URL, now, fetch=fetch, read=read, save=save or jobs.save)
    except Exception as e:  # noqa: BLE001
        return jobs.log("prices", "error", started, error=f"{type(e).__name__}: {e}"[:300])
    return jobs.log("prices", summ.pop("status"), started, **summ)


RUNNERS = {"eshop": run_eshop, "macro": run_macro, "prices": run_prices}


def jobs_tick(now=None, runners=None):
    now = now or datetime.now(MSK)
    runners = runners or RUNNERS
    js = _read("jobs.json", {})
    for job, fn in runners.items():
        if not job_due(js, now, job):
            continue
        with _jobs_lock:
            rec = fn(now)
        _mark(js, job, now, rec.get("status") != "error")
        _write("jobs.json", js)


def eshop_refresh(now=None, runner=None):
    """Кнопка «Обновить цены». → (HTTP-код, тело)."""
    now = now or datetime.now(MSK)
    js = _read("jobs.json", {})
    last = js.get("eshop_manual")
    if last:
        wait = ESHOP_MANUAL_MIN * 60 - (now - datetime.fromisoformat(last)).total_seconds()
        if wait > 0:
            return 429, {"ok": False, "error": f"не чаще раза в {ESHOP_MANUAL_MIN} минут",
                         "retry_after": int(wait) + 1}
    if not _jobs_lock.acquire(blocking=False):
        return 409, {"ok": False, "error": "загрузка цен уже идёт"}
    try:
        js["eshop_manual"] = jobs.now_iso(now)
        _write("jobs.json", js)
        rec = (runner or run_eshop)(now)
    finally:
        _jobs_lock.release()
    ok = rec.get("status") != "error"
    return (200 if ok else 502), {"ok": ok, "status": rec.get("status"), "error": rec.get("error"),
                                  "items": rec.get("items"), "at": rec.get("ts")}


def nsuid_lookup(body, getter=None, steam_getter=None):
    """Поиск nsuid/обложки игры (games.html): {title?, platform?, eshop_url?} → (200, результат) | (404, …) | (502, …).

    Платформа steam/steam_deck/pc/xbox — Steam, switch/switch2 — eShop, иначе eShop и откат на Steam."""
    q = str((body or {}).get("eshop_url") or (body or {}).get("title") or "").strip()
    if not q:
        return 400, {"error": "нужны title или eshop_url"}
    try:
        hit = eshop_lookup.lookup_any({"title": str((body or {}).get("title") or "").strip() or q,
                                       "platform": (body or {}).get("platform"),
                                       "eshop_url": (body or {}).get("eshop_url")},
                                      getter or eshop_lookup.fetch, steam_getter or eshop_lookup.steam_fetch)
    except (OSError, ValueError) as e:        # URLError и HTTPError — наследники OSError
        return 502, {"error": "US eShop недоступен", "detail": f"{type(e).__name__}: {e}"[:200]}
    if not hit:
        return 404, {"error": "не найдено в US eShop"}
    return 200, hit


NSUID_FILL_MAX = 40
NSUID_FILL_PAUSE = 0.7
NSUID_FILL_BUDGET = 25.0


def nsuid_fill(body, getter=None, sleep=time.sleep, budget=NSUID_FILL_BUDGET, clock=time.monotonic, steam_getter=None):
    """Массовый подбор nsuid/обложек (games.html): {items:[{title, platform?, eshop_url?}]} → (200, {results, done}).

    Последовательно, eshop_url главнее названия; пауза между запросами к Nintendo; бюджет времени —
    не уложились → то, что успели, done=false. Больше NSUID_FILL_MAX записей → 400."""
    items = (body or {}).get("items")
    if not isinstance(items, list) or not items:
        return 400, {"error": "нужен непустой список items"}
    if len(items) > NSUID_FILL_MAX:
        return 400, {"error": f"не больше {NSUID_FILL_MAX} записей за раз"}
    get = getter or eshop_lookup.fetch
    sget = steam_getter or eshop_lookup.steam_fetch
    t0 = clock()
    results, done = [], True
    for n, it in enumerate(items):
        if n:
            if clock() - t0 >= budget:
                done = False
                break
            sleep(NSUID_FILL_PAUSE)
        it = it if isinstance(it, dict) else {}
        title = str(it.get("title") or "").strip()
        try:
            hit = eshop_lookup.lookup_any({"title": title, "platform": it.get("platform"),
                                           "eshop_url": it.get("eshop_url")}, get, sget)
        except (OSError, ValueError):
            results.append({"title": title, "error": "сеть"})
            continue
        if not hit:
            results.append({"title": title, "error": "не найдено"})
            continue
        results.append(hit)
    return 200, {"results": results, "done": done}


def scheduler():
    while True:
        try:
            tick()
        except Exception:
            traceback.print_exc()
        try:
            jobs_tick()
        except Exception:
            traceback.print_exc()
        time.sleep(60)


# ─────────────────────────── HTTP ───────────────────────────
def _devices(subs):
    return [{"label": s.get("label") or "устройство", "added": s.get("added")} for s in subs]


def pf_last_run():
    d = pf_build.runs_dir(DATA)
    runs = sorted(p.name for p in d.iterdir() if p.is_dir()) if d.is_dir() else []
    return runs[-1] if runs else None


class Handler(BaseHTTPRequestHandler):
    server_version = "hub-notify/" + VERSION

    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 16384:
                return None
            return json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return None

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/internal/health":
            # для hub-api → /api/health → deploy.zsh: контейнер на старом коде? (отпечаток при старте)
            return self._json(200, {"version": VERSION, "code": CODE_HASH})
        if u.path == "/api/push/key":
            _, pub = vapid_keys()
            with _lock:
                st = _read("state.json", None) or new_state()
                subs = _read("subscriptions.json", [])
            return self._json(200, {"public_key": pub, "mode": st["mode"], "devices": len(subs), "version": VERSION})
        if u.path == "/api/push/status":
            q = parse_qs(u.query)
            ep = (q.get("endpoint") or [""])[0]
            sec = (q.get("section") or [""])[0] or None
            with _lock:
                st = _read("state.json", None) or new_state()
                subs = _read("subscriptions.json", [])
            return self._json(200, {"mode": st["mode"], "off": st.get("off") or [], "kinds": KINDS, "sections": SECTIONS,
                                    "subscribed": any(s["endpoint"] == ep for s in subs),
                                    "devices": _devices(subs), "last_daily": st.get("last_daily"),
                                    "last_hourly": st.get("last_hourly"), "log": log_for(st["log"], sec),
                                    "version": VERSION})
        if u.path == "/api/pf/status":
            run = (parse_qs(u.query).get("run") or [""])[0] or pf_last_run()
            st = pf_build.read_status(DATA, run) if run else None
            if not st:
                return self._json(404, {"error": "сборок ещё не было" if not run else "нет такого прогона"})
            return self._json(200, st)
        if u.path == "/api/pf/stress/weights":
            try:
                return self._json(*stress_job.get_weights(
                    ROOT, refresh=(Path(DATA) / "pf" / "stress", jobs.save, subprocess.run)))
            except Exception as e:  # noqa: BLE001
                return self._json(500, {"error": f"{type(e).__name__}: {str(e)[:300]}"})
        return self._json(404, {"error": "not found"})

    def _do_pf_build(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > pf_build.MAX_BODY:
                return self._json(413, {"error": "файлы больше 30 МБ"})
            payload = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return self._json(400, {"error": "bad json"})
        return self._json(*pf_build.start(DATA, ROOT, payload, datetime.now(MSK), log=jobs.log))

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/api/pf/build":
            return self._do_pf_build()
        b = self._body()
        if b is None:
            return self._json(400, {"error": "bad json"})
        if u.path == "/api/pf/cancel":
            return self._json(*pf_build.cancel(DATA, str(b.get("run") or "")))
        if u.path == "/api/pf/save":
            try:
                return self._json(*pf_build.save(DATA, str(b.get("run") or ""), jobs.save, datetime.now(MSK),
                                                 log=jobs.log, root=ROOT, read_fn=jobs.read,
                                                 background=True))
            except jobs.SaveError as e:
                return self._json(502, {"error": str(e)[:300]})
        if u.path == "/api/pf/decision":
            # решение владельца с карточки бумаги → Portfolio/decisions/ (decision_job); файл всегда новый
            def _save_new(rel, content):
                try:
                    return jobs.save_new(rel, content)
                except jobs.ExistsError:
                    raise decision_job.AlreadyExists(rel) from None
            try:
                return self._json(*decision_job.post_decision(ROOT, b, _save_new, datetime.now(MSK), read_fn=jobs.read))
            except jobs.SaveError as e:
                return self._json(502, {"error": str(e)[:300]})
            except Exception as e:  # noqa: BLE001
                return self._json(500, {"error": f"{type(e).__name__}: {str(e)[:300]}"})
        if u.path == "/api/pf/condition":
            # условие-напоминание владельца → Portfolio/conditions.yaml (condition_job): add / withdraw, запись с base_hash
            def _save_cas(rel, content, base_hash):
                try:
                    return jobs.save_if(rel, content, base_hash)
                except jobs.ConflictError:
                    raise condition_job.Conflict(rel) from None
            try:
                return self._json(*condition_job.post_condition(ROOT, b, _save_cas, datetime.now(MSK), read_fn=jobs.read,
                                                                quotes_fn=fetch_prices, held_fn=lambda: held_keys(ROOT)))
            except jobs.SaveError as e:
                return self._json(502, {"error": str(e)[:300]})
            except Exception as e:  # noqa: BLE001
                return self._json(500, {"error": f"{type(e).__name__}: {str(e)[:300]}"})
        if u.path in ("/api/pf/stress/weights", "/api/pf/stress/terms", "/api/pf/stress/recalc", "/api/pf/splits"):
            try:
                if u.path == "/api/pf/splits":
                    return self._json(*stress_job.post_splits(ROOT, b, jobs.save, datetime.now(MSK), read_fn=jobs.read))
                if u.path == "/api/pf/stress/terms":
                    return self._json(*stress_job.post_terms(ROOT, b, jobs.save, datetime.now(MSK)))
                if u.path == "/api/pf/stress/recalc":
                    return self._json(*stress_job.post_recalc(ROOT, Path(DATA) / "pf" / "stress", jobs.save,
                                                              subprocess.run, datetime.now(MSK)))
                return self._json(*stress_job.post_weights(ROOT, Path(DATA) / "pf" / "stress", b, jobs.save,
                                                           subprocess.run, datetime.now(MSK)))
            except jobs.SaveError as e:
                return self._json(502, {"error": str(e)[:300]})
            except Exception as e:  # noqa: BLE001
                return self._json(500, {"error": f"{type(e).__name__}: {str(e)[:300]}"})
        if u.path == "/internal/nsuid-lookup":
            if self.headers.get("X-Forwarded-For"):
                return self._json(403, {"error": "internal only"})
            return self._json(*nsuid_lookup(b))
        if u.path == "/internal/nsuid-fill":
            if self.headers.get("X-Forwarded-For"):
                return self._json(403, {"error": "internal only"})
            return self._json(*nsuid_fill(b))
        if u.path in ("/internal/zm-csv-report", "/internal/zm-csv-apply", "/internal/zm-rule", "/internal/zm-trip", "/internal/zm-stmt-report"):
            # выгрузка CSV ZenMoney (zm_csv.py): отчёт и запись по «да»; только из docker-сети (hub-api)
            if self.headers.get("X-Forwarded-For"):
                return self._json(403, {"error": "internal only"})
            route = {"/internal/zm-csv-report": zm_csv.route_report, "/internal/zm-csv-apply": zm_csv.route_apply,
                     "/internal/zm-rule": zm_csv.route_rule, "/internal/zm-trip": zm_csv.route_trip,
                     "/internal/zm-stmt-report": zm_stmt.route_report}[u.path]
            try:
                return self._json(*route(ROOT, b, datetime.now(MSK), jobs.read, jobs.save, jobs.log))
            except jobs.SaveError as e:
                return self._json(502, {"error": str(e)[:300]})
        if u.path == "/internal/eshop-refresh":
            # только из docker-сети (hub-api); Caddy сюда не проксирует, а если бы — с X-Forwarded-For
            if self.headers.get("X-Forwarded-For"):
                return self._json(403, {"error": "internal only"})
            return self._json(*eshop_refresh())
        if u.path == "/api/push/subscribe":
            s = b.get("subscription") or {}
            ep, keys = s.get("endpoint"), s.get("keys") or {}
            if not (isinstance(ep, str) and ep.startswith("https://") and keys.get("p256dh") and keys.get("auth")):
                return self._json(400, {"error": "bad subscription"})
            with _lock:
                subs = [x for x in _read("subscriptions.json", []) if x["endpoint"] != ep]
                subs.append({"endpoint": ep, "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]},
                             "label": _short(b.get("label") or "", 40) or None,
                             "added": jobs.now_iso()})
                _write("subscriptions.json", subs[-10:])
            return self._json(200, {"ok": True, "devices": len(subs)})
        if u.path == "/api/push/prune":
            keep = b.get("keep")
            with _lock:
                subs = [x for x in _read("subscriptions.json", []) if keep and x["endpoint"] == keep]
                _write("subscriptions.json", subs)
            return self._json(200, {"ok": True, "devices": len(subs)})
        if u.path == "/api/push/unsubscribe":
            ep = b.get("endpoint")
            with _lock:
                subs = [x for x in _read("subscriptions.json", []) if x["endpoint"] != ep]
                _write("subscriptions.json", subs)
            return self._json(200, {"ok": True, "devices": len(subs)})
        if u.path == "/api/push/test":
            # на ВСЕ подписанные устройства: «нажал на компе — пришло и на телефон» (решение 2026-10-16)
            with _lock:
                subs = _read("subscriptions.json", [])
            if not subs:
                return self._json(404, {"error": "no devices"})
            msg = {"title": "Портфель: пробное уведомление",
                   "body": "Уведомления работают. Нажми — откроется «Сегодня».",
                   "url": f"{VIEWER}#tab=today", "tag": "test"}
            results, dead = [], []
            for x in subs:
                code = push_one(x, msg)
                results.append({"label": x.get("label") or "устройство", "ok": 200 <= code < 300, "push_status": code,
                                "this": x["endpoint"] == b.get("endpoint")})
                if code in (404, 410):
                    dead.append(x["endpoint"])
            if dead:   # подписка умерла (устройство отозвало) — убрать, иначе «подписано» врёт
                with _lock:
                    _write("subscriptions.json", [x for x in _read("subscriptions.json", []) if x["endpoint"] not in dead])
            return self._json(200, {"ok": all(r["ok"] for r in results), "results": results, "removed": len(dead)})
        if u.path == "/api/push/mode":
            mode = b.get("mode")
            if mode not in ("quiet", "live"):
                return self._json(400, {"error": "mode: quiet | live"})
            with _lock:
                st = _read("state.json", None) or new_state()
                st["mode"] = mode
                _write("state.json", st)
            return self._json(200, {"ok": True, "mode": mode})
        if u.path == "/api/push/settings":
            off = b.get("off")
            if not isinstance(off, list) or any(k not in KIND_IDS for k in off):
                return self._json(400, {"error": "off: список из " + ", ".join(KIND_IDS)})
            with _lock:
                st = _read("state.json", None) or new_state()
                st["off"] = [k for k in KIND_IDS if k in off]
                _write("state.json", st)
            return self._json(200, {"ok": True, "off": st["off"]})
        return self._json(404, {"error": "not found"})


class _Srv(ThreadingHTTPServer):
    daemon_threads = True


def main():
    vapid_keys()
    threading.Thread(target=scheduler, daemon=True).start()
    print(f"hub-notify {VERSION}: :{PORT}, root={ROOT}, data={DATA}", flush=True)
    _Srv(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
