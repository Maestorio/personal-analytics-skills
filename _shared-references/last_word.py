#!/usr/bin/env python3
"""Модуль (б) схемы данных: «последнее слово» по бумаге и статус гейта (schema.md §1 п.3, §3.5; decision.md R4/R5).

Чистые функции без ввода-вывода: card / cards. Файлы читает вызывающий (решения — `decisions_read.load`, строки
обзоров — по ключу, справочник бумаг `security-attrs@1`, ключи снапшота, план). JS-близнец —
`tools/assets/last-word.js` (`window.LW`): та же выдача поле в поле; паритет и равенство текста правил ниже шапке JS
держит `tools/tests/test_last_word_parity.py`. Любое изменение правил — здесь и в шапке JS одновременно.

Таблицы и сроки — из кодлистов (`codelists.py`): `verdict_to_gate`, `verdict_direction`, `user_plan_direction`,
`gate_to_block`, `defaults` (`review_days`, `add_cooldown_days`, `ipo_pause_quarters`, `plan_tolerance_pp`); коды статусов гейта —
кодлист `gate_status` (модуль падает при загрузке, если нужного кода нет). Файла гейтов нет: статус вычисляется.
В упакованном скилле модуль лежит в `scripts/` рядом с codelists.py/.json (pack.sh кладёт по импорту).

Вход — один словарь `ctx` (уже разобранные объекты, даты и время — строки):
  today          'YYYY-MM-DD'
  decisions      [decision@1] — любые ключи (берутся с key = ключ)
  reviews        {ключ: [строка обзора]}; строка: review_date, recorded_at, advisor_verdict,
                 advisor_verdict_confidence, advisor_verdict_basis, gate_review_required (флаг
                 `flags.gate_review_required` строки), doc (имя файла обзора, необязательно)
  security_attrs документ security-attrs@1 или None
  snapshot_keys  [ключ] — бумаги в снапшоте (qty > 0)
  stock_keys     [ключ] — акции (гейт только у них; тип — по реестру типов, решает вызывающий)
  first_buy      [ключ] — кандидаты первой покупки (бумаги нет в снапшоте, план «докупать»)
  plan           {ключ: {user_plan, user_status, changed_at, fact_pct, plan_pct}} — changed_at: время последней строки
                 журнала плана; fact_pct и plan_pct — доля бумаги факт и план, п.п. (нужны только для BALANCE, правило 11)
  last_trade_at  {ключ: время} — последняя сделка по бумаге (разница количества между снапшотами; считает вызывающий)
  last_sell_at   {ключ: время} — последнее уменьшение количества по бумаге (продажа; так же, считает вызывающий)
  last_buy_at    {ключ: время} — последнее увеличение количества по бумаге (покупка; так же, считает вызывающий)
  buys_at        {ключ: [время]} — все увеличения количества по бумаге (покупки; так же, считает вызывающий), правило 7
  maturities     {ключ: дата} — дата погашения облигации (считает вызывающий из снапшотов и обзора облигаций)
  ai_mode        'on' | 'off' — режим сайта (по умолчанию 'on'; любое значение, кроме 'off', — 'on'), правило 9
Ключи, которых нет, равны пустым значениям.

ПРАВИЛА (спецификация для JS)
 1. Время сравнивается как строка: везде YYYY-MM-DDTHH:MM:SS+03:00 (один пояс), даты — YYYY-MM-DD;
    лексикографический порядок = хронологический. «Что новее» — только по recorded_at.
 2. Источники ключа: решения с key = ключ и строки reviews[ключ] с непустыми recorded_at и advisor_verdict
    (строка без них источником не считается). Порядок источников — по (recorded_at, вид, id), вид: обзор раньше
    решения — при равном времени решение новее обзора. id решения — id, строки обзора — doc, без него — review_date.
 3. Последнее слово — новейший источник: verdict; direction = verdict_direction[verdict] (нет кода — null);
    confidence и basis (у решения — confidence и note, у обзора — advisor_verdict_confidence и advisor_verdict_basis);
    verdict_source {kind: decision | review, id, recorded_at}. Источников нет — все эти поля null.
 4. Только из новейшего решения: decision_verdict, target_pct, review_by (как записан), decision_id,
    decision_recorded_at, conditions_created, conditions_resolved (решения нет — null и пустые списки).
    review_recorded_at — recorded_at новейшей строки обзора (нет — null). Обзор эти поля не несёт и не стирает.
 5. Гейт только для акций: ключа нет в stock_keys -> gate.applicable = false, status null, expired false, даты null,
    blocking false, reasons []. Дальше — только для акций.
 6. Срок: expires_on = review_by новейшего решения, null -> дата recorded_at + defaults.review_days;
    expired = expires_on < today. Решения нет — expires_on null, expired false.
    Статус — первое подходящее:
      а) ключа нет в snapshot_keys и нет в first_buy -> divested;
      б) ключ в first_buy и решения нет -> new_position;
      в) есть строка обзора с gate_review_required = true новее новейшего решения (решения нет — любая) -> review_needed;
      г) решения нет -> null (держимая бумага без решения не блокируется);
      д) expired -> review_aging; иначе verdict_to_gate[вердикт новейшего решения].
 7. Пауза докупки — от первой покупки после решения: d — дата recorded_at новейшего решения с вердиктом BUY или ADD;
    b — первая покупка по ключу после него: наименьшее из buys_at[ключ] с датой ≥ d (покупка в день решения — по нему:
    времена покупок — дни снапшотов, порядок внутри дня неизвестен); списка buys_at[ключ] нет — last_buy_at[ключ] с датой
    ≥ d (последняя покупка; при одной покупке после решения — она же первая). b нет -> паузы нет (решение без покупки
    докупку не закрывает). Иначе конец = дата b + defaults.add_cooldown_days; add_cooldown_until = конец, если
    today < конец, иначе null.
 8. IPO-пауза: в справочнике security_attrs.by_key[ключ] ticker_class = ipo и listed_at не null -> конец = listed_at +
    3 × defaults.ipo_pause_quarters месяцев (день — не больше длины месяца); ipo_pause_until = конец, если конец > today,
    иначе null. Возраст q — полных кварталов: наибольшее q, при котором listed_at + 3q месяцев ≤ today.
    Действует при любом вердикте и у первой покупки.
 9. reasons по порядку: «gate:<status>», если status есть в карте gate_to_block; «ipo_gate:<q>q» при ipo_pause_until;
    «add_cooldown:<add_cooldown_until>» при паузе. У divested пауз и причин нет (бумаги нет).
    blocking = reasons непуст. Режим «без ИИ» (ai_mode = off) блокирует теми же статусами, что и «с ИИ» (решение 11.11): снимает
    блок не разбор советника, а решение владельца (правило 9а при off не действует). Флаг defaults.noai_gate_blocks = false
    оставлен на случай отката: тогда при off «gate:<status>» уходит из reasons в warnings (тот же текст).
 9а. При on гейт считается дважды: по всем решениям и без решений с source.kind = owner (решение владельца с сайта
    докупку, закрытую гейтом, не открывает — только разбор советника; закрыть может). Итог — строже: reasons —
    объединение без дублей (gate: впереди); если gate: даёт только вариант без решений владельца — status, expired,
    expires_on и gate:-причина из него (срок разбора), owner_pending_review = true; иначе всё из первого. При off и без
    решений владельца — один расчёт, owner_pending_review = false.
10. Конфликт (R5). Хвост — наибольший конечный отрезок источников с тем же direction, что у новейшего; S — первый
    источник хвоста, P — источник перед S. Конфликт есть, если P существует, вид P ≠ вид S и direction обоих не null;
    иначе conflict = null. conflict = {at: S.recorded_at, source: {kind, id, recorded_at, verdict, direction} S,
    against: то же для P, open, closed_by, closed_at}. Закрытие — самое раннее из: confirmed — второй источник хвоста
    (следующий источник подтвердил направление; его recorded_at); plan — plan[ключ].changed_at > at (владелец правил
    план после конфликта); trade — last_trade_at[ключ] > at (сделка после конфликта, «закрыто сделкой, без
    подтверждения»). При равном времени порядок confirmed, plan, trade. Нет закрытия — open = true, closed_by и
    closed_at null. Срока давности нет.
11. План против решения. plan_direction: у плана BALANCE («привести к плану») — по знаку отклонения факта от плана:
    f = plan[ключ].fact_pct, p = plan[ключ].plan_pct (числа, считает вызывающий), t = defaults.plan_tolerance_pp
    (гистерезис плана): f > p + t -> down, f < p − t -> up, иначе flat; f или p нет -> null; у остальных планов —
    user_plan_direction[user_plan] (BALANCE в карте — flat «по умолчанию», правилом не читается). plan_direction и
    direction последнего слова оба не null и различны -> plan_vs_decision = {user_plan, plan_direction, verdict,
    direction, source_kind}; иначе null.
12. Карточка — плоский словарь: key, verdict, direction, confidence, basis, verdict_source, decision_verdict,
    target_pct, review_by, decision_id, decision_recorded_at, review_recorded_at, conditions_created,
    conditions_resolved, gate {applicable, status, expired, expires_on, add_cooldown_until, ipo_pause_until, blocking,
    reasons, warnings, owner_pending_review}, conflict, plan_vs_decision, executed_by_trade_at, executed_source_kind, decision_executed_at, held, left_at, left_kind. cards — карточки по ключам
    в порядке ключа; ключи — переданный список, иначе объединение ключей решений, reviews, snapshot_keys и first_buy.
13. Исполнение сделкой — по источнику последнего слова (verdict_source: решение или обзор): direction = down и
    last_sell_at[ключ] > его recorded_at -> executed_by_trade_at = last_sell_at[ключ]; direction = up и
    last_buy_at[ключ] > его recorded_at -> executed_by_trade_at = last_buy_at[ключ]; иначе null (источника нет,
    направление flat или null, сделки в ту сторону после него нет). executed_source_kind = вид этого источника
    (decision | review), если executed_by_trade_at не null, иначе null. Отдельно decision_executed_at — то же правило
    для новейшего решения (решения нет — null), даже если последнее слово — обзор: строка разбора и «Сделано» по
    решению. Уход бумаги из снапшота — тоже уменьшение количества. Гейт, срок, паузы и причины признак не меняет:
    решение действует до review_by, что показывать — дело вызывающего.
14. Есть в портфеле (все классы, независимо от gate.applicable): held = ключ в snapshot_keys. Ушла — ключа нет
    в snapshot_keys и в first_buy, и есть last_sell_at[ключ] или дата погашения m = maturities[ключ] ≤ today; тогда
    left_at = last_sell_at[ключ] (нет — null), left_kind = redeemed, если m есть и (left_at не null и дата left_at ≥ m,
    или left_at null), иначе sold (у акций и фондов дат погашения нет — всегда sold). Не ушла (держится, первая
    покупка или в известной истории не держалась) — left_at и left_kind null. Гейт признак не меняет: divested акций —
    правило 6а.

CLI нет: выборки для советника — `decisions_read.digest` (обёртка над этим модулем), движок «Сейчас» —
`gate_aware_sizing.py`, проверка бэкфилла — `backfill_decisions.py verify`.

Зависимости: stdlib (+ codelists.py рядом).
"""
from __future__ import annotations

