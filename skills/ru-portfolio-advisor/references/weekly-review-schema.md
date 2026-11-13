# Weekly Review YAML — схема обзора (schema 2)

Действующая схема еженедельного обзора: `schema_version: 2`, несколько горизонтов
(`horizons` / `horizon_ends` / `primary_horizon`), у катализатора нет `in_horizon` — попадание в
горизонт потребитель считает из `date_window`. Горизонты и Monte Carlo подробно —
`references/yaml-schemas.md` §11. Файлы со `schema_version` ≠ 2 не принимают ни валидаторы
save-to-library, ни integrated-view (мигратор — `portfolio-scenario-stress/scripts/migrate_v1_to_v2.py`).

**Контракт между:** `ru-portfolio-advisor` (producer) → `portfolio-integrated-view` (consumer)
**Файл:** `Portfolio/weekly-reviews/weekly-review-stock-{date}.yaml` (облигации — `weekly-review-bond-{date}.yaml`)

---

## 1. Принципы дизайна

| Принцип | Применение |
|---|---|
| **Confidence intervals everywhere** | Каждое числовое предсказание → `{value, ci: [lo, hi]}` или `{value, ci_pct: [lo, hi]}` |
| **Source required for catalysts** | Catalyst без `source` field не пишется в YAML вообще |
| **Macro dependency explicit** | Каждый catalyst опционально привязан к stress-сценарию через `macro_dependency` |
| **Горизонты из стаба** | `horizons` / `horizon_ends` / `primary_horizon` ставит стаб, модель их не меняет; `advisor_verdict` — на `primary_horizon`. Катализатор вне горизонта отбрасывает потребитель по `date_window` |
| **Caveats inherited** | Все caveats из YAML наследуются в integrated-view |
| **Schema versioned** | `schema_version: 2` (число) → consumers fail fast на несовместимой версии |

### 1.1. Иерархия таргетов веса (RPA-19, 2026-08-20)

Схема несла единственный таргет веса — цель Invest Era (IE) — как будто это цель владельца.
У владельца есть собственный план (`planned_share_pct` в снапшоте), и он — **primary**:

- **`weight_user_planned_pct` / `weight_divergence_vs_planned_pp` — PRIMARY.** База сравнения
  по умолчанию для рекомендаций, эскалаций, сортировки по расхождению. `null`, если у бумаги
  нет плана (см. edge cases §5) — это НЕ повод подставить IE вместо плана.
- **`weight_ie_target_pct` / `weight_divergence_vs_ie_pp` — secondary.** Эталон стороннего
  сервиса, годится как diagnostic-сигнал и как fallback при `weight_user_planned_pct == null`
  (с явной пометкой, что использован fallback), но никогда не заменяет primary молча.
- **`weight_divergence_pp` — DEPRECATED алиас `weight_divergence_vs_ie_pp`.** Только для чтения
  обзоров, сохранённых до 20.08.2026, и текущего вьюера. Новый код не читает и не пишет решения
  на этом поле — использовать `weight_divergence_vs_planned_pp` / `weight_divergence_vs_ie_pp`.

## 2. Полная schema

