# HANDOFF → Cowork: пофазный апгрейд данных в Claude-Memory

**Версия:** 2026-05-08, финальная после архитектурного обсуждения
**Парный документ:** `HANDOFF-claude-code-phased.md` (загружается вместе с этим файлом)
**Среда работы:** Cowork-сессия с доступом к Claude-Memory на Synology
**Корневой путь данных:** `/Users/you/Library/CloudStorage/SynologyDrive-home/Ext_gDrive/Claude-Memory/`
**Язык работы:** русский

---

# 0. Контекст для нового чата (читать первым)

## Кто пользователь и что у него есть

- **Профиль:** биостатистик, 7 лет на рынке, мат-стат, не профи индустрии, способен handle full detail.
- **Портфель:** MOEX (акции + облигации RUB/USD/EUR/CNY + фонды), ~13.5M RUB.
- **Хранилище данных:** `~/Library/CloudStorage/SynologyDrive-home/Ext_gDrive/Claude-Memory/` (Synology Drive, **БЕЗ git**).
- **Хранилище кода:** `~/Documents/Программы/claude_skills` (репо под git, доступно только Claude Code).
- **Две среды работы:** Cowork (этот документ) и Claude Code (парный документ). Пользователь передаёт оба файла в каждую среду.

## Что находится в Claude-Memory (рабочая поверхность Cowork)

```
Claude-Memory/
├── scenarios/         ← 4 активные scenario matrices
│   ├── scenario-geopolitics-ru-west-2026-05-04.yaml + .md
│   ├── scenario-brent-dec-2026-2026-04-30.yaml + .md
│   ├── scenario-usd-rub-sept-2026-2026-04-30.yaml + .md
│   └── scenario-ai-capex-scenarios-2026-2026-04-30.yaml + .md
├── forecasts/         ← ~22 forecast YAMLs (см. inventory ниже)
├── macro-chain/       ← macro-input-2026-05-04.yaml (текущая single-file версия)
├── audits/            ← retrospective audits
├── domains/           ← {domain}/{audit}.md иерархическая библиотека
├── INDEX.md           ← мастер-индекс trust-весов
└── _sync_log.md       ← лог saves
```

И отдельно (auto-memory, не в Synology, в Application Support):
```
.auto-memory/
├── lib_bcs_strategy_2025.md          ← compact source profile
├── lib_invest_era.md
├── lib_vtb_mi.md
├── lib_sbercib.md
├── lib_finam.md
├── lib_cbr.md
├── lib_stratfor.md
├── lib_chatham_house.md
├── lib_morgan_stanley.md
└── MEMORY.md
```

## Принципы работы

- **Корректность > читаемость > стоимость > скорость**
- Скиллы инвестиционного назначения **не дают buy/sell рекомендаций**, только аналитика
- Все правки в Claude-Memory с явным backup (`.pre-X` суффикс)
- Лог в `_sync_log.md` после каждой Phase

## Доступ к Claude-Memory

В новой Cowork-сессии Synology обычно НЕ автоматически смонтирован. Первое 
действие в каждой сессии:

```
mcp__cowork__request_cowork_directory(
    path="/Users/you/Library/CloudStorage/SynologyDrive-home/Ext_gDrive/Claude-Memory"
)
```

Bash-mount автоматически появится в `/sessions/{...}/mnt/Claude-Memory/`.

---

# 1. Архитектурный фундамент (общий с Claude-Code-документом)

## Что решает апгрейд

Текущая система прогнозов и сценариев имеет 4 структурных дефекта:

1. **Веса сценариев появлялись в чате без следа** (Sc-D=0.525 был экспромтом Claude в чате во время `macro-forecast-chain` 2026-05-03, не воспроизводимо)
2. **Conditional values смешаны с marginal** в одном файле `macro-input-{date}.yaml`
3. **Источники не атрибутированы по сценариям** — невозможен retrospective audit per-scenario
4. **Stress-test использовал mixed-worlds factors**: Brent с Sc-A worldview (Ормуз открыт) + USD/RUB с Sc-D worldview (sanctions hold) в одном bundle

## Двухслойная архитектура

```
LAYER 1 — MARGINAL FORECASTS (independent)
  • один FCA на фактор, trust-weighted на источниках
  • используется для weekly-review, EV, factor betas
  • выход: macro-marginal-{date}.yaml
  
LAYER 2 — SCENARIO BUNDLES (coherent)
  • 4 сценария, в каждом все факторы согласованы под worldview сценария
  • используется для stress-test, robustness check, hedge sizing
  • выход: macro-scenarios-{date}.yaml
```

## Двойной marginal в каждом forecast YAML

```
forecast.central_estimate                    ← Layer 1 marginal
                                                trust-weighted FCA, scenarios игнорируются
                                                ИСПОЛЬЗУЕТСЯ для портфельной EV
                                                
conditional_on_scenarios.marginal.values     ← Layer 2 marginal
                                                probability-weighted от by_scenario
                                                диагностика, не основа решений
```

Они расходятся, когда coverage асимметричный или один HIGH-trust источник доминирует.

## Три типа updates (после апгрейда)

| Type | Триггер | Что меняется | Время |
|------|---------|--------------|-------|
| **A — Weight-only** | leading_indicator сработал, новость, change of belief | только Layer 2 marginal + presentation labels | ~30 сек |
| **B — Factor baseline** | premise фактора сломалась | один factor's by_scenario + Layer 1 marginal этого фактора | ~30 мин (1 FCA) |
| **C — Structural** | оси сценарной матрицы устарели | вся scenario matrix + все conditional FCA | ~1–2 дня |

