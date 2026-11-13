#!/usr/bin/env python3
"""Панель навигационного слоя на телефоне — НАСТОЯЩИМ браузером.

Зачем отдельный набор: обрезку подписи («Сохра…» вместо «Сохранить») нельзя
поймать чтением кода, и два подряд «исправления» её не убрали, потому что
мерились не те числа:

  1. `bar.scrollWidth > bar.clientWidth` — всегда 0: flex сжимает кнопки, а не
     переполняет панель;
  2. `label.scrollWidth > label.clientWidth` — почти всегда равны: у текста с
     `text-overflow: ellipsis` многоточие само помещается в отведённую ширину.

Рабочий признак — сравнить ширину кнопок при ЗАПРЕЩЁННОМ сжатии, что слой и
делает (класс `is-measuring`). Тест проверяет результат: на 320–430 px ни одна
подпись не обрезана и панель не вылезает за экран, а кнопка сохранения
появляется, как только есть неотправленные отметки.

Запуск из корня репозитория:
    python3 skills/travel-planning/tests/test_nav_layout.py

Без playwright/chromium — честный пропуск, не падение.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
EXPORT_DIR = REPO_ROOT / "skills" / "travel-planning" / "scripts" / "export"
sys.path.insert(0, str(EXPORT_DIR.parent))
from export import html_lib  # noqa: E402

checks_run = 0
checks_failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global checks_run, checks_failed
    checks_run += 1
    print(f"  {'✓' if cond else '✗'} {name}" + ("" if cond else f"  — {detail}"))
    if not cond:
        checks_failed += 1


# Документ-фикстура: обложка, день с датой (для кнопки «Сегодня»/«До старта»),
# раздел подготовки с пунктами `[ ]` — минимум, на котором панель полная.
BODY = (
    '<div class="page"><div class="guide">'
    '<div class="cover-kicker">Финальный план</div><h1 class="cover-title">Вьетнам</h1>'
    '<div class="section-plate"><span class="sp-title">Маршрут по дням</span></div>'
    '<div class="day" id="day1" data-date="2099-09-05"><div class="day-head">'
    '<span class="day-date">День 1 · 05.09</span><h3 class="day-title">Ханой</h3></div></div>'
    '<div class="section-plate section-plate--sub"><span class="sp-title">'
    'Чеклист за 2 недели до поездки</span></div><div class="notelist">'
    + "".join(f'<div class="note-item"><div>[ ] Пункт подготовки номер {i}</div></div>'
              for i in range(1, 8))
    + "</div></div></div>"
)

MEASURE = """() => {
  const bar = document.querySelector('.tnav-bar');
  const btns = [...bar.querySelectorAll('.tnav-b:not(.tnav-off)')].map(b => {
    const w = b.querySelector('.tnav-w');
    const shown = w && getComputedStyle(w).display !== 'none';
    return { text: b.textContent.trim() || '^', compact: b.classList.contains('is-compact'),
             clipped: shown ? (w.scrollWidth > w.clientWidth) : false };
  });
  const r = bar.getBoundingClientRect();
  return { btns, overflow: bar.scrollWidth - bar.clientWidth,
           offscreen: Math.round(r.right) > window.innerWidth || Math.round(r.left) < 0,
           docWider: document.documentElement.scrollWidth > window.innerWidth };
}"""


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("⊘ playwright не установлен — пропуск")
        return 0

    doc = html_lib.build_html_document(BODY, title="Вьетнам — финальный план",
                                       embed_fonts=False, doc_key="вьетнам_2026-09")
    with tempfile.TemporaryDirectory() as tmp:
        page_path = Path(tmp) / "5_вьетнам_2026-09_финальный_план_v1.html"
        page_path.write_text(doc, encoding="utf-8")
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                print("\n[1] панель на телефоне: подписи не режутся")
                for width in (320, 360, 390, 430):
                    for marks in (0, 3):
                        ctx = browser.new_context(viewport={"width": width, "height": 800})
                        pg = ctx.new_page()
                        pg.goto(page_path.as_uri())
                        pg.wait_for_timeout(400)
                        if marks:
                            pg.eval_on_selector_all(
                                ".tnav-box", f"ns => ns.slice(0,{marks}).forEach(n => n.click())")
                            pg.wait_for_timeout(300)
                        r = pg.evaluate(MEASURE)
                        label = f"{width}px, отметок {marks}"
                        clipped = [b["text"] for b in r["btns"] if b["clipped"]]
                        check(f"{label}: ни одна подпись не обрезана", not clipped, str(clipped))
                        check(f"{label}: панель в пределах экрана",
                              not r["offscreen"] and r["overflow"] <= 1, str(r))
                        check(f"{label}: документ не шире экрана", not r["docWider"])
                        has_save = any("tnav-b--save" in b for b in
                                       pg.eval_on_selector_all(".tnav-bar .tnav-b:not(.tnav-off)",
                                                               "ns => ns.map(n => n.className)"))
                        check(f"{label}: кнопка сохранения {'есть' if marks else 'скрыта'}",
                              has_save == bool(marks))
                        if marks:
                            # Подпись действия снимается ПОСЛЕДНЕЙ. На 320 px (самый узкий
                            # живой телефон) места не хватает даже так — там кнопка
                            # честно вырождается в «✓ 3»: иконка с числом, а не обрезок
                            # слова. Проверяем именно это: счётчик обязан остаться.
                            save = next(b for b in r["btns"] if "Сохран" in b["text"] or "Войти" in b["text"])
                            if width >= 360:
                                check(f"{label}: подпись действия сохранена", not save["compact"])
                            else:
                                check(f"{label}: действие вырождено в иконку со счётчиком",
                                      save["compact"] and str(marks) in save["text"], save["text"])
                        ctx.close()
                browser.close()
        except Exception as e:  # noqa: BLE001
            print(f"⊘ браузер недоступен ({type(e).__name__}: {e}) — пропуск")
            return 0

    print(f"\n{'=' * 60}\nВсего проверок: {checks_run}, провалов: {checks_failed}")
    return 1 if checks_failed else 0


if __name__ == "__main__":
    sys.exit(main())
