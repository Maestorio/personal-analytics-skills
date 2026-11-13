# YAML Schemas — Все типы в DAG прогнозов

Единый реестр YAML-форматов, используемых скиллами. Каждый тип описан кратко;
полные примеры — в `events-yaml-spec.md`.

**Правило schema_version:** все новые YAML-файлы содержат `schema_version: 1`.
Файлы без этого поля считаются legacy и помечаются при ревизии.

> **Phase 4 (2026-06-10):** `weekly-review-stock`, `weekly-review-bond` и `stress`
> подняты до `schema_version: 2` (multiple horizons + Monte Carlo). Полная спека
> v2 — **§11 ниже**. v1 не принимается: валидаторы save-to-library и integrated-view
> отклоняют `schema_version` ≠ 2 (мигратор — `portfolio-scenario-stress/scripts/migrate_v1_to_v2.py`).

---

## 1. `type: forecast-events` — прогноз (Tier 1 / Tier 2)

**Кто пишет:** `forecast-confidence-applier` (Tier 1) + `hypothesis-stress-tester` (Tier 2)
**Кто читает:** `forecast-monitor`, `portfolio-scenario-stress`, `portfolio-integrated-view`
**Папка:** `Claude-Memory/forecasts/`
**Файл:** `{topic-slug}-{forecast-date}.yaml` (нет `-stress` суффикса)
**Стресс-вариант:** `{topic-slug}-{forecast-date}-stress.yaml` (параллельная пара, не патч)

Обязательные поля Tier 1:
```yaml
schema_version: 1
type: forecast-events
forecast_ref: <basename>.md
status: active
forecast:
  date: YYYY-MM-DD
  horizon: YYYY-MM-DD
  domain: <domain>
  topic: <topic-slug>
  central_estimate: "<text>"
  confidence: 0.00
reviews:
  interval_months: <N>
  next_due: YYYY-MM-DD      # вычисляет save-to-library при сохранении
  last_completed: null
  history: []
final_audit:
  due: YYYY-MM-DD
  status: pending
```

Tier 2 добавляет: `monitoring[]`, `assumptions[]`, `thresholds[]`, `deadlines[]`,
`falsifiers[]`, `agents[]` — с полем `auto_checkable: bool` в каждом элементе.

**Отличие Tier 1 / Tier 2:** наличие хотя бы одной из секций HST (monitoring, falsifiers,
assumptions, thresholds, deadlines, agents). Отражается в `forecasts/INDEX.md`.

---

## 2. `type: scenario-events` — сценарная матрица

**Кто пишет:** `scenario-builder`
**Кто читает:** `forecast-monitor`
**Папка:** `Claude-Memory/scenarios/`
**Файл:** `scenario-{topic-slug}-{date}.yaml`

Обязательные поля:
```yaml
schema_version: 1
type: scenario-events
scenario_ref: <basename>.md
status: active
matrix:
  date: YYYY-MM-DD
  horizon: YYYY-MM-DD
  domain: <domain>
  topic: <topic-slug>
  axis_x: "<переменная X: полюс A vs полюс B>"
  axis_y: "<переменная Y: полюс C vs полюс D>"
scenario_triggers:
  - scenario_id: A          # A | B | C | D
    label: "<имя>"
    probability: 0.25
    enabling_conditions: [...]
    leading_indicators: [...]
reviews:
  interval_months: <N>
  next_due: YYYY-MM-DD
  last_completed: null
  history: []
final_audit:
  due: YYYY-MM-DD
  status: pending
```

---

## 3. `type: forecast_collection` — коллекция для ретро-аудита

**Кто пишет:** `forecast-collector`
**Кто читает:** `retrospective-forecast-audit`
**Папка:** `Claude-Memory/forecast-collections/`
**Файл:** `fc-{source-slug}-collection-{date}.md` (только `.md`, без `.yaml`)

Frontmatter:
```yaml
source: <source-slug>
collection_date: YYYY-MM-DD
domain: <domain>
n_collected: <N>
n_dropped: <N>
warnings: []
```

---

## 4. `macro-input` — выход macro-forecast-chain

**Кто пишет:** `macro-forecast-chain`
**Кто читает:** `portfolio-scenario-stress`, вьюер (цепочка стресс → макросценарии → прогнозы)
**Папка:** `Claude-Memory/macro-chain/`
**Файл:** `macro-scenarios-{date}.yaml` (+ `macro-marginal-{date}.yaml`; старое имя — `macro-input-{date}.yaml`)

Ключевые поля:
```yaml
schema_version: 2            # 2 — несёт forecast_files (обязателен); 1 — старые файлы без ссылки
run_id: MFC-YYYYMMDD-N
forecast_files:              # {фактор: имя файла forecasts/<имя>.yaml без расширения} — ссылка, не копия;
  brent_price: brent-price-2026-09-17   # строит check_source_files.py --forecast-files из source_files
mode: QUICK-REFRESH | FULL | PARTIAL
generated_at: <date>
portfolio_snapshot: portfolio-{date}.json
coverage:
  total_required: <N>
  total_fresh: <N>
  coverage_score: "<N/M>"
  ready_for_stress_test: bool
forecasts:           # geopolitics, cbr_rate, brent, usdrub, inflation_ru, ...
  <factor>:
    status: fresh | stale | missing
    ...
scenarios: [...]
caveats: [...]
ready_for_stress_test: bool
blocking_issues: []
```

---

## 5. `stress` — выход portfolio-scenario-stress

**Кто пишет:** `portfolio-scenario-stress`
**Кто читает:** `portfolio-integrated-view`, `ru-portfolio-advisor` (mode 8)
**Папка:** `Claude-Memory/Portfolio/stress/`
**Файл:** `stress-{date}-{source}.yaml` (+ парный `.md`)

Ключевые поля:
```yaml
schema_version: 1
date: <date>
scenario_source: macro-forecast-chain | forecast-confidence-applier | scenario-builder | manual
portfolio_snapshot_id: portfolio-{date}.json
macro_input: macro-scenarios-{date}.yaml  # ссылка на макросценарии (ставит build_stress_stub.py); второго поля нет
run_id: PSS-YYYYMMDD-N
scenarios: [...]
portfolio_pl_range_rub: {min, max}
expected_pl_rub: <N>
top_risks: [...]
concentration_metrics: {...}
```

> **v2 (Phase 4):** `schema_version: 2` добавляет `horizons`/`horizon_ends`,
> заменяет `scenarios.X.factors` → `scenarios.X.factors_by_horizon`, а в
> `per_position.X` выносит всё горизонт-зависимое в блок `by_horizon`
> (`factor_betas` остаются плоскими). Полная спека — §11.2.

---

## 6. `portfolio-snapshot` — выход portfolio-data-loader

**Кто пишет:** `portfolio-data-loader`
**Кто читает:** `ru-portfolio-advisor`, `macro-forecast-chain`, `portfolio-scenario-stress`
**Папка:** `Claude-Memory/Portfolio/snapshots/`
**Файл:** `portfolio-{date}.json`

Ключевые поля (JSON, schema_version в корне):
```json
{
  "schema_version": "1.0",
  "as_of_date": "YYYY-MM-DD",
  "generated_at": "<iso8601>",
  "input_files": {"trades": "<filename>", "balance": "<filename>"},
  "holdings": [
    {
      "ticker": "<str>", "isin": "<str|null>", "name": "<str>",
      "qty": 0, "avg_cost_rub": null, "current_price": 0,
      "current_price_source": "moex_iss", "current_price_ts": "<iso>",
      "value_rub": 0, "currency": "RUB|USD|EUR|CNY",
      "asset_type": "stock|bond|fund|cash", "account": "main|iis|...",
      "is_blocked": false, "nominal_currency": "<str>",
      "ytm_pct": null, "ytm_source": null
    }
  ]
}
```

