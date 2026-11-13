# Existing Skills — Change List

**Дата:** 2026-05-05
**Контекст:** Phases 1, 2, 3, 5 из MASTER-PLAN
**Цель:** delta-документ для существующих скиллов: что добавить, что изменить, что не трогать.

---

## 1. portfolio-data-loader

### 1.1. Скрипт `scripts/parse_portfolio.py` — расширение до v2

**Зависимость:** `01-JSON-SCHEMA-V2-PROPOSAL.md`

**Изменения:**

#### A. Поднять SCHEMA_VERSION

```python
# Было
SCHEMA_VERSION = "1.0"

# Стало
SCHEMA_VERSION = "2.0"
```

#### B. Добавить parsing функции

Новые функции:
- `parse_ie_model(numbers_doc)` → читает вкладку «Invest Era» → блок `ie_model`
- `parse_ie_actual(numbers_doc)` → читает колонки `IE New / IE Old / Доля Реальная / Действие / IE / T / AI` из вкладки «Акции»
- `compute_ie_summary(ie_model, ie_actual)` → derived stats
- `parse_iis_assignment(numbers_doc, holdings)` → определяет account=iis_3 для каждого holding

#### C. Изменить main flow

```python
def parse_portfolio(balance_path, trades_path):
    numbers_doc = read_numbers(balance_path)

    holdings = parse_holdings(numbers_doc)
    iis_assignment = parse_iis_assignment(numbers_doc, holdings)

    # Apply iis_3 account
    for h in holdings:
        h["account"] = iis_assignment.get(h["ticker"], "main")

    # Split positions if iis is partial
    holdings = split_positions_by_account(holdings, iis_assignment)

    # New blocks
    ie_model = parse_ie_model(numbers_doc)
    ie_actual = parse_ie_actual(numbers_doc)
    ie_summary = compute_ie_summary(ie_model, ie_actual, holdings)

    # Recalculate balance excl iis
    balance_summary = compute_balance_summary_v2(holdings)

    return {
        "schema_version": SCHEMA_VERSION,
        "as_of_date": ...,
        "holdings": holdings,
        "ie_model": ie_model,           # NEW
        "ie_actual": ie_actual,         # NEW
        "ie_summary": ie_summary,       # NEW
        "balance_summary": balance_summary,  # MODIFIED (by_account block added)
        # existing blocks unchanged
        "cash": ...,
        "returns": ...,
        "per_instrument_xirr": ...,
        "corrections_log": ...,
        "data_quality_flags": ...,
    }
```

#### D. Decimal parsing для русских чисел

```python
def parse_decimal_ru(s):
    """Парсит '5,59' → 5.59. '-' → None. None → None. Float → return as-is."""
    if s is None: return None
    if isinstance(s, (int, float)): return float(s)
    s = str(s).strip()
    if s in ("-", "", "—"): return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None
```

#### E. Add data quality flags

```python
# Новые типы flags (добавить в существующий список)
def check_ie_consistency(ie_model, ie_actual):
    flags = []
    total = sum(p.target_share_pct for p in ie_model.positions)
    if abs(total - 100.0) > 1.0:
        flags.append({
            "step": "ie_model_parse",
            "severity": "warn",
            "code": "ie_model_total_mismatch",
            "message": f"Сумма target_share_pct = {total:.1f}%, ожидается 100.0%"
        })
    return flags
```

### 1.2. SKILL.md — обновление документации

**Изменения в `portfolio-data-loader/SKILL.md`:**

#### A. Update output schema section

Добавить документацию по новым полям:
- `ie_model`
- `ie_actual`
- `ie_summary`
- `holdings[i].account` extension
- `balance_summary.by_account`

#### B. Add «Что НЕ парсится» section

```markdown
## Что НЕ парсится из .numbers (intentional)

- Вкладка «Импорт Акции» — raw IntelInvest snapshot, дублирует `holdings`
- Вкладка «Планы» — плановые пополнения, заблокировано правилом №4 advisor'а
- Вкладка «Импорт облигации» — raw, дублирует `holdings` для bonds
- Колонки «Точка Входа» / «Стоимость» из вкладки «Акции» — дублируется с MOEX-данными в `holdings.current_price` и `value_rub`
- Колонки в Numbers, начинающиеся с `Расчёт_` или `Авто_` — внутренние формулы Numbers
```

#### C. Add schema versioning section

