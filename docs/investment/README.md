# Документация инвестиционно-прогнозного контура

Единая точка входа в документацию по 17 скиллам финансово-прогнозного пайплайна
(всё, кроме `travel-planning`, у которого своё дерево — `docs/travel-planning/`).

Сюда же ходит личный скилл-навигатор `/investment-docs <скилл|домен>` — он по этому
каталогу определяет, какие файлы прочитать перед правкой/обсуждением скилла.

---

## 1. Три домена

Скиллы делятся на три поддомена. Forecasting **питает** portfolio
(сценарии/прогнозы → stress → integrated-view), но это разные концерны —
правя скилл одного домена, документацию другого читать не нужно.

| Домен | Скиллы | Папка докумен­тации |
|---|---|---|
| **portfolio** | `portfolio-data-loader`, `ru-portfolio-advisor`, `portfolio-scenario-stress`, `portfolio-integrated-view`, `portfolio-coherence-audit` | `portfolio/` |
| **forecasting** | `macro-ru-watcher`, `macro-forecast-chain`, `forecast-collector`, `forecast-confidence-applier`, `forecast-monitor`, `scenario-builder`, `retrospective-forecast-audit`, `hypothesis-stress-tester` | `forecasting/` |
| **memory** | `save-to-library`, `memory-sync`, `revise-memory-local`, `revise-memory-remote` | `memory/` |

Общесистемные документы (аудит всех скиллов, мастер-план, карта DAG) — в `_cross-cutting/`.

---

## 2. Раскладка

```
docs/investment/
├── README.md            ← этот файл: точка входа + каталог skill→доки
├── TODO.md              ← ЕДИНЫЙ бэклог всех скиллов (ID префиксованы: RPA-, FCA-, PIV-…)
├── TODO_design.md       ← вьюер портфеля: дизайн, движок вывода, новое содержание (с 2026-10-12)
├── portfolio-workflow-guide.md  ← операционный навигатор: что/в каком порядке гонять, вкладка→скилл, провенанс; зеркало пользовательской справки вьюера (DOC)
│
├── _cross-cutting/      общесистемное (касается всех доменов)
│   ├── plan.md                      мастер-план фаз 0–7 (PLAN)
│   ├── conditional-architecture.md  полная спека двухслойной архитектуры прогнозов (D1–D8, типы updates/прогнозов, D8-атрибуция); вынесена из CLAUDE.md 2026-08-12, в корне — сводка (DOC)
│   ├── scripts-map.md               карта Python-скриптов всех скиллов контура; вынесена из CLAUDE.md 2026-08-12, жёсткие правила — в корне (DOC)
│   ├── data-structures-plan.md      план цикла машиночитаемости портфельных данных (PLAN)
│   ├── data-structures/             цикл машиночитаемости (30.10–31.10): schema.md — эталон схемы данных портфеля
│   │                                (сущности, писатели, читатели, модули (а)(б)(в), время, кодлисты); decision.md —
│   │                                решения R1–R25, 18 шагов и §4.2 «Переключение»; инвентарь, трассы, приложения (DOC)
│   ├── report.md                    аудит 15 скиллов, P0–P3 (REVIEW)
│   ├── reviews-INDEX.md             индекс per-skill ревью + топ-10 приоритетов
│   ├── _cross-skill.md              D3/D4-нарушения, schema-mismatch между скиллами
│   ├── _claude-memory-anomalies.md  аномалии хранилища Claude-Memory/
│   ├── scripts-optimization-report.md  возможности оптимизации Python (REVIEW)
│   ├── phase-3-mfc-4-plan.md           handoff-план Фазы 3 (SS-1) + MFC-4 (PLAN)
│   ├── phase-4-v2-plan.md              handoff-план Фазы 4 (V2-A horizons + V2-B Monte Carlo) (PLAN)
│   ├── phase-6-v3-ux-plan.md           handoff-план Фазы 6 (V3-A: история + мобайл) (PLAN)
│   ├── phase-4-post-v2-cutover-plan.md  handoff-план V2-CUTOVER (миграция v1→v2 + снятие co-existence) (PLAN)
│   ├── phase-7-long-term-plan.md       roadmap Фазы 7 (v4-A…D, эскиз по каждой; W2/W3 отменены 2026-10-08) (PLAN)
│   ├── open-source-and-portfolio.md    стоит ли open-source-ить систему (REVIEW)
│   ├── phase-10.2-nas-hosting.md       хостинг вьюера на NAS (PLAN, отложен)
│   ├── skill-system-map.html           интерактивная карта DAG скиллов (DOC)
│   └── new_structure/                  редизайн стресс-теста 2026-05-08 (PLAN/handoff)
│       ├── HANDOFF-claude-code-phased.md
│       ├── HANDOFF-cowork-data-phased.md
│       ├── HANDOFF-runbook.md
│       └── REVIEW-stress-test-redesign-2026-05-08.md   ⚠ HISTORICAL
│
├── portfolio/
│   ├── methodology.md               SSOT расчётных методов: METH-1 catalyst, §9 иерархия, §10 gate (DOC)
│   ├── new_met.md                   METH-2: Fundamental Gate Review Tracking v3 (DOC/спека)
│   ├── HTML_VIEW_TODO.md            задачи вьюера (FIX, в основном закрыто)
│   ├── html-comments.md             накопительные замечания по вьюеру (FIX/COMMENTS)
│   └── reviews/                     per-skill ревью 4 портфельных скиллов (REVIEW)
│
├── forecasting/
│   ├── conditional-forecasts-architecture.md  двухслойная архитектура прогнозов (DOC)
│   └── reviews/                     per-skill ревью 8 прогнозных скиллов (REVIEW)
│
└── memory/
    ├── save-to-library-fixes.md     3 дефекта Workflow E, готовы к применению (FIX)
    └── reviews/                     per-skill ревью 4 memory-скиллов (REVIEW)
```

