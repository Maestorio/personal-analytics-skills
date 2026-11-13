---
name: portfolio-integrated-view
description: >
  Read-only синтезатор macro-stress + weekly-review + portfolio snapshot в единый
  dashboard для решений по композиции портфеля (equity vs bond) на нескольких горизонтах (v2: 6/12/24, primary 12).
  Только агрегация трёх артефактов с propagation of confidence intervals, joint
  expected return через macro_dependency, подсветка disagreement zones. Никаких
  buy/sell рекомендаций, никаких новых прогнозов.
  ИСПОЛЬЗУЙ когда: «сведи стресс и обзор», «полная картина по портфелю»,
  «equity vs bond verdict», «integrated view», «честное сравнение акции облигации»,
  «что докупать с учётом всего», «собери картину 20 месяцев».
  НЕ активировать на: расчёт XIRR/доходности (→ portfolio-data-loader), глубокий
  разбор тикера (→ ru-portfolio-advisor), пересмотр стресс-сценариев
  (→ portfolio-scenario-stress), построение новых прогнозов
  (→ forecast-confidence-applier), advice по ребалансировке (→ ru-portfolio-advisor).
shared_refs: [transport-layer, yaml-schemas, claude-memory-layout, file-naming, model-routing, events-yaml-spec]
---

# portfolio-integrated-view

Read-only синтезатор для биостатистика-инвестора: честно собирает картину
**expected return per position** с CI на горизонте 20 мес и подсвечивает,
где equity beats bond и наоборот. Не пересчитывает данные, не даёт
рекомендаций, не строит прогнозы — только агрегация.

---

## Inputs / Outputs

**Inputs (обязательные):**
- Portfolio snapshot `portfolio-{date}.json` (schema 2.0) ← `Portfolio/snapshots/` через transport-layer, age ≤ 14d
  **Порядок обнаружения снапшота:** `Glob("{MEMORY_ROOT}/Portfolio/snapshots/portfolio-*.json")` — единственный канонический паттерн; взять файл с наибольшей датой в имени. Запрещено: искать в корне `Claude-Memory/` или произвольных директориях. Если Glob вернул ошибку → `request_cowork_directory` → повторить Glob → только потом диагностировать отсутствие.
- Stress test `stress-{date}-{slug}.yaml` (schema 1) ← `Portfolio/stress/`, age ≤ 90d
  **Числа — из пересчёта сайта, если он есть.** Найти самый свежий стресс (по дате в имени; из двух файлов одной даты — записанный позже), затем проверить `Portfolio/stress/auto/recalc-{имя этого стресса}.yaml`. Файл есть — под ключом `stress` в payload идёт ЕГО содержимое целиком (те же суждения на последнем снапшоте и весах сайта), иначе числа обзора отстанут от портфеля. Файла нет — идёт сам стресс. Пересчёт другого, не самого свежего стресса не брать. Не брать и пересчёт, сделанный раньше последней записи файла стресса (`recalc.at` раньше времени записи файла): стресс заменили под тем же именем, пересчёт остался от прежней версии — идёт сам стресс, в `data_quality` строка об этом. Возраст стресса и поля `inputs.stress`, `stress_date`, `stress_age_days` — по файлу стресса скилла (дата суждений; у файла пересчёта `date` — день пересчёта, по ней стресс всегда выглядел бы свежим); время пересчёта — в `inputs.stress_recalc_at`.
- Weekly review (Phase 10.4 split): каждый YAML сопровождается парным MD рядом (один и тот же date / stock|bond):
  - `weekly-review-stock-{date}.yaml` + `weekly-review-stock-{date}.md` — схема `weekly-stocks-review`
  - `weekly-review-bond-{date}.yaml` + `weekly-review-bond-{date}.md` — схема `weekly-bonds-review`
  - YAML — для расчётов (синтез, агрегация); MD — для §1 verdict-pointer (читабельная цитата)
  - Все файлы → `Portfolio/weekly-reviews/`, age ≤ 14d
  - Старый формат `weekly-review-{date}.{yaml,md}` (без stock/bond суффикса) — legacy, читается с пометкой LEGACY_FORMAT

**Inputs (опциональные):**
- `Claude-Memory/INDEX.md` — trust matrix для catalyst confidence discount
- Macro context для intermediate-уровневой диагностики:
  - `macro-chain/macro-marginal-{date}.yaml` — Layer 1 (для weekly-review EV decisions)
  - `macro-chain/macro-scenarios-{date}.yaml` — Layer 2 (4 coherent scenario bundles, для stress diagnostic)
- Предыдущий `integrated-view-{date}.md` — для diff-секции (флаг `--diff-with-previous`, v1.1)
- `scenarios/horizons.json` — сроки, заданные на сайте: кладётся в payload под `horizons_file` (ключ `horizons` — список горизонтов); не совпал со сроками стресса — `validation.stress_terms_mismatch` (§0 и оговорка в §9: числа стресса относятся к прежним срокам)

**Schema v2 (Phase 4 — multiple horizons):**
- Payload несёт `horizons: [6, 12, 24]` (список, default) и `primary_horizon` (default 12). Вход не schema 2 (stress/review без `schema_version: 2`) скрипт отклоняет ошибкой `schema_v1_not_supported` с адресом мигратора `migrate_v1_to_v2.py`.
- Stress v2 несёт `per_position.X.by_horizon.{hNN}` и top-level `horizon_ends`; weekly-review v2 —
  `horizons`/`horizon_ends`, catalyst без `in_horizon` (consumer считает из `date_window`, §11.3).
- **Coverage-инвариант (fail-fast):** запрошенные горизонты должны быть в stress. Несовпадение
  (или v1-stress с >1 горизонтом) → output `{error: "horizon_mismatch", ...}`; синтез не делать,
  перегенерировать stress с нужными горизонтами.
- **Output:** `per_position[t].by_horizon.{hNN}` + плоские поля = `primary_horizon` (совместимость
  прозы/viewer); `portfolio_by_horizon`, `tail_flags_by_horizon`, `sanity_by_horizon` — на каждый
  горизонт; `predictions_for_review` — единый dedup-список катализаторов с полем `horizons: [...]`.
- **CLI:** `--horizon 12` (повторяемо, подмножество) / `--all-horizons` (default).
- **Вердикты — один на позицию**, привязаны к `primary_horizon` (D4-8). Per-horizon вердиктов не плодить.

**Schema v2 (Phase 4 — Monte Carlo CI, V2-B):**
- CI считается через **Monte Carlo** (`ci_method: mc`, default; stdlib `random`, 10k путей,
  `mc: {paths, seed}` в output). На каждом пути разыгрывается ОДИН сценарий, общий для всех
  позиций/катализаторов → когерентные «миры», корреляции учитываются честно, без `corr_matrix`.
- **Точечные значения остаются аналитическими** (D4-7) — MC меняет только CI (per-position
  `total.ci`, portfolio equity/bond CI, единый `spread.ci` вместо пары linear/quadratic).
  `tail_flags` считаются от MC-CI.
- `--ci-mode analytic` возвращает прежний аналитический CI (двойной spread linear/quadratic) —
  для регрессии/отладки. `--mc-paths` / `--mc-seed` — детерминизм.
- **Guard `mc_divergence`:** при `|MC mean − analytic| > 1.5 п.п.` по equity/bond — запись в
  `mc_divergence` (поднять как caveat: точка и центр CI расходятся).
