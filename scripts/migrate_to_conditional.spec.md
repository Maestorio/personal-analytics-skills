# `migrate_to_conditional.py` — спецификация (Phase 1)

Pseudocode для миграционного скрипта Phase 3 (`scripts/migrate_to_conditional.py`).
Скрипт читает forecast YAML + парный `.md`, заменяет legacy блок `geopolitics_translation`
(или эквивалент) на новый `conditional_on_scenarios` блок согласно `events-yaml-spec.md` §5.

**Связанные документы:**
- `events-yaml-spec.md` §5 — целевая схема
- `_shared-references/scenario-yaml-spec.md` — SSOT для весов (вход для `aggregate_marginal`)
- `HANDOFF-claude-code-phased.md` §2.4 — оригинальная задача
- `HANDOFF-claude-code-phased.md` §13 — известные edge cases

---

## INPUT

- `forecasts/{factor}-{horizon}-{date}.yaml` — основной файл с legacy блоком
- `forecasts/{factor}-{horizon}-{date}.md` — sibling, читается для парсинга markdown-таблиц (если YAML не содержит `geopolitics_translation` напрямую)
- Опционально: `--scenario <path>` — путь к SSOT scenario YAML для `source_matrix`. Если не задан, скрипт ищет последнюю активную матрицу в `Claude-Memory/scenarios/` через дату forecast.

## OUTPUT

- Тот же `*.yaml` файл с заменённым блоком `geopolitics_translation` → `conditional_on_scenarios`
- Backup: `<file>.yaml.pre-migration` (атомарно создаётся ДО записи)
- Diff-отчёт `<file>.migration-diff.md` (что изменилось в значениях; для ручного review)

---

## STEPS

```
1. PARSE INPUT
   1.1 Detect encoding: open file as bytes, run chardet.detect()
       - if encoding != "utf-8" AND confidence > 0.7:
           decode as detected, re-encode as UTF-8, write to .yaml.pre-migration
           continue with cleaned bytes
       - if mojibake heuristic (Latin-1 декодинг UTF-8: символы вроде "Ð¡Ñ†") detected:
           apply repair: text_str.encode("latin-1").decode("utf-8")
           (text_str — строка, ошибочно распарсенная как Latin-1; encode обратно
            в bytes, потом decode как настоящий UTF-8.)
           log to migration-diff.md as "ENCODING REPAIR: latin-1 → utf-8"
   1.2 Load YAML (ruamel.yaml для preserve comments/order)
   1.3 Load sibling .md (для парсинга markdown-таблиц на Step 5)

2. DETECT METHOD
   Анализ существующих полей:
     - geopolitics_translation.scenario_rates_2026 (or similar) → "linear"
     - geopolitics_translation.cny_rub_2026 with non-monotonic values → "nonlinear"
     - geopolitics_translation.alternatives only (без scenario-specific block) → "linear" via alternatives
     - distribution_used: true (без scenario block) → "indifferent" или markdown-only
     - Явный axis-dependent mapping → "axis_dependent" (редкий случай)
   Сохранить method для Step 9 (aggregate_marginal call).

3. PARSE scenario_rates_<year> / cny_rub_<year> / etc (linear case)
   3.1 Iterate keys vs scenario_id mapping:
        - Sc-A | A | scenario-a | "Перезагрузка"  → "A"
        - Sc-B | B                                → "B"
        - и т.д.
   3.2 Для каждого значения:
        - regex_percent = r"(-?\d+\.?\d*)\s*%"
        - regex_dollar  = r"\$(-?\d+\.?\d*)"
        - regex_range   = r"(-?\d+\.?\d*)\s*[–\-]\s*(-?\d+\.?\d*)"
        - При match range:    central = (lo+hi)/2, range = [lo, hi]
        - При match single:   central = value, range = null
   3.3 Записать в by_scenario[X].values["{horizon}"].{central, range}
   3.4 Установить:
        - provenance: "native_fca" (если в legacy block есть source attribution)
                    OR "single_native" (если один источник)
                    OR "derived_from_marginal" (если выведено через dependency)
        - sources_used: extracted from legacy block если есть, иначе []
        - coverage_quality: HIGH | MEDIUM | LOW | DERIVED по правилу из §5.2

4. PARSE alternatives (если только alternatives без scenario_rates)
   4.1 Извлечь:
        - Sc-A alternative → by_scenario.A
        - Sc-B alternative → by_scenario.B
        - Sc-C alternative → by_scenario.C
        - Sc-D? Special case: для cny-rub Sc-D сидит в forecast.central_estimate
              верхнего уровня, не в alternatives. Применить edge-case handler 5.6.
   4.2 Парсинг значений — те же regex'ы что в Step 3.2

5. PARSE markdown table (worst case, ru-cpi)
   Если YAML НЕ содержит ни scenario_rates_*, ни alternatives:
   5.1 Прочитать sibling .md
   5.2 Найти секцию `## Геополитическая трансляция` или `## Сценарии`
   5.3 Найти markdown-таблицу с колонками сценариев
   5.4 Regex по строкам: r"\|\s*Sc-([ABCD])\s*\|\s*([0-9.\-–]+%?)\s*\|"
   5.5 Парсить значения как в Step 3.2
   5.6 EDGE CASE для cny-rub: если Sc-D отсутствует в alternatives, искать
       в `forecast.central_estimate` или в "Сценарий D" subsection

