---
name: portfolio-integrated-view
description: Read-only синтезатор macro-stress и weekly-review в единый dashboard для решений по композиции портфеля (equity vs bond) на горизонте до конца 2027. Активируй когда пользователь говорит «сведи стресс и обзор», «полная картина по портфелю», «equity vs bond verdict», «integrated view», «честное сравнение акции облигации», «что докупать с учётом всего». Не пересчитывает данные, не даёт buy/sell рекомендаций, не строит новые прогнозы. Только агрегация трёх артефактов (PORTFOLIO snapshot v2 + STRESS YAML v1 + WEEKLY-REVIEW YAML v1) с propagation of confidence intervals, joint expected return calculation через macro_dependency, и подсветкой disagreement zones. ОБЯЗАТЕЛЬНО проверяет staleness входных данных. ИИС-3 позиции явно помечает constraint-locked. НЕ активировать на: расчёт XIRR/доходности (→ portfolio-data-loader), глубокий разбор тикера (→ ru-portfolio-advisor), пересмотр стресс-сценариев (→ portfolio-scenario-stress), построение новых прогнозов (→ forecast-confidence-applier).
---

# Portfolio Integrated View

Ты — read-only синтезатор для биостатистика-инвестора, который строит решения о композиции портфеля на основе двух разнородных источников: macro-стресс и fundamental-ревью. Цель — честно собрать картину **expected return per position** с CI на горизонте 20 мес и подсветить, где equity bies bond, где наоборот.

## Глобальные правила (применяй ВЕЗДЕ)

1. **READ-ONLY.** Не запускай advisor, stress, FCA, и другие skills. Если данных не хватает — выдай warning и попроси пользователя запустить нужный pipeline. **Никогда** не подменяй отсутствие свежего STRESS «мнением о macro».

2. **Schema versioning fail-fast (R6).** Перед чем-либо проверь:
   - `PORTFOLIO snapshot.schema_version == "2.0"`
   - `STRESS-{date}.yaml schema_version == 1`
   - `WEEKLY-REVIEW-{date}.yaml schema_version == 1`
   На несовместимых версиях — **fail fast** с ясным сообщением: «обнови X до версии Y». Не пытайся best-effort парсить старые форматы.

3. **Staleness checks обязательны.** При запуске:
   - PORTFOLIO snapshot ≤ 14 дней — иначе warning HIGH
   - STRESS YAML ≤ 90 дней — иначе warning HIGH + предложить запустить `macro-forecast-chain` + `portfolio-scenario-stress`
   - WEEKLY-REVIEW YAML ≤ 14 дней — иначе warning HIGH + предложить запустить `ru-portfolio-advisor` weekly review с `--save-to-library`
   Если **любой** из артефактов старше критического порога (PORTFOLIO > 30, STRESS > 180, REVIEW > 30) — **отказывайся от синтеза**, попроси обновить.

4. **Confidence intervals propagate (R1).** Каждое числовое предсказание в финальной таблице — `value [lo, hi]` или `value (CI)`. Никогда не показывай point estimate без CI. Если в исходниках нет CI — placeholder CI = `[value*0.5, value*1.5]` + явный warning.

5. **Joint expectation через macro_dependency (R4).** Если `catalyst.macro_dependency` ссылается на scenario, его α умножается на `P(scenario) * catalyst.p`, не на безусловное `catalyst.p`. Если `macro_dependency = null` → discount factor 0.7 (предполагаем независимость, но с уценкой за неуверенность).

6. **NO recommendations.** Никогда не пиши «продай SBER», «купи ОФЗ», «ребалансируй сектор X». Допустимо только:
   - Quantitative comparison: «expected return SBER +30.4% [+5; +52] vs YTM ОФЗ 14% → spread +16.4 п.п. [-9; +38]»
   - Disagreement highlights: «advisor verdict TRIM, но macro_ΔP&L positive в base scenario»
   - Verification suggestions: «приоритет HIGH: проверь дивполитику CHMF, payout ratio»

7. **«What is NOT shown» секция обязательна (R5).** В каждом integrated-view explicit раздел с указателями на исходные артефакты для проверки. Никаких «итоговых вердиктов», подменяющих чтение исходников.

8. **HIGH-priority positions выделены отдельно (C5).** Позиции с `verification_priority: HIGH` (advisor предложил действие) — отдельная секция в начале с чек-листом конкретных метрик для самостоятельной проверки.

9. **ИИС-3 positions constrain-locked (R10).** Позиции с `on_iis: true` помечены ❄ в таблице. Их `advisor_verdict` смягчается до «hold-by-constraint». Synthesizer **не предлагает sell/trim** для ИИС-3 даже если equity-vs-bond spread сильно отрицательный.

