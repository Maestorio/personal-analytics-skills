# Stage 0 — output-spec: канонический формат `0_scope.md`

> **low freedom для контрактных частей.** Контракт формата артефакта `0_scope.md`.
> Формат свободнее, чем у других стадий (нет скрипта-валидатора, регионы
> варьируются) — output-spec фиксирует только структурные части (YAML, заголовки
> регионов, обязательные блоки, anti-scope-creep). Правишь контракт — правишь
> **здесь**; `tests/test_format_contract.py` проверит. В рантайме файл не грузится.

---

## Часть 1 — Контракт формата (канон)

### Двухактный flow
**Akt A** (digest уточнений) → пользователь → **Akt B** (markdown-артефакт).
Akt B — это и есть `0_scope.md`.

### Структура Akt B (`0_scope.md`)
- **Регионы** — заголовки `#### {Регион}` (русская транслитерация + латиница), по
  каждому — аллокация ночей, логика выбора, content-density.
- **Tempo + country quota** — в YAML и в honest assessment.
- **`{trip_start_city}`** — точка старта/финиша (резолв из `home_city` профиля
  или запроса), в honest assessment как редактируемое решение.
- **Honest assessment** — тредофы, `nights/base_count` (< 3.5 → soft warning),
  logistics tradeoff при 2+ маршрутах.
- **`trip_wishes`** — вербатим-пожелания пользователя (backstop для Stage 4).

### YAML-шапка
`trip_id`, `stage: 0_scope`, `regions`, аллокация ночей, `tempo`,
`country_quota`, `home_city` / `trip_start_city` / `home_eq_start`,
`trip_wishes`, `content_density_override`.

### Anti-scope-creep (жёстко)
- **НЕ** создавать `## Решение` / `## Предложенные пакеты` — это не Stage 0.
- **НЕ** включать Stage 5-детали (отели, часы работы, дневные планы) — Stage 0
  только режет регионы и распределяет ночи.
- Блок `## Сохранить как` — НЕ в теле файла (отдельным сообщением).

---

## Часть 2 — Реестр копий (где формат продублирован в рантайме)

- **Продюсер:** `stage0-scope.md` §3 (Akt A/B flow), §6 (методика, классы A–F
  Pre-emit, anti-scope-creep), §6 region-density.
- **Mini-spec:** `SKILL.md` (model self-check, формат поездки).
- **Потребители (ось B):** Stage 1 (`stage1-dr-prompt.md`) — читает `regions` +
  `season` + `## Решение`-парсинг; Stage 4 / Stage 5 — дублирующее чтение
  `0_scope` (погодная логика, региональные описания, trip_wishes).

---

## Часть 3 — Известные дрейфы / на что смотреть при чтении `0_scope.md`

- **Scope creep:** Stage 5-детали (конкретные отели/часы/дневные планы) протекают
  в Stage 0 — Stage 0 только режет регионы и ночи. Класс D Pre-emit это ловит.
- **Mixed-script `trip_id`** (`argentina_юг_2025-03`) — warning + продолжение
  (storage-and-naming §10.8); при чтении учитывать смесь латиницы/кириллицы.
- **«3 пакета» — устаревший термин.** Текущий Stage 0 НЕ выдаёт «пакеты»;
  выдаёт регионы (`#### {Регион}`) + аллокацию ночей + honest assessment.
