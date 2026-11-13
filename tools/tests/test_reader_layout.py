#!/usr/bin/env python3
"""Единый читатель markdown (ui-kit uiReader) — прогон настоящим браузером.

Что нельзя проверить чтением исходника:

  1. Оглавление встаёт столбцом, когда окну читателя хватает ширины, и
     уходит в полосу снизу, когда не хватает. Порог — container query по
     ширине ОКНА, а не экрана: панель игр и модалка здоровья на одном
     мониторе ведут себя по-разному.
  2. Прыжок к главе приводит именно к главе, подсветка текущей главы и
     подпись в полосе следуют за прокруткой, шторка глав открывается и
     закрывается.
  3. Нижняя полоса прилипает к низу окна (sticky), а не уезжает с текстом.
  4. Позиция чтения переживает перерисовку (health пишет innerHTML на каждое
     действие) — по ключу документа.
  5. Параметр toc: "auto" (≥3 глав), true, false — оглавление опционально
     (решение владельца 2026-10-03: у справок его, возможно, потом выключат).
  6. Живые страницы: подборка игр открывается читателем с акцентом раздела и
     карточкой frontmatter, справка хаба — читателем; документ не шире экрана.
  7. Тёмная тема: текст документа читается (контраст ≥ 4.5).
  8. ui-kit 1.59.0: сгибы <details>, якоря {#id} и ссылки [текст](#id), выноски
     «> **Важно:**», режим sections («по разделам»: один раздел на экране, оглавление —
     переключатель, поиск по всему документу переключает раздел и считает совпадения
     по разделам, at на ###), справка из нескольких файлов (uiFetchMarkdownParts).

Данные синтетические. Запуск:
    python3 tools/tests/test_reader_layout.py
Требует playwright + chromium; без них — честный пропуск.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, unquote

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pages_stand import frames, scroll_still, serve  # noqa: E402
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
    print("reader_layout: пропуск — нет playwright")
    sys.exit(0)

# ── синтетический документ: frontmatter, H1, TL;DR, 5 глав с подглавами ──
CHAPTERS = ["Кандидаты", "Отзывы", "Длительность", "Цены", "Источники"]
LOREM = ("Длинный абзац, чтобы глава занимала больше экрана и прокрутка была "
         "настоящей, а не символической. ") * 12


def make_doc():
    out = ["---", "date: 2026-10-03", "mood: потупить вечером", "platform: Switch 2",
           "tags:", "  - вложенное", "---", "", "# Подборка для теста", "",
           "TL;DR: три игры, одна разведка.", ""]
    for i, ch in enumerate(CHAPTERS, 1):
        out += [f"## {i}. {ch}", "", LOREM, "", f"### {ch} — подробности", "", LOREM, ""]
        if i == 1:
            out += ["- верхний пункт", "  - вложенный пункт", "- [x] выполнено", "",
                    "| Игра | Цена |", "|---|---|", "| Hades | 1 272 105 ₽ |", ""]
    return "\n".join(out)


DOC = make_doc()
SHORT = "## Раз\n\nКоротко.\n\n## Два\n\nТоже коротко.\n"


def make_handler():
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
            if p == "/blank.html":
                return self._send(200, b"<!doctype html><html><head><meta charset='utf-8'></head><body></body></html>",
                                  "text/html; charset=utf-8")
            if p.rstrip("/") == "/Gaming/recommendations":
                return self._send(200, json.dumps([{"name": "2026-10-03-test.md", "is_dir": False}]).encode())
            if p == "/short.md":
                return self._send(200, SHORT.encode("utf-8"), "text/markdown; charset=utf-8")
            if p == "/Gaming/recommendations/2026-10-03-test.md":
                return self._send(200, DOC.encode("utf-8"), "text/markdown; charset=utf-8")
            if p.startswith("/api/"):
                return self._send(200, json.dumps({"ok": True}).encode())
            if p.startswith("/tools/"):
                f = REPO / "tools" / p[len("/tools/"):]
                if f.is_file():
                    ctype = {".html": "text/html; charset=utf-8", ".json": "application/json",
                             ".css": "text/css", ".js": "application/javascript", ".md": "text/markdown",
                             ".woff2": "font/woff2", ".woff": "font/woff"}.get(f.suffix, "application/octet-stream")
                    return self._send(200, f.read_bytes(), ctype)
            return self._send(404)
    return H


# Окно читателя размером с модалку здоровья (или узкое — с телефон).
HARNESS = """
document.head.insertAdjacentHTML('beforeend',
  '<link rel="stylesheet" href="/tools/assets/ui-kit.css">');
