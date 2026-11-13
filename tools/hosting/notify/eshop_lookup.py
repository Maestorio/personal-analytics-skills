"""Поиск игры в US eShop для сайта: nsuid, название, платформа, обложка (без LLM).

Страница https://www.nintendo.com/us/store/products/<slug>/ несёт в <script id="__NEXT_DATA__">
объект Product с urlKey == slug и полем nsuid; чужие nsuid (похожие игры) игнорируются.
Обложка: картинка товара в том же объекте (productImage / productImageSquare / boxart / image …)
— в виде строки-URL, объекта {publicId, url} или списка таких; publicId превращается в
https://assets.nintendo.com/image/upload/f_auto/q_auto/c_scale,w_400/<publicId>.
ФОРМАТ ПОЛЯ ОБЛОЖКИ ПРОВЕРИТЬ НА NAS: из среды разработки nintendo.com недоступен, поэтому парсер
терпимый — нет картинки → cover_url None, остальное работает.

Steam (platforms steam/steam_deck/pc): публичный storesearch без ключа, steam_lookup(); lookup_any() —
единая точка по платформе. ФОРМАТ ОТВЕТА STORESEARCH (items[]: id, name, tiny_image) — по документации,
ПРОВЕРИТЬ НА NAS.

Перенос из tools/eshop_lookup.py (CLI на Mac остаётся, делает fill по watchlist.yaml).
Только stdlib; hub-notify вызывает lookup() из POST /internal/nsuid-lookup.
"""
from __future__ import annotations

import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://www.nintendo.com/us/store/products/"
IMG = "https://assets.nintendo.com/image/upload/f_auto/q_auto/c_scale,w_400/"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Safari/605.1.15"
TIMEOUT = 15
NEXT_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
IMAGE_KEYS = ("productImage", "productImageSquare", "boxArt", "boxart", "image", "heroBanner", "squareHeroBanner")


def slug_of(url_or_slug: str) -> str:
    s = url_or_slug.strip().rstrip("/")
    return s.rsplit("/products/", 1)[-1].split("?")[0].strip("/") if "/" in s else s


def slugify(title: str) -> str:
    t = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    t = t.lower().replace("&", " and ").replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def candidates(title: str, platform: str | None = None) -> list[str]:
    base = slugify(title)
    if not base:
        return []
    order = ["switch-2", "switch"] if platform == "switch_2" else ["switch", "switch-2"]
    return [f"{base}-{suf}" for suf in order]


def _img_url(v) -> str | None:
    """Строка-URL | {publicId|url} | список → https-URL картинки или None."""
    if isinstance(v, list):
        for x in v:
            r = _img_url(x)
            if r:
                return r
        return None
    if isinstance(v, str):
        return v if v.startswith("https://") else None
    if isinstance(v, dict):
        pid = v.get("publicId")
        if isinstance(pid, str) and pid.strip():
            return IMG + pid.strip().lstrip("/")
        u = v.get("url")
        return u if isinstance(u, str) and u.startswith("https://") else None
    return None


def cover_of(product: dict) -> str | None:
    for k in IMAGE_KEYS:
        r = _img_url(product.get(k))
        if r:
            return r
    return None


def extract(html: str, slug: str) -> dict | None:
    """__NEXT_DATA__ → {nsuid_us, store_title, eshop_url, cover_url, platform} объекта с urlKey == slug."""
    m = NEXT_RE.search(html or "")
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return None
    stack = [data]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            if o.get("urlKey") == slug and o.get("nsuid"):
                plat = o.get("platform") or {}
                return {"nsuid_us": str(o["nsuid"]), "store_title": str(o.get("name") or "").strip(),
                        "eshop_url": f"{BASE}{slug}/", "cover_url": cover_of(o),
                        "platform": plat.get("code") if isinstance(plat, dict) else None}
            stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)
    return None


