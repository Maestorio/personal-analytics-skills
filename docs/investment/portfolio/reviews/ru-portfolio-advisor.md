# Skill: ru-portfolio-advisor

## Summary
Самый сложный по поверхности скилл: 8 режимов, 5 скриптов в data-loader (используются), trust-иерархия, integration с stress (Mode 8). Реальные `Portfolio/weekly-reviews/weekly-review-2026-05-06.yaml` (stocks) и `weekly-review-bond-2026-05-07.yaml` (bonds, Phase 10.4) присутствуют и валидны по `_shared-references/yaml-schemas.md §7/§7b`. Главные дефекты: (1) D3-правило (advisor НЕ пишет в `Portfolio/weekly-reviews/`) формально декларировано в SKILL.md, но не оформлено как absolute prohibition — риск self-write при невнимательной правке скилла; (2) bootstrap risk для `[lib] Invest Era` trust-профиля — при первом запуске Mode 3 советник не имеет trust-весов, fallback не описан; (3) inconsistency stocks/bonds dates (5/6 vs 5/7) без описанного workflow комбинированного режима 1+2.

## Correctness (P1)
- **[CLOSED]** [d3-formality] SKILL.md правила 19–22 указывают, что advisor генерирует YAML как code-block в чат, save-to-library пишет в файлы. Но **абсолютного запрета на Write-операцию из самого advisor** нет в явной форме (как, скажем, anti-pattern с восклицательным знаком).
  - Эффект: при правке скилла кто-то может добавить Write — система пропустит без warning'а.
  - Fix sketch: в anti-patterns SKILL.md: «АБСОЛЮТНЫЙ ЗАПРЕТ: advisor НЕ выполняет `Write()` в `Portfolio/weekly-reviews/`. Только save-to-library Workflow F».
  - _Закрыто: добавлен пункт «АБСОЛЮТНЫЙ ЗАПРЕТ (D3)» в секцию «Что не делать» SKILL.md._
- **[CLOSED]** [bootstrap-risk] `references/trust-hierarchy.md` использует `[lib] Invest Era` из auto-memory. Если профиля нет (первый запуск, новая сессия после очистки memory), Mode 3 (Rebalance) и аналогичные модули падают на дефолты.
  - Эффект: рекомендации опираются на дефолтную trust-таблицу (HIGH для облигаций, MEDIUM для макро, LOW для остального) без предупреждения.
  - Fix sketch: в `startup-checklist.md` Шаг 0: проверить наличие `[lib] {expected-source}` в memory; если нет — phrase «trust-профиль не загружен — использую консервативные дефолты».
  - _Закрыто: добавлен Шаг 0.1 в `startup-checklist.md` с проактивной проверкой и явным предупреждением в шапке ответа._
- **[CLOSED]** [workflow-mismatch] `weekly-review-2026-05-06.yaml` (stocks) и `weekly-review-bond-2026-05-07.yaml` (bonds) — даты разные. Если режимы 1 и 2 запускаются в одном сеансе, даты должны совпадать. SKILL.md не описывает комбинированный workflow.
  - Эффект: integrated-view может смешать обзоры разных дней без предупреждения.
  - Fix sketch: в `output-templates.md` ввести Template 1+2 для комбинированного запуска; либо явно сказать «obзоры stocks/bonds могут быть в разные дни — integrated-view обязан проверить, что обе даты ≥ snapshot_date − 14d».
  - _Закрыто: добавлен блок «Синхронизация дат при комбинированном Mode 1+2» в секцию `--save-to-library` SKILL.md._
- **[CLOSED]** [mode8-fallback] Режим 8 (Stock Quality Forward Review) ожидает свежий stress-файл. SKILL.md строка 179 предупреждает о старении (>30d), но не определяет, что делать дальше: fallback на «последний прогноз ставки ЦБ из NEWS», отказ выполнять режим, или выполнять с пометкой «макро-контекст устарел».
  - Эффект: при отсутствии свежего stress пользователь получит непроверяемый ответ.
  - Fix sketch: «если stress > 30d → требуется явное подтверждение пользователя или запуск `portfolio-scenario-stress`; иначе режим 8 отказывает».
  - _Закрыто: soft warn заменён на трёхуровневый fallback: >30d запрос подтверждения; >30d + --allow-stale продолжить с пометкой; >60d отказ._