- **Spread CI в §2:** в v2 (mc) — единый `ci`; в `--ci-mode analytic` — прежняя пара corr=0/corr=1.

**Двухслойная архитектура (events-yaml-spec.md §5):**
- Stress YAML использует `by_scenario` напрямую (Layer 2 из `forecast.conditional_on_scenarios`).
- Weekly-review использует `forecast.central_estimate` (Layer 1, marginal trust-weighted FCA).
- Если в stress YAML отсутствуют `expected_pl_pct`/`expected_pl_rub` (новый default по D2) —
  использовать `worst_case`/`best_case`/`spread`/`modal_scenario_id` для портфельной диагностики.

**Что читает integrated-view (по типам forecast):**
- **Stress YAML** (обязательный) — это уже агрегированный bundle от `macro-forecast-chain`, содержит per-scenario значения. Никакие forecast YAML напрямую не читаются.
- **Weekly-review YAML/MD** — из catalysts ссылается на `macro_dependency: <scenario_id>`; integrated-view сам forecast YAML не открывает, использует только id для cross-link на Сценарии (через viewer).
- **`macro-marginal-{date}.yaml`** (от macro-forecast-chain) — Layer 1 marginal по каждому фактору (точечные оценки от Type 1 isolated + central_estimate от Type 2). LLM парсит его и передаёт в payload под ключом `macro_marginal` как `{factor: {level_l1_<год>: <число>, unit: <unit>}}`. Скрипт переводит уровень→движение против `baseline_spot` из stress, вычисляет `macro_return_l1 = Σ_f (beta[f] × движение[f])` и кладёт её в **`macro.l1_point`** + `macro.coherence_gap = |l1 − l2|` (разрыв с Layer 2 из stress). **@1.4:** канонический `macro.value` при этом ОСТАЁТСЯ Layer 2 p-weighted (MC-совместимый центр) — L1-точка информационная, headline/spread/CI она не двигает (см. Шаг 4 «Единый канон»). **Поведение по умолчанию (A8d):** если свежий `macro-marginal-{date}.yaml` (age ≤ 30 дней) доступен через transport-layer — **использовать его как L1-overlay**; не ждать явной просьбы. Явная фраза пользователя «макро из стресса» / «только L2» — переопределяет (skip L1). При отсутствии файла или age > 30 дней — Layer 2 без изменений.
  - **Контракт payload (MFC-4 — иначе L1 не сработает):**
    - **Формат фактора:** `level_l1_<год>` (числовой уровень от `compute_marginal_move.py`) + `unit` (`usd_per_bbl` / `rub_per_usd` / `rub_per_cny` / `usd_per_troy_oz` / `rate_pct`). Скрипт сам переводит уровень в движение против `baseline_spot` из stress по контракту единиц (см. `references/events-yaml-spec.md` §5.6): price-факторы → % от спота, `cbr_rate` → Δ п.п. Год выбирается ближайший к горизонту прогона (`as_of + horizon_months`).
    - **Источник payload:** прогнать `macro-forecast-chain/scripts/compute_marginal_move.py` на блоке `factors` из `macro-marginal-{date}.yaml` — он добавит `level_l1_<год>` + `unit` рядом с человекочитаемыми строками. `baseline_spot` берётся из stress автоматически (`run()` читает `stress.baseline_spot`).
    - **Ключи фактора = имена `factor_betas` в stress** (`geopol`, `brent`, `cbr_rate`, `cnyrub`, `usdrub`, `xauusd`, `sanctions`). Скрипт умеет alias `geopolitics→geopol` (`MACRO_FACTOR_ALIASES`); факторы без соответствующей беты пропускаются.
    - **Backward-compat:** старый плоский числовой `central_estimate` (= уже готовое движение) по-прежнему принимается, если нет `level_l1_<год>`/`baseline_spot`.
    - Если ни один фактор не дал числовое движение (все качественные строки вроде geopolitics/sanctions, либо нет `baseline_spot`) → `macro.l1_point = null`, overlay не считался (не ложный L1=0).
- **`macro-scenarios-{date}.yaml`** (опц., от macro-forecast-chain) — Layer 2 bundle (4 coherent scenario bundles). Используется как фоновая диагностика для сверки с stress YAML.
- **Type 1 isolated forecast YAML** напрямую integrated-view НЕ читает — они проходят через macro-marginal aggregation в macro-forecast-chain.

**Outputs (черновик в `_drafts/` + выжимка в чат, Шаг 6):**
- `integrated-view-{date}.md` → `Claude-Memory/_drafts/` → save-to-library (Workflow G1.0) переносит в `Portfolio/integrated-views/`
- в чат — выжимка: акции vs облигации по горизонтам, joint expectation, что сменилось против прошлого вида, строка «черновик: …»

**Upstream скиллы:** portfolio-data-loader (snapshot), portfolio-scenario-stress (stress), ru-portfolio-advisor (weekly-review)
**Downstream скиллы:** save-to-library, retrospective-forecast-audit (через 6 мес — проверка predictions_for_review), forecast-monitor (мониторит staleness)
**Shared refs:** transport-layer, yaml-schemas, claude-memory-layout, file-naming

---

## Модель

**Opus** (текущий Opus-тир) обязательно. Скилл синтезирует три
разнородных артефакта со сложной propagation of CI и joint expectation — Sonnet
даёт worse calibration на multi-source aggregation. См. `references/model-routing.md`.

---

## Глобальные правила (применяй ВЕЗДЕ)

1. **READ-ONLY.** Не запускай advisor, stress, FCA, и другие skills. Если данных не хватает — выдай warning и попроси пользователя запустить нужный pipeline. **Никогда** не подменяй отсутствие свежего STRESS «мнением о macro».

2. **Schema versioning fail-fast (R6).** Перед чем-либо проверь версии всех трёх входов. На несовместимых — fail fast с ясным сообщением. Не пытайся best-effort парсить старые форматы. Детали — `references/synthesizer-workflow.md` Шаг 1.

3. **Staleness checks обязательны.** При запуске:
   - snapshot ≤ 14d — иначе warning HIGH
   - stress ≤ 90d — иначе warning HIGH + предложить запустить `macro-forecast-chain` + `portfolio-scenario-stress`
   - review ≤ 14d — иначе warning HIGH + предложить запустить `ru-portfolio-advisor` weekly review с `--save-to-library`

   Если **любой** артефакт старше критического порога (snapshot >30, stress >180, review >30) — **отказывайся** от синтеза, попроси обновить.

4. **Confidence intervals propagate (R1).** Каждое числовое предсказание в финальной таблице — `value [lo, hi]` или `value (CI)`. Никогда не показывай point estimate без CI. Если в исходниках нет CI — placeholder `[value*0.5, value*1.5]` + явный warning.
   Для портфельных агрегатов (Equity vs Bond, spread) выводить **два варианта CI**:
   - **Консервативный** (линейное сложение, corr = 1): `spread_ci = [equity_lo − bond_hi, equity_hi − bond_lo]` — текущий подход.
   - **Реалистичный** (квадратурное сложение, независимые ошибки): `σ_eq = (equity_hi − equity_lo)/4`, `σ_bond = (bond_hi − bond_lo)/4`, `σ_spread = sqrt(σ_eq² + σ_bond²)`, CI ≈ `[spread − 2σ_spread, spread + 2σ_spread]`.
   Реальный CI лежит между этими двумя — корреляция компонент не оценена. Детали — `references/synthesizer-workflow.md` Шаг 4.

