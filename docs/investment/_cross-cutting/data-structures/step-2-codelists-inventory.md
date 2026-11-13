> **Сведено в `_shared-references/codelists.json` 31.10.2026 (шаг 2):** вошли п.1 `verdict` (+legacy облигаций), 2 `gate_status`, 3+12 → `actor`, 4 `ticker_class` (по схеме), 6 `user_plan`, 7 `user_status`, 9 `condition_trigger_type`, 10 `condition_kind`, 11 `condition_event` (коды conditions-state@1), 16 `block_reason`, 18 `report_kind`, 19 `mode_codes`, 20 `verification_priority`, 32 категории → `alert_kind`, `ticker_aliases`, новые `asset_class`, `condition_action`, `owner_mark`, `decision_source`, `condition_source`; осталось вне цикла: 5, 8, 13–15, 17, 21–31, 33–40, `VALID_LEVEL_HML`, классы и сроки гейта в `apply_gate_review.py`/`validate_library.py`, `set_by` гейта, `GATE_SET_BY_RU`/`SRC` и `COND_TRIGGER_RU` вьюера, события `conditions@1.2` в `apply_condition.py`, наборы слов плана в движке.

> Подготовка шага 2 цикла машиночитаемости (`decision.md` §4). Собрано агентом Sonnet 30–31.10.2026 только чтением; оркестратор выборочно перепроверил по коду: `set_by: user` отсутствует в `validate_library.py:1079`; `WAIT/TRIM` есть в движке и `gate_aware_sizing.py:144`, но не в `server.py` (`PLAN_USER_PLANS`); вердикты облигаций `WATCH`/`MATURE`/`HOLD_NO_OFFER` реально встречаются в обзорах. Реальные суммы и доли портфеля не приводятся. Назначение: источник для `_shared-references/codelists.json` — какие перечни свести, какие копии удалить, какие коды данных узаконить или мигрировать.

# Инвентарь кодлистов портфельного контура (на 2026-10-30, ветка claude/data-structures)

Только факты. Пути от корня репо `/Users/you/Documents/personal-analytics-skills`, `file:line` по рабочему дереву.
Данные: NAS-снимки (`scratchpad/nas/`: conditions, gate-reviews, plan, plan-journal, security-types) и зеркало `SynologyDrive-home/Claude-Memory/Portfolio/` (reports 54 файла/49 с frontmatter, weekly-reviews 100 файлов, снимки, stress, decision-journal, monitor-reports). Суммы/доли в файл не копировались.
Сокращения: **V** = `tools/assets/viewer.js`, **E** = `tools/assets/rebalance-engine.js`, **S** = `tools/hosting/api/server.py`, **N** = `tools/hosting/notify/notifier.py`, **AA** = `skills/save-to-library/scripts/assemble_artifact.py`, **AC** = `.../apply_condition.py`, **AG** = `.../apply_gate_review.py`, **GAS** = `skills/ru-portfolio-advisor/scripts/gate_aware_sizing.py`, **VL** = `skills/revise-memory-remote/scripts/validate_library.py`, **TR** = `_shared-references/terms_ru.py`, **GS** = `_shared-references/gate_status_ru.py`, **CE** = `_shared-references/constraint_engine.py`, **DJ** = `skills/portfolio-data-loader/scripts/decision_journal.py`, **AS** = `.../assemble_snapshot.py`.

## 1. Сводная таблица

Колонки: № · имя · поле · копий в коде (перечень / словарь слов) · слово есть · тест-сторож · расхождение код/данные.

