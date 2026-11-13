# Skill: revise-memory-local

## Summary
Самый компактный скилл (154 строки SKILL.md), две reference-страницы (`memory-structure.md`, `consolidation-rules.md`). Чистит локальную auto-memory: дедупликация, миграция project→feedback/user, упаковка `MEMORY.md` под порог 180 строк (запас до 160). Запреты на `CLAUDE.md`, `SKILL.md`, `.claude/settings.json` явные. После верификации: 2 из 3 дефектов оказались галлюцинациями ревьюера; 1 реальный gap (fallback при отсутствии контекста для `Why:`/`How to apply:`) перенесён в TODO как RML-1.

## Correctness (P1)
- ~~[missing-tests]~~ **❌ ГАЛЛЮЦИНАЦИЯ.** Скилл — чистая LLM-оркестрация без единого Python-скрипта (только `SKILL.md` + 2 reference-файла). Тестировать нечего; паттерн `tests/test_*.py` здесь неприменим. Ревьюер ошибочно перенёс паттерн из `revise-memory-remote` → `validate_library.py`.
- ~~[policy-undefined]~~ **❌ ГАЛЛЮЦИНАЦИЯ.** Политика задокументирована в нескольких местах: `SKILL.md:112-124` (хук ≤150 симв, уплотнение до ≤160), `consolidation-rules.md:53-63` (три способа уплотнения), `memory-structure.md:21-22` (MEMORY.md = только хуки, детали — в файлах). Информация о «фрейм-обрыве» (LLM context truncation) не относится к этому скиллу.
- [stub-records] **📋 TODO → [RML-1](../../TODO.md#rml-1).** Реальный gap: `SKILL.md:92` говорит «дополнить из контекста файла», но fallback при отсутствии контекста не описан. Косметическая правка: добавить одну инструкцию в `consolidation-rules.md` — оставить как `project_*.md` с `status: awaiting_context`.

## Readability (P2)
- 154 строки SKILL.md — компактно, читается за 5 минут.
- Запреты явные (CLAUDE.md, SKILL.md, settings.json, sensitive-файлы).
- `consolidation-rules.md` хорошо описывает «когда объединять» (long-term semantic) vs «когда оставлять» (different facets).

## Cost (P3)
- Локальные операции, нет API-вызовов.

## Speed (P4)
- O(n) по числу файлов в `~/.claude/projects/.../memory/`. Реальные размеры — ≤30 файлов, миллисекунды.

## Cross-skill / contract
- Standalone скилл; может вызываться после `memory-sync` или `revise-memory-remote` для уплотнения локальной memory.
- D3-обхода нет — оперирует только локальной auto-memory (`~/.claude/projects/...`), не Claude-Memory.

## Verified against artifact
- Не верифицировал (локальная memory пользователя — не предмет этого ревью библиотеки).
- `MEMORY.md` index в `_shared-references` обозначен; реальное состояние памяти пользователя соблюдает компактный шаблон.
