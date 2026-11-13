#!/usr/bin/env python3
"""
reconcile_constraints.py — срез ограничений бумаг для обзора недели (Шаг 9.5, Mode 1/2/7/8).

Срез `user_constraints[]` обзора ПРОИЗВОДНЫЙ (schema.md §4.2): строится заново на каждый обзор из действующих
условий (модуль (а): определения `conditions@2` + состояние `conditions-state@1`) и плана владельца
(`ie_actual.per_ticker[*].user_plan` снапшота). Из прошлого обзора ничего не переносится, новое ограничение
скрипт не заводит: ограничение бывает только условием (Режим 9 / `apply_condition.py add`) или словом плана
владельца на сайте.

Правила (на дату обзора `--today`, она же `as_of` среза):
  1. Условие ждёт (`status: pending`) и задаёт `verdict_now` → запись среза с `condition_id`; итоговый вердикт =
     `verdict_now` (первое такое условие по id; у других бумаги другой verdict_now → предупреждение
     `conflicting_verdict_now`, решает аналитик в отчёте). `reason` — по направлению `verdict_on_trigger`:
     вниз → sell_condition, вверх → pending_buy_condition, иначе condition_hold; `until` — дата триггера `date`,
     иначе `valid_until`.
  2. Условие сработало и ждёт владельца (`waits_owner`) → запись с `status: fired`; вердикт не меняется —
     резолюция в отчёте (SKILL.md, Pre-emit checklist).
  3. Аналитический вердикт вверх (BUY/ADD), а слово плана владельца покупку закрывает (направление плана не «вверх»
     и не BALANCE: KEEP / WAIT / SELL) → запись с `plan_field: user_plan`, `reason: user_plan`; вердикт не меняется
     (план — слово владельца, разрыв виден в срезе и в «Сейчас»).
  4. `unconstrained_verdict` (+ уверенность) — только если итоговый вердикт ≠ аналитическому; тогда срез непуст.

Вход: JSON (stdin или --input) {"analytical_verdicts": {KEY: {"verdict": "BUY", "confidence": 0.7}, …}}
  + источники одним из способов:
    --root <Claude-Memory>      Portfolio/conditions.yaml + Portfolio/conditions-state.json;
    --snapshot <portfolio.json> план владельца;
    либо в самом JSON: "conditions": [строки модуля (а)], "plan": {KEY: "WAIT", …} (для проверки без файлов).
Выход: {"as_of", "tickers": {KEY: {advisor_verdict, unconstrained_verdict, unconstrained_verdict_confidence,
        advisor_verdict_constraints[], user_constraints[], waits_owner[], diagnostics[], markdown_block}}, "summary"}.
Поля бумаги копируются в обзор как есть (через delta carry_over_weekly.py); форму среза проверяет
save-to-library (`constraint_engine.slice_form_errors`), и этот скрипт — тем же правилом перед выдачей.

CLI:
    echo '{"analytical_verdicts": {...}}' | python3 reconcile_constraints.py --root <Claude-Memory> \
        --snapshot <Portfolio/snapshots/portfolio-YYYY-MM-DD.json> --today YYYY-MM-DD --pretty

Зависимости: stdlib (+ PyYAML для чтения conditions.yaml через conditions_merge).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

# Общие модули — канон в _shared-references/; в упакованном .skill — в своей scripts/ (pack.sh кладёт по импорту).
_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (_HERE, os.path.normpath(os.path.join(_HERE, "..", "..", "..", "_shared-references"))):
    if _cand not in sys.path:
        sys.path.insert(0, _cand)
import codelists  # noqa: E402
import conditions_merge as cm  # noqa: E402
import constraint_engine as ce  # noqa: E402

_VERDICT_DIR = codelists.map_("verdict_direction")
_PLAN_DIR = codelists.map_("user_plan_direction")
PLAN_BLOCKS_BUY = {p for p, d in _PLAN_DIR.items() if d != "up" and p != "BALANCE"}


def _dir(verdict) -> str | None:
    return _VERDICT_DIR.get(str(verdict or "").upper())


def _reason(row: dict) -> str:
    d = _dir(row.get("verdict_on_trigger"))
    return "sell_condition" if d == "down" else "pending_buy_condition" if d == "up" else "condition_hold"


def _until(row: dict):
    trig = row.get("trigger") or {}
    if trig.get("type") == "date" and isinstance(trig.get("value"), str):
        return trig["value"][:10]
    vu = row.get("valid_until")
    return vu[:10] if isinstance(vu, str) else None


def _summary(row: dict) -> str:
    text = (row.get("text") or row.get("note") or "").strip()
    return f"условие {row['id']}: {text}" if text else f"условие {row['id']}"


def slice_for_key(key: str, analytical: dict, rows: list[dict], plan_word, as_of: str) -> dict:
    """Срез и итоговый вердикт одной бумаги (правила 1–4 докстринга)."""
    av = (analytical or {}).get("verdict")
    conf = (analytical or {}).get("confidence")
    out: dict[str, Any] = {"advisor_verdict": av, "unconstrained_verdict": None,
                           "unconstrained_verdict_confidence": None, "advisor_verdict_constraints": [],
                           "user_constraints": [], "waits_owner": [], "diagnostics": []}
    final = av
    pinned = None
    for r in sorted((r for r in rows if r.get("key") == key and r.get("active")), key=lambda r: r["id"]):
        rec = {"derived": True, "as_of": as_of, "condition_id": r["id"], "reason": _reason(r),
               "status": r.get("status"), "until": _until(r), "summary": _summary(r)}
        if r.get("status") == "pending" and r.get("verdict_now"):
            out["user_constraints"].append(rec)
            out["advisor_verdict_constraints"].append(rec["summary"])
            if pinned is None:
                pinned = r["verdict_now"]
                final = pinned
            elif r["verdict_now"] != pinned:
                out["diagnostics"].append(f"conflicting_verdict_now:{r['id']}")
        elif r.get("status") == "fired" and r.get("waits_owner"):
            out["user_constraints"].append(rec)
            out["waits_owner"].append(r["id"])
    if isinstance(plan_word, str) and plan_word in PLAN_BLOCKS_BUY and _dir(av) == "up":
        word = codelists.ru("user_plan", plan_word)
        rec = {"derived": True, "as_of": as_of, "plan_field": "user_plan", "plan_value": plan_word,
               "reason": "user_plan", "until": None,
               "summary": f"план владельца «{word}» — докупка закрыта, вердикт {av} расходится с планом"}
        out["user_constraints"].append(rec)
        out["advisor_verdict_constraints"].append(rec["summary"])
    out["advisor_verdict"] = final
    if final != av:
        out["unconstrained_verdict"] = av
        out["unconstrained_verdict_confidence"] = conf
    errs = ce.slice_form_errors(out["user_constraints"])
    if errs:  # страховка: скрипт не выдаёт срез, который сам же не пропустит валидатор
        raise ValueError(f"{key}: срез не проходит форму: {errs}")
    out["markdown_block"] = _markdown(key, av, final, out)
    return out


def _markdown(key: str, av, final, out: dict) -> str:
    if not out["user_constraints"]:
        return ""
    lines = [f"**{key}** — ограничения на {out['user_constraints'][0]['as_of']}:"]
    for c in out["user_constraints"]:
        tail = f" (до {c['until']})" if c.get("until") else ""
        mark = " — сработало, ждёт владельца" if c.get("status") == "fired" else ""
        lines.append(f"- {c['summary']}{tail}{mark}")
    if final != av:
        lines.append(f"→ аналитический вердикт {av}, итоговый {final}.")
    return "\n".join(lines)


def build(payload: dict, rows: list[dict], plan: dict, as_of: str) -> dict:
    analytical = payload.get("analytical_verdicts") or {}
    res = {k: slice_for_key(k, v, rows, plan.get(k), as_of) for k, v in analytical.items()}
    return {
        "as_of": as_of,
        "tickers": res,
        "summary": {
            "total": len(res),
            "with_slice": sorted(k for k, r in res.items() if r["user_constraints"]),
            "verdict_changed": sorted(k for k, r in res.items() if r["unconstrained_verdict"] is not None),
            "waits_owner": sorted(k for k, r in res.items() if r["waits_owner"]),
        },
    }


def _rows_from_root(root: str, today: str) -> list[dict]:
    defs = os.path.join(root, "Portfolio", "conditions.yaml")
    state = os.path.join(root, "Portfolio", "conditions-state.json")
    if not os.path.isfile(defs):
        return []
    doc = cm.load_yaml(defs) or {}
    if doc.get("schema_version") != "conditions@2":
        raise ValueError(f"{defs}: формат {doc.get('schema_version')!r}, нужен conditions@2")
    st = {"events": []}
    if os.path.isfile(state):
        with open(state, encoding="utf-8") as f:
            st = json.load(f)
    return cm.merge(doc.get("conditions") or [], st, today)


def _plan_from_snapshot(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        snap = json.load(f)
    per = (snap.get("ie_actual") or {}).get("per_ticker") or {}
    return {k: v.get("user_plan") for k, v in per.items() if isinstance(v, dict)}


def _cli(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Срез ограничений бумаг для обзора недели из условий и плана (Шаг 9.5).")
    ap.add_argument("--input", "-i", help="JSON со analytical_verdicts (по умолчанию stdin)")
    ap.add_argument("--output", "-o")
    ap.add_argument("--root", help="корень Claude-Memory: условия conditions@2 + состояние")
    ap.add_argument("--snapshot", help="снапшот портфеля: план владельца ie_actual.per_ticker[*].user_plan")
    ap.add_argument("--today", required=True, help="дата обзора YYYY-MM-DD (as_of среза)")
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.input:
            with open(args.input, encoding="utf-8") as f:
                payload = json.load(f)
        else:
            payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"ERROR: вход не JSON ({exc.msg}, строка {exc.lineno}); ждём "
                         '{"analytical_verdicts": {KEY: {"verdict", "confidence"}}}\n')
        return 2
    rows = payload.get("conditions") or (_rows_from_root(args.root, args.today) if args.root else [])
    plan = payload.get("plan") or (_plan_from_snapshot(args.snapshot) if args.snapshot else {})
    out = build(payload, rows, plan, args.today)
    text = json.dumps(out, ensure_ascii=False, indent=2 if args.pretty else None)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
