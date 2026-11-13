#!/usr/bin/env python3
"""
render_weekly_md.py — сборка MD-отчёта недельного обзора (Mode 1 / Mode 2) из YAML (RPA-33).

Зачем. 26.10.2026 модель написала MD обзора акций целиком сама: одноразовый `build_report.py` на 66 КБ
отчёта и около 26 шагов правки под линт — вторая по весу причина переполнения контекста на Sonnet.
Но 80–90% отчёта — пересказ YAML: таблица позиций, очередь условий, покрытие проверкой, IE-дисциплина,
катализаторы, оговорки, источники. Это детерминированная часть; суждение модели — короткое:
итог недели, срочные действия, «что произошло / рекомендация» по бумагам с новостями, пункты действий.
Скрипт собирает отчёт из YAML, модель пишет только `changes.md`.

Формат `changes.md` — фрагменты с маркерами-комментариями (текст до первого маркера недопустим):
  <!-- section: summary -->   итог недели / основной вывод          [ОБЯЗАТЕЛЕН]
  <!-- section: actions -->   пункты действий по приоритету          [ОБЯЗАТЕЛЕН]
  <!-- section: urgent -->    срочные действия (нет — раздел опущен)
  <!-- section: macro -->     макро-контекст (нет — опущен)
  <!-- section: ie -->        изменения / материалы Invest Era (нет — опущен)
  <!-- section: events -->    только облигации: рейтинговые действия и корпоративные события
  <!-- section: risks -->     ключевые риски (нет — строятся из YAML `key_risks`)
  <!-- section: extra -->     свободный раздел со своим заголовком `##` в тексте
  <!-- item: SBER -->  или  <!-- item: SBER | Сбербанк -->   (облигации — ISIN)
      раздел по бумаге с новостями: «Что произошло / Рекомендация». Заголовок, вес/цена/план,
      гейт словами, катализаторы и источники бумаги дописывает скрипт из YAML.
  <!-- cond: <id условия> -->   резолюция сработавшего условия одной строкой («применён …» / «уже исполнено — …» /
      «отклонено — …» / «перенесено — …»); id — из выборки `--conditions`. Обзор состояние условий не пишет:
      резолюция — только текст отчёта (у старых обзоров — `conditions_evaluated.fired[].resolution` YAML).
Бумага БЕЗ фрагмента попадает в таблицу «без существенных новостей» одной строкой из YAML
(вердикт, уверенность, первая фраза `advisor_verdict_basis`, вес/план) — текст не выдумывается.

Из YAML строятся: шапка (`snapshot_id:` строкой), таблица позиций, покрытие проверкой,
IE-дисциплина (акции), топ катализаторы, оговорки, источники (без дублей URL, с `accessed_date`),
план ↔ факт (облигации). Нет поля в YAML — нет строки. Очередь условий — из `--conditions` (JSON-вывод
`apply_condition.py digest` на дату обзора: строки модуля (а), резолюция сработавшего — из фрагмента
`<!-- cond: id -->` changes.md, у старых обзоров — из `conditions_evaluated.fired`); без него — из YAML старого обзора
как есть. Статусы гейтов — словами (gate_status_ru),
голое «Mode N» в тексте из YAML заменяется на «разбор бумаги (Mode 4)».

Проверка текста модели. Фрагменты `changes.md` скрипт не правит, но проверяет вне обратных кавычек:
голый «Mode N» без слов (правило: режим словами с номером в скобках — references/output-templates.md
§ «Режимы в тексте для человека») и коды статусов гейтов (`reviewed_keep` и др. — gate_status_ru).
Находки — предупреждения в stderr (раздел/бумага + цитата), код выхода остаётся 0; `--strict-text` → 3.

`--embed-notes` (контракт A плана переосмысления вьюера, 2026-10-26): фрагмент каждой бумаги
разбирается в `per_*[id].week_note = {what_happened: [...], recommendation: [...], macro_link}`
(подписи «Что произошло / Рекомендация / Макро», markdown снимается) и YAML обзора перезаписывается
(без якорей, порядок ключей сохраняется); у бумаги без фрагмента поле снимается. Карточка во вьюере
показывает «Что произошло за неделю» из него, старые обзоры без поля читаются как раньше.

Необязательные расширения (аддитивные: без них вывод прежний):
  - `name` бумаги в YAML (акции — из стаба) — название в заголовке раздела; маркер `| Название` приоритетнее;
  - `coverage.checked_dates` (sweep_collect) — даты проверки в блоке покрытия и колонке «Проверка»;
  - `--prior PRIOR.yaml` — прошлый обзор того же вида: цена (акции, таблица позиций) и цена/YTM
    (облигации, по ISIN) «прошлое → текущее»; бумаги нет в прошлом — только текущее.

CLI:
  python3 render_weekly_md.py --yaml review.yaml --changes changes.md --output review.md [--kind stock|bond]
                              [--prior prior.yaml] [--strict-text]
Код выхода: 0 — готово; 2 — ошибка входа (неизвестный/повторный маркер, нет обязательного раздела,
бумаги нет в YAML, нечитаемый файл, --prior другого вида); 3 — только с --strict-text: в тексте модели
есть предупреждения (файл при этом записан). Зависимости: stdlib + PyYAML; gate_status_ru.py
(канон _shared-references/, в бандле — рядом).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("render_weekly_md.py требует PyYAML\n")
    sys.exit(2)

# gate_status_ru — канон _shared-references/ (в бандле pack.sh кладёт его в scripts/ рядом).
_SHARED_DIR = Path(__file__).resolve().parents[3] / "_shared-references"
if _SHARED_DIR.is_dir() and str(_SHARED_DIR) not in sys.path:
    sys.path.append(str(_SHARED_DIR))
from gate_status_ru import GATE_STATUS_RU, label as gate_label, effect as gate_effect  # noqa: E402
import rating_check as rc  # noqa: E402
from terms_ru import MODE_RU as _MODE_WORDS, VERDICT_RU, L2_RU, conf_word  # noqa: E402


# --- маркеры changes.md ----------------------------------------------------

SECTIONS_COMMON = ("summary", "actions", "urgent", "macro", "ie", "risks", "extra")
SECTIONS_BOND_ONLY = ("events",)
REQUIRED_SECTIONS = ("summary", "actions")

_MARKER = re.compile(r"<!--\s*(section|item|cond)\s*:\s*(.*?)\s*-->")
# резолюции сработавших условий (<!-- cond: id -->) — в sections под этим ключом словарём {id: текст}
COND_RESOLUTIONS = "_cond_resolutions"


class InputError(Exception):
    """Ошибка входа (код выхода 2)."""


def allowed_sections(kind: str) -> tuple[str, ...]:
    return SECTIONS_COMMON + (SECTIONS_BOND_ONLY if kind == "bond" else ())


def parse_changes(text: str, kind: str, known_items: set[str]):
    """→ (sections: {имя: текст}, items: {id: (имя|None, текст)}). Ошибки — InputError."""
    allowed = allowed_sections(kind)
    parts = _MARKER.split(text)
    # split с 2 группами: [до, тип, значение, текст, тип, значение, текст, ...]
    if parts[0].strip():
        raise InputError("changes.md: текст до первого маркера недопустим "
                         "(каждый фрагмент начинается с <!-- section: … --> или <!-- item: … -->)")
    sections: dict[str, str] = {}
    items: dict[str, tuple[str | None, str]] = {}
    for i in range(1, len(parts), 3):
        mtype, mval, body = parts[i], parts[i + 1].strip(), parts[i + 2].strip()
        if mtype == "cond":
            res = sections.setdefault(COND_RESOLUTIONS, {})
            if not mval:
                raise InputError("маркер cond без id условия")
            if mval in res:
                raise InputError(f"резолюция условия «{mval}» задана дважды")
            if body:
                res[mval] = " ".join(body.split())
            continue
        if mtype == "section":
            if mval not in allowed:
                raise InputError(f"неизвестный раздел «{mval}»; допустимые: {', '.join(allowed)}")
            if mval in sections:
                raise InputError(f"раздел «{mval}» задан дважды")
            if body:
                sections[mval] = body
        else:
            ident, _, name = mval.partition("|")
            ident, name = ident.strip(), name.strip() or None
            if not ident:
                raise InputError("маркер item без идентификатора бумаги")
            if ident not in known_items:
                raise InputError(f"бумага «{ident}» из changes.md отсутствует в YAML")
            if ident in items:
                raise InputError(f"бумага «{ident}» задана дважды")
            if body:
                items[ident] = (name, body)
    for req in REQUIRED_SECTIONS:
        if req not in sections:
            raise InputError(f"нет обязательного раздела «{req}» (<!-- section: {req} -->)")
    return sections, items


# --- week_note: фрагмент бумаги → YAML (контракт A плана переосмысления вьюера, 2026-10-26) ---------

# Подписи блоков во фрагменте бумаги: «**Что произошло:**», «Рекомендация:», «### Макро-связь».
_NOTE_LABELS = (
    ("what_happened", ("что произошло", "что случилось", "события недели", "новости недели", "новости")),
    ("recommendation", ("рекомендация", "вердикт", "что делать", "решение")),
    ("macro_link", ("макро", "макро-связь", "связь с макро", "макро-привязка", "макро-контекст")),
)
# подпись с двоеточием («**Рекомендация:** держать») или заголовок/жирная строка без него («### Макро»)
_NOTE_LINE = re.compile(r"^\s*(?:#{1,6}\s*)?(?:[*_]{1,2})?\s*([^:*_#]{3,40}?)\s*(?:[*_]{1,2})?\s*(?::\s*(?:[*_]{1,2})?\s*(.*?))?\s*$")
_MD_MARK = re.compile(r"(\*\*|__)")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")


def _note_key(label: str) -> str | None:
    low = label.strip().lower()
    for key, names in _NOTE_LABELS:
        if low in names:
            return key
    return None


def _note_items(lines: list[str]) -> list[str]:
    """Строки блока → пункты: маркеры списка снимаются, абзацы без маркеров — своим пунктом,
    продолжение строки (без маркера после маркера) приклеивается к предыдущему пункту."""
    items: list[str] = []
    prev_bullet = False
    for raw in lines:
        t = _MD_MARK.sub("", raw).rstrip()
        if not t.strip():
            prev_bullet = False
            continue
        if _BULLET.match(t):
            items.append(_BULLET.sub("", t).strip())
            prev_bullet = True
        elif prev_bullet and items and t.startswith((" ", "\t")):
            items[-1] = (items[-1] + " " + t.strip()).strip()
        else:
            items.append(t.strip())
            prev_bullet = False
    return [i for i in items if i]


def parse_week_note(frag: str) -> dict | None:
    """Фрагмент бумаги из changes.md → {what_happened: [...], recommendation: [...], macro_link: str|None}.
    Блоки узнаются по подписям («Что произошло», «Рекомендация», «Макро»); текст без подписи — в
    what_happened. Markdown-жирность и маркеры списка снимаются, текст иначе не правится.
    Пустой фрагмент → None."""
    blocks: dict[str, list[str]] = {"what_happened": [], "recommendation": [], "macro_link": []}
    cur = "what_happened"
    for line in (frag or "").splitlines():
        m = _NOTE_LINE.match(line)
        key = _note_key(m.group(1)) if m else None
        if key:
            cur = key
            if (m.group(2) or "").strip():
                blocks[cur].append(m.group(2))
            continue
        blocks[cur].append(line)
    wh, rec, macro = (_note_items(blocks[k]) for k in ("what_happened", "recommendation", "macro_link"))
    if not (wh or rec or macro):
        return None
    return {"what_happened": wh, "recommendation": rec, "macro_link": " ".join(macro) or None}


class _NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):  # без якорей &id001 — как carry_over_weekly.py
        return True


def embed_week_notes(y: dict, items: dict, kind: str) -> int:
    """Вкладывает week_note в per_stock/per_bond[ident] по фрагментам (бумага без фрагмента — поле
    снимается: прошлонедельный week_note не должен выдаваться за текущий). → число записанных."""
    per = y.get("per_stock" if kind == "stock" else "per_bond") or {}
    n = 0
    for ident, p in per.items():
        if not isinstance(p, dict):
            continue
        note = parse_week_note(items[ident][1]) if ident in items else None
        if note:
            p["week_note"] = note
            n += 1
        else:
            p.pop("week_note", None)
    return n


def dump_yaml(data: dict) -> str:
    return yaml.dump(data, Dumper=_NoAliasDumper, sort_keys=False, allow_unicode=True, default_flow_style=False)


# --- форматирование ---------------------------------------------------------

def num(x, nd: int = 2, sign: bool = False, trim: bool = False) -> str:
    """Число как в отчётах: запятая, пробел — разделитель тысяч, «−» для минуса. Не число → «—»."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return "—"
    s = f"{x:,.{nd}f}".replace(",", " ")
    if trim and "." in s:
        s = s.rstrip("0").rstrip(".")
    if sign and x > 0:
        s = "+" + s
    s = s.replace(".", ",").replace("-", "−")
    return s


