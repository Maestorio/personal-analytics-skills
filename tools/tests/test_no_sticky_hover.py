#!/usr/bin/env python3
"""Липкая подсветка на касании: `:hover` только внутри `@media (hover:hover)`.

Было (ui-kit 1.61): на iPhone :hover остаётся на элементе под пальцем после тапа —
кнопки и плитки выглядят «нажатыми». Правило: любое правило с `:hover` в селекторе
лежит внутри @media (hover:hover); комбинированные `.a:hover, .a:focus-visible`
разделяются — focus-visible остаётся снаружи. Проверяются <style> всех страниц
tools/*.html и все tools/assets/*.css. Разбор текста со счётом вложенности
фигурных скобок (комментарии вырезаются), браузер не нужен.
"""
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
passed = failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}")


def strip_comments(s):
    return re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), s, flags=re.S)


def blocks(s):
    i, n = 0, len(s)
    while i < n:
        j = s.find("{", i)
        if j < 0:
            return
        d, k = 1, j + 1
        while k < n and d:
            d += (s[k] == "{") - (s[k] == "}")
            k += 1
        yield s[i:j], s[j + 1:k - 1]
        i = k


def bare_hover(css):
    """Селекторы с :hover, у которых нет предка @media (hover:hover)."""
    res = []

    def walk(c, ok):
        for pre, body in blocks(c):
            p = pre.strip()
            if p.startswith("@"):
                if re.match(r"@(media|supports|layer)", p):
                    walk(body, ok or bool(re.search(r"hover\s*:\s*hover", p)))
            elif ":hover" in p and not ok:
                res.append(" ".join(p.split()))

    walk(strip_comments(css), False)
    return res


if __name__ == "__main__":
    # самопроверка разбора
    check("разбор: голый :hover найден", bare_hover(".a:hover{x:1}") == [".a:hover"])
    check("разбор: внутри hover:hover — чисто", not bare_hover("@media (hover: hover){ .a:hover{x:1} }"))
    check("разбор: внутри max-width — голый", bare_hover("@media (max-width:600px){ .a:hover{x:1} }") == [".a:hover"])
    check("разбор: в комментарии не считается", not bare_hover("/* .a:hover{x:1} */ .b{x:1}"))
    check("разбор: вложенный hover внутри max-width — чисто",
          not bare_hover("@media (max-width:600px){ @media (hover:hover){ .a:hover{x:1} } }"))

    srcs = {}
    for f in sorted(TOOLS.glob("*.html")):
        srcs[f"tools/{f.name}"] = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", f.read_text(encoding="utf-8"), flags=re.S))
    for f in sorted((TOOLS / "assets").glob("*.css")):
        srcs[f"tools/assets/{f.name}"] = f.read_text(encoding="utf-8")
    check("найдены страницы и css-ассеты", len(srcs) >= 10)
    for name, css in srcs.items():
        bad = bare_hover(css)
        check(f"{name}: нет :hover вне @media (hover:hover) ({bad[:3]})", not bad)
    print(f"no_sticky_hover: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
