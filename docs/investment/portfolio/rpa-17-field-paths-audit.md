# RPA-17. Аудит путей полей snapshot v2 в документации ru-portfolio-advisor

> **Статус: отработан 19.08.2026.** Все 12 несуществующих путей исправлены,
> оба вопроса владельца получили ответ (см. «Где нужно решение владельца
> контракта» ниже), находка №5 снята как ложная. Документ сохранён как метод
> (как искать дрейф документации от схемы) и как история дефекта — не как
> открытый бэклог. Сводка закрытия — `TODO.md` → `#rpa-17`.

**Дата аудита:** 2026-08-19
**Эталоны:** живой снапшот `portfolio-2026-08-19.json` (`as_of_date`/`generated_at` = 19.08, содержит поля волн 1–2) и `skills/portfolio-data-loader/references/output-schema.md` (SSOT схемы снапшота, обновлён 19.08).
**Область:** все `.md`-файлы `skills/ru-portfolio-advisor/` (`SKILL.md`, `EXAMPLES.md`, `references/*.md`).

## Контекст и повод

19.08 обнаружены два случая одного класса дефекта:

1. `references/bonds-methodology.md` дважды велела читать `balance_summary.bonds_value_by_type_excl_iis` — ключ физически не существовал в снапшоте (добавлен только 19.08).
2. `references/rebalance-framework.md`, раздел «Входные данные» — восемь пунктов, почти все указывают на схему промежуточного `portfolio.json` (парсер v1), а не на снапшот v2, который скилл реально читает.

Этот аудит проверяет гипотезу о масштабе: точечные ошибки или системный дрейф документации advisor’а от схемы v2.

## Метод

Из всех `.md`-файлов скилла регулярным выражением извлечены все backtick-путиданных вида `a.b.c` / `a[].b` (154 сырых совпадения; после отсева имён файлов — 115). Дополнительно вручную добавлены 5 путей, которые извлекатель не мог поймать по конструкции regex (голые однословные имена вроде `errors_check`, `stocks`, `invest_era`, `tickers_with_changes`, а также сдвоенное упоминание `credit_rating`/`credit_rating_file`) — все найдены при чтении контекста `rebalance-framework.md` и `SKILL.md`, на которые нацелил сам повод аудита. Из выборки исключены 8 ложных срабатываний regex, не являющихся путями данных: доменные имена (`iss.moex.com`, `www.moex.com`), вызовы Python-функций/модулей (`yaml.safe_load`, `scipy.optimize.brentq`, `constraint_engine.compute_verification_priority`).

Каждый путь сверен против:
- множества всех реальных путей снапшота (объединение ключей по всем элементам массивов — не только по первому, иначе теряются бондо-специфичные поля вроде `plan_bucket`/`ytm_pct`, которых нет у акций);
- `output-schema.md` — для семантики и «легального» списка блоков;
- явного текста абзаца — указан ли источник (снапшот / weekly-review YAML / stress YAML / conditions.yaml / промежуточный `portfolio.json`), когда путь НЕ из снапшота.

## Сводка

**Итоговая таблица находок — 102 строки** (107 живых путей после отсева 8 ложных срабатываний regex из 115, плюс 5 вручную найденных голых имён; часть строк таблицы объединяет 2–3 пути одной фразы текста — например, `returns.total / returns.restricted / returns.by_type` в одной ячейке `returns` считается тремя путями при подсчёте классов ниже).

| Класс | Количество | Что значит |
|---|---:|---|
| ✅ существует | 53 | путь читается верно |
| ⚠️ существует, но null на этом снапшоте | 6 | нельзя отличить «нет ключа» от «нет данных на этом прогоне»; из них 3 — принципиальный кейс (`per_instrument_xirr` целиком null на полном снапшоте), 3 — ожидаемая опциональность отдельных holdings-полей |
| ➖ не из снапшота (другой артефакт) | 31 | легитимно, если источник назван явно; из них 28 — названы явно, 1 — образцово (файл сам себя корректирует), 1 — нечётко промаркирован, 1 — прямой конфликт с SKILL.md Inputs |
| ❌ не существует | 12 | путь придуман/устарел, верного эквивалента либо нет, либо он под другим именем |

