# Workflow P — ручные записи журнала решений (AIR-1)

Журнал решений и теневые базы пересобирает сборка сайта скриптом `portfolio-data-loader/scripts/decision_journal_update.py`
(решение владельца D-1). Ручных входов три, их пишет **только** этот workflow; скрипт их читает (валидатор
`ds_schemas.py refusals|theses|incidents` до сборки — невалидный файл останавливает пересборку) и никогда не правит. План и смысл — `docs/investment/portfolio/air-1-decision-journal-plan.md`
(§3, §7, §7а, §9).

Все три файла — в `Portfolio/decision-journal/`, **только дописывание** (append-only): существующие
записи не правятся и не удаляются; исправление — новой записью со ссылкой `corrects: <id>`.

## P1. Триггеры и тип записи

| Сигнал в чате | Файл | Запись |
|---|---|---|
| Владелец ответил на вопрос «… предлагал X — не сделано. Сознательно?» (или сказал «пропустить»); обычно в начале обзора advisor | `refusals.yaml` | одна на каждый заданный вопрос |
| «запиши инцидент: …»; advisor предложил «записать инцидент?» и получил «да» | `incidents.yaml` | одна |
| Открытие или закрытие ставки владельца (валютная ставка на рубль и т.п.) | `theses.yaml` | одна (закрытие — отдельной записью) |

**Итог разбора контрольной точки** («обнови журнал решений и разбери контрольную точку», «проверь правило
отключения…», полугодовой разбор) записывается **решением** по бумаге, которой касается вывод: Workflow M2,
`decision_write.py owner --key X --verdict … --note "контрольная точка <дата>: …"` (вердикт + заметка, R25).
`checkpoints.yaml` упразднён — в него не писать и файл не создавать. Вывод о системе целиком (правило отключения,
«продолжать / свернуть») носителя в схеме пока не имеет: сказать об этом владельцу, в файлы не писать.

## P2. Схемы

```yaml
# refusals.yaml
schema: decision-journal-refusals@1
refusals:
  - episode_id: "stock:MDMG:2026-09-26:-"   # ДОСЛОВНО из journal.json → pending_questions[].episode_id
    reason: "держу до отчёта за 3 кв."        # фраза владельца; «пропустить» → null
    answered: 2026-10-03

# incidents.yaml
schema: decision-journal-incidents@1
incidents:
  - id: inc-2026-10-03-1
    date: 2026-10-03
    what: "advisor взял не ту базу для доли облигаций"
    category: data            # data | process | forecast | execution
    found_by: owner           # owner | advisor | script
    cost_rub: null            # если известна цена ошибки
    related: weekly-review-bond-2026-10-03.yaml   # опционально

# theses.yaml
schema: decision-journal-theses@1
theses:
  - id: rub-weakening-2026-10
    opened: 2026-10-07
    check_date: 2027-10-01
    event: "USD/RUB ЦБ на check_date выше порога безубыточности"
    threshold: "…"            # число и как посчитано (план §5 п. 6: (1+r_RUB)/(1+r_FX) − 1)
    p: 0.7                    # вероятность владельца, 0..1
    rationale: "…"
    status: open              # open | closed
  - id: rub-weakening-2026-10
    status: closed
    closed: 2027-10-01
    outcome: true             # событие наступило?
    note: "…"
```

## P3. Проверки перед записью (hard-block)

- `episode_id` в refusals есть в выборке журнала по бумаге — `python3 {ru-portfolio-advisor}/scripts/journal_digest.py
  --root {root} --key <бумага из episode_id> --limit 50` (`episodes[].episode_id`; журнал целиком не читать) — иначе не
  писать и показать ближайшие совпадения. Повторный ответ на тот же эпизод — не писать (вопрос один раз).
- `category` / `found_by` / `status` — только из перечислений выше.
- `p` в theses — число в [0, 1]; `check_date` позже `opened`.
- Даты — ISO; mojibake — отказ.

## P4. Запись

Транспорт — как везде (Read/Write через Synology mount, без Bash). Файла нет → создать с полем `schema`.
Прочитать → дописать запись в конец списка → записать целиком. `INDEX.md` и `_sync_log.md` не трогать:
это служебные входы скрипта, а не артефакты библиотеки.

В чате — одна строка: «Записано в `decision-journal/<файл>`: <кратко>». После записи refusals предложить
не нужно ничего: скрипт подхватит ответ при следующем обновлении журнала.
