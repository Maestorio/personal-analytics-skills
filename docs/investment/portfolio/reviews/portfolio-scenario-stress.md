# Skill: portfolio-scenario-stress

> **Статус ревью (2026-05-10):** все 4 P1-бага закрыты в коде и валидаторе save-to-library; P2 hardcode и /tmp — в `docs/investment/TODO.md`.

## Summary
Скрипт `compute_per_position.py` решает заявленную capacity-проблему (>30 позиций) — реальный артефакт покрывает 92/93 unblocked. Главные дефекты: документированная схема внутренних факторов (`brent_pct_change`) расходится с тем, что ожидает скрипт (canonical `brent`); обязательные поля `unmapped_tickers` и `caveats` декларированы в Pre-emit checklist, но в свежем артефакте отсутствуют.

## Correctness (P1)
- ✅ **ЗАКРЫТО (A3).** [schema-mismatch] Internal-format факторов в `references/input-adapters.md:75–157` (`brent_pct_change`, `rate_bps_change`, `usdrub_pct_change`, `sanctions_escalation`, `geopol_escalation`) расходится с canonical-набором, который ожидает `scripts/compute_per_position.py:31` (`["sanctions","geopol","cbr_rate","usdrub","cnyrub","brent","xauusd"]`). Нормализация нигде не описана.
  - Эффект: если LLM сформирует `scenarios-fragment.yaml` во внутреннем формате, скрипт выполнит `factors.get(f, 0)` → нулевые beta, все `delta_pct = 0`, top-risks молча пустые.
  - Fix sketch: добавить раздел «Нормализация имён факторов» в `input-adapters.md` с явной mapping-таблицей; либо сделать соответствующую трансформацию в начале `compute_per_position.py`.
  - **Реализовано:** в `references/input-adapters.md` добавлен раздел «Канонические имена факторов» с явной mapping-таблицей и поток данных `macro-input → scenarios-fragment → script`. В `SKILL.md` Шаг 2 переписан на canonical-формат с указанием на mapping. Реальные артефакты в `Claude-Memory/` уже на canonical (внутренний-format использовался только в документации) — миграция данных не нужна. Полная унификация формул в `bonds-sensitivity.md` / `sector-sensitivities.md` / `fund-decomposition.md` перенесена в 📋 PSS-3.
- ✅ **ЗАКРЫТО (A4).** [missing-field] Артефакт `Portfolio/stress/stress-2026-05-06-zheleznyi-zanaves.yaml` не содержит `unmapped_tickers: [...]`, требуемое в Pre-emit checklist (`SKILL.md:471`). UNMAPPED-позиции выбрасываются `compute_per_position.py` с warning в stderr, но не маркируются в выходном YAML.
  - Эффект: пользователь не видит, какие позиции были исключены и сколько весов выпало.
  - Fix sketch: добавить в скрипт ключ `unmapped_tickers` (список всех тикеров без priors) + сумму `unmapped_weight_pct`; внести в обязательную проверку перед save-to-library.
  - **Реализовано:** `compute_per_position.py` теперь собирает `unmapped_tickers: [{ticker, weight_pct, reason}]` и выводит в fragment. SKILL.md обновлён — Шаг 3.6.5 явно требует копировать оба ключа (`per_position` + `unmapped_tickers`) в финальный YAML. Валидатор `assemble_artifact.py:validate_stress` теперь блокирует артефакт без `unmapped_tickers`. Покрыто 4 новыми тестами.
- ✅ **ЗАКРЫТО (A4).** [missing-field] В свежем артефакте отсутствует `caveats` — заявлен обязательным в Pre-emit checklist (`SKILL.md:473`).
  - Эффект: caveat «duration-based линейная аппроксимация без конвексности», заявленный в `SKILL.md:178`, исчезает к моменту чтения downstream.
  - **Реализовано:** валидатор `validate_stress` уже блокировал артефакт без `caveats[severity:HIGH]` (строки 164–180). Это подтверждено существующим тестом — артефакт 2026-05-06 был сохранён в обход валидации. Pre-emit checklist в SKILL.md остался обязательным; для единообразия с `unmapped_tickers` добавлен явный блок-чек.
- ✅ **ЗАКРЫТО (A4).** [schema-mismatch] Поле `generated_at` в артефакте (top-level) не описано в `_shared-references/yaml-schemas.md §5`; верхнеуровневое имя поля — `date`. Минор, но создаёт двусмысленность для downstream-парсеров.
  - **Реализовано:** валидатор `validate_stress` теперь блокирует случай «есть `generated_at` без `date`» (новая проверка). Покрыто тестом `test_generated_at_without_date_blocks`.

## Readability (P2)
- 📋 **Уточнено в A3.** `references/input-adapters.md` подробно описывает Type A/B/C, но не указывает момент перехода internal → canonical. Ошибка проектирования контракта: документация и скрипт говорят на разных языках.
- Шаг 3.5 (idiosyncratic reasoning, `SKILL.md:189–256`) проговаривает логику, но в артефакт идиосинкратика попадает только в `macro_blindspots`. Для пользователя теряется trace «что я знал → что попало в стресс».
- 📋 **В TODO (PSS-1).** `compute_per_position.py:39–45` хардкодит список идиосинкратических тикеров (MDMG, PRMD, OZON, WUSH, DOMRF). Список не цитируется в SKILL.md и обновляется только в коде.

## Cost (P3)
- Стороны написания и отладки. Скрипт детерминирован, работает в priors-only режиме (Phase 4.1) — `R²=null`, `CI = ±max(|Δ|×0.4, 5%)` placeholder. Документировано (`SKILL.md`), но при росте портфеля точность уплывёт.
- 📋 **В TODO (PSS-2).** `/tmp/`-промежуточные файлы (`SKILL.md:315–324`) не очищаются — не критично для cost, но захламляет рабочее окружение между запусками.

## Speed (P4)
- Линейный пайплайн `LLM → /tmp → script → /tmp → LLM`. Для портфеля <200 позиций — миллисекунды; масштабирование текущей капасити отдельно не обсуждается.

## Cross-skill / contract
- D3 OK: скилл сам в `Claude-Memory/` не пишет, выходит артефактом в чат → save-to-library.
- Hardcoded paths сверены с `_shared-references/transport-layer.md` — `Portfolio/stress/`, `Portfolio/snapshots/` совпадают.
- Downstream `portfolio-integrated-view` ожидает `expected_pl_rub`, `portfolio_snapshot_id`, `top_risks` — все три в артефакте есть.
- save-to-library Pre-emit checklist (`SKILL.md:452–474`) перечисляет обязательные поля, но сам save-to-library их не валидирует (см. `save-to-library.md` ревью). Это даёт окно «обязательное, но не проверяемое» — два недостающих поля в свежем артефакте именно так и проскочили.

## Verified against artifact
- `~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/Portfolio/stress/stress-2026-05-06-zheleznyi-zanaves.yaml`:
  - `schema_version: 1` ✓, `date: 2026-05-06` ✓, `weight_type: probability` ✓
  - 4 сценария (Sc-A/B/C/D), 92 позиции из 93 unblocked (~99% coverage) — capacity-режим скрипта работает
  - `factor_betas` каноничны (7 факторов) ✓
  - `unmapped_tickers` — **отсутствует**
  - `caveats` — **отсутствуют**
  - `macro_blindspots` — 5 позиций, причины задокументированы ✓
  - `top_risks` соответствуют per_position-агрегации ✓
