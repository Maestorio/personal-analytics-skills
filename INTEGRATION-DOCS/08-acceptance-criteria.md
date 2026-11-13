# Acceptance Criteria — End-to-End

**Дата:** 2026-05-05
**Версия:** 1.0
**Назначение:** testlist для проверки готовности всей системы. Каждая Phase из MASTER-PLAN имеет свой блок criteria. Phase считается завершённым только при прохождении всех criteria.

---

## Phase 1: Data Layer (parse_portfolio.py → JSON v2)

### 1.1. Schema correctness

- [ ] Сгенерированный JSON содержит `"schema_version": "2.0"` в frontmatter
- [ ] Сгенерированный JSON парсится через `json.loads()` без ошибок
- [ ] Валидация против JSON Schema (если будет написана) проходит без ошибок

### 1.2. New fields presence

- [ ] `ie_model.positions` содержит ровно 21 запись (все позиции из вкладки «Invest Era»)
- [ ] Каждая запись `ie_model.positions[i]` имеет поля: ticker, name, sector, target_share_pct, active_in_model
- [ ] `ie_model.model_total_pct` равен ~100.0 (±1.0)
- [ ] `ie_actual.per_ticker` содержит записи для всех тикеров с непустыми `IE New` или `IE Old`
- [ ] `ie_actual.per_ticker[ticker].ie_delta_pct` корректно вычислен
- [ ] `ie_summary.tickers_in_ie_model` соответствует длине `ie_model.positions`
- [ ] `ie_summary.list_in_portfolio_not_in_ie` non-empty (есть позиции вне IE)
- [ ] `ie_summary.list_in_ie_not_in_portfolio` корректен

### 1.3. ИИС-3 account assignment

- [ ] Все `holdings[i].account` ∈ {`"main"`, `"iis_3"`}
- [ ] Сумма `value_rub` для записей с `account == "iis_3"` равна `balance_summary.iis_balance_rub` (с погрешностью ≤1 руб.)
- [ ] Если позиция split между main и ИИС-3 → две записи с одним ticker, разными account и qty
- [ ] `balance_summary.total_current_rub_excl_iis` ≠ `balance_summary.total_current_rub` (баг v1 исправлен)
- [ ] `balance_summary.by_account` содержит обе записи `main` и `iis_3`
- [ ] `balance_summary.by_account.iis_3.bonds_rub` соответствует сумме holdings.value_rub для bond + iis_3

### 1.4. Backward compatibility

- [ ] Старые поля в `holdings` не изменены (ticker, name, qty, value_rub, asset_type, currency, etc.)
- [ ] `cash`, `returns`, `per_instrument_xirr` структура идентична v1
- [ ] Старые consumers (например, скрипты для XIRR), читающие v1 поля, продолжают работать

### 1.5. Decimal parsing

- [ ] Значения в формате «5,59» из вкладок Numbers корректно парсятся в `5.59`
- [ ] Значения «-» парсятся в `null`
- [ ] Значения `None` или пустые строки парсятся в `null` (не в `0.0`)
- [ ] `ie_model.positions[i].div_yield_2024_pct` для тикеров без дивов = `null`, не `0.0`

### 1.6. Data quality flags

- [ ] Если `ie_model_total_mismatch` обнаружен → flag добавлен в `data_quality_flags`
- [ ] Если split iis-3 position → flag `iis_split_position`
- [ ] Если ie_changes detected → flag `ie_changes_detected` с деталями

### 1.7. End-to-end test

Test scenario: загрузить текущий `Общий баланс.numbers` пользователя через обновлённый loader.

- [ ] Loader не падает с error
- [ ] Output JSON содержит ie_model с реальными 21 позицией
- [ ] Diff с предыдущим v1 JSON (через jq) показывает только additive changes (новые поля)
- [ ] `ru-portfolio-advisor` v2 принимает этот snapshot как input без ошибок
- [ ] `portfolio-scenario-stress` v2 принимает этот snapshot как input без ошибок

---

## Phase 2: Advisor refactor

### 2.1. Input contract

- [ ] Advisor принимает `PORTFOLIO-{date}.json` v2.x как primary input
- [ ] Advisor проверяет staleness (rejects > 14d с warning)
- [ ] Advisor fallback на raw `.numbers + trades.xlsx` работает (запускает loader inline)
- [ ] Без любого input — advisor first response: «Нужны файлы», ничего больше
- [ ] Advisor не пытается работать на схеме v1.x (выдаёт SchemaIncompatible)

