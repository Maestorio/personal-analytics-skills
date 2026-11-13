"""Проверки выгрузки ZenMoney ДО записи месяца (этап «Деньги» «меньше ИИ», задача 3.7): только CSV и история,
без MCP и без ИИ. Исследование и бэктест — docs/zenmoney/csv-checks-research.md (§3, §4а).

Вход — те же операции формата MCP, что строит `zenmoney_csv_backfill.build` (в `zm_csv.recompute`:
`ops, refs, notes = B.build(...)`), и `AM.Ctx` над ними. Проверки A1, A3, A4, A5, B7, D13 — функции скилла
`audit_month` (не копии); остальные — здесь.

    run_checks(ops, refs, ctx, history, months, cfg) -> [{id, cls, month, text, count, sample:[…≤5]}]

  ops      все операции выгрузки (история нужна: медианы за 12 прошлых месяцев, места, поездки);
  ctx      audit_month.Ctx над ops (курсы, категории, счета, карта);
  history  необязательные подсказки: {"trip_dates": {имя поездки: [с, по]}, "known_places": {названия мест из словаря},
           "account_currencies": {имя счёта: {валюты}}}; чего нет — берётся из самих операций;
  months   проверяемые месяцы «ГГГГ-ММ» (закрываемые); прошлые месяцы для медиан — любые раньше;
  cfg      переопределение DEFAULTS; ключ "today" (дата) — «сегодня» для N6.

`collect` отдаёт срабатывания с id операций (для бэктеста), `run_checks` сворачивает их по (проверка, месяц).
Только stdlib; ничего не пишет.
"""
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
_ROOTS = [HERE / "pdl"]
if len(HERE.parents) > 2:
    _ROOTS.append(HERE.parents[2])
for _r in _ROOTS:
    _p = _r / "skills/zenmoney-analyst/scripts"
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.append(str(_p))
import audit_month as AM  # noqa: E402

# Пороги и классы. Класс — результат бэктеста 2026-11-10 (docs/zenmoney/csv-checks-research.md §4а):
# stop — точность ≥ 80 % и ошибка искажает итог месяца; warn — ≥ 50 %; hint — ниже 50 % или эталона нет.
DEFAULTS = {
    "history_months": 12,        # окно прошлых месяцев для медиан
    "n2_k": 3.0,                 # N2/N2i: отклонение больше k·MAD (MAD не меньше n2_mad_floor от медианы)
    "n2_mad_floor": 0.10,        # доля медианы: нижняя граница MAD, иначе у стабильной категории MAD = 0
    "n2_min_months": 6,          # категория с ненулевыми значениями хотя бы в стольких из 12 месяцев
    "n2_min_delta_rub": 3000,    # и отклонение не меньше стольких ₽ (мелочь не интересна)
    "n9_share": 0.60,            # N9: операций в месяце меньше этой доли медианы за 12 месяцев
    "n9_min_months": 6,
    "b6_active_months": 9,       # B6': счёт активен в стольких из 12 прошлых месяцев
    "p_min_ops": 5,              # P1/P2: операций места в истории
    "p_lookback_months": 24,     # история места — не глубже
    "p1_share": 0.90,            # P1: доля операций места в одной категории
    "p2_factor": 5.0,            # P2: сумма больше медианы места в стольких раз
    "p2_min_rub": 1000,          # … и не меньше стольких ₽
    "p3_known_ops": 3,           # P3: место с таким числом прошлых операций считается знакомым
    "p4_min_len": 6,             # P4: опечатка на одну букву — только в названиях не короче
    "p4_twin_ops": 3,            # P4: «настоящее» написание — с таким числом прошлых операций
    "n1_days": 1,                # N1: окно дат дубля
    "n5_share": 0.70,            # N5: категория «поездочная», если столько её сумм внутри дат поездок несут тег
    "n5_min_ops": 5,
    "n6_old_days": 730,          # N6: дата старше (от createdDate и «сегодня») — опечатка года
    "n6_recent_days": 45,        # N6: смотрим операции, созданные или правленные за столько дней до «сегодня»
    "n7_min_ops": 10,            # N7: без списка счетов — набор валют счёта по истории при таком числе операций
    "n10_factor": 3.0,           # N10: трата больше медианной месячной суммы категории в стольких раз
    "n10_min_rub": 5000,
    "n10_min_months": 6,
    "transfer_words": ("перевод",),   # N3: слова в названии категории-перевода
    "cls": {
        "A1": "hint", "A3": "warn", "A4": "warn", "A5": "hint", "B7": "hint", "D13": "hint",
        "N1": "hint", "N2": "hint", "N2i": "hint", "N3": "hint", "N5": "hint", "N6": "hint", "N7": "hint",
        "N9": "hint", "N10": "hint", "B6'": "hint", "P1": "hint", "P2": "hint", "P3": "hint", "P4": "hint",
    },
}

