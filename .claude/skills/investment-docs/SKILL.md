---
name: investment-docs
description: >
  Навигатор по документации инвестиционно-прогнозного контура репозитория
  claude_skills (17 скиллов: portfolio / forecasting / memory). Передаёшь имя
  скилла или домен — скилл грузит ТОЛЬКО релевантную документацию (референсы,
  per-skill ревью, нужные TODO) перед правкой / улучшением / обсуждением, не
  читая чужие домены. Вызов: /investment-docs <скилл|домен> [ещё скиллы].
trigger: /investment-docs
---

# /investment-docs

Точечная загрузка документации перед работой над одним из 17 скиллов
финансово-прогнозного пайплайна. Цель — не читать лишнее: правя `forecast-monitor`,
не тянуть `methodology.md` портфеля.

Проектный скилл — живёт в `.claude/skills/` репозитория `claude_skills` (рядом с
`travel-stage-builder`), осмыслен только внутри него. Все пути ниже — относительно
корня репозитория.
**Корень документации:** `docs/investment/` — там `README.md` с полным каталогом
`skill→доки` (раздел 3) и индексом источников правок (раздел 4). README — SSOT
каталога; таблица ниже его дублирует для скорости, при расхождении верь README.

## Использование

```
/investment-docs ru-portfolio-advisor                      # один скилл
/investment-docs portfolio                                 # весь домен
/investment-docs portfolio-integrated-view forecast-monitor  # несколько скиллов
/investment-docs                                           # без аргумента → прочитать README и спросить
```

## Процедура

1. **Разобрать аргумент** в список скиллов:
   - имя скилла → он сам;
   - имя домена (`portfolio` / `forecasting` / `memory`) → все его скиллы;
   - несколько токенов → объединение;
   - пусто → прочитать `docs/investment/README.md` и спросить пользователя, по
     какому скиллу/домену готовить контекст.
2. **Всегда прочитать сначала:**
   - `docs/investment/README.md` (каталог + раскладка);
   - корневой `CLAUDE.md` (приоритеты, правила D3/сценарной независимости);
   - целевой `skills/<скилл>/SKILL.md` и его `references/` по мере надобности.
3. **Для каждого запрошенного скилла** прочитать его строку каталога (раздел 3
   README): доки-референсы + per-skill ревью + TODO-префиксы. Грузить только эти
   файлы. Чужие домены не открывать.
4. **Кросс-системное** (релевантно всем, читать при сомнениях/широкой правке):
   `docs/investment/_cross-cutting/{report.md, reviews-INDEX.md, _cross-skill.md,
   _claude-memory-anomalies.md, plan.md}` и `docs/investment/TODO.md`
   (фильтровать по TODO-префиксу скилла).
5. **Доложить, что загружено**, и ждать задачу (правка / улучшение / обсуждение).
   Если пользователь просил «проанализируй/проверь» — выдать анализ и ждать;
   править сразу только по «исправь/сделай».

## Карта домен → скиллы

| Домен | Скиллы | Папка |
|---|---|---|
| **portfolio** | portfolio-data-loader, ru-portfolio-advisor, portfolio-scenario-stress, portfolio-integrated-view, portfolio-coherence-audit | `docs/investment/portfolio/` |
| **forecasting** | macro-ru-watcher, macro-forecast-chain, forecast-collector, forecast-confidence-applier, forecast-monitor, scenario-builder, retrospective-forecast-audit, hypothesis-stress-tester | `docs/investment/forecasting/` |
| **memory** | save-to-library, memory-sync, revise-memory-local, revise-memory-remote | `docs/investment/memory/` |

## Каталог скилл → доки (зеркало README §3)

