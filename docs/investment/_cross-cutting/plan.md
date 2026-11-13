# План правок скиллов и инфраструктуры

**Дата:** 2026-05-05 (финаль: 2026-05-06)
**Статус:** Phase 0/1/2/3/4/4.1/5/6/7/8 завершены; Phase 2 остаток (Portfolio/INDEX.md) — не сделан
**Источники решений:** `docs/investment/_cross-cutting/report.md` (аудит) + диалог 2026-05-05 + `INTEGRATION-DOCS/00-MASTER-PLAN.md`

---

## 0. Принятые решения (фиксированные)

| # | Решение |
|---|---|
| **D1** | Shared-references: каждый `.skill` **самодостаточен** — внутри архива лежат полные копии shared-файлов в `references/`. В репо канон живёт в `_shared-references/`, в `skills/<имя>/references/` — пусто (если не нужны локальные правки). `pack.sh` при упаковке: делает temp-копию скилла; для каждого `shared_refs:` из frontmatter — если в скилле уже лежит локальная копия `references/<name>.md`, оставляет её (override с правками); если нет — копирует канон. Зипает temp в `.skill`, чистит. Репо после pack не меняется |
| **D2** | Структура `Claude-Memory/`: единая иерархия с `Portfolio/` как отдельной веткой (см. §2). Snapshots, stress и portfolio-forecasts — внутри `Portfolio/`, а не в `forecasts/` |
| **D3** | **Никакой скилл, кроме `save-to-library`, не пишет в gDrive.** Все остальные генерируют артефакт в чат / temp, а пользователь явно зовёт save-to-library |
| **D4** | Case-конвенция: **lowercase kebab-case** для всех артефактов скиллов (результатов работы) — `portfolio-*.json`, `weekly-review-*.yaml`, `stress-*.yaml`, `macro-input-*.yaml`, `<slug>-<date>.{md,yaml}`. **UPPER_CASE** для системных/инфраструктурных файлов: `INDEX.md`, всё содержимое `Claude-Memory/_shared/` (`DEPENDENCY-MAP.md`). Так визуально виден класс файла: lowercase = результат, UPPER_CASE = инфраструктура для работы скиллов |
| **D5** | DOCX-генерация удаляется отовсюду; вернётся только в будущем human-facing скилле и только по явному запросу |
| **D6** | `forecast-collector` работает только для ретро-аудита: collector → retrospective-forecast-audit → save-to-library. Связь с `forecast-confidence-applier` убирается |
| **D7** | `macro-forecast-chain` — оркестратор без триггеров по описанию. Активация только явная или из upstream-скилла |
| **D8** | `ru-portfolio-advisor` читает портфель **только** из `Portfolio/snapshots/portfolio-*.json` через transport-layer (если файл не приложен явно). Сам ничего не считает дублирующего и ничего не сохраняет |
| **D9** | `KNOWN_SPLITS` живёт **только** в `portfolio-data-loader/scripts/portfolio_returns.py` |
| **D10** | `INTEGRATION-DOCS/` — будущий контур (Portfolio Integrated View). Все правки ниже **должны** учитывать его requirements (новый скилл `portfolio-integrated-view`, JSON v2, weekly-review YAML, stress per-position) |

---

## 1. Целевая структура `Claude-Memory/` (плоский Portfolio/, финализирован)

```
Claude-Memory/
├── INDEX.md                              # master, схема в шапке файла
├── _sync_log.md                          # пишут save-to-library и memory-sync
│
├── domains/                              # профили аудитов источников
│   ├── geopolitics/
│   ├── ru-sellside/
│   ├── global-banks/
│   ├── tech-ceo/
│   ├── ru-macro/
│   └── commodity-agencies/
│
├── forecasts/                            # макро/геополитика: FCA и FCA+HST
│   ├── INDEX.md                          # схема в шапке + tier 1/2 разметка
│   ├── <slug>-<date>.{md,yaml}           # tier 1 (FCA only)
│   └── <slug>-<date>-stress.{md,yaml}    # tier 2 (FCA+HST, parallel pair)
│
├── scenarios/                            # Shell 2×2 сценарии
│   └── INDEX.md
│
├── forecast-collections/                 # fc-<source>-collection-<date>.md (вход ретро-аудита)
│
├── audits/                               # выходы retrospective-forecast-audit
│   └── INDEX.md
│
├── macro-snapshots/                      # ru-<date>.md от macro-ru-watcher
│
├── macro-chain/                          # macro-input-<date>.yaml (выход macro-forecast-chain)
│
├── reports/                              # human-facing сводки
│
├── Portfolio/                            # вся portfolio-ветка
│   ├── INDEX.md
│   ├── README.md
│   ├── snapshots/                        # portfolio-<date>.json (от data-loader)
│   ├── stress/                           # stress-<date>-<source>.{md,yaml}
│   ├── forecasts/                        # per-stock catalyst forecasts
│   ├── weekly-reviews/                   # weekly-review-<date>.yaml
│   └── integrated-views/                 # integrated-view-<date>.md
│
└── _shared/                              # инфраструктура для работы скиллов (UPPER_CASE)
    └── DEPENDENCY-MAP.md                 # факторные зависимости макро-DAG
```

