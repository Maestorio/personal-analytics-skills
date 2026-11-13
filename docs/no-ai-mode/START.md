# Старт работ «Кабинет без ИИ» — стартовый пакет

**Статус: ревизия 09.11 выполнена; порядок работ — `PLAN-less-ai.md` §3; ветка интеграции `claude/less-ai`; пути и якоря — по `main`.** Этот файл — единственное, что нужно
открыть, чтобы начать: принципы режима, принятые решения, схемы новых файлов, задачи по шагам с файлами,
тестами и критериями приёмки, путь возврата к ИИ. Обоснования — в `README.md` и приложениях этой папки; решения ревизии — `REVIEW-2026-11-09.md`.
Ссылки на код — якоря (имя функции, константы, CSS-класса, заголовка), не номера строк.

Шкала: S ≈ часы–день, M ≈ 2–5 дней, L ≈ недели. Каждая задача заканчивается тестом в
`docs/test-registry.md` и правкой справки страницы (правила `CLAUDE.md` «Справки страниц кабинета»,
«Синхронизация справки вьюера»).

---

## 0. Принципы режима «без ИИ»

1. **Один флаг на весь сайт.** `ai_mode: on | off` в `Claude-Memory/_hub/settings.json`. Пишет только
   hub-api; читают страницы, hub-notify (напрямую с NAS) и скрипты-писатели Mac (через `_shared-references/hub_settings.py`).
2. **Гейт по происхождению входа.** При `off` отказывают писатели, чей вход — вывод модели (`promote_draft.py`,
   `stamp-report`, `decision_write.py from-report`, `update_index.py`, `build_snapshot.py` из скилла,
   `validate_*.py merge` по данным модели, прямой `Write` скиллов) — с текстом «сайт в режиме без ИИ: правки идут с сайта».
   Писатели с владельческим входом (`decision_write.py owner`, `apply_condition.py add/withdraw` с `source: owner`,
   `intake.py apply` подтверждённого плана, `zenmoney_csv_backfill.py` + `audit_history.py`, `security_attrs.py set`,
   `known_splits.py` CLI) работают в обоих режимах с проверкой свежести зеркала и `author: owner`. Сайт (hub-api, hub-notify)
   пишет всегда. `hub_settings.py` читает флаг сначала по сети (`GET /api/hub/settings`), иначе из файла зеркала; у файла срок
   годности — старше N дней предупреждение, а не молчаливое `on`. Нет файла и нет сети — `on`.
3. **(Пересмотрено 11.11: блокируют те же статусы, что при ИИ; снимает решение владельца — текст ниже описывает прежнее решение.) В режиме «без ИИ» понятия «блокировка докупки по качеству» нет.** Логика двойная: *качество бумаги*
   (решение владельца: вердикт, срок, заметка) и *план по бумаге* (доля, слово плана, статус). Колонка
   «Сейчас» строится из решения и плана. Истёкший срок решения — **напоминание**, не гейт. Блокируют только
   то, что задал сам владелец: слово плана `WAIT`, его же условия, отсутствие цены.
4. **Решение владельца — первоклассная запись.** Тот же `decision@1` (`author: owner`,
   `source.kind: owner`), что пишет `decision_write.py owner`; советник при возврате ИИ читает его как
   любое решение (`decision_write.py digest`, `last_word`). Ничего «временного» не заводим.
5. **Условия владельца — простые:** «произошло X → напомни Y». Это `conditions@2` с `kind: watch`,
   `on_trigger.action: notify_only`, триггер `date | price_below | price_above | event`, `source.kind: owner`.
   Смена полей (вердикт, доля, реинвест) через условия в режиме «без ИИ» не предлагается.
6. **Возврат к ИИ обязателен и дёшев:** переключить флаг, убедиться, что зеркало Synology Drive догнало NAS,
   получить список правок сайта за время «без ИИ» (`GET /api/hub/changes`), и дать скиллам сверить их первым шагом
   (`return-to-ai.md`).
7. **Ничего не затирать.** Все записи с сайта — `base_hash`/409 и `.versions/` (уже так); узкие проверки по
   полям (`waits_owner`, `updated_by`) — всегда, флаг режима — предохранитель поверх них.

---

## 1. Решения владельца (сводно)

| # | Решение | Где учтено |
|---|---|---|
| 1 | Статусы игр `куплена / играю / пройдена` нужны | задача 3.4 |
| 2 | Переключатель — на весь сайт, цель — не перезатирать правки сайта | задачи 1.1–1.3 |
| 3 | В режиме «без ИИ» блокировки нет: срок решения → напоминание; качество бумаги проверяет владелец и меняет решение сам; дальше — действие в плане. **Пересмотрено 11.11: блокируют как при ИИ (те же статусы гейта), снимает решение владельца, не разбор советника** | задачи 2.1–2.3 |
| 4 | Токен ZenMoney не заводить; CSV-выгрузка на сайт; проверки заскриптованы (A1–A5, B7) | задачи 3.6–3.7 |
| 5 | Простые условия «произошло X → напоминание Y», без смены полей | задача 2.4 |
| 6 | Путь возврата к ИИ с минимальной работой | задачи 1.4, `return-to-ai.md` |
| 7 | Путешествия — чисто ИИ, черновик поездки не делаем | снято |
| 8 | Ветка интеграции `claude/less-ai`; ветки этапов — от неё и в неё | `PLAN-less-ai.md` §3 |

