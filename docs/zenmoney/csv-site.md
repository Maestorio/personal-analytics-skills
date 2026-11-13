# Выгрузка CSV на сайт — устройство (этап «Деньги» плана «меньше ИИ», задача 3.6)

Политика записи и проверки до записи — `csv-checks-research.md` (§2 — правила, §3 — кандидаты проверок,
§4 — бэктест на Mac). Здесь — как это устроено на сайте: файлы, маршруты, схема отчёта, что остаётся
за владельцем. Код этапа — ветка `less-ai/money`.

## Поток

```
money.html «Загрузка → Выгрузка ZenMoney» ──POST /api/zm/csv (файл, base64)──▶ hub-api: ZenMoney/csv/incoming/<id>.csv
        │                                                   │ (id = ГГГГ-ММ-ДД-<sha256[:8]>)
        ├──POST /api/zm/csv-report {id}──▶ hub-api ──▶ hub-notify /internal/zm-csv-report
        │        ◀── отчёт zm-csv-report@1 (ZenMoney/csv/reports/<id>.json) ──┘
        │   страница показывает: полнота · что изменилось между выгрузками · месяцы и поездки к записи · стопы
        └──POST /api/zm/csv-apply {id, confirm:true}──▶ hub-api ──▶ hub-notify /internal/zm-csv-apply
                 запись spending.json / trips.json (копии в .versions/, source: csv), incoming → last.csv
```

- **Писатель истории** — только hub-notify через `jobs.save` (hub-api, `base_hash`, копия в `.versions/`);
  логика записи — `audit_history.apply_spending` / `apply_trip` (копии скриптов скилла в `pdl/`, как у
  portfolio-data-loader). Скилл и страница в `audit/` сами не пишут.
- **Гейт режима:** вход — владелец (файл, явное «да»), группа Б: работает и при `ai_mode: off`.
- **Ничего не пишется без отчёта и «да»:** apply принимает только `id`, у которого есть отчёт без стопов
  и хэш выгрузки совпадает с отчётом.

## Файлы на NAS (`Claude-Memory/ZenMoney/csv/`)

| Путь | Кто пишет | Что |
|---|---|---|
| `incoming/<id>.csv` | hub-api (`/api/zm/csv`) | загруженная выгрузка; хранится до записи, потом удаляется |
| `last.csv` | hub-notify (apply) | последняя записанная выгрузка — база для diff следующей |
| `reports/<id>.json` | hub-notify (report) | отчёт `zm-csv-report@1` |
| `aux/` | владелец (копия с Mac) / рецепт Claude Code | `accounts.json`, `category-flags.json`, `trip-ids.json`, `payee-map.json`, `rates-cbr.json`, `rates-zm.json` (курсы валют, которых нет у ЦБ; без него месяцы и поездки с такими валютами — стоп) — то, что сегодня лежит в `docs/zenmoney/csv/` |

Выгрузка — личные финансы: зона `/api/zm/*` под паролем с любого IP (как `/api/hd/*`), файлы
`/ZenMoney/*` Caddy наружу не отдаёт без пароля (проверка в `deploy.zsh`). Лимит тела — 16 МБ (как импорт IE).

**Без `aux/` пересчёт месяцев невозможен** — отчёт тогда даёт только полноту и diff операций, а раздел
«к записи» помечен `unavailable: "нет вспомогательных файлов"`. Словарь мест (`payee-map.json`) обновляет
только рецепт Claude Code (нужен MCP); устаревший словарь → в отчёте предупреждение «мест без словаря: N»,
записи это не мешает (на странице окажутся тексты банка — как и в рецепте).

## Отчёт `zm-csv-report@1`

```json
{
  "schema": "zm-csv-report@1", "id": "2026-11-09-1a2b3c4d", "sha256": "…", "built_at": "2026-11-09T21:40:00+03:00",
  "rows": 37035, "first": "2020-01-03", "last": "2026-11-08",
  "completeness": { "ok": true, "stops": [], "warnings": ["последняя операция 2026-11-08 — месяц 2026-11 не закончен, к записи не идёт"],
                    "prev_rows": 36870, "months_missing": [] },
  "diff": { "prev": "last.csv" | null,
            "added": 61, "deleted": 6, "changed": 12, "lost_trip_tags": [ {"date","amount","account","payee","tag"} ],
            "by_month": { "2026-10": {"added": 55, "deleted": 2, "changed": 3}, … },
            "samples": { "deleted": [ … ≤20 ], "changed": [ … ≤20 ] } },
  "months": [ { "month": "2026-10", "action": "add|replace|same", "explained": true,
                "changes": ["expense_rub: было 370 368, CSV 121 000", …], "ops_changed_after": 3 } ],
  "trips": [ { "name": "#Грузия’26", "action": "replace", "changes": [...] } ],
  "stops": ["потерян тег поездки у 4 операций", "необъяснимое расхождение 2026-07", "неполная выгрузка: пропали месяцы, бывшие в прошлой выгрузке, — 2024-03"],
  "aux": { "ok": true, "payee_unmapped": 7, "missing": [] }
}
```

