# Events YAML — спецификация v1

Единый источник истины формата `*.yaml` файлов, парных к `*.md` прогнозам и сценариям. Используется:

- `save-to-library` — валидация и запись
- `revise-memory-remote` — проверка целостности и миграция
- `forecast-confidence-applier`, `hypothesis-stress-tester`, `scenario-builder` — генерация технических блоков для save-to-library
- `haiku-forecast-checker` (планируется) — еженедельная автоматическая проверка событий

**Принципы:**

1. **Co-location.** `*.md` и `*.yaml` хранятся в одной папке с одинаковым базовым именем.
   Пример: `forecasts/ru-rates-2026-2026-04-30.md` ↔ `forecasts/ru-rates-2026-2026-04-30.yaml`
2. **Машиночитаемость превыше эстетики.** YAML парсится автоматически haiku — никаких вольностей с форматом.
3. **schema_version: 1** во всех новых файлах. Дублируется во frontmatter `*.md`.
4. **TODO-маркер** для не-обязательных, но не извлечённых полей: `field: null  # TODO: <причина>`.
   Обязательные поля (см. таблицы ниже) НЕ могут быть `null`.
5. **Нет полей-плейсхолдеров.** Если поле не нужно для конкретного типа прогноза — оно не пишется.

---

## 1. Имена и slug

### 1.1 Имена файлов

| Тип | Папка | Имя файла |
|-----|-------|-----------|
| Прогноз | `forecasts/` | `{topic-slug}-{forecast_date}.md` + `.yaml` |
| Сценарий | `scenarios/` | `scenario-{topic-slug}-{date_created}.md` + `.yaml` |

`forecast_date`/`date_created` в формате `YYYY-MM-DD`. Пример: `ru-rates-2026-2026-04-30.md`.

### 1.2 Правило slug (для `topic` и для `id` внутри yaml)

- lowercase, символы `[a-z0-9-]`
- кириллица → ISO 9 транслит (например, `ставка → stavka`, `рубль → rubl`)
- стоп-слова отсеиваются: `и в на для что ли будет может с по от из о the a of to is at`
- первые **3 значимых слова**, разделитель `-`
- максимум **30 символов** (обрезка по последнему дефису, не посередине слова)
- внутри одного yaml-файла `id` уникальны; коллизия → суффикс `-2`, `-3`, …

**Примеры:**

| Исходный текст | Slug |
|----------------|------|
| Проверить рост ставки ЦБ выше 21% | `rost-stavki-cb` |
| OPEC announces production cut | `opec-production-cut` |
| Инфляция в РФ выше 7% к концу 2026 | `inflyatsiya-rf-7pct` |
| Brent below $50/bbl | `brent-50-bbl` |

---

## 2. Tier 1 — минимальная схема (любой прогноз)

```yaml
schema_version: 1
type: forecast-events           # forecast-events | scenario-events
forecast_ref: <basename>.md     # имя парного .md в той же папке
status: active                  # active | resolved | superseded | expired

forecast:
  date: YYYY-MM-DD              # = forecast_date в .md frontmatter
  horizon: YYYY-MM-DD           # = horizon_date; ОБЯЗАТЕЛЬНО (не null)
  domain: <domain>              # geopolitics | ru-macro | ru-sellside | global-banks | tech-ceo
  topic: <topic-slug>           # = topic в .md frontmatter
  central_estimate: "<text>"    # формат «{переменная}: {значение или диапазон} к {дата}», ≤200 симв.
  confidence: 0.00              # 0.0–1.0, формула FCA или null+TODO

reviews:
  interval_months: <N>          # 1 | 3 | 6 | 12
  next_due: YYYY-MM-DD          # haiku сравнивает с today; первый = forecast.date + interval_months
  last_completed: null          # YYYY-MM-DD после первого ревью
  history: []                   # [{date: ..., status: done|skipped, notes: "..."}]

final_audit:
  due: YYYY-MM-DD               # = forecast.horizon
  status: pending               # pending | done | overdue | deferred (§19)
  # scheduled_for: YYYY-MM-DD   # обязательно при status: deferred — на когда отложен ретро-аудит
```

### 2.1 Поля Tier 1 — обязательность

| Поле | Обязательное | Дефолт |
|------|--------------|--------|
| `schema_version` | ✓ | `1` |
| `type` | ✓ | — |
| `forecast_ref` | ✓ | — |
| `status` | ✓ | `active` |
| `forecast.date` | ✓ | — |
| `forecast.horizon` | ✓ | НЕТ — спросить пользователя |
| `forecast.domain` | ✓ | — |
| `forecast.topic` | ✓ | — |
| `forecast.central_estimate` | ✓ | `null + # TODO` если не FCA |
| `forecast.confidence` | рекомендуется | `null + # TODO` если не FCA |
| `reviews.interval_months` | ✓ | — |
| `reviews.next_due` | ✓ | вычисляется |
| `final_audit.due` | ✓ | = `forecast.horizon` |

### 2.2 `confidence` — формула FCA

```
confidence = 0.4 + 0.4 × (доля HIGH-источников среди собранных) − 0.2 × (есть Asymmetry warning ? 1 : 0)
```

Округление до 2 знаков. Минимум 0.0, максимум 1.0.

**Примеры:**
- 5 источников, 3 HIGH, нет asymmetry → `0.4 + 0.4×0.6 − 0 = 0.64`
- 4 источника, 0 HIGH, asymmetry warning → `0.4 + 0 − 0.2 = 0.20`
- 6 источников, 6 HIGH, нет asymmetry → `0.4 + 0.4 − 0 = 0.80`

### 2.3 `central_estimate` — формат

Структурированный шаблон: `«{переменная}: {значение или диапазон} к {дата}»`. Машиночитаемый для haiku.

**Примеры:**
- `"Ключевая ставка ЦБ РФ: 14.5% к 2026-12-31"`
- `"Война РФ–НАТО: вероятность <15% к 2030-12-31"`
- `"Brent: $70–80/bbl к 2026-12-31"`
- `"Korean-style armistice по Украине: к 2027-Q4"` (если число неприменимо — текстовый исход + дата)

Для качественных прогнозов без числа допустимо: `"<исход>: <вероятность>% к <дата>"`.

---

## 3. Tier 2 — расширение для прогнозов со стресс-тестом

Поверх Tier 1 добавляются секции из `hypothesis-stress-tester`:

```yaml
monitoring:
  - id: <slug>
    description: "<что проверяем>"
    source: "<URL или издание>"   # опционально; если из HST — поле опускается
    threshold: "<конкретный порог>"
    check_date: YYYY-MM-DD        # haiku сравнивает с today
    impact: invalidates           # invalidates | supports | mixed
    severity: critical            # critical | high | medium
    auto_checkable: true          # true → haiku web_search; false → требует суждения

assumptions:
  - id: <slug>
    text: "<допущение>"
    robustness: MEDIUM            # HIGH | MEDIUM | LOW
    sensitivity: critical         # critical | moderate | low
    auto_checkable: false         # ВСЕГДА false (assumptions требуют интерпретации)

thresholds:                       # из Sensitivity sweep, только если "флипает: Да"
  - id: <slug>
    variable: "<переменная>"
    condition: "<при каком значении флипает>"
    flips_to: "<scenario_id или текстовое описание альтернативы>"
    auto_checkable: true          # обычно true (численная переменная)

deadlines:                        # из Reversibility check
  - id: <slug>
    date: YYYY-MM-DD
    description: "<что происходит>"
    action: "<что делать при наступлении>"
    auto_checkable: true          # дата всегда проверяется

falsifiers:                       # из Pre-mortem, топ-3 причины провала
  - id: <slug>
    description: "<событие фальсификации>"
    would_resolve: true           # true → прогноз закрывается (status: resolved); false → meaningfully weakens
    auto_checkable: true

agents:                           # из Red team
  - id: <slug>
    agent: "<кто>"
    action: "<что делает>"
    window: "YYYY-MM-DD/YYYY-MM-DD"
    impact: invalidates
    severity: high
    auto_checkable: false         # ВСЕГДА false (agent intent требует суждения)
```

### 3.1 Когда Tier 2 включается

`save-to-library` добавляет Tier 2 при наличии хотя бы одной из секций в исходном `.md`:

- `## Что проверить в первую очередь` → `monitoring`
- `## Pre-mortem` → `falsifiers`
- `## KAC` (или `## Key Assumptions Check`) → `assumptions`
- `## Sensitivity sweep` → `thresholds` (только пункты «флипает: Да»)
- `## Reversibility check` → `deadlines` (если есть точка невозврата)
- `## Red team` → `agents`
- `## Counterfactual test` → `assumptions` (необходимые предусловия → допущения)

Поиск секций — точный match названия (case-insensitive) на верхнем уровне Markdown (`##`).