| # | Вопрос | Решение | Где учтено |
|---|---|---|---|
| 9 | Пауза докупки 21 день после BUY/ADD и IPO-пауза 8 кварталов в режиме «без ИИ» | **блок** (как и при ИИ): это механические правила владельца, не анализ | задача 2.1: при `off` снимаются только статусы класса `gate`; `add_cooldown` и `ipo_gate` блокируют всегда |
| 10 | Держимая бумага без решения в режиме «без ИИ» | **напоминать** | задача 2.3: вид push `no_decision` включён при `off`; подпись в карточке и в «Сейчас» |
| 11 | Ручной ввод анализов на странице «Здоровье» при `ai_mode: on` | **не оставлять**: при `on` единственный писатель `labs.json` — `intake.py` (в том числе из `PLAN.json`, подготовленного локальной моделью по `spike-health-pdf-local.md`); ручная форма точек — только при `off`. Apple Health с сайта не делаем; давление вводится формой страницы (`vitals.json` `bp[]`) | задачи 1.2, 3.2, 3.3: ручные точки помечены `source: manual` и при возврате ИИ не трогаются |

---

## 2. Схемы новых файлов и форм

### 2.1 `Claude-Memory/_hub/settings.json` — `hub-settings@1`

```json
{
  "schema": "hub-settings@1",
  "ai_mode": "off",
  "off_since": "2026-11-20T10:15:00+03:00",
  "returned_at": null,
  "by": "site",
  "note": "блокировка"
}
```

- Пишет hub-api: `GET /api/hub/settings` → `{hash, settings}`, `POST /api/hub/settings {settings, base_hash}`;
  зона — пароль с любого IP (исключение для `/api/hub/*` в `@api_trusted` Caddy), File Station (нужен зеркалу на Mac), `.versions/`.
- Переход `on → off`: `off_since = now`, `returned_at = null`. Переход `off → on`: `returned_at = now`,
  `off_since` остаётся до следующего `off` (по нему считается «что менялось на сайте»).
- Читатели: ui-kit при загрузке (кэш в `localStorage["hub-noai"]`, атрибут `data-noai` на `<html>`),
  hub-notify в дневном проходе, скрипты — через `_shared-references/hub_settings.py`.

### 2.2 Решение владельца с сайта → `decision@1`

Форма в карточке бумаги («Проверить качество» / «Подтверждаю держать»): `verdict` (кодлист `verdict`),
`target_pct` (необязательно), `review_by` (дата, по умолчанию +60 дней; 7–180), `note` (обязательно,
≥ 20 знаков), `confidence` (необязательно). Сервер (маршрут в hub-notify, модули `last_word`,
`ds_schemas`, `conditions_merge` выложены в `pdl/`; `decision_write.py` добавляется в `deploy.zsh`) собирает запись как `decision_write.cmd_owner`
(`skills/save-to-library/scripts/decision_write.py`): `source = {kind: owner}`, `author: owner`,
`recorded_at` — МСК сервера, `conditions_resolved` — **только** условия с `waits_owner`
(см. задачу 1.2), файл `Portfolio/decisions/{дата}T{ЧЧММ}-{KEY}.json` через `/api/job/save`
(новая запись `JOB_WHITELIST` в `tools/hosting/api/server.py`). Повтор той же минуты — 409.

### 2.3 Условие-напоминание с сайта → `conditions@2`

Форма на «Действиях» / в карточке: **Когда** — `date` (дата) | `price_below` / `price_above` (порог ₽) |
`event` (отмечу сам кнопкой «вышел»); **Напомнить** — текст (`on_trigger.text`, ≤ 200);
**Бумага** — ключ или «портфель» (`key`). Остальное фиксировано: `kind: watch`, `on_trigger.action:
notify_only`, `while_pending: {verdict: null, text: ""}` («none» = вердикта нет: схема допускает null только у `kind: watch`), `source: {kind: owner}`, `created_by: owner`. Запись —
`apply_condition.py add` в hub-notify (PyYAML там есть) с новым флагом `--no-restamp` (перештамповка
обзора недели R33 в hub-notify невозможна: `weekly-reviews/` вне его записи) и выводом содержимого вместо
записи на mount (`--emit`), затем `/api/job/save` → `Portfolio/conditions.yaml` (whitelist). Срабатывание —
уже существующие проходы hub-notify (`collect_daily`, `collect_hourly`, `tick` в `notifier.py`), резолюция — существующие кнопки
(`POST /api/pv/cond/event`).

### 2.4 `Gaming/user-state.json` — `gaming-user@1` (оверлей игр)

```json
{ "schema": "gaming-user@1", "updated": "…", "items": [
  { "title": "…", "platform": "switch2", "state": "играю", "rating": null, "note": "",
    "price_target_usd": 29.99, "discount_target_pct": null, "nsuid_us": "…", "eshop_url": "…",
    "deleted": false, "updated": "…" } ] }
```

