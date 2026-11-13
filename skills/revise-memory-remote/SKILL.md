---
name: revise-memory-remote
description: "Ревизия библиотеки Claude-Memory на Synology: проверяет YAML frontmatter аудитов, парность *.md ↔ *.yaml в forecasts/ и Scenarios/, консистентность INDEX.md, актуальность прогнозов и сценариев. Выдаёт краткий отчёт в чат с предлагаемыми действиями. Используй когда пользователь говорит «ревизия памяти», «проверь библиотеку», «revise memory», «проверь прогнозы», «что устарело в Claude-Memory», «проверь yaml», или запускай ежемесячно вместе с check_forecasts."
shared_refs: [transport-layer, events-yaml-spec, yaml-schemas, audit-frontmatter-schema]
---

# revise-memory-remote

Ревизия библиотеки `Claude-Memory` как источника истины. Три независимых слоя:

1. **Слой 1 — Аудиты.** Файлы аудитов источников во всех субпапках `domains/`.
   Список доменов определяется динамически через Glob — скилл не фиксирует конкретные имена папок.
2. **Слой 2 — Прогнозы.** Файлы в `forecasts/`: парность `*.md` ↔ `*.yaml`, валидность yaml-схемы, актуальность по `next_due` / `final_audit.due`.
3. **Слой 3 — Сценарии.** Файлы в `scenarios/`: парность, валидность yaml-схемы, актуальность.

Результат — краткий структурированный отчёт в чат. Файлы не создаются и не изменяются без явного подтверждения.

---

## Inputs / Outputs

**Inputs:**
- `Claude-Memory/` (все субдиректории) ← Synology mount: `domains/*/`, `forecasts/`, `scenarios/`, INDEX.md

**Outputs (как artefact в чат):**
- Отчёт с предлагаемыми действиями → пользователь подтверждает → правки в `Claude-Memory/` только с явного подтверждения

**Upstream скиллы:** — (maintenance-скилл)
**Downstream скиллы:** — (опц.: save-to-library для cleanup, revise-memory-local)
**Shared refs:** transport-layer, events-yaml-spec, yaml-schemas, audit-frontmatter-schema

---

## Транспортный слой

Читай `references/transport-layer.md` — пути и типовые операции.

```
LOCAL_ROOT = ~/Library/CloudStorage/SynologyDrive-home/Claude-Memory
```
Транспорт один — Synology mount; недоступен → остановиться и сообщить пользователю.

---

## Делегирование скрипту `scripts/validate_library.py`

Все детерминированные проверки (frontmatter обязательные поля, парность .md ↔ .yaml,
schema validation forecast-events / scenario-events, триггеры по датам, сумма
probability, broken refs, INDEX consistency) — **в скрипте**. LLM никогда не
сравнивает даты, не считает сумму вероятностей и не валидирует поля вручную.

### Workflow

1. **LLM читает файлы** через transport:
   - **Слой 1 (discovery):** `Glob("*/", path="{LOCAL_ROOT}/domains/")` → список domain_dirs;
     для каждого — `Glob("*.md", path="{LOCAL_ROOT}/domains/{domain_dir}/")` + Read.
   - **Слой 2–3:** Glob/Read для `forecasts/` и `scenarios/` как прежде.
2. **LLM парсит** YAML frontmatter и YAML-файлы. Файлы, которые не парсятся,
   передавай в скрипт со значением `null` в `yaml_data` — он их флагнет как
   `yaml_unparseable`.
3. **LLM собирает payload** (см. схему ниже) и вызывает скрипт.
4. **LLM группирует issues** по `layer` / `level` / `category` и форматирует
   итоговые таблицы и блок «Предлагаемые действия».

### JSON-вход

