#!/usr/bin/env python3
"""tools/zenmoney_payee_map.py — словарь «текст банка → место» (2026-10-07: на странице
«PRODUKTY ERMOLINO» вместо «Ермолино»: CSV «Кому» — сырой текст банка, если место поставил
плагин). Текст с одним местом — в by_text; один текст у разных мест — поштучно в by_op;
место снято в ZenMoney — пусто («без места»); совпадающие с местом строки в словарь не идут;
перевод не сопоставляется; одинаковые суммы в один день различаются по тексту."""
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "tools"))
import zenmoney_payee_map as pm  # noqa: E402

H = "date;categoryName;payee;comment;outcomeAccountName;outcome;outcomeCurrencyShortTitle;incomeAccountName;income;incomeCurrencyShortTitle;createdDate;changedDate;qrCode\n"
passed = failed = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name} {extra}")


def row(date, payee, amount, acc="Карта", inc_acc="Карта", inc="0"):
    return f'{date};"Питание";"{payee}";;"{acc}";"{amount}";RUB;"{inc_acc}";"{inc}";RUB;"{date} 10:00:00";"{date} 10:00:00";\n'


def op(i, date, amount, orig, mid):
    return {"id": f"t{i}", "date": date, "expense": {"accountId": "a1", "amount": amount},
            "originalPayee": orig, "merchantId": mid}


refs = {"accounts": {"a1": {"name": "Карта"}},
        "merchants": {"m1": {"name": "Ермолино"}, "m2": {"name": "Азбука вкуса"},
                      "m3": {"name": "AV .AZBUKAVKUSA"}, "m4": {"name": "Метро"}, "m5": {"name": "Пятёрочка"}}}
data = [op(1, "2026-05-01", 500, "PRODUKTY ERMOLINO", "m1"),
        op(2, "2026-05-21", 700.5, "PRODUKTY ERMOLINO", "m1"),
        op(3, "2026-03-02", 300, "PRODUKTY ERMOLINO", "m1"),         # место задано руками → CSV «Ермолино»
        op(4, "2026-04-01", 900, "AV AZBUKAVKUSA", "m2"),
        op(5, "2026-04-02", 800, "AV AZBUKAVKUSA", "m3"),
        op(6, "2026-04-03", 800, "AV AZBUKAVKUSA", "m3"),
        op(7, "2026-04-04", 3000, "427938******4223", None),         # место снято
        op(8, "2026-04-05", 42, "Moskva Metro", "m4"),
        op(9, "2026-04-05", 42, "PYATEROCHKA 231", "m5"),            # та же сумма в тот же день
        ]
csv_text = (H + row("2026-05-01", "PRODUKTY ERMOLINO", "500") + row("2026-05-21", "PRODUKTY ERMOLINO", "700,5")
            + row("2026-03-02", "Ермолино", "300") + row("2026-04-01", "AV AZBUKAVKUSA", "900")
            + row("2026-04-02", "AV AZBUKAVKUSA", "800") + row("2026-04-03", "AV AZBUKAVKUSA", "800")
            + row("2026-04-04", "427938******4223", "3000") + row("2026-04-05", "Moskva Metro", "42")
            + row("2026-04-05", "PYATEROCHKA 231", "42")
            + row("2026-04-06", "", "5000", acc="Карта", inc_acc="Вклад", inc="5000"))  # перевод

with tempfile.TemporaryDirectory() as t:
    pages = Path(t, "pages"); pages.mkdir()
    (pages / "p001.json").write_text(json.dumps({"data": data, "references": refs}), encoding="utf-8")
    c = Path(t, "x.csv"); c.write_text("﻿" + csv_text, encoding="utf-8")
    out = Path(t, "map.json")
    rc = pm.main(["build", "--csv", str(c), "--pages", str(pages), "--out", str(out)])
    m = json.loads(out.read_text(encoding="utf-8"))
    check("build — код 0 и схема", rc == 0 and m["schema"] == pm.SCHEMA, m)
    check("текст банка с одним местом — в by_text", m["by_text"].get("PRODUKTY ERMOLINO") == "Ермолино", m["by_text"])
    check("строка, где «Кому» = место, в словарь не идёт", "Ермолино" not in m["by_text"]
          and not any(k.endswith("|Ермолино") for k in m["by_op"]), m)
    check("место снято → пусто (без места)", m["by_text"].get("427938******4223") == "", m["by_text"])
    check("один текст у двух мест — не в by_text, поштучно в by_op",
          "AV AZBUKAVKUSA" not in m["by_text"] and len([k for k in m["by_op"] if "AV AZBUKAVKUSA" in k]) == 3, m)
    check("одинаковые суммы в один день различены по тексту",
          m["by_text"].get("PYATEROCHKA 231") == "Пятёрочка" and m["by_text"].get("Moskva Metro") == "Метро", m["by_text"])
    check("заменено 8, совпало 1, без неоднозначных",
          m["stats"].get("заменено") == 8 and m["stats"].get("совпало с местом") == 1
          and "неоднозначно — оставлен текст CSV" not in m["stats"], m["stats"])

    fix = pm.load(out)
    check("load: by_text", fix("2026-09-16", "Карта", 1, "PRODUKTY ERMOLINO") == "Ермолино")
    check("load: by_op раньше by_text", fix("2026-04-02", "Карта", 800, "AV AZBUKAVKUSA") == "AV .AZBUKAVKUSA"
          and fix("2026-04-01", "Карта", 900.0, "AV AZBUKAVKUSA") == "Азбука вкуса")
    check("load: неизвестный текст — как есть", fix("2026-04-01", "Карта", 1, "НОВОЕ МЕСТО") == "НОВОЕ МЕСТО")
    check("load: нет файла — None", pm.load(Path(t, "нет.json")) is None)
    check("csv_side: перевод — None", pm.csv_side({"outcome": "5", "income": "5", "outcomeAccountName": "A",
                                                     "incomeAccountName": "B"}) is None)