Классификация расхождения месяца — как в `zenmoney_csv_backfill.py`: «объяснимое», если у месяца есть
операции с `changedDate` позже `as_of` записи или в diff по месяцу есть добавленные/удалённые; иначе —
«необъяснимое» → стоп. Ключ операции для diff — как в `zenmoney_csv_diff.py` (время создания + счета +
суммы). Полнота: первая/последняя дата, число строк против `last.csv` (меньше на >1 % → стоп «похоже
на фильтр по датам»), месяц, бывший в прошлой выгрузке и пропавший целиком (пустой месяц сам по себе законен — июль 2015 в реальной истории), N8 (месяц с последней операцией не записывается).

## Маршруты

| Маршрут | Где | Что |
|---|---|---|
| `POST /api/zm/csv` `{name, b64}` | hub-api | проверка CSV (разделитель `;`, обязательные колонки), запись в `incoming/`, ответ `{id, rows, first, last, sha256}` |
| `POST /api/zm/csv-report` `{id}` | hub-api → hub-notify `/internal/zm-csv-report` | строит и сохраняет отчёт, возвращает его |
| `POST /api/zm/csv-apply` `{id, confirm:true}` | hub-api → hub-notify `/internal/zm-csv-apply` | запись по отчёту; ответ `{written: {months, trips}, versions: [...]}` |
| `GET /api/zm/csv-state` | hub-api | `{last: {name, sha256, written_at} | null, incoming: [ids], aux_ok}` |

Зона задач (`JOB_WHITELIST`) расширяется путями `ZenMoney/audit/spending.json`, `ZenMoney/audit/trips.json`,
`ZenMoney/audit/facts.json`, `ZenMoney/csv/last.csv`, `ZenMoney/csv/reports/<id>[-runs].json`, `ZenMoney/csv/aux/*.json`
(кэш курсов), `ZenMoney/csv/incoming/<id>.csv` — константа `ZM_WHITELIST` в `server.py`. Валидатор записи `spending.json`/`trips.json` —
`audit_history.validate_spending`/`validate_trips` (копии в `pdl/`). Caddy: `/api/zm/*` в исключениях
`@api_trusted`. `deploy.zsh`: скрипты `skills/zenmoney-analyst/scripts/{audit_month,month_stats,trip_stats,audit_history,history_query}.py`,
`tools/zenmoney_payee_map.py` и `tools/zenmoney_csv_backfill.py` (разбор CSV, `build()`) → `pdl/` с раскладкой репозитория; `zm_csv.py` — в `notify/`.

## Что остаётся за ИИ

Аудит с суждениями («Качество учёта» — 3.7 после бэктеста), словарь мест (MCP), категоризация незнакомых
мест, запись в ZenMoney. Прямой API ZenMoney — не планируется (решение 4).

## Решения владельца, нужные до выкладки

1. Перенос вспомогательных файлов `docs/zenmoney/csv/` → `Claude-Memory/ZenMoney/csv/aux/` (однократно,
   затем рецепт Claude Code пишет словарь мест туда же). Без него сайт покажет diff, но не запишет месяцы.
2. Выгрузка хранится на NAS до записи (та же чувствительность, что `spending.json`; под паролем).
3. Итог бэктеста §4 исследования — набор проверок 3.7; до него на странице только полнота, diff и стопы §2.

## Реализация бэкенда (этап 3.6, без страницы)

- Модуль `tools/hosting/notify/zm_csv.py` (`parse_csv`, `completeness`, `op_diff`, `recompute`, `build_report`, `apply_report`,
  `route_report`, `route_apply`); тест `tools/tests/test_zm_csv.py`.
- **Отчёт сверх схемы выше:** `as_of` (дата сборки; она же `as_of` записываемых месяцев), `warnings` (мест без словаря, правило
  не найдено, поездка без ID), `unavailable` (причина, почему «к записи» пусто: нет aux, нет курсов, неполная выгрузка), у месяца —
  `explained_by` (`ops` | `rules` | null); после записи — `applied_at`, `written`. Расчётные результаты (`run` месяцев и поездок)
  лежат отдельно, `reports/<id>-runs.json`, в отчёт и на страницу не идут.
