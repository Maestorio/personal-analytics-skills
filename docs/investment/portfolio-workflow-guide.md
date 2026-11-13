# Портфельный пайплайн: что, в какой последовательности и зачем

**Технический навигатор** (для разработчика — читать перед правками) по
портфельным скиллам и вьюеру `tools/portfolio-integrated-viewer.html`. Отвечает на
вопросы: **какой скилл под какой вопрос**, **что от чего зависит**, **почему режимы
могут расходиться** и **какое поле вьюера откуда берётся**. Лежит на уровне
`README.md`/`TODO.md` как операционная точка входа.

> ⚠ **ПРАВИЛО СИНКА (жёсткое).** Этот документ — технический ракурс той же системы,
> что и **пользовательская справка `tools/assets/help/viewer/*.md`** (§5.7; правится в репо, на сервер — `deploy.zsh`; её
> рендерит кнопка «❓ Справка» во вьюере). **Меняешь операционную реальность —
> обнови ОБА файла:** здесь — технические детали (связи, провенанс полей, схемы),
> там — пользовательский «что гонять и в каком порядке». Правило закреплено в
> корневом `CLAUDE.md` (раздел «Синхронизация справки вьюера»).

> 🎨 **v2.5.0 — редизайн на дизайн-систему Claude Design (2026-07).** Вьюер переведён
> single-file → **multi-file**: `portfolio-integrated-viewer.html` (тонкий шелл) +
> `assets/viewer.css` (токены + компоненты + `@font-face` self-host Golos Text/Spectral) +
> `assets/viewer.js`. Отдаётся по HTTP (Caddy `/srv` = Synology `Claude-Memory`), не
> `file://`; cache-busting `?v=2.5.0` в шелле. Все 14 вкладок + 3 модалки на дизайн-системе.
> §4-герой Интеграционного — `verdict-grid` на чистом CSS/`errbar` **без Chart.js**
> (детерминированный рендер; при непарсящейся §4-прозе — info-fallback вместо ошибки).
> Дизайн-SSOT и контракт `portfolio_by_horizon` (корневой фикс «графики через раз» —
> апстрим `ru-portfolio-advisor`/`integrated-view`) — `tools/design-reference/`.

Связанные документы:
- Пользовательская справка вьюера — `tools/assets/help/viewer/*.md` (§5.7; зеркало, см. правило синка); читатель справки несёт «Поиск по справке» (ui-kit `uiReaderHTML({search})`, подсветка `mark.rd-hit`, Enter/↓/↑/Esc).
- Расчётные подходы — `docs/investment/portfolio/methodology.md` (METH-1 catalyst kinds, METH-2 gate).
- Архитектура прогнозов — `docs/investment/forecasting/conditional-forecasts-architecture.md`.
- Схемы v2 (multiple horizons + Monte Carlo) — `_shared-references/yaml-schemas.md` §11.
- Структура хранилища — `_shared-references/claude-memory-layout.md`.

---

## 1. Карта пайплайна

Данные идут слева направо. Каждый скилл читает артефакты предыдущих и кладёт
свой результат в `Claude-Memory/`.

```
[1] portfolio-data-loader ──► Portfolio/snapshots/portfolio-{date}.json
        │                       (qty, цены, XIRR/TWR, доли, ie_actual, cash)
        │                       пересборка за ту же дату → прежняя версия в snapshots/.versions/
        │
        ├─► [7] ru-portfolio-advisor  (8 режимов анализа — см. §2)
        │         режим 1 ──► weekly-review-stock-{date}.{yaml,md}
        │         режим 2 ──► weekly-review-bond-{date}.{yaml,md}
        │         режимы 3/4/5a/8 ──► отчёт + решения decisions/ (гейт — из решения) + forward-вердикт
        │
        └─► [6] portfolio-scenario-stress ──► Portfolio/stress/stress-{date}-{slug}.yaml
                  ▲                              (ΔP&L по позициям в 4 сценариях)
                  │
   [4] forecast-confidence-applier ──► forecasts/{slug}-{date}.{yaml,md}
        ▲           (Layer 1 marginal + Layer 2 by_scenario)
        │
   [3] macro-forecast-chain (оркестратор DAG, RECALIBRATE весов)
        ▲
   [5] scenario-builder ──► scenarios/{slug}-{date}.yaml  (SSOT весов сценариев)
   [2] macro-ru-watcher  ──► macro-snapshots/ru-{date}.md (7 индикаторов)

[8] portfolio-integrated-view  ◄── snapshot + stress + weekly-review
        └─► Portfolio/integrated-views/integrated-view-{date}.md
            (read-only синтез: per-position EV с Monte-Carlo CI на горизонтах
             6-12-24 мес side-by-side (primary 12 = «1 год»), equity vs bond)

[9] portfolio-coherence-audit  ◄── ВСЁ выше, включая сам integrated-view (мета-слой)
        └─► Portfolio/coherence-audits/coherence-audit-{date}.md
            (Stage P — Python bundle: generation-consistency gate, противоречия
             point-vs-конус, factor-overlap по ногам, joint_tail, diachronic,
             watch_verdict; Stage R — Fable 5: существенность + red-team вывода)
```

> **Schema v2 (Фаза 4, 2026-06-10).** weekly-review и stress подняты до
> `schema_version: 2`: горизонты — **набор `[6, 12, 24]`** (default, `primary 12`),
> а не один 20-мес. Producer'ы и consumer считают `by_horizon.{hNN}`; integrated-view
> заменил аналитический CI на **Monte Carlo** (общий розыгрыш сценария на path).
> Гибрид: скользящий (`--horizons`) и якорный на дату прогноза (`--anchor-dates`,
> `yaml-schemas.md` §11.6). Спека — `_shared-references/yaml-schemas.md` §11.
>
> **V2-CUTOVER (2026-08-03):** вся библиотека weekly-review/stress мигрирована в
> schema 2 (wrap-as-single-horizon, `migrate_v1_to_v2.py`; бэкапы
> `Portfolio/_bak-cutover-2026-08-03/`, 4 ранних эксперимента —
> `Portfolio/stress/_archive-pre-v2/`). Валидаторы save-to-library принимают
> **только** schema 2; v1-роутинг в консьюмерах — мёртвый остаток на снятие,
> не рабочий сценарий.

**Минимальный путь для еженедельной работы:** `[1] → [7] режим 1`.
**Полный путь для структурного решения:** `[1] → [2/3/4/5] → [6] → [7] режим 8 → [8]`.
**Месячный мета-аудит (или по watch_verdict):** `[8] → [9]` — Stage P гоняется дёшево
после любого цикла (скрипт без LLM, `fable_recommended` в stderr/bundle), Stage R —
только Fable 5. Все входы [9] обязаны быть с одной даты снапшота (HARD STOP, exit 2 —
строже, чем drift-warning [8]). Провенанс полей — `skills/portfolio-coherence-audit/README.md`;
промты — `EXAMPLES.md` там же; спека — `docs/investment/portfolio/portfolio-coherence-audit-spec.md`.

### 1.1 Как готовится макро-слой (stress)

Stress = **макро** integrated-view. Его готовит цепочка прогнозов:

```
[5] scenario-builder ──► scenarios/{slug}.yaml   ← SSOT весов 4 сценариев (Shell 2×2)
[2] macro-ru-watcher ──► ru-{date}.md            ← 7 индикаторов (ставка, инфляция, FX, Brent, RGBI, IMOEX)
[3] macro-forecast-chain                          ← оркестратор DAG; coverage-report (свежесть × покрытие
       │                                            горизонта: FRESH/AGING/STALE/FRESH-but-short); RECALIBRATE весов
       │                                            прогноз на заменённой матрице (`source_matrix` → файл с
       │                                            `superseded_by`) — STALE `MATRIX_REPLACED`, режим FULL;
       │                                            `check_macro_scenarios.py --root` не выпускает файл из прогнозов
       │                                            разных матриц. Вьюер: строка «матрица сценариев заменена» (4.4.6)
       ▼
[4] forecast-confidence-applier ──► forecasts/{slug}.yaml
       │   Layer 1 marginal (trust-weighted FCA, для EV) + Layer 2 by_scenario (4 когерентных бандла, для stress)
       ▼
[6] portfolio-scenario-stress ──► Portfolio/stress/stress-{date}-{slug}.yaml  (schema v2)
       betas (compute_per_position): priors (default) | moex (SS-1 — эмпирические OLS-беты на 24 мес MOEX/CBR)
       factors_by_horizon (compute_horizon_factors): per-year уровни FCA → % движения на h6/h12/h24 (MFC-4)
```

