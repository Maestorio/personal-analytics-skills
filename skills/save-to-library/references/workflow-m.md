# Workflow M — условия и решения по слову владельца

Условия «жди X → сделай Y» (`Portfolio/conditions.yaml`, `conditions@2`) и решения по бумаге (`Portfolio/decisions/`,
`decision@1`) пишут только скрипты этого скилла — на mount сами, временным файлом и `os.replace`; модель эти файлы
не открывает и не пишет, видит только JSON-вывод. Файла гейтов и директив гейта нет: гейт акции — проекция её
последнего решения. Состояние условия («сделал», «не актуально», отложить, вернуть) — кнопки владельца на сайте.

Корень `{root}` — в Cowork `$HOME/mnt/Claude-Memory` (путь узнаётся через `request_cowork_directory`, в команде не
зашивается). Ошибка скрипта (`ok: false`) — показать `error`/`errors` владельцу; ничего не записано, вручную не дописывать.

## M1. Условия — `scripts/apply_condition.py`

Вызывает и Режим 9 `ru-portfolio-advisor` (таблица «фраза → команда» и поля входа — его
`references/mode-9-conditions.md`), и сохранение отчёта (Workflow N).

```bash
echo '<JSON>' | python3 scripts/apply_condition.py <add|edit|withdraw|digest|crosscheck|validate> --root {root} \
  --by <owner|mode_N> [--plan <план %>] [--snapshot <portfolio-….json>] [--key K1,K2] [--today ГГГГ-ММ-ДД]
```

- `add` — новое условие, `id` ставит скрипт; `edit {"id", <меняемые поля>, "note"}` — новая версия с тем же `id`
  (закрытое — ошибка, нужно `add`); `withdraw {"id", "reason"}` — снятие с причиной; `digest` / `list` — выборка
  модулем (а); `crosscheck` — вердикты обзора против ждущих условий; `validate` — проверка файла.
- Удаления нет: снятое остаётся в файле с `withdrawn`. Резервные копии в `.backups/` не пишутся — замену делает
  скрипт атомарно, история версий — в самом файле.
- `source` новой версии `edit` без `source` во входе: `--by owner` → `{kind: owner, doc: null}`, режим →
  `{kind: report, doc: null}`.
- **Правка условий сама перештамповывает обзор того же дня** (R33): `add`/`edit`/`withdraw` по бумаге из обзора
  недели с `review_date` = сегодня (МСК) пересчитывают его приоритет (`restamped: [{doc, priority_changed}]`);
  ошибка штампа — `restamp_warnings`, правка условия остаётся. Порядок при сохранении обзора: правки условий →
  штамп обзора → `validate --root` (Workflow F3).

## M2. Решение по слову владельца — `scripts/decision_write.py owner`

Триггеры: «подтверждаю держать X», «держим X до …», «по X решение — продать». При `ai_mode: on` решение владельца
без разбора закрытую гейтом качества докупку не открывает (может закрыть) — открывает только разбор советника; сказать
это владельцу, если он просит «подтвердить держать», чтобы открыть докупку.

```bash
python3 scripts/decision_write.py owner --root {root} --key X --verdict HOLD --note "подтверждено владельцем: …" \
  [--target-pct N] [--review-by ГГГГ-ММ-ДД] [--keep-open id1,id2]
```

Скрипт ставит `id`, время, `author: owner`, `source.kind: owner` и закрывает сработавшие условия ключа
(`conditions_resolved`, кроме `--keep-open`). `--review-by` — 7–180 дней; без него срок 60 дней. Сообщение
владельцу — вердикт и гейт словами (`references/gate-status-labels.md`), не кодами.

Решения из разбора пишет Workflow N (`decision_write.py from-report`), не этот workflow.

## M3. Индексы

- `_sync_log.md` — строка через `scripts/update_index.py`: «условие {id}: {add|edit|withdraw}» или «решение {id}
  (owner)»; при непустом `restamped` — в ту же строку «перештамповано: {файл обзора} ({priority_changed} или «без
  изменений»)». Скрипт условий в журнал не пишет.
- `Portfolio/INDEX.md` не меняется.

## Anti-patterns

- ❌ Читать или писать `conditions.yaml` / файлы `decisions/` инструментами Read/Write/Edit — только скриптами.
- ❌ Править состояние условия (сработало, «сделал», отложить) — это кнопки сайта.
- ❌ Новое условие вместо переноса сработавшего — перенос = `edit` того же `id`.
- ❌ Решение обзора недели файлом решения — обзор решений не пишет.
