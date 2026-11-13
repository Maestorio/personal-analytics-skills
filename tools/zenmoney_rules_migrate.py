#!/usr/bin/env python3
"""Миграция правил «разовая»: тройка операции и названия места — в сам `spending-rules.json`.

Дописывает `op` ({date, account, amount}) правилам `one_off` и `names` — правилам `one_off_merchants` из ручного
`rule-ops.json`; правила, которых там нет, пытается найти по записи месяца в выгрузке (как `zm_csv`).
Без `--write` только показывает сводку; с `--write` — копия `*.before-rules-op-<дата>` рядом и запись
с проверкой `validate_rules`. В сводку идут числа, а note и месяц — только у ненайденных.

  python3 tools/zenmoney_rules_migrate.py --rules spending-rules.json --rule-ops rule-ops.json \
      [--spending spending.json --csv выгрузка.csv --aux папка_aux] [--write]

Только stdlib. Поиск по записи месяца использует разбор CSV из `zenmoney_csv_backfill.py`.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "skills/zenmoney-analyst/scripts", ROOT / "tools", ROOT / "tools/hosting/notify"):
    if str(_p) not in sys.path:
        sys.path.append(str(_p))


def _triple(k):
    amount = float(k[2])
    return {"date": k[0], "account": k[1], "amount": int(amount) if amount == int(amount) else amount}


def migrate(rules, rule_ops, written=None, ops=None):
    """→ (новые правила, {filled_op, filled_names, filled_by_record, kept, missing: [(note, month|None)]}).
    Файлов не пишет."""
    import audit_history as AH
    from zm_csv import match_by_record
    ro_ops, ro_merch = (rule_ops or {}).get("ops") or {}, (rule_ops or {}).get("merchants") or {}
    new = json.loads(json.dumps(rules))
    st = {"filled_op": 0, "filled_names": 0, "filled_by_record": 0, "kept": 0, "missing": []}
    for x in new.get("one_off", []):
        if "op" in x:
            st["kept"] += 1
            continue
        k = ro_ops.get(x["id"])
        if k:
            x["op"] = _triple(k)
            st["filled_op"] += 1
            continue
        hits = match_by_record(x, written or {}, ops) if (written and ops) else []
        if len(hits) == 1:
            x["op"] = _triple(hits[0]["_key"])
            st["filled_op"] += 1
            st["filled_by_record"] += 1
        else:
            st["missing"].append((x.get("note"), x.get("month")))
    for x in new.get("one_off_merchants", []):
        if "names" in x:
            st["kept"] += 1
            continue
        v = ro_merch.get(x["merchant_id"])
        if v:
            x["names"] = [v] if isinstance(v, str) else list(v)
            st["filled_names"] += 1
        else:
            st["missing"].append((x.get("note"), None))
    errs = AH.validate_rules(new)
    if errs:
        raise SystemExit("правила после миграции не прошли проверку: " + "; ".join(errs))
    return new, st


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rules", required=True)
    ap.add_argument("--rule-ops", required=True)
    ap.add_argument("--spending")
    ap.add_argument("--csv")
    ap.add_argument("--aux")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    rp = Path(a.rules)
    rules = json.loads(rp.read_text(encoding="utf-8"))
    ro = Path(a.rule_ops)
    rule_ops = json.loads(ro.read_text(encoding="utf-8")) if ro.is_file() else {}
    written = ops = None
    if a.spending and a.csv and a.aux:
        import zenmoney_csv_backfill as B
        import zenmoney_payee_map as PM
        sp = json.loads(Path(a.spending).read_text(encoding="utf-8"))
        written = {m["month"]: m for m in sp.get("months", [])}
        with tempfile.TemporaryDirectory(prefix="zm-rules-mig-") as tmp:
            work = Path(tmp)
            for f in Path(a.aux).glob("*.json"):
                shutil.copy2(f, work / f.name)
            pmap = PM.load(work / "payee-map.json")
            ops, _refs, _notes = B.build(Path(a.csv), work, pmap)
    new, st = migrate(rules, rule_ops, written, ops)
    print(f"правил разовая: {len(new.get('one_off', []))}, мест: {len(new.get('one_off_merchants', []))}")
    print(f"заполнено op: {st['filled_op']} (из них по записи месяца: {st['filled_by_record']}), "
          f"names: {st['filled_names']}, уже было: {st['kept']}")
    print(f"не найдено: {len(st['missing'])}")
    for note, month in st["missing"]:
        print(f"  - {note} {month or ''}".rstrip())
    if not a.write:
        print("сухой прогон — ничего не записано (--write для записи)")
        return 0
    if new == rules:
        print("менять нечего")
        return 0
    bak = rp.with_name(f"{rp.name}.before-rules-op-{date.today().isoformat()}")
    shutil.copy2(rp, bak)
    rp.write_text(json.dumps(new, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"записано; копия — {bak.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