```markdown
## Schema versioning

Текущая версия — `2.0` (см. `01-JSON-SCHEMA-V2-PROPOSAL.md`).

Изменения относительно v1.0:
- Добавлены: `ie_model`, `ie_actual`, `ie_summary` blocks
- Расширено: `holdings[i].account` поддерживает `"iis_3"`
- Расширено: `balance_summary.by_account` block
- Исправлен баг: `total_current_rub_excl_iis` теперь корректно отделяет ИИС-3

Backward compatibility: v1.x consumers продолжают работать (новые поля игнорируют). v2.x consumers требуют `schema_version >= "2.0"`.
```

### 1.3. Acceptance criteria

См. `08-acceptance-criteria.md` Phase 1.

---

## 2. ru-portfolio-advisor

### 2.1. SKILL.md — input contract change

**Текущее правило 0:** «нужны `Общий баланс.numbers` + `trades_portfolio_*.xlsx`»

**Новое правило 0 (черновик):**

```markdown
0. **БЕЗ ВХОДНЫХ ДАННЫХ — НЕ ОТВЕЧАЙ ПО СУЩЕСТВУ.** 

Этот скилл анализирует частный портфель. Допустимые входы:
- (Primary) `PORTFOLIO-{date}.json` v2.x age ≤ 14 дней — предпочтительный путь
- (Fallback) `Общий баланс.numbers` + `trades_portfolio_*.xlsx` — скилл сам запускает 
  `portfolio-data-loader` для генерации snapshot перед анализом

Если ничего не приложено — first response: попроси либо JSON, либо raw файлы. Без файлов работа НЕ продолжается.

Запрещено:
- «общий обзор рынка» вместо анализа портфеля
- «топ-N дивидендных акций» вместо разбора пользовательских позиций
- любая подмена жанром аналитической публикации (см. правило №АП — anti-pattern)
```

**Изменения в логике загрузки:**

```python
def load_input(message_attachments):
    # Try primary first
    json_files = [f for f in message_attachments if f.endswith('.json') and 'PORTFOLIO' in f]
    if json_files:
        snapshot = json.load(open(json_files[0]))
        if snapshot["schema_version"] < "2.0":
            raise SchemaIncompatible("PORTFOLIO snapshot v1.x не поддерживается. Перегенерируй через v2 loader.")
        # Check freshness
        as_of = parse_date(snapshot["as_of_date"])
        if (date.today() - as_of).days > 14:
            warn("Snapshot age > 14 days. Consider regenerating.")
        return snapshot

    # Fallback to raw
    numbers = [f for f in message_attachments if f.endswith('.numbers')]
    trades = [f for f in message_attachments if 'trades_portfolio' in f]
    if numbers and trades:
        # Run loader inline
        return run_loader(numbers[0], trades[0])

    raise NoInputs("Нужен либо PORTFOLIO-{date}.json (v2, age ≤14d), либо Общий баланс.numbers + trades.xlsx")
```

### 2.2. SKILL.md — Output mode `--save-to-library`

**Новый раздел в SKILL.md:**

```markdown
## Output Modes

### Default mode (chat output only)

Weekly Review / Single Stock Analysis выдаются как conversational response в чат.
Никакие файлы не генерируются.

### `--save-to-library` mode

Активируется через:
- Явный флаг в команде: `/ru-portfolio-advisor --save-to-library`
- Триггерные фразы: «подготовь репорт для сохранения», «save weekly», «сохрани обзор»

В этом режиме advisor дополнительно генерирует структурированный YAML 
**в чат как code block** для визуальной проверки пользователем.

Формат YAML — см. `02-weekly-review-schema-v1.md`.

Пользователь визуально проверяет YAML, потом отдельной командой запускает 
`save-to-library` для записи в библиотеку:

```
/save-to-library type=weekly-review
```

**Никогда не сохраняй в библиотеку автоматически без user trigger.**
```

### 2.3. references/catalyst-tree-rules.md — НОВЫЙ файл