**Логика case-конвенции (D4):**
- **lowercase** = результаты работы скиллов (отчёты, прогнозы, снапшоты): `portfolio-*.json`, `weekly-review-*.yaml`, `<slug>-<date>.md`, `ru-<date>.md` и т.п.
- **UPPER_CASE** = инфраструктура и навигация: `INDEX.md`, `Claude-Memory/_shared/DEPENDENCY-MAP.md`.
- Визуально с любого устройства видно: длинный список `lowercase-files-with-dates` — это результаты, отдельно лежащий `INDEX.md` или `DEPENDENCY-MAP.md` — это «не результат, а служебное».
- `SOURCE-REGISTRY.md` и `PERSPECTIVE-MAPS.md` **упразднены** (2026-05-05): дублируют `INDEX.md` и `domains/`.

---

## 2. `_shared-references/` в репо скиллов (embed-on-pack, выбран)

**Принцип:** каждый `.skill`-архив самодостаточен. Внутри `references/` лежат полные копии **только тех** shared-файлов, которые нужны именно этому скиллу. Это селективный embed, не «положить всё».

**Что определяет селекцию:** поле `shared_refs:` во frontmatter SKILL.md каждого скилла. Это per-skill manifest — единственная точка правды о том, что класть в архив. Файлы не из этого списка в архив не попадают, даже если лежат в `_shared-references/`.

### Где что лежит в репо

```
claude_skills/
├── _shared-references/                   # КАНОН — единственная точка правды
│   ├── transport-layer.md
│   ├── events-yaml-spec.md
│   └── ...
└── skills/
    └── <имя>/
        ├── SKILL.md                      # frontmatter содержит shared_refs: [...]
        └── references/                   # пусто по умолчанию;
                                          # полная копия shared-файла кладётся сюда
                                          # ТОЛЬКО если для этого скилла нужны правки
```

### Где что лежит в `.skill` (после упаковки)

```
<имя>.skill (zip)
├── SKILL.md
└── references/
    ├── transport-layer.md                # копия канона ИЛИ локальный override
    ├── events-yaml-spec.md
    └── ... (всё, что было в shared_refs:)
```

### Жизненный цикл

**Разработка:**
- Канон правится в `_shared-references/<name>.md` — единое место для всех скиллов.
- Если конкретному скиллу нужна правленая версия (отличающаяся от канона) — кладёшь полную копию с правками в `skills/<имя>/references/<name>.md`. Эта копия попадёт в архив как override.
- В обычном случае `skills/<имя>/references/` пуст — скилл получит канон при упаковке.

**Упаковка (`pack.sh`):**
1. Делает временную копию `skills/<имя>/` в `mktemp -d`.
2. Читает frontmatter SKILL.md: `shared_refs: [transport-layer, events-yaml-spec, ...]`.
3. Для каждого имени:
   - Если `<temp>/references/<name>.md` уже существует (из репо) → оставляет (local override).
   - Иначе копирует `_shared-references/<name>.md` → `<temp>/references/<name>.md` (canonical inject).
4. Зипает temp в `outputs/<имя>.skill`.
5. Удаляет temp. **Репо не меняется.**

**Результат:** в git нет sync-копий канона; в каждом `.skill`-архиве есть полная самодостаточная `references/`.

### Канонический список файлов в `_shared-references/`

| Файл | Что описывает |
|---|---|
| `transport-layer.md` | Transport B/A core, Cowork procedure, базовые операции |
| `events-yaml-spec.md` | Полная схема `forecast-events` и `scenario-events` YAML, включая tier 1/2 разметку |
| `yaml-schemas.md` | Все YAML типы DAG (`forecast_collection`, `forecast-events`, `scenario-events`, `fca-output`, `weekly-review`, `integrated-view`) |
| `file-naming.md` | Конвенции имён (lowercase для результатов, UPPER_CASE для инфраструктуры), правила slug |
| `claude-memory-layout.md` | Реестр подпапок и владельцев (кто пишет / кто читает) |
| `audit-frontmatter-schema.md` | Frontmatter профилей аудитов в `domains/*` |
| `model-routing.md` | Какая модель для какого скилла/режима |

### Что должно быть в SKILL.md скилла (manifest)

Каждый скилл объявляет ровно те shared-refs, которые ему нужны:

```yaml
---
name: <skill-name>
description: ...
shared_refs: [transport-layer, file-naming]
---

## ... тело SKILL.md ...

При работе с транспортом — читай `references/transport-layer.md`.
```

Пример: `forecast-monitor` нужны только `transport-layer`, `events-yaml-spec`, `file-naming`. Он НЕ получит `claude-memory-layout`, `model-routing` и т.п. — ровно три файла в `references/` его архива.

В `.skill`-архиве каждый объявленный файл всегда лежит — либо канон (по умолчанию), либо локальный override (если в репо была положена правленая копия в `skills/<имя>/references/`).

### Кто отвечает за манифест

- При создании нового скилла его автор прописывает `shared_refs:` исходя из того, что реально использует SKILL.md.
- При добавлении нового shared-файла в `_shared-references/` — он не появляется автоматически в скиллах. Нужно обновить `shared_refs:` в тех SKILL.md, где этот файл нужен.
- Это намеренная inconvenience — заставляет автора скилла думать, что именно ему надо, а не тащить весь общий бэкграунд.

`pack.sh` реализует эту схему — см. `pack.sh` и `.claude/commands/pack.md`.

---

## 3. Изменения в `ru-portfolio-advisor` (5.3 / 6.1, детально)

Скилл advisor сейчас не правим, но фиксируем точный change-list для будущей фазы:

