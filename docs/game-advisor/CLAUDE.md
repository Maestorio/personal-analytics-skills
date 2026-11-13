# Game Advisor — дев-правила

Self-contained советник по играм (Nintendo Switch 2 + Steam Deck); вся логика — в `SKILL.md` +
`references/` скилла, исполняемых скриптов и тестов нет. Дев-правила, не выводимые из SKILL.md:

- SSOT профиля вкуса — `Claude-Memory/Gaming/taste-profile.yaml`; `references/taste-profile.yaml`
  в бандле — сид/fallback, синхронизируется с SSOT вручную; при живом Synology приоритет у `Gaming/`.
- Транспорт — только Synology mount; недоступен → остановиться и сообщить пользователю.
- Провенанс-гейты источников (лестница WebSearch → Chrome MCP → web_fetch → webarchive)
  скриптами/прокси не обходить; цены — только из fetched-страниц **или** из
  `Gaming/eshop-prices.json` не старше 24 ч (с 2026-10-21: файл пишет задача сайта
  `tools/hosting/notify/eshop.py` из API Nintendo, 08:30 МСК + кнопка «Обновить цены»; скилл
  его только читает). `nsuid_us` в watchlist заполняет `tools/eshop_lookup.py` по ссылке на
  страницу US eShop — это инфраструктура сайта, не скрипт скилла. Обложки и магазин с сайта подбирает
  hub-notify (`eshop_lookup.lookup_any`): Switch/Switch 2 — US eShop, Steam Deck/Steam/PC/Xbox — Steam
  storesearch (`steam_appid`, обложка CDN Steam); цены для Steam сайт не берёт. Тот же прогон шлёт push
  (2026-10-26): «Скидки на игры» — о любой новой скидке игры списка, «Цены игр» — порог
  выполнен; пороги сайт берёт только из чисел `price_target_usd`/`discount_target_pct`,
  текст `condition` не читает — поэтому скилл обязан дублировать ценовой порог числом.
- Поля владельца (статус из 4, флаг `demo: true` — «играл в демо, не купил» (только при некупленном статусе; у `куплена` сервер его снимает; старое `state: демо` сервер при сохранении приводит к флагу, страница, уведомитель цен и `tools/gaming_migrate.py` читают так же), прохождение `progress`, оценка из 4, заметка, пороги цены, часы, `nsuid_us` или `steam_appid`, обложка) — `Gaming/user-state.json`
  (`gaming-user@1`), пишет его только сайт (`/api/gm/*`, карточка игры); скилл читает и при чтении считает
  его главнее `watchlist.yaml`/`library`, сам не пишет и не переносит; `taste-profile.yaml` и `watchlist.yaml` —
  только скилл. Enum состояний/платформ/оценок — кодлисты `game_state`/`game_progress`/`game_platform`/`game_rating`, один
  источник для сервера, страницы и скилла (сторож — `test_pages_contracts.py`).
- **Два слоя данных, записи между ними не переносятся.** Карта «файл → писатель → поля», порядок слияния
  при чтении и запреты — `skills/game-advisor/references/data-layout.md` (SSOT; меняешь поле оверлея,
  файл раздела или писателя — правь её, `GAMING_ITEM_KEYS` в `tools/hosting/api/server.py` и строки
  `Gaming/` в `claude-memory-layout.md` одним заходом). Модель слияния библиотеки — `tools/assets/games-model.js`, общая для страницы игр и плитки «Игры» хаба; «Присматриваюсь» сливает `mergeWatch`
  (`tools/games.html`), задача цен — в `eshop.targets`. Просьба «перенести библиотеку в `user-state.json`»
  или «свести в один файл» противоречит устройству — не выполнять, объяснить.
- Пользовательская справка страницы «Игры» — `tools/assets/help/games.md`: правишь режимы,
  триггеры, модель или файлы `Gaming/` — обнови её (см. «Справки страниц кабинета» в корневом `CLAUDE.md`).
