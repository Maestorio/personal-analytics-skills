# Weekly Review YAML — Schema v1

**Документ версии:** 1.0
**Дата:** 2026-05-05
**Контракт между:** `ru-portfolio-advisor` (producer) → `portfolio-integrated-view` (consumer)
**Файл:** `Weekly-Reviews/REVIEW-{date}.yaml`

---

## 1. Принципы дизайна

| Принцип | Применение |
|---|---|
| **Confidence intervals everywhere** | Каждое числовое предсказание → `{value, ci: [lo, hi]}` или `{value, ci_pct: [lo, hi]}` |
| **Source required for catalysts** | Catalyst без `source` field не пишется в YAML вообще |
| **Macro dependency explicit** | Каждый catalyst опционально привязан к stress-сценарию через `macro_dependency` |
| **Horizon hard-locked at 20mo** | `horizon_months: 20` фиксировано. `in_horizon: false` → catalyst отбрасывается |
| **Caveats inherited** | Все caveats из YAML наследуются в integrated-view |
| **Schema versioned** | `schema_version: 1` → consumers fail fast на несовместимой версии |

## 2. Полная schema

```yaml
# Frontmatter / metadata
schema_version: 1
type: weekly-stocks-review
review_date: "2026-05-04"            # ISO date
horizon_months: 20                    # фиксировано в v1
snapshot_id: "PORTFOLIO-2026-05-03.json"
snapshot_date: "2026-05-03"
advisor_version: "ru-portfolio-advisor@2.x"
producer: "claude-opus-4-7"           # модель, сгенерировавшая review
trust_matrix_source: "Claude-Memory/INDEX.md"
trust_matrix_extracted_at: "2026-05-04T10:00:00"

# Per-stock data — основная часть
per_stock:

  # Пример 1: bank with full catalyst tree
  SBER:
    weight_real_pct: 12.46              # из ie_actual.real_share_pct
    weight_ie_target_pct: 6.0           # из ie_model.target_share_pct
    weight_divergence_pp: 6.46          # = weight_real - weight_ie_target
    on_iis: false                       # R10: из holdings[i].account == "iis_3"
    sector: "Финансовый"                # из ie_model.sector

    fundamental_score: HIGH             # HIGH/MEDIUM/LOW/RED_FLAG
    fundamental_score_basis: |
      ROE 24% (МСФО Q1-26), CET1 13.2%, NIM 5.8%, CIR 31%.
      Отчётность Q1-26 +12% YoY чистой прибыли.
    fundamental_score_sources:
      - url: "https://www.sberbank.com/ru/investor-relations/disclosure"
        label: "Sber IR — раскрытия Q1-26 МСФО"
        accessed_date: "2026-05-04"
      - url: "https://e-disclosure.ru/portal/event.aspx?EventId=..."
        label: "e-disclosure — отчётность Q1-26"
        accessed_date: "2026-05-04"

    # Дивидендная компонента — критическая для total return
    div_yield_12m_pct:
      value: 11.5
      ci_pct: [9.0, 13.0]              # R1: confidence interval обязателен
    div_confidence: HIGH                 # HIGH/MEDIUM/LOW
    div_basis: |
      Дивполитика 50% от МСФО прибыли. Q1-26 PnL предполагает дивы
      ~37 руб./акция в июле 2026. Историческая выплата 100% объявленных.
    div_sources:
      - url: "https://www.sberbank.com/ru/investor-relations/dividends"
        label: "Sber — дивидендная политика"
        accessed_date: "2026-05-04"
      - url: "https://e-disclosure.ru/..."
        label: "ГОСА протокол 2025-06-12"
        accessed_date: "2026-05-04"

    # Catalyst tree — idiosyncratic alpha с привязкой к macro
    catalyst:
      - id: rate_cut_re_rating
        trigger: "ROE recovery via rate cuts to ~12% by end-2026"
        date_window: "2026-Q4 to 2027-Q2"
        in_horizon: true                  # R3: дата ≤ 2027-12-31?
        p: 0.6
        upside_pct: 25
        upside_ci_pct: [15, 35]           # R1
        source: "advisor estimate based on 2014-2017 cycle"
        source_quality: HIGH              # R9: HIGH (regulatory data) / MEDIUM (analyst) / LOW (heuristic)
        macro_dependency: "Sc-D_base"     # R4: id сценария из STRESS YAML
        macro_dependency_basis: |
          Reference scenario: «Железный занавес-2», предполагает rate cuts -175 bp.
          Если этот сценарий не реализуется (Sc-A или Sc-C) — catalyst not fires.

      - id: sanctions_tail
        trigger: "Secondary sanctions on Sber correspondents"
        date_window: any
        in_horizon: true                  # any → true
        p: 0.15
        downside_pct: 40
        downside_ci_pct: [25, 60]
        source: "stress-test Sc-B factor sanctions intensity"
        source_quality: HIGH
        macro_dependency: "Sc-B_stress"

      - id: dividend_decision
        trigger: "ГОСА approval of дивидендов за 2025"
        date_window: "2026-06"
        in_horizon: true
        p: 0.85
        upside_pct: 0                     # ужe заложено в div_yield_12m
        upside_ci_pct: [-2, 3]
        source: "https://e-disclosure.ru/... (ожидаемая дата ГОСА)"
        source_quality: HIGH
        macro_dependency: null            # независимое корп-событие

    ie_divergence_pp: 6.46                # дублирует weight_divergence_pp для удобства consumers
    ie_divergence_intentional: true       # R10: из ie_actual.user_action / user_note_*
    ie_divergence_basis: "Пользователь намеренно держит обе SBER+SBERP выше IE-цели"

    advisor_verdict: HOLD                 # HOLD/BUY/TRIM/SELL
    advisor_verdict_confidence: 0.75
    advisor_verdict_basis: |
      Фундаментал HIGH, дивы прогнозируемы, но позиция уже выше IE-цели.
      В Sc-D base scenario — нейтральный, в Sc-B — большая просадка.
      Вердикт HOLD, не BUY.

    verification_priority: LOW            # C5: HIGH/MEDIUM/LOW
    verification_checklist: []            # пусто для LOW
    last_corp_event: "2026-04-28: МСФО Q1-26 +12% YoY чистая прибыль"

  # Пример 2: stock with no calibrated catalysts (R2 in action)
  CHMF:
    weight_real_pct: 0.33
    weight_ie_target_pct: null            # not in IE model
    weight_divergence_pp: null
    on_iis: false
    sector: "Металлургический"

    fundamental_score: MEDIUM
    fundamental_score_basis: "Steel demand cycle pressured, китайский импорт"
    fundamental_score_sources:
      - url: "..."
        label: "..."
        accessed_date: "2026-05-04"

    div_yield_12m_pct:
      value: 0
      ci_pct: [0, 8]                     # широкий CI: дивы могут быть, могут нет
    div_confidence: LOW
    div_basis: |
      CHMF приостановил выплаты в 2022, в 2024 возобновил частично.
      Прогноз дивов на 2026 невозможен без раскрытия дивполитики.
    div_sources:
      - url: "..."
        label: "..."
        accessed_date: "2026-05-04"

    catalyst: []                          # R2: нет calibrated catalyst → пустой массив
    advisor_note: |
      No calibrated catalysts found within horizon.
      Position behaves macro-only (steel cycle, USD/RUB).
      Use macro_ΔP&L from stress-test без idio adjustment.

    ie_divergence_pp: null
    ie_divergence_intentional: false
    advisor_verdict: TRIM
    advisor_verdict_confidence: 0.6
    advisor_verdict_basis: |
      Маленькая позиция (0.33%), стальной цикл pressured.
      Капитал лучше переложить в позиции с явными catalysts.

    verification_priority: MEDIUM         # disagreement zone
    verification_checklist:
      - "Проверить дивполитику CHMF на сайте IR"
      - "Сверить с peer'ами (NLMK, MAGN) — они тоже без дивов?"
    last_corp_event: "2026-03-15: Q1-26 РСБУ"

  # Пример 3: ИИС-3 position (R10 in action)
  RU000A107RH8:
    weight_real_pct: 0.42                  # часть на main
    weight_ie_target_pct: null
    weight_divergence_pp: null
    on_iis: true                            # R10
    sector: "Облигации"

    fundamental_score: HIGH                 # для bond — credit quality
    fundamental_score_basis: "Русал, рейтинг A+ (Эксперт РА), купон 13.4% YTM"
    fundamental_score_sources:
      - url: "https://raexpert.ru/..."
        label: "Эксперт РА — рейтинг Русал"
        accessed_date: "2026-05-04"

    div_yield_12m_pct:                       # для bond — YTM scaled
      value: 13.4
      ci_pct: [13.4, 13.4]                  # YTM фиксированный — узкий CI
    div_confidence: HIGH
    div_basis: "YTM 13.4% при покупке, hold to maturity"
    div_sources:
      - url: "https://iss.moex.com/..."
        label: "MOEX ISS — данные облигации"
        accessed_date: "2026-05-04"

    catalyst:                                # для bond — обычно один: погашение
      - id: redemption
        trigger: "Погашение в 2027-04-20"
        date_window: "2027-04-20"
        in_horizon: true
        p: 0.97                               # высокая, при HIGH credit
        upside_pct: 0                         # ужe в YTM
        upside_ci_pct: [-1, 1]
        source: "https://iss.moex.com/..."
        source_quality: HIGH
        macro_dependency: null
      - id: credit_event
        trigger: "Дефолт / реструктуризация"
        date_window: any
        in_horizon: true
        p: 0.03
        downside_pct: 60
        downside_ci_pct: [40, 90]
        source: "Эксперт РА migration matrix для рейтинга A+"
        source_quality: MEDIUM
        macro_dependency: "Sc-B_stress"

    advisor_verdict: HOLD
    advisor_verdict_confidence: 0.9
    advisor_verdict_basis: "ИИС-3 hold to maturity, нельзя продавать без потери льготы"
    advisor_verdict_constraints:
      - "iis_3_hold_lock: позиция на ИИС-3, продажа разрушит налоговую льготу"

    verification_priority: LOW
    verification_checklist: []
    last_corp_event: "2026-04-15: купонная выплата 33.45 руб."

# Summary block — quick stats для consumers
summary:
  positions_reviewed: 25
  positions_with_calibrated_catalysts: 18
  positions_macro_only: 7                  # R2 result: no catalyst
  positions_on_iis: 8
  equity_div_yield_weighted_pct:
    value: 7.2
    ci_pct: [5.8, 8.6]                     # weighted CI
  ie_divergence_count: 4                    # позиций с |divergence| > 2pp
  red_flag_count: 0                         # fundamental_score == RED_FLAG

# Caveats — наследуются в integrated-view (R5)
caveats:
  - severity: HIGH
    message: |
      Catalyst trees — экспертная оценка advisor, не калиброванная вероятностная модель.
      P и Δ% — best estimate без backtesting. Calibration TODO для v2 через retrospective audit.
  - severity: HIGH
    message: |
      Div yield для PRMD/MDMG: confidence LOW — нет устоявшейся дивидендной политики.
      Числа в div_yield_12m — статистический estimate, не объявленные выплаты.
  - severity: MEDIUM
    message: |
      Macro dependencies between catalysts and scenarios estimated by analogy.
      Full covariance matrix — TODO для v2.
  - severity: INFO
    message: |
      Trust matrix snapshot from {trust_matrix_extracted_at}. Re-check каждые 3 мес.

# Quality checks — automatic checks producer выполнил
quality_checks:
  - check: "every catalyst has source"
    passed: true
  - check: "every catalyst.in_horizon flag computed"
    passed: true
  - check: "div_yield CI present for every position"
    passed: true
  - check: "iis_3 positions have advisor_verdict_constraints"
    passed: true
  - check: "fundamental_score_sources present for HIGH scores"
    passed: true
```