6. NORMALIZE scenario_id format (D5)
   Применить regex на ВСЕ keys и values:
     pattern = r"\bSc-([ABCD])\b"
     replacement = r"\1"
   Это меняет:
     - by_scenario keys (если внутри парсинга остались как "Sc-A")
     - sources_used значения (если содержат references)
     - rationale тексты (опционально, без потери смысла)
   Записать `scenario_id_format: short` в conditional_on_scenarios.

7. EXTRACT unit (один на блок)
   7.1 Detect unit из распарсенных regex matches:
        - "%" → unit: "%"
        - "$" → unit: "USD"
        - "₽" → unit: "RUB"
        - "$/bbl" → unit: "USD/bbl"
        - none detected → ask user (interactive prompt) или default "%"
   7.2 Записать в conditional_on_scenarios.unit
   7.3 Удалить unit-suffixes из central/range values (числа без юнита)

8. STRIP scenario weights from forecast YAML (D7)
   Удалить любые поля типа:
     - geopolitics_translation.weights
     - scenario_probability_*
     - scenario_weight_*
   Веса резолвятся через source_matrix → SSOT scenario YAML.

9. RECOMPUTE Layer 2 marginal
   9.1 Загрузить SSOT scenario YAML (--scenario flag или auto-detect)
   9.2 Вызвать aggregate_marginal(by_scenario, weights, horizon, method) [Phase 2]
   9.3 Записать в conditional_on_scenarios.marginal:
        - method: <detected_method>
        - modal_scenario_id: argmax(weights) если max > 0.30, иначе "none"
        - values["{horizon}"]: {central, range}
        - aggregation_formula: "weighted_mean"

10. COMPUTE coherence_diagnostic
    10.1 layer1 = parse_central(forecast.central_estimate)
    10.2 layer2 = conditional_on_scenarios.marginal.values["{horizon}"].central
    10.3 divergence_pct = abs(layer1 - layer2) / abs(layer1) * 100
    10.4 severity = LOW (<5%) | MEDIUM (5-15%) | HIGH (>15%)
    10.5 warning = текст для MEDIUM/HIGH; null для LOW
    10.6 Записать coherence_diagnostic блок (top-level в forecast YAML)
    10.7 Если severity == HIGH: добавить запись в migration-diff.md
         "MANUAL REVIEW REQUIRED: divergence {pct}% между Layer 1 и Layer 2"