def pct(x, nd: int = 2, sign: bool = False) -> str:
    return "—" if not isinstance(x, (int, float)) or isinstance(x, bool) else num(x, nd, sign) + "%"


def frac_pct(x, nd: int = 1, sign: bool = True) -> str:
    """Доля (0,2018) → «+20,2%»."""
    return "—" if not isinstance(x, (int, float)) or isinstance(x, bool) else pct(x * 100, nd, sign)


def rub(x) -> str:
    return "—" if not isinstance(x, (int, float)) or isinstance(x, bool) else num(x, 0) + " ₽"


def cell(s) -> str:
    """Безопасная ячейка таблицы: без переводов строк и «|»."""
    if s is None or s == "":
        return "—"
    return " ".join(str(s).split()).replace("|", "\\|")


# _MODE_WORDS — канон terms_ru.MODE_RU (контракт D, 2026-10-26)
_BARE_MODE = re.compile(r"(?<![(\w])Mode (\d[ab]?)\b")
_GATE_CODE = re.compile(r"(?<![\w`])(" + "|".join(map(re.escape, GATE_STATUS_RU)) + r")(?![\w`])")


def ru_modes(text):
    """Текст из YAML для человека: «Mode 4 от 17.09» → «разбор бумаги (Mode 4) от 17.09» (со словами —
    не трогает); код статуса гейта (review_needed) → «Нужен разбор» (gate_status_ru)."""
    if not isinstance(text, str):
        return text
    text = _GATE_CODE.sub(lambda m: f"«{gate_label(m.group(1))}»", text)

    def repl(m):
        w = _MODE_WORDS.get(m.group(1))
        if not w:
            return m.group(0)
        before = m.string[max(0, m.start() - 45): m.start()].lower()
        if w.split()[0][:5] in before:  # слова режима уже стоят рядом: «разбор бумаги 17.09, Mode 4»
            return m.group(0)
        return f"{w} (Mode {m.group(1)})"

    return _BARE_MODE.sub(repl, text)


