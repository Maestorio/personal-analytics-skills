#!/usr/bin/env python3
"""Разовый внутренний скрипт: статистика месяцев ZenMoney из CSV-выгрузки приложения.

Зачем: «закрой месяц» через MCP читает операции страницами по 200 — на 15 лет
истории это сотни вызовов. Выгрузка CSV из приложения даёт все операции разом.
Скрипт превращает её в операции формата MCP и считает месяцы ТЕМ ЖЕ кодом
скилла (`month_stats.compute`), поэтому правила те же: очищенные итоги, три
корзины (поездки → разовые → обычные), места платежа с `kind`, разовые поштучно.

Чего в CSV нет и как это закрыто:
  * ID операций — разовые из `spending-rules.json` находятся по (дата, счёт, сумма)
    из самого правила (`op`), запасной — `rule-ops.json`; разовые места — по названию места (payee);
  * курсы — ЦБ на дату операции (`XML_daily`), кеш в `rates-cbr.json`; совпадают
    с курсами ZenMoney (сверено 2026-10-06 по GEL июля–августа). Криптовалют у ЦБ
    нет — такие операции уходят в `unconverted`;
  * признаки категорий (доходная/расходная) — `category-flags.json`;
  * «в балансе» у счёта — из `list_accounts` (`accounts.json`);
  * место: «Кому» в CSV у мест, поставленных плагином банка, — сырой текст банка
    («PRODUKTY ERMOLINO» вместо «Ермолино»). Название места берётся из словаря
    `payee-map.json` (`tools/zenmoney_payee_map.py`, собирается из страниц MCP);
    без словаря на странице окажутся тексты банка — скрипт предупреждает.

Гейт: месяцы, уже записанные в `spending.json` скиллом (по MCP), пересчитываются
и сверяются до рубля — расхождение значит, что CSV-путь считает иначе, и
записывать его месяцы нельзя.

  python3 tools/zenmoney_csv_backfill.py --csv <выгрузка.csv> --data docs/zenmoney/csv \\
      --audit <Claude-Memory/ZenMoney/audit> [--from 2025-01] [--to 2026-09] [--out <папка>]

Ничего не пишет в Claude-Memory: кладёт результаты month_stats по месяцам в
`--out` (по умолчанию <data>/runs/) и печатает сверку. Запись — отдельно, штатным
`audit_history.py spending --run … --write` (dry-run, хэш, .bak).

Выгрузка и вспомогательные файлы лежат в docs/zenmoney/csv/ и в git не идут
(.gitignore) — там личные финансы.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "zenmoney-analyst" / "scripts"
sys.path.insert(0, str(SKILL))
from audit_month import Ctx, month_bounds  # noqa: E402
from month_stats import compute, load_rules  # noqa: E402
import trip_stats  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import zenmoney_payee_map  # noqa: E402

CSV_TO_MCP_CURRENCY = {"ETH": "µETH"}       # в CSV — µETH под кодом ETH (VDSina 15 162 = µETH)
NOT_AT_CBR = {"TON", "µETH"}
ROW_KEYS = ("date", "categoryName", "payee", "comment", "outcomeAccountName", "outcome", "incomeAccountName", "income")
AS_OF = "2026-10-06"


# ─── CSV → операции MCP ──────────────────────────────────────────────────────

def num(s):
    return float(s.replace(",", ".")) if s else 0.0


def build(csv_path, data_dir, pmap=None):
    flags = json.loads((data_dir / "category-flags.json").read_text(encoding="utf-8"))
    income_only, both = set(flags["income_only"]), set(flags["both"])
    accs = json.loads((data_dir / "accounts.json").read_text(encoding="utf-8"))["data"]
    by_name = defaultdict(list)
    for a in accs:
        by_name[(a["name"], a["instrument"])].append(a)

    cats, accounts, merchants, notes = {}, {}, {}, Counter()

    def cat_id(path):
        """«Питание / Магазины» → id = путь; родитель — первая часть."""
        path = path.strip()
        if path in cats:
            return path
        parts = [p.strip() for p in path.split(" / ", 1)]
        parent = None
        if len(parts) == 2:
            parent = cat_id(parts[0])
        inc = path in income_only or path in both
        exp = path not in income_only
        cats[path] = {"name": parts[-1], "parentId": parent, "isIncome": inc, "isExpense": exp, "isArchived": False}
        return path

    def acc_id(name, cur):
        inst = CSV_TO_MCP_CURRENCY.get(cur, cur)
        aid = f"{name}|{inst}"
        if aid not in accounts:
            cand = by_name.get((name, inst)) or []
            flags_ = {a.get("isInBalance") is not False for a in cand}
            if not cand:
                notes[f"счёт не найден в list_accounts: {name} ({inst}) — считаю в балансе"] += 1
            elif len(flags_) > 1:
                notes[f"два счёта «{name}» ({inst}) с разным «в балансе» — считаю в балансе"] += 1
            accounts[aid] = {"name": name, "instrument": inst, "type": (cand[0]["type"] if cand else "checking"),
                             "isInBalance": (True if len(flags_) != 1 else flags_.pop())}
        return aid

    ops = []
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        for n, r in enumerate(csv.DictReader(f, delimiter=";"), start=2):
            out_a, in_a = r["outcomeAccountName"], r["incomeAccountName"]
            out_v, in_v = num(r["outcome"]), num(r["income"])
            op = {"id": f"csv-{n}", "date": r["date"]}
            if out_v and in_v and out_a != in_a:
                op["expense"] = {"accountId": acc_id(out_a, r["outcomeCurrencyShortTitle"]), "amount": out_v}
                op["income"] = {"accountId": acc_id(in_a, r["incomeCurrencyShortTitle"]), "amount": in_v}
            elif out_v and not in_v:
                op["expense"] = {"accountId": acc_id(out_a, r["outcomeCurrencyShortTitle"]), "amount": out_v}
            elif in_v and not out_v:
                op["income"] = {"accountId": acc_id(in_a, r["incomeCurrencyShortTitle"]), "amount": in_v}
            else:
                notes["строка без суммы или со странными сторонами — пропущена"] += 1
                continue
            if r["categoryName"]:
                first, *tags = split_cats(r["categoryName"])
                op["categoryId"] = cat_id(first)
                if tags:
                    op["tagIds"] = [cat_id(t) for t in tags]
            payee = r["payee"]
            side = zenmoney_payee_map.csv_side(r)
            if pmap and side:
                fixed = pmap(r["date"], side[0], side[1], payee)
                if fixed != payee:
                    notes["место по словарю вместо текста «Кому» (payee-map.json)"] += 1
                    payee = fixed
            if payee:
                mid = "p:" + payee
                merchants[mid] = {"id": mid, "name": payee}
                op["merchantId"] = mid
            if r["comment"]:
                op["comment"] = r["comment"]
            op["_key"] = (r["date"], out_a or in_a, out_v or in_v)
            op["_changed"] = r["changedDate"]
            op["_row"] = tuple(r[k] for k in ROW_KEYS)
            ops.append(op)
    refs = {"user": {"currency": "RUB", "monthStartDay": 1}, "accounts": accounts,
            "categories": cats, "merchants": merchants}
    return ops, refs, notes


def split_cats(s):
    """«Одежда, обувь, аксессуары, Путешествия / #Вьетнам'26» → [категория, теги].
    Запятая и разделяет категорию с тегами, и бывает в названии; кусок с маленькой
    буквы — продолжение названия (названия категорий с большой буквы или с «#»)."""
    out = []
    for piece in s.split(", "):
        if out and piece[:1].islower():
            out[-1] += ", " + piece
        else:
            out.append(piece.strip())
    return out


# ─── курсы ЦБ ────────────────────────────────────────────────────────────────

def cbr_day(d):
    url = f"https://www.cbr.ru/scripts/XML_daily.asp?date_req={d[8:10]}/{d[5:7]}/{d[:4]}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (zenmoney-csv-backfill)"})
    for attempt in range(6):
        try:
            raw = urllib.request.urlopen(req, timeout=20).read().decode("cp1251")
            break
        except urllib.error.HTTPError as e:      # ЦБ отвечает 429 на частые запросы и изредка 502–504
            if e.code not in (429, 502, 503, 504) or attempt == 5:
                raise
            time.sleep(5 * (attempt + 1))
    out = {}
    for chunk in raw.split("<Valute ")[1:]:
        code = chunk.split("<CharCode>")[1].split("<")[0]
        nom = float(chunk.split("<Nominal>")[1].split("<")[0])
        val = float(chunk.split("<Value>")[1].split("<")[0].replace(",", "."))
        out[code] = val / nom
    return out


