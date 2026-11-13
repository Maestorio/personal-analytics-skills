# Stage 2 — output-spec: канонический формат `2_similarity.md`

> **low freedom — эмитить ДОСЛОВНО.** Единственный канонический контракт формата
> артефакта `2_similarity.md`. Таксоны и пороги сверяются со скриптом
> `similarity_score.py` и downstream-стадиями. Правишь формат/таксон — правишь
> **здесь**, затем синхронизируешь копии (часть 2); `tests/test_format_contract.py`
> проверит. В рантайме файл не грузится.

---

## Часть 1 — Контракт формата (канон)

### Категории автора (5, канонические имена)
`HIGH` · `MEDIUM` · `LOW` · `OUTLIER` · `UNSCORED`. Считает **скрипт**
(`similarity_score.py`), LLM их не назначает. Пороги (default):
- `HIGH` — total_score ≥ **7.0** (`DEFAULT_HIGH_THRESHOLD`).
- `MEDIUM` — ≥ 5.0; `MEDIUM ≥ 6.5` → `reading_list_extended`.
- `LOW` — < 5.0.
- `OUTLIER` — семантически релевантен профилю, но низкий total (LLM ставит
  `outlier_signal`, скрипт финализирует).
- `UNSCORED` — известно < 3 компонентов (`UNSCORED_KNOWN_THRESHOLD`).

`in_reading_list` = `HIGH` + `OUTLIER`. **Запрещены** выдуманные таксоны
(Tier-1/2/3 и т.п.) и шкала 0–100 — только 0–10.

### Язык таксона: ключ — в YAML, ярлык — в теле

Одна категория, две формы. **YAML и JSON-payload — английский ключ; тело
`.md` — русский ярлык.** Ярлык не переводится моделью: копируется вербатим
из `category_label` (автор) / `severity_label` (warning) output'а
`similarity_score.py`. Источник переводов — `scripts/data/taxonomy.json`.

| Ярлык в теле | Ключ (YAML / JSON) | Счётчик в YAML |
|---|---|---|
| ВЫСОКАЯ | `HIGH` | `high_similarity_count` |
| СРЕДНЯЯ | `MEDIUM` | `medium_count` |
| НИЗКАЯ | `LOW` | `low_count` |
| ОСОБЫЙ СИГНАЛ | `OUTLIER` | `outlier_count` |
| БЕЗ ОЦЕНКИ | `UNSCORED` | `unscored_count` |

Severity warnings в теле: `critical` → **критично**, `borderline` →
**погранично**, `info` → **инфо**.

**Что остаётся английским в теле** (решение Р5 + якоря парсинга):
компонентные строки `C1 style 8→2.0` (имена компонентов — машинные),
`SIGNAL:`, суффиксы `[user_added]` / `[low_confidence: N/6]`, заголовки секций.

### 6 компонентов (канонические имена, порядок)
`style` · `focus` · `pace` · `independence` · `depth` · `demo`
(`COMPONENT_NAMES` в `similarity_score.py`). Шкала каждого — **0–10**.
total_score считает скрипт по весам архетипа; null-компонент → скрипт
перераспределяет вес. Переименовывать компоненты ЗАПРЕЩЕНО (`season` вместо
`pace` и т.п. — провал).

### Структура output (§8)
- `## Распределение` — counts по 5 категориям (строки — русскими ярлыками:
  `| ВЫСОКАЯ (балл ≥ 7.0) | N | NN% |`) + проверка «ВЫСОКАЯ не пуста / не
  доминирует».
- Reading list — три H3-подсекции: `### Обязательные (ВЫСОКАЯ)` /
  `### ОСОБЫЙ СИГНАЛ` / `### Расширенный список (СРЕДНЯЯ ≥ 6.5)`;
  `## БЕЗ ОЦЕНКИ с outlier-сигналом` — отдельной секцией.
- Per-author блок: total_score, разбивка по 6 компонентам (weighted_contributions),
  ярлык категории, confidence, reasoning «Тянет вверх / Тянет вниз».
- `warnings` — русским текстом, severity словом (`критично:` / `погранично:` /
  `инфо:`), включая anti-bloat: `OUTLIER > 30%` (`OUTLIER_BLOAT_THRESHOLD`).

### YAML-шапка
`trip_id`, `stage: 2_similarity`, `archetype_used`, `weights_source`,
`thresholds_used`, опц. `partial_parse`/`llm_fallback_authors`/
`skipped_authors_count` (при opt-in fallback парсера).

---

## Часть 2 — Реестр копий (где формат продублирован в рантайме)

- **Продюсер:** `stage2-similarity.md` §1 (5 категорий + 6 компонентов), §6.2
  (rubric компонентов), §8 (формат output).
- **Mini-spec:** `SKILL.md` (5 категорий, 6 компонентов, шкала 0–10 — грузится
  всегда, model self-check).
- **Скрипт (контракт чисел):** `similarity_score.py` — `COMPONENT_NAMES`,
  категории `HIGH|MEDIUM|LOW|OUTLIER|UNSCORED`, `DEFAULT_HIGH_THRESHOLD`,
  `OUTLIER_BLOAT_THRESHOLD`.
- **Потребители:** Stage 3 (`stage3-poi.md`) — читает reading-list (HIGH+OUTLIER+
  extended MEDIUM) и категории авторов; export-парсер Stage 2.

---

## Часть 3 — Известные дрейфы / на что смотреть при чтении `2_similarity.md`

- **Срезание углов на не-Opus модели** (Sonnet без thinking / Haiku-fallback после
  safety-pause): выдуманные `Tier-1/2/3`, шкала 0–100 вместо 0–10, переименованные
  компоненты (`season` вместо `pace`), скрипт не запущен. Model self-check Stage 2
  блокирует Haiku.
- **OUTLIER-bloat:** на структурном конфликте профиля с выборкой (Vietnam: «прав
  нет» vs мото-ориентированные авторы) доля OUTLIER уходила к 51%. `> 30%` →
  warning; если воспроизводится — сигнал менять scope или ужесточать rubric §6.4.
- **null-компоненты:** «не указано» в карточке → компонент `null` в payload (не 0);
  скрипт перераспределит вес. Подмена null на 0 искажает score.