_CODE_SPAN = re.compile(r"```.*?```|`[^`\n]*`", re.S)


def check_text(sections: dict, items: dict) -> list[str]:
    """Предупреждения по тексту модели (changes.md) вне обратных кавычек: голый «Mode N» и коды гейтов.
    → ['раздел «summary»: голый «Mode 4» — …цитата…', ...]. Текст не правит."""
    warns: list[str] = []

    def scan(where: str, text: str):
        t = _CODE_SPAN.sub(lambda m: " " * len(m.group(0)), text)  # код в `...` легален; длины сохраняем
        quote = lambda m: " ".join(text[max(0, m.start() - 35): m.end() + 35].split())
        for m in _BARE_MODE.finditer(t):
            w = _MODE_WORDS.get(m.group(1))
            before = t[max(0, m.start() - 45): m.start()].lower()
            if w and w.split()[0][:5] in before:
                continue  # слова режима уже рядом
            warns.append(f"{where}: голый «Mode {m.group(1)}» без слов (нужно «"
                         f"{w or 'режим словами'} (Mode {m.group(1)})») — …{quote(m)}…")
        for m in _GATE_CODE.finditer(t):
            warns.append(f"{where}: код статуса гейта «{m.group(1)}» (нужно «{gate_label(m.group(1))}») — …{quote(m)}…")

    for name, text in sections.items():
        if name == COND_RESOLUTIONS:
            for cid, t in (text or {}).items():
                scan(f"резолюция условия {cid}", t)
            continue
        scan(f"раздел «{name}»", text)
    for ident, (_, text) in items.items():
        scan(f"бумага {ident}", text)
    return warns


def first_sentence(text, limit: int = 200) -> str:
    if not isinstance(text, str) or not text.strip():
        return "—"
    t = " ".join(text.split())
    parts = re.split(r"(?<=[.!?;])\s+(?=[А-ЯA-Z0-9«])", t)
    s = parts[0]
    if len(s) > limit:
        s = s[: limit - 1].rstrip(" ,;:") + "…"
    return s


def ds(date_s) -> str:
    """2026-10-26 → 26.10 для короткой подписи; не дату — как есть."""
    m = re.fullmatch(r"(\d{4})-(\d\d)-(\d\d)", str(date_s or ""))
    return f"{m.group(3)}.{m.group(2)}" if m else str(date_s or "")


# Вердикты акций — заглавными из канона terms_ru (REDUCE/WATCH — старые синонимы обзоров до 2026-07).
STOCK_VERDICT_RU = {**{k: v.upper() for k, v in VERDICT_RU.items()}, "REDUCE": "СОКРАТИТЬ", "WATCH": "НАБЛЮДАТЬ"}


def verdict_ru(v, kind: str) -> str:
    if not v:
        return "—"
    return STOCK_VERDICT_RU.get(str(v), str(v)) if kind == "stock" else str(v)


def verdict_conf(item: dict, kind: str) -> str:
    """«ДЕРЖАТЬ (средняя)» — уверенность словом, не числом (контракт D; до 2026-10-26 — «(0,65)»)."""
    v = verdict_ru(item.get("advisor_verdict"), kind)
    w = conf_word(item.get("advisor_verdict_confidence"))
    return f"{v} ({w})" if w else v


def table(headers: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(cell(c) for c in r) + " |" for r in rows]
    return out


def _wsort(d: dict):
    return sorted(d.items(), key=lambda kv: -(kv[1].get("weight_real_pct") or 0)
                  if isinstance(kv[1], dict) else 0)


# --- источники ---------------------------------------------------------------

_URL = re.compile(r"https?://[^\s;,)\]]+")


class SourceBook:
    """Источники без дублей URL; без URL — дубль по тексту."""

    def __init__(self):
        self.groups: dict[str, list[tuple[str, str, str]]] = {}
        self.seen: set[str] = set()

    def add(self, group: str, url: str | None, label: str | None, date_s: str | None = None):
        key = (url or label or "").strip()
        if not key or key in self.seen:
            return
        self.seen.add(key)
        self.groups.setdefault(group, []).append((url or "", label or "", date_s or ""))

    def add_any(self, group: str, obj, prefix: str = ""):
        """Строка / {url,label,accessed_date} / список таких."""
        if isinstance(obj, list):
            for o in obj:
                self.add_any(group, o, prefix)
        elif isinstance(obj, dict):
            url = obj.get("url")
            label = obj.get("label") or obj.get("title") or ""
            if url or label:
                self.add(group, url, (prefix + label).strip(), obj.get("accessed_date"))
        elif isinstance(obj, str) and obj.strip():
            urls = _URL.findall(obj)
            if urls and len(urls) == 1 and obj.strip() == urls[0]:
                self.add(group, urls[0], prefix.strip() or None)
            elif urls:
                for u in urls:
                    self.add(group, u, (prefix + "см. текст источника").strip())
            else:
                self.add(group, None, prefix + obj.strip())

    def render(self) -> list[str]:
        out: list[str] = []
        for g, rows in self.groups.items():
            out += [f"**{g}:**"]
            for url, label, d in rows:
                body = " — ".join(x for x in (label, url) if x)
                out.append(f"- {ru_modes(body)}" + (f" ({ds(d)})" if d else ""))
            out.append("")
        return out


def collect_sources(y: dict, per: dict, kind: str, items: set | None = None) -> list[str]:
    """Сводный список. По бумагам — только открытые в этом прогоне (`accessed_date` = дата обзора) и
    только у бумаг без своего раздела: у бумаг с фрагментом источники уже стоят в разделе. Полный
    список с датами — в YAML (на обзоре 26.10 без этого отбора блок занимал 37 из 105 КБ MD)."""
    items = items or set()
    rd = str(y.get("review_date") or "")[:10]
    book = SourceBook()
    src = y.get("sources")
    if isinstance(src, dict):
        for k, v in src.items():
            if k in ("macro", "web"):
                book.add_any("Макро и рынок" if k == "macro" else "Веб", v)
            elif k in ("snapshot", "prior_review", "macro_input", "conditions", "free_form_reports",
                       "reports", "external_reviews", "moex_quotes", "moex_iss"):
                book.add_any("Файлы и первичные данные", v)
            else:
                book.add_any("Прочее", v)
    for t, p in per.items():
        if not isinstance(p, dict) or t in items:
            continue
        for key in ("fundamental_score_sources", "fundamental_sources", "div_sources"):
            fresh = [x for x in p.get(key) or [] if isinstance(x, dict) and str(x.get("accessed_date") or "")[:10] == rd]
            book.add_any("По бумагам (открыты в этом прогоне)", fresh, prefix=f"{t}: ")
    out = book.render()
    if out:
        out += ["", "Полный список источников с датами проверки — в YAML обзора (`*_sources`, `catalyst[].source`)."]
    return out