import calendar
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codelists  # noqa: E402


def _gate_code(code):
    if code not in codelists.codes("gate_status", legacy=False):
        raise RuntimeError(f"last_word: в кодлисте gate_status нет кода {code!r}")
    return code


VERDICT_TO_GATE = codelists.map_("verdict_to_gate")
VERDICT_DIRECTION = codelists.map_("verdict_direction")
PLAN_DIRECTION = codelists.map_("user_plan_direction")
GATE_TO_BLOCK = codelists.map_("gate_to_block")
_D = codelists.defaults()
REVIEW_DAYS = _D["review_days"]
ADD_COOLDOWN_DAYS = _D["add_cooldown_days"]
IPO_PAUSE_QUARTERS = _D["ipo_pause_quarters"]
PLAN_TOLERANCE_PP = _D["plan_tolerance_pp"]
NOAI_GATE_BLOCKS = bool(_D.get("noai_gate_blocks", False))
BALANCE = "BALANCE"
ADD_VERDICTS = ("BUY", "ADD")
IPO_CLASS = "ipo"
DIVESTED = _gate_code("divested")
NEW_POSITION = _gate_code("new_position")
REVIEW_NEEDED = _gate_code("review_needed")
REVIEW_AGING = _gate_code("review_aging")
KIND_DECISION, KIND_REVIEW = "decision", "review"
_KIND_ORDER = {KIND_REVIEW: 0, KIND_DECISION: 1}   # правило 2: при равном времени решение новее


