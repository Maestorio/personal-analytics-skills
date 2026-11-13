"""Цены US eShop для «Присматриваюсь» (API-1, PR-8 брифа docs/api-migration/implementation-brief.md).

Вход — Gaming/watchlist.yaml + оверлей Gaming/user-state.json (оверлей главнее: пороги, nsuid, добавление и снятие игр): статусы «хочу» и «на-карандаш» (в том числе с флагом `demo: true`), у которых есть `nsuid_us`
(nsuid заполняет tools/eshop_lookup.py по ссылке на страницу игры в US eShop; пороги —
`price_target_usd` (цена ≤ $X) и `discount_target_pct` (скидка ≥ N%), выполнен любой из двух). Выход — Gaming/eshop-prices.json (схема eshop-prices@1), пишет hub-api.

Источник — api.ec.nintendo.com/v1/price?country=US (ответ: tools/tests/fixtures/eshop/):
цены строками в raw_value, скидка — discount_price с start/end_datetime (UTC), неизвестный
nsuid — sales_status «not_found», не больше 50 id в запросе (51 → HTTP 400 code 4004).
Работает и с NAS в России (проверено владельцем 2026-10-21: HTTP 200).

Ошибка источника НЕ стирает прошлые цены и не выдаёт их за свежие: файл переписывается
со status «unavailable», прошлыми items и прошлым fetched_at (время цен), а время попытки
и ошибка — в attempt_at / error. Скилл game-advisor доверяет файлу 24 ч по fetched_at.

Только stdlib (+ PyYAML из hub-notify для watchlist).
"""
import json
import re
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone

API = "https://api.ec.nintendo.com/v1/price?country=US&lang=en&ids="
BATCH = 50
WATCH_STATUSES = ("хочу", "на-карандаш", "демо")   # «демо» — старое значение: читается как на-карандаш + флаг demo
PATH = "Gaming/eshop-prices.json"
SCHEMA = "eshop-prices@1"


OVERLAY_PATH = "Gaming/user-state.json"
OVERLAY_ON = ("хочу", "на-карандаш", "демо")   # «демо» — старое значение, см. _eff_state


def _eff_state(o):
    """Состояние записи оверлея по новому контракту: старое «демо» = на-карандаш (не-интересно при оценке «не понравилось»)
    + флаг demo; сам флаг на состояние не влияет."""
    st = str(o.get("state") or "").strip()
    if st == "демо":
        return "не-интересно" if o.get("rating") == "не понравилось" else "на-карандаш"
    return st


def gaming_key(title):
    """Ключ игры в оверлее (копия gaming_key из hub-api: server.py сюда не импортируется)."""
    t = unicodedata.normalize("NFKC", str(title or "")).casefold()
    t = re.sub(r"[’'`´]", "", t)
    t = re.sub(r"[^\w]+", " ", t, flags=re.UNICODE)
    return " ".join(t.split())


def _target(it, status, source):
    nsuid = str(it.get("nsuid_us") or "").strip()
    tgt, pct = it.get("price_target_usd"), it.get("discount_target_pct")
    return {"title": it.get("title"), "store_title": it.get("store_title"), "nsuid_us": nsuid,
            "watch_status": status, "source": source,
            "price_target_usd": float(tgt) if isinstance(tgt, (int, float)) and not isinstance(tgt, bool) else None,
            "discount_target_pct": abs(int(pct)) if isinstance(pct, (int, float)) and not isinstance(pct, bool) else None}