### 3.1 Input contract
- **Default:** читать `Portfolio/snapshots/portfolio-<latest>.json` через transport-layer. Если последний снапшот старше 14 дней — предупредить и попросить регенерировать.
- **Опционально:** если в сообщении приложен `.xlsx`/`.numbers` — НЕ обрабатывать самому. Сообщить пользователю: «приложен файл, запусти `portfolio-data-loader` для генерации snapshot, потом меня снова».
- Удалить раздел в SKILL.md, описывающий парсинг входных файлов внутри advisor.

### 3.2 Удаление дублирования
- Убрать из SKILL.md inline-копию `KNOWN_SPLITS` (стр. 29–30 текущего advisor).
- Убрать раздел расчёта доходности отдельной бумаги (стр. 313–346, дублирует data-loader).
- Заменить ссылками: «расчёты XIRR/TWR/ROI делает `portfolio-data-loader`, схема выхода — `portfolio-data-loader/references/output-schema.md`».
- Убрать любое упоминание `merge_cross_currency_positions` и `apply_known_splits` (CLAUDE.md уже это запрещает снаружи).

### 3.3 Output mode (из INTEGRATION-DOCS Phase 2; расширено 2026-05-06)
Три opt-in ветки, default — только chat output.

| Флаг / триггер | Артефакт | Назначение |
|---|---|---|
| `--save-to-library` / «save weekly», «подготовь YAML для обзора», «сохрани обзор для integrated view» | `weekly-review-{date}.yaml` | Машиночитаемые данные для portfolio-integrated-view |
| `--save-report` / «подготовь репорт для сохранения», «save report», «сохрани отчёт» | `weekly-review-{date}.md` | Человекочитаемый архив |
| «репорт и файл для интеграционного анализа» / «подготовь оба» | оба файла | Полный комплект |

- Никакой скилл не пишет в библиотеку сам (D3) — пользователь вызывает `save-to-library` после проверки.
- Схема YAML — `references/weekly-review-schema-v1.md`. Шаблон .md — `references/report-template.md`.
- save-to-library Workflow F расширен: поддерживает .yaml, .md и оба файла.

### 3.4 Новые references
- `references/catalyst-tree-rules.md` (из INTEGRATION-DOCS Phase 2).
- `references/startup-checklist.md` (вынести строки 113–165 текущего SKILL.md).
- `references/analysis-process.md` (вынести строки 405–453).
- `references/trust-hierarchy.md` (вынести правила 19–22).

### 3.5 Связь с другими скиллами (mode 8)
- Mode 8 (Stock Quality Forward Review) читает `Portfolio/stress/stress-<latest>.{md,yaml}` через transport-layer для макро-фильтра.
- Если stress-файл старше 30 дней — предупредить, рекомендовать запуск `macro-forecast-chain` → `portfolio-scenario-stress`.

### 3.6 Триггеры
- Явное правило: «advisor не активируется, если в сообщении нет файла И нет свежего snapshot < 14d, без явной команды пользователя».
- Не пересекаться с `portfolio-data-loader` (который активируется на «загрузи портфель», «парсни выгрузку»).

### 3.7 Source of trust
- Trust matrix берётся из `Claude-Memory/INDEX.md` (subdomain weights) — D2.5 из INTEGRATION-DOCS.
- В catalyst confidence — discount по `source_quality` (R2 mitigation).

### 3.8 Удаляется / упрощается
- README.md, CHANGELOG.md, EXAMPLES.md, USAGE.md — оставить только README + EXAMPLES, остальное в reference (если нужно).
- Решение по mode 1 vs 8 — отложено, не трогаем.

---

## 4. Контракты I/O (направление зависимостей)

| Скилл | Читает (← upstream) | Пишет artefact в чат → save-to-library кладёт в |
|---|---|---|
| `portfolio-data-loader` | `.xlsx`/`.numbers` от пользователя | `Portfolio/snapshots/portfolio-<date>.json` |
| `macro-ru-watcher` | внешние индикаторы (web/MOEX/CBR) | `macro-snapshots/ru-<date>.md` |
| `forecast-collector` | **описание источника от пользователя** (какой архив/блог/PDF, для какой темы), затем извлечённые из него resolved-прогнозы | `forecast-collections/fc-<source>-collection-<date>.md` (вход для retrospective-forecast-audit) |
| `retrospective-forecast-audit` | `forecast-collections/*` (опц.) или прямо переданный пользователем источник | `audits/<date>-<topic>.md` + report |
| `forecast-confidence-applier` | `domains/*`, тема прогноза от пользователя | `forecasts/<slug>-<date>.{md,yaml}` (tier 1) |
| `hypothesis-stress-tester` | **любое из четырёх:** (а) свежий прогноз в текущем чате, (б) `forecasts/<slug>-<date>.{md,yaml}` через transport-layer, (в) приложенный пользователем yaml/md-файл, (г) inline-описание прогноза в сообщении | `forecasts/<slug>-<date>-stress.{md,yaml}` (tier 2, parallel pair) |
| `scenario-builder` | запрос пользователя | `scenarios/<slug>-<date>.{md,yaml}` |
| `macro-forecast-chain` | `forecasts/*.yaml` (свежие), `Portfolio/snapshots/*.json` | `macro-chain/macro-input-<date>.yaml` |
| `portfolio-scenario-stress` | `macro-chain/`, `Portfolio/snapshots/`, `forecasts/*.yaml` | `Portfolio/stress/stress-<date>-<source>.{md,yaml}` |
| `ru-portfolio-advisor` | `Portfolio/snapshots/` (обязательно, default через transport-layer). **Stress-файлы не обязательны** — advisor работает независимо; читает их только если они свежие (<30d) и явно нужны для mode 8 макро-фильтра | (chat) или `Portfolio/weekly-reviews/weekly-review-<date>.yaml` (opt-in) |
| `portfolio-integrated-view` (NEW) | `Portfolio/weekly-reviews/`, `Portfolio/stress/` | `Portfolio/integrated-views/integrated-view-<date>.md` |
| `forecast-monitor` | `forecasts/*.yaml`, `scenarios/*.yaml` | (отчёт пользователю; staleness checks, без записи в библиотеку) |
| `save-to-library` | artefact от любого скилла | соответствующая папка + `INDEX.md` + `_sync_log.md` |
| `memory-sync` | `domains/*` (frontmatter) | `memory_user_edits` `[lib]` + `_sync_log.md` |
| `revise-memory-remote` | `Claude-Memory/` (всё) | (правки + отчёт; писать может, потому что это maintenance-скилл) |
| `revise-memory-local` | `~/.claude/projects/*/memory/` | (правки локальной памяти) |