**Затронутые файлы (по числу ❌ / ➖-проблем):**

| Файл | ❌ не существует | ➖ проблемные (нечётко/конфликт) | ⚠️ null | Комментарий |
|---|---:|---:|---:|---|
| `references/rebalance-framework.md` | 8 | 0 | 0 | Худший файл — все 8 пунктов раздела «Входные данные» стоят на схеме v1/`portfolio.json`; см. подтверждённую гипотезу задачи |
| `SKILL.md` | 1 | 0 | 5 | 2 независимых дефекта на фоне в целом качественной документации |
| `references/analysis-process.md` | 1 | 0 | 1 | дубль одного из дефектов rebalance-framework.md (`goals.matrix`) |
| `references/output-templates.md` | 1 | 1 | 0 | 1 устаревшее поле в шаблоне Mode 8 + 1 конфликт со scope stress-файла |
| `references/bonds-methodology.md` | 1 | 0 | 0 | минорная неточность в паре `credit_rating`/`credit_rating_file` |
| `references/fanout-news.md` | 0 | 1 | 0 | один путь без явного префикса источника |

## Главные находки

1. **`references/rebalance-framework.md`, раздел «Входные данные» (строки 65–72) — подтверждено: все 8 пунктов битые.** Список целиком описывает промежуточный `portfolio.json` (парсер v1: `metrics.*`, `goals.*`, `errors_check`, `stocks`, `invest_era`), которого advisor не читает — он читает снапшот v2. У 5 из 8 пунктов есть точный современный эквивалент (см. таблицу), у одного («errors_check») эквивалента нет вообще.
2. **Та же ошибка (`goals.matrix`) продублирована в `references/analysis-process.md:62`** — значит, это не опечатка в одном месте, а стабильно неверное представление модели о схеме, разошедшееся по двум файлам.
3. **`references/output-templates.md:811`** (шаблон Mode 8, Stock Quality Forward Review) требует таблицу «по ВСЕМ тикерам из `metrics.active_stock_tickers`» — поля из parser v1. При этом `references/stocks-methodology.md:21` **в этом же скилле** явно документирует, что это поле удалено в v2 — то есть корректная информация в скилле есть, но не долетела до шаблона вывода.
4. **`SKILL.md:132`** — таблица «Ключевые блоки snapshot v2» (в остальном образцовая и точная) называет несуществующий `ie_summary.tickers_with_changes`; реальное поле — `ie_summary.ie_changes_count` (счётчик, не список).
5. ~~**`per_instrument_xirr` — null на всём живом снапшоте**~~ — **ЛОЖНАЯ НАХОДКА, снята при приёмке 19.08.** Тестовый снапшот, выданный аудитору, собирался без шага `per_security_xirr.py` (я его пропустил при ручной сборке), поэтому поле и оказалось `null`. В боевых снапшотах библиотеки оно заполнено: `portfolio-2026-08-06.json` — 85 записей, `-08-10` — 84, `-08-15` — 84. Дефекта нет, правок не требуется. Урок для будущих аудитов: `null` в тестовой фикстуре ≠ `null` в проде — сверять с `Claude-Memory/Portfolio/snapshots/`.
6. **`references/output-templates.md:420`** тянет `by_horizon.h24` (поле stress-YAML) в шаблон Mode 3 (Rebalance Opinion), а `SKILL.md` Inputs заявляет, что stress-файл читается «только Mode 8». Это либо недокументированная зависимость Mode 3 от stress-файла, либо устаревшая копипаста — нужно решение владельца.

## Полная таблица находок

Сортировка: по файлу (в порядке ухудшения — сначала файлы с найденными ❌/➖-проблемами), внутри файла — по номеру строки. Столбец «Путь как написан» — дословно из документа.