5. **Joint expectation kind-aware (R4, METH-1).** Формула вклада catalyst зависит от `kind`:
   - **`binary`**: `E = p × scenario_mass × upside × src_disc`, где `scenario_mass = Σ p(s)` для `s ∈ active_scenarios` (или legacy `[macro_dependency]`), либо `NULL_DEPENDENCY_DISCOUNT = 0.7` если scenario не задан.
   - **`quantitative`**: `E = Σ_s p(s) × upside_by_scenario[s] × src_disc` — никакого `p`, никакого scenario-gate.
   - **legacy без `kind`**: backward-compat по эвристике — `binary` с scenario gate (систематическое занижение для continuous catalysts; validator выдаёт `catalyst_missing_kind` yellow).

   Полная методология и формулы — `docs/investment/portfolio/methodology.md` §1. Реализация — `scripts/aggregate_positions.py::compute_catalyst_contribution`. Источник правды для классификации kind при заполнении weekly-review — `skills/ru-portfolio-advisor/references/catalyst-tree-rules.md`.

6. **NO recommendations.** Никаких «продай SBER», «купи ОФЗ», «ребалансируй сектор X». Synthesizer **не генерирует** свои buy/sell/trim сигналы и **не цитирует** конкретные action items из обзоров (лимитные заявки, лоты, ценовые лимиты). Допустимо только:
   - **Quantitative comparison:** «expected return SBER +30.4% [+5; +52] vs YTM ОФЗ 14% → spread +16.4 п.п.»
   - **Verdict-pointer** (цитата verdict-кода из обзора как ярлык для навигации, не как руководство к действию): «📄 weekly-review-stock-2026-05-06.md → SBER: TRIM» — указатель на парный markdown-обзор (для облигаций — `weekly-review-bond-{date}.md`), не призыв трюмить.
   - **Disagreement highlights:** «advisor verdict TRIM, но macro ΔP&L positive в base scenario»
   - **Verification suggestions** (что проверить ДО любого действия по источнику): «приоритет HIGH: проверь дивполитику CHMF, free-float SBER»

   **НЕ допустимо** в §1 / §3 / любом другом месте артефакта:
   - «Лимитная заявка +80 шт. ≤1280 ₽» — это копирование action item из обзора, тяните его через pointer.
   - «Купи на просадке» / «зафиксируй прибыль» / «закрой позицию» — собственные сигналы, запрещены.
   - «При сценарии Sc-X сделай Y» — встраивание сценарной логики (см. сценарную независимость).

7. **«What is NOT shown» секция обязательна (R5).** Explicit раздел с указателями на исходники для проверки. Никаких «итоговых вердиктов», подменяющих чтение исходников.

8. **HIGH-priority positions выделены отдельно (C5).** Позиции с `verification_priority: HIGH` — отдельная секция в начале с чек-листом метрик для самостоятельной проверки.

9. **ИИС-3 positions constrain-locked (R10).** `on_iis: true` → метка ❄, advisor_verdict смягчается до «hold-by-constraint». Не предлагать sell/trim для ИИС-3 даже при сильно отрицательном equity-vs-bond spread.

10. **Каждый запуск создаёт `predictions_for_review` block (R7).** Минимум 5 проверяемых предсказаний с датами и источниками. Правило дат:
    - **20-мес прогнозы** (equity vs bond spread, bond carry) — дата проверки `view_date + 20 мес`, не через 6 мес.
    - **Промежуточные сверки** (через 6 мес) — записывать как отдельные entries с явной формулой расчёта наблюдаемого значения (какой XIRR брать, как агрегировать), иначе ретро-аудит будет смотреть на другую метрику.
    - **R7-петля (IV-B):** катализаторы из §10 с `auto_checkable: true` отслеживаются
      `forecast-monitor` — монитор читает `weekly-review-stock-*.yaml` и проверяет через
      `web_search`, сработал ли катализатор к `check_date`. Для этого в YAML катализатора
      должны быть указаны поля `auto_checkable: true` и `check_what` (наблюдаемый исход).

11. **Trust matrix awareness.** Матч идёт по структурному тегу `catalyst.source_trust: {analyst, subdomain}`, который проставляет производитель (`ru-portfolio-advisor`, R11): если trust matrix говорит IGNORE для этой пары — catalyst игнорируется в joint expectation (но виден в таблице с пометкой). Катализатор **без тега не дисконтируется** — обзоры до 2026-08-16 поля не несут; их доля лежит в `validation.trust_coverage`.
    > ⚠ До 2026-08-16 сравнивался прозаический `catalyst.source` (URL или фраза) с тегами матрицы — совпасть не могло никогда, и правило не срабатывало ни разу за всё время (прогон 08-15: 28 IGNORE-записей против 105 катализаторов, отфильтровано 0). Поэтому **отсутствие пометок IGNORE само по себе ничего не доказывает**: сперва посмотреть `trust_coverage.tagged`. При нуле §9 обязан написать «фильтрация по доверию не работала», а не «низкодоверенных источников нет».

12. **Output на русском, технический стиль.** Структурированные таблицы и compact prose. Минимум воды.
    - Заголовки секций, заголовки колонок таблиц, текст — на русском.
    - Английские термины допустимы только как устоявшийся инвестиционный стандарт: XIRR, YTM, CI, α, BUY/HOLD/SELL, ИИС-3 (аббревиатура). При первом упоминании нестандартного английского термина — расшифровка.
    - **Никогда не выводить имена YAML-полей** (`expected_pct_pweighted`, `factor_betas_r2`, `weight_real_pct`, `regression_mode` и т.п.) — вместо них человеческие описания.
    - **Никогда не выводить verdict-коды** (`IDIOSYNCRATIC_DOMINATES`, `MIXED`, `priors-only`) — вместо них: «доминирует идиосинкр. компонента», «смешанный», «только приоры».
    - ID катализаторов и предсказаний сохраняются для трассируемости, но **всегда** сопровождаются человеческим названием: «снижение ставки → рост ипотечного рынка (`rate_cut_mortgage`)».

---

## Workflow

### Шаг 0. Транспорт

Прочитать `references/transport-layer.md` (пути, проверка доступности Synology mount).

### Шаг 1. Validate inputs

