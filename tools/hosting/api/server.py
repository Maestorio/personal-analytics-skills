#!/usr/bin/env python3
"""Write-API sidecar для Personal Hub (второй контейнер рядом с Caddy).

Единственный писатель со стороны веба. Обслуживает ДВА ТОМА и ТРИ зоны доступа.

Тома (с миграции 2026-08-13 — поддеревья ОДНОГО дерева /volume1/homes/hubuser/Claude-Memory,
вне облачных синков; ro/rw-разделение томов сохранено сознательно):

  * Claude-Memory (`/srv`) — travel, games, портфель, страницы;
  * Health (`/srv-health`) — медицинские данные;
  * Food (`/srv-food`) — еда.

Зоны — это не то же самое, что тома: у зоны свой whitelist и свой валидатор, а
корень может совпадать. `/api/*` и `/api/fd/*` смотрят в ОДИН том, но пути у них
не пересекаются (travel/games — markdown-артефакты, еда — JSON в `Food/`), и
формат проверяется по-разному. Разделены именно ради этого: у еды есть схема,
которую нельзя дать сломать, а у travel-артефактов её нет.

Протокол (JSON):

  GET  /api/health          → {"ok", "writable", "api": {"code"}, "health_writable",
                               "health_files", "food_files"}
                              api.code — отпечаток server.py работающего процесса (deploy.zsh
                              сверяет с _nas/api/server.py: устаревший контейнер).
                              healthcheck + ВОЗМОЖНОСТИ сайдкара (историческое имя;
                              к разделу «Здоровье» отношения не имеет).
                              *_files — какие живые файлы этот сайдкар умеет:
                              по ним страницы и deploy.zsh ловят рассинхрон версий.
  GET  /api/file?path=…     → {"path", "content", "hash"} — Claude-Memory
  POST /api/save            → тело {"path", "content", "base_hash"} — Claude-Memory
  GET  /api/hub/settings    → {"path", "hash", "settings"} — режим сайта «с ИИ / без ИИ»
                              (Claude-Memory/_hub/settings.json, hub-settings@1); нет файла → режим on, hash null
  POST /api/hub/settings    → тело {"settings": {"ai_mode": on|off, "by"?, "note"?}, "base_hash"} —
                              переходы ставит сервер (off_since / returned_at / updated_at); 409 при гонке
  GET  /api/hub/changes?since=… → {"since", "generated_at", "zones", "files": [{"path", "size", "mtime",
                              "sha256"}], "truncated"} — файлы зон Portfolio/ Gaming/ Health/ ZenMoney/ _hub/,
                              изменённые после since (с хэшем); без since — все, без хэшей. Сверка зеркала
                              Mac после режима «без ИИ» (tools/noai_return.py)
  GET  /api/gm/file?path=Gaming/user-state.json → оверлей игр (gaming-user@1); POST /api/gm/save — запись
                              (base_hash, валидатор validate_gaming; пароль с любого IP)
  GET  /api/hd/file?path=…  → то же для Health-Data
  POST /api/hd/save         → то же для Health-Data (whitelist: живые JSON, biomarkers-info.json, reports/*.md)
  POST /api/hd/report       → тело {"name"|"topic", "content", "overwrite"?}: отчёт health-report@1 → Health/reports/
                              (форма — validate_report.check скилла health-labs; то же имя с другим текстом — 409
                              «exists», пока нет overwrite: true; копия — в .versions/)
  POST /api/hd/marker-info  → тело {"id", "what": [..], "up", "down", "base_hash"}: справка одного маркера в
                              biomarkers-info.json (validate_labs_info.merge_info(manual=True): запись помечается
                              manual и скилл её не затирает); 409 при гонке
  POST /api/hd/upload       → тело {"kind", "date", "b64"} (до 28 МБ, HD_UPLOAD_BODY_MAX; файл ≤ 20 МБ): файл
                              исследования → Health/studies/ГГГГ-ММ-ДД-вид.ext; тип по первым байтам (PDF, JPEG,
                              PNG, HEIC), занятое имя не перезаписывается (-2, -3…); ответ {"name", "path", "type"}
  GET  /api/hd/file?path=labs.json, POST /api/hd/save {path: "labs.json", content, base_hash} — анализы. Пишет
                              скилл health-labs (intake.py); со страницы — ТОЛЬКО при ai_mode: off и только ручные
                              точки source=manual (+ новый показатель): при on — 403; правка точек скилла, категорий,
                              чужих полей маркера — 400; base_hash обязателен (409 при гонке). Статус точки и
                              производные поля маркера (kind/unit/ref) считает сервер — labs_rules.check_manual_edit.
                              Модули validate_report.py / validate_labs_info.py / labs_rules.py / hub_settings.py лежат рядом с
                              server.py (compose монтирует в /app, deploy кладёт в _nas/api/).
  GET  /api/fd/file?path=…  → то же для раздела «Еда» (Claude-Memory/Food)
  POST /api/fd/save         → то же для раздела «Еда»
  POST /api/fd/delete       → тело {"path", "base_hash"} — удаление файла рецепта
                              (копия в .versions/, потом remove). Больше нигде
                              удаления нет: см. FOOD_DELETABLE.
  POST /api/fd/shop-add     → тело {"text" | "items": [..], "source"?} — позиция или несколько через «,»/«и»
                              («молоко 2 литра, хлеб») в список покупок, только
                              продукты каталога; ответ {"status", "message",
                              "choose": [{text, message, candidates}]}. Для
                              шортката iPhone: base_hash и пересборку JSON сервер
                              берёт на себя.
  POST /api/pv/sync         → тело {"have": {путь: версия}} — вьюер портфеля одним запросом
                              (pv-sync@1): папки вьюера (имя + версия) и содержимое только
                              новых/изменившихся файлов, до 6 МБ за ответ (more: true — ещё).
                              Только чтение; зона — пароль с любого IP (см. PV_DIRS).
  GET  /api/pv/plan         → план портфеля: {"path", "hash", "plan"} из Portfolio/plan.json (404 — нет файла)
  GET  /api/pv/cond/state?since=ISO+03:00 → {"schema_version", "events": [...]} события условий с at > since (все — без since); файла нет → пусто
  POST /api/pv/cond/event   → {"condition_id", "event", "data"?} — отметка владельца с сайта: owner_mark (data.mark dismissed|deferred; у deferred обязателен data.until), done (by: owner), reopened, event_found (кнопка «вышел»: только ждущее условие с триггером report_published или event — сервер сверяет последнюю версию в conditions.yaml и события состояния; data.note необязателен); иначе 400. Ответ {event, events}; at ставит сервер
  POST /api/pv/cond/event/internal → для hub-notify (та же авторизация: заголовок Authorization): fired | expired | event_found | done (by: site, в data decision_id или trade_date); {"by": notifier|site|script}. Повтор → 200 {"duplicate": true}, без записи: для той же пары condition_id+version незакрытый fired, терминальное (done, expired, dismissed) или event_found с тем же data.doc
  POST /api/pv/plan/set     → пакет {"changes": [{"path": "stocks.T.plan_pct", "value"}, ...] (1–50),
                              "reason", "base_hash"} (или старая форма {path, value, reason, base_hash}) —
                              все изменения проверяются по PLAN_PATH_RULES до записи (400 с "index"; дубль
                              пути → 400 duplicate path), файл пишется ОДИН раз, журнал — одним проходом.
                              Ответ {hash, plan, entries, entry=entries[0]}. user_status: код DONE/DEFERRED/
                              ORDER/NOTED, строка ≤120 или null. base_hash не сошёлся → 409 со свежим
                              планом; успех пишет файл (копия в .versions/) и строки в
                              Portfolio/plan-journal.jsonl. Зона /api/pv/* — пароль с любого IP.
                              Пути (этап 4, элементы списков — по ключу, запись создаётся): classes.<Класс>.share,
                              matrix.<CUR>/<Класс>.share, bond_buckets.<ключ>.share (доли единицы 0..1 или null;
                              сумма ≠ 1 не запрещена), bonds.<ISIN>.(type|subtype|rating|action|iis_qty|manual|reason),
                              funds.<T>.(class|currency|in_rebalance|bucket|note|fee_pct|spread_pct; fee_pct — комиссия фонда, % в год, spread_pct — спред, %: число ≥ 0 или null; bucket — любой из девяти ключей корзин PLAN_BUCKET_KEYS или null), manual_positions.<тип>/<имя>.value_rub (запись суммы ставит value_as_of = сегодня).
  POST /api/pv/plan/ie-import → тело {"name", "b64", "tickers"?} — страница IE (webarchive Safari или голый
                              HTML) → разбор по заголовкам колонок и diff к plan.json БЕЗ записи:
                              {kind: model|general, rows, positions, cash_pct, diff, ignored, hash};
                              у каждого элемента diff ключ held (тикер из tickers); general — все
                              строки в diff, ignored всегда [].
                              Тело до 16 МБ (IE_IMPORT_MAX_BYTES), больше → 413; не разобрать → 400.
  POST /api/pv/plan/ie-set  → тело {"base_hash", "source": site|webarchive, "page"?: model|general, "extraction_date"?, "cash_pct"?,
                              "changes": [{ticker, share_pct?, note_ie?, reason?, position?}]} — единственный
                              писатель долей/позиций модели IE: stocks.T.ie_new_pct/ie_old_pct, ie_model.*,
                              ie_history; webarchive+page=general пишет ie_model.general_date, а не extraction_date;
                              файл — один раз, журнал — одним проходом; ответ {hash, plan, entries}.
  GET  /api/pv/plan/export?format=json|xlsx → база сайта (plan.json) вложением site-db-{дата}: json — байты как есть, xlsx — до девяти
                              листов-таблиц Excel с фильтрами и закреплённой шапкой (назад не грузится); заголовок X-Plan-Hash; 404 нет файла, 400 иной format.
  POST /api/pv/plan/import  → тело {"base_hash", "plan", "reason"? ≤300, "dry_run"?, "name"?} (до 2 МБ) — JSON базы сайта целиком:
                              проверка ДО записи (schema_version plan@1.0, разделы по правилам set; 400 bad plan + problems ≤50),
                              diff к текущему файлу {path, old, new} (≤2000, diff_truncated) и counts; dry_run — без записи, пустой
                              diff — unchanged без записи; запись: updated_by hub-api, журнал — одна строка kind=import.
  POST /api/pv/macro/inflation → тело {"record": {date, week_pct, week_period, yoy_pct, yoy_as_of?, source_name, source_url?}, "base_hash"?}
                              (поля можно слать и без обёртки) — недельная инфляция владельца с формы «Внести инфляцию» вьюера:
                              проверка границ (400 bad record + problems), строка author "owner" дописывается в
                              macro-snapshots/inflation/owner.jsonl (единственный писатель файла; model.jsonl — скилл); base_hash —
                              sha256 owner.jsonl (пустого — sha256 пустых байтов), не сошёлся → 409 со свежим current_hash; повтор той же
                              записи — 200 {"duplicate": true}. Ответ {record, hash, records}. Зона /api/pv/* — пароль с любого IP.
  GET  /api/pv/plan/journal?limit=50[&since=ISO+03:00] → {"entries": [...]} последние строки журнала, новые первыми (≤500)
  GET  /api/moex/quotes?boards=TQBR → котировки MOEX (quotes@1), только чтение
                              публичных рыночных данных; состав портфеля в запросе
                              не передаётся. boards — через запятую из белого
                              списка TQBR, TQOB, TQCB (иная → 400). Прокси к ISS
                              с кэшем по доске в памяти (5 мин в торговые часы MSK,
                              30 мин вне их; ISS упал → кэш до 24 ч со stale:true,
                              кэша нет → 502). Тома не использует.

  POST /api/zm/csv          → тело {"name", "b64"} (до 16 МБ): выгрузка CSV ZenMoney → ZenMoney/csv/incoming/<id>.csv,
                              ответ {id, name, sha256, rows, first, last}; пароль с любого IP (Caddy), как /api/gm/*
  POST /api/zm/csv-report   → {"id"}: проброс в hub-notify /internal/zm-csv-report (отчёт zm-csv-report@1)
  POST /api/zm/csv-apply    → {"id", "confirm": true}: проброс в hub-notify /internal/zm-csv-apply (запись истории)
  POST /api/zm/rule         → {"id", "month", "date", "account", "amount", "payee"?, "note"} («Это разовая») или
                              {"id", "remove": true, "rule_id"|тройка}: проброс в hub-notify /internal/zm-rule, ответ — пересчитанный отчёт
  POST /api/zm/trip         → {"id", "name", "start", "end"} («Добавить поездку»): проброс в /internal/zm-trip, ответ — пересчитанный отчёт
  GET  /api/zm/csv-state    → {last: {name, sha256, written_at}|null, incoming: [id], aux_ok}
  POST /api/zm/stmt         → тело {"name", "b64"} (до 11 МБ, файл ≈ 8 МБ): сверка выписки банка без ZenMoney (задача 3.8) — выписка XLSX / CSV (Bank of Georgia, Райффайзенбанк)
                              (тип по содержимому: zip с xl/workbook.xml, текст UTF-8/cp1251 с разделителем; расширение имени не читается;
                              PDF отклоняется 400 «PDF на сайте не разбирается…») →
                              ZenMoney/csv/stmt-incoming/<id>.<xlsx|csv>, ответ {id, name, sha256, format, size}; пароль с любого IP (Caddy)
  POST /api/zm/stmt-report  → {"id"}: проброс в hub-notify /internal/zm-stmt-report (отчёт zm-stmt-report@1 ответом, на диск не пишется);
                              файл выписки стирается сразу после ответа (при любом исходе), остатки старше часа — при каждой загрузке и отчёте.
                              Только чтение: ни ZenMoney, ни audit/, ни карта, ни словари не меняются
  GET  /api/job/file?path=…  → то же для файлов задач сайта (JOB_WHITELIST) и оверлея игр (чтение)
  POST /api/job/save        → тело {"path", "content", "base_hash"} — задачи сайта
  POST /api/job/append      → тело {"path", "line"} — строка в журнал _jobs/log-ГГГГ-ММ.jsonl
                              /api/job/* — только изнутри docker-сети (hub-notify):
                              запрос через Caddy (X-Forwarded-For) → 403.
  POST /api/games/eshop-refresh → кнопка «Обновить цены» games.html: проброс в
                              hub-notify (/internal/eshop-refresh), его код ответа
                              (429 — не чаще раза в 10 минут).

`base_hash` ≠ текущему хэшу файла → 409 c current_hash (защита от гонки с
Synology Drive, второй вкладкой или скиллом), перед записью копия в .versions/,
запись атомарная.

Пути строго по whitelist (редактирование существующих артефактов, не создание).
Health-файлы дополнительно проходят ВАЛИДАЦИЮ СХЕМЫ перед записью: структурно
битый JSON отклоняется с 400, чтобы ни страница, ни скилл-обогатитель не могли
оставить файл в нечитаемом состоянии.

Зоны доступа — уровнем выше (Caddy): `/api/*` свободен с доверенных IP, а
`/api/hd/*` требует пароль с ЛЮБОГО IP (здоровье приватно и на чтение, и на
запись — иначе устройство в LAN могло бы писать аптечку, не имея права её
прочитать).

Только stdlib. Корни задаются HUB_API_ROOT, HUB_API_HEALTH_ROOT и HUB_API_FOOD_ROOT.

Доставка правок в зеркала Synology Drive — гибрид через File Station API
(см. блок «File Station: доставка правок в синк»): HUB_API_DSM_URL /
HUB_API_DSM_ACCOUNT / HUB_API_DSM_PASSWORD + маппинг корней HUB_API_FS_ROOT /
HUB_API_FS_HEALTH_ROOT / HUB_API_FS_FOOD_ROOT. Без этих переменных сайдкар
пишет по-старому (локальный os.replace) — тесты и dev работают без DSM.
"""
import base64
import binascii
import gzip
import hashlib
import json
import os
import plistlib
import re
import shutil
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.environ.get("HUB_API_ROOT", "/srv")
HEALTH_ROOT = os.environ.get("HUB_API_HEALTH_ROOT", "/srv-health")
# «Еда» переехала в несинхронизируемое дерево к здоровью (2026-07-20):
# отдельный корень, а не подкаталог ROOT — деревья РАЗНЫЕ.
FOOD_ROOT = os.environ.get("HUB_API_FOOD_ROOT", "/srv-food")
PORT = int(os.environ.get("HUB_API_PORT", "8000"))
VERSIONS_DIR = ".versions"
# Копии в .versions/ (2026-10-23): копилось без предела — копия на каждую галочку «куплено».
# На файл держим VERSIONS_KEEP последних; из них старше VERSIONS_DAYS дней — удаляются, но
# VERSIONS_MIN самых свежих остаются всегда (откатиться есть куда даже после долгой паузы).
VERSIONS_KEEP = int(os.environ.get("HUB_API_VERSIONS_KEEP", "30"))
VERSIONS_DAYS = int(os.environ.get("HUB_API_VERSIONS_DAYS", "180"))
VERSIONS_MIN = int(os.environ.get("HUB_API_VERSIONS_MIN", "5"))
_VERSION_TS = re.compile(r"^(\d{8}-\d{6})_(.+)$")
APPEND_ONLY_RE = re.compile(r"^daily-\d{4}\.jsonl$")   # Portfolio/prices/: дописывается строкой в день
APPEND_VERSIONS_KEEP = 3
MAX_BYTES = 8 * 1024 * 1024  # артефакты — markdown и журнал решений (journal.json ~1,6 МБ и растёт); больше 8 МБ = что-то не то

# Владелец всего созданного сайдкаром. Контейнер работает под root, а вотчер
# Synology Drive Server СЛЕП к root-записям: файл, созданный root, не попадает
# в инкрементальный индекс и уезжает в зеркала только при полном рескане
# (рестарте пакета Drive) — так web-правки месяцами не доезжали до Mac
# (эмпирика гейта 0.1 миграции 2026-08-13: chown на пользователя доставляет
# файл за секунды, root-файл не доставляется вовсе). Поэтому каждый созданный
# файл и каталог сразу приводится к владельцу-человеку.
CHOWN_UID = int(os.environ.get("HUB_API_CHOWN_UID", "1026"))   # hubuser
CHOWN_GID = int(os.environ.get("HUB_API_CHOWN_GID", "100"))    # users


def _chown_quiet(path):
    """chown на владельца-человека; вне root (тесты, dev) молча пропускается."""
    try:
        os.chown(path, CHOWN_UID, CHOWN_GID)
    except OSError:
        pass


def _makedirs_owned(root, dirpath):
    """makedirs + chown каждого уровня от root (не включая) до dirpath."""
    os.makedirs(dirpath, exist_ok=True)
    p = os.path.abspath(dirpath)
    stop = os.path.abspath(root)
    while p != stop and p.startswith(stop):
        _chown_quiet(p)
        p = os.path.dirname(p)


# ─────────────────── File Station: доставка правок в синк ───────────────────
# Вотчер Synology Drive СЛЕП к файловым событиям процессов внутри docker
# (chown не помогает — фильтруется происхождение события, не владелец): всё,
# что контейнер кладёт на диск сам, не попадает в инкрементальный индекс и не
# уезжает в зеркала до полного рескана (рестарта пакета Drive). Диагноз
# 2026-08-13, гейт 0.1 миграции Claude-Memory.
#
# Обход (гибрид): содержимое собирается контейнером в staging-каталоге (это
# событие Drive не видит — и не нужно), а НА МЕСТО файл ставит File Station
# API — операцию выполняет процесс DSM на хосте, событие рождается в host
# namespace, вотчер его ловит, правка уезжает в зеркала за секунды. mv в
# пределах тома — rename(2): атомарность и вся механика base_hash/409
# сохраняются. Удаление — тем же способом (FS Delete).
#
# При ЛЮБОЙ ошибке FS (DSM лёг, пароль сменился, таймаут) — молчаливый откат
# на локальный os.replace/os.remove: запись обязана пройти всегда, деградирует
# только скорость доставки в зеркала (до ближайшего рестарта Drive).
#
# Конфиг через env; без него (тесты, dev) поведение прежнее — чистый os.replace.
DSM_URL = os.environ.get("HUB_API_DSM_URL", "").rstrip("/")
DSM_ACCOUNT = os.environ.get("HUB_API_DSM_ACCOUNT", "")
DSM_PASSWORD = os.environ.get("HUB_API_DSM_PASSWORD", "")
# Контейнерный корень → путь File Station (вид «/home/Claude-Memory»).
FS_BASES = {
    ROOT: os.environ.get("HUB_API_FS_ROOT", ""),
    HEALTH_ROOT: os.environ.get("HUB_API_FS_HEALTH_ROOT", ""),
    FOOD_ROOT: os.environ.get("HUB_API_FS_FOOD_ROOT", ""),
}
STAGING_DIR = ".hub-api-staging"


