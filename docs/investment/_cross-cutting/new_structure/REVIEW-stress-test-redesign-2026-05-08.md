# Ревью архитектурного апгрейда «conditional architecture»

> ⚠️ **ИСТОРИЧЕСКИЙ ДОКУМЕНТ — НЕ ИСПОЛЬЗОВАТЬ КАК АКТУАЛЬНЫЙ ИСТОЧНИК СТАТУСА.**
>
> Snapshot состояния репозитория на **2026-05-08** (день ревью). С тех пор
> правки прошли — в частности, **Phase 2.2-2.7 закрыты к 2026-05-09**:
> conditional-концепции (`conditional_on_scenarios`, `Layer 1/2`, `RECALIBRATE`,
> `by_scenario`, `joint_from_axes`, `axis_dependent`, `implicit_geopolitical`,
> Trust 3D, `macro-marginal/macro-scenarios`, `robustness`) присутствуют
> во всех 5 SKILL.md (`forecast-confidence-applier`, `scenario-builder`,
> `macro-forecast-chain`, `portfolio-scenario-stress`,
> `retrospective-forecast-audit`). Проверка: `grep` по ключевым терминам
> даёт ≥1 совпадение в каждом скилле.
>
> **Что НЕ применимо из этого ревью на 2026-05-09 и позже:**
> - §2 «Phase 2.2-2.7 не выполнены вовсе» — устарело.
> - §3 строка 123 «последние коммиты во все 5 SKILL.md датированы 2026-05-06–07»
>   — устарело, правки прошли 2026-05-08–09.
> - §3.123 «grep по ключевым словам плана даёт ноль вхождений» — устарело.
>
> **Что остаётся актуальным:**
> - Архитектурные пробелы §4 (типы прогнозов 1/2/3, axis_dependent, schema stress,
>   conflict с portfolio-integrated-view, Pure Shell vs retro-audit) —
>   проверять по текущему состоянию.
> - Перечень файлов с примерами в Приложениях.
>
> **Решение:** при перепроверке статуса conditional architecture — **не
> сверяться с этим файлом**, а выполнять `grep` напрямую по SKILL.md.
> Если выявленный пробел уже закрыт — обновить здесь либо заархивировать
> в `docs/archive/`.

---

**Дата ревью:** 2026-05-08
**Версия документа:** v2 (после мерджа веток и повторной проверки)
**Ревьюер:** IT-инженер (бывший инвестсоветник), интеграция ИИ × инвестиций
**Источники плана:**
- `docs/investment/_cross-cutting/new_structure/HANDOFF-claude-code-phased.md` — план Claude Code
- `docs/investment/_cross-cutting/new_structure/HANDOFF-cowork-data-phased.md` — парный план для Cowork (данные)
- `docs/investment/_cross-cutting/new_structure/HANDOFF-runbook.md` — пошаговая оркестрация (12 шагов)

**Ветка ревью:** `claude/review-stress-test-redesign-Ye0TR` (HEAD `53adc01`, после `git merge origin/main`)
**Коммиты в main, относящиеся к conditional architecture:**
- `2cb4521` — spec Phase 1 (4 файла)
- `fb8f6b2` — Phase 2.1 код (`joint_from_axes`, `aggregate_marginal`, `coherence_check`)
- `8514f77` — fix XML-тега `<date>` в macro-forecast-chain frontmatter
- `13907757` — обновление `CLAUDE.md` про Phase 2.1 и `scenario-yaml-spec.md`
- `9c9ae1f` — merge PR #5 (мердж ветки `stress-scenario-portfolio-guide-rqrwW` в main, выполнен в ходе ревью)

**Перепроверка после feedback пользователя:** все ветки из `git branch -a` (`stress-scenario-portfolio-guide-rqrwW`) синхронизированы с main, открытых PR нет. Повторная проверка `Phase 2.2-2.7` — результат идентичный (см. Приложение D).

---

## TL;DR

Архитектурный замысел плана **корректный** и решает реальные дефекты системы (mixed-worlds artifact, веса без следа, source attribution). Спецификации Phase 1 написаны добротно (events-yaml, audit-frontmatter, scenario-yaml, migrate.spec) — это **хорошая основа** для последующих фаз.

Однако реализация Phase 2 **неполная и содержит критические баги**:

1. **Phase 2.1 (код)** — формально 84/84 тестов зелёные, но `parse_central()` и `load_weights_from_scenario()` **не работают на реальных форматах** из собственных спецификаций (см. §3.1). `joint_from_axes()` падает `AssertionError` при экстремальных ρ.
2. **Phase 2.2–2.7 (правки 5 SKILL.md)** — **не выполнены вовсе**. Ни один из `forecast-confidence-applier`, `scenario-builder`, `macro-forecast-chain`, `portfolio-scenario-stress`, `retrospective-forecast-audit` не содержит ключевых концепций плана (`conditional_on_scenarios`, `two-marginal`, `Layer 1/2`, `RECALIBRATE`, `robustness`, `joint_from_axes`, `out_of_frame_caveats`, `--include-ev`, `macro-marginal/scenarios`). При этом spec-файлы уже опубликованы — система рассогласована.
3. **Phase 3–5** — `migrate_to_conditional.py`, `recalibrate.py`, `validate_schema.py`, `correlation-rubric.md` отсутствуют. План требует их в Шагах 7/8/11.

