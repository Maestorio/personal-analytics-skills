# Scenario YAML — SSOT-спецификация

Расширение `events-yaml-spec.md` §4 (`type: scenario-events`) — правила хранения и
обновления **весов сценариев** в `Claude-Memory/scenarios/{slug}-{date}.yaml`.

Этот файл — **единственное место** в системе, где живут вероятности 4 сценариев.
Любой forecast YAML, который ссылается на сценарную матрицу (`conditional_on_scenarios.source_matrix`),
читает веса отсюда.

Связанные документы:
- `events-yaml-spec.md` §4 — базовая схема `scenario-events`
- `events-yaml-spec.md` §5 — потребитель весов через `source_matrix`
- `HANDOFF-claude-code-phased.md` §1.5 (D1, D5, D6, D7) — архитектурные решения

---

## 1. SSOT-правила (D7 lazy aggregation)

### 1.1 Единственное место хранения весов

`scenario_triggers` — **список на ВЕРХНЕМ уровне документа**, рядом с `matrix`,
а не внутри него:

```yaml
matrix:
  date: 2026-07-01
  # … оси, домен, тема

scenario_triggers:           # ← верхний уровень, СПИСОК
  - scenario_id: A
    probability: 0.25        # ← ЕДИНСТВЕННОЕ место хранения веса сценария A
  - scenario_id: B
    probability: 0.25
  - scenario_id: C
    probability: 0.25
  - scenario_id: D
    probability: 0.25
```

> **Форма исправлена 2026-08-05 по факту.** До этого спека показывала блок
> **под `matrix`** — формы, которой нет ни в одном из шести живых файлов и
> которую не выдаёт генератор (`scenario-builder` SKILL.md, шаблон Events YAML).
> Ошибка спеки стоила трёх дефектов у трёх независимых читателей, и каждый был
> **молчаливым**: `recalibrate.load_weights` возвращала `{}` на всех живых
> матрицах; `validate_library` собирал пустой `scenario_ids` и отключал
> кросс-проверку `macro_dependency`; тестовые фикстуры обоих закрепляли выдуманные
> формы. `save-to-library` при этом требует верхний уровень **blocking** — то есть
> артефакт, собранный строго по прежней спеке, не сохранился бы.
>
> Читателям: искать на верхнем уровне, `matrix.scenario_triggers` принимать как
> легаси-терпимость. Писателям: только верхний уровень.

**Запрещено** дублировать `probability` в:

- forecast YAML (`forecasts/*.yaml`) — ни в `conditional_on_scenarios`, ни в `forecast.*`
- `macro-input-{date}.yaml` (legacy, до split в Phase 2.5)
- `macro-marginal-{date}.yaml` или `macro-scenarios-{date}.yaml` (Phase 2.5)
- stress-test YAML (`Claude-Memory/Portfolio/stress/*.yaml`)

Все потребители читают веса через `source_matrix` путь и `load_weights_from_scenario()` (Phase 2).

### 1.2 Sum invariant

```
sum(scenario_triggers[*].probability) == 1.0 ± 0.001
```

Валидатор (`scripts/validate_schema.py`, Phase 5; `recalibrate.py`, Phase 4) отвергает
файл при нарушении инварианта.

### 1.3 Пересчёт downstream

Изменение `probability` в scenario YAML → запуск `macro-forecast-chain --mode RECALIBRATE`
(Phase 4):

1. Layer 2 marginal в каждом forecast YAML с `source_matrix == <этот файл>` пересчитывается
   через `aggregate_marginal()`.
2. Stress-test summary обновляется (modal_scenario, hedge_target, robustness verdict).
3. Layer 1 marginal (`forecast.central_estimate`) **не пересчитывается** — он независим от весов.
4. Никаких LLM-вызовов; время <30 секунд.

---

## 2. Default по D1 — Pure Shell mode

При создании матрицы через `scenario-builder`:

```yaml
scenario_triggers:             # верхний уровень (§1.1), не под matrix
  - scenario_id: A
    probability: 0.25
  - scenario_id: B
    probability: 0.25
  - scenario_id: C
    probability: 0.25
  - scenario_id: D
    probability: 0.25

matrix:
  modal_scenario_id: none      # явный маркер "no modal" при equal weights
  modal_flag: no_modal          # синоним для legibility; "modal" если есть argmax

  # Type 3 (multi-matrix coexistence): явная пометка использования матрицы.
  usage_status:
    active_for_portfolio_stress: true | false   # участвует ли в portfolio-scenario-stress
    active_for_marginal_decisions: true | false # читается ли в weekly-review marginal
    superseded_by: null                          # ID более новой матрицы или null
```