| Файл | Строка | Путь как написан | Класс | Комментарий / верный путь |
|---|---:|---|---|---|
| `references/rebalance-framework.md` | 65 | `metrics.stocks_with_action_notes` | ❌ не существует | Не существует в snapshot v2. Данные о пометках План/Статус/IE/AI по факту лежат в `ie_actual.per_ticker.{user_plan,user_status,user_note_ie,user_note_ai}` — но это не готовый «список позиций с пометками», а разрозненные поля на каждом тикере; абзац нуждается в переформулировке, а не просто в замене имени пути |
| `references/rebalance-framework.md` | 66 | `errors_check` | ❌ не существует | Не существует в snapshot v2 и не имеет прямого эквивалента. Ближайшее по смыслу: `data_quality_flags[]` (severity error/warn/info) и `cash_reconciliation` (дрейф кэша) — но семантика другая (это не сверка с IntelInvest). Нужно решение владельца: убрать пункт или переопределить его через эти два блока |
| `references/rebalance-framework.md` | 67 | `goals.matrix` | ❌ не существует | См. analysis-process.md:62 — тот же несуществующий путь, дублируется в двух файлах |
| `references/rebalance-framework.md` | 68 | `balance_summary.bonds_plan_vs_fact` | ✅ существует | тело абзаца уже называет верный путь (в отличие от жирного лейбла того же пункта — см. БАГ ниже) |
| `references/rebalance-framework.md` | 68 | `goals.bonds_breakdown` | ❌ не существует | Жирный лейбл пункта называет несуществующий путь `goals.bonds_breakdown`. Тело того же пункта уже (верно) называет `balance_summary.bonds_plan_vs_fact` как готовый источник (и `balance_summary.goals_bonds_breakdown` как legacy-путь для старых снапшотов) — механическая правка: заменить лейбл на `balance_summary.bonds_plan_vs_fact` |
| `references/rebalance-framework.md` | 69 | `stocks` | ❌ не существует | Не существует как топ-уровневый блок в snapshot v2. Верный путь по методике stocks-methodology.md: `holdings[]` where `asset_type=="stock"` + `ie_actual.per_ticker` (IE New/Old/Real/Planned/План/Статус живут в `ie_actual.per_ticker.*`, не в отдельном `stocks`) |
| `references/rebalance-framework.md` | 70 | `invest_era` | ❌ не существует | Не существует как топ-уровневый блок. Верный путь: `ie_model.positions[]` — поля `name`/`target_share_pct`/`entry_price_rub`/`growth_potential_12m_pct`(`_lt_pct`) точно соответствуют перечисленным в тексте «Название»/«Доля»/«Точка входа»/«Потенциал роста» |
| `references/rebalance-framework.md` | 71 | `metrics.bonds_value_by_type` | ❌ не существует | Не существует. Верный путь: `balance_summary.bonds_value_by_type_excl_iis` (основные счета) или `_iis_only` (ИИС-3) — именно эти поля дают суммы по USD/EUR/CNY/ОФЗ/КОРП, как и описано в тексте |
| `references/rebalance-framework.md` | 72 | `metrics.ie_not_in_active` | ❌ не существует | Не существует. Верный путь: `ie_summary.list_in_ie_not_in_portfolio` — семантика совпадает дословно («тикеры из IE, которых нет в портфеле»), это уже используется под верным именем в 4 других файлах (EXAMPLES.md, SKILL.md, fanout-news.md, stocks-methodology.md) |
| `references/output-templates.md` | 259 | `holdings[].plan_bucket_key` | ✅ существует | — |
| `references/output-templates.md` | 300 | `balance_summary.bonds_plan_vs_fact` | ✅ существует | — |
| `references/output-templates.md` | 322 | `balance_summary.bonds_plan_vs_fact_iis` | ✅ существует | — |
| `references/output-templates.md` | 420 | `by_horizon.h24` | ➖ не из снапшота (⚑ конфликт) | встречается в «Шаблон 3. Rebalance Opinion» (Mode 3), но SKILL.md Inputs заявляет stress-yaml «опц., только Mode 8». Либо Mode 3 тоже читает stress-файл (тогда это нужно явно прописать в Inputs SKILL.md), либо секция — устаревшая копипаста из Mode 8. Решение владельца контракта |
| `references/output-templates.md` | 811 | `metrics.active_stock_tickers` | ❌ не существует | Поле из parser v1, в snapshot v2 блока `metrics` нет (см. собственное признание stocks-methodology.md:21). В шаблоне Mode 8 это НЕ помечено как legacy. Верный реестр (по методике stocks-methodology.md Шаг 1 / SKILL.md:206): `holdings[]` where `asset_type=="stock"` and `status!="blocked"` + `ie_actual.per_ticker` где `planned_share_pct>0` + `ie_summary.list_in_ie_not_in_portfolio` |
| `references/output-templates.md` | 1052 | `expires.type` | ➖ не из снапшота | user_constraints (weekly-review/conditions); секция про constraint-schema, источник ясен из соседних правил closed_reason/carry-over |
| `references/output-templates.md` | 1055 | `expires.value` | ➖ не из снапшота | см. выше |
| `references/output-templates.md` | 1056 | `expires.value` | ➖ не из снапшота | см. выше |
| `references/output-templates.md` | 1057 | `expires.value` | ➖ не из снапшота | см. выше |
| `SKILL.md` | 29 | `catalyst[]` | ➖ не из снапшота | weekly-review-stock YAML (schema weekly-stocks-review); явно назван «stock YAML» рядом |
| `SKILL.md` | 55 | `balance_summary.total_current_rub_excl_iis` | ✅ существует | — |
| `SKILL.md` | 56 | `balance_summary.bonds_value_by_type_excl_iis` | ✅ существует | — |
| `SKILL.md` | 61 | `ie_actual.per_ticker` | ✅ существует | — |
| `SKILL.md` | 129 | `holdings[]` | ✅ существует | ссылка на массив целиком — корректно |
| `SKILL.md` | 130 | `ie_model.positions[]` | ✅ существует | ссылка на массив целиком — корректно |
| `SKILL.md` | 131 | `ie_actual.per_ticker` | ✅ существует | — |
| `SKILL.md` | 132 | `ie_summary.list_in_ie_not_in_portfolio / list_in_portfolio_not_in_ie` | ✅ существует | две части OK, см. отдельно tickers_with_changes ниже — БАГ |
| `SKILL.md` | 132 | `ie_summary.tickers_with_changes` | ❌ не существует | Не существует в snapshot v2. Реальное поле — `ie_summary.ie_changes_count` (число изменений, не список тикеров). Прямого списочного эквивалента нет; ближайшее — пересечь `ie_summary.tickers_in_both` с построчным сравнением `ie_new_pct`/`ie_old_pct` в `ie_actual.per_ticker`, либо просто заменить на `ie_changes_count` с изменением смысла предложения (счётчик, не список) |
| `SKILL.md` | 134 | `returns.total / returns.restricted / returns.by_type` | ✅ существует | — |
| `SKILL.md` | 137 | `data_quality_flags[]` | ✅ существует | ссылка на массив целиком — корректно |
| `SKILL.md` | 140 | `balance_summary.bonds_value_by_type_excl_iis` | ✅ существует | — |
| `SKILL.md` | 141 | `returns.restricted.xirr / returns.by_type` | ✅ существует | — |
| `SKILL.md` | 170 | `holdings[].current_price` | ⚠️ null на этом снапшоте | поле существует; null у 38/120 позиций (blocked/cost_basis + TPAY/TMON) — для ISS-fallback baseline это не критично, но текст не оговаривает это исключение |
| `SKILL.md` | 192 | `snapshot.returns` | ✅ существует | — |
| `SKILL.md` | 192 | `snapshot.per_instrument_xirr` | ⚠️ null на этом снапшоте | поле есть в схеме (output-schema.md), но на живом снапшоте — null целиком, хотя снапшот полный (не returns_only). Похоже, при сборке этого снапшота не был передан `--per-security` (выход per_security_xirr.py) в assemble_snapshot.py. SKILL.md не предупреждает об этой зависимости пайплайна |
| `SKILL.md` | 203 | `snapshot.returns.by_type` | ✅ существует | — |
| `SKILL.md` | 206 | `snapshot.per_instrument_xirr` | ⚠️ null на этом снапшоте | см. выше — null на этом снапшоте |
| `SKILL.md` | 232 | `by_horizon.h12 / h24` | ➖ не из снапшота | stress-*.yaml; явно назван `Portfolio/stress/stress-<latest>.yaml` в том же абзаце |
| `SKILL.md` | 363 | `by_horizon.h12 / h24` | ➖ не из снапшота | stress-*.yaml; явно назван «stress-файл» в том же абзаце (дубль формулировки из EXAMPLES.md) |
| `SKILL.md` | 366 | `on_trigger.verdict` | ➖ не из снапшота | conditions.yaml / Mode 9; контекст — чеклист Workflow M с явным упоминанием conditions.yaml строкой выше |
| `SKILL.md` | 461 | `user_constraints[].active` | ➖ не из снапшота | weekly-review per_stock; контекст явно про carry-over из прошлого обзора |
| `SKILL.md` | 486 | `returns.by_type` | ✅ существует | — |
| `SKILL.md` | 506 | `returns.total.xirr / returns.restricted / returns.by_type` | ✅ существует | — |
| `SKILL.md` | 512 | `ie_summary.list_in_ie_not_in_portfolio` | ✅ существует | — |
| `SKILL.md` | 536 | `holdings[].current_price` | ⚠️ null на этом снапшоте | см. SKILL.md:170 — null у части позиций, тот же нюанс |
| `SKILL.md` | 538 | `holdings[].nominal_currency` | ⚠️ null на этом снапшоте | null для всех не-бондовых позиций — это ожидаемо (замещайки — только бонды), текст сам подразумевает условность; дефект не в этом |
| `SKILL.md` | 538 | `holdings[].value_rub` | ✅ существует | — |
| `references/analysis-process.md` | 12 | `snapshot.returns / returns.by_type` | ✅ существует | — |
| `references/analysis-process.md` | 14 | `snapshot.per_instrument_xirr` | ⚠️ null на этом снапшоте | см. SKILL.md:192 — null на этом снапшоте |
| `references/analysis-process.md` | 24 | `ie_actual.per_ticker` | ✅ существует | — |
| `references/analysis-process.md` | 51 | `balance_summary.total_current_rub_excl_iis` | ✅ существует | — |
| `references/analysis-process.md` | 62 | `goals.matrix` | ❌ не существует | Не существует в snapshot v2 (нет блока `goals`, нет валютно-типовой матрицы уровня NAV вообще — только бондовые срезы `balance_summary.bonds_value_by_type[_excl_iis]`/`by_subtype`). Прямого 1:1 эквивалента нет: L1-доли классов актива нужно считать вручную группировкой `holdings[]` по `asset_type`/`currency` от базы `balance_summary.total_current_rub_excl_iis`. Дубль той же ошибки — rebalance-framework.md:67 |
| `references/analysis-process.md` | 92 | `balance_summary.total_current_rub_excl_iis / balance_summary.bonds_value_by_type_excl_iis / ie_actual.per_ticker` | ✅ существует | — |
| `references/analysis-process.md` | 137 | `user_constraints[].active` | ➖ не из снапшота | weekly-review; блок Part A явно про reconcile_constraints.py и per_stock/per_bond |
| `references/analysis-process.md` | 139 | `per_stock.price_rub` | ➖ не из снапшота | weekly-review per_stock, тот же блок Part A |
| `references/analysis-process.md` | 148 | `user_constraints[]` | ➖ не из снапшота | weekly-review, Part B conditions.yaml контекст явный |
| `references/analysis-process.md` | 164 | `on_trigger.verdict` | ➖ не из снапшота | conditions.yaml; контекст — verification_priority derived из активного условия |
| `references/analysis-process.md` | 196 | `user_constraints[]` | ➖ не из снапшота | weekly-review, копирование constraint_payload — контекст явный |
| `references/analysis-process.md` | 306 | `snapshot.holdings` | ✅ существует | — |
| `references/bonds-methodology.md` | 3 | `holdings[].plan_bucket_key` | ✅ существует | — |
| `references/bonds-methodology.md` | 5 | `holdings[]` | ✅ существует | — |
| `references/bonds-methodology.md` | 13 | `holdings[]` | ✅ существует | — |
| `references/bonds-methodology.md` | 13 | `credit_rating` (вторая часть пары `credit_rating_file`/`credit_rating`) | ❌ не существует | В holdings[] существует только `credit_rating_file` — отдельного поля `credit_rating` нет. Механическая правка: убрать «/credit_rating» в обоих местах (строки 13 и 36) |
| `references/bonds-methodology.md` | 15 | `balance_summary.bonds_value_by_subtype_excl_iis` | ✅ существует | — |
| `references/bonds-methodology.md` | 38 | `holdings[] / balance_summary.goals_bonds_breakdown` | ✅ существует | goals_bonds_breakdown — легитимный legacy-путь для старых снапшотов, назван явно как legacy |
| `references/bonds-methodology.md` | 83 | `balance_summary.bonds_plan_vs_fact / bonds_plan_vs_fact_iis` | ✅ существует | — |
| `references/bonds-methodology.md` | 85 | `balance_summary.goals_bonds_breakdown / bonds_value_by_type_excl_iis` | ✅ существует | legacy-путь помечен явно |
| `references/bonds-methodology.md` | 88 | `balance_summary.bonds_plan_vs_fact` | ✅ существует | — |
| `references/bonds-methodology.md` | 125 | `per_bond.ytm_pct` | ➖ не из снапшота | явно сказано «в weekly-review» в начале того же предложения |
| `references/bonds-methodology.md` | 151 | `balance_summary.bonds_plan_vs_fact` | ✅ существует | — |
| `references/fanout-news.md` | 31 | `ie_summary.list_in_ie_not_in_portfolio` | ✅ существует | — |
| `references/fanout-news.md` | 65 | `snapshot.holdings[].name` | ✅ существует | — |
| `references/fanout-news.md` | 65 | `per_bond[].issuer` | ➖ не из снапшота (нечётко) | цепочка «предыдущий weekly-review → `snapshot.holdings[].name` → для облигаций `per_bond[].issuer`» — третий член цепочки идёт сразу после пути с явным префиксом `snapshot.`, но сам этот префикс не несёт; вероятно это поле weekly-review-bond (per_bond), не снапшота — стоит явно проставить источник |
| `references/mode-9-conditions.md` | 30 | `while_pending.verdict` | ➖ не из снапшота | весь файл — про conditions.yaml (заголовок + первый абзац) |
| `references/mode-9-conditions.md` | 32 | `on_trigger.verdict` | ➖ не из снапшота | весь файл — про conditions.yaml |
| `references/mode-9-conditions.md` | 33 | `while_pending.verdict / on_trigger.verdict` | ➖ не из снапшота | весь файл — про conditions.yaml |
| `references/weekly-review-schema-v1.md` | 5 | `catalyst[].in_horizon` | ➖ не из снапшота | весь файл v1 SUPERSEDED; строка документирует УДАЛЕНИЕ поля в v2, это не инструкция читать его |
| `references/weekly-review-schema-v1.md` | 408 | `constraint_engine.compute_verification_priority` | ➖ не из снапшота | вызов Python-функции, а не путь данных; контекст ясен |
| `references/weekly-review-schema-v1.md` | 519 | `ie_summary.list_in_ie_not_in_portfolio` | ✅ существует | — |
| `references/weekly-review-schema-v1.md` | 539 | `summary.positions_reviewed` | ➖ не из снапшота | самоссылка v1-схемы на собственное поле — корректно |
| `references/save-flow.md` | 118 | `weighted_ytm_pct.value` | ➖ не из снапшота | выходной YAML weekly-review-bond, считается Python-стабом assemble_artifact.py — контекст явный («Bond summary-агрегаты») |
| `references/save-flow.md` | 125 | `weighted_ytm_pct.basis` | ➖ не из снапшота | см. выше, тот же YAML |
| `references/save-flow.md` | 155 | `snapshot.as_of_date` | ✅ существует | — |
| `EXAMPLES.md` | 45 | `ie_summary.list_in_ie_not_in_portfolio` | ✅ существует | — |
| `EXAMPLES.md` | 91 | `balance_summary.bonds_plan_vs_fact` | ✅ существует | — |
| `EXAMPLES.md` | 117 | `ie_actual.per_ticker` | ✅ существует | — |
| `EXAMPLES.md` | 122 | `balance_summary.bonds_plan_vs_fact` | ✅ существует | — |
| `EXAMPLES.md` | 294 | `returns.by_type` | ✅ существует | — |
| `EXAMPLES.md` | 324 | `returns.restricted` | ✅ существует | — |
| `EXAMPLES.md` | 363 | `by_horizon.h12 / h24` | ➖ не из снапшота | stress-*.yaml (portfolio-scenario-stress); явно назван «stress-файл» рядом |
| `references/catalyst-tree-rules.md` | 354 | `user_constraints[]` | ➖ не из снапшота | carry-over enforcement — контекст про weekly-review явный (заголовок раздела) |
| `references/mode-8-stress.md` (с 20.08.2026 — `references/stress-reading.md`, RPA-20) | 14 | `by_horizon.h12 / h24` | ➖ не из снапшота | весь файл — про чтение stress-*.yaml, источник назван в шаге 3.8 абзацем выше |
| `references/startup-checklist.md` | 28 | `snapshot.as_of_date` | ✅ существует | — |
| `references/startup-checklist.md` | 39 | `snapshot.holdings[].name` | ✅ существует | — |
| `references/startup-checklist.md` | 40 | `dividend_forward.policy_state` | ➖ не из снапшота | явно «из предыдущего обзора берётся» абзацем выше |
| `references/stocks-methodology.md` | 12 | `holdings[]` | ✅ существует | — |
| `references/stocks-methodology.md` | 14 | `ie_actual.per_ticker` | ✅ существует | — |
| `references/stocks-methodology.md` | 16 | `ie_summary.list_in_ie_not_in_portfolio` | ✅ существует | — |
| `references/stocks-methodology.md` | 18 | `ie_actual.per_ticker` | ✅ существует | — |
| `references/stocks-methodology.md` | 21 | `metrics.active_stock_tickers (и соседи)` | ➖ не из снапшота (образцово) | ОБРАЗЦОВО: сам файл явно помечает поле как исторический parser v1, «в snapshot v2 блока metrics нет» — контраст с rebalance-framework.md и output-templates.md, где то же поле используется БЕЗ такой пометки |
| `references/stocks-methodology.md` | 196 | `snapshot.ie_actual.per_ticker` | ✅ существует | — |
| `references/stocks-methodology.md` | 199 | `ie_summary.list_in_portfolio_not_in_ie` | ✅ существует | — |
| `references/trust-hierarchy.md` | 193 | `validation.trust_coverage.untagged` | ➖ не из снапшота | помечено «у потребителя» — не снапшот, а валидатор downstream-потребителя |

