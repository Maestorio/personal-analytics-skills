# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Обзор репозитория

Коллекция скиллов Claude Code (slash-команды) для личных инвестиционных и прогнозных задач. Каждый скилл — отдельная директория с `SKILL.md` (определение скилла) и `references/` (файлы, загружаемые по требованию внутри скилла).

Архитектурные решения зафиксированы в `docs/investment/_cross-cutting/plan.md`. Будущий контур Portfolio Integrated View — в `INTEGRATION-DOCS/00-MASTER-PLAN.md`.

**Документация по 17 скиллам контура** живёт в `docs/investment/` (поддомены `portfolio/` · `forecasting/` · `memory/` + `_cross-cutting/`). Точка входа и каталог `skill→доки` — `docs/investment/README.md`. Перед правкой конкретного скилла можно вызвать проектный скилл-навигатор `/investment-docs <скилл|домен>` (`.claude/skills/investment-docs/`, рядом с `travel-stage-builder`) — он грузит только релевантную документацию. Документация `travel-planning` — отдельным деревом в `docs/travel-planning/` (точка входа и каталог «тема→доки» — `docs/travel-planning/README.md`; навигатор `/travel-docs <стадия|тема>` — `.claude/skills/travel-docs/`). Дизайн-контур HTML-страниц (Personal Hub, портфельный вьюер, дизайн-система/токены, HTML-экспорт travel, хостинг Caddy/API) — навигатор `/design-docs <тема>` (`.claude/skills/design-docs/`; SSOT дизайн-системы — `tools/design-reference/INDEX.md`). Раздел «Еда» как предметная область (страница, БД продуктов/рецептов на Synology, инструкция генератора рецептов и справка по мультиварке, скрипты кухни, зона записи `/api/fd/*`) — отдельный навигатор `/food-docs <тема>` (`.claude/skills/food-docs/`): он не тянет дизайн-контур ради правки рецепта. Контур ZenMoney (скилл `zenmoney-analyst`, аудит и статистика, история `ZenMoney/audit/`, карта, CSV-пересчёт) — навигатор `/zenmoney-docs <тема>` (`.claude/skills/zenmoney-docs/`); вид страницы «Деньги» — у `/design-docs money`.

## Запуск тестов

Исполняемый код — Python-скрипты внутри скиллов (`skills/*/scripts/`) и `tools/`. Тесты запускаются из корня
репозитория **запускателем по реестру**:

```bash
python3 tools/run_tests.py --tier fast        # без браузера, -j 4 — на каждый коммит
python3 tools/run_tests.py --tier browser     # Playwright, -j 2 — перед выкладкой
python3 tools/run_tests.py                    # полный (fast, затем browser) — закрытие шага, общие ассеты
python3 tools/run_tests.py zenmoney-analyst   # подстрока пути (ИЛИ); --group invest|health, --list, -x
```

Агент гоняет только целевые файлы; группы, ярусы и полный реестр — оркестратор.

**Реестр `docs/test-registry.md` — единственный список тестов** (команда + аннотация: история дефектов,
контракты, что закрывает тест). Перед правкой скилла прочитай блоки его тестов там. Новый тест — блок
в реестре (аннотация `# …` + строка `python3 …`); в CLAUDE.md тесты не перечисляются. «Прогнал все тесты»
= `run_tests.py` без фильтров. Интерпретатор запускатель выбирает сам (pyenv 3.12.9; см. `--python`).

Зависимости: `numbers-parser`, `openpyxl`, `pyyaml`. Установка: `pip install numbers-parser openpyxl pyyaml --break-system-packages`.
`compute_per_position.py` в режиме `--regression-mode moex` (SS-1, эмпирические беты через OLS) требует `numpy` + сеть (ISS MOEX + ЦБ); режим `priors` (default) — stdlib only. Установка: `pip install numpy --break-system-packages`.
PDF-экспорт (`scripts/export/`) требует `reportlab` (+опц. `matplotlib` для DejaVu-шрифта; для **карты Stage 6** matplotlib обязателен — без него PDF строится без карты): `pip install reportlab matplotlib --break-system-packages`.
Stage 6 геокодер (`scripts/geocode.py`) — stdlib only, читает забандленный газетир `skills/travel-planning/scripts/data/gazetteer.json`; контур стран для карты — `scripts/export/data/ne_countries.geojson`.
Скрипты `weighted_consensus.py`, `monitor_alerts.py`, `validate_library.py`, `sync_planner.py`, `retro_metrics.py`, `coverage_report.py`, `assemble_artifact.py`, `aggregate_positions.py`, `similarity_score.py`, `parse_dr_cards.py`, `aggregate_pois.py` зависимостей не требуют (только stdlib).