```json
{
  "today": "YYYY-MM-DD",
  "audits": {
    "{domain_dir}": {
      "files": [
        {"basename": "isw-2024.md",
         "frontmatter": {"source": "ISW", "audit_date": "2024-09-15", "trust": {...}}}
      ],
      "index_entries": ["isw-2024.md", "..."]
    }
  },
  // Ключи "audits" — имена папок из domains/, обнаруженных через Glob.
  // Их количество не фиксировано: добавление нового домена не требует правки скилла.
  // Папки `audits/` и `_audits/` deprecated и в норме пусты: аудиты источников живут в `domains/<dom>/`, слой 1 читает именно их.
  // Без `index_entries` у папки INDEX-проверка пропускается с жёлтой записью `index_check_skipped`.
  "forecasts": {
    "files_md":   ["russia-2026.md", "..."],
    "files_yaml": ["russia-2026.yaml", "..."],
    "files_docx": ["legacy.docx"],
    "yaml_data": {
      "russia-2026.yaml": { ...распарсенный yaml... }
    },
    "index_entries": ["russia-2026.md", "russia-2026.yaml", "..."]
  },
  "scenarios": {
    "files_md":   ["..."],
    "files_yaml": ["..."],
    "yaml_data":  { "...": {...} }
  },
  "portfolio_carriers": {
    "decisions": {"2026-10-30T1015-GMKN.json": { ...распарсенный json... }},
    "conditions": { ...conditions.yaml... },
    "conditions_archive": [{ ...conditions-archive-2025.yaml... }],
    "conditions_state": { ...conditions-state.json... },
    "security_attrs": { ...security-attrs.json... },
    "snapshot_keys": ["SBER", "RU000A10...", "LQDT"],
    "blocked_keys": ["JPM", "KO"]
  },
  "library_layout": {
    // Слой 6 — структурные проблемы layout'а, не связанные с контентом файлов.
    // Полностью опциональный: если ключа нет → слой пропускается.
    "deprecated_dirs": {
      "_audits": ["fursov-2020-2024-audit", "rebuild-plan-2026-05-11.md"],
      "audits":  []
    },
    "dup_marker_files": [
      "_sync_log (1).md", "_sync_log (2).md",
      "_sync_log_append_2026-05-15-zhirinovsky.md",
      "domains/geopolitics/INDEX (1).md"
    ],
    "domains": {
      "geopolitics": ["fursov-2020-2024-audit.md", "zhirinovsky-1991-2022.md", "..."]
    }
  }
}
```

`index_entries` опционально — если `null`, проверка INDEX пропускается.

`portfolio_carriers` опционально — нет ключа или поле `null` → соответствующая проверка пропускается. Сборка payload
(всё из `Claude-Memory/Portfolio/`, файлы читаются только для ревизии, не правятся):

1. `decisions` — Glob `decisions/*.json`, каждый файл распарсить: `{имя файла: объект}`.
2. `conditions` — `conditions.yaml` (формат `conditions@2`); `conditions_archive` — список распарсенных
   `conditions-archive-*.yaml` (нужны, чтобы события прошлых условий нашли определение).
3. `conditions_state` — `conditions-state.json`.
4. `security_attrs` — `security-attrs.json`; `snapshot_keys` — ключи бумаг последнего
   `snapshots/portfolio-{date}.json` (тикер у акций и фондов, ISIN у облигаций); бумаги со `status == "blocked"`
   (замороженные с 2022) — отдельно в `blocked_keys`, скрипт их вычтет.

Решения, условия и справочник бумаг пишут только скрипты save-to-library (`decision_write.py`,
`apply_condition.py`, `security_attrs.py`), состояние условий — только hub-api: находки слоя чинятся ими, не правкой файла.

### Вызов

```bash
cat payload.json | python3 scripts/validate_library.py --pretty
# или: python3 scripts/validate_library.py --input payload.json --output report.json
```

### JSON-выход

```json
{
  "today": "...",
  "summary": {
    "audits_checked": N, "audits_with_issues": N,
    "forecasts_md": N, "forecasts_yaml": N, "forecasts_docx": N,
    "forecasts_with_issues": N,
    "scenarios_md": N, "scenarios_yaml": N, "scenarios_with_issues": N,
    "carriers_decisions": N, "carriers_decision_keys": N, "carriers_conditions": N,
    "carriers_state_events": N, "carriers_security_attrs": N, "carriers_with_issues": N,
    "library_layout_deprecated_files": N, "library_layout_dup_markers": N, "library_layout_profile_suffix": N,
    "total_issues": N, "red": N, "yellow": N, "green": N
  },
  "issues": [
    {
      "layer": "audits|forecasts|scenarios|weekly_reviews|portfolio_carriers|library_layout",
      "file": "geopolitics/cfr-2024.md",
      "level": "red|yellow|green",
      "category": "audit_missing_required",      // machine code
      "human_message": "нет обязательных полей: audit_date",
      "action_hint": "добавить вручную или через save-to-library",
      "detail": { ... опциональный контекст ... }
    },
    ...
  ]
}
```