def _day(iso):
    return str(iso)[:10]


def add_days(d, n):
    return (date.fromisoformat(_day(d)) + timedelta(days=n)).isoformat()


def add_months(d, n):
    """Дата + n месяцев; день не больше длины месяца (правило 8)."""
    x = date.fromisoformat(_day(d))
    total = x.month - 1 + n
    y, m = x.year + total // 12, total % 12 + 1
    return date(y, m, min(x.day, calendar.monthrange(y, m)[1])).isoformat()


def _sources(ctx, key):
    """Правило 2: источники ключа по (recorded_at, вид, id)."""
    out = []
    for d in ctx.get("decisions") or []:
        if d.get("key") == key:
            out.append({"kind": KIND_DECISION, "id": d.get("id") or "", "recorded_at": d["recorded_at"],
                        "verdict": d.get("verdict"), "confidence": d.get("confidence"), "basis": d.get("note"),
                        "flag": False, "doc": d})
    for r in (ctx.get("reviews") or {}).get(key) or []:
        if not r.get("recorded_at") or not r.get("advisor_verdict"):
            continue
        out.append({"kind": KIND_REVIEW, "id": r.get("doc") or r.get("review_date") or "",
                    "recorded_at": r["recorded_at"], "verdict": r.get("advisor_verdict"),
                    "confidence": r.get("advisor_verdict_confidence"), "basis": r.get("advisor_verdict_basis"),
                    "flag": r.get("gate_review_required") is True, "doc": None})
    out.sort(key=lambda s: (s["recorded_at"], _KIND_ORDER[s["kind"]], s["id"]))
    return out


