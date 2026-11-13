# Спецификация: `portfolio-coherence-audit` (Fable deep-pass, сфера 3)

**Версия спеки:** 0.1 (draft к согласованию)
**Целевая модель скилла:** `claude-fable-5`
**Статус в пайплайне:** новый верхний слой (meta), read-only, потребляет артефакты существующего пайплайна.

---

## 1. Зачем и место в пайплайне

Твой пайплайн уже даёт синтез: `portfolio-integrated-view` (Opus 4.7, mandatory) собирает snapshot + stress + weekly-reviews + macro-chain в `integrated-view@1.3` — 10 секций, joint equity-vs-bond spread через `macro_dependency`, propagated CI, disagreement-флаги (🟢/🔴/👁), tail-risk (§9), `predictions_for_review`.

**Проблема, которую integrated-view структурно не решает:** он агрегирует строго *по объявленным рёбрам схемы*. Он не ищет:

1. **Кросс-артефактные противоречия допущений.** stress-test закладывает один путь ставки в `factors_by_horizon`; bond weekly-review — свой implied rate view в `catalyst[].macro_dependency`; macro-chain L1 (`central_estimate_l1_*`) — третий. integrated-view проверяет staleness/schema/share-basis/p-нормализацию, но **не сверяет сами допущения между собой** на семантическую согласованность.
2. **Off-diagonal факторные взаимодействия** — «рёбра, которых в DAG нет». Per-position `factor_betas` (equity) и `bond_carry` (Layer 2) агрегируются как независимые ноги. Общий макро-фактор, двигающий и бету крупной акции, и carry облигационной лестницы в одну сторону, даёт скрытую концентрацию **сверх** `concentration_ratio`.
3. **Совместный хвост** — tail, возникающий только при одновременном сваливании equity- и bond-ног через общий фактор, а не в каждой ноге по отдельности.
4. **Ред-тим собственного вывода.** integrated-view по своим правилам «никаких новых суждений» — он не атакует свой же equity-vs-bond вердикт.

**Ниша deep-pass:** держать *все* артефакты разом (включая сам `integrated-view-<date>.md`) и выдавать слой когерентности: противоречия → немоделированные взаимодействия → red-team устойчивости вывода. Он сидит **на слой выше** integrated-view и потребляет его как вход, а не конкурирует с ним.

---

## 2. Почему именно Fable, а не Opus