class _FileStation:
    """Минимальный клиент DSM File Station (stdlib): login + CopyMove + Delete."""

    _AUTH_ERR = {105, 106, 107, 119}  # сессия невалидна/протухла → перелогин

    def __init__(self, url, account, password):
        self.url = url
        self.account = account
        self.password = password
        self._sid = None
        self._sid_lock = threading.Lock()

    def _http(self, cgi, params, timeout=6):
        q = urllib.parse.urlencode(params)
        with urllib.request.urlopen(f"{self.url}/webapi/{cgi}?{q}", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def _login(self):
        d = self._http("auth.cgi", {
            "api": "SYNO.API.Auth", "version": "6", "method": "login",
            "account": self.account, "passwd": self.password,
            "session": "FileStation", "format": "sid"})
        if not d.get("success"):
            raise RuntimeError(f"DSM login failed: {d.get('error')}")
        self._sid = d["data"]["sid"]

    def _call(self, params):
        with self._sid_lock:
            if self._sid is None:
                self._login()
            sid = self._sid
        d = self._http("entry.cgi", {**params, "_sid": sid})
        if not d.get("success") and d.get("error", {}).get("code") in self._AUTH_ERR:
            with self._sid_lock:
                self._login()
                sid = self._sid
            d = self._http("entry.cgi", {**params, "_sid": sid})
        return d

    def move_into(self, src, dest_dir, timeout_s=5.0):
        """mv src → dest_dir/ с перезаписью. True — задача реально завершилась."""
        d = self._call({"api": "SYNO.FileStation.CopyMove", "version": "3",
                        "method": "start", "path": src,
                        "dest_folder_path": dest_dir,
                        "overwrite": "true", "remove_src": "true"})
        if not d.get("success"):
            return False
        taskid = d.get("data", {}).get("taskid", "")
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            s = self._call({"api": "SYNO.FileStation.CopyMove", "version": "3",
                            "method": "status", "taskid": taskid})
            if s.get("success") and s.get("data", {}).get("finished"):
                return True
            time.sleep(0.05)
        return False

    def delete(self, path):
        """Синхронное удаление (method=delete ждёт завершения сам)."""
        d = self._call({"api": "SYNO.FileStation.Delete", "version": "2",
                        "method": "delete", "path": path})
        return bool(d.get("success"))


_FS = (_FileStation(DSM_URL, DSM_ACCOUNT, DSM_PASSWORD)
       if DSM_URL and DSM_ACCOUNT and DSM_PASSWORD else None)


def _fs_base(root):
    """FS-путь корня («/home/Claude-Memory») или None, если гибрид не настроен."""
    base = FS_BASES.get(root, "")
    return base if (base and _FS is not None) else None


def _read_hash(path):
    try:
        with open(path, "rb") as f:
            return file_hash(f.read())
    except OSError:
        return None


# Сбой File Station (2026-10-23): раньше — только строка в логе контейнера, и правки 13 дней молча
# не доезжали до зеркал (инцидент 2026-09-02). Теперь счётчик в /api/health (fs_fallbacks,
# fs_last_fallback): его видят deploy.zsh и страницы. Сбрасывается рестартом контейнера.
FS_STATS = {"fallbacks": 0, "last": None, "last_path": None}

MSK = timezone(timedelta(hours=3))


def _now_iso(now=None):
    """Единственная запись времени в файлы и ответы: `ГГГГ-ММ-ДДTЧЧ:ММ:СС+03:00` (МСК, schema.md §1 п.4)."""
    return (now or datetime.now(MSK)).astimezone(MSK).strftime("%Y-%m-%dT%H:%M:%S+03:00")


def _fs_fallback(relpath):
    FS_STATS["fallbacks"] += 1
    FS_STATS["last"] = _now_iso()
    FS_STATS["last_path"] = relpath


def _place(root, relpath, full, data):
    """Атомарно положить data в full; при настроенном File Station — руками DSM.

    Успех определяется по факту (содержимое full == data), а не по ответу
    polling'а: если задача CopyMove завершилась, но статус опоздал, второй
    записи не будет.
    """
    base = _fs_base(root)
    if base is not None:
        name = os.path.basename(relpath)
        staging = os.path.join(root, STAGING_DIR)
        os.makedirs(staging, exist_ok=True)
        _chown_quiet(staging)
        staged = os.path.join(staging, name)
        with open(staged, "wb") as f:
            f.write(data)
        _chown_quiet(staged)
        rel_dir = os.path.dirname(relpath)
        dest_fs = base + ("/" + rel_dir.replace(os.sep, "/") if rel_dir else "")
        try:
            _FS.move_into(f"{base}/{STAGING_DIR}/{name}", dest_fs)
        except Exception as e:                       # сеть/DSM — запись не роняем
            print(f"fs-move: {e}", flush=True)
        if _read_hash(full) == file_hash(data):
            return
        if os.path.exists(staged):                   # FS не сработал — локально
            print(f"fs-move не сработал для {relpath} — локальный os.replace "
                  "(в зеркала уедет после рестарта Drive)", flush=True)
            _fs_fallback(relpath)
            os.replace(staged, full)
            _chown_quiet(full)
            return
        print(f"fs-move: staged исчез без результата ({relpath}), "
              "пишу заново локально", flush=True)
        _fs_fallback(relpath)
    tmp = full + ".hub-api-tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, full)
    _chown_quiet(full)


def _remove(root, relpath, full):
    """Удалить full; при настроенном File Station — руками DSM (событие в синк)."""
    base = _fs_base(root)
    if base is not None:
        try:
            if _FS.delete(base + "/" + relpath.replace(os.sep, "/")) \
                    and not os.path.exists(full):
                return
        except Exception as e:
            print(f"fs-delete: {e}", flush=True)
        print(f"fs-delete не сработал для {relpath} — локальный os.remove "
              "(зеркала узнают после рестарта Drive)", flush=True)
        _fs_fallback(relpath)
    os.remove(full)

# Что разрешено читать/писать через API. Расширять по мере появления
# редактируемых страниц (см. план Personal Hub, фаза «редактирование»).
WHITELIST = [
    re.compile(r"^travel-planner/trips/[^/]+/3_[^/]+\.md$"),   # Stage 3: теги/комментарии POI
    re.compile(r"^travel-planner/trips/[^/]+/4_[^/]+\.md$"),   # Stage 4: варианты
    # Stage 5/6: отметки подготовки («- [x] Выкупить билеты») из навигационного
    # слоя экспорта. Пишется ТОЛЬКО символ в скобках, остальная строка та же;
    # цель выбирается по содержимому (prep_sync.resolve_plan_md), а не по имени.
    re.compile(r"^travel-planner/trips/[^/]+/5_[^/]+\.md$"),   # Stage 5: план
    re.compile(r"^travel-planner/trips/[^/]+/6_[^/]+\.md$"),   # Stage 6: финал
]

# Живое состояние раздела «Здоровье» (мастер — на Synology, не деплоится с Mac).
# labs.json — главный файл анализов: при включённом ИИ его пишет только скилл health-labs (intake.py); страница
# пишет его ТОЛЬКО при ai_mode: off (_hub/settings.json) и только ручные точки source=manual (health_labs_manual_save:
# 403 при on, 400 при попытке тронуть точки скилла; правила — labs_rules.py скилла). biomarkers-info.json и reports/*.md — в HEALTH_WHITELIST
# отдельно: их правит и скилл, и страница (редактор справки маркера, «Сохранить отчёт»), форма — модули скилла.
#
# Список ЯВНЫЙ и отдаётся в /api/health как health_files: страница и deploy.zsh
# по нему видят, какие файлы умеет ИМЕННО ЭТОТ сайдкар. Без такого признака
# рассинхрон версий (страница новее server.py на NAS) снаружи неотличим от
# «нет прав»: и то и другое — 403. Так и вышло 2026-07-17 со studies.json.
HEALTH_FILES = ("meds", "vaccinations", "vitals", "studies", "anamnesis", "labs")
HEALTH_WHITELIST = [
    re.compile(r"^(" + "|".join(HEALTH_FILES) + r")\.json$"),
    # Справка маркера и отчёты .md: пишет и страница (редактор справки, «Сохранить отчёт»), и скилл health-labs.
    # Правила — модули скилла, смонтированные рядом с server.py (validate_labs_info.py / validate_report.py).
    re.compile(r"^biomarkers-info\.json$"),
    re.compile(r"^reports/\d{4}-\d{2}-\d{2}-[a-zа-яё0-9-]+\.md$"),
]
# POST /api/hd/upload: файл исследования → Health/studies/. Тело — base64 (×4/3), поэтому отдельный лимит
# по образцу IE_IMPORT_MAX_BYTES; общий MAX_BYTES (8 МБ) не трогаем.
HD_UPLOAD_MAX_BYTES = 20 * 1024 * 1024               # сам файл
HD_UPLOAD_BODY_MAX = 28 * 1024 * 1024                # тело запроса: 20 МБ → base64 ≈ 26,7 МБ + JSON
HD_HEIC_BRANDS = (b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1")
HD_STUDIES_DIR = "studies"

# Живое состояние раздела «Еда». Лежит в ТОМ ЖЕ томе, что travel/games, но зоной
# отделено: у этих файлов есть схема, и пускать их через безсхемную зону /api/*
# значило бы разрешить странице записать нечитаемый JSON.
#
# Список явный по той же причине, что и HEALTH_FILES: страница сверяет свой
# NEED_FILES с food_files из /api/health и отличает «сайдкар старый» от «нет прав».
#
# inbox/*.md сюда НЕ входит: рецепты туда кладёт человек, страница их
# только читает листингом.
FOOD_FILES = ("products", "recipes", "shopping")
# Рецепты — ПО ФАЙЛУ НА РЕЦЕПТ (2026-07-20). Причины, по которым общий
# recipes.json оказался хуже:
#   · добавление рецепта = положить файл, без импорта и слияния;
#   · правки разных рецептов не сталкиваются (общий файл давал 409 на каждую
#     параллельную правку — вдвоём это ежедневно);
#   · один файл от проекта Claude.ai ложится 1:1, без переупаковки.
# Имя файла = id рецепта, поэтому оно и есть ключ: два файла с одним именем
# невозможны физически.
RECIPE_RE = re.compile(r"^recipes/[a-z0-9][a-z0-9-]*\.json$")
FOOD_WHITELIST = [
    re.compile(r"^(products|shopping)\.json$"),
    RECIPE_RE,
]
# Что разрешено УДАЛЯТЬ. Список НАМЕРЕННО уже, чем на запись, и это не
# перестраховка: рецепт — отдельный файл, его удаление обратимо копией в
# .versions/, а products.json и shopping.json — живое состояние раздела, которое
# накапливалось месяцами. Кнопки, стирающей их одним запросом, в вебе быть не
# должно, даже если страница такую никогда не нарисует.
FOOD_DELETABLE = [RECIPE_RE]

# Раздел «Игры» (gaming-user@1): оверлей человеческих полей Gaming/user-state.json — состояние, оценка, заметка,
# пороги цены, nsuid, обложка. Единственный писатель файла — сайт (эта зона); скилл game-advisor его читает,
# taste-profile.yaml и watchlist.yaml остаются за скиллом. Зона с паролем с любого IP (Caddy @api_trusted исключает /api/gm/*).
GAMING_FILES = ("user-state",)
GAMING_WHITELIST = [re.compile(r"^Gaming/user-state\.json$")]
GAMING_SCHEMA = "gaming-user@1"
GAMING_TITLE_MAX, GAMING_NOTE_MAX, GAMING_URL_MAX = 200, 500, 400
GAMING_ITEM_KEYS = frozenset({"title", "platform", "state", "rating", "progress", "note", "hours", "price_target_usd", "discount_target_pct",
                              "nsuid_us", "steam_appid", "eshop_url", "cover_url", "store_title", "cover_tried", "deleted",
                              "updated", "added", "demo"})   # новое поле — и сюда, и в запись «все поля» test_write_api.py

# Зона ЗАДАЧ САЙТА: файлы, которые пишет не страница, а hub-notify — по расписанию (цены US eShop,
# макросрез без LLM, журнал прогонов) и по кнопкам вьюера (сборка и «Сохранить» снапшота, журнал решений,
# типы бумаг, реестр сплитов, веса сценариев и сроки стресса, пересчёт стресса). Только изнутри
# docker-сети: запрос через Caddy несёт X-Forwarded-For и получает 403 — ни страница, ни
# внешний клиент сюда не пишут, даже с доверенного IP.
#   · перезапись — с base_hash и копией в .versions/ (любая прошлая версия восстанавливается из копии);
#   · журнал _jobs/log-ГГГГ-ММ.jsonl — только дописывание строки (/api/job/append),
#     без копий: прошлые строки не меняются.
# Выгрузка CSV ZenMoney (hub-notify zm_csv.py, этап «Деньги» 3.6): входящая выгрузка и отчёты, последняя записанная
# выгрузка, вспомогательные файлы пересчёта (aux/, в том числе кэш курсов ЦБ) и история итогов, которую пишет только
# apply (audit_history.apply_spending/apply_trip). Выгрузку в incoming/ кладёт hub-api (/api/zm/csv); подробно — docs/zenmoney/csv-site.md.
ZM_ID = r"\d{4}-\d{2}-\d{2}-[0-9a-f]{8}"
ZM_WHITELIST = [
    re.compile(rf"^ZenMoney/csv/incoming/{ZM_ID}\.csv$"),
    re.compile(rf"^ZenMoney/csv/reports/{ZM_ID}(-runs)?\.json$"),
    re.compile(r"^ZenMoney/csv/last\.csv$"),
    re.compile(r"^ZenMoney/csv/aux/[a-z0-9-]+\.json$"),
    re.compile(r"^ZenMoney/audit/(spending|trips|facts|spending-rules|site-audit)\.json$"),
]
ZM_REQUIRED = ("date", "categoryName", "payee", "comment", "outcomeAccountName", "outcome", "outcomeCurrencyShortTitle",
               "incomeAccountName", "income", "incomeCurrencyShortTitle", "createdDate", "changedDate")   # как zm_csv.REQUIRED_COLUMNS
ZM_AUX = ("accounts.json", "category-flags.json", "trip-ids.json")
ZM_ID_RE = re.compile(rf"^{ZM_ID}$")
# поля тела, которые hub-api пробрасывает в hub-notify по маршрутам правки (остальные отбрасываются); значения — типы
ZM_PROXY_FIELDS = {
    "/internal/zm-csv-report": {},
    "/internal/zm-csv-apply": {"confirm": (bool,)},
    "/internal/zm-stmt-report": {},
    "/internal/zm-rule": {"month": (str,), "date": (str,), "account": (str,), "amount": (int, float), "payee": (str,),
                          "note": (str,), "remove": (bool,), "rule_id": (str,)},
    "/internal/zm-trip": {"name": (str,), "start": (str,), "end": (str,)},
}

JOB_WHITELIST = [
    re.compile(r"^Gaming/eshop-prices\.json$"),
    re.compile(r"^macro-snapshots/auto/ru-\d{4}-\d{2}-\d{2}\.(md|json)$"),
    # снапшот, собранный с вьюера (hub-notify pf_build.py, пробный режим) — только пробная папка;
    # рабочая Portfolio/snapshots/ отсюда недоступна; суффикс -ЧЧММ-bal|trades — несколько сборок на дату
    re.compile(r"^Portfolio/snapshots/auto/(portfolio|build-summary)-\d{4}-\d{2}-\d{2}(-\d{4}-(bal|trades))?\.json$"),
    # сайт сохраняет снапшот в рабочую папку (pf_build.SAVE_DIR, 29.10): прежняя версия — в .versions/
    re.compile(r"^Portfolio/snapshots/portfolio-\d{4}-\d{2}-\d{2}\.json$"),
    # журнал решений (decision_journal_update.py): hub-notify пересобирает его при «Сохранить» (pf_build.publish_journal);
    # только производные файлы — ручные входы папки (incidents/refusals/theses.yaml) сайт не пишет
    re.compile(r"^Portfolio/decision-journal/(inputs|baselines|journal)\.json$"),
    re.compile(r"^Portfolio/decision-journal/report-\d{4}-\d{2}-\d{2}\.md$"),
    # справочник типов бумаг с Мосбиржи (security_types.py): сборка на сайте обновляет его в томе /data
    # hub-notify и выкладывает сюда при «Сохранить» (pf_build.save) — скилл на Маке в ISS не ходит, читает файл
    re.compile(r"^Portfolio/security-types\.json$"),
    # справочник бумаг (security-attrs@1): при «Сохранить» снапшота сайт добавляет ТОЛЬКО новые ключи держаний
    # (pf_build.save_attrs → security_attrs.add_missing); существующие записи правит лишь скилл (security_attrs.py set)
    re.compile(r"^Portfolio/security-attrs\.json$"),
    # реестр сплитов (known-splits@1): подтверждение/отклонение сплита со страницы (hub-notify stress_job.post_splits)
    re.compile(r"^Portfolio/known-splits\.json$"),
    # решение владельца с карточки бумаги (decision@1, author owner; hub-notify decision_job): файл-запись на минуту,
    # только новый — save_file(base_hash=null) при существующем отвечает 409; путь = {дата}T{ЧЧММ}-{KEY}
    re.compile(r"^Portfolio/decisions/\d{4}-\d{2}-\d{2}T\d{4}-[A-Z0-9.-]+\.json$"),
    # условия-напоминания владельца (conditions@2, source owner; hub-notify condition_job): add / withdraw с base_hash,
    # тот же файл правит скилл (apply_condition.py) — гонку ловит 409; новая запись — .versions/
    re.compile(r"^Portfolio/conditions\.yaml$"),
    # веса сценариев стресса, заданные на сайте по осям матрицы (stress-weights@1; stress_job.post_weights);
    # саму матрицу scenarios/scenario-*.yaml сайт не пишет
    re.compile(r"^scenarios/stress-weights-[a-z0-9-]+\.json$"),
    # сроки прогонов, заданные на сайте (horizons@1; stress_job.post_terms): единственное место сроков прогнозов и стресса
    re.compile(r"^scenarios/horizons\.json$"),
    # пересчёт чисел стресса без модели (stress_recalc.py): один текущий файл на исходный стресс, рядом со стрессом скилла
    re.compile(r"^Portfolio/stress/auto/recalc-stress-[a-z0-9-]+\.yaml$"),
    # дневной ряд цен закрытия держимых бумаг и курсов ЦБ (prices_job.py, только вперёд; одна строка на торговую дату);
    # единственный писатель — hub-notify, файл на год: ~100 бумаг × 250 дней ≈ 2 МБ, лимит тела — MAX_BYTES (8 МБ)
    re.compile(r"^Portfolio/prices/daily-\d{4}\.jsonl$"),
] + ZM_WHITELIST
JOB_LOG_RE = re.compile(r"^_jobs/log-\d{4}-\d{2}\.jsonl$")
NOTIFY_URL = os.environ.get("HUB_API_NOTIFY_URL", "http://hub-notify:8001").rstrip("/")


ZM_CSV_MAX_BYTES = 16 * 1024 * 1024      # тело запроса, как у импорта IE
# Сверка выписки банка (hub-notify zm_stmt.py, задача 3.8): временная зона — файл живёт до ответа отчёта (или часа), отчёт не хранится.
ZM_STMT_DIR = "ZenMoney/csv/stmt-incoming"
ZM_STMT_MAX_BYTES = 11 * 1024 * 1024     # тело запроса (base64): файл ≈ 8 МБ; выписка банка — единицы МБ
ZM_STMT_TTL = 3600                       # секунд: брошенный файл (отчёт не запрошен) стирается при следующем обращении


def zm_stmt_sniff(raw):
    """Тип выписки по содержимому → "xlsx" | "csv"; ValueError с текстом, если это не выписка по форме (PDF сайт не разбирает)."""
    import io as _io
    import zipfile as _zip
    if not raw:
        raise ValueError("файл пустой")
    if raw[:5] == b"%PDF-":
        raise ValueError("PDF на сайте не разбирается — поддержаны CSV Райффайзенбанка и XLSX BOG")
    if raw[:4] == b"PK\x03\x04":
        try:
            with _zip.ZipFile(_io.BytesIO(raw)) as z:
                if "xl/workbook.xml" in z.namelist():
                    return "xlsx"
        except _zip.BadZipFile:
            pass
        raise ValueError("архив, но не книга Excel (xlsx)")
    if b"\0" in raw[:4096]:
        raise ValueError("двоичный файл: нужен CSV Райффайзенбанка или XLSX BOG")
    for enc in ("utf-8-sig", "cp1251"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            text = None
    first = (text or "").lstrip().split("\n", 1)[0]
    if text is None or "\n" not in text.strip() or not any(d in first for d in (";", ",", "\t")):
        raise ValueError("не похоже на выписку: нужен CSV Райффайзенбанка или XLSX BOG с шапкой колонок")
    return "csv"


def zm_stmt_sweep(root, now_ts=None, ttl=ZM_STMT_TTL, only=None):
    """Стереть файлы выписок: `only` — один id (после отчёта), иначе всё старше ttl. Ошибки удаления не роняют запрос."""
    d = os.path.join(root, ZM_STMT_DIR)
    try:
        names = os.listdir(d)
    except OSError:
        return 0
    now_ts = time.time() if now_ts is None else now_ts
    n = 0
    for name in names:
        stem = name.rsplit(".", 1)[0]
        if not ZM_ID_RE.match(stem):
            continue
        p = os.path.join(d, name)
        try:
            if (only is not None and stem == only) or (only is None and now_ts - os.path.getmtime(p) > ttl):
                os.remove(p)
                n += 1
        except OSError:
            pass
    return n


def zm_csv_check(raw):
    """Форма выгрузки ZenMoney → {rows, first, last}; ValueError с текстом. Колонки — как zm_csv.parse_csv."""
    import csv as _csv
    import io as _io
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("файл не UTF-8") from None
    rd = _csv.DictReader(_io.StringIO(text, newline=""), delimiter=";")
    missing = [c for c in ZM_REQUIRED if c not in (rd.fieldnames or [])]
    if missing:
        raise ValueError("в выгрузке нет колонок: " + ", ".join(missing))
    n, first, last = 0, None, None
    for i, r in enumerate(rd, start=2):
        d = r.get("date") or ""
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
            raise ValueError(f"строка {i}: дата «{d}» не ГГГГ-ММ-ДД")
        n += 1
        first = d if first is None or d < first else first
        last = d if last is None or d > last else last
    if not n:
        raise ValueError("в выгрузке нет операций")
    return {"rows": n, "first": first, "last": last}


def _zm_reports(root):
    """[(id, отчёт)] из ZenMoney/csv/reports/<id>.json; битые пропускаются."""
    d = os.path.join(root, "ZenMoney/csv/reports")
    out = []
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    for n in names:
        if ZM_ID_RE.match(n[:-5]) and n.endswith(".json"):
            try:
                with open(os.path.join(d, n), encoding="utf-8") as f:
                    out.append((n[:-5], json.load(f)))
            except (OSError, ValueError):
                pass
    return out


def zm_drop_applied(root):
    """Записанные выгрузки (в отчёте applied_at) из incoming/ стираем: hub-notify удалять не умеет (/api/job/save)."""
    for id_, rep in _zm_reports(root):
        if isinstance(rep, dict) and rep.get("applied_at"):
            try:
                os.remove(os.path.join(root, f"ZenMoney/csv/incoming/{id_}.csv"))
            except OSError:
                pass


def zm_csv_state(root):
    """GET /api/zm/csv-state → {last: {name, sha256, written_at}|null, incoming: [id], aux_ok}."""
    applied = {i: r for i, r in _zm_reports(root) if isinstance(r, dict) and r.get("applied_at")}
    last, lp = None, os.path.join(root, "ZenMoney/csv/last.csv")
    if os.path.isfile(lp):
        with open(lp, "rb") as f:
            sha = file_hash(f.read())
        name = next((i for i, r in sorted(applied.items(), key=lambda kv: kv[1]["applied_at"], reverse=True)
                     if r.get("sha256") == sha), None)
        rep = applied.get(name) or {}
        last = {"name": name, "sha256": sha, "rows": rep.get("rows"), "last_op": rep.get("last"),
                "written_at": applied[name]["applied_at"] if name else
                datetime.fromtimestamp(os.path.getmtime(lp), timezone(timedelta(hours=3))).strftime("%Y-%m-%dT%H:%M:%S+03:00")}
    try:
        inc = sorted(n[:-4] for n in os.listdir(os.path.join(root, "ZenMoney/csv/incoming"))
                     if n.endswith(".csv") and ZM_ID_RE.match(n[:-4]) and n[:-4] not in applied)
    except OSError:
        inc = []
    aux_ok = all(os.path.isfile(os.path.join(root, "ZenMoney/csv/aux", n)) for n in ZM_AUX)
    return {"last": last, "incoming": inc, "aux_ok": aux_ok}


def _api_code():
    """Отпечаток этого файла при старте процесса: по нему deploy.zsh видит, что hub-api работает на старом
    server.py (случай 2026-11-07: файл сроков был в списке разрешённых путей на диске, но не в процессе)."""
    try:
        with open(__file__, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except OSError:
        return None


API_CODE = _api_code()


def _notify_health():
    """{"version", "code"} hub-notify или None — для /api/health (deploy.zsh видит забытый restart)."""
    try:
        with urllib.request.urlopen(NOTIFY_URL + "/internal/health", timeout=1) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError:
        return {"version": None, "code": None}      # отвечает, но ручки нет — hub-notify старее 1.7.0
    except (OSError, ValueError):
        return None

_write_lock = threading.Lock()


def norm_path(raw):
    """Нормализует относительный путь; None, если путь опасен или пуст."""
    if not raw or "\\" in raw or "\x00" in raw:
        return None
    p = raw.strip().lstrip("/")
    norm = os.path.normpath(p)
    if norm in (".", "") or norm.startswith("..") or os.path.isabs(norm):
        return None
    return norm.replace(os.sep, "/")


def is_allowed(relpath, whitelist=None):
    return any(rx.match(relpath) for rx in (WHITELIST if whitelist is None else whitelist))


# ─────────────────── валидация health-схем ───────────────────
# Контракт «страница ↔ файл ↔ скилл». Проверяем ровно то, без чего файл
# перестаёт парситься потребителями; содержательные поля не трогаем —
# их наполняют человек (user-поля) и скилл (ref-поля).
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

HEALTH_SCHEMAS = {
    "meds.json": "health-meds@1",
    "vaccinations.json": "health-vaccinations@1",
    "vitals.json": "health-vitals@1",
    "labs.json": "health-labs@1",           # анализы: главный файл; пишет скилл, а при ai_mode off — страница (ручные точки)
    "studies.json": "health-studies@1",     # МРТ/УЗИ/ЭКГ: заключение текстом
    "anamnesis.json": "health-anamnesis@1",  # семейный анамнез (контракт §11)
}

_AN_RELATIONS = ("mother", "father", "brother", "sister", "son", "daughter",
                 "grandmother", "grandfather", "great-grandmother",
                 "great-grandfather", "aunt", "uncle", "cousin")
_AN_GROUPS = ("cardio", "lipid", "metabolic", "onco", "kidney", "endocrine",
              "digestive", "neuro", "other")


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _validate_anamnesis(doc):
    if "self" in doc:
        _validate_self(doc["self"])
    fam = doc.get("family")
    if not isinstance(fam, list):
        raise ValueError("family — список")
    seen = set()
    for i, f in enumerate(fam):
        if not isinstance(f, dict):
            raise ValueError(f"family[{i}] — объект")
        fid = f.get("id")
        if not isinstance(fid, str) or not fid:
            raise ValueError(f"family[{i}].id — непустая строка")
        if fid in seen:
            raise ValueError(f"family: повтор id {fid!r}")
        seen.add(fid)
        if f.get("relation") not in _AN_RELATIONS:
            raise ValueError(f"family[{i}].relation — из перечня родства")
        if f.get("side") not in ("maternal", "paternal", None):
            raise ValueError(f"family[{i}].side — maternal/paternal/null")
        for k in ("born", "died"):
            if f.get(k) is not None and not _is_int(f.get(k)):
                raise ValueError(f"family[{i}].{k} — год или null")
        if "unknown" in f and not isinstance(f["unknown"], bool):
            raise ValueError(f"family[{i}].unknown — true/false")
        conds = f.get("conditions", [])
        if not isinstance(conds, list):
            raise ValueError(f"family[{i}].conditions — список")
        for j, c in enumerate(conds):
            at = f"family[{i}].conditions[{j}]"
            if not isinstance(c, dict):
                raise ValueError(f"{at} — объект")
            if not isinstance(c.get("name"), str) or not c["name"].strip():
                raise ValueError(f"{at}.name — непустая строка")
            if c.get("group") not in _AN_GROUPS:
                raise ValueError(f"{at}.group — из перечня групп")
            if c.get("kind") not in ("disease", "surgery"):
                raise ValueError(f"{at}.kind — disease/surgery")
            oa = c.get("onset_age")
            if oa is not None and not (_is_int(oa) and 0 <= oa <= 120):
                raise ValueError(f"{at}.onset_age — целое 0–120 или null")
            if c.get("certainty") not in ("known", "hearsay", "guess"):
                raise ValueError(f"{at}.certainty — known/hearsay/guess")


_AN_DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


def _validate_self(sf):
    if not isinstance(sf, dict):
        raise ValueError("self — объект")
    if "allergies_checked" in sf and not isinstance(sf["allergies_checked"], bool):
        raise ValueError("self.allergies_checked — true/false")
    alg = sf.get("allergies", [])
    if not isinstance(alg, list):
        raise ValueError("self.allergies — список")
    seen = set()
    for i, a in enumerate(alg):
        at = f"self.allergies[{i}]"
        if not isinstance(a, dict):
            raise ValueError(f"{at} — объект")
        aid = a.get("id")
        if not isinstance(aid, str) or not aid:
            raise ValueError(f"{at}.id — непустая строка")
        if aid in seen:
            raise ValueError(f"self.allergies: повтор id {aid!r}")
        seen.add(aid)
        if not isinstance(a.get("substance"), str) or not a["substance"].strip():
            raise ValueError(f"{at}.substance — непустая строка")
        if a.get("kind") not in ("drug", "food", "insect", "other"):
            raise ValueError(f"{at}.kind — drug/food/insect/other")
        if a.get("severity") not in ("mild", "moderate", "severe", "anaphylaxis"):
            raise ValueError(f"{at}.severity — mild/moderate/severe/anaphylaxis")
        if a.get("certainty") not in ("known", "hearsay", "guess"):
            raise ValueError(f"{at}.certainty — known/hearsay/guess")
        if a.get("since") is not None and not _is_int(a.get("since")):
            raise ValueError(f"{at}.since — год или null")
    hist = sf.get("history", [])
    if not isinstance(hist, list):
        raise ValueError("self.history — список")
    seen = set()
    for i, h in enumerate(hist):
        at = f"self.history[{i}]"
        if not isinstance(h, dict):
            raise ValueError(f"{at} — объект")
        hid = h.get("id")
        if not isinstance(hid, str) or not hid:
            raise ValueError(f"{at}.id — непустая строка")
        if hid in seen:
            raise ValueError(f"self.history: повтор id {hid!r}")
        seen.add(hid)
        if not isinstance(h.get("name"), str) or not h["name"].strip():
            raise ValueError(f"{at}.name — непустая строка")
        if h.get("kind") not in ("chronic", "illness", "surgery", "injury", "hospitalization"):
            raise ValueError(f"{at}.kind — chronic/illness/surgery/injury/hospitalization")
        if h.get("group") not in _AN_GROUPS:
            raise ValueError(f"{at}.group — из перечня групп")
        if h.get("status") not in ("active", "resolved", "remission", "unknown"):
            raise ValueError(f"{at}.status — active/resolved/remission/unknown")
        if h.get("certainty") not in ("known", "hearsay", "guess"):
            raise ValueError(f"{at}.certainty — known/hearsay/guess")
        st, en = h.get("start"), h.get("end")
        if not isinstance(st, str) or not _AN_DATE_RE.match(st):
            raise ValueError(f"{at}.start — ГГГГ, ГГГГ-ММ или ГГГГ-ММ-ДД")
        if en is not None:
            if not isinstance(en, str) or not _AN_DATE_RE.match(en):
                raise ValueError(f"{at}.end — ГГГГ, ГГГГ-ММ, ГГГГ-ММ-ДД или null")
            n = min(len(st), len(en))
            if en[:n] < st[:n]:
                raise ValueError(f"{at}: конец раньше начала")
        sd = h.get("study")
        if sd is not None and not isinstance(sd, str):
            raise ValueError(f"{at}.study — строка или null")
        for wk in ("window_before", "window_after"):
            if wk in h:
                wv = h[wk]
                if isinstance(wv, bool) or not isinstance(wv, int) or not 0 <= wv <= 365:
                    raise ValueError(f"{at}.{wk} — целое 0–365 или без поля")
        if "markers" in h:
            mk = h["markers"]
            if not isinstance(mk, list) or len(mk) > 30:
                raise ValueError(f"{at}.markers — список не более 30 id показателей или без поля")
            for m in mk:
                if not isinstance(m, str) or not m or len(m) > 80:
                    raise ValueError(f"{at}.markers — непустые строки до 80 символов")
            if len(set(mk)) != len(mk):
                raise ValueError(f"{at}.markers — повтор id")


def _validate_bp(doc):
    bp = doc.get("bp")
    if bp is None:
        return
    if not isinstance(bp, list):
        raise ValueError("bp — список")
    seen = set()
    for i, b in enumerate(bp):
        if not isinstance(b, dict):
            raise ValueError(f"bp[{i}] — объект")
        bid = b.get("id")
        if not isinstance(bid, str) or not bid:
            raise ValueError(f"bp[{i}].id — непустая строка")
        if bid in seen:
            raise ValueError(f"bp: повтор id {bid!r}")
        seen.add(bid)
        if not isinstance(b.get("date"), str) or not b["date"]:
            raise ValueError(f"bp[{i}].date — строка ГГГГ-ММ-ДД")
        if b.get("time") is not None and not isinstance(b.get("time"), str):
            raise ValueError(f"bp[{i}].time — строка или null")
        sys_, dia = b.get("sys"), b.get("dia")
        if not _is_int(sys_) or not 60 <= sys_ <= 260:
            raise ValueError(f"bp[{i}].sys — целое 60–260")
        if not _is_int(dia) or not 30 <= dia <= 160:
            raise ValueError(f"bp[{i}].dia — целое 30–160")
        if sys_ <= dia:
            raise ValueError(f"bp[{i}]: верхнее должно быть больше нижнего")
        p = b.get("pulse")
        if p is not None and not (_is_int(p) and 25 <= p <= 250):
            raise ValueError(f"bp[{i}].pulse — целое 25–250 или null")


def validate_health(relpath, content):
    """Проверяет структуру health-файла. ValueError с понятным текстом, если битый."""
    name = os.path.basename(relpath)
    if relpath.startswith("reports/") and name.endswith(".md"):
        vr, _ = _health_skill_mods()
        if vr is None:
            raise ValueError("модуль validate_report.py не смонтирован в hub-api")
        errors, _w, _m = vr.check(content, _health_labs(), name)
        if errors:
            raise ValueError("отчёт не прошёл проверку формата: " + "; ".join(errors[:5]))
        return
    if name == "biomarkers-info.json":
        _, vl = _health_skill_mods()
        if vl is None:
            raise ValueError("модуль validate_labs_info.py не смонтирован в hub-api")
        try:
            doc = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"не разбирается как JSON: {e}")
        bad = [i["message"] for i in vl.validate_info(doc) if i["severity"] == "blocking"]
        if bad:
            raise ValueError("справка биомаркеров: " + "; ".join(bad[:5]))
        return
    expected = HEALTH_SCHEMAS.get(name)
    if expected is None:
        return
    try:
        doc = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"не разбирается как JSON: {e}")
    if not isinstance(doc, dict):
        raise ValueError("корень должен быть объектом")
    if doc.get("schema") != expected:
        raise ValueError(f"schema должна быть {expected!r}, получено {doc.get('schema')!r}")

    if name == "vitals.json":
        h = doc.get("height_cm")
        if h is not None and not isinstance(h, (int, float)):
            raise ValueError("height_cm — число или null")
        weight = doc.get("weight")
        if not isinstance(weight, list):
            raise ValueError("weight — список")
        for i, w in enumerate(weight):
            if not isinstance(w, dict):
                raise ValueError(f"weight[{i}] — объект")
            if not isinstance(w.get("kg"), (int, float)):
                raise ValueError(f"weight[{i}].kg — число")
            if not isinstance(w.get("date"), str):
                raise ValueError(f"weight[{i}].date — строка")
        _validate_bp(doc)
        return

    if name == "anamnesis.json":
        _validate_anamnesis(doc)
        return

    if name == "labs.json":
        # содержательные правила (точки, референсы, ручные/скилловые) — labs_rules.check_manual_edit при записи;
        # здесь — только форма, без которой страница и скилл не прочтут файл
        if not isinstance(doc.get("biomarkers"), list) or not isinstance(doc.get("categories"), list):
            raise ValueError("biomarkers и categories — списки")
        return

    key = {"meds.json": "meds", "vaccinations.json": "vaccinations",
           "studies.json": "studies"}[name]
    items = doc.get(key)
    if not isinstance(items, list):
        raise ValueError(f"{key} — список")
    seen = set()
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            raise ValueError(f"{key}[{i}] — объект")
        iid = it.get("id")
        if not isinstance(iid, str) or not iid:
            raise ValueError(f"{key}[{i}].id — непустая строка")
        if iid in seen:
            raise ValueError(f"{key}: повтор id {iid!r}")
        seen.add(iid)
    if key == "studies":
        for i, it in enumerate(items):
            if not isinstance(it.get("date"), str) or not it["date"]:
                raise ValueError(f"studies[{i}].date — непустая строка")
            if not isinstance(it.get("kind"), str) or not it["kind"].strip():
                raise ValueError(f"studies[{i}].kind — непустая строка (МРТ/УЗИ/…)")
            for f in ("area", "conclusion", "doctor", "clinic", "file", "notes"):
                if f in it and it[f] is not None and not isinstance(it[f], str):
                    raise ValueError(f"studies[{i}].{f} — строка")
    if key == "meds":
        for i, it in enumerate(items):
            if not isinstance(it.get("name"), str) or not it["name"].strip():
                raise ValueError(f"meds[{i}].name — непустая строка")
            if not isinstance(it.get("taking"), bool):
                raise ValueError(f"meds[{i}].taking — true/false")
            # Третье состояние аптечки: лекарство кончилось. Запись не удаляют —
            # она остаётся образцом для повторного добавления, страница её прячет.
            if it.get("archived") is not None and not isinstance(it.get("archived"), bool):
                raise ValueError(f"meds[{i}].archived — true/false или отсутствует")
            # Срок годности — «ГГГГ-ММ»: на упаковке дня нет. Полная дата тут не
            # «точнее», а ломает выбор месяца на странице.
            exp = it.get("expiry")
            if exp not in (None, "") and not _MONTH_RE.match(exp if isinstance(exp, str) else ""):
                raise ValueError(f"meds[{i}].expiry — «ГГГГ-ММ» или пусто")
            # Назначение (блок в списке аптечки). Пустое/отсутствующее = «считать
            # по описанию», страница раскладывает эвристикой. Здесь только тип:
            # закрытый словарь значений — смысловая проверка, она живёт в
            # validate_meds.py скилла (иначе список пришлось бы держать в трёх
            # местах и синхронизировать руками).
            grp = it.get("group")
            if grp is not None and not isinstance(grp, str):
                raise ValueError(f"meds[{i}].group — строка или отсутствует")
            aff = it.get("affects", [])
            if not isinstance(aff, list) or not all(isinstance(a, str) for a in aff):
                raise ValueError(f"meds[{i}].affects — список строк")
            # Сила влияния на биомаркер: {id: strong|moderate|weak}. Страница
            # рисует градацию чипов; смысловую сверку (ключи ⊂ affects) делает
            # validate_meds.py скилла.
            st = it.get("affects_strength")
            if st is not None:
                if not isinstance(st, dict):
                    raise ValueError(f"meds[{i}].affects_strength — объект или отсутствует")
                for k, v in st.items():
                    if v not in ("strong", "moderate", "weak"):
                        raise ValueError(
                            f"meds[{i}].affects_strength[{k!r}] — strong/moderate/weak")
            _validate_ref_meta(i, it.get("ref_meta"))


# Провенанс справки: кто заполнил поле, из какого источника и когда.
# Пишет скилл health-meds; страница блок не рисует, но сохраняет (med-save
# делает Object.assign поверх записи — чужие ключи переживают правку).
# Здесь — только структура: смысловые проверки (источник на каждый заявленный
# факт, живые ссылки affects) живут в skills/health-meds/scripts/validate_meds.py,
# которому доступен labs.json. Сайдкар отвечает лишь за то, чтобы файл остался
# разбираемым для страницы.
def _validate_ref_meta(i, rm):
    if rm is None:
        return
    if not isinstance(rm, dict):
        raise ValueError(f"meds[{i}].ref_meta — объект или отсутствует")
    if rm.get("confidence") not in (None, "high", "medium", "low"):
        raise ValueError(f"meds[{i}].ref_meta.confidence — high/medium/low")
    ff = rm.get("fields_filled", [])
    if not isinstance(ff, list) or not all(isinstance(f, str) for f in ff):
        raise ValueError(f"meds[{i}].ref_meta.fields_filled — список строк")
    src = rm.get("sources", [])
    if not isinstance(src, list) or not all(isinstance(s, dict) for s in src):
        raise ValueError(f"meds[{i}].ref_meta.sources — список объектов")


# ─────────────────── валидация схем раздела «Еда» ───────────────────
# Тот же принцип, что и у health: проверяем ТОЛЬКО то, без чего файл перестаёт
# работать у потребителей, и ничего сверх. Содержательное наполнение — дело
# человека и страницы.
#
# Что здесь СОЗНАТЕЛЬНО не проверяется:
#   * `category` — свободная строка. Новый отдел не должен ронять сохранение;
#     страница рисует незнакомое как «Прочее», а не прячет.
#   * стоп-лист блюд (морепродукты / печень / грибы) — это ВКУС, а не структура.
#     400 из-за слова «грибы» в заметке о заменах — издевательство; правило живёт
#     в генерации рецепта на стороне Claude.ai, а не в хранилище.
#   * `difficulty`, `cuisine`, `sources`, `equipment` — на разбор не влияют.
FOOD_SCHEMAS = {
    "products.json": ("food-products@1", "products"),
    "shopping.json": ("food-shopping@1", "shopping-items"),
}


def _is_num(v):
    """Число, но НЕ bool: в Python True — это int, и без этой проверки
    `"qty": true` прошло бы как количество."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _num_or_none(where, field, v):
    if v is not None and not _is_num(v):
        raise ValueError(f"{where}.{field} — число или null (получено {v!r})")


def validate_recipe_file(content):
    """Один рецепт = один файл. ValueError, если битый.

    Проверяем ровно то, без чего страница считает неверно, а не «полноту»:
    servings — делитель пересчёта порций (ноль или строка разносят NaN по
    всему списку покупок), qty — слагаемое (строка «600» при сложении
    СКЛЕИТСЯ, а не сложится).
    """
    try:
        doc = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"не разбирается как JSON: {e}")
    if not isinstance(doc, dict):
        raise ValueError("рецепт — объект, а не список")
    if doc.get("schema") != "food-recipe@1":
        raise ValueError(f"schema — «food-recipe@1» (получено {doc.get('schema')!r})")
    if not isinstance(doc.get("title"), str) or not doc["title"].strip():
        raise ValueError("title — непустая строка")
    # `id` внутри файла НЕ обязателен: имя файла — единственная идентичность
    # рецепта (упрощение 2026-07-21, чтобы копия файла не ломалась забытым id).
    # Если id всё же есть, он не должен быть мусором.
    if "id" in doc and doc["id"] is not None:
        if not isinstance(doc["id"], str) or not doc["id"].strip():
            raise ValueError("id — непустая строка или отсутствует")
    sv = doc.get("servings")
    if not _is_num(sv) or sv <= 0:
        raise ValueError(f"servings — положительное число (получено {sv!r})")
    ings = doc.get("ingredients", [])
    if not isinstance(ings, list):
        raise ValueError("ingredients — список")
    for i, g in enumerate(ings):
        if not isinstance(g, dict):
            raise ValueError(f"ingredients[{i}] — объект")
        if not isinstance(g.get("name"), str) or not g["name"].strip():
            raise ValueError(f"ingredients[{i}].name — непустая строка")
        _num_or_none(f"ingredients[{i}]", "qty", g.get("qty"))
        st = g.get("state")
        if st is not None and st not in ("cooked", "dry"):
            raise ValueError(
                f"ingredients[{i}].state — «cooked», «dry» или отсутствует "
                f"(получено {st!r}). Опечатка тихо отключит пересчёт варёного веса")
        # measure — свободный текст для показа человеку («1 стакан», «2 ст. л.»).
        # В КБЖУ и список идёт qty (STD в г/мл/шт), measure — только отображение.
        ms = g.get("measure")
        if ms is not None and not isinstance(ms, str):
            raise ValueError(f"ingredients[{i}].measure — строка или отсутствует "
                             f"(получено {ms!r}). Это показ, число сюда не кладут")
    steps = doc.get("steps", [])
    if not isinstance(steps, list):
        raise ValueError("steps — список")
    nu = doc.get("nutrition")
    if nu is not None:
        if not isinstance(nu, dict):
            raise ValueError("nutrition — объект или null")
        for k in ("kcal", "protein_g", "fat_g", "carb_g"):
            _num_or_none("nutrition", k, nu.get(k))
    _num_or_none("recipe", "finished_g", doc.get("finished_g"))
    # Оценка «понравилось» — 1..3 или её нет вовсе. Ноль и строка отклоняются
    # намеренно: карточка рисует звёзды по этому числу, и «rating»: "3" молча
    # дало бы пустую шкалу, а 0 путал бы «не понравилось» с «не пробовали»
    # (неоценённое блюдо — ОТСУТСТВИЕ поля).
    rt = doc.get("rating")
    if rt is not None and (isinstance(rt, bool) or not isinstance(rt, (int, float))
                           or rt != int(rt) or not 1 <= rt <= 3):
        raise ValueError(f"rating — целое 1..3 или отсутствует (получено {rt!r})")


def gaming_key(title):
    """Ключ игры в оверлее: название без регистра, лишних пробелов и типографики (как normName страницы)."""
    t = unicodedata.normalize("NFKC", str(title or "")).casefold()
    t = re.sub(r"[’'`´]", "", t)
    t = re.sub(r"[^\w]+", " ", t, flags=re.UNICODE)
    return " ".join(t.split())


def normalize_gaming(content):
    """Приводит оверлей игр к текущему контракту перед проверкой и записью (только сайт, /api/gm/save):
    старое state «демо» → demo true + state на-карандаш (не-интересно при оценке «не понравилось»);
    флаг demo у state «куплена» снимается. Что не разбирается — возвращается как есть (ошибку даст валидатор)."""
    try:
        doc = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return content
    items = doc.get("items") if isinstance(doc, dict) else None
    if not isinstance(items, list):
        return content
    changed = False
    for it in items:
        if not isinstance(it, dict):
            continue
        if it.get("state") == "демо":
            it["demo"] = True
            it["state"] = "не-интересно" if it.get("rating") == "не понравилось" else "на-карандаш"
            changed = True
        if it.get("state") == "куплена" and "demo" in it:
            del it["demo"]
            changed = True
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n" if changed else content


def validate_gaming(relpath, content):
    """Схема gaming-user@1 оверлея игр. ValueError с понятным текстом — файл не пишется."""
    try:
        doc = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"не разбирается как JSON: {e}")
    if not isinstance(doc, dict):
        raise ValueError("корень должен быть объектом")
    if doc.get("schema") != GAMING_SCHEMA:
        raise ValueError(f"schema должна быть {GAMING_SCHEMA!r}, получено {doc.get('schema')!r}")
    if not isinstance(doc.get("updated"), str) or not _PLAN_DATE_RE.match(doc["updated"][:10]):
        raise ValueError("updated — дата «ГГГГ-ММ-ДД» (или время)")
    items = doc.get("items")
    if not isinstance(items, list):
        raise ValueError("items — список")
    states, platforms, ratings = _cl_words("game_state"), _cl_words("game_platform"), _cl_words("game_rating")
    progresses = _cl_words("game_progress")
    seen = set()
    for i, it in enumerate(items):
        p = f"items[{i}]"
        if not isinstance(it, dict):
            raise ValueError(f"{p} — объект")
        title = it.get("title")
        if not isinstance(title, str) or not title.strip() or len(title) > GAMING_TITLE_MAX:
            raise ValueError(f"{p}.title — непустая строка до {GAMING_TITLE_MAX} знаков")
        key = gaming_key(title)
        if key in seen:
            raise ValueError(f"{p}.title: игра «{title}» в оверлее дважды (ключ — название без регистра)")
        seen.add(key)
        if it.get("state") not in states:
            raise ValueError(f"{p}.state — одно из {', '.join(states)}")
        if it.get("platform") is not None and it["platform"] not in platforms:
            raise ValueError(f"{p}.platform — одно из {', '.join(platforms)} или null")
        if it.get("rating") is not None and it["rating"] not in ratings:
            raise ValueError(f"{p}.rating — одно из {', '.join(ratings)} или null")
        if it.get("progress") is not None:
            if it["progress"] not in progresses:
                raise ValueError(f"{p}.progress — одно из {', '.join(progresses)} или null")
            if it.get("state") not in ("куплена", "демо") and it.get("demo") is not True:
                raise ValueError(f"{p}.progress задаётся только у state куплена или у игры с demo true (у «{it.get('state')}» — null)")
        note = it.get("note")
        if note is not None and not (isinstance(note, str) and len(note) <= GAMING_NOTE_MAX):
            raise ValueError(f"{p}.note — строка до {GAMING_NOTE_MAX} знаков или null")
        tgt = it.get("price_target_usd")
        if tgt is not None and not (isinstance(tgt, (int, float)) and not isinstance(tgt, bool) and 0 < tgt < 1000):
            raise ValueError(f"{p}.price_target_usd — число 0–1000 или null")
        pct = it.get("discount_target_pct")
        if pct is not None and not (isinstance(pct, int) and not isinstance(pct, bool) and 1 <= pct <= 99):
            raise ValueError(f"{p}.discount_target_pct — целое 1–99 или null")
        ns = it.get("nsuid_us")
        if ns is not None and not (isinstance(ns, str) and ns.isdigit() and 8 <= len(ns) <= 20):
            raise ValueError(f"{p}.nsuid_us — строка цифр или null")
        sa = it.get("steam_appid")
        if sa is not None and not (isinstance(sa, str) and sa.isdigit() and 1 <= len(sa) <= 10):
            raise ValueError(f"{p}.steam_appid — строка цифр (id приложения Steam) или null")
        ct = it.get("cover_tried")
        if ct is not None and not (isinstance(ct, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", ct)):
            raise ValueError(f"{p}.cover_tried — дата ГГГГ-ММ-ДД последней неудачной попытки подбора обложки или null")
        for k in ("eshop_url", "cover_url"):
            v = it.get(k)
            if v is not None and not (isinstance(v, str) and v.startswith("https://") and len(v) <= GAMING_URL_MAX):
                raise ValueError(f"{p}.{k} — https-ссылка до {GAMING_URL_MAX} знаков или null")
        hrs = it.get("hours")
        if hrs is not None and not (isinstance(hrs, (int, float)) and not isinstance(hrs, bool) and 0 <= hrs < 100000):
            raise ValueError(f"{p}.hours — число часов ≥ 0 или null")
        if "deleted" in it and not isinstance(it["deleted"], bool):
            raise ValueError(f"{p}.deleted — true/false")
        if "demo" in it:
            if not isinstance(it["demo"], bool):
                raise ValueError(f"{p}.demo — true/false")
            if it["demo"] and it.get("state") == "куплена":
                raise ValueError(f"{p}.demo — флаг «играл в демо» допустим только у некупленной игры")
        if "updated" in it and not (isinstance(it["updated"], str) and _PLAN_DATE_RE.match(it["updated"][:10])):
            raise ValueError(f"{p}.updated — дата «ГГГГ-ММ-ДД» (или время)")
        unknown = set(it) - GAMING_ITEM_KEYS
        if unknown:
            raise ValueError(f"{p}: неизвестные поля {', '.join(sorted(unknown))}")


def validate_food(relpath, content):
    """Проверяет структуру файла раздела «Еда». ValueError, если битый."""
    if RECIPE_RE.match(relpath):
        validate_recipe_file(content)
        # Идентичность рецепта — ИМЯ ФАЙЛА, оно же путь записи: файл с чужим id
        # внутри пишется в СВОЙ путь и оригинал не перетирает. Поэтому реджект
        # по расхождению id с именем отменён (2026-07-23) в пользу мягкой
        # политики: страница откроет рецепт по имени и покажет предупреждение
        # (док food/instruction.md), а не отклонит. По новому формату id в
        # файле нет вовсе — сам сайдкар его не требует (food_id_optional).
        return
    name = os.path.basename(relpath)
    spec = FOOD_SCHEMAS.get(name)
    if spec is None:
        return
    expected, key = spec
    try:
        doc = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"не разбирается как JSON: {e}")
    if not isinstance(doc, dict):
        raise ValueError("корень должен быть объектом")
    if doc.get("schema") != expected:
        raise ValueError(f"schema должна быть {expected!r}, получено {doc.get('schema')!r}")

    # Ключ массива у shopping отличается от имени файла — отсюда явная карта выше.
    arr_key = {"products": "products", "recipes": "recipes",
               "shopping-items": "items"}[key]
    items = doc.get(arr_key)
    if not isinstance(items, list):
        raise ValueError(f"{arr_key} — список")

    seen = set()
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            raise ValueError(f"{arr_key}[{i}] — объект")
        iid = it.get("id")
        if not isinstance(iid, str) or not iid:
            raise ValueError(f"{arr_key}[{i}].id — непустая строка")
        if iid in seen:
            raise ValueError(f"{arr_key}: повтор id {iid!r}")
        seen.add(iid)

    if arr_key == "products":
        for i, it in enumerate(items):
            if not isinstance(it.get("name"), str) or not it["name"].strip():
                raise ValueError(f"products[{i}].name — непустая строка")
            al = it.get("aliases", [])
            if not isinstance(al, list) or not all(isinstance(a, str) for a in al):
                raise ValueError(f"products[{i}].aliases — список строк")
            # Страница делит на pack_size, считая упаковки. Строка дала бы «NaN уп.»
            # прямо на экране в магазине. С 2026-08-01 pack_size — каноничное
            # МЕСТО фасовки (понятие «магазин» из страницы убрано).
            _num_or_none(f"products[{i}]", "pack_size", it.get("pack_size"))
            # ЛЕГАСИ: stores[] (2026-07-20..08-01, фасовка жила внутри
            # магазинов). Страница такие файлы читает (packOf берёт первую
            # заполненную фасовку) и при сохранении продукта переводит на
            # плоский pack_size — форму по-прежнему проверяем, чтобы битый
            # старый файл не разнёс NaN по списку до своей миграции.
            st = it.get("stores")
            if st is not None:
                if not isinstance(st, list):
                    raise ValueError(f"products[{i}].stores — список или отсутствует")
                for j, one in enumerate(st):
                    if not isinstance(one, dict):
                        raise ValueError(f"products[{i}].stores[{j}] — объект")
                    if not isinstance(one.get("name", ""), str):
                        raise ValueError(f"products[{i}].stores[{j}].name — строка")
                    # Делитель числа упаковок — та же причина, что и выше.
                    _num_or_none(f"products[{i}].stores[{j}]", "pack_size",
                                 one.get("pack_size"))
            if it.get("staple") is not None and not isinstance(it.get("staple"), bool):
                raise ValueError(f"products[{i}].staple — true/false или отсутствует")
            # Разваривание: сколько граммов готового продукта из 1 г сухого.
            # Страница ДЕЛИТ на него варёный вес из рецепта, чтобы узнать,
            # сколько покупать. Строка или ноль дали бы NaN/деление на ноль
            # прямо в количестве к покупке.
            cr = it.get("cooked_ratio")
            if cr is not None:
                if not _is_num(cr) or cr <= 0:
                    raise ValueError(
                        f"products[{i}].cooked_ratio — положительное число или null "
                        f"(получено {cr!r})")
            # Граммов в штуке: связывает «3 шт» с весом. Ноль или строка сделали
            # бы пересчёт штук в граммы NaN'ом прямо в списке покупок.
            pg = it.get("piece_g")
            if pg is not None:
                if not _is_num(pg) or pg <= 0:
                    raise ValueError(
                        f"products[{i}].piece_g — положительное число или null "
                        f"(получено {pg!r})")
            # Граммов в 100 мл: плотность жидкого продукта (масло, молоко, вино).
            # Страница ДЕЛИТ на неё (qty*d/100) и умножает — строка или ноль дали
            # бы NaN/ноль прямо в КБЖУ. Это НЕ глобальная таблица: цифра у
            # конкретного продукта. Нет её → мл ≈ г (безопасный откат).
            gm = it.get("g_per_100ml")
            if gm is not None:
                if not _is_num(gm) or gm <= 0:
                    raise ValueError(
                        f"products[{i}].g_per_100ml — положительное число или null "
                        f"(получено {gm!r})")
            # Пищевая ценность СЫРОГО продукта на 100 г. Только КБЖУ — витамины
            # и минералы вне области интереса, а вместе с ними отпадает вся
            # система коэффициентов удержания USDA: для белка и углеводов она
            # равна единице (уходит вода, а не нутриент), а жир меняется только
            # сливом и впитыванием масла, что задаётся на уровне рецепта.
            # Источник — этикетка продукта: для российских товаров она точнее
            # любой сверки с USDA по названию.
            n1 = it.get("nutrition_100g")
            if n1 is not None:
                if not isinstance(n1, dict):
                    raise ValueError(f"products[{i}].nutrition_100g — объект или null")
                for k, v in n1.items():
                    if k == "source":
                        if v is not None and not isinstance(v, str):
                            raise ValueError(f"products[{i}].nutrition_100g.source — строка")
                        continue
                    _num_or_none(f"products[{i}].nutrition_100g", k, v)

    elif arr_key == "recipes":
        for i, it in enumerate(items):
            if not isinstance(it.get("title"), str) or not it["title"].strip():
                raise ValueError(f"recipes[{i}].title — непустая строка")
            # САМАЯ ВАЖНАЯ ПРОВЕРКА ФАЙЛА. servings — делитель пересчёта порций;
            # ноль или строка тихо разносит NaN/Infinity по каждой строке списка
            # покупок, которая произошла от этого рецепта, и заметить это можно
            # только у полки.
            sv = it.get("servings")
            if not _is_num(sv) or sv <= 0:
                raise ValueError(f"recipes[{i}].servings — положительное число (получено {sv!r})")
            ing = it.get("ingredients")
            if not isinstance(ing, list):
                raise ValueError(f"recipes[{i}].ingredients — список")
            for j, g in enumerate(ing):
                if not isinstance(g, dict):
                    raise ValueError(f"recipes[{i}].ingredients[{j}] — объект")
                if not isinstance(g.get("name"), str) or not g["name"].strip():
                    raise ValueError(f"recipes[{i}].ingredients[{j}].name — непустая строка")
                # Строка вместо числа при суммировании СКЛЕИТСЯ, а не сложится:
                # "600"+"400" = "600400". Тихо и катастрофично.
                _num_or_none(f"recipes[{i}].ingredients[{j}]", "qty", g.get("qty"))
                u = g.get("unit")
                if u is not None and not isinstance(u, str):
                    raise ValueError(f"recipes[{i}].ingredients[{j}].unit — строка или null")
                # Единственное место, где enum оправдан: опечатка тут не «покажет
                # незнакомое», а ТИХО отключит пересчёт варёного веса в сухой —
                # и в список покупок уедет 390 г гречки вместо 156 г.
                stt = g.get("state")
                if stt is not None and stt not in ("cooked", "dry"):
                    raise ValueError(
                        f"recipes[{i}].ingredients[{j}].state — cooked/dry или отсутствует "
                        f"(получено {stt!r})")
            st = it.get("steps")
            if not isinstance(st, list) or not all(isinstance(s, dict) for s in st):
                raise ValueError(f"recipes[{i}].steps — список объектов")
            nu = it.get("nutrition")
            if nu is not None:
                if not isinstance(nu, dict):
                    raise ValueError(f"recipes[{i}].nutrition — объект или null")
                for k, v in nu.items():
                    _num_or_none(f"recipes[{i}].nutrition", k, v)
            # Масса ГОТОВОГО блюда, если её взвесили. Нужна ровно для одного —
            # значений «на 100 г»: сколько выпарилось воды, из данных не выводится
            # (зависит от посуды, крышки, огня, времени), поэтому величина
            # измеряемая, а не вычисляемая. Нет числа — значений на 100 г нет.
            _num_or_none(f"recipes[{i}]", "finished_g", it.get("finished_g"))

    else:  # shopping
        for i, it in enumerate(items):
            _num_or_none(f"items[{i}]", "qty", it.get("qty"))
            _num_or_none(f"items[{i}]", "extra", it.get("extra"))
            if it.get("bought") is not None and not isinstance(it.get("bought"), bool):
                raise ValueError(f"items[{i}].bought — true/false или отсутствует")
            fr = it.get("from", [])
            if not isinstance(fr, list) or not all(isinstance(f, dict) for f in fr):
                raise ValueError(f"items[{i}].from — список объектов")


_HEALTH_MODS = None
_LABS_RULES = None


def _labs_rules():
    """labs_rules.py скилла health-labs (правила ручной точки) или None, если не смонтирован рядом с server.py."""
    global _LABS_RULES
    if _LABS_RULES is None:
        _health_skill_mods()                       # дополняет sys.path каталогами скилла и _nas/api
        try:
            import labs_rules as lr
            _LABS_RULES = lr
        except ImportError as e:
            print(f"hub-api: labs_rules.py недоступен ({e}) — ручные точки анализов с сайта отключены", flush=True)
            _LABS_RULES = False
    return _LABS_RULES or None


def _health_skill_mods():
    """→ (validate_report, validate_labs_info) или (None, None). Модули скилла health-labs лежат рядом с server.py
    (deploy кладёт их в _nas/api/, compose монтирует в /app) — иначе канон репозитория skills/health-labs/scripts
    (+ _shared-references для hub_settings). Их правила — единственная реализация: страница и скилл проверяют одним кодом."""
    global _HEALTH_MODS
    if _HEALTH_MODS is not None:
        return _HEALTH_MODS
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.normpath(os.path.join(here, "..", "..", ".."))
    for cand in (here, os.path.join(repo, "skills", "health-labs", "scripts"), os.path.join(repo, "_shared-references"),
                 os.path.join(ROOT, "_nas", "api")):
        if os.path.isdir(cand) and cand not in sys.path:
            sys.path.append(cand)
    try:
        import validate_report as vr
        import validate_labs_info as vl
        _HEALTH_MODS = (vr, vl)
    except ImportError as e:
        print(f"hub-api: модули health-labs недоступны ({e}) — отчёты и справка маркера с сайта отключены", flush=True)
        _HEALTH_MODS = (None, None)
    return _HEALTH_MODS


def _health_labs():
    """labs.json раздела (для сверки id маркеров) или None. Читает, не пишет."""
    try:
        with open(os.path.join(HEALTH_ROOT, "labs.json"), encoding="utf-8") as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) else None
    except (OSError, ValueError):
        return None


def health_report_save(root, body, now=None):
    """POST /api/hd/report {name | topic, content, overwrite?} → (код, ответ).

    Форма — validate_report.check (ровно как скилл). Новое имя пишется; то же содержимое — no-op; другое
    содержимое под тем же именем — 409 «exists», пока клиент не пришлёт overwrite: true (копия в .versions/)."""
    vr, _ = _health_skill_mods()
    if vr is None:
        return 503, {"error": "validate_report.py не смонтирован в hub-api"}
    content = body.get("content")
    if not isinstance(content, str) or not content.strip():
        return 400, {"error": "bad request body", "detail": "content — непустая строка"}
    if len(content.encode("utf-8")) > MAX_BYTES:
        return 413, {"error": "content too large"}
    name = body.get("name")
    if not name:
        topic = body.get("topic")
        if not isinstance(topic, str) or not vr.slug(topic):
            return 400, {"error": "bad request body", "detail": "нужно name или topic"}
        meta, _b, _e = vr.parse(content)
        if not vr.iso_ok((meta or {}).get("date", "")):      # имя берётся из даты шапки: нет даты — отдать ошибки формата
            errors, warnings, _m = vr.check(content, _health_labs())
            return 400, {"error": "report invalid", "detail": "; ".join(errors[:6]), "errors": errors, "warnings": warnings}
        name = f"{meta['date']}-{vr.slug(topic)}.md"
    if not isinstance(name, str):
        return 400, {"error": "bad request body", "detail": "name — строка"}
    name = unicodedata.normalize("NFC", name)
    if not vr.NAME_RE.match(name) or not vr.iso_ok(name[:10]):
        return 400, {"error": "bad name", "detail": "имя — ГГГГ-ММ-ДД-тема.md (строчные буквы, цифры, дефис)"}
    errors, warnings, _meta = vr.check(content, _health_labs(), name)
    if errors:
        return 400, {"error": "report invalid", "detail": "; ".join(errors[:6]), "errors": errors, "warnings": warnings}
    rel = "reports/" + name
    full = os.path.join(root, rel)
    try:
        with open(full, "rb") as f:
            cur = f.read()
    except FileNotFoundError:
        cur = None
    try:
        if cur is None:
            h = save_file(root, rel, content, None, now)
            return 200, {"path": rel, "name": name, "hash": h, "status": "created", "warnings": warnings}
        if cur == content.encode("utf-8"):
            return 200, {"path": rel, "name": name, "hash": file_hash(cur), "status": "same", "warnings": warnings}
        if body.get("overwrite") is not True:
            return 409, {"error": "exists", "name": name, "current_hash": file_hash(cur)}
        h = save_file(root, rel, content, file_hash(cur), now)
        return 200, {"path": rel, "name": name, "hash": h, "status": "replaced", "warnings": warnings}
    except Conflict as c:
        return 409, {"error": "hash mismatch", "current_hash": c.current_hash}
    except TooLarge:
        return 413, {"error": "content too large"}


def health_marker_info_save(root, body, now=None):
    """POST /api/hd/marker-info {id, what: [str], up, down, base_hash} → (код, ответ).

    Слияние — validate_labs_info.merge_info(manual=True): запись помечается `manual: true` и заменяет прежнюю;
    записи с `manual: true` скилл не переписывает. base_hash — хэш biomarkers-info.json (null — файла ещё нет)."""
    _, vl = _health_skill_mods()
    if vl is None:
        return 503, {"error": "validate_labs_info.py не смонтирован в hub-api"}
    mid, what = body.get("id"), body.get("what")
    if "base_hash" not in body:
        return 400, {"error": "bad request body", "detail": "нужен base_hash"}
    base_hash = body["base_hash"]
    if not isinstance(mid, str) or not mid or not (base_hash is None or isinstance(base_hash, str)):
        return 400, {"error": "bad request body"}
    rel = "biomarkers-info.json"
    full = os.path.join(root, rel)
    try:
        with open(full, "rb") as f:
            raw = f.read()
        doc = json.loads(raw.decode("utf-8"))
        cur_hash = file_hash(raw)
    except FileNotFoundError:
        doc, cur_hash = {"schema": vl.SCHEMA, "info": {}}, None
    except ValueError:
        return 500, {"error": "biomarkers-info.json не разбирается — файл не тронут"}
    if base_hash != cur_hash:
        return 409, {"error": "hash mismatch", "current_hash": cur_hash}
    labs = _health_labs()
    labs_ids = set(vl.load_labs_markers(labs)) if labs else None
    today = (now or datetime.now()).strftime("%Y-%m-%d")
    new_doc, report = vl.merge_info(doc, {mid: {"what": what, "up": body.get("up"), "down": body.get("down")}},
                                    today=today, overwrite=True, labs_ids=labs_ids, manual=True)
    act = report[0]["action"] if report else ""
    if act in ("reject_invalid", "reject_unknown_id"):
        return 400, {"error": "schema invalid", "detail": report[0].get("reason", "")}
    try:
        h = save_file(root, rel, json.dumps(new_doc, ensure_ascii=False, indent=2) + "\n", cur_hash, now,
                      validate=validate_health)
    except Conflict as c:
        return 409, {"error": "hash mismatch", "current_hash": c.current_hash}
    except ValueError as e:
        return 400, {"error": "schema invalid", "detail": str(e)}
    return 200, {"path": rel, "hash": h, "action": act}


def health_labs_manual_save(root, content, base_hash, now=None):
    """Запись labs.json со страницы → (код, ответ). Только при ai_mode: off; только ручные точки (source=manual).

    403 — режим on (или режим не читается: молчаливо считаем «on»); 503 — нет labs_rules.py; 409 — base_hash не
    совпал с файлом; 400 — правка вышла за разрешённое (labs_rules.check_manual_edit) или файла нет. Статус точек и
    производные поля маркера считает сервер; в ответе normalized: true — страница перечитывает файл."""
    try:
        mode = hub_settings_read(ROOT)[0].get("ai_mode")
    except (OSError, ValueError):
        mode = "on"
    if mode != "off":
        return 403, {"error": "ai_mode on", "detail": "ручная запись анализов доступна только при выключенном ИИ "
                     "(режим «без ИИ»); при включённом — анализы вносит скилл health-labs"}
    lr = _labs_rules()
    if lr is None:
        return 503, {"error": "labs_rules.py не смонтирован в hub-api"}
    if not isinstance(base_hash, str):
        return 400, {"error": "schema invalid", "detail": "labs.json правится только поверх существующего (base_hash)"}
    try:
        old_raw = open(os.path.join(root, "labs.json"), "rb").read()
    except FileNotFoundError:
        return 404, {"error": "not found", "path": "labs.json"}
    if file_hash(old_raw) != base_hash:
        return 409, {"error": "hash mismatch", "current_hash": file_hash(old_raw)}
    try:
        old, new = json.loads(old_raw.decode("utf-8")), json.loads(content)
    except ValueError as e:
        return 400, {"error": "schema invalid", "detail": f"не разбирается как JSON: {e}"}
    errors, norm = lr.check_manual_edit(old, new)
    if errors:
        return 400, {"error": "schema invalid", "detail": "; ".join(errors[:5]), "errors": errors[:20]}
    norm["updated"] = (now or datetime.now()).strftime("%Y-%m-%d")
    text = json.dumps(norm, ensure_ascii=False, indent=1) + "\n"
    try:
        new_hash = save_file(root, "labs.json", text, base_hash, now, validate=validate_health)
    except Conflict as c:
        return 409, {"error": "hash mismatch", "current_hash": c.current_hash}
    except TooLarge:
        return 413, {"error": "content too large"}
    except ValueError as e:
        return 400, {"error": "schema invalid", "detail": str(e)}
    return 200, {"path": "labs.json", "hash": new_hash, "normalized": True}


def hd_sniff(raw):
    """Тип файла исследования по первым байтам (расширению из имени верить нельзя) → "pdf"|"jpg"|"png"|"heic"|None."""
    if raw[:5] == b"%PDF-":
        return "pdf"
    if raw[:3] == b"\xff\xd8\xff":
        return "jpg"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if raw[4:8] == b"ftyp" and raw[8:12] in HD_HEIC_BRANDS:
        return "heic"
    return None


def health_upload(root, body, now=None):
    """POST /api/hd/upload {kind, date, b64} → (код, ответ). Файл → Health/studies/ГГГГ-ММ-ДД-вид.ext;
    занятое имя не перезаписывается (-2, -3…), байт в байт тот же файл — возвращается существующий."""
    kind, date_s, b64 = body.get("kind", ""), body.get("date"), body.get("b64")
    if not isinstance(kind, str) or not isinstance(date_s, str) or not isinstance(b64, str):
        return 400, {"error": "bad request body"}
    try:
        datetime.strptime(date_s, "%Y-%m-%d")
    except ValueError:
        return 400, {"error": "bad request body", "detail": "date — ГГГГ-ММ-ДД"}
    slug = re.sub(r"[^a-zа-яё0-9]+", "-", unicodedata.normalize("NFC", kind).strip().lower()).strip("-")[:40].strip("-") or "файл"
    try:
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        return 400, {"error": "bad file", "detail": "b64: не base64"}
    if not raw:
        return 400, {"error": "bad file", "detail": "пустой файл"}
    if len(raw) > HD_UPLOAD_MAX_BYTES:
        return 413, {"error": "file too large", "detail": "файл больше 20 МБ"}
    ext = hd_sniff(raw)
    if ext is None:
        return 400, {"error": "bad file", "detail": "формат не распознан: нужны PDF, JPEG, PNG или HEIC"}
    sha = file_hash(raw)
    with _write_lock:
        n = 1
        while True:
            name = f"{date_s}-{slug}{'' if n == 1 else '-' + str(n)}.{ext}"
            rel = f"{HD_STUDIES_DIR}/{name}"
            full = os.path.join(root, rel)
            if not os.path.exists(full):
                break
            if _read_hash(full) == sha:
                return 200, {"name": name, "path": rel, "sha256": sha, "size": len(raw), "type": ext, "status": "same"}
            n += 1
            if n > 99:
                return 409, {"error": "exists", "detail": "слишком много файлов с таким именем"}
        _makedirs_owned(root, os.path.dirname(full))
        _place(root, rel, full, raw)
    return 200, {"name": name, "path": rel, "sha256": sha, "size": len(raw), "type": ext, "status": "created"}


def file_hash(data):
    return hashlib.sha256(data).hexdigest()


def read_file(root, relpath):
    """→ (content_str, hash). FileNotFoundError, если файла нет."""
    full = os.path.join(root, relpath)
    with open(full, "rb") as f:
        data = f.read()
    return data.decode("utf-8"), file_hash(data)


class Conflict(Exception):
    """base_hash не совпал с текущим состоянием файла."""

    def __init__(self, current_hash):
        self.current_hash = current_hash


class TooLarge(ValueError):
    """Тело больше MAX_BYTES. Наследник ValueError — обратная совместимость.

    В do_POST ловится ДО ValueError: превышение размера → 413,
    провал валидации схемы → 400.
    """


def prune_versions(backup_dir, basename, now=None):
    """Оставить копии файла basename в backup_dir по правилу VERSIONS_KEEP/DAYS/MIN. → сколько удалено.

    Сбой чистки запись не роняет: копии — страховка, а не данные. Удаляется локально (os.remove):
    копии создаются так же, мимо File Station, в зеркала их и не возили."""
    try:
        names = sorted((n for n in os.listdir(backup_dir)
                        if (m := _VERSION_TS.match(n)) and m.group(2) == basename), reverse=True)
    except OSError:
        return 0
    cutoff = (now or datetime.now()) - timedelta(days=VERSIONS_DAYS)
    # дописываемые ряды (дневные цены, 11.11): каждая версия — прежняя плюс строка дня, старые копии ничего не
    # страхуют, а файл растёт до ~2 МБ к концу года — держим APPEND_VERSIONS_KEEP последних
    keep = APPEND_VERSIONS_KEEP if APPEND_ONLY_RE.match(basename) else max(VERSIONS_KEEP, VERSIONS_MIN)
    removed = 0
    for i, n in enumerate(names):
        try:
            old = datetime.strptime(_VERSION_TS.match(n).group(1), "%Y%m%d-%H%M%S") < cutoff
        except ValueError:
            continue
        if i >= keep or (old and i >= min(VERSIONS_MIN, keep)):
            try:
                os.remove(os.path.join(backup_dir, n))
                removed += 1
            except OSError:
                pass
    return removed


def save_file(root, relpath, content, base_hash, now=None, validate=None):
    """Проверяет base_hash, бэкапит в .versions/, атомарно пишет. → новый hash.

    validate — необязательная функция (relpath, content); ValueError из неё
    означает «структура битая, не пишем» (для health-файлов — схема).
    """
    full = os.path.join(root, relpath)
    data = content.encode("utf-8")
    if len(data) > MAX_BYTES:
        raise TooLarge("content too large")
    if validate is not None:
        validate(relpath, content)      # ValueError → 400 выше
    with _write_lock:
        if base_hash is None:
            # Создание нового файла. Если он ВСЁ ЖЕ существует — кто-то создал
            # его параллельно; 409, а не тихая перезапись (тот же контракт, что
            # у гонки правок). Бэкап не нужен: прежней версии нет.
            if os.path.exists(full):
                raise Conflict(file_hash(open(full, "rb").read()))
            _makedirs_owned(root, os.path.dirname(full))
        else:
            with open(full, "rb") as f:  # FileNotFoundError → 404 выше
                current = f.read()
            if file_hash(current) != base_hash:
                raise Conflict(file_hash(current))
            ts = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
            backup_dir = os.path.join(root, VERSIONS_DIR, os.path.dirname(relpath))
            _makedirs_owned(root, backup_dir)
            backup = os.path.join(backup_dir, ts + "_" + os.path.basename(relpath))
            shutil.copy2(full, backup)
            _chown_quiet(backup)
            prune_versions(backup_dir, os.path.basename(relpath), now)
        _place(root, relpath, full, data)
    return file_hash(data)


def validate_job(relpath, content):
    """JSON задач обязан читаться: битый eshop-prices.json сломал бы страницу и скилл; в .jsonl — каждая строка."""
    if relpath.endswith(".jsonl"):
        for n, ln in enumerate(content.split("\n"), 1):
            if ln.strip():
                try:
                    json.loads(ln)
                except ValueError as e:
                    raise ValueError(f"строка {n}: не JSON: {e}") from None
        return
    if relpath.endswith(".json"):
        try:
            json.loads(content)
        except ValueError as e:
            raise ValueError(f"не JSON: {e}") from None


def append_line(root, relpath, line):
    """Дописать одну строку в журнал задач. Строка — один JSON-объект без переводов строк."""
    if not JOB_LOG_RE.match(relpath):
        raise PermissionError(relpath)
    if "\n" in line or "\r" in line:
        raise ValueError("одна строка")
    json.loads(line)                                   # ValueError → 400
    full = os.path.join(root, relpath)
    with _write_lock:
        try:
            with open(full, "rb") as f:
                old = f.read()
        except FileNotFoundError:
            old = b""
            _makedirs_owned(root, os.path.dirname(full))
        data = old + line.encode("utf-8") + b"\n"
        if len(data) > MAX_BYTES:
            raise TooLarge("log too large")
        _place(root, relpath, full, data)
    return file_hash(data)


def delete_file(root, relpath, base_hash, now=None):
    """Проверяет base_hash, бэкапит в .versions/, удаляет файл. → True.

    base_hash ОБЯЗАТЕЛЕН строкой: удаления вслепую («сотри, что там лежит») быть
    не должно. Иначе гонка с Synology Drive или второй вкладкой стирала бы не тот
    файл, который человек видел на экране, — а восстановить он это может только
    из .versions/, зная, что вообще произошло.

    Имя бэкапа то же, что у save_file (ts_имя): восстановление — одна и та же
    операция независимо от того, правкой файл испортили или удалением.
    """
    full = os.path.join(root, relpath)
    with _write_lock:
        with open(full, "rb") as f:      # FileNotFoundError → 404 выше
            current = f.read()
        if file_hash(current) != base_hash:
            raise Conflict(file_hash(current))
        ts = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
        backup_dir = os.path.join(root, VERSIONS_DIR, os.path.dirname(relpath))
        _makedirs_owned(root, backup_dir)
        backup = os.path.join(backup_dir, ts + "_" + os.path.basename(relpath))
        shutil.copy2(full, backup)
        _chown_quiet(backup)
        prune_versions(backup_dir, os.path.basename(relpath), now)
        _remove(root, relpath, full)
    return True


# ─────────────────── быстрое добавление в список покупок ───────────────────
# POST /api/fd/shop-add — для шортката iPhone: одна строка текста («молоко 2»,
# «сметана 20% 400 г») → строка в shopping.json. Шорткату не нужно ни читать
# файл, ни пересобирать JSON, ни знать про base_hash: всё это делает сервер.
#
# ДОБАВЛЯЕТ ТОЛЬКО ПРОДУКТЫ КАТАЛОГА (решение 2026-09-22). Страница незнакомое
# заводит новым продуктом, а здесь — нет: голосовой ввод даёт опечатки и
# падежи, и каждая стала бы продуктом-сиротой без отдела. Незнакомое →
# кандидаты на выбор или «не нашёл», но не запись.
#
# Сопоставление — копия правил tools/food/match_products.py (точное совпадение
# по name/alias после normalize → применяем; иначе — только подсказки). Копия,
# а не импорт: в контейнер монтируется один server.py. Совпадение normalize с
# эталоном стережёт test_write_api.py.
SHOP_ADD_PATH = "/api/fd/shop-add"

_SA_NOISE = re.compile(
    r"\b(варён\w*|варен\w*|отварн\w*|свеж\w+|замороженн\w+|молот\w+|"
    r"тёрт\w+|терт\w+|нарезанн\w+|очищенн\w+)\b", re.I)
_SA_PARENS = re.compile(r"\([^)]*\)")
_SA_PUNCT = re.compile(r"[^\w\s]", re.U)
_SA_SPACES = re.compile(r"\s+")


def shop_normalize(s):
    """Ключ сравнения — тот же, что match_products.normalize."""
    if not s:
        return ""
    s = s.lower().replace("ё", "е")
    s = _SA_PARENS.sub(" ", s)
    s = _SA_NOISE.sub(" ", s)
    s = _SA_PUNCT.sub(" ", s)
    return _SA_SPACES.sub(" ", s).strip()


# Количество — только ОТДЕЛЬНОЕ число в начале или в конце строки, с
# необязательной единицей. «20%» количеством не считается (за числом идёт %,
# а не конец строки/единица): «сметана 20%» — это продукт, а не 20 сметаны.
# Диктовка пишет единицы и сокращённо («500 г»), и словом («500 грамм», «2 литра»,
# «10 штук») — второе раньше не разбиралось, и количество молча терялось в
# названии. Длинные формы — первыми: иначе «г» откусил бы начало «грамм».
_SA_UNIT = (r"(?P<unit>килограмм(?:а|ов)?|кило|миллилитр(?:а|ов)?|грамм(?:а|ов)?|"
            r"литр(?:а|ов)?|штук(?:а|и)?|шт|гр|г|кг|мл|л)?\.?")
_SA_NUM = r"(?P<num>\d+(?:[.,]\d+)?)"
_SA_QTY_TAIL = re.compile(r"^(?P<name>.+?)\s+" + _SA_NUM + r"\s*" + _SA_UNIT + r"$", re.I)
_SA_QTY_HEAD = re.compile(r"^" + _SA_NUM + r"\s*" + _SA_UNIT + r"\s+(?P<name>.+)$", re.I)
# Единица → (базовая единица, множитель к ней). Одна таблица и для речи, и для
# каталога: «1 кг» к продукту в граммах = 1000, «500 г» к продукту в кг = 0,5.
# Разные базы («2 л» гречки в граммах) — отказ, а не угадывание плотности.
_SA_BASE = {"шт": ("шт", 1), "г": ("г", 1), "гр": ("г", 1), "кг": ("г", 1000),
            "мл": ("мл", 1), "л": ("мл", 1000)}


# Слово → сокращение из _SA_BASE.
_SA_UNIT_WORD = {}
for _stem, _abbr in (("килограмм", "кг"), ("миллилитр", "мл"), ("грамм", "г"), ("литр", "л")):
    for _end in ("", "а", "ов"):
        _SA_UNIT_WORD[_stem + _end] = _abbr
_SA_UNIT_WORD.update({"кило": "кг", "штук": "шт", "штука": "шт", "штуки": "шт"})


# Модель (и диктовка) склеивает число с названием: «молоко300мл», «хлеб100г».
# Ставим пробел на границе буква↔цифра — названия каталога от этого не страдают
# («Сметана 20%» и так с пробелом, «молоко3,2%» становится «молоко 3,2%»).
_SA_GLUE = re.compile(r"(?<=[^\W\d_])(?=\d)|(?<=\d)(?=[^\W\d_])|(?<=%)(?=\d)", re.U)


def shop_unglue(text):
    return _SA_SPACES.sub(" ", _SA_GLUE.sub(" ", text)).strip()


def shop_parse(text):
    """→ (название, число|None, единица из речи|None). Число — как сказано."""
    t = _SA_SPACES.sub(" ", text).strip().rstrip(".")
    if not _SA_QTY_TAIL.match(t) and not _SA_QTY_HEAD.match(t):
        t = shop_unglue(t)
    for rx in (_SA_QTY_TAIL, _SA_QTY_HEAD):
        m = rx.match(t)
        if m:
            unit = _SA_UNIT_WORD.get((m.group("unit") or "").lower(), (m.group("unit") or "").lower()) or None
            return m.group("name").strip(), float(m.group("num").replace(",", ".")), unit
    return t, None, None


def _pack_of(prod):
    """Фасовка продукта — как packOf() страницы (плоский pack_size, затем легаси stores[])."""
    if prod.get("pack_size") is not None:
        return prod["pack_size"]
    for st in prod.get("stores") or []:
        if isinstance(st, dict) and st.get("pack_size") is not None:
            return st["pack_size"]
    return None


def shop_qty(num, spoken_unit, line_unit, prod):
    """→ (qty в единице строки, None) или (None, текст отказа)."""
    if num is None:
        return None, None
    lb, lf = _SA_BASE.get(line_unit or "", (line_unit or "", 1))
    if spoken_unit:
        sb, sf = _SA_BASE[spoken_unit]
        if line_unit and sb != lb:
            return None, (f"«{prod['name']}» в каталоге считается в «{line_unit}», "
                          f"а сказано «{spoken_unit}» — не добавлено.")
        return (num * sf / lf if line_unit else num), None
    # Голое число. Для штучного — это штуки. Для весового/объёмного «молоко 2» —
    # не 2 мл: это упаковки, если фасовка известна, иначе переспрашиваем.
    if lb not in ("г", "мл"):
        return num, None
    pack = _pack_of(prod)
    if pack:
        return num * pack, None
    return None, (f"Сколько «{prod['name']}»? Скажите с единицей: "
                  f"«… 500 {'г' if lb == 'г' else 'мл'}» или «… 1 {'кг' if lb == 'г' else 'л'}».")


def _shop_keys(p):
    return [shop_normalize(k) for k in [p.get("name", "")] + list(p.get("aliases") or [])]


def shop_exact(name, products):
    """→ список продуктов с точным совпадением ключа (обычно 0 или 1)."""
    keys = {shop_normalize(name), shop_normalize(shop_unglue(name))} - {""}
    if not keys:
        return []
    return [p for p in products if keys & set(_shop_keys(p))]


# Падежи из речи («хлеба», «молока») — строгое сопоставление по основе: у всех
# слов совпадают основы, слов столько же, числа — буква в букву, и такой продукт
# в каталоге РОВНО один. Тогда применяем без вопроса. Это не фаззи-матч: жирность
# и прочие числа сравниваются точно («сметаны 20» ≠ «Сметана 15%»), а разные
# слова («картошки» → «Картофель») по-прежнему идут в вопрос или через алиас.
_SA_ENDINGS = sorted((
    "ями", "ами", "ого", "его", "ому", "ему", "ыми", "ими", "ах", "ях", "ой", "ей",
    "ий", "ый", "ая", "яя", "ое", "ее", "ые", "ие", "ую", "юю", "ов", "ев", "ом",
    "ем", "ых", "их", "а", "я", "ы", "и", "у", "ю", "е", "о", "ь"), key=len, reverse=True)


def _sa_stem(w):
    if w.isdigit():
        return w
    for e in _SA_ENDINGS:
        if w.endswith(e) and len(w) - len(e) >= 3:
            return w[:-len(e)]
    return w


def _sa_stem_key(s):
    # Порядок слов не значим: модель выдаёт и «фарш куриный», и «куриный фарш».
    # Набор слов и числа при этом обязаны совпасть полностью.
    return tuple(sorted(_sa_stem(w) for w in shop_normalize(s).split()))


def shop_unglue_words(name, products):
    """«фаршкуриный» → «фарш куриный», если разрез даёт слова каталога.

    Модель склеивает и слова между собой, а границы там нет вовсе. Пробуем
    каждый разрез длинного слова и принимаем только тот, где ОБЕ половины —
    основы слов одного и того же продукта каталога.
    """
    words = shop_normalize(name).split()
    stems = set()
    for p in products:
        for k in [p.get("name", "")] + list(p.get("aliases") or []):
            stems.update(_sa_stem(w) for w in shop_normalize(k).split())
    out, changed = [], False
    for w in words:
        if len(w) < 8 or _sa_stem(w) in stems:
            out.append(w)
            continue
        cuts = [(w[:i], w[i:]) for i in range(4, len(w) - 3)
                if _sa_stem(w[:i]) in stems and _sa_stem(w[i:]) in stems]
        if len(cuts) == 1:
            out.extend(cuts[0])
            changed = True
        else:
            out.append(w)
    return " ".join(out) if changed else name


def shop_stem_exact(name, products):
    key = _sa_stem_key(shop_unglue(name))
    hits = [p for p in products
            if any(_sa_stem_key(k) == key for k in [p.get("name", "")] + list(p.get("aliases") or []))]
    if hits:
        return hits
    unglued = shop_unglue_words(shop_unglue(name), products)
    if unglued == name:
        return []
    key = _sa_stem_key(unglued)
    if not key:
        return []
    return [p for p in products
            if any(_sa_stem_key(k) == key for k in [p.get("name", "")] + list(p.get("aliases") or []))]


def _sa_word_hit(a, b):
    # Падежи из диктовки («молока», «сметаны») точного слова не дают — для
    # ПОДСКАЗОК сравниваем и по общему началу от 4 букв. В запись это не
    # попадает никогда: кандидат применяется только после выбора человеком.
    return a == b or (len(a) >= 4 and len(b) >= 4 and a[:4] == b[:4])


def shop_suggest(name, products, limit=5):
    """Ранжированные кандидаты (продукты) — логика match_products.suggest + падежи."""
    want = set(shop_normalize(name).split())
    # «творог 5%» → «5» совпал бы с жирностью молока; числа ранжируют только
    # в паре со словами, сами по себе кандидата не тянут.
    words = {w for w in want if not w.isdigit()}
    if not want:
        return []
    scored = []
    for i, p in enumerate(products):
        have = set()
        for k in _shop_keys(p):
            have |= set(k.split())
        if not have:
            continue
        inter = {w for w in want if any(_sa_word_hit(w, h) for h in have)}
        if not inter or (words and not (inter & words)):
            continue
        exact = len(inter & have)
        # при равенстве — у кого общее начало слова длиннее: «гречки» ближе к
        # «гречка» (5 букв), чем к «греческий» (4)
        prefix = sum(max(len(os.path.commonprefix([w, h])) for h in have) for w in inter)
        scored.append((len(inter) / min(len(want), len(have)), exact, len(inter), prefix, -i, p))
    scored.sort(key=lambda x: x[:5], reverse=True)
    return [p for *_, p in scored[:limit]]


def _fmt_qty(q):
    return str(int(q)) if float(q).is_integer() else str(round(q, 3)).replace(".", ",")


# ── несколько продуктов одной фразой ──
# «молоко 2 литра, картошку 2 кг и хлеб» → три позиции. Разделители — «;»,
# перевод строки, запятая (кроме десятичной «3,2»), союз «и». Диктовка не всегда
# ставит запятые, поэтому граница есть и после количества С ЕДИНИЦЕЙ, за которым
# идёт слово: «молоко 2 литра картошка 2 кг». После голого числа не режем —
# «сметана 20 молоко» неоднозначно.
# «|» — разделитель ответа модели на телефоне (шорткат может сначала отдать
# фразу модели «На устройстве», а сюда прислать «молоко 900 мл | картофель 2 кг»).
_SA_SEP = re.compile(r"\s*(?:[;|\n]|,(?!\d)|\s+и\s+)\s*", re.I)
_SA_AFTER_UNIT = re.compile(
    r"(\d+(?:[.,]\d+)?\s*(?:килограмм(?:а|ов)?|кило|миллилитр(?:а|ов)?|грамм(?:а|ов)?|"
    r"литр(?:а|ов)?|штук(?:а|и)?|шт|гр|г|кг|мл|л)\.?)\s+(?=[^\d\s])", re.I)
_SA_UNIT_THEN_NUM = re.compile(
    r"(\d+(?:[.,]\d+)?\s*(?:килограмм(?:а|ов)?|кило|миллилитр(?:а|ов)?|грамм(?:а|ов)?|"
    r"литр(?:а|ов)?|штук(?:а|и)?|шт|гр|г|кг|мл|л)\.?)\s+(?=\d)", re.I)
# Слова-связки речи в начале куска: «мне нужно молока», «ещё хлеб».
_SA_FILLER = re.compile(
    r"^(?:(?:я|мы|мне|нам|хочу|хотим|хотел|хотела|нужно|надо|нужен|нужна|нужны|"
    r"купить|купи|куплю|взять|возьми|ещ[её]|также|тоже|и|а|пожалуйста|добавь|добавить|"
    r"предположим|давай|в\s+магазине|в\s+магазин|из\s+магазина)\s+)+", re.I)


def shop_split(text, products):
    """→ список позиций. Кусок, склеенный с соседом через запятую, остаётся одним,
    если так он совпадает с продуктом каталога («Говядина, суповой набор»)."""
    raw = [p for p in _SA_SEP.split(text.strip()) if p and p.strip()]
    parts = []
    for piece in raw:
        # «2 литра 500 гр гречки» — после единицы сразу число: начало следующей позиции.
        for sub in _SA_UNIT_THEN_NUM.sub(r"\1\n", piece).split("\n"):
            sub = _SA_FILLER.sub("", sub.strip())
            # Режем после количества, только если перед ним уже есть слово:
            # «500 гр овсянки» (число впереди) — одна позиция, а не «500 гр» + «овсянки».
            start = 0
            for m in _SA_AFTER_UNIT.finditer(sub):
                if sub[start:m.start()].strip():
                    parts.append(sub[start:m.end(1)])
                    start = m.end()
            parts.append(sub[start:])
    parts = [_SA_FILLER.sub("", x.strip()).strip(" .") for x in parts]
    parts = [x for x in parts if x]
    out, i = [], 0
    while i < len(parts):
        if i + 1 < len(parts):
            joined = parts[i] + ", " + parts[i + 1]
            if shop_exact(joined, products) or shop_exact(shop_parse(joined)[0], products):
                out.append(joined)
                i += 2
                continue
        out.append(parts[i])
        i += 1
    return out


def _shop_resolve(text, products):
    """Текст позиции → (продукт, число, единица) или готовый ответ без записи."""
    # Сначала — строка целиком: «Сметана 20» может оказаться именем продукта,
    # и тогда число в ней — часть названия, а не количество.
    hits = shop_exact(text, products)
    num, unit, name = None, None, text
    if not hits:
        name, num, unit = shop_parse(text)
        hits = shop_exact(name, products)
    if not hits:
        stem_hits = shop_stem_exact(name, products)
        if len(stem_hits) == 1:
            hits = stem_hits
    if len(hits) == 1:
        return hits[0], num, unit, None
    # Хвост кандидата — количество РОВНО как сказано: повторный запрос
    # разберёт его теми же правилами, что и первый.
    tail = "" if num is None else " " + _fmt_qty(num) + (" " + unit if unit else "")
    shown = shop_unglue(name)
    cands = hits or shop_suggest(name, products)
    if not cands:
        return None, None, None, {"status": "not_found", "name": shown + tail,
                                  "message": f"«{shown}» нет в каталоге продуктов — не добавлено."}
    # Количество — прямо в заголовке выбора: у полки должно быть видно, к чему
    # оно относится, а не только в самих вариантах.
    head = f"Уточните «{shown}»" + (f" — {tail.strip()}" if tail else "") + ":"
    return None, None, None, {"status": "choose", "name": shown, "text": text,
                              "message": head,
                              # Последним — отказ: выбор в Командах нельзя отменить,
                              # не оборвав весь шорткат, поэтому «пропустить» даёт
                              # сервер, а не интерфейс.
                              "candidates": [p["name"] + tail for p in cands] + [SHOP_SKIP]}


def _shop_apply(doc, prod, num, unit, now):
    """Применяет позицию к загруженному shopping-документу. → (ответ, изменён ли)."""
    items = doc.setdefault("items", [])
    open_line = next((it for it in items
                      if it.get("product_id") == prod["id"] and not it.get("bought")), None)
    line_unit = (open_line or {}).get("unit") or prod.get("unit") or None
    qty, refusal = shop_qty(num, unit, line_unit, prod)
    if refusal:
        return {"status": "unit_mismatch" if unit else "need_unit",
                "name": prod["name"], "message": refusal}, False
    u = f" {line_unit}" if line_unit else ""
    if open_line is not None:
        if qty is None:
            return {"status": "exists", "name": prod["name"],
                    "message": f"«{prod['name']}» уже в списке."}, False
        # Прибавка к открытой строке — в extra, как ручная правка тапом на
        # странице: qty там «структурное» (форма/рецепты) и пересчитывается.
        open_line["extra"] = (open_line.get("extra") or 0) + qty
        total = (open_line.get("qty") or 0) + open_line["extra"]
        return {"status": "merged", "name": prod["name"], "product_id": prod["id"],
                "short": f"{prod['name']} (теперь {_fmt_qty(total)}{u})",
                "message": f"«{prod['name']}»: теперь {_fmt_qty(total)}{u}"}, True
    # id — миллисекунды, как у страницы; несколько позиций за один запрос
    # получили бы одинаковый id, а повтор id валидатор отвергает.
    ids = {it.get("id") for it in items}
    n = int(now.timestamp() * 1000)
    while "i" + str(n) in ids:
        n += 1
    items.append({
        "id": "i" + str(n), "product_id": prod["id"], "name": prod["name"],
        "qty": qty, "unit": line_unit, "extra": 0, "bought": False,
        "from": [], "added": now.strftime("%Y-%m-%d"), "note": "",
    })
    q = "" if qty is None else f" — {_fmt_qty(qty)}{u}"
    return {"status": "added", "name": prod["name"], "product_id": prod["id"],
            "short": prod["name"] + q, "message": f"Добавлено: {prod['name']}{q}"}, True


SHOP_SKIP = "⏭ Пропустить"
# «choose» в сводке НЕТ намеренно: неоднозначные позиции шорткат тут же
# доспрашивает циклом, и строка «Уточните: …» в итоговом уведомлении только мешает —
# человек в этот момент уже уточнил. Сводка отвечает на вопрос «что в списке».
_SA_GROUPS = (("added", "Добавлено"), ("merged", "Добавлено"),
              ("exists", "Уже в списке"), ("need_unit", "Нужна единица (г/кг/мл/л)"),
              ("unit_mismatch", "Не та единица"), ("not_found", "Нет в каталоге"),
              ("suspect", "Проверьте число"))
_SA_NUMS = re.compile(r"\d+(?:\.\d+)?")


def _shop_summary(results):
    lines = []
    for title in dict.fromkeys(t for _, t in _SA_GROUPS):
        names = [r.get("short") or r.get("name") or "?" for r in results
                 if dict(_SA_GROUPS).get(r["status"]) == title]
        if names:
            lines.append(f"{title}: " + "; ".join(names))
    return "\n".join(lines)


def shop_add(root, text, now=None, retries=3, source=None, items=None):
    """Добавляет позицию или несколько позиций в shopping.json. → dict ответа шортката.

    Одна позиция — status: added | merged | exists | choose | not_found |
    unit_mismatch | need_unit; несколько — status: batch и сводка в message.
    Плюс всегда: empty | error. Во всех ответах есть `choose` — список
    {text, message, candidates} для неоднозначных позиций (пустой, если их нет):
    шорткат может обходить его одним циклом в обоих режимах. Для одной позиции
    `candidates` дублируется и на верхнем уровне — первая версия шортката
    читает его оттуда.
    items — готовый список позиций (тип результата «Список» у модели в
    Командах) вместо text: позиции уже разделены, сервер их НЕ режет повторно —
    запятая внутри элемента («Говядина, суповой набор») остаётся названием.
    source — исходная фраза, если text/items пришли от модели: числа сверяются с ней
    (status позиции suspect, если модель число выдумала или исказила).
    Запись — ОДНА на весь запрос через save_file (бэкап, схема, base_hash):
    при нескольких записях за секунду бэкапы с одним именем затирали бы друг
    друга, и исходное состояние списка терялось. 409 → перечитать и повторить.
    """
    now = now or datetime.now()
    text = (text or "").strip()
    if items is not None:
        items = [x.strip() for x in items if x.strip()]
    if not (items if items is not None else text):
        return {"status": "empty", "message": "Пустой ввод — ничего не добавлено.", "choose": []}
    if items is None and text == SHOP_SKIP:
        return {"status": "skipped", "message": "Пропущено.", "choose": []}
    try:
        products = json.loads(read_file(root, "products.json")[0]).get("products") or []
    except FileNotFoundError:
        return {"status": "error", "message": "Каталог продуктов не найден.", "choose": []}

    # Фраза целиком — продукт каталога? Тогда не делим (запятая в названии).
    if items is not None:
        parts = items
    else:
        parts = [text] if shop_exact(text, products) else shop_split(text, products) or [text]
    resolved = [_shop_resolve(p, products) for p in parts]
    lost = []
    if source:
        # Текст пришёл от модели. Модель умеет тихо заменить число (500 г
        # овсянки → 900 г), а заметно это станет только у кассы. Число позиции
        # обязано встречаться в исходной фразе, иначе позиция не пишется.
        # Каждое сказанное число подтверждает ОДНУ позицию: иначе «900 мл
        # молока» прикрыло бы выдуманные «900 г гречки».
        said = {}
        # «20%» во фразе — часть названия (жирность), а не количество.
        for x in _SA_NUMS.findall(re.sub(r"\d+(?:[.,]\d+)?\s*%", " ", source).replace(",", ".")):
            said[x] = said.get(x, 0) + 1
        checked = []
        for part, (pr, num, unit, early) in zip(parts, resolved):
            # Проверяем и неоднозначные позиции: их число уедет в кандидата и
            # запишется после выбора уже БЕЗ source.
            if early is not None:
                num = shop_parse(part)[1]
            key = None if num is None else _fmt_qty(num).replace(",", ".")
            if key is None or said.get(key, 0) > 0:
                if key is not None:
                    said[key] -= 1
                checked.append((pr, num, unit, early))
            else:
                checked.append((None, None, None, {
                    "status": "suspect", "name": part,
                    "message": f"«{part}»: такого числа в сказанном нет — не добавлено."}))
        resolved = checked
        # Обратная проверка: число из фразы, которое не досталось ни одной позиции,
        # — модель его потеряла («300 г хлеба» → «хлеб триста»). Позиция тогда
        # запишется без количества; молчать об этом нельзя.
        lost = [k for k, c in said.items() for _ in range(c)]

    for _ in range(retries):
        try:
            content, h = read_file(root, "shopping.json")
            doc = json.loads(content)
        except FileNotFoundError:
            doc, h = {"schema": "food-shopping@1", "items": []}, None
        results, changed = [], False
        for prod, num, unit, early in resolved:
            if early is not None:
                results.append(early)
                continue
            res, ch = _shop_apply(doc, prod, num, unit, now)
            results.append(res)
            changed = changed or ch
        if changed:
            doc["updated"] = now.strftime("%Y-%m-%d")
            new = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
            try:
                save_file(root, "shopping.json", new, h, now=now, validate=validate_food)
            except Conflict:
                continue
        break
    else:
        return {"status": "error", "message": "Список меняется параллельно — повторите.",
                "choose": []}

    choose = [{"text": r["text"], "message": r["message"], "candidates": r["candidates"]}
              for r in results if r["status"] == "choose"]
    warn = ("\n⚠ Не учтены числа из фразы: " + ", ".join(x.replace(".", ",") for x in lost)) if lost else ""
    if len(results) == 1:
        r = dict(results[0])
        for k in ("name", "short", "text"):
            r.pop(k, None)
        r["choose"] = choose
        r["message"] += warn
        if lost:
            r["lost_numbers"] = lost
        return r
    out = {"status": "batch", "message": _shop_summary(results) + warn, "choose": choose,
           "items": [{"status": r["status"], "message": r["message"]} for r in results]}
    if lost:
        out["lost_numbers"] = lost
    return out


# ─────────────────── GET /api/moex/quotes — живые цены MOEX ───────────────────
# Прокси к бесплатному ISS (задержка 15 мин) для вьюера портфеля. Отдаёт целые
# доски, а не список тикеров: в запросе нет состава портфеля, поэтому эндпоинт
# публичен (Caddy: /api/moex/*), а кэш общий для всех вкладок и устройств.
# Формат ответа — quotes@1 (tools/design-reference/live-prices-plan.md §2.1);
# правило цены то же, что у загрузчика (_shared-references/moex_quotes.py).
MOEX_BOARDS = {"TQBR": "shares", "TQOB": "bonds", "TQCB": "bonds"}  # доска → market ISS
MOEX_BOND_BOARDS = ("TQOB", "TQCB")   # у облигаций к цене добавлены isin, НКД, номинал и его валюта
MOEX_ISS = ("https://iss.moex.com/iss/engines/stock/markets/{market}/boards/{board}/securities.json"
            "?iss.meta=off&iss.only=securities,marketdata"
            "&securities.columns={seccols}"
            "&marketdata.columns=SECID,LAST,MARKETPRICE,LCURRENTPRICE,UPDATETIME,SYSTIME,TRADINGSTATUS{mdbond}")
MOEX_MD_BOND = ",YIELD,YIELDTOOFFER,DURATION"   # доходность и дюрация облигаций — как их показывает биржа
MOEX_SEC_COLS = "SECID,LOTSIZE,PREVPRICE,PREVDATE"
MOEX_SEC_COLS_BOND = "SECID,ISIN,LOTSIZE,PREVPRICE,PREVDATE,ACCRUEDINT,FACEVALUE,FACEUNIT,CURRENCYID"
MOEX_TIMEOUT = 8
MOEX_DELAYED_MIN = 15
MOEX_TTL_TRADING = 5 * 60       # торговые часы MSK
MOEX_TTL_OFF = 30 * 60          # вне торговых часов
MOEX_STALE_MAX = 24 * 3600      # столько отдаём кэш при упавшем ISS


def _moex_num(v):
    """ISS отдаёт null/0 для «нет данных»: ноль и нецелое трактуем как отсутствие."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _moex_signed(v):
    """Доходность: null и 0 — «нет данных»; отрицательная возможна."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f != 0 else None


def iss_board_to_items(board, iss_json):
    """Ответ ISS по доске → {SECID: item} в формате quotes@1.

    Чистая функция (без сети). Цена: LAST, иначе MARKETPRICE, иначе PREVPRICE
    (метки last / market / prev_close); бумаги без цены не включаются. Доски облигаций
    несут ещё isin, accrued_int (в рублях: валюта торгов), face_value, face_unit,
    currency_id (валюта торгов; SUR — рубли) (зеркало — moex_quotes.board_to_quotes_items), а при цене
    last/market — yield_pct (YIELD биржи, % годовых: к погашению, у бумаг с офертой как показывает биржа),
    yield_offer_pct (YIELDTOOFFER, обычно null) и duration_days (DURATION, дни; null/0 — нет).
    """
    def table(name):
        t = (iss_json or {}).get(name) or {}
        cols = t.get("columns") or []
        return [dict(zip(cols, row)) for row in (t.get("data") or [])]

    md = {r.get("SECID"): r for r in table("marketdata")}
    items = {}
    for sec in table("securities"):
        secid = sec.get("SECID")
        if not secid:
            continue
        m = md.get(secid, {})
        prev = _moex_num(sec.get("PREVPRICE"))
        last, market = _moex_num(m.get("LAST")), _moex_num(m.get("MARKETPRICE"))
        if last is not None:
            price, kind, ts = last, "last", m.get("SYSTIME")
        elif market is not None:
            price, kind, ts = market, "market", m.get("SYSTIME")
        elif prev is not None:
            price, kind, ts = prev, "prev_close", sec.get("PREVDATE")
        else:
            continue
        lot = sec.get("LOTSIZE")
        lot = lot if isinstance(lot, int) and not isinstance(lot, bool) and lot > 0 else None
        items[secid] = {"price": price, "price_kind": kind, "lot_size": lot,
                        "board": board, "ts": ts, "prev_close": prev}
        if board in MOEX_BOND_BOARDS:
            try:
                accrued = float(sec.get("ACCRUEDINT")) if sec.get("ACCRUEDINT") is not None else None
            except (TypeError, ValueError):
                accrued = None
            items[secid].update({"isin": sec.get("ISIN") or None, "accrued_int": accrued,
                                 "face_value": _moex_num(sec.get("FACEVALUE")),
                                 "face_unit": sec.get("FACEUNIT") or None,
                                 "currency_id": sec.get("CURRENCYID") or None})
            # доходность и дюрация — к цене того же момента: у цены «вчерашнее закрытие» они устаревшие — не отдаём
            if kind != "prev_close":
                y, yo, dur = _moex_signed(m.get("YIELD")), _moex_signed(m.get("YIELDTOOFFER")), _moex_num(m.get("DURATION"))
                items[secid].update({"yield_pct": y, "yield_offer_pct": yo,
                                     "duration_days": int(dur) if dur is not None else None})
    return items


def moex_is_trading(now):
    """Будни 07:00–23:50 MSK (расписание с утренней и вечерней сессиями)."""
    now = now.astimezone(MSK)
    if now.weekday() >= 5:
        return False
    return (7, 0) <= (now.hour, now.minute) < (23, 50)


def moex_ttl(now):
    return MOEX_TTL_TRADING if moex_is_trading(now) else MOEX_TTL_OFF


def moex_fetch_board(board):
    """Сырой JSON ISS по доске (ходит в сеть; в тестах подменяется)."""
    url = MOEX_ISS.format(market=MOEX_BOARDS[board], board=board,
                          seccols=MOEX_SEC_COLS_BOND if board in MOEX_BOND_BOARDS else MOEX_SEC_COLS,
                          mdbond=MOEX_MD_BOND if board in MOEX_BOND_BOARDS else "")
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip",
                                               "Accept": "application/json",
                                               "User-Agent": "hub-api/1.0"})
    with urllib.request.urlopen(req, timeout=MOEX_TIMEOUT) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


_MOEX_CACHE = {}    # board → {"items", "fetched": epoch, "fetched_at": iso}
_MOEX_LOCKS = {board: threading.Lock() for board in MOEX_BOARDS}


class MoexError(Exception):
    pass


def moex_board(board, now=None):
    """→ (entry, stale). Кэш по доске; параллельные запросы склеены lock'ом.

    Свежий кэш (TTL по расписанию) → без сети. Иначе одна выборка, остальные
    ждут на lock'е и берут её результат. ISS упал: кэш моложе 24 ч → (entry,
    True); кэша нет или он старше → MoexError.
    """
    now = now or datetime.now(MSK)
    ts = now.timestamp()
    ent = _MOEX_CACHE.get(board)
    if ent and ts - ent["fetched"] < moex_ttl(now):
        return ent, False
    with _MOEX_LOCKS[board]:
        ent = _MOEX_CACHE.get(board)
        if ent and ts - ent["fetched"] < moex_ttl(now):   # успели, пока ждали lock
            return ent, False
        try:
            items = iss_board_to_items(board, moex_fetch_board(board))
            if not items:
                raise ValueError("ISS вернул пустую доску")
        except Exception as e:      # сеть, таймаут, битый JSON — одинаково «ISS упал»
            if ent and ts - ent["fetched"] < MOEX_STALE_MAX:
                return ent, True
            raise MoexError(f"{board}: {type(e).__name__}: {e}")
        ent = {"items": items, "fetched": ts,
               "fetched_at": _now_iso(now)}
        _MOEX_CACHE[board] = ent
        return ent, False


CBR_DAILY_URL = "https://www.cbr.ru/scripts/XML_daily.asp"
FX_TTL = 24 * 3600              # курс ЦБ меняется раз в сутки
FX_STALE_MAX = 7 * 24 * 3600    # столько отдаём прошлый курс при недоступном cbr.ru
_FX_CACHE = {}                  # {"fx": {...}, "fetched": epoch}
_FX_LOCK = threading.Lock()


def cbr_xml_to_fx(xml_text, currencies=None):
    """XML_daily ЦБ → {"USD": руб/ед, "KZT": …, "date": "YYYY-MM-DD"} или None (нет даты / ни одной валюты).
    Курс = Value / Nominal (KZT — за 100). currencies=None — все валюты ответа; иначе только перечисленные
    (не найденных у ЦБ в результате нет). Зеркало — moex_quotes.cbr_xml_to_fx."""
    m = re.search(r'<ValCurs[^>]*\bDate="(\d{2})\.(\d{2})\.(\d{4})"', xml_text or "")
    if not m:
        return None
    want = None if currencies is None else set(currencies)
    out = {}
    for v in re.finditer(r"<CharCode>([A-Z]{3})</CharCode>\s*<Nominal>(\d+)</Nominal>.*?<Value>([\d,\.]+)</Value>",
                         xml_text, re.S):
        code = v.group(1)
        if want is not None and code not in want:
            continue
        rate = float(v.group(3).replace(",", ".")) / int(v.group(2))
        if rate > 0:
            out[code] = rate
    if not out:
        return None
    out["date"] = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return out


FX_CODE_RE = re.compile(r"^[A-Z]{3}$")
FX_MAX_CODES = 10


def parse_fx_param(raw):
    """Параметр fx=USD,EUR,KZT → список кодов или None (параметра нет). ValueError — невалидный."""
    if raw is None:
        return None
    codes = list(dict.fromkeys(c.strip().upper() for c in raw.split(",") if c.strip()))
    if not codes or len(codes) > FX_MAX_CODES or any(not FX_CODE_RE.match(c) for c in codes):
        raise ValueError("bad fx")
    return codes


def fx_pick(fx_all, codes):
    """Из полного среза ЦБ — только запрошенные валюты (+date) или None, если ни одной."""
    if not fx_all or not codes:
        return None
    out = {c: fx_all[c] for c in codes if c in fx_all and c != "date"}
    if not out:
        return None
    out["date"] = fx_all["date"]
    return out


def cbr_fetch_xml():
    """Сырой XML ЦБ (ходит в сеть; в тестах подменяется)."""
    req = urllib.request.Request(CBR_DAILY_URL, headers={"User-Agent": "hub-api/1.0"})
    with urllib.request.urlopen(req, timeout=MOEX_TIMEOUT) as r:
        return r.read().decode("windows-1251", errors="replace")


def moex_fx(now=None):
    """Полный срез курсов ЦБ (все валюты) или None; фильтрация на выдаче — fx_pick. Кэш на сутки; cbr.ru упал — прошлый курс моложе 7 дней,
    иначе None (облигации в валюте остаются по снапшоту)."""
    now = now or datetime.now(MSK)
    ts = now.timestamp()
    ent = _FX_CACHE.get("e")
    if ent and ts - ent["fetched"] < FX_TTL:
        return ent["fx"]
    with _FX_LOCK:
        ent = _FX_CACHE.get("e")
        if ent and ts - ent["fetched"] < FX_TTL:
            return ent["fx"]
        try:
            fx = cbr_xml_to_fx(cbr_fetch_xml())
            if not fx:
                raise ValueError("нет курсов в ответе ЦБ")
        except Exception:
            return ent["fx"] if ent and ts - ent["fetched"] < FX_STALE_MAX else None
        _FX_CACHE["e"] = {"fx": fx, "fetched": ts}
        return fx


def moex_quotes(boards, now=None, fx=None):
    """boards: список досок из белого списка → quotes@1. MoexError, если доска не получена.
    fx — коды валют (параметр fx=USD,KZT): блок fx только с ними (+date), нет курса — блока нет;
    без fx блока нет."""
    now = now or datetime.now(MSK)
    out_boards, items, stale = {}, {}, False
    for b in boards:
        ent, st = moex_board(b, now)
        out_boards[b] = {"fetched_at": ent["fetched_at"], "stale": st}
        items.update(ent["items"])
        stale = stale or st
    out = {"schema": "quotes@1",
           "fetched_at": min(v["fetched_at"] for v in out_boards.values()),
           "source": "moex_iss", "delayed_min": MOEX_DELAYED_MIN,
           "stale": stale, "boards": out_boards, "items": items}
    if fx:
        blk = fx_pick(moex_fx(now), fx)
        if blk:
            out["fx"] = blk
    return out


# ─────────────────── /api/pv/plan — план портфеля (Portfolio/plan.json) ───────────────────
# Единственный писатель плана (этап 2 numbers-exit-plan.md). Правка — по одному полю за запрос,
# с base_hash (поле или пакет до 50 полей одной записью файла); каждая правка дописывается в журнал
# plan-journal.jsonl (только дописывание).
PLAN_FILE = "Portfolio/plan.json"


def _load_codelists():
    """Кодлисты (`codelists.json`, schema.md §3.4): рядом с server.py (deploy кладёт его в _nas/api/, compose
    монтирует в /app), иначе канон репозитория `_shared-references/`, иначе копия на томе (`<ROOT>/_nas/api/` —
    если контейнер перезапущен без пересоздания и /app/codelists.json ещё не смонтирован). Нет файла — пустые
    перечни: запись user_plan/статуса плана отклоняется, остальной API работает (ошибка — в лог)."""
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "codelists.json"),
                 os.path.normpath(os.path.join(here, "..", "..", "..", "_shared-references", "codelists.json")),
                 os.path.join(ROOT, "_nas", "api", "codelists.json")):
        try:
            with open(cand, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            continue
    print("hub-api: codelists.json не найден — план: перечни user_plan/user_status пусты", flush=True)
    return {"lists": {}}


_CODELISTS = _load_codelists()


def _cl_words(name):
    """{код: слово} кодлиста в каноническом порядке."""
    return {c: e.get("ru") for c, e in (_CODELISTS.get("lists", {}).get(name) or {}).items()}


PLAN_JOURNAL = "Portfolio/plan-journal.jsonl"
PLAN_STOCK_FIELDS = ("plan_pct", "user_plan", "user_status", "note_ie", "note_ai", "ie_new_pct", "ie_old_pct")
PLAN_USER_PLANS = tuple(_cl_words("user_plan"))   # кодлист user_plan
PLAN_TEXT_MAX = 500
PLAN_REASON_MAX = 1000
PLAN_BATCH_MAX = 50
PLAN_STATUS_CODES = tuple(_cl_words("user_status"))   # кодлист user_status
PLAN_STATUS_MAX = 120
_plan_lock = threading.Lock()   # весь цикл «прочитать → записать → журнал»; файловые операции берут _write_lock сами


def _plan_pct(v):
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or not 0 <= v <= 100:
        raise ValueError("число от 0 до 100 или null")
    return v


def _plan_choice(v):
    if v is None:
        return None
    if v not in PLAN_USER_PLANS:
        raise ValueError("одна из " + "/".join(PLAN_USER_PLANS) + " или null")
    return v


def _plan_text(v):
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError("строка или null")
    v = v.strip()
    if len(v) > PLAN_TEXT_MAX:
        raise ValueError(f"не длиннее {PLAN_TEXT_MAX} символов")
    return v or None


def _plan_status(v):
    """Код из PLAN_STATUS_CODES или произвольная строка ≤120 (старые значения из Numbers) или null."""
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError("код статуса, строка или null")
    v = v.strip()
    if len(v) > PLAN_STATUS_MAX:
        raise ValueError(f"не длиннее {PLAN_STATUS_MAX} символов")
    return v or None


PLAN_CLASSES = ("Акции", "Облигация", "Золото", "Другое", "Кеш")                 # классы целей (classes[])
PLAN_MATRIX_CLASSES = ("Кеш", "Акция", "Облигация", "Золото", "Другое")           # в матрице акции — «Акция», как в Numbers
PLAN_CURRENCIES = ("RUB", "USD", "EUR", "CNY")
PLAN_BUCKET_KEYS = ("USD", "EUR", "CNY", "ОФЗ/>10", "ОФЗ/<10", "ОФЗ/Флоат", "КОРП/AA+", "КОРП/A", "КОРП/B+")
PLAN_BOND_TYPES = ("ОФЗ", "КОРП", "USD", "EUR", "CNY")
PLAN_BOND_SUBTYPES = (">10", "<10", "Флоат", "AA+", "A", "B+")
PLAN_BOND_ACTION_MAX = 200
PLAN_BOND_RATING_MAX = 40
PLAN_FUND_FIELDS = ("class", "currency", "in_rebalance", "bucket", "note", "fee_pct", "spread_pct")


class PlanShape(Exception):
    """Раздел plan.json имеет не тот тип, чтобы в него писать (→ 500 plan invalid)."""


def _plan_share(v):
    """Доля единицы 0..1 (не проценты) или null."""
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or not 0 <= v <= 1:
        raise ValueError("число от 0 до 1 (доля единицы) или null")
    return v


def _plan_enum(options):
    def check(v):
        if v is None:
            return None
        if not isinstance(v, str) or v not in options:
            raise ValueError("одно из " + "/".join(options) + " или null")
        return v
    return check


def _plan_str(maxlen):
    def check(v):
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("строка или null")
        v = v.strip()
        if len(v) > maxlen:
            raise ValueError(f"не длиннее {maxlen} символов")
        return v or None
    return check


def _plan_nonneg_int(v):
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise ValueError("целое число ≥ 0 или null")
    return v


def _plan_nonneg_num(v):
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v < 0:
        raise ValueError("число ≥ 0 или null")
    return v


def _plan_bool(v):
    if v is None:
        return None
    if not isinstance(v, bool):
        raise ValueError("true, false или null")
    return v


def _plan_row(plan, section, match, make):
    """Строка списка plan[section] с match(row) → True; нет — создаётся make() и добавляется. Раздела нет — создаётся []."""
    rows = plan.setdefault(section, [])
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise PlanShape(f"{section} — не список объектов")
    for r in rows:
        if match(r):
            return r
    r = make()
    rows.append(r)
    return r


def _plan_dict_rec(plan, section, key, make):
    d = plan.setdefault(section, {})
    if not isinstance(d, dict):
        raise PlanShape(f"{section} — не объект")
    rec = d.get(key)
    if rec is None:
        rec = d[key] = make()
    elif not isinstance(rec, dict):
        raise PlanShape(f"{section}.{key} — не объект")
    return rec


def _set_field(rec, field, val):
    was = rec.get(field)
    rec[field] = val
    return was


def _ap_stock(plan, m, val):
    return _set_field(_plan_dict_rec(plan, "stocks", m.group(1), lambda: {f: None for f in PLAN_STOCK_FIELDS}), m.group(2), val)


def _ap_class(plan, m, val):
    cls = m.group(1)
    return _set_field(_plan_row(plan, "classes", lambda r: r.get("class") == cls, lambda: {"class": cls, "share": None}), "share", val)


def _ap_matrix(plan, m, val):
    cur, cls = m.group(1), m.group(2)
    row = _plan_row(plan, "matrix", lambda r: r.get("currency") == cur and r.get("class") == cls,
                    lambda: {"currency": cur, "class": cls, "share": None})
    return _set_field(row, "share", val)


def _ap_bucket(plan, m, val):
    key = m.group(1)
    typ, _, sub = key.partition("/")
    row = _plan_row(plan, "bond_buckets", lambda r: r.get("key") == key,
                    lambda: {"key": key, "type": typ, "subtype": sub or None, "share": None})
    return _set_field(row, "share", val)


def _ap_bond(plan, m, val):
    rec = _plan_dict_rec(plan, "bonds", m.group(1), lambda: {"name": None, "type": None, "subtype": None,
                                                              "rating": None, "action": None, "iis_qty": None})
    return _set_field(rec, m.group(2), val)


def _ap_fund(plan, m, val):
    rec = _plan_dict_rec(plan, "funds", m.group(1), lambda: {f: None for f in PLAN_FUND_FIELDS})
    return _set_field(rec, m.group(2), val)


def _ap_manual(plan, m, val):
    typ, name = m.group(1), m.group(2)
    row = _plan_row(plan, "manual_positions", lambda r: r.get("type") == typ and r.get("name") == name,
                    lambda: {"type": typ, "name": name, "value_rub": None})
    was = _set_field(row, "value_rub", val)
    row["value_as_of"] = "@today"            # метка; ниже заменяется датой updated_at (дата сервера)
    return was


def _alt(options):
    return "(" + "|".join(re.escape(o) for o in options) + ")"


_PLAN_TICKER = r"([A-Z0-9][A-Z0-9_.-]{0,15})"
# (regex пути, validator значения, applier(plan, match, value) → was) — этап 3 (IE) пишет через ie-set, не здесь
PLAN_PATH_RULES = [
    (re.compile(rf"^stocks\.{_PLAN_TICKER}\.(plan_pct)$"), _plan_pct, _ap_stock),
    (re.compile(rf"^stocks\.{_PLAN_TICKER}\.(user_plan)$"), _plan_choice, _ap_stock),
    (re.compile(rf"^stocks\.{_PLAN_TICKER}\.(user_status)$"), _plan_status, _ap_stock),
    (re.compile(rf"^stocks\.{_PLAN_TICKER}\.(note_ie|note_ai)$"), _plan_text, _ap_stock),
    # этап 4: классы, матрица, корзины, облигации, фонды, ручные позиции (элементы списков — по ключу)
    (re.compile(rf"^classes\.{_alt(PLAN_CLASSES)}\.share$"), _plan_share, _ap_class),
    (re.compile(rf"^matrix\.{_alt(PLAN_CURRENCIES)}/{_alt(PLAN_MATRIX_CLASSES)}\.share$"), _plan_share, _ap_matrix),
    (re.compile(rf"^bond_buckets\.{_alt(PLAN_BUCKET_KEYS)}\.share$"), _plan_share, _ap_bucket),
    (re.compile(r"^bonds\.([A-Z0-9]{12})\.(type)$"), _plan_enum(PLAN_BOND_TYPES), _ap_bond),
    (re.compile(r"^bonds\.([A-Z0-9]{12})\.(subtype)$"), _plan_enum(PLAN_BOND_SUBTYPES), _ap_bond),
    (re.compile(r"^bonds\.([A-Z0-9]{12})\.(rating)$"), _plan_str(PLAN_BOND_RATING_MAX), _ap_bond),
    (re.compile(r"^bonds\.([A-Z0-9]{12})\.(action)$"), _plan_str(PLAN_BOND_ACTION_MAX), _ap_bond),
    (re.compile(r"^bonds\.([A-Z0-9]{12})\.(iis_qty)$"), _plan_nonneg_int, _ap_bond),
    (re.compile(r"^bonds\.([A-Z0-9]{12})\.(manual)$"), _plan_bool, _ap_bond),
    (re.compile(r"^bonds\.([A-Z0-9]{12})\.(reason)$"), _plan_str(PLAN_BOND_ACTION_MAX), _ap_bond),
    (re.compile(rf"^funds\.{_PLAN_TICKER}\.(class)$"), _plan_enum(PLAN_CLASSES), _ap_fund),
    (re.compile(rf"^funds\.{_PLAN_TICKER}\.(currency)$"), _plan_enum(PLAN_CURRENCIES), _ap_fund),
    (re.compile(rf"^funds\.{_PLAN_TICKER}\.(in_rebalance)$"), _plan_bool, _ap_fund),
    (re.compile(rf"^funds\.{_PLAN_TICKER}\.(bucket)$"), _plan_enum(PLAN_BUCKET_KEYS), _ap_fund),
    (re.compile(rf"^funds\.{_PLAN_TICKER}\.(note)$"), _plan_text, _ap_fund),
    (re.compile(rf"^funds\.{_PLAN_TICKER}\.(fee_pct|spread_pct)$"), _plan_nonneg_num, _ap_fund),
    (re.compile(r"^manual_positions\.([^.]+)/([^.]+)\.value_rub$"), _plan_nonneg_num, _ap_manual),
]


def plan_read(root):
    """→ (plan, hash). FileNotFoundError — плана нет; ValueError — битый JSON / не объект."""
    text, h = read_file(root, PLAN_FILE)
    plan = json.loads(text)
    if not isinstance(plan, dict):
        raise ValueError("корень плана — не объект")
    return plan, h


def plan_dump(plan):
    return json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _plan_get(plan, parts):
    cur = plan
    for p in parts:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


# ───────────── режим сайта «с ИИ / без ИИ» — Claude-Memory/_hub/settings.json (hub-settings@1) ─────────────
# Единственный писатель файла — hub-api (эти ручки); читают страницы (ui-kit), hub-notify (с NAS напрямую)
# и скрипты-писатели Mac (через зеркало, `_shared-references/hub_settings.py`). Нет файла — режим `on`.
HUB_SETTINGS_FILE = "_hub/settings.json"
HUB_SETTINGS_SCHEMA = "hub-settings@1"
HUB_AI_MODES = ("on", "off")
HUB_SETTINGS_TEXT_MAX = 200


def hub_settings_default():
    return {"schema": HUB_SETTINGS_SCHEMA, "ai_mode": "on", "off_since": None, "returned_at": None,
            "by": None, "note": None, "updated_at": None}


def validate_hub_settings(relpath, content):
    """Схема hub-settings@1; ValueError с текстом — файл не пишется."""
    try:
        doc = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"не разбирается как JSON: {e}")
    if not isinstance(doc, dict):
        raise ValueError("корень должен быть объектом")
    if doc.get("schema") != HUB_SETTINGS_SCHEMA:
        raise ValueError(f"schema должна быть {HUB_SETTINGS_SCHEMA!r}, получено {doc.get('schema')!r}")
    if doc.get("ai_mode") not in HUB_AI_MODES:
        raise ValueError(f"ai_mode — одно из {', '.join(HUB_AI_MODES)}, получено {doc.get('ai_mode')!r}")
    for k in ("off_since", "returned_at", "updated_at"):
        v = doc.get(k)
        if v is not None and not (isinstance(v, str) and _CSTATE_DATE_RE.match(v)):
            raise ValueError(f"{k} — время «ГГГГ-ММ-ДДTЧЧ:ММ:СС+03:00» или null")
    for k in ("by", "note"):
        v = doc.get(k)
        if v is not None and not (isinstance(v, str) and len(v) <= HUB_SETTINGS_TEXT_MAX):
            raise ValueError(f"{k} — строка до {HUB_SETTINGS_TEXT_MAX} знаков или null")
    unknown = set(doc) - set(hub_settings_default())
    if unknown:
        raise ValueError(f"неизвестные поля: {', '.join(sorted(unknown))}")


def hub_settings_read(root):
    """→ (settings, hash). Нет файла — настройки по умолчанию и hash None (режим `on`)."""
    full = os.path.join(root, HUB_SETTINGS_FILE)
    try:
        with open(full, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        return hub_settings_default(), None
    validate_hub_settings(HUB_SETTINGS_FILE, raw.decode("utf-8"))   # ValueError → 500 выше: битый файл не затираем молча
    return json.loads(raw.decode("utf-8")), file_hash(raw)


def hub_settings_apply(current, incoming, now_iso):
    """Чистый переход режима: on→off ставит off_since и обнуляет returned_at; off→on ставит returned_at,
    off_since остаётся (по нему считают правки сайта за период «без ИИ»); тот же режим — только by/note.
    ValueError на неверный вход."""
    if not isinstance(incoming, dict):
        raise ValueError("settings — объект")
    mode = incoming.get("ai_mode")
    if mode not in HUB_AI_MODES:
        raise ValueError(f"ai_mode — одно из {', '.join(HUB_AI_MODES)}")
    unknown = set(incoming) - {"ai_mode", "by", "note", "schema"}
    if unknown:
        raise ValueError(f"settings: поля {', '.join(sorted(unknown))} ставит сервер")
    for k in ("by", "note"):
        v = incoming.get(k)
        if v is not None and not (isinstance(v, str) and len(v) <= HUB_SETTINGS_TEXT_MAX):
            raise ValueError(f"{k} — строка до {HUB_SETTINGS_TEXT_MAX} знаков или null")
    new = dict(current)
    if current.get("ai_mode") == "on" and mode == "off":
        new["off_since"], new["returned_at"] = now_iso, None
    elif current.get("ai_mode") == "off" and mode == "on":
        new["returned_at"] = now_iso
    new.update(schema=HUB_SETTINGS_SCHEMA, ai_mode=mode, by=incoming.get("by") or "site",
               note=incoming.get("note"), updated_at=now_iso)
    return new


def hub_settings_get(root):
    """→ (код, тело) для GET /api/hub/settings: {path, hash, settings}; hash null — файла ещё нет."""
    try:
        settings, h = hub_settings_read(root)
    except (ValueError, OSError) as e:
        return 500, {"error": "settings invalid", "detail": str(e)}
    return 200, {"path": HUB_SETTINGS_FILE, "hash": h, "settings": settings}


def hub_settings_post(root, body, now=None):
    """→ (код, тело) для POST /api/hub/settings {settings: {ai_mode, by?, note?}, base_hash}.
    base_hash null допустим только пока файла нет; расхождение → 409 с current_hash и текущими настройками."""
    if not isinstance(body, dict) or "settings" not in body or "base_hash" not in body:
        return 400, {"error": "bad request body", "detail": "нужны settings и base_hash"}
    try:
        current, h = hub_settings_read(root)
    except (ValueError, OSError) as e:
        return 500, {"error": "settings invalid", "detail": str(e)}
    if body["base_hash"] != h:
        return 409, {"error": "conflict", "current_hash": h, "settings": current}
    try:
        new = hub_settings_apply(current, body["settings"], _now_iso(now))
    except ValueError as e:
        return 400, {"error": "bad settings", "detail": str(e)}
    content = json.dumps(new, ensure_ascii=False, indent=2) + "\n"
    try:
        new_hash = save_file(root, HUB_SETTINGS_FILE, content, h, now, validate=validate_hub_settings)
    except Conflict as c:
        cur, _ = hub_settings_read(root)
        return 409, {"error": "conflict", "current_hash": c.current_hash, "settings": cur}
    except ValueError as e:
        return 400, {"error": "bad settings", "detail": str(e)}
    return 200, {"path": HUB_SETTINGS_FILE, "hash": new_hash, "settings": new}


# ───────────── правки на NAS за период — GET /api/hub/changes?since= (сверка зеркала Mac, noai_return.py) ─────────────
HUB_CHANGE_ZONES = ("Portfolio", "scenarios", "macro-snapshots", "Gaming", "Health", "ZenMoney", "travel-planner", "_hub")   # всё, что пишет сайт
HUB_CHANGES_MAX = 5000
_HUB_SKIP_DIRS = {VERSIONS_DIR, ".backups", ".intake-backups", "__pycache__"}


def _hub_since(since):
    """Строка since → datetime МСК или ValueError."""
    if not isinstance(since, str) or not _CSTATE_DATE_RE.match(since):
        raise ValueError("since: ожидается время «ГГГГ-ММ-ДДTЧЧ:ММ[:СС][+03:00]»")
    t = datetime.fromisoformat(since.replace("Z", "+00:00"))
    return t.replace(tzinfo=MSK) if t.tzinfo is None else t.astimezone(MSK)


def hub_changes(root, since=None, zones=HUB_CHANGE_ZONES, max_files=HUB_CHANGES_MAX):
    """→ (код, тело) {since, generated_at, zones, files: [{path, size, mtime, sha256?}], truncated}.
    С `since` — только файлы с mtime позже него, каждый с sha256 (зеркало сверяет содержимое); без `since` —
    все файлы зон с размером и временем, без хэшей (дёшево). Копии `.versions/`, `.backups/`, скрытые имена
    и `*.tmp` не считаются правками. Больше max_files — список обрезан, `truncated: true`."""
    try:
        cutoff = _hub_since(since) if since else None
    except ValueError as e:
        return 400, {"error": "bad since", "detail": str(e)}
    files, truncated = [], False
    for zone in zones:
        base = os.path.join(root, zone)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in _HUB_SKIP_DIRS and not d.startswith("."))
            for name in sorted(filenames):
                if name.startswith(".") or name.endswith(".tmp"):
                    continue
                full = os.path.join(dirpath, name)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                mt = datetime.fromtimestamp(st.st_mtime, MSK)
                if cutoff is not None and mt <= cutoff:
                    continue
                if len(files) >= max_files:
                    truncated = True
                    break
                rel = os.path.relpath(full, root).replace(os.sep, "/")
                item = {"path": rel, "size": st.st_size, "mtime": _now_iso(mt)}
                if cutoff is not None:
                    try:
                        with open(full, "rb") as f:
                            item["sha256"] = file_hash(f.read())
                    except OSError:
                        item["sha256"] = None
                files.append(item)
            if truncated:
                break
        if truncated:
            break
    return 200, {"since": since, "generated_at": _now_iso(), "zones": list(zones), "files": files,
                 "truncated": truncated}


def plan_get(root):
    """→ (код, тело) для GET /api/pv/plan."""
    try:
        plan, h = plan_read(root)
    except FileNotFoundError:
        return 404, {"error": "not found"}
    except (ValueError, OSError) as e:
        return 500, {"error": "plan invalid", "detail": str(e)}
    return 200, {"path": PLAN_FILE, "hash": h, "plan": plan}


_journal_state = {"running": False, "dirty": False, "data": None}   # под _write_lock; носитель журнала плана
_cstate_state = {"running": False, "dirty": False, "data": None}    # носитель conditions-state.json


def _deliver_loop(root, full, relpath, state):
    """Фон: перенести полный файл через _place (File Station; сам откатывается на локальную запись и
    считает FS_STATS). Носитель один на файл: пока он идёт, запись лишь обновляет state["data"] (актуальное
    содержимое в памяти) и ставит dirty; по окончании переноса носитель берёт свежие data. Перенос
    перезаписывает файл содержимым, собранным ДО него, поэтому базой для следующей записи служит data,
    а не файл, — иначе запись, сделанная во время переноса, потерялась бы."""
    while True:
        with _write_lock:
            if not state["dirty"]:
                state.update(running=False, data=None)
                return
            state["dirty"] = False
            data = state["data"]
        try:
            _place(root, relpath, full, data)         # вне замка: перенос через DSM занимает секунды
        except Exception as e:  # noqa: BLE001 — локальный файл уже записан, форму не роняем
            print(f"deliver {relpath}: {e}", flush=True)


def _journal_deliver(root, full, relpath):
    _deliver_loop(root, full, relpath, _journal_state)


def _write_and_deliver(root, relpath, state, build):
    """Изменить файл: build(старые_байты) → (новые_байты | None, результат); None — писать нечего.
    Локально — сразу и под замком (форма не ждёт DSM: перенос стоил 3–5 с); в зеркала Мака файл уезжает
    фоновым потоком (_deliver_loop). Базой служит содержимое в памяти, пока идёт перенос. → результат."""
    full = os.path.join(root, relpath)
    with _write_lock:
        if state["running"]:
            old = state["data"]
        else:
            try:
                with open(full, "rb") as f:
                    old = f.read()
            except FileNotFoundError:
                old = b""
        data, result = build(old)
        if data is None:
            return result
        if not old:
            _makedirs_owned(root, os.path.dirname(full))
        tmp = full + ".hub-api-tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, full)
        _chown_quiet(full)
        state.update(dirty=True, data=data)
        if state["running"]:
            return result
        state["running"] = True
    threading.Thread(target=_deliver_loop, args=(root, full, relpath, state), daemon=True).start()
    return result


def append_plan_journal(root, entry):
    """Дописать строку (или список строк) в Portfolio/plan-journal.jsonl (только дописывание)."""
    entries = entry if isinstance(entry, list) else [entry]
    blob = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries).encode("utf-8")
    _write_and_deliver(root, PLAN_JOURNAL, _journal_state, lambda old: (old + blob, None))


# ─────────────────── /api/pv/cond/* — состояние условий (Portfolio/conditions-state.json) ───────────────────
# conditions-state@1 (schema.md §3.3): только дописывание событий, единственный писатель — hub-api.
# Сайт (владелец) — /cond/event; hub-notify — /cond/event/internal. Определения условий (conditions.yaml)
# сервер не пишет; читает построчно только для кнопки «вышел» (event_found от владельца, R32): тип триггера,
# окно, срок и снятие последней версии. Остальное — форма записи: коды кодлистов, обязательные поля, until.
CSTATE_FILE = "Portfolio/conditions-state.json"
CSTATE_SCHEMA = "conditions-state@1"
CSTATE_SITE_EVENTS = ("owner_mark", "done", "reopened", "event_found")
CDEFS_FILE = "Portfolio/conditions.yaml"
CSTATE_FOUND_TRIGGERS = ("report_published", "event")   # «вышел» владельцем — только у этих триггеров
CSTATE_INTERNAL_EVENTS = ("fired", "expired", "event_found", "done")
CSTATE_SITE_MARKS = ("dismissed", "deferred")
CSTATE_INTERNAL_ACTORS = ("notifier", "site", "script", "decision")   # decision — done по новому решению (hub-notify)
CSTATE_FIELD_MAX = 500
_CSTATE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?([+-]\d{2}:\d{2}|Z)?)?$")


def _cstate_parse(raw):
    """байты файла → список событий; пусто → []; битый файл → ValueError (не затираем молча)."""
    if not raw.strip():
        return []
    obj = json.loads(raw.decode("utf-8"))
    if not isinstance(obj, dict) or not isinstance(obj.get("events"), list):
        raise ValueError("conditions-state.json: нет events[]")
    return obj["events"]


def _cstate_dup(events, cid, version, event, data=None):
    """Повтор на внутреннем маршруте: для пары condition_id + version уже есть такое незакрытое событие или
    состояние терминально. Цепочка считается после последнего reopened; терминальные — done, expired,
    owner_mark dismissed. fired — дубль, пока прежний fired не закрыт; expired и done — дубль при любом
    терминальном; event_found — дубль при терминальном или если находка с тем же data.doc уже есть.
    Сайт этим не ограничен: его события пишутся всегда."""
    fired = terminal = False
    docs = set()
    for e in events:
        if not isinstance(e, dict) or e.get("condition_id") != cid or e.get("version") != version:
            continue
        ev = e.get("event")
        if ev == "reopened":
            fired = terminal = False
            docs = set()
        elif ev == "fired":
            fired = True
        elif ev == "event_found":
            docs.add((e.get("data") or {}).get("doc"))
            if e.get("by") == "owner":   # «вышел» владельцем = сработало (модуль (а), правило 5)
                fired = True
        elif ev in ("done", "expired") or (ev == "owner_mark" and (e.get("data") or {}).get("mark") == "dismissed"):
            terminal = True
    if terminal:
        return True
    if event == "fired":
        return fired
    if event == "event_found":
        return (data or {}).get("doc") in docs
    return False


def _yaml_scalar(v):
    v = v.split(" #", 1)[0].strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        v = v[1:-1].replace("''", "'") if v[0] == "'" else v[1:-1]
    return None if v in ("", "null", "~") else v


def cond_def_brief(text, cid):
    """Последняя версия определения `cid` в conditions.yaml (запись apply_condition.py: элементы `- id:` в колонке 0,
    поля с отступом 2, поля trigger/withdrawn — 4) построчно, без PyYAML → {version, type, window_end, valid_until,
    created_at, withdrawn} или None. Только для проверки кнопки «вышел»; смысл условий сервер не трактует."""
    items, cur, sect = [], None, None
    for line in text.splitlines():
        if line.startswith("- id:"):
            cur = {"id": _yaml_scalar(line[5:]), "version": None, "type": None, "window_end": None,
                   "valid_until": None, "created_at": None, "withdrawn": False}
            items.append(cur)
            sect = None
            continue
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            cur = None
            continue
        if cur is None or ":" not in line:
            continue
        indent = len(line) - len(line.lstrip(" "))
        k, _, v = line.strip().partition(":")
        if indent == 2:
            raw = v.split(" #", 1)[0].strip()
            sect, v = k, _yaml_scalar(v)
            if k == "version":
                cur["version"] = int(v) if v and v.isdigit() else None
            elif k in ("valid_until", "created_at"):
                cur[k] = v
            elif k == "withdrawn":
                cur["withdrawn"] = raw not in ("null", "~")   # «withdrawn:» с записью ниже или {…} — снято
        elif indent == 4 and sect == "trigger" and k in ("type", "window_end"):
            cur[k] = _yaml_scalar(v)
    best = None
    for it in items:
        if it["id"] == cid and isinstance(it["version"], int) and (best is None or it["version"] > best["version"]):
            best = it
    return best


def cond_found_check(root, cid, version, events, today):
    """Кнопка «вышел» (event_found от владельца): ошибка-текст или None. Условие ждёт (pending по модулю (а):
    после последнего reopened нет fired, done, expired, dismissed и «вышел»; окно и срок не прошли), не снято,
    триггер report_published или event, version (если задана) = последней."""
    try:
        with open(os.path.join(root, CDEFS_FILE), encoding="utf-8") as f:
            d = cond_def_brief(f.read(), cid)
    except (OSError, UnicodeDecodeError):
        d = None
    if d is None:
        return f"условие {cid} не найдено в {CDEFS_FILE}"
    if version is not None and version != d["version"]:
        return f"version {version}: последняя версия условия — {d['version']}"
    if d["type"] not in CSTATE_FOUND_TRIGGERS:
        return f"«вышел» — только у условий с триггером {', '.join(CSTATE_FOUND_TRIGGERS)} (у этого {d['type']})"
    if d["withdrawn"]:
        return "условие снято"
    if d["type"] == "report_published" and d["window_end"] and d["window_end"] < today:
        return "окно отчёта прошло — условие уже сработало по сроку"
    if d["valid_until"] and d["valid_until"] < today:
        return "срок условия вышел"
    since = d["created_at"] or ""
    live = "pending"
    for e in events:
        if not isinstance(e, dict) or e.get("condition_id") != cid or str(e.get("at") or "") < since:
            continue
        ev = e.get("event")
        if ev == "reopened":
            live = "pending"
        elif ev in ("fired", "done", "expired") or (ev == "owner_mark" and (e.get("data") or {}).get("mark") == "dismissed") \
                or (ev == "event_found" and e.get("by") == "owner"):
            live = "closed"
    return None if live == "pending" else "условие уже не ждёт (сработало или закрыто)"


def cond_event_check(body, internal):
    """→ (None, событие-без-времени) или (ошибка-текст, None). Форма записи; смысл условий не проверяется."""
    cid, event, data = body.get("condition_id"), body.get("event"), body.get("data", {})
    version = body.get("version")
    if not isinstance(cid, str) or not cid.strip() or len(cid) > 120:
        return "condition_id: нужна непустая строка", None
    if not isinstance(event, str) or event not in _cl_words("condition_event"):
        return f"event: неизвестное событие {event!r}", None
    allowed = CSTATE_INTERNAL_EVENTS if internal else CSTATE_SITE_EVENTS
    if event not in allowed:
        return f"event {event!r} этим маршрутом писать нельзя (разрешены: {', '.join(allowed)})", None
    if version is not None and (isinstance(version, bool) or not isinstance(version, int) or version < 1):
        return "version: целое от 1 или не задавать", None
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return "data: нужен объект", None
    if any(isinstance(v, str) and len(v) > CSTATE_FIELD_MAX for v in data.values()):
        return f"data: строка длиннее {CSTATE_FIELD_MAX} знаков", None
    if event == "owner_mark":
        mark = data.get("mark")
        if mark not in _cl_words("owner_mark") or mark not in CSTATE_SITE_MARKS:
            return f"data.mark: допустимы {', '.join(CSTATE_SITE_MARKS)}", None
        if mark == "deferred":
            until = data.get("until")
            if not isinstance(until, str) or not _CSTATE_DATE_RE.match(until):
                return "data.until: у deferred обязательна дата «ГГГГ-ММ-ДД»", None
    if internal:
        by = body.get("by")
        if event == "done":
            by = by or "site"
            if by not in ("site", "decision"):
                return "done по внутреннему маршруту пишется с by: site (сделка) или decision (решение)", None
            if by == "decision" and not data.get("decision_id"):
                return "done (decision): в data нужен decision_id", None
            if by == "site" and not (data.get("decision_id") or data.get("trade_date")):
                return "done (site): в data нужен decision_id или trade_date", None
        if by not in CSTATE_INTERNAL_ACTORS or by not in _cl_words("actor"):
            return f"by: допустимы {', '.join(CSTATE_INTERNAL_ACTORS)}", None
    else:
        by = "owner"
    ev = {"condition_id": cid.strip()}
    if version is not None:
        ev["version"] = version
    ev.update(event=event, by=by, data=data)
    return None, ev


class _CondRefused(Exception):
    """Отказ записи события по смыслу (кнопка «вышел» у неподходящего условия) — 400, файл не тронут."""


def cond_event(root, body, internal=False, now=None):
    """→ (код, тело) для POST /api/pv/cond/event[/internal]: дописать событие в конец conditions-state.json.
    Время `at` ставит сервер. Повтор на внутреннем маршруте (_cstate_dup) — 200 {"duplicate": true}, без записи."""
    err, ev = cond_event_check(body if isinstance(body, dict) else {}, internal)
    if err:
        return 400, {"error": "bad event", "message": err}
    ev["at"] = _now_iso(now)
    ev = {k: ev[k] for k in ("condition_id", "version", "event", "at", "by", "data") if k in ev}

    def build(old):
        events = _cstate_parse(old)
        if internal and _cstate_dup(events, ev["condition_id"], ev.get("version"), ev["event"], ev.get("data")):
            return None, {"duplicate": True, "events": len(events)}
        if not internal and ev["event"] == "event_found":
            why = cond_found_check(root, ev["condition_id"], ev.get("version"), events, ev["at"][:10])
            if why:
                raise _CondRefused(why)
        events.append(ev)
        doc = {"schema_version": CSTATE_SCHEMA, "events": events}
        return (json.dumps(doc, ensure_ascii=False, indent=1) + "\n").encode("utf-8"), {"event": ev, "events": len(events)}

    try:
        res = _write_and_deliver(root, CSTATE_FILE, _cstate_state, build)
    except _CondRefused as e:
        return 400, {"error": "bad event", "message": str(e)}
    except (ValueError, UnicodeDecodeError) as e:
        return 500, {"error": "conditions-state unreadable", "detail": str(e)}
    return 200, res


def cond_state(root, since=None):
    """→ (код, тело) для GET /api/pv/cond/state: события с at > since (строки времени с поясом +03:00)."""
    with _write_lock:
        if _cstate_state["running"]:
            raw = _cstate_state["data"]
        else:
            try:
                with open(os.path.join(root, CSTATE_FILE), "rb") as f:
                    raw = f.read()
            except FileNotFoundError:
                raw = b""
    try:
        events = _cstate_parse(raw)
    except (ValueError, UnicodeDecodeError) as e:
        return 500, {"error": "conditions-state unreadable", "detail": str(e)}
    if since:
        events = [e for e in events if isinstance(e, dict) and str(e.get("at") or "") > since]
    return 200, {"schema_version": CSTATE_SCHEMA, "events": events}


def plan_set(root, path, value, reason, base_hash, now=None):
    """→ (код, тело) для POST /api/pv/plan/set в старой форме {path, value}: пакет из одного изменения."""
    if not isinstance(path, str):
        return 400, {"error": "bad request body"}
    return plan_set_batch(root, [{"path": path, "value": value}], reason, base_hash, now)


def plan_set_batch(root, changes, reason, base_hash, now=None):
    """→ (код, тело) для POST /api/pv/plan/set в пакетной форме: все изменения валидируются до записи,
    файл пишется один раз, журнал — одним проходом (по строке на изменение)."""
    if not isinstance(changes, list) or not isinstance(base_hash, str) or not base_hash \
            or not (reason is None or isinstance(reason, str)):
        return 400, {"error": "bad request body"}
    if not 1 <= len(changes) <= PLAN_BATCH_MAX:
        return 400, {"error": "bad request body", "detail": f"changes: от 1 до {PLAN_BATCH_MAX} элементов"}
    parsed, seen = [], set()
    for i, ch in enumerate(changes):
        if not isinstance(ch, dict) or not isinstance(ch.get("path"), str) or "value" not in ch:
            return 400, {"error": "bad request body", "index": i}
        path = ch["path"]
        for rx, validator, applier in PLAN_PATH_RULES:
            m = rx.match(path)
            if m:
                break
        else:
            return 400, {"error": "bad path", "index": i, "detail": path}
        if path in seen:
            return 400, {"error": "duplicate path", "index": i, "detail": path}
        seen.add(path)
        try:
            val = validator(ch["value"])
        except ValueError as e:
            return 400, {"error": "bad value", "index": i, "detail": str(e)}
        # тикер может содержать точку: ключ и поле берём из регулярки, не из split
        parsed.append((path, m, applier, val))
    reason = (reason or "").strip()[:PLAN_REASON_MAX] or None
    with _plan_lock:
        try:
            plan, cur_hash = plan_read(root)
        except FileNotFoundError:
            return 404, {"error": "not found"}
        except (ValueError, OSError) as e:
            return 500, {"error": "plan invalid", "detail": str(e)}
        if cur_hash != base_hash:
            return 409, {"error": "hash mismatch", "current_hash": cur_hash, "plan": plan}
        ts_s = _now_iso(now)
        entries = []
        try:
            for path, m, applier, val in parsed:
                was = applier(plan, m, val)
                entries.append({"ts": ts_s, "who": "site", "path": path, "was": was, "now": val, "reason": reason, "decision_id": None})
        except PlanShape as e:
            return 500, {"error": "plan invalid", "detail": str(e)}
        plan["updated_at"] = ts_s
        for r in plan.get("manual_positions") or []:
            if isinstance(r, dict) and r.get("value_as_of") == "@today":
                r["value_as_of"] = ts_s[:10]
        plan["updated_by"] = "hub-api"
        t0 = time.monotonic()
        try:
            new_hash = save_file(root, PLAN_FILE, plan_dump(plan), base_hash)
        except TooLarge:
            return 413, {"error": "content too large"}
        except Conflict as c:
            return 409, {"error": "hash mismatch", "current_hash": c.current_hash, "plan": plan_read(root)[0]}
        t1 = time.monotonic()
        out = {"hash": new_hash, "plan": plan, "entries": entries, "entry": entries[0]}
        try:
            append_plan_journal(root, entries)
        except Exception as e:  # noqa: BLE001 — журнал не должен ронять уже записанную правку
            out["journal_error"] = str(e)
        out["timing_ms"] = {"save": round((t1 - t0) * 1000), "journal": round((time.monotonic() - t1) * 1000)}   # где уходит время записи
    return 200, out


def plan_journal(root, limit=50, since=None):
    """→ список последних строк журнала, новые первыми. `since` — ISO-время с поясом: только строки с
    `ts > since` (сравнение строк; корректно лишь когда все `ts` в одном формате `…+03:00` — для старых
    строк с `Z` сначала миграция migrate_plan_journal_ts.py)."""
    with _write_lock:
        mem = _journal_state["data"] if _journal_state["running"] else None
    if mem is not None:                      # идёт фоновый перенос: файл на мгновение может отстать от памяти
        lines = mem.decode("utf-8", "replace").splitlines()
    else:
        try:
            with open(os.path.join(root, PLAN_JOURNAL), "rb") as f:
                lines = f.read().decode("utf-8", "replace").splitlines()
        except FileNotFoundError:
            return []
    out = []
    for ln in reversed(lines):
        if not ln.strip():
            continue
        try:
            row = json.loads(ln)
        except ValueError:
            continue
        if since and not (isinstance(row, dict) and str(row.get("ts") or "") > since):
            continue
        out.append(row)
        if len(out) >= limit:
            break
    return out


# ─────────────────── /api/pv/macro/inflation — недельная инфляция владельца (форма «Внести инфляцию») ───────────────────
# macro-snapshots/inflation/owner.jsonl — файл владельца, единственный писатель — hub-api (файл модели model.jsonl пишет
# только скилл macro-ru-watcher, save_inflation.py: один файл — один писатель). Строка — тот же формат, author "owner";
# страница берёт самую свежую по `date` запись из двух файлов. Только дописывание.
# ⚠ SYNC: границы и поля — skills/macro-ru-watcher/scripts/save_inflation.py (сторож — test_write_api).
INFL_OWNER = "macro-snapshots/inflation/owner.jsonl"
INFL_FIELDS = ("date", "week_pct", "week_period", "yoy_pct", "yoy_as_of", "source_url", "source_name", "recorded_at", "author")
_infl_state = {"running": False, "dirty": False, "data": None}   # носитель owner.jsonl


class _InflConflict(Exception):
    def __init__(self, current_hash):
        self.current_hash = current_hash


def infl_validate(rec, today, recorded_at):
    """→ (строка | None, [ошибки]); author — owner, лишние поля отбрасываются."""
    errs = []

    def num(v, lo, hi, name):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or not lo <= v <= hi:
            errs.append(f"{name}: число от {lo} до {hi}")
            return None
        return round(float(v), 3)

    def day(v, name, floor=None):
        try:
            d = datetime.strptime(v, "%Y-%m-%d").date() if isinstance(v, str) and len(v) == 10 else None
        except ValueError:
            d = None
        if d is None:
            errs.append(f"{name}: дата ГГГГ-ММ-ДД")
        elif d > today:
            errs.append(f"{name}: дата из будущего")
        elif floor and d < floor:
            errs.append(f"{name}: старше года — опечатка?")
        else:
            return v
        return None

    if not isinstance(rec, dict):
        return None, ["запись — объект"]
    out = {"date": day(rec.get("date"), "date", today - timedelta(days=366)),
           "week_pct": num(rec.get("week_pct"), -3, 5, "week_pct")}
    wp = rec.get("week_period")
    wp = wp.strip() if isinstance(wp, str) else ""
    if not 3 <= len(wp) <= 40:
        errs.append("week_period: строка 3–40 символов («03–09.11»)")
    out["week_period"] = wp
    out["yoy_pct"] = num(rec.get("yoy_pct"), -5, 100, "yoy_pct")
    ya = rec.get("yoy_as_of")
    out["yoy_as_of"] = day(ya if ya else out["date"], "yoy_as_of") if (ya or out["date"]) else None
    url = rec.get("source_url")
    if url in (None, ""):
        url = None
    elif not (isinstance(url, str) and url.startswith(("http://", "https://")) and " " not in url and len(url) <= 300):
        errs.append("source_url: http(s)-ссылка без пробелов, до 300 символов")
    out["source_url"] = url
    sn = rec.get("source_name")
    sn = sn.strip() if isinstance(sn, str) else ""
    if not 2 <= len(sn) <= 80:
        errs.append("source_name: строка 2–80 символов")
    out["source_name"] = sn
    out["recorded_at"] = recorded_at
    out["author"] = "owner"
    return (None, errs) if errs else ({k: out[k] for k in INFL_FIELDS}, [])


def infl_owner_hash(root):
    """sha256 текущего owner.jsonl (пустого файла нет — sha256 пустых байтов): base_hash формы."""
    with _write_lock:
        data = _infl_state["data"] if _infl_state["running"] else None
    if data is None:
        try:
            with open(os.path.join(root, INFL_OWNER), "rb") as f:
                data = f.read()
        except FileNotFoundError:
            data = b""
    return file_hash(data)


def infl_add(root, body, now=None):
    """→ (код, тело) для POST /api/pv/macro/inflation: проверка, дописывание строки в owner.jsonl.
    base_hash необязателен: если передан и не совпал с хэшем файла — 409 со свежим хэшем (форма перечитывает и повторяет).
    Та же запись (кроме recorded_at) уже есть — 200 {"duplicate": true} без записи."""
    if not isinstance(body, dict):
        return 400, {"error": "bad request body"}
    bh = body.get("base_hash")
    if bh is not None and not isinstance(bh, str):
        return 400, {"error": "bad request body"}
    ts = _now_iso(now)
    rec, errs = infl_validate(body.get("record", body), (now or datetime.now(MSK)).astimezone(MSK).date(), ts)
    if errs:
        return 400, {"error": "bad record", "problems": errs}

    def build(old):
        if bh is not None and file_hash(old) != bh:
            raise _InflConflict(file_hash(old))
        for ln in old.decode("utf-8", "replace").splitlines():
            try:
                row = json.loads(ln)
            except ValueError:
                continue
            if isinstance(row, dict) and all(row.get(k) == rec.get(k) for k in INFL_FIELDS if k != "recorded_at"):
                return None, {"duplicate": True, "record": row, "hash": file_hash(old)}
        base = old if not old or old.endswith(b"\n") else old + b"\n"
        data = base + (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8")
        return data, {"record": rec, "hash": file_hash(data), "records": data.count(b"\n")}

    try:
        res = _write_and_deliver(root, INFL_OWNER, _infl_state, build)
    except _InflConflict as c:
        return 409, {"error": "hash mismatch", "current_hash": c.current_hash}
    return 200, res


# ─────────────────── /api/pv/plan/export, import — база сайта (plan.json) целиком (этап 5) ───────────────────
# Экспорт: JSON — байты plan.json как есть, XLSX — книга для просмотра (назад не грузится, только stdlib zipfile).
# Импорт: только JSON; всё проверяется ДО записи теми же правилами, что и set; diff к текущему файлу;
# запись — один раз, в журнал — одна строка kind=import.
PLAN_IMPORT_TOP = ("schema_version", "generated_at", "updated_at", "updated_by", "source", "stocks", "classes", "matrix",
                   "bond_buckets", "bonds", "funds", "manual_positions", "ie_model", "ie_history")
PLAN_IMPORT_META = ("generated_at", "updated_at", "updated_by", "source")      # в diff не входят
PLAN_IMPORT_REASON_MAX = 300
PLAN_IMPORT_NAME_MAX = 200
PLAN_IMPORT_PROBLEMS_MAX = 50
PLAN_IMPORT_DIFF_MAX = 2000
PLAN_IMPORT_PATHS_MAX = 50
PLAN_IMPORT_HISTORY_MAX = 20000
PLAN_IMPORT_TOL = 1e-9
PLAN_STOCK_NUM_FIELDS = ("ie_new_pct", "ie_old_pct")      # у set правил для них нет (пишет ie-set)
PLAN_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PLAN_USER_PLAN_WORD = _cl_words("user_plan")
PLAN_USER_STATUS_WORD = _cl_words("user_status")
_PLAN_BUCKET_TYPE_CHECK = _plan_enum(PLAN_BOND_TYPES)
_PLAN_BUCKET_SUB_CHECK = _plan_enum(PLAN_BOND_SUBTYPES)
_PLAN_BOND_NAME_CHECK = _plan_str(200)
_PLAN_ISIN_RE = re.compile(r"^[A-Z0-9]{12}$")
_PLAN_DATE_RE = re.compile(r"^\d{4}-\d\d-\d\d$")


class _PlanProblems(Exception):
    """Достаточно проблем — дальше проверять нечего."""


class _PlanCheck:
    """Сбор проблем проверки импортируемого плана (не больше PLAN_IMPORT_PROBLEMS_MAX)."""

    def __init__(self):
        self.problems = []

    def bad(self, path, detail):
        self.problems.append({"path": path, "detail": detail})
        if len(self.problems) >= PLAN_IMPORT_PROBLEMS_MAX:
            raise _PlanProblems

    def by_rule(self, path, value):
        """Плоский путь → правило из PLAN_PATH_RULES → нормализованное значение (или None и проблема)."""
        if path.endswith(".iis_qty") and isinstance(value, float) and value.is_integer():
            value = int(value)             # Numbers отдавал количество как 5.0
        for rx, validator, _ap in PLAN_PATH_RULES:
            if rx.match(path):
                try:
                    return validator(value)
                except ValueError as e:
                    self.bad(path, str(e))
                    return None
        self.bad(path, "путь не разрешён")
        return None

    def with_(self, path, check, value):
        try:
            return check(value)
        except ValueError as e:
            self.bad(path, str(e))
            return None


def _plan_is_scalar(v):
    return v is None or isinstance(v, (str, bool)) or (isinstance(v, (int, float)) and v == v and abs(v) != float("inf"))


def _plan_import_dict_section(plan, name, ck, key_ok, fields, extra):
    """stocks / bonds / funds: {ключ: запись}; поля — по PLAN_PATH_RULES, extra — {поле: проверка} вне правил set."""
    sec = plan.get(name)
    out = {}
    if sec is None:
        return out
    if not isinstance(sec, dict):
        ck.bad(name, "должен быть объектом")
        return out
    for key, rec in sec.items():
        p = f"{name}.{key}"
        if not key_ok(key):
            ck.bad(p, "недопустимый ключ")
            continue
        if not isinstance(rec, dict):
            ck.bad(p, "запись должна быть объектом")
            continue
        o = {}
        for f, v in rec.items():
            if f in extra:
                o[f] = ck.with_(f"{p}.{f}", extra[f], v)
            elif f in fields:
                o[f] = ck.by_rule(f"{p}.{f}", v)
            else:
                ck.bad(f"{p}.{f}", "неизвестное поле")
        out[key] = o
    return out


def _plan_import_rows_section(plan, name, ck, keyf, rowfn):
    """classes / matrix / bond_buckets / manual_positions: список записей, ключ строки — keyf(row)."""
    rows = plan.get(name)
    out = []
    if rows is None:
        return out
    if not isinstance(rows, list):
        ck.bad(name, "должен быть списком")
        return out
    seen = set()
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            ck.bad(f"{name}[{i}]", "строка должна быть объектом")
            continue
        k = keyf(r)
        if k is None:
            ck.bad(f"{name}[{i}]", "нет ключа строки (строки в нужных полях)")
            continue
        if k in seen:
            ck.bad(f"{name}.{k}", "дубль строки")
            continue
        seen.add(k)
        o = rowfn(r, f"{name}.{k}")
        if o is not None:
            out.append(o)
    return out


def _plan_known_keys(ck, path, rec, allowed):
    for f in rec:
        if f not in allowed:
            ck.bad(f"{path}.{f}", "неизвестное поле")


def _plan_import_model(plan, ck):
    m = plan.get("ie_model")
    if m is None:
        return None
    if not isinstance(m, dict):
        ck.bad("ie_model", "должен быть объектом")
        return None
    out = {}
    for k, v in m.items():
        p = f"ie_model.{k}"
        if k in ("extraction_date", "general_date"):
            if v is not None and not (isinstance(v, str) and _PLAN_DATE_RE.match(v)):
                ck.bad(p, "дата YYYY-MM-DD или null")
            out[k] = v
        elif k == "cash_pct":
            out[k] = ck.with_(p, _plan_pct, v)
        elif k == "model_total_pct":
            out[k] = ck.with_(p, lambda y: _ie_plain_num(y, k), v)
        elif k == "cash_ticker":
            if v is not None and not (isinstance(v, str) and IE_TICKER_RE.match(v)):
                ck.bad(p, "тикер или null")
            out[k] = v
        elif k == "positions":
            out[k] = _plan_import_positions(v, ck)
        else:
            ck.bad(p, "неизвестное поле")
    return out


def _plan_import_positions(v, ck):
    if v is None:
        return []
    if not isinstance(v, list):
        ck.bad("ie_model.positions", "должен быть списком")
        return []
    out, seen = [], set()
    for i, r in enumerate(v):
        if not isinstance(r, dict) or not isinstance(r.get("ticker"), str) or not IE_TICKER_RE.match(r["ticker"]):
            ck.bad(f"ie_model.positions[{i}]", "объект с полем ticker (строка-тикер)")
            continue
        t = r["ticker"]
        if t in seen:
            ck.bad(f"ie_model.positions.{t}", "дубль тикера")
            continue
        seen.add(t)
        o = {"ticker": t}
        for f, x in r.items():
            p = f"ie_model.positions.{t}.{f}"
            if f == "ticker":
                continue
            if f in IE_NUM_FIELDS:
                o[f] = ck.with_(p, _plan_pct if f == "target_share_pct" else (lambda y, f=f: _ie_plain_num(y, f)), x)
            elif f in IE_TEXT_FIELDS:
                if x is not None and (not isinstance(x, str) or len(x) > IE_TEXT_MAX):
                    ck.bad(p, f"строка не длиннее {IE_TEXT_MAX} или null")
                o[f] = x
            elif f == "active_in_model":
                if x is not None and not isinstance(x, bool):
                    ck.bad(p, "true, false или null")
                o[f] = x
            else:
                ck.bad(p, "неизвестное поле")
        out.append(o)
    return out


def _plan_import_history(v, ck):
    if v is None:
        return []
    if not isinstance(v, list):
        ck.bad("ie_history", "должен быть списком")
        return []
    if len(v) > PLAN_IMPORT_HISTORY_MAX:
        ck.bad("ie_history", f"не больше {PLAN_IMPORT_HISTORY_MAX} записей")
        return []
    for i, r in enumerate(v):
        if not isinstance(r, dict) or not all(isinstance(k, str) and _plan_is_scalar(x) for k, x in r.items()):
            ck.bad(f"ie_history.{i}", "запись — объект из простых значений")
    return v


def plan_import_validate(plan):
    """→ (нормализованный план, problems). План не меняется; problems — [{path, detail}] (≤ 50)."""
    ck = _PlanCheck()
    out = {}
    try:
        if plan.get("schema_version") != "plan@1.0":
            ck.bad("schema_version", 'должна быть "plan@1.0"')
        for k in plan:
            if k not in PLAN_IMPORT_TOP:
                ck.bad(k, "неизвестный раздел")
        out["schema_version"] = plan.get("schema_version")
        for k in ("generated_at", "updated_at", "updated_by"):
            v = plan.get(k)
            if v is not None and not isinstance(v, str):
                ck.bad(k, "строка или null")
            if k in plan:
                out[k] = v
        if "source" in plan:
            if plan["source"] is not None and not isinstance(plan["source"], dict):
                ck.bad("source", "объект или null")
            out["source"] = plan["source"]
        t_ok = lambda k: bool(re.fullmatch(_PLAN_TICKER, k))                              # noqa: E731
        if "stocks" in plan:
            out["stocks"] = _plan_import_dict_section(
                plan, "stocks", ck, t_ok, PLAN_STOCK_FIELDS,
                {f: _plan_pct for f in PLAN_STOCK_NUM_FIELDS})
        if "bonds" in plan:
            out["bonds"] = _plan_import_dict_section(
                plan, "bonds", ck, lambda k: bool(_PLAN_ISIN_RE.match(k)),
                ("type", "subtype", "rating", "action", "iis_qty", "manual", "reason"), {"name": _PLAN_BOND_NAME_CHECK})
        if "funds" in plan:
            out["funds"] = _plan_import_dict_section(plan, "funds", ck, t_ok, PLAN_FUND_FIELDS, {})

        def row_share(keyname, fields):
            def fn(r, p):
                _plan_known_keys(ck, p, r, fields)
                o = {f: r[f] for f in fields if f in r and f != "share"}
                share = ck.by_rule(f"{p}.share", r.get("share"))      # заодно проверяет допустимость самого ключа строки
                if "share" in r:
                    o["share"] = share
                return o
            return fn

        if "classes" in plan:
            out["classes"] = _plan_import_rows_section(
                plan, "classes", ck, lambda r: r["class"] if isinstance(r.get("class"), str) else None,
                row_share("class", ("class", "share")))
        if "matrix" in plan:
            out["matrix"] = _plan_import_rows_section(
                plan, "matrix", ck,
                lambda r: f"{r['currency']}/{r['class']}" if isinstance(r.get("currency"), str) and isinstance(r.get("class"), str) else None,
                row_share("matrix", ("currency", "class", "share")))
        if "bond_buckets" in plan:
            def bucket(r, p):
                o = row_share("key", ("key", "type", "subtype", "share"))(r, p)
                if "type" in r:
                    o["type"] = ck.with_(f"{p}.type", _PLAN_BUCKET_TYPE_CHECK, r["type"])
                if "subtype" in r:
                    o["subtype"] = ck.with_(f"{p}.subtype", _PLAN_BUCKET_SUB_CHECK, r["subtype"])
                return o
            out["bond_buckets"] = _plan_import_rows_section(
                plan, "bond_buckets", ck, lambda r: r["key"] if isinstance(r.get("key"), str) else None, bucket)
        if "manual_positions" in plan:
            def manual(r, p):
                _plan_known_keys(ck, p, r, ("type", "name", "value_rub", "value_as_of"))
                o = {"type": r["type"], "name": r["name"]}
                if "value_rub" in r:
                    o["value_rub"] = ck.by_rule(f"{p}.value_rub", r["value_rub"])
                if "value_as_of" in r:
                    v = r["value_as_of"]
                    if v is not None and not (isinstance(v, str) and _PLAN_DATE_RE.match(v)):
                        ck.bad(f"{p}.value_as_of", "дата YYYY-MM-DD или null")
                    o["value_as_of"] = v
                return o
            out["manual_positions"] = _plan_import_rows_section(
                plan, "manual_positions", ck,
                lambda r: f"{r['type']}/{r['name']}" if isinstance(r.get("type"), str) and isinstance(r.get("name"), str) else None,
                manual)
        if "ie_model" in plan:
            out["ie_model"] = _plan_import_model(plan, ck)
        if "ie_history" in plan:
            out["ie_history"] = _plan_import_history(plan["ie_history"], ck)
    except _PlanProblems:
        pass
    return out, ck.problems


def _plan_flatten(plan):
    """Нормализованный план → {плоский путь: лист}. Списки — по ключу строки, ie_history — по индексу."""
    flat = {}

    def walk(path, v):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(f"{path}.{k}" if path else str(k), x)
        else:
            flat[path] = v

    for name in PLAN_IMPORT_TOP:
        if name in PLAN_IMPORT_META or name == "schema_version" or name not in plan:
            continue
        v = plan[name]
        if name == "ie_history" and isinstance(v, list):
            for i, r in enumerate(v):
                walk(f"{name}.{i}", r)
        elif name == "ie_model" and isinstance(v, dict):
            for k, x in v.items():
                if k == "positions" and isinstance(x, list):
                    for r in x:
                        if isinstance(r, dict):
                            walk(f"ie_model.positions.{r.get('ticker')}", {f: y for f, y in r.items() if f != "ticker"})
                else:
                    walk(f"ie_model.{k}", x)
        elif isinstance(v, list):
            for r in v:
                if not isinstance(r, dict):
                    continue
                k = {"classes": lambda r: r.get("class"), "matrix": lambda r: f"{r.get('currency')}/{r.get('class')}",
                     "bond_buckets": lambda r: r.get("key"),
                     "manual_positions": lambda r: f"{r.get('type')}/{r.get('name')}"}.get(name, lambda r: None)(r)
                skip = {"classes": ("class",), "matrix": ("currency", "class"), "bond_buckets": ("key",),
                        "manual_positions": ("type", "name")}.get(name, ())
                walk(f"{name}.{k}", {f: y for f, y in r.items() if f not in skip})
        else:
            walk(name, v)
    return flat


def _plan_num_same(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= PLAN_IMPORT_TOL
    return a == b


def plan_import_diff(old, new):
    """→ (diff [{path, old, new}], counts). old/new — планы (диск и нормализованный импорт)."""
    fo, fn = _plan_flatten(old), _plan_flatten(new)
    diff, counts, by = [], {"added": 0, "removed": 0, "changed": 0}, {}
    for path in sorted(set(fo) | set(fn)):
        a, b = fo.get(path), fn.get(path)
        if path in fo and path in fn:
            if _plan_num_same(a, b):
                continue
            kind = "changed"
        elif path in fn:
            if b is None:
                continue
            kind = "added"
        else:
            if a is None:
                continue
            kind = "removed"
        counts[kind] += 1
        sec = path.split(".", 1)[0]
        by[sec] = by.get(sec, 0) + 1
        diff.append({"path": path, "old": a, "new": b})
    counts["total"] = len(diff)
    counts["by_section"] = by
    return diff, counts


def plan_import(root, body, now=None):
    """→ (код, тело) для POST /api/pv/plan/import: проверка плана целиком, diff, при отсутствии dry_run — запись."""
    if not isinstance(body, dict) or not isinstance(body.get("base_hash"), str) or not body["base_hash"] \
            or not isinstance(body.get("plan"), dict):
        return 400, {"error": "bad request body"}
    reason, name, dry = body.get("reason"), body.get("name"), body.get("dry_run", False)
    if not isinstance(dry, bool) or not (reason is None or isinstance(reason, str)) \
            or not (name is None or isinstance(name, str)):
        return 400, {"error": "bad request body"}
    reason = (reason or "").strip()
    if len(reason) > PLAN_IMPORT_REASON_MAX or len(name or "") > PLAN_IMPORT_NAME_MAX:
        return 400, {"error": "bad request body", "detail": f"reason ≤ {PLAN_IMPORT_REASON_MAX}, name ≤ {PLAN_IMPORT_NAME_MAX} символов"}
    new_plan, problems = plan_import_validate(body["plan"])
    if problems:
        return 400, {"error": "bad plan", "problems": problems}
    with _plan_lock:
        try:
            cur, cur_hash = plan_read(root)
        except FileNotFoundError:
            return 404, {"error": "not found"}
        except (ValueError, OSError) as e:
            return 500, {"error": "plan invalid", "detail": str(e)}
        if cur_hash != body["base_hash"]:
            return 409, {"error": "hash mismatch", "current_hash": cur_hash, "plan": cur}
        diff, counts = plan_import_diff(cur, new_plan)
        shown = diff[:PLAN_IMPORT_DIFF_MAX]
        out = {"hash": cur_hash, "diff": shown, "counts": counts}
        if len(diff) > PLAN_IMPORT_DIFF_MAX:
            out["diff_truncated"] = True
        if not diff:
            out["unchanged"] = True            # «поля нет» ≡ null: _plan_flatten даёт лист None, diff такие пары пропускает
            return 200, out
        if dry:
            return 200, out
        ts_s = _now_iso(now)
        plan = new_plan
        for k in ("generated_at", "source"):
            if k not in plan and k in cur:
                plan[k] = cur[k]
        plan["updated_at"] = ts_s
        plan["updated_by"] = "hub-api"
        t0 = time.monotonic()
        try:
            new_hash = save_file(root, PLAN_FILE, plan_dump(plan), body["base_hash"])
        except TooLarge:
            return 413, {"error": "content too large"}
        except Conflict as c:
            return 409, {"error": "hash mismatch", "current_hash": c.current_hash, "plan": plan_read(root)[0]}
        t1 = time.monotonic()
        res = {"hash": new_hash, "plan": plan, "counts": counts}
        try:
            append_plan_journal(root, {"ts": ts_s, "who": "site", "kind": "import", "reason": reason or None,
                                       "name": (name or "").strip() or None, "n_changes": len(diff), "counts": counts,
                                       "paths": [d["path"] for d in diff[:PLAN_IMPORT_PATHS_MAX]],
                                       "decision_id": None})
        except Exception as e:  # noqa: BLE001 — журнал не должен ронять уже записанный план
            res["journal_error"] = str(e)
        res["timing_ms"] = {"save": round((t1 - t0) * 1000), "journal": round((time.monotonic() - t1) * 1000)}
    return 200, res


# ── экспорт: XLSX из stdlib (SpreadsheetML без стилей и sharedStrings) ──
_XML_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def _xml_esc(s):
    return (_XML_BAD.sub("", str(s)).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _xl_name(n):
    """Название листа: без запрещённых знаков, ≤31 символа, экранировано для атрибута."""
    return _xml_esc(re.sub(r"[\[\]\\/?*:]", "", n)[:31]).replace('"', "&quot;")


def _xl_col(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _xl_cell(ref, v):
    if v is None or v == "":
        return ""
    if isinstance(v, bool):
        v = "да" if v else "нет"
    if isinstance(v, (int, float)):
        if v != v or v in (float("inf"), float("-inf")):
            return ""
        return f'<c r="{ref}" t="n"><v>{repr(v) if isinstance(v, float) else v}</v></c>'
    if isinstance(v, (dict, list)):
        v = json.dumps(v, ensure_ascii=False)
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{_xml_esc(v)}</t></is></c>'


def _xl_sheet_xml(rows, widths, header_row=1, table=False):
    """Лист: dimension по реальным размерам, закреплённая шапка, <tableParts> при table=True. Пустые строки не пишутся."""
    ncols = max([len(r) for r in rows] + [len(widths), 1])
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths))
    body = []
    for ri, row in enumerate(rows, 1):
        cells = "".join(_xl_cell(f"{_xl_col(ci)}{ri}", v) for ci, v in enumerate(row))
        if cells:
            body.append(f'<row r="{ri}">{cells}</row>')
    pane = (f'<pane ySplit="{header_row}" topLeftCell="A{header_row + 1}" activePane="bottomLeft" state="frozen"/>'
            f'<selection pane="bottomLeft" activeCell="A{header_row + 1}" sqref="A{header_row + 1}"/>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<dimension ref="A1:{_xl_col(ncols - 1)}{max(len(rows), 1)}"/>'
            f'<sheetViews><sheetView workbookViewId="0">{pane}</sheetView></sheetViews>'
            f'<cols>{cols}</cols><sheetData>{"".join(body)}</sheetData>'
            + ('<tableParts count="1"><tablePart r:id="rId1"/></tableParts>' if table else '')
            + '</worksheet>')


def _xl_table_xml(tid, display, rows, header_row):
    """Таблица Excel (ListObject) поверх шапки и строк данных листа."""
    head = rows[header_row - 1]
    ref = f"A{header_row}:{_xl_col(len(head) - 1)}{len(rows)}"
    cols = "".join(f'<tableColumn id="{i}" name="{_xml_esc(h).replace(chr(34), "&quot;")}"/>' for i, h in enumerate(head, 1))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<table xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            f'id="{tid}" name="{display}" displayName="{display}" ref="{ref}" headerRowCount="1">'
            f'<autoFilter ref="{ref}"/><tableColumns count="{len(head)}">{cols}</tableColumns>'
            '<tableStyleInfo name="TableStyleMedium2" showFirstColumn="0" showLastColumn="0" '
            'showRowStripes="1" showColumnStripes="0"/></table>')


_XL_TABLE_NAMES = {"Акции": "T_Stocks", "Классы": "T_Classes", "Матрица": "T_Matrix", "Корзины": "T_Buckets",
                   "Облигации": "T_Bonds", "Фонды": "T_Funds", "Ручные позиции": "T_Manual", "Модель IE": "T_IEModel",
                   "История IE": "T_IEHistory"}


def _pct(v):
    """Доля единицы → проценты без хвоста плавающей точки."""
    return round(v * 100, 8) if isinstance(v, (int, float)) and not isinstance(v, bool) else v


def plan_xlsx_sheets(plan):
    """→ [(название листа, строки, ширины колонок, номер строки шапки)] — девять листов; «История IE» только при записях."""
    g = lambda d, k: d.get(k) if isinstance(d, dict) else None                            # noqa: E731
    dicts = lambda name: sorted((k, v) for k, v in (plan.get(name) or {}).items() if isinstance(v, dict))   # noqa: E731
    lists = lambda name: [r for r in (plan.get(name) or []) if isinstance(r, dict)]        # noqa: E731
    model = plan.get("ie_model") if isinstance(plan.get("ie_model"), dict) else {}
    sheets = []
    rows = [["Тикер", "План, %", "План словом", "Статус", "Доля IE, %", "Была доля IE, %", "Заметка IE", "Моя заметка"]]
    for t, r in dicts("stocks"):
        st = r.get("user_status")
        rows.append([t, r.get("plan_pct"), PLAN_USER_PLAN_WORD.get(r.get("user_plan"), r.get("user_plan")),
                     PLAN_USER_STATUS_WORD.get(st, st), r.get("ie_new_pct"), r.get("ie_old_pct"),
                     r.get("note_ie"), r.get("note_ai")])
    sheets.append(("Акции", rows, [12, 10, 18, 18, 12, 14, 50, 40], 1))
    sheets.append(("Классы", [["Класс", "Доля, %"]] + [[r.get("class"), _pct(r.get("share"))] for r in lists("classes")], [18, 10], 1))
    sheets.append(("Матрица", [["Валюта", "Класс", "Доля, %"]]
                   + [[r.get("currency"), r.get("class"), _pct(r.get("share"))] for r in lists("matrix")], [10, 16, 10], 1))
    sheets.append(("Корзины", [["Корзина", "Тип", "Подтип", "Доля, %"]]
                   + [[r.get("key"), r.get("type"), r.get("subtype"), _pct(r.get("share"))] for r in lists("bond_buckets")],
                   [16, 10, 10, 10], 1))
    sheets.append(("Облигации", [["ISIN", "Название", "Тип", "Подтип", "Рейтинг", "Действие", "Количество на ИИС"]]
                   + [[i, r.get("name"), r.get("type"), r.get("subtype"), r.get("rating"), r.get("action"), r.get("iis_qty")]
                      for i, r in dicts("bonds")], [16, 34, 8, 10, 10, 30, 18], 1))
    sheets.append(("Фонды", [["Тикер", "Класс", "Валюта", "Корзина", "В балансировке", "Комиссия, % в год", "Спред, %", "Заметка"]]
                   + [[t, r.get("class"), r.get("currency"), r.get("bucket"), r.get("in_rebalance"), r.get("fee_pct"), r.get("spread_pct"), r.get("note")]
                      for t, r in dicts("funds")], [12, 14, 10, 14, 16, 18, 10, 40], 1))
    sheets.append(("Ручные позиции", [["Тип", "Название", "Стоимость, ₽", "Оценка на дату"]]
                   + [[r.get("type"), r.get("name"), r.get("value_rub"), r.get("value_as_of")] for r in lists("manual_positions")],
                   [22, 30, 16, 16], 1))
    rows = [["Дата модели", g(model, "extraction_date")], ["Дата общего портфеля", g(model, "general_date")]]
    if g(model, "cash_pct") is not None:
        rows.append(["Кэш, %", g(model, "cash_pct")])
    rows.append([])
    header_row = len(rows) + 1
    rows.append(["Тикер", "Название", "Активна в модели", "Доля цели, %", "Цена IE, ₽", "Цель 12 мес, ₽", "Долгосрочная цель, ₽",
                 "Потенциал 12 мес, %", "Потенциал долгосрок, %", "Дивдоходность, %", "Риск", "Сектор", "Отрасль"])
    for r in (model.get("positions") or []):
        if isinstance(r, dict):
            rows.append([r.get("ticker"), r.get("name"), r.get("active_in_model"), r.get("target_share_pct"),
                         r.get("current_price_rub"), r.get("target_price_rub"), r.get("target_price_lt_rub"),
                         r.get("growth_potential_12m_pct"), r.get("growth_potential_lt_pct"), r.get("div_yield_2024_pct"),
                         r.get("risk_level"), r.get("sector"), r.get("industry")])
    sheets.append(("Модель IE", rows, [20, 24, 16, 14, 12, 14, 20, 18, 20, 16, 12, 18, 18], header_row))
    hist = [r for r in (plan.get("ie_history") or []) if isinstance(r, dict)]
    keys = []
    for r in hist:
        keys += [k for k in r if k not in keys]
    if keys:
        head = [k if str(k).strip() else f"col_{i}" for i, k in enumerate(keys, 1)]
        sheets.append(("История IE", [head] + [[r.get(k) for k in keys] for r in hist], [20] * len(keys), 1))
    return sheets


def plan_xlsx(plan):
    """→ байты .xlsx (zipfile, ZIP_DEFLATED): листы с dimension и закреплённой шапкой, таблицы Excel там, где есть данные."""
    import io
    import zipfile
    sheets = plan_xlsx_sheets(plan)
    tabled = [i for i, (_n, rows, _w, h) in enumerate(sheets, 1) if len(rows) > h and any(c not in (None, "") for c in rows[h - 1])]
    buf = io.BytesIO()
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        ct = "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                     for i in range(1, len(sheets) + 1))
        ct += "".join(f'<Override PartName="/xl/tables/table{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"/>'
                      for i in tabled)
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   f'{ct}</Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   f'<Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   f'<workbook xmlns="{ns}" xmlns:r="{rel}"><sheets>'
                   + "".join(f'<sheet name="{_xl_name(n)}" sheetId="{i}" r:id="rId{i}"/>'
                             for i, (n, _r, _w, _h) in enumerate(sheets, 1))
                   + '</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i}" Type="{rel}/worksheet" Target="worksheets/sheet{i}.xml"/>'
                             for i in range(1, len(sheets) + 1)) + '</Relationships>')
        for i, (n, rows, widths, h) in enumerate(sheets, 1):
            has_table = i in tabled
            z.writestr(f"xl/worksheets/sheet{i}.xml", _xl_sheet_xml(rows, widths, h, has_table))
            if has_table:
                z.writestr(f"xl/worksheets/_rels/sheet{i}.xml.rels",
                           '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                           '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                           f'<Relationship Id="rId1" Type="{rel}/table" Target="../tables/table{i}.xml"/></Relationships>')
                z.writestr(f"xl/tables/table{i}.xml", _xl_table_xml(i, _XL_TABLE_NAMES.get(n, f"T_{i}"), rows, h))
    return buf.getvalue()


def plan_export(root, fmt):
    """→ (код, тело-байты, mime, имя файла, hash) для GET /api/pv/plan/export; при ошибке тело — dict (JSON)."""
    if fmt not in ("json", "xlsx"):
        return 400, {"error": "bad format", "detail": "format: json или xlsx"}, None, None, None
    try:
        text, h = read_file(root, PLAN_FILE)
        plan = json.loads(text)
        if not isinstance(plan, dict):
            raise ValueError("корень плана — не объект")
    except FileNotFoundError:
        return 404, {"error": "not found"}, None, None, None
    except (ValueError, OSError) as e:
        return 500, {"error": "plan invalid", "detail": str(e)}, None, None, None
    upd = plan.get("updated_at")
    day = upd[:10] if isinstance(upd, str) and _PLAN_DATE_RE.match(upd[:10]) else _now_iso()[:10]
    if fmt == "json":
        return 200, text.encode("utf-8"), "application/json", f"site-db-{day}.json", h
    return 200, plan_xlsx(plan), PLAN_XLSX_MIME, f"site-db-{day}.xlsx", h


# ─────────────────── /api/pv/plan/ie-import, ie-set — модель IE с сайта (этап 3) ───────────────────
# ie-import разбирает страницу IE (webarchive Safari или голый HTML) и считает diff к plan.json БЕЗ записи;
# ie-set — единственный писатель полей IE (доли, позиции модели, кэш, журнал ie_history).
IE_IMPORT_MAX_BYTES = 16 * 1024 * 1024    # webarchive ≈ 6,5 МБ → base64 ≈ 8,7 МБ; общий MAX_BYTES не трогаем
IE_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9_.-]{0,15}$")
IE_CASH_TICKER = "LQDT"
IE_TOL = 0.005                            # допуск сравнения долей и чисел
IE_BATCH_MAX = 400
IE_COLUMNS = {                            # заголовок колонки (нижний регистр) → ключ позиции; сопоставление по заголовкам
    "название": "name", "тикер": "ticker", "сектор": "sector", "отрасль": "industry", "доля": "target_share_pct",
    "текущая цена": "current_price_rub", "точка входа": "entry_price_rub", "уровень риска": "risk_level",
    "потенциал": "target_price_rub", "долгосрочный потенциал": "target_price_lt_rub",
    "потенциал роста, %": "growth_potential_12m_pct", "долгосрочный потенциал роста, %": "growth_potential_lt_pct",
}                                         # «Дивиденды…» (с годом в заголовке) → div_yield_2024_pct, ищется по префиксу
IE_NUM_FIELDS = ("target_share_pct", "current_price_rub", "entry_price_rub", "target_price_rub", "target_price_lt_rub",
                 "growth_potential_12m_pct", "growth_potential_lt_pct", "div_yield_2024_pct")
IE_TEXT_FIELDS = ("name", "sector", "industry", "risk_level")
IE_FIELDS_DIFF = tuple(f for f in IE_NUM_FIELDS if f != "target_share_pct") + ("risk_level", "sector", "industry")
IE_TEXT_MAX = 120


class _IETables(HTMLParser):
    """Все <table> страницы как списки строк (текст ячеек со схлопнутыми пробелами) + <title>."""

    def __init__(self):
        super().__init__()
        self.tables, self._stack, self._row, self._cell = [], [], None, None
        self.title, self._in_title = "", False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.tables.append([])
            self._stack.append(self.tables[-1])
        elif tag == "tr" and self._stack:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = ""
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            self._row.append(re.sub(r"\s+", " ", self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self._stack[-1].append(self._row)
            self._row = None
        elif tag == "table" and self._stack:
            self._stack.pop()
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._cell is not None:
            self._cell += data
        if self._in_title:
            self.title += data


def _ie_num(s):
    """'-' / пусто → None; запятая и точка — разделители; узкие пробелы убираются."""
    s = re.sub(r"[\s   ]", "", s or "").replace(",", ".").replace("%", "")
    if s in ("", "-", "—", "–"):
        return None
    try:
        v = float(s)
    except ValueError:
        raise ValueError(f"не число: {s!r}") from None
    if v != v or v in (float("inf"), float("-inf")):
        raise ValueError(f"не число: {s!r}")
    return v


def _ie_str(s):
    s = (s or "").strip()
    return None if s in ("", "-", "—", "–") else s


def ie_parse_page(raw):
    """webarchive (bplist/xml plist) или голый HTML → {kind, url, title, rows, positions, cash_pct, cash_ticker}.
    Колонки — по заголовкам. ValueError — не разобрать (plist/HTML/таблица не найдена)."""
    url, enc, data = None, "utf-8", raw
    if raw[:6] == b"bplist" or (raw[:5] == b"<?xml" and b"<plist" in raw[:2000]):
        try:
            mr = plistlib.loads(raw)["WebMainResource"]
            data, url = mr["WebResourceData"], mr.get("WebResourceURL")
            enc = mr.get("WebResourceTextEncodingName") or "utf-8"
        except Exception as e:  # noqa: BLE001 — любой сбой plist = «не webarchive»
            raise ValueError(f"не удалось прочитать webarchive: {e}") from None
        if not isinstance(data, (bytes, bytearray)):
            raise ValueError("в webarchive нет WebResourceData")
    try:
        html = bytes(data).decode(enc, "replace")
    except LookupError:
        html = bytes(data).decode("utf-8", "replace")
    p = _IETables()
    p.feed(html)
    p.close()
    for tb in p.tables:
        if len(tb) < 2:
            continue
        head = [re.sub(r"\s+", " ", h).strip().lower() for h in tb[0]]
        if "тикер" not in head:
            continue
        cols = {}
        for i, h in enumerate(head):
            key = IE_COLUMNS.get(h) or ("div_yield_2024_pct" if h.startswith("дивиденды") else None)
            if key and key not in cols:
                cols[key] = i
        positions, cash_pct, cash_ticker, seen = [], None, None, set()
        for r in tb[1:]:
            if len(r) < len(head):
                r = r + [""] * (len(head) - len(r))
            t = (r[cols["ticker"]] or "").strip().upper()
            if not t:
                continue
            row = {}
            for key, i in cols.items():
                row[key] = _ie_num(r[i]) if key in IE_NUM_FIELDS else _ie_str(r[i])
            row["ticker"] = t
            if t == IE_CASH_TICKER and ((row.get("name") or "").lower() == "кэш" or row.get("sector") is None):
                cash_pct, cash_ticker = row.get("target_share_pct"), t
                continue
            if t in seen:
                continue
            seen.add(t)
            positions.append(row)
        return {"kind": "model" if "target_share_pct" in cols else "general", "url": url,
                "title": _ie_str(p.title), "rows": len(positions) + (1 if cash_ticker else 0),
                "positions": positions, "cash_pct": cash_pct, "cash_ticker": cash_ticker}
    raise ValueError("таблица с колонкой «Тикер» не найдена")


def _ie_same(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(a - b) < IE_TOL
    return a == b


def _ie_model(plan):
    """→ (ie_model, positions) без создания; ValueError — форма плана неверна."""
    m = plan.get("ie_model")
    if m is None:
        return {}, []
    if not isinstance(m, dict) or not isinstance(m.get("positions", []), list):
        raise ValueError("ie_model — не объект или positions — не список")
    return m, m.get("positions", [])


def _ie_cur_share(plan, ticker):
    """Текущая доля IE: stocks.T.ie_new_pct ?? positions[T].target_share_pct ?? None."""
    rec = (plan.get("stocks") or {}).get(ticker)
    if isinstance(rec, dict) and rec.get("ie_new_pct") is not None:
        return rec["ie_new_pct"]
    _m, positions = _ie_model(plan)
    for x in positions:
        if isinstance(x, dict) and x.get("ticker") == ticker:
            return x.get("target_share_pct")
    return None


def _ie_diff(plan, page, tickers):
    """→ (diff, ignored) страницы к плану; general — все строки в diff с ключом held, ignored всегда []."""
    _m, positions = _ie_model(plan)
    pos = {x.get("ticker"): x for x in positions if isinstance(x, dict)}
    model = page["kind"] == "model"
    diff, ignored, on_page = [], [], set()
    for row in page["positions"]:
        t = row["ticker"]
        on_page.add(t)
        old = pos.get(t)
        fields = {}
        if old is not None:
            for f in IE_FIELDS_DIFF:
                if f in row and not _ie_same(old.get(f), row[f]):
                    fields[f] = {"was": old.get(f), "now": row[f]}
        item = {"ticker": t, "name": row.get("name") or (old or {}).get("name"), "fields": fields,
                "held": t in tickers}
        if model:
            cur, now = _ie_cur_share(plan, t), row.get("target_share_pct")
            item["share"] = {"was": cur, "now": now}
            item["status"] = "new" if cur is None and now is not None else \
                "same" if _ie_same(cur, now) else "changed"
        else:
            item["share"] = None
            item["status"] = "new" if old is None else "changed" if fields else "same"
        diff.append(item)
    if model:
        for t, x in pos.items():
            if t not in on_page and x.get("active_in_model") is not False:
                diff.append({"ticker": t, "name": x.get("name"), "status": "removed",
                             "share": {"was": _ie_cur_share(plan, t), "now": None}, "fields": {},
                             "held": t in tickers})
    return diff, ignored


def plan_ie_import(root, body):
    """→ (код, тело) для POST /api/pv/plan/ie-import: разбор страницы IE и diff к plan.json, без записи."""
    if not isinstance(body, dict) or not isinstance(body.get("b64"), str) \
            or not isinstance(body.get("tickers", []), list) \
            or not all(isinstance(t, str) for t in body.get("tickers", [])):
        return 400, {"error": "bad request body"}
    try:
        plan, h = plan_read(root)
    except FileNotFoundError:
        return 404, {"error": "not found"}
    except (ValueError, OSError) as e:
        return 500, {"error": "plan invalid", "detail": str(e)}
    try:
        raw = base64.b64decode(body["b64"], validate=True)
    except (binascii.Error, ValueError):
        return 400, {"error": "bad page", "detail": "b64: не base64"}
    try:
        page = ie_parse_page(raw)
        diff, ignored = _ie_diff(plan, page, set(body.get("tickers", [])))
    except ValueError as e:
        return 400, {"error": "bad page", "detail": str(e)}
    return 200, {"kind": page["kind"], "url": page["url"], "title": page["title"], "rows": page["rows"],
                 "positions": page["positions"], "cash_pct": page["cash_pct"], "cash_ticker": page["cash_ticker"],
                 "hash": h, "diff": diff, "ignored": ignored}


def _ie_check_position(v):
    """Объект позиции → очищенная копия; ValueError с текстом."""
    if not isinstance(v, dict):
        raise ValueError("position — объект")
    out = {}
    for k, x in v.items():
        if k == "ticker":
            continue                       # тикер берётся из changes[i].ticker
        if k in IE_NUM_FIELDS:
            out[k] = _plan_pct(x) if k == "target_share_pct" else _ie_plain_num(x, k)
        elif k in IE_TEXT_FIELDS:
            if x is not None and (not isinstance(x, str) or len(x) > IE_TEXT_MAX):
                raise ValueError(f"{k}: строка не длиннее {IE_TEXT_MAX} или null")
            out[k] = x
        elif k == "active_in_model":
            if not isinstance(x, bool):
                raise ValueError("active_in_model: true/false")
            out[k] = x
        else:
            raise ValueError(f"неизвестное поле position.{k}")
    return out


def _ie_plain_num(x, k):
    if x is None:
        return None
    if isinstance(x, bool) or not isinstance(x, (int, float)) or x != x or abs(x) > 1e12:
        raise ValueError(f"{k}: число или null")
    return x


def _ie_bad(code_err, i, detail):
    return 400, {"error": code_err, "index": i, "detail": detail}


def plan_ie_set(root, body, now=None):
    """→ (код, тело) для POST /api/pv/plan/ie-set: запись изменений модели IE (доли, заметки, позиции, кэш).
    Всё проверяется до записи; файл пишется один раз, журнал — одним проходом."""
    if not isinstance(body, dict) or not isinstance(body.get("base_hash"), str) or not body["base_hash"] \
            or not isinstance(body.get("changes"), list):
        return 400, {"error": "bad request body"}
    source = body.get("source")
    if source not in ("site", "webarchive"):
        return 400, {"error": "bad value", "detail": "source: site или webarchive"}
    page = body.get("page", "model")
    if page not in ("model", "general"):
        return 400, {"error": "bad value", "detail": "page: model или general"}
    ext = body.get("extraction_date")
    if ext is not None:
        try:
            if not isinstance(ext, str) or not re.fullmatch(r"\d{4}-\d\d-\d\d", ext):
                raise ValueError
            datetime.strptime(ext, "%Y-%m-%d")
        except ValueError:
            return 400, {"error": "bad value", "detail": "extraction_date: YYYY-MM-DD или null"}
    has_cash = "cash_pct" in body
    try:
        cash = _plan_pct(body["cash_pct"]) if has_cash else None
    except ValueError as e:
        return 400, {"error": "bad value", "detail": f"cash_pct: {e}"}
    chs = body["changes"]
    if len(chs) > IE_BATCH_MAX:
        return 400, {"error": "bad request body", "detail": f"changes: не больше {IE_BATCH_MAX} элементов"}
    parsed, seen, any_op = [], set(), has_cash
    for i, ch in enumerate(chs):
        if not isinstance(ch, dict) or not isinstance(ch.get("ticker"), str) or not IE_TICKER_RE.match(ch["ticker"]):
            return _ie_bad("bad ticker", i, str(ch.get("ticker")) if isinstance(ch, dict) else "не объект")
        t = ch["ticker"]
        if t in seen:
            return _ie_bad("duplicate ticker", i, t)
        seen.add(t)
        c = {"ticker": t, "reason": None}
        try:
            if "share_pct" in ch:
                c["share_pct"] = _plan_pct(ch["share_pct"])
            if "note_ie" in ch:
                c["note_ie"] = _plan_text(ch["note_ie"])
            if "position" in ch:
                c["position"] = _ie_check_position(ch["position"])
            r = ch.get("reason")
            if r is not None and (not isinstance(r, str) or len(r) > PLAN_REASON_MAX):
                raise ValueError(f"reason: строка не длиннее {PLAN_REASON_MAX} или null")
            c["reason"] = (r or "").strip() or None
        except ValueError as e:
            return _ie_bad("bad value", i, str(e))
        any_op = any_op or any(k in c for k in ("share_pct", "note_ie", "position"))
        parsed.append(c)
    if not any_op:
        return 400, {"error": "bad request body", "detail": "пустой пакет: нет ни одного изменения"}
    with _plan_lock:
        try:
            plan, cur_hash = plan_read(root)
        except FileNotFoundError:
            return 404, {"error": "not found"}
        except (ValueError, OSError) as e:
            return 500, {"error": "plan invalid", "detail": str(e)}
        if cur_hash != body["base_hash"]:
            return 409, {"error": "hash mismatch", "current_hash": cur_hash, "plan": plan}
        stocks = plan.setdefault("stocks", {})
        try:
            if not isinstance(stocks, dict):
                raise ValueError("stocks — не объект")
            for c in parsed:
                if c["ticker"] in stocks and not isinstance(stocks[c["ticker"]], dict):
                    raise ValueError(f"stocks.{c['ticker']} — не объект")
            model = plan.setdefault("ie_model", {})
            _ie_model(plan)
            positions = model.setdefault("positions", [])
            if any(not isinstance(x, dict) for x in positions):
                raise ValueError("ie_model.positions: не объект в списке")
        except ValueError as e:
            return 500, {"error": "plan invalid", "detail": str(e)}
        before = plan_dump(plan)
        ts_s = _now_iso(now)
        day = ts_s[:10]
        hist = plan.setdefault("ie_history", [])
        if not isinstance(hist, list):
            return 500, {"error": "plan invalid", "detail": "ie_history — не список"}
        entries = []

        def jr(path, was, now_, reason):
            entries.append({"ts": ts_s, "who": "site", "path": path, "was": was, "now": now_, "reason": reason,
                            "decision_id": None})

        def stock_rec(t):
            if t not in stocks:
                stocks[t] = {f: None for f in PLAN_STOCK_FIELDS}
            return stocks[t]

        def find_pos(t):
            return next((x for x in positions if x.get("ticker") == t), None)

        for c in parsed:
            t, reason = c["ticker"], c["reason"]
            cur = _ie_cur_share(plan, t)                   # доля ДО правок пакета по этой бумаге
            if "position" in c:                            # сначала position, потом share_pct (доля из share главнее)
                old = find_pos(t)
                was_pos = dict(old) if old is not None else None
                if old is None:
                    old = {"ticker": t, "target_share_pct": None, "active_in_model": None}
                    positions.append(old)
                old.update(c["position"])
                if was_pos is None and "active_in_model" not in c["position"]:
                    old["active_in_model"] = old["target_share_pct"] is not None
                skip = ("target_share_pct", "active_in_model") if "share_pct" in c else ()
                ch_keys = [k for k in old if k != "ticker" and k not in skip
                           and not _ie_same((was_pos or {}).get(k), old[k])]
                if ch_keys:
                    jr(f"ie_model.positions.{t}", {k: (was_pos or {}).get(k) for k in ch_keys},
                       {k: old[k] for k in ch_keys}, reason)
            if "share_pct" in c and not _ie_same(cur, c["share_pct"]):
                new = c["share_pct"]
                rec = stock_rec(t)
                rec["ie_old_pct"], rec["ie_new_pct"] = cur, new
                pos = find_pos(t)
                if pos is None and new is not None:
                    pos = {"ticker": t, "target_share_pct": None, "active_in_model": True}
                    positions.append(pos)
                if pos is not None:
                    if new is None and not any(pos.get(k) is not None for k in
                                               ("industry", "target_price_rub", "target_price_lt_rub")):
                        positions.remove(pos)              # чисто модельная бумага — как у Numbers, строки нет
                    else:
                        pos["target_share_pct"], pos["active_in_model"] = new, new is not None
                jr(f"stocks.{t}.ie_new_pct", cur, new, reason)
                hist.append({"ts": ts_s, "date": day, "ticker": t, "was": cur, "now": new,
                             "reason": reason, "source": source})
            if "note_ie" in c:
                rec = stock_rec(t)
                if rec.get("note_ie") != c["note_ie"]:
                    jr(f"stocks.{t}.note_ie", rec.get("note_ie"), c["note_ie"], reason)
                    rec["note_ie"] = c["note_ie"]
        if has_cash:
            if not _ie_same(model.get("cash_pct"), cash):
                jr("ie_model.cash_pct", model.get("cash_pct"), cash, None)
            model["cash_pct"] = cash
            if cash is not None:
                model["cash_ticker"] = IE_CASH_TICKER
        date_key = "general_date" if source == "webarchive" and page == "general" else "extraction_date"
        if ext is not None:
            model[date_key] = ext
        elif source == "webarchive":
            model[date_key] = day
        model["model_total_pct"] = round(sum(
            x["target_share_pct"] for x in positions if x.get("active_in_model") is not False
            and isinstance(x.get("target_share_pct"), (int, float))), 4)
        if plan_dump(plan) == before:                      # ничего не изменилось — файл не трогаем
            return 200, {"hash": cur_hash, "plan": plan, "entries": []}
        plan["updated_at"] = ts_s
        plan["updated_by"] = "hub-api"
        t0 = time.monotonic()
        try:
            new_hash = save_file(root, PLAN_FILE, plan_dump(plan), body["base_hash"])
        except TooLarge:
            return 413, {"error": "content too large"}
        except Conflict as cf:
            return 409, {"error": "hash mismatch", "current_hash": cf.current_hash, "plan": plan_read(root)[0]}
        t1 = time.monotonic()
        out = {"hash": new_hash, "plan": plan, "entries": entries}
        if entries:
            try:
                append_plan_journal(root, entries)
            except Exception as e:  # noqa: BLE001 — журнал не должен ронять уже записанную правку
                out["journal_error"] = str(e)
        out["timing_ms"] = {"save": round((t1 - t0) * 1000), "journal": round((time.monotonic() - t1) * 1000)}
    return 200, out


# ─────────────────── POST /api/pv/sync — вьюер портфеля одним запросом ───────────────────
# Случай 2026-10-23: телефон издалека — ~18 листингов + файлы по одному, каждый запрос 150–300 мс.
# Вьюер шлёт, какие версии файлов у него уже есть ({"have": {путь: версия}}), ответ — все папки
# вьюера (имя + версия) и содержимое только новых/изменившихся файлов. ТОЛЬКО ЧТЕНИЕ, тех же
# файлов, что вьюер и так читает через Caddy. Зона — пароль с любого IP (Caddy: /api/pv/* исключён
# из @api_trusted); здесь вдобавок требуется Authorization (вторая линия, если кто-то дойдёт мимо).
# Папки и шаблоны — те же, что loadHttpMode1 во вьюере, строка в строку (сторож — test_write_api).
PV_DIRS = (
    ("Portfolio/integrated-views/", r"^integrated-view-.*\.md$"),
    ("Portfolio/weekly-reviews/", r"^weekly-review-.*\.(yaml|yml|md)$"),
    ("Portfolio/stress/", r"^stress-\d{4}-\d{2}-\d{2}.*\.(yaml|yml|md)$"),
    ("Portfolio/stress/auto/", r"^recalc-stress-\d{4}-\d{2}-\d{2}.*\.(yaml|yml)$"),
    ("Portfolio/snapshots/", r"^portfolio-\d{4}-\d{2}-\d{2}.*\.json$"),
    ("Portfolio/reports/", r"\.md$"),
    ("Portfolio/decision-journal/", r"^(baselines|journal)\.json$|^report-\d{4}-\d{2}-\d{2}\.md$"),
    ("Portfolio/decisions/", r"^\d{4}-\d{2}-\d{2}T\d{4}-.+\.json$"),
    ("Portfolio/prices/", r"^daily-\d{4}\.jsonl$"),     # вьюер 5.2.0: дневной ряд цен закрытия (hub-notify) — график цены в карточке
    ("Portfolio/", r"^conditions\.yaml$|^conditions-state\.json$|^conditions-archive-\d{4}\.yaml$|^security-attrs\.json$"),
    ("macro-snapshots/", r"\.md$"),
    ("macro-snapshots/auto/", r"^ru-\d{4}-\d{2}-\d{2}\.json$"),
    ("macro-snapshots/inflation/", r"^(model|owner)\.jsonl$"),     # вьюер: недельная инфляция — файлы скилла и владельца, свежее по date
    ("monitor-reports/", r"^monitor-report-.*\.(yaml|yml)$"),
    ("forecasts/", r"\.(yaml|yml|md)$"),     # вьюер 3.63.0: md-отчёты прогнозов (часть «Предложения на аудит»)
    ("scenarios/", r"\.(yaml|yml|md)$|^horizons\.json$"),     # вьюер 3.109.0: тексты сценариев — окно из «Действий»; файл сроков сайта
    ("macro-chain/", r"^macro-scenarios-.*\.(yaml|yml)$"),     # вьюер 3.111.0: макро-вход стресс-теста — роль прогноза
) + tuple((f"domains/{d}/", r"\.md$") for d in (
    "geopolitics", "ru-sellside", "global-banks", "tech-ceo", "ru-macro", "commodity-agencies"))
PV_MAX_BYTES = 6 * 1024 * 1024     # содержимого за ответ; больше — more: true, вьюер спросит ещё
PV_MAX_HAVE = 20000


def pv_name(name):
    """Имя в адресе — как в листинге Caddy (url.PathEscape): ключи копии вьюера в обоих путях одни."""
    return urllib.parse.quote(name, safe="$&+:=@")


def pv_scan(root):
    """→ [(folder, имя-в-адресе, версия, полный путь)] по папкам вьюера; служебное — мимо."""
    out = []
    for folder, pat in PV_DIRS:
        rx = re.compile(pat)
        try:
            with os.scandir(os.path.join(root, folder)) as it:
                for e in it:
                    if e.name[:1] in (".", "@", "#") or not e.is_file(follow_symlinks=False):
                        continue
                    name = pv_name(e.name)
                    if not rx.search(name):
                        continue
                    st = e.stat(follow_symlinks=False)
                    out.append((folder, name, f"s:{st.st_size}:{st.st_mtime_ns}", e.path))
        except (FileNotFoundError, NotADirectoryError):
            continue
    return out


def pv_sync(root, have, max_bytes=PV_MAX_BYTES):
    """→ {"schema", "dirs": {папка: [[имя, версия], ...]}, "files": {путь: текст}, "more"}.

    Файл в ответе, если его версии у вьюера нет; набор содержимого — до max_bytes (первый файл —
    всегда, даже если он больше), остальное — more: true (вьюер повторит, добавив полученное в have).
    Папки нет — в dirs её нет (как 404 листинга: «папки нет, это норма»).
    """
    dirs, files, size, more = {}, {}, 0, False
    for folder, name, ver, full in pv_scan(root):
        dirs.setdefault(folder, []).append([name, ver])
        rel = folder + name
        if have.get(rel) == ver:
            continue
        try:
            n = os.path.getsize(full)
        except OSError:
            continue
        if files and size + n > max_bytes:
            more = True
            continue
        try:
            with open(full, "rb") as f:
                files[rel] = f.read().decode("utf-8", "replace")
        except OSError:
            continue
        size += n
    return {"schema": "pv-sync@1", "dirs": dirs, "files": files, "more": more}


class Handler(BaseHTTPRequestHandler):
    server_version = "HubWriteAPI/1.0"

    def _drain_body(self, cap=2 * 1024 * 1024):
        """Дочитать тело запроса перед отказом, который идёт ДО чтения тела (403 без Authorization): иначе сервер
        закрывает соединение, пока клиент ещё шлёт тело, и клиент видит обрыв (RemoteDisconnected / ERR_CONNECTION_RESET)
        вместо ответа. Звать только там, где тело ещё не читали. Тело больше cap не читается."""
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            return
        if 0 < length <= cap:
            try:
                self.rfile.read(length)
            except OSError:
                pass

    def _json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _zm_proxy(self, notify_path, limit, timeout, after=None):
        """/api/zm/csv-report|csv-apply|stmt-report → hub-notify (/internal/zm-*); тело {"id", "confirm"?}, ответ как есть.
        `after(id)` вызывается при любом исходе до ответа клиенту (сверка выписки стирает по нему файл)."""
        body = self._pv_json_body(limit)
        if body is None:
            return
        if not isinstance(body.get("id"), str) or not ZM_ID_RE.match(body["id"]):
            self._json(400, {"error": "bad id"})
            return
        try:
            code, obj = self._zm_proxy_call(body, notify_path, timeout)
        finally:
            if after:   # до ответа клиенту: страница получила отчёт — файла на диске уже нет
                after(body["id"])
        self._json(code, obj)

    def _zm_proxy_call(self, body, notify_path, timeout):
        """→ (код, объект ответа) hub-notify; сам ничего не отправляет."""
        payload = {"id": body["id"]}
        for k, types in ZM_PROXY_FIELDS[notify_path].items():
            if k in body:
                v = body[k]
                if not isinstance(v, types) or (isinstance(v, bool) and bool not in types) or \
                        (isinstance(v, str) and len(v) > 400):
                    return 400, {"error": f"bad field {k}"}
                payload[k] = v
        req = urllib.request.Request(NOTIFY_URL + notify_path, data=json.dumps(payload).encode("utf-8"),
                                     method="POST", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                code, raw = r.status, r.read()
        except urllib.error.HTTPError as e:
            code, raw = e.code, e.read()
        except OSError as e:
            return 502, {"error": "hub-notify недоступен", "detail": str(e)[:200]}
        try:
            return code, json.loads(raw.decode("utf-8"))
        except ValueError:
            return 502, {"error": "bad answer from hub-notify"}

    def _do_zm_stmt_upload(self):
        """POST /api/zm/stmt {name, b64} → ZenMoney/csv/stmt-incoming/<id>.<xlsx|csv>; id = ГГГГ-ММ-ДД-<sha256[:8]>.
        Тип — по содержимому (расширение имени не читается); смысл — отчёт hub-notify. Старые брошенные файлы стираются."""
        body = self._pv_json_body(ZM_STMT_MAX_BYTES)
        if body is None:
            return
        if not isinstance(body.get("b64"), str) or not isinstance(body.get("name", ""), str):
            self._json(400, {"error": "bad request body"})
            return
        try:
            raw = base64.b64decode(body["b64"], validate=True)
        except (binascii.Error, ValueError):
            self._json(400, {"error": "bad file", "detail": "b64: не base64"})
            return
        try:
            fmt = zm_stmt_sniff(raw)
        except ValueError as e:
            self._json(400, {"error": "bad statement", "detail": str(e)})
            return
        sha = hashlib.sha256(raw).hexdigest()
        id_ = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d") + "-" + sha[:8]
        rel = f"{ZM_STMT_DIR}/{id_}.{fmt}"
        full = os.path.join(ROOT, rel)
        with _write_lock:
            zm_stmt_sweep(ROOT)
            if not os.path.exists(full):
                _makedirs_owned(ROOT, os.path.dirname(full))
                _place(ROOT, rel, full, raw)
        self._json(200, {"id": id_, "name": body.get("name", ""), "sha256": sha, "format": fmt, "size": len(raw)})

    def _do_zm_csv_upload(self):
        """POST /api/zm/csv {name, b64} → ZenMoney/csv/incoming/<id>.csv; id = ГГГГ-ММ-ДД-<sha256[:8]>.
        Проверяется только форма (UTF-8, разделитель «;», обязательные колонки, даты); смысл — отчёт hub-notify."""
        body = self._pv_json_body(ZM_CSV_MAX_BYTES)
        if body is None:
            return
        if not isinstance(body.get("b64"), str) or not isinstance(body.get("name", ""), str):
            self._json(400, {"error": "bad request body"})
            return
        try:
            raw = base64.b64decode(body["b64"], validate=True)
        except (binascii.Error, ValueError):
            self._json(400, {"error": "bad file", "detail": "b64: не base64"})
            return
        try:
            info = zm_csv_check(raw)
        except ValueError as e:
            self._json(400, {"error": "bad csv", "detail": str(e)})
            return
        sha = hashlib.sha256(raw).hexdigest()
        id_ = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d") + "-" + sha[:8]
        rel = f"ZenMoney/csv/incoming/{id_}.csv"
        full = os.path.join(ROOT, rel)
        with _write_lock:
            zm_drop_applied(ROOT)
            if not os.path.exists(full):
                _makedirs_owned(ROOT, os.path.dirname(full))
                _place(ROOT, rel, full, raw)
        self._json(200, {"id": id_, "name": body.get("name", ""), "sha256": sha, **info})

    def _do_hd_post(self, path):
        """Зона здоровья, не-файловые записи (пароль с любого IP — Caddy @api_trusted исключает /api/hd/*):
        /api/hd/report — отчёт .md в reports/, /api/hd/marker-info — справка маркера, /api/hd/upload — файл в studies/."""
        upload = path == "/api/hd/upload"
        body = self._pv_json_body(HD_UPLOAD_BODY_MAX if upload else MAX_BYTES + 4096)
        if body is None:
            return
        fn = health_upload if upload else health_report_save if path == "/api/hd/report" else health_marker_info_save
        try:
            code, payload = fn(HEALTH_ROOT, body)
        except FileNotFoundError:
            code, payload = 404, {"error": "not found"}
        self._json(code, payload)

    def _do_zm_csv_state(self):
        self._json(200, zm_csv_state(ROOT))

    def _checked_path(self, raw, whitelist=None):
        """→ relpath или None (ответ уже отправлен)."""
        rel = norm_path(raw)
        if rel is None:
            self._json(400, {"error": "bad path"})
            return None
        if not is_allowed(rel, whitelist):
            self._json(403, {"error": "path not in whitelist", "path": rel})
            return None
        return rel

    def _internal(self):
        """Зона задач — только из docker-сети. Caddy добавляет X-Forwarded-For любому
        проксируемому запросу, значит, его наличие = запрос пришёл снаружи."""
        if self.headers.get("X-Forwarded-For"):
            self._json(403, {"error": "internal only"})
            return False
        return True

    def _do_eshop_refresh(self):
        """Кнопка «Обновить цены» (games.html) → hub-notify. Частоту (раз в 10 минут)
        держит hub-notify; здесь только проброс — общее правило Caddy для /api/*
        (доверенный IP свободно, извне по паролю) действует как для остальной записи."""
        req = urllib.request.Request(NOTIFY_URL + "/internal/eshop-refresh", data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                code, body = r.status, r.read()
        except urllib.error.HTTPError as e:
            code, body = e.code, e.read()
        except OSError as e:
            self._json(502, {"error": "hub-notify недоступен", "detail": str(e)[:200]})
            return
        try:
            self._json(code, json.loads(body.decode("utf-8")))
        except ValueError:
            self._json(502, {"error": "bad answer from hub-notify"})

    def _do_nsuid_lookup(self):
        """Поиск nsuid с games.html → hub-notify (/internal/nsuid-lookup); ответ как есть."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(min(length, 4096)) or b"{}"
        except ValueError:
            raw = b"{}"
        req = urllib.request.Request(NOTIFY_URL + "/internal/nsuid-lookup", data=raw, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                code, body = r.status, r.read()
        except urllib.error.HTTPError as e:
            code, body = e.code, e.read()
        except OSError as e:
            self._json(502, {"error": "hub-notify недоступен", "detail": str(e)[:200]})
            return
        try:
            self._json(code, json.loads(body.decode("utf-8")))
        except ValueError:
            self._json(502, {"error": "bad answer from hub-notify"})

    def _do_nsuid_fill(self):
        """Массовый подбор nsuid/обложек с games.html → hub-notify (/internal/nsuid-fill); ответ как есть."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(min(length, 65536)) or b"{}"
        except ValueError:
            raw = b"{}"
        req = urllib.request.Request(NOTIFY_URL + "/internal/nsuid-fill", data=raw, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                code, body = r.status, r.read()
        except urllib.error.HTTPError as e:
            code, body = e.code, e.read()
        except OSError as e:
            self._json(502, {"error": "hub-notify недоступен", "detail": str(e)[:200]})
            return
        try:
            self._json(code, json.loads(body.decode("utf-8")))
        except ValueError:
            self._json(502, {"error": "bad answer from hub-notify"})

    def _do_job_post(self, path):
        if not self._internal():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > MAX_BYTES + 4096:
                self._json(413, {"error": "body too large"})
                return
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            rel = norm_path(body["path"])
            if rel is None:
                raise ValueError
            if path == "/api/job/append":
                self._json(200, {"path": rel, "hash": append_line(ROOT, rel, body["line"])})
                return
            content, base_hash = body["content"], body["base_hash"]
            if not isinstance(content, str) or not (base_hash is None or isinstance(base_hash, str)):
                raise ValueError
        except PermissionError:
            self._json(403, {"error": "path not in whitelist"})
            return
        except TooLarge:
            self._json(413, {"error": "content too large"})
            return
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            self._json(400, {"error": "bad request body"})
            return
        if not is_allowed(rel, JOB_WHITELIST):
            self._json(403, {"error": "path not in whitelist", "path": rel})
            return
        try:
            new_hash = save_file(ROOT, rel, content, base_hash, validate=validate_job)
        except FileNotFoundError:
            self._json(404, {"error": "not found", "path": rel})
        except Conflict as c:
            self._json(409, {"error": "hash mismatch", "current_hash": c.current_hash})
        except TooLarge:
            self._json(413, {"error": "content too large"})
        except ValueError as e:
            self._json(400, {"error": "schema invalid", "detail": str(e)})
        else:
            self._json(200, {"path": rel, "hash": new_hash})

    def _zone(self, url_path):
        """Эндпоинт → (корень, whitelist, валидатор) или None.

        Порядок важен: /api/fd/* и /api/hd/* проверяются ДО общего /api/*,
        иначе более общая зона перехватила бы их безсхемной веткой.
        """
        if url_path in ("/api/hd/file", "/api/hd/save"):
            return HEALTH_ROOT, HEALTH_WHITELIST, validate_health
        if url_path in ("/api/fd/file", "/api/fd/save", "/api/fd/delete"):
            return FOOD_ROOT, FOOD_WHITELIST, validate_food
        if url_path in ("/api/gm/file", "/api/gm/save"):
            return ROOT, GAMING_WHITELIST, validate_gaming
        if url_path in ("/api/file", "/api/save"):
            return ROOT, WHITELIST, None
        return None

    def _pv_auth(self):
        if not self.headers.get("Authorization"):
            self._drain_body()   # отказ до чтения тела — дочитать, иначе клиент увидит обрыв вместо 403
            self._json(403, {"error": "auth required"})
            return False
        return True

    def _do_hub_settings(self):
        """POST /api/hub/settings — режим сайта «с ИИ / без ИИ» (hub-settings@1); пароль с любого IP, как /api/pv/*."""
        if not self._pv_auth():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 64 * 1024:
                self._json(413, {"error": "body too large"})
                return
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError
        except (ValueError, TypeError, json.JSONDecodeError):
            self._json(400, {"error": "bad request body"})
            return
        self._json(*hub_settings_post(ROOT, body))

    def _do_pv_plan_set(self):
        if not self._pv_auth():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > MAX_BYTES:
                self._json(413, {"error": "body too large"})
                return
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(body, dict) or "base_hash" not in body or not (
                    "changes" in body or {"path", "value"} <= body.keys()):
                raise ValueError
        except (ValueError, TypeError, json.JSONDecodeError):
            self._json(400, {"error": "bad request body"})
            return
        if "changes" in body:
            code, payload = plan_set_batch(ROOT, body["changes"], body.get("reason"), body["base_hash"])
        else:
            code, payload = plan_set(ROOT, body["path"], body["value"], body.get("reason"), body["base_hash"])
        self._json(code, payload)

    def _pv_json_body(self, limit):
        """Тело запроса /api/pv/* как JSON-объект; сам отвечает 413/400 и возвращает None."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > limit:
                self._json(413, {"error": "body too large"})
                return None
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError
            return body
        except (ValueError, TypeError, json.JSONDecodeError):
            self._json(400, {"error": "bad request body"})
            return None

    def _do_pv_macro_inflation(self):
        if not self._pv_auth():
            return
        body = self._pv_json_body(64 * 1024)
        if body is not None:
            self._json(*infl_add(ROOT, body))

    def _do_pv_plan_import(self):
        if not self._pv_auth():
            return
        body = self._pv_json_body(MAX_BYTES)
        if body is not None:
            self._json(*plan_import(ROOT, body))

    def _do_pv_plan_export(self, query):
        if not self._pv_auth():
            return
        fmt = (parse_qs(query).get("format") or ["json"])[0]
        code, data, mime, fname, h = plan_export(ROOT, fmt)
        if code != 200:
            self._json(code, data)
            return
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
        self.send_header("X-Plan-Hash", h)
        self.send_header("Access-Control-Expose-Headers", "Content-Disposition, X-Plan-Hash")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _do_pv_ie_import(self):
        if not self._pv_auth():
            return
        body = self._pv_json_body(IE_IMPORT_MAX_BYTES)
        if body is not None:
            self._json(*plan_ie_import(ROOT, body))

    def _do_pv_ie_set(self):
        if not self._pv_auth():
            return
        body = self._pv_json_body(MAX_BYTES)
        if body is not None:
            self._json(*plan_ie_set(ROOT, body))

    def _do_pv_cond_event(self, internal):
        if not self._pv_auth():
            return
        body = self._pv_json_body(16 * 1024)
        if body is not None:
            self._json(*cond_event(ROOT, body, internal))

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/pv/cond/state":
            if not self._pv_auth():
                return
            since = (parse_qs(url.query).get("since") or [""])[0].strip().replace(" ", "+") or None   # «+» в query = пробел
            self._json(*cond_state(ROOT, since))
            return
        if url.path == "/api/pv/plan/export":
            self._do_pv_plan_export(url.query)
            return
        if url.path == "/api/hub/settings":
            if not self._pv_auth():
                return
            self._json(*hub_settings_get(ROOT))
            return
        if url.path == "/api/hub/changes":
            if not self._pv_auth():
                return
            since = (parse_qs(url.query).get("since") or [""])[0].strip().replace(" ", "+") or None   # «+» в query = пробел
            self._json(*hub_changes(ROOT, since))
            return
        if url.path in ("/api/pv/plan", "/api/pv/plan/journal"):
            if not self._pv_auth():
                return
            if url.path == "/api/pv/plan":
                code, payload = plan_get(ROOT)
                self._json(code, payload)
                return
            try:
                limit = int((parse_qs(url.query).get("limit") or ["50"])[0])
            except ValueError:
                limit = 50
            since = (parse_qs(url.query).get("since") or [""])[0].strip().replace(" ", "+") or None   # «+» в query = пробел
            self._json(200, {"entries": plan_journal(ROOT, max(1, min(limit, 500)), since)})
            return
        if url.path == "/api/health":
            self._json(200, {"ok": True, "writable": os.access(ROOT, os.W_OK),
                             # отпечаток server.py работающего процесса — сверка с _nas/api/server.py в deploy.zsh
                             "api": {"code": API_CODE},
                             "health_writable": os.access(HEALTH_ROOT, os.W_OK),
                             "food_writable": os.access(FOOD_ROOT, os.W_OK),
                             "health_files": list(HEALTH_FILES),
                             # запись из страницы: отчёт .md, справка маркера, файл исследования (модули health-labs смонтированы)
                             "health_report": _health_skill_mods()[0] is not None,
                             "health_marker_info": _health_skill_mods()[1] is not None,
                             # ручная точка анализа (labs.json, только при ai_mode off): модуль правил смонтирован
                             "health_labs_manual": _labs_rules() is not None,
                             "health_upload": True,
                             "food_files": list(FOOD_FILES),
                             # оверлей игр (gaming-user@1): зона /api/gm/file|save
                             "gaming_files": list(GAMING_FILES),
                             # выгрузка CSV ZenMoney: POST /api/zm/csv, /api/zm/csv-report, /api/zm/csv-apply, GET /api/zm/csv-state
                             "zm_csv": True,
                             # сверка выписки банка: POST /api/zm/stmt, /api/zm/stmt-report (файл стирается после отчёта)
                             "zm_stmt": True,
                             # режим сайта «с ИИ / без ИИ»: ручки GET/POST /api/hub/settings есть
                             "hub_settings": True,
                             "hub_changes": True,
                             # маркер разделения рецептов по файлам
                             "food_recipe_dir": True,
                             # умеет создавать новый файл (base_hash=null) —
                             # без этого редактор не сохранит новый рецепт
                             "food_create": True,
                             # id рецепта опционален (идентичность = имя файла).
                             # Старый сайдкар требует id и отклонит файлы без него.
                             "food_id_optional": True,
                             # умеет удалять файл рецепта. Страница по этому
                             # признаку решает, рисовать ли кнопку удаления:
                             # без признака «старый сайдкар» неотличим от
                             # «нет прав» — оба отвечают 40x.
                             "food_delete": True,
                             # POST /api/fd/shop-add — строка текста → список
                             # покупок (шорткат iPhone), только продукты каталога
                             "food_shop_add": True,
                             # зона задач сайта (/api/job/*) и кнопка цен eShop
                             "site_jobs": True,
                             # whitelist /api/job/* знает пробную папку снапшотов
                             "pf_auto": True,
                             # POST /api/pv/sync — вьюер портфеля одним запросом (2026-10-23)
                             "pv_sync": True,
                             # GET /api/pv/plan, POST /api/pv/plan/set, GET /api/pv/plan/journal
                             "pv_plan": True,
                             # GET /api/pv/cond/state, POST /api/pv/cond/event[/internal] — состояние условий
                             "pv_cond_state": True,
                             # POST /api/pv/plan/ie-import, /api/pv/plan/ie-set — модель IE с сайта
                             "pv_ie": True,
                             # GET /api/pv/plan/export?format=json|xlsx, POST /api/pv/plan/import — база сайта (plan.json) целиком
                             "pv_import": True,
                             # доставка правок в синк: filestation | local; сбои с рестарта
                             "fs_mode": "filestation" if _FS is not None and any(FS_BASES.values()) else "local",
                             "fs_fallbacks": FS_STATS["fallbacks"],
                             "fs_last_fallback": FS_STATS["last"],
                             "versions_keep": VERSIONS_KEEP,
                             # hub-notify: версия и отпечаток кода, с которым он стартовал —
                             # deploy.zsh сверяет с _nas/notify/ (null — hub-notify не ответил)
                             "notify": _notify_health()})
            return
        if url.path == "/api/zm/csv-state":
            self._do_zm_csv_state()
            return
        if url.path == "/api/job/file":
            if not self._internal():
                return
            # чтение — зона задач плюс оверлей игр: цены eShop берут пороги и nsuid из Gaming/user-state.json;
            # запись оверлея отсюда закрыта (его пишет только страница через /api/gm/save)
            rel = self._checked_path((parse_qs(url.query).get("path") or [""])[0], JOB_WHITELIST + GAMING_WHITELIST)
            if rel is None:
                return
            try:
                content, h = read_file(ROOT, rel)
            except FileNotFoundError:
                self._json(404, {"error": "not found", "path": rel})
                return
            self._json(200, {"path": rel, "content": content, "hash": h})
            return
        if url.path == "/api/moex/quotes":
            self._do_moex_quotes(url)
            return
        zone = self._zone(url.path)
        if zone is None or not url.path.endswith("/file"):
            self._json(404, {"error": "unknown endpoint"})
            return
        root, whitelist, _ = zone
        raw = (parse_qs(url.query).get("path") or [""])[0]
        rel = self._checked_path(raw, whitelist)
        if rel is None:
            return
        try:
            content, h = read_file(root, rel)
        except FileNotFoundError:
            self._json(404, {"error": "not found", "path": rel})
            return
        except UnicodeDecodeError:
            self._json(415, {"error": "not utf-8", "path": rel})
            return
        self._json(200, {"path": rel, "content": content, "hash": h})

    def _do_moex_quotes(self, url):
        """GET /api/moex/quotes?boards=TQBR,TQOB[&fx=USD,KZT] — публично, только чтение."""
        raw = (parse_qs(url.query).get("boards") or ["TQBR"])[0]
        boards = list(dict.fromkeys(b.strip().upper() for b in raw.split(",") if b.strip()))
        bad = [b for b in boards if b not in MOEX_BOARDS]
        if not boards or bad:
            self._json(400, {"error": "unknown board", "boards": bad or [raw],
                             "allowed": list(MOEX_BOARDS)})
            return
        try:
            fx = parse_fx_param((parse_qs(url.query, keep_blank_values=True).get("fx") or [None])[0])
        except ValueError:
            self._json(400, {"error": "bad fx", "hint": "коды ^[A-Z]{3}$ через запятую, не больше %d" % FX_MAX_CODES})
            return
        try:
            self._json(200, moex_quotes(boards, fx=fx))
        except MoexError as e:
            self._json(502, {"error": str(e)})

    def _do_delete(self, root):
        """POST /api/fd/delete — единственная точка удаления во всём сайдкаре."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            raw, base_hash = body["path"], body["base_hash"]
            if not isinstance(base_hash, str):
                raise ValueError
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            self._json(400, {"error": "bad request body"})
            return
        # whitelist УЖЕ, чем на запись (FOOD_DELETABLE): products.json и
        # shopping.json через эту ручку не удалить.
        rel = self._checked_path(raw, FOOD_DELETABLE)
        if rel is None:
            return
        try:
            delete_file(root, rel, base_hash)
        except FileNotFoundError:
            self._json(404, {"error": "not found", "path": rel})
            return
        except Conflict as c:
            self._json(409, {"error": "hash mismatch", "current_hash": c.current_hash})
            return
        self._json(200, {"path": rel, "deleted": True})

    def _do_shop_add(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 4096:
                self._json(413, {"error": "body too large"})
                return
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            text, items, source = body.get("text"), body.get("items"), body.get("source")
            # Ровно одно из двух: text (строка) или items (список строк).
            if (text is None) == (items is None):
                raise ValueError
            if text is not None and not isinstance(text, str):
                raise ValueError
            if items is not None and not (isinstance(items, list)
                                          and all(isinstance(x, str) for x in items)):
                raise ValueError
            if not (source is None or isinstance(source, str)):
                raise ValueError
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            self._json(400, {"error": "bad request body", "message": "Нужно тело {\"text\": \"…\"} или {\"items\": [\"…\"]}."})
            return
        # Бизнес-исходы (не нашёл, уточните, уже есть) — 200 со status: шорткату
        # проще ветвиться по полю, чем разбирать коды HTTP.
        # И сбой (нет каталога, гонка) тоже 200 со status=error: на не-2xx
        # «Получить содержимое URL» может прервать шорткат, не показав message.
        self._json(200, shop_add(FOOD_ROOT, text, source=source or None, items=items))

    def _do_pv_sync(self):
        if not self.headers.get("Authorization"):
            self._drain_body()
            self._json(403, {"error": "auth required"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > MAX_BYTES:
                self._json(413, {"error": "body too large"})
                return
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            have = body.get("have") or {}
            if not isinstance(have, dict) or len(have) > PV_MAX_HAVE \
                    or not all(isinstance(k, str) and isinstance(v, str) for k, v in have.items()):
                raise ValueError
        except (ValueError, TypeError, AttributeError, json.JSONDecodeError):
            self._json(400, {"error": "bad request body"})
            return
        self._json(200, pv_sync(ROOT, have))

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/pv/sync":
            self._do_pv_sync()
            return
        if path in ("/api/pv/cond/event", "/api/pv/cond/event/internal"):
            self._do_pv_cond_event(path.endswith("/internal"))
            return
        if path == "/api/pv/plan/set":
            self._do_pv_plan_set()
            return
        if path == "/api/hub/settings":
            self._do_hub_settings()
            return
        if path == "/api/pv/macro/inflation":
            self._do_pv_macro_inflation()
            return
        if path == "/api/pv/plan/import":
            self._do_pv_plan_import()
            return
        if path == "/api/pv/plan/ie-import":
            self._do_pv_ie_import()
            return
        if path == "/api/pv/plan/ie-set":
            self._do_pv_ie_set()
            return
        if path == SHOP_ADD_PATH:
            self._do_shop_add()
            return
        if path in ("/api/job/save", "/api/job/append"):
            self._do_job_post(path)
            return
        # выгрузка CSV ZenMoney: пароль с любого IP (Caddy исключает /api/zm/* из @api_trusted), как /api/gm/*
        if path == "/api/zm/csv":
            self._do_zm_csv_upload()
            return
        if path == "/api/zm/csv-report":
            self._zm_proxy("/internal/zm-csv-report", 4096, 300)
            return
        if path == "/api/zm/stmt":
            self._do_zm_stmt_upload()
            return
        if path == "/api/zm/stmt-report":
            self._zm_proxy("/internal/zm-stmt-report", 4096, 120, after=lambda i: (zm_stmt_sweep(ROOT, only=i), zm_stmt_sweep(ROOT)))
            return
        if path == "/api/zm/csv-apply":
            self._zm_proxy("/internal/zm-csv-apply", 4096, 300)
            return
        if path == "/api/zm/rule":
            self._zm_proxy("/internal/zm-rule", 8192, 300)
            return
        if path == "/api/zm/trip":
            self._zm_proxy("/internal/zm-trip", 8192, 300)
            return
        if path == "/api/games/eshop-refresh":
            self._do_eshop_refresh()
            return
        if path == "/api/games/nsuid-fill":
            self._do_nsuid_fill()
            return
        if path == "/api/games/nsuid-lookup":
            self._do_nsuid_lookup()
            return
        if path in ("/api/hd/report", "/api/hd/marker-info", "/api/hd/upload"):
            self._do_hd_post(path)
            return
        zone = self._zone(path)
        if zone is None or not (path.endswith("/save") or path.endswith("/delete")):
            self._json(404, {"error": "unknown endpoint"})
            return
        root, whitelist, validator = zone
        # /delete есть только у зоны еды: остальные зоны такого эндпоинта не
        # знают и до сюда не доходят (_zone вернёт None → 404 выше).
        if path.endswith("/delete"):
            self._do_delete(root)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > MAX_BYTES + 4096:
                self._json(413, {"error": "body too large"})
                return
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            raw, content, base_hash = body["path"], body["content"], body["base_hash"]
            # base_hash=None — создание НОВОГО файла (рецепт по файлу: пока файла
            # нет, хэша тоже нет). Строка — правка существующего с защитой от
            # гонки. Иных типов не бывает.
            if not isinstance(content, str) or not (base_hash is None or isinstance(base_hash, str)):
                raise ValueError
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            self._json(400, {"error": "bad request body"})
            return
        rel = self._checked_path(raw, whitelist)
        if rel is None:
            return
        if validator is validate_gaming:
            content = normalize_gaming(content)
        if validator is validate_health and rel == "labs.json":
            self._json(*health_labs_manual_save(root, content, base_hash))
            return
        try:
            new_hash = save_file(root, rel, content, base_hash, validate=validator)
        except FileNotFoundError:
            self._json(404, {"error": "not found", "path": rel})
            return
        except Conflict as c:
            self._json(409, {"error": "hash mismatch", "current_hash": c.current_hash})
            return
        except TooLarge:
            self._json(413, {"error": "content too large"})
            return
        except ValueError as e:      # провалилась валидация схемы — файл не тронут
            self._json(400, {"error": "schema invalid", "detail": str(e)})
            return
        self._json(200, {"path": rel, "hash": new_hash})


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"hub write-api: root={ROOT} port={PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
