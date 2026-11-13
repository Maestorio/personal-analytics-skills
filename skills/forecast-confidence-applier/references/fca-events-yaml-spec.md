# Events YAML для forecast-confidence-applier

## Шаблон блока

~~~markdown
## Events YAML (для save-to-library)

```yaml
forecast:
  date: {YYYY-MM-DD = дата составления}
  horizon: {YYYY-MM-DD = взвешенный горизонт}
  domain: {domain}
  topic: {topic-slug}
  central_estimate: "{структурированный TL;DR — см. правила ниже}"
  confidence: {формула — см. ниже; LEGACY-скаляр, НЕ трогать}
  source_coverage_score: {то же число под честным именем — из weighted_consensus.py}
  confidence_by_horizon:        # §16 F3 — per-horizon сигнал из weighted_consensus.py
    "{horizon}": {value}        #   передай forecast.horizons в payload → скрипт вернёт map

fca_stats:                    # §14.1 — машинный слепок численного вывода (per-horizon)
  "{horizon}":                #   один блок на каждый горизонт из forecast.horizons
    kind: level               #   level (число) | event (бинарный p)
    unit: "{unit}"            #   percent_annual / USD/bbl / rub_per_usd …
    l1_weighted: {weighted_median}     # из weighted_consensus.py
    l1_unweighted: {unweighted_median} # из weighted_consensus.py; НЕ прятать в notes!
    l2_ev: {marginal.values[horizon].central | null}  # зеркало L2; Type 1 → null
    p10: {p10}
    p90: {p90}

reviews:
  interval_months: {см. таблицу дефолтов ниже}
  next_due: {forecast.date + interval_months}

monitoring:
  - id: {slug-первых-3-значимых-слов}
    description: "{из ключевого допущения / leading indicator}"
    source: "{URL основного источника}"
    threshold: "{конкретный порог}"
    check_date: {next_due или промежуточная}
    impact: invalidates|supports|mixed
    severity: critical|high|medium
    auto_checkable: true|false
```
~~~

## Правила заполнения

**`forecast.central_estimate`:** `"{переменная}: {значение или диапазон} к {дата}"`
Примеры: `"USD/RUB: 88–95 к 2026-12-31"`, `"Война РФ–НАТО: вероятность <15% к 2030-12-31"`

**`forecast.confidence` и `reviews.next_due` берутся из output `weighted_consensus.py`** —
не пересчитывай вручную. Формула в скрипте:

```
confidence = 0.4 + 0.4 × (доля HIGH среди источников в consensus) − 0.2 × (asymmetry_warning ? 1 : 0)
```

Округление до 2 знаков, диапазон [0.0, 1.0]. Скрипт также возвращает
`reviews.interval_months` и `reviews.next_due = forecast_date + interval_months`.

**F3 — расслоение confidence (§16, аддитивно).** Передавай в payload `weighted_consensus.py`
поле `horizons: [<forecast.horizons>]`. Скрипт вернёт (эмить как есть в forecast-блок):
- `source_coverage_score` — то же число, что `confidence` (честное имя метрики покрытия);
- `confidence_by_horizon` — per-horizon сигнал (декэй по дальности + cap'ы; носитель настоящей
  уверенности);
- `anchor_share` — доля топ-источника (диагностика; в forecast-блок можно не выносить).

**`confidence` (скаляр) НЕ пересчитывай и не подменяй** — он legacy, нулевой дрейф (миграция
консьюмеров на `confidence_by_horizon` — отдельный поздний шаг F3b). Пороги декэя/cap'ов —
provisional-константы в скрипте.

**Дефолты `interval_months` по домену** (применяются скриптом, если не передан
`interval_months_override`):

| Тип прогноза | Дефолт |
|---|---|
| ru-macro (ставка ЦБ, инфляция, курс) | 3 |
| ru-sellside, global-banks | 3 |
| geopolitics (включая активную динамику) | 6 |
| tech-ceo, структурные тренды | 6 |
| Прогнозы на 5+ лет | 12 (передавай через `interval_months_override`) |

Если стандартного дефолта недостаточно (например, активная геополитика — 3 мес,
а не 6), передавай в JSON-входе `interval_months_override: 3`.

**`monitoring`:** 2–4 item-а из «Ключевых допущений» и «Leading indicators»:
- `auto_checkable: true` если есть числовой порог или конкретная дата события
- `auto_checkable: false` если требует интерпретации
- `impact: invalidates` — пробитие порога означает, что прогноз провалился
- `severity: critical` — пробитие меняет вердикт прогноза

**`fca_stats`** (§14.1, для калибровки — обязателен при `method: fca`): машинное
зеркало точечной оценки, per-horizon. Значения берутся **напрямую из output
`weighted_consensus.py`** (не пересчитывать вручную):

- `l1_weighted` ← `weighted_median`
- `l1_unweighted` ← `unweighted_median` (**критично:** это поле, не проза в `notes`/
  `confidence_note` — иначе тест «ценность весов» невозможен, self-audit ошибки №2/№3)
- `l2_ev` ← `conditional_on_scenarios.marginal.values["{horizon}"].central` (Type 2);
  для Type 1 (isolated) → `null`. Это **зеркало** SSOT `marginal.values`, не второй источник.