Типы: **DOC** — читать как референс; **PLAN** — план/roadmap; **REVIEW** — аудит
текущего состояния; **FIX** — actionable-бэклог конкретных правок.

---

## 3. Каталог: скилл → релевантные доки

Колонка «бэклог» — где искать «что править» по этому скиллу. Кросс-системные
файлы (`plan.md`, `report.md`, `reviews-INDEX.md`, `_cross-skill.md`, `TODO.md`,
корневой `CLAUDE.md`) релевантны всем — в таблице не повторяются.

| Скилл | Домен | Доки-референсы | Ревью | TODO-префиксы |
|---|---|---|---|---|
| `ru-portfolio-advisor` | portfolio | `portfolio/methodology.md`, `portfolio/new_met.md`, `portfolio-workflow-guide.md`, `portfolio/rpa5-fanout-calibration.md` (журнал калибровки fan-out Mode 1/2 — дописывать после каждого прогона), `portfolio/bond-subtypes-plan.md` (подтипы облигаций: 9 плановых корзин, лестница рейтингов §4.2, контракт полей), `spec-gate-aware-sizing-trim-fix.md` (trim-to-target: категория `Rebalancing` и `--trim` §§1–7; правило неразворота §8; лимиты концентрации §9; **§10 — решения владельца, §11 — точка возобновления**; читать §10 ПЕРЕД §8 — B3 там отменён) | `portfolio/reviews/ru-portfolio-advisor.md` | RPA-, W2, W3, CR-, DRIFT-, METH- |
| `portfolio-data-loader` | portfolio | `portfolio/methodology.md`, `portfolio-workflow-guide.md`, `portfolio/bond-subtypes-plan.md` (подтипы облигаций: 9 плановых корзин, лестница рейтингов §4.2, контракт полей), `portfolio/air-1-decision-journal-plan.md` (AIR-1: теневые базы B0–B2 и журнал решений, решения владельца §7) | `portfolio/reviews/portfolio-data-loader.md` | PDL-, I-, D- |
| `portfolio-scenario-stress` | portfolio | `forecasting/conditional-forecasts-architecture.md`, `portfolio-workflow-guide.md`, `portfolio/factor-betas-explained.md`, `portfolio/stress-run-playbook.md` (рабочая инструкция прогона — читать перед запуском), `portfolio/stress-math.md` (расчётный контракт: все формулы, единицы, границы), `portfolio/sanctions-position-rubric.md` (как назначать и пересматривать позиции — процедура, не результат), `portfolio/sanctions-positions.yaml` (SSOT значений — оттуда их читает прогон), `portfolio/sanctions-position-draft.md` (человекочитаемый разбор), `portfolio/pss-4-sanctions-calibration-plan.md`, `portfolio/scenario-weights-and-ci-plan.md` (сценарные веса по горизонтам и факторный CI: PSS-6/P2-4/PSS-9/MFC-5, §8 — состояние и находки) (санкционный фактор: диагноз §1a, исследование §6–§7, форма модели §3.3) | `portfolio/reviews/portfolio-scenario-stress.md` | PSS-, SS- |
| `portfolio-integrated-view` | portfolio | `portfolio-workflow-guide.md`, `portfolio/methodology.md`, `forecasting/conditional-forecasts-architecture.md`, `TODO_design.md` (бэклог вьюера, с 2026-10-12), `portfolio/HTML_VIEW_TODO.md`, `portfolio/html-comments.md`, `portfolio/piv-run-2026-08-15-review.md` (разбор прогона: три падения Python, верификация артефакта пересчётом, пять дефектов контура — мёртвый L1-overlay, `on_iis` вне контракта payload, неработающая trust-матрица, расхождение якорей горизонтов, `macro_blindspot`); `INTEGRATION-DOCS/`; `tools/design-reference/` (дизайн-система HTML-viewer, Claude Design) | `portfolio/reviews/portfolio-integrated-view.md` | IV-, V2-, V3-, PIV- |
| `portfolio-coherence-audit` | portfolio | `portfolio/portfolio-coherence-audit-spec.md` (SPEC v0.1: ниша/двухстадийность/границы), `portfolio-workflow-guide.md` | — | — |
| `macro-ru-watcher` | forecasting | — | `forecasting/reviews/macro-ru-watcher.md` | MRW- |
| `macro-forecast-chain` | forecasting | `forecasting/conditional-forecasts-architecture.md`, `portfolio/scenario-weights-and-ci-plan.md` (сценарные веса по горизонтам и факторный CI: PSS-6/P2-4/PSS-9/MFC-5, §8 — состояние и находки) | `forecasting/reviews/macro-forecast-chain.md` | MFC-, v4-E |
| `forecast-collector` | forecasting | — | `forecasting/reviews/forecast-collector.md` | FC- |
| `forecast-confidence-applier` | forecasting | `forecasting/conditional-forecasts-architecture.md` | `forecasting/reviews/forecast-confidence-applier.md` | FCA- |
| `forecast-monitor` | forecasting | — | `forecasting/reviews/forecast-monitor.md` | FM- |
| `scenario-builder` | forecasting | `forecasting/conditional-forecasts-architecture.md` | `forecasting/reviews/scenario-builder.md` | SB- |
| `retrospective-forecast-audit` | forecasting | — | `forecasting/reviews/retrospective-forecast-audit.md` | CMA- |
| `hypothesis-stress-tester` | forecasting | — | `forecasting/reviews/hypothesis-stress-tester.md` | HST- |
| `save-to-library` | memory | `memory/save-to-library-fixes.md` | `memory/reviews/save-to-library.md` | STL-, MS-, CR-, DRIFT- |
| `memory-sync` | memory | — | `memory/reviews/memory-sync.md` | — |
| `revise-memory-local` | memory | — | `memory/reviews/revise-memory-local.md` | RML- |
| `revise-memory-remote` | memory | — | `memory/reviews/revise-memory-remote.md` | RMR- |

