#!/usr/bin/env python3
"""Edit-слои HTML-экспорта Stage 3 и Stage 4 — комментарии пишутся в md.

Что закрывает:
  * Stage 3 — «Комментарий к региону» (что ещё хочется посмотреть): поле под
    карточкой региона; строки нет → создаётся сразу под заголовком региона,
    есть → правится на месте (без дублей); md после записи читается парсером
    (`Region.user_comment`), `check_format` (счётчик POI) не ломается.
  * Stage 4 — комментарии к вариантам + общий: секция `## Комментарии к
    вариантам` создаётся перед `## Решение`, повторная правка меняет строку,
    новая дописывается в секцию; парсер отдаёт `Variant.user_comment` /
    `general_comment`, гейт `decision_empty` цел.
  * Тёмная тема: статус «сохранено HH:MM» на панели записи читаем (панель
    вне `.guide`, цвет раньше наследовался от body — чёрный по тёмному).

Статичная часть (без браузера) — всегда; браузерная — НАСТОЯЩИМ chromium через
playwright против локального фейкового write-API (тот же протокол, что сайдкар
хостинга: /api/health · /api/file · /api/save с base_hash). Без playwright —
честный пропуск браузерной части.

Запуск из корня репозитория:
    python3 skills/travel-planning/tests/test_edit_layers.py
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "skills" / "travel-planning" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from export import adapter, parser, stages_html  # noqa: E402
from export.stages import stage3, stage4  # noqa: E402
import check_format  # noqa: E402

KO = REPO_ROOT / "docs" / "travel-planning" / "calibration" / "корея"
S3_MD = KO / "3_poi_aggregation_opus_t.md"
S4_MD = KO / "4_variants_v1.md"

checks_run = 0
checks_failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global checks_run, checks_failed
    checks_run += 1
    print(f"  {'✓' if cond else '✗'} {name}" + ("" if cond else f"  — {detail}"))
    if not cond:
        checks_failed += 1


def _render(sid: str, md_path: Path, out: Path, **kw) -> str:
    adapted = adapter.adapt_for_recipient(parser.parse_stage_file(md_path), "self")
    return stages_html.render_html(sid, adapted, out, source_file=md_path,
                                   embed_fonts=False, **kw)


def _decision(text: str) -> str:
    """Тело блока `## Решение` до следующего H2/EOF (фикстура уже заполнена,
    поэтому сверяем неизменность, а не пустоту гейтом decision_empty)."""
    i = text.find("\n## Решение")
    j = text.find("\n## ", i + 1)
    return text[i: j if j > 0 else len(text)].rstrip()


def _extract(mod, md_path: Path) -> dict:
    return mod.extract_content(parser.parse_stage_file(md_path))


# ---------------------------------------------------------------------------
# Статичная часть: парсеры, конфиг слоя, витрина без API
# ---------------------------------------------------------------------------

def test_static() -> None:
    print("\n[1] парсеры и статичная витрина")
    with tempfile.TemporaryDirectory() as t:
        trip = Path(t)
        # Stage 3: строка комментария к региону в шапке → парсер + статичный HTML
        src = S3_MD.read_text(encoding="utf-8")
        head = "### Пусан — 11 POI · **тег:** _____"
        src = src.replace(head, head + "\n\n**Комментарий к региону:** рынок Чагальчхи", 1)
        md3 = trip / "3_poi_pool.md"
        md3.write_text(src, encoding="utf-8")
        ex = _extract(stage3, md3)
        by = {r.name: r for r in ex["regions"]}
        check("s3: user_comment распарсен", by["Пусан"].user_comment == "рынок Чагальчхи")
        check("s3: у остальных регионов пусто", by["Кёнджу"].user_comment is None)
        check("s3: check_format poi_count не задет",
              check_format.check_poi_count(src) == [])
        doc = _render("3_poi_aggregation", md3, trip / "3_места.html")
        check("s3: якорь data-region-comment на каждый регион",
              doc.count('data-region-comment="') == len(ex["regions"]))
        check("s3: статичный текст комментария в HTML", "рынок Чагальчхи" in doc)
        check("s3: паттерн комментария региона уезжает в JS вербатим",
              json.dumps(stage3._REGION_COMMENT_RE.pattern, ensure_ascii=False)[1:-1] in doc)
        check("s3: edit-bar с цветом текста (тёмная тема)",
              "background:var(--paper);color:var(--ink);" in doc)
        # POI-комментарий в теле POI не принимается за комментарий региона
        body_only = S3_MD.read_text(encoding="utf-8").replace(
            "6. Комментарий пользователя:", "**Комментарий к региону:** чужое\n6. Комментарий пользователя:", 1)
        md3b = trip / "3_poi_pool_v2.md"
        md3b.write_text(body_only, encoding="utf-8")
        check("s3: строка внутри POI не считается комментарием региона",
              all(r.user_comment is None for r in _extract(stage3, md3b)["regions"]))

        # Stage 4: секция комментариев → варианты + общий, секция не уходит в extras
        src4 = S4_MD.read_text(encoding="utf-8").replace(
            "## Решение",
            "## Комментарии к вариантам\n\n**Вариант B:** Чеджу на 2 ночи\n"
            "- **Общий комментарий:** без ночных автобусов\n\n## Решение", 1)
        md4 = trip / "4_variants.md"
        md4.write_text(src4, encoding="utf-8")
        ex4 = _extract(stage4, md4)
        vb = [v for v in ex4["variants"] if v.letter.upper() == "B"]
        check("s4: комментарий варианта B", bool(vb) and vb[0].user_comment == "Чеджу на 2 ночи")
        check("s4: общий комментарий", ex4["general_comment"] == "без ночных автобусов")
        check("s4: секция не попала в extras",
              all("Комментари" not in e["heading"] for e in ex4["extras"]))
        check("s4: блок `## Решение` не задет", _decision(src4) == _decision(S4_MD.read_text(encoding="utf-8")))
        doc4 = _render("4_variants", md4, trip / "4_варианты.html")
        check("s4: слоты на каждый вариант + общий",
              doc4.count('data-var-comment="') == len(ex4["variants"]) + 1)
        check("s4: edit-слой включён (конфиг + /api/save)",
              "s4-edit-config" in doc4 and "/api/save" in doc4)
        check("s4: mdFile — канонический 4_variants.md", '"mdFile": "4_variants.md"' in doc4)
        check("s4: паттерн строки уезжает в JS вербатим",
              json.dumps(stage4._COMMENT_LINE_RE.pattern, ensure_ascii=False)[1:-1] in doc4)
        check("s4: статичный текст комментариев", "Чеджу на 2 ночи" in doc4
              and "без ночных автобусов" in doc4)
        doc4_pdf = _render("4_variants", md4, trip / "4_варианты.html", for_pdf=True)
        check("s4: for_pdf — слоя нет", "s4-edit-config" not in doc4_pdf)
        # polished-вход → канон рядом с выводом, версия максимальная
        (trip / "4_variants_v2.md").write_text(src4, encoding="utf-8")
        check("s4: имя md — максимальная версия",
              stages_html._stage4_md_name(trip / "x.html", trip / "polished_stage_4.md")
              == "4_variants_v2.md")


def test_legacy() -> None:
    """Обратная совместимость: артефакты БЕЗ новых полей (все калибровочные
    3_*/4_* — созданы до них) парсятся и рендерятся как раньше: комментариев
    нет, в витрине нет ни текста, ни плашек, слоты пусты (скрыты), PDF-рендер
    цел. Сверка «старый код ↔ новый» на этих же файлах дала идентичный HTML
    с точностью до пустых слотов (2026-09-25)."""
    print("\n[0] файлы без новых полей (обратная совместимость)")
    cal = REPO_ROOT / "docs" / "travel-planning" / "calibration"
    files = sorted(p for p in cal.rglob("*.md")
                   if p.name.startswith(("3_poi", "4_variants")))
    check("есть калибровочные файлы Stage 3/4", len(files) >= 4, str(len(files)))
    for md in files:
        text = md.read_text(encoding="utf-8")
        rel = md.relative_to(cal)
        check(f"{rel}: новых полей в файле нет",
              "Комментарий к региону" not in text and "Комментарии к вариантам" not in text)
        is3 = md.name.startswith("3_")
        sid = "3_poi_aggregation" if is3 else "4_variants"
        ex = _extract(stage3 if is3 else stage4, md)
        if is3:
            check(f"{rel}: user_comment регионов пуст",
                  all(r.user_comment is None for r in ex["regions"]))
        else:
            check(f"{rel}: комментарии вариантов пусты",
                  all(v.user_comment == "" for v in ex["variants"])
                  and ex["general_comment"] == "")
        with tempfile.TemporaryDirectory() as t:
            doc = _render(sid, md, Path(t) / "o.html")
            pdf = _render(sid, md, Path(t) / "p.html", for_pdf=True)
        slot = "region-comment" if is3 else "var-comment"
        n_slots = len(ex["regions"]) if is3 else len(ex["variants"]) + 1
        check(f"{rel}: витрина без текста комментариев, слоты пустые",
              'class="rc-static"' not in doc and 'class="vc-static"' not in doc
              and doc.count(f'class="{slot}"') == n_slots
              and 'sp-title">Комментарии к вариантам' not in doc,
              f"slots={doc.count(f'class={chr(34)}{slot}{chr(34)}')} ожидалось {n_slots}")
        check(f"{rel}: рендер для PDF собирается без edit-слоя",
              "edit-config" not in pdf)


# ---------------------------------------------------------------------------
# Браузерная часть: фейковый write-API + chromium
# ---------------------------------------------------------------------------

def _serve(root: Path):
    """HTTP-сервер: статика из root + фейковый write-API (протокол сайдкара)."""
    def _hash(b: bytes) -> str:
        return hashlib.sha256(b).hexdigest()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # тихо
            pass

        def _json(self, code, obj):
            b = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/api/health":
                return self._json(200, {"ok": True, "writable": True})
            if u.path == "/api/file":
                p = root / parse_qs(u.query)["path"][0]
                if not p.exists():
                    return self._json(404, {"error": "nf"})
                b = p.read_bytes()
                return self._json(200, {"content": b.decode(), "hash": _hash(b)})
            p = root / unquote(u.path).lstrip("/")
            if not p.is_file():
                self.send_response(404)
                self.end_headers()
                return
            b = p.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n))
            p = root / req["path"]
            if _hash(p.read_bytes()) != req["base_hash"]:
                return self._json(409, {"error": "conflict"})
            b = req["content"].encode()
            p.write_bytes(b)
            return self._json(200, {"hash": _hash(b)})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _luma(css_color: str, page) -> float:
    """Относительная яркость цвета через canvas (переваривает oklch/rgb)."""
    return page.evaluate("""(c) => {
      const cv = document.createElement('canvas'); cv.width = cv.height = 1;
      const x = cv.getContext('2d'); x.fillStyle = c; x.fillRect(0,0,1,1);
      const [r,g,b] = x.getImageData(0,0,1,1).data;
      return (0.2126*r + 0.7152*g + 0.0722*b) / 255;
    }""", css_color)


def _save_and_wait(page) -> str:
    page.click(".edit-bar button")
    page.wait_for_function(
        "() => /сохранено|ошибка|изменился/.test("
        "(document.querySelector('.edit-bar .edit-status')||{}).textContent||'')",
        timeout=10000)
    return page.text_content(".edit-bar .edit-status") or ""


def test_browser() -> None:
    print("\n[2] браузер: поле → «Сохранить» → md")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  ⊘ playwright не установлен — пропуск браузерной части")
        return
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        trip = root / "trip"
        trip.mkdir()
        shutil.copy(S3_MD, trip / "3_poi_pool.md")
        shutil.copy(S4_MD, trip / "4_variants.md")
        _render("3_poi_aggregation", trip / "3_poi_pool.md", trip / "s3.html")
        _render("4_variants", trip / "4_variants.md", trip / "s4.html")
        srv = _serve(root)
        base = f"http://127.0.0.1:{srv.server_address[1]}/trip/"
        try:
            with sync_playwright() as pw:
                try:
                    br = pw.chromium.launch()
                except Exception:
                    br = pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
                ctx = br.new_context()
                ctx.add_init_script("try{localStorage.setItem('hub-theme','dark')}catch(e){}")
                page = ctx.new_page()
                _stage3_flow(page, base, trip)
                _stage4_flow(page, base, trip)
                br.close()
        finally:
            srv.shutdown()


def _stage3_flow(page, base: str, trip: Path) -> None:
    md = trip / "3_poi_pool.md"
    page.goto(base + "s3.html")
    sel = '.region-comment[data-region-comment="Кёнджу"] textarea'
    page.wait_for_selector(sel, timeout=10000)
    check("s3/br: поле комментария под каждым регионом",
          page.locator(".region-comment textarea").count()
          == len(_extract(stage3, md)["regions"]))
    page.fill(sel, "ещё храм Кирымса\nи рассвет")
    page.fill('.region-comment[data-region-comment="Тэгу"] textarea', "рынок Сомун")
    status = _save_and_wait(page)
    check("s3/br: статус «сохранено»", status.startswith("сохранено"), status)

    # тёмная тема: статус читаем на фоне панели
    theme = page.evaluate("document.documentElement.getAttribute('data-theme') || "
                          "document.body.getAttribute('data-theme')")
    fg = page.evaluate("getComputedStyle(document.querySelector('.edit-bar .edit-status')).color")
    bg = page.evaluate("getComputedStyle(document.querySelector('.edit-bar')).backgroundColor")
    check("s3/br: тёмная тема включена", theme == "dark", str(theme))
    check("s3/br: статус светлый на тёмной панели",
          _luma(fg, page) - _luma(bg, page) > 0.4, f"fg={fg} bg={bg}")

    text = md.read_text(encoding="utf-8")
    lines = text.split("\n")
    i = lines.index("### Кёнджу — 13 POI · **тег:** _____")
    check("s3/br: строка создана сразу под заголовком региона",
          lines[i + 1] == "" and lines[i + 2]
          == "**Комментарий к региону:** ещё храм Кирымса и рассвет", repr(lines[i:i + 3]))
    ex = {r.name: r for r in _extract(stage3, md)["regions"]}
    check("s3/br: парсер читает записанное (Кёнджу)",
          ex["Кёнджу"].user_comment == "ещё храм Кирымса и рассвет")
    check("s3/br: парсер читает записанное (Тэгу)", ex["Тэгу"].user_comment == "рынок Сомун")
    check("s3/br: POI не потерялись",
          sum(len(r.pois) for r in ex.values())
          == sum(len(r.pois) for r in _extract(stage3, S3_MD)["regions"]))
    check("s3/br: check_format poi_count цел", check_format.check_poi_count(text) == [])

    # повторная правка существующей строки — замена, не дубль; POI-коммент рядом
    page.fill('.region-comment[data-region-comment="Кёнджу"] textarea', "только Пульгукса")
    page.fill('.poi[data-poi="1"] .poi-edit textarea', "обязательно на рассвете")
    status = _save_and_wait(page)
    text = md.read_text(encoding="utf-8")
    check("s3/br: повторное сохранение", status.startswith("сохранено"), status)
    check("s3/br: строка заменена, не задвоена",
          text.count("**Комментарий к региону:**") == 2
          and "**Комментарий к региону:** только Пульгукса" in text)
    ex1 = _extract(stage3, md)
    poi1 = [p for r in ex1["regions"] for p in r.pois if p.num == 1][0]
    check("s3/br: комментарий POI сохранён рядом",
          (poi1.user_comment or "").strip() == "обязательно на рассвете")

    # перезагрузка: поле подхватывает значение из md
    page.goto(base + "s3.html")
    page.wait_for_selector(sel, timeout=10000)
    check("s3/br: после перезагрузки поле из md",
          page.input_value(sel) == "только Пульгукса")


def _stage4_flow(page, base: str, trip: Path) -> None:
    md = trip / "4_variants.md"
    page.goto(base + "s4.html")
    page.wait_for_selector(".var-comment textarea", timeout=10000)
    ex = _extract(stage4, md)
    check("s4/br: поле под каждым вариантом + общее",
          page.locator(".var-comment textarea").count() == len(ex["variants"]) + 1)
    page.fill('.var-comment[data-var-comment="A"] textarea', "Чонджу — да, но 1 ночь")
    page.fill('.var-comment[data-var-comment="*"] textarea', "без ночных автобусов")
    status = _save_and_wait(page)
    check("s4/br: статус «сохранено»", status.startswith("сохранено"), status)
    fg = page.evaluate("getComputedStyle(document.querySelector('.edit-bar .edit-status')).color")
    bg = page.evaluate("getComputedStyle(document.querySelector('.edit-bar')).backgroundColor")
    check("s4/br: статус светлый на тёмной панели",
          _luma(fg, page) - _luma(bg, page) > 0.4, f"fg={fg} bg={bg}")

    text = md.read_text(encoding="utf-8")
    check("s4/br: секция создана перед `## Решение`",
          0 <= text.find("## Комментарии к вариантам") < text.find("## Решение"))
    ex = _extract(stage4, md)
    va = [v for v in ex["variants"] if v.letter.upper() == "A"][0]
    check("s4/br: парсер читает комментарий варианта A",
          va.user_comment == "Чонджу — да, но 1 ночь")
    check("s4/br: парсер читает общий комментарий",
          ex["general_comment"] == "без ночных автобусов")
    check("s4/br: блок `## Решение` не задет",
          _decision(text) == _decision(S4_MD.read_text(encoding="utf-8")))
    check("s4/br: варианты не потерялись", len(ex["variants"]) == 3)

    page.fill('.var-comment[data-var-comment="A"] textarea', "Чонджу — 2 ночи")
    page.fill('.var-comment[data-var-comment="B"] textarea', "Чеджу — перелёт ок")
    status = _save_and_wait(page)
    text = md.read_text(encoding="utf-8")
    check("s4/br: повторное сохранение", status.startswith("сохранено"), status)
    check("s4/br: секция одна", text.count("## Комментарии к вариантам") == 1)
    check("s4/br: строка A заменена", text.count("**Вариант A:**") == 1
          and "**Вариант A:** Чонджу — 2 ночи" in text)
    ex = _extract(stage4, md)
    vb = [v for v in ex["variants"] if v.letter.upper() == "B"][0]
    check("s4/br: строка B дописана в секцию", vb.user_comment == "Чеджу — перелёт ок")
    check("s4/br: общий комментарий не задет",
          ex["general_comment"] == "без ночных автобусов")


def main() -> int:
    if not (S3_MD.exists() and S4_MD.exists()):
        print("⊘ нет калибровочных фикстур корея/ — пропуск")
        return 0
    test_legacy()
    test_static()
    test_browser()
    print(f"\nedit_layers: {checks_run} проверок, {checks_failed} провалено")
    return 1 if checks_failed else 0


if __name__ == "__main__":
    sys.exit(main())
