---
name: forecast-confidence-applier
description: >
  Агрегирует прогнозы из 3–7 источников через web_search и применяет trust weights
  из INDEX.md. Выдаёт filtered consensus с TL;DR modal scenario и дисконтом на bias.

  Используй ОБЯЗАТЕЛЬНО когда пользователь спрашивает: «что говорят про X», «прогноз
  по Y на 2026/2027», «consensus по теме», «оценка экспертами», «кто что прогнозирует
  по нефти/ставке/выборам/геополитике», «взвесь мнения аналитиков», «будет ли
  война/кризис/конфликт между X и Y».

  Симметрия атрибуции обязательна: для асимметричных запросов («будет ли X атаковать Y»)
  карта лагерей строится с обеих сторон через references/perspective-maps.md или
  Full-auto. Контр-лагерь без представительства → asymmetry warning.

  Домены: геополитика, sell-side РФ, global banks, tech-CEO, ru-macro. Выход на
  русском. НЕ делает собственных прогнозов и рекомендаций к покупке/продаже.

  НЕ активировать на: исторические прогнозы (→ retrospective-forecast-audit);
  просьбы сделать прогноз самому Claude; fact-checking без прогнозной компоненты.
shared_refs: [transport-layer, events-yaml-spec, yaml-schemas, file-naming, audit-frontmatter-schema, source-discovery, scenario-yaml-spec]
bundle_scripts: [fca_output_checks.py, scenario_axis_weights.py]
---

# Forecast Confidence Applier

Агрегирует текущие прогнозы по теме, применяет веса доверия из библиотеки аудитов
и выдаёт взвешенный консенсус. Не делает собственных прогнозов — только
агрегирует чужие с поправкой на track record.

## Inputs / Outputs

**Inputs:**
- Тема / вопрос прогноза ← пользователь, текст
- Trust-веса источников ← `Claude-Memory/INDEX.md` через Synology mount
- Прогнозные материалы из 3–7 источников ← web_search

**Outputs (как artefact в чат):**
- Filtered consensus + Events YAML Tier 1 → пользователь проверяет → save-to-library кладёт в `Claude-Memory/forecasts/<slug>-<date>.{md,yaml}`
- Черновик той же пары в `Claude-Memory/_drafts/` (служебная зона, Шаг 6) — источник для save-to-library, чат не теряет текст при сжатии контекста

**Upstream скиллы:** —
**Downstream скиллы:** hypothesis-stress-tester (опц.), portfolio-scenario-stress, save-to-library
**Shared refs:** transport-layer, events-yaml-spec, yaml-schemas, file-naming, audit-frontmatter-schema

---

## Принципы

0. **Язык вывода — русский** (как в retrospective-forecast-audit).
1. Ты агрегатор, не аналитик — твоя задача корректно взвесить чужие мнения,
   а не добавить своё.
2. Trust weight берётся ТОЛЬКО из INDEX.md. Никогда не назначай вес «по ощущениям»
   от репутации источника — это ключевое ограничение, иначе смысл всей системы теряется.
3. Не аудированный источник = вес 0 в consensus. Его прогноз показывается отдельно
   с пометкой «не аудирован» + рекомендацией прогнать через retrospective-forecast-audit.
4. Если всё не укладывается в 6 месяцев — помечай «нет свежей позиции».
5. **Горизонт прогноза** — фиксируй горизонт каждого источника (на какую дату/период
   дан прогноз). Если горизонты совпадают — укажи один. Если расходятся — посчитай
   взвешенный горизонт (HIGH x 1.0, MEDIUM x 0.5) и укажи диапазон. Если горизонты
   принципиально несравнимы (напр., «конец 2026» vs «2030+»), разбей вывод по горизонтам.
6. **Повторный аудит**: если источник был в INDEX как «не аудирован» на момент прошлого
   прогноза, но с тех пор был аудирован и добавлен в INDEX — при следующем запуске
   пересчитай его вес из INDEX и переклассифицируй. Прогнозы не пересобираются
   автоматически, но новый snapshot должен отражать актуальное состояние INDEX.

## Reference-файлы

- `references/transport-layer.md` — Synology mount для Claude-Memory; читай в Шаге 0
- `references/source-discovery.md` — списки источников по доменам + паттерны web_search
- `references/perspective-maps.md` — **глобальный справочник карт лагерей** для тем
  с поляризованными позициями (geopolitics, ru-macro дебаты, ru-sellside, global-banks,
  tech-ceo). Используется в Шаге 1.5 ДО Full-auto: если карта для темы есть — берём её.
- `references/trust-application.md` — правила маппинга INDEX.md → вес
- `references/index-reader.md` — формат INDEX.md и правила парсинга
- `references/output-template.md` — шаблон вывода с примерами и anti-patterns
  (включая TL;DR modal scenario, asymmetry warning, Events YAML блок)

