#!/usr/bin/env python3
"""
audit_candidates.py

Какие источники прогнозов ещё не аудированы, но их стоит аудировать.

Читает (только чтение):
- Claude-Memory/forecasts/*.md   — секции «Не аудированные источники» (таблицы FCA-отчётов);
- Claude-Memory/forecasts/*.yaml — conditional_on_scenarios.by_scenario.*.sources_used[]
  с trust_level None / отсутствует / UNAUDITED («сценарный слой»);
- Claude-Memory/INDEX.md         — «Track record summary» (уже аудированные).

Источник, чьё имя совпало с таблицей INDEX (после нормализации и словаря синонимов),
в кандидаты не попадает, а выводится отдельным блоком «уже аудированы с тех пор».

CLI:
    python3 audit_candidates.py [--memory PATH] [--min N] [--top N] [--json]

Только stdlib (yaml используется, если установлен; иначе — запасной разбор регулярками).
Код завершения 0.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

try:  # yaml необязателен
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None

DEFAULT_MEMORY = Path.home() / "Library/CloudStorage/SynologyDrive-home/Claude-Memory"

# Группы синонимов: любое имя из группы = один и тот же источник.
ALIASES: list[list[str]] = [
    ["ЦБ РФ", "Банк России", "CBR", "Bank of Russia"],
    ["Минэкономразвития", "МЭР", "MER"],
    ["Invest Era", "Инвест Эра"],
    ["ВТБ Мои Инвестиции", "VTB Mi"],
    ["БКС", "BKS"],
    ["Финам", "Finam"],
    ["Сбер", "SberCIB"],
    ["Альфа-Банк", "Альфа Банк", "Alfa Bank"],
    ["Т-Банк", "T-Bank", "Тинькофф"],
    ["Goldman Sachs", "Goldman"],
    ["JPMorgan", "JP Morgan", "J.P. Morgan"],
    ["Bank of America", "BofA"],
    ["Wells Fargo", "Wells Fargo II"],
    ["ЦМАКП", "ЦМАКП ИНП РАН"],
    ["Freedom Global", "Freedom Finance Global"],
    ["CFR", "Council on Foreign Relations"],
    ["ECFR", "European Council on Foreign Relations"],
]

NOISE_WORDS = ("investment research", "research")
NOT_FORECASTER_NAME = ("консенсус", "опрос", "агрегат", "мета", "consensus", " poll")
NOT_FORECASTER_REC = ("первоисточник", "агрегат", "аудит невозможен", "не применим")

DOMAIN_BY_NAME = [
    ("ru-sellside", ("альфа", "alfa", "т банк", "t bank", "тинькофф", "синара", "сбер", "вtб", "втб", "бкс",
                     "bks", "финам", "finam", "invest era", "инвест эра", "атон", "газпромбанк", "открытие",
                     "райффайзен", "совкомбанк", "vtb")),
    ("global-banks", ("goldman", "morgan", "jpmorgan", "citi", "hsbc", "ubs", "bank of america", "wells fargo",
                      "barclays", "deutsche", "nomura", "bloomberg", "westpac", "societe", "bnp", "commerzbank",
                      "ing research", "standard chartered", "macquarie")),
    ("commodity-agencies", ("eia", "iea", "opec", "опек", "world bank", "imf", "мвф", "crea", "platts", "argus",
                            "energy aspects", "rystad")),
    ("ru-macro", ("цб рф", "банк россии", "cbr", "bank of russia", "минэкономразвития", "мэр", "mer", "росстат",
                  "цмакп", "инп ран", "минфин", "вэб", "нифи", "ипэи", "hse", "вшэ")),
    ("geopolitics", ("institute", "chatham", "carnegie", "rand", "isw", "csis", "brookings", "cfr", "stratfor",
                     "rusi", "iiss", "valdai", "quincy", "think tank", "polymarket", "metaculus")),
    ("tech-ceo", ("semianalysis", "sequoia", "ceo", "nvidia", "openai", "anthropic", "a16z")),
]
DOMAIN_BY_TOPIC = [
    ("ru-macro", ("cbr", "inflation", "cpi", "usdrub", "usd-rub", "cnyrub", "cny-rub", "budget", "rates", "ruble")),
    ("commodity-agencies", ("brent", "urals", "oil", "gas")),
    ("geopolitics", ("war", "sanction", "ukraine", "iran", "russia-europe", "ru-west", "taiwan")),
    ("tech-ceo", ("ai-", "capex")),
    ("global-banks", ("xau", "gold", "fed", "recession")),
]


# --------------------------------------------------------------------------
# Нормализация имён
# --------------------------------------------------------------------------

def clean_display(name: str) -> str:
    """Убирает markdown-разметку и пробелы для показа."""
    s = re.sub(r"[*_`]+", "", name)
    s = re.sub(r"\s+", " ", s).strip(" \t.;:")
    return s


def normalize(name: str) -> str:
    """lower, без скобок, шумовых слов и пунктуации, схлопнутые пробелы."""
    s = clean_display(name).lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    for w in NOISE_WORDS:
        s = s.replace(w, " ")
    s = re.sub(r"[^\w\s]|_", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _contains_words(haystack: str, needle: str) -> bool:
    if not needle:
        return False
    return f" {needle} " in f" {haystack} "


_ALIAS_NORM: list[tuple[int, str]] = []  # (id группы, нормализованный алиас)
for _i, _grp in enumerate(ALIASES):
    for _a in _grp:
        _ALIAS_NORM.append((_i, normalize(_a)))


def alias_group(norm: str) -> int | None:
    """Группа синонимов для нормализованного имени (самое длинное совпадение по границам слов)."""
    best: tuple[int, int] | None = None
    for gid, al in _ALIAS_NORM:
        if _contains_words(norm, al) and (best is None or len(al) > best[1]):
            best = (gid, len(al))
    return best[0] if best else None


def _words_with_parens(name: str) -> str:
    """Имя в нижнем регистре со словами из скобок (для поиска синонимов)."""
    s = re.sub(r"[^\w\s]|_", " ", clean_display(name).lower(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def canon_key(name: str) -> str:
    n = normalize(name)
    g = alias_group(n)
    if g is None:
        g = alias_group(_words_with_parens(name))
    return f"alias:{g}" if g is not None else n


def names_match(a: str, b: str) -> bool:
    """Одно имя — то же, что другое (синоним, равенство или вхождение по словам)."""
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return False
    ga, gb = alias_group(na), alias_group(nb)
    if ga is not None and ga == gb:
        return True
    if na == nb:
        return True
    short, long_ = (na, nb) if len(na) <= len(nb) else (nb, na)
    return len(short) >= 4 and _contains_words(long_, short)


# --------------------------------------------------------------------------
# Разбор файлов
# --------------------------------------------------------------------------

DATE_RE = re.compile(r"^(?P<stem>.+)-(?P<date>\d{4}-\d{2}-\d{2})\.(?:md|yaml)$")
HEADING_RE = re.compile(r"^#{2,3}\s+Не аудированные источники", re.IGNORECASE)


def file_meta(path: Path) -> tuple[str, str]:
    """(тема из имени, дата из имени)."""
    m = DATE_RE.match(path.name)
    if not m:
        return path.stem, ""
    return m.group("stem"), m.group("date")


def split_cells(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def split_names(cell: str) -> list[str]:
    """Делит ячейку «A, B, C» по запятым вне скобок."""
    parts: list[str] = []
    depth, cur = 0, ""
    for ch in cell:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return [p for p in (clean_display(p) for p in parts) if p]


def is_forecaster(name: str, rec: str) -> bool:
    n, r = name.lower(), rec.lower()
    if any(w in n for w in NOT_FORECASTER_NAME):
        return False
    if any(w in r for w in NOT_FORECASTER_REC):
        return False
    return True


def parse_md_table_rows(text: str) -> list[tuple[str, str]]:
    """[(имя источника, рекомендация)] из всех секций «Не аудированные источники»."""
    rows: list[tuple[str, str]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if not HEADING_RE.match(lines[i].strip()):
            i += 1
            continue
        i += 1
        # ищем начало таблицы до следующего заголовка
        while i < len(lines) and not lines[i].lstrip().startswith("|"):
            if lines[i].lstrip().startswith("#"):
                break
            i += 1
        if i >= len(lines) or not lines[i].lstrip().startswith("|"):
            continue
        header = split_cells(lines[i])
        rec_idx = next((k for k, h in enumerate(header) if "рекоменд" in h.lower()), None)
        i += 1
        while i < len(lines) and lines[i].lstrip().startswith("|"):
            cells = split_cells(lines[i])
            i += 1
            if all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in cells if c) and any(cells):
                continue  # разделитель
            if not cells or not cells[0]:
                continue
            rec = cells[rec_idx] if rec_idx is not None and rec_idx < len(cells) else ""
            rec = re.sub(r"\s+", " ", re.sub(r"[*`]", "", rec)).strip()
            for nm in split_names(cells[0]):
                if is_forecaster(nm, rec):
                    rows.append((nm, rec))
    return rows


def md_frontmatter_value(text: str, key: str) -> str:
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return ""
    mm = re.search(rf"^{key}:\s*(.+)$", m.group(1), re.MULTILINE)
    return mm.group(1).strip().strip("\"'") if mm else ""


def parse_yaml_candidates(text: str) -> tuple[list[tuple[str, str]], str, str]:
    """([(source_id, trust)], topic, domain) для источников без trust_level."""
    data: Any = None
    if yaml is not None:
        try:
            data = yaml.safe_load(text)
        except Exception:
            data = None
    out: list[tuple[str, str]] = []
    topic = domain = ""
    if isinstance(data, dict):
        fc = data.get("forecast") if isinstance(data.get("forecast"), dict) else {}
        topic = str(fc.get("topic") or data.get("topic") or "")
        domain = str(fc.get("domain") or data.get("domain") or "")
        cos = data.get("conditional_on_scenarios")
        by = cos.get("by_scenario") if isinstance(cos, dict) else None
        if isinstance(by, dict):
            for sc in by.values():
                if not isinstance(sc, dict):
                    continue
                used = sc.get("sources_used")
                for s in used if isinstance(used, list) else []:
                    if isinstance(s, dict) and s.get("source_id"):
                        out.append((str(s["source_id"]), _trust_str(s.get("trust_level"))))
    else:  # запасной разбор без yaml
        mt = re.search(r"^\s*topic:\s*(\S+)", text, re.MULTILINE)
        md = re.search(r"^\s*domain:\s*(\S+)", text, re.MULTILINE)
        topic, domain = (mt.group(1) if mt else ""), (md.group(1) if md else "")
        for line in text.splitlines():
            if "source_id" not in line:
                continue
            sid = re.search(r"source_id:\s*([^\s,}]+)", line)
            tl = re.search(r"trust_level:\s*([^\s,}]+)", line)
            if sid:
                out.append((sid.group(1).strip("\"'"), _trust_str(tl.group(1) if tl else None)))
    cands = [(sid, tr) for sid, tr in out if tr in ("", "none", "null", "unaudited", "~")]
    return cands, topic, domain


def _trust_str(v: Any) -> str:
    return "" if v is None else str(v).strip().lower()


def parse_track_record(index_text: str) -> list[tuple[str, str]]:
    """[(имя источника, subfolder)] из таблицы «Track record summary»."""
    out: list[tuple[str, str]] = []
    m = re.search(r"^##\s+Track record summary\s*$", index_text, re.MULTILINE)
    if not m:
        return out
    for line in index_text[m.end():].splitlines():
        s = line.strip()
        if s.startswith("## "):
            break
        if not s.startswith("|"):
            continue
        cells = split_cells(s)
        if len(cells) < 2 or cells[0].lower() == "source" or re.fullmatch(r"-+", cells[0].replace(" ", "")):
            continue
        out.append((clean_display(cells[0]), cells[1]))
    return out


# --------------------------------------------------------------------------
# Домен
# --------------------------------------------------------------------------

def suggest_domain(name: str, topics: list[str], file_domains: list[str]) -> str:
    n = " " + normalize(name) + " "
    for dom, keys in DOMAIN_BY_NAME:
        if any((f' {k.strip()} ' in n) if len(k.strip()) <= 4 else (k in n) for k in keys):
            return dom
    tl = " ".join(topics).lower()
    for dom, keys in DOMAIN_BY_TOPIC:
        if any(k in tl for k in keys):
            return dom
    valid = {d for d, _ in DOMAIN_BY_NAME}
    doms = [d for d in file_domains if d in valid]
    if doms:
        return Counter(doms).most_common(1)[0][0]
    return "?"


# --------------------------------------------------------------------------
# Основная логика
# --------------------------------------------------------------------------

def collect(memory: Path) -> dict[str, Any]:
    fdir = memory / "forecasts"
    md_files = sorted(fdir.glob("*.md")) if fdir.is_dir() else []
    yaml_files = sorted(fdir.glob("*.yaml")) if fdir.is_dir() else []

    # упоминания: список dict(name, stem, date, topic, domain, rec, layer)
    mentions: list[dict[str, str]] = []
    for p in md_files:
        text = p.read_text(encoding="utf-8", errors="replace")
        rows = parse_md_table_rows(text)
        if not rows:
            continue
        stem, date = file_meta(p)
        topic = md_frontmatter_value(text, "topic") or stem
        domain = md_frontmatter_value(text, "domain")
        for nm, rec in rows:
            mentions.append(dict(name=nm, stem=stem + "|" + date, date=date, topic=topic,
                                 domain=domain, rec=rec, layer="md"))
    for p in yaml_files:
        text = p.read_text(encoding="utf-8", errors="replace")
        cands, topic, domain = parse_yaml_candidates(text)
        if not cands:
            continue
        stem, date = file_meta(p)
        for sid, tr in cands:
            nm = re.sub(r"[-_]+", " ", sid).strip()
            rec = "сценарный слой: trust_level " + (tr if tr else "не задан")
            mentions.append(dict(name=nm, stem=stem + "|" + date, date=date, topic=topic or stem,
                                 domain=domain, rec=rec, layer="yaml"))

    track = []
    idx = memory / "INDEX.md"
    if idx.is_file():
        track = parse_track_record(idx.read_text(encoding="utf-8", errors="replace"))
    # Профили domains/<домен>/*.md (frontmatter `source:`) — то же множество аудированных, что показывает
    # вьюер в «Доверии к источникам»; в Track record summary бывают пропуски (МЭР на 27.10.2026)
    seen = {canon_key(n) for n, _ in track}
    dom_root = memory / "domains"
    if dom_root.is_dir():
        for prof in sorted(dom_root.glob("*/*.md")):
            if prof.name.lower() == "index.md":
                continue
            src = md_frontmatter_value(prof.read_text(encoding="utf-8", errors="replace"), "source")
            if src and canon_key(src) not in seen:
                seen.add(canon_key(src))
                track.append((clean_display(src), "domains/" + prof.parent.name))
    return dict(mentions=mentions, track=track, n_md=len(md_files), n_yaml=len(yaml_files))


def build(memory: Path, min_mentions: int = 1, top: int | None = None, at_least: int | None = 10) -> dict[str, Any]:
    raw = collect(memory)
    track: list[tuple[str, str]] = raw["track"]

    groups: dict[str, list[dict[str, str]]] = {}
    for m in raw["mentions"]:
        groups.setdefault(canon_key(m["name"]), []).append(m)

    candidates: list[dict[str, Any]] = []
    audited: list[dict[str, Any]] = []
    for key, ms in groups.items():
        names = Counter(m["name"] for m in ms)
        display = names.most_common(1)[0][0]
        stems = {m["stem"] for m in ms}
        topics: list[str] = []
        for m in sorted(ms, key=lambda x: x["date"], reverse=True):
            if m["topic"] not in topics:
                topics.append(m["topic"])
        last = max(ms, key=lambda x: (x["date"], x["layer"] == "md"))
        dates = sorted({m["date"] for m in ms if m["date"]})
        matched = next((t for t, _ in track if names_match(display, t) or any(names_match(n, t) for n in names)), None)
        rec = dict(
            source=display,
            mentions=len(stems),
            topics=topics[:3],
            last=last["date"],
            first=dates[0] if dates else "",
            recommendation=last["rec"],
            domain=suggest_domain(display, topics, [m["domain"] for m in ms]),
            scenario_layer_only=all(m["layer"] == "yaml" for m in ms),
        )
        if matched:
            rec["audited_as"] = matched
            audited.append(rec)
        else:
            candidates.append(rec)

    def order(r: dict[str, Any]):
        return (-r["mentions"], _neg_date(r["last"]), r["source"].lower())

    candidates.sort(key=order)
    audited.sort(key=order)
    candidates = [c for c in candidates if c["mentions"] >= min_mentions]
    if top is not None:
        candidates = candidates[:top]
    threshold = shortlist_threshold(candidates, at_least) if at_least else 1
    shortlist = [c for c in candidates if c["mentions"] >= threshold]
    rest = [c for c in candidates if c["mentions"] < threshold]
    return dict(read=dict(md=raw["n_md"], yaml=raw["n_yaml"], index_sources=len(track)),
                threshold=threshold, candidates=shortlist, rest=rest, already_audited=audited)


def shortlist_threshold(candidates: list[dict[str, Any]], at_least: int = 10) -> int:
    """Порог упоминаний для короткого списка (правило владельца 27.10.2026): берём источники с X и более
    упоминаниями, где X — наибольшее число, при котором в списке хотя бы `at_least` источников; все источники
    с одинаковым числом упоминаний идут целиком. Кандидатов меньше `at_least` → порог 1 (все)."""
    counts = sorted({int(c.get("mentions") or 0) for c in candidates}, reverse=True)
    acc = 0
    for x in counts:
        acc += sum(1 for c in candidates if int(c.get("mentions") or 0) == x)
        if acc >= at_least:
            return x
    return counts[-1] if counts else 1


def _neg_date(d: str) -> tuple[int, ...]:
    """Ключ сортировки «поздняя дата раньше»."""
    return tuple(-int(x) for x in d.split("-")) if d else (0,)


def esc(s: str, limit: int | None = None) -> str:
    s = re.sub(r"\s+", " ", s).replace("|", "/").strip()
    if limit and len(s) > limit:
        s = s[: limit - 1].rstrip() + "…"
    return s


def render_markdown(res: dict[str, Any]) -> str:
    r = res["read"]
    out = [f"# Кандидаты на аудит источников прогнозов", "",
           f"Прочитано: md — {r['md']}, yaml — {r['yaml']}; источников в Track record summary — {r['index_sources']}.", "",
           "| Источник | Упоминаний | Темы (до 3) | Последнее | Рекомендация (последняя) | Домен? |",
           "|---|---|---|---|---|---|"]
    for c in res["candidates"]:
        name = esc(c["source"]) + (" (сценарный слой)" if c["scenario_layer_only"] else "")
        out.append(f"| {name} | {c['mentions']} | {esc(', '.join(c['topics']))} | {c['last']} | "
                   f"{esc(c['recommendation'], 110)} | {c['domain']} |")
    if not res["candidates"]:
        out.append("| — | | | | | |")
    if res.get("rest"):
        out += ["", f"Порог короткого списка — {res['threshold']} упоминаний (хотя бы 10 источников, группа по числу упоминаний целиком). "
                    f"Остальные {len(res['rest'])}: " + "; ".join(f"{esc(c['source'])} ({c['mentions']})" for c in res["rest"])]
    out += ["", "Порядок: `/forecast-collector Собери прогнозы <источник> для аудита` → `/retrospective-forecast-audit`.", "", "## Уже аудированы с тех пор", ""]
    if res["already_audited"]:
        for a in res["already_audited"]:
            span = a["first"] if a["first"] == a["last"] else f"{a['first']} … {a['last']}"
            out.append(f"- {esc(a['source'])} → {esc(a['audited_as'])}: упоминаний {a['mentions']} ({span})")
    else:
        out.append("Нет.")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Кандидаты на аудит источников прогнозов")
    ap.add_argument("--memory", default=str(DEFAULT_MEMORY), help="путь к Claude-Memory")
    ap.add_argument("--min", type=int, default=1, dest="min_mentions", help="минимум упоминаний")
    ap.add_argument("--top", type=int, default=None, help="показать первые N кандидатов")
    ap.add_argument("--at-least", type=int, default=10, dest="at_least",
                    help="короткий список: все источники с X+ упоминаниями, X — чтобы вышло хотя бы N (0 — без порога)")
    ap.add_argument("--json", action="store_true", help="вывод в JSON")
    args = ap.parse_args(argv)
    res = build(Path(args.memory).expanduser(), args.min_mentions, args.top, args.at_least or None)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(render_markdown(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
