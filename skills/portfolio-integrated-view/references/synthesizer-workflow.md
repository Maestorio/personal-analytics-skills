# Synthesizer Workflow — детальный pseudocode

Развёрнутая спецификация Шагов 1–4 из SKILL.md. Использовать как референс
при имплементации синтеза. Pseudocode ориентирован на Python-подобный
синтаксис, но реальный pipeline — Claude reads YAML/JSON через transport-layer
и считает в голове / через ad-hoc Python.

---

## Шаг 1: Validate inputs

```python
def validate_inputs():
    snapshot = load_latest("Portfolio/snapshots/portfolio-*.json")
    if snapshot.schema_version != "2.0":
        raise SchemaIncompatible(
            f"snapshot schema {snapshot.schema_version}, требуется 2.0. "
            f"Перегенерируй через portfolio-data-loader."
        )

    stress = load_latest("Portfolio/stress/stress-*.yaml")
    stress_file = stress                      # возраст, inputs.stress, stress_date — всегда по нему
    recalc = load_if_exists(f"Portfolio/stress/auto/recalc-{stress.filename}")
    if recalc:                                # пересчёт сайта: те же суждения, свежий снапшот и веса сайта
        stress = recalc                       # числа — из него; inputs.stress_recalc_at = recalc.recalc.at
    if stress.schema_version != 1:
        raise SchemaIncompatible(
            f"stress schema {stress.schema_version}, требуется 1. "
            f"Перегенерируй через portfolio-scenario-stress."
        )

    # Phase 10.4: weekly-review разделён на stock + bond. Грузим оба, какой найден.
    # Legacy weekly-review-{date}.yaml (без stock/bond суффикса) поддерживается с warning.
    review_stock = load_latest("Portfolio/weekly-reviews/weekly-review-stock-*.yaml")
    review_bond = load_latest("Portfolio/weekly-reviews/weekly-review-bond-*.yaml")
    review_legacy = load_latest("Portfolio/weekly-reviews/weekly-review-[!sb]*.yaml")  # без stock/bond префикса

    for r in (review_stock, review_bond, review_legacy):
        if r is not None and r.schema_version != 1:
            raise SchemaIncompatible(
                f"review schema {r.schema_version}, требуется 1. "
                f"Перегенерируй через ru-portfolio-advisor --save-to-library."
            )

    if review_stock is None and review_bond is None and review_legacy is None:
        raise SchemaIncompatible(
            "Не найдено ни одного weekly-review (stock/bond/legacy) в "
            "Portfolio/weekly-reviews/. Запусти ru-portfolio-advisor --save-to-library."
        )

    review = review_stock or review_bond or review_legacy  # для дальнейшей staleness-проверки берём newest available

    # Staleness
    today = date.today()
    snapshot_age = (today - parse_date(snapshot.as_of_date)).days
    stress_age = (today - parse_date(stress_file.date)).days
    review_age = (today - parse_date(review.review_date)).days

    warnings = []
    if snapshot_age > 14: warnings.append(("snapshot", snapshot_age, 14))
    if stress_age > 90: warnings.append(("stress", stress_age, 90))
    if review_age > 14: warnings.append(("review", review_age, 14))

    # Critical thresholds — refuse to synthesize
    if snapshot_age > 30 or stress_age > 180 or review_age > 30:
        raise CriticalStaleness(
            f"snapshot={snapshot_age}d, stress={stress_age}d, review={review_age}d. "
            f"Обнови pipeline перед запуском integrated-view."
        )

    return snapshot, stress, review, warnings
```

---

## Шаг 1.5: Нормировка вероятностей сценариев

```python
def normalize_scenario_probs(stress):
    S = sum(sc.p for sc in stress.scenarios.values())
    for sc in stress.scenarios.values():
        sc.p_norm = sc.p / S

    delta = abs(S - 1.0)
    if delta > 0.05:
        severity = "MEDIUM"
    elif delta > 0.02:
        severity = "LOW"
    else:
        severity = None  # без warning

    return S, severity
    # Во всех дальнейших расчётах использовать sc.p_norm, а не sc.p
```