## Readability (P2)
- **[→ TODO RPA-1]** 330 строк SKILL.md + 17 references — большой объём. Структура (8 режимов × правила 1–22) читается, но требует первого прохода для запоминания.
- **[→ TODO RPA-2]** Trust-иерархия (правила 19–22) ссылается на `[lib] {source}` — но процедура «как этот lib появляется» не описана прямо в SKILL.md (она в memory-sync workflow).
- **[HALLUCINATION]** Per-stock catalyst forecasts: SKILL.md упоминает `Portfolio/forecasts/` как opt-in выход режима 8. Реальная директория содержит только подпапку `portfolio-level/` — per-stock-файлов нет. Возможно, режим 8 чисто чат-выход. Уточнить.
  - _Галлюцинация: SKILL.md нигде не упоминает `Portfolio/forecasts/` как выход Mode 8. Это upstream-директория, не output скилла. Mode 8 — чисто чат-ответ._
- **[HALLUCINATION]** IE-данные: SKILL.md правило №10 «строго из `IE New / IE Old` в файле пользователя», `weekly-review-stock` schema: `ie_actual.per_ticker`. Откуда брать IE-веса — из `ie_actual` snapshot или из файла пользователя? Источник истины не указан.
  - _Галлюцинация: SKILL.md правило №10 (строка 50) явно указывает: «строго из `ie_actual.per_ticker` в snapshot». Источник истины определён._

## Cost (P3)
- Sonnet 4.6 базово, Opus 4.7 для Mode 8 и многорежимных. `model-routing.md` указывает ожидаемое сокращение токенов на 30–40% после маршрутизации.
- **[→ TODO RPA-4]** `model-routing.md` упоминает: новый токенизатор Opus 4.7 даёт +35% токенов, что нивелирует экономию. SKILL.md этого не упоминает.
- `moex_quotes.py` батчит до 10 SECID — экономно.

## Speed (P4)
- Mode 1: parsing snapshot + MOEX-quotes + IE-фильтр ~5–10 сек.
- Mode 8 (Opus 4.7) на 20+ тикерах + макро-overlay: 30–60 сек.
- **[→ TODO RPA-3]** Hard timing для скриптов в SKILL.md не приведены.

## Cross-skill / contract
- D3 — см. issue #1. Декларативно соблюдается; формально не запрещено.
- Upstream:
  - `portfolio-data-loader/portfolio-{date}.json` — обязателен (snapshot).
  - `portfolio-scenario-stress/stress-*.yaml` — для Mode 8.
  - `_shared-references/yaml-schemas.md §7/§7b` — schema validation.
- Downstream:
  - `save-to-library/Workflow F` — пишет stocks-review; F1b — bonds-review (см. `save-to-library` audit: F1b отсутствует в dispatch-таблице — это смежный bug).
  - `portfolio-integrated-view` — потребляет оба обзора.
- 7 hardcoded paths согласованы с `transport-layer.md` ✓.
- Phase 10.4 (bonds) интегрирован: `weekly-review-bond-{date}.yaml` пишется, schema соответствует §7b.

## Verified against artifact
- `~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/Portfolio/weekly-reviews/weekly-review-2026-05-06.yaml` (52 KB, stocks):
  - `schema_version: 1`, `type: weekly-stocks-review`, `horizon_months: 20` ✓
  - `per_stock` блоки с `fundamental_score`, `div_yield_12m_pct`, `catalyst[]`, `advisor_verdict`, `verification_priority` ✓
- `weekly-review-bond-2026-05-07.yaml` (56 KB, bonds, Phase 10.4):
  - `type: weekly-bonds-review`, per_bond с `credit_quality`, `catalyst[]`, `advisor_verdict`, `verification_priority` ✓
  - `summary.weighted_ytm_pct`, `by_type_pct`, `maturity_ladder_pct` ✓
- `weekly-review-2026-05-05.md` (6.6 KB) — markdown human-facing версия, дата на день старше yaml-stocks (нормально, если writer запускался 6-го с данными от 5-го).
- `Portfolio/forecasts/portfolio-level/` присутствует, но содержит только подпапку — per-stock catalyst forecasts отсутствуют.
- `Portfolio/snapshots/portfolio-2026-05-05.json` — основной input, формат `schema_version: "2.0"` ✓.

## Update 2026-08-20: gate-aware sizing доставлен как исполняемый шаг

Правка 19.08.2026 внесла методику неподвижной точки (`T* = F/(1−S)`) в референсы прозой и в тот же день промахнулась мимо доставки (`docs/investment/2026-08-19-retro_calibration-missed-fixed-point-rule.md`). Волна `docs/investment/portfolio/gate-aware-sizing-rollout-plan.md` (T1–T7, 2026-08-20) закрыла доставку тремя слоями:

- новый CLI `scripts/gate_aware_sizing.py` снимает с LLM сбор входов из снапшота, арифметику (импортирует `constraint_engine.compute_fixed_point_target`) и формулировку итогового текста (`--lint-draft` — pre-emit проверка черновика);
- правило №24 внесено в `SKILL.md` (файл, читаемый всегда), конкурирующая inline-сводка процесса удалена;
- `analysis-process.md` Шаг 6.1, `output-templates.md` (верхнеуровневый раздел «Сколько можно докупить», pre-emit checklist), `stocks/bonds/funds-methodology.md`, `rebalance-framework.md` — согласованная граница применимости («только акции») и ловушка `goals_matrix.Изменение` закрыта в трёх местах.