```yaml
# Frontmatter / metadata
schema_version: 2
type: weekly-stocks-review
review_date: "2026-05-04"            # ISO date
horizons: [6, 12, 24]                 # месяцы; ставит стаб
horizon_ends:                         # конец месяца review_date + N мес; ставит стаб
  h6: "2026-11-30"
  h12: "2027-05-31"
  h24: "2028-05-31"
primary_horizon: 12                   # advisor_verdict привязан к нему
horizon_mode: rolling                 # rolling | anchored (--anchor-dates)
snapshot_id: "PORTFOLIO-2026-05-03.json"
snapshot_date: "2026-05-03"
advisor_version: "ru-portfolio-advisor@2.x"
producer: "claude-opus-5"           # модель, сгенерировавшая review
trust_matrix_source: "Claude-Memory/INDEX.md"
trust_matrix_extracted_at: "2026-05-04T10:00:00"

# Per-stock data — основная часть
per_stock:

  # Пример 1: bank with full catalyst tree — полный набор (план есть, IE-цель есть)
  SBER:
    weight_real_pct: 12.46                    # из ie_actual.real_share_pct
    weight_user_planned_pct: 11.12            # PRIMARY target: план владельца,
                                               # из ie_actual.per_ticker[t].planned_share_pct
    weight_ie_target_pct: 6.0                 # secondary target: из ie_model.target_share_pct
    weight_divergence_vs_planned_pp: 1.34     # PRIMARY: weight_real_pct − weight_user_planned_pct
    weight_divergence_vs_ie_pp: 6.46          # secondary: weight_real_pct − weight_ie_target_pct
    weight_divergence_pp: 6.46          # DEPRECATED алиас weight_divergence_vs_ie_pp — только
                                         # для обратной совместимости (обзоры до 20.08.2026, вьюер)
    on_iis: false                       # R10: из holdings[i].account == "iis_3"
    sector: "Финансовый"                # из ie_model.sector

    fundamental_score: HIGH             # HIGH / MEDIUM / LOW / RED_FLAG (см. §3.5)
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
        date_window: "2026-Q4 to 2027-Q2"   # по нему потребитель решает, в каком горизонте катализатор
        p: 0.6
        upside_pct: 25
        upside_ci_pct: [15, 35]           # R1
        source: "advisor estimate based on 2014-2017 cycle"
        source_quality: HIGH              # R9: HIGH (regulatory data) / MEDIUM (analyst) / LOW (heuristic)
        source_trust:                     # R11 (2026-08-16): АТРИБУЦИЯ для матрицы доверия.
          analyst: "advisor"              #   Кто автор сигнала — как в INDEX.md («Invest Era»,
          subdomain: "self"               #   «БКС», «SberCIB»…); собственная оценка → analyst: advisor
                                          #   Поддомен — как в INDEX.md: oil-gas-ru / bonds-rub / …
                                          #   Опускать поле нельзя молча: без него потребитель
                                          #   (portfolio-integrated-view) фильтр IGNORE не применит,
                                          #   и это попадёт в validation.trust_coverage как «не
                                          #   атрибутировано». Подробности — trust-hierarchy.md §R11
        macro_dependency: "D"             # R4: scenario_id из source_matrix (SSOT scenarios YAML)
        macro_dependency_basis: |
          Catalyst срабатывает при сценарии D (семантика читается runtime из
          source_matrix). При других сценариях из той же матрицы catalyst not fires.
        auto_checkable: true              # R7/IV-B: числовой/датируемый порог → true;
                                          #   требует суждения → false (пропускается монитором)
        check_what: "Q4 2026 МСФО ROE ≥ 12%"  # наблюдаемый исход — используется как
                                          #   threshold в web_search forecast-monitor

      - id: sanctions_tail
        trigger: "Secondary sanctions on Sber correspondents"
        date_window: any                  # any → во всех горизонтах
        p: 0.15
        downside_pct: 40
        downside_ci_pct: [25, 60]
        source: "stress-test factor sanctions intensity (tail-risk scenario из source_matrix)"
        source_quality: HIGH
        macro_dependency: "B"             # tail-risk scenario_id из source_matrix
        auto_checkable: false             # tail-risk — нет числового порога, требует суждения

      - id: dividend_decision
        trigger: "ГОСА approval of дивидендов за 2025"
        date_window: "2026-06"
        p: 0.85
        upside_pct: 0                     # ужe заложено в div_yield_12m
        upside_ci_pct: [-2, 3]
        source: "https://e-disclosure.ru/... (ожидаемая дата ГОСА)"
        auto_checkable: true              # датируемый корп-event — монитор проверит
        check_what: "ГОСА состоялось, дивиденды утверждены"
        source_quality: HIGH
        macro_dependency: null            # независимое корп-событие

    ie_divergence_intentional: true       # R10: из ie_actual.user_plan / user_status / user_note_*
    ie_divergence_basis: "Пользователь намеренно держит обе SBER+SBERP выше IE-цели"

    advisor_verdict: HOLD                 # HOLD/BUY/TRIM/SELL
    advisor_verdict_confidence: 0.75
    advisor_verdict_basis: |
      Фундаментал HIGH, дивы прогнозируемы, но позиция уже выше IE-цели.
      Probability-weighted EV нейтральный (доминирует базовый сценарий),
      но в tail-сценарии большая просадка. Вердикт HOLD, не BUY.

    verification_priority: LOW            # C5: HIGH/MEDIUM/LOW
    verification_checklist: []            # пусто для LOW
    last_corp_event: "2026-04-28: МСФО Q1-26 +12% YoY чистая прибыль"   # только прошедшие (дата ≤ today)
    next_corp_event: null                 # ближайшее будущее событие — "2026-06-15 ГОСА"
    # carried_over: true                  # ОПЦИОНАЛЬНО (R-COV 2026-07-23): ставить ТОЛЬКО при
    #                                     #   осознанном переносе фундаментального блока из прошлого
    #                                     #   обзора без свежей проверки (новостей нет). Без флага
    #                                     #   валидатор save-to-library ставит warning, если нет ни
    #                                     #   одного источника с accessed_date в окне 7 дн до
    #                                     #   review_date. См. SKILL.md «R-COV — свежесть исследований»

  # Пример 2: stock with no calibrated catalysts (R2 in action) — случай «нет плана владельца»
  CHMF:
    weight_real_pct: 0.33
    weight_user_planned_pct: null           # плана по этой opportunistic-позиции нет
    weight_ie_target_pct: 0.5               # secondary target: в модели IE есть небольшая цель
    weight_divergence_vs_planned_pp: null   # нет слагаемого weight_user_planned_pct → null
    weight_divergence_vs_ie_pp: -0.17       # secondary: 0.33 − 0.5
    weight_divergence_pp: -0.17             # DEPRECATED алиас weight_divergence_vs_ie_pp
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

    ie_divergence_intentional: false
    advisor_verdict: TRIM
    advisor_verdict_confidence: 0.6
    advisor_verdict_basis: |
      Маленькая позиция (0.33%), стальной цикл pressured.
      Капитал лучше переложить в позиции с явными catalysts.
      Выходить по рынку без ценового условия — тезис сломан, ждать нечего. (R11: форма 4)

    verification_priority: MEDIUM         # disagreement zone
    verification_checklist:
      - "Проверить дивполитику CHMF на сайте IR"
      - "Сверить с peer'ами (NLMK, MAGN) — они тоже без дивов?"
    last_corp_event: "2026-03-15: Q1-26 РСБУ"
    next_corp_event: null

  # Пример 3: ИИС-3 position (R10 in action) — случай «нет в модели IE»
  RU000A107RH8:
    weight_real_pct: 0.42                     # часть на main
    weight_user_planned_pct: 0.5              # PRIMARY target: план владельца покрывает
                                               # и облигационную часть портфеля
    weight_ie_target_pct: null                # secondary: IE — equity-only модель,
                                               # облигации не покрывает → null
    weight_divergence_vs_planned_pp: -0.08    # PRIMARY: 0.42 − 0.5
    weight_divergence_vs_ie_pp: null          # нет слагаемого weight_ie_target_pct → null
    weight_divergence_pp: null                # DEPRECATED алиас weight_divergence_vs_ie_pp
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

    # Bond-enrichment поля (MOEX ISS). ytm_pct — carry-базис YTM-К-ПОГАШЕНИЮ.
    ytm_pct: 13.4
    ytm_to_offer_pct: null      # yield-to-offer; заполнять для бумаг с офертой
    coupon_pct: 13.4
    offer_date: null            # put/оферта; задаёт реальный срок короче maturity
    maturity_date: "2030-05-04"
    # ⚠ Не класть yield-to-offer в ytm_pct. MOEX YIELD для бумаги с близкой офертой =
    # доходность-к-оферте (на коротком горизонте раздувается до сотен % годовых).
    # → yield-to-offer пиши в ytm_to_offer_pct; ytm_pct оставляй YTM-к-погашению/null.
    # Экономику оферты держи в catalyst (offer_exit), не в carry. См. bonds-methodology.md.

    # S3: стандартное погашение НЕ выносится в catalyst — дата уже есть в maturity_date.
    # catalyst с id: redemption пишется ТОЛЬКО если есть реальный риск не-погашения.
    catalyst:                                # для bond — только нестандартные события
      - id: credit_event
        trigger: "Дефолт / реструктуризация"
        date_window: any
        p: 0.03
        downside_pct: 60
        downside_ci_pct: [40, 90]
        source: "Эксперт РА migration matrix для рейтинга A+"
        source_quality: MEDIUM
        macro_dependency: "B"   # tail-risk scenario_id из source_matrix

    advisor_verdict: HOLD
    advisor_verdict_confidence: 0.9
    advisor_verdict_basis: "ИИС-3 hold to maturity, нельзя продавать без потери льготы"
    advisor_verdict_constraints:
      - "iis_3_hold_lock: позиция на ИИС-3, продажа разрушит налоговую льготу"

    verification_priority: LOW
    verification_checklist: []
    last_corp_event: "2026-04-15: купонная выплата 33.45 руб."   # только прошедшие события
    next_corp_event: "2027-04-20: погашение"                      # ближайшее будущее

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

  # S4: для bond-review — ПЛОСКИЙ формат (не вложенный main_only/main_plus_iis).
  # Главное поле = full portfolio (main + IIS). Дополнительные — суффикс _main_only.
  weighted_ytm_pct:
    value: 11.96
    ci_pct: [11.55, 12.45]                 # main+IIS (полный портфель облигаций)
  weighted_ytm_pct_main_only:
    value: 11.81
    ci_pct: [11.40, 12.30]                 # опционально
  weighted_duration_days: 776              # main+IIS — просто число, не объект
  weighted_duration_days_main_only: 692    # опционально

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
  - check: "every catalyst has date_window"
    passed: true
  - check: "div_yield CI present for every position"
    passed: true
  - check: "iis_3 positions have advisor_verdict_constraints"
    passed: true
  - check: "fundamental_score_sources present for HIGH scores"
    passed: true
  - check: "equity BUY/TRIM/SELL verdict has actionable basis (R11)"
    passed: true
```