Найти и загрузить три последних артефакта (или указанные пользователем). Проверить:
- `schema_version` каждого
- staleness vs пороги
- cross-reference: все `macro_dependency` из review должны резолвиться в `stress.scenarios`
- **Stale-pipeline gate (R-PIPE):** агрегатно посчитать долю unresolved `macro_dependency`. Если `unresolved_count / total_catalysts_with_dependency > 0.3` — **отказаться от синтеза** (это не точечный warning, а методологическая устарелость review относительно текущего scenario layer). Сообщение должно перечислить, какие сценарные ID отсутствуют, и предложить либо запустить `RECALIBRATE-mode` через `macro-forecast-chain` на active forecasts, либо обновить weekly-review через `ru-portfolio-advisor`. Причина: per-catalyst discount=0.7 корректен для одиночного unresolved (Rule 5), но при массовой rasstroyka сценарных ID он маскирует тот факт, что весь review был построен на устаревшем макро-каркасе.
- **Флаги качества снапшота (R-DQF):** `aggregate_positions.py` кладёт в `validation.snapshot_quality_flags` все записи `data_quality_flags` снапшота, кроме `info`/`debug`. **Перечислить их в §0 целиком** и указать, на какие разделы они влияют. Фраза «нарушений нет» допустима только при пустом списке: это утверждение о данных, а не о собственных проверках обзора. Прецедент 2026-08-04 — `iis_split_position` и `ie_model_total_mismatch` (сумма целей IE-модели 93%, а не 100%) не доехали никуда, §0 писал «нарушений нет», §5 считал отклонения от неполной модели.
- **Snapshot drift check (R-SNAP):** сравнить дату snapshot, использованного в stress, с `snapshot_id` в review. Если разница > 3 дней — добавить warning СРЕДНЕЙ серьёзности в §0. Веса позиций для §3 и §4 **всегда** брать из stress (`per_position.weight_pct`, total-portfolio basis). Веса из review (`weight_real_pct`) — это % от sub-bucket (стоки/облигации внутри своего обзора), их **запрещено** мешать с stress-весами в портфельных агрегатах.

Детали и pseudocode — `references/synthesizer-workflow.md` Шаги 1–2.

### Шаг 1.5. Нормировка вероятностей сценариев (R-NORM)

Перед расчётами вычислить `S = Σ p_i` по всем сценариям стресс-теста.
Применять нормированные веса `p_i_norm = p_i / S` во всех дальнейших расчётах.
Если `|S − 1| > 0.02` — добавить warning в Раздел 0:
- `|S − 1| > 0.02` и ≤ 0.05 → НИЗКАЯ серьёзность (математическая неточность в стресс-тесте).
- `|S − 1| > 0.05` → СРЕДНЯЯ серьёзность (стресс-тест нуждается в пересмотре).
Детали — `references/synthesizer-workflow.md` Шаг 1.5.

### Шаг 2. Compute per-position aggregates

**Use `scripts/aggregate_positions.py` for all числовые расчёты.** LLM упаковывает payload (распарсенные snapshot/stress/review_stocks/review_bonds/trust_matrix **+ `fund_classification`** — секция из `sector-overrides.yaml` as-is) в JSON, скрипт возвращает per-position строки + portfolio aggregates + validation block (нормировка p_i, stale-pipeline gate, snapshot drift).

**Читать результат — `--summary`**, а не ad-hoc-скриптами в чате: `python3 scripts/aggregate_positions.py --input run.json --summary` печатает валидацию, портфель по горизонтам, полную доходность и tail-флаги. JSON остаётся источником истины для вьюера и §3. (Прогон 08-15 потратил 20+ команд на разглядывание JSON и трижды упал на `None` в весах заблокированных позиций и на вложенности `total_return_by_horizon`.) Поля payload, которые скилл обязан заполнить сам (снапшот их НЕ несёт):

| Ключ | Откуда брать | Что ломается при пропуске |
|---|---|---|
| `fund_classification` | секция `sector-overrides.yaml` as-is | все фонды уезжают в equity-бакет |
| `macro_marginal` | **`factors`-блок** `macro-chain/macro-marginal-{date}.yaml` (не файл целиком) | L1-overlay не считается; передавать только если L1 нужен |
| `snapshot.holdings[*].on_iis` | необязательно: скрипт выведет сам из `stress.per_position[t].on_iis` / `account` / `accounts_merged` | ничего — с 2026-08-16 метка ❄ и R10 держатся без этого поля (PIV-5b) |

Если `validation.stale_pipeline_gate == "FAIL"` — отказ от синтеза с сообщением из `validation.stale_pipeline_message`. Если гейт PASS, но `validation.idio_layer_unlinked == true` («0 неразрешённых из 0» при живых катализаторах) — синтез продолжается, а `stale_pipeline_message` обязан попасть в §0 и HIGH-оговоркой в §9. `validation.fund_unrouted` (фонды вне справочника → equity по умолчанию) и `validation.merged_duplicate_tickers` (позиции, схлопнутые с нескольких счетов) — перечислить в §0, если непусты.

**Три поля валидации против тихих отказов (PIV-5, прогон 08-15).** Каждое несёт готовое `message` — если оно непустое, текст обязан доехать до §0 и оговоркой в §9; молчание здесь означает, что артефакт утверждает не то, что посчитано:

| Поле | Когда сообщение непустое | Серьёзность оговорки |
|---|---|---|
| `validation.l1_overlay` | overlay передали, а он не применился ни на одной позиции (имена факторов не совпали с бетами/`baseline_spot`) — результат чистый L2 | ВЫСОКАЯ; писать «L1 подключён» **запрещено** |
| `validation.horizon_anchor_drift` | якоря горизонтов stress и weekly-review расходятся; несёт поимённый список катализаторов, учтённых на «не своём» горизонте | СРЕДНЯЯ; истина — stress |
| `validation.blindspot_coverage` | справочно: сколько позиций помечено 👁 и откуда сигнал (`from_position_flag` / `from_stress_table`) | — (для §3 и §9) |
| `validation.stress_recalc` | в payload положен пересчёт сайта: имя стресса скилла, дата суждений (`judgments_date`), снапшот и время пересчёта | — ; в строке источников §0 дописать «числа — пересчёт сайта от {at} на снапшоте {snapshot_id}», возраст считать по `judgments_date` |
| `validation.stress_terms_mismatch` | сроки сайта (`horizons_file`) не совпали со сроками стресса; несёт код `STRESS_TERMS_MISMATCH` | СРЕДНЯЯ; числа стресса не выдавать за действующие сроки |
| `validation.trust_coverage` | ни один катализатор не несёт `source_trust` → фильтр доверия не мог сработать; либо атрибутирована часть | ВЫСОКАЯ при нуле, СРЕДНЯЯ при частичной |

Метку 👁 в §3 ставить по `macro.blindspot` из результата — она уже сводит булев флаг позиции и вердикт таблицы `stress.macro_blindspots`. Руками сверять таблицу не нужно.

Для каждого ticker из snapshot.holdings (выполняется внутри скрипта):
- **Проверить ticker collision / is_blocked**: если `is_blocked = true` И `currency` не соответствует локализации тикера (признак смешения двух инструментов с одним тикером) — изолировать позицию: включить в таблицу с тегом `🔒 blocked` и методологической оговоркой, исключить из портфельных агрегатов equity vs bond.
- **Классификация фондов (маршрутизация по бакетам)**: SSOT — `sector-overrides.yaml` → секция `fund_classification`. Читать при старте (через transport-layer, рядом со снапшотом) и **передать в payload ключом `fund_classification` as-is** — маршрутизацию выполняет сам скрипт (PIV-4b): `cash_equivalent`/`gold` → вне equity/bond агрегатов, `bond_bucket` → bond, `equity_bucket` → equity; фонд вне справочника уходит в equity по умолчанию и попадает в `validation.fund_unrouted` — перечислить в §0 и предложить дозаполнить справочник. Если `sector-overrides.yaml` недоступен — fallback на предыдущий `integrated-view-*.md` с **warning MEDIUM** «fund_classification из предыдущего IV, актуальность не гарантирована». Реклассифицировать «вручную» по памяти запрещено. Дедуп позиций, разложенных по счетам (main + ИИС-3), тоже в скрипте (PIV-4c) — вручную схлопывать строки снапшота не нужно.
- **Cash обработка**: использовать `cash.liquid_rub = cash.total_rub + cash.cash_equiv_rub` как полную ликвидность. `cash.cash_equiv_tickers` — фонды денежного рынка (LQDT, TMON, TPAY и аналоги), которые пользователь относит к кешу. Если `cash.by_account.main = null` — показывать только `cash.by_account.iis_3` как достоверный остаток, `liquid_rub = iis_3_cash + cash_equiv_rub`. Поле `cash.by_currency.RUB` (derived from trades) выводить в виде «trade-flow ≈ X ₽» с пояснением, что это накопительная разница trade-log, не источник истины.
- macro component (из stress.per_position)
- dividend component (из review, нормализован к 20 мес)
- idiosyncratic α (joint P через macro_dependency, trust-matrix discount, source_quality discount)
- total = macro + div + idio с propagated CI

