#!/usr/bin/env python3
"""stmt_accounts.py — подвязка счетов банка к счетам ZenMoney по названию и валюте, без номера счёта (2026-10-11)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import stmt_accounts as sa  # noqa: E402
import stmt_import as si  # noqa: E402

ok = fail = 0


def check(name, cond, extra=None):
    global ok, fail
    if cond:
        ok += 1
        print(f"  [OK] {name}")
    else:
        fail += 1
        print(f"  [FAIL] {name} {extra if extra is not None else ''}")


A = lambda i, name, ccy, **kw: {"externalIds": kw.pop("ext", []), "id": i, "name": name, "instrument": ccy, "type": kw.pop("type", "card"), "isSavings": kw.pop("isSavings", False), "isArchived": kw.pop("isArchived", False), **kw}
lst = {"data": [
    A("g", "BOG Лари", "GEL"), A("u", "BOG $", "USD"), A("e", "BOG €", "EUR"), A("d", "BOG Депозит $", "USD", type="deposit", isSavings=True),
    A("ff1", "FF bank - rub", "RUB"), A("ff2", "FF bank, $", "USD"), A("t", "Tinkoff Black USD", "USD"), A("old", "BOG старый $", "USD", isArchived=True),
]}
P_BOG, P_FF = si.BANKS["bog"]["account_patterns"], si.BANKS["ff"]["account_patterns"]

print("\n== выбор по названию, валюте и типу ==")
r = sa.resolve(lst, P_BOG, ["GEL", "USD", "EUR", "GBP"])
check("по одному счёту на валюту; депозит и архивный не берутся", r["accounts"] == {"GEL": "g", "USD": "u", "EUR": "e"}, r)
check("валюты без счёта — missing, не выдумываются", r["missing"] == ["GBP"])
check("депозитный счёт отдаётся отдельно (для сверки переводов на депозит)", r["savings"] == {"USD": [{"id": "d", "name": "BOG Депозит $", "iban_check": "unknown"}]})
r = sa.resolve(lst, P_FF, ["RUB", "USD", "KZT", "EUR"])
check("«FF» не цепляет «Tinkoff» (слово целиком)", r["accounts"] == {"RUB": "ff1", "USD": "ff2"} and r["missing"] == ["KZT", "EUR"], r)
lst2 = {"data": lst["data"] + [A("u2", "BOG $ запасной", "USD")]}
r = sa.resolve(lst2, P_BOG, ["USD"])
check("два подходящих счёта одной валюты — ambiguous (спросить), не угадывать", "USD" not in r["accounts"] and len(r["ambiguous"]["USD"]) == 2, r)
check("название по-русски и по-английски", sa.resolve({"data": [A("x", "Банк Грузии USD", "USD")]}, P_BOG, ["USD"])["accounts"] == {"USD": "x"} and sa.resolve({"data": [A("x", "bank of georgia", "USD")]}, P_BOG, ["USD"])["accounts"] == {"USD": "x"})

print("\n== institution и externalIds ==")
inst = {"data": [A("i1", "Мой доллар", "USD", institution={"name": "Bank of Georgia"}, ext=["2USD"]), A("i2", "Депозит", "USD", type="deposit", isSavings=True, institution={"name": "Bank of Georgia"}, ext=["0830"])]}
r = sa.resolve(inst, P_BOG, ["USD"], iban="GE70BG0000000539567482")
check("банк определяется и по названию учреждения, если в названии счёта метки нет", r["accounts"] == {"USD": "i1"}, r)
check("externalIds «2USD» = последняя цифра IBAN + валюта → match", r["iban_check"] == {"USD": "match"})
check("депозит «0830» против выписки …0831 — mismatch (другой счёт банка)", sa.resolve(inst, P_BOG, ["USD"], iban="GE88BG0000000607700831")["savings"]["USD"][0]["iban_check"] == "mismatch")
check("депозит «0830» против выписки …0830 — match", sa.resolve(inst, P_BOG, ["USD"], iban="GE18BG0000000607700830")["savings"]["USD"][0]["iban_check"] == "match")
check("IBAN не дан или externalIds непонятные — unknown, не mismatch", sa.iban_check(inst["data"][0], None) == "unknown" and sa.iban_check({"instrument": "RUB", "externalIds": ["7035x"]}, "GE00") == "unknown")

print("\n== сверка остатков (страховка подвязки) ==")
check("остаток банка = остатку ZenMoney — пусто", sa.check_balances({"USD": "11.51", "GEL": "0"}, {"USD": 11.51, "GEL": 0}) == [])
check("не сошлось — названа валюта", sa.check_balances({"USD": "11.51"}, {"USD": 11.52}) == ["USD: банк 11.51, ZenMoney 11.52"])

print("\n== реальный список счетов (если лежит рядом) ==")
real = ROOT.parent.parent / "docs" / "zenmoney" / "source" / "bog-regression" / "list-accounts.json"
if real.exists():
    r = sa.resolve(json.loads(real.read_text(encoding="utf-8")), P_BOG, ["GEL", "USD", "EUR"])
    check("реальные счета BOG находятся однозначно по названию и валюте", len(r["accounts"]) == 3 and not r["ambiguous"] and not r["missing"], r)
else:
    print("  (нет файла — пропуск)")
print(f"\nИтого: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