- **apply** отказывает (409): нет отчёта, уже записан, есть `stops`, есть `unavailable` (писать нечего), нет `confirm: true`, sha256
  файла ≠ отчёту. Порядок записи: `spending.json` → `trips.json` → `facts.json` → `last.csv` → отчёт с `applied_at`;
  пишутся только месяцы и поездки с action add|replace. Сбой посередине оставляет отчёт без `applied_at` — повтор безопасен.
- **incoming после записи.** `jobs.save` удалять не умеет, поэтому `incoming/<id>.csv` остаётся; hub-api стирает записанные
  (в отчёте `applied_at`) выгрузки при следующей загрузке файла, `csv-state` их в `incoming` не показывает.
- **Курсы ЦБ.** Кэш `aux/rates-cbr.json` читается; недостающие дни запрашиваются у ЦБ, дополненный кэш сохраняется через `jobs.save`.
  ЦБ недоступен → стоп «нет курсов за ДАТА». Первый отчёт по полной истории без прогретого кэша идёт долго (1 с на день).
- **Размер.** Выгрузка и `last.csv` не больше 8 МБ (MAX_BYTES зоны задач) — иначе стоп до записи; тело загрузки — до 16 МБ.
- Колонки выгрузки проверяются дважды: в hub-api (копия списка `ZM_REQUIRED`, контейнер не видит notify) и в `zm_csv.parse_csv`;
  тест держит списки равными.

## Проверка на реальных данных (2026-11-10, Mac, только чтение)

Прогон `zm_csv.build_report` по выгрузкам `docs/zenmoney/source/` против живой истории `ZenMoney/audit/`:

| Прогон | Итог |
|---|---|
| последняя записанная выгрузка (`…1793565970.csv`) | 82 месяца и 24 поездки «same», стопов нет, < 1 с — сайт считает то же, что записал `zenmoney_csv_backfill.py` |
| предыдущая выгрузка того же дня против записанной поздней | стоп «выгрузка старее записанной» |

Что реальные данные поправили в коде (каждое — с тестом в `test_zm_csv.py`):

- **Пустой месяц законен.** Июль 2015 без операций давал стоп «неполная выгрузка». Стоп — только месяц, бывший
  в прошлой выгрузке и пропавший целиком; без прошлой выгрузки пустые месяцы — предупреждение.
- **История ведётся с первого записанного месяца.** Выгрузка идёт с 2011 года, история — с 2020-01: сайт предлагал
  «добавить» 99 месяцев. Более ранние месяцы не пересчитываются (`skipped_before`); расширить историю назад —
  рецепт `csv-recompute.md`.
- **Разовая без `rule-ops.json`.** Правило «ЕНП» (2026-10) завёл скилл, его операции в `aux/rule-ops.json` нет —
  месяц расходился «необъяснимо». Операция находится по записи месяца (место и сумма разовой из `spending.json`,
  ровно одно совпадение); предупреждение в отчёте.
- **Выгрузка старее записанной** — отдельный стоп по последней правке операций (`changedDate`), а не
  косвенное «необъяснимое расхождение» случайного месяца.

Сделано (вариант Б, решение владельца): тройка операции хранится в самом правиле — `one_off[].op {date, account, amount}`,
у места `one_off_merchants[].names`; пишет `audit_history.py rules --op / --merchant-name`, читают `rules_for_csv` и `zm_csv`.
`aux/rule-ops.json` необязателен: он запасной путь для правил без `op`/`names`, а поиск по записи месяца — последний.
Обязательные aux — `accounts.json`, `category-flags.json`, `trip-ids.json` (`zm_csv.AUX_REQUIRED`, `ZM_AUX` hub-api);
предупреждение «правило не найдено» — только у правила без тройки и без записи в rule-ops. Старые правила переносит
`tools/zenmoney_rules_migrate.py` (сухой прогон по умолчанию; `--write` — с копией `*.before-rules-op-<дата>`).

## Правки с сайта: «Разовая», «Новая поездка», аудит сайта (2026-11-10)

| Маршрут | Где | Что |
|---|---|---|
| `POST /api/zm/rule` `{id, month, date, account, amount, payee?, note}` | hub-api → hub-notify `/internal/zm-rule` | правило `one_off` `{id: "site-<sha1(date\|account\|amount)[:12]>", month, note, date: <сегодня>, op: {date, account, amount}}` в `ZenMoney/audit/spending-rules.json` (`audit_history.apply_rules`, `jobs.save`, копия в `.versions/`); отчёт пересчитывается и возвращается (поле `rule`). Траты — только из `months[].candidates` отчёта (403 иначе); `note` обязателен |
| `POST /api/zm/rule` `{id, remove: true, rule_id}` (или тройка) | то же | снять отметку; только id `site-…` (чужие — 403), нет такой — 409 |
| `POST /api/zm/trip` `{id, name, start, end}` | hub-api → hub-notify `/internal/zm-trip` | `aux/trip-ids.json`: `ids[name] = "site:" + name`, `dates[name] = [start, end]`; отчёт пересчитывается. Только поездка из `new_trips` (403 иначе) |