TEXTS = {
    "A1": "перевод между своими счетами записан расходом и доходом",
    "A3": "операции без категории",
    "A4": "проект (#…) стоит основной категорией",
    "A5": "дубли: одна дата, счёт, сумма и место",
    "B7": "траты со счёта вне баланса",
    "D13": "траты прямо в родительской категории, у которой есть подкатегории",
    "N1": "похоже на дубль: сумма, счёт и категория те же, дата в пределах дня",
    "N2": "категория обычных трат вне привычного диапазона",
    "N2i": "категория дохода вне привычного диапазона",
    "N3": "расход в категории-переводе без пары на своём счёте",
    "N5": "траты в даты поездки без тега поездки в «поездочной» категории",
    "N6": "дата операции в будущем или слишком давняя у недавно внесённой операции",
    "N7": "валюта операции не из набора валют счёта",
    "N9": "операций в месяце заметно меньше обычного — месяц неполный или банк не синхронизирован",
    "N10": "крупная трата в категории без комментария",
    "B6'": "счёт, где операции бывают почти каждый месяц, без операций в этом месяце",
    "P1": "место обычно в другой категории",
    "P2": "сумма в месте много больше обычной для него",
    "P3": "место названо сырым текстом банка",
    "P4": "новое написание уже известного места",
}
ORDER = list(TEXTS)
_SAMPLE = 5


# ─── вспомогательное ─────────────────────────────────────────────────────────

def _cfg(cfg):
    out = dict(DEFAULTS)
    for k, v in (cfg or {}).items():
        out[k] = {**DEFAULTS["cls"], **v} if k == "cls" else v
    return out


def _add_months(m, n):
    y, mo = map(int, m.split("-"))
    t = y * 12 + mo - 1 + n
    return f"{t // 12}-{t % 12 + 1:02d}"


def _prior(m, n):
    return [_add_months(m, -i) for i in range(n, 0, -1)]


def payee(o):
    mid = o.get("merchantId") or ""
    return mid[2:] if mid.startswith("p:") else None


def _brief(ctx, o):
    s = AM.side(o)
    return {"date": o["date"], "amount": round(ctx.rub(o) or 0.0, 2), "account": ctx.acc(s["accountId"]).get("name"),
            "payee": payee(o) or "", "category": ctx.cat_name(o.get("categoryId")) if o.get("categoryId") else ""}


