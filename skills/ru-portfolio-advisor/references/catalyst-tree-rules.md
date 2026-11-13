# Catalyst Tree Generation Rules

При генерации `weekly-review-stock-<date>.yaml` (и `weekly-review-bond-<date>.yaml`)
для каждой позиции создавай catalyst tree по следующим правилам.

Каноническая методология и формулы — `docs/investment/portfolio/methodology.md` §1.
Структура YAML — `references/events-yaml-spec.md` §12.

---

## 1. Hard rules (R2 mitigation)

1. **Source required.** Если для catalyst нет явного источника (URL, document,
   analyst name + report ID) — НЕ пиши catalyst в YAML. Пиши `catalyst: []` для
   этой позиции.

2. **`date_window` required (R3, schema v2).** Каждый catalyst обязан иметь
   `date_window` (форматы — `references/yaml-schemas.md` §11.3). Принадлежность
   горизонту **вычисляет consumer** детерминированно из `date_window` (катализатор
   «в горизонте h», если начало окна ≤ конца горизонта). **НЕ пиши поле `in_horizon`** —
   оно удалено в v2, drift-валидатор заблокирует его присутствие. Катализаторы за
   пределами всех горизонтов можно оставить в YAML (consumer сам их отфильтрует
   per-horizon) либо не писать, если они нерелевантны.

