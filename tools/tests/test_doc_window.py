#!/usr/bin/env python3
"""Окно документа (ui-kit .ui-docwin) на travel.html — прогон настоящим браузером.

Решения владельца 2026-10-05:
  • стадия поездки открывается окном ПО ЦЕНТРУ (как отчёты здоровья и
    подборки игр), а не боковой панелью; ширина 1280px — экспортному HTML
    стадии хватает места, чтобы nav-layer поставил оглавление столбцом слева;
  • кнопки темы в nav-layer нет — тема берётся из кабинета;
  • статус поездки виден и в рельсе («Идёт · день X из Y» / «До старта · N дн»),
    и в нижней панели («Сегодня X/Y»);
  • Escape по слоям: открытое меню глав (или шторка оглавления md-читателя)
    закрывается первым, следующее нажатие закрывает окно — в том числе когда
    фокус внутри iframe стадии; в поле ввода Escape окно не закрывает.

Поездки и «сегодня» (2026-10-03) — синтетические, из test_travel_status;
HTML стадии — минимальный лист с настоящим слоем `html_lib.nav_layer()`.
Запуск:
    python3 tools/tests/test_doc_window.py
Требует playwright + chromium; без них — честный пропуск.
"""
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO / "skills" / "travel-planning" / "scripts"))
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
    print("doc_window: пропуск — нет playwright")
    sys.exit(0)

from test_travel_status import FAKE_NOW, TRIPS, make_root, serve  # noqa: E402
from export import html_lib  # noqa: E402


def stage_html(trip_id, dates, prep=False):
    """Лист A4 с плашками разделов и днями — ровно то, из чего nav-layer строит меню.
    `prep` — ещё раздел «Подготовка заранее» с пунктами (кнопка «Заранее»)."""
    notes = ("<div class=\"section-plate\">Подготовка заранее</div>"
             + "".join(f"<div class=\"note-item\">[ ] Пункт {i}</div>" for i in range(1, 5))) if prep else ""
    days = "\n".join(
        f'<div class="day" data-date="{d}"><span class="day-date">День {i} · {d[8:]}.{d[5:7]}</span>'
        f'<p>{"Текст дня. " * 60}</p></div>' for i, d in enumerate(dates, 1))
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>body{margin:0;background:#eee}.page{width:794px;margin:0 auto;background:#fff;padding:40px}</style>"
        f"</head><body data-tnav-key=\"{trip_id}\"><div class=\"page\"><div class=\"guide\">"
        "<div class=\"cover-kicker\">Финальный план</div><div class=\"cover-title\">Тест</div>"
        "<div class=\"section-plate\">Маршрут по дням</div>"
        f"{days}{notes}<div class=\"section-plate\">Контакты</div><p>{'Текст. ' * 200}</p>"
        f"</div></div>{html_lib.nav_layer()}</body></html>")


def open_stage(pg, trip, idx=5):
    pg.evaluate("([d, i]) => { const a = document.querySelector("
                "`.vw-link[data-dir=\"${d}\"][data-idx=\"${i}\"]`); if (a) a.click(); }", [trip, idx])
    pg.wait_for_selector("#viewer:not([hidden])", timeout=10000)


def frame_of(pg):
    fr = pg.frame_locator("#vw-frame")
    fr.locator("#tnav-root").wait_for(state="attached", timeout=10000)
    return pg.query_selector("#vw-frame").content_frame()


def viewer_open(pg):
    return pg.evaluate("() => !document.getElementById('viewer').hidden")


def viewer_closed(pg):
    # закрытие анимировано (ui-kit 1.38.0, uiHide: 170 мс до hidden) — ждём итог,
    # а не фиксированную паузу короче анимации
    try:
        pg.wait_for_function("() => document.getElementById('viewer').hidden", timeout=2000)
    except Exception:
        return False
    return True


