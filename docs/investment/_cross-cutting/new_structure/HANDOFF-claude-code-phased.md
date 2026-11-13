# HANDOFF → Claude Code: пофазный апгрейд скиллов

**Версия:** 2026-05-08, финальная после архитектурного обсуждения
**Парный документ:** `HANDOFF-cowork-data-phased.md` (загружается вместе с этим файлом)
**Среда работы:** Claude Code, репозиторий `~/Documents/Программы/claude_skills`
**Язык работы:** русский (везде — скиллы, коммиты, документация)

---

# 0. Контекст для нового чата (читать первым)

## Кто пользователь и что у него есть

- **Профиль:** биостатистик, 7 лет на рынке, мат-стат, не профи индустрии, способен handle full detail.
- **Портфель:** MOEX (акции + облигации RUB/USD/EUR/CNY + фонды), ~13.5M RUB.
- **Хранилище данных:** `~/Library/CloudStorage/SynologyDrive-home/Ext_gDrive/Claude-Memory/` (Synology Drive, **БЕЗ git**).
- **Хранилище кода:** `~/Documents/Программы/claude_skills` (репо под git).
- **Две среды работы:** Claude Code (этот документ) и Cowork (парный документ). Пользователь передаёт оба файла в каждую среду.

## Что находится в Claude-Memory (для понимания, не править из Claude Code)

```
Claude-Memory/
├── scenarios/      ← 4 активные scenario matrices
├── forecasts/      ← ~22 forecast YAMLs
├── macro-chain/    ← macro-input-{date}.yaml (текущая версия — single file)
├── audits/         ← retrospective audits, lib_*.md под доменами
├── domains/        ← {domain}/{audit}.md — иерархическая библиотека
├── INDEX.md        ← мастер-индекс trust-весов источников
└── _sync_log.md    ← лог saves
```

## Принципы работы

- **Корректность > читаемость > стоимость > скорость**
- Скиллы инвестиционного назначения **не дают buy/sell рекомендаций**, только аналитика
- Коммиты на русском
- Все доступы из Claude Code только к репо, **не править Claude-Memory** — это работа Cowork

---

# 1. Архитектурный фундамент (общий с Cowork-документом)

## Что решает апгрейд

Текущая система прогнозов и сценариев имеет 4 структурных дефекта:

1. **Веса сценариев появлялись в чате без следа** (Sc-D=0.525 был экспромтом Claude в чате во время `macro-forecast-chain` 2026-05-03, не воспроизводимо)
2. **Conditional values смешаны с marginal** в одном файле `macro-input-{date}.yaml`
3. **Источники не атрибутированы по сценариям** — невозможен retrospective audit per-scenario
4. **Stress-test использовал mixed-worlds factors**: Brent с Sc-A worldview (Ормуз открыт) + USD/RUB с Sc-D worldview (sanctions hold) в одном bundle, что методологически некорректно

## Двухслойная архитектура

```
LAYER 1 — MARGINAL FORECASTS (independent)
  • один FCA на фактор, trust-weighted на источниках
  • источники могут implicit противоречить друг другу
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
Это диагностика через `coherence_diagnostic` блок (см. §1.4).

## Три типа updates (после апгрейда)

| Type | Триггер | Что меняется | Время |
|------|---------|--------------|-------|
| **A — Weight-only** | leading_indicator сработал, новость, change of belief | только Layer 2 marginal + presentation labels | ~30 сек |
| **B — Factor baseline** | premise фактора сломалась | один factor's by_scenario + Layer 1 marginal этого фактора | ~30 мин (1 FCA) |
| **C — Structural** | оси сценарной матрицы устарели | вся scenario matrix + все conditional FCA | ~1–2 дня |

## 7 архитектурных решений (зафиксированы пользователем 2026-05-08)

| # | Решение | Что значит для кода |
|---|---------|---------------------|
| **D1** | `scenario-builder` выдаёт 0.25 каждому по default. Пользователь правит в SSOT (scenarios/{name}.yaml). | `joint_from_axes()` остаётся как opt-in CLI флаг `--apply-joint-from-axes`, не auto-применяется |
| **D2** | `expected_pl_pct` удалить из default. Opt-in флаг `--include-ev`. | `portfolio-scenario-stress` не считает weighted EV by default; флаг включает |
| **D3** | «Unaccounted» сценарий убрать. Заменить на `out-of-frame_caveats`. | В schema spec — отдельный блок для out-of-frame событий |
| **D4** | Trust 3D (marginal/conditional/world_picking). Phase 2 реализует 2D (marginal+world); conditional — Phase 6. | В audit-frontmatter-schema полная 3D схема, но valid input — backward-compat 1D и 2D |
| **D5** | scenario_id формат `A` (короткий). `Sc-A` deprecated. | Миграционный скрипт через regex меняет `Sc-A` → `A` |
| **D6** | ρ correlation как параметр в scenario YAML + рубрика оценки в `correlation-rubric.md`. Default ρ=0. | `joint_from_axes(ev_x, ev_y, rho=0)` |
| **D7** | Pure Lazy aggregation. Marginal пересчитывается только при RECALIBRATE. Нет pre-commit hook (нет git в Claude-Memory). Soft default, `--strict` флаг. | Validator в RECALIBRATE: stale → auto-recalculate с warning |

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

# 2. Phase 1 — Спецификации схем (без кода)

**Цель:** письменная спецификация в `_shared-references/`, которую можно валидировать.
**Время:** 2–3 часа.
**Предусловия:** D1–D7 зафиксированы (✓ выше).
**Артефакты:**

## 2.1 `_shared-references/events-yaml-spec.md`

Добавить разделы:

### `§N. conditional_on_scenarios` блок

```yaml
conditional_on_scenarios:
  source_matrix: "scenarios/{scenario-id}.yaml"   # SSOT для весов
  scenario_id_format: short                        # "A" вместо "Sc-A" (D5)
  by_scenario:
    A:
      values:
        "{horizon}": { central: <number>, range: [lo, hi] }
      provenance: native_fca | single_native | derived_from_marginal
      sources_used: [<source_id>, …]              # для retrospective-audit
      coverage_quality: HIGH | MEDIUM | LOW | DERIVED
    B: { … }
    C: { … }
    D: { … }
  marginal:
    method: linear | nonlinear | axis_dependent | indifferent
    modal_scenario_id: A | B | C | D | none       # обязательно для tail-risk; "none" если веса equal
    values:
      "{horizon}": { central: <number>, range: [lo, hi] }
    aggregation_formula: "weighted_mean"
  unit: "%"                                        # один раз для всего блока
  