def rates_for(ops, refs, cache_path, frm, to):
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    need = defaultdict(set)
    for op in ops:
        if not (frm <= op["date"][:7] <= to):
            continue
        for s in (op.get("expense"), op.get("income")):
            if s:
                inst = refs["accounts"][s["accountId"]]["instrument"]
                if inst != "RUB" and inst not in NOT_AT_CBR:
                    need[op["date"]].add(inst)
    fresh = [d for d in sorted(need) if d not in cache]
    for i, d in enumerate(fresh):
        cache[d] = cbr_day(d)
        time.sleep(1.0)
        if i % 10 == 9:
            cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    rates = {}
    zm = cache_path.parent / "rates-zm.json"         # курсы ZenMoney для валют, которых нет у ЦБ
    if zm.exists():
        for x in json.loads(zm.read_text(encoding="utf-8"))["data"]:
            rates[(x["instrument"], x["date"])] = x["rate"]
    for d, insts in need.items():
        for inst in insts:
            if inst in cache.get(d, {}) and (inst, d) not in rates:
                rates[(inst, d)] = cache[d][inst]
    return rates, len(fresh)


# ─── правила: ID операций → строки CSV ───────────────────────────────────────

def _rule_ops(data):
    p = Path(data) / "rule-ops.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def rules_for_csv(rules_path, rule_ops, ops, by_text=None):
    """Копия spending-rules.json, где ID операций и мест заменены на CSV-шные.
    Тройка операции и названия места — из самого правила (`op`, `names`); нет — из `rule_ops` (необязательный
    ручной файл `rule-ops.json`, может быть None)."""
    r = json.loads(rules_path.read_text(encoding="utf-8"))
    rule_ops = rule_ops or {}
    ro_ops, ro_merch = rule_ops.get("ops") or {}, rule_ops.get("merchants") or {}
    by_key = defaultdict(list)
    for op in ops:
        by_key[(op["_key"][0], op["_key"][1], round(op["_key"][2], 2))].append(op["id"])
    miss, out = [], []
    for x in r.get("one_off", []):
        o = x.get("op")
        k = [o["date"], o["account"], o["amount"]] if o else ro_ops.get(x["id"])
        hits = by_key.get((k[0], k[1], round(k[2], 2))) if k else None
        if hits and len(hits) > 1:      # две одинаковые покупки в один день — обе не угадать
            hits = None
        if not hits or len(hits) != 1:
            miss.append(f"{x['id']} ({x['note']}): {'нет тройки в правиле и в rule-ops.json' if not k else len(hits or []) or 'нет'} строк")
            continue
        out.append(dict(x, id=hits[0]))
    # у места в CSV может быть несколько написаний (payee) — правило на каждое
    # текст банка → место по словарю (как у операций в build)
    by_text = by_text or {}

    def _names(x):
        v = x.get("names") or ro_merch.get(x["merchant_id"])
        return None if not v else list(dict.fromkeys(by_text.get(n, n) for n in ([v] if isinstance(v, str) else v)))

    om = []
    for x in r.get("one_off_merchants", []):
        ns = _names(x)
        if ns is None:
            miss.append(f"место {x['merchant_id']}: нет имени ни в правиле, ни в rule-ops.json")
            continue
        om += [dict(x, merchant_id="p:" + n) for n in ns]
    return dict(r, one_off=out, one_off_merchants=om), miss


