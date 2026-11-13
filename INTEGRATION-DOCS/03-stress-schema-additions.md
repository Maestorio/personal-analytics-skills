# STRESS YAML — Schema additions for v1

**Документ версии:** 1.0
**Дата:** 2026-05-05
**Контракт между:** `portfolio-scenario-stress` (producer) → `portfolio-integrated-view` (consumer)
**Файл:** `Portfolio-Stress/STRESS-{date}.yaml`

---

## 1. Что меняется

Существующий формат STRESS YAML расширяется **аддитивно** — старые поля не меняются. Добавляются:
1. `schema_version` field (для R6)
2. `per_position` block (для R4 joint expectation в синтезаторе)
3. `scenarios.{id}.id` явные ID сценариев (для R4 macro_dependency reference)
4. `scenarios.{id}.expected_pct_ci` confidence intervals (для R1 propagation)

## 2. Новые поля в schema

### 2.1. Top-level `schema_version`

```yaml
# В начало файла
schema_version: 1
type: portfolio-stress-test
```

### 2.2. Расширение блока `scenarios`

**Было (предположительная структура существующего):**
```yaml
scenarios:
  - name: "Sc-D Железный занавес-2"
    probability: 0.525
    factors:
      sanctions_intensity: -0.05
      cbr_rate_delta_bp: -175
      usdrub_delta_pct: 12.5
      brent_usd: 65
      ...
    expected_pct_pweighted: -2.5
    sector_breakdown:
      banks: -3.2
      ...
```

**Стало (v1):**
```yaml
scenarios:
  Sc-D_base:                                    # ключ — explicit ID для macro_dependency
    name: "Железный занавес-2"
    p: 0.525                                    # short alias для probability
    probability: 0.525                          # старое имя для backward compat
    description: |
      Sanctions stable, CBR cuts to ~12% by end-2026, USD/RUB → 99
    factors:
      sanctions_intensity: -0.05
      cbr_rate_delta_bp: -175
      usdrub_delta_pct: 12.5
      brent_usd: 65
      ...
    portfolio_level:                            # переименовано из scenarios.expected_*
      expected_pct_pweighted: -2.5
      expected_pct_ci:                          # R1: новый field
        lo: -8.0
        hi: 4.0
      delta_rub: -350000
    sector_breakdown:                           # без изменений
      banks: -3.2
      ...
  Sc-A_bull:
    name: "Дипломатический оазис"
    p: 0.08
    ...
  Sc-B_stress:
    name: "Sanctions tail event"
    p: 0.15
    ...
  Sc-C_war:
    name: "Военная экономика"
    p: 0.22
    ...
```

**Замечание:** ключи (`Sc-D_base`, `Sc-A_bull`, etc.) — это те самые ID, на которые ссылается `catalyst.macro_dependency` в weekly-review YAML. Должны быть **stable** между versions (не переименовывать без bump schema_version).

### 2.3. Новый блок `per_position`