- `p10` ← `p10`, `p90` ← `p90`
- `kind: event` вместо level — только для бинарных резолвов (заседание ЦБ, OPEC-решение):
  тогда вместо `l1_*/p10/p90` пишется `predicted_p` (из `catalyst.p` / модального пути). Если
  прогноз дал модальный путь без явной вероятности — `predicted_p: null # TODO`, но впредь
  для event стремиться к явной `p` (без неё Brier невозможен).
- Любое не извлечённое численное поле — `null # TODO: <причина>`. **Фабриковать нельзя.**

`fca_stats` — источник заморозки для `outcome_log` (его наполняет `save-to-library`,
см. `references/events-yaml-spec.md` §14).

**Когда блок НЕ выводится:** только если пользователь явно сказал «не сохраняй» или
запрос операционный без намерения сохранения. По умолчанию блок присутствует —
save-to-library не запускается без отдельной команды пользователя.

---

## Conditional architecture (двухслойная маргинальная)

Forecast YAML может содержать опциональный блок `conditional_on_scenarios`,
связывающий маргинальный прогноз со scenario matrix. Полная спецификация —
`references/events-yaml-spec.md` §5.

**Краткий обзор для FCA:**

- `forecast.central_estimate` — **Layer 1 marginal**, прямой trust-weighted FCA;
  scenarios игнорируются; используется для портфельной EV и weekly-review.
- `conditional_on_scenarios.marginal.values` — **Layer 2 marginal**, агрегированное
  через `aggregate_marginal()` (см. `weighted_consensus.py`); диагностика через
  `coherence_diagnostic` блок.
- `conditional_on_scenarios.by_scenario.{A,B,C,D}` — per-scenario values; читается
  напрямую `portfolio-scenario-stress`.
- `source_matrix` — путь к scenario YAML (SSOT для весов; D7 lazy aggregation).

**Type 1 — Isolated forecasts** (`events-yaml-spec.md` §5.5):

Прогнозы без сценарной геометрии (бинарные события, прогнозы вне макро-цепочки):

```yaml
forecast:
  central_estimate: "..."
  confidence: 0.40
isolated: true
isolated_reason: "Single binary event без сценарной декомпозиции"
# conditional_on_scenarios — отсутствует
```

В FCA для Type 1 — обычный workflow (`weighted_consensus.py compute`), но НЕ строится
`conditional_on_scenarios` блок; вместо этого добавляется `isolated: true`.

**implicit_geopolitical_scenarios в audit frontmatter** (`events-yaml-spec.md` §6):

Источник может имплицитно опираться на конкретный scenario worldview. Это влияет на
filtering при per-scenario FCA (Phase 6+):

```yaml
implicit_geopolitical_scenarios:
  primary: { scenario_id: D, weight: 0.7, rationale: "..." }
  secondary: { scenario_id: B, weight: 0.3, rationale: "..." }
agnostic_subdomains: [oil-forecast]
```

Инвариант: `primary.weight + secondary.weight == 1.0` (или `agnostic_total: true`
для глобальных источников типа Morgan Stanley / Goldman Sachs).

---

## Чек одностороннего конуса (§15, F1) — обязателен для Type 2

После сборки `by_scenario` (все 4 сценария) прогони детерминированный чек: не лежат ли все
4 мира по одну сторону от **текущего факта** (self-audit Ошибка №1 — по ставке/рублю нет мира
«пауза/hike ЦБ», нет мира «крепкий рубль»). Полная спека — `references/events-yaml-spec.md` §15.

**Шаги:**

1. Заполни `fact_anchor` — **текущий наблюдаемый факт** (не L1!), который ты уже достал на Шаге 4:
   спот из `baseline_spot` для FX/нефти/золота, текущая ключевая ставка для cbr, текущий спот-уровень
   для спредов. С `as_of` + `source` (задел под staleness F6):
   ```yaml
   conditional_on_scenarios:
     fact_anchor: { value: 14.25, as_of: 2026-06-19, source: "CBR" }
   ```
2. Прогони helper (арифметика, без reasoning):
   ```bash
   echo '{"anchor": 14.25, "by_scenario": <by_scenario>}' \
     | python3 <save-to-library>/scripts/assemble_artifact.py check-one-sided-cone
   ```
   Запиши `one_sided_cone` + `cone_side` (per-horizon) из результата.
3. Если `one_sided_cone: true` — **осознанное решение** (save-to-library заблокирует сохранение без него):
   - **Предпочтительно — добавь встречный мир** в `by_scenario`. Он втечёт в macro-scenarios →
     `portfolio-scenario-stress` → портфельный вердикт увидит двусторонний фактор. Так исправление
     прогноза доходит до портфеля (петля self-audit сфера-1 → сфера-3).
   - Либо `counter_world_reason: "<обоснование, почему во всех мирах так>"` (гейт закрывает, но до
     портфеля не доходит).

**Подсказка по ставке (важно, где искать встречный мир).** Мир высокой ставки — **НЕ в ветке
разрядки**, а на оси инфляция / фискальное доминирование: эскалация → девальвация рубля →
pass-through в CPI → ЦБ вынужден держать/повышать. То есть counter-world по `cbr_rate` пристёгивается
к **сильной девальвации** (война/Sc-A), не к миру-разрядке. Не сочиняй `counter_world_reason` — чек
только ставит флаг и требует твоего решения.

**Стороны falsifiers.** Проставь `side: up | down | both` на записях `falsifiers`/`monitoring` — чек
покрытия (§15.5) выдаст warning `missing_side_falsifier`, если непокрыта сторона up или down. Пример:
у cbr монитор «пауза/повышение вместо −25» — это `side: up`.
