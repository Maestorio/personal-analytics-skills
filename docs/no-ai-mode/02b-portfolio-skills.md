> Приложение к `docs/no-ai-mode/README.md`. Разбор кода и документации на 2026-11-07; ключевые утверждения выборочно проверены по коду, номера строк могут сдвигаться.

# Портфельный контур без LLM: аналитические скиллы

**Актуальность (ревизия 2026-11-09):** база разбора — `main` на 30.10; главнее `02c-portfolio-errata-data-structures.md` и `REVIEW-2026-11-09.md` §4 S5.
Санкционные позиции пересмотрены 06.11 (формулировки «просрочены» сняты); PSS-17..19 сделаны; `apply_condition.py` — add/edit/withdraw/digest/crosscheck/validate;
`apply_gate_review.py` и `securities_index.py` удалены; слой `gate_reviews` в `validate_library.py` снят.
«Приоритет №1: авто-aging гейтов / fail-open» снят решениями 3 и 9 `START.md` (при `off` срок — предупреждение, пауза докупки и IPO-пауза блокируют всегда); порядок работ — `PLAN-less-ai.md` §3.

Дата разбора: 2026-11-07. Охват: 14 скиллов (ru-portfolio-advisor, portfolio-scenario-stress, portfolio-integrated-view, portfolio-coherence-audit, macro-forecast-chain, forecast-confidence-applier, forecast-monitor, scenario-builder, hypothesis-stress-tester, retrospective-forecast-audit, forecast-collector, save-to-library, revise-memory-remote, memory-sync).
Вьюер, загрузчик снапшота и macro-ru-watcher — на другом агенте; здесь они только как потребители/соседи.

Оценки трудоёмкости: **S** — до 1 дня, **M** — 2–5 дней, **L** — 1–3 недели (включая тесты в реестре `docs/test-registry.md` и правки справок по правилам CLAUDE.md).
Классы: **A** — уже работает без LLM; **B** — переносимо без LLM; **C** — LLM необходим принципиально.

---

## 0. Главное за минуту

1. **Числа стресса считаются скриптами, не моделью.** После `build_stress_stub` → `compute_per_position` → `compute_bond_carry` → `compute_portfolio_aggregates` → `validate_stress_output` LLM нужен только для (а) бет по новым бумагам, (б) текстовых блоков (`top_risks`, `caveats`, таблица `macro_blindspots`, идио-проход), (в) самих сценариев и их факторных уровней. Поэтому **«пересчёт старого мира сценариев на новом снапшоте» делается на NAS без LLM** — беты уже лежат в старом stress-YAML (`compute_per_position.py:1380`, `factor_betas`, `factor_betas_method`, `factor_betas_r2`, `sanctions_position`).
2. **Самый опасный тихий сбой без Claude — гейты.** Статус `review_aging` («оценка устарела») ставит только `auto_maintain_gate_reviews.py` при сохранении через save-to-library. Ни вьюер (`rebalance-engine.js:26` только читает статус), ни `hub-notify` по `valid_until` его не выводят. Без Claude гейты «держать/наращивать» навсегда останутся разрешающими докупку, хотя срок (45/60 дней) давно вышел. Закрыть — S (cron-задача на NAS + эндпоинт записи).
3. **Условия (conditions) обнаруживаются без LLM** (`notifier.py:222` — зеркало `apply_condition.py evaluate`; push по цене/дате). Не работает только **резолюция** (Исполнил/Перенести/Отказываюсь): кнопки вьюера копируют команду для Claude (`07-conditions.md`). Эндпоинт записи `POST /api/pv/cond/save` на сервере есть (`tools/hosting/api/server.py:47,1951`), клиента нет.
4. **Что принципиально требует LLM:** веб-поиск и чтение первоисточников (новости, отчёты, рейтинги, прогнозы банков), вердикты и катализаторы, построение сценариев, ретроспективный аудит источников, red-team (Fable), Mode 4/5/8, `forecast-collector`, `hypothesis-stress-tester`.
5. **Инфраструктура для переноса уже есть и обкатана:** `hub-notify` гоняет задачи по расписанию без Claude (eShop, макросрез, сборка снапшота — `notifier.py:1-95`, `jobs.py`, `macro_job.py`, `pf_build.py`), пишет через `hub-api /api/job/*` по белому списку `JOB_WHITELIST` (`server.py:428`); PyYAML в контейнере `hub-notify` ставится в `/deps`. Новые задачи — расширение этого же паттерна.

---

## 1. Таблица по скиллам и режимам

Колонки: что делает LLM → что делают скрипты → артефакт и читатель → класс → деградация без LLM.
Пути скриптов — `skills/<скилл>/scripts/`.

### 1.1 ru-portfolio-advisor (9 режимов, `SKILL.md:174-205`, `EXAMPLES.md`)