Детали — `references/synthesizer-workflow.md` Шаг 3 + `references/joint-expectation-rules.md`.

### Шаг 3. Compute portfolio-level aggregates

Equity-portfolio expected return, bond-portfolio expected return, spread с CI propagation. Annualization для honest comparison. Детали — `references/synthesizer-workflow.md` Шаг 4.

**Schema v2 (multiple horizons):** скрипт отдаёт `portfolio_by_horizon.{hNN}` — equity/bond/spread **на каждый горизонт**. Плоский `portfolio` = `primary_horizon` (совместимость). Equity-vs-bond сравнение (§2) и per-position таблица (§3) — **per-horizon** (по колонке на 12/20/36); вывод §2 (контекст, не вердикт) один, привязан к `primary_horizon`, и всегда идёт вместе с порогами переключения `spread_switch` (Шаг 3.7). Каждый горизонт несёт дату `horizon_ends[hNN]` — показывать её рядом с горизонтом.

### Шаг 3.5. Bond carry adjustment (Sc-aware)

При расчёте bond portfolio expected return:
- **Источник carry — приоритет (R-BOND-CARRY, обновлён 2026-07 total-return):**
  0. **Блок `bond_carry` в stress** (Слой 2, `compute_bond_carry.py`, §11.2) — ПРИОРИТЕТНЫЙ источник: carry = Σ p_norm × carry[s] из per-scenario ячеек (купоны по факт. расписанию + pull-to-par + реинвест тела по сценарной КС + FX); MC сэмплирует ячейку разыгранного сценария. У гасящихся бумаг stress несёт `price_delta_zeroed` — тело НЕ дублируется между слоями (валидатор E3 блокирует). Пункты 1–3 ниже — fallback для stress без блока.
  1. Если `weekly-review-bond` содержит `ytm_pct` для позиции → carry = `ytm_pct × eff_months/12`. Это основной источник (forward-looking yield на дату обзора).
  2. Иначе fallback на `holdings[i].xirr` из snapshot → carry = `xirr × eff_months/12` (historical proxy, использовать только если bond review отсутствует или не покрывает позицию).
  3. Если ни того, ни другого — `div_yield_12m_pct` из stocks-review (для гибридов типа REIT). Для чистых облигаций без `ytm_pct` и `xirr` — carry=0 + warning HIGH.
  Критично: bond review **не использует** `div_yield_12m_pct` (там этого поля нет), поэтому стандартный stocks-флоу `Шаг 3` для облигаций не работает; carry для облигаций считается отдельно по этому правилу.
  - **Capping горизонта (put/offer):** `eff_months = min(h, месяцев до ближайшей `offer_date`/`maturity_date`)` для каждого горизонта `h` (v2: 12/20/36) — после оферты/погашения бумага гасится, carry за пределами не начисляется. Поэтому на длинных горизонтах carry put-облигации «упирается» в оферту и перестаёт расти.
  - **Санити-базис ytm:** если `ytm_pct` неправдоподобен (>60% — почти наверняка yield-to-offer, а не YTM-к-погашению) → базис переключается на `coupon_pct`. Экономику самой оферты несёт catalyst `offer_exit`, а не carry.
  - **Backstop-клампа:** итоговый `|carry| ≤ 50 пп` (`source` получает суффикс `_capped`). Защита от любых аномалий в upstream-данных.
- **Асимметричный CI**: при базовом сценарии cutting-rate (когда доминирует сценарий со снижением ставки) расширить нижнюю границу CI на 1–2 pp относительно симметричного ±15% (rolldown в более низкие купоны). Явно указать в Разделе 4: «точечная оценка — forward YTM из bond-review (или исторический XIRR); в сценарии снижения ставки forward carry может быть ниже на 1–2 пп».

### Шаг 3.6. Total return (три слоя) и дивидендный слой

- **Слой 3 (дивиденды):** `aggregate_positions.py` предпочитает `per_stock.dividend_forward`
  (гейт policy_state, проекция год1/год2, год 3+ = carry_forward с флагом) полю
  `div_yield_12m_pct` (fallback для v1-review). `uncertain` → 0 + флаг
  `dividend_missing_policy_unknown` — в артефакте ОБЯЗАН читаться как «доход не учтён
  (политика неизвестна)», не как «дивы = 0».
- **`total_return_by_horizon`** (в результате скрипта): price + carry + dividend по
  сценариям и бакетам equity/bond/cash + портфель целиком (стоимостной базис снапшота,
  задокументирован в `weights_basis`). Идиосинкратика в сценарную декомпозицию НЕ входит
  (METH-1 остаётся в per_position) — копировать note блока. Дивидендный haircut в
  сценариях `sanctions ≥ 1` — параметр `payload.div_sanctions_haircut` (default 0.25,
  `null` выключает); при срабатывании — явная строка в §4.
- Показывать **раздельно И суммой**: три полосы уверенности (carry — контрактная,
  дивиденды — репортная, цена — priors) из `layers` — не схлопывать в одно число.

### Шаг 3.7. Пороги переключения спреда (`spread_switch`)

Веса сценариев ставятся руками, поэтому точка спреда «акции − облигации» сама по себе
выдаёт ложную точность. Скрипт считает (`compute_spread_switch_thresholds`), при каком
весе **одного** сценария знак спреда меняется (остальные делят остаток в текущих
пропорциях; модель та же, что у PSS-6 `reweight_stress.py`). База — `total_return_by_horizon`
без идиосинкратики, поэтому `spread_now_pp` ≠ headline-спред; порог по точке, не по CI.
В §2 таблица порогов **обязательна** (шаблон §2 «Когда вывод переворачивается»), числа
as-is; `--summary` печатает её для основного горизонта.

### Шаг 4. Build output

Сгенерировать `integrated-view-{date}.md` по шаблону из `references/output-template.md`. 10 секций в 3 тирах (skip с reason если данных нет). Frontmatter включает `schema_version: "integrated-view@1.4"` (поля `tiers`, `tail_flags`, `portfolio_by_horizon`, `total_return`).

