#!/usr/bin/env python3
"""gaming_migrate.py — приводит оверлей Gaming/user-state.json к трём осям (статус · прохождение · оценка).

Правило (то же, что normUserRec в tools/games.html):
  state играю / пройдена / брошена → state куплена + progress с тем же словом;
  rating «брошено» → rating null и, если progress пуст, progress «брошена»;
  демо — флаг demo: true («играл в демо, игру не купил») при некупленном state:
        state демо → demo true + state не-интересно, если оценка «не понравилось», иначе на-карандаш;
        запись state куплена, название которой оканчивается на «Demo» / «: Demo» / «Trial Version»
        (регистр не важен) → то же; оценка «брошено» или «не понравилось» → «не понравилось»,
        progress при этом «брошена» не ставится;
        demo true у state куплена снимается.

Запуск:
  python3 tools/gaming_migrate.py --file <путь к user-state.json>          # сухой прогон по файлу, ничего не пишет
  HUB_URL=https://… HUB_AUTH='…' python3 tools/gaming_migrate.py           # сухой прогон по живому оверлею
  … --write                                                                 # POST /api/gm/save с base_hash (409 → код 1)

Печатает сводку по правилам и поимённый список изменений. Зависимости: stdlib.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

USER_PATH = "Gaming/user-state.json"
LEGACY_STATES = ("играю", "пройдена", "брошена")
DEMO_RE = re.compile(r"(?:\s+demo|:\s*demo|\s+trial\s+version)\s*$", re.I)


def is_demo_title(title: str) -> bool:
    return bool(DEMO_RE.search(str(title or "").strip()))


KEYS = ("state", "rating", "progress", "demo")


def demo_state(it: dict) -> str:
    """Некупленный state записи, ставшей демо-карточкой."""
    return "не-интересно" if it.get("rating") == "не понравилось" else "на-карандаш"


def migrate_item(it: dict) -> list[str]:
    """Правит запись на месте; возвращает коды применённых правил (пусто — запись не менялась)."""
    rules = []
    if it.get("state") == "куплена" and is_demo_title(it.get("title")):
        if it.get("rating") == "брошено":
            it["rating"] = "не понравилось"
            rules.append("демо: оценка → не понравилось")
        it["state"] = demo_state(it)
        it["demo"] = True
        rules.append("демо → флаг demo")
        if it.get("rating") == "не понравилось":
            return rules   # прохождение «брошена» у демо не ставим
    elif it.get("state") == "демо":
        it["state"] = demo_state(it)
        it["demo"] = True
        rules.append("state демо → флаг demo")
    if it.get("demo") is True and it.get("state") == "куплена":
        del it["demo"]
        rules.append("demo снят: игра куплена")
    if it.get("state") in LEGACY_STATES:
        if not it.get("progress"):
            it["progress"] = it["state"]
        it["state"] = "куплена"
        rules.append("state → куплена + progress")
    if it.get("rating") == "брошено":
        it["rating"] = None
        rules.append("оценка «брошено» снята")
        if not it.get("progress"):
            it["progress"] = "брошена"
            rules.append("progress → брошена")
    if it.get("progress") == "не-начата":
        it["progress"] = None
    return rules


def _key(title) -> str:
    """Ключ названия как у сервера (gaming_key): без регистра, апострофов и пунктуации."""
    import unicodedata
    t = unicodedata.normalize("NFKC", str(title or "")).casefold().replace("'", "").replace("’", "")
    return " ".join(re.sub(r"[^\w]+", " ", t).split())


def fold_demos(doc: dict, today: str) -> list[tuple[str, list[str], dict, dict]]:
    """Демо, у которой в оверлее есть запись основной игры, — одна карточка вместо двух: основная куплена → демо
    скрывается; иначе основная получает статус «демо» и оценку демо (если своей нет), демо скрывается."""
    out, items = [], [i for i in doc.get("items") or [] if isinstance(i, dict)]
    by_key = {_key(i.get("title")): i for i in items}
    for d in items:
        if d.get("deleted") or not is_demo_title(d.get("title")):
            continue
        b = by_key.get(_key(DEMO_RE.sub("", str(d["title"]).strip()).rstrip(" :")))
        if not b or b is d or b.get("deleted"):
            continue
        bb = {k: b.get(k) for k in KEYS}
        if b.get("state") in ("куплена",) + tuple(LEGACY_STATES):
            rule = "демо скрыта: основная игра куплена"
        else:
            b["demo"] = True
            if b.get("state") == "демо":
                b["state"] = "на-карандаш"
            if not b.get("rating") and d.get("rating"):
                b["rating"] = "не понравилось" if d["rating"] in ("брошено", "не понравилось") else d["rating"]
            for f in ("hours", "cover_url", "note"):
                if b.get(f) in (None, "") and d.get(f) not in (None, ""):
                    b[f] = d[f]
            b["updated"] = today
            rule = "демо и основная игра — одна карточка с флагом demo"
            out.append((b.get("title"), [rule], bb, {k: b.get(k) for k in KEYS}))
        d["deleted"], d["updated"] = True, today
        out.append((d.get("title"), [rule], {"deleted": False}, {"deleted": True}))
    return out


def add_records(doc: dict, demo, hide, today: str) -> list[tuple[str, list[str], dict, dict]]:
    """Игры, которых нет в оверлее (только в файлах советника): --demo → карточка с флагом demo, --hide → скрыть карточку."""
    out, items = [], doc.setdefault("items", [])
    by_key = {_key(i.get("title")): i for i in items if isinstance(i, dict)}
    for title, state, deleted, rule in [(t, "на-карандаш", False, "демо (по слову владельца)") for t in demo or []] + \
                                       [(t, "куплена", True, "карточка скрыта (по слову владельца)") for t in hide or []]:
        it = by_key.get(_key(title))
        before = {k: it.get(k) for k in ("state", "deleted", "demo")} if it else {}
        if not it:
            it = {"title": title, "state": state, "deleted": False, "added": today}
            items.append(it)
            by_key[_key(title)] = it
        if deleted:
            it["deleted"] = True
        else:
            if it.get("state") in ("куплена", "демо") + tuple(LEGACY_STATES) or not it.get("state"):
                it["state"] = state
            it["deleted"], it["demo"] = False, True
        it["updated"] = today
        out.append((title, [rule], before, {k: it.get(k) for k in ("state", "deleted", "demo")}))
    return out


def migrate_doc(doc: dict, today: str | None = None, demo=None, hide=None) -> list[tuple[str, list[str], dict, dict]]:
    """Правит doc на месте; [(название, правила, было, стало)] только по изменённым записям."""
    import datetime
    today = today or datetime.date.today().isoformat()
    out = fold_demos(doc, today) + add_records(doc, demo, hide, today)
    for it in doc.get("items") or []:
        if not isinstance(it, dict) or (it.get("deleted") and is_demo_title(it.get("title"))):
            continue                                   # скрытая демо (свёрнута в основную игру) — не трогаем
        before = {k: it.get(k) for k in KEYS}
        rules = migrate_item(it)
        after = {k: it.get(k) for k in KEYS}
        if rules and before != after:
            out.append((it.get("title"), rules, before, after))
    return out


def _req(url: str, auth: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET",
                               headers={"Authorization": auth, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def summary(changes) -> dict:
    cnt: dict[str, int] = {}
    for _t, rules, _b, _a in changes:
        for r in rules:
            cnt[r] = cnt.get(r, 0) + 1
    return cnt


def run(argv=None, opener=_req) -> int:
    ap = argparse.ArgumentParser(description="оверлей игр → три оси (статус · прохождение · оценка)")
    ap.add_argument("--file", help="локальный user-state.json (только сухой прогон)")
    ap.add_argument("--write", action="store_true", help="записать через POST /api/gm/save (нужны HUB_URL и HUB_AUTH)")
    ap.add_argument("--demo", action="append", metavar="НАЗВАНИЕ", help="игра только из файлов советника → карточка с флагом demo (можно несколько)")
    ap.add_argument("--hide", action="append", metavar="НАЗВАНИЕ", help="скрыть карточку игры (deleted) — напр. демо при купленной основной игре")
    a = ap.parse_args(argv)
    base, auth = os.environ.get("HUB_URL", "").rstrip("/"), os.environ.get("HUB_AUTH", "")
    h = None
    if a.file:
        if a.write:
            print("✗ --write несовместим с --file: запись идёт только через сайт", file=sys.stderr)
            return 2
        with open(os.path.expanduser(a.file), encoding="utf-8") as f:
            doc = json.load(f)
    else:
        if not base or not auth:
            print("✗ нужны HUB_URL и HUB_AUTH (или --file для сухого прогона)", file=sys.stderr)
            return 2
        st, j = opener(f"{base}/api/gm/file?path={USER_PATH}", auth)
        if st != 200:
            print(f"✗ чтение оверлея: HTTP {st}", file=sys.stderr)
            return 1
        doc, h = json.loads(j["content"]), j.get("hash")
    changes = migrate_doc(doc, demo=a.demo, hide=a.hide)
    print(f"Записей: {len(doc.get('items') or [])}, изменится: {len(changes)}")
    for r, n in sorted(summary(changes).items(), key=lambda kv: -kv[1]):
        print(f"  {n:4d}  {r}")
    for title, rules, b, af in changes:
        fmt = lambda d: "/".join(str(d.get(k)) for k in KEYS) if "state" in d and "rating" in d \
            else ", ".join(f"{k}={v}" for k, v in d.items()) or "нет записи"      # noqa: E731
        print(f"  · {title}: {fmt(b)} → {fmt(af)}  [{'; '.join(rules)}]")
    if not a.write:
        print("Сухой прогон: ничего не записано (--write — записать).")
        return 0
    if not changes:
        print("Менять нечего.")
        return 0
    st, j = opener(f"{base}/api/gm/save", auth, {"path": USER_PATH, "content": json.dumps(doc, ensure_ascii=False, indent=2) + "\n", "base_hash": h})
    if st == 409:
        print("✗ 409: оверлей изменили параллельно — перезапусти скрипт", file=sys.stderr)
        return 1
    if st != 200:
        print(f"✗ запись: HTTP {st} {j.get('detail') or j.get('error') or ''}", file=sys.stderr)
        return 1
    print(f"✓ записано (hash {j.get('hash')})")
    return 0


if __name__ == "__main__":
    sys.exit(run())