| Режим | LLM делает | Скрипты делают | Артефакт → читатель | Класс | Без LLM |
|---|---|---|---|---|---|
| **1. Обзор акций за неделю** (`EXAMPLES.md:41`) | веб-новости по каждой бумаге (fan-out субагентов на Haiku, обязательно при ≥5 тикеров — `SKILL.md:212`), вердикты, катализаторы, гейт-директивы, текст `changes.md` | `build_weekly_stock_stub.py` (веса, цены, XIRR, расхождения с планом/IE — всё детерминированно), `weekly_changes.py` (Δ по закрытиям ISS), `prior_digest.py`, `carry_over_weekly.py` (перенос прошлого анализа в новый стаб, `:1-75`), `reconcile_constraints.py` (даты/цены ограничений), `concentration_limits.py`, `sweep_collect.py`, `render_weekly_md.py` (80–90% MD из YAML, `:1-30`), `classify_catalyst.py`, `fill_catalyst_scenarios.py` | `weekly-review-stock-{date}.yaml`+`.md` → вьюер (вкладки «Акции», «Действия», «Изменения», «Доли и цели», гейты), `integrated-view`, `forecast-monitor` (катализаторы), push-уведомления (смены вердиктов) | **C** (ядро: новости+вердикт). Механическая часть — **B-M** | Вердикты замораживаются на дату последнего обзора. Числа на странице (вес, цена, доли «Сейчас») живые — считает вьюер по снапшоту+MOEX. Плашка «обзор акций» жёлтая через 14 дней, красная через 30 |
| **2. Обзор облигаций** (`:87`) | рейтинги, оферты, корпсобытия (веб), вердикты по облигациям | `build_weekly_bond_stub.py` (MOEX ISS: YTM, дюрация, купоны, даты — детерминированно), `carry_over_weekly.py`, `render_weekly_md.py` | `weekly-review-bond-{date}.yaml/.md` → вкладка «Облигации», `compute_bond_carry` (через overrides), `integrated-view` | **C** (+ часть **A/B**: YTM, дюрация, календарь выплат уже в снапшоте/стабе) | То же: вердикты/рейтинги замораживаются; YTM и выплаты — из снапшота |
| **3. Ребалансировка** (`:117`) | суждение «слушаться ли IE», веса, текст | `gate_aware_sizing.py` (сайзинг докупки/среза, `:1-60`), `constraint_engine`, `concentration_limits.py`, `stress_digest.py --mode 3` | отчёт в `Portfolio/reports/`, директивы | Арифметика — **A** (JS-зеркало `rebalance-engine.js`, колонка «Сейчас», паритет проверяет `test_rebalance_parity.py`); мнение об IE — **C** | «Сейчас» работает полностью по плану сайта, гейтам и условиям. Пропадает только оценка внешней модели IE. Блокировка докупки при протухшем стрессе — только внутри скилла, на «Сейчас» не влияет |
| **4a/4b. Разбор акции / облигации / эмитента** (`:164,193`) | вся работа: чтение отчётности, новости, оценка, итоговый гейт | `moex_quotes.py`, шаблоны | `Portfolio/reports/*.md` + директива гейта → `gate-reviews.yaml` | **C** | Нет новых разборов → новые бумаги навсегда «новая»/«нужен разбор» (докупка закрыта), у старых истекает срок гейта (см. раздел 3) |
| **5a/5b. Разбор / подбор фонда** (`:230,258`) | сравнение фондов, комиссия, состав | нет | отчёт в чат/`reports/` | **C** | Данные по фондам (комиссия, спред, класс) можно вручную вносить в «Доли и цели» (`bonds/funds.*.fee_pct` в `/api/pv/plan/set`, `server.py:~70`) |
| **6. Доходность** (`:287`) | словесный анализ «что тянет вниз» | числа уже в снапшоте: `returns.by_type`, `per_instrument_xirr` | показ во вьюере (плитки «Сегодня», «Динамика», «Какая доходность какая») | **A** (вывод чисел), текст-интерпретация **C** | Полностью на странице |
| **7. Докупка на ИИС-3** (`:349`) | выбор бумаг по макро-контексту, текст | `iis_shortlist.py` (stdlib+`moex_quotes.py`, ISS: лоты, остаток, доли до/после, `:1-50`) | отчёт → вкладка «ИИС-3» («последний разбор») | Шортлист-таблица **B-S** (кнопка «Сумма пополнения» → задача на NAS), выбор — **C** | Можно показать таблицу кандидатов без рекомендации (скрипт сам говорит: «не даёт финальную рекомендацию») |
| **8. Оценка качества акций 1–2 года** (`:383`) | оценка по каждой акции корзины (Opus) | `stress_digest.py --mode 8` (EV/tail из stress), `gate_aware_sizing` | отчёт + пачка гейт-директив | **C** | Гейты не обновляются (см. раздел 3). Mode 8 по правилу скилла отказывается при стрессе >60 дн. |
| **9. Условия (CRUD)** (`:435`, `mode-9-conditions.md`) | разбор фразы пользователя в команду; расстановка исходов | `save-to-library/scripts/apply_condition.py` (1225 строк: add/close/open/edit/remove/fire/list/evaluate; stdlib, JSON-in/out) | `Portfolio/conditions.yaml` → вьюер, notifier | **B-M** (форма на сайте) | Обнаружение сработавших — работает (notifier). Резолюция — только руками через Claude либо новая форма (раздел 4) |

### 1.2 portfolio-scenario-stress (`SKILL.md:80-700`)

| Шаг | LLM | Скрипты | Класс |
|---|---|---|---|
| Приём/валидация входов, нормализация сценариев (Шаги 1–2) | чтение разнородного входа (scenario-builder / FCA / macro-chain / inline) | `input_contract.py` (канон факторов, 6 гардов, `:1-30`), `migrate_v1_to_v2.py` | **B** (входной формат macro-chain YAML фиксирован) |
| Свежесть санкционных позиций (3.6.0) | пересмотр по рубрике (`/sanctions-positions`) и поиск событий | `check_position_freshness.py` (дата `as_of` в `references/sanctions-positions.yaml`, порог `stale_after_days: 30`, строит поисковые запросы, сам в сеть не ходит) | проверка срока — **A**; пересмотр значений — **C** |
| Беты по бумагам (3.6.1–3.6.2, `betas-priors.json`) | пишет priors по всем новым бумагам по sector-таблицам, ставит `asset_type`, `sanctions_position` | — | для **уже известных** бумаг — **B** (взять из прошлого стресса: `SKILL.md` прямо разрешает «reused from stress-<id>»); для **новых** — **C** (или правило «сектор → беты»: **B-M**) |
| Факторы по горизонтам | выбор уровней года FCA/сценария | `compute_horizon_factors.py` (уровни года → движения против `baseline_spot`, stdlib) | **A** при готовых уровнях |
| Per-position ΔP&L (3.6.4) | запуск | `compute_per_position.py` (1593 строки, режим `priors` — stdlib+PyYAML; режим `moex` — numpy + сеть ISS/ЦБ; maturity guard облигаций) | **A** |
| Bond carry (3.7) | подмешивание overrides по плавающим | `compute_bond_carry.py` (849 строк; купоны по факт. расписанию, pull-to-par, реинвест, FX, MM/кэш) | **A** |
| Агрегаты (Шаг 4) | запуск | `compute_portfolio_aggregates.py` (обе базы price/total_return, range, robustness), `validate_stress_output.py` (RECONCILE), `build_stress_stub.py` | **A** |
| Идио-проход (3.5), таблица `macro_blindspots`, `top_risks`, `caveats`, `hedge candidates`, `sector_breakdown` (текстовая часть) | рассуждение | частично (флаг blindspot по R²/|β|) | **C** (но вьюер переносит отсутствие: `viewer.js:4435` фильтрует `top_risks` по горизонту, поля необязательны) |
| «А если другие веса?» | запуск | `reweight_stress.py` (только чтение, без сети, переусреднение готовых `delta_pct_by_scenario`) | **A** |

