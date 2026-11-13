# Claude-Memory Layout

Единый реестр структуры `Claude-Memory/` на Synology Drive.

**Корень:** `~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/`
(NAS-оригинал: `/volume1/homes/hubuser/Claude-Memory`; вне облачных синков.
До миграции 2026-08-13 дерево жило в `Ext_gDrive/Claude-Memory` и синкалось
в Google Drive — оба факта историчны.)

---

## Структура

```
Claude-Memory/
├── INDEX.md                       # master-индекс; схема описана в шапке самого файла
├── _sync_log.md                   # лог операций; пишут save-to-library и memory-sync
│
├── domains/                       # сжатые trust-профили источников (.md, БЕЗ суффикса -audit)
│   ├── geopolitics/               #   {source-slug}-{period}.md
│   ├── ru-sellside/
│   ├── global-banks/
│   ├── tech-ceo/
│   ├── ru-macro/
│   └── commodity-agencies/
│
├── forecasts/                     # макро/геополитика: FCA (Tier 1) и FCA+HST (Tier 2); допустимы подпапки forecasts/<тема>/
│   └── INDEX.md
│
├── scenarios/                     # Shell 2×2 сценарии
│   └── INDEX.md
│
├── forecast-collections/          # fc-<source>-collection-<date>.md (от forecast-collector)
│
├── macro-snapshots/               # ru-<date>.md (от macro-ru-watcher)
│   └── auto/                      #   ru-<date>.md + .json — задача сайта без LLM (пробный месяц с 2026-10-21)
│
├── macro-chain/                   # macro-scenarios-<date>.yaml (+ macro-marginal-*): forecast_files{фактор: файл прогноза}
│
├── monitor-reports/               # monitor-report-<date>.yaml (от forecast-monitor, Phase 10.3)
│
├── reports/                       # полные ретро-аудиты + прочие human-facing сводки
│   ├── INDEX.md                   #   {YYYY-MM-DD}-{source-slug}-{period}.{md|docx}
│   └── ...                        #   парный сжатый профиль — в domains/{domain}/
│
├── Portfolio/                     # вся portfolio-ветка
│   ├── INDEX.md
│   ├── README.md
│   ├── snapshots/                 # portfolio-<date>.json (от portfolio-data-loader)
│   │   └── .versions/             # прежние версии снапшота дня перед перезаписью: portfolio-<date>.<generated_at>.json (archive_snapshot.py, 2026-10-20)
│   ├── stress/                    # stress-<date>-<source>.{md,yaml} (от portfolio-scenario-stress)
│   │   └── _archive-pre-v2/       #   стрессы схемы v1 до V2-CUTOVER (история, не трогать)
│   ├── forecasts/                 # per-stock catalyst forecasts (от advisor opt-in)
│   ├── weekly-reviews/            # weekly-review-<date>.yaml (от advisor opt-in)
│   ├── integrated-views/          # integrated-view-<date>.md (от portfolio-integrated-view)
│   ├── coherence-audits/          # coherence-audit-<date>.md + coherence-input-bundle-<date>.json (bundle Stage P; от portfolio-coherence-audit, решение A2)
│   ├── reports/                   # личные репорты от ru-portfolio-advisor (memory layer; viewer кнопка «📄 Reports»)
│   ├── sensitivity/               # sensitivity-артефакты macro-сценариев
│   ├── plan.json · plan-journal.jsonl  # план владельца и журнал его правок (пишет только hub-api)
│   ├── conditions.yaml            # определения условий `conditions@2` (пишет сам save-to-library apply_condition.py + сайт — условия владельца; живой файл — 1.2 до переключения)
│   ├── conditions-archive-{ГГГГ}.yaml  # годовой архив определений условий (читают вьюер и журнал решений вместе с текущими)
│   ├── conditions-state.json      # состояние условий `conditions-state@1`: только дописывание событий, пишет только hub-api
│   ├── decisions/                 # решения по бумаге `decision@1`, файл на запись `{ГГГГ-ММ-ДДTЧЧММ}-{KEY}.json` (пишет сам save-to-library decision_write.py)
│   ├── security-attrs.json        # справочник бумаг `security-attrs@1`: класс и дата листинга (пишет save-to-library security_attrs.py; сайт при «Сохранить» добавляет лишь новые ключи; появляется при переключении, шаг 17)
│   ├── security-types.json        # реестр типов бумаг с Мосбиржи (сборка сайта)
│   ├── known-splits.json          # реестр сплитов `known-splits@1` (пишет только `known_splits.py` загрузчика; нет файла — встроенный набор)
│   ├── decision-journal/          # журнал решений AIR-1: собирает сайт; ручные refusals/theses/incidents.yaml — save-to-library Workflow P
│   ├── gate-reviews.yaml          # УПРАЗДНЁН (schema.md §4.4): писателя нет, удаляется при переключении шага 17
│   ├── gate-reviews-archive-{year}.yaml  # УПРАЗДНЁН вместе с gate-reviews.yaml: удаляется при переключении шага 17 (история — в архиве шага 1)
│   ├── securities/                # УПРАЗДНЕНА (шаг 15): писателей нет, удаляется при переключении шага 17
│   ├── .backups/                  # только копии INDEX от update_index.py (`INDEX-{ГГГГ-ММ-ДД}-{ЧЧММ}.md`); прочее удалено при переключении
│   └── _bak-cutover-2026-08-03/   # бэкап V2-CUTOVER (история, не трогать)
│
├── travel-planner/                # скилл travel-planning (self-contained дерево)
│   ├── profiles/                  #   анкеты «кто едет»
│   └── trips/{trip}/              #   артефакты Stage 0..6 + экспорты; Stage 3–6 правятся с веба
│
├── Gaming/                        # скилл game-advisor
│   ├── taste-profile.yaml         #   SSOT профиля вкуса
│   ├── library_full.yaml
│   ├── watchlist.yaml             #   «Присматриваюсь» (game-advisor; nsuid_us — tools/eshop_lookup.py)
│   ├── eshop-prices.json          #   цены US eShop, задача сайта 08:30 МСК (eshop-prices@1)
│   └── recommendations/           #   рекомендации; пишет только скилл
│
├── Food/                          # раздел «Еда» Personal Hub (вне инвест-контура)
│   ├── products.json              #   каталог продуктов
│   ├── shopping.json              #   список покупок
│   ├── recipes/                   #   рецепт = файл; правятся с веба через /api/fd/*
│   └── inbox/                     #   входящие рецепты (кладёт человек)
│
├── ZenMoney/                      # скилл zenmoney-analyst (личные финансы)
│   ├── zenmoney-map.md            #   тонкая карта: исключения ролей, особые категории, поездки, проверки
│   └── audit/                     #   история аудитов учёта (пишет только scripts/audit_history.py)
│       ├── history.json           #     zenmoney-audit@1: агрегаты по месяцам + реестр замечаний по ID
│       ├── accepted.json          #     zenmoney-audit-accepted@1: принятые исключения
│       ├── spending.json          #     zenmoney-spending@1: итоги месяцев, категории и подкатегории, поездки, топ мест
│       ├── facts.json             #     zenmoney-facts@1: факты «на что взглянуть» (производный, пересчитывается при записи месяца)
│       ├── site-audit.json        #     zenmoney-site-audit@1: проверки сайта при записи выгрузки, по месяцам (только hub-notify; скилл читает как подсказку)
│       └── spending-rules.json    #     zenmoney-spending-rules@1: разовые траты и крупные обычные группы
│   └── csv/                       #   зона сайта: выгрузка CSV со страницы «Деньги» (docs/zenmoney/csv-site.md)
│       ├── stmt-incoming/<id>.<xlsx|csv>  #  ВРЕМЕННО: выписка банка для сверки на сайте (hub-api /api/zm/stmt); стирается сразу после отчёта, брошенная — через час; отчёт не хранится (docs/zenmoney/stmt-site.md)
│       ├── incoming/<id>.csv      #     загруженные выгрузки (hub-api /api/zm/csv)
│       ├── last.csv               #     последняя записанная выгрузка — база сравнения следующей
│       ├── reports/<id>.json      #     zm-csv-report@1 (+ <id>-runs.json — расчёт месяцев к записи)
│       └── aux/*.json             #     счета, признаки категорий, trip-ids, словарь мест, курсы ЦБ
│
├── Health/                        # раздел «Здоровье» (health-meds / health-labs)
│   ├── meds.json · vaccinations.json · vitals.json · studies.json
│   ├── labs.json · biomarkers-info.json   # labs: при `on` — только intake.py (labs_rules.py); при `off` — сайт, только точки source=manual и новый показатель (POST /api/hd/save, 403 при `on`); справку (what/up/down) пишут скилл и страница (merge_info)
│   └── reports/                   # отчёты .md: скилл (validate_report.py save) и страница (POST /api/hd/report)
│
├── stale_flags.yaml               # УПРАЗДНЁН (шаг 14): писателя нет, удаляется при переключении шага 17
│
├── _archive/data-structures/      # архивы цикла машиночитаемости: папка на прогон `<ГГГГ-ММ-ДД>T<ЧЧММ>-step<N>/` + MANIFEST.md (md5), хранить до 2027-05-01
│
├── _hub/                          # настройки сайта (служебная, не индексируется)
│   └── settings.json              #   hub-settings@1: ai_mode on|off, off_since, returned_at — пишет только hub-api (GET/POST /api/hub/settings)
│
├── _drafts/                       # черновики до сохранения (служебная, не индексируется): прогноз <topic>-<date>.md + .events.yaml;
│                                  #   сценарии scenario-<topic>-<date>.md + .events.yaml; стресс-тест <topic>-<date>.patch.yaml + .hst.md;
│                                  #   monitor-report-<date>.yaml; stress-<date>-<slug>.md + .yaml; integrated-view-<date>.md;
│                                  #   ретро-аудит <date>-<source-slug>-<period>.md + <source-slug>-<period>-profile.md
│
├── _nas/                          # хостинг Personal Hub: Caddyfile, docker-compose, api/server.py
│
├── tools/                         # HTML-страницы кабинета и offline-инструменты (не пишут скиллы)
│
└── _shared/                       # инфраструктурные данные (UPPER_CASE — не результаты)
    └── DEPENDENCY-MAP.md          # факторные зависимости макро-DAG
```

