# Workflow Q — справочник бумаг (класс, дата листинга)

Справочник `Portfolio/security-attrs.json` (`security-attrs@1`): класс бумаги (`ticker_class`), дата первых торгов на
Мосбирже (`listed_at` — для IPO-паузы: 8 кварталов без докупок) и одна фраза (`note`). Пишет только скрипт
`scripts/security_attrs.py` — на mount сам, атомарно, после валидатора; модель файл не открывает и не пишет.

Триггеры: «поменяй класс X на …», «X — не IPO, а переезд», «дата листинга X — …», «покажи бумаги класса ipo».

```bash
python3 scripts/security_attrs.py set  --root {root} --key X [--class <ticker_class>|none] \
  [--listed-at ГГГГ-ММ-ДД|none] [--note "одна фраза"|none] --by <owner|mode_N|script>
python3 scripts/security_attrs.py get  --root {root} --key X
python3 scripts/security_attrs.py list --root {root} [--class ipo]
```

- `--by` — только код кодлиста `actor`: по слову владельца в чате — `owner`; из разбора — свой режим (`mode_4`, `mode_8` …); разработчик из Claude Code — `script`.
- Не названное поле не меняется; `none` очищает поле. Класс — только из кодлиста `ticker_class`
  (`bluechip`, `mid_cap`, `ipo`, `fund_zpif`, `fund`, `bond`); нового кода скрипт не примет — новый класс добавляет
  разработчик в кодлисты.
- Нет файла — ошибка «справочник не заполнен» (его разово заполняет миграция при переключении); скрипт файл не создаёт.
- Сообщение владельцу — «было → стало» из вывода (`before` / `record`) и что это значит: класс `ipo` с `listed_at`
  моложе 8 кварталов закрывает докупку при любом вердикте.
- `_sync_log.md` — строка через `scripts/update_index.py sync-log`: «справочник бумаг: X — {поля}».