# --- блоки бумаги ------------------------------------------------------------

def _effect_text(c: dict) -> str:
    up, dn = c.get("upside_pct"), c.get("downside_pct")
    ci_u, ci_d = c.get("upside_ci_pct"), c.get("downside_ci_pct")
    parts = []
    if isinstance(up, (int, float)):
        ci = f" [{num(ci_u[0], 1)}; {num(ci_u[1], 1)}]" if isinstance(ci_u, list) and len(ci_u) == 2 else ""
        parts.append(f"ожидаемый эффект {num(up, 1, True)}%{ci}")
    if isinstance(dn, (int, float)):
        ci = f" [{num(ci_d[0], 1)}; {num(ci_d[1], 1)}]" if isinstance(ci_d, list) and len(ci_d) == 2 else ""
        parts.append(f"downside {num(-abs(dn), 1)}%{ci}")
    if isinstance(c.get("p"), (int, float)):
        parts.append(f"p={num(c['p'], 2)}")
    return ", ".join(parts)


def catalyst_line(c: dict, who: str | None = None) -> str:
    head = f"**{who}**: " if who else ""
    trig = ru_modes(first_sentence(c.get("trigger"), 180))
    eff = _effect_text(c)
    win = f"; окно {c['date_window']}" if c.get("date_window") else ""
    return f"{head}{trig} — {eff}{win}" if eff else f"{head}{trig}{win}"


def _rating_checked_note(p: dict) -> str:
    """« (проверен ДД.ММ.ГГГГ)» / « (дата проверки не записана)»; у суверенных бумаг пусто."""
    if rc.is_sovereign(p):
        return ""
    d = rc.parse_check_date(p.get("credit_rating_checked_at"))
    return f" (проверен {d.strftime('%d.%m.%Y')})" if d else " (дата проверки не записана)"


def rating_due_line(y: dict, per: dict) -> list[str]:
    """Одна строка-сводка под таблицами облигаций; нет таких бумаг — пусто."""
    asof = rc.parse_check_date(str(y.get("snapshot_date") or y.get("review_date") or "")[:10])
    if asof is None:
        return []
    due = rc.bonds_due_for_rating_check(per, asof)
    if not due:
        return []
    return [f"Рейтинг пора перепроверить: {', '.join(rc.due_label(d) for d in due)}.", ""]


def item_block(ident: str, name: str | None, frag: str, p: dict, kind: str, per_label: str) -> list[str]:
    title = f"{name}" if name else ""
    if kind == "stock":
        head = f"#### {ident}" + (f" ({title})" if title else "") + f" — {verdict_ru(p.get('advisor_verdict'), kind)}"
    else:
        nm = p.get("name") or ""
        head = f"### {nm or ident} (`{ident}`) — **{p.get('advisor_verdict') or '—'}**"
        if isinstance(p.get("value_rub"), (int, float)):
            head += f" · {rub(p['value_rub'])}"
        if isinstance(p.get("weight_in_bonds_pct"), (int, float)):
            head += f" · {pct(p['weight_in_bonds_pct'])} облигаций"
    out = [head]
    facts = []
    if kind == "stock":
        w, pl, dv = p.get("weight_real_pct"), p.get("weight_user_planned_pct"), p.get("weight_divergence_vs_planned_pp")
        if isinstance(w, (int, float)):
            s = f"вес {pct(w)} {L2_RU}"
            if isinstance(pl, (int, float)):
                s += f" при плане {pct(pl, 1)}"
                if isinstance(dv, (int, float)):
                    s += f" ({num(dv, 2, True)} пп)"
            facts.append(s)
        if isinstance(p.get("price_rub"), (int, float)):
            facts.append(f"цена {num(p['price_rub'], 2)} ₽")
        if isinstance(p.get("xirr"), (int, float)):
            facts.append(f"XIRR {frac_pct(p['xirr'])}")
        if isinstance(p.get("pnl_rub"), (int, float)):
            facts.append(f"P&L {rub(p['pnl_rub'])}")
    else:
        if isinstance(p.get("current_price"), (int, float)):
            facts.append(f"цена {num(p['current_price'], 2)}")
        if isinstance(p.get("ytm_pct"), (int, float)):
            facts.append(f"YTM {pct(p['ytm_pct'])}")
        if isinstance(p.get("duration_days"), (int, float)):
            facts.append(f"дюрация {num(p['duration_days'], 0)} дн")
        if p.get("maturity_date"):
            facts.append(f"погашение {p['maturity_date']}")
        if p.get("credit_rating"):
            facts.append(f"рейтинг {p['credit_rating']}" + _rating_checked_note(p))
        elif not rc.is_sovereign(p) and "credit_rating" in p:
            facts.append("рейтинг не установлен" + _rating_checked_note(p))
    if facts:
        out.append("Позиция: " + "; ".join(facts) + ".")
    g = (p.get("gate_status_snapshot") or {}).get("status") if kind == "stock" else None
    if g:
        eff = gate_effect(g)
        out.append(f"Гейт: «{gate_label(g)}»" + (f" — {eff.rstrip('.')}." if eff else "."))
    cw = conf_word(p.get("advisor_verdict_confidence"))
    cb = p.get("confidence_basis")
    if cw:   # уверенность словом и что её снижает (confidence_basis, 2026-10-26)
        out.append(f"Уверенность: {cw}" + (f" — {ru_modes(str(cb).strip().rstrip('.'))}." if isinstance(cb, str) and cb.strip() else "."))
    out += ["", frag.strip(), ""]
    cats = [c for c in (p.get("catalyst") or []) if isinstance(c, dict)]
    if cats:
        out.append("**Катализаторы:**")
        out += [f"- {catalyst_line(c)}" for c in cats]
        out.append("")
    book = SourceBook()
    for key in ("fundamental_score_sources", "fundamental_sources", "div_sources"):
        book.add_any("", p.get(key))
    rows = book.groups.get("", [])
    if rows:
        out.append("**Источники по бумаге:**")
        for url, label, d in rows:
            out.append(f"- {ru_modes(' — '.join(x for x in (label, url) if x))}" + (f" ({ds(d)})" if d else ""))
        out.append("")
    return out


# --- разделы -----------------------------------------------------------------

def header_lines(y: dict, kind: str, today: str) -> list[str]:
    title = "Обзор акций за неделю (Mode 1)" if kind == "stock" else "Обзор облигаций за неделю (Mode 2)"
    lines = [f"# Weekly Review {y.get('review_date', '')} — {title}", ""]
    meta = [("snapshot_id", y.get("snapshot_id")), ("review_date", y.get("review_date"))]
    he = y.get("horizon_ends")
    if y.get("horizons"):
        hz = "/".join(str(h) for h in y["horizons"]) + " мес"
        if y.get("primary_horizon"):
            hz += f" (primary {y['primary_horizon']})"
        if isinstance(he, dict):
            hz += " · " + " · ".join(f"{k} {v}" for k, v in he.items())
        meta.append(("horizons", hz))
    meta.append(("model", y.get("producer")))
    src = y.get("sources") if isinstance(y.get("sources"), dict) else {}
    pr = y.get("carried_over_from") or src.get("prior_review")
    meta.append(("prior_review", Path(str(pr)).name if pr else None))
    per = y.get("period")
    if isinstance(per, dict) and per.get("from") and per.get("to"):
        meta.append(("period", f"{per['from']} → {per['to']}"))
    meta.append(("macro", y.get("macro_source")))
    lines += ["```"]
    lines += [f"{k + ':':<14}{ru_modes(v)}" for k, v in meta if v]
    lines += ["```", ""]
    return lines