### 3.2 `auto_checkable` — правила

| Поле | auto_checkable | Логика |
|------|----------------|--------|
| `monitoring` | true / false | true если есть числовой `threshold` или конкретная дата события |
| `assumptions` | **всегда false** | требует интерпретации |
| `thresholds` | обычно true | численная переменная — true; качественная — false |
| `deadlines` | **всегда true** | дата всегда автоматически проверяется |
| `falsifiers` | true / false | true если есть числовой порог; false если требует интерпретации |
| `agents` | **всегда false** | agent intent / capability — требует суждения |

---

## 4. Scenarios — отдельная схема (scenarios/)

```yaml
schema_version: 1
type: scenario-events
scenario_ref: <basename>.md
status: active                     # active | superseded | expired

matrix:
  date: YYYY-MM-DD                 # дата построения
  horizon: YYYY-MM-DD              # горизонт сценариев
  domain: <domain>
  topic: <topic-slug>
  axis_x: "<переменная X: полюс A vs полюс B>"
  axis_y: "<переменная Y: полюс C vs полюс D>"

scenario_triggers:
  - scenario_id: A                 # A | B | C | D
    label: "<имя сценария>"
    probability: 0.25              # default 0.25 (Shell-равновероятность); может быть переопределено пользователем
    enabling_conditions:
      - "<условие 1>"
      - "<условие 2>"
    leading_indicators:
      - id: <slug>
        description: "<что наблюдать>"
        threshold: "<порог если есть>"
        check_date: YYYY-MM-DD     # опционально, для haiku
        auto_checkable: true       # true если численный порог; false если качественный

reviews:
  interval_months: <N>
  next_due: YYYY-MM-DD
  last_completed: null
  history: []

final_audit:
  due: YYYY-MM-DD                  # = matrix.horizon
  status: pending
```

### 4.1 Отличия от Tier 1/2

- Нет `forecast.central_estimate` (4 равновероятных сценария — нет одного)
- Нет `forecast.confidence` (метод Shell не даёт probability одному сценарию)
- Нет Tier 2 секций по умолчанию (стресс-тест запускается на отдельных сценариях, не на матрице)
- Триаж по хрупкости из scenario-builder Шаг 4 — НЕ сохраняется в этот yaml; если пользователь делает stress-test одного сценария → он сохраняется как отдельный forecast в `forecasts/` со ссылкой на матрицу в `central_estimate`.

---

## 5. Блок `conditional_on_scenarios` (Tier 1/Tier 2)

Опциональный блок в forecast YAML. Связывает marginal-прогноз с матрицей сценариев из `Claude-Memory/scenarios/`. Используется `portfolio-scenario-stress` (читает `by_scenario` напрямую), `macro-forecast-chain` (выгружает Layer 2 в `macro-scenarios-{date}.yaml`), `retrospective-forecast-audit` Phase 6 (per-scenario audit через `sources_used`).

**Двухслойная архитектура (см. `HANDOFF-claude-code-phased.md` §1.3):**

- `forecast.central_estimate` (Tier 1) — **Layer 1 marginal**, прямой trust-weighted FCA, scenarios игнорируются. Используется для портфельной EV и weekly-review.
- `conditional_on_scenarios.marginal.values` — **Layer 2 marginal**, probability-weighted aggregation от `by_scenario`. Диагностика, не основа решений.

### 5.1 Структура

```yaml
conditional_on_scenarios:
  source_matrix: "scenarios/{scenario-id}.yaml"   # SSOT для весов (без префикса Claude-Memory/)
  scenario_id_format: short                        # короткий формат "A" вместо "Sc-A" (D5)
  unit: "%"                                        # один на блок: %, USD, RUB, USD/bbl, и т.д.

  by_scenario:
    A:
      values:
        "{horizon}": { central: <number>, range: [<lo>, <hi>] }
      provenance: inferred_from_content            # канон FCA-3 (6 значений) — см. §5.2.1
      sources_used:                                # объекты с camp_weight + reasoning (D8); legacy: список строк id
        - source_id: <source_id>
          camp_weight: 1.0                         # доля «голоса» источника, отнесённая к этому сценарию (0..1)
          reasoning: "1–2 предложения почему этот источник классифицирован к данному сценарию"
      upstream_used:                               # ТОЛЬКО при provenance: derived_from_upstream (§5.2.1);
        - factor: brent                            #   опционален при остальных provenance
          value: 62
          unit: USD/bbl                            # опц.
          source_file: forecasts/brent-oil-price-2026-05-11.yaml   # опц.
      coverage_quality: HIGH                       # HIGH | MEDIUM | LOW | DERIVED
    B: { … }
    C: { … }
    D: { … }

  marginal:
    method: linear                                 # linear | nonlinear | axis_dependent | indifferent
    modal_scenario_id: none                        # A | B | C | D | none (равные веса)
    values:
      "{horizon}": { central: <number>, range: [<lo>, <hi>] }
    aggregation_formula: "weighted_mean"

coherence_diagnostic:
  layer1_marginal: <number>                        # из forecast.central_estimate (распарсено)
  layer2_marginal: <number>                        # из conditional_on_scenarios.marginal.values
  divergence_pct: <number>                         # |L1 − L2| / |L1| × 100
  severity: LOW                                    # LOW <5%, MEDIUM 5–15%, HIGH >15%
  warning: null                                    # текст при severity != LOW; иначе null
```

### 5.2 Семантика полей

| Поле | Назначение |
|------|------------|
| `source_matrix` | Путь к scenario YAML; единственный источник весов. Веса в forecast YAML не дублируются. |
| `scenario_id_format: short` | Маркер D5: `A`/`B`/`C`/`D`, не `Sc-A`. Старые файлы мигрируются. |
| `unit` | Один на весь блок. Допустимо `%`, `USD`, `RUB`, `USD/bbl`, `bps`, `index`. |
| `by_scenario.{X}.values."{horizon}"` | `{central, range}` — числа, не строки. Один или несколько горизонтов. |
| `by_scenario.{X}.provenance` | Происхождение значения — канонический набор из **6** значений, см. §5.2.1. |
| `by_scenario.{X}.sources_used` | Список объектов `{source_id, camp_weight, reasoning}` (D8) — каждый источник с долей голоса в этом сценарии и кратким обоснованием. **Legacy-формат:** просто список строк id (тогда camp_weight=1.0 implicit, reasoning отсутствует). При `derived_from_marginal` / `derived_from_upstream` — допустимо `[]`. |
| `by_scenario.{X}.upstream_used` | Список объектов `{factor, value, unit?, source_file?}` — из каких upstream-макрофакторов выведено значение этого сценария. **Обязателен и непуст** при `provenance: derived_from_upstream`; при остальных provenance — опционален (даёт traceability). |
| `by_scenario.{X}.coverage_quality` | `HIGH` ≥3 source при ≥2 HIGH-trust; `MEDIUM` 2 source; `LOW` 1 source; `DERIVED` если `provenance: derived_from_marginal`. |
| `marginal.method` | Как `aggregate_marginal()` сворачивает 4 сценария: `linear` (probability-weighted mean), `nonlinear` (модальный + note про tail), `modal` (modal-сценарий доминирует — для unequal weights), `axis_dependent` (диагностический тег: фактор монотонно зависит от одной оси, индифферентен к другой; `aggregation_formula: weighted_mean`; необязательная аннотация `dominant_axis: x\|y`; математически эквивалентен `linear`), `indifferent` (значение одинаково во всех 4 сценариях). |
| `marginal.modal_scenario_id` | `argmax(weights)` если `max(weights) > 0.30`; иначе `none`. SSOT правила — `scenario-yaml-spec.md` §3.4. При equal weights 0.25 — всегда `none`. |
| `coherence_diagnostic.severity` | LOW <5%, MEDIUM 5–15%, HIGH >15% — пороги divergence Layer 1 vs Layer 2. |
| `coherence_diagnostic.warning` | Текст при severity != LOW: причина (asymmetric coverage, dominant HIGH-trust source, unequal weights). |

### 5.2.1 Канон provenance (FCA-3, 2026-08-03)

Легальный набор `by_scenario.{X}.provenance` — ровно 6 значений:

| Значение | Семантика | Требования к спутникам |
|---|---|---|
| `native_fca` | Прямые источники в этом сценарии (полноценный FCA) | `sources_used` непустой список объектов |
| `single_native` | Один источник | `sources_used` непустой (1 объект) |
| `inferred_from_content` | D8 — динамическая атрибуция источников по контенту (FCA Шаг 1.5B) | `sources_used` непустой |
| `derived_from_marginal` | Layer 2 marginal посчитан из других сценариев (probability-weighted) | `sources_used` может быть `[]`; `upstream_used` не требуется |
| `derived_from_upstream` | Значение выведено из **других макрофакторов** (Brent → USDRUB; CPI → ставка ЦБ) | `upstream_used` **обязан** быть непустым; `sources_used` может быть `[]` |
| `derived_from_geopolitics_translation` | Legacy: перевод качественной geopolitics-оси в фактор (macro-forecast-chain Шаг 5.x) | как `derived_from_upstream`, но без обязательного `upstream_used` (старые файлы) |