Отчёт сверх схемы: у месяца к записи — `candidates` (крупные обычные траты: `date, account, amount, rub, category, payee, comment` — те же, что `outlier_candidates` скилла, с тройкой операции из CSV; до 15) и `site_rules` (отметки сайта месяца со «Снять»); у отчёта —
`new_trips` (тег поездки без ID: `name, ops, first, last, start, end`; период — `trip_stats.report` по правилу `infer_period`, иначе первая и последняя трата с тегом) и `checks_months` (месяцы, где прогонялись проверки). Правка возможна только до записи выгрузки (после `applied_at` — 409).
Белый список зоны задач — `spending-rules.json` и `site-audit.json` (`ZM_WHITELIST`).

**Аудит сайта.** При `apply` для каждого записанного месяца из `checks_months` hub-notify сохраняет в `ZenMoney/audit/site-audit.json`
(`zenmoney-site-audit@1`: `{schema, updated, months: {"ГГГГ-ММ": {as_of, export_id, checks: [{id, cls, count, text}], stops_overridden: []}}}`)
только агрегаты: без `sample`, названий и сумм; форму держит `zm_csv.validate_site_audit`. Ошибка этого файла записи месяцев не отменяет (в ответе `site_audit.error`).
Страница `money.html` (с v2.4.0; номер — `VERSION` в файле): «Качество учёта» показывает аудит скилла (`history.json`), а при его отсутствии — аудит сайта с пометкой «аудит сайта»;
«месяц закрыт не полностью» не горит у месяца с итогами и аудитом сайта (закрыт «по сайту»); так же `hub.html`. Аудит скилла полнее и при появлении заменяет сайтовый.

**Два «камня».**
1. Скилл считает месяц через MCP и ищет правило по ID операции MCP — правила сайта (ID у них нет) он не находил. Теперь `month_stats.resolve_rule_ops`
   (её зовут `load_rules` скилла и CSV-путь) сопоставляет правило с `op` по тройке: дата, название счёта (`refs.accounts`), сумма ±0,01, ровно одна операция.
2. Когда скилл посчитает «сайтовую» поездку через MCP, у неё настоящий ID тега — в `trips.json` возник бы дубль. `audit_history.apply_trip`: запись с тем же `trip.name`
   и id `site:…` заменяется пришедшей записью с настоящим id; запись сайта при уже настоящей обновляет её числа, id остаётся настоящим.

## Проверки «на что взглянуть» в отчёте (3.7, 2026-11-10)

`zm_checks.run_checks` вызывается из `zm_csv.recompute` для месяцев к записи (не больше `CHECK_MONTHS` последних); результат —
`report.checks: [{id, cls, month, text, count, sample}]`, страница показывает блок «На что взглянуть до записи». **Стопов среди
проверок нет**: по бэктесту на 15 выгрузках ни одна не набрала 80 % подтверждений (таблица — `csv-checks-research.md` §4а);
это подсказки, записи они не мешают. Выключены как шум (`CHECKS_OFF`: A5, N1, N5, P2, B7, B6' — 0 подтверждений, у A5 38 «это
норма» в реестре аудита); код остаётся, вернуть — после нового бэктеста. Сбой модуля проверок отчёт и запись не роняет.

Репетиция на реальных данных (копия истории без 2026-10, правила после миграции `op`, без `rule-ops.json`): октябрь «новый»,
итоги совпали с записанными скиллом до рубля, 81 месяц без изменений, стопов нет, 8 подсказок по октябрю (D13, N2, P1, P3).
Без миграции правил та же репетиция расходится на разовую трату — поэтому миграция `zenmoney_rules_migrate.py --write`
обязательна до первого закрытия месяца с сайта. Поездки и месяцы до начала истории не пересчитываются и не дают предупреждений.

## Не сделано

Сверка выписки банка на сайте (3.8) сделана отдельно — `stmt-site.md`; с money v2.6.0 она вторым блоком на той же вкладке «Загрузка» (ключ вкладки `csv`; блоки независимы: у каждого свой слот, кнопка, сообщение и результат; набранное в «что это» и датах поездки переживает перерисовку). Импорт выписки в ZenMoney по-прежнему за скиллом (режимы E/F, `statement-import.md`).