# дозагрузка: операция 5 перенесена на «Азбуку вкуса», место m3 переименовано — поздний файл побеждает
with tempfile.TemporaryDirectory() as t:
    pages = Path(t, "pages"); pages.mkdir()
    (pages / "p001.json").write_text(json.dumps({"data": data, "references": refs}), encoding="utf-8")
    upd = dict(op(5, "2026-04-02", 800, "AV AZBUKAVKUSA", "m2"))
    (pages / "u20261008-001.json").write_text(json.dumps({"data": [upd, op(6, "2026-04-03", 800, "AV AZBUKAVKUSA", "m3")],
        "references": {"accounts": refs["accounts"], "merchants": {"m2": {"name": "Азбука вкуса"}, "m3": {"name": "Азбука вкуса (2)"}}}}),
        encoding="utf-8")
    rows, span, nf = pm.load_pages([pages])
    got = {(d, amt): name for d, _a, amt, _o, name in rows}
    check("дозагрузка: операция — из позднего файла", got[("2026-04-02", 800)] == "Азбука вкуса" and len(rows) == len(data), got)
    check("дозагрузка: новое название места", got[("2026-04-03", 800)] == "Азбука вкуса (2)", got)

# changed: окна дат по changedDate (правка места без смены «Кому»), новой операции; до --from — не берётся
def crow(date, payee, amount, created, changed_at):
    return f'{date};"Питание";"{payee}";;"Карта";"{amount}";RUB;"Карта";"0";RUB;"{created}";"{changed_at}";\n'

with tempfile.TemporaryDirectory() as t:
    old, new = Path(t, "o.csv"), Path(t, "n.csv")
    base = [("2019-05-01", "X", 1, "2019-05-01 10:00:00", "2019-05-01 10:00:00"),
            ("2024-03-01", "AV AZBUKAVKUSA", 900, "2024-03-01 10:00:00", "2024-03-01 10:00:00"),
            ("2024-03-02", "Y", 5, "2024-03-02 10:00:00", "2024-03-02 10:00:00"),
            ("2025-07-01", "Z", 7, "2025-07-01 11:00:00", "2025-07-01 11:00:00")]
    old.write_text("\ufeff" + H + "".join(crow(*r) for r in base), encoding="utf-8")
    nb = [base[0][:4] + ("2026-10-07 13:53:01",), base[1][:4] + ("2026-10-07 13:53:01",), base[2], base[3],
          ("2026-10-01", "Новое", 9, "2026-10-01 12:00:00", "2026-10-01 12:00:00")]
    new.write_text("\ufeff" + H + "".join(crow(*r) for r in nb), encoding="utf-8")
    r = pm.changed(old, new)
    check("changed: правка без смены «Кому» и новая операция; 2019 — нет",
          r["operations"] == 2 and r["days"] == 2, r)
    check("changed: соседние дни склеены в одно окно", [(w["from"], w["to"]) for w in r["windows"]]
          == [("2024-03-01", "2026-10-01")], r)
    # одинаковые покупки в разные дни (время создания 00:00:00) — правка одной не теряется (2026-10-07: 16.04.2024)
    twin = [("2024-04-16", "AV AZBUKAVKUSA", 935, "2024-04-16 00:00:00", "2024-04-16 00:00:00"),
            ("2024-05-20", "AV AZBUKAVKUSA", 935, "2024-05-20 00:00:00", "2024-05-20 00:00:00")]
    o2, n2 = Path(t, "o2.csv"), Path(t, "n2.csv")
    o2.write_text("\ufeff" + H + "".join(crow(*r) for r in twin), encoding="utf-8")
    n2.write_text("\ufeff" + H + crow(*twin[0][:4], "2026-10-07 14:54:59") + crow(*twin[1]), encoding="utf-8")
    r3 = pm.changed(o2, n2)
    check("changed: одинаковые покупки в разные дни — изменённая найдена", r3["days"] == 1
          and r3["windows"][0]["from"] == "2024-04-16", r3)
    r2 = pm.changed(old, new, page=2)
    check("changed: окно не больше страницы", len(r2["windows"]) == 2, r2)

print(f"test_zenmoney_payee_map: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
