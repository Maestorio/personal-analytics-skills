# MACRO-INPUT YAML Schema (Output Contract, Шаг 8b)

Полная аннотированная схема файла `macro-input-{date}.yaml`. Это **выходной артефакт** скилла macro-forecast-chain, и одновременно **входной контракт** для portfolio-scenario-stress.

## Файл: macro-input-{date}.yaml

```yaml
# MACRO-INPUT-{date}.yaml
schema_version: 2                 # 2 = несёт forecast_files (обязателен); старые файлы — 1, без ссылки
run_id: "MFC-{YYYYMMDD-HHMM}"
generated: {ISO datetime}
portfolio_snapshot: "portfolio-{snapshot_date}.json"
mode: FULL | QUICK-REFRESH | PARTIAL
coverage_score: N/M

# Ссылки на прогнозы (schema.md §4.6): {фактор: имя файла forecasts/<имя>.yaml без расширения}.
# Печатает scripts/check_source_files.py --forecast-files из source_files факторов — руками не собирать.
# Версии прогнозов не копируются: «есть новее» вьюер видит по superseded_by самого прогноза.
forecast_files:
  sanctions: "sanctions-2026-05-02"
  brent: "brent-2026-04-30"
  cbr_rate: "cbr-rate-2026-04-28"

factors:
  geopolitics:
    status: FRESH | STALE | ACCEPTED_STALE | ACCEPTED_MISSING
    type: scenario_matrix         # geopolitics — Shell-матрица 4 сценариев
    central_estimate: "{label модального сценария}"
    modal_scenario_id: "Sc-A"
    modal_probability: 0.30
    all_scenarios:                # копия из scenario-builder результата
      - {id: "Sc-A", label: "...", probability: 0.30}
      - {id: "Sc-B", label: "...", probability: 0.28}
      - {id: "Sc-C", label: "...", probability: 0.22}
      - {id: "Sc-D", label: "...", probability: 0.20}
    axes:                         # если scenario-builder зафиксировал оси
      conflict_intensity: 0.60    # ожидаемое значение по распределению
      sanctions_intensity: 0.55
    date: YYYY-MM-DD
    confidence: 0.XX
    source_file: "scenarios/geopolitics-2026-04-15.yaml"   # у матрицы — одно поле source_file; у остальных факторов — список source_files

  sanctions:
    status: FRESH
    type: single_estimate
    central_estimate: "Текущий режим сохраняется без ужесточения к 2026-12-31"
    date: 2026-05-02
    confidence: 0.58
    source_files: ["forecasts/sanctions-2026-05-02.yaml"]   # точные файлы, из которых взяты числа (Layer 1 и Layer 2)
    geopolitics_translation:
      method: axis_dependent      # см. dependency-map.md
      axis: "sanctions_intensity"
      axis_value_used: 0.55

  brent:
    status: FRESH
    type: single_estimate
    central_estimate: "$88/b к 2026-12-31"
    date: 2026-04-30
    confidence: 0.40
    source_files: ["forecasts/brent-2026-04-30.yaml"]
    geopolitics_translation:
      method: nonlinear           # см. dependency-map.md
      modal_scenario_id: "Sc-A"
      modal_probability: 0.30
      alternatives_recorded: true   # см. alternatives ниже
    alternatives:                 # только для nonlinear-факторов (Шаг 5.2)
      - scenario_id: "Sc-B"
        probability: 0.28
        central_estimate: "$72/b"
        indicative: true
        sources_used: 3
      - scenario_id: "Sc-C"
        probability: 0.22
        central_estimate: "$108/b"
        indicative: true
        sources_used: 4
      - scenario_id: "Sc-D"
        probability: 0.20
        central_estimate: "$95/b"
        indicative: true
        sources_used: 3

  cbr_rate:
    status: FRESH
    type: single_estimate
    central_estimate: "12% к 2026-12-31"
    date: 2026-04-28
    confidence: 0.71
    source_files: ["forecasts/cbr-rate-2026-04-28.yaml"]
    geopolitics_translation:
      method: linear              # marginalization works
      distribution_used: true     # FCA получил все 4 сценария

  # ... остальные факторы

scenarios:
  - label: "Base"
    probability: 0.45
    factors:
      brent_pct_change: +8.0
      rate_bps_change: -200
      usdrub_pct_change: +6.0
      cnyrub_pct_change: +5.0
      sanctions_escalation: false
      geopol_escalation: false
      xauusd_pct_change: +5.0
      urals_discount_usd: 13.0
      cbr_rate_absolute: 15.0
      inflation_ru_pct: 7.5
  - label: "Stress-down"
    probability: 0.20
    factors: {...}
  - label: "Bull"
    probability: 0.15
    factors: {...}
  - label: "Tail-risk"
    probability: 0.05
    factors: {...}
  - label: "Unaccounted"
    probability: 0.15
    factors: null    # резерв на непредвиденное

caveats:
  - type: ACCEPTED_STALE
    factor: urals_discount
    stale_since: "2026-02-01"
    severity: medium
    note: "Принято пользователем 2026-05-02"
  - type: CONSISTENCY_WARNING
    factors: [brent, usdrub]
    severity: medium
    note: "Brent↑ + рубль↓. Объяснение: санкционный разрыв нефтяной премии"
  - type: LOW_CONFIDENCE
    factor: xauusd
    confidence: 0.48
    severity: low
    note: "Мало аудированных источников по золоту"
  # В режиме PARTIAL — каждый MISSING/STALE фактор пишется как явный data_gap:
  - type: DATA_GAP
    factor: inflation_ru
    status: MISSING
    severity: critical              # отсутствует upstream для cbr_rate и bonds
    impact_on_downstream: [cbr_rate, sector_banks, sector_bonds_rub]
    note: "PARTIAL mode: FCA не запускался. Stress-test cbr-зависимых
           позиций без этого фактора некорректен."
  - type: DATA_GAP
    factor: cbr_rate
    status: STALE
    stale_since: "2026-01-10"
    severity: medium
    note: "PARTIAL mode: используем устаревшее значение, но в разумных пределах."
  # Cascade-флаг: фактор сам FRESH, но upstream был пересобран — текущий прогноз
  # построен на устаревшем upstream-контексте.
  - type: STALE_UPSTREAM_CONTEXT
    factor: cbr_rate
    upstream: inflation_ru
    severity: medium
    note: "Прогноз cbr_rate FRESH (12% от 2026-04-28), но inflation_ru пересобран
           в этом run и сместился. cbr_rate стоит пересобрать в следующий FULL прогон."
  # nonlinear-фактор без блока by_scenario (deprecated/legacy YAML)
  - type: MISSING_BY_SCENARIO
    factor: brent
    severity: medium
    note: "Прогноз brent в legacy-формате без блока conditional_on_scenarios.by_scenario.
           Под D1 (Pure Shell, modal_scenario: none) downstream-стресс будет вынужден
           использовать медианный fallback по доступным значениям — это деградация
           tail-risk анализа. Рекомендация: пересобрать прогноз с 4 параллельными
           FCA-запросами (по одному на сценарий) и заполнить by_scenario."
  - type: ALTERNATIVES_NOT_RECORDED
    factor: usdrub
    severity: medium
    note: "nonlinear-фактор в weighted-режиме (modal_scenario != none): основной FCA
           на модальном сценарии собран, но alternatives на остальных 3 сценариях
           пропущены. Tail-risk анализ по альтернативным geopolitics-сценариям
           ограничен. Под D1 (no_modal) этот caveat не актуален — там используется
           by_scenario."

ready_for_stress_test: true | false | partial   # 'partial' — для PARTIAL-режима
blocking_issues: []                              # severity=critical data_gaps
mode: FULL | QUICK-REFRESH | PARTIAL
```

