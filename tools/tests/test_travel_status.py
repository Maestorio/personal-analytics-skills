#!/usr/bin/env python3
"""Путешествия: статус «когда поездка» на travel.html и hub.html — прогон
настоящим браузером на синтетических поездках с подменённой «сегодня».

Решения владельца 2026-10-03 (план docs/travel-planning/plans/
trip-status-and-reader-plan.md):
  • поездка — только с точными датами start/end в trip.yaml: «через 12 дн»,
    «идёт · день 3 из 10», «прошла»;
  • status: ready + месяц — поездка с точностью до месяца: «в следующем месяце»;
  • без дат и не ready — возможная поездка, только год — идея: без отсчёта
    времени и без «в этом/следующем году»;
  • прошедшая возможная — в архив с «срок прошёл», не «состоялась»;
  • «Ближайшая» (travel) и «Моя ближайшая» (hub) — только поездки; если их
    нет — оговорка «точных дат нет · идея»;
  • md-режим стадии — общий читатель; «Сегодня» — только у идущей поездки с
    точными датами, прыжок к сегодняшнему дню.

Запуск:
    python3 tools/tests/test_travel_status.py
Требует playwright + chromium; без них — честный пропуск.
"""
import json
import shutil
import sys
import tempfile
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, unquote

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pages_stand import serve as _stand_serve  # noqa: E402
passed = failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}")


try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("travel_status: пропуск — нет playwright")
    sys.exit(0)

# «Сегодня» для всех страниц прогона: 3 октября 2026, полдень (локально).
FAKE_NOW = """(() => {
  const RD = Date, fixed = new RD(2026, 9, 3, 12, 0, 0).getTime();
  function D(...a){ return a.length ? new RD(...a) : new RD(fixed); }
  D.now = () => fixed; D.UTC = RD.UTC; D.parse = RD.parse; D.prototype = RD.prototype;
  window.Date = D;
})();"""


def yaml(title, status, season, start=None, end=None, travelers="[алексей]"):
    out = [f"schema: trip-meta@1", f"title: {title}", f"status: {status}",
           f"travelers: {travelers}", f'season: "{season}"']
    if start:
        out += [f"start: {start}", f"end: {end}"]
    return "\n".join(out) + "\n"


def plan_md(trip_id, days):
    head = f"---\ntrip_id: {trip_id}\nstage: 5\n---\n\n# Финальный план\n\n## Маршрут по дням\n\n"
    return head + "\n".join(f"### День {n} ({d} Пн). Город {n}\n\n" + ("Текст дня. " * 40) + "\n"
                            for n, d in days)


TRIPS = {
    # идущая поездка с точными датами — «идёт · день 3 из 10», «Сегодня»
    "вьетнам_2026-10": (yaml("Вьетнам", "ready", "2026-10", "2026-10-01", "2026-10-10"),
                        plan_md("вьетнам_2026-10", [(i, f"{i:02d}.10") for i in range(1, 11)])),
    # будущая поездка с точными датами
    "китай_2026-10": (yaml("Китай", "ready", "2026-10", "2026-10-15", "2026-10-24"),
                      plan_md("китай_2026-10", [(i, f"{14 + i:02d}.10") for i in range(1, 11)])),
    # ready + месяц без дат — поездка с точностью до месяца
    "япония_2026-11": (yaml("Япония", "ready", "2026-11"), None),
    # возможная поездка: месяц, статус planning
    "перу_2027-02": (yaml("Перу", "planning", "2027-02"), None),
    # идея: только год
    "исландия_2027": (yaml("Исландия", "planning", "2027"), None),
    # возможная поездка, срок прошёл — «срок прошёл», не «состоялась»
    "чили_2026-08": (yaml("Чили", "planning", "2026-08"), None),
    # явно состоявшаяся
    "корея_2024-03": (yaml("Корея", "done", "2024-03"), None),
    # поездка родителей — идёт и началась РАНЬШЕ Вьетнама: «Ближайшей» не становится
    "родители_2026-09": (yaml("Родители в Сочи", "ready", "2026-09", "2026-09-30", "2026-10-08",
                              travelers="[родители]"), None),
}
# Вторая коллекция для хаба: только возможные/идеи — «точных дат нет · идея».
TRIPS_IDEAS = {k: v for k, v in TRIPS.items() if k in ("перу_2027-02", "исландия_2027", "корея_2024-03")}