Читай нужный reference-файл перед соответствующим шагом, а не все сразу.

## Скрипты

- `scripts/weighted_consensus.py` — детерминированный расчёт filtered consensus:
  weighted/unweighted median, P10/P90, split по позициям, weighted horizon,
  confidence, next_due. Используется в Шагах 5 и 6 (Events YAML). Не зависит
  от внешних библиотек, только stdlib. Тесты: `tests/test_weighted_consensus.py`.

  **Правило:** все числовые расчёты filtered consensus и формула confidence —
  только через скрипт, никогда вручную. Это устраняет арифметические ошибки
  и фиксирует контракт с save-to-library.

---

## Workflow (7 шагов + подшаг 1.5 — или 6 в Lite-режиме)

### Шаг 0 — Транспорт

Прочитай `references/transport-layer.md`. Транспорт один — Synology mount.

Выполни проверку доступности:

```
LOCAL_LIBRARY_ROOT = ~/Library/CloudStorage/SynologyDrive-home/Claude-Memory
```

`Glob("*", path=LOCAL_LIBRARY_ROOT)` — если пусто или ошибка → вызвать `request_cowork_directory`,
объяснив пользователю что нужен доступ к папке Synology Drive. В каждом новом чате Cowork
доступ нужно выдавать заново — это ожидаемое поведение, не признак недоступности Synology.
Дождаться предоставления доступа и повторить Glob.

Если Synology недоступен и после этого — остановиться и сообщить пользователю.
**Bash-пути не использовать.**

---

### Шаг 1 — Domain Detection

Определи домен запроса. Это влияет на то, какие источники искать.

| Домен | Признаки в запросе |
|---|---|
| `geopolitics` | конфликты, санкции, выборы, геополитика, НАТО, война |
| `ru-sellside` | акции MOEX, облигации РФ, целевые цены на эмитентов |
| `global-banks` | глобальные рынки, S&P, нефть, EM, ставки Fed/ECB |
| `tech-ceo` | AI, LLM, чипы, Big Tech, прогнозы CEO |
| `ru-macro` | ключевая ставка ЦБ РФ, инфляция, ВВП РФ, курс рубля |

Если запрос смешанный (например, «ставка ЦБ и рубль»), собери источники из обоих
доменов. Прочитай `references/source-discovery.md` чтобы получить списки источников
и паттерны поиска для выбранного(ых) домена(ов).

---

### Шаг 1.5 — Карта лагерей. Развилка по типу FCA

Цель шага — зафиксировать камппы **до/во время** сбора источников. Какие именно камппы строятся, зависит от того, что строит FCA:

- **Шаг 1.5A — точечная атрибуция (Layer 1 marginal)**: камппы возникают **из данных post hoc** (тематические позиции, например «монетаристы / структуралисты», «Iran-side / Atlantic-side», «bull / bear»). Цель — охватить все значимые позиции при поиске источников и зафиксировать `camp_distribution` для формулы confidence Layer 1. **Это вся текущая логика 1.5a → 1.5b → 1.5c → перечислены ниже.**

- **Шаг 1.5B — сценарная атрибуция (Layer 2 conditional)**: камппы **уже заданы** scenario YAML (`A`/`B`/`C`/`D`). Работа FCA — приклеить каждый источник к одному из существующих сценариев по контенту его прогноза. **Никаких подкампов внутри сценария** — расхождение по величине внутри Sc-A это просто широкий range/CI у Sc-A, не второй уровень анализа. Раздел ниже после 1.5c.

> **Сосуществование 1.5A + 1.5B в одной сессии:**
>
> Для **Type 1 isolated** FCA → нужен только **Шаг 1.5A** (Layer 1 marginal — `forecast.central_estimate`).
>
> Для **Type 2 conditional** FCA → нужны **оба шага**:
>  - **1.5A → Layer 1 marginal** (`forecast.central_estimate` + Layer 1 confidence) — используется `ru-portfolio-advisor` и `portfolio-integrated-view`.
>  - **1.5B → Layer 2 conditional** (`conditional_on_scenarios.by_scenario.{A,B,C,D}`) — используется `portfolio-scenario-stress`.
>
> Это **один FCA-запуск, два слоя**: источники грузятся один раз, прогон `weighted_consensus.py` идёт 5 раз — один прогон без сценарной фильтрации (Layer 1) + 4 прогона с атрибуцией per scenario (Layer 2). Финальный forecast YAML содержит оба слоя + `coherence_diagnostic` (расхождение Layer 1 vs Layer 2).
>
> **Anti-pattern:** не **смешивать камп-семантики** в одной карте лагерей (например, не пытаться построить «bull-within-Sc-A» как отдельный камп). 1.5A и 1.5B — две параллельные системы атрибуции на одной сессии, каждая со своим назначением.