---

## 7. `weekly-review-stock` — выход ru-portfolio-advisor (акции)

**Кто пишет:** `save-to-library` (по opt-in от advisor)
**Кто читает:** `portfolio-integrated-view`, `portfolio-integrated-viewer.html`
**Папка:** `Claude-Memory/Portfolio/weekly-reviews/`
**Файл:** `weekly-review-stock-{date}.yaml` (новая конвенция, 2026-05-07)
**Legacy-файл:** `weekly-review-{date}.yaml` (без суффикса; распознаётся через `type: weekly-stocks-review`)

Схема: `references/weekly-review-schema.md` в скилле `ru-portfolio-advisor` (детали там).
Ключевые поля: `schema_version: 2`, `type: weekly-stocks-review`, `horizons`/`horizon_ends`/`primary_horizon`, `per_stock` с per-ticker блоками (fundamental_score, div_yield_12m_pct, catalyst, advisor_verdict, verification_priority).

> **v2 (Phase 4):** `schema_version: 2` заменяет `horizon_months`/`horizon_end`
> на `horizons`/`horizon_ends`/`primary_horizon`, а в `catalyst[]` удаляет
> `in_horizon` (consumer вычисляет из `date_window`). Спека — §11.1.

> **R-COV (2026-07-23, только v2):** опциональный per-stock флаг `carried_over: true` —
> осознанный перенос фундаментального блока из прошлого обзора без свежей проверки.
> Без флага валидатор save-to-library ставит warning, если у тикера нет ни одного
> источника с `accessed_date` в окне 7 дней до `review_date` (детектор молчаливого
> carry-over). Детали — `weekly-review-schema.md` + SKILL.md «R-COV».

> **Блок `coverage` (RPA-25/RPA-34, акции и облигации, аддитивно).** Отдаёт `sweep_collect.py`:
> `method`, `tickers_total`, `checked_this_run[]`, `carried_over[]`, `not_checked[]`, `note`.
> С `review_date` ≥ 2026-10-27 при ≥5 акциях / корп-эмитентах валидатор блокирует обзор без
> `coverage.method: sweep_collect` (сбор новостей субагентами); исключение —
> `inline_owner_approved` с непустым `method_note` (владелец согласился собирать без субагентов) —
> warning. Обзоры раньше даты не затрагиваются.

### 7a. Catalyst sub-schema (METH-1, 2026-05-13)

Каждый элемент `per_stock.{ticker}.catalyst[]` обязан иметь `kind`. Полная
спека и формулы — канон `events-yaml-spec.md` §12 и
`docs/investment/portfolio/methodology.md` §1.

**binary** (дискретное событие):
```yaml
- id: <slug>
  kind: binary                    # required
  p: 0.88                         # required, ∈ (0, 0.95]
  upside_pct: 3                   # required
  upside_ci_pct: [0, 5]           # required
  in_horizon: true                # required
  source: "..."                   # required
  source_quality: HIGH|MEDIUM|LOW # required
  trigger: "..."                  # required
  date_window: "2026-07"          # required
  # Сценарная привязка (опционально, одно из двух):
  active_scenarios: ["A"]         # новая форма (список)
  macro_dependency: "A"           # legacy (одиночный id; equiv. active_scenarios=[id])
```

**quantitative** (непрерывная величина):
```yaml
- id: <slug>
  kind: quantitative              # required
  in_horizon: true                # required
  source: "..."                   # required
  source_quality: HIGH|MEDIUM|LOW # required
  trigger: "..."                  # required
  date_window: "..."              # required
  upside_by_scenario:             # required, все 4 сценария
    A: 18
    B: 10
    C: 10
    D: 0
  upside_ci_by_scenario:          # required
    A: [8, 30]
    B: [3, 17]
    C: [3, 17]
    D: [0, 0]
  # p: НЕ ДОЛЖНО присутствовать (validator warning)
  # macro_dependency: опционально, для отчётности (доминирующий сценарий)
```

**Legacy** (без `kind`): catalyst без поля `kind` интерпретируется как `binary`
с автоматической backward-compat миграцией; Validator выдаёт
`catalyst_missing_kind` уровня yellow. См. `events-yaml-spec.md` §12.3.

## 7b. `weekly-review-bond` — выход ru-portfolio-advisor (облигации, Phase 10.4)

**Кто пишет:** `save-to-library` (по opt-in от advisor; вместе с stock review при стандартном еженедельном обзоре)
**Кто читает:** `portfolio-integrated-viewer.html` (вкладка «Облигации»), будущий `portfolio-integrated-view` синтезатор
**Папка:** `Claude-Memory/Portfolio/weekly-reviews/`
**Файл:** `weekly-review-bond-{date}.yaml`

> **v2 (Phase 4):** `schema_version: 2` заменяет `horizon_months`/`horizon` на
> `horizons`/`horizon_ends`/`primary_horizon`, в `catalyst[]` удаляет
> `in_horizon`. Структура `per_bond` не меняется. Спека — §11.1.