Выход: `stress-{date}-{slug}.md/.yaml` → вьюер («Стресс»), `integrated-view`, `ru-portfolio-advisor` (Mode 3/8), `coherence-audit`.

### 1.3 portfolio-integrated-view (`SKILL.md`, Opus)

| Что | LLM | Скрипты | Класс |
|---|---|---|---|
| Упаковка payload (разбор snapshot, stress, 2 weekly-review, trust matrix из `INDEX.md`, опц. macro-chain, предыдущий вид) | да, по `references/synthesizer-workflow.md` | — | **B-M** (парсер на Python+PyYAML) |
| Все числа: нормировка p, R-PIPE/R-SNAP гейты, per-position (macro+div/carry+idio), joint expectation (macro_dependency), Monte Carlo CI 10k путей, tail flags, spread, total return 3 слоя | нет: «все числа — этот скрипт» | `aggregate_positions.py` (3177 строк, stdlib, `:1-27`) | **A** (как код), оболочка — **B** |
| Проза §1/§9/§10, caveats, verdict-pointer колонки | да | — | **C** (но §1 — таблица из verdict кодов обзора: можно собрать механически) |
| Frontmatter `portfolio_by_horizon`/`total_return`/`tail_flags` | копирует `result[...]` as-is (контракт стабильности графиков) | validate-integrated-view в `assemble_artifact.py:3141` | **A/B** |

Выход: `integrated-view-{date}.md` → вьюер («Интеграционный анализ», «Динамика», ожидания на «Акции»). Строгие входные гейты скилла (snapshot ≤14 дн., review ≤14/30 дн., stress ≤90) — в самом скилле.

### 1.4 portfolio-coherence-audit