---

## Кто пишет / кто читает

| Папка / файл | Пишет | Читает |
|---|---|---|
| `domains/{domain}/` | `save-to-library` (Workflow A — сжатый профиль; для ретро-аудита — атомарно вместе с reports/, см. Workflow D) | `forecast-confidence-applier`, `memory-sync` |
| `forecasts/` | `save-to-library` (Workflow B) | `forecast-monitor`, `forecast-confidence-applier`, `macro-forecast-chain`, `revise-memory-remote` |
| `scenarios/` | `save-to-library` (Workflow C) | `forecast-monitor`, `revise-memory-remote` |
| `forecast-collections/` | `save-to-library` | `retrospective-forecast-audit` |
| `macro-snapshots/` | `macro-ru-watcher` напрямую (исключение D3, см. ниже) | `macro-forecast-chain` |
| `macro-snapshots/auto/` | задача сайта `hub-notify` (`macro_job.py` → `build_macro.py`) через `hub-api` `/api/job/*`; копии перезаписей — `.versions/` | вьюер (вкладка «Макро»: плитки и графики — основной ряд с 11.11, только `*.json`); `build_macro.py` (история z-score инфляции ЦБ) |
| `macro-snapshots/inflation/model.jsonl` | `macro-ru-watcher` — только `scripts/save_inflation.py` (дописывание; гейт `require_ai`, при «без ИИ» отказ кодом 3) | вьюер («Макро» → «Недельная инфляция»), hub-notify (срок годности) |
| `macro-snapshots/inflation/owner.jsonl` | `hub-api` — только `POST /api/pv/macro/inflation` (форма «Внести инфляцию», дописывание; пароль с любого IP, `/api/pv/*`) | вьюер, хаб (плашка свежести), hub-notify (push «Пора внести инфляцию»); страница берёт самую свежую по `date` запись из двух файлов — один файл, один писатель |
| `Portfolio/prices/` | задача сайта `hub-notify` (`prices_job.py`, будни 19:00 МСК, повтор 20:00) через `hub-api` `/api/job/*`: `daily-ГГГГ.jsonl`, одна строка на торговую дату — цены закрытия держимых бумаг и курсы ЦБ, только вперёд (без истории назад, без стоимости и XIRR); строка даты не перезаписывается; копии перезаписей — `.versions/` | пока никто (вьюер подключается следующим шагом; в `PV_DIRS` не входит) |
| `macro-chain/` | `save-to-library` | `portfolio-scenario-stress` |
| `monitor-reports/` | `save-to-library` (Workflow L) | (пользователь); `hub-notify` — `condition_findings[]` последнего отчёта → события состояния условий (шаг 7) |
| `reports/` | `save-to-library` (Workflow D — полные ретро-аудиты, атомарно с сжатым профилем в `domains/`; прочие human-facing сводки тоже сюда) | `retrospective-forecast-audit` (опц.), (пользователь) |
| `Portfolio/inputs/<YYYY-MM-DD>/` | импорт выгрузок на сайте (API-1b PR-6; в пробном режиме с 2026-10-21 входы сборок с сайта лежат в томе `notify_data` контейнера `hub-notify`, сюда не пишутся — пусто) | `portfolio-data-loader` (`build_snapshot.py`, Шаг 4б: последняя выгрузка ИИС-3) |
| `Portfolio/snapshots/` | `portfolio-data-loader` напрямую (исключение D3, см. ниже) | `ru-portfolio-advisor`, `macro-forecast-chain`, `portfolio-scenario-stress`, `portfolio-integrated-view` |
| `Portfolio/snapshots/auto/` | сборка снапшота с вьюера (пробный режим с 2026-10-21): `hub-notify` `pf_build.py` → `build_snapshot.py` без `--commit`, «Сохранить» → `hub-api` `/api/job/save` (`portfolio-<дата>-<ЧЧММ>-bal|trades.json` + `build-summary-…` с тем же суффиксом — несколько сборок на дату; файлы без суффикса — сохранения до 2026-10-22; копии перезаписей — `.versions/`) | никто из скиллов и вкладок вьюера (подпапка); пользователь — сверка с рабочими снапшотами. `portfolio-data-loader` по `--commit` (без `--working`) пишет сюда `portfolio-<дата>-<ЧЧММ>-skill.json` + `build-summary-…-skill.json` |
| `Portfolio/stress/` | `save-to-library`; `_archive-pre-v2/` — стрессы v1 до V2-CUTOVER, история | `ru-portfolio-advisor` (mode 8), `portfolio-integrated-view` |
| `Portfolio/weekly-reviews/` | `save-to-library` (opt-in от advisor) | `portfolio-integrated-view` |
| `Portfolio/integrated-views/` | `save-to-library` | (пользователь) |
| `Portfolio/reports/` | `ru-portfolio-advisor` (ad-hoc save workflow для Mode 3/4/5/6/7 и free-form запросов; см. SKILL.md «Ad-hoc save»), `save-to-library`, или пользователь напрямую. Формат `*.md` с шапкой `report@1` (schema.md §4.3: `schema_version`, `title`, `date`, `kind`, `mode_codes[]`, `tickers[]`, `recorded_at` + открытые поля `summary`, `author`, `mode`, …; проверка — `assemble_artifact.py validate-report`, блокирующая); необязательный блок `decisions:` — вход `decision_write.py from-report`. | viewer (кнопка «📄 Reports» в header), retrospective-forecast-audit (опц.) |
| `Portfolio/decisions/` | `save-to-library` — скрипт `decision_write.py` пишет файлы **сам** (формат `decision@1`, schema.md §3.1): один файл на запись `{ГГГГ-ММ-ДДTЧЧММ}-{KEY}.json` (имя = `id`, время — МСК записи), `--root <корень Claude-Memory>`, валидатор `ds_schemas.validate_decision`, временный файл + `os.replace`; файл уже есть — ошибка, не перезапись; без удалений. Команды: `from-report` (по блоку `decisions:` шапки сохранённого отчёта), `owner` (по слову владельца), `digest` (чтение). Блок `decisions:` в шапке после записи кодом не читается (срез) | `hub-notify` (`conditions_resolved[]` → `done`), журнал решений (`decision_journal.py`), выборки `decision_write.py digest` / `security_digest.py` / `prior_digest.py --decisions` / `assemble_artifact.py --root` (общий `decisions_read.py`: чтение файлов, гейт — обёрткой над модулем (б)); модуль (б) «последнее слово» `last_word.py` / `last-word.js` (шаг 11): движок «Сейчас» (`gate_aware_sizing.py --decisions`, `rebalance-engine.js`), `backfill_decisions.py verify`; вьюер (вкладка и окно «Решения», карточки) |
| `Portfolio/gate-reviews.yaml`, `gate-reviews-archive-{year}.yaml` | **Упразднены** (schema.md §4.4, шаг 8): писателей нет (`apply_gate_review.py`, `auto_maintain_gate_reviews.py` удалены); статус гейта считается из последнего решения (`decisions/`). Файлы остаются в данных до переключения (шаг 17, `decision.md` §4.2) и тогда удаляются после бэкфилла решений (шаг 9); копии — в архиве шага 1 | код сайта и скиллов больше не читает (вьюер — шаг 12, журнал решений — шаг 13, индекс бумаги удалён в шаге 15); остался только необязательный слой `gate_reviews` в `revise-memory-remote` (`validate_library.py`): без файла он пропускается |
| `Portfolio/coherence-audits/` | `portfolio-coherence-audit` напрямую (исключение D3, решение A2): `coherence-audit-<date>.md` и `coherence-input-bundle-<date>.json` (bundle Stage P) | (пользователь) |
| `Portfolio/decision-journal/` | `inputs.json`, `baselines.json`, `journal.json`, `report-{date}.md` — полная пересборка скриптом `decision_journal_update.py` загрузчика (детерминированно, без LLM, AIR-1 D-1); писатель — только сборка сайта после «Сохранить» (`pf_build.publish_journal`), `build_snapshot.py` журнал не запускает (шаг 15); годовые архивы `conditions-archive-ГГГГ.yaml` читаются вместе с текущими; входы: обзоры, снапшоты, `decisions/`, `conditions.yaml` (conditions@2) + `conditions-state.json`, `plan-journal.jsonl`, `security-types.json` (schema.md §4.5); `refusals.yaml`, `incidents.yaml`, `theses.yaml` — `save-to-library` (Workflow P, только дописывание), валидатор `ds_schemas.py refusals|theses|incidents` проверяет их до сборки; `incidents.yaml` журнал читает (`incidents_monthly.manual`) | `ru-portfolio-advisor` — выборкой `journal_digest.py` (вопросы об отказах, строка точности, эпизоды по бумаге), (пользователь) |
| `Portfolio/securities/` | **Упразднено** (schema.md §2, шаг 15): писателей нет (`securities_index.py`, `pf_build.publish_securities`, запись в whitelist hub-api удалены); бумагу читает выборка `security_digest.py` (stdout, без записи) через общие читатели `security_sources.py`. Папка с файлами остаётся в данных до переключения (шаг 17, `decision.md` §4.2) и тогда удаляется; копия — в архиве шага 1 | — |
| `Portfolio/security-types.json` | Справочник типов бумаг с Мосбиржи (`security-types@1.0`: тикер → `type` stock/bond/fund, `moex_type`, `moex_group`, `isin`, `fetched_at`; «нет на бирже» — `type: null`, перепроверка раз в 90 дней) — `portfolio-data-loader` (`security_types.py`, шаг сборки `build_snapshot.py`; в сеть ходит только сборка на сайте; у hub-notify том Claude-Memory только на чтение, поэтому сборка ведёт справочник в своём томе `/data/pf/security-types.json`, стартуя из этого файла, а сюда его выкладывает hub-api при «Сохранить» (`pf_build.save`, JOB_WHITELIST); исключение D3: производный справочник, без LLM) | `portfolio-data-loader` (`--types-cache` у возвратов и сборки), вьюер («Загрузки», карточка «Тип бумаги изменился») |
| `Portfolio/known-splits.json` | Реестр сплитов `known-splits@1`: `splits[] = {ticker, date (день возобновления торгов), ratio, note, added_at, added_by}` и `dismissed[]` — подозрения, признанные не сплитом. Единственный писатель — `known_splits.py` загрузчика (`add` / `dismiss`: проверка записи, резервная копия в `.backups/`, атомарная замена) и сайт теми же проверками (`POST /api/pf/splits`, кнопки панели сборки); вручную не править. Читают все шаги сборки снапшота (`--splits-file`, по умолчанию этот файл); файла нет — действует встроенный набор, невалидный файл останавливает сборку. | `portfolio-data-loader` (сборка сайта) |
| `Portfolio/stress/auto/recalc-<стресс>.yaml` | Числа стресса, пересчитанные сайтом без модели (`stress_recalc.py`): суждения — из стресс-файла скилла `<стресс>`, снапшот — последний сохранённый, веса — из файла весов, если он задан на сроки этого стресса. Схема как у стресс-файла + блок `recalc {source_stress, snapshot_id, weights_source, reason, narrative_stale, needs_judgment, dropped}`. Один текущий файл на стресс скилла, перезаписывается; стресс-файл скилла сайт не трогает. Пишет только hub-notify (после «Сохранить» снапшота и после смены весов). | вьюер («Стресс») |
| `scenarios/horizons.json` | Сроки прогнозов и стресса (`horizons@1`): `horizon_ends` (`hN` → дата), `primary_horizon`, `set_at`, `reason`, `history` (20 прежних состояний). **Единственный писатель — сайт** (`stress_job.post_terms`, «Стресс» → «Настройки стресса»); читают `stress_build.py` (сроки прогона, без автосдвига), тексты `forecast-confidence-applier` и `macro-forecast-chain` (даты горизонтов), `stress_digest.py` советника и `aggregate_positions.py` интегрированного вида (предупреждение при расхождении со стрессом), вьюер. Нет файла — сроки прошлого стресса |
| `scenarios/stress-weights-<матрица>.json` | Веса сценариев, заданные владельцем на сайте на СРОКИ СТРЕССА (`stress-weights@1`): `horizon_ends`, `axis_beliefs` (ответы на два вопроса по осям на каждый срок), `weights`, `set_at`, `reason`, `weight_history`. Пишет только сайт (`POST /api/pf/stress/weights`, «применить» с причиной). Единый источник действующих весов: макро-цепочка (RECALIBRATE) берёт их отсюда же, интерполируя на даты прогнозов; веса матрицы `scenarios/<матрица>.yaml` остаются исходными на её дату и этим файлом не меняются. Сроки стресса изменились — в стрессе файл не применяется, владелец задаёт веса заново. | `stress_recalc.py`, `stress_build.py`, `recalibrate.py`, вьюер |
| `Portfolio/security-attrs.json` | Справочник бумаг `security-attrs@1` (schema.md §4.8): `by_key[тикер\|ISIN] = {ticker_class, listed_at, note, updated_at, updated_by}` — у каждой бумаги реестра типов и снапшота, «нет класса» = `null`. Валидатор — `ds_schemas.py` (`validate_security_attrs`). Писатели: скрипт `security_attrs.py` save-to-library и сайт при «Сохранить» снапшота (hub-notify `pf_build.save_attrs` через hub-api `/api/job/save`, та же функция `add_missing`: ТОЛЬКО отсутствующие ключи держаний, `ticker_class: null`, `listed_at` из `holdings[].listing_date`, `updated_by: script`; существующие записи не трогает никогда, файла нет — не создаёт). Скрипт (Workflow Q: `set --root … --key … [--class …] [--listed-at …] [--note …] --by <код actor: owner, mode_N, script>`, `get`, `list [--class ipo]`; валидатор до записи, временный файл + `os.replace`, `updated_at`/`updated_by` ставит скрипт; файла нет — ошибка «справочник не заполнен», файл скрипт не создаёт). Разовое заполнение — `tools/data-structures/migrations/init_security_attrs.py` во временный корень (шаг 9); в рабочую папку файл кладёт оркестратор при переключении (шаг 17) | модуль (б) (IPO-пауза: `ticker_class: ipo` и `listed_at` + 8 кварталов) — движок «Сейчас» (`gate_aware_sizing.py --security-attrs`, `rebalance-engine.js`), `decisions_read.gate` (`load_attrs`); вьюер (карточка, плашка «IPO · до …»); выборка `security_digest.py` советника (блок `attrs`), `security_attrs.py get/list` |
| `Portfolio/plan.json` | План портфеля (`plan@1.0`, `numbers-exit-plan.md` §3.1): классы, матрица, корзины облигаций, план/статус/заметки по акциям, модель IE, ручные позиции. Этап 1 (2026-10-27): файл пишет владелец командой `numbers_to_plan.py --portfolio … --out`, загрузчик читает его рядом с Numbers и кладёт в снапшот `plan_check` (сверка); с этапа 2 (27.10.2026) единственный писатель с сайта — `hub-api` `/api/pv/plan/set` (исключение D3 по образцу `Food/`; `base_hash`, копии в `.versions/`), журнал — `Portfolio/plan-journal.jsonl` (только дописывание: `ts, who, path, was, now, reason, decision_id`; `ts` — МСК с поясом `ГГГГ-ММ-ДДTЧЧ:ММ:СС+03:00`, `decision_id` — `null` у каждой новой строки, связь с решением ставится позже; `plan.updated_at` — время того же формата; запись локальная и мгновенная, затем файл целиком уезжает в зеркало Мака фоновым потоком через File Station — читают скрипты советника; сбой File Station — откат на локальную запись и счётчик `fs_fallbacks` в `/api/health`; `GET /api/pv/plan/journal?since=<ISO+03:00>` отдаёт только строки с `ts` позже; старые строки с `Z` — после миграции `tools/data-structures/migrations/migrate_plan_journal_ts.py`); `numbers_to_plan.py --out` после правок сайта отказывается перезаписывать без `--force`; поля модели IE (`ie_model`, `stocks.*.ie_new_pct/ie_old_pct`, `ie_history[]`) с этапа 3 (27.10.2026) пишет только `/api/pv/plan/ie-set` (окно доли IE и импорт страницы IE через `ie-import`); с этапа 5 (27.10.2026) `hub-api` пишет план и целиком — `/api/pv/plan/import` (JSON-файл с diff и причиной, одна строка `kind: import` в журнале) |
| `Portfolio/conditions.yaml` | `save-to-library` — скрипт `apply_condition.py` пишет файл **сам** (формат `conditions@2`, schema.md §3.2); **+ сайт — только условия владельца** (`source.kind: owner`, `kind: watch`, `notify_only`): `POST /api/pf/condition` (hub-notify `condition_job.py`) собирает запись тем же `apply_condition.py --emit` и кладёт файл через hub-api `/api/job/save` с `base_hash` (add / withdraw; чужие условия сайт не снимает): `--root <корень Claude-Memory>`, валидатор `ds_schemas.py` (общий модуль, в скилл его кладёт pack.sh) на весь документ, временный файл + `os.replace`, без удалений (правка = новая версия с `superseded_by`, снятие = `withdrawn`); модель файл инструментом Write не пишет. Состояние условий — отдельный файл `conditions-state.json` (пишет только hub-api), скрипт его только читает. Живой файл на mount до переключения (`decision.md` §4.2) — формата 1.2 (`touched`/`history[]`); hub-api пишет его только по запросу hub-notify (`/api/job/save`, условия владельца с сайта) | только через модуль (а) или выборки: `apply_condition.py` (list/digest/crosscheck), `ru-portfolio-advisor` (выдачей скриптов, файл не открывает), viewer, `hub-notify`, `forecast-monitor` (`monitor_alerts.py`: `report_published`/`event`), `decision_journal.py`, `gate_aware_sizing.py`, `security_digest.py` |
| `Portfolio/conditions-state.json` | **только `hub-api`** (шаг 4 цикла машиночитаемости, schema.md §3.3): `POST /api/pv/cond/event` (сайт: `owner_mark`, `done` by owner, `reopened`) и `POST /api/pv/cond/event/internal` — события уведомителя и задач NAS (контейнер `hub-notify`, шаг 7): уведомитель — `fired` (касание порога цены, `data.price`; наступившая дата и закрытое окно отчёта, `data.by_deadline`, у окна `data.note: «не найдено»`), `expired` (`valid_until` прошёл); задачи NAS — `event_found` + `fired` с `data.doc` (находка `condition_findings[]` отчёта монитора), `done` by site с `data.decision_id` (новое решение с `conditions_resolved[]`; `done` по сделке — отложен); у всех `version` последнего определения; только дописывание событий `{condition_id, version?, event, at, by, data}`, `at` ставит сервер (МСК, `+03:00`); повторы для той же пары id+version (незакрытый `fired`, любое после терминального, `event_found` с тем же `doc`) сервер отбрасывает; локально сразу, в зеркало — фоновым переносом через File Station | вьюер (sync, `GET /api/pv/cond/state?since=`), журнал решений, `hub-notify` (читает с тома `/srv` только на чтение вместе с `conditions.yaml` модулем (а), пишет — только через API). Определения и состояние читатели объединяют только модулем (а) `conditions_merge.py` (в `.skill` — `scripts/`, на странице — `assets/conditions-merge.js`, `window.CM`); переход читателей — шаги 7 (уведомитель), 10 (скрипты советника), 11 (движок «Сейчас», `constraint_engine.py`), 12 (вьюер) |
| `Portfolio/conditions-archive-{ГГГГ}.yaml` | годовой срез определений условий (schema.md §3.2); писателя в коде пока нет (годовой срез при обслуживании — TODO «годовой архив условий»), файлов нет | вьюер (строки модуля (а) — закрытая история видна), журнал решений (старые окна видят закрытые условия) |
| `_archive/data-structures/<дата>T<ЧЧММ>-step<N>/` | `tools/data-structures/archive_pre_ds.py --run` (оркестратор перед мигрирующим шагом; копии с сохранением путей + `MANIFEST.md`: путь, md5, размер, шаг); новая папка на каждый прогон, рабочая папка не трогается; хранение до 2027-05-01 | `archive_pre_ds.py verify`; разовые миграции (`backfill_decisions.py`, `init_security_attrs.py`) — архивные копии носителей |
| `travel-planner/` | `travel-planning` (скилл), server.py (web-правки Stage 3–6) | `travel-planning`, страница travel |
| `Gaming/` | `game-advisor` (скилл) | `game-advisor`, страница games |
| `Gaming/user-state.json` | только сайт (`/api/gm/save`, `gaming-user@1`, `base_hash`, `.versions/`) — статус (4) и флаг «играл в демо» (`demo`, только у некупленной), прохождение (`progress`, только у куплена и игр с `demo`), оценка (4), часы, заметка, пороги цены, nsuid/steam_appid, обложка; записи из YAML скилла сюда не переносятся (карта — `skills/game-advisor/references/data-layout.md`); скилл `game-advisor` читает как источник человеческих полей, не пишет | страница games, `game-advisor`, задача `eshop.py` (пороги и nsuid поверх watchlist) |
| `Gaming/eshop-prices.json` | задача сайта `hub-notify` (`eshop.py`) через `hub-api` `/api/job/*`, кнопка «Обновить цены» | `game-advisor` (доверяет 24 ч), страница games |
| `_jobs/log-<YYYY-MM>.jsonl` | `hub-api` `/api/job/append` — журнал прогонов задач сайта (только дописывание) | (пользователь, разбор пробного месяца) |
| `Food/` | server.py (`/api/fd/*`), человек (inbox) | страница food, скрипты кухни |
| `Health/` | server.py (`/api/hd/*`: живые JSON; `reports/*.md` и `biomarkers-info.json` — теми же `validate_report.check` / `merge_info`, что у скилла; `studies/` — `POST /api/hd/upload`, без перезаписи), `health-meds`/`health-labs` (мердж-скрипты) | страница health |
| `ZenMoney/` | человек (или Claude по прямой просьбе, вне скилла); скилл сам не пишет — кроме `ZenMoney/audit/` (`audit_history.py`, исключение D3 2026-10-05) и строк `zenmoney-map.md` (`map_edit.py` после «да» на diff, 2026-10-06) | `zenmoney-analyst`, страница `money.html` (план) |
| `ZenMoney/audit/site-audit.json` | только сайт (hub-notify `zm_csv.py` при записи выгрузки; агрегаты проверок, без сумм и названий) | `zenmoney-analyst` (подсказка при «закрой месяц», не пишет), страницы money и hub |
| `ZenMoney/audit/spending-rules.json` | скилл (`audit_history.py rules`) и сайт — только правила `one_off` с id `site-…` («Разовая» в отчёте выгрузки, hub-notify `/internal/zm-rule`) | `zenmoney-analyst` |
| `ZenMoney/audit/{spending,trips,facts}.json` | два писателя, один код: скилл (`audit_history.py`) и сайт (hub-notify `zm_csv.py` через `/api/job/save`, после отчёта без стопов и «да» владельца; `coverage.history: csv-site`) | `zenmoney-analyst`, страница money |
| `ZenMoney/csv/` | только сайт (hub-api `/api/zm/*`, hub-notify); `aux/` — копия с Mac, словарь мест обновляет рецепт Claude Code `docs/zenmoney/csv-recompute.md` | hub-notify; скиллы не читают |
| `_hub/settings.json` | только `hub-api` (`/api/hub/settings`, `base_hash`, `.versions/`, File Station) | ui-kit страниц, hub-notify (с NAS), скрипты-писатели Mac через общий модуль `hub_settings.py` (сеть → файл зеркала); нет файла — режим `on` |
| `_drafts/` | `forecast-confidence-applier` (Шаг 6: `<topic>-<forecast_date>.md` + `.events.yaml` — отчёт и блок Events YAML до сохранения), `scenario-builder` (Шаг 5: `scenario-<topic>-<date>.md` + `.events.yaml`), `hypothesis-stress-tester` (Шаг 6: `<topic>-<date>.patch.yaml` — блок patch, + `.hst.md` — полный текст), `forecast-monitor` (Шаг 7.5: `monitor-report-<date>.yaml`), `portfolio-scenario-stress` (Шаг 6: `stress-<date>-<slug>.md` + `.yaml`), `portfolio-integrated-view` (Шаг 6: `integrated-view-<date>.md`), `retrospective-forecast-audit` (`<date>-<source-slug>-<period>.md` — полный отчёт, + `<source-slug>-<period>-profile.md` — сжатый профиль); имена — те же, что в библиотеке (у профиля снимается `-profile`); в чат эти генераторы печатают выжимку; служебная зона: не индексируется, в `_sync_log.md` не попадает, сторожа библиотеки её не проверяют | `save-to-library` (Workflow B1.0 — пара прогноза, B1.2/B1.3 — патч HST, C1.0 — пара сценариев, L1.0 — monitor-report, E1.0 — стресс, G1.0 — интегрированный вид, D1.0 — ретро-аудит; приёмка — `promote_draft.py` (`promote-draft`): сборка, валидация, запись, INDEX, `_sync_log.md`; черновик удаляется при приёмке) |
| `_nas/` | вручную / деплой | docker (Caddy + hub-api) |
| `_nas/api/` (кодлисты), `_nas/notify/pdl/` (общие модули схемы: кодлисты с загрузчиком, `time_msk.py`, модуль (а) `conditions_merge.py`, `ds_schemas.py`) | `tools/deploy.zsh` — копии общих модулей репозитория (schema.md §3.4; правка только в репозитории) | hub-api (допустимые `user_plan`/`user_status` плана), hub-notify (слова вердиктов в push, условия только модулем (а), решения — валидатором `decision@1`), журнал решений сборки сайта |
| `_shared/` | вручную / при ревизии | все скиллы с данными о мире |
| `INDEX.md` (master) | `save-to-library`, `memory-sync` | `revise-memory-remote`, `forecast-confidence-applier` |
| `_sync_log.md` | `save-to-library`, `memory-sync` | `revise-memory-remote` |
| `tools/` | вручную (пользователь, deploy.zsh) | (пользователь) |