**Ключевое следствие D3:** ни один скилл, кроме `save-to-library` и maintenance-скиллов (`revise-memory-remote`, `revise-memory-local`, `memory-sync`), **не делает Write в Claude-Memory/**. Все артефакты идут через буфер «чат / artefact», пользователь явно сохраняет.

**Уточнения по комментариям 2026-05-05:**
- `forecast-collector` принимает на вход **описание источника** (какой архив/канал/PDF искать) — это задание на сбор. Выход — собранные resolved-прогнозы для последующего ретро-аудита. Без описания источника скилл не активируется.
- `hypothesis-stress-tester` — гибкий по входу: работает с прогнозом в любой форме (свежий из чата / файл из памяти / приложенный файл / inline-описание). Это нужно явно прописать в `## Inputs / Outputs` его SKILL.md.
- `ru-portfolio-advisor` **независим** от stress-теста: основной режим работы — анализ snapshot без stress. Stress-файл нужен только для mode 8 (Stock Quality Forward Review) как макро-фильтр; в остальных режимах не читается.
- Все имена файлов в таблице — lowercase (D4 уточнён): `portfolio-*`, `weekly-review-*`, `stress-*`, `macro-input-*`, `integrated-view-*`. Только `INDEX.md` остаётся UPPER.

---

## 5. Шаблон `## Inputs / Outputs` (для всех 15 скиллов)

```markdown
## Inputs / Outputs

**Inputs:**
- {что} ← {источник}, {формат / reference}

**Outputs (как artefact в чат):**
- {что} → пользователь визуально проверяет → save-to-library пишет в {путь}

**Upstream скиллы:** {список или «—»}
**Downstream скиллы:** {список или «—»}
**Shared refs:** {список из `_shared-references/`}
```

---

## 6. План работ по фазам

**Принцип:** правки выполняются **поверх** требований `INTEGRATION-DOCS/`. Каждая фаза включает соответствующие изменения из обоих источников.

### Phase 0 — Фундамент ✅ (завершена 2026-05-05)
- ✅ Финализирована структура `Portfolio/` (плоский вариант, §1).
- ✅ Создан `_shared-references/` в репо (7 файлов; `source-registry-pointer.md` упразднён).
- ✅ `pack.sh` и `.claude/commands/pack.md` обновлены под embed-on-pack (вариант B).
- ✅ `CLAUDE.md` обновлён: DAG, D3, D4, пути, список скиллов.
- ✅ Миграция `Claude-Memory/` выполнена: `macro-chain/`, `domains/`, `Portfolio/` (snapshots/stress/forecasts/weekly-reviews/integrated-views), `macro-snapshots/`, `forecast-collections/`, `audits/`, `_shared/`.
- ✅ `_shared/DEPENDENCY-MAP.md` создан (`SOURCE-REGISTRY.md` и `PERSPECTIVE-MAPS.md` упразднены как дубли `INDEX.md`).
- ✅ `Portfolio/README.md` создан.
- ✅ `INDEX.md` обновлён: пути `domains/`, расширены cross-references.
- ✅ `_sync_log.md` обновлён записью о миграции.

### Phase 1 — Data Layer ✅ (завершена 2026-05-05)
- ✅ `portfolio-data-loader`: расширен `parse_portfolio.py` до JSON v2 (ie_model, ie_actual, ie_summary, IIS-3 split). 17/17 acceptance criteria пройдено.
- ✅ Добавлен `## Inputs / Outputs` блок в SKILL.md.
- ✅ Исправлены пути: `Portfolio-Snapshots/` → `Portfolio/snapshots/`, имена файлов → lowercase.
- ✅ Обновлён `references/output-schema.md` до v2 (account: "iis_3", IIS-3 split, ie_model/ie_actual).
- ✅ Устранены техдолги: MOEX `last` vs `price`, xirr% vs decimal, qty для акций из returns.json (SKILL.md + docstrings).
- ✅ Скилл упакован: `outputs/portfolio-data-loader.skill` (149 KB). Прогон на реальных данных — 17/17 checks OK.
- Acceptance: `08-acceptance-criteria.md` Phase 1 — пройдено.

### Phase 2 — CLAUDE.md и shared-схемы (частично ✅, остаток — 0.5 сессии)
- ✅ Обновлён корневой `CLAUDE.md` (см. §7).
- ✅ Создан `Claude-Memory/_shared/DEPENDENCY-MAP.md` (`SOURCE-REGISTRY.md` и `PERSPECTIVE-MAPS.md` упразднены).
- ✅ Создан `Portfolio/README.md`.
- ❌ `Portfolio/INDEX.md` требует ревизии (унаследован из `Claude-Portfolio/`, содержит устаревшие пути). **Следующая фаза.**

### Phase 3 — Advisor refactor ✅ (завершена 2026-05-06)
- ✅ §3.1 Input contract: Primary — `Portfolio/snapshots/portfolio-<date>.json` v2 через transport-layer (age ≤ 14d). If .numbers/.xlsx — redirect to data-loader. Removed sections describing parsing inside advisor.
- ✅ §3.2 Удаление дублирования: убрана inline-копия KNOWN_SPLITS, удалены разделы про parse_portfolio.py / portfolio_returns.py / per_security_xirr.py / замечания по полям. Заменены ссылками на output-schema.md data-loader'а.
- ✅ §3.3 Output mode: добавлен `--save-to-library` (YAML) + `--save-report` (markdown). Три ветки: только чат / YAML / .md / оба. Создан `references/report-template.md`. save-to-library Workflow F расширен под оба типа.
- ✅ §3.4 Новые references: созданы startup-checklist.md, analysis-process.md, trust-hierarchy.md, catalyst-tree-rules.md. SKILL.md содержит поинтеры.
- ✅ §3.5 Mode 8: читает `Portfolio/stress/stress-<latest>.yaml` для макро-фильтра. Если > 30d — предупреждение.
- ✅ §3.6 Trigger rules: добавлено правило неактивации без snapshot/файлов.
- ✅ §3.7 Trust matrix из Claude-Memory/INDEX.md упомянут в output modes.
- ✅ §3.8 Удалены CHANGELOG.md, USAGE.md (оставлены README.md + EXAMPLES.md).
- Не правили mode 1 vs 8 (отложено).
- Acceptance: `08-acceptance-criteria.md` Phase 2.

### Phase 4 — Stress test extension (Phase 3 INTEGRATION-DOCS, 1 сессия) ✅ (завершена 2026-05-05)
- ✅ `portfolio-scenario-stress`: добавлен Шаг 3.6 per_position computation (factor_betas, CI, macro_blindspots).
- ✅ `references/output-template.md` переписан под схему STRESS YAML v1 (schema_version, scenarios как dict с Sc-X_label ключами, per_position, macro_blindspots, backward-compat fields).
- ✅ Добавлен `## Inputs / Outputs` (Upstream/Downstream/Shared refs).
- ✅ Step 6 переписан: прямые Write() удалены, заменены artefact-паттерном → save-to-library в `Portfolio/stress/` (D3).
- ✅ Исправлены пути и имена файлов по D4: `Portfolio-Stress/` → `Portfolio/stress/`, `PORTFOLIO-` → `portfolio-`, `STRESS-` → `stress-`, `Macro-Chain/MACRO-INPUT-` → `macro-chain/macro-input-`, `Scenarios/` → `scenarios/`.

### Phase 4.1 — Stress-test polish (1 сессия) ✅ (завершена 2026-05-05)

После аудита первого реального запуска `portfolio-scenario-stress` на 52-позиционном портфеле (артефакты `stress-2026-05-05-iron-curtain-2.{md,yaml}`) выявлены: capacity-предел Sonnet 4.6 (per_position покрыл ~41% веса вместо 100%), точечные дефекты инструкций (sanctions combination rules, geopol в каноне, bond method strings), encoding-issue в transport-layer (mojibake UTF-8→cp1252).

Решение: Python-скрипт берёт numeric crunching, модель формирует только текстовые priors. Encoding-check переезжает в save-to-library как блокирующая проверка.

- ✅ `scripts/compute_per_position.py` — детерминистический расчёт per_position блока (priors-only режим; `--regression-mode moex` placeholder для Phase 4.2).
- ✅ `references/idiosyncratic-tickers.md` — список тикеров с автоматическим `macro_blindspot: true` (MDMG, PRMD, OZON, WUSH, DOMRF) с обоснованием каждого.
- ✅ `references/sector-sensitivities.md` (B1) — combination rules для `sanctions_intensity` (continuous) + `sanctions_escalation` (binary) + `geopol_escalation`.
- ✅ `references/output-template.md` (B2) — `geopol` добавлен в канонический пример `factor_betas`; правило «отсутствующий фактор означает β=0, но запись опускать нельзя».
- ✅ `references/bonds-sensitivity.md` (B4) — канонические `factor_betas_method` строки для ОФЗ / USD/EUR/CNY-замещаек / корп RUB / флоатеров / вечных.
- ✅ SKILL.md `portfolio-scenario-stress`: новый раздел «Модель и масштаб» (Sonnet ≤30 позиций / Opus или скрипт >30); Шаг 3.6 переписан под скрипт (5 подшагов: read refs → priors JSON → save → run script → copy fragment).
- ✅ SKILL.md `save-to-library`: добавлен Workflow E (E1 идентификация → E2 encoding-check → E3 schema v1 валидация → E4 дедуп → E5 сохранение → E6/E7 индексы → E8 сообщение); триггеры в description; anti-patterns про mojibake и неполное покрытие.

**Phase 4.2** (отложено) — MOEX history fetch для реальных factor_betas с регрессией (24mo monthly returns + manual sanctions timeline). Архитектура `compute_per_position.py` готова (флаг `--regression-mode moex`).

### Phase 5 — Forecast pipeline cleanup ✅ (завершена 2026-05-06)
- ✅ `forecast-collector`: уточнен триггер (требование конкретного источника), убран redirect на confidence-applier (D6).
- ✅ `forecast-confidence-applier`: вынесен Шаг 6 (Events YAML) → `references/fca-events-yaml-spec.md`; исправлено D3-нарушение (генерирует artefact, не пишет в Claude-Memory).
- ✅ `hypothesis-stress-tester`: заменены все 15 вхождений "patch" → "stress-pair"; вынесены Шаг 1 → `references/tier1-methods.md`, Шаг 6 → `references/hst-events-yaml-spec.md`; добавлена секция `## Inputs / Outputs`.
- ✅ `scenario-builder`: добавлена секция `## Inputs / Outputs` с явным указанием save-to-library workflow.
- ✅ `forecast-monitor`: убран встроенный fallback DAG; исправлены пути на `Claude-Memory/_shared/DEPENDENCY-MAP.md`; добавлена секция `## Inputs / Outputs`.

### Phase 6 — Macro chain & watcher ✅ (завершена 2026-05-06)
- ✅ `macro-forecast-chain`: убрана D7-нарушение (триггеры из description), вынесены 3 шаблона в references (coverage-report-template.md, mode-selection-template.md, macro-input-schema.md); output contract MACRO-INPUT YAML зафиксирован; D3 исправлен (Шаг 8d: artifact + save-to-library); D4 исправлен (lowercase paths: macro-input-*, macro-chain/); добавлена секция Inputs/Outputs.
- ✅ `macro-ru-watcher`: добавлено правило обработки Synology конфликтных файлов (RU-<date> (N).md); D3 исправлен (Шаг 5: artifact + save-to-library); D4 исправлен (lowercase paths: macro-snapshots/); добавлена секция Inputs/Outputs.

### Phase 6 — Macro chain & watcher ✅ (завершена 2026-05-06)
- ✅ `macro-forecast-chain`: убрана D7-нарушение (триггеры из description), вынесены 3 шаблона в references (coverage-report-template.md, mode-selection-template.md, macro-input-schema.md); output contract MACRO-INPUT YAML зафиксирован; D3 исправлен (Шаг 8d: artifact + save-to-library); D4 исправлен (lowercase paths: macro-input-*, macro-chain/); добавлена секция Inputs/Outputs.
- ✅ `macro-ru-watcher`: добавлено правило обработки Synology конфликтных файлов (RU-<date> (N).md); D3 исправлен (Шаг 5: artifact + save-to-library); D4 исправлен (lowercase paths: macro-snapshots/); добавлена секция Inputs/Outputs.

### Phase 7 — Synthesizer ✅ (завершена 2026-05-06)
- ✅ Создан `portfolio-integrated-view` skill (см. `INTEGRATION-DOCS/04-portfolio-integrated-view-SKILL.md`).
- ✅ Inputs: `Portfolio/snapshots/portfolio-*.json` (v2.0), `Portfolio/stress/stress-*.yaml` (v1), `Portfolio/weekly-reviews/weekly-review-*.yaml` (v1) — через transport-layer.
- ✅ Output (artefact): `integrated-view-<date>.md` → save-to-library пишет в `Portfolio/integrated-views/` (D3 соблюдён).
- ✅ Покрыто: R1 (CI propagation), R4 partial (macro_dependency joint P), R5 (Section 9 What is NOT shown), R6 (schema fail-fast), R7 (predictions_for_review block), R10 (ИИС-3 constraints).
- ✅ References: `synthesizer-workflow.md` (pseudocode Шагов 1–4), `joint-expectation-rules.md` (R1+R4), `output-template.md` (11 секций), `predictions-for-review-spec.md`.
- ✅ EXAMPLES.md (10 сценариев), TODO.md (v1.1 / v2 / v3 roadmap).
- ✅ D4 paths: lowercase везде (`integrated-view-*`, `weekly-review-*`, `stress-*`, `portfolio-*`).
- ✅ Model: Opus 4.7 обязательно (multi-source aggregation с CI propagation).
- НЕ покрыто в v1 (намеренно): R3 multiple horizons, R4 full covariance, R8 concurrency, R9 calibrated catalyst quality. См. TODO.md.

### Phase 8 — save-to-library расширение ✅ (завершена 2026-05-06)
- ✅ Новые Workflows F–K: weekly-review, integrated-view, portfolio-snapshot, macro-snapshot, macro-input, forecast-collection.
- ✅ Workflow D: DOCX удалён, ретро-аудит переехал в `audits/{date}-{topic}.md`.
- ✅ Workflow A: `lib_*.md` → `{source}-{period}.md`; домен `commodity-agencies` добавлен.
- ✅ Шаг 0: таблица классификации расширена до 11 типов.
- ✅ INDEX-templates/ убраны; минимальные шаблоны INDEX.md встроены в B7/C7 inline.
- ✅ `_sync_log.md` прописан во всех Workflows A–K.
- ✅ `assemble_artifact.py`: +commodity-agencies, +validate-weekly-review, +validate-snapshot.
- ✅ Тесты: 55 → 66 проверок.
- Верификация 2026-05-06: ключевые пункты (Workflows F–K, assemble_artifact.py, 66 тестов, Workflow D/A) подтверждены чтением кода. Phase 8 помечена корректно.

### Phase 9 — memory-sync, revise-memory-* ✅ (завершена 2026-05-06)
- ✅ `memory-sync`: Step 3 переписан под динамический Glob `domains/*/` (вместо хардкоженного списка 5 доменов); добавлена `LOCAL_DOMAINS_ROOT`; Setup-секция убрана от фиксированного `mkdir`; `references/index-templates.md`: шаблон таблицы динамический, справочник subdomain'ов дополнен `commodity-agencies`, добавлен дисклеймер «код не фильтрует по этому списку».
- ✅ `revise-memory-remote`: Слой 1 переписан на динамический discovery `domains/`; JSON-схема `audits` обобщена до `{domain_dir}`; Workflow §1 добавлен discovery-шаг для обоих транспортов.
- ✅ `revise-memory-local`: расширен с 36 до 139 строк (4 фазы, anti-patterns, структура файлов); созданы `references/memory-structure.md` и `references/consolidation-rules.md`.

### Phase 10.1 — Локальный интерактивный дашборд (активная, ~3 сессии MVP)

Расширение spec06 (`INTEGRATION-DOCS/06-portfolio-integrated-viewer-HTML-spec.md`) под реальный workflow. Архитектура «Frame + History Strips»: один integrated-view как primary view, supplementary YAML/JSON для drill-down, плюс multi-weekly/multi-stress/multi-macro как history для diff/timeline/sparklines.

**Loading:** Mode 4 (folder picker через `<input webkitdirectory>` или `showDirectoryPicker`) для desktop Safari/Chrome/Edge; Mode 5 (manual drag-drop) как fallback для iOS Safari.

**UI:** 8 базовых вкладок spec06 + 3 новые — Diff vs last week (изменения verdict / fundamental / catalysts / div_yield), Action queue (HIGH-priority через все источники), Macro context (sparklines из ru-*.md).

**Этапы:**
- A — базовый viewer (8 вкладок + drill-down + charts) + Mode 5: ~1.5 сессии.
- A+ — Mode 4 folder picker + auto-detect: ~0.3 сессии.
- B — Diff vs last week: ~0.5 сессии.
- C — Action queue + Predictions countdown: ~0.5 сессии.
- D (опц.) — Timeline в drill-down: ~0.5 сессии.
- E (опц.) — Macro context tab: ~0.5 сессии.

**MVP = A + A+ + B + C ≈ 3 сессии.** Полный 10.1 ≈ 3.8 сессии.

**Деплой:** `tools/portfolio-integrated-viewer.html` → копия в `Claude-Memory/Tools/` (через Synology Drive sync). Открывается через Safari `file://` со смонтированного NAS.

