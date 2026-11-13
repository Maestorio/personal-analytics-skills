# Шаг 1.5B — Сценарная атрибуция для Type 2 (conditional FCA)

> Вынесено из SKILL.md дословно при дроблении 2026-08-12 (этап 3, подготовка Max → Pro).

## Шаг 1.5B — Сценарная атрибуция для Type 2 (conditional FCA)

Применяется, когда строится `by_scenario` блок (4 значения для `A`/`B`/`C`/`D`) с конкретной сценарной матрицей. **Лагеря уже заданы** scenario YAML — это сами `scenario_id` с их triggers/assumptions. Работа FCA — НЕ изобретать новые камппы, а атрибутировать каждый источник к существующему `scenario_id`.

> **Решение D8 (CLAUDE.md):** атрибуция делается динамически по контенту прогноза, а не из static-поля в profile источника. См. `events-yaml-spec.md` §6.

> **Важно — Type 2 FCA выполняет ОБА шага 1.5A и 1.5B в одной сессии:**
> - 1.5A → Layer 1 marginal (`forecast.central_estimate` + Layer 1 confidence) для `ru-portfolio-advisor`
> - 1.5B → Layer 2 conditional (`by_scenario.{A,B,C,D}`) для `portfolio-scenario-stress`
>
> Источники грузятся **один раз**, `weighted_consensus.py` прогоняется **5 раз** (1 без фильтрации + 4 per scenario). Финальный forecast YAML содержит оба слоя + `coherence_diagnostic`. **Не сохранять Type 2 без `forecast.central_estimate`** — это нарушение спецификации events-yaml-spec.md §5 (см. anti-patterns ниже).

#### Алгоритм

1. **Загрузить scenario YAML** из `source_matrix` форекаста → список `scenario_id` с trigger conditions / assumptions.

2. **Для каждого источника** прочитать его forecast snippet + assumptions:
   - Какие триггеры/премиссы он закладывает?
   - С какой scenario это лучше всего согласуется?
   - Если есть `methodology_notes:` в profile — учесть как подсказку (не как директиву).

3. **Назначить:**
   - `primary scenario_id` (один — основной)
   - `secondary scenario_id` (опционально — если источник явно смешан, рассматривает 2 worldview параллельно)
   - `camp_weight`: `1.0` (одиночный) или `0.7/0.3` для primary/secondary
   - `reasoning`: 1–2 предложения про конкретный триггер прогноза, который привёл к выбору

4. **Если источник agnostic** (ЦБ-РФ модельный прогноз без геополитической премиссы, ВТБ-МИ, Morgan Stanley с глобальным макро) — атрибуция распределяется равномерно по всем сценариям (`camp_weight: 0.25` в каждом) либо передаётся как baseline-anchor отдельно.

5. **Никаких подкампов внутри сценария.** Если в Sc-A источники разошлись по величине ($50 vs $80) — это становится широким `range/CI` у Sc-A, а не отдельным анализом «bull within Sc-A».

#### Выход и сохранение

Для каждого `scenario_id` — список источников с эффективным весом (`trust_weight × camp_weight`) + reasoning. Это input для `weighted_consensus.py`, запускаемого **4 раза** (один FCA на каждый `scenario_id`).

Записывается в forecast YAML:
```yaml
by_scenario:
  A:
    values: { ... }
    provenance: inferred_from_content
    sources_used:
      - source_id: bks-2025-2026
        camp_weight: 0.7
        reasoning: "BCS прогноз $115 предполагает war + sanctions high → primary D, но в этом форекасте — сценарий A через ремарку «при resolution цены могут вернуться к $80»"
      - source_id: ...
    coverage_quality: MEDIUM
```

#### Anti-patterns

- **Жёстко прописывать атрибуцию в profile источника** — она должна жить в forecast, а не в memory (D8).
- **Смешивать камп-семантики 1.5A и 1.5B в одной карте лагерей** (например, «bull within Sc-A» как отдельный камп). 1.5A camps = направления (bull/bear); 1.5B camps = scenario_id (A/B/C/D). Они **параллельные**: для Type 2 forecast выполняются оба, но каждый со своей семантикой. Расхождение по величине внутри Sc-A отражается через широкий `range/CI`, не через дополнительный камп-анализ.
- **Сохранять Type 2 forecast YAML без Layer 1** (`forecast.central_estimate`). Это **неполный Type 2** — `ru-portfolio-advisor` лишается точечной оценки. Для Type 2: запустить 1.5A + 1.5B в одной сессии, получить Layer 1 (`forecast.central_estimate` + confidence) и Layer 2 (`by_scenario` + 4 prov), вместе с `coherence_diagnostic` (расхождение Layer 1 vs Layer 2).
- **Принимать в промпте готовые scenario interpretations или старые значения как anchor.** Если orchestrator (например, `macro-forecast-chain` в emit-plan) передал в промпт «Sc-A → нормализация Ормуза, brent восстанавливается» или «базовые данные: L1 weighted median $68/bbl» — это **leak оркестратора**, нарушение separation of concerns. Поведение FCA:
  1. Распознать leak (любая интерпретация неосевого фактора через сценарии или цитата старого ответа в промпте).
  2. Пометить в выводе warning: `⚠️ ORCHESTRATOR_LEAK: промпт содержит готовую interpretation/anchor — игнорирую, читаю scenario YAML самостоятельно`.
  3. Открыть scenario YAML по пути `source_matrix:` и прочитать triggers/assumptions **сам**.
  4. Атрибуцию источников делать на основе scenario YAML + forecast snippets, **не** на основе orchestrator'овой подсказки.

  **Исключение — axis_dependent факторы:** если фактор **сам является осью** сценарной матрицы (например, sanctions в geopolitics-матрице), значения оси per scenario определены by construction. Передача этих значений в промпт — не leak, а напоминание. Но и в этом случае FCA должен сверить с scenario YAML.

