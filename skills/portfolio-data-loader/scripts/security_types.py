#!/usr/bin/env python3
"""
security_types.py — тип бумаги (акция / облигация / фонд) с Мосбиржи и справочник типов.

Зачем: эвристика portfolio_returns.classify_instrument_type видит только историю сделок
(фонд без выплат падает в «акцию»). Группа бумаги на Мосбирже однозначна. Сеть — ТОЛЬКО при
сборке на сайте (build_snapshot.py, шаг security_types); скилл на Маке читает справочник
Portfolio/security-types.json и в ISS не ходит.

Справочник: {"schema_version": "security-types@1.0", "updated_at": ISO, "by_ticker": {T: {...}}}
  найден:    {"type": "fund", "moex_type": "etf_ppif", "moex_group": "stock_etf", "isin": …,
              "fetched_at": "YYYY-MM-DD", "source": "moex_iss"}   — не перепроверяется
  облигация: + "bond": {"sectype", "typename", "matdate", "faceunit", "facevalue", "is_floater",
              "issuer_type"}  (parse_bond_attrs; запись без блока "bond" дозапрашивается)
  нет на бирже: {"type": null, "source": "moex_iss", "fetched_at": …, "note": "нет на Мосбирже"}
              — перепроверка раз в 90 дней

Признаки облигации (ISS description, все проверяемы по тому же ответу):
  issuer_type — "ofz" если ISSUENAME содержит «облигации федерального займа» (эмитент Минфин РФ);
                "gov_other" — TYPENAME «Государственная облигация» без этой фразы (иностранный суверен,
                регион: Казахстан-11 имеет TYPE ofz_bond, но ОФЗ не является); иначе "corp".
  is_floater  — ISSUENAME/NAME содержат «переменным купон», «плавающ» или «ОФЗ-ПК» (ОФЗ-ПК 29xxx). Корпоративный
                флоатер, у которого формула ставки не вынесена в название, так не видно — для него корзину
                задаёт рейтинг.
  faceunit    — SUR → RUB, остальное как есть (USD/EUR/CNY).

CLI:
  security_types.py refresh --cache PATH --tickers A,B,C [--today YYYY-MM-DD] [--offline]
      → JSON {"online", "fetched": [...], "failed": [...]} в stdout
  security_types.py show --cache PATH

Только stdlib.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# Время МСК (`time_msk.py`) — канон в _shared-references/; в упакованном .skill — рядом (pack.sh).
_SHARED = Path(__file__).resolve().parents[3] / "_shared-references"
if _SHARED.is_dir() and str(_SHARED) not in sys.path:
    sys.path.append(str(_SHARED))
import time_msk  # noqa: E402

SCHEMA = "security-types@1.0"
ISS_URL = "https://iss.moex.com/iss/securities/{secid}.json?iss.meta=off&iss.only=description"
TIMEOUT = 10
RECHECK_DAYS = 90
MAX_CONSECUTIVE_FAILS = 5          # ISS лёг: остальные тикеры не ждём по 10 с каждый
NOT_ON_MOEX_NOTE = "нет на Мосбирже"

MOEX_GROUP_TO_TYPE = {
    "stock_shares": "stock", "stock_dr": "stock", "stock_foreign_shares": "stock",
    "stock_bonds": "bond", "stock_eurobond": "bond",
    "stock_etf": "fund", "stock_ppif": "fund",
}


def group_to_type(group: str | None) -> str:
    return MOEX_GROUP_TO_TYPE.get(group or "", "other")


def _ssl_context():
    """SSL-контекст с certifi-бандлом, если доступен (как market_series._ssl_context)."""
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


BOND_GROUPS = ("stock_bonds", "stock_eurobond")
_OFZ_PHRASE = "облигации федерального займа"
_FLOATER_MARKS = ("переменным купон", "плавающ", "офз-пк")


def _to_float(v):
    try:
        return float(str(v).replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        return None


def parse_bond_attrs(kv: dict) -> dict:
    """Блок "bond" из пар name→value description (чистая функция)."""
    issue = str(kv.get("ISSUENAME") or "").lower()
    name = str(kv.get("NAME") or "").lower()
    typename = kv.get("TYPENAME")
    if _OFZ_PHRASE in issue:
        issuer = "ofz"
    elif "государственн" in str(typename or "").lower():
        issuer = "gov_other"
    else:
        issuer = "corp"
    unit = str(kv.get("FACEUNIT") or "").strip().upper()
    unit = {"SUR": "RUB", "RUR": "RUB"}.get(unit, unit) or None
    mat = str(kv.get("MATDATE") or "")[:10]
    return {
        "sectype": kv.get("TYPE"), "typename": typename,
        "matdate": mat if len(mat) == 10 and mat[4] == "-" and mat[7] == "-" else None,
        "faceunit": unit, "facevalue": _to_float(kv.get("FACEVALUE")),
        "is_floater": any(m in issue or m in name for m in _FLOATER_MARKS),
        "issuer_type": issuer,
    }


def parse_description(js: dict) -> dict | None:
    """Ответ ISS securities/{secid}.json (description) → {type, moex_type, moex_group, isin[, bond]}
    или None, если бумаги на бирже нет (пустая description)."""
    d = (js or {}).get("description") or {}
    rows = d.get("data") or []
    if not rows:
        return None
    cols = d.get("columns") or ["name", "title", "value"]
    try:
        i_name, i_val = cols.index("name"), cols.index("value")
    except ValueError:
        i_name, i_val = 0, 2
    kv = {}
    for r in rows:
        if len(r) > max(i_name, i_val):
            kv[str(r[i_name])] = r[i_val]
    group = kv.get("GROUP")
    if not group and not kv.get("TYPE"):
        return None
    out = {"type": group_to_type(group), "moex_type": kv.get("TYPE"), "moex_group": group,
           "isin": kv.get("ISIN")}
    if group in BOND_GROUPS:
        out["bond"] = parse_bond_attrs(kv)
    return out


def fetch_type(secid: str, timeout: int = TIMEOUT) -> dict | None:
    """Один запрос к ISS. None — бумаги на бирже нет; сетевая ошибка — исключение."""
    url = ISS_URL.format(secid=urllib.parse.quote(secid, safe=""))
    with urllib.request.urlopen(url, timeout=min(timeout, TIMEOUT), context=_ssl_context()) as r:
        js = json.load(r)
    return parse_description(js)


def load_types(path) -> dict:
    """Справочник; нет файла / битый — пустой справочник."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    if not isinstance(data.get("by_ticker"), dict):
        data["by_ticker"] = {}
    data.setdefault("schema_version", SCHEMA)
    return data