## Архитектура

### Пайплайн скиллов (данные идут слева направо)

```
macro-ru-watcher ──────────────────────────────────────────────────────┐
forecast-collector → retrospective-forecast-audit                      │
scenario-builder ─────────────────────────────────────────────────┐    │
forecast-confidence-applier ──────────────────────────────────────┤    │
                                                                   ↓    ↓
portfolio-data-loader → ru-portfolio-advisor       portfolio-scenario-stress
                      ↑                                            ↑
                      └─ macro-forecast-chain ─────────────────────┘

portfolio-integrated-view ← snapshot + stress YAML + weekly-review YAML (read-only синтез)
portfolio-coherence-audit ← ВСЕ артефакты включая integrated-view (мета-слой, Fable deep-pass)

Сохранение: save-to-library → Claude-Memory/
Синхронизация: memory-sync → memory_user_edits [lib]-записи
Обслуживание: revise-memory-local, revise-memory-remote, forecast-monitor
```

**Исключения D3** (само правило — в «Хранилище данных»): `portfolio-data-loader` пишет `Portfolio/snapshots/portfolio-{date}.json` напрямую как pure data layer (детерминированный, без LLM-интерпретации; артефакт — input для downstream, не human-facing отчёт); журнал решений `Portfolio/decision-journal/` собирает только сайт (ручные входы — save-to-library Workflow P). Подробности — `_shared-references/claude-memory-layout.md`. Второе (решение A2): `portfolio-coherence-audit` пишет `Portfolio/coherence-audits/coherence-audit-{date}.md` напрямую — в файл, в чат только TL;DR. Третье: `zenmoney-analyst` пишет `ZenMoney/audit/` (только агрегаты) единственным писателем `audit_history.py` и строки карты `ZenMoney/zenmoney-map.md` только скриптом `map_edit.py` после «да» на показанный diff. Четвёртое: `ZenMoney/stmt-places.json` (словарь мест импорта выписок) — только командой `stmt_propose.py places-add`.

### Роли скиллов