| № | имя | поле данных | копий (перечень/слова) | рус. слово | тест | расх. |
|---|---|---|---|---|---|---|
| 1 | `verdict` | advisor_verdict, unconstrained_verdict, on_trigger.verdict, while_pending.verdict | 7+ / 3 (+1 производный) | да | частично | да |
| 2 | `gate_status` | gate-reviews.tickers[].status, gate_status_snapshot.status | 6 / 3 | да | да (4 места) | нет (но 3 копии без стража) |
| 3 | `gate_set_by` | gate .set_by, history[].set_by | 5 / 2 (разные слова) | да | нет | да |
| 4 | `ticker_class` | gate .ticker_class | 3 (+доки) / 0 | нет | нет | нет |
| 5 | `critical_event_code` | directive.critical_event_code | 2 / 0 | нет | нет | нет |
| 6 | `user_plan` | plan.json stocks[].user_plan; snapshot ie_actual.per_ticker[].user_plan | 4 / 3 | да | частично | да |
| 7 | `user_status` | plan.json stocks[].user_status | 3 / 3 + свободный текст | да | частично | да |
| 8 | `condition_state` | conditions[].state | 1 (+ слово в V) / 0 | частично | нет | да (history «expired», conditions_state-строка) |
| 9 | `condition_trigger_type` | conditions[].trigger.type | 3 / 1 | частично | нет | нет |
| 10 | `condition_kind` | conditions[].kind | 3 / 1 | да | нет | нет |
| 11 | `condition_event` | conditions[].history[].event | 0 перечня (8 литералов) / 2 | частично | нет | да |
| 12 | `condition_created_by` | conditions[].created_by | 1 (не проверяется) / 0 | нет | нет | да |
| 13 | `condition_touch_source` | conditions[].touched.source | 1 / 1 | да | нет | нет |
| 14 | `constraint_type` | user_constraints[].type | 4 / 1 | частично | нет | да |
| 15 | `constraint_expires_closed` | user_constraints[].expires.type, closed_reason | 2 / 0 | нет | нет | нет |
| 16 | `block_reason` | Сейчас: reason / frozen_reason (`gate:X` …) | 2 (Py+JS) / 1 | да | поведенческий | нет |
| 17 | `rebalance_category` | notes.category, row.direction | 2 / 0 | нет | поведенческий | нет |
| 18 | `report_kind` | reports/*.md frontmatter `kind` | 4 / 1 | да | да (live→V) | да |
| 19 | `advisor_mode` | reports frontmatter `mode`, MODE_RU ключи | 3 / 3 | да | да | да |
| 20 | `level_hml` (verification_priority, source_quality, fundamental_score, div confidence) | per_*.verification_priority и др. | 1 общий набор на 5 полей / 2 | частично | нет | нет |
| 21 | `catalyst_kind` | catalyst[].kind | 1 (inline) / 0 | нет | нет | нет |
| 22 | `asset_type` | holdings[].asset_type, security-types.type | 3 / 3 | да | нет | да |
| 23 | `bond_type` | per_bond.bond_type | 1 / 1 (V, шире) | да | нет | да |
| 24 | `plan_bucket` (+subtype, key) | holdings.plan_bucket/plan_subtype, plan.bonds[], bond_buckets[].key | 6 / 0 | нет | частично | нет |
| 25 | `plan_class` (+matrix, currency) | plan.classes/matrix/funds | 4 / 0 | нет | нет | да (Акция/Акции) |
| 26 | `position_status` | holdings[].status | 2 / 0 | нет | нет | да |
| 27 | `price_source` (current_price_source, bucket_source, ytm_source) | holdings[] | 0 перечня / 2 | частично | нет | да |
| 28 | `dq_flag_code` + `dq_severity` | snapshot.data_quality_flags[] | 0 реестра (67 литералов) / 0 | нет | нет | да |
| 29 | `snapshot_check_id` | checks.py `_r(id, level…)` | 0 реестра (44 литерала) / 0 | да (message_ru) | да (test_snapshot_checks) | нет |
| 30 | `journal_verdict_dir`, `concordance`, `owner_action`, `error_category` | journal.json | по 1 / 0 | нет | нет | да |
| 31 | `incident_category` | incidents.yaml[].category | 0 в коде / 0 | нет | нет | нет |
| 32 | `alert_category` + `alert_severity` | monitor-report alerts[] | 3 / 2 | да | частично | да |
| 33 | `monitor_internal_kind` | monitor_alerts.py alerts[].kind/severity | 0 перечня / 0 | нет | нет | — |
| 34 | `notify_kind` | push-журнал kind, off[] | 1 / (label внутри) | да | да (test_notifier) | нет |
| 35 | `freshness_kind` | STALE_* ключи | 3 (V, N, hub.html) / 3 | да | да | да (AA другой набор) |
| 36 | `doc_status` | reports status/superseded_by | 1 / 1 | да | нет | нет |
| 37 | `caveat_type` (stress) | stress.caveats[].type | 0 перечня / 1 (V) | частично | нет | да (35 из 50) |
| 38 | `provenance` (прогнозы) | events provenance | 3 / 1 | да | нет | нет |
| 39 | `scenario_id` | A/B/C/D, Sc-A.. | 3 / 0 | нет | нет | — |
| 40 | `timeline_kind` | V TL_KIND / TL_RANK | 2 / 1 | да | нет | нет |

Итого 40 строк (в п.1 «verdict» считаю одним кодлистом с подмножествами; п.30 — 4 мини-списка).

## 2. По кодлистам

### 1. `verdict`
| код | слово (TR:33 / V:6429 / N:265) | замечание |
|---|---|---|
| BUY, ADD | Докупать | у N строчными «докупать» |
| HOLD / TRIM / SELL | Держать / Сократить / Продать | |
| HOLD_TO_MAT | Держать до погашения | только облигации |
| HOLD_ADD | Держать, можно добирать | |
| RED_FLAG | Красный флаг | |

- Объявлен (слова): TR:33-36; V:6429; N:265-266 (⚠ SYNC-комментарий N:264); производный `STOCK_VERDICT_RU` `skills/ru-portfolio-advisor/scripts/render_weekly_md.py:328` (= VERDICT_RU верхним регистром + REDUCE, WATCH); `_VCODE_RX` N:267.
- Объявлен (перечень): AA:1242 `VALID_ADVISOR_VERDICT_STOCK` {BUY,HOLD,TRIM,SELL,ADD}; AA:1260 `VALID_ADVISOR_VERDICT_BOND` (+HOLD_ADD, HOLD_TO_MAT, RED_FLAG); AC:93 `VALID_WHILE_VERDICTS` {HOLD,TRIM,BUY,SELL}; AC:95 `VALID_TRIGGER_VERDICTS` {BUY,HOLD,TRIM,SELL,ADD,None}; AC:107 `TRADE_VERDICTS`; AC:1101-1102 `_CONFLICT_IF_SELL/BUY`; CE:210 `ACTIONABLE_VERDICTS`; AA:2458 `DIRECTIONAL_VERDICTS`; DJ:41-42 PLUS/MINUS; V:2982 `TRADE_VERDICTS`; V:3720,3730,3803,3809 inline `['BUY','SELL','TRIM','ADD']`; V:2079 порядок `['BUY','ADD','HOLD','WATCH','TRIM','SELL']`; V:6022 `SORT_ORDINAL`.
- Проверяется: AA:2607 (stock), AA:2999 (bond), AC:363,519,558,572.
- Читается: V:6535,6542,6633,33663 (VERDICT_WORD); N:497,287 (замена кодов в тексте); TR:72 `verdict_word`; V:6756 (TRIM/SELL в условиях).
- Тесты: `tools/tests/test_terms_ru.py::test_verdicts_match_viewer` (TR.VERDICT_RU == словарь V, regex по тексту `const VERDICT_WORD`); `tools/tests/test_notifier.py:296` (N.VERDICT_WORD == {k: v.lower()} из TR.VERDICT_RU). Не охвачены: перечни AA/AC/CE/DJ, inline-списки V.
- В данных (weekly-reviews, все файлы): акции advisor_verdict {HOLD, BUY, SELL, TRIM}; unconstrained {HOLD, TRIM, BUY}; облигации {HOLD, HOLD_TO_MAT, ADD, TRIM, HOLD_ADD, SELL, BUY, RED_FLAG, **WATCH(1), HOLD_NO_OFFER(1), MATURE(2)**} (оба файла 2026-05-12); prior_verdict облигаций {HOLD, TRIM, HOLD_TO_MAT, ADD, SELL, BUY}. Conditions: on_trigger.verdict {HOLD, BUY, TRIM, None}; while_pending {HOLD}; branches then.verdict {HOLD, TRIM, BUY}. journal.json system.verdict {ADD, HOLD, TRIM, None, HOLD_TO_MAT, **WATCH, HOLD_NO_OFFER, MATURE**, HOLD_ADD, RED_FLAG, SELL, BUY}.
- Расхождения: WATCH/HOLD_NO_OFFER/MATURE в данных, нет ни в AA:1260, ни в VERDICT_RU (V покажет код как есть); WATCH/REDUCE есть только в V:2079 и render:328; в данных не встречаются: акции — ADD, HOLD_ADD, HOLD_TO_MAT, RED_FLAG; условия — SELL/ADD as on_trigger.

### 2. `gate_status`
| код | подпись (GS:21 / V:7855) | в BLOCKING |
|---|---|---|
| new_position | Новая | да |
| review_needed | Нужен разбор | да |
| reviewed_keep | Держать | нет |
| reviewed_buy_more | Наращивать | нет |
| reviewed_under_review | На пересмотре | да |
| reviewed_reduce | Снижать | нет |
| review_aging | Оценка устарела | да |
| divested | Продана | нет (V: считается «новая») |

- Объявлен: AG:30 `VALID_STATUSES`; AG:41 `REVIEWED_STATUSES`; VL:1074; GS:21 (+effect); V:7855 `GATE_STATUS_META` (label + cssClass); V:7879 `GATE_PILL_WORD` (производный); V:7963 `GATE_STATUS_HINT` (третий текст); `_shared-references/gate-status-labels.md:19-28`; `_shared-references/yaml-schemas.md:642`; блокирующие: GAS:136, E:26, V:7880 `GATE_BLOCKING`; CE:211 `GATE_REVIEW_PENDING`={review_needed,new_position}; AC:35-47 фолбэк (самодостаточный дубль VALID_STATUSES/REVIEWED_STATUSES); AC:101 `VALID_SET_STATUS`.
- Проверяется: AG:98-114 (переходы: new_position/divested/review_aging — только set_by=auto), AG:173; VL:1145; AA — через constraint/priority; AC:522,567 (set_status).
- Читается: V:3262,4162,5854,6502,6582,7904,8649,34362; GAS:561-563,611; E:112-113,138; `prior_digest.py:136,345`, `render_weekly_md.py:260,503`.
- Тест: `tools/tests/test_gate_status_ru.py::test_same_codes_everywhere` (множества кодов GS == AG.VALID_STATUSES == V.GATE_STATUS_META == строки md-таблицы), `::test_labels_match_viewer` (подписи GS↔V), `::test_md_table_matches_module` (подпись+effect GS↔md). НЕ сверяют: VL:1074, GAS:136, E:26, V:7880 GATE_BLOCKING, V:7963 HINT, CE:211.
- В данных: gate-reviews.status {reviewed_keep 15, divested 6, reviewed_under_review 5, reviewed_reduce 2}; history.status дополнительно {review_aging, reviewed_buy_more, review_needed, new_position}; gate_status_snapshot (weekly) {reviewed_keep, reviewed_buy_more, reviewed_reduce, reviewed_under_review, new_position, review_aging, review_needed}. Все 8 кодов встречаются, вне перечня значений нет.
- Расхождения: нет по составу; риск — 3 копии BLOCKING без стража.

### 3. `gate_set_by`
| код | слово GATE_SET_BY_RU (V:8673) | слово SRC в gateLineText (V:6585) |
|---|---|---|
| auto | автоматически | автоматически |
| mode_1 | обзор недели | обзор недели |
| mode_3 | ребалансировка | ребалансировка |
| mode_4 | разбор бумаги | разбор |
| mode_5a | разбор фонда | разбор фонда |
| mode_8 | оценка качества на 1–2 года | оценка качества |
| user | вручную | решение владельца |
| manual | вручную | решение владельца |

- Объявлен: AG:54 `VALID_SET_BY`={mode_1,mode_4,mode_5a,mode_8,auto,user}; VL:1079 `VALID_GATE_SET_BY`={mode_1,mode_4,mode_5a,mode_8,auto} (БЕЗ user); `yaml-schemas.md:645` (без user); V:6106 `SUPERSEDE_GATE_BY`={mode_4,mode_8,user}; V:8673; V:6585.
- Проверяется: AG:188-193; VL:1156-1161.
- Читается: V:6119,8692,6585; AG:281,290 (mode_4/mode_8 обходят cooldown), AG:340.
- Тест: нет.
- В данных: gate-reviews .set_by {mode_4 13, mode_8 8, auto 6, user 1}; history {mode_8, auto, mode_4, mode_1, user, mode_5a}; **weekly gate_status_snapshot.set_by: `mode_1_mode_8_combined` (22), mode_8, mode_4, auto, mode_1, user**.
- Расхождения: `user` есть в данных и в AG, нет в VL:1079 и yaml-schemas.md (валидатор слоя 5 даст gate_invalid_set_by на реальный файл); mode_3 и manual есть только в V (в данных нет); `mode_1_mode_8_combined` нигде не объявлен (SRC[...]||null → строка без источника); два словаря V дают разные слова для одного кода.

### 4. `ticker_class` — bluechip, mid_cap, small_cap, ipo, event_driven, fund_zpif
- Объявлен: AG:56 (+ AG:59 `VALID_DAYS_BY_CLASS` 60/45/30/30/30/90, AG:67 DEFAULT 45); VL:1080; yaml-schemas.md:650. Слов нет. Проверяется AG:203-208, VL:1167. Тест нет.
- В данных: {mid_cap, bluechip, ipo, fund_zpif, None(1)}; small_cap, event_driven не использованы. Расхождений нет.

### 5. `critical_event_code` — bankruptcy_filing, delisting_announce, sanction_against_issuer, fraud_charges, emergency_ceo_change
- AG:74-80 `CLOSED_CRITICAL_EVENTS`; `skills/ru-portfolio-advisor/references/critical-events-list.md:11+` (2-я копия). Слов нет, теста нет. В данных: history без critical_event_code (155 записей, поле везде None).

### 6. `user_plan`
| код | слово (TR:39 / V:6430 / S:2105) |
|---|---|
| KEEP | держать |
| BALANCE | привести к плану |
| WAIT | ждать |
| SELL | продать |
| BUY | докупать |

- Объявлен: S:1677 `PLAN_USER_PLANS` (валидатор записи); S:2105 `PLAN_USER_PLAN_WORD`; TR:39; V:6430; перечни поведения: GAS:144-145,2090-2094 и E:31-37 (`EXPLICIT_NO_BUY_PLANS`, `NO_BUY_DORMANT_PLANS`, `AUTO_TRIM_PLANS`, `AUTO_SELL_PLANS`, `HOLD_IN_BASE_PLANS`, `FIRST_BUY_PLANS`, `_WAIT_PLANS`/`WAIT_PLANS`) — содержат **WAIT/TRIM**; V:8722 спец-случай `WAIT/TRIM` → «ждать».
- Проверяется: S:1694 `_plan_choice` (PLAN_PATH_RULES S:1879); значения вне 5 кодов отклоняются.
- Читается: V:7328,7332,33309,33771,33909,34281,39642; E:117; GAS:574,656,1335.
- Тесты: `test_terms_ru.py::test_user_plan_matches_viewer` (TR↔V); `tools/tests/test_rebalance_parity.py:505-512` и `test_pages_contracts.py:5657-5659` (6 множеств слов плана Python == JS). НЕ сверяют: S:1677, S:2105 (третья копия слов), WAIT_PLANS отдельно не в списке `test_rebalance_parity`.
- В данных: plan.json {KEEP 20, WAIT 2, SELL 1, BALANCE 1}; plan-journal now {KEEP, WAIT, BALANCE, SELL, BUY}; **исторические снимки ie_actual.per_ticker.user_plan: + `WAIT/TRIM` (24), `TRIM` (12)**.
- Расхождения: WAIT/TRIM — в GAS/E/V, нет в S:1677 и TR (сервер новую запись такого слова отклонит); `TRIM` как план — нигде в коде (только старые снимки).

### 7. `user_status`
| код | слово (TR:45 / V:6431 / S:2106) |
|---|---|
| DONE / DEFERRED / ORDER / NOTED | сделал / отложил / поставил заявку / запомнил |

- Объявлен: S:1681 `PLAN_STATUS_CODES`; S:2106; TR:45; V:6431. Проверка S:1713 `_plan_status`: код ИЛИ любая строка ≤120 (PLAN_STATUS_MAX S:1682); V:11431 `legacyStatus` сохраняет старый текст.
- Тест: `test_terms_ru.py::test_user_plan_matches_viewer` (USER_STATUS_RU↔V). S:1681/S:2106 без стража.
- В данных: plan.json {None 23, DONE 1}; plan-journal now {DONE 3, ORDER 3, DEFERRED 2, NOTED 1, None 8, **'111', 'Заявка подана'**}; в снимках 30+ вариантов текста («Купил 20», «Продал», …).
- Расхождения: свободный текст в данных — нормальный легаси (так задумано, S:1713).

### 8. `condition_state`
- Объявлен: AC:92 `VALID_STATES`={pending, fired}; проверка AC:552. Слов отдельным словарём нет (V строит «ждём»/«сработало» в коде, V:6833).
- Читается: V:8711 reasonRu (`c.state === 'pending'`), V:9022, V:13661; E:150-165; N:328,348,374; GAS:360.
- В данных conditions.yaml: {pending 16, fired 2}. **Weekly `conditions_state[].state` — свободная строка**, а не код: `pending`, `pending (23.10)`, `pending (…) — создано Mode 9 …`, `fired`, `fired 2026-10-01 → записано обзором акций …`, `closed_manual 23.10 (владелец)`, `closed (Mode 9, …)`, `pruned (evaluate …)` (по всем файлам обзоров; читают V:13661 `.includes('closed_manual')`, N:453, `render_weekly_md.py:827`, carry_over_weekly.py:134 как блок целиком).
- Расхождения: у state нет `expired`/`closed_manual` — они кодируются как `fired` + событие истории (AC:722-725, 915); в обзорах слово другое по смыслу.

### 9. `condition_trigger_type` — date, price_above, price_below
- AC:91; AC:112 `_KIND` (date/above/below); проверка AC:469; V:8875 `COND_TRIGGER_RU` (price_above/price_below → «порог цены», date → «дата»); E:100 `conditionUnblockBy` (те же три); N:223 `evaluate_condition`. Теста нет. В данных: {date 14, price_below 3, price_above 1}. Расхождений нет (слово общее для двух кодов).

### 10. `condition_kind` — trade, review
- AC:104 `VALID_KINDS`, AC:170-173 `derive_kind` (нет поля → trade если verdict ∈ AC:107, иначе review); V:2987 `COND_KIND_RU`; V:2982-2985 `condKind` (копия правила). Проверка AC:526. Теста нет. В данных: kind {None 12, review 6} (trade явно не записан — выводится).

### 11. `condition_event` (conditions[].history[].event)
- Перечня нет; литералы пишут: `created` AC:677; `closed_manual` AC:725; `reopened` AC:768; `touched_cleared` AC:773,889; `edited` AC:887; `fired`/`expired` AC:915; `price_touched` AC:974 и N:948.
- Слова: V:6833 `{created: создано, fired: сработало, closed_manual: закрыто, edited: изменено, reopened: перенесено, expired: истекло}`; V:6912 `SEC_EV_COND`={created, fired, closed_manual, executed, expired}; V:8878,41001; N:462.
- Тест: нет.
- В данных: {created 18, edited 10, closed_manual 2, reopened 1}.
- Расхождения: `executed` читают V:6912,41001 и N:462 — писателя в коде не найдено; `price_touched`, `touched_cleared` слов в V не имеют; `edited/reopened` — без слова в SEC_EV_COND.

### 12. `condition_created_by`
- AC:96 `VALID_CREATED_BY`={mode_1, mode_4, mode_8, user} — **объявлено, не используется ни в одной проверке** (grep по AC: только объявление). Слов нет.
- В данных: {user 11, mode_1 3, mode_4 3, **mode_3 1**} (`lsngp-tranche2-rsbu9m`). Расхождение: mode_3 вне перечня.

### 13. `condition_touch_source` — notifier, site, review
- AC:105; слова AC:106 `_TOUCH_SOURCE_RU` (уведомлятель/сайт/обзор); проверка AC:444. Тест нет. В данных touched отсутствует.

### 14. `constraint_type` (user_constraints[].type)
| код | в AA:1866 | в CE (CE:41,46) | в V:6244 | в данных (последние 2 обзора / вся библиотека) |
|---|---|---|---|---|
| no_buy_until_date | да | buy-block | «не покупать до даты» | 4 / 46 |
| price_gate_buy | да | buy-block | — | 0 / 28 |
| price_gate_sell | да | — | — | 3 / 26 |
| no_buy | да | buy-block | — | 0 / 0 |
| hold_override | да | hold-override | — | 0 / 15 |
| manual | да | по умолч. | «решение владельца» | 14+2 / 44+5 |
| no_sell_until_date, no_buy_until_price, no_sell_until_price | нет | нет | есть | 0 |

- Объявлен: AA:1866-1869; CE:41,46; V:6244; `output-templates.md:295-300` (таблица типов, без no_sell_*). Проверка AA:1924. Тест нет.
- Расхождение: V знает 3 кода, которых нет ни в валидаторе, ни в данных, и не знает 4 кодов, которые в данных есть (price_gate_buy, price_gate_sell, hold_override, no_buy) — V:6247 откатится на `type.replace(/_/g,' ')`.

### 15. `constraint_expires_closed`
- `expires.type` {date, price_below, price_above, manual}: AA:1870; проверка AA:1941. `closed_reason` {date_passed, price_crossed_below, price_crossed_above, manual_removed}: AA:1871; проверка AA:1969; `output-templates.md:276`. Слов нет, теста нет. В данных: expires {date, price_below, price_above, manual}; closed_reason {date_passed, price_crossed_below, manual_removed} (price_crossed_above не встречается). Расхождений нет.

### 16. `block_reason` (причины блокировки в «Сейчас»; Py и JS пишут одинаковые строки, склейка через `; `)
| код | слово (V:8711 reasonRu) |
|---|---|
| `gate:<status>` (new_position, review_needed, reviewed_under_review, review_aging) | гейт «…» до даты / «после разбора бумаги» |
| `pending_buy_condition` | ждёт условия |
| `sell_condition:<id>` | условие с продажей <id> |
| `condition_hold:<id>` | условие «держать» <id> |
| `ipo_gate:<N>q` | IPO-гейт · через (8−N) кв. торгов |
| `user_plan:<WAIT|WAIT/TRIM>` | план «ждать» |
| `no_price` | нет цены |
| `below_hysteresis:<x>pp` (dormant) | в коридоре, недобор |
| `concentration_breach:<группа>` | лимит эмитента |

- Объявлен: E:112-118,150-165,218-220,244; GAS:561-578,2309-2318,1839-1846; слова V:8711-8727; `unblock_by` E:138,E:104-109. Теста по словам нет; поведенческие: `test_gate_aware_sizing.py`, `tools/tests/test_rebalance_parity.py` (Py↔JS на фикстурах).
- В данных: живых `notes` в файлах нет (считается на лету). Расхождений нет; `WAIT/TRIM`-ветка V:8722 — единственное место, где слово плана получается из причины.

### 17. `rebalance_category` / `direction`
- category: open, rebalancing, blocked, dormant (+`selling` только в GAS:545-546); direction: buy, trim, hold (E:249-253, GAS:821-835 `_direction_for`); `_ACTED_DIRECTIONS` GAS:182 {buy,trim}. Слов нет; V:11162 читает `category === 'blocked'`. Тест — парность Py↔JS на данных. Расхождение: `selling` есть только в Python.

### 18. `report_kind`
| kind | слово (V:9660 REPORT_KIND_RU) | в enum adhoc-save | в данных (файлов) |
|---|---|---|---|
| tactical_rebalance | Тактическая ребалансировка | да | 25 |
| single_analysis | Разбор бумаги | да | 15 |
| scenario_analysis | Сценарный разбор | да | 3 |
| general | Свободный разбор | да | 3 |
| bond_bridge_planner | Переток облигации → акции | да | 1 (без кавычек) |
| candidates_outside_ie | Кандидаты вне модели IE | да | 1 |
| tax_optimization | Налоговая оптимизация | да | 0 |
| retro_calibration | Самоаудит советов | да | 0 |
| advisory | Инвестиционный обзор | нет | 0 (файл без frontmatter) |
| ie_posts_review | Разбор публикаций IE | нет | 0 (файл без frontmatter) |
| stock_quality | — | нет | 0 |

- Объявлен: `skills/ru-portfolio-advisor/references/adhoc-save.md:42-51` (enum 8); `skills/save-to-library/references/workflow-n.md:13` и SKILL.md:70 (повтор); V:9660; `prior_digest.py:184` `_REVIEW_KINDS`={single_analysis, tactical_rebalance, stock_quality}; префикс имени workflow-n.md:68; AA:4672 `CALIBRATION_KIND_PREFIX` (adhoc, skill, source_rerating, catalyst — **другой** kind для калибровочных отчётов).
- Проверяется: в коде валидатора kind ad-hoc отчёта НЕТ (только в тексте workflow-n.md:35,121; workflow-o.md:37 говорит blocking); V:9674 `reportKindRu` с откатом на `replace(/_/g,' ')`.
- Тест: `tools/tests/test_pages_contracts.py:3972-3989` (все live kind из `Portfolio/reports/` ⊆ ключей REPORT_KIND_RU; пропуск, если библиотека не смонтирована). Обратного направления (enum ⊆ V) нет.
- Расхождения: в данных 5 файлов без `kind` (4 без frontmatter, 1 с frontmatter без kind: `portfolio-candidates-outside-ie-2026-05-13.md`); `stock_quality` — только prior_digest; advisory/ie_posts_review — только V.

### 19. `advisor_mode`
| код (ключ) | слово (TR:25 / V:7982) |
|---|---|
| 1 | обзор акций за неделю |
| 2 | обзор облигаций за неделю |
| 3 | ребалансировка |
| 4 / 4a / 4b | разбор бумаги / акции / облигации |
| 5a / 5b | разбор фонда / подбор фонда |
| 6 | доходность |
| 7 | докупка на ИИС-3 |
| 8 | оценка качества акций на 1–2 года |
| 9 | отложенные условия |

- Объявлен: TR:25; V:7982 (+`_MODE_RE` V:7985, `humanizeText` V:6448-6449); `skills/ru-portfolio-advisor/EXAMPLES.md` (заголовки «Режим 4a/4b/5a/5b», таблица 561-574); `tools/assets/help/viewer/02-models.md:25-34` (таблица режимов — 3-я копия слов, формулировки с «(Mode N)»); `render_weekly_md.py:76,258` (`_MODE_WORDS` ← TR).
- Проверяется: нет; frontmatter `mode` — свободная строка. Регулярки по строке: V:6107 `SUPERSEDE_MODE_RE=/(^|[^\d])(4|5a?|8)(?!\d)/`; V:2749 `_isIisReport` (7|iis-3|иис-3); V:6161 `_modeShort`.
- Тест: `test_terms_ru.py::test_modes_match_viewer` (TR↔V). 02-models.md и EXAMPLES — `test_pages_contracts.py` проверяет наличие файлов/якорей, не значения.
- В данных (`mode` 48 файлов, 27 разных строк): «4 (single)» 9, «free_form» 5, «3 (rebalance_opinion)» 4, «8 (stock_quality_forward_review)» 3, «5a (fund analysis)» 2, комбинации «3 (rebalance) + 4 (single)», «3/4 (…)», «2 (bonds) + 3 + free_form», «5 (fund)», «4 (single) x3», «3 (…) + single-instrument selection»…
- Расхождения: `free_form`, номер `5` без буквы, `4 (single) x3`, `weight opinion` — вне MODE_RU; режима 7 в данных нет (ИИС-3 отчёты не сохранялись); ключей 4a/4b в frontmatter нет (пишут «4 (single)»).

### 20. `level_hml` (один набор HIGH/MEDIUM/LOW на 5 разных полей)
- AA:1241 `VALID_LEVEL_HML` — verification_priority (AA:2604,3002), source_quality катализатора (AA:1679), bond credit_quality/by_credit_quality ключи (AA:2948,2997,3003), dividend confidence (AA:2195); отдельно AA:1240 `VALID_FUNDAMENTAL_SCORE`={HIGH,MEDIUM,LOW,RED_FLAG}; AA:546 `VALID_TRUST_LEVELS` (+IGNORE); CE:248-263 `compute_verification_priority` (производное, AA:2107-2135 сверяет → warning); V:3761 `PRIORITY_RU`={HIGH: срочно, MEDIUM: желательно, LOW: не срочно}; V:13574 `SEV_RU` (важно/средне/слабо/справка); V:145 `DIV_CONF_CI_REL`.
- Тест: нет на слова. В данных: verification_priority {LOW, MEDIUM, HIGH}; source_quality {HIGH, MEDIUM, LOW}; fundamental_score {HIGH, MEDIUM, LOW, RED_FLAG}. Расхождений нет. Слово PRIORITY_RU относится только к verification_priority; к source_quality слова нет.

### 21. `catalyst_kind` — binary, quantitative
- AA:1719 inline (`kind_s in ("binary","quantitative")`, нижний регистр); `classify_catalyst.py`; `carry_over_weekly.py:549` (имя поля). В данных {binary, quantitative, None(79/143)}. Слов, теста нет.

### 22. `asset_type`
- Значения stock, bond, fund (+ other): `security_types.py:52-57` `MOEX_GROUP_TO_TYPE`, :237 `SURE_TYPES`, :281 `TYPE_RU` (акция/облигация/фонд/другое); V:8349 `PF_TYPE_RU` (те же слова — копия); `securities_index.py:47` `KIND_RU` (мн. число: акции/облигации/фонды); AS:1867 (`at if at in (stock,bond,fund) else other`); `portfolio_returns.py:2765`; `shadow_baselines.py:51` `CLASSES`=(stock,bond,gold,other,cash) — другой набор. Проверки в коде: нет перечня-валидатора поля holdings.asset_type. Теста слов нет.
- В данных: holdings {stock, bond, fund}; security-types.json {bond 92, stock 84, fund 34, other 7, **null 89 (note «нет на Мосбирже»)**}. Расхождения: `null` в security-types не из перечня; `other` в снимке не встречается.

### 23. `bond_type`
- AA:1243 `VALID_BOND_TYPE`={ofz, corp_rub, fx_replacement, floater, perpetual} (проверка AA:2992); yaml-schemas.md:310,428; V:2257 `bondTypeLabel` (ofz→ОФЗ, corp_rub→Корп RUB, fx_replacement→Замещайка, floater→Флоатер, perpetual→Вечная, **bonds_to_offer→С офертой, municipal→Муниципальная**). Теста нет.
- В данных (bond): {ofz, fx_replacement, corp_rub}. Расхождения: в V два кода вне валидатора; floater/perpetual в данных нет.

### 24. `plan_bucket` (тип/подтип/ключ корзины плана)
- Типы: S:1729 `PLAN_BOND_TYPES`=(ОФЗ,КОРП,USD,EUR,CNY); подтипы S:1730 (>10,<10,Флоат,AA+,A,B+); ключи S:1728 `PLAN_BUCKET_KEYS` (9: USD,EUR,CNY,ОФЗ/>10,ОФЗ/<10,ОФЗ/Флоат,КОРП/AA+,КОРП/A,КОРП/B+); V:12131 `PLAN_BUCKET_KEYS`; `parse_portfolio.py:156` `VALID_TYPE_SUBTYPE`; AA:1247 `VALID_PLAN_BUCKET_SUBTYPE`; `bond_bucket.py:32` `FX_BUCKETS`; `parse_portfolio.py:136-150` лестница рейтингов и `CORP_SUBTYPE_BUCKETS`; AA:1255 `VALID_BOND_RATING_VALUES`; AA:1259 агентства (=`bond_bucket.py:30`).
- Проверка: S:1886-1887,1896 (запись), AA:2736-2744, `parse_portfolio`. Тест: `test_pages_contracts.py:5182,5264` (V.PLAN_BUCKET_KEYS буквально). Слов нет (ключи — сами русские).
- В данных: plan.json type {КОРП, ОФЗ, USD, CNY, EUR}, subtype {None, B+, A, AA+, >10, <10, Флоат}; bond_buckets 9 ключей = S:1728; funds.bucket {None, ОФЗ/<10, USD}. КОРП/Флоат структурно разрешён (AA:1247, parse:156), в ключах корзин нет.

### 25. `plan_class` (+ matrix class, currency)
- S:1725 `PLAN_CLASSES`=(Акции,Облигация,Золото,Другое,Кеш); S:1726 `PLAN_MATRIX_CLASSES`=(Кеш,Акция,Облигация,Золото,Другое); S:1727 `PLAN_CURRENCIES`=(RUB,USD,EUR,CNY); V:12730 `FUND_CLASSES`; AS:947-952 `CLASS_ORDER`, `_CLASS_CANON`, `_CLASS_PLAN_NAME` («Акция»→«Акции»). Проверка S:1893-1894 и regex-пути S:1881-1882. Тест: нет по составу.
- В данных: classes {Акции, Облигация, Золото, Другое, Кеш}; matrix class {Акция, Другое, Облигация, Кеш, Золото}; funds.class {Другое, Облигация, Кеш, Золото}; manual_positions.type — свободные строки вида «USD - Облигации», «RUB - ИИС».
- Расхождение: «Акции» и «Акция» — два написания в двух перечнях (намеренно, S:1726).

### 26. `position_status` — normal, blocked, distressed
- AS:78 `POSITION_STATUSES`; AS:87 `KNOWN_POSITION_STATUS`; чтения V (is_blocked, 'blocked' V:11162 — другое поле), `yaml-schemas.md`. Слов нет, теста нет. В данных: {normal, blocked}; distressed в снимках не встречается, но флаг `distressed_positions` был (8 раз).

### 27. `price_source`
- Перечней нет; слова: V:12731 `FUND_SRC_RU` (moex_iss, moex_live, last_trade, cost_basis); V:12791 `BOND_SRC_RU` (iss, rating). yaml-schemas.md:318 `ytm_source: moex_iss | intelinvest | manual_estimate`.
- В данных: current_price_source {moex_iss, last_trade, cost_basis}; bucket_source {iss, rating, **plan**}; ytm_source {moex_iss}; current_price_basis {last, prev_close}; account {main, iis_3}.
- Расхождения: `plan` (bucket_source) и `prev_close` без слов; `moex_live` — только V.

### 28. `dq_flag_code` + `dq_severity`
- Реестра нет. 67 кодов — литералы в `_flag(step, severity, code, msg)` AS:346 и словарях: asset_type_changed, avg_cost_fallback_value_over_qty, balance_*, blocked_positions_*, bond_* (bond_bucket_changed, bond_bucket_not_in_plan, bond_rating_missing, bond_subtype_unknown …), cash_* , distressed_positions, iis_*, implied_bond_price, moex_*, manual_* … (полный перечень — AST по `portfolio-data-loader/scripts/*.py`). Подмножества: `build_snapshot.py:67` `DECISIONS` (4 флага, требующих решения), `build_snapshot.py:84` `ATTENTION_FLAGS` (13), `build_snapshot.py:895` `LEVEL_RU` (block/warning/info).
- severity в литералах: info 25, warn 24, warning 20, error 3; в данных: {info, warn, warning}.
- В данных (41 снимок) 26 различных code; один флаг — строка вместо объекта (`holdings_only: …`). Теста нет. Расхождение: `warn` и `warning` — два написания одного уровня; `error` в данных не встречается; в `LEVEL_RU` нет warn/error.

### 29. `snapshot_check_id` (checks.py)
- 44 id в `_r(id, level, …)` (checks.py:112), level {block, warning, info} (`ORDER` checks.py:557); русское сообщение в `message_ru`. Перечня нет. Тест: `skills/portfolio-data-loader/tests/test_snapshot_checks.py` (по реестру тестов — фикстуры на проверки).

### 30. журнал решений (journal.json)
- `direction` «+»/«−»: DJ:41-42 (PLUS/MINUS), DJ:52 `direction()`; `concordance` {followed, ignored, contrary, acted_on_hold, n/a}: DJ:143-153; `owner.action` {none, bought, sold}: DJ:134; `error_category` {data, forecast}: DJ:322-324; HORIZONS DJ:43 {1m,3m,12m}. Слов в коде нет, теста нет.
- В данных: concordance {ignored, n/a, acted_on_hold, followed} (contrary не встретился); error_category {None, data, forecast}; episodes.concordance {ignored 58, followed 35}; record kind {verdict}; gate_changes/plan_changes kind {gate_change, plan_change}.
- Расхождение: system.verdict берёт значения без перечня → `WATCH`, `HOLD_NO_OFFER`, `MATURE` (см. п.1) попадают в записи; для них direction = None.

### 31. `incident_category` — data, process (incidents.yaml, 22 записи: data 17, process 5)
- В коде перечня нет (`decision_journal*.py` читает категорию как строку; DJ:466 считает только `error_category == "data"`). Слов, теста нет.

### 32. `alert_category` / `alert_severity` (monitor-report@1)
- AA:4739 `_MR_SEVERITIES`={HIGH,MEDIUM,LOW,INFO}; AA:4740 `_MR_CATEGORIES`={stale, horizon_passed, event_window, factor_breach, source_dead, prediction_due, catalyst_missed}; AA:4741 `_MR_FRESHNESS`; yaml-schemas.md:474-479 (+ `target_kind`: forecast|scenario|catalyst|source|view); V:3562 `MON_CAT_RU` (7 категорий, слова); V:3489 `_SEV_RANK`; V:13574 `SEV_RU`; V:3195-3196,3448,3571-3575 читают HIGH/MEDIUM; N:561 (HIGH).
- Проверка AA:4757-4818. Тест: валидатор — `skills/save-to-library/tests/test_assemble_artifact.py` (monitor-report); слова категорий не сторожатся.
- В данных (monitor-reports): category {factor_breach, event_window, stale, catalyst_missed, prediction_due}; severity {MEDIUM, HIGH, LOW, INFO}; freshness_audit ключи {weekly_review, macro_snapshot, integrated_view, stress, trust_matrix, **portfolio_snapshot**}.
- Расхождения: `portfolio_snapshot` вне AA:4741; source_dead/horizon_passed в данных нет.

### 33. `monitor_internal_kind`
- `skills/forecast-monitor/scripts/monitor_alerts.py`: kind {review:142, horizon_passed:179, deadline:210, monitoring:252, threshold:279, falsifier:302, outcome_capture:359, catalyst:623, condition_event:710}; severity {red, yellow, none} (:89-103,:181,:281,:361); `SEVERITY_ORDER` :44 {critical, high, medium, low}. Это третий словарь важности (рядом с HIGH/MEDIUM и stale_flags critical/warning, yaml-schemas.md:600). Правила перевода в категории отчёта в коде нет (делает LLM по SKILL.md). Теста на значения нет.

### 34. `notify_kind`
- N:113-125 `KINDS` (id+section+label+desc): cond_open, cond_date, cond_price, verdict, monitor, stale, eshop, eshop_sale; `KIND_IDS` N:128; `KIND_SECTION` N:134; SECTIONS N:132 (portfolio, games). Подписи «живут только здесь» (N:111); V берёт из `/api/push/status`. Тест: `tools/tests/test_notifier.py` (виды/выключение/журнал). Режим `quiet|live` N:720.

### 35. `freshness_kind` (stocks, bonds, stress, portfolio, monitor, integratedView, macro)
- V:22 `STALE_THRESHOLDS_DAYS`, V:39 `STALE_FAIL_DAYS`; N:145 `STALE_WARN_DAYS`, N:147 `STALE_FAIL_DAYS`, N:148 `STALE_LABEL`, N:584 `STALE_SHORT`, N:586 `STALE_CMD`, N:151 `STALE_FILES`; `hub.html` (failAfter); справка `03-fresh.md`. Тесты: `test_notifier.py` (пороги N == V), `test_pages_contracts.py` ось «свежесть». Другой набор ключей у AA:4741 `_MR_FRESHNESS` (integrated_view, stress, weekly_review, macro_snapshot, trust_matrix).

### 36. `doc_status`
- V:3321 `DOC_STATUS_RU`={active: действует, superseded: заменён новым файлом, resolved: разрешён, archived: в архиве}; в данных reports: status {superseded 3} (+ supersedes/superseded_by/superseded_date/superseded_reason по 3). Перечня-валидатора нет. `yaml-schemas.md:605` stale_flags.status {active, resolved} — отдельный набор.

### 37. `caveat_type` (stress.caveats[].type) — открытый словарь
- V:13564 `CAVEAT_TYPE_RU` (15 ключей); V:13606 использует с `|| null`. Валидатора перечня нет (AA:693-698 — только запреты полей basis). В данных (stress/*.yaml): 50 различных type; **35 не имеют слова во V** (например CARRY_MODEL_OMISSIONS, EUR_VIA_USD_PROXY, FX_ASSUMPTION_CARRIES_THE_RESULT, MATURITY_GUARD_APPLIED, BETAS_REUSED_FROM_PREVIOUS_RUN, IIS_SPLIT_POSITION …); близкие по смыслу, но разные коды: V `EUR_VIA_USDRUB_PROXY` / данные `EUR_VIA_USD_PROXY`; V `FX_ASSUMPTION_DRIVES_RESULT` / данные `FX_ASSUMPTION_CARRIES_THE_RESULT`. severity {HIGH, MEDIUM, LOW}: V:13574. Хвосты V:13498 `TAIL_META` {sign_unresolved, binary_skew, portfolio_tail}. Теста нет.

### 38. `provenance` (events)
- AA:3435 `VALID_PROVENANCE` (6), AA:3443 `LEGACY_PROVENANCE_MAP` (4), AA:3451; V:14070 `PROVENANCE_RU` (canonical + legacy); `events-yaml-spec.md §5`. Теста нет. Вне портфельного ядра; приведено из-за соседства.

### 39. `scenario_id`
- AA:1801 `_VALID_SCENARIO_IDS` {A,B,C,D,Sc-A..Sc-D}; AA:3335 `VALID_SCENARIO_POLE`; AA:3455-3456 `VALID_MODAL_SCENARIO`/`REQUIRED_BY_SCENARIO_KEYS`; yaml-schemas.md:76. Слов нет.

### 40. `timeline_kind` — rev, report, gate, cond, plan, trade
- V:6776 `TL_RANK` (порядок) и V:6782 `TL_KIND` (слова: обзор, разбор, гейт, условие, план, сделка). Теста нет.

## 3. Таблицы соответствия между кодлистами, уже существующие в коде

1. **Вердикт условия → вид действия**: `on_trigger.verdict ∈ {BUY,SELL,TRIM,ADD}` → kind=trade, иначе review: AC:170-173 ↔ V:2982-2985 (две реализации).
2. **Условие → причина блокировки**: on_trigger.verdict BUY → `pending_buy_condition`; TRIM/SELL → `sell_condition:<id>`; while_pending HOLD/TRIM/SELL (не-BUY триггер) → `condition_hold:<id>`: E:150-165, GAS:2250-2279.
3. **Статус гейта → блокировка покупки**: {new_position, review_needed, reviewed_under_review, review_aging} → `gate:<status>`: GAS:136,561-563 / E:26,112-113 / V:7880; допуск «до 1 п.п.» по статусу — `gate-status-labels.md:16` и GS:21-30.
4. **Статус гейта → verification_priority**: CE:211 `GATE_REVIEW_PENDING` {review_needed,new_position} → HIGH (CE:253); вердикт ∈ ACTIONABLE → HIGH (CE:251), unconstrained/условие actionable или conf<0.6 → MEDIUM (CE:254-262).
5. **set_by → статус**: new_position/divested/review_aging допустимы только при set_by=auto (AG:103-114); cooldown обходят mode_4/mode_8 (AG:290); `conditions.on_trigger.set_status` ограничен REVIEWED ∪ {review_needed} (AC:101).
6. **set_by ↔ режим**: `mode_N` ↔ ключ MODE_RU (mode_1→1, mode_4→4, mode_5a→5a, mode_8→8; mode_3 ↔ 3 есть только в V:8673,6585). Замещение строки обзора: гейт с set_by ∈ SUPERSEDE_GATE_BY={mode_4,mode_8,user} (V:6106,6119) ИЛИ отчёт с mode по SUPERSEDE_MODE_RE=(4|5|5a|8) (V:6107,6130,6840) — множества не совпадают (mode_5a в гейтах не замещает, режим 5 в отчётах замещает).
7. **kind отчёта → имя файла**: `{kind-slug}` = kind c `_`→`-` (`workflow-n.md:68`); kind калибровки → префикс AA:4672. **kind ↔ mode** автоматической связи нет: mode — свободный текст (`adhoc-save.md:29-33`: «7 (iis3 buy)» обязательна для ИИС-3, V:2749 ищет её регуляркой).
8. **Слово плана → поведение «Сейчас»**: KEEP,SELL → dormant `user_plan:X`; WAIT,WAIT/TRIM → blocked `user_plan:X`; BALANCE → срез до плана при перевесе > гистерезиса; SELL → срез до нуля; KEEP,BUY → в базе без операции; BUY,BALANCE → кандидат на первую покупку: GAS:2062-2094 (таблица в комментарии), E:31-37, GAS:1308-1335.
9. **Тип ограничения → вердикт**: `_is_buy_block_type` {no_buy_until_date, price_gate_buy, no_buy} блокирует BUY/ADD→HOLD; `hold_override` блокирует любой не-defensive вердикт: CE:39-46; AC:1101-1102 `_CONFLICT_IF_SELL/BUY`.
10. **Вердикт → направление эпизода журнала**: PLUS {BUY,ADD,HOLD_ADD} / MINUS {TRIM,SELL,RED_FLAG}: DJ:41-42 ≈ AA:2458 DIRECTIONAL (одинаковый состав, два объявления).
11. **Тип по группе MOEX → asset_type**: `security_types.py:52` stock_shares/stock_dr/stock_foreign_shares→stock, stock_bonds/stock_eurobond→bond, stock_etf/stock_ppif→fund, прочее→other; рейтинг → корзина КОРП: `parse_portfolio.py:146` (AAA..AA-→AA+; A+..A-→A; BBB+..B-→B+).
12. **Класс плана ↔ класс матрицы**: «Акции» (classes) = «Акция» (matrix): AS:952 `_CLASS_PLAN_NAME`.
13. **Уверенность вердикта → слово**: advisor_verdict_confidence < 0.6 «низкая», 0.6–0.8 «средняя», ≥ 0.8 «высокая»: TR:60-69 ↔ V `confWord` (стережёт test_terms_ru).
14. **Статус гейта → слово в тексте владельца**: GS:21 ↔ GATE_STATUS_META V:7855 (подпись) ↔ GATE_PILL_WORD V:7879 (нижний регистр) ↔ HINT V:7963 (длинный текст, не совпадает с GS-effect дословно).

## 4. Чего в коде нет, но данные этого требуют

| что | где в данных | чего нет в коде |
|---|---|---|
| bond verdict `WATCH`, `HOLD_NO_OFFER`, `MATURE` | weekly-review-bond-2026-05-12.yaml; journal.json system.verdict | AA:1260, TR:33, V:6429 |
| gate `set_by=user` | gate-reviews (1 + 3 в history) | VL:1079, yaml-schemas.md:645 |
| gate_status_snapshot `set_by=mode_1_mode_8_combined` | weekly stock (22 раза) | AG:54, V:8673, V:6585 |
| condition `created_by=mode_3` | conditions.yaml (1) | AC:96 (и проверки created_by нет вовсе) |
| user_constraints `price_gate_buy/price_gate_sell/hold_override/no_buy` | weekly stock | V:6244 CONSTRAINT_TYPE_RU |
| user_plan `WAIT/TRIM`, `TRIM` | исторические снимки ie_actual (24 / 12) | S:1677, TR:39 (WAIT/TRIM есть в GAS/E) |
| user_status — свободный текст (`111`, `Заявка подана`, «Купил 20» …) | plan-journal, снимки | перечень намеренно открыт (S:1713) |
| conditions_state[].state — строка с датой и пояснением (`pending (23.10)`, `fired … → записано …`, `closed_manual 23.10 (владелец)`, `pruned (…)`, `closed (Mode 9, …)`) | weekly-review-*.yaml | перечня кодов и поля даты нет (V:13661 ищет подстроку) |
| condition history `price_touched`, `touched_cleared`, `executed` | AC пишет первые два; `executed` читают V:6912,41001, N:462 | слов в V:6833; писателя `executed` не найдено |
| bucket_source `plan`, current_price_basis `prev_close` | holdings | V:12791 BOND_SRC_RU, слов нет |
| dq severity `warn` и `warning` | snapshot data_quality_flags | единого набора нет; `LEVEL_RU` build_snapshot.py:895 знает block/warning/info |
| security-types.type `null` («нет на Мосбирже») | security-types.json (89) | не входит в stock/bond/fund/other |
| freshness_audit `portfolio_snapshot` | monitor-report (2 файла) | AA:4741 |
| mode `free_form`, `5`, `3/4`, `4 (single) x3` | reports frontmatter | MODE_RU V:7982/TR:25 |
| report kind: файл без `kind` (1) и без frontmatter (4) | reports/ | валидатора kind в коде нет |
| stress caveat type: 35 из 50 | stress/*.yaml | V:13564 |
| поля без перечня, читаемые как коды: `fired_by` (AC:913; значения trigger/expiry), `critical_event_code`, `incident.category`, `error_category`, `target_kind` | см. выше | перечней в коде нет |
| поле `flags.*` в weekly-review | не найдено ни в последних, ни в старых файлах | — |

Объявлено в коде, но не встречено в данных: ticker_class small_cap/event_driven; user_plan BUY в plan.json (есть только в журнале); constraint `no_buy`; condition `kind=trade`; VERDICT stock ADD/HOLD_ADD/RED_FLAG; bond_type floater/perpetual; position_status distressed; report kind tax_optimization/retro_calibration; V `bonds_to_offer`/`municipal`; Python-категория `selling` (GAS:545); VERDICT акций ADD/HOLD_ADD/RED_FLAG; constraint `no_buy`.

## 5. Не проверено

- Не просматривал построчно тела `portfolio-integrated-view`, `portfolio-scenario-stress`, `portfolio-coherence-audit`, `macro-forecast-chain`, `scenario-builder` на собственные enum (только то, что лежит в AA/V/yaml-schemas.md); `coherence-audit`/`integrated-view` frontmatter-значения не снимал.
- Не делал полный перечень 67 кодов data_quality_flags и 44 id checks.py поимённо в блоке п.28/29 (получен AST-обходом; список воспроизводится командой); не сверял каждый с `build_snapshot.py` DECISIONS.
- Остальные словари V по макро/прогнозам (FACTOR_RU V:3334, UNIT_RU V:14209, UNIT_HUMAN_LABELS V:10524, MON_CAT) и страниц games/health/food (HEALTH_SCHEMAS, FOOD_SCHEMAS в S) не разбирал.
- `tools/hosting/api/server.py` — только PLAN_*-блок; другие whitelists (WHITELIST S:366 и т.д.) — пути, не коды.
- Реальные значения проверены только на подмножестве: conditions/gate-reviews/plan/journal-снимки NAS от 30.10; `Portfolio/reports/` целиком (54 файла); weekly-reviews — полная библиотека (по значениям) и два последних stock/bond; stress/monitor-reports — по всем файлам для caveat/category. `Claude-Memory/Portfolio/securities/`, `coherence-audits/`, `integrated-views/` не открывал.
- Не проверял, срабатывает ли VL на реальный gate-reviews.yaml (вывод «даст gate_invalid_set_by» — по чтению кода VL:1155-1161, запуск валидатора не делал).
- Не запускал тесты; утверждения о том, что тест сверяет, — по чтению исходников тестов (test_terms_ru.py:33-51, test_gate_status_ru.py:44-58, test_notifier.py:296, test_pages_contracts.py:3972-3989,5657-5659, test_rebalance_parity.py:505-512).
- `GAS:2250-2279` в п.3 — диапазон по докстрокам функций, не одна строка.
