# Portfolio Integrated View — Master Plan

**Версия:** 1.0
**Дата:** 2026-05-05
**Статус:** ready for implementation
**Цель:** объединить macro-стресс и weekly-review в единый dashboard, который честно сравнивает equity expected return с bond YTM на горизонте до конца 2027.

---

## 1. Что мы строим

Pipeline из трёх слоёв с read-only синтезатором сверху:

```
LAYER 1 — DATA
  portfolio-data-loader (.numbers + trades.xlsx → PORTFOLIO-{date}.json v2)

LAYER 2A — MACRO (quarterly)            LAYER 2B — EQUITY (weekly)
  macro-forecast-chain                    ru-portfolio-advisor (Weekly Review mode)
        ↓                                       ↓
  portfolio-scenario-stress              [новый] --save-to-library флаг
        ↓                                       ↓
  STRESS-{date}.yaml                     WEEKLY-REVIEW-{date}.yaml

LAYER 3 — SYNTHESIS (on demand, weekly cadence)
  [новый] portfolio-integrated-view
        ↓
  INTEGRATED-VIEW-{date}.md
        ↓
  [новый] portfolio-integrated-viewer.html  (interactive dashboard)
        ↓
  ЧЕЛОВЕК (решение)
```

## 2. Принятые решения (фиксируется здесь как single source of truth)

### 2.1. Mitigation rules (R1–R10)

| ID | Risk | Решение в v1 |
|---|---|---|
| R1 | Phantom precision | **Confidence intervals везде** (`{value, ci: [lo, hi]}`). Никогда point estimate без CI |
| R2 | Catalyst hallucinations | **Source required**. Нет source → нет catalyst. `source_quality: LOW` → `p × 0.5` discount |
| R3 | Horizon mismatch | **Принудительная нормализация на 20 мес.** Catalyst с date_window > 20 мес → `in_horizon: false` → отбрасывается |
| R4 | Correlations | **`macro_dependency` per catalyst.** Если катализатор привязан к stress-сценарию, его α умножается на P(сценария), не на безусловное P(catalyst). v2 — full covariance matrix |
| R5 | Cognitive substitution | **Раздел «What is NOT shown» обязателен.** Каждое предложение содержит explicit «проверь у эмитента: X, Y, Z» с конкретными метриками |
| R6 | Schema drift | **Strict schema_version + dependency contract.** На несовместимой версии — fail fast, не best-effort parsing |
| R7 | Validation loop | **`predictions_for_review` block** в integrated-view. Каждая прогноз-таблица с датой проверки. Через 6 мес — `retrospective-forecast-audit` |
| R8 | Concurrency | v2 (lockfile). v1 — explicit предупреждение |
| R9 | Asymmetric catalyst quality | Частично закрыто через R2 (источники для pharma/tech сложно найти → меньше catalyst → меньше шанс инфляции α) + `source_quality` flag |
| R10 | ИИС-3 constraint | **`account` field в holdings + `verification_priority` в advisor.** Synthesizer не предлагает SELL для iis_3 позиций |

### 2.2. Cadence

| Слой | Каденция | Trigger |
|---|---|---|
| Data (snapshot) | По загрузке файлов | User uploads `.numbers` + trades.xlsx |
| Macro forecast chain | Quarterly | + macro shock > 10% по любому фактору |
| Portfolio stress | Quarterly + after macro chain | |
| Weekly Review | Weekly (понедельник) | + corp event / earnings / div decision |
| Integrated View | Weekly (после Weekly Review) | Manual trigger в v1; scheduled в v2 |

### 2.3. Horizon

**Принудительный horizon = 20 месяцев** (до конца 2027).

Все YAML schemas имеют поле `horizon_months: 20`. Все вычисления нормализуются на это окно.

В v2 — поддержка multiple horizons (12 / 20 / 36+ мес).

### 2.4. Output mode для advisor

`--save-to-library` — **opt-in**. Default: только chat output. Триггеры:
- Явный флаг в команде
- Фразы: «подготовь репорт для сохранения», «save weekly», «сохрани обзор»

При триггере advisor генерирует YAML **в чат как artefact**, пользователь визуально проверяет, потом отдельной командой запускает `save-to-library` для записи.

### 2.5. Источник трасты

