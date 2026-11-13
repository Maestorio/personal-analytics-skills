# Skill: retrospective-forecast-audit

## Summary
Самый «дисциплинированный» из аудиторских скиллов: 50/50 тестов `retro_metrics.py` зелёные, 3 шкалы + матрица ценности −3..+3 + 9 агрегатов, маркеры ⭐/🌍/👤/⚠️ — всё детерминированно посчитано. Правило про русский язык и `audit-frontmatter-schema.md` корректно. Главный артефактный issue: `Claude-Memory/audits/` пуст — выходы аудитов сохраняются только в `domains/<dom>/<source>-*.md`, при этом `audits/` упоминается как «выход» в `_shared-references/claude-memory-layout.md:32–33`. Либо `audits/` — рудимент, либо пропущен альтернативный путь сохранения.

## Correctness (P1)
- [layout-ambiguity] `_shared-references/claude-memory-layout.md:32–33` обещает: «`audits/` — выходы retrospective-forecast-audit», но реальная директория пуста, а файлы лежат в `domains/<dom>/<source>-*.md`. SKILL.md `retrospective-forecast-audit/SKILL.md:620–634` ясно говорит, что save-to-library пишет в `domains/`. Layout-doc устарел.
  - Эффект: пользователь, ожидающий найти аудит в `audits/`, не находит его. Скрипт `revise-memory-remote/scripts/validate_library.py` может пометить parsed-аудит как «осиротевший», если проверяет `audits/`.
  - Fix sketch: либо обновить layout-doc (убрать `audits/` или указать «legacy, использует domains/»), либо ввести сохранение синтез-сводок в `audits/`.
- [llm-discipline-risk] Инвариант «русский язык» (`SKILL.md:32–34`), L-R sweep (`SKILL.md:186–189`), snapshot sell-side для RU-акций (`SKILL.md:159–160`) — всё это требует LLM-дисциплины и не контролируется автоматически. Pre-output checkpoint (`SKILL.md:327–367`) — 67-пункт чек-лист, тяжелый для LLM.
  - Эффект: непредсказуемые регрессии при понижении модели или скиле.
  - Fix sketch: добавить хотя бы 1–2 автоматических проверки в `retro_metrics.py` или отдельный `validate_audit.py`: (a) присутствует ли цитата на русском с переводом для иноязычного источника; (b) для каждой ❓-метки есть ли web_search-комментарий.
- [boundary-on-input] Скилл явно запрещает Deep Research в одном turn'е (`SKILL.md:404–407`); workflow B (DR отдельным turn'ом, потом скилл со сырьём) — корректное решение, но требует от пользователя помнить эту особенность.

## Readability (P2)
- 712 строк SKILL.md, но навигация по шагам и primary/secondary разделам понятна.
- 4 типа маркеров (⭐/🌍/👤/⚠️) и 4 типа исключений (⏳/🌪/❓/Split) — много, но в `references/output-templates.md` дано в одном месте.
- Light vs Full audit разделены ясно (`SKILL.md:574–593` Light, +`SKILL.md:510–556` Full). Routing на Opus 4.7 при ≥9 тезисов или ≥45 мин — описан.
- Ценность матрица в `references/value-matrix.md` дублирует логику `retro_metrics.py:72–107`. Кодом единственным источником истины можно сделать через docstring → MD pipeline.

## Cost (P3)
- Web_search/fetch: 8–25 запросов на аудит — умеренно.
- Скрипт без зависимостей.
- Light audit на Sonnet — экономично; Full на Opus — обоснованно.

## Speed (P4)
- 10–15 turn'ов для Full, 6–10 для Light.
- Workflow B (DR отдельно) добавляет 1 turn, но сильно разгружает контекст основного.

## Cross-skill / contract
- D3 OK: артефакт в чат → save-to-library → `domains/<dom>/<source>-*.md`. INDEX.md и `_sync_log.md` обновляются.
- Auto-inclusion: pin OR HIGH trust → `[lib]`-запись через memory-sync. Согласовано.
- Upstream: forecast-collector (опц., прикладывается как материал).
- Pre-emit: `audit-frontmatter-schema.md` обязательные поля (`source`, `audit_date`, `trust`) — присутствуют в реальных файлах.

## Verified against artifact
- `~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/audits/`: ПУСТО — но это объясняется выбором save-to-library писать в `domains/`. Layout-doc устарел.
- `~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/domains/global-banks/` и подобные содержат файлы вида `<source>-<period>.md` с frontmatter (source, audit_date, trust, …) ✓.
- `retro_metrics.py` — 50/50 тестов зелёные (`CLAUDE.md`).
- EXAMPLES.md (раздел 1–4): пример Invest Era — 47 тезисов, hit_rate 48.8%, alpha_generation 66.7% — соответствует таблице ценности и маркерам ✓.

---

## Статус ревью (2026-05-10)

- **[layout-ambiguity]** RFA-D: **TRACKED [RMR-1](../../TODO.md#rmr-1)** — задача «легализовать пустой `audits/`» уже трекается в TODO как часть revise-memory-remote (правка SKILL.md / claude-memory-layout.md).
- **[llm-discipline-risk]** & **[boundary-on-input]**: оставлены без правок (требуют ввода validate_audit.py / процесс для DR — не входит в scope текущей итерации).
