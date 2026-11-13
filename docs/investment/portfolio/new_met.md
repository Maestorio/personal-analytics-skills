# METH-2: Fundamental Gate Review Tracking (v3)

**Дата:** 2026-05-13 (исходный план), 2026-06-09 (статус актуализирован)
**Статус:** ✅ **РЕАЛИЗОВАНО** — это не план, а живая спецификация (SSOT) gate-review.
Реализующий код: `skills/save-to-library/scripts/auto_maintain_gate_reviews.py`,
`skills/save-to-library/scripts/apply_gate_review.py`, схема снапшота —
`skills/portfolio-data-loader/scripts/assemble_snapshot.py` (все ссылаются на §3.1–§3.8).
В каталоге документации (`docs/investment/README.md`) классифицирован как **DOC**, не PLAN.
Исходный статус (2026-05-13): «план согласован, готов к реализации».
**Связано с:** METH-1 (catalyst kinds, `methodology.md`), архитектура advisor Mode 1/3/4/8

---

## 1. Проблема

### 1.1 Якорь на IE-target

`ru-portfolio-advisor` в Mode 4 (Single Analysis) неявно использует `ie_actual.per_ticker.{T}.ie_new_pct` (доля по модели Invest Era) как «правильный» target. В существующих docs:

- `analysis-process.md` Шаг 5: «Любой обзор обязан учитывать `ie_actual` до любого внешнего анализа»
- `rebalance-framework.md`: классификация дрейфа строится **относительно** IE New
- Trust-иерархия IE фильтрует **сигналы изменений**, но не **уровень** target'а

Результат: при вопросе «стоит ли докупать OZON до целевой доли?» советник по умолчанию обсуждает **тайминг входа к 7%**, а не «является ли 7% разумной целью с учётом фундаментала, концентрации и истории XIRR». Пересмотр target включается только при прямом промте «а стоит ли вообще доходить до X%».

### 1.2 Существует `planned_share_pct`, но не используется

В snapshot уже есть `ie_actual.per_ticker.{T}.planned_share_pct` — колонка «Доля Планируемая» из Numbers, заполняемая пользователем. Loader пишет её (`parse_portfolio.py:281-291`), viewer показывает (`portfolio-integrated-viewer.html:4556`). Advisor её **не использует** ни в одном из mode-документов.

### 1.3 Mode 1 не имеет инструмента эскалации

Mode 1 (Weekly Stock Review) — лёгкий, без полного FCA и сценарного стресса. При обнаружении hard trigger (резкое падение NIM, санкция, делистинг-risk) Mode 1 не имеет ресурсов для глубокого фундаментального пересмотра, но и не имеет машинно-проверяемого способа просигнализировать «эту бумагу надо разобрать в Mode 4». Если ставить булев флаг каждую неделю — Mode 1 будет триггерить пересмотр на одной и той же информации, что приведёт к шуму.

### 1.4 Mode 3 действует слепо

Mode 3 (Rebalance) предлагает действия на основе divergence от IE без учёта того, что (а) фундаментальный тезис мог сломаться, (б) макро-сценарий не благоприятствует, (в) пользователь намеренно отклонился от IE через planned_share_pct. Также — Mode 3 не имеет stability constraints: может предлагать «продать 270 акций сейчас» без phased подхода.

---

## 2. Решение — трёхслойная архитектура

### 2.1 Иерархия принятия решений

```
1. Fundamental gate            ← filter (бинарный: можем ли вообще держать)
   "Компания жизнеспособна как актив?"
   Маржа, кэш, долг, менеджмент, рыночная позиция, catalyst delivery

2. Macro / scenario context    ← sizing modifier (какого размера при текущей погоде)
   "Внешние условия благоприятны на 20 мес?"
   catalyst.upside_by_scenario, stress files

3. Target frame                ← tactical (к какому уровню движемся)
   planned_share_pct → ie_target → real
```

**Логика комбинации:**

| Fundamental gate | Macro modal scenario | Verdict |
|------------------|---------------------|---------|
| alive | tailwind | BUY/HOLD к target |
| alive | neutral | HOLD, small adds возможны |
| alive | headwind | HOLD без adds, ждать триггеров |
| alive | severe headwind | TRIM до safe-size |
| under_review | любой | HOLD, ждать gate-clarification |
| broken | любой | REDUCE/EXIT поэтапно |

Иерархия: фундаментал → IE → planned. **Фундаментал — gate, остальное — координаты тактики ВНУТРИ "go" решения.**

### 2.2 Mode-specific поведение