Ключевые механики, которые легко забыть:
- **Total return — три слоя (2026-07):** stress несёт ДВА слоя: `per_position.delta_*` (Слой 1, price-only; у облигаций с погашением/офертой внутри горизонта price_delta **обнулён** maturity guard'ом — `price_delta_zeroed`) и top-level блок `bond_carry` (Слой 2, `compute_bond_carry.py`: купоны по факт. расписанию + pull-to-par + реинвест тела по сценарной КС + FX; MM/кэш по КС−1пп). Слой 3 — `dividend_forward` в weekly-stocks-review (гейт policy_state, 2-летняя проекция). Суммирует только `portfolio-integrated-view` (`total_return_by_horizon`: equity/bond/cash + портфель по сценариям; идио — отдельным слоем). Валидатор E3 блокирует двойной счёт (`matures_within` × живой price_delta). `baseline_spot` в stress ОБЯЗАТЕЛЕН (уровень КС для carry + L1-overlay).
- **Пороги переключения спреда (2026-10-07):** `aggregate_positions.py` → `result["spread_switch"]` (`compute_spread_switch_thresholds`): по `total_return_by_horizon.by_scenario` (без идио) для каждого сценария — спред «акции − облигации» внутри сценария, текущий вес и вес `w_flip`, при котором знак портфельного спреда меняется (остальные сценарии делят остаток в текущих пропорциях; модель PSS-6 `reweight_stress.py`, замкнутая форма). Обязательная таблица §2 integrated-view; во frontmatter и вьюер не идёт. `spread_now_pp` ≠ headline-спред (там есть идио).
- **Frontmatter-контракт вьюера (@1.4):** `aggregate_positions.py` эмитит готовые блоки `frontmatter_portfolio_by_horizon`/`frontmatter_total_return` — копируются в frontmatter integrated-view as-is; вьюер ≥2.6.0 рисует графики из них детерминированно (скрейп прозы §4 — только fallback старых отчётов).
- **Единый канон центра ноги (@1.4, 2026-07):** `portfolio_by_horizon.*.{value,spread,ci}` — из ОДНОЙ модели (MC-совместимый центр: L2 p-weighted price + income + idio; центр и CI из одной модели — на практике value внутри CI, строгую гарантию перцентили не дают, редкие бинарные катализаторы ловит `mc_divergence`). Раньше L1-overlay подменял центр аналитической точкой (bond m12 35.2 вне CI [24.8, 32.3], spread от одного семейства, CI от другого). L1-точка теперь — отдельное информационное поле `l1_point` (per-bucket и в frontmatter), в headline/spread/CI не входит. headline = `total_return.expected` + идио-слой (METH-1) + эффект дивидендного haircut в санкционных сценариях (expected его учитывает, headline-доход — нет). Downstream (predictions_for_review, coherence-audit §3) читают канон из `value`.
- **Денежный поток облигаций:** снапшот несёт `bond_cashflow_calendar` (контрактные купоны/погашения на 12 мес; оферта — отдельно как пут) и `fx_rates_used` (курсы ЦБ только по валютам держимых бумаг, любым, что публикует ЦБ; валюта без курса — блок `fx_rates_missing`, не курс 1.0; живые цены — `quotes@1` с `fx=<валюты номинала держимых облигаций>`); замещайки без котировки получают implied-цену из стоимости позиции (`current_price_source: implied_from_value`). Вкладка «Облигации» рендерит календарь офлайн.
- **Одна цена MOEX во всех блоках (2026-10-27, PDL-15/16):** `build_snapshot.py` запускает `per_security_xirr.py --quotes quotes.json` после шага котировок — `per_instrument_xirr[*].market_value_rub` идёт по той же цене, что `holdings.current_price` (в ISS — только за бумагами вне файла). `portfolio_returns` запрашивает MOEX и по бумагам с ISIN `RU…`, купленным за валюту (юаневые облигации). Молчаливая оценка не по MOEX при живой котировке — error и блок записи: `returns_price_not_moex` (доходность портфеля и стоимость holdings без баланса; акции, фонды, облигации), `per_instrument_price_not_moex` (XIRR и результат по бумагам); расхождение цены блоков > 0,5 % — warning `per_instrument_value_mismatch`. Причина двух случаев (22.10, 27.10) — облачная среда Claude: MOEX ISS отвечает не на всё; на NAS сеть стабильна.
- **Тип бумаги с Мосбиржи (вьюер 3.84.0, 2026-10-28):** `scripts/security_types.py` (stdlib) — запрос `iss.moex.com/iss/securities/{secid}.json?iss.meta=off&iss.only=description` (`GROUP` → `stock_shares/dr/foreign_shares` = акция, `stock_bonds/eurobond` = облигация, `stock_etf/ppif` = фонд, прочее `other`; пустая description = бумаги на бирже нет → `type: null`, перепроверка раз в 90 дней; найденные не перепроверяются). Справочник `Portfolio/security-types.json` (`security-types@1.0`, атомарная запись). **Сеть — только сборка на сайте:** `build_snapshot.py` шагом `security_types` (через `Runner`, поэтому `--record` пишет запросы в `net/`) обновляет справочник ДО возвратов при `not --no-moex and not moex_down and not --replay`; скилл на Маке ходить в ISS не должен и читает справочник (`--types-cache`). **На сайте** (hub-notify) том Claude-Memory только на чтение — первая сборка 28.10 упала на записи справочника: теперь `pf_build.py` ведёт кеш в `/data/pf/security-types.json` (посев из `Portfolio/security-types.json`, если кеша ещё нет), передаёт `--types-cache`, а при «Сохранить» выкладывает справочник в `Portfolio/security-types.json` через hub-api (JOB_WHITELIST). Ошибка записи справочника больше не роняет шаг: `security_types.py refresh` печатает `errors`, все тикеры уходят в `failed`, флаг `types_step_failed` (warning). Порядок классификации: справочник (`portfolio_returns.set_type_overrides`, значения `stock|bond|fund`; `other`/`null` не перебивают) → эвристика `classify_instrument_type` (known_funds, FX/RSH, фьючерсы, купоны/дивиденды, ISIN). `--types-cache PATH` — у `portfolio_returns.py`, `per_security_xirr.py`, `iis_returns.py` (build_snapshot передаёт его всем трём); нет файла — без переопределений. После сборки `security_types.compare_types` (чистая функция) сверяет каждый холдинг: `snapshot.type_check = {cache, online, fetched, failed, changes[{ticker,name,was,now,moex,heur,reason}]}`, `reason` = `prev_vs_now` / `moex_vs_heuristic`; флаги `asset_type_changed` (warn, `ATTENTION_FLAGS`) и `moex_types_unavailable` (info, онлайн и сбой по всем тикерам); в `build-summary` — `type_changes` и `types {online, fetched, failed}`. Сборка не блокируется. Бумаги без сделок (баланс, перенос) сверяются по эвристике одного тикера (`known_funds`, FX/RSH, ISIN/ОФЗ-серия; дефолт «stock» и «other» — не эвристика). Подряд 5 сбоев ISS обрывают опрос (остальные тикеры — в `failed`). В пакете `--record` справочник после обновления кладётся в `security-types.json` пакета, `--replay` берёт его (сети нет, `online: false`, `type_check.cache = bundle:caches/security-types.json`). Вьюер: `pfTypesCard(b)` читает `brief.type_changes` / `brief.types` — **`pf_build.brief()` эти ключи пока не пробрасывает** (файл не менялся; без двух строк `"type_changes": summary.get("type_changes") or [], "types": summary.get("types")` и перезапуска `hub-notify` карточки на сайте не будет, флаг `asset_type_changed` виден в «Флагах загрузчика»). Пользовательская версия — `08-site.md` `{#site-build}` (зеркало, SYNC).
- **Позиции ИИС-3 без «Общего баланса» (решение владельца 2026-10-30):** позиции и количество счёта — по сделкам его выгрузки (`trades_portfolio_838526*.xlsx`: приложенная или последняя в `Portfolio/inputs/`; `assemble_snapshot._portfolio_from_trades`, основной счёт = выгрузка основного − ИИС-3); провенанс — `iis_positions_source: trades_export | balance | carried | none`, `balance_summary.carried` без `iis_positions`, когда позиции по сделкам. Баланс приложен — его позиции ИИС-3 только сверяются (`iis_returns_mismatch`). Выгрузки счёта нет — перенос из последнего снапшота с балансом (`carried`). Советник читает провенанс плана по `plan_check`, а не по `balance_carried_from` (`startup-checklist.md`).
- **`--commit` не ухудшает снапшот дня (2026-10-30):** `build_snapshot.commit_guarded` → `downgrade_refusal`: сборка «только сделки» (`is_trades_only`: `snapshot_type == trades_holdings` и `cash_reconciliation.current_drift_rub` пуст) поверх сохранённого `portfolio-<as_of>.json` с балансом или с внесённым кэшем — `StepError`, код 1, до архивации: ни снапшот, ни `.versions/` не меняются. Правило то же, что у «Сохранить» на сайте (`pf_build._is_trades_only` и `save`, 409 `balance`/`cash_fact`; `⚠ SYNC` в обоих файлах). С вьюера 3.122.1 `pf_build.brief()` отдаёт то же заранее: `trades_only` и `save_block` (`balance`/`cash_fact`/null; сохранённый — снапшот того же `as_of_date`), окно «Загрузок» не рисует зелёную плашку, блокирует «Сохранить» и ведёт к полю кэша; 409 сервера остаётся защитой. Проверки `plan_mismatch`/`numbers_stale` (`checks.py`, «план расходится с Numbers») окно показывает в «К сведению» как «Общий баланс отстаёт от плана на сайте по N полям»; уровень в загрузчике не менялся. `--allow-downgrade` — осознанная перезапись, прежняя версия в `.versions/`. Защита относится к `--commit --working` (журнал решений и индекс бумаги `build_snapshot.py` больше не запускает — шаг 15); `--commit` без `--working` кладёт снапшот скилла в пробную `Portfolio/snapshots/auto/portfolio-<дата>-<ЧЧММ>-skill.json` (+ `build-summary-…-skill.json`) и ничего больше не трогает: рабочим снапшотом штатно владеет сайт («Сохранить»). Корзина облигации из плана — пара (тип, подтип) целиком (`numbers_to_plan.apply_plan_primary`, trades_mode); бумага/фонд основного счёта с корзиной вне плана — warn `bond_bucket_not_in_plan` (`_build_bonds_plan_vs_fact`).
- **Проданные бумаги:** результат по акциям, облигациям и фондам обоих счетов — отдельный блок `per_instrument_xirr_closed` (`closed: true`, `close_date`, `holding_days`, разбивка потоков, `pnl_rub`, `xirr`); `per_instrument_xirr` остаётся «тем, что держу» (доли, сортировка по XIRR, `recent_*`). Строит только `build_snapshot.py` (второй прогон `per_security_xirr.py` по закрытым тикерам).
- **Кэш без «Общего баланса» (решение владельца 2026-10-27: Numbers уходит):** `snapshot_type: trades_holdings` — кэш основного счёта = реконструкция по сделкам + прошлое расхождение (оценка, `cash.source: trades_plus_prev_drift`) или факт, внесённый владельцем из IntelInvest (`--cash-fact RUB`, `cash.source: owner_intelinvest`, `cash_reconciliation` строится как у баланса: `actual` = total, drift = total − реконструкция; следующая сборка опирается на него). `cash.fact_date` — день последнего факта (баланс или внесённый кэш); оценка старше `CASH_FACT_MAX_AGE_DAYS` = 14 дн. → warning `cash_fact_stale` (решение build_snapshot: «пересобрать с --cash-fact»). `find_prev_snapshot` берёт trades-снапшот, только если у него есть `cash_reconciliation.current_drift_rub`. `balance_carried_from` — день баланса, а не prev. С балансом `--cash-fact` игнорируется (info `cash_fact_ignored`). `--cash-fact-iis RUB` (3.80.0; только рубли, `cash_fact_iis` в манифесте/теле `/api/pf/build`/статусе/журнале): подменяет перенос кэша ИИС-3, `cash.iis_source: owner_intelinvest`, `fact_date` = `as_of`; оценка основного счёта и `cash_fact_stale` не меняются (возраст — по прошлому факту). `brief.auto.cash_main_rub`/`cash_iis_rub` предзаполняют поля «Кеш после сборки».
- **`balance_summary.by_account` без «Общего баланса» (2026-10-30):** сборка из сделок считает его из holdings (`assemble_snapshot._by_account_from_holdings`), смысл полей как у баланса: `main.funds_rub` без TMON/TPAY/LQDT и FINAMAR, `main.cash_rub` — «грязный» остаток (кэш + денежные фонды + FINAMAR); `iis_3.funds_rub` — реальные фонды счёта (при балансе 0). Читают стабы советника (`build_weekly_*_stub.py`, `iis_shortlist.py`); со сверкой по эталонному дню все поля в пределах 0,2% (разница цен сборок), законное различие одно — `iis_3.funds_rub`.
- **Настоящий кэш и «Имеется» (фикс 2026-07-08):** строка «Имеется (RUB)» баланса = весь портфель **включая ИИС-3**, без заблокированных (инвариант файла: «Итого» = Имеется + Пополнение) → `total_current_rub_incl_iis` = Имеется, `excl_iis` = Имеется − ИИС. `cash.total_rub` = Имеется − все незаблокированные holdings (считает `assemble_snapshot._build_cash` по готовым holdings); `liquid_rub` = кэш + TMON/TPAY (`CASH_EQUIV_TICKERS`, без двойного счёта); FINAMAR — обычная fund-позиция, не кэш. `balance_summary.by_account.*.cash_rub` — «грязный» балансовый остаток (содержит TPAY/TMON/FINAMAR, которых нет во вкладках), для кэша не использовать. `cash_reconciliation.actual_cash_rub` = `cash.total_rub`; старые снапшоты несут baseline «~2,2 млн» — артефакт двойного счёта, первый перегон требует `--rebaseline-cash` (реальная дыра ~340 тыс.). **PDL-14 (19.08.2026):** гейт `balance_total_vs_trades_drift` сравнивает «Имеется» с реконструкцией на СВЕДЁННЫХ базах — `cash.total_rub` вместо реконструированного кэша (кассовую дыру мониторит `cash_drift_changed`, дважды её считать нельзя) плюс Σ НКД к чистым ценам MOEX (IntelInvest показывает грязную). **С 2026-10-12** `portfolio_returns` сам оценивает облигации грязной ценой (`returns.parameters.bond_value_basis: "dirty"`; НКД MOEX — в валюте торгов, у замещаек рублях) — гейт НКД второй раз не прибавляет; XIRR облигаций старых снапшотов (без поля) занижен, прямо не сравнивать. Порог 2% → **1%**, остаток на файле того же дня 0.42%. Срабатывание читать так: сначала дата сохранения Numbers-файла (устаревшие цены — главная ложная причина), потом поиск пропавшей позиции. SBGB (`metrics.iis_other_tickers`) → `account: iis_3`; TMON/XXXXXX classify → `fund`.
- **Отпечаток выгрузки сделок (2026-10-21):** `snapshot.trades_digest` — сырые строки выгрузки IntelInvest до `as_of`, сгруппированные (тикер, операция) → [строк, сумма, количество] (`scripts/trades_digest.py`, пишет `assemble_snapshot.py`). Читает только `checks.py` (`build_snapshot.py`): отпечаток прошлого снапшота против новой выгрузки на ту же дату → удаления, сделки и корректировки задним числом, поздние выплаты, вклад правок в кэш-дрейф. Сделка, датированная днём прошлого снапшота и пришедшая после его сборки (снапшот собран в свой день, по ячейке прошлая выгрузка равна строкам строго до этого дня), — не правка задним числом: одна info `trades_on_prev_snapshot_day`, а в проверках позиций её бумага считается сделкой после снапшота (`_same_day_cells`). Вьюер и советник поле не читают. Там же проверки ошибок данных IntelInvest: дробное количество облигации (блок), денежные автокорректировки, выплаты на больше бумаг, чем держали. Схема — `output-schema.md` → `trades_digest`.
- **Тексты проверок сборки (2026-11-11):** `checks.py` — `message_ru` по-русски: даты ДД.ММ (с годом, если не текущий), суммы «3 703,50 ₽». `payout_exceeds_holding` — `details.items[]` {ticker, name, date, operation, held, paid_qty, currency, kind, rows[{amount, qty, new}]}: вьюер рисует таблицу; `new` («новая с прошлой сборки») — по отпечатку прошлого снапшота (`_new_flags`: Δ строк/суммы/количества ячейки, строка входит в каждый подходящий набор; неоднозначно — `null`). `money_rows_changed_before_prev` — добавлено/удалено/изменено раздельно + строка про кэш из `cash_reconciliation` (прошлое расхождение — у прошлого снапшота, порог — `threshold_rub`; кэш-оценка `trades_plus_prev_drift` фактом не называется). `trades_changed_before_prev` — info, если все изменения — удаление строк бумаг и операций из `prev.build_suspects` (пишет `build_snapshot` после проверок), иначе warning. Бриф сайта (`pf_build.brief`) несёт `info_checks` (инфо о правках задним числом) — вьюер показывает их в «К сведению».
- **Доходность БКС-ИИС-3 (2026-10-12):** опциональный Шаг 4б data-loader — `iis_returns.py` по отдельной выгрузке IntelInvest этого счёта (`trades_portfolio_838526*.xlsx`: приложенная, иначе последняя из `Claude-Memory/Portfolio/inputs/<дата>/` — туда её кладёт импорт на сайте; с 2026-10-21 папки на Mac не ищутся) → `returns.by_account.iis_3`: `fact` (XIRR счёта), `forward` (IRR к погашению по сегодняшней цене; SBGB — прокси средневзвешенной YTM состава RGBI; кэш 0%), `locked` (зафиксированная при покупке). Финамовский ИИС-3 владелец ведёт как брокерский — `account: iis_3` в holdings = БКС. Выгрузка приходит только после покупки/продажи/взноса; купоны между выгрузками — синтетика по MOEX bondization, вытесняется реальными. Линкер (ОФЗ-ИН 156012) — индексация по Layer 1 `forecasts/inflation-ru-*.yaml`, нет → 4%; `*_real_pct` — без индексации. Сверка с балансом (позиции + кэш ИИС) → при расхождении `status: mismatch` и блок без чисел. Схема — `output-schema.md` → `returns.by_account.iis_3`. **Перенос (2026-10-13):** без `--iis-returns` `assemble_snapshot` переносит блок из последнего снапшота, где он есть (`--output` читается ДО перезаписи — файл того же дня, `--prev-snapshot`, `--snapshots-dir`), с `carried_from`/`carried_reason` и флагом `iis_returns_carried`; qty ИИС-3 по ISIN против holdings источника разошлись → warn `iis_composition_changed`, блок всё равно переносится (`_carry_iis_block`). В упакованном скилле `docs/investment/source/` нет — иначе блок пропадал. Вьюер блок пока не показывает.
- **Сектор позиции (PDL-F 2026-08-03, исправлено PDL-I 2026-08-27):** `holdings[].sector` — ВСЕГДА машинный canon-ключ macro-forecast-chain/stress (`banks_finance`/`oil_gas`/`utilities`…); дыры (SBERP/MOEX/NVTK/BTBR, новые IPO — IntelInvest сектор не даёт) закрывает `Claude-Memory/sector-overrides.yaml` через флаг `--sector-overrides` в Шаге 6 сборки (только gap-fill, размеченное не перекрашивается). Отображаемый ярлык (словарь IntelInvest, «Финансовый»/«IT»…) идёт в ОТДЕЛЬНОЕ поле `holdings[].sector_ru` — `null`, если ярлыка для тикера нет ни в overrides, ни выше по цепочке (переводов не выдумываем). До PDL-I `sector_ru` схлопывался прямо в `sector` — один и тот же сектор оказывался под двумя именами (машинный ключ у части тикеров, русский ярлык у тикеров из overrides); снапшоты старее 2026-08-27 несут эту смесь как есть (не мигрируются, пересобираются на лету). Weekly-стаб advisor'а строит те же два поля цепочкой `ie_model → snapshot.holdings → overrides → unknown` для `sector` (ie_model может нести произвольный текст из «Invest Era» — вне этого контракта) и `holdings.sector_ru → overrides.sector_ru → null` для `sector_ru`; вьюер показывает `sector_ru` с фоллбэком на `sector` — «unknown» на вкладке «Акции» означает дыру и в overrides-файле.
- **Статус позиции — SSOT в снапшоте (2026-07):** `holdings[].status` ∈ `normal | blocked | distressed` из **ручного** реестра `KNOWN_POSITION_STATUS` (`assemble_snapshot.py`, аналог `KNOWN_SPLITS`; MOEX статусы не отдаёт). Non-normal — с `status_note` (дата+причина+ссылка; пример: БорецКЗО26 `RU000A105GN3` — национализация 27.03.2026, купоны физлицам заблокированы судом). `is_blocked` — производное (`status == "blocked"`). Доли стоимости — `status_summary.by_status`; downstream (stress, integrated-view, coherence-audit §3) blocked/distressed-числа берёт отсюда, а не считает по своим спискам.
- **Подтипы облигаций (PDL, 2026-08-18):** план по облигациям в «Общем балансе»
  вырос с 5 (валюты+ОФЗ+КОРП одной строкой) до **9 плановых корзин** (ОФЗ ×3 срока/купон,
  КОРП ×3 кредитных диапазона). `holdings[]` облигаций несут `plan_bucket`/`plan_subtype`
  (из «Облигации».`Тип`/`Подтип` — **не** из таблицы «План по Облигациям», это два разных
  листа/таблицы) + производный `plan_bucket_key` (`"ОФЗ/>10"`, для валют — просто `"USD"`)
  + `credit_rating_file` (детальный рейтинг из файла; отдельно от `credit_rating` weekly-review,
  который остаётся `TODO_LLM`). Лестница §4.2: имя корзины — **ярлык, не порог** — `AA+`
  содержит `AAA`, `B+` содержит `BBB+`. `balance_summary.bonds_value_by_subtype*` (3 среза)
  дублирует `bonds_value_by_type*` по этому более узкому ключу; `balance_summary.bonds_plan_vs_fact` —
  план↔факт по каждой из 9 корзин, база **без ИИС-3** (владелец: «ИИС-3 фигурирует только
  в Общем балансе, дальше в долях отсутствует»), `actual_rub` пересчитан заново по
  `holdings[]` (свежие цены MOEX, не файловое значение) и для валютных корзин включает
  фонды из «Tаблица 1» с `Тип` вида `"<корзина> - Облигации"` (TLCB-кейс — фонд не на
  вкладке «Облигации», без него USD расходится с файлом на 500 400 ₽); параллельный
  `bonds_plan_vs_fact_iis` — факт по ИИС-3, без плана. 14 новых гейтов в
  `data_quality_flags` (`bond_subtype_missing`, `bond_bucket_not_in_plan`,
  `bond_ofz_subtype_maturity_mismatch`, `bond_rating_bucket_mismatch`… полный список —
  `output-schema.md`), поделены между `parse_portfolio.py` (не нужны свежие MOEX-данные)
  и `assemble_snapshot.py` (нужны holdings/даты погашения). Снапшоты до 2026-08-18 несут
  legacy-колонку `Рейтинг` вместо `Подтип` и 6 корзин — не мигрируются, читаются как есть
  (§4.4). Полный контракт (SSOT, не дублировать) — `docs/investment/portfolio/bond-subtypes-plan.md`.
- **Корзина облигации выводится (2026-10-28, §4.5):** `bond_bucket.py` из блока `bond` справочника
  `Portfolio/security-types.json` (`security_types.py` берёт его из ISS description: валюта номинала, `MATDATE`,
  эмитент Минфин по `ISSUENAME`, флоатер по «переменным купоном») и рейтинга КОРП (`per_bond[ISIN].rating` последнего
  обзора облигаций → `plan.bonds[ISIN].rating`, запасной; с 3.104 обзор перебивает план). Источники `assemble_snapshot` берёт рядом с `--plan`
  (`security-types.json`, `weekly-reviews/`) либо из `--types-cache`/`--reviews-dir`. Итоговая корзина в снапшоте
  пока по плану; выведенная — в `bucket_derived`, причина — `bucket_reason`, расхождение — `bond_bucket_changed` и
  `snapshot.bond_bucket_check`; ручная корзина — `plan.bonds[ISIN].manual`. Средняя цена покупки
  (`avg_price_pct`/`avg_cost_rub`, WACC по сделкам счёта) считается тут же: основной счёт — сделки основной
  выгрузки минус сделки ИИС-3, ИИС-3 — `bond_trades` из `iis_returns.py`. «При покупке» (`locked_pct`, у линкеров ещё
  `locked_real_pct`) — в holding каждого счёта: IRR потоков счёта по бумаге + будущие потоки по графику MOEX на количество
  счёта (`bond_locked.apply_locked`, общий расчёт `iis_returns.locked_for`); основной счёт — суммарные потоки
  `per_security` минус потоки ИИС-3 (как `by_account`), ИИС-3 — из `returns.by_account.iis_3.per_bond`; график — сеть к ISS
  (`--no-bond-locked` / `moex_down` — поле не пишется), нет графика или потоков — `null`. Провенанс: справочник — ISS при сборке на
  сайте; рейтинг — режим 2 советника (`rating {value, agency, date, source}`); `build_snapshot.py` флаги пока не
  выносит в карточку «Загрузок» (`bond_bucket_changed` нет в `ATTENTION_FLAGS`).
  Вьюер 3.103: карточка бумаги показывает выведенную корзину с причиной и источником (`bucket_source`/`bucket_reason`), исключение пишет `bonds.<ISIN>.{type,subtype,manual,reason}` (whitelist `api/pv/plan/set`), расхождение с планом — плашка «принять/оставить» и `pfBucketCard` на «Загрузках» (читает `brief.bond_bucket_check`); плитка «Средняя цена» — из `avg_price_pct`/`avg_cost_rub` счёта.
  Вьюер 3.104: «Моя доходность» в карточке (акция, облигация, фонд) — `myReturnTile` по `per_instrument_xirr[KEY].by_account[выбранный счёт]` (есть у бумаги на двух счетах; крупно — XIRR, при истории счёта < 30 дней — результат в % от вложенного «за N дней», годовых мелко; мелко «по обоим счетам»; без `by_account` — объединение с подписью, при `iis_trades_stale` — «сделки ИИС-3 устарели»); у облигации на ИИС-3 рядом «При покупке на ИИС». Поле «Рейтинг в плане» — только при итоговой корзине КОРП/*. `pf_build.brief` несёт `bond_bucket_check`.
- **Свёртка недавних сделок для RPA-правила неразворота (Rule 3, 2026-08):**
  `per_instrument_xirr[ticker]` несёт `recent_net_rub`/`recent_n_buys`/`recent_n_sells`/
  `recent_last_trade_date`/`recent_round_trip`/`recent_direction` — свёртку buy/sell-сделок
  за скользящее окно (топ-уровневый `recent_trades_window` даёт `days`/`net_threshold_rub`/
  `threshold_basis`). Только Покупка/Продажа: дивиденды/купоны/амортизации и Корректировки
  (Korrektirovka — синтетическая реконсиляция IntelInvest↔брокер, не решение владельца) в
  нетто **не входят** — реализация в `per_security_xirr._compute_recent_window`. Окно
  считает Шаг 4 (`--recent-window-days`, default 60, per_security_xirr.py); порог и
  классификация `recent_direction` (buy/trim/null) — Шаг 6 (`assemble_snapshot.
  _derive_recent_net_threshold`), потому что только там доступна «акционная книга»
  (`balance_summary.goals_matrix` RUB/Акция «Сейчас»; fallback — NAV excl. ИИС;
  `--recent-net-threshold-pct` default `1.0`, `--recent-net-threshold-rub` — override).
  Снапшоты до этой даты и любой `per_security.json` без `recent_window_days` — поля
  отсутствуют целиком (аддитивно, `schema_version` не менялся). Реализует и потребляет
  ЭТИ данные `ru-portfolio-advisor` (правило неразворота); data-loader только считает и
  кладёт в снапшот. Полная схема — `skills/portfolio-data-loader/references/output-schema.md`.
- **Лимиты концентрации акционной книги (2026-08, spec §9):** считает
  `ru-portfolio-advisor/scripts/concentration_limits.py`, конфиг —
  `references/concentration-limits.yaml` (один эмитент 15%, SBER+SBERP 20% именованным
  исключением, сектор 35%). **Знаменатель — фактическая книга `L2_cur`, а НЕ база докупки:**
  цели размещения считаются от того, куда книга идёт, лимиты — от того, какой риск несётся
  сегодня; «унификация» знаменателей здесь регрессия. Группировка эмитента — из конфига, а не
  по суффиксу `P`. Нарушение блокирует `Open` на докупку сильнее арифметического разрыва, но
  срез не блокирует никогда и снимает признак `--acted` правила неразворота. Секторная часть
  отказывается считать при доле `sector = null` выше 5% книги.
- **Правило кэша (2026-08):** `gate_aware_sizing.py` отдаёт блок `cash_buffer` —
  `buffer_pct% × NAV + (T_full − T*)` против **`cash.liquid_rub`** (не `total_rub`: деньги под
  гейтами стоят в money-market, по `total_rub` правило показывает вечную «нехватку» 96% и при
  односторонней тревоге молчит всегда). Фолбэка на `total_rub` нет намеренно. Тревога только
  на превышение — кэш ниже ожидаемого это рабочее состояние. Формулировка правила —
  `gate-aware-sizing.md` §«Сколько кэша считать нормальным…» (раздел о сайзинге вынесен из `stocks-methodology.md` 2026-10-26).
- **SS-1 (эмпирические беты, opt-in `--regression-mode moex`):** беты считаются OLS-регрессией месячной доходности на 24 мес истории MOEX/CBR; `macro_blindspot` авто при R²<0.3. Default — ручные priors (stdlib only, без сети).
- **MFC-4 (числовые макро-уровни):** в `macro-marginal-{date}.yaml` уровни — строки (`'$68/bbl'`); `compute_marginal_move.py` парсит их в `level_l1_<год>`+`unit`. `compute_horizon_factors` берёт уровень года, ближайшего к концу горизонта, и переводит в движение против `baseline_spot` (§5.6). Это же разблокирует **Layer 1** в integrated-view (`coherence_gap`).
- **Coverage-инвариант:** FCA-прогноз должен дотягивать до самого дальнего горизонта (сейчас FCA до 2027 → h24 на 2028 помечается `extrapolated`, CI инфлируется). См. §4.1.

- **Ввод задним числом и дубли досок (кейсы владельца).** ЭталонФин5 продан 28.09, внесён в IntelInvest после 13.10: бумага «пропала» без сделки, кэш-дрейф скакнул, обзоры прошедших недель разбирали проданное. Пересборка снапшота за тот же день кладёт прежнюю версию в `snapshots/.versions/`, на неё опираются сделанные обзоры. НорНик1P17 торгуется на TQCB и TQOY — в «Облигациях» Numbers одной строкой с общим количеством, иначе флаг «количество облигаций расходится со сделками».

### 1.2 Модель по скиллу (зеркало — справка, раздел «Модели и режимы» `{#models}`)

SSOT — `_shared-references/model-routing.md` (+ детальные `references/model-routing.md`
у `ru-portfolio-advisor` и `retrospective-forecast-audit`). Пользовательская справка
вьюера держит сжатую копию таблицы (§2а) — **при смене маршрутизации в
model-routing.md обнови и её, и эту сводку** (правило синка выше).

| Скилл | Когда | Модель |
|---|---|---|
| `portfolio-data-loader` | снимок портфеля | Sonnet |
| `ru-portfolio-advisor` | режимы 1–7 (обзоры, ребаланс, эмитент, фонды, доходность, ИИС) | Sonnet |
| `ru-portfolio-advisor` | режим 8 (Forward review) и многорежимные запросы | **Opus** |
| `macro-ru-watcher`, `macro-forecast-chain`, `portfolio-scenario-stress` | макро-срез, прогнозы, стресс | Sonnet |
| `forecast-confidence-applier`, `scenario-builder`, `hypothesis-stress-tester`, `forecast-collector` | прогнозы и сценарии | Sonnet |
| `retrospective-forecast-audit` | ≤8 тезисов / ≤45 мин — Sonnet; больше — **Opus** | Sonnet / Opus |
| `forecast-monitor` | еженедельная проверка прогнозов | Haiku |
| `portfolio-integrated-view` | интегрированный вид | **Opus** |
| `portfolio-coherence-audit` | Stage P — любая; полный прогон (Stage R) — **Fable** (на Pro нет → Opus с оговоркой) | Fable |
| `save-to-library`, `memory-sync`, `revise-memory-*` | сохранение и обслуживание библиотеки | Sonnet |

**Черновик + выжимка (зеркало — справка `01-run.md` `{#run}`).** `portfolio-scenario-stress`, `portfolio-integrated-view`,
`forecast-monitor` и `retrospective-forecast-audit` пишут полный артефакт черновиком в `Claude-Memory/_drafts/` под
библиотечным именем (`stress-<дата>-<slug>.md`+`.yaml`, `integrated-view-<дата>.md`, `monitor-report-<дата>.yaml`,
`<дата>-<source-slug>-<period>.md` + `<source-slug>-<period>-profile.md`) до вывода, в чат печатают выжимку и строку
«черновик: …»; save-to-library берёт файл из черновика (Workflow E1.0, G1.0, L1.0, D1.0), без mount — из чата
(«черновик не записан»). Вьюер черновики не читает: на сайте артефакт появляется только после сохранения.
`ru-portfolio-advisor` печатает отчёт в чат полностью. Раскладка зоны — `claude-memory-layout.md`.

---

### Журнал решений и теневые базы (AIR-1, 2026-10-07)

Писатель — только сборка сайта: после «Сохранить» на «Загрузках» `pf_build.publish_journal` запускает
`decision_journal_update.py` (рабочий корень `--memory` со ссылками на том; `build_snapshot.py` журнал больше не
запускает — шаг 15; на Маке — только по просьбе) → `shadow_inputs.py` (факт B3 = Σ незаблокированных + кэш, с 2026-07-08;
внешние потоки — «Внесение/Списание» денег с пустой заметкой или «Пополнение счета»; дивиденд брутто на акцию; история
плана из `ie_actual.planned_share_pct`, `goals_overall`, `goals_bonds_breakdown`) → `shadow_baselines.py`
(B0/B1/B2-live/B2-frozen на тех же потоках, правило полос ±5 п.п. / ±25%) → `decision_journal.py` →
`Portfolio/decision-journal/`. Источники `decision_journal.py` (schema.md §4.5): обзоры, файлы решений
(`decisions_read`; невалидный — флаг), определения `conditions@2` + годовые архивы + `conditions-state.json` через
модуль (а) на срезе конца окна, журнал плана `plan-journal.jsonl`, реестр типов. Эпизод решения — окно от
`recorded_at` до следующего решения, не дальше `review_by` (+60 дней без него); без сделки по порядку:
`deferred_by_condition` (связанное условие или ждущее владельца, R23) → `owner_decided` (R24: `done by: owner`,
`owner_mark` dismissed/deferred, строка журнала плана `stocks|bonds|funds.<K>.user_status|user_plan|action`) →
`ignored`; вопрос об отказе — один раз и только по `ignored`. Ручные входы (`refusals/theses/incidents.yaml`) —
save-to-library Workflow P, валидатор `ds_schemas.py` до сборки; `incidents.yaml` журнал читает
(`incidents_monthly.manual`); итог контрольной точки — решением (`decision_write.py owner`, R25), `checkpoints.yaml`
нет. Ряды рынка — `market_series.py` (кэш `~/.cache/claude-skills/market-series/`). Советник журнал целиком не
читает — выборка `journal_digest.py` (Шаг 3.6 стартового чек-листа). Пользовательская версия — справка,
`08-site.md` `{#site-journal}` (зеркало, SYNC). План — `docs/investment/portfolio/air-1-decision-journal-plan.md`.

---

### 1.3 Данные портфеля: сущности, писатели, модули (цикл машиночитаемости, 31.10)

Эталон — `docs/investment/_cross-cutting/data-structures/schema.md` (§2 карта, §3 новые сущности, §6 читатели);
раскладка и матрица «кто пишет / кто читает» — `_shared-references/claude-memory-layout.md`. Правило — **один
писатель на файл**; производные не хранятся; читатели объединяют источники только тремя модулями с Python- и
JS-близнецами и тестом паритета.

| Сущность | Файл | Писатель | Читают через |
|---|---|---|---|
| решение по бумаге `decision@1` | `Portfolio/decisions/{ГГГГ-ММ-ДД}T{ЧЧММ}-{KEY}.json` | `decision_write.py` (save-to-library: `from-report`, `owner`); с сайта — hub-notify `decision_job.py` (`POST /api/pf/decision` → hub-api `/api/job/save`, только новый файл) | модуль (б) |
| определение условия `conditions@2` | `Portfolio/conditions.yaml` (+ `conditions-archive-ГГГГ.yaml`) | `apply_condition.py` (save-to-library) | модуль (а) |
| состояние условия `conditions-state@1` | `Portfolio/conditions-state.json` | hub-api (сайт и hub-notify) | модуль (а) |
| справочник бумаг `security-attrs@1` | `Portfolio/security-attrs.json` | `security_attrs.py set` (save-to-library Workflow Q) | модуль (б), выборки |
| обзор недели, отчёт `report@1` | `weekly-reviews/*`, `reports/*.md` | save-to-library (F, N; `stamp-report` ставит `recorded_at`) | модуль (б) — вердикт обзора |
| план, журнал плана | `plan.json`, `plan-journal.jsonl` | hub-api | напрямую (`since=`) |
| снапшот, реестр типов, журнал решений | `snapshots/`, `security-types.json`, `decision-journal/` | сборка сайта | напрямую |
| кодлисты `codelists@1` | `_shared-references/codelists.json` | разработчик (git) | модуль (в) |

Модули: **(а)** условия «определение + состояние» — `conditions_merge.py` / `conditions-merge.js`; **(б)** «последнее
слово» и гейт — `last_word.py` / `last-word.js`; **(в)** кодлисты — `codelists.py` / `codelists.js` (генерация
`--emit-js`). Время — `time_msk.py`: `ГГГГ-ММ-ДДTЧЧ:ММ:СС+03:00`, ставит скрипт или сервер, «что новее» — только по
полю времени. Удалены: `gate-reviews*.yaml`, `Portfolio/securities/`, `stale_flags.yaml`, `checkpoints.yaml`,
содержимое `.backups/` кроме копий `INDEX-*.md` от `update_index.py` (из рабочей папки — при переключении, шаг 17), директивы гейта в отчётах, `condition_events` монитора.

**Порядок сохранения отчёта** (save-to-library Workflow N2): файл → `assemble_artifact.py stamp-report` →
`validate-report` (блокирующая) → `apply_condition.py add` для новых условий → `decision_write.py from-report
[--created …]`. **Выборки для советника** вместо чтения носителей (C5, ≤ 6 тыс. токенов на бумагу):
`security_digest.py --key`, `decision_write.py digest --key`, `apply_condition.py digest --key`,
`security_attrs.py get`, `journal_digest.py`, `prior_digest.py --decisions --conditions`; сторож —
`test_skill_instructions_ds.py`.

## 2. Режимы ru-portfolio-advisor

8 режимов. Все, кроме 5b и методологических вопросов, требуют **snapshot ≤ 14 дней**.

> **Примеры запуска (что сказать Claude)** — пользовательские триггер-фразы по каждому
> режиму и скиллу: в справке вьюера, `01-run.md` `{#run}` («Как
> запустить») и в `skills/ru-portfolio-advisor/EXAMPLES.md` (полные промты; часть
> примеров там ссылается на старые поля — снапшот уже всё содержит, сверяйся).
> Зависимости «что от чего» и пример «прогноз на дату X / скользящий период Y» — там же.

| # | Режим | Вопрос пользователя | Горизонт | Читает stress | Артефакт |
|---|---|---|---|---|---|
| 1 | Weekly Stocks | «обзор акций за неделю» | недели | нет | `weekly-review-stock` |
| 2 | Weekly Bonds | «обзор облигаций» | недели | нет | `weekly-review-bond` |
| 3 | Rebalance | «слушаться ли IE», «какие веса» | тактика (срез **h12**) | **да** — для L1-redirect | `tactical-rebalance` |
| 4 | Single Analysis | «разбери Сбер», «доходность по X» | — | нет | в чат |
| 5 | Fund Analysis | «разбери TGLD» / «чем заменить» | — | нет | в чат |
| 6 | Returns | «какая моя доходность», «что тянет вниз» | — | нет | в чат |
| 7 | ИИС-3 Buy | «пополнил ИИС, что купить» | — | нет | в чат |
| 8 | Forward Review | «качество корзины на 1–2 года», «что заменить» | **1–2 года (h12/h24)** | **да** | gate-update + чат |

> **Обзоры недели — контекст и провенанс (RPA-34…38, 2026-10-26).** Сбор новостей по ≥5 бумагам —
> только субагентами в файлы (`fanout-news.md` → `sweep_collect.py`, `coverage.method: sweep_collect`;
> без него валидатор блокирует обзоры с 27.10, исключение `inline_owner_approved` + `method_note`).
> Прошлый обзор — выжимкой `prior_digest.py` с `--conditions --decisions --reports-dir` (шаг 10 цикла
> машиночитаемости): условия модулем (а), гейты из последних решений словами, разборы бумаг после прошлого
> обзора с записанными из них решениями. Перенос
> `carry_over_weekly.py` отбирает старые источники (живые ссылки + 3 новейших) и не даёт delta удалить
> действующее ограничение (`--example` — образец delta). MD — `render_weekly_md.py` из YAML + `changes.md`
> модели (RPA-33). YAML/MD — файлами, валидатор — `--file`/`--anchor --current`. Статусы
> гейтов в тексте для человека — подписями вьюера (`_shared-references/gate-status-labels.md`).

### 2.1 Почему режим 1 и режим 8 расходятся

Это **штатное** поведение — режимы отвечают на разные вопросы.

```
Режим 1 (near-term):   фундаментал(near) + недельные катализаторы → вердикт
Режим 8 (forward):     фундаментал(gate) × макро-сценарии(stress) → вердикт за 1–2 года (h12/h24)
```

Иерархия принятия решений (`methodology.md §9.1`):

```
1. Fundamental gate    ← фильтр: «компания жива как актив?»  (alive/under_review/broken)
2. Macro / scenario    ← модификатор размера: «условия благоприятны на 1–2 года?»
3. Target frame        ← тактика: planned_share → ie_target → real
```

Режим 1 даёт near-term сигнал **без** сценарного макро-слоя. Режим 8 читает
stress и накладывает макро поверх фундаментала по таблице §9.2:

| Gate | Modal-сценарий | Вердикт |
|---|---|---|
| alive | tailwind | BUY/HOLD к target |
| alive | neutral | HOLD, малые adds |
| alive | **headwind** | **HOLD без adds, ждать триггеров** |
| alive | severe headwind | TRIM до safe-size |
| under_review | любой | HOLD, ждать gate-clarification |
| broken | любой | REDUCE/EXIT поэтапно |

**Кейс OZON:** режим 1 = «BUY» (near-term тезис ок), режим 8 = «не добирать»
(на 1–2 года либо gate-сомнение, либо headwind-сценарий из stress). Для
**структурного** решения авторитетен режим 8. Диагностика — *почему* он против:
- если **фундаментал** (`under_review`/`broken`) → ждать прояснения gate;
- если **headwind-сценарий** (gate `alive`) → это «не сейчас», а не «никогда»;
  триггер на добор вернётся при смене modal-сценария.

Именно это расхождение `portfolio-integrated-view` подсвечивает тегом
🔴 **disagree** (стресс и обзор не согласны).

### 2.2 Какой режим под твой вопрос

- «Что нового на неделе, есть ли срочные триггеры» → **режим 1**.
- «Стоит ли мне добирать/резать X вдолгую, какая корзина на 1–2 года» → **режим 8**.
- «Какие веса выставить сейчас, слушаться ли ребаланса IE» → **режим 3**.
- «Сколько я заработал / что тянет портфель вниз» → **режим 6**.

### 2.3 Гонять 8 или 8+1

- Режим 1 **уже прогнан**, snapshot свежий → запускай **режим 8 отдельно**.
  Повторять режим 1 не нужно.
- Связка **1+8** оправдана, только если нужны оба свежих YAML
  (`weekly-review-stock` + forward-вердикт) для `integrated-view` в одной сессии —
  экономит один read snapshot.
- Оба варианта (режим 8 и любой многорежимный запрос) → модель **Opus 4.7**.
  Режим 1 отдельно → Sonnet 4.6.

### 2.4 Когда перегонять stress

`Portfolio/stress/stress-{latest}.yaml` читают **два** режима, и лестницы у них разные
(RPA-20, 2026-08-20). В обоих случаях файл разбирает `scripts/stress_digest.py`, а не
чтение YAML руками; процедура — `skills/ru-portfolio-advisor/references/stress-reading.md`.

| Возраст stress | Режим 8 (forward review) | Режим 3 (rebalance) |
|---|---|---|
| ≤ 30 дней | работает молча | полная TR-таблица §6.2 |
| 30–60 дней | предупреждение + запрос подтверждения | предупреждение; пропорция redirect помечается «проверить после refresh» |
| > 60 дней или файла нет | отказ: «запусти macro-forecast-chain → portfolio-scenario-stress» | **defer только L1-redirect** (§6.3): buffer остаётся внутри акций, остальной режим (диф IE, тайминг продаж, база докупки, макро-матрица) выдаётся полностью |

Режим 3 не отказывает целиком потому, что стресс нужен одной его ветке из семи —
обоснованию переноса денег через границу класса.

**Горизонты якорные.** `horizon_mode: anchored`: ключи h6/h12/h24 — конвенция цепочки, а
длина берётся из `horizon_ends` (для прогона 15.08.2026 — 4,5 / 10,5 / 22,5 мес). Основной
срез режима 3 — **h12**, h24 второй колонкой; дивиденды и купоны масштабируются реальным
множителем (0,873 / 1,875), не литеральными `12/12` и `24/12`. Bond-сторона TR-таблицы по
**держимым** выпускам берётся из готового блока `bond_carry` стресса; руками считаются
только кандидаты, которых в портфеле нет.

`portfolio-integrated-view` свой порог держит на **90 днях**.

**Практика:** 16 дней — свежо, перегонять не надо. Исключение — если за этот
срок было заседание ЦБ или резкий сдвиг FX/Brent: тогда
`macro-forecast-chain → portfolio-scenario-stress`, потом повтори режим 8.

---

## 3. Гейт — проекция последнего решения (`Portfolio/decisions/`)

Файла гейтов нет (schema.md §4.4): статус гейта, его срок, пауза докупки, IPO-пауза, `new_position` и `divested`
считает **модуль (б)** «последнее слово» — `_shared-references/last_word.py` и близнец `tools/assets/last-word.js`
(`window.LW`, паритет `test_last_word_parity.py`) — из файлов решений `Portfolio/decisions/*.json` (`decision@1`),
строк обзоров недели, справочника бумаг `security-attrs.json` и снапшота. Читают его движок «Сейчас»
(`rebalance-engine.js` `runAuto`, Python-близнец `gate_aware_sizing.py --decisions --security-attrs`), вьюер (`lwCard`,
`gateOf`), `decisions_read.gate`, `backfill_decisions.py verify`. `gate-reviews.yaml` и архив кодом не читаются;
в рабочей папке лежат до переключения (шаг 17, `data-structures/decision.md` §4.2).

**Решение владельца с сайта (no-ai-mode 2.2).** Карточка бумаги во вьюере (акция, облигация, фонд) пишет решение
`decision@1` с `author: owner`, `source.kind: owner` — тем же кодом, что CLI `decision_write.py owner`: единая сборка
`decision_write.build_owner` (проверка полей `ds.validate_report_decisions`, `conditions_resolved` — только `waits_owner`
по модулю (а), `ds.validate_decision`); CLI и сайт не имеют двух реализаций. Маршрут — `POST /api/pf/decision`
(hub-notify, `tools/hosting/notify/decision_job.py`; зона Caddy `/api/pf/*` — пароль с любого IP): тело `{key, verdict,
target_pct?, review_by?, note, confidence?}`; `verdict` — кодлист `verdict`, `review_by` по умолчанию сегодня + 60 дней
и допустимо 7–180, `note` 20–200 знаков, ключ — `[A-Z0-9.-]+` (так устроен путь в `JOB_WHITELIST` hub-api:
`Portfolio/decisions/{ГГГГ-ММ-ДД}T{ЧЧММ}-{KEY}.json`), `recorded_at` — МСК сервера. Файл всегда новый: проверка `read_fn`
до записи и `jobs.save_new` (base_hash = null; 409 hub-api не повторяется с чужим хэшем, в отличие от `jobs.save`) —
повтор той же минуты по ключу даёт 409, перезаписи нет. Модули в контейнере берутся из `pdl/` (deploy.zsh выкладывает
`decision_write.py` в `pdl/skills/save-to-library/scripts/`, остальное — `_shared-references/`). Журнал решений подхватит
запись при следующем «Сохранить» снапшота (`pf_build.publish_journal` требует выгрузки сделок прогона — отдельной
пересборки при записи решения нет). Вьюер: `ownerDecisionNode` (`viewer.js`), одна кнопка «Записать решение» (форма `ownerDecForm`: вердикт, срок, уверенность, «почему»; `target_pct` в форме нет — доля задаётся планом, движок долю решения не читает), только при `data-noai` (режим «без ИИ», решение владельца
11.11: при «с ИИ» решение владельца докупку не открывает — правило 9а — и кнопки только путали). Пользовательская версия — `06-gates.md` `{#gates}` и `08-site.md` (SYNC).

**Последнее слово — по полям** (schema.md §3.5): вердикт, направление, уверенность — из новейшего источника по
`recorded_at` (решение или строка обзора; при равенстве решение новее); целевая доля, срок пересмотра,
созданные/закрытые условия — **только из новейшего решения**. Конфликт — предыдущий источник другого вида с другим
`verdict_direction`; закрывается подтверждением направления, правкой `user_status`/`user_plan` (строка журнала плана
новее конфликта) или сделкой (разница количеств между снапшотами — «закрыто сделкой, без подтверждения»).
«План против последнего слова» (плашка; до 03.11 — «План против решения») — `user_plan_direction[план]` против `verdict_direction[последнее слово]`. Карты — кодлисты. У «привести к плану» (BALANCE, R31, правило 11) направление — знак отклонения: `fact_pct > plan_pct + defaults.plan_tolerance_pp` → down, ниже минус допуск → up, внутри → flat, нет долей → null; вьюер передаёт `fact_pct`/`plan_pct` из `ie_actual.per_ticker` (`dsPlanCtx`). Проза строк «Действий» — `_proseNode` (первая фраза, короче 40 знаков — две; остаток под «подробнее ▾»); id условий в прозе обзора — `_noCondIds` → «короткий текст условия» (`condShortText`), неизвестный id остаётся.

### 3.1 Кто меняет гейт

**Режим «без ИИ» (`ai_mode: off`, `last_word.py`/`last-word.js` правило 9, `ctx.ai_mode`, по умолчанию `on`):** с 11.11 блокируют те же статусы класса `gate` (`gate_to_block`), что и при `on`, плюс `ipo_gate` и `add_cooldown`; `gate.warnings` пуст при `defaults.noai_gate_blocks: true` (значение с 11.11; `false` — откат: `gate:<status>` уходил бы из `gate.reasons` в `gate.warnings`). Блок снимает решение владельца (правило 9а при `off` не действует — решение владельца считается как любое), вьюер при `off`: «откроет твоё решение» в `buyReasonsText`, ссылка «запиши решение →» в «Сейчас» (`.rb-own-dec`: открывает карточку и раскрывает форму `ownerDecisionNode`; только причина `gate:`, паузы и условия без неё). **При `on` — правило 9а:** гейт считается дважды (по всем решениям и без решений `source.kind = owner`), итог — строже из двух; если докупку держит только вариант без решений владельца, `gate` несёт его статус и срок разбора и `owner_pending_review: true` (вьюер: «подтверждено вами дд.мм — откроет разбор советника»); решение владельца гейт закрывает, но не открывает. Вердикт, цель и срок карточки — из новейшего решения, как прежде. Движок: `runAuto(..., {aiMode})` / `gate_aware_sizing.py --ai-mode on|off` (по умолчанию `on`).

| Источник | Что делает |
|---|---|
| Разбор бумаги / ребалансировка / оценка качества (режимы 4, 3, 5a, 8) | блок `decisions:` в шапке отчёта (`report@1`: `verdict`, `target_pct`, `review_by`, `note`) → при сохранении `save-to-library` Workflow N пишет файл решения скриптом `decision_write.py from-report`; гейт = `verdict_to_gate[verdict]`, срок = `review_by` (null → +60 дней) |
| Владелец («подтверждаю держать X») | `decision_write.py owner` (Workflow M) — новое решение с `author: owner` |
| Режим 1 | решений не пишет: `flags.gate_review_required: true` у бумаги даёт «Нужен разбор», пока обзор новее решения (модуль (б), шаг 11); критические события — `critical-events-list.md` |
| Справочник бумаг | класс (`ticker_class`) и `listed_at` — `security_attrs.py` (Workflow Q); IPO-пауза = класс `ipo` и листинг моложе 8 кварталов |
| Сайт | ничего не пишет: статус пересчитывается при каждом чтении (истечение `review_by`, пауза 21 день от покупки, IPO-пауза, `divested` по снапшоту) |

Выборки гейта для советника (`decisions_read.gate` — обёртка над модулем (б)):
`decision_write.py digest --key` (строка `latest.gate`), `security_digest.py --key`, `prior_digest.py --decisions`,
`assemble_artifact.py validate-weekly-review-stock|bond --file … --root` (контекст `verification_priority`).

**Приоритет проверки (R28, 4.2.1).** `verification_priority` ставит скрипт: `assemble_artifact.py stamp-report --root …
--doc Portfolio/weekly-reviews/weekly-review-{stock|bond}-<дата>.yaml` после записи обзора — `recorded_at` (если нет) и
приоритет каждой бумаги `constraint_engine.compute_verification_priority` в контексте `_priority_context_from_root`
(гейт модуля (б) по решениям и строке самого обзора, действующие условия модуля (а), справочник бумаг); правка построчная,
вывод `priority_changed` «тикер: было → стало». Стабы пишут `verification_priority: null`, `carry_over_weekly.py` прошлое
значение не переносит, копию `gate_status_snapshot` не переносит и не принимает (`ITEM_DROPPED`). Валидатор обзора:
с `--root` расхождение (и пустое поле) — blocking; без `--root` — warning «контекст не передан»; копия
`gate_status_snapshot` — warning «устаревшая копия» (старые обзоры валидны). Движок: `GATE_REVIEW_PENDING` =
`review_needed`, `new_position`, `review_aging` → HIGH; `reviewed_under_review` — не pending (MEDIUM через условие).
Читатели: приоритет — подпись строки; вьюер (`actionBlocks`) ставит в «Проверить» только пункты `verification_checklist`
при HIGH, «срочно» без пунктов — «Ждём» (есть ждущее условие) или «К сведению»; уведомитель (`action_row`) — push по
направлению вердикта или пунктам при HIGH. MD-обзор `render_weekly_md.py` колонку гейта берёт из копии — у новых обзоров
её нет (прочерк).

**Перештамповка и пункты проверки (R33, 4.2.2).** `apply_condition.py add|edit|withdraw` после записи перештамповывает
обзор недели того же дня (по МСК), где есть ключ условия (`assemble_artifact.stamp_report` функцией; вывод
`restamped: [{doc, priority_changed, stamped}]`, ошибка — `restamp_warnings` без отката правки); повтор без новой правки
ничего не меняет. `edit` без `source` во входе: `--by owner` → `{owner, null}`, `mode_*` → `{report, null}`, прочие —
прежний. Упразднённые блоки обзора (`TOP_DROPPED` в `carry_over_weekly.py`: `conditions_evaluated`, `conditions_state`,
`conditions_mutations_applied`, `gate_review_directives`, `proposed_gate_review_directives`) не переносятся и через delta не
принимаются; валидатор (`_obsolete_blocks_check`, обзоры с 31.10) — warning, `written_back: true` — blocking. Пункты
проверки (`_checklist_check`, по приоритету после штампа): HIGH без `verification_checklist` — blocking, HIGH от гейта
`GATE_REVIEW_PENDING` при вердикте-не-действии — warning «нужен разбор: «Разбери X»», MEDIUM — warning. Резолюция
сработавшего условия — фрагмент `<!-- cond: id -->` в changes.md (`render_weekly_md.py`, у старых обзоров —
`conditions_evaluated.fired[].resolution`).

**4.2.2, дополнения 03.11.** (8) R20 уточнён: «горизонт прошёл» у любого прогноза вне входов стресса — «Проверить»
(`B.check.horizon`, `_horizonAlert`/`_horizonRow`: «горизонт прошёл дд.мм → закрой с исходом», фраза
«/save-to-library Закрой прогноз <stem файла> с исходом: …»); у входов стресса — прежний путь `_forecastActionable` в
«Сделать». (9) Счётчики «Сделать»/«Проверить» = строкам: `_doRowSpecs(B)`/`_checkRowSpecs(B)` — один список для
`B.n` и `renderActions` (стресс «есть новее» по N прогнозам — одна строка и одна единица). (10) План и плашка — один
источник (`ie_actual.per_ticker` после `planApplyAll`); память `lwCtx` теперь ключуется версией плана
(`state.plan.hash`), иначе после ✎ (`planEditSave` не сбрасывает журнал) плашка держала прежний план; `loadPlan`
перерисовывает и «Действия»/«Сегодня». (11) Правило 13 модуля (б) — по последнему слову (решение или обзор):
«вниз» + `last_sell_at` позже → время продажи, «вверх» + `last_buy_at` позже → время покупки; `executed_source_kind`; `decision_executed_at` — то же по новейшему решению (строка разбора `decisionRowText`, «Сделано» по решению);
вьюер — `executedText`, «Сделано» `_executedRow` по всем ключам, заголовок блока «Решение» карточки.

**Есть в портфеле (R29, правило 14 модуля (б)).** Карточка несёт `held` (ключ в `snapshot_keys`), `left_at`
(`last_sell_at`) и `left_kind` (`redeemed`, если ушла в дату ≥ `maturities[ключ]`, иначе `sold`) — для всех классов, гейт
не меняется. Ушла — только при свидетельстве: продажа в истории или погашение ≤ сегодня; кандидаты и бумаги вне известной
истории — `left_kind: null`. Входы: вьюер — `dsMaturities()` (снапшоты истории и обзоры облигаций), уведомитель — `held_keys`
= `decisions_read.held_keys` (одна функция для `snapshot_keys`, количество > 0, без `first_buy`). Вьюер: `divestedOf(key)` →
`{sold, kind}` для любого класса; карточка облигации/фонда — «Погашена/Продана дд.мм» без доли, YTM, дюрации и «При
покупке»; «Облигации» — строка остаётся (фильтр «Нет в портфеле», подзаголовок «в портфеле N, погашено M»); «Фонды» —
подзаголовок «в портфеле N, продано M»; «Действия» — строки ключа в «Сделано» («погашена дд.мм — обзор дд.мм исполнен»),
условия — с пометкой «бумаги нет в портфеле» (`condGoneNote`, снимает владелец); «Выплаты» и «Сегодня» — выплаты после
ухода, сроки условий и катализаторы ушедшей бумаги не показываются (`payoutGone`).

**4.2.4, хвосты 04.11.** (1) «Фонды» и «ИИС-3» — ушедшие строками, как «Облигации»: `goneRows` (`goneKeysOf('fund')` без
ушедших только с ИИС-3) и `_iisGoneRows` (ИИС-3 бумаги истории + `other_positions` перенесённого расчёта); счёт строки —
`_lastAcctsOf(key)` (последний снапшот, где бумага была; `_goneOnlyIis` — не на «Облигациях»/«Фондах»); `other_positions`
ушедшей бумаги не даёт строки живой. Подзаголовок — `_goneCountWord`, фильтр «Нет в портфеле», атрибут `data-gone`.
(2) «Прогнозы»: `_fcHorizonAlert(stem)` — незакрытый `horizon_passed` по файлу → строка `.fc-hp` «горизонт прошёл дд.мм» и
`_copyChip(_horizonSay(…), 'Закрыть')`. (3) Одна команда — одна строка блока: `_mergeSpecsBySay` (фраза по `_specSay`:
стресс, устаревший отчёт, монитор без пары) → `[вид, элемент, слитые]`, счётчик = строкам; `_mergedRow` — стресс устарел +
на заменённых → `_stressMergedRow` (`data-stale` и `data-stress-newer`), иначе заголовки слитых — `ui-sub`. (4)
`integratedView` больше не выкинут из `_actStaleList`: при строке стресса (`_doRowSpecs`) его команда — `.act-then` «затем:
…» в той же строке, без неё — своя `_staleRow`.

### 3.2 Статусы

`new_position` · `review_needed` · `reviewed_keep` · `reviewed_buy_more` ·
`reviewed_under_review` · `reviewed_reduce` · `review_aging` · `divested` — кодлист `gate_status`, проекция
вердикта — карта `verdict_to_gate` (BUY/ADD → `reviewed_buy_more`, HOLD/HOLD_TO_MAT → `reviewed_keep`, WATCH →
`reviewed_under_review`, TRIM/SELL → `reviewed_reduce`); истёк срок решения → `review_aging`; пауза докупки —
21 день от первой покупки после решения BUY/ADD (`defaults.add_cooldown_days`; правило 7 модуля (б), 11.11: покупки — `buys_at`,
без него `last_buy_at`; покупки нет — паузы нет; движок получает их в `gateInputs`, советник — `decisions_read.trade_times`
по истории снапшотов). Гейт — только у акций (реестр типов).
Замороженные позиции (`status == "blocked"`) вне scope gate.

### 3.3 Как изменения попадают в данные

Директив гейта и Workflow применения нет: решение пишет скрипт при сохранении отчёта (порядок Workflow N2:
файл отчёта → `stamp-report` → `validate-report` → `apply_condition.py add` для новых условий →
`decision_write.py from-report --created …`). Решение append-only (новый файл на каждую запись), сработавшие
условия бумаги оно закрывает (`conditions_resolved`, кроме `keep_open`). Резервных копий в `.backups/` нет.

### 3.4 Где gate отображается во вьюере

| Элемент | Код | Что показывает |
|---|---|---|
| Кнопка `🛡 Решения` в шапке (`#btn-gate-legend`) | `showGateLegendModal` → `decisionKeysAll`, `lwCard`, `gateOf`, `buyReasonsText` | окно «Решения по бумагам»: по бумаге — «докупка открыта/закрыта: причина» (`.dec-buy`), вердикт и его источник, цель, срок, пауза докупки, IPO-пауза, плашки модуля (б) (`lwPlaquesNode`), история решений из `decisions/` со ссылкой «разбор от дд.мм» (`source.doc`, имя файла — в `title`); фильтр по статусу и «закрыта докупка»; легенда статусов из кодлиста `gate_status` |
| Бейдж у тикера (📈 Акции) | `renderGateBadge` → `GATE_STATUS_META` | значок статуса; tooltip — решение, срок, паузы; «нужен разбор»/«срок решения вышел» копируют команду разбора |
| Блок «Решение» карточки | `lwCard` → `h3r` «<источник последнего слова> дд.мм [· обзор дд.мм] · уверенность», `decisionRowText`, `buyLineText`, «Ждём:» (`condShortText`), `gateSayNode`, `lwPlaquesNode`, `cardBaseNode`, проза свёрнута | последнее слово по полям, строка решения («Разбор 23.10: сократить — исполнено сделкой 27.10 · срок решения 06.11», `executed_by_trade_at`), «Докупка: открыта/закрыта: …», фразы снятия, плашки конфликта и «план против последнего слова» |
| Блок «Фундаментальная оценка» карточки эмитента | `renderGateBlock` | статус, «почему» (`decision.note`), дата и источник решения, срок, паузы |
| Фильтр «Решение» над таблицей | `filterState.gate` | срез по статусу (напр., только `review_needed` — todo-лист для Mode 4) |
| Сверка в integrated-view §0 | producer-проза | расхождения gate-статуса vs weekly-вердикта помечаются (штатная разница слоёв) |

### 3.4а Статусы кодами ↔ словами; влияние на базу «Сейчас» (вьюер 3.91.0)

#### Что на что влияет (3.95.0; пользовательское зеркало — `06-gates.md` `{#gates}` (статусы, фразы снятия, неразворот и лимиты) и `05-now.md` `{#now}` (слова плана, блокировки, база))

| Сущность (код причины) | Блокирует докупку | Вызывает продажу | В базе «Сейчас» | Кто снимает/меняет |
|---|---|---|---|---|
| статус `gate:new_position` / `review_needed` / `reviewed_under_review` / `review_aging` (на экране — «Докупка: закрыта: …», `buyReasonsText`; «Сейчас» — `gateReasonText`) | да | нет | `frozen` (F) по текущим рублям — и недобранная, и выше плана (§10.7) | новое решение: разбор (mode_4), оценка качества (mode_8), `decision_write.py owner` |
| статус `reviewed_keep` / `reviewed_buy_more` / `reviewed_reduce` | нет | нет | F по текущим рублям (бумага не торгуется; решение владельца 11.11) | разбор |
| IPO-гейт `ipo_gate:Nq` (справочник бумаг: `ticker_class: ipo`, `listed_at` + 8 кварталов > сегодня) | да | нет | F (`frozen`) | время, разбором не снимается |
| пауза докупки `add_cooldown:<дата>` (21 день от первой покупки после решения BUY/ADD, `defaults.add_cooldown_days`) | да | нет | F (`frozen`) | время |
| неразворот `no_reversal:<до>` (§10.6 п.6 спеки trim-fix; `defaults.no_reversal_days` = 14; сделки — `last_sell_at`/`last_buy_at` в `gateInputs`; строка `no_reversal {until, trade, trade_at}`) | да — после продажи; срез после покупки не предлагается | нет | F (недобранная — blocked, перевешенная — dormant) | новое решение или правка плана (`plan_changed_at`: журнал плана `stocks.T.user_plan`/`plan_pct`) позже дня сделки; время |
| лимит эмитента `concentration_breach:<issuer>` (в тексте `conc:<issuer>`; 15 %, SBER+SBERP 20 %) | да | нет | F (`frozen`) | срез или рост книги |
| условие с исходом «купить» `pending_buy_condition` (`on_trigger.verdict` BUY) | да | нет | F (`frozen`) | срабатывание, событие `done`/`owner_mark` (кнопки сайта), `withdraw` (`apply_condition.py`) |
| условие с исходом «срез/продать» `sell_condition:<id>` и «пока ждём: держать» `condition_hold:<id>` (`while_pending` HOLD/TRIM/SELL) | да, в окне `not_before`..`valid_until` | нет — продажу не вызывает и не блокирует | F (`frozen`) | то же |
| условие вида «разбор» (`kind: review`, без `while_pending` HOLD/TRIM/SELL) | нет | нет | F по текущим рублям (не заморожена) | то же; на строке — подстрока «условие: разбор до …» (`reviewCondText`) |
| план `KEEP` | нет (`user_plan:KEEP` — dormant) | нет | F по текущим рублям (11.11; `HOLD_IN_BASE_PLANS` — только метка `hold`/`base_weight_pct`) | план на сайте |
| план `BALANCE` | нет | да: перевес > гистерезиса, срез до плана (`AUTO_TRIM_PLANS`) | S | план на сайте |
| план `BUY` | нет | нет | S при недоборе > коридора (докупка); без операции — F по текущим рублям | план на сайте |
| план `WAIT` (`user_plan:WAIT`) | да | нет | F (`frozen`) | план на сайте |
| план `SELL` (`AUTO_SELL_PLANS`) | да (dormant) | да: `trim = 0` при любой доле, до проверки блокировок | вес 0 | план на сайте |

Покупка требует плана и отсутствия блокировок; продажа — только плана. Замороженная бумага — в F своими рублями (и выше плана): книга после исполнения = база.


Слова статусов — кодлист `gate_status` (`codelists.json`): `GATE_STATUS_META.label` во вьюере и `GATE_STATUS_RU` в `_shared-references/gate_status_ru.py` читают его (тест `test_gate_status_ru.py`); слова плашки/колонки — `GATE_PILL_WORD` (те же). **R27 (03.11.2026):** подписи статусов равны словам решений («наблюдать», «сократить», «докупать»), слово «гейт» на экране не пишется — только «Докупка: открыта / закрыта: причина, до даты»; «гейт» — название понятия в справке и в коде. Коды кодлистов (вердикт, приоритет проверки, `fundamental_level`, `credit_quality`, `alert_severity`) на экране — словом через одну обёртку `codeTag(list, code)` / `codeWord`, код — в `title`; проза советника на экране проходит `humanizeText` (коды, пути файлов → «разбор от дд.мм» через `fileWord`, «гейт …» → слова решения).

Гейт (закрытие докупки решением) — только по акциям; фонды и облигации решения имеют, но докупку они не закрывают (тип — реестр типов `security-types.json` при чтении, модуль (б) правило «гейт только акциям»). Бумага, переставшая быть акцией (переклассификация сборкой), гейта больше не имеет, это не продажа; её решения остаются. Вьюер: `_gateTickerLinks` открывает карточку фонда/облигации; для `divested` — «Продана дд.мм» и последнее слово, без фраз для Claude. «Продано» вьюер выводит по снапшотам в загрузке — бумага, проданная раньше самого старого загруженного снапшота, «продана» не получит (реестр типов вьюер не читает, TODO).

| Код | Подпись (`GATE_STATUS_META`) | Слово плашки/колонки | Блокирует докупку (`BLOCKING_GATE_STATUSES`) | Срок |
|---|---|---|---|---|
| `new_position` | новая, без разбора | новая, без разбора | да | нет; нет решения и **первая покупка** (`firstBuyCandidates`, колонка «Решение» на базе «к цели IE»); держимая бумага без решения не блокируется |
| `review_needed` | нужен разбор | нужен разбор | да | нет; обзор с `gate_review_required` **новее** решения; важнее `review_aging` |
| `reviewed_under_review` | наблюдать | наблюдать | да | `review_by` решения (7–180 дней; null → `recorded_at` + 60) |
| `review_aging` | срок решения вышел | срок решения вышел | да | вычисляется: `review_by` < сегодня |
| `reviewed_keep` / `reviewed_buy_more` | держать / докупать | — | нет (после BUY/ADD — пауза докупки 21 день) | `review_by` |
| `reviewed_reduce` | сократить | — | нет (советник предлагает снижать) | `review_by` |
| `divested` | продана | — | — | бумаги нет в снапшоте |
| IPO-гейт (автоматический) | вторая плашка «IPO · до дд.мм» (`ipoPillTag`, `ipo_pause_until` модуля (б)) | — | да (`ipo_gate:` в `blockingReasons`; срок — `defaults.ipo_pause_quarters` = 8) | из справочника бумаг (`ticker_class: ipo` + `listed_at`), снимается временем, разбором не снимается (вердикт «держать»/«наращивать» его не отменяет — решение владельца 28.10.2026); отличается от `new_position` (нет решения) |

Строка «Докупка» в блоке «Решение» карточки акции — `buyLineText(key)` по `gate.reasons` модуля (б) (`buyReasonsText`): не блокирует — «Докупка: открыта»; `gate:<status>` — «закрыта: <слово статуса>, до дд.мм» (`expires_on`; у `review_aging` — «срок решения вышел дд.мм, откроет разбор»; у `new_position`/`review_needed` — только слово), `ipo_gate:Nq` — «IPO-пауза до дд.мм», `add_cooldown:` — «пауза после докупки до дд.мм»; несколько причин — через «;». У фондов, облигаций и `divested` строки нет. Над ней — строка решения `decisionRowText`: «Разбор дд.мм: <слово> — исполнено сделкой дд.мм (`executed_by_trade_at`) · целевая доля · срок решения дд.мм · условий создано N» (`source.kind: owner` — «Решение дд.мм (вы)»; режим отчёта не-разбор — его слово из `mode_codes`). Источник — `decisionSourceWord` (бэкфилл — без слова: «восстановлено из истории» только подсказкой у даты в «Истории», `≈` у времени, `decisionEstimated`). Под ней `gateSayNode` — фразы для Claude: исключение из правила «команды только на «Действиях»» (решение владельца 03.11), записано в справке 6.

Влияние на базу — тот же расчёт, что в §5.6: заблокированные (`cls.blocked`: гейт, условие, IPO, план `WAIT`) входят в F неподвижно, `base = (blockedSum + dormantSum) / (1 − S)` (`compute_fixed_point_target`), `blocked_gap_rub = class_plan_rub − base_rub`. Гейт блокирует строку, только если `notAchieved` (доля ниже плана больше коридора); устаревшая оценка у бумаги не ниже плана ничего не замораживает. **Пример на снапшоте 28.10.2026** (числа на дату, устаревают; план класса 40 %). Портфель без ИИС-3 — 14,61 млн ₽, план акций 40 % = 5,79 млн ₽, акции сейчас 4,88 млн ₽. Неподвижны бумаги с закрытой докупкой (решение, IPO-пауза), под условием и планом «ждать» (список и сумма — сгиб «заморожено» под плитками). С 11.11 (§10.7 спеки trim-fix) все они — и перевешенные — в F своими текущими рублями; правило «на плане» (`frozen_at_plan`, 28.10) отменено в пользу инварианта «база = книга после исполнения». База докупки ≈ 4,55 млн ₽, то есть ≈ 1,24 млн ₽ плана не размещается — очередь до снятия блокировок, а не недобор; снимется гейт YDEX — база пересчитается. Срез OZON считается от той же базы. В справке вместо этого — пример на круглых числах (план 4 млн ₽, заблокированная бумага весом 20 % на 0,6 млн ₽; недобрана при открытых на 2,6 млн ₽ → база 3 млн ₽, не размещается 1 млн ₽; при открытых на 1,8 млн ₽ база та же 3 млн ₽ — заблокированная в F своими рублями).


### 3.5 Условия: определение (`conditions.yaml`) + состояние (`conditions-state.json`)

Две сущности с разными писателями (schema.md §3.2–§3.3), объединяет их только **модуль (а)** —
`_shared-references/conditions_merge.py` и близнец `tools/assets/conditions-merge.js` (`window.CM`, правила 1–14 в
докстринге, паритет `test_conditions_merge_parity.py`). Живой файл на mount до переключения (шаг 17) — формата 1.2;
весь код в репозитории читает только формат 2 (миграция `migrate_conditions_v2.py --decisions` — при переключении).

| Аспект | Деталь |
|---|---|
| Определение — кто пишет | только скрипт `save-to-library` `apply_condition.py` на mount сам (`--root`; `add`, `edit` — новая версия с тем же `id` и `superseded_by` у прежней; правка сработавшего условия — только с `--state-reset` (состояние начинается заново, отсрочка владельца стирается), без флага ошибка, `withdraw` — снятие с причиной; `digest`/`list`, `crosscheck`, `validate`; вход — JSON, `--by` из кодлиста `actor`). Вызывают: Режим 9 советника и сохранение отчёта (Workflow N2). Режимы 1 и 2 только читают (`digest`, `crosscheck`). Модель файл не открывает |
| Структура определения | `id`, `version`, `key`, `kind` (`review`/`trade`/`watch`), `trigger.{type, value, window_end?}` (`report_published`: окно = ожидаемая дата + 3 дня, `defaults.report_window_days`), `event_text`, `while_pending`, `on_trigger.{action, verdict?, target_pct?, text, branches?, otherwise?}` (`action` — кодлист `condition_action`), `on_expiry`, окно `not_before`/`valid_until`, `note`, `context`, `source.{kind, doc, decision_id?}`, `created_at`/`created_by`, `withdrawn`, `superseded_by`. Удалены из 1.2: `state`, `fired_date`, `touched`, `history[]`, `on_trigger.set_status` |
| **Условие владельца с сайта (no-ai-mode 2.4, 11.11)** | `POST /api/pf/condition` в hub-notify (`condition_job.py`): `add` (тикер, `date`/`price_below`/`price_above`/`event`, значение, «что напомнить» ≤ 200, `valid_until`) и `withdraw` (**только `source.kind: owner`**; чужое — 400). Определение — `kind: watch`, `on_trigger.action: notify_only`, **`while_pending.verdict: null`** (схема допускает null только у `kind: watch`: напоминание не закрепляет вердикт бумаги — `reconcile_constraints`/`_auto_stop_condition` читают `verdict_now`), `source: {kind: owner, doc: null}`, `created_by: owner`. Писатель — тот же `apply_condition.py add\|withdraw --by owner --emit --no-restamp [--owner-only]` (в процессе): `--emit` не пишет на mount, а отдаёт текст нового `conditions.yaml` и `base_digest` (sha256 прочитанных байтов); hub-notify сверяет его с хэшем hub-api (`jobs.read`) и пишет через `/api/job/save` с `base_hash` (`jobs.save_if`, JOB_WHITELIST `Portfolio/conditions.yaml`; расхождение или 409 — «повтори»), перештамповки обзора нет (`weekly-reviews/` вне записи hub-notify). Бумага — **любой тикер MOEX**: существует, если на досках TQBR/TQOB/TQCB есть цена (`fetch_prices`) или ключ есть в портфеле; ценовой проход `check_conditions_price` и монитор `_process_condition_events` держимость не проверяют. Работает в обоих режимах (`ai_mode` не читается; `--by owner` проходит гейт). Вьюер: `condAddFormNode` (форма), `buildCondAddCard` («Новое условие» на «Действиях»), `cardCondAddNode` («＋ Напоминание» в карточке акции/облигации/фонда, тикер предзаполнен), `condWithdrawNode` («снять» — карточка, окно условия, «Все условия»; только `source.kind: owner`), `condApplyLocal` (ответ сервера ложится в `state.data.conditions` без синка), `livePriceOf` для бумаги вне портфеля берёт цену из `state.live.quotes.items` (держимая позиция без цены — null), карточка бумаги вне портфеля — `outsideCandidate`: облигация (котировка доски TQOB/TQCB или поля `face_value`/`accrued_int` — `bondCandQuote`, без котировки — ключ-ISIN) — `bondCandidatePosition` (`_kind: 'bondcand'`, `cardKindOf` → `bondcand`, `CARD_SUBS.bondcand` — только «Главное»; `cardBondCandHead`: цена % номинала и ₽ за бумагу (по курсу ЦБ `quotes.fx` для валютного номинала), НКД, доходность `yield_pct` (подпись — `yield_offer_pct`), дюрация `duration_days`; «Главное» — пометка, `cardWaitNode`, `cardCondAddNode`, сбоку `cardBondCandKv`: ISIN, номинал, лот, закрытие вчера, время котировки; без позиции, доходности и решения), иначе — `candidatePosition` (`candidate: true`, фонд — как акция); строка «Всех условий» с ключом-ISIN открывает облигационную карточку. Форма при `uiAiMode() === 'off'` и «Когда: событие» показывает `.cond-add-offhint` (`COND_EVENT_OFF_HINT`: «без ИИ событие ищет только монитор с ИИ — сработает по сроку; лучше выбрать «дата» или «цена»»); при «с ИИ» — нет. Пользовательская версия — `07-conditions.md` `{#conditions}` (зеркало, SYNC). |
| Состояние — кто пишет | только hub-api: `POST /api/pv/cond/event` (сайт: `owner_mark` dismissed/deferred+`until`, `done` by owner, `reopened`, `event_found` by owner — кнопка «вышел» (R32): только у ждущего `report_published`/`event`, сервер сверяет последнюю версию в `conditions.yaml` построчным чтением `cond_def_brief` и события состояния `cond_found_check`, иначе 400; модуль (а) правило 5 переводит pending → fired, уведомитель — push «сработало: вышел отчёт … — ждёт владельца» вида `cond_open`) и внутренний маршрут hub-notify (`fired` по цене не раньше `not_before` — ежечасно по будням; `fired` по дате и окну отчёта `data.by_deadline` и `expired` — ежедневно; `event_found` + `fired` с `data.doc` из `condition_findings[]` сохранённого отчёта монитора; `done` by decision с `data.decision_id` — новое решение с `conditions_resolved[]`, только по условиям, ждущим владельца; отложенные им не закрываются). Только дописывание; повторы сервер отбрасывает (`_cstate_dup`) |
| Статус (модуль (а)) | действующее = определение не снято и состояние не терминально; `fired` без закрытия — «ждёт владельца»; `deferred` снимает «ждёт» до `until`; `done`/`dismissed`/`expired` — закрыто; `reopened` обнуляет. Дедлайны считаются и при чтении (страховка до прохода уведомителя): дата ≤ сегодня или `window_end` < сегодня → `fired` с `fired_by_deadline`; `valid_until` в прошлом → `expired`. Правило 14: новая версия определения начинает состояние заново |
| Связь с решением | решение пишет `conditions_created[]` (условия, созданные тем же сохранением, `--created`) и `conditions_resolved[]` (условия ключа, ждущие владельца — отложенные им не входят, — минус `keep_open`); уведомитель ставит по нему `done` с `by: decision`. Условие → `source.decision_id`. Журнал решений по этой связи различает `deferred_by_condition` и `ignored` (R23) |
| Связь с weekly | копия `weekly.user_constraints` — срез с `as_of`; очередь условий в MD — `render_weekly_md.py --conditions` из выдачи `apply_condition.py digest`. Срез строит `reconcile_constraints.py` советника из условий (модуль (а)) и плана владельца (`derived: true`, `as_of`, `condition_id` или `plan_field`), из прошлого обзора не переносится; валидатор обзора проверяет только форму среза (`constraint_engine.slice_form_errors`, F2.6), источником его не читает (DS-PA, 31.10) |
| Монитор | `monitor_alerts.py` берёт определения `report_published`/`event` последней версии (что ищем — `event_text`, иначе `trigger.value`; контрольная дата — `window_end`, иначе `valid_until`) → `kind: condition_event` в плане web_search; находка — `condition_findings[]` отчёта (`{condition_id, version, doc, found_at, note}`); прошлая находка той же версии переносится. Монитор состояние не пишет |
| Во вьюере | `dsCondRows` — одна точка вызова модуля (а) (определения `JSON_SCHEMA` без автодат + годовые архивы `conditions-archive-ГГГГ.yaml` + `conditions-state.json`); метки `condBadge` (ждём · сработало дд.мм (по сроку) · отложено до · срок вышел · сделано · не актуально · снято); кнопки `condOwnerButtons` (сделал / отложить до / не актуально / открыть заново — кроме триггеров `date` и `report_published`) → `POST api/pv/cond/event` с `version`, локальное дописывание события (`condStateAppend`) и пересчёт без синка; хвост `GET api/pv/cond/state?since=` при возврате на вкладку (периодического опроса нет). «Действия» → «Сделать» / «Проверить» (`_condDecisionRow`; «только сообщить» и вид `watch` — «Проверить»), «Все условия» (`buildConditionsWatchCard`), карточка — «Чего ждём» со ссылками «создано: разбор …» / «решено: отчёт …» (`condSourceNode`) |
| Реинвест (R30, 4.2.1) | `on_trigger.action: reinvest` — деньги от погашения / оферты / купонов / продажи в другую бумагу или корзину: `target` (кодлист `bond_bucket` = ключи `plan.json bond_buckets[].key`, или ключ бумаги), `amount_source` (кодлист `reinvest_source`), `text`; `verdict`/`target_pct` запрещены (`ds_schemas` правило 18). При `plan.json` в корне корзина-цель обязана быть в его `bond_buckets[].key` — иначе ошибка «корзины <код> нет в плане» `apply_condition.py add|edit|validate` (правило 20, `plan_bucket_errors`; плана нет — только кодлист). У облигации с датным триггером в день погашения или позже `set_verdict` up/flat — ошибка `apply_condition.py add|edit|validate` (правило 19, `ds_schemas.maturity_errors`; даты — `decisions_read.maturities` по снапшотам корня; нет даты — пропуск, `maturity: null`). Модуль (а) несёт `target`, `amount_source` строкой (действие — `action_code`). Вьюер: `condActionText` → «погашение → реинвест в <слово корзины>», `condThen` — без стрелки «→ вердикт» у reinvest и у датного условия ≥ погашения; сработавший — «Сделать» `reinvestDoText` + фраза `reinvestSay` (счёт бумаги-источника: `main` → режим 3, `iis_3` → режим 7, слова `mode_codes`); цель-бумага куплена после срабатывания (`dsLastTradeAt().buy`) — «Сделано» `_reinvestDoneRow` «исполнено сделкой» (событие не пишется); `set_verdict` на экране — словом вердикта (`condActWord`). Уведомитель: `cond_act_word` — «Сделать: реинвестировать погашение → …» |
| Развилка и план постановки | `on_trigger.branches: [{if_text, then: {verdict, action, target_pct?, text}}]` и `otherwise{}`; рубли и лоты вьюер считает от живой цены и базы акций (`branchSizingText`); `context.plan_pct` — план на момент постановки, плашка «План менялся» (`planChangedSince`) |

Спека — schema.md §3.2–§3.3 (`docs/investment/_cross-cutting/data-structures/`); прежняя —
`docs/investment/portfolio/claude-code-spec-conditions-and-reconcile.md` (история).
Пользовательская версия — `07-conditions.md` `{#conditions}` (зеркало, SYNC).

---

## 4. portfolio-integrated-view — зачем и какие выводы

**Read-only синтезатор.** Собирает три артефакта (snapshot + stress +
weekly-review) в единую картину **expected return на горизонтах 6-12-24 мес
side-by-side (primary 12 = «1 год») с Monte-Carlo доверительными интервалами**. Не
пересчитывает данные, **не даёт buy/sell рекомендаций**, не строит прогнозов.

### 4.1 Что считает (на каждый горизонт `hNN`)

Для каждой позиции — блок `by_horizon.{hNN}` (h6/h12/h24); плоские поля = primary (h12):

```
total = macro + (dividend | bond carry) + idiosyncratic α      [точка — аналитич.]

macro   — из stress.per_position.by_horizon[hNN] (сценарный ΔP&L этого горизонта).
          L2 (expected_pct_pweighted из stress) ИЛИ L1 (Σ β×движение из macro-marginal,
          MFC-4: level_l1_<год>+unit → % от baseline_spot; coherence_gap = |L1−L2|).
div     — из weekly-review (div_yield × h/12) или bond carry (базис × eff_months/12;
          eff_months capped до оферты/погашения, при ytm>60% базис → coupon_pct, |carry|≤50)
idio α  — из catalyst-деревьев обзора, фильтр in-horizon по date_window (§11.3);
          joint P через active_scenarios/macro_dependency, trust- и source_quality-дисконты
```

На уровне портфеля (per horizon): **equity-EV vs bond-EV vs spread**.

**CI — Monte Carlo (Фаза 4, V2-B, default `ci_method: mc`):** 10k путей, на каждом
ОДИН сценарий разыгрывается для всех позиций/катализаторов сразу → корреляции
учитываются честно (без `corr_matrix`); spread — единый CI из joint-сэмплов. Точки
остаются аналитическими; guard `mc_divergence` при расхождении точки и центра CI >1.5 п.п.
Режим `--ci-mode analytic` возвращает прежний двойной spread-CI (corr=1 / corr=0).

**Coverage-инвариант:** макро-прогноз FCA должен дотягивать до горизонта анализа.
Год нужного горизонта нет → `compute_horizon_factors` берёт ближайший + инфлирует CI
×√(h_target/h_source) + warning (`extrapolated`); consumer делает fail-fast, если
запрошенный горизонт вообще отсутствует в stress.

### 4.2 Что НЕ делает (важно для интерпретации)

- §2 (equity vs bond spread) — это **macro-context, НЕ вердикт**. Не «облигации
  впереди → нарасти bonds». Decision frame — это per-position вердикты в
  `weekly-review` и `tactical-rebalance` (режим 3).
- Не цитирует action items (лимитные заявки, лоты, ценовые уровни) — только
  verdict-pointer как навигационный ярлык.
- ИИС-3 позиции (`on_iis: true`) — метка ❄, никогда не SELL/TRIM.

### 4.3 Главная ценность

Подсветка **disagreement zones** — где стресс (макро) и обзор (фундаментал/идио)
расходятся. Именно сюда попадает кейс вроде OZON. Плюс блок
`predictions_for_review` (≥5 проверяемых предсказаний с датами) для будущего
ретро-аудита.

---

## 5. Вьюер: разделы и источники данных

Файл `tools/portfolio-integrated-viewer.html`. Загружает артефакты из
`Claude-Memory/` (HTTP autoindex или drag-and-drop). Разделы появляются только
если есть соответствующие данные (`buildTabs()`). **С v3.0 (2026-10-12, TODO_design §1)**
вьюер — на общем ui-kit: строка разделов `uiTabsHTML`/`uiTabsMount` (без эмодзи; редкие —
`more: true` → список «Ещё ▾»), имя раздела `.ui-h1` + строка «данные на …» (`tabLead`),
плитки `kpiTile` (`.ui-grid.kpi`/`.ui-big`, мини-график `sparkNode` — 6 мес по календарю),
карточка бумаги `openCard` (см. 5.0). Старые id вкладок — псевдонимы `TAB_ALIASES`
(`watchlist`/`action-queue` → `actions`, `forecast-l2`/`predictions` → `forecasts`).
Полоса горизонтов — под строкой разделов и только в `HORIZON_TABS`
(Акции, Стресс, Интеграционный). На «Динамике» (v3.1.0) и «Облигациях» (v3.4.0, сигнал дюрации) горизонт — сегментом `horizonSegNode` в самом блоке (тот же `setHorizon`, что у полосы). Липкие элементы отсчитывают от `--stick-h` (на телефоне шапка с кнопками уезжает: `--chrome-h − --hdr-h`); широкая таблица на телефоне — липкая копия шапки `uiTableStickyHead` (ui-kit 1.43.0, зовёт `syncTabwrapScroll`); перерисовка того же раздела сохраняет `scrollLeft` таблиц (`renderTabContent`). В шапке — кнопка **«❓ Справка»**: грузит и рендерит
части справки (§5.7; пользовательская инструкция). **Офлайн** (v3.49.0, ui-kit 1.54–1.55): вьюером управляет `portfolio-sw.js` (push) с общим ядром
`sw-offline.js` (как `sw.js` остальных страниц): оболочка «сначала сеть», данные из `CAB_KEEP` (без
`Portfolio/reports/`, `domains/`) — копия с меткой пароля; `/api/pv/sync` (POST) ядро пропускает как есть,
пока не знает, что связи нет (ядро 1.2.0: метка в кеше `cab-state-v1` после первого таймаута — тогда ≤1,2 с,
иначе сетевая ошибка); без
связи вьюер берёт свою копию `FileCache` (`piv-files`) — в ней все файлы вьюера, отчёты и аудиты тоже. Хаб раз в 6 ч прогревает страницы в невидимом
фрейме (`uiOfflineWarm`). Без связи (v3.50.0: `navigator.onLine === false` или сеть упала на
`/api/pv/sync`; v3.51.0: ещё проба входа `ensureAuth` пришла из копии ядра — заголовок `X-Cab-Saved` — или
не ответила за 10 с → `state.offline`; на телефоне `onLine` бывает `true`, а запросы висят) — `loadFromDevice`: всё из `FileCache` без сверки, плашка ui-kit `uiOfflineShow`; живые цены при `state.offline` сами не запрашиваются. Сторож — `tools/tests/test_offline.py`. **Только с сервера** (v3.48.0): локальные режимы
`file://` (выбор папки/файлов, перетаскивание) и ссылки `?view=<integrated-view>` удалены, `state.mode`
всегда `'http'`, «Обновить» — `refreshPage` (сторож — `test_pages_contracts`). **Загрузка с сервера** (`loadHttpMode1`, v3.46.0–3.47.0): сначала **один запрос**
`POST /api/pv/sync` (`pvSync`, hub-api `pv_sync`, pv-sync@1): вьюер шлёт `have` — версии своей копии
(`s:размер:mtime_ns`), сервер отвечает папками `PV_DIRS` (= `dirs` вьюера, сторож — `test_write_api`)
и содержимым только новых/изменившихся, пачками до 6 МБ (`more` — повтор). Нет ручки (404), пароля,
сбой — дальше путь 3.46.0: листинги — JSON Caddy
(`Accept: application/json`, `cache: no-store`; имя, размер, `mod_time`), файлы — сверка с копией на
устройстве `FileCache` (IndexedDB `piv-files`, запись `{path, folder, name, ver, fp, text}`):
`ver = size|mod_time` совпала — файл не запрашивается, иначе качается (`fetchNoCache` = `cache: no-cache`,
без метки в адресе; неизменившийся у браузера — 304). Не больше `NET_LIMIT` (8) запросов разом
(`runPool`), таймаут `NET_TIMEOUT_MS` (30 с) вместе с телом и один повтор (`fetchTextRetry`). Листинг
не ответил / файл не скачался — копия с устройства + предупреждение «показана копия»; копии нет —
«Не загрузилось» (`reportHttpLoadFailures`). Копия привязана к токену (`fileCacheMark` = `uiAuthMark`):
чужая метка — стирается; файлы, пропавшие из ответивших листингов, — тоже. HTML-листинг (без версий,
тестовые серверы) — файлы качаются всегда. Итог прогона — `state.netStats`. **«Обновить»**
(`refreshFromHandle`, v3.39.0) в http-режиме — `location.reload()`, раздел и прокрутка возвращаются
(`sessionStorage['piv-reload']`); метки `piv-cb` с v3.46.0 нет (стирается). Второе нажатие за
`FULL_RELOAD_MS` (60 с, `localStorage['piv-refresh-at']`) ставит `sessionStorage['piv-full']` →
следующая загрузка очищает копию и качает всё. Ручной сброс кэша браузера (Option+Cmd+E) не нужен: двойное «Обновить» в течение `FULL_RELOAD_MS` делает полную перекачку. **При правке справки — синхронизировать с этим документом** (правило синка выше).

**Глобальный селектор горизонта (v2.0, Блок C).** Под строкой разделов — сегмент-контрол
`[6 | 12 ★ | 24]` с датами из `horizon_ends` (★ = `primary_horizon`). Источник —
`stress.horizons` (fallback — frontmatter integrated-view); v1/одногоризонтные
артефакты → задизейблен. Выбор в `state.horizon` + `localStorage('piv-horizon')`,
смена вызывает `renderTabContent()`. Хелперы: `getHorizonMeta`/`currentHorizon`/
`hKey`/`hSlice` (срез `by_horizon[hN]` с fallback на плоские поля).
Вкладки читают выбранный горизонт:
- **Акции** (`wrToPositions`): macro из `per_position.by_horizon[hN]`, дивиденды
  ×N/12, фильтр катализаторов через `catalystInHorizon`/`dateWindowStart`
  (`date_window` ≤ конца горизонта — замена удалённого в v2 `in_horizon`);
  tooltip «Итого» — `totalByHorizon`.
- **Стресс** (`renderScenarios`): worst/best/Δ и факторы из `*_by_horizon`;
  строка горизонтов с флагом экстраполяции из `caveats`.
- **Стресс** (`buildStressStrip`, с v3.0 сверху раздела, раньше — на «Сегодня»): критические/стабильные из `by_horizon[hN]`.
- **Интеграционный** (`extractEquityBondByHorizonV2`): график §4 на выбранном
  горизонте; fuzzy-фоллбэк удалён (нераспознанный §4 → честный отказ).
- **Динамика** — две панели: (1) `buildExpectedHistory` → `extractEquityBondForView`: §4-парсер
  по всем `integrated-view-*.md` → линия equity/bond/спред **ожидаемой** доходности вперёд
  (следует за селектором горизонта; нераспознанные → «пропущены», иной-горизонт → оговорка);
  (2) `buildXirrHistory`: **реализованная** XIRR из снапшотов → годовых, на дату снапшота —
  акции/облигации (`returns.by_type`, активная часть) + два портфельных среза: **активная часть**
  (`returns.restricted.xirr`) и **вся история** (`returns.total.xirr`, с первой операции, ВКЛ. заблокированные с
  фев-2022 иностранные бумаги, оценённые в 0 ₽ (`--blocked-value zero`) — мёртвый капитал тянет
  money-weighted XIRR вниз; именно поэтому total ≪ компонентов). Плитка «Доходность активной части» на «Сегодня» с 3.45.0 — живая: `liveReturns` решает XIRR по `returns.live_basis` снапшота (потоки по дням + позиции) с конечной стоимостью на живых ценах MOEX (акции и фонды — qty × цена, доска TQBR — там и фонды, TQTF закрыта; облигации с оценкой по MOEX — qty × (цена/100 × номинал × курс + НКД в ₽) котировки, доски TQOB/TQCB, курс 1 у рублёвых, у валютных — курс ЦБ из `quotes.fx` (нет курса или НКД не в рублях — по снапшоту); заблокированные, FINAMAR — по снапшоту), дата конца — сегодня; на ценах снапшота даёт ровно `returns.*.xirr` (`test_viewer_live_xirr.py`); нет блока — XIRR снапшота. Тем же уравнением `liveReturns` пересчитывает и строки: бумагу (`live_basis.flows_by_ticker` — `cashflows` записи per_security без терминала, под ключами `per_instrument_xirr`; у бумаг на двух счетах — `flows_by_ticker_account`), тип (`flows_by_type` — потоки `subportfolio_metrics`, терминал = Σ живых стоимостей незаблокированных позиций типа), ИИС-3 (`returns.by_account.iis_3.live_basis` — потоки и позиции расчёта счёта; перенесённый `carried_from` не считается). `liveApplyReturns` кладёт результат в копию снапшота с живыми ценами (`per_instrument_xirr[*].xirr/pnl_rub/market_value_rub` + `live_ret`, `returns.by_type/total/restricted`, `by_account.iis_3.fact`); `snapParsed` (ряды «Динамики», дрейф) читает исходный. Нет новых полей (снапшот до 11.11.2026) — итог пересчитывается, строки остаются по снапшоту. «Динамика» — по снапшотам, живые цены её не трогают. Панель объясняет разрыв; с 3.43.3
  внизу — блок «Какая доходность какая» (`.xirr-legend`, кегль `.bench-row`): активная часть — основная,
  вся история — строгая, IntelInvest выше, потому что оценивает замороженные по рынку (сверено
  2026-10-22: те же потоки IntelInvest с замороженными в 0 дают 2,99 % против 2,96 % у скрипта). Две панели намеренно раздельны (прогноз-вперёд
  vs факт-назад, полная-за-горизонт vs годовых) — оси подписаны явно. Общий рендер — `drawLineChart`. Без сети.

| Раздел | Render-функция | Главный источник | Что показывает |
|---|---|---|---|
| Сегодня | `renderToday` | все | плитки (`buildTodayTiles`: портфель · `returns.restricted.xirr` + мини-график · «требует внимания» = `actionCounts().attention` = «Сделать» + «Проверить» блоков `actionBlocks()` (пачка 3 читаемости, 4.2.0); то же число — на ярлыке «Действий» и в шапке «Действий» · купоны+погашения 12 мес); `buildStaleAlert` (устаревшее; при пустом списке и `stressNewerList()` — «файлы свежие; стресс на заменённом прогнозе …»); с 3.60.0 (решение владельца 27.10, план §7.4–7.5) — `buildUpcomingCard` («Ближайшие 30 дней»; 3.62.0: единственная выплата дня → `openCard` облигации по ISIN; 3.63.0: несколько → раскрытие `up-sub` по бумагам (`items`), каждая → карточка; условие без позиции в `buildPositionByTicker` → `showConditionModal` на общем `condCardNode`, тот же путь у строк «Действий»: `bond_cashflow_calendar.detail` + даты условий `trigger/valid_until/not_before` + `valid_until/cooldown_until` гейтов + катализаторы с окном, одним списком по датам) и `buildMoversCard` («Движение за неделю»: `currentPort()` против записи `portfolioHistory` не позже чем за 7 дней до текущего снапшота, стоимость — Σ `holdings[].value_rub`, цена и вклад в ₽ по тикеру, топ-3 вверх/вниз); убраны с «Сегодня» `buildFiredConditionsCard`, `buildVerdictCards`, `buildWatchlistHighStrip`, плашка `computeDurationSignal` (их место — «Действия» и «Облигации»; функции остаются) |
| Режим «без ИИ» (11.11) | `buildTabs` | `uiAiMode()==='off'` | вкладки без ИИ-обновления (`forecasts`, `sources`, `dashboard`, `diff` — только из обзоров) уходят в «Ещё» группой «Архив ИИ» (`group`/`menu` у пункта, `uiTabsHTML` печатает заголовок группы), дата — `noaiArchDate` (самый свежий `rec.date` вида); `scenarios` — по `noaiStressDate` = max(дата сценариев, `recalc.at` пересчёта сайта) ≤ `NOAI_STRESS_DAYS` (60) на полосе, плашка `noaiStressNote` в `tabLead` («сценарии от ДД.ММ, позиции свежие»), старше — в архив; `#tab=…` на ушедшую вкладку открывает её (`renderTabs` ищет по полному списку) |
| Акции | `renderPositions` **3.80.0:** `wrToPositions` добавляет строки `noReview: true` для акций снапшота (`asset_type=stock`, `account!=iis_3`, `current_price_source!=cost_basis`, `qty>0`), которых нет в `per_stock`; `raw: {}`, вердикт/приоритет/гейт пусты; из `sumW`/ожидания и итога таблицы исключены. `renderIeModel` добавляет тикеры таких акций в `tickers` (доля — от стоимости), т.к. `ie_actual.per_ticker` в режиме без баланса переносится из прошлого снапшота. | `weekly-review-stock` + решения (модуль (б)) + снапшот | плитки `buildStocksTiles` (сумма/доля · `by_type.stock.xirr` и `restricted.xirr` с мини-графиками · вес-взвешенное ожидание); таблица: бумага (`.ui-name`), кол-во и стоимость (снапшот без ИИС-3; ниже — `weight`), XIRR, сектор, фундаментал, вердикт (+ `сейчас → при срабатывании` из conditions, gate-badge), ожидание за горизонт (подсказка — `partsByHorizon`: макро/дивиденды/идио + итоги других горизонтов), «Ожид. IE 12 мес» = `ie_model.growth_potential_12m_pct` как есть (ниже `growth_potential_lt_pct`). Фильтры `buildPositionsCard` (3.78.0) — общие `filterChipGroup` («Вердикт», «Приоритет», «Решение» с «без оценки» = `__none__`) и `filterChipCheckbox` («только с ограничениями»), со счётчиками, как у облигаций и фондов; сектор — список. Поиск — `_tableSearch` (поле `.ui-q` в шапке карточки: прячет строки, итоги и листание карточки — по видимым; телефон — к верху экрана с удержанием высоты) и `_filterTools` (телефон: окно-шторка по «Фильтры (N)», «Сброс»); то же на «Облигациях». `verification_priority` (DERIVED, CR-C: HIGH=действие сейчас/review-pending · MEDIUM=отложенное действие/conf<0.6 · LOW=устоявшийся HOLD; `compute_verification_priority`) — фильтр и метка карточки |
| Фонды (3.76.0, после «Облигаций», при `fundRows().length` или `plan.funds`) | `renderFunds` | снапшот `holdings[asset_type=fund, qty>0]` + `per_instrument_xirr` + `balance_summary.class_plan_vs_fact` + `state.plan.plan.funds` | одна таблица `.ui-table.dense.fd-t` в карточке с `_tableSearch('fundsQ')`, фильтрами `_filterTools('funds')` (`state.filterStates.funds`: `cls` — чипы `_fundChipGroup`, `__none` = без класса; `reb` — только `in_rebalance !== false`), сортировкой `th[aria-sort]` (`state.sortStates.funds`, по умолчанию стоимость). Колонки (3.83.0, порядок): фонд (имя · тикер · «оценка вручную» если `current_price_source` не `moex_iss`/`moex_live`) · класс (подстрока `в балансировке`/`вне балансировки` из `in_rebalance`, `.fd-none` — warn) · кол-во · цена (`livePriceOf`; подстрока `моя N ₽` — `holding.avg_cost_rub` основного счёта, иначе `buy_total_rub / qty_now` при `n_sells === 0`) · стоимость (`value_rub`; подстрока `N % портфеля` — доля от `balanceBase()`; колонки «Доля, %» и «В балансировке» убраны, суммы процентов в подвале нет) · «К плану» (3.82.0: «факт → план» самой узкой группы; фонд класса «Облигация» с корзиной — план `planClassPct × bucketPlanFactRows().rowOf(bucket).plan / 100` и факт `aRub / total`, остальные — `planClassPct` и `class_plan_vs_fact.actual_pct`; подстрока `.fd-nb` — имя группы и соседи из `fundRows()` / `bucketMembers` / `cashSplit` только при непустом списке соседей (3.83.0); отклонение вынесено в колонку «Отклонение»: `_planFactDev(planPct, factPct, grpRub, total)` — `b.ui-num` «+7,07 %» (`rb-devn out` вне коридора), подстрока ₽; `grpRub` — `aRub` класса из `classPlanFactData()` или корзины из `bucketPlanFactRows().rowOf`; вне балансировки «—»; сортировка по `dev`). `fundRows` с 3.82.0 считает только основной счёт (`account !== 'iis_3'`); фонд только на ИИС-3 в таблицу не попадает. `.ui-name > b.good/.bad` и `> .ui-sub.good/.bad` в viewer.css перебивают ui-kit (цвет доходности) · доходность (`per_instrument_xirr[t].xirr`, `pnl_rub`; у ручной оценки нет) · заметка (`.ui-ell`). Телефон (3.83.0): остаются фонд · стоимость · «К плану» · доходность; `hide-mobile` у класса (уходит подстрокой имени `.fd-cls-m`), количества, цены, отклонения, заметки; `.fd-nb` скрыта, отступы ячеек 2px, чтобы таблица влезала в 390 px. Плитки `buildCashTiles(cashSplit())`: деньги — `cash.by_account.main`, фонды денежного рынка — фонды основного счёта с `plan.funds[T].class === 'Кеш'` (без плана — `cash.cash_equiv_tickers`), «Кеш всего» против плана класса. Клик/Enter → `openCard(fundEntries()…)`; `_fundRefresh` перерисовывает вкладку (`#funds-table`). Карточка фонда: подвкладки main/ret/hist, `ret` = `cardFundRet` (вложено `buy_total_rub`, средняя цена, срок от `first_trade_date`, XIRR + общий с акцией блок `cardPnlNodes`; без `per_instrument_xirr[t]` — `card-empty`). **3.83.0:** схема `plan.funds[T]` — `class · currency · in_rebalance · bucket · note · fee_pct · spread_pct` (комиссия % в год и спред %, число ≥ 0 или null; `PLAN_FUND_FIELDS`, правило `funds.<T>.(fee_pct|spread_pct)` → `_plan_nonneg_num`, импорт JSON берёт поля из `PLAN_FUND_FIELDS`, XLSX «Фонды» — колонки «Комиссия, % в год», «Спред, %» после «В балансировке»); во вьюере — инлайн-поля `_fundPctFld` в `cardFundMain`, в таблице не выводятся. `lockPlan` (карточка с «ИИС-3» и фонд есть на основном счёте, `qty > 0`) блокирует селекты и чекбокс; фонд только на ИИС-3 — поля активны. **3.77.0:** `cardFundMain` «Позиция» — порядок как у акции (`cardStockKv`): Стоимость · Количество (`lot_size` подстрокой) · «Моя средняя» (`hold.avg_cost_rub`; пусто и `per_instrument_xirr[t].n_sells === 0` → `buy_total_rub / qty_now` без подписи (с 3.81.0); при продажах без поля — строки нет) · `cardPnlNodes` (не для оценки вручную) · Цена · Счёт · Источник цены. **3.82.0:** `classPlanFactData()` вычитает из `aRub` класса и из базы фонды основного счёта с `plan.funds[T].in_rebalance === false` (результат несёт `excluded: [{ticker, value, cls}]`, `aPct` пересчитан от новой базы; снапшот и загрузчик не меняются); `balanceBase()` — та же база для «Доля, %», «К плану» и плитки «Доля портфеля»; `cashSplit().classFact/classPct` — из строки «Кеш» этих данных; плитка «Общих долей» — «База балансировки». `fundInfo(t, account)` (`'main'` — холдинги `account !== 'iis_3'`, `'iis_3'` — холдинги счёта; `accts` всегда по всем счетам). На «ИИС-3» `_iisRows` строит для фонда `pos = {_kind:'fund', ticker, name, onIis:true, _iis:{qty, value, share}}` — строка кликабельна, карточка фондовая с числами счёта (плитка «Доля счёта», тег «❄ ИИС-3»), в `cardFundMain` при `onIis` кнопки `.ui-select-btn` и чекбокс «В балансировке» disabled, заметка активна; `per_instrument_xirr[t]` по тикеру (сделки всех счетов) — плитка подписана «по сделкам обоих счетов», если фонд лежит на обоих. Фильтры — общие `filterChipGroup`/`filterChipCheckbox` (верхнего уровня; ими же `renderBonds`, классы `fl-group`/`fpill-label`/`chip-toggle`). **3.86.0:** `filterChipCheckbox('с ИИС-3')` (`state.filterStates.funds.iis`, по умолчанию false) добавляет `iisRows` — фонды `holdings[account=iis_3, asset_type=fund]`, которых нет на основном счёте; строка с `iis: true` (числа счёта, `tag soft` «ИИС-3», «К плану»/«Отклонение» «—» · «ИИС-3 вне целей», без доли), клик → `{_kind:'fund', onIis:true, _iis}`; поле `chg` строк и `snapH`/`sp` убраны; колонка «К плану» `min-width:215px`, «Заметка» скрыта ≤1199px. Флаг `manual_value_stale` (assemble_snapshot, режим сделок с планом): количество ручной позиции по сделкам изменилось против прошлого снапшота, а `value_rub` в плане прежний, либо `plan.manual_positions[].value_as_of` раньше последней сделки (`per_security[T].last_trade_date`) — один флаг на бумагу, первая ветка приоритетнее; в `ATTENTION_FLAGS`. Карточка фонда: под полем «Оценка вручную» подпись «оценка от дд.мм.гггг» (`_fundManualNode`). `--record` кладёт `plan.json` в `caches-start/plan.json`, `--replay` без `--plan` берёт его оттуда. |
| Облигации | `renderBonds` | `weekly-review-bond` + снапшот **11.11:** YTM и дюрация строки — живые (`liveApplyBondYields`: quotes@1 `yield_pct`/`duration_days` → `holding.ytm_pct`/`duration_days`, `ytm_live`; прежние — `ytm_snapshot`/`duration_snapshot`), у бумаги без котировки — обзор/снапшот, подпись `ytmSrcNote` («по снапшоту ДД.ММ»); плитка средневзвешенной YTM — по живым YTM и живым стоимостям строк (`ytmTileSrc`); карточка, «YTM MOEX» на ИИС-3 и светофор дюрации (`computeDurationSignal`) — то же; в `rebalance-engine.js` не заходит **3.74.0:** `buildBucketsFold` — сгиб `details.ui-fold` «Корзины: план ↔ факт» (свёрнут; строка на корзину, без правки; ссылка `goToTab('ie-model')`; план из `plan.bond_buckets`; **3.76.0:** факт — общий `bucketPlanFactRows` (сумма `bucketMembers(key)` по текущим ценам, база — сумма девяти корзин; `balance_summary.bonds_plan_vs_fact[]` — запасной вариант, когда в снапшоте нет облигаций в `holdings`), отклонение факт − план во вьюере); фильтр «Корзина» (9 ключей) — `state.filterStates.bonds.bucket` по `holding.plan_bucket_key` (`bucketKey` строки), входит в счётчик и «Сброс»; правка корзин — на «Долях и целях». | **только `account != iis_3`** (ИИС-3 — `renderIis`; бумага из обзора, лежащая лишь на ИИС, скрыта и посчитана в шапке таблицы). `buildBondTiles(rows)` и `buildBondDistributions(rows)` считают по строкам таблицы (стоимость снапшота × YTM/дюрация/тип/качество обзора), не по `summary` обзора (там main+ИИС); доля портфеля — от `total_current_rub_excl_iis`; `by_type.bond.xirr`; сигнал дюрации — без ИИС; таблица: тип · кол-во · стоимость (доля облигаций) · к погашению · «Погашение» в две строки (`_bondMatCell`) · качество · вердикт |
| ИИС-3 | `renderIis` **3.80.0:** `iisCashTile` — `cash.by_account.iis_3`; подпись «факт» при `cash.iis_source == owner_intelinvest` (у балансового снапшота без `cash.source` — по `fact_date`), иначе «оценка · из снапшота». | снапшот `returns.by_account.iis_3` + holdings `account=="iis_3"` | `fact.xirr` · `forward.account_pct`/`bonds_irr_pct` · `locked.bonds_irr_pct` · стоимость; `per_bond` (forward/locked/real/moex_ytm); `status: mismatch` → предупреждение без чисел; кнопка — последний `advisorReport` с режимом 7 во frontmatter `mode`/`modes` (`_isIisReport`/`_latestIisReport`, v3.6.6; заголовок не учитывается; `iis3` в имени — только у старых отчётов без `mode`; конвенция — `skills/ru-portfolio-advisor/references/adhoc-save.md`). Нет блока → плашка «нужна выгрузка БКС (Шаг 4б)». Плитка «Дюрация облигаций» — `_iisDuration` (по стоимости, фонды не входят); таблица `_iisRows` — сортировка, «Погашение» `_bondMatCell`; карточка со строки — `pos._iis` (кол-во, стоимость, доля счёта, `locked_pct` вместо XIRR основного портфеля) |
| Выплаты | `renderPayouts` | снапшот `bond_cashflow_calendar` + `weekly-review-stock` | 3.59.0: переключатель счетов `state.payoutsAcct` (`all|main|iis_3`, localStorage `piv-payouts-acct`), `payoutsCalendarFor` строит `by_month` счёта из `detail` × доля qty счёта (как `cardBondPay`), при `iis_3` дивиденды не рисуются; купоны+погашения по месяцам `.ui-cols.ro` (24 мес, дальше 12 — бледно), таблица месяцев в `<details>`; дивиденды за 12 мес — `computeDivEstimate(12)` (та же формула, что total return: `divForwardAtHorizon` × стоимость; гейт policy_state). Заменил «Денежный поток»/«График погашений» облигаций и дивидендную полосу акций |
| Динамика | `renderHistoryTab` | `integrated-view` (≥2) и/или снапшоты (≥2) | панель 1: equity/bond §4 ожидаемая (следует за горизонтом; при `uiAiMode() === 'off'` не рисуется — новых прогнозов без ИИ нет); панель 2: реализованная XIRR stock/bond/total из снапшотов (+ линия по дням при дневном ряде и `live_basis`); панель «Стоимость портфеля» (только при дневном ряде); **3.107.0 — панель 3 «Помогает ли система»** (`decisionJournalCard`: `Portfolio/decision-journal/{baselines,journal}.json` + последний `report-ДАТА.md` — классы `djBaselines`/`djJournal`/`djReport` в `classifyByName`, папка в `loadHttpMode1` и `PV_DIRS` сервера; `journal.json` разбирается до `as_of`/`summary`/`flags`; «Мой факт» = `b3.twr_ann`, базы B0 / B1 / B2-live — `bases[*].twr_ann`, `b3_minus_base_pp_ann`, `b3_minus_base_rub`; вердикты — `summary.{stock,bond}.hits_3m_clean / matured_3m_clean`; строка «пока шум» — до `DJ_CHECKPOINT` 2027-01-06; нет файлов — блока нет; вьюер ничего не пересчитывает); смена `returns.parameters.bond_value_basis` (нет поля = `clean` → `dirty` с 13.10.2026) — вертикальная отметка «облигации с НКД» (`buildXirrHistory().marks`, плагин `vMarks` в `drawLineChart`) + строка под графиком (v3.34.0); локально, без сети (Chart.js) |
| Стресс | `renderScenarios` | `stress-*` + `scenarios/*` | v3.1.0 от общего к частному: плитки (ожидание по весам / худший / лучший / разброс п.п.) → Δ по сценариям (Chart.js) → карточки сценариев (веса, факторы, 🔭) → `buildStressPositions` (критичные в худшем, устойчивые, top risks) |
| — | **4.3.0: правка плана без связи.** `GET api/pv/plan` держит офлайн-ядро (`sw-offline.js` 1.4.2+, приватно); правка — только `planEditable()` = `plan.status === 'ok' && !state.offline`; `setOffline()` ставит `html.pv-offline`, CSS прячет `[data-plan-edit]`, поля плана — текстом (как при незагруженном плане), подсказка `PLAN_EDIT_HINT.offline`. **4.4.1:** связь вернулась — `setOnline()` (по `cab-online` фонового скрипта или `probeOnline()` на `online`/возврат на вкладку: `GET api/pv/plan` ответил сервер, не копия) снимает признак, перечитывает план и перерисовывает раздел | — |
| Действия | `renderActions` | строки модуля (а) (`dsCondRows`: определения + состояние) + модуль (б) (`lwCard`: решения и обзоры) + мой план (`currentPort().ie_actual.per_ticker` после `planApplyAll`, журнал плана) + «Сейчас» движка (`nowAutoResult` → `RebalanceEngine.runAuto`) + `monitor-report` + forecasts/scenarios входов действующего стресса | шапка `actionsHeadText` («Действия · дд.мм · N сделать · M проверить · K ждём · L к сведению», нули скрыты) и пять блоков (4.2.0, пачка 3 читаемости, F1; отнесение — `actionBlocks()`, только по полям, прозу не разбирает): **Сделать** (`#act-do`) — `_condsAwaiting` вида сделка/разбор (`_condDecisionRow`, кнопки `condOwnerButtons`), вердикты `_actionItems` с `verdict_direction` up/down без ждущего условия (`_verdictRow`; решение с `executed_by_trade_at` — в «Сделано»), строки плана `_planActRows().act` (`user_plan_direction` up/down или BALANCE с операцией; `user_status` не DONE/ORDER/DEFERRED; `direction` buy с `lots ≠ 0` или trim) — `planOpText`, ссылка «Доли и цели →» (та же бумага с вердиктом — одна строка, план первым, фразы нет), стресс на заменённом прогнозе (`stressNewerList()` по `forecastNewer`, фраза `STRESS_RERUN_SAY`), монитор HIGH/MEDIUM по R20 (`_forecastActionable`), устаревшие отчёты `_actStaleList`; **Проверить** (`#act-check`) — пункты `verification_checklist` строк HIGH без направления (`_checkRow`, «сделал» → `localStorage['piv-check-done']`, 14 дней), план `user_status: ORDER` («заявка стоит с дд.мм — исполнилась?», дата — `_planStatusSince` по журналу; «сделал» → `POST api/pv/plan/set` `user_status: DONE`), условия «только сообщить»/`watch`; **Ждём** (`#act-wait`) — вердикты с направлением и ждущим условием, план «стоит» (`planWaitText` → `reasonRu`), план DEFERRED, ждущие условия по бумагам портфеля (`_condsWaiting` + прочие `pending`, `snapshot_keys`), `verification_checklist` и `catalyst[].trigger · date_window` строк MEDIUM/LOW без направления (`_noteRow`, не больше трёх строк); порядок `waitRowsOrdered` — с датой (срок условия, `unblock_by` плана) по возрастанию, затем без даты, на виду `WAIT_SHOWN` = 6, остальное — `details.act-wait-more`; условия одной бумаги — `_waitCondsRow` одной строкой через «;»; план DONE старше 7 дней по журналу при операции «Сейчас» — снова в «Сделать» (`doneAt`, «отмечено сделанным дд.мм, но по плану ещё …»); **К сведению** (`#act-info`, свёрнуто) — тикеры строк без направления и не HIGH (кнопка → карточка), справочные предупреждения монитора; **Сделано** (`#act-done`, свёрнуто) — `_soldRow`, `_executedRow` (`executed_by_trade_at` за 30 дней), план DONE за 7 дней, `_replacedRow`, отмеченные проверки, условия, закрытые за 30 дней, сделанное по монитору. `actionCounts()` — `{do, check, wait, info, done, attention = do + check, high, stale, blocks}`. Интегрированный вид строк не даёт (R19). Журнал плана грузится лениво (`planJournalEnsure`). Пользовательское зеркало — `04-tabs.md`, `05-now.md`, `07-conditions.md`, `03-fresh.md` |
| Изменения | `renderDiff` → `renderDiffStock` / `renderDiffBond` | текущий + прошлый `weekly-review` (акции) или `weekly-review-bond` (облигации) | счётчики плитками; v3.1.0 — строка на бумагу (`DIF_COLS`) со всеми изменениями; клик — карточка, катализатор — `openCard(pos, list, {sub:'cat', focus:{тикер:id}})` с подсветкой `.catalyst.hl`. v3.106.0 — сегмент `.diff-seg` «Акции · Облигации» (`diffKinds`/`diffPick`: вид выбран ссылкой `#tab=diff&kind=bond&date=ГГГГ-ММ-ДД` из push или свежестью обзора); у облигаций вердикт словами, качество, доля от `DIF_WEIGHT_PP` (0,25 п.п.), новые/ушедшие; смена по решению владельца (`ownerDecided`: сделка в `trades_since_prior`, закрытое условие, «владелец купил/отклонил» в основании) — пометка «после твоего решения ДД.ММ»; то же правило — `owner_decided` в notifier.py С 3.120.1: без ссылки открыт период «→ сейчас» (`diffIdx` → 0), пара — только по `date` из ссылки; заголовок группы в `diffBetweenNode` — кнопка `.dif-evt-open` → `openCard(pos, список бумаг блока)` (бумаги вне `buildPositionByTicker()` — не кликабельны). С 3.108.0: список выбора (`uiSelectNode`, `state.diffDate`) и стрелки «← старее · новее →»; смена вида сбрасывает дату. **3.120.0, периоды:** `diffPeriods(k)` — первым `{id:'now'}` («дата последнего обзора → сейчас», без сравнения), затем пары `list[j]` против `list[j+1]`; `diffIdx` без ссылки открывает свежую пару, кнопка «Сейчас» (`data-act=diff-now`) ставит `state.diffDate='now'`. Блок «Между обзорами» (`diffBetweenNode`) — события `securityEvents({kind, from, to, ticker?})` за (from, to]: `report` (отчёт по шапке `report@1`), `gate` (файлы решений `decisions/` бумаги, `recorded_at`), `cond` (версии определения — created/edited по `created_at`, события `conditions-state.json` — fired/done/owner_mark/expired/reopened по `at`; шаг 12, `SUPERSEDE_MODE_RE` удалён), `plan` (журнал плана `stocks.T.plan_pct|user_plan|user_status`, `ts` — МСК с поясом, старые строки без пояса — UTC, `dsIso`); границы — `T`-метки обзора (`created_at`/mtime md-пары), `_atLE`: в день границы неизвестное время у любого из двух = «до обзора». Журнал плана грузится `planJournalEnsure` (`state.planJournalFail` — не повторять после ошибки), подпись «журнал плана — с 27.10» (`PLAN_JOURNAL_SINCE`) при его недоступности и периодах раньше. **3.122.0:** `securityEvents({…, collapse:true})` (только «Изменения») — `_collapsePlan`: по бумаге и полю плана серия `plan` между опорами (report/gate/cond/trade; поля по отдельности) → одна строка `_planText(first.was, last.now, N)`, время последней правки, was=now — строки нет; опора `trade` — `_tradeEventsOf` (смена `qty` между снапшотами `portfolioHistory`, дата снапшота; `Portfolio/securities/{KEY}.json` вьюер не грузит, его `trades` — те же снапшотные даты); «История» не сворачивается; `_tlRow` без хвостовой `→`; `_openSecCard(t, kind)` через `positionForTicker`. Сбор gate/cond/report/plan — `_secRaw(ticker, kind)`, общий с «Историей» карточки (`cardTimelineNode`: разбор, у которого в тот же день есть гейт со ссылкой на этот отчёт, сливается со строкой гейта; `TL_KIND.report/plan`). |
| Доли и цели | `renderIeModel` **3.80.0:** `buildIeStateCard` — только состояние (+ ссылка `goToTab('pfbuild')`), импорт IE (`ieImportControl`, `buildIeLoadCard`) и `#pf-file` — на странице «Загрузки»; «Общие доли» — строка-ссылка. | snapshot `ie_model`/`ie_actual`/`ie_summary` · `plan_check` (3.63.0: плашка both/n_diff → список расхождений path · Numbers · plan.json; plan_only; error) · `state.plan` (3.64.0: `loadPlan` → `GET api/pv/plan`; `showPlanEditModal(ticker)` → `POST api/pv/plan/set` пакетом `changes[]` (3.65.0; 3.64 — по полю) с `base_hash`, 409 → перечитать; статус — коды `USER_STATUS_WORD` ↔ `terms_ru.USER_STATUS_RU` (`test_terms_ru`); режимы таблицы `state.ieView` watch|work = «План»|«Сделки» (localStorage `piv-ie-view`; 3.69.1: поиск по бумаге `_tableSearch('ieModelQ')` в шапке `.rb-card` (итоги `tfoot` по видимым), колонка «Цена, ₽» (`livePriceOf` → цена снапшота) в обоих режимах, скрыта на телефоне; 3.66.0: свои наборы `cols` с `data-col`, карандаш `.rb-pen`, план и статус в строке и в карточке — `inlinePlanField` (3.67.0) → `POST set` одним полем без причины, отметка из `state.planJournal`, журнал фильтруется по `state.rebalMode`; полоса `devBar` убрана); после записи правится `ie_actual.per_ticker[t]` в памяти снапшота; журнал — `GET api/pv/plan/journal`) В «Сделках» у условий «продать/держать» в «Сейчас» — «сработало по касанию порога (дата и время из уведомлятеля), даже если цена вернулась; закрывает обзор». **3.76.0, колонка «Сумма, ₽»** (`cols` режима watch, ключ `sumGoal`, `data-col=sum`, между «План» и «Цель IE 12 мес, ₽»; в `work` и в «Все бумаги» — раннем выходе `renderIeAll` — её нет; на телефоне `.rb-v-watch [data-col=sum]` скрыта): жирно `sumGoal = goal / 100 × base` (`goal` — мой план при базе «к моему плану», цель IE при «к цели IE»; `base` — акции без `cost_basis`, та же, что у ₽ отклонения), подстрокой `sumFact = real / 100 × base`; нет цели — «—» и факт; итог `sumFoot` по видимым строкам; сортировка по `sumGoal`. **3.72.0 (этап 4c-1; режим «План», база ≠ «Все бумаги», после таблицы долей, до `buildIeStateCard`):** `buildClassGoalsCard` (план — `state.plan.plan.classes` при ok, иначе снапшот; факт — `balance_summary.class_plan_vs_fact[]`, отклонение факт − план считается во вьюере; `planFactTable`; **11.11, живые цены:** `RebalanceEngine.applyQuotes(snap, quotes, {fundClasses: plan.funds})` ↔ `apply_quotes(snap, quotes, fund_classes)` сдвигают `actual_rub` строк `class_plan_vs_fact` и `matrix_plan_vs_fact` на Δ стоимости позиций основного счёта (ячейка — правило загрузчика `build_class_breakdown`: акция — (валюта, «Акция»), облигация — корзина USD/EUR/CNY → её валюта, ОФЗ/КОРП → RUB, иначе валюта номинала; фонд — `plan.funds[T].class/currency`, без записи — строка `class: null` «не отнесён»; ИИС-3 не входит), пересчитывают `actual_pct`, `target_rub`, `delta_pp`, `delta_rub` от живого `total_current_rub_excl_iis` — Σ `actual_rub` классов = живой NAV; вьюер передаёт `plan.funds` (`liveBuildParsed`), а при загрузке плана и правке `funds.*` пересчитывает только строки классов и матрицы копии от строк снапшота и Δ стоимости по ключу тикер|ISIN|счёт (`liveRebuild` → `RebalanceEngine.reclassLive`; позиции копии не трогаются, зеркала в Python нет); CLI `--auto --quotes` берёт `plan.funds` из `Portfolio/plan.json` рядом со снапшотом (`_plan_funds_near`); `bonds_plan_vs_fact` (корзины) — по снимку; сверка — `test_rebalance_parity.py` 5б2), `buildBucketGoalsCard` (3.74.0: «Цели по облигациям», три группы валютные/ОФЗ/КОРП; 3.100.0: у строки группы — суммы её корзин (план, факт %, ₽ и отклонение как у корзин; без акцента и раскрытия), в «Что перевести» и в итог плана группы не входят — `planMovesSides` и `sumPlan` берут только строки без `group`; 3.75.0: `buildGoalsPair` собирает сетку `.ui-grid.pf-pair` из двух карточек (3.76.0: список фондов убран — вкладка «Фонды»), классы слева, облигации справа, ≤900px одна колонка; **3.76.0:** `planFactTable` — ячейка «План» двумя строками (% и `.ui-sub` сумма `base × план / 100`, база та же, что у факта; итог — 100 % и сумма базы), у «Кеш» вторая подстрока `.pf-sub2` «деньги X ₽ · фонды Y ₽» (`cashSplit()`: деньги `cash.by_account.main`, фонды — факт класса минус деньги); `planFactTable` строит не `<table>`, а строки `.ui-row.pf-row` (`--cols` в viewer.css), раскрытие корзины как в money.html — `div.ui-catopen.fresh` + `.ui-catdetail`, `.ui-chev`, `.closing`, `uiExpandIn`/`uiCollapseOut`, кнопка «все» `.ui-chev-all`; `bucketMembersNode` → `bucketMembers(key)`: облигации основного счёта по `holdings[].plan_bucket_key` (фильтр `account !== 'iis_3'`, записи одного тикера сливаются суммой) и фонды-члены по `plan.funds[T].bucket`; **3.76.0:** шапка `.ui-row.head.pf-bl-hd` (Бумага · ISIN · Стоимость · Доля корзины; на телефоне скрыта), доля — от суммы показанных бумаг, подвал только «Итого: X ₽»; сравнения со снапшотом нет). Матрица «валюта × класс» с экрана убрана и производная: `planSharesSave` дописывает в пакет `matrix.<CUR>/<Класс>.share` через `planMatrixDerivedChanges` (только изменившиеся, допуск 1e-6, 4 знака; журнал сворачивает такие записи одного `ts` в «матрица пересчитана»). Фонды — вкладка `renderFunds` (3.76.0, см. её строку; карточка фонда `cardFundMain` держит `_fundSelect` → один `POST api/pv/plan/set` без причины, чекбокс `in_rebalance` и для `current_price_source` не `moex_iss`/`moex_live` поле «Оценка вручную» → `manual_positions.<тип>/<тикер>.value_rub`, тип из строки плана с этим именем либо «<валюта> - <класс>»). Окна — `showPlanSharesModal` (kinds `classes`|`matrix`|`buckets` в `planEditOpen`, сохранение `planSharesSave`: пакет только изменённых путей `classes.<Класс>.share`, `matrix.<CUR>/<Класс>.share`, `bond_buckets.<ключ>.share`; в файл — доли единицы с 4 знаками, на экране — %; сумма ≠ 100 % предупреждает, не запрещает). Журнал «к моему плану» читает новые пути словами (`planPathHuman`). | ребалансировка, шаг А (цены снапшота): база — акции без `cost_basis`; цель IE (`ie_new_pct`) / план (`planned_share_pct`) / факт (`real_share_pct`); отклонение % и ₽ (до 3.82 — %), коридор `REBAL_CORRIDOR_PP` = 2; переключатель «к цели IE / к моему плану»; «Потенциал IE 12 мес» — `ieTargetFor().pot`/`potLt` как в модели (v3.24.0: «до цели от текущей цены» убран — модель обновляется вместе с долями); «до цели» от цены свежего снапшота); изменения модели (`ie_old_pct`→`ie_new_pct`, `ie_changes_count`). Без калькулятора «куда положить» (рекомендация). Ценовые условия (v3.6.2): `livePriceOf`/`priceDistText`/`condTriggerLive` — порог + текущая цена + «ещё ±N %»/«созрело» в «Действиях», таблице условий, карточке (цена — живая, а не `price_rub` обзора), сроке ограничения `expires price_*`, плитке (`conditionsDueStat().priceRipe`) и в «Сейчас» (`pending_buy_condition` → «созрело, закроет следующий обзор»; движок блок не снимает — решение владельца «вьюер подсказывает, обзор закрывает»). Шаг Б (v3.6.0) — живые цены: после отрисовки `loadLivePrices` → `GET api/moex/quotes?boards=TQBR` (hub-api, quotes@1, кэш 5/30 мин) → `RebalanceEngine.applyQuotes` к `currentPortRec()` (исходный — `rec.parsedSnapshot`; дрейф, ряд XIRR, график цены, веса IV-якоря читают его через `snapParsed`), метка `#live-src` — сама кнопка «взять цены заново» (v3.6.4; `#btn-live` в шапке убрана — не помещалась на телефоне), подзаголовок «Долей и целей» — от неё же; формулы — `tools/design-reference/live-prices-plan.md` §2; сверка Py↔JS — `test_rebalance_parity.py`, браузер — `test_viewer_live_prices.py`. Режим «к моему плану» (v3.5.0): колонка «Сейчас» и плитка — `RebalanceEngine.runAuto` (`tools/assets/rebalance-engine.js`) по снапшоту + `gateReviews` + `conditions`, зеркало `gate_aware_sizing.py --auto`; сверка `test_rebalance_parity.py`; лоты — `holdings[].lot_size` (loader с 13.10). С v3.55.0 (2026-10-26): докупка только при недоборе > гистерезиса 1 %; pending-условие с продажей (`sell_condition`) или «держать» (`condition_hold`) в своём окне закрывает докупку; вердикты недельного обзора колонка не читает — их место в отчёте; 3.61.0 (план §7.3 «в»): под ячейкой «Сейчас» — `.rb-adv` «<чьё> <дд.мм>: <вердикт> →» — последнее слово модуля (б) `lwCard(t)` (решение советника/владельца или обзор, что новее; 5.1.2, было — вердикт недельного обзора) (BUY/ADD/TRIM/SELL) со ссылкой на «Действия», расхождение направления с арифметикой — `.warn`; второго расчёта сумм нет; 3.68.0 (этап 3 ухода от Numbers): модель IE читается из `state.plan.plan.ie_model` при `status==='ok'` (иначе из снапшота) — `ieModel()`, цель бумаги `ieShareOf` (plan первичен), история `ie_history` → `ieHistoryLast` («с <дата>, было N %»); `active_in_model === false` — позиция общего портфеля IE (потенциалы без доли). Окно доли IE `showIeEditModal` (карандаш `iet`, кнопка карточки) → `POST api/pv/plan/ie-set {base_hash, source:'site', changes:[{ticker, share_pct?, note_ie?, reason}]}`; пустая причина допускается (предупреждение, в журнале «без причины»). Карточка `buildIeStateCard` + импорт: файл → `pfFileB64` → `POST api/pv/plan/ie-import {name, b64, tickers}` (разбор webarchive/HTML на сервере, без записи) → `showIeImportModal` (diff changed/new/removed/same, причины по строкам) → «Применить» = `ie-set {source:'webarchive', extraction_date:null, cash_pct (модельный), changes:[{ticker, position, share_pct?, reason}]}`; `planApplyToSnapshot` синхронизирует `ie_new_pct/ie_old_pct/ie_delta_pct` в снапшоте в памяти; журнал «IE» рисует `stocks.T.ie_new_pct|note_ie`, `ie_model.positions.T`, `ie_model.cash_pct` 3.69.0: окно доли IE без поля причины — `reason` = текст заметки IE (предупреждение «доля меняется без заметки IE»); импорт модели — `.ui-table.dense` (телефон ≤640px — карточки) с колонками Бумага · Доля · Цена IE · Цель 12 мес ₽ · Долгоср. цель ₽ · Дивиденды · Риск · Причина, изменение `.ie-chg`, причина уходит как `reason` и `note_ie`; `kind=general` — окно «Оценки IE по бумагам» (части «Мои бумаги» по `held` / «Остальные бумаги IE»), `ie-set {source:'webarchive', page:'general', changes:[{ticker, position}]}` для всех строк, дата — `ie_model.general_date`; цели в ₽ — `ieGoalsOf` (`target_price_rub`/`target_price_lt_rub` страницы, иначе `current_price_rub × (1 + потенциал)`; база — цена IE, не Мосбиржи), колонка «Цель IE 12 мес, ₽». «Сделки»: фильтры план / статус / только с действием / вне коридора (`ie-work-plan` первым, общий `fSt` режима). 3.70.0: порядок колонок `cols` — «План»: Бумага · Цель IE · Цена · Мой план · Факт · Отклонение…; «Сделки»: Бумага · Мой план · Факт · Отклонение · Цена · Сейчас…; третья база `state.rebalMode = 'all'` («Все бумаги», только в «Плане»; в «Сделках» считается 'plan', сохранённое не трогаем) — `renderIeAll`: «Оценки IE по бумагам» по всем `ie_model.positions` (и `active_in_model === false`), колонки Бумага · Цель IE, % · Цена IE · Цель 12 мес ₽ · Долгоср. цель ₽ · Дивиденды · Риск · Отрасль (`industry` / `sector`), фильтры `state.filterStates['ie-all']` {risk, held, inModel}, поиск `ieModelQ`, клик открывает карточку только у бумаг портфеля; на телефоне остаются Бумага · Цель 12 мес · Долгоср. цель (`.rb-v-all`; 3.119.0: плюс «Мой план, %» с ✎). 3.119.0, проданная бумага: читатель `instrXirr(T)` = `per_instrument_xirr[T]` или `per_instrument_xirr_closed[T]` (признак — `closed: true` / `price_source: 'closed'` / запись из блока `closed`); плитка «Моя доходность» (`closedReturnTile`: XIRR, «итог ± N ₽ · продана дд.мм», вместо «Вес: факт» — «продана дд.мм»), блок «Итог по бумаге» (`closedReturnNode`: подвкладка «Доходность» акции и фонда, «Главное» облигации). Тесты `test_viewer_plan_ie_all.py`, `test_viewer_closed_card.py`. **3.77.0, четвёртая база `overall` («Общие доли», первая в сегменте; в «Сделках» сегмент серый, `mode` = 'plan'; `state.rebalMode` по умолчанию 'plan'):** `renderOverall` — ранний выход до таблицы долей: плитки (база без ИИС-3, вне коридора = классы + корзины через `_planFactDev`, «Кеш всего» = `cashSplit` деньги + фонды класса «Кеш», «Свободно сверх плана кеша» = факт − план×база), `buildGoalsPair(buildMovesCard())` — слева `buildClassGoalsCard` (данные `classPlanFactData`) и под ней `#pf-move` (`movesSection`; 3.78.0: строки «Отдать» — класс `bad`, «Получить» — `good`, итог без цвета), справа `buildBucketGoalsCard`, затем `buildPlanJournalNode('plan')`; `buildIeStateCard` не рисуется. В `plan`/`ie` пары карточек под таблицей нет. **`planMoves(rows, corridorPp, base)`** (чистая функция, только вьюер, зеркала в Python нет): источники `aPct − plan > коридор` (излишек `aRub − plan/100×base`), приёмники `< −коридор` (недобор); `S = min(Σизлишков, Σнедоборов)`; возвращает `{ give, take, total }`: «отдать» i = `round(S × exc_i/Σexc)`, «получить» j = `round(S × need_j/Σneed)`, `total = round(S)`, строки меньше `MOVE_MIN_RUB` (1 000 ₽) отброшены (матрицы «из X в Y» нет); два раздела — классы (`classPlanFactData`) и корзины (`bucketPlanFactRows`, по текущим ценам); `planMovesSides` даёт источники/приёмники для сообщений «источника нет» и «всё в коридоре или выше плана». Тест — `test_viewer_plan_moves.py`. |
| Ещё → Интеграционный анализ | `renderDashboard` | `integrated-view` | плашка отставания от свежих обзоров; «Портфель с момента анализа» (`buildDriftCard`, якорный ↔ свежий снапшот); шапка — `buildDocMetaCard` (как у полного отчёта); акции против облигаций с интервалом по горизонтам 6-12-24; полная доходность по слоям. Карточка монитора убрана в 3.18.0 — она в «Действиях» |
| Ещё → Прогнозы | `renderForecasts` → `renderForecastLayer2` / `renderPredictions` | `forecasts/*` · `integrated-view` | переключатель (`state.forecastsView`): Layer 2 by_scenario прогнозы (провенанс двумя колонками, viewer 2.13.0: «Использованы» — `sources_used`, «Upstream» — `upstream_used`, spec §5.2.1) · `predictions_for_review` |
| Макро (справа от «Доли и цели», с 3.13.0) | `renderMacroContext` | `macro-snapshots/auto/ru-*.json` (тип `macroAuto`; hub-notify по будням 08:30, `build_macro.py`) — основной ряд с 11.11; без автосрезов — прежний вид по `ru-*.md` (≥2) | `renderMacroAutoTiles`: 7 индикаторов плитками `kpiTile` (ключи `MACRO_AUTO_KEYS`; Brent — фьючерс BR на MOEX «на дату», инфляция г/г — месячная ЦБ «за ММ.ГГГГ (ЦБ)»), мини-графики `.ui-spark` по ряду автосрезов, продолженному назад срезами скилла `ru-*.md` (`parsed.indicators`, даты раньше первого автосреза показателя; подпись под плитками называет склейку и Brent ICE); плитка `cpi` — оценка г/г по неделям: `parsed.indicators.cpi` срезов скилла + `inflRecords()` (`yoy_pct` на `yoy_as_of`), месячная ЦБ автосреза — в подписи плитки; нет ни одной недельной оценки — месячная ЦБ; `renderMacroInflation` — недельная инфляция из двух файлов `macro-snapshots/inflation/{model,owner}.jsonl` (тип `macroInfl`, `inflRecords()`): самая свежая по `date` запись, источник, «внесено вами / скиллом» — `model.jsonl` пишет только скилл (`save_inflation.py`, `require_ai`), `owner.jsonl` — только hub-api (`POST /api/pv/macro/inflation`, форма «Внести инфляцию» при «без ИИ»); срок годности — только у недельной инфляции (`STALE_THRESHOLDS_DAYS.macro` 9 / `STALE_FAIL_DAYS.macro` 16 ↔ `STALE_WARN_DAYS`/`STALE_FAIL_DAYS` notifier.py ↔ `CONFIG.reports[macro]` hub.html); z-флаг автосреза — по значениям одного источника (инфляция ЦБ — только по месячным значениям из `auto/*.json`, `build_macro.load_auto_infl`); `renderMacroAutoLog` — ряд автосрезов с пропусками и аномалиями |
| Источники → часть «Источники» (3.63.0: раздел в основной строке после «Макро»; 3.62.0: раздел `renderProvenanceTab` с сегментом `PROVENANCE_PARTS`, часть — `state.provPart`; в 3.58–3.61 — кнопка в шапке и окно `showProvenanceModal`; ссылки `#tab=caveats\|whats-not` ведут в раздел на нужную часть через `goToTab`) | `renderSources` | все | профили доверия по доменам (`_renderDomainAudit`: уровни по-русски, тезисы/попадания/ценность, заметки аудита), файлы строками по типам, пропущенные и ошибки (3.14.0; плашки свежести убраны в 3.13.0 — устаревшее на «Сегодня», `_staleList`) |
| Источники → Предложения на аудит (3.63.0) | `renderAuditCandidates` | `forecasts/*.md` (вид `forecastMd`, грузится с 3.63.0) · `domains/*/*.md` | порт `audit_candidates.py`: таблицы «Не аудированные источники» из отчётов FCA, нормализация имён и `AUDIT_ALIASES` (контракт-тест сверяет с python `ALIASES`), вычитание аудированных по `fm.source` профилей; 3.63.2: короткий список `auditShortlistThreshold` (хотя бы 10, порог по упоминаниям целиком) ↔ `shortlist_threshold` в python; 3.63.3: строка `tr.pick` → `_copyText` фразы `/forecast-collector Собери прогнозы <источник> для аудита` (порядок пайплайна: collector → retrospective-forecast-audit); сценарный слой yaml (`sources_used` без `trust_level`) только в скрипте |
| Источники → Оговорки | `renderCaveats` | все | хвостовой риск (`buildTailFlagsCard`) группами по `code`; §9 интеграционного анализа по серьёзности (`_ivCaveatParts`: без «Tail-risk флагов» и «Что не показано»); оговорки обзора и стресса — HIGH сразу, остальное в `details`; типы стресса — `CAVEAT_TYPE_RU` (3.17.0) |
| Источники → Что не показано | `renderWhatsNot` | `integrated-view` | подраздел §9 «Что не показано (где взять)» (`_ivCaveatParts().whatsNot`) |
| Ещё → Загрузки (с 3.43.0, до 3.81 «Проба сборки снапшота»; кнопка `#btn-pfbuild`) | `renderPfBuildTab` | `POST api/pf/build` · `POST api/pf/cancel` (3.121.0: прерывает группу процессов сборки, статус `cancelled`, `save` → 409) · `GET api/pf/status` · `POST api/pf/save` (контейнер hub-notify, `pf_build.py`) | 3.104: «Сохранить» — «Сохранить как рабочий снапшот»; 3.105: save отвечает сразу `{saved, run}`, журнал решений идёт фоновым потоком (`state` running → done/error в status.json; running старше TIMEOUT+60 с читается как error «прервано»), вьюер опрашивает `GET api/pf/status` каждые 3 с (до 20 мин) и показывает `securities_index`/`decision_journal` (обновлён / не обновлён: причина), 409 «уже есть снапшот с балансом» — словами. только http-режим; файлы base64 (сделки обязательны; баланс и ИИС-3 — нет: без баланса `assemble --holdings-from-trades`; с 3.85.0 штатно сделки + `plan.json`: план, цели, IE, типизация облигаций и FINAMAR — из плана, из прошлого снапшота лишь ИИС-3, названия и дрейф кеша — `balance_summary.carried`) → `build_snapshot.py` без `--commit`, `--memory /srv` (ro); итог `brief`: числа сборки против ПОСЛЕДНЕГО снапшота скилла (3.102.0: `inputs.compare_snapshot` — самый свежий `portfolio-*.json` с датой ≤ as_of любого типа, `find_compare_snapshot`; нет поля — старый загрузчик, тогда `prev_snapshot`), а не против опоры кэша (`inputs.prev_snapshot` — самый свежий СНАПШОТ С БАЛАНСОМ или внесённым кэшем, `find_prev_snapshot`; правило после инцидента 27.10 не меняется); если опора кэша — другой файл, `brief.cache_base_as_of` и подпись «опора кэша — снапшот от …»; проверки не-info, флаги внимания, фолбэки; решение `cash_drift_changed` → пересборка с `rebaseline_cash`; решение `cash_fact_stale` (3.75.1) → поле «свободные деньги основного портфеля в IntelInvest» → пересборка с `cash_fact` (`--cash-fact`; 0 ≤ x < 1e9, иначе 400); «Сохранить» → рабочая `Portfolio/snapshots/portfolio-<дата>.json` (`SAVE_DIR`; имя как у скилла, `SNAP_RE` видит; прежний файл дня — в `.versions/` hub-api; без баланса поверх снапшота с балансом → 409), служебная `build-summary-<дата>-<ЧЧММ>-<bal|trades>.json` — в `snapshots/auto/`; через `hub-api /api/job/save` (нужен путь `Portfolio/snapshots/portfolio-ДАТА.json` в `JOB_WHITELIST`), блок → 409; после сохранения `pf_build.publish_securities` пересобирает `pf_build.publish_journal` пересобирает журнал решений (`decision_journal_update.py` на рабочем корне в папке прогона, сделки — выгрузка прогона; наружу через hub-api только `inputs/baselines/journal.json` и `report-ДАТА.md`, ручные `*.yaml` не пишутся; результат — `status.decision_journal`, сбой снапшот не отменяет) С 3.44.0 — на ui-kit: плитки файлов `.pf-file` (выбор и перетаскивание), полоса хода `.pf-bar`, вердикт `.pf-verdict` с «Сохранить» сверху, сравнение плитками `.ui-stat` (`#pf-compare`), под ними `pfParityBlock(b.parity)` (`#pf-parity`, сгиб `#pf-parity-fold` с `diverged_paths`; `brief.parity` ← `build-summary.parity`, `report_path` pf_build отрезает; 3.85.0), проверки карточками `.pf-check` с меткой уровня; кнопки `.ui-btn.lg`/`.ghost` (ui-kit 1.52.0). Шаг 7в скилла (сборка из `auto/` рабочей: копия прежнего → `auto/…-skill-replaced.json`, `incidents.yaml`) нужен только для старых проб из `auto/`. Подписи для пользователя: под плитками сравнения — строка «Поле за полем против снапшота …: совпало · в допуске · известных · расходится» со сгибом «Где расходится» (пути полей) или «Сверки нет», если рабочего снапшота с балансом на эту дату нет; расхождения сохранению не мешают. Карточка «Тип бумаги изменился» (перед «Кэшем по счетам»): строка «TMON ETF · TMON — был акция → стал фонд», под ней «по бирже: фонд · по сделкам: акция» и причина — «против прошлого снапшота» (тип сменился) или «новая бумага: биржа и эвристика разошлись»; бумаги без сделок сверяются эвристикой по тикеру; «Типы с биржи не запрашивались (сборка без сети)» — Мосбиржа недоступна, типы из справочника и по сделкам; скилл на Mac в Мосбиржу за типами не ходит. «Кэш по счетам» (3.122.0, `pfCashCard`): строка на счёт — «в сохранённом (дд.мм) → в этой сборке · Δ» (`brief.skill.cash_*` против `brief.auto.cash_*`), метка источника из `brief.auto.cash_source` / `cash_iis_source` (owner_intelinvest — «внесён»; trades_plus_prev_drift, carried_from_prev — «оценка»; с балансом — «из баланса»), поле суммы в той же строке (основной счёт и ИИС-3 — свободные деньги, ИИС-3 только рубли; строка ИИС-3 есть, если у сборки или сохранённого есть кэш ИИС-3), подставлена оценка сборки, пустое поле не передаётся; «Сравнение со скиллом» стало «Что изменится, если сохранить»: `brief.positions_diff` (`pf_build.positions_diff`: ключ (счёт, тикер), продано/куплено/количество, до 20 строк + `more`; null — сохранённого нет), плитки «Стоимость с ИИС-3» (подпись по `brief.skill.generated_at`) и «XIRR»; `pfParityBlock` без `parity` и без баланса не рисуется; «Проверки» — «Нужно действие» (checks) и «К сведению» (флаги по коду: `balance_absent_holdings_from_trades` → сгиб «Источники сборки», `bond_rating_missing` → общая строка «Рейтинг в плане»); поле «Общий баланс» — в свёрнутом `#pf-bal-fold`; теги результата «кэш внесён: N ₽», «кэш ИИС-3 внесён: N ₽». Пробная сборка без «Сохранить» ничего не пишет. Повтор пакета прогона берёт план из пакета (`caches-start/plan.json`). |
| Ещё → Уведомления | `renderNotifyTab` → ui-kit `uiPushMount({section: 'portfolio'})` (с 3.54.0) | `GET api/push/status?section=portfolio` · `POST api/push/settings` (контейнер hub-notify) | только http-режим; виды портфеля (`off`, каталог `KINDS` с полем `section`) и журнал раздела (`log`, фильтр на сервере `log_for`); строка «это устройство · режим» и ссылка `hub.html#notify`. Устройство (подписка через ui-kit `uiPushSubscribe` на тот же фоновый скрипт `tools/portfolio-sw.js`, манифест `assets/portfolio-manifest.json`), режим quiet/live и виды всех разделов — в hub (`uiTopHTML({push: "all"})` → `uiPushOpen(null)`). `pushRegister` вьюера — обёртка над `uiPushReg` (офлайн-скрипт вьюера). Кнопка «Уведомления» в шапке ведёт сюда. Ссылки уведомлений `#card=ТИКЕР`/`#tab=…` — `applyDeepLink` (при загрузке, `hashchange`, сообщение `piv-open` от фонового скрипта) |

### 5.0 Карточка бумаги (`openCard`, v3.0)

Окно `uiModalHTML` (1150px, `cls: "tall"` — постоянной высоты; на телефоне во весь экран),
стопкой: `cardStack` + `uiStackCls`/`uiStackPop`/`uiStackKeepScroll` (prefix `card-body-`).
Шапка (`cardStockHead`/`cardBondHead`, слот `top` — не прокручивается): метки и плитки
(акция: вес факт/план/IE · XIRR · ожидание на горизонте [худший…лучший сценарий + дивиденды +
идио] · потенциал IE 12 мес (4.4.7: `ieGoalsOf` — от текущей цены `ieMarketPrice` до цели строки IE; поле `growth_potential_*` участвует только в выводе цели, когда `target_price_*` пуст; «Моя доходность» при истории короче года — % за период, `RET_SHORT_DAYS = 365`); облигация: цена в % номинала (v3.56.0) · YTM [CI] · погашение/оферта · моя доходность).
Метки шапки — словами с пояснением (`tagInfo`, `gateTagNode`). Подвкладки `CARD_SUBS` (v3.56.0, план
`tools/design-reference/viewer-rethink-plan.md` §1): акция — «Главное» (`cardDecisionNode`: вердикт словами
`VERDICT_WORD`, уверенность словом `confWord`, гейт, «почему» из предложений `advisor_verdict_basis` через `humanizeText`;
`cardWeekNode`: `week_note` контракта A (`what_happened`, `macro_link`, с 3.57.0 — «Рекомендация недели» из `recommendation`), пока его нет — `fundamental_score_basis` свёрнуто; `cardWaitNode`: условия
таблицей «если → тогда» — `on_trigger.branches` контракта B (3.57.0: `then.note` заметкой, `then.target_pct` → `branchSizingText` «≈ ±₽ · лоты по цене»; плашка «План менялся» по `context.plan_pct`, иначе по истории снапшотов), иначе строки «тогда / пока ждём» из `action`; уверенность словом с причиной `confidence_basis`; `cardBanNode`: только
непроизводные `user_constraints` обзора (`derived: true` не рисуются) с «когда вернуться к вопросу» из `re_entry`) ·
«Доходность» (`decomp`/`div` + `priceChartNode` с точками-подсказками) · «Риски» (`cardCatalystsNode` вверх/вниз,
числа в (i); `cardThesisBreakNode` из условий TRIM/SELL и правил гейта; `betas`/`scen`/`corp`) · «История»
(`cardTimelineNode`: обзоры + история гейта + история условий + сделки по смене количества в снапшотах; старая таблица
свёрнута) · **3.104: «История» — ссылка у обзора только при смене вердикта/фундаментала (качества) против предыдущего обзора; «Отчёты» — обзоры недели только с markdown-парой (`cardReviewsOf`)** · **«Отчёты» (3.97.0, у акции, облигации и фонда после «Истории»)**: `reportsForTicker(ticker, {isin, name})` по `state.data.advisorReports` — отчёт относится к бумаге, если `fm.tickers` содержит тикер или ISIN холдинга (регистр не важен) либо имя, которое сопоставил `_tickerByName` (3.96.0); внутри и разборы бумаги, и общие отчёты; строки `.ui-row.pick.card-rep` (дата + время записи файла, заголовок, вид, режим коротко, первая фраза `summary`), порядок `cmpRecent`; ярлык «Отчёты · N» (3.102.0: N = отчёты + обзоры недели). **Вторая группа «Обзоры недели · N» (3.102.0):** `reviewsForTicker(ticker, {isin})` — YAML `weeklyReview*` (`per_stock`/`per_bond` по тикеру или ISIN), пара md по дате; строка `.card-rep` — дата + время (правило 3.99), «обзор акций/облигаций за неделю», вердикт словом, первая фраза `week_note.what_happened` ≤160; больше трёх — сгиб `.ui-fold.card-revs-fold` свёрнут; клик → `showMdReportModal(md, kind, {fromCard: true})`, «← К бумаге»; тот же помощник питает «Историю» (`cardTimelineNode`). Клик по отчёту → `showAdvisorReportModal(r, {fromCard: true})`: окно документа (`#modal-overlay`, z 300) встаёт стопкой поверх карточки (z 220), «← К бумаге» = `closeModal`, Esc — тоже только отчёт; карточка из шапки такого отчёта выше (`overDoc`, z 320). В «Главном» строка-ссылка `cardReportsLinkNode`. **«История» со ссылками:** `_tlLinkOf` связывает событие журнала с документом только по дате и бумаге — `rev` → md-обзор той же даты (`weeklyReviewMdHistory`/`weeklyBondReviewMdHistory`), `gate` (set_by не `auto`) и `cond` (есть `created_by`, событие не `fired`/`expired`) → первый по `cmpRecent` отчёт этой даты с бумагой, подсказка «ещё N отчётов этой даты» при нескольких; сделки не связываются; один помощник `reportsForTicker` на подвкладку и журнал. Облигация — те же узлы по `review`, «Выплаты» (`cardBondPay`), «Рейтинг и риски» (`rating` + катализаторы), «История». **3.73.0, «Мой план» облигации (`bondPlanNodes` в `cardBondKv`, всегда):** «Корзина» — инлайн-список девяти ключей (`PLAN_BUCKET_KEYS`) и «—»; выбор пишет одним пакетом `bonds.<ISIN>.type` + `bonds.<ISIN>.subtype` (валютные — subtype `null`), текущее значение — `plan.bonds[ISIN]` при ok, иначе `holdings.plan_bucket`/`plan_subtype`; расхождение плана со снапшотом — подстрока «в снапшоте: …»; «Действие» — текст ≤200 (Enter/blur при изменении, пусто → `null`) → `bonds.<ISIN>.action`; «Рейтинг в плане» — только чтение; при `state.plan.status ≠ ok` поля disabled с `planEditHint()`. ISIN — `holding.isin`. **Карточка фонда (3.73.0, `kind: 'fund'`):** открывается по имени в «Фонды» (`fundEntries()` — порядок таблицы; листание ← →, Esc); не берётся из `buildPositionByTicker` (перерисовка стопки фонд не подменяет). Шапка `cardFundHead`: стоимость · доля (без ИИС-3) · XIRR из `per_instrument_xirr` (для оценённых вручную — «—») · карта плана. «Главное» (`cardFundMain`): «Мой план» = карта `funds.<T>.(class|currency|bucket|in_rebalance|note)` через те же `_fundSelect`/`_planTextInput` + `_fundRefresh`; «Позиция» — количество, лот, средняя, цена, стоимость, счёт, источник цены, «Оценка вручную» (`_fundManualNode`). «История» (`cardFundHist`): `priceChartNode` + таблица снапшотов (цена · количество · стоимость). **3.76.0:** подвкладка «Доходность» (`CARD_SUBS.fund` = main/ret/hist) — `cardFundRet`: «Вложено» (`buy_total_rub`), «Средняя цена» (`avg_cost_rub`), «Срок владения» (от `first_trade_date`), «XIRR» и блок `cardPnlNodes(ticker)` — тот же, что в «Позиции» акции (прибыль по сделкам, дивиденды, текущая прибыль, результат); пустые строки не рисуются, без `per_instrument_xirr[t]` — `card-empty`, у оценённых вручную доходность не считается. Вердиктов и советов нет — советника у фондов нет.
Правая колонка (`cardStockKv`): лоты двумя строками по `holdings[].lot_size`, «Мой план» (`user_plan` словами, статус и
заметка только если есть), «Модель IE» («было X%» только при смене `ie_old_pct`→`ie_new_pct`, свежесть `IE_FRESH_DAYS` = 62).
На телефоне (v3.3.0, ui-kit 1.42.0) окно `.fold`: прокручивается `.ui-modal-box`, шапка липкая,
плитки (`.ui-modal-fold`) уезжают и гаснут (`animation-timeline: view()`), подвкладки
(`.ui-modal-stick`) липнут под шапкой, `uiFoldMount` ставит `.folded` → строка `subAlt`
(сводка из `cardTitleParts().alt`); прокрутку помнит/сбрасывает `uiFoldScroller`; смена
подвкладки в свёрнутом окне оставляет его свёрнутым (`cardSub`). Справа на «Главном» — колонка `.ui-kv` (`cardStockKv`/`cardBondKv`). Листание ← → (кнопки
в слоте `lead`, клавиши ←/→) — по списку `list`, переданному таблицей (фильтр и сортировка),
подвкладка сохраняется; новая карточка — «Главное» (`CARD_REMEMBER_SUB = false`). Сдвиг и
появление — `uiAnimIn`. Документ и карточка — общая стопка слоёв (`docOpen`/`docThaw`): отчёт из карточки встаёт поверх неё;
Esc, «←» и фон закрывают только верхнее окно и возвращают по цепочке до исходного документа («Решения», отчёт, «Отчёты»).

Подписи для пользователя: у обзоров до 26.10 вместо «Что произошло за неделю» — свёрнутое «Состояние компании»; «Запрет» в «Главном» — только решения владельца; модель IE старше двух месяцев помечена как устаревшая; суммы и лоты в «Чего ждём» — по актуальной цене.

### 5.1 Классификация файлов (`classifyByName`)

Вьюер определяет тип файла по имени и пути:

| Паттерн имени | Тип | Папка |
|---|---|---|
| `integrated-view-*.md` | `integratedView` | `Portfolio/integrated-views/` |
| `weekly-review-stock-*.{yaml,md}` | `weeklyReview` / `weeklyReviewMd` | `Portfolio/weekly-reviews/` |
| `weekly-review-bond-*.{yaml,md}` | `weeklyBondReview` / `…Md` | `Portfolio/weekly-reviews/` |
| `stress-YYYY-MM-DD*.yaml` | `stress` (действующий — `cmpRecent`: дата → время записи файла → имя; то же правило у сайта, советника и аудита) | `Portfolio/stress/` |
| `recalc-stress-YYYY-MM-DD*.yaml` | `stressRecalc` (подменяет `parsed` у `stressCurrent`; `date`/`name` остаются от стресса скилла; пересчёт с `recalc.at` раньше времени записи файла стресса — от прежней версии, не берётся: `stressRecalcIsStale`, флаг `recalcStale`, сайт пересчитывает сам) | `Portfolio/stress/auto/` — вне листингов `PV_DIRS`, берётся прямым запросом `fetchStressRecalc`; офлайн-копии нет |
| `portfolio-YYYY-MM-DD*.json` | `portfolio` | `Portfolio/snapshots/` |
| `{ГГГГ-ММ-ДД}T{ЧЧММ}-{KEY}.json` в `Portfolio/decisions/` | `decision` (решение `decision@1`) | `Portfolio/decisions/` |
| `conditions.yaml` · `conditions-archive-ГГГГ.yaml` (YAML без автодат, `JSON_SCHEMA`) | `conditions` · `conditionArchive` | `Portfolio/` |
| `conditions-state.json` · `security-attrs.json` | `conditionsState` · `securityAttrs` | `Portfolio/` |
| `macro-scenarios-*.yaml` в `macro-chain/` | `macroScenarios` (цепочка стресса) | `macro-chain/` |
| `baselines.json` · `journal.json` в `Portfolio/decision-journal/` | `djBaselines` · `djJournal` | `Portfolio/decision-journal/` |
| `monitor-report-*.yaml` | `monitorReport` | `monitor-reports/` |
| `*.yaml` в `forecasts/` (не `-stress`) | `forecast` | `forecasts/` |
| `*.yaml` в `scenarios/` | `scenarioYaml` | `scenarios/` |
| `ru-YYYY-MM-DD*.md` | `macroSnapshot` | `macro-snapshots/` |
| `*.md` в `domains/<domain>/` | `domainAudit` | `domains/*/` |
| `*.md` в `Portfolio/reports/` | `advisorReport` | `Portfolio/reports/` |

### 5.1б Порядок и время отчётов советника (3.97.0)

`parseListing` сохраняет `mtime` (Caddy JSON `mod_time` → epoch мс; автоиндекс без JSON — `null`); у файлов из `/api/pv/sync` и копии на устройстве время берётся из версии (`verMtime`: `s:<размер>:<mtime_ns>` и `<размер>|<mod_time>`), оно доезжает до записи `records[].mtime` через `makeHttpFile`. `cmpRecent(a, b)` — дата отчёта убыв. → `mtime` убыв. → имя убыв.; применяется ко всем выборкам `advisorReports` (список «Мои репорты», `_latestIisReport`, карточки). В списке «Мои репорты» рядом с датой стоит «16:29», если день `mtime` совпадает с `date` отчёта (`reportTimeLabel`); иначе только дата — у старых отчётов, перенесённых синком, время файла ничего не значит. Порядок — по дате отчёта, внутри дня по времени записи файла; правка старого отчёта двигает его только внутри его даты.

**3.99.0 — время создания и время событий** (история; с шага 3 цикла машиночитаемости время ставят скрипты и сервер — `recorded_at` с поясом, `time_msk.py`; `securities_index.py` и `apply_gate_review.py` удалены, `history[]` условий заменён событиями `conditions-state.json`). Отчёт советника (Workflow N) и YAML обзора недели (Workflow F) могут нести необязательное `created_at: "YYYY-MM-DDTHH:MM"` (локальное, `date +%Y-%m-%dT%H:%M` перед записью файла); `securities_index.py` пробрасывает его в `reports[]`. Теперь `cmpRecent` — дата → `created_at` (`recCreatedAt`) → `mtime` → имя; `reportTimeLabel` показывает `created_at`, а при его отсутствии `mtime` (если день совпал с датой). Скрипты `apply_gate_review.py` и `apply_condition.py` сами пишут `time` «ЧЧ:ММ» (МСК, момент применения) в `history[]` гейта (и `set_time` записи) и во все события `history[]` условий; старые записи без `time` допустимы. В «Истории» карточки время события = `time` журнала → `created_at` связанного документа (отчёт по правилу 3.97; для обзора — YAML обзора) → `mtime` документа, если его день = дате события → нет. Порядок — `cmpTimeline`: дата убыв.; внутри дня события со временем по времени убыв., без времени — после них от позднего этапа к раннему (сделка, условие, гейт, обзор: обзор недели выходит раньше разбора); время мелко под датой (`.tl-t`). Фонды, лежащие только на ИИС-3, попадают в `buildPositionByTicker` записью `iisOnlyFundEntries()` (`onIis`, `_iis{qty,value,share}`) — чип отчёта открывает карточку фонда ИИС-3 с неактивными полями плана.

**3.101.0 — одна запись на тикер, счёт — измерение.** `buildPositionByTicker` в конце вызывает `attachAccounts`: запись бумаги (акция, облигация, фонд) несёт `accounts: { main, iis_3 }` (`qty`, `value`, `share`; у `main` ещё `avg`, `xirr`; у `iis_3` — `locked`, `lockedReal`; `h` — строка holdings; `null` — бумаги на счёте нет); `onIis` = «лежит на ИИС-3». **3.107.0 — плитки облигации и позиция счёта.** `cardBondHead` рисует ровно четыре плитки на любом счёте: YTM · погашение/оферта · `bondLockedTile` («При покупке» = `locked_pct` holding'а выбранного счёта, у линкера + `locked_real_pct`; нет — «—», «нет графика выплат») · `myReturnTile`. Цена — только в заголовке (`cardTitleParts`). `attachAccounts` кладёт `locked`/`lockedReal` в обе стороны (`accounts.main` — из holding основного счёта; `accounts.iis_3` — из `iisBlock().per_bond`, запасной — holding), `cardView` — `_pos` (qty, value, share, locked) выбранного счёта; доля облигации — стоимость / облигации основного счёта по снапшоту (не `weight_real_pct` обзора, он на другую дату). `cardBondKv`: первый блок «Позиция» (стоимость, количество, доля, `bondAvgText`, НКД на бумагу/позицию, счёт), затем «Бумага» — общее. Фонд на двух счетах: `cardPnlNodes(ticker, acct)` и `cardFundRet` берут `per_instrument_xirr[t].by_account[acct]` (результат, вложено, срок, XIRR — по счёту), плитка «Доля счёта» подписана «ИИС-3». Клонов `onIis: true` во вкладке «ИИС-3», в `iisOnlyFundEntries` и в «Фондах» нет: они открывают ту же запись с `openCard(entry, list, { account: 'iis_3' })` (счёт хранится в слое карточки, `L.account`). `renderCards`/`fillCard` рисуют `cardView(entry, L.account)` — копию записи с показателями выбранного счёта (`onIis`, `_iis`, `_hold`, `holding`); `cardAccount` откатывается на основной счёт (листание ← → сохраняет счёт, если он есть у соседа). Бумага на обоих счетах — сегмент `.ui-seg` «Основной счёт · ИИС-3» под плитками (`data-act="card-acct"`); он меняет только показатели позиции и строку «Счёт» (`_acctLine`: «брокерский · есть и на ИИС-3» / «ИИС-3 · есть и на брокерском»). Тег «❄ ИИС-3» — только у бумаги без основного счёта. Правило 3.83 отменено: `lockPlan` фонда = `!(accounts.main.qty > 0)` — поля «Мой план» (класс, валюта, корзина, балансировка, комиссия, спред, заметка, оценка вручную) правятся ⇔ фонд есть на основном счёте, независимо от точки входа; иначе выключены с одной `ui-note`.

### 5.2 Блок «Фундаментальная оценка» и «Решение» (модуль (б))

В карточке эмитента — `renderGateBlock(ticker)`; источник — `gateOf(ticker)` (выход модуля (б) `lwCard(key).gate` +
файл решения `decisionById(c.decision_id)`), гейт только у акций:

| Поле | Откуда | Что показывает |
|---|---|---|
| статус | `gate.status` (кодлист `gate_status`, `verdict_to_gate` от новейшего решения) | значок + подпись `GATE_STATUS_META`, подсказка `GATE_STATUS_HINT` |
| почему | `decision.note` | одна фраза решения |
| решение | `decision_recorded_at` + `decisionSourceWord(decision)` | дата и кто записал (разбор режима N, владелец, бэкфилл) |
| срок | `gate.expires_on` (`review_by`, null → +60 дней), `gate.expired` | «Срок решения» / «Срок вышел» |
| паузы | `gate.add_cooldown_until`, `gate.ipo_pause_until` | пауза докупки 21 день от первой покупки после решения, IPO-пауза |

Блок «Решение» на «Главном» — `cardDecisionNode`: последнее слово с датой (и дата обзора, если последнее слово — решение), вердикт из новейшего источника,
доля и срок только из решения (`decisionRowText`), `buyLineText`, «Ждём:», `gateSayNode`, плашки `lwPlaquesNode`, `cardBaseNode`, проза основания свёрнута («<источник> дд.мм подробнее»). Бейдж у тикера —
`renderGateBadge` (tooltip `_gateTooltip`: решение, срок, паузы). Окно «🛡 Решения» — §3.4.

### 5.3 Теги позиций в master-таблице (§3 integrated-view)

| Тег | Условие |
|---|---|
| 🟢 agree | стресс и обзор согласны (HOLD/HOLD) |
| 🔴 disagree | стресс и обзор расходятся ИЛИ обзор BUY/SELL при нейтральном макро |
| 👁 blindspot | `macro_blindspot: true` (доминирует идио α) |
| ⚠ HIGH | `verification_priority: HIGH` — нужна сверка с первоисточником |
| 🔒 blocked | ticker collision / `is_blocked` — исключён из агрегатов |
| ❄ | `on_iis: true` — ИИС-3, без SELL/TRIM |

---

> **«Mode N» в текстах (вьюер 3.20.0).** Тексты советника пишут режим номером; вьюер при показе
> (`_modeLinkify`, повешен на тот же MutationObserver, что `wrapNakedTables`) заменяет
> «Mode 4» на «разбор бумаги (Mode 4)» — ссылкой на таблицу режимов справки (`02-models.md` `{#modes}`)
> (`openModesHelp` → `openHelpAt('modes')` → `uiHelpOpen(..., {files, sections, at})`, ui-kit 1.46.0/1.59). Словарь — `MODE_RU` в viewer.js;
> новый режим скилла → строка в `MODE_RU` и в таблице режимов справки.

### 5.4 Push-уведомления (v3-B, 2026-10-16)

Пользовательская версия — `08-site.md` `{#site-push}` (зеркало, SYNC). Сервер —
`tools/hosting/notify/notifier.py` (контейнер `hub-notify`, Caddy `/api/push/*` с паролем с любого IP),
без LLM. Читает `Claude-Memory` только на чтение; ключи VAPID, подписки, «уже сообщено» и журнал —
в своём томе `notify_data` (D3 не затрагивается).

| Слот (MSK) | Вид (`KINDS`) | Источник | Ключ «уже сообщено» |
|---|---|---|---|
| 08:30 | `cond_date` | условие перешло в «ждёт владельца» по находке монитора: задача NAS переносит `condition_findings[]` свежего отчёта в состояние (`event_found` + `fired` с `data.doc`), push — по строке модуля (а) с `found_at` (`check_conditions_waiting`) | `cond:{id}@{version}:fired` — один push на срабатывание |
| 08:30, своим уведомлением | `cond_open` (тело — «Действия → «Сделать»», у «только сообщить»/`watch` — «Проверить», `_cond_block`) | `plan_conditions_daily` → события состояния через внутренний маршрут hub-api (`fired` по дате и окну отчёта с `data.by_deadline`, `expired`, `done` по новым решениям с `conditions_resolved[]`); push — условия, перешедшие в «ждёт владельца» (`check_conditions_waiting`, несколько — `cond_summary`); при сбое hub-api — очередь | `cond:{id}@{version}:fired` — **один раз** на срабатывание, без ежедневного повтора |
| 08:30 | `verdict` | два последних `weekly-review-{stock,bond}-*.yaml`, `advisor_verdict`; смена считается, только если новая строка стоит в «Сделать»/«Проверить» «Действий» (`action_row`: `verdict_direction` up/down или пункты `verification_checklist` при `verification_priority: HIGH` — одно «срочно» push не даёт, R28; вердикт не «вверх» по бумаге вне последнего снапшота — `held_keys` = `decisions_read.held_keys`, правило 14 модуля (б) — не пушится; без снапшота фильтра по портфелю нет) и не решение владельца (`owner_decided`) | `verdicts:{kind}:{review_date}` |
| 08:30 | `monitor` | HIGH последнего `monitor-report`, которых нет в предыдущем — одним; ссылка `#tab=actions&new={цели через \|}` → окно с полным текстом | `monitor:{дата отчёта}` |
| 08:30, вторым уведомлением | `stale` | дата из имени самого свежего файла вида; пороги = `STALE_THRESHOLDS_DAYS`/`STALE_FAIL_DAYS` вьюера; новые — одним (`stale_summary`) | `stale:{вид}:{дата}:{warn|fail}` |
| 08:30, четвёртым уведомлением | `ahead_review` / `ahead_offer` / `ahead_maturity` / `ahead_pause` (группа `ahead` в `KINDS`, «Напоминать заранее») | `check_ahead`: держимые бумаги последнего снапшота (qty > 0, без `first_buy`); решения и гейт — `last_word.card` через `decisions_read` (срок = `expires_on` гейта акции или `review_by`; конец паузы докупки/IPO — карточка на вчера); `offer_date`/`maturity_date` из снапшота. Пороги — `AHEAD_DAYS` (решение 7/0, оферта 14/3, погашение 7); пауза — в день окончания; сводка `ahead_summary` («Напоминания заранее: N»), в журнале запись на событие; работает и при `ai_mode: off` | `ahead:{вид}:{бумага}:{дата события}:{порог}` |
| 08:30, пятым, только `ai_mode: off` | `no_decision` (без группы; при `on` — молчит, «без разбора» делает обзор советника) | `check_no_decision`: акции последнего снапшота (qty > 0, не `first_buy`, не `is_blocked`, оценка не по `cost_basis`; тип `stock` по `asset_type` или `security-types`), у которых `last_word.card` по всем ключам даёт `decision_id` null — гейт закрыт, блок снимает решение владельца. Облигации/фонды не берутся (гейта нет; на 11.11 это 41+23 бумаги — еженедельная простыня). Одна сводка `no_decision_summary` («Без решения: N акций»), одна бумага — как есть; дедуп `rate` по бумаге 7 дней (`RATE_DAYS`) | `no_decision:{бумага}:{день}` |
| будни 10–18, раз в час | `cond_price` | `GET hub-api/api/moex/quotes?boards=TQBR,TQOB,TQCB`; `check_conditions_price` по строкам `pending` модуля (а), не раньше `not_before`; пересечение порога → push и событие `fired` с `data.price` во внутренний маршрут (`touch_condition`) | `cond:{id}@{version}:fired` (тот же ключ — утром второго push нет) |

Утро — не больше трёх уведомлений: «Ждут решения» (`cond_open`) отдельным, события `cond_date`/`verdict`/`monitor` сводкой (`events_summary`; одно —
как есть, на карточку; сводка — на `#tab=notify`) и просрочки (`stale_summary`) — параметр `combine` у
`process`. Пробное (`POST /api/push/test`) — на все устройства, итог по каждому, 404/410 удаляются; `POST /api/push/prune`
(`keep` — эндпоинт этого устройства) — «оставить только это» / «убрать все» в разделе.
Частота по бумаге — 7 дней на `rate`-ключ; ценовые без сводки: больше 4 — 3 по одному + сводка; тихий режим и
выключенный вид считают событие отработанным. Сверки: `tools/tests/test_notifier.py` (логика, шифрование,
HTTP, контракты хостинга), `tools/tests/test_viewer_push.py` (раздел и ссылки в Chromium/WebKit),
`tools/tests/test_caddy_zones.py` (зона `/api/push/*`).

Пересоздание ярлыка «На экран „Домой“» копит старые подписки — в кабинете у списка устройств «оставить только это» (`/api/push/prune`). С 26.10.2026 устройство и тихий режим — только в кабинете (hub → «Уведомления»); во вьюере («Ещё → Уведомления») — виды портфеля и журнал.

### 5.5 База сайта (plan.json): экспорт и импорт (вьюер 3.79.0, этап 5 ухода от Numbers; с 3.82.0 «База сайта», файлы `site-db-*`)

Карточка `#pf-file` (`buildPlanFileCard`) на странице «Загрузки» (`renderPfBuildTab`, ряд `.pf-loads` рядом с `#pf-ie`; с 3.80.0), в «Общих долях» (`renderOverall`) — строка-ссылка. Пользовательская
версия — `04-tabs.md` `{#tabs}`, сгибы «Доли и цели» и «Общие доли» (зеркало, SYNC).

- **Экспорт** — `GET /api/pv/plan/export?format=json|xlsx` (зона `/api/pv/*`, та же авторизация, что у `GET /api/pv/plan`; нет
  файла → 404, иной `format` → 400). `json` — байты `Portfolio/plan.json` без перекодирования, `Content-Disposition:
  attachment; filename="site-db-<updated_at>.json"`, заголовок `X-Plan-Hash` = hash файла. `xlsx` — `plan_xlsx()` на stdlib
  (`zipfile`, SpreadsheetML без sharedStrings, ячейки `inlineStr`/`n`), до девяти листов: Акции · Классы · Матрица ·
  Корзины · Облигации · Фонды · Ручные позиции · Модель IE (шапка: даты модели и общего портфеля, кэш — строка «Кэш, %» только при `cash_pct`) · История IE (лист только при записях). С 3.82.0 каждый лист — `<dimension ref>` по реальным размерам, закреплённая шапка (`<pane ySplit>`; в «Модели IE» — под шапкой «Тикер…», мета-строки над таблицей) и настоящая таблица Excel (ListObject: `xl/tables/tableN.xml`, `autoFilter`, `TableStyleMedium2`, `displayName` `T_Stocks`… уникальные, `xl/worksheets/_rels/sheetN.xml.rels`, `<tableParts>`, Override в `[Content_Types].xml`); таблица — только при ≥1 строке данных; пустые строки не пишутся; имена колонок уникальны и непусты (пустой ключ истории → `col_N`). `plan_xlsx_sheets` отдаёт `(лист, строки, ширины, номер строки шапки)`. Доли
  классов/матрицы/корзин — в процентах; план и статус акций — словами. XLSX назад не читается (нет такого маршрута и не будет).
- **Импорт** — `POST /api/pv/plan/import {base_hash, plan, reason?≤300, dry_run?, name?}` (тело ≤ 2 МБ). Проверка ДО записи, всё
  или ничего: `schema_version == "plan@1.0"`, верхние ключи только из `PLAN_IMPORT_TOP`, секции `stocks/classes/matrix/
  bond_buckets/bonds/funds/manual_positions` — теми же валидаторами, что `set` (плоские пути прогоняются через
  `PLAN_PATH_RULES`; `manual_positions[].value_as_of` — необязательная дата оценки `YYYY-MM-DD` или `null` (иной формат → 400); поля без правила — `ie_new_pct/ie_old_pct`, `bonds.*.name`, `bond_buckets.*.type/subtype` — проверяются
  типами), `ie_model` (`positions[]` — объекты с `ticker`, числа числами, неизвестные поля → ошибка) и `ie_history` —
  структурно; `iis_qty` вида `5.0` принимается как `5`. Ошибка → 400 `{"error": "bad plan", "problems": [{path, detail}]}`
  (≤ 50). `base_hash` не сошёлся → 409 со свежим планом (и у `dry_run` тоже).
- **Diff** — `plan_import_diff`: плоские пути (объекты — через точку; списки `classes/matrix/bond_buckets/manual_positions/
  ie_model.positions` — по ключу строки `class`, `currency/class`, `key`, `type/name`, `ticker`; `ie_history` — по индексу),
  числа сравниваются с допуском 1e-9; `generated_at/updated_at/updated_by/source` не сравниваются. Ответ `diff: [{path, old,
  new}]` (≤ 2000, иначе `diff_truncated: true`) и `counts: {added, removed, changed, total, by_section}`; пара «нет поля ↔
  null» изменением не считается в обе стороны (отсутствие ключа ≡ `null`; тест — `test_write_api.py`, блок «поля нет ≡ null»). Порядок строк списков не учитывается.
- **Дата оценки ручной позиции** — `manual_positions[].value_as_of` (`YYYY-MM-DD`, необязательное): hub-api при записи `manual_positions.<тип>/<имя>.value_rub` ставит её равной `updated_at` (дата сервера); XLSX — колонка «Оценка на дату» листа «Ручные позиции» после «Стоимость, ₽»; `numbers_to_plan.py` её не пишет (дата баланса в плане неизвестна). Загрузчик (режим сделок с планом): `value_as_of` раньше последней сделки по бумаге (`per_security[T].last_trade_date`) → флаг `manual_value_stale` (вторая ветка, см. `output-schema.md`); карточка фонда показывает подпись «оценка от дд.мм.гггг» под полем «Оценка вручную».
- **Запись** — `dry_run: true` → 200 `{hash, diff, counts}` без записи; пустой diff (и с `dry_run`, и без) → 200 `unchanged: true`, запись без diff не делается
  без записи; иначе `updated_by: "hub-api"`, `updated_at` = сегодня, `source` и `generated_at` берутся из файла (нет — из
  текущего плана), `save_file(..., base_hash)` (копия в `.versions/`), в `plan-journal.jsonl` — одна строка `{ts, who:
  "site", kind: "import", reason, name, n_changes, counts, paths[≤50]}` (строки без `path`; вьюер показывает их в журнале
  «мои» одной строкой). Ответ `{hash, plan, counts, timing_ms}`. `/api/health` → `pv_import`.
- **Круг** «экспорт → импорт того же файла» даёт `unchanged: true` — тест `tools/tests/test_write_api.py` (блок «pv export/import»).
- **Клиент:** скачивание — `authFetch` → Blob → `_downloadBlob` (`a[download]`); выбор файла → `JSON.parse` → dry_run → окно
  `showPlanImportModal` (`planEditOpen.kind = 'fileimport'`, таблица по разделам через `planDiffHuman`) → «Применить»
  (`planImportApply`, причина обязательна) → `state.plan` из ответа. Server.py живёт на NAS: после выкладки — `restart hub-api`.

### 5.6 «Сейчас» в «Долях и цели» (вьюер 3.90.0; зеркало — `05-now.md` `{#now}`)

`RebalanceEngine.runAuto(port, engineGateInputs(), engineCondInputs(), opts)` (входы модулей (б) — решения, справочник бумаг, обзоры — и (а) — определения + состояние) читает `port.ie_actual.per_ticker[t].user_plan / planned_share_pct` из объекта снапшота, поэтому план сайта (`plan.json`) вливается в снапшот всегда: `planApplyAll()` (обход `state.plan.plan.stocks` → `planApplyToSnapshot`) вызывается в `loadPlan` при `status === 'ok'`, после `portfolioLatest = …`, после `applyQuotes` в `loadLivePrices`, перед `runAuto` в `renderIeModel`, после каждой записи плана (`planEditSave`, `ieSetPost`, импорт, `inlinePlanField`). Встроенные списки «План»/«Статус» после 200 перерисовывают раздел (`renderTabContent`) или карточки (`renderCards`) с сохранением прокрутки.

Правила движка (зеркало `gate_aware_sizing.py`, паритет — `test_rebalance_parity.py`):
- доля факта = стоимость / книга акций основного счёта по живым ценам (без ИИС-3 и замороженных); коридор ±1 п.п. (`hysteresisPp`), внутри — «спит»;
- докупка (`autoCycleFlags`, gap < 0 и пусто `blockingReasons`): блокируют гейт `new_position` / `review_needed` / `reviewed_under_review` / `review_aging`, ждущее условие на покупку, условие с продажей по порогу или «держать» в окне (`autoStopCondition`), IPO-гейт (< 8 кварталов торгов), план `WAIT`, лимит по эмитенту 15 % (Сбер 20 %);
- слова плана (`user_plan`; константы `EXPLICIT_NO_BUY_PLANS = {WAIT, WAIT/TRIM, KEEP, SELL}`, `NO_BUY_DORMANT_PLANS = {KEEP, SELL}`, `AUTO_TRIM_PLANS = {BALANCE}`, `AUTO_SELL_PLANS = {SELL}`; 3.94: SELL → `trim = 0` при любой доле `real > 0`, до проверки блокировок — гейты и условия продажу не держат — в `rebalance-engine.js` и `gate_aware_sizing.py` одинаковые, сверяет `test_rebalance_parity.py`): KEEP — недобор и перевес «ничего» (dormant, reason `user_plan:KEEP`); BALANCE — недобор докупка, перевес срез до плана; BUY — недобор докупка, перевес ничего; WAIT — недобор «ничего», блокировка `user_plan:WAIT`; SELL — недобор «ничего» (dormant `user_plan:SELL`), перевес — срез до нуля БЕЗ коридора (вес 0 в `rebalancing`, цель 0 ₽, лоты вверх по всей позиции; план пустой/0/null не отбрасывает строку); лимит концентрации на SELL не влияет;
- таблица «План → К моему плану» (3.89.0): без горизонтальной прокрутки на 1280+ (контейнер 1146 px) — `rb-v-watch`: колонки `noteie`/`noteai` скрыты (есть в окне правки ✎ и в карточке), «Цель IE 12 мес» — число и потенциал, долгосрок в `title`, «Сейчас» с переносом;
- слова плана и база (`HOLD_IN_BASE_PLANS = {KEEP, BUY}`): KEEP и BUY без операции (dormant) — в F своими текущими рублями, вес в S не кладётся (решение владельца 11.11: бумага не торгуется, её рубли ≠ w × база, иначе инвариант «книга после сделок = база» ломался — на живых данных база 4,388 вместо 4,756 млн, CNRU резался до 2,77 % вместо 3 %); `hold` у `autoCycleFlags` / `hold_weights` → `base_weight_pct` у dormant-строки остаются меткой, на расчёт не влияют; SELL — вес 0 в rebalancing; WAIT, гейт, условия, IPO-гейт, лимит эмитента, бумаги в коридоре без слова-исключения — в F; без блокировок база = полный план класса, при S ≥ 0,99 — `manual_check_required` (`t_full_no_gates`); во вьюере блокирующий гейт — плашка `gatePill` под тикером в ячейке «Бумага»; покупка требует и плана, и гейта, продажа — только плана;
- причыны блокировки собираются полностью (`blockingReasons` + `autoStopCondition`, порядок гейт → условия → IPO → план) в `reason` через «; », `unblock_by` — по первой причине с датой; вьюер (`REASON_RU`) переводит каждый код в слова со своей датой из gate-reviews/conditions, кодов на экране нет;
- срез: доля выше плана больше коридора И `user_plan = BALANCE`; срез — только по слову плана (BALANCE, SELL), отдельной ветки «гейт → срез» нет: под блокирующим гейтом срез предлагается только при плане «привести к плану» или «продать»; докупать под гейтом нельзя (пороги статусов гейтов — 1 п.п., как коридор);
- база целей (§10.6 п.2 спеки trim-fix, 11.11): непрерывная — неподвижная точка `F / (1 − S)` при любом составе F (заблокированные и спящие одинаково, `compute_fixed_point_target(full_plan_without_gates=False)`), цель торгуемой бумаги = её вес × база; план класса (`t_full_no_gates`) — только когда в F ничего нет; снятие последней блокировки базу не прыгает;
- разрыв «план − база» (`blocked_gap_rub`, совместимость) = `gap_gated_rub` (недобор заблокированных до их доли плана) + `gap_in_corridor_rub` (спящие, со знаком) + `gap_unallocated_rub` (Σ плановых долей < 100 %), каждое на (1 − S_eff); норма кэша советника — только `gap_gated_rub`; плитка вьюера «не размещается сейчас» читает `blocked_gap_rub` (`viewer.js` `nowTile`);
- каскад одним расчётом (§10.6 п.1): `runAuto`/`run_auto` итерируют «сделки → идеальное исполнение → доли от новой книги → переклассификация», торгуемая бумага остаётся в наборе, до неизменного набора (предел — бумаг + 1); результат `cascade {iterations, converged, added}`, строка `cascade`; не сошлось — первый проход и `converged: false`; докупаемая с целью ниже текущей уходит в F; §10.3а («на плане») отменён (§10.7) — повторный расчёт после идеального исполнения даёт ноль сделок всегда;
- горизонт известных дат (§10.6 п.7; `defaults.known_dates_horizon_days` = 7): недобранная заблокированная бумага, блокировка которой снимается в известную дату ≤ 7 дней и на ту дату гейт открыт целиком (`LW.card` с today = дата), — открыта для базы срезов (`base_trim_rub`, `horizon`), сегодня не покупается (строка `opens_on`, `opens_if_price_holds`); функции `knownOpenDate`/`condLift` ↔ `_known_open_date`/`_cond_lift`;
- предохранитель базы (3.92.0): `base = min(T*, T_full)`; сработал предел — `base_source = fixed_point_capped`, `blocked_gap_rub = 0` (и три слагаемых — нули) (JS — в `runAuto`; Python — `compute_sizing` передаёт `t_full=class_plan_rub` в `compute_fixed_point_target`, результат `capped`); срез от той же базы; паритет — фикстура «F выше доли» в `test_rebalance_parity.py`;
- замороженная бумага — в F своими рублями (§10.7, 11.11; правило 3.95.0/3.97 «перевешенная заморозка на плане» — `frozen_plans`/`book_rub` в `compute_fixed_point_target`, `frozen_on_plan`, `frozen_at_plan`, `at_plan` — отменено и удалено из кода и выхода): строки `blocked` и dormant без `hold`/`base_weight_pct` — `frozen` (рубли в F) и `frozen_reason` (коды причин; блокировка/заметка, иначе `blockingReasons` + стоп-условие); подпись «выше плана» — во вьюере по `real_pct > plan_pct` (`frozenAbovePlan`). Ручной режим (`run_sizing`) классифицирует и считает так же — разбор бумаги и ребалансировка советника считают базу так же, как «Сейчас». Где видна заморозка во вьюере: «стоит: …» в колонке «Сейчас», сгиб «заморожено: N бумаг · X млн ₽» под плитками (`frozenFoldNode`), строка «Для базы «Сейчас»» в блоке «Решение» карточки (`cardBaseNode`); подстрока «условие: разбор до …» (`reviewCondText`) — для ждущих `kind: review` (напоминание, не блокировка; у строк «стоит:» не дублируется);
- подпись цели под «Сейчас» (3.92.0, `nowGoalSub`): «до X % книги после сделок · база N» (`base_rub` движка), для SELL — «до 0 % · выход»; плитка — «книга сейчас» (`class_fact_rub`) рядом с «база докупки»; «Факт» считается от книги сейчас, цель — от базы;
- первая покупка (3.90.0; `firstBuyCandidates` ↔ `first_buy_candidates`, `FIRST_BUY_PLANS = {BUY, BALANCE}`): тикер `ie_actual.per_ticker` с `planned_share_pct > 0` и `user_plan` BUY/BALANCE без активной акции в снапшоте (замороженные/cost_basis и денежный рынок позицией не считаются; запись с qty = 0 идёт обычным путём) превращается в синтетический holding (`first_buy`, qty 0, value 0) и проходит те же правила; гейт: нет записи / `new_position` / `divested` → `gate:new_position` (`unblock_by` «после разбора бумаги»), остальные блокирующие — как обычно; IPO-гейт для таких бумаг не считается (возраста листинга нет). Цена: `quotes@1` (`opts.quotes` в JS = `state.live.quotes`, `quotes=` у `run_auto`; `api/moex/quotes` отдаёт всю доску TQBR, запрос не расширялся), иначе `ie_model.positions[].current_price_rub` (`opts.iePrices` во вьюере берёт модель с сайта), иначе блокировка `no_price`; лот из котировки, иначе 1 (`lot_known = false`), и тогда `lots = null`, `trade_rub = null` (считается только сумма `delta_rub`; вьюер: «купить ≈ X ₽ · первая покупка · лот уточни по котировке»). Строка результата несёт `first_buy`, `price_source` (`live` / `ie`), `lot_known`; вьюер дописывает «· первая покупка», пометку «по цене IE»;
- база «к цели IE» (`mode === 'ie'`): колонки без «Сумма, ₽» и «План» (слово плана правится в «К моему плану» и в окне ✎), с «Мой план, %» (3.119.0: `planCell(r, true)`, сортировка `planV` = `planPctOf` — сайт, иначе снапшот; та же колонка в «Все бумаги»; ✎ у бумаги вне портфеля и плана создаёт `stocks.T.plan_pct` через `POST api/pv/plan/set`) и «Гейт» (нет записи в gate-reviews или `divested` = «новая»; блокирующие — `tag trim`, разрешающие — словом; сортировка: блокирующие, затем разрешающие); плашка гейта под тикером в этой базе не рисуется; бумаги плана с долей > 0 входят в список тикеров;
- сортировка таблицы: производные поля строк (`userPlanW`, `userStatusW`, `markTs`, `absDev`, `gateRank`) считаются ДО `sortBy(rows, …)`; версия движка — `ENGINE_VERSION` в шапке `rebalance-engine.js`, равна `?v=` в html;
- путь новой бумаги — `05-now.md` `{#now-new}` (импорт IE → гейт «новая» → разбор → мой план → «Сейчас» предлагает первую покупку → покупка и снапшот → докупки до плана → истёк срок → «оценка устарела»);
- как снять гейт — §3.4а и `06-gates.md` `{#gates}` (новое решение: разбор бумаги mode_4, оценка качества mode_8 — `decision_write.py from-report`; решение владельца — `decision_write.py owner` или сайт — при «с ИИ» гейт качества не открывает (правило 9а), при «без ИИ» — единственный способ снять статусный блок (разбор советника там не предполагается); срок — `review_by` решения, null → +60 дней, класс бумаги срок не задаёт; истечение и `review_aging` считает модуль (б) при чтении); в карточке акции блокирующие статусы несут фразы-чипы «Что сказать Claude»;
- снять блокировку: разбор бумаги у советника (гейт), фраза Claude с «Действий» (условие), правка плана/статуса на сайте. Подробно — `skills/ru-portfolio-advisor/references/gate-aware-sizing.md`.

### 5.7 Справка вьюера: раздел = файл

Пользовательская справка — 10 частей `tools/assets/help/viewer/NN-slug.md` (правятся только в репо; на сервер их везёт `deploy.zsh` вместе с `assets/`, путь `/tools/assets/*` в Caddy публичный). Вьюер (`showHelpModal`, `openModesHelp`, `openGatesHelp` → `openHelpAt(якорь)`) грузит части через ui-kit `uiFetchMarkdownParts` / `uiHelpOpen({files})`, склеивает через `\n\n` и показывает читателем в режиме `sections: true` (оглавление = переключатель разделов, поиск по всему документу). Офлайн держит все части (`CAB_PAGES` в `sw-offline.js`).

| Файл | Якорь | Что внутри |
|---|---|---|
| `00-about.md` | — | SYNC-шапка и «как пользоваться справкой» (в оглавлении — «О справке») |
| `01-run.md` | `run` | что гонять и в каком порядке, полные команды, прогноз на дату, горизонты |
| `02-models.md` | `models`, `modes` | модели по скиллам; таблица режимов советника (на `modes` открывают ссылки «Mode N») |
| `03-fresh.md` | `fresh` | пороги плашек (= `STALE_THRESHOLDS_DAYS`/`STALE_FAIL_DAYS`), схема зависимостей |
| `04-tabs.md` | `tabs` | вкладка → что показывает → откуда (ячейка ≤ 300 знаков), «как устроен вьюер» сгибами |
| `05-now.md` | `now`, `now-new` | слова плана × недобор/перевес/база, блокировки, база докупки, путь новой бумаги |
| `06-gates.md` | `gates` | статусы гейтов словами, фразы снятия, неразворот и лимиты (на `gates` открывает окно «🛡 Решения») |
| `07-conditions.md` | `conditions`, `conditions-priority` | виды условий, метки, фразы Mode 9, приоритет |
| `08-site.md` | `site`, `site-build`, `site-journal`, `site-push` | сборка снимка на сайте, журнал решений, уведомления |
| `09-limits.md` | `limits` | чего вьюер не делает |

Формат раздела: `## N. Заголовок {#slug}` → 2–3 фразы «зачем» → таблица → «Что сказать Claude» (фраза `(#copy)` · модель, effort) → «Где это видно на сайте» → сгибы `<details><summary>Подробнее: …</summary>`. Пометок версий, путей файлов, флагов CLI и кодов статусов в справке нет — они здесь. Контракт частей (файлы, якоря, ячейки ≤ 300, ноль пометок версий, ссылки только на существующие якоря, модель у каждого режима, пороги «Свежести» = вьюер) — `tools/tests/test_pages_contracts.py`, блок «вьюер · справка из частей».

## 6. Свежесть артефактов (пороги)

> **Плашки = пользовательская шкала.** Список устаревшего на «Сегодня» во вьюере и сводка
> отчётов на хабе используют два уровня — «плашка» и «жёсткая плашка» (числа — таблица
> `03-fresh.md` `{#fresh}`). Они живут в коде страниц (`STALE_THRESHOLDS_DAYS` +
> `STALE_FAIL_DAYS` в `tools/assets/viewer.js` ↔ `CONFIG.reports[].staleAfter/failAfter` в
> `tools/hub.html`; недельная инфляция `macro-snapshots/inflation/*.jsonl` (9 / 16 дн., дата внутри строк — у хаба `jsonl: true`) — в обоих местах, автосрез и результат
> `macro-forecast-chain` плашкой не меряется (решение 2026-10-16); синхронность держит ось «свежесть» в
> `tools/tests/test_pages_contracts.py`) и здесь не дублируются. Таблица ниже — **годность
> входа самого `integrated-view`** (его собственный гейт, шире плашек для стресса: 90/180
> против 30/60 у режимов 3 и 8 советника). `portfolio-coherence-audit` со своим окном
> (интеграционный анализ ≤ 14 д) плашками не покрывается.

| Артефакт | OK | Warning | Отказ |
|---|---|---|---|
| snapshot | ≤ 14 д | > 14 д | > 30 д |
| stress (режим 8) | ≤ 30 д | 30–60 д | > 60 д |
| stress (integrated-view) | ≤ 90 д | > 90 д | > 180 д |
| weekly-review | ≤ 14 д | > 14 д | > 30 д |

Если хоть один вход у `integrated-view` за критическим порогом — синтез
отклоняется. Дополнительно работает **stale-pipeline gate**: если доля
catalyst с unresolved `macro_dependency` > 30%, синтез тоже отклоняется
(нужен `macro-forecast-chain --mode RECALIBRATE`).

### Веса сценариев по горизонтам (с 2026-08-05)

> **Единый источник (2026-11-06).** Действующие веса — файл сайта `scenarios/stress-weights-<матрица>.json`: его читают стресс
> (`stress_recalc.py`, `stress_build.py`) и RECALIBRATE макро-цепочки (`recalibrate.py` через `_shared-references/scenario_weights.py`:
> на даты прогнозов — линейная интерполяция по дням между сроками сайта, вне сроков — ближайший). Веса в матрице — исходные на её
> дату и действуют, только пока файла сайта нет. Советник (`stress_digest.py`) и аудит (`build_coherence_bundle.py`) читают числа
> стресса из `Portfolio/stress/auto/recalc-<самый свежий стресс>.yaml`, если он есть; возраст — по дате суждений.

Матрица `geopolitics-ru-west-2026-07-01` несёт `p_by_horizon` — убеждение на
срок вместо одного набора вероятностей. Что из этого следует для порядка работы:

- **Стресс.** `build_stress_stub.py` переносит блок из SSOT в стресс-стаб, но
  только если он покрывает все горизонты прогона; при частичном покрытии веса не
  переносятся и причина печатается в стаб. Дальше веса читают все ноги
  total-return (цена, carry, идио, MC, вьюер). С v2.13.2 вьюер горизонтные веса
  ещё и показывает: подпись «Вероятность» карточки сценария — вес выбранного
  горизонта (до этого рисовался скаляр = h12 на всех горизонтах), в сводке
  Стресса — «Ожидание (по весам)» из `expected_pl_pct_by_horizon`.
- **RECALIBRATE такую матрицу ПОДДЕРЖИВАЕТ** (MFC-5 шаг 2, 2026-08-06): каждый
  горизонт Layer 2 агрегируется весами СВОЕГО горизонта — даты `marginal.values`
  сопоставляются датам матрицы (`horizon_intermediate` + `horizon`). Прогнозы с
  горизонтами вне дат матрицы (h18-файлы `2027-12-31`) пропускаются целиком и
  громко (`SKIP:`/`skipped_files`) — интерполяция весов запрещена сознательно.
  `method: axis_dependent` (urals_discount) не пересчитывается, как и раньше.
  Приёмка: brent/usdrub бит-в-бит с bundle 08-06. Помнить про
  [MFC-6](TODO.md#mfc-6): реально изменяемые файлы переформатируются целиком
  (`yaml.dump` уносит комментарии).
- **Архив не пересчитывается.** RECALIBRATE трогает только `status: active`
  (24 из 31 прогноза библиотеки — `superseded`, и они ссылаются на ту же матрицу,
  что и активные преемники). Всё пропущенное печатается строками `SKIP:`.
- **Полярность обязана быть объявлена** (`matrix.polarity`), если веса выводятся
  из убеждений по осям: перепутанная не падает, а зеркалит веса.

## Пересчёт стресса сайтом (вьюер 4.4.0)

Числа вкладки «Стресс» берутся из `Portfolio/stress/auto/recalc-<имя стресса скилла>.yaml` (пишет `hosting/notify/stress_job.py`
после «Сохранить» снапшота — шаг `stress_recalc` в `pf_build.POST_STEPS` — и по `POST /api/pf/stress/weights`). Схема файла — стресса
плюс блок `recalc` (`skills/portfolio-scenario-stress/references/stress-recalc.md`). Суждения (беты, тексты, оговорки) переносятся из
стресса скилла как есть, поэтому при `recalc.narrative_stale` вкладка отмечает один раз, что текст написан для чисел стресса скилла.
**Возраст и устаревание стресса считаются по дате суждений** (`stressCurrent.date` = дата стресса скилла), не по дате пересчёта: файл
пересчёта подменяет только `stressCurrent.parsed`. Интегрированный вид берёт числа из того же файла: при наличии
`auto/recalc-<самый свежий стресс>.yaml` в payload идёт он (`aggregate_positions.stress_recalc_info` → `validation.stress_recalc`,
возраст — по дате суждений), в шапке отчёта — `inputs.stress_recalc_at`; `ivRecalcNote` молчит, когда оно равно `recalc.at`.
Напоминание о сроках: `stressTermsDue(horizon_ends, today)` во вьюере — `today > plus_months(min(ends), -3)` с обрезкой дня по длине месяца
(⚠ SYNC: `stress_build.shift_horizons`, `SHIFT_WHEN_MONTHS_LEFT = 3`); только строка «Действий» (сливается со строкой «перегнать стресс»), примечание на «Стрессе»
и отметка на «Сегодня» — числа и веса сайт не пересчитывает.
Оговорку о сроке за пределами прогноза (`HORIZON_EXTRAPOLATED`, `source: script`) пишет `stress_recalc.script_caveats` при сборке
и при каждом пересчёте; остальные оговорки — суждения модели и переносятся как есть. Веса сценариев — `scenarios/stress-weights-<матрица>.json` (`stress-weights@1`):
`GET /api/pf/stress/weights` (`weights`, `horizon_ends`, `axes`, `scenario_names`, `horizons_changed`), `POST` с `apply:false` («а что если»)
и `apply:true` (запись + пересчёт, причина обязательна); сплиты — `POST /api/pf/splits` (`add`/`dismiss`) из панели сборки по
предупреждению `split_suspected`. Дата проверки рейтинга облигации (`credit_rating_checked_at`) — правило `ratingCheckDue` во вьюере
повторяет `_shared-references/rating_check.py`; паритет закреплён в `tools/tests/test_viewer_stress_recalc.py`.

## Сроки с сайта и подхват макро-таблицы (вьюер 4.5.0)

Решения владельца 06.11.2026; формулы не менялись — изменилось, кто и когда запускает тот же расчёт (журнал заморозки —
`_cross-cutting/forecast-calibration-calendar.md` §6).

**Файл сроков — `scenarios/horizons.json` (`horizons@1`), единственный источник дат прогнозов и стресса.** Пишет только сайт:
`POST /api/pf/stress/terms` (`confirm:false` — проверка, `confirm:true` — запись с причиной, прежнее состояние в `history`, 20 записей;
`stress_job.post_terms`, разрешённый путь записи — `JOB_WHITELIST` hub-api). Правила: 1–6 меток `hN`, даты строго возрастают по N,
`primary_horizon` среди меток, при записи все даты позже сегодняшней. Невалидный файл читатели считают отсутствующим и говорят об этом.
Читают:

| Кто | Что делает с файлом |
|---|---|
| `stress_build.py` (`--library-root`) | сроки прогона — из файла (режим anchored), автосдвиг `shift_horizons` выключен; до ближайшего срока меньше 3 мес — предупреждение «сдвиньте на сайте»; явные `--horizons`/`--anchor-dates` с другими датами — отказ; сроки прошлого стресса отличаются — предупреждение и напоминание пересмотреть политические пути |
| `forecast-confidence-applier`, `macro-forecast-chain` (текст скиллов) | даты `horizons` прогноза и `chain_target_horizons` — все даты файла; другие даты в запросе — сказать о расхождении, файл не менять |
| `stress_digest.py` советника (`--horizons-file`) | `terms: {stress, site, match}`; несовпадение → `stress_terms_mismatch` в `warnings` |
| `aggregate_positions.py` интегрированного вида (ключ payload `horizons_file`; `horizons` занят списком горизонтов) | несовпадение → `validation.stress_terms_mismatch`, код `STRESS_TERMS_MISMATCH` |
| сайт (`stress_job.read_terms`) и вьюер (запись типа файла сроков из общего набора; `PV_DIRS`: `scenarios/` с `^horizons\.json$`) | блок «Сроки» в окне «Настройки стресса», `terms`, `terms_mismatch`, `terms_history` в `GET /api/pf/stress/weights`; строки «Действий» |

Файла нет — всё работает по-прежнему (сроки переносятся из прошлого стресса). Запись сроков не трогает ни веса, ни стресс, ни пересчёт:
дальше сайт только напоминает, что не на новых сроках.

**Подхват макро-таблицы.** `stress_recalc.py --macro-scenarios ФАЙЛ` пересчитывает числовые факторы сценариев, `baseline_spot`,
`horizon_coverage` и уровень ставки купонного слоя по сетке макро-файла на сроки стресса — тем же кодом, что `stress_build` в режиме
«из макро-файла» (`stress_recalc.apply_macro`; равенство чисел закреплено `test_recalc_macro_equals_build`); санкционный и геополитический
пути остаются из стресса. Отказ кодом 1: макро-файл не проходит `validate_macro` или собран на другой матрице. В блоке `recalc` —
`macro_input`, `macro_input_was`, `reason: macro`. Сайт (`stress_job.macro_state`):

- `latest` — самый свежий `macro-chain/macro-scenarios-*.yaml` (дата в имени → время записи → имя);
- `apply` — подставлять ли его в **каждый** пересчёт: таблица новее той, что записана в самом стрессе скилла (другое имя с большим
  ключом либо то же имя, записанное позже файла стресса), и матрица та же. Сравнение идёт со стрессом, а не с прошлым пересчётом:
  источник пересчёта — всегда стресс скилла, и без этого следующий пересчёт вернул бы числа на прежнюю таблицу;
- `newer` — действующие числа ещё не на `latest` (сравнение с `recalc.macro_input` свежего пересчёта) — это причина сайту пересчитать самому;
- `blocked: "matrix"` — матрица макро-файла другая: нужен прогон скилла;
- отказ скрипта с макро-таблицей не роняет пересчёт: он повторяется без неё, в сводке `macro_error`; ошибка помнится по версии
  макро-файла (имя + время записи) — обычные пересчёты её больше не пробуют, «Пересчитать» пробует снова.

**Когда сайт пересчитывает сам** (`refresh_if_needed`, запускается запросом весов при открытии «Стресса»): пересчёт устарел
(`stress_replaced`) либо появилась макро-таблица новее действующих чисел (`macro`); повтор для той же пары версий — не чаще 10 минут.
Состояние — `refresh: {state, reason, error, at}` в `GET /api/pf/stress/weights` (в памяти процесса hub-notify).
`POST /api/pf/stress/recalc` — тот же полный пересчёт по кнопке, синхронно.

**Вьюер 4.5.0 (`tools/assets/viewer.js`).** Типы записей: `stressMd` (`Portfolio/stress/*.md` — отчёт скилла, кнопка «Отчёт скилла»,
окно `showDocModal`; над текстом — для каких чисел написан, если вкладка показывает пересчёт) и `horizons` (`scenarios/horizons.json` →
`state.data.horizons`: только валидный файл, `horizonsInvalid(j)` по правилам `horizons@1`, иначе null и предупреждение); списки папок
`loadHttpMode1` и `PV_DIRS` сервера — строка в строку (сторож `test_write_api`). На «Стрессе» сгиба весов нет: строка состояния
`#stress-status` («Сроки: до … · веса …»), кнопки `#stress-settings-btn` и `#stress-report-btn`, плашка `#stress-refresh-banner`
(«Идёт пересчёт…» по `refresh.state` ответа весов, после «Применить»/«Пересчитать»; ошибка — «Не пересчитано: …»), заметки
`#stress-terms-mismatch`, `#stress-macro-blocked`, `#stress-recalc-stale`. `swLoad(force)` запрашивает `GET /api/pf/stress/weights`
при отрисовке вкладки; ответ перерисовывает плашку и заметки на месте (`stressUiSync`), `stressAwaitRefresh` опрашивает `refresh.state`
(и старые флаги `recalc_stale`/`recalc_refreshing`). Окно «Настройки стресса» (`showStressSettings`, документный слой `docOpen`):
сроки (`termsDraw` → «Сдвинуть сроки»/«Подтвердить сроки» `#st-shift` → поля `#st-d-hN`, подстановки `#st-fill-today` (от сегодня
6/12/24) и `#st-fill-halves` (концы полугодий) → `#st-check` = `POST terms {confirm:false}` + `termsRerunList` («что придётся перегнать»:
прогнозы без дат новых сроков — без санкционного и геополитического, они на датах матрицы; макро-таблица по ключам
`scenario_weights_by_horizon`; стресс; веса) → `#st-reason`, `#st-save` = `POST terms {confirm:true}`), блок весов `#sw-box` (прежние id и
логика), одна кнопка `#stress-main-action` (`data-mode` recalc → `stressRecalcNow` = `POST /api/pf/stress/recalc`; apply — прежний путь с
причиной), строка `#stress-last-recalc`. Без связи — только текст. Состояние `SW`: `recalcBusy`, `mainErr`, `te`, `loading`.
«Действия» (`stressSay(kind)`, `STRESS_TERMS_CHAIN` / `STRESS_MACRO_ONLY` / `STRESS_ONLY`; `stressTermsShift`, `stressMacroBlocked`):
сроки сайта не совпадают (`data-stress-termsshift`) → полный пайплайн + стресс + «затем задать веса» текстом, остальные строки стресса
сливаются в неё; матрица заменена — как раньше; прогнозы новее макро-таблицы → только `/macro-forecast-chain Обнови макро-прогноз`
(«стресс сайт пересчитает сам»; стресс старше 30 дней — прежняя слитая строка с двумя командами); макро-таблица не подставлена
(`macro.blocked`/`macro.error` из ответа весов — есть только после открытия «Стресса» при связи; `data-stress-macro`) → команда стресса с
причиной; стресс старше 30 дней → только команда стресса; бумаги без чувствительности → только команда стресса; «до ближайшего срока
меньше 3 месяцев» — по срокам сайта, без команды («сдвиньте сроки: «Стресс» → «Настройки стресса»»). Тесты —
`tools/tests/test_viewer_stress_settings.py`, `test_viewer_stress_recalc.py`, `test_viewer_actions_blocks.py`.

**Когда нужен скилл стресса:** новая бумага без чувствительности, санкционное событие, замена матрицы, сдвиг сроков (политические пути
задаются заново), стресс старше 30 дней по дате суждений (пересмотр суждений и текста). Пересборка прогнозов на той же матрице и тех же
сроках скилла стресса не требует: достаточно `/macro-forecast-chain Обнови макро-прогноз`.

## Дневной ряд цен закрытия (hub-notify, с 11.11.2026)

Фоновая задача `prices` (`tools/hosting/notify/prices_job.py`, расписание `JOB_TIMES` в `notifier.py`): по будням в 19:00 МСК
(повтор 20:00 при сбое; пропущенные дни не догоняются) берёт держимые бумаги последнего снапшота (qty > 0, без `cost_basis`
и blocked), котировки `/api/moex/quotes?boards=TQBR,TQOB,TQCB[&fx=…]` (облигация — по тикеру, иначе по ISIN, как `bondItem`
вьюера) и дописывает **одну строку на торговую дату** в `Portfolio/prices/daily-ГГГГ.jsonl`: `date`, `recorded_at`, `fx`,
`items{ключ → close, kind[, accrued, face, face_unit]}`, `missing`. Только вперёд: истории назад нет; стоимость портфеля и XIRR
не пишутся — вьюер посчитает из цен и позиций. Строка даты, которая уже есть, не перезаписывается. Выходной и праздник
(большинство цен — `prev_close`, либо дата торгов ≠ сегодня) — строки нет, в журнале `_jobs/log-*.jsonl` статус `skip`.
Запись — `jobs.save` (`/api/job/save`, `base_hash`, один повтор при 409), писатель только hub-notify.

**Читает вьюер (график цены в карточке, VW-DAILY):** `PV_DIRS` отдаёт `Portfolio/prices/daily-ГГГГ.jsonl` текстом (папка есть и в
`loadHttpMode1`, сторож — test_write_api), `classifyByName` → `priceDaily`, `state.data.priceDaily` (сырой текст по годам). Разбор —
`dailySeries()`: индекс `тикер → [[дата, закрытие]…]` по возрастанию, годы склеены, один раз на набор файлов (мемо по массиву
`priceDaily`, он новый при каждой загрузке), битая строка пропускается. `priceChartNode`: линия = объединение по дате — снапшот
(цена снапшота) > закрытие ряда; сегодня — живая цена MOEX вместо снапшота и закрытия; маркеры `.pc-pt` только у снапшотов и
живой точки, дни ряда — линия без маркера. Больше 400 точек — `priceThin`: окна, в каждом первая/последняя/min/max, все не-закрытия
(снапшоты, живая) остаются; прореживается только рисование. Подсказка ближайшего дня — один `.pc-float` на поле графика (наведение,
касание), подпись «закрытие» / «снапшот» / «MOEX сейчас». Нет ряда — график по снапшотам, как до VW-DAILY. «Динамика» читает тот же ряд (`dailyDays()` — строки дней, один разбор с `dailySeries`; курс дня без значения — последний известный):
`dynDaily()` считает на каждый день ряда (с даты первого снапшота, дни снапшотов — маркеры со значением снапшота) стоимость = кэш опорного
снапшота (последний с датой ≤ d) + Σ qty × `livePosUnit` по незаблокированным позициям (без цены в ряде — оценка снапшота) и XIRR
(`liveTerminals` над `returns.live_basis` + потоки ≤ d + конечная стоимость; Ньютон из прошлого корня, `xirrDay`) — только при `live_basis`
у опорного снапшота. Провенанс рядов: снапшотные точки — как раньше (`buildXirrHistory`, `balance_summary.total_current_rub_incl_iis`),
дни — пересчёт вьюера (не данные снапшота); сделок после снапшота нет. Мемо — `priceDaily` + `portfolioHistory`.
