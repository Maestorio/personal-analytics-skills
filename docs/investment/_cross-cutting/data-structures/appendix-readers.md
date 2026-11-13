> Приложение к `inventory.md` (этап 1, срез 30.10.2026). Собрано субагентом Sonnet только чтением; ключевые утверждения выборочно перепроверены оркестратором по коду и данным, остальное — с опорами файл:строка внутри. Реальные суммы, количества и доли портфеля не приводятся.

# Агент 3 — читатели (группа I) и случаи ошибок (этап 1, data-structures-plan §3.3 I, §3.4)

Только чтение. Опоры: `V` = `tools/assets/viewer.js`, `E` = `tools/assets/rebalance-engine.js`, `S` = `tools/hosting/api/server.py`,
`N` = `tools/hosting/notify/notifier.py`, `PB` = `tools/hosting/notify/pf_build.py`. Данные: зеркало Мака (`~/Library/CloudStorage/SynologyDrive-home/Claude-Memory`)
и снимок NAS в scratchpad `nas/` (снят владельцем 30.10 17:39). «не проверено» — опоры нет.

---

## A. Вьюер

### A1. Что вьюер читает

Один вход данных: `initHttpLoad` (V:447) → `loadHttpMode1` (V:464). Весь пакет файлов — одним `POST api/pv/sync` (`pvSync` V:369–398, тело `{have:{путь: версия}}`, версия = `s:размер:mtime_ns`);
нет ручки / 403 / сбой — запасной путь: листинги Caddy по папкам (`fetchDirListing` V:435) и файлы по одному (`fetchTextRetry`, запрос файла V:548). Копия на устройстве — IndexedDB `FileCache` (V:308, метка `fileCacheMark`).
Парсинг и раскладка по типам — `classifyByName` (V:728) → `ingestFiles` (V:1085).

| # | Путь | Как читается | Функция / файл:строка | Для чего |
|---|---|---|---|---|
| 1 | `Portfolio/integrated-views/integrated-view-*.md` | sync/листинг | `dirs[]` V:467; `parseIntegratedViewMd` V:783 | вкладка «Интеграционный анализ», строки «Действий» (раздел `Действия с высоким приоритетом`) |
| 2 | `Portfolio/weekly-reviews/weekly-review-*.(yaml\|yml\|md)` | sync | V:468; `normalizeWeeklyReview` V:967 | «Акции», «Облигации», карточка, «Действия», «История» |
| 3 | `Portfolio/stress/stress-YYYY-MM-DD*.(yaml\|yml)` | sync | V:469; `normalizeStress` V:987 | «Стресс», «Сценарии» |
| 4 | `Portfolio/snapshots/portfolio-YYYY-MM-DD*.json` | sync | V:470 | всё про позиции; `auto/` не читается (подпапка) |
| 5 | `Portfolio/reports/*.md` (все) | sync | V:471; тип `advisorReport` (V:738), `parseFrontmatter` V:772 | «Reports», подвкладка «Отчёты», замещение обзора, «История» |
| 6 | `Portfolio/decision-journal/{baselines,journal}.json`, `report-YYYY-MM-DD.md` | sync | V:473; `ingestFiles` V:1105 (journal режется до `as_of/summary/flags`) | блок «Помогает ли система» на «Динамике» |
| 7 | `Portfolio/gate-reviews.yaml`, `gate-reviews-archive-YYYY.yaml`, `conditions.yaml` | sync (один листинг на три файла) | V:477 | гейты, условия, «Сейчас» |
| 8 | `macro-snapshots/*.md`, `macro-snapshots/auto/ru-*.json` | sync | V:478–482; `parseMacroSnapshotMd` V:798 | «Макро» |
| 9 | `monitor-reports/monitor-report-*.(yaml\|yml)` | sync | V:483 | «Действия» (монитор), свежесть |
| 10 | `forecasts/*`, `scenarios/*`, `macro-chain/macro-scenarios-*.yaml` | sync | V:484–486 | «Прогнозы», роль прогноза |
| 11 | `domains/{6 папок}/*.md` | sync | V:492 | trust-профили |
| 12 | `POST api/pv/sync` (манифест `have`) | `pvSync` | V:369–398; сервер `pv_sync` S:3206, список папок `PV_DIRS` S:3161 | **список папок продублирован** в V:466–490 и S:3161–3177 (K3) |
| 13 | `GET api/pv/plan` → `plan.json` | `loadPlan` V:11350 (`pvApi` V:11340) | S:3440, `plan_get` S:1925 | план, статус, модель IE, корзины; вливается в снапшот `planApplyToSnapshot` V:11551 |
| 14 | `GET api/pv/plan/journal?limit=200` → хвост `plan-journal.jsonl` | `planJournalLoad` V:10814 (запрос V:10818) | S:3440–3452, `plan_journal` S:2069 (потолок 500) | «план изменён», «Отметка», «История»/«Изменения» (смены плана) |
| 15 | `GET api/moex/quotes?boards=TQBR` (`quotes@1`) | `loadLivePrices` V:1577 (fetch V:1585) | S:3511 | живые цены, база «Сейчас», условия |
| 16 | `POST api/pv/plan/{set,ie-set,ie-import,import}`, `GET plan/export` | `pvApi`/`authFetch` V:10866, 34572, 34854, 35289, 35922, 36036, 36330, 36429 | S:3627–3637 | запись плана (не чтение) |
| 17 | `api/pf/{build,status,save,cancel}` → hub-notify | `pfApi` V:8074 | `pf_build.py` | вкладка «Загрузки» |
| 18 | `api/push/*` → hub-notify | `pushRegister` V:8063; `UI_PUSH_API` ui-kit.js:3130 | N | подписка на уведомления |