### 2.1 Type 3 — Multi-matrix coexistence

В системе **могут сосуществовать несколько scenario matrices**, каждая со своей цепочкой
прогнозов. Это разрешено и нормально.

**Текущие активные матрицы (по runbook):**

- `geopolitics-ru-west` → `usage_status.active_for_portfolio_stress: true`
- `brent-dec`, `ai-capex` → `false` (reference / другой домен)
- `usd-rub-sept` → `superseded_by: <newer-id>` (deprecated)

**Инварианты:**

1. **One matrix per forecast.** Каждый forecast YAML ссылается **максимум на одну** scenario
   matrix через `source_matrix`. Если фактор семантически имеет несколько condition'ов
   (например, USD/RUB зависит и от geopolitics, и от brent matrices) — выбирается **dominant**
   matrix; остальное идёт через `upstream_snapshot` или dependency-map.
2. **Multi-conditional forecasts** (пересечение двух матриц) — **не поддерживаются** в Phase 1–5.
   Это Phase 8+, требует отдельной архитектурной работы.
3. `macro-forecast-chain` собирает stress только из матриц с `active_for_portfolio_stress: true`.

`scenario-builder` **не выводит** веса автоматически из FCA на осях. Пользователь правит
вручную в SSOT файле или явно вызывает opt-in `joint_from_axes` (см. §3 ниже).

---

## 3. `joint_from_axes(ev_x, ev_y, rho)` — opt-in рецепт (D1, D6)

Получение весов 4 сценариев из FCA на осях. Используется **только** при явной просьбе
пользователя или CLI флаге `--apply-joint-from-axes` (`scenario-builder` Шаг 5.5, Phase 2).

### 3.1 Mapping

Стандартное соответствие осей и сценариев Shell-матрицы:

```
A: x_HIGH + y_HIGH     ← HH   стресс-полюс («Затяжная осада»)
B: x_HIGH + y_LOW      ← HL
C: x_LOW  + y_HIGH     ← LH
D: x_LOW  + y_LOW      ← LL   detente-полюс («Большая сделка»)
```

> **Маппинг исправлен 2026-08-05 — до этого он был здесь ЗЕРКАЛЬНЫМ** (`A` = обе
> LOW, `D` = обе HIGH) и противоречил и канону §17 F4 в этом же файле, и коду
> (`scenario_axis_weights.CANON_QUADRANT_MAPPING`, `weights_from_axes`,
> `joint_from_axes`). Проверка прогоном: при `ev_x = ev_y = 0.8` код даёт
> `A = 0.64`, а прежняя формулировка спеки предписывала `A = 0.04`.
>
> Это не теоретический риск: зеркальный маппинг **уже жил в коде**
> `joint_from_axes` до 2026-08-04 и уводил вес войны на разрядку — он не падает
> и не выглядит подозрительно, просто переворачивает порядок сценариев. Спека
> сохраняла ту же ошибку ещё сутки после починки кода.

`x_HIGH` / `y_HIGH` — pole, на котором `axis_x` / `axis_y` принимает «эскалационное» значение
(война, санкции, и т.д.). `ev_x = P(axis_x = HIGH)`, `ev_y = P(axis_y = HIGH)` — вероятности
из FCA по каждой оси.

Для конкретной матрицы соответствие фиксируется при создании в `axis_x` / `axis_y` строках
(`events-yaml-spec.md` §4) и **не меняется** в течение жизни матрицы.

### 3.2 Формула

```python
p_x_low = 1 - ev_x
p_y_low = 1 - ev_y

cov_correction = rho * sqrt(ev_x * p_x_low * ev_y * p_y_low)

p_A = ev_x * ev_y         + cov_correction      # HH — стресс-полюс
p_D = p_x_low * p_y_low   + cov_correction      # LL — detente-полюс
p_B = ev_x * p_y_low      - cov_correction      # HL
p_C = p_x_low * ev_y      - cov_correction      # LH
```

Сумма всегда равна 1.0 при `rho ∈ [-1, +1]` (математически: cov_correction добавляется
к diagonals и вычитается из off-diagonals в равных количествах). Если численное округление
выводит сумму за `1.0 ± 1e-6` — нормировка делением на `sum`.

Все веса должны лежать в `[0, 1]`; иначе `rho` слишком экстремален для данных `(ev_x, ev_y)`,
скрипт выдаёт ошибку (Phase 2).

