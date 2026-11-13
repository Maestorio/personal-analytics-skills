---
name: travel-docs
description: >
  Навигатор по дев-документации скилла travel-planning в репозитории
  claude_skills. Передаёшь стадию (stage 0..6) или тему (export / methodology /
  firewall / calibration / postmortem / profile / i18n) — скилл грузит ТОЛЬКО релевантную
  документацию (дев-гайд, нужные stages/export/plans-доки, бэклог) перед
  правкой / улучшением / обсуждением, не читая остальное дерево.
  Вызов: /travel-docs <стадия|тема> [ещё темы].
trigger: /travel-docs
---

# /travel-docs

Точечная загрузка документации перед работой над скиллом `travel-planning`.
Цель — не читать лишнее: правя Stage 3, не тянуть экспортный дизайн-док на
1600 строк.

Проектный скилл — живёт в `.claude/skills/` репозитория `claude_skills` (рядом
с `investment-docs` и `travel-stage-builder`), осмыслен только внутри него.
Все пути ниже — относительно корня репозитория.
**Корень документации:** `docs/travel-planning/` — там `README.md` с полным
каталогом «тема → доки» (§2) и раскладкой (§1). README — SSOT каталога;
таблица ниже его дублирует для скорости, при расхождении верь README.

## Использование

```
/travel-docs stage 3              # одна стадия
/travel-docs export               # экспортный контур (PDF/DOCX/HTML, карты)
/travel-docs stage 6 export       # несколько тем
/travel-docs methodology          # методология целиком
/travel-docs                      # без аргумента → прочитать README и спросить
```

## Процедура

1. **Разобрать аргумент** в список тем:
   - `stage N` / `стадия N` / `stage0`…`stage6` → стадия N;
   - тема: `export` / `methodology` / `firewall` (= format-firewall / парсеры) /
     `calibration` / `postmortem` (= разбор поездки) / `profile` (= анкета) / `i18n` (= русификация) /
     `todo` / `changelog`;
   - несколько токенов → объединение;
   - пусто → прочитать `docs/travel-planning/README.md` и спросить пользователя.
2. **Всегда прочитать сначала:**
   - `docs/travel-planning/CLAUDE.md` — дев-гайд, **обязателен при любой правке
     скилла** (self-contained-правила, что НЕ должно протекать в `.skill`,
     синхронизация документации, калибровочные кейсы);
   - `docs/travel-planning/README.md` (каталог + раскладка);
   - `skills/travel-planning/SKILL.md` — routing-таблица и gate'ы (по мере надобности).
3. **Для каждой запрошенной темы** прочитать её строку каталога (§2 README):
   доки + указанные § `architecture.md` + код скилла по необходимости.
   Грузить только это. `changelog.md` (2700 строк) — только если нужна история
   конкретной правки; `TODO.md` — фильтровать по теме.
4. **Кросс-темное** (читать при сомнениях/широкой правке):
   `docs/travel-planning/architecture.md` (решения + failure modes),
   `docs/travel-planning/TODO.md`, `skills/travel-planning/STAGES.md`
   (человеческая шпаргалка). Перед правкой парсеров/форматов экспорта —
   `docs/travel-planning/format-firewall.md` обязателен.
5. **Доложить, что загружено**, и ждать задачу (правка / улучшение / обсуждение).
   Если пользователь просил «проанализируй/проверь» — выдать анализ и ждать;
   править сразу только по «исправь/сделай».

Для **дизайна новой стадии** (Stage 7+) этот скилл не используется — там
`/travel-stage-builder` (он сам читает всю документацию пайплайна).

## Карта тема → доки (зеркало README §2)

Пути доков — относительно `docs/travel-planning/`; код — относительно
`skills/travel-planning/`. Кросс-темные (`CLAUDE.md`, `architecture.md`,
`changelog.md`, `TODO.md`) в строках не повторяются.

| Тема | Доки | Код скилла |
|---|---|---|
| methodology | `travel-planning-methodology.md` (Stage N → §(N+4)) | `references/methodology.md` |
| stage 0 | `stages/f40-stage0-v2-design.md` | `references/stage0/`, `scripts/export/stages/stage0.py` |
| stage 1 | `stages/awd_reports_subforum_discovery.md`, `plans/r2-split-plan.md` | `references/stage1/`, `scripts/fetch_awd.py`, `scripts/parse_dr_cards.py` |
| stage 2 | `architecture.md` §3+§6+§7, `export/vietnam-similarity-scoring.html` (HTML-образец) | `references/stage2/`, `scripts/similarity_score.py` |
| stage 3 | `architecture.md` §8, `stages/stage3-handoff-context.md`, пример `stages/Stage-3.md` | `references/stage3/`, `scripts/aggregate_pois.py` |
| stage 4 | `architecture.md` §9, `stages/stage4-comments.md`, пример `stages/Stage-4-example.md` | `references/stage4/` |
| stage 5 | `stages/stage5-handoff-context.md`, `stages/stage5-etap2-plan.md` | `references/stage5/`, `scripts/export/stages/stage5.py` |
| stage 6 | `stages/stage6-handoff-context.md`, `stages/stage6-korea-test-findings.md`, `export/travel-plan-maps-spec.md`, `export/sys3-g6-inset-assessment.md` | `references/stage6/`, `scripts/geocode.py`, `scripts/export/stages/stage6.py` |
| export | `plans/export-fix-batch-2-2026-07.md` (активный план, батч 2), `plans/export-fix-batch-2026-07.md` (батч 1, реализован), `export/export-design.md` (SSOT), `export/export-design-by-type.md`, `export/export-polish-plan.md`, `export/stage4-pdf-export-plan.md`, `export/travel-planning-pdf-правки.md`, `export/travel-plan-review.md` + `format-firewall.md` | `references/export/`, `scripts/export/`, `scripts/normalize.py`, `scripts/check_format.py` |
| profile | `calibration/анкета_*.docx` (образцы) | `references/profile-management.md`, `scripts/profile/` |
| firewall | `format-firewall.md`, `plans/r2-split-plan.md` | `scripts/normalize.py`, `scripts/check_format.py`, `tests/test_format_contract.py` |
| calibration | `CLAUDE.md` §Calibration, `calibration/*` (постмортемы, прогоны-фикстуры) | `tests/` (фикстуры страна_г_1/страна Б) |
| postmortem | `calibration/postmortem-procedure.md`, `calibration/postmortem-template.md`, эталон `calibration/vietnam_north_2026_postmortem_template.md` | `references/profile-management.md` |
| i18n | `plans/russification-phase2-plan.md` (активный), `plans/russification-plan.md` (Фаза 1), `format-firewall.md` | `scripts/taxonomy.py`, `scripts/data/taxonomy.json` |

**Не читать** handoff-доки закрытых стадий ради «общего контекста» — они
исторические, актуальное состояние всегда в `architecture.md` (например,
`stages/stage4-handoff-context.md` — pre-implementation, текущий Stage 4 —
`architecture.md` §9 + `stages/stage4-comments.md`).

## Принципы

- **Минимум контекста.** Грузить только доки запрошенных тем.
- **README — SSOT каталога.** При добавлении дока обновлять
  `docs/travel-planning/README.md` (§1–§2) и зеркальную таблицу здесь.
- **Дев-гайд обязателен.** `docs/travel-planning/CLAUDE.md` читается всегда —
  его self-contained-правила защищают `.skill`-архив от протечки дев-материалов.
- **Язык — русский** (как и вся документация репозитория).