| Mode | Поведение после fundamental gate |
|------|----------------------------------|
| **1 — Weekly Review** | Naследует gate из последнего weekly-review/Mode 4 эмита. Trigger detect. При hard trigger — directive «нужен Mode 4». Без числовых таргетов в default-режиме (бинарка «приближаться к target / не приближаться»). |
| **3 — Rebalance** | Reader-only gate. Skip review_needed. Применяет stability rules. Числовая оптимизация % только для прошедших gate. |
| **4 — Single Analysis** | Updater gate для одного тикера. Три режима глубины: full (stress свежий) / stale-caveat / fundamental-only (нет stress — не выдаёт committed %). |
| **8 — Stock Quality Forward Review** | Batch updater gate для всей корзины. Раз в 2–3 мес. |

---

## 3. SSOT файл `Portfolio/gate-reviews.yaml`

### 3.1 Schema

```yaml
schema_version: "gate-reviews@1.0"
last_updated: 2026-05-13

tickers:
  SBER:
    status: review_needed
    set_date: 2026-05-13
    set_by: mode_1
    trigger_reason: "Q1 NIM упал с 5.8% до 4.7%"
    cooldown_until: null            # активен только при reviewed_*
    valid_until: null               # активен только при reviewed_*
    ticker_class: bluechip
    history:
      - date: 2026-05-13
        status: review_needed
        set_by: mode_1
        reason: "Q1 NIM drop"

  OZON:
    status: reviewed_keep
    set_date: 2026-04-30
    set_by: mode_4
    trigger_reason: "Q1 2026 — 4-й прибыльный квартал, тезис подтверждён"
    cooldown_until: 2026-05-21      # set_date + 3 нед
    valid_until: 2026-06-14          # set_date + 45 дней (mid-cap)
    ticker_class: mid_cap
    history:
      - date: 2026-04-15
        status: review_needed
        set_by: mode_1
        reason: "thin margin warning"
      - date: 2026-04-30
        status: reviewed_keep
        set_by: mode_4
        reason: "fundamental thesis intact"
```

### 3.2 State enum (8 статусов)

| Статус | Кто ставит | Семантика |
|--------|-----------|-----------|
| `new_position` | save-to-library (auto при первом появлении в snapshot) | Только что куплено. Mode 3 трактует мягко (cap 0.5 п.п., REDUCE OK). Первые 4 нед — ожидаемое состояние. |
| `review_needed` | Mode 1 / Mode 8 / мост conditions (`on_trigger.set_status`) | Hard trigger обнаружен ИЛИ сработало условие, требующее пересмотра, — требуется Mode 4 |
| `reviewed_keep` | Mode 4 / Mode 8 / `user` (переподтверждение) | Gate alive, тезис подтверждён |
| `reviewed_buy_more` | Mode 4 / Mode 8 / `user` | Фундаментал улучшился, рекомендация увеличить target |
| `reviewed_under_review` | Mode 4 / Mode 8 / `user` | Gate uncertain — держать без adds |
| `reviewed_reduce` | Mode 4 / Mode 8 / `user` | Gate broken — поэтапный выход |
| `review_aging` | автоматически (auto-promote при `valid_until < today`) | Оценка устарела. Mode 3 трактует как `reviewed_under_review`. |
| `divested` | save-to-library (auto при исчезновении из snapshot) | Бумага продана. Mode 3 игнорирует. |

**`set_by: user` (2026-07-23).** Переподтверждение решения самим пользователем — типовой
кейс: гейт постарел до `review_aging`, а решение уже принято в свежем weekly-обзоре и
полный Mode 4 избыточен. Переход `review_aging → reviewed_*` с `set_by: user` легален
**только с явным подтверждением пользователя в чате** (сессия не назначает его сама);
cooldown-защиту `review_needed` (§3.3, анти-спам) `user` не обходит — в отличие от
Mode 4/8. До 2026-07-23 такие переходы маскировались под `set_by: mode_4`, и провенанс
в history врал (кейс SBER/SBERP 23.07) — ради этого лейбл и введён.

**Мост из conditions (2026-07-23).** `conditions.yaml` → `on_trigger.set_status` может
толкать не только settled `reviewed_*`, но и `review_needed`: «условие сработало →
тикер требует разбора Mode 4» (зажигает 🟡 во вьюере). Настоящий канал для условий,
исход которых надо переосмыслить, — вместо запрещённого «settled-статус без Mode 4».

### 3.3 Cooldown и valid_until — разделение задач

```
cooldown_until = set_date + 3 нед         # анти-спам Mode 1 повторными триггерами
valid_until    = set_date + valid_days     # TTL решения, по истечении → review_aging
```