Оверлей — **постоянный SSOT человеческих полей** (состояние, оценка, заметка, пороги цены, nsuid, удаление) в обоих
режимах; `taste-profile.yaml` несёт только модельные поля (веса `mood_clusters`, история рекомендаций). Скилл оверлей
читает; переноса в YAML и `deleted: true` при возврате нет.
`state` ∈ `хочу | на-карандаш | не-интересно | куплена | играю | пройдена | брошена`, `platform` — списки в
`_shared-references/codelists.json`; «брошена» только в `state` (в `verdict` библиотеки «брошено» уже есть).
`rating` ∈ 5 значений вердикта библиотеки (`VERDICTS` в `games.html`). Ключ — нормализованный `title`.
Зона `/api/gm/file|save` с паролем (не как `/api/fd/*` без пароля; `_zone` в `server.py`), валидатор `validate_gaming` (stdlib; гарантирует
числовые пороги и формат nsuid). Страница показывает слияние YAML-слоя и оверлея; `eshop.targets` (`notify/eshop.py`)
читает пороги и `nsuid_us` из оверлея поверх watchlist.

---

## 3. Задачи по шагам

Нумерация — порядок выполнения; «Файлы» — что править; «Тесты» — что дописать (новых файлов тестов
не заводить без нужды — дописывать оси; каждый тест — блок в `docs/test-registry.md`).

### Шаг 1. Флаг режима и защита от перезатирания