---

## Шаг 1.5A — Карта позиций для Type 1 (точечная FCA)

Применяется, когда строится одна marginal-оценка (`forecast.central_estimate` + `confidence`) без сценарной декомпозиции. Цель шага — зафиксировать карту позиций **до** сбора источников, чтобы поиск охватил все значимые лагеря, включая те, которых нет в дефолтных списках `source-discovery.md`. Дефолтные списки однородны по позициям (например, `geopolitics` — только западные think tanks), что создаёт риск ложного консенсуса из источников одного лагеря.

---

#### Подшаг 1.5a — Mandatory-detection: когда Full-auto обязателен

**Пропуск Шага 1.5 (режим Lite) ЗАПРЕЩЁН** на запросах со следующими признаками
(вне зависимости от формулировки пользователя):

| Признак | Пример |
|---|---|
| Асимметричная атрибуция ответственности | «будет ли Россия атаковать НАТО», «приведёт ли политика ЕС к кризису» |
| Тема входит в `references/perspective-maps.md` (по триггер-таблице в начале файла) | Иран, Тайвань, ставка ЦБ РФ, US recession, AGI timeline и т.д. |
| Конфликтная домен-тема (`geopolitics` + ключевые слова: war, attack, invasion, escalation, aggression, retaliation, sanctions) | любые формулировки про военные/санкционные сценарии |
| Политически-полярная тема (`ru-macro` + ставка/инфляция; `ru-sellside` + национализация/возврат активов) | ставка ЦБ, инфляция РФ, разворот РФ-Запад |

Если хотя бы один признак выполнен → переходи в Full-auto (или Full-guided, если
пользователь дал свою карту). Lite-режим оставляй только для нейтральных
числовых запросов без поляризации (напр., «какой forecast по нефти Brent на конец 2026»).

---

#### Подшаг 1.5b — Источник карты лагерей (приоритет: готовая → Full-auto)

**Приоритет 1 — готовая карта из `references/perspective-maps.md`:**

1. Прочитай `references/perspective-maps.md`.
2. Сопоставь тему запроса с триггер-таблицей в начале файла.
3. Если найдено совпадение → возьми карту лагерей из соответствующего раздела
   как стартовую. Дополнения/уточнения от Full-auto допустимы, но удаление
   лагерей из готовой карты требует обоснования в выводе.

**Приоритет 2 — Full-guided** (пользователь явно дал список лагерей):

Принимай в свободном формате. Ориентир:

```
- Монетаристы [Dominant]: инфляция — главный враг, ставка оправдана
- Структуралисты [Significant]: высокая ставка убивает инвестиции
- ВПК-реалисты [Minority]: ставка нерелевантна в военной экономике
```

Если пользователь не указал уровень — определи сам по таблице уровней ниже.

**Приоритет 3 — Full-auto** (карты нет в файле, пользователь не дал свою):

Алгоритм построения:

1. Проверь память по домену (из Шага 1). Если есть контекст — строй карту из него.
   Если памяти нет — строй из знания Claude с пометкой в выводе:
   *«карта построена без опоры на perspective-maps.md и аудиты — возможны пропуски»*.
2. Выяви 2–5 лагерей с несовместимыми базовыми тезисами.
   Лагерь — это позиция по конкретному вопросу, а не организация.
3. Для каждого: core claim (1 строка) + типичные носители (3–7 институций) + уровень.
4. Fringe-позиции (нет институциональной базы) — не включать в карту.
5. **После завершения работы**: предложи пользователю добавить эту карту в
   `references/perspective-maps.md` (это growing reference; см. §6 в файле).

---

#### Подшаг 1.5c — Symmetry attribution check

После построения карты (любым из трёх путей выше) обязательно проверь:

> Если запрос содержит асимметричную атрибуцию ответственности (формулировки «будет ли
> X атаковать Y», «приведёт ли политика X к кризису», «накопление вооружений Y вызовет
> войну»), карта обязана содержать как минимум один лагерь с обратной атрибуцией.

**Если контр-лагерь отсутствует:**
1. Проведи целевой поиск по альтернативной стороне (примеры паттернов — в
   `references/perspective-maps.md`, разделы по конкретным конфликтам).
2. Если контр-лагерь не найден в institutional discourse — зафиксируй явно
   в выводе блок **«⚠️ Asymmetry warning»** (формат — в `references/output-template.md`).
3. Не пытайся сбалансировать карту fringe-источниками или частными мнениями
   без институциональной базы.

---

#### Уровни лагерей