```yaml
schema_version: 1
type: weekly-bonds-review
review_date: "2026-05-06"
horizon_months: 20
snapshot_id: "portfolio-2026-05-05.json"
snapshot_date: "2026-05-05"
advisor_version: "ru-portfolio-advisor@2.x"
producer: "claude-opus-4-7"
trust_matrix_source: "Claude-Memory/INDEX.md"
trust_matrix_extracted_at: "2026-05-06T11:55:00"
stress_reference: "stress-2026-05-06-zheleznyi-zanaves.yaml"

# Per-bond блок — каждая позиция (ISIN или MOEX-тикер)
per_bond:
  RU000A1038V6:
    name: "ОФЗ 78714"
    weight_real_pct: 1.28
    on_iis: true
    bond_type: ofz                       # ofz | corp_rub | fx_replacement | floater | perpetual
    plan_bucket: "ОФЗ"                   # опционально (STL-7): USD | EUR | CNY | ОФЗ | КОРП | null — плановая таксономия владельца, см. «Правила» ниже
    plan_subtype: ">10"                  # опционально: >10 | <10 | Флоат (для ОФЗ) | AA+ | A | B+ (для КОРП, + Флоат) | null (для валютных)
    is_floater: false                    # опционально, bool — ортогонален bond_type, см. «Правила» ниже
    nominal_currency: RUB                # RUB | USD | EUR | CNY
    maturity_date: "2041-05-15"
    duration_days: 5500                  # estimated если не дано
    ytm_pct: 14.82
    ytm_source: "moex_iss"               # moex_iss | intelinvest | manual_estimate
    coupon_pct: 7.1
    coupon_freq_per_year: 2
    next_coupon_date: "2026-08-15"

    credit_rating: "AAA"                 # рейтинг (Эксперт РА / АКРА / S&P)
    credit_rating_agency: "АКРА"
    credit_rating_basis: "Государственный долг РФ"
    credit_rating_checked_at: "2026-11-03"  # опционально: дата последней сверки рейтинга с первоисточником агентства | null; корп-бумаги старше 28 дн. → warning rating_check_due
    rating:                              # опционально: рейтинг агентства, по нему загрузчик выводит корзину КОРП; у ОФЗ нет
      value: "AA-"                       # AAA…B- (лестница §4.2) | "нет рейтинга"
      agency: "АКРА"                     # АКРА | Эксперт РА | НКР | НРА
      date: "2026-09-12"                 # дата релиза агентства
      source: "https://www.acra-ratings.ru/..."
    credit_rating_file: "AAA"            # опционально (STL-7): справочный рейтинг из файла владельца — источник для сверки, НЕ подмена credit_rating (см. «Правила»)
    credit_quality: HIGH                 # HIGH | MEDIUM | LOW (для viewer's color coding)

    fundamental_sources:
      - url: "https://iss.moex.com/..."
        label: "MOEX ISS — данные облигации"
        accessed_date: "2026-05-06"

    # Catalysts — для облигаций обычно redemption + кредитные риски
    catalyst:
      - id: redemption
        trigger: "Погашение в 2041-05-15"
        date_window: "2041-05-15"
        in_horizon: false                # вне 20-мес окна
        p: 0.97
        upside_pct: 0
        upside_ci_pct: [-1, 1]
        source: "moex_iss"
        source_quality: HIGH
        macro_dependency: null
      - id: rate_cut_capital_gain
        trigger: "Снижение ставки ЦБ → рост цены тела облигации"
        date_window: "2026-Q4 to 2027-Q2"
        in_horizon: true
        p: 0.6
        upside_pct: 8
        upside_ci_pct: [3, 14]
        source: "advisor estimate"
        source_quality: MEDIUM
        macro_dependency: "Sc-D_base"

    advisor_verdict: HOLD                # единый словарь (codelists verdict, schema.md §3.4): HOLD (default) | HOLD_TO_MAT | ADD | WATCH | TRIM | SELL | BUY (редко)
    advisor_verdict_confidence: 0.9
    # p_outperform_3m: 0.6               # ТОЛЬКО у направленных (BUY/ADD/TRIM/SELL): P(обгонит/отстанет от
    #                                    # индекса класса/корзины за 3 мес.); с 2026-10-08 обязателен (AIR-1 D-3)
    advisor_verdict_basis: "ИИС-3 hold to maturity, qualcrédit"
    advisor_verdict_constraints:
      - "iis_3_hold_lock: позиция на ИИС-3, продажа разрушит налоговую льготу"

    verification_priority: LOW           # HIGH | MEDIUM | LOW — ставит stamp-report save-to-library (R28), модель не заполняет
    verification_checklist: []           # 1–3 пункта: проверяемое утверждение с датой или порогом; HIGH без пунктов — блок (R33)
    last_corp_event: "2026-04-15: купонная выплата 35.45 ₽"

# Aggregate summary block — для viewer summary
summary:
  positions_reviewed: 18
  positions_on_iis: 6

  # Средневзвешенные метрики (по weight_real_pct)
  weighted_ytm_pct:
    value: 13.8
    ci_pct: [12.5, 15.0]                 # узкий CI если все YTM известны
  weighted_duration_days: 1850
  total_bond_weight_pct: 42.3            # доля облигаций в портфеле

  # Распределение по типам
  by_type_pct:
    ofz: 18.5
    corp_rub: 14.2
    fx_replacement: 7.8
    floater: 1.5
    perpetual: 0.3

  # Распределение по кредитному качеству
  by_credit_quality_pct:
    HIGH: 28.4
    MEDIUM: 12.1
    LOW: 1.8

  # Maturity ladder (год → суммарная доля портфеля % погашающихся в этот год)
  maturity_ladder_pct:
    "2026": 2.1
    "2027": 8.5
    "2028": 12.3
    "2029": 5.4
    "2030+": 14.0

  # ИИС-3 распределение
  on_iis_total_pct: 12.5
  red_flag_count: 0

caveats:
  - severity: HIGH
    message: "Duration estimated для бумаг без явной maturity_date в снапшоте"
  - severity: MEDIUM
    message: "..."

quality_checks:
  - check: "every bond has ytm_pct"
    passed: true
  - check: "iis_3 bonds have hold_lock constraint"
    passed: true
```

**Правила:**
- Файл генерируется ru-portfolio-advisor вместе со stocks review при стандартном еженедельном обзоре (не отдельный mode).
- ISIN или MOEX-тикер используется как ключ `per_bond.{key}`.
- `bond_type` фиксированный набор: `ofz | corp_rub | fx_replacement | floater | perpetual`.
- `credit_quality` HIGH/MEDIUM/LOW для viewer — derived из `credit_rating` + `bond_type` (ОФЗ всегда HIGH).
- **`plan_bucket`/`plan_subtype`** (STL-7, опциональны) — **плановая** таксономия владельца
  (Numbers, таблица «План по Облигациям»): `plan_bucket` ∈ `USD | EUR | CNY | ОФЗ | КОРП | null`,
  `plan_subtype` — подтип внутри корзины (`>10 | <10 | Флоат` для ОФЗ; `AA+ | A | B+` (+ `Флоат`)
  для КОРП; `null` для валютных корзин). Эта таксономия **ортогональна** инструментальной
  `bond_type` и её **не заменяет** — обе сосуществуют. Допустимые пары (Тип, Подтип) —
  `docs/investment/portfolio/bond-subtypes-plan.md` §4.3. Отсутствие обоих полей валидно
  (артефакты до 2026-08-18 их не несут).
- **`is_floater`** (STL-7, опционален, bool) — тип купона (плавающий/фиксированный),
  **ортогонален `bond_type` и НЕ подменяет в нём значение `floater`.** ОФЗ-ПК обязана
  оставаться `bond_type: ofz` (иначе ломается вывод `credit_quality`, где «ОФЗ всегда HIGH»
  завязано именно на `bond_type`) и одновременно нести `is_floater: true`. Решение принято
  осознанно (`bond-subtypes-plan.md`, решение RPA-14) — если `bond_type` для ОФЗ-ПК вдруг
  окажется переписан на `floater`, это регресс, а не починка: два признака (эмитент и тип
  купона) не должны делить одно поле.
- **`credit_rating_file`** (STL-7, опционален) — справочный рейтинг **из файла владельца**
  (Numbers, колонка «Рейтинг»). Источник для сверки с `credit_rating`, не подмена: `credit_rating`
  по-прежнему заполняется моделью по агентствам (Эксперт РА / АКРА / НКР / НРА) — решение Q5.
- **`rating`** (необязательный блок `{value, agency, date, source}`) — рейтинг агентства, из которого загрузчик выводит
  корзину КОРП; меняется только при новом релизе агентства (заготовка обзора переносит прошлое значение). Форма —
  warning валидатора; `credit_rating` остаётся аналитическим полем модели. Правило вывода — `bond-subtypes-plan.md` §4.5.
- `verification_priority`: ставит `assemble_artifact.py stamp-report` функцией движка `compute_verification_priority` (вердикт, уверенность, действующие условия, гейт модуля (б)) после записи обзора; в стабе `null`, модель не заполняет, из прошлого обзора не переносится (R28). Копии статуса гейта `gate_status_snapshot` в обзоре нет — у старых обзоров валидатор даёт предупреждение «устаревшая копия».
- `catalyst[*]` — обычно один `redemption` + опц. `rate_cut_capital_gain` (если duration > 2 лет) + `credit_event` (если LOW credit_quality).

---

## 8. `monitor-report` — выход forecast-monitor (Phase 10.3)

**Кто пишет:** `forecast-monitor` → artefact в чат → пользователь зовёт `save-to-library` (D3-compliant)
**Кто читает:** `portfolio-integrated-viewer.html` (Watchlist tab); опц. ru-portfolio-advisor для контекста
**Папка:** `Claude-Memory/monitor-reports/`
**Файл:** `monitor-report-{date}.yaml` (lowercase, D4)

