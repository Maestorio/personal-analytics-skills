# File Naming Conventions

## Общее правило

**Lowercase kebab-case** для всех файлов и папок, кроме `INDEX.md` и содержимого
`Claude-Memory/_shared/` (там UPPER_CASE для отличия инфраструктуры от результатов).

| Класс | Регистр | Примеры |
|---|---|---|
| Артефакты скиллов (результаты работы) | lowercase | `portfolio-2026-05-03.json`, `ru-rates-2026-2026-04-30.md` |
| Папки | lowercase | `forecasts/`, `macro-chain/`, `Portfolio/snapshots/` |
| Структурный маркер | UPPER | `INDEX.md` |
| Инфраструктура _shared/ | UPPER_CASE | `DEPENDENCY-MAP.md`, `SOURCE-REGISTRY.md` |

---

## Slug-правила

- Символы: `[a-z0-9-]`, кириллица → ISO 9 транслит
- Стоп-слова убираются: `и в на для что ли будет может с по от из о the a of to is at`
- Первые **3 значимых слова**, разделитель `-`
- Максимум **30 символов** (обрезка по последнему дефису)
- Внутри одного yaml `id` уникальны; коллизия → суффикс `-2`, `-3`, …

| Исходный текст | Slug |
|---|---|
| Проверить рост ставки ЦБ выше 21% | `rost-stavki-cb` |
| OPEC announces production cut | `opec-production-cut` |
| Инфляция в РФ выше 7% к концу 2026 | `inflyatsiya-rf-7pct` |
| Brent below $50/bbl | `brent-50-bbl` |

---

## Паттерны имён файлов по типу

| Тип | Папка | Имя файла |
|---|---|---|
| Прогноз (FCA, Tier 1) | `forecasts/` | `{topic-slug}-{forecast-date}.{md,yaml}` |
| Прогноз со стрессом (Tier 2) | `forecasts/` | `{topic-slug}-{forecast-date}-stress.{md,yaml}` |
| Сценарная матрица | `scenarios/` | `scenario-{topic-slug}-{date}.{md,yaml}` |
| Коллекция прогнозов | `forecast-collections/` | `fc-{source-slug}-collection-{date}.md` |
| Ретро-аудит (полный отчёт) | `reports/` | `{YYYY-MM-DD}-{source-slug}-{period}.{md,docx}` |
| Профиль источника (сжатый, парный к ретро-аудиту) | `domains/{domain}/` | `{source-slug}-{period}.md` (без префиксов `lib_` и суффиксов `-audit`) |
| Макро-снапшот | `macro-snapshots/` | `ru-{date}.md` |
| Портфельный снапшот | `Portfolio/snapshots/` | `portfolio-{date}.json` |
| Стресс портфеля | `Portfolio/stress/` | `stress-{date}-{source}.{md,yaml}` |
| Еженедельный обзор | `Portfolio/weekly-reviews/` | `weekly-review-{date}.yaml` |
| Интегрированный вид | `Portfolio/integrated-views/` | `integrated-view-{date}.md` |
| Macro-chain output | `macro-chain/` | `macro-input-{date}.yaml` |
| Решение по бумаге (`decision@1`) | `Portfolio/decisions/` | `{YYYY-MM-DD}T{HHMM}-{KEY}.json` — время МСК записи, `KEY` = тикер или ISIN как есть; имя = `id` решения; ставит `decision_write.py`, существующее имя — ошибка, не перезапись |
| Годовой архив определений условий | `Portfolio/` | `conditions-archive-{YYYY}.yaml` |
| Архив цикла машиночитаемости | `_archive/data-structures/` | папка `{YYYY-MM-DD}T{HHMM}-step{N}/` на каждый прогон `archive_pre_ds.py` + `MANIFEST.md`; внутри — пути источников как в корне |

`{date}` — всегда `YYYY-MM-DD`. `{forecast-date}` — дата написания прогноза.

---

## Stress-pair slug rules

Stress-расширение прогноза (`hypothesis-stress-tester`) сохраняется параллельной парой к Tier 1, не патчем поверх:

- Имя файла: `<base-slug>-stress.{md,yaml}` рядом с `<base-slug>.{md,yaml}` в той же папке (`forecasts/` для макро/геополитики; `Portfolio/stress/` — отдельная конвенция, см. таблицу выше).
- `<base-slug>` — точно тот же slug, что у Tier 1 пары; **не** ремисливать заново.
- Slug uniqueness внутри одного YAML-файла обязательна (`assumptions[].id`, `monitoring[].id`, `thresholds[].id`, `falsifiers[].id`, `agents[].id`); коллизия → суффикс `-2`, `-3`, …
- Между парой `<base>.yaml` и `<base>-stress.yaml` slug'и могут совпадать (это разные namespaces).
- Tier 1 пара может физически отсутствовать в момент сохранения stress (HST запущен на тексте без FCA). В этом случае `save-to-library` создаёт Tier 1 stub с `central_estimate: null` — slug Tier 1 = base из stress.

---

## Singleton-конвенции (METH-2)

Некоторые файлы — **singleton** (не дата в имени, один файл на весь Portfolio/); каждый пишет один писатель:

- `Portfolio/conditions.yaml` — определения условий `conditions@2` (`apply_condition.py`: правка = новая версия, снятие = `withdrawn`);
- `Portfolio/conditions-state.json` — состояние условий `conditions-state@1` (только hub-api, только дописывание событий);
- `Portfolio/security-attrs.json` — справочник бумаг `security-attrs@1` (`security_attrs.py`);
- `Portfolio/plan.json` + `plan-journal.jsonl` — план владельца и журнал правок (hub-api).

Скрипт заменяет файл целиком через временный файл + `os.replace`; история — версиями записей внутри файла или в годовом
архиве. `Portfolio/gate-reviews.yaml` и `gate-reviews-archive-{year}.yaml` **упразднены** (schema.md §4.4): статус гейта
считается из последнего решения, файлы удаляются при переключении (шаг 17).

---

## Примечание: устаревшие конвенции

- `lib_*.md` — НЕ используется. Профили источников: `{source-slug}-{period}.md`.
- `Scenarios/` (с заглавной) — НЕ используется. Папка: `scenarios/` (lowercase).
- `PORTFOLIO-*.json`, `MACRO-INPUT-*.yaml`, `STRESS-*.yaml` — UPPER_CASE устарел. Все новые файлы — lowercase.
- `audits/`, `_audits/` — НЕ используются. Полные ретро-аудиты — в `reports/`. Сжатые профили — в `domains/{domain}/` (атомарной парой через save-to-library Workflow D).
- `{source-slug}-{period}-audit.md` в `domains/` — НЕ используется. Суффикс `-audit` не нужен: имя профиля и так лежит в `domains/`.
- `_sync_log (N).md`, `_sync_log_append-*.md`, `INDEX (N).md` — НЕ используются. Это следы MCP create без edit; должны быть слиты в основной `_sync_log.md` / `INDEX.md` при ревизии.