**Маппинг легаси-имён** (стихийные варианты из живых файлов 2026-05-11; при миграции — 1:1 переименование):
`source_native` → `single_native`; `inferred_from_cpi_floor` / `inferred_from_upstream_dependency` / `structural_derivation` → `derived_from_upstream`.

Валидация: `validate-forecast-events` (save-to-library) блокирует значения вне канона; кросс-правила provenance ↔ `sources_used`/`upstream_used` — warning в обычном режиме, blocking в strict-режиме (`{"_strict": true}` в payload, с подчёркиванием — включает FCA перед сохранением нового артефакта, см. FCA SKILL Шаг 6).

### 5.3 Инварианты

- **Все 4 сценария обязательны** в `by_scenario`, даже при `method: nonlinear`. При отсутствии native FCA для конкретного сценария → `provenance: derived_from_marginal`, `coverage_quality: DERIVED`.
- **`axis_dependent` инвариант**: сценарии с одинаковым состоянием доминантной оси имеют равное значение фактора. `aggregation_formula` = `weighted_mean`. Нет `_todo`. При наличии `dominant_axis: x|y` — аннотация, которую скрипт не заполняет автоматически (заполнить вручную).
- **Веса не дублируются** в forecast YAML. Резолвятся через `source_matrix` (D7 lazy aggregation).
- **Числа, не строки**: `central: 14.5`, не `central: "14.5%"`. Юнит выносится в `unit`. Парсинг `"13.5%"` → `13.5` + `unit: "%"` — задача миграционного скрипта.
- **`marginal.values` пересчитывается детерминированно** функцией `aggregate_marginal(by_scenario, weights, horizon, method)` (Phase 2). Правило `modal_scenario_id` — единое для трёх документов (events/scenario/migrate spec): `argmax(weights)` если `max > 0.30`, иначе `none`. При `weights = [0.25, 0.25, 0.25, 0.25]` → `modal_scenario_id: none`.
- **`unit` един** для `by_scenario`, `marginal`, и `coherence_diagnostic`. Смена юнита по сценариям не допускается.
- **Tier 1 без conditional (Type 2 без матрицы)**: если у прогноза нет сценарной матрицы (например, чисто technical forecast), блок отсутствует — это допустимо. `coherence_diagnostic.warning: "no conditional_on_scenarios block"`, `severity: LOW`.

### 5.5 Type 1 — Isolated forecasts

Прогнозы, которые **не связаны** ни с одной scenario matrix и не должны иметь блок `conditional_on_scenarios`. Используется когда:

- Бинарное событие на дату (например, `iran-us-may-deal-2026-04-30`).
- Прогноз другого домена, не входящий в портфельную макро-цепочку (например, `china-taiwan-forecast`).
- Long-horizon вне текущей scenario matrix (например, `russia-europe-war-2030`).

**Схема:**

```yaml
forecast:
  central_estimate: "..."
  confidence: 0.40
  domain: ru-macro

isolated: true
isolated_reason: "Single binary event без сценарной декомпозиции"

# НЕТ блока conditional_on_scenarios
# НЕТ блока coherence_diagnostic

monitoring: [...]
assumptions: [...]
falsifiers: [...]
```

**Правила:**

- `isolated: true` — boolean, обязательно если `conditional_on_scenarios` отсутствует И прогноз не Tier 0.
- `isolated_reason` — строка, ≤200 символов, объяснение причины (для retrospective audit).
- `coherence_diagnostic` НЕ пишется — нечему сверяться.
- В `portfolio-scenario-stress` Type 1 прогнозы не участвуют (нет `by_scenario`).
- `forecast-monitor` отслеживает только `monitoring`/`falsifiers`, без сценарной геометрии.
- Migration script (`migrate_to_conditional.py`): forecast без `geopolitics_translation` → `isolated: true` с `isolated_reason: "auto: no scenario translation block found"`. **Не создавать пустой `conditional_on_scenarios`**.

**Inventory (по runbook):** `iran-us-may-deal-2026-04-30`, `china-taiwan-forecast`, `russia-europe-war-2030`, `ukraine-postwar-forecast`, `ukraine-russia-*` — Type 1.

### 5.4 Пример (linear, equal weights)

```yaml
conditional_on_scenarios:
  source_matrix: "scenarios/scenario-geopolitics-ru-west-2026-05-04.yaml"
  scenario_id_format: short
  unit: "%"
  by_scenario:
    A:
      values:
        "2026-12-31": { central: 10.5, range: [9.0, 12.0] }
      provenance: derived_from_marginal
      sources_used: []
      coverage_quality: DERIVED
    B:
      values:
        "2026-12-31": { central: 12.5, range: [11.0, 14.0] }
      provenance: native_fca
      sources_used: [bks-2025-2026, sber-cib-2026]
      coverage_quality: MEDIUM
    C:
      values:
        "2026-12-31": { central: 11.5, range: [10.0, 13.0] }
      provenance: single_native
      sources_used: [vtb-research-2026]
      coverage_quality: LOW
    D:
      values:
        "2026-12-31": { central: 13.5, range: [12.0, 15.0] }
      provenance: native_fca
      sources_used: [bks-2025-2026, alfa-research-2026, sber-cib-2026, vtb-research-2026, raiffeisen-2026]
      coverage_quality: HIGH
  marginal:
    method: linear
    modal_scenario_id: none
    values:
      "2026-12-31": { central: 12.0, range: [9.0, 15.0] }
    aggregation_formula: "weighted_mean"

coherence_diagnostic:
  layer1_marginal: 12.7
  layer2_marginal: 12.0
  divergence_pct: 5.5
  severity: MEDIUM
  warning: "Layer 1 marginal (12.7) расходится с Layer 2 marginal (12.0) на 5.5%. Вероятно, dominant HIGH-trust БКС в Layer 1 vs symmetric Layer 2 aggregation."
```

### 5.6 Контракт единиц фактора (SSOT, MFC-4)

Определяет, в **каких единицах** задаётся «движение фактора», на которое умножаются `factor_betas`.
Используется тремя скиллами: `macro-forecast-chain` (producer), `portfolio-integrated-view`
(consumer, конвертация уровень→движение), `portfolio-scenario-stress` (OLS-регрессия).

| Фактор | Единица движения | Перевод уровень → движение |
|---|---|---|
| `brent`, `usdrub`, `cnyrub`, `xauusd` | **% отклонение от `baseline_spot`** | `(level − spot) / spot × 100` |
| `cbr_rate` | **п.п. (процентные пункты)** | `target_pct − baseline_cbr_rate_pct` |
| `sanctions`, `geopol` | индекс эскалации `[-1..+1]` (`+1` ужесточение, `−1` смягчение) | `unit: intensity` → уровень уже есть движение; при качественной оценке числового уровня нет → в L1 не участвуют |

**Поле `unit` в macro-marginal YAML** (после парсинга `compute_marginal_move.py`):

| `unit` | Ключ в `baseline_spot` | Тип конвертации |
|---|---|---|
| `usd_per_bbl` | `brent_usd` | `pct_from_spot` |
| `rub_per_usd` | `usdrub` | `pct_from_spot` |
| `rub_per_cny` | `cnyrub` | `pct_from_spot` |
| `usd_per_troy_oz` | `xauusd_usd` | `pct_from_spot` |
| `rate_pct` | `cbr_rate_pct` | `pp_diff` |
| `intensity` | — (спот не нужен) | движение = сам уровень: интенсивность задана относительно текущего состояния |

**Единицы `factor_betas` (контракт P0-1, 2026-08-03).** Симметрично таблице выше:
**β — процентные пункты цены на ОДНУ единицу движения фактора**. Для
`sanctions`/`geopol` единица — интенсивность `1.0`, поэтому политическая бета
акции-банка ≈ **−35**, а не −0.35 (у облигации она законно мала:
`−duration × Δspread_бп / 100`). Долевая запись отличается ×100 и молча зануляет
политический канал — `compute_per_position.py` отказывается считать
(`--political-scale-check`, default `error`). Полное описание и калибровка —
`portfolio-scenario-stress/references/sector-sensitivities.md` → «Контракт единиц».

**Горизонтный путь политических дилов (P0-2).** `sanctions`/`geopol` задаются
**на каждый горизонт** — `{h6: −0.3, h12: −0.6, h24: −0.9}` либо
`{level_l1_<год>: …, unit: intensity}`. Один скаляр на все горизонты означает
«разрядка через полгода = разрядка через два года» и помечается warning'ом.

