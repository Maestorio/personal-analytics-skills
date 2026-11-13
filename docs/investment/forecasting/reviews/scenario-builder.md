# Skill: scenario-builder

## Summary
Свежий artifact `scenario-ai-capex-scenarios-2026-2026-04-30.yaml` валиден по `_shared-references/yaml-schemas.md §2`. Структура 2×2 (axis_x, axis_y, scenario_triggers A/B/C/D) корректна, оси сформулированы как полюса. Два P1-бага исправлены. Два P2-замечания в TODO.

## Correctness (P1)

- [missing-validation] ✅ **ИСПРАВЛЕНО** — добавлена команда `validate-scenario-events` в
  `skills/save-to-library/scripts/assemble_artifact.py`: проверяет обязательные поля и
  Σ `scenario_triggers[*].probability` ∈ [0.98, 1.02] (warning). `save-to-library/SKILL.md`
  A2.4 обновлён — `scenario-events` теперь вызывает `assemble_artifact.py`, а не
  несуществующий `validate_schema.py`. 5 новых тестов, итого 74.

- [auto-checkable-laxity] ✅ **ИСПРАВЛЕНО** — в `skills/scenario-builder/SKILL.md` добавлено
  поле `manual_check_method` в шаблон `leading_indicators` (строка ~290) и требование в
  «Правилах заполнения»: при `auto_checkable: false` поле обязательно (≤100 симв., с примером).

## Readability (P2)

- [step-4.5-triggers] → **TODO [SB-2]** — триггеры активации Step 4.5 («Downstream sensitivity
  hints») заменить на explicit-лист условий.

- [fca-workflow-link] → **TODO [SB-3]** — задокументировать в SKILL.md цепочку после FCA:
  обновить `probability` вручную → save-to-library Workflow C → RECALIBRATE.

## Дополнительно обнаружено

- [validate_schema.py missing] → **TODO [STL-5]** — `save-to-library/SKILL.md` A2.4 ссылался
  на `scripts/validate_schema.py` для `forecast-events`, которого не существует.
  До реализации A2.4 использует ручной чеклист для `forecast-events`. Сложность M.

## Cost (P3)
- 2–3 web_search на сценарий (Шаг 1.1) — приемлемо.

## Speed (P4)
- Шаг 1.2 — checkpoint с пользователем (подтверждение осей). Бутылочное горло — у пользователя, не у скрипта. OK.

## Cross-skill / contract
- D3 OK: артефакт в чат → save-to-library Workflow C → `scenarios/`.
- forecast-monitor читает scenario-events через схему `_shared-references/yaml-schemas.md §2`, ожидает `reviews.next_due` — присутствует.
- hypothesis-stress-tester handoff текстовый, без формального флага — приемлемо.
- forecast-confidence-applier обновление probability не автоматизировано — по дизайну (D1, User in the loop).
- `references/transport-layer.md` отсутствует локально — ожидаемое поведение: `pack.sh` инжектирует shared-refs из `_shared-references/`.

## Verified against artifact
- `~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/scenarios/scenario-ai-capex-scenarios-2026-2026-04-30.yaml`:
  - `schema_version: 1`, `type: scenario-events` ✓
  - `matrix.axis_x: "AI монетизация: ROI подтверждается [A] vs Разрыв ROI сохраняется [B]"` ✓
  - 4 scenario_triggers (A/B/C/D), `probability: 0.25` каждый, Σ = 1.0 ✓
  - `leading_indicators`: 6 items, 3 с `auto_checkable: true` (числовые/датовые), 3 — false ✗
    (теперь потребуют `manual_check_method` при следующем сохранении)
  - `reviews.next_due` присутствует ✓
  - `final_audit.due` и `status` присутствуют ✓
