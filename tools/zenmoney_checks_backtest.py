#!/usr/bin/env python3
"""Бэктест проверок выгрузки (tools/hosting/notify/zm_checks.py) по цепочке выгрузок CSV. Не для сайта.

Суррогат эталона: срабатывание на операции (или месяце) в выгрузке N подтверждено, если в одной из СЛЕДУЮЩИХ
выгрузок эта операция изменена в том же измерении (категория / место / дата / удалена или сумма-счёт изменены —
ключ операции как в zm_csv._key), а для месячных проверок (N2, N9, B6') — итог месяца/категории/счёта сдвинулся.
Срабатывания, впервые замеченные в последней выгрузке, не оцениваются (не с чем сравнить). Слабости суррогата —
в docs/zenmoney/csv-checks-research.md §4а.

  python3 tools/zenmoney_checks_backtest.py --source docs/zenmoney/source --aux docs/zenmoney/csv \\
      --audit <Claude-Memory/ZenMoney/audit> --out <папка>

Пишет в --out: zm-checks-backtest.md (таблица без названий и сумм) и zm-checks-backtest-private.md (примеры —
личные данные, в репозиторий не класть).
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tools/hosting/notify"))
import zm_checks as ZC  # noqa: E402
import zm_csv  # noqa: E402

AM, MS, B, PM = None, None, None, None


def _mods():
    global AM, MS, B, PM
    _a, AM, MS, _t, B, PM = zm_csv._scripts()


MSK_MONTHS = 3          # проверяемых закрытых месяцев на выгрузку


def dump_date(p):
    return date.fromisoformat(re.search(r"zen_(\d{4}-\d{2}-\d{2})", p.name).group(1))


def closed_months(today, n):
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(f"{y}-{m:02d}")
    return sorted(out)


def rates_dict(aux):
    cache = json.loads((aux / "rates-cbr.json").read_text(encoding="utf-8"))
    rates = {}
    zm = aux / "rates-zm.json"
    if zm.exists():
        for x in json.loads(zm.read_text(encoding="utf-8"))["data"]:
            rates[(x["instrument"], x["date"])] = x["rate"]
    for d, insts in cache.items():
        for inst, v in insts.items():
            rates.setdefault((inst, d), v)
    return rates


def load_dump(path, aux, audit):
    rows = zm_csv.read_csv(path)
    pmap = PM.load(aux / "payee-map.json")
    ops, refs, _notes = B.build(path, aux, pmap)
    rule_ops = json.loads((aux / "rule-ops.json").read_text(encoding="utf-8"))
    src = audit / "spending-rules.json"
    tmp = Path(path).parent / ".none"
    rules_path = src if src.exists() else tmp
    try:
        rules, _miss = B.rules_for_csv(rules_path, rule_ops, ops, pmap.meta["by_text"] if pmap else None)
    except Exception:  # noqa: BLE001
        rules = {}
    import tempfile
    with tempfile.TemporaryDirectory() as t:
        rp = Path(t) / "r.json"
        rp.write_text(json.dumps(rules), encoding="utf-8")
        cfg = MS.load_rules(str(rp), {})
    meta = {}
    for o in ops:
        r = rows[int(o["id"][4:]) - 2]
        meta[o["id"]] = (r["createdDate"], r["changedDate"])
    clean = [{k: v for k, v in o.items() if not k.startswith("_")} for o in ops]
    ctx = AM.Ctx(clean, refs, None, rates_dict(aux), cfg, set())
    tr = json.loads((aux / "trip-ids.json").read_text(encoding="utf-8"))
    known = set(pmap.meta["by_text"].values()) | set(pmap.meta["by_op"].values()) if pmap else set()
    hist = {"trip_dates": tr.get("dates") or {}, "known_places": known}
    return rows, clean, refs, ctx, hist, meta


def row_of(rows, op_id):
    return rows[int(op_id[4:]) - 2]


def identity(h, rows):
    if h["op_ids"]:
        return (h["id"], frozenset(zm_csv._key(row_of(rows, i)) for i in h["op_ids"]))
    return (h["id"], h["month"], h["subject"])


CAT_CHECKS = {"A3", "D13", "P1", "N5"}
MISSING_CHECKS = {"A1", "A5", "N1", "P2", "N7"}


def confirmed(h, old_rows, later):
    """later — выгрузка (rows, index, agg) после той, где сработало; True — изменено в том же измерении."""
    rows_l, idx_l, agg_l = later["rows"], later["idx"], later["agg"]
    cid = h["id"]
    if h["op_ids"]:
        pairs = []
        for i in h["op_ids"]:
            r = row_of(old_rows, i)
            pairs.append((r, idx_l.get(zm_csv._key(r))))
        for r, n in pairs:
            if cid in MISSING_CHECKS and n is None:
                return True
            if cid == "A4" and (n is None or (n["categoryName"].split(", ")[0] != r["categoryName"].split(", ")[0])):
                return True
            if cid in CAT_CHECKS and n is not None and n["categoryName"] != r["categoryName"]:
                return True
            if cid == "N3" and (n is None or n["categoryName"] != r["categoryName"]):
                return True
            if cid == "B7" and (n is None or n["categoryName"] != r["categoryName"]):
                return True
            if cid in ("P3", "P4") and n is not None and n["payee"] != r["payee"]:
                return True
            if cid == "N6" and (n is None or n["date"] != r["date"]):
                return True
            if cid == "N10" and (n is None or n["comment"] != r["comment"]):
                return True
        return False
    m = h["month"]
    a_new = agg_for(agg_l, m)
    a_old = h["_agg"]
    if cid in ("N2", "N2i"):
        key = "exp" if cid == "N2" else "inc"
        o, n = a_old[key].get(h["subject"], 0.0), a_new[key].get(h["subject"], 0.0)
        return abs(n - o) > max(500.0, 0.01 * abs(o))
    if cid == "N9":
        return a_new["n"] > a_old["n"] * 1.05
    if cid == "B6'":
        return h["subject"] in a_new["accs"] and h["subject"] not in a_old["accs"]
    return False


def agg_for(store, m):
    return store.get(m) or {"exp": {}, "inc": {}, "n": 0, "accs": set()}


def process(path, aux, audit, months=None):
    rows, ops, refs, ctx, hist, meta = load_dump(path, aux, audit)
    today = dump_date(path)
    months = months or closed_months(today, MSK_MONTHS)
    cfg = {"today": today}
    hits = ZC.collect(ops, refs, ctx, hist, months, cfg, meta)
    D = ZC._Data(ops, ctx, ZC._cfg(cfg))
    agg = {m: D.agg(m) for m in sorted({x["date"][:7] for x in ops})}
    return {"path": path, "date": today, "rows": rows, "idx": {zm_csv._key(r): r for r in reversed(rows)},
            "ops": ops, "ctx": ctx, "hist": hist, "meta": meta, "refs": refs, "hits": hits, "agg": agg,
            "months": months, "D": D}


def table(lines):
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True)
    ap.add_argument("--aux", required=True)
    ap.add_argument("--audit", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    _mods()
    src, aux, audit, out = Path(a.source), Path(a.aux), Path(a.audit), Path(a.out)
    files = sorted(src.glob("zen_*.csv"), key=lambda p: (dump_date(p), p.name))
    runs = []
    for f in files:
        print("dump", f.name, file=sys.stderr)
        runs.append(process(f, aux, audit))
    last = len(runs) - 1
    first_seen = {}
    for i, r in enumerate(runs):
        for h in r["hits"]:
            h["_agg"] = r["agg"][h["month"]] if h["month"] in r["agg"] else {"exp": {}, "inc": {}, "n": 0, "accs": set()}
            first_seen.setdefault(identity(h, r["rows"]), (i, h))
    stat = defaultdict(lambda: {"total": 0, "assess": 0, "conf": 0})
    for ident, (i, h) in first_seen.items():
        s = stat[h["id"]]
        s["total"] += 1
        if i == last:
            continue
        s["assess"] += 1
        if any(confirmed(h, runs[i]["rows"], runs[j]) for j in range(i + 1, len(runs))):
            s["conf"] += 1
    final = Counter(h["id"] for h in runs[last]["hits"])
    nm = len(runs[last]["months"])

    # k для N2 — сетка 2…5 по тем же правилам
    grid = {}
    for k in (2, 3, 4, 5):
        seen, st = {}, {"N2": [0, 0, 0], "N2i": [0, 0, 0]}
        for i, r in enumerate(runs):
            cfg = ZC._cfg({"n2_k": float(k)})
            D = ZC._Data(r["ops"], r["ctx"], cfg)
            for m in r["months"]:
                for h in ZC._n2(D, m, "exp") + ZC._n2(D, m, "inc"):
                    h["_agg"] = r["agg"][m]
                    seen.setdefault(identity(h, r["rows"]), (i, h))
        for ident, (i, h) in seen.items():
            s = st[h["id"]]
            s[0] += 1
            if i == last:
                continue
            s[1] += 1
            if any(confirmed(h, runs[i]["rows"], runs[j]) for j in range(i + 1, len(runs))):
                s[2] += 1
        grid[k] = st

    # реестр history.json (замечания «ПРОВЕРКА:id») — агрегаты
    reg = Counter()
    hj = audit / "history.json"
    if hj.exists():
        for v in json.loads(hj.read_text(encoding="utf-8")).get("issues", {}).values():
            reg[(v["check"], v["status"])] += 1
    wide = process(files[-1], aux, audit, months=[f"2026-{m:02d}" for m in range(1, 11)])
    wide_c = Counter(h["id"] for h in wide["hits"])

    L = ["# Бэктест проверок выгрузки (без названий и сумм)", "",
         f"Выгрузок в цепочке: {len(runs)}; проверяемых закрытых месяцев на выгрузку: {MSK_MONTHS}; "
         f"в последней выгрузке проверено месяцев: {nm}. Дата прогона: {date.today()}.", "",
         "| проверка | срабатываний всего | оценимых | подтверждено | точность | в последней выгрузке (на месяц) |",
         "|---|---|---|---|---|---|"]
    for id_ in ZC.ORDER:
        s = stat.get(id_, {"total": 0, "assess": 0, "conf": 0})
        p = f"{100 * s['conf'] / s['assess']:.0f} %" if s["assess"] else "—"
        L.append(f"| {id_} | {s['total']} | {s['assess']} | {s['conf']} | {p} | {final.get(id_, 0)} ({final.get(id_, 0) / nm:.1f}) |")
    L += ["", "## Подбор k для N2 / N2i", "", "| k | N2 срабатываний | оценимых | подтверждено | точность | N2i срабатываний | оценимых | подтверждено | точность |",
          "|---|---|---|---|---|---|---|---|---|"]
    for k, st in grid.items():
        row = [str(k)]
        for c in ("N2", "N2i"):
            t, asx, cf = st[c]
            row += [str(t), str(asx), str(cf), f"{100 * cf / asx:.0f} %" if asx else "—"]
        L.append("| " + " | ".join(row) + " |")
    L += ["", "## Сверка с реестром замечаний history.json", "",
          "Реестр содержит только замечания проверок A2–A5 (записаны скиллом при закрытии месяцев).", "",
          "| проверка | в реестре (статус: число) | срабатываний в 2026-01…2026-10 по последней выгрузке |", "|---|---|---|"]
    for c in ("A1", "A3", "A4", "A5", "B7", "D13"):
        st = ", ".join(f"{s}: {n}" for (cc, s), n in sorted(reg.items()) if cc == c) or "нет"
        L.append(f"| {c} | {st} | {wide_c.get(c, 0)} |")
    (out / "zm-checks-backtest.md").write_text(table(L), encoding="utf-8")

    P = ["# Бэктест — примеры (ЛИЧНЫЕ ДАННЫЕ, в репозиторий не класть)", ""]
    byid = defaultdict(list)
    for h in runs[last]["hits"]:
        byid[h["id"]].append(h)
    for id_ in ZC.ORDER:
        P += [f"## {id_} — {ZC.TEXTS[id_]} (в последней выгрузке: {len(byid[id_])})", ""]
        for h in byid[id_][:6]:
            P.append(f"- {h['month']} {json.dumps(h['detail'], ensure_ascii=False)}")
        P.append("")
    (out / "zm-checks-backtest-private.md").write_text("\n".join(P), encoding="utf-8")
    print(table(L))


if __name__ == "__main__":
    main()