### Категории issues (для группировки в таблицах)

| Layer | Category | Level |
|---|---|---|
| audits | `audit_missing_required` | red |
| audits | `audit_no_frontmatter` | yellow |
| audits | `audit_missing_recommended` | yellow |
| audits/forecasts/scenarios | `index_dead_link` | yellow |
| audits/forecasts/scenarios | `index_missing_entry` | yellow |
| audits/forecasts/scenarios | `index_check_skipped` | yellow |
| forecasts | `orphan_yaml` | red |
| forecasts/scenarios | `md_without_yaml` | yellow |
| forecasts | `docx_without_md` | yellow |
| forecasts | `yaml_no_schema_version` | yellow |
| forecasts/scenarios | `yaml_wrong_type` | yellow |
| forecasts | `yaml_wrong_forecast_ref` | red |
| forecasts | `yaml_missing_forecast_field` | red |
| forecasts/scenarios | `horizon_before_date` | red |
| forecasts | `nonstandard_interval_months` | yellow |
| forecasts/scenarios | `final_audit_due_mismatch` | yellow |
| forecasts | `missing_auto_checkable` | yellow |
| forecasts/scenarios | `final_audit_due` | red |
| forecasts/scenarios | `final_audit_overdue` | red |
| forecasts | `outcome_uncaptured` | yellow (§2.3.1 — superseded/expired, исход не зафиксирован → capture + save-to-library) |
| forecasts | `deferred_schedule_passed` | red (§19 — отложенный аудит просрочен) |
| forecasts | `deferred_without_schedule` | yellow (§19 — deferred без scheduled_for) |
| forecasts/scenarios | `review_due` | yellow |
| forecasts/scenarios | `review_due_soon` | green (info-only) |
| forecasts/scenarios | `broken_superseded_by` | red |
| forecasts/scenarios | `missing_audit_file` | yellow |
| scenarios | `yaml_wrong_scenario_ref` | red |
| scenarios | `yaml_missing_matrix_field` | red |
| scenarios | `scenario_triggers_count` | yellow |
| scenarios | `probability_sum_off` | yellow |
| forecasts/scenarios | `yaml_unparseable` | red |
| portfolio_carriers | `ds_decision_invalid` | red |
| portfolio_carriers | `ds_decision_name_mismatch` | red |
| portfolio_carriers | `ds_decision_review_overdue` | yellow (`review_by` текущего решения бумаги в прошлом) |
| portfolio_carriers | `ds_conditions_invalid` | red |
| portfolio_carriers | `ds_state_invalid` | red |
| portfolio_carriers | `ds_state_orphan_event` | red (событие состояния без определения условия) |
| portfolio_carriers | `ds_security_attrs_invalid` | red |
| portfolio_carriers | `ds_security_attrs_missing` | yellow (бумага снапшота без записи в справочнике) |
| library_layout | `deprecated_directory_file` | red |
| library_layout | `dup_marker_file` | red |
| library_layout | `profile_audit_suffix` | yellow |

Полное описание правил — в исходнике `scripts/validate_library.py`.

### Сборка `library_layout` payload

1. **`deprecated_dirs`**: проверить существование папок `Claude-Memory/_audits/` и `Claude-Memory/audits/`. Если есть — `Glob("*", path=...)` → список basename'ов. Если папки нет — пустой массив или просто опустить ключ.
2. **`dup_marker_files`**: `Glob` по корню `Claude-Memory/` и по `domains/*/` для паттернов `* (*).{md,yaml,json}` и `_sync_log_append*`. Передать все найденные пути (относительно корня Claude-Memory).
3. **`domains`**: уже собирается для слоя 1; те же `domain_dirs`, но в `library_layout.domains` нужны только basenames (без frontmatter) — чтобы детектить суффикс `-audit`.

Слой полностью опционален: если все три массива пусты или ключа `library_layout` нет — issues по этому слою не генерируются.