**Единый канон центрального значения ноги (@1.4 — фикс двойного центра):**
`portfolio_by_horizon.<h>.{equity,bond}.value`, `spread.value` и CI строятся от
**одной модели** — MC-совместимого центра (Layer 2 p-weighted price + income +
idio; ровно эти слои сэмплирует Monte Carlo). Систематический рассинхрон
«центр из одной модели, CI из другой» исключён; строгое «центр внутри CI» при
этом не теорема — у редкого бинарного катализатора (p < 2.5%) p-взвешенная
точка может выйти за перцентили бимодального распределения, такие случаи ловит
`mc_divergence`. До @1.4 L1-overlay подменял macro-центр аналитической точкой →
headline bond m12 35.2 оказывался ВНЕ своего CI [24.8, 32.3], а spread считался
от одного семейства, CI — от другого. Теперь L1-точка НЕ выброшена, а вынесена
в отдельное информационное поле **`l1_point`** (per-bucket и в frontmatter) —
альтернативная аналитическая оценка (marginal-прогнозы × беты), не участвующая
в headline/spread/CI; разрыв виден как coherence gap в §3. Соотношение с
`total_return.expected`: headline = expected + идио-слой (METH-1: идио в
headline есть, в сценарную декомпозицию total_return сознательно не входит)
**+ эффект дивидендного haircut**, если он сработал (санкционные сценарии:
expected учитывает haircut per-scenario, headline-доход — нет; на данных
2026-07-02 это ~0.3 пп на equity-ноге).

**Контракт стабильности графиков (@1.4 — ОБЯЗАТЕЛЬНО):** скопировать
`result["frontmatter_portfolio_by_horizon"]` → frontmatter-ключ `portfolio_by_horizon`
и `result["frontmatter_total_return"]` → `total_return` **as-is, без переформатирования
чисел**. Вьюер ≥2.6.0 читает эти блоки первым; прозаический §4 остаётся для человека.
Ручная вёрстка чисел в frontmatter запрещена — «плавающий» вывод ломал графики.
Контракт enforced: `save-to-library` (Workflow G2.1) гоняет
`validate-integrated-view` и **отказывает в записи** при строках вместо чисел,
незакавыченных датах, расхождении ключей-горизонтов или v1-полях горизонта.

**Tail-risk флаги (@1.2).** `aggregate_positions.py` возвращает `result["tail_flags"]` — детерминированный пост-процессинг поверх уже посчитанных CI (никакой ручной арифметики). Три ортогональных флага, каждый маршрутизирует к **разному** действию:

- **`БИНАРНЫЙ`** (`binary_skew`) — скос точки `> 2.0` (длинное плечо CI ≥ 2× короткого): точка неинформативна (схлопнутый бимодальный payoff). Ставит ⚡ к строке §3 (автоматизация прежней ручной конвенции).
- **`ЗНАК НЕ РАЗРЕШЁН`** (`sign_unresolved`) — `lo < 0 < hi` на позиции с весом ≥ 2.0%: знак доходности не разрешён интервалом. Severity HIGH → поднимать в §9 ВЫСОКАЯ.
- **`ХВОСТ ПОРТФЕЛЯ`** (`portfolio_tail`) — позиция вносит > 15% в нижний хвост портфеля (только при `Σ contrib_down ≥ 3.0` пп·доля, cap top-3): сюда смотреть для сужения хвоста.

Скопировать `tail_flags` as-is в frontmatter артефакта; отрендерить под-блок «Tail-risk флаги» в §9 (или «не сработало», если `fired == false` — молчание = информация). Пороги — параметры скрипта (`payload.tail_thresholds`), не хардкод.

⚠️ **Принципиальная оговорка (R1):** флаги — **эвристические указатели внимания, НЕ VaR**. CI в этом скилле — методологическая полоса (corr=1 линейная / corr=0 квадратурная), а не подогнанное распределение. Не формализовать «хвост» в tail-метрику с мнимой точностью.

Теги позиций в master-table (§3):
- `🟢 agree` — стресс и обзор согласны на HOLD/HOLD.
- `🔴 disagree` — стресс и обзор расходятся ИЛИ обзор даёт BUY/SELL при нейтральном макро.
- `👁 blindspot` — `macro_blindspot = true` в стресс-тесте (доминирует idio α).
- `⚠ HIGH` — `verification_priority = HIGH`, нужна сверка с первоисточником ДО действия.
- `🔒 blocked` — ticker collision или `is_blocked = true` с признаками смешения инструментов; позиция исключена из агрегатов.

Один тикер может нести несколько тегов (например, `⚠ HIGH 🔴 disagree 👁 blindspot`).

**§2 — macro-context, НЕ вердикт.**

⚠️ §2 — это **macro-only spread** (equity vs bond bucket по stress per_position при текущих сценарных весах). Это **не decision frame**: не утверждать «облигации впереди» как готовый вывод, не давать рекомендации «нарастить bonds», не использовать spread как trigger без cross-reference с tactical-rebalance. Decision frame — парный `tactical-rebalance-{date}.md` (Mode 3) или per-position verdicts в `weekly-review-{stock|bond}-{date}.md`.

Текст §2 ОБЯЗАН содержать: (1) явную пометку «это не decision frame», (2) точечный spread + оба CI (corr=0 и corr=1) без выбора одного как «истинного», (3) при `scenario_weights_calibrated=false` — HIGH-caveat про Pure Shell defaults, (4) при наличии парного tactical-rebalance и расхождении его per-position TR от macro-spread > 3 пп — note о расхождении с явным пояснением, что tactical = decision frame.

См. `references/output-template.md` §2.

**§1 — таблица HIGH-priority позиций (verdict-pointers + verification).**

⚠️ Это **НЕ** action queue. Synthesizer не генерирует свои buy/sell сигналы и не цитирует конкретные action items из обзоров (см. Rule 6). §1 показывает: позиции, требующие внимания, с указателем на источник вердикта и списком того, что нужно проверить ДО действия.