## Что править и в каком порядке

### 1. Механическое переименование пути (низкий риск, можно делать батчем)

| Файл:строка | Было | Стало |
|---|---|---|
| `references/rebalance-framework.md:68` | `**goals.bonds_breakdown**` (жирный лейбл) | `**balance_summary.bonds_plan_vs_fact**` — тело абзаца уже называет верный путь, меняется только лейбл |
| `references/rebalance-framework.md:70` | `invest_era` | `ie_model.positions[]` |
| `references/rebalance-framework.md:71` | `metrics.bonds_value_by_type` | `balance_summary.bonds_value_by_type_excl_iis` (+ `_iis_only` для ИИС-3) |
| `references/rebalance-framework.md:72` | `metrics.ie_not_in_active` | `ie_summary.list_in_ie_not_in_portfolio` |
| `references/rebalance-framework.md:69` | `stocks` | `holdings[]` where `asset_type == "stock"` (+ `ie_actual.per_ticker` для IE-полей) |
| `references/bonds-methodology.md:13,36` | `credit_rating_file`/`credit_rating` | `credit_rating_file` (убрать несуществующее второе поле) |
| `references/fanout-news.md:65` | `per_bond[].issuer` без префикса | явно указать артефакт-источник (weekly-review-bond) |

### 2. Нужен пересмотр смысла абзаца (нет 1:1 замены, требуется решение)