def make_root(d: Path, trips):
    for name, (y, md) in trips.items():
        t = d / "travel-planner" / "trips" / name
        t.mkdir(parents=True)
        (t / "trip.yaml").write_text(y, encoding="utf-8")
        (t / "0_scope.md").write_text(f"---\ntrip_id: {name}\nstage: 0\n---\n# Рамки\n", encoding="utf-8")
        if md:
            (t / f"5_{name}_финальный_план_v1.md").write_text(md, encoding="utf-8")
    (d / "travel-planner" / "profiles").mkdir(parents=True, exist_ok=True)


def make_handler(root: Path):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body=b"", ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_GET(self):
            p = unquote(urlparse(self.path).path)
            if p.startswith("/api/"):
                return self._send(200, json.dumps({"ok": True}).encode())
            f = (REPO / "tools" / p[len("/tools/"):]) if p.startswith("/tools/") else (root / p.lstrip("/"))
            if f.is_dir():
                return self._send(200, json.dumps([{"name": c.name, "is_dir": c.is_dir()}
                                                   for c in sorted(f.iterdir())]).encode())
            if not f.is_file():
                return self._send(404)
            ctype = {".html": "text/html; charset=utf-8", ".json": "application/json",
                     ".css": "text/css", ".js": "application/javascript", ".md": "text/markdown; charset=utf-8",
                     ".yaml": "text/plain; charset=utf-8", ".woff2": "font/woff2"}.get(f.suffix, "application/octet-stream")
            return self._send(200, f.read_bytes(), ctype)
    return H


def serve(root):
    """(сервер, база) стенда поездок с данными root — _pages_stand: новый сервер, очередь 128, keep-alive."""
    return _stand_serve(make_handler(root))


def card_text(pg, title):
    return pg.evaluate("t => { const c = [...document.querySelectorAll('.trip-card')]"
                       ".find(x => (x.querySelector('.trip-title') || {}).textContent === t);"
                       " return c ? c.innerText : null; }", title)


def card_group(pg, title):
    return pg.evaluate("t => { const c = [...document.querySelectorAll('.trip-card')]"
                       ".find(x => (x.querySelector('.trip-title') || {}).textContent === t);"
                       " const s = c && c.closest('.trip-group'); return s ? s.querySelector('h2').textContent : null; }", title)