Trust matrix берётся из `Claude-Memory/INDEX.md` через subdomain weights. Применяется в advisor и synthesizer для discount catalyst confidence.

---

## 3. Файлы пакета

| # | Файл | Назначение | Размер |
|---|---|---|---|
| 00 | MASTER-PLAN.md | Этот файл — overview, decisions, dependency graph | средний |
| 01 | JSON-SCHEMA-V2-PROPOSAL.md | Расширение PORTFOLIO snapshot до v2 | большой |
| 02 | weekly-review-schema-v1.md | Контракт YAML для weekly review (advisor → synthesizer) | большой |
| 03 | stress-schema-additions.md | Что добавить в существующий STRESS YAML | средний |
| 04 | portfolio-integrated-view-SKILL.md | Полный SKILL.md нового скилла | большой |
| 05 | portfolio-integrated-view-TODO.md | Внутренний TODO скилла для v2/v3/v4 | средний |
| 06 | portfolio-integrated-viewer-HTML-spec.md | Спецификация HTML viewer'а | средний |
| 07 | existing-skills-changes.md | Change-list для каждого существующего скилла | большой |
| 08 | acceptance-criteria.md | End-to-end testlist для всей системы | средний |

---

## 4. Зависимости и порядок реализации

```
┌──────────────────────────────────────────────────────────────┐
│ Phase 1: Data Layer (1-2 сессии)                              │
│   Изменить parse_portfolio.py → JSON v2                       │
│   Регенерировать существующий PORTFOLIO snapshot              │
│   Acceptance: все criteria из 01-JSON-SCHEMA-V2 пройдены      │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ Phase 2: Advisor refactor (2-3 сессии)                        │
│   Input contract: JSON v2 как primary input (≤14d)            │
│   Output mode: --save-to-library                              │
│   YAML schema v1 generation (catalyst tree, sources, etc)     │
│   Acceptance: все criteria из 02-weekly-review                │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ Phase 3: Stress test extension (1 сессия)                     │
│   Per-position breakdown                                       │
│   schema_version field                                         │
│   Acceptance: все criteria из 03-stress-schema                │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ Phase 4: Synthesizer (2-3 сессии)                             │
│   Создать portfolio-integrated-view skill                     │
│   Synthesis logic (Python скрипт)                             │
│   TODO.md внутри                                              │
│   Acceptance: end-to-end test на реальных данных              │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ Phase 5: Infrastructure (1 сессия)                            │
│   save-to-library: новые типы артефактов                      │
│   forecast-monitor: staleness checks                          │
│   Acceptance: artifacts корректно сохраняются и мониторятся   │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ Phase 6: HTML viewer (1-2 сессии, опционально для v1)         │
│   Создать portfolio-integrated-viewer.html                    │
│   Schema-validated, renders YAML uploaded by user             │
│   Acceptance: пользователь может открыть YAML в браузере      │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ Phase 7: Validation hooks (0.5 сессии)                        │
│   Calendar reminder: through 6 мес → retrospective audit      │
│   INDEX.md → раздел "Self-validation roadmap"                 │
└──────────────────────────────────────────────────────────────┘
```

**Итого:** ~10 рабочих сессий.

**Минимально жизнеспособная версия (MVP):** Phase 1-5 без HTML viewer. Это уже даёт полный pipeline. HTML viewer (Phase 6) — улучшение UX, не критично для функционала.

---

## 5. Что НЕ делается в v1 (TODO для v2+)

Из R1-R10, **отложены**:
- R3 full handling (multiple horizons) — v2
- R4 full covariance matrix — v2
- R8 concurrency safety (lockfile) — v2
- R9 backtested catalyst quality calibration — v2

Также в v2/v3:
- Per-account XIRR (отдельно для ИИС-3) — нужна отдельная trades-выгрузка
- Calibration of catalyst.p discount factor через retrospective audit
- Interactive HTML dashboard с history view (как менялся verdict со временем)

Полный TODO — в файле `05-portfolio-integrated-view-TODO.md`.

---

## 6. Структура GitHub репо (рекомендация)