## Поле status (factor-level)

- **FRESH** — прогноз не старше пороговой даты для type (см. staleness-config.md)
- **STALE** — прогноз старше порога, но пользователь согласился его использовать в Checkpoint 1
- **ACCEPTED_STALE** — явное согласие пользователя (записано в caveat)
- **ACCEPTED_MISSING** — фактор отсутствует, но пользователь согласился обойтись без него (PARTIAL mode)

## Поле type (factor-level)

- **scenario_matrix** — многосценарный; используется для geopolitics
- **single_estimate** — точечный прогноз с одной центральной оценкой
- **proxy_estimate** — замена за отсутствующий фактор (редко; обычно DATA_GAP caveat)

## Поле geopolitics_translation (для nonlinear-факторов)

Показывает, как фактор зависит от geopolitics-сценариев:

- **method: linear** — фактор маргинализируется по всем 4 сценариям (simple approach)
- **method: axis_dependent** — фактор зависит от одной из осей (sanctions_intensity и т.п.)
- **method: nonlinear** — фактор уникален для каждого сценария (в alternatives)

## Поле scenarios (global)

Список всех сценариев и их P&L дельты по факторам. Вероятности должны суммироваться в 1.0.

## Поле caveats (global)

Реестр caveat-типов — единственное место, где они перечислены. Все расхождения, STALE прогнозы,
MISSING факторы и логические противоречия:

| Type | Содержит | Кто ставит |
|------|----------|-----------|
| ACCEPTED_STALE | Пользовательское согласие использовать устаревший прогноз | оркестратор |
| CONSISTENCY_WARNING | Логическое противоречие между двумя факторами (e.g. Brent↑ + RUB↓) | оркестратор (`consistency-rules.md`) |
| LOW_CONFIDENCE | Confidence < 0.55 или < 3 аудированных источников | оркестратор |
| DATA_GAP | Отсутствующий MISSING или стоящий STALE фактор (PARTIAL mode) | оркестратор |
| STALE_UPSTREAM_CONTEXT | Фактор FRESH, но его upstream был пересобран | оркестратор |
| MISSING_BY_SCENARIO | Nonlinear-фактор без блока conditional_on_scenarios.by_scenario; downstream-стресс деградирует к медианному fallback (medium) | оркестратор |
| ALTERNATIVES_NOT_RECORDED | Nonlinear-фактор без записанных alternatives для других сценариев (Шаг 5.2 пропущен, medium) | оркестратор |
| BROKEN_RECORD | `method: fca` + `confidence: null` — запись сломана (critical) | `coverage_report.py` |
| NO_CONFIDENCE | `method: manual / external_quoted` + `confidence: null` (medium) | `coverage_report.py` |
| LEGACY_FORMAT_NO_METHOD | в YAML отсутствует поле `method` (low) | `coverage_report.py` |
| LEGACY_FORMAT | `schema_version` прогноза не 1, нужна миграция | `coverage_report.py` |
| INSUFFICIENT_HORIZON | max_horizon < chain_target_horizons (medium при FRESH, critical при STALE) | `coverage_report.py` |
| VERY_STALE | возраст прогноза сильно выше порога — rebuild целиком | `coverage_report.py` |
| MONITOR_BREACH | `forecast-monitor` зафиксировал пробой фактора (`factor_breach`) — прогноз STALE | `coverage_report.py --monitor-report` |
| STALE_VS_SPOT | Центр ближайшего неистёкшего горизонта дальше порога от спота последнего макроснимка — прогноз STALE при свежей дате | `coverage_report.py --spot` (пороги — `staleness-config.md`) |
| MATRIX_REPLACED | Прогноз построен на заменённой матрице сценариев (`source_matrix` → файл с `superseded_by`) — STALE при свежей дате; пересобрать на действующей | `coverage_report.py --root` |
| UNMAPPED_ACCEPTED | тикер без фактора принят пользователем и исключён из required_factors | оркестратор (Шаг 1) |
| MISSING_SCENARIO_ATTRIBUTION | у прогноза нет ни `isolated`, ни `conditional_on_scenarios` — reject, фикс вручную | оркестратор (Шаг 1) |

## Поле ready_for_stress_test

- **true** — режим FULL, 0 critical issues
- **false** — режим FULL, есть critical caveats; portfolio-scenario-stress должна учесть их и предупредить пользователя
- **partial** — режим PARTIAL; matrix неполная, некоторые позиции не поддерживаются данными

## Числовые L1-поля в macro-marginal (MFC-4)

Парный артефакт `macro-marginal-{date}.yaml` (Layer 1) хранит оценки факторов как
человекочитаемые строки-уровни. Для downstream-арифметики `portfolio-integrated-view`
к каждому факторному блоку добавляются **машинные** поля — детерминированно, через
`scripts/compute_marginal_move.py` (Шаг 8b), без ручной арифметики у LLM:

```yaml
brent:
  central_estimate_l1_2026: "$68/bbl (JPMorgan-dominant weighted median)"  # источник
  level_l1_2026: 68.0        # числовой уровень (добавлено скриптом)
  level_l1_2027: 57.0
  unit: usd_per_bbl          # единица УРОВНЯ
```

| `unit` | Применимо к | Перевод уровень→движение (в consumer) |
|---|---|---|
| `usd_per_bbl` | brent, urals_discount | % от `baseline_spot.brent_usd` |
| `rub_per_usd` | usdrub | % от `baseline_spot.usdrub` |
| `rub_per_cny` | cnyrub | % от `baseline_spot.cnyrub` |
| `usd_per_troy_oz` | xauusd | % от `baseline_spot.xauusd_usd` |
| `rate_pct` | cbr_rate | Δ п.п. от `baseline_spot.cbr_rate_pct` |

Перевод уровень→движение выполняет **consumer** (`portfolio-integrated-view`) против
`baseline_spot` из stress — та же база, что у Layer 2, → осмысленный `coherence_gap`.
Контракт единиц (SSOT): `references/events-yaml-spec.md` §5.6.
Качественные факторы (geopolitics, sanctions) числового уровня не получают.

## Путь сохранения

Артефакт → save-to-library → `Claude-Memory/macro-chain/macro-input-{date}.yaml`

**Нижний регистр в пути и имени файла** (D4).
