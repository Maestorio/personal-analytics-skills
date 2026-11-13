---
name: design-docs
description: >
  Навигатор по дизайн-документации HTML-страниц репозитория claude_skills:
  Personal Hub (hub/travel/games/money), портфельный вьюер, дизайн-система
  (токены Claude Design), HTML-экспорт travel-стадий, хостинг (Caddy/API).
  Передаёшь тему — скилл грузит ТОЛЬКО релевантную документацию перед
  правкой / улучшением / обсуждением, не читая остальное.
  Вызов: /design-docs <тема> [ещё темы].
trigger: /design-docs
---

# /design-docs

Точечная загрузка документации перед работой над HTML-страницами и их
отображением. Цель — не читать лишнее: правя карточку в `travel.html`,
не тянуть 1600-строчный экспортный дизайн-док.

Проектный скилл — живёт в `.claude/skills/` репозитория `claude_skills`
(рядом с `investment-docs` и `travel-docs`), осмыслен только внутри него.
Все пути ниже — относительно корня репозитория.
**Корень дизайн-референса:** `tools/design-reference/` — там `INDEX.md`
(SSOT дизайн-системы вьюера + статус реализации). Для HTML-экспорта travel
SSOT — `docs/travel-planning/export/export-design.md`.

## Использование

```
/design-docs hub                # страницы хаба (hub/travel/games)
/design-docs money              # раздел «Деньги» (money.html, ZenMoney)
/design-docs viewer             # портфельный вьюер
/design-docs tokens             # дизайн-система / токены / Claude Design
/design-docs travel-export      # HTML-рендер travel-стадий
/design-docs hosting            # Caddy, write-API, деплой на Synology
/design-docs hub hosting        # несколько тем
/design-docs план travel-share  # загрузить план + его темы и ВЫПОЛНИТЬ его
/design-docs                    # без аргумента → показать карту и спросить
```

## Процедура

1. **Разобрать аргумент** в список тем:
   - `hub` (= страницы хаба: hub/travel/games) · `health` (= раздел «Здоровье»:
     страница, данные, конвертер) · `money` (= раздел «Деньги»: страница
     money.html и её данные из ZenMoney/audit/) · `viewer` (= портфельный вьюер) ·
     `tokens` (= дизайн-система / токены / Claude Design / DesignSync) ·
     `travel-export` (= HTML-рендер стадий travel) · `hosting`
     (= Caddy / write-API / деплой);
   - синонимы: `дизайн-система`→tokens, `страницы`→hub, `вьюер`→viewer,
     `caddy`/`api`/`deploy`→hosting, `export`/`html-export`→travel-export,
     `здоровье`/`анализы`/`аптечка`/`биомаркеры`→health,
     `деньги`/`zenmoney`/`финансы`/`траты`→money;
   - несколько токенов → объединение;
   - пусто → показать карту тем ниже и спросить пользователя;
   - **`план <имя>` / «выполни план <имя>»** → прочитать
     `tools/design-reference/<имя>-plan.md` (активные планы дизайн-контура
     лежат там по конвенции `*-plan.md`; список — `ls`), загрузить темы,
     указанные в шапке плана, и ВЫПОЛНИТЬ план (это режим «исправь/сделай»,
     ждать отдельной команды не нужно). Конкретные планы в этот SKILL.md
     НЕ вписывать — скилл остаётся универсальным, план после выполнения
     помечается выполненным в самом файле плана.
2. **Всегда прочитать сначала:**
   - `tools/design-reference/INDEX.md` — SSOT дизайн-системы, важные
     оговорки (устаревший viewer.css в Design-проекте, self-host шрифты,
     «вкладки сверх дизайна сохранять»), статус реализации;
   - целевые страницы/код — по мере надобности из строки темы.
3. **Для каждой запрошенной темы** прочитать её строку каталога ниже.
   Грузить только это.
