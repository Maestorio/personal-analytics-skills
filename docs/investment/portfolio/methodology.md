# Methodology — расчётные подходы для портфельных скиллов

Этот документ — **live source-of-truth** для методологических решений, которые
используются скриптами и скиллами при агрегации catalyst trees, сценарных
прогнозов и портфельных метрик. При изменении любого подхода — обновлять
здесь и менять ссылки в SKILL.md релевантных скиллов.

Связанные канонические файлы:
- Структура YAML — `_shared-references/yaml-schemas.md`
- Семантика полей — `_shared-references/events-yaml-spec.md`
- Сценарная SSOT — `_shared-references/scenario-yaml-spec.md`

---

## 1. Catalyst kinds (METH-1, 2026-05-13)

Каждый catalyst в `weekly-review-stock-*.yaml` (и аналогах) обязан декларировать
`kind`. Две допустимые категории:

### 1.1 `kind: binary` — дискретное событие

Событие либо произошло, либо нет. Примеры: дивотсечка, M&A, регуляторное
одобрение, snyatiye sanctions, MSFO release.

Обязательные поля:
- `p ∈ (0, 0.95]` — вероятность события (безусловная, либо conditional при
  явной сценарной привязке через `active_scenarios`)
- `upside_pct` (numeric) — размер эффекта при наступлении события
- `upside_ci_pct: [lo, hi]` — CI оценки размера

Опциональные:
- `active_scenarios: [scenario_id, ...]` — если событие может произойти только
  в подмножестве сценариев. Если опущено и `macro_dependency` тоже null —
  событие scenario-independent (доступно во всех сценариях).
- `macro_dependency: scenario_id` — legacy-форма скалярного `active_scenarios`
  (равносильно `active_scenarios: [scenario_id]` при backward-compat).

Формула вклада:

```
E[contrib] = p × scenario_mass × upside × src_disc

где scenario_mass:
  = Σ_{s ∈ active_scenarios} p(s)         если active_scenarios задан
  = p(macro_dependency)                    если legacy macro_dependency задан
  = 1                                       если ни active_scenarios, ни macro_dependency

src_disc = 0.5 если source_quality = LOW, иначе 1.0
```

CI пропагируется линейно по тем же весам:
`CI_lo = p × scenario_mass × ci_lo × src_disc`,
`CI_hi = p × scenario_mass × ci_hi × src_disc`.

### 1.2 `kind: quantitative` — непрерывная величина по сценариям

Эффект происходит в разных сценариях с разной амплитудой. Бинарное «случилось/нет»
неприменимо — есть **распределение по величине**. Примеры: rate cut → multiple
re-rating, NIM compression, margin expansion, market share growth.

Обязательные поля:
- `upside_by_scenario: {A: x, B: y, C: z, D: w}` — размер эффекта в каждом
  сценарии. Ключи — `scenario_id` из `scenarios/{slug}-{date}.yaml`
  (`matrix.scenario_triggers.*`).
- `upside_ci_by_scenario: {A: [lo, hi], B: [lo, hi], ...}` — CI на каждый
  сценарий.

Запрещённое поле:
- `p` — для quantitative нет «вероятности срабатывания», вся uncertainty
  магнитуды лежит в `upside_ci_by_scenario`. Если `p` присутствует — validator
  выдаёт warning, агрегатор игнорирует.

Опционально:
- `macro_dependency` — для отчётности (доминирующий сценарий). На расчёт
  **не влияет**. По умолчанию советуется удалять или хранить как `null`.

Формула вклада:

```
E[contrib] = Σ_s p(s) × upside_by_scenario[s] × src_disc
CI_lo     = Σ_s p(s) × upside_ci_by_scenario[s][0] × src_disc
CI_hi     = Σ_s p(s) × upside_ci_by_scenario[s][1] × src_disc
```

Если для какого-то сценария значение не задано — подставляется 0 с warning
`catalyst_quantitative_incomplete_scenarios` уровня yellow.

### 1.3 Legacy / backward-compat

Catalyst без `kind`, написанный в старой схеме (`p`, `upside_pct`,
`macro_dependency`) — интерпретируется как `binary` с
`active_scenarios=[macro_dependency]` если tag задан, иначе scenario-independent
со старым 0.7 дисконтом за null-dependency.