## 3. Hard rules для producer (advisor)

### 3.1. Catalyst writing rules (R2, R9)

```python
# Псевдокод правила
def should_write_catalyst(c):
    if not c.source:
        return False                    # R2: no source → drop
    if not c.in_horizon:
        return False                    # R3: out of 20mo → drop

    if c.source_quality == "LOW":
        c.p = c.p * 0.5                 # R9: discount unreliable

    return True
```

### 3.2. Div yield rules (R1)

- Если есть fixed дивполитика → narrow CI (3-5 pp range)
- Если payout discretionary → wide CI (отражает uncertainty)
- Если no history → CI [0, max_industry_yield]
- **Никогда не писать point estimate без CI**

### 3.3. Verification priority assignment (C5)

```python
def assign_verification_priority(stock):
    if stock.advisor_verdict in ("BUY", "TRIM", "SELL"):
        return "HIGH"
    if stock.advisor_verdict_confidence < 0.6:
        return "MEDIUM"
    if any(c.macro_dependency and stress.scenarios[c.macro_dependency].p < 0.2
           for c in stock.catalysts):
        return "MEDIUM"                  # critical event hidden in low-prob scenario
    return "LOW"
```

### 3.4. ИИС-3 verdict constraints (R10)

```python
def constrain_verdict_for_iis(stock):
    if stock.on_iis:
        if stock.advisor_verdict == "SELL":
            stock.advisor_verdict = "HOLD"
            stock.advisor_verdict_constraints.append(
                "iis_3_hold_lock: позиция на ИИС-3, продажа разрушит налоговую льготу"
            )
        if stock.advisor_verdict == "TRIM":
            stock.advisor_verdict = "HOLD"
            stock.advisor_verdict_constraints.append(
                "iis_3_partial_lock: trim возможен только при cessation льготы — не рекомендуется"
            )
    return stock
```