```yaml
schema_version: 1
type: monitor-report
generated_at: "2026-05-07T10:00:00"
producer: "forecast-monitor"
horizon_window_days: 7              # окно, в котором запускался monitor
scope: full                         # full | partial; без поля — full (кроме caveat «Запуск по одному файлу» → partial)
checked: []                         # при partial обязателен: проверенные target_file; вьюер и уведомления
                                    # заменяют предупреждения только по ним, остальные берут из последнего full

# Список алертов — основная нагрузка
alerts:
  - severity: HIGH                   # HIGH | MEDIUM | LOW | INFO
    category: stale                  # stale | horizon_passed | event_window | factor_breach |
                                     # source_dead | prediction_due | catalyst_missed
    target: "ukraine-russia-2026-04-01"
    target_file: "forecasts/ukraine-russia-2026-04-01.yaml"
    target_kind: forecast            # forecast | scenario | catalyst | source | view
    message: "Прогноз просрочен по next_due на 12д"
    detected_at: "2026-05-07"
    web_search_summary: |            # опц., если monitor делал web_search
      ...
    suggested_action: "Запусти retrospective-forecast-audit"
    monitoring_id: "cbr-decision-2310"  # опц.: алерт по пункту monitoring[] цели (id из вывода monitor_alerts.py)

# Пункты monitoring[] активных целей с check_date ≤ даты generated_at, по которым алерта нет
monitoring_checked:
  - target: "cpi-yoy-ocr-2026"
    target_file: "forecasts/cpi-yoy-ocr-2026-2026-10-10.yaml"
    monitoring_id: "mer-weekly-26oct"
    check_date: "2026-10-28"
    result: not_met                  # кодлист monitoring_result: met | not_met | unverified
    note: "недельная инфляция 0,12% — ниже порога"   # опц.; при unverified — почему

# Аудит свежести по типам артефактов
freshness_audit:
  integrated_view:
    age_days: 12
    next_due: "2026-11-04"
    due_for_refresh: false
  stress:
    age_days: 95
    threshold_days: 90
    due_for_refresh: true
    message: "Превышен лимит свежести"
  weekly_review:
    age_days: 1
    threshold_days: 14
    due_for_refresh: false
  macro_snapshot:
    age_days: 6
    threshold_days: 14
    due_for_refresh: false
  trust_matrix:
    age_days: 67
    threshold_days: 90
    due_for_refresh: false

# Сводка по предсказаниям
predictions:
  total_active: 47
  overdue_count: 2
  due_30d_count: 5
  overdue_list:
    - { id: "sber_div_2025", file: "Portfolio/integrated-views/integrated-view-2025-11-01.md", days_overdue: 3 }

# Опц.: factor checkpoints (Phase 10.3 v2)
factor_breaches: []

# Опц.: захваченные исходы для калибровки (events-yaml-spec.md §14.3).
# Монитор кладёт сюда факт на резолве; save-to-library Workflow L пишет его в forecasts/.
outcome_log_updates:
  - target_file: "forecasts/cbr-rate-2026-2027-2026-07-02.yaml"
    resolve_date: "2026-07-24"     # по какой записи outcome_log (resolve_date + kind)
    kind: event                    # level | event
    actual: 14.0                   # level: факт (число); для event можно оставить null
    resolved: 1                    # event: наступило(1)/нет(0); для level — null
    actual_source: "https://cbr.ru/press/pr/?file=..."
    shock_flag: none               # none | exogenous_shock
    detected_at: "2026-07-24"

# Опц.: находки по отложенным условиям (conditions@2: report_published / event; forecast-monitor Шаг 1c).
# Монитор условия не пишет — задача hub-notify переносит находку в conditions-state.json (event_found + fired).
condition_findings:
  - condition_id: "c-2026-10-19-ru000a106ep1-1"
    version: 1
    doc: "https://e-disclosure.ru/..."   # null — не найдено
    found_at: "2026-11-12"               # дата публикации события; null — не найдено
    note: "ПР-Лизинг опубликовал МСФО за 9 месяцев 2026"

caveats:
  - severity: INFO
    message: "Web search budget на эту неделю — 8 запросов; использовано 5."
```

**Правила:**
- `alerts` — массив, может быть пустым.
- `severity: HIGH` — требует внимания пользователя на этой неделе.
- `severity: INFO` — информационное, viewer показывает свернутым.
- `target_file` — относительный путь от `Claude-Memory/`. Viewer использует для ссылок.
- `category` определяет иконку и группировку в Watchlist.
- `freshness_audit` — обязателен; viewer выводит таблицей.
- `predictions.overdue_list` — список просроченных предсказаний с днями просрочки.
- `condition_findings` — опционально; по строке на искомое условие (`{condition_id, version, doc, found_at, note}`);
  найдено — `doc` и `found_at` заполнены; не найдено — оба `null` (честное «не нашли», не «не вышло»). Прежнее поле
  `condition_events` упразднено: `validate-monitor-report` его блокирует.
- `monitoring_checked` и `alerts[].monitoring_id` — каждый пункт `monitoring[]` активного файла (при `scope: partial` —
  файла из `checked`) с `check_date` не позже даты `generated_at` отражён алертом с тем же `monitoring_id` и целью
  (`target_file` или `target`) или строкой `monitoring_checked`, а пункты прогноза с алертом `horizon_passed` (та же
  цель) — этим алертом; иначе `validate-monitor-report --root` — blocking
  (отчёты с `generated_at` до 2026-11-05 не проверяются; без `--root` — warning). `monitoring_id`, которого нет в
  `monitoring[]` цели, — warning.
- `outcome_log_updates` — опционально; заполняется только на резолве. Монитор не пишет
  forecasts напрямую (D3) — только захватывает факт; запись делает save-to-library Workflow L
  (`complete-outcome-log` считает `error_pct`/`in_p10_p90`).

---

## 8b. `stale_flags.yaml` — упразднён (шаг 14 цикла машиночитаемости)

Файла нет: свежесть прогноза читатели (монитор, макроцепочка) считают по датам самого прогноза
(`forecast.date`, горизонт); «горизонт прошёл» ставит `monitor_alerts.py` (алерт `horizon_passed`, поля
`horizon_date`/`horizon_passed` строки файла); пробой порога — алерт `factor_breach` отчёта монитора.
Прежний файл архивирует `archive_pre_ds.py`; из рабочей папки удаляется при переключении.

---

## 9. Domains в прогнозах

| domain | Описание |
|---|---|
| `geopolitics` | геополитика, войны, санкции |
| `ru-macro` | макро РФ: ставка ЦБ, инфляция, курс, Brent |
| `ru-sellside` | российский sell-side |
| `global-banks` | глобальные банки, GS, JPM и т.п. |
| `tech-ceo` | tech CEO, выступления |
| `commodity-agencies` | EIA STEO, ОПЕК+ |

---

## 10. Решение по бумаге `decision@1` (`Portfolio/decisions/*.json`)

Схема — `docs/investment/_cross-cutting/data-structures/schema.md` §3.1, валидатор — `ds_schemas.validate_decision`
(`assemble_artifact.py validate-decision`). Один JSON на запись, имя файла = `id` = `{ГГГГ-ММ-ДД}T{ЧЧММ}-{KEY}`; пишет
**только скрипт** `save-to-library` `decision_write.py` (`from-report` по блоку `decisions:` шапки отчёта, `owner` по
слову владельца); существующий файл не перезаписывается.