**Правило D3:** никакой скилл, кроме `save-to-library` и maintenance-скиллов
(`revise-memory-remote`, `revise-memory-local`, `memory-sync`), не делает Write
в Claude-Memory напрямую. Все остальные генерируют артефакт в чат,
пользователь явно вызывает save-to-library.

**Запись скриптами save-to-library** — не исключение, а форма записи самого `save-to-library`: решения
(`decision_write.py`), определения условий (`apply_condition.py`) и справочник бумаг (`security_attrs.py`) скрипт
пишет на mount сам (корень `--root`, валидатор, временный файл + `os.replace`, без удалений; `transport-layer.md`).
Модель эти файлы не читает и не пишет инструментами — только выдачей скриптов.

**Задокументированные исключения D3 (observation-объекты, не аналитические артефакты):**

- **`portfolio-data-loader`** пишет `Portfolio/snapshots/portfolio-{date}.json` напрямую.
  Обоснование: loader — детерминированный data layer без LLM-интерпретации, артефакт —
  input для downstream-скиллов (advisor, stress, integrated-view), а не human-facing отчёт.
  Журнал решений `Portfolio/decision-journal/` скрипт загрузчика пересобирает только в сборке сайта после
  «Сохранить» (ручные `refusals/incidents/theses.yaml` — save-to-library Workflow P).