| Скилл | Роль |
|---|---|
| `portfolio-data-loader` | Чистый data layer: парсит выгрузки IntelInvest с планом сайта `Portfolio/plan.json` («Общий баланс» Numbers — только для сверки), считает XIRR/TWR, сохраняет JSON-снапшот (рабочий снапшот штатно сохраняет сайт) |
| `ru-portfolio-advisor` | Инвестиционный анализ (8 режимов: еженедельный обзор акций/облигаций, ребалансировка, анализ эмитента, анализ фондов, доходность, ИИС-3 Buy Advice, Stock Quality Forward Review) |
| `portfolio-scenario-stress` | Транслирует сценарии/прогнозы в ΔP&L по позициям на Мосбирже |
| `portfolio-integrated-view` | Read-only синтезатор snapshot + stress + weekly-review в единый dashboard (контекст equity vs bond по горизонтам с порогами переключения по весу сценария, CI propagation, joint expectation через macro_dependency); только агрегация, никаких рекомендаций и вердиктов |
| `portfolio-coherence-audit` | Мета-слой НАД пайплайном (read-only deep-pass): Stage P (Python) собирает валидированный bundle всех артефактов с generation-consistency gate; Stage R ищет кросс-артефактные противоречия, off-diagonal факторные связки, joint tail и red-team'ит equity-vs-bond вывод. Каденс: ежемесячно или по `watch_verdict` |
| `macro-ru-watcher` | Снапшот российских макроиндикаторов (ставка ЦБ, инфляция, USD/RUB, CNY/RUB, Brent, RGBI, IMOEX) — без интерпретации |
| `macro-forecast-chain` | Оркестратор макропрогнозного пайплайна (DAG-порядок) для portfolio-scenario-stress; активируется явно |
| `forecast-collector` | Ingest pipeline: собирает 10–20 верифицируемых resolved-прогнозов из источника → `forecast-collections/fc-<source>-collection-<date>.md`; входной материал для `retrospective-forecast-audit` |
| `forecast-confidence-applier` | Агрегирует 3–7 источников с весами доверия → filtered consensus |
| `forecast-monitor` | Еженедельная проверка активных `forecasts/*.yaml` и `scenarios/*.yaml` через web_search |
| `retrospective-forecast-audit` | Ретроспективный аудит по трём шкалам (исполнение / позиция к консенсусу / локализация ошибки). Save выдаёт пару: полный отчёт → `reports/`, сжатый trust-профиль → `domains/{domain}/` |
| `scenario-builder` | Shell Scenario Planning: матрица 2×2 из реальных разногласий |
| `hypothesis-stress-tester` | Логическая атака на прогноз: Pre-mortem, KAC, Devil's Advocate, Reversibility check |
| `save-to-library` | Сохраняет аудиты, прогнозы, сценарии, отчёты в `Claude-Memory/` и обновляет INDEX.md и `_sync_log.md` |
| `memory-sync` | Синхронизирует YAML frontmatter из `Claude-Memory/` → `memory_user_edits` `[lib]`-записи; пишет в `_sync_log.md` |
| `revise-memory-local` | Чистка и дедупликация локальных файлов auto-memory |
| `revise-memory-remote` | Ревизия библиотеки `Claude-Memory/`: валидность YAML, парность *.md ↔ *.yaml, устаревшие прогнозы |
| `travel-planning` | Self-contained пайплайн планирования путешествий: Profile mode → Stage 0 (scope) → 1 (DR-промт) → 2 (similarity) → 3 (POI) → 4 (variants) → 5 (final plan) → 6 (финиш: карта + досье) → Export. Не использует `shared_refs`, не связан с финансово-прогнозным пайплайном, своё дерево хранилища `Claude-Memory/travel-planner/`. Подробности — секция «Travel Planning» ниже |
| `health-meds` | Self-contained обогатитель аптечки раздела «Здоровье» Personal Hub: читает `meds.json`+`labs.json` из `Claude-Memory/Health/` на Synology, заполняет справочные поля по официальным инструкциям (ГРЛС · DailyMed · SmPC) с провенансом в `ref_meta`, мержит через `validate_meds.py` — поля человека не трогает никогда. Медицинских рекомендаций не даёт. `shared_refs: [transport-layer]` |
| `health-labs` | Self-contained внесение медицинских документов: `intake.py` читает первоисточник «Медицинские анализы» → числа в `labs.json` (главный файл), заключения в `studies.json` (зеркало + бэкап; правится и страницей), связь точка→исследование; справка биомаркеров; сохранение отчётов (`health-report@1`). Медицинских рекомендаций не даёт. `shared_refs: [transport-layer]` |
| `game-advisor` | Self-contained советник по играм (Switch 2 + Steam Deck): рекомендация/калибровка/обновление профиля/цены/магазины. Хранилище `Claude-Memory/Gaming/`. Подробности — секция «Game Advisor» ниже |
| `zenmoney-analyst` | Личные финансы через MCP ZenMoney (запись — по согласованию): месяцы, категории, периоды, запас, остатки на дату, поездки, возвраты, общий счёт. **Режимы E/F (с 2026-10-11): импорт и сверка по выписке банка** (PDF/CSV; банк узнаётся по содержимому; реализован FF; парсеры банков расширяемы) со сверкой остатков. Пишет лишь `ZenMoney/audit/` и строки карты `zenmoney-map.md` скриптом `map_edit.py` после «да» на diff (исключение D3). Инвестсоветов не даёт. Дев-доки — `docs/zenmoney/README.md`. `shared_refs: [transport-layer]` |

### Двухслойная архитектура прогнозов — сводка