def main():
    tmp = Path(tempfile.mkdtemp())
    try:
        make_root(tmp / "a", TRIPS)
        make_root(tmp / "b", TRIPS_IDEAS)
        srv_a, base_a = serve(tmp / "a")
        srv_b, base_b = serve(tmp / "b")
        with sync_playwright() as pw:
            try:
                br = pw.chromium.launch()
            except Exception as e:
                print(f"travel_status: пропуск — chromium не запускается ({str(e)[:60]})")
                return 0
            ctx = br.new_context(viewport={"width": 1280, "height": 900})
            ctx.add_init_script(FAKE_NOW)
            pg = ctx.new_page()
            pg.goto(base_a + "/tools/travel.html")
            pg.wait_for_load_state("networkidle")
            try:
                pg.wait_for_selector(".trip-card", timeout=15000)
            except Exception:
                pass
            pg.wait_for_timeout(400)

            # карточки
            t = card_text(pg, "Вьетнам") or ""
            check("идущая поездка: «идёт · день 3 из 10»", "идёт · день 3 из 10" in t)
            t = card_text(pg, "Китай") or ""
            check("будущая поездка с датами: «через 12 дн»", "через 12 дн" in t)
            check("будущая поездка: точные даты в шапке карточки (надзаголовок — капсом через CSS)", "15–24 октября 2026" in t.lower())
            t = card_text(pg, "Япония") or ""
            check("ready + месяц: «в следующем месяце»", "в следующем месяце" in t)
            t = card_text(pg, "Перу") or ""
            check("возможная: «возможная · даты не определены», без отсчёта",
                  "возможная · даты не определены" in t and "через" not in t)
            t = card_text(pg, "Исландия") or ""
            check("идея (только год): «идея», без «в этом/следующем году»",
                  "идея" in t and "году" not in t)
            check("прошедшая возможная — в архиве", card_group(pg, "Чили") == "Архив" or
                  (card_group(pg, "Чили") or "").lower().startswith("арх"))
            t = card_text(pg, "Чили") or ""
            check(f"прошедшая возможная — «срок прошёл», не «состоялась» ({t[:60]!r})",
                  "срок прошёл" in t and "состоялась" not in t)
            t = card_text(pg, "Корея") or ""
            check("явный status: done — «состоялась»", "состоялась" in t)
            check("подсказка у возможной — «точных дат нет»",
                  pg.evaluate("() => { const e = [...document.querySelectorAll('.trip-when--possible')][0];"
                              " return e ? e.title : ''; }").startswith("точных дат нет"))
            # мои / для близких
            check(f"сводка: мои 7 · для близких 1 ({pg.inner_text('#sum-mine')} / {pg.inner_text('#sum-others')})",
                  pg.inner_text("#sum-mine") == "7" and pg.inner_text("#sum-others") == "1")
            check("сводка: всего 8", pg.inner_text("#sum-total") == "8")
            # сводка «Ближайшая» — из моих, поездка родителей (раньше) не берётся
            nxt = pg.inner_text("#sum-next")
            check(f"«Ближайшая» — идущая поездка с датами («{nxt}»)",
                  nxt == "Ближайшая — Вьетнам, идёт · день 3 из 10")

            # окно просмотра md-стадии: статус в шапке + читатель + «Сегодня»
            pg.evaluate("() => { const a = document.querySelector('.vw-link[data-dir=\"вьетнам_2026-10\"][data-idx=\"5\"]'); if (a) a.click(); }")
            try:
                pg.wait_for_selector("#vw-md .rd", timeout=10000)
            except Exception:
                pass
            pg.wait_for_timeout(400)
            check("окно: md-стадия открыта общим читателем", pg.locator("#vw-md .rd").count() == 1)
            check("окно: статус поездки в шапке", pg.inner_text("#vw-when") == "идёт · день 3 из 10")
            act = pg.locator("#vw-md .rd-toc .rd-act")
            check("окно: «Сегодня · 03.10» над оглавлением", act.count() == 1 and "Сегодня · 03.10" in act.inner_text())
            if act.count():
                act.click()
                pg.wait_for_timeout(900)
                off = pg.evaluate("() => { const h = [...document.querySelectorAll('#vw-md .rd-doc h3')]"
                                  ".find(x => x.textContent.startsWith('День 3 ')); const s = document.getElementById('vw-md');"
                                  " return h ? h.getBoundingClientRect().top - s.getBoundingClientRect().top : null; }")
                check(f"«Сегодня» приводит к дню 3 (смещение {off and round(off)})", off is not None and -2 <= off <= 40)
            pg.evaluate("() => document.getElementById('vw-close').click()")
            pg.wait_for_timeout(200)
            # будущая поездка — без «Сегодня»
            pg.evaluate("() => { const a = document.querySelector('.vw-link[data-dir=\"китай_2026-10\"][data-idx=\"5\"]'); if (a) a.click(); }")
            try:
                pg.wait_for_selector("#vw-md .rd", timeout=10000)
            except Exception:
                pass
            pg.wait_for_timeout(300)
            check("будущая поездка: в окне «через 12 дн», кнопки «Сегодня» нет",
                  pg.inner_text("#vw-when") == "через 12 дн" and pg.locator("#vw-md .rd-act").count() == 0)
            pg.close()

            # хаб: «Моя ближайшая»
            pg = ctx.new_page()
            pg.goto(base_a + "/tools/hub.html")
            pg.wait_for_load_state("networkidle")
            pg.wait_for_timeout(600)
            check(f"хаб: «Моя ближайшая» — поездка с датами («{pg.inner_text('#trips-next')}»)",
                  pg.inner_text("#trips-next") == "Вьетнам, идёт · день 3 из 10")
            check(f"хаб: «мои · для близких» у числа поездок («{pg.inner_text('#trips-split')}»)",
                  pg.inner_text("#trips-split") == "мои: 7 · для близких: 1")
            pg.close()
            pg = ctx.new_page()
            pg.goto(base_b + "/tools/hub.html")
            pg.wait_for_load_state("networkidle")
            pg.wait_for_timeout(600)
            nx = pg.inner_text("#trips-next")
            check(f"хаб без поездок с датами: оговорка «точных дат нет · идея» («{nx}»)",
                  nx == "точных дат нет · идея — Перу, февраль 2027")
            pg.close()
            pg = ctx.new_page()
            pg.goto(base_b + "/tools/travel.html")
            pg.wait_for_load_state("networkidle")
            pg.wait_for_timeout(600)
            nx = pg.inner_text("#sum-next")
            check(f"travel без поездок с датами: «Точных дат пока нет · ближайшая идея» («{nx}»)",
                  nx == "Точных дат пока нет · ближайшая идея — Перу, февраль 2027")
            pg.close()
            br.close()
        srv_a.shutdown(); srv_b.shutdown()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\ntravel_status: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
