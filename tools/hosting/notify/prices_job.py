"""Дневной ряд цен закрытия держимых бумаг и курсов ЦБ — только вперёд (решение владельца 2026-11-11).

Каждый торговый день вечером hub-notify дописывает в Portfolio/prices/daily-ГГГГ.jsonl одну строку:
цены держимых бумаг (qty > 0, без cost_basis и blocked) по последнему снапшоту и курсы ЦБ валют номинала
держимых облигаций. Истории назад не собираем. Стоимость портфеля и XIRR не пишем — только цены (стоимость
вьюер считает сам из цен и позиций).

Строка: {"date", "recorded_at", "fx", "items": {ключ: {"close", "kind"[, "accrued", "face", "face_unit"]}}, "missing"}
Ключ — ticker как в снапшоте; бумага ищется по SECID, иначе по ISIN (как bondItem вьюера). Акции и фонды —
close и kind; облигации — ещё НКД, номинал и валюта номинала (null, если ISS не отдал).

Повтор даты: строка этой даты уже есть — НЕ пишем (ни вторую, ни замену): ряд append-only, старые строки не
трогаются. Цена, записанная в 19:00, не перетирается более поздним срезом.
Не торговый день: котировки — закрытие прошлой сессии (большинство prev_close), строки нет, статус skip.
Запись: файл целиком через hub-api /api/job/save с base_hash (jobs.save); писатель — только hub-notify.
Только stdlib.
"""
import json
import urllib.request
from collections import Counter
from datetime import datetime

import jobs

FOLDER = "Portfolio/prices"
TRADED = ("last", "market")           # вид цены, говорящий «сегодня торговалось»


def path_for(day):
    return f"{FOLDER}/daily-{day[:4]}.jsonl"


def holdings(root):
    """Держимые бумаги последнего снапшота: qty > 0, цена не cost_basis, не заблокирована. → список holdings."""
    import decisions_read          # из _shared-references: notifier добавляет путь в sys.path после своих импортов
    snaps = decisions_read.snapshot_files(str(root))
    if not snaps:
        return []
    with open(snaps[-1][1], encoding="utf-8") as f:
        snap = json.load(f)
    out = []
    for h in snap.get("holdings") or []:
        if not isinstance(h, dict) or not h.get("ticker") or not decisions_read._qty_pos(h):
            continue
        if h.get("is_blocked") or h.get("status") == "blocked":
            continue
        # только бумаги с биржевой оценкой (moex_*): cost_basis — замороженные, last_trade — внебиржевые (FINAMAR,
        # стоимость вручную) — их цены на MOEX нет, иначе каждый день «missing» и статус partial
        if not str(h.get("current_price_source") or "").startswith("moex"):
            continue
        out.append(h)
    return out


def fx_codes(hs):
    """Валюты номинала держимых облигаций кроме рубля (как liveFxParam вьюера)."""
    cur = set()
    for h in hs:
        c = str(h.get("nominal_currency") or "").strip().upper()
        if h.get("asset_type") == "bond" and len(c) == 3 and c.isalpha() and c not in ("RUB", "SUR"):
            cur.add(c)
    return sorted(cur)[:10]


def quotes_url(base, hs):
    codes = fx_codes(hs)
    return base + ("&fx=" + ",".join(codes) if codes else "")


def fetch_quotes(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        q = json.loads(r.read().decode("utf-8"))
    if q.get("schema") != "quotes@1" or not isinstance(q.get("items"), dict):
        raise ValueError("ответ не quotes@1")
    return q


def build_row(hs, quotes, now):
    """→ (строка дня или None, причина пропуска). Дата строки — дата торгов из котировок, не дата запуска."""
    items = quotes.get("items") or {}
    by_isin = {i["isin"]: i for i in items.values() if isinstance(i, dict) and i.get("isin")}
    out, missing, traded_days = {}, [], Counter()
    kinds = Counter()
    for h in hs:
        key = h["ticker"]
        it = items.get(key) or by_isin.get(h.get("isin") or key)
        if not it or it.get("price") is None:
            missing.append(key)
            continue
        row = {"close": it["price"], "kind": it.get("price_kind")}
        if h.get("asset_type") == "bond":
            row.update({"accrued": it.get("accrued_int"), "face": it.get("face_value"),
                        "face_unit": it.get("face_unit")})
        out[key] = row
        kinds[it.get("price_kind")] += 1
        if it.get("price_kind") in TRADED and it.get("ts"):
            traded_days[str(it["ts"])[:10]] += 1
    if not out:
        return None, "нет ни одной цены"
    today = now.date().isoformat()
    n_traded = sum(traded_days.values())
    if now.weekday() >= 5 or n_traded * 2 < len(out) or traded_days.most_common(1)[0][0] != today:
        return None, "не торговый день: котировки — закрытие прошлой сессии"
    fx = quotes.get("fx") if isinstance(quotes.get("fx"), dict) else {}
    return {"date": today, "recorded_at": jobs.now_iso(now), "fx": fx, "items": out, "missing": missing}, None


def run(root, base_url, now, fetch=None, read=None, save=None):
    """→ итог для журнала (status: ok | skip | partial). Сеть и запись подменяются в тестах."""
    read = read or jobs.read
    save = save or jobs.save
    hs = holdings(root)
    if not hs:
        return {"status": "skip", "reason": "нет держимых бумаг в снапшоте"}
    q = (fetch or fetch_quotes)(quotes_url(base_url, hs))
    row, why = build_row(hs, q, now)
    if row is None:
        return {"status": "skip", "reason": why}
    path = path_for(row["date"])
    # читаем файл, добавляем строку и пишем целиком; jobs.save берёт base_hash и при 409 повторяет с новым хэшем
    # (писатель один — hub-notify). Строка этой даты уже есть — не пишем
    content, _ = read(path)
    lines = [ln for ln in (content or "").split("\n") if ln.strip()]
    for ln in lines:
        if json.loads(ln).get("date") == row["date"]:
            return {"status": "skip", "reason": "строка этой даты уже есть", "date": row["date"]}
    lines.append(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
    save(path, "\n".join(lines) + "\n")
    return {"status": "partial" if row["missing"] else "ok", "date": row["date"], "items": len(row["items"]),
            "missing": row["missing"], "fx": sorted(k for k in row["fx"] if k != "date")}