- **`references/rebalance-framework.md:65`** (`metrics.stocks_with_action_notes`) — готового списка «позиций с пометками» в снапшоте v2 нет, есть только россыпь полей `ie_actual.per_ticker.{user_plan,user_status,user_note_ie,user_note_ai}` по каждому тикеру. Абзац нужно переписать как «пройтись по `ie_actual.per_ticker` и отобрать тикеры с непустыми user_*».
- **`references/rebalance-framework.md:66`** (`errors_check`) — эквивалента нет вообще. Решить: убрать пункт или переопределить через `data_quality_flags[]` + `cash_reconciliation` с оговоркой, что семантика не идентична (не сверка с IntelInvest, а собственные data-quality проверки data-loader’а).
- **`references/rebalance-framework.md:67` и `references/analysis-process.md:62`** (`goals.matrix`, дубль в двух файлах) — валютно-типовой матрицы уровня NAV в снапшоте v2 нет вообще (только бондовые срезы). Нужно явно прописать, что L1-матрица считается вручную группировкой `holdings[]` по `asset_type`/`currency`, база — `balance_summary.total_current_rub_excl_iis`.
- **`references/output-templates.md:811`** (`metrics.active_stock_tickers`) — заменить на реестр из `stocks-methodology.md` Шаг 1 (см. таблицу выше), синхронизировав формулировку с уже верной версией в SKILL.md:206.
- **`SKILL.md:132`** (`ie_summary.tickers_with_changes`) — решить, менять ли на `ie_changes_count` (счётчик — другая семантика) или на производный список (`tickers_in_both` + сравнение `ie_new_pct`/`ie_old_pct`).
- **`references/output-templates.md:420` vs `SKILL.md` Inputs** (`by_horizon.h24` в шаблоне Mode 3) — нужно решение владельца: расширять ли официальный scope stress-файла на Mode 3, или вычищать секцию как устаревшую.
- **`SKILL.md:192/206`, `references/analysis-process.md:14`** (`per_instrument_xirr` null на полном снапшоте) — добавить в SKILL.md/Inputs явную оговорку про зависимость от `per_security_xirr.py`-шага пайплайна и что делать advisor’у, если поле пришло null.