class _Data:
    """Индексы над операциями: по месяцам, агрегаты месяцев, места."""

    def __init__(self, ops, ctx, cfg):
        from month_stats import Stats
        self.ctx, self.cfg, self.ops = ctx, cfg, ops
        self.st = Stats(ctx)
        self.by_month = defaultdict(list)
        for o in ops:
            self.by_month[o["date"][:7]].append(o)
        self.one_off = set(ctx.cfg.get("one_off_ids") or [])
        self.one_off_m = set(ctx.cfg.get("one_off_merchant_ids") or [])
        self._agg = {}
        self.by_payee = defaultdict(list)
        for o in ops:
            p = payee(o)
            if p and AM.kind(o) == "expense":
                self.by_payee[p].append(o)
        for v in self.by_payee.values():
            v.sort(key=lambda o: o["date"])

    def has_project(self, o):
        c = self.ctx
        return bool(set(o.get("tagIds") or []) & c.project_ids) or o.get("categoryId") in c.project_ids

    def excluded(self, o):
        return bool(self.st.group(o.get("categoryId")))

    def agg(self, m):
        """Месяц: обычные траты и доход по корневой категории, число операций, счета (по имени)."""
        if m in self._agg:
            return self._agg[m]
        ctx, st = self.ctx, self.st
        exp, inc, accs = defaultdict(float), defaultdict(float), set()
        ops = self.by_month.get(m, [])
        for o in ops:
            for s in (o.get("expense"), o.get("income")):
                if s:
                    accs.add(ctx.acc(s["accountId"]).get("name"))
            k = AM.kind(o)
            if k == "transfer" or self.excluded(o):
                continue
            v = ctx.rub(o)
            if v is None:
                continue
            cid = o.get("categoryId")
            root = ctx.cat_name(st.root(cid)) if cid else "Без категории"
            if k == "expense" or st.is_refund(o):
                if self.has_project(o) or o["id"] in self.one_off or o.get("merchantId") in self.one_off_m:
                    continue
                exp[root] += v if k == "expense" else -v
            else:
                inc[root] += v
        out = {"exp": dict(exp), "inc": dict(inc), "n": len(ops), "accs": accs}
        self._agg[m] = out
        return out

    def root_name(self, o):
        cid = o.get("categoryId")
        return self.ctx.cat_name(self.st.root(cid)) if cid else "Без категории"


def _hit(id_, month, op_ids=(), subject=None, detail=None):
    return {"id": id_, "month": month, "op_ids": list(op_ids), "subject": subject, "detail": detail or {}}


def _median_mad(vals, floor):
    med = statistics.median(vals)
    mad = statistics.median([abs(v - med) for v in vals])
    return med, max(mad, floor * abs(med))


# ─── проверки скилла (audit_month) ───────────────────────────────────────────

def _skill_checks(D, m, month_ops, hist_ops):
    ctx = D.ctx
    out = []
    for p in AM.a1_transfer_pairs(ctx, month_ops):
        out.append(_hit("A1", m, [p["expense_id"], p["income_id"]], detail={
            "date": p["date"], "amount": round(p.get("rub") or 0.0, 2), "account": p["from"], "payee": "", "category": ""}))
    byid = {o["id"]: o for o in month_ops}
    for r in AM.a3_no_category(ctx, month_ops):
        out.append(_hit("A3", m, [r["id"]], detail=_brief(ctx, byid[r["id"]])))
    for r in AM.a4_project_as_category(ctx, month_ops, hist_ops):
        out.append(_hit("A4", m, [r["id"]], detail=_brief(ctx, byid[r["id"]])))
    for r in AM.a5_duplicates(ctx, month_ops):
        out.append(_hit("A5", m, r["ids"], detail=_brief(ctx, byid[r["ids"][0]])))
    for r in AM.b7_off_balance(ctx, month_ops):
        ids = [o["id"] for o in month_ops if AM.kind(o) == "expense"
               and ctx.acc(o["expense"]["accountId"]).get("name") == r["account"]
               and ctx.acc(o["expense"]["accountId"]).get("isInBalance") is False]
        out.append(_hit("B7", m, ids, subject=r["account"], detail={"account": r["account"], "count": r["count"],
                                                                    "amount": r["rub"]}))
    for name, n in AM.d13_parent_with_children(ctx, month_ops).items():
        ids = [o["id"] for o in month_ops if AM.kind(o) != "transfer" and o.get("categoryId")
               and ctx.cat_name(o["categoryId"]) == name]
        out.append(_hit("D13", m, ids, subject=name, detail={"category": name, "count": n}))
    return out


# ─── расхождения ─────────────────────────────────────────────────────────────

def _n2(D, m, which):
    cfg = D.cfg
    key, id_ = ("exp", "N2") if which == "exp" else ("inc", "N2i")
    prior = [D.agg(p)[key] for p in _prior(m, cfg["history_months"])]
    cur = D.agg(m)[key]
    out = []
    for cat in sorted(set(cur) | set().union(*prior)):
        vals = [a[cat] for a in prior if a.get(cat)]
        if len(vals) < cfg["n2_min_months"]:
            continue
        v = cur.get(cat, 0.0)
        med, mad = _median_mad(vals, cfg["n2_mad_floor"])
        if abs(v - med) > cfg["n2_k"] * mad and abs(v - med) >= cfg["n2_min_delta_rub"]:
            out.append(_hit(id_, m, subject=cat, detail={"category": cat, "amount": round(v, 2),
                                                         "median": round(med, 2), "months": len(vals)}))
    return out