| Уровень | Критерий |
|---|---|
| **Dominant** | Позиция большинства институциональных экспертов в домене |
| **Significant** | Есть институциональная база; регулярно цитируется Tier-1 агрегатором (Reuters/AP/AFP/Bloomberg) или ведущим национальным деловым изданием региона источника |
| **Minority** | Академическая или экспертная ниша; редко присутствует в мейнстримных изданиях |
| **Fringe** | Нет институциональной базы → не включать в карту |

---

#### Расширенный поиск для нестандартных лагерей

Для лагерей, не покрытых дефолтными списками из `source-discovery.md` (типичный случай —
лагеря из `perspective-maps.md` для не-Atlantic стороны: Iran-side, Russia-side,
China-side, regional realists), сгенерируй паттерн поиска по аналогии:

`"{представитель лагеря}" "{тема}" прогноз/forecast 2026`

Конкретные представители каждого лагеря — в таблицах `perspective-maps.md`.

---

#### Checkpoint покрытия — обязателен перед переходом к Шагу 4

Зафиксируй статус явно в выводе:

```
Покрытие лагерей: [Монетаристы ✓] [Структуралисты ✓] [ВПК-реалисты ✗ — не найдено]
Symmetry check: ✓ / ⚠️ asymmetric (см. блок warning в выводе)
```

- **Dominant**: жёсткое требование — нет источника → проведи дополнительный поиск.
  Если и после него не найдено → зафиксируй «лагерь не представлен в доступных
  источниках» и двигайся дальше.
- **Significant**: мягкое — если не найдено после одного поиска, фиксируй пробел.
- **Minority**: опционально.

---

## Шаг 1.5B — Сценарная атрибуция для Type 2 (conditional FCA)

Только для **Type 2**: лагеря уже заданы scenario YAML (`A`/`B`/`C`/`D`), FCA
атрибутирует каждый источник к существующему `scenario_id` по контенту прогноза
(D8 — динамически, не из static-поля профиля). Алгоритм, правила agnostic-источников,
формат `sources_used`/`camp_weight` и anti-patterns (включая ORCHESTRATOR_LEAK —
готовые interpretations в промпте игнорировать, читать scenario YAML самому) —
**загрузи `references/scenario-attribution.md` перед атрибуцией Type 2**.
Жёсткое ядро: оба шага 1.5A+1.5B в одной сессии; никаких подкампов внутри
сценария; Type 2 без `forecast.central_estimate` не сохранять.

---

### Шаг 2 — Existing Memory Check

Перед веб-поиском проверь, есть ли в Claude-Memory уже сохранённые прогнозы и сценарии
по теме запроса. Это позволяет обновить существующий снапшот (не создавать дубль)
или использовать сохранённые сценарии как контекст при агрегации.

```
Glob("*.md", path="{LOCAL_LIBRARY_ROOT}/forecasts/")
Glob("*.md", path="{LOCAL_LIBRARY_ROOT}/Scenarios/")
```

Из найденных файлов прочитай YAML frontmatter каждого — достаточно первых 15 строк.
Извлеки: `topic`, `domain`, `forecast_date`, `horizon_date`.

**Отбор кандидатов — широкий semantic match:**

Включи файл в список кандидатов если выполнено хотя бы одно условие:
1. **Точное совпадение**: `topic` или имя файла содержит ключевые слова из запроса
2. **Тот же домен**: `domain` совпадает с доменом текущего запроса (ru-macro, geopolitics и т.д.)
3. **Смежный субдомен**: тема файла связана с запросом через общую макропеременную
   (примеры: `ru-rates` ↔ инфляция; `usd-rub` ↔ ставка ЦБ; `oil-price` ↔ курс рубля;
   `budget-deficit` ↔ инфляция/ставка; сценарии по геополитике ↔ любой ru-macro запрос)

Исключи файлы из других доменов без смысловой связи с текущей темой.

**Если кандидаты найдены** — покажи список и задай вопрос. Жди явного ответа перед
любым продолжением. Не выбирай режим самостоятельно, даже если запрос содержит намёк
на намерение («расширить», «обновить», «дополнить» — не разрешение пропустить вопрос).

```
📂 Найдены прогнозы/сценарии, которые могут быть полезны как контекст:
- [1] {файл}: topic={topic}, дата={forecast_date}, горизонт={horizon_date}
- [2] {файл}: ...

Какие использовать? (можно несколько, можно ни один)
```

**Остановиться и ждать ответа. Не переходить к Шагу 3 без явного ответа.**

**При выборе файлов:** прочитай их полный текст и используй как дополнительный контекст
в Шагах 1.5 (карта лагерей) и 4 (агрегация источников). Не заменяет веб-поиск.

**Если кандидатов нет** → молча переходи к Шагу 3.

---

### Шаг 3 — INDEX Read