**Почему против `baseline_spot`, а не против текущего спота:**
L2-факторы в stress — «% отклонение от `baseline_spot`». Чтобы `coherence_gap = |L1 − L2|`
имел смысл, L1 должен считаться по **той же базе**. Поэтому уровень→движение переводит
`aggregate_positions` (он же грузит stress с `baseline_spot`), а не producer.

**Пример (brent):** macro-marginal даёт `level_l1_2026 = 68.0`, stress `baseline_spot.brent_usd = 94.11`
→ движение L1 `= (68 − 94.11) / 94.11 × 100 = −27.74%` → `β_brent × (−27.74)` на позицию.

---

## 6. Сценарная атрибуция источников — динамическая (D8)

> **D8 (2026-05-10):** блок `implicit_geopolitical_scenarios` в audit frontmatter **отозван**. Сценарная атрибуция источника не хранится в profile, потому что:
> - Сценарии — эфемерные конструкты (горизонт 6–18 мес), источники — стабильные сущности (горизонт лет). При смене сценарной оси все profile стали бы stale.
> - Worldview источника эволюционирует (BCS-2024 ≠ BCS-2026); static frontmatter этого не отражает.
> - Скиллы должны оставаться сценарно-независимыми (см. CLAUDE.md «Принцип сценарной независимости»).

### 6.1 Где живёт атрибуция теперь

В момент построения **Type 2 conditional FCA** скилл `forecast-confidence-applier` (Шаг 1.5B — branched развилка от Шага 1.5):

1. Загружает scenario YAML из `source_matrix` → список `scenario_id` с trigger conditions.
2. Для каждого источника читает его forecast snippet + assumptions, классифицирует к одному (или двум) `scenario_id`.
3. Записывает результат **inline в forecast YAML**: `by_scenario.{X}.sources_used = [{source_id, camp_weight, reasoning}]`, `provenance: inferred_from_content`.

Это даёт трассируемость без stale frontmatter — атрибуция всегда актуальна на момент FCA, и видна вместе с forecast YAML.

### 6.2 Опциональное поле в profile: `methodology_notes`

Если хочется зафиксировать в profile **методологическую характеристику** источника (без привязки к конкретным `scenario_id`) — используется поле `methodology_notes:` (свободный текст) в audit frontmatter. См. `audit-frontmatter-schema.md`. Пример:

```yaml
methodology_notes: |
  RU sell-side, регулярные базовые сценарии, склонны к консерватизму.
  Не специализируются на геополитике — взгляд на санкции вторичен.
```

Это **не диктует** атрибуцию — LLM при FCA Шаг 1.5B ориентируется на это как на подсказку, но решение принимает по контенту конкретного прогноза.

### 6.3 Backward compat (legacy `implicit_geopolitical_scenarios`)

Если в profile встречается старый блок (формат отозванного D4) — он **игнорируется** новыми скиллами. Удалять при первой ревизии profile, но не критично.

---

## 7. Поле `superseded_by`

Появляется только при `status: superseded`. Содержит **basename** нового файла (без расширения):

```yaml
status: superseded
superseded_by: ru-rates-2026-2026-07-15
```

`forecasts/` и `scenarios/` — раздельные базы, ссылки внутри одной папки.

---

## 8. Полный пример Tier 1

`forecasts/ru-rates-2026-2026-04-30.yaml`:

```yaml
schema_version: 1
type: forecast-events
forecast_ref: ru-rates-2026-2026-04-30.md
status: active

forecast:
  date: 2026-04-30
  horizon: 2026-12-31
  domain: ru-macro
  topic: ru-rates-2026
  central_estimate: "Ключевая ставка ЦБ РФ: 14.5% к 2026-12-31"
  confidence: 0.64

reviews:
  interval_months: 3
  next_due: 2026-07-30
  last_completed: null
  history: []

final_audit:
  due: 2026-12-31
  status: pending
```

---

## 9. Полный пример Tier 2

`forecasts/ukraine-russia-stress-2026-04-28.yaml`:

```yaml
schema_version: 1
type: forecast-events
forecast_ref: ukraine-russia-stress-2026-04-28.md
status: active

forecast:
  date: 2026-04-28
  horizon: 2027-12-31
  domain: geopolitics
  topic: ukraine-russia-2026
  central_estimate: "Korean-style armistice по Украине: к 2027-Q4"
  confidence: 0.55

reviews:
  interval_months: 3
  next_due: 2026-07-28
  last_completed: null
  history: []

final_audit:
  due: 2027-12-31
  status: pending

monitoring:
  - id: brent-fnb-trigger
    description: "Brent ниже $50 одновременно с истощением ФНБ"
    source: "https://www.eia.gov/dnav/pet/pet_pri_spt_s1_d.htm"
    threshold: "Brent < $50/bbl AND ФНБ ликвидная часть < 3 трлн ₽"
    check_date: 2026-10-01
    impact: invalidates
    severity: critical
    auto_checkable: true

  - id: kongress-vybory-2026
    description: "Результаты выборов в Конгресс США 2026-11-03"
    threshold: "Изменение баланса в Сенате/Палате"
    check_date: 2026-11-04
    impact: mixed
    severity: high
    auto_checkable: true

assumptions:
  - id: zapad-ne-eskaliruet
    text: "Запад не идёт на прямую военную интервенцию в течение 18 мес"
    robustness: MEDIUM
    sensitivity: critical
    auto_checkable: false

thresholds:
  - id: nato-troop-deployment
    variable: "Численность NATO Multinational Corps в Балтии"
    condition: "Превышает 50 000 на постоянной основе"
    flips_to: "scenario_escalation"
    auto_checkable: true

deadlines:
  - id: kongress-vybory-deadline
    date: 2026-11-03
    description: "Выборы в Конгресс США"
    action: "Запустить FCA на тему ukraine-russia-2026 для пересборки консенсуса"
    auto_checkable: true

falsifiers:
  - id: full-russian-mobilization
    description: "Объявление полной мобилизации в РФ"
    would_resolve: true
    auto_checkable: true

  - id: nato-article-5
    description: "Активация Статьи 5 НАТО по любому поводу"
    would_resolve: true
    auto_checkable: true

  - id: kim-trump-deal
    description: "Прямой договор Трамп–Путин с territorial concessions"
    would_resolve: true
    auto_checkable: false

agents:
  - id: china-mediator
    agent: "КНР"
    action: "Выступить медиатором с сильным ультиматумом обеим сторонам"
    window: "2026-09-01/2027-03-31"
    impact: mixed
    severity: high
    auto_checkable: false
```

---

## 10. Полный пример Scenarios

`scenarios/scenario-ru-economy-2030-2026-04-30.yaml`:

```yaml
schema_version: 1
type: scenario-events
scenario_ref: scenario-ru-economy-2030-2026-04-30.md
status: active

matrix:
  date: 2026-04-30
  horizon: 2030-12-31
  domain: ru-macro
  topic: ru-economy-2030
  axis_x: "Геополитика: разворот к Западу vs продолжение конфронтации"
  axis_y: "Внутренняя экономика: реформы vs мобилизационная модель"

scenario_triggers:
  - scenario_id: A
    label: "Перезагрузка"
    probability: 0.25
    enabling_conditions:
      - "Снятие части санкций"
      - "Пакет институциональных реформ"
    leading_indicators:
      - id: snyatie-sanktsiy
        description: "Снятие минимум 30% санкций ЕС"
        threshold: "≥30% санкций EU отменены"
        check_date: 2027-12-31
        auto_checkable: true
      - id: cb-nezavisimost
        description: "Восстановление операционной независимости ЦБ"
        threshold: "Прекращение давления Госдумы на КС"
        auto_checkable: false

  - scenario_id: B
    label: "Замороженная конфронтация"
    probability: 0.35
    enabling_conditions:
      - "Армистис без снятия санкций"
      - "Точечные реформы"
    leading_indicators:
      - id: armistis-podpisan
        description: "Подписание соглашения о прекращении огня"
        threshold: "Официальный документ с обеими сторонами"
        check_date: 2027-06-30
        auto_checkable: true

  - scenario_id: C
    label: "Осада с реформами"
    probability: 0.20
    enabling_conditions:
      - "Усиление санкций"
      - "Внутренняя либерализация рынка"
    leading_indicators:
      - id: ekonom-libertarian-package
        description: "Пакет либерализации рынка труда и капитала"
        auto_checkable: false

  - scenario_id: D
    label: "Военная экономика"
    probability: 0.20
    enabling_conditions:
      - "Эскалация конфликта"
      - "Мобилизационная модель закреплена"
    leading_indicators:
      - id: oboronnye-rashody
        description: "Доля военных расходов в ВВП"
        threshold: "> 7% ВВП на постоянной основе"
        check_date: 2027-12-31
        auto_checkable: true

reviews:
  interval_months: 6
  next_due: 2026-10-30
  last_completed: null
  history: []

final_audit:
  due: 2030-12-31
  status: pending
```

