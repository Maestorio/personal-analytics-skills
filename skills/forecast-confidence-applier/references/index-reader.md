# INDEX Reader

Формат файла INDEX.md и правила его парсинга.

---

## Где живёт INDEX.md

INDEX.md хранится в `Claude-Memory/` (Synology mount, см. `references/transport-layer.md`).

**Алгоритм чтения (идёт по уровням, не останавливается на первом шаге):**

```
Уровень 1 — master index:
  Read("{LOCAL_LIBRARY_ROOT}/INDEX.md")

Уровень 2 — субпапки (если уровень 1 дал ошибку):
  Для каждого: geopolitics, ru-sellside, global-banks, ru-macro, tech-ceo
    Glob("INDEX.md", path="{LOCAL_LIBRARY_ROOT}/{subfolder}/")
  В каждой ищи INDEX.md или lib_*.md — они содержат профили источников

Уровень 3 — lib-файлы напрямую (если INDEX.md нигде не найден):
  Glob("lib_*.md", path="{LOCAL_LIBRARY_ROOT}/")
  Glob("lib_*.md", path="{LOCAL_LIBRARY_ROOT}/{subfolder}/")

Уровень 4 — только если все уровни дали ноль:
  Спроси пользователя: «Не нашёл INDEX.md в Synology. Папка Claude-Memory доступна?»
```

**Важно**: если на уровне 2–3 нашёл отдельные `lib_*.md` файлы без центрального INDEX.md —
используй их напрямую для извлечения trust-профилей. Они содержат ту же информацию.

---

## Формат INDEX.md

INDEX.md генерируется скиллом `retrospective-forecast-audit` и сохраняется через
`save-to-library`.

### Структура файла

```markdown
# Forecast Audit Library

| Источник | Период | Аудит | Тезисов | Hit rate | Альфа | Доверие | Файл |
|---|---|---|---|---|---|---|---|
| Stratfor | 2022–2025 | 2025-10 | 18 | 61% | +8% | HIGH long-term-russia, MEDIUM middle-east/nato-future/us-domestic, IGNORE eu-future/china-collapse | lib_stratfor.md |
| Invest Era | 2022–2025 | 2025-09 | 24 | 58% | +5% | HIGH bonds-rub, MEDIUM finance-ru/ru-rates/inflation, IGNORE usd-rub | lib_invest_era.md |
| ВТБ Инвестиции | 2023–2025 | 2025-11 | 15 | 55% | +3% | MEDIUM ru-sellside/ru-rates, LOW usd-rub | lib_vtb_invest.md |
```

### Колонки

| Колонка | Описание |
|---|---|
| Источник | Название источника (может отличаться от маркетингового имени) |
| Период | Охватываемый период аудита |
| Аудит | Дата проведения аудита (YYYY-MM) |
| Тезисов | Количество проверенных прогнозных тезисов |
| Hit rate | Процент подтвердившихся тезисов |
| Альфа | Превышение над случайным гаданием 50/50 |
| Доверие | Trust-профиль по субдоменам ← главная колонка |
| Файл | Имя файла с полным аудитом в той же папке |

---

## Нормализация имён источников

Имя источника в INDEX.md может не совпадать с тем, как источник фигурирует в новостях
или в запросе пользователя. **Делай fuzzy-match по ключевым токенам**, не требуй точного
совпадения строк.

### Правило нормализации

Убирай суффиксы типа «Мои», «Capital», «Global Markets», «CIB», «Инвестиции» и сравнивай
по корневому бренду:

| Как может быть в INDEX | Варианты в запросе / источниках |
|---|---|
| ВТБ Инвестиции | ВТБ Мои Инвестиции, ВТБ Капитал, ВТБ CIB, VTB Capital, vtb.ru |
| Альфа-Инвестиции | Альфа-банк, Альфа Инвест, Alfa Investments, alfabank.ru |
| Т-Инвестиции | Тинькофф Инвестиции, Tinkoff Investments, tbank.ru |
| SberCIB | Сбер Инвестиции, Сбербанк CIB, sbercib.ru |
| БКС | БКС Мир инвестиций, BCS Global Markets, bcs-express.ru |
| Goldman Sachs | GS, gs.com, Goldman |
| JPMorgan | JP Morgan, JPM, jpmorgan.com |
| Carnegie | Carnegie Endowment, Carnegie Moscow, Carnegie Russia |