coherence_diagnostic:
  layer1_marginal: <number>                        # из forecast.central_estimate
  layer2_marginal: <number>                        # из conditional_on_scenarios.marginal.values
  divergence_pct: <number>
  severity: LOW | MEDIUM | HIGH                    # <5%, 5-15%, >15%
  warning: <text or null>
```

**Инварианты:**
- `by_scenario` всегда содержит **все 4 сценария**, даже при method=nonlinear
- Веса не дублируются в `by_scenario` — резолвятся через `source_matrix`
- Числа, не строки. Регексы парсинга «13.5%» — в migration script
- `marginal.values` пересчитывается детерминированно из `by_scenario` функцией `aggregate_marginal()`
- При `weights = [0.25, 0.25, 0.25, 0.25]` → `modal_scenario_id: none`

### `§N+1. implicit_scenario` блок для источников

В audit-файле (`lib_*.md` или `domains/{domain}/{audit}.md`) — YAML frontmatter:

```yaml
implicit_geopolitical_scenarios:
  primary:
    scenario_id: D
    weight: 0.7
    rationale: "Источник держит постоянный sanctions-stable worldview"
  secondary:
    scenario_id: B
    weight: 0.3
    rationale: "Иногда обсуждает sanctions tightening как high-probability"
agnostic_subdomains: [oil-forecast, ny-rates]
# ИЛИ
implicit_geopolitical_scenarios:
  agnostic_total: true   # source agnostic to scenarios for ALL subdomains
  rationale: "Внешний global macro, RU geopolitics не релевантны"
```

**Правило:** `primary.weight + secondary.weight == 1.0`. Tertiary разрешён, но редко используется.

## 2.2 `_shared-references/audit-frontmatter-schema.md`

Расширить trust-схему до 3D (D4):

```yaml
trust:
  marginal:        # точность point-estimate vs realized — Phase 2
    {subdomain}: HIGH | MEDIUM | LOW | IGNORE
  world_picking:   # точность выбора implicit_scenario — Phase 2 (упрощённый)
    {subdomain}: HIGH | MEDIUM | LOW | UNTESTED
  conditional:     # точность внутри implicit-сценария — Phase 6 (DEFERRED)
    {subdomain}: HIGH | MEDIUM | LOW | IGNORE | UNTESTED
```

**Backward compat:** если есть только `trust:` без подразделов — считать как `trust.marginal`.

## 2.3 `_shared-references/scenario-yaml-spec.md` (новый файл)

SSOT-правила для сценарных матриц:

- `matrix.scenario_triggers[*].probability` — **единственное** место хранения весов
- Сумма должна быть 1.0 ± 0.001 (валидатор)
- `joint_from_axes(ev_x, ev_y, rho)` — рецепт получения весов из FCA на осях (opt-in)
- `correlation_xy: <number>` — отдельное поле, оценка корреляции между осями (D6)
- Default по D1: каждый сценарий получает probability=0.25 при создании через scenario-builder

## 2.4 Migration spec — `scripts/migrate_to_conditional.spec.md`

Pseudocode для миграционного скрипта:

```
INPUT: forecasts/{factor}-{horizon}.yaml + соответствующий .md

STEPS:
  1. Прочитать YAML, найти `geopolitics_translation` блок
  2. Определить method: linear | nonlinear | axis_dependent | indifferent
  3. Если есть `scenario_rates_2026` / `cny_rub_2026` / etc:
      - Парсить значения через regex (проценты, диапазоны)
      - Конвертировать в numbers (string "13.5%" → number 13.5 + unit "%")
      - Записать в by_scenario[X].values["{horizon}"].central
  4. Если есть `alternatives`:
      - Извлечь Sc-A/B/C alternatives
      - Sc-D — из central_estimate top-level (cny-rub case)
      - Записать в by_scenario
  5. Если есть только `distribution_used: true` (худший случай — ru-cpi):
      - Парсить markdown-таблицу геополитической трансляции
      - Regex на «Sc-{X}: {value}{unit}»
      - Извлечь, конвертировать
  6. scenario_id format: `Sc-A` → `A` (D5)
  7. Записать unit отдельно (один на блок)
  8. Удалить scenario-specific weights — они в source_matrix
  9. Пересчитать marginal через aggregate_marginal() и сравнить с существующим central_estimate
  10. Если разница > 5% — flag для ручной проверки