def targets(watchlist, user_state=None):
    """watchlist.yaml + оверлей gaming-user@1 → ([цели с nsuid], [пропущенные с причиной]).
    Оверлей главнее: «хочу»/«на-карандаш» (в т. ч. с флагом demo; старое «демо» читается как на-карандаш) (не deleted) переопределяет запись watchlist с тем же
    ключом и добавляет новые игры; любое другое состояние убирает игру из целей."""
    over = {}
    for it in (user_state or {}).get("items") or []:
        if isinstance(it, dict) and gaming_key(it.get("title")):
            over[gaming_key(it.get("title"))] = it
    out, skipped, seen = [], [], set()

    def add(cand, title):
        if str(cand.get("nsuid_us") or "").strip().isdigit():
            out.append(cand)
        else:
            skipped.append({"title": title, "reason": "нет nsuid_us"})

    for it in (watchlist or {}).get("items") or []:
        if not isinstance(it, dict) or str(it.get("status") or "").strip() not in WATCH_STATUSES:
            continue
        k = gaming_key(it.get("title"))
        seen.add(k)
        o = over.get(k)
        if o is not None:
            continue                                    # решает оверлей (ниже)
        add(_target(it, str(it.get("status")).strip(), "watchlist"), it.get("title"))
    for k, o in over.items():
        st = _eff_state(o)
        if o.get("deleted") is True or st not in OVERLAY_ON:
            continue
        base = {}
        for w in (watchlist or {}).get("items") or []:
            if isinstance(w, dict) and gaming_key(w.get("title")) == k:
                base = w
                break
        merged = {**base, **{f: o[f] for f in ("title", "nsuid_us", "store_title", "price_target_usd",
                                               "discount_target_pct") if o.get(f) not in (None, "")}}
        add(_target(merged, st, "overlay"), o.get("title"))
    return out, skipped


def _money(p):
    try:
        return round(float((p or {}).get("raw_value")), 2)
    except (TypeError, ValueError):
        return None


def parse(resp, now):
    """Ответ API → {nsuid: цена}. Сменился формат (нет списка prices) → ValueError."""
    if not isinstance(resp, dict) or not isinstance(resp.get("prices"), list):
        raise ValueError("формат ответа eShop изменился: нет списка prices")
    out = {}
    for p in resp["prices"]:
        nsuid = str(p.get("title_id") or "")
        if not nsuid:
            continue
        reg = _money(p.get("regular_price"))
        d = p.get("discount_price") or {}
        sale, end = _money(d), d.get("end_datetime")
        start = d.get("start_datetime")
        now_utc = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if now.tzinfo else None
        if sale is not None and now_utc and ((start and start > now_utc) or (end and end < now_utc)):
            sale, end = None, None                     # скидка ещё не началась или уже кончилась
        out[nsuid] = {"sales_status": p.get("sales_status"), "regular_usd": reg, "sale_usd": sale,
                      "discount_pct": round((1 - sale / reg) * 100) if sale is not None and reg else None,
                      "sale_end": end}
    return out


def fetch(nsuids, opener=urllib.request.urlopen, timeout=30):
    """Цены пачками по BATCH. Любая ошибка пачки — исключение: частичный ответ хуже ясного
    «источник недоступен» (страница показала бы часть игр без цены как будто так и есть)."""
    res = {}
    for i in range(0, len(nsuids), BATCH):
        with opener(API + ",".join(nsuids[i:i + BATCH]), timeout=timeout) as r:
            res.setdefault("_raw", []).append(json.loads(r.read().decode("utf-8")))
    return res.get("_raw", [])


def report(tg, skipped, responses, now):
    prices = {}
    for resp in responses:
        prices.update(parse(resp, now))
    items = []
    for t in tg:
        p = prices.get(t["nsuid_us"]) or {"sales_status": "not_found", "regular_usd": None, "sale_usd": None,
                                          "discount_pct": None, "sale_end": None}
        # not_found — цены нет; preorder и прочие статусы с ценой — цена показывается со статусом
        # (Metaphor: ReFantazio для Switch 2 на 21.10 — preorder)
        cur = p["sale_usd"] if p["sale_usd"] is not None else p["regular_usd"]
        met = ((t["price_target_usd"] is not None and cur is not None and cur <= t["price_target_usd"] + 1e-9)
               or (t["discount_target_pct"] is not None and (p["discount_pct"] or 0) >= t["discount_target_pct"]))
        items.append({**t, **p, "price_usd": cur, "target_met": met})
    return {"schema": SCHEMA, "fetched_at": now.isoformat(timespec="seconds"), "attempt_at": None,
            "status": "ok", "error": None, "source": "api.ec.nintendo.com/v1/price country=US",
            "items": items, "skipped": skipped}