def _direction(verdict):
    return VERDICT_DIRECTION.get(verdict) if verdict else None


def _brief(s):
    return {"kind": s["kind"], "id": s["id"], "recorded_at": s["recorded_at"], "verdict": s["verdict"],
            "direction": _direction(s["verdict"])}


def _ipo(ctx, key, today):
    """Правило 8: (ipo_pause_until, q) или (None, None)."""
    attrs = ((ctx.get("security_attrs") or {}).get("by_key") or {}).get(key) or {}
    listed = attrs.get("listed_at")
    if attrs.get("ticker_class") != IPO_CLASS or not listed:
        return None, None
    end = add_months(listed, 3 * IPO_PAUSE_QUARTERS)
    if not end > today:
        return None, None
    q = 0
    while q < IPO_PAUSE_QUARTERS and add_months(listed, 3 * (q + 1)) <= today:
        q += 1
    return end, q


def _first_buy_after(ctx, key, d):
    """Правило 7: первая покупка по ключу с датой ≥ d (buys_at; списка нет — last_buy_at) или None."""
    buys = (ctx.get("buys_at") or {}).get(key)
    if buys is None:
        lb = (ctx.get("last_buy_at") or {}).get(key)
        buys = [lb] if lb else []
    after = sorted(_day(b) for b in buys if b and _day(b) >= d)
    return after[0] if after else None


def _is_owner(doc):
    return ((doc or {}).get("source") or {}).get("kind") == "owner"


def _gate_codes(reasons):
    return [r for r in reasons if r.startswith("gate:")]


def _gate(ctx, key, today, decision, srcs):
    """Правило 9а: при on гейт — строже из двух (все решения / без решений владельца)."""
    a = _gate_core(ctx, key, today, decision, srcs)
    if ctx.get("ai_mode") == "off" or not a["applicable"]:
        return a
    if not any(s["kind"] == KIND_DECISION and _is_owner(s["doc"]) for s in srcs):
        return a
    srcs_b = [s for s in srcs if not (s["kind"] == KIND_DECISION and _is_owner(s["doc"]))]
    decs_b = [s["doc"] for s in srcs_b if s["kind"] == KIND_DECISION]
    b = _gate_core(ctx, key, today, decs_b[-1] if decs_b else None, srcs_b)
    gb = _gate_codes(b["reasons"])
    if not gb:
        return a
    ga = _gate_codes(a["reasons"])
    rest = [r for r in a["reasons"] if not r.startswith("gate:")]
    if ga:
        a["reasons"] = list(dict.fromkeys(ga + gb)) + rest
        return a
    for k in ("status", "expired", "expires_on"):
        a[k] = b[k]
    a["reasons"] = gb + rest
    a["blocking"] = True
    a["owner_pending_review"] = True
    return a