Validator выдаёт `catalyst_missing_kind` уровня yellow. Aggregator выдаёт
warning в output. Это **gradual migration path** — старые отчёты продолжают
считаться (с систематическим занижением), но видны в audit log.

### 1.4 Когда какой kind использовать (decision tree)

1. Можно ли описать catalyst фразой «событие либо произошло, либо нет»?
   → **binary**
2. Имеет ли смысл вопрос «насколько catalyst сработает в этом сценарии»?
   → **quantitative**
3. Описывается ли catalyst в terms of continuous magnitude (КС снизится,
   мультипликатор вырастет, маржа сожмётся)?
   → **quantitative**
4. Это discrete corporate event с фиксированной датой/condition?
   → **binary**
5. Tail risk на одном сценарии (capex overrun, лицензия отозвана)?
   → **binary** с `active_scenarios`

При сомнениях — запустить `classify_catalyst.py` (skill: ru-portfolio-advisor),
он даёт heuristic suggestion + reasoning.

### 1.5 Фильтр macro-overlap

Не писать catalyst для эффектов, которые **полностью** улавливаются макро-бетами
в стресс-тесте (КС → equity-цена через линейную бету; USD/RUB → FX-облигации).
Дублирование = двойной счёт.

Можно писать catalyst, если он captures:
- Non-linear часть (re-rating sentiment, ускорение при пороге)
- Idiosyncratic events (дивы, MSFO, M&A)
- Sector-specific reactions, которых нет в макро-факторах
- Tail risks, специфичные для компании

---

## 2. Сценарные веса p(s) (D1, scenario-yaml-spec)

- 4 mutually exclusive сценария A/B/C/D, веса хранятся в
  `scenarios/{slug}-{date}.yaml` (SSOT).
- Default D1 — равные веса 0.25/0.25/0.25/0.25.
- При Σ p(s) ≠ 1 — `aggregate_positions.normalize_scenario_probs()`
  нормализует `p_norm = p / Σ`. Warning severity LOW/MEDIUM по отклонению
  (`SCENARIO_P_LOW_THRESHOLD = 0.02`, `SCENARIO_P_MEDIUM_THRESHOLD = 0.05`).
- Изменение весов через `macro-forecast-chain --mode RECALIBRATE`
  пересчитывает Layer 2 marginals и stress modal ranking, **не трогая**
  catalyst trees (они хранят per-scenario data, marginal — derived).

---

## 3. CI propagation (additive v1)

Все агрегаты используют **линейную свёртку CI** под одинаковыми весами,
что и для point estimate. Это **conservative additive** допущение: ошибки
компонент считаются полностью коррелированными.

```
total = macro + div + idio
ci_lo(total) = ci_lo(macro) + ci_lo(div) + ci_lo(idio)
ci_hi(total) = ci_hi(macro) + ci_hi(div) + ci_hi(idio)
```

Для портфельного спреда equity/bond поддерживаются **два** варианта:
- `ci_linear` (corr=1, conservative) — линейная свёртка
- `ci_quadratic` (corr=0, realistic) — `σ = √(σ_eq² + σ_bond²)`,
  где `σ_X ≈ width(CI_X) / 4` (предположение нормальности 95% CI).

`portfolio-integrated-view` показывает оба, текст в §4 явно поясняет
интерпретацию.

**Что НЕ делаем (v2 roadmap):**
- Полная ковариационная декомпозиция между сценариями.
- Per-scenario correlation matrices между компонентами.
- Гипотетические joint distributions через Monte Carlo.

---

## 4. Source quality discount

| Quality tag | Множитель к вкладу catalyst | Где применяется |
|---|---|---|
| `HIGH` | 1.0 | primary source (e-disclosure, ИФА, IR-release) |
| `MEDIUM` | 1.0 | sell-side analyst с verifiable attribution |
| `LOW` | 0.5 | анонимные источники, Smart-lab, Pulse без attribution |
| `IGNORE` (в trust matrix) | 0.0 (catalyst отбрасывается) | блок-листы доменов |