# ─── сверка с записанными месяцами ───────────────────────────────────────────

def close(a, b):
    """До рубля; на больших суммах — до 0,05%: курс ЦБ изредка расходится с ZenMoney
    на день (VND 08.09.2026: −19 ₽ на 101 тыс.)."""
    return abs(a - b) <= max(1.0, 0.0005 * abs(b))


def diff_month(new, old):
    out = []
    for k, v in old["totals"].items():
        if k == "operations":
            continue
        nv = new["totals"].get(k)
        if nv is None or not close(nv, v):
            out.append(f"{k}: было {v:,.0f}, CSV {nv if nv is None else f'{nv:,.0f}'}")
    for key in ("categories_regular", "trips"):
        o = {c["name"]: c["rub"] for c in old.get(key) or []}
        n = {c["name"]: c["rub"] for c in new.get(key) or []}
        for name in sorted(set(o) | set(n)):
            if not close(n.get(name, 0), o.get(name, 0)):
                out.append(f"{key} «{name}»: было {o.get(name, 0):,.0f}, CSV {n.get(name, 0):,.0f}")
    return out


def trips(ctx, data, audit, out, frm):
    """Поездки кодом скилла. Даты — из карты (trip-ids.json), иначе trip_stats выводит их по данным."""
    ti = json.loads((data / "trip-ids.json").read_text(encoding="utf-8"))
    by_name = {c["name"]: cid for cid, c in ctx.cats.items() if c["name"].startswith("#")}
    ctx.cfg = dict(ctx.cfg, trip_dates={by_name[n]: d for n, d in ti["dates"].items() if n in by_name})
    written = {t["trip"]["id"]: t for t in json.loads((audit / "trips.json").read_text(encoding="utf-8"))["trips"]}
    ok = True
    print("\nПоездки:")
    for name, cid in sorted(by_name.items(), key=lambda kv: kv[0][-2:] + kv[0]):
        last = max((o["date"] for o in ctx.ops if o.get("categoryId") == cid or cid in (o.get("tagIds") or [])), default="")
        if last[:7] < frm:
            continue
        if name in ti.get("skip", {}):
            print(f"  – {name}: не пишется — {ti['skip'][name]}")
            continue
        real = ti["ids"].get(name)
        if not real:
            print(f"  ! {name}: нет ID в trip-ids.json — пропущена")
            continue
        ctx.missing = set()
        r = trip_stats.report(ctx, cid, None)
        r["trip"] = {"id": real, "name": name}
        (out / f"trip-{real}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        t, per = r["totals"], r["period"]
        line = (f"  {name:<18} {per['start']}…{per['end']} ({per['basis']}, {per['days']} дн.)  "
                f"всего {t['spent_rub']:>9,.0f}  операций {t['operations']}")
        unc = (r.get("coverage") or {}).get("unconverted") or r.get("unconverted")
        if unc:   # операции без курса дали бы 0 ₽ — итог поездки неверен, писать нельзя
            line += f"  ✗ без курса: {unc}"
            ok = False
        if real in written:
            w = written[real]["totals"]["spent_rub"]
            late = sum(1 for o in ctx.ops if o.get("_late") and (o.get("categoryId") == cid or cid in (o.get("tagIds") or [])))
            if close(t["spent_rub"], w):
                line += "  ✓ сходится с записанным"
            elif late:
                line += f"  ~ записано {w:,.0f}: {late} операций изменено в ZenMoney после записи — права выгрузка"
            else:
                line += f"  ✗ записано {w:,.0f}"
                ok = False
        print(line)
    return ok


def months_between(a, b):
    y, m = map(int, a.split("-"))
    while f"{y}-{m:02d}" <= b:
        yield f"{y}-{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--csv", required=True)
    p.add_argument("--data", required=True, help="папка с accounts.json, category-flags.json (rule-ops.json — необязательный запасной)")
    p.add_argument("--audit", required=True, help="Claude-Memory/ZenMoney/audit (только чтение)")
    p.add_argument("--from", dest="frm")
    p.add_argument("--to")
    p.add_argument("--out")
    p.add_argument("--top", type=int, default=0, help="0 — все места (как month_stats); N — N на категорию + «прочие»")
    p.add_argument("--prev-csv", help="выгрузка, по которой записаны текущие данные: операции, которых в ней нет "
                                      "в том же виде, — правки после записи (точнее, чем время файла)")
    p.add_argument("--trips", action="store_true",
                   help="ещё и поездки (категории «#…», последняя трата не раньше --from): trip_stats.report; "
                        "ID и даты — trip-ids.json; сверка с trips.json")
    p.add_argument("--payee-map", help="словарь «текст банка → место» (по умолчанию <data>/payee-map.json)")
    a = p.parse_args(argv)
    data, audit = Path(a.data), Path(a.audit)
    out = Path(a.out) if a.out else data / "runs"
    out.mkdir(parents=True, exist_ok=True)

    pmap = zenmoney_payee_map.load(a.payee_map or data / "payee-map.json")
    ops, refs, notes = build(a.csv, data, pmap)
    rules, miss = rules_for_csv(audit / "spending-rules.json",
                                _rule_ops(data), ops,
                                pmap.meta["by_text"] if pmap else None)
    rule_dates = {x["note"]: x["date"] for x in rules["one_off"] + rules["one_off_merchants"]}
    rules_path = out / "_rules-csv.json"
    rules_path.write_text(json.dumps(rules, ensure_ascii=False, indent=1), encoding="utf-8")
    sp = json.loads((audit / "spending.json").read_text(encoding="utf-8"))
    written = {m["month"]: m for m in sp["months"]}
    first, last = min(o["date"] for o in ops)[:7], AS_OF[:7]
    frm, to = a.frm or first, a.to or max(m for m in months_between(first, last) if m < last)
    # поездки идут и за последний закрытый месяц (текущая или только что закончившаяся) — курсы нужны до конца данных
    rates, fetched = rates_for(ops, refs, data / "rates-cbr.json", frm, last if a.trips else to)
    # когда записан spending.json: операции, изменённые в ZenMoney позже, объясняют
    # расхождение — тогда права выгрузка (она свежее записи)
    recorded = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime((audit / "spending.json").stat().st_mtime))
    trips_recorded = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime((audit / "trips.json").stat().st_mtime))
    if a.prev_csv:
        with open(a.prev_csv, encoding="utf-8-sig", newline="") as f:
            prev = Counter(tuple(r[k] for k in ROW_KEYS) for r in csv.DictReader(f, delimiter=";"))
        for op in ops:
            op["_new"] = prev[op["_row"]] <= 0
            prev[op["_row"]] -= 1
        recorded = f"выгрузки {Path(a.prev_csv).name}"
        for op in ops:
            op["_changed"], op["_late_m"] = "", op["_new"]
    changed_after = Counter(op["date"][:7] for op in ops if op.get("_late_m") or (not a.prev_csv and op["_changed"] > recorded))
    for op in ops:
        op.pop("_key")
        op["_late"] = op.pop("_new", None) if a.prev_csv else op.pop("_changed") > trips_recorded
        op.pop("_changed", None)
        op.pop("_row", None)
        op.pop("_late_m", None)
    ctx = Ctx(ops, refs, None, rates, load_rules(str(rules_path), {}), set())
    print(f"CSV: {len(ops)} операций {first}…{max(o['date'] for o in ops)}; курсов ЦБ скачано {fetched}")
    if pmap:
        pm = pmap.meta
        print(f"Словарь мест: {pm['built']}, страницы MCP {pm['pages']['from']}…{pm['pages']['to']}, "
              f"текстов {len(pm['by_text'])}, операций {len(pm['by_op'])}")
    else:
        print("  ! словаря мест нет (payee-map.json) — места будут текстом банка из «Кому»; "
              "собрать: tools/zenmoney_payee_map.py build")
    for k, v in notes.items():
        print(f"  ! {k} — {v}")
    for m in miss:
        print(f"  ! правило не найдено в CSV: {m}")

    gate_ok, report = True, []
    for month in months_between(frm, to):
        start, end = month_bounds(month, 1)
        ctx.missing = set()
        cur = compute(ctx, month, start, end, a.top)
        run = {"schema": "zenmoney-month-stats-run@1", "month": month,
               "period": [start.isoformat(), end.isoformat()], "as_of": AS_OF,
               "closed": date.fromisoformat(AS_OF) > end, "main_currency": "RUB", **cur, "compare": None,
               "coverage": {"unconverted": dict(Counter(i for _o, _a, i in ctx.missing)), "history": "csv-backfill"}}
        if not cur["totals"]["operations"]:
            continue
        (out / f"run-{month}.json").write_text(json.dumps(run, ensure_ascii=False, indent=1), encoding="utf-8")
        t = cur["totals"]
        line = (f"{month}: расход {t['expense_rub']:>10,.0f}  обычные {t['expense_regular_rub']:>10,.0f}  "
                f"поездки {t['expense_trips_rub']:>9,.0f}  разовые {t['expense_one_off_rub']:>9,.0f}  "
                f"доход {t['income_rub']:>10,.0f}")
        if run["coverage"]["unconverted"]:
            line += f"  без курса: {run['coverage']['unconverted']}"
        if month in written:
            d = diff_month(cur, written[month])
            late = changed_after.get(month, 0)
            # разовые по правилу, записанному после месяца (VDSina 2026-10-06 → сентябрь)
            new_rules = [x["name"] for x in cur["one_off"]
                         if x["note"] in rule_dates and rule_dates[x["note"]] > written[month]["as_of"]]
            if d and new_rules and not late:
                # старую запись сдвигаем на эти разовые и сверяем заново: прочее должно сойтись
                old = json.loads(json.dumps(written[month]))
                for x in cur["one_off"]:
                    if x["name"] in new_rules:
                        old["totals"]["expense_regular_rub"] -= x["rub"]
                        old["totals"]["expense_one_off_rub"] += x["rub"]
                        for c in old["categories_regular"]:
                            if c["name"] == x["category"]:
                                c["rub"] -= x["rub"]
                d = diff_month(cur, old)
                if not d:
                    line += f"  ~ расходится только на разовые по правилу новее записи ({', '.join(new_rules)}) — права выгрузка"
            line += ("" if new_rules and "правилу" in line else "  ✓ сходится с записанным" if not d else
                     f"  ~ расходится: {late} операций изменено в ZenMoney после записи ({recorded}) — права выгрузка"
                     if late else "  ✗ РАСХОДИТСЯ")
            if d and not late:
                gate_ok = False
                line += "".join(f"\n      {x}" for x in d)
        report.append(line)
    print("\n".join(report))
    if a.trips:
        gate_ok = trips(ctx, data, audit, out, frm) and gate_ok
    print("\nГейт сверки: " + ("пройден" if gate_ok else "НЕ пройден — CSV-месяцы не записывать"))
    return 0 if gate_ok else 1


if __name__ == "__main__":
    sys.exit(main())