> **Факторные беты стресс-теста — особый случай.** Правишь `factor_betas` или
> сценарные факторы `sanctions`/`geopol` — сначала читай
> `skills/portfolio-scenario-stress/references/sector-sensitivities.md`, секции
> «Контракт единиц» и «Позиция на санкционной шкале». β — п.п. цены на одну
> единицу фактора; для политических единица = интенсивность 1.0 (бета банков
> −35, не −0.35). Долевая запись отличается ×100 и зануляет канал — движок
> откажется считать. Разбор и калибровка —
> `portfolio/pss-4-sanctions-calibration-plan.md`, код замеров —
> `tools/research/pss-4-sanctions/`.

Глобальные shared-references скиллов — в `_shared-references/` (репо-корень), не здесь.

---

## 3а. Правка скилла → обнови справку вьюера (жёсткое правило)

Пользователь видит скиллы контура через кнопку «❓ Справка» во вьюере портфеля —
`tools/assets/help/viewer/NN-slug.md` (10 частей; деплоятся с `assets/`), технический двойник —
`portfolio-workflow-guide.md`. **Меняешь у любого из 17 скиллов триггеры, режимы,
порядок запуска, артефакты или рекомендуемую модель — обнови оба файла в том же
коммите:** `01-run.md` (что сказать Claude), `02-models.md` (модель по скиллу; SSOT —
`_shared-references/model-routing.md`), `04-tabs.md`/`03-fresh.md` (вкладки, свежесть). Сменилась модель
или набор скиллов раздела — ещё и строку «Портфель» в `tools/assets/help/hub.md`.
Общее правило для всех страниц — корневой `CLAUDE.md`, «Справки страниц кабинета».

