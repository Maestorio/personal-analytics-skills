#!/usr/bin/env python3
"""Сверка двух реализаций одной арифметики: колонка «Сейчас» в «Долях и целях» вьюера.

Вьюер считает «купить/продать N лотов» в браузере (tools/assets/rebalance-engine.js,
runAuto) — чтобы свежие гейты и условия советника учитывались без перезагрузки
портфеля (решение владельца 2026-10-13, вариант А). Та же арифметика у советника —
gate_aware_sizing.py --auto (run_auto). Две копии расходятся молча, поэтому тест:

  1. прогоняет обе на одинаковых входах (синтетика на каждое правило + реальные снапшоты
     Synology с решениями и справочником бумаг временного корня шага 9 и условиями, мигрированными
     в conditions@2 во временную папку, если всё это есть) и требует совпадения категорий,
     направлений, лотов, причин блокировки текстом, «до чего стоит» и сумм до 2 копеек;
  2. входы гейта и условий (шаг 11 цикла машиночитаемости): решения decision@1, справочник бумаг
     security-attrs@1, строки обзоров, определения conditions@2 + состояние conditions-state@1 —
     обе стороны получают один JSON (даты строками, как требуют модули (а) и (б)); гейт считает
     модуль (б) last_word, условия — модуль (а) conditions_merge; файла гейтов нет;
  3. сверяет лимиты концентрации JS (CONC_LIMITS) с references/concentration-limits.yaml;
  4. проверяет сам себя: на заведомо изменённом правиле сверка обязана упасть;
  5. живые цены поверх снапшота (quotes@1, план tools/design-reference/live-prices-plan.md):
     apply_quotes (Python) против applyQuotes (JS) по всем изменённым полям, затем
     run_auto/runAuto на результате; на реальных снапшотах со сдвинутыми ценами; проверка P0
     (цены равны снапшотным → доли и строка класса не меняются); самопроверка «JS без
     пересчёта долей расходится».

Меняешь правило в одном месте — тест упадёт, пока не поменяешь во втором.
Нужен node (вьюерный движок — обычный JS); без node — честный пропуск, не зелёный.
Запуск: python3 tools/tests/test_rebalance_parity.py
"""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "skills/ru-portfolio-advisor/scripts"))
sys.path.insert(0, str(REPO / "_shared-references"))

import yaml  # noqa: E402
from gate_aware_sizing import run_auto, apply_quotes, load_gate_inputs, load_conditions_inputs  # noqa: E402
from concentration_limits import load_limits_config  # noqa: E402

ENGINE = REPO / "tools/assets/rebalance-engine.js"
LIMITS = REPO / "skills/ru-portfolio-advisor/references/concentration-limits.yaml"
CM_ROOT = Path.home() / "Library/CloudStorage/SynologyDrive-home/Claude-Memory"
MEM = CM_ROOT / "Portfolio"

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}  {detail}")


NODE = shutil.which("node")
if not NODE:
    print("rebalance_parity: пропуск — нет node (JS-движок вьюера нечем запустить)")
    sys.exit(0)

JS_RUNNER = r"""
const fs = require('fs');
const [engine, snapPath, giPath, condPath, optsJson] = process.argv.slice(1);
const E = require(engine);
const load = (p) => (!p || p === '-') ? null : JSON.parse(fs.readFileSync(p, 'utf8'));
const opts = JSON.parse(optsJson);
if (opts.limits === 'none') opts.limits = null;
const out = E.runAuto(JSON.parse(fs.readFileSync(snapPath, 'utf8')), load(giPath), load(condPath), opts);
process.stdout.write(JSON.stringify({ out, conc: E.CONC_LIMITS }));
"""


def _json_tmp(obj, name):
    """Вход гейта/условий в JSON-файл для node (None → «-»)."""
    if obj is None:
        return "-"
    p = tmp / f"{name}.json"
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return str(p)


def run_js(snap_path, gi, cond, opts=None):
    r = subprocess.run([NODE, "-e", JS_RUNNER, str(ENGINE), str(snap_path),
                        _json_tmp(gi, "gi"), _json_tmp(cond, "cond"), json.dumps(opts or {})],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:500])
    return json.loads(r.stdout)


JS_APPLY_RUNNER = r"""
const fs = require('fs');
const [engine, snapPath, quotesPath, giPath, condPath, optsJson] = process.argv.slice(1);
const E = require(engine);
const load = (p) => (!p || p === '-') ? null : JSON.parse(fs.readFileSync(p, 'utf8'));
const opts = JSON.parse(optsJson);
const snap0 = JSON.parse(fs.readFileSync(snapPath, 'utf8')), before = JSON.stringify(snap0);
const snap = E.applyQuotes(snap0, JSON.parse(fs.readFileSync(quotesPath, 'utf8')), opts);
const pure = JSON.stringify(snap0) === before;
const out = E.runAuto(snap, load(giPath), load(condPath), {});
process.stdout.write(JSON.stringify({ snap, out, pure }));
"""


def run_js_apply(snap_path, quotes_path, gi=None, cond=None, opts=None):
    r = subprocess.run([NODE, "-e", JS_APPLY_RUNNER, str(ENGINE), str(snap_path), str(quotes_path),
                        _json_tmp(gi, "gia"), _json_tmp(cond, "conda"), json.dumps(opts or {})],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:500])
    return json.loads(r.stdout)