CI для `LOW` дополнительно расширяется ×1.5 на этапе advisor'а
(`catalyst-tree-rules.md`). На этапе aggregator'а — только point-множитель.

**METH-2 примечание:** IE-target и planned_share_pct **не используются** как источники истины в иерархии принятия решений. Они — координаты target frame (§9.3), применяются **после** fundamental gate. Источниковая система (HIGH/MEDIUM/LOW) — отдельная плоскость от gate state.

---

## 5. Trust matrix / unresolved macro_dependency

- Pipeline gate (R-PIPE): доля catalyst с unresolved `macro_dependency`
  (scenario_id не в текущем scenarios YAML) > 30% → integrated-view FAIL
  с явным сообщением «запусти RECALIBRATE».
- Unresolved single catalyst → discount 0.7 (как для null-dependency),
  но это **симптом**, не норма. Должно быть починено advisor'ом.

---

## 6. Snapshot drift (R-SNAP)

- Если `snapshot_id` стресс-теста и обзоров расходятся > 3 дней — warning.
- Веса позиций ВСЕГДА берутся из stress (R-SNAP), не из обзора. Это
  гарантирует консистентность с per-scenario factor sensitivities.

---

## 7. Дивиденды vs bond carry (R-BOND-CARRY)

Приоритет источника:

1. **Bond carry**: `ytm_pct` из `weekly-review-bond` → fallback `xirr` из
   снапшота → fallback 0 (с warning).
2. **Equity dividends**: `div_yield_12m_pct` из `weekly-review-stock` × N/12.

Bond carry = `базис × eff_months/12` — линейная нормировка (без рекапитализации).
Это `marginal` annualization; реальная total return с учётом реинвестирования
выше на 1–3 пп — это документировано как caveat в §9 integrated-view.

**Защита от yield-to-offer (put/offer-облигации):** MOEX отдаёт `ytm_pct` для бумаги
с близкой офертой как доходность-к-оферте (на коротком горизонте — сотни % годовых).
Умножать её на горизонт нельзя. Поэтому:
- `eff_months = min(horizon_months, месяцев до ближайшей offer_date/maturity_date)` —
  после оферты/погашения бумага гасится, carry дальше не идёт;
- если `ytm_pct` неправдоподобен (>60%) → базис переключается на `coupon_pct`
  (экономику оферты несёт catalyst `offer_exit`, не carry);
- backstop-клампа `|carry| ≤ 50 пп`.
Upstream: `portfolio-data-loader` (`moex_quotes.py`) разделяет `ytm_pct` (YTM-к-погашению)
и `ytm_to_offer_pct`; `revise-memory-remote` флагует `per_bond.ytm_pct > 100`.

---

## 8. Annualization

`Eγ_horizon → annualized`:

```
annualized = horizon_value × 12 / horizon_months
```