### 2.2. Default mode (chat output)

- [ ] Без флага `--save-to-library` advisor выдаёт только chat response
- [ ] Никакие файлы не записываются в library без explicit user trigger

### 2.3. `--save-to-library` mode

- [ ] При triggers «save weekly», «подготовь репорт для сохранения», `--save-to-library` advisor дополнительно генерирует YAML
- [ ] YAML появляется в чате как code block для visual inspection
- [ ] YAML парсится `python -c "import yaml; yaml.safe_load(...)"` без ошибок
- [ ] YAML соответствует schema v1 (см. acceptance ниже)

### 2.4. YAML schema correctness

- [ ] `schema_version: 1`
- [ ] `type: weekly-stocks-review`
- [ ] `horizon_months: 20` (hard-locked)
- [ ] `snapshot_id` ссылается на реальный snapshot
- [ ] `per_stock` содержит все active positions
- [ ] Каждый position имеет: weight_real_pct, sector, fundamental_score, div_yield_12m_pct (с CI), advisor_verdict, verification_priority
- [ ] Каждый position имеет `on_iis` field
- [ ] ИИС-3 позиции имеют `advisor_verdict_constraints` non-empty
- [ ] ИИС-3 позиции не имеют `advisor_verdict ∈ {SELL, TRIM}` (rule R10)

### 2.5. Catalyst tree compliance (R2 + R9)

- [ ] **Каждый** catalyst имеет non-null `source` field
- [ ] Catalyst без source отсутствует в YAML (не пустой source — отсутствует целиком)
- [ ] Каждый catalyst имеет `source_quality ∈ {HIGH, MEDIUM, LOW}`
- [ ] Каждый catalyst имеет `in_horizon: bool`
- [ ] Catalyst с `in_horizon: false` отсутствует в YAML (отбрасывается)
- [ ] `macro_dependency` либо null, либо реально существующий scenario id
- [ ] Каждый catalyst имеет CI для upside_pct или downside_pct

### 2.6. CI everywhere (R1)

- [ ] `div_yield_12m_pct` имеет `ci_pct: [lo, hi]`
- [ ] Каждый catalyst's upside/downside имеет CI
- [ ] `summary.equity_div_yield_weighted_pct` имеет CI

### 2.7. Caveats

- [ ] `caveats` содержит минимум 1 запись severity HIGH
- [ ] Хотя бы один caveat про catalyst calibration / phantom precision
- [ ] Если есть div confidence LOW позиции → caveat про это

### 2.8. Quality checks

- [ ] `quality_checks` array присутствует
- [ ] Все checks имеют `passed: true`
- [ ] Если хотя бы один failed → YAML не отдаётся, advisor сообщает об ошибке генерации

### 2.9. End-to-end test

- [ ] Запустить advisor на свежем PORTFOLIO snapshot v2 с флагом `--save-to-library`
- [ ] Получить YAML в чате
- [ ] Запустить `save-to-library type=weekly-review` на этом YAML
- [ ] Save-to-library принимает YAML без ошибок и сохраняет в `Weekly-Reviews/`

---

## Phase 3: Stress test extension

### 3.1. Schema correctness

- [ ] STRESS YAML содержит `schema_version: 1` в начале
- [ ] STRESS YAML содержит `type: portfolio-stress-test`
- [ ] Старые поля сохранены (backward compat)

### 3.2. Scenario IDs

- [ ] `scenarios` is dict с keys как stable IDs (`Sc-A_bull`, `Sc-D_base`, etc.)
- [ ] Каждый scenario имеет alias `p` дополнительно к `probability`
- [ ] Сумма всех `p` ≈ 1.0 (±0.001)

### 3.3. Per-position breakdown

- [ ] `per_position` содержит все active (non-blocked, non-zero) positions из snapshot
- [ ] Каждая position имеет: weight_pct, on_iis, factor_betas, delta_pct_by_scenario, expected_pct_pweighted
- [ ] Каждая position имеет `on_iis` корректно унаследованный из snapshot
- [ ] `expected_pct_pweighted` имеет CI
- [ ] `delta_pct_by_scenario.{id}` для каждого scenario — value + CI
- [ ] `tail_var_pct` указывает на worst scenario value
- [ ] `tail_var_scenario_id` корректен

### 3.4. Macro blindspots

- [ ] `macro_blindspots` array присутствует
- [ ] Включает позиции с low R² (если есть)
- [ ] Включает hardcoded idiosyncratic (MDMG, PRMD, OZON, DOMRF, WUSH, X5, GLRX) если они в портфеле