OUTPUT: тот же файл с заменённым `geopolitics_translation` →
        `conditional_on_scenarios`. Backup: .yaml.pre-migration

EDGE CASES:
  - Sc-D в central_estimate vs alternatives (cny-rub-style)
  - Диапазоны "$50–65" → range: [50, 65]
  - "%-strings" "13.5%" → 13.5 + unit: "%"
  - mojibake (Latin-1 декодинг UTF-8) — chardet detection + repair
  - Forecasts без geopolitics_translation вовсе — добавить пустой conditional блок
    с derivation для всех сценариев
```

**Тесты для миграции (используются из Cowork Phase 5):**
- `ru-rates-2026-2027-2026-05-04.yaml` (linear, лучший YAML)
- `cny-rub-dec2026-dec2027-2026-05-04.yaml` (nonlinear, частичный)
- `ru-cpi-2026-2027-2026-05-04.yaml` (худший случай — только markdown)

---

# 3. Phase 2 — Core code: weighted_consensus.py + SKILL.md edits

**Цель:** работающий код для `joint_from_axes`, `aggregate_marginal`, `coherence_check` + правки SKILL.md.
**Время:** 4–5 часов.
**Предусловия:** Phase 1 завершён.

## 3.1 `skills/forecast-confidence-applier/scripts/weighted_consensus.py`

Добавить функции:

### `joint_from_axes()`

```python
def joint_from_axes(ev_x: float, ev_y: float, rho: float = 0.0) -> dict[str, float]:
    """
    Получить веса 4 сценариев Shell-матрицы из FCA на осях.
    Используется ТОЛЬКО при opt-in (CLI флаг --apply-joint-from-axes); 
    по default scenario-builder выдаёт 0.25 каждому (D1).
    
    Args:
        ev_x: P(axis_x = HIGH), 0..1
        ev_y: P(axis_y = HIGH), 0..1
        rho: корреляция между осями, -1..1 (D6: default 0 = независимость)
    
    Returns:
        {"A": p_A, "B": p_B, "C": p_C, "D": p_D}, сумма == 1.0
    
    Mapping (как в scenario-geopolitics-ru-west):
    ⚠️ ЗЕРКАЛЬНЫЙ И НЕВЕРНЫЙ — историческая запись от 2026-05-08, оставлена как есть.
       Канон (§17 F4 и код `scenario_axis_weights.CANON_QUADRANT_MAPPING`):
       A = обе оси HIGH (стресс-полюс), D = обе LOW (detente). Ровно этот
       зеркальный маппинг жил в joint_from_axes до 2026-08-04 и уводил вес войны
       на разрядку. НЕ копировать отсюда — брать из `scenario-yaml-spec.md` §3.1.
        A: x_LOW + y_LOW       (мирный, без санкций)
        B: x_LOW + y_HIGH      (мирный, санкции)
        C: x_HIGH + y_LOW      (война, без санкций)
        D: x_HIGH + y_HIGH     (война, санкции)
    """
    p_x_low = 1 - ev_x
    p_y_low = 1 - ev_y
    
    # Joint distribution с поправкой на корреляцию
    cov_correction = rho * (ev_x * p_x_low * ev_y * p_y_low) ** 0.5
    
    p_D = ev_x * ev_y + cov_correction
    p_A = p_x_low * p_y_low + cov_correction
    p_B = p_x_low * ev_y - cov_correction
    p_C = ev_x * p_y_low - cov_correction
    
    weights = {"A": p_A, "B": p_B, "C": p_C, "D": p_D}
    assert all(0 <= w <= 1 for w in weights.values()), f"Invalid weights: {weights}"
    
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-6:
        weights = {k: v/total for k, v in weights.items()}  # нормировка
    
    return weights
```

### `aggregate_marginal()`

```python
def aggregate_marginal(by_scenario: dict, weights: dict[str, float], 
                       horizon: str, method: str = "linear") -> dict:
    """
    Детерминированный пересчёт Layer 2 marginal-значения из by_scenario блока.
    
    Args:
        by_scenario: {"A": {"values": {horizon: {"central": x, ...}}}, …}
        weights: {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25}, сумма == 1.0
        horizon: "2026-12-31" и т.д.
        method: linear | nonlinear | modal | axis_dependent
    
    Returns:
        {"central": <number>, "range": [lo, hi]}
    """
    if method == "linear":
        central = sum(
            weights[sid] * by_scenario[sid]["values"][horizon]["central"]
            for sid in ["A", "B", "C", "D"]
        )
        # range — простой охват: min(lows), max(highs)
        lows = [by_scenario[sid]["values"][horizon].get("range", [None, None])[0]
                for sid in ["A", "B", "C", "D"]]
        highs = [by_scenario[sid]["values"][horizon].get("range", [None, None])[1]
                 for sid in ["A", "B", "C", "D"]]
        lows = [x for x in lows if x is not None]
        highs = [x for x in highs if x is not None]
        return {
            "central": central,
            "range": [min(lows), max(highs)] if lows and highs else None
        }
    elif method == "modal":
        # Используется при unequal weights; modal-сценарий доминирует
        modal = max(weights, key=weights.get)
        return by_scenario[modal]["values"][horizon]
    elif method == "nonlinear":
        # Modal значение + комментарий о tail
        modal = max(weights, key=weights.get)
        return {
            **by_scenario[modal]["values"][horizon],
            "note": f"nonlinear: modal {modal} (p={weights[modal]:.2f})"
        }
    elif method == "axis_dependent":
        raise NotImplementedError("axis_dependent requires axis_value mapping context")
    else:
        raise ValueError(f"Unknown method: {method}")
