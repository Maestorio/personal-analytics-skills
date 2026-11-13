#!/usr/bin/env python3
"""
prior_digest.py — короткая выжимка прошлого weekly-review вместо чтения его целиком (RPA-24).

Зачем. 16.10.2026 прошлый MD обзора (67–86 КБ) читался целиком, а у облигаций дважды; вместе с
YAML (200–265 КБ) это главный вход контекста режимов 1/2. После RPA-23 перенос делает
`carry_over_weekly.py`, но модели всё равно нужно ВИДЕТЬ каждый прошлый вердикт, чтобы
пересмотреть его по фактам недели, а не унаследовать молча. Выжимка — таблица на 5–10 КБ:
бумага, вердикт, уверенность, первая фраза обоснования, рейтинг (облигации), условия по бумаге,
катализаторы, чьё окно наступает в ближайшие N дней или уже прошло.

С `--decisions` и `--reports-dir` — ещё блоки: гейт каждой акции словами, вычисленный из её последнего
решения (`Portfolio/decisions/`, модуль (б) `last_word` через обёртку `decisions_read.gate`: статус — проекция
вердикта, срок — `review_by`, IPO-пауза — по справочнику бумаг корня; строки обзоров в гейт не передаются — бумага
считается держимой); разборы бумаг после прошлого
обзора с решениями, записанными из них; устаревшие гейты (срок решения прошёл) с последним отчётом по бумаге и
назначенным разбором.

Условия (`--conditions Portfolio/conditions.yaml`, `conditions@2`; состояние — `conditions-state.json` рядом)
читаются модулем (а) `conditions_merge`: действующие условия своего класса со статусом, вердиктами «пока ждём → при
срабатывании», первой фразой `note` и пометкой «решение владельца» для `created_by: owner`: 26.10 обзор переспросил срез OZON, хотя 16.10 владелец решил «держим» и завёл
`ozon-below-1610`, — в выжимке было видно только «price_below 3250». С `--macro-dir` — последний
макроснимок (`macro-snapshots/ru-*.md`) с датой: 26.10 обзор написал «инфляция не обновлялась,
валюта/нефть не собирались» при снимке от 21.10 (инфляция 7,15%, USD/RUB −2,5%, Brent $108).

CLI:
  python3 prior_digest.py --prior weekly-review-bond-2026-10-08.yaml \
      [--conditions Portfolio/conditions.yaml] [--decisions Portfolio/decisions] [--reports-dir Portfolio/reports] \
      [--macro-dir Claude-Memory/macro-snapshots] [--today 2026-10-16] [--days 14] [--basis-chars 140]
Выход — Markdown в stdout. Полный прошлый MD — только точечно, по бумаге с событием.
Зависимости: stdlib + PyYAML; gate_status_ru, codelists, conditions_merge, decisions_read, last_word (канон
_shared-references/, в бандле — рядом).
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, timedelta
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("prior_digest.py требует PyYAML\n")
    sys.exit(2)

# gate_status_ru — канон _shared-references/ (в бандле pack.sh кладёт его в scripts/ рядом).
_SHARED_DIR = Path(__file__).resolve().parents[3] / "_shared-references"
if _SHARED_DIR.is_dir() and str(_SHARED_DIR) not in sys.path:
    sys.path.append(str(_SHARED_DIR))
from gate_status_ru import label as gate_label  # noqa: E402
import codelists  # noqa: E402
import conditions_merge as cm  # noqa: E402
import decisions_read as dr  # noqa: E402
import rating_check as rc  # noqa: E402


# Вводная фраза о движении цены («Цена 80,96 → 80,78, YTM …») — не причина вердикта: пропускается.
_PRICE_LEAD = re.compile(r"^(Цена|YTM|Курс)\b[^.]*→")


def _first_sentence(text, limit: int, skip_price: bool = False) -> str:
    if not isinstance(text, str):
        return "—"
    t = " ".join(text.split())
    parts = re.split(r"(?<=[.!?;])\s+(?=[А-ЯA-Z0-9«])", t)
    if skip_price:
        rest = [p for p in parts if not _PRICE_LEAD.match(p)]
        parts = rest or parts
    s = parts[0]
    return s if len(s) <= limit else s[:limit - 1].rstrip() + "…"


def _cell(s) -> str:
    return str(s).replace("|", "/").replace("\n", " ")


def _date_end(c: dict):
    """Конец окна катализатора: event_date или последняя дата в date_window (YYYY-MM-DD / YYYY-MM)."""
    for key in ("event_date", "date_window"):
        v = c.get(key)
        if isinstance(v, date):
            return v
        if not isinstance(v, str):
            continue
        found = re.findall(r"\d{4}-\d{2}(?:-\d{2})?", v)
        if not found:
            continue
        last = found[-1]
        try:
            if len(last) == 10:
                return date.fromisoformat(last)
            y, m = int(last[:4]), int(last[5:7])
            return date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
        except ValueError:
            continue
    return None


_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")


def _rating_due_block(items: dict, today: date) -> list[str]:
    """Блок «Рейтинг пора перепроверить» (правило — rating_check); пусто — блока нет."""
    due = rc.bonds_due_for_rating_check(items, today)
    if not due:
        return []
    lines = ["## Рейтинг пора перепроверить", "",
             f"Дата проверки рейтинга пуста или старше {rc.RATING_CHECK_MAX_AGE_DAYS} дн. (корп-бумаги, без ОФЗ): "
             "сверить с первоисточником агентства и поставить `credit_rating_checked_at`.", ""]
    by_issuer: dict = {}
    for d in due:
        by_issuer.setdefault(d["issuer"] or d["name"] or d["key"], []).append(d)
    for issuer, ds in by_issuer.items():
        ag = ds[0]["credit_rating_agency"]
        rating = ds[0]["credit_rating"] or "рейтинга нет"
        rating += f" ({ag})" if ag and ag not in str(rating) else ""
        chk = ds[0]["checked_at"]
        chk = str(chk) if chk else "не записана"
        lines.append(f"- {issuer}: {', '.join(d['key'] for d in ds)} — {rating}; последняя проверка: {chk}")
    lines.append("")
    return lines


def digest(prior: dict, conditions: list[dict] | None, today: date, days: int, basis_chars: int,
           gates: dict | None = None, reports: list[dict] | None = None,
           macro: dict | None = None) -> str:
    """conditions — действующие строки модуля (а) (`load_conditions`), у строки поле `created_by` из определения;
    gates — {ключ акции: decisions_read.gate(...) — гейт модуля (б)} (`load_gates`); reports — `load_reports`."""
    kind = "bond" if "per_bond" in prior else "stock"
    gates = (gates or {}) if kind == "stock" else {}
    items = prior.get("per_bond") or prior.get("per_stock") or {}
    conds_by = {}
    for c in conditions or []:
        # условия своего класса: у облигаций ключ — ISIN, у акций — тикер (обзор акций не тащит 10 облигационных)
        if c.get("active") and (c.get("key_kind") == "isin") == (kind == "bond"):
            conds_by.setdefault(c.get("key"), []).append(c)

    horizon = today + timedelta(days=days)
    lines = [f"# Выжимка обзора {prior.get('review_date')} ({'облигации' if kind == 'bond' else 'акции'}, "
             f"{len(items)} бумаг) — на {today.isoformat()}", "",
             "Каждый вердикт ниже — решение ПРОШЛОЙ недели: пересмотреть по фактам этой недели.", ""]
    counts = {}
    for e in items.values():
        v = (e or {}).get("advisor_verdict")
        counts[v] = counts.get(v, 0) + 1
    lines.append("Вердикты: " + ", ".join(f"{k} {n}" for k, n in sorted(counts.items(), key=lambda x: -x[1])))
    lines.append("")
    head = ("| Бумага | Вердикт | Ув. | " + ("Рейтинг | " if kind == "bond" else "")
            + ("Гейт | " if gates else "") + "Обоснование (1 фраза) |")
    lines += [head, "|" + "---|" * (head.count("|") - 1)]
    events = []
    for key, e in items.items():
        e = e or {}
        name = e.get("name") or e.get("sector_ru") or ""
        label = f"{key} {name}".strip() if kind == "bond" else key
        row = [label, e.get("advisor_verdict", "—"), e.get("advisor_verdict_confidence", "—")]
        if kind == "bond":
            agency = e.get("credit_rating_agency")
            row.append(f"{e.get('credit_rating') or '—'}" + (f" ({agency})" if agency and agency not in str(e.get('credit_rating')) else ""))
        if gates:
            g = gates.get(key)
            row.append(gate_label(g["status"]) if g else "нет решения")
        row.append(_first_sentence(e.get("advisor_verdict_basis"), basis_chars, skip_price=True))
        lines.append("| " + " | ".join(_cell(x) for x in row) + " |")
        for c in e.get("catalyst") or []:
            if not isinstance(c, dict):
                continue
            end = _date_end(c)
            if end is not None and end <= horizon:
                state = "ПРОШЛО — закрыть или обновить" if end < today else f"до {end.isoformat()}"
                events.append(f"- {label}: `{c.get('id')}` — {_first_sentence(c.get('trigger'), 90)} ({state})")
    lines.append("")
    if events:
        lines += [f"## Катализаторы с окном до {horizon.isoformat()} или уже прошедшие", ""] + events + [""]
    if kind == "bond":
        lines += _rating_due_block(items, today)
    keys = set(items)
    cond_lines = []
    for t, cs in conds_by.items():
        for c in cs:
            trig = c.get("trigger") or {}
            mark = "" if t in keys else " (бумаги нет в прошлом обзоре)"
            note = c.get("note")
            who = f" · решение владельца {str(c.get('created_at'))[:10]}" if c.get("created_by") == "owner" else ""
            st = "СРАБОТАЛО — ждёт владельца, нужна резолюция" if c.get("waits_owner") else \
                ("сработало, отложено" if c.get("status") == cm.FIRED else "ждёт")
            cond_lines.append(f"- {t}{mark}: `{c.get('id')}` — {trig.get('type')} {trig.get('value')}; {st}; "
                              f"сейчас {c.get('verdict_now') or '—'}, при срабатывании "
                              f"{c.get('verdict_on_trigger') or '—'}{who}"
                              + (f" — {_first_sentence(note, 160)}" if isinstance(note, str) and note.strip() else ""))
    if cond_lines:
        lines += ["## Действующие условия", "",
                  "«Решение владельца» — уже принято: не переспрашивать, а сослаться.", ""] + sorted(cond_lines) + [""]
    if macro is not None:
        lines += _macro_block(macro, today)
    if reports is not None:
        lines += _reports_block(reports, gates, str(prior.get("review_date"))[:10], today, set(items), kind,
                                conditions)
    risks = prior.get("key_risks") or []
    if isinstance(risks, list) and risks:
        lines += ["## Ключевые риски прошлого обзора", ""]
        for r in risks[:8]:
            txt = r.get("risk") or r.get("description") or r.get("id") if isinstance(r, dict) else r
            lines.append(f"- {_first_sentence(txt, 160)}")
        lines.append("")
    return "\n".join(lines)


# ───────────────────────── разборы бумаг, решения и гейты ─────────────────────────

_REPORT_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})-")
# Отчёты разбора: разбор бумаги (Mode 4), ребалансировка (Mode 3) и оценка качества (Mode 8; legacy-код и целевой).
# Коды — из кодлиста report_kind (выбор подмножества — правило этого скрипта; неизвестный код роняет импорт).
_REVIEW_KINDS = {k for k in ("single_analysis", "tactical_rebalance", "quality_review", "stock_quality")
                 if k in codelists.codes("report_kind")}
assert len(_REVIEW_KINDS) == 4, "prior_digest: kind отчёта разбора нет в кодлисте report_kind"


def load_reports(reports_dir: str, since: date, decisions: list[dict] | None = None) -> list[dict]:
    """Отчёты Portfolio/reports/ с датой в имени ≥ since: kind, тикеры, вывод (шапка) и решения, записанные
    из отчёта (`source.doc` решения = путь отчёта). Тело отчёта не читается."""
    by_doc: dict[str, list[dict]] = {}
    for d in decisions or []:
        doc = (d.get("source") or {}).get("doc")
        if doc:
            by_doc.setdefault(Path(doc).name, []).append(d)
    out = []
    for p in sorted(Path(reports_dir).glob("*.md")):
        m = _REPORT_DATE.match(p.name)
        if not m:
            continue
        try:
            d = date.fromisoformat(m[1])
        except ValueError:
            continue
        if d < since:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        front = {}
        if text.startswith("---"):
            end = text.find("\n---", 3)
            if end > 0:
                try:
                    front = yaml.safe_load(text[3:end]) or {}
                except yaml.YAMLError:
                    front = {}
        if front.get("kind") not in _REVIEW_KINDS:
            continue
        tk = front.get("tickers") or []
        out.append({"file": p.name, "date": d, "kind": front.get("kind"),
                    "tickers": [tk] if isinstance(tk, str) else tk,
                    "summary": front.get("summary"), "recorded_decisions": by_doc.get(p.name, [])})
    return out


def load_conditions(path: str, today: date) -> list[dict]:
    """Действующие условия модулем (а): conditions.yaml (conditions@2) + conditions-state.json рядом.
    К строке добавлено `created_by` последней версии определения (связь по id)."""
    doc = cm.load_yaml(path) or {}
    if not isinstance(doc, dict) or doc.get("schema_version") != "conditions@2":
        raise ValueError(f"{path}: нужен формат conditions@2, получено {doc.get('schema_version') if isinstance(doc, dict) else doc!r}")
    defs = doc.get("conditions") or []
    state_path = Path(path).with_name("conditions-state.json")
    state = {"events": []}
    if state_path.is_file():
        import json
        state = json.loads(state_path.read_text(encoding="utf-8"))
    last: dict[str, dict] = {}
    for c in defs:
        if isinstance(c, dict) and (c.get("id") not in last or c.get("version", 0) > last[c["id"]].get("version", 0)):
            last[c["id"]] = c
    rows = cm.select(cm.merge(defs, state, today.isoformat()), only_active=True)
    for r in rows:
        r["created_by"] = (last.get(r["id"]) or {}).get("created_by")
        r["created_at"] = (last.get(r["id"]) or {}).get("created_at")
    return rows


def load_gates(decisions_dir: str, today: date) -> tuple[dict, list[dict]]:
    """({ключ акции: гейт карточки модуля (б) по решениям ключа}, все решения); обёртка — decisions_read.gate."""
    items, _invalid = dr.load_dir(decisions_dir)
    root = str(Path(decisions_dir).resolve().parents[1])
    types, attrs = dr.key_types(root), dr.load_attrs(root)
    gates = {k: dr.gate(d, today.isoformat(), decisions=dr.for_key(items, k), attrs=attrs)
             for k, d in dr.latest_by_key(items).items()
             if dr.key_type(types, k) in ("stock", None) and not _ISIN.match(k)}
    return gates, items


# ───────────────────────── макроснимок ─────────────────────────

_MACRO_NAME = re.compile(r"^ru-(\d{4}-\d{2}-\d{2})\.md$")
MACRO_FRESH_DAYS = 7


def load_macro(macro_dir: str) -> dict:
    """Последний macro-snapshots/ru-YYYY-MM-DD.md: дата и строки «индикатор — текущее значение»."""
    files = sorted((m[1], p) for p in Path(macro_dir).glob("ru-*.md") if (m := _MACRO_NAME.match(p.name)))
    if not files:
        return {"date": None, "file": None, "rows": []}
    d, p = files[-1]
    rows, in_table = [], False
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("| Индикатор"):
            in_table = True
            continue
        if in_table:
            if not line.startswith("|"):
                break
            cells = [x.strip() for x in line.strip("|").split("|")]
            if len(cells) >= 2 and not set(cells[0]) <= set("-: "):
                rows.append((cells[0], cells[1]))
    return {"date": date.fromisoformat(d), "file": p.name, "rows": rows}


def _macro_block(macro: dict, today: date) -> list[str]:
    if not macro.get("date"):
        return ["## Макроснимок", "", "Снимков нет — запустить /macro-ru-watcher или оговорить в caveats.", ""]
    age = (today - macro["date"]).days
    head = f"## Макроснимок {macro['date'].strftime('%d.%m')} (`{macro['file']}`, {age} дн.)"
    lines = [head, ""]
    if age > MACRO_FRESH_DAYS:
        lines += [f"Старше {MACRO_FRESH_DAYS} дней — обновить /macro-ru-watcher или писать «данные на ДД.ММ».", ""]
    lines += [f"- {k}: {v}" for k, v in macro["rows"]] + [""]
    return lines


def aging_gates(gates: dict, reports: list[dict], today: date, keys: set,
                conditions: list[dict] | None = None) -> list[dict]:
    """Устаревшие гейты бумаг обзора (срок последнего решения прошёл) + последний отчёт, где бумага упомянута, и
    назначенный разбор — действующее условие на бумагу с `kind: review` или `action_code: run_analysis`: тогда разбор
    уже назначен и повторно не предлагается."""
    planned = {}
    for c in conditions or []:
        if c.get("active") and (c.get("kind") == "review" or c.get("action_code") == "run_analysis"):
            planned.setdefault(c.get("key"), c)
    out = []
    for t in sorted(keys):
        g = gates.get(t)
        if not g or not g.get("expired"):
            continue
        last = None
        for r in reports:
            if t in [str(x) for x in r["tickers"]] and (last is None or r["date"] >= last["date"]):
                last = r
        out.append({"ticker": t, "status": g["status"], "valid_until": g["expires_on"], "report": last,
                    "planned": planned.get(t)})
    return out


def _reports_block(reports: list[dict], gates: dict, prior_date: str, today: date | None = None,
                   keys: set | None = None, kind: str = "stock", conditions: list[dict] | None = None) -> list[str]:
    lines = []
    # отчёты своего класса: бумага обзора в тикерах отчёта или тикер того же вида (ISIN у облигаций)
    reports = [r for r in reports if (keys and set(map(str, r["tickers"])) & keys)
               or any(bool(_ISIN.match(str(t))) == (kind == "bond") for t in r["tickers"])]
    since = [r for r in reports if r["date"].isoformat() >= prior_date]
    if since:
        lines += [f"## Разборы бумаг после прошлого обзора ({prior_date})", "",
                  "Вывод разбора — исходная точка вердикта по этим бумагам; не переоценивать заново, "
                  "полный отчёт читать точечно.", ""]
        for r in since:
            tick = ", ".join(map(str, r["tickers"])) or "—"
            dec = "; ".join(f"{d['key']} — {codelists.ru('verdict', d['verdict'])}" for d in r.get("recorded_decisions") or [])
            lines.append(f"- {r['date'].strftime('%d.%m')} · {tick} · `{r['file']}` — "
                         f"{_first_sentence(r.get('summary'), 220)}"
                         + (f" Решения записаны: {dec}." if dec else " Решений из отчёта не записано."))
        lines.append("")
    aging = aging_gates(gates, reports, today, keys or set(), conditions) if today else []
    if aging:
        lines += ["## Срок решения вышел — нужен разбор", "",
                  "Писать «Срок решения по X вышел ДД.ММ — докупка закрыта до нового разбора» и предлагать разбор "
                  "бумаги (`/ru-portfolio-advisor Разбери X`). Переподтверждение без разбора не предлагать: решение "
                  "владельца без разбора докупку не открывает (модуль (б), правило 9а). Отчёт ниже — опора для разбора.", ""]
        for a in aging:
            vu = f", срок истёк {a['valid_until'][8:10]}.{a['valid_until'][5:7]}" if a["valid_until"] else ""
            r = a["report"]
            ref = (f"последний отчёт с бумагой — {r['date'].strftime('%d.%m')} (`{r['file']}`, {r['kind'] or '—'})"
                   if r else "отчётов с бумагой за 60 дней нет — нужен разбор бумаги")
            pl = a.get("planned")
            if pl:
                when = (pl.get("trigger") or {}).get("value")
                ref = f"разбор уже назначен — условие `{pl.get('id')}` (срок {when}); не переспрашивать, сослаться"
            lines.append(f"- **{a['ticker']}**: «{gate_label(a['status'])}»{vu}; {ref}")
        lines.append("")
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prior", required=True)
    ap.add_argument("--conditions", help="Portfolio/conditions.yaml (conditions@2; состояние — conditions-state.json рядом)")
    ap.add_argument("--decisions", dest="decisions_dir", help="Portfolio/decisions — гейт акций из последнего решения (временно до модуля (б))")
    ap.add_argument("--reports-dir", help="Portfolio/reports — разборы бумаг после прошлого обзора")
    ap.add_argument("--macro-dir", help="Claude-Memory/macro-snapshots — последний макроснимок с датой")
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--basis-chars", type=int, default=160)
    a = ap.parse_args(argv)
    with open(a.prior, encoding="utf-8") as f:
        prior = yaml.safe_load(f)
    if not isinstance(prior, dict) or not ("per_bond" in prior or "per_stock" in prior):
        print("ERROR: ожидается weekly-review YAML (per_stock / per_bond)", file=sys.stderr)
        return 2
    today = date.fromisoformat(a.today)
    conds = load_conditions(a.conditions, today) if a.conditions else None
    gates, decisions = load_gates(a.decisions_dir, today) if a.decisions_dir else (None, None)
    reports = None
    if a.reports_dir:
        # 60 дней: решение по устаревшему гейту бывает старше прошлого обзора; блок «Разборы после
        # прошлого обзора» сам отбирает отчёты с даты прошлого обзора.
        reports = load_reports(a.reports_dir, today - timedelta(days=60), decisions)
    macro = load_macro(a.macro_dir) if a.macro_dir else None
    print(digest(prior, conds, today, a.days, a.basis_chars, gates, reports, macro))
    return 0


if __name__ == "__main__":
    sys.exit(main())
