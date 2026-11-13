#!/usr/bin/env python3
"""«Что перевести» вьюера (v3.77.0, 4d, решение владельца: деньги, не лоты; только во вьюере) — planMoves настоящим браузером.

Контракты (синтетические строки {name, plan, aPct, aRub}, база 1 000 000 ₽, коридор ±1 п.п.):
  1. один источник, один приёмник: отдать = получить = min(излишек, недобор);
  2. несколько: S = min(Σизлишков, Σнедоборов); «отдать» i = S × излишек_i/Σизлишков, «получить» j = S × недобор_j/Σнедоборов,
     Σотдать = Σполучить = total = S (±2 ₽ округления). planMoves → { give, take, total };
  3. источников нет (всё ниже плана) — пусто; всё в коридоре — пусто;
  4. строки меньше 1 000 ₽ не показываются; строки без плана/факта игнорируются; база выводится из факта, если не передана.
Требует playwright + chromium; без них — пропуск. Запуск: python3 tools/tests/test_viewer_plan_moves.py
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pages_stand import serve  # noqa: E402  (стенд — _pages_stand, keep-alive)
passed = failed = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name} {extra}")


try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("viewer_plan_moves: пропуск — нет playwright")
    sys.exit(0)

BASE = 1_000_000.0


def row(name, plan, rub):
    return {"name": name, "plan": plan, "aPct": rub / BASE * 100, "aRub": rub}


def main():
    httpd = serve(directory=REPO)[0]   # _pages_stand: очередь 128, keep-alive
    url = f"http://127.0.0.1:{httpd.server_address[1]}/tools/portfolio-integrated-viewer.html"
    with sync_playwright() as p:
        try:
            br = p.chromium.launch()
        except Exception:  # noqa: BLE001
            print("viewer_plan_moves: пропуск — нет chromium")
            return 0
        pg = br.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("**/api/**", lambda r: r.fulfill(status=502, body="{}"))
        pg.goto(url)
        pg.wait_for_function("typeof planMoves === 'function'", timeout=20000)
        mv = lambda rows, base=BASE: pg.evaluate("([r, b]) => planMoves(r, 1, b)", [rows, base])  # noqa: E731

        # 1. один источник и один приёмник
        r1 = [row("Кеш", 4, 150_000), row("Акции", 40, 300_000), row("Облигация", 56, 550_000)]
        m1 = mv(r1)
        check("один к одному: отдать Кеш 100 000, получить Акции 100 000, всего 100 000 = min(110 000; 100 000)",
              m1 == {"give": [{"name": "Кеш", "rub": 100000}], "take": [{"name": "Акции", "rub": 100000}], "total": 100000}, str(m1))

        # 2. несколько источников и приёмников: отдать = S × излишек/Σ, получить = S × недобор/Σ
        r2 = [row("A", 10, 300_000), row("B", 10, 200_000), row("C", 30, 100_000), row("D", 25, 150_000), row("E", 25, 250_000)]
        exc = {"A": 200_000, "B": 100_000}
        need = {"C": 200_000, "D": 100_000}
        S = min(sum(exc.values()), sum(need.values()))
        m2 = mv(r2)
        give = {x["name"]: x["rub"] for x in m2["give"]}
        take = {x["name"]: x["rub"] for x in m2["take"]}
        check("отдать: S × излишек_i/Σизлишков", give == {k: round(S * v / sum(exc.values())) for k, v in exc.items()}, str(give))
        check("получить: S × недобор_j/Σнедоборов", take == {k: round(S * v / sum(need.values())) for k, v in need.items()}, str(take))
        check("total = S; Σотдать = Σполучить = total (±2 ₽ округления)", m2["total"] == round(S)
              and abs(sum(give.values()) - m2["total"]) <= 2 and abs(sum(take.values()) - m2["total"]) <= 2, str(m2))
        check("E в коридоре — ни отдаёт, ни получает", "E" not in give and "E" not in take)

        # 3. источников нет; всё в коридоре; приёмников нет
        empty = {"give": [], "take": [], "total": 0}
        check("источников нет — пусто", mv([row("A", 50, 400_000), row("B", 50, 450_000)]) == empty)
        check("всё в коридоре — пусто", mv([row("A", 50, 505_000), row("B", 50, 495_000)]) == empty)
        check("приёмников нет — пусто", mv([row("A", 40, 600_000), row("B", 60, 600_000)]) == empty)

        # 4. мелочь, пустые строки, база из факта
        m4 = mv([row("A", 50, 520_300), row("B", 50, 479_700)])
        check("строки меньше 1 000 ₽ скрыты, при остатке пусто или ≥ 1 000", all(x["rub"] >= 1000 for x in m4["give"] + m4["take"]))
        m4b = mv([row("A", 20, 211_200), row("B", 20, 190_000), row("C", 60, 598_800)], 1_000_000.0)
        check("мелкие перевод 1 200 ₽ (<коридор) не появляется", m4b == empty, str(m4b))
        check("строки без плана или факта игнорируются",
              mv(r1 + [{"name": "Z", "plan": None, "aPct": 5, "aRub": 50000}, {"name": "Y", "plan": 5, "aPct": None, "aRub": None}]) == m1)
        a = pg.evaluate("([r]) => planMoves(r, 1)", [r1])
        check("база не передана — выводится из факта строки", a == m1, str(a))
        check("ошибок JS нет", not errs, str(errs[:2]))
        br.close()
    httpd.shutdown()
    print(f"viewer_plan_moves: {passed} OK, {failed} FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