## 4. Hard rules для consumer (integrated-view)

### 4.1. Schema validation

```python
def validate_schema(yaml_data):
    if yaml_data.get("schema_version") != 1:
        raise SchemaIncompatible(
            f"weekly-review schema {yaml_data.get('schema_version')} "
            f"не поддерживается. Обнови portfolio-integrated-view."
        )
```

### 4.2. Joint expectation calculation (R4)

```python
def compute_joint_expected_pct(stock, stress_yaml):
    base_macro = stress_yaml.per_position[stock.ticker].expected_pct_pweighted
    div_contribution = stock.div_yield_12m_pct.value * (20.0 / 12.0)  # normalize to 20mo

    idio_alpha = 0.0
    for c in stock.catalyst:
        if c.macro_dependency:
            scenario_p = stress_yaml.scenarios[c.macro_dependency].p
            p_joint = scenario_p * c.p
        else:
            p_joint = c.p * 0.7              # discount for unknown dependency

        contribution = p_joint * (
            c.upside_pct if "upside_pct" in c else -c.downside_pct
        )
        idio_alpha += contribution

    return base_macro + div_contribution + idio_alpha
```

### 4.3. CI propagation

```python
def propagate_ci(stock, stress_yaml):
    # Симплифицированная Monte Carlo
    samples = []
    for _ in range(1000):
        macro = sample_from_ci(stress_yaml.per_position[stock.ticker].expected_pct_ci)
        div = sample_from_ci(stock.div_yield_12m_pct.ci_pct) * (20.0/12.0)
        idio = sum(
            sample_p(c.p) * sample_from_ci(c.upside_ci_pct or c.downside_ci_pct)
            for c in stock.catalyst
        )
        samples.append(macro + div + idio)
    return {
        "value": np.median(samples),
        "ci_pct": [np.percentile(samples, 16), np.percentile(samples, 84)]
    }
```