```json
{"schema_version": "decision@1", "id": "2026-10-29T1740-GMKN", "key": "GMKN",
 "verdict": "HOLD", "target_pct": null, "review_by": "2026-12-15", "note": "одна фраза «почему»", "confidence": 0.7,
 "conditions_created": [], "conditions_resolved": ["c-2026-10-19-gmkn-1"],
 "source": {"kind": "report", "doc": "Portfolio/reports/2026-10-29-single-analysis-gmkn.md", "mode_codes": ["4a"],
            "stress_id": "stress-2026-10-04-geopol-ru-west-shell-d1"},
 "author": "model", "recorded_at": "2026-10-29T17:40:00+03:00"}
```

Модель заполняет `verdict` (единый словарь, кодлист `verdict` без legacy), `target_pct` (% портфеля или null),
`review_by` (дата 7–180 дней от записи или null = 60 дней), `note` (≤ 200), по желанию `confidence`; остальное — скрипт:
`conditions_resolved` = сработавшие (`fired`) условия ключа модулем (а) минус `keep_open`, `conditions_created` —
`--created`, `source.kind` ∈ `decision_source`. Гейт и класс бумаги в решении не хранятся.

**Блок `decisions:` в шапке отчёта `report@1`** (вход `decision_write.py from-report`, проверка — `validate-report`):

```yaml
decisions:
  - key: GMKN            # из tickers[] шапки
    verdict: HOLD
    target_pct: null
    review_by: "2026-12-15"
    note: "…"
    confidence: 0.7      # необязательно
    keep_open: []        # необязательно: сработавшие условия, которые решение не закрывает
```

После записи блок кодом не читается (срез): источник истины — `Portfolio/decisions/`.

## 10а. `gate-reviews@1.0` — УПРАЗДНЁН (schema.md §4.4)

Писателя нет (`apply_gate_review.py`, `auto_maintain_gate_reviews.py` удалены в шаге 8), читателей в коде сайта и
скиллов нет (шаги 10–13); статус гейта считает модуль (б) `last_word.py` / `last-word.js` из последнего решения (§10) по
таблице `verdict_to_gate` кодлистов. Файлы `gate-reviews.yaml` и `gate-reviews-archive-{year}.yaml` лежат в архиве
`_archive/data-structures/` и удаляются из рабочей папки при переключении (шаг 17). Прежняя форма — в архивной копии и в
истории git этого файла; необязательный слой `gate_reviews` в `validate_library.py` без файла пропускается.

## 10б. Определения условий `conditions@2` (`Portfolio/conditions.yaml`)

Схема — schema.md §3.2, валидатор — `ds_schemas.validate_conditions_file`; пишет **только скрипт** `apply_condition.py`
(save-to-library, `add`/`edit`/`withdraw`; корень `--root`; временный файл + `os.replace`). Правка = новая запись с тем
же `id` и `version+1`, прежняя получает `superseded_by`; снятие = `withdrawn`; удаления нет.

```yaml
schema_version: conditions@2
conditions:
  - id: c-2026-10-19-ydex-1          # старые id — как есть
    version: 1
    key: YDEX                         # тикер или ISIN
    kind: review                      # кодлист condition_kind: review | trade | watch
    trigger: {type: report_published, value: "МСФО 3К", window_end: "2026-11-03"}   # окно = ожидаемая дата + 3 дня
    event_text: "МСФО Яндекса за 3 квартал"   # необязательно
    while_pending: {verdict: HOLD, target_pct: null, text: "…"}
    on_trigger: {action: run_analysis, text: "…", branches: [{if_text: "…", then: {verdict: ADD, action: set_target_pct, target_pct: 10, text: "…"}}], otherwise: {…}}
    on_expiry: null
    not_before: null
    valid_until: "2026-11-30"
    note: "почему создано"            # ≤ 200, необязательно
    context: {plan_pct: 8.0, snapshot_id: "portfolio-2026-10-19", as_of: "2026-10-19"}
    source: {kind: report, doc: "Portfolio/reports/…md", decision_id: null}
    created_at: "2026-10-19T17:40:00+03:00"
    created_by: mode_4                # кодлист actor
    withdrawn: null                   # или {at, by, reason}
    superseded_by: null               # или "id@version"
```

Типы триггера — кодлист `condition_trigger_type` (`date`, `price_below`, `price_above`, `report_published`,
`gate_expired`, `forecast_breach`, `event`); действия — `condition_action`: `run_analysis` (разобрать), `set_verdict`
(вердикт обязателен — на экране словом вердикта), `set_target_pct` (доля), `notify_only` (только сообщить),
`reinvest` (с 03.11, R30: деньги от погашения/оферты/купонов/продажи — в другую бумагу или корзину):

```yaml
    on_trigger: {action: reinvest, target: "ОФЗ/>10", amount_source: redemption, text: "погашение → реинвест в ОФЗ длиннее 10 лет"}
```

У `reinvest` обязательны `target` (корзина облигаций — кодлист `bond_bucket`, коды = ключи `plan.json`
`bond_buckets[].key`; или ключ бумаги) и `text`; `verdict` и `target_pct` запрещены; `amount_source` — кодлист
`reinvest_source` (`redemption`, `offer`, `coupon`, `sale`), необязателен. У облигации с датным триггером в день
погашения или позже `set_verdict` «держать/докупать» — ошибка `apply_condition.py add|edit|validate` (дата погашения
из снапшотов корня): после погашения бумаги нет, нужен `reinvest`. Удалено из 1.2: `state`, `fired_date`,
`touched`, `history[]`, `on_trigger.set_status` (состояние — §10в). Годовой архив — `conditions-archive-{ГГГГ}.yaml` той же
формы.

## 10в. Состояние условий `conditions-state@1` (`Portfolio/conditions-state.json`)

Схема — schema.md §3.3, валидатор — `ds_schemas.validate_conditions_state`; пишет **только hub-api** (сайт — `POST
/api/pv/cond/event`; уведомитель и задачи NAS — внутренний маршрут). Только дописывание; `at` ставит сервер.

```json
{"schema_version": "conditions-state@1",
 "events": [{"condition_id": "c-2026-10-19-ydex-1", "version": 1, "event": "fired",
             "at": "2026-11-03T08:30:00+03:00", "by": "notifier",
             "data": {"by_deadline": true, "note": "не найдено"}}]}
```

`event` — кодлист `condition_event`: `fired`, `expired`, `event_found` (от монитора — вместе с `fired`; от владельца —
кнопка «вышел» у ждущего `report_published`/`event`, сам даёт «сработало», R32), `owner_mark` (`data.mark` ∈ `dismissed` |
`deferred` + обязательная `data.until`), `reopened` (только `by: owner`), `done` (нужен `data.decision_id`,
`trade_date` или `note`). Статус условия считает только модуль (а) `conditions_merge.py` / `conditions-merge.js`.

## 10г. Справочник бумаг `security-attrs@1` (`Portfolio/security-attrs.json`)

Схема — schema.md §4.8, валидатор — `ds_schemas.validate_security_attrs`; пишет **только скрипт** `security_attrs.py set`
(save-to-library Workflow Q).

```json
{"schema_version": "security-attrs@1",
 "by_key": {"YDEX": {"ticker_class": "bluechip", "listed_at": "2024-07-24", "note": "переезд, не IPO",
                     "updated_at": "2026-10-31T12:00:00+03:00", "updated_by": "owner"}}}
```

Все пять полей обязательны у каждой записи; `ticker_class` (кодлист `ticker_class`) и `listed_at` могут быть `null`.
`ticker_class: ipo` + `listed_at` + 8 кварталов > сегодня → IPO-пауза докупки при любом вердикте.

## 10д. Кодлисты `codelists@1` (`codelists.json`, общий модуль репозитория)

