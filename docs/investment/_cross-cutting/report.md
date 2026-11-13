# Аудит скиллов Claude Code: согласованность и качество

**Дата:** 2026-05-05
**Объект:** репозиторий `/Users/you/Documents/personal-analytics-skills/`
**Охват:** 15 скиллов, 6470 строк `SKILL.md`, 50 reference-файлов
**Метод:** статический анализ — чтение `SKILL.md` + всех `references/*.md` без доступа к артефактам в `Claude-Memory/`

---

## 0. Метод и охват верификации

**Верифицировано на реальных артефактах в `~/Library/CloudStorage/SynologyDrive-home/Ext_gDrive/`:**

- `Claude-Memory/INDEX.md` (master)
- `Claude-Memory/forecasts/INDEX.md` + парный `brent-oil-dec-2026-2026-04-30.{md,yaml}`
- `Claude-Memory/scenarios/scenario-brent-dec-2026-2026-04-30.yaml`
- `Claude-Memory/Macro-Chain/MACRO-INPUT-2026-05-04.yaml`
- `Claude-Memory/Portfolio-Stress/STRESS-2026-05-04-macro-input.yaml`
- `Claude-Memory/geopolitics/isw-2022-2025.md` (frontmatter профиля источника)
- `Claude-Memory/_sync_log.md`
- `Portfolio-Snapshots/PORTFOLIO-2026-05-03.json`
- `Macro-Snapshots/RU-2026-05-02.md`