### Phase 10.2 — NAS hosting (отложено, см. `docs/investment/_cross-cutting/phase-10.2-nas-hosting.md`)

Поднятие HTTP-сервера на NAS для доступа с iPhone в LAN и опциональной глобальной видимости. Архивный план в `docs/investment/_cross-cutting/phase-10.2-nas-hosting.md` содержит:
- Контекст ограничений Synology Web Station (`/home/` недоступен по дефолту).
- Три опции (Container Manager + Caddy / Task Scheduler + python http.server / rsync mirror в /volume1/web/).
- HTTP loading modes (Mode 1 autoindex / Mode 2 manifest / Mode 3 URL query).
- Безопасность (HTTPS + Basic Auth для глобального доступа).

Объём ~1–1.3 сессии после готовности 10.1.

### Phase 11 — Validation hooks (Phase 7 INTEGRATION-DOCS, 0.5 сессии) ✅ (завершена 2026-05-07)
- ✅ `Portfolio/INDEX.md` переписан: исправлены пути (D4, lowercase), структура subdirs, dependency-иерархия.
- ✅ Раздел «Self-validation roadmap» добавлен в `Portfolio/INDEX.md`: таблица integrated-view → target audit date (2026-11-06), инструкция по аудиту, checklist что проверяется.
- ✅ `save-to-library` Workflow G расширен: G5 (Calendar reminder) — вычисление T+6 мес, предложение создать Google Calendar event через MCP или показать текст для ручного создания, обновление Self-validation roadmap table. Текущий G5 переименован в G6.