### 3.3 Поле `correlation_xy`

Отдельное поле в scenario YAML (D6):

```yaml
matrix:
  axis_x: "Конфликт: эскалация vs деэскалация"
  axis_y: "Санкции: ужесточение vs ослабление"
  correlation_xy: 0.10        # ρ между осями, оценка пользователя
  correlation_rationale: |
    Историческая корреляция conflict×sanctions для RU (2014–2024) ≈ 0.10:
    эскалация конфликта чаще сопровождается ужесточением санкций.
```

- **Default ρ = 0** (D6, независимость) при отсутствии оснований.
- Диапазон: `[-1, +1]`.
- Рубрика оценки — `skills/scenario-builder/references/correlation-rubric.md` (создаётся в Phase 2.4).
- Поле опционально для матриц, не использующих `joint_from_axes`.

### 3.4 Запись результата

После применения `joint_from_axes(ev_x, ev_y, rho)`:

1. Веса записываются в `scenario_triggers[*].probability` (верхний уровень, §1.1).
2. `modal_scenario_id = argmax(weights)` если max(weights) > 0.30; иначе `none`.
3. `modal_flag = "modal"` если `modal_scenario_id != none`; иначе `"no_modal"`.
4. Опциональное поле `weights_provenance` для аудита:

```yaml
matrix:
  weights_provenance:
    method: joint_from_axes
    ev_x: 0.65
    ev_y: 0.73
    rho: 0.10
    derived_at: 2026-05-08
    derived_by: "scenario-builder Шаг 5.5"
```

---

## 4. scenario_id — short format (D5)

В новых scenario YAMLs использовать **только** короткие идентификаторы:

```
A | B | C | D
```

Старые файлы с `Sc-A` / `Sc-B` / `Sc-C` / `Sc-D` мигрируются `migrate_to_conditional.py`
(Phase 3) через regex `\bSc-([ABCD])\b` → `\1`.

Маркер совместимости — поле `scenario_id_format: short` в `conditional_on_scenarios`
(потребляющий forecast YAML) и в frontmatter scenario YAML после миграции.

---

## 5. Обновление весов — три типа updates

См. `HANDOFF-claude-code-phased.md` §1.4 для детального описания.

| Type | Триггер | Что меняется в scenario YAML | Downstream |
|------|---------|------------------------------|------------|
| **A — Weight-only** | Сработал leading_indicator, новость, change of belief | только `scenario_triggers[*].probability` (+ опционально `modal_scenario_id`, `weights_provenance`) | `RECALIBRATE` (~30 сек) |
| **B — Factor baseline** | Premise одного фактора сломалась | scenario YAML не меняется; меняется один forecast YAML's `by_scenario` | FCA по фактору; `RECALIBRATE` для distribution |
| **C — Structural** | Оси сценарной матрицы устарели | весь scenario YAML переписывается через `scenario-builder`; новый `slug-{date}.yaml` | старая матрица → `status: superseded`, `superseded_by: <new>`; миграция всех forecast YAMLs |

### 5.1 Лог изменений весов

При каждом Type-A update — добавить запись в `weight_history`:

```yaml
matrix:
  weight_history:
    - date: 2026-05-08
      old: { A: 0.25, B: 0.25, C: 0.25, D: 0.25 }
      new: { A: 0.20, B: 0.30, C: 0.20, D: 0.30 }
      reason: "Leading indicator armistis-podpisan сработал; пересчёт через joint_from_axes(0.50, 0.40, rho=0.10)"
      provenance: joint_from_axes | manual
```

`weight_history` — append-only лог. Старые записи не удаляются.

---

## 6. `out_of_frame_caveats` (D3)

Заменяет ранее предлагавшийся «Unaccounted» 5-й сценарий. Документирует события, которые
лежат **вне** axes матрицы:

```yaml
matrix:
  out_of_frame_caveats:
    - severity: low                 # low | medium | high
      description: |
        4 сценария Shell-матрицы конструктивно полны для axes
        (conflict_intensity × sanctions_intensity). События вне axes
        обрабатываются отдельным механизмом, не внутри scenario-matrix
        probability frame.
      examples_of_out_of_frame:
        - "Кибератака на банковский сектор РФ"
        - "Катастрофа Saudi Aramco"
        - "Политический кризис в США 2026-2027"
```

Эти события **не** имеют веса в `scenario_triggers` и не учитываются в `aggregate_marginal()`.
Они идут отдельным треком через `hypothesis-stress-tester` или индивидуальные forecast YAMLs.

