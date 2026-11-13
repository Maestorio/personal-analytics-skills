# Coverage Report Template (Шаг 3)

Шаблон для форматирования таблицы готовности факторов. Скрипт `scripts/coverage_report.py` возвращает summary-данные; LLM форматирует таблицу ниже в соответствии с этим шаблоном (сохраняя кириллические эмодзи и выравнивание колонок).

## Структура таблицы

```
━━━ MACRO-FORECAST-CHAIN: Coverage Report ━━━
Run: {date} | Портфель: {snapshot_date} | Режим: FULL/QUICK-REFRESH/PARTIAL

Coverage Score: N/M факторов готовы

Фактор              Статус            Дата         Method  Confidence  Horizon coverage
─────────────────────────────────────────────────────────────────────────────────────────
geopolitics         ✓ FRESH           2026-04-15   manual  null *      COVERS
                                                                       * NO_CONFIDENCE caveat
sanctions           ✗ MISSING         —            —       —           —
brent               ✓ FRESH           2026-04-28   fca     0.72        COVERS
urals_discount      ⚠ STALE           2026-02-01   fca     0.55        COVERS
usdrub              ⚠ FRESH-but-short 2026-04-20   fca     0.61        INSUFFICIENT
                                                                       (max 2026-09-01,
                                                                       нужно 2027-12-31)
inflation_ru        ✗ MISSING         —            —       —           —
cbr_rate            ⚠ BROKEN          2026-04-28   fca     null **     COVERS
                                                                       ** confidence:null
                                                                       при method:fca —
                                                                       нужен rebuild
xauusd              ✗ MISSING         —            —       —           —
budget_deficit      ⚠ STALE           2026-01-15   fca     0.52        COVERS

Расхождение со спотом (summary.stale_vs_spot):
  • brent: центр 90 (2026-12-31) против спота 106.46 (2026-11-02), 15.46 % > 15 %

Резюме проблем (severity: critical):
  • cbr_rate: BROKEN_RECORD — fca-прогноз без confidence, нужен rebuild
  • 4 фактора MISSING — sanctions, inflation_ru, xauusd, ...

Допустим для стресс-теста: НЕТ (1 Broken, 4 Missing, 2 Stale, 1 Insufficient horizon)
```

## Колонки

- **Фактор** — имя фактора (DAG order)
- **Статус** — `✓ FRESH` | `⚠ STALE` | `⚠ FRESH-but-short` | `⚠ BROKEN` | `✗ MISSING`
- **Дата** — дата прогноза или `—` если MISSING/BROKEN
- **Method** — `manual` | `fca` | `—`
- **Confidence** — число 0.XX или `null` с пометкой caveat
- **Horizon coverage** — `COVERS` | `INSUFFICIENT` (с объяснением) | `—`

## Расхождение со спотом

Блок перечисляет факторы из `summary.stale_vs_spot` по `spot_check` строки: центр с горизонтом, спот с датой,
расхождение и порог. Такой фактор в таблице — `⚠ STALE` даже при свежей дате. Пометку «спот от <дата>»
(снимок старше 10 дней) и центр не из `l1_weighted` (`center_field`) показывать рядом. Блок выводится и в
QUICK-REFRESH; пустой список — блок не выводится.

## Правила сортировки

Идти по порядку DAG (от Level 0 к Level N). Это помогает пользователю сразу видеть, где разрыв в цепочке.

## Резюме проблем

Перечислить только critical issues; non-critical omit. Пример формата: `• {фактор}: {ISSUE_TYPE} — {описание}`.

## Допустим для стресс-теста

Финальная строка: `true` если 0 critical issues; иначе `false` с перечнем проблем в скобках.