def unavailable(prev, error, now):
    """Источник упал: прошлые цены остаются с прошлым временем, попытка и ошибка — рядом."""
    base = prev if isinstance(prev, dict) and prev.get("schema") == SCHEMA else {
        "schema": SCHEMA, "fetched_at": None, "items": [], "skipped": [],
        "source": "api.ec.nintendo.com/v1/price country=US"}
    return {**base, "status": "unavailable", "attempt_at": now.isoformat(timespec="seconds"),
            "error": str(error)[:300]}


def _until(i):
    end = i.get("sale_end") or ""
    return f" до {end[8:10]}.{end[5:7]}" if len(end) >= 10 else ""


def _thresholds(i):
    """Пороги записи словами: «$10.00 или −50%»; порогов нет — ""."""
    parts = ([f"${i['price_target_usd']:.2f}"] if i.get("price_target_usd") is not None else []) + \
            ([f"−{i['discount_target_pct']}%"] if i.get("discount_target_pct") is not None else [])
    return " или ".join(parts)


TITLE_MAX = 32   # заголовок уведомления: в свёрнутом виде на телефоне видна одна строка


def _name(i):
    return i.get("store_title") or i.get("title") or i["nsuid_us"]


def _headline(i):
    """«Undertale −34%: $9.89» — одинаково у скидки и у порога; длинное имя обрезается, цена остаётся."""
    pct = f" −{i['discount_pct']}%" if i.get("discount_pct") else ""
    tail = f"{pct}: ${i['price_usd']:.2f}"
    name = _name(i)
    if len(name) + len(tail) > TITLE_MAX:
        name = name[: max(TITLE_MAX - len(tail) - 1, 4)].rstrip() + "…"
    return name + tail


def _lasts(i):
    return f" · {_until(i).strip()}" if _until(i) else ""


def target_events(prev, cur, url="/tools/games.html#sale"):
    """Порог (цена ≤ $X или скидка ≥ N%) впервые выполнен → событие push (вид «eshop»).
    Текст тот же, что у скидки, плюс «порог выполнен»: про эту скидку отдельного «eshop_sale»
    не будет. Ключ включает конец скидки: та же игра в следующую распродажу — новое событие."""
    was = {i["nsuid_us"] for i in (prev or {}).get("items") or [] if i.get("target_met")}
    evs = []
    for i in cur.get("items") or []:
        if not i.get("target_met") or i["nsuid_us"] in was:
            continue
        end = i.get("sale_end") or ""
        evs.append({"key": f"eshop:{i['nsuid_us']}:{end[:10] or i['price_usd']}",
                    "title": _headline(i),
                    "body": f"Порог {_thresholds(i)} выполнен" + _was(i) + _lasts(i) + "\nИгры → Присматриваюсь",
                    "line": f"{_name(i)} — порог выполнен",
                    "url": url, "kind": "eshop"})
    return evs


def _was(i):
    return f" · было ${i['regular_usd']:.2f}" if i.get("sale_usd") is not None and i.get("regular_usd") else ""


def _sale_key(i):
    return (i.get("sale_end") or "")[:10] or f"{i.get('sale_usd')}"