```markdown
# Catalyst Tree Generation Rules

При генерации weekly-review YAML, для каждого ticker создавай catalyst tree 
по следующим правилам.

## Hard rules (R2 mitigation)

1. **Source required.** Если для catalyst нет explicit source (URL, document, analyst name + report ID) — НЕ пиши catalyst в YAML. Пиши `catalyst: []` для этой позиции.

2. **In-horizon required (R3).** Если `date_window` для catalyst > 20 месяцев — НЕ пиши catalyst.

3. **Source quality flag (R9):**
   - HIGH — primary source (e-disclosure, ГОСА протокол, рейтинговое агентство, IR releases)
   - MEDIUM — sell-side analyst (Invest Era, БКС, etc) с проверяемым именем + датой report
   - LOW — Smart-lab, Пульс, общая аналитика без attribution

4. **Macro dependency assignment (R4):**
   - Если catalyst — про rate cycle → `macro_dependency: "Sc-D_base"` (или соответствующий)
   - Если catalyst — про sanctions tail → `macro_dependency: "Sc-B_stress"`
   - Если catalyst — про reflation → `macro_dependency: "Sc-A_bull"` или null
   - Если catalyst — про escalation/inflation → `macro_dependency: "Sc-C_war"`
   - Если catalyst — про корп-событие (дивы, M&A, продукт) → `macro_dependency: null`

## Catalyst types per sector

### Banks (SBER, T, MBNK, RENI, DOMRF, etc.)

Типичные catalysts:
- `rate_cut_re_rating` — depends on Sc-D_base
- `sanctions_tail` — depends on Sc-B_stress  
- `dividend_decision` — independent
- `cet1_buffer_change` — regulatory, independent
- `cor_change` — credit cycle, partial macro dependency

### Oil & Gas (NVTK, etc.)

Типичные catalysts:
- `oil_price_shift` — embedded в macro stress, обычно НЕ separate catalyst
- `discount_to_brent_change` — независимый или Sc-D
- `tax_regime_change` — независимый политический
- `dividend_capacity_change` — следствие cash flow

### Tech / IT (YDEX, OZON, DATA, BTBR)

- `growth_acceleration` — в основном idiosyncratic
- `regulatory_relief` — независимое политическое
- `monetization_milestone` — independent operational
- `capital_intensity_change` — partial macro (rate-driven)

### Pharma (MDMG, PRMD)

- `regulation_approval` — independent
- `clinic_opening` (для MDMG) — independent
- `drug_launch` — independent
- `government_program_inclusion` — political, independent

### Retail (X5, LENT)

- `dividend_resumption_X5` — independent corp event
- `lfl_acceleration` — partial macro (consumer demand)
- `format_innovation_payoff` — independent operational

### Utilities (UPRO, LSNGP)

- `tariff_review` — regulatory
- `rab_program_change` — regulatory
- `dividend_policy_change` — independent

## Probability assignment

Использовать historical base rates где возможно:
- Дивидендное решение от стабильного payer (SBER) — P=0.85+
- M&A в текущем regulatory environment — P=0.05-0.15
- Sanctions tail event — P=0.10-0.20
- Catalyst > 6 мес — P automatically discount 0.7x
- Catalyst > 12 мес — P discount 0.5x

## Confidence interval rules

Для upside/downside:
- Если есть analog: CI = ±50% от mean (e.g., upside 25% → CI [12, 38])
- Если нет analog (новая компания / событие): CI = ±100% от mean (e.g., upside 25% → CI [0, 50])
- Source quality LOW → CI extra-wide (×1.5)

## Anti-patterns

❌ Catalyst без даты или с фразой «когда-то»
❌ Catalyst без источника, основанный на «общем мнении»
❌ Catalyst с P > 0.95 (всегда есть uncertainty)
❌ Catalyst со ссылкой на Telegram-канал без archive
❌ Дублирование одного события несколькими catalysts
❌ macro_dependency на несуществующий scenario id
```

### 2.4. references/stocks-methodology.md — обновление

Добавить раздел «Generating weekly-review YAML» с reference на 02-weekly-review-schema-v1.md и catalyst-tree-rules.md.

### 2.5. Acceptance criteria

См. 08-acceptance-criteria.md Phase 2.

---

## 3. portfolio-scenario-stress

### 3.1. SKILL.md — output schema extension

**Зависимость:** `03-stress-schema-additions.md`

**Изменения в SKILL.md:**

#### A. Добавить раздел «Output schema v1»

С отсылкой на `03-stress-schema-additions.md` и явным списком новых полей:
- `schema_version: 1`
- `scenarios.{id}` keys как stable IDs
- `per_position` block (per-ticker breakdown)
- `macro_blindspots` list

#### B. Добавить per-position computation logic

```markdown
## Per-position breakdown computation

Для каждого active holding (не blocked, не cash):

1. Estimate factor_betas через regression на 24mo monthly returns:
   - Predictors: ΔKEY_RATE, ΔUSDRUB, ΔBrent, sanctions_index_proxy
   - Response: monthly stock return
   - Method: OLS, без time-varying для v1

2. Per-scenario delta = Σ(beta_i × scenario.factors[i])

3. Confidence intervals via bootstrap (500 samples) из beta covariance matrix

4. Mark as macro_blindspot если:
   - R² < 0.3, OR
   - Все |beta_i| < 0.1, OR
   - Ticker в hard-coded list (MDMG, PRMD, OZON, DOMRF, WUSH, X5)
```

