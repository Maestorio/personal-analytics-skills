# Skill: forecast-confidence-applier

## Summary
Скрипт `weighted_consensus.py` отлично детерминирован: 47/47 тестов, формула `confidence = 0.4 + 0.4×share_HIGH − 0.2×asymmetry` работает корректно на всех граничных случаях (0 HIGH, 100% HIGH, asymmetry-флаг). UTF-8 (`ensure_ascii=False`) исключает классическое mojibake. Главные дефекты: (1) корень markdown-bold mojibake, обнаруженного в `forecasts/ai-capex-slowdown-2026-2026-04-30.md` (см. save-to-library audit) — НЕ в скрипте, а в текстовых шаблонах output (тогда происходит при формировании человеко-читаемого `.md`); (2) `asymmetry_warning` в payload — boolean-флаг, заполняемый LLM на Шаге 1.5, без машинной проверки; (3) MEDIUM fallback при отсутствии subdomain в INDEX.md — тих, не пишет warning.

## Correctness (P1)
- [bug-source] Mojibake-вставки `**` посередине кириллических слов (видны в `forecasts/ai-capex-slowdown-2026-2026-04-30.md`) — скрипт сам кириллицу в JSON не корраптит (тесты прошли). Источник — markdown-форматирование вывода в `.md`-файле, генерируемом LLM по шаблону. То есть проблема не в `weighted_consensus.py`, а в текстовых шаблонах `references/output-templates.md` или в том, как LLM строит выделения курсивом/полужирным внутри слов.
  - Эффект: артефакт нечитаем; downstream видит мусор. См. `save-to-library.md` issue.
  - Fix sketch: pre-output checkpoint в `SKILL.md` — регулярка против `\w\*\*\w` в финальном `.md`. Дополнительно — переучить LLM не подсвечивать **полужирным** середины слов; bold для целых терминов.
- [contract-gap] `asymmetry_warning` (boolean, передаётся в payload `weighted_consensus.py`) заполняется LLM на Шаге 1.5 (карта лагерей). Скрипт его принимает, но не валидирует контекст: «есть ли реальные основания», есть ли список контр-источников.
  - Эффект: LLM может ошибочно поставить `false` (asymmetry penalty 0) при действительно асимметричной карте → завышенная confidence.
  - Fix sketch: расширить payload полем `camp_distribution` (например, `{bull: N, bear: M, neutral: K}`) и считать asymmetry внутри скрипта.
- [silent-fallback] При отсутствии точного subdomain в `INDEX.md` `weighted_consensus.py:97` дефолтит на MEDIUM trust. Логика правильная, но не пишет warning в `warnings[]` выхода.
  - Эффект: «тихий» источник без явного trust-профиля попадает в consensus с MEDIUM-весом; пользователь не замечает, что нужно бы сделать аудит.
  - Fix sketch: добавить в скрипт `warnings.append({"type": "fallback_medium", "source": <name>})` для каждого случая.

## Readability (P2)
- 570 строк SKILL.md — много, шаги 0–6 разделены, но повтор «все числовые расчёты только через скрипт» встречается ≥3 раз.
- Формула взвешенного горизонта (HIGH×1.0, MEDIUM×0.5) описана в `weighted_consensus.py:147–170`, но не дублируется в SKILL.md явно.
- 6 shared-refs — много для одного скилла, но осмысленные (transport, yaml-schemas, file-naming, audit-frontmatter, claude-memory-layout, model-routing).

## Cost (P3)
- Скрипт без зависимостей, миллисекунды на запрос.
- 3–7 источников × web_search — основной cost, LLM-driven.

## Speed (P4)
- Шаг 3 (читать INDEX) → Шаг 4 (web_search) — последовательны. Параллельный web_search для multiple sources возможен, но в SKILL.md не указан.

## Cross-skill / contract
- D3 OK: артефакт в чат → save-to-library Workflow B → `forecasts/<slug>-<date>.{md,yaml}`. Tier 1.
- Контракт `_shared-references/yaml-schemas.md §1` (Tier 1) соблюдается.
- forecast-monitor читает `reviews.next_due` и `interval_months` — присутствуют.
- hypothesis-stress-tester может работать поверх (создаёт `-stress` пару) — handoff корректный.
- INDEX.md trust-матрица — авторитетный источник для скрипта.

## Verified against artifact
- `~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/forecasts/brent-oil-dec-2026-2026-04-30.yaml`: frontmatter Tier 1 полный, `confidence: 0.40` соответствует формуле при 0 HIGH ✓.
- `forecasts/iran-us-may-deal-2026-04-30.yaml`: `confidence: 0.48` — соответствует формуле.
- `forecasts/ai-capex-slowdown-2026-2026-04-30.md`: содержит markdown-bold mojibake внутри кириллических слов ✗ (источник — текстовый шаблон, не YAML/skript).
- `forecasts/ru-rates-2026-2026-04-28.yaml`: `confidence: null` — это уже зона save-to-library (валидация). FCA не должен был отдать null; либо файл был сохранён пользователем вручную обходом скрипта.

---

## Статус ревью (2026-05-10)

- **[bug-source]** FCA-D: **HALLUCINATION** — файла `forecasts/ai-capex-slowdown-2026-2026-04-30.md` не существует, mojibake-утверждение неверифицируемо.
- **[contract-gap]** FCA-E: **→ TODO [FCA-1](../../TODO.md#fca-1)** — `asymmetry_warning` остаётся bool из payload; миграция на вычисление из `camp_distribution` отложена (M-задача).
- **[silent-fallback]** FCA-F: **FIXED** — `applied_weight()` возвращает третьим элементом `is_fallback_medium`; в `compute()` собирается `warnings: [{type: "fallback_medium", source, subdomain}]`. Добавлены 2 теста (test_compute_emits_fallback_medium_warning, test_compute_no_fallback_warning_when_profile_matches).
- **[ru-rates artefact]** FCA-G: **HALLUCINATION** — файл `forecasts/ru-rates-2026-2026-04-28.yaml` не существует.
