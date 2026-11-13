#!/usr/bin/env python3
"""Регрессионные тесты HTML-рендер-слоя экспорта (html_lib + stages_html/*).

Покрывают:
  - html_lib.md_inline: md-ссылки / голые URL / голые домены / bold-italic /
    TODO-подсветка / XML-escape (без взаимной порчи);
  - html_lib.md_block: md-таблицы → .data-table, вложенные bullet'ы (отступ),
    обёртка контента .note-item, horizontal rule;
  - build_html_document: инлайн CSS + @font-face + landscape;
  - smoke всех 7 рендереров (Stage 0–6) на фикстуре Корея: валидный HTML,
    ключевые CSS-классы дизайн-системы, без утечек repr;
  - конкретные фиксы: чип брони без дубля, узел-аэропорт убран с карты,
    локатор + лента из координат, parse_day_nums.

Запуск из корня репозитория:
    python3 skills/travel-planning/tests/test_html_export.py

HTML-слой не требует reportlab; карта Stage 6 — matplotlib (иначе пропуск).
"""
from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[3]
EXPORT_DIR = REPO_ROOT / "skills" / "travel-planning" / "scripts" / "export"
KO = REPO_ROOT / "docs" / "travel-planning" / "calibration" / "корея"

sys.path.insert(0, str(EXPORT_DIR.parent))
from export import parser, adapter, html_lib, stages_html  # noqa: E402
from export import export as cli                        # noqa: E402
from export.stages import (                              # noqa: E402
    stage0, stage1, stage2, stage3, stage4, stage5)
from export.stages_html import (                         # noqa: E402
    stage0 as h0, stage1 as h1, stage2 as h2, stage3 as h3,
    stage4 as h4, stage5 as h5, stage6 as h6)

try:
    from export.stages import stage6
    MPL = stage6.MATPLOTLIB_AVAILABLE
except Exception:
    MPL = False

checks_run = 0
checks_failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global checks_run, checks_failed
    checks_run += 1
    if condition:
        print(f"  ✓ {name}")
    else:
        checks_failed += 1
        print(f"  ✗ {name}" + (f"  — {detail}" if detail else ""))


def skip(name: str, reason: str) -> None:
    print(f"  ⊘ {name} (skip: {reason})")


def _extract(stage_mod, md: Path, recipient="self"):
    return stage_mod.extract_content(
        adapter.adapt_for_recipient(parser.parse_stage_file(md), recipient))


def _render(html_mod, extracted, **kw) -> str:
    with tempfile.TemporaryDirectory() as t:
        return html_mod.build_html(extracted, Path(t) / "o.html",
                                   embed_fonts=False, **kw)


# ─── 1. md_inline ────────────────────────────────────────────────────────────

def test_md_inline():
    print("\n[1] html_lib.md_inline")
    mi = html_lib.md_inline
    check("md-ссылка [t](url)",
          '<a class="lnk" href="https://x.com">t</a>' in mi("[t](https://x.com)"))
    check("голый URL http://",
          'href="http://forum.awd.ru/x"' in mi("см http://forum.awd.ru/x"))
    check("голый домен srail.or.kr → ссылка",
          'href="https://srail.or.kr"' in mi("брони на srail.or.kr"))
    check("домен co.kr (kobus.co.kr)",
          'href="https://kobus.co.kr"' in mi("kobus.co.kr"))
    check("«8.4/10» НЕ линкуется", "href" not in mi("рейтинг 8.4/10"))
    # Регресс 2026-09-03: destination обязан был начинаться с http(s)://, и
    # сводная таблица «Регионы маршрута» стадии 5 печатала свои внутренние
    # ссылки сырым текстом — «[Ханой](#region-1)» прямо в ячейке.
    check("внутренний якорь #region-N — ссылка",
          '<a class="lnk" href="#region-1">Ханой</a>' in mi("[Ханой](#region-1)"))
    check("внутренний якорь #dayN — ссылка",
          'href="#day3"' in mi("[3](#day3)") and 'href="#day5"' in mi("[3](#day3)–[5](#day5)"))
    check("голый «#» без имени якоря НЕ линкуется", "href" not in mi("[бра](#) пусто"))
    check("индекс массива a[0](x) не линкуется", "href" not in mi("массив a[0](x)"))
    check("bold", "<b>жирн</b>" in mi("**жирн**"))
    check("italic", "<em>кур</em>" in mi("*кур*"))
    check("TODO-подсветка", '<span class="todo">' in mi("TODO: сверить"))
    check("XML-escape", "&lt;b&gt;" in mi("\\<b\\>".replace("\\", "")) or "&lt;" in mi("<тег>"))
    check("ссылка не рвётся TODO/bold",
          '<a class="lnk" href="https://b.com/x">b.com</a>'.replace("https://b.com/x", "https://b.com/x")
          and 'href="https://b.com/x"' in mi("TODO: глянь [b.com](https://b.com/x)"))


# ─── 2. md_block ─────────────────────────────────────────────────────────────

def test_md_block():
    print("\n[2] html_lib.md_block")
    mb = html_lib.md_block
    tbl = mb("| A | B |\n|---|---|\n| 1 | 2 |")
    check("таблица → .data-table", '<table class="data-table' in tbl and "<th>A</th>" in tbl)
    nested = mb("- верх\n  - под")
    check("вложенный bullet — отступ margin-left", "margin-left:1.4em" in nested)
    check("верхний bullet — без отступа", nested.count("margin-left") == 1)
    wrapped = mb("- **K-ETA** Россия не входит ([src](https://k.kr))")
    check("note-item оборачивает контент в <div>",
          '<div class="note-item"><div>' in wrapped)
    check("horizontal rule «---» → <hr>", "<hr" in mb("текст\n\n---\n\nещё"))


# ─── 3. build_html_document ──────────────────────────────────────────────────

def test_document():
    print("\n[3] build_html_document")
    doc = html_lib.build_html_document("<p>hi</p>", title="t", embed_fonts=False)
    check("DOCTYPE + body", doc.startswith("<!DOCTYPE html>") and "<p>hi</p>" in doc)
    check("инлайн @font-face IBM Plex", "@font-face" in doc and "IBM Plex Sans" in doc)
    check("дизайн-токены :root", ":root{" in doc)
    check("компоненты .scard", ".scard{" in doc)
    land = html_lib.build_html_document("x", landscape=True, embed_fonts=False)
    check("landscape → A4 landscape", "size:A4 landscape" in land)
    check("portrait по умолчанию — без landscape",
          "size:A4 landscape" not in doc)
    check("batch2 §1.3: break-inside:avoid для карточек в @media print",
          ".scard,.poi,.opt-card,.day,.note-item{" in doc
          and "break-inside:avoid" in doc)


def _strip_media_blocks(css: str) -> str:
    """Убрать все @media-блоки (со вложенными фигурными скобками) — остаётся
    только то, что действует безусловно, в любом медиа."""
    out, i = [], 0
    while i < len(css):
        at = css.find("@media", i)
        if at < 0:
            out.append(css[i:])
            break
        out.append(css[i:at])
        j = css.find("{", at)
        depth = 0
        while j < len(css):
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        i = j + 1
    return "".join(out)


def test_print_page_geometry():
    """Регрессия 2026-09-03: PDF срезал 12% справа.

    `.page` в дизайн-CSS — width:794px (ровно A4 при 96dpi) + padding:--pad с
    двух сторон. box-sizing:border-box стоял ТОЛЬКО под @media screen (с
    пометкой «печать — ровно A4, не затронута»), а про padding забыли: в печати
    действовал content-box, внешняя ширина листа = 794 + 2*48 = 890px против
    793.7px листа A4. `@page{margin:0}` поглотить перекос нечем — HTML→PDF молча
    срезал правый край: полосу дат обложки, правые колонки таблиц, край карты.
    Дефект был во всех стадиях и во всех движках (chromium/weasyprint/wkhtmltopdf),
    потому что живёт в CSS, а не в конвертере. Здесь же проверяется главное
    следствие: экранное превью и PDF обязаны совпадать 1:1."""
    print("\n[3b] печатная геометрия листа (A4 = width + padding)")
    MM_PX = 96 / 25.4                       # CSS-px на миллиметр при 96dpi
    a4_w, a4_h = 210 * MM_PX, 297 * MM_PX   # 793.7 x 1122.5

    doc = html_lib.build_html_document("<p>x</p>", embed_fonts=False)
    unconditional = _strip_media_blocks(doc)
    check("box-sizing:border-box для .page действует вне @media",
          ".page{box-sizing:border-box;}" in unconditional)
    check("экранное правило больше не дублирует box-sizing",
          "box-sizing:border-box;width:min(794px,100%)" not in doc)

    tokens = (html_lib._ASSETS / "design-tokens.css").read_text(encoding="utf-8")
    comps = (html_lib._ASSETS / "design-components.css").read_text(encoding="utf-8")
    pad = int(re.search(r"--pad:(\d+)px", tokens).group(1))
    width = int(re.search(r"\.page\{[^}]*?width:(\d+)px", comps, re.S).group(1))

    check(f"ширина листа .page = A4 ({width}px ≈ {a4_w:.1f}px)",
          abs(width - a4_w) <= 1, f"width={width}, A4={a4_w:.1f}")
    check("border-box: лист с padding помещается в A4",
          width <= a4_w + 1, f"внешняя ширина={width}px, A4={a4_w:.1f}px")
    check(f"content-box дал бы перекос ~{2 * pad}px — ровно исходный дефект",
          width + 2 * pad > a4_w + 50,
          f"content-box={width + 2 * pad}px против A4 {a4_w:.1f}px")

    land = html_lib.build_html_document("x", landscape=True, embed_fonts=False)
    lw = int(re.search(r"\.page\{width:(\d+)px;\}", land).group(1))
    check(f"landscape: {lw}px помещается в A4 landscape ({a4_h:.1f}px)",
          lw <= a4_h + 1, f"width={lw}, A4-land={a4_h:.1f}")