def portfolio_lines(y: dict, kind: str) -> list[str]:
    out: list[str] = []
    if kind == "stock":
        ps = y.get("portfolio_summary")
        if not isinstance(ps, dict):
            return out
        if "stocks_share_actual_pct" in ps:
            s = f"Класс «Акции»: {pct(ps['stocks_share_actual_pct'])} NAV"
            if "stocks_share_target_pct" in ps:
                s += f" при цели {pct(ps['stocks_share_target_pct'], 1)}"
            if "stocks_undershoot_pct" in ps:
                s += f"; недобор {num(ps['stocks_undershoot_pct'], 2, True)} пп"
                if "stocks_undershoot_rub" in ps:
                    s += f" ({rub(ps['stocks_undershoot_rub'])})"
            out.append("- " + s)
        r = ps.get("returns") if isinstance(ps.get("returns"), dict) else {}
        if "stocks_xirr" in r:
            s = f"XIRR акций {frac_pct(r['stocks_xirr'])}"
            if "stocks_pnl_rub" in r:
                s += f"; P&L {rub(r['stocks_pnl_rub'])}"
            out.append("- " + s)
    else:
        s = y.get("summary")
        if not isinstance(s, dict):
            return out
        if "bond_share_pct" in s:
            t = f"Класс «Облигации»: {pct(s['bond_share_pct'])} NAV"
            if "target_share_pct" in s:
                t += f" при цели {pct(s['target_share_pct'], 1)}"
            if "share_delta_pct" in s:
                t += f"; Δ {num(s['share_delta_pct'], 2, True)} пп"
            if "bond_deficit_rub" in s:
                t += f" ({rub(s['bond_deficit_rub'])})"
            out.append("- " + t)
        wy = s.get("weighted_ytm_pct")
        wy = wy.get("value") if isinstance(wy, dict) else wy
        if isinstance(wy, (int, float)):
            t = f"Средневзвешенная YTM {pct(wy)}"
            if isinstance(s.get("weighted_duration_days"), (int, float)):
                t += f", дюрация {num(s['weighted_duration_days'], 0)} дн"
            out.append("- " + t)
        if isinstance(s.get("verdict_counts"), dict):
            out.append("- Вердикты: " + ", ".join(f"{k} — {v}" for k, v in s["verdict_counts"].items()))
        r = s.get("returns") if isinstance(s.get("returns"), dict) else {}
        if "bond_xirr" in r:
            t = f"XIRR облигаций {frac_pct(r['bond_xirr'])}"
            if "bond_pnl_rub" in r:
                t += f"; P&L {rub(r['bond_pnl_rub'])}"
            out.append("- " + t)
    return (["## Сводка портфеля", ""] + out + [""]) if out else []


def _div12(p: dict):
    """Дивдоходность 12м: div_yield_12m_pct, иначе dividend_forward.year1_yield_pct."""
    v = p.get("div_yield_12m_pct")
    if isinstance(v, (int, float)):
        return v
    df = p.get("dividend_forward")
    return df.get("year1_yield_pct") if isinstance(df, dict) else None


def arrow(prev, cur, nd: int = 2) -> str:
    """«прошлое → текущее»; прошлого нет (не число) — только текущее."""
    if isinstance(prev, (int, float)) and not isinstance(prev, bool):
        return f"{num(prev, nd)} → {num(cur, nd)}"
    return num(cur, nd)


def stock_positions_table(per: dict, prior_per: dict | None = None) -> list[str]:
    rows = []
    for t, p in _wsort(per):
        cats = [c for c in (p.get("catalyst") or []) if isinstance(c, dict)]
        key_event = first_sentence(cats[0].get("trigger"), 70) if cats else "—"
        g = (p.get("gate_status_snapshot") or {}).get("status")
        row = [
            t, pct(p.get("weight_real_pct")), pct(p.get("weight_user_planned_pct"), 1),
            pct(p.get("weight_ie_target_pct"), 1), num(p.get("weight_divergence_vs_planned_pp"), 2, True),
            frac_pct(p.get("xirr")), pct(_div12(p)),
            verdict_conf(p, "stock"), gate_label(g) if g else "—", ru_modes(key_event),
        ]
        if prior_per is not None:
            pp = prior_per.get(t) if isinstance(prior_per.get(t), dict) else {}
            row.insert(1, arrow(pp.get("price_rub"), p.get("price_rub")))
        rows.append(row)
    heads = ["Тикер", "Вес L2", "План", "IE", "Δ к плану, пп", "XIRR", "Див. 12м",
             "Вердикт (уверенность)", "Гейт", "Ключевое событие"]
    if prior_per is not None:
        heads.insert(1, "Цена, ₽ (было → стало)")
    out = ["## Позиции — акции", ""]
    out += table(heads, rows)
    out += ["", "Примечание: вес L2 — доля внутри класса «Акции» по снапшоту; знак Δ: минус = недовес к плану; "
            "«Ключевое событие» — первый катализатор бумаги из YAML.", ""]
    return out


def stock_item_sections(per: dict, items: dict) -> list[str]:
    if not items:
        return []
    out = ["## Позиции с существенными новостями (детали)", ""]
    by_sector: dict[str, list[str]] = {}
    for t, p in _wsort(per):
        if t in items:
            by_sector.setdefault(p.get("sector_ru") or p.get("sector") or "Прочее", []).append(t)
    for sector, tickers in by_sector.items():
        out += [f"### {sector}", ""]
        for t in tickers:
            name, frag = items[t]
            out += item_block(t, name or per[t].get("name"), frag, per[t], "stock", "")  # маркер приоритетнее YAML
    return out


def quiet_stock_table(per: dict, items: dict, cov: dict) -> list[str]:
    carried = set((cov or {}).get("carried_over") or [])
    not_checked = set((cov or {}).get("not_checked") or [])
    dates = (cov or {}).get("checked_dates") if isinstance((cov or {}).get("checked_dates"), dict) else {}
    rows = []
    for t, p in _wsort(per):
        if t in items:
            continue
        chk = "carry-over: новости не проверены" if t in carried else (
            "не проверено" if t in not_checked else ("проверено" if cov else "—"))
        if chk == "проверено" and dates.get(t):
            chk += f" {ds(dates[t])}"
        rows.append([t, verdict_conf(p, "stock"),
                     f"{pct(p.get('weight_real_pct'))} / план {pct(p.get('weight_user_planned_pct'), 1)}",
                     ru_modes(first_sentence(p.get("advisor_verdict_basis"))), chk])
    if not rows:
        return []
    return ["## Позиции без существенных новостей", ""] + table(
        ["Тикер", "Вердикт (уверенность)", "Вес L2 / план", "Обоснование (первая фраза)", "Проверка"], rows) + [""]