---

## 11. Миграция существующих файлов (revise-memory-remote)

При обнаружении `*.md` без парного `*.yaml`:

1. Извлечь frontmatter `*.md`: `forecast_date`, `horizon_date`, `review_interval_months`, `topic`, `domain`.
2. Сгенерировать минимальный Tier 1 yaml:
   - `schema_version: 1`
   - `type: forecast-events`
   - `forecast_ref: <basename>.md`
   - `status: active` (или другое — спросить пользователя если непонятно)
   - `forecast.{date, horizon, domain, topic}` — из frontmatter
   - `forecast.central_estimate: null  # TODO: извлечь из текста .md`
   - `forecast.confidence: null  # TODO: запустить FCA`
   - `reviews.interval_months` — из frontmatter
   - `reviews.next_due` — вычислить от `forecast_date + interval_months`, пропустить уже прошедшие
   - `final_audit.due = horizon_date`
3. Сохранить как новый файл, **не перезаписывая** `*.md`.
4. Обновить `forecasts/INDEX.md`: добавить строку для `*.yaml`.

**Если schema_version в `.yaml` отсутствует или меньше текущей** — пометить «нужна миграция», предложить обновление, не выполнять автоматически.

---

## 12. Catalyst kinds в weekly-review (METH-1, 2026-05-13)

Catalyst tree в `weekly-review-stock-*.yaml` и `weekly-review-bond-*.yaml`
использует **kind-aware** схему: каждый catalyst декларирует `kind: binary`
или `kind: quantitative`. Это определяет, какие поля обязательны и какую
формулу применяет агрегатор.

Каноническая методология и формулы — `docs/investment/portfolio/methodology.md` раздел 1. Здесь —
только YAML-структура.

### 12.1 `kind: binary` — дискретное событие

```yaml
catalyst:
  - id: dividend_record_date_2025
    kind: binary
    trigger: "Otsechka reestra ~20 iyulya 2026 ..."
    date_window: "2026-07"
    in_horizon: true
    p: 0.88                              # обязательно, ∈ (0, 0.95]
    upside_pct: 3                        # обязательно
    upside_ci_pct: [0, 5]                # обязательно
    source: "https://..."
    source_quality: HIGH
    macro_dependency: null               # null = scenario-independent
    # active_scenarios: ["A"]            # опц., альтернатива macro_dependency как list

  - id: sanctions_easing_arctic_spg2
    kind: binary
    p: 0.65
    upside_pct: 45
    upside_ci_pct: [20, 70]
    active_scenarios: ["A"]              # binary, возможно только в Sc-A
    source_quality: MEDIUM
```

Поля:
- `p` (required): вероятность события. Range `(0, 0.95]`.
- `upside_pct` (required): размер эффекта.
- `upside_ci_pct: [lo, hi]` (required): CI оценки размера.
- `active_scenarios: [scenario_id, ...]` (optional): сценарная привязка.
  Если опущено и `macro_dependency = null` — событие scenario-independent
  (доступно во всех сценариях с весом 1.0).
- `macro_dependency: scenario_id | null` (legacy): equivalent
  `active_scenarios: [scenario_id]` при backward-compat.

### 12.2 `kind: quantitative` — непрерывная величина по сценариям

```yaml
catalyst:
  - id: rate_cut_rerating_2026
    kind: quantitative
    trigger: "Snizhenie KS 14.5% → 9.5% к 2027 → rost multiplikatorov P/B"
    date_window: "2026-Q3 to 2027-Q1"
    in_horizon: true
    upside_by_scenario:                  # обязательно, все 4 сценария
      A: 18
      B: 10
      C: 10
      D: 0
    upside_ci_by_scenario:               # обязательно
      A: [8, 30]
      B: [3, 17]
      C: [3, 17]
      D: [0, 0]
    source: "advisor estimate"
    source_quality: MEDIUM
    # p НЕ ПРИСУТСТВУЕТ для quantitative
    # macro_dependency опционально для отчётности (доминирующий сценарий)
```

Поля:
- `upside_by_scenario` (required): map `scenario_id → numeric`. Ключи должны
  совпадать с `matrix.scenario_triggers.*` в `scenarios/{slug}-{date}.yaml`.
- `upside_ci_by_scenario` (required): map `scenario_id → [lo, hi]`.
- `p`: **запрещено** (Validator warning). Uncertainty магнитуды лежит в CI.

### 12.3 Backward-compat (legacy без `kind`)

Catalyst без `kind`, написанный по старой схеме (`p`, `upside_pct`,
`macro_dependency` без `kind`) — Validator выдаёт `catalyst_missing_kind`
уровня yellow. Aggregator интерпретирует как:
- `binary` с `active_scenarios=[macro_dependency]` если `macro_dependency != null`
- `binary` со scenario-independent + 0.7 дисконтом если `macro_dependency = null`

Это даёт gradual migration: старые YAML продолжают считаться (с систематическим
занижением quant-катализаторов), но видны в audit log.

### 12.4 Anti-patterns для catalyst kinds

❌ **`kind: quantitative` без `upside_by_scenario`** — invalid, Validator red.
❌ **`kind: quantitative` с `p`** — поле игнорируется, Validator yellow warning,
  рекомендуется удалить.
❌ **`kind: binary` без `p` или без `upside_pct`** — invalid, Validator red.
❌ **`upside_by_scenario` с ключами не из scenarios YAML** — invalid, Validator
  red (`catalyst_scenario_id_unknown`).
❌ **`upside_by_scenario` с пропущенными сценариями** — Validator yellow
  (`catalyst_quantitative_incomplete_scenarios`); пропущенные подставляются как 0.
❌ **Использовать `p` для непрерывных феноменов** (rate cut, margin compression,
  market share growth) — концептуальная ошибка. См. `docs/investment/portfolio/methodology.md` §1.4
  decision tree.
❌ **Дублировать macro reprice в catalyst tree** (rate→price через линейную бету
  уже в stress). Catalyst должен capture non-linear / idio / event компоненту.

---

## 13. Anti-patterns

❌ **Хранить `null` в обязательных полях без TODO-комментария** — нарушение валидации.
❌ **Дублировать схему между `*.md` frontmatter и `*.yaml`** сверх минимально необходимого. `*.md` frontmatter содержит только идентификационные поля (date, horizon, domain, topic, schema_version). Все события — в `.yaml`.
❌ **Использовать кириллицу в `id`** — slug всегда транслит.
❌ **Помечать `auto_checkable: true` без конкретного `threshold`/`check_date`** — haiku не сможет проверить.
❌ **Сохранять `falsifiers.would_resolve: true` без чёткого критерия закрытия прогноза** — либо критерий, либо `would_resolve: false`.
❌ **Перезаписывать `*.md` при создании парного `*.yaml`** (миграция) — `.md` неприкосновенен.
❌ **Дублировать веса сценариев** в `conditional_on_scenarios.by_scenario` или в forecast YAML — веса хранятся ТОЛЬКО в `source_matrix` SSOT (см. §5.3, D7).
❌ **Хранить значения `central` как строки** (`"13.5%"`, `"$70"`) в `by_scenario.values` — числа + отдельный `unit` (см. §5.3).
❌ **Пропускать сценарии в `by_scenario`** (не все 4 присутствуют) — даже при `provenance: derived_from_marginal` все 4 обязательны.
❌ **Использовать `Sc-A` вместо `A`** в новых файлах — short format (D5). Старые файлы мигрируются `migrate_to_conditional.py` (Phase 3).
❌ **Сочетать `agnostic_total: true` с `primary`/`secondary`** в `implicit_geopolitical_scenarios` — взаимоисключающие виды (см. §6.3).

---

## 14. Калибровочные блоки — `fca_stats` и `outcome_log` (аддитивно, 2026-07-05)

Два **опциональных, аддитивных** блока в forecast YAML (`type: forecast-events`), которые
делают возможной калибровку прогнозной системы (Brier, interval-coverage, тест «weighted vs
unweighted»). Файлы без них остаются валидными — backward-compat, миграция не нужна. Ничего
в существующей схеме не переписывается.

**Мотивация** (self-audit 2026-07-04 §7): при `expired`/`superseded`/PIERCED раньше
фиксировался только `status`, но не исход. Поэтому в библиотеке было **0 записей «прогноз vs
факт»** — ни Brier, ни interval-coverage, ни ценность весов посчитать нельзя.

### 14.1 `fca_stats` — машинный бэкбон точечной оценки (Layer 1/2)

