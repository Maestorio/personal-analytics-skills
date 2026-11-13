"""Единые кнопки и подвал на всех страницах кабинета (ui-kit 1.70.0, правила — tools/design-reference/buttons.md).

Проверяет то, что владелец сверяет глазами, переходя между вкладками:
  1. У страницы один цвет: --sec-acc на body = UI_ACC ui-kit = полоса плитки на хабе = таблица buttons.md;
     в браузере кнопка действия (.ui-btn), ромбик шапки (.ui-top-dot) и кнопка окна (.ui-modal-save) одного цвета.
  2. Форма: действие — прямоугольник (у .ui-btn скругление 8px), выбор — пилюля без заливки цветом
     (.fchip / .vchip / .chip-btn, если есть на странице); сегментный переключатель .ui-seg и кнопки шапки (.ui-top, .ui-hdr) — отдельные виды, не проверяются.
  3. Своих классов кнопок у страниц нет (rep-btn, tiny-btn, act-btn, plan-btn, share-btn, x-btn, btn-secondary),
     у <button> нет инлайн-заливки цветом раздела.
  4. Подвал — только uiFootHTML с версией (version:), своих подвалов (#buildline, .app-footer) нет; на открытой
     странице справа «<раздел> vX… · <состояние данных>», путь к данным — подсказкой (title), а не текстом.
Данные — пустой корень (страницы показывают «нет данных»): проверяется оформление, не содержимое.
Запуск: python3 tools/tests/test_buttons_uniform.py
"""
import os
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pages_stand import Checker, Quiet, per_engine, serve  # noqa: E402

check = Checker()
T = REPO / "tools"
PAGES = {   # страница → (ключ UI_ACC, цвет раздела по buttons.md)
    "hub.html": ("hub", None), "portfolio-integrated-viewer.html": (None, "--c-1"), "food.html": ("food", "--c-2"),
    "health.html": ("health", "--c-3"), "travel.html": ("travel", "--c-4"), "games.html": ("games", "--c-5"),
    "money.html": ("money", "--c-6"),
}
LEGACY = ("rep-btn", "tiny-btn", "act-btn", "plan-btn", "share-btn", "x-btn", "btn-secondary")
UIKIT_JS = (T / "assets/ui-kit.js").read_text(encoding="utf-8")
UI_ACC = dict(re.findall(r'(\w+): "(--[\w-]+)"', re.search(r"var UI_ACC = \{([^}]*)\}", UIKIT_JS).group(1)))
HUB = (T / "hub.html").read_text(encoding="utf-8")
DOC = (T / "design-reference/buttons.md").read_text(encoding="utf-8")


def src(page):
    s = (T / page).read_text(encoding="utf-8")
    if page.startswith("portfolio"):
        s += (T / "assets/viewer.js").read_text(encoding="utf-8") + (T / "assets/viewer.css").read_text(encoding="utf-8")
    return s


# ── 1–4 статически ──
for page, (key, acc) in PAGES.items():
    s = src(page)
    if acc:
        check(f"{page}: --sec-acc на body = {acc}", re.search(r"body\s*\{[^}]*--sec-acc:\s*var\(" + re.escape(acc) + r"\)", s) is not None
              or re.search(r'<body[^>]*--sec-acc:var\(' + re.escape(acc) + r'\)', s) is not None)
        if key:
            check(f"{page}: UI_ACC ui-kit «{key}» = {acc}", UI_ACC.get(key) == acc, str(UI_ACC.get(key)))
        if page != "portfolio-integrated-viewer.html":
            check(f"{page}: полоса плитки на хабе = {acc}", re.search(r'href="' + re.escape(page) + r'" style="border-left:3px solid var\(' + re.escape(acc) + r'\)', HUB) is not None
                  or re.search(r'href="' + re.escape(page) + r'"[^>]*>\s*<div class="card-top">\s*<span class="dom-eyebrow" style="color:var\(' + re.escape(acc) + r'\)', HUB) is not None)
        check(f"{page}: цвет {acc} записан в таблице buttons.md", re.search(r"\|\s*[^|]+\|\s*`" + re.escape(acc) + r"`", DOC) is not None)
    for cls in LEGACY:
        check(f"{page}: своего класса кнопки «{cls}» нет", re.search(r'class=\\?["\'][^"\']*\b' + cls + r'\b', s) is None)
    check(f"{page}: у <button> нет инлайн-заливки цветом раздела",
          re.search(r'<button[^>]*style="[^"]*background:\s*var\(--c-\d\)', s) is None)
    check(f"{page}: подвал — uiFootHTML с версией", re.search(r"uiFootHTML\(\{[^)]*version\s*:", s) is not None)
    check(f"{page}: своих подвалов нет (#buildline, .app-footer)", 'id="buildline"' not in s and not re.search(r'class=\\?["\']app-footer', s))