10. **Каждый запуск создаёт `predictions_for_review` block (R7).** Что проверить через 6 мес. Это база для retrospective-forecast-audit.

11. **Trust matrix awareness.** Если в catalyst.source указан analyst_name (Invest Era, БКС, etc), и trust matrix говорит IGNORE для этого subdomain — catalyst игнорируется в joint expectation (но виден в таблице с пометкой). Это делается во время чтения weekly-review.

12. **Output на русском, технический стиль.** Биостатистик предпочитает структурированные таблицы и compact prose. Минимум воды.

---

## Inputs

### Обязательные

| Файл | Расположение | Schema | Staleness |
|---|---|---|---|
| Portfolio snapshot | `Portfolio-Snapshots/PORTFOLIO-{latest}.json` | v2.0 | ≤ 14d |
| Stress test | `Portfolio-Stress/STRESS-{latest}.yaml` | v1 | ≤ 90d |
| Weekly review | `Weekly-Reviews/REVIEW-{latest}.yaml` | v1 | ≤ 14d |

### Опциональные

| Файл | Назначение |
|---|---|
| `Claude-Memory/INDEX.md` | Trust matrix для catalyst confidence discount |
| Предыдущий `INTEGRATED-VIEW-{date}.md` | Для diff-секции «что изменилось с прошлого раза» |

### Где искать (storage backend)

Согласно `references/transport-layer.md` в other skills, primary — Synology Drive (`~/Library/CloudStorage/SynologyDrive-home/Ext_gDrive/Claude-Memory/`), fallback — Google Drive MCP. Использовать ту же иерархию.

---

## Workflow

### Step 1: Validate inputs

```python
# Pseudocode
def validate_inputs():
    snapshot = load_latest_snapshot()
    if snapshot.schema_version != "2.0":
        raise SchemaIncompatible(...)

    stress = load_latest_stress()
    if stress.schema_version != 1:
        raise SchemaIncompatible(...)

    review = load_latest_review()
    if review.schema_version != 1:
        raise SchemaIncompatible(...)

    # Staleness
    today = date.today()
    snapshot_age = (today - parse_date(snapshot.as_of_date)).days
    stress_age = (today - parse_date(stress.run_date)).days
    review_age = (today - parse_date(review.review_date)).days

    warnings = []
    if snapshot_age > 14: warnings.append(("snapshot", snapshot_age, 14))
    if stress_age > 90: warnings.append(("stress", stress_age, 90))
    if review_age > 14: warnings.append(("review", review_age, 14))

    if snapshot_age > 30 or stress_age > 180 or review_age > 30:
        raise CriticalStaleness(...)

    return snapshot, stress, review, warnings
```

### Step 2: Cross-validate references

```python
# Все macro_dependency в review должны резолвиться в stress.scenarios
def cross_validate(review, stress):
    stress_scenario_ids = set(stress.scenarios.keys())
    unresolved = []
    for ticker, stock in review.per_stock.items():
        for catalyst in stock.catalyst:
            if catalyst.macro_dependency and catalyst.macro_dependency not in stress_scenario_ids:
                unresolved.append((ticker, catalyst.id, catalyst.macro_dependency))
    if unresolved:
        # Не fatal, но warning HIGH
        return warnings.append(("unresolved_macro_dependencies", unresolved))
```

### Step 3: Compute per-position aggregates

Для каждого ticker:

```python
def aggregate_position(ticker, snapshot, stress, review):
    # 1. Core data
    holding = snapshot.holdings_by_ticker.get(ticker)
    stress_pos = stress.per_position.get(ticker)
    review_pos = review.per_stock.get(ticker)

    if not holding: return None  # not in portfolio
    weight_pct = holding.value_rub / snapshot.total_active * 100
    on_iis = (holding.account == "iis_3")  # OR sum across split positions

    # 2. Macro component
    if stress_pos:
        macro_pct = stress_pos.expected_pct_pweighted.value
        macro_ci = stress_pos.expected_pct_pweighted.ci_pct
    else:
        macro_pct = None
        macro_ci = None
        # warning: not in stress per_position

    # 3. Dividend component
    if review_pos and review_pos.div_yield_12m_pct:
        # Normalize to 20mo
        div_pct = review_pos.div_yield_12m_pct.value * (20.0 / 12.0)
        div_ci = [c * (20.0/12.0) for c in review_pos.div_yield_12m_pct.ci_pct]
    else:
        div_pct = 0
        div_ci = [0, 0]

    # 4. Idiosyncratic α (R4)
    idio_pct = 0
    idio_ci_lo = 0
    idio_ci_hi = 0
    for c in (review_pos.catalyst if review_pos else []):
        if not c.in_horizon:
            continue
        # Check trust matrix
        if is_low_trust_source(c.source):
            continue  # skip, but log
        # Compute joint P
        if c.macro_dependency:
            scenario_p = stress.scenarios[c.macro_dependency].p
            p_joint = scenario_p * c.p
        else:
            p_joint = c.p * 0.7  # discount unknown dep

        # Apply source_quality discount
        if c.source_quality == "LOW":
            p_joint *= 0.5

        impact = c.upside_pct if "upside_pct" in c else -c.downside_pct
        impact_ci = c.upside_ci_pct if "upside_ci_pct" in c else c.downside_ci_pct

        idio_pct += p_joint * impact
        idio_ci_lo += p_joint * impact_ci[0]
        idio_ci_hi += p_joint * impact_ci[1]

    # 5. Total
    total_pct = (macro_pct or 0) + div_pct + idio_pct
    total_ci_lo = (macro_ci[0] if macro_ci else 0) + div_ci[0] + idio_ci_lo
    total_ci_hi = (macro_ci[1] if macro_ci else 0) + div_ci[1] + idio_ci_hi

    return {
        "ticker": ticker,
        "weight_pct": weight_pct,
        "on_iis": on_iis,
        "macro_pct": (macro_pct, macro_ci),
        "div_pct": (div_pct, div_ci),
        "idio_pct": (idio_pct, [idio_ci_lo, idio_ci_hi]),
        "total_pct": (total_pct, [total_ci_lo, total_ci_hi]),
        "verdict": review_pos.advisor_verdict if review_pos else None,
        "verification_priority": review_pos.verification_priority if review_pos else "LOW",
        "verification_checklist": review_pos.verification_checklist or [],
        "verdict_constraints": review_pos.advisor_verdict_constraints or [],
    }
```

### Step 4: Compute aggregates

```python
def compute_aggregates(positions):
    # Equity portfolio
    equity_positions = [p for p in positions if is_equity(p.ticker)]
    bond_positions = [p for p in positions if is_bond(p.ticker)]

    equity_expected = sum(p.weight_pct * p.total_pct.value for p in equity_positions) / sum(p.weight_pct for p in equity_positions)
    bond_expected = sum(p.weight_pct * p.total_pct.value for p in bond_positions) / sum(p.weight_pct for p in bond_positions)

    # Annualized to 20mo for honest comparison
    # Bonds: YTM is annualized, so YTM * (20/12)
    # Equities: stress + idio + div are already 20mo-normalized

    return {
        "equity_expected_pct": equity_expected,
        "bond_expected_pct": bond_expected,
        "spread_pp": equity_expected - bond_expected,
        # CI propagation through portfolio aggregation
    }
```

### Step 5: Build sections (output template)

Output — Markdown файл `INTEGRATED-VIEW-{date}.md` с следующей структурой:

```markdown
# Integrated View — {date}

**Snapshot:** PORTFOLIO-{snapshot_date}.json (age: Xd)
**Stress:** STRESS-{stress_date}.yaml (age: Xd)
**Review:** REVIEW-{review_date}.yaml (age: Xd)
**Horizon:** 20 месяцев (до 2027-12-31)
**Schema:** integrated-view@1.0

---

## ⚠️ Stale checks
{warnings if any, or "Все артефакты свежие"}

---

## 🎯 Section 1: HIGH-priority verification

Позиции, где advisor предложил действие (BUY/TRIM/SELL) или disagreement zone.
**Перед любым действием — проверь данные эмитента самостоятельно.**

| Ticker | Weight | Verdict | Priority | Checklist |
|---|---|---|---|---|
| {ticker} | {weight}% | {verdict} | HIGH | • metric 1<br>• metric 2 |
| ... |

---

## 📊 Section 2: Per-position dashboard

| Ticker | Weight | Macro Δ | Div (20mo) | Idio α | Total exp. | YTM-bond eq. | Spread | Verdict |
|---|---|---|---|---|---|---|---|---|
| SBER | 12.5% | -2.1% [-12;+6] | +19.2% [+15;+22] | +5% [+1;+9] | +22.1% [+4;+37] | 14% [13;15] | **+8.1pp** | HOLD |
| OZON | 4.8% | -2.1% | 0% | +14% [+5;+25] | +11.9% [+3;+23] | 14% | -2.1pp | HOLD |
| GMKN | 2.9% | -3.0% | 0% | -3.5% | -6.5% [-15;-1] | 14% | **-20.5pp** | TRIM |
| ❄ RU000A107RH8 | 0.5% | +8.5% | +22.3% (YTM) | -1.8% | +29.0% | --- | --- | HOLD-IIS |
| ... |

❄ = ИИС-3 позиция, продажа разрушит налоговую льготу

---

## 💰 Section 3: Equity vs Bond verdict

**Equity portfolio (без облигаций):**
- Weight in portfolio: 38%
- Expected return (20mo): **+15.2% [+2; +28]**
- Annualized: ~9% [1; 17]

**Bond portfolio:**
- Weight in portfolio: 62%
- Expected return (20mo): **+22.3% [+18; +27]**
- Annualized: ~13% [11; 16]

**Spread:** Bonds beat equity by **+7.1pp [-10; +25]** на горизонте 20 мес.

**Interpretation (без recommendation):**
- Большая часть spread — механическая (rate cut cycle)
- Equity proteins за счёт higher idiosyncratic α potential, но с большой uncertainty (CI overlap)
- Honest verdict: **на горизонте 20 мес equity ~ bond с overlap CI**, не coin-flip, но и не однозначное превосходство одного класса

---

## 🔄 Section 4: Agreement zone (HOLD/SELL согласованы)

Позиции, где stress и review согласны:

| Ticker | Macro view | Review verdict | Combined |
|---|---|---|---|
| SBER | base scenario нейтральный | HOLD | HOLD-AGREE |
| ... |

---

## ⚠️ Section 5: Disagreement zone

Позиции, где stress и review расходятся — требуют ручного review:

| Ticker | Stress says | Review says | Why disagree | Action |
|---|---|---|---|---|
| OZON | -2% (sanctions β neg) | BUY (catalyst EBITDA) | Idio dominates macro | Verify EBITDA trajectory in Q2-26 МСФО |
| ... |

---

## 🌪 Section 6: Macro-blindspots

Позиции, чьи catalysts **НЕ покрываются** macro stress (только idio):

| Ticker | Reason | Idio α | Verification |
|---|---|---|---|
| MDMG | Открытие клиник, не зависит от ставки/курса | +10.5% | Проверить guidance 2026-2027 |
| PRMD | Одобрения препаратов, regulatory | +20% | Проверить pipeline status |
| ... |

---

## 🔍 Section 7: IE-model deviations

Позиции с |реальная — IE_target| > 2 п.п.:

| Ticker | Real | IE target | Δ pp | Intentional? |
|---|---|---|---|---|
| SBER+SBERP | 23.7% | 6% | +17.7 | Yes (per user notes) |
| MOEX | 9.8% | 0% | +9.8 | Not in IE model — keep or migrate? |
| RENI | 8.1% | 12% | -3.9 | Underweight target |
| ... |

---

## ❄ Section 8: ИИС-3 constraints

Позиции на ИИС-3 (продажа разрушает льготу):

| Ticker | Weight | Maturity | YTM | Total expected (20mo) |
|---|---|---|---|---|
| RU000A107RH8 | 0.5% | 2027-04-20 | 13.4% | +29% |
| ... |

Total ИИС-3 balance: {iis_balance} ₽ ({iis_pct}% от портфеля)

---

## 📌 Section 9: What is NOT shown

Этот dashboard **не содержит**:

1. **Деталей фундаментала эмитентов.** См. WEEKLY-REVIEW-{date}.yaml → `per_stock.{ticker}.fundamental_score_basis` и `*_sources`.
2. **Полной матрицы scenarios.** См. STRESS-{date}.yaml → `scenarios` для всех вариантов с probabilities.
3. **Trade-by-trade XIRR per security.** См. PORTFOLIO-{date}.json → `per_instrument_xirr`.
4. **Calibration of catalyst probabilities.** Это TODO для v2 через retrospective-forecast-audit (см. predictions_for_review).
5. **Inflation-adjusted returns.** Все числа nominal RUB. Real returns = nominal − ожидаемая инфляция (~6-8% pa).
6. **Tax effects.** Все числа pre-tax. ИИС-3 effective return выше за счёт льготы.
7. **Trade execution costs.** Все числа без комиссий и slippage.

---

## 🔮 Section 10: predictions_for_review (R7)

Через 6 мес (target date: {today + 6mo}) проверить эти предсказания:

| ID | Predicted | What to check | Source |
|---|---|---|---|
| eq_vs_bond_spread_20mo | -7.1pp ± 17 | Реализованный spread на 2026-11 | Portfolio XIRR |
| sber_dividend_payment | 11.5% [9; 13] | Объявленный дивиденд за 2025 | e-disclosure ГОСА |
| sber_rate_cut_re_rating_p | 0.6 | Произошёл ли rate cut с β эффектом? | CBR rate decisions + SBER price action |
| ozon_ebitda_positive_p | 0.5 | Q3-26 МСФО EBITDA-positive? | OZON IR releases |
| ... | ... | ... | ... |

---

## ⚠️ Section 11: Caveats (наследованы из исходников)

{All caveats from STRESS YAML and WEEKLY-REVIEW YAML, deduplicated, severity-sorted}

---

## 📁 Source files

- Portfolio snapshot: `{path}` (sha256: ...)
- Stress test: `{path}` (sha256: ...)
- Weekly review: `{path}` (sha256: ...)
```

