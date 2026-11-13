> Приложение к `inventory.md` (этап 1, срез 30.10.2026). Собрано субагентом Sonnet только чтением; ключевые утверждения выборочно перепроверены оркестратором по коду и данным, остальное — с опорами файл:строка внутри. Реальные суммы, количества и доли портфеля не приводятся.

# Агент 2 — аналитика (группы B, F, G) и данные трассировок. Этап 1 плана «структуры данных»

Только чтение. Мак-зеркало Synology (`~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/`); для `plan.json`, `plan-journal.jsonl`, `conditions.yaml`, `gate-reviews.yaml` — копии с NAS от 30.10 17:39 ((скрипты замеров — в scratchpad сессии, в репозиторий не входят); `conditions.yaml`, `gate-reviews.yaml`, `plan.json` на Маке байт-в-байт совпали с копиями, `plan-journal.jsonl` на Маке короче). Интерпретатор — pyenv 3.12.9, PyYAML 6.0.3 есть. Суммы, количества и доли портфеля не приводятся. Скрипты — (скрипты замеров — в scratchpad сессии, в репозиторий не входят) (`a_reports.py`, `a_blocks.py`, `b_keys.py`, `b_k3.py`, `d_collect.py`, `d_extras.py`, `d_render.py`).

Файлы: трассировки — `trace-GMKN.md`, `trace-MDMG.md`, `trace-RU000A106EP1.md`, `trace-forecast-brent-price.md`; частоты ключей обзоров — `b_keys_stock_since0830.txt`, `b_keys_bond_since0830.txt` (без значений).

---

## A. `Portfolio/reports/` — frontmatter и машинные блоки

**Состав.** 54 объекта: 53 `.md` + `2026-06-25-advisory-portfolio-iis3.yaml`. У 4 `.md` frontmatter нет вовсе (`2026-06-25-advisory-portfolio-iis3.md`, `2026-06-25-ie-posts-review-ofz-finance-growth.md`, `2026-08-25-macro-report-ai-debt-treasuries-2026-08-25.md`, `bond-bridge-planner-2026-05-13.md`); у `portfolio-candidates-outside-ie-2026-05-13.md` frontmatter частичный (нет `kind`, `mode`, `tickers`). Разобрано: 49 файлов с frontmatter.

| Поле | Факт (опора: `a_reports.py`) |
|---|---|
| `kind` | `tactical_rebalance` 25, `single_analysis` 15, `scenario_analysis` 3, `general` 3, `bond_bridge_planner` 1, `candidates_outside_ie` 1, нет — 1. Mode 8 (оценка качества книги) лежит как `tactical_rebalance`: 3 файла «чистого» Mode 8 + 3 комбинированных. Значения `stock_quality`, которое ждёт `prior_digest.py` (`_REVIEW_KINDS`, стр. 184), в данных нет — K5 |
| `mode` | 27 разных строк у 48 файлов (+ `None`): `4 (single)` 9, `free_form` 5, `3 (rebalance_opinion)` 4, `8 (stock_quality_forward_review)` 3, `5a (fund analysis)` 2, `3 (rebalance) + 4 (single)` 2, … «+»-комбинации, разные написания одного режима («3 (rebalance)», «3 (rebalance opinion)», «3 (rebalance_opinion)», «3/4 (…)»), `8 (stock quality forward review)` без подчёркиваний — K5. Машинно режим не выделяется |
| `tickers` | есть у 48 из 49; значения — тикеры (340 вхождений) и ISIN (172), имён бумаг в `tickers` отчётов нет; у 3 файлов список блочный, у остальных строчный. Ключ бумаги тикер/ISIN смешан в одном поле — K6 |
| `created_at` | у 41 из 49, формат `YYYY-MM-DDTHH:MM` без пояса. Нет у 8: 3 файла мая (v1/v2 «planned-shares-opinion»), `2026-08-01-…ie-changes`, `2026-08-15-…plzl`, `2026-08-19-…cash-deploy-fixed-point`, `2026-10-02-general-ie-webinar` и **`2026-10-29-…x5-ifrs-3q26`** (самый свежий). Сверка с mtime (14 файлов 19.09–29.10, из них 13 с `created_at`): совпадает до минуты у 12; **GMKN 29.10: created_at 17:40, файл записан 17:34** (+6 мин) — поле не отражает момент записи (K6). В расклад. слоя «10 полей» поле не входит (`claude-memory-layout.md`, строка про `Portfolio/reports/`) |
| прочие ключи | `supersedes/superseded_by/superseded_date/superseded_reason/status` — по 3 файла, `review_date`, `horizon_end`, `note` — по 1 |