def _bond_px_ytm(isin: str, p: dict, prior_per: dict | None) -> list[str]:
    """Цена и YTM для таблицы: с --prior — «прошлое → текущее» по ISIN (нет в прошлом — только текущее)."""
    if prior_per is None:
        return [num(p.get("current_price"), 2), num(p.get("ytm_pct"), 2)]
    pp = prior_per.get(isin) if isinstance(prior_per.get(isin), dict) else {}
    return [arrow(pp.get("current_price"), p.get("current_price")), arrow(pp.get("ytm_pct"), p.get("ytm_pct"))]


def bond_tables(per: dict, prior_per: dict | None = None) -> list[str]:
    groups: dict[str, list] = {}
    for isin, p in _wsort(per):
        groups.setdefault(p.get("plan_bucket") or p.get("bond_type") or "Прочее", []).append((isin, p))
    out = ["## Цены, YTM и вердикты по корзинам", ""]
    for g, lst in groups.items():
        out += [f"### {g}", ""]
        out += table(["Выпуск", "ISIN", "Цена" + (" (было → стало)" if prior_per is not None else ""),
                      "YTM, %" + (" (было → стало)" if prior_per is not None else ""), "Дюр., дн", "Погашение", "Доля книги", "Вердикт"],
                     [[p.get("name") or isin, f"`{isin}`", *_bond_px_ytm(isin, p, prior_per),
                       num(p.get("duration_days"), 0), p.get("maturity_date"), pct(p.get("weight_in_bonds_pct")),
                       p.get("advisor_verdict")] for isin, p in lst])
        out.append("")
    return out


def bond_item_sections(per: dict, items: dict) -> list[str]:
    if not items:
        return []
    out = ["## Позиции, требующие внимания", ""]
    for isin, p in _wsort(per):
        if isin in items:
            name, frag = items[isin]
            out += item_block(isin, name, frag, p, "bond", "")
    return out


def quiet_bond_table(per: dict, items: dict) -> list[str]:
    rows = []
    for isin, p in _wsort(per):
        if isin in items:
            continue
        chk = "carry-over: новости не проверены" if p.get("carried_over") else "проверено"
        prior = p.get("prior_verdict")
        v = verdict_conf(p, "bond") + (f"; было {prior}" if prior and prior != p.get("advisor_verdict") else "")
        rows.append([p.get("name") or isin, v, pct(p.get("weight_in_bonds_pct")),
                     ru_modes(first_sentence(p.get("advisor_verdict_basis"))), chk])
    if not rows:
        return []
    return ["## Остальные позиции — обоснования", ""] + table(
        ["Выпуск", "Вердикт (уверенность)", "Доля книги", "Обоснование (первая фраза)", "Проверка"], rows) + [""]


def plan_vs_fact(y: dict) -> list[str]:
    pvf = y.get("plan_vs_fact")
    if not isinstance(pvf, list) or not pvf:
        return []
    base = y.get("plan_vs_fact_base_rub")
    out = ["## План ↔ факт по корзинам" + (f" (база без ИИС-3: {rub(base)})" if base else ""), ""]
    out += table(["Корзина", "План, %", "Факт, %", "Δ, пп", "Δ, ₽"],
                 [[r.get("bucket_key"), num(r.get("target_pct"), 1), num(r.get("actual_pct"), 2),
                   num(r.get("delta_pp"), 2, True), num(r.get("delta_rub"), 0, True)]
                  for r in pvf if isinstance(r, dict)])
    return out + [""]


def plan_change(y: dict) -> list[str]:
    pc = y.get("plan_change_proposal")
    if not isinstance(pc, dict):
        return []
    out = ["## Предложения по плану (решение владельца)", ""]
    if pc.get("status"):
        out.append(f"- Статус: {ru_modes(pc['status'])}")
    for ch in pc.get("changes") or []:
        if isinstance(ch, dict):
            out.append(f"- {ch.get('bucket_key')}: {num(ch.get('from_pct'), 1)}% → {num(ch.get('to_pct'), 1)}%")
    for k, lab in (("basis", "Обоснование"), ("funding_note", "Источники средств")):
        if pc.get(k):
            out.append(f"- {lab}: {ru_modes(pc[k])}")
    ac = pc.get("also_consider")
    if isinstance(ac, dict) and ac.get("note"):
        out.append(f"- Также: {ac.get('bucket_key', '')} — {ru_modes(ac['note'])}")
    return out + [""]


def stale_conditions(y: dict, conds: dict | None = None) -> bool:
    """Блок условий не этой недели: дата выборки (`conds["today"]` из `apply_condition.py digest`; без неё —
    `conditions_evaluated.evaluated_at` старого обзора) раньше даты обзора больше чем на 3 дня."""
    if conds is not None:
        ev = str(conds.get("today") or "")[:10]
    else:
        ce = y.get("conditions_evaluated")
        ev = str(ce.get("evaluated_at") or "")[:10] if isinstance(ce, dict) else ""
    rd = str(y.get("review_date") or "")[:10]
    try:
        from datetime import date as _d
        return bool(ev and rd) and (_d.fromisoformat(rd) - _d.fromisoformat(ev)).days > 3
    except ValueError:
        return False


STALE_HINT = "повторить `apply_condition.py digest --today <дата обзора>` и передать вывод в `--conditions`"


def _trig(tr) -> str:
    if not isinstance(tr, dict):
        return str(tr or "—")
    return f"{tr.get('type')} {tr.get('value')}" + (f", окно до {tr['window_end']}" if tr.get("window_end") else "")


def conditions_digest_block(y: dict, per: dict, conds: dict, resolutions: dict | None = None) -> list[str]:
    """Очередь условий из выдачи `apply_condition.py digest` (строки модуля (а)); резолюция сработавшего — из
    фрагмента `<!-- cond: id -->` changes.md, у старого обзора — `conditions_evaluated.fired[].resolution` по id."""
    res = {}
    ce = y.get("conditions_evaluated")
    for f in (ce.get("fired") or []) if isinstance(ce, dict) else []:
        if isinstance(f, dict) and f.get("id") and f.get("resolution"):
            res[f["id"]] = f["resolution"]
    res.update(resolutions or {})
    out = [f"## Очередь условий (на {conds.get('today') or '—'})", ""]
    if stale_conditions(y, conds):
        out += [f"> ⚠ Выборка условий от {conds.get('today')} — не этой недели (обзор {str(y.get('review_date'))[:10]}): "
                f"{STALE_HINT}.", ""]
    body, others = [], 0
    for c in conds.get("items") or []:
        if not isinstance(c, dict) or not c.get("active"):
            continue
        if c.get("key") not in per:
            others += 1
            continue
        text = c.get("text") or c.get("note")
        if c.get("status") == "fired":
            s = f"- ✅ `{c.get('id')}` — {c.get('key')}: СРАБОТАЛО ({_trig(c.get('trigger'))})"
            s += f" → **резолюция: {res[c['id']]}**" if c.get("id") in res else " — ждёт резолюции"
        else:
            s = f"- ⏳ `{c.get('id')}` — {c.get('key')}: ждёт ({_trig(c.get('trigger'))})"
        if text:
            s += f" — {first_sentence(text, 260)}"
        body.append(ru_modes(s))
    if others:
        body.append(f"- Условий по бумагам вне этого обзора: {others}.")
    return (out + body + [""]) if body else []