Прецедент: ранний `brent-oil-2026-2027-2026-05-09.yaml` (superseded) уже нёс `fca_stats` с
per-horizon `weighted_median`/`unweighted_median`. Воскрешаем его как **живой машинный слепок**
численного вывода FCA — чтобы `l1_unweighted` и `l2_ev` жили **полями**, а не только прозой в
`notes`/`central_estimate`/`confidence_note` (именно проза мешала калибровке — self-audit
ошибки №2/№3).

Пишет `forecast-confidence-applier` в момент составления прогноза (из вывода
`weighted_consensus.py`). SSOT точечной оценки Layer 1 для человека остаётся
`forecast.central_estimate` (проза); `fca_stats` — её машинное зеркало.

```yaml
fca_stats:                      # опционально; per-horizon; ключи = строки-даты из forecast.horizons
  "2026-12-31":
    kind: level                 # level | event (совпадает с outcome_log.kind этого горизонта)
    unit: "percent_annual"      # для level — единица l1_*/actual
    l1_weighted: 13.0           # = weighted_consensus.py weighted_median (Layer 1, trust-weighted)
    l1_unweighted: null         # = unweighted_median; null # TODO: <причина> если не персистилось
    l2_ev: 13.03                # ЗЕРКАЛО conditional_on_scenarios.marginal.values["2026-12-31"].central
                                #   (SSOT = marginal.values; плоское число здесь только для заморозки)
    p10: 12.25
    p90: 13.25
  "2026-07-24":                 # date-ключ события допустим, если это event-резолв (заседание ЦБ)
    kind: event
    predicted_p: null           # вероятность бинарного исхода (из catalyst.p / модального пути);
                                #   null # TODO если прогноз дал модальный путь, а не явную p
```

Правила:
- Ключи `fca_stats` — подмножество `forecast.horizons` (плюс date-ключи событий из
  `monitoring[].check_date`, если резолв бинарный — например заседание ЦБ).
- `l2_ev` **намеренно дублирует** `marginal.values[horizon].central` — плоское число под
  заморозку. SSOT — `marginal`. При смене L2 обновляется и `fca_stats.l2_ev` (или ставится `null`).
- `l1_unweighted`/`l2_ev`/`p10`/`p90`/`predicted_p` могут быть `null # TODO: <причина>` — это НЕ
  ошибка, а честная отметка «на момент составления не персистилось». **Фабриковать нельзя.**
- Type 1 (isolated): `l2_ev: null` (сценарного слоя нет).

### 14.2 `outcome_log` — журнал исходов «прогноз vs факт»

Список записей, по одной на резолв-точку (горизонт / дата события / заседания / дата замены при
supersession). Замороженные `forecast_*` — **на момент составления прогноза**, а не на момент
резолва (иначе тест ценности весов бессмыслен). Запись создаёт `save-to-library` (seeding при
сохранении; снимок при supersession/expiry) и дозаполняет `forecast-monitor` **через
`save-to-library` Workflow L** (монитор сам в `forecasts/` не пишет — D3 + read-only-контракт).

```yaml
outcome_log:                    # опционально; список
  - resolve_date: 2026-12-31    # горизонт / дата события / заседания / дата замены
    logged_at: 2026-07-05       # когда запись создана/обновлена
    record_type: horizon_resolve  # horizon_resolve | interim_supersession
    kind: level                 # level | event
    # --- заморожено на момент ПРОГНОЗА (копия из fca_stats на дату составления) ---
    forecast_l1_weighted: 13.0
    forecast_l1_unweighted: null   # null # TODO: не персистилось до схемы
    forecast_l2_ev: 13.03
    p10_p90: [12.25, 13.25]
    confidence_at_forecast: 0.40
    # --- для kind: event вместо forecast_l1_*/p10_p90 ---
    # predicted_p: 0.60           # ОБЯЗАТЕЛЬНО для event при резолве (иначе Brier невозможен)
    # --- заполняется на РЕЗОЛВЕ (forecast-monitor → save-to-library Workflow L) ---
    actual: null                # факт (level: число)
    in_p10_p90: null            # bool; считает скрипт: p10 <= actual <= p90
    error_pct: null             # (actual − forecast_l1_weighted)/forecast_l1_weighted; считает скрипт
    resolved: null              # для event: 0|1 (наступило/нет)
    actual_source: null         # URL/файл — провенанс факта
    shock_flag: none            # none | exogenous_shock (экзогенный шок → исключать из «чистой» калибровки)
```

Семантика полей:

| Поле | Тип | Кто пишет | Правило |
|---|---|---|---|
| `resolve_date` | YYYY-MM-DD | seeding | горизонт / событие / дата замены |
| `logged_at` | YYYY-MM-DD | все | дата создания/обновления записи |
| `record_type` | enum | seeding | `horizon_resolve` (дозрел до горизонта) \| `interim_supersession` (снимок на дату замены). **Нельзя мешать 1:1 в Brier** — interim шумнее |
| `kind` | enum | seeding | `level` (brent/ставка) \| `event` (бинарный p) |
| `forecast_l1_weighted` | num | seeding (freeze) | Layer 1 weighted; **на момент прогноза** |
| `forecast_l1_unweighted` | num\|null | seeding (freeze) | тест ценности весов; null → тест недоступен (warning, не блок) |
| `forecast_l2_ev` | num\|null | seeding (freeze) | Layer 2 EV; Type 1 → null |
| `p10_p90` | [lo,hi]\|null | seeding (freeze) | interval-coverage; null → coverage недоступен (warning) |
| `predicted_p` | 0..1 | seeding (freeze) | **kind: event** — ОБЯЗАТЕЛЬНО при резолве (blocking, если `resolved` задан). Стаб без резолва: `null # TODO` (warning) |
| `confidence_at_forecast` | 0..1 | seeding (freeze) | `forecast.confidence` на момент прогноза |
| `actual` | num\|null | резолв | факт (level) |
| `resolved` | 0\|1\|null | резолв | наступление (event) |
| `in_p10_p90` | bool\|null | скрипт | `p10 <= actual <= p90` |
| `error_pct` | num\|null | скрипт | `(actual − forecast_l1_weighted)/forecast_l1_weighted` |
| `actual_source` | str\|null | резолв | провенанс факта; null при заполненном actual → warning |
| `shock_flag` | enum | резолв | `none` \| `exogenous_shock` |

### 14.3 Жизненный цикл записи

1. **Seeding** (`save-to-library` Workflow B, шаг B4.6): при сохранении прогноза создать stub
   для **ближайшего неразрешённого горизонта, когда он входит в ~4-мес окно** от `forecast.date`.
   Дальние горизонты (2027/2028) преждевременно не seed'ятся — получат запись позже, по мере
   приближения (при следующем supersession/rescan). `actual`/`resolved` = null.
2. **Резолв** (`forecast-monitor` → `save-to-library` Workflow L): монитор при `❌ ПРОБИТ` /
   наступлении события / достижении горизонта достаёт факт web_search'ем и кладёт его в
   `outcome_log_updates[]` своего monitor-report (`yaml-schemas.md` §8). `save-to-library`
   применяет: находит запись по (`resolve_date`, `kind`), дозаполняет `actual`/`resolved`/
   `actual_source`/`shock_flag`, гоняет helper (`error_pct`/`in_p10_p90`).
3. **Supersession** (`save-to-library`, `active→superseded`): промежуточный снимок
   `record_type: interim_supersession`, `resolve_date = дата замены`, `forecast_* = оригинал
   (дата составления)`, `actual = факт на дату замены` (если известен, иначе `null`).
4. **Expiry** (`save-to-library`, `active→expired`): запись `record_type: horizon_resolve` на
   `resolve_date = horizon`, факт на горизонт.

Приоритет seeding/резолва — **микропрогнозы** (заседания ЦБ ~раз в 6 недель, OPEC, недельная
инфляция): резолвятся быстро, дают калибровочную выборку уже к осени.

### 14.4 Anti-patterns

❌ **Фабриковать `l1_unweighted`/`predicted_p`/`p10_p90`, если не персистилось.** Только
   `null # TODO`. Ложная точность — ровно дефект (ошибки №2/№3 self-audit), который блок и чинит.
❌ **Морозить `forecast_*` на дату резолва/замены.** Заморозка — на момент составления, иначе
   «weighted vs unweighted» бессмыслен.
❌ **Мешать `interim_supersession` и `horizon_resolve` в одном Brier-подсчёте 1:1.** Interim шумнее.
❌ **kind: event без `predicted_p` при `resolved != null`.** Нельзя Brier-скорить — blocking.
❌ **Монитор пишет `outcome_log` прямо в `forecasts/`.** Нарушение D3 + read-only-контракта
   монитора. Только через monitor-report → save-to-library Workflow L.
