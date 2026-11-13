#!/usr/bin/env python3
"""normalize.py — детерминированная нормализация MD-артефактов к канону.

Применяется на **всех** стадиях 0–6: универсальные механические правила
коэрсят формат к канону `stageN-output-spec.md`. Идемпотентно, контент НЕ
меняет — только механика. Снимает с polish ручную работу (делиметр, `$`) и
убирает целый класс будущих формат-дрейфов до того, как они станут багами.

Сознательно НЕ делает рискованных структурных правок (перенумерация полей
`1.`→`1.2.3.`, реструктуризация карточек, скобки POI): это оставлено
толерантным парсерам + модели в петле — иначе нормализатор мог бы повредить
контент (нумерованные списки в прозе Stage 5 и т.п.), нарушив «polish ≠ writing».

Правила (универсальные, все стадии):
  • делиметр   — строка `-{4,}` → `---` (YAML-границы и разделители карточек);
  • $-escape   — `$NN` → `\\$NN` ВНЕ code-спанов (канон: `\\$` / `USD ` / backtick);
  • tidy       — хвостовые пробелы строк убрать.

Парсеры экспорта вызывают `normalize_delimiters` защитно (чтобы сырой `-----`
во входе парсился), полный `normalize` — инструмент save-time / CLI.

CLI:
  python3 normalize.py [--stage N] < in.md > out.md      # нормализует, пишет stdout
  python3 normalize.py --check     < in.md               # только отчёт в stderr, exit 1 если есть что чинить
"""
from __future__ import annotations

import argparse
import re
import sys

# Code-спаны (fenced ``` … ``` + inline `…`) — внутри них $-escape НЕ применяем.
_CODE_SPAN_RE = re.compile(r"```.*?```|`[^`\n]*`", re.DOTALL)
# Разделитель из 4+ дефисов на отдельной строке → канонические `---`.
_DELIM_RE = re.compile(r"^[ \t]*-{4,}[ \t]*$", re.MULTILINE)
# `$` перед цифрой, не экранированный.
_DOLLAR_RE = re.compile(r"(?<!\\)\$(\d)")
# Хвостовые пробелы.
_TRAILING_WS_RE = re.compile(r"[ \t]+$", re.MULTILINE)

# Блок frontmatter (между ведущими `---` и закрывающими `---`), CRLF-толерантно.
_FM_BLOCK_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)(\r?\n---[ \t]*(?:\r?\n|$))",
                          re.DOTALL)
# Типографские двойные кавычки, которые LLM ставит вместо ASCII `"` как
# YAML-делимитеры: “ (U+201C) ” (U+201D) „ (U+201E). Прямые → `"`.
_TYPO_DQUOTE = {0x201C: '"', 0x201D: '"', 0x201E: '"'}


def normalize_frontmatter_quotes(text: str) -> str:
    """В границах frontmatter выпрямить типографские двойные кавычки “ ” „ → `"`.

    Покрывает `key: “val”`, list-элементы `- “…”` и flow-списки [“a”, “b”] —
    везде, где LLM поставил типографские кавычки как YAML-делимитеры (иначе
    parse_yaml не снимает их, и значение с кавычками ломает матчинг — напр. имён
    регионов с `### {регион}`). Идемпотентно; тело документа НЕ трогает, guillemets
    «…» (U+00AB/BB — легитимные русские кавычки-контент) НЕ трогает."""
    m = _FM_BLOCK_RE.match(text)
    if not m:
        return text
    fm = m.group(1)
    fixed = fm.translate(_TYPO_DQUOTE)
    if fixed == fm:
        return text
    return text[:m.start(1)] + fixed + text[m.end(1):]


def normalize_delimiters(text: str) -> str:
    """`-{4,}`-строка → `---`. Парс-релевантно (YAML-границы)."""
    return _DELIM_RE.sub("---", text)


def normalize_dollar(text: str) -> str:
    """`$NN` → `\\$NN` ВНЕ code-спанов (внутри кода — как есть)."""
    out: list[str] = []
    last = 0
    for m in _CODE_SPAN_RE.finditer(text):
        out.append(_DOLLAR_RE.sub(r"\\$\1", text[last:m.start()]))
        out.append(m.group(0))          # code-спан не трогаем
        last = m.end()
    out.append(_DOLLAR_RE.sub(r"\\$\1", text[last:]))
    return "".join(out)


def normalize_tidy(text: str) -> str:
    """Хвостовые пробелы строк убрать (безопасный косметический тидиап)."""
    return _TRAILING_WS_RE.sub("", text)


# Универсальные правила (порядок важен: delimiters до прочего — иначе `-----`
# не даст распознать границы frontmatter для quote-фикса).
_UNIVERSAL = (normalize_delimiters, normalize_frontmatter_quotes,
              normalize_dollar, normalize_tidy)
# Per-stage правила (зарезервировано). Рискованные структурные сюда НЕ кладём —
# их обрабатывают толерантные парсеры. Ключ — `stage`-значение из YAML.
_PER_STAGE: dict[str, tuple] = {}


def normalize(text: str, stage: str | None = None) -> str:
    """Полная нормализация: универсальные + (опц.) per-stage правила."""
    for fn in _UNIVERSAL:
        text = fn(text)
    for fn in _PER_STAGE.get(str(stage), ()):  # type: ignore[arg-type]
        text = fn(text)
    return text


def diff_report(before: str, stage: str | None = None) -> list[str]:
    """Что нормализатор изменит (для `--check` и тестов)."""
    issues: list[str] = []
    n_delim = len(_DELIM_RE.findall(before))
    if n_delim:
        issues.append(f"делиметр: {n_delim} строк `----…` → `---`")
    # Типографские двойные кавычки во frontmatter (key/list/flow).
    fmq = _FM_BLOCK_RE.match(normalize_delimiters(before))
    if fmq:
        n_q = sum(fmq.group(1).count(chr(c)) for c in _TYPO_DQUOTE)
        if n_q:
            issues.append(f"frontmatter-кавычки: {n_q} `“ ” „` → `\"`")
    # $-escape — считаем только вне кода.
    stripped = _CODE_SPAN_RE.sub("", before)
    n_dollar = len(_DOLLAR_RE.findall(stripped))
    if n_dollar:
        issues.append(f"$-escape: {n_dollar} неэкранированных `$NN` → `\\$NN`")
    if _TRAILING_WS_RE.search(before):
        issues.append("tidy: хвостовые пробелы строк")
    return issues


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Нормализация MD-артефакта к канону.")
    ap.add_argument("--stage", default=None, help="номер стадии (0–6); для per-stage правил")
    ap.add_argument("--check", action="store_true",
                    help="не писать вывод; отчёт в stderr, exit 1 если есть что чинить")
    args = ap.parse_args(argv)
    text = sys.stdin.read()
    if args.check:
        issues = diff_report(text, args.stage)
        for it in issues:
            print(f"  • {it}", file=sys.stderr)
        return 1 if issues else 0
    sys.stdout.write(normalize(text, args.stage))
    return 0


if __name__ == "__main__":
    sys.exit(main())