def fetch(slug: str, timeout: int = TIMEOUT) -> str | None:
    """HTML страницы; 404 → None; сеть/прочие коды → исключение (URLError/HTTPError/OSError)."""
    req = urllib.request.Request(f"{BASE}{slug}/", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def lookup(url_or_title: str, getter=fetch, platform: str | None = None) -> dict | None:
    """Ссылка/slug или название → результат extract или None (нет в US eShop). Сетевая ошибка — исключение."""
    q = (url_or_title or "").strip()
    if not q:
        return None
    if "/products/" in q or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", q):
        slugs = [slug_of(q)]
    else:
        slugs = candidates(q, platform)
    for slug in slugs:
        html = getter(slug)
        hit = extract(html, slug) if html else None
        if hit:
            return hit
    return None


# ── Steam ────────────────────────────────────────────────────────────────────
STEAM_SEARCH = "https://store.steampowered.com/api/storesearch/?term={term}&cc=us&l=en"
STEAM_COVER = "https://cdn.cloudflare.steamstatic.com/steam/apps/{id}/library_600x900.jpg"
STEAM_COVER_FALLBACK = "https://cdn.cloudflare.steamstatic.com/steam/apps/{id}/header.jpg"
STEAM_APP = "https://store.steampowered.com/app/{id}/"
_NOISE = re.compile(r"\b(?:the|remastered|remaster|definitive edition|complete edition|game of the year edition|goty edition|"
                    r"enhanced edition|deluxe edition|special edition|director'?s cut|hd|edition)\b")


def _norm(name: str) -> str:
    """Без регистра, пунктуации и суффиксов-изданий: «Hades II: Definitive Edition» → «hades ii»."""
    t = unicodedata.normalize("NFKD", name or "").lower().replace("’", "'").replace("™", "").replace("®", "")
    t = _NOISE.sub(" ", t)
    return " ".join(re.sub(r"[^\w]+", " ", t).split())


def steam_fetch(title: str, timeout: int = TIMEOUT) -> dict | None:
    """JSON storesearch по названию; сеть/коды → исключение (OSError/ValueError)."""
    url = STEAM_SEARCH.format(term=urllib.parse.quote(title))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def steam_lookup(title: str, getter=steam_fetch) -> dict | None:
    """Название → {steam_appid, store_title, store_url, cover_url, cover_fallback_url, platform: "steam"} | None.

    Первый результат с совпавшим нормализованным именем, иначе первый, в имени которого запрос — подстрока по границам слов.
    Сеть/битый ответ → None (поиск «мягкий»; запасная обложка — onerror на странице)."""
    q = (title or "").strip()
    nq = _norm(q)
    if not nq:
        return None
    try:
        data = getter(q)
    except (OSError, ValueError):
        return None
    items = [x for x in ((data or {}).get("items") or []) if isinstance(x, dict) and x.get("id") and x.get("name")] \
        if isinstance(data, dict) else []
    pick = next((x for x in items if _norm(str(x["name"])) == nq), None) \
        or next((x for x in items if f" {nq} " in f" {_norm(str(x['name']))} "), None)
    if not pick:
        return None
    aid = str(pick["id"])
    if not aid.isdigit():
        return None
    return {"steam_appid": aid, "store_title": str(pick["name"]).strip(), "store_url": STEAM_APP.format(id=aid),
            "cover_url": STEAM_COVER.format(id=aid), "cover_fallback_url": STEAM_COVER_FALLBACK.format(id=aid),
            "platform": "steam"}


def _eshop_plat(code) -> str | None:
    """Код платформы со страницы Nintendo (свой словарь, напр. switch_2) → код кодлиста game_platform: switch2 | switch."""
    c = re.sub(r"[^a-z0-9]", "", str(code or "").lower())
    if not c:
        return None
    return "switch2" if "2" in c else "switch"


_STEAM_URL = re.compile(r"store\.steampowered\.com/app/(\d{1,10})(?:/|$|\?)")
_STEAM_PLATS = {"steam", "steamdeck", "pc", "xbox"}
_ESHOP_PLATS = {"switch", "switch2"}


def lookup_any(item: dict, getter=fetch, steam_getter=steam_fetch) -> dict | None:
    """{title, platform?, eshop_url?} → единый вид результата или None. Сетевая ошибка eShop — исключение.

    steam/steam_deck/pc/xbox → Steam; switch/switch2 → eShop; платформы нет/неизвестна → eShop, затем Steam.
    Адрес store.steampowered.com/app/<id> в eshop_url → appid из адреса без поиска. platform в ответе — как у входа."""
    item = item if isinstance(item, dict) else {}
    title = str(item.get("title") or "").strip()
    url = str(item.get("eshop_url") or "").strip()
    plat_raw = str(item.get("platform") or "").strip()
    plat = plat_raw.lower().replace("-", "").replace("_", "")
    m = _STEAM_URL.search(url)
    if m:  # владелец вставил адрес страницы Steam — appid берём из него, поиск не нужен
        aid = m.group(1)
        return {"title": title, "platform": plat_raw or "steam", "store": "steam", "nsuid_us": None, "steam_appid": aid,
                "store_title": title or None, "eshop_url": None, "store_url": STEAM_APP.format(id=aid),
                "cover_url": STEAM_COVER.format(id=aid), "cover_fallback_url": STEAM_COVER_FALLBACK.format(id=aid)}
    if plat in _STEAM_PLATS:
        s = steam_lookup(title, steam_getter) if title else None
    else:
        s = None
        e = lookup(url or title, getter, platform="switch_2" if plat == "switch2" else None)
        if e:
            return {"title": title, "platform": plat_raw or _eshop_plat(e.get("platform")), "store": "eshop", "nsuid_us": e["nsuid_us"],
                    "steam_appid": None, "store_title": e.get("store_title"), "eshop_url": e.get("eshop_url"),
                    "store_url": e.get("eshop_url"), "cover_url": e.get("cover_url"), "cover_fallback_url": None}
        if plat not in _ESHOP_PLATS and title:
            s = steam_lookup(title, steam_getter)
    if not s:
        return None
    return {"title": title, "platform": plat_raw or "steam", "store": "steam", "nsuid_us": None, "steam_appid": s["steam_appid"],
            "store_title": s["store_title"], "eshop_url": None, "store_url": s["store_url"],
            "cover_url": s["cover_url"], "cover_fallback_url": s["cover_fallback_url"]}