Полная спецификация (два слоя, двойной marginal, решения D1–D8, три типа updates,
три типа прогнозов, динамическая атрибуция источников D8, forecast chains) —
**`docs/investment/_cross-cutting/conditional-architecture.md`**. Читать перед правкой
forecasting-скиллов. Жёсткое ядро, действующее всегда:

- **Layer 1** (marginal, trust-weighted FCA) — основа EV-решений, `forecast.central_estimate`;
  weekly-review читает его. **Layer 2** (coherent scenario bundles) —
  `conditional_on_scenarios.by_scenario`; stress-тест читает его напрямую.
  Layer 2 marginal — только диагностика расхождения (`coherence_diagnostic`).
- **SSOT весов и сроков** — файлы сайта `scenarios/stress-weights-{матрица}.json`, `scenarios/horizons.json`
  (пишет сайт); нет — веса матрицы, сроки прошлого стресса. Пересчёт Layer 2 — только RECALIBRATE (D7).
- **V2-CUTOVER (2026-08-03):** библиотека weekly-review/stress целиком schema 2; валидаторы
  save-to-library принимают только schema 2 (v1 → blocking). Сводка: `docs/investment/TODO.md#v2-cutover`.

### Хранилище данных

`Claude-Memory/` живёт на Synology (`~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/`,
NAS-оригинал `/volume1/homes/hubuser/Claude-Memory`), вне облачных синков (миграция 2026-08-13).
Полное дерево директорий и матрица «кто пишет / кто читает» —
**`_shared-references/claude-memory-layout.md`**. Жёсткие правила:

- **D3:** в `Claude-Memory/` пишут только `save-to-library` (решения, условия, справочник бумаг —
  его скрипты на mount сами) и maintenance-скиллы (`revise-memory-remote`, `revise-memory-local`,
  `memory-sync`); остальные генерируют артефакт в чат. Исключения: `portfolio-data-loader`
  (снапшоты — pure data layer), `macro-ru-watcher`, `portfolio-coherence-audit` (решение A2).
  Генераторы артефактов пишут черновик в `_drafts/` (служебная зона), в библиотеку его переносит save-to-library.
- **Игры:** `Gaming/user-state.json` пишет только сайт, YAML — только скилл; записи между ними не переносить (`docs/game-advisor/CLAUDE.md`).
- **Режим «без ИИ»:** `_hub/settings.json` пишет только hub-api; при `ai_mode: off` писатели с входом от модели
  отказывают кодом 3 (`hub_settings.py`) — `docs/no-ai-mode/PLAN-less-ai.md`.
- **Транспорт — только Synology mount**: `Read`/`Write`/`Edit`/`Glob`, никакого Bash для файловых
  операций; скрипты save-to-library пишут сами с корнем `--root` (`transport-layer.md`). Недоступен → скилл останавливается и сообщает пользователю (альтернатив нет).
- **Case-конвенция (D4):** артефакты — lowercase kebab-case; UPPER_CASE только `INDEX.md` и `_shared/`.

### Синхронизация справки вьюера (жёсткое правило)

Документация портфельной системы живёт в **двух зеркалах** с разной аудиторией —
**при правке операционной реальности обновлять ОБА:**

| Файл | Аудитория | Что в нём |
|---|---|---|
| `docs/investment/portfolio-workflow-guide.md` (репо) | разработчик (перед правками) | технический ракурс: связи, провенанс полей, схемы, формулы |
| `tools/assets/help/viewer/NN-slug.md` (репо; 10 частей, раздел = файл; на сервер — деплоем с `assets/`) | пользователь | «что гонять и в каком порядке», вкладка→скилл, свежесть |

**Правятся только части `tools/assets/help/viewer/NN-slug.md` в репозитории**; на сервер их выкладывает
`tools/deploy.zsh` вместе с `assets/` (путь `/tools/assets/*` публичный). Правка копии на Synology пропадёт
со следующим деплоем. Формат раздела: `## N. Заголовок {#slug}`, якоря не переименовывать — на них открывают
справку ссылки вьюера (`openHelpAt`); контракт частей — блок «вьюер · справка из частей» в `test_pages_contracts.py`.

