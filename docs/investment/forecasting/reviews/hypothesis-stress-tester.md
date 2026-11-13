# Skill: hypothesis-stress-tester

## Summary
4 техники Tier 1 (Pre-mortem, KAC lite, Devil's Advocate, Reversibility) логически целостны, реальный artifact (`forecasts/iran-us-may-deal-2026-04-30-stress.yaml`) валиден по `_shared-references/yaml-schemas.md §1` Tier 2. Главные дефекты: (1) нет описанной формулы агрегации pre-mortem-причин в downward-revision вероятности; (2) artifact использует `confidence: LOW|MEDIUM` в `assumptions[]`, тогда как `references/hst-events-yaml-spec.md` оперирует понятием `robustness` — schema divergence; (3) описание slug-uniqueness отправляет к save-to-library/references, что хрупко при изменениях.

## Correctness (P1)
- [missing-formula] `SKILL.md` Шаг 2.1 (Pre-mortem) требует top-3 причин, но не объясняет, **как** конкретно эти 3 причины переоценивают `confidence`. Вердикт от Tier 1 70% к Tier 2 30–40% делается «суждением» — нет ни формулы, ни эвристики (например, «каждая HIGH-причина минус 0.10»).
  - Эффект: разные сессии HST на одном прогнозе дадут разные результаты; нет калибровки на 100+ ретро-аудитах.
  - Fix sketch: ввести базовую эвристику (например, downward = sum_of_(severity_weight × top3_likelihood)), либо явно сказать «calibration to be developed in retrospective-forecast-audit».
- [schema-divergence] В свежем артефакте `assumptions[]` содержит поле `confidence: LOW|MEDIUM` (вместе с `severity: critical`). `references/hst-events-yaml-spec.md` шаблон-секция использует `robustness`. Несовпадение между спецификацией и реальным выводом.
  - Эффект: validate_forecast в save-to-library / revise-memory-remote может игнорировать одно из имён → invalid YAML пройдёт через сетки.
  - Fix sketch: выбрать одно имя и обновить либо spec, либо validate-script.
- [convention-leak] Slug-правила в `references/hst-events-yaml-spec.md:79–86` ссылаются на «`save-to-library/references/`» — кросс-проектная зависимость, которая ломается, если save-to-library изменит spec.
  - Эффект: при будущем изменении правил в save-to-library стресс-пары начнут конфликтовать с уже сохранёнными.
  - Fix sketch: вынести slug-правила в `_shared-references/file-naming.md` (там уже есть аналогичные). HST ссылается на shared, не на save-to-library.

## Readability (P2)
- 4 техники Tier 1 описаны кратко (`tier1-methods.md` — 40 строк), пояснения «как именно строить ACH-матрицу, какие dimensions» нет — пользователь итерационно догадывается.
- Шаг 3 (Итоговый вердикт) — template содержит `## Итог стресс-теста`, в реальном artifact раздел называется `## Стресс-тест` — мелкое расхождение.
- Quick-mode (`SKILL.md:52–59`) определён, но default = full. Триггеры quick-mode (формулировка пользователя) не нормированы.
- Соотношение между 16 численными расчётами и YAML-полями нигде не сведено в таблицу.

## Cost (P3)
- 4 техники Tier 1 + 6 Tier 2 секций — это полнопроходный 30–60-минутный анализ на Sonnet/Opus. Cost обоснован для критичных прогнозов; для мелких полезен quick-mode, но он плохо обозначен.
- Нет скриптов — все 16 операций mental arithmetic. Калибровка через retro-audit упоминается, но не интегрирована в DAG.

## Speed (P4)
- Pre-mortem генерация и ACH-матрица — ручной brainstorming. Бутылочное горло — это сам smysl метода. Здесь не нужно ускорять.

## Cross-skill / contract
- D3 OK: HST не пишет в `Claude-Memory/`. Артефакт идёт в save-to-library как stress-pair (`<slug>-stress.{md,yaml}`).
- HST не заполняет Tier 1 поля прогноза (`central_estimate`, `confidence`) — это правильно (Tier 1 от FCA или пользователя).
- [contract-gap] Если HST запущен на тексте без FCA (`SKILL.md:44`), как save-to-library должна знать, что нужно создать Tier 1 с `central_estimate: null # TODO`? Артефакт идёт как `-stress`, но Tier 1 пары может не существовать. Этот сценарий не обработан.
  - Fix sketch: явный флаг в frontmatter `tier1_pair_required: true|false`.

## Verified against artifact
- `~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/forecasts/iran-us-may-deal-2026-04-30-stress.yaml`:
  - `monitoring`: 3 (UKMTO ormuz, Israel-Beirut, KSDR), один `auto_checkable: true` ✓
  - `assumptions`: 3 (все `auto_checkable: false`, как и предписано) ✓
  - `thresholds`: 2 (обе `flip: invalidates`) ✓
  - `deadlines`: 1 (KSDR window 2026-05-14, `auto_checkable: true`) ✓
  - `falsifiers`: 3 (top-3 pre-mortem с `resolution_direction`) ✓
  - `agents`: 3 (`auto_checkable: false`) ✓
  - **Расхождение**: assumptions содержат `confidence: LOW|MEDIUM` — spec говорит `robustness` ✗
  - **Расхождение**: falsifiers содержат `resolution_direction`, agents содержат `interests`/`likely_actions` — поля не в spec template (расширение), нужно либо легализовать, либо удалить ✗
- Slug uniqueness внутри файла OK; коллизий между файлами не проверял (зона save-to-library).

---

## Статус ревью (2026-05-10)

- **[missing-formula]** HST-H: **→ TODO [HST-1](../../TODO.md#hst-1)** — формула downward-revision из top-3 pre-mortem-причин отложена (DEFERRED, зависит от V2-C — нужно ≥10 ретро-аудитов для калибровки).
- **[schema-divergence]** HST-F: **FIXED** — мигрирован `iran-us-may-deal-2026-04-30-stress.yaml`: `assumptions[*].confidence` → `robustness` (строки 48/55/61). Tier 1 `forecast.confidence: 0.4` (числовой) не тронут. Backup `.pre-robustness-rename` создан. `ukraine-russia-forecast-stress-test.yaml` уже использовал `robustness` — теперь все артефакты выровнены со spec.
- **[convention-leak]** HST-G: **FIXED** — slug-правила вынесены в `_shared-references/file-naming.md` § «Stress-pair slug rules»; добавлен `file-naming` в `shared_refs:` SKILL.md; ссылка в `hst-events-yaml-spec.md:79-86` заменена с битого `save-to-library/references/` на `file-naming.md` (инжектится при упаковке).
- **[contract-gap / Tier 1 missing]**: оставлено без правок (флаг `tier1_pair_required` — небольшая, но архитектурная задача, не входила в scope).
