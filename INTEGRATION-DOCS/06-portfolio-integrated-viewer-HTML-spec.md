# Portfolio Integrated Viewer — HTML Specification

**Файл:** `tools/portfolio-integrated-viewer.html` + `assets/` (multi-file с v2.5.0; standalone, no backend, отдаётся по HTTP)
**Назначение:** интерактивный browser-based dashboard для чтения integrated-view данных
**Schema compatibility:** `integrated-view@1.x` (specific, not generic) — regex `/^integrated-view@1\./` принимает и `@1.1`, и `@1.2`
**Дата:** 2026-05-05 (v1.0); 2026-05-07 (v1.1: Phase 10.1 implementation); 2026-06-08 (viewer 1.8: tail_flags)
**Версия:** 1.1 (spec); viewer build `VIEWER_VERSION = 2.5.0`

**v2.5.0 (редизайн Claude Design, 2026-07):** single-file → **multi-file** (`portfolio-integrated-viewer.html` тонкий шелл + `assets/viewer.css` + `assets/viewer.js` + self-host шрифты Golos Text/Spectral), отдача по HTTP, cache-busting `?v=`. Все 14 вкладок + 3 модалки на дизайн-системе Claude Design; §4-герой Интеграционного — `verdict-grid` на чистом CSS/`errbar` без Chart.js (детерминированный рендер). Дизайн-SSOT + контракт стабильности `portfolio_by_horizon` (корневой фикс «графики через раз») — `tools/design-reference/`. Прежние пункты этой спеки про single-file (§2.1/§10/§14) — historical; актуальная файловая раскладка — `tools/design-reference/INDEX.md` и `docs/investment/portfolio-workflow-guide.md`.

**Phase 10.1 (реализована 2026-05-07):** базовый viewer + 3 новые вкладки (Diff vs last week, Action queue, Macro context) + расширенный Predictions с countdown + timeline в drill-down. Loading через Mode 4 (folder picker) и Mode 5 (manual drag-drop). HTTP modes (1/2/3) — отложены в Phase 10.2 (см. `docs/investment/_cross-cutting/phase-10.2-nas-hosting.md`).

**Tail-risk флаги (viewer 1.8, output schema `integrated-view@1.2`):** `renderCaveats` рендерит карту «⚡ Tail-risk флаги» из `fm.tail_flags` (вкладка «Оговорки»). Три типа: `binary_skew` (⚡), `sign_unresolved` (⚠️, severity HIGH), `portfolio_tail` (🪢). При `fired:false` — строка «ни один флаг не сработал». **Backward-compat:** ключ `tail_flags` отсутствует в `@1.1`-отчётах → `buildTailFlagsCard` возвращает `null`, viewer не ломается. Маркер ⚡ в строках §3 и под-блок §9 рендерятся как raw markdown (`simpleMarkdownToHtml`) — отдельной обработки не требуют. **Контракт 5 колонок §1 (`r[2]`=verdict-pointer, `r[4]`=verification) не менялся** — index-парс `buildActionQueue`/`showReportModal` затрагивает только §1, ⚡ живёт в §3.

---

## 1. Что это

Standalone HTML файл, который:
1. Принимает upload одного или нескольких файлов через drag-and-drop:
   - `INTEGRATED-VIEW-{date}.md` (production: для отображения как primary view)
   - `WEEKLY-REVIEW-{date}.yaml` (для drill-down контекста по позициям)
   - `STRESS-{date}.yaml` (для drill-down контекста по сценариям)
   - `PORTFOLIO-{date}.json` (для weight расчётов и filters)
2. Валидирует schema versions всех файлов
3. Рендерит interactive dashboard на основе этих данных
4. Работает offline (no network calls после загрузки)
5. Запускается через `file:///path/to/portfolio-integrated-viewer.html` или Synology web view