### Phase 12 — `## Inputs / Outputs` во все скиллы (1 сессия) ✅ (завершена 2026-05-07)
- ✅ Добавлены блоки `## Inputs / Outputs` в 8 скиллов, у которых их не было: ru-portfolio-advisor, forecast-collector, forecast-confidence-applier, retrospective-forecast-audit, save-to-library, memory-sync, revise-memory-local, revise-memory-remote.
- ✅ Все 16 скиллов покрыты (grep: 16/16).
- Формат: шаблон §5 плана; maintenance-скиллы (save-to-library, memory-sync, revise-memory-local) используют адаптированный заголовок Outputs («пишет напрямую, без буфера чата»).

**Итого:** ~14 сессий (Phase 0/1/4/4.1/5 завершены — 5 сессий). MVP без Phase 10 — 13 сессий.

---

## 7. Обновление CLAUDE.md (черновик)

Ключевые изменения для корневого `CLAUDE.md`:

1. **Структура хранилища** — заменить текущий блок реальной структурой из §1 этого плана с `Portfolio/` веткой.
2. **DAG** — обновить:
   ```
   forecast-collector → retrospective-forecast-audit → save-to-library
   forecast-confidence-applier → (HST опц.) → save-to-library
   scenario-builder → (HST опц.) → save-to-library
   macro-ru-watcher → save-to-library
   macro-forecast-chain → portfolio-scenario-stress → save-to-library
   portfolio-data-loader → save-to-library → ru-portfolio-advisor
                                          → portfolio-integrated-view ← weekly-review (advisor)
   ```