Линейная (не геометрическая) — соответствует подходу advisor'а к catalyst
upside (тоже линейные point estimates без compound'а). Геометрический
annualized = `(1 + horizon_value)^(12/H) − 1` доступен опционально через
скрипт-helper, но в default-отчётах не используется.

---

## 9. Fundamental Gate — трёхслойная иерархия (METH-2, 2026-05-13)

См. `docs/investment/portfolio/new_met.md` для полной спецификации. Краткая методологическая сводка:

### 9.1 Слои принятия решений

```
1. Fundamental gate           ← filter (бинарный: alive/under_review/broken)
   "Компания жизнеспособна как актив?"
   Метрики: маржа, кэш, долг, менеджмент, рыночная позиция, catalyst delivery

2. Macro / scenario context   ← sizing modifier
   "Внешние условия благоприятны на 20 мес?"
   Источник: catalyst.upside_by_scenario + Portfolio/stress/

3. Target frame               ← tactical (как двигаемся к target)
   planned_share_pct → ie_target → real
```

**Иерархия**: фундаментал → IE → planned. Фундаментал — gate, остальное — координаты тактики **внутри** "go" решения.

### 9.2 Логика комбинации (gate × macro)

| Fundamental gate | Macro modal scenario | Verdict |
|------------------|---------------------|---------|
| alive | tailwind | BUY/HOLD к target |
| alive | neutral | HOLD, small adds возможны |
| alive | headwind | HOLD без adds, ждать триггеров |
| alive | severe headwind | TRIM до safe-size |
| under_review | любой | HOLD, ждать gate-clarification |
| broken | любой | REDUCE/EXIT поэтапно |

### 9.3 IE-target vs planned_share_pct

- `planned_share_pct` (snapshot.ie_actual.per_ticker[T]) — **primary** target, из Numbers
- `ie_new_pct` — **secondary** signal, IE может оспаривать planned
- Оба применяются **после** fundamental gate, не вместо него
- При `planned=null` → fallback на `ie_new_pct` с явной пометкой в reasoning

---

## 10. Gate Review Workflow (METH-2, 2026-05-13)

### 10.1 8 статусов SSOT

Файл: `Claude-Memory/Portfolio/gate-reviews.yaml`

| Статус | Кто ставит | Семантика |
|--------|-----------|-----------|
| `new_position` | save-to-library (auto) | Только что куплено, первые 4 нед — ожидаемое |
| `review_needed` | Mode 1 / Mode 8 | Hard trigger, требуется Mode 4 |
| `reviewed_keep` | Mode 4 / Mode 8 | Gate alive |
| `reviewed_buy_more` | Mode 4 / Mode 8 | Фундаментал улучшился, апгрейд |
| `reviewed_under_review` | Mode 4 / Mode 8 | Gate uncertain |
| `reviewed_reduce` | Mode 4 / Mode 8 | Gate broken |
| `review_aging` | auto при `valid_until < today` | Оценка устарела |
| `divested` | save-to-library (auto) | Продано из портфеля |

### 10.2 Cooldown vs valid_until

- `cooldown_until = set_date + 21д` — анти-спам Mode 1 повторными триггерами
- `valid_until = set_date + valid_days` — TTL решения, по истечении → `review_aging`

`valid_days` зависит от ticker_class (`_shared-references/ticker-classes.md`):

| Класс | `valid_days` |
|-------|--------------|
| `bluechip` | 60 |
| `mid_cap` | 45 (default) |
| `small_cap` / `ipo` / `event_driven` | 30 |

### 10.3 Critical events — двухуровневая модель

- **Closed enum** (auto-override cooldown): `bankruptcy_filing`, `delisting_announce`, `sanction_against_issuer`, `fraud_charges`, `emergency_ceo_change`
- **Open trigger** (proposed-directive с подтверждением): `quarterly_negative_fcf_2x`, `controlling_shareholder_legal`, `insider_large_sale`, `rating_downgrade_2plus_notches`, free_text

Список — `ru-portfolio-advisor/references/critical-events-list.md`.

### 10.4 Workflow по Mode

| Mode | Gate role |
|------|-----------|
| **1** | Inherit + trigger detect. При **любом** триггере (`flags.gate_review_required: true` — closed critical event, open trigger, истёкший `valid_until`, дивергенция weight/fundamental) эмитит `gate_review_directive` → `review_needed`. F4.5 применяет без подтверждения. НЕ флипает в reviewed_*. |
| **3** | Reader-only. Skip review_needed, применяет stability caps. |
| **4** | Updater. Три режима глубины: full / stale-caveat / fundamental-only. Эмитит `gate_review_update` (finальный `reviewed_*`). |
| **8** | Bulk updater + escalator. Эмитит `gate_review_bulk_update`: `reviewed_*` для решённых тикеров, `review_needed` для тикеров, требующих Mode 4 (противоречивые сигналы, низкая confidence + значимый вес, data gap, неэффективная позиция). |

Mode 1 — на cooldown — выводит блок `Watchlist (cooldown active)` с накопленными сигналами, не молчит.

### 10.5 Re-buy после divest

Простое правило: `divested` → `new_position` всегда. Прошлая history архивируется в `gate-reviews-archive-{year}.yaml`. Новый цикл — с чистого листа.

### 10.6 Concurrent-edit guard

При применении directive через save-to-library Workflow M — проверка timestamp ordering против `history[-1].date`. Запоздавшая директива rejected. Точный повтор → idempotent no-op.

### 10.7 Bootstrap и автоматическое обслуживание

`Portfolio/gate-reviews.yaml` создаётся и обслуживается **без явного запроса пользователя**:

- При первом же сохранении Mode 1 (weekly-stocks-review) через `save-to-library` срабатывает Workflow F шаг **F4.5** → `auto_maintain_gate_reviews.py` с пустым SSOT и текущим snapshot. Все тикеры snapshot получают `new_position` с `valid_until` по ticker_class.
- На последующих сохранениях Mode 1 F4.5 поддерживает SSOT: `reviewed_*` стареют в `review_aging` после `valid_until`, исчезнувшие из snapshot тикеры (≥ N missing snapshots) уходят в `divested`, вернувшиеся — снова `new_position` (history архивируется).
- Mode 4 / Mode 8 эмитят явные директивы → Workflow M (`apply_gate_review.py`).

Pure no-op (файл не переписывается) если auto-maintain не нашёл ни одной transition и SSOT уже существовал. Bootstrap (первый запуск) всегда создаёт файл.

---

## 11. Mode 3 Stability Rules (METH-2, 2026-05-13)

### 11.1 Caps по gate status

| Status | Cap drift | INCREASE | REDUCE |
|--------|-----------|----------|--------|
| `new_position` (≤4 нед) | 0.5 п.п. | да (small) | да |
| `none` (нет записи) | 1.0 п.п. (×0.5) | нет | да |
| `review_needed` | **skip** | — | — |
| `reviewed_keep` | 1.5 п.п. | да | да |
| `reviewed_buy_more` | 1.5 п.п., priority | да | да |
| `reviewed_under_review` | 0.5 п.п. | нет | да |
| `review_aging` | 0.5 п.п. | нет | да |
| `reviewed_reduce` | 40% позиции/цикл | нет | да |
| `divested` | ignore | — | — |

### 11.2 Четыре правила

1. **Cap per position per cycle** — см. таблицу 11.1
2. **Cap per cycle** — ≤4 позиции за rebalance, приоритет: broken → under_review с trigger → drift ≥2 п.п.
3. **Hysteresis** — не двигать если `|real - target| < 1 п.п.` И нет триггера
4. **Continuity check** — прочитать предыдущий weekly-review, не разворачивать verdict без gate-flip объяснения
5. **L1 redirect total-return rule** — если суммарный buffer от per-position решений пересекает границу L1-класса (stocks→bonds/fund/cash), redirect-пропорция обосновывается **per-instrument total return** сравнением, а не stress-EV кластером. См. `rebalance-framework.md` §6. Stress-EV cluster spread пропускает дивиденды, idio catalysts и instrument-specific YTM — недостаточное основание для L1 redirect.

### 11.3 Carve-outs

- **Полный гейт-крах на крупной позиции** (banker's-style critical event) — Правило 1 отменяется через `critical_event_code`
- **Налоговая оптимизация** (декабрь, IIS-3 окончание) — Cap per cycle расширяется до 6–8

---

## История изменений

| Дата | Что | Скилл / файл |
|---|---|---|
| 2026-05-16 | Mode 3 §11.2 правило 5: L1 redirect total-return rule (stress-EV cluster spread недостаточен для L1 redirect; обязателен per-instrument TR) | methodology.md §11.2, rebalance-framework.md §6, output-templates.md Шаблон 3 |
| 2026-05-13 | METH-2: Fundamental Gate Review Tracking (SSOT, 8 статусов, Mode 3 stability) | Portfolio/gate-reviews.yaml, apply_gate_review.py, auto_maintain_gate_reviews.py, validate_library.py (Слой 5), advisor process docs, viewer |
| 2026-05-13 | METH-1: catalyst kind split (binary/quantitative) + per-scenario upside | aggregate_positions.py, catalyst-tree-rules.md, validate_library.py |
| 2026-05-10 | D8: dynamic scenario attribution; flatten_trust как noop | forecast-confidence-applier |
| 2026-05-08 | D1–D7: двухслойная архитектура прогнозов (Layer 1 marginal + Layer 2 by_scenario) | events-yaml-spec.md |
