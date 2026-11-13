# Отдельный трек: самостоятельный сайт + локальные API

**Дата: 2026-11-07.** Вопрос владельца: на случай блокировок или финансовых ограничений думать
в сторону более самостоятельной работы сайта с «локальными API» — без Claude вообще или с заменой
Claude локальной/иной моделью. Этот документ — про варианты замены *двигателя*, а не про то, что уже
работает без LLM (это — остальные части `docs/no-ai-mode/`).

Факты из веба помечены ссылками; то, что я не смог проверить, помечено **[проверить]**.
Цены и условия провайдеров меняются быстро: раздел «Российский API» опирается на анализ
`docs/api-migration/analysis-2026-10-20.md` (16–20.10.2026) и здесь не перепроверялся.

---

## 1. Что именно пропадает вместе с Claude

Четыре разные вещи, у каждой свой путь замены:

| Что теряем | Где это в системе | Чем заменимо |
|---|---|---|
| **Рассуждение по длинным инструкциям** (SKILL.md 56–79 КБ, справочники 680 КБ у советника) | все аналитические скиллы | только модель класса Sonnet/Opus — локально на 16 ГБ недостижимо (§3) |
| **Агентный цикл с инструментами** (Read/Write/Glob в зеркале Synology, Bash для скриптов, web_search) | Claude Code как исполнитель скиллов | другой агент-раннер, читающий SKILL.md (§4), на локальной или API-модели |
| **MCP-серверы, доступные только внутри Claude** | ZenMoney (`mcp__ZenMoney__*`), память профиля (`memory-sync`) | MCP — открытый протокол: сторонние MCP ZenMoney запускаются в любом клиенте по токену (§5); память профиля не заменима |
| **Чтение сканов/фото, веб-поиск, проверка источников** | health-labs, forecast-*, game-advisor, travel-planning | частично локальный OCR (низкое качество на бланках), веб-поиск через API провайдера |

Вывод отсюда: «самостоятельный сайт» строится в три слоя, и слои независимы:

1. **Слой 0 — код без модели** (уже есть и растёт): hub-api, hub-notify, скрипты скиллов на NAS. Это
   основная ставка, она не зависит ни от каких провайдеров. Детали — остальные документы серии.
2. **Слой 1 — узкие вызовы модели из `hub-notify`** по фиксированным сценариям с JSON-схемой ответа и
   валидатором (как предлагал `analysis-2026-10-20.md` §4). Модель — взаимозаменяемая: локальная на
   Mac, российский API, Anthropic API. Один OpenAI-совместимый клиент с `base_url` в конфиге.
3. **Слой 2 — запуск скиллов другим агентом** (Codex CLI, OpenCode и др.) на другой модели. Самый
   дорогой по качеству и самый близкий к текущему опыту.

---

## 2. Слой 1: узкие вызовы модели из сайта

### Архитектура

```
hub-notify (расписание / кнопка) ──► клиент OpenAI-совместимого API ──► модель
        │                                 base_url из env (локальный Mac / РФ-провайдер / Anthropic)
        ▼
  валидатор ответа (JSON по схеме, повтор ≤2) ──► hub-api /api/job/save (base_hash, .versions/)
```

- Промты — **не SKILL.md**, а короткие шаблоны под одну задачу (≤2 КБ) + схема ответа. Правило живёт
  в двух местах (SKILL.md и шаблон) — это осознанная цена; шаблон кладётся рядом с `notify/` и
  попадает в реестр тестов.
- Модель никогда не пишет в `Claude-Memory/` напрямую — только через hub-api после валидатора, при
  необходимости — после подтверждения на странице (D3 сохраняется).
- Секреты (ключ API) — в `_nas/.env`, как креды DSM; не в Claude-Memory и не в репозитории.

### Кандидаты на слой 1 (по убыванию пользы; все — «деградированная версия скилла»)

| Задача | Вход | Выход | Модель достаточна? |
|---|---|---|---|
| `forecast-monitor`: «наступило ли событие» | тезис + результаты веб-поиска (поиск делает код через API поиска) | `{resolved, confidence, evidence_url}` | 4–9B локально — только как предфильтр; решение — модель уровня Sonnet/DeepSeek-V4 |
| «Что заметно в тратах» (money) | `facts.json` (агрегаты) | 3–5 фраз | да, даже 9B |
| Категоризация незнакомых мест в выписке | строка банка + список категорий | `{category, merchant}` + «не уверен» | да, с валидатором и подтверждением |
| Импорт рецепта из текста/URL | текст страницы | JSON рецепта по схеме `validate_recipe.py` | да |
| Заготовка weekly-review «без вердиктов» | снапшот + план + условия | заполненный stub (`build_weekly_*_stub.py` уже делает скелет) | вердикты — нет; скелет — код |
| Сводка integrated-view по старым числам | `aggregate_positions.py` → frontmatter | краткий текст | текст — да, суждение — нет |