```

### `coherence_check()` — НОВАЯ функция (после обсуждения two-marginal)

```python
def coherence_check(forecast_yaml: dict) -> dict:
    """
    Сравнивает Layer 1 marginal (forecast.central_estimate) с Layer 2 marginal
    (computed from by_scenario). Возвращает divergence diagnostic.
    
    Используется в conditional_on_scenarios.coherence_diagnostic блок.
    """
    layer1 = parse_central(forecast_yaml["forecast"]["central_estimate"])
    
    cond = forecast_yaml.get("conditional_on_scenarios")
    if not cond:
        return {"layer1_marginal": layer1, "layer2_marginal": None, 
                "severity": "LOW", "warning": "no conditional_on_scenarios block"}
    
    # Загружаем веса из SSOT
    scenario_path = cond["source_matrix"]
    weights = load_weights_from_scenario(scenario_path)
    
    # Берём первый horizon для diagnostic (можно расширить)
    horizon = list(cond["by_scenario"]["A"]["values"].keys())[0]
    layer2 = aggregate_marginal(cond["by_scenario"], weights, horizon, 
                                method=cond["marginal"]["method"])["central"]
    
    if layer1 is None or layer2 is None:
        return {"severity": "UNKNOWN"}
    
    divergence_pct = abs(layer1 - layer2) / abs(layer1) * 100 if layer1 != 0 else 0
    severity = (
        "LOW"    if divergence_pct < 5
        else "MEDIUM" if divergence_pct < 15
        else "HIGH"
    )
    
    warning = None
    if severity != "LOW":
        warning = (
            f"Layer 1 marginal ({layer1:.2f}) расходится с Layer 2 marginal ({layer2:.2f}) "
            f"на {divergence_pct:.1f}%. Возможные причины: asymmetric coverage, "
            f"dominant HIGH-trust source, unequal weights с непропорциональными conditional values."
        )
    
    return {
        "layer1_marginal": layer1,
        "layer2_marginal": layer2,
        "divergence_pct": divergence_pct,
        "severity": severity,
        "warning": warning
    }
```

### `parse_central()`, `load_weights_from_scenario()` — helpers

```python
def parse_central(central_estimate: str | float) -> float | None:
    """Парсит '12.7%' или '$88' или '85-90' в число (берёт центр диапазона)."""
    # Implementation — regex на проценты, доллары, диапазоны
    ...

def load_weights_from_scenario(scenario_yaml_path: str) -> dict[str, float]:
    """Читает SSOT scenario YAML, возвращает {A: weight, B: weight, ...}."""
    ...
```

## 3.2 Тесты в `tests/test_weighted_consensus.py`

```python
def test_joint_from_axes_independent():
    w = joint_from_axes(0.73, 0.65, rho=0.0)
    assert abs(w["D"] - 0.4745) < 1e-4
    assert abs(sum(w.values()) - 1.0) < 1e-6

def test_joint_from_axes_with_correlation():
    w = joint_from_axes(0.73, 0.65, rho=0.10)
    assert w["D"] > 0.4745  # positive correlation усиливает diagonals
    assert abs(sum(w.values()) - 1.0) < 1e-6

def test_aggregate_marginal_linear_equal_weights():
    by_scen = {
        "A": {"values": {"2026-12-31": {"central": 10.5}}},
        "B": {"values": {"2026-12-31": {"central": 12.5}}},
        "C": {"values": {"2026-12-31": {"central": 11.5}}},
        "D": {"values": {"2026-12-31": {"central": 13.5}}}
    }
    weights = {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25}
    result = aggregate_marginal(by_scen, weights, "2026-12-31", "linear")
    assert abs(result["central"] - 12.0) < 1e-6  # простое арифметическое среднее

def test_coherence_check_divergent():
    # Ситуация: HIGH-trust БКС dominate Layer 1, asymmetric coverage Layer 2
    # Ожидаем HIGH severity
    ...
```

## 3.3 `skills/forecast-confidence-applier/SKILL.md`

Добавить:

### `§N. Implicit-scenario фильтрация источников`

При FCA per scenario использовать только sources, чьи 
`implicit_geopolitical_scenarios.primary` или `secondary` включает целевой scenario_id. 
Веса источников взвешиваются на `trust.conditional × implicit_weight_in_scenario`.

В Phase 2 (упрощённый): использовать `trust.marginal` если `trust.conditional` отсутствует
(D4 backward compat).

### `§N+1. Coverage diagnostic`

После FCA выдавать:

```yaml
coverage_diagnostic:
  per_scenario:
    A: { sources_used: 0, confidence: DERIVED }   # ⚠ asymmetry
    B: { sources_used: 2, confidence: MEDIUM }
    C: { sources_used: 1, confidence: LOW }
    D: { sources_used: 5, confidence: HIGH }
  asymmetry_warning: "Sc-A не покрыт native sources; derived через dependency-map"
  dominant_implicit_world: D