Порог, который Opus/Sonnet не берут надёжно, — **whole-corpus coherence + sustained autonomy**: одновременно удержать snapshot + stress (все позиции × горизонты × 7 факторов) + два weekly-review + L1/L2 macro-chain + integrated-view + сценарии, и рассуждать о взаимодействиях между *далёкими* кусками с самопроверкой. Это ровно тот класс задач, где отрыв Fable растёт нелинейно с длиной и сложностью ([Anthropic](https://www.anthropic.com/news/claude-fable-5-mythos-5)).

Тест на оправданность: **если задача помещается в один заход Opus без потери когерентности — она не для Fable.** Здесь не помещается: входов много, они разно-схемные, и ценность именно в перекрёстных связях.

---

## 3. Роутинг и каденс (трёх-тир для этой цепочки)

| Тир | Модель | Скиллы | Каденс |
|---|---|---|---|
| Сбор | Sonnet 4.6 / Haiku 4.5 | `portfolio-data-loader`, `macro-ru-watcher`, `forecast-monitor` | еженедельно/по событию |
| Анализ | Opus 4.7 | `portfolio-scenario-stress`, `portfolio-integrated-view`, `macro-forecast-chain` | еженедельно/ежемесячно |
| **Meta-когерентность** | **Fable 5** | **`portfolio-coherence-audit`** | **ежемесячно или на смене режима** |

Fable-прогон **дорогой и редкий**: не еженедельно. Триггеры — смена макро-режима (шаг ставки, санкционный сдвиг, слом нефти) или плановый месячный аудит. Всё еженедельное остаётся на дешёвых тирах.

---

## 4. Входные контракты

Все пути — от корня `Claude-Memory/` (Synology primary: `~/Library/CloudStorage/SynologyDrive-home/Ext_gDrive/Claude-Memory/`).

**Обязательные:**

| Артефакт | Файл | Схема | Staleness gate |
|---|---|---|---|
| Снапшот (числа-истина) | `Portfolio/snapshots/portfolio-<date>.json` | `schema_version 2.0` | ≤14 дн |
| Стресс-тест | `Portfolio/stress/stress-<date>-<slug>.{md,yaml}` | `schema_version 2` | ≤90 дн |
| Обзор акций | `Portfolio/weekly-reviews/weekly-review-stock-<date>.{yaml,md}` | `weekly-stocks-review`, `schema_version 2` | ≤14 дн |
| Обзор облигаций | `Portfolio/weekly-reviews/weekly-review-bond-<date>.{yaml,md}` | `weekly-bonds-review` | ≤14 дн |
| Синтез (аудируемый) | `Portfolio/integrated-views/integrated-view-<date>.md` | `integrated-view@1.3` | ≤14 дн |

**Опциональные (overlay):** `macro-chain/macro-marginal-<date>.yaml` (L1 EV, ≤30 дн), `macro-chain/macro-scenarios-<date>.yaml` (L2 `by_scenario`), `scenarios/*.yaml` (Shell 2×2), `forecasts/*.yaml` (только Tier-2 conditional), `INDEX.md` (trust-матрица), `sector-overrides.yaml` (`fund_classification`).

**Generation-consistency gate (критично).** Кросс-артефактное рассуждение — мусор, если входы из разных состояний портфеля. Скилл нормализует ссылку на снапшот к дате (YYYY-MM-DD) из каждого артефакта — `snapshot.as_of_date`, `stress.portfolio_snapshot_id`, `weekly.snapshot_id`, `integrated_view.inputs.snapshot_date` — и сверяет их. Расхождение → **HARD STOP** с явным перечнем, какой артефакт разошёлся и что перезапустить. Это строже, чем snapshot-drift warning в integrated-view (реальный пример: снапшот 07-03 при стрессе/integrated-view на 07-02 → STOP).

**Факторный набор не хардкодится:** читается из `factor_definitions` стресс-теста (7 канонических факторов + определения). Так скилл не ломается при смене факторной модели.

---

## 5. Двухстадийность: Opus-prep → Fable-reasoning

Ключевой принцип подготовки: **всё детерминированное и дешёвое делается ДО Fable.** Fable дорог и его сила — суждение, а не парсинг. Поэтому пайплайн разрезан на две стадии, между ними — единый валидированный артефакт `coherence-input-bundle-<date>.json`.

### Stage P — подготовка (Python, без LLM; оркеструет Opus/Sonnet)

Скрипт `build_coherence_bundle.py`. Никакого рассуждения — только механика, которую нельзя доверять дорогой модели «на глаз»:

- **P1. Ingest & freshness.** Загрузить обязательные входы; staleness + generation-consistency gate (см. §4). При провале — STOP с машинной диагностикой (какой артефакт устарел / какой `snapshot_id` разошёлся). Fable вообще не запускается на мусоре.
- **P2. Assumption ledger.** Извлечь *все допущения* и нормализовать к {факторы × горизонт}: `factors_by_horizon` из stress; `catalyst[].macro_dependency` из обоих weekly; `central_estimate_l1_*` (L1) и `by_scenario` пути (L2) из macro-chain; оси сценариев. Факторный набор — из `factor_definitions` стресс-теста, не хардкод.
- **P3. Contradiction candidates (предрасчёт).** Для каждого фактора×горизонта собрать значения из всех артефактов в одну строку и посчитать разброс (min/max/spread, знак-конфликт). Это **не суждение** — это выкладка «кто что заложил», по которой Fable решает, что существенно.
- **P4. Factor-overlap matrix (предрасчёт).** Матрица пересечения: для каждого фактора — суммарная equity-экспозиция и bond-экспозиция, обе как Σ `per_position.factor_betas`·`weight_pct`, раздельно по классу актива (облигации в `per_position` **тоже имеют `factor_betas`** → bond-нога считается честно, не только carry). Строки с ненулевой экспозицией в обеих ногах и `direction: reinforcing` — кандидаты в off-diagonal (скрытая концентрация); `offsetting` — естественный хедж. Только числа; межфакторное ранжирование (беты разных единиц) — за Fable.

Выход Stage P: `coherence-input-bundle-<date>.json` — самодостаточный, провалидированный, нормализованный. Fable читает **только его** + бриф, не роясь в 6 разно-схемных файлах.

### Stage R — рассуждение (Fable 5)

Fable получает bundle + фиксированный бриф (§SKILL.md) и делает только неустранимое:

- **R1. Consistency verdict.** Из P3-кандидатов выбрать *существенные* противоречия и объяснить, почему они ломают/не ломают equity-vs-bond вывод. Пример: «bond-review закладывает ставку ↓ к H12, equity-stress — flat, macro-chain L1 — ↑100 б.п.; спред держится на неразрешённом допущении».
- **R2. Off-diagonal interpretation.** Из P4-кандидатов — какие пересечения реальны экономически, оценить совместный эффект и скрытую концентрацию сверх `concentration_ratio`.
- **R3. Self-check / red-team** (внутренний HST: Pre-mortem + Devil's Advocate + Reversibility). Атаковать equity-vs-bond вывод integrated-view. Вердикт устойчивости **Высокая/Средняя/Низкая** + единственное несущее допущение, чей flip ломает вывод, + фальсификатор.
- **R4. Emit** `coherence-audit-<date>.md` (см. §6).

**Что это даёт:** (1) Fable точнее — вход чистый и однозначный; (2) дешевле — не жжёт токены на парсинг; (3) воспроизводимо/тестируемо — bundle инспектируется отдельно; (4) ошибки локализованы — garbage-in ловится в P1 до траты денег на Fable.

**Железное правило (обе стадии):** **рассуждаем над валидированными числами, но не пересчитываем их.** XIRR/YTM/ΔP&L берутся из снапшота и стресс-теста как есть. Никакой арифметики LLM поверх точных данных; Stage P только *переупаковывает* числа, не выводит новые.

---

## 6. Выходной артефакт

Файл: `Portfolio/coherence-audits/coherence-audit-<date>.md`
Схема frontmatter: `coherence-audit@1.0`

**Frontmatter:** `schema_version`, `snapshot_id`, `inputs[]` (файл + возраст), `consistency_status` (ok/degraded/stop), `robustness_verdict` (Высокая/Средняя/Низкая), `load_bearing_assumption`, `review_date`.

**Секции:**

- **§0 Provenance & generation-consistency.** Какие артефакты, даты, `snapshot_id`, вердикт согласованности поколения.
- **§1 Cross-artifact contradiction ledger.** Таблица: допущение | артефакт A | артефакт B | Δ | severity (ВЫС/СРЕД/НИЗ).
- **§2 Off-diagonal factor interactions.** Фактор | equity-экспозиция | bond-экспозиция | совместный эффект | почему агрегация это упускает.
- **§3 Hidden concentration / joint tail.** Скрытая концентрация и совместный хвост сверх `concentration_ratio`.
- **§4 Red-team вывода.** Вердикт устойчивости equity-vs-bond + несущее допущение + фальсификатор.
- **§5 «Что уже покрыто downstream».** Явные указатели на integrated-view — чтобы **не дублировать** (spread, per-position α, tail-flags остаются там).
- **§6 Caveats** (ВЫСОКАЯ/СРЕДНЯЯ/НИЗКАЯ, provenance-tagged) + `review_date`.
- **`predictions_for_review`** (≥3): проверяемые следствия найденных противоречий, с `check_date`/`auto_checkable`/`check_what` — совместимо с `forecast-monitor`.
- **«Что НЕ показано»** — указатели на первоисточники для самостоятельной проверки (R5-стиль, как в integrated-view).

---

## 7. Границы (наследуются из house rules)

Скилл наследует твой стиль ограничений (как у всех аналитических скиллов):

- **Только анализ. Никаких buy/sell, никаких лотов/цен/лимиток.**
- **Read-only.** Не пересчитывает числа, не строит прогнозы, не запускает другие скиллы, не правит чужие артефакты.
- **Не подменяет** отсутствующий вход собственным мнением — при нехватке обязательного входа STOP.
- **Не дублирует integrated-view** — §5 явно перечисляет, что остаётся downstream.
- **ИИС-3** никогда не получает SELL/TRIM-подтекста (хотя buy/sell тут и так вне области).

---

## 8. Интеграция и сохранение

`save-to-library` — единственный писатель библиотеки (кроме D3-исключений), и я его править в этой сессии не могу. Два пути:

- **(A) По умолчанию — inline-only** (как `hypothesis-stress-tester`): результат выводится в чат, сохраняется только по явному «сохрани». Для сохранения нужен один из:
  - **(A1)** новый Workflow O в `save-to-library` + папка `Portfolio/coherence-audits/` (чистый путь, но требует однострочного дополнения твоего save-to-library — сделаешь ты);
  - **(A2)** прямая запись как D3-исключение (прецедент: `data-loader`, `macro-watcher` пишут напрямую) — самый низкофрикционный путь, скилл сам пишет в `Portfolio/coherence-audits/`.

**Рекомендация:** A2 по умолчанию (не трогаем save-to-library), с задокументированной опцией A1 на потом.

---

## 9. Открытые решения (твой выбор)

1. **Имя скилла:** `portfolio-coherence-audit` (по умолчанию) / `portfolio-deep-pass` / `portfolio-crossdep-audit`.
2. **Сохранение:** A2 прямая запись (по умолчанию) / A1 через save-to-library / inline-only.
3. **Каденс:** ежемесячно + на смене режима (по умолчанию) / только вручную.
4. **Скоуп self-check:** атаковать только equity-vs-bond вывод (по умолчанию) / шире — все находки §1–§3.

---

## 10. Риски и верификация

- **Garbage-in.** Без generation-consistency gate кросс-рассуждение бессмысленно → gate обязателен (§4), HARD STOP при расхождении `snapshot_id`.
- **Зависимость от наличия stress + integrated-view.** Если их нет за окно — скилл не запускается (это верхний слой, ему нужен нижний).
- **Стоимость.** Fable дорог → каденс редкий, потребляет готовые артефакты, ничего не пересчитывает.
- **Проверка на дубль.** Приёмочный тест: каждая находка deep-pass должна быть тем, чего **нет** в `integrated-view@1.3`. Если находка воспроизводима fixed-schema скиллом — она лишняя.
