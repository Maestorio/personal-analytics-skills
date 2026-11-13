# Joint Expectation Rules — R1 (CI) и R4 (macro_dependency)

Ключевые правила propagation uncertainty и joint probability в синтезаторе.

---

## R1: Confidence intervals propagate

**Правило:** каждое числовое предсказание в output — `value [lo, hi]` или `value (CI)`. Никогда не показывать point estimate без CI.

### Формат CI в исходниках

| Источник | Поле | Пример |
|---|---|---|
| stress YAML | `expected_pct_pweighted: {value, ci_pct: [lo, hi]}` | `{value: -2.1, ci_pct: [-12, 6]}` |
| weekly-review | `div_yield_12m_pct: {value, ci_pct: [lo, hi]}` | `{value: 11.5, ci_pct: [9, 13]}` |
| weekly-review catalyst | `upside_pct, upside_ci_pct: [lo, hi]` | `25, [15, 35]` |

### Если CI отсутствует

Placeholder: `[value*0.5, value*1.5]` для positive value, симметрично для negative.
Обязательно сопровождать warning:

```
⚠ {ticker}.{field}: CI отсутствует в исходнике, использован placeholder [value*0.5, value*1.5].
```

### Aggregation внутри позиции (компоненты)

Простая additivity для v1:
```
total_value = macro + div + idio
total_ci_lo = macro_ci[0] + div_ci[0] + idio_ci_lo
total_ci_hi = macro_ci[1] + div_ci[1] + idio_ci_hi
```

**Допущение:** компоненты независимы. Реально есть корреляции (rate cut → re-rating + expanded multiples), но их моделирование — v2.

### Aggregation на уровне портфеля (positions)

Weighted mean по weight_pct:
```
expected = Σ (w_i × value_i) / Σ w_i
ci_lo = Σ (w_i × ci_lo_i) / Σ w_i
ci_hi = Σ (w_i × ci_hi_i) / Σ w_i
```

**Допущение:** позиции независимы. Это сильное упрощение (особенно внутри сектора), но честное в рамках v1: явно говорим в output, что CI portfolio-level — это weighted aggregate, не Monte Carlo.

### Spread CI

Equity vs bond spread:
```
spread = E - B
spread_ci_lo = E_ci_lo - B_ci_hi   # worst case for spread
spread_ci_hi = E_ci_hi - B_ci_lo   # best case for spread
```

Это conservative bounds (без correlations). Если var(E) и var(B) положительно скоррелированы (общий macro factor), реальный CI уже. v1 показывает worst/best — честно расширенный CI.

---

## R4: Joint expectation через macro_dependency

**Правило:** если catalyst.macro_dependency ссылается на scenario, его α взвешивается на P(scenario) × P(catalyst), а не на безусловное P(catalyst).

### Формула

```
if catalyst.macro_dependency:
    p_joint = scenarios[catalyst.macro_dependency].p × catalyst.p
else:
    p_joint = catalyst.p × 0.7    # discount factor — penalty за неуверенность
                                   # в independence от macro
```

### Почему 0.7

Если catalyst не имеет explicit dependency, мы не знаем correlation с macro. Безусловное P(catalyst) переоценивает реальное E[α]:
- Catalyst может быть macro-conditional, но не указано → P должна быть conditional × P(scenario)
- 0.7 ≈ средняя scenario probability в равновероятной 4-scenarios матрице (1/3 для центральной group)

Это не калиброванная константа, а honest discount. v2-C: backtested calibration.

### Source quality discount (R9 partial)

После joint P — дополнительный discount:
```
if catalyst.source_quality == "LOW":
    p_joint *= 0.5
```

`source_quality` — поле в weekly-review YAML, выставляется advisor'ом по trust matrix.

### Пример: SBER, catalyst "Rate cut re-rating"

```yaml
# В weekly-review:
catalyst:
  - id: rate_cut_re_rating
    p: 0.6
    macro_dependency: D    # abstract scenario_id из source_matrix
    upside_pct: 25
    upside_ci_pct: [15, 35]
    source_quality: HIGH
    in_horizon: true

# В stress:
scenarios:
  D:                       # ID согласован с source_matrix; label опционален
    p: 0.525
```

**Вычисление:**
```
p_joint = 0.525 × 0.6 = 0.315
contribution_to_idio = 0.315 × 25 = +7.9 п.п.
ci_contribution = [0.315 × 15, 0.315 × 35] = [+4.7, +11.0]
```

В output:
```
SBER catalyst rate_cut_re_rating:
  P(joint) = 0.315 (= 0.525 × 0.6)
  Contribution: +7.9 п.п. [+4.7; +11.0]
```

---

## Trust matrix awareness

Если `catalyst.source` указывает на analyst_name (Invest Era, БКС, и т.п.), и trust matrix (`Claude-Memory/INDEX.md`) для этого subdomain говорит IGNORE — catalyst исключается из joint expectation.

**Но** показывается в таблице с пометкой `trust=IGNORE` и контрибуцией 0:

```markdown
| Catalyst | Source | Trust | P(joint) | Contribution |
|---|---|---|---|---|
| EBITDA growth | Invest Era | IGNORE | --- (excluded) | 0 |
| Rate cut re-rating | advisor estimate | --- | 0.315 | +7.9pp |
```

Это критично для R5 (cognitive substitution mitigation): пользователь видит, что catalyst был, но не повлиял на joint expected return — и может сам решить, согласен ли он с trust verdict.

---

## Check: неотрицательность вероятностей

После всех discount'ов:
```
assert 0 ≤ p_joint ≤ 1
```

Если расчёт даёт p_joint > 1 (никогда не должно происходить, но защита) — log error и cap к 1.0.

---

## v2 расширения (не делать в v1)

- Full covariance matrix между catalysts
- Monte Carlo CI propagation (10,000 paths)
- Calibrated catalyst.p через retrospective audit
- Sector-specific source_quality discount factors