## 5. Edge cases и их обработка

| Edge case | Handling |
|---|---|
| Stock в portfolio, нет в IE model | `weight_ie_target_pct: null`, `weight_divergence_pp: null` |
| Stock в IE model, нет в portfolio | НЕ пишется в `per_stock`. Идёт в integrated-view как «IE candidate not held» через `ie_summary.list_in_ie_not_in_portfolio` |
| Bond с YTM | `div_yield_12m_pct` = YTM (не дивы). `catalyst` включает `redemption` |
| Blocked position (`is_blocked: true` в snapshot) | `fundamental_score: RED_FLAG`, `advisor_verdict: HOLD`, basis = "blocked, illiquid" |
| Position без MOEX-цены (cost_basis only) | `fundamental_score: LOW`, all CIs widened, `verification_priority: MEDIUM` |
| Catalyst date_window > 20 мес | `in_horizon: false` → автоматически отбрасывается через рулу 3.1 |
| Catalyst без macro_dependency | OK, считается как полностью idiosyncratic с discount factor 0.7 в синтезаторе |
| Все catalysts отброшены | `catalyst: []`, `advisor_note: "macro_ΔP&L only..."`, position survives с macro-only оценкой |

## 6. Acceptance criteria

YAML считается valid если:

- [ ] `schema_version == 1`
- [ ] `horizon_months == 20`
- [ ] `snapshot_id` существует и доступен
- [ ] `per_stock` содержит все active positions из snapshot
- [ ] Каждый catalyst имеет non-null `source` field
- [ ] Каждый catalyst имеет `in_horizon: bool`
- [ ] Каждое числовое предсказание имеет CI
- [ ] Все ИИС-3 позиции имеют `on_iis: true` и `advisor_verdict_constraints` non-empty
- [ ] `summary.positions_reviewed` совпадает с `len(per_stock)`
- [ ] `caveats` содержит минимум 1 запись severity HIGH (про catalyst calibration)
- [ ] `quality_checks` все `passed: true`
- [ ] YAML парсится без ошибок (e.g. `python -c "import yaml; yaml.safe_load(open('REVIEW-X.yaml'))"`)