**Режимы советника:** меняешь `skills/ru-portfolio-advisor/EXAMPLES.md` (режимы, промты, модели,
effort) — в том же заходе обнови таблицу режимов в `02-models.md` `{#modes}` и, если сменился
список режимов, словарь `MODE_RU` в `tools/assets/viewer.js`.

Части справки грузятся динамически кнопкой **«❓ Справка»** во вьюере
(`tools/portfolio-integrated-viewer.html`, `showHelpModal`, ui-kit `uiHelpOpen({files})`). При изменении пайплайна,
схем, набора вкладок или порядка запуска — **синхронизировать оба файла** (в каждом
есть SYNC-маркер в шапке). Расхождение справок = баг документации.

### Справки страниц кабинета (жёсткое правило)

Каждая страница кабинета, данные которой готовит хотя бы один скилл, несёт кнопку
**«? Справка»** (общий компонент `helpBtnHTML`/`uiHelpOpen` в `tools/assets/ui-kit.js`).
Справка — пользовательское зеркало скиллов раздела: что сказать Claude, **какую модель
брать**, порядок запуска, где результат на странице.

| Страница | Справка | Скиллы | Где правило синка у группы |
|---|---|---|---|
| вьюер портфеля | `tools/assets/help/viewer/*.md` (`02-models.md` — модели) | инвестиционный контур | раздел выше + `docs/investment/README.md` |
| `travel.html` | `tools/assets/help/travel.md` | `travel-planning` | `docs/travel-planning/CLAUDE.md` |
| `games.html` | `tools/assets/help/games.md` | `game-advisor` | раздел «Game Advisor» ниже |
| `health.html` | `tools/assets/help/health.md` | `health-labs`, `health-meds` | `tools/design-reference/health-plan.md` §8 |
| `money.html` | `tools/assets/help/money.md` | `zenmoney-analyst` | `docs/zenmoney/README.md` |
| `hub.html` | `tools/assets/help/hub.md` | карта «раздел → скиллы → модель» | этот раздел |

**Меняешь триггеры, режимы, входы/выходы, модель или порядок запуска скилла — обнови
справку его страницы в том же коммите** (и строку в `hub.md`, если сменилась модель или
набор скиллов раздела). Новый скилл с данными на странице — кнопка + файл + строка в
`UI_HELP`. Контракт «кнопка ↔ файл ↔ скиллы существуют» — `tools/tests/test_pages_contracts.py`.

### Python-скрипты

Карта скриптов всех скиллов (назначение, вход/выход, кто вызывает) —
**`docs/investment/_cross-cutting/scripts-map.md`**. Жёсткие правила, действующие всегда:

- Порядок загрузки портфеля: `parse_portfolio.py` → `portfolio_returns.py` → `per_security_xirr.py`.
  `merge_cross_currency_positions` и сплиты снаружи не применять — они внутри
  `reconstruct_positions`.
- **Single-ownership загрузки:** входные файлы парсит только `portfolio-data-loader`;
  `ru-portfolio-advisor` работает с готовым снапшотом (нет снапшота → сначала data-loader).
- Новый сплит → `known_splits.py add` загрузчика (реестр `Portfolio/known-splits.json`)
  с датой возобновления торгов.

### Выбор модели

Детальная таблица маршрутизации — в `_shared-references/model-routing.md`. Краткая сводка:

- **Haiku** — `forecast-monitor` (`claude -p` на Pro тратит тот же лимит подписки — выносом его не сэкономить)
- **Sonnet** — большинство скиллов (по умолчанию); у Opus на Pro отдельный недельный
  счётчик — исполнение на Sonnet его не расходует
- **Opus** — `ru-portfolio-advisor` режим 8 (Stock Quality Forward Review),
  `retrospective-forecast-audit` ≥9 тезисов или ≥45 мин, `portfolio-integrated-view`;
  для планирования сложных правок — `/model opusplan`
- **Fable** — только Stage R `portfolio-coherence-audit`; на Pro недоступен
  (API-кредиты или деградация на Opus с оговоркой — см. model-routing.md)

### Делегирование субагентам

Субагент перезагружает CLAUDE.md и контекст целиком — делегировать когда шумная
внутренняя работа сворачивается в короткое резюме, а не ради «параллельно = быстрее».

