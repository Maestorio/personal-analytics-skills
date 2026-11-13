"""Сверка выписки банка на сайте без ZenMoney и без Claude (этап «Деньги» «меньше ИИ», задача 3.8).
Устройство — docs/zenmoney/stmt-site.md.

Только чтение: ничего не пишет ни в ZenMoney, ни в `ZenMoney/audit/`, ни в карту и словари. Файл выписки лежит в
`ZenMoney/csv/stmt-incoming/<id>.<xlsx|csv>` (кладёт hub-api, он же стирает файл сразу после отчёта и по сроку);
отчёт `zm-stmt-report@1` уходит ответом на запрос и на диск не пишется.

Логики разбора здесь нет: банк узнаёт `stmt_import.detect_bank`, разбирают `parse_<банк>_statement.py`, флаги даёт
`<банк>_normalize.py`, счёт ZenMoney подбирает `stmt_accounts.resolve`, сравнение — `stmt_compare.compare`. Копии
этих скриптов в контейнере лежат в `pdl/skills/zenmoney-analyst/scripts/` (в репозитории — на своих местах).
Сравнение с ZenMoney идёт по последней принятой CSV-выгрузке (`ZenMoney/csv/last.csv`) и `aux/accounts.json`.

Импорт скриптов ленивый: без них hub-notify стартует, а отчёт отвечает понятной ошибкой. Только stdlib
(+ openpyxl для xlsx). Сайт разбирает только Райффайзенбанк (CSV) и Bank of Georgia (XLSX); PDF отклоняет hub-api на входе.
"""
import json
import re
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import zm_csv  # sys.path к скриптам скилла (pdl/ или репозиторий)

SCHEMA = "zm-stmt-report@1"
STMT_DIR = "ZenMoney/csv/stmt-incoming"
EXTS = ("xlsx", "csv")
SITE_BANKS = ("raif", "bog")   # банки, которые разбирает сайт; остальные парсеры скилла остаются для режимов E/F на Маке
MAX_OPS = 1500          # операций выписки в отчёте (больше — operations_truncated)
MAX_LIST = 200          # расхождений каждого списка сравнения
TEXT_MAX = 160
SUPPORTED = "Райффайзенбанк (CSV), Bank of Georgia (XLSX)"
# человеческие названия флагов нормализаторов; незнакомый вид показывается как есть
FLAG_TITLES = {"unknown-row": "строка не распознана", "fee-unlinked": "комиссия без своей покупки",
               "check-failed": "проверка выписки не сошлась", "no-date": "операция без даты",
               "zero-quirk": "нулевое показание остатка у банка"}


class Refused(Exception):
    """Отчёт не построен по понятной причине: code — HTTP-код ответа."""

    def __init__(self, code, text):
        super().__init__(text)
        self.code = code
        self.text = text


def _scripts():
    try:
        import stmt_accounts
        import stmt_compare
        import stmt_import
    except ImportError as e:
        raise Refused(503, f"скрипты скилла zenmoney-analyst не развёрнуты в контейнере: {e}") from None
    return stmt_import, stmt_accounts, stmt_compare


def _dec(x):
    if x in (None, ""):
        return Decimal(0)
    try:
        return Decimal(re.sub(r"[\s  ]", "", str(x)).replace(",", ".").lstrip("+"))
    except InvalidOperation:
        return None