---

## Шаг 2: Cross-validate references + Stale-pipeline gate

Все `macro_dependency` в review должны резолвиться в `stress.scenarios`. Если резолвится мало — это означает, что review строился на устаревшем сценарном каркасе, и synthesizer должен отказаться, а не глушить через discount=0.7.

```python
STALE_PIPELINE_THRESHOLD = 0.3  # доля unresolved для отказа

def cross_validate(review, stress):
    stress_scenario_ids = set(stress.scenarios.keys())
    unresolved = []
    total_with_dependency = 0
    for ticker, stock in review.per_stock.items():
        for catalyst in stock.catalyst:
            if not catalyst.macro_dependency:
                continue
            total_with_dependency += 1
            if catalyst.macro_dependency not in stress_scenario_ids:
                unresolved.append((ticker, catalyst.id, catalyst.macro_dependency))

    if not total_with_dependency:
        return None  # некого валидировать

    unresolved_share = len(unresolved) / total_with_dependency

    if unresolved_share > STALE_PIPELINE_THRESHOLD:
        # R-PIPE: stale-pipeline gate
        missing_ids = sorted({ref for _, _, ref in unresolved})
        raise StalePipeline(
            f"unresolved macro_dependency: {len(unresolved)} из {total_with_dependency} "
            f"({unresolved_share:.0%}). "
            f"Отсутствующие scenario IDs: {missing_ids}. "
            f"Запусти RECALIBRATE-mode (macro-forecast-chain) на active forecasts "
            f"или обнови weekly-review через ru-portfolio-advisor."
        )

    if unresolved:
        # Под порогом — warning HIGH, discount=0.7 применяется per-catalyst
        return ("unresolved_macro_dependencies", unresolved)
    return None


def check_snapshot_drift(stress, review):
    # R-SNAP
    stress_snapshot_date = parse_date(stress.snapshot_id)  # из YAML stress
    review_snapshot_date = parse_date(review.snapshot_id)
    drift_days = abs((stress_snapshot_date - review_snapshot_date).days)
    if drift_days > 3:
        return ("snapshot_drift", drift_days, stress_snapshot_date, review_snapshot_date)
    return None
```

**Источник весов для §3 и §4 — только stress (R-SNAP).**
`stress.per_position[ticker].weight_pct` — это % от полного портфеля (total-portfolio basis).
`review.per_stock[ticker].weight_real_pct` — это % от sub-bucket (стоки внутри stocks-review, облигации внутри bonds-review). В портфельные агрегаты review-веса не пускать.

---

## Шаг 3: Per-position aggregate

Для каждого ticker — три компоненты + total:

```python
def aggregate_position(ticker, snapshot, stress, review, trust_matrix):
    # 1. Core data
    holding = snapshot.holdings_by_ticker.get(ticker)
    if not holding:
        return None  # not in portfolio

    weight_pct = holding.value_rub / snapshot.total_active * 100
    # ИИС-3 detection: если позиция split между счетами,
    # on_iis = True если ANY часть на ИИС-3
    on_iis = any(h.account == "iis_3" for h in holding.split_positions or [holding])

    stress_pos = stress.per_position.get(ticker)
    review_pos = review.per_stock.get(ticker)

    # 2. Macro component (20mo, из stress)
    if stress_pos:
        macro_pct = stress_pos.expected_pct_pweighted.value
        macro_ci = stress_pos.expected_pct_pweighted.ci_pct
    else:
        macro_pct = None
        macro_ci = None
        # warning: position not in stress per_position — fallback на sector_breakdown

    # 3. Dividend / carry component (R-BOND-CARRY)
    asset_class = holding.asset_class  # "equity" | "bond" | "fund_*"
    if asset_class == "bond":
        # Облигации: carry из bond-review, не div_yield (поля нет в bond-review).
        # Авторитетная реализация — aggregate_div_or_carry() в aggregate_positions.py.
        bond_pos = review_bond.per_bond.get(ticker) if review_bond else None
        # Горизонт capped до ближайшей оферты/погашения (put-бумага гасится → carry не идёт дальше)
        eff_months = min(20.0, months_to(bond_pos.offer_date or bond_pos.maturity_date))
        f = eff_months / 12.0
        if bond_pos and bond_pos.ytm_pct and abs(bond_pos.ytm_pct.value) > 60 and bond_pos.coupon_pct:
            # ytm неправдоподобен (yield-to-offer, напр. 414%) → базис coupon_pct
            div_pct = bond_pos.coupon_pct * f
            div_ci = [div_pct, div_pct]
        elif bond_pos and bond_pos.ytm_pct:
            div_pct = bond_pos.ytm_pct.value * f
            div_ci = [c * f for c in bond_pos.ytm_pct.ci_pct]
        elif holding.xirr is not None:
            # Fallback на historical XIRR из snapshot
            div_pct = holding.xirr * f
            div_ci = [div_pct * 0.85, div_pct * 1.15]  # ±15% на отсутствие forward CI
        else:
            div_pct = 0
            div_ci = [0, 0]
            # warning HIGH: bond без carry source
        div_pct = clamp(div_pct, -50, 50)  # backstop |carry| ≤ 50 пп
    else:
        # Акции и фонды: dividend yield из stocks-review
        if review_pos and review_pos.div_yield_12m_pct:
            div_pct = review_pos.div_yield_12m_pct.value * (20.0 / 12.0)
            div_ci = [c * (20.0/12.0) for c in review_pos.div_yield_12m_pct.ci_pct]
        else:
            div_pct = 0
            div_ci = [0, 0]

    # 4. Idiosyncratic α (R4 — см. joint-expectation-rules.md)
    idio_pct, idio_ci_lo, idio_ci_hi = 0, 0, 0
    for c in (review_pos.catalyst if review_pos else []):
        if not c.in_horizon:
            continue
        # Trust matrix check
        if is_low_trust_source(c.source, trust_matrix):
            continue  # skip, but log в "ignored catalysts"

        # Joint P
        if c.macro_dependency:
            scenario_p = stress.scenarios[c.macro_dependency].p
            p_joint = scenario_p * c.p
        else:
            p_joint = c.p * 0.7  # discount unknown dependency

        # Source quality discount (R9 partial)
        if c.source_quality == "LOW":
            p_joint *= 0.5

        impact = c.upside_pct if "upside_pct" in c else -c.downside_pct
        impact_ci = c.upside_ci_pct if "upside_ci_pct" in c else c.downside_ci_pct

        idio_pct += p_joint * impact
        idio_ci_lo += p_joint * impact_ci[0]
        idio_ci_hi += p_joint * impact_ci[1]

    # 5. Total (additive — упрощение v1; full covariance в v2)
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
        "verdict": review_pos.advisor_verdict if review_pos else "NOT REVIEWED",
        "verification_priority": (
            review_pos.verification_priority if review_pos else "HIGH"
        ),
        "verification_checklist": (
            review_pos.verification_checklist if review_pos else []
        ),
        "verdict_constraints": (
            review_pos.advisor_verdict_constraints if review_pos else []
        ),
        "macro_blindspot": (stress_pos.macro_blindspot if stress_pos else False),
    }
```

---

## Шаг 4: Portfolio-level aggregates