```

### `§N+2. Two-marginal architecture`

Каждый forecast YAML содержит ДВЕ marginal-оценки:

1. `forecast.central_estimate` — Layer 1, computed by direct trust-weighted FCA на 
   источниках, scenarios игнорируются. Используется для портфельных EV-решений.

2. `conditional_on_scenarios.marginal.values` — Layer 2, computed by 
   `aggregate_marginal(by_scenario, weights)`. Используется как sanity-check, 
   не основа решений.

`coherence_diagnostic` блок отслеживает divergence; severity LOW/MEDIUM/HIGH.

**ВАЖНО:** `portfolio-scenario-stress` использует `by_scenario` НАПРЯМУЮ, не marginal. 
`weekly-review` использует Layer 1 marginal. Layer 2 marginal — диагностика only.

## 3.4 `skills/scenario-builder/SKILL.md`

### Default behavior (D1)

Все 4 сценария получают `probability: 0.25`. `modal_scenario_id: none`. `modal_flag: no_modal`.

### `§N. Шаг 5.5 — Joint weights derivation (opt-in)`

Если CLI флаг `--apply-joint-from-axes` или явная просьба пользователя:

```
1. Выполнить FCA по каждой оси (3-7 источников × 2 оси), получить ev_x, ev_y
2. Оценить ρ через references/correlation-rubric.md (default ρ=0 per D6)
3. Применить joint_from_axes(ev_x, ev_y, rho)
4. Записать результат в matrix.scenario_triggers[*].probability
5. Установить modal_scenario_id = argmax(weights)
```

**ВАЖНО:** веса записываются ТОЛЬКО в scenario YAML (SSOT). НИКОГДА не дублируются
в forecast YAMLs или macro-input.

Создать `references/correlation-rubric.md`:
- Как оценивать ρ (исторические аналоги пар событий)
- Default ρ=0 при отсутствии оснований
- Примеры: для conflict×sanctions осей в RU-geopolitics ρ≈0.10 (positive correlation)

## 3.5 `skills/macro-forecast-chain/SKILL.md`

### Output split (D1+D2)

Заменить single `macro-input-{date}.yaml` на:

```
macro-marginal-{date}.yaml    — Layer 1, для weekly-review и EV
macro-scenarios-{date}.yaml   — Layer 2, для portfolio-scenario-stress
```

### Coherence diagnostic в macro-marginal

```yaml
coherence_diagnostic:
  implicit_world_distribution: { A: <n>, B: <n>, C: <n>, D: <n>, agnostic: <n> }
  dominant_implicit_world: <id>
  inconsistency_score: 0..1     # доля факторов с противоположным implicit
  warnings:
    - factor: brent
      implicit: A
      contradicts_majority: D
      severity: HIGH
      action: "Brent в Sc-A worldview противоречит majority Sc-D. Для marginal — допустимо. Для stress — НЕ ИСПОЛЬЗОВАТЬ macro-marginal, переключиться на macro-scenarios."
```

### `§N+2. RECALIBRATE-mode (D7)`

```
macro-forecast-chain --mode RECALIBRATE [--strict]

  1. Прочитать новые веса из scenarios/{ref}.yaml (SSOT)
  2. Проверить sum == 1.0 ± 0.001
  3. Coverage check: какие сценарии теперь модальные? Хватает ли источников?
     Если modal_scenario_id изменился И coverage_quality для нового modal == DERIVED:
        → выдать предупреждение «нужен FCA для нового modal» (но не блокировать)
  4. Прогон portfolio aggregator с новыми весами:
     - Layer 2 marginal в каждом forecast YAML пересчитывается
     - `expected_pl_pct` НЕ считается (D2)
     - 4 ΔP&L точки stress остаются неизменными (они от весов не зависят)
     - Modal/hedge-target ranking обновляется
  5. Validator stale marginal:
     - Default soft: stale → auto-recalculate с info-warning
     - --strict: stale → отказ с инструкцией пересмотра вручную
  6. Время: <30 секунд, никаких LLM-вызовов
  
ВАЖНО: НЕ запускает FCA. НЕ пересчитывает Layer 1 marginal. 
       НЕ меняет conditional values. Только labels + Layer 2 marginal.
```

### `§N+3. Out-of-frame caveats (D3)`

Заменить «Unaccounted» сценарий на:

```yaml
out_of_frame_caveats:
  - severity: low
    description: |
      4 сценария Shell-матрицы конструктивно полны для axes 
      (conflict_intensity × sanctions_intensity). События вне axes 
      (черный лебедь — кибератака, природная катастрофа, политический 
      кризис в США) обрабатываются отдельным механизмом, не внутри 
      scenario-matrix probability frame.
    examples_of_out_of_frame:
      - "Кибератака на банковский сектор РФ"
      - "Катастрофа Saudi Aramco"
      - "Политический кризис в США 2026-2027"