**Зачем отдельно от Markdown output:**
- Markdown — простой read view, не интерактивен
- HTML viewer — sortable tables, drill-down, charts, history toggle
- Mobile-friendly (markdown в Synology mobile неудобен)
- Можно открыть на ноутбуке без Claude

## 2. Architectural decisions

### 2.1. No build system

Vanilla HTML + JS, без webpack / npm / build steps. Зависимости через CDN (но с graceful fallback если offline).

**Allowed CDNs:**
- `https://cdnjs.cloudflare.com/` — js-yaml для YAML parsing
- `https://cdn.jsdelivr.net/` — Chart.js для графиков

**No allowed:**
- React / Vue / Angular (overkill)
- Webpack / Vite / Rollup
- SSR / Backend
- Cookies / localStorage с user data (privacy)

### 2.2. Schema-validated, not generic

Viewer привязан к `integrated-view@1.x` schema. На несовместимой версии:
```
❌ Schema mismatch
This viewer supports integrated-view@1.x.
Uploaded file declares schema version: {version}.
Please use the matching version of viewer.
```

**Аргумент:** generic viewer был бы слабее по UX. Specific viewer rendering точно знает структуру и может делать smart things (например, ИИС-3 ❄ icons, color coding HIGH-priority).

### 2.3. Privacy first

Viewer **никогда** не отправляет данные куда-либо. Всё парсинг и рендеринг — клиент-side. Это критично, потому что данные содержат структуру личного портфеля.

**Acceptance test:**
- Открыть viewer с интернетом → load data → выключить интернет → reload page (with cached files)
- Должно работать (всё локально)

## 3. UI sections

```
┌─────────────────────────────────────────────────────────────┐
│ [Header]                                                     │
│ Portfolio Integrated Viewer v1.0                             │
│ Loaded: INTEGRATED-VIEW-2026-05-04.md                        │
│ + supplementary: WEEKLY-REVIEW-2026-05-04.yaml,              │
│                  STRESS-2026-05-04.yaml,                      │
│                  PORTFOLIO-2026-05-03.json                    │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ [Stale checks banner — yellow if any]                        │
│ ⚠ Stress YAML age: 95 days (limit 90). Consider re-running.  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ [Tabs]                                                       │
│ Dashboard | Positions | Scenarios | IE Model | What's not   │
│            shown | Predictions | Caveats | Source files     │
└─────────────────────────────────────────────────────────────┘

[Active tab content rendered here]
```

### 3.1. Dashboard tab (default)

```
┌─────────────────────────────────────────────────────────────┐
│ Equity vs Bond Verdict                                       │
│                                                              │
│ Equity (38% portfolio):     +15.2% [+2;  +28]               │
│ Bond (62% portfolio):       +22.3% [+18; +27]               │
│ Spread:                     -7.1pp [-10; +25]               │
│                                                              │
│ [Visualization: bar chart with CI as error bars]            │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ HIGH-priority verification (3 positions)                     │
│                                                              │
│ [Sortable table]                                             │
│  Ticker  Weight  Verdict  Priority  Action                   │
│  CHMF    0.33%   TRIM     HIGH      [Show checklist]         │
│  ...                                                         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Per-position dashboard (sortable, filterable)                │
│                                                              │
│ Filter: [□ Show ИИС-3 only] [□ Show macro-blindspots only]  │
│         [Sector ▼] [Verdict ▼]                               │
│                                                              │
│ [Sortable table]                                             │
│  Ticker  W%   Macro  Div  Idio  Total  YTM  Spread  Verdict  │
│  SBER   12.5  -2.1   +19  +5    +22.1  14   +8.1pp  HOLD     │
│  ...                                                         │
│                                                              │
│ Click row → drill-down modal                                 │
└─────────────────────────────────────────────────────────────┘
```

### 3.2. Positions tab

Detailed per-position view. Same data as dashboard table но с большим контекстом для каждой:
- Fundamental score basis + sources
- All catalysts with sources (если supplementary review YAML загружен)
- IE divergence info
- ИИС-3 status