INDEX.md — источник trust-весов. Источник — Synology mount (primary source of truth).

```
LOCAL_LIBRARY_ROOT = ~/Library/CloudStorage/SynologyDrive-home/Claude-Memory
```

Алгоритм — пробуй уровни последовательно:

1. `Read("{LOCAL_LIBRARY_ROOT}/INDEX.md")` — master index
2. Не нашёл? → Для каждого subfolder (`geopolitics`, `ru-sellside`, `global-banks`, `ru-macro`, `tech-ceo`):
   `Glob("INDEX.md", path="{LOCAL_LIBRARY_ROOT}/{subfolder}/")`
3. Всё ещё ничего? → `Glob("lib_*.md", path="{LOCAL_LIBRARY_ROOT}/")` и в субпапках —
   lib-файлы содержат trust-профили напрямую
4. Только если все три уровня дали ноль → спроси пользователя о пути

**Bash-пути не использовать.** Только Read/Glob, не bash.

Детали формата и парсинга → `references/index-reader.md`.

Извлеки из INDEX.md:
- список источников с их trust-профилями по субдоменам
- для каждого источника: nearest-domain match к текущему запросу → итоговый вес

---

### Шаг 4 — Source Aggregation

Прочитай `references/source-discovery.md` для паттернов поиска.

Для каждого релевантного источника — 1 целевой `web_search` запрос.
**НЕ использовать** launch_extended_search_task (запрещён).

Сбор ведётся по двум спискам:
- **Дефолтные источники** из `references/source-discovery.md` для выбранного домена
- **Нестандартные источники** из Шага 1.5 (если был Full-guided или Full-auto)

Извлеки из результатов:
- цитата прогноза (≤15 слов оригинала + перевод если не русский)
- дата публикации
- URL первоисточника

Если источник не публиковал на эту тему за последние 6 месяцев → «нет свежей позиции».

---

### Шаг 5 — Filtered Consensus

Прочитай `references/trust-application.md` для правил применения весов и
группировки источников (HIGH / MEDIUM / LOW / IGNORE / не аудирован).

**Расчёт делегируется скрипту `scripts/weighted_consensus.py`** — это
устраняет арифметические ошибки и стабилизирует контракт с save-to-library.
Сам никогда не считай weighted median, P10/P90, confidence или next_due
вручную: сборка JSON + один вызов скрипта.

#### 5.1 Подготовь JSON-вход

Для каждого собранного в Шаге 4 источника заполни:

```json
{
  "query_domain": "ru-macro",
  "camp_distribution": {"bull": 3, "bear": 1, "neutral": 1},
  "forecast_date": "YYYY-MM-DD",
  "interval_months_override": null,
  "sources": [
    {
      "id": "stratfor",
      "name": "Stratfor",
      "value": 88.5,                    // числовой прогноз — заполнить ИЛИ position
      "position": "bullish",            // качественный — заполнить ИЛИ value
      "horizon_date": "2026-12-31",
      "applied_level": "HIGH",          // если nearest-match сделан — передай level
      "trust_profile": [                // альтернатива: список subdomain×level из INDEX,
        {"subdomain": "long-term-russia", "level": "HIGH"}  // скрипт возьмёт MAX
      ],
      "audited": true                   // false → unaudited секция
    }
  ]
}
```

`applied_level` приоритетнее `trust_profile`. Если у источника аудит есть, но
нужного субдомена нет в профиле — оставь `trust_profile: []`, скрипт вернёт
дефолт MEDIUM (см. `references/trust-application.md` §nearest-domain).

**`camp_distribution` (FCA-1, 2026-08-03) — счётчики источников по лагерям из карты
лагерей Шага 1.5.** Имена лагерей — как в твоей карте (`bull/bear/neutral` или
предметные `Iran-side/Atlantic-side/...`), скрипт считает долю по ВСЕМ ключам.
`asymmetry_warning` теперь считает СКРИПТ: доля доминирующего лагеря ≥ 0.7 → true
(порог `ASYMMETRY_CAMP_THRESHOLD`, provisional). НЕ выставляй `asymmetry_warning`
bool'ом сам — ручной bool остался только как backward-compat fallback и логируется
warning'ом `manual_asymmetry`.

#### 5.2 Вызови скрипт

```bash
cat input.json | python3 scripts/weighted_consensus.py --pretty
# или: python3 scripts/weighted_consensus.py --input input.json --output result.json
```

Скрипт возвращает:
- `kind`: `numeric` | `qualitative` | `mixed`
- **числовой режим:** `weighted_median`, `unweighted_median`, `filter_strength` (=|w−u|), `p10`, `p90`;
  при ничьей (вес делится ровно пополам между двумя значениями) `weighted_median` — их середина,
  а пара лежит в `weighted_median_tie` — назови её в отчёте, это признак малого числа источников