❌ **Считать `error_pct`/`in_p10_p90` «на глаз».** Детерминированная арифметика — helper
   `assemble_artifact.py complete-outcome-log`.
❌ **Вписывать `actual`/`resolved` в запись руками.** `actual`/`resolved` пишутся только выводом
   `complete-outcome-log`; без `forecast_l1_weighted` (у event — без `predicted_p`) помощник откажет
   blocking'ом — запись остаётся с `actual: null` (`resolved: null`).
❌ **Класть текстовый `actual` на `kind: event`.** Исход бинарного события — в `resolved` (0|1);
   прозаическое описание — в `actual_source` или `note`; `actual` для event остаётся `null`
   (валидатор warning). Числовой `actual` — только для `kind: level`.

---

## 15. Чек односторонних сценарных конусов (F1, аддитивно, 2026-07-05)

Детерминированная арифметика без reasoning (self-audit Ошибка №1): по ставке и рублю все 4
сценария систематически лежат по одну сторону от **текущего факта** — нет мира «пауза/hike ЦБ»,
нет мира «крепкий рубль». Чек **не выдумывает чисел и ничего не впихивает** — ставит флаг и
требует осознанного решения аналитика. Все поля опциональны и аддитивны.

### 15.1 Якорь — ТЕКУЩИЙ факт, не L1 marginal

**Критично:** знак считается против `(value − anchor)`, где `anchor` = **текущий наблюдаемый
факт**, а НЕ L1 marginal прогноза. Якорение на L1 **вырождает** чек: конус всегда симметричен
вокруг своего же EV, флаг никогда не сработает. Смысл именно в том, лежит ли весь конус по одну
сторону от **сегодняшней реальности**.

| Фактор | anchor |
|---|---|
| `brent`, `usdrub`, `cnyrub`, `xauusd` | компонент `baseline_spot` (текущий спот) |
| `cbr_rate` | текущая ключевая ставка |
| спреды/прочее (urals-discount, инфляция) | текущий спот-уровень фактора |

### 15.2 Аддитивные поля в `conditional_on_scenarios`

```yaml
conditional_on_scenarios:
  # ... (by_scenario, marginal, ...)
  fact_anchor:                    # текущий факт, вокруг которого должен лежать конус
    value: 14.25                  # число в unit блока
    as_of: 2026-06-19             # дата факта (staleness — задел под F6: старый якорь → warning впредь)
    source: "CBR"                 # источник факта (URL/издание/тикер)
    # by_horizon: { "2026-12-31": {value, as_of, source} }  # опц., если факт различается по горизонтам
  one_sided_cone: true            # вычислено check_one_sided_cone; true если ХОТЬ ОДИН горизонт односторонний
  cone_side:                      # per-horizon сторона конуса
    "2026-12-31": down            # up | down | two_sided | neutral
    "2027-06-30": down
    "2028-06-30": down
  counter_world_reason: null      # ОБЯЗАТЕЛЬНО при one_sided_cone: true (иначе save → blocking):
                                  #   либо встречный мир добавлен в by_scenario, либо строка-обоснование
                                  #   «почему во всех мирах так». null # TODO — гейт держит сохранение.
```

Правила:
- `anchor` — скаляр `{value, as_of, source}` (один текущий факт применяется ко всем горизонтам);
  `by_horizon` — редкий опциональный override.
- `one_sided_cone` — «любой горизонт» (более ловящий выбор): дальний горизонт без встречного мира
  — тоже слепая зона.
- `counter_world_reason` — escape-хатч осознанный: **предпочтительно добавить встречный мир** в
  `by_scenario` (он втечёт в macro-scenarios → portfolio-scenario-stress → портфельный вердикт
  увидит двустороннюю ставку — так исправление прогноза доходит до портфеля), либо строка-обоснование
  «почему во всех мирах так» (гейт закрывает, но петлю до портфеля не замыкает).

### 15.3 Арифметика (helper `check-one-sided-cone`)

Per-horizon: `diff_X = central_X − anchor`; `eps = max(0.5% × |anchor|, малый абсолют)` (по умолчанию;
per-factor override — на будущее). Мир нейтрален, если `|diff_X| ≤ eps` (не считается «стороной»).
Если ВСЕ ненейтральные миры по одну сторону → горизонт односторонний, `cone_side = up|down`; если по
обе → `two_sided`; если все нейтральны → `neutral`. `one_sided_cone = any(горизонт односторонний)`.
Для формата macro-scenarios (значения уже `*_pct_vs_spot`/`cbr_rate_delta_bp`) `anchor = 0`.

### 15.4 Гейт (save-to-library `validate-forecast-events`)

- `one_sided_cone: true` (пересчитано из `fact_anchor` + `by_scenario`) И пустой `counter_world_reason`
  → **blocking**; сообщение называет **какие именно горизонты** сработали (адрес, не только факт).
- Персистированный `one_sided_cone` расходится с пересчитанным → **warning** (drift; истина — пересчёт).
- `conditional_on_scenarios` есть, а `fact_anchor` нет → **warning** «нет fact_anchor — cone-чек пропущен»
  (аддитивно; старые файлы не ломаются).

### 15.5 Покрытие falsifiers по сторонам (шаг 3)

Аддитивное поле `side: up | down | both` на записях `falsifiers[]` и `monitoring[]`. Чек: для
сценарного фактора нужен минимум один falsifier/monitor на **каждую** сторону (up и down).

- Непокрытая сторона (есть размеченные, но нет `up` или `down`) → **warning** `missing_side_falsifier`
  (покрытие фальсификаторов вторично — блокировать сохранение из-за него слишком агрессивно).
- Ни одной размеченной стороны → **warning** «сторона не размечена» (авто-классификация текста =
  reasoning, запрещено — сторону проставляет аналитик).
- Пример: у cbr есть up-сторонний монитор `cbr-july-decision` («пауза/повышение вместо −25»); при
  `side: up` → `missing_side_falsifier` не сработает, даже если конус односторонний.

### 15.6 Anti-patterns

❌ **Якорить на L1 marginal.** Вырождает чек — конус всегда вокруг своего EV.
❌ **Авто-сочинять `counter_world_reason`.** Чек ставит флаг; обоснование/встречный мир — осознанное
   решение аналитика. Для ставки counter-world пристёгивается к **сильной девальвации** (война/Sc-A:
   эскалация → девальвация → pass-through → ЦБ держит/повышает), НЕ к миру-разрядке.
❌ **Заполнять `fact_anchor.value` из L1/прогноза.** Только текущий факт (спот/ставка) с `as_of`+`source`.
❌ **Классифицировать сторону falsifier из текста.** `side` проставляется явно, не выводится reasoning'ом.

---

## 16. Расслоение confidence — `source_coverage_score` + `confidence_by_horizon` (F3, аддитивно)

Self-audit Ошибка №3: `confidence` — метрика **покрытия источниками**, а не неопределённости
исхода (21/43 файлов ровно 0.40; один headline на горизонты 2026–2028; 0.80 «единодушие одного»).
F3 **не мутирует** `confidence` — только добавляет честные поля. Все опциональны и аддитивны.

### 16.1 Поля (в блоке `forecast`)

```yaml
forecast:
  confidence: 0.40              # LEGACY-скаляр — НЕ трогается (нулевой дрейф; консьюмеры читают его)
  source_coverage_score: 0.40   # то же число «0 HIGH → 0.40», но ЧЕСТНО названное (метрика покрытия)
  confidence_by_horizon:        # НАСТОЯЩИЙ сигнал: per-horizon уверенность (F3)
    "2026-12-31": 0.50          #   база source_coverage − декэй по дальности − cap'ы
    "2027-06-30": 0.46
    "2028-06-30": 0.30          #   тонкое покрытие дальнего горизонта → cap ≤0.30
```

- **`confidence` (скаляр) — legacy, зафиксирован.** Его значение = то, что FCA эмитил всегда
  (формула §2.2). Не пересчитывается: миграция консьюмеров (`macro-forecast-chain`
  `factor.confidence`, monitor-дайджест, weekly-review) на `confidence_by_horizon` — отдельный
  поздний шаг (F3b), каждый со своим before/after. Пока цель — **перестать терять** информацию.
- **`source_coverage_score`** — тот же скаляр под честным именем (метрика покрытия, не
  неопределённости). Float 0..1.
- **`confidence_by_horizon`** — единственный носитель нового сигнала. Считается
  `weighted_consensus.py` (`compute_confidence_by_horizon`): база `source_coverage_score` минус
  декэй по дальности горизонта, cap при тонком покрытии, cap при `anchor_share > 0.5`.

### 16.2 Провизорные пороги (until outcome_log calibration)

Все пороги — **named-константы в `weighted_consensus.py`**, помечены `provisional until
outcome_log calibration` (взяты из self-audit §8 F3, НЕ подтверждены данными — `outcome_log` §14
ещё пуст). Подкрутить после накопления resolved-исходов.