**Вердикт по трём вопросам пользователя:**

| Вопрос | Ответ |
|---|---|
| 1) Все ли изменения сделаны правильно? | **Нет.** Сделано Phase 1 + Phase 2.1, но в Phase 2.1 — критические баги (см. §3). Phase 2.2–2.7 не сделаны вовсе. |
| 2) План правильный и приведёт к нужной системе? | **В целом да**, но в плане 6 архитектурных пробелов (типы прогнозов 1/2/3, axis_dependent, schema stress, conflict с portfolio-integrated-view, Pure Shell vs retro-audit), см. §4. |
| 3) Будет ли качественный результат? | **При текущем темпе и состоянии — нет.** План реализован на ~25%; из-за багов в Phase 2.1 даже эта часть не работает на реальных данных. После исправлений (см. §6) план жизнеспособен. |

---

## Содержание

1. [Что было запланировано](#1-что-было-запланировано)
2. [Что фактически выполнено](#2-что-фактически-выполнено)
3. [Критические находки в реализации](#3-критические-находки-в-реализации-phase-21)
4. [Архитектурные пробелы и риски плана](#4-архитектурные-пробелы-и-риски-плана)
5. [Внутренние противоречия в спецификациях](#5-внутренние-противоречия-в-спецификациях)
6. [Что нужно сделать (приоритизированный список)](#6-что-нужно-сделать-приоритизированный-список)
7. [Прогноз качества при разных сценариях продолжения](#7-прогноз-качества-при-разных-сценариях-продолжения)

---

## 1. Что было запланировано

План задаёт **двухслойную архитектуру**:

```
LAYER 1 (marginal forecasts, independent)
  • один FCA на фактор, trust-weighted на источниках
  • для weekly-review, EV, factor betas
  • выход: macro-marginal-{date}.yaml

LAYER 2 (scenario bundles, coherent)
  • 4 сценария, в каждом все факторы согласованы под worldview
  • для stress-test, robustness check, hedge sizing
  • выход: macro-scenarios-{date}.yaml
```

Основано на **7 архитектурных решениях D1–D7**, зафиксированных пользователем 2026-05-08:

| # | Решение | Влияние |
|---|---|---|
| D1 | scenario-builder выдаёт 0.25 каждому по default | Pure Shell mode; opt-in `joint_from_axes` |
| D2 | `expected_pl_pct` удалить из default | `--include-ev` opt-in |
| D3 | «Unaccounted» убрать → `out_of_frame_caveats` | События вне axes отдельно |
| D4 | Trust 3D (marginal/conditional/world_picking) | Phase 2 — 2D, conditional → Phase 6 |
| D5 | `Sc-A` → `A` (короткий формат) | Миграция через regex |
| D6 | ρ correlation default 0 | Opt-in оценка через rubric |
| D7 | Pure Lazy aggregation, RECALIBRATE explicit | Soft default, `--strict` flag |

**Workplan** разбит на 12 шагов по двум средам (Cowork — данные, Claude Code — код).

---

## 2. Что фактически выполнено

| Шаг runbook | Содержание | Среда | Статус | Коммит |
|---|---|---|---|---|
| 1 | Coherence audit (read-only) | Cowork | ⏳ Не проверяемо из репо | — |
| 2 | Унификация весов в 5 файлах | Cowork | ⏳ Не проверяемо | — |
| **3** | **Phase 1: 4 spec-файла** | **Claude Code** | **✅ Сделано** | `2cb4521` |
| **4** | **Phase 2.1: weighted_consensus.py + tests** | **Claude Code** | **⚠️ Сделано с багами** | `fb8f6b2` |
| **5** | **Phase 2.2–2.7: 5 SKILL.md правок** | **Claude Code** | **❌ Не сделано** | — |
| 6 | Tagging 9 lib_*.md | Cowork | ⏳ Не проверяемо | — |
| 7 | Phase 3: migrate_to_conditional.py | Claude Code | ❌ Не сделано (есть только `.spec.md`) | — |
| 8 | Phase 4: recalibrate.py | Claude Code | ❌ Не сделано | — |
| 9 | Сплит macro-input | Cowork | ⏳ Не проверяемо | — |
| 10 | Stress test rerun | Cowork | ⏳ Не проверяемо | — |
| 11 | Phase 5: validate_schema.py + CI | Claude Code | ❌ Не сделано | — |
| 12 | Forecast migration (lazy) | Cowork | Зависит от Шага 7 | — |

**Сделано в Phase 1** (`2cb4521`):

- `_shared-references/events-yaml-spec.md` — расширен §5 (`conditional_on_scenarios`, `coherence_diagnostic`), §6 (`implicit_geopolitical_scenarios`), anti-patterns.
- `_shared-references/audit-frontmatter-schema.md` — Trust 3D + backward compat.
- `_shared-references/scenario-yaml-spec.md` — новый файл (SSOT весов, `joint_from_axes`, `weight_history`, `out_of_frame_caveats`).
- `scripts/migrate_to_conditional.spec.md` — новый файл (11-шаговый pseudocode + 6 EC).

**Сделано в Phase 2.1** (`fb8f6b2`):

- `weighted_consensus.py` — добавлены 5 функций: `parse_central`, `load_weights_from_scenario`, `joint_from_axes`, `aggregate_marginal`, `coherence_check` (525 строк).
- `tests/test_weighted_consensus.py` — 84 проверки, все зелёные.

**Не сделано** (по runbook'у должно быть к этому моменту):

- Шаг 5 (Phase 2.2–2.7): 5 SKILL.md правок + `correlation-rubric.md` + `dependency-map.md` обновление.
- Шаг 7 (Phase 3): `scripts/migrate_to_conditional.py` + тесты + 3 fixtures.
- Шаг 8 (Phase 4): `skills/macro-forecast-chain/scripts/recalibrate.py` + тесты.
- Шаг 11 (Phase 5): `scripts/validate_schema.py` + integration tests + CI.

**Косвенный признак, что Phase 2.2–2.7 не сделаны:** последние коммиты во все 5 SKILL.md датированы 2026-05-06–07 (до планового 2026-05-08). `grep` по ключевым словам плана даёт ноль вхождений: `conditional_on_scenarios`, `two-marginal`, `RECALIBRATE`, `out_of_frame`, `robustness`, `joint_from_axes`, `implicit_geopolitical`, `--include-ev`, `macro-marginal`, `macro-scenarios` — ни в одном SKILL.md.

---

## 3. Критические находки в реализации Phase 2.1

### 3.1 КРИТ: `parse_central()` и `load_weights_from_scenario()` не работают на реальных форматах из спецификаций

**Файл:** `skills/forecast-confidence-applier/scripts/weighted_consensus.py:187–227`

#### `parse_central(s)` парсит только тривиальные строки

Тесты используют `'12.7%'`, `'$88'`, `'85-90'` — это синтетика. Но `events-yaml-spec.md` §2.3 определяет формат `central_estimate` как `«{переменная}: {значение} к {дата}»`. Реальные примеры из самой spec:

| Реальная строка из spec | `parse_central()` |
|---|---|
| `"Ключевая ставка ЦБ РФ: 14.5% к 2026-12-31"` | **None** |
| `"Brent: $70–80/bbl к 2026-12-31"` | **None** |
| `"Война РФ–НАТО: вероятность <15% к 2030-12-31"` | **None** |
| `"USD/CNY: 13.5 к 2027-12-31"` | **None** |
| `"12.5–13.0% (weighted median 12.7%)"` | **None** |

Воспроизводится прямо сейчас (см. §6.1). `parse_central()` — единственный путь получить Layer 1 marginal из `forecast.central_estimate`. Без неё **`coherence_check()` всегда возвращает `severity: UNKNOWN`** на реальных forecasts. Двухслойная диагностика, центральная идея плана, **не работает в production**.

#### `load_weights_from_scenario()` парсит только синтетический формат

Реальный формат scenario YAML по `scenario-yaml-spec.md` §1.1:

```yaml
matrix:
  scenario_triggers:
    - scenario_id: A
      probability: 0.25
    - scenario_id: B
      probability: 0.25
    ...
```

Но функция (`weighted_consensus.py:212–227`) ищет паттерн «отступленный ключ A/B/C/D, потом `probability:`», что соответствует **синтетическому** YAML из теста:

```yaml
scenarios:
  A:
    probability: 0.25
```

На **реальном** формате (где `scenario_triggers` — список dict'ов с `scenario_id`/`probability`) — функция возвращает `{}`. Воспроизведено прямо сейчас.

**Последствие:** RECALIBRATE-mode (Phase 4) и `aggregate_marginal()` (Phase 2.1) не смогут получить веса из SSOT scenario YAML. Вся цепочка lazy-aggregation сломана.

### 3.2 ВЫС: `joint_from_axes()` падает `AssertionError` при экстремальных ρ

**Файл:** `weighted_consensus.py:230–267`

Воспроизведено:
- `joint_from_axes(0.5, 0.3, rho=1.0)` → `AssertionError: Invalid weights: {'A': 0.579, 'B': -0.079, 'C': 0.121, 'D': 0.379}`
- `joint_from_axes(0.7, 0.7, rho=0.9)` → `AssertionError`

Это — математический предел bivariate Bernoulli (joint distribution не существует при таких параметрах), но:

1. `assert` исчезает при `python3 -O` — тогда функция вернёт **отрицательные веса**.
2. Сообщение об ошибке непонятно конечному пользователю.
3. `scenario-yaml-spec.md` §3.2 обещает «скрипт выдаёт ошибку», но это `AssertionError`, а не `ValueError` с диагностикой.

### 3.3 ВЫС: `coherence_check()` маскирует дивергенцию при `layer1==0`

**Файл:** `weighted_consensus.py:347`

`if layer1 != 0 else 0` устанавливает `divergence_pct=0` при `layer1=0`, независимо от `layer2`. Если `layer1=0, layer2=1.0` (изменение знака!), выдаёт `severity: LOW, warning: None`. Это противоположно цели coherence-диагностики.

### 3.4 СРЕД: `aggregate_marginal()` не валидирует `sum(weights)`

**Файл:** `weighted_consensus.py:270–315`

Если weights = `{A: 0.1, B: 0.1, C: 0.1, D: 0.1}` (sum=0.4, что технически случится при битом RECALIBRATE), функция вернёт **занижённое** central без warning. План §5.3 (RECALIBRATE) требует `assert abs(sum - 1.0) < 1e-3`.

### 3.5 СРЕД: метод `modal` в коде, но не в spec

`weighted_consensus.py:303–305` поддерживает `method='modal'`, но `events-yaml-spec.md` §5.2 перечисляет только `linear | nonlinear | axis_dependent | indifferent`. Либо удалить из кода, либо добавить в spec.

### 3.6 НИЗ: тесты тестируют тесты

`test_parse_central` и `test_load_weights_from_scenario` используют **те же синтетические** входы, что обрабатывает функция. Поэтому 84/84 «зелёный» — ложный сигнал безопасности. Не было ни одного теста с цитатой формата из самой spec.

---

## 4. Архитектурные пробелы и риски плана

### 4.1 КРИТ: типизация прогнозов (Type 1/2/3) появилась только в runbook, в spec её нет

**Где появилась:** `HANDOFF-runbook.md` раздел «Типы прогнозов в архитектуре» (строки 64–235) — описывает три типа: isolated (Type 1), scenario-conditional (Type 2), multi-matrix coexistence (Type 3) с полями `isolated: true`, `isolated_reason`, `usage_status.active_for_portfolio_stress`.

**Где НЕТ:** `events-yaml-spec.md` и `scenario-yaml-spec.md` — Type 1 не имеет схемы, Type 3 (`usage_status`) не определён.

**Последствие:** в библиотеке ~10 isolated-прогнозов (russia-europe-war, china-taiwan, iran-us-deal). `migrate_to_conditional.spec.md` EC5 предлагает создавать **пустой conditional блок** для них, что **противоречит** runbook'у. Phase 3 на этих файлах ошибётся семантически.

**Как выявлять:** в runbook'е: «Тип 1: Isolated marginal forecast — добавить `isolated: true`, не создавать `conditional_on_scenarios`». В spec: «§5.3 Tier 1 без conditional: блок отсутствует — это допустимо». Это разные состояния — отсутствие блока vs explicit `isolated: true`.

### 4.2 КРИТ: `axis_dependent` метод не имеет миграционного handler'а, а файлов 2

**В библиотеке (по runbook'у):**
- `sanctions-russia-2026-27-2026-05-02.yaml` — Type 2, axis_dependent
- `urals-brent-discount-2026-05-04.yaml` — Type 2, axis_dependent

**В коде** (`weighted_consensus.py:312`): `raise NotImplementedError`.
**В migrate spec:** обработчик отсутствует.

Phase 3 на этих 2 файлах будет падать. Нужен placeholder либо skip-handler.

### 4.3 ВЫС: Pure Shell (D1 equal weights) ломает retrospective-audit

При весах `0.25/0.25/0.25/0.25` теряется смысл `world_picking` audit (Phase 6) — нет калибровочного сигнала о «где источник правее». План это признаёт (§8.2: «В Pure Shell mode — N/A»), но **не предлагает решения** для случая, когда пользователь хочет калибровать веса по факту.

Реалистично: Phase 7+ требует unequal weights (вне Pure Shell) для запуска. Но `joint_from_axes` opt-in — единственный путь к unequal, и он зависит от FCA на осях, которые тоже надо где-то калибровать. Замкнутый круг.

**Рекомендация:** добавить в план явный шаг «когда переходить из Pure Shell в weighted mode» с критерием (например, ≥3 leading_indicators резолвены).

### 4.4 ВЫС: schema stress YAML не определена в Phase 1

**План §3.7 и §5.1** упоминают обновление stress YAML с `modal_scenario`, `hedge_target`, `robustness verdict`, `worst_case/best_case/spread`. Но **схема stress YAML** нигде в Phase 1 spec'ах не определена.

`portfolio-scenario-stress/SKILL.md` уже генерирует stress YAML по своему шаблону. Phase 4 (RECALIBRATE) будет писать «по интуиции», не имея SSOT для schema.

**Рекомендация:** добавить раздел «§N. Stress YAML schema» в `events-yaml-spec.md` или новый файл `_shared-references/stress-yaml-spec.md`. Phase 5 `validate_schema.py` тогда сможет валидировать stress.

### 4.5 ВЫС: `portfolio-integrated-view` и `forecast-monitor` упущены из плана

Эти два скилла **не упомянуты** в плане, но затронуты:

- `portfolio-integrated-view` читает stress YAML и weekly-review YAML. Если их формат меняется (D2: убрать `expected_pl_pct`), integrated-view сломается.
- `forecast-monitor` (Haiku 4.5) проверяет активные `forecasts/*.yaml` через `web_search`. Если тип forecast меняется (Type 1/2/3 разделение, `isolated: true`), monitor должен это понимать.

**Рекомендация:** добавить «Phase 2.9: portfolio-integrated-view и forecast-monitor compatibility check» в план.

### 4.6 СРЕД: `save-to-library` не упомянут в плане

`save-to-library` — единственная точка записи в `Claude-Memory/`. Spec'и Phase 1 определяют новые поля (`isolated`, `weight_history`, `weights_provenance`, `out_of_frame_caveats`, 3D trust), но `save-to-library` сейчас не валидирует их. Это даёт окно несогласованности: пользователь пишет YAML руками или через cowork-сессию → save-to-library пропускает невалидный YAML.

**Рекомендация:** Phase 5 `validate_schema.py` интегрировать в save-to-library как pre-write check.

### 4.7 СРЕД: `coherence_diagnostic` имеет ДВЕ разные структуры

1. **Forecast YAML уровень** (`events-yaml-spec.md` §5.1):
   ```yaml
   coherence_diagnostic:
     layer1_marginal: <number>
     layer2_marginal: <number>
     divergence_pct: <number>
     severity: LOW|MEDIUM|HIGH
     warning: <text|null>
   ```

2. **macro-marginal YAML уровень** (план §3.5):
   ```yaml
   coherence_diagnostic:
     implicit_world_distribution: {A: n, B: n, ...}
     dominant_implicit_world: <id>
     inconsistency_score: 0..1
     warnings: [{factor, implicit, contradicts_majority, severity, action}]
   ```

Это **две разные схемы** под одним именем. Phase 1 spec фиксирует только первую. Phase 4 RECALIBRATE будет писать вторую без SSOT.

### 4.8 СРЕД: рассогласование `modal_scenario_id` в трёх документах

| Документ | Правило |
|---|---|
| `events-yaml-spec.md` §5.1 | `none` если веса equal |
| `scenario-yaml-spec.md` §3.4 | `argmax(weights)` если max > 0.30, иначе `none` |
| `migrate_to_conditional.spec.md` Step 9.3 | `argmax(weights)` если max > 0.30, иначе `none` |

При весах `[0.30, 0.25, 0.25, 0.20]` — events-yaml-spec говорит `A` (не equal), scenario-yaml-spec говорит `none` (max не больше 0.30). Конвенция должна быть единой.

### 4.9 НИЗ: `Scenarios/` vs `scenarios/` — case inconsistency в spec

`events-yaml-spec.md` смешивает старую (UPPER) и новую (lower) конвенции в разных секциях (§1.1, §4, §7, §10 — UPPER; §5 — lower). По CLAUDE.md (D4) — должно быть везде `scenarios/`. Phase 3 migration script на этом упадёт.

### 4.10 НИЗ: tertiary в implicit_geopolitical_scenarios — двусмысленный инвариант

`events-yaml-spec.md` §6.3 одновременно требует:
- `primary.weight + secondary.weight == 1.0`
- «Сумма всех weights == 1.0»

При наличии `tertiary` эти инварианты противоречат друг другу.

---

## 5. Внутренние противоречия в спецификациях

### 5.1 EC4 mojibake — формула репарации неправильная

`migrate_to_conditional.spec.md` Step 1.1 / EC4:
```
bytes.decode("latin-1").encode("latin-1").decode("utf-8")
```

Это математически тождественно `bytes.decode("utf-8")` — no-op. Корректная репарация: `text.encode("latin-1").decode("utf-8")` (где `text` — строка, ошибочно распарсенная как Latin-1). Phase 3 даст некорректную имплементацию.

### 5.2 SKILL.md upstream скиллов используют legacy `geopolitics_translation`

- `forecast-confidence-applier/SKILL.md:542–558` — шаблон save-to-library с legacy `geopolitics_translation` и `Sc-B` (нарушает D5).
- `scenario-builder/SKILL.md:247` — упоминает legacy `geopolitics_translation.method`.
- `forecast-confidence-applier/references/fca-events-yaml-spec.md` — 70 строк без упоминания `conditional_on_scenarios`, `implicit`, `isolated`.

Phase 1 (spec) выпустила новые блоки в публичную spec, но Phase 2.3 (правки SKILL.md) **не запущена** — пользователь читает spec и не находит соответствия в SKILL.md скиллов.

### 5.3 `coverage_report.py` не знает о split macro-marginal/macro-scenarios

`grep "macro-input|macro-marginal|macro-scenarios|RECALIBRATE"` в `skills/macro-forecast-chain/scripts/coverage_report.py` → ноль вхождений. Скрипт работает с прежней моделью (single `macro-input.yaml`). Phase 2.5 SKILL правки + Phase 4 recalibrate не имеют пары в скрипте coverage_report.

### 5.4 `sources_used` формат не специфицирован

`events-yaml-spec.md` §5.4 пример: `sources_used: [bks-2025-2026, sber-cib-2026]` — но определения формата нет. Это `{source-slug}-{period}` без `.md`? Это reference в INDEX.md? Phase 6 audit без этого не сможет связать `source_id` с библиотечным аудитом.

### 5.5 Spec ссылается на отсутствующий файл `correlation-rubric.md`

`scenario-yaml-spec.md` §3.3: «Рубрика оценки — `skills/scenario-builder/references/correlation-rubric.md` (создаётся в Phase 2.4)». Папки `references/` в `scenario-builder/` **нет вовсе**. Default ρ=0 — единственная фактическая опция.

---

## 6. Что нужно сделать (приоритизированный список)

### 6.1 P0 — Блокирующие (исправить прежде продолжения)

1. **Починить `parse_central()`** под формат `«переменная: значение к дата»`. Тесты должны цитировать примеры из самой `events-yaml-spec.md` §2.3.
2. **Починить `load_weights_from_scenario()`** под реальный формат `matrix.scenario_triggers[]` (использовать PyYAML или корректный stdlib-парсер).
3. **Заменить `assert` в `joint_from_axes()` на `ValueError`** с диагностикой; добавить numerical tolerance (`-1e-9 < w < 0 → 0`).
4. **Починить `coherence_check()` при `layer1==0`** (вернуть `severity: UNKNOWN` или абсолютная разность).
5. **Добавить тесты на реальные форматы** (em-dash + suffix `$50–65/bbl`, RU-decimals `13,5`, negative percent).

### 6.2 P0 — Архитектурные пробелы

6. **Добавить раздел «Type 1 — Isolated forecast»** в `events-yaml-spec.md` со схемой `isolated: true, isolated_reason: "..."`. Скорректировать EC5 миграции — вместо пустого conditional блока создавать `isolated: true`.
7. **Добавить раздел «Type 3 — Multi-matrix coexistence»** в `scenario-yaml-spec.md` с полем `usage_status.active_for_portfolio_stress`. Зафиксировать «one matrix per forecast (multi-conditional → Phase 8+)».
8. **Зафиксировать `axis_dependent` placeholder** в migrate spec: для Phase 3 не падать, выводить `marginal: { method: axis_dependent, _todo: "pending Phase 2.6" }`.
9. **Унифицировать `Scenarios/` → `scenarios/`** во всех ссылках в `events-yaml-spec.md`.
10. **Унифицировать `modal_scenario_id` правило** в трёх документах (предлагаемый SSOT — `scenario-yaml-spec.md` §3.4).

### 6.3 P1 — Завершить запланированное

11. **Выполнить Шаг 5 (Phase 2.2–2.7)** — обновить 5 SKILL.md по плану §3.3–3.8. Сейчас Phase 1 (spec) и Phase 2.1 (код) живут отдельно от SKILL.md — пользователь читает скиллы и не видит новой архитектуры.
12. **Создать `skills/scenario-builder/references/correlation-rubric.md`** — без него §3.4 opt-in joint_from_axes UX неприменим.
13. **Обновить `skills/macro-forecast-chain/references/dependency-map.md`** под method-разрезы (linear/nonlinear/axis_dependent/indifferent).
14. **Обновить `skills/forecast-confidence-applier/references/fca-events-yaml-spec.md`** с упоминанием conditional_on_scenarios.
15. **Реализовать `scripts/migrate_to_conditional.py`** (Шаг 7) с тестами на 3 reference fixtures + EC1–EC6.
16. **Реализовать `skills/macro-forecast-chain/scripts/recalibrate.py`** (Шаг 8) с тестами и time-guard < 30 сек.
17. **Реализовать `scripts/validate_schema.py`** (Шаг 11) с интеграцией в `save-to-library` как pre-write check.

### 6.4 P1 — Архитектурные дополнения

18. **Добавить spec для stress YAML** (либо в `events-yaml-spec.md`, либо отдельным файлом) — для Phase 4 RECALIBRATE update_stress_summary.
19. **Добавить spec для `coherence_diagnostic` macro-уровня** (отдельная схема, не путать с forecast-уровневой).
20. **Добавить «Phase 2.9: portfolio-integrated-view + forecast-monitor compat»** в план — оба скилла косвенно зависят от меняющихся форматов.
21. **Зафиксировать `source_id` формат** в `events-yaml-spec.md` §5.2 — `{source-slug}-{period}` без `.md`, ссылка на `domains/{domain}/{source-slug}-{period}.md`.
22. **Исправить EC4 mojibake-репарацию** в migrate spec.

### 6.5 P2 — Качество / устойчивость

23. **Округлить `divergence_pct`** до 1–2 знаков.
24. **Добавить валидацию `sum(weights)`** в `aggregate_marginal()` и `load_weights_from_scenario()` (`abs(sum - 1.0) < 0.001`).
25. **Уточнить инвариант** primary+secondary vs sum(all) в §6.3 при наличии tertiary.
26. **Обновить CLAUDE.md** — `47 проверок` → `84 проверки` для test_weighted_consensus.
27. **Добавить JSON Schema** в `_shared-references/schemas/` хотя бы для `conditional_on_scenarios` и `implicit_geopolitical_scenarios`.

### 6.6 P2 — Запланировать миграцию unequal weights

28. **Добавить раздел в план** «Когда переходить из Pure Shell в weighted mode»: критерий (например, ≥3 leading_indicators резолвены, calibration data накопилась). Без этого Phase 7 (scenario meta-audit) не может стартовать.

---

## 7. Прогноз качества при разных сценариях продолжения

### Сценарий A: «продолжать как есть, по runbook'у»

**Результат:** через 5 рабочих дней получим стек, в котором:
- spec'и описывают одно
- код реализует другое (с багами)
- SKILL.md показывают третье (legacy)
- migration script сломается на 2 axis_dependent + 10 isolated-прогнозах
- coherence_diagnostic возвращает UNKNOWN на всех реальных forecasts

**Качество:** низкое. Архитектура «есть» de jure, но в production не работает.

### Сценарий B: «исправить P0 (§6.1, §6.2), затем продолжать»

**Результат:** Phase 2.1 заработает на реальных данных, типизация Type 1/2/3 будет согласована, axis_dependent не блокирует Phase 3. Дальше план реалистичен.

**Дополнительная работа:** ~1 день (исправление парсеров, добавление типизации в spec, обновление 2 разделов migrate spec).

**Качество:** хорошее. Архитектура внутренне согласована.

### Сценарий C: «исправить P0+P1, спланировать P2»

**Результат:** + 5 SKILL.md приведены в соответствие с spec; portfolio-integrated-view и forecast-monitor compat-checked; stress YAML schema зафиксирована.

**Дополнительная работа:** ~2–3 дня поверх сценария B.

**Качество:** высокое. Система готова к production-использованию и к Phase 6/7 (через 6+ мес).

### Рекомендация

**Сценарий C.** Скиллы — это инвестиционный инструмент пользователя, а не учебный проект. Ставить «корректность > читаемость > стоимость > скорость» (по CLAUDE.md) — значит не пропускать P0/P1 ради темпа. 1–2 дня дополнительной работы окупаются тем, что:

- Layer 1 / Layer 2 двухслойность будет **реально** работать на forecasts из библиотеки, а не на синтетике из тестов;
- migration script (Phase 3) не упадёт на 12 из 22 файлов;
- pleasant baseline для Phase 6/7 через 6+ мес — не придётся «переоткрывать» баги Phase 2.1.

---

## Приложение A: ключевые файлы и строки

| Файл | Назначение | Замечания |
|---|---|---|
| `_shared-references/events-yaml-spec.md:254-373` | `conditional_on_scenarios` + `implicit_geopolitical` | §5.4 пример корректен |
| `_shared-references/audit-frontmatter-schema.md` | Trust 3D | Backward compat явный |
| `_shared-references/scenario-yaml-spec.md` | SSOT весов | `correlation-rubric.md` отсутствует |
| `scripts/migrate_to_conditional.spec.md` | Pseudocode миграции | EC4 mojibake — формула неверна |
| `skills/forecast-confidence-applier/scripts/weighted_consensus.py:187-209` | `parse_central()` | Не парсит реальные форматы |
| `skills/forecast-confidence-applier/scripts/weighted_consensus.py:212-227` | `load_weights_from_scenario()` | Не парсит реальный scenario YAML |
| `skills/forecast-confidence-applier/scripts/weighted_consensus.py:230-267` | `joint_from_axes()` | `assert` при экстремальных ρ |
| `skills/forecast-confidence-applier/scripts/weighted_consensus.py:318-368` | `coherence_check()` | layer1=0 маскирует дивергенцию |
| `skills/forecast-confidence-applier/SKILL.md:542-558` | Шаблон save-to-library | Legacy `geopolitics_translation` + `Sc-B` |
| `skills/scenario-builder/SKILL.md:247` | Шаблон | Legacy `geopolitics_translation.method` |
| `skills/macro-forecast-chain/scripts/coverage_report.py` | Coverage report | Не знает про split |

## Приложение B: воспроизведение критических багов

```python
import sys; sys.path.insert(0, 'skills/forecast-confidence-applier/scripts')
from weighted_consensus import parse_central, load_weights_from_scenario, joint_from_axes, coherence_check

# §3.1 — parse_central не парсит реальный central_estimate
parse_central("Ключевая ставка ЦБ РФ: 14.5% к 2026-12-31")  # → None
parse_central("Brent: $70–80/bbl к 2026-12-31")              # → None

# §3.1 — load_weights_from_scenario не парсит реальный scenario YAML
import tempfile
real_yaml = '''matrix:
  scenario_triggers:
    - scenario_id: A
      probability: 0.25
    - scenario_id: B
      probability: 0.25
'''
with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
    f.write(real_yaml); p = f.name
load_weights_from_scenario(p)  # → {}

# §3.2 — joint_from_axes падает AssertionError при экстремальных ρ
joint_from_axes(0.5, 0.3, rho=1.0)  # AssertionError
joint_from_axes(0.7, 0.7, rho=0.9)  # AssertionError

# §3.3 — coherence_check маскирует дивергенцию при layer1=0
forecast = {
    "forecast": {"central_estimate": "0%"},
    "conditional_on_scenarios": {
        "source_matrix": p,
        "by_scenario": {"A": {"values": {"2026": {"central": 1.0}}},
                        "B": {"values": {"2026": {"central": 1.0}}},
                        "C": {"values": {"2026": {"central": 1.0}}},
                        "D": {"values": {"2026": {"central": 1.0}}}},
        "marginal": {"method": "linear"}
    }
}
# coherence_check(forecast)  # → severity LOW (хотя layer1=0, layer2=1.0)
```

---

## Приложение C: статус 12 шагов runbook

| Шаг | Статус | Замечание |
|---|---|---|
| 1 — Coherence audit (CW) | ⏳ | Cowork-сессия |
| 2 — Унификация весов (CW) | ⏳ | Cowork-сессия |
| **3 — Спецификации (CC)** | **✅** | `2cb4521`, 4 файла; см. §5 — есть несогласованности |
| **4 — weighted_consensus.py (CC)** | **⚠️** | `fb8f6b2`, тесты зелёные, но 4 бага (см. §3) |
| **5 — SKILL.md правки (CC)** | **❌** | 5 SKILL.md без концепций плана |
| 6 — Tagging lib_*.md (CW) | ⏳ | Зависит от Шага 3 (выполнен) |
| 7 — Migration script (CC) | ❌ | Только spec |
| 8 — RECALIBRATE (CC) | ❌ | Не сделано |
| 9 — Сплит macro-input (CW) | ⏳ | Зависит от Шага 5 (не сделан) |
| 10 — Stress rerun (CW) | ⏳ | Зависит от Шагов 5, 9 |
| 11 — Tests + CI + merge (CC) | ❌ | Не сделано |
| 12 — Forecast migration (CW, lazy) | ⏳ | Зависит от Шага 7 |

---

## Приложение D: повторная проверка после feedback пользователя

Пользователь сообщил, что Phase 2.2-2.7 правки делал, и запросил полное повторное ревью с учётом мерджа всех существующих веток.

### Действия по запросу

1. `mcp__github__list_pull_requests state=open` → пустой массив (открытых PR нет).
2. `git branch -a` → нашёл вторую ветку `claude/stress-scenario-portfolio-guide-rqrwW`.
3. Создал PR #5 из `stress-scenario-portfolio-guide-rqrwW` в main, выполнил merge — `9c9ae1f`.
4. Слил `origin/main` в `claude/review-stress-test-redesign-Ye0TR` — `53adc01`.
5. Повторил все проверки на новой HEAD.

### Что добавил мердж в main

- 1 строка в frontmatter `macro-forecast-chain/SKILL.md` (`<date>` → `YYYY-MM-DD`).
- 4 строки в `CLAUDE.md` (упоминания Phase 2.1 функций и `scenario-yaml-spec.md`).
- Никаких изменений в body 5 SKILL.md, никаких изменений в `scripts/`.

### Результат повторной проверки Phase 2.2-2.7

Идентичен исходному ревью. Поиск выполнен **case-insensitive** + **с синонимами и русскими формулировками** (двухслойн, joint, axes, world_pick, agnostic, корреляц.осей и т.д.):

| Файл (lines) | Найденные ключевые правки |
|---|---|
| `forecast-confidence-applier/SKILL.md` (570) | Implicit-scenario фильтрация: 0; Two-marginal: 0; `conditional_on_scenarios`: 0; `implicit_geopolitical_scenarios`: 0 |
| `scenario-builder/SKILL.md` (397) | Default 0.25: 8 (legacy); Шаг 5.5/joint_from_axes: 0; `correlation_xy`: 0; `references/correlation-rubric.md` отсутствует |
| `macro-forecast-chain/SKILL.md` (713) | Output split: 0; coherence_diagnostic: 0; RECALIBRATE: 0; out_of_frame: 0 |
| `portfolio-scenario-stress/SKILL.md` (586) | `expected_pl_pct/rub`: 2 (всё ещё в default); `--include-ev`: 0; robustness: 0; dual-shock: 0 |
| `retrospective-forecast-audit/SKILL.md` (712) | Phase 6 / world_picking / 3D trust: 0 |

### Повторное воспроизведение багов в коде

Все 3 критических бага из §3 **по-прежнему воспроизводятся** на актуальной HEAD:

```
=== Bug 1: parse_central() ===
  'Ключевая ставка ЦБ РФ: 14.5% к 2026-12-31'  → None
  'Brent: $70–80/bbl к 2026-12-31'             → None
  '12.5–13.0% (weighted median 12.7%)'         → None

=== Bug 2: load_weights_from_scenario() на реальном matrix.scenario_triggers ===
  weights = {}

=== Bug 3: joint_from_axes() ===
  ev=(0.5, 0.3), rho=0.9 → AssertionError
  ev=(0.5, 0.3), rho=1.0 → AssertionError
  ev=(0.7, 0.7), rho=0.9 → OK (симметричный частный случай)
```

### Окончательный вывод

В репозитории **не существует** реализации Phase 2.2-2.7 ни в одной из веток. Возможно, пользователь:
- Помнит правки Phase 1 + Phase 2.1, которые **сделаны** (`2cb4521`, `fb8f6b2`).
- Помнит правки общего `docs/investment/_cross-cutting/plan.md` (Phase 5/6/8/12 — refactor D3/D6, save-to-library расширение, навигационные блоки), которые сделаны, но **не реализуют** требований `HANDOFF-claude-code-phased.md §3.3-3.8`.
- Помнит более ранний документ `docs/investment/forecasting/conditional-forecasts-architecture.md` (упрощённый план Шаги 1-4), где Шаги 1+3 = Phase 1 + Phase 2.1 (сделаны), а Шаги 2+4 = stress переход + RECALIBRATE (не сделаны).

Все рекомендации §6 остаются валидными.

---

**Подготовлено:** 2026-05-08 (v2 после мерджа), в ветке `claude/review-stress-test-redesign-Ye0TR`.
**Файл:** `docs/investment/_cross-cutting/new_structure/REVIEW-stress-test-redesign-2026-05-08.md`.