- **Генераторы артефактов** (`forecast-confidence-applier`, `scenario-builder`, `hypothesis-stress-tester`,
  `forecast-monitor`, `portfolio-scenario-stress`, `portfolio-integrated-view`, `retrospective-forecast-audit`)
  пишут черновик в `_drafts/` (служебная зона, не библиотека) до вывода в чат; в библиотеку его переносит
  save-to-library (Workflow B1.0, B1.2/B1.3, C1.0, D1.0, E1.0, G1.0, L1.0) командой `promote_draft.py`, черновик
  удаляется при приёмке. Четыре последних печатают в чат только выжимку — тело артефакта через вывод модели не проходит.

- **`macro-ru-watcher`** пишет `macro-snapshots/ru-{date}.md` и `macro-snapshots/inflation/model.jsonl` (скрипт `save_inflation.py`) напрямую.
  Обоснование: атомарный observation-снапшот без интерпретации, используется как
  input для macro-forecast-chain. Прохождение через save-to-library добавило бы лишний
  шаг подтверждения без выгоды.

- `forecast-monitor` в библиотеку не пишет (только черновик в `_drafts/`): `stale_flags.yaml` **упразднён** (шаг 14) — свежесть по датам
  самих прогнозов, пробой — `factor_breach` сохранённого отчёта монитора; файл в архиве, из корня удаляется при
  переключении.

Снапшоты в master `INDEX.md` и `_sync_log.md` не попадают (у этих файлов писатели —
`save-to-library` и `memory-sync`). След сборок и сохранений — журнал задач сайта
`_jobs/log-ГГГГ-ММ.jsonl` (`pf_build`, `pf_save`), сводки `Portfolio/snapshots/auto/build-summary-*`
и прежние версии `Portfolio/snapshots/.versions/`; список снапшотов — `ls Portfolio/snapshots/`.

---

## Примечание о Case

- Все папки и файлы — **lowercase kebab-case** (исключение: `INDEX.md`).
- `_shared/` — UPPER_CASE имена файлов (`DEPENDENCY-MAP.md` и т.п.).
- Устаревшие имена: `Scenarios/` → `scenarios/`, `Portfolio-Snapshots/` → `Portfolio/snapshots/`,
  `Macro-Snapshots/` → `macro-snapshots/`, `Macro-Chain/` → `macro-chain/`.