def save_types(path, data: dict) -> None:
    """Атомарно: tmp + replace."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = dict(data)
    data["schema_version"] = SCHEMA
    data["updated_at"] = time_msk.now_iso()
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)


def overrides_from(data: dict) -> dict[str, str]:
    """Тикер → stock|bond|fund (other и None эвристику не переопределяют)."""
    out = {}
    for t, e in (data.get("by_ticker") or {}).items():
        if isinstance(e, dict) and e.get("type") in ("stock", "bond", "fund"):
            out[t] = e["type"]
    return out


def needs_fetch(entry: dict | None, today: dt.date) -> bool:
    if not isinstance(entry, dict):
        return True
    if entry.get("type") is None:                       # «нет на бирже» — раз в 90 дней
        try:
            age = (today - dt.date.fromisoformat(str(entry.get("fetched_at"))[:10])).days
        except ValueError:
            return True
        return age >= RECHECK_DAYS
    if entry.get("type") == "bond" and not isinstance(entry.get("bond"), dict):
        return True                                     # запись до блока "bond" — дозапросить один раз
    return False


def refresh_types(path, tickers, online: bool, today=None, errors: list | None = None):
    """→ (data, fetched, failed). offline — только читает; online — спрашивает тикеры, которых
    нет в справочнике (и «нет на бирже» старше 90 дней). Ошибка одного тикера — в failed;
    ошибка записи справочника — все в failed, текст — в errors (если передан список)."""
    if today is None:
        today = dt.date.today()
    elif isinstance(today, str):
        today = dt.date.fromisoformat(today)
    data = load_types(path)
    fetched, failed = [], []
    if not online:
        return data, fetched, failed
    by = data["by_ticker"]
    todo = [t for t in dict.fromkeys(tickers) if t and needs_fetch(by.get(t), today)]
    streak = 0
    for i, t in enumerate(todo):
        if streak >= MAX_CONSECUTIVE_FAILS:
            failed.extend(todo[i:])
            break
        try:
            res = fetch_type(t)
        except Exception:                                # noqa: BLE001 — сеть: любая ошибка = failed
            failed.append(t)
            streak += 1
            continue
        streak = 0
        if res is None:
            by[t] = {"type": None, "source": "moex_iss", "fetched_at": today.isoformat(),
                     "note": NOT_ON_MOEX_NOTE}
        else:
            by[t] = {**res, "fetched_at": today.isoformat(), "source": "moex_iss"}
        fetched.append(t)
    if fetched:
        try:
            save_types(path, data)
        except OSError as e:
            # справочник не записался (том только на чтение: hub-notify /srv, 2026-10-28) — дочерние шаги
            # его не увидят, поэтому честно: ничего не получено, все тикеры в failed; причина — в errors
            if errors is not None:
                errors.append(f"справочник не записан: {type(e).__name__}: {e}")
            failed, fetched = fetched + failed, []
    return data, fetched, failed


# ───────────────────────────── сверка типов ─────────────────────────────

SURE_TYPES = ("stock", "bond", "fund")


def compare_types(holdings, prev_holdings, moex_by_ticker, heur_by_ticker) -> list[dict]:
    """Чистая сверка типов бумаг нового снапшота.
    holdings / prev_holdings — списки holdings снапшота; moex_by_ticker — тикер → stock|bond|fund
    (из справочника); heur_by_ticker — тикер → тип эвристики БЕЗ переопределений.
    reason: prev_vs_now (тип сменился против прошлого снапшота) или moex_vs_heuristic
    (бумага новая, биржа и эвристика разошлись — сработала биржа)."""
    prev_list = [h for h in (prev_holdings or []) if isinstance(h, dict)]
    by_acc = {(h.get("account"), h.get("ticker")): h for h in prev_list if h.get("ticker")}
    by_isin = {h["isin"]: h for h in prev_list if h.get("isin") and h.get("asset_type") == "bond"}
    by_tk = {}
    for h in prev_list:
        by_tk.setdefault(h.get("ticker"), h)
    out, seen = [], set()
    for h in holdings or []:
        tk, now = h.get("ticker"), h.get("asset_type")
        if not tk or not now:
            continue
        key = (h.get("account"), tk)
        if key in seen:
            continue
        seen.add(key)
        p = by_acc.get(key)
        if p is None and h.get("isin") and now == "bond":
            p = by_isin.get(h["isin"])
        if p is None:
            p = by_tk.get(tk)
        was = p.get("asset_type") if p else None
        moex = moex_by_ticker.get(tk)
        heur = heur_by_ticker.get(tk)
        reason = None
        if p is not None:
            if was and was != now:
                reason = "prev_vs_now"
        elif moex in SURE_TYPES and heur and heur != moex:
            reason = "moex_vs_heuristic"
        if reason:
            out.append({"ticker": tk, "name": h.get("name"), "was": was, "now": now,
                        "moex": moex, "heur": heur, "reason": reason})
    return out


TYPE_RU = {"stock": "акция", "bond": "облигация", "fund": "фонд", "other": "другое"}


def change_text(c: dict) -> str:
    """«TMON: был акция, стал фонд (по бирже)» — для флага снапшота."""
    now = TYPE_RU.get(c.get("now"), c.get("now"))
    src = " (по бирже)" if c.get("moex") == c.get("now") and c.get("moex") else ""
    if c.get("reason") == "prev_vs_now":
        return f"{c['ticker']}: был {TYPE_RU.get(c.get('was'), c.get('was'))}, стал {now}{src}"
    return (f"{c['ticker']}: новая бумага, по бирже {TYPE_RU.get(c.get('moex'), c.get('moex'))}, "
            f"по сделкам {TYPE_RU.get(c.get('heur'), c.get('heur'))}")


# ───────────────────────────── CLI ─────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("refresh", help="дополнить справочник типами с Мосбиржи")
    r.add_argument("--cache", required=True)
    r.add_argument("--tickers", required=True, help="через запятую")
    r.add_argument("--today", default=None)
    r.add_argument("--offline", action="store_true", help="только прочитать справочник")
    s = sub.add_parser("show", help="показать справочник")
    s.add_argument("--cache", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "show":
        for t, e in sorted(load_types(a.cache)["by_ticker"].items()):
            print(f"{t}\t{e.get('type')}\t{e.get('moex_group') or e.get('note') or ''}")
        return 0
    tickers = [t.strip() for t in a.tickers.split(",") if t.strip()]
    errors: list[str] = []
    _, fetched, failed = refresh_types(a.cache, tickers, not a.offline, a.today, errors=errors)
    print(json.dumps({"online": not a.offline, "fetched": fetched, "failed": failed, "errors": errors},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
