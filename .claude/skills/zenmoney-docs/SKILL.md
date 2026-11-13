---
name: zenmoney-docs
description: >
  Навигатор по контуру ZenMoney в репозитории claude_skills: скилл
  zenmoney-analyst (режимы, рецепты, контракт MCP, запись в ZenMoney), аудит
  учёта и статистика месяцев, поездки, история ZenMoney/audit/ на Synology,
  правка приватной карты, пересчёт истории из CSV-выгрузки, страница «Деньги»
  со стороны данных. Передаёшь тему — скилл грузит ТОЛЬКО релевантное.
  Вызов: /zenmoney-docs <тема> [ещё темы].
trigger: /zenmoney-docs
---

# /zenmoney-docs

Точечная загрузка документации перед работой над контуром ZenMoney (личные
финансы). Контур вырос до скилла с пятью скриптами, своей историей на Synology,
приватной картой и CSV-пересчётом — читать всё ради правки одного правила
подсчёта дороже, чем полезно.

Проектный скилл — живёт в `.claude/skills/` репозитория `claude_skills`
(рядом с `design-docs`, `food-docs`, `investment-docs`, `travel-docs`).
Все пути — относительно корня репозитория.

**Вид страницы «Деньги» — у `/design-docs money`.** Здесь — данные, которые
она показывает, и скилл, который их пишет.

## Использование

```
/zenmoney-docs skill        # SKILL.md: режимы A–D, принципы, анти-паттерны, рецепты
/zenmoney-docs audit        # Режим D «закрой месяц»: проверки учёта, audit_month.py
/zenmoney-docs stats        # итоги месяца: month_stats.py, корзины, места, правила «разовая»
/zenmoney-docs trips        # итоги поездок: trip_stats.py, даты, фазы, типы трат
/zenmoney-docs history      # ZenMoney/audit/ на Synology: файлы, контракты, audit_history.py
/zenmoney-docs map          # приватная карта: что в ней, map_edit.py
/zenmoney-docs csv          # пересчёт истории из CSV-выгрузки: tools/zenmoney_csv_backfill.py
/zenmoney-docs csv-site     # выгрузка CSV с сайта (этап «Деньги» плана «меньше ИИ»): csv-site.md, zm_csv.py, /api/zm/*; сверка выписки на сайте (второй блок вкладки «Загрузка», только Райф CSV и BOG XLSX) — stmt-site.md, zm_stmt.py
/zenmoney-docs mcp          # контракт MCP, запись в ZenMoney (Режим C), запреты
/zenmoney-docs page         # money.html со стороны данных (поля, синк справки)
/zenmoney-docs tests        # что гонять после правок
/zenmoney-docs              # без аргумента → показать карту и спросить
```

## Процедура

1. **Разобрать аргумент** в список тем; синонимы: `скилл`/`режимы`/`рецепты` →
   skill; `аудит`/`закрой месяц`/`замечания`/`корректировки` → audit;
   `статистика`/`траты`/`разовые`/`места`/`категории` → stats; `поездка`/
   `поездки` → trips; `история`/`audit`/`файлы`/`synology` → history; `карта` →
   map; `выгрузка`/`пересчёт`/`пересчитай`/`backfill`/`csv` → csv; `сайт`/`без ИИ`/`zm_csv`/`csv-site` → csv-site; `запись`/`контракт`/`api` → mcp;
   `страница`/`деньги`/`money` → page. Пусто — показать карту и спросить.
2. **Всегда прочитать сначала** раздел «Состояние на … и как возобновить
   работу» в `docs/zenmoney/README.md` — версии, что где лежит, типовые действия.
3. **Для каждой темы** — её строка каталога ниже. Только это.
4. **Кросс-темное** (держать в голове при любой правке контура):
   - **Данные — НЕ в репозитории.** `Claude-Memory/ZenMoney/` на Synology:
     `~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/ZenMoney/`
     (`zenmoney-map.md` + `audit/`). В репозитории и в `.skill` — ни ID, ни сумм,
     ни названий счетов (правило `SKILL.md` «В сам скилл не класть»).
   - **Писатели — только скрипты.** `audit/` — только `audit_history.py`
     (dry-run, хеш, `.bak`, whitelist полей); карта — только `map_edit.py` после
     «да» на diff. Узкие исключения D3 — корневой `CLAUDE.md`.
   - **Меняешь поля `audit/*.json`** — в том же коммите whitelist в
     `audit_history.py`, `money.html`, справка `tools/assets/help/money.md`,
     бриф `docs/zenmoney/money-page-brief.md`, тесты (правило синка — README,
     «Страница „Деньги“»).
   - **Личные выгрузки** (`docs/zenmoney/*.csv`, `docs/zenmoney/csv/`) — в
     `.gitignore`. Коммитить только явные пути, никогда `git add -A docs`
     (2026-10-06 CSV так попал в коммит, историю пришлось переписывать).
   - **Запись в ZenMoney** — Режим C: каждое изменение по согласию;
     `delete_transactions` и `upsert_accounts` запрещены пользователем совсем.
   - **Версии:** скилл — строка «Версия скилла» в `SKILL.md` + раздел в README;
     страница — `VERSION` в `money.html` (виден в подвале). После правки скилла —
     `./pack.sh zenmoney-analyst`; страницы — `zsh tools/deploy.zsh`.
5. **Команда-действие.** Аргумент «пересчитай историю (места) из csv <файл>» — это не
   «загрузи доки», а задача: прочитать `docs/zenmoney/csv-recompute.md` и выполнить его по
   шагам (стопы рецепта — обязательны: потерянный тег поездки, непройденный гейт, изменённые
   итоги поездок → сначала спросить пользователя). Запись в `audit/` — только `audit_history.py`.