3. **Правило D3:** «Никакой скилл, кроме save-to-library, не пишет напрямую в Claude-Memory/. Каждый генерирует artefact в чат, пользователь явно вызывает save-to-library.»
4. **Транспорт:** Synology mount (единственный с миграции 2026-08-13); путь `~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/`. Каждая Cowork-сессия — `request_cowork_directory`. Ссылка на `_shared-references/transport-layer.md`.
5. **Конвенция имён:** lowercase kebab-case для всех файлов и папок (`portfolio-*`, `macro-input-*`, `stress-*`, `weekly-review-*`, `integrated-view-*`). UPPER-CASE — единственное исключение: `INDEX.md`.
6. **Префикс `lib_*`:** удалён. Файлы аудитов — `<source>-<period>.md`, обнаружение по frontmatter (`source`, `trust`, `pin`).
7. **Домены:** добавить `commodity-agencies/`.
8. **`_sync_log.md`:** упомянуть как пишется save-to-library и memory-sync.
9. **`KNOWN_SPLITS`:** «единственное место правды — `portfolio-data-loader/scripts/portfolio_returns.py`. Advisor никогда не трогает.»
10. **Tier 1 / Tier 2:** ввести как часть схемы forecast-events. Tier 1 = только FCA, Tier 2 = FCA+HST с parallel `-stress` парой.
11. **Список скиллов:** добавить `portfolio-integrated-view` (новый, Phase 7).
12. **Ссылка на `INTEGRATION-DOCS/00-MASTER-PLAN.md`** как основной документ архитектуры Portfolio Integrated View.
13. **Ссылка на `docs/investment/_cross-cutting/plan.md`** (этот файл) как roadmap правок.