- **качественный режим:** `split_by_position` (count, weight_sum, high, medium для каждой позиции), `modal_position`
- `horizon`: `weighted_date`, `min_date`, `max_date` (взвешенное среднее по дням от forecast_date)
- `confidence`: посчитанный по формуле из Шага 6
- `reviews`: `interval_months` + `next_due` (для секции Events YAML)
- `n_sources`: high / medium / low_or_ignore / unaudited / in_consensus / outliers / total
- `applied_weights`: per-source диагностика (применённый вес и matched_subdomain)
- `warnings`: предупреждения скрипта

**Зависимостей нет** — только stdlib (Python 3.10+).

#### 5.3 Используй результат для отчёта

- `weighted_median` + `unweighted_median` → секция «Снимок мнений», колонка
  «filter strength» = |w−u|.
- `split_by_position` → таблица голосов по позициям.
- `horizon` → шапка отчёта (взвешенный горизонт + диапазон min/max).
- `applied_weights` → колонка «вес» в таблице «Снимок мнений».
- `confidence`, `reviews` → блок Events YAML (Шаг 6).

Прочитай `references/output-template.md` для шаблона и примеров форматирования.

**Ключевые допущения** — сформулируй 3–5 структурных допущений, на которых держится
filtered consensus. Для каждого оцени обоснованность (HIGH/MEDIUM/LOW) и чувствительность
вывода к его ложности. Самые уязвимые допущения (LOW обоснованность + Критическая
чувствительность) — главные риски прогноза. Шаблон секции — в `references/output-template.md`.

**Условия сценариев** — если прогноз сценарный, явно помечай: условия «необходимые»
(все должны выполниться одновременно) или «достаточные» (любое из них запускает сценарий).

**Сумма вероятностей** — если указываешь вероятности сценариев, они должны давать ~100%.
Остаток выноси явно как «Прочие/непредвиденные: ~X%».

**TL;DR — modal scenario** (новый обязательный блок в шапке вывода):
после Filtered Consensus выдели modal scenario — один наиболее высоковзвешенный
сценарий (для числовых: weighted median; для качественных: позиция-победитель split-а).
Помести его 1–2 строками в шапку отчёта, ОБЯЗАТЕЛЬНО с указанием вероятности (для
сценарных) или весов (для числовых). Это не нарушает агрегаторскую природу скилла —
distillation = выбор max(probability), а не собственный прогноз. Шаблон — в
`references/output-template.md` (секция «TL;DR — modal scenario»).

**Asymmetry warning** — если symmetry attribution check (Подшаг 1.5c) показал
асимметричную карту (≥3 лагерей с одной стороны, 0–1 с обратной), вывести
блок предупреждения сразу после TL;DR. Формат — в `references/output-template.md`.

---

### Шаг 5.5 — Implicit-scenario фильтрация источников (per-scenario FCA)

При FCA per scenario (когда macro-forecast-chain запрашивает оценку по конкретному
сценарию): использовать только те sources, чьи `implicit_geopolitical_scenarios.primary`
или `secondary` включает целевой `scenario_id`. Веса взвешиваются на
`trust.conditional × implicit_weight_in_scenario`.

**Phase 2 (упрощённый):** если `trust.conditional` отсутствует — использовать
`trust.marginal` (D4 backward compat). Если у источника нет поля
`implicit_geopolitical_scenarios` — включать его в маргинальный расчёт (Layer 1),
но не в per-scenario Layer 2.

---

### Шаг 5.6 — Coverage diagnostic

После FCA выдавать в чат:

```yaml
coverage_diagnostic:
  per_scenario:
    A: { sources_used: 0, confidence: DERIVED }   # ⚠ asymmetry
    B: { sources_used: 2, confidence: MEDIUM }
    C: { sources_used: 1, confidence: LOW }
    D: { sources_used: 5, confidence: HIGH }
  asymmetry_warning: "A не покрыт native sources; derived через dependency-map"
  dominant_implicit_world: D
```

`confidence` уровня сценария определяется по числу native sources:
- 0 sources → `DERIVED` (оценка выводится из маргинала через dependency-map)
- 1 source → `LOW`
- 2 sources → `MEDIUM`
- ≥3 sources → `HIGH`

---

### Шаг 5.7 — Two-marginal architecture

Каждый forecast YAML содержит **ДВЕ** marginal-оценки:

1. `forecast.central_estimate` — **Layer 1**: direct trust-weighted FCA по всем
   источникам, scenarios игнорируются. Используется для портфельных EV-решений
   и в `weekly-review`.

2. `conditional_on_scenarios.marginal.values` — **Layer 2**: computed by
   `aggregate_marginal(by_scenario, weights)` через `scripts/weighted_consensus.py`.
   Используется как sanity-check только.