---

## 7. Валидация (Phase 5 `scripts/validate_schema.py`)

Обязательные проверки для scenario YAML:

1. `sum(scenario_triggers[*].probability) == 1.0 ± 0.001`
2. `scenario_id` уникальны и принадлежат `{A, B, C, D}` (не `Sc-A`)
3. Все 4 сценария присутствуют (не подмножество)
4. `correlation_xy` ∈ `[-1, +1]` если присутствует
5. `weights_provenance.method` ∈ `{joint_from_axes, manual}` если присутствует
6. `weight_history` — массив, каждая запись с `date`, `old`, `new`, `reason`, `provenance`

Несоблюдение → отказ от записи в `save-to-library`; `revise-memory-remote` помечает issue.

---

## 8. Anti-patterns

❌ **Веса в forecast YAML или macro-input** — действующие веса живут в файле сайта `scenarios/stress-weights-<матрица>.json`, исходные — в scenario YAML; больше нигде.
❌ **Удаление сценария из `scenario_triggers`** при изменении весов — даже probability=0.0 с rationale лучше, чем удаление (нарушит inv «все 4 сценария»).
❌ **Изменение mapping `axis_x`/`axis_y` ↔ scenario_id** в течение жизни матрицы — это Type-C update, требует нового файла.
❌ **Запись `Sc-A` в новых файлах** — short format обязателен (D5).
❌ **`correlation_xy: 0.95`** без серьёзного исторического обоснования — рекомендуемый диапазон `[-0.3, +0.3]`; экстремальные значения требуют `correlation_rationale` с конкретными данными.
❌ **Удаление `weight_history`** при upgrade — append-only лог, нужен для retrospective-forecast-audit.

---

## Осевые якоря и веса по горизонтам (2026-08-04)

### `axes_meta.<ось>.quantitative_anchor`

Живые матрицы уже несут осевое убеждение — вероятность того, что ось окажется в
HIGH-полюсе:

```yaml
downstream_sensitivity_hints:
  axes_meta:
    axis_x:
      name: conflict_intensity
      domain: {low_label: "перемирие/заморозка", high_label: "война продолжается"}
      quantitative_anchor:
        low_value: 0.0
        high_value: 1.0
        modal_expected_value: 0.6            # P(ось X в HIGH)
        modal_expected_value_by_horizon:     # опционально, 2026-08-04
          h6: 0.85
          h12: 0.65
          h24: 0.40
```

`modal_expected_value_by_horizon` — расширение под убеждение, зависящее от срока.
Промежуточные горизонты **не интерполируются**: не заданный горизонт берёт скаляр
оси, а если нет и его — равные веса (Pure Shell D1) с явной пометкой.

### Полярность — обязательна к соблюдению

Маппинг квадрантов на id сценариев — канон §17 F4 `matrix.polarity`
(`stress_pole: A`, `detente_pole: D`):

| id | ось X | ось Y | смысл в матрице geopolitics-ru-west |
|---|---|---|---|
| A | HIGH | HIGH | война + ужесточение («Затяжная осада») |
| B | HIGH | LOW | война + фрагментация санкций |
| C | LOW | HIGH | перемирие + holding санкций |
| D | LOW | LOW | перемирие + снятие («Большая сделка») |

**Полярность обязана быть ОБЪЯВЛЕНА** блоком `matrix.polarity`, если матрица
используется для вывода весов из осей. Канон верен для `geopolitics-ru-west`, но
по смыслу квадрантов ему следуют не все: у `usd-rub-sept-2026` и `ai-capex-2026`
полярность зеркальная (A — благополучный мир), у `brent-dec-2026` стресс вообще
в C. Без объявления `mapping_from_matrix` возвращает `None`, и вызывающий обязан
решить сам — умолчания нет.

Всего матриц в библиотеке шесть (четыре `active`, две `superseded`), и **`matrix.polarity` объявлена ровно у одной** — `geopolitics-ru-west-2026-07-01` (2026-08-05, при переходе на веса по горизонтам). У остальных блока нет, поэтому `mapping_from_matrix` вернёт `None` и вызывающий обязан решить сам.

Перепутанная полярность **не падает и не выглядит подозрительно** — она зеркалит
веса. Канон перевода осей в веса — `scripts/scenario_axis_weights.py` (внутри скилла;
источник — общий каталог, инжектится через `bundle_scripts`). Кросс-скилловые ссылки на `scripts/` чужого
скилла запрещены.

