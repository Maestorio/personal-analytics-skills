#!/usr/bin/env python3
"""
Регрессионные тесты истории аудитов ZenMoney: audit_month.py --history (перепроверка
прошлых замечаний, доля исправленного, возраст, тренд) и audit_history.py (запись
history.json / accepted.json: агрегаты без привязки, гейты, бэкап, атомарность).

Синтетические данные. Запуск из корня репозитория:
    python3 skills/zenmoney-analyst/tests/test_audit_history.py
Без внешних зависимостей.
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "skills" / "zenmoney-analyst" / "scripts"))
import audit_history as ah  # noqa: E402
import audit_month as am  # noqa: E402

PASSED = FAILED = 0


def check(name, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  [OK] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name} {detail}")


ACC = {"acc-card": {"name": "Карта", "instrument": "RUB", "type": "card", "isInBalance": True, "isOtherUser": False}}
CATS = {
    "c-cafe": {"name": "Кафе", "parentId": None, "isArchived": False},
    "c-corr": {"name": "Корректировка", "parentId": None, "isArchived": False},
    "c-trip": {"name": "#Страна'26", "parentId": None, "isArchived": False},
}


def ex(i, dt, amt, cat=None, **kw):
    o = {"id": i, "date": dt, "expense": {"accountId": "acc-card", "amount": amt}}
    if cat:
        o["categoryId"] = cat
    o.update(kw)
    return o


def page(ops):
    return {"data": ops, "nextCursor": None,
            "references": {"user": {"currency": "RUB", "monthStartDay": 1}, "accounts": ACC,
                           "categories": CATS, "merchants": {}}}


def jdump(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return str(path)


def cli(mod, argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = mod.main(argv)
    return rc, json.loads(buf.getvalue())


# Август: 3 замечания (без категории, проект основной категорией, корректировка)
AUG = [
    ex("a-ok", "2026-08-03", 100, "c-cafe"),
    ex("a-nocat", "2026-08-05", 500),
    ex("a-proj", "2026-08-06", 700, "c-trip"),
    ex("a-corr", "2026-08-07", 300, "c-corr"),
]
# Июнь — давний месяц вне окна сентябрьского аудита
JUN = [ex("j-nocat", "2026-06-10", 50)]


def main():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        hist = t / "audit" / "history.json"
        accp = t / "audit" / "accepted.json"

        print("1. Июньский аудит без истории → первая запись")
        rc, run_jun = cli(am, ["month", "--month", "2026-06", "--as-of", "2026-07-02",
                                "--tx", jdump(t / "jun.json", page(JUN)), "--history", str(hist)])
        check("без файла истории — «нет истории»", run_jun["coverage"]["history"] == "нет истории" and run_jun["history"] is None)
        check("замечания — ключи «проверка:id»", run_jun["issues"] == {"A3:j-nocat": {"check": "A3", "month": "2026-06"}}, run_jun["issues"])
        rc, s = cli(ah, ["apply", "--run", jdump(t / "r-jun.json", run_jun), "--history", str(hist), "--date", run_jun["as_of"]])
        check("dry-run ничего не пишет", rc == 0 and not hist.exists() and s["written"] is False, s)
        rc, s = cli(ah, ["apply", "--run", str(t / "r-jun.json"), "--history", str(hist), "--date", run_jun["as_of"], "--write"])
        check("запись создаёт папку и файл", rc == 0 and hist.exists() and s["new"] == 1, s)
        rec = json.loads(hist.read_text(encoding="utf-8"))["records"][0]
        check("места месяца — только числа по видам (2.15.0)", isinstance(rec.get("places_counts"), dict)
              and set(rec["places_counts"]) <= ah.PLACES_KINDS
              and all(v is None or isinstance(v, int) for v in rec["places_counts"].values()), rec.get("places_counts"))
        check("без мест в прогоне — places_counts None", ah.record_from_run({**run_jun, "places": None})["places_counts"] is None)

        print("2. Август — с историей")
        rc, run_aug = cli(am, ["month", "--month", "2026-08", "--as-of", "2026-09-02",
                                "--tx", jdump(t / "aug.json", page(JUN + AUG)), "--history", str(hist)])
        h = run_aug["history"]
        check("окно с 10 июня — июнь не покрыт целиком → не перепроверено",
              h["keys"]["not_rechecked"] == ["A3:j-nocat"] and h["keys"]["fixed"] == [], h["keys"])
        rc, s = cli(ah, ["apply", "--run", jdump(t / "r-aug.json", run_aug), "--history", str(hist), "--date", run_aug["as_of"], "--write"])
        check("август: 3 новых, июньское остаётся открытым", s["new"] == 3 and s["fixed"] == 0 and s["open_total"] == 4, s)
        check("бэкап прежней версии", hist.with_suffix(".json.bak").exists())

        print("3. Принятое исключение")
        rc, s = cli(ah, ["accept", "--accepted", str(accp), "--add", "a-corr", "A2", "корректировка кошелька — норма",
                         "--date", "2026-09-30", "--write"])
        check("исключение добавлено", rc == 0 and s["added"] == 1)
        rc, s = cli(ah, ["accept", "--accepted", str(accp), "--add", "a-corr", "A2", "повтор", "--date", "2026-09-30"])
        check("повтор не добавляется", s["added"] == 0)
        rc, s = cli(ah, ["accept", "--accepted", str(accp), "--add", "a-corr", "A2", "перевод себе вне учёта",
                         "--kind", "transfer_out", "--date", "2026-09-30"])
        check("повтор с --kind обновляет вид (перепометка)", rc == 0 and s["updated"] == 1 and s["added"] == 0, s)
        rc, s = cli(ah, ["accept", "--accepted", str(accp), "--add", "a-nocat", "A3", "x", "--kind", "unknown",
                         "--date", "2026-09-30"])
        check("вид только для корректировок (A2) — blocking", rc == 2, s)

        print("4. Сентябрь: a-nocat исправлен, a-proj нет, a-corr принят, июнь вне окна")
        aug_fixed = [ex("a-ok", "2026-08-03", 100, "c-cafe"), ex("a-nocat", "2026-08-05", 500, "c-cafe"),
                     ex("a-proj", "2026-08-06", 700, "c-trip"), ex("a-corr", "2026-08-07", 300, "c-corr")]
        sep = [ex("s-ok", "2026-09-10", 1000, "c-cafe"), ex("s-nocat", "2026-09-12", 200)]
        window = [o for o in aug_fixed] + sep   # окно с 2026-08-03 — июнь не входит
        rc, run_sep = cli(am, ["month", "--month", "2026-09", "--as-of", "2026-10-05",
                                "--tx", jdump(t / "sep.json", page(window)), "--history", str(hist),
                                "--window-from", "2026-07-07",
                                "--accepted", str(accp)])
        k = run_sep["history"]["keys"]
        check("исправленное найдено перепроверкой августа", k["fixed"] == ["A3:a-nocat"], k)
        check("неисправленное — открыто", k["still_open"] == ["A4:a-proj"], k)
        check("принятое — accepted", k["accepted"] == ["A2:a-corr"], k)
        check("июнь вне окна — не перепроверен (не «исправлен»)", k["not_rechecked"] == ["A3:j-nocat"], k)
        hs = run_sep["history"]
        check("доля исправленного = 1/2 перепроверенных", hs["fixed_share"] == 0.5 and hs["rechecked_count"] == 2, hs)
        check("возраст — всех открытых, включая не перепроверенный июнь (сумма = открытым): s-nocat свежее, a-proj 1–3 мес, июнь дольше", hs["open_by_age"] == {"lt_1m": 1, "1_3m": 1, "gt_3m": 1}, hs["open_by_age"])
        check("тренд: июнь и август", [r["month"] for r in hs["trend"]] == ["2026-06", "2026-08"], hs["trend"])
        check("предыдущий месяц", hs["previous_month"] == "2026-08")
        rc, s = cli(ah, ["apply", "--run", jdump(t / "r-sep.json", run_sep), "--history", str(hist), "--date", run_sep["as_of"], "--write"])
        check("сводка apply: 1 исправлено, 1 принято, 1 новое; открыты a-proj, июнь, s-nocat",
              s["fixed"] == 1 and s["accepted"] == 1 and s["new"] == 1 and s["open_total"] == 3, s)
        H = json.loads(hist.read_text(encoding="utf-8"))
        check("статусы в реестре", H["issues"]["A3:a-nocat"]["status"] == "fixed" and H["issues"]["A3:a-nocat"]["closed_at"] == "2026-10-05"
              and H["issues"]["A2:a-corr"]["status"] == "accepted" and H["issues"]["A3:j-nocat"]["status"] == "open")
        check("first_seen сохраняется", H["issues"]["A4:a-proj"]["first_seen"] == "2026-09-02")
        check("записи по месяцам", [r["month"] for r in H["records"]] == ["2026-06", "2026-08", "2026-09"])
        rec = H["records"][-1]
        check("запись — только агрегаты", set(rec) <= ah.RECORD_KEYS and rec["fixed_share"] == 0.5, sorted(rec))
        blob = hist.read_text(encoding="utf-8")
        check("в истории нет названий счетов и категорий", "Карта" not in blob and "Кафе" not in blob and "Страна" not in blob)

        print("5. Повторный аудит того же месяца — замена, а не дубль")
        rc, s = cli(ah, ["apply", "--run", str(t / "r-sep.json"), "--history", str(hist), "--date", run_sep["as_of"]])
        check("запись заменена", s["record"] == "заменена" and s["records_total"] == 3, s)

        print("6. Вернувшееся замечание открывается заново")
        sep_back = window[:1] + [ex("a-nocat", "2026-08-05", 500)] + window[2:]
        rc, run_b = cli(am, ["month", "--month", "2026-08", "--as-of", "2026-10-06",
                              "--tx", jdump(t / "back.json", page(sep_back)), "--history", str(hist), "--accepted", str(accp),
                              "--window-from", "2026-07-07"])
        rc, s = cli(ah, ["apply", "--run", jdump(t / "r-back.json", run_b), "--history", str(hist), "--date", run_b["as_of"]])
        check("reopened", s["reopened"] == 1, s)
        hb = run_b["history"]
        check("повторный аудит месяца помечен", hb["rerun_of_month"] is True, hb)
        check("замечания самого месяца не входят в долю исправленного",
              hb["rechecked_count"] == 0 and hb["fixed_share"] is None and hb["rerun_rechecked_count"] == 2, hb)  # a-proj (август) + s-nocat (сентябрь, не раньше аудируемого)
        check("первый аудит месяца — не повторный", run_sep["history"]["rerun_of_month"] is False)

        print("7. Гейты")
        no_hist = dict(run_sep, history=None)
        rc, s = cli(ah, ["apply", "--run", jdump(t / "r-nohist.json", no_hist), "--history", str(hist)])
        check("аудит без --history при открытых замечаниях — blocking", rc == 2 and "--history" in s["blocking"], s)
        rc, s = cli(ah, ["apply", "--run", jdump(t / "bad.json", {"schema": "x"}), "--history", str(hist)])
        check("чужой вход — blocking", rc == 2)
        seen = ah.read(hist, {})[1]
        hist.write_text(hist.read_text(encoding="utf-8").replace('"updated"', '"updated" ', 1), encoding="utf-8")
        try:
            ah.write_atomic(hist, {"x": 1}, seen)
            check("файл изменился после чтения — запись запрещена", False)
        except ah.Blocking:
            check("файл изменился после чтения — запись запрещена", True)
        bad = json.loads(hist.read_text(encoding="utf-8"))
        bad["records"][0]["account_name"] = "Карта"
        check("лишнее поле в записи ловится", any("недопустимые поля" in e for e in ah.validate_history(bad)))
        bad2 = json.loads(hist.read_text(encoding="utf-8"))
        bad2["issues"]["A3:a-nocat"]["check"] = "A4"
        check("ключ ↔ проверка сверяются", any("не совпадает" in e for e in ah.validate_history(bad2)))
        bad3 = json.loads(hist.read_text(encoding="utf-8"))
        bad3["records"].append(dict(bad3["records"][0]))
        check("повтор месяца ловится", any("повторяются" in e for e in ah.validate_history(bad3)))
        bad4 = json.loads(hist.read_text(encoding="utf-8"))
        bad4["records"][0]["places_counts"] = {"rename": ["Ермолино"]}
        check("в places_counts только числа — названия ловятся", any("places_counts" in e for e in ah.validate_history(bad4)))
        rc, s = cli(ah, ["accept", "--accepted", str(accp), "--add", "x", "Z9", "?", "--date", "2026-10-01"])
        check("неизвестная проверка в исключении — blocking", rc == 2)
        rc, s = cli(ah, ["validate", "--history", str(hist), "--accepted", str(accp)])
        check("validate живых файлов", rc == 0 and s["ok"], s)

        print("9. Правила статистики: ответ «это разовая» пишет скилл, не пользователь")
        rp = t / "spending-rules.json"
        rc, s = cli(ah, ["rules", "--rules", str(rp), "--date", "2026-10-05",
                         "--one-off", "op-1", "2026-08", "холодильник", "--regular-big", "cat-rent", "аренда"])
        check("rules: dry-run не пишет", rc == 0 and not rp.exists() and s["one_off_total"] == 1, s)
        rc, s = cli(ah, ["rules", "--rules", str(rp), "--date", "2026-10-05",
                         "--one-off", "op-1", "2026-08", "холодильник", "--regular-big", "cat-rent", "аренда", "--write"])
        check("rules: запись", rc == 0 and rp.exists() and s["written"], s)
        rc, s = cli(ah, ["rules", "--rules", str(rp), "--date", "2026-10-06", "--one-off", "op-1", "2026-08", "холодильник Bosch",
                         "--write"])
        r = json.loads(rp.read_text(encoding="utf-8"))
        check("rules: повтор ID — замена, не дубль", len(r["one_off"]) == 1 and r["one_off"][0]["note"] == "холодильник Bosch", r)
        rc, s = cli(ah, ["rules", "--rules", str(rp), "--date", "2026-10-06", "--remove", "op-1", "--write"])
        check("rules: снять ошибочное", rc == 0 and s["removed"] == 1 and json.loads(rp.read_text())["one_off"] == [], s)
        rc, s = cli(ah, ["rules", "--rules", str(rp), "--date", "2026-10-06", "--remove", "nope"])
        check("rules: снимать нечего — blocking", rc == 2, s)
        rc, s = cli(ah, ["rules", "--rules", str(rp), "--date", "2026-10-06", "--one-off", "op-2", "2026-8", "x"])
        check("rules: плохой месяц — blocking", rc == 2, s)
        rc, s = cli(ah, ["rules", "--rules", str(rp), "--date", "2026-10-06"])
        check("rules: пустая команда — blocking", rc == 2, s)
        # 2026-10-06: «VDSina — всегда разовые» — правило по месту платежа, не по операции
        rc, s = cli(ah, ["rules", "--rules", str(rp), "--date", "2026-10-06",
                         "--one-off-merchant", "m1_vds", "хостинг раз в год", "--write"])
        r = json.loads(rp.read_text())
        check("rules: разовое место платежа", rc == 0 and s["one_off_merchants_total"] == 1
              and r["one_off_merchants"] == [{"merchant_id": "m1_vds", "note": "хостинг раз в год", "date": "2026-10-06"}], r)
        rc, s = cli(ah, ["rules", "--rules", str(rp), "--date", "2026-10-06", "--remove", "m1_vds", "--write"])
        check("rules: разовое место снимается", rc == 0 and s["removed"] == 1 and json.loads(rp.read_text())["one_off_merchants"] == [], s)
        # 2026-11-10: тройка операции хранится в правиле — CSV-пересчёт не нужен ручной rule-ops.json
        rc, s = cli(ah, ["rules", "--rules", str(rp), "--date", "2026-11-10", "--one-off", "op-9", "2026-10", "разовая-синт",
                         "--op", "op-9", "2026-10-03", "Тест-счёт", "1500.5", "--write"])
        r = json.loads(rp.read_text())
        check("rules --op: тройка записана в правило",
              rc == 0 and r["one_off"][0]["op"] == {"date": "2026-10-03", "account": "Тест-счёт", "amount": 1500.5}, r)
        rc, s = cli(ah, ["rules", "--rules", str(rp), "--date", "2026-11-11", "--one-off", "op-9", "2026-10", "заметка новее", "--write"])
        r = json.loads(rp.read_text())
        check("rules: повтор ID без --op сохраняет тройку", rc == 0 and r["one_off"][0]["op"]["account"] == "Тест-счёт", r)
        rc, s = cli(ah, ["rules", "--rules", str(rp), "--date", "2026-11-11", "--op", "нет-такого", "2026-10-03", "С", "1"])
        check("rules --op на чужой ID — blocking", rc == 2, s)
        rc, s = cli(ah, ["rules", "--rules", str(rp), "--date", "2026-11-11", "--op", "op-9", "2026-10-03", "С", "много"])
        check("rules --op: сумма не число — blocking", rc == 2, s)
        rc, s = cli(ah, ["rules", "--rules", str(rp), "--date", "2026-11-11", "--one-off-merchant", "m2", "место",
                         "--merchant-name", "m2", "Тест-место", "--merchant-name", "m2", "Тест-место 2", "--write"])
        r = json.loads(rp.read_text())
        check("rules --merchant-name: названия места в правиле",
              rc == 0 and r["one_off_merchants"][0]["names"] == ["Тест-место", "Тест-место 2"], r)
        base = {"schema": ah.RULES_SCHEMA, "updated": "2026-11-10", "regular_big": [], "one_off_merchants": [],
                "one_off": [{"id": "a", "month": "2026-10", "note": "n", "date": "2026-11-10"}]}
        check("validate_rules: старое правило без op/names валидно", ah.validate_rules(base) == [])
        for bad in ({"date": "2026-10-03", "account": "С"}, {"date": "10.03", "account": "С", "amount": 1},
                    {"date": "2026-10-03", "account": "С", "amount": "1"}, {"date": "2026-10-03", "account": "С", "amount": 1, "x": 1}):
            b = json.loads(json.dumps(base))
            b["one_off"][0]["op"] = bad
            check(f"validate_rules: кривой op {sorted(bad)} — ошибка", ah.validate_rules(b) != [], bad)
        b = json.loads(json.dumps(base))
        b["one_off_merchants"] = [{"merchant_id": "m", "note": "n", "date": "2026-11-10", "names": []}]
        check("validate_rules: пустой names — ошибка", ah.validate_rules(b) != [])
        rc, s = cli(ah, ["validate", "--rules", str(rp)])
        check("validate правил", rc == 0 and s["ok"], s)

        print("10. Дата аудита — день записи, не конец данных перезакрытого месяца")
        H0 = {"schema": ah.HISTORY_SCHEMA, "updated": "2026-11-01", "records": [], "issues": {
            "A3:old": {"check": "A3", "month": "2026-01", "first_seen": "2026-10-06", "last_seen": "2026-10-06", "status": "open"}}}
        R0 = {"schema": ah.RUN_SCHEMA, "mode": "month", "month": "2026-06", "as_of": "2026-07-01",
              "stats": {"operations": 10, "flagged": 1, "clean_share_count": 0.9, "clean_share_rub": 0.9, "expense_rub": 100,
                        "correction_share_of_expense": 0, "by_check": {}}, "checks": {}, "coverage": {},
              "history": {"keys": {"fixed": ["A3:old"]}, "open_by_age": {"lt_1m": 0, "1_3m": 0, "gt_3m": 1}},
              "issues": {"A5:new": {"check": "A5", "month": "2026-06"}}}
        n0, _ = ah.apply(R0, H0, today="2026-11-02")
        check("as_of записи — день записи", n0["records"][0]["as_of"] == "2026-11-02", n0["records"][0]["as_of"])
        check("найденное сегодня — first_seen сегодня, возраст «до месяца»",
              n0["issues"]["A5:new"]["first_seen"] == "2026-11-02" and n0["records"][0]["open_by_age"] == {"lt_1m": 1, "1_3m": 0, "gt_3m": 0}, n0)
        check("закрытое — не раньше, чем найдено", n0["issues"]["A3:old"]["closed_at"] == "2026-11-02")
        try:   # без today «закрыто 01.07» раньше «найдено 06.10» — запись не проходит проверку
            ah.apply(R0, H0); check("без today — закрыть раньше, чем найдено, нельзя (blocking)", False)
        except ah.Blocking as e:
            check("без today — закрыть раньше, чем найдено, нельзя (blocking)", "назад во времени" in str(e), str(e))
        bad = {**H0, "issues": {"A3:old": {**H0["issues"]["A3:old"], "status": "fixed", "closed_at": "2026-02-01"}}}
        check("закрыто раньше, чем найдено — ошибка проверки", any("назад во времени" in e for e in ah.validate_history(bad)))
        H1 = {"schema": ah.HISTORY_SCHEMA, "updated": "2026-11-01",
              "records": [{"month": "2026-01", "as_of": "2026-02-01"}, {"month": "2026-06", "as_of": "2026-07-01", "open_by_age": {"lt_1m": 0, "1_3m": 0, "gt_3m": 2}}],
              "issues": {"A3:j": {"check": "A3", "month": "2026-01", "first_seen": "2026-10-06", "last_seen": "2026-10-06", "status": "fixed", "closed_at": "2026-02-01"},
                         "A5:a": {"check": "A5", "month": "2026-06", "first_seen": "2026-07-01", "last_seen": "2026-07-01", "status": "open"},
                         "A5:z": {"check": "A5", "month": "2026-05", "first_seen": "2026-07-01", "last_seen": "2026-07-01", "status": "open"}}}
        n1, s1 = ah.redate(H1, ["2026-01", "2026-06"], "2026-11-01")
        check("redate: as_of записей и даты их замечаний",
              [r["as_of"] for r in n1["records"]] == ["2026-11-01", "2026-11-01"] and n1["issues"]["A3:j"]["closed_at"] == "2026-11-01"
              and n1["issues"]["A3:j"]["first_seen"] == "2026-10-06" and n1["issues"]["A5:a"]["first_seen"] == "2026-11-01", s1)
        check("redate: чужой месяц не трогает", n1["issues"]["A5:z"]["first_seen"] == "2026-07-01")
        check("redate: возраст последней записи пересчитан", n1["records"][-1]["open_by_age"] == {"lt_1m": 1, "1_3m": 0, "gt_3m": 1}, n1["records"][-1])
        check("redate: исходник не изменён", H1["records"][0]["as_of"] == "2026-02-01")
        try:
            ah.redate(H1, ["2026-03"], "2026-11-01"); check("redate: нет месяца — blocking", False)
        except ah.Blocking:
            check("redate: нет месяца — blocking", True)

        print("8. load_accepted читает оба формата")
        check("список", am.load_accepted(jdump(t / "l.json", [{"id": "x", "check": "A3"}])) == {("x", "A3")})
        check("accepted.json", ("a-corr", "A2") in am.load_accepted(str(accp)))
        check("нет файла — пусто", am.load_accepted(str(t / "nope.json")) == set())

    print(f"\nИтого: {PASSED} OK, {FAILED} FAIL")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