## 3. Hard rules для producer (advisor)

### 3.1. fundamental_score: RED_FLAG

`RED_FLAG` — отдельное значение enum, не синоним LOW. Использовать когда:
- Иск Генпрокуратуры / судебный запрет / угроза национализации
- Реальный риск дефолта / не-погашения (credit_quality по сути D или CC)
- Любое событие, которое делает инвестицию «потенциально обнулённой»

```yaml
fundamental_score: RED_FLAG
fundamental_score_basis: "RED FLAG: иск Генпрокуратуры о взыскании активов (решение ожидается Q3-26)"
```

Нельзя использовать `fundamental_score: LOW` + текст "RED FLAG:" в basis — viewer определяет RED_FLAG только по enum.

### 3.2. last_corp_event / next_corp_event

- `last_corp_event` — **только прошедшее** событие (дата ≤ today). Формат: `"YYYY-MM-DD: описание"`.
- `next_corp_event` — **ближайшее будущее** событие (дата > today). Формат: `"YYYY-MM-DD: описание"`. Если нет — `null`.

```yaml
last_corp_event: "2026-04-28: МСФО Q1-26 +12% YoY"
next_corp_event: "2026-06-15: ГОСА, решение по дивидендам"
```

Нельзя писать будущую дату в `last_corp_event`. Это нарушает семантику и ломает viewer.