Sorting: by weight DESC (default), by total_expected, by verdict, by priority.

Filter:
- Sector
- Verdict (HOLD / BUY / TRIM / SELL / NOT REVIEWED)
- Priority (HIGH / MEDIUM / LOW)
- ИИС-3 only / no ИИС-3
- Macro-blindspot only

### 3.3. Scenarios tab

Только если STRESS YAML загружен.

```
For each scenario:
- Name, probability, description
- Factor changes (sanctions, rate, FX, oil)
- Top 5 positions affected positively
- Top 5 positions affected negatively
- Sector breakdown
```

Visualization: probability pie chart + per-scenario bar chart of portfolio impact.

### 3.4. IE Model tab

Из supplementary PORTFOLIO snapshot (если загружен):
- Full IE model positions (21)
- Sector allocation in IE model
- Comparison: what user holds vs IE model
- Underweight / overweight per position
- Positions in portfolio not in IE model
- Positions in IE model not in portfolio

### 3.5. What's not shown tab

Direct render of section 9 from integrated-view markdown.
Plus: explicit links to source files (relative paths).

### 3.6. Predictions tab

`predictions_for_review` block:
- Table format
- "Time to review" countdown ("4 months remaining until review date")
- Each prediction expandable with full context

### 3.7. Caveats tab

All caveats from STRESS + REVIEW + integrated-view itself, dedup'd, sorted by severity.

### 3.9. Diff vs last week tab (Phase 10.1, NEW)

Появляется когда найдены ≥2 weekly-review (current + history[0]).

Сравнивает два последних weekly-review по позиционно. Группы изменений:
- 🔁 Изменения вердикта (HOLD → BUY и т.п.)
- 📊 Изменения fundamental_score (HIGH → MEDIUM)
- 💰 Изменения div_yield_12m_pct (>0.5 пп)
- ✅ Новые catalysts (по id)
- ❌ Исчезнувшие catalysts
- 🔔 Изменения verification_priority
- ➕ Добавленные позиции
- ➖ Удалённые позиции

Каждая группа — карточка с цветовой подсветкой (add=зелёный, rem=красный, mod=жёлтый). Сортировка внутри группы — по weight DESC.

### 3.10. Action queue tab (Phase 10.1, NEW)

Сводная таблица из всех источников: HIGH-priority позиции из integrated-view §1 + позиции с verification_priority HIGH/MEDIUM или verdict BUY/SELL/TRIM из weekly-review.

Колонки: Источник · Тикер · Вес · Вердикт · Priority · Action / что проверить (включая verification_checklist).
Сортировка: by weight DESC.
Каждая строка показывает источник пометки (weekly-review / integrated-view §1) — позволяет понимать «почему позиция здесь».

### 3.11. Macro context tab (Phase 10.1, NEW)

Появляется когда найдены ≥2 ru-*.md (macro-snapshots).

Sparkline'ы для 7 индикаторов: CBR rate, CPI, USD/RUB, CNY/RUB, Brent, RGBI, IMOEX. Каждый индикатор — карточка с:
- Текущим значением (latest)
- Δ vs первый snapshot (зелёный/красный/нейтральный)
- Sparkline-графиком за весь загруженный период

Формат парсинга macro-snapshot: regex по строкам типа `Ключевая ставка ЦБ: 16%`, `USD/RUB: 95.43`, `Brent: $82.50`. Толерантен к произвольному порядку строк и наличию emoji.

### 3.8. Source files tab

```
Files loaded:
- INTEGRATED-VIEW-2026-05-04.md  [Open / Download]
- WEEKLY-REVIEW-2026-05-04.yaml  [Open / Download]
- STRESS-2026-05-04.yaml         [Open / Download]
- PORTFOLIO-2026-05-03.json      [Open / Download]

Schema versions:
- integrated-view: 1.0  ✓
- weekly-review:   1    ✓
- stress:          1    ✓
- portfolio:       2.0  ✓

All compatible with viewer 1.0
```