6. **Доложить, что загружено**, и ждать задачу. «Проанализируй/проверь» —
   анализ и ждать; править сразу только по «исправь/сделай».

## Карта тема → что читать

| Тема | Доки | Код / данные | Тесты |
|---|---|---|---|
| **skill** | `skills/zenmoney-analyst/SKILL.md`; `references/recipes.md` (R1–R12), `references/output-format.md` (язык ответа); README «Зафиксированные решения» | — | `tools/tests/test_skill_refs_integrity.py` |
| **audit** | `references/audit.md` (§ проверки, вид корректировок, формат «закрытия»); `docs/zenmoney/audit-plan.md` (решения) | `scripts/audit_month.py`; `audit/accepted.json` (принятые) | `tests/test_audit_month.py` |
| **stats** | `references/audit.md` (статистика месяца, «разовая», места); README 2.7.1–2.8.0 | `scripts/month_stats.py`; `audit/spending-rules.json` (разовые по операции и месту) | `tests/test_month_stats.py` |
| **trips** | `references/recipes.md` R4; README (поездка — тег; даты — из карты) | `scripts/trip_stats.py`; `audit/trips.json`; карта, раздел «Поездки» | `tests/test_trip_stats.py` |
| **history** | шапка `scripts/audit_history.py` (файлы, команды, запись); `references/history.md` (вопросы за годы, факты, `history_query.py`); `docs/zenmoney/money-page-brief.md` §1 (контракты) | `audit/{history,spending,trips,accepted,spending-rules,facts}.json`; пороги фактов — `PARAMS` в `scripts/history_query.py` | `tests/test_audit_history.py`, `tests/test_history_query.py` |
| **map** | `references/private-map.template.md`; `SKILL.md` «Карта данных» и правило записи; шапка `scripts/map_edit.py` | `Claude-Memory/ZenMoney/zenmoney-map.md` (+ `backup-*`) | `tests/test_map_edit.py` |
| **csv** | **`docs/zenmoney/csv-recompute.md`** (рецепт по шагам: что изменилось → сухой прогон → копия → запись); README «Состояние…» (последняя записанная выгрузка); шапки `tools/zenmoney_csv_backfill.py`, `tools/zenmoney_csv_diff.py`, `tools/zenmoney_payee_map.py` (словарь «текст банка → место»: CSV «Кому» у мест от плагина банка — сырой текст; обновляется дозагрузкой изменённых дней — `changed` → `list_transactions` по окнам → `grab` → `build`) | `docs/zenmoney/csv/` (вне git: курсы ЦБ/ZenMoney, `rule-ops.json`, `trip-ids.json`, `accounts.json`, `category-flags.json`, `payee-map.json` + `payee-pages/`) | гейт сверки внутри скрипта (до рубля с записанным); `tools/tests/test_zenmoney_csv_diff.py`, `tools/tests/test_zenmoney_payee_map.py` |
| **csv-site** | **`docs/zenmoney/csv-site.md`**, для сверки выписки на сайте — `docs/zenmoney/stmt-site.md` (поток, файлы `ZenMoney/csv/` на NAS, маршруты `/api/zm/*`, схема отчёта `zm-csv-report@1`, решения владельца); `docs/zenmoney/csv-checks-research.md` (§2 политика записи, §3 кандидаты проверок, §4 бэктест); `docs/no-ai-mode/PLAN-less-ai.md` §1.4 и §3 строка «Деньги» | `tools/hosting/notify/zm_csv.py`, маршруты hub-notify `/internal/zm-csv-*`, зона `ZM_WHITELIST` в `tools/hosting/api/server.py`, раздел «Выгрузка» `tools/money.html` | `tools/tests/test_zm_csv.py`; `test_write_api.py`, `test_site_jobs.py`, `test_caddy_zones.py` |
| **mcp** | `references/mcp-contract.md` (инструменты, допущения, журнал версий), `references/write-mode.md` (Режим C, ловушки upsert), `references/data-schema.md` (поля, роли счетов) | — | `tests/test_audit_month.py` (разбор ответов MCP) |
| **page** | `docs/zenmoney/money-page-brief.md`; справка `tools/assets/help/money.md`; вид — `/design-docs money` | `tools/money.html` (только чтение `audit/*.json`), плитка в `tools/hub.html` | `tools/tests/test_pages_contracts.py` (money), `tools/tests/test_money_layout.py` (Chromium + WebKit) |
| **tests** | `docs/test-registry.md` (блоки ZenMoney и «Деньги») | — | `python3 tools/run_tests.py zenmoney` и `… money` |

Пути `references/`, `scripts/`, `tests/` — внутри `skills/zenmoney-analyst/`.

## Что в этом скилле НЕ живёт

- Вёрстка, токены, графики ui-kit, плитки хаба → `/design-docs money`, `/design-docs hub`.
- Хостинг (Caddy, зоны доступа, deploy) → `/design-docs hosting`.
- Инвестиции и портфель — другой контур (`/investment-docs`); скилл
  инвестсоветов не даёт.

## Принципы

- **Минимум контекста.** Только доки запрошенных тем.
- **Числа считают скрипты, модель объясняет.** Правило подсчёта меняется в
  скрипте и тесте, не в тексте ответа.
- **История пересчитывается дёшево** (CSV → скрипт) — поэтому решения
  пользователя хранятся правилами (`spending-rules.json`, карта), а не правками
  итогов вручную.
- **Язык — русский.**