def conditions_block(y: dict, per: dict, kind: str, conds: dict | None = None,
                     resolutions: dict | None = None) -> list[str]:
    if conds is not None:
        return conditions_digest_block(y, per, conds, resolutions)
    out = ["## Очередь условий", ""]
    body: list[str] = []
    if kind == "stock":
        ce = y.get("conditions_evaluated")
        if not isinstance(ce, dict):
            return []
        summ = {}
        for t, p in per.items():
            for c in (p.get("user_constraints") or []) if isinstance(p, dict) else []:
                if isinstance(c, dict) and c.get("id") and c.get("summary"):
                    summ[c["id"]] = c["summary"]
        if ce.get("evaluated_at"):
            out[0] = f"## Очередь условий (на {ce['evaluated_at']})"
            if stale_conditions(y):
                out += [f"> ⚠ Блок условий от {ce['evaluated_at']} — не этой недели (обзор {str(y.get('review_date'))[:10]}): "
                        f"{STALE_HINT}.", ""]
        for f in ce.get("fired") or []:
            if isinstance(f, dict):
                s = f"- ✅ `{f.get('id')}` — {f.get('ticker')}: СРАБОТАЛО ({f.get('trigger')})"
                if f.get("resolution"):
                    s += f" → **резолюция: {f['resolution']}**"
                if f.get("note"):
                    s += f" — {f['note']}"
                body.append(ru_modes(s))
        others = 0
        for pnd in ce.get("pending_next_7_30d") or []:
            if not isinstance(pnd, dict):
                continue
            if pnd.get("ticker") not in per:
                others += 1
                continue
            s = f"- ⏳ `{pnd.get('id')}` — {pnd.get('ticker')}: не выполнено ({pnd.get('trigger')})"
            if summ.get(pnd.get("id")):
                s += f" — {first_sentence(summ[pnd['id']], 260)}"
            body.append(ru_modes(s))
        if others:
            body.append(f"- Условий по бумагам вне этого обзора (облигации и др.): {others}.")
        for key, lab in (("added", "Добавлено"), ("pruned", "Снято")):
            lst = ce.get(key) or []
            if lst:
                body.append(f"- {lab}: " + ", ".join(
                    f"`{x.get('id')}`" if isinstance(x, dict) else str(x) for x in lst))
        if ce.get("note"):
            body.append(f"- Примечание: {ru_modes(first_sentence(ce['note'], 600))}")
    else:
        for c in y.get("conditions_state") or []:
            if isinstance(c, dict):
                s = f"- ⏳ `{c.get('id')}` — {c.get('state') or '—'}"
                if c.get("note"):
                    s += f": {c['note']}"
                body.append(ru_modes(s))
        if y.get("conditions_mutations_applied"):
            body.append(f"- Изменения условий: {ru_modes(y['conditions_mutations_applied'])}")
    return (out + [""] + body + [""]) if body else []


def coverage_block(y: dict, per: dict, kind: str) -> list[str]:
    out: list[str] = []
    if kind == "stock":
        cov = y.get("coverage")
        if not isinstance(cov, dict):
            return []
        chk, car, nch = cov.get("checked_this_run") or [], cov.get("carried_over") or [], cov.get("not_checked") or []
        total = cov.get("tickers_total")
        out.append(f"- Проверено {len(chk)}" + (f" из {total}" if total else "") + " тикеров: " +
                   (", ".join(chk) or "—"))
        dates = cov.get("checked_dates") if isinstance(cov.get("checked_dates"), dict) else {}
        dd = {t: dates[t] for t in chk if dates.get(t)}
        if dd:
            uniq = sorted(set(dd.values()))
            if len(uniq) == 1 and len(dd) == len(chk):
                out[-1] += f"; дата проверки {ds(uniq[0])}"
            else:
                out.append("- Даты проверки: " + ", ".join(f"{t} ({ds(d)})" for t, d in dd.items()))
        if car:
            out.append("- Carry-over (новости не проверены): " + ", ".join(car))
        if nch:
            out.append("- Не проверено: " + ", ".join(nch))
        if cov.get("note"):
            out.append(f"- Ограничения: {ru_modes(cov['note'])}")
    else:
        carried = [p.get("name") or i for i, p in per.items() if isinstance(p, dict) and p.get("carried_over")]
        if not per:
            return []
        out.append(f"- Проверено в этом прогоне {len(per) - len(carried)} из {len(per)} выпусков.")
        if carried:
            out.append("- Carry-over (новости не проверены): " + ", ".join(carried))
    return ["## Покрытие проверкой (R-COV)", ""] + out + [""]


def ie_block(y: dict) -> list[str]:
    ie = y.get("ie_discipline")
    if not isinstance(ie, dict):
        return []
    out: list[str] = []
    if "real_share_total_in_ie_pct" in ie:
        out.append(f"- Доля бумаг IE-модели в книге: {pct(ie['real_share_total_in_ie_pct'])}; порог отклонения "
                   f"{num(ie.get('threshold_pp'), 1)} пп; дрейфов без решения: {ie.get('drifts_without_decision', '—')}")
    dev = [d for d in ie.get("deviations_ge_threshold") or [] if isinstance(d, dict)]
    if dev:
        out += ["", "**Отклонения от IE ≥ порога:**", ""]
        out += table(["Тикер", "Факт", "План", "IE", "Решение"],
                     [[d.get("ticker"), pct(d.get("real")), pct(d.get("planned"), 1), pct(d.get("ie"), 1),
                       ru_modes(d.get("mark"))] for d in dev])
        out.append("")
    if ie.get("outside_ie"):
        out.append("- Вне модели IE: " + ", ".join(ie["outside_ie"]))
    for x in ie.get("ie_not_in_portfolio") or []:
        out.append(f"- IE-бумага не в портфеле: {x}")
    for k, lab in (("ie_changes_this_period", "Изменения IE за период"), ("ie_materials_this_period", "Материалы IE"),
                   ("trust_note", "Доверие к IE")):
        if ie.get(k):
            out.append(f"- {lab}: {ru_modes(ie[k])}")
    return (["## IE-дисциплина", ""] + out + [""]) if out else []


def top_catalysts(per: dict, kind: str, n: int = 8) -> list[str]:
    pos, neg = [], []
    for t, p in per.items():
        if not isinstance(p, dict):
            continue
        who = t if kind == "stock" else (p.get("name") or t)
        for c in p.get("catalyst") or []:
            if not isinstance(c, dict):
                continue
            up, dn = c.get("upside_pct"), c.get("downside_pct")
            if isinstance(up, (int, float)) and up > 0:
                pos.append((up, who, c))
            if isinstance(dn, (int, float)) and dn != 0:
                neg.append((abs(dn), who, c))
    if not pos and not neg:
        return []
    out = ["## Топ катализаторы", ""]
    for title, lst in (("Позитивные", pos), ("Риски", neg)):
        if not lst:
            continue
        lst.sort(key=lambda r: -r[0])
        out += [f"### {title}", ""]
        out += [f"{i}. {catalyst_line(c, who)}" for i, (_, who, c) in enumerate(lst[:n], 1)]
        if len(lst) > n:
            out.append(f"\nПоказано {n} из {len(lst)}; полный список — в YAML (`catalyst[]` по бумагам).")
        out.append("")
    out.append("Все p и Δ% — экспертные оценки advisor, не калиброванная вероятностная модель.")
    return out + [""]