```

## 3.6 `skills/macro-forecast-chain/references/dependency-map.md`

Обновить под conditional-формат:
- Промпт-шаблоны для каждого method (linear / nonlinear / axis_dependent / indifferent)
- Шаблон для conditional FCA per scenario (когда coverage позволяет)
- Примеры trust-weight применения per scenario

## 3.7 `skills/portfolio-scenario-stress/SKILL.md`

### Изменения (D2)

- **Вход** переключается с `macro-input-*.yaml` на `macro-scenarios-*.yaml`
- **Удалить из default output** `expected_pl_pct: <n>` и `expected_pl_rub: <n>`
- Добавить **opt-in флаг** `--include-ev` для случаев, когда EV нужен
- Добавить **modal_scenario highlight** в summary (главный сценарий, если есть)
- Добавить **robustness verdict**:

```yaml
robustness:
  positive_or_neutral_scenarios: 3   # из 4
  worst_case: { id: "B", pl_pct: -5.7 }
  best_case: { id: "D", pl_pct: +7.9 }
  spread: 13.6                       # max - min, sensitivity к мирам
  hedge_target: "Sc-B sanctions+geopol exposure"
```

### Pre-flight check на dual-shock

Проверить, что `pass_through` уже встроен в conditional CPI/usdrub. Если в bundle 
есть и shock_brent, и shock_inflation_via_brent — выдать ошибку «двойной счёт». 
Документировать в SKILL.md правила.

## 3.8 `skills/retrospective-forecast-audit/SKILL.md` (Phase 6 stub)

В Phase 2 добавить только stub:

```markdown
## §N. Conditional retrospective protocol (DRAFT — Phase 6)

Когда realized scenario известен:
  - Шаг 1: marginal_score = |source_value - actual_value|
  - Шаг 2: world_picking score = HIT/MISS на implicit_scenario
  - Шаг 3: conditional_score = N/A если их world не realized; иначе marginal_score
  - Шаг 4: trust update раздельно по 3 измерениям

Полная спецификация — Phase 6, после первого audit кейса.
```

---

# 4. Phase 3 — Migration script

**Цель:** работающий `migrate_to_conditional.py`, прогнан на 3 тестовых файлах.
**Время:** 2–3 часа.
**Предусловия:** Phase 1 + Phase 2 завершены.

## 4.1 `scripts/migrate_to_conditional.py`

Реализовать по spec из §2.4. Принимает forecast YAML + sibling MD, выдаёт обновлённый YAML с `conditional_on_scenarios` блоком.

## 4.2 Тестовые прогоны

На реальных данных через Cowork (см. парный документ Phase 5):
- `ru-rates-2026-2027-2026-05-04.yaml` — должен пройти clean
- `cny-rub-dec2026-dec2027-2026-05-04.yaml` — должен handle nonlinear partial
- `ru-cpi-2026-2027-2026-05-04.yaml` — должен парсить markdown table

## 4.3 Backup стратегия

- Перед миграцией: `<file>.yaml` → `<file>.yaml.pre-migration`
- Diff-отчёт: что изменилось в значениях (для ручного review)
- Rollback инструкция в comments скрипта
- chardet для UTF-8 / Latin-1 mojibake detection

---

# 5. Phase 4 — RECALIBRATE-mode (production-ready)

**Цель:** работающая команда `macro-forecast-chain --mode RECALIBRATE`.
**Время:** 2 часа.
**Предусловия:** Phase 2 завершён, scenario YAML содержит SSOT веса.

## 5.1 `skills/macro-forecast-chain/scripts/recalibrate.py`

```python
def recalibrate(scenario_yaml_path: Path, 
                forecasts_dir: Path,
                stress_yaml_path: Path,
                output_path: Path,
                strict: bool = False) -> RecalibrateResult:
    """
    Lazy-режим: читает новые веса, обновляет stress-test summary, 
    проверяет coverage. Никаких LLM-вызовов.
    """
    # 1. Read SSOT weights
    weights = load_weights_from_scenario(scenario_yaml_path)
    assert abs(sum(weights.values()) - 1.0) < 1e-3
    
    # 2. Recalculate Layer 2 marginals в каждом forecast YAML
    stale_marginals = []
    for forecast_path in forecasts_dir.glob("*.yaml"):
        if has_conditional_block(forecast_path):
            old, new = recalculate_layer2_marginal(forecast_path, weights)
            if abs(old - new) > 0.01:
                stale_marginals.append((forecast_path, old, new))
                if not strict:
                    write_updated_marginal(forecast_path, new)
    
    if strict and stale_marginals:
        raise StaleMarginalError(stale_marginals)
    
    # 3. Coverage check
    alerts = check_coverage_for_modal(weights, forecasts_dir)
    
    # 4. Update stress test summary (labels, modal, hedge target)
    update_stress_summary(stress_yaml_path, weights, output_path)
    
    return RecalibrateResult(
        old_weights=load_previous_weights(stress_yaml_path),
        new_weights=weights,
        stale_recalculated=stale_marginals,
        coverage_alerts=alerts,
        updated_files=[stress_yaml_path]
    )
