# API-1: точка входа

**Обновлено: 2026-10-21.** Что сделано, как устроено, как запускать и тестировать локально, что дальше.
Задача — [`docs/TODO.md` → API-1](../TODO.md#api-1).

## Документы

| Файл | Что в нём | Когда читать |
|---|---|---|
| этот README | система как есть: состав, устройство, запуск, тесты, открытые вопросы | первым |
| [`analysis-2026-10-20.md`](analysis-2026-10-20.md) | исследование «переносить ли на API» и вердикт по каждому скиллу | если встал вопрос «зачем» |
| [`deterministic-plan.md`](deterministic-plan.md) | архитектура и решения владельца (загрузчик, eShop, макро) | перед правкой архитектуры |
| [`implementation-brief.md`](implementation-brief.md) | нарезка на PR-1…9, критерии приёмки, журнал теневого периода | перед следующим PR |
| [`../test-registry.md`](../test-registry.md) | аннотации тестов (блоки «API-1b») | перед правкой скриптов |

## Статус

| Часть | Состояние |
|---|---|
| PR-2 `build_snapshot.py` — сборка снапшота без LLM | ✅ сделано, проверено на реальных входах 16.10 без MOEX/ЦБ |
| PR-3 `checks.py` — проверки целостности | ✅ сделано, пороги откалиброваны на паре 13.10 → 16.10 |
| PR-4 `parity_check.py` + `shadow_bundle.py` + Шаг 6а SKILL.md | ✅ сделано |
| Теневой период (2–4 прогона скилла на Mac) | ⏳ следующий шаг |
| PR-1 карта полей снапшота | ⏸ не делался (не блокирует) |
| PR-5 переключение скилла | ⏸ после теневого периода |
| PR-6 веб во вьюере | ✅ сборка снапшота с вьюера: «Собрать» → `hub-notify` `pf_build.py` → проба в `Portfolio/snapshots/auto/`, «Сохранить» — рабочий снапшот `Portfolio/snapshots/` (с вьюера 4.0.0; `pf_build.SAVE_DIR`), затем журнал решений и пересчёт стресса; основной путь сборки — сайт, скилл — запасной |
| PR-7…9 eShop | ✅ 2026-10-21 код: `notify/eshop.py` (08:30 МСК, повтор 09:00, кнопка «Обновить цены», push «порог выполнен»), `tools/eshop_lookup.py` (nsuid по ссылке; 20 из 21 игры нашлись по названию), цены на `games.html`, правило 24 ч в `game-advisor`. API Nintendo с NAS отвечает 200. ⏳ деплой и `nsuid_us` в watchlist |
| Макро (`build_macro.py`) | ✅ 2026-10-21: 5 индикаторов + Brent BR MOEX, Δ/z по `anomaly-detection.md`; инфляция — вход или `--infl-cbr` (месячная из таблицы ЦБ). Задача сайта `notify/macro_job.py` — по будням в `macro-snapshots/auto/`. ⏳ деплой |
| Пробный месяц задач сайта | до 2026-11-21: журнал `_jobs/log-ГГГГ-ММ.jsonl`, копии перезаписей в `.versions/`, выключатель `JOBS_OFF` — см. ниже |

Код — в ветке `claude/api-migration-research`, в `main` пока не влит.

## Как устроено (загрузчик портфеля)

Все новые файлы — в `skills/portfolio-data-loader/`.

```
scripts/build_snapshot.py   оркестратор: Шаги 1–7 SKILL.md одной командой
  ├─ parse_portfolio.py → portfolio_returns.py → per_security_xirr.py → iis_returns.py
  │   → moex_quotes.py → assemble_snapshot.py        (существующие скрипты, без изменений логики)
  ├─ checks.py              проверки block / warning / info → build-summary.json
  └─ --commit               Portfolio/snapshots/portfolio-<дата>.json + decision_journal_update.py
scripts/netcache.py         запись/повтор ответов сети (подмена urllib.request.urlopen)
scripts/parity_check.py     сверка двух снапшотов поле за полем
scripts/shadow_bundle.py    пакет прогона СКИЛЛА для теневой сверки (init / finish)
references/parity-known-diffs.yaml   законные расхождения скилл↔скрипт с причиной
```

Что оркестратор делает вместо модели:
- выбирает режим по набору файлов (полный / только сделки / только баланс);
- находит прошлый снапшот (самый свежий с датой ≤ даты сборки), `sector-overrides.yaml`,
  последнюю выгрузку ИИС-3 (`Portfolio/inputs/<дата>/` — кладёт импорт на сайте; папки Mac не ищутся);
- проверяет MOEX (`moex_quotes.py --health`, признак — поле `ok` в JSON, не код выхода),
  при недоступности — `--no-moex` и флаг `moex_unavailable`; ЦБ 503 → `--cbr-offline`;
- ИИС-3 не посчитался → флаг `iis_returns_failed`, блок переносится из прошлого снапшота;
- флаги, требующие вашего ответа (`cash_drift_changed`, `iis_returns_mismatch`,
  `iis_composition_changed`), выносит в `decisions` сводки;
- блок-проверка → `--commit` не пишет, код выхода 2.

**Пакет прогона** (`--record DIR` / `--replay DIR`): входы, стартовое состояние кэшей курсов ЦБ
и рядов бенчмарков, все ответы сети, `manifest.json` (дата, входы, решения о фолбэках).
Повтор не ходит в сеть и не зависит от дня запуска: дата — из манифеста
(`assemble_snapshot.py --as-of`, `PDL_AS_OF`), кэши — через `PDL_CBR_CACHE` и
`PDL_MARKET_SERIES_CACHE`. Без этих переменных скрипты ведут себя как раньше.

## Запуск локально

Окружение (один раз): pyenv 3.12.9, как у всех тестов репозитория.

```bash
pip install openpyxl numbers-parser
# если numbers-parser падает с «incompatible Protobuf Gencode/Runtime»:
pip install -U protobuf
```

Обычная сборка (сухой прогон — ничего не пишет):

```bash
CM=~/Library/CloudStorage/SynologyDrive-home/Claude-Memory
python3 skills/portfolio-data-loader/scripts/build_snapshot.py \
    --trades ~/Downloads/trades_portfolio_707160-46.xlsx \
    --balance "<путь>/Общий баланс.numbers" \
    --memory "$CM" --out /tmp/pdl
# вывод: позиции, XIRR, флаги, вопросы-решения, проверки; полная сводка — /tmp/pdl/build-summary.json
```

С записью: добавить `--commit`. Принять новое кэш-расхождение: `--rebaseline-cash`.
Отдельно проверки по готовому снапшоту:

```bash
python3 skills/portfolio-data-loader/scripts/checks.py "$CM/Portfolio/snapshots/portfolio-2026-10-16.json" \
    --prev "$CM/Portfolio/snapshots/portfolio-2026-10-13.json" --trades <выгрузка сделок>
```

## Теневой период — что делать

Скилл `portfolio-data-loader` запускается как обычно (в Claude Code на Mac), Шаг 6а SKILL.md делает
сверку сам:

1. `shadow_bundle.py init` — пакет в `~/.cache/claude-skills/pdl-parity/<дата>/` (локально, не на Synology);
2. команды Шагов 2–6 — через `netcache.py run --record "$B/net" -- …`;
3. `shadow_bundle.py finish …` — повтор скриптом и `parity-report.md` в пакете.

После прогона — строка в журнале `implementation-brief.md` («Теневой период»). Расхождение —
разбор: ошибка скрипта (чинить) или законное отличие (`parity-known-diffs.yaml` с причиной).
**Переключение (PR-5):** 2 прогона подряд без «расходится», всего ≥2, хотя бы один со сделками.

## Тесты

```bash
python3 tools/run_tests.py portfolio-data-loader    # все тесты загрузчика (≈10 с)
python3 tools/run_tests.py                          # весь репозиторий — перед пушем
```

Новые тесты (сеть не нужна; описание каждого — в `docs/test-registry.md`, блоки «API-1b»):

| Тест | Что держит | Проверок |
|---|---|---|
| `tests/test_netcache.py` | повтор никогда не идёт в сеть; HTTP-ошибки и gzip повторяются точно | 8 |
| `tests/test_build_snapshot.py` | сквозная сборка на синтетической выгрузке через повтор; детерминизм; фолбэк MOEX; запрет `--commit` при повторе; хелперы | 13 |
| `tests/test_snapshot_checks.py` | каждая проверка срабатывает и не срабатывает; живые случаи 16.10 | 26 |
| `tests/test_parity_check.py` | совпало / в допуске / известное / расходится; коды выхода | 9 |

В облачной сессии 2026-10-20 весь набор: 129 из 130 зелёные; `travel-planning/tests/test_anketa.py`
падает только там (нужен профиль на Mac).

## Решения владельца 2026-10-21

- **Проверки данных IntelInvest** (фантом, автокорректировки, дубли выплат, задним числом) — в
  `checks.py`, общие для скилла и сайта: одна реализация `build_snapshot.py` + `checks.py`.
- **Выгрузки сделок не хранить**, пока хватает сравнения итогов по бумагам двух снапшотов
  (`per_instrument_xirr`): изменения задним числом видны по бумаге и виду потока, без строки.
  Хранение выгрузок — только если этого окажется мало.
- **Выгрузка ИИС-3:** дали — считаем по ней и кладём в `Portfolio/inputs/` (нужна правка
  `claude-memory-layout.md`); не дали — последняя сохранённая там же, а не поиск по папкам Mac.
- **`--cbr-offline`** починен (`ea8f779`).
- **Brent для скрипта макро** — расчётная цена ближайшего фьючерса BR MOEX (ISS), Δ на одном
  контракте (без скачка при смене контракта), дата смены источника помечается в истории.

## Теневой период макро

Срез скилла делается как обычно. В тот же день — скрипт с теми же цифрами инфляции, что нашёл скилл:

```bash
python3 skills/macro-ru-watcher/scripts/build_macro.py --history "$CM/macro-snapshots" --out /tmp/macro \
    --infl-yoy <г/г> --infl-yoy-asof "на DD.MM" --infl-week <нед> --infl-week-period "DD–DD.MM" \
    --infl-source "[источник](url)"
```

Сравнить с `ru-<дата>.md` скилла построчно: MOEX и ставка — совпадение при одном времени сбора;
Brent — ожидаемо другой (BR вместо ICE с разных сайтов), сравнивается Δ; z-score — у скрипта
по одной процедуре. Ставка ЦБ и курсы с Mac через VPN недоступны — прогон на NAS или с исключением
cbr.ru из VPN.

## Задачи сайта (цены eShop, макро) — устройство и пробный месяц

```
hub-notify (расписание, 08:30 МСК; повтор 09:00)          hub-api (единственный писатель веба)
  ├─ eshop.py      Gaming/watchlist.yaml (nsuid_us) ──►  POST /api/job/save  → Gaming/eshop-prices.json
  │                 API Nintendo, пачки по 50 id            (+ копия прежней версии в .versions/)
  ├─ macro_job.py  build_macro.make(…, infl_cbr=True) ►  POST /api/job/save  → macro-snapshots/auto/ru-<дата>.md|json
  └─ jobs.py       журнал прогона ─────────────────────►  POST /api/job/append → _jobs/log-ГГГГ-ММ.jsonl
games.html «Обновить цены» → /api/games/eshop-refresh (hub-api) → hub-notify /internal/eshop-refresh (раз в 10 мин)
```

- `/api/job/*` и `/internal/*` — только изнутри docker-сети: запрос через Caddy несёт
  `X-Forwarded-For` и получает 403.
- Сбой источника цен не стирает прошлые цены: `status: unavailable`, прежний `fetched_at`,
  время попытки — в `attempt_at`. Скилл берёт цены из файла только моложе 24 ч.
- Макро на пробный месяц пишется отдельно от срезов скилла (вьюер и история z-score читают только
  `macro-snapshots/` без подпапок). Инфляция — месячная из таблицы ЦБ, недельной нет.
- **Деплой:** `tools/deploy.zsh`, затем на NAS `cd …/_nas && sudo docker compose up -d && sudo docker restart hub-api`
  (compose сменился: `hub-notify` монтирует папку `notify/` целиком; `hub-api` compose не
  пересоздаёт — без restart работает старый `server.py`, и «Обновить цены» отвечает
  «unknown endpoint», случай 2026-10-21). Проверка: `deploy.zsh` предупреждает,
  если `/api/health` не сообщает `site_jobs`.
- **nsuid в watchlist:** `python3 tools/eshop_lookup.py fill --watchlist "$CM/Gaming/watchlist.yaml"
  --out /tmp/wl.yaml` → посмотреть diff → поставить на место. Нет страницы — нужна ссылка eShop.
- **Откат:** `JOBS_OFF: "eshop,macro"` в compose и `docker compose up -d hub-notify`; файлы — из `.versions/`.

### Сборка снапшота с вьюера (PR-6, пробный режим с 2026-10-21)

```
вьюер «Проба сборки снапшота» ──► Caddy /api/pf/* (пароль с любого IP) ──► hub-notify pf_build.py
  POST /api/pf/build  файлы base64 → /data/pf/runs/<id>/inputs/ → build_snapshot.py (копия notify/pdl/,
                      без --commit, --memory /srv только чтение; кэши ЦБ и рядов — /data/pf/) в фоне
  GET  /api/pf/status сводка: числа против прошлого снапшота, проверки, решения, фолбэки
  POST /api/pf/save   ──► hub-api /api/job/save → Portfolio/snapshots/auto/portfolio-<дата>-<ЧЧММ>-bal|trades.json + build-summary
```

- Отличия от плана PR-6: исполняет `hub-notify` (там уже том зависимостей и фоновые потоки), а не
  `hub-api`; входы — в томе `notify_data`, не в `Portfolio/inputs/`; запись — только пробная папка.
- **Баланс необязателен (решение владельца 2026-10-21):** без него `build_snapshot.py` передаёт
  `assemble_snapshot.py --holdings-from-trades` — позиции, qty, стоимость и средняя цена из сделок
  (цены MOEX, котировки по тикерам сделок); название, корзины облигаций, доли и цели (IE), план↔факт —
  из прошлого снапшота с `balance_carried_from`; ИИС-3 — позиции прошлого снапшота (облигация на
  двух счетах распознаётся); внебиржевые (FINAMAR) — по цене прошлого снапшота; кэш — оценка
  «реконструкция + прошлое расхождение», решения `cash_drift_changed` в этом режиме нет. Флаг
  `balance_absent_holdings_from_trades` перечисляет перенесённое. Тест — `test_trades_mode.py`.
  Скилл (Шаги SKILL.md) вызывает `assemble` без флага — его поведение не изменилось (returns-only).
- Зависимости `hub-notify`: + `openpyxl`, `numbers-parser` (колёса musllinux есть, компиляции нет) —
  новая метка тома в compose, первый старт после деплоя дольше.
- **Деплой:** `tools/deploy.zsh` (кладёт `notify/pf_build.py` и `notify/pdl/`), на NAS
  `sudo docker compose up -d && sudo docker restart hub-api portfolio-viewer` (Caddyfile: зона `/api/pf/*`).
- Журнал: строки `pf_build` / `pf_save` в `_jobs/log-ГГГГ-ММ.jsonl`. Откат — убрать `reverse_proxy @api_pf`.

## Открытые вопросы к владельцу

1. MOEX недоступен целиком → сейчас снапшот сохраняется с предупреждением (как в скилле), но при
   всех ценах из последних сделок XIRR искажён (16.10: −1,94 % вместо 8,27 %). Предложение — блок.
2. Снапшот 16.10: `cash_drift_changed` +169 тыс. ₽ к базе 13.10 — перебазировать или искать
   пропуск в выгрузке.
3. ~~Макро: источники Brent и инфляции~~ — решено 2026-10-21: Brent — BR MOEX, инфляция — таблица ЦБ (месячная).
4. ~~eShop: ответ эндпоинта Nintendo~~ — с NAS 200 (2026-10-21).