Блок `coherence_diagnostic` отслеживает расхождение Layer 1 vs Layer 2:
- `severity: LOW` — расхождение <5%, в норме
- `severity: MEDIUM` — 5–15%, требует объяснения в комментарии
- `severity: HIGH` — >15%, требует ручного ревью перед сохранением

**ВАЖНО:** `portfolio-scenario-stress` использует `by_scenario` НАПРЯМУЮ, не marginal.
Layer 2 marginal — диагностика only.

---

### Шаг 6 — Сборка блока Events YAML

В самом конце вывода (после `§ Что дальше`) добавляется технический блок для
автоматического сохранения через save-to-library. Этот блок — **не для чтения
пользователем**, а для машинного парсинга при сохранении.

Полный шаблон и правила заполнения — в `references/fca-events-yaml-spec.md`.

**Обязательно при `method: fca`** — блок `fca_stats` (per-horizon машинный слепок:
`l1_weighted`/`l1_unweighted`/`l2_ev`/`p10`/`p90`). Значения — напрямую из output
`weighted_consensus.py` (`weighted_median`/`unweighted_median`/`p10`/`p90`) и из
`marginal.values` (для `l2_ev`). **`unweighted_median` пишется ПОЛЕМ, а не прозой в
`notes`** — иначе калибровка «weighted vs unweighted» невозможна (`references/events-yaml-spec.md`
§14.1). Не извлечённое — `null # TODO`, не сочинять.

**Обязательно для Type 2** — чек одностороннего конуса (§15, F1): заполни `fact_anchor`
(текущий факт: спот/ставка с Шага 4, **не L1**), прогони `check-one-sided-cone`, запиши
`one_sided_cone`/`cone_side`. При `one_sided_cone: true` — добавь встречный мир в `by_scenario`
(предпочтительно) или `counter_world_reason`; иначе save-to-library **заблокирует** сохранение.
Правила и подсказка по ставке — `references/fca-events-yaml-spec.md` (раздел «Чек одностороннего
конуса»).

**Обязательно перед выводом Events YAML — pre-save валидация формы (FCA-2):**

```bash
echo '<events-yaml-as-json>' | python3 scripts/validate_fca_output.py
```

Скрипт ловит известные non-spec привычки вывода (события 2026-05-11: `horizon_2026:`
вместо `values."YYYY-MM-DD"`, `central_estimate`/`p10`/`p90` вместо `central`/`range`,
`sources_used` числом, `coherence_diagnostic` внутри `conditional_on_scenarios`,
provenance вне канона §5.2.1) и кросс-правила provenance ↔ `sources_used`/`upstream_used`
(derived-прогноз обязан нести `upstream_used`). Exit 1 → исправь блок и перегони;
НЕ выводи Events YAML с blocking-нарушениями — save-to-library прогонит тот же канон
в strict-режиме (`{"_strict": true}` в `validate-forecast-events`) и заблокирует сохранение.

**Черновик в файл (до вывода в чат).** После валидации запиши два файла через `Write` на mount
(`references/transport-layer.md`): `{LOCAL_LIBRARY_ROOT}/_drafts/<topic>-<forecast_date>.md` — весь отчёт
как в чате, с frontmatter, и `{LOCAL_LIBRARY_ROOT}/_drafts/<topic>-<forecast_date>.events.yaml` — содержимое
блока Events YAML без обёртки; `<topic>` — slug темы по `references/events-yaml-spec.md` §1.2, те же имена
получит пара в `forecasts/`. В чат — как раньше плюс строка «черновик: `_drafts/<topic>-<forecast_date>`»;
save-to-library берёт пару из черновика, поэтому сжатие контекста между сбором и сохранением текст не теряет.
Mount недоступен — вывод только в чат и фраза «черновик не записан».

Для **derived-прогнозов** (значение фактора выведено из других макрофакторов, не из
прямого опроса источников — USDRUB из Brent, ставка из CPI): `provenance:
derived_from_upstream` + непустой `upstream_used: [{factor, value, unit?, source_file?}]`;
`sources_used: []` допустим (`references/events-yaml-spec.md` §5.2.1).

---

## Output Format

Смотри `references/output-template.md` — там полный шаблон с примерами.
Ключевые требования к выводу:

- **TL;DR — modal scenario** — обязателен в шапке всех выводов (числовых и качественных)
- **⚠️ Asymmetry warning** — если карта лагерей асимметрична, блок выводится сразу
  после TL;DR
- Всегда указывай сколько источников отброшено из filtered consensus и почему
- URL цитат — обязательно
- Дата запроса — в заголовке
- Горизонт прогноза — в заголовке (взвешенный по источникам)
- **Таблица «Карта лагерей»** — обязательна в Full-guided и Full-auto режимах,
  выводится перед секцией «Снимок мнений»; в Lite-режиме — опускается