---

## Слой 1 — Ревизия аудитов источников

### Что сканировать

Список доменов определяется динамически:
- `Glob("*/", path="{LOCAL_ROOT}/domains/")` → список `domain_dirs`

Для каждого `domain_dir`:
- `Glob("*.md", path="{LOCAL_ROOT}/domains/{domain_dir}/")`

Исключить: `INDEX.md`, `_sync_log.md`, файлы с именем начинающимся на `_`.

### Обязательные поля YAML frontmatter

| Поле | Уровень |
|------|---------|
| `source` | 🔴 Обязательное |
| `audit_date` | 🔴 Обязательное |
| `trust` | 🔴 Обязательное |
| `period` | 🟡 Рекомендуемое |
| `last_updated` | 🟡 Рекомендуемое |
| `pin` | ⚪ Опциональное |

### Проверка INDEX.md

Для каждой субпапки прочитать `INDEX.md` и проверить:
- Файлы в субпапке, которых нет в INDEX.md → 🟡 «не занесён в INDEX»
- Строки INDEX.md, указывающие на несуществующий файл → 🟡 «мёртвая ссылка в INDEX»

### Формат вывода (Слой 1)

Если проблем нет:
```
### 🗂 Аудиты источников
✅ N файлов проверено — проблем не найдено
```

Если есть:
```
### 🗂 Аудиты источников
N файлов проверено, M с замечаниями:

| Файл | Проблема | Предлагаемое действие |
|------|----------|-----------------------|
| geopolitics/cfr-2024.md | нет `period` | добавить вручную или через save-to-library |
| ru-sellside/atom-2024.md | нет frontmatter | проверить файл, возможно повреждён |
| geopolitics/INDEX.md | мёртвая ссылка: cfr-2023.md | удалить строку или восстановить файл |
```

---

## Слой 2 — Ревизия прогнозов (forecasts/)

### Что сканировать

```
Glob("*.md", path="{LOCAL_ROOT}/forecasts/")
Glob("*.yaml", path="{LOCAL_ROOT}/forecasts/")
Glob("*.docx", path="{LOCAL_ROOT}/forecasts/")
```

Исключить: `INDEX.md`, файлы начинающиеся на `_`.

### 2.1 Проверка парности `*.md` ↔ `*.yaml`

Для каждого `*.md` (кроме `INDEX.md`):

- Существует ли парный `{basename}.yaml`?
  - **Если нет** → 🟡 «нет парного yaml — events-monitoring невозможен; haiku-checker пропустит». Действие: предложить создать минимальный Tier 1 yaml из frontmatter `*.md`.
  - **Если есть** → перейти к 2.2.

Для каждого `*.yaml` без парного `*.md`:
- 🔴 «orphan yaml» — потерянный файл без основного контента. Действие: восстановить `*.md` или удалить yaml.

### 2.2 Валидация yaml-схемы

Для каждого парного `*.yaml`:

| Проверка | Если не выполнено |
|----------|-------------------|
| `schema_version: 1` присутствует | 🟡 «нет schema_version — нужна миграция» |
| `type: forecast-events` | 🟡 «неверный type» |
| `forecast_ref` совпадает с именем `.md` | 🔴 «forecast_ref не соответствует имени файла» |
| `forecast.{date, horizon, domain, topic}` присутствуют | 🔴 «нет обязательного поля forecast.X» |
| `forecast.horizon` ≥ `forecast.date` | 🔴 «horizon раньше date — ошибка» |
| `reviews.interval_months` ∈ {1,3,6,12} | 🟡 «нестандартный interval_months» |
| `final_audit.due` == `forecast.horizon` | 🟡 «final_audit.due не совпадает с horizon» |
| `monitoring`, `falsifiers`, `thresholds` items имеют валидный `auto_checkable` | 🟡 «auto_checkable отсутствует — haiku не сможет триажить» |

### 2.3 Триггеры актуальности

Для прогнозов с валидным yaml. **active** — полная логика ниже; **superseded/expired** — узкий
outcome-свип (§2.3.1); **resolved** — пропуск (уже отаудирован). Всю date-арифметику делает
`check_triggers` в скрипте.