def _iso(s):
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(s).strip()[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def _num(d):
    """Decimal → строка с точкой без экспоненты («-1234.50»)."""
    return format(d, "f")


def _money(a):
    """Сумма из ZenMoney/нормализатора → строка с копейками («77» → «77.00»); больше знаков — как есть."""
    d = Decimal(str(a))
    q = d.quantize(Decimal("0.01"))
    return _num(q if q == d else d)


def _mask(s):
    s = str(s or "").strip()
    return ("…" + s[-4:]) if len(s) > 4 else (s or None)


def _short(s, n=TEXT_MAX):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[:n - 1] + "…"


# ─── общий вид выписки (одна разобранная выписка любого банка) ───────────────

def _rows(st):
    """Строки парсера → [{date, time, amount, currency, text}] со знаком суммы: у банков разные поля
    (debit/credit у FF и BOG, знаковая amount у Райффайзена и Т-Банка)."""
    meta, out = st["meta"], []
    for r in st["rows"]:
        if r.get("amount") is not None:
            a = _dec(r["amount"])
        else:
            c, d = _dec(r.get("credit")), _dec(r.get("debit"))
            a = None if c is None or d is None else c - d
        out.append({"date": _iso(r.get("date")), "time": r.get("time"), "amount": a,
                    "currency": r.get("currency") or meta.get("currency"), "text": _short(r.get("purpose"))})
    return out


def _balances(bank, meta, rows):
    """Сверка «входящий + сумма операций = исходящий» по валютам. Есть не у всех банков: у Райффайзена остатков
    в выписке нет, у Т-Банка нет входящего — тогда `status: unavailable` с причиной."""
    sums = {}
    for r in rows:
        if r["amount"] is not None:
            sums[r["currency"]] = sums.get(r["currency"], Decimal(0)) + r["amount"]
    out = []
    if bank in ("ff", "bog"):
        op = meta["opening"] if isinstance(meta["opening"], dict) else {meta["currency"]: meta["opening"]}
        cl = meta["closing"] if isinstance(meta["closing"], dict) else {meta["currency"]: meta["closing"]}
        for ccy in sorted(set(op) | set(cl) | set(sums)):
            o, c, s = _dec(op.get(ccy)), _dec(cl.get(ccy)), sums.get(ccy, Decimal(0))
            calc = o + s
            diff = c - calc
            out.append({"currency": ccy, "opening": _num(o), "sum_ops": _num(s), "closing": _num(c), "calc": _num(calc),
                        "diff": _num(diff), "status": "match" if diff == 0 else "mismatch", "note": None})
        return out
    why = ("в выписке Райффайзенбанка нет остатков" if bank == "raif" else
           "во входящей справке Т-Банка нет входящего остатка" if bank == "tbank" else "в выписке нет остатков")
    for ccy in sorted(sums) or [meta.get("currency")]:
        c = meta.get("closing") if isinstance(meta.get("closing"), str) else None
        out.append({"currency": ccy, "opening": None, "sum_ops": _num(sums.get(ccy, Decimal(0))),
                    "closing": _num(_dec(c)) if c else None, "calc": None, "diff": None, "status": "unavailable",
                    "note": why + ("; остаток в справке — доступный на " + str(meta.get("closing_date")) if c else "")})
    return out


def _footer(bank, meta, rows):
    """Итоги справки Т-Банка («Пополнения» / «Расходы») против операций — единственная сверка суммы у этого банка."""
    if bank != "tbank" or meta.get("total_in") is None:
        return None
    pos = sum((r["amount"] for r in rows if r["amount"] is not None and r["amount"] > 0), Decimal(0))
    neg = sum((-r["amount"] for r in rows if r["amount"] is not None and r["amount"] < 0), Decimal(0))
    tin, tout = _dec(meta["total_in"]), _dec(meta["total_out"])
    return {"in": _num(tin), "out": _num(tout), "rows_in": _num(pos), "rows_out": _num(neg), "match": tin == pos and tout == neg}


def _flags(st, rows, norm, norm_error):
    """Только то, что умеют скрипты: проверки парсера, флаги нормализатора, нечитаемая дата строки."""
    flags, chk = [], st.get("checks") or {}
    bad = [k for k, v in chk.items() if v is False and k != "ok"]
    errs = [str(e) for k in ("row_errors", "problems") for e in (chk.get(k) or [])]
    if chk.get("ok") is False or bad or errs:
        flags.append({"kind": "check-failed", "date": None,
                      "detail": "арифметика выписки не сошлась — числа не гарантированы" + (": " + ", ".join(bad) if bad else "")})
        flags += [{"kind": "check-failed", "date": None, "detail": _short(e)} for e in errs[:20]]
    if chk.get("zero_quirk"):
        flags.append({"kind": "zero-quirk", "date": None,
                      "detail": f"банк показал нулевой остаток при ненулевом расчёте: {len(chk['zero_quirk'])}"})
    nd = sum(1 for r in rows if not r["date"])
    if nd:
        flags.append({"kind": "no-date", "date": None, "detail": f"строк без читаемой даты: {nd}"})
    for f in (norm or {}).get("flags", []):
        flags.append({"kind": f.get("kind"), "date": f.get("date"), "detail": _short(f.get("detail"), 200)})
    for f in flags:
        f["title"] = FLAG_TITLES.get(f["kind"], f["kind"])
    return flags


# ─── сравнение с ZenMoney по последней принятой CSV-выгрузке ────────────────

def _zen_from_csv(rows, accounts, window):
    """Строки CSV ZenMoney → формат MCP list_transactions для stmt_compare: {data, references}."""
    by_name, dup = {}, set()
    for a in accounts.get("data", []):
        n = a.get("name")
        if n in by_name:
            dup.add(n)
        by_name[n] = a
    refs_acc = {a["id"]: {"instrument": a.get("instrument")} for a in accounts.get("data", [])}
    cats, mers = {}, {}

    def side(name, amount, ccy):
        if not name or not amount:
            return None
        a = by_name.get(name)
        if a is not None and name not in dup:
            aid = a["id"]
        else:
            aid = "n:" + name
            refs_acc.setdefault(aid, {"instrument": ccy})
        return {"accountId": aid, "amount": float(str(amount).replace(",", "."))}
    data = []
    for i, r in enumerate(rows):
        if not window[0] <= r["date"] <= window[1]:
            continue
        inc = side(r["incomeAccountName"], r["income"], r["incomeCurrencyShortTitle"])
        exp = side(r["outcomeAccountName"], r["outcome"], r["outcomeCurrencyShortTitle"])
        if not (inc or exp):
            continue
        z = {"id": f"csv{i}", "date": r["date"], "income": inc, "expense": exp, "comment": r["comment"] or None}
        if r["categoryName"]:
            cid = "c:" + r["categoryName"]
            cats[cid] = {"name": r["categoryName"].split(",")[0].strip()}
            z["categoryId"] = cid
        if r["payee"]:
            mid = "m:" + r["payee"]
            mers[mid] = {"name": r["payee"]}
            z["merchantId"] = mid
        data.append(z)
    return {"data": data, "references": {"accounts": refs_acc, "categories": cats, "merchants": mers}}


def _compare(root, bank, st, view, norm, norm_error):
    """→ {available, reason?, …}. Любая причина невозможности — честная фраза, а не молчание."""
    def no(reason):
        return {"available": False, "reason": reason}
    stmt_import, stmt_accounts, stmt_compare = _scripts()
    csv_dir = Path(root) / zm_csv.CSV_DIR
    if not (csv_dir / "last.csv").is_file():
        return no("на сайте нет принятой выгрузки ZenMoney (last.csv) — сравнивать не с чем")
    if not (csv_dir / "aux" / "accounts.json").is_file():
        return no("нет aux/accounts.json — счета ZenMoney неизвестны")
    if norm is None:
        return no("операции выписки не приведены к общему виду: " + (norm_error or "нормализатор отказал"))
    if not (view["period"]["from"] and view["period"]["to"]):
        return no("у выписки не определён период")
    ccys = sorted({o.get("currency") or (o.get("from") or {}).get("currency") for o in norm["operations"]} - {None})
    if not ccys:
        return no("в выписке нет операций для сравнения")
    try:
        accounts = json.loads((csv_dir / "aux" / "accounts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return no("aux/accounts.json не читается")
    res = stmt_accounts.resolve(accounts, stmt_import.BANKS[bank]["account_patterns"], ccys, st["meta"].get("account") if bank in ("ff", "bog") else st["meta"].get("contract"))
    miss = [c for c in ccys if c not in res["accounts"]]
    if miss:
        why = "несколько подходящих счетов" if any(c in res["ambiguous"] for c in miss) else "подходящего счёта нет"
        return no(f"счёт не сопоставлен ({why}: {', '.join(miss)}) — сравнение с ZenMoney недоступно")
    window = (view["period"]["from"], view["period"]["to"])
    try:
        rows = zm_csv.read_csv(csv_dir / "last.csv")
    except (OSError, ValueError) as e:
        return no(f"last.csv не читается: {_short(e, 80)}")
    zen = _zen_from_csv(rows, accounts, window)
    cmp_ = stmt_compare.compare(norm, zen, {c: res["accounts"][c] for c in ccys}, window[0], window[1])
    names = {a["id"]: a.get("name") for a in accounts.get("data", [])}
    miss_zen = [_bank_item(o) for o in cmp_["missing_in_zen"]]
    miss_bank = [_zen_item(z) for z in cmp_["missing_in_bank"]]
    sm = cmp_["summary"]
    other = {k: sm[k] for k in ("differs", "date_shift", "merged", "partial_transfer", "topup_currency", "to_other_account",
                                 "expense_vs_transfer") if sm.get(k)}
    return {"available": True, "reason": None, "window": {"from": window[0], "to": window[1]},
            "accounts": {c: names.get(res["accounts"][c]) for c in ccys},
            "bank_ops": sm["bank_ops"], "zen_ops": sm["zen_ops"], "matched": sm["matched"], "other": other,
            "missing_in_zen": miss_zen[:MAX_LIST], "missing_in_zen_total": len(miss_zen),
            "missing_in_bank": miss_bank[:MAX_LIST], "missing_in_bank_total": len(miss_bank)}


def _bank_item(o):
    """Операция банка без пары в ZenMoney → строка списка: дата, сумма со знаком, валюта, описание."""
    if o["type"] == "transfer":
        amt, ccy = f'{_money(o["from"]["amount"])} → {_money(o["to"]["amount"])}', f'{o["from"]["currency"]} → {o["to"]["currency"]}'
    else:
        sign = "" if o["type"] in ("topup", "refund") else "-"
        amt, ccy = sign + _money(o["amount"]), o.get("currency")
    text = o.get("place") or o.get("raw") or o.get("text") or o.get("kind") or o["type"]
    return {"date": o["date"], "amount": amt, "currency": ccy, "text": _short(text)}


def _zen_item(z):
    out, inc = z.get("out"), z.get("in")
    if out and inc:
        amt, ccy = f'{_money(out["amount"])} → {_money(inc["amount"])}', f'{out["ccy"]} → {inc["ccy"]}'
    elif out:
        amt, ccy = "-" + _money(out["amount"]), out["ccy"]
    else:
        amt, ccy = _money(inc["amount"]), inc["ccy"]
    text = z.get("merchant") or z.get("original_payee") or z.get("comment") or z.get("category") or ""
    return {"date": z["date"], "amount": amt, "currency": ccy, "text": _short(text)}


# ─── отчёт ───────────────────────────────────────────────────────────────────

def find_file(root, id_):
    for ext in EXTS:
        p = Path(root) / STMT_DIR / f"{id_}.{ext}"
        if p.is_file():
            return p
    return None


def build_report(id_, path, root, now):
    path = Path(path)
    stmt_import, _acc, _cmp = _scripts()
    head = stmt_import._read_head(str(path))
    bank = stmt_import.detect_bank(head)
    if bank not in SITE_BANKS:
        raise Refused(422, "банк не узнан: нужен образец для нового разбора. Сейчас умею: " + SUPPORTED)
    parse, normalize, blocking = stmt_import.BANKS[bank]["loader"]()
    try:
        st = parse(str(path))
    except Exception as e:  # noqa: BLE001 — парсер банка отказал (шапка, колонки, арифметика)
        raise Refused(422, "выписка не разобрана: " + _short(e, 300)) from None
    st["file"] = "statement" + path.suffix
    meta = st["meta"]
    rows = _rows(st)
    norm, norm_error = None, None
    try:
        norm = normalize({"statements": [st]})
    except blocking as e:
        norm_error = _short(e, 300)
    except Exception as e:  # noqa: BLE001
        norm_error = f"{type(e).__name__}: {_short(e, 200)}"
    dated = sorted(r["date"] for r in rows if r["date"])
    period = {"from": _iso(meta.get("period_from")) or (dated[0] if dated else None),
              "to": _iso(meta.get("period_to")) or (dated[-1] if dated else None)}
    ident = meta.get("contract") or meta.get("account")
    ccys = meta.get("currencies") or ([meta["currency"]] if meta.get("currency") else sorted({r["currency"] for r in rows if r["currency"]}))
    view = {"period": period}
    ordered = sorted(rows, key=lambda r: (r["date"] or "", r["time"] or ""))
    ops = [{"date": r["date"], "time": r["time"], "amount": None if r["amount"] is None else _num(r["amount"]),
            "currency": r["currency"], "text": r["text"]} for r in ordered[:MAX_OPS]]
    try:
        compare = _compare(root, bank, st, view, norm, norm_error)
    except Refused:
        raise
    except Exception as e:  # noqa: BLE001 — сравнение не обязано получиться; сама выписка от этого не страдает
        compare = {"available": False, "reason": f"сравнение не построено: {type(e).__name__}: {_short(e, 120)}"}
    bals = _balances(bank, meta, rows)
    flags = _flags(st, rows, norm, norm_error)
    if norm_error:
        flags.append({"kind": "normalize-unavailable", "date": None, "title": "флаги разбора недоступны", "detail": norm_error})
    return {"schema": SCHEMA, "id": id_, "built_at": zm_csv._iso(now), "format": path.suffix.lstrip(".").lower(),
            "bank": bank, "bank_name": stmt_import.BANKS[bank]["name"],
            "account": _mask(ident), "kind": meta.get("kind"), "currencies": ccys, "period": period,
            "ops_count": len(rows), "checks_ok": bool((st.get("checks") or {}).get("ok")),
            "balances": bals, "footer": _footer(bank, meta, rows),
            "flags": flags, "operations": ops, "operations_truncated": len(rows) > MAX_OPS, "compare": compare}


# ─── маршрут hub-notify (без HTTP — тестируется напрямую) ────────────────────

def route_report(root, body, now, read, save, log=None):
    """POST /internal/zm-stmt-report {id} → (код, тело). Ничего не пишет (`save` не вызывается)."""
    t0 = time.monotonic()
    i = (body or {}).get("id")
    if not (isinstance(i, str) and zm_csv.ID_RE.match(i)):
        return 400, {"error": "bad id"}
    path = find_file(root, i)
    if path is None:
        return 404, {"error": "нет такой выписки (файл уже удалён после показа — загрузи заново)", "id": i}
    try:
        report = build_report(i, path, root, now)
    except Refused as e:
        if log:
            log("zm-stmt", "refused", t0, op="report", id=i, code=e.code)
        return e.code, {"error": e.text}
    except Exception as e:  # noqa: BLE001
        if log:
            log("zm-stmt", "error", t0, op="report", id=i, error=f"{type(e).__name__}"[:80])
        return 500, {"error": f"{type(e).__name__}: {str(e)[:300]}"}
    if log:   # в журнал — только числа и банк: ни сумм, ни текстов, ни счетов
        log("zm-stmt", "ok", t0, op="report", id=i, bank=report["bank"], ops=report["ops_count"],
            flags=len(report["flags"]), compare=report["compare"]["available"])
    return 200, report
