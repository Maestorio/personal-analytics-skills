# Сверка выписки банка на сайте — устройство (этап «Деньги» плана «меньше ИИ», задача 3.8)

Блок «Выписка банка (CSV, XLSX)» на вкладке «Загрузка» страницы «Деньги» (`tools/money.html`; отдельная вкладка была в v2.5.0,
с v2.6.0 — вторым блоком под «Выгрузкой ZenMoney (CSV)», адрес вкладки `csv` прежний): выбрать выписку → «Проверить выписку» →
отчёт `zm-stmt-report@1`. **Сайт разбирает только Райффайзенбанк (CSV) и Bank of Georgia (XLSX); PDF не разбирается** (решение
владельца 2026-11-10) — выписки FF и Т-Банка в PDF по-прежнему разбирает скилл на Маке (режимы E/F). Без ZenMoney и без Claude, **только чтение**: в ZenMoney, `ZenMoney/audit/`, карту и словари
(`places-add`, `map_edit`) ничего не пишется. Работает одинаково при `ai_mode: on` и `off`; подсказка «/zenmoney-analyst
внеси операции из выписки» (импорт в ZenMoney — режимы E/F скилла) прячется при `off`. Устроено как выгрузка CSV (`csv-site.md`).

## Поток

```
money.html «Загрузка → Выписка банка» ──POST /api/zm/stmt (файл, base64)──▶ hub-api: ZenMoney/csv/stmt-incoming/<id>.<xlsx|csv>
        └──POST /api/zm/stmt-report {id}──▶ hub-api ──▶ hub-notify /internal/zm-stmt-report (zm_stmt.py)
                 ◀── отчёт zm-stmt-report@1 в ответе (на диск не пишется) ◀──┘
                 после ответа hub-api стирает файл (при любом исходе)
```

- **Одна реализация.** `zm_stmt.py` не разбирает ничего сам: банк узнаёт `stmt_import.detect_bank`, разбирает `parse_<банк>_statement.py`,
  флаги даёт `<банк>_normalize.py`, счёт ZenMoney подбирает `stmt_accounts.resolve`, сравнение — `stmt_compare.compare`. Копии
  7 скриптов скилла (`stmt_import`, `stmt_compare`, `stmt_accounts`, парсеры и нормализаторы Райффайзена и BOG) `deploy.zsh` кладёт в `notify/pdl/skills/zenmoney-analyst/scripts/` (в репозитории модуль берёт их на своих местах).
- **Банки и форматы** (`zm_stmt.SITE_BANKS`): Райффайзенбанк — CSV; Bank of Georgia — XLSX. Банк узнаётся по содержимому; неизвестный
  (в том числе файл, похожий на выписку FF или Т-Банка) → 422 «банк не узнан… Сейчас умею: Райффайзенбанк (CSV), Bank of Georgia
  (XLSX)». PDF отклоняет hub-api на входе. Один файл за раз.
  Парсеры FF и Т-Банка `deploy.zsh` на сервер не выкладывает: `stmt_import` грузит парсер банка лениво (в `BANKS[...]["loader"]`),
  цепочке CSV/XLSX они не нужны.
- **Приватность.** Только синтетика в коде и тестах. Счёт в отчёте — последние 4 знака; в журнал `job=zm-stmt` идут id, банк, числа (без текстов и сумм).

## Временная зона и сроки

| Путь | Кто | Жизнь |
|---|---|---|
| `ZenMoney/csv/stmt-incoming/<id>.<xlsx\|csv>` (id = ГГГГ-ММ-ДД-<sha256[:8]>) | hub-api | стирается сразу после ответа `stmt-report` (успех, 422, hub-notify недоступен); брошенный файл старше часа — при следующей загрузке или отчёте |

Отчёт нигде не хранится: закрыл вкладку — исчез. Зона в белый список задач (`JOB_WHITELIST`) не входит.

## Маршруты и лимиты