#### C. Stable scenario IDs

Зафиксировать в SKILL.md что **никогда не переименовывать** scenario IDs без bump schema_version. Это контракт с downstream consumers.

```markdown
## Scenario ID stability (CRITICAL)

Scenario IDs (`Sc-A_bull`, `Sc-D_base`, `Sc-B_stress`, `Sc-C_war`) — стабильный
public API. Их изменение → breaking change → bump schema_version.

Внутренние detail (например, изменение probabilities или factor values) — 
non-breaking, не требуют schema bump.
```

### 3.2. Скрипты

Если у `portfolio-scenario-stress` есть Python scripts (вероятно, есть для factor regression):

```python
# Add per_position computation to existing stress run
def compute_per_position_breakdown(snapshot, scenarios, factor_history):
    result = {}
    for h in snapshot.holdings:
        if h.is_blocked or h.value_rub == 0: continue
        # ... computation per spec
    return result

def is_macro_blindspot(ticker, betas, r2):
    HARDCODED = ["MDMG", "PRMD", "OZON", "DOMRF", "WUSH", "X5", "GLRX"]
    if r2 < 0.3: return True, "low_r2"
    if all(abs(b) < 0.1 for b in betas.values()): return True, "low_sensitivity"
    if ticker in HARDCODED: return True, "hardcoded_idiosyncratic"
    return False, None
```

### 3.3. Acceptance criteria

См. 08-acceptance-criteria.md Phase 3.

---

## 4. save-to-library

### 4.1. SKILL.md — добавить два новых типа артефактов

**Изменения:**

#### A. Add type `weekly-review`

```markdown
## Type: weekly-review

Сохраняет weekly review YAML от ru-portfolio-advisor.

Validation:
- `schema_version == 1`
- `type == "weekly-stocks-review"`
- Required fields present (см. 02-weekly-review-schema-v1.md acceptance criteria)
- All catalyst entries have source field
- All numeric predictions have CI

Filename pattern: `Weekly-Reviews/REVIEW-{review_date}.yaml`

Storage: Synology-first, gdrive fallback.

Update INDEX.md: append entry to «Weekly Reviews» section.
```

#### B. Add type `integrated-view`

```markdown
## Type: integrated-view

Сохраняет integrated view markdown от portfolio-integrated-view.

Validation:
- Header содержит `Schema: integrated-view@1.x`
- Содержит все 11 sections (ИЛИ explicit «section X skipped: reason»)
- Source files paths указаны в конце
- predictions_for_review block content valid

Filename pattern: `Integrated-Views/INTEGRATED-VIEW-{date}.md`

Storage: Synology-first, gdrive fallback.

Update INDEX.md: append entry to «Integrated Views» section.
```

### 4.2. Validation logic в скрипте

```python
def validate_weekly_review(yaml_data):
    errors = []
    if yaml_data.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if yaml_data.get("type") != "weekly-stocks-review":
        errors.append("type must be weekly-stocks-review")
    
    for ticker, stock in yaml_data.get("per_stock", {}).items():
        for c in stock.get("catalyst", []):
            if not c.get("source"):
                errors.append(f"{ticker}/{c.get('id')}: missing source field")
            if "in_horizon" not in c:
                errors.append(f"{ticker}/{c.get('id')}: missing in_horizon flag")
        if "div_yield_12m_pct" in stock:
            if "ci_pct" not in stock["div_yield_12m_pct"]:
                errors.append(f"{ticker}: div_yield missing CI")
    
    return errors


def validate_integrated_view(md_text):
    errors = []
    if "Schema: integrated-view@1." not in md_text:
        errors.append("schema declaration missing or wrong version")
    
    required_sections = [
        "## ⚠️ Stale checks",
        "## 🎯 Section 1:",
        "## 📊 Section 2:",
        "## 💰 Section 3:",
        "## 📌 Section 9:",
        "## 🔮 Section 10:",
        "## ⚠️ Section 11:",
    ]
    for sec in required_sections:
        if sec not in md_text and f"<!-- skipped: " not in md_text:
            errors.append(f"missing section: {sec}")
    
    return errors
```

### 4.3. Acceptance criteria

См. 08-acceptance-criteria.md Phase 5.

---

## 5. forecast-monitor

### 5.1. SKILL.md — расширить scope

**Текущее назначение:** мониторинг forecast YAMLs из `forecasts/`.

**Расширение:** добавить мониторинг portfolio artifacts staleness.

#### A. Новый раздел «Portfolio artifacts staleness»

