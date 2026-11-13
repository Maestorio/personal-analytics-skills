# Session handoff — 2026-05-23

Короткая выжимка контекста сессии для продолжения работы локально.
Бранч: `claude/travel-stage-4-builder-mkxG7`. Запушен.

## Где находится travel-planning после этой сессии

- Stage 4 (Route variants) **реализован** — коммит `2b9b239`.
- Сделан follow-up cleanup поверх Stage 4 — коммит `a2a0bd4`.
- Версия пайплайна: **v0.11**.
- Тесты: 355/355 (similarity 135 + parse_dr 68 + aggregate_pois 152).

## Что сделано в этой сессии (поверх v0.11)

### 1. Глобальная смена приоритета источника входного артефакта

Новый порядок (был Synology → приложенный → MCP):

```
1. Файл приложен к чату    ← дефолт (явная воля пользователя)
2. Synology mount          ← fallback
3. Google Drive MCP        ← последний резерв (base64-декод)
```

Логика: приложенный к чату файл = явный сигнал «работать именно с этой
версией»; Synology — fallback только когда не приложено. Раньше Synology
шёл первым, и это конфликтовало с реальной интенцией пользователя при
прикреплении исправленной версии артефакта.

**Затронутые файлы:**
- `skills/travel-planning/references/storage-and-naming.md` §8.0 — главная
  конвенция.
- `skills/travel-planning/references/stages/stage2-similarity.md` §3 шаг 3.
- `skills/travel-planning/references/stages/stage3-poi.md` §3 шаг 2.
- `skills/travel-planning/references/stages/stage4-variants.md` §3 шаг 2.

В `changelog.md` v0.10 запись оставлена как есть (это исторически верное
описание состояния в v0.10). Новая запись добавлена в v0.11.

### 2. Чистка калибровочных утечек из Stage 4 + пересмотр §3

`skills/travel-planning/references/stages/stage4-variants.md`:

- **§3 «Размер выборки и нагрузка»** переписана:
  - Убраны конкретные цифры калибровочных кейсов (Vietnam 47, Argentina 26).
  - **Смена логики**: на больших поездках **не сокращать число вариантов
    до 2** — наоборот, разнообразие тредофов между вариантами тем
    важнее. Вместо этого — рекомендация эскалации модели к Opus 4.7.
- **§6.3** (бюджет-warning): абстрагирован пример (убрано Pu Luong → Sapa).
- **§6.6** (RED FLAG exception): абстрагирован пример (убрано Argentina
  Isla Martillo + Maria Dol). Оставлено объяснение цели правила.
- **§9.3** (узкая HIGH-когорта): убрана конкретика Vietnam-кейса,
  оставлено описание поведения.

**Iconic exception (§6.5) оставлен** — короткое концептуальное упоминание
паттерна (Isla Martillo / Angkor Wat как «топ-1 эталон категории»),
парный фрагмент в `stage3-poi.md §6.8`. Это не калибровочный leak, а
концептуальный пример паттерна.

## Что НЕ сделано / следующие шаги

1. **Калибровка Stage 4 на Argentina + Vietnam.** Главный
   следующий шаг. Postmortem-шаблоны:
   - `argentina_south_2025_postmortem_template.md`
   - `vietnam_2023_postmortem_template.md`

   Методология описана в `CLAUDE.md` секция «Travel Planning →
   Calibration». Blind-режим: postmortem заполняется ДО прогона,
   hindsight bias блокируется секцией «оставлять незаполненным до
   прогона скилла».

   На калибровке проверить, в том числе, новую логику §3
   («Opus вместо сокращения вариантов»).

2. **Stage 5 (final plan).** Дизайн ещё не начат. Дев-инструмент —
   `/travel-stage-builder` (читает всю документацию, предлагает план,
   обсуждает оптимизацию, реализует). Хороший вход — handoff-контекст
   `stage3-handoff-context.md` как образец формы дизайн-документа.

3. **Storage swap (опционально).** Если переход на чистый S3 / локальную
   папку — править §1 + §8 в
   `skills/travel-planning/references/storage-and-naming.md`. SKILL.md
   и stage-references обращаются к хранилищу абстрактно через
   `{travel_root}/...`.

## Где смотреть детали

| Документ | Назначение |
|---|---|
| `architecture.md` | Архитектурные решения и known failure modes |
| `changelog.md` | История версий v0.1 → v0.11 (последний раздел — v0.11 cleanup) |
| `travel-planning-methodology.md` | Пользовательская методология пайплайна |
| `stage3-handoff-context.md` | Образец дизайн-документа стадии (для Stage 5+) |
| `stage4-handoff-context.md` | Контекст дизайна Stage 4 (теперь implemented) |
| `Stage-3.md`, `Stage-4-example.md` | Примеры реальных артефактов стадий |

## Состояние ветки на момент handoff

```
a2a0bd4 fix(travel-planning): источник priority + чистка калибровочных leak (Stage 4)  ← HEAD
2b9b239 feat(travel-planning): Stage 4 — Route variants (v0.11)
1ed6a15 Create Stage-4-example.md
97511c0 Create Stage-3.md
62a37bc docs(travel-planning): архитектура v0.10, Stage 4 handoff, тест-команда
```

Пушено на `origin/claude/travel-stage-4-builder-mkxG7`. Чтобы продолжить
локально — fetch + checkout этой ветки.