def _n9(D, m):
    cfg = D.cfg
    vals = [D.agg(p)["n"] for p in _prior(m, cfg["history_months"]) if D.agg(p)["n"]]
    n = D.agg(m)["n"]
    if len(vals) >= cfg["n9_min_months"]:
        med = statistics.median(vals)
        if n < cfg["n9_share"] * med:
            return [_hit("N9", m, subject=m, detail={"count": n, "median": med})]
    return []


def _b6(D, m):
    cfg = D.cfg
    prior = [D.agg(p)["accs"] for p in _prior(m, cfg["history_months"])]
    cnt = Counter(a for s in prior for a in s)
    cur = D.agg(m)["accs"]
    out = []
    for a, n in sorted(cnt.items(), key=lambda x: (-x[1], str(x[0]))):
        if n >= cfg["b6_active_months"] and a not in cur and D.agg(m)["n"]:
            out.append(_hit("B6'", m, subject=a, detail={"account": a, "active_months": n}))
    return out


# ─── места ───────────────────────────────────────────────────────────────────

_RAW_SERVICE = [rx for w, _t, rx in AM.RENAME_RULES if w in ("symbols", "code", "broker")]


def _raw_looking(name):
    return bool(AM.BANK_CAPS_RX.match(name) or any(rx.search(name) for rx in _RAW_SERVICE)) \
        and not AM.PERSON_RX.match(name) and not AM.CARD_RX.search(name)


def _places(D, m, month_ops, history):
    ctx, cfg = D.ctx, D.cfg
    start = m + "-01"
    since = _add_months(m, -cfg["p_lookback_months"]) + "-01"
    known = set(history.get("known_places") or ())
    out = []
    prior_cache = {}

    def prior_ops(p):
        if p not in prior_cache:
            prior_cache[p] = [o for o in D.by_payee.get(p, []) if since <= o["date"] < start]
        return prior_cache[p]

    twins_pool = None
    for o in month_ops:
        if AM.kind(o) != "expense":
            continue
        p = payee(o)
        if not p:
            continue
        pr = prior_ops(p)
        v = ctx.rub(o)
        # P1
        if len(pr) >= cfg["p_min_ops"] and o.get("categoryId"):
            top, n = Counter(x.get("categoryId") for x in pr).most_common(1)[0]
            if top and n / len(pr) >= cfg["p1_share"] and o["categoryId"] != top:
                out.append(_hit("P1", m, [o["id"]], subject=p, detail={**_brief(ctx, o), "usual": ctx.cat_name(top)}))
        # P2
        if len(pr) >= cfg["p_min_ops"] and v is not None:
            rubs = [r for r in (ctx.rub(x) for x in pr) if r is not None]
            if len(rubs) >= cfg["p_min_ops"]:
                med = statistics.median(rubs)
                if v > cfg["p2_factor"] * med and v >= cfg["p2_min_rub"]:
                    out.append(_hit("P2", m, [o["id"]], subject=p, detail={**_brief(ctx, o), "median": round(med, 2)}))
        # P3
        if _raw_looking(p) and p not in known and len(pr) < cfg["p3_known_ops"]:
            out.append(_hit("P3", m, [o["id"]], subject=p, detail=_brief(ctx, o)))
        # P4
        if not pr and not [x for x in D.by_payee.get(p, []) if x["date"] < start]:
            if twins_pool is None:
                twins_pool = {}
                for q, lst in D.by_payee.items():
                    old = [x for x in lst if since <= x["date"] < start]
                    if len(old) >= cfg["p4_twin_ops"]:
                        twins_pool[q] = AM.norm_name(q)
            n = AM.norm_name(p)
            twin = next((q for q, nq in sorted(twins_pool.items()) if q != p and n and (
                nq == n or (len(n) >= cfg["p4_min_len"] and len(nq) >= cfg["p4_min_len"] and n[:2] == nq[:2]
                            and AM.lev1(n, nq)))), None)
            if twin:
                out.append(_hit("P4", m, [o["id"]], subject=p, detail={**_brief(ctx, o), "twin": twin}))
    return out