Схема — schema.md §3.4. Пишет разработчик в репозитории; на сайт и в hub-api едет деплоем, в скиллы — `pack.sh`.
Форма: `{"schema_version": "codelists@1", "lists": {"<имя>": {"<КОД>": {"ru": "…", "short": "…", "since": "…"}}},
"maps": {…}, "defaults": {…}}`. Загрузчики — `codelists.py` и сгенерированный `tools/assets/codelists.js`; копия
перечня вне JSON роняет `test_codelists.py`. Временные поля до переключения: `migrate_to` у legacy-кодов, `weekly` у
`verdict`.

---

## 11. Schema v2 (Phase 4 — multiple horizons + Monte Carlo)

> **Что и зачем.** Phase 4 — единственная фаза с breaking changes: synchronous
> schema bump v1 → v2 для `weekly-review-stock`, `weekly-review-bond` и `stress`.
> Цель: считать **несколько горизонтов** (12/20/36 мес) side-by-side вместо
> прошитых 20 мес (V2-A) и заменить аналитический CI на **Monte Carlo** с общим
> розыгрышем сценария на path (V2-B). Решения D4-1…D4-9 — в
> `docs/investment/_cross-cutting/phase-4-v2-plan.md`.
>
> **Backward-compat (D4-4).** 23 боевых v1-артефакта НЕ мигрируются. Consumers v2
> принимают v1-вход и авто-оборачивают его как `{h20: …}`. Валидаторы
> маршрутизируют по `schema_version`: v1 → существующие валидаторы (не трогаются),
> v2 → новые. Новые артефакты пишутся только v2.
>
> **Ключи горизонтов — строки `h<NN>`** (`h12`, `h20`, `h36`), не int-ключи YAML.

### 11.0 Общие top-level поля v2 (weekly-review и stress)

```yaml
schema_version: 2
horizons: [6, 12, 24]              # отсортированный список уникальных int (месяцы); default [6, 12, 24]
horizon_ends:                      # детерминированно от якоря: +h мес, конец месяца
  h6:  '2026-12-31'
  h12: '2027-06-30'
  h24: '2028-06-30'
primary_horizon: 12                # ∈ horizons; default 12 («1 год»); к нему привязан advisor_verdict (D4-8)
horizon_mode: rolling              # rolling (default) | anchored
```

> **Default-набор горизонтов — `[6, 12, 24]`, `primary_horizon: 12`** (одна константа
> `DEFAULT_HORIZONS`/`DEFAULT_PRIMARY_HORIZON` в каждом producer/consumer, D4-9;
> перекрывается `--horizons` / `--anchor-dates`). Структурные примеры ниже (§11.1–11.2)
> показывают формат ключей `h<NN>` на произвольных значениях — это иллюстрация формы,
> не дефолт.

**`horizon_mode`** определяет семантику `horizons` и `horizon_ends`:

| Режим | Якорь | Семантика |
|---|---|---|
| `rolling` (default) | `review_date` / stress `date` | Даты скользят с каждым прогоном: `horizon_ends[hNN] = якорь + NN мес (конец месяца)` |
| `anchored` | то же поле | Фиксированные целевые даты; `NN` со временем уменьшается до наступления цели |

**Якорь:** для `type: portfolio-stress-test` — поле `date`; для weekly-review — поле `review_date`.

**Время записи (schema.md §4.2, §1 п.4) — только у weekly-review v2:**

```yaml
recorded_at: '2026-10-31T12:34:56+03:00'   # момент записи файла, МСК с поясом; ставит скрипт сохранения по часам
recorded_at_estimated: true                # только у мигрированных старых обзоров: время оценено (review_date + T00:00:00+03:00)
```

Новому обзору `recorded_at` ставит скрипт, флага `recorded_at_estimated` у него нет. Валидаторы обзора неизвестные
верхнеуровневые ключи не отклоняют, оба ключа принимаются (держит `tools/tests/test_time_msk.py`).

**Шапка отчёта советника `Portfolio/reports/*.md` (`report@1`, schema.md §4.3):** `schema_version: report@1`,
`mode_codes: [...]` (главный код первым; список кодов — `codelists.json`, список `mode_codes`), `tickers: [...]`
(ключи: тикер акции/фонда или ISIN облигации), `recorded_at` (МСК с поясом) и `recorded_at_estimated` (как выше).
Старые поля (`mode`, `created_at`) остаются; `created_at` — оценка модели, `recorded_at` — время записи. Проверка —
`assemble_artifact.py validate-report` (блокирующая; обязательны `schema_version`, `title`, `date`, `kind`, `mode_codes`,
`tickers`, `recorded_at`; `kind` и `mode_codes` без legacy-кодов); необязательный блок `decisions:` — §10.

`horizon_ends[hNN]` в режиме `rolling` вычисляется детерминированно: якорь + `NN` месяцев,
округлённое до **конца месяца**. Допуск при валидации — ±5 дней. В режиме `anchored` даты
задаются явно через `--anchor-dates` и должны строго возрастать. Хардкод дат в rolling запрещён.

### 11.1 weekly-review v2 (stock и bond)

```yaml
schema_version: 2
type: weekly-stocks-review         # | weekly-bonds-review (без изменений)
review_date: '2026-06-15'
horizons: [12, 20, 36]             # §11.0
horizon_ends: {h12: ..., h20: ..., h36: ...}
primary_horizon: 20
horizon_mode: rolling              # rolling (default) | anchored — §11.0
# УДАЛЕНЫ в v2: horizon_months, horizon_end, horizon  (drift-check ловит — §11.4)

per_stock:                         # структура НЕ меняется, кроме catalyst[].in_horizon
  <TICKER>:
    catalyst:
    - id: ...
      kind: binary | quantitative
      date_window: '2026-07'       # ОБЯЗАТЕЛЬНОЕ в v2; форматы — §11.3
      # УДАЛЕНО в v2: in_horizon — consumer вычисляет из date_window детерминированно
      ...остальные поля catalyst без изменений (METH-1: p/upside_pct/upside_by_scenario/…)
```

- `div_yield_12m_pct` / `ytm_pct` остаются **годовыми** — горизонтное
  масштабирование всегда было на стороне consumer (`× h/12`), не меняется.
- **`dividend_forward` (Слой 3 total-return, 2026-07, опциональный блок per_stock):**

  ```yaml
  dividend_forward:
    policy_state: declared | expected | suspended | none | uncertain
    year1_yield_pct: 11.0        # ТОЛЬКО при declared/expected (fwd на текущую цену, 0-12 мес)
    year2_yield_pct: 10.0        # при year2_basis analyst|carry_forward (12-24 мес)
    year2_basis: analyst | carry_forward | none
    source: "решение СД 2026-06-20"
    as_of: "2026-07-01"          # старше 8 недель от review_date → stale-warning
    confidence: HIGH | MEDIUM | LOW   # declared=HIGH, expected=MEDIUM, carry_forward=LOW
    note: "2026 declared 11% (СД), 2027 expected ~10% (аналитик)"
  ```

  Гейт: вклад дают ТОЛЬКО declared/expected; suspended/none/uncertain с ненулевым
  yield → BLOCKING («не оживает»); `uncertain` ≠ `none` (неизвестно vs решение не
  платить) — обязательна note-пометка ПРОПУСКА. Consumer (`aggregate_positions.py`)
  предпочитает блок `div_yield_12m_pct`-полю; год 3+ = carry_forward года 2 с флагом.
  Backward-compat: отсутствие блока валидно, старый путь работает.