Тест `skills/ru-portfolio-advisor/tests/test_gate_aware_sizing.py` (38 проверок, класс `TestDocsGuard` сторожит размещение правки во всех перечисленных файлах) — зелёный. Отложено (нужен отдельный план): развести `weekly-review-schema-v1.md` на `planned` vs `IE` таргет (`gate-aware-sizing-rollout-plan.md` §6).

## Update 2026-08-20 (2): чтение стресса доведено до Mode 3 (RPA-20)

Дефект `[mode8-fallback]` выше закрывался в предположении, что stress — забота одного
режима. С 19.08 это неверно: Mode 3 читает стресс для обоснования L1-redirect, но
процедурный файл остался `mode-8-stress.md` — «Режим 8» в заголовке и «в остальных
режимах (1-7) stress-файл не нужен» в последней строке. Модель, запуская Mode 3 по
указанию SKILL.md, открывала инструкцию, отрицающую саму себя.

- `references/mode-8-stress.md` → `references/stress-reading.md`, переписан под оба
  режима; лестницы свежести разведены: Mode 8 при >60 дней отказывается, Mode 3
  откладывает только L1-redirect и выдаёт остальной режим полностью.
- Новый CLI `scripts/stress_digest.py` — свежесть и вердикт по режиму, множители якорных
  горизонтов (`horizon_ends` — SSOT; ключ `hNN` не равен числу месяцев), EV и tail по
  акциям с ренормировкой на покрытые, `bond_carry` по держимым выпускам, сверка
  поколения со снапшотом, пропорция redirect, готовый блок с провенансом.
- Попутно закрыты два арифметических дефекта шаблона Mode 3: множитель дивидендов
  `× 24/12` при реальных 22,5 мес горизонта (завышение ~7%) и ручной пересчёт
  bond-стороны §6.2 при готовом блоке `bond_carry` в самом стрессе.
- Горизонт решения зафиксирован владельцем: primary — **h12**, h24 второй колонкой
  (SKILL.md, шаблон и фреймворк расходились).

Тест `skills/ru-portfolio-advisor/tests/test_stress_digest.py` (70 проверок, включая
живую регрессию на стрессе 15.08 против снапшота 19.08 и `TestDocsGuard` на все
перечисленные файлы) — зелёный. Разбор — `docs/investment/TODO.md#rpa-20`.

## Update 2026-08-20 (3): план владельца доведён до артефакта обзора (RPA-19)

Схема обзора несла единственный таргет веса — цель Invest Era, — как будто это цель
владельца. Живые числа (снапшот и обзор 15.08): портфель отклоняется от плана владельца
максимум на 1,34 пп, от IE — до 5,7 пп, и фиксировалась вторая картина. У 7 из 22 бумаг
расхождения не было вовсе (`weight_divergence_pp: null` — их нет в модели IE), при живом
плане по всем семи: треть книги в артефакте без единого числа о положении к цели.

- Три новых поля: `weight_user_planned_pct`, `weight_divergence_vs_planned_pp` (primary),
  `weight_divergence_vs_ie_pp` (secondary). `weight_divergence_pp` остался deprecated-
  алиасом ради обзоров до 20.08 и вьюера. Фантомный `ie_divergence_pp` (описан в схеме,
  никем не эмитился и не читался) убран.
- Валидатор впервые **сверяет арифметику** расхождений (допуск 0,05 пп) и равенство
  deprecated-алиаса — до этого числа проверялись только на присутствие и тип.
- Порог эскалации Mode 8 (`> +5 пп` → Mode 4), сортировка таблицы Mode 8 и база сравнения
  в BUY-разделе переведены на план владельца; IE оставлен secondary-сигналом.
- Карточка тикера во вьюере показывает план и расхождение с ним перед IE-строкой, шкала
  «Вес vs целевой» получила вторую метку. План берётся из снапшота, поэтому старые обзоры
  тоже рисуются с плановой долей.
- Сохранённые обзоры не мигрированы (решение владельца): артефакт — запись того, что было
  известно на дату прогона.

Тесты: `test_assemble_artifact.py` 469 → 477, `test_build_weekly_stock_stub.py` 22 → 28.
Попутные находки вынесены в `docs/investment/TODO.md#rpa-21` (мёртвый счётчик
`skipped_frozen_us`; валидатор требует непустой `weight_real_pct`, который продюсер умеет
отдать null). Разбор — `docs/investment/TODO.md#rpa-19`.