# ─── прочее ──────────────────────────────────────────────────────────────────

def _n1(D, m, month_ops):
    ctx, cfg = D.ctx, D.cfg
    groups = defaultdict(list)
    for o in month_ops:
        k = AM.kind(o)
        if k == "transfer":
            continue
        s = AM.side(o)
        groups[(s["accountId"], float(s["amount"]), k, o.get("categoryId"))].append(o)
    out = []
    for g in groups.values():
        g.sort(key=lambda o: o["date"])
        used = set()
        for a, b in zip(g, g[1:]):
            if abs((AM.d(b["date"]) - AM.d(a["date"])).days) <= cfg["n1_days"]:
                used |= {a["id"], b["id"]}
        if used:
            ops = [o for o in g if o["id"] in used]
            out.append(_hit("N1", m, [o["id"] for o in ops], detail=_brief(ctx, ops[0])))
    return out


def _n3(D, m, month_ops, a1_ids):
    ctx, cfg = D.ctx, D.cfg
    ids = {cid for cid, c in ctx.cats.items() if any(w in AM.norm_name(c.get("name", "")) for w in cfg["transfer_words"])}
    out = []
    for o in month_ops:
        if AM.kind(o) == "expense" and o.get("categoryId") in ids and o["id"] not in a1_ids:
            out.append(_hit("N3", m, [o["id"]], detail=_brief(ctx, o)))
    return out


def _trip_windows(D, history):
    ctx = D.ctx
    by_name = {c["name"]: cid for cid, c in ctx.cats.items() if c["name"].startswith("#")}
    out = {}
    for name, w in (history.get("trip_dates") or {}).items():
        if name in by_name and w and len(w) == 2:
            out[by_name[name]] = (w[0], w[1])
    return out


def _n5(D, m, month_ops, history, first_month):
    ctx, cfg = D.ctx, D.cfg
    win = _trip_windows(D, history)
    if not win:
        return []
    inside = lambda o: any(a <= o["date"] <= b for a, b in win.values())
    tot, tagged, cnt = defaultdict(float), defaultdict(float), Counter()
    for o in D.ops:
        if o["date"][:7] >= first_month or AM.kind(o) != "expense" or D.excluded(o) or not inside(o):
            continue
        v = ctx.rub(o)
        if v is None:
            continue
        root = D.root_name(o)
        tot[root] += v
        cnt[root] += 1
        if D.has_project(o):
            tagged[root] += v
    trip_cats = {c for c in tot if cnt[c] >= cfg["n5_min_ops"] and tot[c] > 0 and tagged[c] / tot[c] >= cfg["n5_share"]}
    out = []
    for o in month_ops:
        if AM.kind(o) == "expense" and not D.excluded(o) and inside(o) and not D.has_project(o) \
                and D.root_name(o) in trip_cats:
            out.append(_hit("N5", m, [o["id"]], detail=_brief(ctx, o)))
    return out


def _n6_hits(D, today, created):
    """N6, один раз на выгрузку: дата в будущем у любой операции; дата старше 2 лет от «сегодня» у операции,
    созданной за последние n6_recent_days (задним числом внесённая давняя — опечатка года). Правка старой
    операции — не признак: владелец правит категории давних лет."""
    cfg, ctx = D.cfg, D.ctx
    out = []
    old = (today - timedelta(days=cfg["n6_old_days"])).isoformat()
    recent = (today - timedelta(days=cfg["n6_recent_days"])).isoformat()
    for o in D.ops:
        dt = o["date"]
        cr = created.get(o["id"]) or ""
        why = "future" if dt > today.isoformat() else ("old" if dt < old and cr >= recent else None)
        if why:
            out.append(_hit("N6", dt[:7], [o["id"]], detail={**_brief(ctx, o), "why": why}))
    return out