```markdown
## Portfolio artifacts staleness check

При запуске мониторинга, дополнительно проверь:

1. **Latest PORTFOLIO snapshot** — `Portfolio-Snapshots/PORTFOLIO-{latest}.json`
   - Threshold: 14 days
   - Если старше → alert «Snapshot устарел, перегенерируй через portfolio-data-loader»

2. **Latest STRESS YAML** — `Portfolio-Stress/STRESS-{latest}.yaml`
   - Threshold: 90 days
   - Если старше → alert «Stress test устарел, запусти macro-forecast-chain + portfolio-scenario-stress»

3. **Latest WEEKLY-REVIEW YAML** — `Weekly-Reviews/REVIEW-{latest}.yaml`
   - Threshold: 14 days
   - Если старше → alert «Weekly review устарел, запусти ru-portfolio-advisor с --save-to-library»

4. **Latest INTEGRATED-VIEW** — `Integrated-Views/INTEGRATED-VIEW-{latest}.md`
   - Threshold: 7 days
   - Если старше → alert «Integrated view устарел, запусти portfolio-integrated-view»

Все алерты идут в weekly digest вместе с forecast monitoring.
```

### 5.2. Acceptance criteria

См. 08-acceptance-criteria.md Phase 5.

---

## 6. Отдельный change для INDEX.md в Claude-Memory

### 6.1. Новые subsections

Добавить в INDEX.md разделы:

```markdown
## Portfolio Snapshots
- [Snapshot history table]

## Portfolio Stress Tests
- [Stress runs table]

## Weekly Reviews
- [Review history table]

## Integrated Views
- [IV history table]

## Self-validation roadmap

Через 6 мес после запуска integrated-view (target date: {today + 6mo}):
1. Запустить retrospective-forecast-audit на накопленных predictions_for_review
2. Калибровать catalyst.p discount factors
3. Опубликовать calibration report в Claude-Memory/calibration/
4. Bump portfolio-integrated-view → v1.1 (или v2.0 если breaking)
```

---

## 7. Cross-cutting concerns

### 7.1. Storage paths — единая иерархия

В Claude-Memory:

```
Claude-Memory/
├── INDEX.md
├── Portfolio-Snapshots/
│   └── PORTFOLIO-2026-05-03.json   (v2)
├── Portfolio-Stress/
│   └── STRESS-2026-05-04.yaml      (v1)
├── Weekly-Reviews/                  (NEW)
│   └── REVIEW-2026-05-04.yaml      (v1)
├── Integrated-Views/                (NEW)
│   └── INTEGRATED-VIEW-2026-05-04.md (v1)
├── Tools/                           (NEW)
│   └── portfolio-integrated-viewer.html
├── ru-sellside/
├── geopolitics/
├── forecasts/
├── Scenarios/
├── reports/
└── calibration/                     (NEW for v2)
```

### 7.2. Naming conventions

- Snapshots: `PORTFOLIO-YYYY-MM-DD.json`
- Stress: `STRESS-YYYY-MM-DD.yaml`
- Reviews: `REVIEW-YYYY-MM-DD.yaml`
- Integrated views: `INTEGRATED-VIEW-YYYY-MM-DD.md`

Если за один день несколько runs (rare): suffix `-001`, `-002`.

### 7.3. Schema version compatibility matrix

| Producer | Schema | Consumed by | Required version |
|---|---|---|---|
| portfolio-data-loader | v2.0 | advisor, stress, synthesizer | ≥ 2.0 |
| ru-portfolio-advisor | weekly-review v1 | synthesizer | ≥ 1 |
| portfolio-scenario-stress | stress v1 | synthesizer | ≥ 1 |
| portfolio-integrated-view | integrated-view v1 | HTML viewer, save-to-library | ≥ 1 |

Любой mismatch → fail fast в consumer.

### 7.4. Documentation updates

После реализации каждой Phase, обновлять CHANGELOG.md в каждом затронутом скилле.

---

## 8. Что explicitly не меняется

Не трогать:
- `portfolio-data-loader/scripts/portfolio_returns.py` (XIRR computation — backward compat)
- `portfolio-data-loader/scripts/moex_quotes.py` (price fetching — без изменений)
- `ru-portfolio-advisor/scripts/per_security_xirr.py` (existing)
- Существующие references в advisor (только additions)
- macro-forecast-chain (не в scope этих изменений)
- forecast-confidence-applier (не в scope)
- scenario-builder, hypothesis-stress-tester (не в scope)
- retrospective-forecast-audit (но будет использован в v2 для calibration)

Если изменения требуются за пределами этого списка — они должны быть отдельной change-request с обоснованием.