- **`week_note` и `confidence_basis` (план переосмысления вьюера, 2026-10-26; per_stock и per_bond,
  необязательные):**

  ```yaml
  week_note:                     # пишет render_weekly_md.py --embed-notes из фрагмента бумаги в changes.md
    what_happened: ["23.10: IR подтвердил восстановление доступа к данным Cloud.", "…"]
    recommendation: ["держать 9% без добора"]   # [] или null, если во фрагменте нет
    macro_link: "удары по ЦОД — прямой фактор, ставка вторична"   # или null
  confidence_basis: "один источник, отчёт не вышел"   # что снижает advisor_verdict_confidence; null при ≥ 0,8
  ```

  `week_note` описывает одну неделю: `carry_over_weekly.py` его не переносит, бумага без фрагмента поля не
  несёт; форма при наличии строгая (валидатор `_week_note_and_confidence_checks`: списки непустых строк,
  только три ключа). `confidence_basis` — строка или null; незаполненный TODO_LLM из стаба блокирует,
  уверенность ниже 0,8 без причины — warning. Вьюер: «Что произошло за неделю» и «уверенность низкая: …»
  в карточке (без полей — обоснование вердикта предложениями, как раньше).
- `per_bond` v2 — аналогично: top-level §11.0, `catalyst[].in_horizon` удалён,
  остальное без изменений.
- `advisor_verdict` остаётся **один на позицию** (D4-8), семантически привязан к
  `primary_horizon`. Per-horizon вердиктов НЕ плодить.

### 11.2 stress v2

```yaml
schema_version: 2
type: portfolio-stress-test
date: '2026-06-15'
horizons: [12, 20, 36]             # §11.0
horizon_ends: {h12: ..., h20: ..., h36: ...}
primary_horizon: 20
horizon_mode: rolling              # rolling (default) | anchored — §11.0
portfolio_snapshot_id: portfolio-....json
baseline_spot: {...}               # ЕДИНЫЙ на все горизонты (без изменений)

scenarios:
  A:
    name: ...
    p: 0.25
    factors_by_horizon:            # БЫЛО: factors (один набор)
      h12: {brent: -10.0, cbr_rate: -2.0, usdrub: 8.0, ...}   # единицы — §5.6
      h20: {...}
      h36: {...}
    portfolio_level_by_horizon:    # БЫЛО: portfolio_level (опц.)
      h12: {delta_rub: ..., expected_pct_pweighted: ...}
      ...

per_position:
  <TICKER>:
    weight_pct: ...
    on_iis: ...
    factor_betas: {...}            # ПЛОСКИЕ — месячные беты SS-1, от горизонта НЕ зависят
    factor_betas_method: ...
    factor_betas_r2: ...
    by_horizon:                    # НОВОЕ: всё горизонт-зависимое сюда
      h12:
        delta_pct_by_scenario: {A: {value, ci_pct}, ...}
        expected_pct_pweighted: {value, ci_pct}
        tail_var_pct: ...
        tail_var_scenario_id: ...
      h20: {...}
      h36: {...}
    macro_blindspot: ...           # горизонт-независим (R²-критерий), плоский
```

**Total return (2026-07) — три аддитивных дополнения stress v2:**

1. **`baseline_spot` обязателен** (стаб копирует из `macro-scenarios-{date}.yaml`).
   Потребители: L1-overlay integrated-view (MFC-4) и `compute_bond_carry.py`
   (уровень КС). Отсутствие → warning валидатора (L1 молча деградирует в L2).
2. **Maturity guard (Слой 1):** облигация с `min(offer_date, maturity_date)` ≤
   конца горизонта получает в срезе `by_horizon.hNN` нулевые
   `delta_pct_by_scenario` + поля `price_delta_zeroed: maturity_within_horizon`
   и `t_live_months`. Переоценка несуществующей бумаги = двойной счёт с carry.
3. **Блок `bond_carry` (Слой 2, top-level, опционален)** — выход
   `compute_bond_carry.py` (купоны по факт. расписанию + pull-to-par + реинвест
   тела по сценарной траектории КС + FX на купоны/тело + MM/кэш по КС−1пп):

```yaml
bond_carry:
  schema: bond-carry@1
  as_of: '2026-07-02'
  baseline_cbr_rate_pct: 14.25
  params: {fx_reinvest_rate_pct: 5.0, sanctions_haircut: 0.25, mm_spread_pp: 1.0, ...}
  per_position:
    <ticker|ISIN|CASH_RUB>:
      kind: bond | money_market | cash
      event_date: '2027-06-29'            # min(offer, maturity) | null
      by_horizon:
        hNN:
          t_live_months: 11.89
          matures_within: true            # тело в carry → цена ОБЯЗАНА быть обнулена
          by_scenario:
            A: {carry_pct: 41.01, ci_pct: [36.9, 45.1],
                components: {coupons: 3.09, pull_to_par: 3.09, fx_income: 34.74,
                             reinvest: 0.09, sanctions_haircut: -1.2}}  # аддитивны
          expected_carry_pct: 29.48       # p-weighted
          flags: [reinvested, floater_coupon_adjusted, ...]
      flags: [credit_review_required, eur_fx_proxy_usdrub, ...]
  caveats: [...]                          # ≥1 HIGH (немоделируемое: реинвест купонов и т.д.)
```

Валидатор E3: orphan scenario-ID в ячейках → BLOCKING; `matures_within` при
живом `price_delta` → BLOCKING `double_count_risk`; обнулённая цена без
carry-блока → warning. Consumer — `portfolio-integrated-view`
(`aggregate_positions.py`: приоритет над legacy R-BOND-CARRY, MC-сэмплинг
по разыгранному сценарию, `total_return_by_horizon`).

**Откуда per-horizon факторы (D4-3).** `factors_by_horizon[hNN]` строит
детерминированный хелпер `compute_horizon_factors.py` (в `portfolio-scenario-stress`)
из **per-year уровней FCA** (механика MFC-4): уровень года, ближайшего к
`as_of + h месяцев`, → % против `baseline_spot` по контракту §5.6. Если уровень
нужного года отсутствует — берётся ближайший доступный, CI инфлируется
**×√(h_target / h_source)**, пишется warning. Никакой ручной арифметики у LLM.

### 11.2a Контракт баз расчёта stress v2 (basis contract)

За 17 прогонов (2026-05-11…2026-09-18) портфельный уровень стресса менял
имена/состав 4 раза, при этом одни и те же имена значили разную базу
(price-only vs price+carry) — сравнение двух прогонов давало ложный вывод
«доходность ушла в минус», хотя менялась только база. Разбор и полная спека
задачи — `docs/investment/task-stress-basis-contract.md`. Ниже — контракт как
часть схемы v2; проверяет его `scripts/validate_stress_output.py`.

**Две базы.** `price` = Layer 1 (переоценка позиций, `per_position.*`).
`total_return` = Layer 1 + Layer 2 (`price + bond_carry`). Дивидендов в стрессе
нет (`layers_included.dividends` всегда `false` — див-слой живёт в
weekly-review, полную доходность из трёх слоёв собирает `portfolio-integrated-view`).
**Инвариант:** `per_position` — ВСЕГДА `price`; total-return `portfolio-integrated-view`
считает сам из `per_position` + `bond_carry.per_position` — класть в `per_position`
готовую полную доходность нельзя, купон задвоится.