| Триггер | Условие | Уровень | Действие |
|---------|---------|---------|----------|
| **Финальный аудит** | `final_audit.due ≤ сегодня` AND `final_audit.status == pending` | 🔴 | Запустить `retrospective-forecast-audit` |
| **Финальный аудит просрочен** | `final_audit.due ≤ сегодня - 30 дней` AND `final_audit.status == pending` | 🔴 | Пометить status=expired ИЛИ запустить retro-audit |
| **Отложенный аудит** (§19) | `final_audit.status == deferred` | — | `scheduled_for` в будущем → молчать; прошёл → 🔴 `deferred_schedule_passed`; без даты → 🟡 |
| **Регулярный ревью** | `reviews.next_due ≤ сегодня` | 🟡 | Пересобрать через `forecast-confidence-applier` |
| **Регулярный ревью скоро** | `reviews.next_due ≤ сегодня + 7 дней` | 🟢 | Скоро (информационно, без действия) |
| **OK** | ничего из вышеперечисленного | 🟢 | Ждать |

### 2.3.1 Свип незафиксированных исходов + «проанализируй устаревшие» (F7-sweep)

Монитор скипает superseded/expired ради экономии — их незакрытые исходы ловит **этот
maintenance-свип**. `check_triggers` для superseded/expired проверяет резолв-точки
(`outcome_log.resolve_date` + `fca_stats`-ключи + `forecast.horizon`), которые **прошли** и
**не зафиксированы** (`actual`/`resolved = null`) → issue `outcome_uncaptured` 🟡.

**По запросу «проанализируй устаревшие прогнозы / закрой те, чьё время прошло»** — свип по всей
библиотеке (все статусы), собери отчёт:

- **close-кандидаты**: active с прошедшим горизонтом без аудита/deferred → предложить `expired`.
- **capture-кандидаты**: `outcome_uncaptured` (superseded/expired с прошедшей незаполненной точкой).
- **retro-audit-кандидаты**: горизонт разрешился, аудита нет.

