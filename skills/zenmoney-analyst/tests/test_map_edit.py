#!/usr/bin/env python3
"""map_edit.py — единственный писатель карты ZenMoney (решение 2026-10-06).

Зачем: карта задаёт правила всех будущих итогов; до этого её сохранял пользователь
вручную — 8 копий за два дня и ID без кавычек-кода у одной поездки. Скрипт правит
только строки названного раздела, пишет только с хешем увиденной карты, делает копию.
"""
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import map_edit as me  # noqa: E402

ok = fail = 0


def check(name, cond, extra=None):
    global ok, fail
    if cond:
        ok += 1
        print(f"  [OK] {name}")
    else:
        fail += 1
        print(f"  [FAIL] {name} {extra if extra is not None else ''}")


MAP = """# Приватная карта ZenMoney

## Мета

- Обновлено: 2026-10-05, вечер
- Предыдущая версия: `zenmoney-map.backup-2026-10-05d.md`
- Схема карты: тонкая

---

## Поездки

Текст про поездки.

| Поездка | ID | Даты | Кошелёк | Заметки |
|---|---|---|---|---|
| #Сибирь'24 / #Сахалин'24 | `a` / `b` | | | Разные поездки |
| #Вьетнам'26 | `c` | 2026-09-04…2026-09-16 | | |

---

## Известные странности данных

- Первая.
- Вторая.

---

## Проверки

| Проверка | Дата |
|---|---|
| охват | 2026-10-01 |
"""


def cli(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = me.main(argv)
    head = buf.getvalue().split("\n}\n", 1)
    return rc, json.loads(head[0] + ("\n}" if len(head) > 1 else "")), (head[1] if len(head) > 1 else "")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        mp = Path(tmp) / "zenmoney-map.md"
        mp.write_text(MAP, encoding="utf-8")
        base = ["--map", str(mp), "--date", "2026-10-06"]
        rc, h, _ = cli(["hash"] + base)
        H = h["sha256"]

        print("Dry-run и добавление строки")
        row = "| #Сочи'20 | `d` | 2020-09-07…2020-09-15 | | |"
        rc, out, diff = cli(["add-row", "--section", "Поездки", "--row", row, "--note", "даты поездок"] + base)
        check("dry-run не пишет, показывает diff", rc == 0 and not out["written"] and mp.read_text() == MAP
              and "+" + row in diff, diff)
        rc, out, _ = cli(["add-row", "--section", "Поездки", "--row", row, "--note", "даты поездок", "--write",
                          "--expect", H] + base)
        t = mp.read_text()
        check("строка — в конец таблицы раздела", rc == 0 and t.index(row) > t.index("#Вьетнам'26")
              and t.index(row) < t.index("## Известные"), t)
        check("остальное не тронуто", t.replace(row + "\n", "").replace(
            "- Обновлено: 2026-10-06 (даты поездок)", "- Обновлено: 2026-10-05, вечер").replace(
            "zenmoney-map.backup-2026-10-06.md", "zenmoney-map.backup-2026-10-05d.md") == MAP)
        check("«Предыдущая версия» — на сделанную копию", "- Предыдущая версия: `zenmoney-map.backup-2026-10-06.md`" in t)
        check("«Обновлено» в Мета", "- Обновлено: 2026-10-06 (даты поездок)" in t)
        check("копия прежней версии", (Path(tmp) / "zenmoney-map.backup-2026-10-06.md").read_text() == MAP)

        print("Хеш: запись только по увиденной карте")
        rc, out, _ = cli(["add-row", "--section", "Поездки", "--row", row, "--write", "--expect", H] + base)
        check("карта изменилась после чтения — blocking, ничего не записано", rc == 2 and mp.read_text() == t, out)
        rc, out, _ = cli(["add-row", "--section", "Поездки", "--row", row, "--write"] + base)
        check("запись без --expect — blocking", rc == 2, out)
        H2 = me.sha(t)

        print("Замена и удаление строки")
        new = "| #Сибирь'24 / #Сахалин'24 | `a` / `b` | 2024-05-28…2024-06-15 / 2024-08-31…2024-09-14 | | Разные поездки |"
        rc, out, _ = cli(["set-row", "--section", "Поездки", "--match", "#Сибирь'24", "--row", new,
                          "--write", "--expect", H2] + base)
        t2 = mp.read_text()
        check("set-row меняет ровно строку", rc == 0 and new in t2 and "| | | Разные поездки |" not in t2, out)
        check("вторая копия за день — с буквой", (Path(tmp) / "zenmoney-map.backup-2026-10-06a.md").exists())
        rc, out, _ = cli(["set-row", "--section", "Поездки", "--match", "#", "--row", new] + base)
        check("неоднозначный --match — blocking", rc == 2, out)
        rc, out, _ = cli(["set-row", "--section", "Поездки", "--match", "#Нет'99", "--row", new] + base)
        check("нет строки — blocking", rc == 2, out)
        rc, out, _ = cli(["remove-row", "--section", "Поездки", "--match", "#Сочи'20", "--write",
                          "--expect", me.sha(t2)] + base)
        check("remove-row удаляет строку", rc == 0 and "#Сочи'20" not in mp.read_text(), out)

        print("Гейты строки и раздела")
        rc, out, _ = cli(["add-row", "--section", "Поездки", "--row", "| мало | колонок |"] + base)
        check("число колонок ≠ шапке — blocking", rc == 2, out)
        rc, out, _ = cli(["add-row", "--section", "Поездки", "--row", "без черты"] + base)
        check("строка без «|» — blocking", rc == 2, out)
        rc, out, _ = cli(["add-row", "--section", "Нет такого", "--row", row] + base)
        check("нет раздела — blocking", rc == 2, out)
        rc, out, _ = cli(["add-row", "--section", "Известные странности данных", "--row", row] + base)
        check("в разделе нет таблицы — blocking", rc == 2, out)

        print("Пункт списка")
        t3 = mp.read_text()
        rc, out, _ = cli(["add-line", "--section", "Известные странности данных", "--line", "- Третья.",
                          "--write", "--expect", me.sha(t3)] + base)
        t4 = mp.read_text()
        check("пункт — в конец раздела, до «---»", rc == 0 and t4.index("- Третья.") > t4.index("- Вторая.")
              and t4.index("- Третья.") < t4.index("## Проверки"), t4)
        rc, out, _ = cli(["add-row", "--section", "Проверки", "--row", "| охват-2 | 2026-10-06 |", "--write",
                          "--expect", me.sha(t4)] + base)
        check("таблица в последнем разделе", rc == 0 and mp.read_text().rstrip().endswith("| охват-2 | 2026-10-06 |"))

    print(f"\nИтого: {ok} OK, {fail} FAIL")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
