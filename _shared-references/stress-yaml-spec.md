# Stress YAML — спецификация v1

Канонический формат `stress-{date}-{slug}.yaml` файлов из `Portfolio/stress/`.
Производитель — `portfolio-scenario-stress`. Потребители — `portfolio-integrated-view`,
`retrospective-forecast-audit`, `recalibrate.py`.

Полный шаблон с примерами — `skills/portfolio-scenario-stress/references/output-template.md`.
Этот файл — SSOT инвариантов и обязательных полей.

---

## 1. Top-level контракт (schema_version: 1)

| Поле | Тип | Обязательно | Описание |
|------|-----|------------|----------|
| `schema_version` | `int = 1` | ДА | Версия контракта |
| `type` | `"portfolio-stress-test"` | ДА | save-to-library классифицирует |
| `date` | `YYYY-MM-DD` | ДА | Дата stress-теста |
| `portfolio_snapshot_id` | `portfolio-{date}.json` | ДА | JOIN-ключ для integrated-view |
| `scenario_source` | enum | ДА | `scenario-builder \| forecast-confidence-applier \| hypothesis-stress-tester \| macro-forecast-chain \| manual \| hybrid` |
| `weight_type` | `"equal" \| "probability"` | ДА | Pure Shell (D1) → `equal` |
| `scenario_count` | `int` (обычно 4) | ДА | |
| `scenarios` | dict | ДА | Ключи в формате `Sc-X_label` |
| `per_position` | dict | ДА | Ключи — тикеры |
| `sector_breakdown_pct` | dict | ДА | Σ ≈ 100% ±2% |
| `top_risks` | list (≤5) | ДА | |
| `macro_blindspots` | list (может быть пустым) | ДА | |
| `portfolio_pl_range_rub` | `{min, max}` | ДА | |
| `concentration_ratio` | `float` | ДА | |
| `dominant_factor` | `string` | ДА | |
| `unmapped_tickers` | list | ДА | |
| `caveats` | list (≥1 запись `severity: HIGH`) | ДА | |
| `review_date` | `YYYY-MM-DD` | ДА | `date + 6 мес` |

---

## 2. Robustness verdict (обязательная секция, Phase 2.7)

```yaml
robustness:
  positive_or_neutral_scenarios: <int 0..4>
  worst_case: { id: "<scenario_id>", pl_pct: <float> }
  best_case:  { id: "<scenario_id>", pl_pct: <float> }
  spread: <best_pl_pct - worst_pl_pct>      # чувствительность к сценариям
  hedge_target: "<scenario_id или null>"    # сценарий, требующий хеджирования
  modal_scenario: "<id или none>"           # см. §4 ниже
```

---

## 3. D2 — `expected_pl_pct` / `expected_pl_rub`

**Default:** ОТСУТСТВУЮТ. По D2 (HANDOFF-claude-code-phased.md §1.5) probability-weighted
EV не считается без явного opt-in.

**Включение через флаг:** `--include-ev` (CLI флаг `portfolio-scenario-stress`).
При `--include-ev`:

```yaml
expected_pl_pct: <float>        # probability-weighted среднее ΔP&L (%)
expected_pl_rub: <int>          # probability-weighted среднее ΔP&L (RUB)
weight_type: probability        # обязательно при наличии expected_pl_*
```

**Pure Shell (equal weights, D1):** `expected_pl_*` НЕ создаётся даже при `--include-ev`,
потому что probability=0.25 — методологическое допущение, не реальная вероятность.

---

## 4. `modal_scenario_id` правило

Единое для трёх документов (`events-yaml-spec.md` §5, `scenario-yaml-spec.md` §3.4,
`migrate_to_conditional.spec.md`):

```
modal_scenario_id = argmax(weights)  if max(weights) > 0.30 else "none"
```

При equal weights `[0.25, 0.25, 0.25, 0.25]` → `"none"` (Pure Shell mode).

---

## 5. D3 — `out_of_frame_caveats`

Заменяет legacy `Unaccounted` сценарий. События вне axes scenario-матрицы (чёрные
лебеди — кибератака, природная катастрофа, политический кризис в США) обрабатываются
отдельным блоком, не внутри scenario probability frame:

```yaml
out_of_frame_caveats:
  - severity: low | medium | high
    description: "..."
    examples:
      - "..."
```

Размещение — в `caveats[]` или отдельным top-level блоком (на усмотрение производителя).
Validator проверяет наличие `description` и `severity`, не требует обязательности самого
блока.

---

## 6. Связь с conditional_on_scenarios (Layer 2)

`portfolio-scenario-stress` читает `by_scenario` напрямую из forecast YAMLs, не агрегированный
Layer 2 marginal. Это гарантирует coherent worldview: все факторы Sc-A — мирный/без-санкций;
все факторы Sc-D — война/санкции.

Stress YAML НЕ дублирует scenario probabilities — они в `Claude-Memory/scenarios/{matrix}.yaml`
(SSOT по D7).

---

## 7. Type 1 isolated forecasts (events-yaml-spec.md §5.5)

Forecasts с `isolated: true` НЕ участвуют в `portfolio-scenario-stress`. У них нет
`by_scenario` блока и они не вписываются в matrix worldview. Они аудитируются отдельно
через `retrospective-forecast-audit` как marginal-only.
