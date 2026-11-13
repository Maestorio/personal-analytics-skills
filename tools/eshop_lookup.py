#!/usr/bin/env python3
"""eshop_lookup.py — nsuid, название и платформа игры US eShop без LLM (API-1, PR-9 брифа).

Страница https://www.nintendo.com/us/store/products/<slug>/ несёт в <script id="__NEXT_DATA__">
объект Product с urlKey == slug и полем nsuid. На странице десятки чужих nsuid (похожие игры),
поэтому берётся ТОЛЬКО объект с совпадающим urlKey. Страница открылась и объект нашёлся —
это и есть проверка, что игра есть в US eShop. Издание для Switch 2 — отдельный товар со своим
nsuid и slug на «-switch-2».

    python3 tools/eshop_lookup.py lookup <ссылка или slug>
    python3 tools/eshop_lookup.py fill --watchlist <watchlist.yaml> --out <новый файл>

fill: для «хочу» и «на-карандаш» без nsuid_us пробует slug из названия (+ «-switch» /
«-switch-2» по платформе; сначала по ссылке eshop_url, если она уже есть), печатает, что нашлось,
и пишет ИСПРАВЛЕННУЮ КОПИЮ в --out: строки store_title / nsuid_us / eshop_url сразу после
title, остальной текст и комментарии файла не трогаются. Сам watchlist.yaml не пишет —
его владелец game-advisor; копия ставится на место после показанного diff.
Только stdlib.

Поиск для сайта (с обложкой) — hosting/notify/eshop_lookup.py (POST /internal/nsuid-lookup); этот CLI — fill по watchlist.yaml.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request

BASE = "https://www.nintendo.com/us/store/products/"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Safari/605.1.15"
NEXT_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
WATCH_STATUSES = ("хочу", "на-карандаш")


def slug_of(url_or_slug: str) -> str:
    s = url_or_slug.strip().rstrip("/")
    return s.rsplit("/products/", 1)[-1].split("?")[0].strip("/") if "/" in s else s


def extract(html: str, slug: str) -> dict | None:
    """__NEXT_DATA__ → {nsuid, store_title, platform, url} объекта с urlKey == slug."""
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
                return {"nsuid": str(o["nsuid"]), "store_title": str(o.get("name") or "").strip(),
                        "platform": plat.get("code") if isinstance(plat, dict) else None,
                        "url": f"{BASE}{slug}/"}
            stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)
    return None


def fetch(slug: str, timeout: int = 30) -> str | None:
    req = urllib.request.Request(f"{BASE}{slug}/", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def lookup(url_or_slug: str, getter=fetch) -> dict | None:
    slug = slug_of(url_or_slug)
    html = getter(slug)
    return extract(html, slug) if html else None


def slugify(title: str) -> str:
    t = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    t = t.lower().replace("&", " and ").replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def candidates(title: str, platform: str | None) -> list[str]:
    base = slugify(title)
    if not base:
        return []
    order = ["switch-2", "switch"] if platform == "switch_2" else ["switch", "switch-2"]
    return [f"{base}-{suf}" for suf in order]


# ───────────────────────────── fill ─────────────────────────────

ITEM_RE = re.compile(r"^(\s*)- title:\s*(.+?)\s*$")
FIELD_RE = re.compile(r"^(\s+)([a-z_]+):\s*(.*?)\s*$")


def _unq(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def items_with_lines(text: str) -> list[dict]:
    """Позиции items в тексте: title, status, platform, eshop_url, nsuid_us, номер строки title."""
    lines = text.split("\n")
    out, cur = [], None
    for i, line in enumerate(lines):
        m = ITEM_RE.match(line)
        if m:
            cur = {"line": i, "indent": len(m.group(1)) + 2, "title": _unq(m.group(2))}
            out.append(cur)
            continue
        f = FIELD_RE.match(line)
        if cur and f and len(f.group(1)) == cur["indent"]:
            cur[f.group(2)] = _unq(f.group(3))
        elif cur and line.strip() and len(line) - len(line.lstrip(" ")) < cur["indent"]:
            cur = None                           # вышли из записи (комментарий группы, конец items)
    return out


def _q(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def fill(text: str, finder, pause: float = 1.0, log=print) -> tuple[str, list[dict]]:
    """→ (новый текст, отчёт по играм). finder(item) → dict из extract или None."""
    lines = text.split("\n")
    report, inserts = [], []
    for it in items_with_lines(text):
        if it.get("status") not in WATCH_STATUSES or it.get("nsuid_us"):
            continue
        hit = finder(it)
        report.append({"title": it["title"], "found": hit})
        log(f"{'✓' if hit else '✗'} {it['title']}" + (f" → {hit['store_title']} · {hit['nsuid']} · {hit['platform']}"
                                                     if hit else " — не найдено, нужна ссылка на страницу US eShop"))
        if hit:
            pad = " " * it["indent"]
            add = [f"{pad}store_title: {_q(hit['store_title'])}", f'{pad}nsuid_us: "{hit["nsuid"]}"']
            if not it.get("eshop_url"):
                add.append(f"{pad}eshop_url: {hit['url']}")
            inserts.append((it["line"] + 1, add))
        time.sleep(pause)
    for at, add in sorted(inserts, reverse=True):
        lines[at:at] = add
    return "\n".join(lines), report


def finder_web(it: dict) -> dict | None:
    if it.get("eshop_url"):
        return lookup(it["eshop_url"])
    for slug in candidates(it["title"], it.get("platform")):
        hit = lookup(slug)
        if hit:
            return hit
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="nsuid игры US eShop по ссылке на страницу.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a1 = sub.add_parser("lookup")
    a1.add_argument("url")
    a2 = sub.add_parser("fill")
    a2.add_argument("--watchlist", required=True)
    a2.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "lookup":
        hit = lookup(a.url)
        print(json.dumps(hit, ensure_ascii=False, indent=1) if hit else "не найдено")
        return 0 if hit else 1
    text = open(a.watchlist, encoding="utf-8").read()
    new, rep = fill(text, finder_web)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(new)
    print(f"найдено {sum(1 for r in rep if r['found'])} из {len(rep)}; копия: {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