```

## 5.2 CLI integration

```bash
$ macro-forecast-chain --mode RECALIBRATE
$ macro-forecast-chain --mode RECALIBRATE --scenario scenarios/scenario-geopolitics-ru-west-2026-05-04.yaml
$ macro-forecast-chain --mode RECALIBRATE --strict   # отказ при stale marginal
```

## 5.3 Валидаторы

- Sum of weights = 1.0 ± 0.001
- Все 4 сценария присутствуют
- Если `modal_scenario_id` сменился — проверить `coverage_per_scenario` для нового modal
- Time guard: вся операция должна укладываться в 30 секунд

---

# 6. Phase 5 — Tests + CI

**Цель:** pytest зелёный, миграция проверена.
**Время:** 2 часа.
**Предусловия:** Phase 2–4 завершены.

## 6.1 Unit tests

- `test_weighted_consensus.py`:
  - `joint_from_axes` (independent, with correlation, edge cases при ev=0/1)
  - `aggregate_marginal` (linear, nonlinear, modal, axis_dependent)
  - `coherence_check` (LOW/MEDIUM/HIGH severity, edge cases)
- `test_recalibrate.py`:
  - валидация sum
  - corner case: modal сменился
  - corner case: scenario YAML missing
  - strict vs soft mode
- `test_migration.py`:
  - 3 reference YAML миграция
  - regex extraction edge cases
  - mojibake recovery

## 6.2 Integration tests

- End-to-end: scenario YAML edit → RECALIBRATE → новый stress YAML
- Migration → load → aggregate_marginal → сравнение с pre-migration central_estimate
- Two-marginal divergence в реальных данных (БКС dominant case)

## 6.3 Linter / schema validation

- jsonschema для `conditional_on_scenarios`, `implicit_geopolitical_scenarios`
- Скрипт-валидатор в `scripts/validate_schema.py`:
  - Проверка sum-of-weights в scenario YAML
  - Проверка all-4-scenarios в by_scenario
  - Проверка numbers (не strings) в values

---

# 7. Phase 6 — Forecast-level retrospective audit (DEFERRED)

**Цель:** полная реализация conditional protocol в `retrospective-forecast-audit`.
**Время:** 1 день.
**Когда:** при первом реальном резолвед-прогнозе (≥6 мес после Phase 5).
**Предусловия:** Phase 1–5 в production, есть accumulated data о implicit_scenarios.

Содержание:
- 3D-скоринг: marginal / conditional / world_picking
- Trust update механика (раздельно по 3 измерениям)
- Conditional FCA mode для следующих циклов (источники с trust.conditional + matched implicit)
- Reanalysis старых аудитов с новой schema (опционально)

---

# 8. Phase 7 — Scenario-level meta-audit (DEFERRED, 12+ мес)

**Цель:** калибровка процесса прогнозирования (а не индивидуальных прогнозов).
**Время:** 2 дня.
**Когда:** ≥12 мес после Phase 1, есть ≥6 резолвед-сценариев.

## 8.1 Audit 0 — Robustness tracking (always-on)

```python
def robustness_audit(stress_yamls: list[Path], period: timedelta) -> RobustnessReport:
    """
    Из всех stress-тестов за period:
      - в каком % были все 4 ΔP&L ≥ 0?
      - в каком % был хотя бы 1 ΔP&L ниже -10%?
      - средний spread (max - min)
    Это калибровка качества решений, независимая от весов.
    """
```

## 8.2 Audit 1 — Калибровка весов (opt-in, conditional на использование)

Применяется только если пользователь использует unequal weights (D1 — manual override или joint_from_axes mode):

```python
def weight_calibration_audit(scenarios: list[Scenario], realizations: list[Realization]):
    """
    После 6+ резолвед матриц:
      - freq(modal_realized) vs avg(modal_probability)
      - Brier score on probability assignments
      - Calibration curve
    """
```

В Pure Shell mode (default 0.25) — N/A.

## 8.3 Audit 2 — Дискриминативность осей

```python
def axis_discriminative_power(scenarios: list[Scenario], realizations):
    """
    За период:
      - Реально ли ось разделяет factor outcomes между сценариями?
      - Within-scenario variance vs between-scenario variance
    Если between < within — ось декоративная, заменить.
    """
```

## 8.4 Audit 3 — Калибровка implicit_scenario тегов

Для каждого источника с `primary: D`: систематически точнее ли в Sc-D-резолюциях?

## 8.5 Audit 4 — Калибровка dependency-map

Для factor с method `linear`: derived оценка точнее или хуже native FCA?

## 8.6 Audit 5 — Стоимость coverage gaps

Когда Sc-A почти реализовался при coverage=0 native — насколько prediction error?

## 8.7 Audit 6 — Drift сценарной топологии

Раз в 12 мес: остались ли оси релевантными? Если конфликт закончился — `conflict_intensity` устарел.

---

# 9. Карта файлов в репозитории

```
~/Documents/Программы/claude_skills/
├── _shared-references/
│   ├── events-yaml-spec.md          ← Phase 1.1 (conditional_on_scenarios + implicit_scenario)
│   ├── audit-frontmatter-schema.md  ← Phase 1.2 (3D trust)
│   └── scenario-yaml-spec.md        ← Phase 1.3 (NEW, SSOT правила)
├── scripts/
│   ├── migrate_to_conditional.py    ← Phase 3.1 (NEW)
│   ├── migrate_to_conditional.spec.md ← Phase 1.4 (NEW)
│   └── validate_schema.py           ← Phase 5.3 (NEW)
├── skills/
│   ├── forecast-confidence-applier/
│   │   ├── SKILL.md                  ← Phase 2.3 (implicit_scenario, two-marginal)
│   │   └── scripts/
│   │       └── weighted_consensus.py ← Phase 2.1 (joint_from_axes, aggregate_marginal, coherence_check)
│   ├── scenario-builder/
│   │   ├── SKILL.md                  ← Phase 2.4 (default 0.25, Шаг 5.5 opt-in)
│   │   └── references/
│   │       └── correlation-rubric.md ← Phase 2.4 (NEW)
│   ├── macro-forecast-chain/
│   │   ├── SKILL.md                  ← Phase 2.5 (split, RECALIBRATE, out-of-frame)
│   │   ├── references/
│   │   │   └── dependency-map.md     ← Phase 2.6
│   │   └── scripts/
│   │       └── recalibrate.py        ← Phase 4.1 (NEW)
│   ├── portfolio-scenario-stress/
│   │   └── SKILL.md                  ← Phase 2.7 (no expected_pl, robustness)
│   └── retrospective-forecast-audit/
│       └── SKILL.md                  ← Phase 2.8 stub; Phase 6 full
└── tests/
    ├── test_weighted_consensus.py    ← Phase 5.1 (NEW)
    ├── test_recalibrate.py           ← Phase 5.1 (NEW)
    └── test_migration.py             ← Phase 5.1 (NEW)