| Маршрут | Что |
|---|---|
| `POST /api/zm/stmt {name, b64}` | тип **по содержимому** (zip с `xl/workbook.xml`; текст UTF-8/cp1251 с шапкой и разделителем; имя не читается); **PDF (`%PDF-`) → 400 «PDF на сайте не разбирается — поддержаны CSV Райффайзенбанка и XLSX BOG»**; пустой, двоичный, zip не-xlsx → 400; тело до 11 МБ (файл ≈ 8 МБ), больше → 413 (у CSV-выгрузки лимит 16 МБ); ответ `{id, name, sha256, format, size}` |
| `POST /api/zm/stmt-report {id}` | проброс в hub-notify (таймаут 120 с), лишние поля отбрасываются; 404 файла нет, 422 банк не узнан / выписка не разобрана, 503 нет скриптов скилла в контейнере |

Зона `/api/zm/*` — пароль с любого IP (Caddy), как у CSV.

## Если возвращать PDF

Требование владельца на случай, если FF когда-нибудь вернётся на сайт (реализации нет): выписки FF обязаны приходить **парами
«текущий + депозитный счёт» по каждой валюте**, и нужна загрузка сразу 4–6 файлов по разным валютам; без пары — отказ.

## Отчёт `zm-stmt-report@1`

```json
{ "schema": "zm-stmt-report@1", "id": "2026-11-10-1a2b3c4d", "built_at": "…+03:00", "format": "xlsx|csv",
  "bank": "bog|raif", "bank_name": "…", "account": "…1234", "kind": "current|null", "currencies": ["RUB"],
  "period": {"from": "2026-10-01", "to": "2026-10-31"}, "ops_count": 120, "checks_ok": true,
  "balances": [{"currency", "opening", "sum_ops", "closing", "calc", "diff", "status": "match|mismatch|unavailable", "note"}],
  "footer": {"in", "out", "rows_in", "rows_out", "match"} | null,
  "flags": [{"kind", "title", "date", "detail"}],
  "operations": [{"date", "time", "amount": "-250.00", "currency", "text"}], "operations_truncated": false,
  "compare": {"available": true, "window", "accounts": {"RUB": "название счёта"}, "bank_ops", "zen_ops", "matched", "other": {…},
              "missing_in_zen": [{"date","amount","currency","text"}], "missing_in_zen_total", "missing_in_bank": […], "missing_in_bank_total"}
            | {"available": false, "reason": "…"} }
```

- **Сверка остатка** «входящий + сумма операций = исходящий» по валютам — у BOG. У Райффайзенбанка остатков в выписке нет:
  `status: unavailable` с причиной; `footer` у сайтовых банков всегда `null`.
- **Флаги — только то, что умеют скрипты:** проверки арифметики парсера (`check-failed`), «нулевое показание» BOG (`zero-quirk`), флаги
  нормализатора (`unknown-row`, `fee-unlinked`…), строка без читаемой даты. Дублей скрипты не ищут — их здесь нет.
- **Сравнение с ZenMoney** — по последней принятой CSV-выгрузке `ZenMoney/csv/last.csv`, за период выписки, по счетам из
  `aux/accounts.json` (`stmt_accounts.resolve`: метка банка в названии + валюта). Строки CSV приводятся к формату MCP и идут в
  `stmt_compare.compare`; списки до 200 строк (`*_total` — полное число). Нет `last.csv` / `accounts.json`, нормализатор отказал, период
  не определён, для валюты нет единственного счёта («счёт не сопоставлен… сравнение с ZenMoney недоступно») — `available: false` с причиной.
- Операции выписки — до 1500 строк (`operations_truncated`). Без оценок и советов: только факты.

## Не сделано

Несколько файлов за раз; поиск дублей в выписке; выбор счёта вручную при двух подходящих. Синтетическими проверены Райф (CSV) и BOG (XLSX);
отказ для PDF и «банков с PDF» — `test_zm_stmt.py`.
