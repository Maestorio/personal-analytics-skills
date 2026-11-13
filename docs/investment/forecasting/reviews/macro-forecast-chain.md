# Skill: macro-forecast-chain

> **Статус ревью (2026-05-10):** все P1-баги закрыты в коде/документации; P2-косметика перенесена в `docs/investment/TODO.md`.

## Summary
Самый зрелый из критических скиллов: 58 тестов зелёные (было 54 + 4 новых для legacy method-fallback), реальный артефакт `macro-input-2026-05-04.yaml` соответствует schema yaml-schemas.md §4, DAG-логика с переводом geopolitics-сценария по 4 классам (linear / nonlinear / axis_dependent / indifferent) выглядит корректно. Минорные замечания: расхождение `stale_flags.yaml` (brent: critical 2026-05-07) и итогового статуса `FRESH` в свежем артефакте — нет явного описания, на каком шаге чтение флагов влияет на режим; method=null backward-compatibility в скрипте обрабатывается через fallback к `manual`, но условие неявное.

## Correctness (P1)
- ✅ **ЗАКРЫТО (A1).** [inconsistency] `stale_flags.yaml` помечает `brent-oil-dec-2026: severity=critical 2026-05-07`, но `macro-input-2026-05-04.yaml` имеет 10/10 FRESH и `brent` без флага. Артефакт старее флага на 3 дня — это объяснимо, но поведение «как монитор-флаги влияют на следующий запуск» не описано в `SKILL.md` шагах 3.5/4 явно.
  - Эффект: пользователь может пропустить critical-флаг и запустить QUICK-REFRESH вместо FULL.
  - Fix sketch: в Шаг 3.5 (mode-selection) явно прописать: «если в `stale_flags.yaml` есть critical для какого-либо требуемого фактора → форс FULL/PARTIAL, нельзя QUICK-REFRESH».
  - **Реализовано:** в `SKILL.md` Шаг 3.5 и `references/mode-selection-template.md` добавлено жёсткое правило про critical-флаг (запрет QUICK-REFRESH).
- ✅ **ЗАКРЫТО (A2).** [inconsistency] `coverage_report.py:140–142` корректно делает worst-of-two (age × monitor-flag), но fallback `method is None → treat as manual` (≈ строки 250+) не явный — поле может быть пустым в legacy YAML, тогда coverage_score посчитается без штрафа за неаудированный источник.
  - Эффект: занижение «качества покрытия» не сработает на старых файлах, FCA-cluster trust будет завышен.
  - Fix sketch: в скрипте: явно treat `method in (None, "")` как `manual`; в схеме YAML сделать `method` required.
  - **Реализовано:** добавлен явный fallback `method in (None, "")` → treat as manual + caveat `LEGACY_FORMAT_NO_METHOD`. Покрыто 2 новыми тестами (test_evaluate_factor_legacy_no_method, test_evaluate_factor_legacy_empty_method). Schema YAML required `method` — отдельная задача 📋 MFC-3.

## Readability (P2)
- 📋 **В TODO (MFC-2).** 8 шагов + 2 checkpoint'а — полно, но 713 строк SKILL.md — много. Шаги 5.0/5.1/5.2 (geopolitics translation) — самая плотная часть; диаграмма «фактор → метод → сценарий → backflow» ускорила бы чтение.
- 7 reference-файлов (dependency-map, sector-factor-matrix, staleness-config, consistency-rules, coverage-report-template, mode-selection-template, macro-input-schema). Дробно, но имена осмысленные.
- 📋 **В TODO (MFC-1).** `caveats[]` в выводе — 5 типов (LOW_CONFIDENCE_CLUSTER, CONSISTENCY_WARNING, NONLINEAR_CONDITIONAL_ON_MODAL, ZERO_AUDITED_SOURCES, HORIZON_GAP, WEAK_MODAL_GEOPOLITICS). Нет реестра в одном месте — раскиданы между `SKILL.md` и `consistency-rules.md`.

## Cost (P3)
- coverage_report.py — 0 dependencies, ≤ 1ms на типичный inventory. Норма.
- Checkpoint 1/2 ждут пользователя — вне cost-профиля.
- Шаг 5.2 (alternatives для nonlinear) запускает по 3 короткие FCA — это уровень `forecast-confidence-applier`, не самого скилла; стоимость переходит туда.

## Speed (P4)
- Шаги 1–3 read-only (parsing YAML), быстрые.
- Шаг 5: N факторов × FCA в DAG-порядке — последовательно. Параллелизация затруднена (downstream зависят от upstream через cascade-флаги). Не критично для 5–7 факторов.

## Cross-skill / contract
- D3 OK: пишет артефакт в чат, save-to-library помещает в `macro-chain/`. Hardcoded paths сверены — все совпадают с `_shared-references/transport-layer.md`. ✓
- Downstream `portfolio-scenario-stress` ожидает factors-набор с canonical-именами (`brent`, `usdrub`, `cnyrub`, `cbr_rate`, `inflation_ru`, `sanctions`, `geopol`). В артефакте есть. ✓
- Sector-overrides.yaml — `transport-layer.md:178–185` описывает merge-on-read; в `SKILL.md` шаг 1.2 commands corresponding. Если файл отсутствует, не блокирует — правильное поведение.
- `_shared/DEPENDENCY-MAP.md` — фактически `_shared-references/...` дублируется через `pack.sh`. Согласуются.

## Verified against artifact
- `~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/macro-chain/macro-input-2026-05-04.yaml`:
  - `schema_version: 1`, `run_id: MFC-20260504-1`, `mode: QUICK-REFRESH`, `coverage: 10/10` ✓
  - `geopolitics_translation` для cbr_rate / inflation_ru = `linear`; brent / usdrub / cnyrub = `nonlinear`; sanctions / urals_discount = `axis_dependent` ✓
  - `alternatives` для nonlinear-факторов с `indicative: true` присутствуют ✓
  - 5 типов caveats покрыты ✓
  - 4 Shell-сценария + Unaccounted (p=0.065) ✓
- `stale_flags.yaml`: `brent-oil-dec-2026: severity=critical, flagged: 2026-05-07` — монитор поднял флаг ПОСЛЕ генерации артефакта 2026-05-04. Поведение при следующем запуске должно учесть; правило в SKILL.md не явное.
- `_shared/DEPENDENCY-MAP.md` (в Claude-Memory) присутствует, версия согласована с `_shared-references/`.