**Не проверено** (низкий приоритет): локальный `~/.claude/.../memory_user_edits`, файлы reports/*.docx (бинарные), все `*.md` в `geopolitics/, ru-sellside/, ...` (просмотрен один как образец).

Раздел 12 в конце отчёта суммирует подтверждённые и опровергнутые гипотезы.

---

## 1. Резюме (Executive Summary)

### Главное

- **Архитектура звуква́** — DAG из CLAUDE.md внутренне непротиворечив, скиллы правильно ссылаются друг на друга в общих словах.
- **Метаданные дрейфуют** — параллельные копии общих файлов (`transport-layer.md`, `events-yaml-spec.md`) расходятся между скиллами.
- **YAML-схемы фрагментированы** — три разные парадигмы по DAG прогнозов (`forecast_collection` / `fca` / `forecast-events`), нет single source of truth.
- **Контракты передачи данных размыты** — нигде нет явного раздела `## Inputs/Outputs`, поэтому несовместимости находятся при чтении деталей.
- **Несколько скиллов перегружены** — 8 из 15 имеют `SKILL.md` >400 строк; крупные блоки (методологии, шаблоны выходов, YAML-примеры) сидят в `SKILL.md` вместо `references/`.
- **Один скилл недоделан** — `revise-memory-local` (35 строк, без references).

### Метрики перегруженности

| Скилл | Строки `SKILL.md` | references | Статус |
|---|---:|---:|---|
| macro-forecast-chain | **849** | 5 | 🔴 раздут |
| save-to-library | **739** | 3 | 🔴 раздут |
| retrospective-forecast-audit | **635** | 7 | 🟡 крупный |
| forecast-confidence-applier | **551** | 6 | 🟡 крупный |
| forecast-collector | 497 | 2 | 🟡 крупный |
| forecast-monitor | 491 | 2 | 🟡 крупный |
| ru-portfolio-advisor | 473 | 11+README | 🟡 многорежимный |
| portfolio-scenario-stress | 421 | 6 | 🟢 ок |
| scenario-builder | 380 | 1 | 🟡 мало references |
| hypothesis-stress-tester | 344 | **0** | 🟡 монолит |
| revise-memory-remote | 335 | 1 | 🟢 ок |
| memory-sync | 250 | 5 | 🟢 ок |
| portfolio-data-loader | 247 | 6 | 🟢 ок |
| macro-ru-watcher | 223 | 4 | 🟢 ок |
| revise-memory-local | **35** | **0** | 🔴 недоработан |

### Карта приоритетов (P0–P3)

| # | Проблема | Прио | Усилие | Где |
|---|---|---|---|---|
| **0** | **CLAUDE.md разошёлся с реальностью** (см. раздел 12) | **P0** | низкое | CLAUDE.md |
| 1 | `events-yaml-spec.md` — 2 идентичные копии | **P0** | низкое | save-to-library, forecast-monitor |
| 2 | `INDEX-templates/` упоминаются, но не существуют | **P0** | низкое | save-to-library |
| 3 | `transport-layer.md` — 11 копий, дрейф | **P1** | среднее | весь репо |
| 4 | YAML-схемы не сведены в один документ | **P1** | среднее | forecast-* |
| 5 | Дублирование расчётов advisor ↔ data-loader | **P1** | среднее | portfolio-* |
| 6 | revise-memory-local недоделан | **P1** | среднее | revise-memory-local |
| 7 | Нет `## Inputs/Outputs` ни в одном скилле | **P2** | низкое | все 15 |
| 8 | macro-forecast-chain раздут до 849 строк | **P2** | среднее | macro-forecast-chain |
| 9 | save-to-library раздут до 739 строк | **P2** | среднее | save-to-library |
| 10 | Triggers description пересекаются | **P2** | низкое | 6+ скиллов |
| 11 | hypothesis-stress-tester — монолит без refs | **P2** | низкое | hypothesis-stress-tester |
| 12 | Контракты MACRO-INPUT / STRESS / PORTFOLIO.json не зафиксированы в SKILL.md | **P1** | низкое | macro-forecast-chain, portfolio-scenario-stress, portfolio-data-loader |
| 13 | dependency-map.md инлайн в forecast-monitor | **P3** | низкое | forecast-monitor |
| 14 | 8 режимов advisor — режимы 1 и 8 пересекаются | **P3** | среднее | ru-portfolio-advisor |
| 15 | revise-memory-local никем не упомянут | **P3** | низкое | revise-memory-local |
| 16 | `lib_*.md` префикс — устарелая конвенция (реально без префикса) | **P0** | низкое | save-to-library, memory-sync, CLAUDE.md |
| 17 | `scenarios/` lowercase в реальности (CLAUDE.md и скиллы пишут `Scenarios/`) | **P0** | низкое | проверить case-sensitivity, привести к единому |

---

## 2. Системные (cross-cutting) проблемы

### 2.1 Дрейф `transport-layer.md` — 11 копий, 3 группы

11 скиллов содержат `references/transport-layer.md`, **все разного размера** (4654–7422 байт). Файлы дрейфовали независимо.

| Группа | Размер | Файлы | Содержание |
|---|---:|---|---|
| **A — базовые (идентичны)** | 4654–5798 | forecast-confidence-applier, macro-ru-watcher, memory-sync, ru-portfolio-advisor, scenario-builder | базовое ядро Transport B/A |
| **B — расширенные** | 6191–6444 | forecast-monitor, save-to-library, revise-memory-remote | + блок про парные YAML, ссылка на `events-yaml-spec.md`, упоминание `haiku-forecast-checker` |
| **C — специализированные** | 5228–7422 | macro-forecast-chain, portfolio-data-loader, portfolio-scenario-stress | собственные пути (`MACRO_CHAIN_DIR`, `PORTFOLIO_SNAPSHOTS_ROOT`, `Portfolio-Stress`, `sector-overrides.yaml`, `stale_flags.yaml`, fallback `PORTFOLIO_DIR_LEGACY`) |

**Конкретный риск:** `scenario-builder` пишет `*.yaml` в `Scenarios/`, но его `transport-layer.md` (Группа A) **не описывает парный YAML** — то есть скилл создаёт артефакт, формат которого не описан в его собственной transport-документации. Аналогично `forecast-confidence-applier` — пишет YAML в форматах из Группы B, но имеет копию из Группы A.

**Рекомендация (P1):**
1. Создать `_shared-references/transport-layer-base.md` — общее ядро (Transport B/A, Cowork procedure, типовые операции).
2. В каждом скилле оставить тонкий `transport-layer.md`: 1 строка ссылки + 5–15 строк локальной специализации.
3. forecast-confidence-applier и scenario-builder — добавить блок про парные YAML.
4. macro-forecast-chain, portfolio-* — оставить специализированные дополнения (они корректны).

---

### 2.2 `events-yaml-spec.md` — две идентичные копии (509 × 2)

```
forecast-monitor/references/events-yaml-spec.md
save-to-library/references/events-yaml-spec.md
```

Хеш совпадает. Это нарушение DRY: изменение в одной копии не синхронизируется. Фактически, файл должен быть **single source of truth** для всех скиллов, работающих с `forecasts/*.yaml` и `Scenarios/*.yaml`.

**Рекомендация (P0):** Переместить в `_shared-references/events-yaml-spec.md`, удалить дубликаты, в обоих скиллах оставить ссылку. Дополнительно: `revise-memory-remote` тоже валидирует эти YAML по неявной схеме — должен ссылаться на тот же файл.

---

### 2.3 YAML-схемы фрагментированы по DAG

Три скилла пишут YAML-метаданные о прогнозах с **разными парадигмами** и без явного контракта:

| Скилл | Тип | Поля верхнего уровня |
|---|---|---|
| forecast-collector | `type: forecast_collection` | `n_collected`, `n_dropped`, `warnings:` |
| forecast-confidence-applier | `method: fca` | `upstream_snapshot:`, `geopolitics_translation:`, `alternatives:` |
| forecast-monitor (читает) | `type: forecast-events` | `forecast.date`, `monitoring[]`, `deadlines[]`, `falsifiers[]`, `reviews.next_due` |
| save-to-library (пишет события) | то же `forecast-events` | вычисляет `reviews.next_due` из `interval_months` |

**Критическая лакуна:** `forecast-confidence-applier` (Шаг 6, строки 388–453) показывает Events YAML с полем `reviews.interval_months`, а `forecast-monitor` (Шаг 3a, строка 99) ждёт `reviews.next_due`. **Кто и где вычисляет `next_due`?** В тексте подразумевается save-to-library, но это явно не написано.

**Дополнительные несовместимости имён файлов:**
- collector → `FC-[ИСТОЧНИК]-collection-YYYY-MM-DD.md` в `forecast-collections/` (не в `forecasts/`)
- confidence-applier → ищет `Glob("*.md", path="{LOCAL_LIBRARY_ROOT}/forecasts/")`, но collector сохраняет в другое место
- monitor → читает `forecasts/*.yaml` и ищет по `topic:` в frontmatter, не по имени

**Рекомендация (P1):** Создать `_shared-references/yaml-schemas.md` с тремя секциями:
- `## type: forecast_collection` — output forecast-collector, input retrospective-audit
- `## type: forecast-events` — output forecast-confidence-applier (через save-to-library), input forecast-monitor
- `## type: scenario-events` — output scenario-builder, input forecast-monitor

И отдельный `_shared-references/file-naming.md` с явным правилом: где какие файлы лежат, как они находятся (по имени vs по полю frontmatter).

---

### 2.4 Нет единого реестра подпапок `Claude-Memory/` и источников

CLAUDE.md перечисляет 10 подпапок: `geopolitics/, ru-sellside/, global-banks/, tech-ceo/, ru-macro/, forecasts/, Scenarios/, Portfolio-Snapshots/, Macro-Snapshots/, reports/`. Но ни один скилл не использует все 10.

**Покрытие подпапок скиллами:**

| Подпапка | save-to-library | memory-sync | revise-memory-remote | Кто пишет |
|---|:---:|:---:|:---:|---|
| geopolitics/ | ✅ | ✅ | ✅ | save-to-library (Workflow A) |
| ru-sellside/ | ✅ | ✅ | ✅ | save-to-library |
| global-banks/ | ✅ | ✅ | ✅ | save-to-library |
| tech-ceo/ | ✅ | ✅ | ✅ | save-to-library |
| ru-macro/ | ✅ | ✅ | ✅ | save-to-library |
| forecasts/ | ✅ | ❌ | ✅ | save-to-library (Workflow B) |
| Scenarios/ | ✅ | ❌ | ✅ | save-to-library (Workflow C) |
| reports/ | ✅ | ❌ | ❌ | save-to-library (Workflow D) |
| **Portfolio-Snapshots/** | ❌ | ❌ | ❌ | **никто (загадка)** |
| **Macro-Snapshots/** | ❌ | ❌ | ❌ | **никто (загадка)** |

`memory-sync` ограничен только аудит-доменами — это, видимо, by design (только для `[lib]`-записей в `memory_user_edits`), но это **нигде не объяснено**. `Portfolio-Snapshots/` и `Macro-Snapshots/` упоминаются в CLAUDE.md, но **ни один скилл не описывает запись в них**. Видимо, их пишут `portfolio-data-loader` и `macro-ru-watcher` напрямую, минуя save-to-library, но это не зафиксировано.

**Реестр источников также фрагментирован** в 4 файлах:
- `forecast-collector/references/source-strategies.md` — как получить архив
- `forecast-confidence-applier/references/source-discovery.md` — списки по доменам
- `forecast-confidence-applier/references/perspective-maps.md` — карты позиций
- `retrospective-forecast-audit/references/consensus-sources.md` — откуда брать консенсус

Домены повторяются: `geopolitics`, `ru-macro`, `ru-sellside`, `global-banks`, `tech-ceo` — но логика «что и зачем брать» расходится.

**Рекомендация (P2):**
1. `_shared-references/claude-memory-layout.md` — единственный реестр подпапок с полем «кто пишет / кто читает».
2. `_shared-references/source-registry.md` — единая таблица источников `| Источник | Домен | Скилл-читатель | Стратегия доступа |`.
3. Решить судьбу `Portfolio-Snapshots/` и `Macro-Snapshots/`: либо добавить в save-to-library, либо отметить «пишутся напрямую данными-скиллами».

---

### 2.5 `## Inputs/Outputs` — нет ни в одном скилле

Ни один из 15 `SKILL.md` не имеет явного раздела с описанием входов и выходов. Это приходится восстанавливать чтением 200–700 строк методологии.

**Последствие:** контракты между скиллами не документированы единообразно — все находки 2.3 (несовместимость YAML), 7.1 (INDEX-templates), 8.2 (output-schema vs advisor) **прячутся** именно из-за этого.

**Рекомендация (P2):** Ввести во все 15 скиллов одинаковый блок сразу после frontmatter:

```markdown
## Inputs / Outputs

**Inputs:**
- {файл/запрос} ← {откуда}, {какой формат / reference}

**Outputs:**
- {файл/артефакт} → {куда}, {какой формат / reference}

**Upstream скиллы:** {список}
**Downstream скиллы:** {список}
```

Это самый дешёвый и высокоэффективный фикс — раскроет все контрактные проблемы.

---

## 3. Перегруженность отдельных `SKILL.md`

### 3.1 `macro-forecast-chain` (849 строк)

Самый раздутый скилл. В `SKILL.md` сидят большие шаблоны выходов и YAML-примеры:

| Строки | Что | Куда вынести |
|---|---|---|
| 615–730 | YAML-шаблон `macro_input.yaml` + caveats типов | `references/macro-input-template.yaml` |
| 253–285 | Coverage Report — детальный пример с конкретными статусами | `references/coverage-report-template.md` |
| 375–407 | Каскадный план запуска (DAG-plan) | `references/dag-plan-template.md` |

**Потенциальное сокращение:** ~180 строк (21%). Останется логика DAG без переполнения примерами.

### 3.2 `save-to-library` (739 строк)

Содержит четыре workflow развёрнуто целиком:
- Workflow A (Аудиты): 67–144
- Workflow B (Прогнозы): 147–387
- Workflow C (Сценарии): 390–534
- Workflow D (Ретро-отчёты): 537–633

В `references/` всего 3 файла. Что нужно вынести:

| Что | Куда | Прио |
|---|---|---|
| Семантическая валидация confidence (B4.1a, 241–285) | `references/confidence-validation.md` | P2 |
| Правила slug для topic/id (упоминаются в B3, B4.4, нет деталей) | `references/slug-rules.md` | P2 |
| Дефолты `review_interval_months` по domain (199) | `references/review-intervals.md` | P3 |
| Шаблоны `INDEX-templates/forecasts-INDEX.md`, `Scenarios-INDEX.md` (упоминаются в 361, 514) | **создать или удалить упоминание** | **P0** (см. 7.1) |
| DOCX-генерация (Workflow D) | `references/docx-generation.md` | P3 |

### 3.3 `retrospective-forecast-audit` (635 строк)

| Строки | Что | Куда |
|---|---|---|
| 112–260 | Декомпозиция A/B/C, три шкалы оценки, маркеры, матрица ценности (148 строк методологии) | `references/evaluation-matrix.md` |
| повторы | Шаги 5–6 правил таблиц повторяют Шаг 2 теории | дедупликация в одном reference |

### 3.4 `forecast-monitor` (491 строка)

| Строки | Что | Куда |
|---|---|---|
| 91–192 | Полная спец web_search пост-фильтра (101 строка) | `references/event-handling-logic.md` |
| 482–491 | Inline fallback dependency-map | удалить, сослаться на `macro-forecast-chain/references/dependency-map.md` |

### 3.5 `ru-portfolio-advisor` (473 строки + 11 references + README + CHANGELOG + EXAMPLES + USAGE)

Многорежимный (8 режимов). Перегружен дважды: размером и числом артефактов вокруг.

| Строки | Что | Куда |
|---|---|---|
| 113–165 | Стартовый 5-шаговый чек-лист | `references/startup-checklist.md` |
| 172–346 | Расчёт XIRR/TWR/ROI — **дублирует data-loader** | сослаться на `portfolio-data-loader/references/xirr-twr-calculation.md` |
| 405–453 | «Обязательный процесс анализа» + «Что не делать» | `references/analysis-process.md` |
| правила 19–22 | Иерархия trust-профилей инвест-домов | `references/trust-hierarchy.md` |

При выносе — сократится на ~40% (до ~280 строк, как у data-loader). Также рассмотреть, действительно ли нужны параллельно `README.md`, `CHANGELOG.md`, `EXAMPLES.md`, `USAGE.md` — это нетипично много для скилла.

### 3.6 `hypothesis-stress-tester` (344 строки, 0 references)

Декларирует себя монолитом (строка 342: «references — нет»), но содержит крупные блоки, которые по логике должны быть в references:

| Строки | Что | Куда |
|---|---|---|
| 78–118 | Tier 1 методы (Pre-mortem, KAC lite, ACH lite, Devil's Advocate) — 40 строк методологических справок | `references/tier1-methods.md` |
| 214–273 | Events YAML patch spec (60 строк) | `references/hst-events-yaml-spec.md` |
| 303–313 | `auto_checkable` правила — таблица | (включить в hst-events-yaml-spec.md) |

После выноса: ~225 строк в SKILL.md + 2 references = разумный баланс.

### 3.7 `forecast-collector` (497) и `forecast-confidence-applier` (551)

Менее критично, но оба перегружены:
- collector: вынести Шаг 4 «правила отсева» (если занимает >40 строк)
- confidence-applier: вынести Шаг 6 (Events YAML composition) — сейчас 65 строк inline

---

## 4. Недоделанность

### 4.1 `revise-memory-local` (35 строк, 0 references)

Сравнение с `revise-memory-remote` (335 строк, 1 reference) показывает разрыв в зрелости:

| Параметр | revise-memory-local | revise-memory-remote |
|---|---|---|
| Строк SKILL.md | 35 | 335 |
| References | 0 | 1 |
| Описаны слои проверки | нет | 3 |
| Алгоритм консолидации | прозой | пошагово |
| Целевые метрики | «MEMORY.md ≤200 строк, ~25 КБ» — задано | измеримо |
| Что считать дублем | не описано | есть критерии |

**Конкретные пробелы:**
- Нет описания структуры `~/.claude/projects/*/memory/MEMORY.md` и `*.md` файлов памяти
- Нет правил отличия долгосрочного факта от ephemeral
- Нет алгоритма обработки относительных дат («на следующей неделе» → 2026-MM-DD)
- Нет связи с другими скиллами (хотя save-to-library и memory-sync работают со смежной памятью)

**Рекомендация (P1):**
1. Создать `revise-memory-local/references/memory-structure.md` — формат файлов auto-memory, поля frontmatter, MEMORY.md как индекс.
2. Создать `references/consolidation-rules.md` — критерии дубля, алгоритм слияния, обработка дат.
3. Расширить SKILL.md до ~150–200 строк с workflow, как у remote-варианта.
4. Явно указать связь: «работает только с локальной auto-memory; для библиотеки на Synology — `revise-memory-remote`».

### 4.2 Несуществующие `INDEX-templates/`

`save-to-library` ссылается на:
- строка 361: `INDEX-templates/forecasts-INDEX.md`
- строка 514: `INDEX-templates/Scenarios-INDEX.md`

**Этих файлов нет в репозитории.** `revise-memory-remote` валидирует INDEX.md, но без явной схемы — он сравнивает парность, не структуру.

**Рекомендация (P0):** Либо создать шаблоны (предпочтительно — внутри `save-to-library/references/`), либо удалить ссылки и описать структуру inline.

### 4.3 `Portfolio-Snapshots/` и `Macro-Snapshots/` без писателя

Объявлены в CLAUDE.md, но ни в `save-to-library`, ни в data-скиллах не описано, как туда сохраняется. Вероятно, `portfolio-data-loader` и `macro-ru-watcher` пишут напрямую — это нужно зафиксировать в их `SKILL.md`.

---

## 5. Триггеры (`description`) пересекаются

### 5.1 forecast-collector vs forecast-confidence-applier

- collector: «Сбор прогнозов из источника», 10–20 верифицируемых
- confidence-applier: «Агрегирует прогнозы из 3–7 источников»

**Риск:** запрос «прогноз по нефти на 2026» подходит обоим. Различие — collector требует конкретный архив (Telegram/блог/PDF), confidence-applier работает по теме.

**Рекомендация:** уточнить description явно:
- collector → «Сбор верифицируемых прогнозов из КОНКРЕТНОГО АРХИВА»
- confidence-applier → «Агрегация текущих мнений ≥3 источников по ТЕМЕ»

### 5.2 scenario-builder vs hypothesis-stress-tester vs macro-forecast-chain

Все три имеют «scenario / forecast / matrix» в триггерах:
- scenario-builder: «какие сценарии возможны», «построй сценарии»
- hypothesis-stress-tester: «стресс-тест прогноза»
- macro-forecast-chain: «собери матрицу прогнозов»

**Различие:** macro-forecast-chain — про **факторные** прогнозы (Brent, USDRUB), не про сценарии. Описание не подчёркивает это.

**Рекомендация:** в macro-forecast-chain description: «Обновляет матрицу факторных прогнозов (не сценарных Shell 2×2 — для этого scenario-builder).»

### 5.3 portfolio-data-loader vs portfolio-scenario-stress vs ru-portfolio-advisor

- data-loader говорит «сценарный анализ → portfolio-scenario-stress»
- advisor включает «фундаментальный анализ позиции» и сам внутренне запускает скрипты loader'а

**Риск:** при «оцени мой портфель» — может активироваться advisor, который потом запросит то, что уже сделал loader (а если файлы не в `Portfolio-Snapshots/`, цикл задвоится).

**Рекомендация:** в advisor — добавить «НЕ активировать без файлов в текущем сообщении». В loader — «НЕ активировать, если нужна интерпретация».

### 5.4 save-to-library / memory-sync / revise-memory-remote / revise-memory-local

Не пересекаются по словам, но функционально:
- save-to-library пишет
- revise-memory-remote проверяет написанное
- memory-sync синхронизирует часть (только аудиты!)
- revise-memory-local — изолированно, на локальной памяти

**Рекомендация:** в каждом из 4 скиллов добавить блок «Связанные скиллы» в верхнюю часть.

---

## 6. Размытые границы ответственности

### 6.1 portfolio-data-loader vs ru-portfolio-advisor

**Декларация (CLAUDE.md):** loader — чистый data layer, advisor — анализ.

**Реальность:**
- advisor (стр. 313–346) имеет свой раздел расчёта доходности отдельной бумаги, который вызывает скрипты `portfolio-data-loader/scripts/`
- advisor (стр. 29–30) копирует список `KNOWN_SPLITS` из data-loader; CLAUDE.md (стр. 98) предписывает обновлять `KNOWN_SPLITS` в `scripts/portfolio_returns.py`, но не указывает, **из какого скилла**
- output-schema.md (data-loader) описывает JSON, advisor (140–169) описывает свои поля парсера — формальная связь не указана

**Риск:** при добавлении нового сплита advisor может предложить обновить `KNOWN_SPLITS`, и пользователь обновит inline в Python-файле, а не через data-loader. Версии разойдутся.

**Рекомендация (P1):**
1. Явно зафиксировать в advisor: расчёты идут только через скрипты, advisor — потребитель `Portfolio-Snapshots/`.
2. При появлении нового сплита advisor → запрашивает дату → перенаправляет в data-loader для обновления registry.
3. Добавить в advisor SKILL.md ссылку на `portfolio-data-loader/references/output-schema.md` как описание формата JSON-снапшота.

### 6.2 macro-ru-watcher vs macro-forecast-chain

CLAUDE.md: «watcher — без интерпретации, chain — оркестратор». В тексте обоих скиллов это соблюдается, но они **независимы** и нигде это явно не сказано.

`macro-forecast-chain` НЕ читает `Macro-Snapshots/` (созданные watcher'ом). Это **не баг**, но не очевидно — пользователь может ожидать, что chain «знает» текущие значения CBR/Brent.

**Рекомендация:** в macro-forecast-chain Шаг 2.1 одной строкой: «macro-ru-watcher создаёт информационную панель и не влияет на DAG; для текущих значений факторов читай свежие forecasts в forecasts/.»

### 6.3 memory-sync vs revise-memory-local

Оба касаются «памяти», но на разных уровнях:
- memory-sync: Synology / Google Drive → `[lib]`-записи в `memory_user_edits`
- revise-memory-local: локальный `.claude/projects/*/memory/`

**Цепочка не описана:** что попадает в локальную auto-memory? Кто туда пишет? Где граница между `[lib]`-записями и обычной auto-memory?

**Рекомендация (P2):** В `memory-sync/SKILL.md` или отдельном `_shared-references/memory-architecture.md` нарисовать цепочку:
```
Local auto-memory (write by Claude Code runtime) ─ revise-memory-local чистит
Claude-Memory/ (write by save-to-library) ─ revise-memory-remote ревизует
                                          └ memory-sync читает frontmatter аудитов → memory_user_edits [lib]
```

---

## 7. Локальные точечные проблемы

### 7.1 `INDEX.md` — кто читает, кто пишет, по какой схеме?

`save-to-library` пишет:
- `Claude-Memory/{subfolder}/INDEX.md` (для каждой подпапки доменов)
- `Claude-Memory/INDEX.md` (master)
- `forecasts/INDEX.md`, `Scenarios/INDEX.md`, `reports/INDEX.md`

**Кто читает?** Только `revise-memory-remote` (для проверки парности). Но **не по схеме**, а по фактам.

**Шаблонов нет** — `save-to-library` ссылается на несуществующие `INDEX-templates/`. Структура восстанавливается только из текста в Workflow A/B/C/D.

**Рекомендация (P0):** Создать `save-to-library/references/index-md-schema.md` с конкретными шаблонами и привести к нему ссылки во всех Workflow. Альтернатива — описать структуру INDEX.md inline и удалить ссылки на несуществующие шаблоны.

### 7.2 Frontmatter аудитов (`source`, `trust`, `period`)

Описана только в `save-to-library/SKILL.md` (стр. 81–99). `revise-memory-remote` (Слой 1, стр. 42–50) валидирует те же поля без ссылки на единое описание. `memory-sync` читает `trust`, чтобы решить, попадёт ли запись в `memory_user_edits`.

**Рекомендация (P2):** Создать `_shared-references/audit-frontmatter-schema.md`. Все три скилла ссылаются на него.

### 7.3 `forecast-monitor` — inline `dependency-map.md`

Шаг 7 (стр. 365–425) пытается читать `references/dependency-map.md`, которого **нет в forecast-monitor/references/** (он есть только в `macro-forecast-chain/references/`). Скилл fallback'ит на встроенный минимальный маппинг (стр. 482–491) — антипаттерн, потому что при обновлении в macro-forecast-chain forecast-monitor отстанет.

**Рекомендация (P3):** Сделать `dependency-map.md` shared (например, под `_shared-references/`) или явно сослаться из forecast-monitor на путь `../macro-forecast-chain/references/dependency-map.md`. Удалить inline fallback.

### 7.4 `confidence-applier`: `reviews.next_due` vs `reviews.interval_months`

В Шаге 6 (стр. 388–453) `forecast-confidence-applier` пишет `reviews.interval_months`. `forecast-monitor` (Шаг 3a, стр. 99) ищет `reviews.next_due`. **Кто вычисляет переход?** Подразумевается save-to-library — но это явно не написано.

**Рекомендация (P1):** Включить в `_shared-references/yaml-schemas.md` (см. 2.3) явный absatz: «`save-to-library` при сохранении прогноза вычисляет `reviews.next_due = forecast.date + reviews.interval_months` и пишет это поле в frontmatter.»

### 7.5 advisor: режимы 1 и 8 пересекаются по акциям

Из 8 режимов:
- Режим 1 (Weekly Stocks): новостной обзор активных акций, 7 дней
- Режим 8 (Stock Quality Forward Review): стратегический обзор с XIRR за всё время + 1–2 года forward

Оба требуют `per_security_xirr.py` по каждой акции, оба упирают в макро-фильтр. Граница — горизонт. Но в triggers (стр. 361–386) оба ловятся на «обзор акций».

**Рекомендация (P3):** Либо слить режимы в один с флагом `--deep` (для Opus), либо переписать триггеры явно: режим 1 = «еженедельный обзор», режим 8 = «годовой / стратегический обзор».

### 7.6 portfolio-scenario-stress — input-adapters не связаны с уровнями

Шаг 1 (стр. 54–95) описывает приоритет источников D > C > B > A. Шаг 2 (стр. 104–132) ссылается на `references/input-adapters.md` для нормализации. Но в `input-adapters.md` нет таблицы соответствия `уровень → файл → нормализуемые поля`. Шаг 2 неюзабелен без одновременного чтения нескольких файлов.

**Рекомендация (P2):** Добавить в SKILL.md таблицу:
```
| Уровень | Файл input | Нормализуемые поля | Reference |
| D | MACRO-INPUT-*.yaml | all_factors (6) | input-adapters §D |
| C | stress-tested.yaml | main_case, vulnerabilities | input-adapters §C |
| B | filtered_consensus.md | factors, alternatives | input-adapters §B |
| A | пользовательский ввод | вручную | input-adapters §A |
```

### 7.7 `model-routing` для режима 8 не сигнализируется наружу

ru-portfolio-advisor (стр. 79) обещает: «При режиме, требующем более мощной модели, добавь рекомендацию переключиться». Это работает изнутри, но `references/README.md` (28 строк, мета-индекс) **не упоминает** этого правила. Пользователь, читающий метаиндекс, не узнает, что режим 8 — Opus.

**Рекомендация (P2):** В `references/README.md` добавить блок «Model Routing Summary» с явным указанием Opus 4.7 для режима 8.

---

## 8. Кросс-ссылки между скиллами (полнота connectivity)

| Скилл | Ссылается на | Должен ссылаться |
|---|---|---|
| forecast-collector | retrospective-forecast-audit ✅, save-to-library ✅ | forecast-confidence-applier (контракт FC-* → fca) |
| forecast-confidence-applier | save-to-library (косвенно) | forecast-collector ✅ (Шаг 2 fallback), forecast-monitor (через `next_due`) |
| forecast-monitor | macro-forecast-chain ✅ (Шаг 7), но без файла | save-to-library (как источник YAML) |
| retrospective-forecast-audit | forecast-collector ✅, save-to-library ✅ | — |
| scenario-builder | hypothesis-stress-tester ✅ (Шаг 4) | save-to-library |
| hypothesis-stress-tester | forecast-confidence-applier ✅ | scenario-builder (downstream после triage) |
| macro-forecast-chain | portfolio-scenario-stress (handoff не явный) | macro-ru-watcher (явно сказать, что не зависит) |
| macro-ru-watcher | — | portfolio-data-loader (косвенно), macro-forecast-chain |
| portfolio-data-loader | ru-portfolio-advisor (косвенно), portfolio-scenario-stress (триггер) | save-to-library (для Portfolio-Snapshots/) |
| portfolio-scenario-stress | macro-forecast-chain (через D-уровень), forecast-confidence-applier (B-уровень) | save-to-library |
| ru-portfolio-advisor | portfolio-data-loader (через скрипты) | portfolio-scenario-stress (через макро-фильтр) |
| save-to-library | memory-sync ✅, revise-memory-remote ✅ | revise-memory-local (нет связи — нормально) |
| memory-sync | save-to-library (косвенно) | — |
| revise-memory-local | **никого** | — (изолирован by design, но это надо явно сказать) |
| revise-memory-remote | save-to-library ✅ | memory-sync (после правок) |

**Существенные пропуски:**
- `forecast-collector` ↔ `forecast-confidence-applier`: контракт FC-*-collection-*.md → confidence-applier не зафиксирован. confidence-applier ищет в `forecasts/`, collector сохраняет в `forecast-collections/`.
- `macro-forecast-chain` → `portfolio-scenario-stress`: handoff формата `macro_input.yaml` упоминается, но без явного раздела «что portfolio-scenario-stress читает из этого файла».
- `revise-memory-local` — никем не упомянут и сам никого не упоминает.

---

## 9. Проверка соответствия CLAUDE.md

| Утверждение в CLAUDE.md | Реальность в скиллах |
|---|---|
| DAG: forecast-collector → confidence-applier → portfolio-scenario-stress | ✅ В целом, но контракт между collector и confidence-applier неявный (см. 2.3) |
| watcher без интерпретации, chain — оркестратор | ✅ Соблюдается, но граница не зафиксирована в самих скиллах (см. 6.2) |
| Transport B (Synology) — основной | ✅ Все 11 transport-layer.md это явно говорят |
| 8 режимов advisor | ✅ Все 8 описаны, но 1 и 8 пересекаются (см. 7.5) |
| `Portfolio-Snapshots/` и `Macro-Snapshots/` | ⚠️ Объявлены, но не описано, кто туда пишет (см. 4.3) |
| `_sync_log.md` | ⚠️ Упомянут только в CLAUDE.md, не упоминается ни в одном скилле |
| Opus 4.7 для режима 8 advisor | ✅ Прописано в advisor, но не в README/мета (см. 7.7) |
| KNOWN_SPLITS обновляется в `portfolio_returns.py` | ⚠️ И data-loader, и advisor упоминают это; владелец не зафиксирован (см. 6.1) |
| Никогда не вызывать `merge_cross_currency_positions` снаружи | ⚠️ Сказано в CLAUDE.md, но не во всех скиллах, использующих скрипты |

---

## 10. План действий (приоритезированный)

### P0 — быстрые исправления (1–2 часа суммарно)
1. **events-yaml-spec.md** — выбрать одну копию как канон, удалить другую, оставить ссылку
2. **INDEX-templates/** в save-to-library — либо создать, либо удалить упоминания
3. Удалить inline `dependency-map.md` fallback из forecast-monitor (если решено держать его в macro-forecast-chain)

### P1 — структурные фиксы (полдня)
4. **transport-layer.md** — выделить shared base, сократить копии до тонких локальных дополнений
5. **`_shared-references/yaml-schemas.md`** — единая схема всех YAML-типов в DAG (forecast_collection, forecast-events, scenario-events, fca-output)
6. **`_shared-references/file-naming.md`** — конвенции имён файлов
7. **`_shared-references/claude-memory-layout.md`** — реестр подпапок и ответственных
8. **revise-memory-local** — расширить до 150–200 строк, добавить 2 references

### P2 — качество и читаемость (1–2 дня)
9. Ввести `## Inputs/Outputs` во все 15 скиллов (самый высокоэффективный фикс)
10. Разрезать macro-forecast-chain (вынести 3 шаблона)
11. Разрезать save-to-library (вынести confidence-validation, slug-rules)
12. Разрезать ru-portfolio-advisor (вынести startup-checklist, дедуплицировать XIRR с data-loader)
13. Создать references для hypothesis-stress-tester (tier1-methods, hst-events-yaml-spec)
14. `_shared-references/audit-frontmatter-schema.md` — единая схема для аудит-файлов
15. Уточнить triggers (forecast-collector vs confidence-applier; advisor vs data-loader)

### P3 — финальные улучшения
16. Дописать model-routing summary в advisor README
17. Решить судьбу режимов 1 и 8 advisor (слить или явно разнести)
18. `_shared-references/memory-architecture.md` — диаграмма потоков (local memory → remote → memory_user_edits)
19. Добавить «Связанные скиллы» в верхнюю часть всех 15 скиллов

---

## 11. Что следует сохранить (не трогать)

Не всё нуждается в правках. Ниже — то, что выглядит зрелым и согласованным:

- **CLAUDE.md** — DAG, model routing, тестовая структура, ограничения по сплитам — всё корректно зафиксировано.
- **portfolio-data-loader** — границы (data layer без анализа) соблюдены, references полны.
- **portfolio-scenario-stress** — внутренне непротиворечив (только мелкая правка по input-adapters, см. 7.6).
- **revise-memory-remote** — как референс зрелости для revise-memory-local.
- **macro-ru-watcher** — компактный (223 строки), хорошо ограничен.
- **memory-sync** — компактный (250 строк), 5 references, чистый scope.

---

## Приложение A. Скилл-by-скилл сводка перегруженности

```
🔴 раздут (>700 строк)         macro-forecast-chain (849), save-to-library (739)
🟡 крупный (400–700)           retrospective-forecast-audit (635), forecast-confidence-applier (551),
                              forecast-collector (497), forecast-monitor (491), ru-portfolio-advisor (473),
                              portfolio-scenario-stress (421)
🟡 без references               hypothesis-stress-tester (344, 0 refs), scenario-builder (380, 1 ref)
🟢 ок                           revise-memory-remote (335), memory-sync (250),
                              portfolio-data-loader (247), macro-ru-watcher (223)
🔴 недоделан                    revise-memory-local (35, 0 refs)
```

## Приложение B. Reference-файлы — карта дублирования

```
transport-layer.md           ×11  — 3 группы по содержанию (см. 2.1)
events-yaml-spec.md          × 2  — идентичны (см. 2.2)
output-template.md           × 3  — forecast-confidence-applier, macro-ru-watcher, portfolio-scenario-stress
output-templates.md          × 2  — retrospective-forecast-audit, ru-portfolio-advisor
output-schema.md             × 1  — portfolio-data-loader
model-routing.md             × 2  — retrospective-forecast-audit, ru-portfolio-advisor
sources*.md / source-*.md    × 4  — fragmentированы (см. 2.4)
methodology-*.md             × 1  — retrospective-forecast-audit
domain-*.md                  × 3  — retrospective-forecast-audit (geopolitics, finance-ru, tech-ceo)
```

## 12. Верификация по реальным артефактам (Synology Drive)

### 12.1 КРИТИЧНО: CLAUDE.md разошёлся с реальной структурой хранилища

**Декларация в CLAUDE.md:**
```
Claude-Memory/
├── geopolitics/, ru-sellside/, global-banks/, tech-ceo/, ru-macro/
├── forecasts/, Scenarios/
├── Portfolio-Snapshots/, Macro-Snapshots/
└── reports/, _sync_log.md
```

**Реальная структура `Ext_gDrive/`:**
```
Ext_gDrive/
├── Claude-Memory/
│   ├── geopolitics/, ru-sellside/, global-banks/, tech-ceo/, ru-macro/   ✅
│   ├── commodity-agencies/                                                ❌ нет в CLAUDE.md (домен EIA STEO)
│   ├── forecasts/                                                         ✅
│   ├── scenarios/                                                         ⚠️  lowercase, в CLAUDE.md и скиллах "Scenarios/"
│   ├── Macro-Chain/                                                       ❌ нет в CLAUDE.md (выходы macro-forecast-chain)
│   ├── Portfolio-Stress/                                                  ❌ нет в CLAUDE.md (выходы portfolio-scenario-stress)
│   ├── _meta-analysis/                                                    ❌ нет в CLAUDE.md (пустая)
│   ├── reports/, INDEX.md, _sync_log.md                                   ✅
├── Macro-Snapshots/                                                       ❌ СНАРУЖИ Claude-Memory/, не внутри
├── Portfolio-Snapshots/                                                   ❌ СНАРУЖИ Claude-Memory/, не внутри
└── Claude-Portfolio/                                                      ❌ ЦЕЛАЯ ОТДЕЛЬНАЯ ВЕТКА не упомянута
    ├── forecasts/
    └── INDEX.md
```

**Влияние:**
- `_shared-references/claude-memory-layout.md` (предлагался в P2) должен описывать **минимум 3 sibling-директории**, не одну.
- Скиллы, использующие пути из CLAUDE.md как авторитетные, могут промахиваться (особенно `Macro-Snapshots/`, `Portfolio-Snapshots/`).
- В transport-layer.md `macro-forecast-chain` (Группа C — расширенная) пути `MACRO_CHAIN_DIR`, `Portfolio-Stress/`, `Portfolio-Snapshots/` — **корректные**, это группа A/B (forecast-confidence-applier и др.) отстают.
- **`Claude-Portfolio/` — отдельная ветка** с собственным INDEX.md и `forecasts/`. Кто туда пишет — неизвестно из самих скиллов; нужно выяснить и зафиксировать.

**Рекомендация (P0):** обновить CLAUDE.md под реальность; ввести в `_shared-references/` единый реестр путей, и каждому скиллу указать, в какую sibling-директорию он пишет/читает.

### 12.2 Конвенция имён файлов аудитов: `lib_*.md` НЕ используется

**В CLAUDE.md (стр. 71):** `geopolitics/ — профили аудитов источников (lib_*.md)`

**В save-to-library/SKILL.md (Workflow A):** многократное упоминание `lib_*.md`.

**Реальность в `Claude-Memory/geopolitics/`:**
```
carnegie-2010-2016.md
chatham-house-2013-2021.md
isw-2022-2025.md
qdr-2001-reference.md
stratfor-1995-2025.md
stratfor-2010-2020-reference.md
stratfor-2015-2025.md
INDEX.md
```

**Префикс `lib_` ни на одном файле.** Это **breaking change** в конвенции, не отражённый в SKILL.md и CLAUDE.md.

**Влияние:**
- `memory-sync` ищет файлы для агрегации `[lib]`-записей — если он опирается на `lib_*` glob, он промахивается; видимо использует другой критерий (frontmatter `pin`/`trust`).
- `revise-memory-remote` валидирует «lib_*.md ↔ lib_*.yaml» парность — реально пары `<source>-<period>.md` без yaml (профили это .md only).

**Рекомендация (P0):** В save-to-library, memory-sync, CLAUDE.md заменить `lib_*.md` на `<source>-<period>.md` или явно описать, что префикс не используется и обнаружение по frontmatter (`source`, `trust`, `pin`).

### 12.3 ✅ Подтверждённые гипотезы

| Гипотеза | Подтверждение |
|---|---|
| `events-yaml-spec.md` действительно используется как канон | `forecasts/INDEX.md` явно ссылается: «Полная схема `*.yaml` — в `save-to-library/references/events-yaml-spec.md`» |
| `reviews.next_due` вычисляется при сохранении (предположительно save-to-library) | `brent-oil-dec-2026-2026-04-30.yaml`: `forecast_date: 2026-04-30 + interval_months: 3 → next_due: 2026-07-30` ✅ |
| `INDEX.md` реально пишутся и поддерживаются | мастер `Claude-Memory/INDEX.md` обновляется (комментарий «Last sync: 2026-05-04, Goldman Sachs added»); `forecasts/INDEX.md` детальная таблица с 14 активными прогнозами |
| Frontmatter аудитов согласован | `isw-2022-2025.md`: `source, period, audit_type, audit_date, last_updated, trust:{...}, pin: true, theses_count, hit_rate, alpha_generation, avg_value, skill_version` — соответствует `save-to-library` Workflow A |
| YAML-схема `forecast-events` богата и стабильна | `brent-oil-dec-2026-*.yaml`: `forecast.{date,horizon,domain,topic,central_estimate,confidence}`, `reviews`, `final_audit`, `monitoring[]`, `assumptions[]`, `thresholds[]`, `deadlines[]`, `falsifiers[]`, `agents[]`, везде поле `auto_checkable: bool` |
| YAML-схема `scenario-events` отдельная и согласованная | `scenario-brent-dec-2026-*.yaml`: `type: scenario-events`, `matrix.{axis_x, axis_y}`, `scenario_triggers[].{scenario_id, label, probability, enabling_conditions[], leading_indicators[]}` |
| `_sync_log.md` имеет стабильный формат | реальный лог `## Sync 2026-05-02 MSK ...` со списком `replace`/`add` операций и счётчиками `LIB_ENTRIES`/`USER_ENTRIES` |

### 12.4 ⚠️ Опровергнутые / уточнённые гипотезы

| Гипотеза в отчёте | Уточнение по факту |
|---|---|
| Контракт collector → confidence-applier (FC-*-collection-*.md) реальный | В реальной `forecasts/` файлов с префиксом `FC-*-collection-*` НЕТ. Сюда пишет только save-to-library (через FCA+HST). Видимо, collector сохраняет в **отдельную** папку (workspace или отдельная), и его выходы преобразуются. Это нужно прояснить |
| `Portfolio-Snapshots/` и `Macro-Snapshots/` пишутся напрямую data-скиллами | ✅ подтверждено — лежат **снаружи** Claude-Memory/ как отдельные sibling-директории. CLAUDE.md ошибается в иерархии |
| `forecast-events` — единый формат для прогнозов | В `forecasts/INDEX.md` есть градация **Tier 1 / Tier 2** — то есть существует ещё один уровень типизации, не описанный явно в SKILL.md. Tier 2 = FCA+HST, Tier 1 = только FCA |
| `forecasts/` содержит только output FCA | Реально содержит `*-stress.{md,yaml}` (после HST) — например `iran-us-may-deal-2026-04-30-stress.{md,yaml}` рядом с `iran-us-may-deal-2026-04-30.{md,yaml}`. То есть HST пишет **новый файл** с суффиксом `-stress`, а не патчит существующий |

### 12.5 Реальные контракты, которые надо явно зафиксировать в SKILL.md

Все три ниже-описанных формата **существуют и работают**, но **не задокументированы явно** ни в одном `SKILL.md` как контракт. Это нужно добавить.

#### 12.5.1 `MACRO-INPUT-YYYY-MM-DD.yaml` — выход `macro-forecast-chain`

Файл: `Claude-Memory/Macro-Chain/MACRO-INPUT-2026-05-04.yaml`

Реальная структура:
```yaml
run_id: MFC-20260504-1
mode: QUICK-REFRESH | FULL  # 2 режима
generated_at: <date>
portfolio_snapshot: PORTFOLIO-YYYY-MM-DD.json     # ссылка на input
transport: "A (Google Drive MCP)" | "B (Synology)"
chain_target_horizons: [<list of dates>]

coverage:
  total_required: 10
  total_fresh: 10
  coverage_score: "10/10"
  ready_for_stress_test: bool

sectors_in_portfolio: [<list>]

forecasts:
  geopolitics: {status, type: scenario_matrix|single_estimate, ..., source_file, geopolitics_translation: {method, ...}}
  sanctions: {...}
  cbr_rate: {..., upstream_snapshot: [{factor, central_estimate, confidence, date}]}
  inflation_ru: {..., scenario_breakdown: {Sc-A, Sc-B, Sc-C, Sc-D}}
  brent: {..., alternatives: [{scenario, probability, range}]}
  urals_discount: {...}
  usdrub: {..., sensitivity: {brent_plus_15, brent_minus_15, fnb_threshold}}
  cnyrub: {...}
  xauusd: {..., p10_p90: {P10, P90}}
  budget_deficit: {..., note}

scenarios:                                          # 4-5 сценариев + Unaccounted
  - {label, probability, factors: {brent_dec26_usd, urals_discount_usd, cbr_rate_pct, ...}}

caveats:                                            # 8 типов
  - {type: LOW_CONFIDENCE_CLUSTER | CONSISTENCY_WARNING | NONLINEAR_CONDITIONAL_ON_MODAL | ZERO_AUDITED_SOURCES | HORIZON_GAP | MISSING_FACTOR | ...,
     factors|factor, severity: low|medium|high, note, ...}

ready_for_stress_test: bool
blocking_issues: []
```

**Где это должно жить:** `macro-forecast-chain/references/macro-input-template.yaml` (и в SKILL.md явный раздел `## Output contract`). Сейчас в SKILL.md шаблон **разбросан** по строкам 615–730 без единого имени.

#### 12.5.2 `STRESS-YYYY-MM-DD-<source>.{md,yaml}` — выход `portfolio-scenario-stress`

Файл: `Claude-Memory/Portfolio-Stress/STRESS-2026-05-04-macro-input.yaml`

Реальная структура:
```yaml
date: <date>
scenario_source: macro-forecast-chain | forecast-confidence-applier | scenario-builder | manual
weight_type: probability | equal
portfolio_snapshot_id: PORTFOLIO-YYYY-MM-DD.json
macro_input_id: MACRO-INPUT-YYYY-MM-DD.yaml         # ссылка вверх по DAG
run_id: PSS-YYYYMMDD-N
scenario_count: int
total_value_rub: int

scenarios:
  - {label, probability, factors: {brent_pct_change, urals_discount_usd, rate_bps_change, inflation_ru_pct,
                                    usdrub_pct_change, cnyrub_pct_change, xauusd_pct_change,
                                    sanctions_escalation: bool, geopol_escalation: bool},
     pnl_rub, pnl_pct}

portfolio_pl_range_rub: {min, max}
expected_pl_rub: int
prob_loss: float
prob_gain: float

top_risks:
  - {rank, ticker, sector, worst_scenario, delta_rub, delta_pct, main_factor}

concentration_metrics: {banks_share_pct, fx_bonds_share_pct, long_rub_weakening_share_pct,
                        sector_concentration_top, dominant_factor}
unmapped_tickers: [<list>]
review_date: <date>
notes: <str>
```

**Где это должно жить:** `portfolio-scenario-stress/references/output-template.md` уже есть, но нужно сверить со схемой выше. **Поле `macro_input_id` критично** — обеспечивает обратную трассируемость по DAG, без него нельзя восстановить, на каких прогнозах стресс-тест считался.

#### 12.5.3 `PORTFOLIO-YYYY-MM-DD.json` — выход `portfolio-data-loader`

Файл: `Portfolio-Snapshots/PORTFOLIO-2026-05-03.json` (93 KB)

Реальная структура:
```json
{
  "schema_version": "1.0",
  "as_of_date": "<date>",
  "generated_at": "<iso8601>",
  "input_files": {"trades": "<filename.xlsx>", "balance": "<filename.numbers>"},
  "holdings": [
    {
      "ticker": "<str>",
      "isin": "<str|null>",
      "name": "<str>",
      "qty": <num>,
      "avg_cost_rub": <num|null>,
      "current_price": <num>,
      "current_price_source": "moex_iss",
      "current_price_ts": "<iso>",
      "value_rub": <num>,
      "currency": "RUB|USD|EUR|CNY",
      "asset_type": "stock|bond|fund|cash",
      "account": "main|iis|...",
      "is_blocked": bool,
      "nominal_currency": "<str>",
      "ytm_pct": <num|null>,
      "ytm_source": "<str|null>"
    }
  ]
}
```

**Где это должно жить:** `portfolio-data-loader/references/output-schema.md` существует, но **не проверено** соответствует ли описание реальным полям. Нужно сверить и привести в соответствие. Конкретно — поля `is_blocked`, `nominal_currency`, `ytm_source`, `current_price_source`, `current_price_ts` должны быть явно в схеме.

### 12.6 Дополнительные конкретные находки

**Дубликаты в `Macro-Snapshots/`:**
```
RU-2026-05-02.md       (1948 байт)
RU-2026-05-02 (1).md   (2376 байт)
```
Похоже, артефакт Synology cloud-sync (конфликт версий). `macro-ru-watcher` должен иметь правило обработки такой ситуации — сейчас не описано.

**Tier 1 vs Tier 2 в `forecasts/INDEX.md`:**
- `Tier 1` — только FCA (events-yaml без HST полей)
- `Tier 2` — FCA + HST (events-yaml с `assumptions`, `thresholds`, `agents`)

Это дополнительная градация, не зафиксированная ни в `events-yaml-spec.md`, ни в `forecast-confidence-applier`, ни в `hypothesis-stress-tester`. Должна быть явная схема.

**Файлы со суффиксом `-stress`:** `iran-us-may-deal-2026-04-30-stress.{md,yaml}` — паттерн «оригинальный FCA + после HST с суффиксом». Это **не патч**, как описано в hypothesis-stress-tester (Шаг 6 «Events YAML patch»), а **отдельная пара файлов**. Расхождение: HST SKILL.md описывает «patch на существующий yaml», в реальности — параллельная копия с `-stress` суффиксом.

**Master `INDEX.md` содержит структуру track record:** `Track record summary` (строки 22–40) — таблица с trust по subdomain'ам. Это богатая структура, **которая никем не описана как контракт** — но `memory-sync` явно её строит. Нужно зафиксировать формат `INDEX.md` master в save-to-library/references.

**`commodity-agencies/`:** новый домен (EIA STEO добавлен в master INDEX 2026-05-04). Должен быть в списке доменов в save-to-library, memory-sync, revise-memory-remote, CLAUDE.md. Сейчас все три устарели.

### 12.7 Итог по верификации

**Хорошие новости:**
- Реальные YAML-схемы богаты и согласованы между парами файлов (.md ↔ .yaml).
- INDEX.md mastered и обновляется.
- DAG `macro-forecast-chain → portfolio-scenario-stress` работает с явными reference-id (`portfolio_snapshot_id`, `macro_input_id`).
- `_sync_log.md` ведётся с предсказуемой структурой.
- Frontmatter аудитов соответствует тому, что описано в save-to-library.

**Плохие новости:**
- CLAUDE.md существенно устарел (архитектура, имена подпапок, префикс `lib_`).
- 3 ключевых output-контракта (MACRO-INPUT.yaml, STRESS.yaml, PORTFOLIO.json) **существуют, но не зафиксированы явно** в `SKILL.md` как контракты — каждый раз модель восстанавливает их из шаблонов в SKILL.md.
- HST реально пишет файлы с суффиксом `-stress`, а в SKILL.md описан как «patch».
- `Tier 1` vs `Tier 2` — реально используется, нигде не описано.

**Финальная рекомендация:** до правок самих скиллов (P1–P3) сначала сделать **обновление CLAUDE.md и реестра путей** (P0), иначе все остальные правки рискуют закрепить устаревшие представления.

---

## Приложение C. Предлагаемая структура `_shared-references/`

```
_shared-references/
├── transport-layer-base.md         # Transport B/A core, Cowork procedure
├── events-yaml-spec.md             # один источник правды для forecast-events / scenario-events
├── yaml-schemas.md                 # все YAML типы в DAG прогнозов
├── file-naming.md                  # FC-*, *-{date}, slug правила
├── claude-memory-layout.md         # реестр подпапок и владельцев
├── source-registry.md              # таблица всех источников
├── audit-frontmatter-schema.md     # для lib_*.md
├── memory-architecture.md          # диаграмма local memory ↔ Claude-Memory ↔ memory_user_edits
└── README.md                       # индекс
```