**Машинные блоки в теле** (`a_blocks.py`; ```-блоки по типам). В 11 из 53 отчётов есть блок директивы гейта; семь разных форм одной сущности:

| # | Форма блока | Файлов | Пример (обезличен) |
|---|---|---|---|
| 1 | `gate_review_update:` как словарь | 5 (всего 7 блоков; `reni-ozon-plzl` — 3 блока) | `ticker, new_status, set_date, set_by, reason, ticker_class, cooldown_weeks, valid_days` (NVTK 27.10 — без `cooldown_weeks`) |
| 2 | `gate_review_update:` как список (`- ticker: …`) | 2 (`plzl-gmkn` 02.10, `ydex-mdmg-plzl` 23.10) | те же ключи в списке |
| 3 | `gate_review_bulk_update:` с `tickers: {T: {new_status, reason, ticker_class, valid_days}}` | 1 (29.05) | `set_date, set_by, run_id, tickers{…}` |
| 4 | `gate_review_bulk_update:` с `directives: [ … ]` | 2 (19.09: `ticker,new_status,reason`; 28.10 `prmd-data-posi`: + `cooldown_weeks,ticker_class,valid_days`) | `set_date, set_by, directives[…]` |
| 5 | ключ = тикер, формат самого реестра (`T: {status, trigger_reason, cooldown_until, valid_until}`) | 1 (15.05, 2 блока) | реестровая форма, не директива |
| 6 | `condition_update:` (`id, operation, trigger, note`) | 1 (`lsngp` 28.10) — **предложение**, «применяется через Режим 9» | `condition_update: {id, operation: open, trigger{type,value}, note}` |
| 7 | не-машинные ```-блоки (формулы, `/save-to-library`, схемы рассуждений) | 6 файлов (≈10 блоков) | текст |

Ещё 2 файла содержат строку `gate_review_update` только в тексте («для фондов не формируется», TGLD и Рентал ПРО 28.10) — отсюда «9 отчётов с блоком» в §0 плана: по факту 7 файлов с блоком `gate_review_update` + 3 с `gate_review_bulk_update` + 1 старый формат.

**Парсер блоков уже существует и не покрывает все формы:** `ru-portfolio-advisor/scripts/prior_digest.py:187-198` (`_directives`) читает формы 1, 2, 4; формы 3 и 5 — нет (K10). Фильтр по `kind` — стр. 184 и 232 (`_REVIEW_KINDS`; отчёт без нужного `kind` пропускается, если в нём нет директив).

**Вердикт / план-доля / триггеры: где машинно, где прозой.**

| Что | Машинно | Только прозой |
|---|---|---|
| Статус гейта бумаги (`reviewed_keep/under_review/reduce/buy_more`) | 11 отчётов (блоки 1–5), но без времени; `reason` — свободный текст | 42 отчёта (Mode 3/5/6/free-form не эмитят блока; фонды — решение владельца 28.10 «гейты по фондам не ставятся»; Mode 4 по облигациям — гейтов нет) |
| Вердикт (держать/купить/срезать) | нигде как поле: в блоке гейта — другая шкала (`reviewed_*`), не `HOLD/BUY/TRIM` | все 53 (TL;DR + «Выводы / Action items») |
| План-доля (целевая) | нигде | все 53 (в заголовке, TL;DR, таблицах) |
| Триггеры пересмотра/среза | `condition_update` в 1 отчёте (как предложение); условия по результату разбора заводятся отдельной операцией `save-to-library` и в отчёт не возвращаются (`created_by: user`) | все остальные (GMKN 29.10: три триггера среза — только «Выводы» п.2; условий по GMKN в реестре 0) |
| Срок (`cooldown_weeks`, `valid_days`) | блоки 1–2, 4 | остальные |
| Время создания | `created_at` у 41 из 49 (минуты, без пояса) | — |

---

## B. Аналитика по бумаге

### B1. `weekly-reviews/*.yaml` — схема

49 YAML (stock, bond) + md-парные. Окно с 30.08: 8 обзоров акций (03.09 … 28.10) и 7 облигаций (03.09 … 28.10) — все `schema_version: 2`. Полные объединения ключей до глубины 3 с частотой — `b_keys_stock_since0830.txt`, `b_keys_bond_since0830.txt`. Главное:

- **Верх (акции):** `advisor_version, amendments[], caveats[], conditions_evaluated{added,backup,evaluated_at,fired[],note,pending_next_7_30d[],pruned,ssot,status_pushes[],status_pushes_rejected[],written_back}, coverage{carried_over,checked_this_run,method,not_checked,note,tickers_total}, gate_aware_sizing{…}, gate_review_directives, horizon_ends, horizon_mode, horizons, ie_discipline{…}, key_risks[], macro_context{…}, macro_input, per_stock{}, period{from,to}, portfolio_summary{…}, primary_horizon, producer, proposed_gate_review_directives[], review_date, schema_version, snapshot_date, snapshot_id, sources{…}, type`.
- **Верх (облигации):** `carried_over_from, caveats[], closed_positions[], conditions_mutations_applied, conditions_state[], coverage{…checked_dates{эмитент: дата}}, key_risks[], macro_source, per_bond{}, plan_change_proposal{basis,changes[],funding_note,status}, plan_vs_fact[], plan_vs_fact_iis[], reports_considered[], revision, scenario_matrix{labels,p_h12,ref,status,binding_logic}, summary{…}, trades_since_prior[], trust_matrix_source`.
- **`per_stock[*]` — 41 поле в окне** (ключ — тикер): вердикт `advisor_verdict` + `advisor_verdict_basis/confidence/constraints`, `unconstrained_verdict` (+`_confidence`; 7 из 8 обзоров), `carried_over`, `catalyst`, `div_*`, `fundamental_score*`, **копии чужих баз:** `gate_status_snapshot{status,set_date,set_by}` (6 из 8), `user_constraints[]` (производная копия условий: `id,type,expires,on_trigger_verdict,source,active,derived,set_date,summary,closed_date,closed_reason`), `weight_user_planned_pct/weight_ie_target_pct` (копии плана/IE), `last_corp_event/next_corp_event` (текст с датой внутри).
- **`per_bond[*]` — 55 полей в окне** (ключ — ISIN): те же `advisor_verdict*`, `unconstrained_verdict`, `user_constraints`, `credit_rating*`, `plan_bucket/plan_subtype`, `ytm_*`, `maturity_date/offer_date`.
- **Разнобой ключей (K6):** `per_stock` — тикер, `per_bond` — ISIN, `coverage.checked_dates` — имя эмитента (`NORNICKEL, POLYUS…`), `conditions_state[].ticker` — ISIN.
- **`macro_context` — свободная структура:** около 95 различных ключей (до глубины 3) за 8 обзоров, значения и **даты зашиты в имена ключей** (`imoex_2026_10_08_0917`, `brent_futures_brx6_usd_2026_10_27`); набор от обзора к обзору разный (K5/K10 для любого читателя).

**Поля даты/времени.** Даты: `review_date`, `snapshot_date`, `period.{from,to}`, `macro_context.as_of`, `horizon_ends.*`, `amendments[].date`, `conditions_evaluated.evaluated_at`, `conditions_state[].fired_date`, `sources.*[].accessed_date`, `coverage.checked_dates.*`. **Времени суток нет ни в одном поле; `created_at` нет ни в одном из 49 YAML** (grep; по расклад. слою «опциональный `created_at`»). Момент записи — только mtime файла. Обзор «10-01» записан 4.10 14:16, «10-08» — 9.10 09:26 (дата обзора ≠ дата файла); облигации «09-03» — 4.09 07:30 (K6). Автор прогона — `producer` (`claude-opus-5`, `claude-opus-5-5`, `claude-sonnet-5-5 (…)`), id прогона нет.

### B2. K3 — копии `user_constraints` и `gate_status_snapshot` против реестров (3 даты)

Скрипт `b_k3.py`; сравнение с `gate-reviews.yaml` (история на дату обзора) и `conditions.yaml` (копия NAS 30.10 + `.backups/`). 21 акция в каждом обзоре.

| Обзор (файл записан) | Копия гейта ≠ реестр **на дату обзора** | Копия гейта ≠ реестр **сейчас** | Условия: копий / из них нет в реестре сейчас | Условия реестра (акции), созданные ≤ даты, но отсутствующие в копии |
|---|---|---|---|---|
| 16.10 (14:15) | 1: YDEX (в реестре в тот же день `review_needed/mode_1`, в копии `reviewed_keep` от 19.09) | 9 | 6 / 2 (MDMG, X5 — удалены prune) | 1 (`ozon-below-1610`, создано 16.10) |
| 26.10 (15:09) | 6: YDEX, MDMG, PLZL (реестр 23.10 `mode_4`, копия — прежняя, отставание 3 дня), CNRU (26.10 `user`), PRMD и DATA (26.10 `auto/review_aging`) | 9 | 8 / 2 | 4 (созданы 26.10) |
| 28.10 (12:08) | 3: PRMD, DATA, LSNGP (записи Mode 4 от 28.10 позже обзора: файлы отчётов 14:45–15:14) | 5 | 13 / 2 (+1 `x5-ifrs3q-review` закрыто 29.10) | 0 |

Выводы: (1) копия гейта в обзоре — снимок «на момент старта обзора» и стареет в тот же день (Mode 4 после обзора); на 26.10 у MDMG копия отставала на 3 дня на момент записи — механизм: `carry_over_weekly.py:110, 745-750` переносит `gate_status_snapshot`/`user_constraints` из прошлого обзора и сам помечает их `stale_sensitive`. (2) Копия условия расходится по **смыслу** после закрытия: MDMG — копия `closed_reason: date_passed, closed_date: 2026-10-28`, реестр — `fired` 26.10 + `closed_manual` 26.10 «исполнено» (подробно — `trace-MDMG.md`). (3) После prune история условия в живой базе теряется; остаётся копия в обзорах и `.backups/` (23 копии реестра с MDMG-условием). Класс K3/K8/K9.

### B3. `stress/`, `integrated-views/`, `coherence-audits/`, `sensitivity/`

- **`stress/` (18 YAML + md-пары).** Два свежих: `stress-2026-10-04-geopol-ru-west-shell-d1` (mtime 10-04 13:56) и `stress-2026-09-18-…` (14:20). Ссылаются на: `portfolio_snapshot_id` (10-04→`portfolio-2026-10-01.json`; 09-18→`portfolio-2026-09-16.json`), `macro_input` (имя файла бандла: `macro-scenarios-2026-10-04.yaml` / `-09-17.yaml`), `scenario_matrix_ref` (`scenarios/scenario-geopolitics-ru-west-2026-07-01.yaml`), `scenario_source: macro-forecast-chain`, `run_id`, `date`. **Даты прогнозов внутри нет** — ни одного `forecasts/…` или id прогноза (grep пуст); `baseline_spot.*` без дат; `method.factors`/`caveats` называют «идентично бандлу 09-17» прозой. Свежесть читателями считается по `date` стресса (`stress_digest.py:696-699`).
- **`integrated-views/` (26 md).** Свежий — `integrated-view-2026-10-04.md` (mtime 14:12): frontmatter `inputs{snapshot,snapshot_date,snapshot_age_days,stress,stress_date,stress_age_days,review_stock,review_bond,review_date,review_age_days}` — **единственное машинное место, где стресс и обзоры связаны** (обзоры 10-01 при стрессе 10-04; сам вид собран до записи файла обзора «10-01» в 14:16 — какую версию читал, не проверено). Берёт из стресса: сценарные веса, `portfolio_by_horizon`, `total_return`, `tail_flags`; из обзоров — вердикты и катализаторы (по тексту §1/§3). Макро-слой: «L2 only, macro-marginal 10-04 в расчёт не включён» — прозой. Вид устарел на 26 дней (монитор 10-29: «не пора»).
- **`coherence-audits/`.** 4 аудита (04.07, 05.07, 29.07, 06.08) + 3 `coherence-input-bundle-*.json` (`coherence-input-bundle@1.4`, Stage P: `build_coherence_bundle.py`, gate поколения — нормализация `snapshot_id` по источникам, стр. 185-207); последний — 06.08 (85 дней), в окне 60 дней нет. Пишет скилл напрямую (исключение D3, A2); читатель — пользователь.
- **`sensitivity/`.** Один файл `macro-scenarios-2026-07-02-Esens.yaml` (04.07, 23 КБ); в «Кто пишет / кто читает» раскладки строки нет (только в дереве каталогов, стр. 58) — писатель и читатель не определены.

---

## C. Прогнозный контур как вход (группа F)

Полная трасса одного прогноза — `trace-forecast-brent-price.md`. Здесь — схемы и карта.

**Как стресс получает прогнозы.** `macro-forecast-chain` собирает `macro-chain/macro-scenarios-<дата>.yaml` и `macro-marginal-<дата>.yaml`. Ключи: `run_id, assembled_date, assembled_by, mode (FULL/QUICK-REFRESH/PARTIAL), supersedes, portfolio_snapshot, ready_for_stress_test, coverage_score, scenario_matrix{source_file, scenario_weights_by_horizon, modal_flag}, baseline_spot{…}, factors{<фактор>: {unit, confidence, type, geopolitics_translation, source_forecast, fact_anchor{value, as_of, source}, by_scenario{…}, l2_ev{…}}}, consistency_check, caveats[], unmapped_tickers`. Стресс берёт бандл по имени (`macro_input`). Контракт `factors.*.source_files` (SKILL macro-forecast-chain:725, `check_source_files.py`) введён 29.10 (коммит 55ba1f62); в **бандлах 08-15, 09-04, 09-17, 10-04 `source_files` нет** (grep 0), поэтому состав стресса «по названию» восстанавливает вьюер (`viewer.js:3341-3367`, `stressInputs()`: тема + самая свежая версия с датой ≤ даты сборки).

**Как обзор недели ссылается на стресс.** Обзор акций: **поля нет** (`macro_input: null` в 10-16/26/28, а в 10-08 — это снимок `macro-snapshots`, не стресс); «стресс» упомянут только в тексте `advisor_verdict_basis` и в frontmatter отчётов (`related_artifacts`). Обзор облигаций: `scenario_matrix.ref` → `macro-scenarios-2026-09-17.yaml` (старее бандла 10-04, на котором стоит стресс) — разные версии входа в одном цикле. По SKILL (`ru-portfolio-advisor/SKILL.md:18, 252`) Mode 1/2/4–7 стресс и `forecasts/*.yaml` не читают; стресс читает `stress_digest.py` только в Mode 3 и 8 (лестница 30/60 дн по `stress.date`). Отчёт Mode 4 (GMKN 29.10) тем не менее ссылается на стресс 10-04 в `related_artifacts` и тексте (читал вручную).

**`monitor-reports/*.yaml` — схема.** `schema_version: 1, type: monitor-report, generated_at, producer, horizon_window_days, alerts[{severity, category, target, target_file, target_kind, message, detected_at, web_search_summary?, suggested_action}], freshness_audit{integrated_view, stress, weekly_review, macro_snapshot, trust_matrix: {age_days, threshold_days, due_for_refresh}}, predictions{total_active, overdue_count, due_30d_count, overdue_list[{id,file,days_overdue}]}, condition_events[{condition_id, ticker, event, status, event_date, fact, url, deadline, checked}], outcome_log_updates[], caveats[]` (`condition_events` — с 10-26). 6 отчётов с 28.08, 60 предупреждений: `category` — `stale` 27, `event_window` 18, `factor_breach` 12, `prediction_due` 3; `severity` — HIGH 30, MEDIUM 24, LOW 3, INFO 3; `target_kind` — forecast 45, scenario 13, view 2. **Категории `horizon_passed` в данных нет**, хотя перечислена в SKILL (:715) и должна ставиться вместо `stale`, когда горизонт < даты прогона (:771): `scenario-usd-rub-sept-2026` 03.09 («горизонт 2026-09-01 наступил») помечен `stale` (K5). `review_overdue` в схеме нет — просрочка дана в `predictions.overdue_list[].days_overdue`. Что машинно: все поля выше; что нет: «пробой → какой стресс/обзор затронут» (только `target_file`); частичность запуска определяется regex'ом по тексту caveat («запуск по одному файлу|частичн… прогон», `notifier.py:516-529`, зеркало `viewer.js:3038`) — K10.

**`stale_flags.yaml` — схема.** `generated, generated_by, stale_flags[{factor, flagged_by, reason(проза), upstream_topic, flagged_at, severity, depth}]`; сейчас одна запись (`usdrub-rate`, `warning`, `depth 1`, `upstream_topic: brent-price`, 08.10, mtime 09:22). Только имена тем: ни файла/версии прогноза, ни id отчёта-источника. Читатель — `macro-forecast-chain` по тексту SKILL (2.2 п.3, :407); в `scripts/` ссылок нет, во вьюере/`hub-notify`/`server.py` — нет. Файл по SKILL перезаписывается каждым запуском, фактически не перезаписан тремя запусками после 08.10 — решение «флаг оставить» записано в `caveats` отчётов 26.10 и 29.10 прозой.

**Карта «скилл → прогноз/сценарий → откуда → как проверяется свежесть».**

| Потребитель | Что читает | Откуда | Свежесть |
|---|---|---|---|
| `portfolio-scenario-stress` | факторные прогнозы (L2 по сценариям), `baseline_spot` | бандл `macro-scenarios-*.yaml` (файлы прогнозов напрямую не читает) | дата бандла/`stress.date`; внутренний возраст прогноза — только caveat (`MACRO_INPUT_PARTIAL`, `BASELINE_SPOT_STALE`) |
| `ru-portfolio-advisor` Mode 3/8 | EV, carry, сценарные веса | стресс через `stress_digest.py` | `stress.date`: >30 дн предупреждение, >60 дн Mode 8 отказывает, Mode 3 откладывает redirect |
| `ru-portfolio-advisor` Mode 1/2 | веса сценариев (облигации: `scenario_matrix.ref`) | бандл `macro-scenarios-*`/матрица сценариев | никак (ссылка на файл, версия бандла может быть старее стресса) |
| `ru-portfolio-advisor` Mode 4 | стресс — по факту, вручную | стресс-файл | вердикт свежести в индексе («стресс 04.10, 25 дн, fresh») |
| `portfolio-integrated-view` | стресс + обзоры | `inputs.*` во frontmatter | `stress_age_days`, `review_age_days`, лимиты 90/14 |
| `forecast-monitor` | `forecasts/`, `scenarios/` | напрямую | `forecast.horizon`/`reviews`/пороги; `freshness_audit` по дате стресса/обзора |
| `macro-forecast-chain` | `forecasts/*.yaml`, `stale_flags.yaml` | напрямую | дата прогноза vs порог; флаги поверх возраста |
| вьюер «Действия» | монитор, `condition_events`, роль прогноза в стрессе | `monitor-reports/`, `macro-scenarios-*` | «по названию» / «есть новее» |
| `hub-notify` | последний монитор + предыдущий | `monitor-reports/` | по дате в имени файла и `generated_at` |

---

## D. Данные трассировок за 60 дней (31.08–30.10)

Таблицы с колонкой «Что показывал сайт» (пустой) — в `trace-GMKN.md`, `trace-MDMG.md`, `trace-RU000A106EP1.md`; каждая содержит «Где цепочка рвётся».

**Выбор облигации — RU000A106EP1 (ПР-Лиз 2P2, корзина КОРП/B+).** Критерий §3.1: за 60 дней событие условий и смена корзины. Три условия созданы 09.10 после разбора Mode 4 (`created_by: user`), одно отредактировано 14.10 (поле `event`); монитор проверял `ifrs9m-3011` 26.10 (`not_found`); корзина КОРП/B+ изменена на сайте 28.10 в 12:24 МСК (`plan-journal.jsonl`, `who: site`, `reason: null`), через 10 минут после записи обзора облигаций, где то же изменение значилось «proposed (решение владельца)». Гейтов у облигаций нет. Запасной вариант — RU000A107795 (условие закрыто 26.10 и удалено prune).

**Сводка разрывов.**
- **GMKN (разбор 29.10).** Вердикт, план, три триггера среза — проза; машинно только директива гейта без времени (`set_time` нет, хотя код пишет с 28.10 19:15). Гейт 17:30:47 → файл отчёта 17:34 → `created_at` 17:40. Обзор 28.10 (12:08) остаётся последним «вердиктом» бумаги, копия гейта в нём устарела; индекс `securities/GMKN.json` отстал до пересборки 30.10; условий нет; история правок плана (журнал) начинается только 27.10, по GMKN — переключение KEEP→BALANCE→KEEP 28.10 13:09 МСК за 10 секунд без причины.
- **MDMG (срез 26.10).** Условие со сроком 19.10 «сработало» 26.10 — оценка только при записи обзора (задержка 7 дней); три обзора подряд «HOLD при `unconstrained=TRIM`» записаны в журнале как `ignored`; закрытие условия — прозой в `note`; копия в обзоре 28.10 говорит `date_passed`, реестр — `closed_manual 26.10`; после prune история условия — только в `.backups/`; инструкция «после исполнения — гейт `reviewed_keep`» не исполнена (гейт `reviewed_reduce@23.10`), `cooldown_until` позже `valid_until`.
- **RU000A106EP1.** Предложение смены корзины в обзоре не связывается с применением на сайте (`reason: null`); вердикт HOLD повторяется 7 недель, из разбора 09.10 структурно в обзор ничего не попадает кроме условий; автор разбора в условиях записан как `user`; `history.time` нет.
- **`brent-price`.** Дата версии прогноза теряется на шаге «прогноз → макро-вход» (в факторе — только тема и `fact_anchor.as_of`), а на «макро-вход → стресс» остаётся лишь имя бандла = дата сборки; пересбор 08.10 09:48 стресс 10-04 не видит; `stale_flags` несёт только темы.

---

## E. Группа G — служебное

| Объект | Размер/объём (30.10) | Кто пишет | Что внутри | Читает ли кто-то машинно |
|---|---|---|---|---|
| `Portfolio/INDEX.md` | 333 КБ, 449 строк (много длинных строк) | `save-to-library` — `update_index.py` (`add-rows`, `add-meta`; pre-write копии `Portfolio/.backups/INDEX-<дата-время>.md`); часть — руками модели | оглавление по секциям: снапшоты, стрессы (с колонкой «Macro input»), обзоры (95 строк), журнал Workflow M (проза), интегр. виды (6 в таблице при 26 файлах — «каталог неполон»), ad-hoc отчёты (43 строки при 53 файлах), метаданные | `update_index.py` (разбирает таблицы по заголовкам секций, `_find_section`) и `revise-memory-remote/validate_library.py` (парность INDEX ↔ файлы, :175-215); вьюер и уведомитель — нет (grep) |
| master `INDEX.md` | 40 КБ, 127 строк | `save-to-library`, `memory-sync` | «Last sync: 2026-10-08»; блок «Portfolio — еженедельные обзоры (последние)» **остановился на 2026-07-11**; монитор-отчёты до 10-29 актуальны; матрица доверия «Track record summary» | `audit_candidates.py:371` (`parse_track_record`), `weighted_consensus.py` (trust-веса — в docstring; ввод весов идёт отдельным JSON, парсинг INDEX не найден), `validate_library.py`; в frontmatter интегр. вида `trust_matrix_source: Claude-Memory/INDEX.md` — значение собирает модель |
| `_sync_log.md` | 455 КБ, 1288 строк; последняя запись 30.10 | `save-to-library` (`update_index.py sync-log`), `memory-sync`; один пункт 30.10 — «claude-code (по просьбе владельца, вне save-to-library)» (ручная правка прогноза) | хронология операций: дата · источник · файл · Workflow · детали | машинного читателя нет (`validate_library.py` ищет только лишние `_sync_log_append-*`); `revise-memory-remote` — по описанию |
| `_jobs/log-2026-10.jsonl` | 86 строк, 21.10 → 30.10 16:54 МСК | `hub-notify` (`jobs.py:80`) → `hub-api` `POST /api/job/append` (`server.py:3297`, шаблон `JOB_LOG_RE` :447) | `ts` (с поясом +03:00), `job` (`pf_build` 34, `eshop` 26, `pf_save` 18, `macro` 8), `status` (3 `error`), поля по типу (`items`, `values`, `path`, …) | машинного читателя нет (в раскладке — «пользователь, разбор пробного месяца»); единственный журнал с ISO-временем и поясом |
| прочее в `_jobs/` | `pdl-run-tmp.tgz`, `pdl-tmp/` (выгрузки сделок `trades_portfolio_*.xlsx`) | вручную/разовый прогон | не журнал | нет; в раскладке не описано; содержит личные выгрузки — вынести (замечание, не пробел данных) |

---

## Что не удалось проверить

- Содержимое `securities/*.json` между 29.10 17:34 и 30.10 12:26 (версий индекса нет), а также NAS-mtime `securities/GMKN.json` и `MDMG.json` (в `stat.txt` листинг `securities/` обрезан на `BTBR.json`; использован mtime Мака 30.10 15:07).
- Был ли push по наступившей дате условия MDMG (19.10) и по пробою Brent (08.10) — лог `hub-notify` не смотрел.
- Какая версия скилла исполнялась при записи гейта GMKN 29.10 (код с `set_time` — с 28.10 19:15, запись без времени).
- Почему журнал решений помечает все записи по RU000A106EP1 как `revised_post_hoc=true`, `error_category=data`.
- Какую версию обзора акций «10-01» читал интегрированный вид 10-04 (файл записан на 4 минуты позже вида).
- Содержимое `.md`-частей прогнозов (проза) против YAML.
- Соответствие mtime Мака и NAS для `weekly-reviews/`, `reports/`, `stress/` (на NAS для этих папок снимка нет; у сверенных `conditions.yaml`/`gate-reviews.yaml` mtime совпадают).