# ── 5. удаление: красная кнопка (.danger) и подтверждение (решение владельца 2026-11-10) ──
# действие → (страница, нужно ли подтверждение). Строки в несохранённой форме редактора (ed-*-del) подтверждения не
# требуют: «Отмена» формы возвращает всё как было; остальное удаляет записанные данные.
DELETES = {
    "health.html": {a: True for a in ("lab-del", "bp-del", "weight-del", "an-cdel", "an-alg-del", "an-ev-del", "an-del", "med-del", "study-del")},
    "games.html": {"gm-del": True},
    "money.html": {"csv-rule-remove": True},
    "food.html": {"item-del": True, "unplan": True, "clear-bought": True, "prod-del": True, "ed-delete": True,
                  "ed-ing-del": False, "ed-line-del": False, "ed-step-del": False},
}
for page, acts in DELETES.items():
    s = src(page)
    for act, need_confirm in acts.items():
        tags = re.findall(r'<button[^>]*data-act=\\?"' + re.escape(act) + r'\\?"[^>]*>', s) + \
               re.findall(r'<button[^>]*class=\\?"[^"\\]*"[^>]*data-act=\\?"' + re.escape(act) + r'\\?"', s)
        check(f"{page}: «{act}» — красная кнопка (.danger)", bool(tags) and all(re.search(r'class=\\?"[^"\\]*\bdanger\b', t) for t in tags))
        if need_confirm:
            m = re.search(r'(?<![\w-])["\']?' + re.escape(act) + r'["\']?\s*:\s*function[\s\S]{0,1400}?\n  [}"a-z]', s) or \
                re.search(r'act === "' + re.escape(act) + r'"\)\s*(\w+)\(', s)
            body = m.group(0) if m else ""
            if m and m.lastindex:      # вызов функции: тело функции
                f = re.search(r"function " + m.group(1) + r"\([\s\S]{0,900}", s)
                body = f.group(0) if f else body
            if "csvRuleRemove" in body or act == "csv-rule-remove":
                f = re.search(r"function csvRuleRemove\([\s\S]{0,500}", s); body = f.group(0) if f else body
            check(f"{page}: «{act}» спрашивает подтверждение", re.search(r"uiConfirm\(|confirm\w*Delete\(", body) is not None)


# ── в браузере ──
def run(name, br):
    tmp = Path(tempfile.mkdtemp())
    os.symlink(T, tmp / "tools")
    srv, base = serve(Quiet, directory=tmp)
    try:
        for page in PAGES:
            ctx = br.new_context(viewport={"width": 1280, "height": 900})
            ctx.add_init_script("localStorage.setItem('hub-auth','t')")
            pg = ctx.new_page()
            pg.goto(base + "/tools/" + page)
            try:
                pg.wait_for_selector(".ui-foot", state="attached", timeout=15000)
            except Exception:
                check(f"{name} {page}: подвал ui-kit (.ui-foot) на странице есть", False)
                ctx.close()
                continue
            pg.wait_for_timeout(400)
            r = pg.evaluate("""() => {
                const probe = (cls) => { const b = document.createElement('button'); b.className = cls; b.textContent = 'x';
                    document.body.appendChild(b); const g = getComputedStyle(b); const v = [g.backgroundColor, g.borderRadius]; b.remove(); return v; };
                const col = (v) => { const i = document.createElement('i'); i.style.color = v; document.body.appendChild(i);
                    const c = getComputedStyle(i).color; i.remove(); return c; };
                const acc = getComputedStyle(document.body).getPropertyValue('--sec-acc').trim();
                const dot = document.querySelector('.ui-top-dot');
                const pills = [...document.querySelectorAll('.fchip, .vchip, .chip-btn')].filter(e => e.offsetParent && !e.closest('.ui-top, .ui-hdr'))
                    .map(e => getComputedStyle(e)).map(g => [g.borderRadius, g.backgroundColor]);
                const foot = document.querySelector('.ui-foot'), meta = foot && foot.querySelector('.ui-foot-meta');
                return { btn: probe('ui-btn'), save: probe('ui-modal-save')[0], acc: acc ? col(acc) : col('var(--c-1)'),
                         dot: dot ? getComputedStyle(dot).backgroundColor : null, pills,
                         foot: meta ? meta.textContent.trim() : (foot ? foot.textContent.trim() : ''), title: meta ? meta.title : '' };
            }""")
            check(f"{name} {page}: кнопка действия цвета страницы", r["btn"][0] == r["acc"], f"{r['btn'][0]} / {r['acc']}")
            check(f"{name} {page}: кнопка окна «Сохранить» цвета страницы", r["save"] == r["acc"], f"{r['save']} / {r['acc']}")
            check(f"{name} {page}: действие — прямоугольник 8px", r["btn"][1] == "8px", r["btn"][1])
            if r["dot"] is not None and page != "hub.html":
                check(f"{name} {page}: ромбик шапки того же цвета, что кнопка", r["dot"] == r["btn"][0], f"{r['dot']} / {r['btn'][0]}")
            bad = [p for p in r["pills"] if not p[0].endswith("px") or int(float(p[0][:-2])) < 16 or p[1] == r["acc"]]
            check(f"{name} {page}: выбор — пилюля без заливки цветом ({len(r['pills'])} шт.)", not bad, str(bad[:3]))
            check(f"{name} {page}: подвал «раздел vX · состояние данных», путь — подсказкой",
                  re.search(r"\bv\d+(\.\d+)* · (загрузка…|данные живые|данные частично \(\d+/\d+\)|нет связи с данными|копия от .+)$", r["foot"]) is not None
                  and "Synology" not in r["foot"], f"{r['foot']!r} title={r['title']!r}")
            ctx.close()
    finally:
        srv.shutdown()
        srv.server_close()


if __name__ == "__main__":
    try:
        import playwright.sync_api  # noqa: F401
        per_engine(run, engines=("chromium",))
    except ImportError:
        print("buttons_uniform: браузерная часть пропущена — нет playwright")
    print(f"buttons_uniform: {check.passed} OK, {check.failed} FAIL")
    sys.exit(1 if check.failed else 0)