def _gate_core(ctx, key, today, decision, srcs):
    """Правила 5–9."""
    g = {"applicable": False, "status": None, "expired": False, "expires_on": None, "add_cooldown_until": None,
         "ipo_pause_until": None, "blocking": False, "reasons": [], "warnings": [], "owner_pending_review": False}
    if key not in set(ctx.get("stock_keys") or []):
        return g
    g["applicable"] = True
    if decision is not None:
        g["expires_on"] = decision.get("review_by") or add_days(decision["recorded_at"], REVIEW_DAYS)
        g["expired"] = g["expires_on"] < today
    in_snap = key in set(ctx.get("snapshot_keys") or [])
    first = key in set(ctx.get("first_buy") or [])
    d_at = decision["recorded_at"] if decision is not None else None
    flagged = any(s["kind"] == KIND_REVIEW and s["flag"] and (d_at is None or s["recorded_at"] > d_at) for s in srcs)
    if not in_snap and not first:
        g["status"] = DIVESTED
        return g
    if first and decision is None:
        g["status"] = NEW_POSITION
    elif flagged:
        g["status"] = REVIEW_NEEDED
    elif decision is None:
        g["status"] = None
    elif g["expired"]:
        g["status"] = REVIEW_AGING
    else:
        g["status"] = VERDICT_TO_GATE.get(decision["verdict"])
    adds = [s["doc"] for s in srcs if s["kind"] == KIND_DECISION and s["verdict"] in ADD_VERDICTS]
    buy = _first_buy_after(ctx, key, _day(adds[-1]["recorded_at"])) if adds else None
    if buy:
        end = add_days(buy, ADD_COOLDOWN_DAYS)
        g["add_cooldown_until"] = end if today < end else None
    ipo_end, q = _ipo(ctx, key, today)
    g["ipo_pause_until"] = ipo_end
    reasons = []
    soft = ctx.get("ai_mode") == "off" and not NOAI_GATE_BLOCKS
    if g["status"] in GATE_TO_BLOCK:
        (g["warnings"] if soft else reasons).append(f"gate:{g['status']}")
    if ipo_end:
        reasons.append(f"ipo_gate:{q}q")
    if g["add_cooldown_until"]:
        reasons.append(f"add_cooldown:{g['add_cooldown_until']}")
    g["reasons"] = reasons
    g["blocking"] = bool(reasons)
    return g


def _conflict(ctx, key, srcs):
    """Правило 10."""
    if not srcs:
        return None
    last_dir = _direction(srcs[-1]["verdict"])
    i = len(srcs) - 1
    while i > 0 and _direction(srcs[i - 1]["verdict"]) == last_dir:
        i -= 1
    if i == 0:
        return None
    s, p = srcs[i], srcs[i - 1]
    if p["kind"] == s["kind"] or _direction(s["verdict"]) is None or _direction(p["verdict"]) is None:
        return None
    at = s["recorded_at"]
    closes = []
    if i + 1 < len(srcs):
        closes.append((srcs[i + 1]["recorded_at"], 0, "confirmed"))
    changed = ((ctx.get("plan") or {}).get(key) or {}).get("changed_at")
    if changed and changed > at:
        closes.append((changed, 1, "plan"))
    trade = (ctx.get("last_trade_at") or {}).get(key)
    if trade and trade > at:
        closes.append((trade, 2, "trade"))
    first = min(closes) if closes else None
    return {"at": at, "source": _brief(s), "against": _brief(p), "open": first is None,
            "closed_by": first[2] if first else None, "closed_at": first[0] if first else None}


