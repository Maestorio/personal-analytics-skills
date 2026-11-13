# Skill: save-to-library

## Summary
Hub-скилл. После верификации (2026-05-10) из 6 P1-дефектов: 3 — галлюцинации, 2 — исправлены, 1 — артефакт старой схемы. P2/P3 вынесены в TODO.md (STL-1..STL-4).

---

## Correctness (P1)

- ~~[bug] Валидация перед записью не обязательна.~~ → **✅ ИСПРАВЛЕНО** (`references/workflow-bcde.md` Workflow B6.0: добавлен blocking вызов `assemble_artifact.py validate-forecast` перед Write; при `blocking` issues — возврат в B4.1a, файл не пишется.)

- [artifact] `forecasts/ru-rates-2026-2026-04-28.yaml:12` имеет `confidence: null`. Файл `status: superseded`, создан до последних изменений схемы (3–4 дня). Не является доказательством текущего дефекта в Workflow B6 — скрипт `validate_forecast_frontmatter` корректно ловит этот случай (`test_fca_without_confidence_blocking`).

- ~~[bug] E2 encoding-check не ловит «синтаксическое mojibake» (`**` внутри кириллицы) в `forecasts/ai-capex-slowdown-2026-2026-04-30.md`.~~ → **ГАЛЛЮЦИНАЦИЯ** (файл чистый: все `**` только вокруг целых слов).

- ~~[missing-dispatch] `SKILL.md:52–70` не упоминает `weekly-bonds-review`.~~ → **ГАЛЛЮЦИНАЦИЯ** (строка 61 таблицы: `type: weekly-bonds-review → Workflow F`).

- ~~[bug] `Portfolio/weekly-reviews/` пуст.~~ → **ГАЛЛЮЦИНАЦИЯ** (`Claude-Memory/Portfolio/weekly-reviews/` содержит 7 файлов, последние от 2026-05-09/10).

- ~~[bug] `forecast-collections/` — 7 файлов с `FC-` UPPERCASE (нарушение D4).~~ → **✅ ИСПРАВЛЕНО** (6 файлов переименованы в `fc-*`; `forecast-collector/SKILL.md` — шаблон имени файла исправлен; `forecast-collections/INDEX.md` — обновлён, добавлена пропущенная IEA-запись).

- [missing-validation] Парность `.md` ↔ `.yaml` не проверяется в Workflow B/C — есть только anti-pattern «никаких одиночных файлов» (SKILL.md:43). Текущая память чиста, но защита не системная.

---

## Readability (P2) → [docs/investment/TODO.md](../../TODO.md)

- **STL-1** — Workflow A/L inline в SKILL.md; B–K в references — инконсистентно.
- **STL-2** — 24 anti-pattern без группировки (SKILL.md:318–372).
- **STL-3** — `SKILL.md:25` упоминает «11 скиллов» — не совпадает с реальным числом.
- **STL-4** — Шаблон `_sync_log.md` в `workflow-bcde.md` расходится с реальными pipe-delimited записями.

---

## Cost (P3)

- Дублирование валидационной логики между SKILL.md (текстом) и `assemble_artifact.py` (кодом). Лучше короткий pointer к функции скрипта.
- Молчаливый fallback B → A (transport-layer.md:66–90 требует прозрачности).

## Speed (P4)

- Последовательная запись `.md` → `.yaml` → INDEX → `_sync_log`. При пакетном сохранении 5+ артефактов можно параллелить запись `.md`/`.yaml` пар.

---

## Cross-skill / contract

- D3 OK: только save-to-library + maintenance пишут в `Claude-Memory/`. По `_sync_log.md` это так.
- Auto-inclusion (`pin OR HIGH`) корректно реализован — но результат не помечается `include_in_memory: true/false` во frontmatter. memory-sync пересчитывает каждый раз; при ручном edit'е легко рассинхронизировать.
- `_sync_log.md`: формат реальных записей (pipe-delimited `ДАТА | операция | файл | ...`) расходится с шаблоном в `workflow-bcde.md`. → **STL-4** в TODO.md.

---

## Verified against artifact (2026-05-10)

- `forecasts/`: 19 файлов, 100% парность `.md+.yaml`. ✓
- `forecasts/ru-rates-2026-2026-04-28.yaml:12` — `confidence: null` — артефакт старой схемы, файл superseded.
- `forecasts/ai-capex-slowdown-2026-2026-04-30.md` — чистый. ✓
- `scenarios/`: 3 файла, парность OK ✓.
- `forecast-collections/`: 6 файлов переименованы в `fc-*` ✓.
- `audits/`: пусто — отдельный issue (`_claude-memory-anomalies.md`).
- `Portfolio/weekly-reviews/`: 7 файлов (до 2026-05-10) ✓.
- `monitor-reports/monitor-report-2026-05-07.yaml`: формат соответствует `yaml-schemas.md §8` ✓.
- `INDEX.md` обновляется — последняя запись 2026-05-06 (Full audit IEA OMR) ✓.