## 4. Drill-down modal (per-position)

Click on row in dashboard / positions table → modal:

```
┌──────────────────────────────────────────┐
│ SBER (Сбербанк)                      [X] │
├──────────────────────────────────────────┤
│ Sector: Финансовый                       │
│ Weight: 12.5% (real) vs 6.0% (IE target) │
│ Divergence: +6.5pp (intentional)         │
│ ИИС-3: No                                │
│                                          │
│ Expected return (20mo): +22.1% [+4; +37] │
│ ├─ Macro Δ:   -2.1%  [-12; +6]           │
│ ├─ Dividend:  +19.2% [+15; +22]          │
│ └─ Idio α:    +5%    [+1; +9]            │
│                                          │
│ Fundamental: HIGH                        │
│   ROE 24%, CET1 13.2%, NIM 5.8%          │
│   [Sources →]                            │
│                                          │
│ Catalysts (3):                           │
│ ├─ Rate cut re-rating                    │
│ │  P=0.6 (joint with Sc-D_base p=0.525)  │
│ │  Δ=+25% [+15; +35]                     │
│ │  Source: advisor estimate [link]       │
│ ├─ Sanctions tail                        │
│ │  P=0.15 (joint with Sc-B_stress)       │
│ │  Δ=-40% [-25; -60]                     │
│ │  Source: stress-test [link]            │
│ └─ Dividend approval ГОСА                │
│    P=0.85 (independent)                  │
│    Δ=0% [-2; +3]                         │
│    Source: e-disclosure [link]           │
│                                          │
│ Verdict: HOLD (confidence 0.75)          │
│ Basis: уже выше IE-цели; в Sc-B          │
│ большая просадка                         │
│                                          │
│ Last corp event:                         │
│ 2026-04-28: МСФО Q1-26 +12% YoY          │
│                                          │
│ Verification priority: LOW               │
│ Checklist: (empty)                       │
└──────────────────────────────────────────┘
```

## 5. Loading modes (Phase 10.1)

В Phase 10.1 реализованы только Mode 4 и Mode 5. HTTP-режимы (1, 2, 3) — Phase 10.2 (см. `docs/investment/_cross-cutting/phase-10.2-nas-hosting.md`).

### Mode 4 — Folder picker (PRIMARY для desktop)

- Условие: `location.protocol === 'file:'`.
- Доступен через `<input type="file" webkitdirectory>` (Safari/Chrome/Edge desktop) или `showDirectoryPicker()` (Chromium с persistent FileSystemAccess handle).
- Поток: пользователь нажимает «Выбрать папку» → выбирает `Claude-Memory/` целиком → JS итерирует все файлы → классифицирует и автозаполняет вкладки.
- В Chromium с `showDirectoryPicker` появляется кнопка «Обновить» — повторное чтение через сохранённый handle без re-pick.

### Mode 5 — Manual drag-and-drop (fallback)

- Условие: webkitdirectory не поддерживается (iOS Safari) или пользователь явно выбирает.
- Поток: drag несколько файлов или нажать «Выбрать файлы» → multi-select. Также работает drag целой папки в desktop-браузерах через `webkitGetAsEntry()` API.

### File loading flow

```
1. User triggers Mode 4 (Pick folder) or Mode 5 (drag-drop / multi-select)
2. JS reads files (FileReader API) — all parsing client-side
3. Detect file types by extension and content:
   - .md with frontmatter "schema_version: integrated-view@..." → integrated-view
   - .yaml with "schema_version: 1, type: weekly-stocks-review" → weekly-review
   - .yaml with "schema_version: 1, type: portfolio-stress-test" → stress
   - .json with "schema_version: 2.x" → portfolio
   - .md matching "ru-YYYY-MM-DD" or in macro-snapshots/ → macro-snapshot
4. Validate each file's schema version (fail-fast on mismatch)
5. Group by type; pick latest by frontmatter date for current; rest = history
6. Build internal data model
7. Render Dashboard tab (or first available)
8. Tabs auto-hide based on data: Diff требует ≥2 weekly; Macro context — ≥2 ru-*; Scenarios — stress.yaml; IE Model — portfolio.json
```

