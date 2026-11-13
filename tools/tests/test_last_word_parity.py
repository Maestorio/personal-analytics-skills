#!/usr/bin/env python3
"""Паритет модуля (б) схемы данных: «последнее слово» по бумаге и статус гейта.

Две реализации одних правил: `_shared-references/last_word.py` (скрипты скиллов, советник, движок «Сейчас» в
`gate_aware_sizing.py`, проверка бэкфилла) и `tools/assets/last-word.js` (`window.LW`, вьюер и `rebalance-engine.js`).
Тест:

  1. синтетический контекст (решения decision@1 проходят валидатор, справочник security-attrs@1 тоже) — по бумаге на
     случай schema.md §3.5: обзор новее решения меняет вердикт, но не долю и срок; решение новее обзора; истечение
     срока; пауза докупки; IPO-пауза по справочнику; divested; new_position; review_needed только от обзора новее
     решения; конфликт открыт / закрыт подтверждением / правкой плана новее конфликта / сделкой; «план против
     решения»; фонд и облигация — gate.applicable false; исполнение сделкой (правило 13, по последнему слову — решение или
     обзор): TRIM + продажа после решения, до решения, покупка после решения; SELL + уход из снапшота; HOLD + продажа; обзор
     «сократить» + продажа, обзор «докупать» + покупка, обзор «сократить» + покупка — null; без last_sell_at — null;
  2. проверяет случаи на выдаче Python при нескольких today (до и после сроков) — паритет переносит их на JS;
  3. Python и JS на тех же входах при всех today и на крайних входах — JSON с сортировкой ключей байт в байт;
  4. сторожа: текст правил в докстринге Python = шапке JS; `?v=` у last-word.js в странице = md5[:8], подключён после
     conditions-merge.js и до движка; JS без DOM и сети;
  5. самопроверка: JS с изменённым правилом (пауза докупки на день длиннее; признак исполнения у любого направления,
     кроме «вверх») обязан разойтись.

Нужен node; без node — честный пропуск, не зелёный.
Запуск: python3 tools/tests/test_last_word_parity.py
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "_shared-references"))

import ds_schemas as ds  # noqa: E402
import last_word as lw  # noqa: E402

JS = REPO / "tools/assets/last-word.js"
CLJS = REPO / "tools/assets/codelists.js"
HTML = REPO / "tools/portfolio-integrated-viewer.html"
NODE = shutil.which("node")

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}" + (f"\n    → {detail}" if detail else ""))


def dump(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def T(d, hm="00:00"):
    return f"{d}T{hm}:00+03:00"


def dec(key, day, verdict, *, hm="10:00", review_by=None, target=None, note="почему", conf=None,
        created=(), resolved=(), kind="backfill"):
    return {"schema_version": "decision@1", "id": f"{day}T{hm.replace(':', '')}-{key}", "key": key,
            "verdict": verdict, "target_pct": target, "review_by": review_by, "note": note, "confidence": conf,
            "conditions_created": list(created), "conditions_resolved": list(resolved),
            "source": {"kind": kind, "doc": None, "mode_codes": [], "stress_id": None},
            "author": "owner", "recorded_at": T(day, hm)}


def rev(day, verdict, *, hm="00:00", flag=None, conf=0.55, basis="обзор недели"):
    r = {"review_date": day, "recorded_at": T(day, hm), "advisor_verdict": verdict,
         "advisor_verdict_confidence": conf, "advisor_verdict_basis": basis,
         "doc": f"weekly-review-stock-{day}.yaml"}
    if flag is not None:
        r["gate_review_required"] = flag
    return r


DECISIONS = [
    dec("REVN", "2026-10-01", "ADD", review_by="2026-11-20", target=4.5, conf=0.7, created=["c-1"]),
    dec("DECN", "2026-10-20", "TRIM", review_by="2026-12-01", target=1.5),
    dec("AGE", "2026-08-01", "HOLD", review_by="2026-10-25"),
    dec("AGE0", "2026-08-01", "HOLD"),                         # срок null → recorded_at + 60 дней = 2026-09-30
    dec("COOL", "2026-10-20", "BUY", review_by="2026-12-20"),
    dec("COOL2", "2026-10-05", "ADD", review_by="2026-12-20"),
    dec("COOL2", "2026-10-25", "HOLD", review_by="2026-12-20"),  # пауза от BUY/ADD, даже если новейшее — HOLD
    dec("IPO", "2026-10-01", "HOLD", review_by="2026-12-20"),
    dec("SOLD", "2026-09-01", "SELL", review_by="2026-11-01"),
    dec("NEEDOLD", "2026-10-20", "HOLD", review_by="2026-12-20"),
    dec("NEEDNEW", "2026-10-01", "HOLD", review_by="2026-12-20"),
    dec("FBDEC", "2026-10-25", "BUY", review_by="2026-12-20"),
    dec("CONF", "2026-10-01", "ADD", review_by="2026-12-20"),
    dec("CONFOK", "2026-10-01", "ADD", review_by="2026-12-20"),
    dec("CONFPL", "2026-10-01", "ADD", review_by="2026-12-20"),
    dec("CONFTR", "2026-10-01", "ADD", review_by="2026-12-20"),
    dec("CONFDD", "2026-10-01", "HOLD", review_by="2026-12-20"),
    dec("CONFDD", "2026-10-20", "TRIM", review_by="2026-12-20"),  # решение сменило своё — не конфликт
    dec("PLAN", "2026-10-10", "TRIM", review_by="2026-12-20"),
    dec("FUND", "2026-10-10", "ADD", review_by="2026-12-20"),
    dec("RU000A106EP1", "2026-10-10", "HOLD_TO_MAT", review_by="2026-12-20"),
    dec("TIE", "2026-10-20", "HOLD", hm="00:00", review_by="2026-12-20"),
    dec("EXTR", "2026-10-20", "TRIM", review_by="2026-12-20"),     # правило 13: продажа после решения
    dec("EXTRB", "2026-10-20", "TRIM", review_by="2026-12-20"),    # продажа до решения
    dec("EXTRBUY", "2026-10-20", "TRIM", review_by="2026-12-20"),  # после решения — покупка, не продажа
    dec("EXSELL", "2026-10-20", "SELL", review_by="2026-12-20"),   # ушла из снапшота после решения
    dec("EXHOLD", "2026-10-20", "HOLD", review_by="2026-12-20"),   # продажа при HOLD — не исполнение
    # правило 11 (R31): «привести к плану» — направление по знаку отклонения факта от плана с допуском
    dec("BALOVER", "2026-10-20", "TRIM", review_by="2026-12-20"),   # перевес + «сократить» — плашки нет
    dec("BALUNDER", "2026-10-20", "TRIM", review_by="2026-12-20"),  # недобор + «сократить» — плашка up/down
    dec("BALIN", "2026-10-20", "TRIM", review_by="2026-12-20"),     # внутри допуска + «сократить» — flat/down
    dec("BALEDGE", "2026-10-20", "TRIM", review_by="2026-12-20"),   # ровно на границе допуска — внутри (flat)
    dec("BALNOFACT", "2026-10-20", "TRIM", review_by="2026-12-20"), # нет факта — направления нет, плашки нет
    dec("BUYTRIM", "2026-10-20", "TRIM", review_by="2026-12-20"),   # «докупать» против «сократить» — плашка
    dec("DECEX", "2026-10-23", "TRIM", review_by="2026-12-20"),     # как MDMG: решение «сократить», продажа, затем обзор HOLD
    # правило 7 (11.11): пауза — от первой покупки после решения BUY/ADD
    dec("COOLNB", "2026-10-20", "ADD", review_by="2026-12-20"),   # решение без покупки — паузы нет
    dec("COOLPRE", "2026-10-20", "ADD", review_by="2026-12-20"),  # покупка ДО решения не считается
    dec("COOLMANY", "2026-10-10", "BUY", review_by="2026-12-20"), # три покупки: пауза от первой после решения
    dec("COOLLAST", "2026-10-15", "ADD", review_by="2026-12-20"), # buys_at нет — last_buy_at
]
REVIEWS = {
    "REVN": [rev("2026-10-14", "HOLD", conf=0.6, basis="обзор: держать")],
    "DECN": [rev("2026-10-14", "HOLD")],
    "NEEDOLD": [rev("2026-10-14", "HOLD", flag=True)],         # флаг старше решения — не review_needed
    "NEEDNEW": [rev("2026-10-14", "HOLD", flag=True), rev("2026-10-21", "HOLD", flag=False)],
    "NEEDNODEC": [rev("2026-10-21", "HOLD", flag=True)],       # держимая бумага без решения, флаг → review_needed
    "CONF": [rev("2026-10-14", "TRIM")],                       # решение ↑, обзор ↓ — открыт
    "CONFOK": [rev("2026-10-14", "TRIM"), rev("2026-10-21", "SELL")],   # подтверждён следующим обзором
    "CONFPL": [rev("2026-10-14", "TRIM")],
    "CONFTR": [rev("2026-10-14", "TRIM")],
    "TIE": [rev("2026-10-20", "TRIM")],                        # равное время — решение новее обзора
    "DECEX": [rev("2026-10-28", "HOLD")],
    "REVDOWN": [rev("2026-10-20", "TRIM")],                    # правило 13 (11): обзор вниз + продажа после
    "REVUP": [rev("2026-10-20", "BUY")],                       # обзор вверх + покупка после
    "REVDNBUY": [rev("2026-10-20", "TRIM")],                   # обзор вниз + только покупка — null
    "NOVERD": [{"review_date": "2026-10-14", "recorded_at": T("2026-10-14"), "advisor_verdict": None},
               {"review_date": "2026-10-15", "recorded_at": None, "advisor_verdict": "HOLD"}],
}
ATTRS = {"schema_version": "security-attrs@1", "by_key": {
    "IPO": {"ticker_class": "ipo", "listed_at": "2025-02-28", "note": None,
            "updated_at": T("2026-10-31"), "updated_by": "owner"},
    "FBIPO": {"ticker_class": "ipo", "listed_at": "2026-06-30", "note": None,
              "updated_at": T("2026-10-31"), "updated_by": "owner"},
    "OLDIPO": {"ticker_class": "ipo", "listed_at": "2020-01-15", "note": None,
               "updated_at": T("2026-10-31"), "updated_by": "owner"},
    "COOL": {"ticker_class": "mid_cap", "listed_at": "2023-01-01", "note": None,
             "updated_at": T("2026-10-31"), "updated_by": "owner"},
}}
STOCKS = ["REVN", "DECN", "AGE", "AGE0", "COOL", "COOL2", "IPO", "SOLD", "NEEDOLD", "NEEDNEW", "NEEDNODEC",
          "FB", "FBDEC", "FBIPO", "OLDIPO", "CONF", "CONFOK", "CONFPL", "CONFTR", "CONFDD", "PLAN", "TIE", "HELD",
          "NOVERD", "EXTR", "EXTRB", "EXTRBUY", "EXSELL", "EXHOLD",
          "BALOVER", "BALUNDER", "BALIN", "BALEDGE", "BALNOFACT", "BUYTRIM", "REVDOWN", "REVUP", "REVDNBUY", "DECEX",
          "COOLNB", "COOLPRE", "COOLMANY", "COOLLAST"]
CTX = {
    "decisions": DECISIONS, "reviews": REVIEWS, "security_attrs": ATTRS,
    "snapshot_keys": [k for k in STOCKS if k not in ("SOLD", "FB", "FBDEC", "FBIPO", "EXSELL")] + ["FUND", "RU000A106EP1"],
    "stock_keys": STOCKS,
    "first_buy": ["FB", "FBDEC", "FBIPO"],
    "plan": {"CONFPL": {"user_plan": "KEEP", "user_status": "NOTED", "changed_at": T("2026-10-16", "12:00")},
             "CONFTR": {"user_plan": "KEEP", "user_status": None, "changed_at": T("2026-10-10")},  # до конфликта
             "PLAN": {"user_plan": "WAIT", "user_status": None, "changed_at": None},
             "REVN": {"user_plan": "BUY", "user_status": None, "changed_at": None},
             "FUND": {"user_plan": "SELL", "user_status": None, "changed_at": None},
             "BALOVER": {"user_plan": "BALANCE", "changed_at": None, "fact_pct": 6.34, "plan_pct": 5.0},
             "BALUNDER": {"user_plan": "BALANCE", "changed_at": None, "fact_pct": 3.5, "plan_pct": 5.0},
             "BALIN": {"user_plan": "BALANCE", "changed_at": None, "fact_pct": 5.4, "plan_pct": 5.0},
             "BALEDGE": {"user_plan": "BALANCE", "changed_at": None, "fact_pct": 6, "plan_pct": 5},
             "BALNOFACT": {"user_plan": "BALANCE", "changed_at": None, "fact_pct": None, "plan_pct": 5.0},
             "BUYTRIM": {"user_plan": "BUY", "changed_at": None, "fact_pct": 6.34, "plan_pct": 5.0}},
    "last_trade_at": {"CONFTR": T("2026-10-17", "23:59"), "CONF": T("2026-10-13"),   # у CONF — до конфликта
                      "EXTR": T("2026-10-22"), "EXTRB": T("2026-10-19"), "EXTRBUY": T("2026-10-22"),
                      "EXSELL": T("2026-10-23"), "EXHOLD": T("2026-10-22")},
    "last_buy_at": {"REVUP": T("2026-10-22"), "REVDNBUY": T("2026-10-22"), "EXTRBUY": T("2026-10-22"),
                    "COOLLAST": T("2026-10-18"), "COOLMANY": T("2026-10-24")},
    # правило 7: все покупки (дни снапшотов); у COOL — в день решения (считается), у COOLMANY — до решения и две после
    "buys_at": {"COOL": [T("2026-10-20")], "COOL2": [T("2026-10-05")], "COOLNB": [], "COOLPRE": [T("2026-10-19")],
                "COOLMANY": [T("2026-10-24"), T("2026-10-08"), T("2026-10-12")]},
    "last_sell_at": {"DECEX": T("2026-10-27"), "REVDOWN": T("2026-10-22"), "EXTR": T("2026-10-22"), "EXTRB": T("2026-10-19"), "EXSELL": T("2026-10-23"),
                     "EXHOLD": T("2026-10-22"), "CONFTR": T("2026-10-17", "23:59"),
                     # правило 14: облигации и фонд ушли из снапшота
                     "RU000A107795": T("2026-11-03"), "RU000A10SOLD": T("2026-10-20"), "FUNDGONE": T("2026-10-21")},
    # правило 14: даты погашения облигаций (считает вызывающий из снапшотов и обзора облигаций)
    "maturities": {"RU000A107795": "2026-10-30", "RU000A10SOLD": "2027-05-01", "RU000A10OLDM": "2026-09-01",
                   "RU000A106EP1": "2028-01-01"},
}
# правило 14: погашена (ушла в дату ≥ погашения), продана до погашения, ушла без даты продажи с прошедшим погашением,
# фонд ушёл — «продан»; в снапшоте их нет, гейта у них нет
CTX["reviews"] = dict(CTX["reviews"], **{
    "RU000A107795": [rev("2026-10-28", "HOLD_TO_MAT")], "RU000A10SOLD": [rev("2026-10-14", "HOLD")],
    "RU000A10OLDM": [rev("2026-08-01", "HOLD_TO_MAT")], "FUNDGONE": [rev("2026-10-14", "HOLD")],
    "REVNEVER": [rev("2026-10-14", "HOLD")]})
TODAYS = ["2026-10-24", "2026-10-26", "2026-10-31", "2026-11-10", "2026-11-25", "2027-03-01"]

print("-- 0. Фикстуры проходят валидаторы --")
bad = [(d["id"], e) for d in DECISIONS for e in ds.validate_decision(d)]
check("решения — decision@1, справочник — security-attrs@1",
      not bad and ds.validate_security_attrs(ATTRS) == [], str(bad[:3]) + str(ds.validate_security_attrs(ATTRS)[:3]))


def C(today):
    return {c["key"]: c for c in lw.cards(dict(CTX, today=today))}


R = {t: C(t) for t in TODAYS}
r = R["2026-10-31"]
g = {k: v["gate"] for k, v in r.items()}

print("-- 1. Случаи schema.md §3.5 на выдаче Python --")
CASES = [
    ("обзор новее решения: вердикт, уверенность и основание — из обзора, доля и срок — из решения",
     (r["REVN"]["verdict"], r["REVN"]["confidence"], r["REVN"]["basis"], r["REVN"]["verdict_source"]["kind"],
      r["REVN"]["target_pct"], r["REVN"]["review_by"], r["REVN"]["decision_verdict"], r["REVN"]["conditions_created"],
      g["REVN"]["status"]) == ("HOLD", 0.6, "обзор: держать", "review", 4.5, "2026-11-20", "ADD", ["c-1"],
                               "reviewed_buy_more")),
    ("решение новее обзора: вердикт решения, источник decision, обе даты на карточке",
     (r["DECN"]["verdict"], r["DECN"]["verdict_source"]["kind"], r["DECN"]["decision_recorded_at"],
      r["DECN"]["review_recorded_at"]) == ("TRIM", "decision", T("2026-10-20", "10:00"), T("2026-10-14"))),
    ("равное время: решение новее обзора", r["TIE"]["verdict"] == "HOLD" and r["TIE"]["verdict_source"]["kind"] == "decision"),
    ("истечение срока: review_by < today → review_aging, блок «gate:review_aging»",
     (R["2026-10-24"]["AGE"]["gate"]["status"], g["AGE"]["status"], g["AGE"]["expired"], g["AGE"]["expires_on"],
      g["AGE"]["reasons"]) == ("reviewed_keep", "review_aging", True, "2026-10-25", ["gate:review_aging"])),
    ("в день срока ещё не истёк (review_by = today)", R["2026-10-24"]["AGE"]["gate"]["expired"] is False
     and lw.card(dict(CTX, today="2026-10-25"), "AGE")["gate"]["expired"] is False),
    ("срок null → recorded_at + review_days", g["AGE0"]["expires_on"] == "2026-09-30" and g["AGE0"]["status"] == "review_aging"),
    ("пауза докупки 21 день от решения BUY: до 2026-11-10, в этот день уже нет",
     (g["COOL"]["add_cooldown_until"], g["COOL"]["reasons"], g["COOL"]["blocking"],
      R["2026-11-10"]["COOL"]["gate"]["add_cooldown_until"]) == ("2026-11-10", ["add_cooldown:2026-11-10"], True, None)),
    ("пауза докупки: решение ADD без покупки — паузы нет; покупка до решения не считается",
     (g["COOLNB"]["add_cooldown_until"], g["COOLNB"]["reasons"], g["COOLPRE"]["add_cooldown_until"],
      g["COOLPRE"]["blocking"]) == (None, [], None, False)),
    ("пауза докупки — 21 день от ПЕРВОЙ покупки после решения (не от решения, не от последней покупки)",
     R["2026-10-24"]["COOLMANY"]["gate"]["add_cooldown_until"] == "2026-11-02"
     and R["2026-11-10"]["COOLMANY"]["gate"]["add_cooldown_until"] is None),
    ("пауза докупки: без buys_at — по last_buy_at после решения (18.10 + 21 = 08.11)",
     g["COOLLAST"]["add_cooldown_until"] == "2026-11-08" and g["COOLLAST"]["reasons"] == ["add_cooldown:2026-11-08"]),
    ("пауза докупки — от новейшего BUY/ADD, даже если новейшее решение HOLD",
     R["2026-10-24"]["COOL2"]["gate"]["add_cooldown_until"] == "2026-10-26" and g["COOL2"]["add_cooldown_until"] is None),
    ("IPO-пауза по справочнику: ipo + listed_at 2025-02-28 → до 2027-02-28, возраст 6 кв., при любом вердикте",
     (g["IPO"]["ipo_pause_until"], g["IPO"]["reasons"], g["IPO"]["status"]) ==
     ("2027-02-28", ["ipo_gate:6q"], "reviewed_keep")
     and R["2027-03-01"]["IPO"]["gate"]["ipo_pause_until"] is None),
    ("IPO-пауза и у первой покупки; старое IPO и не-IPO класс — без паузы",
     g["FBIPO"]["reasons"] == ["gate:new_position", "ipo_gate:1q"] and g["OLDIPO"]["ipo_pause_until"] is None
     and g["COOL"]["ipo_pause_until"] is None),
    ("divested: бумаги нет в снапшоте и не первая покупка — без причин",
     (g["SOLD"]["status"], g["SOLD"]["reasons"], g["SOLD"]["blocking"]) == ("divested", [], False)),
    ("new_position: первая покупка без решения; с решением — по вердикту",
     (g["FB"]["status"], g["FB"]["reasons"], g["FBDEC"]["status"]) ==
     ("new_position", ["gate:new_position"], "reviewed_buy_more")),
    ("держимая бумага без решения не блокируется", (g["HELD"]["status"], g["HELD"]["blocking"]) == (None, False)),
    ("review_needed — только от обзора с флагом новее решения",
     (g["NEEDOLD"]["status"], g["NEEDNEW"]["status"], g["NEEDNODEC"]["status"]) ==
     ("reviewed_keep", "review_needed", "review_needed") and g["NEEDNEW"]["reasons"] == ["gate:review_needed"]),
    ("строка обзора без recorded_at или вердикта — не источник", r["NOVERD"]["verdict"] is None
     and r["NOVERD"]["verdict_source"] is None),
    ("конфликт: решение ↑, обзор ↓ новее — открыт, у CONF сделка до конфликта не закрывает",
     r["CONF"]["conflict"] is not None and r["CONF"]["conflict"]["open"] is True
     and (r["CONF"]["conflict"]["source"]["kind"], r["CONF"]["conflict"]["against"]["kind"]) == ("review", "decision")),
    ("конфликт закрыт подтверждением следующим источником",
     (r["CONFOK"]["conflict"]["open"], r["CONFOK"]["conflict"]["closed_by"], r["CONFOK"]["conflict"]["closed_at"])
     == (False, "confirmed", T("2026-10-21"))),
    ("конфликт закрыт правкой плана новее конфликта",
     (r["CONFPL"]["conflict"]["open"], r["CONFPL"]["conflict"]["closed_by"]) == (False, "plan")),
    ("конфликт закрыт сделкой; правка плана до конфликта не закрывает",
     (r["CONFTR"]["conflict"]["open"], r["CONFTR"]["conflict"]["closed_by"]) == (False, "trade")),
    ("смена мнения внутри одного вида и совпадение направлений — не конфликт",
     r["CONFDD"]["conflict"] is None and r["AGE"]["conflict"] is None),
    ("конфликт в обе стороны: обзор новее решения (REVN) и решение новее обзора (DECN)",
     (r["REVN"]["conflict"]["source"]["kind"], r["DECN"]["conflict"]["source"]["kind"],
      r["DECN"]["conflict"]["open"]) == ("review", "decision", True)),
    ("план против решения: план «ждать» (flat) против TRIM (down)",
     r["PLAN"]["plan_vs_decision"] == {"user_plan": "WAIT", "plan_direction": "flat", "verdict": "TRIM",
                                       "direction": "down", "source_kind": "decision"}),
    ("план совпал по направлению — плашки нет; REVN «докупать» против HOLD обзора — есть",
     r["DECN"]["plan_vs_decision"] is None and r["REVN"]["plan_vs_decision"]["source_kind"] == "review"),
    ("фонд и облигация: gate.applicable false, вердикт и плашка плана считаются",
     (g["FUND"]["applicable"], g["FUND"]["status"], g["RU000A106EP1"]["applicable"], r["FUND"]["verdict"],
      r["FUND"]["plan_vs_decision"]["direction"]) == (False, None, False, "ADD", "up")),
    ("правило 11: «привести к плану» при перевесе больше допуска = down — против «сократить» плашки нет",
     r["BALOVER"]["plan_vs_decision"] is None and r["BALOVER"]["direction"] == "down"),
    ("правило 11: «привести к плану» при недоборе = up — против «сократить» плашка",
     (r["BALUNDER"]["plan_vs_decision"] or {}).get("plan_direction") == "up"),
    ("правило 11: «привести к плану» внутри допуска и на границе = flat — против «сократить» плашка",
     (r["BALIN"]["plan_vs_decision"] or {}).get("plan_direction") == "flat"
     and (r["BALEDGE"]["plan_vs_decision"] or {}).get("plan_direction") == "flat"),
    ("правило 11: «привести к плану» без факта — направления нет, плашки нет",
     r["BALNOFACT"]["plan_vs_decision"] is None),
    ("правило 11: «докупать» против «сократить» — плашка есть, факт и план не читаются",
     r["BUYTRIM"]["plan_vs_decision"] == {"user_plan": "BUY", "plan_direction": "up", "verdict": "TRIM",
                                          "direction": "down", "source_kind": "decision"}),
]
CASES += [
    ("исполнение сделкой: TRIM + продажа после решения — время продажи; гейт, срок и причины те же, что без продажи",
     r["EXTR"]["executed_by_trade_at"] == T("2026-10-22")
     and r["EXTR"]["gate"] == lw.card(dict(CTX, today="2026-10-31", last_sell_at={}), "EXTR")["gate"]),
    ("исполнение сделкой: TRIM + продажа до решения — null", r["EXTRB"]["executed_by_trade_at"] is None),
    ("исполнение сделкой: TRIM + покупка после решения — null", r["EXTRBUY"]["executed_by_trade_at"] is None),
    ("исполнение сделкой: SELL + уход из снапшота после решения — время ухода, статус divested",
     (r["EXSELL"]["executed_by_trade_at"], g["EXSELL"]["status"]) == (T("2026-10-23"), "divested")),
    ("исполнение сделкой: HOLD + продажа — null; источника нет — null",
     r["EXHOLD"]["executed_by_trade_at"] is None and r["HELD"]["executed_by_trade_at"] is None),
    ("исполнение сделкой (11, 03.11): последнее слово — обзор «сократить», продажа после него — время продажи, вид review",
     (r["CONFTR"]["executed_by_trade_at"], r["CONFTR"]["executed_source_kind"]) == (T("2026-10-17", "23:59"), "review")
     and (r["REVDOWN"]["executed_by_trade_at"], r["REVDOWN"]["executed_source_kind"]) == (T("2026-10-22"), "review")),
    ("исполнение сделкой (11): обзор «докупать», покупка после него — время покупки; обзор «сократить» и покупка — null",
     (r["REVUP"]["executed_by_trade_at"], r["REVUP"]["executed_source_kind"]) == (T("2026-10-22"), "review")
     and (r["REVDNBUY"]["executed_by_trade_at"], r["REVDNBUY"]["executed_source_kind"]) == (None, None)),
    ("исполнение сделкой: решение «сократить» и продажа — вид decision; decision_executed_at то же время",
     r["EXTR"]["executed_source_kind"] == "decision" and r["EXTR"]["decision_executed_at"] == T("2026-10-22")),
    ("исполнение сделкой (как MDMG): решение TRIM 23.10, продажа 27.10, обзор HOLD 28.10 — по последнему слову null, "
     "decision_executed_at = продажа; у обзора без решения decision_executed_at null",
     (r["DECEX"]["executed_by_trade_at"], r["DECEX"]["decision_executed_at"]) == (None, T("2026-10-27"))
     and r["REVDOWN"]["decision_executed_at"] is None),
    ("исполнение сделкой: last_sell_at нет в ctx — null без падения",
     lw.card({k: v for k, v in CTX.items() if k != "last_sell_at"} | {"today": "2026-10-31"}, "EXTR")
     ["executed_by_trade_at"] is None),
]
CASES += [
    ("«есть в портфеле»: держимая акция, облигация и фонд — held, без даты ухода",
     [(r[k]["held"], r[k]["left_at"], r[k]["left_kind"]) for k in ("HELD", "RU000A106EP1", "FUND")]
     == [(True, None, None)] * 3),
    ("«есть в портфеле»: облигация ушла в день погашения или позже — redeemed с датой ухода; гейта нет",
     (r["RU000A107795"]["held"], r["RU000A107795"]["left_at"], r["RU000A107795"]["left_kind"],
      g["RU000A107795"]["applicable"], g["RU000A107795"]["status"]) == (False, T("2026-11-03"), "redeemed", False, None)),
    ("«есть в портфеле»: облигация ушла до погашения — sold; фонд — sold",
     (r["RU000A10SOLD"]["left_kind"], r["RU000A10SOLD"]["left_at"], r["FUNDGONE"]["left_kind"], r["FUNDGONE"]["held"])
     == ("sold", T("2026-10-20"), "sold", False)),
    ("«есть в портфеле»: ушла без даты продажи, погашение прошло — redeemed, left_at null",
     (r["RU000A10OLDM"]["left_at"], r["RU000A10OLDM"]["left_kind"]) == (None, "redeemed")),
    ("«есть в портфеле»: проданная акция — sold с датой ухода, divested как прежде; первая покупка — не ушла",
     (r["EXSELL"]["held"], r["EXSELL"]["left_at"], r["EXSELL"]["left_kind"], g["EXSELL"]["status"],
      r["FB"]["held"], r["FB"]["left_kind"]) == (False, T("2026-10-23"), "sold", "divested", False, None)),
    ("«есть в портфеле»: бумага, не державшаяся в известной истории (только строка обзора), — не «ушла»",
     (r["NEEDNODEC"]["held"], r["REVNEVER"]["held"], r["REVNEVER"]["left_at"], r["REVNEVER"]["left_kind"])
     == (True, False, None, None)),
    ("«есть в портфеле»: погашение ещё впереди и продажи нет — не «ушла»",
     lw.card(dict(CTX, today="2026-08-01"), "RU000A10OLDM")["left_kind"] is None),
    ("«есть в портфеле»: без дат погашения в ctx облигация — sold",
     lw.card({k: v for k, v in CTX.items() if k != "maturities"} | {"today": "2026-10-31"}, "RU000A107795")
     ["left_kind"] == "sold"),
]
for name, ok in CASES:
    check(name, ok)

print("-- 1б. Режим «без ИИ» (решение 11.11): блокируют те же статусы, что при «с ИИ»; снимает решение владельца --")
OFF = {k: v["gate"] for k, v in {c["key"]: c for c in lw.cards(dict(CTX, today="2026-10-31", ai_mode="off"))}.items()}
check("off: истёкший срок AGE блокирует как при on (reasons те же), warnings пуст",
      (OFF["AGE"]["status"], OFF["AGE"]["blocking"], OFF["AGE"]["reasons"], OFF["AGE"]["warnings"]) == ("review_aging", True, ["gate:review_aging"], [])
      and OFF["AGE"] == g["AGE"])
check("off: пауза докупки блокирует (COOL: add_cooldown), IPO-пауза блокирует (IPO: ipo_gate)",
      (OFF["COOL"]["blocking"], OFF["COOL"]["reasons"]) == (True, g["COOL"]["reasons"]) and OFF["IPO"]["blocking"]
      and OFF["IPO"]["reasons"] == g["IPO"]["reasons"] and all(x.startswith("ipo_gate") for x in OFF["IPO"]["reasons"]))
check("off: статус гейта и блок те же, что при on; первая покупка без решения (new_position) блокирует",
      all(OFF[k]["status"] == g[k]["status"] and OFF[k]["blocking"] == g[k]["blocking"] and OFF[k]["reasons"] == g[k]["reasons"] for k in g)
      and OFF["FB"]["status"] == "new_position" and (OFF["FB"]["blocking"], OFF["FB"]["warnings"]) == (True, []))
check("off и on: warnings пуст у всех (флаг noai_gate_blocks = true)",
      all(OFF[k]["warnings"] == [] for k in OFF) and all(g[k]["warnings"] == [] for k in g)
      and lw.NOAI_GATE_BLOCKS is True)
check("ai_mode не задан или не «off» — как on", lw.card(dict(CTX, today="2026-10-31", ai_mode="on"), "AGE")["gate"] == g["AGE"]
      and lw.card(dict(CTX, today="2026-10-31", ai_mode="OFF"), "AGE")["gate"] == g["AGE"])

print("-- 1в. Решение владельца с сайта при «с ИИ» (правило 9а): строже из двух --")
OW = {"stock_keys": ["O1", "O2", "O3", "O4", "O5", "O6"], "snapshot_keys": ["O1", "O2", "O3", "O5", "O6"],
      "first_buy": ["O4"], "today": "2026-10-31", "last_buy_at": {"O4": T("2026-10-30", "15:00")},
      "decisions": [
          dec("O1", "2026-08-01", "HOLD", review_by="2026-10-25"),                           # срок разбора вышел
          dec("O1", "2026-10-30", "HOLD", review_by="2026-12-30", kind="owner"),             # «Подтверждаю держать»
          dec("O2", "2026-10-01", "HOLD", review_by="2026-12-20"),                           # разбор действует
          dec("O2", "2026-10-30", "WATCH", review_by="2026-12-30", kind="owner"),            # владелец закрыл
          dec("O3", "2026-10-30", "HOLD", review_by="2026-12-30", kind="owner"),             # держимая, только владелец
          dec("O4", "2026-10-30", "BUY", review_by="2026-12-30", kind="owner"),              # первая покупка, только владелец
          dec("O5", "2026-08-01", "HOLD", review_by="2026-10-25"),
          dec("O5", "2026-10-29", "HOLD", review_by="2026-11-29", kind="owner"),
          dec("O5", "2026-10-30", "TRIM", review_by="2026-12-30"),                           # новее владельца — разбор
          dec("O6", "2026-10-01", "HOLD", review_by="2026-12-20"),
          dec("O6", "2026-10-30", "HOLD", review_by="2026-12-30", kind="owner")]}            # ничего не закрыто
OWG = {c["key"]: c["gate"] for c in lw.cards(OW)}
OWF = {c["key"]: c["gate"] for c in lw.cards(dict(OW, ai_mode="off"))}
check("on: срок разбора вышел, новее «держать» владельца — блок, статус и срок РАЗБОРА, признак owner_pending_review",
      (OWG["O1"]["blocking"], OWG["O1"]["reasons"], OWG["O1"]["status"], OWG["O1"]["expires_on"], OWG["O1"]["expired"],
       OWG["O1"]["owner_pending_review"]) == (True, ["gate:review_aging"], "review_aging", "2026-10-25", True, True))
check("on: вердикт, цель, review_by и источник карточки — из новейшего решения (владельца), меняется только gate",
      (lambda c: (c["verdict"], c["review_by"], c["decision_id"], c["verdict_source"]["kind"]))(
          {c["key"]: c for c in lw.cards(OW)}["O1"]) == ("HOLD", "2026-12-30", "2026-10-30T1000-O1", "decision"))
check("off: тот же набор — правило 9а не действует: «держать» владельца как любое решение снимает блок срока, признак false",
      (OWF["O1"]["blocking"], OWF["O1"]["reasons"], OWF["O1"]["warnings"], OWF["O1"]["owner_pending_review"],
       OWF["O1"]["status"]) == (False, [], [], False, "reviewed_keep"))
check("on: владелец закрыл («наблюдать») поверх действующего «держать» — блок по решению владельца, не «ожидание разбора»",
      (OWG["O2"]["blocking"], OWG["O2"]["reasons"], OWG["O2"]["status"], OWG["O2"]["owner_pending_review"])
      == (True, ["gate:reviewed_under_review"], "reviewed_under_review", False))
check("on: держимая бумага только с решениями владельца — как бумага без решения, не блок (правило 6г)",
      (OWG["O3"]["blocking"], OWG["O3"]["status"], OWG["O3"]["owner_pending_review"]) == (False, "reviewed_keep", False))
check("on: первая покупка только с решением владельца — блок «нужен разбор» (new_position), срока нет",
      (OWG["O4"]["blocking"], OWG["O4"]["reasons"], OWG["O4"]["status"], OWG["O4"]["expires_on"],
       OWG["O4"]["owner_pending_review"]) == (True, ["gate:new_position", "add_cooldown:2026-11-20"], "new_position", None, True))
check("off: первая покупка только с решением владельца — как любое решение: гейт не предупреждает, блок только пауза докупки",
      (OWF["O4"]["reasons"], OWF["O4"]["warnings"], OWF["O4"]["owner_pending_review"]) == (["add_cooldown:2026-11-20"], [], False))
check("on: за решением владельца идёт более новый разбор — вариант Б = А, признак false, как раньше",
      (OWG["O5"]["blocking"], OWG["O5"]["owner_pending_review"], OWG["O5"]["status"]) == (False, False, "reviewed_reduce"))
check("on: разбор действует, владелец подтвердил — открыто, как раньше",
      (OWG["O6"]["blocking"], OWG["O6"]["owner_pending_review"], OWG["O6"]["status"]) == (False, False, "reviewed_keep"))
check("on: паузы остаются из варианта А (причины без дублей, gate впереди): владелец ADD поверх устаревшего разбора",
      (lambda g_: (g_["reasons"][0], len(g_["reasons"]), g_["blocking"]))(
          lw.card(dict(OW, decisions=OW["decisions"][:1] + [dec("O1", "2026-10-30", "ADD", review_by="2026-12-30",
                                                                kind="owner")],
                       last_buy_at={"O1": T("2026-10-30", "15:00")}), "O1")["gate"])
      == ("gate:review_aging", 2, True))
check("регрессия: без решений владельца при on результат прежний, признак false у всех",
      all(x["owner_pending_review"] is False for x in g.values()) and all(x["owner_pending_review"] is False for x in OFF.values()))

print("-- 2. Паритет Python = JS --")
JS_RUNNER = r"""
const fs = require('fs');
const [mod, inPath] = process.argv.slice(1);
const LW = require(mod);
function stable(v) {
  if (Array.isArray(v)) return '[' + v.map(stable).join(',') + ']';
  if (v && typeof v === 'object') return '{' + Object.keys(v).sort().map(k => JSON.stringify(k) + ':' + stable(v[k])).join(',') + '}';
  return JSON.stringify(v === undefined ? null : v);
}
const cases = JSON.parse(fs.readFileSync(inPath, 'utf8'));
process.stdout.write(JSON.stringify(cases.map(c => stable(c.keys === undefined ? LW.cards(c.ctx) : LW.cards(c.ctx, c.keys)))));
"""


def run_js(cases, mod=JS):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(cases, fh, ensure_ascii=False)
        p = fh.name
    try:
        res = subprocess.run([NODE, "-e", JS_RUNNER, str(mod), p], capture_output=True, text=True, timeout=60)
    finally:
        Path(p).unlink(missing_ok=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip()[:600])
    return json.loads(res.stdout)


def first_diff(a, b):
    i = next((k for k in range(min(len(a), len(b))) if a[k] != b[k]), min(len(a), len(b)))
    return f"с символа {i}: py «{a[max(0, i - 80):i + 80]}» / js «{b[max(0, i - 80):i + 80]}»"


def compare(label, cases, mod=JS, report=True):
    js = run_js(cases, mod)
    bad = 0
    for c, j in zip(cases, js):
        py = dump(lw.cards(c["ctx"], c.get("keys")))
        if report:
            check(f"{label} today={c['ctx']['today']}: Python = JS", py == j, first_diff(py, j))
        bad += py != j
    return bad


edge = [
    {"ctx": {"today": "2026-10-31"}},
    {"ctx": {"today": "2026-10-31", "decisions": None, "reviews": None, "security_attrs": None, "snapshot_keys": None,
             "stock_keys": None, "first_buy": None, "plan": None, "last_trade_at": None, "last_sell_at": None,
             "last_buy_at": None, "maturities": None},
     "keys": ["X"]},
    {"ctx": {"today": "2026-10-31", "stock_keys": ["X"], "snapshot_keys": ["X"],
             "decisions": [dec("X", "2026-10-01", "ADD"), dec("X", "2026-10-01", "RED_FLAG", hm="10:01")],
             "reviews": {"X": [rev("2026-10-20", "MATURE"), dict(rev("2026-10-21", "WAT"), doc=None)]},
             "security_attrs": {"by_key": {"X": {"ticker_class": "ipo", "listed_at": None}}},
             "plan": {"X": {"user_plan": "WAIT/TRIM"}}}},
    {"ctx": {"today": "2026-03-31", "stock_keys": ["X"], "snapshot_keys": ["X"],
             "security_attrs": {"by_key": {"X": {"ticker_class": "ipo", "listed_at": "2024-03-31"}}}}},
    {"ctx": {"today": "2026-10-31", "stock_keys": ["X"], "snapshot_keys": ["X"], "keys": [],
             "decisions": [dec("X", "2026-10-01", "WATCH", review_by="2026-11-01")],
             "reviews": {"X": [rev("2026-10-02", "TRIM"), rev("2026-10-03", "TRIM")]},
             "plan": {"X": {"user_plan": "SELL", "changed_at": T("2026-10-02", "12:00")}},
             "last_trade_at": {"X": T("2026-10-02", "12:00")}}},
    {"ctx": {"today": "2026-10-31", "stock_keys": ["X"], "snapshot_keys": ["X"],
             "decisions": [dec("X", "2026-10-01", "ADD")], "reviews": {"X": [rev("2026-10-02", "TRIM")]},
             "plan": {"X": {"user_plan": "KEEP", "changed_at": T("2026-10-05")}},
             "last_trade_at": {"X": T("2026-10-05")}}, "keys": ["X", "X", "Y"]},
    {"ctx": {"today": "2026-10-31", "stock_keys": ["X"], "decisions": [dec("X", "2026-10-01", "SELL")],
             "last_sell_at": {"X": T("2026-10-01", "10:00")}}},   # продажа в ту же секунду — не позже решения
    {"ctx": {"today": "2026-10-30", "maturities": {"B": "2026-10-30", "C": "2026-10-31", "D": ""},
             "last_sell_at": {"D": ""}, "reviews": {"B": [rev("2026-10-01", "HOLD")], "C": [rev("2026-10-01", "HOLD")],
                                                    "D": [rev("2026-10-01", "HOLD")]}}},   # правило 14: в день погашения
    {"ctx": OW}, {"ctx": dict(OW, ai_mode="off")}, {"ctx": dict(OW, today="2026-10-24")},   # правило 9а
    {"ctx": dict(OW, today="2026-12-31")}, {"ctx": dict(OW, ai_mode="on", today="2026-11-25")},
]
if NODE is None:
    print("  — node не найден: паритет не проверен (пропуск — не зелёный)")
    failed += 1
else:
    compare("синтетика", [{"ctx": dict(CTX, today=t)} for t in TODAYS])
    compare("без ИИ", [{"ctx": dict(CTX, today=t, ai_mode="off")} for t in TODAYS])
    compare("по списку ключей", [{"ctx": dict(CTX, today="2026-10-31"), "keys": ["SOLD", "FB", "NOPE", "FUND"]}])
    compare("крайние", edge)
    check("крайние: неизвестный (в т.ч. прежний) вердикт — направление null; ipo без listed_at — без паузы",
          (lambda c: (c["direction"], c["decision_verdict"], c["gate"]["ipo_pause_until"], c["plan_vs_decision"]))(
              lw.card(edge[2]["ctx"], "X")) == (None, "RED_FLAG", None, None))
    check("крайние: IPO 2024-03-31 + 8 кв. = 2026-03-31 — в этот день пауза уже снята",
          lw.card(edge[3]["ctx"], "X")["gate"]["ipo_pause_until"] is None)
    check("крайние: продажа в ту же секунду, что решение SELL, — не исполнение (строго позже)",
          lw.card(edge[6]["ctx"], "X")["executed_by_trade_at"] is None)
    x5 = lw.card(edge[5]["ctx"], "X")["conflict"]
    check("крайние: план и сделка в одно время — закрытие планом (порядок confirmed, plan, trade)",
          (x5["closed_by"], x5["closed_at"]) == ("plan", T("2026-10-05")))

print("-- 3. Сторожа --")
src_py = (REPO / "_shared-references/last_word.py").read_text(encoding="utf-8")
src_js = JS.read_text(encoding="utf-8")
HEAD = "ПРАВИЛА (спецификация для JS)"
py_rules = src_py[src_py.index(HEAD):src_py.index("CLI нет:")].rstrip()
js_head = src_js[:src_js.index("*/")]
js_rules = "\n".join(l[3:] if l.startswith(" * ") else l[2:] for l in js_head[js_head.index(HEAD) - 3:].splitlines()).rstrip()
check("текст правил 1–14 (и 9а): докстринг Python = шапка JS", py_rules == js_rules and "14. " in py_rules and "ai_mode" in py_rules,
      first_diff(py_rules, js_rules))
html = HTML.read_text(encoding="utf-8")
md5 = hashlib.md5(JS.read_bytes()).hexdigest()[:8]
pos = [html.find("assets/conditions-merge.js?v="), html.find(f"assets/last-word.js?v={md5}\""),
       html.find("assets/rebalance-engine.js?v=")]
check("вьюер подключает last-word.js?v=<md5[:8]> после conditions-merge.js и до движка",
      0 <= pos[0] < pos[1] < pos[2], f"<script src=\"assets/last-word.js?v={md5}\"></script> между conditions-merge.js и rebalance-engine.js")
check("JS-близнец без DOM и сети", not any(x in src_js for x in ("document.", "fetch(", "XMLHttpRequest", "localStorage")))

print("-- 4. Самопроверка: изменённое правило в JS обязано разойтись --")
if NODE is not None:
    with tempfile.TemporaryDirectory() as t:
        shutil.copy(CLJS, Path(t) / "codelists.js")
        mut = src_js.replace("ADD_COOLDOWN_DAYS = D.add_cooldown_days", "ADD_COOLDOWN_DAYS = D.add_cooldown_days + 1")
        (Path(t) / "last-word.js").write_text(mut, encoding="utf-8")
        n = compare("мутант", [{"ctx": dict(CTX, today="2026-10-31")}], mod=Path(t) / "last-word.js", report=False)
        check("JS с паузой докупки на день длиннее расходится с Python", mut != src_js and n == 1)
        mut2 = src_js.replace('d === "up" ? "last_buy_at" : null', 'd === "up" ? null : "last_sell_at"')
        (Path(t) / "last-word.js").write_text(mut2, encoding="utf-8")
        n2 = compare("мутант 13", [{"ctx": dict(CTX, today="2026-10-31")}], mod=Path(t) / "last-word.js", report=False)
        check("JS без исполнения покупкой и с исполнением продажей у HOLD расходится с Python", mut2 != src_js and n2 == 1)
        mut5 = src_js.replace('var decEx = executed(ctx, key, decs.length ? decs[decs.length - 1] : null)[0];', 'var decEx = ex[0];')
        (Path(t) / "last-word.js").write_text(mut5, encoding="utf-8")
        n5 = compare("мутант 13 решение", [{"ctx": dict(CTX, today="2026-10-31")}], mod=Path(t) / "last-word.js", report=False)
        check("JS с decision_executed_at по последнему слову (а не по решению) расходится с Python", mut5 != src_js and n5 == 1)
        # правило 14: «есть в портфеле» только у акций (held считается лишь при gate.applicable) — обязан разойтись
        mut3 = src_js.replace('if (setOf(get(ctx, "snapshot_keys"))[key]) return [true, null, null];',
                              'if (setOf(get(ctx, "snapshot_keys"))[key] || !setOf(get(ctx, "stock_keys"))[key]) return [true, null, null];')
        (Path(t) / "last-word.js").write_text(mut3, encoding="utf-8")
        n3 = compare("мутант 14", [{"ctx": dict(CTX, today="2026-10-31")}], mod=Path(t) / "last-word.js", report=False)
        check("JS с «есть в портфеле» только у акций расходится с Python", mut3 != src_js and n3 == 1)
        # правило 11 (R31): «привести к плану» всегда flat (как в карте) — обязан разойтись
        mut4 = src_js.replace('if (up !== BALANCE) return mapGet(PLAN_DIRECTION, up);', 'return mapGet(PLAN_DIRECTION, up);')
        (Path(t) / "last-word.js").write_text(mut4, encoding="utf-8")
        n4 = compare("мутант 11", [{"ctx": dict(CTX, today="2026-10-31")}], mod=Path(t) / "last-word.js", report=False)
        check("JS с «привести к плану» всегда flat расходится с Python", mut4 != src_js and n4 == 1)

        # правило 9 (решение 11.11): «без ИИ» блокирует как «с ИИ» — JS, где off не блокирует (предупреждает), обязан разойтись
        mut6 = src_js.replace('var soft = get(ctx, "ai_mode") === "off" && !NOAI_GATE_BLOCKS;', 'var soft = get(ctx, "ai_mode") === "off";')
        (Path(t) / "last-word.js").write_text(mut6, encoding="utf-8")
        n6 = compare("мутант 9", [{"ctx": dict(CTX, today="2026-10-31", ai_mode="off")}], mod=Path(t) / "last-word.js", report=False)
        check("JS, где «без ИИ» не блокирует гейтом, расходится с Python", mut6 != src_js and n6 == 1)

        # правило 9а: «владелец открывает при on» — вариант Б не считается; JS обязан разойтись
        mut7 = src_js.replace('var gb = gateCodes(b.reasons);', 'var gb = [];')
        (Path(t) / "last-word.js").write_text(mut7, encoding="utf-8")
        n7 = compare("мутант 9а", [{"ctx": OW}], mod=Path(t) / "last-word.js", report=False)
        check("JS, где решение владельца открывает докупку при «с ИИ», расходится с Python", mut7 != src_js and n7 == 1)

print(f"\nlast_word_parity: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
