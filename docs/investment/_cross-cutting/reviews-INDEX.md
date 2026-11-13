# Skill Reviews — INDEX

Полный аудит 16 скиллов на 2026-05-07. Приоритезация по `CLAUDE.md`: **корректность > читаемость > стоимость > скорость**. Каждый файл выполнен по фиксированному шаблону (Summary → P1 Correctness → P2 Readability → P3 Cost → P4 Speed → Cross-skill / contract → Verified against artifact). Кросс-системные находки и аномалии библиотеки — в отдельных `_*`-файлах.

## Per-skill review

| Скилл | P1 | P2 | P3 | P4 | Файл |
|---|---:|---:|---:|---:|---|
| portfolio-scenario-stress | 4 | 3 | 1 | 0 | [portfolio-scenario-stress.md](../portfolio/reviews/portfolio-scenario-stress.md) |
| save-to-library | 5 | 3 | 1 | 1 | [save-to-library.md](../memory/reviews/save-to-library.md) |
| macro-forecast-chain | 2 | 2 | 0 | 0 | [macro-forecast-chain.md](../forecasting/reviews/macro-forecast-chain.md) |
| memory-sync | 3 | 2 | 0 | 1 | [memory-sync.md](../memory/reviews/memory-sync.md) |
| portfolio-integrated-view | 3 | 2 | 0 | 0 | [portfolio-integrated-view.md](../portfolio/reviews/portfolio-integrated-view.md) |
| hypothesis-stress-tester | 3 | 3 | 0 | 0 | [hypothesis-stress-tester.md](../forecasting/reviews/hypothesis-stress-tester.md) |
| scenario-builder | 2 | 2 | 0 | 0 | [scenario-builder.md](../forecasting/reviews/scenario-builder.md) |
| portfolio-data-loader | 3 | 1 | 0 | 0 | [portfolio-data-loader.md](../portfolio/reviews/portfolio-data-loader.md) |
| forecast-collector | 3 | 2 | 0 | 0 | [forecast-collector.md](../forecasting/reviews/forecast-collector.md) |
| retrospective-forecast-audit | 3 | 1 | 0 | 0 | [retrospective-forecast-audit.md](../forecasting/reviews/retrospective-forecast-audit.md) |
| forecast-confidence-applier | 3 | 2 | 0 | 1 | [forecast-confidence-applier.md](../forecasting/reviews/forecast-confidence-applier.md) |
| forecast-monitor | 3 | 2 | 0 | 1 | [forecast-monitor.md](../forecasting/reviews/forecast-monitor.md) |
| revise-memory-remote | 3 | 0 | 0 | 0 | [revise-memory-remote.md](../memory/reviews/revise-memory-remote.md) |
| revise-memory-local | 3 | 1 | 0 | 0 | [revise-memory-local.md](../memory/reviews/revise-memory-local.md) |
| macro-ru-watcher | 3 | 1 | 0 | 0 | [macro-ru-watcher.md](../forecasting/reviews/macro-ru-watcher.md) |
| ru-portfolio-advisor | 4 | 3 | 1 | 1 | [ru-portfolio-advisor.md](../portfolio/reviews/ru-portfolio-advisor.md) |
| **TOTAL** | **51** | **30** | **3** | **5** | — |

Числа — кол-во issues в каждой категории. Цифры приблизительны: фокус был на P1-correctness, P2/P3/P4 фиксировались только при наличии существенных пунктов.

## Кросс-системные документы

- [_cross-skill.md](_cross-skill.md) — D3/D4-нарушения, schema-mismatches между shared-refs и скиллами, мёртвые shared-refs, mojibake-источники.
- [_claude-memory-anomalies.md](_claude-memory-anomalies.md) — реальные аномалии в `Claude-Memory/` (битый symlink, UPPERCASE префиксы, пустые директории, undocumented dirs).

## Топ-10 P1 (correctness) для немедленной правки

Отсортировано по «эффект × вероятность срабатывания». Приоритет — каскад на максимум скиллов.

