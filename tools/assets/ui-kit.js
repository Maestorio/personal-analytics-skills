'use strict';

// ═══════════════════════════════════════════════════════════════════════════
// ui-kit.js — общие UI-компоненты Personal Hub
// (tools/hub.html · travel.html · games.html · food.html · health.html)
//
// Подключается как внешний ассет с версией в query-string — тот же паттерн,
// что у assets/viewer.js (portfolio-integrated-viewer.html):
// `<script src="assets/ui-kit.js?v=1.0.0"></script>`. Версия ниже — SSOT:
// ?v=<версия> обязана совпадать на КАЖДОЙ странице, которая подключает
// ui-kit.js/ui-kit.css, и обязана совпадать со строкой в query-string
// (проверяется tools/tests/test_pages_contracts.py).
//
// Подключать СТРОГО ДО инлайн-скрипта страницы-хозяина: делегированные
// обработчики хозяина должны видеть готовые функции (dateField/openCalendar/…)
// на момент первого рендера.
//
// ⚠ Компоненты ui-kit НЕ имеют права ссылаться на функции и константы
// страницы-хозяина. Инлайн-скрипты всех пяти страниц кабинета обёрнуты в
// IIFE `(function(){ … })()`, поэтому их `var X`/`function X` НЕ попадают
// в window, и свободная переменная в коде ui-kit.js не резолвится ничем —
// ReferenceError в момент вызова. Именно так молча умер датапикер после
// Фазы 1 (разбор — в блоке датапикера ниже). Всё, что нужно компоненту,
// он определяет сам; проверяется tools/tests/test_pages_contracts.py
// («ui-kit.js не ссылается на глобалы страниц-хозяев»).
//
// Толчок к выносу: пять однофайловых страниц кабинета копировали UI-компоненты
// (топбар, кнопки Обновить/Войти-Выйти, esc(), датапикер) вручную, и копии
// уже разошлись (см. историю плана унификации UI-компонентов). Компоненты
// переезжают сюда по одному, начиная с датапикера — единственного компонента,
// который на 2026-07-21 существовал только в health.html (Фаза 1, чистый
// перенос без дедупликации между страницами).
//
// ⚠ Одноимённая функция в двух <script> НЕ даёт ошибку — молча побеждает
// загруженная последней. При переносе компонента на очередной странице
// СТАРОЕ определение в инлайн-скрипте страницы обязательно УДАЛЯТЬ, иначе
// перенос фиктивен (страница продолжит жить по старой копии).
//
// v1.0.0 (2026-07-21, Фаза 0+1): каркас + перенос датапикера health.html —
// maskDMY/parseDMY/dateField/monthField/openMonthPicker/openCalendar/
// closeCalendars + приватные DP_WD/UI_MONTHS_NOM (переименованы из WD/
// MONTHS_NOM — не путать с MSHORT/MONTHS страницы-хозяина, которые вне
// виджета используются ещё в других местах health.html и остаются на месте).
//
// v1.1.0 (2026-07-21, Фаза 2): перенос esc()/attr() — эталон health.html
// (полный replace всех 5 спецсимволов, включая кавычки). Заменяет три
// разошедшиеся копии: games.html/travel.html экранировали только `&<>`
// (textContent→innerHTML), что оставляло `"` неэкранированной — реальный
// дефект в data-*-атрибутах (travel data-profile/data-name/data-dir, games
// data-file/data-title); food.html уже закрывал кавычки отдельной функцией
// attr(). attr теперь — алиас esc (после унификации они тождественны).
// Подключён hub.html/travel.html/games.html/food.html (для этих четырёх —
// первое подключение ui-kit.js вообще); health.html — только версия. Датапикер
// (Фаза 1) отныне резолвит esc уже ИЗ ui-kit.js, а не из host-глобала —
// host-контракт виджета ниже обновлён.
//
// v1.2.0 (2026-07-21, Фаза 3 — auth/refresh, единственная фаза, меняющая
// ВИДИМОЕ поведение): authToken()/clearAuthToken()/loginUrl(why)/
// authBtnHTML({why,prefix}) — один элемент-тернарник Войти/Выйти вместо
// hub-пары #btn-login/#btn-logout (два hidden-узла были источником бага
// гонки видимости — оба видны до отработки JS) + uiRefresh(btn)/uiLogout(btn)
// на общем делегированном click-листенере с дискриминатором
// data-cache-prefix (кнопки без префикса — food/health-refresh — этот
// листенер молча игнорирует, их ведут доменные data-act-диспетчеры).
// hub/travel/games переведены целиком на общие хелперы; food впервые получает
// кнопку «Выйти» (раньше логаута не было вовсе); health переведён, старая
// logout-ветка убрана из его ACTS — логаут теперь ловит только делегат
// ui-kit. Канон имени сброса токена — clearAuthToken() (в hub было
// clearToken(), переименовано при переносе).
//
// v1.3.1 (2026-08-04, фикс): датапикер развязан от страницы-хозяина —
// UI_MONTHS_SHORT/dpFmtDay/dpTodayISO вместо host-глобалов MSHORT/fmtDay/todayISO.
// Контракт «хозяин предоставляет глобалы» был невыполним с самого начала
// (инлайн-скрипт хозяина — IIFE), и все три поля даты в «Здоровье» лежали
// с Фазы 1: срок годности лекарства открывал ПУСТОЙ попап, поля с
// проставленной датой (прививка, вес, исследование) роняли рендер модалки.
//
// v1.4.0 (2026-09-26): справка раздела — helpBtnHTML(page)/uiHelpOpen(page)/
// uiMarkdown(md). Кнопка «?» в топбаре hub/travel/games/health открывает
// модалку с markdown из assets/help/<page>.md (те же правила, что у «❓
// Справки» портфельного вьюера: что гонять, каким скиллом, на какой модели).
// v1.4.1: иконка кнопки — красный ❓, как у «❓ Справки» вьюера (было «?» в кружке).
// Ловит её собственный делегат по [data-ui-help] — НЕ data-act, чтобы не
// пересекаться с доменными ACTS-диспетчерами food/health.
// v1.5.0 (2026-09-29): крестик очистки поиска — uiSearchX(id). Страница ставит
// кнопку СРАЗУ ПОСЛЕ своего <input> внутри position:relative-обёртки; видимость —
// чистый CSS (input:placeholder-shown + .ui-search-x → скрыт), состояния нет.
// Клик: value = "" + синтетический bubbling-«input» — страница реагирует СВОИМ
// существующим обработчиком ввода (patchMarkers/patchHTML…), логика поиска
// страниц не дублируется и не трогается. Делегат по [data-ui-search-x] — не
// data-act, чтобы не пересекаться с ACTS-диспетчерами food/health.
// ═══════════════════════════════════════════════════════════════════════════
// v1.59.1 (2026-10-28, константа и ?v= поднимаются позже, отдельным шагом): окно документа, слой .ui-fx, окно и панель стопкой уходят с затуханием (CSS: у ухода своя анимация ui-modal-fade-out; раньше у входа и ухода было общее имя ui-modal-fade, .enter оставался на слое, и браузер продолжал давно закончившийся вход вместо ухода — слой пропадал за кадр, анимировался только невидимый потомок); выноска «> **Важно:** …» — метка с двоеточием («Важно: текст»).
// v1.60.0 (2026-10-28, константа и ?v= поднимаются позже, отдельным шагом): читатель на телефоне — поле поиска на узком окне отдельной строкой под шапкой окна (.rd-q-dock, вне прокручиваемого тела; без flex-родителя — липкое непрозрачное), кнопки ‹ › у поля (предыдущее/следующее совпадение, фокус остаётся в поле), окно с читателем (справка uiHelpOpen, uiModalHTML, .ui-docwin) во всю высоту 100dvh: полоса глав прижата к низу, пустое место — внутри тела; справка на телефоне прокручивает тело, а не оверлей.
// v1.72.0 (2026-11-11): меню «Ещё» вкладок умеет группы (поля group и menu у пункта, заголовок .ui-tabs-pop-h) — вьюер кладёт туда «Архив ИИ» в режиме «без ИИ».
// v1.71.1 (2026-11-11): переключатель вида уведомлений — без плашки ««…» — включено» сверху (состояние видно по переключателю, плашка сдвигала экран); ошибка сохранения — по-прежнему плашкой.
// v1.71.0 (2026-11-11): uiPushMount — виды с group «ahead» отдельной группой «Напоминать заранее» (на ПК справа под «Этим устройством»); на узком экране (≤860px) «Что присылать» и «Напоминать заранее» — свёрнутые сгибы .ui-push-fold, открытое состояние переживает перерисовку.
// v1.70.1 (2026-11-11): строка журнала уведомлений несёт ключ события (data-push-key) — uiPushMount отдаёт его вторым аргументом onOpen(url, { key }) (вьюер: «условие сработало» → карточка бумаги); окно документа вьюера стопкой — .modal-overlay.stacked (светлое затемнение без размытия, нижнее окно видно).
// v1.69.1: uiDateWire() — обвязка стандартного поля даты (dateField) для страниц без своей; .ui-daterow — период в одну строку.
// v1.69.0 (2026-11-10): слот файла — uiFileSlot + стили .ui-file-box/.ui-files/.ui-file*/.ui-file-msg (перенос вьюерных .pf-*; вьюер на общем компоненте, старые классы — алиасами через alias:'pf'); деньги — вкладка «Выгрузка» тем же порядком
// v1.66.1 (2026-11-03): правило «позади» (.behind) покрывает и окно документа вьюера — .modal-overlay.behind > .modal (отчёт под карточкой сдвигается, как окна стопки); вьюер ставит класс сам (_syncBehind).
// v1.68.0: кнопки действия (.ui-btn, «Сохранить» окон, «ОК» подтверждений) — один цвет --btn-acc во всех разделах.
// v1.67.7: окно «Вернуться к ИИ» — время выключения в подзаголовке и имена файлов под видами правок (список — за весь период без ИИ).
// v1.67.6: окно «Вернуться к ИИ» сначала запрашивает настройки (клик до ответа сервера, нет входа) и говорит об этом словами.
// v1.67.5: uiConfirm появляется плавно (.enter); у .ui-modal.compact подвал без отступа safe-area — кнопки на одном расстоянии от края, как у подтверждения.
// v1.67.4: .ui-modal.compact — небольшое окно по центру и на телефоне; окно «Вернуться к ИИ» на нём (единообразно с подтверждением выключения).
// v1.67.3: окно «Вернуться к ИИ» — шторка снизу на телефоне (.sheet), не во весь экран.
// v1.67.2: окно «Вернуться к ИИ» — появление (enter), Esc, фокус.
// v1.67.1: окно «Вернуться к ИИ» не считает сам файл флага правкой владельца.
// v1.67.0: режим сайта «с ИИ / без ИИ» — флаг _hub/settings.json (hub-settings@1) читается при загрузке (кэш localStorage hub-noai → атрибут data-noai на <html> ещё в <head>, затем GET ../api/hub/settings), событие "ui-noai"; кнопка «Режим» в шапке хаба (uiTopHTML({mode:true})): с ИИ → без ИИ — подтверждение и запись; без ИИ → с ИИ — окно «Вернуться к ИИ» со списком правок сайта за период (GET ../api/hub/changes?since=off_since) и напоминанием про зеркало Mac; при data-noai скрыты команды для Claude (.ui-claude-cmd, .ui-say, .act-say, .gate-say, .cond-say, .fc-hp, .noai-hide).
// v1.66.0 (2026-11-03): кнопка команды для Claude — uiClaudeCmd(text, {label}) → button.ui-claude-cmd (контур + значок копирования, подпись «для Claude», data-cmd, title с полным текстом); нажатие копирует (общий uiCopyText), на кнопке 1,6 с «скопировано», без буфера — уведомление с текстом. Залитые кнопки записи на сайт стиль не меняют: «контур и значок — копирует команду, залитая — пишет на сайт».
// v1.65.3 (2026-11-03): выпадающий список (uiSelectPlace, не combo): правый край списка за правым краем ближайшего окна / карточки (.ui-card, .ui-modal-body, .ui-modal) или экрана — список выравнивается по правому краю кнопки (план в карточке бумаги не вылезал за окно).
// v1.65.2 (2026-11-03): «Уведомления» при недоступном сервере — без пути к инструкции разработчика: «проверь, что на NAS запущен hub-notify».
// v1.65.1 (2026-11-03): тот же код под новым номером — 1.65.0 выложен до .ui-pane.over и поля «только год», браузер держал старый ui-kit.css.
// v1.65.0 (2026-11-03): поле неполной даты uiFuzzyDateField(name, iso, opts) — день, месяц и год или только год одним полем (хранение "ГГГГ-ММ-ДД" | "ГГГГ-ММ" | "ГГГГ" | ""): parseFuzzyDate/fuzzyDateText/fuzzyDateHint, ввод цифрами без автомаски (4 цифры — год, 6 — месяц и год, 8 — дата) или с разделителями, подпись под полем (.fd-hint); календарь openCalendar в нечётком режиме (кнопка data-fd-open) с переключателем точности День · Месяц · Год (.dp-prec); поведение поля ведёт сам ui-kit (страница ничего не подключает). Панель .ui-pane.over (слой 220) — поверх окна документа .ui-docwin (215): страница ставит класс панелям, открытым из документа. uiFuzzyDateField(name, iso, {only:"y"}) — только год: 4 цифры, календарь сразу сеткой лет без переключателя.
// v1.64.0 (2026-11-02): uiScrollTop(el?) — «наверх» только мгновенно (никаких smooth, вне зависимости от prefers-reduced-motion); пункты нижнего меню, рельса и вкладок (uiTabsMount), в том числе текущий, поднимают страницу сами после отрисовки вкладки (rAF); uiLayerBind({depth, closeTop, dirty, closeAll}) — слой страницы: Escape при открытых окнах гасится (preventDefault) и закрывает верхний слой после собственных окон ui-kit, пункт меню/рельса/вкладки при открытых окнах закрывает их (при несохранённых правках — uiConfirm «Закрыть без сохранения?»), uiFormDirty(корень) — несохранённые правки по сравнению с исходной разметкой; «к началу» в читателе — мгновенно.
// v1.63.0 (2026-11-01): поле поиска с крестиком — Escape стирает запрос (пустой — снимает фокус), Enter/↑/↓ отдаются странице событием ui-search-key (обработала — preventDefault; нет — Enter снимает фокус, как раньше).
// v1.62.1 (2026-10-30): Escape, закрывающий всплывающее окно вкладок и подсказку (i), — с preventDefault: не выводит Mac из полноэкранного режима.
// v1.62.0 (2026-10-30): длинный список в форме (combo) раскрывается ПОВЕРХ содержимого везде — position:fixed у поля (uiSelectPlace), кнопка остаётся невидимой и держит высоту ряда; вниз не влезает — вверх; соседи не двигаются.
// v1.61.0 (2026-10-30): подсветка :hover в ui-kit.css — только в @media (hover:hover); на касании iOS оставлял кнопки и плитки «нажатыми» после тапа.
// v1.60.1 (2026-10-29, константа и ?v= поднимаются позже): скрытая подсказка (i) — display:none, сдвиг --ui-info-dx считается заранее (uiInfoPlaceAll) и через left: у правого края заголовка она раздвигала страницу «Динамики» на телефоне; тост «прошлая версия» не показывается при штатном офлайне; поиск читателя — в колонке оглавления поле на всю ширину колонки, счётчик внутри справа, кнопки ‹ › второй строкой 50/50 (колонка не сжимается); глифы ‹ › по центру кнопок (flex, line-height 1) на всех ширинах. Фоновый скрипт 1.3.0: сообщение cab-stale (отдана прошлая версия ассета/страницы, сеть не ответила) → тост «Открыта прошлая версия страницы — сеть не ответила. Обновить» (uiStaleShow, #ui-stale, один на страницу).
// v1.59.0 (2026-10-28, константа и ?v= поднимаются позже, отдельным шагом): читатель markdown — сгибы <details>/<summary> (.ui-fold.rd-fold), якоря «## Заголовок {#id}» и ссылки [текст](#id), режим uiReaderHTML({sections:true}) «по разделам» (оглавление = переключатель, поиск по всему документу со счётчиком «·N» у разделов), выноски «> **Важно:** …» (.ui-callout), справка из нескольких файлов (UI_HELP.files / uiFetchMarkdownParts), абзац «{.ui-note} …»; исправлено: подпись полосы глав не обновлялась при включённом поиске.
// v1.58.0 (2026-10-28): uiReaderHTML({search:true}) — поиск по тексту читателя: поле .ui-qbox над оглавлением (на узком окне — над текстом), подсветка mark.rd-hit, «N из M», Enter/↓/↑/Esc; справки (uiHelpOpen, viewer-help) включают поиск по умолчанию.
// v1.57.1 (2026-10-26): hub «Уведомления» — сверху «Это устройство» | «Режим», ниже раздел = своя карточка (Портфель | Игры), по две в ряд.
// v1.57.0 (2026-10-26): уведомления кабинета — uiPushMount/uiPushOpen/uiPushBtnHTML (+ uiTopHTML({push})): hub — устройство, режим, все виды по разделам; страница раздела — свои виды и журнал; подписка — на portfolio-sw.js, как у вьюера. Перенесено из вьюера (раздел «Ещё → Уведомления»).
// v1.53.0 (2026-10-23): uiTimeChartHTML/uiTimeChartMount + .ui-tchart — график показателя во времени, 1:1 под ширину блока: ≤20 замеров — вся история; больше и не влезает — «полгода» с прокруткой вбок и переключателем «полгода · вся история» (медианы месяцев); паузы сжаты в разрыв, плотные недели — медиана с усиком, вторая серия пунктиром. Первая — «Здоровье» (давление верхнее/нижнее одной карточкой).
// v1.52.0 (2026-10-22): .ui-btn.lg (крупная), .ui-btn.ghost (контурная), .ui-btn:disabled; наведение — в @media (hover:hover). Первая — «Загрузки» вьюера (до 3.81 — «Проба сборки снапшота»).
// v1.51.0 (2026-10-16): шапка uiTopHTML — порядок кнопок как во вьюере: Обновить · Справка · Войти/Выйти · Тема (было Выйти · Справка · Обновить · Тема).
// v1.50.1 (2026-10-14): Enter — выйти из любого поля поиска с крестиком uiSearchX (поиск в «Здоровье» и «Еде»), не только .ui-q.
// v1.50.0 (2026-10-14): крестик поиска (uiSearchX) больше не ставит курсор в поле — только очищает; Enter в .ui-q — выйти из поля.
// v1.49.0 (2026-10-14): [фраза](#copy) в markdown — плашка .ui-say, нажатие копирует фразу (справки: «что сказать Claude»); uiCopyText.
// v1.48.0 (2026-10-14): .ui-modal.sheet (окно-шторка снизу на телефоне) + .ui-qrow/.ui-fbtn/.ui-freset (поиск + «Фильтры» + «Сброс»).
// v1.47.0 (2026-10-14): .ui-head-l + .ui-qbox/.ui-q — поле поиска в строке заголовка карточки (таблицы вьюера).
// v1.46.2 (2026-10-14): листание ← → и крестик окна — подсветка наведения только при мыши (на iPhone серый фон залипал после нажатия).
// v1.46.1 (2026-10-14): справка без цветной полосы сверху (3px акцента на скруглённом углу читалась как тонкая зелёная линия-артефакт).
// v1.46.0 (2026-10-13): uiHelpOpen(page, opener, {at}) / uiReaderMount({at}) — справка сразу на нужной главе; .uh-overlay поверх окон (z 900).
// v1.45.1 (2026-10-13): точки .ui-spark-pt.dot — 5–6px без обводки (были жирные кружки).
// v1.45.0 (2026-10-13): uiInfoHTML/uiInfoPlace — значок (i) с подсказкой, которая не исчезает сразу.
// v1.44.0 (2026-10-13): uiTableStickyHead — сдвиг копии шапки ведёт прокрутка (scroll-timeline), без отставания на iPhone.
// v1.43.0 (2026-10-13): uiTableStickyHead — липкая шапка у таблицы, прокручиваемой вбок (телефон).
// v1.42.0 (2026-10-13): сворачивание шапки окна на телефоне — .ui-modal.fold, uiFoldMount, uiFoldScroller;
//   uiModalHTML: subAlt (сжатая сводка), содержимое top — в .ui-modal-topin; uiStackKeepScroll
//   помнит прокрутку того, что реально прокручивается.
// v1.41.0 (2026-10-13): только CSS — .ui-table.dense (плотная таблица данных).
// v1.40.0 (2026-10-13): только CSS — нулевой уровень мини-графика (.ui-spark line.zero).
// v1.39.0 (2026-10-12): вьюер портфеля на ui-kit — строка разделов uiTabsHTML/uiTabsMount
//   (10+ пунктов, «Ещё ▾»), мост uiNode(html), появление uiAnimIn (листание ← →, смена
//   вкладки); uiModalHTML — слоты lead/aside/top. CSS: .ui-tabs, .ui-name, .ui-ci,
//   .ui-alert.info/.warn, сортировка/липкая шапка/tfoot у .ui-table, .ui-pager-btn.
// v1.38.0 (2026-10-07): uiShow/uiHide — плавные появление и уход окна, которое страница
//   показывает атрибутом hidden (окно документа travel/games, профиль travel); справка
//   въезжает и уходит плавно (uiHelpClose(true)).
// v1.37.0 (2026-10-07): uiPaneHTML — боковая панель одна на кабинет (была своя у health, 4 копии
//   inline-разметки); стопкой — теми же uiStack*. uiStackPop закрывает все слои от i (каждый уходит).
// v1.36.0 (2026-10-07): uiStackCls/uiStackPop/uiStackKeepScroll — логика окон стопкой из money
//   в ui-kit (классы слоя, закрытие с анимацией, прокрутка слоёв); одиночное окно — тем же.
// v1.35.0 (2026-10-07): JS без изменений — CSS: .ui-modal.tall (окно постоянной высоты).
// v1.34.0 (2026-10-07): uiModalHTML({ cls }) — окна стопкой с плавным переходом (enter/behind/leave/return).
// v1.33.0 (2026-10-07): uiModalHTML({ z }) — слой окна для окон стопкой (money: окно категории поверх «Обычных трат»).
// v1.32.0 (2026-10-07): JS без изменений — CSS: тулбар на телефоне, выбор месяцев, стрелка «все».
// v1.31.0 (2026-10-07): uiExpandIn/uiCollapseOut — плавное раскрытие и сворачивание блока
//   (money: раскрытая категория). CSS: карточка .ui-catopen, график «к прошлому году» .ui-cols.yoy.
// v1.30.0 (2026-10-06): JS без изменений — CSS: тулбар одной строкой, вторая линия графика.
// v1.29.0 (2026-10-06): длинный список в форме — поле с подсказками в потоке
//   (как «Добавить в список» у «Еды»); список в окне формы не заходит на шапку.
// v1.28.0 (2026-10-06): uiSaveBarHTML — плашка сохранения одна на кабинет.
// v1.27.0 (2026-10-06): uiFieldHTML — поле формы одно на кабинет (подсказка после
//   названия), стили .fld/.fld-lbl/.fld-hint — в ui-kit.css.
// v1.26.0 (2026-10-06): uiModalHTML — окно формы одно на кабинет (шапка и
//   кнопки закреплены, на телефоне во весь экран).
// v1.25.0 (2026-10-06): uiConfirm — своё окно подтверждения вместо confirm().
// v1.24.0 (2026-10-06): uiHelpOpen(page, opener, o) — справка вне реестра (вьюер
//   портфеля: свой файл, под паролем) тем же читателем с оглавлением.
// v1.23.0 (2026-10-06): навигация раздела — uiRailHTML/uiNavMount/uiNavSet:
//   один список на рельс и нижнюю панель; панель монтируется один раз в body.
// v1.22.0 (2026-10-06): JS без изменений — в CSS общая шапка окна документа.
// v1.21.0 (2026-10-06): uiSelect value — записанное значение вне списка не
//   теряется при сохранении формы (показывается «нет в списке»).
// v1.20.0 (2026-10-06): выпадающий список — один на кабинет: размер md (формы,
//   фильтры), поиск при > 12 вариантах, работа в формах (скрытое поле id,
//   change, подпись на месте), раскрытие по экрану (вверх, если внизу тесно),
//   на телефоне длинный список — шторкой у верха.
// v1.19.0 (2026-10-06): даты — один словарь месяцев и форматы uiDateLong /
//   uiMonthShort / uiDateNum / uiYmd / uiCap вместо копий на пяти страницах и
//   двух словарей здесь же (DP_*); вывод на страницах не изменился.
// v1.18.0 (2026-10-06): JS без изменений — в CSS .ui-hdr (нелипкая шапка) для
//   вьюера портфеля: его шапка теперь в одну строку, как у остальных.
// v1.17.0 (2026-10-06): шапка одна на кабинет — uiTopHTML (крошка «← Хаб»,
//   ромб и имя раздела, вход, справка, «Обновить», тема) вместо четырёх вёрсток;
//   тема — uiSetTheme/uiTheme + событие "ui-theme" вместо пяти копий
//   переключателя (games снимал атрибут, остальные ставили "light").
// v1.16.0 (2026-10-06): вход — одна реализация на кабинет. authFetch (был
//   копией в food/health/hub/money; credentials:"omit" обязателен — без него
//   неверный пароль открывает нативное окно и замораживает вкладку); отвергнутый
//   пароль (401 при отправленном токене) запоминается, и кнопка «Выйти» на всех
//   страницах становится «Войти заново»; uiGoLogin/uiLoginOk — уход на
//   login.html со страховкой от петли (были копии goLogin+BOUNCE_KEY в health
//   и money с разными условиями).
// v1.15.1 (2026-10-06): JS без изменений — CSS: ширина графика месяцев явно.
// v1.15.0 (2026-10-06): JS без изменений — в ui-kit.css плавная линия среднего и
//   подписи значений над столбиками; версия синхронизирована.
// v1.14.0 (2026-10-06): JS без изменений — в ui-kit.css один график месяцев
//   (столбики + скользящее среднее), строки категорий; версия синхронизирована.
// v1.13.0 (2026-10-06): JS без изменений — в ui-kit.css dot plot .ui-dots, плитки
//   KPI, строка статуса, карточка поездки (money: вкладка «Обзор»).
// v1.12.0 (2026-10-06): JS без изменений — в ui-kit.css .ui-split и мини-столбики
//   со средним .ui-mbars (money: «Обычные траты»); версия синхронизирована.
// v1.11.0 (2026-10-05): uiSelectHTML — выпадающий список из макета «Деньги»
//   (кнопка-карточка + список с галочкой; клавиатура, Esc, клик мимо; выбор —
//   событием ui-select). Страница раздела целиком на ui-kit (.ui-page/.ui-top/…,
//   стили в ui-kit.css) — первый потребитель money.html. UI_HELP: money.
// v1.10.0 (2026-10-05): Escape сворачивает открытую шторку оглавления
//   читателя (.rd-sheet) и не доходит до страницы — раньше одно нажатие
//   закрывало сразу всё окно документа. Стили: .ui-docwin (окно документа).
// v1.9.0 (2026-10-03): uiTripIsMine + UI_OWNER — «мои / для близких», одно имя
//   владельца на весь кабинет (travel: счётчики в сводке и «Ближайшая» только из
//   моих; hub: «мои · для близких» у числа поездок).
// v1.8.0 (2026-10-03): uiTripWhen — когда поездка, один расчёт для travel и hub
//   (поездка = точные даты start/end; ready + месяц — поездка с точностью до
//   месяца; иначе возможная поездка / идея без отсчёта времени; архив: прошла /
//   состоялась / срок прошёл без дат). uiReader: opts.actions — кнопки прыжка к
//   главе в столбце оглавления и в полосе (travel: «Сегодня»).
// v1.7.0 (2026-10-03): единый читатель markdown — uiReaderHTML/uiReaderMount
//   (порт режима чтения вьюера: оглавление столбцом или полосой снизу по ширине
//   окна, текущая глава, прогресс, TL;DR, врезные лиды, карточка frontmatter,
//   позиция чтения по ключу). uiMarkdown: вложенные списки, чек-листы, голые
//   ссылки, h5, «*» в адресах и коде больше не становится курсивом. Подключены:
//   справки (UI_HELP_TOC), подборки игр, отчёты здоровья.
// v1.6.0 (2026-10-02): JS без изменений — ui-kit.css стал единым файлом базы
//   (шрифты + токены тем + базовый слой body, --font-sans/--font-serif); версия
//   синхронизирована.
// v1.5.1 (2026-09-29): uiMarkdown — «\|» в ячейке таблицы = литеральная черта.
var UI_KIT_VERSION = '1.72.0';

/* ═══ uiFileSlot: слот выбора файла (образец — «Загрузка» вьюера) ══════════
   uiFileSlot({key,label,need,hint,accept,onChange,id,alias}) → {node,input,clear()}.
   Вся карточка — кнопка выбора, файл можно перетащить; «убрать» сбрасывает.
   data-state: empty | set. alias — префикс старых классов (pf → pf-file, pf-file-in…)
   на тех же узлах. Узел переживает перерисовки страницы: input хранит выбранный файл. */
function uiFileSize(n){ return n >= 1048576 ? (n / 1048576).toFixed(1).replace('.', ',') + ' МБ' : Math.max(1, Math.round(n / 1024)) + ' КБ'; }
function uiFileSlot(o){
  var al = o.alias ? function(sfx){ return ' ' + o.alias + sfx; } : function(){ return ''; };
  function mk(tag, cls, sfx, txt){ var e = document.createElement(tag); e.className = cls + al(sfx); if (txt != null) e.textContent = txt; return e; }
  var input = document.createElement('input');
  input.type = 'file'; input.className = 'ui-file-in' + al('-file-in'); input.id = o.id || ('ui-file-' + o.key);
  if (o.accept) input.accept = o.accept;
  var slot = mk('label', 'ui-file', '-file'); slot.htmlFor = input.id; slot.dataset.state = 'empty';
  var tag = mk('span', 'ui-tag' + (o.need ? ' need' : ''), '', o.need ? 'обязательно' : 'по желанию');
  var top = mk('div', 'ui-file-top', '-file-top');
  top.appendChild(mk('span', 'ui-file-t', '-file-t', o.label)); top.appendChild(tag);
  var name = mk('div', 'ui-file-name', '-file-name'), meta = mk('div', 'ui-file-meta', '-file-meta');
  var hint = mk('div', 'ui-sub ui-file-hint', '-file-hint', o.hint || '');
  slot.appendChild(input); slot.appendChild(top); slot.appendChild(name); slot.appendChild(meta); slot.appendChild(hint);
  function sync(){
    var file = input.files[0];
    slot.dataset.state = file ? 'set' : 'empty';
    name.textContent = file ? file.name : 'Файл не выбран';
    meta.textContent = '';
    if (file){
      meta.appendChild(document.createTextNode(uiFileSize(file.size) + ' · заменить · '));
      var rm = mk('button', 'ui-link ui-file-rm', '-file-rm', 'убрать'); rm.type = 'button';
      rm.addEventListener('click', function(e){ e.preventDefault(); e.stopPropagation(); clear(); });
      meta.appendChild(rm);
    } else meta.textContent = 'Выбрать или перетащить сюда';
  }
  function clear(){ input.value = ''; sync(); if (o.onChange) o.onChange(null); }
  input.addEventListener('change', function(){ sync(); if (o.onChange) o.onChange(input.files[0] || null); });
  slot.addEventListener('dragover', function(e){ e.preventDefault(); slot.classList.add('drag'); });
  slot.addEventListener('dragleave', function(){ slot.classList.remove('drag'); });
  slot.addEventListener('drop', function(e){
    e.preventDefault(); slot.classList.remove('drag');
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length){ input.files = e.dataTransfer.files; sync(); if (o.onChange) o.onChange(input.files[0] || null); }
  });
  sync();
  return { node: slot, input: input, clear: clear };
}

/* ═══ esc()/attr(): HTML-экранирование ════════════════════════════════════
   Единственная функция на все 5 страниц кабинета. Полный replace всех 5
   спецсимволов & < > " ' — безопасна и в текстовом узле (innerHTML), и в
   значении атрибута (value="…"/data-*="…"). attr — алиас: назначение то же,
   имя сохранено ради ~25 call-site'ов food.html (attr(...) в атрибутах),
   их менять незачем — attr(s) и esc(s) после унификации делают одно и то же. */