```python
def compute_aggregates(positions):
    equity_positions = [p for p in positions if is_equity(p.ticker)]
    bond_positions = [p for p in positions if is_bond(p.ticker)]

    def weighted_mean(positions, key):
        total_w = sum(p.weight_pct for p in positions)
        if total_w == 0: return None
        return sum(p.weight_pct * p[key].value for p in positions) / total_w

    def weighted_ci(positions, key):
        total_w = sum(p.weight_pct for p in positions)
        if total_w == 0: return [None, None]
        lo = sum(p.weight_pct * p[key].ci[0] for p in positions) / total_w
        hi = sum(p.weight_pct * p[key].ci[1] for p in positions) / total_w
        return [lo, hi]

    equity_expected = weighted_mean(equity_positions, "total_pct")
    equity_ci = weighted_ci(equity_positions, "total_pct")

    bond_expected = weighted_mean(bond_positions, "total_pct")
    bond_ci = weighted_ci(bond_positions, "total_pct")

    spread = equity_expected - bond_expected

    # CI propagation — два варианта (оба выводятся в output)
    # 1. Консервативный (линейное сложение, corr=1 между всеми ошибками)
    spread_ci_linear = [
        equity_ci[0] - bond_ci[1],
        equity_ci[1] - bond_ci[0],
    ]
    # 2. Реалистичный (квадратурное сложение, независимые ошибки)
    #    σ ≈ ширина CI / 4 (приближение для ≈95% CI = point ± 2σ)
    sigma_eq   = (equity_ci[1] - equity_ci[0]) / 4.0
    sigma_bond = (bond_ci[1]   - bond_ci[0])   / 4.0
    sigma_spread = (sigma_eq**2 + sigma_bond**2) ** 0.5
    spread_ci_quadratic = [spread - 2 * sigma_spread, spread + 2 * sigma_spread]
    # Истинный CI между linear (corr=1) и quadratic (corr=0)

    return {
        "equity": {
            "weight_pct": sum(p.weight_pct for p in equity_positions),
            "expected_pct_20mo": (equity_expected, equity_ci),
            "expected_pct_annualized": (
                equity_expected * (12/20),
                [c * (12/20) for c in equity_ci],
            ),
        },
        "bond": {
            "weight_pct": sum(p.weight_pct for p in bond_positions),
            "expected_pct_20mo": (bond_expected, bond_ci),
            "expected_pct_annualized": (
                bond_expected * (12/20),
                [c * (12/20) for c in bond_ci],
            ),
        },
        "spread_pp_20mo": {
            "point": spread,
            "ci_linear": spread_ci_linear,       # консервативный (corr=1)
            "ci_quadratic": spread_ci_quadratic,  # реалистичный (corr=0)
        },
    }
```

---

## Особенности и допущения

1. **Нормировка вероятностей** — применяется автоматически через p_norm = p / S. Использовать p_norm везде в Шагах 3 и 4.
2. **Аддитивная декомпозиция** total = macro + div + idio — упрощение v1. Валидно при низкой корреляции компонент. Полная covariance — v2.
3. **Двойной CI propagation** на уровне портфеля: линейный (corr=1, консервативный) + квадратурный (corr=0, реалистичный). Оба выводятся; реальный CI между ними.
4. **Bond carry** — точечная оценка `базис × eff_months/12`, где базис = `ytm_pct` (→ `coupon_pct` если ytm неправдоподобен >60%, т.е. yield-to-offer) → `xirr`, а `eff_months` capped до ближайшей оферты/погашения; backstop `|carry| ≤ 50`. При доминирующем cutting-rate сценарии расширить нижнюю границу CI на 1–2 pp (rolldown).
5. **Annualization** через линейное масштабирование `20mo × (12/20)` — корректно для линейных returns; для compounded returns корректировка через `(1+r)^(12/20) - 1` (v2).
6. **ИИС-3 split detection** требует чтения `holdings[i].split_positions` если snapshot v2 разбивает позиции по счетам.
7. **Trust matrix** парсится из `Claude-Memory/INDEX.md` один раз, кешируется in-memory на время запуска.
8. **Ticker collision**: при `is_blocked=true` + несоответствии `currency` ожидаемой локализации тикера — пометить 🔒, исключить из агрегатов, показать в отдельной строке master-table с методологической оговоркой.