```
claude-portfolio-skills/
├── README.md                              # Overview
├── INTEGRATION-DOCS/                      # Все эти файлы (00-08)
│   ├── 00-MASTER-PLAN.md
│   ├── 01-JSON-SCHEMA-V2-PROPOSAL.md
│   ├── 02-weekly-review-schema-v1.md
│   ├── 03-stress-schema-additions.md
│   ├── 04-portfolio-integrated-view-SKILL.md
│   ├── 05-portfolio-integrated-view-TODO.md
│   ├── 06-portfolio-integrated-viewer-HTML-spec.md
│   ├── 07-existing-skills-changes.md
│   └── 08-acceptance-criteria.md
├── skills/
│   ├── portfolio-data-loader/             # existing, будет обновлён
│   │   ├── SKILL.md
│   │   ├── scripts/
│   │   │   ├── parse_portfolio.py         # ← Phase 1: расширить до v2
│   │   │   ├── moex_quotes.py
│   │   │   └── portfolio_returns.py
│   │   └── references/
│   ├── ru-portfolio-advisor/              # existing, будет обновлён
│   │   ├── SKILL.md                        # ← Phase 2: input contract + save-to-library
│   │   ├── scripts/
│   │   ├── references/
│   │   │   └── catalyst-tree-rules.md     # ← Phase 2: новый файл
│   │   └── EXAMPLES.md
│   ├── portfolio-scenario-stress/         # existing, будет обновлён
│   │   └── SKILL.md                        # ← Phase 3: per_position breakdown
│   ├── portfolio-integrated-view/         # NEW — Phase 4
│   │   ├── SKILL.md
│   │   ├── TODO.md
│   │   ├── scripts/
│   │   │   └── synthesize.py
│   │   └── references/
│   ├── save-to-library/                   # existing, обновлён в Phase 5
│   ├── forecast-monitor/                  # existing, обновлён в Phase 5
│   └── ...other existing skills...
├── tools/
│   └── portfolio-integrated-viewer.html   # NEW — Phase 6
└── tests/
    ├── test_parse_portfolio_v2.py         # Phase 1 acceptance
    ├── test_weekly_review_schema.py       # Phase 2 acceptance
    └── test_synthesizer_e2e.py            # Phase 4 acceptance
```

---

## 7. Кто делает что (рекомендация)

**Claude Code** (моя рекомендация на финальном вопросе):
- Phases 1-5 (multi-file Python refactoring + skills updates)
- Phase 6 (HTML viewer)
- Все тесты

**Cowork** при желании:
- Phase 0 — review этих документов
- Phase 6 — если хочется работать с HTML интерактивно

**Я (Claude в чате)**:
- Уже сделал Phase 0 (документы пакета)
- При необходимости — review code reviews из Claude Code

---

## 8. Глоссарий

| Термин | Значение |
|---|---|
| **macro_ΔP&L** | Изменение P&L позиции под влиянием macro factors (rate, FX, oil, sanctions). Дает stress-test. |
| **idiosyncratic α** | Изменение P&L позиции из-за catalyst events (corp news, earnings surprises, regulatory). Дает advisor. |
| **div contribution** | Дивидендный доход за horizon (12-mo div yield × scaling factor) |
| **Total expected return** | macro_ΔP&L + div_contribution + idio_α — суммарный ожидаемый return за horizon |
| **YTM-bond equivalent** | Bond YTM, нормализованный на 20-месячный horizon (для apples-to-apples сравнения с equity) |
| **catalyst** | Конкретное событие, которое может произойти в horizon с вероятностью P и эффектом Δ% |
| **macro_dependency** | Привязка catalyst к stress-сценарию (для R4 joint expectation) |
| **verification_priority** | HIGH/MEDIUM/LOW — насколько срочно проверять данные эмитента перед действием |
| **horizon_months** | 20 — единый горизонт всех расчётов в v1 |

---

## 9. Что делать после прочтения этого файла

1. **Прочитать все 9 файлов пакета** в порядке нумерации (00 → 08)
2. **Создать GitHub репо** по структуре из section 6
3. **Скопировать `INTEGRATION-DOCS/`** в репо
4. **Скопировать существующие скиллы** (export из Claude.ai → `skills/`)
5. **Открыть Claude Code в репо** и начать с Phase 1 (JSON schema v2)
6. **Каждый Phase завершается прохождением acceptance criteria из файла 08**

В случае проблем — открывать issue в репо со ссылкой на конкретный criterion.