## 6. Interactivity features

### 6.1. Sortable tables

Click column header → sort asc/desc. Numeric columns sort numerically. Indicator arrow.

### 6.2. Filterable tables

Filter widgets above table. AND-logic between filters.

### 6.3. Per-position drill-down

Click row → modal with full context.

### 6.4. Charts

Using Chart.js:
- Bar chart: equity vs bond expected return with error bars
- Pie chart: scenario probabilities
- Bar chart: per-scenario portfolio impact
- Stacked bar: portfolio composition by sector
- Heatmap (optional v2): IE divergence per position

### 6.5. Print-friendly mode

CSS @media print:
- Hide tabs UI, show all content sequentially
- Hide drill-down modals
- Use A4 page breaks at section boundaries

### 6.6. Dark mode toggle

CSS variables for color scheme. Toggle in header. No localStorage (privacy) — toggle resets on reload.

## 7. Error handling

### 7.1. Missing primary file

```
"Drop INTEGRATED-VIEW-{date}.md to start.
Optionally also drop:
- WEEKLY-REVIEW-{date}.yaml (per-position drill-down)
- STRESS-{date}.yaml (scenarios tab)
- PORTFOLIO-{date}.json (IE model tab)"
```

### 7.2. Schema version mismatch

```
❌ Schema version mismatch

Detected: integrated-view@2.1
Supported: integrated-view@1.x

Please use the matching viewer version.
Latest viewer: tools/portfolio-integrated-viewer.html
```

### 7.3. Malformed YAML / JSON

```
❌ Failed to parse {filename}

Error: {error message}
Line: {line number}

Please regenerate the file via the matching skill.
```

### 7.4. Cross-file inconsistency

E.g. weekly-review references scenarios that don't exist in stress YAML:
```
⚠ Cross-file warning

Weekly review references scenario "Sc-X_test" not present in stress YAML.
This catalyst will be displayed but excluded from joint expectation.
```

## 8. Performance

### 8.1. Large portfolios

For portfolios with 100+ positions:
- Lazy render of table rows (virtualized list)
- Aggregate computation cached after first render
- Search-as-you-type with debounce 200ms

### 8.2. Mobile

Responsive layout:
- Single column on width < 768px
- Hide less-important columns (Macro Δ, Idio α) — show in drill-down
- Touch-friendly tap targets (min 44x44px)

## 9. Acceptance criteria

Viewer считается готовым когда:

### Functional

- [ ] Open in Chrome / Firefox / Safari / Edge — все рендерятся одинаково
- [ ] Drag-and-drop работает для всех 4 типов файлов
- [ ] Schema validation корректно отлавливает несовместимые версии
- [ ] Все 8 tabs рендерятся при наличии primary + supplementary files
- [ ] Drill-down modal работает на click row
- [ ] Sort / filter / search работают на всех tables
- [ ] Charts рендерятся корректно
- [ ] Print preview корректен (no clipped content)

### Performance

- [ ] Initial render < 1s для портфеля 60 позиций
- [ ] Sort / filter response < 200ms
- [ ] No memory leaks при многократном reload файлов

### Privacy

- [ ] Verifiable: no network calls после initial CDN load (DevTools Network tab)
- [ ] No localStorage / sessionStorage / cookies с user data
- [ ] Open / close test: данные **не** persist между tab close + reopen

### Compatibility

- [ ] Schema integrated-view@1.x — supported
- [ ] Schema weekly-review@1 — supported (для supplementary)
- [ ] Schema stress@1 — supported
- [ ] Schema portfolio@2.0 — supported
- [ ] Other versions → graceful error message