### `p_by_horizon` — где живёт в SSOT

Убеждение зависит от срока: на полгода модален один мир, на два года другой.
Веса по горизонтам живут **внутри элемента `scenario_triggers[]`**, рядом со
скаляром `probability` — там же, где и все веса (§1.1), отдельного блока нет:

```yaml
scenario_triggers:
  - scenario_id: A
    label: "Затяжная осада"
    probability: 0.15        # = вес на primary_horizon; обязателен рядом
    p_by_horizon:
      h6:  0.28
      h12: 0.15
      h24: 0.24
```

Требования: блок задан **у всех** сценариев, сумма 1 на каждом горизонте,
скаляр `probability` обязателен рядом. Отсутствие блока → скаляр (по умолчанию
0.25 — Pure Shell D1).

**Веса выводимы из убеждений по осям, и источник стоит хранить рядом.** В
`downstream_sensitivity_hints.axes_meta.<ось>.quantitative_anchor` есть
`modal_expected_value_by_horizon: {h6: …, h12: …, h24: …}` — вероятность
**HIGH-полюса** оси на каждый срок. `scripts/scenario_axis_weights.py`
(`weights_by_horizon`) переводит их в веса квадрантов, и тогда четыре числа на
горизонт не висят без происхождения. Промежуточные горизонты **не
интерполируются**: убеждение на срок — суждение, выдумывать его нельзя.

> **Полярность обязана быть объявлена** (`matrix.polarity`), иначе перевод осей
> в веса невозможен: неизвестно, какой `scenario_id` какому углу матрицы
> соответствует. Ошибка здесь не падает, а зеркалит веса.

**Проводка до стресса.** `build_stress_stub.py` переносит блок из SSOT в
`scenarios.<id>.p_by_horizon` стресс-артефакта, **только если он покрывает все
горизонты прогона**; при частичном покрытии веса не переносятся, а в стаб
выводится причина. Половинчатый перенос дал бы заведомо неработающий стаб —
движок на смешанном входе останавливается.

### `p_by_horizon` у потребителя

Портфельный стресс принимает веса по горизонтам как
`scenarios.<id>.p_by_horizon: {hNN: вес}`.

**Кто читает горизонтные веса** (после PSS-9, 2026-08-05): ценовой слой
(`compute_per_position.py`), Слой 2 (`compute_bond_carry.py` — облигации,
money-market, голый кэш), `portfolio-integrated-view` (carry, идио-слой через
`compute_catalyst_contribution`, `total_return_by_horizon`, Monte Carlo),
JS-зеркало вьюера (`viewer.js::_scenarioP`) и подписи ячеек `joint_tail` в
coherence-audit. Ноги total-return считаются на одном убеждении.

Скаляр `p` обязателен не как рудимент: по нему считается диагностика нормировки
(сумма весов и её severity), и он же — деградация на горизонтах, которых в блоке
нет. Блок, заданный **части** сценариев, останавливает расчёт: смешивать
горизонтные веса со скаляром нельзя.

`macro-forecast-chain --mode RECALIBRATE` матрицы с `p_by_horizon`
**поддерживает** (MFC-5 шаг 2, 2026-08-06): каждая дата `marginal.values`
агрегируется весами своего горизонта — hNN сопоставляются датам матрицы
(`horizon_intermediate` + `horizon`, порядково по возрастанию). Прогноз с
горизонтом вне дат матрицы (h18-файлы) пропускается **целиком** и громко
(`SKIP:`/`skipped_files`): интерполяция весов запрещена, частичный пересчёт
оставил бы Layer 2 одного файла на двух наборах убеждений. Дефекты формы блока
(частичный блок, разные наборы ключей, сумма ≠ 1 на любом горизонте) — явный
отказ, а не тихая деградация на скаляр.

**Файл сайта старше матрицы.** Если рядом с матрицей лежит
`stress-weights-<имя матрицы>.json` (веса владельца со страницы «Стресс»; даты сроков — `scenarios/horizons.json`, тоже пишет только сайт),
RECALIBRATE берёт веса из него: на дату прогноза — линейная интерполяция по
дням между соседними сроками сайта, раньше первого и позже последнего срока —
значение ближайшего (`scenario_weights.weights_on_dates`). Тогда дат «вне
матрицы» нет и h18-файлы пересчитываются. Негодный файл сайта — отказ, а не
откат на матрицу. Веса в матрице при этом — исходные на её дату: расхождение с
файлом сайта нормально и вопросом владельцу не является.