4. **Кросс-темное** (держать в голове при любой правке страниц):
   - обе темы (light/dark) обязательны: `:root` + `[data-theme="dark"]`;
   - «наверх» — только `uiScrollTop(el?)`, всегда мгновенно (пункты меню/рельса/вкладок поднимают сами, ui-kit ≥1.64); Escape и меню при открытых окнах — через `uiLayerBind({depth, closeTop, dirty})`, своих `keydown`-Escape и `scrollTo(0,0)` на странице нет;
   - акценты доменов строго из категориальной палитры: инвестиции `--c-1`,
     еда `--c-2`, здоровье `--c-3`, путешествия `--c-4`, игры `--c-5`,
     деньги `--c-6` (свободных `--c-N` больше нет — новый раздел обсуждать);
   - **кнопки и подвал — `tools/design-reference/buttons.md`** (ui-kit 1.70.0): кнопка действия цвета
     страницы, пилюля = выбор, прямоугольник `.ui-btn` = действие (главная / `.ghost` / `.plain` / `.danger`),
     подвал `uiFootHTML({page, version, src})` + `uiDataDone`; своих классов кнопок и подвалов у страниц нет
     (проверка — `tools/tests/test_buttons_uniform.py`);
   - **новая страница раздела — целиком на ui-kit, без своего `<style>`**
     (ui-kit ≥1.11.0, первая — `money.html`): шапка `.ui-top` (крошка, ромб,
     тег, кнопки), `.ui-main`/`.ui-h1`/`.ui-lead`, сегменты `.ui-seg`,
     карточки `.ui-card`/`.ui-tile`/`.ui-stat`, строки с полосами `.ui-row`
     (колонки — `--cols`), `.ui-bar`/`.ui-stack`/`.lv1–5`, мини-графики
     `.ui-spark`, единый график месяцев `.ui-cols` (столбики + скользящее среднее, режим `.net`), KPI `.ui-grid.kpi`, строки `.ui-catrow` с `.ui-minibars`,
     `.ui-fold`, нижняя навигация `.ui-mnav`. Клик по графику, над которым
     меняется высота блоков, — с якорем (график остаётся на месте экрана).
     Ось месяцев — календарная: пропущенный месяц — пустое место `.gap`,
     «N месяцев до» — по календарю, не по соседним записям. Обзор раздела —
     только из тех же функций, что вкладки (своих расчётов нет). Графиков
     месяцев на экране — один (повторяющие друг друга графики — дефект). Акцент —
     `style="--sec-acc:var(--c-N)"` на `.ui-page`. Inline-стили — только для
     данных (ширина/высота/координаты). Нужного компонента нет — добавить его
     в ui-kit.css, а не в страницу. Старые страницы держат свои копии
     `.h-top`/`.chip-btn` (разошлись) — их перевод на `.ui-top` отдельной
     задачей, переименованием; голые `.h-top{`/`.chip-btn{` в ui-kit запрещены
     (молча поменяли бы чужие шапки). Контракт — секция «money» в
     `test_pages_contracts.py`;
   - **окно поверх окна — стопкой** (ui-kit 1.33–1.36, образец — money «к прошлому году»):
     `uiModalHTML({ z, cls: uiStackCls(i, n, fresh) })`, закрытие — `uiStackPop`, прокрутка
     слоёв — `uiStackKeepScroll` (логика в ui-kit, страница держит только массив окон;
     `.leave`/`.return` страницей не ставить), слой — опцией `z` (inline `--modal-z` нарушает
     контракт страницы); одиночное окно — тем же при n = 1; **боковая панель** (карточка справа)
     — только `uiPaneHTML` (ui-kit 1.37.0, стопкой — теми же `uiStack*`, образец — «Здоровье»);
     окно не появляется рывком (ui-kit 1.38.0): форма — `cls: "enter"` только при открытии,
     окно под `hidden` — `uiShow`/`uiHide` (своё окно — класс `.ui-fx`), справка — сама;
     окно, чьё содержимое
     меняется по клику, — `cls: "tall"` (не перецентровывается, график не прыгает). Рецепт
     по шагам — INDEX.md «Окна стопкой с плавным переходом» (там же — где уже стоит и панели стопкой).
     Раскрытие строки — `uiExpandIn`/`uiCollapseOut` (анимируется высота JS, не CSS),
     `uiReduceMotion()` — без анимаций; страница с раскрывающимися блоками — `.ui-page.anchor-js`
     (иначе браузерная привязка прокрутки уводит экран при «свернуть все»). Сравнение год к
     году — `.ui-cols.yoy` (12 месяцев подряд, не календарный год). Экран «Траты» в money не
     перестраивать ради новой функции — новое кладётся в окно;
   - **разделов больше, чем влезает в `.ui-seg`, — `uiTabsHTML`/`uiTabsMount`** (ui-kit 1.39.0,
     вьюер 3.0): одна строка без эмодзи, редкие — `more: true` в «Ещё ▾»; таблица данных —
     `.ui-table` с `th[aria-sort]`, `.sticky`, `tfoot`, обёртка `.ui-table-wrap` (много колонок
     вперемешку текст/числа — `.ui-table.dense`, 1.41.0; шире экрана — липкая копия шапки
     `uiTableStickyHead(wrap)`, 1.43.0; своих `table.compact`/`section.card`/`.banner`
     во вьюере нет — контракт); ячейка «имя /
     тикер» — `.ui-name`, интервал у числа — `.ui-ci`; окно с листанием ← → — `uiModalHTML({ lead,
     aside, top })` + `uiAnimIn`; на телефоне шапка с плитками сворачивается — `.ui-modal.fold` +
     `uiFoldMount` (1.42.0; плитки — `.ui-modal-fold`, подвкладки — `.ui-modal-stick`, сводка — `subAlt`); страница на DOM берёт разметку ui-kit через `uiNode(html)`;
   - **поиск по таблице — `.ui-qbox`/`.ui-q` в строке заголовка карточки** (ui-kit 1.47–1.50): строки
     прятать на месте, поле не пересоздавать; фильтры на телефоне — окно `.ui-modal.sheet` по кнопке
     `.ui-fbtn`, «Сброс» (`.ui-freset`) — на виду, пока фильтр включён; подсветка `:hover` — только
     в `@media (hover:hover)` (на касании залипает); фразы для Claude в справках — `[фраза](#copy)`;
   - **график показателя во времени (ось X — даты замеров) — только `uiTimeChartHTML`/
     `uiTimeChartMount`** (ui-kit 1.53.0, первая — карточка маркера «Здоровья»): ≤20 замеров —
     вся история; больше и не влезает — «полгода» с прокруткой и переключателем «полгода · вся
     история»; паузы — разрыв, частые замеры — медианы; без масштабирования. Своих SVG-графиков
     по датам на странице не заводить;
   - **дата, известная не целиком (только месяц и год, только год), — только `uiFuzzyDateField`**
     (ui-kit 1.65.0): одно поле, 4/6/8 цифр — год / месяц и год / дата, календарь с переключателем
     «День · Месяц · Год»; `{ only: "y" }` — поле года. Хранение `ГГГГ-ММ-ДД | ГГГГ-ММ | ГГГГ`.
     Полная дата — `dateField`, месяц срока годности — `monthField`; своих связок «точность + поля»
     не заводить. Панель, открытая из окна документа, — класс `.over` поверх `.ui-docwin`
     (документ не закрывается; рецепт — INDEX.md «Боковые панели стопкой»);
   - **выпадающий список — только `uiSelectHTML`** (ui-kit 1.11.0, из макета
     «Деньги»): кнопка-карточка с полоской акцента + список с галочкой и
     цифрой справа; клавиатура (↑↓ Home End Enter Esc), клик мимо; выбор —
     событием `ui-select` с `{name, value}`, страница перерисовывается сама.
     Список (и длинный с поиском — combo) раскрывается поверх у поля, ряд и форма не
     растут (ui-kit 1.62.0) — своих заплаток позиционирования не заводить.
     Нативный `<select>` и самодельные попапы не заводить;
   - шрифты только self-host (`assets/fonts/`, Golos Text + Spectral),
     никаких CDN — страницы должны жить офлайн/в LAN;
   - **markdown-документ на странице — только через `uiReaderHTML`/`uiReaderMount`**
     (ui-kit ≥1.7.0: оглавление, полоса глав на телефоне, прогресс). Свой
     мини-рендер markdown на странице не заводить; `toc` — `"auto"`/`true`/`false`;
   - **база — в одном файле `tools/assets/ui-kit.css`** (ui-kit ≥1.6.0): шрифты
     (`@font-face` + токены `--font-sans`/`--font-serif`), токены тем и базовый
     слой (`* / html / body` — шрифт, цвет, фон). Страница подключает ui-kit.css
     (вьюер — ДО viewer.css) и пишет только своё (узор фона, свои токены);
     копировать базу, `@font-face` или стек шрифтов строкой запрещено — шрифт
     только `var(--font-sans)`/`var(--font-serif)`. Без `color` на body модалки
     чернеют в тёмной теме. Контракт — `test_pages_contracts.py`;
   - при правке форматов данных страниц (trip.yaml, taste-profile,
     имена экспортов) — прогнать `tools/tests/test_pages_contracts.py`;
   - **мобильные правила** (страницы кабинета открывают с телефона): поля
     ввода на сенсорном экране ≥16px, иначе iOS Safari приближает страницу
     при фокусе и обратно НЕ отдаляет; длинные токены (URL) переносить —
     иначе документ шире экрана и iOS сжимает его целиком; полная
     перерисовка обязана возвращать прокрутку не только окна, но и модалки.
     Проверяется `tools/tests/test_food_layout.py` (headless-chromium);
     **графики «Денег» — ещё и в WebKit** (`tools/tests/test_money_layout.py`):
     Safari считает размеры иначе, и одного Chromium мало (линия среднего
     обрывалась только на iPhone);
   - **заметная правка вьюера → строка в «Что нового»** (`tools/assets/help/viewer/10-new.md`, `{#new}`): версия и
     дата, что появилось и где, без причин, языком списков изменений приложений; технические правки не пишутся;
   - правило двух зеркал справки вьюера: `docs/investment/portfolio-workflow-guide.md`
     (репо) ↔ `tools/assets/help/viewer/NN-slug.md` (репо, раздел = файл; на сервер — только `deploy.zsh`, копию на Synology не править) — при изменении
     пайплайна/вкладок синхронизировать оба (SYNC-маркеры в шапках);
   - **справки остальных страниц** (кнопка «? Справка», ui-kit 1.4:
     `helpBtnHTML(page)` → модалка с `tools/assets/help/<page>.md`, реестр
     разделов `UI_HELP` в `ui-kit.js`): hub/travel/games/health/money. Это
     пользовательские зеркала скиллов раздела (что сказать, модель, порядок,
     откуда данные вкладок). Меняешь вкладки/экраны страницы или источники их
     данных — поправь таблицу «откуда данные» в справке; новая страница со
     скиллами — кнопка + файл + строка `UI_HELP` (контракт —
     `test_pages_contracts.py`, секция «справки страниц»). Еда справки нет:
     её данные скиллы не готовят;
   - **любая правка страницы → поднять её версию.** У каждой страницы в подвале
     стоит `<имя> vX.Y` (`hub`, `travel`, `games`, `login` — литералом в
     разметке; `food`, `health` — константой `VERSION` в скрипте). Поднимать
     хотя бы minor даже на мелкой правке: версия нужна ровно для того, чтобы по
     скриншоту понять, ту ли сборку человек видит, — иначе «у меня не работает»
     неотличимо от «у меня старая версия из кеша», а страницы кэшируются и
     обновляются отдельно от данных. Наличие версии проверяет
     `tools/tests/test_pages_contracts.py`, но поднять её может только автор
     правки. **Какую цифру** (вьюер, ui-kit, офлайн-ядро; X.Y.Z): X — веха с
     несовместимыми данными (4.0.0 — уход от Numbers); Y — новая функция
     (колонка, блок, режим, вкладка, кнопка); Z — правка существующего
     (ошибка, поведение по умолчанию, вёрстка, тексты). Несколько правок в
     одной выкладке — один шаг; номер, ещё не выложенный, повторно не
     поднимается; выложенный — не переиспользуется (кэш браузера);
   - **правка требует обновления контейнера → выдать команды, а не сказать
     «нужно задеплоить».** Четыре файла живут НА NAS и синком не доставляются:
     `tools/hosting/api/server.py`, `tools/hosting/notify/notifier.py`,
     `tools/hosting/Caddyfile`, `tools/hosting/docker-compose.yml`. Тронул любой
     из них — закончи ответ готовыми командами из «Обновление контейнера —
     шпаргалка» (`tools/hosting/SYNOLOGY-SETUP.md`): `restart hub-api` для
     server.py, `restart hub-notify` для notifier.py (push-уведомления вьюера),
     `restart portfolio-viewer` для Caddyfile, `up -d` для compose. И скажи
     прямо, ЧТО не будет работать до обновления — иначе правка выглядит
     сделанной, а на устройстве её нет. Правки только `*.html`/`assets/`
     обновления контейнера НЕ требуют.
