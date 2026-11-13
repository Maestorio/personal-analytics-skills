# Skill: forecast-collector

## Summary
Структура коллекции (YAML frontmatter + таблица) воспроизводится корректно по `_shared-references/yaml-schemas.md §3`, реальные файлы (`fc-gs-collection-2026-05-04.md` и т.д.) выглядят аккуратно, дедупликация через `updated_from`/`split_from` работает. Главные дефекты: (1) UPPERCASE префикс `FC-` в реальных файлах против lowercase `fc-` в `_shared-references/file-naming.md:41` и в `_shared-references/yaml-schemas.md §3` (`fc-{source-slug}-collection-{date}.md`); (2) граница «не аудируешь» нарушена в `warnings.direction_bias_note` свежей коллекции (систематическая интерпретация вместо сухой статистики); (3) Pending Rule требует `verification_url` и `verification_method` для ❓-статусов, но в реальных файлах эти поля иногда опускаются.

## Correctness (P1)
- [naming-violation] Реальные файлы используют префикс `FC-` (`forecast-collections/FC-GS-collection-2026-05-04.md`, FC-IEA, FC-JPM, …). По `_shared-references/file-naming.md:41` и `yaml-schemas.md §3` — должно быть `fc-` lowercase. SKILL.md (`forecast-collector/SKILL.md:308`) сам пишет ID в UPPERCASE (`FC-[ИСТОЧНИК]-[NNN]`), стр. 325 — имя файла lowercase. Внутренняя противоречивость скилла.
  - Эффект: D4-нарушение, Glob-фильтры в downstream могут пропустить часть файлов.
  - Fix sketch: одно из двух — либо легализовать UPPERCASE в `file-naming.md` (для совместимости с существующими файлами), либо добавить миграционный скрипт.
- [boundary-leak] `warnings.direction_bias_note` в `FC-GS-collection-2026-05-04.md` содержит интерпретативное утверждение типа «GS-Equities (Kostin) systematically underestimate». `SKILL.md:93–100` запрещает интерпретации в выводе коллекции (это работа `retrospective-forecast-audit`).
  - Эффект: выход из роли — статистика обогащается мнением до аудита. Аудитор получает «зашумлённый» вход.
  - Fix sketch: пре-output checkpoint, отвергающий warnings, содержащие квалификативные слова («systematically», «typically», «biased»). Допустимы только raw-цифры.
- [pending-incomplete] Pending Rule (`SKILL.md:124–148`) требует для ❓-записей поля `verification_url` и `verification_method`. В реальных коллекциях иногда опускаются.
  - Эффект: retrospective-forecast-audit не сможет проверить ❓ автоматически.
  - Fix sketch: блокирующая проверка перед save: «у каждого `status: ❓` должен быть `verification_url` (URL) или `pending_until` (дата) + `verification_method` (текст ≥10 слов)».

## Readability (P2)
- 514 строк SKILL.md — много, но шаги хорошо разделены (0–9). Diversity-баланс описан на 3 уровнях (тематика, время, направление), но нет явной check-листа в виде таблицы — только текст.
- `horizon-rules.md` (≤1 года для local macro, ≤2 для commodity, 1–10 для геополитики) хорошо структурированы; цитируются в SKILL.md.
- INDEX.md в `forecast-collections/` указывает «новый стандарт: `fc-…-lowercase`», что прямо противоречит реальным файлам.

## Cost (P3)
- 3–5 web_search + 4–6 web_fetch на 20 кандидатов — приемлемо.
- Тестов нет, но это allowed (LLM-only задача с структурным выходом).

## Speed (P4)
- 5–7 turn'ов на типичную коллекцию. Долгие архивы (ISW, Telegram) могут потребовать 10+. SKILL.md не задаёт timeout — корректно делегировано пользователю.

## Cross-skill / contract
- D3 OK: артефакт в чат → save-to-library → `forecast-collections/`.
- Downstream `retrospective-forecast-audit` потребляет коллекцию (через cowork-mode или приложенный файл). Контракт `type: forecast_collection`, `schema_version: 1` соблюдается.
- INDEX.md в `forecast-collections/` обещает lowercase-имена, но реальность UPPERCASE.

## Verified against artifact
- `~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/forecast-collections/FC-GS-collection-2026-05-04.md`:
  - 16 прогнозов, 8 отброшено (соответствует обещанным 10–20) ✓
  - Frontmatter: `source`, `collection_date`, `domain`, `n_collected`, `n_dropped`, `warnings` присутствуют ✓
  - Таблица 11 колонок, дату формата ISO ✓
  - `warnings.direction_bias_note` содержит интерпретацию «systematically» ✗
- Префикс `FC-` UPPERCASE × 7 файлов в директории — нарушает D4 и spec.

---

## Статус ревью (2026-05-10)

- **[naming-violation]** FC-A: **HALLUCINATION** — реальные файлы используют lowercase `fc-`. SKILL.md:308 описывает internal ID (`FC-XXX-NNN`), SKILL.md:325 — filename (`fc-…`); это разные сущности, не противоречие.
- **[boundary-leak]** FC-B: **FIXED** — добавлен блокирующий pre-output checkpoint CK1 в SKILL.md (отвергает qualifying-термины в `direction_bias_note`).
- **[pending-incomplete]** FC-C: **FIXED** — добавлен блокирующий pre-output checkpoint CK2 в SKILL.md (требует `pending_until` + `verification_url` + `verification_method`≥10 слов для каждого `❓`).
- Расширение CK1 на любые `*_note` warnings → **TODO [FC-1](../../TODO.md#fc-1)**.