- **Поиск по репозиторию / «где лежит X»** → агент Explore, `model: haiku`.
- **Механические правки по готовому образцу и прогон тестов** → субагент `model: sonnet`
  с заранее выданными разрешениями (иначе дёргает подтверждение каждую минуту).
- **Fan-out ≥3 агентов** — только sonnet/haiku, никогда на дорогой модели
  (кейс 2026-08-03: 3 из 5 Fable-аудиторов упали об лимит сессии).
- Субагент возвращает **резюме, не простыни**: его вывод попадает в основной контекст
  дословно.
- Субагент гоняет только целевые файлы тестов; `--group`, `--tier` и полный реестр — основная сессия.
- Основная модель оставляет себе: архитектуру, правки контрактов/схем, всё, где нужен
  контекст целой сессии.

### Принцип сценарной независимости скиллов

Скилл может декларировать **факторные зависимости** («актив X коррелирует с фактором Y»), но не должен встраивать **сценарно-специфическую логику** («при сценарии A делать X»).

**Правило для `SKILL.md` и `references/`:**
- ✅ «LKOH зависит от прогноза Brent — использовать Layer 1 marginal forecast» — OK: фактор независим от сценария
- ❌ «При войне в Иране (или снятии санкций) увеличить долю LKOH» — НЕ OK: сценарий встроен в скилл

Сценарный анализ — зона `scenario-builder` и `portfolio-scenario-stress`. Скиллы остаются гибкими и не ломаются при смене сценарной матрицы.

**Исключение:** триггеры пересмотра источниковых профилей (T1–T6 в `references/{source}-profile.md`) допустимы — это «когда обновить профиль», а не «что делать при наступлении сценария».

### Структура SKILL.md

Каждый `SKILL.md` начинается с YAML frontmatter (`name`, `description`, `shared_refs`). Поле `description` — триггер-матчер: держи его точным, чтобы не было ложных срабатываний. `shared_refs` — список canonical-файлов из `_shared-references/`, которые `pack.sh` инжектирует в `references/` при упаковке. Файлы из `references/` загружаются **по требованию** внутри скилла, а не при старте.

**Текст скилла — правило и последствие одной фразой, без истории.** Номера задач, даты правок,
«раньше было», разборы инцидентов — в TODO, реестр тестов, коммит (CS-3).

### Глобальные shared-references

Директория `_shared-references/` содержит канонические файлы, общие для нескольких скиллов
(транспорт, схемы YAML, раскладка `Claude-Memory/`, именование, маршрутизация моделей, SSOT весов сценариев).
Перечень — `ls _shared-references/`, назначение — в шапке каждого файла.

**Правило:** локальные копии в `references/` скиллов **не создаются** — `pack.sh` инжектирует их из `_shared-references/` при упаковке. Исключение: файлы с уникальным скилл-специфичным содержимым (например, `model-routing.md` в `retrospective-forecast-audit` и `ru-portfolio-advisor` — детальнее глобального).

При работе со скиллом помни, что кроме `references/` скилла есть глобальные файлы в `_shared-references/` — они могут быть релевантны при анализе поведения скилла.

## Travel Planning — особенности

> Подробности работы со скиллом `travel-planning` вынесены в отдельный
> dev-гайд: **`docs/travel-planning/CLAUDE.md`** (архитектурные принципы,
> self-contained-правила, что НЕ должно протекать в `.skill`, calibration-кейсы,
> синхронизация документации). **При любой правке travel-planning — обязательно
> читать его.** Нормализация/валидация артефактов — `docs/travel-planning/
> format-firewall.md`.
>
> Дев-документация организована поддоменами `stages/` · `export/` · `plans/` ·
> `calibration/` (точка входа — `docs/travel-planning/README.md`). Перед правкой
> конкретной стадии/темы можно вызвать навигатор `/travel-docs <стадия|тема>`
> (`.claude/skills/travel-docs/`, рядом с `investment-docs`) — он грузит только
> релевантную документацию.

## Game Advisor — особенности

Дев-правила (SSOT профиля вкуса, транспорт, провенанс-гейты, синк справки «Игры») —
**`docs/game-advisor/CLAUDE.md`**; при любой правке `game-advisor` — читать его.