**`valid_days` зависит от ticker_class:**

| Класс | `valid_days` | Критерий |
|-------|-------------|----------|
| `bluechip` | 60 | Top-20 ликвидности на MOEX (SBER, GAZP, LKOH, GMKN, ROSN, MGNT и т.д.) — фундаменталы меняются медленно |
| `mid_cap` | 45 | MOEX, MTLR, IRAO, OZON, PLZL и др. |
| `small_cap` / `ipo` (<1 год) / `event_driven` | 30 | BTBR, DOMRF, NVTK при санкциях — fundamentals летят быстрее |
| `fund_zpif` | 90 | Биржевые фонды (ЗПИФ/ETF, напр. Рентал ПРО): фундаментал квартальный — отчёты УК, NAV. Первичный разбор — Mode 5a (`set_by: mode_5a`) |

Default при отсутствии классификации — **45**. Список фиксирован в `_shared-references/ticker-classes.md`, не определяется LLM.

**Scope:** gate-механизм покрывает только торгуемые позиции. Замороженные (`holdings[].status == "blocked"` — санкционная заморозка 2022: JPM, KO, FinEx и т.п.) вне scope: MOEX их не котирует, фундаментал-ревью невозможен; auto-maintain и validator исключают их автоматически.

**Cooldown 3 нед — единый для всех** (анти-спам, не функция класса).

### 3.4 Critical events — двухуровневая механика

```yaml
# references/critical-events-list.md
closed_enum_no_confirm:        # cooldown_override автоматически
  - bankruptcy_filing
  - delisting_announce
  - sanction_against_issuer
  - fraud_charges
  - emergency_ceo_change

open_trigger_with_confirm:     # Mode 1 эмитит proposed-directive, пользователь подтверждает
  - quarterly_negative_fcf_2x
  - controlling_shareholder_legal
  - insider_large_sale          # >20% пакета
  - rating_downgrade_2plus_notches
  - <free_text + proposed_override: true>
```

**Closed enum**: Mode 1 эмитит `gate_review_directive` с `reason_code` из enum → save-to-library применяет автоматически, cooldown игнорируется.

**Open trigger**: Mode 1 эмитит `proposed_gate_review_directive` с `requires_user_confirmation: true` → пользователь явно подтверждает → save-to-library применяет.

### 3.5 Mode 1 — Watchlist при cooldown

Когда cooldown активен и hard trigger обнаружен (не critical), Mode 1 **не молчит**, а выводит:

```markdown
### Watchlist (cooldown active)
| Тикер | Cooldown до | Накопленные сигналы |
|-------|-------------|---------------------|
| OZON | 2026-05-21 | Q1 EBITDA margin 16%, цена +3% |
```

Если в Watchlist накопилось ≥3 средних сигнала или ≥1 hard trigger без override — рекомендация «рассмотреть досрочный Mode 4» (как рекомендация, не директива).

### 3.6 Concurrent-edit guard

При применении directive через save-to-library Workflow M:
1. Read текущий `gate-reviews.yaml`, найти `tickers.{T}`
2. Сравнить `directive.set_date` с `history[-1].date`
3. Если `directive.set_date < history[-1].date` (запоздавшая) → reject, warning
4. Если `==` И `set_by ==` (повтор) → idempotent, no-op
5. Иначе → append в history, update top-level

### 3.7 Re-buy после divest

Тикер был `divested`, появился снова в snapshot:
1. save-to-library auto-maintain ставит `new_position` с `first_appearance_date = today`
2. Прошлая history (до `divested`) архивируется в `gate-reviews-archive-{year}.yaml`
3. Новый цикл начинается «с чистого листа» — новый Mode 4 при первом hard trigger

Простое правило > умное правило. Даже короткий gap (<14 дней) → `new_position`. Gate review дешёвый.

### 3.8 History bounded + archive

- Active `gate-reviews.yaml`: последние **10** записей history на тикер
- Overflow → `gate-reviews-archive-{year}.yaml` (append-only)
- Viewer tooltip: последние 3 + ссылка на архив

### 3.9 Mode 3 — таблица caps по статусу