---

## 8. Что не трогаем

- `ru-portfolio-advisor` mode 1 vs 8 (отложено).
- Mode internals advisor (8 режимов) — рефактор только по §3 этого плана.
- `INTEGRATION-DOCS/` — read-only для этой работы; правки оттуда только если найдём расхождение с реальностью при имплементации.

---

## 9. Решения по открытым вопросам (зафиксированы 2026-05-05)

| # | Вопрос | Решение |
|---|---|---|
| Q1 | Структура `Portfolio/` | **Плоский Portfolio/** — оптимизировать под мобильный доступ: минимум вложенности, связанные файлы рядом. Все портфельные артефакты под одной веткой |
| Q2 | Миграция | `Claude-Memory/` лежит на gDrive, git нет — **миграция = простое переименование папок** через transport-layer. Никаких `git mv` и case-проблем |
| Q3 | `Claude-Portfolio/` (внешняя ветка) | Это исторические JSON от portfolio-loader. **Мигрировать в `Claude-Memory/Portfolio/snapshots/`** и удалить старую ветку |
| Q4 | Schema versioning | **Применить strict `schema_version`**, но интеграцию (Portfolio Integrated View) пока не делаем. На этом этапе только готовим: добавляем поле `schema_version: "1.0"` во все новые YAML; ретро-валидация существующих — отдельной задачей перед Phase 7 |
| Q5 | Pack-скилл | **Доработан 2026-05-05** (вариант B + embed-on-pack): исправлен путь (`skills/<имя>/`); скрипт работает через mktemp — инжектит shared-refs в временную копию, репо остаётся чистым; slash-command переписан. См. `pack.sh` и `.claude/commands/pack.md` |
| Q6 | Case-конвенция | **Финализирована** (D4): lowercase для результатов работы скиллов (`portfolio-*.json`, `weekly-review-*.yaml`, …); UPPER_CASE для инфраструктуры (`INDEX.md`, всё содержимое `Claude-Memory/_shared/`) |
| Q7 | Shared-refs архитектура | **Вариант B + embed-on-pack** (D1): в репо нет sync-копий, `pack.sh` инжектит при упаковке. Pack уже подготовлен под эту схему |

### Phase 0 — итог (всё выполнено, Phase 1 готова к старту)

- ✅ `pack.sh` переписан под вариант B: temp-dir, embed-on-pack, cleanup.
- ✅ `.claude/commands/pack.md` обновлён под новый flow.
- ✅ `_shared-references/` создан (7 файлов по списку §2).
- ✅ `Claude-Memory/` мигрирована (все папки переименованы/перемещены, файлы в lowercase).
- ✅ `_shared/DEPENDENCY-MAP.md` создан; `SOURCE-REGISTRY.md` и `PERSPECTIVE-MAPS.md` не создаются (решение 2026-05-05: дублируют `INDEX.md`).
- ✅ `schema_version: 1` уже присутствует в `_shared-references/yaml-schemas.md`.
- ✅ `CLAUDE.md` обновлён.
- ✅ `Portfolio/README.md` создан.
- ⚠️ `Portfolio/INDEX.md` — устаревшее содержимое (ревизия в Phase 2).

### Phase 5 — итог (всё выполнено, Phase 6 готова к старту)

- ✅ Форкаст-пайплайн очищен: D3/D6 полная компиляция.
- ✅ forecast-collector: триггер уточнен, связь с confidence-applier разорвана.
- ✅ forecast-confidence-applier: Шаг 6 в reference, прямая запись в Claude-Memory убрана.
- ✅ hypothesis-stress-tester: patch → stress-pair (15 замен), Шаги 1 и 6 в references.
- ✅ scenario-builder, forecast-monitor: добавлены `## Inputs / Outputs`, пути исправлены.
- ✅ Созданы 3 новых reference-файла в скиллах.