Что **не** класть в слой 1 ни на какой модели: медицинские данные (152-ФЗ, решение в анализе
2026-10-20 §3), вердикты по бумагам, стресс/сценарии, травел-стадии 0–5.

### Варианты двигателя для слоя 1

| Двигатель | Где работает | Плюсы | Минусы | Что проверить |
|---|---|---|---|---|
| **Локальная модель на Mac** (`mlx_lm.server`, OpenAI-совместимый, `docs/mlx-lm-guide_4.md` §2, §10) | MacBook Air M4 16 ГБ, LAN | приватно, бесплатно, без блокировок | Mac должен быть включён и в сети; на 16 ГБ потолок ≈ 9–14B в 4-бит (6–8 ГБ, 12–16 tok/s; гайд §15); tool-calling ненадёжен ниже 27B (гайд §15 «Уровень 4») | формат `/no_think`, качество русского JSON на 20 примерах; доступность Mac для hub-notify по LAN (`http://<mac>:8080/v1`) |
| **Ollama на Mac** (с 2026 — движок MLX на Apple Silicon: превью 30.03.2026, по сторонним данным стабильно в 0.30 с 13.05.2026 — [Ollama blog](https://registry.ollama.ai/blog/mlx), [DEV](https://dev.to/jovan_chan_9500711396d4e6/ollama-v030-on-apple-silicon-what-the-stable-mlx-release-actually-changed-from-the-preview-25h7)) | то же | проще развёртывание, уже есть `Modelfile` (qwen3.5:9b, `num_ctx 8192`) | то же; версия 0.40 из поиска не подтверждена **[проверить]** | `ollama serve` как служба, `OLLAMA_HOST=0.0.0.0` |
| **Российский API** (Yandex AI Studio, Cloud.ru, Selectel Token Factory, GigaChat — источники в `analysis-2026-10-20.md` §7) | облако РФ | нет зависимости от Mac; поиск у Yandex | данные уходят провайдеру; условия меняются; модели DeepSeek/Qwen 200B+ — ближе к Sonnet на простых задачах | актуальные цены, наличие OpenAI-совместимого эндпоинта, политика хранения |
| **Anthropic API** (кредиты Max 5x/20x) | облако | те же модели, что в скиллах | та же блокируемость, что у подписки; РФ не в списке стран | — |

Рекомендация: клиент в `hub-notify` пишется один раз с `LLM_BASE_URL`/`LLM_MODEL`/`LLM_API_KEY` из
env; первый пилот — локальная модель на Mac по LAN (нулевой риск), вторая — российский API для задач с
поиском.

---

## 3. Локальная модель: честные границы на имеющемся железе

Из `docs/mlx-lm-guide_4.md` (гайд ориентирован на MacBook Air M4 / 16 ГБ):

- **Бюджет памяти:** ≈0,55 ГБ на 1 млрд параметров в 4-бит; практический потолок 10–11 ГБ под веса,
  комфортно — до 6 ГБ. Это Qwen3.5-9B / Qwen3-8B-6bit (≈6 ГБ, ~15 tok/s) или Qwen3-14B-4bit (≈8 ГБ,
  ~12 tok/s) как потолок (§15).
- **Tool calling:** приемлемая доля корректных вызовов достигается на 27–70B; на 4–9B ошибки
  перемножаются по шагам агентного цикла (§15 «Уровень 4»). Отсюда — **агентный контур локально
  не работает**, механический («код ходит в сеть, модель жуёт текст») — работает.
- Сторонние тесты Qwen3.5-9B как локального агента на 16 ГБ: «простые одношаговые задачи — да,
  длинные многошаговые — не доказано» ([ai-radar.it](https://ai-radar.it/article/qwen-3-5-9b-un-agente-llm-locale-su-macbook-pro-m1),
  [DEV benchmark](https://dev.to/kuroko1t/benchmarking-local-coding-llms-11-realistic-tasks-232-runs-and-the-bugs-my-bench-found-in-my-46pl)).
  Это анекдотические источники, не бенчмарк — но они совпадают с выводом гайда.
- **NAS (2 ГБ ОЗУ, `mem_limit 900m` у hub-notify)** — модель на нём невозможна в принципе; NAS остаётся
  только клиентом.

Что это значит для скиллов: ни один аналитический скилл (советник, стресс, IV, прогнозы, travel 0–5,
health) на локальной модели не воспроизводится. Локальная модель уместна только в слое 1 и в
«предфильтрации перед Claude» (гайд §17), что ценно, только пока Claude есть.

Апгрейд железа (Mac с 48–64 ГБ или Mac Studio) поднимает потолок до 27–32B в 4–6 бит — класс, где
tool-calling уже надёжен и где Qwen3.5/Gemma-4 27B на русском сопоставимы с Haiku/младшим Sonnet на
задачах по шаблону. Это единственный путь к «слою 2 локально»; оценивать стоит отдельно, когда/если
блокировка станет фактом.

---

## 4. Слой 2: запуск скиллов другим агент-раннером

Формат скиллов этого репозитория (`SKILL.md` + `references/`) — открытый стандарт Agent Skills
(Anthropic, декабрь 2025, спецификация на agentskills.io). По состоянию на 2026 его читают Codex CLI,
OpenCode, Gemini CLI, Cursor, Goose и другие — [обзор 16+ инструментов](https://dev.to/serenitiesai/ai-agent-skills-guide-2026-build-skills-for-16-ai-tools-1jea),
[список агентов](https://www.shiplight.ai/blog/agent-skills), [mdskills.ai](https://www.mdskills.ai/learn/ai-agents-that-support-skill-md-2026).
Глубина поддержки разная (стандарт описывает формат, не рантайм), версии спецификации у агентов
отстают — сверять на agentskills.io **[проверить перед выбором]**.

В репозитории уже есть задел: `AGENTS.md` — копия `CLAUDE.md` под Codex (пути `.Codex/skills/`,
«Codex-Memory»). Он механически переименован и устарел относительно `CLAUDE.md` (список тестов там
старый, реестр `docs/test-registry.md` не упомянут) — если трек станет актуальным, `AGENTS.md` надо
генерировать из `CLAUDE.md`, а не вести вручную.

| Раннер | Локальные модели | MCP | Что известно |
|---|---|---|---|
| **Codex CLI** (OpenAI) | `codex --oss` через Ollama/LM Studio, конфиг провайдера в `~/.codex/config.toml` — [Ollama blog](https://registry.ollama.ai/blog/codex), [гайд 06.2026](https://knightli.com/en/2026/06/18/codex-cli-oss-mode-local-model-guide/) | да, `codex mcp add` (HTTP/stdio, OAuth) — [olostep](https://www.olostep.com/blog/best-mcp-servers-for-codex-cli) | контекст ≥32K рекомендован; с подпиской OpenAI — та же блокируемость, что у Anthropic |
| **OpenCode** (open source, Go) | Ollama `http://localhost:11434/v1` в `opencode.json` — [infralovers](https://www.infralovers.com/blog/2026-02-27-opencode-free-local-llms/), [TDS](https://towardsdatascience.com/build-your-own-local-ai-coding-agent-with-gemma-4-and-opencode/) | да (локальные и удалённые серверы) | читает SKILL.md и AGENTS.md; с малым контекстом скиллы подключает выборочно — [MathWorks](https://blogs.mathworks.com/matlab/?p=4356) |
| **Claude Code** | нет | да | текущий; блокируется вместе с Anthropic |

Что потребуется, чтобы скиллы вообще запустились в другом раннере (независимо от модели):

1. **Транспорт `Claude-Memory`** — скиллы требуют инструменты `Read/Write/Edit/Glob` и запрещают Bash
   для файлов (`_shared-references/transport-layer.md`). В Codex/OpenCode инструменты называются
   иначе; нужен слой «транспорт по имени раннера» или смягчение правила до «любой файловый инструмент
   раннера, Bash для файлов — нет».
2. **Модельная маршрутизация** (`model-routing.md`: Opus/Sonnet/Haiku/Fable) — заменить на абстрактные
   тиры «сильная / средняя / дешёвая» с таблицей соответствия по провайдеру.
3. **`memory-sync`, `revise-memory-local`** — завязаны на память Claude, в другом раннере отмирают.
4. **Веб-поиск** — у Codex/OpenCode свои инструменты или через MCP; скиллы с лестницей источников
   (game-advisor, forecast-*) пишутся под `web_search`/Chrome MCP — потребуют адаптации.
5. **Качество.** На российских API-моделях уровня DeepSeek-V4/Qwen-3.8 простые скиллы (loader,
   macro, save-to-library, forecast-monitor) вероятно пройдут; советник, стресс, IV, travel 0–5,
   retrospective-audit — ожидаемо хуже, с риском выдуманных дат и цитат (анализ 2026-10-20 §3).
   Нужен прогон 2–3 реальных задач с валидаторами до любого решения.

Оценка трудоёмкости переноса «чтобы запускалось»: M–L на транспорт и маршрутизацию (общие файлы
`_shared-references/`), плюс по S на каждый скилл с веб-поиском. Это разумно делать **только при
наступлении блокировки**, но подготовительный шаг — абстракция транспорта и тиров моделей — можно
сделать заранее (S–M) и он полезен сам по себе (пригодится и для `claude -p` на API-кредитах).

---

## 5. Локальные API данных: что доступно без Claude

«Локальные API» в смысле *источников данных*, к которым сайт и NAS ходят сами:

| Источник | Статус | Где используется | Риск блокировки |
|---|---|---|---|
| MOEX ISS (`iss.moex.com`) | работает с NAS, кэш 5/30 мин, stale до 24 ч | живые цены, сборка снапшота, макро | низкий (РФ) |
| ЦБ РФ (`cbr.ru`, `web.cbr.ru`) | работает; офлайн-фолбэк курсов | снапшот, макро (ставка, инфляция месячная), ZenMoney CSV (курсы) | низкий (РФ); с Mac через VPN недоступен — только с NAS |
| Nintendo price API (`api.ec.nintendo.com`) | работает с NAS из РФ (проверено 21.10.2026) | цены eShop | средний (иностранный) |
| `nintendo.com/us/store` (страницы для nsuid) | **не проверено с NAS** | `eshop_lookup.py` (сейчас на Mac) | средний |
| **ZenMoney API** | официальная wiki описывает `https://api.zenmoney.ru/v8/diff/` (инкрементальная синхронизация: accounts, transactions, tags, merchants, instruments; запись через тот же diff), OAuth2 (`/oauth2/authorize/`, `/oauth2/token/`, регистрация приложения вручную) и персональный токен без регистрации через сторонний `zerro.app/token` — [ZenMoney API wiki](https://github.com/zenmoney/ZenPlugins/wiki/ZenMoney-API) (последняя правка 08.2023); `suggest` для категорий | сейчас — только MCP внутри Claude | **[проверить]**: срок жизни токена, доступность с NAS, права записи у персонального токена, лимиты. Сторонние MCP-серверы ZenMoney (`zenmoney-mcp` на PyPI/npm, `mcp-server-zenmoney` с `--read-only`) работают по тому же токену в любом MCP-клиенте — [PyPI](https://pypi.org/project/zenmoney-mcp/), [glama](https://glama.ai/mcp/servers/krax1337/mcp-server-zenmoney/tree); официального MCP от ZenMoney в поиске не найдено |
| IntelInvest | только ручная выгрузка xlsx; API в репозитории не описан | снапшот | — |
| Apple Health | экспорт `export.xml` вручную; парсится stdlib | давление/пульс (режим не реализован) | — |
| Лаборатории (Инвитро, Гемотест, KDL, Helix) | PDF; экспортов/API нет | health | — |

Практический вывод для «Денег»: единственный раздел, где замена MCP прямым API даёт **полную**
автономию (spending/trips/facts по расписанию в hub-notify, аудит — без суждений). Токен — в
`_nas/.env`, предпочтительно read-only; конвертер ответа diff в формат страниц MCP (`{data, references}`),
чтобы `month_stats`/`trip_stats`/`audit_month` не менять. Размер M; детали — `05-money.md` §3(b).

---

## 6. Что ещё важно для «самостоятельности» сайта (не про модель)

- **Код без Claude не развивается.** Всё, что перечислено в серии как «S/M/L», делается, пока Claude
  доступен. Это главный аргумент за приоритет этих работ сейчас, а не «когда заблокируют».
- **Деплой и репозиторий.** `deploy.zsh` работает с локальной копии репозитория; GitHub нужен только
  для синхронизации. Держать на Mac актуальный клон и на NAS — копию `_nas/` (уже так).
- **Холодный старт NAS.** `hub-notify` при первом старте ставит зависимости с PyPI
  (`docker-compose.yml`, том `notify_deps`). При пересоздании тома без PyPI контейнер не поднимется —
  стоит однажды сохранить колёса (`pip download`) в `_nas/wheels/` и ставить из них (S).
- **Внешний вход.** HTTPS и push держатся на DDNS `synology.me` + Let's Encrypt через DSM. Запасной
  путь — Tailscale (описан в `SYNOLOGY-SETUP.md`) или LAN `http://<IP>:8080` (без офлайна и push).
- **Образы контейнеров** (`caddy:2-alpine`, `python:3.12-alpine`) — уже на NAS; при `docker compose
  pull` нужен Docker Hub. Не обновлять образы «на всякий случай» во время блокировок.

---

## 7. Рекомендуемый порядок (если трек открывается)

1. **Сейчас, пока Claude есть (S–M):** в `hub-notify` — один OpenAI-совместимый клиент с env-конфигом
   и одна пилотная задача без приватных данных («что заметно в тратах» по `facts.json` или импорт
   рецепта из текста). Проверить локально на Mac (`mlx_lm.server` / Ollama с `Modelfile`) и, если
   решено, на одном российском API. Записать: доля ответов, прошедших валидатор; токены; время.
2. **Сейчас (S):** абстракция транспорта и тиров моделей в `_shared-references/` — задел для любого
   другого раннера и для `claude -p`.
3. **По факту блокировки:** ZenMoney по прямому API (M), раннер Codex/OpenCode для простых скиллов
   (loader/macro/save-to-library) на российском API (M), решение об апгрейде Mac под 27–32B (деньги).
4. **Не делать:** переносить здоровье и инвестиционное ядро на локальные/сторонние модели; строить
   «общий LLM-эндпоинт» за Caddy с произвольным промтом (риск инъекций и утечки токена).

## Источники

- Agent Skills: [DEV Community — 16+ инструментов](https://dev.to/serenitiesai/ai-agent-skills-guide-2026-build-skills-for-16-ai-tools-1jea) · [Shiplight — список агентов](https://www.shiplight.ai/blog/agent-skills) · [mdskills.ai](https://www.mdskills.ai/learn/ai-agents-that-support-skill-md-2026) · [parallel.ai](https://parallel.ai/articles/what-are-agent-skills)
- Codex CLI + локальные модели/MCP: [Ollama blog](https://registry.ollama.ai/blog/codex) · [DEV Community](https://dev.to/shashikant86/codex-cli-running-gpt-oss-and-local-coding-models-with-ollama-lm-studio-and-mlx-403g) · [knightli.com](https://knightli.com/en/2026/06/18/codex-cli-oss-mode-local-model-guide/) · [olostep](https://www.olostep.com/blog/best-mcp-servers-for-codex-cli)
- OpenCode: [infralovers](https://www.infralovers.com/blog/2026-02-27-opencode-free-local-llms/) · [Towards Data Science](https://towardsdatascience.com/build-your-own-local-ai-coding-agent-with-gemma-4-and-opencode/) · [MathWorks blog](https://blogs.mathworks.com/matlab/?p=4356) · [Ollama setup](https://www.developersdigest.tech/setup/ollama/opencode)
- Ollama на MLX: [Ollama blog](https://registry.ollama.ai/blog/mlx) · [DEV Community](https://dev.to/jovan_chan_9500711396d4e6/ollama-v030-on-apple-silicon-what-the-stable-mlx-release-actually-changed-from-the-preview-25h7) · [InsiderLLM](https://insiderllm.com/guides/qwen35-mac-mlx-vs-ollama/)
- Qwen3.5-9B локально: [ai-radar.it](https://ai-radar.it/article/qwen-3-5-9b-un-agente-llm-locale-su-macbook-pro-m1) · [DEV benchmark](https://dev.to/kuroko1t/benchmarking-local-coding-llms-11-realistic-tasks-232-runs-and-the-bugs-my-bench-found-in-my-46pl) · [openclawdc — 16 GB](https://www.openclawdc.com/blog/best-local-llms-16gb-ram/)
- ZenMoney API и MCP: [ZenMoney API wiki](https://github.com/zenmoney/ZenPlugins/wiki/ZenMoney-API) · [zenmoney-mcp (PyPI)](https://pypi.org/project/zenmoney-mcp/) · [mcp-server-zenmoney (glama)](https://glama.ai/mcp/servers/krax1337/mcp-server-zenmoney/tree) · [theblackhaired/zenmoney-mcp](https://glama.ai/mcp/servers/theblackhaired/zenmoney-mcp)
- Внутренние: `docs/mlx-lm-guide_4.md` (§2, §10, §13, §15, §17), `docs/api-migration/analysis-2026-10-20.md`, `AGENTS.md`, `Modelfile`