# ─── 4. smoke рендереров 0–6 ─────────────────────────────────────────────────

def test_renderers():
    print("\n[4] smoke Stage 0–6 (фикстура Корея)")
    cases = [
        ("Stage 0", KO / "0_scope_opus.md", stage0, h0,
         ['<div class="scard"', "cover-kicker", "scard-grid", 'class="section-plate"'], {}),
        ("Stage 1", KO / "1_dr_reports.md", stage1, h1,
         ['<div class="scard"', 'class="kv"', "База отчётов"], {}),
        ("Stage 3", KO / "3_poi_aggregation_opus_t.md", stage3, h3,
         ['class="region-bar"', '<div class="poi"', "region-tag"], {}),
        ("Stage 4", KO / "4_variants_v1.md", stage4, h4,
         ['class="opt-card', "opt-letter", "data-table"], {}),
        ("Stage 5", KO / "5_final_plan_v1_1.md", stage5, h5,
         ['class="day', "statband", "cover-kicker"], {}),
    ]
    for label, md, smod, hmod, must, kw in cases:
        if not md.exists():
            skip(label, f"нет {md.name}")
            continue
        try:
            doc = _render(hmod, _extract(smod, md), **kw)
        except Exception as e:  # noqa: BLE001
            check(f"{label}: рендер без исключения", False, str(e))
            continue
        check(f"{label}: валидный HTML-документ", doc.startswith("<!DOCTYPE html>"))
        for cls in must:
            check(f"{label}: есть {cls}", cls in doc)
        check(f"{label}: нет утечки repr (объект(…))",
              "object at 0x" not in doc and "Cluster(" not in doc)

    # Stage 2 — extract_content возвращает объект (не dict)
    s2 = KO / "2_similarity.md"
    if s2.exists():
        ex = stage2.extract_content(adapter.adapt_for_recipient(parser.parse_stage_file(s2), "self"))
        doc = _render(h2, ex)
        for cls in ['class="score-big"', 'class="comp"', "meter-fill", "sig--strong"]:
            check(f"Stage 2: есть {cls}", cls in doc)
    else:
        skip("Stage 2", "нет 2_similarity.md")


# ─── 5. Stage 6 + конкретные фиксы ───────────────────────────────────────────

def test_stage6_and_fixes():
    print("\n[5] Stage 6 + фиксы (карта / бронь / локатор / лента)")
    s6, s5p = KO / "6_final_v1.md", KO / "5_final_plan_v1_1.md"
    if not (s6.exists() and s5p.exists()):
        skip("Stage 6", "нет фикстур 6_final/5_final")
        return
    with tempfile.TemporaryDirectory() as t:
        doc = h6.build_html(parser.parse_stage_file(s6), Path(t) / "o.html",
                            source_file=s5p, embed_fonts=False)
    check("Stage 6: дорожное досье", "Дорожное досье" in doc)
    check("Stage 6: локатор «вы здесь»", 'class="locator"' in doc and "loc-badge" in doc)
    check("Stage 6: лента баз", 'class="ribbon"' in doc and "ribbon-name" in doc)
    check("Stage 6: статбенд «Базы»", "Базы" in doc)
    # чип брони — один на день со сменой локации (День 3 = Сокчо)
    seg = doc[doc.find("Переезд Сеул"):]
    seg = seg[:seg.find("День 4")] if "День 4" in seg else seg[:1500]
    check("чип брони без дубля в новой локации", seg.count("бронь:") <= 1,
          f"got {seg.count('бронь:')}")
    if MPL:
        check("Stage 6: карта встроена (base64 PNG)", "data:image/png;base64," in doc)
    else:
        skip("карта Stage 6", "matplotlib не установлен")

    # _strip_airport_route убирает Инчхон из маршрута карты
    body = next((s["body"] for s in parser.parse_stage_file(s6).get("sections", [])
                 if "координаты" in s.get("heading", "").lower()), "")
    if body:
        ex5 = stage5.extract_content(adapter.adapt_for_recipient(parser.parse_stage_file(s5p), "self"))
        spec = stage6.build_route_spec(body, title="t",
                                       region_groups=stage5.group_regions(ex5["days"]))
        stripped = stage6._strip_airport_route(spec)
        names = [spec["nodes"][i][2] for i in stripped["route"]]
        check("карта без узла-аэропорта (Инчхон)",
              not any("нчхон" in str(n) for n in names), str(names))


# ─── 6. parse_day_nums ───────────────────────────────────────────────────────

def test_parse_day_nums():
    print("\n[6] stage5 HTML parse_day_nums (базы локатора)")
    f = h5.parse_day_nums
    check("«дни 1-2, 16-18» → диапазоны", f("дни 1-2, 16-18") == {1, 2, 16, 17, 18})
    check("«дни 3-5»", f("дни 3-5") == {3, 4, 5})
    check("пусто → пустое множество", f("") == set())


# ─── 7. Диспетчер stages_html ────────────────────────────────────────────────

def test_dispatcher():
    print("\n[7] stages_html.render_html / normalize_stage_id / has_builder")
    n = stages_html.normalize_stage_id
    check("normalize «5_final_plan»", n("5_final_plan") == "5_final_plan")
    check("normalize alias «5_stage» → 5_final_plan", n("5_stage") == "5_final_plan")
    check("normalize цифра «0» → 0_scope", n("0") == "0_scope")
    check("normalize «6_final»", n("6_final") == "6_final")
    check("normalize None → None", n(None) is None)
    check("has_builder 0_scope/6_final", stages_html.has_builder("0_scope")
          and stages_html.has_builder("6_final"))
    check("has_builder неизвестной → False", not stages_html.has_builder("9_zzz"))

    md = KO / "5_final_plan_v1_1.md"
    if md.exists():
        a = adapter.adapt_for_recipient(parser.parse_stage_file(md), "self")
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "o.html"
            doc = stages_html.render_html("5_final_plan", a, out,
                                          recipient="self", embed_fonts=False)
            check("render_html пишет файл + возвращает HTML",
                  out.exists() and doc.startswith("<!DOCTYPE html>"))
        try:
            stages_html.render_html("9_zzz", a, "/dev/null")
            check("render_html неизвестной стадии → KeyError", False)
        except KeyError:
            check("render_html неизвестной стадии → KeyError", True)
    else:
        skip("render_html stage5", "нет 5_final_plan_v1_1.md")


# ─── 8. CLI-маршрутизация (export.main) ───────────────────────────────────────