| Порог | Константа | Значение |
|---|---|---|
| Декэй по дальности | `CONF_DECAY_PER_6MO` / `CONF_DECAY_FREE_MONTHS` | −0.05 за 6 мес сверх 6 мес |
| Тонкое покрытие горизонта | `CONF_THIN_COVERAGE_MIN_SOURCES` / `CONF_THIN_COVERAGE_CAP` | `<2` источников на горизонт → `≤0.30` |
| Доминирующий источник | `ANCHOR_SHARE_CAP_THRESHOLD` / `ANCHOR_SHARE_CAP` | `anchor_share>0.5` → `≤0.40` (кусок F2) |

`anchor_share` (= вес топ-источника / сумма весов консенсуса) считается дешёвым байпродуктом там
же — доставка куска F2 ради этого cap'а.

### 16.3 Валидация (save-to-library) — warning-only

`validate-forecast-events` проверяет типы `source_coverage_score` (число 0..1) и
`confidence_by_horizon` (dict {horizon: 0..1}) — **только warning**, никогда blocking (аддитивно,
старые файлы валидны). Скаляр `forecast.confidence` валидатор **не трогает**.

### 16.4 Anti-patterns

❌ **Пересчитывать/мутировать скаляр `confidence` в рамках F3.** Он legacy и зафиксирован —
   before/after ОБЯЗАН показать нулевой дрейф. Дрейф скаляра = баг, не улучшение.
❌ **Переиспользовать имя `coverage_score`.** Оно занято `macro-forecast-chain` (строка «N/M»,
   покрытие DAG); перегрузка семантики — тот класс coherence-багов, который система и чинит.
❌ **Хардкодить пороги магией.** Только named-константы с пометкой provisional.

---

## 17. Polarity-lock сценарной матрицы (F4, аддитивно)

Self-audit Ошибка №4а: инверсия семантики осей между версиями матрицы (06-10 переопределила
Sc-A/Sc-D относительно 05-04) стоила пересборки ~13 файлов — доминирующая часть process-churn
(~62%). Канон полярности нигде не был зафиксирован как правило → риск повтора. F4 фиксирует канон
машинным полем; все поля аддитивны, проверки **warning-only**.

### 17.1 Канон

**Sc-A = максимальный стресс (война+санкции), Sc-D = максимальная разрядка (мир+снятие санкций).**
Де-факто стандарт с 06-10. Новая матрица темы обязана **наследовать** полярность.

### 17.2 Аддитивные поля (в блоке `matrix` scenario YAML)

```yaml
matrix:
  polarity:                       # канон: stress_pole=A, detente_pole=D
    stress_pole: A
    detente_pole: D
  axis_polarity_change: false     # true ТОЛЬКО при осознанной смене полярности
  axis_polarity_migration:        # обязательна при axis_polarity_change: true — таблица A↔D
    A: D                          #   старый scenario_id → новый
    D: A
```

### 17.3 Проверки (`validate-scenario-events`, warning-only)

- `matrix.polarity` отсутствует → warning «задекларируй {stress_pole:A, detente_pole:D}».
- `stress_pole`/`detente_pole` не из `{A,B,C,D}` или равны → warning.
- Полярность отклоняется от канона (stress_pole≠A или detente_pole≠D) **и** `axis_polarity_change`
  ≠ true → **warning рассинхрона** (смена только осознанно).
- `axis_polarity_change: true` без непустой `axis_polarity_migration` → warning.

Ни одна проверка не блокирует (аддитивно; старые файлы валидны, получают soft-warning).

### 17.4 Anti-patterns

❌ **Инвертировать Sc-A↔Sc-D между версиями матрицы без `axis_polarity_change: true` + миграции.**
❌ **Менять `axis_x`/`axis_y` ↔ scenario_id mapping в течение жизни матрицы** (это Type-C update,
   новый файл — см. `scenario-yaml-spec.md` §5, §8).

---

## 18. `l2_informative` — когда Layer 2 не несёт информации (F5, аддитивно)

Self-audit Ошибка №4б: после июньской пересборки `by_scenario` строится ИЗ marginal (весь
DERIVED) → coherence-диагностика тавтологична (`divergence 0.0% by construction`). Трактовать
0.0% как «хорошую согласованность» — ложь: L2 перестал быть независимым измерением. F5 маркирует
это явно; поля аддитивны, проверки **warning-only**.

### 18.1 Аддитивное поле + N/A severity

```yaml
conditional_on_scenarios:
  l2_informative: false           # false, если весь by_scenario DERIVED из marginal (L2 = копия L1)
coherence_diagnostic:
  severity: "N/A"                 # НОВОЕ допустимое значение (наряду с LOW/MEDIUM/HIGH):
  warning: "L2 не независим (весь by_scenario derived_from_marginal) — coherence не измеряется"
```

`severity: "N/A"` добавлено в разрешённые (§5.2 LOW/MEDIUM/HIGH + N/A). Пороговые проверки
(LOW<5%, …) к N/A не применяются.

### 18.2 Проверки (`validate-forecast-events`, warning-only)

- Все 4 `by_scenario.{A,B,C,D}.provenance == derived_from_marginal` (полный DERIVED):
  - `l2_informative` ≠ `false` → warning «задай l2_informative:false (L2 не несёт информации;
    coherence N/A, не LOW 0.0%)».
  - `coherence_diagnostic.severity == LOW` (флэт/per-horizon/by_horizon) → warning «0.0% coherence
    тавтологична при полном DERIVED — репортить N/A, не трактовать LOW как согласованность».
- `l2_informative: false`, но есть native `by_scenario` (провенанс ≠ DERIVED) → warning
  (противоречие).

### 18.3 Anti-patterns

❌ **Трактовать `divergence 0.0%` как хорошую согласованность при полном DERIVED.** Это тавтология,
   а не сигнал — репортить `severity: N/A`, `l2_informative: false`.
❌ **`l2_informative: false` при наличии native per-scenario источников.** Противоречие: L2 несёт
   информацию, если хоть один сценарий native_fca / single_native.

---

## 19. Отложенный ретро-аудит — `final_audit.status: deferred` (аддитивно)

Горизонт прошёл, но ретро-аудит **сознательно назначен на конкретную дату** (например, ждём
дозревания данных). Раньше такой прогноз попадал в `expired` (= «просрочен/заброшен»), что
навешивало ложный ярлык. `deferred` разводит «отложен по плану» и «заброшен».

### 19.1 Поля

```yaml
final_audit:
  due: {horizon}                 # прошёл
  status: deferred               # наряду с pending | done | overdue
  scheduled_for: 2026-11-15      # ОБЯЗАТЕЛЬНО при deferred — на когда назначен ретро-аудит
```

- **`deferred`** — осознанная отсрочка с датой; top-level `status` при этом остаётся `active`
  (прогноз не заброшен, просто аудит позже). Отличается от `expired` (нет плана / дата не
  назначена) и от `overdue` (аудит должен был быть сделан).
- Наблюдаемый факт на горизонте всё равно пишется в **`outcome_log`** сразу (не ждёт аудита) —
  калибровочная точка не теряется. Формальный ретро-аудит → `status: resolved` на `scheduled_for`.

### 19.2 Взаимодействие с `revise-memory-remote`

- `revise-memory-remote` **не предлагает `expired`**, если `final_audit.status: deferred` и
  `scheduled_for > today` — уважает план, ждёт до даты.
- Когда `scheduled_for` прошёл, а аудита нет → тогда стандартный триггер (предложить
  `expired`/запустить retro-audit).
- save-to-library (light-validation): `status: deferred` без `scheduled_for` (или с прошедшим
  `scheduled_for`) → warning.

### 19.3 Anti-patterns

❌ **`deferred` без `scheduled_for`.** Отсрочка обязана иметь дату — иначе это `expired`.
❌ **Терять факт на горизонте, ожидая аудита.** Пиши `outcome_log` сразу; `deferred` — про
   формальный аудит, а не про фиксацию исхода.

## 20. Закрытие по факту — `final_audit.closed_by` (аддитивно)

`status: resolved` без ретро-аудита ставит save-to-library по фразе владельца «Закрой прогноз …» (`references/close-forecast.md`):

```yaml
status: resolved
final_audit: {due: {горизонт}, status: done, completed: {дата}, closed_by: owner_close, audit_file: null, result: "hit | miss — …"}
```

`closed_by`: `owner_close` | `retro_audit`. `resolved` обязан опираться на `outcome_log` с `record_type: horizon_resolve` и фактом (`actual` / `resolved`); при `owner_close` отсутствие — blocking, иначе warning. Сценарная матрица пары несёт `status: resolved` и `final_audit` с `realized_scenario` / `prior_probability`, без `outcome_log`.