Строго 5 колонок в следующем порядке (структура заморожена для совместимости с viewer'ом):

| Тикер | Доля | Verdict-pointer | Ожид. за 20 мес | Что проверить |
|---|---|---|---|---|

- Колонка 0: тикер (для облигаций — `ISIN / short_name`, например `RU000A106E90 / ОФЗ 78729`)
- Колонка 1: доля в портфеле, %
- Колонка 2: **verdict-pointer** — verdict-код источника как ярлык навигации: `BUY` / `ADD` / `TRIM` / `HOLD` / `SELL` без собственной интерпретации. Никакого собственного вердикта.
- Колонка 3: ожидаемая доходность за 20 мес с CI: `+30.4% [+5; +52]`
- Колонка 4: **verification check** — что нужно проверить ДО любого действия по источнику: «дивполитика CHMF», «free-float после buyback», «cap rate банка vs ставка ЦБ». **НЕ** «лимитная заявка», **НЕ** ценовой уровень, **НЕ** размер лота — это action items, которые остаются в weekly-review.

Viewer читает r[2] как verdict-pointer и r[4] как verification-check. Структуру (число и порядок колонок) менять нельзя без bump версии viewer; семантика колонок 2 и 4 уточнена в этой ревизии — генерация артефакта должна следовать новой семантике.

### Шаг 5. Self-checklist

Перед выдачей — пройти acceptance checklist (см. ниже). Если хотя бы один пункт не выполнен — fix или явный disclaimer.

### Шаг 6. Черновик в `_drafts/` + выжимка в чат (D3)

Скилл **не пишет** в библиотеку сам. Полный `integrated-view-{date}.md` (после Шага 5) запиши через `Write` на mount
(`references/transport-layer.md`) в `{LOCAL_LIBRARY_ROOT}/_drafts/integrated-view-{date}.md` — то же имя получит
файл в `Portfolio/integrated-views/`. Запись — до вывода в чат. В чат — только выжимка:
1. §2 акции vs облигации по каждому горизонту (центр, CI, спред, ★ основной) и HIGH-caveats;
2. joint expectation портфеля по горизонтам (центр и CI полной доходности);
3. что сменилось против прошлого вида — 3–5 строк (блок «Что изменилось»; без `--diff-with-previous` — сравнить с
   последним `integrated-view-*.md` по §2 и `tail_flags`; прошлого вида нет — так и сказать);
4. сработавшие `tail_flags`;
5. строка «черновик: `_drafts/integrated-view-{date}.md` — сохранить: `save-to-library`».

Mount недоступен — полный вид в чат и фраза «черновик не записан». Владелец просит «выведи полностью» — полный вид
дополнительно печатается в чат. Флаг `--save-to-library` или явная просьба сохранить — предложить запуск `save-to-library`.

---

## Edge cases

| Edge case | Handling |
|---|---|
| Snapshot без `ie_model` (старая v1.x) | Schema fail-fast |
| Stress без `per_position` | Fallback на `sector_breakdown`, warning HIGH |
| Review с unresolved `macro_dependency` | Warning + use `discount=0.7` instead of `scenario.p` |
| Position в snapshot, нет в review | Включить в таблицу с `verdict: NOT REVIEWED`, `verification_priority: HIGH` |
| Position в review, нет в snapshot | Skip + warning «position not in current snapshot» |
| Все три файла >30d | Refuse to generate, попроси обновить pipeline |
| Один свежий, два устаревшие | Generate с heavy warnings в начале |
| HIGH-priority section пустая | Skip §1, написать «Все позиции в HOLD по обзору» |
| ИИС-3 balance = 0 | Skip §6 |
| `catalyst.source_trust` попадает в IGNORE-пару матрицы | Skip catalyst в joint, показать в §3 с пометкой trust=IGNORE |
| `catalyst.source_trust` отсутствует (обзор до 2026-08-16) | Катализатор считается как есть, фильтр не применяется; сообщить в §0/§9 из `validation.trust_coverage` |
| `is_blocked=true` + currency mismatch | Добавить тег 🔒, исключить из агрегатов §4, оставить в §3 |
| `cash.by_account.main = null` | Показать trade-flow с пояснением, не как итог; `liquid_rub = iis_3_cash + cash_equiv_rub` |
| `cash.cash_equiv_tickers` пуст | `liquid_rub = cash.total_rub`; строку Cash-эквивалентов не показывать |
| Σ p_i ≠ 1 | Нормировать через p_norm = p_i / S; warning в §0 если |S−1| > 0.02 |
| Snapshot drift между stress и review > 3д | Warning СРЕДНЕЙ в §0 («stress на portfolio-{date1}, review на portfolio-{date2}, разница {N}д»). Веса для §3/§4 — всегда из stress, review-веса в портфельные агрегаты не пускать |
| `unresolved macro_dependency / total > 0.3` | Stale-pipeline gate: отказ от синтеза, перечислить отсутствующие scenario IDs, предложить RECALIBRATE-mode или обновление weekly-review |
| `validation.snapshot_quality_flags` непуст | Перечислить все флаги в §0 (`код — сообщение` + затронутые разделы). «Нарушений нет» писать запрещено (R-DQF) |
| Бумага разложена по счетам (main + iis_3) | Стресс уже схлопнул ноги: `weight_pct` — полная позиция, `on_iis: true`. Руками не пересобирать и не делить обратно |
| Облигация без `ytm_pct` в bond-review | Fallback на `holdings[i].xirr` из snapshot; если и его нет — carry=0 + warning HIGH |
| `tail_flags.fired == false` | §9 под-блок = одна строка «ни один флаг не сработал; хвост диверсифицирован». ⚡ в §3 не ставить. Это корректный результат, не пропуск |
| `Σ contrib_down < 3.0` (пп·доля) | Флаг 3 «ХВОСТ ПОРТФЕЛЯ» не показывать вовсе (хвост портфеля незначим — anti-fatigue floor) |
| Позиция без CI (`total.ci = [null, null]`) | Пропускается во всех tail-флагах без падения; не входит в `portfolio_downside` |

---

## Anti-patterns (НЕ делай так)

1. **«Я думаю, что …»** — синтезатор не имеет своего мнения.
2. **«Рекомендую купить X / продать Y»** — нарушение rule 6.
3. **«CI ширина не существенна»** — нарушение R1. CI = honesty.
4. **Скрыть caveats в подвале мелким шрифтом** — high-severity caveats идут в начало.
5. **«Stress и review согласны, поэтому действуй»** — синтезатор не выдаёт actions.
6. **Подменить Section 9 («What is NOT shown») формальной фразой** — это критический раздел.
7. **«Продай SBER на ИИС-3»** — нарушение R10. Никогда.
8. **Сгенерировать integrated-view на устаревших данных без warnings** — нарушение rule 3.
9. **Принять unresolved macro_dependency как catalyst valid** — нарушение rule 5.
10. **«Игнорируй CI, точечный estimate достаточно»** — phantom precision (R1).
11. **«Скопировать имя YAML-поля или verdict-кода прямо в текст»** — нарушение rule 12. Читатель не должен знать структуру внутренних схем: `expected_pct_pweighted` → «взвешенное по сценариям ожидание», `IDIOSYNCRATIC_DOMINATES` → «доминирует идиосинкр. компонента», `factor_betas_r2=null` → «бета-коэффициенты построены на приорах без МОЕХ-регрессии».

---

## Output options

**Default:** полный вид — черновик `_drafts/integrated-view-{date}.md`, в чат — выжимка (Шаг 6). Пользователь может запустить `save-to-library` отдельно.

**`--save-to-library` flag:** автоматически предлагает запустить `save-to-library` после генерации (в библиотеку скилл не пишет сам — D3; черновик в `_drafts/` — служебная зона).

**`--diff-with-previous` flag (v1.1):** найти предыдущий `integrated-view-*.md` и добавить блок «Что изменилось» в начале.

---

## Self-checklist (запускать перед выдачей)

**Корректность (приоритет 0):**
- [ ] Вероятности сценариев нормированы (S = Σ p_i; применяется p_i_norm = p_i / S); warning если |S − 1| > 0.02
- [ ] Stale-pipeline gate пройден: доля unresolved `macro_dependency` ≤ 0.3 (иначе отказ, не синтез на discount=0.7)
- [ ] Snapshot drift между stress и review проверен; веса в §3/§4 взяты из stress (не из review weight_real_pct)
- [ ] Bond carry: для облигаций carry = `ytm_pct × eff_months/12` из bond-review (fallback на `xirr`); горизонт capped до оферты/погашения; при неправдоподобном `ytm_pct` (>60%) базис → `coupon_pct`; backstop `|carry|≤50`; НЕ через `div_yield_12m_pct`
- [ ] Ticker collision / is_blocked позиции изолированы с тегом 🔒, исключены из агрегатов
- [ ] Cash: использован `liquid_rub = total_rub + cash_equiv_rub`; если `cash.by_account.main = null` — только ИИС-3 cash достоверен; trade-flow RUB подписан как «накопительная разница trade-log»
- [ ] Bond carry CI асимметричен при доминирующем cutting-rate сценарии
- [ ] CI портфельных агрегатов: при `ci_method: mc` в основных таблицах §2/§4 — точка + MC CI (joint); полоса corr=0…1 — только в свёртке (U2). При `analytic` — оба CI (linear/quadratic) как раньше
- [ ] Прогнозы в predictions_for_review имеют check_date = конец соответствующего горизонта (`horizon_ends`)
- [ ] Schema versions cross-validated
- [ ] Stale warnings присутствуют, если данные устарели
- [ ] **Frontmatter v2 (Фаза 4):** `horizons`/`horizon_ends`/`primary_horizon`/`ci_method` присутствуют; legacy `horizon_months`/`horizon_end` НЕ записаны
- [ ] **`inputs.*_age_days` — явными полями**, не YAML-комментариями (U4; иначе вьюер показывает «возраст: —д»)
- [ ] **Сверка базисов долей** (holdings / стресс-база / акционная часть) — таблица в шапке отчёта (U1)
- [ ] Под каждой таблицей с тегами — компактная легенда-строка (U6); «спред» — только акции−облигации (U5)
- [ ] `tail_flags` вычислены (из `aggregate_positions.py`); §9 содержит под-блок «Tail-risk флаги» (или явное «не сработало»); ⚡ у строк §3 проставлены только для Флага `БИНАРНЫЙ`; Флаг 2 поднят в §9 ВЫСОКАЯ

**Читабельность (приоритет 1):**
- [ ] Все 10 секций в 3-тирной структуре (или explicit skip с причиной)
- [ ] Каждое числовое предсказание имеет CI
- [ ] Позиции в master-table (§3) размечены тегами: 🟢 agree / 🔴 disagree / 👁 blindspot / ⚠ HIGH / 🔒 blocked
- [ ] HIGH-priority действия вынесены в §1
- [ ] ИИС-3 позиции помечены ❄ и не имеют SELL/TRIM verdict
- [ ] §9 содержит раздел «Что не показано» с конкретными ссылками на исходники
- [ ] Блок предсказаний содержит ≥ 5 проверяемых предсказаний с датами; каждое — ID + человеческое название
- [ ] Caveats разделены на ВЫСОКАЯ / СРЕДНЯЯ / НИЗКАЯ серьёзность
- [ ] Источники указаны в §10 (с возрастом каждого)
- [ ] В тексте нет имён YAML-полей (`expected_pct_pweighted`, `IDIOSYNCRATIC_DOMINATES` и т.п.)
- [ ] Маркеры происхождения caveats: «этот отчёт» / «стресс-тест» / «еженедельный обзор»
- [ ] Катализаторы в §3/§4 указаны полным именем, ID в скобках
- [ ] Заголовки таблиц и секций — на русском

---

## References

- `references/synthesizer-workflow.md` — детальный workflow с pseudocode (Шаги 1–4)
- `references/joint-expectation-rules.md` — R1 (CI propagation) и R4 (joint P через macro_dependency)
- `references/output-template.md` — полный шаблон markdown-артефакта (10 секций в 3 тирах; output schema `integrated-view@1.2`, блок `tail_flags`)
- `references/predictions-for-review-spec.md` — формат R7 блока

## Scripts

- `scripts/aggregate_positions.py` — детерминированный per-position aggregator: нормировка p_i, stale-pipeline gate (R-PIPE), snapshot drift check (R-SNAP), bond carry priority (R-BOND-CARRY), joint expectation, trust-matrix discount, equity/bond aggregates с двойным CI, **tail-risk флаги (@1.2)** (БИНАРНЫЙ скос / ЗНАК НЕ РАЗРЕШЁН / ХВОСТ ПОРТФЕЛЯ + anti-fatigue floor и cap top-3; эвристика внимания, **не VaR**). LLM упаковывает payload и читает результат; никакой ручной арифметики в чате.

---

## Versioning

- v1.0 — исходный SKILL.md
- v1.1 — нормировка p_i, двойной CI (линейный + квадратурный), 3-тирная структура output, теги позиций, ticker collision handling, cash null fallback, исправление predictions_for_review дат; schema output `integrated-view@1.1`
- v1.2 — `scripts/aggregate_positions.py` (детерминированная per-position aggregation), R-PIPE (stale-pipeline gate ≥30% unresolved), R-SNAP (snapshot drift check, веса всегда из stress), R-BOND-CARRY (приоритет ytm_pct → xirr → 0)
- v1.3 — **tail-risk флаги** в `aggregate_positions.py` (`compute_tail_flags`): три ортогональных флага (БИНАРНЫЙ скос / ЗНАК НЕ РАЗРЕШЁН / ХВОСТ ПОРТФЕЛЯ) с anti-fatigue (materiality floor + cap top-3), параметризуемые пороги. **Output schema `integrated-view@1.1 → @1.2`** (новое поле `tail_flags` в frontmatter, ⚡-сноска §3 автоматизирована, под-блок §9). Viewer bump `1.7 → 1.8` (рендер `tail_flags`, backward-compat с @1.1). Флаги — эвристика внимания, **не VaR** (R1)
- v1.4 — **total return (2026-07)**: Слой 2 `bond_carry`-блок stress приоритетнее legacy R-BOND-CARRY (per-scenario ячейки + MC-сэмплинг по разыгранному сценарию), Слой 3 `dividend_forward` вытесняет `div_yield_12m_pct`, `total_return_by_horizon` (equity/bond/cash + портфель, сценарная декомпозиция без идио, дивидендный haircut при sanctions≥1), frontmatter-контракт вьюера (`portfolio_by_horizon` + `total_return` эмитятся скриптом, LLM копирует as-is). **Output schema `@1.2 → @1.3`**, viewer bump `2.5.0 → 2.6.0`
- v1.5 — **единый канон центра ноги (2026-07, фикс двойного центрального значения)**: L1-overlay больше НЕ подменяет `macro.value` — канон всегда Layer 2 p-weighted (MC-совместимый: headline/spread/CI из одной модели, value лежит внутри собственного MC-CI; до фикса bond m12 = 35.2 при CI [24.8, 32.3] и spread от другого семейства). L1-точка вынесена в `macro.l1_point` → per-bucket `portfolio_by_horizon.*.l1_point` → frontmatter `{equity,bond}.l1_point` (информационная, «не входит в headline/spread/CI»); `mc_divergence`-warning перестал срабатывать каждый прогон. headline = `total_return.expected` + идио-слой (METH-1) + эффект див-haircut в санкционных сценариях. **Output schema `@1.3 → @1.4`** (additive: только новое поле `l1_point`)
- v1.6 — **пороги переключения спреда (2026-10-07, шаг 4 разбора «ИИ в инвестициях»)**: `result["spread_switch"]` — при каком весе одного сценария знак спреда «акции − облигации» меняется; §2 обязан показывать таблицу порогов вместо прежней оговорки «sensitivity по p(s) вне отчёта». Строго аддитивно: ни одно число не изменилось (golden — +1 блок); frontmatter и вьюер не затронуты
- v1.x — additive (новые опциональные sections, diff-with-previous)
- v2.x — breaking (multiple horizons, full covariance, Monte Carlo)

Roadmap расширений — `TODO.md` в скилле.