## 7 архитектурных решений (зафиксированы пользователем 2026-05-08)

| # | Решение | Что значит для данных |
|---|---------|------------------------|
| **D1** | `scenario-builder` выдаёт 0.25 каждому. Пользователь правит в SSOT. | В scenarios/{name}.yaml — все weights = 0.25. Custom веса = manual edit. |
| **D2** | `expected_pl_pct` удалить из default. | В stress YAMLs убрать поле или пометить deprecated. |
| **D3** | «Unaccounted» убрать. Заменить на `out-of-frame_caveats`. | В macro-input убрать «Unaccounted» из scenarios block. |
| **D4** | Trust 3D, Phase 2 — 2D (marginal+world). | В `lib_*.md` подготовить структуру для 3D, заполнить 2D. |
| **D5** | scenario_id формат `A` (короткий). | Миграция данных: `Sc-A` → `A` через regex. |
| **D6** | ρ correlation default 0. | В scenario YAMLs не записывать correlation_xy если используется default. |
| **D7** | Pure Lazy aggregation, RECALIBRATE как explicit команда. | В forecast YAMLs marginal может быть stale между RECALIBRATE-запусками. |

## Глоссарий

- **FCA** — Forecast-Confidence-Applier, скилл для filtered consensus из 3-7 источников
- **SSOT** — Single Source of Truth (для весов: `scenarios/{name}.yaml`)
- **Conditional value** — значение фактора, conditional на конкретный сценарий
- **Marginal value** — общее значение фактора без сценарной геометрии
- **Implicit scenario** — worldview, на который implicit опирается источник
- **Coverage quality** — HIGH/MEDIUM/LOW/DERIVED, отражает источниковую базу per scenario
- **RECALIBRATE** — режим `macro-forecast-chain` для cheap weight updates (Type A)
- **Layer 1** — marginal forecasts (independent FCA per factor)
- **Layer 2** — scenario bundles (coherent worlds × 4)

---

# 2. Phase 0 — Coherence audit существующих данных

**Цель:** диагностический отчёт о текущем состоянии прогнозов и сценариев.
**Время:** 1.5 часа.
**Предусловия:** доступ к Claude-Memory смонтирован.
**Output:** `Claude-Memory/_audits/coherence-audit-{date}.md`

## 2.1 Inventory всех YAML

| Категория | Локация | Кол-во | Назначение |
|-----------|---------|--------|------------|
| Активные сценарии | `scenarios/` | 4 | geopolitics-ru-west, brent-dec, usd-rub-sept, ai-capex |
| Прогнозы factor-level | `forecasts/` | ~22 | см. список ниже |
| macro-input | `macro-chain/` | 1 | будет split в Phase 3 |
| Stress-test | `Ретроспективный анализ/stress-2026-05-05-iron-curtain-2.yaml` | 1 | будет перезапущен Phase 4 |
| Source profiles | `.auto-memory/lib_*.md` | 9 | будут тегированы Phase 2 |

## 2.2 Текущие forecast YAMLs (на 2026-05-08)

```
forecasts/
├── ai-capex-slowdown-2026-2026-04-30.yaml
├── brent-oil-dec-2026-2026-04-30.yaml
├── byudzhetnyj-defitsit-rf-2026-05-03.yaml
├── china-taiwan-forecast-2026-04-28.yaml
├── cny-rub-dec2026-dec2027-2026-05-04.yaml          ← migration test #2
├── iran-us-may-deal-2026-04-30-stress.yaml
├── iran-us-may-deal-2026-04-30.yaml
├── ru-cpi-2026-2027-2026-05-04.yaml                 ← migration test #3 (worst case)
├── ru-rates-2026-2026-04-28.yaml
├── ru-rates-2026-2027-2026-05-04.yaml               ← migration test #1 (best case)
├── russia-europe-war-2030-2026-04-29.yaml
├── russia-europe-war-2030.yaml
├── sanctions-russia-2026-27-2026-05-02.yaml
├── ukraine-postwar-forecast.yaml
├── ukraine-russia-forecast-stress-test.yaml
├── ukraine-russia-war-end-2026-05-02.yaml
├── ukraine-russia-war-forecast-2026-04-28.yaml
├── urals-brent-discount-2026-05-04.yaml
├── us-technical-recession-2026-2026-04-30.yaml
├── usd-rub-dec2026-dec2027-2026-05-03.yaml
├── usd-rub-sept-2026-2026-04-30.yaml
└── xauusd-price-2026-2027-2026-05-04.yaml
```

## 2.3 Coherence checklist для каждого forecast

Для каждого YAML в `forecasts/` зафиксировать:

```yaml
- file: forecasts/{name}.yaml
  status: active | superseded | expired
  has_geopolitics_translation: true | false
  translation_method: linear | nonlinear | axis_dependent | indifferent | none
  scenario_values_present: true | false
  scenario_id_format: "Sc-A" | "A" | mixed
  weights_duplicated: true | false
  values_format: numbers | strings | mixed
  implicit_modal_scenario: A | B | C | D | unclear
  utf8_valid: true | false
  needs_migration: true | false
  migration_complexity: trivial | moderate | hard
```

## 2.4 Текущая аномалия весов (baseline на 2026-05-08)

Подтверждено через bash-grep:

| Файл | Sc-A | Sc-B | Sc-C | Sc-D | Сумма |
|------|------|------|------|------|-------|
| `scenarios/scenario-geopolitics-ru-west-2026-05-04.yaml` | 0.08 | 0.18 | 0.22 | **0.52** | 1.00 ✓ |
| `forecasts/ru-rates-2026-2027-2026-05-04.yaml` (distribution) | 0.08 | 0.18 | 0.22 | **0.525** | 1.005 ✗ |
| `forecasts/cny-rub-dec2026-dec2027-2026-05-04.yaml` | 0.08 | 0.18 | 0.22 | **0.525** | 1.005 ✗ |
| `forecasts/ru-cpi-2026-2027-2026-05-04.yaml` (markdown) | — | — | — | — | n/a |
| `macro-chain/macro-input-2026-05-04.yaml` | 0.08 | 0.18 | 0.22 | **0.525** | + «Unaccounted» 0.065 = 1.07 ✗ |
| `Ретроспективный анализ/stress-2026-05-05-iron-curtain-2.yaml` | 0.08 | 0.18 | 0.22 | **0.525** | 1.005 ✗ |

**Sc-D inconsistency:** scenario YAML 0.52, остальные 0.525. После D1 — все станут 0.25.

## 2.5 Implicit-scenario diagnosis (для Phase 2 тегирования)

Гипотезы (финальные значения подтверждаются пользователем при Phase 2):

| Источник | Профиль из lib_*.md | Гипотеза implicit |
|----------|---------------------|-------------------|
| БКС | HIGH bonds-rub, MEDIUM ru-rates, IGNORE usdrub | primary D (0.7), secondary B (0.3) |
| Invest Era | HIGH bonds-rub, MEDIUM ru-rates/inflation | primary D (0.6), secondary B (0.4) |
| ВТБ-МИ | MEDIUM bonds-fx/rub, IGNORE geopolitics-ru | agnostic_total: true |
| SberCIB | HIGH bonds-rub/ru-economy, MEDIUM oil | primary D (0.5), secondary C (0.5) |
| Финам | HIGH small-caps-ru, MEDIUM ru-rates | primary D (0.7), secondary B (0.3) |
| ЦБ РФ | HIGH ru-rates-late-cycle | agnostic_total: true |
| Stratfor | HIGH long-term-russia, MEDIUM nato | primary D (0.8), secondary B (0.2) |
| Chatham House | HIGH nato-future/short-term-russia | primary D (0.7), secondary B (0.3) |
| Morgan Stanley | MEDIUM ny-rates/recession, LOW EM | agnostic_total: true |

**Asymmetry warning:** 0 источников с primary Sc-A (мирный). Sc-A coverage = 0 native sources.

## 2.6 UTF-8 / mojibake check

```bash
for f in /sessions/.../mnt/Claude-Memory/forecasts/*.yaml; do
  iconv -f UTF-8 -t UTF-8 "$f" > /dev/null 2>&1 || echo "INVALID: $f"
done
```

Записать список проблемных файлов в audit.

## 2.7 Output: `_audits/coherence-audit-{date}.md`

Структура:
1. Inventory (§2.1)
2. Forecast checklist (§2.3) — таблица 22 строк
3. Weights anomaly baseline (§2.4)
4. Implicit-scenario hypothesis (§2.5)
5. UTF-8 validation (§2.6)
6. Recommendations for Phase 1 (weights), Phase 2 (tagging), Phase 5 (migration order)

---

# 3. Phase 1 — Унификация весов

**Цель:** все 5 файлов с весами сценариев согласованы; SSOT определён.
**Время:** 30 минут.
**Предусловия:** D1 = 0.25 default (✓ зафиксировано); Phase 0 audit завершён.
**Output:** правки в 5 YAML + запись в `_sync_log.md`.

## 3.1 Канонические значения (D1 + D3)

Все 5 файлов получают:
```
Sc-A: 0.25
Sc-B: 0.25
Sc-C: 0.25
Sc-D: 0.25
Sum:  1.00 ✓
modal_scenario_id: none
modal_flag: no_modal
```

«Unaccounted 0.065» (D3) — удаляется из `macro-input`, заменяется на `out_of_frame_caveats` блок.

## 3.2 Файл-by-файл правки

### `scenarios/scenario-geopolitics-ru-west-2026-05-04.yaml`

```yaml
# matrix.scenario_triggers — все 4 сценария
- scenario_id: A
  probability: 0.25       # было 0.08
- scenario_id: B
  probability: 0.25       # было 0.18
- scenario_id: C
  probability: 0.25       # было 0.22
- scenario_id: D
  probability: 0.25       # было 0.52
  modal: false            # было true
  
# matrix
modal_probability: 0.25
modal_flag: no_modal      # было strong_modal

# Удалить:
fca_calibration:
  conflict_intensity_ev: 0.73
  sanctions_intensity_ev: 0.65
# (заменить на):
fca_calibration:
  note: "По умолчанию все веса 0.25 (Pure Shell). Для opt-in расчёта через FCA — использовать --apply-joint-from-axes."
```

### `forecasts/ru-rates-2026-2027-2026-05-04.yaml`

```yaml
geopolitics_translation:
  distribution:
    Sc-A: 0.25       # было 0.08
    Sc-B: 0.25       # было 0.18
    Sc-C: 0.25       # было 0.22
    Sc-D: 0.25       # было 0.525
```

(Этот файл будет полностью мигрирован в `conditional_on_scenarios` схему в Phase 5.
Сейчас — лишь фикс весов для консистентности.)

### `forecasts/cny-rub-dec2026-dec2027-2026-05-04.yaml`

```yaml
geopolitics_translation:
  modal_probability: 0.25     # было 0.525
  alternatives:
    - { scenario_id: A, probability: 0.25, ... }    # было 0.08
    - { scenario_id: B, probability: 0.25, ... }    # было 0.18
    - { scenario_id: C, probability: 0.25, ... }    # было 0.22
```

