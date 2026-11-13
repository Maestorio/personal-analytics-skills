# Дополнительные функции после аудита: Режим A (SAVE) и Режим B (EXPORT)

> Вынесено из SKILL.md дословно при дроблении 2026-08-12 (этап 3, подготовка Max → Pro).

Активируются ТОЛЬКО после явного запроса пользователя одного из режимов.

### Режим A: SAVE (сохранение аудита в библиотеку через save-to-library)

Цель — занести полный файл аудита (содержимое отчёта + YAML frontmatter) в библиотеку `Claude-Memory/{subfolder}/`. Транспорт — **Synology mount** (`~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/`). Компактный [lib]-профиль в auto-memory формируется автоматически при ближайшем запуске `memory-sync`.

**Поток данных:**

```
audit (этот скилл)
   ↓
save-to-library  →  пишет через Synology mount
   ↓
validate YAML  →  determine subfolder  →  Claude-Memory/{subfolder}/{source}-{period}.md
                                                      ↓
                                          Claude-Memory/reports/{source}-{period}.docx  ← если docx был создан
                                          Claude-Memory/reports/{source}-{period}.md    ← иначе markdown
                                                      ↓
                                              INDEX.md (subfolder + master)
                                                      ↓
                                       [user runs memory-sync]
                                                      ↓
                                      [lib] {source} в auto-memory (≤500 симв.)
```

**Структура итогового файла аудита** — в `references/output-templates.md`, секция «Audit File for save-to-library» (заменила прежнюю «Memory Profile»). Структура содержит обязательный YAML frontmatter (`source`, `period`, `audit_type`, `audit_date`, `trust` по subdomain'ам, `pin`, `theses_count`, `hit_rate`, `alpha_generation`, `avg_value`, `skill_version`, `meta_audit_used`, `data_source`, `deep_research_used`) + полный текст отчёта (§0–§7).

**Pre-check субдоменов (до генерации YAML — обязательный шаг):**

Перед тем как формировать trust-таблицу, явно перечисли все тематические треки, которые покрыты тезисами T1–TN аудита:

- Выпиши каждый тематический кластер (например: нефтяные цены, ставки ФРС, ВВП США, ВВП России, ВВП Китая, рецессия, акции S&P, и т.д.)
- Каждый кластер → отдельная запись в trust. **Нельзя молча сворачивать** один тематический трек в другой (us-macro-gdp ≠ recession-call; ru-economy-growth ≠ emerging-markets; china-macro ≠ emerging-markets). Если тезис покрывает GDP-прогноз отдельной страны — это отдельный трек.
- Если канонического subdomain для кластера нет в `references/subfolder-mapping.md` — использовать нестандартное имя с пометкой в `trust` и отметить нестандарт при сохранении в save-to-library.

Только после этой сверки — формировать YAML.

**Процесс:**
1. Сгенерируй YAML frontmatter по шаблону. Все обязательные поля (`source`, `audit_date`, `trust`) — обязательно заполнены, без `?`/`tbd`.
2. Покажи пользователю YAML frontmatter и одну строку summary trust в формате `[lib]` (для предпросмотра, как это будет выглядеть в памяти после memory-sync). Дословно: «Готов передать в save-to-library такой YAML + полный текст аудита: [YAML]. Сводный trust для [lib]-кеша после memory-sync будет: [summary]. Подтвердить?»
3. Получи явное подтверждение (да/нет).
4. Только при «да» — вызови скилл `save-to-library`, передав готовый файл аудита (YAML frontmatter + полный текст). save-to-library валидирует YAML, определит subfolder, проверит дубли, сохранит `.md` в `Claude-Memory/{subfolder}/{source}-{period}.md`, сохранит репорт в `Claude-Memory/reports/` (docx если был создан в этом аудите, иначе markdown), обновит `INDEX.md` (subfolder + master).
5. Если save-to-library озвучит сомнения (неоднозначный subfolder, найден дубль, не проходит auto-inclusion в memory) — передай вопросы пользователю как есть, не угадывай ответы.
6. После успешного сохранения save-to-library предложит запустить `memory-sync` — это отдельный скилл, отдельный confirmation flow. Не запускай автоматически.

**Если save-to-library недоступен** (скилл не установлен, Synology недоступен, LIBRARY_ROOT не найден):
- Сначала попробуй установить save-to-library или подсказать пользователю про настройку пути Synology Drive.
- Только как последнее средство — fallback на старое поведение «компактная запись (≤500 симв.) через `memory_user_edits` с командой `add`». Явно предупреди пользователя: «save-to-library недоступен; пишу только в локальную память. При следующем запуске memory-sync это перезатрётся, если на Synology не появится исходный файл аудита». Это antipattern — не используй без необходимости.

**Если для источника уже есть аудит на Synology того же `period`** — save-to-library спросит, заменить ли. Если предыдущий аудит был сделан этим же скиллом и эта сессия — обновление, выбирай `replace`. Если новый аудит покрывает другой `period` или применяет другую методологию — выбирай `add new`.

### Режим B: EXPORT FOR SKILL (выжимка для встраивания в другой skill)

Цель — self-contained Markdown-блок, который пользователь вручную вставит в SKILL.md другого скилла.

Шаблон — в `references/output-templates.md`, секция «Skill Export Block».

Блок выдавай в кодовом блоке Markdown, чтобы пользователь мог скопировать как есть.

### Режим A+B: оба варианта последовательно

1. Сначала Режим A (SAVE через save-to-library на Synology). Дождись успешного завершения сохранения и сообщения от save-to-library.
2. Только после этого — Режим B (EXPORT-блок для встраивания в SKILL.md другого скилла). Export-блок может ссылаться на сохранённый файл («Полный аудит: `Claude-Memory/{subfolder}/{filename}.md`») вместо дублирования всех метрик, чтобы экспортируемый блок оставался компактным.