```yaml
per_position:
  SBER:
    weight_pct: 12.46
    on_iis: false                                # R10 — наследуется из snapshot

    # Factor betas — оценка чувствительности позиции к макрофакторам
    factor_betas:
      sanctions: -0.59
      cbr_rate: 0.30
      usdrub: -0.10
      brent: 0.05
    factor_betas_method: "regression on 24mo monthly returns 2024-2026"
    factor_betas_r2: 0.62                       # R-squared, для качества модели

    # Per-scenario delta
    delta_pct_by_scenario:
      Sc-D_base:
        value: -2.5
        ci_pct: [-8.0, 4.0]                     # R1
      Sc-A_bull:
        value: 18.0
        ci_pct: [10, 28]
      Sc-B_stress:
        value: -38.0
        ci_pct: [-55, -25]
      Sc-C_war:
        value: -8.0
        ci_pct: [-15, -3]

    # Probability-weighted expected (главная цифра для consumers)
    expected_pct_pweighted:
      value: -2.1
      ci_pct: [-12, 6]                          # propagated CI through scenarios

    # Tail risk metric
    tail_var_pct: -38.0                         # worst-case scenario value
    tail_var_scenario_id: "Sc-B_stress"

  T:
    weight_pct: 6.66
    on_iis: false
    factor_betas:
      sanctions: -0.45
      cbr_rate: 0.25
      ...
    delta_pct_by_scenario:
      ...
    expected_pct_pweighted:
      value: 0.5
      ci_pct: [-8, 12]
    ...

  # Bonds also get per_position breakdown
  RU000A107RH8:
    weight_pct: 0.42                             # main + iis combined
    on_iis: true                                 # has iis component
    factor_betas:
      sanctions: -0.10                           # for credit spread
      cbr_rate: -0.50                            # primary driver for bonds
      usdrub: 0
      brent: 0
    delta_pct_by_scenario:
      Sc-D_base:
        value: 8.5                               # rate cut → bond price up
        ci_pct: [5, 12]
      ...
    expected_pct_pweighted:
      value: 5.2
      ci_pct: [-2, 11]

# Sector-level summary (might already exist, add if missing)
sector_breakdown_pct:
  Банки:
    weight_pct: 32.1
    expected_pct_pweighted:
      value: -1.5
      ci_pct: [-10, 8]
  Облигации_RUB:
    weight_pct: 28.5
    expected_pct_pweighted:
      value: 6.8
      ci_pct: [3, 11]
  ...

# Top tier risks (might already exist)
top_risks:
  - {position: "SBER", scenario: "Sc-B_stress", delta_pct: -38, weight_pct: 12.46}
  - {position: "SBERP", scenario: "Sc-B_stress", delta_pct: -38, weight_pct: 11.22}
  ...

# NEW: macro_blindspots — позиции, чьи catalysts не покрываются macro factors
macro_blindspots:
  - ticker: "MDMG"
    reason: "Catalyst — открытие новых клиник, не зависит от macro factors напрямую"
  - ticker: "PRMD"
    reason: "Catalyst — одобрение препаратов, regulatory event"
  - ticker: "OZON"
    reason: "Catalyst — выход в EBITDA-positive, operational milestone"
  - ticker: "DOMRF"
    reason: "Catalyst — реформа льготной ипотеки, политическое событие"

# Caveats — существующая структура, дополнения
caveats:
  - severity: HIGH
    message: |
      Macro factors confidence: 0.40. Joint covariance estimated by analogy.
  - severity: HIGH
    message: |
      Stress horizon: до конца 2027 (~20 мес). Beyond this — уже другой режим.
  - severity: MEDIUM
    message: |
      factor_betas estimated on 24mo window (2024-2026). Russian regime shifts
      могут делать betas нестабильными. Re-estimate каждые 6 мес.
```

## 3. Backward compatibility

Старые consumers, читающие текущий формат STRESS YAML, продолжают работать:
- Старые поля `scenarios[i].name`, `scenarios[i].probability` сохраняются
- `top_risks`, `sector_breakdown` сохраняются
- Новые поля (`per_position`, `schema_version`, `macro_blindspots`) opt-in для consumers v2+

`portfolio-integrated-view` хочет **новые поля**. Если их нет — graceful degradation:
- Нет `per_position` → fallback на `sector_breakdown` (грубее)
- Нет `expected_pct_ci` → CI = `[value*0.5, value*1.5]` (placeholder)
- Нет `schema_version` → assume `0` → warning в integrated-view

## 4. Hard rules для producer (portfolio-scenario-stress)

### 4.1. Per-position breakdown computation

```python
# Псевдокод
def compute_per_position(snapshot, scenarios):
    result = {}
    for holding in snapshot.holdings:
        if holding.is_blocked or holding.value_rub == 0:
            continue                              # skip blocked/zero positions

        # Factor betas estimation
        prices_history = fetch_moex_history(holding.ticker, months=24)
        factor_history = fetch_factor_history(months=24)
        betas, r2 = regress(prices_history, factor_history)

        # Per-scenario delta
        delta_by_scenario = {}
        for sid, scenario in scenarios.items():
            delta = sum(betas[f] * scenario.factors[f] for f in betas)
            ci = bootstrap_ci(delta, betas, scenario.factors, samples=500)
            delta_by_scenario[sid] = {"value": delta, "ci_pct": ci}

        # Probability-weighted
        expected = sum(s.p * delta_by_scenario[sid].value for sid, s in scenarios.items())
        expected_ci = propagate_ci_through_scenarios(scenarios, delta_by_scenario)

        result[holding.ticker] = {
            "weight_pct": holding.value_rub / total_value * 100,
            "on_iis": (holding.account == "iis_3"),
            "factor_betas": betas,
            "factor_betas_method": "regression on 24mo monthly returns",
            "factor_betas_r2": r2,
            "delta_pct_by_scenario": delta_by_scenario,
            "expected_pct_pweighted": {"value": expected, "ci_pct": expected_ci},
            "tail_var_pct": min(d.value for d in delta_by_scenario.values()),
            "tail_var_scenario_id": worst_scenario_id,
        }
    return result
```