def _run_cli(argv: list[str]) -> tuple[int, dict]:
    """Прогнать export.main, вернуть (код, распарсенный JSON из stdout)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), \
            contextlib.redirect_stderr(io.StringIO()):
        rc = cli.main(argv)
    out = buf.getvalue().strip()
    return rc, (json.loads(out) if out else {})


def test_cli_routing():
    print("\n[8] CLI: --engine html (default) → HTML / HTML→PDF handoff")
    md = KO / "5_final_plan_v1_1.md"
    if not md.exists():
        skip("CLI routing", "нет 5_final_plan_v1_1.md")
        return
    with tempfile.TemporaryDirectory() as t:
        # --format html → .html написан, RenderRequest(format=html).
        rc, out = _run_cli(["--stage", "5", "--input", str(md),
                            "--trip", "корея", "--output-dir", t,
                            "--format", "html"])
        check("html: exit 0", rc == 0)
        check("html: format=html", out.get("format") == "html")
        hp = out.get("output_path", "")
        check("html: файл .html написан", hp.endswith(".html") and Path(hp).exists())

        html_export_path = Path(hp)
        html_export_bytes = html_export_path.read_bytes()

        # --format pdf (дефолтный engine html) → HTML→PDF handoff.
        rc, out = _run_cli(["--stage", "5", "--input", str(md),
                            "--trip", "корея", "--output-dir", t,
                            "--format", "pdf"])
        check("pdf: exit 0", rc == 0)
        check("pdf: format=pdf", out.get("format") == "pdf")
        check("pdf: engine html→pdf", out["content"].get("engine") == "html→pdf")
        side = out["content"].get("html_source", "")
        # Batch 2 (коллизия имён): сайдкар — {stem}_print.html, НЕ имя
        # HTML-экспорта; PDF-прогон не затирает html-файл экспорта.
        check("pdf: сайдкар именован *_print.html", side.endswith("_print.html"))
        check("pdf: сайдкар ≠ HTML-экспорт (нет коллизии имён)",
              Path(side) != html_export_path)
        check("pdf: HTML-экспорт не затёрт PDF-прогоном",
              html_export_path.exists()
              and html_export_path.read_bytes() == html_export_bytes)
        # Без движка локальная конвертация неуспешна, есть handoff-нота.
        if not html_lib.pdf_engine_available():
            check("pdf: local_conversion=false без движка",
                  out["content"].get("local_conversion") is False)
            check("pdf: handoff-нота про core pdf skill",
                  any("core `pdf` skill" in nt for nt in out.get("notes", [])))
            check("pdf: сайдкар оставлен для handoff-конвертации",
                  Path(side).exists())
        else:
            check("pdf: local_conversion=true при доступном движке",
                  out["content"].get("local_conversion") is True
                  and out["content"].get("pdf_engine") in ("chromium", "weasyprint", "wkhtmltopdf"))
            check("pdf: сайдкар удалён после успешной локальной конвертации",
                  not Path(side).exists())


# ─── 9. Правки по обратной связи (русификация / лэйаут / ссылки) ─────────────

def test_ru_anglicisms():
    print("\n[9] html_lib.ru_anglicisms — русификация видимых англицизмов")
    r = html_lib.ru_anglicisms
    check("on_target → в рамках бюджета", r("статус on_target") == "статус в рамках бюджета")
    check("vs target → к плану", "к плану" in r("итог vs target ₽257,000"))
    check("In-trip → В поездке", r("In-trip итого") == "В поездке итого")
    check("all-in → всё включено", "всё включено" in r("Всего all-in"))
    check("cost rank → ранг стоимости", "ранг стоимости" in r("Cost rank: $$"))
    check("Variant → Вариант", r("Variant B") == "Вариант B")
    check("open-jaw НЕ переводится (авиатермин)", "open-jaw" in r("маршрут open-jaw"))
    check("multi_region_tour → мульти-регион-тур",
          r("multi_region_tour") == "мульти-регион-тур")
    check("under_budget → ниже бюджета", r("under_budget") == "ниже бюджета")
    check("пустой/без токенов не трогается",
          r("") == "" and r("обычный текст 8.4/10") == "обычный текст 8.4/10")
    # Фаза 2a.4: проза warnings Stage 2 (живой Китай).
    check("Reading list → Список для чтения (регистр начала фразы сохранён)",
          r("Reading list при этом широкий") == "Список для чтения при этом широкий")
    check("reading list в середине фразы — строчной",
          r("широкий reading list") == "широкий список для чтения")
    check("score → балл", "балл" in r("получил score ниже HIGH"))
    check("HIGH-когорта не трогается (таксон с легендой RU=EN)",
          "HIGH-когорта" in r("узкая HIGH-когорта"))

    # Словарь доходит до пользователя только если рендерер его зовёт: до
    # Фазы 2a.4 проза Stage 2 шла мимо (ru() был лишь в баннере, Р11).
    ht_stage2 = (EXPORT_DIR / "stages_html" / "stage2.py").read_text(encoding="utf-8")
    rl_stage2 = (EXPORT_DIR / "stages" / "stage2.py").read_text(encoding="utf-8")
    check("HT/stage2 русифицирует контекст и warnings",
          "md(ru(ex.context))" in ht_stage2 and "md(ru(str(w)))" in ht_stage2)
    check("RL/stage2 русифицирует контекст и warnings (Р7 — та же политика)",
          "_ru(content.context)" in rl_stage2 and "_ru(w) for w in warns" in rl_stage2)


def test_feedback_layout():
    print("\n[10] лэйаут/ссылки по обратной связи (Stage 0/1/2/3/5)")

    # Stage 0: нет «Формат»/multi_region_tour, контекст в .lead, плотность пуста → нет бейджа
    s0 = KO / "0_scope_opus.md"
    if s0.exists():
        d0 = _render(h0, _extract(stage0, s0))
        check("Stage 0: multi_region_tour убран", "multi_region_tour" not in d0)
        check("Stage 0: контекст в .lead", 'class="lead"' in d0)
        check("Stage 0: «Найдено вне выборки» — sub-плашка (не filled-стена)",
              "Найдено вне выборки" in d0
              and '<div class="section-plate"><span class="sp-title">Найдено' not in d0)
        check("Stage 0: пустая density → пустой бейдж", h0._density("") == "" and h0._density(None) == "")
    else:
        skip("Stage 0 feedback", "нет 0_scope_opus.md")

    # Stage 1: format-зависимая ориентация — HTML портрет+cols-1, PDF landscape+2col
    s1 = KO / "1_dr_reports.md"
    if s1.exists():
        ex1 = _extract(stage1, s1)
        d_html = _render(h1, ex1)                       # default landscape=False
        d_pdf = _render(h1, ex1, landscape=True)
        check("Stage 1 HTML: портрет (без landscape)", "size:A4 landscape" not in d_html)
        check("Stage 1 HTML: cols-1 (полная ширина)", "scard-grid cols-1" in d_html)
        check("Stage 1 PDF: landscape", "size:A4 landscape" in d_pdf)
        check("Stage 1 PDF: 2-колоночный грид (без cols-1)",
              "scard-grid cols-1" not in d_pdf
              and _re.search(r'class="scard-grid"[ >]', d_pdf.split("</style>", 1)[-1]) is not None)
        # Batch 2 §2.1: обложка не хардкод, реальный титул + паспорт-таблица.
        check("Stage 1: обложка не хардкод «Источники для маршрута»",
              "Источники для маршрута" not in d_html)
        check("Stage 1: паспорт-таблица на обложке (.passport-row)",
              '<div class="passport-row">' in d_html)
    else:
        skip("Stage 1 feedback", "нет 1_dr_reports.md")

    # Stage 2: cols-1 + якоря карточек + ссылки из таблицы «Все авторы»
    s2 = KO / "2_similarity.md"
    if s2.exists():
        ex = stage2.extract_content(adapter.adapt_for_recipient(parser.parse_stage_file(s2), "self"))
        d2 = _render(h2, ex)
        check("Stage 2: scard-grid cols-1", "scard-grid cols-1" in d2)
        check("Stage 2: «Все авторы» — sub-плашка (не filled-стена)",
              "Все авторы" in d2
              and '<div class="section-plate"><span class="sp-title">Все авторы' not in d2)
        check("Stage 2: якорь карточки id=author-0", 'id="author-0"' in d2)
        check("Stage 2: ссылка из таблицы на карточку", 'href="#author-' in d2)
    else:
        skip("Stage 2 feedback", "нет 2_similarity.md")

    # Stage 3: Google Images ссылки на POI (паритет с DOCX)
    s3 = KO / "3_poi_aggregation_opus_t.md"
    if s3.exists():
        d3 = _render(h3, _extract(stage3, s3))
        check("Stage 3: poi-images Google ссылки", "poi-images" in d3 and "tbm=isch" in d3)
    else:
        skip("Stage 3 feedback", "нет 3_poi_aggregation_opus_t.md")

    # Stage 5: русификация бюджет-таблицы в рендере
    s5f = KO / "5_final_plan_v1_1.md"
    if s5f.exists():
        d5 = _render(h5, _extract(stage5, s5f))
        check("Stage 5: on_target/vs target/In-trip русифицированы",
              "on_target" not in d5 and "vs target" not in d5 and "In-trip" not in d5)
    else:
        skip("Stage 5 feedback", "нет 5_final_plan_v1_1.md")


def test_i18n_2c():
    """i18n Фаза 2c: tempo из taxonomy, флаги POI, warnings через русификатор."""
    print("\n[10b] i18n 2c: tempo/flag_badge/scarce-abundant")
    from export import cover_common as cc
    check("_TEMPO_RU построен из taxonomy (алиас moderate)",
          cc._TEMPO_RU.get("moderate") == "сбалансированный", str(cc._TEMPO_RU))
    check("localize_tempo: balanced (…) → сбалансированный (…)",
          cc.localize_tempo("balanced (3.6 ночи/база)") == "сбалансированный (3.6 ночи/база)")

    ru = html_lib.ru_anglicisms
    check("scarce-режим → скудный режим (без дефиса)",
          ru("scarce-режим: мало HIGH") == "скудный режим: мало HIGH")
    check("abundant → обильный", ru("abundant покрытие") == "обильный покрытие")

    # HT stage1: iconic-бейдж русский, не сырой EN.
    card = SimpleNamespace(is_critical=False, focus_tag=None,
                           flags={"iconic"}, fields={})
    b = h1._badges(card)
    check("HT stage1: iconic-флаг → «знаковый»", "знаковый" in b and ">iconic<" not in b, b)

    # HT stage3 на фикстуре Кореи: сырых EN-префиксов флагов нет.
    s3f = KO / "3_poi_aggregation_opus_t.md"
    if s3f.exists():
        d3 = _render(h3, _extract(stage3, s3f))
        check("Stage 3: нет сырых `iconic:`/`tourist-trap:` префиксов",
              ">iconic: " not in d3 and "tourist-trap: " not in d3)
    else:
        skip("Stage 3 флаги 2c", "нет 3_poi_aggregation_opus_t.md")


import re as _re


def test_plate_anno_helpers():
    print("\n[11] html_lib.plate / anno (P0-3/P0-4)")
    p = html_lib.plate
    check("filled — без --sub", p("Тест") == '<div class="section-plate"><span class="sp-title">Тест</span></div>')
    check("sub — ВСЕГДА с базовым классом (P0-3)",
          'class="section-plate section-plate--sub"' in p("Г", sub=True))
    check("§ SN / sp-no убраны полностью", "sp-no" not in p("Т") and "§" not in p("Т"))
    check("anno mono-разделитель", html_lib.anno("Тема") == '<div class="anno">Тема</div>')
    check("anno first — без верхнего отступа", 'class="anno first"' in html_lib.anno("Т", first=True))


def test_design_review_fixes():
    print("\n[12] правки дизайн-ревью Claude Design (P0–P2)")
    KOf = {"0_scope": "0_scope_opus.md", "1_dr_reports": "1_dr_reports.md",
           "2_similarity": "2_similarity.md", "3_poi_aggregation": "3_poi_aggregation_opus_t.md",
           "4_variants": "4_variants_v1.md", "5_final_plan": "5_final_plan_v1_1.md",
           "6_final": "6_final_v1.md"}
    docs = {}
    for sid, fn in KOf.items():
        md = KO / fn
        if not md.exists():
            continue
        kw = {"source_file": str(KO / "5_final_plan_v1_1.md")} if sid == "6_final" else {}
        with tempfile.TemporaryDirectory() as t:
            p = parser.parse_stage_file(md)
            a = adapter.adapt_for_recipient(p, "self")
            docs[sid] = stages_html.render_html(sid, a, Path(t) / "o.html",
                                                embed_fonts=False, **kw)

    def filled(doc):  # filled = section-plate без --sub
        return len(_re.findall(r'class="section-plate"(?!\s*section-plate--sub)', doc))

    # P0-1: ровно 1 filled-плашка на стадию
    for sid, doc in docs.items():
        check(f"P0-1 {sid}: ровно 1 filled-плашка", filled(doc) == 1, f"got {filled(doc)}")
    # P0-2: s3 — заголовки регионов только .region-bar (≥1), не дублируются section-plate
    if "3_poi_aggregation" in docs:
        d3 = docs["3_poi_aggregation"]
        check("P0-2 s3: region-bar присутствует, дублей плашек региона нет",
              d3.count("region-bar") >= 2 and filled(d3) == 1)
    # P0-4: § SN / sp-no убраны во всех стадиях + anno в s6
    check("P0-4: § SN / sp-no отсутствуют во всех стадиях",
          all("sp-no" not in d and "§ S" not in d for d in docs.values()))
    if "6_final" in docs:
        check("P0-4: anno-разделители в s6", 'class="anno' in docs["6_final"])
    # P1-1: s2 RU-короткая форма лейбла метра «самост.» (taxonomy ru_short),
    # а не EN «independence»/«indep.» в самом лейбле метра (.comp-k). Свободный
    # текст (напр. строка весов «… independence 10 …») — легитимен, не проверяем.
    if "2_similarity" in docs:
        check("P1-1 s2: RU-короткий лейбл метра «самост.» (не EN independence)",
              "самост." in docs["2_similarity"]
              and '<span class="comp-k">independence' not in docs["2_similarity"]
              and '<span class="comp-k">indep.' not in docs["2_similarity"])
    # P1-2: s0 портрет
    if "0_scope" in docs:
        check("P1-2 s0: портрет (нет A4 landscape)", "A4 landscape" not in docs["0_scope"])
    # P1-3 + P2-1: s5 hotel-name + move-tag--loc
    if "5_final_plan" in docs:
        d5 = docs["5_final_plan"]
        check("P1-3 s5: имя отеля в .hotel-name", 'class="hotel-name"' in d5)
        check("P2-1 s5: «Локация» — move-tag--loc (серая)", "move-tag--loc" in d5)
    # P2-2: s0 нет пустых .box (… — </div>)
    if "0_scope" in docs:
        check("P2-2 s0: нет пустых box (X — </div>)",
              not _re.search(r"—\s*</div>", docs["0_scope"]))


def test_final_polish():
    print("\n[13b] финальная полировка (§ SN убран полностью, пустые маркеры, рус-лейбл)")
    # plate: моно-индекс § SN убран — ни filled, ни sub его не рисуют.
    check("plate(filled) — без sp-no/§", "sp-no" not in html_lib.plate("Г")
          and "§" not in html_lib.plate("Г"))
    check("plate(sub=True) — без sp-no/§",
          "sp-no" not in html_lib.plate("Г", sub=True))

    def render(sid, f, **kw):
        p = parser.parse_stage_file(KO / f)
        a = adapter.adapt_for_recipient(p, "self")
        with tempfile.TemporaryDirectory() as t:
            return stages_html.render_html(sid, a, Path(t) / "o.html", embed_fonts=False, **kw)

    def body(doc):  # без CSS-правил из <style>
        return doc.split("</style>", 1)[-1]

    if (KO / "0_scope_opus.md").exists():
        b0 = body(render("0_scope", "0_scope_opus.md"))
        check("s0: § SN отсутствует в теле", "§ S" not in b0 and "sp-no" not in b0)
        check("s0: role убран из подвала карточки",
              ">supporting</span>" not in b0 and ">core</span>" not in b0)
        check("s0: filled-плашка стадии на месте (без § SN)",
              'class="section-plate"' in b0)
    # Stage 1 format-зависимая ориентация через диспетчер (for_pdf).
    if (KO / "1_dr_reports.md").exists():
        check("render_html s1 for_pdf=False → портрет",
              "A4 landscape" not in render("1_dr_reports", "1_dr_reports.md", for_pdf=False))
        check("render_html s1 for_pdf=True → landscape",
              "A4 landscape" in render("1_dr_reports", "1_dr_reports.md", for_pdf=True))

    if (KO / "3_poi_aggregation_opus_t.md").exists():
        d3 = render("3_poi_aggregation", "3_poi_aggregation_opus_t.md")
        check("s3: рус-лейбл «Находки вне турпотока»",
              "Находки вне турпотока" in d3 and "Non-mainstream" not in d3)
    if (KO / "5_final_plan_v1_1.md").exists():
        d5 = render("5_final_plan", "5_final_plan_v1_1.md")
        b5 = body(d5)
        check("s5: prog-item без колонки времени (маркер по левому краю)",
              '<div class="prog-time"></div>' not in b5
              and '<div class="prog-item"><span class="prog-mark' in b5)
        check("s5: пустой warn «⚠️ —» не рисуется",
              not _re.search(r'box--warn"><span class="box-mark"></span><div>\s*—?\s*</div>', b5))


def test_pdf_engines():
    print("\n[14] html_lib HTML→PDF: мультидвижковый детектор")
    eng = html_lib.pdf_engine_available()
    check("pdf_engine_available → имя движка или None",
          eng is None or eng in ("chromium", "weasyprint", "wkhtmltopdf"))
    if eng is None:
        # Без движка html_to_pdf падает с понятным сообщением про core pdf skill.
        try:
            html_lib.html_to_pdf("<html><body>x</body></html>",
                                 Path(tempfile.gettempdir()) / "nope.pdf")
            check("html_to_pdf без движка → RuntimeError", False)
        except RuntimeError as e:
            check("html_to_pdf без движка → RuntimeError + core pdf skill",
                  "core `pdf` skill" in str(e))
    else:
        skip("html_to_pdf error-path", f"движок доступен ({eng})")


def test_pdf_degradation():
    print("\n[14b] html_to_pdf: деградация по цепочке (упавший движок → следующий)")
    import subprocess as _sp
    orig = {k: getattr(html_lib, k) for k in
            ("_find_chromium", "_run_chromium", "_have_weasyprint",
             "_run_weasyprint", "_find_wkhtmltopdf")}
    try:
        html_lib._find_chromium = lambda: "/fake/chromium"

        def _boom(*a, **k):
            raise _sp.CalledProcessError(1, "chromium", stderr=b"chromium crashed X")
        html_lib._run_chromium = _boom
        html_lib._have_weasyprint = lambda: False
        html_lib._find_wkhtmltopdf = lambda: None
        try:
            html_lib.html_to_pdf("<html></html>", Path(tempfile.gettempdir()) / "x.pdf")
            check("упавший chromium без запасных → RuntimeError", False)
        except RuntimeError as e:
            check("упавший движок → RuntimeError со stderr в хвосте",
                  "chromium crashed X" in str(e) and "упавшие движки" in str(e))

        # chromium падает, но weasyprint успешен → fall-through возвращает путь.
        called = {"wp": False}
        html_lib._have_weasyprint = lambda: True

        def _wp_ok(html_str, out):
            called["wp"] = True
            Path(out).write_text("pdf", encoding="utf-8")
        html_lib._run_weasyprint = _wp_ok
        with tempfile.TemporaryDirectory() as t:
            out = html_lib.html_to_pdf("<html></html>", Path(t) / "y.pdf")
            check("упавший chromium → weasyprint (fall-through)",
                  called["wp"] and Path(out).exists())
    finally:
        for k, v in orig.items():
            setattr(html_lib, k, v)


def test_wkhtmltopdf_opt_in():
    """Batch 2 §1.1: wkhtmltopdf вне авто-цепочки, включается только явным
    env TRAVEL_PDF_ENGINE=wkhtmltopdf. §1.2: landscape-CSS → --orientation
    Landscape (CLI wkhtmltopdf не читает @page{landscape})."""
    print("\n[14c] wkhtmltopdf: явный опт-ин + orientation-патч")
    import os as _os
    orig = {k: getattr(html_lib, k) for k in
            ("_find_chromium", "_have_weasyprint", "_find_wkhtmltopdf")}
    orig_env = _os.environ.get("TRAVEL_PDF_ENGINE")
    try:
        html_lib._find_chromium = lambda: None
        html_lib._have_weasyprint = lambda: False
        html_lib._find_wkhtmltopdf = lambda: "/fake/wkhtmltopdf"
        _os.environ.pop("TRAVEL_PDF_ENGINE", None)

        check("без опт-ина: pdf_engine_available → None (wkhtmltopdf не в авто-цепочке)",
              html_lib.pdf_engine_available() is None)
        try:
            html_lib.html_to_pdf("<html></html>", Path(tempfile.gettempdir()) / "z.pdf")
            check("без опт-ина: html_to_pdf → RuntimeError (handoff)", False)
        except RuntimeError as e:
            check("без опт-ина: html_to_pdf → RuntimeError (handoff)",
                  "core `pdf` skill" in str(e))

        _os.environ["TRAVEL_PDF_ENGINE"] = "wkhtmltopdf"
        check("с опт-ином: pdf_engine_available → wkhtmltopdf",
              html_lib.pdf_engine_available() == "wkhtmltopdf")

        captured = {}

        def _fake_run(cmd, **kw):
            captured["cmd"] = cmd
            Path(cmd[-1]).write_text("pdf", encoding="utf-8")
            class _R:
                returncode = 0
            return _R()
        orig_run = html_lib.subprocess.run
        html_lib.subprocess.run = _fake_run
        try:
            with tempfile.TemporaryDirectory() as t:
                out = Path(t) / "land.pdf"
                html_lib.html_to_pdf(
                    "<style>@page{size:A4 landscape;}</style><body>x</body>", out)
                check("landscape-CSS → --orientation Landscape в CLI",
                      "--orientation" in captured["cmd"]
                      and "Landscape" in captured["cmd"])
                out2 = Path(t) / "port.pdf"
                html_lib.html_to_pdf("<body>x</body>", out2)
                check("портрет (без landscape-CSS) → без --orientation",
                      "--orientation" not in captured["cmd"])
        finally:
            html_lib.subprocess.run = orig_run
    finally:
        for k, v in orig.items():
            setattr(html_lib, k, v)
        if orig_env is None:
            _os.environ.pop("TRAVEL_PDF_ENGINE", None)
        else:
            _os.environ["TRAVEL_PDF_ENGINE"] = orig_env


def test_summary_text_blocks():
    print("\n[13] сводные text-секции (баг «пустая ГАСТРОНОМИЯ»)")
    # Хелпер: text-блок рендерится, пустая секция не даёт голый заголовок.
    item_text = {"title": "Гастрономия", "blocks": [
        {"type": "text", "content": "**Сеул**\n- Самгетхан"}]}
    out = h5._summary_item(item_text)
    check("text-блок рендерит тело", "Самгетхан" in out and "Гастрономия" in out)
    check("пустая секция → ничего (нет голого заголовка)",
          h5._summary_item({"title": "Пусто", "blocks": []}) == ""
          and h5._summary_item({"title": "Пусто", "blocks": [
              {"type": "text", "content": "  "}]}) == "")

    # На фикстуре: Гастрономия с телом по городам в s5 и s6.
    s5f = KO / "5_final_plan_v1_1.md"
    if s5f.exists():
        d5 = _render(h5, _extract(stage5, s5f))
        check("s5: Гастрономия с телом (Тосокчон + города)",
              "Гастрономия" in d5 and "Тосокчон" in d5
              and all(c in d5 for c in ("Сокчо", "Кёнджу", "Пусан")))
        # Заголовок секции не остаётся без тела
        check("s5: нет голой плашки Гастрономия",
              "Гастрономия" not in d5
              or d5.split("Гастрономия", 1)[1].lstrip()[:200].count("Тосокчон") >= 0)
        s6f, s5src = KO / "6_final_v1.md", s5f
        if s6f.exists():
            with tempfile.TemporaryDirectory() as t:
                d6 = h6.build_html(parser.parse_stage_file(s6f), Path(t) / "o.html",
                                   source_file=s5src, embed_fonts=False)
            check("s6: Гастрономия с телом (паритет с s5)",
                  "Гастрономия" in d6 and "Тосокчон" in d6)
    else:
        skip("summary text", "нет 5_final_plan_v1_1.md")


def _is_nonempty(v) -> bool:
    return v not in (None, "", [], {}, 0, False)


def test_completeness_contract():
    print("\n[14] drift-контракт полноты (CONSUMED_KEYS)")
    VN = REPO_ROOT / "docs" / "travel-planning" / "calibration" / "вьетнам"
    cases = [
        ("0_scope", "0_scope_opus.md", stage0, h0),
        ("1_dr_reports", "1_dr_reports.md", stage1, h1),
        ("3_poi_aggregation", "3_poi_aggregation_opus_t.md", stage3, h3),
        ("4_variants", "4_variants_v1.md", stage4, h4),
        ("5_final_plan", "5_final_plan_v1_1.md", stage5, h5),
    ]
    for sid, fn, smod, hmod in cases:
        md = KO / fn
        if not md.exists():
            skip(f"{sid} contract", f"нет {fn}")
            continue
        ex = _extract(smod, md)
        consumed = getattr(hmod, "CONSUMED_KEYS", None)
        if consumed is None:
            check(f"{sid}: CONSUMED_KEYS объявлен", False)
            continue
        undeclared = {k for k, v in ex.items() if _is_nonempty(v)} - consumed
        check(f"{sid}: непустые ключи extract ⊆ CONSUMED_KEYS",
              not undeclared, f"недекларированы: {sorted(undeclared)}")

    # Section-smoke Stage 5: на фикстуре с полным набором review-секций (Вьетнам)
    # каждая непустая секция обязана дать свою плашку в HTML (защита от рецидива
    # «потери» Шапки/critical_prep/рисков/TODO/чеклиста).
    vn5 = VN / "5_final_plan.md"
    if vn5.exists():
        ex = _extract(stage5, vn5)
        doc = _render(h5, ex)
        for key, title in (("header", "Шапка"),
                           ("critical_prep", "Критические подготовительные"),
                           ("risk_plan_blocks", "План реагирования на риски"),
                           ("todo", "TODO для верификации"),
                           ("checklist_2w", "Чеклист за 2 недели")):
            if _is_nonempty(ex.get(key)):
                check(f"s5 section-smoke: непустой {key} → «{title}» в HTML",
                      title in doc)
    else:
        skip("s5 section-smoke", "нет вьетнам/5_final_plan.md")


def test_stage3_edit_layer():
    """Edit-слой Stage 3 (правки тег/комментарий через write-API хостинга):
    включается только при source_md_name (HTML-экспорт), выключен для
    HTML→PDF-прогона; JS-регэкспы — те же Python-паттерны stages/stage3
    (контракт «ноль дрейфа»: паттерн уезжает в JSON-конфиг вербатим)."""
    print("\n[15] Stage 3 edit-слой (write-API)")
    md = KO / "3_poi_aggregation_opus_t.md"
    if not md.exists():
        skip("stage3 edit-слой", "нет 3_poi_aggregation_opus_t.md")
        return
    adapted = adapter.adapt_for_recipient(parser.parse_stage_file(md), "self")
    with tempfile.TemporaryDirectory() as t:
        out = Path(t) / "o.html"
        doc = stages_html.render_html("3_poi_aggregation", adapted, out,
                                      source_file=md)
        doc_pdf = stages_html.render_html("3_poi_aggregation", adapted, out,
                                          source_file=md, for_pdf=True)
        doc_none = _render(h3, _extract(stage3, md))

    check("HTML-экспорт: конфиг-скрипт слоя", 's3-edit-config' in doc)
    check("HTML-экспорт: имя md-источника",
          '"mdFile": "3_poi_aggregation_opus_t.md"' in doc)
    check("HTML-экспорт: JS зовёт /api/save и /api/health",
          "/api/save" in doc and "/api/health" in doc)
    check("HTML-экспорт: якоря data-region + tagopt",
          'data-region="' in doc and 'class="tagopt"' in doc)
    check("HTML-экспорт: якоря data-poi", 'data-poi="' in doc)
    check("HTML-экспорт: хук .poi-comment на статичном комментарии",
          "poi-comment" in doc)
    check("HTML-экспорт: print прячет edit-ui",
          ".edit-ui,.edit-bar{display:none !important;}" in doc)
    # Контракт «ноль дрейфа»: паттерны в JSON-конфиге == паттерны парсера.
    for label, rx in (("region", stage3._REGION_HEADER_RE),
                      ("poi", stage3._POI_HEADER_RE),
                      ("comment", stage3._MD_COMMENT_LINE_RE),
                      ("tag", stage3._MD_TAG_IN_HEADER_RE)):
        embedded = json.dumps(rx.pattern, ensure_ascii=False)[1:-1]
        check(f"паттерн {label} уезжает в JS вербатим", embedded in doc)
    # Канонические теги в конфиге (та же тройка, что чекбоксы DOCX).
    check("канон тегов в конфиге",
          json.dumps(list(stage3._CANONICAL_TAGS), ensure_ascii=False) in doc)
    # Число регион-якорей == числу регионов; POI-якорей == числу POI.
    ex = _extract(stage3, md)
    check("data-region на каждый регион",
          doc.count('data-region="') == len(ex.get("regions") or []))
    n_pois = sum(len(r.pois) for r in ex.get("regions") or [])
    check("data-poi на каждый POI", doc.count('data-poi="') == n_pois)

    check("for_pdf: слоя нет",
          's3-edit-config' not in doc_pdf and "/api/save" not in doc_pdf)
    check("без source_md_name: слоя нет, якоря безвредны",
          's3-edit-config' not in doc_none and 'data-poi="' in doc_none)


def test_stage3_edit_md_name():
    """Имя md-источника в edit-слое — КАНОНИЧНОЕ `3_*.md` из директории поездки,
    а не имя входного файла экспорта.

    Каноничный flow (`references/export/export-modes.md`) рендерит из черновика
    `polished_stage_3.md`, и его имя, уехав в страницу, даёт тихий 403 write-API
    (whitelist сайдкара пускает только `trips/{id}/3_*.md`): edit-слой не
    поднимается, правки недоступны молча. Реальный случай — регион_a_2027,
    2026-07-27: экспорт нёс `"mdFile": "polished_3_poi_pool.md"`."""
    print("\n[15b] Stage 3: имя md для edit-слоя (polished ≠ канон)")
    _name = stages_html._stage3_md_name
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        out = d / "3_регион_b_2027-04_места.html"
        # 1) polished-вход + канон рядом с выводом → канон
        (d / "3_poi_pool.md").write_text("x", encoding="utf-8")
        check("polished-вход → канон из директории вывода",
              _name(out, d / "polished_3_poi_pool.md") == "3_poi_pool.md")
        # 2) каноничный вход авторитетнее (даже если лежит вне trips/)
        check("каноничный вход побеждает",
              _name(out, Path("/scratch/3_poi_pool_v4.md")) == "3_poi_pool_v4.md")
        # 3) несколько кандидатов → `3_poi_pool.md` приоритетен
        (d / "3_poi_pool_v2.md").write_text("x", encoding="utf-8")
        check("несколько кандидатов → 3_poi_pool.md",
              _name(out, d / "polished.md") == "3_poi_pool.md")
        # 4) версии без канон-имени → максимальная
        (d / "3_poi_pool.md").unlink()
        (d / "3_poi_pool_v10.md").write_text("x", encoding="utf-8")
        check("версии → максимальный _vN",
              _name(out, d / "polished.md") == "3_poi_pool_v10.md")
        # 5) лог стадии — не источник
        for p in d.glob("3_*.md"):
            p.unlink()
        (d / "3_stage_log.md").write_text("x", encoding="utf-8")
        check("3_stage_log.md не считается источником",
              _name(out, d / "polished.md") is None)
        # 6) нечего предложить → слой не включаем (лучше витрина, чем битый путь)
        (d / "3_stage_log.md").unlink()
        check("нет кандидатов → None", _name(out, d / "polished.md") is None)

    # e2e: рендер из polished-файла не должен нести имя черновика
    md = KO / "3_poi_aggregation_opus_t.md"
    if not md.exists():
        skip("stage3 polished e2e", "нет 3_poi_aggregation_opus_t.md")
        return
    adapted = adapter.adapt_for_recipient(parser.parse_stage_file(md), "self")
    with tempfile.TemporaryDirectory() as t:
        trip = Path(t)
        (trip / "3_poi_pool.md").write_text(md.read_text(encoding="utf-8"),
                                            encoding="utf-8")
        polished = trip / "polished_stage_3.md"
        polished.write_text(md.read_text(encoding="utf-8"), encoding="utf-8")
        doc = stages_html.render_html("3_poi_aggregation", adapted,
                                      trip / "3_места.html", source_file=polished)
        # без канон-файла рядом слой выключается, а не ссылается на черновик
        (trip / "3_poi_pool.md").unlink()
        doc_orphan = stages_html.render_html("3_poi_aggregation", adapted,
                                             trip / "3_места.html",
                                             source_file=polished)
    check("e2e: polished-вход → mdFile = 3_poi_pool.md",
          '"mdFile": "3_poi_pool.md"' in doc)
    check("e2e: имя черновика в страницу не уезжает",
          "polished_stage_3.md" not in doc)
    check("e2e: канон-файла рядом нет → слоя нет",
          "s3-edit-config" not in doc_orphan)
    # Диагностика вместо молчания: причина 403/404 показывается, если API живой
    check("JS различает 403 (вне whitelist) и 404 (нет файла)",
          "вне whitelist write-API" in doc and "нет «" in doc)


def test_strict_version():
    """Строгое соответствие версии входа и выхода (_resolve_version):
    версия берётся из frontmatter `iteration` (версия плана), а не из имени
    файла; при расхождении имени — предупреждение, но выход по содержимому.
    Ловит кейс «экспорт-сессия подала v5-контент в v1-именованном файле»."""
    print("\n[16] строгое соответствие версии (_resolve_version)")
    from pathlib import Path as _P
    # имя == содержимому → версия из iteration, без сюрпризов
    check("v5-имя + iteration 5 → 5",
          cli._resolve_version(_P("5_final_plan_v5.md"), {"frontmatter": {"iteration": 5}}) == 5)
    # КЛЮЧЕВОЙ кейс: имя v1, но содержимое iteration 5 → выход v5 (по содержимому)
    check("v1-имя + iteration 5 → 5 (содержимое авторитетнее имени)",
          cli._resolve_version(_P("5_final_plan_v1.md"), {"frontmatter": {"iteration": 5}}) == 5)
    # нет iteration → откат на версию из имени
    check("нет iteration → версия из имени (v3)",
          cli._resolve_version(_P("5_final_plan_v3.md"), {"frontmatter": {}}) == 3)
    # iteration нечисловой → откат на имя
    check("iteration нечисловой → откат на имя (v2)",
          cli._resolve_version(_P("4_variants_v2.md"), {"frontmatter": {"iteration": "x"}}) == 2)
    # безверсионное имя без iteration → 1
    check("безверсионное имя, нет iteration → 1",
          cli._resolve_version(_P("5_final_plan.md"), {}) == 1)


def test_nav_layer():
    """Навигационный слой TNAV (assets/nav-layer.{css,js}).

    Слой строит меню ИЗ документа по классам рендереров — поэтому главная
    проверка тут drift-гард: если рендерер переименует `.day`/`.poi`/`.scard`
    или уберёт `.section-plate`, меню молча опустеет, а тесты рендера этого
    не заметят (класс-то в HTML остался — просто другой).
    """
    print("\n[17] навигационный слой TNAV")
    css = (EXPORT_DIR / "assets" / "nav-layer.css").read_text(encoding="utf-8")
    js = (EXPORT_DIR / "assets" / "nav-layer.js").read_text(encoding="utf-8")

    doc = html_lib.build_html_document("<p>x</p>", title="t", embed_fonts=False)
    check("слой инжектится по умолчанию",
          'id="tnav-style"' in doc and 'id="tnav-script"' in doc)
    check("nav=False — документ без слоя",
          "tnav-style" not in html_lib.build_html_document(
              "<p>x</p>", embed_fonts=False, nav=False))
    check("doc_key → data-tnav-key на body",
          'data-tnav-key="регион_a_2027"' in html_lib.build_html_document(
              "x", embed_fonts=False, doc_key="регион_a_2027"))
    # проверять по тегу <body>, а не по всему документу: строка
    # "data-tnav-key" есть и в инлайн-скрипте слоя (он её читает)
    check("без doc_key тег body голый", "<body>" in doc)

    # печать: слоя нет, «[ ]» пунктов возвращается на бумагу
    check("в @media print слой скрыт целиком",
          "@media print { #tnav-root { display: none !important; } }" in css)
    check("на бумаге чекбокс скрыт, «[ ]» возвращается",
          ".tnav-box { display: none !important; }" in css
          and ".tnav-pb { display: inline !important; }" in css)

    # автономность: файл открывают офлайн и с диска
    for name, src in (("css", css), ("js", js)):
        check(f"nav-layer.{name}: ни одного внешнего адреса",
              "http://" not in src and "https://" not in src and "//cdn" not in src)
    # Сеть у слоя есть ровно одна: запись отметок подготовки в план через
    # write-API хостинга. Ни одного абсолютного адреса быть не должно —
    # страницу открывают и с диска, и с чужого домена.
    check("nav-layer.js: сеть только к своему /api",
          "XMLHttpRequest" not in js
          and all(u.startswith('"/api/') for u in __import__("re").findall(r'fetch\((\"[^\"]*)', js) or ['"/api/'])
          and '"/api/file?path=' in js and '"/api/save"' in js)

    # ── drift-гард: за что слой цепляется в разметке ──
    contract = {
        ".section-plate": "разделы", ".anno": "подсекции",
        ".day": "дни", ".day-date": "номер/дата дня", ".day-title": "заголовок дня",
        ".poi[data-poi]": "POI", ".poi-name": "имя POI", ".region-bar": "регион",
        ".opt-card": "варианты", ".scard": "карточки", ".scard-title": "имя карточки",
        ".note-item": "пункты подготовки", ".cover-kicker": "кикер обложки",
    }
    for sel, what in contract.items():
        check(f"js читает {sel} ({what})", sel in js)

    md5 = KO / "5_final_plan_v1_1.md"
    if md5.exists():
        ex5 = _extract(stage5, md5)
        doc5 = _render(h5, ex5)
        for sel in (".section-plate", "class=\"day", "note-item", "cover-kicker"):
            check(f"Stage 5 реально эмитит {sel}", sel in doc5)
        # 5 и 6 должны делить ключ: чеклист там один и тот же
        key5 = str((ex5.get("cover") or {}).get("trip_id") or "")
        check("Stage 5: data-tnav-key = trip_id", f'data-tnav-key="{key5}"' in doc5)
        # даты дней
        dates = h5.iso_dates(ex5)
        days_with_num = [d for d in ex5["days"] if getattr(d, "day_num", None)]
        check("iso_dates: год разрешён из trip_id, даты у всех дней",
              bool(dates) and len(dates) == len(days_with_num),
              f"{len(dates)} из {len(days_with_num)}")
        check("data-date попал в карточку дня",
              doc5.count("data-date=") == len(dates))
        if dates:
            iso = sorted(dates.values())
            check("даты монотонны и в формате ГГГГ-ММ-ДД",
                  all(len(x) == 10 and x[4] == "-" for x in iso)
                  and iso == [dates[k] for k in sorted(dates)])
    else:
        skip("Stage 5 фикстура", "нет 5_final_plan_v1_1.md")

    # год не выводится ниоткуда → атрибута нет, «Сегодня» не показывается
    class _D:
        heading = "### День 1 (28.12 Пн). Старт"
        day_num = 1
    check("нет года → iso_dates пусто (кнопка «Сегодня» просто не появится)",
          h5.iso_dates({"cover": {}, "frontmatter": {}, "days": [_D()]}) == {})
    # переход через январь
    class _D2(_D):
        heading = "### День 5 (03.01 Сб). Новый год"
        day_num = 5
    rolled = h5.iso_dates({"cover": {"trip_id": "тур_2026-12"}, "frontmatter": {},
                           "days": [_D(), _D2()]})
    check("28.12 → 03.01 переносит год",
          rolled == {1: "2026-12-28", 5: "2027-01-03"}, str(rolled))

    # 2026-10: переключателя темы нет — тема из кабинета (hub-theme), а кнопка
    # в iframe кабинета перекрашивала только документ, не страницу вокруг
    check("nav-layer.js: кнопки темы нет (ни в шторке, ни в рельсе)",
          "Светлая / тёмная тема" not in js and "I.theme" not in js
          and "LS.s(\"hub-theme\"" not in js)
    # статус поездки в рельсе — раньше он жил только в нижней панели
    check("nav-layer.js: рельс показывает «До старта · N дн» / «Идёт · день X из Y»",
          '"До старта · " + daysLeft' in js and '"Идёт · день " + dayNo + " из " + dayTot' in js
          and ".tnav-rail-st" in css)
    check("nav-layer.js: «Сегодня» в панели — с номером дня X/Y",
          'setBtn(bCtx, I.today, "Сегодня", dayNo + "/" + dayTot)' in js)
    check("nav-layer.css: рельс border-box (отступы не выталкивают «В начало» за край)",
          "box-sizing: border-box" in css.split(".tnav-rail {", 1)[1][:200])
    check("nav-layer.css: закрытая шторка visibility:hidden (тень не ложится на окно)",
          "visibility: hidden" in css.split(".tnav-sheet {", 1)[1][:600])
    check("nav-layer.js: переход по меню держит подсветку на цели (spyHold)",
          "spyHold" in js and "setActive(id);" in js)
    for _m in (h3, h4):
        check("Stage 3/4: панель «Сохранить» уважает hidden",
              ".edit-bar[hidden]{display:none;}" in _m._EDIT_CSS)
    check("nav-layer.js: «Заранее» в рельсе — со счётчиком несохранённого",
          "function paintRailPrep()" in js and "paintRailPrep();" in js
          and ".tnav-cta.has-unsaved" in css)

    # Stage 3: кнопка «Сохранить» edit-слоя не должна оказаться под панелью
    check("Stage 3 edit-bar поднят над панелью (--tnav-bottom)",
          "bottom:calc(18px + var(--tnav-bottom,0px))" in h3._EDIT_CSS)

    # Stage 2 в HTML — интерактивный lookup со своим шаблоном: слоя там нет
    # ОСОЗНАННО (нет ни .page, ни плашек — меню было бы пустым).
    s2 = KO / "2_similarity.md"
    if s2.exists():
        ex = stage2.extract_content(adapter.adapt_for_recipient(parser.parse_stage_file(s2), "self"))
        with tempfile.TemporaryDirectory() as t:
            inter = stage2.build_html(ex, Path(t) / "o.html", embed_fonts=False)
        check("Stage 2 (интерактивный lookup) — без слоя, это решение, а не потеря",
              "tnav-script" not in inter)


def test_prep_sync():
    """Отметки подготовки живут в строке плана (`- [x] …`), а не в отдельном
    хранилище: тогда они переживают пересборку экспорта и попадают в PDF.

    Здесь проверяется то, на чём это держится: нормализация сводит одну и ту же
    строку в HTML (ссылки отрисованы) и в `.md` (ссылки разметкой) к общему
    ключу; файл плана выбирается ПО СОДЕРЖИМОМУ (имя врёт: у Китая объявленный
    `5_final_plan_v1.md` не совпадает с лежащим `5_final _plan_v1.md`); правка
    трогает только символ в скобках; JS-зеркало получает те же правила.
    """
    print("\n[19] отметки подготовки: HTML ↔ план (prep_sync)")
    from export import prep_sync as ps

    js = (EXPORT_DIR / "assets" / "nav-layer.js").read_text(encoding="utf-8")
    md_line = "- [ ] Курс CNY/RUB — [cbr.ru](https://www.cbr.ru/), [xe.com](https://xe.com/)"
    html_line = "[ ] Курс CNY/RUB — cbr.ru, xe.com"
    check("ссылка в .md и отрисованная в HTML дают один ключ",
          ps.normalize_item(md_line.replace("- [ ] ", ""))
          == ps.normalize_item(html_line.replace("[ ] ", "")))
    check("«ё» и регистр не различают пункты",
          ps.normalize_item("Взять Приёмник") == ps.normalize_item("взять приемник"))
    check("пунктуация и жирный не различают",
          ps.normalize_item("**Виза** — проверить!") == ps.normalize_item("Виза  проверить"))

    md = ("## Чеклист\n\n- [ ] Купить билеты\n- [x] Оформить страховку\n"
          "  - [ ] Вложенный пункт\n\nпроза\n")
    items = ps.md_checklist(md)
    check("чеклист .md разобран (в т.ч. вложенный)", len(items) == 3)
    check("состояние из скобок", [i["done"] for i in items] == [False, True, False])
    check("номера строк с единицы", [i["line"] for i in items] == [3, 4, 5])

    new, missed = ps.apply_marks(md, {ps.normalize_item("Купить билеты"): True,
                                      ps.normalize_item("Оформить страховку"): False})
    check("правится только символ в скобках",
          "- [x] Купить билеты" in new and "- [x] Оформить страховку" not in new
          and "- [ ] Оформить страховку" in new)
    check("остальной текст цел", new.count("проза") == 1 and new.endswith("проза\n"))
    check("отступ вложенного пункта сохранён", "  - [ ] Вложенный пункт" in new)
    check("несуществующий пункт → missed, файл не тронут",
          ps.apply_marks(md, {"нет такого": True}) == (md, ["нет такого"]))

    dup = "- [ ] Один\n- [ ] Один\n"
    _, miss2 = ps.apply_marks(dup, {ps.normalize_item("Один"): True})
    check("неоднозначный пункт пропускается, а не угадывается", miss2 == [ps.normalize_item("Один")])

    # «[]» без пробела — встречается в рукописных правках плана
    empty = "- [] Пустые скобки\n- [ ] Пробел\n- [x] Отмечен\n"
    check("«[]» разбирается наравне с «[ ]»",
          [i["done"] for i in ps.md_checklist(empty)] == [False, False, True])
    fixed, _ = ps.apply_marks(empty, {ps.normalize_item("Пустые скобки"): True})
    check("запись в «[]» приводит скобки к канону «[x]»", "- [x] Пустые скобки" in fixed)
    check("«[]» в HTML-пункте тоже читается",
          [i["done"] for i in ps.html_checklist(
              '<div class="note-item"><div>[] Раз</div></div>'
              '<div class="note-item"><div>[x] Два</div></div>')] == [False, True])
    check("JS принимает пустые скобки в обеих проверках",
          "/^\\s*\\[[ xXхХ]?\\]/" in js and "/^\\[([ xXхХ]?)\\]/" in js)

    # сверка HTML ↔ план (отладочный слой): страница судит по плану, не по себе
    check("JS считает расхождения и показывает их",
          "diag = { checked: 0" in js and "HTML старше плана" in js
          and "нет строки в плане" in js and "текст встречается дважды" in js)
    check("правда за планом: состояние страницы подтягивается",
          "r.md = plan[r.key];" in js and "refreshFromPlan" in js)

    # выбор файла плана по содержимому
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        (d / "5_final_plan_v1.md").write_text("- [ ] Старая задача\n", encoding="utf-8")
        (d / "5_final_plan_v5.md").write_text(
            "- [ ] Купить билеты\n- [ ] Оформить страховку\n- [ ] Прогноз погоды\n", encoding="utf-8")
        page = ("".join(f'<div class="note-item"><div>[ ] {x}</div></div>'
                        for x in ("Купить билеты", "Оформить страховку", "Прогноз погоды")))
        res = ps.resolve_plan_md(d, page)
        check("версия плана выбрана по содержимому, не по имени",
              res and res["name"] == "5_final_plan_v5.md" and res["matched"] == 3, str(res))
        # имя-подсказка не может перебить содержимое
        res2 = ps.resolve_plan_md(d, page, hint="5_final_plan_v1.md")
        check("подсказка не перебивает содержимое",
              res2 and res2["name"] == "5_final_plan_v5.md")
        # чужая папка → цели нет (лучше не предложить, чем записать не туда)
        (d / "empty").mkdir()
        check("нет кандидатов → None", ps.resolve_plan_md(d / "empty", page) is None)
        # слабое совпадение не проходит порог
        weak = '<div class="note-item"><div>[ ] Совсем другой пункт</div></div>'
        check("совпадение ниже порога → None", ps.resolve_plan_md(d, weak) is None)

    # конфиг для страницы: те же правила, что у Python
    cfg = ps.js_config("5_final_plan_v5.md")
    check("в конфиг уезжает имя файла плана", cfg["mdFile"] == "5_final_plan_v5.md")
    check("правила нормализации уезжают в JS вербатим",
          [r[0] for r in cfg["normRules"]] == [r[0] for r in ps.NORM_RULES])
    check("regex строки чекбокса — общий с Python", cfg["itemRe"] == ps.ITEM_RE_SRC)

    check("JS строит RegExp из конфига, своей копии правил не держит",
          "new RegExp(r[0]" in js and "new RegExp(PCFG.itemRe)" in js)
    check("JS зеркалит apply_marks (правит только скобку)",
          'mm[1] + "[" + (marks[key] ? "x" : " ") + "] " + mm[3]' in js)

    # сборка Stage 5: конфиг цели попадает в документ
    md5 = KO / "5_final_plan_v1_1.md"
    if md5.exists():
        ex5 = _extract(stage5, md5)
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "5_корея_финальный_план_v1.html"
            plan = Path(t) / "5_final_plan_v1.md"
            plan.write_text(md5.read_text(encoding="utf-8"), encoding="utf-8")
            doc = h5.build_html(ex5, out, embed_fonts=False)
        has_items = bool(ps.html_checklist(doc))
        if has_items:
            check("Stage 5: цель записи отметок в странице",
                  'id="tnav-prep-config"' in doc and "5_final_plan_v1.md" in doc)
        else:
            skip("Stage 5: цель записи", "в фикстуре нет пунктов [ ]")
    else:
        skip("Stage 5 фикстура", "нет 5_final_plan_v1_1.md")

    # промежуточный рендер для PDF интерактив не несёт
    stripped = html_lib.strip_nav_layer(html_lib.build_html_document(
        "<p>x</p>", embed_fonts=False, doc_key="k", prep_md="5_final_plan_v1.md"))
    check("strip_nav_layer убирает и слой, и конфиг цели",
          "tnav-style" not in stripped and "tnav-prep-config" not in stripped
          and "<p>x</p>" in stripped)


def test_inject_nav():
    """Впрыск слоя в УЖЕ собранные экспорты (`inject_nav.py`).

    Нужен потому, что старые экспорты нельзя пересобрать без потери полиша
    (полированный вход часто эфемерный — на диске остались только сырой `.md`
    и собранный HTML). Ключевые свойства: содержимое документа не меняется,
    повторный прогон не удваивает слой, блок берётся из того же
    `html_lib.nav_layer()` — второй реализации слоя нет.
    """
    print("\n[18] впрыск слоя в готовые экспорты (inject_nav)")
    from export import inject_nav as inj

    tid = inj.trip_id_from_name("5_регион_b_2027-04_финальный_план_v1.html")
    check("trip_id и год разбираются из имени экспорта",
          tid == ("регион_b_2027-04", 2027), str(tid))
    check("имя вне конвенции → None", inj.trip_id_from_name("случайный.html") is None)

    # старый экспорт = документ, собранный без слоя
    old = html_lib.build_html_document(
        '<div class="page"><div class="guide">'
        '<div class="day day--transfer" id="day1"><div class="day-head">'
        '<span class="day-date">День 1 · 28.12</span>'
        '<h3 class="day-title">Старт</h3></div><p>полиш-текст</p></div>'
        '<div class="day" id="day5"><div class="day-head">'
        '<span class="day-date">День 5 · 03.01</span></div></div>'
        "</div></div>", title="t", embed_fonts=False, nav=False)
    check("исходный файл без слоя (предусловие)", "tnav-script" not in old)

    new, rep = inj.inject(old, doc_key="регион_b_2027-04", year=2026)
    check("слой впрыснут", 'id="tnav-style"' in new and 'id="tnav-script"' in new)
    import unicodedata
    nfd = unicodedata.normalize("NFD", "5_регион_b_2027-04_финальный_план_v1.html")
    old_bar = "<style>" + inj._EDIT_STATUS_CSS + "</style>"
    fixed, did = inj.fix_edit_bar(old_bar)
    check("inject_nav: старая панель «Сохранить» доводится до генератора, повторно — нет",
          did and inj._EDIT_BAR_FIX in fixed and inj.fix_edit_bar(fixed) == (fixed, False))
    check("trip_id из имени в NFD (macOS) → NFC, как у сборщика",
          inj.trip_id_from_name(nfd) == ("регион_b_2027-04", 2027))
    check("блок тот же, что у сборщика", html_lib.nav_layer() in new)
    check("ключ проставлен на body",
          'data-tnav-key="регион_b_2027-04"' in new)
    check("даты дней проставлены с переносом года",
          'id="day1" data-date="2026-12-28"' in new
          and 'id="day5" data-date="2027-01-03"' in new, str(rep))
    check("подписи дня не тронуты", "День 1 · 28.12" in new and "День 5 · 03.01" in new)
    check("контент документа сохранён", "полиш-текст" in new)

    # обратимость: снять слой и добавленные атрибуты → исходник байт в байт
    back = inj.strip_layer(new)
    import re as _re
    back = _re.sub(r' data-date="[\d-]+"', "", back)
    back = _re.sub(r' data-tnav-key="[^"]*"', "", back)
    check("правка обратима: снятие слоя даёт исходный файл", back == old)

    # идемпотентность: второй прогон обновляет, а не удваивает
    again, rep2 = inj.inject(new, doc_key="регион_b_2027-04", year=2026)
    check("повторный прогон не удваивает слой",
          again.count('id="tnav-style"') == 1 and again.count('id="tnav-script"') == 1)
    check("повторный прогон видит прежний слой (режим апгрейда)", rep2["had_layer"])
    check("повторный прогон не плодит data-date",
          again.count("data-date=") == new.count("data-date="))
    check("двойной впрыск идемпотентен по содержимому", again == new)

    # день без распознаваемой даты — атрибут не выдумывается
    plain = html_lib.build_html_document(
        '<div class="page"><div class="guide"><div class="day"><div class="day-head">'
        '<span class="day-date">День 2</span></div></div></div></div>',
        embed_fonts=False, nav=False)
    out, rep3 = inj.inject(plain, doc_key="x", year=2026)
    check("нет «DD.MM» в подписи → data-date не ставится",
          "data-date=" not in out and rep3["dates"] == 0)

    # не документ (интерактивный lookup Stage 2) — файл не трогаем
    with tempfile.TemporaryDirectory() as t:
        p = Path(t) / "2_поездка_2026-09_похожие_авторы.html"
        p.write_text("<html><body><div id='app'></div></body></html>", encoding="utf-8")
        before = p.read_text(encoding="utf-8")
        res = inj.process_file(p)
        check("интерактивная страница пропускается", "пропуск" in res, res)
        check("пропущенный файл не изменён", p.read_text(encoding="utf-8") == before)

    # не HTML — понятная ошибка, а не порча файла
    try:
        inj.inject("просто текст", doc_key="x")
        check("мусор на входе → ValueError", False)
    except ValueError:
        check("мусор на входе → ValueError", True)


def main():
    for fn in (test_md_inline, test_md_block, test_document,
               test_print_page_geometry, test_renderers,
               test_stage6_and_fixes, test_parse_day_nums,
               test_dispatcher, test_cli_routing,
               test_ru_anglicisms, test_feedback_layout, test_i18n_2c,
               test_plate_anno_helpers, test_design_review_fixes,
               test_final_polish, test_pdf_engines, test_pdf_degradation,
               test_wkhtmltopdf_opt_in,
               test_summary_text_blocks, test_completeness_contract,
               test_stage3_edit_layer, test_stage3_edit_md_name,
               test_strict_version, test_nav_layer, test_prep_sync, test_inject_nav):
        fn()
    print(f"\n{'=' * 60}\nВсего проверок: {checks_run}, провалов: {checks_failed}")
    sys.exit(1 if checks_failed else 0)


if __name__ == "__main__":
    main()