### 3.3. Catalyst redemption rule (S3)

Стандартное погашение **не выносить в catalyst**. Дата уже есть в `maturity_date`. Viewer отображает `maturity_date` в параметрах — дублирование в catalyst tree создаёт шум.

`id: redemption` допустим ТОЛЬКО при реальном риске не-погашения:
```yaml
# Правильно — только если дефолт-риск есть:
- id: redemption
  trigger: "Погашение 16.12.2027 при отсутствии дефолта"
  p: 0.72   # сниженная вероятность из-за кредитного риска
- id: credit_event
  trigger: "Дефолт / реструктуризация"
  p: 0.28

# Неправильно — стандартная облигация с HIGH credit:
- id: redemption   # ← убрать, maturity_date уже покрывает
  p: 0.97
```

### 3.4. Catalyst ID naming convention (S6)

Формат: `{event_type}_{fiscal_year_or_qualifier}`.

- `dividend_record_date_2025` — дивиденды **за** 2025 год, выплачиваемые в 2026. Это корректно.
- `rate_cut_h2_2026` — снижение ставки во второй половине 2026.
- Год в ID = **фискальный/отчётный период**, не дата события.

После прохождения `date_window` — `forecast-monitor` ставит `resolved: true`. Не менять ID задним числом.

### 3.5. Catalyst writing rules (R2, R9)