3. **Source quality flag (R9):**
   - `HIGH` — primary source (e-disclosure, ГОСА протокол, рейтинговое агентство, IR-releases)
   - `MEDIUM` — sell-side analyst с проверяемым именем + датой отчёта
   - `LOW` — Smart-lab, Пульс, общая аналитика без attribution
   - При `LOW`: дополнительный дисконт ×0.5 (на этапе агрегатора, не в YAML),
     CI extra-wide (×1.5 на этапе advisor'а)

   **Отдельно от качества — атрибуция источника (R11, обязательна с 2026-08-16):**
   `source_trust: {analyst, subdomain}`. Это другая ось: `source_quality` отвечает
   «насколько твёрд сам факт», `source_trust` — «чей это сигнал», и по нему
   потребитель применяет матрицу доверия из `INDEX.md`. Раньше матрица
   сопоставлялась с прозаическим `source` и не срабатывала никогда (прогон 08-15:
   28 IGNORE-записей, 0 отфильтрованных катализаторов из 105). Значения и таблица
   случаев — `references/trust-hierarchy.md` §R11. Собственная оценка advisor —
   `{analyst: advisor, subdomain: self}`, а не пропуск поля.

4. **Сценарная привязка — из SSOT-матрицы, не из стресса (RPA-7).**
   Сценарные ID для `macro_dependency` / `active_scenarios` /
   `upside_by_scenario` берутся из **активной сценарной матрицы**
   `Claude-Memory/scenarios/scenario-*-{date}.yaml` (`status: active`, блок
   `scenario_triggers` — id + label). Матрица существует независимо от
   стресс-теста; **«стресс-файл ещё не собран» — НЕ причина пропустить
   привязку** (ретро-кейс 08-06: оба обзора выпустили 110/110 катализаторов
   без `macro_dependency` с этой отговоркой — идио-слой integrated-view
   оказался полностью развязан со сценарным, каждый катализатор получил
   плоский дисконт 0.7 вместо сценарной массы; агрегатор теперь поднимает
   это HIGH-оговоркой `idio_layer_unlinked`).

   Для каждого катализатора привязка — **рассмотренное решение, а не
   пропуск**: либо ID сценария (событие мир-зависимо: снятие санкций,
   разрядка, эскалация), либо явный `macro_dependency: null` для
   действительно scenario-independent событий (дивотсечка, MSFO release).
   Сценарная независимость скилла не нарушается: привязка декларирует
   зависимость события от мира, а не встраивает «при сценарии X делать Y».

---

## 2. Kind: binary vs quantitative (METH-1, 2026-05-13)

**Каждый catalyst обязан иметь `kind`** — это явная классификация природы
феномена.

### 2.1 Decision tree

Задай 3 вопроса:

1. **Дискретное событие?** Можно ли описать catalyst фразой
   «либо произошло, либо нет» (дивотсечка, M&A, MSFO release, лицензия, snyatie
   sanctions, выкуп)?
   → `kind: binary`

2. **Непрерывная величина по сценариям?** Имеет ли смысл вопрос «насколько
   catalyst сработает в этом сценарии» (re-rating, NIM compression, market
   share growth, rate cut effect, margin expansion)?
   → `kind: quantitative`

3. **Сомневаешься?** Запусти классификатор:
   ```bash
   python3 skills/ru-portfolio-advisor/scripts/classify_catalyst.py \
     --catalyst-json '{"id": "...", "trigger": "..."}'
   ```
   - HIGH confidence → следуй suggestion.
   - MEDIUM/LOW → читай reasoning, override с явным basis в `macro_dependency_basis`.

### 2.2 Поля по kind

#### `kind: binary`

```yaml
- id: dividend_record_date_2025
  kind: binary
  trigger: "Otsechka reestra ~20 iyulya 2026 ..."
  date_window: "2026-07"           # consumer вычисляет принадлежность горизонту (нет in_horizon)
  p: 0.88                          # ∈ (0, 0.95]; вероятность события
  upside_pct: 3
  upside_ci_pct: [0, 5]
  source: "..."
  source_quality: HIGH
  macro_dependency: null           # null = scenario-independent
  # ИЛИ:
  # active_scenarios: ["A"]        # binary, возможно только в части сценариев
```

#### `kind: quantitative`

```yaml
- id: rate_cut_rerating_2026
  kind: quantitative
  trigger: "Snizhenie KS 14.5% → 9.5% k 2027 → rost multiplikatorov P/B"
  date_window: "2026-Q3 to 2027-Q1"   # диапазон A..B; начало окна сравнивается с концом горизонта
  upside_by_scenario:              # обязательно все 4 сценария
    A: 18
    B: 10
    C: 10
    D: 0
  upside_ci_by_scenario:           # обязательно
    A: [8, 30]
    B: [3, 17]
    C: [3, 17]
    D: [0, 0]
  source: "advisor estimate"
  source_quality: MEDIUM
  # p НЕ ПРИСУТСТВУЕТ для quantitative
  # macro_dependency опционально (доминирующий сценарий для отчётности)
```

### 2.3 Заполнение `upside_by_scenario` для quant

Для каждого из 4 сценариев нужно оценить **величину эффекта при условии этого
сценария**. Источники:

- Stress YAML factor values для конкретного сценария.
- Macro-marginal forecasts (Layer 2 by_scenario из forecast YAML).
- Прямая логика «во сколько раз эффект усиливается/ослабевает».

**Пример rate-cut catalyst для SBER (на 20-мес горизонте):**
- Sc-A: КС снижается до 9.5% быстро → max re-rating (+18%)
- Sc-B: КС снижается до 11% медленно → moderate (+10%)
- Sc-C: КС снижается до 11.5% → moderate (+10%)
- Sc-D: КС задерживается выше 12% → null (0%)

Не оставляй TODO_LLM в финальном YAML. Если данных недостаточно — лучше:
- (a) Перенести catalyst в `kind: binary` с консервативной p; или
- (b) Удалить catalyst (риск чрезмерной идиосинкратики); или
- (c) Заполнить все 4 одинаковым значением (`scenario-independent` quant)
  с явной оговоркой в `macro_dependency_basis`.

### 2.4 Probability assignment (только для binary)

Использовать historical base rates где возможно:
- Дивидендное решение от стабильного payer (SBER) → P = 0.85+
- M&A в текущем regulatory environment → P = 0.05–0.15
- Sanctions tail event → P = 0.10–0.20
- Catalyst > 6 мес → P = p × 0.7 (автоматический дисконт)
- Catalyst > 12 мес → P = p × 0.5
- Source quality `LOW` НЕ применяется к p на этапе advisor'а — это сделает агрегатор.

Максимум P = 0.95 (всегда есть uncertainty). Минимум не ограничен.

### 2.5 Confidence interval rules

Для `upside_ci_pct` (binary) и `upside_ci_by_scenario` (quantitative):
- Если есть historical analog → CI = ±50% от mean (e.g., upside 25% → CI [12, 38])
- Если нет analog (новая компания / событие) → CI = ±100% (e.g., upside 25% → CI [0, 50])
- Source quality LOW → extra-wide (×1.5 от базового CI)
- Никогда не писать point estimate без CI

---

## 3. Macro-overlap filter

**Не писать catalyst для эффектов, полностью улавливаемых макро-бетами**
в стресс-тесте — это дублирование с double-count в integrated-view.

| Эффект | В стресс? | Catalyst пишем? |
|---|---|---|
| КС → equity цена через линейную бету | да | нет (бета captures) |
| Нелинейный re-rating мультипликатора при пороге КС | нет | да, quant |
| USD/RUB → FX-облигации reprice | да | нет |
| Brent → нефтегаз | да | нет |
| Дивотсечка | нет | да, binary |
| MSFO release | нет | да, binary |
| Snyatie sanctions | нет | да, binary с active_scenarios |
| Market share growth от competitive dynamics | нет | да, quant |
| Margin compression от структурных изменений | нет | да, quant |
| Capex overrun specific to company | нет | да, binary tail risk |

Когда сомневаешься: catalyst должен capture **что-то, чего стресс не учитывает**.
Если эффект сводится к factor × beta — не пиши catalyst.

---

## 4. Типичные catalysts по секторам

### Banks
- `rate_cut_re_rating` → **quantitative**, upside_by_scenario {A,B,C,D}
- `nim_compression_risk` → **quantitative**, asymmetric (упрощённо: D=0 если NIM сжатие происходит в "благоприятных" сценариях)
- `dividend_decision` → **binary**, p ≈ 0.85
- `cet1_buffer_change` → **binary** (regulatory) или quant, по характеру
- `sanctions_tail` → **binary** с `active_scenarios` (specific tail)

### Oil & Gas
- `discount_to_brent_change` → **quantitative** (continuous)
- `tax_regime_change` → **binary** (политический)
- `dividend_capacity_change` → **quantitative** (следствие FCF)
- (нефтяная цена не пишется отдельным catalyst — она embedded в macro stress)

### Tech / IT
- `growth_acceleration` → **quantitative** (рост revenue, GMV)
- `regulatory_relief` → **binary** (политический)
- `monetization_milestone` → **quantitative** (gradual ramp-up)
- `capital_intensity_change` → **quantitative** (partial macro, rate-driven)
- `ai_infra_monetization` → **quantitative** (gradual)

### Pharma
- `regulation_approval` → **binary**
- `clinic_opening` → **binary** (event), или **quantitative** (gradual rollout)
- `product_launch` → **binary**
- `government_program_inclusion` → **binary**

### Retail
- `dividend_resumption` → **binary**
- `lfl_acceleration` → **quantitative** (partial macro, consumer demand)
- `format_innovation_payoff` → **quantitative**

### Utilities
- `tariff_review` → **binary** (regulatory)
- `dividend_policy_change` → **binary**

### Облигации (bonds)
- `redemption` → **binary**
- `credit_event` → **binary** с `active_scenarios` для tail-risk сценариев
- `coupon_reinvestment_risk` → **quantitative** (depends on rate path)
- `rate_cut_capital_gain` → **quantitative** (continuous reprice от КС)

---

## 5. ИИС-3 verdict constraints (R10)

```python
if stock.on_iis:
    if stock.advisor_verdict == "SELL":
        # Сменить на HOLD
        advisor_verdict_constraints.append(
            "iis_3_hold_lock: позиция на ИИС-3, продажа разрушит налоговую льготу"
        )
    if stock.advisor_verdict == "TRIM":
        # Сменить на HOLD
        advisor_verdict_constraints.append(
            "iis_3_partial_lock: trim возможен только при cessation льготы — не рекомендуется"
        )
```

---

## 6. Verification priority assignment (C5 — расширенное)

`verification_priority` — **DERIVED, ставит скрипт**: `assemble_artifact.py stamp-report` save-to-library после
записи обзора считает его `constraint_engine.compute_verification_priority` и перезаписывает поле; модель его не
заполняет (в стабе `null`), из прошлого обзора оно не переносится. Это «приоритет перепроверки перед действием», а не важность бумаги. После глубокого
разбора (Mode 4/8), сменившего вердикт BUY→HOLD, приоритет спадает сам.

```python
ACTIONABLE = {"BUY", "TRIM", "SELL", "ADD"}
# HIGH — действие СЕЙЧАС или разбор не сделан (нужна верификация прямо сейчас)
if advisor_verdict in ACTIONABLE:                      # actionable сейчас
    return "HIGH"
if gate_status in ("review_needed", "new_position", "review_aging"):   # нужен разбор: флаг, новая, срок вышел
    return "HIGH"
# MEDIUM — действие ОТЛОЖЕНО (actionable-soon) или неопределённость
if unconstrained_verdict in ACTIONABLE:                # намерение под constraint'ом (MOEX HOLD/TRIM) — ждём
    return "MEDIUM"
if any(c.verdict_on_trigger in ACTIONABLE             # действующее условие сработает позже (дата/цена)
       for c in active_conditions):                     # строки выборки apply_condition.py digest
    return "MEDIUM"
if advisor_verdict_confidence < 0.6:
    return "MEDIUM"
if any(c.kind == "binary" and c.macro_dependency        # скрытое крит. событие в low-prob сценарии
       and scenarios[c.macro_dependency].p < 0.2 for c in catalysts):
    return "MEDIUM"
return "LOW"
```

**HOLD + HIGH** валидно ТОЛЬКО при review-pending (gate `review_needed`/`new_position`). Отложенное
действие (div-capture, price-gate) — это **MEDIUM**, не HIGH (иначе HIGH заливается). save-to-library
предупреждает (warning), если приоритет рассинхронен с пересчётом (`_priority_check`: контекст гейта и условий
строит `validate-weekly-review-stock --file … --root {root}` из последних решений и действующих условий).

---

## 7. Pre-emit checklist (защита от drift)

### Catalyst (для каждого item в catalyst[]):

- [ ] `kind` задано явно (`binary` или `quantitative`)
- [ ] Если `binary`: есть `p ∈ (0, 0.95]` + `upside_pct` + `upside_ci_pct`
- [ ] Если `quantitative`: есть `upside_by_scenario` со всеми 4 сценариями + `upside_ci_by_scenario`
- [ ] Если `quantitative`: НЕТ поля `p`
- [ ] `source` и `source_quality` присутствуют
- [ ] `source_trust: {analyst, subdomain}` присутствует (R11) — для собственной оценки `{advisor, self}`, для первички `{issuer_disclosure, primary}`; пропуск = катализатор выпадает из фильтра доверия у потребителя
- [ ] `date_window` задан (consumer вычисляет принадлежность горизонту; поля `in_horizon` НЕТ — v2)
- [ ] Сценарные ID в `upside_by_scenario` / `active_scenarios` / `macro_dependency` — из активной SSOT-матрицы `scenarios/` (Hard rule 4); со stress YAML совпадут автоматически, т.к. стресс читает ту же матрицу
- [ ] Привязка рассмотрена для КАЖДОГО катализатора: ID сценария или явный `null` (scenario-independent). Если в итоге 0 катализаторов с привязкой на весь обзор — это подозрительно (идио-слой развяжется со сценарным), объяснить в summary почему

### Fundamental Gate (METH-2)

См. `docs/investment/portfolio/new_met.md` §2.1, §3, `analysis-process.md` Шаг 7.5.

- [ ] Статус гейта — из выборки `security_digest` (модуль (б)); копию `gate_status_snapshot` в weekly-review не писать
- [ ] Если Mode 1 обнаружил hard trigger по позиции с inherited `reviewed_*` — `flags.gate_review_required: true` у бумаги (open_trigger — с вопросом владельцу)
- [ ] Mode 1 решений не пишет — гейт меняет только решение разбора
- [ ] Mode 4 при deep dive — запись в `decisions:` шапки отчёта (вердикт → гейт, `review_by` → срок)
- [ ] Mode 8 — записи в `decisions:` шапки отчёта для всех тикеров с изменениями
- [ ] Verdict (advisor_verdict) согласован с gate × macro таблицей (см. analysis-process.md Шаг 7.5)
- [ ] Если gate=under_review/aging — verdict не INCREASE
- [ ] Если gate=broken — verdict REDUCE/EXIT с stability cap (40% за цикл)

### Срез ограничений (`user_constraints`) — форма

- [ ] Срез взят из выхода `scripts/reconcile_constraints.py` на дату обзора (условия + план владельца), не из
      прошлого обзора и не руками
- [ ] Каждая запись: `derived: true`, `as_of`, ровно одно из `condition_id` / `plan_field`, `summary`
- [ ] `unconstrained_verdict` ≠ `advisor_verdict` ⇒ срез непуст (TRIPLET RULE)
- [ ] Новое ограничение — условием через Режим 9 или словом плана, не записью в YAML

Validator (`save-to-library` → `assemble_artifact.py validate-weekly-review-stock|bond`, F2.6) проверит форму
автоматически; протокол — `references/analysis-process.md` Шаг 9.5.

---

## 8. Anti-patterns

❌ Catalyst без даты или с фразой «когда-то»
❌ Catalyst без источника, основанный на «общем мнении»
❌ `kind: quantitative` без полного `upside_by_scenario` (все 4 сценария обязательны)
❌ `kind: quantitative` с заполненным полем `p` (uncertainty в CI, не в p)
❌ `kind: binary` без `p` или с `p > 0.95`
❌ P > 0.95 (нарушение R-MAX)
❌ Ссылка на Telegram-канал без archive
❌ Дублирование одного события несколькими catalysts
❌ `macro_dependency` / `active_scenarios` на несуществующий scenario id
❌ Числовое предсказание без CI
❌ ИИС-3 позиция с `advisor_verdict: SELL` или `TRIM` без constraints
❌ Catalyst для эффекта, уже captured макро-бетами в стресс-тесте (см. §3)
❌ Использовать `p` для непрерывных феноменов (rate cut величина, margin compression
   уровень, market share growth темп) — это концептуальная ошибка (см. METH-1)