11. WRITE OUTPUT
    11.1 Backup оригинала: copy {file}.yaml → {file}.yaml.pre-migration
    11.2 Atomic write нового {file}.yaml через tempfile + rename
    11.3 Append diff в {file}.migration-diff.md:
          - что было удалено (geopolitics_translation, weights)
          - что добавлено (conditional_on_scenarios, coherence_diagnostic)
          - выявленные warnings
```

---

## EDGE CASES

### EC1. `Sc-D` в `central_estimate`, не в `alternatives` (cny-rub case)

В `cny-rub-dec2026-dec2027-2026-05-04.yaml` Sc-D сидит в `forecast.central_estimate`
верхнего уровня (`"USD/CNY: 13.5 к 2027-12-31"`), а Sc-A/B/C — в `alternatives`.

**Handler:** при detection отсутствия Sc-D в `alternatives` → использовать
`forecast.central_estimate` как Sc-D source. Залогировать в migration-diff.md
`EDGE CASE EC1 applied: Sc-D from central_estimate`.

### EC2. Диапазоны типа `"$50–65"` или `"50—65%"`

Regex `r"(-?\d+\.?\d*)\s*[–\-—]\s*(-?\d+\.?\d*)"` ловит как Unicode `–`/`—`, так и ASCII `-`.
Записать как `range: [50, 65]` + `central: 57.5` (среднее).

### EC3. Percent-strings `"13.5%"`

Regex extraction → `central: 13.5`, `unit: "%"`. Никогда не сохранять `"13.5%"` как строку.

### EC4. Mojibake (Latin-1 декодинг UTF-8)

Symptom: символы вроде `Ð¡Ñ†` или `СтавкаÂ` вместо `Ставка`.

**Detect:** chardet с low confidence на utf-8, ИЛИ regex `r"Ã[\x80-\xBF]"` matches.
**Repair:** `text_str.encode("latin-1").decode("utf-8")` — где `text_str` это
строка, ошибочно распарсенная как Latin-1 (содержит mojibake). Encode обратно
в bytes, потом decode как настоящий UTF-8. (Реализация в
`scripts/migrate_to_conditional.py:72` уже использует корректную формулу.)
**Validate post-repair:** загрузить как YAML, должен парситься без UnicodeDecodeError.

### EC5. Forecast без `geopolitics_translation` вовсе

Различаем **два под-кейса** по типизации (`events-yaml-spec.md` §5.5):

#### EC5a — Type 1 (isolated)

Прогноз не привязан ни к одной scenario matrix (например, `russia-europe-war-2030`,
`china-taiwan-forecast`, `iran-us-may-deal`). Триггер — CLI флаг `--isolated`
или явное предписание пользователя.

**Handler:** НЕ создавать `conditional_on_scenarios`. Добавить:

```yaml
isolated: true
isolated_reason: "auto: no scenario translation block found (Type 1 per spec §5.5)"
```

`coherence_diagnostic` НЕ создаётся. В migration-diff.md залогировать
`EDGE CASE EC5a (Type 1 isolated): no conditional_on_scenarios block`.

#### EC5b — Type 2 без `geopolitics_translation`

Forecasts чисто technical, но привязаны к scenario matrix (например,
`imoex-target-2026-04-30.yaml`). Триггер — отсутствие флага `--isolated`
И присутствует `--scenario` параметр.

**Handler:** добавить пустой `conditional_on_scenarios` блок:
```yaml
conditional_on_scenarios:
  source_matrix: <best-guess или null>
  scenario_id_format: short
  unit: <detected>
  by_scenario:
    A: { values: {<horizon>: {central: <Layer 1 value>, range: null}}, provenance: derived_from_marginal, sources_used: [], coverage_quality: DERIVED }
    B: { … }   # все 4 равны Layer 1, derivation note
    C: { … }
    D: { … }
  marginal:
    method: indifferent
    modal_scenario_id: none
    values: { <horizon>: { central: <Layer 1>, range: <Layer 1 range> } }
    aggregation_formula: "weighted_mean"