| № | Задача | Файлы | Тесты | Приёмка | Размер |
|---|---|---|---|---|---|
| 1.1 | Файл `_hub/settings.json`, ручки `GET/POST /api/hub/settings` (whitelist, `base_hash`, File Station, `.versions/`); зона с паролем с любого IP | `tools/hosting/api/server.py` (`_zone`, whitelist, `/api/health` признак `hub_settings`), `tools/hosting/Caddyfile.example` (обязательно: `/api/hub/*` в исключения `@api_trusted`, иначе открыт доверенным IP без пароля), `_shared-references/claude-memory-layout.md` | `tools/tests/test_write_api.py` (новая зона, 409, валидатор), `test_caddy_zones.py` | `curl` с паролем читает/пишет; без пароля — 403 | S |
| 1.2 | **Узкие проверки писателей** (не зависят от флага): `decision_write._resolved` и `notifier.cond_done_events` закрывают только условия с `waits_owner` (отложенные владельцем — не трогать); `apply_condition.py edit` не стирает отсрочку (`state_reset` только по явному флагу); события от решения — актёр `decision`: значение в кодлисте `actor`, в `CSTATE_INTERNAL_ACTORS`, в `ds_schemas`. `intake.py` перечитывает `labs.json` с хэшем перед записью (сейчас хэш только у `studies.json`); `known_splits.py` — хэш чтения | `skills/save-to-library/scripts/decision_write.py` (`_resolved`), `tools/hosting/notify/notifier.py` (`cond_done_events`), `skills/save-to-library/scripts/apply_condition.py` (докстринг `edit`, поле `state_reset`), `_shared-references/codelists.json` (`actor` += `decision`), `_shared-references/ds_schemas.py`, `tools/hosting/api/server.py` (`CSTATE_INTERNAL_ACTORS`), `skills/health-labs/scripts/intake.py`, `skills/portfolio-data-loader/scripts/known_splits.py` | `skills/save-to-library/tests/test_decision_write.py`, `test_apply_condition.py`, `tools/tests/test_notifier.py`, `test_codelists.py` (паритет кодлиста `actor` ↔ `CSTATE_INTERNAL_ACTORS` ↔ `ds_schemas`), тесты `intake`/`known_splits` (устаревшее зеркало → отказ) | отложенное владельцем условие переживает новое решение и `edit`; `by: decision` проходит валидаторы; устаревшее зеркало не затирает `labs.json` | S |
| 1.3 | **Общий модуль флага** `_shared-references/hub_settings.py` (`ai_mode(path) → "on"|"off"`: сначала `GET /api/hub/settings`, иначе файл зеркала со сроком годности; нет файла и сети → `on`; **корень `Claude-Memory/` выводится из переданного пути** — семь скриптов принимают прямой путь, а не `--root`: `validate_meds`, `validate_labs_info`, `validate_report`, `audit_history`, `map_edit`, `stmt_propose`, `known_splits`) и **гейт по происхождению входа** (принцип 0.2). Группа А — **отказывают при `off`** (вход — вывод модели): `promote_draft.py`, `assemble_artifact.py stamp-report`, `decision_write.py from-report`, `update_index.py`, `build_snapshot.py` (любая запись под `--memory`: `--commit` с `--working` и без, `--record`, кэши), `validate_meds.py merge`, `validate_labs_info.py merge`, `validate_report.py save`, `map_edit.py --write`, `stmt_propose.py places-add`, `apply_condition.py` не-owner/`edit`, `audit_history.py --write` вне CSV-пути, travel `merge_dr_additions.py --inplace` и `export/*` (travel-planning — не «без скриптов-писателей»), миграции, прямой `Write` скиллов. Группа Б — **работают в обоих режимах** (проверка свежести зеркала, `author: owner`): `decision_write.py owner`, `apply_condition.py add/withdraw` с `source: owner`, `intake.py apply` подтверждённого плана, `apple_health_bp.py` (терминал Mac, разовый; не развивается), `build_health_json.py` (импорт CSV владельца, режим merge), `zenmoney_csv_backfill.py` + `audit_history.py` с `source: csv`, `security_attrs.py set`, `numbers_to_plan.py --out` (`--force` не обходит проверку; защита по `updated_by` остаётся), `known_splits.py` — гейт **только в CLI** (`stress_job` зовёт `apply_add` напрямую, сайт пишет всегда). Скиллы без скриптов-писателей (`game-advisor`, `macro-ru-watcher`, `portfolio-coherence-audit`) — шаг 0 в SKILL.md + правило в `transport-layer.md`; `travel-planning` — шаг 0 и гейт в скриптах; модуль — в бандлы (`pack.sh`/`bundle_scripts`). Группа каждого писателя уточняется по матрице «кто пишет» `claude-memory-layout.md` | перечисленные скрипты; `_shared-references/transport-layer.md`; `claude-memory-layout.md`; SKILL.md перечисленных скиллов; `pack.sh` | новый `tools/tests/test_ai_mode_gate.py` — тест-таблица «скрипт → группа (А/Б) → поведение при `off`» (А: код выхода ≠ 0 и ничего не записано; Б: работает; нет файла флага → `on`; старое зеркало → отказ/предупреждение); `test_skill_instructions_ds.py` — сторож «шаг 0» в SKILL.md | каждый писатель группы А отказывает при `off`, группы Б работает в обоих режимах, при отсутствии файла флага работают все | M |
| 1.4 | **Возврат к ИИ — серверная часть и сверка:** маршрут `GET /api/hub/changes?since=` в hub-api — файлы с хэшем по зонам `Portfolio/ Gaming/ Health/ ZenMoney/ _hub/` (`POST /api/pv/sync` отдаёт только размер и mtime и только `PV_DIRS` — не годится); `tools/noai_return.py` читает этот маршрут: по `off_since` (или `--since`) собирает список правок сайта (журнал плана, события `conditions-state.json`, решения `author: owner`, `Gaming/user-state.json`, `Health/labs.json` точки `source: manual`, `ZenMoney/audit/*` с `source: csv`), сверяет хэши зеркала Mac и печатает «зеркало отстаёт: N файлов» / «можно включать» | `tools/hosting/api/server.py` (маршрут, зона с паролем), новый `tools/noai_return.py`, `_shared-references/claude-memory-layout.md` | `tools/tests/test_write_api.py` (маршрут `hub/changes`: зоны, хэши, `since`), `tools/tests/test_noai_return.py` (на tmp-корне) | чек-лист `return-to-ai.md` проходится за 5 минут | M |
| 1.5 | ui-kit: чтение флага при загрузке, `data-noai`, кнопка в шапке хаба «Режим: с ИИ / без ИИ» (переключение `on → off` — сразу; `off → on` — через окно «Вернуться к ИИ» со списком из `/api/hub/changes`, подтверждение пишет `ai_mode: on`); CSS: при `data-noai` скрыты `.ui-claude-cmd`, `.act-say`, подписи «Что сказать Claude», CTA гейтов; серые плашки для LLM-файлов | `tools/assets/ui-kit.js` (рядом с `uiSetTheme`), `ui-kit.css`, `tools/hub.html` (кнопка и окно), `tools/assets/help/hub.md`, `tools/assets/viewer.js` (`_staleList`; скрытие `.act-say` — CSS-правилом по селектору, не по местам вхождений), страницы money/games/health (подсказки «Скажи Claude…») | `test_pages_contracts.py` (новая ось «режим без ИИ»: атрибут, скрытые классы, версии страниц), `test_viewer_words.py` | в режиме `off` на страницах нет ни одной команды для Claude; плашки LLM-файлов серые | S–M |

### Шаг 2. Портфель в режиме «без ИИ»

