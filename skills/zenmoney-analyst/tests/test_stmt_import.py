#!/usr/bin/env python3
"""stmt_import.py — точка входа режимов E/F: банк, тип счёта и валюта определяются по содержимому файла.

Зачем (решение 2026-10-11): пользователь не хочет объяснять, «что есть что» — приложил файлы, скилл сам
узнаёт банк и роль файла, говорит, чего не хватает, и отказывается угадывать неизвестный банк.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
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


print("\n== определение банка ==")
check("FF по русскому названию банка в шапке", si.detect_bank("АО «Фридом Банк Казахстан»\nВыписка по текущему счету") == "ff")
check("FF по английскому названию и SWIFT", si.detect_bank("FREEDOM BANK KAZAKHSTAN JSC") == "ff" and si.detect_bank("SWIFT/BIC KSNVKZKA") == "ff")
check("регистр не важен", si.detect_bank("фридом БАНК казахстан") == "ff")
check("чужой банк — не узнан (None), не угадывается", si.detect_bank("Т-Банк, выписка по счёту") is None)
check("пустой файл — не узнан", si.detect_bank("") is None)

print("\n== run: разбор, группировка, что не хватает ==")


class Blocking(Exception):
    pass


def make_banks(statements):
    def parse(path):
        return statements[Path(path).name]

    def normalize(parsed):
        cur = {s["meta"]["currency"] for s in parsed["statements"] if s["meta"]["kind"] == "current"}
        miss = [c for c in ("RUB", "USD") if c not in cur]
        if miss:
            raise Blocking("нет текущих выписок: " + ", ".join(miss))
        return {"operations": [], "flags": []}
    return {"xx": {"name": "Тестовый банк", "signatures": ["тестбанк"], "loader": lambda: (parse, normalize, Blocking)}}


def st(cur, kind="current"):
    return {"meta": {"currency": cur, "kind": kind, "period_from": "01.01.2026", "period_to": "31.12.2026"}, "rows": [], "checks": {"ok": True}}


stmts = {"a.pdf": st("RUB"), "b.pdf": st("USD"), "c.pdf": st("USD", "deposit"), "only_rub.pdf": st("RUB")}
heads = {"a.pdf": "ТестБанк", "b.pdf": "ТЕСТБАНК выписка", "c.pdf": "тестбанк", "only_rub.pdf": "тестбанк", "z.pdf": "Неведомый банк"}
rd = lambda p: heads[Path(p).name]
r = si.run(["/x/a.pdf", "/x/b.pdf", "/x/c.pdf"], make_banks(stmts), rd)
check("файлы описаны сами: банк, тип, валюта, период", [(f["kind"], f["currency"]) for f in r["files"]] == [("current", "RUB"), ("current", "USD"), ("deposit", "USD")], r["files"])
check("комплект полный — операции получены, ничего не пропало", "xx" in r["banks"] and not r["missing"] and not r["unrecognized"])
r = si.run(["/x/only_rub.pdf"], make_banks(stmts), rd)
check("не хватает выписки — сказано, чего именно", r["missing"] and "USD" in r["missing"][0]["why"], r["missing"])
r = si.run(["/x/a.pdf", "/x/z.pdf"], make_banks(stmts), rd)
check("файл неизвестного банка — в unrecognized, остальное разобрано", r["unrecognized"] == ["z.pdf"] and [f["file"] for f in r["files"]] == ["a.pdf"], r)

DOCS = ROOT.parent.parent / "docs" / "zenmoney"
files = sorted(DOCS.glob("текущ_*.pdf")) + sorted(DOCS.glob("депозит_*.pdf"))
if len(files) == 8:
    print("\n== интеграция: 8 выписок FF 2026 «вслепую» (без пояснений) ==")
    res = si.run([str(f) for f in files])
    kinds = sorted((f["currency"], f["kind"]) for f in res["files"])
    check("все 8 узнаны как FF с верными типом и валютой", len(res["files"]) == 8 and kinds == sorted((c, k) for c in ("RUB", "USD", "KZT", "EUR") for k in ("current", "deposit")), kinds)
    check("комплект полный, банк узнан, операции собраны", not res["missing"] and not res["unrecognized"] and len(res["banks"]["ff"]["operations"]) > 80)
    res = si.run([str(f) for f in files if "EUR" not in f.name])
    check("без EUR-выписок: «не хватает EUR», а не молчаливый пропуск", res["missing"] and "EUR" in res["missing"][0]["why"], res["missing"])
else:
    print("\n  (реальные выписки не лежат рядом — интеграция пропущена)")

print(f"\nИтого: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