| Status | Cap drift | INCREASE | REDUCE |
|--------|-----------|----------|--------|
| `new_position` (≤4 нед) | 0.5 п.п. | да (small) | да |
| `none` (нет записи) | 1.0 п.п. (×0.5 от обычного) | нет | да |
| `review_needed` | **skip** в блок `pending_review` | — | — |
| `reviewed_keep` | 1.5 п.п. (default) | да | да |
| `reviewed_buy_more` | 1.5 п.п., приоритет | да | да |
| `reviewed_under_review` | 0.5 п.п. | нет | да |
| `review_aging` | 0.5 п.п. | нет | да |
| `reviewed_reduce` | 40% позиции за цикл | нет | да (план Mode 4) |
| `divested` | ignore | — | — |

### 3.10 Stability rules (Mode 3)

1. **Cap per position per cycle** — см. таблицу 3.9
2. **Cap per cycle** — ≤4 позиции за один rebalance (priority: broken → under_review с trigger → drift ≥2 п.п.)
3. **Hysteresis** — не двигать если `|real - target| < 1 п.п.` И нет триггера
4. **Continuity check** — прочитать предыдущий weekly-review, не разворачивать verdict без gate-flip объяснения

---

## 4. Python delegation

### 4.1 Что LLM, что Python

| Задача | Python | LLM |
|--------|--------|-----|
| Детект hard trigger из новостей | ✗ | ✓ |
| Текст `trigger_reason` | ✗ | ✓ |
| Verdict Mode 4 (keep/reduce/buy_more) | ✗ | ✓ |
| Schema validation directive | ✓ | ✗ |
| State transition table | ✓ | ✗ |
| Date math (cooldown_until, valid_until) | ✓ | ✗ |
| Auto-promote → review_aging | ✓ | ✗ |
| Auto-init new_position | ✓ | ✗ |
| Auto-divest | ✓ | ✗ |
| Re-entry detection | ✓ | ✗ |
| Concurrent-edit guard | ✓ | ✗ |
| History truncation + archive | ✓ | ✗ |
| Closed_enum check | ✓ | ✗ |
| Orphan/consistency checks | ✓ | ✗ |

### 4.2 Скрипты

**1. `save-to-library/scripts/apply_gate_review.py`**
- Вход: directive YAML, текущий `gate-reviews.yaml`
- Шаги: validate schema → timestamp merge guard → state-transition table → recompute дат → append history → truncate to 10 → output
- Чисто stdlib (ручной YAML парсер, как в существующих скриптах)
- Тесты: ≥25 проверок

**2. `save-to-library/scripts/auto_maintain_gate_reviews.py`**
- Вход: последний snapshot, текущий `gate-reviews.yaml`
- Логика:
  - Тикер в snapshot, нет в SSOT → init `new_position`
  - SSOT.status=`reviewed_*` с `valid_until < today` → auto-promote → `review_aging`
  - Тикер в SSOT, нет в snapshot N циклов подряд → auto-promote → `divested`
  - SSOT.status=`divested`, появился снова → `new_position` (re-entry)
- Запускается save-to-library при ingestion нового snapshot
- Тесты: ≥20 проверок

**3. `revise-memory-remote/scripts/validate_gate_reviews.py`** (или интеграция в `validate_library.py`)
- Schema validation, orphan check vs snapshot, history append-only, stale-warnings, консистентность дат
- Тесты: ≥15 проверок

---

## 5. Изменения в файлах

### 5.1 Новые файлы

1. `Claude-Memory/Portfolio/gate-reviews.yaml` (SSOT, создаётся при первой записи)
2. `Claude-Memory/Portfolio/gate-reviews-archive-{year}.yaml` (по необходимости)
3. `_shared-references/ticker-classes.md` (bluechip / mid_cap / small_cap список)
4. `ru-portfolio-advisor/references/critical-events-list.md` (closed_enum + open_trigger)
5. `save-to-library/scripts/apply_gate_review.py` + тесты
6. `save-to-library/scripts/auto_maintain_gate_reviews.py` + тесты
7. `revise-memory-remote/scripts/validate_gate_reviews.py` (или интеграция)

### 5.2 Изменяемые файлы

- `ru-portfolio-advisor/SKILL.md` — описание gate_review интеграции
- `ru-portfolio-advisor/references/analysis-process.md` — Mode 1/3/4/8 шаги
- `ru-portfolio-advisor/references/output-templates.md` — gate_review_update директива в Mode 4/8
- `ru-portfolio-advisor/references/stocks-methodology.md` — Mode 4 шаг «Output directive»
- `ru-portfolio-advisor/references/rebalance-framework.md` — таблица caps + pending_review блок
- `ru-portfolio-advisor/references/catalyst-tree-rules.md` §7 — fundamental gate в pre-emit checklist
- `save-to-library/SKILL.md` — Workflow M
- `save-to-library/scripts/assemble_artifact.py` — Workflow M интеграция
- `save-to-library/tests/test_assemble_artifact.py` — тесты Workflow M
- `revise-memory-remote/scripts/validate_library.py` — интеграция validate_gate_reviews
- `revise-memory-remote/tests/test_validate_library.py` — тесты
- `portfolio-data-loader/scripts/parse_portfolio.py` — first_appearance_date
- `tools/portfolio-integrated-viewer.html` — gate badge, фильтры, tooltip
- `_shared-references/claude-memory-layout.md` — новый путь
- `_shared-references/yaml-schemas.md` — gate-reviews schema
- `_shared-references/file-naming.md` — singleton convention
- `docs/investment/portfolio/methodology.md` — 3 новых раздела
- `docs/investment/TODO.md` — METH-2 status