| № | Задача | Файлы | Тесты | Приёмка | Размер |
|---|---|---|---|---|---|
| 2.1 | **(Переделано 11.11: при `off` те же статусы блокируют, `noai_gate_blocks: true`, снимает решение владельца; ссылка «запиши решение →» в «Сейчас»; ниже — прежняя постановка.) Гейты не блокируют при `off`:** модуль (б) получает параметр режима; при `off` статусы класса `gate` (`codelists.json` `maps.gate_to_block`) не дают `blocking`, но `reasons` несут текст «срок решения вышел дд.мм» как предупреждение; паритет JS↔Python; пауза докупки (`add_cooldown`) и IPO-пауза (`ipo_gate`) **блокируют в обоих режимах** (решение 9) | `_shared-references/last_word.py` (статус срока — правило 6; блокировка рождается в сборке `reasons`/`blocking`), `tools/assets/last-word.js` (`function gate`), `tools/assets/rebalance-engine.js` (`function gateContext`), `skills/ru-portfolio-advisor/scripts/gate_aware_sizing.py` (флаг `--ai-mode`), `_shared-references/codelists.json` (`defaults.noai_gate_blocks: false`) | `test_last_word_parity.py`, `test_rebalance_parity.py`, `test_viewer_last_word.py`, `test_viewer_plan_now.py` | при `off` «Сейчас» считает по решению и плану; предупреждения видны; при `on` поведение прежнее | S + паритет |
| 2.2 | **Решение владельца с сайта** (форма §2.2) — маршрут `POST /api/pf/decision` в hub-notify (модули в `pdl/`), whitelist `Portfolio/decisions/\d{4}-\d{2}-\d{2}T\d{4}-[A-Z0-9.-]+\.json`, 409 на ту же минуту; карточка бумаги: кнопки «Проверить качество» (полная форма) и «Подтверждаю держать» (вердикт HOLD, срок +60, заметка «подтверждено владельцем»); журнал решений подхватывает автоматически (`pf_build.publish_journal`). **deploy.zsh: копии `decision_write.py` / `apply_condition.py` в `pdl/`. Caddy: маршрут `/api/pf/*` уже в hub-notify — проверить зону (`@api_pf`, пароль с любого IP)** | `tools/hosting/notify/notifier.py` (маршрут, по образцу `/api/pf/splits`), `tools/hosting/notify/stress_job.py` или новый `decision_job.py`, `tools/hosting/api/server.py` (`JOB_WHITELIST`), `tools/deploy.zsh`, `tools/hosting/Caddyfile.example`, `tools/assets/viewer.js` (`gateSayNode` → форма), `tools/assets/help/viewer/06-gates.md`, `08-site.md` | `tools/tests/test_site_jobs.py` (маршрут), `test_write_api.py` (whitelist), `test_caddy_zones.py`, `test_viewer_last_word.py` (форма), `skills/save-to-library/tests/test_decision_write.py` (общая сборка записи) | решение с сайта видно в «Истории» карточки, в `digest` советника и в журнале | S–M |
| 2.3 | **Push о сроке решения** — вид `decision_expiry` («истекает через 7 дн.» и «срок вышел», раз в день, дедуп по решению), вид `no_decision` для держимой бумаги без решения (включён при `off` — решение 10; при `on` выключен, там это делает обзор); разделить `stale` на «обновляемое без ИИ» (снапшот, автосрез) и «LLM-файлы» (выключен при `off`); при `off` «Сказать Claude» из `check_stale` убрано, при `on` остаётся | `tools/hosting/notify/notifier.py` (`KINDS`, `check_stale`, `STALE_CMD`, `load_decisions` + `last_word`); `tools/assets/help/hub.md` §2а | `tools/tests/test_notifier.py`, `test_push_pages.py` | **[no_decision сделан 11.11: только акции без решения (не замороженные), сводка, дедуп 7 дн.; на живом снапшоте 0 бумаг; облигации и фонды не берутся — 41+23 дали бы простыню]** утренний push называет бумаги с истекающим сроком; при `off` без «Сказать Claude» | S |
| 2.4 | **[СДЕЛАНО 11.11: `condition_job.py` + `POST /api/pf/condition` (add/withdraw, `--emit --no-restamp --owner-only`, запись `/api/job/save` с base_hash через `jobs.save_if`; `JOB_WHITELIST` `Portfolio/conditions.yaml`); форма «Новое условие» на «Действиях» и «＋ Напоминание» в карточке; «снять» у условий владельца; бумага вне портфеля — `livePriceOf` из `state.live.quotes.items`, карточка-кандидат; монитор и ценовой проход держимость не проверяют (тесты), советник не теряет условия на не держимые бумаги (тесты, одна фраза в SKILL.md). Схема: `while_pending.verdict` допускает null только у `kind: watch` — напоминание не закрепляет вердикт. Не сделано: `edit` (этап 5)]** **Условия-напоминания с сайта, только add/withdraw** (форма §2.3; `edit` — этап 5 `PLAN-less-ai.md`): `apply_condition.py add --no-restamp --emit`, маршрут `POST /api/pf/condition` в hub-notify → `/api/job/save` `Portfolio/conditions.yaml` (whitelist; корректность записи проверяет hub-notify через `ds_schemas`); форма на «Действиях» и в карточке; «снять» — `withdraw` тем же маршрутом (только условия `source.kind: owner`). **Бумаги не из портфеля (решение владельца 11.11):** форма принимает любой тикер MOEX, не только держимый — «купить, когда упадёт до X» (`price_below`) и «разобрать отчёт перед покупкой» (`report_published`); тикер проверяется по котировкам TQBR (цена есть — бумага существует), карточка такой бумаги открывается как кандидат (`candidate: true`, есть во вьюере); ценовой проход hub-notify берёт всю доску TQBR, держание не требуется — проверить тестом. Сверка 11.11: hub-notify (`check_conditions_price`, доски TQBR/TQOB/TQCB) и forecast-monitor (`_process_condition_events`) держимость не проверяют — закрепить тестами; **вьюер** `livePriceOf` берёт цену только из позиций снапшота — для бумаги вне портфеля брать из `state.live.quotes.items` (иначе у условия нет «сейчас X · ещё ±N %»); **советник** (`gate_aware_sizing`, digest обзора) — проверить, что условия на не держимые бумаги не выпадают из выборки, и упомянуть это в SKILL.md советника и монитора одной фразой. **deploy.zsh: копии `decision_write.py` / `apply_condition.py` в `pdl/`. Caddy: маршрут `/api/pf/*` уже в hub-notify — проверить зону** | `skills/save-to-library/scripts/apply_condition.py` (флаги), `tools/hosting/notify/notifier.py` (маршрут), `tools/hosting/api/server.py` (`JOB_WHITELIST`), `tools/deploy.zsh`, `tools/assets/viewer.js` («Действия»), `help/viewer/07-conditions.md` | `test_apply_condition.py` (`--no-restamp`, `--emit`), `test_site_jobs.py`, `test_viewer_conditions_pack.py`, `test_viewer_actions_blocks.py` | условие, заведённое с сайта, срабатывает проходом hub-notify и закрывается кнопкой «сделал»; условие на бумагу вне портфеля срабатывает так же | M |
| 2.5 | **[макро сделано 11.11 — решение владельца по сверке автосреза: плашка и графики «Макро» читают автосрез в обоих режимах; недельная инфляция — отдельная карточка, два файла `macro-snapshots/inflation/{model,owner}.jsonl` (скилл `/macro-ru-watcher Обнови инфляцию` ↔ форма «Внести инфляцию» при «без ИИ», `POST /api/pv/macro/inflation`), срок только у неё — 9/16 дн., на «Действиях» строка при «с ИИ», push `macro_infl` при «без ИИ»; z-флаг инфляции — по одному источнику; тесты `test_viewer_macro_auto`, `test_write_api`, `test_notifier`, `test_build_macro`, `test_save_inflation`, `test_ai_mode_gate`]** Мелочи: плашка и графики «Макро» видят автосрез (`_staleList`, `macroAuto` в начальном `state.data`); таблица «Акции» из снапшота без обзора (`renderPositions`, `buildPositionsCard`); `PV_DIRS` без `gate-reviews*.yaml`; `security-attrs.json` для новых бумаг при «Сохранить» (даты с ISS, по образцу `init_security_attrs.py`) | `tools/assets/viewer.js`, `tools/hosting/api/server.py` (`PV_DIRS`), `tools/hosting/notify/pf_build.py` | `test_viewer_macro_auto.py`, `test_pages_contracts.py`, `test_write_api.py`, `test_pf_build.py` | — | S каждая |