5. **Доложить, что загружено**, и ждать задачу (правка / улучшение /
   обсуждение). Если пользователь просил «проанализируй/проверь» — выдать
   анализ и ждать; править сразу только по «исправь/сделай».

## Карта тема → доки

| Тема | Доки | Код / страницы | Тесты |
|---|---|---|---|
| **hub** | `tools/design-reference/personal-hub-brief.md` (бриф + фазы внедрения), память `project_personal_hub_plan` | `tools/hub.html`, `tools/travel.html`, `tools/games.html`, `tools/food.html` | `tools/tests/test_pages_contracts.py`, `tools/tests/test_food_layout.py` (вёрстка «Еды» на телефоне настоящим браузером; без playwright — пропуск), `tools/tests/test_reader_layout.py` (единый читатель markdown `uiReader`) |
| **health** | `tools/design-reference/health-plan.md` (§0 сверка «план ↔ дизайн», §0.1 аудит данных, §6 скилл-обогатитель); `skills/health-labs/SKILL.md` + `references/methodology.md` (конвертер и справочник биомаркеров, 2026-08-05) | `tools/health.html`; конвертер `skills/health-labs/scripts/build_health_json.py` (владелец — скилл, не `tools/`); вход CSV — ВНЕ репо на Mac `~/Documents/Claude/Projects/Health/данные/` (медицине в git не место), выход `labs.json`/`biomarkers-info.json` — сразу на Synology `Claude-Memory/Health/` (без промежуточного деплоя), живые файлы (`meds`/`vaccinations`/`vitals`/`studies.json`) — там же | `tools/tests/test_pages_contracts.py` (секция health), `python3 skills/health-labs/scripts/build_health_json.py --selftest`, `python3 skills/health-labs/tests/test_validate_labs_info.py` |
| **money** | `docs/zenmoney/money-page-brief.md` (контракты history/spending/trips.json, чек-лист порта, подписи без кодов), `docs/zenmoney/README.md`; макет `tools/design-reference/Деньги.dc.html` (Claude Design, проект `553ebbf1-…`; стили макета НЕ переносить — только раскладка и логика) | `tools/money.html` (только чтение `ZenMoney/audit/*.json` с токеном), плитка на `tools/hub.html` в ряду `.hub-row1` рядом с портфелем; справка `tools/assets/help/money.md`; писатель данных — `skills/zenmoney-analyst/scripts/audit_history.py` (история — ещё и `tools/zenmoney_csv_backfill.py`); данные и скилл — `/zenmoney-docs` | `tools/tests/test_pages_contracts.py` (секции money/ui-kit/hub), `tools/tests/test_money_layout.py` (графики в Chromium и WebKit), `tools/tests/test_caddy_zones.py` (страница публична, `/ZenMoney/*` — нет) |
| **viewer** | `tools/design-reference/INDEX.md`, `docs/investment/TODO_design.md` (бэклог вьюера; §1 — решения переделки 2026-10-12), `tools/design-reference/viewer-ui-kit-map.md` (карта «компонент вьюера → ui-kit», этап 1), `docs/investment/portfolio/HTML_VIEW_TODO.md`, `docs/investment/portfolio/html-comments.md`, справка `tools/assets/help/viewer/NN-slug.md` (10 частей, раздел = файл) | `tools/portfolio-integrated-viewer.html`, `tools/assets/viewer.css`, `tools/assets/viewer.js` | — |
| **tokens** | `tools/design-reference/INDEX.md` (§ Источник — Claude Design проекты и их id), `personal-hub-brief.md` §0–§2 | `tools/design-reference/design-tokens-extracted.css`, `tools/design-reference/personal-hub-ds/` (tokens + 6 превью), генератор `gen_personal_hub_ds.py`; референс-макет `Дашборд - все вкладки.dc.html` | — |
| **travel-export** | `docs/travel-planning/export/export-design.md` (SSOT), `export/export-design-by-type.md`, `plans/export-fix-batch-2026-07.md` (активный план) | `skills/travel-planning/scripts/export/html_lib.py`, `scripts/export/stages_html/`, таксономия `scripts/data/taxonomy.json` | `skills/travel-planning/tests/test_html_export.py` |
| **hosting** | `tools/hosting/SYNOLOGY-SETUP.md`, `tools/hosting/COLD-START-PLAN.md` (разбор медленного холодного старта после консолидации хранения + план правок; этап 0 — диагностика на живом NAS) | `tools/hosting/Caddyfile` (зоны публично/приватно/api — комментарии в шапке = SSOT решений), `tools/hosting/api/server.py` (write-API sidecar), `tools/hosting/notify/notifier.py` (push-уведомления вьюера, контейнер hub-notify), `tools/deploy.zsh`, `tools/hosting/docker-compose.yml` | `tools/tests/test_write_api.py`, `tools/tests/test_notifier.py` |