**Для capture-кандидатов — ищи факт и предлагай значения (роль revise, §14.3):**
1. Для каждой незаполненной `resolve_date` сделай `web_search` факта на эту дату.
2. Предложи в отчёте `actual` (level, число) / `resolved` (event, 0|1) + `actual_source` +
   `shock_flag`. **Замороженные предсказанные** (`predicted_p`/`forecast_l1_*`/`p10_p90`) НЕ
   сочиняй — они уже в `fca_stats`/стабе прогноза (save-to-library их замораживает helper'ом).
3. **Сам forecasts НЕ пиши.** Передай предложения `save-to-library` — он замораживает из
   `fca_stats` (`freeze-outcome-log`), считает `error_pct`/`in_p10_p90` (`complete-outcome-log`)
   и пишет `outcome_log` + закрывает статус (единый писатель, D3).

Т.е. **детекция = скрипт; web_search факта + предложение = revise (для устаревших); арифметика =
скрипт; запись/закрытие = save-to-library.** Для active тот же web_search+предложение делает
forecast-monitor (F7 `outcome_capture` → `outcome_log_updates`).

### 2.4 Проверка `.docx` без `.md`-компаньона

Логика прежняя — `.docx` рядом с `.md` считается документационной копией. `.docx` без `.md` → 🟡 «нет .md-компаньона». Workflow создания компаньона см. в разделе ниже.

### 2.5 Проверка status

Для каждого yaml:
- Если `status: superseded`, проверить `superseded_by` — существует ли указанный файл? Если нет → 🔴 «битая ссылка superseded_by».
- Если `status: resolved`, проверить `final_audit.audit_file` — существует ли файл аудита? Если нет → 🟡 «нет связанного retro-audit файла».

### 2.6 Проверка INDEX.md прогнозов

Прочитать `forecasts/INDEX.md` (если существует):
- Строки таблицы → файлы существуют? мёртвая ссылка → 🟡
- Файлы в папке (и .md, и .yaml) → есть в INDEX? → 🟡 если нет

### 2.7 Workflow создания yaml для существующих `.md` (миграция)

Если пользователь подтверждает создание yaml из существующего `*.md` без yaml:

1. Прочитать `*.md` frontmatter: `forecast_date`, `horizon_date`, `review_interval_months`, `topic`, `domain`.
2. Если каких-то полей нет — спросить пользователя.
3. Сгенерировать минимальный Tier 1 yaml (см. `events-yaml-spec.md` §9):

```yaml
schema_version: 1
type: forecast-events
forecast_ref: <basename>.md
status: active

forecast:
  date: {forecast_date}
  horizon: {horizon_date}
  domain: {domain}
  topic: {topic}
  central_estimate: null  # TODO: извлечь из текста .md или запустить FCA
  confidence: null  # TODO: запустить FCA для оценки

reviews:
  interval_months: {review_interval_months}
  next_due: {форму расчёта см. ниже}
  last_completed: null
  history: []

final_audit:
  due: {horizon_date}
  status: pending
```

**Расчёт `next_due`:** найти ближайшую дату вида `forecast_date + N × interval_months` (N ≥ 1), которая ещё в будущем относительно сегодня. Если `final_audit.due ≤ сегодня` — поставить `next_due = null` (только final_audit активен).

4. Записать `Write("{LOCAL_ROOT}/forecasts/{basename}.yaml", ...)`. **Не перезаписывать `*.md`.**
5. Обновить `forecasts/INDEX.md` — добавить строку для `*.yaml`.

### 2.8 Workflow создания `.md`-компаньона для `.docx`

Логика прежняя:

1. Извлечь текст из `.docx` через bash + python-docx:
   ```bash
   pip install python-docx --break-system-packages -q
   python3 -c "
   from docx import Document
   doc = Document('/path/to/file.docx')
   for p in doc.paragraphs:
       if p.text.strip(): print(p.text)
   "
   ```
   ⚠ Таблицы Word при таком извлечении не сохраняются — отметить в `.md` где они были.

2. Уточнить метаданные у пользователя или извлечь из текста:
   `forecast_date`, `horizon_date`, `review_interval_months`, `topic`, `domain`.

3. Создать `.md` с frontmatter + извлечённым текстом. Имя: `{topic}-{forecast_date}.md` или совпадающее с `.docx` (без расширения).

4. **Сразу после создания `.md`** — предложить также создать парный `.yaml` (Слой 2.7).

5. `.docx` не удалять.

### Формат вывода (Слой 2)

```
### 📊 Прогнозы
N .md / N .yaml / K .docx файлов проверено.
Events YAML: M из N прогнозов имеют yaml файл (K без yaml — нужна миграция)

| Файл | Тема | Составлен | Горизонт | Status | Действие |
|------|------|-----------|----------|--------|----------|
| russia-2026.md | Россия 2026 | 2025-01-10 | 2026-12-31 | active | 🟡 next_due прошёл — обновить FCA |
| nato-future.md | НАТО | 2024-06-01 | 2025-12-31 | active | 🔴 horizon прошёл — финальный аудит |
| china-2027.md | Китай | 2026-03-01 | 2027-06-01 | active | 🟢 next_due 2026-09-01 |
| orphan-forecast.docx | — | — | — | — | 🟡 Нет .md-компаньона |
| old-forecast.md | (без yaml) | 2025-08-15 | 2026-08-15 | — | 🟡 Нет yaml — нужна миграция Tier 1 |
| broken.yaml | — | — | — | — | 🔴 orphan yaml (нет .md) |
```

---

## Слой 3 — Ревизия сценариев (Scenarios/)

### Что сканировать

```
Glob("*.md", path="{LOCAL_ROOT}/Scenarios/")
Glob("*.yaml", path="{LOCAL_ROOT}/Scenarios/")
```

Исключить: `INDEX.md`, файлы начинающиеся на `_`.

### 3.1 Проверка парности

Аналогично Слою 2.1: для каждого `*.md` (кроме INDEX.md) — проверить парный `*.yaml`.

### 3.2 Валидация yaml-схемы (scenario-events)

| Проверка | Если не выполнено |
|----------|-------------------|
| `schema_version: 1` | 🟡 миграция |
| `type: scenario-events` | 🟡 неверный type |
| `scenario_ref` совпадает с `.md` | 🔴 |
| `matrix.{date, horizon, domain, topic, axis_x, axis_y}` | 🔴 нет обязательного поля |
| `scenario_triggers` — массив длиной 4 (A, B, C, D) | 🟡 ожидается 4 сценария Shell |
| Сумма `probability` = 1.0 ± 0.05 | 🟡 «суммарная вероятность {sum} ≠ 1.0» |
| `final_audit.due` == `matrix.horizon` | 🟡 |

### 3.3 Триггеры актуальности

Те же что в Слое 2.3 (final_audit, reviews, overdue).

### 3.4 Workflow миграции (старые сценарные файлы → новый формат)

Если в `Scenarios/` найден файл со старым frontmatter (`type: scenario-matrix` без парного yaml):

Аналогично 2.7 — извлечь поля, сгенерировать минимальный yaml `type: scenario-events`. Часть полей (probability, leading_indicators) не извлекается из старого формата → ставится `null + # TODO`.

### Формат вывода (Слой 3)

```
### 🎯 Сценарии
N .md / M .yaml файлов проверено.
Events YAML: K из N матриц имеют yaml файл

| Файл | Тема | Составлен | Горизонт | Status | Действие |
|------|------|-----------|----------|--------|----------|
| scenario-ru-economy-2030.md | RU экономика | 2026-04-30 | 2030-12-31 | active | 🟢 next_due 2026-10-30 |
| scenario-iran-2027.md | Иран | 2025-12-15 | 2027-12-31 | active | 🟡 sum probability = 0.85 ≠ 1.0 |
```

---

## Финальный блок — Предлагаемые действия

После всех слоёв выводить сводку только если есть 🔴 или 🟡:

```
### Предлагаемые действия

🔴 Срочно:
1. `nato-future.md` — горизонт прошёл, запустить retrospective-forecast-audit
2. `geopolitics/cfr-2024.md` — нет обязательного поля `source`, исправить вручную
3. `forecasts/broken.yaml` — orphan yaml без .md, удалить или восстановить .md

🟡 Рекомендуется:
4. `russia-2026.md` — next_due прошёл, пересобрать через forecast-confidence-applier
5. `orphan-forecast.docx` — создать .md-компаньон с frontmatter + парный yaml
6. `old-forecast.md` — нет yaml, создать минимальный Tier 1 (миграция)
7. `geopolitics/INDEX.md` — мёртвая ссылка на cfr-2023.md, удалить

С чего начнём?
```

Если всё в порядке:
```
✅ Ревизия завершена — проблем не найдено.
N аудитов · M прогнозов (M с yaml) · K сценариев (K с yaml) — все в норме.
```

---

## Anti-patterns

❌ **Bash для файловых операций.** При Synology — только `Glob`/`Read`. Bash допустим только для извлечения текста из `.docx` при создании компаньона.

❌ **Изменять файлы без подтверждения.** Скилл только читает и сообщает; любые правки (включая создание yaml для миграции) — только после явного «да» от пользователя.

❌ **Угадывать отсутствующие поля frontmatter / yaml.** Нет поля → флаг в отчёт, уточнить у пользователя.

❌ **Удалять `.docx` после создания `.md`.** Docx — читабельная версия, хранится рядом с `.md`.

❌ **Удалять старые `.yaml` при миграции схемы.** Создаём новый, помечаем старый «нужна миграция», ждём подтверждения.

❌ **Генерировать файл отчёта.** Только вывод в чат.

❌ **Перезаписывать `.md` при создании парного `.yaml`.** `.md` неприкосновенен.

❌ **Помечать `expired` без подтверждения пользователя.** revise только предлагает; смену статуса делает save-to-library по подтверждению.

---

## Структура файлов скилла

- `SKILL.md` (этот файл) — оркестрация: чтение, парсинг, сборка отчёта
- `scripts/validate_library.py` — детерминированный валидатор (frontmatter,
  парность, schema, триггеры, probability sum, broken refs). Без зависимостей.
- `tests/test_validate_library.py` — 45 регрессионных проверок
- `references/transport-layer.md` — Synology mount: пути, типовые операции

Полная спецификация yaml-схемы — в `save-to-library/references/events-yaml-spec.md` (читать при необходимости валидации).

**Правило:** ни одна валидация и ни один трудовой расчёт дат не выполняется LLM
вручную — всё через `validate_library.py`. LLM делает только I/O и сборку
финального markdown-отчёта.
