# docs/travel-planning/

Дев-документация скилла `travel-planning`: архитектурные решения, known failure
modes, методология, экспортный контур, история правок и калибровочные кейсы.
Внутри `.skill`-архива этого нет — скилл self-contained, дев-материалы живут
только здесь.

Сюда же ходит проектный скилл-навигатор `/travel-docs <стадия|тема>` — он по
каталогу ниже определяет, какие файлы прочитать перед правкой/обсуждением.
**При любой правке скилла обязателен `CLAUDE.md` этого дерева** (дев-гайд:
self-contained-правила, что НЕ должно протекать в `.skill`, синхронизация
документации).

---

## 1. Раскладка

```
docs/travel-planning/
├── README.md            ← этот файл: точка входа + каталог тема→доки
├── CLAUDE.md            ← дев-гайд (ОБЯЗАТЕЛЕН при любой правке скилла)
├── TODO.md              ← единый forward-looking бэклог
├── changelog.md         ← история правок по версиям (v0.1 → …)
├── architecture.md      ← consolidated picture: решения + known failure modes
├── format-firewall.md   ← нормализация/валидация артефактов (normalize → check_format)
├── travel-planning-methodology.md  ← полная методология (Stage N → §(N+4))
│
├── stages/              ← per-stage дизайн, handoff-контексты, примеры выходов
│   ├── f40-stage0-v2-design.md          дизайн Stage 0 v2 (PLAN)
│   ├── stage3-handoff-context.md        actual state Stage 3 (REVIEW)
│   ├── Stage-3.md                       пример реального выхода Stage 3 (страна В)
│   ├── stage4-handoff-context.md        ⚠ HISTORICAL (pre-implementation Stage 4)
│   ├── stage4-comments.md               журнал failure modes Stage 4 + Pre-emit checklist
│   ├── Stage-4-example.md               пример выхода Stage 4 (Страна Б)
│   ├── stage5-handoff-context.md        контекст Stage 5
│   ├── stage5-etap2-plan.md             план Этапа 2 Stage 5 (статус-маркеры и пр.)
│   ├── stage6-handoff-context.md        контекст Stage 6 (карта + досье)
│   ├── stage6-korea-test-findings.md    находки live-теста Stage 6 на Страна А
│   └── awd_reports_subforum_discovery.md  памятка B1 discovery awd.ru (Stage 1 / fetch_awd)
│
├── export/              ← экспортный контур (PDF/DOCX/HTML, карты)
│   ├── export-design.md                 SSOT дизайна экспорта (визуальный язык, polish)
│   ├── export-design-by-type.md         дизайн по типам получателей
│   ├── export-polish-plan.md            полиграфические правки по дизайн-ревью Страна А
│   ├── stage4-pdf-export-plan.md        дизайн PDF-экспорта Stage 4
│   ├── travel-planning-pdf-правки.md    накопительные правки PDF
│   ├── travel-plan-review.md            рамка качества плана (эталон self-guided операторов)
│   ├── travel-plan-maps-spec.md         спека карт финального плана
│   ├── sys3-g6-inset-assessment.md      оценка inset-карт (SYS-3/G6)
│   ├── vietnam-similarity-scoring.html  образец интерактивного HTML Stage 2
│   ├── gen_pdf.py                       ⚠ HISTORICAL: ручной прототип PDF (Страна А 2024)
│   └── map-prototype/                   прототипы overview-карт (код + PNG/PDF)
│
├── plans/               ← одноразовые планы, ревью, session-handoff'ы
│   ├── export-fix-batch-2026-07.md      батч 1 правок экспорта (PLAN, реализован 2026-07-05)
│   ├── export-fix-batch-2-2026-07.md    батч 2 правок экспорта по прогону Китая (PLAN, активный)
│   ├── russification-phase2-plan.md     русификация Фаза 2: эмит .md + рендер-словарь (PLAN)
│   ├── r2-split-plan.md                 R2: split format-contract / выходных спек
│   ├── russification-plan.md            русификация (Фаза 1 сделана, §7 — карта Фазы 2)
│   ├── travel-planning-structure-review-2026-06-04.md  внешнее ревью структуры скилла
│   ├── checklist.md                     golden-чеклист LLM-прогона Волны 1b+2
│   └── session-handoff-2026-05-23.md    ⚠ HISTORICAL
│
└── calibration/         ← калибровочные кейсы, постмортемы, реальные прогоны
    ├── postmortem-procedure.md          ★ процедура разбора поездки (этапы А–Д)
    ├── postmortem-template.md           ★ шаблон разбора — копировать в {slug}_postmortem.md
    ├── past_trips.md                    посещённые места (негативный фильтр)
    ├── vietnam_2023_postmortem_template.md     кейс 1 (mediocre)
    ├── argentina_south_2025_postmortem_template.md  кейс 2 (successful)
    ├── vietnam_north_v4_calibrated.md   откалиброванный план Страна Б v4
    ├── vietnam_north_2026_postmortem_template.md  кейс 3: план vs факт реальной поездки по Stage 5 v6 + брони (закрыт, §11 — разбор)
    ├── страна Г.md                           наблюдения Stage 0 по Страна Г
    ├── анкета_*.docx                    образцы анкеты профиля
    └── страна В/ страна Б/ страна_г_0/ страна_г_1/ страна А/   полные прогоны-фикстуры
                                         (страна_г_1 и страна Б читает test_export_engine.py [15])
```

Типы: **DOC** — референс; **PLAN** — план/roadmap; **REVIEW** — аудит состояния;
**HISTORICAL** — не актуализируется, читать только за историческим контекстом.

---

## 2. Каталог: тема → релевантные доки

Кросс-темные файлы (`CLAUDE.md`, `architecture.md`, `changelog.md`, `TODO.md`)
релевантны всем — в таблице не повторяются. Колонка «код скилла» — где живёт
реализация в `skills/travel-planning/`.