function esc(s){
  return String(s == null ? "" : s).replace(/[&<>"']/g, function(c){
    return { "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c];
  });
}
var attr = esc;

// plural — русская форма множественного числа (Ярус 1: был на 4 страницах идентично).
function plural(n, one, few, many){
  var m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return few;
  return many;
}

/* ═══ Auth/Refresh: Войти/Выйти + Обновить (Фаза 3) ═══════════════════════════
   Единая точка входа кабинета — токен localStorage["hub-auth"] (btoa
   hubuser:пароль), общий для origin'а: пишет login.html, читают вьюер
   портфеля, health, food и edit-слой travel. Приватные пути Caddy отдаёт
   ТОЛЬКО с явным Authorization; без него — тихий 403 (нативного окна пароля
   не бывает, см. шапку Caddyfile). «Обновить» — сброс TTL-кеша страницы +
   новый cache-buster + reload; паттерн один на все пять страниц, отличается
   только префикс localStorage-ключей (`<prefix>-cache:*`/`<prefix>-cb`).

   Четыре расхождения старых копий, которые общий хелпер ОБЯЗАН учитывать —
   иначе тихая регрессия (см. tools/design-reference/ui-kit-plan.md §Фаза 3):
     1. loginUrl(why) несёт per-page параметр (hub → why=hub, health →
        why=health, food → why=food) — why передаётся аргументом, НЕ хардкодится.
     2. uiRefresh(btn) читает data-cache-prefix с самой кнопки: чистит
        `<prefix>-cache:*`, ставит И `<prefix>-cb`, И `<prefix>-last-refresh`
        (последний ключ раньше писал только hub — на travel/games безвреден,
        пишем всегда, без спецкейсов по странице).
     3. uiLogout(btn) тоже читает data-cache-prefix и, кроме
        clearAuthToken()+reload, обязан чистить `<prefix>-cache:*` и пытаться
        removeItem("piv-seen") — иначе hub-сводка «зависает» после выхода
        (это фиксировал комментарий в старом hub.html при логаут-обработчике).
     4. Канон имени сброса токена — clearAuthToken() (у старого hub было
        clearToken() — переименовано при переносе, вызовы на странице править).
   ═══════════════════════════════════════════════════════════════════════════ */
function authToken(){ try { return localStorage.getItem("hub-auth") || ""; } catch(e){ return ""; } }
function clearAuthToken(){ try { localStorage.removeItem("hub-auth"); } catch(e){} }
function loginUrl(why){ return "login.html?why=" + encodeURIComponent(why || "hub") + "&next=" + encodeURIComponent(location.pathname + location.search); }

/* Отпечаток токена (не сам токен — второй копии пароля в хранилище не нужно). */
function uiAuthMark(tok){
  var h = 5381;
  for (var i = 0; i < tok.length; i++) h = ((h << 5) + h + tok.charCodeAt(i)) | 0;
  return String(h >>> 0);
}
/* Сервер отверг ИМЕННО этот токен (401 бывает только при неверном пароле:
   без токена Caddy отвечает тихим 403 — tools/tests/test_caddy_zones.py).
   Метка общая для всех страниц origin'а и сама гаснет, когда токен сменился. */
function uiAuthRejected(){
  var tok = authToken();
  if (!tok) return false;
  try { return localStorage.getItem("hub-auth-rejected") === uiAuthMark(tok); } catch(e){ return false; }
}
function uiMarkAuthRejected(tok){
  try { localStorage.setItem("hub-auth-rejected", uiAuthMark(tok)); } catch(e){}
  /* уже нарисованные «Выйти» (статичные шапки hub/travel/games) — сразу
     заменить на «Войти заново»; страницы, что перерисовывают шапку сами,
     получат то же из authBtnHTML */
  var bs = document.querySelectorAll('[data-act="logout"][data-cache-prefix]');
  for (var i = 0; i < bs.length; i++){
    var b = bs[i];
    b.outerHTML = authBtnHTML({ why: b.getAttribute("data-why") || "hub", prefix: b.getAttribute("data-cache-prefix") });
  }
}

/* Единственный fetch к приватным данным кабинета (было 4 копии в страницах).
   credentials:"omit" — КРИТИЧНО: при неверном пароле Caddy шлёт 401 с
   WWW-Authenticate, и без omit браузер открыл бы НАТИВНОЕ окно пароля,
   замораживающее вкладку. Явный Authorization при этом уходит. */
function authFetch(url, init){
  init = init || {};
  init.credentials = "omit";
  var tok = authToken();
  if (tok){
    var h = new Headers(init.headers || {});
    h.set("Authorization", "Basic " + tok);
    init.headers = h;
  }
  return fetch(url, init).then(function(r){
    if (r.status === 401 && tok) uiMarkAuthRejected(tok);
    return r;
  });
}

/* Уход на login.html для страниц, целиком закрытых паролем (health, money).
   Страховка от петли: если только что (< 20 с) уже уводили, а данные опять не
   отдаются, — дело не в пароле; второй раз не уводим, а зовём onLoop(есть ли
   токен), и страница объясняет, что не так. Метка — `<why>-login-bounce` в
   sessionStorage; успешная загрузка снимает её через uiLoginOk(why). */
function uiGoLogin(why, onLoop){
  var key = why + "-login-bounce", last = 0;
  try { last = parseInt(sessionStorage.getItem(key) || "0", 10); } catch(e){}
  if (Date.now() - last < 20000){ if (onLoop) onLoop(!!authToken()); return false; }
  try { sessionStorage.setItem(key, String(Date.now())); } catch(e){}
  location.replace(loginUrl(why));
  return true;
}
function uiLoginOk(why){ try { sessionStorage.removeItem(why + "-login-bounce"); } catch(e){} }

/* ОДИН элемент — тернарник Войти/Выйти (заменяет hub-пару #btn-login/
   #btn-logout — оба узла были hidden и переключались JS'ом уже ПОСЛЕ первой
   отрисовки, что давало на миг видимыми обе кнопки/ни одной). why → страница
   входа (login.html?why=…), prefix → data-cache-prefix кнопки «Выйти» — его
   читает uiLogout, чтобы почистить кеш именно этого домена, а не чужого. */
function authBtnHTML(opts){
  opts = opts || {};
  var why = opts.why || "hub", prefix = opts.prefix || why;
  if (!authToken())
    return '<a class="chip-btn" href="' + attr(loginUrl(why)) + '" title="Войти в кабинет">Войти</a>';
  /* пароль сервер уже отверг — «Выйти» обманывает: данные не грузятся */
  if (uiAuthRejected())
    return '<a class="chip-btn" data-auth="stale" href="' + attr(loginUrl(why)) + '" title="Пароль больше не подходит — войдите заново">Войти заново</a>';
  return '<button class="chip-btn" data-act="logout" data-cache-prefix="' + attr(prefix) + '" data-why="' + attr(why) + '" title="Выйти из кабинета">Выйти</button>';
}

/* ═══ Кеш и листинги каталогов (ui-kit 1.19.0) ═══════════════════════════════
   Были копиями: bust ×5 (food без метки дописывал «cb=0», money читал метку
   сам), cacheGet/cacheSet ×3, listDir ×3 (hub — с паролем, travel — с mod_time,
   games — своим ключом), fetchText ×2. Ключи — те же, что чистит uiRefresh:
   метка обновления `<prefix>-cb`, кеш `<prefix>-cache:<ключ>`.
     uiBust(prefix, url)        ?cb=<метка «Обновить»>, нет метки — url как есть
     uiCacheGet(prefix, key, ttlMin) / uiCacheSet(prefix, key, v)
     uiFetchText(url, o)        текст с кешем; o = { prefix, ttlMin, auth, accept }
     uiListDir(url, o)          листинг Caddy (Accept: application/json) →
                                [{ name, isDir, mtime }] без «.»/«@»-служебных
   auth:true — через authFetch (приватные пути), иначе обычный fetch. */
function uiBust(prefix, url){
  var cb = "";
  try { cb = localStorage.getItem(prefix + "-cb") || ""; } catch(e){}
  return cb ? url + (url.indexOf("?") < 0 ? "?" : "&") + "cb=" + encodeURIComponent(cb) : url;
}
function uiCacheGet(prefix, key, ttlMin){
  try {
    var raw = localStorage.getItem(prefix + "-cache:" + key);
    if (!raw) return null;
    var obj = JSON.parse(raw);
    if (Date.now() - obj.t > (ttlMin || 60) * 60000) return null;
    return obj.v;
  } catch(e){ return null; }
}
function uiCacheSet(prefix, key, v){
  try { localStorage.setItem(prefix + "-cache:" + key, JSON.stringify({ t: Date.now(), v: v })); } catch(e){}
}
function uiGet(url, o, accept){
  var init = accept ? { headers: { "Accept": accept } } : {};
  return (o.auth ? authFetch : fetch)(uiBust(o.prefix, url), init).then(function(r){
    if (!r.ok) throw new Error(url + " → " + r.status);
    return r;
  });
}
function uiFetchText(url, o){
  o = o || {};
  var hit = uiCacheGet(o.prefix, url, o.ttlMin);
  if (hit !== null) return Promise.resolve(hit);
  return uiGet(url, o, o.accept).then(function(r){ return r.text(); })
    .then(function(t){ uiCacheSet(o.prefix, url, t); return t; });
}
function uiListDir(url, o){
  o = o || {};
  var key = "d:" + url, hit = uiCacheGet(o.prefix, key, o.ttlMin);
  if (hit !== null) return Promise.resolve(hit);
  return uiGet(url, o, "application/json").then(function(r){ return r.json(); }).then(function(arr){
    if (!Array.isArray(arr)) throw new Error("not a listing");
    /* Caddy пишет имена директорий с хвостовым слэшем; @eaDir — служебные
       Synology. mod_time (RFC3339) → мс: кнопка «План» travel ведёт на
       последний по времени артефакт; нет поля — 0, решает запасной порядок. */
    var v = arr.map(function(e){
      return { name: (e.name || "").replace(/\/+$/, ""), isDir: !!e.is_dir, mtime: Date.parse(e.mod_time || "") || 0 };
    }).filter(function(e){ return e.name && e.name.charAt(0) !== "." && e.name.charAt(0) !== "@"; });
    uiCacheSet(o.prefix, key, v);
    return v;
  });
}

/* Общая логика кнопки «Обновить»: сброс TTL-кеша страницы под её префиксом +
   новый cache-buster + reload. data-refresh-ico/data-refresh-lbl — опциональные
   потомки кнопки (иконка/подпись), не у всех страниц есть оба — оба поиска
   graceful на null. */
function uiRefresh(btn){
  if (btn.disabled) return;
  var prefix = btn.getAttribute("data-cache-prefix");
  if (!prefix) return;   // без префикса — не наша кнопка (food/health ведут её сами)
  btn.disabled = true;
  var ico = btn.querySelector("[data-refresh-ico]"); if (ico) ico.classList.add("spin");
  var lbl = btn.querySelector("[data-refresh-lbl]"); if (lbl) lbl.textContent = "Обновляю…";
  try {
    for (var i = localStorage.length - 1; i >= 0; i--){
      var k = localStorage.key(i);
      if (k && k.indexOf(prefix + "-cache:") === 0) localStorage.removeItem(k);
    }
    localStorage.setItem(prefix + "-cb", String(Date.now()));
    localStorage.setItem(prefix + "-last-refresh", String(Date.now()));
  } catch(e){}
  setTimeout(function(){ location.reload(); }, 400);
}

/* Общая логика кнопки «Выйти»: сброс токена + сброс piv-seen (иначе
   портфельный виджет hub «зависает» на старом состоянии) + чистка кеша СВОЕГО
   префикса + reload. */
function uiLogout(btn){
  var prefix = btn && btn.getAttribute ? btn.getAttribute("data-cache-prefix") : "";
  clearAuthToken();
  /* офлайн-копия приватных данных (фоновый скрипт, ui-kit 1.54.0) — стереть вместе со входом */
  try { if (navigator.serviceWorker && navigator.serviceWorker.controller)
          navigator.serviceWorker.controller.postMessage({ type: "cab-logout" }); } catch(e){}
  try { localStorage.removeItem("piv-seen"); } catch(e){}
  try {
    if (prefix) for (var i = localStorage.length - 1; i >= 0; i--){
      var k = localStorage.key(i);
      if (k && k.indexOf(prefix + "-cache:") === 0) localStorage.removeItem(k);
    }
  } catch(e){}
  location.reload();
}

/* Делегированный click-листенер ui-kit: реагирует ТОЛЬКО на [data-act] с
   ПРОСТАВЛЕННЫМ data-cache-prefix — дискриминатор, чтобы сосуществовать с
   доменными data-act-диспетчерами food/health без задвоения. Кнопки refresh
   food/health намеренно БЕЗ data-cache-prefix (свой SPA-перерендер) — этот
   листенер их молча игнорирует. stopPropagation НЕ вызываем: доменные
   диспетчеры пусть тоже отработают — они graceful на неизвестном act
   (food: `if (!fn) return;`; health: logout-ветка убрана из ACTS явно). */
document.addEventListener("click", function(ev){
  var btn = ev.target.closest ? ev.target.closest("[data-act]") : null;
  if (!btn) return;
  if (!btn.getAttribute("data-cache-prefix")) return;
  var act = btn.getAttribute("data-act");
  if (act === "refresh"){ ev.preventDefault(); uiRefresh(btn); }
  else if (act === "logout"){ ev.preventDefault(); uiLogout(btn); }
}, false);

/* ═══ Справка раздела (❓) ═══════════════════════════════════════════════════
   Аналог «❓ Справки» портфельного вьюера для остальных страниц кабинета:
   какие скиллы наполняют данные раздела, как их вызвать, на какой модели,
   в каком порядке и где результат видно на странице.

   Содержимое — НЕ в коде, а в assets/help/<page>.md (деплоится вместе с
   assets/, Caddy отдаёт его публично как и остальные ассеты; *.md получают
   Cache-Control: no-cache — правка справки видна без бампа версии).
   SSOT справки — сам .md; источники истины, с которыми его надо сверять при
   правке скиллов, перечислены в SYNC-комментарии в его шапке.

   UI_HELP — реестр разделов: что за файл, заголовок, доменный акцент.
   Новый раздел = строка здесь + файл assets/help/<page>.md + кнопка
   helpBtnHTML(page) в топбаре (контракт — tools/tests/test_pages_contracts.py). */
var UI_HELP = {
  hub:    { title: "Личный кабинет", acc: "--accent" },
  travel: { title: "Путешествия",    acc: "--c-4" },
  games:  { title: "Игры",           acc: "--c-5" },
  health: { title: "Здоровье",       acc: "--c-3" },
  money:  { title: "Деньги",         acc: "--c-6" }
};

function helpBtnHTML(page){
  return '<button type="button" class="chip-btn" data-ui-help="' + attr(page) + '" ' +
    'title="Справка: какие скиллы ведут данные этой страницы и как их запускать" aria-label="Справка">' +
    '<span class="uh-ico" aria-hidden="true">❓</span><span class="h-btn-lbl">Справка</span></button>';
}

/* ═══ Шапка раздела и тема ═════════════════════════════════════════════════
   Одна шапка на кабинет (ui-kit 1.17.0). Раньше их было четыре: статичная
   разметка .h-top/.crumb (hub, travel, games — у games ещё и свои имена
   .h-sep/.h-ident/.h-diamond), сборка скриптом с классами (health), сборка со
   стилями прямо в разметке (food) и .ui-top (money). Крошка «← Хаб», подписи
   кнопок и правила для телефона на каждой странице вели себя по-своему.

   uiTopHTML({ page, name?, tag?, brand?, refresh?, refreshing?, share?, help? })
     page   — ключ раздела: why для входа, префикс кеша, справка, акцент (UI_ACC)
     name   — имя раздела (ромб + имя); без него — brand (хаб: «Synology · …»)
     refresh — "page" (по умолчанию): кнопка несёт data-cache-prefix=page, её
               ведёт uiRefresh; "spa": без префикса — страница перечитывает сама
               (food/health), refreshing — крутить значок
     share  — гостевой режим (travel ?trip=): без крошки, входа и справки
     help   — false у раздела без справки (food)
   Статичные страницы вставляют шапку прямо при разборе страницы:
     <script>document.currentScript.insertAdjacentHTML("beforebegin", uiTopHTML({…}))</script>
   — ui-kit.js для этого подключён в <head>, мигания нет. */
var UI_ACC = { hub: "--accent", travel: "--c-4", games: "--c-5", health: "--c-3", money: "--c-6", food: "--c-2" };

function uiTheme(){ return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light"; }
function uiThemeLabel(t){ return t === "dark" ? "Светлая тема" : "Тёмная тема"; }
/* Сменить тему: атрибут на <html>, запомнить в hub-theme (общий для кабинета),
   подписи всех кнопок темы, событие "ui-theme" (detail — новая тема) —
   страницы, что рисуют от темы (узор фона, графики), перерисовываются по нему. */
function uiSetTheme(t, persist){
  t = t === "dark" ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", t);
  if (persist !== false) try { localStorage.setItem("hub-theme", t); } catch(e){}
  var ls = document.querySelectorAll("[data-theme-lbl]");
  for (var i = 0; i < ls.length; i++) ls[i].textContent = uiThemeLabel(t);
  var ev; try { ev = new CustomEvent("ui-theme", { detail: t }); } catch(e){ ev = null; }
  if (ev) document.dispatchEvent(ev);
}
function uiThemeBtnHTML(){
  return '<button type="button" class="chip-btn" data-act="theme" data-ui-theme aria-label="Переключить тему">' +
    '<span aria-hidden="true">◐</span><span class="h-btn-lbl" data-theme-lbl>' + uiThemeLabel(uiTheme()) + '</span></button>';
}
/* ═══ Режим сайта «с ИИ / без ИИ» (ui-kit 1.67.0) ════════════════════════════
   Флаг — Claude-Memory/_hub/settings.json (hub-settings@1); пишет только hub-api (GET/POST ../api/hub/settings).
   Атрибут data-noai на <html> ставится синхронно из кэша localStorage["hub-noai"] (ui-kit подключён в <head>,
   мигания нет), затем уточняется запросом с токеном. Страницы реагируют на CSS html[data-noai] и событие
   "ui-noai" (detail: "on"|"off"). Переключение — только с хаба (uiTopHTML({ mode: true })).
     uiAiMode() → "on"|"off";   uiAiModeFetch() → Promise {hash, settings}
     uiAiModeSet(mode, note) → Promise settings — GET хэша → POST, при 409 один повтор со свежим хэшем
     uiAiReturnOpen() — окно «Вернуться к ИИ»: правки сайта за период off_since по видам + зеркало Mac. */
var UI_NOAI_API = "../api/hub/";
var UI_NOAI = { hash: null, settings: null, loaded: false };
var UI_NOAI_KINDS = [            // зеркало KINDS из tools/noai_return.py — подписи правок сайта по путям
  ["Portfolio/decisions/", "решения владельца с сайта"],
  ["Portfolio/conditions.yaml", "условия-напоминания"],
  ["Portfolio/conditions-state.json", "состояние условий (сделал / отложить / не актуально)"],
  ["Portfolio/plan", "план и журнал плана"],
  ["Portfolio/snapshots/", "снапшоты сайта"],
  ["Portfolio/stress/auto/", "пересчёты стресса"],
  ["Portfolio/known-splits.json", "реестр сплитов"],
  ["Portfolio/security-attrs.json", "атрибуты бумаг"],
  ["scenarios/", "веса сценариев и сроки"],
  ["Gaming/user-state.json", "оверлей игр"],
  ["Gaming/", "игры: прочее"],
  ["Health/labs.json", "точки анализов"],
  ["Health/studies", "исследования и файлы"],
  ["Health/reports/", "отчёты здоровья"],
  ["Health/", "здоровье: прочее"],
  ["ZenMoney/audit/", "итоги месяцев и поездок из CSV"],
  ["ZenMoney/", "деньги: прочее"],
  ["_hub/", "настройки сайта"],
  ["Portfolio/", "портфель: прочее"]
];
(function(){ try { if (localStorage.getItem("hub-noai") === "off") document.documentElement.setAttribute("data-noai", ""); } catch(e){} })();
function uiAiMode(){ return document.documentElement.hasAttribute("data-noai") ? "off" : "on"; }
function uiAiModeLabel(m){ return m === "off" ? "Режим: без ИИ" : "Режим: с ИИ"; }
function uiAiModeApply(mode, settings){
  var off = mode === "off";
  if (settings) UI_NOAI.settings = settings;
  if (off) document.documentElement.setAttribute("data-noai", ""); else document.documentElement.removeAttribute("data-noai");
  try { localStorage.setItem("hub-noai", off ? "off" : "on"); } catch(e){}
  var ls = document.querySelectorAll("[data-noai-lbl]");
  for (var i = 0; i < ls.length; i++) ls[i].textContent = uiAiModeLabel(off ? "off" : "on");
  var bs = document.querySelectorAll("[data-ui-noai]");
  for (var j = 0; j < bs.length; j++) bs[j].classList.toggle("is-off", off);
  var ev; try { ev = new CustomEvent("ui-noai", { detail: off ? "off" : "on" }); } catch(e){ ev = null; }
  if (ev) document.dispatchEvent(ev);
}
function uiAiModeFetch(){
  return authFetch(UI_NOAI_API + "settings?cb=" + Date.now(), { cache: "no-store" })
    .then(function(r){ if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(function(b){
      UI_NOAI.hash = b.hash; UI_NOAI.loaded = true;
      var m = b.settings && b.settings.ai_mode === "off" ? "off" : "on";
      if (m !== uiAiMode() || !UI_NOAI.settings) uiAiModeApply(m, b.settings); else UI_NOAI.settings = b.settings;
      return b;
    });
}
function uiAiModeSet(mode, note){
  var body = { settings: { ai_mode: mode, by: "site", note: note || null } };
  function post(hash){
    body.base_hash = hash;
    return authFetch(UI_NOAI_API + "settings", { method: "POST", headers: { "Content-Type": "application/json" },
                                                 body: JSON.stringify(body) })
      .then(function(r){ return r.json().then(function(b){ return { status: r.status, body: b }; }); });
  }
  return uiAiModeFetch().then(function(b){ return post(b.hash); })
    .then(function(res){
      if (res.status === 409) return post(res.body.current_hash);   // кто-то переключил параллельно — один повтор
      return res;
    })
    .then(function(res){
      if (res.status !== 200) throw new Error((res.body && (res.body.detail || res.body.error)) || ("HTTP " + res.status));
      UI_NOAI.hash = res.body.hash;
      uiAiModeApply(res.body.settings.ai_mode, res.body.settings);
      return res.body.settings;
    });
}
function uiAiModeBtnHTML(){
  var m = uiAiMode();
  return '<button type="button" class="chip-btn' + (m === "off" ? ' is-off' : '') + '" data-act="ai-mode" data-ui-noai ' +
    'aria-label="Режим сайта: с ИИ или без ИИ" title="Без ИИ: скиллы не пишут в Claude-Memory, команды для Claude скрыты, правки идут с сайта">' +
    '<span aria-hidden="true">◇</span><span class="h-btn-lbl" data-noai-lbl>' + uiAiModeLabel(m) + '</span></button>';
}
function uiAiSinceLabel(since){
  var d = new Date(since);
  if (isNaN(d)) return "Сайт в режиме без ИИ";
  var hm = ("0" + d.getHours()).slice(-2) + ":" + ("0" + d.getMinutes()).slice(-2);
  return "Сайт в режиме без ИИ с " + uiDateLong(d) + ", " + hm;
}
function uiAiKind(path){
  for (var i = 0; i < UI_NOAI_KINDS.length; i++) if (path.indexOf(UI_NOAI_KINDS[i][0]) === 0) return UI_NOAI_KINDS[i][1];
  return "прочее";
}
function uiAiReturnClose(){
  var m = document.getElementById("ui-noai-return");
  if (!m) return;
  document.removeEventListener("keydown", uiAiReturnKey, true);
  if (m.parentNode) m.parentNode.removeChild(m);
  try { if (m.__opener && m.__opener.focus) m.__opener.focus({ preventScroll: true }); } catch(e){}
}
function uiAiReturnKey(ev){
  if (ev.key === "Escape"){ ev.preventDefault(); ev.stopImmediatePropagation(); uiAiReturnClose(); }
}
function uiAiReturnOpen(){
  uiAiReturnClose();
  var since = UI_NOAI.settings && UI_NOAI.settings.off_since;
  var wrap = document.createElement("div");
  wrap.id = "ui-noai-return";
  wrap.__opener = document.activeElement;
  wrap.innerHTML = uiModalHTML({
    title: "Вернуться к ИИ", close: "noai-return-close", cls: "compact enter", width: 560,   // по центру и на телефоне (как uiConfirm), enter — появление
    sub: since ? uiAiSinceLabel(since) : "Сайт в режиме без ИИ",
    body: '<div class="ui-noai-list"><div class="ui-state">Считаю правки сайта за период…</div></div>' +
      '<p class="ui-noai-warn">Зеркало Mac должно догнать NAS (клиент Synology Drive — «Up to date»): скрипты скиллов сверяют его с сайтом ' +
      'сами перед записью и откажут, пока оно отстаёт. Правки сайта скиллы учитывают первым шагом.</p>',
    foot: '<span class="ui-modal-sp"></span><button type="button" class="ui-modal-cancel" data-act="noai-return-close">Отмена</button>' +
          '<button type="button" class="ui-modal-save" data-act="noai-return-ok">Вернуться к ИИ</button>'
  });
  document.body.appendChild(wrap);
  document.addEventListener("keydown", uiAiReturnKey, true);   // Esc закрывает, как у uiConfirm
  try { wrap.querySelector(".ui-modal-x").focus({ preventScroll: true }); } catch(e){}
  var list = wrap.querySelector(".ui-noai-list");
  // настройки могли не успеть прийти (клик сразу после загрузки) или их нет без входа — сначала спросить сервер
  var ready = UI_NOAI.settings ? Promise.resolve(UI_NOAI.settings) : (authToken() ? uiAiModeFetch().then(function(b){ return b.settings; }) : Promise.reject(new Error("noauth")));
  ready.then(function(st){
    since = st && st.off_since;
    var sub = wrap.querySelector(".ui-modal-sub");
    if (sub && since) sub.textContent = uiAiSinceLabel(since);
    if (!since) throw new Error("nosince");
    return authFetch(UI_NOAI_API + "changes?since=" + encodeURIComponent(since), { cache: "no-store" })
      .then(function(r){ if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); });
  })
    .then(function(b){
      var counts = {}, names = {}, files = b.files || [];
      files = files.filter(function(f){ return (f.path || "") !== "_hub/settings.json"; });   // сам флаг — не правка владельца
      files.forEach(function(f){
        var k = uiAiKind(f.path || ""); counts[k] = (counts[k] || 0) + 1;
        (names[k] = names[k] || []).push((f.path || "").split("/").pop());
      });
      var keys = Object.keys(counts).sort(function(a, c){ return counts[c] - counts[a]; });
      list.innerHTML = files.length
        ? '<div class="ui-noai-head">За это время на сайте изменено файлов: ' + files.length + (b.truncated ? ' (список обрезан)' : '') + '</div><ul class="ui-noai-kinds">' +
          keys.map(function(k){
            var nm = names[k].slice(0, 3).join(", ") + (names[k].length > 3 ? " …" : "");
            return '<li><span>' + esc(k) + '<small class="ui-noai-files">' + esc(nm) + '</small></span><b>' + counts[k] + '</b></li>';
          }).join("") + '</ul>'
        : '<div class="ui-state">За период на сайте ничего не менялось.</div>';
    })
    .catch(function(e){
      var msg = e.message === "noauth" ? "Нет входа на этом устройстве — список правок сервер не отдаёт. Войдите (кнопка в шапке) и откройте окно снова."
        : e.message === "nosince" ? "Сервер не записал момент выключения: режим включён другим путём или файл настроек пересоздан. Возвращаться можно."
        : "Сайт не ответил на запрос правок (" + esc(e.message) + ") — возвращаться можно, но правки сверьте скриптом noai_return.py.";
      list.innerHTML = '<div class="ui-state err">' + msg + '</div>';
    });
}
document.addEventListener("click", function(ev){
  var t = ev.target.closest ? ev.target : null;
  if (!t) return;
  var btn = t.closest('[data-act="ai-mode"][data-ui-noai]');
  if (btn){
    ev.preventDefault();
    if (uiAiMode() === "on"){
      uiConfirm({ title: "Выключить ИИ на сайте?", danger: false, ok: "Выключить", cancel: "Оставить",
                  text: "Скиллы перестанут писать в Claude-Memory, команды для Claude на страницах скроются, " +
                        "плашки свежести отчётов станут серыми. Правки — только с сайта. Вернуть можно той же кнопкой." })
        .then(function(ok){ if (ok) return uiAiModeSet("off"); })
        .catch(function(e){ alert("Не удалось переключить режим: " + e.message); });
    } else uiAiReturnOpen();
    return;
  }
  if (t.closest('[data-act="noai-return-close"]')){ ev.preventDefault(); uiAiReturnClose(); return; }
  if (t.closest('[data-act="noai-return-ok"]')){
    ev.preventDefault();
    var b = t.closest('[data-act="noai-return-ok"]'); b.disabled = true;
    uiAiModeSet("on").then(uiAiReturnClose).catch(function(e){ b.disabled = false; alert("Не удалось вернуть режим: " + e.message); });
  }
}, false);
document.addEventListener("DOMContentLoaded", function(){ if (authToken()) uiAiModeFetch().catch(function(){}); });

function uiRefreshBtnHTML(o){
  o = o || {};
  var spa = o.refresh === "spa";
  return '<button type="button" class="chip-btn" data-act="refresh"' +
    (spa ? "" : ' data-cache-prefix="' + attr(o.page) + '"') + (o.refreshing ? " disabled" : "") +
    ' title="Сбросить кеш и обновить данные">' +
    '<span data-refresh-ico aria-hidden="true"' + (o.refreshing ? ' class="spin"' : "") + '>⟳</span>' +
    '<span class="h-btn-lbl" data-refresh-lbl>' + (o.refreshing ? "Обновляю…" : "Обновить") + '</span></button>';
}
function uiTopHTML(o){
  o = o || {};
  var page = o.page || "hub", acc = UI_ACC[page] || "--accent";
  var left = o.name
    ? (o.share ? "" : '<a class="ui-crumb" href="hub.html"><span class="ui-crumb-arw">←</span><span class="ui-crumb-lbl"> Хаб</span></a><span class="ui-top-div"></span>') +
      '<div class="ui-top-sec"><span class="ui-top-dot"></span><span class="ui-top-name">' + esc(o.name) + '</span>' +
        (o.tag ? '<span class="ui-tag">' + esc(o.tag) + '</span>' : "") + '</div>'
    : '<span class="ui-top-brand">' + esc(o.brand || "") + '</span>';
  return '<div class="ui-top" data-ui-top="' + attr(page) + '" style="--sec-acc:var(' + acc + ')">' + left +
    '<div class="ui-top-spacer"></div>' +
    // порядок кнопок — как во вьюере портфеля (решение владельца 2026-10-16):
    // Обновить · [свои кнопки страницы] · Справка · Войти/Выйти · Тема
    uiRefreshBtnHTML(o) +
    (o.mode && !o.share ? uiAiModeBtnHTML() : "") +            // 1.67.0: «Режим: с ИИ / без ИИ» — только хаб
    (o.push && !o.share ? uiPushBtnHTML(o.push) : "") +       // 1.57.0: «Уведомления» — hub ("all") и разделы
    (o.share || o.help === false ? "" : helpBtnHTML(page)) +
    (o.share ? "" : authBtnHTML({ why: page, prefix: page })) +
    uiThemeBtnHTML() +
  '</div>';
}
/* ═══ Плашка сохранения (ui-kit 1.28.0) ═════════════════════════════════════
   «Сохраняю…», ошибка записи, сообщение — внизу по центру экрана, над нижней
   панелью навигации (--ui-mnav-offset) и над окнами форм. Было: класс
   .savebar у health (слой 220) и инлайн-стили у food (слой 300, радиус 999px
   у «Сохраняю…» и обычный у сообщений — длинный текст раздувал пилюлю).
     uiSaveBarHTML({ text, kind: "busy"|"err"|"ok", dismiss? }) — dismiss —
     data-act кнопки «Понятно» (её ловит страница). */
function uiSaveBarHTML(o){
  o = o || {};
  if (!o.text) return "";
  var kind = o.kind || "busy";
  /* вид — общее уведомление .ui-toast (ui-kit 1.56.0): почти во всю ширину, низкое, крестик по центру */
  return '<div class="ui-savebar ui-toast ' + kind + '" role="' + (kind === "err" ? "alert" : "status") + '">' +
    '<span class="ui-toast-txt">' + esc(o.text) + '</span>' +
    (o.dismiss ? '<button type="button" class="ui-savebar-x ui-toast-x" data-act="' + attr(o.dismiss) + '" aria-label="Скрыть">✕</button>' : '') +
  '</div>';
}

/* ═══ Поле формы (ui-kit 1.27.0) ═══════════════════════════════════════════════
   Одно на кабинет: было по fld() в health (подсказка серым после названия,
   <label> вокруг) и в food (подсказка строкой ПОД полем, label for=), стили
   .fld/.fld-lbl — копиями с разными шрифтом и отступами. Решение владельца
   2026-10-06: подсказка — после названия («Дозировка · в одной таблетке»).
     uiFieldHTML({ label, id, value?, ph?, hint?, span?, type?, area?, rows?,
                   suffix?, suffixCls?, inputmode?, extra?, style? })
       span   — true: во всю строку сетки (1 / -1); число N: span N;
       area   — многострочное поле (rows — стартовая высота);
       suffix — единица справа в поле («г»), suffixCls — класс для живой правки;
       extra  — сырые атрибуты поля (data-*, disabled…).
   Id поля не меняется — код сохранения читает его как раньше. */
function uiFieldHTML(o){
  o = o || {};
  var span = o.span === true ? "grid-column:1 / -1;" : (o.span > 1 ? "grid-column:span " + o.span + ";" : "");
  var v = attr(o.value == null ? "" : o.value);
  var common = ' class="fld' + (o.suffix != null ? ' has-sfx' : '') + '" id="' + attr(o.id) + '" placeholder="' + attr(o.ph || "") + '"' +
    (o.inputmode ? ' inputmode="' + attr(o.inputmode) + '"' : '') + (o.extra ? " " + o.extra : "") + (o.style ? ' style="' + attr(o.style) + '"' : '');
  var input = o.area
    ? '<textarea' + common + (o.rows ? ' rows="' + attr(o.rows) + '"' : '') + '>' + esc(o.value == null ? "" : o.value) + '</textarea>'
    : '<input' + common + ' type="' + attr(o.type || "text") + '" value="' + v + '">';
  if (o.suffix != null)
    input = '<span class="ui-field-in">' + input + '<span class="ui-field-sfx num' + (o.suffixCls ? " " + attr(o.suffixCls) : "") + '">' + esc(o.suffix) + '</span></span>';
  return '<label class="ui-field"' + (span ? ' style="' + span + '"' : '') + '><span class="fld-lbl">' + esc(o.label || "") +
    (o.hint ? ' <span class="fld-hint">· ' + esc(o.hint) + '</span>' : '') + '</span>' + input + '</label>';
}

/* ═══ Окно формы (ui-kit 1.26.0) ═══════════════════════════════════════════════
   Одно на кабинет: было своё у health (шапка и кнопки закреплены) и у food
   (прокручивалось всё окно — «Сохранить» уезжал вниз длинной формы; клик
   внутри гасила заглушка data-act="noop"). Решения владельца 2026-10-06:
   шапка и кнопки всегда видны, прокручиваются только поля; на телефоне
   (и любом экране ниже 500px — телефон лёжа) окно — во весь экран.
     uiModalHTML({ title, sub?, subHTML?, body, close, save?, saveLabel?,
                   footLeft?, foot?, width?, grid?, bodyId?, z?, cls? })
       close — data-act закрытия (затемнение, ✕, «Отмена») — ловит страница;
       save  — data-act «Сохранить»; нет save и foot — нижней строки нет;
       foot  — своя нижняя строка целиком; footLeft — кнопки слева (удалить);
       grid  — поля в две колонки (на телефоне — одна); width — ширина, px;
       z     — слой (z-index) для окон стопкой: следующее окно поверх предыдущего (1.33.0);
       cls   — классы окна (1.34.0): enter — плавно въехать; behind — окно под верхним
               (сдвинуто, чуть меньше); fresh — только что ушло назад (плавно); stacked —
               верхнее окно стопки (светлее затемнение, нижнее видно); leave/return — ставит
               страница перед закрытием верхнего окна; tall — постоянная высота 90vh (1.35.0).
       lead  — HTML слева от заголовка (стрелки листания ← →, 1.39.0);
       aside — HTML справа от заголовка, перед ✕ (счётчик «3 из 12», 1.39.0);
       top   — HTML закреплённой полосы под шапкой (плитки, подвкладки): не
               прокручивается вместе с телом (1.39.0).
   Esc закрывает страница (её обработчик), как и раньше. Прокручивается
   .ui-modal-body — его scrollTop страница возвращает после перерисовки. */
function uiModalHTML(o){
  o = o || {};
  var close = attr(o.close || "close-modal");
  var foot = o.foot != null ? o.foot
    : (o.save ? (o.footLeft || "") + '<span class="ui-modal-sp"></span>' +
        '<button type="button" class="ui-modal-cancel" data-act="' + close + '">Отмена</button>' +
        '<button type="button" class="ui-modal-save" data-act="' + attr(o.save) + '">' + esc(o.saveLabel || "Сохранить") + '</button>' : "");
  var sub = o.subHTML != null ? o.subHTML : (o.sub ? esc(o.sub) : "");
  return '<div class="ui-modal' + (o.cls ? " " + attr(o.cls) : "") + '" style="--modal-w:' + (o.width || 640) + 'px' + (o.z ? '; --modal-z:' + (+o.z) : '') + '">' +
    '<div class="ui-modal-bg" data-act="' + close + '"></div>' +
    '<div class="ui-modal-box" role="dialog" aria-modal="true" aria-label="' + attr(o.title || "") + '">' +
      '<div class="ui-modal-head">' + (o.lead ? '<div class="ui-modal-lead">' + o.lead + '</div>' : '') +
        '<div class="ui-modal-titles"><div class="ui-modal-title">' + esc(o.title || "") + '</div>' +
        (sub ? '<div class="ui-modal-sub">' + sub + '</div>' : '') +
        (o.subAlt ? '<div class="ui-modal-sub alt" aria-hidden="true">' + o.subAlt + '</div>' : '') + '</div>' +
        (o.aside ? '<div class="ui-modal-aside">' + o.aside + '</div>' : '') +
        '<button type="button" class="ui-modal-x" data-act="' + close + '" aria-label="Закрыть">✕</button></div>' +
      (o.top ? '<div class="ui-modal-top"><div class="ui-modal-topin">' + o.top + '</div></div>' : '') +
      '<div class="ui-modal-body' + (o.grid ? ' ui-modal-grid' : '') + '"' + (o.bodyId ? ' id="' + attr(o.bodyId) + '"' : '') + '>' + (o.body || "") + '</div>' +
      (foot ? '<div class="ui-modal-foot">' + foot + '</div>' : '') +
    '</div></div>';
}

/* ═══ Строка разделов, мост к DOM, появление (ui-kit 1.39.0) ════════════════
   Вьюер портфеля строит разметку через document.createElement, а компоненты
   ui-kit отдают HTML-строки: uiNode(html) — первый элемент строки узлом (был
   свой мостик только для выпадающего списка).
     uiTabsHTML(items, cur, o) — строка разделов .ui-tabs. items: [{ id, label,
       n?, alert?, more? }] — more: пункт уходит в список «Ещё ▾» в конце строки;
       o.moreLabel — подпись пункта («Ещё»); o.label — aria-label строки. Когда
       открыт раздел из «Ещё», пункт показывает его имя («Ещё: Макро ▾») и подсвечен.
     uiTabsMount(nav, onPick) — вешает обработчики на строку (один раз на узел):
       клик по разделу → onPick(id); «Ещё» открывает список поверх (position:fixed —
       прокрутка строки его не обрезает), Esc и клик мимо закрывают; активный
       раздел подводится в видимую часть строки (телефон).
     uiAnimIn(el, kind) — короткое появление только что вставленного блока:
       "next"/"prev" — сдвиг в сторону листания, "fade" — смена вкладки. Только
       transform и прозрачность — высота окна не прыгает; «уменьшить движение» —
       без анимации. */
function uiNode(html){
  var w = document.createElement("div");
  w.innerHTML = String(html == null ? "" : html).trim();
  return w.firstElementChild;
}
function uiTabsHTML(items, cur, o){
  o = o || {};
  var main = [], more = [];
  (items || []).forEach(function(t){ (t.more ? more : main).push(t); });
  var btn = function(t, inPop){
    var on = t.id === cur;
    return '<button type="button" class="ui-tab" data-ui-tab="' + attr(t.id) + '"' + (on ? ' aria-current="page"' : '') +
      (inPop ? ' role="menuitem"' : '') + '>' + esc(inPop && t.menu ? t.menu : t.label) +
      (t.n != null && t.n !== "" ? '<span class="ui-tab-n' + (t.alert ? ' alert' : '') + '">' + esc(t.n) + '</span>' : '') + '</button>';
  };
  var curMore = more.filter(function(t){ return t.id === cur; })[0];
  var lbl = o.moreLabel || "Ещё";
  return '<nav class="ui-tabs" aria-label="' + attr(o.label || "Разделы") + '">' +
    main.map(function(t){ return btn(t); }).join("") +
    (more.length ? '<button type="button" class="ui-tab more" data-ui-tabs-more aria-haspopup="menu" aria-expanded="false"' +
      (curMore ? ' aria-current="page"' : '') + '>' + esc(curMore ? lbl + ": " + curMore.label : lbl) +
      '<span class="ui-tab-chev" aria-hidden="true"></span></button>' +
      '<template data-ui-tabs-pop>' + more.map(function(t, i){
        // t.group — заголовок группы в меню (печатается перед первым пунктом группы)
        var h = t.group && (i === 0 || more[i - 1].group !== t.group) ? '<div class="ui-tabs-pop-h" role="presentation">' + esc(t.group) + '</div>' : '';
        return h + btn(t, true);
      }).join("") + '</template>' : '') +
    '</nav>';
}
function uiTabsClose(){
  var p = document.querySelector(".ui-tabs-pop");
  if (p){
    if (p.__uiOpener) p.__uiOpener.setAttribute("aria-expanded", "false");
    p.remove();
  }
}
function uiTabsMount(nav, onPick){
  if (!nav) return;
  var tabs = nav.classList.contains("ui-tabs") ? nav : nav.querySelector(".ui-tabs");
  if (!tabs) return;
  tabs.__uiPick = onPick;
  var cur = tabs.querySelector('.ui-tab[aria-current="page"]');
  if (cur && tabs.scrollWidth > tabs.clientWidth){
    var l = cur.offsetLeft, r = l + cur.offsetWidth;
    if (l < tabs.scrollLeft || r > tabs.scrollLeft + tabs.clientWidth) tabs.scrollLeft = Math.max(0, l - 24);
  }
  if (tabs.__uiMounted) return;
  tabs.__uiMounted = true;
  tabs.addEventListener("click", function(e){
    var b = e.target.closest("[data-ui-tab]");
    if (b){ uiTabsClose(); tabs.__uiPick && tabs.__uiPick(b.getAttribute("data-ui-tab")); return; }
    var m = e.target.closest("[data-ui-tabs-more]");
    if (!m) return;
    if (document.querySelector(".ui-tabs-pop")){ uiTabsClose(); return; }
    var tpl = tabs.querySelector("template[data-ui-tabs-pop]");
    if (!tpl) return;
    var pop = document.createElement("div");
    pop.className = "ui-tabs-pop";
    pop.setAttribute("role", "menu");
    pop.innerHTML = tpl.innerHTML;
    pop.__uiOpener = m;
    document.body.appendChild(pop);
    var r = m.getBoundingClientRect(), w = pop.offsetWidth;
    pop.style.top = Math.round(r.bottom + 4) + "px";
    pop.style.left = Math.round(Math.max(8, Math.min(r.right - w, window.innerWidth - w - 8))) + "px";
    m.setAttribute("aria-expanded", "true");
    pop.addEventListener("click", function(ev){
      var it = ev.target.closest("[data-ui-tab]");
      if (!it) return;
      uiTabsClose();
      tabs.__uiPick && tabs.__uiPick(it.getAttribute("data-ui-tab"));
    });
    var f = pop.querySelector('[aria-current="page"]') || pop.querySelector(".ui-tab");
    if (f) f.focus();
  });
}
if (typeof window !== "undefined"){   // ui-kit.js читают и вне браузера (тесты в node)
document.addEventListener("click", function(e){
  if (!document.querySelector(".ui-tabs-pop")) return;
  if (e.target.closest(".ui-tabs-pop") || e.target.closest("[data-ui-tabs-more]")) return;
  uiTabsClose();
}, true);
document.addEventListener("keydown", function(e){
  var p = document.querySelector(".ui-tabs-pop");
  if (!p) return;
  if (e.key === "Escape"){ e.preventDefault(); e.stopPropagation(); var o = p.__uiOpener; uiTabsClose(); if (o) o.focus(); return; }
  if (e.key === "ArrowDown" || e.key === "ArrowUp"){
    var it = [].slice.call(p.querySelectorAll(".ui-tab")), i = it.indexOf(document.activeElement);
    i = e.key === "ArrowDown" ? Math.min(it.length - 1, i + 1) : Math.max(0, i - 1);
    if (it[i]) it[i].focus();
    e.preventDefault();
  }
}, true);
window.addEventListener("resize", uiTabsClose);
window.addEventListener("scroll", function(e){ if (!(e.target && e.target.closest && e.target.closest(".ui-tabs-pop"))) uiTabsClose(); }, true);
}
function uiAnimIn(el, kind){
  if (!el || uiReduceMotion()) return;
  var c = kind === "next" ? "ui-in-next" : kind === "prev" ? "ui-in-prev" : "ui-in-fade";
  el.classList.remove("ui-in-next", "ui-in-prev", "ui-in-fade");
  void el.offsetWidth;
  el.classList.add(c);
  el.addEventListener("animationend", function h(){ el.classList.remove(c); el.removeEventListener("animationend", h); });
}

/* ═══ Окна стопкой (ui-kit 1.36.0) ══════════════════════════════════════════
   Логика стопки одна на кабинет (была в money.html — каждая страница копировала
   бы её). Состояние — у страницы (массив окон), страница рисует все окна сама;
   ui-kit даёт классы слоя, закрытие с анимацией и прокрутку слоёв. Годится и
   для одиночного окна (n = 1): плавно въезжает и плавно уходит.
     uiStackCls(i, n, fresh)    — классы слоя i из n для uiModalHTML({ cls }):
                                  fresh — индекс только что открытого окна (или null);
                                  страница сбрасывает его после перерисовки;
     uiStackPop(layers, i, done) — закрыть слои от i и выше: они уходят (.leave), окно
                                  под ними возвращается (.return), через 170 мс — done()
                                  (страница убирает окна из состояния и перерисовывает).
                                  layers — окна стопки по порядку (querySelectorAll).
                                  Повторный вызов во время анимации игнорируется;
                                  «уменьшить движение» — сразу;
     uiStackKeepScroll(prefix, n) — до перерисовки: запомнить прокрутку тел окон
                                  (bodyId = prefix + i); вернёт функцию, которую
                                  вызвать после перерисовки. */
function uiStackCls(i, n, fresh){
  return (i < n - 1 ? "behind" : "") + (i > 0 ? " stacked" : "") +
    (fresh === i ? " enter" : fresh === i + 1 ? " fresh" : "");
}
var uiStackBusy = false;
function uiStackPop(layers, i, done){
  if (uiStackBusy) return;
  var top = layers[layers.length - 1], under = i > 0 ? layers[i - 1] : null;
  if (!top || uiReduceMotion()){ done(); return; }
  uiStackBusy = true;
  for (var j = Math.max(i, 0); j < layers.length; j++)layers[j].classList.add("leave");
  if (under){ under.classList.remove("behind", "fresh"); under.classList.add("return"); }
  setTimeout(function(){ uiStackBusy = false; done(); }, 170);
}
/* Сворачивание шапки окна на телефоне (ui-kit 1.42.0; CSS — .ui-modal.fold).
   uiFoldMount(modal) — один раз на окно после вставки: меряет высоту шапки в
   --ui-fold-top (подвкладки липнут под ней; ResizeObserver — шапка меняет высоту
   при листании) и следит IntersectionObserver'ом за .ui-modal-fold: ушёл под шапку —
   окну класс .folded (строка под названием сменяется сводкой .ui-modal-sub.alt).
   uiFoldScroller(el) — кто прокручивается: окно .fold на телефоне — .ui-modal-box,
   иначе сам элемент (тело). Нужен тем, кто помнит/сбрасывает прокрутку окна. */
function uiFoldScroller(el){
  if (!el) return el;
  var m = el.closest ? el.closest(".ui-modal.fold") : null;
  if (!m) return el;
  var box = m.querySelector(".ui-modal-box");
  return box && getComputedStyle(box).overflowY !== "visible" && getComputedStyle(box).display === "block" ? box : el;
}
function uiFoldMount(m){
  if (!m || m.__uiFold) return;
  var box = m.querySelector(".ui-modal-box"), head = m.querySelector(".ui-modal-head"), fold = m.querySelector(".ui-modal-fold");
  if (!box || !head) return;
  m.__uiFold = true;
  var io = null;
  var setTop = function(){
    var h = head.offsetHeight;
    m.style.setProperty("--ui-fold-top", h + "px");
    if (!fold || typeof IntersectionObserver === "undefined") return;
    if (io) io.disconnect();
    io = new IntersectionObserver(function(es){
      var e = es[es.length - 1];
      m.classList.toggle("folded", !e.isIntersecting && e.boundingClientRect.top < e.rootBounds.top + 1);
    }, { root: box, rootMargin: "-" + h + "px 0px 0px 0px", threshold: 0 });
    io.observe(fold);
  };
  setTop();
  if (typeof ResizeObserver !== "undefined") new ResizeObserver(setTop).observe(head);
}

/* Липкая шапка у таблицы, прокручиваемой вбок (ui-kit 1.43.0). Внутри обёртки с
   overflow-x:auto шапка .ui-table.sticky липнет к обёртке, а не к странице — на телефоне
   (таблица шире экрана) шапки при прокрутке не видно. uiTableStickyHead(wrap): копия
   шапки (.ui-table-shead) стоит над таблицей вплотную, поверх настоящей шапки, липнет к
   верху страницы (--ui-sticky-top) и сдвигается вбок вместе с таблицей; ширины колонок —
   с настоящих th (ResizeObserver), клик по заголовку копии — клик по настоящему
   (сортировка). Обёртка, которой прокрутка не нужна (.flow), копию снимает: там липнет
   настоящая шапка. Звать после каждой перерисовки / смены .flow (идемпотентно). */
function uiTableStickyHead(wrap){
  if (!wrap) return;
  var table = wrap.querySelector(":scope > table.ui-table.sticky");
  var prev = wrap.previousElementSibling && wrap.previousElementSibling.classList.contains("ui-table-shead") ? wrap.previousElementSibling : null;
  if (!table || !table.tHead || wrap.classList.contains("flow")){
    if (prev) prev.remove();
    if (wrap.__uiTl && wrap.parentNode) wrap.parentNode.style.removeProperty("timeline-scope");
    return;
  }
  var box = prev || document.createElement("div");
  if (!prev){
    // Сдвиг вбок ведёт сама прокрутка таблицы (1.44.0): именованная шкала прокрутки обёртки
    // (scroll-timeline) + timeline-scope на общем родителе — копия едет на композиторе
    // вместе с таблицей. Скриптом по событию scroll (как было) на iPhone шапка отставала на
    // кадр-два при инерционной прокрутке и «дёргалась». Нет поддержки — остаётся скрипт.
    if (typeof CSS !== "undefined" && CSS.supports && CSS.supports("timeline-scope", "--a") && CSS.supports("animation-timeline", "--a")){
      wrap.__uiTl = "--ui-tbl-" + (uiTableStickyHead.n = (uiTableStickyHead.n || 0) + 1);
      wrap.style.setProperty("scroll-timeline", wrap.__uiTl + " inline");
      box.style.setProperty("--ui-shead-tl", wrap.__uiTl);
    }
    box.className = "ui-table-shead";
    box.setAttribute("aria-hidden", "true");
    wrap.parentNode.insertBefore(box, wrap);
    wrap.addEventListener("scroll", function(){ var t = box.firstChild; if (t && !wrap.__uiTl) t.style.transform = "translateX(" + (-wrap.scrollLeft) + "px)"; }, { passive: true });
    box.addEventListener("click", function(e){
      var th = e.target.closest ? e.target.closest("th") : null;
      if (!th) return;
      var i = [].indexOf.call(th.parentNode.children, th), real = wrap.querySelector(":scope > table > thead > tr");
      if (real && real.children[i]) real.children[i].click();
    });
    if (typeof ResizeObserver !== "undefined") new ResizeObserver(function(){ uiTableStickyHead(wrap); }).observe(table);
  }
  var src = table.tHead.querySelectorAll("th"), ws = [];
  for (var k = 0; k < src.length; k++) ws.push(Math.round(src[k].getBoundingClientRect().width * 10) / 10);
  var sig = ws.join(",") + "|" + (wrap.scrollWidth - wrap.clientWidth) + "|" + table.offsetWidth + "|" + table.tHead.offsetHeight + "|" + table.tHead.textContent + "|" + table.tHead.innerHTML.length;
  if (box.__sig === sig) return;   // без изменений — не трогать DOM (наблюдатели страницы не будятся впустую)
  box.__sig = sig;
  var t = document.createElement("table");
  t.className = table.className;
  t.style.width = table.offsetWidth + "px";
  t.appendChild(table.tHead.cloneNode(true));
  var dst = t.querySelectorAll("th");
  for (var i = 0; i < dst.length; i++){ var w = ws[i]; dst[i].style.width = w + "px"; dst[i].style.minWidth = w + "px"; dst[i].style.maxWidth = w + "px"; }
  if (wrap.__uiTl){
    var par = wrap.parentNode, sc = (par.style.getPropertyValue("timeline-scope") || "").split(",").map(function(x){ return x.trim(); }).filter(Boolean);
    if (sc.indexOf(wrap.__uiTl) < 0){ sc.push(wrap.__uiTl); par.style.setProperty("timeline-scope", sc.join(", ")); }
    box.style.setProperty("--ui-shead-max", Math.max(0, wrap.scrollWidth - wrap.clientWidth) + "px");
    t.classList.add("tl");
  } else t.style.transform = "translateX(" + (-wrap.scrollLeft) + "px)";
  box.style.marginBottom = (-table.tHead.offsetHeight) + "px";
  box.innerHTML = "";
  box.appendChild(t);
}

function uiStackKeepScroll(prefix, n){
  var t = [];
  for (var i = 0; i < n; i++){ var b = uiFoldScroller(document.getElementById(prefix + i)); t.push(b ? b.scrollTop : 0); }
  return function(){
    t.forEach(function(v, i){ var b = uiFoldScroller(document.getElementById(prefix + i)); if (b) b.scrollTop = v; });
  };
}

/* ═══ Появление окна (ui-kit 1.38.0) ═══════════════════════════════════════
   Окна, которые страница держит в разметке и показывает атрибутом hidden
   (окно документа .ui-docwin в travel/games, профиль travel), появлялись и
   исчезали рывком. uiShow — показать с плавным входом (.enter), uiHide —
   плавный уход (.leave, 170 мс), затем hidden и done(). Анимируются слой
   (затемнение) и его дочернее окно [role="dialog"]; стили — ui-kit.css для
   .ui-docwin, .uh-overlay и любого слоя с классом .ui-fx.
   Окно, которое страница рисует перерисовкой (health), ставит .enter сама —
   только при открытии, иначе вход повторялся бы на каждой перерисовке. */
function uiShow(el){
  if (!el) return;
  clearTimeout(el.__uiHideT);
  el.classList.remove("leave");
  el.classList.add("enter");
  el.hidden = false;
}
function uiHide(el, done){
  if (!el || el.hidden){ if (done) done(); return; }
  if (el.classList.contains("leave")) return;
  var fin = function(){ el.hidden = true; el.classList.remove("leave", "enter"); if (done) done(); };
  if (uiReduceMotion()){ fin(); return; }
  el.classList.add("leave");
  el.__uiHideT = setTimeout(fin, 170);
}

/* ═══ Боковая панель (ui-kit 1.37.0) ═══════════════════════════════════════
   Карточка, выезжающая справа (биомаркер, лекарство, исследование «Здоровья»).
   Была своя у страницы — четыре копии inline-разметки. Шапка закреплена,
   прокручивается тело; на экране уже 820px — во весь экран. Стопкой (панель
   из панели) — теми же uiStackCls/uiStackPop, что и окна: нижняя сдвинута
   влево и приглушена, верхняя въезжает справа.
     uiPaneHTML({ title, eyebrow?, lead?, aside?, body, close, back?, width?,
                  oneLine?, cls?, bodyId? })
       close — data-act закрытия (затемнение, ✕) — ловит страница;
       lead  — HTML слева от заголовка (стрелки листания); back — подпись кнопки
               «← …» туда, откуда пришли (data-act="pane-back"), вместо lead;
       aside — HTML справа от заголовка (счётчик); oneLine — заголовок в строку
               с многоточием; width — ширина, px (560). Слой 200: под окнами форм. */
function uiPaneBackHTML(label, sub){
  return '<button type="button" class="ui-pane-back" data-act="pane-back"><span class="ui-pane-back-ar">←</span>' +
    '<span class="ui-ell">' + esc(label || "") + '</span>' + (sub ? '<span class="ui-pane-back-sub">· ' + esc(sub) + '</span>' : '') + '</button>';
}
function uiPaneHTML(o){
  o = o || {};
  var close = attr(o.close || "close-pane");
  var back = o.back ? uiPaneBackHTML(o.back.label, o.back.sub) : (o.lead || "");
  return '<div class="ui-pane' + (o.cls ? " " + attr(o.cls) : "") + '" style="--pane-w:' + (o.width || 560) + 'px">' +
    '<div class="ui-pane-bg" data-act="' + close + '" title="Закрыть"></div>' +
    '<aside class="ui-pane-box" role="dialog" aria-modal="true" aria-label="' + attr(o.title || "") + '">' +
      '<div class="ui-pane-head">' + back +
        '<div class="ui-pane-titles">' + (o.eyebrow ? '<div class="ui-pane-eyebrow">' + esc(o.eyebrow) + '</div>' : '') +
          '<div class="ui-pane-title' + (o.oneLine ? ' one' : '') + '">' + esc(o.title || "") + '</div></div>' +
        (o.aside || "") +
        '<button type="button" class="ui-pane-x" data-act="' + close + '" aria-label="Закрыть">✕</button></div>' +
      '<div class="ui-pane-body"' + (o.bodyId ? ' id="' + attr(o.bodyId) + '"' : '') + '>' + (o.body || "") + '</div>' +
    '</aside></div>';
}

/* ═══ Раскрытие блока (ui-kit 1.31.0) ═══════════════════════════════════════
   Страницы кабинета перерисовываются целиком (innerHTML), поэтому CSS-переход
   высоты не сработает: блок появляется уже готовым. Анимируем после
   перерисовки через Web Animations API (есть и в Safari): высота 0 → своя,
   прозрачность 0 → 1. Сворачивание — наоборот, и только по окончании страница
   меняет состояние (done). «Уменьшить движение» в системе — без анимации.
     uiExpandIn(el, ms?)          — раскрыть только что вставленный блок;
     uiCollapseOut(el, done, ms?) — свернуть и вызвать done(). */
function uiReduceMotion(){ try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch(e){ return false; } }
function uiExpandIn(el, ms){
  if (!el || !el.animate || uiReduceMotion()) return;
  var cs = getComputedStyle(el);
  el.style.overflow = "hidden";
  var a = el.animate([{ height: "0px", paddingTop: "0px", paddingBottom: "0px", opacity: 0 },
                      { height: el.offsetHeight + "px", paddingTop: cs.paddingTop, paddingBottom: cs.paddingBottom, opacity: 1 }],
                     { duration: ms || 320, easing: "cubic-bezier(.33,1,.68,1)" });   // ease-out cubic: без рывка в начале
  a.onfinish = a.oncancel = function(){ el.style.overflow = ""; };
}
function uiCollapseOut(el, done, ms){
  if (!el || !el.animate || uiReduceMotion()){ done(); return; }
  el.style.overflow = "hidden";
  var a = el.animate([{ height: el.offsetHeight + "px", opacity: 1 },
                      { height: "0px", paddingTop: "0px", paddingBottom: "0px", opacity: 0 }],
                     { duration: ms || 220, easing: "cubic-bezier(.65,0,.35,1)", fill: "forwards" });
  a.onfinish = done;
}

/* ═══ Подтверждение (ui-kit 1.25.0) ═══════════════════════════════════════════
   Своё окно вместо нативного confirm(): тот на iOS блокирует страницу целиком
   и не показывает того единственного, ради чего подтверждение нужно, — ЧТО
   удаляется и что потянется следом («Еда», окно удаления рецепта). Было: своё
   окно у рецепта и confirm() ещё в пяти местах health/food.
     uiConfirm({ title, name?, text?, warn?, ok?, cancel?, danger? }) → Promise<bool>
       name — что именно (крупно), text — пояснение (\n — новая строка),
       warn — жёлтая плашка «что потянется следом», danger (по умолчанию
       true) — красная кнопка.
   «Отмена», Esc и клик мимо — «нет»; фокус сразу на «Отмене» (случайный Enter
   ничего не удаляет); Tab ходит между двумя кнопками. Слой — выше всего
   (1100): подтверждают и из открытой формы. */
function uiConfirm(o){
  o = o || {};
  return new Promise(function(resolve){
    var prev = document.activeElement;
    var ov = document.createElement("div");
    ov.className = "ui-confirm enter";   // 1.67.5: плавное появление, как у окон
    var br = function(t){ return esc(t).replace(/\n/g, "<br>"); };
    ov.innerHTML = '<div class="ui-confirm-box" role="alertdialog" aria-modal="true" aria-labelledby="ui-confirm-t">' +
      '<div class="ui-confirm-t' + (o.danger === false ? '' : ' danger') + '" id="ui-confirm-t">' + esc(o.title || "Удалить?") + '</div>' +
      (o.name ? '<div class="ui-confirm-n">' + esc(o.name) + '</div>' : '') +
      (o.text ? '<div class="ui-confirm-x">' + br(o.text) + '</div>' : '') +
      (o.warn ? '<div class="ui-confirm-w">' + br(o.warn) + '</div>' : '') +
      '<div class="ui-confirm-f"><button type="button" class="ui-confirm-no">' + esc(o.cancel || "Отмена") + '</button>' +
        '<button type="button" class="ui-confirm-ok' + (o.danger === false ? '' : ' danger') + '">' + esc(o.ok || "Удалить") + '</button></div>' +
    '</div>';
    document.body.appendChild(ov);
    var no = ov.querySelector(".ui-confirm-no"), yes = ov.querySelector(".ui-confirm-ok");
    function done(v){
      document.removeEventListener("keydown", key, true);
      if (ov.parentNode) ov.parentNode.removeChild(ov);
      try { if (prev && prev.focus) prev.focus({ preventScroll: true }); } catch(e){}
      resolve(v);
    }
    function key(ev){
      if (ev.key === "Escape"){ ev.preventDefault(); ev.stopImmediatePropagation(); done(false); }
      else if (ev.key === "Tab"){ ev.preventDefault(); (document.activeElement === no ? yes : no).focus(); }
    }
    document.addEventListener("keydown", key, true);
    ov.addEventListener("click", function(ev){
      ev.stopPropagation();                // клик по подтверждению не доходит до страницы
      if (ev.target === ov || ev.target.closest(".ui-confirm-no")) done(false);
      else if (ev.target.closest(".ui-confirm-ok")) done(true);
    });
    try { no.focus({ preventScroll: true }); } catch(e){ no.focus(); }
  });
}

/* ═══ Навигация раздела (ui-kit 1.23.0) ═════════════════════════════════════
   Один список пунктов на обе формы — рельс и нижняя панель; рассинхрон
   подсветки невозможен по построению (в health он был реальным багом).
     items: [{ k, label, sub?, short?, icon (svg), n? }]
     o:     { act, key }  — атрибуты кнопки для обработчика страницы:
            data-act="<act>" <key>="<k>" (health: act "tab", key "data-id";
            food: "nav"/"data-arg"; «Деньги»: "tab"/"data-v"; games: без act,
            key "data-s"). Каждая кнопка несёт и data-ui-nav="<k>".
   uiRailHTML(items, cur, o)  — разметка рельса (рисует страница; счётчики
                                 n и подписи sub живут здесь);
   uiNavMount(items, cur, o)  — нижняя панель: создаётся ОДИН раз в <body>,
                                 дальше только подсветка; пересоздаётся, лишь
                                 если сменился сам набор пунктов;
   uiNavSet(cur)              — подсветить пункт в рельсе и панели;
   uiNavHide(hidden)          — спрятать панель (загрузка/ошибка страницы).
   Ширина, высота, порог и слои — в ui-kit.css (раздел «Навигация»). */
function uiNavAttrs(o, k){
  o = o || {};
  return (o.act ? ' data-act="' + attr(o.act) + '"' : '') + ' ' + (o.key || "data-v") + '="' + attr(k) + '" data-ui-nav="' + attr(k) + '"';
}
function uiRailHTML(items, cur, o){
  o = o || {};
  return '<aside class="ui-rail"><div class="ui-rail-lbl">' + esc(o.title || "Разделы") + '</div>' + items.map(function(x){
    var on = x.k === cur;
    return '<button type="button" class="ui-rail-item' + (on ? " on" : "") + '"' + uiNavAttrs(o, x.k) + (on ? ' aria-current="page"' : '') + '>' +
      '<span class="ui-rail-ic" aria-hidden="true">' + (x.icon || "") + '</span>' +
      '<span class="ui-rail-txt"><span>' + esc(x.label) + '</span>' +
        (x.sub != null ? '<span class="ui-rail-sub">' + esc(x.sub) + '</span>' : '') + '</span>' +
      (x.n != null ? '<span class="ui-rail-n">' + esc(x.n) + '</span>' : '') + '</button>';
  }).join("") + '</aside>';
}
function uiNavMount(items, cur, o){
  o = o || {};
  var sig = items.map(function(x){ return x.k + ":" + (x.short || x.label); }).join("|") + "#" + (o.act || "") + (o.key || "");
  var nav = document.getElementById("ui-mnav");
  if (!nav || nav.getAttribute("data-sig") !== sig){
    if (!nav){
      nav = document.createElement("nav");
      nav.id = "ui-mnav"; nav.className = "ui-mnav";
      nav.setAttribute("aria-label", o.title || "Разделы");
      document.body.appendChild(nav);
    }
    nav.setAttribute("data-sig", sig);
    nav.style.setProperty("--n", items.length);
    nav.innerHTML = items.map(function(x){
      return '<button type="button" class="ui-mnav-btn"' + uiNavAttrs(o, x.k) + '>' +
        '<span class="ui-mnav-ic" aria-hidden="true">' + (x.icon || "") + '</span>' + esc(x.short || x.label) + '</button>';
    }).join("");
  }
  uiNavHide(false);
  uiNavSet(cur);
}
function uiNavSet(cur){
  var all = document.querySelectorAll("[data-ui-nav]");
  for (var i = 0; i < all.length; i++){
    var on = all[i].getAttribute("data-ui-nav") === cur;
    all[i].classList.toggle("on", on);
    if (on) all[i].setAttribute("aria-current", "page"); else all[i].removeAttribute("aria-current");
  }
}
function uiNavHide(hidden){
  var nav = document.getElementById("ui-mnav");
  if (nav) nav.hidden = !!hidden;
}

/* ═══ Подъём наверх и слой страницы (ui-kit 1.64.0) ══════════════════════════
   uiScrollTop(el?)  — «наверх» ВСЕГДА мгновенно (без плавной прокрутки и вне
                       зависимости от prefers-reduced-motion): без аргумента —
                       окно страницы, с аргументом — прокручиваемый контейнер.
                       Других scrollTo(0,0)/scrollTop=0 «наверх» на страницах нет.
   Нажатие пункта нижнего меню, рельса и вкладок (uiTabsMount), в том числе
   текущего, поднимает страницу само — ПОСЛЕ того, как страница перерисовала
   вкладку (requestAnimationFrame: кадра со старой прокруткой не бывает).
   uiLayerBind({ depth, closeTop, dirty, closeAll })  — одна регистрация на
   страницу: depth() — число открытых слоёв страницы (окна, панели, просмотрщик);
   closeTop(ev) — закрыть верхний слой (вернуть false — «ничего не закрыл»,
   тогда Escape не гасится); dirty() — у открытого слоя есть несохранённые
   правки (uiFormDirty(корень) считает по сравнению с исходными значениями
   разметки); closeAll() — необязательно: закрыть всё сразу (без него ui-kit
   зовёт closeTop, пока depth() > 0).
   • Escape: собственные окна ui-kit (справка, список, всплывающее окно вкладок,
     подсказка (i), подтверждение, поиск) обрабатывают его первыми; иначе при
     depth() > 0 ui-kit гасит событие (Mac не выходит из полноэкранного режима)
     и зовёт closeTop.
   • Пункт меню/рельса/вкладки при открытых слоях: dirty() — uiConfirm «Закрыть
     без сохранения?» («нет» — ничего не происходит); затем все слои закрываются
     и выполняется переход с подъёмом. */
function uiScrollTop(el){
  var node = (!el || el === window || el === document || el === document.documentElement || el === document.body) ? null : el;
  var tg = node ? [node] : [document.documentElement, document.body];
  var prev = tg.map(function(t){ return t.style.scrollBehavior; });
  tg.forEach(function(t){ t.style.scrollBehavior = "auto"; });
  try {
    if (node) node.scrollTop = 0;
    else window.scrollTo(0, 0);
  } finally {
    tg.forEach(function(t, i){ t.style.scrollBehavior = prev[i]; });
  }
}
function uiFormDirty(root){
  if (!root || !root.querySelectorAll) return false;
  var f = root.querySelectorAll("input, textarea, select");
  for (var i = 0; i < f.length; i++){
    var x = f[i], t = (x.type || "").toLowerCase();
    if (t === "button" || t === "submit" || t === "reset" || t === "file" || t === "search" && x.classList.contains("ui-q")) continue;
    if (t === "checkbox" || t === "radio"){ if (x.checked !== x.defaultChecked) return true; }
    else if (x.tagName === "SELECT"){
      for (var j = 0; j < x.options.length; j++) if (x.options[j].selected !== x.options[j].defaultSelected) return true;
    }
    else if (x.value !== x.defaultValue) return true;
  }
  return false;
}
var UI_LAYER = null;
function uiLayerBind(o){ UI_LAYER = o || null; }
function uiLayerDepth(){ try { return UI_LAYER && UI_LAYER.depth ? (UI_LAYER.depth() | 0) : 0; } catch(e){ return 0; } }
function uiLayerCloseAll(){
  return new Promise(function(res){
    if (!UI_LAYER) return res();
    if (UI_LAYER.closeAll){ var r; try { r = UI_LAYER.closeAll(); } catch(e){} return Promise.resolve(r).then(function(){ res(); }, function(){ res(); }); }
    var guard = 0;
    (function step(){      // закрывающие анимацию окна уходят по одному: ждём, пока depth() уменьшится
      var n = uiLayerDepth();
      if (n <= 0 || guard++ > 40) return res();
      try { UI_LAYER.closeTop(null); } catch(e){ return res(); }
      var t0 = Date.now();
      (function wait(){
        if (uiLayerDepth() < n) return step();
        if (Date.now() - t0 > 800) return res();
        setTimeout(wait, 30);
      })();
    })();
  });
}
var UI_NAV_SEL = "[data-ui-nav], .ui-tabs [data-ui-tab], .ui-tabs-pop [data-ui-tab]";
var uiNavPass = false;
function uiNavTopLater(){
  requestAnimationFrame(function(){ uiScrollTop(); requestAnimationFrame(function(){ uiScrollTop(); }); });
}
function uiNavGo(sel){
  return uiLayerCloseAll().then(function(){
    if (sel.tab){
      uiTabsClose();
      if (sel.tabs && sel.tabs.__uiPick) sel.tabs.__uiPick(sel.tab);
    } else {
      var all = document.querySelectorAll('[data-ui-nav="' + sel.nav.replace(/"/g, "") + '"]'), b = null;
      for (var i = 0; i < all.length && !b; i++) if (all[i] === sel.el) b = sel.el;
      b = b || all[0];
      if (b){ uiNavPass = true; try { b.click(); } finally { uiNavPass = false; } }
    }
    uiNavTopLater();
  });
}
if (typeof window !== "undefined"){
  document.addEventListener("click", function(ev){
    if (uiNavPass || !ev.target || !ev.target.closest) return;
    var b = ev.target.closest(UI_NAV_SEL);
    if (!b) return;
    if (uiLayerDepth() === 0){ uiNavTopLater(); return; }
    ev.preventDefault(); ev.stopPropagation(); ev.stopImmediatePropagation();
    var sel = { el: b, nav: b.getAttribute("data-ui-nav"), tab: b.getAttribute("data-ui-tab"), tabs: null };
    if (sel.tab){
      var pop = b.closest(".ui-tabs-pop");
      sel.tabs = pop ? (pop.__uiOpener && pop.__uiOpener.closest(".ui-tabs")) : b.closest(".ui-tabs");
    }
    var dirty = false;
    try { dirty = !!(UI_LAYER && UI_LAYER.dirty && UI_LAYER.dirty()); } catch(e){}
    if (!dirty){ uiNavGo(sel); return; }
    uiConfirm({ title: "Закрыть без сохранения?", text: "В открытом окне есть несохранённые изменения.", ok: "Закрыть", cancel: "Остаться", danger: false })
      .then(function(yes){ if (yes) uiNavGo(sel); });
  }, true);
}

/* Подвал раздела: «← Хаб» слева, справа источник данных и версия страницы
   (по версии видно, доехала ли выкладка). */
/* 1.70.0: uiFootHTML({page, version, src, crumb}) → «← Хаб» слева, справа «<version> · <состояние данных>»;
   src (путь к данным) — подсказкой при наведении, не текстом. crumb:false — без «← Хаб» (сам хаб).
   Состояние ведёт uiDataDone(ok) — страница зовёт его на каждый свой источник данных (ok — прочитан, false — нет);
   копия без связи (uiOfflineShow) пишет «копия от ДД.ММ, ЧЧ:ММ». Старый вызов {page, text} работает как раньше. */
function uiFootHTML(o){
  o = o || {};
  var right = o.version != null
    ? '<span class="ui-foot-meta"' + (o.src ? ' title="' + esc(o.src) + '"' : '') + '>' + esc(o.version) +
      ' · <span class="ui-foot-state" id="ui-foot-state">' + esc(uiFootStateText()) + '</span></span>'
    : '<span>' + esc(o.text || "") + '</span>';
  return '<footer class="ui-foot" style="--sec-acc:var(' + (UI_ACC[o.page] || "--accent") + ')">' +
    (o.crumb === false ? '<span></span>' : '<a class="ui-crumb" href="hub.html"><span class="ui-crumb-arw">←</span> Хаб</a>') +
    right + '</footer>';
}
var uiData = { live: 0, dead: 0, copy: null };
function uiFootStateText(){
  if (uiData.copy) return "копия от " + uiData.copy;
  if (uiData.dead === 0 && uiData.live > 0) return "данные живые";
  if (uiData.live === 0 && uiData.dead > 0) return "нет связи с данными";
  if (uiData.live + uiData.dead === 0) return "загрузка…";
  return "данные частично (" + uiData.live + "/" + (uiData.live + uiData.dead) + ")";
}
function uiFootStateRefresh(){
  var el = document.getElementById("ui-foot-state");
  if (!el) return;
  var t = uiFootStateText();
  if (el.textContent !== t) el.textContent = t;
  el.className = "ui-foot-state" + (uiData.copy || (uiData.dead && uiData.live) ? " warn" : uiData.dead ? " err" : "");
}
/* источник данных страницы прочитан (ok) или нет; reset — новая загрузка страницы целиком (⟳) */
function uiDataDone(ok){ if (ok) uiData.live++; else uiData.dead++; uiFootStateRefresh(); }
function uiDataReset(){ uiData.live = 0; uiData.dead = 0; uiData.copy = null; uiFootStateRefresh(); }
/* Кнопка темы: ведёт ui-kit (метка data-ui-theme). Доменные диспетчеры
   data-act страниц про "theme" больше не знают — им остаётся событие ui-theme. */
document.addEventListener("click", function(ev){
  var btn = ev.target.closest ? ev.target.closest('[data-act="theme"][data-ui-theme]') : null;
  if (!btn) return;
  ev.preventDefault();
  uiSetTheme(uiTheme() === "dark" ? "light" : "dark");
}, false);

/* Мини-рендер markdown — ровно то подмножество, которым пишутся справки:
   заголовки #–####, абзацы, списки («-», «*», «1.»), таблицы |…|, ``` блоки, > цитаты,
   ---, инлайн `код`, **жирный**, *курсив*, [ссылка](url), HTML-комментарии
   (вырезаются — в них SYNC-маркер). Вход сначала экранируется целиком,
   поэтому сырой HTML из файла в DOM не попадает.
   1.59.0: единственное исключение — блок <details>…</details> (теги на своих строках,
   первой строкой <summary>…</summary>, один уровень): сгиб .ui-fold.rd-fold с обычным
   markdown внутри. «## Заголовок {#id}» — заголовок с якорем. Цитата, начинающаяся с
   **Важно:** / **Внимание:** / **Совет:** / **Почему:** — выноска .ui-callout.
   Абзац, начинающийся с «{.ui-note} », — приглушённая заметка (.ui-note). */
function uiMarkdown(md){
  // Вставки (код, ссылки) прячутся в \u0000N\u0000 до разметки жирного/курсива:
  // иначе «*» внутри URL или кода превращался бы в <em>.
  function inline(t){
    var keep = [];
    function stash(h){ keep.push(h); return "\u0000" + (keep.length - 1) + "\u0000"; }
    function em(x){
      return x.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
              .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
    }
    t = t.replace(/`([^`]+)`/g, function(_, c){ return stash("<code>" + c + "</code>"); });
    // 1.49.0: [фраза](#copy) — плашка «что сказать Claude»: нажатие копирует фразу
    t = t.replace(/\[([^\]]+)\]\(#copy\)/g, function(_, txt){
      return stash('<button type="button" class="ui-say" data-ui-copy title="Нажми — скопировать">' + txt + '</button>');
    });
    t = t.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, function(_, txt, url){
      var safe = /^(https?:|\.{0,2}\/|#|[\w-]+\.html)/.test(url) ? url : "#";
      var ext = /^https?:/.test(safe) ? ' target="_blank" rel="noopener"' : "";
      return stash('<a href="' + safe + '"' + ext + '>' + em(txt) + '</a>');
    });
    // Голый адрес — ссылкой (отчёты и подборки пишут источники без [текст](…)).
    // Хвостовая пунктуация предложения в адрес не входит.
    t = t.replace(/(^|[\s(«])(https?:\/\/[^\s<)»]+)/g, function(_, pre, url){
      var tail = /[.,;:!?]+$/.exec(url); tail = tail ? tail[0] : "";
      if (tail) url = url.slice(0, -tail.length);
      return pre + stash('<a href="' + url + '" target="_blank" rel="noopener">' + url + '</a>') + tail;
    });
    t = em(t);
    while (/\u0000\d+\u0000/.test(t)) t = t.replace(/\u0000(\d+)\u0000/g, function(_, i){ return keep[+i]; });
    return t;
  }
  // «\|» — литеральная черта внутри ячейки (GFM): до разбиения прячем её в
  // \u0001, после — возвращаем. Иначе «\|r\| ≤ 0,23» рвал строку на лишние
  // столбцы (отчёт health 2026-09-29).
  function cells(row){
    return row.trim().replace(/\\\|/g, "\u0001").replace(/^\|/, "").replace(/\|$/, "").split("|")
      .map(function(c){ return inline(c.trim()).replace(/\u0001/g, "|"); });
  }
  // «- [ ]» / «- [x]» — пункт чек-листа (так пишут планы и отчёты).
  function task(h){
    return h.replace(/^\[ \]\s+/, '<input type="checkbox" disabled> ')
            .replace(/^\[[xX]\]\s+/, '<input type="checkbox" checked disabled> ');
  }
  var LI = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
  // Список с вложенностью по отступу. Смена «-» ↔ «1.» на одном уровне — новый
  // список; строка с отступом ≥2 без маркера — продолжение пункта.
  function listBlock(){
    var items = [];
    while (i < src.length){
      var m = LI.exec(src[i]);
      if (m){ items.push({ ind: m[1].replace(/\t/g, "    ").length, ord: /\d/.test(m[2]), text: m[3] }); i++; continue; }
      if (items.length && /^\s{2,}\S/.test(src[i])){ items[items.length - 1].text += " " + src[i].trim(); i++; continue; }
      break;
    }
    var k = 0;
    function level(ind){
      var ord = items[k].ord, tag = ord ? "ol" : "ul", h = "<" + tag + ">";
      while (k < items.length && items[k].ind >= ind){
        if (items[k].ind > ind){ h = h.replace(/<\/li>$/, "") + level(items[k].ind) + "</li>"; continue; }
        if (items[k].ord !== ord) break;
        h += "<li>" + task(inline(items[k].text)) + "</li>"; k++;
      }
      return h + "</" + tag + ">";
    }
    var html = "";
    while (k < items.length) html += level(items[k].ind);
    return html;
  }
  // 1.59.0: блоки <details> вынимаются до экранирования, тело разбирается этим же разборщиком
  var folds = [], raw = String(md || "").replace(/<!--[\s\S]*?-->/g, "").split(/\r?\n/), kept = [], fence = false;
  for (var r = 0; r < raw.length; r++){
    var rl = raw[r];
    if (/^```/.test(rl)) fence = !fence;
    if (!fence && /^\s*<details>\s*$/.test(rl)){
      var re = r + 1;
      while (re < raw.length && !/^\s*<\/details>\s*$/.test(raw[re])) re++;
      if (re < raw.length){
        var fb = raw.slice(r + 1, re), fs = 0;
        while (fs < fb.length && !fb[fs].trim()) fs++;
        var sm = fs < fb.length ? /^\s*<summary>(.*?)<\/summary>\s*$/.exec(fb[fs]) : null;
        folds.push({ s: sm ? sm[1] : "Подробнее", b: fb.slice(sm ? fs + 1 : 0) });
        kept.push("\u0002" + (folds.length - 1) + "\u0002");
        r = re; continue;
      }
    }
    kept.push(rl);
  }
  var src = esc(kept.join("\n")).split(/\r?\n/);
  var out = [], i = 0, para = [];
  function flush(){
    if (!para.length) return;
    var pt = para.join(" "), nt = /^\{\.ui-note\}\s+/.exec(pt);
    out.push(nt ? '<p class="ui-note">' + inline(pt.slice(nt[0].length)) + "</p>" : "<p>" + inline(pt) + "</p>");
    para = [];
  }
  while (i < src.length){
    var ln = src[i];
    if (/^```/.test(ln)){
      flush(); var buf = []; i++;
      while (i < src.length && !/^```/.test(src[i])){ buf.push(src[i]); i++; }
      out.push("<pre><code>" + buf.join("\n") + "</code></pre>"); i++; continue;
    }
    var fm = /^\u0002(\d+)\u0002$/.exec(ln.trim());
    if (fm){
      flush(); var fd = folds[+fm[1]];
      out.push('<details class="ui-fold rd-fold"><summary>' + inline(esc(fd.s)) + '<span class="ui-chev">▾</span></summary><div class="rd-fold-body">' +
        uiMarkdown(fd.b.join("\n")) + '</div></details>');
      i++; continue;
    }
    var h = /^(#{1,5})\s+(.*?)\s*#*\s*$/.exec(ln);
    if (h){
      flush(); var lv = Math.max(2, h[1].length), ht = h[2], hid = "";
      var im = /\s*\{#([a-z0-9-]+)\}\s*$/.exec(ht);
      if (im){ hid = ' id="' + im[1] + '"'; ht = ht.slice(0, im.index); }
      out.push("<h" + lv + hid + ">" + inline(ht) + "</h" + lv + ">"); i++; continue;
    }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(ln)){ flush(); out.push("<hr>"); i++; continue; }
    if (/^\s*\|/.test(ln) && i + 1 < src.length && /^\s*\|?\s*:?-{2,}/.test(src[i + 1])){
      flush();
      var th = cells(ln), rows = []; i += 2;
      while (i < src.length && /^\s*\|/.test(src[i])){ rows.push(cells(src[i])); i++; }
      out.push('<div class="uh-tbl"><table><thead><tr>' + th.map(function(c){ return "<th>" + c + "</th>"; }).join("") +
        "</tr></thead><tbody>" + rows.map(function(r){ return "<tr>" + r.map(function(c){ return "<td>" + c + "</td>"; }).join("") + "</tr>"; }).join("") +
        "</tbody></table></div>");
      continue;
    }
    if (/^&gt;\s?/.test(ln)){
      flush(); var q = [];
      while (i < src.length && /^&gt;\s?/.test(src[i])){ q.push(src[i].replace(/^&gt;\s?/, "")); i++; }
      var co = /^\*\*(Важно|Внимание|Совет|Почему):?\*\*:?\s*/.exec(q[0]);
      if (co){
        q[0] = q[0].slice(co[0].length);
        var cp = uiMarkdown.__para(q, inline).replace(/^<p>/, "<p><b>" + co[1] + ":</b> ");
        if (cp.indexOf("<b>") !== 0 && cp.indexOf("<p><b>") !== 0) cp = "<p><b>" + co[1] + ":</b></p>" + cp;
        out.push('<div class="ui-callout ' + (co[1] === "Важно" || co[1] === "Внимание" ? "warn" : "info") + '">' + cp + "</div>"); continue;
      }
      out.push("<blockquote>" + uiMarkdown.__para(q, inline) + "</blockquote>"); continue;
    }
    if (LI.test(ln)){ flush(); out.push(listBlock()); continue; }
    if (!ln.trim()){ flush(); i++; continue; }
    para.push(ln.trim()); i++;
  }
  flush();
  return out.join("\n");
}
// Абзацы внутри цитаты: пустая строка рвёт абзац, как и снаружи.
uiMarkdown.__para = function(lines, inline){
  return lines.join("\n").split(/\n\s*\n/).map(function(p){
    return p.trim() ? "<p>" + inline(p.replace(/\n/g, " ")) + "</p>" : "";
  }).join("");
};

/* ── uiReader: режим чтения длинного markdown (ui-kit 1.7.0) ─────────────────
   Порт режима чтения вьюера портфеля (viewer.js · renderReportDoc): оглавление
   из ##/### самого документа — липким столбцом, когда окну хватает ширины, и
   липкой полосой снизу со шторкой глав, текущей главой и прогрессом, когда не
   хватает (телефон, узкая панель). Порог считается по ширине ОКНА ЧИТАТЕЛЯ,
   а не экрана (CSS container queries): панель игр 840px и модалка здоровья
   1000px на одном и том же мониторе ведут себя по-разному.

   Две половины, потому что страницы рисуют по-разному: health собирает всё
   строкой и пишет innerHTML на каждое действие, games/справка — DOM-ом.
     uiReaderHTML(md, opts) → строка разметки;
     uiReaderMount(root, opts) → слушатели (прокрутка, клики), идемпотентно.
   opts:
     toc        "auto" (по умолчанию: оглавление при ≥3 главах) | true | false
     acc        имя токена акцента раздела, например "--c-5"
     head       HTML над документом (шапка страницы: флаги, провенанс)
     frontmatter "card" — плоские поля «ключ: значение» карточкой;
                 false — срезать молча (по умолчанию "card")
     dropH1     срезать первую строку «# …» (заголовок уже в шапке окна), true
     actions    [{label, find(текст главы)}] — кнопки прыжка к главе (1.8.0)
     search      true — поле поиска над оглавлением (1.58.0): подсветка <mark class="rd-hit">,
                 «N из M», Enter/↓/↑ — к следующему/предыдущему, Esc — очистить; справки — да, отчёты — нет
     sections   true (1.59.0) — режим «по разделам»: документ делится по ##, на экране один
                раздел, оглавление = переключатель разделов (под активным — его ###); текст до
                первого ## короче ~6 строк показывается над любым разделом, длиннее — пункт «О справке»;
                поиск идёт по всему документу, у разделов с совпадениями — «·N». По умолчанию false
     key        ключ документа: позиция прокрутки переживает перерисовку и
                 повторное открытие в этой вкладке
   Mount: opts.scroller — прокручиваемый контейнер (по умолчанию ближайший
   предок с overflow:auto), opts.head — липкая шапка внутри него (для отступа
   при прыжке к главе), opts.at — id («{#id}») или текст заголовка ##/###, куда открыть. */
var UI_READER_TOC_MIN = 3;
// Оглавление в справках страниц: "auto" — как у всех документов (решение
// 2026-10-03: пока для проверки показываем); false — выключить только у справок.
var UI_HELP_TOC = "auto";
var UI_READER_POS = {};

function uiReaderFrontmatter(md){
  var m = /^﻿?---\r?\n([\s\S]*?)\r?\n---[^\n]*\n?/.exec(md);
  if (!m) return { meta: null, body: md };
  var meta = [];
  m[1].split(/\r?\n/).forEach(function(ln){
    var kv = /^([A-Za-z_][\w-]*):\s*(.*)$/.exec(ln);
    if (!kv || !kv[2].trim() || /^[|>[{]/.test(kv[2].trim())) return;   // вложенное и списки — не в карточку
    meta.push([kv[1], kv[2].trim().replace(/^["']|["']$/g, "")]);
  });
  return { meta: meta, body: md.slice(m[0].length) };
}

function uiReaderHTML(md, opts){
  opts = opts || {};
  var src = String(md || "").replace(/\r\n/g, "\n");
  var fm = uiReaderFrontmatter(src);
  src = fm.body;
  // Служебные комментарии (SYNC-маркеры справок) стоят ДО заголовка — без
  // этого первый «# …» не считался бы первым и попадал в оглавление.
  src = src.replace(/<!--[\s\S]*?-->/g, "");
  if (opts.dropH1 !== false) src = src.replace(/^\s*#\s+[^\n]*\n?/, "");
  var box = document.createElement("div");
  box.innerHTML = uiMarkdown(src);

  // `---` прямо перед главой — две линии подряд: линейка главы сильнее.
  Array.prototype.forEach.call(box.querySelectorAll("hr"), function(hr){
    var n = hr.nextElementSibling;
    if (n && n.tagName === "H2") hr.remove();
  });
  // Разряды числа отделены обычным пробелом — законная точка переноса, и на
  // телефоне «1 272 105» вставало тремя строками. Числовые ячейки не переносим:
  // ширину набирает прокрутка таблицы.
  var NUM = /^[+\-−–±≈~]?\d[\d\s .,]*(\s*(%|пп|п\.п\.|₽|\$|€|¥|x|×|г|кг|мл|л|ч|мин))?$/i;
  Array.prototype.forEach.call(box.querySelectorAll("td"), function(td){
    var t = (td.textContent || "").trim();
    if (t && NUM.test(t)) td.classList.add("rd-num");
  });
  // TL;DR — отдельной панелью; врезной лид «**2.4. Название.** текст» — как
  // подзаголовок абзаца (правило узкое: номер + точка, иначе любой абзац с
  // жирным началом стал бы подзаголовком).
  var tldr = false;
  Array.prototype.forEach.call(box.querySelectorAll("p"), function(p){
    var t = (p.textContent || "").trim();
    if (!tldr && /^TL;?\s?DR\b/i.test(t)){ p.classList.add("rd-tldr"); tldr = true; return; }
    var st = p.firstElementChild;
    if (st && st.tagName === "STRONG" && p.firstChild === st && p.childNodes.length > 1 &&
        (st.textContent || "").trim().length <= 120 && /^\d+(\.\d+)*\.\s+\S/.test((st.textContent || "").trim()))
      p.classList.add("rd-lead");
  });

  var pref = "rd" + (++uiReaderHTML.__n) + "-";
  var heads = [];
  Array.prototype.forEach.call(box.querySelectorAll("h2, h3"), function(h, i){
    if (h.closest("details")) return;   // заголовки внутри сгиба в оглавление не идут
    var label = (h.textContent || "").trim();
    if (!label) return;
    if (!h.id) h.id = pref + i;         // {#id} из markdown сохраняется
    h.setAttribute("data-rd-h", "");
    heads.push({ id: h.id, lvl: h.tagName === "H2" ? 2 : 3, label: label });
  });
  // 1.59.0: режим «по разделам» — верхнеуровневые элементы раскладываются по <section class="rd-sec">
  var secOfId = {}, secMode = false, preTop = "", secHTML = "";
  if (opts.sections){
    var kids = Array.prototype.slice.call(box.children), pre = [], secList = [], curS = null;
    kids.forEach(function(el){
      if (el.tagName === "H2" && el.hasAttribute("data-rd-h")){ curS = [el]; secList.push(curS); }
      else if (curS) curS.push(el); else pre.push(el);
    });
    if (secList.length){
      secMode = true;
      var preChars = 0, preLines = 0;
      pre.forEach(function(el){ var n = (el.textContent || "").trim().length; preChars += n; preLines += n ? Math.max(1, Math.ceil(n / 80)) : 0; });
      var k0 = 0, markSec = function(els, k){
        els.forEach(function(el){
          var hs = el.hasAttribute && el.hasAttribute("data-rd-h") ? [el] : [];
          hs = hs.concat(Array.prototype.slice.call(el.querySelectorAll ? el.querySelectorAll("[data-rd-h]") : []));
          hs.forEach(function(h){ secOfId[h.id] = k; });
        });
      };
      var wrapEls = function(els){ return els.map(function(el){ return el.outerHTML; }).join("\n"); };
      if (preChars > 0 && preLines > 6){
        var iid = pref + "intro";
        heads.unshift({ id: iid, lvl: 2, label: "О справке" });
        secOfId[iid] = 0; markSec(pre, 0);
        secHTML += '<section class="rd-sec is-on" data-rd-sec="0" id="' + iid + '">' + wrapEls(pre) + '</section>';
        k0 = 1;
      } else {
        markSec(pre, -1);
        if (preChars > 0) preTop = '<div class="rd-pre">' + wrapEls(pre) + '</div>';
      }
      secList.forEach(function(els, j){
        var k = k0 + j;
        markSec(els, k);
        secHTML += '<section class="rd-sec' + (k === 0 ? " is-on" : "") + '" data-rd-sec="' + k + '">' + wrapEls(els) + '</section>';
      });
    }
  }
  // Действия раздела (ui-kit 1.8.0): [{label, find(текст главы) → bool}] —
  // кнопка прыжка к первой подходящей главе в столбце оглавления и в полосе
  // (travel: «Сегодня» к дню с сегодняшней датой). Не нашлось главы — нет кнопки.
  var acts = (opts.actions || []).map(function(a){
    for (var j = 0; j < heads.length; j++) if (a && a.find && a.find(heads[j].label)) return { label: a.label, id: heads[j].id };
    return null;
  }).filter(Boolean);
  var mode = opts.toc == null ? "auto" : opts.toc;
  var withToc = mode === true ? heads.length > 0 : mode === "auto" ? (heads.length >= UI_READER_TOC_MIN || (secMode && heads.length > 0)) : false;

  var list = function(){
    return '<ol class="rd-toc-list">' + heads.map(function(h){
      var sk = secMode ? secOfId[h.id] : null;
      var open = secMode && h.lvl === 3 && (sk === 0 || sk < 0);
      return '<li class="lvl-' + h.lvl + (open ? " is-open" : "") + '"' + (secMode ? ' data-rd-sec="' + sk + '"' : "") +
        '><a href="#' + h.id + '" data-rd-go="' + h.id + '"' + (secMode && h.lvl === 2 && sk === 0 ? ' class="is-sec"' : "") + '>' + esc(h.label) + '</a></li>';
    }).join("") + '</ol>';
  };
  var card = "";
  if (fm.meta && fm.meta.length && opts.frontmatter !== false){
    card = '<div class="rd-meta">' + fm.meta.map(function(kv){
      return '<span class="rd-mrow"><span class="rd-mk">' + esc(kv[0].replace(/_/g, " ")) + '</span><span class="rd-mv">' + esc(kv[1]) + '</span></span>';
    }).join("") + '</div>';
  }
  // 1.58.0: опция search — поле «Поиск» над оглавлением (столбец) и над текстом (узкое окно: оглавления-столбца нет)
  var qbox = function(cls){
    return '<div class="ui-qbox rd-q ' + cls + '"><span class="rd-q-in"><input class="ui-q" type="search" data-rd-q placeholder="Поиск по справке" aria-label="Поиск по справке" autocomplete="off" spellcheck="false" enterkeyhint="next">' +
      '<span class="rd-q-n" data-rd-qn aria-live="polite"></span></span>' +
      '<button type="button" class="rd-q-b" data-rd-qprev aria-label="Предыдущее совпадение" disabled>‹</button>' +
      '<button type="button" class="rd-q-b" data-rd-qnext aria-label="Следующее совпадение" disabled>›</button></div>';
  };
  var style = opts.acc ? ' style="--rd-acc:var(' + esc(opts.acc) + ');"' : "";
  var key = opts.key != null ? ' data-rd-key="' + esc(String(opts.key)) + '"' : "";
  return '<div class="rd' + (withToc ? " rd-has-toc" : "") + (secMode ? " rd-sections" : "") + '"' + style + key + '><div class="rd-grid">' +
    (withToc ? '<nav class="rd-toc" aria-label="Содержание">' + (opts.search ? qbox("rd-q-toc") : "") +
      acts.map(function(a){ return '<button type="button" class="rd-act" data-rd-go="' + a.id + '">' + esc(a.label) + '</button>'; }).join("") +
      '<div class="rd-toc-h">Содержание</div>' + list() +
      '<button type="button" class="rd-top" data-rd-top>↑ В начало</button></nav>' : "") +
    '<div class="rd-main">' + (opts.head || "") + (opts.search ? qbox("rd-q-main") : "") + card + '<article class="rd-doc">' + (secMode ? preTop + secHTML : box.innerHTML) + '</article></div>' +
    (withToc ? '<div class="rd-bar"><div class="rd-prog"><i></i></div>' +
      '<div class="rd-sheet" hidden>' + list() + '</div>' +
      '<button type="button" class="rd-bar-btn rd-open" data-rd-sheet aria-expanded="false">☰ <span class="rd-cur">Содержание</span></button>' +
      acts.map(function(a){ return '<button type="button" class="rd-bar-btn rd-act-btn" data-rd-go="' + a.id + '">' + esc(a.label) + '</button>'; }).join("") +
      '<button type="button" class="rd-bar-btn rd-up" data-rd-top aria-label="В начало">↑</button></div>' : "") +
    '</div></div>';
}
uiReaderHTML.__n = 0;

function uiReaderScrollParent(el){
  for (var p = el.parentElement; p && p !== document.body; p = p.parentElement){
    var oy = getComputedStyle(p).overflowY;
    if (oy === "auto" || oy === "scroll") return p;
  }
  return null;   // прокручивается окно
}

function uiReaderMount(root, opts){
  if (root && !(root.classList && root.classList.contains("rd"))) root = root.querySelector && root.querySelector(".rd");
  if (!root || root.__rdOn) return null;
  root.__rdOn = true;
  opts = opts || {};
  var sc = opts.scroller || uiReaderScrollParent(root);
  var win = !sc;
  var target = win ? window : sc;
  var head = opts.head || null;
  var key = root.getAttribute("data-rd-key");
  function headH(){
    if (!head) return 0;
    var p = getComputedStyle(head).position;
    return (p === "sticky" || p === "fixed") ? head.offsetHeight : 0;
  }
  function top(){ return win ? (window.scrollY || 0) : sc.scrollTop; }
  function scrollTo(y){ (win ? window : sc).scrollTo({ top: Math.max(0, y), behavior: "smooth" }); }
  var heads = Array.prototype.slice.call(root.querySelectorAll("[data-rd-h]"));
  var sheet = root.querySelector(".rd-sheet"), openBtn = root.querySelector("[data-rd-sheet]");
  var cur = root.querySelector(".rd-cur"), fill = root.querySelector(".rd-prog i");
  var links = Array.prototype.slice.call(root.querySelectorAll("[data-rd-go]"));
  function toggle(open){
    if (!sheet) return;
    if (open) sheet.removeAttribute("hidden"); else sheet.setAttribute("hidden", "");
    if (openBtn) openBtn.setAttribute("aria-expanded", open ? "true" : "false");
  }
  // 1.59.0: режим «по разделам» — показ/скрытие секций классом, без перерисовки markdown
  var secs = Array.prototype.slice.call(root.querySelectorAll(".rd-sec"));
  var secOn = secs.length > 0 && root.classList.contains("rd-sections");
  var active = null;
  function setSec(k){
    if (!secOn) return;
    secs.forEach(function(s){ s.classList.toggle("is-on", +s.getAttribute("data-rd-sec") === k); });
    Array.prototype.forEach.call(root.querySelectorAll(".rd-toc-list li.lvl-3"), function(li){
      var s = +li.getAttribute("data-rd-sec"); li.classList.toggle("is-open", s === k || s < 0);
    });
    var title = "";
    Array.prototype.forEach.call(root.querySelectorAll(".rd-toc-list li.lvl-2"), function(li){
      var on = +li.getAttribute("data-rd-sec") === k;
      li.firstChild.classList.toggle("is-sec", on);
      if (on && !title) title = (li.firstChild.firstChild ? li.firstChild.firstChild.nodeValue : li.firstChild.textContent) || "";
    });
    if (cur && title) cur.textContent = title.trim();
    links.forEach(function(a){ a.classList.remove("is-active"); });
    active = null;
    if (typeof onScroll === "function") onScroll();
  }
  function secOf(n){ var s = n && n.closest ? n.closest(".rd-sec") : null; return s ? +s.getAttribute("data-rd-sec") : null; }
  function reveal(n){
    var k = secOf(n);
    if (secOn && k != null && !secs[k].classList.contains("is-on")) setSec(k);
  }
  function toStart(smooth){
    var base = win ? 0 : sc.getBoundingClientRect().top;
    (win ? window : sc).scrollTo({ top: Math.max(0, root.getBoundingClientRect().top - base + top() - headH() - 4), behavior: smooth ? "smooth" : "auto" });
  }
  function jump(id, instant){
    var n = root.querySelector("#" + (window.CSS && CSS.escape ? CSS.escape(id) : id));
    if (!n) return;
    reveal(n);
    if (secOn && (n.classList.contains("rd-sec") || (n.tagName === "H2" && n === n.parentNode.firstElementChild))){ toStart(!instant); return; }
    var base = win ? 0 : sc.getBoundingClientRect().top;
    (win ? window : sc).scrollTo({ top: Math.max(0, n.getBoundingClientRect().top - base + top() - headH() - 10), behavior: instant ? "auto" : "smooth" });
  }
  root.addEventListener("click", function(ev){
    var t = ev.target.closest ? ev.target : null;
    if (!t) return;
    var go = t.closest("[data-rd-go]");
    if (go){ ev.preventDefault(); toggle(false); jump(go.getAttribute("data-rd-go")); return; }
    // [текст](#id) внутри документа — переход к заголовку читателя; адрес страницы не меняется
    var lk = t.closest("a[href^='#']");
    if (lk && lk.closest(".rd-doc")){
      var lid = lk.getAttribute("href").slice(1);
      if (lid && lid !== "copy"){ ev.preventDefault(); toggle(false); jump(lid); return; }
    }
    if (t.closest("[data-rd-top]")){ toggle(false); if (secOn) toStart(true); else uiScrollTop(win ? null : sc); return; }
    if (t.closest("[data-rd-sheet]")){ toggle(sheet && sheet.hasAttribute("hidden")); }
  });
  // 1.58.0: поиск по тексту читателя — подсветка <mark class="rd-hit"> по текстовым узлам (разметка не пересобирается)
  var qIn = Array.prototype.slice.call(root.querySelectorAll("[data-rd-q]"));
  if (qIn.length){
    var doc = root.querySelector(".rd-doc"), hits = [], curHit = -1, dockQ = null;
    var fold = function(t){ return String(t).toLowerCase().replace(/ё/g, "е"); };   // длина строки не меняется
    var clearHits = function(){
      Array.prototype.forEach.call(doc.querySelectorAll("mark.rd-hit"), function(m){
        var par = m.parentNode;
        while (m.firstChild) par.insertBefore(m.firstChild, m);
        par.removeChild(m);
        par.normalize();
      });
      hits = []; curHit = -1;
      Array.prototype.forEach.call(root.querySelectorAll(".rd-sec-n"), function(n){ n.parentNode.removeChild(n); });
    };
    // 1.59.0: у разделов с совпадениями в оглавлении — «·N» (где ещё искать)
    var paintCounts = function(){
      if (!secOn) return;
      var per = {};
      hits.forEach(function(m){ var k = secOf(m); if (k != null) per[k] = (per[k] || 0) + 1; });
      Array.prototype.forEach.call(root.querySelectorAll(".rd-toc-list li.lvl-2"), function(li){
        var n = per[li.getAttribute("data-rd-sec")];
        if (!n) return;
        var sp = document.createElement("span");
        sp.className = "rd-sec-n ui-muted"; sp.textContent = " ·" + n;
        li.firstChild.appendChild(sp);
      });
    };
    var qAll = function(sel){
      var l = Array.prototype.slice.call(root.querySelectorAll(sel));
      return dockQ ? l.concat(Array.prototype.slice.call(dockQ.querySelectorAll(sel))) : l;
    };
    var setCount = function(txt){
      qAll("[data-rd-qn]").forEach(function(n){ n.textContent = txt; });
      qAll("[data-rd-qprev], [data-rd-qnext]").forEach(function(b){ b.disabled = !hits.length; });
    };
    var goHit = function(i, smooth){
      if (!hits.length) return;
      if (curHit >= 0 && hits[curHit]) hits[curHit].classList.remove("is-cur");
      curHit = (i + hits.length) % hits.length;
      var m = hits[curHit];
      m.classList.add("is-cur");
      for (var d = m.closest("details"); d; d = d.parentElement && d.parentElement.closest("details")) d.open = true;   // совпадение в свёрнутом блоке
      reveal(m);   // 1.59.0: совпадение в другом разделе — переключить раздел
      var base = win ? 0 : sc.getBoundingClientRect().top;
      var y = m.getBoundingClientRect().top - base + top();
      var h = win ? window.innerHeight : sc.clientHeight;
      (win ? window : sc).scrollTo({ top: Math.max(0, y - headH() - Math.min(140, h / 4)), behavior: smooth ? "smooth" : "auto" });
      setCount((curHit + 1) + " из " + hits.length);
    };
    var run = function(q){
      clearHits();
      q = String(q || "").trim();
      if (q.length < 2){ setCount(""); return; }
      var needle = fold(q), L = needle.length;
      var walker = document.createTreeWalker(doc, 4 /* SHOW_TEXT */, {
        acceptNode: function(n){ return n.parentElement && n.parentElement.closest("script, style") ? 2 /* REJECT */ : 1 /* ACCEPT */; } });
      var nodes = [];
      while (walker.nextNode()) nodes.push(walker.currentNode);
      nodes.forEach(function(n){
        var t = n.nodeValue, f = fold(t), at = f.indexOf(needle);
        if (at < 0) return;
        var frag = document.createDocumentFragment(), last = 0;
        while (at >= 0){
          frag.appendChild(document.createTextNode(t.slice(last, at)));
          var m = document.createElement("mark");
          m.className = "rd-hit"; m.textContent = t.slice(at, at + L);
          frag.appendChild(m); hits.push(m);
          last = at + L; at = f.indexOf(needle, last);
        }
        frag.appendChild(document.createTextNode(t.slice(last)));
        n.parentNode.replaceChild(frag, n);
      });
      if (!hits.length){ setCount("нет совпадений"); return; }
      paintCounts();
      goHit(0, false);
    };
    var syncVal = function(src){ qIn.forEach(function(i){ if (i !== src) i.value = src.value; }); };
    qIn.forEach(function(inp){
      inp.addEventListener("input", function(){ syncVal(inp); run(inp.value); });
      inp.addEventListener("keydown", function(ev){
        if (ev.isComposing) return;
        if (ev.key === "Enter" || ev.key === "ArrowDown"){ ev.preventDefault(); ev.stopPropagation(); goHit(curHit + (ev.shiftKey && ev.key === "Enter" ? -1 : 1), true); }
        else if (ev.key === "ArrowUp"){ ev.preventDefault(); goHit(curHit - 1, true); }
        else if (ev.key === "Escape"){
          if (inp.value || hits.length){ ev.preventDefault(); ev.stopPropagation(); ev.stopImmediatePropagation(); qIn.forEach(function(i){ i.value = ""; }); run(""); }
        }
      }, true);
    });
    // 1.60.0: кнопки ‹ › — предыдущее/следующее совпадение (то же, что ↑/↓/Enter); фокус остаётся в поле — клавиатура на телефоне не прячется
    var qNav = function(ev){
      var b = ev.target.closest && ev.target.closest("[data-rd-qprev], [data-rd-qnext]");
      if (!b || b.disabled) return;
      ev.preventDefault();
      var inp = b.closest(".rd-q").querySelector("[data-rd-q]");
      var had = inp && document.activeElement === inp;
      goHit(curHit + (b.hasAttribute("data-rd-qnext") ? 1 : -1), true);
      if (had) try { inp.focus({ preventScroll: true }); } catch(e){}
    };
    var qEls = qIn.map(function(i){ return i.closest(".rd-q"); });
    qEls.forEach(function(q){
      q.addEventListener("mousedown", function(ev){ if (ev.target.closest("[data-rd-qprev], [data-rd-qnext]")) ev.preventDefault(); });
      q.addEventListener("click", qNav);
    });
    // 1.60.0: на узком окне поле поиска — отдельной строкой под шапкой окна, вне прокручиваемого тела
    // (если родитель прокрутки — колонка flex: окна ui-kit); иначе остаётся липким в тексте
    var qMain = root.querySelector(".rd-q-main"), qMark = null;
    if (qMain && sc && sc.parentElement){
      var mq = window.matchMedia ? window.matchMedia("(max-width:720px)") : null;
      var place = function(){
        var par = sc.parentElement;
        if (!par) return;
        var cs = getComputedStyle(par);
        var want = !!(mq && mq.matches) && cs.display === "flex" && cs.flexDirection === "column";
        if (want && !dockQ){
          Array.prototype.forEach.call(par.querySelectorAll(":scope > .rd-q-dock"), function(o){ if (o !== qMain) par.removeChild(o); });
          qMark = document.createComment("rd-q");
          qMain.parentNode.insertBefore(qMark, qMain);
          qMain.classList.add("rd-q-dock");
          par.insertBefore(qMain, sc);
          dockQ = qMain;
        } else if (!want && dockQ){
          qMain.classList.remove("rd-q-dock");
          if (qMark && qMark.parentNode){ qMark.parentNode.insertBefore(qMain, qMark); qMark.parentNode.removeChild(qMark); }
          dockQ = null;
        }
      };
      place();
      window.addEventListener("resize", place, { passive: true });
      root.__rdUndock = function(){ window.removeEventListener("resize", place); if (dockQ){ if (dockQ.parentNode) dockQ.parentNode.removeChild(dockQ); dockQ = null; } };
    }
  }
  var raf = 0;
  function sync(){
    raf = 0;
    if (!root.isConnected){ detach(); return; }
    if (key && !secOn) UI_READER_POS[key] = top();
    var vh = secOn ? heads.filter(function(h){ var s = h.closest(".rd-sec"); return !s || s.classList.contains("is-on"); }) : heads;
    if (!vh.length) return;
    var base = (win ? 0 : sc.getBoundingClientRect().top) + headH() + 24;
    var id = vh[0].id;
    for (var i = 0; i < vh.length; i++){ if (vh[i].getBoundingClientRect().top <= base) id = vh[i].id; else break; }
    if (fill){
      var max = win ? document.documentElement.scrollHeight - window.innerHeight : sc.scrollHeight - sc.clientHeight;
      fill.style.width = (max > 0 ? Math.min(100, top() / max * 100) : 0) + "%";
    }
    if (id === active) return;
    active = id;
    var h = root.querySelector("#" + (window.CSS && CSS.escape ? CSS.escape(id) : id));
    if (cur && h) cur.textContent = (h.textContent || "").trim() || "Содержание";
    links.forEach(function(a){ a.classList.toggle("is-active", a.getAttribute("data-rd-go") === id); });
  }
  function onScroll(){ if (!raf) raf = requestAnimationFrame(sync); }
  function detach(){
    target.removeEventListener("scroll", onScroll);
    window.removeEventListener("resize", onScroll);
    if (root.__rdUndock) root.__rdUndock();
    if (raf) cancelAnimationFrame(raf);
  }
  target.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll, { passive: true });
  root.style.setProperty("--rd-top", (headH() + 14) + "px");
  // Перерисовка страницы (health пишет innerHTML на каждое действие) и повторное
  // открытие того же документа возвращают к месту чтения.
  // 1.46.0: opts.at — сразу на главу, чей заголовок содержит текст (без плавной прокрутки)
  var atH = null;
  if (opts.at){
    atH = heads.filter(function(h){ return h.id === opts.at; })[0] ||
          heads.filter(function(h){ return (h.textContent || "").indexOf(opts.at) >= 0; })[0] || null;
  }
  if (secOn){
    // 1.59.0: без at — первый раздел; at (id/текст ## или ###) — его раздел и прокрутка к ###
    var k0 = atH ? secOf(atH) : null;
    setSec(k0 != null ? k0 : 0);
    if (atH) jump(atH.id, true);
  } else if (atH){
    var base0 = win ? 0 : sc.getBoundingClientRect().top;
    (win ? window : sc).scrollTo({ top: Math.max(0, atH.getBoundingClientRect().top - base0 + top() - headH() - 10), behavior: "auto" });
  } else if (key && UI_READER_POS[key] && !win) sc.scrollTop = UI_READER_POS[key];
  requestAnimationFrame(sync);
  return detach;
}
// Навесить все ещё не навешенные читатели внутри узла — для страниц, которые
// перерисовываются строкой (health).
function uiReaderMountAll(scope){
  Array.prototype.forEach.call((scope || document).querySelectorAll(".rd"), function(r){ uiReaderMount(r); });
}

/* ── uiTripWhen: когда поездка (ui-kit 1.8.0) ───────────────────────────────
   Один расчёт для travel.html и hub.html (раньше у каждой своя копия разбора
   сезона). Признак «поездка / возможная поездка» — точные даты start/end в
   trip.yaml (решение владельца 2026-10-03); отдельного поля нет.
     trip        start+end                → «через 12 дн» · «идёт · день 3 из 10» · «прошла»
     trip-month  status ready + месяц      → «в следующем месяце» · «в этом месяце» · «прошла»
     possible    месяц, статус не ready    → «возможная · даты не определены», без отсчёта
     idea        только год                → «идея», без «в этом/следующем году»
     none        ничего                    → ""
   archive: null | "done" (status done) | "past" (поездка прошла) |
            "expired" (возможная/идея: срок прошёл, а дат так и нет).
   nearest: годится в «Ближайшую» (только trip и trip-month, не в архиве).
   today — "YYYY-MM-DD" или Date (для тестов); по умолчанию локальная дата. */
/* ═══ Даты: один словарь и три формата на кабинет (ui-kit 1.19.0) ═══════════
   Раньше месяцы лежали в девяти местах (hub, travel, games, health, money и
   дважды здесь же), а одно имя fmtDate значило три разных вывода: «6 октября
   2026» в hub/games и «окт 2025» в health. Формат выбирает место вызова — какой
   был, такой и остаётся (где показывали месяц — там месяц):
     uiDateLong(v)   «6 октября 2026»  v — "YYYY-MM-DD…" или Date (по локальному времени)
     uiMonthShort(v) «окт 2025»        v — "YYYY-MM[-DD]"
     uiDateNum(v)    «14.10.2025»      v — "YYYY-MM-DD"; "YYYY-MM" → «окт 2025»
     uiYmd(v)        Date из js-yaml (полночь UTC) → "YYYY-MM-DD"; строку — как есть
   Месяцы строчными; с заглавной — uiCap() при выводе. */
var UI_MONTHS_NOM = ["январь","февраль","март","апрель","май","июнь","июль","август","сентябрь","октябрь","ноябрь","декабрь"];
var UI_MONTHS_GEN = ["января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря"];
var UI_MONTHS_SHORT = ["янв","фев","мар","апр","май","июн","июл","авг","сен","окт","ноя","дек"];
function uiCap(s){ s = String(s == null ? "" : s); return s.charAt(0).toUpperCase() + s.slice(1); }
function uiYmd(v){ return v instanceof Date ? v.toISOString().slice(0, 10) : v; }
function uiDateLong(v){
  if (v instanceof Date) return v.getDate() + " " + UI_MONTHS_GEN[v.getMonth()] + " " + v.getFullYear();
  var m = String(v || "").match(/(\d{4})-(\d{2})-(\d{2})/);
  return m ? (+m[3]) + " " + UI_MONTHS_GEN[+m[2] - 1] + " " + m[1] : String(v || "");
}
function uiMonthShort(v){
  var p = String(v || "").split("-");
  if (p.length < 2) return v || "";
  return UI_MONTHS_SHORT[parseInt(p[1], 10) - 1] + " " + p[0];
}
function uiDateNum(v){
  var p = String(v || "").split("-");
  if (p.length === 2) return uiMonthShort(v);
  if (p.length < 3) return v || "";
  return p[2] + "." + p[1] + "." + p[0];
}
function uiTripWhen(t, today){
  t = t || {};
  function ymd(v){
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(v || "").trim().replace(/^["']|["']$/g, ""));
    if (!m) return null;
    var y = +m[1], mo = +m[2], d = +m[3], dt = new Date(Date.UTC(y, mo - 1, d));
    return dt.getUTCMonth() === mo - 1 && dt.getUTCDate() === d ? { y: y, m: mo, d: d, n: Date.UTC(y, mo - 1, d) / 864e5 } : null;
  }
  var T;
  if (today instanceof Date) T = ymd(today.getFullYear() + "-" + ("0" + (today.getMonth() + 1)).slice(-2) + "-" + ("0" + today.getDate()).slice(-2));
  else if (today) T = ymd(today);
  if (!T){ var n = new Date(); T = ymd(n.getFullYear() + "-" + ("0" + (n.getMonth() + 1)).slice(-2) + "-" + ("0" + n.getDate()).slice(-2)); }
  var status = String(t.status || "").trim();
  var S = ymd(t.start), E = ymd(t.end);
  if (!S || !E || E.n < S.n){ S = E = null; }
  var sm = /^(\d{4})(?:-(\d{2}))?/.exec(String(t.season || "").replace(/^["']|["']$/g, ""));
  var sy = sm ? +sm[1] : null, smo = sm && sm[2] ? +sm[2] : null;
  if (smo !== null && (smo < 1 || smo > 12)) smo = null;
  var NOEXACT = "точных дат нет — по сезону из trip.yaml";
  var r = { kind: "none", phase: null, label: "", title: "", seasonLabel: "", sortKey: null, archive: null, nearest: false };
  if (S){
    r.kind = "trip";
    r.sortKey = S.y * 10000 + S.m * 100 + S.d;
    r.seasonLabel = S.y === E.y
      ? (S.m === E.m ? S.d + "–" + E.d + " " + UI_MONTHS_GEN[S.m - 1] : S.d + " " + UI_MONTHS_GEN[S.m - 1] + " – " + E.d + " " + UI_MONTHS_GEN[E.m - 1]) + " " + S.y
      : S.d + " " + UI_MONTHS_GEN[S.m - 1] + " " + S.y + " – " + E.d + " " + UI_MONTHS_GEN[E.m - 1] + " " + E.y;
    r.title = r.seasonLabel;
    if (T.n < S.n){
      var dd = S.n - T.n;
      r.phase = "before"; r.label = dd === 1 ? "завтра" : "через " + dd + " дн";
    } else if (T.n <= E.n){
      r.phase = "during"; r.label = "идёт · день " + (T.n - S.n + 1) + " из " + (E.n - S.n + 1);
    } else { r.phase = "after"; r.label = "прошла"; r.archive = "past"; }
  } else if (sy !== null && smo !== null){
    r.kind = status === "ready" ? "trip-month" : "possible";
    r.sortKey = sy * 10000 + smo * 100 + 15;
    r.seasonLabel = uiCap(UI_MONTHS_NOM[smo - 1]) + " " + sy;
    r.title = NOEXACT;
    var md = (sy - T.y) * 12 + (smo - T.m);
    r.phase = md > 0 ? "before" : md === 0 ? "during" : "after";
    if (r.kind === "trip-month"){
      r.label = md > 1 ? "через " + md + " мес" : md === 1 ? "в следующем месяце" : md === 0 ? "в этом месяце" : "прошла";
      if (md < 0) r.archive = "past";
    } else {
      r.label = md < 0 ? "срок прошёл · дат нет" : "возможная · даты не определены";
      if (md < 0) r.archive = "expired";
    }
  } else if (sy !== null){
    r.kind = "idea";
    r.sortKey = sy * 10000 + 700;
    r.seasonLabel = String(sy);
    r.title = NOEXACT;
    r.phase = sy > T.y ? "before" : sy === T.y ? "during" : "after";
    r.label = sy < T.y ? "срок прошёл · дат нет" : "идея";
    if (sy < T.y) r.archive = "expired";
  }
  // Явный status: done сильнее расчёта: «состоялась», даже если дат нет.
  if (status === "done"){ r.archive = "done"; if (r.kind !== "none") r.label = "состоялась"; }
  r.nearest = (r.kind === "trip" || r.kind === "trip-month") && !r.archive && status !== "superseded";
  return r;
}

/* ── uiTripIsMine: чья поездка (ui-kit 1.9.0) ────────────────────────────────
   «Мои» — владелец кабинета в travelers (один или с кем-то); иначе — «для
   близких» (родители и т.п.). Нет travelers — поездка своя (давний дефолт
   travel/hub). Имя владельца — одно место на весь кабинет (раньше было
   вписано в whoKeys travel.html и tripIsMine hub.html по отдельности).
   travelers — массив или flow-строка «[алексей, мария]». */
var UI_OWNER = "алексей";   // основа имени: «алексей», «алексей_мария» в имени профиля
function uiTripIsMine(travelers){
  var list = Array.isArray(travelers) ? travelers
    : String(travelers == null ? "" : travelers).replace(/^\[|\]$/g, "").split(",");
  list = list.map(function(x){ return String(x).trim().toLowerCase().replace(/ё/g, "е"); })
             .filter(function(x){ return !!x; });
  if (!list.length) return true;
  return list.some(function(n){ return n.indexOf(UI_OWNER) >= 0; });
}

// anim — плавный уход (крестик, затемнение, Escape); без него — сразу (открытие другой справки)
function uiHelpClose(anim){
  if (!anim) [].forEach.call(document.querySelectorAll(".uh-overlay.leave"), function(o){ o.remove(); });
  var ov = document.querySelector(".uh-overlay:not(.leave)");
  if (!ov) return;
  document.documentElement.style.overflow = ov.getAttribute("data-prev-overflow") || "";
  var back = ov.__opener;
  if (back && back.focus && document.contains(back)) try { back.focus(); } catch(e){}
  if (anim) uiHide(ov, function(){ ov.remove(); }); else ov.remove();
}

/* 1.59.0: справка из нескольких файлов — раздел = файл. files: ["a/01-run.md", …] грузятся
   параллельно (тот же fetch без кэша, что у одиночного файла), склеиваются через пустую строку
   в порядке списка. Файл, который не загрузился, заменяется разделом-заглушкой «## <имя файла>»
   с пометкой «не загрузился» — остальные показываются. У частей после первой срезаются
   frontmatter и заголовок «# …» (он дублирует раздел). o.auth — грузить через authFetch.
   Возвращает Promise<string> (markdown целиком) — для uiReaderHTML. */
function uiFetchMarkdownParts(files, o){
  o = o || {};
  var get = o.auth ? authFetch : fetch;
  return Promise.all((files || []).map(function(f, idx){
    return get(f + (f.indexOf("?") < 0 ? "?" : "&") + "cb=" + Date.now(), { cache: "no-store" })
      .then(function(r){ if (!r.ok) throw new Error("HTTP " + r.status); return r.text(); })
      .then(function(md){
        if (idx === 0) return md;
        md = uiReaderFrontmatter(String(md).replace(/\r\n/g, "\n")).body.replace(/<!--[\s\S]*?-->/g, "");
        return md.replace(/^\s*#\s+[^\n]*\n?/, "");
      })
      .catch(function(e){
        var nm = String(f).split("?")[0].split("/").pop();
        return "## " + nm + "\n\n{.ui-note} Раздел не загрузился (" + (e && e.message || e) + "). Остальные разделы показаны.";
      });
  })).then(function(parts){ return parts.join("\n\n"); });
}

/* o — справка вне реестра UI_HELP (вьюер портфеля: viewer-help.md рядом со
   страницей, под паролем): { title, acc, src|file | files, auth, kicker, sections }.
   files — справка из нескольких файлов (uiFetchMarkdownParts); sections — режим «по разделам». */
function uiHelpOpen(page, opener, o){
  // 1.46.0: o.at — открыть сразу на главе, чей заголовок содержит этот текст (ссылка «Mode 4 → справка»)
  var meta = o || UI_HELP[page];
  if (!meta) return;
  var src = meta.src || meta.file || ("assets/help/" + encodeURIComponent(page) + ".md");
  var parts = Array.isArray(meta.files) && meta.files.length ? meta.files : null;
  uiHelpClose();
  var ov = document.createElement("div");
  ov.className = "uh-overlay enter";   // плавный вход (ui-kit 1.38.0)
  ov.setAttribute("data-prev-overflow", document.documentElement.style.overflow || "");
  ov.__opener = opener || null;
  ov.innerHTML =
    '<div class="uh-modal" role="dialog" aria-modal="true" aria-labelledby="uh-title" style="--uh-acc:var(' + meta.acc + ');">' +
      '<div class="uh-head"><div><div class="uh-kicker">' + esc(meta.kicker || "Справка · скиллы раздела") + '</div>' +
        '<h2 class="uh-title" id="uh-title">' + esc(meta.title) + '</h2></div>' +
        '<button type="button" class="uh-close" data-uh-close aria-label="Закрыть справку">✕</button></div>' +
      '<div class="uh-body"><div class="uh-state">Загрузка справки…</div></div>' +
    '</div>';
  document.body.appendChild(ov);
  // Прокрутка страницы под модалкой замирает, крутится сам оверлей.
  document.documentElement.style.overflow = "hidden";
  var close = ov.querySelector("[data-uh-close]");
  try { close.focus({ preventScroll: true }); } catch(e){}
  var body = ov.querySelector(".uh-body");
  (parts ? uiFetchMarkdownParts(parts, { auth: meta.auth }) :
    (meta.auth ? authFetch : fetch)(src + (src.indexOf("?") < 0 ? "?" : "&") + "cb=" + Date.now(), { cache: "no-store" })
      .then(function(r){ if (!r.ok) throw new Error("HTTP " + r.status); return r.text(); }))
    .then(function(md){
      if (!document.contains(body)) return;
      // Единый читатель: frontmatter срезается молча, первый H1 дублирует
      // заголовок модалки и тоже срезается. Оглавление — по UI_HELP_TOC.
      body.innerHTML = uiReaderHTML(md, { toc: UI_HELP_TOC, acc: meta.acc, frontmatter: false, key: "help:" + page, search: meta.search !== false, sections: meta.sections === true });
      // 1.60.0: на телефоне окно справки — колонка во весь экран, прокручивается тело (шапка и поиск неподвижны); иначе — оверлей
      var bodyScrolls = /auto|scroll/.test(getComputedStyle(body).overflowY);
      uiReaderMount(body, { scroller: bodyScrolls ? body : ov, head: bodyScrolls ? null : ov.querySelector(".uh-head"), at: meta.at || null });
    })
    .catch(function(e){
      if (!document.contains(body)) return;
      body.innerHTML = '<div class="uh-err">Не удалось загрузить справку (' + esc(src) + '): ' +
        esc(e && e.message || e) + '.<br>Справка грузится по HTTP — открой страницу через NAS-сервер, не через file://.</div>';
    });
}

document.addEventListener("click", function(ev){
  if (!ev.target.closest) return;
  var b = ev.target.closest("[data-ui-help]");
  if (b){ ev.preventDefault(); uiHelpOpen(b.getAttribute("data-ui-help"), b); return; }
  var ov = document.querySelector(".uh-overlay");
  if (!ov) return;
  // Клик по крестику или по затемнению (мимо окна) — закрыть.
  if (ev.target.closest("[data-uh-close]") || ev.target === ov){ ev.preventDefault(); uiHelpClose(true); }
}, false);

// Escape закрывает справку и НЕ доходит до страницы: у health/travel/games
// свой Escape («назад», закрыть просмотрщик) — без перехвата в capture-фазе
// одно нажатие закрыло бы и справку, и то, что было открыто под ней.
document.addEventListener("keydown", function(ev){
  if (ev.key !== "Escape" || !document.querySelector(".uh-overlay")) return;
  // 1.58.0: Escape в поле поиска по справке с введённым запросом — сначала очистить поиск (его снимает сам читатель), закрытие — следующим нажатием
  var t = ev.target;
  if (t && t.hasAttribute && t.hasAttribute("data-rd-q") && (t.value || document.querySelector(".uh-overlay mark.rd-hit"))) return;
  ev.preventDefault(); ev.stopImmediatePropagation(); ev.stopPropagation();
  uiHelpClose(true);
}, true);

// Escape по слоям и в читателе: открытая шторка оглавления (.rd-sheet, узкое
// окно) сворачивается первой, окно документа закрывает уже следующее нажатие.
// Справка выше перехватывает Escape раньше (слушатель зарегистрирован первым).
document.addEventListener("keydown", function(ev){
  if (ev.key !== "Escape") return;
  var sh = document.querySelector(".rd-sheet:not([hidden])");
  if (!sh) return;
  ev.preventDefault(); ev.stopImmediatePropagation(); ev.stopPropagation();
  sh.setAttribute("hidden", "");
  var root = sh.closest(".rd"), btn = root && root.querySelector("[data-rd-sheet]");
  if (btn) btn.setAttribute("aria-expanded", "false");
}, true);

/* ═══ Датапикер: календарь выбора даты ═══════════════════════════════════════
   Нативный <input type="date"> удобен, но его выпадашку нельзя стилизовать —
   она рисуется браузером и выбивается из кабинета. Поэтому свой компонент.

   Виджет САМОДОСТАТОЧЕН: ни одной ссылки на код страницы-хозяина.

   Так было не всегда, и цена ошибки — молчаливая смерть всех полей даты.
   Фаза 1 вынесла датапикер из health.html сюда, но три его зависимости
   (fmtDay/MSHORT/todayISO) остались объявлены ВНУТРИ IIFE health.html —
   то есть не в window. Свободная переменная в ui-kit.js их не находит:
     • openMonthPicker («Годен до» лекарства) успевал вставить пустой .dp-pop
       и падал на MSHORT — кнопка нажимается, но не показывает ничего, а
       следующий клик попадал в ветку «попап уже открыт» и просто закрывал
       его. Со стороны — «кнопка не работает»;
     • dateField с непустой датой падал на fmtDay ПРИ РЕНДЕРЕ, унося с собой
       всю модалку (прививка, вес, исследование не открывались вовсе).
   Ошибка ушла в pageerror, где её никто не читает, и жила до 2026-08-04.
   Отсюда правило: ничего host-специфичного в компонентах ui-kit.

   Важно: он НЕ дёргает общий render() страницы. Формы модалок неуправляемые
   (значения читаются со страницы в момент «Сохранить»), и полная перерисовка
   стёрла бы уже набранный текст в соседних полях. Поэтому виджет работает
   точечно с DOM: пишет ISO в скрытый input (его читает val()), а в видимом
   текстовом поле — ДД.ММ.ГГГГ.

   dateField (день) — поле РЕДАКТИРУЕМОЕ: раньше это была <button> без
   возможности набрать дату с клавиатуры. Теперь это <input>, календарь —
   по клику на иконку рядом (openCalendar), а набор руками — через маску
   maskDMY/parseDMY. monthField (месяц, например срок годности) — другая
   грамматика (месяц текстом, а не числом). */
// Дата-хелперы виджета: подписи — общие uiDateNum/UI_MONTHS_* (блок «Даты» выше).
function dpTodayISO(){                         // сегодня в ISO, по локальному времени
  var d = new Date();
  return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
}
function maskDMY(raw){                        // "2107202" -> "21.07.202"
  var d = String(raw || "").replace(/\D/g, "").slice(0, 8);
  if (d.length <= 2) return d;
  if (d.length <= 4) return d.slice(0, 2) + "." + d.slice(2);
  return d.slice(0, 2) + "." + d.slice(2, 4) + "." + d.slice(4, 8);
}
function parseDMY(s){                          // "21.07.2026" -> "2026-07-21" | null
  var m = /^(\d{1,2})\.(\d{1,2})\.(\d{4})$/.exec(String(s || "").trim());
  if (!m) return null;
  var d = parseInt(m[1], 10), mo = parseInt(m[2], 10), y = parseInt(m[3], 10);
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return null;
  var dt = new Date(y, mo - 1, d);
  // «31.02» рвётся тут: JS Date тихо перекатывает несуществующий день в
  // следующий месяц, round-trip его ловит.
  if (dt.getFullYear() !== y || dt.getMonth() !== mo - 1 || dt.getDate() !== d) return null;
  return y + "-" + String(mo).padStart(2, "0") + "-" + String(d).padStart(2, "0");
}
// Приватные константы виджета (не глобальные WD/MONTHS_NOM хозяина —
// префикс DP_ защищает от будущей коллизии, т.к. ui-kit.js грузится всеми
// страницами кабинета, а не только health.html).
var DP_WD = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

function dateField(name, iso){
  var vis = iso ? uiDateNum(iso) : "";
  return '<div class="dp-wrap">' +
    '<input type="hidden" id="f-' + name + '" value="' + esc(iso || "") + '">' +
    '<input type="text" class="dp-input" id="fv-' + name + '" data-dpv="' + name + '" ' +
      'inputmode="numeric" autocomplete="off" placeholder="ДД.ММ.ГГГГ" value="' + esc(vis) + '">' +
    '<button type="button" class="dp-ico-btn" data-dp-open="' + name + '" aria-label="Открыть календарь">▤</button>' +
  '</div>';
}

/* 1.69.1: обвязка стандартного поля даты для страниц без своей (health.html держит собственную): кнопка ▤
   открывает календарь, щелчок мимо и Esc закрывают, ручной ввод — маска ДД.ММ.ГГГГ и ISO в скрытое f-<имя>.
   Вызывать один раз при загрузке страницы. */
var UI_DATE_WIRED = false;
function uiDateWire(){
  if (UI_DATE_WIRED || typeof document === "undefined") return;
  UI_DATE_WIRED = true;
  document.addEventListener("click", function(ev){
    var b = ev.target.closest && ev.target.closest("[data-dp-open]");
    if (b){ ev.preventDefault(); openCalendar(b); return; }
    if (!(ev.target.closest && ev.target.closest(".dp-pop"))) closeCalendars();
  });
  document.addEventListener("input", function(ev){
    var n = ev.target.getAttribute && ev.target.getAttribute("data-dpv");
    if (!n) return;
    var masked = maskDMY(ev.target.value);
    if (masked !== ev.target.value) ev.target.value = masked;
    var hidden = document.getElementById("f-" + n), parsed = masked.length === 10 ? parseDMY(masked) : null;
    if (hidden) hidden.value = parsed || "";
    ev.target.classList.toggle("is-invalid", masked.length === 10 && !parsed);
  });
  document.addEventListener("focusout", function(ev){
    var n = ev.target.getAttribute && ev.target.getAttribute("data-dpv");
    if (!n) return;
    var v = ev.target.value.trim();
    ev.target.classList.toggle("is-invalid", !!v && !parseDMY(v));
  });
  document.addEventListener("keydown", function(ev){
    if (ev.key === "Escape" && document.querySelector(".dp-pop")){ ev.preventDefault(); ev.stopImmediatePropagation(); closeCalendars(); }
  }, true);
}

/* ── поле неполной даты (1.65.0) ──────────────────────────────────────────
   Хранение: "ГГГГ-ММ-ДД" | "ГГГГ-ММ" | "ГГГГ" | "". Ввод цифрами БЕЗ автомаски
   (точки на лету сделали бы «2024» и «1503» неразличимыми): 4 цифры — год,
   6 — месяц и год, 8 — дата; с разделителями — по числу частей. */
function parseFuzzyDate(s){                    // → {iso, prec} | null
  var t = String(s == null ? "" : s).trim();
  if (!t) return { iso: "", prec: "" };
  var dd, mm, yy;
  if (/^\d+$/.test(t)){
    if (t.length === 4) yy = t;
    else if (t.length === 6){ mm = t.slice(0, 2); yy = t.slice(2); }
    else if (t.length === 8){ dd = t.slice(0, 2); mm = t.slice(2, 4); yy = t.slice(4); }
    else return null;
  } else {
    var parts = t.split(/[.,\-\/\s]+/).filter(function(x){ return x !== ""; });
    for (var i = 0; i < parts.length; i++) if (!/^\d+$/.test(parts[i])) return null;
    if (parts.length === 1 && parts[0].length === 4) yy = parts[0];
    else if (parts.length === 2){ mm = parts[0]; yy = parts[1]; }
    else if (parts.length === 3){ dd = parts[0]; mm = parts[1]; yy = parts[2]; }
    else return null;
  }
  if (!/^\d{4}$/.test(yy)) return null;
  var y = parseInt(yy, 10);
  if (y < 1900 || y > 2100) return null;
  if (mm === undefined) return { iso: yy, prec: "y" };
  if (mm.length > 2) return null;
  var mo = parseInt(mm, 10);
  if (mo < 1 || mo > 12) return null;
  var mIso = yy + "-" + String(mo).padStart(2, "0");
  if (dd === undefined) return { iso: mIso, prec: "m" };
  if (dd.length > 2) return null;
  var full = parseDMY(parseInt(dd, 10) + "." + mo + "." + yy);
  return full ? { iso: full, prec: "d" } : null;
}
function fuzzyDateText(iso){                   // "2024-03-15" → «15.03.2024»
  var m = /^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$/.exec(String(iso || ""));
  if (!m) return "";
  return (m[3] ? m[3] + "." : "") + (m[2] ? m[2] + "." : "") + m[1];
}
function fuzzyDateHint(iso){
  var m = /^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$/.exec(String(iso || ""));
  if (!m) return "";
  if (m[3]) return uiDateLong(iso);
  if (m[2]) return UI_MONTHS_NOM[parseInt(m[2], 10) - 1] + " " + m[1] + " · месяц";
  return m[1] + " · год";
}
// opts.only: "y" — только год (поле «с какого года»): 4 цифры, календарь сразу сеткой лет, без переключателя точности
function uiFuzzyDateField(name, iso, opts){
  iso = iso || "";
  var y = !!(opts && opts.only === "y"), only = y ? ' data-fd-only="y"' : '';
  return '<div class="dp-wrap">' +
    '<input type="hidden" id="f-' + name + '" value="' + esc(iso) + '">' +
    '<input type="text" class="dp-input" id="fv-' + name + '" data-fdv="' + name + '"' + only + ' inputmode="numeric" autocomplete="off" ' +
      (y ? 'maxlength="4" ' : '') + 'placeholder="' + (y ? 'ГГГГ' : 'ДД.ММ.ГГГГ') + '" value="' + esc(fuzzyDateText(iso)) + '">' +
    '<button type="button" class="dp-ico-btn" data-fd-open="' + name + '"' + only + ' aria-label="Открыть календарь">▤</button>' +
  '</div><div class="fd-hint" id="fh-' + name + '">' + esc(fuzzyDateHint(iso) || fdEmptyHint(y)) + '</div>';
}
function fdEmptyHint(y){ return y ? "год, 4 цифры" : "дата, ММ.ГГГГ или ГГГГ"; }
// разбор с учётом «только год»: месяц или дата в таком поле — ошибка
function fdParse(input){
  var r = parseFuzzyDate(input.value);
  return r && r.iso && input.getAttribute("data-fd-only") === "y" && r.prec !== "y" ? null : r;
}
function fdSync(name, iso, bad){               // подпись под полем
  var h = document.getElementById("fh-" + name), inp = document.getElementById("fv-" + name);
  if (!h) return;
  var y = !!(inp && inp.getAttribute("data-fd-only") === "y");
  h.textContent = bad ? (y ? "не год: 4 цифры, например 2015" : "не дата: 4, 6 или 8 цифр — год, месяц и год, дата") : (fuzzyDateHint(iso) || fdEmptyHint(y));
  h.classList.toggle("is-bad", !!bad);
}
document.addEventListener("input", function(ev){
  var n = ev.target.getAttribute && ev.target.getAttribute("data-fdv");
  if (!n) return;
  var r = fdParse(ev.target);
  var hidden = document.getElementById("f-" + n);
  if (hidden) hidden.value = r ? r.iso : "";
  if (r) ev.target.classList.remove("is-invalid");
  fdSync(n, r ? r.iso : "", !r);
});
document.addEventListener("focusout", function(ev){
  var n = ev.target.getAttribute && ev.target.getAttribute("data-fdv");
  if (!n) return;
  var r = fdParse(ev.target);
  if (r && r.iso) ev.target.value = fuzzyDateText(r.iso);
  ev.target.classList.toggle("is-invalid", !r);
});
document.addEventListener("click", function(ev){
  var b = ev.target.closest ? ev.target.closest("[data-fd-open]") : null;
  if (!b) return;
  ev.preventDefault();
  ev.stopImmediatePropagation();               // обработчик страницы «клик мимо — закрыть» не должен гасить открытый попап
  openCalendar(b);
});

function closeCalendars(){
  var pops = document.querySelectorAll(".dp-pop");
  for (var i = 0; i < pops.length; i++) pops[i].remove();
}

/* Срок годности и подобные поля — месяц и год. Нативный month-input не
   годится: Safari его НЕ поддерживает и рисует обычное текстовое поле без
   всякого пикера. Поэтому свой выбор в грамматике dp-*: год стрелками,
   месяц сеткой 3×4. */
function monthField(name, iso){
  var vis = iso && /^\d{4}-\d{2}$/.test(iso) ? UI_MONTHS_NOM[parseInt(iso.split("-")[1], 10) - 1] + " " + iso.split("-")[0] : "выбрать месяц";
  return '<div class="dp-wrap">' +
    '<input type="hidden" id="f-' + name + '" value="' + esc(iso || "") + '">' +
    '<button type="button" class="dp-field' + (iso ? '' : ' is-empty') + '" data-mp="' + name + '">' +
      '<span class="dp-val">' + esc(vis) + '</span><span class="dp-ico">▤</span></button>' +
  '</div>';
}

function openMonthPicker(btn){
  var name = btn.getAttribute("data-mp");
  var input = document.getElementById("f-" + name);
  var already = document.querySelector('.dp-pop[data-for="' + name + '"]');
  closeCalendars();
  if (already) return;

  var sel = /^\d{4}-\d{2}$/.test(input.value) ? input.value : null;
  var now = new Date();
  var view = { y: sel ? parseInt(sel.split("-")[0], 10) : now.getFullYear() };
  var curIso = now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0");

  var pop = document.createElement("div");
  pop.className = "dp-pop";
  pop.setAttribute("data-for", name);
  pop.style.position = "fixed";
  document.body.appendChild(pop);
  function place(){
    var r = btn.getBoundingClientRect();
    var h = pop.offsetHeight || 240, w = pop.offsetWidth || 274;
    var top = r.bottom + 6;
    if (top + h > window.innerHeight - 8) top = Math.max(8, r.top - h - 6);
    pop.style.top = Math.round(top) + "px";
    pop.style.left = Math.round(Math.max(8, Math.min(r.left, window.innerWidth - w - 8))) + "px";
  }
  function draw(){
    var cells = UI_MONTHS_NOM.map(function(mn, i){
      var v = view.y + "-" + String(i + 1).padStart(2, "0");
      var cls = "dp-day dp-mon";
      if (v === curIso) cls += " dp-today";
      if (v === sel) cls += " dp-sel";
      // Истёкшее видно прямо в пикере: выбирать прошлый месяц можно
      // (лекарство могло протухнуть), но пусть это будет заметно.
      if (v < curIso) cls += " dp-past";
      return '<button type="button" class="' + cls + '" data-m="' + v + '">' + UI_MONTHS_SHORT[i] + '</button>';
    }).join("");
    pop.innerHTML =
      '<div class="dp-head">' +
        '<button type="button" class="dp-nav" data-nav="-1" aria-label="Предыдущий год">◀</button>' +
        '<div class="dp-title">' + view.y + '</div>' +
        '<button type="button" class="dp-nav" data-nav="1" aria-label="Следующий год">▶</button>' +
      '</div>' +
      '<div class="mp-grid">' + cells + '</div>' +
      '<div class="dp-foot"><button type="button" data-set="">Очистить</button></div>';
  }
  draw(); place();

  pop.addEventListener("click", function(ev){
    var t = ev.target.closest("button");
    if (!t) return;
    ev.preventDefault(); ev.stopPropagation();
    if (t.hasAttribute("data-nav")){
      view.y += parseInt(t.getAttribute("data-nav"), 10);
      draw(); place(); return;
    }
    var v = t.hasAttribute("data-m") ? t.getAttribute("data-m")
          : (t.hasAttribute("data-set") ? t.getAttribute("data-set") : null);
    if (v === null) return;
    input.value = v;
    var lab = btn.querySelector(".dp-val");
    if (lab) lab.textContent = v ? UI_MONTHS_NOM[parseInt(v.split("-")[1], 10) - 1] + " " + v.split("-")[0] : "выбрать месяц";
    btn.classList.toggle("is-empty", !v);
    closeCalendars();
  });
}

/* День со «всплытием» год↔месяц↔день: должна быть возможность нажать на
   месяц — выбрать месяц; нажать на год — выбрать год, потом месяц, потом
   день. Заголовок — <button> в day/month-режиме (клик всплывает на уровень
   выше), и обычный <div> в year-режиме (там уже верхний уровень, всплывать
   некуда). Выбор в year/month-режиме не закрывает попап — спускается на
   уровень ниже; закрывает только выбор конкретного дня (data-d) или
   «Сегодня»/«Очистить» (data-set). */
function openCalendar(btn){
  var fz = btn.hasAttribute("data-fd-open") ? "d" : null;   // нечёткий режим: точность d | m | y
  var name = btn.getAttribute(fz ? "data-fd-open" : "data-dp-open");
  var hidden = document.getElementById("f-" + name);
  var text = document.getElementById("fv-" + name);
  var already = document.querySelector('.dp-pop[data-for="' + name + '"]');
  closeCalendars();
  if (already) return;                       // повторный клик по тому же полю — закрыть

  var sel = hidden.value && /^\d{4}-\d{2}-\d{2}$/.test(hidden.value) ? hidden.value : null;
  var base = sel ? new Date(sel + "T00:00:00") : new Date();
  var valPrec = "", fzv = hidden.value;        // точность текущего значения (нечёткий режим)
  if (fz){
    valPrec = /^\d{4}-\d{2}-\d{2}$/.test(fzv) ? "d" : /^\d{4}-\d{2}$/.test(fzv) ? "m" : /^\d{4}$/.test(fzv) ? "y" : "";
    if (valPrec) base = new Date(parseInt(fzv.slice(0, 4), 10), valPrec === "y" ? 0 : parseInt(fzv.slice(5, 7), 10) - 1, valPrec === "d" ? parseInt(fzv.slice(8, 10), 10) : 1);
    fz = valPrec || "d";
    if (btn.getAttribute("data-fd-only") === "y") fz = "y";
  }
  var fzLock = btn.getAttribute("data-fd-only") === "y";   // только год — без переключателя точности
  var view = { mode: fz === "m" ? "month" : fz === "y" ? "year" : "day", y: base.getFullYear(), m: base.getMonth(), yb: base.getFullYear() - 5 };

  // ВАЖНО: попап живёт в <body>, а не рядом с полем. Тело модалки имеет
  // overflow-y:auto и обрезает всё, что выходит за его границы — календарь
  // внутри него показывал только шапку с днями недели (поймано на снимке).
  var pop = document.createElement("div");
  pop.className = "dp-pop";
  pop.setAttribute("data-for", name);
  pop.style.position = "fixed";
  document.body.appendChild(pop);
  function place(){
    var r = btn.getBoundingClientRect();
    var h = pop.offsetHeight || 320, w = pop.offsetWidth || 274;
    var top = r.bottom + 6;
    if (top + h > window.innerHeight - 8) top = Math.max(8, r.top - h - 6);  // не влезает вниз — вверх
    var left = Math.min(r.right - w, window.innerWidth - w - 8);
    pop.style.top = Math.round(top) + "px";
    pop.style.left = Math.round(Math.max(8, left)) + "px";
  }

  function iso(y, m, d){
    return y + "-" + String(m + 1).padStart(2, "0") + "-" + String(d).padStart(2, "0");
  }
  function commit(v){
    hidden.value = v || "";
    if (text){ text.value = fz ? fuzzyDateText(v) : (v ? uiDateNum(v) : ""); text.classList.remove("is-invalid"); }
    if (fz) fdSync(name, v || "", false);
    closeCalendars();
  }
  function drawBody(){
    if (view.mode === "year"){
      var curY = new Date().getFullYear(), cellsY = "";
      for (var yy = view.yb; yy < view.yb + 12; yy++){
        var clsY = "dp-day dp-yr";
        if (yy === curY) clsY += " dp-today";
        if (fz ? (fz === "y" && valPrec === "y" && yy === parseInt(fzv, 10)) : yy === view.y) clsY += " dp-sel";
        cellsY += '<button type="button" class="' + clsY + '" data-y="' + yy + '">' + yy + '</button>';
      }
      pop.innerHTML =
        '<div class="dp-head">' +
          '<button type="button" class="dp-nav" data-nav="-12" aria-label="Предыдущие годы">◀</button>' +
          '<div class="dp-title">' + view.yb + '–' + (view.yb + 11) + '</div>' +
          '<button type="button" class="dp-nav" data-nav="12" aria-label="Следующие годы">▶</button>' +
        '</div>' +
        '<div class="mp-grid">' + cellsY + '</div>';
      return;
    }
    if ("month" === view.mode){
      var now = new Date(), selY = sel ? parseInt(sel.slice(0, 4), 10) : null, selM = sel ? parseInt(sel.slice(5, 7), 10) - 1 : null;
      var cellsM = UI_MONTHS_NOM.map(function(mn, i){
        var clsM = "dp-day dp-mon";
        if (view.y === now.getFullYear() && i === now.getMonth()) clsM += " dp-today";
        if (fz ? (fz === "m" && valPrec === "m" && view.y === parseInt(fzv.slice(0, 4), 10) && i === parseInt(fzv.slice(5, 7), 10) - 1) : (view.y === selY && i === selM)) clsM += " dp-sel";
        return '<button type="button" class="' + clsM + '" data-m="' + i + '">' + UI_MONTHS_SHORT[i] + '</button>';
      }).join("");
      pop.innerHTML =
        '<div class="dp-head">' +
          '<button type="button" class="dp-nav" data-nav="-1" aria-label="Предыдущий год">◀</button>' +
          '<button type="button" class="dp-title" data-drill="year">' + view.y + '</button>' +
          '<button type="button" class="dp-nav" data-nav="1" aria-label="Следующий год">▶</button>' +
        '</div>' +
        '<div class="mp-grid">' + cellsM + '</div>';
      return;
    }
    var first = new Date(view.y, view.m, 1);
    // В JS неделя начинается с воскресенья — сдвигаем к понедельнику.
    var shift = (first.getDay() + 6) % 7;
    var start = new Date(view.y, view.m, 1 - shift);
    var todayIso = dpTodayISO();
    var cells = "";
    for (var i = 0; i < 42; i++){
      var d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
      var di = iso(d.getFullYear(), d.getMonth(), d.getDate());
      var cls = "dp-day";
      if (d.getMonth() !== view.m) cls += " dp-out";
      if (di === todayIso) cls += " dp-today";
      if (di === sel && (!fz || valPrec === "d")) cls += " dp-sel";
      cells += '<button type="button" class="' + cls + '" data-d="' + di + '">' + d.getDate() + '</button>';
    }
    pop.innerHTML =
      '<div class="dp-head">' +
        '<button type="button" class="dp-nav" data-nav="-1" aria-label="Предыдущий месяц">◀</button>' +
        '<button type="button" class="dp-title" data-drill="month">' + UI_MONTHS_NOM[view.m] + " " + view.y + '</button>' +
        '<button type="button" class="dp-nav" data-nav="1" aria-label="Следующий месяц">▶</button>' +
      '</div>' +
      '<div class="dp-grid">' + DP_WD.map(function(w){ return '<div class="dp-wd">' + w + '</div>'; }).join("") + cells + '</div>' +
      '<div class="dp-foot"><button type="button" data-set="' + todayIso + '">Сегодня</button>' +
        '<button type="button" data-set="">Очистить</button></div>';
  }
  function draw(){
    drawBody();
    if (!fz) return;
    if (!pop.querySelector(".dp-foot")){
      var nowD = new Date(), foot = fz === "m"
        ? '<button type="button" data-set="' + nowD.getFullYear() + "-" + String(nowD.getMonth() + 1).padStart(2, "0") + '">Этот месяц</button>'
        : fz === "y" ? '<button type="button" data-set="' + nowD.getFullYear() + '">Этот год</button>'
        : '<button type="button" data-set="' + dpTodayISO() + '">Сегодня</button>';
      pop.insertAdjacentHTML("beforeend", '<div class="dp-foot">' + foot + '<button type="button" data-set="">Очистить</button></div>');
    }
    var seg = [["d", "День"], ["m", "Месяц"], ["y", "Год"]].map(function(o){
      return '<button type="button" data-prec="' + o[0] + '" class="' + (fz === o[0] ? "on" : "") + '" aria-pressed="' + (fz === o[0] ? "true" : "false") + '">' + o[1] + '</button>';
    }).join("");
    if (!fzLock) pop.insertAdjacentHTML("afterbegin", '<div class="dp-prec" role="group" aria-label="Точность даты">' + seg + '</div>');
  }
  draw();
  place();

  pop.addEventListener("click", function(ev){
    var t = ev.target.closest("button");
    if (!t) return;
    ev.preventDefault(); ev.stopPropagation();
    if (fz && t.hasAttribute("data-prec")){
      fz = t.getAttribute("data-prec");
      view.mode = fz === "m" ? "month" : fz === "y" ? "year" : "day";
      if (fz === "y") view.yb = view.y - 5;
      draw(); place(); return;
    }
    if (t.hasAttribute("data-drill")){
      if (t.getAttribute("data-drill") === "year"){ view.yb = view.y - 5; view.mode = "year"; }
      else view.mode = "month";
      draw(); place(); return;
    }
    if (t.hasAttribute("data-nav")){
      var step = parseInt(t.getAttribute("data-nav"), 10);
      if (view.mode === "year") view.yb += step;
      else if ("month" === view.mode) view.y += step;
      else { var nm = view.m + step; view.y += Math.floor(nm / 12); view.m = ((nm % 12) + 12) % 12; }
      draw(); place(); return;
    }
    if (t.hasAttribute("data-y")){
      view.y = parseInt(t.getAttribute("data-y"), 10);
      if (fz === "y"){ commit(String(view.y)); return; }
      view.mode = "month"; draw(); place(); return;
    }
    if (t.hasAttribute("data-m")){
      view.m = parseInt(t.getAttribute("data-m"), 10);
      if (fz === "m"){ commit(view.y + "-" + String(view.m + 1).padStart(2, "0")); return; }
      view.mode = "day"; draw(); place(); return;
    }
    if (t.hasAttribute("data-d")){ commit(t.getAttribute("data-d")); return; }
    if (t.hasAttribute("data-set")){ commit(t.getAttribute("data-set")); return; }
  });
}


/* ── «что сказать Claude» — копирование по нажатию (1.49.0) ───────────────
   Читатель markdown рисует [фраза](#copy) кнопкой .ui-say. Нажатие копирует
   текст фразы; на кнопке на 1,6 с — «скопировано». Буфер обмена недоступен
   (страница по http в LAN) — запасной путь через выделение и execCommand. */
function uiCopyText(text){
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
  return new Promise(function(ok, fail){
    var ta = document.createElement("textarea");
    ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy") ? ok() : fail(new Error("copy")); } catch(e){ fail(e); }
    ta.remove();
  });
}
document.addEventListener("click", function(ev){
  var b = ev.target.closest ? ev.target.closest("[data-ui-copy]") : null;
  if (!b) return;
  ev.preventDefault();
  uiCopyText(b.textContent.trim()).then(function(){
    b.classList.add("copied");
    clearTimeout(b.__t); b.__t = setTimeout(function(){ b.classList.remove("copied"); }, 1600);
  }, function(){});
});

/* ── кнопка команды для Claude (1.66.0) ───────────────────────────────────
   uiClaudeCmd(text, {label}) — HTML кнопки. Контурная, со значком копирования:
   отличается от залитых кнопок записи на сайт. Копирует text (uiCopyText), на
   кнопке 1,6 с «скопировано»; буфер недоступен — уведомление с самим текстом. */
function uiClaudeCmd(text, o){
  var label = (o && o.label) || "для Claude";
  return '<button type="button" class="ui-claude-cmd" data-cmd="' + esc(text) + '" title="' + esc("Скопировать для чата Claude: " + text) + '">' +
    '<svg class="ui-cc-ico" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"><rect x="5.5" y="5.5" width="8" height="8" rx="1.5"/><path d="M10.5 3.5v-.5a1.5 1.5 0 0 0-1.5-1.5H3.5A1.5 1.5 0 0 0 2 3v5.5A1.5 1.5 0 0 0 3.5 10H4"/></svg>' +
    '<span class="ui-cc-t">' + esc(label) + '</span></button>';
}
document.addEventListener("click", function(ev){
  var b = ev.target.closest ? ev.target.closest(".ui-claude-cmd") : null;
  if (!b) return;
  ev.preventDefault(); ev.stopPropagation();
  var cmd = b.getAttribute("data-cmd") || "";
  uiCopyText(cmd).then(function(){
    var t = b.querySelector(".ui-cc-t");
    if (!b.__lbl && t) b.__lbl = t.textContent;
    if (t) t.textContent = "скопировано";
    b.classList.add("copied");
    clearTimeout(b.__t); b.__t = setTimeout(function(){ b.classList.remove("copied"); if (t && b.__lbl) t.textContent = b.__lbl; }, 1600);
  }, function(){ uiNotice(cmd, "info", 6000); });
}, true);

/* ── крестик очистки поиска (v1.5.0) ──────────────────────────────────────
   uiSearchX("f-rec-q") → кнопка, которая ставится сразу за <input id="f-rec-q">.
   Прячется CSS'ом, пока поле пустое (нужен placeholder у поля — он есть у
   всех полей поиска кабинета). 1.50.0: после очистки курсор в поле НЕ ставится
   (и уходит, если был): крестик — «убрать поиск», а не «набрать заново»;
   на телефоне не всплывает клавиатура. */
function uiSearchX(forId){
  return '<button type="button" class="ui-search-x" data-ui-search-x="' + esc(forId) +
    '" aria-label="Очистить поиск" title="Очистить">✕</button>';
}
document.addEventListener("click", function(ev){
  var b = ev.target.closest ? ev.target.closest("[data-ui-search-x]") : null;
  if (!b) return;
  ev.preventDefault();
  var inp = document.getElementById(b.getAttribute("data-ui-search-x"));
  if (!inp) return;
  inp.value = "";
  if (document.activeElement === inp) inp.blur();
  inp.dispatchEvent(new Event("input", { bubbles: true }));
});
// 1.50.0: Enter в поле поиска — выйти из поля (на телефоне прячется клавиатура); поиск и так
// применяется на каждой букве, «отправлять» нечего. 1.50.1: любое поле поиска кабинета —
// .ui-q или поле с крестиком uiSearchX (Здоровье, Еда), а не только .ui-q вьюера.
// 1.63.0: клавиши поиска отдаются странице событием "ui-search-key" (detail.key — Enter |
// ArrowDown | ArrowUp; отменяемое, всплывает от поля): страница знает, что такое «открыть
// единственный результат» и «перебрать результаты»; кит — нет. Страница обработала →
// preventDefault, и кит ничего не делает; не обработала — прежнее поведение (Enter убирает
// поле из фокуса). Escape: непустой запрос — стирается, пустой — поле теряет фокус; до
// страницы Escape не доходит (у Еды Escape в редакторе — «Отмена», его поиск не касается).
function uiIsSearchInput(t){
  return !!(t && t.tagName === "INPUT" && ((t.classList && t.classList.contains("ui-q")) ||
    (t.id && document.querySelector('[data-ui-search-x="' + t.id.replace(/"/g, '') + '"]'))));
}
document.addEventListener("keydown", function(ev){
  var t = ev.target;
  if (ev.isComposing || !uiIsSearchInput(t)) return;
  if (ev.key === "Escape"){
    ev.preventDefault(); ev.stopPropagation();
    if (t.value){ t.value = ""; t.dispatchEvent(new Event("input", { bubbles: true })); }
    else t.blur();
    return;
  }
  if (ev.key !== "Enter" && ev.key !== "ArrowDown" && ev.key !== "ArrowUp") return;
  var e2 = new CustomEvent("ui-search-key", { bubbles: true, cancelable: true, detail: { key: ev.key } });
  t.dispatchEvent(e2);
  if (e2.defaultPrevented){ ev.preventDefault(); return; }
  if (ev.key === "Enter"){ ev.preventDefault(); t.blur(); }
});

/* ═══ Выпадающий список (v1.11.0; один на кабинет с v1.20.0) ═════════════════
   Пара к .ui-select-* в ui-kit.css; вид — из макета «Деньги» (выбор поездки).
   uiSelectHTML({ name, label, cur: {t, s}, options: [{ value, t, s, aside,
   selected }], compact, size, block, id, act, attrs, style, search, placeholder, value })
   → разметка. attrs — доп. атрибуты скрытого поля (data-* для обработчика страницы),
   style — на корень (например, max-width в строке).

   Один компонент на два случая (решение владельца 2026-10-06):
     мало вариантов  — просто список;
     много (> 12) или search:true — сверху поле: печатаешь «мол…», остаются
                       подходящие (без учёта регистра, ё = е); Enter — первый.
   Размеры: крупный (по умолчанию — главный выбор страницы, как месяц в
   «Деньгах») и size:"md" — обычный, в формах и панелях фильтров (как поле
   ввода рядом). block:true — во всю ширину (поле формы).
   Телефон — не отдельный размер: мишень ≥ 44px; длинный список (с поиском)
   открывается шторкой у верха экрана — снизу его закрыла бы клавиатура;
   шрифт поиска 16px — иначе iPhone увеличивает страницу при касании; рядом с
   поиском крестик — закрыть список одним касанием.

   Выбор: подпись кнопки и галочка обновляются НА МЕСТЕ (формы не
   перерисовываются — пропал бы набранный текст), на корне всплывает
   CustomEvent("ui-select", { name, value }). Для форм — id: скрытое поле
   <input type="hidden" id=… data-act=…> держит значение (код сохранения
   читает .value, как у <select>) и получает всплывающий "change", как
   нативный список. cur можно не передавать — берётся из selected. value — что
   записано: нет в вариантах — показывается первым «нет в списке» и не теряется.

   Раскрытая часть ставится по экрану (position:fixed) у кнопки: не режется
   прокручиваемым окном формы; внизу нет места — раскрывается вверх.
   Длинный список в форме (combo) тоже раскрывается ПОВЕРХ содержимого: от верха
   поля, ряд не растёт, соседи не двигаются.
   Клавиатура: Enter/Space/↓ открывают, ↑/↓ ходят, Home/End — к краям, буква
   на закрытом длинном списке — открыть с поиском по ней, Esc — закрыть и
   вернуть фокус на кнопку; клик мимо, Tab наружу, прокрутка страницы —
   закрывают или переставляют. */
var UI_SELECT_SEARCH_MIN = 13;
function uiSelNorm(s){ return String(s || "").toLowerCase().replace(/ё/g, "е"); }
function uiSelectHTML(o){
  o = o || {};
  var opts = o.options || [];
  // value — записанное значение поля. Нет такого варианта (скилл записал своё,
  // словарь сменился) — показываем его первым «нет в списке» и сохраняем как
  // есть: <select> молча подставлял первый вариант и правка рукой его затирала
  if (o.value != null && o.value !== "" &&
      !opts.some(function(x){ return String(x.value) === String(o.value); })){
    opts = [{ value: o.value, t: String(o.value), s: "записано так — нет в списке", selected: true }]
      .concat(opts.map(function(x){ return Object.assign({}, x, { selected: false }); }));
  }
  var sel = opts.filter(function(x){ return x.selected; })[0];
  // поле формы ведёт себя как <select>: ничего не выбрано — выбран первый
  // (и его значение уйдёт при сохранении) — иначе поменялось бы, что пишется
  if (!sel && o.id && opts.length){
    opts = opts.map(function(x, k){ return k ? x : Object.assign({}, x, { selected: true }); });
    sel = opts[0];
  }
  var cur = o.cur || (sel ? { t: sel.t, s: sel.s } : { t: o.empty || "—" });
  var search = o.search != null ? !!o.search : opts.length >= UI_SELECT_SEARCH_MIN;
  // combo — длинный список в форме (обычный размер): печатают прямо в поле,
  // подсказки — поверх содержимого от верха поля (решение владельца 2026-10-06:
  // одна строка вместо кнопки + поиска; 2026-10-30: поверх везде, не раздвигая соседей)
  var combo = search && o.size === "md";
  var cls = "ui-select" + (o.compact ? " compact" : "") + (o.size === "md" ? " md" : "") +
            (o.block ? " block" : "") + (search ? " search" : "") + (combo ? " combo" : "");
  var extra = Object.keys(o.attrs || {}).map(function(k){ return " " + k + '="' + attr(o.attrs[k]) + '"'; }).join("");
  return '<div class="' + cls + '" data-ui-select="' + attr(o.name || o.id || "") + '"' +
      (o.style ? ' style="' + attr(o.style) + '"' : '') + '>' +
    (o.id ? '<input type="hidden" id="' + attr(o.id) + '" value="' + attr(sel ? sel.value : "") + '"' +
            (o.act ? ' data-act="' + attr(o.act) + '"' : '') + extra + '>' : '') +
    '<button type="button" class="ui-select-btn" aria-haspopup="listbox" aria-expanded="false"' +
      (o.label ? ' aria-label="' + attr(o.label) + '"' : '') + '>' +
      '<span class="ui-select-bar" aria-hidden="true"></span>' +
      '<span class="ui-select-txt"><span class="ui-select-t">' + esc(cur.t || "") + '</span>' +
        '<span class="ui-select-s"' + (cur.s ? '' : ' hidden') + '>' + esc(cur.s || "") + '</span></span>' +
      // стрелка — SVG, а не «▾»: в шрифтах страниц символа нет, и он падал в точку
      '<span class="ui-select-chev" aria-hidden="true"><svg width="12" height="12" viewBox="0 0 12 12"><path d="M3 4.5l3 3 3-3" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg></span></button>' +
    '<div class="ui-select-pop" role="listbox" hidden>' +
      (search ? '<div class="ui-select-search"><input type="text" inputmode="search" class="ui-select-q" autocomplete="off" ' +
        'autocapitalize="off" spellcheck="false" enterkeyhint="done" aria-label="Найти в списке" placeholder="' + attr(o.placeholder || "Начните вводить…") + '">' +
        // крестик — закрыть список одним касанием (на телефоне иначе: убрать
        // клавиатуру, потом тапнуть мимо шторки)
        '<button type="button" class="ui-select-close" aria-label="Закрыть список" title="Закрыть">✕</button></div>' : '') +
      opts.map(function(x){
        return '<button type="button" class="ui-opt" role="option" aria-selected="' + (x.selected ? "true" : "false") +
          '" data-value="' + attr(x.value) + '" data-q="' + attr(uiSelNorm((x.t || "") + " " + (x.s || ""))) + '">' +
          '<span class="ui-opt-check" aria-hidden="true">' + (x.selected ? "✓" : "") + '</span>' +
          '<span class="ui-opt-txt"><span class="ui-opt-t">' + esc(x.t || "") + '</span>' +
            (x.s ? '<span class="ui-opt-s">' + esc(x.s) + '</span>' : '') + '</span>' +
          '<span class="ui-opt-aside">' + esc(x.aside || "") + '</span></button>';
      }).join("") +
      (search ? '<div class="ui-select-none" hidden>Ничего не найдено</div>' : '') +
    '</div></div>';
}
function uiSelectItems(root){
  return Array.prototype.slice.call(root.querySelectorAll(".ui-opt")).filter(function(x){ return !x.hidden; });
}
/* Раскрытую часть — по экрану у кнопки: ниже, а если там тесно — выше. */
function uiSelectPlace(root){
  var btn = root.querySelector(".ui-select-btn"), pop = root.querySelector(".ui-select-pop");
  if (!btn || !pop || pop.hidden) return;
  var vw = window.innerWidth, vh = window.innerHeight;
  if (root.classList.contains("combo")){
    // длинный список в форме — ПОВЕРХ содержимого, поле не растёт и соседи не двигаются:
    // раскрывается от верха поля вниз (не влезает — от низа поля вверх), по экрану (fixed) —
    // не режется окном формы
    root.classList.remove("sheet");
    var cr = btn.getBoundingClientRect(), ce = 8, cw = Math.min(cr.width, vw - 2 * ce);
    var cl = Math.min(Math.max(ce, cr.left), vw - ce - cw);
    var cbelow = vh - cr.top - ce, cabove = cr.bottom - ce, cwant = Math.min(pop.scrollHeight, 300);
    var cup = cbelow < Math.min(cwant, 190) && cabove > cbelow;
    var cmax = Math.max(80, Math.min(300, cup ? cabove : cbelow));
    pop.style.cssText = "position:fixed; right:auto; left:" + cl + "px; width:" + cw + "px; max-height:" + cmax + "px; " +
      (cup ? "top:auto; bottom:" + (vh - cr.bottom) + "px;" : "bottom:auto; top:" + cr.top + "px;");
    return;
  }
  if (root.classList.contains("search") && vw <= 600){       // телефон: шторка у верха
    root.classList.add("sheet");
    pop.style.cssText = "";
    return;
  }
  root.classList.remove("sheet");
  var r = btn.getBoundingClientRect(), gap = 6, edge = 8;
  var w = Math.min(Math.max(r.width, 240), vw - 2 * edge);
  // правый край списка за правым краем ближайшего окна / карточки (или экрана) — список по правому краю кнопки
  var box = root.closest(".ui-card, .ui-modal-body, .ui-modal"), bxr = box ? box.getBoundingClientRect() : null;
  var rightLim = Math.min(vw - edge, bxr ? bxr.right : vw - edge);
  var left = r.left + w > rightLim ? r.right - w : r.left;
  left = Math.min(Math.max(edge, left), vw - edge - w);
  // в окне формы список не заходит на шапку и кнопки окна — только поле полей
  var area = root.closest(".ui-modal-body"), ar = area ? area.getBoundingClientRect() : null;
  var topLim = ar ? Math.max(0, ar.top) : 0, botLim = ar ? Math.min(vh, ar.bottom) : vh;
  var below = botLim - r.bottom - gap - (ar ? 0 : edge), above = r.top - topLim - gap - (ar ? 0 : edge);
  var want = Math.min(pop.scrollHeight, 340);
  // вниз — пока снизу помещается хотя бы ~5 строк (дальше список прокручивается
  // внутри): раскрытие вверх закрывает подпись своего же поля
  var up = below < Math.min(want, 190) && above > below;
  var maxH = Math.max(ar ? 80 : 120, Math.min(340, up ? above : below));
  pop.style.cssText = "position:fixed; right:auto; left:" + left + "px; width:" + w + "px; max-height:" + maxH + "px; " +
    (up ? "top:auto; bottom:" + (vh - r.top + gap) + "px;" : "bottom:auto; top:" + (r.bottom + gap) + "px;");
}
function uiSelectFilter(root, q){
  q = uiSelNorm(q).trim();
  var any = false, all = root.querySelectorAll(".ui-opt");
  for (var i = 0; i < all.length; i++){
    var hit = !q || all[i].getAttribute("data-q").indexOf(q) !== -1;
    all[i].hidden = !hit; if (hit) any = true;
  }
  var none = root.querySelector(".ui-select-none");
  if (none) none.hidden = any;
}
/* Фокус без прокрутки страницы и подкрутка ТОЛЬКО внутри списка. focus() и
   scrollIntoView прокручивают всех предков вплоть до страницы — список,
   открытый в окне отчёта, тянул окно вверх, экран мигал и дёргался
   (вьюер, версия отчёта, 2026-10-06). */
function uiSelFocus(el){
  if (!el) return;
  try { el.focus({ preventScroll: true }); } catch(e){ el.focus(); }
  var pop = el.closest && el.closest(".ui-select-pop");
  if (pop && el !== pop) uiSelReveal(pop, el);
}
function uiSelReveal(pop, el){
  var head = pop.querySelector(".ui-select-search"), hh = head ? head.offsetHeight : 0;
  var top = el.offsetTop, bot = top + el.offsetHeight;
  if (top - hh < pop.scrollTop) pop.scrollTop = Math.max(0, top - hh);
  else if (bot > pop.scrollTop + pop.clientHeight) pop.scrollTop = bot - pop.clientHeight;
}
function uiSelectSet(root, open, focus){
  if (!root) return;
  var btn = root.querySelector(".ui-select-btn"), pop = root.querySelector(".ui-select-pop");
  if (!btn || !pop) return;
  btn.setAttribute("aria-expanded", open ? "true" : "false");
  pop.hidden = !open;
  root.classList.toggle("open", !!open);
  var q = root.querySelector(".ui-select-q");
  if (open){
    if (q){ q.value = ""; uiSelectFilter(root, ""); }
    uiSelectPlace(root);
    var sel = pop.querySelector('.ui-opt[aria-selected="true"]') || pop.querySelector(".ui-opt");
    if (sel) uiSelReveal(pop, sel);
    if (q) uiSelFocus(q);                  // длинный список: сразу печатать
    else if (focus && sel) uiSelFocus(sel);
    // поле с подсказками в окне формы — к верху полей, чтобы подсказки были
    // видны над клавиатурой телефона (и после того, как она выехала)
    var area = root.classList.contains("combo") && window.matchMedia("(pointer:coarse)").matches && root.closest(".ui-modal-body");
    if (area){
      var fieldEl = root.closest(".ui-field, label") || root;   // поле вместе с подписью
      var lift = function(){ area.scrollTop += fieldEl.getBoundingClientRect().top - area.getBoundingClientRect().top - 8; };
      setTimeout(lift, 0); setTimeout(lift, 350);
    }
  } else {
    pop.style.cssText = ""; root.classList.remove("sheet");
    if (focus) uiSelFocus(btn);
  }
}
function uiSelectCloseAll(except){
  var all = document.querySelectorAll(".ui-select");
  for (var i = 0; i < all.length; i++)
    if (all[i] !== except && all[i].querySelector('.ui-select-btn[aria-expanded="true"]')) uiSelectSet(all[i], false);
}
function uiSelectPick(opt){
  var root = opt.closest(".ui-select");
  var value = opt.getAttribute("data-value");
  // подпись и галочка — на месте: формы не перерисовываются
  var all = root.querySelectorAll(".ui-opt");
  for (var i = 0; i < all.length; i++){
    var on = all[i] === opt;
    all[i].setAttribute("aria-selected", on ? "true" : "false");
    all[i].querySelector(".ui-opt-check").textContent = on ? "✓" : "";
  }
  var ot = opt.querySelector(".ui-opt-t"), os = opt.querySelector(".ui-opt-s");
  root.querySelector(".ui-select-t").textContent = ot ? ot.textContent : "";
  var bs = root.querySelector(".ui-select-s");
  bs.textContent = os ? os.textContent : ""; bs.hidden = !os;
  uiSelectSet(root, false, true);
  var hid = root.querySelector('input[type="hidden"]');
  var changed = hid && hid.value !== value;
  if (hid) hid.value = value;
  root.dispatchEvent(new CustomEvent("ui-select", { bubbles: true,
    detail: { name: root.getAttribute("data-ui-select"), value: value } }));
  // как у нативного <select>: change только при смене значения
  if (changed) hid.dispatchEvent(new Event("change", { bubbles: true }));
}
document.addEventListener("click", function(ev){
  var t = ev.target;
  var opt = t.closest ? t.closest(".ui-select .ui-opt") : null;
  if (opt){ ev.preventDefault(); uiSelectPick(opt); return; }
  var cl = t.closest ? t.closest(".ui-select-close") : null;
  if (cl){ ev.preventDefault(); uiSelectSet(cl.closest(".ui-select"), false, true); return; }
  // клик по полю поиска/пустому месту раскрытой части внутри <label> формы
  // не должен «нажать» кнопку списка (активация label) и закрыть его
  if (t.closest && t.closest(".ui-select-pop")){ if (!t.closest(".ui-select-q")) ev.preventDefault(); return; }
  var btn = t.closest ? t.closest(".ui-select-btn") : null;
  if (btn){
    ev.preventDefault();                   // кнопка внутри <label> формы — без повторного клика
    var root = btn.closest(".ui-select");
    var open = btn.getAttribute("aria-expanded") !== "true";
    uiSelectCloseAll(root);
    // мышью — фокус остаётся на кнопке; с клавиатуры (detail 0) — в список
    uiSelectSet(root, open, open && ev.detail === 0);
    return;
  }
  if (!(t.closest && t.closest(".ui-select"))) uiSelectCloseAll(null);
});
document.addEventListener("input", function(ev){
  var q = ev.target;
  if (!q.classList || !q.classList.contains("ui-select-q")) return;
  ev.stopPropagation();                    // поиск по списку — не поиск страницы
  uiSelectFilter(q.closest(".ui-select"), q.value);
}, true);
document.addEventListener("keydown", function(ev){
  var root = ev.target.closest ? ev.target.closest(".ui-select") : null;
  // Esc при открытом списке закрывает список, где бы ни был фокус: Safari не
  // переводит фокус на кнопку по щелчку мышью, и Esc приходил бы «с body» —
  // а страница на том же document закрыла бы окно формы целиком
  if (!root && ev.key === "Escape"){
    var ob = document.querySelector('.ui-select-btn[aria-expanded="true"]');
    if (ob){ ev.preventDefault(); ev.stopImmediatePropagation(); uiSelectSet(ob.closest(".ui-select"), false, true); }
    return;
  }
  if (!root) return;
  var btn = root.querySelector(".ui-select-btn");
  var open = btn.getAttribute("aria-expanded") === "true";
  var q = root.querySelector(".ui-select-q");
  var items = uiSelectItems(root);
  var i = items.indexOf(document.activeElement);
  // Esc закрывает только список: страницы ловят Esc на том же document
  // (закрыть окно формы) — stopImmediatePropagation гасит и их обработчики
  if (ev.key === "Escape" && open){ ev.preventDefault(); ev.stopImmediatePropagation(); uiSelectSet(root, false, true); }
  else if (ev.key === "Enter" && open && ev.target === q){
    ev.preventDefault();                   // не отправлять форму
    if (items[0]) uiSelectPick(items[0]);
  }
  else if (ev.key === "ArrowDown" || ev.key === "ArrowUp"){
    ev.preventDefault();
    if (!open){ uiSelectCloseAll(root); uiSelectSet(root, true, true); return; }
    if (ev.target === q){ if (ev.key === "ArrowDown" && items[0]) uiSelFocus(items[0]); return; }
    if (ev.key === "ArrowUp" && i <= 0 && q){ uiSelFocus(q); return; }
    var n = ev.key === "ArrowDown" ? Math.min(items.length - 1, i + 1) : Math.max(0, i - 1);
    if (items[n]) uiSelFocus(items[n]);
  }
  else if ((ev.key === "Home" || ev.key === "End") && open && items.length && ev.target !== q){
    ev.preventDefault(); uiSelFocus(items[ev.key === "Home" ? 0 : items.length - 1]);
  }
  else if (ev.key === "Tab" && open) uiSelectSet(root, false);
  else if (!open && q && ev.target === btn && ev.key.length === 1 && !ev.ctrlKey && !ev.metaKey && !ev.altKey){
    // буква на закрытом длинном списке — открыть с поиском по ней
    ev.preventDefault();
    uiSelectCloseAll(root); uiSelectSet(root, true);
    q.value = ev.key; uiSelectFilter(root, q.value);
  }
  else if (open && q && ev.target !== q && ev.key.length === 1 && !ev.ctrlKey && !ev.metaKey && !ev.altKey){
    uiSelFocus(q);                         // печать со стрелок по списку — в поиск
  }
});
/* открытый список держится у кнопки при прокрутке и смене размера окна */
function uiSelectReplaceOpen(ev){
  if (ev && ev.target && ev.target.classList && ev.target.classList.contains("ui-select-pop")) return;
  var open = document.querySelectorAll('.ui-select-btn[aria-expanded="true"]');
  for (var k = 0; k < open.length; k++) uiSelectPlace(open[k].closest(".ui-select"));
}
window.addEventListener("scroll", uiSelectReplaceOpen, true);
window.addEventListener("resize", uiSelectReplaceOpen);

/* ── v1.45.0: значок (i) с подсказкой ───────────────────────────────────────
   uiInfoHTML(text, {html, label}) → разметка .ui-info. text экранируется; o.html = true —
   доверенный HTML страницы (абзацы <p>). Открытие касанием/кликом — делегат ниже (класс
   .open, закрытие — касанием мимо или Esc); наведение — CSS. uiInfoPlace сдвигает
   подсказку, чтобы край экрана её не резал. */
function uiInfoHTML(text, o){
  o = o || {};
  return '<span class="ui-info"><button type="button" class="ui-info-btn" data-ui-info aria-expanded="false" aria-label="' +
    esc(o.label || "Пояснение") + '">i</button><span class="ui-info-pop" role="tooltip">' + (o.html ? text : esc(text)) + '</span></span>';
}
/* Сдвиг подсказки --ui-info-dx: чтобы край экрана её не резал. Считается заранее (uiInfoPlaceAll, как только значок
   попал в страницу), а не при наведении: WebKit, увидев подсказку хоть на миг без сдвига у правого края, оставляет
   страницу широкой, даже когда подсказку сдвинули или скрыли. Скрытая подсказка — display:none; ширину снимаем вне
   раскладки страницы (fixed в углу, без переходов). */
function uiInfoPlaceBoxes(boxes){
  var items = [], i, pop, box, prev;
  for (i = 0; i < boxes.length; i++){
    box = boxes[i]; pop = box.querySelector(".ui-info-pop");
    if (!pop || !box.getClientRects().length) continue;   /* не в раскладке (закрытая вкладка/окно) — позже, при наведении */
    items.push({ box: box, pop: pop, shown: getComputedStyle(pop).display !== "none",
      prev: parseFloat(pop.style.getPropertyValue("--ui-info-dx")) || 0 });
  }
  var vw = document.documentElement.clientWidth;
  for (i = 0; i < items.length; i++){
    var it = items[i];
    if (it.shown){ var r0 = it.pop.getBoundingClientRect(); it.w = r0.width; it.left = r0.left - it.prev; }
    else { it.left = it.box.getBoundingClientRect().left - 8; }   /* как left:-8px в CSS */
  }
  for (i = 0; i < items.length; i++) if (!items[i].shown){
    pop = items[i].pop; pop.style.transition = "none"; pop.style.position = "fixed"; pop.style.left = "0"; pop.style.top = "0"; pop.style.display = "block";
  }
  for (i = 0; i < items.length; i++) if (!items[i].shown) items[i].w = items[i].pop.getBoundingClientRect().width;
  for (i = 0; i < items.length; i++) if (!items[i].shown){
    pop = items[i].pop; pop.style.display = ""; pop.style.position = ""; pop.style.left = ""; pop.style.top = "";
  }
  if (items.length) void items[0].pop.offsetWidth;
  for (i = 0; i < items.length; i++){
    it = items[i]; it.pop.style.transition = "";
    var dx = 0;
    if (it.left + it.w > vw - 12) dx = vw - 12 - (it.left + it.w);
    if (it.left + dx < 12) dx = 12 - it.left;
    it.pop.style.setProperty("--ui-info-dx", Math.round(dx) + "px");
    it.box.setAttribute("data-ui-placed", "1");
  }
}
function uiInfoPlace(box){ if (box) uiInfoPlaceBoxes([box]); }
var uiInfoRaf = 0;
function uiInfoPlaceAll(){
  uiInfoRaf = 0;
  uiInfoPlaceBoxes(document.querySelectorAll(".ui-info:not([data-ui-placed])"));
}
function uiInfoSchedule(){ if (!uiInfoRaf) uiInfoRaf = requestAnimationFrame(uiInfoPlaceAll); }
window.addEventListener("resize", function(){
  var all = document.querySelectorAll(".ui-info[data-ui-placed]");
  for (var i = 0; i < all.length; i++) all[i].removeAttribute("data-ui-placed");
  uiInfoSchedule();
});
if (window.MutationObserver) new MutationObserver(function(ms){
  for (var i = 0; i < ms.length; i++) if (ms[i].addedNodes.length){ uiInfoSchedule(); return; }
}).observe(document.documentElement, { childList: true, subtree: true });
uiInfoSchedule();
function uiInfoCloseAll(except){
  var open = document.querySelectorAll(".ui-info.open");
  for (var i = 0; i < open.length; i++) if (open[i] !== except){ open[i].classList.remove("open"); var b = open[i].querySelector("[data-ui-info]"); if (b) b.setAttribute("aria-expanded", "false"); }
}
document.addEventListener("click", function(ev){
  var t = ev.target, btn = t.closest ? t.closest("[data-ui-info]") : null;
  if (btn){
    ev.preventDefault(); ev.stopPropagation();
    var box = btn.closest(".ui-info"), on = !box.classList.contains("open");
    uiInfoCloseAll(box);
    box.classList.toggle("open", on); btn.setAttribute("aria-expanded", on ? "true" : "false");
    if (on) uiInfoPlace(box);
    return;
  }
  if (!(t.closest && t.closest(".ui-info-pop"))) uiInfoCloseAll(null);
}, true);
document.addEventListener("mouseover", function(ev){
  var box = ev.target.closest ? ev.target.closest(".ui-info") : null;
  if (box && !box.classList.contains("open")) uiInfoPlace(box);
});
document.addEventListener("keydown", function(ev){ if (ev.key === "Escape" && document.querySelector(".ui-info.open")){ ev.preventDefault(); uiInfoCloseAll(null); } });


/* ═══ uiTimeChartHTML/uiTimeChartMount: график показателя во времени (1.53.0) ═══
   Ось X — дата: пауза в два года и пауза в месяц выглядят по-разному, иначе
   график врёт о темпе изменений. Режимы:
   • вся история (по умолчанию) — всё во всю ширину, как раньше; если в день
     меньше 9 px, несколько измерений одной недели сводятся в медиану с усиком
     min–max (последнее измерение — всегда само по себе);
   • полгода — только у длинной плотной истории: замеров (дат) больше opts.many (20)
     и в окно не влезают. На экране ~полгода (opts.window дней), прокрутка влево —
     раньше, открыт на последних замерах (uiTimeChartMount); масштаб в пикселях —
     на телефоне меньше месяцев, зато подписи читаемы. Такой истории даётся
     переключатель «полгода · вся история», а «вся история» у неё сводит замеры
     по месяцам (медиана с усиком), чтобы влезть в экран без прокрутки;
   • разрыв: в обоих режимах плотной истории пауза без замеров длиннее opts.gap
     дней (75) сжата в разрыв с подписью длительности и бледным пунктиром — иначе
     экраны пустоты.
   Короткой истории переключатель не показывается — лишняя кнопка. Выбор режима и
   прокрутка помнятся по opts.key (новый просмотр — новый ключ); переключение
   перерисовывает график на месте, страница ничего не делает.
   opts: { key; series: [{ pts:[{date, value, note?}], label?, lastFill? }] — до двух,
             вторая пунктиром (давление верхнее/нижнее);
           bands: [{low, high}] — зоны нормы; unit; fmt(v); window; gap; many }.
   Цвет — --sec-acc раздела (или opts.color). Страница после вставки в DOM
   вызывает uiTimeChartMount(root). */
var UI_TC_SCROLL = {}, UI_TC_MODE = {}, UI_TC_OPTS = {};
function uiTimeChartHTML(o){
  // W0 — ширина блока в px (uiTimeChartMount подставляет настоящую через o._w):
  // рисуем 1:1, и подписи на телефоне те же 13px, а не ужатые вдвое
  var W0 = Math.max(260, o._w || 640), H = 240, L = 10, R = 10, T = 18, B = 40, PW = W0 - L - R, PH = H - T - B;
  var DAY = 864e5, WIN = o.window || 183, GAPD = o.gap || 75, MANY = o.many || 20, BRK = 64, MINPX = 9;
  var unit = o.unit ? " " + o.unit : "";
  var fmt = o.fmt || function(v){ return String(Math.round(v * 1000) / 1000); };
  var ms = function(d){ return new Date(d + "T00:00:00").getTime(); };
  var rr = function(n){ return Math.round(n * 10) / 10; };
  var num = function(a, b){ return a - b; };
  var uniq = function(a){ a.sort(num); return a.filter(function(t, i){ return i === 0 || t !== a[i - 1]; }); };
  var ser = (o.series || []).map(function(s){
    return { label: s.label || "", lastFill: s.lastFill || "var(--tc)",
      pts: (s.pts || []).filter(function(p){ return typeof p.value === "number"; })
        .map(function(p){ return { t: ms(p.date), date: p.date, value: p.value, note: p.note || "" }; })
        .sort(function(a, b){ return a.t - b.t; }) };
  }).filter(function(s){ return s.pts.length; });
  if (!ser.length) return "";
  if (o.key) UI_TC_OPTS[o.key] = o;

  // Раскладка по опорным датам: пауза до GAPD дней — пропорционально (ppd px
  // в день), длиннее — разрыв шириной brkW.
  var lay = function(ts, ppd, brkW){
    var xs = [0], brk = [];
    for (var i = 1; i < ts.length; i++){
      var d = (ts[i] - ts[i - 1]) / DAY;
      if (d > GAPD){ brk.push({ x: xs[i - 1] + brkW / 2, days: d }); xs.push(xs[i - 1] + brkW); }
      else xs.push(xs[i - 1] + d * ppd);
    }
    return { ts: ts, xs: xs, brk: brk, w: xs[xs.length - 1] };
  };
  // сведение в медиану с усиком: по неделе или по месяцу; последнее — само по себе
  var weekKey = function(t){ var dt = new Date(t); return new Date(dt.getFullYear(), dt.getMonth(), dt.getDate() - (dt.getDay() + 6) % 7).getTime(); };
  var monthKey = function(t){ var dt = new Date(t); return dt.getFullYear() * 12 + dt.getMonth(); };
  var bucket = function(pts, keyOf){
    var last = pts[pts.length - 1], groups = [], byKey = {};
    pts.slice(0, -1).forEach(function(p){
      var k = keyOf(p.t);
      if (!byKey[k]){ byKey[k] = []; groups.push(byKey[k]); }
      byKey[k].push(p);
    });
    return groups.map(function(g){
      if (g.length < 2) return g[0];
      var v = g.map(function(p){ return p.value; }).sort(num), m = v.length >> 1;
      return { t: (g[0].t + g[g.length - 1].t) / 2, date: g[0].date, date2: g[g.length - 1].date,
               value: v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2, min: v[0], max: v[v.length - 1], n: g.length };
    }).concat([last]);
  };

  var raw = [];
  ser.forEach(function(s){ s.pts.forEach(function(p){ raw.push(p.t); }); });
  raw = uniq(raw);
  var t0 = raw[0], tN = raw[raw.length - 1], span = (tN - t0) / DAY;
  var win = lay(raw, PW / WIN, BRK);
  var dense = raw.length > MANY && span > WIN && win.w > PW;
  var mode = !dense ? "fit" : (o.key && UI_TC_MODE[o.key] === "all" ? "all" : "win");

  var A, cw = PW, bucketBy = "";
  if (mode === "win"){
    A = win; cw = win.w;
    if (PW / WIN < MINPX) bucketBy = "неделя";
    ser.forEach(function(s){ s.marks = bucketBy ? bucket(s.pts, weekKey) : s.pts; });
  } else if (mode === "all"){
    bucketBy = "месяц";
    ser.forEach(function(s){ s.marks = bucket(s.pts, monthKey); });
    var mt = [];
    ser.forEach(function(s){ s.marks.forEach(function(p){ mt.push(p.t); }); });
    mt = uniq(mt);
    var probe = lay(mt, 1, 0), nb = probe.brk.length;    // probe.w — дни без разрывов
    var brkW = probe.w ? Math.min(BRK, PW * 0.4 / Math.max(nb, 1)) : PW / Math.max(nb, 1);
    A = lay(mt, probe.w ? (PW - nb * brkW) / probe.w : 0, brkW);
  } else {
    var pxDay = PW / Math.max(span, 1);
    if (pxDay < MINPX) bucketBy = "неделя";
    ser.forEach(function(s){ s.marks = bucketBy ? bucket(s.pts, weekKey) : s.pts; });
  }
  var anyBucket = bucketBy && ser.some(function(s){ return s.marks.some(function(p){ return p.n; }); });
  var brk = A ? A.brk : [];
  var xAt = A
    ? function(t){                      // кусочно-линейно между опорными датами
        var ts = A.ts, xs = A.xs;
        for (var k = 0; k < ts.length - 1 && ts[k + 1] < t; k++);
        if (k >= ts.length - 1 || t <= ts[k]) return xs[Math.min(k, xs.length - 1)];
        return xs[k] + (t - ts[k]) / (ts[k + 1] - ts[k]) * (xs[k + 1] - xs[k]);
      }
    : function(t){ return raw.length === 1 ? PW / 2 : (t - t0) / (tN - t0) * PW; };
  var scroll = mode === "win";

  // ось Y — общая для всех серий и зон нормы, одна на всю прокрутку
  var bands = (o.bands || []).filter(Boolean), vals = [];
  ser.forEach(function(s){ s.pts.forEach(function(p){ vals.push(p.value); }); });
  bands.forEach(function(b){ vals.push(b.low, b.high); });
  var mn = Math.min.apply(null, vals), mx = Math.max.apply(null, vals);
  var pad = (mx - mn) * 0.14 || 1, lo = mn - pad, rng = (mx + pad - lo) || 1;
  var X = function(t){ return rr(L + xAt(t)); };
  var Y = function(v){ return rr(T + (1 - (v - lo) / rng) * PH); };
  var VW = rr(cw + L + R);

  var svg = "";
  bands.forEach(function(b){
    svg += '<rect class="band" x="' + L + '" y="' + Y(b.high) + '" width="' + rr(cw) + '" height="' + rr(Y(b.low) - Y(b.high)) + '"></rect>' +
      '<line class="band-edge" x1="' + L + '" x2="' + rr(L + cw) + '" y1="' + Y(b.high) + '" y2="' + Y(b.high) + '"></line>' +
      '<line class="band-edge" x1="' + L + '" x2="' + rr(L + cw) + '" y1="' + Y(b.low) + '" y2="' + Y(b.low) + '"></line>';
  });
  var brkRow = [-1e9, -1e9];   // подписи соседних разрывов — в два ряда, третья тесная не пишется
  brk.forEach(function(b){
    var bx = rr(L + b.x), row = bx - brkRow[0] >= 40 ? 0 : (bx - brkRow[1] >= 40 ? 1 : -1);
    if (row < 0) return;
    brkRow[row] = bx;
    // коротко, чтобы соседние разрывы не слипались: «11 мес», «1,4 г»
    var mo = Math.round(b.days / 30.44);
    var txt = mo < 12 ? mo + " мес" : String(Math.round(mo / 1.2) / 10).replace(".", ",") + " г";
    svg += '<text class="brk" x="' + bx + '" y="' + (T + PH - 4 - row * 15) + '" text-anchor="middle">' + esc(txt) + '</text>';
  });
  ser.forEach(function(s, si){
    var main = "", gaps = "", prev = null;
    s.marks.forEach(function(p){
      var xy = X(p.t) + " " + Y(p.value);
      if (prev && brk.length && (p.t - prev.t) / DAY > GAPD){ gaps += "M" + X(prev.t) + " " + Y(prev.value) + " L" + xy; main += " M" + xy; }
      else main += (main ? " L" : "M") + xy;
      prev = p;
    });
    var cls = si ? " alt" : "";
    if (gaps) svg += '<path class="gap" d="' + gaps + '"></path>';
    svg += '<path class="ln' + cls + '" d="' + main + '"></path>';
    var pre = s.label ? s.label + " · " : "";
    s.marks.forEach(function(p, k){
      var lastP = k === s.marks.length - 1, cx = X(p.t), title;
      if (p.n){
        svg += '<line class="wh" x1="' + cx + '" x2="' + cx + '" y1="' + Y(p.max) + '" y2="' + Y(p.min) + '"></line>';
        title = pre + "медиана " + fmt(p.value) + unit + " (" + fmt(p.min) + "–" + fmt(p.max) + ") · " + p.n + " изм. · " + uiDateNum(p.date) + "–" + uiDateNum(p.date2);
      } else title = pre + fmt(p.value) + unit + " · " + uiDateNum(p.date) + (p.note ? " · " + p.note : "");
      svg += '<circle class="pt' + cls + (lastP ? " last" : "") + '" cx="' + cx + '" cy="' + Y(p.value) + '" r="' + (lastP ? 5.5 : (si ? 3.5 : 4)) + '"' +
        (lastP ? ' style="fill:' + esc(s.lastFill) + '"' : "") + '><title>' + esc(title) + '</title></circle>';
    });
    // подпись последнего значения: первая серия — над точкой, вторая — под ней
    var lp = s.marks[s.marks.length - 1], ly = Y(lp.value), lx = X(lp.t);
    var above = si === 0 ? ly >= T + 24 : ly > H - B - 6;
    svg += '<text class="lv" x="' + lx + '" y="' + rr(above ? ly - 12 : ly + 22) + '" text-anchor="' + (lx > VW - 70 ? "end" : (lx < 40 ? "start" : "middle")) + '">' + esc(fmt(lp.value)) + '</text>';
  });

  // подписи дат по точкам: середину прореживаем, месяц не повторяем, крайние
  // прижаты к краям (при middle «янв 2021» обрезался бы границей SVG)
  var marksT = [];
  ser.forEach(function(s){ s.marks.forEach(function(p){ marksT.push(p.t); }); });
  marksT.sort(num);
  var GAP = 64, EDGE = 88, lastX = -1e9, lastTxt = "", xF = X(marksT[0]), xL = X(marksT[marksT.length - 1]);
  marksT.forEach(function(t, k){
    var dt = new Date(t), px = X(t), edge = k === 0 || k === marksT.length - 1;
    var txt = UI_MONTHS_SHORT[dt.getMonth()] + " " + dt.getFullYear();
    if (!edge && (px - lastX < GAP || px - xF < EDGE || xL - px < EDGE || txt === lastTxt)) return;
    svg += '<text class="ax" x="' + px + '" y="231" text-anchor="' + (marksT.length === 1 ? "middle" : (k === 0 ? "start" : (edge ? "end" : "middle"))) + '">' + esc(txt) + '</text>';
    lastX = px; lastTxt = txt;
  });

  var lg = (bands.length ? '<span><i class="ui-tchart-sw band"></i>зона нормы</span>' : "") +
    ser.map(function(s, si){ return '<span><i class="ui-tchart-sw' + (si ? " alt" : "") + '"></i>' + esc(s.label || "динамика значений") + '</span>'; }).join("") +
    (anyBucket ? '<span><i class="ui-tchart-sw wh"></i>' + bucketBy + ': медиана и разброс</span>' : "");
  // переключатель — только у плотной истории (у короткой и так видно всё)
  var seg = dense && o.key ? '<div class="ui-seg sm ui-tchart-mode" role="group" aria-label="Период графика">' +
      [["win", "полгода"], ["all", "вся история"]].map(function(x){
        return '<button type="button" class="ui-seg-btn" data-tc-mode="' + x[0] + '" data-tc-key="' + esc(o.key) + '" aria-pressed="' + (x[0] === mode) + '">' + x[1] + '</button>';
      }).join("") + '</div>' : "";
  return '<div class="ui-tchart"' + (o.color ? ' style="--tc:' + esc(o.color) + '"' : "") + '>' +
    (seg ? '<div class="ui-tchart-top">' + seg + (scroll ? '<span class="ui-tchart-more">← раньше</span>' : "") + '</div>' : "") +
    '<div class="ui-tchart-lg">' + lg + '</div>' +
    '<div class="ui-tchart-sc' + (scroll ? " wide" : "") + '"' + (o.key ? ' data-tc="' + esc(o.key) + '"' : "") + '>' +
      // широкий — в пикселях: блок шириной W0 показывает ровно окно
      '<svg viewBox="0 0 ' + VW + ' ' + H + '" style="width:' + (scroll ? Math.round(VW * (o._w ? 1 : 0.94)) + 'px' : '100%') + '">' + svg + '</svg></div></div>';
}
// После вставки в DOM: перерисовать под настоящую ширину блока (график с key),
// прокрутку — впервые к последним измерениям, после перерисовки — где была.
function uiTimeChartMount(root){
  [].forEach.call((root || document).querySelectorAll(".ui-tchart-sc[data-tc]"), function(el){
    var k = el.getAttribute("data-tc"), o = UI_TC_OPTS[k], box = el.closest(".ui-tchart");
    var w = el.clientWidth;
    if (!o || !box || w < 200 || Math.abs(w - (o._w || 0)) < 2) return;
    o._w = w;
    box.parentNode.replaceChild(uiNode(uiTimeChartHTML(o)), box);
  });
  [].forEach.call((root || document).querySelectorAll(".ui-tchart-sc.wide"), function(el){
    var k = el.getAttribute("data-tc"), has = k && Object.prototype.hasOwnProperty.call(UI_TC_SCROLL, k);
    el.scrollLeft = has ? UI_TC_SCROLL[k] : el.scrollWidth;
    el.onscroll = function(){ if (k) UI_TC_SCROLL[k] = el.scrollLeft; };
  });
}
// «полгода · вся история»: график перерисовывается на месте по сохранённым opts
document.addEventListener("click", function(ev){
  var b = ev.target.closest ? ev.target.closest("[data-tc-mode]") : null;
  if (!b) return;
  var k = b.getAttribute("data-tc-key"), o = UI_TC_OPTS[k], box = b.closest(".ui-tchart");
  if (!o || !box) return;
  UI_TC_MODE[k] = b.getAttribute("data-tc-mode");
  var nu = uiNode(uiTimeChartHTML(o)), host = box.parentNode;
  host.replaceChild(nu, box);
  uiTimeChartMount(host);
});


/* ═══ Офлайн (ui-kit 1.54.0, 2026-10-23) ═══════════════════════════════════════
   Фоновый скрипт /tools/sw.js (ядро — /tools/sw-offline.js) держит оболочку всех страниц и копию
   данных из списка «что держим офлайн» (CAB_KEEP там же). Страницы ничего не меняют: их fetch идёт
   как раньше — «сначала сеть», а без сети отвечает копия. Каждый ответ копией присылает сюда
   сообщение cab-offline — плашка «Нет связи — показаны данные от …» (одна на страницу, по самой
   старой копии). Только HTTPS (или localhost): по http://<IP>:8080 офлайна нет — как раньше.
   Под Playwright (navigator.webdriver) не регистрируется, если тест не попросил UI_OFFLINE_TEST:
   фоновый скрипт перехватывал бы запросы, которые подменяют прочие тесты. */
var uiOfflineOldest = null;
function uiOfflineFmt(iso){
  var d = new Date(iso);
  if (isNaN(d)) return "";
  var p = function(n){ return (n < 10 ? "0" : "") + n; };
  return p(d.getDate()) + "." + p(d.getMonth() + 1) + ", " + p(d.getHours()) + ":" + p(d.getMinutes());
}
/* Общее уведомление внизу (ui-kit 1.56.0) — одно на кабинет: «нет связи», «сохранено на телефоне»,
   «отправлено», «конфликт». uiNotice(text, kind, ms): kind — ok | err | warn | info; ms — сколько держать
   (0 — пока не закроют). Над «нет связи» (если оно на экране), над нижней навигацией телефона. */
function uiToastHTML(kind, text, closeAttr){
  return '<span class="ui-toast-dot" aria-hidden="true"></span><span class="ui-toast-txt">' + esc(text) + '</span>'
    + '<button type="button" class="ui-toast-x" ' + closeAttr + ' aria-label="Скрыть">✕</button>';
}
var uiNoticeT = null;
function uiNotice(text, kind, ms){
  var el = document.getElementById("ui-notice");
  if (!el){
    el = document.createElement("div");
    el.id = "ui-notice";
    el.setAttribute("role", "status");
    document.body.appendChild(el);
    el.addEventListener("click", function(ev){
      if (ev.target.closest && ev.target.closest("[data-notice-close]")) el.hidden = true;
    });
  }
  el.className = "ui-toast stack " + (kind || "info");
  el.innerHTML = uiToastHTML(kind, text, "data-notice-close");
  el.hidden = false;
  clearTimeout(uiNoticeT);
  if (ms !== 0) uiNoticeT = setTimeout(function(){ el.hidden = true; }, ms || 6000);
}
/* «Нет связи»: закрыли крестиком — до появления связи не возвращается, вместо неё маленькая метка
   «офлайн» в углу (нажать — развернуть). Флаг — sessionStorage, общий для страниц вкладки. */
var UI_OFF_KEY = "ui-offline-dismissed";
function uiOfflineShow(saved){
  if (saved && (!uiOfflineOldest || saved < uiOfflineOldest)) uiOfflineOldest = saved;
  if (uiOfflineOldest){ uiData.copy = uiOfflineFmt(uiOfflineOldest); uiFootStateRefresh(); }
  var el = document.getElementById("ui-offline");
  if (!el){
    el = document.createElement("div");
    el.id = "ui-offline";
    el.setAttribute("role", "status");
    document.body.appendChild(el);
    el.addEventListener("click", function(ev){
      if (ev.target.closest && ev.target.closest("[data-offline-close]")){
        try { sessionStorage.setItem(UI_OFF_KEY, "1"); } catch(e){}
        uiOfflineShow(null);
      } else if (el.classList.contains("chip")){
        try { sessionStorage.removeItem(UI_OFF_KEY); } catch(e){}
        uiOfflineShow(null);
      }
    });
  }
  var dismissed = false;
  try { dismissed = sessionStorage.getItem(UI_OFF_KEY) === "1"; } catch(e){}
  var when = uiOfflineOldest ? uiOfflineFmt(uiOfflineOldest) : "";
  if (dismissed){
    el.className = "ui-toast-chip";
    el.innerHTML = '<span class="ui-toast-dot" aria-hidden="true"></span>офлайн';
    el.title = "Нет связи с сервером — показаны данные с устройства" + (when ? " (от " + when + ")" : "");
    el.setAttribute("aria-label", el.title);
  } else {
    el.className = "ui-toast warn";
    el.innerHTML = uiToastHTML("warn", "Нет связи — показаны данные с устройства" + (when ? " (от " + when + ")" : "") + ".",
                              "data-offline-close");
    el.removeAttribute("title");
  }
  el.hidden = false;
  var st = document.getElementById("ui-stale");
  if (st) st.hidden = true;
  document.documentElement.classList.toggle("ui-offline-on", !dismissed);
}
/* Связь вернулась (событие online или первый ответ сервера через фоновый скрипт) — убрать всё офлайновое */
function uiOfflineGone(){
  try { sessionStorage.removeItem(UI_OFF_KEY); } catch(e){}
  uiOfflineOldest = null;
  uiData.copy = null; uiFootStateRefresh();
  var el = document.getElementById("ui-offline");
  if (el) el.hidden = true;
  document.documentElement.classList.remove("ui-offline-on");
}
/* Сообщения фонового скрипта → уведомления; «есть связь» → отправить очередь записей (ui-kit 1.56.0).
   Область фонового скрипта — весь сайт (scope "/", Caddy отдаёт sw.js с Service-Worker-Allowed: /):
   иначе страницы поездок /travel-planner/… без связи не открывались и их правки шли мимо очереди.
   Прежняя регистрация с областью /tools/ снимается — две регистрации одного скрипта не нужны. */
function uiOfflineFlush(){
  var sw = navigator.serviceWorker && navigator.serviceWorker.controller;
  if (!sw || navigator.onLine === false) return;
  try { sw.postMessage({ type: "cab-flush", auth: (typeof authToken === "function" && authToken()) || null }); } catch(e){}
}
/* Фоновый скрипт отдал прошлую версию страницы или ассета (сеть не ответила): один тост на страницу, кнопка
   перезагружает. Сообщение приходит дважды (сразу и через 3 с) — второе тост не множит. */
function uiStaleShow(){
  if (document.getElementById("ui-stale")) return;
  /* штатный офлайн: уже сказано «нет связи» (плашка или метка «офлайн») — прошлая версия ожидаема, второй тост не нужен */
  var off = document.getElementById("ui-offline");
  if (navigator.onLine === false || (off && !off.hidden)) return;
  var el = document.createElement("div");
  el.id = "ui-stale";
  el.setAttribute("role", "status");
  el.className = "ui-toast stack warn";
  el.innerHTML = '<span class="ui-toast-dot" aria-hidden="true"></span>'
    + '<span class="ui-toast-txt">Открыта прошлая версия страницы — сеть не ответила.</span>'
    + '<button type="button" class="ui-toast-act" data-stale-reload>Обновить</button>'
    + '<button type="button" class="ui-toast-x" data-stale-close aria-label="Скрыть">✕</button>';
  el.addEventListener("click", function(ev){
    var t = ev.target.closest ? ev.target : null;
    if (!t) return;
    if (t.closest("[data-stale-reload]")) location.reload();
    else if (t.closest("[data-stale-close]")) el.hidden = true;
  });
  document.body.appendChild(el);
}
function uiOfflineInit(){
  if (!("serviceWorker" in navigator) || !window.isSecureContext) return;
  if (navigator.webdriver && !window.UI_OFFLINE_TEST) return;
  navigator.serviceWorker.addEventListener("message", function(ev){
    var m = ev.data || {};
    if (m.type === "cab-offline") uiOfflineShow(m.saved || null);
    else if (m.type === "cab-online") uiOfflineGone();
    else if (m.type === "cab-queued") uiNotice("Нет связи — правка сохранена на телефоне и отправится сама, когда связь появится.", "warn");
    else if (m.type === "cab-sent") uiNotice(m.merged ? "Правки без связи отправлены и объединены с изменениями с другого устройства."
                                                       : "Правки без связи отправлены.", "ok");
    else if (m.type === "cab-conflict") uiNotice("Правка без связи не отправлена: «" + (m.name || m.path || "файл")
      + "» изменили с другого устройства в той же строке. Открой страницу и повтори правку.", "err", 0);
    else if (m.type === "cab-stale") uiStaleShow();
    else if (m.type === "cab-auth") uiNotice("Правки без связи ждут входа: пароль не принят — войди заново.", "err", 0);
  });
  window.addEventListener("online", function(){ uiOfflineFlush(); });
  document.addEventListener("visibilitychange", function(){ if (!document.hidden) uiOfflineFlush(); });
  var src = (document.currentScript && document.currentScript.src) || "";
  var swUrl = new URL("../sw.js", src || location.href).href;
  var go = function(){
    navigator.serviceWorker.register(swUrl, { scope: "/" }).then(function(){
      /* весь сайт — прежнюю регистрацию /tools/ того же скрипта снять */
      return navigator.serviceWorker.getRegistrations().then(function(rs){
        rs.forEach(function(r){
          var sc = new URL(r.scope).pathname, a = r.active || r.waiting || r.installing;
          if (sc !== "/" && a && /\/sw\.js(\?|$)/.test(a.scriptURL)) r.unregister();
        });
      });
    }, function(){
      /* сервер не разрешил область «весь сайт» (старый Caddyfile без Service-Worker-Allowed) — как раньше */
      return navigator.serviceWorker.register(swUrl, { scope: new URL("./", swUrl).pathname });
    }).then(function(){ return navigator.serviceWorker.ready; })
      .then(function(){ setTimeout(uiOfflineFlush, 500); }).catch(function(){});
  };
  if (document.readyState === "complete") go(); else window.addEventListener("load", go);
}
/* Прогрев копий (ui-kit 1.55.0): хаб — вход в приложение, и при связи он раз в UI_WARM_EVERY_MS по очереди
   открывает остальные страницы в невидимом фрейме. Каждая выполняет СВОЙ код загрузки, фоновый скрипт
   сохраняет ровно её запросы (вьюер заодно обновляет свою копию через /api/pv/sync) — копия «Еды» свежая,
   даже если неделю открывать только портфель. Адресов страниц здесь нет: поменяет страница, что грузит, —
   прогрев последует сам. Без фонового скрипта (http://IP, старый браузер) — не греет: копий всё равно нет.
   Страница во фрейме считается загруженной, когда 1,5 с не появляется новых запросов (не дольше 25 с). */
var UI_WARM_PAGES = ["food.html", "travel.html", "health.html", "money.html", "games.html",
                     "portfolio-integrated-viewer.html"];
var UI_WARM_EVERY_MS = 6 * 3600 * 1000;
function uiWarmOne(page){
  return new Promise(function(resolve){
    var f = document.createElement("iframe");
    f.setAttribute("aria-hidden", "true");
    f.tabIndex = -1;
    f.style.cssText = "position:fixed;left:-10000px;top:0;width:390px;height:844px;border:0;visibility:hidden;pointer-events:none";
    var started = Date.now(), last = -1, quiet = 0, timer = null;
    var finish = function(){ clearInterval(timer); f.remove(); resolve(page); };
    f.addEventListener("load", function(){
      timer = setInterval(function(){
        var n = 0;
        try { n = f.contentWindow.performance.getEntriesByType("resource").length; } catch(e){}
        quiet = n === last ? quiet + 250 : 0;
        last = n;
        if (quiet >= 1500 || Date.now() - started > 25000) finish();
      }, 250);
    });
    f.src = page + "?warm=1";
    document.body.appendChild(f);
  });
}
function uiOfflineWarm(force){
  var sw = navigator.serviceWorker;
  if (!sw || !sw.controller || navigator.onLine === false) return Promise.resolve(false);
  var now = Date.now(), last = 0;
  try { last = +localStorage.getItem("cab-warm-at") || 0; } catch(e){}
  if (!force && now - last < UI_WARM_EVERY_MS) return Promise.resolve(false);
  try { localStorage.setItem("cab-warm-at", String(now)); } catch(e){}   // до начала: вторая вкладка не дублирует
  /* связи не оказалось (телефон: navigator.onLine врёт, запросы висят) — прогрев не считается, при связи — заново */
  var offline = function(){ return document.documentElement.classList.contains("ui-offline-on"); };
  return UI_WARM_PAGES.reduce(function(p, page){ return p.then(function(){ return offline() ? page : uiWarmOne(page); }); },
                              Promise.resolve()).then(function(){
    if (!offline()) return true;
    try { localStorage.setItem("cab-warm-at", String(last)); } catch(e){}
    return false;
  });
}
uiOfflineInit();

/* ═══ Уведомления кабинета (ui-kit 1.57.0) ══════════════════════════════════
   Что и когда слать, решает сервер без Claude — hub-notify на NAS
   (tools/hosting/notify/notifier.py) за /api/push/* (пароль с любого IP).
   Раскладка (решение владельца 2026-10-26):
     · hub — «Уведомления» целиком: это устройство (включить, пробное, выключить,
       лишние подписки), тихий режим, все виды по разделам;
     · страница раздела — свои виды (вкл/выкл) и журнал «что приходило»; строка
       «это устройство · режим» и ссылка в hub.
   Виды с group "ahead" («Напоминать заранее») — отдельная группа: на странице раздела в правой колонке под
   «Этим устройством», в hub — подзаголовком в карточке раздела. На узком экране (≤860px) «Что присылать» и
   «Напоминать заранее» свёрнуты (общий .ui-fold, выбор помнит box.__uiPushOpen), на широком — раскрыты.
   Выключенные виды хранит сервер — переключатель в hub и на странице раздела
   один и тот же, разойтись им не из чего.
     uiPushMount(box, { section, onOpen, lead, after }) — нарисовать в box (и
       перерисовывать после действий). section: "portfolio" | "games" | null (hub).
       onOpen(url, { key }) — нажатие на строку журнала, key — ключ события сервера (вьюер — свой переход по #card/#tab;
       по умолчанию — переход на адрес). lead — HTML первой фразы, after — узел
       после блока (вьюер: «Как это работает»).
     uiPushOpen(section, opener) — то же в окне поверх страницы (как справка);
       кнопка шапки — uiTopHTML({ push: "games" | "all" }), адрес страницы с
       #notify открывает окно сразу.
   Подписка живёт на фоновом скрипте вьюера /tools/portfolio-sw.js (scope — вьюер):
   её уже держат устройства, поэтому и hub подписывает через него, не через sw.js. */
var UI_PUSH_API = "../api/push/";
var UI_PUSH_SW = { url: "portfolio-sw.js", scope: "./portfolio-integrated-viewer.html" };
var UI_PUSH_STATUS = { sent: "отправлено", quiet: "тихий режим — не отправлено", suppressed: "пропущено — такое уже было за неделю",
  failed: "не доставлено — повтор на следующей проверке", no_devices: "нет подписанных устройств", off: "выключено в настройках" };
var UI_PUSH_SECTION = { portfolio: "Портфель", games: "Игры" };
var _uiPushReg = null;
function uiPushEnv(){
  var ios = /iP(hone|ad|od)/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  var standalone = !!((window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) || navigator.standalone === true);
  var supported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  return { ios: ios, standalone: standalone, supported: supported };
}
function uiPushReg(){
  if (!uiPushEnv().supported || location.protocol === "file:") return Promise.resolve(null);
  if (!_uiPushReg) _uiPushReg = navigator.serviceWorker.register(UI_PUSH_SW.url, { scope: UI_PUSH_SW.scope })
    .catch(function(){ return null; });
  return _uiPushReg;
}
function uiPushApi(path, body){
  var init = body
    ? { method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" }, body: JSON.stringify(body), cache: "no-store" }
    : { headers: { Accept: "application/json" }, cache: "no-store" };
  return authFetch(UI_PUSH_API + path, init).then(function(r){
    return r.json().catch(function(){ return null; }).then(function(j){ return { status: r.status, j: j }; });
  }, function(){ return { status: 0, j: null }; });
}
function uiPushSub(){
  return uiPushReg().then(function(reg){ return reg ? reg.pushManager.getSubscription() : null; })
    .catch(function(){ return null; });
}
function _uiPushKey(s){
  var b = atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice(0, (4 - s.length % 4) % 4));
  return Uint8Array.from(b, function(c){ return c.charCodeAt(0); });
}
function _uiPushDevice(){
  var u = navigator.userAgent;
  if (/iPhone/.test(u)) return "iPhone";
  if (/iPad/.test(u) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)) return "iPad";
  if (/Android/.test(u)) return "Android";
  if (/Mac/.test(u)) return "Mac";
  if (/Windows/.test(u)) return "Windows";
  return "устройство";
}
/* Подписка: разрешение спрашивается первым же действием по нажатию (iPhone иначе не спросит) */
function uiPushSubscribe(){
  var reg, key;
  return Notification.requestPermission().then(function(perm){
    if (perm !== "granted") throw new Error(perm === "denied" ? "уведомления запрещены в настройках" : "разрешение не дано");
    return uiPushReg();
  }).then(function(r){
    if (!r) throw new Error("фоновый скрипт не установился");
    reg = r;
    return uiPushApi("key");
  }).then(function(k){
    if (k.status !== 200 || !k.j || !k.j.public_key) throw new Error("сервер уведомлений: " + (k.status || "нет связи"));
    key = _uiPushKey(k.j.public_key);
    return reg.pushManager.getSubscription();
  }).then(function(sub){
    // ключ сервера сменился (пересоздан том) — старая подписка мертва, переподписываем
    var old = sub && sub.options && sub.options.applicationServerKey ? new Uint8Array(sub.options.applicationServerKey) : null;
    var same = old && old.length === key.length && Array.prototype.every.call(old, function(x, i){ return x === key[i]; });
    if (sub && old && !same) return sub.unsubscribe().then(function(){ return null; });
    return sub;
  }).then(function(sub){
    return sub || reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
  }).then(function(sub){
    return uiPushApi("subscribe", { subscription: sub.toJSON(), label: _uiPushDevice() });
  }).then(function(r){
    if (r.status !== 200) throw new Error("сервер не принял подписку (" + r.status + ")");
  });
}
function uiPushUnsubscribe(){
  return uiPushSub().then(function(sub){
    if (!sub) return;
    return uiPushApi("unsubscribe", { endpoint: sub.endpoint }).then(function(){ return sub.unsubscribe(); });
  });
}
function _uiPushTs(ts){
  var m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(String(ts || ""));
  return m ? m[3] + "." + m[2] + " " + m[4] + ":" + m[5] : String(ts || "");
}
function _uiPushSeg(act, opts, cur){
  return '<div class="ui-seg sm acc">' + opts.map(function(o){
    return '<button type="button" class="ui-seg-btn" data-push-act="' + attr(act + ":" + o[0]) + '" aria-pressed="' + (cur === o[0]) + '">' + esc(o[1]) + "</button>";
  }).join("") + "</div>";
}
function _uiPushCard(title, body, cls, aside, attrs){
  var h = '<h2 class="ui-h2">' + esc(title) + "</h2>";
  return '<section class="ui-card lg ui-push-card' + (cls ? " " + cls : "") + '"' + (attrs || "") + ">" +
    (aside ? '<div class="ui-push-head">' + h + aside + "</div>" : h) + body + "</section>";
}
// Сгиб карточки (общий .ui-fold): на узком экране (тот же брейкпойнт, где колонки складываются) группа свёрнута
// по умолчанию и раскрывается нажатием; на широком — раскрыта и не сворачивается. Выбор владельца в рамках страницы
// помнит box.__uiPushOpen (перерисовка после переключателя не должна схлопывать группу).
function _uiPushNarrow(){ try { return window.matchMedia("(max-width:860px)").matches; } catch(e){ return false; } }
function _uiPushFold(box, id, title, body, cls){
  var st = box.__uiPushOpen || (box.__uiPushOpen = {});
  var open = id in st ? st[id] : !_uiPushNarrow();
  return '<section class="ui-card lg ui-push-card' + (cls ? " " + cls : "") + '" data-push-fold="' + attr(id) + '">' +
    '<details class="ui-fold ui-push-fold"' + (open ? " open" : "") + ' data-push-fold-id="' + attr(id) + '">' +
    '<summary><h2 class="ui-h2">' + esc(title) + '</h2><span class="ui-chev">▾</span></summary>' + body + "</details></section>";
}
function _uiPushKinds(s, kinds){
  var off = s.off || [];
  return kinds.map(function(k){
    return '<div class="ui-push-kind"><div><div class="ui-push-kind-t">' + esc(k.label) + '</div><div class="ui-sub">' + esc(k.desc) + "</div></div>" +
      _uiPushSeg("kind:" + k.id, [["on", "Вкл"], ["off", "Выкл"]], off.indexOf(k.id) >= 0 ? "off" : "on") + "</div>";
  }).join("");
}
function uiPushMount(box, o){
  o = o || {};
  box.__uiPush = o;
  box.classList.add("ui-push");
  if (!box.__uiPushBound){
    box.__uiPushBound = true;
    box.addEventListener("click", function(ev){ _uiPushClick(box, ev); });
    // сгиб запоминает выбор; toggle не всплывает — ловим на погружении
    box.addEventListener("toggle", function(ev){
      var d = ev.target;
      if (d && d.getAttribute && d.getAttribute("data-push-fold-id")){
        (box.__uiPushOpen || (box.__uiPushOpen = {}))[d.getAttribute("data-push-fold-id")] = d.open;
      }
    }, true);
    // экран стал широким — группы раскрываются обратно (на широком они не сворачиваются)
    try {
      window.matchMedia("(max-width:860px)").addEventListener("change", function(e){
        if (e.matches || !box.isConnected) return;
        box.__uiPushOpen = {};
        box.querySelectorAll("details[data-push-fold-id]").forEach(function(d){ d.open = true; });
      });
    } catch(e){}
  }
  return _uiPushRender(box, o.msg || null);
}
function _uiPushRender(box, msg){
  var o = box.__uiPush || {}, env = uiPushEnv(), sec = o.section || null, sub = null;
  if (!box.innerHTML.trim()) box.innerHTML = '<div class="ui-note">Спрашиваю сервер уведомлений…</div>';
  return (env.supported ? uiPushSub() : Promise.resolve(null)).then(function(s){
    sub = s;
    return uiPushApi("status?" + (sec ? "section=" + encodeURIComponent(sec) + "&" : "") + (sub ? "endpoint=" + encodeURIComponent(sub.endpoint) : ""));
  }).then(function(st){
    if (!box.isConnected) return;
    box.__uiPushSub = sub;
    var head = (msg ? '<div class="ui-alert tight' + (msg.ok ? " info" : "") + '">' + esc(msg.text) + "</div>" : "") +
               (o.lead ? '<p class="ui-note ui-push-lead">' + o.lead + "</p>" : "");
    var after = function(){ if (o.after) box.appendChild(o.after); };
    if (st.status === 401 || st.status === 403){
      box.innerHTML = head + _uiPushCard("Уведомления", '<div class="ui-alert tight warn">Нужен вход: уведомления под паролем даже дома. Нажми «Войти» в шапке.</div>');
      return after();
    }
    if (st.status !== 200 || !st.j){
      box.innerHTML = head + _uiPushCard("Уведомления", '<div class="ui-alert tight">Сервер уведомлений не отвечает (' + esc(st.status || "нет связи") +
        "): проверь, что на NAS запущен hub-notify.</div>");
      return after();
    }
    var s = st.j, on = !!(sub && s.subscribed), quiet = s.mode !== "live";
    var kinds = (s.kinds || []).filter(function(k){ return !sec || (k.section || "portfolio") === sec; });
    var nDev = (s.devices || []).length;
    var devs = (s.devices || []).map(function(d){ return d.label; }).join(", ");
    var html;
    if (sec){
      // страница раздела: свои виды и журнал; устройство и режим — одной строкой со ссылкой в hub
      var log = s.log || [];
      var rows = log.map(function(r){
        return '<div class="ui-push-log-row' + (r.url ? " pick" : "") + '"' + (r.url ? ' data-push-url="' + attr(r.url) + '"' : "") + (r.key ? ' data-push-key="' + attr(r.key) + '"' : "") + ">" +
          '<div class="ui-sub">' + esc(_uiPushTs(r.ts)) + " · " + esc(UI_PUSH_STATUS[r.status] || r.status) + (r.grouped ? " (сводкой)" : "") + "</div>" +
          '<div class="ui-push-log-t">' + esc(r.title) + "</div>" + (r.body ? '<div class="ui-muted ui-push-log-b">' + esc(r.body) + "</div>" : "") + "</div>";
      }).join("");
      var mainKinds = kinds.filter(function(k){ return k.group !== "ahead"; });
      var aheadKinds = kinds.filter(function(k){ return k.group === "ahead"; });
      var devCard = _uiPushCard("Это устройство",
          '<div class="ui-kv first"><span>Уведомления</span><b>' + (on ? "включены" : "выключены") + "</b></div>" +
          '<div class="ui-kv"><span>Режим сервера</span><span>' + (quiet ? "тихий — только в журнал" : "отправка") + "</span></div>" +
          '<div class="ui-kv"><span>Подписано устройств</span><span>' + nDev + (devs ? " · " + esc(devs) : "") + "</span></div>" +
          '<a class="ui-link ui-push-hub" href="hub.html#notify">Устройства и тихий режим — в кабинете →</a>');
      // «Напоминать заранее» (виды с group "ahead") — отдельной группой, на ПК в правой колонке под «Этим устройством»
      var aheadCard = aheadKinds.length ? _uiPushFold(box, "ahead", "Напоминать заранее",
          '<p class="ui-note ui-push-sub">Утром, по бумагам в портфеле, одним уведомлением.</p>' + _uiPushKinds(s, aheadKinds)) : "";
      html = head + '<div class="ui-push-grid">' +
        '<div class="ui-push-col">' + _uiPushFold(box, "kinds", "Что присылать",
          '<p class="ui-note ui-push-sub">Общее для всех устройств. Выключенное пишется в журнал как «выключено» и при включении не присылается задним числом.</p>' +
          _uiPushKinds(s, mainKinds)) + "</div>" +
        '<div class="ui-push-col">' + devCard + aheadCard + "</div>" +
        "</div>" +
        _uiPushCard("Журнал" + (log.length ? " · последние " + log.length : ""), rows ||
          '<p class="ui-note">Пока пуст. Утренняя проверка — в 08:30.</p>');
    } else {
      // hub: устройство, режим, все виды по разделам
      var dev = "";
      if (!env.supported){
        dev += '<div class="ui-alert tight info">' + (env.ios && !env.standalone
          ? "На iPhone уведомления приходят только приложению с экрана «Домой». В Safari: «Поделиться» → «На экран „Домой“», открой кабинет с ярлыка и войди (у приложения свой вход), потом — сюда."
          : "Этот браузер не умеет push-уведомления.") + "</div>";
      } else if (Notification.permission === "denied"){
        dev += '<div class="ui-alert tight warn">Уведомления запрещены. Разреши их в настройках: на iPhone — «Настройки → Уведомления», в браузере — значок сайта у адреса.</div>';
      } else {
        dev += '<div class="ui-kv first"><span>Уведомления</span><b>' + (on ? "включены" : "выключены") + "</b></div>" +
          '<div class="ui-push-btns">' + (on
            ? '<button type="button" class="ui-btn ghost" data-push-act="test">Прислать пробное</button>' +
              '<button type="button" class="ui-btn ghost" data-push-act="unsub">Выключить</button>'
            : '<button type="button" class="ui-btn" data-push-act="sub">Включить на этом устройстве</button>') + "</div>";
      }
      // пересоздание ярлыка и проверки копят подписки — одним нажатием оставить только это устройство
      var prune = nDev > (on ? 1 : 0) ? '<button type="button" class="ui-link ui-push-prune" data-push-act="prune">' + (on ? "оставить только это" : "убрать все") + "</button>" : "";
      var day = function(d){ return d ? String(d).slice(8, 10) + "." + String(d).slice(5, 7) : "—"; };
      dev += '<div class="ui-kv"><span>Подписано устройств</span><span class="ui-push-devs">' + nDev + (devs ? " · " + esc(devs) : "") + prune + "</span></div>" +
        '<div class="ui-kv"><span>Последние проверки</span><span class="ui-push-last">утренняя ' + day(s.last_daily) +
        " · по ценам " + (s.last_hourly ? day(s.last_hourly) + " " + String(s.last_hourly).slice(11, 13) + ":00" : "—") + "</span></div>";
      var mode = _uiPushSeg("mode", [["quiet", "Тихий режим"], ["live", "Отправлять"]], quiet ? "quiet" : "live") +
        '<p class="ui-note">' + (quiet
          ? "События пишутся в журналы разделов и на телефон не уходят. Отработанное в тихом режиме при включении не вываливается."
          : "События уходят на все подписанные устройства.") + "</p>" +
        '<p class="ui-note">Что присылать — ниже, по разделам. Это общее для всех устройств; те же переключатели — на странице раздела, рядом с его журналом.</p>';
      // раздел — своя карточка, по две в ряд: новый раздел с уведомлениями — ещё одна карточка
      var bySec = (s.sections || []).map(function(x){
        var ks = kinds.filter(function(k){ return (k.section || "portfolio") === x.id; });
        if (!ks.length) return "";
        var plain = ks.filter(function(k){ return k.group !== "ahead"; }), ahd = ks.filter(function(k){ return k.group === "ahead"; });
        return _uiPushCard(x.label, _uiPushKinds(s, plain) +
          (ahd.length ? '<p class="ui-note ui-push-sub ui-push-ahead-h">Напоминать заранее</p>' + _uiPushKinds(s, ahd) : ""), "", '<a class="ui-link" href="' + attr(x.url) + '">журнал →</a>',
          ' data-push-sec="' + attr(x.id) + '"');
      }).join("");
      html = head + '<div class="ui-push-grid ui-push-rows">' + _uiPushCard("Это устройство", dev) + _uiPushCard("Режим", mode) + "</div>" +
        '<div class="ui-push-grid ui-push-rows">' + bySec + "</div>";
    }
    box.innerHTML = html;
    after();
  });
}
function _uiPushClick(box, ev){
  var row = ev.target.closest("[data-push-url]");
  if (row){
    var o = box.__uiPush || {}, url = row.getAttribute("data-push-url");
    if (o.onOpen) return o.onOpen(url, { key: row.getAttribute("data-push-key") || "" });
    var u = new URL(url, location.href);
    if (u.pathname === location.pathname){
      uiHelpClose(true);
      if (location.hash === u.hash) window.dispatchEvent(new HashChangeEvent("hashchange")); else location.hash = u.hash;
    } else location.href = u.href;
    return;
  }
  var b = ev.target.closest("[data-push-act]");
  if (!b || b.getAttribute("aria-pressed") === "true") return;
  var act = b.getAttribute("data-push-act"), sub = box.__uiPushSub, p;
  b.disabled = true;
  var done = function(m){ return _uiPushRender(box, m); };
  if (act === "sub") p = uiPushSubscribe().then(function(){ return { ok: true, text: "Включено. Нажми «Прислать пробное», чтобы проверить." }; });
  else if (act === "unsub") p = uiPushUnsubscribe().then(function(){ return { ok: true, text: "Это устройство отписано." }; });
  else if (act === "test") p = uiPushApi("test", { endpoint: sub && sub.endpoint }).then(function(r){
    var res = (r.j && r.j.results) || [];
    if (!res.length) return { ok: false, text: "Пробное не ушло (" + r.status + ")." };
    var bad = res.filter(function(x){ return !x.ok; });
    return { ok: !bad.length, text: "Пробное на все устройства: " + res.map(function(x){
        return x.label + (x["this"] ? " (это)" : "") + " — " + (x.ok ? "отправлено" : "не принято (" + (x.push_status || "нет связи") + ")"); }).join(" · ") + "." +
      (r.j && r.j.removed ? " Отозванных подписок убрано: " + r.j.removed + "." : "") +
      (bad.length ? " На устройстве с ошибкой выключи и включи уведомления заново." : " Должно прийти за несколько секунд.") };
  });
  else if (act === "prune") p = uiPushApi("prune", sub ? { keep: sub.endpoint } : {}).then(function(r){
    return r.status === 200 ? { ok: true, text: sub ? "Оставлено только это устройство. На остальных включи уведомления заново." : "Все устройства убраны." }
                            : { ok: false, text: "Не вышло (" + r.status + ")." };
  });
  else if (act.indexOf("mode:") === 0){
    var m = act.slice(5);
    p = uiPushApi("mode", { mode: m }).then(function(r){
      return r.status === 200 ? { ok: true, text: m === "live" ? "Отправка включена — новые события уйдут на телефон." : "Тихий режим: события только в журналы." }
                              : { ok: false, text: "Режим не сменился (" + r.status + ")." };
    });
  } else if (act.indexOf("kind:") === 0){
    var parts = act.split(":"), id = parts[1], v = parts[2];
    p = uiPushApi("status").then(function(st){
      // список выключенных — свежий с сервера: его могли поменять в другом месте
      var off = ((st.j && st.j.off) || []).filter(function(x){ return x !== id; });
      if (v === "off") off.push(id);
      var k = ((st.j && st.j.kinds) || []).filter(function(x){ return x.id === id; })[0];
      var label = k ? k.label : id;
      return uiPushApi("settings", { off: off }).then(function(r){
        // успех виден по самому переключателю — плашку сверху не показываем (она сдвигала экран); ошибку — показываем
        return r.status === 200 ? null
                                : { ok: false, text: "«" + label + "»: настройка не сохранилась (" + r.status + ")." };
      });
    });
  } else return;
  p.then(done, function(err){ return done({ ok: false, text: "Не вышло: " + (err && err.message || err) }); });
}
function uiPushOpen(section, opener){
  uiHelpClose();
  var ov = document.createElement("div");
  ov.className = "uh-overlay enter";
  ov.setAttribute("data-prev-overflow", document.documentElement.style.overflow || "");
  ov.__opener = opener || null;
  var acc = section === "games" ? "--c-5" : section === "portfolio" ? "--c-1" : "--accent";
  ov.innerHTML =
    '<div class="uh-modal ui-push-modal" role="dialog" aria-modal="true" aria-labelledby="up-title" style="--uh-acc:var(' + acc + ');--sec-acc:var(' + acc + ');">' +
      '<div class="uh-head"><div><div class="uh-kicker">' + (section ? "Уведомления раздела" : "Кабинет") + '</div>' +
        '<h2 class="uh-title" id="up-title">' + (section ? esc(UI_PUSH_SECTION[section] || section) : "Уведомления") + '</h2></div>' +
        '<button type="button" class="uh-close" data-uh-close aria-label="Закрыть">✕</button></div>' +
      '<div class="uh-body"></div>' +
    "</div>";
  document.body.appendChild(ov);
  document.documentElement.style.overflow = "hidden";
  try { ov.querySelector("[data-uh-close]").focus({ preventScroll: true }); } catch(e){}
  return uiPushMount(ov.querySelector(".uh-body"), { section: section || null });
}
function uiPushBtnHTML(section){
  return '<button type="button" class="chip-btn" data-ui-push="' + attr(section) + '" title="Push-уведомления: что присылать, журнал" aria-label="Уведомления">' +
    '<span class="uh-ico" aria-hidden="true">🔔</span><span class="h-btn-lbl">Уведомления</span></button>';   // .uh-ico — высота шапки как у «Справки»
}
document.addEventListener("click", function(ev){
  if (!ev.target.closest) return;
  var b = ev.target.closest("[data-ui-push]");
  if (!b) return;
  ev.preventDefault();
  var s = b.getAttribute("data-ui-push");
  uiPushOpen(s === "all" ? null : s, b);
}, false);
/* адрес с #notify (ссылка «журнал →» из hub, «в кабинете →» со страницы раздела) — окно сразу */
function uiPushFromHash(){
  if (location.hash !== "#notify") return;
  var b = document.querySelector("[data-ui-push]");
  if (!b) return;
  try { history.replaceState(null, "", location.pathname + location.search); } catch(e){}
  b.click();
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", uiPushFromHash); else setTimeout(uiPushFromHash, 0);
window.addEventListener("hashchange", uiPushFromHash);

/* Escape слоя страницы (ui-kit 1.64.0, uiLayerBind). Регистрируется ПОСЛЕДНИМ в
   файле: собственные окна ui-kit (справка, список, подсказка (i), поиск,
   подтверждение, шторка читателя) уже погасили событие — тогда defaultPrevented. */
if (typeof window !== "undefined") document.addEventListener("keydown", function(ev){
  if (ev.key !== "Escape" || ev.defaultPrevented || ev.isComposing || !UI_LAYER || uiLayerDepth() <= 0) return;
  if (document.querySelector(".ui-confirm, .uh-overlay, .ui-tabs-pop")) return;
  var r;
  try { r = UI_LAYER.closeTop(ev); } catch(e){ return; }
  if (r !== false) ev.preventDefault();
});