def sale_events(prev, cur, url="/tools/games.html#sale"):
    """Игра ушла в скидку (в прошлом файле скидки не было или была другая — по концу скидки)
    → событие push (вид «eshop_sale») — у ЛЮБОЙ игры списка, с порогом и без. Порог выполнен
    раньше — «порог выполнен» в тексте; не достигнут — каким он был. Игра, у которой порог
    впервые выполнен в этот же прогон, здесь пропускается: её скидка — в уведомлении «eshop»."""
    was = {i["nsuid_us"]: _sale_key(i) for i in (prev or {}).get("items") or []
           if i.get("sale_usd") is not None}
    met = {i["nsuid_us"] for i in (prev or {}).get("items") or [] if i.get("target_met")}
    evs = []
    for i in cur.get("items") or []:
        if i.get("sale_usd") is None or was.get(i["nsuid_us"]) == _sale_key(i):
            continue
        if i.get("target_met") and i["nsuid_us"] not in met:
            continue
        th = _thresholds(i)
        note = (f" · порог {th} выполнен" if i.get("target_met") else f" · до порога {th} не дотянула") if th else ""
        evs.append({"key": f"eshop-sale:{i['nsuid_us']}:{_sale_key(i)}",
                    "title": _headline(i),
                    "body": "Скидка в US eShop" + _was(i) + note + _lasts(i) + "\nИгры → Присматриваюсь",
                    "line": f"{_name(i)}{(' −' + str(i['discount_pct']) + '%') if i.get('discount_pct') else ''} · ${i['price_usd']:.2f}",
                    "url": url, "kind": "eshop_sale"})
    return evs


def sale_summary(evs):
    """Несколько скидок за прогон — одним уведомлением (распродажи Nintendo идут пачками)."""
    if len(evs) == 1:
        return None
    n = len(evs)
    word = "игру" if n % 10 == 1 and n % 100 != 11 else "игры" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "игр"
    lines = ["• " + (e.get("line") or e["title"]) for e in evs[:4]] + ([f"• и ещё {n - 4}"] if n > 4 else [])
    return {"key": "eshop-sale", "title": f"Скидки на {n} {word}",
            "body": "\n".join(lines)[:180], "url": evs[0]["url"]}


def run(load_watchlist, read, save, now, opener=urllib.request.urlopen):
    """Один прогон. → (отчёт, события, итог для журнала). read/save — jobs.read/jobs.save."""
    prev_txt, _ = read(PATH)
    try:
        prev = json.loads(prev_txt) if prev_txt else None
    except ValueError:
        prev = None
    try:
        ov_txt, _ = read(OVERLAY_PATH)
        overlay = json.loads(ov_txt) if ov_txt else None
    except Exception:            # noqa: BLE001 — оверлей необязателен: не прочитался (в т.ч. SaveError hub-api) → цены по watchlist
        overlay = None
    tg, skipped = targets(load_watchlist(), overlay if isinstance(overlay, dict) else None)
    if not tg:
        rep = report([], skipped, [], now)
        save(PATH, json.dumps(rep, ensure_ascii=False, indent=1))
        return rep, [], {"status": "ok", "items": 0, "skipped": len(skipped)}
    try:
        rep = report(tg, skipped, fetch([t["nsuid_us"] for t in tg], opener), now)
    except (OSError, ValueError, urllib.error.URLError) as e:
        rep = unavailable(prev, e, now)
        save(PATH, json.dumps(rep, ensure_ascii=False, indent=1))
        return rep, [], {"status": "error", "error": str(e)[:300], "items": len(tg)}
    save(PATH, json.dumps(rep, ensure_ascii=False, indent=1))
    evs = target_events(prev, rep)
    sales = sale_events(prev, rep)
    st = [i["sales_status"] for i in rep["items"]]
    return rep, evs + sales, {"status": "ok", "items": len(tg), "not_found": st.count("not_found"),
                      "preorder": st.count("preorder"), "skipped": len(skipped),
                      "on_sale": sum(1 for i in rep["items"] if i.get("sale_usd") is not None),
                      "target_met": len(evs), "new_sale": len(sales)}


def fresh(rep, now, hours=24):
    """Цены моложе hours — правило доверия скилла (game-advisor, 24 ч)."""
    try:
        return (now - datetime.fromisoformat(rep["fetched_at"])).total_seconds() < hours * 3600
    except (KeyError, TypeError, ValueError):
        return False