### `macro-chain/macro-input-2026-05-04.yaml`

```yaml
forecasts.geopolitics:
  modal_probability: 0.25    # было 0.525
  modal_scenario_id: none    # было Sc-D
  scenarios:
    - id: Sc-A, probability: 0.25     # было 0.08
    - id: Sc-B, probability: 0.25     # было 0.18
    - id: Sc-C, probability: 0.25     # было 0.22
    - id: Sc-D, probability: 0.25     # было 0.525

scenarios:                              # внизу файла, для stress
  - label: "Sc-A Дипломатический оазис"
    probability: 0.25                   # было 0.08
  # ... аналогично B, C
  - label: "Sc-D Железный занавес-2"
    probability: 0.25                   # было 0.525, и убрать modal-marker

# УДАЛИТЬ блок:
- label: "Unaccounted"
  probability: 0.065
  factors: null

# ДОБАВИТЬ caveats:
caveats:
  - type: SCENARIO_FRAME_LIMITS
    severity: low
    description: |
      4 сценария Shell-матрицы конструктивно полны для axes 
      (conflict_intensity × sanctions_intensity). События вне axes 
      обрабатываются отдельным механизмом, не внутри scenario-matrix.
    out_of_frame_examples:
      - "Кибератака на банковский сектор РФ"
      - "Катастрофа Saudi Aramco"
      - "Политический кризис в США 2026-2027"
```

### `Ретроспективный анализ/stress-2026-05-05-iron-curtain-2.yaml`

```yaml
scenarios:
  Sc-D_base:
    probability: 0.25   # было 0.525
    p: 0.25             # было 0.525
  Sc-A_bull:
    probability: 0.25   # было 0.08
  Sc-C_war:
    probability: 0.25   # было 0.22
  Sc-B_stress:
    probability: 0.25   # было 0.18

# УДАЛИТЬ из top-level (D2):
expected_pl_rub: 437000
expected_pl_pct: 3.4
```

## 3.3 Обновить `scenarios/INDEX.md`

```markdown
# scenarios/INDEX.md

## Активные матрицы

| File | ... | Сценарии (D1 default 0.25 каждому) |
|------|---|---|
| ... geopolitics-ru-west ... | A: Дипломатический оазис (0.25) / B: Заморозка с тисками (0.25) / C: Военная экономика (0.25) / D: Железный занавес-2 (0.25, no modal) |
```

## 3.4 Запись в `_sync_log.md`

```markdown
## 2026-XX-XX — Phase 1 weight unification (D1, D3)

- Reason: Sc-D разъезжался между 0.52/0.525, плюс «Unaccounted» нарушал sum=1.0
- Decision per architectural meeting 2026-05-08:
  - D1: Pure Shell default 0.25/0.25/0.25/0.25 в scenario-builder
  - D3: «Unaccounted» удалить, заменить на out_of_frame_caveats блок
- Files modified:
  - scenarios/scenario-geopolitics-ru-west-2026-05-04.yaml: Sc-X 0.08/0.18/0.22/0.52 → 0.25 each
  - forecasts/ru-rates-2026-2027-2026-05-04.yaml: distribution 0.08/0.18/0.22/0.525 → 0.25 each
  - forecasts/cny-rub-dec2026-dec2027-2026-05-04.yaml: same
  - macro-chain/macro-input-2026-05-04.yaml: same + удалена «Unaccounted»
  - Ретроспективный анализ/stress-2026-05-05-iron-curtain-2.yaml: same + удалены expected_pl_*
- Sum check: each file sum = 1.000 ✓
- Backup: .pre-d1-unification суффикс на всех изменённых файлах
```

## 3.5 Sanity check после правок

```bash
# Через bash в Cowork
for f in scenario-geopolitics-...yaml ru-rates-...yaml cny-rub-...yaml macro-input-...yaml; do
  python -c "import yaml; data = yaml.safe_load(open('$f')); 
             # extract weights, sum, assert == 1.0"
done
```

---

# 4. Phase 2 — Source tagging (implicit_scenario)

**Цель:** все 9 источников в `.auto-memory/lib_*.md` тегированы.
**Время:** 1 час.
**Предусловия:** Claude Code Phase 1.1 завершён (спека `implicit_geopolitical_scenarios` готова).
**Output:** правки в 9 lib_*.md + обновлённый MEMORY.md + `_audits/scenario-coverage-{date}.md`.

## 4.1 Шаблон тегирования

В YAML frontmatter каждого `lib_*.md` добавить:

```yaml
implicit_geopolitical_scenarios:
  primary:
    scenario_id: D
    weight: 0.7
    rationale: "[конкретное обоснование на основе аудитов источника]"
  secondary:
    scenario_id: B
    weight: 0.3
    rationale: "[конкретное обоснование]"
agnostic_subdomains: [oil-forecast, ny-rates]
```

ИЛИ для agnostic-источников:

```yaml
implicit_geopolitical_scenarios:
  agnostic_total: true
  rationale: "[почему не имеет implicit RU geopolitics]"
```

## 4.2 Конкретные теги для 9 источников

(Финальные значения подтверждаются пользователем — это рабочие гипотезы из Phase 0.5)

### `lib_bcs_strategy_2025.md`
```yaml
implicit_geopolitical_scenarios:
  primary: { scenario_id: D, weight: 0.7, rationale: "Sanctions-stable worldview, постоянно базируются на extended sanctions" }
  secondary: { scenario_id: B, weight: 0.3, rationale: "Иногда обсуждают sanctions tightening" }
agnostic_subdomains: [usd-rub-forecast]
```