### Шаг 3. Здоровье, игры, деньги

**Статусы на 2026-11-10 (колонка «Приёмка» ниже — исходная постановка):** 3.1, 3.2, 3.3 сделаны (health v3.2; 3.2 — только при `ai_mode: off`, `labs_rules.py`); 3.4, 3.5 сделаны (games v2.8.1, три оси `state`/`progress`/`rating`, «демо» — флаг `demo`, миграция `tools/gaming_migrate.py`); 3.6, 3.7 сделаны (money v2.4.4, `zm_csv.py`, `zm_checks.py`, аудит сайта `site-audit.json`); **3.8 сделана для CSV и XLSX (money v2.6.0, блок «Выписка банка» на вкладке «Загрузка», `docs/zenmoney/stmt-site.md`); PDF на сайте не разбирается — решение владельца 2026-11-10**. Спайк локального разбора PDF лаборатории отложен тем же решением (в системе `../LLM`, mlx-lm).

| № | Задача | Файлы | Тесты | Приёмка | Размер |
|---|---|---|---|---|---|
| 3.1 | **Здоровье: сохранить отчёт `.md` со страницы** (`validate_report.py check` → whitelist `Health/reports/*.md`) и **редактор справки маркера** (`what/up/down`, whitelist `biomarkers-info.json`, логика `validate_labs_info.merge`); hub-api не видит общих модулей — монтирование `validate_report.py` / `validate_labs_info.py` в compose | `tools/hosting/api/server.py` (`HEALTH_FILES`, валидаторы), `tools/hosting/docker-compose.yml`, `tools/health.html` (вкладка «Отчёты», карточка маркера), `tools/assets/help/health.md` | `test_write_api.py`, `test_health_panes.py`, `test_pages_contracts.py` | — | S |
| 3.2 | **Здоровье: ручной ввод точки анализа** — `labs` в `HEALTH_FILES` (сменить комментарий-контракт и признак `health_files` в `/api/health`); серверный валидатор по правилам `intake.py` (`plan_check`, `auto_status`, `valid_ref`, `recompute_marker` — вынести в общий модуль `skills/health-labs/scripts/labs_rules.py`, чтобы одна реализация); форма в карточке маркера и «Новый показатель» **только при `ai_mode: off`** (решение 11: при `on` сервер отвечает 403 на ручную запись `labs.json`, страница форму прячет; давление и пульс вводит `bpModal` в `vitals.json`); поле `source: manual`; `health.html` читает `labs.json` через `apiGet` с хэшем; `intake.py` при `on` — единственный писатель `labs.json` через `labs_rules.py` и хэш, ручные точки не трогает. **Compose: монтирование `labs_rules.py` в hub-api; Caddy: зона `/api/hd/*` уже под паролем — проверить** | `tools/hosting/api/server.py`, `tools/health.html` (`NEED_FILES`, `apiSave`, `persist(`, чтение `labs.json` через `getJSON(DATA + "labs.json")`), `skills/health-labs/scripts/intake.py`, новый `labs_rules.py`, `tools/hosting/docker-compose.yml`, `tools/assets/help/health.md`, SKILL.md health-labs | `test_write_api.py` (валидатор labs), `skills/health-labs/tests/` (общий модуль правил), `test_health_chart.py` | точка видна на графике и в «требует внимания», статус посчитан сервером | M |
| 3.3 | **Здоровье: загрузка файла в `studies/`** (`POST /api/hd/upload`, base64, тип по magic bytes, ≤ 20 МБ, имя `ГГГГ-ММ-ДД-вид.ext`, без перезаписи; **отдельный лимит тела по образцу `IE_IMPORT_MAX_BYTES`**, общий `MAX_BYTES` — 8 МБ). **Caddy: зона `/api/hd/*` под паролем — проверить** | `tools/hosting/api/server.py`, `tools/health.html` (`studiesModel`, форма исследования с полем `"Файл"`), `help/health.md` | `test_write_api.py`, `test_site_jobs.py`, `test_health_panes.py` | — | S–M |
| 3.4 | **Игры: оверлей** (§2.4) — зона `/api/gm/*` **с паролем**, валидатор `validate_gaming`, формы на странице (добавить, состояние, оценка, заметка, пороги, удалить), слияние слоёв в карточках, `eshop.targets` из оверлея, кнопка «найти nsuid» (перенос `tools/eshop_lookup.py` в `notify/`, проверить доступность `nintendo.com/us/store` с NAS); enum состояний и платформ — в `_shared-references/codelists.json`; SKILL.md game-advisor — чтение оверлея человеческих полей, enum, исправить `genre_weights` (веса — `mood_clusters.<slug>.weight`); исключение D3 в `CLAUDE.md`; убрать мёртвую «кнопку итог» из `help/games.md` (строка «Подборки»). **Caddy: `/api/gm/*` в исключения `@api_trusted`, маршрутизация в hub-notify при необходимости; compose: монтирование валидатора, если он вне `server.py`; лимит тела формы** | `tools/hosting/api/server.py`, `tools/hosting/Caddyfile.example`, `tools/hosting/docker-compose.yml`, `tools/games.html`, `tools/hosting/notify/eshop.py` (`targets`), `notify/eshop_lookup.py`, `_shared-references/codelists.json`, `skills/game-advisor/SKILL.md`, `docs/game-advisor/CLAUDE.md`, `_shared-references/claude-memory-layout.md`, `tools/assets/help/games.md`, `hub.md` | `test_pages_contracts.py` (блок «3a. watchlist.yaml»: контракт read-only → «пишет только оверлей», enum), `test_write_api.py` (зона, запрет `taste-profile.yaml`), `test_caddy_zones.py`, `test_site_jobs.py`, `test_games_eshop_layout.py` | игра добавляется и меняет состояние с телефона; push о скидке учитывает порог из оверлея | M |
| 3.5 | **Игры: скилл читает оверлей** — SKILL.md game-advisor использует `Gaming/user-state.json` как источник состояния, оценки, заметки и порогов; `taste-profile.yaml` несёт только модельные поля (`mood_clusters`, история рекомендаций), `state` в `library[]` не вводится; «брошена» только в `state`; enum состояний и платформ — один источник (`codelists.json`) | SKILL.md и `references/` game-advisor, `_shared-references/codelists.json`, `tools/games.html`, `docs/game-advisor/CLAUDE.md` | `test_pages_contracts.py` (enum: `codelists.json` = `games.html` = SKILL.md) | скилл не переписывает человеческие поля оверлея | S–M |
| 3.6 | **Деньги: CSV на сайт** — вход: результаты `docs/zenmoney/csv-checks-research.md` (политика diff / «да» / удаления, набор проверок по бэктесту). Страница «Загрузить выгрузку» (по образцу панели сборки снапшота): файл base64 → `POST /api/zm/build` (hub-notify, `zenmoney_csv_backfill.py` + `month_stats`/`trip_stats`, вспомогательные файлы переезжают в `Claude-Memory/ZenMoney/csv/`) → превью (сверка до рубля с записанными месяцами, новые месяцы, предупреждение «места — текст банка») → «Сохранить» → `audit_history.py --write` логикой через `/api/job/save` (whitelist `ZenMoney/audit/*.json`); при `ai_mode: off` — единственный путь обновления. **Инфраструктура: Caddy — `/api/zm/*` в исключения `@api_trusted` и маршрутизация в hub-notify (иначе уйдёт в hub-api), зона с паролем; compose — монтирование `zenmoney_csv_backfill.py`, `audit_history.py` и общих модулей в hub-notify; отдельный лимит тела загрузки по образцу `IE_IMPORT_MAX_BYTES` (общий `MAX_BYTES` 8 МБ)** | `tools/money.html` (подсказки «Скажи Claude…» → кнопка), `tools/hosting/notify/` (новый `zm_job.py`), `tools/zenmoney_csv_backfill.py` (режим библиотеки), `tools/hosting/api/server.py` (`JOB_WHITELIST`), `tools/hosting/Caddyfile.example`, `tools/hosting/docker-compose.yml`, `tools/assets/help/money.md` | `test_site_jobs.py`, `test_zenmoney_csv_diff.py` (фикстуры), `test_money_layout.py`, `test_write_api.py`, `test_caddy_zones.py` | месяц закрывается с телефона без Claude | S–M |
| 3.7 | **Деньги: проверки до записи из CSV** — вход: `csv-checks-research.md`. `audit_month.py` уже принимает операции из `backfill.build()`; добавить ключи `csv-N`, категории по имени, `accounts.json`/`category-flags.json`; проверки A1–A5, B7, C и новые по бэктесту; B6 и A2 деградируют без `source` — на странице помечаются «недоступно без ИИ»; `accepted.json` («это норма») — форма на странице | `skills/zenmoney-analyst/scripts/audit_month.py`, `zm_job.py`, `tools/money.html` («Качество учёта»), `help/money.md` | `skills/zenmoney-analyst/tests/` (CSV-вход), `test_money_layout.py` | вкладка «Качество учёта» обновляется от CSV | S–M |
| 3.8 | **Деньги: сверка выписки без ZenMoney** — загрузка PDF/xlsx → `stmt_import.py` (FF, BOG, Raif, T-Bank) → таблица операций, флаги, сверка остатка; `pdftotext` (`apk add poppler-utils`) в hub-notify | `zm_job.py`, `docker-compose.yml`, `tools/money.html` | `test_site_jobs.py` на фикстурах выписок | — | S |

