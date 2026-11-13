"""Плитка «Деньги» хаба (hub v2.1.1) — прогон настоящим браузером (Chromium), данные синтетические.

Правило: плитка показывает самый свежий месяц с итогами. Если он проверен только сайтом (ZenMoney/audit/site-audit.json),
а записи аудита скилла за него нет — в строке «Учёт» проверки сайта и подпись «аудит сайта <дата>», а не аудит более
раннего месяца. Аудит скилла главнее: есть запись за этот месяц — показывается она. Открытые замечания прошлых аудитов
остаются в строке. «Надо: закрыть …» гаснет при закрытии любым из двух способов.
Запуск: python3 tools/tests/test_hub_money_tile.py
"""
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pages_stand import Checker, Quiet, per_engine, serve  # noqa: E402

try:
    import playwright.sync_api  # noqa: F401
except ImportError:
    print("hub_money_tile: пропуск — нет playwright")
    sys.exit(0)

check = Checker()
T = date.today()
PM = date(T.year - (T.month == 1), 12 if T.month == 1 else T.month - 1, 1)          # прошлый календарный месяц
PPM = date(PM.year - (PM.month == 1), 12 if PM.month == 1 else PM.month - 1, 1)
K = lambda d: f"{d.year}-{d.month:02d}"
SPEND = {"months": [{"month": K(PPM), "totals": {"expense_regular_rub": 100000}}, {"month": K(PM), "totals": {"expense_regular_rub": 110000}}]}
REC = lambda m, **kw: dict({"month": m, "as_of": m + "-28", "open_total": 0, "clean_share_rub": 0.97}, **kw)
SITE = lambda n: {"schema": "zenmoney-site-audit@1", "months": {K(PM): {"as_of": T.isoformat(), "checks": ([{"id": "X1", "count": n}] if n else [])}}}


def run(name, br):
    def case(title, hist, site):
        tmp = Path(tempfile.mkdtemp())
        a = tmp / "ZenMoney" / "audit"
        a.mkdir(parents=True)
        (a / "history.json").write_text(json.dumps(hist), encoding="utf-8")
        (a / "spending.json").write_text(json.dumps(SPEND), encoding="utf-8")
        if site is not None:
            (a / "site-audit.json").write_text(json.dumps(site), encoding="utf-8")
        os.symlink(REPO / "tools", tmp / "tools")
        srv, base = serve(Quiet, directory=tmp)
        try:
            ctx = br.new_context(viewport={"width": 1280, "height": 900})
            ctx.add_init_script("localStorage.setItem('hub-auth','t')")
            pg = ctx.new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/tools/hub.html")
            pg.wait_for_function("!document.getElementById('money-kv').hidden", timeout=15000)
            out = (pg.inner_text("#money-q"), pg.inner_text("#money-sub"), pg.is_visible("#money-todo"))
            check(f"{title}: ошибок JS нет", not errs, str(errs[:3]))
            ctx.close()
            return out
        finally:
            srv.shutdown()
            srv.server_close()

    q, sub, todo = case("скилл закрыл месяц", {"records": [REC(K(PPM)), REC(K(PM))]}, SITE(3))
    check("аудит скилла за свежий месяц главнее: «% без замечаний», «аудит учёта», «Надо» нет",
          "без замечаний" in q and "сайт" not in q and sub.startswith("аудит учёта") and not todo, f"{q} | {sub} | {todo}")
    q, sub, todo = case("только сайт, отметки есть", {"records": [REC(K(PPM))]}, SITE(3))
    check("свежий месяц проверен только сайтом: «проверки сайта: 3 отметки», подпись «аудит сайта …», «Надо» нет",
          q == "проверки сайта: 3 отметки" and sub.startswith("аудит сайта ") and not todo, f"{q} | {sub} | {todo}")
    q, sub, todo = case("только сайт, отметок нет", {"records": [REC(K(PPM))]}, SITE(0))
    check("сайт без отметок: «проверки сайта: без отметок»", q == "проверки сайта: без отметок" and sub.startswith("аудит сайта"), f"{q} | {sub}")
    q, sub, todo = case("только сайт + открытые замечания прошлых аудитов",
                        {"records": [REC(K(PPM))], "issues": {"a": {"status": "open"}, "b": {"status": "open"}, "c": {"status": "fixed"}}}, SITE(1))
    check("открытые замечания скилла остаются в строке перед проверками сайта",
          q == "2 замечания открыто · проверки сайта: 1 отметка", q)
    q, sub, todo = case("месяц не закрыт никем", {"records": [REC(K(PPM))]}, None)
    check("нет ни аудита скилла, ни сайта за свежий месяц: показан прошлый аудит скилла и «Надо»",
          "без замечаний" in q and sub.startswith("аудит учёта") and todo, f"{q} | {sub} | {todo}")


if __name__ == "__main__":
    per_engine(run, engines=("chromium",))
    print(f"hub_money_tile: {check.passed} OK, {check.failed} FAIL")
    sys.exit(1 if check.failed else 0)
