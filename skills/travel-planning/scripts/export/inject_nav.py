#!/usr/bin/env python3
"""Впрыск навигационного слоя TNAV в УЖЕ собранные HTML-экспорты.

Зачем отдельный путь доставки. Слой инлайнится сборщиком
(`html_lib.build_html_document`), поэтому новые экспорты получают его сами и
этот скрипт им не нужен. Но экспорты, собранные ДО появления слоя, пересобрать
нельзя без потери полиша: полированный вход (`polished_*.md` с маркерами
`[[регион:]]`/`[[бронь:]]`) часто эфемерный — он жил в сессии, а на диске
остались только исходный `.md` и уже собранный HTML. Пересборка из `.md`
вернула бы документ к неполированному виду.

Второй реализации слоя тут НЕТ: блок берётся из `html_lib.nav_layer()`, даты
считает общий с экспортом `stages_html.stage5.iso_from_daydates`. Скрипт
идемпотентен — повторный прогон вырезает старый блок и ставит свежий, то есть
работает и как апгрейдер слоя в старых файлах.

Что делает с файлом:
  1. вырезает предыдущий блок слоя, если он есть;
  2. проставляет `data-tnav-key` на `<body>` (trip_id из имени файла) —
     общий ключ отметок подготовки у `5_план` и `6_финал`;
  3. проставляет `data-date` на карточки дней (год — из trip_id, число и
     месяц — из видимой подписи «День N · DD.MM»);
  4. вставляет свежий слой перед `</body>`;
  5. чинит CSS панели «Сохранить» edit-слоя Stage 3/4 (2026-10: `display:flex`
     перебивал `hidden` — панель висела всегда) — тем же правилом, что
     генератор (`_EDIT_BAR_FIX`), если его в файле ещё нет.
Содержимое документа при этом не трогается: полиш, правки, картинки, карта
остаются байт в байт.

Запуск:
    python3 inject_nav.py FILE.html [ещё файлы / каталоги]
    python3 inject_nav.py --dry-run trips/регион_a_2027
    python3 inject_nav.py --plan-md 5_final_plan_v2.md FILE.html   # план задан явно
    python3 inject_nav.py --dry-run trips          # все поездки: trips/*/[0-6]_*.html
    python3 inject_nav.py --backup-dir /tmp/nav-backup trips/*/[0-6]_*.html
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import unicodedata
from pathlib import Path

try:
    from export import html_lib, prep_sync
    from export.stages_html import stage5 as h5
except ImportError:  # запуск из каталога export/
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from export import html_lib, prep_sync          # type: ignore
    from export.stages_html import stage5 as h5     # type: ignore

# Наличие слоя (сам вырез — общий `html_lib.strip_nav_layer`).
_LAYER_RE = re.compile(r'<style id="tnav-style">', re.S)
# Карточка дня: class="day" или "day day--transfer", но НЕ "day-head"/"day-title".
_DAY_OPEN_RE = re.compile(r'<div class="day(?:\s[^"]*)?"[^>]*>')
_DAY_LABEL_RE = re.compile(r'<span class="day-date">([^<]*)</span>')
_DAY_NUM_RE = re.compile(r"День\s*(\d+)")
_DAY_DM_RE = re.compile(r"(\d{2})\.(\d{2})")
# trip_id внутри имени экспорта: «5_регион_b_2027-04_финальный_план_v1»
_TRIP_ID_RE = re.compile(r"^\d_(.+?_(20\d{2})-\d{2})_")
_BODY_RE = re.compile(r"<body([^>]*)>")
_PREPCFG_RE = re.compile(
    r'<script type="application/json" id="tnav-prep-config">.*?</script>', re.S)


# Правило из stages_html/stage3.py и stage4.py (_EDIT_CSS) — дописывается
# после `.edit-status{…}` в старых экспортах, собранных до него.
_EDIT_STATUS_CSS = ".edit-status{font-size:var(--fs-small,12px);opacity:.75;}"
_EDIT_BAR_FIX = ".edit-bar[hidden]{display:none;}.edit-status:empty{display:none;}"


def fix_edit_bar(html: str) -> tuple[str, bool]:
    """Довести CSS панели «Сохранить» до текущего генератора. (html, правили ли)."""
    if _EDIT_BAR_FIX in html or _EDIT_STATUS_CSS not in html:
        return html, False
    return html.replace(_EDIT_STATUS_CSS, _EDIT_STATUS_CSS + _EDIT_BAR_FIX, 1), True


def trip_id_from_name(name: str) -> tuple[str, int] | None:
    """('регион_b_2027-04', 2027) из имени файла экспорта, или None.

    Имя — в NFC: macOS отдаёт имена файлов разложенными (NFD, «и» + бреве),
    а сборщик берёт trip_id из frontmatter в NFC. Без нормализации ключ
    отметок впрыснутого файла не совпадал с ключом свежего экспорта."""
    m = _TRIP_ID_RE.match(unicodedata.normalize("NFC", Path(name).stem))
    return (m.group(1), int(m.group(2))) if m else None


def strip_layer(html: str) -> str:
    """Убрать ранее впрыснутый слой (для идемпотентности/апгрейда)."""
    return html_lib.strip_nav_layer(html)


def add_day_dates(html: str, year: int) -> tuple[str, int]:
    """Проставить `data-date` карточкам дней. Возвращает (html, сколько)."""
    opens = list(_DAY_OPEN_RE.finditer(html))
    if not opens:
        return html, 0
    # (позиция тега, day_num, «DD.MM») — подпись ищем сразу за открывающим тегом
    found: list[tuple[re.Match, int, str]] = []
    for m in opens:
        if "data-date=" in m.group(0):
            continue
        lbl = _DAY_LABEL_RE.search(html, m.end(), m.end() + 400)
        if not lbl:
            continue
        num = _DAY_NUM_RE.search(lbl.group(1))
        dm = _DAY_DM_RE.search(lbl.group(1))
        if not num or not dm:
            continue
        found.append((m, int(num.group(1)), f"{dm.group(1)}.{dm.group(2)}"))
    if not found:
        return html, 0
    dates = h5.iso_from_daydates([(n, d) for _m, n, d in found], year)
    out, last = [], 0
    for m, num, _d in found:
        iso = dates.get(num)
        if not iso:
            continue
        out.append(html[last:m.end() - 1])
        out.append(f' data-date="{iso}"')
        last = m.end() - 1
    out.append(html[last:])
    return "".join(out), len(dates)


def prep_target(html: str, directory: Path | str) -> str:
    """Файл плана для отметок подготовки (по содержимому; подсказка — строка
    провенанса «Собран из плана: …», которую печатает Stage 6)."""
    m = re.search(r"Собран из плана:\s*([^<\s][^<]*?)\s*<", html)
    res = prep_sync.resolve_plan_md(directory, html, hint=m.group(1) if m else None)
    return res["name"] if res else ""


def inject(html: str, *, doc_key: str = "", year: int | None = None,
           prep_md: str = "") -> tuple[str, dict]:
    """Впрыснуть слой в готовый HTML. Возвращает (html, отчёт)."""
    report = {"had_layer": bool(_LAYER_RE.search(html)), "dates": 0, "key": "",
              "prep_md": prep_md, "edit_bar": False}
    if "</body>" not in html:
        raise ValueError("не похоже на HTML-документ: нет </body>")
    html = strip_layer(html)
    html, report["edit_bar"] = fix_edit_bar(html)

    if doc_key:
        def _body(m: re.Match) -> str:
            attrs = re.sub(r'\s*data-tnav-key="[^"]*"', "", m.group(1))
            return f'<body{attrs} data-tnav-key="{doc_key}">'
        html, n = _BODY_RE.subn(_body, html, count=1)
        report["key"] = doc_key if n else ""

    if year:
        html, report["dates"] = add_day_dates(html, year)

    i = html.rfind("</body>")
    block = html_lib.prep_config_block(prep_md) + html_lib.nav_layer()
    return html[:i] + block + html[i:], report


def process_file(path: Path, *, dry_run: bool = False,
                 backup_dir: Path | None = None, plan_md: str = "") -> str:
    html = path.read_text(encoding="utf-8")
    # Интерактивный lookup Stage 2 — своя навигация, слой туда не ставим.
    if '<div class="page"' not in html:
        return "пропуск: не документ-лист (интерактивная страница)"
    tid = trip_id_from_name(path.name)
    key, year = (tid[0], tid[1]) if tid else ("", None)
    new, rep = inject(html, doc_key=key, year=year,
                      prep_md=plan_md or prep_target(html, path.parent))
    if new == html:
        return "без изменений"
    what = ("обновлён слой" if rep["had_layer"] else "слой добавлен")
    if rep["edit_bar"]:
        what += ", панель «Сохранить» исправлена"
    if rep["dates"]:
        what += f", дат проставлено: {rep['dates']}"
    if rep["prep_md"]:
        what += f", отметки → {rep['prep_md']}"
    elif prep_sync.html_checklist(html):
        what += ", ФАЙЛ ПЛАНА НЕ ОПОЗНАН (отметки только в браузере)"
    if dry_run:
        return f"[dry-run] {what}"
    if backup_dir:
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup_dir / path.name)
    path.write_text(new, encoding="utf-8")
    return what


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("paths", nargs="+", help="HTML-файлы или каталоги с ними")
    p.add_argument("--dry-run", action="store_true", help="только показать, что будет сделано")
    p.add_argument("--backup-dir", help="куда класть копии файлов перед записью")
    p.add_argument("--plan-md", default="",
                   help="имя файла плана для отметок, если авто-определение отказало "
                        "(v1 и v2 плана почти идентичны по чек-листу — уверенного кандидата нет)")
    args = p.parse_args(argv)

    files: list[Path] = []
    for raw in args.paths:
        pth = Path(raw)
        if pth.is_dir():
            here = sorted(f for f in pth.glob("*.html") if not f.name.startswith("."))
            # корень trips/ — стадии лежат на уровень глубже, в trips/{trip_id}/
            files.extend(here or sorted(f for f in pth.glob("*/[0-6]_*.html")
                                        if not f.name.startswith(".") and not f.parent.name.startswith(".")))
        elif pth.suffix.lower() == ".html":
            files.append(pth)
    if not files:
        print("нечего обрабатывать: HTML-файлы не найдены", file=sys.stderr)
        return 1

    backup = Path(args.backup_dir) if args.backup_dir else None
    for f in files:
        try:
            print(f"{f.name:52} {process_file(f, dry_run=args.dry_run, backup_dir=backup, plan_md=args.plan_md)}")
        except Exception as e:  # noqa: BLE001
            print(f"{f.name:52} ОШИБКА: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