| Stage | LLM | Скрипты | Класс |
|---|---|---|---|
| P: bundle всех артефактов, generation-consistency gate, joint_tail, diachronic, `watch_verdict` («нужен ли Fable-прогон») | нет | `build_coherence_bundle.py` (852 строки, «DETERMINISTIC PRE-STAGE. No LLM», `:1-20`) | **A**/**B-S** (можно гонять по cron раз в неделю и пушить `watch_verdict`) |
| R: поиск противоречий, off-diagonal связок, red-team | Fable (claude-fable-5) | — | **C** |

Артефакт: `coherence-audits/coherence-audit-{date}.md` (вьюер его в плашках не показывает — `PV_DIRS` без этой папки).

### 1.5 Прогнозный контур

| Скилл | LLM | Скрипты | Выход → читатель | Класс | Без LLM |
|---|---|---|---|---|---|
| **macro-forecast-chain** (FULL/QUICK/PARTIAL/RECALIBRATE) | оркестрация FCA и scenario-builder, интерпретация | `coverage_report.py` (статусы свежести/покрытия, режим, consistency), `compute_marginal_move.py` (парсинг строк-уровней), `check_source_files.py`, **`recalibrate.py`** (RECALIBRATE: «Никаких LLM-вызовов. < 30 секунд»; `:1-20`) | `macro-chain/macro-{marginal,scenarios}-{date}.yaml` → stress, вьюер («Ещё → Прогнозы») | FULL/QUICK — **C**; RECALIBRATE и coverage — **A/B-S** | RECALIBRATE пересчитывает Layer 2 по весам из SSOT сценария — но сами веса меняются только решением человека/scenario-builder (см. 4) |
| **forecast-confidence-applier** | поиск 3–7 источников, чтение, атрибуция лагерей, симметрия | `weighted_consensus.py` (веса HIGH=1/MED=0.5, взвешенная медиана, P10/P90, confidence, next_due; stdlib), `validate_fca_output.py` | `forecasts/*.md/.yaml` → monitor, stress, macro-chain | **C** (источники и их чтение) + **B** (ручной ввод цифр → консенсус) | Прогнозы замораживаются, «стареют» по `next_due` (3–6 мес по домену) |
| **forecast-monitor** (Haiku) | web_search по `auto_checkable`, извлечение даты события, вердикт ✅/❌/⚠️ | **`monitor_alerts.py`** (1192 строки: активные, окна review/deadlines/monitoring/thresholds/falsifiers, severity, `web_search_plan`, post-filter по дате, каскад `stale_flags`, калибровочный сторож — `:1-17`) | `monitor-reports/monitor-report-*.yaml` (+`stale_flags.yaml`) → вьюер («Действия»), notifier (push), hub | Даты/сроки/свежесть — **B-M**; «наступило ли событие» — **C** | Без запуска нет алертов о сроках — сейчас их ждёт только Claude |
| **scenario-builder** | всё (матрица 2×2 из реальных разногласий) | нет скриптов | `scenarios/*.yaml` (SSOT весов) | **C** | Сценарии и веса замораживаются |
| **hypothesis-stress-tester** | всё (pre-mortem, KAC, ACH…) | нет | отчёт в чат | **C** | — |
| **retrospective-forecast-audit** | извлечение тезисов, сбор консенсуса на дату, верификация факта, 3 шкалы | `retro_metrics.py` (матрица ценностей, hit_rate, alpha, error clustering), `audit_candidates.py` (какие источники не аудированы) | `reports/` + `domains/{d}/` trust-профиль → INDEX trust matrix | **C** (ядро) + **A** (метрики) | Trust matrix не растёт; существующая работает |
| **forecast-collector** | поиск и отбор 10–20 resolved-прогнозов источника | нет | `forecast-collections/*.md` | **C** | — |

### 1.6 Memory-скиллы

| Скилл | LLM | Скрипты | Класс |
|---|---|---|---|
| **save-to-library** | классификация артефакта, формулировка строк INDEX, интерактивные «да/сомнения», маршрутизация по 16 workflow (A…P), блок-проверки | `assemble_artifact.py` (4922 строки, ≈20 `validate-*`: stress, weekly-review, integrated-view, monitor-report, snapshot, forecast/scenario events — все stdlib, JSON-in/out), `update_index.py` (INDEX.md+`_sync_log.md`), `apply_condition.py`, `apply_gate_review.py`, `auto_maintain_gate_reviews.py`, `backfill_created_at.py` | ядро — **A** (скрипты), роутинг — **C** |
| **memory-sync** | работа с `memory_user_edits` профиля Claude (`[lib]`-записи) | `sync_planner.py` (план add/replace/remove) | **C/отмирает**: цель — память самого Claude |
| **revise-memory-remote** | суждение «устарел ли прогноз», миграции yaml | `validate_library.py` (1459 строк, stdlib; слои 1–3: YAML-поля, парность md↔yaml, триггеры по датам, broken refs, Σ probability) | валидация — **B-S/M**; суждения — **C** |

---

## 2. Числовое ядро, которое можно гонять на NAS по расписанию без LLM

Общее для всех пунктов: запуск как задача в `hub-notify` (паттерн `macro_job.py`/`pf_build.py`), запись через `hub-api` с расширением `JOB_WHITELIST` (`server.py:428`), копия предыдущей версии в `.versions/`, строка в `_jobs/log-ГГГГ-ММ.jsonl`. Скрипты на NAS выкладывает `deploy.zsh` (как для `build_snapshot.py`/`build_macro.py`).
Зависимости контейнера: PyYAML есть (`notifier.py:63`); numpy не нужен (режим `priors`); сеть — только ISS/ЦБ (уже разрешены для макро- и снапшот-задач).

### 2.1 Пересчёт стресса «старый мир сценариев, новый портфель» (рекомендуемый №1)

**Идея.** Взять последний `stress-*.yaml` (schema 2), новый снапшот → выпустить новый `stress-{дата}-auto.yaml`.

| Вопрос | Ответ |
|---|---|
| Входы | (1) последний stress YAML — из него `scenarios.*` (`name`, `p`, `p_by_horizon`, `factors_by_horizon`), `horizon_ends`, `baseline_spot`, `per_position[*].{factor_betas, factor_betas_method, factor_betas_r2, sanctions_position}`, `bond_carry` overrides; (2) рабочий снапшот `portfolio-{date}.json` (PV_DIRS читает вьюер); (3) `references/sanctions-positions.yaml`; (4) опц. `bond-overrides` из последнего `weekly-review-bond` (`bond_type=floater`) |
| Шаги | пересобрать `betas-priors.json` из `per_position` → `compute_per_position.py` (`--regression-mode priors`) → `compute_bond_carry.py` → `compute_portfolio_aggregates.py` → `validate_stress_output.py` → собрать YAML (числовые блоки новые, текстовые — перенос с пометкой) → записать как `Portfolio/stress/stress-<дата>-auto.yaml` (маска `PV_DIRS`: `^stress-\d{4}-\d{2}-\d{2}.*\.(yaml|yml)$` уже подходит) |
| Что получится | актуальные ΔP&L по каждой бумаге × 4 сценария × 3 горизонта (h6/h12/h24 якорные), обе базы (price, total_return), купоны/погашения/реинвест по текущим облигациям, портфельные агрегаты, tail |
| Совпадёт ли формат с вьюером | да, если собирать тем же `build_stress_stub.py`+скриптами: вьюер читает `scenarios.*.portfolio_level_by_horizon`, `per_position.*.by_horizon`, `portfolio_summary` (`viewer.js:985,1057` достраивает сам), `top_risks`/`caveats` необязательны (`viewer.js:4435`) |
| Что нельзя | **новые бумаги без priors** уходят в `unmapped_tickers`; при покрытии <99% скрипт предупреждает (`compute_per_position.py` ~1420). Решения: (а) правило «сектор/asset_type → беты по таблице `sector-sensitivities.md`/`bonds-sensitivity.md`» (S–M, но качество «±5–15 п.п.»), (б) оставить unmapped и показать долю непокрытого. Облигации: беты считаются формулой `β = −duration × Δspread / 100` из снапшота (S) |
| `asset_type` | в `per_position` его нет (в priors он обязателен и «точнее, чем в снапшоте» — различает облигационные фонды); брать из снапшота + `Portfolio/security-types.json` либо хранить в priors-файле на NAS (S) |
| Санкционная шкала | `check_position_freshness.py` (A) сообщит устаревание (порог 30 дн., файл `as_of: 2026-08-06` — уже старше порога); пересмотр значений — LLM/человек. Автозадача обязана вставить caveat «sanctions_position от DD.MM» |
| Спот и уровни | `baseline_spot` в старом стрессе фиксирован на дату старого прогона. Движения факторов = (уровень года FCA − baseline_spot)/spot. Чтобы они отражали **сегодняшний** рынок, нужно пересчитать `compute_horizon_factors.py` по `macro-chain/macro-scenarios-*.yaml` (читаются через PV_DIRS) с актуальным спотом; USD/RUB, CNY/RUB, ключевая ставка — из автосреза (macro_job), **Brent и золото в автосрезе нет** (сейчас Brent берёт web_search) → пока остаются старые споты (честно помечать), нужен источник Brent (ISS FORTS BR — гипотеза из `analysis-2026-10-20.md` §3, не проверена) |
| Честность выхода | стресс «в мире прошлого макро-прогноза»: он отвечает на вопрос «что с портфелем, если сбудется тот же сценарий», а не «что думает рынок сегодня». Метка `producer: site-auto-restress`, `restress_of: stress-<id>` и caveat обязательны; плашка вьюера по дате файла сбросится — **нужна отдельная метка «без пересмотра прогноза»**, иначе скрывается устаревание прогноза (см. раздел 3) |
| Трудоёмкость | **M** (задача-обёртка, тесты, whitelist, метка во вьюере); **+S** на правило бет для новых облигаций; **+M** на бету акций «по сектору» |

### 2.2 Агрегаты integrated-view (`aggregate_positions.py`)

| Вопрос | Ответ |
|---|---|
| Входы | снапшот, stress (в т.ч. 2.1), 2 последних weekly-review YAML (катализаторы, вердикты, `macro_dependency`), опц. `INDEX.md` (trust matrix), macro-chain, предыдущий вид |
| Что нужно | Python-упаковщик payload (`synthesizer-workflow.md` описывает контракт); дальше — только stdlib |
| Выход | `integrated-view-{date}.md` с frontmatter `portfolio_by_horizon`/`total_return`/`tail_flags` (вьюер ≥2.6.0 читает frontmatter первым) + таблица §1, которую вьюер читает по колонкам `r[2]`, `r[4]` (`SKILL.md:~320`). Формат фиксирован → без прозы получится «сухой» файл, что вьюер переварит, но надо сверить с `validate-integrated-view` |
| Подвох | катализаторы и их вероятности — **LLM-авторские** (из обзоров). При старом обзоре (>14 дн.) скилл отказывается, на сервере нужна своя политика: считать на старых катализаторах с пометкой возраста |
| Трудоёмкость | **M–L** (упаковщик + сухой рендер §1–§9 + валидатор `validate-integrated-view` + тесты). Менее затратная альтернатива **S–M**: не выпускать файл, а показывать во вьюере только перепосчитанные ожидания по снапшоту/стрессу без вердикт-таблицы |

### 2.3 `monitor_alerts.py` (сроки forecast-monitor)

| Вопрос | Ответ |
|---|---|
| Входы | все `forecasts/*.yaml`, `scenarios/*.yaml` (PV_DIRS читает), `dependency_map` (из `_shared/DEPENDENCY-MAP.md`), `conditions.yaml`, `weekly-review-stock` каталисты |
| Без сети | просроченные `reviews.next_due`, окна `deadlines`/`monitoring.check_date`, `horizon_passed`, `prediction_due`, freshness_audit, калибровочный сторож — всё из `monitor_alerts.py` |
| Выход | `monitor-reports/monitor-report-{date}.yaml` с `scope: partial`/`caveats: «события не проверялись»` → вьюер («Действия», «Источники»), notifier (HIGH-алерты) уже его читает (`PV_DIRS`: `monitor-reports/`) |
| Подвох | числовые пороги `thresholds[]`/`falsifiers[]` в прогнозах — **свободный текст** (`needs_web_search: True`, `monitor_alerts.py:~289`), структурных `metric/op/value` нет → автопроверка «Brent > X» требует миграции формата прогнозов и источника цены (**M–L**). Но сроки (даты) без поиска — достаточно |
| Трудоёмкость | **M** (сбор input.json на Python+PyYAML, cron, запись, защита от записи сверх whitelist). Дополнение «факторные пороги по ISS/ЦБ» — **M–L** |

### 2.4 Валидация библиотеки (`validate_library.py`) и `assemble_artifact.py validate-*`

| Вопрос | Ответ |
|---|---|
| Что даёт | парность md↔yaml, обязательные поля, Σ probability сценариев (1.0±0.05), триггеры по датам, broken refs, drift-валидаторы схем 2 |
| Вход | payload `library_layout` + распарсенные YAML (`SKILL.md:65,228`) — сборка скриптом: **S–M** |
| Выход | список issues → пуш «библиотека: 3 ошибки» (виды `KINDS` в notifier — добавить вид) |
| Польза без LLM | высокая как сторож **после ручных правок** сайта; ловит поломки, которые раньше ловил save-to-library при записи |

### 2.5 Авто-обслуживание гейтов (`auto_maintain_gate_reviews.py`) — снято решениями 3, 9 START (устарело, см. шапку)

| Вопрос | Ответ |
|---|---|
| Что делает | 5 переходов: новая бумага в снапшоте → `new_position`; пропажа из снапшота N циклов → `divested`; возвращение → `new_position`; `valid_until < today` → `review_aging`; переклассификация в фонд/облигацию → снять запись (`:1-30`). Stdlib, JSON-in/out |
| Входы | `Portfolio/gate-reviews.yaml`, последний снапшот, today |
| Выход | обновлённый SSOT + log + `archive_entries` (в `gate-reviews-archive-{year}.yaml`) |
| Запись | в `JOB_WHITELIST` и `PV_DIRS` файл читается (`gate-reviews.yaml` — только чтение); записывающего эндпоинта нет → нужен по образцу `cond_save` (`server.py:1951`) |
| Почему срочно | без этой задачи **«оценка устарела» не наступает**, и «Сейчас» (`rebalance-engine.js:26`) продолжает разрешать докупку по просроченному гейту. После нескольких недель это скрытое «разрешено». Эта же проблема у `new_position` для новых тикеров: вьюер сам считает отсутствие записи как «новая» (`06-gates.md`), поэтому здесь безопасно |
| Трудоёмкость | **S–M** (задача + эндпоинт `/api/pv/gates/save` с `base_hash` + запись PyYAML на стороне notify как для cond, + тесты). Либо **S**: вычислять aging во вьюере/engine по `valid_until` (как условия) — тогда писать файл не нужно, но нужно держать паритет JS↔Python |

### 2.6 Прочее ядро (дёшево)

| Что | Скрипт | Для чего | S/M |
|---|---|---|---|
| Stage P coherence | `build_coherence_bundle.py` | еженедельная проверка «пора ли аудит»; но Stage R (Fable) без LLM не запустится | S |
| RECALIBRATE макро-цепочки | `recalibrate.py` | пересчёт Layer 2 при изменении весов в `scenarios/*.yaml` (если вес правит человек; сейчас форм нет) | S, но без формы бесполезно |
| Покрытие и свежесть макро-входа | `coverage_report.py` | «какие факторы просрочены» → показать на хабе | S |
| ИИС-3 шортлист | `iis_shortlist.py` | кнопка «Сумма пополнения → таблица кандидатов» | S–M |
| Недельные Δ цен/книги/индексов | `weekly_changes.py` | вкладка «Изменения» сама показывает; отдельно не нужен | — |
| `reweight_stress.py` | — | разовая таблица «а если веса такие», в браузере → форма «веса сценариев» (S) | S |
| Конверт индекса INDEX/`_sync_log` | `update_index.py` | нужен только если вернётся ручной save-to-library | — |

---

## 3. Цепочка свежести: что произойдёт, если LLM исчезнет в день X

Пороги — `tools/assets/viewer.js:22-41` (`STALE_THRESHOLDS_DAYS`, `STALE_FAIL_DAYS`), `tools/hub.html:328-334` (то же), справка `tools/assets/help/viewer/03-fresh.md`. Push-напоминание — `notifier.py` (один раз на уровень).
«Жёсткая плашка» красная; в справке это означает: **скиллы** на файле отказываются работать. При исчезновении LLM эти отказы бессмысленны — остаётся только цвет.

| Артефакт | Кто делает сейчас | Жёлтая (день X+) | Красная (X+) | Что покажет вьюер/хаб | Живёт ли без LLM |
|---|---|---|---|---|---|
| Снапшот портфеля | **сайт без LLM** (`pf_build.py`, кнопка «Собрать снапшот») | 7 | 30 | зависит от того, загружает ли владелец выгрузки сделок | да, пока есть выгрузки IntelInvest |
| Макро-снимок (`macro-snapshots/ru-*.md`) | скилл `macro-ru-watcher` (LLM + скрипт); автосрез сайта пишет в `auto/` | 7 | — | плашка «макро-снимок» **не увидит автосрез**: `_staleList()` берёт только `d.macroSnapshots` (`viewer.js:2535`), автосрезы — отдельный список `macroAuto` (`viewer.js:72`) → станет жёлтой через 7 дней **несмотря на работающую автозадачу** (бага S: учитывать `macroAuto`, пробный месяц до 21.11) | частично |
| Монитор прогнозов | LLM (Haiku) | 10 | — | «Монитор» жёлтый; на «Действиях» не будет новых HIGH/MEDIUM; notifier перестанет присылать «событие условия» и «новое HIGH» (источник — отчёт монитора) | нет (см. 2.3) |
| Обзор акций | LLM | 14 | 30 | жёлтая плашка, затем красная; вердикты, катализаторы, очередь условий из обзора — замороженные; `drift-badge` «Анализ отстаёт от свежих данных на N дней» (`viewer.js:4490`) | нет |
| Обзор облигаций | LLM | 14 | 30 | то же | нет |
| Стресс | LLM+скрипты | 30 | 60 | стресс-числа привязаны к старому снапшоту и старым сценариям; красная плашка; на странице нет автоблокировок (блокировки — в скиллах) | да при 2.1 |
| Интеграционный анализ | LLM+скрипт | 30 | — | ожидания по горизонтам, «акции против облигаций» устаревают; «Динамика» перестаёт расти | частично при 2.2 |
| Гейты (`gate-reviews.yaml`) | save-to-library/Claude | **нет плашки** | — | срок оценки 45 дн. (60 для голубых фишек): по истечении **статус не меняется** → «Сейчас» разрешает докупку (скрытый сбой, см. 2.5). Новая бумага → «новая», докупка закрыта: ограничение остаётся | нет |
| Условия | Claude (создание/резолюция), notifier (обнаружение) | по датам условий | — | сработавшие условия ждут решения: «Ждут решения» в push каждое утро — это хорошо; резолюции без Claude нет | частично |
| Прогнозы (`forecasts/*.yaml`, `next_due` 3–6 мес) | Claude | по `next_due` (3 мес для ru-macro/global-banks/ru-sellside, 6 — geopolitics/tech-ceo: `weighted_consensus.py` DEFAULT_INTERVAL_MONTHS) | — | плашки нет; признак — «просрочено» в мониторе (которого не будет) и вьюер «Ещё → Прогнозы» (дата прогноза видна) | нет |
| Сценарии и веса | Claude | — | — | жизнь долгая (SSOT весов) | да, замороженные |
| `sanctions_position` | `/sanctions-positions` (Claude) | `stale_after_days: 30` (`sanctions-positions.yaml`; `as_of` 2026-08-06 → **уже просрочено на 2026-11-07**) | — | только внутри скилла стресса | нет |
| Trust matrix (INDEX.md) | retro-audit | — | — | не растёт, существующая работает | да |
| coherence-audit | Fable | в плашки не входит | — | перестанет появляться | нет |

**Хронология «день X → через N недель»** (если владелец продолжает вносить сделки, а LLM нет):

| Неделя | Что видит владелец |
|---|---|
| 0 | Всё актуально |
| 1 | макро-снимок жёлтый (7 дн.); снапшот — по загрузкам |
| 1.5 | монитор жёлтый (10 дн.), push «просрочен» |
| 2 | обзоры акций/облигаций жёлтые (14 дн.) |
| 4 | стресс и интегр. вид жёлтые (30 дн.); обзоры красные (30 дн.) |
| ~6–9 | гейты «истекли» без видимых признаков (скрытая проблема); первыми у тех бумаг, чей разбор был дольше всего назад |
| 8–9 | стресс красный (60 дн.) |
| ≥13 (3 мес) | прогнозы `ru-macro` / `global-banks` / `ru-sellside` на `next_due`; нет монитора, чтобы сказать об этом |

Что остаётся работать полностью: сборка снапшота, доли/план/IE и колонка «Сейчас», живые цены MOEX, ценовые и датовые условия (push), выплаты (купоны/погашения/дивидендная оценка), доходность (XIRR/TWR), журнал решений (пересборка при сохранении снапшота), push на телефон, правка плана/IE.

---

## 4. Ручные замены LLM-режимов формой на сайте

Сайт уже умеет: правку плана (`POST /api/pv/plan/set`, пакет до 50 изменений, `base_hash`, журнал), импорт IE-страницы (`ie-import/ie-set`), импорт/экспорт базы (`plan/import`, `plan/export`), снапшот. **Не умеет:** писать условия, гейты, веса сценариев, прогнозы, вердикты (`09-limits.md`: «Меняет условия и гейты — Claude по фразе; кнопки сайта только копируют команду»).

| Что заменить | Форма | Серверная часть | Реалистичность | Сложность |
|---|---|---|---|---|
| **Условия (Mode 9)**: добавить/перенести/закрыть/«Исполнил»/«Отказываюсь» | заменить «копирующие» кнопки «Решений по счёту» (`07-conditions.md`) на вызовы | эндпоинт `POST /api/pv/cond/save` **уже есть** (принимает готовый YAML + `base_hash`); логику мутации берёт `apply_condition.py` (stdlib, JSON-in/out) — запускать в `hub-notify` (там PyYAML), не в `hub-api` | высокая: схема и CRUD описаны, полный набор тестов есть | **M** |
| **Гейт «подтверждаю держать X»** (без анализа, по явному «да») | кнопка «Подтвердить гейт на 45 дней» в карточке акции | эндпоинт записи `gate-reviews.yaml` + `apply_gate_review.py apply` (валидатор директивы, cooldown, защита «свежая оценка защищена ~3 недели») + журнал `set_by: user` | высокая: уже существует для Claude как `directive`, поле `set_by` предусмотрено | **M** (вместе с 2.5 — **M**) |
| **Новая бумага: снять гейт «новая»** без разбора | та же форма, но с обязательным текстом основания | то же, `set_by: user` | средняя: теряется смысл гейта («жива ли компания как актив на 1–2 года») — это ответственность владельца | **S** сверх предыдущего |
| **Веса сценариев** (SSOT `scenarios/{name}.yaml → matrix.scenario_triggers[*].probability`) | 4 слайдера, Σ=1, `p_by_horizon` опц. (в PSS-9 нужны у всех сценариев) | эндпоинт записи сценария + `recalibrate.py` + `reweight_stress.py` для показа + `validate_library.py` (Σ p=1±0.05) | средняя: сценарий — текст LLM, но веса — числа; `scenario_axis_weights.py` (осевые убеждения) лежит в `_shared-references/` и пакуется в бандл | **M** |
| **Weekly-review как форма «вердикт по бумаге»** | таблица тикеров: вердикт (BUY/ADD/HOLD/TRIM/SELL), уверенность, основание (≤280 знаков), катализатор (дата, p, upside) | сборка YAML через `build_weekly_*_stub.py` (числа) + `carry_over_weekly.py` (перенос) + `render_weekly_md.py` (MD) + `validate-weekly-review-*` (R-COV, форма) | **низкая–средняя**: схема обзора тяжёлая (200–265 КБ YAML), валидатор требует блок `coverage` (`sweep_collect`, `SKILL.md:216`), source `accessed_date`, `kind` катализатора (METH-1). Реалистичен только «лёгкий обзор»: **только изменения вердиктов** по бумагам, остальное переносится как есть (`carried_over: true`) | **L** |
| **«Механическое обновление обзора»** (без LLM, всё как есть + свежие числа) | кнопка/cron | `build_weekly_*_stub` + `carry_over_weekly.py` без delta + `render_weekly_md.py` с автокартой «итог недели: без нового анализа» | **технически S–M, но вредно**: сбрасывает плашку возраста вердиктов (дата файла), скрывая, что вердикты старые. Вьюер уже показывает живые числа сам. Если делать — **не менять `date`/`review_date`** или добавить поле «вердикты от DD.MM» и метку на карточке | M |
| **Прогноз «консенсус по цифрам»** (замена FCA без поиска) | форма: источник, значение, горизонт, уровень доверия (HIGH/MEDIUM из INDEX) | `weighted_consensus.py` (stdlib) + `validate_fca_output.py` + запись `forecasts/*.yaml` | средняя: доверие берётся из `INDEX.md` (вручную), сами цифры владелец ищет сам; полезно только если есть откуда брать | **M–L** |
| **ИИС-3 «что докупить»** | поле «сумма», кнопка | `iis_shortlist.py --json` (ISS) | высокая как «таблица кандидатов без совета» | **S–M** |
| **Закрыть прогноз с исходом** (Workflow close-forecast) | форма: дата, факт, «сбылся/нет» | `references/close-forecast.md` логика + запись `outcome_log` | средняя; схема строгая | **M** |

Оценка в целом: заменить **разбор бумаги** (Mode 4/8) формой нельзя — это и есть ценность LLM. Заменить **управление очередями** (условия, гейты, веса) формой реально и дёшево — это наиболее правильные инвестиции.

---

## 5. Memory-скиллы

| Скилл | Нужен ли без LLM | Почему | Что вместо |
|---|---|---|---|
| **save-to-library** | роль нужна, но не как скилл | Он — единственный писатель `Claude-Memory/` по правилу D3 и держит валидаторы, `INDEX.md`, `_sync_log.md`, concurrency guard (`SKILL.md:228`). Без Claude писать будут сайт и `hub-notify` | (а) валидаторы `assemble_artifact.py validate-*` оставить как библиотеку проверок записи (для задач 2.1/2.2/2.3 и форм); (б) `base_hash`+`.versions/`+атомарная замена уже заменяют Concurrency Guard; (в) `update_index.py`/`_sync_log.md` — по желанию, вьюер INDEX не читает; INDEX нужен FCA/integrated-view (trust matrix) — без Claude не обновляется, существующий остаётся |
| **memory-sync** | **отмирает** | синхронизирует `[lib]`-записи в память профиля Claude (`memory_user_edits`) | ничего: без Claude памяти профиля нет |
| **revise-memory-remote** | сторожевая часть нужна | `validate_library.py` полностью детерминирован; суждения «устарел ли прогноз», миграции — LLM | cron-задача «проверка библиотеки» + push (см. 2.4) |
| **revise-memory-local** (вне списка) | отмирает | чистка auto-memory Claude | — |

Итог по памяти: **ядро записи** (валидаторы, `base_hash`, версии) — сохранить; **интерфейс Claude** — умирает; **INDEX/_sync_log** — перестают быть нужны вьюеру (проверить `PV_DIRS`: `INDEX.md` вьюер не синхронизирует).

---

## 6. Приоритеты (если делать)

| № | Что | Класс/Размер | Эффект |
|---|---|---|---|
| 1 | Авто-aging гейтов (2.5) и/или проверка `valid_until` во вьюере/engine | B / S–M | закрывает скрытую ложную «разрешённость» докупки |
| 2 | Форма условий (резолюция) через `/api/pv/cond/save` | B / M | убирает последнюю обязательную зависимость очереди условий от Claude |
| 3 | Пересчёт стресса на новом снапшоте (2.1) + метка «без пересмотра прогноза» | B / M | возвращает вкладку «Стресс» и вход для «Сейчас» (Mode 3) |
| 4 | Монитор по срокам (2.3) без веб-поиска | B / M | возвращает алерты по срокам и просрочкам в push |
| 5 | Проверка библиотеки по cron (2.4) | B / S–M | сторож целостности после ручных правок |
| 6 | Форма весов сценариев + `recalibrate.py` | B / M | единственный числовой рычаг макро-мира без LLM |
| 7 | Сухая сборка integrated-view (2.2) | B / M–L | возвращает «Интеграционный анализ» и «Динамику» |
| 8 | Мелкий баг: плашка «макро-снимок» не учитывает `macroAuto` (`viewer.js:2535`) | S | убирает ложный жёлтый после перехода на автосрез |

---

## 7. Резюме (10 строк)

1. **Уже без LLM (A):** снапшот (сайт), доли/план/IE и «Сейчас» (JS-зеркало `gate_aware_sizing.py`), живые цены, доходность (Mode 6 — числа), выплаты, журнал решений, обнаружение сработавших условий и push (`notifier.py`), макросрез РФ (пока 5 из 7 индикаторов).
2. **Числовое ядро стресса (A):** `compute_per_position`/`compute_bond_carry`/`compute_portfolio_aggregates`/`validate_stress_output` — stdlib+PyYAML, без сети в режиме `priors`; беты сохранены в старом stress YAML → пересчёт на новом снапшоте на NAS возможен за **M**.
3. **Ограничение пересчёта стресса:** новые бумаги без бет, санкционные позиции (`as_of 2026-08-06`, уже за порогом 30 дн.), споты Brent/золота не обновляются автосрезом; результат — «тот же мир, новый портфель», надо метить и не сбрасывать плашку возраста прогноза.
4. **Главный скрытый риск без Claude — гейты:** `review_aging` ставит только `auto_maintain_gate_reviews.py` при сохранении; без него «Сейчас» через 45–60 дней продолжит разрешать докупку по протухшим оценкам. Лечится **S–M**.
5. **Условия:** обнаружение уже без LLM, резолюция — только через Claude; эндпоинт `/api/pv/cond/save` готов, не хватает формы и вызова `apply_condition.py` в `hub-notify` (**M**).
6. **Integrated-view:** все числа в `aggregate_positions.py` (stdlib), но упаковщик payload и проза — LLM; «сухая» версия на NAS — **M–L**, зависит от свежести катализаторов из обзоров (LLM-авторские).
7. **forecast-monitor:** сроки/просрочки/калибровка полностью в `monitor_alerts.py` → cron на NAS (**M**); проверка «наступило ли событие» и численные пороги (они free-text) требуют LLM+поиск либо миграции формата (**M–L**).
8. **Принципиально C:** новости и вердикты Mode 1/2, разборы Mode 4/5/8, scenario-builder, FCA (поиск источников), hypothesis-stress-tester, retrospective-forecast-audit, forecast-collector, coherence-audit Stage R (Fable). Деградация: вердикты, катализаторы, прогнозы и сценарии замораживаются; обзоры краснеют на 30-й день, стресс — на 60-й.
9. **Memory-скиллы:** `memory-sync` и `revise-memory-local` отмирают (память Claude); `save-to-library` сводится к библиотеке валидаторов + `base_hash`/`.versions/`; `validate_library.py` становится cron-сторожем (**S–M**).
10. **Приоритет вложений:** гейты (S–M) → форма условий (M) → пересчёт стресса (M) → монитор по срокам (M) → веса сценариев (M); weekly-review как форма — L и сомнительна, «автообновление обзора» вредно, пока не показывает возраст вердиктов.
