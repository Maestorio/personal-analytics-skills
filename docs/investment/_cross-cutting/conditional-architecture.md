# Двухслойная архитектура прогнозов (conditional architecture)

> Вынесено из CLAUDE.md 2026-08-12 (диета контекста, `docs/compactisation.md`).
> В корне осталась сводка с жёстким ядром; **этот файл — полная спецификация**.
> Синхронизация: правишь архитектуру → правь и сводку в CLAUDE.md.


Зафиксирована 2026-05-08. Решает 4 дефекта старой системы: веса сценариев жили в чате без следа, conditional values смешивались с marginal, источники не атрибутировались по сценариям, stress-тест использовал «mixed-worlds» факторы (Brent из Sc-A worldview + USD/RUB из Sc-D в одном бандле).

> **V2-CUTOVER (cutover-date 2026-08-03):** библиотека weekly-review/stress целиком
> schema 2 — 17 живых v1-файлов мигрированы wrap-as-single-horizon
> (`skills/portfolio-scenario-stress/scripts/migrate_v1_to_v2.py`, бэкапы
> `Portfolio/_bak-cutover-2026-08-03/`), 4 ранних эксперимента —
> `Portfolio/stress/_archive-pre-v2/`. Валидаторы save-to-library принимают
> **только schema 2** (v1 → blocking). Остаток co-existence: v1-обёртка в
> `aggregate_positions.py` (мертва на живых данных, снятие — отдельный заход)
> и normalize* вьюера (живая совместимость эмиссий, НЕ v1-шим — DRIFT-1 отменён).
> Сводка: `docs/investment/TODO.md#v2-cutover`.

#### Два слоя

```
LAYER 1 — MARGINAL FORECASTS (independent)
  • один FCA на фактор, trust-weighted по источникам
  • источники могут implicit противоречить друг другу — это нормально
  • используется для: weekly-review, EV, factor betas
  • хранится в: forecast.central_estimate + macro-marginal-{date}.yaml

LAYER 2 — SCENARIO BUNDLES (coherent)
  • 4 сценария, в каждом все факторы согласованы под worldview сценария
  • используется для: stress-test, robustness check, hedge sizing
  • хранится в: conditional_on_scenarios.by_scenario + macro-scenarios-{date}.yaml
```

#### Двойной marginal в forecast YAML

```yaml
forecast.central_estimate                    ← Layer 1 marginal
                                                trust-weighted FCA, scenarios игнорируются
                                                ОСНОВА портфельных EV-решений

conditional_on_scenarios.marginal.values     ← Layer 2 marginal
                                                probability-weighted от by_scenario
                                                диагностика расхождения, НЕ основа решений
```

`coherence_diagnostic` блок фиксирует расхождение (divergence_pct): `<5%` = LOW, `5–15%` = MEDIUM, `>15%` = HIGH. Расхождение нормально при asymmetric coverage или доминирующем HIGH-trust источнике.

`portfolio-scenario-stress` берёт **`by_scenario` напрямую** (Layer 2).
`weekly-review` берёт **`forecast.central_estimate`** (Layer 1).
Layer 2 marginal — только диагностика.

#### 8 архитектурных решений (D1–D8)

| # | Решение |
|---|---------|
| **D1** | `scenario-builder` выдаёт `probability: 0.25` каждому по default (Pure Shell). Пользователь правит вручную в SSOT (`scenarios/{name}.yaml`). Opt-in расчёт через `joint_from_axes(ev_x, ev_y, rho=0)` — только при явном запросе |
| **D2** | `expected_pl_pct`/`expected_pl_rub` удалены из default output `portfolio-scenario-stress`. Opt-in: флаг `--include-ev` |
| **D3** | Сценарий «Unaccounted» удалён, заменён на `out_of_frame_caveats` блок |
| **D4** ⚠ deprecated | ~~Trust расширен до 3D (`marginal`/`world_picking`/`conditional`)~~. **Уточнено D8 (2026-05-10):** trust остаётся плоским 1D; `implicit_geopolitical_scenarios` отозвано. Backward-compat код `flatten_trust` оставлен как noop |
| **D5** | scenario_id формат — короткий `A` вместо `Sc-A` |
| **D6** | ρ correlation default 0 (независимость осей). Оценка через `correlation-rubric.md` |
| **D7** | Pure Lazy aggregation: Layer 2 marginal пересчитывается только при явном `RECALIBRATE`. Default soft (auto-recalculate с warning), `--strict` блокирует при stale |
| **D8** | Источниковые профили (`domains/{domain}/{source}-*.md`) остаются плоскими (1D `trust`). Сценарная атрибуция источников **не хранится в profile** — делается динамически в момент FCA по контенту прогноза (см. `forecast-confidence-applier/SKILL.md` Шаг 1.5B). Это сохраняет скиллы сценарно-независимыми и предотвращает stale-проблему при смене сценарной оси |