### 3.5. Cross-validation with weekly-review

- [ ] Все scenario IDs упомянутые в `weekly-review.per_stock.{ticker}.catalyst[].macro_dependency` существуют в stress.scenarios
- [ ] (Это check делается в синтезаторе, не в stress producer'е, но stress IDs не должны меняться silently)

### 3.6. End-to-end test

- [ ] Запустить stress test на свежем snapshot v2
- [ ] Output YAML парсится без ошибок
- [ ] `portfolio-integrated-view` принимает этот YAML как input

---

## Phase 4: Synthesizer (portfolio-integrated-view)

### 4.1. Skill structure

- [ ] `SKILL.md` имеет валидный frontmatter (name, description)
- [ ] Description content correctly triggers (test через несколько типичных queries)
- [ ] Anti-pattern queries не activate skill

### 4.2. Input validation

- [ ] Synthesizer fail-fast на `schema_version` mismatch (не parsing best-effort)
- [ ] Stale checks работают:
  - PORTFOLIO > 14d → warning
  - STRESS > 90d → warning
  - REVIEW > 14d → warning
- [ ] Critical staleness (>30 / >180 / >30) → refuse to generate
- [ ] Unresolved `macro_dependency` → warning HIGH, не fatal

### 4.3. Output structure

Generated `INTEGRATED-VIEW-{date}.md` содержит:

- [ ] Header с metadata (schema, snapshot/stress/review IDs, ages)
- [ ] Section 0: Stale checks (присутствует если warnings)
- [ ] Section 1: HIGH-priority verification (или explicit «нет HIGH-priority»)
- [ ] Section 2: Per-position dashboard table с CI везде
- [ ] Section 3: Equity vs Bond verdict
- [ ] Section 4: Agreement zone
- [ ] Section 5: Disagreement zone
- [ ] Section 6: Macro-blindspots
- [ ] Section 7: IE-model deviations
- [ ] Section 8: ИИС-3 constraints (если ИИС-3 balance > 0)
- [ ] Section 9: «What is NOT shown» (всегда)
- [ ] Section 10: predictions_for_review (минимум 5 entries)
- [ ] Section 11: Caveats (наследованы)
- [ ] Source files paths в конце

### 4.4. Computation correctness

- [ ] `total_pct` per position = macro_pct + div_pct + idio_pct (с propagated CI)
- [ ] `idio_pct` использует joint P через macro_dependency (не безусловное P)
- [ ] Catalyst с `source_quality: LOW` дисконтированы (P × 0.5)
- [ ] Trust matrix applied: catalysts с IGNORE source_quality исключены
- [ ] Equity vs Bond aggregates корректны (weighted by weight_pct)
- [ ] CI propagation работает (CI на total не уже чем CI на components)

### 4.5. R10 enforcement

- [ ] Все ИИС-3 позиции в Section 2 помечены ❄ icon
- [ ] Никакая ИИС-3 позиция не имеет verdict SELL или TRIM
- [ ] Section 8 показывает ИИС-3 maturity и YTM
- [ ] Synthesizer не предлагает sell/trim ИИС-3 даже при negative spread

### 4.6. R5 enforcement

- [ ] Section 9 «What is NOT shown» содержит конкретные ссылки на исходники (paths)
- [ ] Section 9 включает минимум 7 пунктов из spec (deals, fundamentals, scenarios full, etc.)
- [ ] HIGH-priority section содержит explicit verification checklists с метриками для проверки

### 4.7. End-to-end test

Полный pipeline на реальных данных пользователя:

1. [ ] Загрузить реальные `.numbers` + trades.xlsx
2. [ ] Запустить `portfolio-data-loader` → snapshot v2 generated
3. [ ] Запустить `macro-forecast-chain` (если необходимо обновить macro)
4. [ ] Запустить `portfolio-scenario-stress` → STRESS YAML v1 generated
5. [ ] Запустить `ru-portfolio-advisor --save-to-library` → REVIEW YAML v1 в чате
6. [ ] Запустить `save-to-library type=weekly-review` → REVIEW сохранён
7. [ ] Запустить `portfolio-integrated-view` → INTEGRATED-VIEW md generated
8. [ ] INTEGRATED-VIEW содержит все sections, корректные числа, CI везде, ИИС-3 помечены
9. [ ] Запустить `save-to-library type=integrated-view` → IV сохранён

### 4.8. TODO.md

- [ ] `TODO.md` создан внутри скилла
- [ ] TODO покрывает R3, R4 full, R7 maturation, R8, R9 для v2+
- [ ] TODO версионирован (v1.1, v2, v3, v4)

---

## Phase 5: Infrastructure (save-to-library + forecast-monitor)

### 5.1. save-to-library

- [ ] Добавлен type `weekly-review` с validation
- [ ] Добавлен type `integrated-view` с validation
- [ ] Validation отлавливает: missing source, missing CI, schema version mismatch, missing required sections
- [ ] При invalid input — clear error message, NOT silent save
- [ ] Filename pattern корректный (`Weekly-Reviews/REVIEW-YYYY-MM-DD.yaml`)
- [ ] Storage flow: Synology first, gdrive fallback
- [ ] INDEX.md обновляется после save

### 5.2. forecast-monitor

- [ ] Добавлен block «Portfolio artifacts staleness»
- [ ] Проверки SNAPSHOT (≤14d), STRESS (≤90d), REVIEW (≤14d), INTEGRATED-VIEW (≤7d)
- [ ] Алерты идут в weekly digest вместе с forecast monitoring

### 5.3. INDEX.md

- [ ] Новые subsections созданы: Portfolio Snapshots, Portfolio Stress Tests, Weekly Reviews, Integrated Views
- [ ] Каждый save-to-library run обновляет соответствующую subsection
- [ ] Subsection «Self-validation roadmap» создан с target date через 6 мес

---

## Phase 6: HTML viewer (опционально для MVP)

См. `06-portfolio-integrated-viewer-HTML-spec.md` Section 9 (acceptance criteria).

Ключевые:
- [ ] Schema validation работает (rejects incompatible versions)
- [ ] All 8 tabs render correctly
- [ ] Drill-down modal работает
- [ ] Privacy: no network calls после initial CDN load
- [ ] Mobile responsive at 375px

---

## Phase 7: Validation hooks

### 7.1. Calendar reminder

- [ ] Создан reminder / calendar event на `today + 6 months` с описанием:
  - «Запустить retrospective-forecast-audit на накопленных predictions_for_review»
  - Ссылка на soft-reminder в `INDEX.md` Self-validation roadmap

### 7.2. INDEX.md update

- [ ] Раздел «Self-validation roadmap» в INDEX.md содержит:
  - Target date
  - Что проверить (predictions_for_review, catalyst hit rates)
  - Какой skill запустить (retrospective-forecast-audit)
  - Что обновить в результате (calibration factors → catalyst-tree-rules.md)

---

## Cross-cutting acceptance

### Quality

- [ ] Все YAML валидны через `yamllint --strict` (или эквивалент)
- [ ] Все Markdown валидны (no broken links, headers in order)
- [ ] Все Python скрипты проходят pylint / ruff без warnings
- [ ] Test coverage для синтезатора ≥ 70%

### Documentation

- [ ] CHANGELOG.md в каждом обновлённом скилле (4 скилла + 1 новый)
- [ ] EXAMPLES.md в `portfolio-integrated-view` skill
- [ ] README.md в репо обновлён с описанием integrated pipeline

### Privacy / Security

- [ ] Никакие данные пользователя не уходят за пределы Claude Memory / Synology / Google Drive
- [ ] HTML viewer: no network calls с user data
- [ ] No hardcoded credentials anywhere
- [ ] Schemas публичны (могут shared в репо), data — нет

### Performance

- [ ] `portfolio-data-loader` v2 не медленнее v1 более чем на 30%
- [ ] `portfolio-integrated-view` синтез < 30s на портфеле 60 позиций
- [ ] HTML viewer initial render < 1s на 60 позиций

---

## Final integrity check

После завершения всех Phases:

- [ ] **Real test**: пользователь запускает полный pipeline на своих данных и получает coherent integrated-view с реалистичными числами
- [ ] **Sanity test**: equity vs bond verdict не противоречит реальности (e.g., bond YTM 14% реально, не +50%)
- [ ] **CI sanity**: confidence intervals не уходят в impossible regions (e.g., expected return -200%)
- [ ] **No phantom precision**: каждое число имеет CI или explicit «point estimate, CI unavailable» disclaimer
- [ ] **No recommendations**: integrated-view не содержит «продай X», «купи Y» — только сравнения и highlights

Если все criteria выше выполнены — система **готова к production use**.

В случае bugs / unexpected behavior после release:
1. Открыть issue в GitHub репо
2. Привязать к конкретному failed criterion из этого документа
3. Регрессия → write test that reproduces, fix, add to test suite