def _executed(ctx, key, last):
    """Правило 13: (время сделки в сторону последнего слова после его записи, вид источника) или (None, None)."""
    if last is None:
        return None, None
    d = _direction(last["verdict"])
    field = "last_sell_at" if d == "down" else "last_buy_at" if d == "up" else None
    at = (ctx.get(field) or {}).get(key) if field else None
    if at and at > last["recorded_at"]:
        return at, last["kind"]
    return None, None


def _held(ctx, key, today):
    """Правило 14: (held, left_at, left_kind)."""
    if key in set(ctx.get("snapshot_keys") or []):
        return True, None, None
    if key in set(ctx.get("first_buy") or []):
        return False, None, None
    left = (ctx.get("last_sell_at") or {}).get(key) or None
    m = (ctx.get("maturities") or {}).get(key) or None
    if left is None and not (m and _day(m) <= today):
        return False, None, None
    redeemed = bool(m) and (left is None or _day(left) >= _day(m))
    return False, left, ("redeemed" if redeemed else "sold")


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _plan_direction(plan):
    """Правило 11: направление плана; у BALANCE — по знаку отклонения факта от плана с допуском."""
    up = plan.get("user_plan")
    if not up:
        return None
    if up != BALANCE:
        return PLAN_DIRECTION.get(up)
    f, p = _num(plan.get("fact_pct")), _num(plan.get("plan_pct"))
    if f is None or p is None:
        return None
    if f > p + PLAN_TOLERANCE_PP:
        return "down"
    if f < p - PLAN_TOLERANCE_PP:
        return "up"
    return "flat"


def card(ctx, key):
    """Карточка «последнего слова» по ключу (правила 1–14)."""
    today = ctx["today"]
    srcs = _sources(ctx, key)
    decs = [s for s in srcs if s["kind"] == KIND_DECISION]
    revs = [s for s in srcs if s["kind"] == KIND_REVIEW]
    d = decs[-1]["doc"] if decs else None
    last = srcs[-1] if srcs else None
    verdict = last["verdict"] if last else None
    direction = _direction(verdict)
    plan = (ctx.get("plan") or {}).get(key) or {}
    pdir = _plan_direction(plan)
    held, left_at, left_kind = _held(ctx, key, today)
    ex_at, ex_kind = _executed(ctx, key, last)
    dec_ex = _executed(ctx, key, decs[-1] if decs else None)[0]
    pvd = None
    if pdir is not None and direction is not None and pdir != direction:
        pvd = {"user_plan": plan.get("user_plan"), "plan_direction": pdir, "verdict": verdict,
               "direction": direction, "source_kind": last["kind"]}
    return {
        "key": key,
        "verdict": verdict,
        "direction": direction,
        "confidence": last["confidence"] if last else None,
        "basis": last["basis"] if last else None,
        "verdict_source": ({"kind": last["kind"], "id": last["id"], "recorded_at": last["recorded_at"]}
                           if last else None),
        "decision_verdict": d.get("verdict") if d else None,
        "target_pct": d.get("target_pct") if d else None,
        "review_by": d.get("review_by") if d else None,
        "decision_id": d.get("id") if d else None,
        "decision_recorded_at": d["recorded_at"] if d else None,
        "review_recorded_at": revs[-1]["recorded_at"] if revs else None,
        "conditions_created": list(d.get("conditions_created") or []) if d else [],
        "conditions_resolved": list(d.get("conditions_resolved") or []) if d else [],
        "gate": _gate(ctx, key, today, d, srcs),
        "conflict": _conflict(ctx, key, srcs),
        "plan_vs_decision": pvd,
        "executed_by_trade_at": ex_at,
        "executed_source_kind": ex_kind,
        "decision_executed_at": dec_ex,
        "held": held,
        "left_at": left_at,
        "left_kind": left_kind,
    }


def all_keys(ctx):
    ks = {d.get("key") for d in ctx.get("decisions") or [] if d.get("key")}
    ks |= set((ctx.get("reviews") or {}).keys())
    ks |= set(ctx.get("snapshot_keys") or []) | set(ctx.get("first_buy") or [])
    return sorted(ks)


def cards(ctx, keys=None):
    """Карточки по ключам в порядке ключа (правило 12)."""
    return [card(ctx, k) for k in sorted(set(keys) if keys is not None else all_keys(ctx))]