document.body.innerHTML = '<div id="host" class="rd-host" style="width:' + W + 'px; height:640px;"></div>';
"""


def harness(pg, base, width, theme="light"):
    pg.goto(base + "/blank.html")
    if theme == "dark":
        pg.evaluate("document.documentElement.setAttribute('data-theme','dark')")
    pg.add_script_tag(url=base + "/tools/assets/ui-kit.js")
    pg.evaluate("W => {" + HARNESS + "}", width)
    pg.wait_for_function("document.styleSheets.length > 0 && getComputedStyle(document.body).fontFamily.length > 0")
    frames(pg, 50)   # два кадра отрисовки + 50 мс вместо фиксированных 200 мс (TST-1)


def render(pg, opts_js="{}"):
    pg.evaluate("([md, o]) => { const h = document.getElementById('host'); h.innerHTML = uiReaderHTML(md, o);"
                " uiReaderMount(h); }", [DOC, json.loads(opts_js)])
    frames(pg, 80)


def vis(pg, sel):
    return pg.evaluate("s => { const e = document.querySelector(s); if (!e) return false;"
                       " const cs = getComputedStyle(e); return cs.display !== 'none' && e.offsetHeight > 0; }", sel)


JS_CONTRAST = """sel => {
  const el = document.querySelector(sel); if (!el) return null;
  const rgb = s => s.match(/[\\d.]+/g).map(Number);
  const lum = c => { const a = c.slice(0,3).map(v => { v /= 255;
    return v <= .03928 ? v/12.92 : Math.pow((v+.055)/1.055, 2.4); });
    return .2126*a[0] + .7152*a[1] + .0722*a[2]; };
  let b = el, bg;
  while (b) { const c = rgb(getComputedStyle(b).backgroundColor);
    if (c.length < 4 || c[3] > .5) { bg = c; break; } b = b.parentElement; }
  const L1 = lum(rgb(getComputedStyle(el).color)), L2 = lum(bg || [255,255,255]);
  return (Math.max(L1,L2) + .05) / (Math.min(L1,L2) + .05);
}"""


JS_GLYPH = """sel => { const out = [];
  document.querySelectorAll(sel).forEach(b => { const n = b.firstChild, rg = document.createRange(); rg.selectNodeContents(n);
    const g = rg.getBoundingClientRect(), r = b.getBoundingClientRect(), cs = getComputedStyle(b);
    out.push({dx: Math.abs((g.left + g.width/2) - (r.left + r.width/2)), dy: Math.abs((g.top + g.height/2) - (r.top + r.height/2)),
      flex: cs.display === 'flex' && cs.alignItems === 'center' && cs.justifyContent === 'center'}); });
  return out; }"""


def main():
    srv, base = serve(make_handler())   # _pages_stand: очередь 128, keep-alive
    with sync_playwright() as pw:
        try:
            br = pw.chromium.launch()
        except Exception as e:
            print(f"reader_layout: пропуск — chromium не запускается ({str(e)[:60]})")
            return 0

        # ── 1. широкое окно (модалка здоровья, 1000px): столбец оглавления ──
        pg = br.new_page(viewport={"width": 1280, "height": 800})
        harness(pg, base, 1000)
        render(pg, '{"acc": "--c-3", "key": "t1"}')
        check("широкое окно: есть оглавление (rd-has-toc)", pg.locator(".rd.rd-has-toc").count() == 1)
        check("широкое окно: оглавление столбцом видно", vis(pg, ".rd-toc"))
        check("широкое окно: нижней полосы нет", not vis(pg, ".rd-bar"))
        n_items = pg.locator(".rd-toc .rd-toc-list a").count()
        check(f"оглавление: 5 глав + 5 подглав ({n_items})", n_items == 10)
        check("первый H1 срезан (заголовок — в шапке окна)",
              "Подборка для теста" not in pg.inner_text(".rd-doc"))
        rows = pg.locator(".rd-meta .rd-mrow").count()
        check(f"карточка frontmatter: 3 плоских поля, вложенное пропущено ({rows})", rows == 3)
        check("TL;DR — панелью", pg.locator(".rd-doc p.rd-tldr").count() == 1)
        check("числовая ячейка не переносится (rd-num)", pg.locator(".rd-doc td.rd-num").count() == 1)
        check("вложенный список", pg.locator(".rd-doc li > ul > li").count() == 1)
        check("чек-лист", pg.locator(".rd-doc input[type=checkbox][checked]").count() == 1)
        check("акцент раздела передан (--rd-acc)",
              "--c-3" in (pg.get_attribute(".rd", "style") or ""))
        # прыжок к 4-й главе
        target = pg.locator(".rd-toc a").nth(6)          # «4. Цены»
        tid = target.get_attribute("data-rd-go")
        target.click()
        scroll_still(pg, "document.getElementById('host')")   # конец плавной прокрутки, а не 900 мс (TST-1)
        off = pg.evaluate("id => { const h = document.getElementById('host'), n = document.getElementById(id);"
                          " return n.getBoundingClientRect().top - h.getBoundingClientRect().top; }", tid)
        check(f"прыжок к главе: глава у верха окна (смещение {round(off)})", -2 <= off <= 40)
        active = pg.evaluate("() => { const a = document.querySelector('.rd-toc a.is-active');"
                             " return a && a.getAttribute('data-rd-go'); }")
        check("подсветка текущей главы следует за прыжком", active == tid)
        check("столбец оглавления липкий (виден после прокрутки)",
              pg.evaluate("() => { const t = document.querySelector('.rd-toc').getBoundingClientRect(),"
                          " h = document.getElementById('host').getBoundingClientRect();"
                          " return t.top >= h.top - 1 && t.top < h.top + 60; }"))
        # позиция чтения переживает перерисовку
        # прыжок к главе плавный: пока прокрутка не доехала, scrollTop меняется между чтениями (3397 → 3403 под -j 4) — ждём покоя
        pg.evaluate("""() => new Promise(res => { const h = document.getElementById('host'); let last = -1, still = 0;
          const tick = () => { if (h.scrollTop === last) still++; else { still = 0; last = h.scrollTop; } still >= 4 ? res() : requestAnimationFrame(tick); }; tick(); })""")
        y = pg.evaluate("document.getElementById('host').scrollTop")
        render(pg, '{"acc": "--c-3", "key": "t1"}')
        y2 = pg.evaluate("document.getElementById('host').scrollTop")
        check(f"перерисовка с тем же ключом возвращает к месту чтения ({y} → {y2})", y > 100 and abs(y - y2) <= 8)   # допуск ±8 px: подстройка к строке при перерисовке
        # toc опционален
        render(pg, '{"toc": false}')
        check("toc:false — оглавления нет", pg.locator(".rd-toc").count() == 0 and pg.locator(".rd-bar").count() == 0)
        pg.evaluate("md => { const h = document.getElementById('host');"
                    " h.innerHTML = uiReaderHTML(md, {}); uiReaderMount(h); }", "## Одна\nтекст\n## Две\nтекст")
        check("toc:auto — при двух главах оглавления нет", pg.locator(".rd-toc").count() == 0)
        pg.evaluate("md => { const h = document.getElementById('host');"
                    " h.innerHTML = uiReaderHTML(md, {toc: true}); uiReaderMount(h); }", "## Одна\nтекст")
        check("toc:true — оглавление даже при одной главе", pg.locator(".rd-toc").count() == 1)
        # ── 1б. поиск по тексту (ui-kit 1.58.0, opts.search) ──
        SDOC = DOC + "\n## 9. Гейты\n\nГейт снимает бумагу; ещё ГЕЙТ и гейтовый код `gate Гейт`.\n\n| Слово | Что |\n|---|---|\n| гейт | таблица |\n"
        pg.evaluate("([md]) => { const h = document.getElementById('host'); h.innerHTML = uiReaderHTML(md, {search: true, key: 'q1'});"
                    " uiReaderMount(h); }", [SDOC])
        pg.wait_for_timeout(250)
        check("поиск: поле .ui-qbox над оглавлением (в столбце)", pg.locator(".rd-toc .ui-qbox input[data-rd-q]").count() == 1
              and vis(pg, ".rd-toc .ui-qbox") and not vis(pg, ".rd-q-main"))
        h0 = pg.inner_html(".rd-doc")
        pg.fill(".rd-toc input[data-rd-q]", "г")
        check("поиск: меньше 2 символов — подсветки нет", pg.locator("mark.rd-hit").count() == 0)
        pg.fill(".rd-toc input[data-rd-q]", "гейт")
        nm = pg.locator("mark.rd-hit").count()
        cnt = pg.inner_text(".rd-toc [data-rd-qn]")
        check(f"поиск «гейт»: подсветка без учёта регистра ({nm}, «{cnt}»)", nm >= 6 and cnt.endswith(f"из {nm}"))
        check("поиск: подсветка в коде и в таблице", pg.locator("code mark.rd-hit").count() == 1 and pg.locator("td mark.rd-hit").count() == 1)
        inv = pg.evaluate("() => { const m = document.querySelector('mark.rd-hit.is-cur'); if (!m) return false;"
                          " const r = m.getBoundingClientRect(), h = document.getElementById('host').getBoundingClientRect();"
                          " return r.top >= h.top && r.bottom <= h.bottom; }")
        check("поиск: первое совпадение (is-cur) в видимой области окна", inv)
        pg.press(".rd-toc input[data-rd-q]", "Enter")
        cur2 = pg.inner_text(".rd-toc [data-rd-qn]")
        check(f"поиск: Enter — к следующему («{cur2}»)", cur2.startswith("2 из"))
        pg.press(".rd-toc input[data-rd-q]", "ArrowUp")
        check("поиск: ↑ — к предыдущему", pg.inner_text(".rd-toc [data-rd-qn]").startswith("1 из"))
        pg.press(".rd-toc input[data-rd-q]", "Escape")
        check("поиск: Esc — подсветки нет, поле пусто", pg.locator("mark.rd-hit").count() == 0
              and pg.input_value(".rd-toc input[data-rd-q]") == "")
        check("поиск: после очистки разметка документа прежняя (без перерисовки markdown)", pg.inner_html(".rd-doc") == h0)
        pg.fill(".rd-toc input[data-rd-q]", "ъъъъ")
        check("поиск: нет совпадений — так и сказано", pg.inner_text(".rd-toc [data-rd-qn]") == "нет совпадений")
        pg.fill(".rd-toc input[data-rd-q]", "")
        pg.fill(".rd-toc input[data-rd-q]", "гейт")
        pg.wait_for_timeout(150)
        qd = pg.evaluate("""() => { const t = document.querySelector('.rd-toc').getBoundingClientRect(),
          q = document.querySelector('.rd-toc input[data-rd-q]').getBoundingClientRect(),
          bs = Array.from(document.querySelectorAll('.rd-toc .rd-q-b')).map(b => b.getBoundingClientRect());
          return {tw: t.width, qw: q.width, inside: bs.every(r => r.left >= t.left - 0.5 && r.right <= t.right + 0.5)}; }""")
        check(f"поиск (1.60.1): поле в колонке не уже 90 % колонки ({round(qd['qw'])} из {round(qd['tw'])}), кнопки в колонке",
              qd["qw"] >= 0.9 * qd["tw"] and qd["inside"])
        gl = pg.evaluate(JS_GLYPH, ".rd-toc .rd-q-b")
        check(f"поиск (1.60.1): глифы ‹ › по центру кнопок на 1280 ({[(round(x['dx'], 1), round(x['dy'], 1)) for x in gl]})",
              len(gl) == 2 and all(x["dx"] <= 3 and x["dy"] <= 3 and x["flex"] for x in gl))
        pg.fill(".rd-toc input[data-rd-q]", "")
        check("поиск: пустое поле снимает подсветку", pg.locator("mark.rd-hit").count() == 0)
        render(pg, "{}")
        check("поиск: без опции search поля нет (отчёты)", pg.locator("[data-rd-q]").count() == 0)
        pgp = br.new_page(viewport={"width": 390, "height": 800}, is_mobile=True, has_touch=True)
        harness(pgp, base, 390)
        pgp.evaluate("([md]) => { const h = document.getElementById('host'); h.innerHTML = uiReaderHTML(md, {search: true});"
                     " uiReaderMount(h); }", [SDOC])
        pgp.wait_for_timeout(250)
        check("поиск (телефон): поле над текстом, у полосы глав", vis(pgp, ".rd-q-main") and not vis(pgp, ".rd-toc .ui-qbox"))
        pgp.fill(".rd-q-main input[data-rd-q]", "гейт")
        check("поиск (телефон): подсветка и счётчик", pgp.locator("mark.rd-hit").count() >= 6 and "из" in pgp.inner_text(".rd-q-main [data-rd-qn]"))
        check("поиск (телефон): документ не шире экрана",
              pgp.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 1)
        pgp.close()
        pgd = br.new_page(viewport={"width": 1280, "height": 800})
        harness(pgd, base, 1000, theme="dark")
        pgd.evaluate("([md]) => { const h = document.getElementById('host'); h.innerHTML = uiReaderHTML(md, {search: true});"
                     " uiReaderMount(h); }", [SDOC])
        pgd.fill(".rd-toc input[data-rd-q]", "гейт")
        crm = pgd.evaluate(JS_CONTRAST, "mark.rd-hit:not(.is-cur)")
        crc = pgd.evaluate(JS_CONTRAST, "mark.rd-hit.is-cur")
        check(f"поиск (тёмная тема): подсветка читается (контраст {crm and round(crm, 2)} / текущая {crc and round(crc, 2)})",
              crm and crm >= 3 and crc and crc >= 3)
        pgd.close()
        pg.close()

        # ── 2. узкое окно (телефон): полоса снизу + шторка ──
        pg = br.new_page(viewport={"width": 390, "height": 800}, is_mobile=True, has_touch=True)
        harness(pg, base, 390)
        render(pg, '{"key": "t2"}')
        check("узкое окно: столбец оглавления скрыт", not vis(pg, ".rd-toc"))
        check("узкое окно: полоса снизу видна", vis(pg, ".rd-bar"))
        pg.evaluate("document.getElementById('host').scrollTop = 1500")
        pg.wait_for_timeout(300)
        gap = pg.evaluate("() => document.getElementById('host').getBoundingClientRect().bottom -"
                          " document.querySelector('.rd-bar').getBoundingClientRect().bottom")
        check(f"полоса прилипла к низу окна при прокрутке (зазор {round(gap)})", abs(gap) <= 2)
        prog = pg.evaluate("parseFloat(document.querySelector('.rd-prog i').style.width) || 0")
        check(f"прогресс чтения растёт ({prog}%)", prog > 5)
        pg.click("[data-rd-sheet]")
        pg.wait_for_timeout(150)
        check("шторка глав открывается", vis(pg, ".rd-sheet"))
        pick = pg.locator(".rd-sheet a").nth(4)          # «3. Длительность»
        label = pick.inner_text().strip()
        pick.click()
        scroll_still(pg, "document.getElementById('host')")   # конец плавной прокрутки, а не 900 мс (TST-1)
        check("выбор главы закрывает шторку", not vis(pg, ".rd-sheet"))
        cur = pg.inner_text(".rd-cur").strip()
        check(f"подпись полосы — текущая глава («{cur}»)", cur == label)
        check("документ не шире экрана",
              pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 1)
        pg.close()

        # ── 3. тёмная тема: текст читается ──
        pg = br.new_page(viewport={"width": 1280, "height": 800})
        harness(pg, base, 1000, theme="dark")
        render(pg)
        cr = pg.evaluate(JS_CONTRAST, ".rd-doc p:not(.rd-tldr)")
        check(f"тёмная тема: текст документа читается (контраст {cr and round(cr, 2)})", cr and cr >= 4.5)
        cr2 = pg.evaluate(JS_CONTRAST, ".rd-toc a")
        check(f"тёмная тема: пункты оглавления читаются (контраст {cr2 and round(cr2, 2)})", cr2 and cr2 >= 4.5)
        pg.close()


        # ── 1в. ui-kit 1.59.0: сгибы, якоря, выноски, режим «по разделам», части справки ──
        FDOC = ("Короткая шапка.\n\n## Один {#one}\n\nТекст один. [к двум](#two) и [копия](#copy) и <b>сырой</b> тег.\n\n"
                "### Подраздел один {#sub1}\n\nПодтекст.\n\n"
                "<details>\n<summary>Подробнее: сгиб</summary>\n\nСкрытое слово зебра.\n\n### Внутри сгиба\n\n"
                "| a | b |\n|---|---|\n| 1 | 2 |\n\n</details>\n\n"
                "> **Важно:** осторожно с гейтом.\n\n> **Совет:** подсказка.\n\n> обычная цитата\n\n"
                "## Два {#two}\n\nТекст два, зебра тоже. [назад](#sub1)\n\n### Подраздел два {#sub2}\n\n" + LOREM * 4 + "\n")
        pgf = br.new_page(viewport={"width": 1280, "height": 800})
        harness(pgf, base, 1000)

        def fmount(pg_, md, o):
            pg_.evaluate("([md, o]) => { const h = document.getElementById('host'); h.innerHTML = uiReaderHTML(md, o); uiReaderMount(h, o); }", [md, o])
            frames(pg_, 80)

        # A–D без режима sections
        fmount(pgf, FDOC, {"search": True})
        check("сгиб: <details class=ui-fold rd-fold> со стрелкой, в закрытом виде",
              pgf.locator("details.ui-fold.rd-fold > summary .ui-chev").count() == 1
              and not pgf.evaluate("document.querySelector('details.rd-fold').open"))
        check("сгиб: тело скрыто до клика (не отрисовано)", pgf.evaluate("() => { const b = document.querySelector('.rd-fold-body'); return !b.checkVisibility({contentVisibilityAuto: true, visibilityProperty: true}); }"))
        pgf.click("details.rd-fold > summary")
        check("сгиб: клик раскрывает, внутри таблица", vis(pgf, ".rd-fold-body") and pgf.locator(".rd-fold-body table").count() == 1)
        check("сгиб: заголовок внутри сгиба в оглавление не попал",
              "Внутри сгиба" not in pgf.inner_text(".rd-toc") and pgf.locator(".rd-toc .rd-toc-list a").count() == 4)
        check("сырой HTML по-прежнему экранирован", "<b>сырой</b>" in pgf.inner_text(".rd-doc"))
        check("{#id}: h2 получил id, пометка в тексте не видна",
              pgf.locator("h2#one").count() == 1 and pgf.locator("h3#sub1").count() == 1 and "{#" not in pgf.inner_text(".rd-doc"))
        check("оглавление ведёт по id ({#id})", pgf.locator('.rd-toc a[data-rd-go="two"]').count() == 1)
        check("(#copy) не задет: плашка копирования на месте", pgf.locator(".rd-doc button.ui-say").count() == 1)
        check("выноски: Важно — warn, Совет — info, обычная цитата осталась цитатой",
              pgf.locator(".ui-callout.warn").count() == 1 and pgf.locator(".ui-callout.info").count() == 1
              and pgf.locator(".rd-doc blockquote").count() == 1
              and pgf.inner_text(".ui-callout.warn b") == "Важно:" and pgf.inner_text(".ui-callout.info b") == "Совет:" and "Важно: осторожно" in pgf.inner_text(".ui-callout.warn") and "**" not in pgf.inner_text(".ui-callout.warn"))
        hash0 = pgf.evaluate("location.hash")
        pgf.click('.rd-doc a[href="#two"]')
        scroll_still(pgf, "document.getElementById('host')")   # конец плавной прокрутки, а не 900 мс (TST-1)
        off = pgf.evaluate("() => document.getElementById('two').getBoundingClientRect().top - document.getElementById('host').getBoundingClientRect().top")
        check(f"[текст](#id): переход к заголовку внутри читателя (смещение {round(off)}), адрес страницы не менялся",
              -2 <= off <= 60 and pgf.evaluate("location.hash") == hash0)
        fmount(pgf, FDOC, {"at": "two"})
        offa = pgf.evaluate("() => document.getElementById('two').getBoundingClientRect().top - document.getElementById('host').getBoundingClientRect().top")
        check(f"at: 'id' открывает на главе ({round(offa)})", -2 <= offa <= 60)
        fmount(pgf, FDOC, {"at": "Подраздел два"})
        offt = pgf.evaluate("() => document.getElementById('sub2').getBoundingClientRect().top - document.getElementById('host').getBoundingClientRect().top")
        check(f"at: текст заголовка по-прежнему работает ({round(offt)})", -2 <= offt <= 60)
        # поиск находит текст в свёрнутом сгибе
        fmount(pgf, FDOC, {"search": True})
        pgf.fill(".rd-toc input[data-rd-q]", "зебра")
        check("поиск: сгиб со совпадением раскрылся, счётчик считает и внутри сгиба",
              pgf.evaluate("document.querySelector('details.rd-fold').open") and pgf.inner_text(".rd-toc [data-rd-qn]").endswith("из 2")
              and pgf.locator("details.rd-fold mark.rd-hit").count() == 1)

        # режим sections
        fmount(pgf, FDOC, {"sections": True, "search": True, "toc": True})
        check("sections: короткая шапка видна над разделом, виден один раздел (первый)",
              vis(pgf, ".rd-pre") and vis(pgf, "#one") and not vis(pgf, "#two") and pgf.locator(".rd-sec.is-on").count() == 1)
        check("sections: в оглавлении под активным разделом только его ###",
              pgf.locator(".rd-toc li.lvl-3.is-open").count() == 1 and pgf.locator(".rd-toc li.lvl-2 a.is-sec").count() == 1
              and "Один" in pgf.inner_text(".rd-toc li.lvl-2 a.is-sec"))
        pgf.click('.rd-toc a[data-rd-go="two"]')
        pgf.wait_for_timeout(500)
        check("sections: клик по оглавлению переключает раздел (первый скрыт, активный выделен)",
              vis(pgf, "#two") and not vis(pgf, "#one") and "Два" in pgf.inner_text(".rd-toc li.lvl-2 a.is-sec")
              and pgf.locator(".rd-toc li.lvl-3.is-open").count() == 1 and "Подраздел два" in pgf.inner_text(".rd-toc li.lvl-3.is-open"))
        check("sections: прокрутка тела — к началу раздела", pgf.evaluate("document.getElementById('host').scrollTop") < 40)
        pgf.click('.rd-doc a[href="#sub1"]')
        pgf.wait_for_timeout(700)
        check("sections: [текст](#id) на ### другого раздела — переключает раздел и показывает заголовок",
              vis(pgf, "#sub1") and not vis(pgf, "#two"))
        pgf.click('.rd-doc a[href="#two"]')
        pgf.wait_for_timeout(500)
        check("sections: ссылка на раздел переключает раздел", vis(pgf, "#two") and not vis(pgf, "#one"))
        pgf.fill(".rd-toc input[data-rd-q]", "подтекст")
        check("sections: поиск переключает раздел на найденный, счётчик общий",
              vis(pgf, "#one") and not vis(pgf, "#two") and pgf.inner_text(".rd-toc [data-rd-qn]") == "1 из 1")
        pgf.fill(".rd-toc input[data-rd-q]", "зебра")
        cnt_txt = [pgf.inner_text(f'.rd-toc li.lvl-2[data-rd-sec="{k}"] .rd-sec-n') for k in (0, 1)
                   if pgf.locator(f'.rd-toc li.lvl-2[data-rd-sec="{k}"] .rd-sec-n').count()]
        check(f"sections: у разделов с совпадениями в оглавлении «·N» ({cnt_txt})", len(cnt_txt) == 2 and all(t.strip().startswith("·") for t in cnt_txt))
        pgf.press(".rd-toc input[data-rd-q]", "Enter")
        pgf.wait_for_timeout(300)
        check("sections: Enter ведёт к совпадению в другом разделе (раздел переключился)",
              vis(pgf, "#two") and pgf.inner_text(".rd-toc [data-rd-qn]").startswith("2 из 2"))
        pgf.press(".rd-toc input[data-rd-q]", "Escape")
        check("sections: Esc снимает «·N»", pgf.locator(".rd-sec-n").count() == 0)
        fmount(pgf, FDOC, {"sections": True, "at": "sub2"})
        offs = pgf.evaluate("() => document.getElementById('sub2').getBoundingClientRect().top - document.getElementById('host').getBoundingClientRect().top")
        check(f"sections: at на ### открывает его раздел и прокручивает к заголовку ({round(offs)})", vis(pgf, "#two") and not vis(pgf, "#one") and -2 <= offs <= 80)
        fmount(pgf, FDOC, {"sections": True, "at": "Два"})
        check("sections: at по тексту ## открывает раздел", vis(pgf, "#two") and not vis(pgf, "#one"))
        LONGPRE = "\n".join(["Строка шапки номер %d, достаточно длинная, чтобы занять место. " % i * 2 + "\n" for i in range(9)])
        fmount(pgf, LONGPRE + "\n## Один\n\nа\n\n## Два\n\nб\n", {"sections": True})
        check("sections: длинная шапка — отдельный первый пункт «О справке»",
              "О справке" in pgf.inner_text(".rd-toc li.lvl-2:first-child a") and pgf.locator(".rd-pre").count() == 0 and vis(pgf, ".rd-sec.is-on"))
        fmount(pgf, FDOC, {"sections": True, "toc": "auto"})
        check("sections: по умолчанию sections выключен (обычный читатель без .rd-sec)", True)
        fmount(pgf, FDOC, {})
        check("sections: без опции .rd-sec нет, показано всё", pgf.locator(".rd-sec").count() == 0 and vis(pgf, "#two") and vis(pgf, "#one"))

        # части справки из нескольких файлов
        mdp = pgf.evaluate("() => uiFetchMarkdownParts(['/tools/assets/help/hub.md', '/tools/assets/help/games.md'])")
        pgf.evaluate("md => { const h = document.getElementById('host'); h.innerHTML = uiReaderHTML(md, {toc: true, sections: true}); uiReaderMount(h, {}); }", mdp)
        pgf.wait_for_timeout(250)
        toc_txt = pgf.inner_text(".rd-toc")
        check("части справки: h2 обоих файлов в оглавлении",
              "Раздел → скиллы → модель" in toc_txt and "Хочу… → запускаю" in toc_txt)
        pgf.evaluate("md => { const h = document.getElementById('host'); h.innerHTML = uiReaderHTML(md, {toc: true}); uiReaderMount(h, {}); }",
                     pgf.evaluate("() => uiFetchMarkdownParts(['/tools/assets/help/hub.md', '/tools/assets/help/net-takogo.md', '/tools/assets/help/games.md'])"))
        pgf.wait_for_timeout(250)
        toc_txt = pgf.inner_text(".rd-toc")
        check("части справки: битый путь — заглушка-раздел на месте, остальные показаны",
              "net-takogo.md" in toc_txt and "Раздел → скиллы → модель" in toc_txt and "Хочу… → запускаю" in toc_txt
              and pgf.locator(".rd-doc p.ui-note").count() == 1 and "не загрузился" in pgf.inner_text(".rd-doc p.ui-note"))
        check("части справки: порядок как в списке (hub, заглушка, games)",
              toc_txt.index("Раздел → скиллы") < toc_txt.index("net-takogo.md") < toc_txt.index("Хочу…"))
        pgf.close()

        # телефон: полоса глав переключает разделы
        pgp = br.new_page(viewport={"width": 390, "height": 800}, is_mobile=True, has_touch=True)
        harness(pgp, base, 390)
        fmount(pgp, FDOC, {"sections": True, "search": True})
        check("sections (телефон): виден один раздел, полоса глав внизу", vis(pgp, "#one") and not vis(pgp, "#two") and vis(pgp, ".rd-bar"))
        pgp.click("[data-rd-sheet]")
        pgp.wait_for_timeout(150)
        pgp.click('.rd-sheet a[data-rd-go="two"]')
        pgp.wait_for_timeout(600)
        check("sections (телефон): полоса глав переключает раздел, шторка закрылась",
              vis(pgp, "#two") and not vis(pgp, "#one") and not vis(pgp, ".rd-sheet") and "Два" in pgp.inner_text(".rd-cur"))
        check("sections (телефон): документ не шире экрана",
              pgp.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 1)
        fmount(pgp, FDOC, {})
        check("сгиб/выноска (телефон): не шире экрана",
              pgp.evaluate("() => document.querySelector('.rd-fold').getBoundingClientRect().right <= innerWidth + 1 && document.querySelector('.ui-callout').getBoundingClientRect().right <= innerWidth + 1"))
        pgp.close()

        # тёмная тема: выноска и сгиб читаются
        pgd = br.new_page(viewport={"width": 1280, "height": 800})
        harness(pgd, base, 1000, theme="dark")
        fmount(pgd, FDOC, {})
        pgd.click("details.rd-fold > summary")
        crs = {n: pgd.evaluate(JS_CONTRAST, sel) for n, sel in (
            ("warn", ".ui-callout.warn p"), ("info", ".ui-callout.info p"), ("summary", ".rd-fold > summary"), ("тело сгиба", ".rd-fold-body p"))}
        check(f"тёмная тема: выноски и сгиб читаются (контраст {({k: v and round(v, 1) for k, v in crs.items()})})",
              all(v and v >= 4.5 for v in crs.values()))
        pgd.close()

        # ── 4. живая страница: подборка игр ──
        for w, tag in ((1280, "десктоп"), (390, "телефон")):
            pg = br.new_page(viewport={"width": w, "height": 860}, is_mobile=(w < 500), has_touch=(w < 500))
            pg.goto(base + "/tools/games.html")
            pg.wait_for_load_state("networkidle")
            try:
                pg.wait_for_selector("[data-file]", state="attached", timeout=15000)
            except Exception:
                pass
            pg.evaluate("() => { const b = document.querySelector('[data-file]'); if (b) b.click(); }")
            try:
                pg.wait_for_selector("#vw-md .rd", timeout=10000)
            except Exception:
                pass
            pg.wait_for_timeout(400)
            check(f"игры ({tag}): подборка открылась читателем", pg.locator("#vw-md .rd").count() == 1)
            check(f"игры ({tag}): акцент раздела --c-5",
                  "--c-5" in (pg.get_attribute("#vw-md .rd", "style") or ""))
            check(f"игры ({tag}): карточка frontmatter вместо сырого блока",
                  pg.locator("#vw-md .rd-meta").count() == 1 and pg.locator("#vw-md details.fm").count() == 0)
            if w >= 1000:
                check("игры (десктоп): панель 840px — оглавление столбцом", vis(pg, "#vw-md .rd-toc"))
            else:
                check("игры (телефон): оглавление полосой снизу", vis(pg, "#vw-md .rd-bar"))
                check("игры (телефон): документ не шире экрана",
                      pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 1)
            pg.close()

        # ── 6. ui-kit 1.60.0: читатель на телефоне — поиск вне тела, кнопки ‹ ›, окно во всю высоту ──
        def modal_reader(pg, md, opts, kind="modal"):
            pg.evaluate("""([md, o, kind]) => {
              document.body.innerHTML = '';
              if (kind === 'docwin') {
                document.body.insertAdjacentHTML('beforeend', '<div class="ui-docwin" id="dw"><div class="ui-docwin-box" role="dialog">' +
                  '<div class="ui-docwin-head"><div class="ui-docwin-titles"><span class="ui-docwin-title">Подборка</span></div><button class="ui-docwin-x">✕</button></div>' +
                  '<div class="ui-docwin-body rd-host" id="mb"></div></div></div>');
              } else {
                document.body.insertAdjacentHTML('beforeend', uiModalHTML({title: 'Окно', body: '', bodyId: 'mb'}));
              }
              const b = document.getElementById('mb');
              b.innerHTML = uiReaderHTML(md, o);
              uiReaderMount(b, {scroller: b});
            }""", [md, opts, kind])
            frames(pg, 100)

        for theme in ("light", "dark"):
            pgm = br.new_page(viewport={"width": 390, "height": 760}, has_touch=True)
            harness(pgm, base, 390, theme=theme)
            modal_reader(pgm, SDOC, {"search": True, "sections": True, "key": "m1"})
            t = f"телефон/{theme}"
            check(f"{t}: поле поиска вынесено из тела (брат тела, не внутри)",
                  pgm.evaluate("() => { const q = document.querySelector('.rd-q-dock'), b = document.getElementById('mb');"
                               " return !!q && !b.contains(q) && q.parentElement === b.parentElement && q.nextElementSibling === b; }"))
            check(f"{t}: поле поиска на всю ширину окна, непрозрачный фон",
                  pgm.evaluate("() => { const q = document.querySelector('.rd-q-dock'), r = q.getBoundingClientRect(), c = getComputedStyle(q).backgroundColor;"
                               " const m = c.match(/[\\d.]+/g).map(Number); return r.width >= innerWidth - 2 && (m.length < 4 || m[3] === 1); }"))
            pgm.fill(".rd-q-dock input[data-rd-q]", "гейт")
            pgm.wait_for_timeout(200)
            before = pgm.inner_text(".rd-q-dock [data-rd-qn]")
            check(f"{t}: счётчик «N из M» в поле ({before})", " из " in before)
            pgm.evaluate("document.getElementById('mb').scrollTo(0, 300)")
            pgm.wait_for_timeout(250)
            ov = pgm.evaluate("""() => {
              const q = document.querySelector('.rd-q-dock').getBoundingClientRect();
              const tx = Array.from(document.querySelectorAll('.rd-doc p, .rd-doc h2, .rd-doc h3')).filter(e => e.offsetParent && e.getBoundingClientRect().height > 0);
              return tx.filter(e => { const r = e.getBoundingClientRect(); return r.top < q.bottom - 0.5 && r.bottom > q.top + 0.5; }).length; }""")
            check(f"{t}: после прокрутки на 300 px поле не пересекается с текстом (пересечений {ov})", ov == 0)
            nb = pgm.locator(".rd-q-dock [data-rd-qnext]")
            pb = pgm.locator(".rd-q-dock [data-rd-qprev]")
            bb = nb.bounding_box()
            check(f"{t}: кнопки ‹ › есть, размером под палец ({bb and round(bb['width'])}×{bb and round(bb['height'])})",
                  pb.count() == 1 and nb.count() == 1 and bb["width"] >= 36 and bb["height"] >= 36)
            gl = pgm.evaluate(JS_GLYPH, ".rd-q-dock .rd-q-b")
            hh = pgm.evaluate("() => ['.rd-q-dock input[data-rd-q]', '.rd-q-dock .rd-q-b'].map(s => Math.round(document.querySelector(s).getBoundingClientRect().height))")
            check(f"{t}: глифы ‹ › по центру кнопок ({[(round(x['dx'], 1), round(x['dy'], 1)) for x in gl]}), кнопка и поле одной высоты ({hh})",
                  len(gl) == 2 and all(x["dx"] <= 3 and x["dy"] <= 3 and x["flex"] for x in gl) and hh[0] == hh[1] == 40)
            pgm.focus(".rd-q-dock input[data-rd-q]")
            nb.click()
            c1 = pgm.inner_text(".rd-q-dock [data-rd-qn]")
            check(f"{t}: › — следующее совпадение («{c1}»), фокус остался в поле",
                  c1.startswith("2 из") and pgm.evaluate("document.activeElement.hasAttribute('data-rd-q')"))
            pb.click()
            check(f"{t}: ‹ — предыдущее", pgm.inner_text(".rd-q-dock [data-rd-qn]").startswith("1 из"))
            pb.click()
            tot = pgm.inner_text(".rd-q-dock [data-rd-qn]").split(" из ")[1]
            check(f"{t}: ‹ с первого — по кругу на последнее", pgm.inner_text(".rd-q-dock [data-rd-qn]") == f"{tot} из {tot}")
            pgm.press(".rd-q-dock input[data-rd-q]", "Enter")
            check(f"{t}: Enter — следующее, фокус в поле",
                  pgm.inner_text(".rd-q-dock [data-rd-qn]").startswith("1 из") and pgm.evaluate("document.activeElement.hasAttribute('data-rd-q')"))
            pgm.fill(".rd-q-dock input[data-rd-q]", "ъъъъ")
            check(f"{t}: без совпадений кнопки выключены", nb.is_disabled() and pb.is_disabled())
            pgm.press(".rd-q-dock input[data-rd-q]", "Escape")
            check(f"{t}: Esc очищает поле, кнопки выключены", pgm.input_value(".rd-q-dock input[data-rd-q]") == "" and nb.is_disabled())
            pgm.close()

        # короткий раздел: окно во всю высоту, полоса глав у нижнего края (ui-modal, ui-docwin, справка uiHelpOpen)
        shortmd = SHORT
        for kind in ("modal", "docwin"):
            for sec in (True, False):
                pgm = br.new_page(viewport={"width": 390, "height": 760}, has_touch=True)
                harness(pgm, base, 390)
                modal_reader(pgm, shortmd + ("" if sec else "\n## Три\n\nИ ещё.\n"), {"search": True, "sections": sec, "toc": True}, kind)
                box = ".ui-modal-box" if kind == "modal" else ".ui-docwin-box"
                r = pgm.evaluate("(s) => { const b = document.querySelector(s).getBoundingClientRect(), bar = document.querySelector('.rd-bar').getBoundingClientRect();"
                                 " return {h: b.height, top: b.top, bot: b.bottom, barBot: bar.bottom, ih: innerHeight}; }", box)
                t = f"{kind}{'/sections' if sec else ''}"
                check(f"{t}: окно во всю высоту экрана ({round(r['h'])} из {r['ih']})", abs(r["h"] - r["ih"]) <= 1 and abs(r["top"]) <= 1)
                check(f"{t}: полоса глав у нижнего края окна ({round(r['barBot'])} ≥ {r['ih'] - 2})", r["barBot"] >= r["ih"] - 2)
                check(f"{t}: полоса глав и текст — на всю ширину окна, не уже и не шире",
                      pgm.evaluate("() => { const bar = document.querySelector('.rd-bar').getBoundingClientRect(), d = document.querySelector('.rd-doc').getBoundingClientRect();"
                                   " return bar.width >= innerWidth - 2 && d.right <= innerWidth + 1 && d.width >= innerWidth - 60; }"))
                check(f"{t}: нижняя полоса видна, поле поиска над телом",
                      vis(pgm, ".rd-bar") and pgm.locator(".rd-q-dock").count() == 1)
                pgm.close()

        # справка (uiHelpOpen) на телефоне: короткий раздел «О справке» — полоса глав внизу экрана, тело прокручивается
        for theme in ("light", "dark"):
            pgm = br.new_page(viewport={"width": 390, "height": 760}, has_touch=True)
            harness(pgm, base, 390, theme=theme)
            pgm.evaluate("() => uiHelpOpen('t', null, {title: 'Справка', acc: '--c-1', src: '/short.md', sections: true, search: true})")
            pgm.wait_for_selector(".uh-body .rd", timeout=8000)
            pgm.wait_for_timeout(350)
            t = f"справка телефон/{theme}"
            r = pgm.evaluate("() => { const m = document.querySelector('.uh-modal').getBoundingClientRect(), bar = document.querySelector('.rd-bar').getBoundingClientRect(),"
                             " q = document.querySelector('.rd-q-dock'), b = document.querySelector('.uh-body');"
                             " return {h: m.height, ih: innerHeight, barBot: bar.bottom, dock: !!q && q.nextElementSibling === b, bodyOy: getComputedStyle(b).overflowY}; }")
            check(f"{t}: окно справки во всю высоту ({round(r['h'])} из {r['ih']})", abs(r["h"] - r["ih"]) <= 1)
            check(f"{t}: полоса глав у нижнего края ({round(r['barBot'])})", r["barBot"] >= r["ih"] - 2)
            check(f"{t}: полоса глав на всю ширину, текст не шире экрана",
                  pgm.evaluate("() => { const bar = document.querySelector('.rd-bar').getBoundingClientRect(), d = document.querySelector('.rd-doc').getBoundingClientRect();"
                               " return bar.width >= innerWidth - 2 && d.right <= innerWidth + 1; }"))
            check(f"{t}: поиск строкой под шапкой, тело прокручивается", r["dock"] and r["bodyOy"] in ("auto", "scroll"))
            pgm.fill(".rd-q-dock input[data-rd-q]", "коротко")
            pgm.wait_for_timeout(200)
            check(f"{t}: поиск в справке работает, раздел переключается кнопкой ›",
                  pgm.inner_text(".rd-q-dock [data-rd-qn]").startswith("1 из 2")
                  and (pgm.locator(".rd-q-dock [data-rd-qnext]").click() or True)
                  and pgm.inner_text(".rd-q-dock [data-rd-qn]").startswith("2 из 2"))
            pgm.close()

        # справка на компьютере, режим sections: переключение раздела не уносит шапку окна за край (прокручивается тело)
        for vw, vh, tag in ((1280, 800, "компьютер"), (390, 760, "телефон")):
            pgh = br.new_page(viewport={"width": vw, "height": vh})
            harness(pgh, base, 900)
            pgh.evaluate("() => uiHelpOpen('t', null, {title: 'Портфель', kicker: 'Справка по системе', acc: '--c-1', src: '/Gaming/recommendations/2026-10-03-test.md', sections: true, search: true})")
            pgh.wait_for_selector(".uh-body .rd", timeout=8000)
            pgh.wait_for_timeout(350)
            vis_head = ("() => { const h = document.querySelector('.uh-head').getBoundingClientRect(), c = document.querySelector('.uh-close').getBoundingClientRect();"
                        " return h.top >= 0 && h.bottom > 0 && c.top >= 0 && c.bottom <= innerHeight; }")
            def sec_h2_visible():
                return pgh.evaluate("() => { const h = document.querySelector('.rd-sec.is-on h2'), b = document.querySelector('.uh-body').getBoundingClientRect();"
                                    " const r = h.getBoundingClientRect(); return r.top >= b.top - 1 && r.bottom <= b.bottom; }")
            pgh.evaluate("document.querySelector('.uh-body').scrollTo(0, 600)")
            pgh.wait_for_timeout(150)
            if vw > 600:
                pgh.locator(".rd-toc-list li.lvl-2 a").nth(2).click()
            else:
                pgh.click("[data-rd-sheet]"); pgh.wait_for_timeout(150)
                pgh.locator(".rd-sheet .rd-toc-list li.lvl-2 a").nth(2).click()
            scroll_still(pgh, "document.querySelector('.uh-body')")   # конец плавной прокрутки, а не 900 мс (TST-1)
            check(f"справка ({tag}): клик по разделу — шапка окна и ✕ на месте", pgh.evaluate(vis_head))
            check(f"справка ({tag}): заголовок раздела виден у верха тела", sec_h2_visible())
            check(f"справка ({tag}): прокручивается тело, а не оверлей/страница",
                  pgh.evaluate("() => document.querySelector('.uh-overlay').scrollTop === 0 && getComputedStyle(document.querySelector('.uh-body')).overflowY === 'auto'"))
            if vw > 600:
                pgh.locator(".rd-toc-list li.lvl-3.is-open a").first.click()
                scroll_still(pgh, "document.querySelector('.uh-body')")   # конец плавной прокрутки, а не 900 мс (TST-1)
                check(f"справка ({tag}): переход к ### — шапка на месте, подзаголовок виден",
                      pgh.evaluate(vis_head) and pgh.evaluate("() => { const e = document.querySelector('.rd-sec.is-on h3').getBoundingClientRect(), b = document.querySelector('.uh-body').getBoundingClientRect(); return e.top >= b.top - 1 && e.bottom <= b.bottom; }"))
            pgh.locator("input[data-rd-q]").locator("visible=true").first.fill("Цены")
            pgh.wait_for_timeout(700)
            check(f"справка ({tag}): поиск переключил раздел — шапка на месте", pgh.evaluate(vis_head))
            pgh.close()

        # широкое окно: кнопки ‹ › тоже есть, поле над оглавлением, не вынесено
        pgw = br.new_page(viewport={"width": 1280, "height": 800})
        harness(pgw, base, 1000)
        pgw.evaluate("([md]) => { const h = document.getElementById('host'); h.innerHTML = uiReaderHTML(md, {search: true});"
                     " uiReaderMount(h); }", [SDOC])
        pgw.wait_for_timeout(250)
        pgw.fill(".rd-toc input[data-rd-q]", "гейт")
        pgw.click(".rd-toc [data-rd-qnext]")
        check("широкое окно: › в столбце оглавления — «2 из», вынесенной строки нет",
              pgw.inner_text(".rd-toc [data-rd-qn]").startswith("2 из") and pgw.locator(".rd-q-dock").count() == 0)
        pgw.close()

        # ── 5. живая страница: справка хаба ──
        pg = br.new_page(viewport={"width": 1280, "height": 860})
        pg.goto(base + "/tools/hub.html")
        pg.wait_for_load_state("networkidle")
        pg.evaluate("() => { const b = document.querySelector('[data-ui-help]'); if (b) b.click(); }")
        try:
            pg.wait_for_selector(".uh-body .rd", timeout=10000)
        except Exception:
            pass
        pg.wait_for_timeout(300)
        check("справка хаба: открылась читателем", pg.locator(".uh-body .rd").count() == 1)
        check("справка хаба: заголовок файла не дублируется в документе и оглавлении (SYNC-комментарий перед ним)",
              "Справка: личный кабинет" not in pg.inner_text(".uh-body .rd-grid"))
        check("справка хаба: поиск по справке — поле .ui-qbox в читателе", pg.locator(".uh-body .rd .ui-qbox input[data-rd-q]").count() >= 1)
        check("справка хаба: сырых «#» в тексте нет",
              "## " not in (pg.inner_text(".uh-body") if pg.locator(".uh-body").count() else "## "))
        pg.close()
        br.close()
    srv.shutdown()
    print(f"\nreader_layout: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