```yaml
# top-level, рядом с schema_version
basis_contract: 1                 # версия контракта баз; инкремент при смене имён
layers_included: {price: true, bond_carry: true, dividends: false}  # dividends — всегда false
per_position_basis: price         # инвариант
base_value_rub: 45060969          # знаменатель ВСЕХ pct-полей, считать один раз
base_value_note: "holdings unblocked + кэш; blocked исключены"
p_basis: primary_horizon | mean_across_horizons   # что значит скаляр scenarios.<X>.p

scenarios:
  A:
    portfolio_level_by_horizon:
      h12:
        price_delta_rub: -94362
        price_delta_pct: -0.63
        carry_rub: 3462924
        carry_pct: 7.69
        total_return_rub: 3179838   # == price_delta_rub + carry_rub, ±1 ₽
        total_return_pct: 7.06

portfolio_aggregates:
  price:
    basis: price
    expected_pl_rub_by_horizon: {h6: ..., h12: ..., h24: ...}   # null допустим при
    expected_pl_pct_by_horizon: {h6: ..., h12: ..., h24: ...}   # weight_type: equal без --include-ev
    pl_range_rub_by_horizon:
      h12: {min: ..., max: ..., min_scenario: "A", max_scenario: "D"}
  total_return:
    basis: total_return
    # та же форма

robustness:
  price:
    basis: price
    by_horizon:
      h12: {positive_or_neutral_scenarios: 4, worst_case: {id: A, pl_pct: -0.63},
            best_case: {id: D, pl_pct: 15.55}, spread_pct: 16.18}
  total_return:
    basis: total_return
    by_horizon: {...}
  modal_scenario: "none"            # от базы не зависит
  hedge_target: "..."                # от базы не зависит

sector_breakdown_basis: price        # sector_breakdown_pct всегда из per_position → всегда price
```

**Запрещено в новых файлах** (валидатор отклоняет): скаляры `delta_rub`,
`expected_pl_rub`, `portfolio_pl_range_rub`, `total_return_by_horizon_rub` на
портфельном уровне; `l1_price_only_delta_rub`/`l1_price_only_pct`; голый
`expected_pct_pweighted` в `portfolio_level_by_horizon` (внутри `per_position`
легитимно); плоский (без базы) `robustness`. Архивные файлы ДО `basis_contract`
эти имена несут законно — читать их только через
`scripts/normalize_stress.py` (не написан на 2026-09-18, задача 4), руками не
интерпретировать.

Допуски: денежные ±1 ₽, процентные ±0.01 п.п., агрегатные сверки снизу вверх
±0.5% от `base_value_rub`, сумма вероятностных весов на горизонте ±1e-6.

### 11.3 Контракт `date_window` (детерминированный in-horizon)

В v2 `catalyst[].in_horizon` удалён — принадлежность катализатора горизонту `h`
вычисляет consumer из `date_window`. Принимаемые форматы (толерантный парсер,
регистронезависимо):

| Форма | Пример | Интерпретация начала окна |
|---|---|---|
| `YYYY-MM` | `2026-07` | 1-е число месяца |
| `YYYY-MM-DD` | `2026-07-15` | сама дата |
| `YYYY` | `2027` | 1 января года |
| `YYYY-Qn` | `2026-Q3` | 1-е число первого месяца квартала |
| диапазон `A..B` / `A—B` / `A - B` | `2026-Q4 .. 2027-Q2` | начало = начало левой стороны |

**Правило:** катализатор «в горизонте `h`», если **начало окна ≤ `horizon_ends[h]`**.

**Непарсибельный `date_window`** → катализатор считается в горизонте на ВСЕХ
горизонтах + warning `date_window_unparseable` (консервативно: сохраняет
v1-поведение, где `in_horizon: true` ставил LLM).

### 11.4 Что удалено в v2 (вход для drift-чеков валидаторов)

| Поле | Где было (v1) | Чем заменено (v2) |
|---|---|---|
| `horizon_months` | top-level weekly/stress | `horizons` + `primary_horizon` |
| `horizon_end` | top-level weekly-stock | `horizon_ends.hNN` |
| `horizon` | top-level weekly-bond / stress | `horizon_ends.hNN` |
| `in_horizon` | `catalyst[]` | вычисляется из `date_window` (§11.3) |
| `scenarios.X.factors` | stress | `scenarios.X.factors_by_horizon` |
| `per_position.X.delta_pct_by_scenario` (и др. горизонт-зависимые) | stress top-level позиции | `per_position.X.by_horizon.hNN.*` |

Присутствие любого из удалённых полей в файле с `schema_version: 2` → BLOCKING
issue `v1_field_in_v2` (анти-möbius drift-чек).

### 11.5 Monte Carlo блок в output integrated-view (D4-5/6/7)

`aggregate_positions.py` v2 заменяет аналитический CI на Monte Carlo (stdlib
`random`, БЕЗ numpy). Детерминизм через сид. Output несёт:

```yaml
ci_method: mc                      # mc (default) | analytic
mc:
  paths: 10000                     # число путей (--mc-paths)
  seed: 42                         # сид (--mc-seed); сид+paths детерминируют output
```

- **Модель корреляций (D4-6):** в каждом path сценарий `s ~ p_norm` разыгрывается
  ОДИН раз и используется всеми позициями/катализаторами → когерентные «миры»
  (нет mixed-worlds). Явного `corr_matrix` НЕТ.
- **Точечные значения (D4-7):** остаются **аналитическими** (текущие формулы Σ не
  трогаются). MC считает только CI (перцентили P2.5/P97.5), spread CI и
  портфельные хвосты (P5/P95). Guard `mc_divergence`: при
  `|mean(MC) − analytic| > 1.5 п.п.` по портфелю → warning.
- **spread CI:** в v2 (`ci_method: mc`) поля `ci_linear`/`ci_quadratic` заменяются
  единым `ci` из joint-сэмплов. В режиме `--ci-mode analytic` остаётся прежняя пара.

### 11.6 Скользящий vs якорный горизонт (consistency с прогнозным слоем)

`horizon_ends[hNN]` — **источник истины** (конкретные даты). Эффективный срок для
масштабирования доходности = `month_diff(review_date, horizon_ends[hNN])`
(календарная разница в месяцах). Это даёт согласованность с прогнозным слоем,
который тоже заякорен на даты (`forecast.horizon: YYYY-MM-DD` + per-year levels).

Два режима — **дуальность на стороне producer'а**, движок consumer'а один:

| Режим | Producer фиксирует | Поведение во времени | Когда |
|---|---|---|---|
| **Скользящий** (default) | список `N` (`--horizons 12,20,36`) | дата = `review + N` едет вперёд; срок постоянный | стоячий «forward N-мес» взгляд, сравнимость недель, diff IV-A |
| **Якорный** | даты-цели (`--anchor-dates 2027-06-30,…`) | дата стоит; остаток сжимается 10→9→8; доходность пересчитывается | согласование с конкретным прогнозом/датой |

**Якорный режим** = producer детерминированно считает `N = month_diff(review_date,
target)` (без ручной арифметики у пользователя), ставит `horizons = [N…]`,
`horizon_ends[hN] = target`. На следующем прогоне с той же датой-целью `N`
уменьшается → carry/div (`× N/12`) и аннуализация (`× 12/N`) пересчитываются,
а **точка прогноза стоит** и макро всегда читает тот же per-year уровень FCA
(нет «прыжка» на стыке лет, который был бы у скользящего окна).

**Требование viewer (Этап 5):** показывать `horizon_ends[hNN]` (дату) рядом с
каждым горизонтом — пользователь должен видеть, к какой дате относится прогноз,
а не только «h20».

**effective_months в consumer'е:** для скользящего `month_diff(review, review+N) = N`
(бит-в-бит совпадает с нумерацией ключа). Для v1-входа (нет `horizon_ends`) —
fallback на номинальный `N` из ключа `hNN` / `horizon_months`. Дата-зависимые
проверки (catalyst-in-horizon §11.3) всегда идут по `horizon_ends[hNN]`.