### `lib_invest_era.md`
```yaml
implicit_geopolitical_scenarios:
  primary: { scenario_id: D, weight: 0.6, rationale: "Sanctions baseline + war continues" }
  secondary: { scenario_id: B, weight: 0.4, rationale: "Sanctions intensification сценарий" }
agnostic_subdomains: [oil-forecast, oil-gas-ru, metals-mining-ru, bonds-fx, dividend-stocks]
```

### `lib_vtb_mi.md`
```yaml
implicit_geopolitical_scenarios:
  agnostic_total: true
  rationale: "ВТБ-МИ IGNORE по geopolitics-ru — implicit не применяется. Применять только marginal trust."
```

### `lib_sbercib.md`
```yaml
implicit_geopolitical_scenarios:
  primary: { scenario_id: D, weight: 0.5, rationale: "Sanctions baseline" }
  secondary: { scenario_id: C, weight: 0.5, rationale: "War economy + revenue flowing близко к sell-side нарративу" }
agnostic_subdomains: [oil-gas-ru]
```

### `lib_finam.md`
```yaml
implicit_geopolitical_scenarios:
  primary: { scenario_id: D, weight: 0.7, rationale: "Long Russia stance" }
  secondary: { scenario_id: B, weight: 0.3, rationale: "Sanctions tightening risk обсуждается" }
agnostic_subdomains: [usd-rub-forecast, metals-mining-ru, it-tech-ru]
```

### `lib_cbr.md`
```yaml
implicit_geopolitical_scenarios:
  agnostic_total: true
  rationale: "ЦБ РФ публикует регуляторно-нейтральные прогнозы. Implicit_scenario не применяется."
```

### `lib_stratfor.md`
```yaml
implicit_geopolitical_scenarios:
  primary: { scenario_id: D, weight: 0.8, rationale: "Long Russia conflict + structural sanctions" }
  secondary: { scenario_id: B, weight: 0.2, rationale: "Frozen conflict scenario обсуждается" }
agnostic_subdomains: [middle-east, china-rise]
```

### `lib_chatham_house.md`
```yaml
implicit_geopolitical_scenarios:
  primary: { scenario_id: D, weight: 0.7, rationale: "NATO escalation + extended sanctions" }
  secondary: { scenario_id: B, weight: 0.3, rationale: "Иногда — Frozen conflict" }
agnostic_subdomains: [eu-future]
```

### `lib_morgan_stanley.md`
```yaml
implicit_geopolitical_scenarios:
  agnostic_total: true
  rationale: "MS — global macro, RU geopolitics scenarios не релевантны. Применять только marginal trust."
```

## 4.3 Trust 3D расширение (D4, упрощённый Phase 2)

В каждом `lib_*.md` дополнить trust-схему до 2D (`marginal` + `world_picking`); 
`conditional` оставить как `UNTESTED` (Phase 6 заполнит):

```yaml
trust:
  marginal:
    {subdomain}: HIGH | MEDIUM | LOW | IGNORE   # перенос из старого trust:
  world_picking:
    {subdomain}: UNTESTED                        # Phase 6
  conditional:
    {subdomain}: UNTESTED                        # Phase 6
```

## 4.4 Обновить MEMORY.md

После тегирования — добавить пометку в каждую строку:

```markdown
- [[lib] БКС] — HIGH bonds-rub/ru-rates-forecast ..., implicit: D(0.7)/B(0.3)
- [[lib] Stratfor] — HIGH long-term-russia ..., implicit: D(0.8)/B(0.2)
- [[lib] ВТБ-МИ] — MEDIUM bonds-fx ..., implicit: agnostic
```

## 4.5 Asymmetry diagnostic — `Claude-Memory/_audits/scenario-coverage-{date}.md`

```markdown
# Scenario coverage из текущей библиотеки

Распределение primary implicit_scenario среди 9 audited sources:

- A (Дипломатический оазис): 0 источников   ⚠ DEAD ZONE
- B (Заморозка с тисками): 0 sources primary (но secondary у 5)
- C (Военная экономика): 0 sources primary (secondary у 1 — SberCIB)
- D (Железный занавес-2): 6 sources primary
- agnostic: 3 (ВТБ-МИ, ЦБ, MS)

## Asymmetry warning

Sc-A coverage = 0 native primary. При построении Sc-A bundle (Layer 2) — 
все значения derived. Confidence для Sc-A = LOW.

## Действия

Краткосрочно: для Sc-A использовать derivation через dependency-map + 
external sources (Polymarket, EIA peace-baseline)

Среднесрочно: расширить библиотеку peace-leaning sources:
  - Альфа Macro
  - Carnegie Endowment (Trenin до 2022)
  - Polymarket ceasefire contracts
  - Финам's optimistic notes

Долгосрочно: при структурной смене ситуации (если война заканчивается) — 
re-audit всех сейчас D-leaning sources на новую базу.
```

---

# 5. Phase 3 — Сплит macro-input

**Цель:** разделение `macro-input-2026-05-04.yaml` на marginal + scenarios.
**Время:** 1.5 часа.
**Предусловия:** Claude Code Phase 2.5 завершён (SKILL macro-forecast-chain обновлён).
**Output:** 2 файла + переименованный/удалённый исходник + sync log.

## 5.1 Создать `macro-marginal-2026-05-04.yaml` (Layer 1)

Содержит **marginal forecasts** + **coherence diagnostic**:

```yaml
---
schema_version: 2
type: macro-marginal
generated_at: "2026-05-04"
portfolio_snapshot: "PORTFOLIO-2026-05-03.json"
scenario_matrix_ref: "scenarios/scenario-geopolitics-ru-west-2026-05-04.yaml"

forecasts:
  geopolitics:
    type: scenario_matrix_reference   # not factor
    source: "scenarios/scenario-geopolitics-ru-west-2026-05-04.yaml"
  
  cbr_rate:
    central_estimate_2026: "12.5–13.0% (weighted median 12.7%)"
    central_estimate_2027: "10.0–11.0% (weighted median 10.7%)"
    confidence: 0.40
    implicit_scenario_aggregate: D
    source_file: "forecasts/ru-rates-2026-2027-2026-05-04.yaml"
  
  brent:
    central_estimate_2026: "$80–92/bbl (modal $88)"
    confidence: 0.40
    implicit_scenario_aggregate: A    # ⚠ противоречит остальным
    source_file: "forecasts/brent-oil-dec-2026-2026-04-30.yaml"
  
  # ... остальные 8 факторов

coherence_diagnostic:
  implicit_world_distribution:
    A: 1   # brent (нормализация Ормуза)
    B: 0
    C: 0
    D: 6   # cbr_rate, inflation_ru, urals_discount, usdrub, cnyrub, sanctions
    agnostic: 3   # xauusd, money_market, ...
  dominant_implicit_world: D
  inconsistency_score: 0.10
  warnings:
    - factor: brent
      implicit: A
      contradicts_majority: D
      severity: HIGH
      action: |
        Brent в Sc-A worldview (Ормуз открыт). Остальные 6 факторов в Sc-D.
        Для marginal-задачи (weekly-review, EV) — допустимо.
        Для stress — НЕ ИСПОЛЬЗОВАТЬ macro-marginal, переключиться на macro-scenarios.

caveats:
  # сохранить из исходника, дополнить coherence-обусловленные
---
```

## 5.2 Создать `macro-scenarios-2026-05-04.yaml` (Layer 2)

**Coherent bundles per scenario**:

```yaml
---
schema_version: 2
type: macro-scenarios
generated_at: "2026-05-04"
scenario_matrix_ref: "scenarios/scenario-geopolitics-ru-west-2026-05-04.yaml"

bundles:
  A:
    label: "Дипломатический оазис"
    factors:
      brent_2026:
        central: 90
        range: [85, 95]
        provenance: native_fca   # МЭА forecast прямо conditional на Sc-A
        sources_used: [iea]
      usdrub_2026:
        central: 83
        range: [78, 88]
        provenance: derived_from_marginal   # ⚠ нет native source for Sc-A
        sources_used: []
        confidence: LOW
      # ... остальные факторы
    coverage_quality: PARTIAL   # 1/9 факторов — derived
  
  B:
    label: "Заморозка с тисками"
    factors:
      # ... per Sc-B conditional
    coverage_quality: MEDIUM
  
  C:
    label: "Военная экономика"
    factors: { ... }
    coverage_quality: MEDIUM
  
  D:
    label: "Железный занавес-2"
    factors: { ... }
    coverage_quality: HIGH

caveats:
  - severity: HIGH
    factor: usdrub
    issue: "Sc-A coverage = 0 native sources. usdrub в Sc-A bundle — derived only."
    action: "При весе Sc-A < 0.10 — приемлемо. При весе ≥ 0.20 — запустить native FCA для Sc-A usdrub."
---
```

## 5.3 Backup исходника

```bash
mv /sessions/.../mnt/Claude-Memory/macro-chain/macro-input-2026-05-04.yaml \
   /sessions/.../mnt/Claude-Memory/macro-chain/macro-input-2026-05-04.yaml.pre-split
```

## 5.4 Verification

После split проверить:
- Сумма весов в `bundles` (через scenario YAML reference) = 1.0
- Каждый фактор присутствует во всех 4 bundles (даже если provenance=derived)
- `marginal` пересчитанный из bundles совпадает с `central_estimate` в `macro-marginal` ± 5%
  (т.е. coherence_diagnostic.divergence — small)

## 5.5 Запись в `_sync_log.md`

```markdown
## 2026-XX-XX — Phase 3 macro-input split

- Reason: разделение Layer 1 (marginal, для EV) и Layer 2 (scenarios, для stress)
- Files:
  - DELETED (renamed): macro-chain/macro-input-2026-05-04.yaml → .pre-split
  - CREATED: macro-chain/macro-marginal-2026-05-04.yaml (Layer 1)
  - CREATED: macro-chain/macro-scenarios-2026-05-04.yaml (Layer 2)
- Coherence diagnostic: divergence_pct {value}, severity {level}
- Verification: passed
```

---

# 6. Phase 4 — Stress test rerun на coherent bundles

**Цель:** новый stress-test на корректных coherent bundles.
**Время:** 30 минут.
**Предусловия:** Phase 3 завершён, Claude Code Phase 2.7 готов.
**Output:** новый `Ретроспективный анализ/stress-2026-05-XX-coherent-v2.yaml`.

## 6.1 Запуск стресса

С новым входом `macro-scenarios-2026-05-04.yaml`:

```
portfolio-scenario-stress \
  --input macro-scenarios-2026-05-04.yaml \
  --portfolio-snapshot PORTFOLIO-2026-05-03.json \
  --no-include-ev    # default per D2
  --output stress-2026-05-XX-coherent-v2.yaml
```

## 6.2 Сравнение vs старый stress

В `Ретроспективный анализ/stress-comparison-2026-05-XX.md` зафиксировать diff:

| Метрика | Старый (mixed worlds) | Новый (coherent) | Diff |
|---------|----------------------|------------------|------|
| Sc-D ΔP&L | +7.9% | ? | ? |
| Sc-A ΔP&L | +4.4% | ? | ? |
| Sc-B ΔP&L | -5.7% | ? | ? |
| Sc-C ΔP&L | -0.4% | ? | ? |
| `expected_pl_pct` | +3.4% | (удалён per D2) | n/a |
| modal_scenario | Sc-D (через 0.525) | none (через 0.25) | per D1 |
| worst_case | Sc-B | ? | ? |

Особое внимание: если Sc-D ΔP&L изменился значительно — это означает, что 
mixed-worlds artifact в старом stress был большим. Документировать.

## 6.3 Robustness verdict в новом отчёте

```yaml
robustness:
  positive_or_neutral_scenarios: ?   # из 4
  worst_case_scenario_id: "?"
  worst_case_pl_pct: ?
  best_case_scenario_id: "?"
  best_case_pl_pct: ?
  spread: ?                           # max - min
  hedge_target: "?"
  
  # При equal weights 0.25:
  # - Если все 4 положительные — портфель robust
  # - Если ≥1 отрицательное с большим magnitude — material risk
```

## 6.4 Документирование

В `stress-comparison-2026-05-XX.md`:
- Что изменилось vs старый stress
- Почему (какие mixed-worlds артефакты ушли)
- Действия (если хеджевая стратегия должна быть пересмотрена)
- Comparison с весами в обоих режимах (старые 0.08/0.18/0.22/0.525 vs новые 0.25 каждому)

---

# 7. Phase 5 — Migration forecast YAMLs (LAZY)

**Цель:** existing forecasts в `forecasts/` мигрированы в `conditional_on_scenarios` схему.
**Время:** ~30 минут на файл, итеративно по мере refresh.
**Предусловия:** Claude Code Phase 3 (migration script готов).
**Output:** обновлённые forecast YAMLs.

## 7.1 НЕ делать batch-миграцию

Существующие YAML работают как Layer 1 marginal. Они не блокируют апгрейд.
Миграция в новую схему — **по мере следующего refresh** каждого фактора.

## 7.2 Очерёдность приоритета (если делать)

1. **`ru-cpi-2026-2027-2026-05-04.yaml`** (худший YAML) — как референс новой схемы
2. **`ru-rates-2026-2027-2026-05-04.yaml`** — лучший YAML, должен пройти clean
3. **`cny-rub-dec2026-dec2027-2026-05-04.yaml`** — nonlinear partial
4. **`usd-rub-dec2026-dec2027-2026-05-03.yaml`** — нет geopolitics_translation, добавить
5. **`brent-oil-dec-2026-2026-04-30.yaml`** — implicit Sc-A, нужен Sc-D conditional FCA
6. Остальные ~17 файлов — по мере refresh

## 7.3 Per-file workflow

```bash
# В Cowork bash:
SOURCE="/sessions/.../mnt/Claude-Memory/forecasts/ru-cpi-2026-2027-2026-05-04.yaml"

# Backup
cp "$SOURCE" "${SOURCE}.pre-migration"

# Прогнать migration script (из Claude Code репо)
python ~/Documents/Программы/claude_skills/scripts/migrate_to_conditional.py \
  --input "$SOURCE" \
  --md "${SOURCE%.yaml}.md" \
  --output "${SOURCE}.migrated"

# Diff review
diff "${SOURCE}.pre-migration" "${SOURCE}.migrated"

# Validate schema
python ~/Documents/Программы/claude_skills/scripts/validate_schema.py "${SOURCE}.migrated"

# Promote
mv "${SOURCE}.migrated" "$SOURCE"
```

## 7.4 Удалить deprecated поля

После миграции — удалить из forecast YAML:
- `geopolitics_translation.distribution` (веса теперь в scenario YAML)
- `geopolitics_translation.scenario_rates_2026` (теперь в `by_scenario`)
- `geopolitics_translation.alternatives` (теперь в `by_scenario`)
- `Sc-A`, `Sc-B`, etc. идентификаторы → `A`, `B`, … (D5)

---

# 8. Карта файлов в Claude-Memory

```
/Users/you/Library/CloudStorage/SynologyDrive-home/Ext_gDrive/Claude-Memory/
├── _audits/
│   ├── coherence-audit-2026-05-XX.md            ← Phase 0 (NEW)
│   └── scenario-coverage-2026-05-XX.md          ← Phase 2 (NEW)
├── scenarios/
│   ├── scenario-geopolitics-ru-west-2026-05-04.yaml ← Phase 1 (D1, D3)
│   └── INDEX.md                                  ← Phase 1 update
├── forecasts/
│   ├── ru-rates-2026-2027-2026-05-04.yaml       ← Phase 1 + Phase 5 (lazy)
│   ├── cny-rub-dec2026-dec2027-2026-05-04.yaml  ← Phase 1 + Phase 5
│   ├── ru-cpi-2026-2027-2026-05-04.yaml         ← Phase 5 (reference)
│   ├── usd-rub-dec2026-dec2027-2026-05-03.yaml  ← Phase 5
│   ├── brent-oil-dec-2026-2026-04-30.yaml       ← Phase 5
│   └── ... (~17 других файлов, lazy migration по мере refresh)
├── macro-chain/
│   ├── macro-input-2026-05-04.yaml.pre-split    ← Phase 3 backup
│   ├── macro-marginal-2026-05-04.yaml           ← Phase 3 (NEW)
│   └── macro-scenarios-2026-05-04.yaml          ← Phase 3 (NEW)
└── _sync_log.md                                 ← Phase 1, 2, 3, 4 entries

/Users/you/Library/Application Support/Claude/.../auto-memory/
├── lib_bcs_strategy_2025.md                     ← Phase 2 (implicit_scenario)
├── lib_invest_era.md                            ← Phase 2
├── lib_vtb_mi.md                                ← Phase 2 (agnostic_total)
├── lib_sbercib.md                               ← Phase 2
├── lib_finam.md                                 ← Phase 2
├── lib_cbr.md                                   ← Phase 2 (agnostic_total)
├── lib_stratfor.md                              ← Phase 2
├── lib_chatham_house.md                         ← Phase 2
├── lib_morgan_stanley.md                        ← Phase 2 (agnostic_total)
└── MEMORY.md                                    ← Phase 2 (lib pointers)

/Users/you/Documents/Claude/Projects/Ретроспективный анализ/
├── stress-2026-05-05-iron-curtain-2.yaml        ← Phase 1 (вес) + DEPRECATED после Phase 4
├── stress-2026-05-XX-coherent-v2.yaml           ← Phase 4 (NEW)
└── stress-comparison-2026-05-XX.md              ← Phase 4 (NEW, diff doc)
```