### 3. Достаточно уточнить источник артефакта (путь верный, но не хватает явного лейбла)

- `references/fanout-news.md:65` — `per_bond[].issuer` идёт в перечислении сразу после пути с префиксом `snapshot.`, из-за чего неочевидно, что сам он НЕ из снапшота. Добавить префикс/пояснение.

## Где нужно решение владельца контракта (не уверен)

1. ~~**`references/output-templates.md:420`**~~ — **ОТВЕТ ПОЛУЧЕН 19.08:** «режим 3 требует стресса для работы с ребалансировкой». Актуален шаблон, а не Inputs; `SKILL.md` расширен до «опц., **Mode 3 и Mode 8**».
2. ~~**`per_instrument_xirr` = null на живом снапшоте**~~ — **проверено, не воспроизводится:** специфика тестовой фикстуры (см. находку №5). В `SKILL.md` всё же добавлена оговорка «что делать, если поле пришло null» — зависимость от шага `per_security_xirr.py` реальна, просто в тот раз её нарушил сборщик фикстуры, а не пайплайн.
3. ~~**`references/rebalance-framework.md:66` (`errors_check`)**~~ — **ЗАКРЫТО ИНАЧЕ, чем предполагал аудит.** Вместо переформулировки пункта поле доведено до снапшота: `parse_portfolio.py` таблицу «Проверка» и так парсил, но в снапшот её не переносил (PDL-13). Теперь путь `balance_summary.errors_check` существует, и пункт указывает на него без потери смысла. Мораль: «эквивалента нет» иногда означает «сборка снапшота теряет то, что парсер уже добыл», — проверять надо не только схему снапшота, но и промежуточный артефакт.
4. **Полнота метода.** Аудит целенаправленно искал dotted/bracket-пути в backtick’ах (как задано в задаче) плюс точечно проверил голые слова, упомянутые в самой задаче или найденные в структурированных таблицах (строка вида `` `Блок` | `под-поле-1`, `под-поле-2` ``). Голые однословные идентификаторы вне такого контекста (их в файлах скилла ~500+, в основном — легитимные поля weekly-review/conditions YAML, вроде `advisor_verdict`, `catalyst`, `gate_review_directive`) не проверялись поштучно против снапшота — экономически нецелесообразно при заданном объёме; если нужен исчерпывающий разбор и этого пласта, это отдельная задача.