## 4. Где искать «что надо править» (кроме TODO.md)

Помимо мастер-`TODO.md`, actionable-бэклоги разбросаны по этим файлам —
это **единый индекс источников правок**:

| Источник | Что внутри | Состояние |
|---|---|---|
| `TODO.md` | мастер-бэклог всех скиллов, ID-префиксы по скиллу | активный |
| `TODO_design.md` | вьюер портфеля: переделка на ui-kit, ревизия вкладок, вывод ИИС-3 и журнала решений, VW-1/CR-D/DRIFT-7/V3-*; в конце — комментарии владельца (сравнение со Snowball) | активный |
| `_cross-cutting/report.md` | аудит: P1 correctness / P2 readability / P3 cost / P4 speed по скиллам | активный |
| `_cross-cutting/reviews-INDEX.md` | сводка per-skill ревью + **топ-10 приоритетов** | активный |
| `_cross-cutting/_cross-skill.md` | D3/D4-нарушения, schema-mismatch, мёртвые shared-refs, mojibake | активный |
| `_cross-cutting/_claude-memory-anomalies.md` | реальные аномалии в `Claude-Memory/` | активный |
| `<домен>/reviews/<скилл>.md` | детальные P1–P4 находки по одному скиллу | активный |
| `_cross-cutting/scripts-optimization-report.md` | возможности вынести логику в Python | предложения |
| `memory/save-to-library-fixes.md` | 3 готовых к применению дефекта Workflow E | готово к правке |
| `portfolio/html-comments.md` | замечания пользователя по вьюеру | накопительный |
| `portfolio/piv-run-2026-08-15-review.md` | разбор прогона integrated-view: пять дефектов контура + приоритезированный список правок (§5) | готово к правке, в TODO не перенесено |
| `portfolio-data-loader-updates.md` | сводка правок загрузчика 2026-10-20…21: moex_quotes на снапшоте v2, версии снапшота `.versions/`, сверка количества облигаций со сделками, итоги PDL-RECON | справочно; открытое — §6 |
| `portfolio/weekly-reviews-audit-2026-10-20.md` | независимый аудит обзоров акций и облигаций 01.10–16.10: акции 0/7/10, облигации 1/7/12 (критично/существенно/мелочь) — базовая линия для повторного аудита | перенесено в TODO (`#wr-1016-audit`) |
| `portfolio/rpa-17-field-paths-audit.md` | аудит ru-portfolio-advisor: 102 пути данных из документации сверены со snapshot v2 — 12 несуществующих, 6 null-на-снапшоте, 31 легитимно из другого артефакта | ✅ отработано (RPA-17/PDL-13 в TODO закрыты 19.08); держим как метод и историю дефекта |
| `tools/research/pss-4-sanctions/` | код и сырой вывод калибровочных замеров санкционного фактора | доказательная база, не бэклог |
| `portfolio/HTML_VIEW_TODO.md` | задачи вьюера | в основном закрыто |
| `portfolio/claude-code-spec-conditions-and-reconcile.md` | спека Conditions SSOT + reconcile enforcement (Part A/B) | реализовано (CR-A/CR-B в TODO) |
| `_cross-cutting/plan.md` | план содержит встроенные TODO-секции по фазам | roadmap |
| `_cross-cutting/data-structures/decision.md` | цикл машиночитаемости: статус шагов 0–17 (§4), список переключения (§4.2), риски (§5), за скобками (§6) | активный до шага 17 |

> **Конвенция:** новые задачи заводить в `TODO.md` с ID-префиксом скилла.
> Per-skill ревью и report.md — диагностический источник, из них задачи
> переносятся в `TODO.md`.

---

## 5. Скилл-навигатор `/investment-docs`

Проектный скилл (`.claude/skills/investment-docs/`, рядом с `travel-stage-builder`).
Передаёшь ему имя скилла или домен — он по разделу 3 этого README грузит нужное подмножество докумен­тации и
готов к правке/улучшению/обсуждению, не читая чужие домены.

```
/investment-docs ru-portfolio-advisor      # доки одного скилла
/investment-docs portfolio                  # весь домен
/investment-docs portfolio-integrated-view portfolio-scenario-stress   # несколько скиллов
```