| Тема | Доки | Код скилла |
|---|---|---|
| Методология (вся) | `travel-planning-methodology.md` (Stage N → §(N+4)) | `references/methodology.md` |
| Stage 0 (scope) | `stages/f40-stage0-v2-design.md` | `references/stage0/`, `scripts/export/stages/stage0.py` |
| Stage 1 (DR-промт) | `stages/awd_reports_subforum_discovery.md`, `plans/r2-split-plan.md` | `references/stage1/`, `scripts/fetch_awd.py`, `scripts/parse_dr_cards.py` |
| Stage 2 (similarity) | `architecture.md` §3+§6+§7, `export/vietnam-similarity-scoring.html` (HTML-образец) | `references/stage2/`, `scripts/similarity_score.py` |
| Stage 3 (POI) | `architecture.md` §8, `stages/stage3-handoff-context.md`, пример `stages/Stage-3.md` | `references/stage3/`, `scripts/aggregate_pois.py` |
| Stage 4 (варианты) | `architecture.md` §9, `stages/stage4-comments.md`, пример `stages/Stage-4-example.md`; история — `stages/stage4-handoff-context.md` | `references/stage4/` |
| Stage 5 (финальный план) | `stages/stage5-handoff-context.md`, `stages/stage5-etap2-plan.md` | `references/stage5/`, `scripts/export/stages/stage5.py` |
| Stage 6 (финиш: карта + досье) | `stages/stage6-handoff-context.md`, `stages/stage6-korea-test-findings.md`, `export/travel-plan-maps-spec.md`, `export/sys3-g6-inset-assessment.md` | `references/stage6/`, `scripts/geocode.py`, `scripts/export/stages/stage6.py` |
| Export (все стадии) | **`plans/export-fix-batch-2-2026-07.md`** (активный исполняемый план, батч 2), `plans/export-fix-batch-2026-07.md` (батч 1, реализован), `export/export-design.md` (SSOT), `export/export-design-by-type.md`, `export/export-polish-plan.md`, `export/stage4-pdf-export-plan.md`, `export/travel-planning-pdf-правки.md`, `export/travel-plan-review.md` + **`format-firewall.md`** (перед правкой парсеров/форматов — обязателен) | `references/export/`, `scripts/export/` (включая `polish_check.py`), `scripts/normalize.py`, `scripts/check_format.py` |
| Profile / анкета | `calibration/анкета_*.docx` (образцы) | `references/profile-management.md`, `scripts/profile/` |
| Format-firewall / парсеры | `format-firewall.md`, `plans/r2-split-plan.md` | `scripts/normalize.py`, `scripts/check_format.py`, `tests/test_format_contract.py` |
| Калибровка / валидация | `CLAUDE.md` §Calibration, `calibration/*` (постмортемы, прогоны) | `tests/` (фикстуры страна_г_1/страна Б) |
| Разбор поездки (postmortem) | `calibration/postmortem-procedure.md`, `calibration/postmortem-template.md`, эталон `calibration/vietnam_north_2026_postmortem_template.md` (§11) | `references/profile-management.md` (куда ложатся профильные находки) |
| Страница `travel.html`: статус поездки, md-режим | **`plans/trip-status-and-reader-plan.md`** (к исполнению; четыре уровня точности дат — точные/месяц/год/нет, `start`/`end` в `trip.yaml` + `scripts/trip_dates.py`, общий `uiTripWhen` для travel и hub, md-стадии и профили → `uiReader`) | `references/storage-and-naming.md` (`trip.yaml`), `scripts/check_format.py`, `tools/travel.html` |
| Русификация (i18n) | **`plans/russification-phase2-plan.md`** (активный план Фазы 2), `plans/russification-plan.md` (Фаза 1, реализована), **`format-firewall.md` §7** (taxonomy.json как SSOT ярлыков/категорий/англицизмов, обе ветки рендера) | `scripts/taxonomy.py`, `scripts/data/taxonomy.json`, `scripts/export/html_lib.py` (`ru_anglicisms`/`legend_line`) |

---

## 3. Когда сюда смотреть

- **Дизайнишь Stage 7+ / новую стадию** — через скилл `/travel-stage-builder`;
  он создаёт `stages/stage{N}-handoff-context.md` по образцу stage3/stage4.
- Правишь конкретную стадию или экспорт — строка каталога §2.
- Дебажишь странное поведение модели — `architecture.md` §5 «Safety filter и Haiku-fallback».
- Думаешь, что переложить в скрипт — `architecture.md` §2 «Граница LLM vs script».
- Нужна история конкретной правки — `changelog.md`; forward-бэклог — `TODO.md`.

## 4. Что НЕ здесь

- Список тестовых команд — `docs/test-registry.md` (запуск: `python3 tools/run_tests.py travel-planning`).
- Активные рабочие инструкции по скиллу — `CLAUDE.md` этого дерева.
- Человеческая шпаргалка по стадиям — `skills/travel-planning/STAGES.md`.

## 5. Скилл-навигатор `/travel-docs`

Проектный скилл (`.claude/skills/travel-docs/`, рядом с `investment-docs` и
`travel-stage-builder`). Передаёшь стадию или тему — он по §2 этого README грузит
нужное подмножество документации, не читая остальное.

```
/travel-docs stage 3            # одна стадия
/travel-docs export             # экспортный контур
/travel-docs methodology        # методология
/travel-docs stage 6 export     # несколько тем
```

> **Конвенция:** новые задачи — в `TODO.md`; история — в `changelog.md`;
> новые доки — регистрировать в §1–§2 этого README (он — SSOT каталога,
> зеркальная таблица в `/travel-docs` обновляется вместе с ним).