#### Три типа updates

| Тип | Триггер | Что меняется | Время |
|-----|---------|--------------|-------|
| **A — Weight-only** | leading_indicator сработал, смена убеждений | только Layer 2 marginal + labels, через RECALIBRATE | ~30 сек |
| **B — Factor baseline** | premise фактора сломалась | `by_scenario` одного фактора + Layer 1 marginal (1 FCA) | ~30 мин |
| **C — Structural** | оси сценарной матрицы устарели | вся scenario matrix + все conditional FCA | 1–2 дня |

#### Три типа прогнозов

| Тип | Когда | Структура YAML |
|-----|-------|----------------|
| **1 — Isolated** | бинарное событие, другой домен, вне сценарных матриц | `isolated: true`, нет `conditional_on_scenarios` |
| **2 — Scenario-conditional** | фактор входит в макро-цепочку портфеля | `conditional_on_scenarios.source_matrix: scenarios/…yaml` |
| **3 — Multi-matrix** | несколько матриц (Phase 8+, не реализовано) | не поддерживается в Phase 1–5 |

Каждый forecast ссылается **максимум на одну** scenario matrix. При нескольких логически релевантных — выбирается dominant.

#### SSOT весов и RECALIBRATE

Действующие сроки прогнозов и стресса — файл сайта `scenarios/horizons.json` (`horizons@1`, решение 2026-11-06): его пишет только сайт («Стресс» → «Настройки стресса»), скиллы прогнозов и стресса берут даты горизонтов из него и сами их не меняют; нет файла — сроки прошлого стресса. Действующие веса сценариев — файл сайта `scenarios/stress-weights-{матрица}.json`: владелец задаёт их на странице «Стресс» на сроки стресса (решение 2026-11-06). Веса на даты прогнозов получаются линейной интерполяцией по дням между сроками сайта, вне сроков — значение ближайшего (`_shared-references/scenario_weights.py`). Пока файла сайта для матрицы нет, действуют веса матрицы — `scenarios/{name}.yaml` → `matrix.scenario_triggers[*].probability` / `p_by_horizon`; после появления файла сайта они остаются исходными весами на дату матрицы. Веса **не дублируются** в forecast YAML или macro-chain файлах.

`macro-forecast-chain --mode RECALIBRATE` [или `--strict`]:
1. Читает веса: файл сайта, если он есть для матрицы, иначе матрица
2. Пересчитывает Layer 2 marginals во всех forecast YAML
3. Обновляет modal/hedge ranking в stress YAML
4. НЕ запускает FCA, НЕ меняет Layer 1, НЕ трогает `by_scenario`
5. Укладывается в <30 сек

#### Сценарная атрибуция источников (D8 — динамическая)

После решения D8 (2026-05-10) сценарная атрибуция источников **не хранится** в `domains/{domain}/{source}-*.md`. Вместо этого:

- При построении **Type 2 conditional FCA** скилл `forecast-confidence-applier` (Шаг 1.5B) **динамически классифицирует** источники по scenario camps на основе контента конкретного прогноза.
- Атрибуция и reasoning записываются inline в forecast YAML: `by_scenario.{X}.sources_used = [{source_id, camp_weight, reasoning}]`, `provenance: inferred_from_content`.
- При смене сценарной оси (например, Iron Curtain → Multipolarity через 2 года) переписывать source profiles не нужно — достаточно обновить scenario YAML, и при следующем FCA источники будут переклассифицированы.

**Зачем это лучше static-атрибуции (отозвано D4):**
- Source profile стабилен, не зависит от текущей scenario matrix.
- Эволюция worldview источника (BCS-2024 ≠ BCS-2026) автоматически отражается.
- Скиллы остаются сценарно-независимыми.

#### Forecast chains (структурные vs функциональные зависимости)

Через блок `upstream_snapshot:` в forecast YAML можно фиксировать **структурную** зависимость («Brent-прогноз построен на снапшоте geopolitics-ru-west такой-то даты») для traceability и freshness через `macro-forecast-chain`.

**Чего пока нет:** функциональной инференции типа `USD/RUB = f(Brent)` — формулы между макрофакторами с весами. Значения всегда получаются через FCA на источниках по теме фактора, не через применение формулы к другому прогнозу.

Логические следствия с весами — потенциально будущая задача (`v4-E` в TODO). Возможные пути: историческая регрессия между факторами (24 мес MOEX), Bayesian VAR — требуют калибровки на накопленных данных.