1. **save-to-library: валидация не обязательна перед write** → `forecasts/ru-rates-2026-2026-04-28.yaml:11` с `confidence: null` тому пример. Затрагивает все Workflow B/C/D/F.
2. **save-to-library: dispatch weekly-bonds-review missing** → схема описана в `yaml-schemas.md §7b`, скилл её игнорирует.
3. **forecast-collector + macro-ru-watcher: D4-нарушение (UPPERCASE префиксы)** → `FC-*.md`, `RU-*.md`. Ломает Glob-фильтры downstream.
4. **portfolio-scenario-stress: schema-mismatch internal vs canonical factor names** → `input-adapters.md` vs `compute_per_position.py:31`. Тихая ошибка с нулевыми бетами.
5. **portfolio-scenario-stress: missing `unmapped_tickers` и `caveats` в свежем артефакте** → Pre-emit checklist обещает, реальность не имеет.
6. **markdown-bold mojibake в forecasts/*.md** → источник: FCA или HST текстовые шаблоны. E2 encoding-check не ловит.
7. **revise-memory-remote: null-значения обязательных полей проходят валидацию** → `trust: null`, `source: null` пройдут.
8. **macro-ru-watcher: USD/RUB ❓ без fallback** → Tier 1 индикатор системно отсутствует в свежих снапшотах.
9. **D3 формальное противоречие layout-doc vs реальные writers** → data-loader, macro-watcher, forecast-monitor пишут напрямую.
10. **Layout-doc не отражает monitor-reports/, stale_flags.yaml, реальный путь audits** → потенциальные ложные срабатывания при revise-memory-remote и человеком.

## P2 (readability) — топ-5

1. `save-to-library`: workflow A inline, B–E/F–K в references, L снова inline — структурная инконсистентность.
2. `forecast-confidence-applier`: 6 shared-refs, дублирующие фразы «все числовые расчёты — только через скрипт» (≥3 раза).
3. `ru-portfolio-advisor`: 8 режимов × правил 1–22 × 17 references — большой когнитивный объём.
4. `hypothesis-stress-tester`: 4 техники описаны очень кратко (`tier1-methods.md` 40 строк), ACH-матрица без примеров.
5. `_sync_log.md` шаблон vs реальность: формат расходится, лог пишется ad-hoc.

## Рекомендуемый порядок исправлений

**Этап A (за 1 день):**
1–2. Правка `save-to-library` Workflow B6 (обязательная валидация) + dispatch для weekly-bonds-review.
3. Массовое переименование UPPERCASE → lowercase в `forecast-collections/` и `macro-snapshots/` + правка `forecast-collector/SKILL.md:308` и шаблона `macro-ru-watcher`.
4. Удаление битого symlink `Claude-Memory/Claude-Memory`.
5. Удаление пустой `weekly-reviews/` в корне.

**Этап B (за неделю):**
6. Регэкс-проверка mojibake `\w\*\*\w` по всем `forecasts/*.md` и `scenarios/*.md`. Авто-фикс или ручная правка.
7. Правка `portfolio-scenario-stress`: добавить normalization факторов в `input-adapters.md` (или в скрипт); добавить `unmapped_tickers` и `caveats` в выход.
8. Правка `revise-memory-remote/scripts/validate_library.py`: проверка non-null значений.
9. Правка `macro-ru-watcher`: явный fallback-список для USD/RUB.

**Этап C (концептуальная гигиена):**
10. Обновить `claude-memory-layout.md`: добавить `monitor-reports/`, `stale_flags.yaml`, скорректировать `audits/`, легализовать D3-исключения для data-loader / macro-watcher / forecast-monitor.
11. Унифицировать формат `_sync_log.md` (форматтер в `sync_planner.py`).
12. Принять решение по `_shared-references/model-routing.md` и `source-discovery.md`: shared или локальные.

## Верификация

- Все 16 per-skill файлов и 2 cross-файла записаны.
- Реальные артефакты в `Claude-Memory/` сверены: forecasts (3), scenarios (1), forecast-collections (выборочно), macro-snapshots (2), macro-chain (1), Portfolio/snapshots (1), Portfolio/stress (1), Portfolio/weekly-reviews (3), Portfolio/integrated-views (1), monitor-reports (1), domains (выборочно).
- `pack.sh` и `_shared-references/` consistency: shared-refs физически существуют все 8; `pack.sh` инжектирует — это объясняет «отсутствующие» локальные `references/transport-layer.md`.