| Скилл | Доки-референсы | Ревью | TODO |
|---|---|---|---|
| ru-portfolio-advisor | portfolio/methodology.md, portfolio/new_met.md, portfolio-workflow-guide.md, portfolio/rpa5-fanout-calibration.md (журнал калибровки fan-out — дописывать после каждого прогона Mode 1/2), portfolio/bond-subtypes-plan.md (подтипы облигаций: 9 плановых корзин, лестница рейтингов §4.2, контракт полей), spec-gate-aware-sizing-trim-fix.md (trim-to-target, правило неразворота, лимиты концентрации; §10 решения владельца — читать ПЕРЕД §8) | portfolio/reviews/ru-portfolio-advisor.md | RPA-, W2, W3, CR-, DRIFT-, METH- |
| portfolio-data-loader | portfolio/methodology.md, portfolio-workflow-guide.md, portfolio/bond-subtypes-plan.md (подтипы облигаций: 9 плановых корзин, лестница рейтингов §4.2, контракт полей), portfolio/air-1-decision-journal-plan.md (AIR-1: теневые базы B0–B2 и журнал решений, решения владельца §7) | portfolio/reviews/portfolio-data-loader.md | PDL-, I-, D- |
| portfolio-scenario-stress | forecasting/conditional-forecasts-architecture.md, portfolio-workflow-guide.md, portfolio/factor-betas-explained.md, portfolio/stress-run-playbook.md (инструкция прогона), portfolio/stress-math.md (расчётный контракт), portfolio/sanctions-position-rubric.md (процедура назначения позиций), portfolio/pss-4-sanctions-calibration-plan.md (санкционный фактор: диагноз, исследование, форма модели), portfolio/scenario-weights-and-ci-plan.md (сценарные веса по горизонтам и факторный CI: пакеты PSS-6/P2-4/PSS-9/MFC-5, §8 — состояние работ и найденное попутно) | portfolio/reviews/portfolio-scenario-stress.md | PSS-, SS- |
| portfolio-coherence-audit | portfolio/portfolio-coherence-audit-spec.md (SPEC v0.1: ниша/двухстадийность/границы), portfolio-workflow-guide.md | — | — |
| portfolio-integrated-view | portfolio-workflow-guide.md, portfolio/methodology.md, forecasting/conditional-forecasts-architecture.md, TODO_design.md (бэклог вьюера, с 2026-10-12), portfolio/HTML_VIEW_TODO.md, portfolio/html-comments.md, portfolio/piv-run-2026-08-15-review.md (разбор прогона 15.08: верификация артефакта пересчётом + пять дефектов контура, включая мёртвый L1-overlay и `on_iis` вне контракта payload); INTEGRATION-DOCS/; tools/design-reference/ (дизайн-система HTML-viewer, Claude Design), portfolio/scenario-weights-and-ci-plan.md (сценарные веса по горизонтам и факторный CI: пакеты PSS-6/P2-4/PSS-9/MFC-5, §8 — состояние работ и найденное попутно) | portfolio/reviews/portfolio-integrated-view.md | IV-, V2-, V3-, PIV- |
| macro-ru-watcher | — | forecasting/reviews/macro-ru-watcher.md | MRW- |
| macro-forecast-chain | forecasting/conditional-forecasts-architecture.md, portfolio/scenario-weights-and-ci-plan.md (сценарные веса по горизонтам и факторный CI: пакеты PSS-6/P2-4/PSS-9/MFC-5, §8 — состояние работ и найденное попутно) | forecasting/reviews/macro-forecast-chain.md | MFC-, v4-E |
| forecast-collector | — | forecasting/reviews/forecast-collector.md | FC- |
| forecast-confidence-applier | forecasting/conditional-forecasts-architecture.md | forecasting/reviews/forecast-confidence-applier.md | FCA- |
| forecast-monitor | — | forecasting/reviews/forecast-monitor.md | FM- |
| scenario-builder | forecasting/conditional-forecasts-architecture.md | forecasting/reviews/scenario-builder.md | SB- |
| retrospective-forecast-audit | — | forecasting/reviews/retrospective-forecast-audit.md | CMA- |
| hypothesis-stress-tester | — | forecasting/reviews/hypothesis-stress-tester.md | HST- |
| save-to-library | memory/save-to-library-fixes.md | memory/reviews/save-to-library.md | STL-, MS-, CR-, DRIFT- |
| memory-sync | — | memory/reviews/memory-sync.md | — |
| revise-memory-local | — | memory/reviews/revise-memory-local.md | RML- |
| revise-memory-remote | — | memory/reviews/revise-memory-remote.md | RMR- |

**Префиксы задач без единственного владельца** — `CS-` (`_shared-references` +
все writing-скиллы), `METH-` и `DRIFT-` (методология и дрейф форматов, задевают
несколько скиллов сразу): грузить вместе с `TODO.md`, когда работа касается
общих контрактов, а не одного скилла.

Пути в таблице — относительно `docs/investment/`. Кросс-системные файлы
(`_cross-cutting/*`, `TODO.md`, корневой `CLAUDE.md`, `_shared-references/`)
релевантны всем скиллам и в строках не повторяются.

### Особый случай: факторные беты стресс-теста

Правишь что-либо, связанное с `factor_betas` или сценарными факторами
`sanctions`/`geopol` — **сначала** прочитай `skills/portfolio-scenario-stress/
references/sector-sensitivities.md`, секции «Контракт единиц» и «Позиция на
санкционной шкале». Там зафиксировано:

- **единицы бет** — п.п. цены на ОДНУ единицу фактора в его собственной единице;
  для `sanctions`/`geopol` единица = интенсивность 1.0, поэтому бета банков −35,
  а не −0.35. Долевая запись отличается ×100 и молча зануляет весь политический
  канал (реальный инцидент 2026-07: перевёрнутый порядок сценариев в двух живых
  артефактах). `compute_per_position.py` отказывается считать при заниженной
  шкале — гард `--political-scale-check`;
- **позиция на шкале** — `sanctions_position ∈ [0,1]`, асимметрия «ужесточение
  слабее, снятие сильнее» берётся из неё, а не из двух разных бет;
- **горизонтный путь** дилов: `{h6: …, h12: …, h24: …}`, скаляр на все горизонты
  помечается warning'ом.

Порядок прогона и что смотреть глазами — `docs/investment/portfolio/stress-run-playbook.md`.
Все формулы, единицы и границы одним местом — `docs/investment/portfolio/stress-math.md`.
Назначение и пересмотр `sanctions_position` — `docs/investment/portfolio/sanctions-position-rubric.md`
(процедура фиксирована намеренно: без неё через месяц другая сессия переопределит числа иначе).
Значения живут в `skills/portfolio-scenario-stress/references/sanctions-positions.yaml`; пересматривать —
скиллом `/sanctions-positions`, свежесть проверяет
`skills/portfolio-scenario-stress/scripts/check_position_freshness.py` (код 3 = устарели).
Разбор дефекта, исследование под калибровку и обоснование формы —
`docs/investment/portfolio/pss-4-sanctions-calibration-plan.md` (§1a — диагноз,
§6 — литература, §7 — собственные замеры, §3.3 — форма модели). Код и сырой
вывод замеров — `tools/research/pss-4-sanctions/`. Единицы факторов как
общесистемный контракт — `_shared-references/events-yaml-spec.md` §5.6.

## Принципы

- **Минимум контекста.** Грузить только доки запрошенных скиллов/домена.
- **README — SSOT каталога.** При добавлении скилла или дока обновлять
  `docs/investment/README.md` (разделы 3–4) и зеркальную таблицу здесь.
- **Язык — русский** (как и вся документация репозитория).
