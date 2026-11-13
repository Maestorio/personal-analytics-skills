#!/usr/bin/env python3
"""
Регрессионные тесты audit_month.py (zenmoney-analyst, режим D «Аудит учёта»).

Синтетические данные в формате ответов MCP ZenMoney v2 — без реальных ID и сумм.
Запуск из корня репозитория:
    python3 skills/zenmoney-analyst/tests/test_audit_month.py
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
SCRIPT_DIR = REPO_ROOT / "skills" / "zenmoney-analyst" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
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


# ─── фикстуры ────────────────────────────────────────────────────────────────

ACC = {
    "acc-card": {"name": "Карта", "instrument": "RUB", "type": "card", "isInBalance": True, "isOtherUser": False},
    "acc-save": {"name": "Накопительный", "instrument": "RUB", "type": "checking", "isInBalance": True, "isOtherUser": False},
    "acc-off": {"name": "Вне баланса", "instrument": "RUB", "type": "card", "isInBalance": False, "isOtherUser": False},
    "acc-usd": {"name": "Долларовый", "instrument": "USD", "type": "cash", "isInBalance": True, "isOtherUser": False},
    "acc-bank2": {"name": "Карта банка 2", "instrument": "RUB", "type": "card", "isInBalance": True, "isOtherUser": False},
    "a1_debt": {"name": "Долг", "instrument": "RUB", "type": "debt", "isInBalance": True, "isOtherUser": False},
}
CATS = [
    {"id": "c-food", "name": "Питание", "parentId": None, "isIncome": False, "isExpense": True, "isArchived": False},
    {"id": "c-cafe", "name": "Кафе", "parentId": "c-food", "isIncome": False, "isExpense": True, "isArchived": False},
    {"id": "c-shop", "name": "Магазины", "parentId": "c-food", "isIncome": False, "isExpense": True, "isArchived": False},
    {"id": "c-corr", "name": "Корректировка", "parentId": None, "isIncome": True, "isExpense": True, "isArchived": False},
    {"id": "c-travel", "name": "Путешествия", "parentId": None, "isIncome": False, "isExpense": True, "isArchived": False},
    {"id": "c-trip-old", "name": "#Страна'25", "parentId": None, "isIncome": False, "isExpense": True, "isArchived": False},
    {"id": "c-trip-done", "name": "#Страна'24", "parentId": "c-travel", "isIncome": False, "isExpense": True, "isArchived": False},
    {"id": "c-trip-now", "name": "#Страна'26", "parentId": None, "isIncome": False, "isExpense": True, "isArchived": False},
    {"id": "c-med1", "name": "Медицина", "parentId": None, "isIncome": False, "isExpense": True, "isArchived": False},
    {"id": "c-med2", "name": "Медицина", "parentId": "c-food", "isIncome": False, "isExpense": True, "isArchived": False},
    {"id": "c-typo", "name": "Подписки", "parentId": None, "isIncome": False, "isExpense": True, "isArchived": False},
    {"id": "c-typo2", "name": "Подпискии", "parentId": None, "isIncome": False, "isExpense": True, "isArchived": False},
    {"id": "c-dead", "name": "Хобби", "parentId": None, "isIncome": False, "isExpense": True, "isArchived": False},
    {"id": "c-arch", "name": "Старое", "parentId": None, "isIncome": False, "isExpense": True, "isArchived": True},
    {"id": "c-salary", "name": "Зарплата", "parentId": None, "isIncome": True, "isExpense": False, "isArchived": False},
]
MERCH = {"m-shop": {"id": "m-shop", "name": "Магазин у дома"}, "m-cafe": {"id": "m-cafe", "name": "Кофейня"}}


def ex(i, dt, acc, amt, cat=None, **kw):
    o = {"id": i, "date": dt, "expense": {"accountId": acc, "amount": amt}}
    if cat:
        o["categoryId"] = cat
    o.update(kw)
    return o


def inc(i, dt, acc, amt, cat=None, **kw):
    o = {"id": i, "date": dt, "income": {"accountId": acc, "amount": amt}}
    if cat:
        o["categoryId"] = cat
    o.update(kw)
    return o


def tr(i, dt, a, b, amt, **kw):
    o = {"id": i, "date": dt, "expense": {"accountId": a, "amount": amt}, "income": {"accountId": b, "amount": amt}}
    o.update(kw)
    return o


OPS = [
    # история: точка m-shop обычно в «Магазинах», m-cafe — в «Кафе»
    ex("h1", "2025-09-20", "acc-card", 500, "c-shop", merchantId="m-shop", source="plugin"),
    ex("h2", "2026-07-03", "acc-card", 450, "c-shop", merchantId="m-shop", source="plugin"),
    ex("h3", "2026-07-04", "acc-card", 300, "c-cafe", merchantId="m-cafe", source="plugin"),
    *[ex(f"h4-{k}", f"2026-07-{10 + 3 * k:02d}", "acc-bank2", 100, "c-cafe", source="plugin") for k in range(5)],  # банк 2: раз в 3 дня, замолчал после июля
    tr("h-tr-plugin", "2026-07-20", "acc-card", "acc-save", 1000, source="plugin"),  # перевод из банка: получатель не «синхронизируемый»
    *[inc(f"h-sv-{k}", f"2026-07-{1 + k:02d}", "acc-save", 10, "c-salary", source="plugin") for k in range(3)],  # редкий счёт: < 5 операций
    ex("h5", "2026-05-01", "acc-card", 1000, "c-trip-done"),                         # поездка давно, уже в «Путешествиях»
    ex("h6", "2026-06-01", "acc-card", 1000, "c-trip-old"),                          # поездка давно, на первом уровне
    ex("h7", "2026-02-01", "acc-card", 100, "c-typo"),
    ex("h8", "2026-02-02", "acc-card", 100, "c-typo2"),
    ex("h9", "2026-02-03", "acc-card", 100, "c-med1"),
    ex("h10", "2026-02-04", "acc-card", 100, "c-med2"),
    inc("h11", "2026-08-05", "acc-card", 100000, "c-salary"),
    # аудируемый месяц 2026-09
    ex("e-tr", "2026-09-05", "acc-card", 20000, "c-corr", source="plugin"),       # A1 + A2: перевод «Корректировкой»
    inc("i-tr", "2026-09-06", "acc-save", 20000, "c-corr"),
    ex("x-usd", "2026-09-07", "acc-usd", 100, "c-cafe"),                          # валюта: курс на дату
    ex("x-nocat", "2026-09-08", "acc-card", 700),                                  # A3
    ex("x-proj1", "2026-09-10", "acc-card", 900, "c-trip-now", merchantId="m-shop", source="plugin"),  # A4 + подсказка
    ex("x-proj2", "2026-09-11", "acc-card", 800, "c-trip-now"),                   # A4 без подсказки
    ex("x-dup1", "2026-09-12", "acc-card", 350, "c-cafe", merchantId="m-cafe", source="plugin"),  # A5
    ex("x-dup2", "2026-09-12", "acc-card", 350, "c-cafe", merchantId="m-cafe", source="plugin"),
    ex("x-off", "2026-09-13", "acc-off", 2500, "c-shop"),                          # B7
    ex("x-corr-trip", "2026-09-14", "acc-usd", 10, "c-corr", tagIds=["c-trip-now"]),  # A2 в поездке
    ex("x-ok-tag", "2026-09-15", "acc-card", 1200, "c-cafe", tagIds=["c-trip-now"], source="plugin"),  # норма
    ex("x-parent", "2026-09-16", "acc-card", 400, "c-food"),                       # D13
    tr("x-transfer", "2026-09-17", "acc-card", "acc-save", 5000),                  # перевод — не в базе
    ex("x-debt", "2026-09-18", "a1_debt", 300, "c-shop"),
    inc("x-refund", "2026-09-20", "acc-card", 350, "c-cafe", source="plugin"),     # возврат — не перевод (нет пары)
    inc("x-salary", "2026-09-25", "acc-card", 100000, "c-salary", source="plugin"),
    ex("n-oct", "2026-10-01", "acc-card", 200, "c-cafe", source="plugin"),          # после месяца: счёт живой
]
RATES = {"data": [{"instrument": "USD", "date": "2026-09-07", "rate": 90.0},
                  {"instrument": "USD", "date": "2026-09-14", "rate": None}]}


def write(tmp, name, obj):
    p = Path(tmp) / name
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return str(p)


def page(ops, cursor=None):
    return {"data": ops, "nextCursor": cursor,
            "references": {"user": {"currency": "RUB", "monthStartDay": 1}, "accounts": ACC,
                           "categories": {c["id"]: c for c in CATS}, "merchants": MERCH}}


def run_cli(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        am.main(argv)
    return json.loads(buf.getvalue())


def history_age_test():
    """Замечание прошлого месяца вне окна операций (не перепроверено) — открыто: входит в разбивку по возрасту."""
    from datetime import date
    from types import SimpleNamespace
    ctx = SimpleNamespace(accepted=set(), ops=[])
    hist = {"records": [], "issues": {"A3:x1": {"check": "A3", "month": "2026-01", "first_seen": "2026-10-06", "last_seen": "2026-10-06", "status": "open"}}}
    args = SimpleNamespace(month="2026-10", mode="month")
    h = am.recheck_history(ctx, hist, args, date(2026, 11, 1), date(2026, 9, 1), set(), 1)
    check("не перепроверенное замечание (месяц вне окна) — not_rechecked", h["keys"]["not_rechecked"] == ["A3:x1"])
    check("и оно входит в разбивку по возрасту (сумма = открытым)", sum(h["open_by_age"].values()) == 1 and h["open_by_age"]["lt_1m"] == 1, h["open_by_age"])


def main():
    history_age_test()
    with tempfile.TemporaryDirectory() as tmp:
        # две страницы + одна обёрнутая средой, с повтором операции
        half = len(OPS) // 2
        p1 = write(tmp, "p1.json", page(OPS[:half], "cur"))
        wrapped = [{"type": "text", "text": json.dumps(page(OPS[half:] + [OPS[0]]), ensure_ascii=False)}]
        p2 = write(tmp, "p2.json", wrapped)
        cats = write(tmp, "cats.json", {"data": CATS, "nextCursor": None})
        rates = write(tmp, "rates.json", RATES)
        base = ["--month", "2026-09", "--as-of", "2026-10-03", "--tx", p1, p2, "--categories", cats]

        print("Загрузка")
        ops, refs = am.merge_pages([p1, p2])
        check("страницы склеены, дубль по id убран", len(ops) == len(OPS), len(ops))
        check("обёртка среды снимается", refs["user"]["currency"] == "RUB")

        print("needs-rates")
        nr = run_cli(["needs-rates"] + base)
        check("нужен USD на две даты месяца", nr["needs"] == {"USD": ["2026-09-07", "2026-09-14"]}, nr)

        print("month")
        r = run_cli(["month"] + base + ["--rates", rates])
        c = r["checks"]
        check("A1: пара перевод-как-расход/доход найдена", len(c["A1"]) == 1 and c["A1"][0]["expense_id"] == "e-tr", c["A1"])
        check("A1: возврат без пары не считается переводом", all(p["income_id"] != "x-refund" for p in c["A1"]))
        check("A2: три корректировки (обе стороны пары + в поездке)", c["A2"]["count"] == 3, c["A2"])
        check("A2: расход корректировок без валютной (нет курса)", c["A2"]["expense_rub"] == 20000.0, c["A2"])
        check("A2: одна корректировка в поездке", c["A2"]["in_trips"] == 1)
        check("A3: операция без категории", [x["id"] for x in c["A3"]] == ["x-nocat"], c["A3"])
        a4 = {x["id"]: x for x in c["A4"]}
        check("A4: два проекта основной категорией", set(a4) == {"x-proj1", "x-proj2"}, list(a4))
        check("A4: подсказка по точке → «Магазины»", (a4["x-proj1"]["suggest"] or {}).get("categoryId") == "c-shop", a4["x-proj1"])
        check("A4: нет точки → нет подсказки", a4["x-proj2"]["suggest"] is None)
        check("A4: тег проекта — не проблема", "x-ok-tag" not in a4)
        check("A5: пара дублей", len(c["A5"]) == 1 and set(c["A5"][0]["ids"]) == {"x-dup1", "x-dup2"}, c["A5"])
        b6 = {x["account"] for x in c["B6"]}
        check("B6: замолчавший синхронизируемый счёт", "Карта банка 2" in b6, c["B6"])
        check("B6: ручной счёт не проверяется", "Долларовый" not in b6 and "Накопительный" not in b6)
        check("B6: активный счёт не в списке", "Карта" not in b6)
        check("B6: редкий счёт (< 5 операций) не судим", "Накопительный" not in b6)
        b6x = {x["account"]: x for x in c["B6"]}
        check("B6: обычная пауза банка 2 — 3 дня", b6x.get("Карта банка 2", {}).get("usual_max_gap") == 3, c["B6"])
        check("B7: трата вне баланса", c["B7"] == [{"account": "Вне баланса", "count": 1, "rub": 2500.0}], c["B7"])
        check("B7: долг не считается", all(x["account"] != "Долг" for x in c["B7"]))
        check("B8: без реестра — пропущено", c["B8"] is None)
        check("C-проверок в месячном нет", "C9" not in c)
        s = r["stats"]
        base_n = sum(1 for o in OPS if "2026-09-01" <= o["date"] <= "2026-09-30" and am.kind(o) != "transfer")
        check("статистика: перевод не в базе", s["operations"] == base_n, s)
        check("статистика: 8 помеченных (A1×2 с пересечением A2, A2, A3, A4×2, A5×2)", s["flagged"] == 8, s)
        # траты — база month_stats с корректировками: возврат покупки x-refund (350) вычтен
        check("статистика: валютная по курсу 90, возврат покупки вычтен",
              abs(s["expense_rub"] - (20000 + 9000 + 700 + 900 + 800 + 700 + 2500 + 1200 + 400 + 300 - 350)) < 0.01, s["expense_rub"])
        check("статистика: доля корректировок", abs(s["correction_share_of_expense"] - 20000 / s["expense_rub"]) < 1e-4)
        check("статистика: сумма корректировок", s["correction_rub"] == 20000.0, s)
        check("охват: без курса — счёт валют", r["coverage"]["unconverted"] == {"USD": 1}, r["coverage"])
        check("охват: окно 90 дней есть", r["coverage"]["b6_window_ok"] is True)
        check("D13: запись в родителя", r["D13_parent_with_children"].get("Питание") == 1, r["D13_parent_with_children"])
        # 2026-10-07: трата прямо в категории с подкатегориями — подсказка «закрой месяц» с операцией
        pd_ = r["parent_direct"]
        check("parent_direct: трата в родителе — с датой, суммой и категорией",
              pd_["count"] == 1 and pd_["items"][0]["id"] == "x-parent" and pd_["items"][0]["date"] == "2026-09-16"
              and pd_["items"][0]["rub"] == 400.0 and pd_["items"][0]["category"] == "Питание", pd_)
        check("parent_direct: не замечание — нет в реестре", not any(k.startswith("D13") for k in r["issues"]))
        rq_ = run_cli(["quarter"] + base)
        check("parent_direct: только в «закрой месяц»", "parent_direct" not in rq_)
        acc_d = write(tmp, "acc-d13.json", [{"id": "x-parent", "check": "D13"}])
        check("parent_direct: «так и задумано» (D13) — больше не показывается",
              run_cli(["month"] + base + ["--accepted", acc_d])["parent_direct"]["count"] == 0)
        check("by_check: A2 считает и пару-перевод", s["by_check"]["A2"]["count"] == 3)

        print("accepted")
        acc = write(tmp, "acc.json", [{"id": "x-dup1", "check": "A5"}, {"id": "x-nocat", "check": "A3"},
                                       {"id": "acc-bank2", "check": "B6"}])
        r2 = run_cli(["month"] + base + ["--accepted", acc])
        check("принятый дубль не повторяется", r2["checks"]["A5"] == [])
        check("принятая операция без категории не повторяется", r2["checks"]["A3"] == [])
        check("принятый молчащий счёт не повторяется", r2["checks"]["B6"] == [])
        check("охват: число принятых", r2["coverage"]["accepted_applied"] == 3)

        print("доля корректировок и B7 (2026-10-05)")
        acc_a2 = write(tmp, "acc_a2.json", [{"id": "e-tr", "check": "A2"}, {"id": "i-tr", "check": "A2"},
                                              {"id": "x-corr-trip", "check": "A2"}])
        r4 = run_cli(["month"] + base + ["--rates", rates, "--accepted", acc_a2])
        check("принятые корректировки — не замечания", r4["checks"]["A2"]["count"] == 0, r4["checks"]["A2"])
        check("…но доля незаписанного та же: принятие её не меняет",
              r4["stats"]["correction_share_of_expense"] == s["correction_share_of_expense"]
              and r4["stats"]["correction_rub"] == 20000.0, r4["stats"])
        acc_kind = write(tmp, "acc_kind.json", {"items": [
            {"id": "e-tr", "check": "A2", "reason": "ушло на мой счёт вне учёта", "date": "2026-10-05", "kind": "transfer_out"}]})
        r7 = run_cli(["month"] + base + ["--rates", rates, "--accepted", acc_kind])
        check("перевод себе вне учёта (transfer_out) — не трата и не в доле незаписанного",
              r7["stats"]["correction_rub"] == 0.0 and r7["stats"]["correction_transfer_out_rub"] == 20000.0
              and abs(r7["stats"]["expense_rub"] - (s["expense_rub"] - 20000)) < 0.01, r7["stats"])
        # карточки корректировок: признаки для вопроса «что это было»
        extra2 = [inc("q-adv", "2026-09-26", "acc-card", 7000, "c-salary", source="plugin"),
                  ex("q-self", "2026-09-27", "acc-card", 7000, "c-corr", source="plugin", comment="Иван И."),
                  ex("q-hand", "2026-09-28", "acc-save", 3000, "c-corr"),
                  tr("q-tr", "2026-09-28", "acc-card", "acc-usd", 3000)]
        r8 = run_cli(["month", "--month", "2026-09", "--as-of", "2026-10-03", "--tx",
                      write(tmp, "p_q.json", page(OPS + extra2)), "--categories", cats, "--rates", rates])
        cards = {x["id"]: x for x in r8["checks"]["A2"]["items"]}
        check("карточка: из банка с получателем — похоже на перевод",
              any("похоже на перевод" in h for h in cards["q-self"]["hints"]) and cards["q-self"]["source"] == "банк", cards.get("q-self"))
        check("карточка: накануне пришло столько же — ушло целиком дальше",
              any("пришло столько же" in h for h in cards["q-self"]["hints"]), cards.get("q-self"))
        check("карточка: вручную — выравнивание; перевод той же суммы с другого счёта",
              any("выравнивание" in h for h in cards["q-hand"]["hints"])
              and any("другого счёта" in h for h in cards["q-hand"]["hints"]), cards.get("q-hand"))
        check("карточка: с тегом поездки", any("поездк" in h for h in cards["x-corr-trip"]["hints"]), cards.get("x-corr-trip"))
        check("карточки — только непринятые", "e-tr" not in {x["id"] for x in r4["checks"]["A2"]["items"]})
        cats_inv = write(tmp, "cats_inv.json", {"data": CATS + [
            {"id": "c-inv", "name": "Инвестиции", "parentId": None, "isIncome": True, "isExpense": True, "isArchived": False}],
            "nextCursor": None})
        extra = [ex("o-trip", "2026-09-21", "acc-off", 5000, "c-cafe", tagIds=["c-trip-now"]),   # кошелёк поездки
                 ex("o-inv", "2026-09-22", "acc-off", 100000, "c-inv"),                           # инвестиции
                 ex("o-card", "2026-09-23", "acc-card", 100000, "c-inv")]                         # инвестиции с карты
        p_inv = write(tmp, "p_inv.json", page(OPS + extra))
        r5 = run_cli(["month", "--month", "2026-09", "--as-of", "2026-10-03", "--tx", p_inv, "--categories", cats_inv,
                      "--rates", rates])
        check("B7: трата поездки и инвестиции вне баланса — не сигнал",
              r5["checks"]["B7"] == [{"account": "Вне баланса", "count": 1, "rub": 2500.0}], r5["checks"]["B7"])
        check("траты без инвестиций, трата поездки — в тратах",
              abs(r5["stats"]["expense_rub"] - s["expense_rub"] - 5000) < 0.01, (r5["stats"]["expense_rub"], s["expense_rub"]))
        cfg_ok = write(tmp, "cfg_ok.json", {"off_balance_ok_account_ids": ["acc-off"]})
        r6 = run_cli(["month"] + base + ["--rates", rates, "--config", cfg_ok])
        check("B7: счёт из off_balance_ok_account_ids не проверяется", r6["checks"]["B7"] == [], r6["checks"]["B7"])

        print("quarter")
        q = run_cli(["quarter"] + base)
        qc = q["checks"]
        twins = {tuple(sorted([x["a"], x["b"]])) for x in qc["C9"]}
        check("C9: одинаковые названия", ("Медицина", "Медицина") in twins, qc["C9"])
        check("C9: опечатка на 1 символ", ("Подписки", "Подпискии") in twins)
        check("C9: архивные не сравниваются", all("Старое" not in t for t in twins))
        dead = {x["name"] for x in qc["C11"]}
        check("C11: неиспользуемая категория", "Хобби" in dead, dead)
        check("C11: родитель с активными детьми не кандидат", "Питание" not in dead)
        check("C11: архивная не кандидат", "Старое" not in dead)
        check("C11: тег считается использованием", "#Страна'26" not in dead)
        cfg_rare = write(tmp, "cfg_rare.json", {"rare_category_ids": ["c-dead"]})
        q_rare = run_cli(["quarter"] + base + ["--config", cfg_rare])
        check("C11: редкая категория из карты не предлагается", "Хобби" not in {x["name"] for x in q_rare["checks"]["C11"]})
        trips = {x["name"]: x for x in qc["C12"]}
        check("C12: давняя поездка на первом уровне", "#Страна'25" in trips, trips)
        check("C12: уже в «Путешествиях» — не сигнал", "#Страна'24" not in trips)
        check("C12: текущая поездка — не сигнал", "#Страна'26" not in trips)
        check("C12: конец по последней операции", trips["#Страна'25"]["end_basis"] == "последняя операция")

        cfg = write(tmp, "cfg.json", {"trip_end": {"c-trip-now": "2026-08-01"}})
        q2 = run_cli(["quarter"] + base + ["--config", cfg])
        t2 = {x["name"]: x for x in q2["checks"]["C12"]}
        check("C12: дата конца из карты важнее операций", "#Страна'26" in t2 and t2["#Страна'26"]["end_basis"] == "карта", t2)

        short = run_cli(["quarter", "--month", "2026-09", "--as-of", "2026-10-03", "--tx",
                         write(tmp, "short.json", page([o for o in OPS if o["date"] >= "2026-09-01"])),
                         "--categories", cats])
        check("C11: окно короче года — пропуск", short["checks"]["C11"] is None)
        check("охват: окно < 90 дней помечено", short["coverage"]["b6_window_ok"] is False)

        print("B8 и config")
        accounts = write(tmp, "accounts.json", {"data": [{"id": k + "-xxxxxxxx", **v} for k, v in ACC.items()], "nextCursor": None})
        known = [(k + "-xxxxxxxx")[:8] for k in ACC if k != "acc-bank2"]
        cfg2 = write(tmp, "cfg2.json", {"accounts_file": accounts, "known_account_prefixes": known,
                                         "correction_ids": ["c-corr"], "project_ids": ["c-trip-now"]})
        r3 = run_cli(["month"] + base + ["--config", cfg2])
        check("B8: новый счёт вне реестра", [x["name"] for x in r3["checks"]["B8"]] == ["Карта банка 2"], r3["checks"]["B8"])
        check("config: проекты только из карты", {x["id"] for x in r3["checks"]["A4"]} == {"x-proj1", "x-proj2"})

        print("финансовый месяц")
        check("monthStartDay=10", am.month_bounds("2026-09", 10) == (am.date(2026, 9, 10), am.date(2026, 10, 9)))
        check("декабрь → январь", am.month_bounds("2026-12")[1] == am.date(2026, 12, 31))

        print("места платежа")
        PM = {k: {"id": k, "name": v} for k, v in {
            "m-p1": "Пятёрочка", "m-p2": "Пятёрочка",                 # два места с одним названием
            "m-g1": "МосГорКафе", "m-g2": "Мосгоркофе",               # опечатка
            "m-v1": "ВкусВилл", "m-v2": "VKUSVILL 2039_4",            # кириллица ↔ латиница + код
            "m-l1": "Лампа", "m-l2": "Kafe Lampa",                    # один текст банка — у двух мест
            "m-k1": "Перекрёсток", "m-k2": "PEREKRESTOK SLAVYANSKI",  # филиалы сети
            "m-b": "Брусника", "m-ip": "IP Ivanov I.I.", "m-y": "YANDEX*GO", "m-v60": "V60 COFFEE  BAKERY",
            "m-pers": "Сергей К.", "m-rs": "ROSTICS SCHELKOVSKA", "m-sal": "Kofeynya Salut",
            "m-brand": "AZBUKA", "m-mes": "МосЭнергоСбыт"}.items()}
        PM["m-brand"]["logoUrl"] = "https://example/icon.png"          # фирменное место — не текст банка
        def pe(i, dt, mid, pay, n=1):
            return [ex(f"{i}-{j}", dt, "acc-card", 100, "c-shop", merchantId=mid, originalPayee=pay) for j in range(n)]
        POPS = (pe("p1", "2026-09-03", "m-p1", "PYATEROCHKA 231", 3) + pe("p2", "2026-07-03", "m-p2", "PYATEROCHKA 11458", 2)
                + pe("g1", "2026-09-04", "m-g1", "KOFEJNYA MOSGORKOFE.", 2) + pe("g2", "2026-07-04", "m-g2", "MOSGORKOFE")
                + pe("v1", "2026-09-05", "m-v1", "VKUSVILL") + pe("v2", "2026-07-05", "m-v2", "VKUSVILL 2039_4")
                + pe("l1", "2026-07-06", "m-l1", "KAFE LAMPA") + pe("l2", "2026-07-06", "m-l2", "KAFE LAMPA")
                + pe("k1", "2026-07-07", "m-k1", "PEREKRESTOK STROGINO") + pe("k2", "2026-07-07", "m-k2", "PEREKRESTOK SLAVYANSKI")
                + pe("b", "2026-09-08", "m-b", "BRUSNIKA", 2) + pe("ip", "2026-09-09", "m-ip", "IP Ivanov I.I.", 2)
                + pe("y", "2026-07-09", "m-y", "YANDEX*GO", 2) + pe("v60", "2026-07-09", "m-v60", "V60 COFFEE  BAKERY", 2)
                + pe("pers", "2026-09-10", "m-pers", "Сергей К.", 3)
                + pe("rs", "2026-09-13", "m-rs", "ROSTICS SCHELKOVSKA") + pe("sal", "2026-07-13", "m-sal", "Kofeynya Salut")
                + pe("brand", "2026-09-13", "m-brand", "AV AZBUKAVKUSA") + pe("mes", "2026-09-13", "m-mes", "МосЭнергоСбыт")
                + [ex("u1", "2026-09-11", "acc-card", 300, "c-cafe", originalPayee="Brusnika"),      # без места
                   ex("u2", "2026-09-12", "acc-card", 300, "c-cafe", originalPayee="427938******4223")])  # карта
        pp = {"data": POPS, "nextCursor": None,
              "references": {"user": {"currency": "RUB", "monthStartDay": 1}, "accounts": ACC, "categories": {c["id"]: c for c in CATS}, "merchants": PM}}
        pf = write(tmp, "places.json", pp)
        P = run_cli(["places", "--month", "2026-09", "--as-of", "2026-10-03", "--tx", pf])["places"]
        tw = {tuple(x["ids"]) for x in P["twins"]}
        check("места: два места с одним названием", ("m-p1", "m-p2") in tw, P["twins"])
        check("места: опечатка в названии", ("m-g1", "m-g2") in tw, P["twins"])
        check("места: кириллица и латиница, номер точки не мешает", ("m-v1", "m-v2") in tw, P["twins"])
        check("места: точное совпадение помечено", next(x for x in P["twins"] if x["ids"] == ["m-p1", "m-p2"])["exact"] is True)
        # 2026-10-07: одно название (регистр не в счёт) — в приложении не различить, нужны даты операций «лишнего» места
        tp = next(x for x in P["twins"] if x["ids"] == ["m-p1", "m-p2"])
        check("места: одно название — даты операций лишнего места", tp.get("same_name") is True and tp["ops"]
              and all(set(o) == {"id", "date", "amount", "account"} for o in tp["ops"]) and tp["keep"] not in {o["id"] for o in tp["ops"]}, tp)
        tg = next(x for x in P["twins"] if x["ids"] == ["m-g1", "m-g2"])
        check("места: опечатка (названия разные) — без списка дат", "ops" not in tg, tg)
        check("места: один текст банка у двух мест", [x["ids"] for x in P["split"]] == [["m-l1", "m-l2"]], P["split"])
        check("места: трата без места, хотя текст банка известен — подсказано место",
              [(x["count"], x["suggest"]["name"]) for x in P["unlinked"]] == [(1, "Брусника")], P["unlinked"])
        why = {x["names"][0]: x["why"] for x in P["rename"]}
        check("места: юрлицо и точка в конце", set(why.get("IP Ivanov I.I.", [])) >= {"legal", "punct"}, why)
        check("места: служебный символ и посредник", set(why.get("YANDEX*GO", [])) >= {"symbols", "broker"}, why)
        check("места: двойной пробел", "punct" in why.get("V60 COFFEE  BAKERY", []), why)
        check("места: перевод человеку не трогаем", "Сергей К." not in why and all("m-pers" not in x["ids"] for x in P["twins"]), why)
        check("места: номер карты не выводится", "427938" not in json.dumps(P, ensure_ascii=False))
        check("места: филиалы сети — в режиме places", [x["ids"] for x in P["chains"]] == [["m-k1", "m-k2"]], P["chains"])
        check("места: одна трата — переименование не предлагаем", all(x["count"] >= 2 for x in P["rename"]))
        # 2026-10-07: место названо текстом банка — показывать всегда (ROSTICS SCHELKOVSKA, PO CHESNOKU)
        bt = {x["names"][0] for x in P["bank_text"]}
        check("места: ВСЁ ЗАГЛАВНОЙ латиницей без логотипа — текст банка, даже с одной тратой", "ROSTICS SCHELKOVSKA" in bt, bt)
        check("места: название буква в букву как текст банка", "Kofeynya Salut" in bt, bt)
        check("места: фирменное (с логотипом), уже в «переименовать», перевод человеку — не текст банка",
              not bt & {"AZBUKA", "YANDEX*GO", "V60 COFFEE  BAKERY", "Сергей К.", "Брусника", "Пятёрочка", "МосЭнергоСбыт"}, bt)
        # 2026-10-07: общий текст банка — разные места (аптеки «APTEKA», фастфуд под кодом «QSR 11001»)
        GM = {"m-a1": {"id": "m-a1", "name": "Вита"}, "m-a2": {"id": "m-a2", "name": "Столички"},
              "m-q1": {"id": "m-q1", "name": "Rostic's"}, "m-q2": {"id": "m-q2", "name": "Бургер Кинг"},
              "m-a3": {"id": "m-a3", "name": "APTEKA 21"}, "m-a4": {"id": "m-a4", "name": "APTEKA 6.5"}}
        GOPS = (pe("ga1", "2026-09-01", "m-a1", "APTEKA") + pe("ga2", "2026-09-01", "m-a2", "APTEKA")
                + pe("gq1", "2026-09-01", "m-q1", "QSR 11001") + pe("gq2", "2026-09-01", "m-q2", "QSR 11003")
                + pe("ga3", "2026-09-01", "m-a3", "APTEKA 21") + pe("ga4", "2026-09-01", "m-a4", "APTEKA 6.5"))
        gf = write(tmp, "generic.json", dict(pp, data=GOPS, references=dict(pp["references"], merchants=GM)))
        G = run_cli(["places", "--month", "2026-09", "--as-of", "2026-10-03", "--tx", gf])["places"]
        check("места: общий текст банка (APTEKA, QSR) — не «одна точка двумя местами»", G["split"] == [], G["split"])
        check("места: «APTEKA 21» и «APTEKA 6.5» — не одно место", G["twins"] == [], G["twins"])
        M = run_cli(["month", "--month", "2026-09", "--as-of", "2026-10-03", "--tx", pf])
        mp = M["places"]
        check("места в «закрой месяц»: только места с тратами в месяце",
              {tuple(x["ids"]) for x in mp["twins"]} == {("m-p1", "m-p2"), ("m-g1", "m-g2"), ("m-v1", "m-v2")}
              and mp["split"] == [] and "YANDEX*GO" not in {x["names"][0] for x in mp["rename"]}, mp)
        check("места в «закрой месяц»: без филиалов сетей", mp["chains"] is None)
        check("места в «закрой месяц»: текст банка — только места месяца",
              {x["names"][0] for x in mp["bank_text"]} == {"ROSTICS SCHELKOVSKA"}, mp["bank_text"])
        check("места не входят в долю «без замечаний» и в реестр", not any(k.startswith("C10") for k in M["issues"]))
        accp = write(tmp, "acc-places.json", [{"id": "m-p1|m-p2", "check": "C10"}])
        P2 = run_cli(["places", "--month", "2026-09", "--as-of", "2026-10-03", "--tx", pf, "--accepted", accp])["places"]
        check("места: «это разные места» больше не показывается", ("m-p1", "m-p2") not in {tuple(x["ids"]) for x in P2["twins"]})

        print("утилиты")
        check("lev1: вставка", am.lev1("подписки", "подпискии"))
        check("lev1: две правки — нет", not am.lev1("кафе", "кофи"))
        check("norm_name: ё и регистр", am.norm_name("Ёлка ") == am.norm_name("елка"))

    print(f"\nИтого: {PASSED} OK, {FAILED} FAIL")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