Раздел **«Еда» как предметная область** (данные продуктов и рецептов на
Synology, инструкция генератора рецептов, справка по технике, скрипты кухни,
зона записи `/api/fd/*`) — отдельный навигатор `/food-docs <тема>`
(`.claude/skills/food-docs/`). Сюда, в `hub`, «Еда» попадает только своей
дизайнерской стороной: вёрстка, токены, обе темы, поведение на телефоне.

Для **глубокой** работы над travel-экспортом (парсеры, PDF, DOCX, карты,
format-firewall) этот скилл не заменяет `/travel-docs export` — там полный
контур с firewall-доками; здесь только HTML-слой отображения.
Аналогично для логики данных вьюера (frontmatter-контракты, aggregate) —
`/investment-docs portfolio-integrated-view`.

## Принципы

- **Минимум контекста.** Грузить только доки запрошенных тем.
- **INDEX.md — SSOT дизайн-системы вьюера**; решения по зонам доступа —
  шапка `tools/hosting/Caddyfile`. При добавлении дизайн-дока обновлять зеркальную
  таблицу здесь.
- **Дизайн не придумывать с нуля** — всё новое в грамматике существующих
  токенов и компонентов (см. кросс-темное в Процедуре, п. 4).
- **Язык — русский** (как и вся документация репозитория).