def _n7(D, m, month_ops, history):
    ctx, cfg = D.ctx, D.cfg
    known = {k: set(v) for k, v in (history.get("account_currencies") or {}).items()}
    if not known:
        seen = defaultdict(Counter)
        for o in D.ops:
            if o["date"][:7] >= m:
                continue
            for s in (o.get("expense"), o.get("income")):
                if s:
                    a = ctx.acc(s["accountId"])
                    seen[a.get("name")][a.get("instrument")] += 1
        known = {n: {i for i, c in cnt.items()} for n, cnt in seen.items() if sum(cnt.values()) >= cfg["n7_min_ops"]}
    out = []
    for o in month_ops:
        for s in (o.get("expense"), o.get("income")):
            if not s:
                continue
            a = ctx.acc(s["accountId"])
            ok = known.get(a.get("name"))
            if ok and a.get("instrument") not in ok:
                out.append(_hit("N7", m, [o["id"]], detail={**_brief(ctx, o), "currency": a.get("instrument")}))
                break
    return out


def _n10(D, m, month_ops):
    ctx, cfg = D.ctx, D.cfg
    prior = [D.agg(p)["exp"] for p in _prior(m, cfg["history_months"])]
    med = {}
    for cat in set().union(*prior):
        vals = [a[cat] for a in prior if a.get(cat)]
        if len(vals) >= cfg["n10_min_months"]:
            med[cat] = statistics.median(vals)
    out = []
    for o in month_ops:
        if AM.kind(o) != "expense" or o.get("comment") or D.excluded(o) or D.has_project(o) \
                or o["id"] in D.one_off or o.get("merchantId") in D.one_off_m:
            continue
        v = ctx.rub(o)
        c = med.get(D.root_name(o))
        if v is not None and c and v > cfg["n10_factor"] * c and v >= cfg["n10_min_rub"]:
            out.append(_hit("N10", m, [o["id"]], detail={**_brief(ctx, o), "median": round(c, 2)}))
    return out


# ─── сборка ──────────────────────────────────────────────────────────────────

def collect(ops, refs, ctx, history, months, cfg=None, rows_meta=None):
    """Все срабатывания: [{id, month, op_ids, subject, detail}]. `rows_meta` — {id операции: (createdDate, changedDate)} для N6 (без него N6 только про будущие даты). Дубли N1 внутри групп A5 снимаются."""
    cfg = _cfg(cfg)
    history = history or {}
    D = _Data(ops, ctx, cfg)
    today = cfg.get("today") or date.today()
    if isinstance(today, str):
        today = date.fromisoformat(today)
    months = sorted(months)
    hits = []
    for m in months:
        mo = D.by_month.get(m, [])
        hist_ops = [o for o in ops if o["date"] < m + "-01"]
        sk = _skill_checks(D, m, mo, hist_ops)
        hits += sk
        a1 = {i for h in sk if h["id"] == "A1" for i in h["op_ids"]}
        a5 = {i for h in sk if h["id"] == "A5" for i in h["op_ids"]}
        n1 = [h for h in _n1(D, m, mo) if not set(h["op_ids"]) <= a5]
        hits += n1 + _n2(D, m, "exp") + _n2(D, m, "inc") + _n3(D, m, mo, a1) + _n9(D, m) + _b6(D, m) \
            + _places(D, m, mo, history) + _n5(D, m, mo, history, months[0]) + _n7(D, m, mo, history) + _n10(D, m, mo)
    meta = rows_meta or {}
    created = {i: v[0] for i, v in meta.items() if v and v[0]}
    hits += [h for h in _n6_hits(D, today, created) if h["month"] in set(months)]
    return hits


def run_checks(ops, refs, ctx, history, months, cfg=None, rows_meta=None):
    """→ [{id, cls, month, text, count, sample}] по (проверка, месяц); порядок — как в TEXTS, затем месяц."""
    c = _cfg(cfg)
    groups = defaultdict(list)
    for h in collect(ops, refs, ctx, history, months, cfg, rows_meta):
        groups[(h["id"], h["month"])].append(h)
    out = []
    for (id_, m), hs in sorted(groups.items(), key=lambda kv: (ORDER.index(kv[0][0]), kv[0][1])):
        out.append({"id": id_, "cls": c["cls"].get(id_, "hint"), "month": m, "text": TEXTS[id_],
                    "count": len(hs), "sample": [h["detail"] for h in hs[:_SAMPLE]]})
    return out