### Mobile

- [ ] Responsive at 375px width (iPhone SE)
- [ ] Touch-friendly buttons
- [ ] No horizontal scroll except in tables

## 10. Tech stack summary

| Component | Tech |
|---|---|
| HTML | Vanilla |
| CSS | Vanilla + CSS variables |
| JS | Vanilla ES6+ |
| YAML parsing | js-yaml@4 (CDN) |
| Charts | Chart.js@4 (CDN) |
| Icons | Inline SVG (no font icons) |
| Build | None |
| Dependencies | 2 (js-yaml, chart.js) |

Total file size target: **< 50KB** uncompressed (excluding CDN deps).

## 11. Не делается в v1.1 (Phase 10.1)

- ❌ HTTP-режимы (Mode 1 autoindex / Mode 2 manifest / Mode 3 URL query) → Phase 10.2 (`docs/investment/_cross-cutting/phase-10.2-nas-hosting.md`).
- ❌ History integrated-view'ов — пользователь подтвердил что один integrated-view за раз. Динамика через history weekly/stress/macro.
- ❌ Notification on changes → v3-B.
- ❌ Hypothetical re-allocation comparison → v3-C.
- ❌ Edit / save changes back to YAML → out of scope (это decision tool, не editor).
- ❌ Multi-portfolio support → v4-A.
- ❌ Real-time price updates → v4-B.
- ❌ Authentication / cloud sync → out of scope (privacy first; auth — на уровне HTTP-сервера в Phase 10.2).
- ❌ Полный Markdown renderer для integrated-view body. Используется regex-extractor секций по `## `-заголовкам + table-renderer для markdown-таблиц + simple inline `**bold**` / `*em*` / `` `code` ``.

## 12. Implementation hints

```html
<!-- Skeleton -->
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Portfolio Integrated Viewer</title>
  <style>
    /* CSS variables for theming */
    :root {
      --bg: #fff;
      --text: #222;
      --border: #ddd;
      --accent: #2563eb;
      --warn: #fbbf24;
      --err: #ef4444;
      --success: #22c55e;
    }
    [data-theme="dark"] {
      --bg: #1a1a1a;
      --text: #eee;
      --border: #444;
      ...
    }
    /* All styles inline */
  </style>
</head>
<body>
  <div id="app">
    <header>...</header>
    <main id="main"></main>
  </div>

  <script src="https://cdnjs.cloudflare.com/ajax/libs/js-yaml/4.1.0/js-yaml.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <script>
    // Application logic in modules
    const VIEWER_VERSION = "1.0";
    const SUPPORTED_INTEGRATED_VIEW = "1.x";
    // ...
  </script>
</body>
</html>
```

## 13. Testing approach

### Manual test set

Минимальный набор тест-кейсов:
1. Все 4 файла свежие, valid → все 8 tabs рендерятся
2. Только primary файл (md) → primary content + warnings on missing tabs
3. Mixed: primary + 2 supplementary → tabs зависят от наличия
4. Schema mismatch на одном файле → graceful error
5. Очень большой portfolio (200 positions) → performance check
6. Mobile (DevTools responsive mode 375px) → layout check
7. Print preview → page break check
8. Empty portfolio (0 positions) → graceful empty state
9. Все verdict = HOLD → HIGH-priority section пустая, hidden
10. ИИС-3 only portfolio → корректное отображение constraints

### Automated test (optional v2)

Playwright / Cypress test suite. Не блокирует release v1 viewer'а.

## 14. Distribution

- Файл живёт в `/tools/portfolio-integrated-viewer.html` в репо
- Копия в Synology Drive `/Claude-Memory/Tools/portfolio-integrated-viewer.html` для прямого доступа
- Открывается через `file:///` URL или Synology web

---

**Implementation owner:** Claude Code (рекомендуется) или ручная разработка.
**Estimated effort:** 1-2 рабочие сессии для v1.