def snap_diff(a, b, path=""):
    """Рекурсивное расхождение двух снапшотов: рубли ±0.02, real_share_pct ±1e-4, доли ±1e-9."""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{path}.{k}: нет с одной стороны")
            else:
                out += snap_diff(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: длина {len(a)} против {len(b)}")
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                out += snap_diff(x, y, f"{path}[{i}]")
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        key = path.rsplit(".", 1)[-1]
        tol = 1e-4 if key == "real_share_pct" else 1e-9 if key == "Доля нынешняя" else 0.02
        if abs(a - b) > tol:
            out.append(f"{path}: py={a!r} js={b!r}")
    elif a != b:
        out.append(f"{path}: py={a!r} js={b!r}")
    return out


def shifted_quotes(snap, factor=None, skip=None, lot_default=1):
    """quotes@1 из цен снапшота: ±7 % детерминированно (чётность суммы кодов тикера); skip(t) → тикера нет."""
    items = {}
    for h in snap["holdings"]:
        if h.get("asset_type") not in ("stock", "fund") or h.get("current_price_source") != "moex_iss":
            continue
        t, p = h["ticker"], h.get("current_price")
        if not p or (skip and skip(t)):
            continue
        k = factor if factor is not None else (1.07 if sum(map(ord, t)) % 2 == 0 else 0.93)
        items[t] = {"price": round(p * k, 2), "price_kind": "last", "lot_size": h.get("lot_size") or lot_default,
                    "board": "TQBR", "ts": "2026-10-14 11:00:00", "prev_close": p}
    return {"schema": "quotes@1", "fetched_at": "2026-10-14T11:15:00+03:00", "source": "moex_iss",
            "delayed_min": 15, "stale": False, "boards": {"TQBR": {"fetched_at": "2026-10-14T11:15:00+03:00", "stale": False}},
            "items": items}


def run_py(snap_path, gi, cond, hysteresis=1.0, quotes=None, ai_mode="on"):
    snap = json.loads(Path(snap_path).read_text(encoding="utf-8"))
    out = run_auto(snap, gi, cond, load_limits_config(str(LIMITS)), hysteresis, quotes=quotes, ai_mode=ai_mode)
    return json.loads(json.dumps(out, default=str))


NUM = ("current_rub", "target_rub", "delta_rub", "trade_rub", "price", "real_pct", "plan_pct")
EXACT = ("category", "direction", "lots", "lot_size", "reason", "unblock_by", "user_plan", "first_buy", "price_source", "lot_known", "frozen", "frozen_reason",
         "no_reversal", "opens_on", "opens_if_price_holds", "cascade")
TOP_NUM = ("nav_excl_iis", "class_plan_rub", "class_fact_rub", "base_rub", "blocked_gap_rub", "buy_rub", "sell_rub",
           "base_trim_rub", "gap_gated_rub", "gap_in_corridor_rub", "gap_unallocated_rub")


def diff(py, js):
    """Список расхождений (пусто — совпали)."""
    out = []
    for k in ("mode", "as_of", "base_source", "horizon", "cascade"):
        if py.get(k) != js.get(k):
            out.append(f"{k}: py={py.get(k)!r} js={js.get(k)!r}")
    for k in TOP_NUM:
        a, b = py.get(k), js.get(k)
        if (a is None) != (b is None) or (a is not None and abs(a - b) > 0.02):
            out.append(f"{k}: py={a!r} js={b!r}")
    pr, jr = {r["ticker"]: r for r in py["rows"]}, {r["ticker"]: r for r in js["rows"]}
    if list(pr) != list(jr):
        out.append(f"тикеры: py={list(pr)} js={list(jr)}")
    for t in pr:
        if t not in jr:
            continue
        for k in EXACT:
            if pr[t].get(k) != jr[t].get(k):
                out.append(f"{t}.{k}: py={pr[t].get(k)!r} js={jr[t].get(k)!r}")
        for k in NUM:
            a, b = pr[t].get(k), jr[t].get(k)
            if (a is None) != (b is None) or (a is not None and abs(a - b) > 0.02):
                out.append(f"{t}.{k}: py={a!r} js={b!r}")
    return out


# ─────────── синтетика: по случаю на каждое правило ───────────
def make_snapshot(rows, nav=10_000_000.0, plan=4_000_000.0, as_of="2026-10-13"):
    """rows: (ticker, value_rub, plan_pct|None, user_plan, extra) — real_share_pct считается от книги.
    Возраста листинга в снапшоте нет: IPO-пауза — только из справочника бумаг (модуль (б))."""
    book = sum(v for t, v, *_ in rows if t not in ("TMON",) and not (_[2] or {}).get("frozen"))
    holdings, per = [], {}
    for t, v, plan_pct, user_plan, extra in rows:
        extra = extra or {}
        h = {"ticker": t, "asset_type": "stock", "value_rub": v, "account": "main",
             "current_price": extra.get("price", 100.0), "lot_size": extra.get("lot", 1),
             "current_price_source": "cost_basis" if extra.get("frozen") else "moex_iss",
             "is_blocked": bool(extra.get("frozen"))}
        holdings.append(h)
        if t == "TMON" or extra.get("frozen"):
            continue
        per[t] = {"real_share_pct": round(v / book * 100, 4), "planned_share_pct": plan_pct,
                  "ie_new_pct": extra.get("ie"), "user_plan": user_plan}
    return {"as_of_date": as_of, "holdings": holdings, "ie_actual": {"per_ticker": per},
            "balance_summary": {"total_current_rub_excl_iis": nav, "goals_matrix": [
                {"Валюта": "RUB", "Бумага": "Акция", "Планы": plan, "Сейчас": book}]}}


def T(day, hm="10:00"):
    return f"{day}T{hm}:00+03:00"


def dec(key, day, verdict, review_by=None):
    """Решение decision@1 (форма — как пишет decision_write.py)."""
    return {"schema_version": "decision@1", "id": f"{day}T1000-{key}", "key": key, "verdict": verdict,
            "target_pct": None, "review_by": review_by, "note": "фикстура", "confidence": None,
            "conditions_created": [], "conditions_resolved": [],
            "source": {"kind": "backfill", "doc": None, "mode_codes": [], "stress_id": None},
            "author": "owner", "recorded_at": T(day)}


def flagged(day):
    """Строка обзора с флагом «нужен разбор» (flags.gate_review_required)."""
    return [{"review_date": day, "recorded_at": T(day, "00:00"), "advisor_verdict": "HOLD",
             "advisor_verdict_confidence": 0.5, "advisor_verdict_basis": "флаг обзора", "gate_review_required": True,
             "doc": f"weekly-review-stock-{day}.yaml"}]


def ipo(listed):
    return {"ticker_class": "ipo", "listed_at": listed, "note": None, "updated_at": T("2026-10-31"), "updated_by": "owner"}


def gate_inputs(decisions=(), reviews=None, attrs=None, **trades):
    """trades — входы сделок и правок плана (last_buy_at, last_sell_at, buys_at, plan_changed_at): пауза докупки
    модуля (б) — от первой покупки после решения, неразворот «Сейчас» (§10.6)."""
    return {"decisions": list(decisions), "reviews": reviews or {},
            "security_attrs": {"schema_version": "security-attrs@1", "by_key": attrs or {}}, **trades}


def cdef(cid, key, trigger, on=None, while_=None, not_before=None, valid_until=None):
    """Определение условия conditions@2 (даты строками)."""
    d = {"id": cid, "version": 1, "key": key, "kind": "trade", "trigger": trigger,
         "on_trigger": {"action": "set_verdict", "verdict": on, "text": "фикстура"},
         "while_pending": {"verdict": while_} if while_ else None,
         "created_at": T("2026-09-01"), "created_by": "owner"}
    if not_before:
        d["not_before"] = not_before
    if valid_until:
        d["valid_until"] = valid_until
    return d


def ev(cid, event, at, **data):
    e = {"condition_id": cid, "event": event, "at": at, "by": "owner"}
    if data:
        e["data"] = data
    return e


def conds(defs, events=()):
    return {"defs": list(defs), "state": {"schema_version": "conditions-state@1", "events": list(events)}}


GATES = gate_inputs(
    [dec("GAZP", "2026-10-01", "WATCH", "2026-12-01"),   # на пересмотре со сроком → «до 2026-12-01»
     dec("LKOH", "2026-10-01", "HOLD", "2026-12-01")],
    attrs={"NEWCO": ipo("2025-10-13")})                  # IPO: ровно 4 кв. к as_of 2026-10-13
CONDS = conds(
    [cdef("condb-price", "CONDB", {"type": "price_below", "value": 44.57}, on="BUY"),
     cdef("moex-date", "MOEX", {"type": "date", "value": "2026-10-01"}, on="BUY")],
    [ev("moex-date", "fired", T("2026-10-01", "09:00")), ev("moex-date", "done", T("2026-10-02", "09:00"))])

BASE_ROWS = [
    ("SBER", 500_000, 18.0, "BUY", None),            # группа SBER+SBERP 23% > лимита 20% → докупка заблокирована
    ("SBERP", 200_000, 7.0, "BUY", None),
    ("GAZP", 300_000, 12.0, "BUY", None),            # решение WATCH со сроком → gate:reviewed_under_review
    ("LKOH", 400_000, 11.0, "KEEP", None),            # перевес у KEEP — стоит
    ("MOEX", 300_000, 10.0, "BUY", {"price": 210.5, "lot": 10}),  # условие сработало и закрыто «сделал» — не блокирует
    ("YDEX", 250_000, 10.0, "BUY", {"price": 4000.0, "lot": None}),  # докупка без лотности → лотов нет
    ("OZON", 350_000, 9.0, "BALANCE", {"price": 4500.0, "lot": 1}),   # перевес BALANCE > 1 п.п. → срез, лоты вверх
    ("NEWCO", 150_000, 6.0, "BUY", None),            # IPO-пауза по справочнику бумаг
    ("WAITR", 100_000, 5.0, "WAIT", None),            # план WAIT
    ("CONDB", 200_000, 8.0, "BUY", None),            # ожидающее BUY-условие с ценой
    ("NOPLAN", 150_000, None, None, {"ie": 5.0}),     # нет моего плана (IE не участвует)
    ("CHEAP", 100_000, 12.0, "BUY", {"price": 120.0, "lot": 10}),     # докупка, лоты вниз
    ("FROZEN", 90_000, None, None, {"frozen": True}),  # заморожена (US) — вне книги
    ("TMON", 100_000, None, None, None),              # фонд денежного рынка — вне книги
]

tmp = Path(tempfile.mkdtemp(prefix="rebal-parity-"))

CASES = {
    "все правила (гейты, условия, IPO, WAIT, лимит эмитента, срез, лоты)": (make_snapshot(BASE_ROWS), True),
    "гейтов нет — непрерывная база": (make_snapshot([r for r in BASE_ROWS if r[0] in ("LKOH", "YDEX", "CHEAP", "MOEX", "OZON")]), False),
    "перевес BALANCE в коридоре — без среза": (make_snapshot([("OZON", 310_000, 30.0, "BALANCE", None), ("YDEX", 690_000, 70.0, "BUY", None)]), False),
    # семь бумаг с планом 14,25% (ниже лимита эмитента 15%) и недобором > гистерезиса, открыто 99,75% класса → база не считается
    "вырожденная база (открыто ≈ весь класс)": (make_snapshot([(f"S{i}", 90_000, 14.25, "BUY", None) for i in range(7)] + [("C", 5_000, 0.25, None, None), ("BIGD", 250_000, 28.24, None, None)]), True),
}

print("== 1. Совпадение Python (gate_aware_sizing --auto) и JS (rebalance-engine.js) ==")
for name, (snap, with_inputs) in CASES.items():
    sp = tmp / "snap.json"
    sp.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    gr, cd = (GATES, CONDS) if with_inputs else (None, None)
    py = run_py(sp, gr, cd)
    js = run_js(sp, gr, cd)["out"]
    d = diff(py, js)
    check(f"{name}: {len(py['rows'])} бумаг, база {py['base_source']}", not d, "; ".join(d[:6]))

# сами случаи должны покрывать то, что заявлено (иначе «совпало» ничего не значит)
sp = tmp / "snap.json"
sp.write_text(json.dumps(CASES[next(iter(CASES))][0], ensure_ascii=False), encoding="utf-8")
py = run_py(sp, GATES, CONDS)
by = {r["ticker"]: r for r in py["rows"]}
check("покрытие: лимит эмитента блокирует докупку SBER", (by["SBER"]["reason"] or "").startswith("concentration_breach"))
check("покрытие: решение «на пересмотре» со сроком → gate:reviewed_under_review «до 2026-12-01»",
      by["GAZP"]["reason"] == "gate:reviewed_under_review" and by["GAZP"]["unblock_by"] == "2026-12-01", by["GAZP"])
check("покрытие: условие с ценой → «цена ≤ 44.57 ₽»", by["CONDB"]["unblock_by"] == "цена ≤ 44.57 ₽", by["CONDB"])
check("покрытие: IPO-пауза по справочнику (ipo_gate:4q, до 2027-10-13) и WAIT блокируют",
      by["NEWCO"]["category"] == "blocked" and by["NEWCO"]["reason"] == "ipo_gate:4q" and by["NEWCO"]["unblock_by"] == "2027-10-13"
      and by["WAITR"]["category"] == "blocked", by["NEWCO"])
check("покрытие: условие сработало и закрыто «сделал» — докупку не держит (не blocked, причины нет)",
      by["MOEX"]["reason"] is None and by["MOEX"]["category"] != "blocked", by["MOEX"])
check("покрытие: срез BALANCE с лотами вверх", by["OZON"]["direction"] == "trim" and (by["OZON"]["lots"] or 0) > 0, by["OZON"])
check("покрытие: докупка с лотами вниз и без лотности", by["CHEAP"]["direction"] == "buy" and by["CHEAP"]["lots"] is not None and by["YDEX"]["lots"] is None)
check("покрытие: перевес KEEP и бумага без плана — без сигнала", by["LKOH"]["category"] == "dormant" and by["NOPLAN"]["category"] == "dormant")
check("покрытие: замороженная бумага и фонд денежного рынка — вне книги", "FROZEN" not in by and "TMON" not in by)
sp.write_text(json.dumps(CASES["вырожденная база (открыто ≈ весь класс)"][0], ensure_ascii=False), encoding="utf-8")
check("покрытие: вырожденная база — числа не досчитываются (ручная проверка)", run_py(sp, None, None)["base_source"] == "manual_check_required")
sp.write_text(json.dumps(CASES["гейтов нет — непрерывная база"][0], ensure_ascii=False), encoding="utf-8")
_ng = run_py(sp, None, None)
check("покрытие: без гейтов — та же неподвижная точка (непрерывная база §10.6), не план класса",
      _ng["base_source"] in ("fixed_point", "fixed_point_capped") and _ng["gap_gated_rub"] == 0, (_ng["base_source"], _ng["gap_gated_rub"]))

# 2026-10-26: докупка с гистерезисом + условия с продажей / «держать» (sell_condition, condition_hold, окно);
# шаг 11: строки модуля (а) — сработавшее «ждёт владельца» держит докупку, закрытое «сделал» — нет
AUTO_CONDS = conds(
    [cdef("sellc-gate", "SELLC", {"type": "price_above", "value": 1200}, on="TRIM", while_="HOLD"),
     cdef("holdc-review", "HOLDC", {"type": "date", "value": "2026-11-30"}, on="HOLD", while_="HOLD"),
     cdef("holdexp", "HOLDEXP", {"type": "date", "value": "2026-11-30"}, on="HOLD", while_="HOLD", valid_until="2026-10-20"),
     cdef("holdfut", "HOLDFUT", {"type": "date", "value": "2026-11-30"}, on="HOLD", while_="HOLD", not_before="2026-11-01"),
     cdef("holdwin", "HOLDWIN", {"type": "date", "value": "2026-11-30"}, on="HOLD", while_="HOLD",
          not_before="2026-10-01", valid_until="2026-10-31"),
     cdef("holdfired", "HOLDFIRED", {"type": "price_below", "value": 90.5}, on="HOLD", while_="HOLD"),
     cdef("holddone", "HOLDDONE", {"type": "price_below", "value": 90.5}, on="HOLD", while_="HOLD"),
     cdef("holddef", "HOLDDEF", {"type": "price_below", "value": 90.5}, on="HOLD", while_="HOLD"),
     cdef("buyc-buy", "BUYC", {"type": "date", "value": "2026-10-31"}, on="BUY", while_="HOLD"),
     cdef("holdrep", "HOLDREP", {"type": "report_published", "value": "МСФО за 9М", "window_end": "2026-11-06"},
          on="HOLD", while_="HOLD")],
    [ev("holdfired", "fired", T("2026-10-20")),
     ev("holddone", "fired", T("2026-10-20")), ev("holddone", "done", T("2026-10-21")),
     ev("holddef", "fired", T("2026-10-20")), ev("holddef", "owner_mark", T("2026-10-21"), mark="deferred", until="2026-11-05")])
# (тикер, стоимость при книге 1 000 000 → реальная доля = стоимость/10 000 %, план = реальная + недобор)
AUTO_ROWS = [
    ("BIGGAP", 50_000, 8.0, "BUY", {"price": 100.0}),      # 5,0 → 8,0: недобор 3 п.п. > порога → докупка
    ("SMALL", 100_000, 10.5, "BUY", None),                  # недобор 0,5 → в коридоре
    ("SELLC", 50_000, 7.0, "BUY", None),                    # недобор 1 п.п.+ и sell-условие → sell_condition (старше порога)
    ("HOLDC", 50_000, 7.0, "BUY", None),                    # condition_hold
    ("HOLDEXP", 50_000, 7.0, "BUY", None),                  # окно истекло → докупка
    ("HOLDFUT", 50_000, 7.0, "BUY", None),                  # окно не началось → докупка
    ("HOLDWIN", 50_000, 7.0, "BUY", None),                  # сегодня 26.10 внутри окна 01–31.10 → блок
    ("HOLDFIRED", 50_000, 7.0, "BUY", None),                # сработавшее, ждёт владельца → блок «после отметки владельца»
    ("HOLDDONE", 50_000, 7.0, "BUY", None),                 # сработавшее и закрытое «сделал» → докупка
    ("HOLDDEF", 50_000, 7.0, "BUY", None),                  # сработавшее, отложено до 05.11 → блок до даты отсрочки
    ("BUYC", 50_000, 7.0, "BUY", None),                     # BUY-условие → pending_buy_condition
    ("HOLDREP", 50_000, 7.0, "BUY", None),                  # ждём отчётность → condition_hold до конца окна (window_end)
    ("REST", 350_000, 35.0, "KEEP", None),                   # на плане
]
snap_auto = make_snapshot(AUTO_ROWS, plan=1_000_000.0, as_of="2026-10-26")
sp_auto = tmp / "snap-auto.json"
sp_auto.write_text(json.dumps(snap_auto, ensure_ascii=False), encoding="utf-8")
for hy in (1.0, 0.3):
    py = run_py(sp_auto, None, AUTO_CONDS, hy)
    js = run_js(sp_auto, None, AUTO_CONDS, {"hysteresisPp": hy})["out"]
    check(f"гистерезис на докупку и условия (порог {hy} п.п.): {len(py['rows'])} бумаг, купить {py['buy_rub']}",
          not diff(py, js), "; ".join(diff(py, js)[:6]))
py = run_py(sp_auto, None, AUTO_CONDS)
by = {r["ticker"]: r for r in py["rows"]}
check("покрытие: недобор > порога — докупка", by["BIGGAP"]["direction"] == "buy" and by["BIGGAP"]["category"] == "open", by["BIGGAP"])
# SMALL в коридоре по сегодняшней доле (10,0 против 10,5), но докупки соседей растят книгу — после исполнения его доля
# уходит ниже коридора, и каскад (§10.6 п.1) докупает его в том же расчёте
check("покрытие: недобор ниже порога сегодня, но ниже коридора после докупок соседей — каскад докупает (cascade)",
      by["SMALL"]["direction"] == "buy" and by["SMALL"]["cascade"] is True and py["cascade"]["converged"], by["SMALL"])
check("покрытие: условие с продажей — sell_condition:<id>", by["SELLC"]["reason"] == "sell_condition:sellc-gate" and by["SELLC"]["direction"] is None, by["SELLC"])
check("покрытие: условие «держать» — condition_hold:<id>", by["HOLDC"]["reason"] == "condition_hold:holdc-review", by["HOLDC"])
check("покрытие: окно истекло / не началось / сработавшее и закрытое — не закрывают докупку",
      all(by[t]["direction"] == "buy" for t in ("HOLDEXP", "HOLDFUT", "HOLDDONE")), [by[t]["reason"] for t in ("HOLDEXP", "HOLDFUT", "HOLDDONE")])
check("покрытие: сработавшее «ждёт владельца» держит докупку — «после отметки владельца»; отложенное — до даты отсрочки",
      (by["HOLDFIRED"]["reason"], by["HOLDFIRED"]["unblock_by"], by["HOLDDEF"]["reason"], by["HOLDDEF"]["unblock_by"])
      == ("condition_hold:holdfired", "после отметки владельца", "condition_hold:holddef", "2026-11-05"), (by["HOLDFIRED"], by["HOLDDEF"]))
check("покрытие: условие внутри окна закрывает; BUY-условие — прежняя причина",
      by["HOLDWIN"]["reason"] == "condition_hold:holdwin" and by["BUYC"]["reason"] == "pending_buy_condition", (by["HOLDWIN"], by["BUYC"]))
check("покрытие: условие «ждём отчётность» — снимется к концу окна window_end",
      (by["HOLDREP"]["reason"], by["HOLDREP"]["unblock_by"]) == ("condition_hold:holdrep", "2026-11-06"), by["HOLDREP"])
py03 = run_py(sp_auto, None, AUTO_CONDS, 0.3)
check("покрытие: порог 0,3 п.п. возвращает докупку по SMALL", {r["ticker"]: r for r in py03["rows"]}["SMALL"]["direction"] == "buy")

# 2026-10-28: слова плана владельца (user_plan) — таблица семантики «Сейчас»; полный набор причин блокировки
WORDS_GATES = gate_inputs([dec("AGEP", "2026-06-01", "HOLD", "2026-09-01")], reviews={"WGATE": flagged("2026-10-23")})
WORDS_CONDS = conds(
    [cdef("wh-sellgate", "WHOLD", {"type": "date", "value": "2026-11-30"}, on="HOLD", while_="HOLD"),
     cdef("wk-hold", "WKEEP2", {"type": "date", "value": "2026-11-30"}, on="HOLD", while_="HOLD")])
WORDS_ROWS = [
    ("KUNDER", 50_000, 8.0, "KEEP", {"price": 100.0}),     # KEEP, недобор 3 п.п. → ничего (dormant user_plan:KEEP)
    ("KOVER", 100_000, 5.0, "KEEP", None),                 # KEEP, перевес → ничего
    ("BUNDER", 50_000, 8.0, "BUY", {"price": 100.0}),      # BUY, недобор → докупка
    ("BOVER", 100_000, 5.0, "BUY", None),                  # BUY, перевес → ничего
    ("WUNDER", 50_000, 8.0, "WAIT", None),                 # WAIT, недобор → блокировка user_plan:WAIT
    ("SOVER", 120_000, 5.0, "SELL", {"price": 130.0, "lot": 10}),  # SELL, перевес → срез до нуля, лоты вверх
    ("SZERO", 90_000, 0.0, "SELL", {"price": 100.0, "lot": 10}),   # SELL, план 0 → срез до нуля
    ("SNULL", 80_000, None, "SELL", {"price": 100.0, "lot": 10}),  # SELL, плана нет → срез до нуля (не отбрасывается)
    ("SSMALL", 20_000, 1.5, "SELL", {"price": 100.0, "lot": 10}), # SELL, перевес 0,05 п.п. (в коридоре) → всё равно срез
    ("SUNDER", 50_000, 8.0, "SELL", {"price": 100.0, "lot": 10}),  # SELL, недобор → всё равно срез до нуля (3.94)
    ("WHOLD", 50_000, 8.0, "WAIT", None),                  # WAIT + condition_hold → обе причины
    ("WGATE", 50_000, 8.0, "WAIT", None),                  # WAIT + флаг обзора новее решения → gate:review_needed
    ("WKEEP2", 50_000, 8.0, "KEEP", None),                 # KEEP + condition_hold → только условие
    ("AGEP", 50_000, 8.0, "BUY", None),                    # срок решения истёк с недобором → blocked до разбора
    ("REST", 400_000, 50.0, "BUY", None),
]
snap_w = make_snapshot(WORDS_ROWS, plan=1_000_000.0, as_of="2026-10-28")
sp_w = tmp / "snap-words.json"
sp_w.write_text(json.dumps(snap_w, ensure_ascii=False), encoding="utf-8")
py_w = run_py(sp_w, WORDS_GATES, WORDS_CONDS)
js_w = run_js(sp_w, WORDS_GATES, WORDS_CONDS)["out"]
check(f"слова плана и полные причины: {len(py_w['rows'])} бумаг, продать {py_w['sell_rub']}, купить {py_w['buy_rub']}",
      not diff(py_w, js_w), "; ".join(diff(py_w, js_w)[:6]))
bw = {r["ticker"]: r for r in py_w["rows"]}
check("слова: KEEP при недоборе — dormant, не open", bw["KUNDER"]["category"] == "dormant" and bw["KUNDER"]["direction"] is None and bw["KUNDER"]["reason"] == "user_plan:KEEP", bw["KUNDER"])
check("слова: KEEP при перевесе — ничего", bw["KOVER"]["category"] == "dormant" and bw["KOVER"]["direction"] is None, bw["KOVER"])
check("слова: BUY при недоборе — докупка (open)", bw["BUNDER"]["category"] == "open" and bw["BUNDER"]["direction"] == "buy", bw["BUNDER"])
check("слова: BUY при перевесе — ничего", bw["BOVER"]["category"] == "dormant" and bw["BOVER"]["direction"] is None, bw["BOVER"])
check("слова: WAIT при недоборе — блокировка user_plan:WAIT", bw["WUNDER"]["category"] == "blocked" and bw["WUNDER"]["reason"] == "user_plan:WAIT", bw["WUNDER"])
for t, qty_lots in (("SOVER", -(-120_000 // 1300)), ("SZERO", 90), ("SNULL", 80), ("SSMALL", 20)):
    r = bw[t]
    check(f"слова: SELL {t} — срез до нуля, лотов ceil(qty/lot) = {qty_lots}",
          r["category"] == "rebalancing" and r["direction"] == "trim" and r["target_rub"] == 0 and r["delta_rub"] == -r["current_rub"] and r["lots"] == qty_lots, r)
check("слова: SELL при недоборе — всё равно срез до нуля (3.94)", bw["SUNDER"]["category"] == "rebalancing" and bw["SUNDER"]["direction"] == "trim" and bw["SUNDER"]["target_rub"] == 0 and bw["SUNDER"]["lots"] == 50, bw["SUNDER"])
check("полные причины: WAIT + «держать» — оба кода, условие раньше плана, дата условия",
      bw["WHOLD"]["reason"] == "condition_hold:wh-sellgate; user_plan:WAIT" and bw["WHOLD"]["unblock_by"] == "2026-11-30", bw["WHOLD"])
check("полные причины: WAIT + флаг обзора новее решения — гейт раньше плана, «после разбора бумаги»",
      bw["WGATE"]["reason"] == "gate:review_needed; user_plan:WAIT" and bw["WGATE"]["unblock_by"] == "после разбора бумаги", bw["WGATE"])
check("срок решения истёк (review_aging) с недобором — blocked, gate:review_aging, «после разбора бумаги»",
      bw["AGEP"]["category"] == "blocked" and bw["AGEP"]["reason"] == "gate:review_aging" and bw["AGEP"]["unblock_by"] == "после разбора бумаги", bw["AGEP"])
check("полные причины: KEEP + «держать» — только условие", bw["WKEEP2"]["reason"] == "condition_hold:wk-hold", bw["WKEEP2"])

# шаг 11: «пять бумаг с разными причинами — текст совпадает у JS и Python» (decision.md §4 строка 11)
RS_GATES = gate_inputs(
    [dec("R_AGE", "2026-06-01", "HOLD", "2026-09-01"), dec("R_UNDER", "2026-10-01", "WATCH", "2026-12-15"),
     dec("R_COOL", "2026-10-20", "ADD", "2026-12-15"), dec("R_MIX", "2026-10-25", "BUY", "2026-12-15"),
     dec("R_KEEP", "2026-09-01", "HOLD", "2026-12-15")],
    attrs={"R_IPO": ipo("2025-04-28"), "R_MIX": ipo("2026-04-01"), "R_KEEP": ipo("2019-01-10")},
    # пауза докупки — от первой покупки после решения BUY/ADD (правило 7 модуля (б), 11.11): покупки в дни решений
    last_buy_at={"R_COOL": T("2026-10-20"), "R_MIX": T("2026-10-25")})
RS_CONDS = conds(
    [cdef("r-waitc", "R_WAITC", {"type": "price_below", "value": 99.5}, on="BUY", while_="HOLD"),
     cdef("r-sell", "R_SELL", {"type": "price_above", "value": 1200}, on="TRIM", while_="HOLD")],
    [ev("r-waitc", "fired", T("2026-10-27"))])
RS_EXPECT = {   # тикер: (причина, когда снимется)
    "R_AGE": ("gate:review_aging", "после разбора бумаги"),
    "R_UNDER": ("gate:reviewed_under_review", "2026-12-15"),
    "R_IPO": ("ipo_gate:6q", "2027-04-28"),
    "R_COOL": ("add_cooldown:2026-11-10", "2026-11-10"),
    "R_WAITC": ("pending_buy_condition", "после отметки владельца"),
    "R_SELL": ("sell_condition:r-sell", "цена ≥ 1200 ₽"),
    "R_MIX": ("ipo_gate:2q; add_cooldown:2026-11-15; user_plan:WAIT", "2028-04-01"),
    "R_KEEP": (None, None),
}
RS_ROWS = [(t, 50_000, 8.0, "WAIT" if t == "R_MIX" else "BUY", None) for t in RS_EXPECT] + [("REST", 350_000, 36.0, "KEEP", None)]
sp_r = tmp / "snap-reasons.json"
sp_r.write_text(json.dumps(make_snapshot(RS_ROWS, plan=1_000_000.0, as_of="2026-10-28"), ensure_ascii=False), encoding="utf-8")
py_r, js_r = run_py(sp_r, RS_GATES, RS_CONDS), run_js(sp_r, RS_GATES, RS_CONDS)["out"]
check(f"разные причины блокировки: Python = JS ({len(py_r['rows'])} бумаг)", not diff(py_r, js_r), "; ".join(diff(py_r, js_r)[:6]))
br, bj = {r["ticker"]: r for r in py_r["rows"]}, {r["ticker"]: r for r in js_r["rows"]}
for t, (rs, ub) in RS_EXPECT.items():
    check(f"причина {t}: «{rs}» · снимется «{ub}» — текст у Python и JS",
          (br[t]["reason"], br[t]["unblock_by"]) == (rs, ub) == (bj[t]["reason"], bj[t]["unblock_by"]),
          (br[t]["reason"], br[t]["unblock_by"], bj[t]["reason"], bj[t]["unblock_by"]))
check("разные причины: каждая заблокированная бумага — blocked и без сделки, R_KEEP (старое IPO, без паузы) — open",
      all(br[t]["category"] == "blocked" and br[t]["direction"] is None for t in RS_EXPECT if t != "R_KEEP")
      and br["R_KEEP"]["category"] == "open" and br["R_KEEP"]["reason"] is None, br["R_KEEP"])

# режим «без ИИ» (решение 11.11): блокируют те же статусы и причины, что при ИИ; блок снимает решение владельца, не разбор
py_o, js_o = (run_py(sp_r, RS_GATES, RS_CONDS, ai_mode="off"),
              run_js(sp_r, RS_GATES, RS_CONDS, {"aiMode": "off"})["out"])
check(f"без ИИ: Python = JS ({len(py_o['rows'])} бумаг)", not diff(py_o, js_o), "; ".join(diff(py_o, js_o)[:6]))
bo = {r["ticker"]: r for r in py_o["rows"]}
for t in ("R_AGE", "R_UNDER"):
    check(f"без ИИ: {t} (истёкший срок / «наблюдать») блокирует, как при ИИ",
          bo[t]["category"] == "blocked" and bo[t]["direction"] is None, bo[t])
for t in RS_EXPECT:
    if t == "R_KEEP":
        continue
    check(f"без ИИ: {t} блокирует, как при ИИ: «{RS_EXPECT[t][0]}» · «{RS_EXPECT[t][1]}»",
          (bo[t]["category"], bo[t]["reason"], bo[t]["unblock_by"]) == ("blocked", RS_EXPECT[t][0], RS_EXPECT[t][1]), bo[t])
check("без ИИ: R_KEEP (старое IPO, нет причин) открыта; строки off = строки on по категории и причине у всех бумаг",
      bo["R_KEEP"]["category"] == "open" and bo["R_KEEP"]["reason"] is None
      and all((bo[t]["category"], bo[t]["reason"]) == (br[t]["category"], br[t]["reason"]) for t in bo), bo["R_KEEP"])
# лоты в «Сейчас»: истёкший срок, пауза докупки и IPO-пауза — без лотов в обоих режимах
LT_GATES = gate_inputs([dec("L_AGE", "2026-06-01", "HOLD", "2026-09-01"), dec("L_COOL", "2026-10-20", "ADD", "2026-12-15")],
                       attrs={"L_IPO": ipo("2025-04-28")}, last_buy_at={"L_COOL": T("2026-10-21")})
LT_ROWS = [(t, 50_000, 14.0, "BUY", {"price": 100.0, "lot": 10}) for t in ("L_AGE", "L_COOL", "L_IPO")] + [("REST", 450_000, 75.0, "KEEP", None)]
sp_l = tmp / "snap-lots.json"
sp_l.write_text(json.dumps(make_snapshot(LT_ROWS, plan=1_000_000.0, as_of="2026-10-28"), ensure_ascii=False), encoding="utf-8")
lt = {m: ({r["ticker"]: r for r in run_py(sp_l, LT_GATES, None, ai_mode=m)["rows"]},
          {r["ticker"]: r for r in run_js(sp_l, LT_GATES, None, {"aiMode": m})["out"]["rows"]}) for m in ("on", "off")}
for m in ("on", "off"):
    check(f"лоты, {m}: Python = JS", not diff(run_py(sp_l, LT_GATES, None, ai_mode=m), run_js(sp_l, LT_GATES, None, {"aiMode": m})["out"]))
for side, nm in ((0, "Python"), (1, "JS")):
    check(f"лоты ({nm}): истёкший срок — blocked без лотов в обоих режимах (снимает разбор при ИИ, решение владельца без ИИ)",
          all(lt[m][side]["L_AGE"]["category"] == "blocked" and not lt[m][side]["L_AGE"]["lots"]
              and lt[m][side]["L_AGE"]["direction"] is None for m in ("on", "off")), (lt["on"][side]["L_AGE"], lt["off"][side]["L_AGE"]))
    check(f"лоты ({nm}): пауза докупки и IPO-пауза блокируют в обоих режимах, без лотов",
          all(lt[m][side][t]["category"] == "blocked" and not lt[m][side][t]["lots"] and lt[m][side][t]["direction"] is None
              for m in ("on", "off") for t in ("L_COOL", "L_IPO")), [lt[m][side][t]["reason"] for m in ("on", "off") for t in ("L_COOL", "L_IPO")])
check("при ИИ (по умолчанию и явное on) R_AGE и R_UNDER по-прежнему blocked",
      br["R_AGE"]["category"] == br["R_UNDER"]["category"] == "blocked"
      and run_py(sp_r, RS_GATES, RS_CONDS, ai_mode="on") == py_r
      and run_js(sp_r, RS_GATES, RS_CONDS, {"aiMode": "on"})["out"] == js_r)

# «держать» (KEEP) без операции: рубли в F, вес не в S (решение владельца 11.11; правило 28.10 «плановым весом» отменено)
BASE_KEEP_ROWS = [(f"K{i}", 100_000, 12.0, "KEEP", {"price": 100.0}) for i in range(1, 7)] + [("BAL", 50_000, 14.0, "BALANCE", {"price": 100.0})]
for label, rows_k, exp_src, exp_base in (
        # непрерывная база (§10.6): без блокировок база — та же неподвижная точка, «держать» в F, не план класса
        ("книга из «держать» + одна «привести к плану» с недобором", BASE_KEEP_ROWS, "fixed_point", 600_000.0 / (1 - 0.14)),
        ("то же + одна «ждать» с недобором", BASE_KEEP_ROWS + [("W", 100_000, 14.0, "WAIT", None)], "fixed_point", 700_000.0 / (1 - 0.14))):
    sp_k = tmp / "snap-keep.json"
    sp_k.write_text(json.dumps(make_snapshot(rows_k, plan=1_000_000.0, as_of="2026-10-28"), ensure_ascii=False), encoding="utf-8")
    py_k, js_k = run_py(sp_k, None, None), run_js(sp_k, None, None)["out"]
    check(f"база и «держать»: {label}", not diff(py_k, js_k), "; ".join(diff(py_k, js_k)[:6]))
    bk = {r["ticker"]: r for r in py_k["rows"]}
    check(f"база и «держать»: {label} → {exp_src}, база {exp_base:.0f}, цель BAL = 0,14 × база",
          py_k["base_source"] == exp_src and abs(py_k["base_rub"] - exp_base) < 1 and abs(bk["BAL"]["target_rub"] - 0.14 * exp_base) < 1
          and bk["K1"]["direction"] is None and bk["K2"]["direction"] is None and bk["K1"]["target_rub"] is None, (py_k["base_source"], py_k["base_rub"]))

# инвариант базы (11.11): «держать» (перевес и недобор) и перевес BUY — в F своими рублями; книга после сделок = база,
# доля торгуемой бумаги после сделок = плану (Python = JS)
INV_ROWS = [("W", 100_000, 20.0, "WAIT", None), ("K1", 125_000, 10.0, "KEEP", {"price": 100.0}), ("K2", 75_000, 10.0, "KEEP", {"price": 100.0}),
            ("R", 460_000, 30.0, "BUY", {"price": 100.0}), ("B", 140_000, 10.0, "BALANCE", {"price": 100.0}), ("O", 100_000, 20.0, "BUY", {"price": 100.0})]
sp_i = tmp / "snap-inv.json"
sp_i.write_text(json.dumps(make_snapshot(INV_ROWS, plan=1_500_000.0, as_of="2026-10-28"), ensure_ascii=False), encoding="utf-8")
py_i, js_i = run_py(sp_i, None, None), run_js(sp_i, None, None)["out"]
check("инвариант базы: Python = JS", not diff(py_i, js_i), "; ".join(diff(py_i, js_i)[:6]))
for nm, out in (("Python", py_i), ("JS", js_i)):
    ri = {r["ticker"]: r for r in out["rows"]}
    traded = [t for t, r in ri.items() if r["target_rub"] is not None]
    fixed = sum(r["current_rub"] for t, r in ri.items() if t not in traded)
    check(f"инвариант базы ({nm}): база = Σ текущих неторгуемых + Σ целей торгуемых; неторгуемых 760 000",
          sorted(traded) == ["B", "O"] and fixed == 760_000 and abs(out["base_rub"] - 760_000 / 0.7) < 1
          and abs(out["base_rub"] - fixed - sum(ri[t]["target_rub"] for t in traded)) < 1, (traded, fixed, out["base_rub"]))
    after = {t: r["current_rub"] + (r["trade_rub"] or 0) * (1 if r["direction"] == "buy" else -1 if r["direction"] == "trim" else 0) for t, r in ri.items()}
    book_after = sum(after.values())
    check(f"инвариант базы ({nm}): доля B и O после идеального исполнения = плану ±0,01 п.п.",
          abs(after["B"] / book_after * 100 - 10.0) < 0.01 and abs(after["O"] / book_after * 100 - 20.0) < 0.01, (after["B"] / book_after, after["O"] / book_after))

# предохранитель базы (3.92.0): замороженные выше своей доли не поднимают базу выше плана класса
CAP_ROWS = [("W1", 600_000, 49.0, "WAIT", None), ("W2", 600_000, 49.0, "WAIT", None), ("O1", 50_000, 12.0, "BUY", {"price": 100.0})]
sp_c = tmp / "snap-cap.json"
sp_c.write_text(json.dumps(make_snapshot(CAP_ROWS, plan=1_000_000.0, as_of="2026-10-28"), ensure_ascii=False), encoding="utf-8")
py_c, js_c = run_py(sp_c, None, None), run_js(sp_c, None, None)["out"]
check("предохранитель базы: Python = JS", not diff(py_c, js_c), "; ".join(diff(py_c, js_c)[:6]))
bc = {r["ticker"]: r for r in py_c["rows"]}
check("предохранитель базы: F выше доли → база = план класса, fixed_point_capped, разрыв 0, цель O1 = 0,12 × план",
      py_c["base_source"] == "fixed_point_capped" and abs(py_c["base_rub"] - 1_000_000.0) < 1 and abs(py_c["blocked_gap_rub"]) < 1
      and abs(bc["O1"]["target_rub"] - 120_000.0) < 1, (py_c["base_source"], py_c["base_rub"], bc["O1"]["target_rub"]))
check("предохранитель базы: JS тоже fixed_point_capped", js_c["base_source"] == "fixed_point_capped" and abs(js_c["base_rub"] - 1_000_000.0) < 1, js_c["base_source"])

# перевешенная заморозка — в F своими рублями, как любая неторгуемая (§10.7, 11.11: «на плане» §10.3а отменено).
# Ожидания пересчитаны: раньше перевешенная WAIT уходила «на план» (вес в S, рубли из F) и база была ниже
# (250 000 / 0,9 = 277 778 вместо 450 000; 263 158 вместо 450 000; 222 222 вместо 400 000); недобранные, коридор,
# предохранитель — без изменений. Полей frozen_at_plan / at_plan больше нет.
KEEPS = [("K1", 100_000, 12.0, "KEEP", {"price": 100.0}), ("K2", 100_000, 12.0, "KEEP", {"price": 100.0})]
G = ("G", 50_000, 30.0, "WAIT", None)   # заморожена и недобрана — рубли в F
FZ_CASES = [
    ("WAIT перевешенная — в F, база = двойнику «держать»", KEEPS + [G, ("W", 200_000, 10.0, "WAIT", None)], 1_000_000.0,
     "fixed_point", 450_000.0),
    ("двойник: та же бумага со словом «держать» — база та же", KEEPS + [G, ("W", 200_000, 10.0, "KEEP", None)], 1_000_000.0,
     "fixed_point", 450_000.0),
    ("WAIT недобранная → рубли в F", KEEPS + [G, ("W", 60_000, 30.0, "WAIT", None)], 1_000_000.0,
     "fixed_point", 310_000.0),
    ("перевешенная и недобранная — обе в F", KEEPS + [("LA", 200_000, 5.0, "WAIT", None), ("LB", 50_000, 30.0, "WAIT", None)], 1_000_000.0,
     "fixed_point", 450_000.0),
    ("смешанный случай с предохранителем (F выше плана класса)",
     [("K1", 50_000, 20.0, "KEEP", {"price": 100.0}), ("O", 50_000, 12.0, "BUY", {"price": 100.0}), ("LA", 300_000, 5.0, "WAIT", None), ("LB", 200_000, 40.0, "WAIT", None)],
     300_000.0, "fixed_point_capped", 300_000.0),
    ("спящая перевешенная в коридоре (BALANCE, перевес 0,6 п.п.) — в F по текущим рублям",
     KEEPS + [G, ("D", 110_000, 30.0, "BALANCE", None)], 1_000_000.0, "fixed_point", 360_000.0),
    ("перевес без гейтов (блокировок нет) — перевешенная «ждать» в F", KEEPS + [("W", 200_000, 10.0, "WAIT", None)], 1_000_000.0,
     "fixed_point", 400_000.0),
]
for label, rows_f, plan_f, exp_src, exp_base in FZ_CASES:
    sp_f = tmp / "snap-fz.json"
    sp_f.write_text(json.dumps(make_snapshot(rows_f, plan=plan_f, as_of="2026-10-28"), ensure_ascii=False), encoding="utf-8")
    py_f, js_f = run_py(sp_f, None, None), run_js(sp_f, None, None)["out"]
    check(f"перевешенная заморозка: {label}: Python = JS", not diff(py_f, js_f), "; ".join(diff(py_f, js_f)[:6]))
    check(f"перевешенная заморозка: {label} → {exp_src}, база {exp_base:.0f}",
          py_f["base_source"] == exp_src and abs(py_f["base_rub"] - exp_base) < 1 and abs(js_f["base_rub"] - exp_base) < 1,
          (py_f["base_source"], py_f["base_rub"], js_f["base_rub"]))
    check(f"перевешенная заморозка: {label}: полей frozen_at_plan / at_plan нет",
          "frozen_at_plan" not in py_f and "frozen_at_plan" not in js_f
          and not any("at_plan" in r for r in py_f["rows"] + js_f["rows"]))

# инвариант §10.7: заморозка выше плана + срез BALANCE + докупка → после идеального исполнения (цели, без лотов)
# повторный расчёт даёт ноль сделок. F = W 300 000 + K1 200 000, S = 0,25 + 0,15 → база 833 333 ₽;
# при старом «на плане» база была бы 400 000 ₽, а книга после исполнения — 660 000 ₽ (повторный расчёт резал бы снова)
FI_ROWS = [("W", 300_000, 10.0, "WAIT", None), ("K1", 200_000, 20.0, "KEEP", {"price": 100.0}),
           ("BAL", 400_000, 25.0, "BALANCE", {"price": 100.0}), ("O", 100_000, 15.0, "BUY", {"price": 100.0})]
sp_fi = tmp / "snap-fz-inv.json"
sp_fi.write_text(json.dumps(make_snapshot(FI_ROWS, plan=1_000_000.0, as_of="2026-10-28"), ensure_ascii=False), encoding="utf-8")
py_fi, js_fi = run_py(sp_fi, None, None), run_js(sp_fi, None, None)["out"]
check("инвариант §10.7 (заморозка выше плана + срез): Python = JS", not diff(py_fi, js_fi), "; ".join(diff(py_fi, js_fi)[:6]))
rfi = {r["ticker"]: r for r in py_fi["rows"]}
check("инвариант §10.7: W заморожена в F своими рублями, база 833 333, BAL срез до 208 333, O докупка до 125 000",
      rfi["W"]["frozen"] and rfi["W"]["target_rub"] is None and abs(py_fi["base_rub"] - 1_000_000 / 1.2) < 1
      and rfi["BAL"]["direction"] == "trim" and abs(rfi["BAL"]["target_rub"] - 208_333.33) < 1
      and rfi["O"]["direction"] == "buy" and abs(rfi["O"]["target_rub"] - 125_000) < 1,
      (py_fi["base_rub"], rfi["BAL"]["target_rub"], rfi["O"]["target_rub"]))
FI_AFTER = [(t, (rfi[t]["target_rub"] if rfi[t]["target_rub"] is not None else v), pl, up, ex) for t, v, pl, up, ex in FI_ROWS]
check("инвариант §10.7: книга после идеального исполнения = база", abs(sum(v for _t, v, *_r in FI_AFTER) - py_fi["base_rub"]) < 1,
      sum(v for _t, v, *_r in FI_AFTER))
sp_fa = tmp / "snap-fz-after.json"
sp_fa.write_text(json.dumps(make_snapshot(FI_AFTER, plan=1_000_000.0, as_of="2026-10-28"), ensure_ascii=False), encoding="utf-8")
py_fa, js_fa = run_py(sp_fa, None, None), run_js(sp_fa, None, None)["out"]
check("инвариант §10.7: повторный расчёт после исполнения — Python = JS", not diff(py_fa, js_fa), "; ".join(diff(py_fa, js_fa)[:6]))
for nm, out in (("Python", py_fa), ("JS", js_fa)):
    check(f"инвариант §10.7 ({nm}): повторный расчёт после исполнения — ноль сделок",
          not [r["ticker"] for r in out["rows"] if r["direction"] in ("buy", "trim")] and abs(out["base_rub"] - py_fi["base_rub"]) < 1,
          [(r["ticker"], r["direction"], r["delta_rub"]) for r in out["rows"]])

# константы слов плана — одни и те же множества в Python и в JS
_src_js = ENGINE.read_text(encoding="utf-8")
_src_py = (REPO / "skills/ru-portfolio-advisor/scripts/gate_aware_sizing.py").read_text(encoding="utf-8")
import re as _re
for _name in ("EXPLICIT_NO_BUY_PLANS", "NO_BUY_DORMANT_PLANS", "AUTO_TRIM_PLANS", "AUTO_SELL_PLANS", "HOLD_IN_BASE_PLANS", "FIRST_BUY_PLANS"):
    _j = _re.search(r"var " + _name + r" = \[([^\]]*)\]", _src_js)
    _p = _re.search(r"^" + _name + r" = \{([^}]*)\}", _src_py, _re.M)
    _sj = set(_re.findall(r'"([^"]+)"', _j.group(1))) if _j else None
    _sp = set(_re.findall(r'"([^"]+)"', _p.group(1))) if _p else None
    check(f"константа {_name}: Python = JS", _sj is not None and _sj == _sp, (_sj, _sp))


# 2026-10-28 (3.90.0): первая покупка — бумага плана BUY/BALANCE без позиции; гейт должен разрешать, нет записи = «новая»
FB_GATES = gate_inputs(
    [dec("NEWQ", "2026-09-01", "HOLD", "2026-12-01"), dec("NEWI", "2026-09-01", "ADD", "2026-12-01"),
     dec("NEWX", "2026-09-01", "HOLD", "2026-12-01"), dec("NEWK", "2026-09-01", "HOLD", "2026-12-01"),
     dec("NEWD", "2026-03-01", "SELL", "2026-05-01"),     # продана давно, срок решения истёк → разбор перед покупкой
     dec("NEWU", "2026-10-01", "WATCH", "2026-12-01"),
     dec("NSELL", "2026-09-01", "HOLD", "2026-12-01"), dec("NKEEP", "2026-09-01", "HOLD", "2026-12-01"),
     dec("NWAIT", "2026-09-01", "HOLD", "2026-12-01")],
    attrs={"NEWIPO": ipo("2026-04-28")})
FB_ROWS = [("REST", 800_000, 70.0, "BUY", None), ("OTHER", 200_000, 20.0, "BUY", None)]
FB_CAND = {   # тикер: (план %, слово плана)
    "NEWQ": (4.0, "BUY"), "NEWI": (3.0, "BALANCE"), "NEWX": (2.0, "BUY"), "NEWK": (2.0, "BUY"), "NEWN": (2.0, "BUY"),
    "NEWP": (2.0, "BUY"), "NEWD": (2.0, "BUY"), "NEWU": (2.0, "BUY"), "NEWIPO": (2.0, "BUY"),
    "NSELL": (2.0, "SELL"), "NKEEP": (2.0, "KEEP"), "NWAIT": (2.0, "WAIT"), "NZERO": (0.0, "BUY"),
}
snap_fb = make_snapshot(FB_ROWS, plan=1_000_000.0, as_of="2026-10-28")
for _t, (_p, _w) in FB_CAND.items():
    snap_fb["ie_actual"]["per_ticker"][_t] = {"real_share_pct": 0.0, "planned_share_pct": _p, "ie_new_pct": _p, "user_plan": _w}
snap_fb["ie_model"] = {"positions": [{"ticker": "NEWI", "current_price_rub": 80.0}, {"ticker": "NEWQ", "current_price_rub": 999.0},
                                     {"ticker": "NEWN", "current_price_rub": 50.0}, {"ticker": "NEWP", "current_price_rub": 50.0},
                                     {"ticker": "NEWD", "current_price_rub": 50.0}, {"ticker": "NEWU", "current_price_rub": 50.0},
                                     {"ticker": "NSELL", "current_price_rub": 50.0}, {"ticker": "NEWIPO", "current_price_rub": 50.0}]}   # NEWX, NEWK — цены нет нигде (NEWK — есть котировка без цены)
fb_quotes = {"schema": "quotes@1", "items": {"NEWQ": {"price": 250.0, "lot_size": 10}, "NEWK": {"price": None, "lot_size": 1}}}
sp_fb = tmp / "snap-fb.json"
sp_fb.write_text(json.dumps(snap_fb, ensure_ascii=False), encoding="utf-8")
for _label, _q in (("с котировкой (живая цена и лот)", fb_quotes), ("без котировок (цена IE, лот неизвестен)", None)):
    py_fb = run_py(sp_fb, FB_GATES, None, quotes=_q)
    js_fb = run_js(sp_fb, FB_GATES, None, {"quotes": _q} if _q else {})["out"]
    check(f"первая покупка, {_label}: {len(py_fb['rows'])} бумаг, купить {py_fb['buy_rub']}", not diff(py_fb, js_fb), "; ".join(diff(py_fb, js_fb)[:6]))
py_fb = run_py(sp_fb, FB_GATES, None, quotes=fb_quotes)
bf = {r["ticker"]: r for r in py_fb["rows"]}
q = bf["NEWQ"]
check("первая покупка: NEWQ (гейт разрешает, котировка) — open/buy, цена и лот котировки, цель = вес × база, лоты вниз",
      q["category"] == "open" and q["direction"] == "buy" and q["first_buy"] and q["price_source"] == "live" and q["lot_known"] and q["lot_size"] == 10
      and q["price"] == 250.0 and q["current_rub"] == 0 and abs(q["target_rub"] - 0.04 * py_fb["base_rub"]) < 0.02
      and q["lots"] == int(q["target_rub"] // 2500) and q["trade_rub"] == q["lots"] * 2500, q)
check("первая покупка: цель кандидата входит в S — база = (кошелёк без открытых) / (1 − S), сумма долей сходится",
      py_fb["base_source"] in ("fixed_point", "fixed_point_capped", "t_full_no_gates") and py_fb["base_rub"] > 0, (py_fb["base_source"], py_fb["base_rub"]))
py_fb2 = run_py(sp_fb, FB_GATES, None)
b2 = {r["ticker"]: r for r in py_fb2["rows"]}
i = b2["NEWI"]
check("первая покупка: NEWI (BALANCE, без котировки) — по цене IE 80, лот неизвестен → lots null (только сумма, паритет с JS), пометки source=ie / lot_known=False",
      i["category"] == "open" and i["direction"] == "buy" and i["price_source"] == "ie" and i["lot_known"] is False and i["lot_size"] == 1 and i["price"] == 80.0
      and i["lots"] is None and i["trade_rub"] is None and i["delta_rub"] > 0, i)
check("первая покупка: котировка перебивает цену IE (NEWQ: 250, не 999), без котировки — цена IE", b2["NEWQ"]["price"] == 999.0 and b2["NEWQ"]["price_source"] == "ie", b2["NEWQ"])
check("первая покупка: нет решения → blocked gate:new_position, «после разбора бумаги»",
      all(bf[t]["category"] == "blocked" and bf[t]["reason"] == "gate:new_position" and bf[t]["unblock_by"] == "после разбора бумаги"
          and bf[t]["direction"] is None for t in ("NEWN", "NEWP")), (bf["NEWN"], bf["NEWP"]))
check("первая покупка: проданная бумага со старым истёкшим решением → blocked gate:review_aging, «после разбора бумаги»",
      bf["NEWD"]["category"] == "blocked" and bf["NEWD"]["reason"] == "gate:review_aging" and bf["NEWD"]["unblock_by"] == "после разбора бумаги", bf["NEWD"])
check("первая покупка: IPO-пауза по справочнику и у бумаги без позиции — gate:new_position; ipo_gate:2q",
      bf["NEWIPO"]["category"] == "blocked" and bf["NEWIPO"]["reason"] == "gate:new_position; ipo_gate:2q", bf["NEWIPO"])
check("первая покупка: прочие блокирующие гейты — как обычно (на пересмотре с датой)",
      bf["NEWU"]["category"] == "blocked" and bf["NEWU"]["reason"] == "gate:reviewed_under_review" and bf["NEWU"]["unblock_by"] == "2026-12-01", bf["NEWU"])
check("первая покупка: цены нет ни в котировках, ни у IE → blocked no_price",
      bf["NEWX"]["category"] == "blocked" and bf["NEWX"]["reason"] == "no_price" and bf["NEWX"]["unblock_by"] == "когда появится цена", bf["NEWX"])
check("первая покупка: котировка без цены не считается ценой (NEWK → no_price)", bf["NEWK"]["reason"] == "no_price", bf["NEWK"])
check("первая покупка: SELL / KEEP / WAIT / план 0 без позиции — строк нет", all(t not in bf for t in ("NSELL", "NKEEP", "NWAIT", "NZERO")), [t for t in ("NSELL", "NKEEP", "NWAIT", "NZERO") if t in bf])
check("первая покупка: обычные бумаги не помечены first_buy", not bf["REST"]["first_buy"] and bf["REST"]["price_source"] is None)
check("первая покупка: в итог «купить» входит сумма кандидата", py_fb["buy_rub"] >= bf["NEWQ"]["trade_rub"], py_fb["buy_rub"])
check("первая покупка: самопроверка — без решений Python и JS с решениями расходятся (тест умеет падать)",
      bool(diff(run_py(sp_fb, None, None), run_js(sp_fb, FB_GATES, None)["out"])))

# ── §10.6 (решения владельца 11.11): каскад одним расчётом, непрерывная база, разрыв из трёх слагаемых,
#    неразворот 14 дней, горизонт известных дат 7 дней — Python = JS и смысл
def _snap_file(name, rows, plan=1_000_000.0, as_of="2026-11-11", prices=None):
    sn = make_snapshot(rows, plan=plan, as_of=as_of)
    for h in sn["holdings"]:
        if prices and h["ticker"] in prices:
            h["current_price"] = prices[h["ticker"]]
    pth = tmp / f"snap-{name}.json"
    pth.write_text(json.dumps(sn, ensure_ascii=False), encoding="utf-8")
    return pth


def _both(pth, gi=None, cond=None, label=""):
    py_, js_ = run_py(pth, gi, cond), run_js(pth, gi, cond)["out"]
    check(f"§10.6 {label}: Python = JS", not diff(py_, js_), "; ".join(diff(py_, js_)[:6]))
    return py_, {r["ticker"]: r for r in py_["rows"]}


def _executed_rows(out):
    """Идеальное исполнение результата: торгуемые — на цели, остальные — как есть (строки make_snapshot)."""
    return [(r["ticker"], r["target_rub"] if r["direction"] in ("buy", "trim") else r["current_rub"], r["plan_pct"],
             r["user_plan"], {"price": 100.0}) for r in out["rows"]]


KEEP6 = [(f"K{i}", 140_000, 13.9, "KEEP", {"price": 100.0}) for i in range(6)]
# каскад срезов (как CNRU → SBER 11.11): C срезается, книга худеет, доля S (в коридоре сегодня) уходит выше коридора
CAS_T = KEEP6 + [("C", 47_000, 3.0, "BALANCE", {"price": 100.0}), ("S", 114_000, 10.5, "BALANCE", {"price": 100.0})]
py_ct, b_ct = _both(_snap_file("cas-trim", CAS_T), label="каскад срезов")
check("§10.6 каскад срезов: C и S срезаются сразу, S — каскадом (cascade), сошлось",
      b_ct["C"]["direction"] == b_ct["S"]["direction"] == "trim" and b_ct["S"]["cascade"] and not b_ct["C"]["cascade"]
      and py_ct["cascade"]["converged"] and py_ct["cascade"]["added"] == ["S"], (py_ct["cascade"], b_ct["S"]))
re_ct = run_py(_snap_file("cas-trim-2", _executed_rows(py_ct)), None, None)
check("§10.6 каскад срезов: повторный расчёт после идеального исполнения — ноль сделок",
      not [r["ticker"] for r in re_ct["rows"] if r["direction"] in ("buy", "trim")], [(r["ticker"], r["direction"]) for r in re_ct["rows"]])
# каскад покупок: докупка O растит книгу — доля B (в коридоре сегодня) уходит ниже коридора
CAS_B = KEEP6[:5] + [("O", 60_000, 20.0, "BUY", {"price": 100.0}), ("B", 80_000, 10.0, "BALANCE", {"price": 100.0})]
py_cb, b_cb = _both(_snap_file("cas-buy", CAS_B, plan=1_200_000.0), label="каскад покупок")
check("§10.6 каскад покупок: O и B докупаются сразу, B — каскадом",
      b_cb["O"]["direction"] == b_cb["B"]["direction"] == "buy" and b_cb["B"]["cascade"] and py_cb["cascade"]["converged"], (py_cb["cascade"], b_cb["B"]))
re_cb = run_py(_snap_file("cas-buy-2", _executed_rows(py_cb), plan=1_200_000.0), None, None)
check("§10.6 каскад покупок: повторный расчёт после идеального исполнения — ноль сделок",
      not [r["ticker"] for r in re_cb["rows"] if r["direction"] in ("buy", "trim")], [(r["ticker"], r["direction"]) for r in re_cb["rows"]])
# не сошлось: каскад добавляет бумаги, пока открытое не покрывает почти весь класс (база не считается) → результат
# первого прохода и cascade.converged = false (сайт показывает предупреждение)
CAS_NC = [("P0", 220_000, 22.88, "BUY", {"price": 100.0}), ("P1", 202_000, 18.76, "BALANCE", {"price": 100.0}),
          ("P2", 617_000, 57.97, "BALANCE", {"price": 100.0})]
sp_nc = _snap_file("cas-nc", CAS_NC)   # без лимитов эмитента (иначе P2 под лимитом и каскада нет)
_nc_py = json.loads(json.dumps(run_auto(json.loads(sp_nc.read_text(encoding="utf-8")), None, None, None, 1.0), default=str))
_nc_js = run_js(sp_nc, None, None, {"limits": "none"})["out"]
check("§10.6 каскад не сошёлся: Python = JS", not diff(_nc_py, _nc_js), "; ".join(diff(_nc_py, _nc_js)[:6]))
py_nc = _nc_py
check("§10.6 каскад не сошёлся: флаг converged = false, строки — первого прохода (без cascade)",
      py_nc["cascade"]["converged"] is False and py_nc["cascade"]["added"] == [] and not any(r["cascade"] for r in py_nc["rows"]),
      py_nc["cascade"])

# непрерывная база: снятие блокировок по одной — база не прыгает на план класса
CONT = KEEP6[:4] + [("C", 47_000, 3.0, "BALANCE", {"price": 100.0}), ("L", 9_500, 1.0, "KEEP", {"price": 100.0}),
                    ("G", 55_000, 12.0, "BALANCE", {"price": 100.0}), ("Y", 85_000, 10.0, "KEEP", {"price": 100.0})]
sp_cont = _snap_file("cont", CONT, plan=1_200_000.0)
_bases = []
for _gated in (("L", "G", "Y"), ("L", "Y"), ("L",), ()):
    _gi = gate_inputs([dec(t, "2026-10-01", "WATCH", "2026-12-31") for t in _gated])
    _o, _ = _both(sp_cont, _gi, label=f"непрерывная база, под гейтом {list(_gated)}")
    _bases.append((_gated, _o["base_rub"], _o["base_source"], _o["gap_gated_rub"]))
check("§10.6 непрерывная база: снятие гейта с «держать» в коридоре (Y, L) базу не меняет; последняя блокировка — без скачка",
      abs(_bases[2][1] - _bases[1][1]) < 1 and abs(_bases[3][1] - _bases[2][1]) < 1 and all(b[2] != "t_full_no_gates" for b in _bases)
      and _bases[3][3] == 0, _bases)
check("§10.6 непрерывная база: снятие гейта с недобранной «привести к плану» (G) меняет базу на её вклад, не на разрыв до плана",
      0 < _bases[1][1] - _bases[0][1] < 0.12 * 1_200_000, _bases)

# разрыв из трёх слагаемых: сумма = план − база
for _o_lbl, _o in (("каскад срезов", py_ct), ("непрерывная база", run_py(sp_cont, gate_inputs([dec("G", "2026-10-01", "WATCH", "2026-12-31")]), None))):
    check(f"§10.6 разрыв ({_o_lbl}): гейты + коридор + нераспределённое = план − база",
          abs(_o["gap_gated_rub"] + _o["gap_in_corridor_rub"] + _o["gap_unallocated_rub"] - _o["blocked_gap_rub"]) < 0.05,
          (_o["gap_gated_rub"], _o["gap_in_corridor_rub"], _o["gap_unallocated_rub"], _o["blocked_gap_rub"]))

# неразворот 14 дней: срез → докупка в 14 дней нет; новое решение / правка плана позже дня сделки — есть; через 14 дней — есть
NR = KEEP6[:5] + [("B", 70_000, 10.0, "BALANCE", {"price": 100.0}), ("T", 160_000, 10.0, "BALANCE", {"price": 100.0})]
sp_nr = _snap_file("nr", NR)
_nr_sold = gate_inputs(last_sell_at={"B": T("2026-11-05", "00:00")}, last_buy_at={"T": T("2026-11-03", "00:00")})
py_nr, b_nr = _both(sp_nr, _nr_sold, label="неразворот")
check("§10.6 неразворот: B продана 05.11 — докупки нет до 19.11 (blocked, no_reversal), T куплена 03.11 — среза нет до 17.11",
      (b_nr["B"]["category"], b_nr["B"]["direction"], b_nr["B"]["reason"], b_nr["B"]["unblock_by"]) == ("blocked", None, "no_reversal:2026-11-19", "2026-11-19")
      and b_nr["B"]["no_reversal"] == {"until": "2026-11-19", "trade": "sell", "trade_at": "2026-11-05"}
      and (b_nr["T"]["category"], b_nr["T"]["direction"], b_nr["T"]["reason"]) == ("dormant", None, "no_reversal:2026-11-17"), (b_nr["B"], b_nr["T"]))
_, b_nr2 = _both(sp_nr, dict(_nr_sold, decisions=[dec("B", "2026-11-06", "HOLD", "2026-12-31")]), label="неразворот снят решением")
_, b_nr3 = _both(sp_nr, dict(_nr_sold, plan_changed_at={"B": T("2026-11-07", "12:00"), "T": T("2026-11-03", "18:00")}), label="неразворот, правка плана")
_, b_nr4 = _both(sp_nr, dict(_nr_sold, last_sell_at={"B": T("2026-10-28", "00:00")}, last_buy_at={"T": T("2026-10-28", "00:00")}), label="неразворот через 14 дней")
check("§10.6 неразворот снимает новое решение после дня сделки (B докупается)", b_nr2["B"]["direction"] == "buy" and b_nr2["B"]["no_reversal"] is None, b_nr2["B"])
check("§10.6 неразворот снимает правка плана после дня сделки (B), правка в день сделки — нет (T)",
      b_nr3["B"]["direction"] == "buy" and b_nr3["T"]["reason"] == "no_reversal:2026-11-17", (b_nr3["B"], b_nr3["T"]))
check("§10.6 неразворот: через 14 дней после сделки — снова докупка и срез", b_nr4["B"]["direction"] == "buy" and b_nr4["T"]["direction"] == "trim", (b_nr4["B"], b_nr4["T"]))

# горизонт известных дат 7 дней (только для среза): T срезается; H недобрана под паузой / условием
HZ = KEEP6[:5] + [("T", 160_000, 10.0, "BALANCE", {"price": 100.0}), ("H", 60_000, 10.0, "BUY", {"price": 100.0})]
sp_hz = _snap_file("hz", HZ, prices={"H": 95.0})
_hz_base = run_py(sp_hz, gate_inputs([dec("H", "2026-08-01", "WATCH", "2026-12-31")]), None)   # гейт — не горизонт
_b0 = {r["ticker"]: r for r in _hz_base["rows"]}
_cool = gate_inputs([dec("H", "2026-10-24", "ADD", "2026-12-31")], last_buy_at={"H": T("2026-10-24", "00:00")})   # пауза до 14.11
py_hz, b_hz = _both(sp_hz, _cool, label="горизонт: пауза кончается через 3 дня")
check("§10.6 горизонт: пауза до 14.11 (через 3 дня) — H «откроется 14.11», не покупается; база среза больше, срез T меньше",
      (b_hz["H"]["category"], b_hz["H"]["direction"], b_hz["H"]["opens_on"], b_hz["H"]["opens_if_price_holds"]) == ("blocked", None, "2026-11-14", False)
      and py_hz["horizon"] == ["H"] and py_hz["base_trim_rub"] > py_hz["base_rub"]
      and abs(b_hz["T"]["delta_rub"]) < abs(_b0["T"]["delta_rub"]) and b_hz["T"]["direction"] == "trim", (py_hz["base_trim_rub"], py_hz["base_rub"], b_hz["H"]))
_rep = conds([cdef("h-rep", "H", {"type": "report_published", "value": "МСФО", "window_end": "2026-11-13"}, on="HOLD", while_="HOLD")], [])
py_hr, b_hr = _both(sp_hz, gate_inputs(), _rep, label="горизонт: условие «отчёт»")
check("§10.6 горизонт: условие «вышел отчёт» (исход неизвестен) — не учитывается", py_hr["horizon"] == [] and b_hr["H"]["opens_on"] is None and py_hr["base_trim_rub"] is None, b_hr["H"])
_dp = lambda thr: conds([cdef("h-px", "H", {"type": "price_below", "value": thr}, on="BUY", while_="HOLD", not_before="2026-11-14")], [])
py_hp, b_hp = _both(sp_hz, gate_inputs(), _dp(100.5), label="горизонт: дата + цена за порогом")
py_hn, b_hn = _both(sp_hz, gate_inputs(), _dp(90.5), label="горизонт: дата + цена не за порогом")
check("§10.6 горизонт: «дата + цена» — цена 95 уже ниже порога 100,5 → учитывается «если цена удержится»; порог 90,5 — нет",
      (b_hp["H"]["opens_on"], b_hp["H"]["opens_if_price_holds"]) == ("2026-11-14", True) and py_hp["base_trim_rub"] is not None
      and b_hn["H"]["opens_on"] is None and py_hn["horizon"] == [], (b_hp["H"], b_hn["H"]))
_ipo = {"H": ipo("2024-11-14")}   # 8 кварталов — 14.11.2026, через 3 дня
py_ie, b_ie = _both(sp_hz, gate_inputs([dec("H", "2026-09-01", "HOLD", "2026-11-12")], attrs=_ipo), label="горизонт: IPO-пауза + решение истекает")
py_iv, b_iv = _both(sp_hz, gate_inputs([dec("H", "2026-09-01", "HOLD", "2026-12-31")], attrs=_ipo), label="горизонт: IPO-пауза + действующее «держать»")
check("§10.6 горизонт: IPO-пауза кончается 14.11, но срок решения к тому дню истёк — не «скоро открытая»; с действующим «держать» — учитывается",
      b_ie["H"]["opens_on"] is None and py_ie["horizon"] == [] and b_iv["H"]["opens_on"] == "2026-11-14" and py_iv["horizon"] == ["H"], (b_ie["H"], b_iv["H"]))

print("== 2. Лимиты концентрации JS = references/concentration-limits.yaml ==")
conc_js = run_js(sp, None, None)["conc"]
cfg = yaml.safe_load(LIMITS.read_text(encoding="utf-8"))
check("лимит по эмитенту по умолчанию", float(cfg["default_issuer_limit_pct"]) == conc_js["default_issuer_limit_pct"])
check("группы эмитентов", {k: sorted(v) for k, v in cfg["issuer_groups"].items()} == {k: sorted(v) for k, v in conc_js["issuer_groups"].items()})
ex_y = {k: (v["issuer"], float(v["limit_pct"]), str(v["review_date"])) for k, v in cfg["issuer_exceptions"].items()}
ex_j = {k: (v["issuer"], float(v["limit_pct"]), str(v["review_date"])) for k, v in conc_js["issuer_exceptions"].items()}
check("именованные исключения (эмитент, лимит, дата пересмотра)", ex_y == ex_j, f"{ex_y} vs {ex_j}")

print("== 3. Сверка ловит расхождение (тест проверяет сам себя) ==")
sp.write_text(json.dumps(CASES["перевес BALANCE в коридоре — без среза"][0], ensure_ascii=False), encoding="utf-8")
check("другой гистерезис в JS на докупке → расхождение найдено",
      bool(diff(run_py(sp_auto, None, AUTO_CONDS, 2.5), run_js(sp_auto, None, AUTO_CONDS, {"hysteresisPp": 1.0})["out"])))
check("другой гистерезис в JS → расхождение найдено", bool(diff(run_py(sp, None, None), run_js(sp, None, None, {"hysteresisPp": 0.5})["out"])))
sp.write_text(json.dumps(CASES[next(iter(CASES))][0], ensure_ascii=False), encoding="utf-8")
check("без лимитов концентрации в JS → расхождение найдено",
      bool(diff(run_py(sp, GATES, CONDS), run_js(sp, GATES, CONDS, {"limits": "none"})["out"])))
_mut = tmp / "mut"
_mut.mkdir()
for _f in ("rebalance-engine.js", "codelists.js", "conditions-merge.js", "last-word.js"):
    shutil.copy(REPO / "tools/assets" / _f, _mut / _f)
_lw = (_mut / "last-word.js").read_text(encoding="utf-8")
(_mut / "last-word.js").write_text(_lw.replace("ADD_COOLDOWN_DAYS = D.add_cooldown_days", "ADD_COOLDOWN_DAYS = D.add_cooldown_days + 1"), encoding="utf-8")
_eng, ENGINE = ENGINE, _mut / "rebalance-engine.js"
_dm = diff(run_py(sp_r, RS_GATES, RS_CONDS), run_js(sp_r, RS_GATES, RS_CONDS)["out"])
ENGINE = _eng
check("модуль (б) в JS с паузой докупки на день длиннее → расхождение найдено (R_COOL, R_MIX)",
      any(x.startswith("R_COOL.") for x in _dm) and any(x.startswith("R_MIX.") for x in _dm), _dm[:4])

print("== 4. Реальные снапшоты (Synology) с решениями и справочником бумаг шага 9 и условиями conditions@2 ==")


def real_inputs():
    """Входы гейта и условий из рабочей папки после переключения 31.10 (decision.md §4.2), только чтением:
    decisions/ + security-attrs.json и conditions.yaml (conditions@2) + conditions-state.json. Чего нет — None."""
    gi = None
    dec, attrs = MEM / "decisions", MEM / "security-attrs.json"
    if dec.is_dir():
        gi, _w = load_gate_inputs(str(dec), str(attrs) if attrs.exists() else None)
    cond = None
    if (MEM / "conditions.yaml").exists() and (MEM / "conditions-state.json").exists():
        cond, _w = load_conditions_inputs(str(MEM / "conditions.yaml"), str(MEM / "conditions-state.json"))
    return gi, cond


snaps = sorted((MEM / "snapshots").glob("portfolio-*.json")) if (MEM / "snapshots").is_dir() else []
gi_real, cd_real = real_inputs() if snaps else (None, None)
if not snaps:
    print("  · пропуск — Synology не смонтирован")
else:
    print(f"  · решений {len((gi_real or {}).get('decisions') or [])}, условий {len((cd_real or {}).get('defs') or [])}"
          + ("" if gi_real else " — временного корня шага 9 нет, гейт без решений"))
    for sp in snaps[-3:]:
        try:
            py = run_py(sp, gi_real, cd_real)
        except Exception as exc:  # noqa: BLE001 — старый снапшот без нужных полей: не про сверку
            print(f"  · {sp.name}: Python не посчитал ({str(exc)[:80]}) — пропуск")
            continue
        js = run_js(sp, gi_real, cd_real)["out"]
        d = diff(py, js)
        acts = sum(1 for r in py["rows"] if r["direction"] in ("buy", "trim"))
        blk = sum(1 for r in py["rows"] if r["category"] == "blocked")
        check(f"{sp.name}: совпало ({len(py['rows'])} бумаг, действий {acts}, заблокировано {blk})", not d, "; ".join(d[:6]))

print("== 5. Живые цены поверх снапшота (apply_quotes / applyQuotes) ==")


def live_synth():
    """Синтетика: make_snapshot + qty, ИИС-позиция, фонд, итоги и строка класса с «Доля план»."""
    snap = make_snapshot(BASE_ROWS)
    for h in snap["holdings"]:
        h["qty"] = h["value_rub"] / h["current_price"]
        h["current_price_ts"] = "2026-10-13 09:00:00"
    snap["holdings"] += [
        {"ticker": "IISBK", "asset_type": "fund", "account": "iis_3", "qty": 100.0, "current_price": 50.0, "value_rub": 5000.0,
         "current_price_source": "moex_iss", "lot_size": 10, "is_blocked": False},          # ИИС: цену получает, NAV без ИИС не трогает
        {"ticker": "FUNDX", "asset_type": "fund", "account": "main", "qty": 1000.0, "current_price": 12.5, "value_rub": 12500.0,
         "current_price_source": "moex_iss", "lot_size": None, "is_blocked": False},         # фонд: цена + лот из котировки
        {"ticker": "BONDY", "asset_type": "bond", "account": "main", "qty": 10.0, "current_price": 98.0, "value_rub": 9800.0,
         "current_price_source": "moex_iss", "lot_size": 1, "is_blocked": False},            # облигации — вне волны 1
    ]
    bs = snap["balance_summary"]
    bs.update({"total_current_rub": bs["total_current_rub_excl_iis"], "total_current_rub_incl_iis": bs["total_current_rub_excl_iis"] + 600_000.0,
               "iis_balance_rub": 600_000.0})
    row = bs["goals_matrix"][0]
    row.update({"Доля план": 0.4, "Планы": 0.4 * bs["total_current_rub_excl_iis"],
                "Доля нынешняя": row["Сейчас"] / bs["total_current_rub_excl_iis"], "Изменение": 0.4 * bs["total_current_rub_excl_iis"] - row["Сейчас"]})
    return snap


syn = live_synth()
sp, qp = tmp / "snap.json", tmp / "quotes.json"
sp.write_text(json.dumps(syn, ensure_ascii=False), encoding="utf-8")
SKIP = {"LKOH", "NEWCO"}                                  # без котировки → missing, цена снапшота
q = shifted_quotes(syn, skip=lambda t: t in SKIP)
q["items"]["FUNDX"]["lot_size"] = 100
qp.write_text(json.dumps(q, ensure_ascii=False), encoding="utf-8")
py_snap = apply_quotes(json.loads(sp.read_text(encoding="utf-8")), q)
js = run_js_apply(sp, qp, GATES, CONDS)
d = snap_diff(py_snap, js["snap"])
check("синтетика: apply_quotes Py = applyQuotes JS по всем полям снапшота", not d, "; ".join(d[:6]))
check("синтетика: JS не мутирует входной снапшот", js["pure"])
orig = json.loads(sp.read_text(encoding="utf-8"))
check("синтетика: Python не мутирует входной снапшот", syn == orig and apply_quotes(syn, q) is not syn)
d = diff(json.loads(json.dumps(run_auto(py_snap, GATES, CONDS, load_limits_config(str(LIMITS)), 1.0), default=str)), js["out"])
check("синтетика: run_auto / runAuto на пересчитанном снапшоте совпали", not d, "; ".join(d[:6]))

H = {h["ticker"]: h for h in py_snap["holdings"]}
H0 = {h["ticker"]: h for h in syn["holdings"]}
check("покрытие: применено moex_live, цена ×1.07/0.93, value_rub = qty×цена",
      H["SBER"]["current_price_source"] == "moex_live" and abs(H["SBER"]["value_rub"] - H["SBER"]["qty"] * H["SBER"]["current_price"]) < 0.01
      and H["SBER"]["current_price"] != H0["SBER"]["current_price"] and H["SBER"]["current_price_ts"] == "2026-10-14 11:00:00")
check("покрытие: тикер без котировки — цена снапшота, в live_quotes.missing",
      all(H[t]["current_price"] == H0[t]["current_price"] and H[t]["current_price_source"] == "moex_iss" for t in SKIP)
      and sorted(py_snap["live_quotes"]["missing"]) == sorted(SKIP) and "SBER" in py_snap["live_quotes"]["applied"], py_snap["live_quotes"])
check("покрытие: cost_basis не тронут", H["FROZEN"] == H0["FROZEN"])
check("покрытие: облигации не тронуты (волна 2)", H["BONDY"] == H0["BONDY"])
check("покрытие: лот фонда из котировки (был null), у остальных не меняется",
      H["FUNDX"]["lot_size"] == 100 and H["MOEX"]["lot_size"] == H0["MOEX"]["lot_size"])
bs, bs0 = py_snap["balance_summary"], syn["balance_summary"]
d_main = sum(H[t]["value_rub"] - H0[t]["value_rub"] for t in H if H[t].get("account") == "main")
d_iis = H["IISBK"]["value_rub"] - H0["IISBK"]["value_rub"]
check("покрытие: ИИС получил цену, NAV без ИИС сдвинулся только на main",
      H["IISBK"]["current_price_source"] == "moex_live" and d_iis != 0
      and abs(bs["total_current_rub_excl_iis"] - (bs0["total_current_rub_excl_iis"] + d_main)) < 0.02
      and abs(bs["total_current_rub"] - bs["total_current_rub_excl_iis"]) < 0.02
      and abs(bs["total_current_rub_incl_iis"] - (bs0["total_current_rub_incl_iis"] + d_main + d_iis)) < 0.02
      and abs(bs["iis_balance_rub"] - (bs0["iis_balance_rub"] + d_iis)) < 0.02, (bs, d_main, d_iis))
book_sum = sum(H[t]["value_rub"] for t in H if H[t]["asset_type"] == "stock" and H[t]["current_price_source"] != "cost_basis"
               and not H[t]["is_blocked"] and t != "TMON")
row = bs["goals_matrix"][0]
check("покрытие: Сейчас = Σ книги, Планы = Доля план × NAV', Изменение = Планы − Сейчас",
      abs(row["Сейчас"] - book_sum) < 0.02 and abs(row["Планы"] - 0.4 * bs["total_current_rub_excl_iis"]) < 0.02
      and abs(row["Изменение"] - (row["Планы"] - row["Сейчас"])) < 0.02
      and abs(row["Доля нынешняя"] - row["Сейчас"] / bs["total_current_rub_excl_iis"]) < 1e-9, row)
pt = py_snap["ie_actual"]["per_ticker"]
check("покрытие: доли активной книги суммируются в 100 %, planned_share_pct/user_plan не тронуты",
      abs(sum(v["real_share_pct"] for v in pt.values()) - 100) < 0.01
      and all(pt[t]["planned_share_pct"] == syn["ie_actual"]["per_ticker"][t]["planned_share_pct"] for t in pt))

print("-- 5б. Три реальных снапшота, цены сдвинуты ±7 % по чётности тикера, каждый пятый без котировки --")
real = sorted((MEM / "snapshots").glob("portfolio-*.json"))[-3:] if (MEM / "snapshots").is_dir() else []
if not real:
    print("  · пропуск — Synology не смонтирован")
for rp in real:
    snap = json.loads(rp.read_text(encoding="utf-8"))
    qr = shifted_quotes(snap, skip=lambda t: sum(map(ord, t)) % 5 == 0)
    qrp = tmp / "q_real.json"
    qrp.write_text(json.dumps(qr, ensure_ascii=False), encoding="utf-8")
    try:
        pys = apply_quotes(snap, qr)
        jsr = run_js_apply(rp, qrp, gi_real, cd_real)
        pya = json.loads(json.dumps(run_auto(pys, gi_real, cd_real, load_limits_config(str(LIMITS)), 1.0), default=str))
    except Exception as exc:  # noqa: BLE001 — старый снапшот без нужных полей: не про сверку
        print(f"  · {rp.name}: не посчитался ({str(exc)[:80]}) — пропуск")
        continue
    d = snap_diff(pys, jsr["snap"]) + diff(pya, jsr["out"])
    lq = pys["live_quotes"]
    check(f"{rp.name}: Py = JS (применено {len(lq['applied'])}, без котировки {len(lq['missing'])}, NAV' {pys['balance_summary']['total_current_rub_excl_iis']:.0f})",
          not d and jsr["pure"], "; ".join(d[:6]))

print("-- 5б2. Факт классов и матрицы валюта × класс по живым ценам: Σ классов = Σ ячеек = NAV' (фонды — класс из plan.funds) --")
_plan_p = MEM / "plan.json"
_funds = json.loads(_plan_p.read_text(encoding="utf-8")).get("funds") if _plan_p.is_file() else None
for rp in real:
    snap = json.loads(rp.read_text(encoding="utf-8"))
    bs0 = snap.get("balance_summary") or {}
    if not bs0.get("class_plan_vs_fact") or not bs0.get("matrix_plan_vs_fact"):
        print(f"  · {rp.name}: нет class_plan_vs_fact — пропуск")
        continue
    qr = shifted_quotes(snap, skip=lambda t: sum(map(ord, t)) % 5 == 0)
    qrp = tmp / "q_real_cls.json"
    qrp.write_text(json.dumps(qr, ensure_ascii=False), encoding="utf-8")
    pys = apply_quotes(snap, qr, _funds)
    jsr = run_js_apply(rp, qrp, gi_real, cd_real, {"fundClasses": _funds})
    d = snap_diff(pys, jsr["snap"])
    bsl = pys["balance_summary"]
    nav = bsl["total_current_rub_excl_iis"]
    sc0 = sum(r["actual_rub"] or 0 for r in bs0["class_plan_vs_fact"])
    sc = sum(r["actual_rub"] or 0 for r in bsl["class_plan_vs_fact"])
    sm = sum(r["actual_rub"] or 0 for r in bsl["matrix_plan_vs_fact"])
    st = next((r for r in bsl["class_plan_vs_fact"] if r["class"] == "Акции"), None)
    gm = next((r for r in bsl.get("goals_matrix") or [] if r.get("Валюта") == "RUB" and r.get("Бумага") == "Акция"), None)
    check(f"{rp.name}: классы по живым ценам — Py = JS", not d, "; ".join(d[:6]))
    # снапшот: Σ классов = NAV загрузчика; после цен расхождение не растёт (сдвиг ровно на ΣΔ main)
    check(f"{rp.name}: Σ классов − NAV' = Σ классов − NAV снапшота ({sc - nav:+.2f}), Σ ячеек матрицы = Σ классов",
          abs((sc - nav) - (sc0 - bs0["total_current_rub_excl_iis"])) < 0.5 and abs(sm - sc) < 0.5, (sc, sm, nav, sc0))
    check(f"{rp.name}: доли классов — от NAV', delta_rub = target_rub − actual_rub, «Акции» = Σ книги (goals_matrix)",
          all(r["actual_pct"] is None or abs(r["actual_pct"] - r["actual_rub"] / nav * 100) < 1e-3 for r in bsl["class_plan_vs_fact"])
          and all(r["target_pct"] is None or abs(r["delta_rub"] - (r["target_rub"] - r["actual_rub"])) < 0.02 for r in bsl["class_plan_vs_fact"])
          and (st is None or gm is None or abs(st["actual_rub"] - gm["Сейчас"]) < 0.5 + abs(sc0 - bs0["total_current_rub_excl_iis"])),
          (st, gm))

# синтетика: фонд с классом в плане (Золото USD), фонд без записи → «не отнесён», облигация валютной корзины, ИИС не сдвигает
_cs = make_snapshot([("SBER", 400_000, 40.0, "BUY", {"price": 100.0})], nav=1_000_000.0)
for h in _cs["holdings"]:
    h["qty"] = h["value_rub"] / h["current_price"]
_cs["holdings"] += [
    {"ticker": "GLDF", "asset_type": "fund", "account": "main", "qty": 1000.0, "current_price": 100.0, "value_rub": 100_000.0, "current_price_source": "moex_iss"},
    {"ticker": "NOPLAN", "asset_type": "fund", "account": "main", "qty": 100.0, "current_price": 100.0, "value_rub": 10_000.0, "current_price_source": "moex_iss"},
    {"ticker": "IISF", "asset_type": "fund", "account": "iis_3", "qty": 100.0, "current_price": 100.0, "value_rub": 10_000.0, "current_price_source": "moex_iss"},
    {"ticker": "USDB", "isin": "XS000USDB", "asset_type": "bond", "account": "main", "qty": 10.0, "current_price": 100.0, "value_rub": 90_000.0,
     "nominal": 100.0, "nominal_currency": "USD", "plan_bucket": "USD", "accrued_int": 0.0, "current_price_source": "moex_iss", "is_blocked": False}]
_cs["balance_summary"].update({"total_current_rub_excl_iis": 1_000_000.0, "class_plan_vs_fact": [
    {"class": "Кеш", "target_pct": 10.0, "target_rub": 100_000.0, "actual_rub": 400_000.0, "actual_pct": 40.0, "delta_pp": -30.0, "delta_rub": -300_000.0},
    {"class": "Акции", "target_pct": 40.0, "target_rub": 400_000.0, "actual_rub": 400_000.0, "actual_pct": 40.0, "delta_pp": 0.0, "delta_rub": 0.0},
    {"class": "Облигация", "target_pct": 40.0, "target_rub": 400_000.0, "actual_rub": 90_000.0, "actual_pct": 9.0, "delta_pp": 31.0, "delta_rub": 310_000.0},
    {"class": "Золото", "target_pct": 10.0, "target_rub": 100_000.0, "actual_rub": 100_000.0, "actual_pct": 10.0, "delta_pp": 0.0, "delta_rub": 0.0},
    {"class": None, "target_pct": None, "target_rub": None, "actual_rub": 10_000.0, "actual_pct": 1.0, "delta_pp": None, "delta_rub": None}],
    "matrix_plan_vs_fact": [
    {"currency": "RUB", "class": "Акция", "target_pct": 40.0, "target_rub": 400_000.0, "actual_rub": 400_000.0, "actual_pct": 40.0, "delta_pp": 0.0, "delta_rub": 0.0},
    {"currency": "USD", "class": "Облигация", "target_pct": 40.0, "target_rub": 400_000.0, "actual_rub": 90_000.0, "actual_pct": 9.0, "delta_pp": 31.0, "delta_rub": 310_000.0}]})
_cq = {"schema": "quotes@1", "fetched_at": "2026-10-14T11:15:00+03:00", "stale": False, "fx": {"USD": 95.0, "date": "2026-10-14"}, "items": {
    "SBER": {"price": 110.0, "lot_size": 1}, "GLDF": {"price": 90.0}, "NOPLAN": {"price": 120.0}, "IISF": {"price": 200.0},
    "USDB": {"price": 100.0, "face_value": 100.0, "face_unit": "USD", "accrued_int": 0.0, "isin": "XS000USDB"}}}
_csp, _cqp = tmp / "snap-cls.json", tmp / "q-cls.json"
_csp.write_text(json.dumps(_cs, ensure_ascii=False), encoding="utf-8")
_cqp.write_text(json.dumps(_cq, ensure_ascii=False), encoding="utf-8")
_cf = {"GLDF": {"class": "Золото", "currency": "USD"}}
_cpy = apply_quotes(_cs, _cq, _cf)
_cjs = run_js_apply(_csp, _cqp, None, None, {"fundClasses": _cf})["snap"]
check("классы, синтетика: Py = JS", not snap_diff(_cpy, _cjs), "; ".join(snap_diff(_cpy, _cjs)[:6]))
_cr = {r["class"]: r for r in _cpy["balance_summary"]["class_plan_vs_fact"]}
_mr = {(r["currency"], r["class"]): r for r in _cpy["balance_summary"]["matrix_plan_vs_fact"]}
# Δ: SBER +40 000 (Акции), GLDF −10 000 (Золото, USD), NOPLAN +2 000 («не отнесён»), USDB 10×(100/100×100×95) = 95 000 → +5 000; ИИС вне
check("классы, синтетика: Акции 440 000, Золото 90 000, не отнесён 12 000, Облигация 95 000, Кеш 400 000; NAV' 1 037 000 = Σ",
      abs(_cr["Акции"]["actual_rub"] - 440_000) < 0.01 and abs(_cr["Золото"]["actual_rub"] - 90_000) < 0.01
      and abs(_cr[None]["actual_rub"] - 12_000) < 0.01 and abs(_cr["Облигация"]["actual_rub"] - 95_000) < 0.01
      and abs(_cr["Кеш"]["actual_rub"] - 400_000) < 0.01 and abs(_cpy["balance_summary"]["total_current_rub_excl_iis"] - 1_037_000) < 0.01
      and abs(sum(r["actual_rub"] for r in _cr.values()) - 1_037_000) < 0.01, _cr)
check("классы, синтетика: доли и дельты от NAV' (Акции 42,4301 %, target 414 800, delta −25 200), ячейки USD/Облигация и новая USD/Золото",
      abs(_cr["Акции"]["actual_pct"] - 42.4301) < 1e-4 and abs(_cr["Акции"]["target_rub"] - 414_800) < 0.01
      and abs(_cr["Акции"]["delta_rub"] + 25_200) < 0.01 and abs(_mr[("USD", "Облигация")]["actual_rub"] - 95_000) < 0.01
      and abs(_mr[("USD", "Золото")]["actual_rub"] + 10_000) < 0.01 and _mr[("USD", "Золото")]["target_pct"] is None
      and abs(_mr[("RUB", "Акция")]["actual_rub"] - 440_000) < 0.01, (_cr["Акции"], _mr))
_rcl = subprocess.run([NODE, "-e", r"""
const fs = require('fs'); const E = require(process.argv[1]);
const s0 = JSON.parse(fs.readFileSync(process.argv[2], 'utf8')), q = JSON.parse(fs.readFileSync(process.argv[3], 'utf8')), fc = JSON.parse(process.argv[4]);
const want = E.applyQuotes(s0, q, { fundClasses: fc }), got = E.applyQuotes(s0, q, {});
const h0 = JSON.stringify(got.holdings);
E.reclassLive(s0, got, fc);
process.stdout.write(JSON.stringify({ same: JSON.stringify(got.balance_summary) === JSON.stringify(want.balance_summary), holdings: JSON.stringify(got.holdings) === h0 }));
""", str(ENGINE), str(_csp), str(_cqp), json.dumps(_cf)], capture_output=True, text=True, timeout=60)
_rcj = json.loads(_rcl.stdout) if _rcl.returncode == 0 else {}
check("классы: reclassLive (вьюер, план загрузился после цен) = applyQuotes с plan.funds, позиции копии не тронуты", _rcj == {"same": True, "holdings": True}, _rcl.stderr[:300] or _rcj)
_cn = apply_quotes(_cs, _cq)
check("классы, синтетика: без plan.funds фонд GLDF — в «не отнесён» (правило загрузчика), Σ классов = NAV'",
      abs({r["class"]: r for r in _cn["balance_summary"]["class_plan_vs_fact"]}[None]["actual_rub"] - 2_000) < 0.01
      and abs(sum(r["actual_rub"] for r in _cn["balance_summary"]["class_plan_vs_fact"]) - 1_037_000) < 0.01)

print("-- 5в. P0: цена = value_rub/qty снапшота → доли и строка класса «Акция» не меняются --")
# Реальные value_rub снапшота НЕ равны qty × current_price (оценка из баланса Numbers идёт по другой
# цене: YDEX −4773 ₽, всего ≈5 тыс. ₽ на книгу). Поэтому «равные цены» берём как value_rub/qty —
# так проверяется сама формула (доли от книги, Сейчас = Σ книги, Планы = Доля план × NAV').
# Скачок от оценки снапшота к рыночной qty × цена — отдельно, справочно (не ошибка пересчёта).
for rp in real:
    snap = json.loads(rp.read_text(encoding="utf-8"))
    qeq = shifted_quotes(snap, factor=1.0)
    for h in snap["holdings"]:
        if h["ticker"] in qeq["items"] and h.get("qty"):
            qeq["items"][h["ticker"]]["price"] = h["value_rub"] / h["qty"]
    same = apply_quotes(snap, qeq)
    try:
        row0 = next(r for r in snap["balance_summary"]["goals_matrix"] if r["Валюта"] == "RUB" and r["Бумага"] == "Акция")
        row1 = next(r for r in same["balance_summary"]["goals_matrix"] if r["Валюта"] == "RUB" and r["Бумага"] == "Акция")
        p0, p1 = snap["ie_actual"]["per_ticker"], same["ie_actual"]["per_ticker"]
        bad = [t for t in p0 if p0[t].get("real_share_pct") is not None and abs(p0[t]["real_share_pct"] - p1[t]["real_share_pct"]) > 0.01]
        # Снапшот без «Общего баланса» (balance_carried_from): строка «Акция» перенесена с другого дня и
        # с holdings не совпадает по построению — ждём не «не изменилась», а «= Σ книги по value_rub».
        if snap.get("balance_carried_from"):
            book = sum(float(h.get("value_rub") or 0) for h in snap["holdings"]
                       if h.get("asset_type") == "stock" and h.get("qty") and h.get("current_price_source") != "cost_basis")
            # доли ie_actual в таком снапшоте — тоже с дня баланса (extraction_date), сверяем с долями от книги
            val = {}
            for h in snap["holdings"]:
                if h.get("asset_type") == "stock" and h.get("qty") and h.get("current_price_source") != "cost_basis":
                    val[h["ticker"]] = val.get(h["ticker"], 0.0) + float(h.get("value_rub") or 0)
            bad = [t for t in p1 if p1[t].get("real_share_pct") is not None and t in val and book
                   and abs(p1[t]["real_share_pct"] - val[t] / book * 100) > 0.01]
            ok = (not bad and abs(row1["Сейчас"] - book) < 1)
            check(f"{rp.name}: баланс перенесён с {snap['balance_carried_from']} — доли = книга ±0.01 п.п. ({len(p1)} бумаг), Сейчас = Σ книги ±1 ₽ ({row1['Сейчас']:.0f})",
                  ok, f"доли: {bad[:4]}; Сейчас {row0['Сейчас']} → {row1['Сейчас']} при книге {book:.2f}")
        else:
            ok = (not bad and abs(row0["Сейчас"] - row1["Сейчас"]) < 1 and abs(row0["Планы"] - row1["Планы"]) < 1)
            check(f"{rp.name}: real_share_pct ±0.01 п.п. ({len(p0)} бумаг), Сейчас/Планы ±1 ₽ ({row1['Сейчас']:.0f} / {row1['Планы']:.0f})",
                  ok, f"доли: {bad[:4]}; Сейчас {row0['Сейчас']} → {row1['Сейчас']}; Планы {row0['Планы']} → {row1['Планы']}")
        mk = apply_quotes(snap, shifted_quotes(snap, factor=1.0))
        pm = mk["ie_actual"]["per_ticker"]
        print(f"    · справочно, цены = current_price снапшота: Сейчас {row0['Сейчас']:.0f} → "
              f"{next(r for r in mk['balance_summary']['goals_matrix'] if r['Валюта'] == 'RUB' and r['Бумага'] == 'Акция')['Сейчас']:.0f}, "
              f"макс. сдвиг доли {max(abs(p0[t]['real_share_pct'] - pm[t]['real_share_pct']) for t in p0 if p0[t].get('real_share_pct') is not None):.3f} п.п.")
    except (StopIteration, KeyError, TypeError) as exc:
        print(f"  · {rp.name}: в снапшоте нет нужных полей ({exc!r}) — пропуск")

print("-- 5г. Самопроверка: JS без пересчёта долей обязан разойтись --")
d = snap_diff(py_snap, run_js_apply(sp, qp, GATES, CONDS, {"noShares": True})["snap"])
check("applyQuotes без пересчёта real_share_pct → расхождение найдено", any("real_share_pct" in x for x in d), d[:3])

print("-- 5д. Облигации (TQOB/TQCB): цена — % номинала × курс ЦБ (валютные) + НКД в ₽; поиск SECID → ISIN; заблокированные не трогаются; нет курса — в missing_bonds --")
bsyn = live_synth()
bsyn["holdings"] = [h for h in bsyn["holdings"] if h["ticker"] != "BONDY"] + [
    {"ticker": "RU000A0JS3W6", "isin": "RU000A0JS3W6", "asset_type": "bond", "account": "main", "qty": 100.0, "current_price": 98.0,
     "nominal": 1000.0, "nominal_currency": "RUB", "accrued_int": 20.0, "value_rub": 100000.0, "current_price_source": "moex_iss", "is_blocked": False},   # ключ — ISIN (SECID у ISS другой)
    {"ticker": "RU000A1CORP", "isin": "RU000A1CORP", "asset_type": "bond", "account": "iis_3", "qty": 7.0, "current_price": 101.0,
     "nominal": 1000.0, "nominal_currency": "RUB", "accrued_int": 5.5, "value_rub": 7000.0, "current_price_source": "moex_iss", "is_blocked": False},   # ИИС, ключ — SECID
    {"ticker": "RU000A10DQB6", "isin": "RU000A10DQB6", "asset_type": "bond", "account": "main", "qty": 3.0, "current_price": 99.0,
     "nominal": 10000.0, "nominal_currency": "CNY", "accrued_int": 1400.0, "value_rub": 250000.0, "current_price_source": "moex_iss", "is_blocked": False},  # замещайка — по снапшоту
    {"ticker": "RU000A1GONE", "isin": "RU000A1GONE", "asset_type": "bond", "account": "main", "qty": 5.0, "current_price": 90.0,
     "nominal": 1000.0, "nominal_currency": "RUB", "accrued_int": 1.0, "value_rub": 4600.0, "current_price_source": "moex_iss", "is_blocked": False},    # нет в котировках
    {"ticker": "RU000A1BLCK", "isin": "RU000A1BLCK", "asset_type": "bond", "account": "main", "qty": 2.0, "current_price": 50.0,
     "nominal": 1000.0, "nominal_currency": "RUB", "accrued_int": 0.0, "value_rub": 1000.0, "current_price_source": "moex_iss", "is_blocked": True},      # заблокирована
]
bq = shifted_quotes(bsyn)
bq["items"]["SU26207RMFS9"] = {"price": 98.975, "price_kind": "last", "lot_size": 1, "board": "TQOB", "ts": "2026-10-14 11:00:00", "prev_close": 98.93,
                               "isin": "RU000A0JS3W6", "accrued_int": 22.11, "face_value": 1000, "face_unit": "SUR"}
bq["items"]["RU000A1CORP"] = {"price": 100.2, "price_kind": "market", "lot_size": 1, "board": "TQCB", "ts": "2026-10-14 11:00:00", "prev_close": 100.0,
                              "isin": "RU000A1CORP", "accrued_int": 6.25, "face_value": 800, "face_unit": "SUR"}   # номинал амортизировался
bq["items"]["RU000A10DQB6"] = {"price": 98.762, "price_kind": "market", "lot_size": 1, "board": "TQOB", "ts": "2026-10-14 11:00:00", "prev_close": 99.36,
                               "isin": "RU000A10DQB6", "accrued_int": 1445.39, "face_value": 10000, "face_unit": "CNY", "currency_id": "SUR"}
bq["fx"] = {"USD": 80.0, "EUR": 90.0, "CNY": 11.5, "date": "2026-10-14"}
bq["items"]["RU000A1BLCK"] = {"price": 60.0, "price_kind": "last", "lot_size": 1, "board": "TQCB", "ts": "2026-10-14 11:00:00", "prev_close": 50.0,
                              "isin": "RU000A1BLCK", "accrued_int": 0.0, "face_value": 1000, "face_unit": "SUR"}
bsp, bqp = tmp / "snap_b.json", tmp / "quotes_b.json"
bsp.write_text(json.dumps(bsyn, ensure_ascii=False), encoding="utf-8")
bqp.write_text(json.dumps(bq, ensure_ascii=False), encoding="utf-8")
bpy = apply_quotes(json.loads(bsp.read_text(encoding="utf-8")), bq)
bjs = run_js_apply(bsp, bqp, GATES, CONDS)
d = snap_diff(bpy, bjs["snap"])
check("облигации: apply_quotes Py = applyQuotes JS по всем полям", not d, "; ".join(d[:6]))
BH = {h["ticker"]: h for h in bpy["holdings"]}
BH0 = {h["ticker"]: h for h in bsyn["holdings"]}
ofz, corp = BH["RU000A0JS3W6"], BH["RU000A1CORP"]
check("облигация по ISIN: value = qty × (цена/100 × номинал + НКД) котировки, moex_live",
      ofz["current_price_source"] == "moex_live" and ofz["current_price"] == 98.975 and ofz["accrued_int"] == 22.11
      and abs(ofz["value_rub"] - 100 * (98.975 / 100 * 1000 + 22.11)) < 0.01, ofz)
check("облигация по SECID с амортизированным номиналом: берётся номинал котировки",
      corp["nominal"] == 800 and abs(corp["value_rub"] - 7 * (100.2 / 100 * 800 + 6.25)) < 0.01, corp)
fxb = BH["RU000A10DQB6"]
check("валютная облигация: value = qty × (цена/100 × номинал × курс ЦБ + НКД в ₽), moex_live",
      fxb["current_price_source"] == "moex_live"
      and abs(fxb["value_rub"] - 3 * (98.762 / 100 * 10000 * 11.5 + 1445.39)) < 0.01, fxb)
check("заблокированная и без котировки — по снапшоту",
      all(BH[t] == BH0[t] for t in ("RU000A1GONE", "RU000A1BLCK")))
lqb = bpy["live_quotes"]
check("missing_bonds: только пропавшая; заблокированные молча; в missing облигаций нет; fx_date — дата курса ЦБ",
      lqb["missing_bonds"] == ["RU000A1GONE"] and sorted(lqb["applied_bonds"]) == ["RU000A0JS3W6", "RU000A10DQB6", "RU000A1CORP"]
      and not any(t.startswith("RU000") for t in lqb["missing"]) and lqb.get("fx_date") == "2026-10-14", lqb)
# нет курса / НКД не в рублях: валютная — в missing_bonds, остальное без изменений; Py = JS
for tag, mut in (("нет блока fx", lambda q: q.pop("fx")),
                 ("currency_id CNY (НКД не в рублях)", lambda q: q["items"]["RU000A10DQB6"].update(currency_id="CNY"))):
    q2 = copy.deepcopy(bq)
    mut(q2)
    q2p = tmp / "quotes_b2.json"
    q2p.write_text(json.dumps(q2, ensure_ascii=False), encoding="utf-8")
    p2 = apply_quotes(json.loads(bsp.read_text(encoding="utf-8")), q2)
    j2 = run_js_apply(bsp, q2p, GATES, CONDS)
    h2 = {h["ticker"]: h for h in p2["holdings"]}
    check(f"валютная облигация, {tag}: missing_bonds, по снапшоту, без fx_date; Py = JS",
          "RU000A10DQB6" in p2["live_quotes"]["missing_bonds"] and h2["RU000A10DQB6"] == BH0["RU000A10DQB6"]
          and "fx_date" not in p2["live_quotes"] and not snap_diff(p2, j2["snap"]), p2["live_quotes"])
bb, bb0 = bpy["balance_summary"], bsyn["balance_summary"]
d_main_b = sum(BH[t]["value_rub"] - BH0[t]["value_rub"] for t in BH if BH[t].get("account") == "main")
d_iis_b = sum(BH[t]["value_rub"] - BH0[t]["value_rub"] for t in BH if BH[t].get("account") != "main")
check("облигации сдвигают NAV и ИИС как акции (ΣΔ по счетам)",
      abs(bb["total_current_rub_excl_iis"] - (bb0["total_current_rub_excl_iis"] + d_main_b)) < 0.02
      and abs(bb["iis_balance_rub"] - (bb0["iis_balance_rub"] + d_iis_b)) < 0.02)

shutil.rmtree(tmp, ignore_errors=True)
print(f"\nrebalance_parity: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