def main():
    tmp = Path(tempfile.mkdtemp())
    try:
        make_root(tmp, TRIPS)
        trips = tmp / "travel-planner" / "trips"
        for tid, dates in (("вьетнам_2026-10", [f"2026-10-{i:02d}" for i in range(1, 11)]),
                           ("китай_2026-10", [f"2026-10-{14 + i:02d}" for i in range(1, 11)])):
            (trips / tid / f"5_{tid}_финальный_план_v1.html").write_text(stage_html(tid, dates, prep=tid.startswith("китай")), encoding="utf-8")
        srv, base = serve(tmp)
        with sync_playwright() as pw:
            try:
                br = pw.chromium.launch()
            except Exception as e:
                print(f"doc_window: пропуск — chromium не запускается ({str(e)[:60]})")
                return 0
            ctx = br.new_context(viewport={"width": 1440, "height": 900})
            ctx.add_init_script(FAKE_NOW)
            pg = ctx.new_page()
            pg.goto(base + "/tools/travel.html")
            pg.wait_for_selector(".trip-card", timeout=15000)

            # ── широкий экран: окно по центру, оглавление в iframe — слева ──
            open_stage(pg, "вьетнам_2026-10")
            f = frame_of(pg)
            pg.wait_for_timeout(300)
            box = pg.evaluate("() => { const r = document.querySelector('#viewer .ui-docwin-box')"
                              ".getBoundingClientRect(); return [r.left, r.width, innerWidth - r.right]; }")
            check(f"окно по центру, 1280px ({box})",
                  abs(box[1] - 1280) < 2 and abs(box[0] - box[2]) < 2)
            check("iframe стадии: оглавление столбцом слева (рельс)",
                  f.evaluate("() => document.getElementById('tnav-root').classList.contains('tnav-desk')"))
            check("рельс: «Идёт · день 3 из 10»",
                  f.evaluate("() => (document.querySelector('.tnav-rail-st') || {}).textContent") == "Идёт · день 3 из 10")
            check("кнопки темы нет — ни в рельсе, ни в шторке",
                  f.evaluate("() => !document.querySelector('[title=\"Светлая / тёмная тема\"]')"
                             " && !/тема/.test(document.querySelector('.tnav-rail').textContent)"))
            geo = f.evaluate("() => { const r = document.querySelector('.tnav-rail').getBoundingClientRect();"
                             " const b = document.querySelector('.tnav-rail-body'); const t = document.querySelector('.tnav-top');"
                             " return {fits: r.bottom <= innerHeight + 0.5, last: b.lastElementChild === t,"
                             " label: t && t.textContent}; }")
            check(f"рельс помещается в окно целиком ({geo})", geo["fits"])
            check("«↑ В начало» — сразу под списком глав, как в читателе кабинета",
                  geo["last"] and geo["label"] == "↑ В начало")
            check("закрытая шторка невидима (её тень не ложится полосой по низу окна)",
                  f.evaluate("() => getComputedStyle(document.querySelector('.tnav-sheet')).visibility") == "hidden")
            # переход к дальнему дню: подсветка сразу на цели, без пробега по главам
            f.evaluate("() => { window.__act = []; new MutationObserver(ms => ms.forEach(m => {"
                       " if (m.target.classList.contains('is-active')) window.__act.push(m.target.dataset.tnavId); }))"
                       ".observe(document.querySelector('.tnav-rail'), {subtree: true, attributes: true, attributeFilter: ['class']}); }")
            f.evaluate("() => [...document.querySelectorAll('.tnav-rl.it')].pop().click()")
            pg.wait_for_timeout(900)
            seen = f.evaluate("() => [...new Set(window.__act)]")
            tgt = f.evaluate("() => [...document.querySelectorAll('.tnav-rl.it')].pop().dataset.tnavId")
            check(f"переход по рельсу: подсвечена только цель ({seen} → {tgt})", seen == [tgt])
            check("дальний переход — сразу на месте",
                  f.evaluate(f"() => Math.abs(document.getElementById('{tgt}').getBoundingClientRect().top - 16) < 3"
                             " || innerHeight + scrollY >= document.documentElement.scrollHeight - 2"))
            # фокус внутри iframe → Escape закрывает окно
            f.click(".day")
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(150)
            check("Escape с фокусом в iframe закрывает окно", viewer_closed(pg))

            # будущая поездка: статус «До старта»
            open_stage(pg, "китай_2026-10")
            f = frame_of(pg)
            pg.wait_for_timeout(300)
            check("рельс будущей поездки: «До старта · 12 дн»",
                  f.evaluate("() => (document.querySelector('.tnav-rail-st') || {}).textContent") == "До старта · 12 дн")
            # «Заранее» на компьютере — боковая панель на месте рельса, а не
            # телефонная шторка снизу поверх рельса (2026-10-06); темы в ней нет
            f.click(".tnav-rail .tnav-cta")
            pg.wait_for_timeout(450)
            sh = f.evaluate("() => { const r = document.querySelector('.tnav-sheet').getBoundingClientRect();"
                            " return {l: r.left, t: r.top, h: r.height, w: r.width, H: innerHeight, W: innerWidth,"
                            " txt: document.querySelector('.tnav-sheet').textContent}; }")
            check(f"«Заранее» на компьютере — панель слева во всю высоту, не шторка снизу ({sh['l']},{sh['t']},{sh['w']}×{sh['h']})",
                  abs(sh["l"]) < 1 and abs(sh["t"]) < 1 and abs(sh["h"] - sh["H"]) < 1 and sh["w"] <= 421 and sh["w"] < sh["W"] / 2)
            check("в панели «Заранее» нет кнопки темы",
                  not f.evaluate("() => !!document.querySelector('.tnav-sheet [title*=\"тема\"]')"))
            f.click(".tnav-sheet .tnav-head .tnav-ico:last-child")
            pg.wait_for_timeout(350)
            check("панель «Заранее» закрывается", not f.evaluate("() => document.querySelector('.tnav-sheet').classList.contains('is-open')"))
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(150)
            check("Escape с фокусом на странице закрывает окно", viewer_closed(pg))

            # ── узкий экран: нижняя панель, меню глав — первый слой Escape ──
            pg.set_viewport_size({"width": 1000, "height": 800})
            open_stage(pg, "вьетнам_2026-10")
            f = frame_of(pg)
            pg.wait_for_timeout(300)
            check("узкое окно: оглавление — нижней панелью",
                  f.evaluate("() => document.getElementById('tnav-root').classList.contains('tnav-mobile')"))
            ctx_btn = f.evaluate("() => (document.querySelector('.tnav-b--ctx') || {}).textContent || ''")
            check(f"панель: «Сегодня» с номером дня 3/10 ({ctx_btn!r})", "Сегодня" in ctx_btn and "3/10" in ctx_btn)
            bb = f.evaluate("() => { const r = document.querySelector('.tnav-bar').getBoundingClientRect();"
                            " return [r.left, r.right, r.bottom, innerWidth, innerHeight]; }")
            check(f"нижняя панель прилеплена к краю во всю ширину ({bb})",
                  abs(bb[0]) < 1 and abs(bb[1] - bb[3]) < 1 and abs(bb[2] - bb[4]) < 1)
            f.click(".tnav-b--main")
            pg.wait_for_timeout(150)
            check("меню глав открыто", f.evaluate("() => document.querySelector('.tnav-sheet').classList.contains('is-open')"))
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(150)
            check("1-й Escape: меню глав закрыто, окно стадии открыто",
                  not f.evaluate("() => document.querySelector('.tnav-sheet').classList.contains('is-open')")
                  and viewer_open(pg))
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(150)
            check("2-й Escape: окно закрыто", viewer_closed(pg))

            # поле ввода внутри стадии (комментарии edit-слоя) — Escape окно не закрывает
            open_stage(pg, "вьетнам_2026-10")
            f = frame_of(pg)
            f.evaluate("() => { const i = document.createElement('textarea'); i.id = 'tx';"
                       " document.querySelector('.guide').prepend(i); }")
            f.focus("#tx")
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(150)
            check("Escape в поле ввода стадии окно не закрывает", viewer_open(pg))
            pg.evaluate("() => document.getElementById('vw-close').click()")

            # ── md-читатель: шторка оглавления — первый слой Escape ──
            pg.set_viewport_size({"width": 700, "height": 800})
            open_stage(pg, "вьетнам_2026-10")
            pg.evaluate("() => document.getElementById('seg-md').click()")
            pg.wait_for_selector("#vw-md .rd-bar", timeout=10000)
            pg.click("#vw-md [data-rd-sheet]")
            pg.wait_for_timeout(150)
            check("md: шторка оглавления открыта", pg.locator("#vw-md .rd-sheet:not([hidden])").count() == 1)
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(150)
            check("md: 1-й Escape сворачивает шторку, окно открыто",
                  pg.locator("#vw-md .rd-sheet:not([hidden])").count() == 0 and viewer_open(pg))
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(150)
            check("md: 2-й Escape закрывает окно", viewer_closed(pg))
            check("телефон: окно во весь экран",
                  pg.evaluate("() => { document.getElementById('viewer').hidden = false;"
                              " const r = document.querySelector('#viewer .ui-docwin-box').getBoundingClientRect();"
                              " document.getElementById('viewer').hidden = true;"
                              " return r.left === 0 && Math.round(r.width) === innerWidth; }"))
            br.close()
        srv.shutdown()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\ndoc_window: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
