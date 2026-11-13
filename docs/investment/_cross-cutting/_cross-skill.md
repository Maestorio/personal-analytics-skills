# Cross-skill: системные нарушения и контракты

Здесь собрано то, что не локально к одному скиллу: расхождения между shared-references и реальными скиллами, нарушения архитектурных правил D3/D4, проблемы транспорта, мёртвые shared-refs.

> **Статусы:** ✅ Закрыт · 🤖 Галлюцинация (не проверяй повторно — уже проверено) · 📋 → TODO · ⚠️ Не верифицирован

---

## Сводная таблица

| Issue | Скиллы затронуты | Severity | Статус |
|---|---|---|---|
| D3 формальное противоречие | data-loader, macro-watcher, forecast-monitor | P1 | ✅ Закрыт |
| D4 в forecast-collections, macro-snapshots | forecast-collector, macro-ru-watcher | P1 | 🤖 Галл. (fc) + 📋 MRW-1 (macro) |
| Layout-doc не описывает monitor-reports/, stale_flags.yaml | forecast-monitor | P1 | ✅ Закрыт |
| Layout-doc: audits/ vs domains/ | retro-audit | P1 | 📋 RMR-1 |
| Schema mismatch input-adapters — «mapping нигде нет» | portfolio-scenario-stress | P1 | 🤖 Галлюцинация |
| Schema divergence HST assumptions confidence vs robustness | hypothesis-stress-tester | P1 | 🤖 Галлюцинация |
| Missing dispatch weekly-bonds-review | save-to-library | P1 | 🤖 Галлюцинация |
| Markdown-bold mojibake | FCA, HST, save-to-library | P1 | ⚠️ Не верифицирован |
| Валидация не обязательна перед save | save-to-library | P1 | 🤖 Галлюцинация |
| LOW-only без warning | save-to-library + memory-sync | P1 | 📋 MS-1 |
| null-значения проходят validate_library.py | revise-memory-remote | P1 | 🤖 Галлюцинация |
| Мёртвые/неоднозначные shared-refs | infrastructural | P2 | ⚠️ Не баг |
| Формат `_sync_log.md` ad-hoc | memory-sync | P2 | 📋 STL-4 (частично) |
| Fallback Transport B→A непрозрачен | все, кто пишет | P2 | 📋 CS-1 |
| Bootstrap trust-profiles | ru-portfolio-advisor | P3 | 📋 RPA-2 |

---

## P1 — нарушения D3/D4

### D3 — три скилла пишут напрямую, не через save-to-library

> ✅ **Закрыт 2026-05-10.** `_shared-references/claude-memory-layout.md` обновлён: таблица исправлена, добавлен раздел «Три задокументированных исключения D3».

**Что было не так:** таблица в layout-doc указывала `save-to-library` как писателя `macro-snapshots/`. Реально там три скилла пишут напрямую:
- `portfolio-data-loader` → `Portfolio/snapshots/`
- `macro-ru-watcher` → `macro-snapshots/`
- `forecast-monitor` → `stale_flags.yaml` в корень (Шаг 6b SKILL.md)

Все три теперь задокументированы в layout-doc как намеренные исключения (observation-объекты, не аналитические артефакты).

---

### D4 — UPPERCASE в forecast-collections

> 🤖 **Галлюцинация. Не проверяй повторно.**
>
> **Факт:** все файлы в `forecast-collections/` — lowercase: `fc-gs-collection-2026-05-04.md`, `fc-iea-collection-2026-05-06.md` и т.д. Проверено `ls` 2026-05-10.
>
> Внутренние ID типа `FC-GS-001` в `forecast-collector/SKILL.md:308` — это идентификаторы строк в таблице внутри файла, не имена файлов. D4 регулирует имена файлов, не содержимое.

