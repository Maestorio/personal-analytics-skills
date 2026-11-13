# Skill: revise-memory-remote

## Summary
`validate_library.py` — 51/45→51 тестов зелёные, 27 категорий issues, валидация трёх слоёв (audits, forecasts, scenarios) с проверкой парности, обязательных полей, sum probability, broken refs (`superseded_by`, `audit_file`), date-триггеров.

**Статус ревью:** закрыто 2026-05-10. Один реальный баг исправлен; два косметических улучшения вынесены в TODO.

## Correctness (P1)
- ~~[bug] `validate_library.py` для обязательных полей (REQUIRED_AUDIT_FIELDS, REQUIRED_FORECAST_FIELDS, REQUIRED_SCENARIO_MATRIX_FIELDS) проверяет наличие ключа, но не non-null значение. Тест `test_validate_library.py:70` использует `trust: {}` — пустой dict; `trust: null` или `source: null` пройдут без issue.~~
  - **✅ Исправлено 2026-05-10.** `f not in frontmatter` → `frontmatter.get(f) is None` в трёх местах скрипта. Добавлено 6 тестов на null-значения (слои 1/2/3). Итого: 51/51.
- [coverage-gap] `Claude-Memory/audits/` пуст; реальные аудиты лежат в `domains/<dom>/<source>-*.md`. Layer 1 (audits) `validate_library.py` логически корректен, но никогда не запускался на живых данных. INDEX-проверка для `audits/INDEX.md` тоже не верифицирована.
  - **→ [RMR-1](../../TODO.md#rmr-1)**: зафиксировать в SKILL.md/layout-doc, что `audits/` пуст и как подавать payload при аудитах из `domains/`.
- [optional-validation] `index_entries` опционален в payload. Если LLM не передал — проверка broken refs в INDEX пропускается. Пропуск молчаливый.
  - **→ [RMR-2](../../TODO.md#rmr-2)**: добавить warning-issue уровня `yellow` / категория `index_check_skipped` при пропуске.

## Readability (P2)
- 486 строк SKILL.md; шесть шагов + Шаг 0; anti-patterns явные. Хорошо.
- 27 категорий issues описаны таблицей — навигация быстрая.
- `transport-layer.md` ссылка через `pack.sh` — корректное поведение, не пропавший файл.

## Cost (P3)
- Локальный скрипт без зависимостей; миллисекунды на типичную библиотеку.
- Bash для `.docx`-extraction только при явном подтверждении пользователя.

## Speed (P4)
- O(n) по числу файлов; параллельные `Glob` через transport. Реальные размеры (~30–50 файлов) — субсекундно.

## Cross-skill / contract
- D3 OK: revise-memory-remote — maintenance-скилл, может писать в `Claude-Memory/`. Реально пишет: чинит broken refs, обновляет INDEX, фиксирует дату последней ревизии.
- Совместно с `memory-sync` и `revise-memory-local` — три «обслуживающих» инструмента, разделённых по зонам ответственности.
- save-to-library — потребитель: после ревизии может потребоваться обновить `_sync_log.md`.

## Verified against artifact
- `~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/INDEX.md`: master-индекс присутствует, обновлён 2026-05-06; разделы Forecasts & Scenarios, Track record summary с trust-уровнями.
- `domains/<sub>/`: реальные аудит-файлы соответствуют `audit-frontmatter-schema.md`.
- 51/51 тестов `validate_library.py` зелёные (после fix 2026-05-10).