**Алгоритм матча**: если ≥1 ключевой токен из INDEX совпадает с токенами найденного
источника → считай их одним источником, используй вес из INDEX.

Если после нормализации есть сомнение → применяй вес MEDIUM (не обнуляй),
и добавь в вывод примечание «имя сопоставлено как [X] → [Y]».

### Если источник не найден в INDEX — ищи его lib-файл напрямую

Источник мог быть аудирован, но ещё не попасть в сводный INDEX.md (или INDEX устарел).
Если конкретный источник не найден в INDEX:

1. `Glob("lib_{бренд}*.md", path="{LOCAL_LIBRARY_ROOT}/")`
2. Проверь субпапки: `geopolitics/`, `ru-sellside/`, `ru-macro/` и т.д.
3. `Read(найденный файл)` — извлеки trust-профиль

Если нашёл — пометь в выводе «найден через прямой поиск (не в INDEX)» + имя файла.

Это важно потому, что аудиты сохраняются в разное время и INDEX.md может не отражать
последние добавления в библиотеку.

---

## Парсинг колонки «Доверие»

Формат строки: `HIGH subdomain1/subdomain2, MEDIUM subdomain3, IGNORE subdomain4/subdomain5`

**Алгоритм парсинга:**

1. Разбей строку по запятым → группы `LEVEL subdomains`
2. Для каждой группы: первое слово = уровень (HIGH/MEDIUM/LOW/IGNORE), остальное = субдомены через `/`
3. Построй словарь: `{subdomain: level}`

**Пример:**
```
Вход: "HIGH long-term-russia, MEDIUM middle-east/nato-future/us-domestic, IGNORE eu-future/china-collapse"

Результат:
{
  "long-term-russia": "HIGH",
  "middle-east": "MEDIUM",
  "nato-future": "MEDIUM",
  "us-domestic": "MEDIUM",
  "eu-future": "IGNORE",
  "china-collapse": "IGNORE"
}
```

---

## MEMORY.md как горячий кеш (вторичный источник)

В контексте разговора может быть память профиля с краткими [lib]-профилями (`mcp__memory`: `/memory-notes.md` → `/lib_*.md`; в старых сессиях — MEMORY.md):
```
- [[lib] Stratfor](lib_stratfor.md) — Trust-профиль: HIGH long-term-russia, ...
- [[lib] ВТБ Инвестиции](lib_vtb.md) — Trust-профиль: MEDIUM ru-sellside/ru-rates, ...
```

MEMORY.md — это **кеш горячих профилей**, не полный INDEX. Используй его только если:
- Synology временно недоступен
- Нужно быстро проверить конкретный источник, который точно в кеше

При любом расхождении между MEMORY.md и INDEX.md (прочитанным через транспорт) — доверяй INDEX.md,
он источник правды.

---

## Edge cases

**INDEX.md не найден в Synology:**
→ Сообщи: «Не могу найти INDEX.md в Claude-Memory/. Уточни путь или проверь, доступна ли папка.»
→ Если пользователь говорит «нет INDEX» — предложи создать шаблон через сохранение первого аудита (save-to-library).

**INDEX.md пустой** (только заголовок, нет строк данных):
→ Все источники = «не аудированы», weighted median недоступен.
→ Сообщи об ограничении в выводе.

**Источник найден в INDEX, но не тот субдомен:**
→ Дефолт: MEDIUM вес.

**Колонка «Доверие» нестандартного формата:**
→ Парси лучшее что можешь; при сомнении — пометь «неясный профиль, принято MEDIUM».

**Дата аудита старше 2 лет:**
→ Пометь «⚠️ аудит от {дата}» — track record мог устареть.