- Секция «Ключевые допущения» — обязательна
- Секция «§ Что дальше» — обязательна
- **## Events YAML (для save-to-library)** — обязателен в самом конце (Шаг 6)

### Правила секции «§ Что дальше»

Рекомендуй ретроспективный аудит неаудированного источника **только если выполнены все условия:**

1. Источник принадлежит к лагерю уровня **Dominant** или **Significant**
   (Minority — не рекомендовать: риск ложного баланса, одно угаданное попадание
   не свидетельствует о системной точности)
2. В его лагере **менее 2 уже аудированных источников** в INDEX.md
3. Источник **опубликовал прогноз по теме за последние 6 месяцев**
4. Источник цитируется в **Tier-1 агрегаторе** (Reuters, AP, AFP, Bloomberg)
   или в **ведущем национальном деловом издании** региона источника

Формат рекомендации:

```
📋 Рекомендуется аудит:
- [Название] — лагерь: [название] [уровень], субдомен: [узкий субдомен]
  Примечание: надёжная калибровка требует N>=3 аудированных прогнозов по субдомену
```

Если Dominant-лагерь не удалось покрыть вообще — дополнительно предложи
целевой поиск по этому лагерю при следующем запуске.

---

## Хранение и ретроспективный ревью

Генерируй готовый прогноз как artefact в чат (markdown + YAML frontmatter) и черновиком в
`Claude-Memory/_drafts/` (Шаг 6). Для сохранения в `Claude-Memory/forecasts/` — пользователь вызывает
`save-to-library`, он переносит черновик в библиотеку. Кроме `_drafts/` скилл в Claude-Memory/ не пишет (D3).

Каждый файл **обязан** начинаться с YAML frontmatter — без него ревью-промпт не сможет
автоматически определить, что проверять:

```yaml
---
forecast_date: YYYY-MM-DD          # дата составления
horizon_date: YYYY-MM-DD           # когда прогноз окончательно сбудется или нет
horizons: [YYYY-MM-DD, ...]        # все горизонты, если прогноз многоточечный (опц.)
review_interval_months: N          # как часто обновлять snapshot (рекомендации ниже)
topic: краткое-название
domain: geopolitics / ru-macro / ...
method: fca                        # тип источника (см. references/output-template.md)
upstream_snapshot:                 # фиксирует upstream-значения, использованные при построении
  - factor: brent
    central_estimate: "..."
    confidence: 0.40
    forecast_date: YYYY-MM-DD
    source_file: "forecasts/{file}.yaml"
  # Для Level-0 факторов: upstream_snapshot: []

# Связь со сценарной матрицей (вместо legacy geopolitics_translation):
# полная схема conditional_on_scenarios — в parallel YAML файле,
# `references/events-yaml-spec.md` §5. Здесь во frontmatter — только
# флаги для маршрутизации.
#
# Для Type 2 (scenario-conditional): conditional_on_scenarios block в YAML
# с by_scenario/A,B,C,D, source_matrix, marginal.method (D5: short scenario_id).
# Для Type 1 (isolated, events-yaml-spec.md §5.5):
isolated: false                    # true → нет conditional_on_scenarios
isolated_reason: null              # обязательно если isolated: true, ≤200 симв
---
```

Поля `method`, `upstream_snapshot`, `horizons` — обязательны для трассируемости
прогноза в DAG-цепочке. Есть `scenarios/horizons.json` — даты `horizons` (и `horizon_date`) берутся из его `horizon_ends`, все; другие даты пользователя — сказать о расхождении и спросить, файл не менять. Полные правила заполнения и примеры — в
`references/output-template.md` (секции «upstream_snapshot — правила заполнения»,
«method — три типа источника»). Сценарная связь — через parallel YAML
`conditional_on_scenarios` block (см. `references/events-yaml-spec.md` §5).

**Рекомендуемые значения review_interval_months по типу прогноза:**
- Ставка ЦБ, инфляция, курс — **3 мес.** (данные меняются быстро)
- Геополитика с активной динамикой (война, выборы) — **3 мес.**
- Геополитика с медленной динамикой (Тайвань, долгосрочные сценарии) — **6–12 мес.**
- Структурные экономические тренды — **6 мес.**

**Логика двух триггеров** (используется ревью-промптом):
1. **Регулярный snapshot**: наступило `forecast_date + N * review_interval_months` для
   целого N → обновить источники, пересобрать snapshot тем же скиллом
2. **Финальный аудит**: `horizon_date` наступил → запустить `retrospective-forecast-audit`,
   оценить точность прогноза, обновить trust-профили источников в INDEX.md