coherence_diagnostic:
  layer1_marginal: <number>
  layer2_marginal: <same number>
  divergence_pct: 0.0
  severity: LOW
  warning: null
```

Залогировать в migration-diff.md `EDGE CASE EC5b applied: no scenario geometry, all 4 == Layer 1`.

#### EC5c — axis_dependent resolved (SB-1, Phase 1 v1.1)

Forecasts с `geopolitics_translation.method == "axis_dependent"` (например,
`sanctions-russia-2026-27`, `urals-brent-discount`).

**Семантика:** axis_dependent-фактор монотонно зависит от **одной** оси и
индифферентен к другой. Сценарии с одинаковым состоянием доминантной оси
имеют равное значение фактора, поэтому probability-weighted mean математически
эквивалентен коллапсу вдоль доминантной оси. Метод сохраняется как диагностический
тег (`dominant_axis: x|y` — опциональная аннотация, добавляется вручную).

**Handler:** preserve `method: axis_dependent`, `aggregation_formula: weighted_mean`,
никакого `_todo`:

```yaml
marginal:
  method: axis_dependent          # диагностический тег, НЕ заглушка
  modal_scenario_id: <argmax если max>0.30 else none>
  values: { <horizon>: { central: <weighted_mean>, ... } }
  aggregation_formula: "weighted_mean"
  # dominant_axis: x              # опц. аннотация — добавить вручную при необходимости
```

Логировать `EC5c: axis_dependent resolved via weighted_mean along dominant axis`.

### EC6. Markdown-only legacy с inconsistent scenario IDs

Если в markdown-таблице используется ненормированный набор (`Sc-A`, `Sc-B`, `Optimistic`, `Worst`):

**Handler:** скрипт интерактивно спрашивает mapping:
```
Detected non-standard scenario labels: ['Optimistic', 'Worst']
Map to A/B/C/D:
  Optimistic → ?
  Worst      → ?
```

После confirmation — применить mapping и продолжить. Записать mapping в migration-diff.md.

---

## TESTOVYE FAYLY (для Phase 3 валидации)

Реальные данные из `Claude-Memory/forecasts/`, тестируются через Cowork (отдельная среда):

| Файл | Class | Цель |
|------|-------|------|
| `ru-rates-2026-2027-2026-05-04.yaml` | linear, лучший YAML | clean migration без warnings |
| `cny-rub-dec2026-dec2027-2026-05-04.yaml` | nonlinear, partial | EC1 (Sc-D в central_estimate) |
| `ru-cpi-2026-2027-2026-05-04.yaml` | markdown-only | EC4 (mojibake) + Step 5 (markdown table parsing) |

Эти 3 файла должны пройти миграцию без unhandled exceptions; результат — manual review через diff в Cowork Phase 5.

---

## ROLLBACK

При обнаружении ошибки в результате миграции:

```bash
mv forecasts/{file}.yaml.pre-migration forecasts/{file}.yaml
rm forecasts/{file}.migration-diff.md
```

Скрипт **не модифицирует** sibling `.md` файл — только `.yaml`. Это упрощает rollback
и сохраняет инвариант «`.md` неприкосновенен» (`events-yaml-spec.md` §12).

---

## DEPENDENCIES (Phase 2 prerequisites)

Скрипт вызывает функции из `skills/forecast-confidence-applier/scripts/weighted_consensus.py`
(Phase 2.1):

- `aggregate_marginal(by_scenario, weights, horizon, method)` — Step 9
- `parse_central(central_estimate)` — Step 10.1
- `load_weights_from_scenario(scenario_yaml_path)` — Step 9.1

Без Phase 2 скрипт не запустить. Phase 1 фиксирует только spec.

Дополнительно требуется:
- `chardet` (encoding detection)
- `ruamel.yaml` (preserve comments/order)
- `re` (stdlib regex)