### Шаг 4. Документация и инфраструктура

| № | Задача | Файлы | Размер |
|---|---|---|---|
| 4.1 | Справки: раздел «Без Claude» первым в `help/viewer/01-run.md`, `help/{health,games,money,hub}.md`; список команд ручного режима в терминале (`decision_write.py owner`, `security_attrs.py set`, `apply_condition.py`, `zenmoney_csv_backfill.py`, `export.py`) — `README.md` §4 волна 1 п.7 | `tools/assets/help/**` | S |
| 4.2 | `CLAUDE.md`: исключение D3 для оверлея игр и `_hub/settings.json`; правило гейта по происхождению входа одной фразой; `_shared-references/claude-memory-layout.md` — новые файлы и писатели; `docs/investment/portfolio-workflow-guide.md` — зеркало справки | корневые доки | S |
| 4.3 | Колёса зависимостей hub-notify в `_nas/wheels/` (`pip download` на Mac, `--no-index --find-links` в compose), фиксированные теги образов; запись в `SYNOLOGY-SETUP.md` | `tools/hosting/docker-compose.yml`, `tools/deploy.zsh`, `SYNOLOGY-SETUP.md` | S |
| 4.4 | Закрыть расхождения доков с кодом (`README.md` §7, `REVIEW-2026-11-09.md` §4) | по списку | S |
| 4.5 | Снять мёртвый whitelist `Gaming/recommendations/*.md` («кнопка итог») из `WHITELIST` в `server.py`; тест `test_write_api.py` использует эти пути в нескольких местах — править все; этап 0 (универсальные) | `tools/hosting/api/server.py` (`WHITELIST`), `test_write_api.py`, `tools/assets/help/games.md` | S |