Реальное нарушение только одно: `macro-snapshots/RU-2026-05-07.md` — трекируется в [MRW-1](../TODO.md#mrw-1), требует ручного переименования пользователем.

---

## P1 — расхождения shared-references vs скиллы

### Layout-doc не отражает `monitor-reports/` и `stale_flags.yaml`

> ✅ **Закрыт 2026-05-10.** `claude-memory-layout.md` обновлён: `monitor-reports/` и `stale_flags.yaml` добавлены в структуру, таблицу и раздел D3-исключений.

---

### Layout-doc упоминает `audits/`, но реальность в `domains/`

> 📋 **→ TODO [RMR-1](../TODO.md#rmr-1).** Уже трекируется.

---

### Schema-mismatch: factor names в portfolio-scenario-stress — «mapping нигде нет»

> 🤖 **Галлюцинация. Не проверяй повторно.**
>
> **Факт:** mapping-таблица internal-format → canonical **существует** в `skills/portfolio-scenario-stress/references/input-adapters.md` строки 22–35. Проверено 2026-05-10.
>
> LLM перед запуском `compute_per_position.py` делает rename по этой таблице. Скрипт ожидает canonical-имена (`brent`, `cbr_rate`, …) — это правильное разделение ответственности.

---

### Schema-divergence: `confidence` vs `robustness` в HST assumptions

> 🤖 **Галлюцинация. Не проверяй повторно.**
>
> **Факт:** оба spec-файла используют `robustness`:
> - `_shared-references/events-yaml-spec.md:143,560` → `robustness: MEDIUM`
> - `skills/hypothesis-stress-tester/references/hst-events-yaml-spec.md:26` → `robustness: HIGH|MEDIUM|LOW`
>
> Расхождения между spec-файлами нет. Если в реальных артефактах на Synology встретится `confidence:` вместо `robustness:` — это баг конкретного файла, не системный.

---

### `weekly-bonds-review` отсутствует в save-to-library dispatch

> 🤖 **Галлюцинация. Не проверяй повторно.**
>
> **Факт:** строка присутствует в `skills/save-to-library/SKILL.md:61`:
> ```
> | Еженедельный обзор — облигации | YAML с type: weekly-bonds-review … | F |
> ```
> Проверено 2026-05-10.

---

## P1 — общие баги

### Mojibake в кириллических артефактах

> ⚠️ **Не верифицирован** — нет доступа к файлам Synology в сессии проверки 2026-05-10. `forecasts/ai-capex-slowdown-2026-2026-04-30.md` не проверялся. Скрипт `weighted_consensus.py` в порядке (UTF-8, тесты зелёные). Если симптом (`**` посередине кириллического слова) встретится — искать в шаблонах output FCA/HST, добавлять regex-проверку `\w\*\*\w` в save-to-library E2.

---

### Валидация перед save-to-library не обязательна

> 🤖 **Галлюцинация. Не проверяй повторно.**
>
> **Факт:** `skills/save-to-library/references/workflow-bcde.md` содержит явный blocking шаг **B6.0**:
> ```
> B6.0. Pre-write validation (blocking):
> python3 scripts/assemble_artifact.py validate-forecast <yaml_content>
> ```
> При `severity: blocking` файл не пишется. Проверено 2026-05-10.

---

### LOW-only sources без warning при save

> 📋 **→ TODO [MS-1](../TODO.md#ms-1).** Уже трекируется.

---

### `null`-значения обязательных полей проходят validate_library.py

> 🤖 **Галлюцинация. Не проверяй повторно.**
>
> **Факт:** `skills/revise-memory-remote/scripts/validate_library.py:90`:
> ```python
> missing_required = [f for f in REQUIRED_AUDIT_FIELDS if frontmatter.get(f) is None]
> ```
> `.get(f)` возвращает `None` и при отсутствии ключа, и при `value: null`. Оба случая пойманы. Проверено 2026-05-10.

---

## P2 — мёртвые/недоиспользованные shared-refs

### `_shared-references/model-routing.md`

> ⚠️ **Не баг, намеренная архитектура.** Глобальный `model-routing.md` — краткий superset. Детальные локальные версии у `retrospective-forecast-audit` и `ru-portfolio-advisor` содержат скилл-специфичное содержимое. Обе сосуществуют намеренно — не удалять.

### `_shared-references/source-discovery.md`

> ⚠️ **Не баг.** Используется `forecast-confidence-applier`. Достаточная причина быть в shared. Если окажется что нужен только одному скиллу — переместить тогда.

---

## P2 — формат `_sync_log.md`

> ⚠️ **Частично покрыт [STL-4](../TODO.md#stl-4).** STL-4 сверяет шаблон из `workflow-bcde.md` с реальным файлом. `memory-sync/SKILL.md:233–250` определяет markdown-блоки (`## Sync {дата}`), не YAML — это нормально. Реальный файл на Synology нужно сверить отдельно.

---

## P2 — fallback Transport B → A не прозрачен

> 📋 **→ TODO [CS-1](../TODO.md#cs-1).** Добавлен 2026-05-10. Требует явного inline warn во всех writing-скиллах при переключении на Transport A.

---

## P3 — bootstrap risk для trust-профилей

> 📋 **→ TODO [RPA-2](../TODO.md#rpa-2).** Уже трекируется.