## 7. Generation flow в advisor

```
1. Load PORTFOLIO-{date}.json (snapshot v2)
2. Filter positions where weight_real_pct > 0 AND not is_blocked
3. For each ticker:
   3.1 Web search recent news (e-disclosure, IR, sell-side reports)
   3.2 Compute fundamental_score with sources
   3.3 Estimate div_yield with CI from history + policy
   3.4 Generate catalyst candidates from news + macro context
   3.5 Filter catalysts: drop if no source, drop if out of horizon
   3.6 For each surviving catalyst: assign macro_dependency if applicable
   3.7 Apply ИИС-3 verdict constraints
   3.8 Assign verification_priority
4. Compute summary stats
5. Generate caveats (always include calibration warnings)
6. Run quality_checks
7. Output YAML to chat (default) or save to library (if flag)
```

## 8. Versioning policy

- v1 — этот документ
- v1.1 — additive only changes (новые optional поля)
- v2 — breaking changes (например, multiple horizons, full covariance)

Consumers объявляют compatibility:
- `portfolio-integrated-view@1.x` supports `weekly-review@1.x`
- `portfolio-integrated-view@2.x` supports `weekly-review@2.x` AND auto-converts `1.x` if possible

## 9. Не делается в v1 (TODO для v2+)

- **Multiple horizons** в одном review (12 / 20 / 36+) — пока horizon hard-locked
- **Full covariance matrix** между catalysts и scenarios — пока упрощённая joint expectation
- **Backtested catalyst.p calibration** — пока best estimates
- **Auto-checking catalyst dates** через `forecast-monitor` — TODO для v1.1
- **ML-based fundamental scoring** — пока экспертная оценка
- **Sentiment analysis** на news — пока нет