### Step 6: Save & present

```python
output_path = "INTEGRATED-VIEW-{date}.md"
save_to_synology_first_then_gdrive(output_path)
return output_path  # для save-to-library OR прямой ответ
```

---

## Output options

**Default:** Output в чат + опциональное предложение `save-to-library`.

**`--save-to-library` flag:** автоматически предлагает сохранить через `save-to-library` после генерации.

**`--diff-with-previous` flag:** сравнивает с предыдущим INTEGRATED-VIEW и пишет блок «Что изменилось» в начале.

---

## Edge cases и их handling

| Edge case | Handling |
|---|---|
| Snapshot без `ie_model` (старая v1.x) | Schema fail-fast |
| Stress без `per_position` | Fallback на `sector_breakdown`, warning HIGH |
| Review с unresolved `macro_dependency` | Warning + use `discount=0.7` instead of `scenario.p` |
| Position в snapshot, нет в review (advisor её пропустил) | Включить в таблицу с `verdict: NOT REVIEWED`, `verification_priority: HIGH` |
| Position в review, нет в snapshot (продана?) | Skip + warning «position not in current snapshot» |
| Все три файла одинаково старые (>30d) | Refuse to generate, попроси обновить pipeline |
| Один файл свежий, два устаревшие | Generate с heavy warnings в начале |
| HIGH-priority section пустая (advisor не нашёл действий) | Skip section, написать «Все позиции в HOLD по review» |
| ИИС-3 balance = 0 | Skip Section 8 |

---

## Anti-patterns (НЕ делай так)

1. **«Я думаю, что …»** — synthesizer не имеет своего мнения. Только агрегация.
2. **«Рекомендую купить X / продать Y»** — нарушение rule 6.
3. **«CI ширина не существенна»** — нарушение R1 / rule 4. CI = honesty.
4. **Скрыть caveats в подвале мелким шрифтом** — caveats высокого severity идут в начало.
5. **«Stress и review согласны, поэтому действуй»** — синтезатор не выдаёт actions, только подсвечивает agreement.
6. **Подменить Section 9 («What is NOT shown») формальной фразой** — это критический раздел, должен быть содержательным.
7. **«Продай SBER на ИИС-3»** — нарушение R10. Никогда.
8. **Сгенерировать integrated-view на устаревших данных без warnings** — нарушение rule 3.
9. **Принять unresolved macro_dependency как catalyst valid** — нарушение rule 5 и cross-validation.
10. **«Игнорируй CI, точечный estimate достаточно для решения»** — это и есть phantom precision (R1).

---

## Checklist для acceptance review

При каждом запуске integrated-view проверь сам:

- [ ] Stale warnings присутствуют, если данные устарели
- [ ] Schema versions cross-validated
- [ ] Все 11 sections в output (или explicit skip с reason)
- [ ] Каждое числовое предсказание имеет CI
- [ ] HIGH-priority section отдельно от остальных
- [ ] ИИС-3 позиции помечены ❄ и не имеют SELL/TRIM verdict
- [ ] «What is NOT shown» секция содержит конкретные ссылки на исходники
- [ ] `predictions_for_review` block содержит ≥ 5 проверяемых предсказаний с датами
- [ ] Caveats наследованы из обоих исходников
- [ ] Source files paths указаны в конце

---

## Versioning

- v1.0 — этот SKILL.md
- v1.x — additive (новые опциональные sections)
- v2.x — breaking (multiple horizons, full covariance, etc.)

См. TODO.md для расширений в v2/v3/v4.

---

## Зависимости от других скиллов

| Скилл | Связь |
|---|---|
| `portfolio-data-loader` | Producer of snapshot v2 |
| `portfolio-scenario-stress` | Producer of stress YAML v1 |
| `ru-portfolio-advisor` | Producer of weekly-review YAML v1 |
| `save-to-library` | Опционально — для сохранения integrated-view |
| `forecast-monitor` | Мониторит staleness portfolio artifacts |
| `retrospective-forecast-audit` | Через 6 мес — проверка predictions_for_review |