def risks_block(y: dict, frag: str | None) -> list[str]:
    if frag:
        return ["## Ключевые риски", "", frag.strip(), ""]
    kr = y.get("key_risks")
    if not isinstance(kr, list) or not kr:
        return []
    out = ["## Ключевые риски", ""]
    for r in kr:
        if not isinstance(r, dict):
            continue
        text = r.get("risk") or r.get("note") or ""
        who = r.get("ticker") or r.get("id")
        out.append(f"- **{r.get('severity', '—')}**" + (f" — {who}" if who else "") + f": {ru_modes(text)}")
    return out + [""]


def caveats_block(y: dict) -> list[str]:
    cv = y.get("caveats")
    if not isinstance(cv, list) or not cv:
        return []
    out = ["## Caveats", ""]
    for c in cv:
        if isinstance(c, dict):
            out.append(f"- **{c.get('severity', '—')}** — {ru_modes(c.get('message') or c.get('text') or '')}")
        else:
            out.append(f"- {ru_modes(str(c))}")
    return out + [""]


def sec(title: str, frag: str | None) -> list[str]:
    return [f"## {title}", "", frag.strip(), "", "---", ""] if frag else []


# --- сборка ------------------------------------------------------------------

def render(y: dict, sections: dict, items: dict, kind: str, prior: dict | None = None,
           conds: dict | None = None) -> str:
    per = y.get("per_stock" if kind == "stock" else "per_bond") or {}
    per = {k: v for k, v in per.items() if isinstance(v, dict)}
    pper = None  # --prior: бумаги прошлого обзора того же вида; None — режим «как раньше»
    if prior is not None:
        pper = prior.get("per_stock" if kind == "stock" else "per_bond")
        pper = pper if isinstance(pper, dict) else {}
    L: list[str] = header_lines(y, kind, "")
    L += sec("Executive summary" if kind == "stock" else "Основной вывод", sections.get("summary"))
    L += sec("Срочные действия", sections.get("urgent"))
    L += portfolio_lines(y, kind)
    if kind == "stock":
        L += stock_positions_table(per, pper)
        L += stock_item_sections(per, items)
        L += quiet_stock_table(per, items, y.get("coverage") or {})
    else:
        L += sec("Рейтинговые действия и корпоративные события", sections.get("events"))
        L += bond_tables(per, pper)
        L += rating_due_line(y, per)
        L += bond_item_sections(per, items)
        L += quiet_bond_table(per, items)
    L += sec("Invest Era", sections.get("ie")) if kind == "bond" else sec(
        "Сводка изменений Invest Era", sections.get("ie"))
    L += sec("Макро-контекст", sections.get("macro"))
    if sections.get("extra"):
        L += [sections["extra"].strip(), "", "---", ""]
    if kind == "bond":
        L += plan_vs_fact(y)
    L += conditions_block(y, per, kind, conds, sections.get(COND_RESOLUTIONS))
    if kind == "bond":
        L += plan_change(y)
    L += coverage_block(y, per, kind)
    if kind == "stock":
        L += ie_block(y)
    L += top_catalysts(per, kind)
    L += risks_block(y, sections.get("risks"))
    L += ["## Пункты действий" if kind == "stock" else "## Что делать с облигационной частью сейчас", "",
          sections["actions"].strip(), ""]
    L += caveats_block(y)
    src = collect_sources(y, per, kind, set(items))
    if src:
        L += ["## Источники", ""] + src
    text = "\n".join(L).rstrip() + "\n"
    return re.sub(r"\n{3,}", "\n\n", text)


def detect_kind(y: dict, forced: str | None) -> str:
    if forced:
        return forced
    t = str(y.get("type") or "")
    if "stock" in t:
        return "stock"
    if "bond" in t:
        return "bond"
    raise InputError(f"не удалось определить вид обзора по type=«{t}»; укажите --kind stock|bond")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Сборка MD недельного обзора из YAML + changes.md")
    ap.add_argument("--yaml", required=True)
    ap.add_argument("--changes", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--kind", choices=("stock", "bond"))
    ap.add_argument("--prior", help="прошлый обзор того же вида (YAML): цена/YTM «прошлое → текущее»")
    ap.add_argument("--conditions", help="JSON-вывод `apply_condition.py digest` (условия бумаг обзора на дату обзора): "
                                         "очередь условий строится из него")
    ap.add_argument("--strict-text", action="store_true",
                    help="код 3, если в тексте модели голый «Mode N» или код статуса гейта (по умолчанию — предупреждения)")
    ap.add_argument("--embed-notes", action="store_true",
                    help="записать week_note (что произошло / рекомендация / макро) из фрагментов бумаг в YAML обзора "
                         "(контракт A: карточка во вьюере читает его вместо обоснования)")
    a = ap.parse_args(argv)
    try:
        y = yaml.safe_load(Path(a.yaml).read_text(encoding="utf-8"))
        if not isinstance(y, dict):
            raise InputError(f"{a.yaml}: не YAML-словарь")
        ch = Path(a.changes).read_text(encoding="utf-8")
        kind = detect_kind(y, a.kind)
        per = y.get("per_stock" if kind == "stock" else "per_bond") or {}
        sections, items = parse_changes(ch, kind, set(per))
        conds = None
        if a.conditions:
            conds = json.loads(Path(a.conditions).read_text(encoding="utf-8"))
            if not isinstance(conds, dict) or not conds.get("ok") or not isinstance(conds.get("items"), list):
                raise InputError(f"{a.conditions}: ожидается JSON-вывод apply_condition.py digest (ok: true, items)")
        prior = None
        if a.prior:
            prior = yaml.safe_load(Path(a.prior).read_text(encoding="utf-8"))
            if not isinstance(prior, dict):
                raise InputError(f"{a.prior}: не YAML-словарь")
            if kind not in str(prior.get("type") or ""):
                raise InputError(f"--prior: type=«{prior.get('type')}» не соответствует виду обзора «{kind}»")
    except (InputError, OSError, yaml.YAMLError, ValueError) as e:
        sys.stderr.write(f"render_weekly_md.py: {e}\n")
        return 2
    md = render(y, sections, items, kind, prior, conds)
    embedded = None
    if a.embed_notes:
        embedded = embed_week_notes(y, items, kind)
        Path(a.yaml).write_text(dump_yaml(y), encoding="utf-8")
    warns = check_text(sections, items)
    if (conds is not None or kind == "stock") and stale_conditions(y, conds):
        warns.append(f"блок условий не этой недели: {STALE_HINT}")
    Path(a.output).write_text(md, encoding="utf-8")
    nb, cb = len(md.encode()), len(ch.encode())
    print(f"{a.output}: {nb / 1024:.1f} КБ; changes.md {cb / 1024:.1f} КБ ({cb / nb:.0%} отчёта пишет модель); "
          f"бумаг с фрагментом: {len(items)} из {len(per)}"
          + (f"; week_note записан в YAML у {embedded} бумаг" if embedded is not None else ""))
    for w in warns:
        sys.stderr.write(f"render_weekly_md.py: предупреждение: {w}\n")
    if warns:
        sys.stderr.write(f"render_weekly_md.py: предупреждений по тексту модели: {len(warns)}"
                         + ("; --strict-text → код 3\n" if a.strict_text else "\n"))
    return 3 if (warns and a.strict_text) else 0


if __name__ == "__main__":
    sys.exit(main())