**Чего вьюер НЕ читает (проверено grep по `V`, `E`, `*.html`):**
- `api/pv/cond` — **ноль вхождений**. Условия вьюер берёт только файлом `Portfolio/conditions.yaml` через sync (строка 7). Ручка `GET /api/pv/cond` нужна только hub-notify (`N:97`, `COND_URL`).
- `Portfolio/securities/*` и `index.json` — **ноль чтений** (в `V` слово встречается в комментарии V:6056 «живее индекса securities/» и в статусах шагов сборки V:8239, 8243, 8464). Карточка и «История» собираются **в браузере** из #1–#7 + #14. Расхождение с `claude-memory-layout.md`, где читателями индекса названы «вьюер, hub-notify» (проверено: hub-notify тоже не читает — grep `securities` по `tools/hosting/notify/*.py` находит только писателя `pf_build.py:438`). Читателей индекса в коде репозитория нет вообще (grep по `skills/ tools/ _shared-references/`: только писатель, тесты, документы).
- `Portfolio/plan.json`, `plan-journal.jsonl`, `security-types.json`, `snapshots/auto/`, `sensitivity/`, `coherence-audits/`, `inputs/` — не в `PV_DIRS`; план и журнал идут отдельными ручками (#13, #14).
- `hub.html` (группа I): читает только листинги папок `../Portfolio/{integrated-views,weekly-reviews,stress,snapshots}/`, `monitor-reports/`, `macro-snapshots/` — по **имени файла** для плашек свежести (`hub.html:328–334`).

**Копии порогов свежести (K3, сторож — тест):** `STALE_THRESHOLDS_DAYS`/`STALE_FAIL_DAYS` в `V:22,39`, `hub.html:328–334`, `N:145–147` (`STALE_WARN_DAYS`/`STALE_FAIL_DAYS`). Возраст везде — по дате **из имени файла** (`_staleList` V:2535; `dated_files` N:168; `latest()` coherence-audit).

### A2. Четыре места показа — источники и приоритет

Общее для всех четырёх: в браузере нет единого «последнего слова» по бумаге; значение собирается заново из нескольких файлов, а «кто новее» решает **тип источника**, не его дата (кроме одной заплатки 3.114).

**Порядок документов для сравнения «по времени»** (`cmpRecent` V:2765): дата в имени/frontmatter ↓ → `created_at` (`recCreatedAt` V:2758) ↓ → `mtime` файла (из версии sync `s:…:mtime_ns`, `verMtime` V:266) ↓ → имя. У YAML обзора **нет** `created_at` (проверено: ключи обзоров `review_date`, без `created_at`/`generated_at`); время обзора берётся у его md-пары (`_docHM` V:6773 → `reportTimeLabel` V:2772: `created_at` md, иначе `mtime`, **только если день mtime = дата документа**).

#### Место 1. Строка бумаги на «Действиях» (`_actionItems` V:3714; сборка вкладки V:3580–3651; счётчик `actionCounts` V:3188)

| Приоритет | Источник | Правило | Сравнение дат/времени |
|---|---|---|---|
| 1 | `weeklyReviewCurrent` = самый свежий YAML `weekly-review-stock-*` (`wks[0]`, сортировка только по `review_date` V:1128) — вердикт, `advisor_verdict_basis`, `verification_priority`, вес | строка попадает, если `HIGH/MEDIUM` приоритет или вердикт BUY/SELL/TRIM/ADD (V:3719) | при равных датах порядок `Array.sort` по результатам параллельного `Promise.all` (V:1085–1100) — не определён «по времени» |
| 1б | `weeklyBondReviewCurrent` (3.115) | то же правило, V:3728–3734 | — |
| 2 | интеграционный анализ: **разбор markdown-таблицы** раздела `Действия с высоким приоритетом` (`findSectionByPattern` V:4689 + `parseMarkdownTableRows` V:13475), только если `view_date` не старше 14 дн. (`IV_ACTIONS_MAX_AGE_DAYS` V:3713) | дубль тикера отбрасывается (V:3744) | по дате файла, не по времени |
| 3 | замещение: `reviewSupersededBy` V:6108 (см. ниже) → строка уходит в «Сделано» (`_supersededRow` V:3259) | `later(day,time)`: день позже обзора, либо тот же день и **известны оба** времени и разбор позже (V:6114) | **есть сравнение даты·времени** — но времени нет у YAML обзора (берётся из md-пары), а у гейтов и событий условий оно в данных **0 из 28 / 0 из 155 / 0 из 31** (замер ниже) |
| 4 | пометка «план изменён дд.мм: A → B» — `planChangeAfterReview` V:10828 по `plan-journal` (`stocks.T.plan_pct` позже обзора; время обзора как в п.3) | журнал грузится лениво (V:3587), ошибка API — пометки нет | журнал: `ts` UTC → местное время в браузере; хвост 200 (K9) |
| 5 | ограничения владельца: `getActiveConstraint(per_stock[T].user_constraints)` — **копия** `conditions.yaml` внутри обзора (V:3753) | `decided` — max `set_date` без `derived` | копия живёт с датой обзора |
| 6 | условия `conditionsForTicker` (`conditions.yaml`) — «Ждёт условия: …» | — | — |

Где **замещение по гейту/отчёту** (введено 3.114, `9bd22a8f` 29.10): `reviewSupersededBy` V:6108–6135.
- Дата обзора `rd` = `review_date` YAML; время `rt` = `_docHM(md пара)`.
- Признак A (гейт, только акции): `gate-reviews.yaml → tickers[T]`, `set_by ∈ {mode_4, mode_8, user}` (V:6106 `SUPERSEDE_GATE_BY`), `set_date` позже обзора по `later()`; время гейта — `set_time`, иначе `history[-1].time` если `history[-1].date = set_date` (V:6121). **`mode_1/mode_3/auto` не замещают.**
- Признак B (запасной): `reportsForTicker` — отчёты, где ticker/ISIN/**имя** (`_tickerByName` V:9695, `_nameKey`) найдены в `fm.tickers`, и **regexp по свободному тексту `fm.mode`**: `SUPERSEDE_MODE_RE = /(^|[^\d])(4|5a?|8)(?!\d)/` (V:6107), дата отчёта позже обзора по `later()` с временем `reportTimeLabel`.
- Результат `{date, by:'gate'|'report', text, status, report}`; текст замещения — `trigger_reason` гейта или `fm.summary/title` отчёта (V:6126–6133).
- Тот же признак `SUPERSEDE_MODE_RE` повторён в `_secRaw` V:6812 (какие отчёты считать «разбором» в «Истории»/«Изменениях») — **вторая копия правила**.
- Факт по данным: из 53 отчётов `reports/` у 29 `fm.mode` попадает под regexp; 28 различных строк `mode`; `kind` пуст у 5; `created_at` есть у 41 из 53; у 12 в `fm.tickers` не тикер, а имя/ISIN (скрипт `a3_modes.py` в scratchpad).

#### Место 2. Карточка бумаги: «Решение» / «последнее слово» / «История»

Явного «последнего слова» (вердикт + план + триггеры + дата/время + источник одним объектом) в коде нет.

`cardDecisionNode` V:6516 («Решение», подвкладка «Главное»):
| Приоритет | Источник | Откуда |
|---|---|---|
| 1 | вердикт, `advisor_verdict_basis`, уверенность, вес — **всегда из последнего обзора** (`weeklyReviewCurrent`/`weeklyBondReviewCurrent`) | V:6516–6560 |
| 2 | пометка «есть разбор новее» в заголовке и строка «После обзора дд.мм — разбор дд.мм: …» + кнопка «открыть отчёт» — `reviewSupersededBy` | V:6551–6577 |
| 3 | строка гейта: `getGateEntry` V:7866 → `gateLineText` V:6581 (поле `status`, `valid_until`, `cooldown_until`, `set_by`, `set_date`; свежесть гейта **по дате не вычисляется** — статус берётся как записан) | V:6554 |
| 4 | «Для базы «Сейчас»»: `cardBaseNode` V:8759 ← `nowAutoResult` V:8748 (движок E; см. ниже) | V:6572 |
| 5 | пара «вердикт сейчас → при срабатывании»: `conditionVerdictPair` (`conditions.yaml`, только pending) | V:6491–6495 |

«История» (`cardTimelineNode` V:6947; общий сбор `_secRaw` V:6812): объединяет по дате (`cmpTimeline` V:6776, потом время, потом ранг `TL_RANK`)
обзоры (`reviewsForTicker` V:6086), гейт (`history[]` + текущая запись, ключ `дата|статус`), историю условий, отчёты по `SUPERSEDE_MODE_RE`, смены плана
(`_planEventsOf` V:6848 из хвоста журнала, ключи `plan_pct|user_plan|user_status`), сделки (`_tradeEventsOf` — разница количества между снапшотами, без даты сделки). Источника «securities/» нет.
Сравнение дат: только сортировка по `дата(+время)`; время есть не у всех типов событий.

#### Место 3. «Доли и цели»: статус и «план словом» (`renderIeModel` V:10964; строка таблицы V:10995–33009)

| Поле | Приоритет источников | Опора |
|---|---|---|
| «План» (слово: ждать/держать/балансировать/…) | `state.plan.plan.stocks[T].user_plan` (сайт, `plan.json`) → `ie_actual.per_ticker[T].user_plan` снапшота (`??`) | V:11003; слова `USER_PLAN_WORD` |
| «Статус» (DONE/DEFERRED/ORDER/NOTED + свободная строка ≤120) | `plan.json … user_status` → снапшот | V:11003 |
| «Отметка» (когда менялся статус) | `planStatusMarkOf` V:10841 по хвосту журнала (`stocks.T.user_status`), максимум `ts`; нет в хвосте → «—» | V:10841–32547, колонка `markTs` V:11113 |
| доля плана | `plan.json … plan_pct` → снапшот (`planCell` V:10801; расхождение с снапшотом — в подсказке) | V:10801–32418 |
| фактический вливок плана в снапшот | `planApplyToSnapshot` V:11551 затирает `ie_actual.per_ticker[T].{planned_share_pct,user_plan,user_status,user_note_*,ie_new_pct,ie_old_pct}` значениями `plan.json` (в памяти) — «Сейчас» и колонки читают уже **подменённый** снапшот | V:11551–34701; вызовы после загрузки плана/данных/живых цен |
| сравнение с вердиктом обзора | рядом с «Сейчас» подпись «советник: <вердикт> · расходится с планом →» — только направление BUY/ADD против TRIM/SELL (`advVerdictBy`/`nowCell` V:11200–33666) | вердикт — всегда из `weeklyReviewCurrent` (через `pbt`), **без учёта замещения 3.114** |

Сравнения «по дате» между `user_status`/`user_plan` и разбором/гейтом нет: колонки показывают состояние `plan.json`; хронологию отдаёт отдельный столбец «Отметка» только для статуса.

#### Место 4. Колонка «Сейчас» (`renderIeModel` V:11046–33183, `nowCellBase` V:11146, `nowCell` V:11211, плитка `nowTile` V:11061; движок E `runAuto`)

Вход `RebalanceEngine.runAuto(port, gate-reviews, conditions, {quotes, iePrices})` (V:11051):
| Вход | Источник | Свежесть/дата |
|---|---|---|
| позиции, цены, доли, `balance_summary.goals_matrix` | текущий снапшот `portfolioLatest` (после `planApplyAll`, при ответе quotes — копия `applyQuotes` E:~395–450) | `as_of_date` снапшота; живые цены `current_price_ts`; «устаревший» снапшот вьюер не помечает в расчёте |
| план | `plan.json` (вливается в снапшот) | `updated_at` плана |
| гейты | `gate-reviews.yaml` | статус как записан; **дата `valid_until` не сверяется с сегодняшней** (E:26 `BLOCKING_GATE_STATUSES` — по строке статуса; «устаревание» — работа `auto_maintain_gate_reviews`) |
| условия | `conditions.yaml`, только `state === "pending"` в окне `not_before/valid_until` (E:89, 160) | дата сегодняшняя берётся из `snapshot.as_of_date` (E:~200 `today`) |
| цены кандидатов | `state.live.quotes` → цена IE `ie_model.positions[].current_price_rub` (E:175–195) | — |

### A3. Причины, по которым «Сейчас» не выдаёт или урезает предложение (K12)

Показ: «показывается» = причина достигает экрана текстом (колонка «Сейчас», сгиб «заморожено: N бумаг», строка «Для базы «Сейчас»» в карточке); «молча» = решение принято кодом, причина не записана и не видна.

| # | Причина | Где в коде | Эффект | Видна ли причина |
|---|---|---|---|---|
| 1 | Гейт со статусом `new_position / review_needed / reviewed_under_review / review_aging` | E:26, 108–113 (`gate:<status>`) | blocked | **показывается**: `reasonRu` V:8711 → «гейт «…» до дд.мм.гггг» (V:11146 «стоит: …», фолд V:8777, карточка V:8759) |
| 2 | Первая покупка без записи гейта / `divested` | E:112, 137 (`gate:new_position`, «после разбора бумаги») | blocked | показывается (как п.1) |
| 3 | Ждущее условие с `on_trigger BUY` | E:85–93, 114 (`pending_buy_condition`) | blocked | показывается «ждёт условия до …» + расстояние до цены (V:11160–33546) |
| 4 | Ждущее условие с продажей/«держать» (`sell_condition`, `condition_hold`) в окне | E:150–166, 128 | blocked | показывается («условие с продажей id», «созрело … закроет следующий обзор» V:11170–33534) |
| 5 | IPO-гейт: `listing_age_quarters < 8` | E:27, 115–116 (`ipo_gate:Nq`) | blocked | показывается («IPO-гейт · через N кв.») V:8721. **Молча**: у кандидата на первую покупку возраст листинга неизвестен — по IPO не блокируется (E:170–174, намеренно); при `listing_age_quarters = null` блока нет (E:115 `isNum`) |
| 6 | План `WAIT / WAIT/TRIM` | E:31, 117 (`user_plan:WAIT`) | blocked | показывается («план «ждать»») V:8722 |
| 7 | План `KEEP` или `SELL` при недоборе | E:32, 218 (`dormant`, `user_plan:KEEP/SELL`) | нет докупки | показывается («держать (ниже плана)»/«продать — докупки нет» V:11192–33579) |
| 8 | Нет цены у кандидата первой покупки | E:118, 144 (`no_price`) | blocked | показывается («нет цены (ни котировки, ни цены IE)») |
| 9 | Лимит по эмитенту (15 %, исключение SBER 20 % до 2027-02-21) | E:20–24, 228–245, 291–295 (`concentration_breach:X`); срез не разворачивается в докупку E:341–343 | blocked / цель = текущая | **блок показывается** («лимит эмитента X» V:8725); **молча**: ограничение цели среза (E:342) — строка остаётся `в норме` |
| 10 | Недобор ≤ гистерезиса 1 п.п. | E:39, 219–220 (`below_hysteresis:N`) | нет докупки | показывается («в коридоре», подсказка с недобором V:11196) |
| 11 | Перевес в коридоре для `BALANCE` / перевес без `BALANCE` | E:221 (срез только при `gap > гистерезис` и `BALANCE`) | нет среза | показывается словом «в коридоре»/«держать (выше плана)» V:11194 — **без причины, почему нет среза** (например, у плана не `BALANCE`) |
| 12 | Цель меньше одного лота | E:256–264, `lots = 0` | нет сделки | показывается («меньше лота», сумма до цели в подсказке V:11149) |
| 13 | Цена или лот неизвестны | E:~366–368 | сумма без лотов | показывается («лот неизвестен», «лот уточни по котировке») |
| 14 | Нет моей доли плана (`plan_pct = null`, не SELL) | E:~205–208 | нет докупки | показывается «нет моего плана» V:11195 |
| 15 | Бумага вне расчёта: `current_price_source = cost_basis` (заморожённые US), `is_blocked`, фонды денежного рынка `TMON/TPAY/LQDT/SBMM` | E:25, 57–66 | строки нет вовсе | **молча** (в «Сейчас» бумаги просто нет; для замороженных US — решение владельца, но на экране не помечено) |
| 16 | Условие в состоянии `fired`/сработавшее и не закрытое | E:89, 160 (учитываются только `pending`) | не блокирует и не режет | **молча** в «Сейчас» (вьюер показывает такое условие отдельно на «Действиях», но «Сейчас» его игнорирует) |
| 17 | Статус гейта `reviewed_keep/reviewed_buy_more` с истёкшим `valid_until` | E:26 — сверки с датой нет | не блокирует | **молча** (зависит от того, обновил ли статус `auto_maintain_gate_reviews`; в движке сверки нет) |
| 18 | `cooldown_until` гейта | в E **нет** (grep: 0 вхождений) | не влияет на расчёт | только текст «не пересматривать до …» в строке гейта V:6585 — правило запрета не машинное |
| 19 | База не считается (`S ≥ 1` → исключение; `1−S < 0.01` → `manual_check_required`) | E:313–316 | нет сумм | показывается в плитке («не посчитано: …», «база не считается … вопрос к советнику» V:11051, 33198); **молча** на строках: у категории `open` без базы ячейка падает в «в норме» (V:11205) |
| 20 | Вердикт обзора (BUY/SELL/TRIM/ADD) расходится с арифметикой | V:11200–33666 | не меняет расчёт | показывается как «советник: … · расходится с планом →» (вердикт обзора, не последнего разбора) |
| 21 | Заморозка базы «на плане» (перевес заморожённой бумаги) | E:322–338 (`at_plan`) | меняет базу докупки остальных | показывается («на плане: перевес при заморозке» V:8765, фолд V:8785) |

Итого молча: пп. 15, 16, 17, 18 (как правило), ограничение цели по лимиту (9б), IPO без возраста листинга (5б), строка `open` без базы (19б), причина «нет среза» (11).

### A4. Парсеры в браузере (K10)

| Функция | Файл:строка | Что разбирает | Вход |
|---|---|---|---|
| `parseFrontmatter` | V:772 | `^---\n…\n---` regexp → `jsyaml.load` | отчёты `reports/*.md`, trust-профили `domains/`, интеграционный анализ |
| `parseIntegratedViewMd` | V:783 | деление тела по `^##\s+…\n` на секции | интеграционный анализ |
| `parseMacroSnapshotMd` | V:798 | **regexp по названию индикатора в первой ячейке строки таблицы** (список `namePatterns`, год к году против недельной инфляции) | `macro-snapshots/*.md` |
| `extractEquityBondByHorizonV2` / `extractEquityBondNumbers` / `extractEquityBondForView` | V:4855 / 4928 / 5153 | числа «Ожидаемая доходность … **x [lo; hi]**» из прозы §4 (структурный `fm.portfolio_by_horizon` читается первым; проза — запасной путь для весенних отчётов; DRIFT-7 закрыт «как неактуальный» 14.10) | интеграционный анализ |
| `extractVerificationFromIV` | V:9928 | строка таблицы `\|\s*\*{0,2}ТИКЕР\*{0,2}\s*\|`, «последняя колонка» | раздел «Действия с высоким приоритетом» |
| `findSectionByPattern`, `parseMarkdownTableRows` | V:4689, 40425 | поиск секции по regexp заголовка; разбор строк таблицы по `\|` | строки «Действий» из интеграционного анализа (V:3737–3750) |
| `SUPERSEDE_MODE_RE` + `reportsForTicker` | V:6107, 6058 | режим разбора из **свободного** `fm.mode`; бумага из свободного `fm.tickers` (тикер/ISIN/**имя** через `_tickerByName` V:9695, `_nameKey`, `TICKER_ALIASES`) | замещение обзора, «История», «Отчёты» |
| `_isIisReport` | V:2749 | режим 7 из `fm.mode/modes` regexp + запасной по имени файла | вкладка «ИИС-3» |
| `reportKindRu`, `REPORT_KIND_RU` | V:9660–9674 | `fm.kind` → русская метка (свободный перечень; добавление ярлыков — 6ba4981c) | подписи отчётов |
| `splitSentences`, `humanizeText` | V:6455, 6441 | предложения обоснования, чистка служебных фраз (`/^Уверенность\s/`, `/^Условие:/`, `/^(Держать\|Докупать\|…)[\s\d]/`) | блок «почему» карточки (V:6560) |
| `recCreatedAt` | V:2758 | regexp даты-времени `YYYY-MM-DD[T ]HH:MM` из `created_at` | порядок отчётов |
| `_rpMarkBlocks`, `_rpHeadings`, `simpleMarkdownToHtml` | V:9400, 9429, 4730 | разметка/оглавление окна отчёта (отображение, не извлечение значений) | окно отчёта |
| `dateFromName`, `extractDate` | V:182, 1280 | дата из имени файла как запасной источник даты всех типов | всё |
| `_firstH1` | V:9898 | заголовок отчёта из тела | список отчётов |
| `verMtime`, `parseMtime`, `parseAutoindex` | V:266, 261, 251 | время записи файла из версии sync/листинга (HTML-листинг — по ссылкам) | порядок внутри дня |

---

## B. hub-notify и hub-api

### B1. hub-notify (контейнер, том Claude-Memory только чтение; пишет только через hub-api)

| Файл | Читает | Пишет (через hub-api) | Расписание |
|---|---|---|---|
| `notifier.py` (v1.8.0) | с тома `/srv`: `Portfolio/conditions.yaml` (`collect_daily` N:666), `weekly-reviews/weekly-review-{stock,bond}-*.yaml` (последние два; `check_verdicts` N:471), `monitor-reports/*` (`monitor_reports` N:657: порядок по имени + `generated_at`), `Portfolio/snapshots/portfolio-*.json` (имена бумаг, `stock_names` N:645), файлы из `STALE_FILES` (N:151: reviews, stress, snapshots, monitor, integrated-views, macro — **только дата из имени**); живые цены `GET hub-api/api/moex/quotes` (N:689) | `POST /api/pv/cond/save` (N:912–960) — отметка касания порога `touched` + строка `history[price_touched]` | ежедневно `DAILY_AT` 08:30 МСК (3 вида уведомлений); ежечасно будни 10–18 МСК — ценовые условия; состояние `state.json` в томе `/data` |
| `pf_build.py` | загрузки с вьюера (`/api/pf/build`) в томе `/data/pf/runs/<id>/`; из `/srv`: прошлый снапшот, `sector-overrides`, прогнозы, `Portfolio/inputs/`, `gate-reviews.yaml`, `decision-journal/{refusals,theses}.yaml` (`JRN_READS`/`JRN_MANUAL` PB:63–64) | `/api/job/save`: `Portfolio/snapshots/auto/…`, рабочий `Portfolio/snapshots/portfolio-<дата>.json`, `Portfolio/securities/*.json` (`publish_securities` PB:438), `Portfolio/decision-journal/{inputs,baselines,journal}.json`+`report-*.md`, `Portfolio/security-types.json` | по кнопке «Сохранить» вьюера |
| `jobs.py` | `GET /api/job/file` | `POST /api/job/save`, `/api/job/append` (журнал `_jobs/log-ГГГГ-ММ.jsonl`) | общий слой задач |
| `macro_job.py` | `macro-snapshots/` (история для z-score) | `macro-snapshots/auto/ru-<дата>.{md,json}` | будни 08:30, повтор 09:00 при неудаче |
| `eshop.py` | `Gaming/watchlist.yaml` | `Gaming/eshop-prices.json` | ежедневно 08:30 |

Что **читает хронологию бумаги**: уведомитель — только по событиям условий и **сменам вердикта между двумя последними обзорами**; `owner_decided` (N:446–465) исключает смены по решению владельца, в т.ч. **regexp по прозе** `_OWNER_RX` (N:442) в `advisor_verdict_basis`. Разборы `reports/`, `gate-reviews.yaml`, `plan.json`, `securities/` уведомитель **не читает** (grep по `N`: нет вхождений `gate`, `reports/`, `securities`). Строки «Действий» уведомитель не собирает — их строит вьюер (A2 место 1); push ведёт ссылкой на вкладку (`#tab=actions`, `#tab=diff&kind=…`).
`touch_condition` (N:927–960): перечитывает `conditions.yaml`, правит `touched` и `history`, **сериализует файл заново через `yaml.safe_dump(sort_keys=False)`** и пишет с `base_hash` (при 409 один повтор). Второй писатель файла наряду с `apply_condition.py` save-to-library (K11): безопасность — `base_hash` на стороне hub-api; `safe_dump` теряет комментарии и своё форматирование файла (не проверено на реальном файле).

### B2. hub-api (`S`), маршруты портфеля

Версии: каждая запись через `save_file`/`plan_*` — проверка `base_hash` → 409 + `current_hash`, копия прежней в `.versions/` (хранение: `VERSIONS_KEEP=30`, `VERSIONS_DAYS=180`, `VERSIONS_MIN=5`, S:143–150), атомарная замена, доставка в зеркало через File Station; chown на пользователя Drive (S:154+).

| Маршрут | Файл | Чтение/запись | base_hash / версии / журнал | S: строка |
|---|---|---|---|---|
| `POST /api/pv/sync` | `PV_DIRS` (13 папок + 6 domains) | чтение | версия файла `s:размер:mtime_ns`, пачки до 6 МБ, `more` | 3621 → `pv_sync` 3206 |
| `GET /api/pv/plan` | `Portfolio/plan.json` | чтение (`hash`) | — | 3440 → `plan_get` 1925 |
| `GET /api/pv/plan/journal?limit=` | `Portfolio/plan-journal.jsonl` | чтение хвоста, новые первыми, `limit ≤ 500`, битые строки **молча пропускаются** | — | 3440–3452 → `plan_journal` 2069 |
| `GET /api/pv/plan/export?format=json\|xlsx` | `plan.json` | чтение | заголовок `X-Plan-Hash` | 3437 |
| `POST /api/pv/plan/set` | `plan.json` + `plan-journal.jsonl` | запись пакетом (1–50 путей, правила `PLAN_PATH_RULES`) | `base_hash` → 409 со свежим планом; `.versions/`; журнал `{ts, who:"site", path, was, now, reason}` (по строке на путь) | 3627 → `plan_set_batch` 2000 |
| `POST /api/pv/plan/ie-set`, `/ie-import`, `/import` | `plan.json` (+ журнал) | запись | то же; `import` — одна строка `kind:import`; `ie-import` без записи (diff) | 3630–3636 |
| `GET /api/pv/cond` | `Portfolio/conditions.yaml` | чтение `{hash, content}` | — | 3432 → `cond_get` 1939 |
| `POST /api/pv/cond/save` | `conditions.yaml` | запись готового YAML (PyYAML у hub-api нет — проверка только `schema_version: conditions@` и наличия `conditions:`) | `base_hash`, 409+`content`, `.versions/` | 3624 → `cond_save` 1950 |
| `GET /api/job/file?path=` | `JOB_WHITELIST` | чтение (только изнутри docker-сети) | hash | 3498 |
| `POST /api/job/save` | `JOB_WHITELIST` (S:427–446): `Gaming/eshop-prices.json`, `macro-snapshots/auto/ru-*`, `Portfolio/snapshots/auto/*`, `Portfolio/snapshots/portfolio-YYYY-MM-DD.json`, `Portfolio/securities/*.json`, `Portfolio/decision-journal/{inputs,baselines,journal}.json`+`report-*.md`, `Portfolio/security-types.json` | запись | `base_hash`, `.versions/` | 3642 |
| `POST /api/job/append` | `_jobs/log-ГГГГ-ММ.jsonl` | дописывание строки | без копий | 3297, 3642 |
| `GET /api/moex/quotes?boards=` | — (прокси ISS, кэш 5 мин/30 мин) | чтение | `quotes@1`, `stale` | 3511 |

Особенность, имеющая значение для читателей: `append_plan_journal` (S:1971–1992) пишет `plan-journal.jsonl` **прямо в том, без File Station** («журнал читает только hub-api, в зеркала Drive он не нужен»). Поэтому зеркало Мака файл не получает: на 30.10 в зеркале 210 строк, последняя `2026-10-27T14:11:47Z`, mtime 27.10 17:11; на NAS 305 строк, последняя `2026-10-30T11:01:36Z`. Всё, что читает журнал с Мака (скрипты, скиллы, Claude в сессии), его не видит; `securities_index.py` журнал плана не читает вообще (grep `plan-journal` в `securities_index.py`: 0).

**K9 в действии (по снимку NAS):** вьюер просит `limit=200` из 305 записей. Хвост начинается с `2026-10-27T11:22:30Z`; 105 ранних записей не видны вьюеру (71 `ie_model.*`, 17 `user_status`, 8 `user_plan`, 7 `plan_pct`, 2 `note_ai`) — это первый день ведения плана на сайте. `reason` пуст у 299 из 305 записей (поле `kind` в журнале у обычных правок отсутствует).

**Время в данных:** `gate-reviews.yaml` (NAS): 28 записей, `set_time` — у 0; `history[]` — 155 строк, `time` — у 0; `conditions.yaml`: 31 строка истории, `time` — у 0; YAML обзоров: `created_at` нет; отчёты `reports/`: `created_at` у 41 из 53. Документация (`claude-memory-layout.md`, коммиты 3.99 от 28.10) обещает поля, но в данных их нет — **сравнение «по времени» в `reviewSupersededBy` для гейтов и условий на данных 30.10 не работает**, остаётся сравнение по дате. (Запись гейта GMKN 29.10 — `set_date: 2026-10-29`, без `set_time`.)

---

## C. Скиллы-читатели

| Читатель | Файл / ввод | Для чего | Проверка свежести/даты |
|---|---|---|---|
| `portfolio-coherence-audit` Stage P (`build_coherence_bundle.py`) | `discover` :117–127: `Portfolio/snapshots/portfolio-*.json`, `stress/stress-*.yaml`, `weekly-reviews/weekly-review-{stock,bond}-*.yaml`, `integrated-views/integrated-view-*.md`, `macro-chain/macro-marginal-*.yaml`, `macro-scenarios-*.yaml` — **последний по лексической сортировке имени** (`latest()` :112) | кросс-артефактные противоречия | **да, по дате из имени**: окна `STALENESS` (:45: снапшот 14, стресс 90, обзоры 14, IV 14, макро 30 дн.) → `stop`; согласованность `snapshot_id` между артефактами (`consistency_gate` :171–215) |
| `portfolio-coherence-audit` | **`reports/`, `gate-reviews.yaml`, `conditions.yaml`, `plan.json`, `decision-journal/`, `securities/` в bundle не входят** (grep по `build_coherence_bundle.py`: 0 вхождений; Stage R читает только bundle) | — | **разборы Mode 4 аудит не видит вообще** |
| `ru-portfolio-advisor` старт Mode 1/2 (`startup-checklist.md` Шаг 3.5) | `prior_digest.py` (`scripts/`): прошлый `weekly-review-{stock\|bond}-*.yaml` (самый свежий по Glob), `conditions.yaml`, `gate-reviews.yaml`, `Portfolio/reports` за 60 дней, `macro-snapshots/ru-*.md` | выжимка: вердикты, гейты словами, условия, разборы после прошлого обзора, невнесённые директивы гейтов, устаревшие гейты, макроснимок | **частично**: отчёты — по **дате в имени файла** `^\d{4}-\d{2}-\d{2}-` (`prior_digest.py:182,208`), отбор `kind ∈ {single_analysis, tactical_rebalance, stock_quality}` (:184, :232, **свободный `kind`**) либо наличие директив, разбор yaml-блоков в теле отчёта regexp ```` ```ya?ml ```` (:181, :222–227, K10); «директива не внесена»: сравнение **дат** гейта и директивы строго `>` (:239–256), время не учитывается; макроснимок — дата из имени |
| Mode 1/2: учитывает ли разбор Mode 4 по той же бумаге | **да** — раздел «Разборы бумаг после прошлого обзора» (:321–343) выводит `summary` разбора как «исходную точку вердикта»; отбирает отчёты своего класса по `fm.tickers` (тикер или ISIN; для облигаций — любой ISIN в тикерах отчёта, :325–326) | — | порог — дата отчёта ≥ дата прошлого обзора (`>=` по ISO-строке, :328): **разбор в день обзора до него** попадёт в выжимку; время не сравнивается |
| `ru-portfolio-advisor` старт Mode 3/4/5a/8 | `startup-checklist.md` Шаг 3–3.7: снапшот (свежесть 14 дн. и `data_quality_flags`), Шаг 3.7 — `conditions.yaml`, `decision-journal/`; `analysis-process.md` Шаг 5.5 (:52): `gate-reviews.yaml`; Шаг 9.6: `conditions.yaml`; для Mode 3/8 — `stress_digest.py` (свежий `stress-*.yaml`, возраст; Mode 8 — стресс ≤ 60 дн.) | наследование гейта; в Mode 4/8 — «обновитель» | снапшот: `as_of_date` > 7 дн. предупредить, > 14 дн. — просить обновить (Шаг 3); **шага «прочитать прошлые отчёты по этой бумаге» для Mode 4/8/3 в инструкциях нет** (grep по `SKILL.md`, `startup-checklist.md`, `analysis-process.md`: нет «прошлый/предыдущий/последний разбор»); про прежний разбор той же бумаги Mode 4 узнаёт только через запись гейта |
| `ru-portfolio-advisor` Mode 1 Шаг 3.6 | `decision-journal/journal.json` (`pending_questions[]`, `summary`) | вопросы об отказах, строка точности | `journal.json` сам убирает отвеченные; свежесть журнала не проверяется (нет файла — шаг пропускается) |
| `portfolio-integrated-view` | `portfolio-*.json` (≤ 14 дн.), `stress-*.yaml` (≤ 90 дн.), `weekly-review-{stock,bond}-*.yaml/md` (≤ 14 дн.), `macro-chain/macro-marginal-*.yaml` (SKILL.md :31–44) | read-only синтез | `age ≤ …` по файлам; `R-SNAP` — дата снапшота стресса против `snapshot_id` обзора, > 3 дн. → warning (:189); `R-PIPE` — доля неразрешённых `macro_dependency` > 0,3 → отказ (:187). **`gate-reviews`, `conditions`, `reports/`, `plan.json` не входят** |
| `hub-notify` | см. B1 | push | только имя файла (даты); дубли порогов с вьюером |
| вьюер | см. A | — | сравнение дат/времени только в `reviewSupersededBy`/`planChangeAfterReview` и порядке `cmpRecent` |

---

## D. Случаи ошибок за 60 дней (31.08–30.10.2026)

Реестр — отдельным файлом `incidents.md` (там таблица на каждый случай). Здесь — сводка.

**Источники и полнота.**
- `Portfolio/decision-journal/incidents.yaml` (зеркало Мака, 22 записи, 13.10–28.10; журнал введён 07.10, ранее случаев нет; `cost_rub` не заполнено ни у одной).
- `_jobs/log-2026-10.jsonl`: 86 строк (старт 21.10), ошибок 3 — все `pf_build`, 21.10 21:34–22:00, `JSONDecodeError: Expecting value: line 1 column 1` за 0,1 с (первый день сборки на сайте); одно `blocked: true` (22.10 02:13). Дальше сбоев нет; исправление этих трёх в журнале/коммитах не найдено — «не проверено, исправлены ли».
- `TODO.md` (очередь по баллам, RPA/PDL/IE-ASK/PIV), `TODO_design.md` (замечания 14–27.10), `numbers-exit-plan.md` §5a/§5b («найдено по ходу»), `viewer-plan-2026-10-29.md`.
- `html-comments.md`: записей в окне **нет** (последние — 2026-05-09; файл больше не ведётся).
- `git log --since=2026-08-31`: 1122 коммита; отобраны по словам и по `fix(…)` портфельного контура (≈60 коммитов, из них в реестр вошли те, где в теле/заголовке названы симптом и корень).

**Итог:** в реестре `incidents.md` — **50** случаев (22 записи `incidents.yaml` → 17 случаев: записи одного инцидента объединены, `inc-2026-10-28-1` — запись о замене рабочего снапшота, не дефект, не учтена; остальные 33 — TODO и коммиты). Основной класс: K3 — 12, K5 — 7, K6 — 4, K1 — 3, K12 — 3, K2 — 3, K7 — 3, K10 — 2, K8 — 2, K4 — 1, K9 — 1, K11 — 1, вне K — 8 (подача данных, процесс, инфраструктура). С пересечениями: K3 — 18, K5 — 10, K6 — 6, K12 — 6, K1 — 5, K10 — 4, K2 — 4, K7 — 4, K8 — 3, K9 — 3, K4 — 2, K11 — 1.
**Случаи, где корень — парсер текста/frontmatter (K10), — 4:** (1) загрузчик искал колонку средней цены по точному названию (13.10, `a98b061b`); (2) монитор: частичные отчёты распознавались по оговорке в тексте (29.10, `cddba131`); (3) GMKN 29.10 — вывод разбора только прозой/блоком в теле, вьюер выбирает «разбор» regexp по свободному `fm.mode` (открыто); (4) свободный `fm.kind` ad-hoc отчётов (29.09, `6ba4981c`). Действующие парсеры без зафиксированного случая — в конце `incidents.md`. Оценка: непосредственно ошибки из-за парсеров за 60 дней редки; зато почти каждый «выбор источника» во вьюере и в `prior_digest.py` опирается на свободный текст — риск структурный.

**Пять наиболее показательных** (класс K):
1. **GMKN 29.10** — разбор Mode 4 не дошёл до «Действий»: вьюер брал обзор 28.10 как «последнее слово» (K1 + K2 + K4; замещение 3.114 — заплатка, корень не закрыт).
2. **inc-2026-10-27-1/2** — в одном снапшоте две оценки одной позиции (`per_instrument_xirr` на цене последней сделки против `holdings` по цене ISS), откат молча, флага нет (K3 + K12), найдено советником, исправлено `44da2e26`.
3. **3.88.0 «Сейчас» читал план из снапшота на момент сборки** — срез OZON «появлялся и исчезал» (K3: копия плана в снапшоте), исправлено `401d37f0`.
4. **3.110.0 монитор: частичный прогон стирал полную картину**, старые частичные отчёты распознавались по оговорке в тексте «Запуск по одному файлу», порядок отчётов — по имени файла, а не по `generated_at` (K10 + K6), исправлено `cddba131`.
5. **RPA-35 / YDEX 23–26.10 + CNRU + OZON** — решение лежало в прозе отчёта и не было внесено в реестр гейтов; обзор «не знал» ни о разборе, ни о решении владельца, ни о макроснимке (K2 + K3 + K7), исправлено `a5bd62aa` (`prior_digest.py` — но он сам разбирает отчёты по имени, `kind` и yaml-блокам = K10).

**Не удалось проверить.**
- Трассировки GMKN/MDMG по часам: время гейта/условий в данных отсутствует, YAML обзора времени не несёт; MDMG 26.10 — отсутствует первичный разбор в доступных источниках (причина «держать, выше плана» при TRIM и сработавшем условии — только гипотеза по коду: E:89, 160, 221 — «Сейчас» игнорирует `fired`-условия и режет только при плане `BALANCE`).
- Содержимое `.versions/` на NAS и `_jobs` NAS (снимок `nas/` содержит только 5 файлов + `stat.txt`).
- Запись хаба `touch_condition` через `safe_dump` — потеря комментариев в реальном `conditions.yaml` не проверена.
- Что `Portfolio/securities/` читают скиллы «по желанию» (layout) — grep читателей не находит; возможное чтение живым Claude вне кода — не проверяемо.
- Были ли исправлены три ошибки `pf_build` 21.10 (`JSONDecodeError`) — в журнале дальше успех, в коммитах за 21–22.10 явной связи нет.
- Работа вьюера на устройстве (IndexedDB-копия, `FileCache`): поведение при частичном ответе sync — по коду V:516–600, не воспроизводилось.