```python
# Псевдокод правила
def should_write_catalyst(c):
    if not c.source:
        return False                    # R2: no source → drop
    if not c.date_window:
        return False                    # R3: без date_window горизонт не определить → drop

    if c.source_quality == "LOW":
        c.p = c.p * 0.5                 # R9: discount unreliable

    return True
```

### 3.2. Div yield rules (R1)

- Если есть fixed дивполитика → narrow CI (3-5 pp range)
- Если payout discretionary → wide CI (отражает uncertainty)
- Если no history → CI [0, max_industry_yield]
- **Никогда не писать point estimate без CI**

### 3.3. Verification priority assignment (C5 — расширенное, DERIVED)

`verification_priority` ставит скрипт, не модель: `assemble_artifact.py stamp-report` save-to-library после записи
обзора считает его `constraint_engine.compute_verification_priority` и перезаписывает поле (в стабе — `null`; из
прошлого обзора не переносится; валидатор с `--root` блокирует расхождение). HIGH = действие СЕЙЧАС
(actionable-вердикт) или нужен разбор (гейт модуля (б) `review_needed` / `new_position` / `review_aging` — флаг
обзора, новая бумага, срок решения вышел). «Наблюдать» (`reviewed_under_review`) — не «нужен разбор»: бумага ждёт
условия → MEDIUM через действующее условие с вердиктом-сделкой. Отложенное действие (actionable-soon: намерение под
constraint'ом / активное условие) → MEDIUM, не HIGH. Приоритет — подпись строки; размещение на «Действиях» и push
решают направление вердикта, сработавшее условие и пункты `verification_checklist`, а не «срочно».

```python
ACTIONABLE = {"BUY", "TRIM", "SELL", "ADD"}
def assign_verification_priority(stock, active_condition_verdicts, gate_status):
    if stock.advisor_verdict in ACTIONABLE:            return "HIGH"   # actionable сейчас
    if gate_status in ("review_needed", "new_position", "review_aging"): return "HIGH"  # нужен разбор
    if stock.unconstrained_verdict in ACTIONABLE:      return "MEDIUM" # actionable-soon (под constraint'ом)
    if any(v in ACTIONABLE for v in active_condition_verdicts): return "MEDIUM"  # условие → действие позже
    if stock.advisor_verdict_confidence < 0.6:         return "MEDIUM"
    if any(c.macro_dependency and stress.scenarios[c.macro_dependency].p < 0.2
           for c in stock.catalysts):                  return "MEDIUM" # critical event hidden in low-prob scenario
    return "LOW"
```

### 3.5. advisor_verdict_basis requirements для акций (R11)

Для акционных позиций (`sector != "Облигации"`) при `advisor_verdict: BUY | TRIM | SELL` поле `advisor_verdict_basis` ОБЯЗАНО содержать хотя бы одну из четырёх форм:

1. **Ценовой ориентир** входа или выхода — «входить ниже 360 ₽», «фиксировать выше 950 ₽»
2. **Yield-порог** — «при дивдоходности ≥10.2%», «при YTM ≥ 14% после снижения купона» (в том числе привязанный к событию)
3. **Событие-триггер с измеримым условием** — «после Q1 МСФО, если ЧП >X млрд»
4. **Явная price-agnostic установка с обоснованием** — «выходить по рынку без условий — тезис сломан» или «набираю плацдарм по рынку, размер позиции не критичен к цене входа»

`HOLD` не требует ни одного из этих элементов.

Правило не применяется к `sector == "Облигации"` (используют YTM-порог, который семантически покрыт формой 2), фондам и ИИС-3 облигационным позициям.

Нарушение → `quality_checks` fail (строка `"equity BUY/TRIM/SELL verdict has actionable basis (R11)"`).

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

`schema_version` ≠ 2 → `aggregate_positions.py` возвращает ошибку `schema_v1_not_supported` с адресом мигратора;
валидаторы save-to-library такой файл блокируют. Катализатор входит в горизонт `hN`, если `date_window`
начинается не позже `horizon_ends.hN` (`any` — во всех).

### 4.2. Joint expectation calculation (R4)

```python
def compute_joint_expected_pct(stock, stress_yaml):
    base_macro = stress_yaml.per_position[stock.ticker].expected_pct_pweighted
    div_contribution = stock.div_yield_12m_pct.value * (h / 12.0)  # h — горизонт в месяцах

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
        div = sample_from_ci(stock.div_yield_12m_pct.ci_pct) * (h / 12.0)
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
| Stock в portfolio, нет в IE model | `weight_ie_target_pct: null`, `weight_divergence_vs_ie_pp: null`, `weight_divergence_pp: null` (deprecated-алиас = vs_ie). Расхождение с планом владельца (`weight_divergence_vs_planned_pp`) при этом считается как обычно, если план есть — отсутствие бумаги в IE НЕ обнуляет primary-расхождение |
| Stock в portfolio, нет плана владельца | `weight_user_planned_pct: null`, `weight_divergence_vs_planned_pp: null`. Расхождение с IE (`weight_divergence_vs_ie_pp`) считается как обычно, если бумага есть в модели IE — это secondary-сигнал, отсутствие плана его не блокирует |
| Stock в IE model, нет в portfolio | НЕ пишется в `per_stock`. Идёт в integrated-view как «IE candidate not held» через `ie_summary.list_in_ie_not_in_portfolio` |
| Bond с YTM | `div_yield_12m_pct` = YTM (не дивы). `catalyst` — только нестандартные события (не redemption при HIGH credit) |
| Blocked position (`is_blocked: true` в snapshot) | `fundamental_score: RED_FLAG`, `advisor_verdict: HOLD`, basis начинается с "RED FLAG: blocked, illiquid" |
| Position без MOEX-цены (cost_basis only) | `fundamental_score: LOW`, all CIs widened (приоритет проверки ставит штамп) |
| Catalyst date_window позже конца горизонта | в этом горизонте не учитывается (потребитель, по `horizon_ends`) |
| Catalyst без macro_dependency | OK, считается как полностью idiosyncratic с discount factor 0.7 в синтезаторе |
| Все catalysts отброшены | `catalyst: []`, `advisor_note: "macro_ΔP&L only..."`, position survives с macro-only оценкой |

## 6. Acceptance criteria

YAML считается valid если:

- [ ] `schema_version == 2`, `horizons` / `horizon_ends` / `primary_horizon` — как в стабе
- [ ] `snapshot_id` существует и доступен
- [ ] `per_stock` содержит все active positions из snapshot
- [ ] Каждый catalyst имеет non-null `source` field
- [ ] Каждый catalyst имеет `date_window`
- [ ] Каждое числовое предсказание имеет CI
- [ ] Все ИИС-3 позиции имеют `on_iis: true` и `advisor_verdict_constraints` non-empty
- [ ] `summary.positions_reviewed` совпадает с `len(per_stock)`
- [ ] `caveats` содержит минимум 1 запись severity HIGH (про catalyst calibration)
- [ ] `quality_checks` все `passed: true`
- [ ] Каждый equity BUY/TRIM/SELL вердикт содержит хотя бы одну из четырёх форм basis (R11)
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
   3.5 Filter catalysts: drop if no source or no date_window
   3.6 For each surviving catalyst: assign macro_dependency if applicable
   3.7 Apply ИИС-3 verdict constraints
   3.8 verification_priority — не заполнять (null): ставит stamp-report при сохранении
4. Compute summary stats
5. Generate caveats (always include calibration warnings)
6. Run quality_checks
7. Output YAML to chat (default) or save to library (if flag)
```