```

---

# 10. Зависимости с Cowork (см. парный документ)

## Что Claude Code зависит от Cowork

| CC Phase | Нужно из Cowork |
|----------|-----------------|
| Phase 3 (migration script) | CW Phase 0 (audit) — реальные edge cases в forecasts/ |
| Phase 5 (tests) | CW Phase 0 — тестовые данные (3 reference forecasts) |
| Phase 6 (3D audit) | CW периодические updates `lib_*.md` с conditional_score data |

## Что Cowork зависит от Claude Code

| CW Phase | Нужно из Claude Code |
|----------|----------------------|
| Phase 2 (lib tagging) | CC Phase 1.1 (спека `implicit_scenario`) |
| Phase 3 (split macro-input) | CC Phase 2.5 (SKILL macro-forecast-chain обновлён) |
| Phase 4 (stress rerun) | CC Phase 2.7 (SKILL portfolio-scenario-stress обновлён) |
| Phase 5 (forecast migration) | CC Phase 3 (migration script готов) |

---

# 11. Joint timeline

```
Day 0 (1 час):  Пользователь подтверждает D1–D7 (✓ выполнено 2026-05-08)
                
Day 1 (4-5 ч):  CC Phase 1 (specs, 5 файлов) ‖
                CW Phase 0 (audit реальных данных) + CW Phase 1 (фикс весов)
                
Day 2 (4-5 ч):  CC Phase 2 (code+SKILL) ‖
                CW Phase 2 (lib tagging — после CC Phase 1.1)
                
Day 3 (3-4 ч):  CC Phase 3 (migration script) ←─── CW тестовые данные
                CW Phase 3 (split macro-input) ←── CC Phase 2.5 готова
                
Day 4 (2 ч):   CC Phase 4 (RECALIBRATE) ‖
                CW Phase 4 (stress rerun на coherent bundles)
                
Day 5 (2 ч):   CC Phase 5 (tests, CI) ‖
                CW Phase 5 (forecast migration — lazy, по запросу)
                
[Stable system]
                
Month 6+:       CC Phase 6 (3D audit) — при первом резолвед-прогнозе
Month 12+:      CC Phase 7 (scenario meta-audit) — при ≥6 резолюций
Month 18+:      Структурные коррекции (axis redesign, library расширение)
```

**Total активной работы: 5 дней parallel-split, или ~7 дней строго sequential.**

---

# 12. Контрольные точки и критерии готовности

| Phase | Done when... |
|-------|--------------|
| 1 | 4 файла спецификаций в репо, обзор пользователем, без TODO |
| 2 | pytest -k weighted_consensus зелёный; 5 SKILL.md обновлены |
| 3 | 3 reference YAML мигрированы; diff проверен; pytest зелёный |
| 4 | `--mode RECALIBRATE` отрабатывает за <30s на реальных данных |
| 5 | CI зелёный; интеграционный тест end-to-end проходит |
| 6 | (отдельный milestone, через 6+ мес) |
| 7 | (отдельный milestone, через 12+ мес) |

---

# 13. Risks / open issues

1. **Mojibake** в существующих forecast YAMLs (Latin-1 декодинг UTF-8). 
   Phase 3 migration должна `chardet`-detect и конвертить корректно. 
   Тест на UTF-8 валидность — обязательный.

2. **`Sc-D` в `cny-rub` сидит в `central_estimate`, а не в alternatives** — 
   migration script должен handle это явно как edge case.

3. **ρ=0.10 для геополитики** — использовать как пример в `correlation-rubric.md`,
   но финальное значение пользователь подтверждает в opt-in joint_from_axes.

4. **3D trust backward compat** — старые `lib_*.md` могут не иметь 3D полей. 
   Загрузчик должен tolerate 1D и 2D forms через fallback на `trust.marginal`.

5. **Synology без git** — pre-commit hook невозможен; полагаемся на validator 
   в RECALIBRATE и opt-in `--strict` flag.

6. **Implicit_scenario для не-RU доменов** (Morgan Stanley, Goldman Sachs) — 
   `agnostic_total: true`. Spec должен явно поддерживать этот случай.

---

# 14. Контакт обратной связи

Если в процессе Phase 1–5 обнаружится несоответствие архитектуры реальным данным —
поднимать в Cowork-сессии (там доступна Claude-Memory). Не пытаться править данные
из Claude Code — это ломает разделение ответственности.

При обнаружении edge case в данных, который не покрыт спекой, фиксировать как 
issue в репо и обсуждать в Cowork-сессии. Затем возвращать в Claude Code для 
обновления спеки и кода.