---

## 4. Порядок и зависимости

```
1.1 флаг ──► 1.3 модуль + отказы
1.1 флаг ──► 1.4 hub/changes + noai_return ──► 1.5 ui-kit/страницы
1.2 узкие проверки (независимо, первым делом)
2.1 гейты при off ──► 2.2 решение с сайта ──► 2.3 push о сроке
2.4 условия-напоминания (после 1.1; независимо от 2.x)
3.1 → 3.2 → 3.3 (здоровье);  3.4 → 3.5 (игры);  3.6 → 3.7, 3.8 (деньги)
4.x — по ходу, 4.4 и 4.5 — когда угодно
```

Порядок этапов и минимум — `PLAN-less-ai.md` §3.

---

## 5. Как начать (первая сессия)

1. `git checkout claude/less-ai && git pull`; `python3 tools/run_tests.py` — зелёный.
2. Прочитать этот файл, `return-to-ai.md`, `README.md` §2 (решения), `02c` §3–§5 (гейты, условия,
   писатели) и `01-infrastructure.md` §5 (переключатель).
3. Решения ревизии — `REVIEW-2026-11-09.md`; новые вопросы — `docs/TODO.md` → NOAI-1.
4. Начать с этапа 0 по `PLAN-less-ai.md` §3.
5. Каждую задачу — отдельным коммитом с тестом в реестре и правкой справки; версии страниц поднимать (важное обновление: первое число +1 один раз на страницу за план, дальше — младшие; `PLAN-less-ai.md` §3).

---

## Что не делаем

Список — `PLAN-less-ai.md` §5.