### 5.3 Тесты — оценка

~80 новых проверок:
- apply_gate_review: ~25
- auto_maintain: ~20
- validate_gate_reviews: ~15
- viewer integration (ручная проверка): ~5
- assemble_artifact (Workflow M): ~10
- loader (first_appearance_date): ~5

---

## 6. Viewer

### 6.1 Рендеринг

- Колонка/badge Gate Status per ticker в таблице «Акции»:
  - ⚪ `new_position`
  - 🟡 `review_needed`
  - 🟢 `reviewed_keep`
  - 🔼 `reviewed_buy_more`
  - 🟠 `reviewed_under_review`
  - 🟠 `review_aging` (тот же оранжевый, другая иконка/подпись)
  - 🔴 `reviewed_reduce`
  - ⚫ `divested` (скрывается по умолчанию)
- Tooltip: trigger_reason, set_date, set_by, cooldown_until, valid_until, последние 3 history

### 6.2 Фильтры

- «☐ Только review_needed»
- «☐ Только recent review (≤30 дней)»
- «☐ Скрыть divested» (default ON)

### 6.3 Секция «Сегодня»

- Блок «Pending gate reviews» если есть `review_needed` старше 7 дней
- Блок «Aging reviews» если есть `review_aging`

### 6.4 Transport

`gate-reviews.yaml` грузится через тот же fetch + js-yaml, что и `weekly-reviews/*.yaml`. Никакой spec.

---

## 7. Порядок реализации

1. **Stage 1** — Python скрипты + тесты (фундамент, изолированно): `apply_gate_review.py`, `auto_maintain_gate_reviews.py`, `validate_gate_reviews.py`
2. **Stage 2** — `portfolio-data-loader` patch: `first_appearance_date` + тесты
3. **Stage 3** — Process docs (advisor): analysis-process, output-templates, stocks-methodology, rebalance-framework, catalyst-tree-rules §7, critical-events-list, ticker-classes
4. **Stage 4** — save-to-library Workflow M: SKILL.md + assemble_artifact.py + тесты
5. **Stage 5** — revise-memory-remote integration
6. **Stage 6** — docs/investment/portfolio/methodology.md (3 новых раздела)
7. **Stage 7** — viewer: gate badge, фильтры, tooltip + ручная проверка
8. **Stage 8** — TODO.md + shared-refs финализация

Коммит-стратегия: per-этап коммит.

Оценка времени: 6–8 часов на чистую реализацию + тесты + viewer.

---

## 8. Открытые/закрытые вопросы

### Закрыто:

1. **Cooldown default**: 3 нед для всех
2. **Critical events**: двухуровневая модель (closed_enum + open_trigger)
3. **Mode 1 в cooldown**: Watchlist-секция, не молчит
4. **Concurrent edits**: timestamp merge в save-to-library
5. **Weekly-review хранит gate_status_snapshot** (read-only mirror), не свой verdict
6. **History bounded 10 + archive по году**
7. **Validator orphan check** против snapshot
8. **Stale review handling**: разделение `cooldown_until` (3 нед) и `valid_until` (30-60 дней)
9. **`valid_days` class-зависим**: bluechip 60 / mid_cap 45 / small_cap/ipo 30
10. **Re-buy после divest**: всегда `new_position`, прошлая history в archive
11. **`reviewed_buy_more`**: добавлен
12. **portfolio-data-loader** пишет `first_appearance_date`
13. **D3 compliance**: Workflow M через save-to-library (не исключение)
14. **Mode 1 → SSOT**: directive, save-to-library применяет

### Открыто (на будущее):

- Mode 9 «Target Sizing Review» с EV-оптимизацией — отложено на 6+ мес, требует данных для cov-матрицы
- `personal_target_pct` поле в weekly-review — отменено, planned_share_pct из snapshot достаточно