---

# 9. Зависимости с Claude Code (см. парный документ)

## Что Cowork зависит от Claude Code

| CW Phase | Нужно из Claude Code |
|----------|----------------------|
| Phase 2 (lib tagging) | CC Phase 1.1 (спека `implicit_geopolitical_scenarios`) |
| Phase 3 (split macro-input) | CC Phase 2.5 (SKILL `macro-forecast-chain` обновлён) |
| Phase 4 (stress rerun) | CC Phase 2.7 (SKILL `portfolio-scenario-stress` обновлён) |
| Phase 5 (forecast migration) | CC Phase 3 (`migrate_to_conditional.py` готов) |

## Что Claude Code зависит от Cowork

| CC Phase | Нужно из Cowork |
|----------|-----------------|
| Phase 3 (migration script) | CW Phase 0 — реальные edge cases в forecasts/ |
| Phase 5 (tests) | CW Phase 0 — тестовые данные |
| Phase 6 (3D audit, Month 6+) | CW updates `lib_*.md` с conditional_score data |

---

# 10. Joint timeline

```
Day 0:  Пользователь подтверждает D1–D7 (✓ выполнено 2026-05-08)

Day 1 (4-5 ч):  CC Phase 1 (specs) ‖ CW Phase 0 (audit) + CW Phase 1 (фикс весов)

Day 2 (4-5 ч):  CC Phase 2 (code) ‖ CW Phase 2 (lib tagging — после CC Phase 1.1)

Day 3 (3-4 ч):  CC Phase 3 (migration) ←─── CW тестовые данные
                CW Phase 3 (split macro-input) ←── CC Phase 2.5

Day 4 (2 ч):   CC Phase 4 (RECALIBRATE) ‖ CW Phase 4 (stress rerun)

Day 5 (2 ч):   CC Phase 5 (tests) ‖ CW Phase 5 (forecast migration — lazy)

[Stable system]

Month 6+:       CC Phase 6 (3D audit) — при первом резолвед-прогнозе
Month 12+:      CC Phase 7 (scenario meta-audit) — при ≥6 резолюций
```

**Total: 5 рабочих дней split parallel.**

---

# 11. Контрольные точки и критерии готовности

| Phase | Done when... |
|-------|--------------|
| 0 | `coherence-audit-{date}.md` создан, обзор пользователем |
| 1 | Все 5 файлов с весами имеют 0.25/0.25/0.25/0.25, sum=1.0; «Unaccounted» удалён; `_sync_log.md` обновлён |
| 2 | 9 lib_*.md имеют `implicit_geopolitical_scenarios` блок; MEMORY.md обновлён; `scenario-coverage-{date}.md` создан |
| 3 | macro-marginal + macro-scenarios существуют; verification passed (sum, coverage, divergence); backup сохранён |
| 4 | Новый stress YAML создан; comparison doc написан; modal_scenario_id = none (D1) |
| 5 | По одному файлу за раз, при следующих refresh цикле |

---

# 12. Risks / open issues

1. **Synology mount ≠ автоматический в новой Cowork-сессии.** В каждой новой 
   сессии вызывать `request_cowork_directory(path="/Users/you/Library/CloudStorage/SynologyDrive-home/Ext_gDrive/Claude-Memory")`.

2. **`.auto-memory/lib_*.md` находится в Application Support, не в Synology.** 
   Это **частная auto-memory**, отдельная от библиотечных аудитов. Правки 
   возможны через Edit-инструмент Cowork, но требуют осторожности — не путать 
   с библиотечными аудитами в `Claude-Memory/domains/`.

3. **Sc-D inconsistency** (0.52 vs 0.525) — после Phase 1 заменяется на 0.25 
   везде, проблема снимается.

4. **«Unaccounted 0.065» в macro-input** — был добавлен пользователем в более 
   ранних итерациях. Удаление безопасно — он не используется в логике стресс-теста.

5. **mojibake** в существующих forecast YAMLs (Latin-1 декодинг UTF-8). Phase 0
   (audit) обнаружит; Phase 5 (migration) исправит через chardet.

6. **Stress test перезапуск (Phase 4)** требует Claude Code SKILL обновления 
   (Phase 2.7) — это блокирующая зависимость.

---

# 13. Контакт обратной связи

Если в процессе обнаружится несоответствие архитектуры реальным данным 
(например, формат YAML отличается от спеки) — фиксировать в новом audit-файле и
эскалировать в Claude Code (правка спеки), не править данные под кривую спеку.

Все 7 архитектурных решений (D1–D7) зафиксированы. Не пересматривать без 
явного указания пользователя.