### 4.2. Macro blindspots detection

Позиция помечается как macro_blindspot если:
- `factor_betas_r2 < 0.3` (low explanatory power)
- ИЛИ все `|beta_i|` < 0.1 (insensitive to macro)
- ИЛИ ticker в hard-coded list of idiosyncratic names: pharma (MDMG, PRMD), e-comm (OZON), regulatory-driven (DOMRF, WUSH), small-caps with weak liquidity

```python
def is_macro_blindspot(ticker, betas, r2):
    if r2 < 0.3:
        return True, "low R^2 in factor regression"
    if all(abs(b) < 0.1 for b in betas.values()):
        return True, "low sensitivity to all macro factors"
    if ticker in HARD_CODED_IDIOSYNCRATIC_LIST:
        return True, HARD_CODED_REASONS[ticker]
    return False, None
```

### 4.3. Scenario IDs stability

**Критично:** ID сценариев (ключи в `scenarios:`) должны быть стабильными между запусками stress-теста.

Если в новом запуске сценарии переопределяются (новый макро-сетап) → bump `schema_version`. Старые weekly-review YAML, которые ссылаются на старые ID через `macro_dependency`, станут unmappable → integrated-view выдаст warning.

Текущие conventional IDs:
- `Sc-A_bull` — оптимистичный (relief, low rates, weak USD)
- `Sc-D_base` — base case (status quo + rate cuts)
- `Sc-C_war` — escalation, inflation, weak RUB
- `Sc-B_stress` — tail event (sanctions intensification)

## 5. Edge cases

| Edge case | Handling |
|---|---|
| Position не имеет MOEX-истории (новый листинг) | factor_betas: skip regression, use sector defaults. r2 = null. Mark macro_blindspot. |
| Bond с фиксированным купоном | factor_betas: только cbr_rate имеет смысл. Остальные = 0. |
| Blocked position (FXIT, FXUS etc) | НЕ включать в per_position, оставить в существующем `blocked_positions` блоке |
| Position на ИИС-3 (split main + iis) | Two entries в per_position OR single entry с `on_iis: true`. Решение: single entry, weight_pct суммарный, on_iis: true если хотя бы часть на ИИС |
| Cash | Не включать в per_position (не является security). Cash в RUB → factor_betas = 0. |

## 6. Acceptance criteria

STRESS YAML v1 считается valid если:

- [ ] `schema_version == 1`
- [ ] `scenarios` is dict с ключами вида `Sc-X_label`
- [ ] Каждый scenario имеет `p` field (alias for probability)
- [ ] Сумма всех `p` ≈ 1.0 (±0.001)
- [ ] `per_position` содержит все unblocked tickers из snapshot
- [ ] Каждая запись в `per_position` имеет `expected_pct_pweighted` с CI
- [ ] Все `macro_dependency` references в weekly-review YAML резолвятся в `scenarios` keys (cross-validation в integrated-view)
- [ ] `caveats` содержит минимум 1 запись HIGH severity
- [ ] Sum of `weight_pct` over `per_position` + cash + blocked = 100% (±1%)

## 7. Versioning policy

- v1 — этот документ
- v1.1 — additive (e.g., new factor types, sub-scenarios)
- v2 — breaking changes (e.g., scenarios as list with explicit IDs vs dict, multiple horizons)

## 8. Не делается в v1 (TODO для v2+)

- Backtest factor_betas против реализованной доходности
- Time-varying factor_betas (rolling window)
- Multiple horizons в одном stress run
- Cross-scenario covariance modeling (сейчас scenarios независимы по конструкции)
- Idiosyncratic component modeling (сейчас macro-only — explicit dichotomy)
