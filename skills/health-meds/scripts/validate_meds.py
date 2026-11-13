#!/usr/bin/env python3
"""
validate_meds.py

Детерминированный валидатор и merge-движок аптечки для скилла health-meds.

Контракт `health-meds@1` — ПЛОСКИЙ (см. живой Claude-Memory/Health/meds.json).
Разделения `user`/`ref` из health-plan.md §1.5 в природе не существует: страница
пишет файл целиком и её форма правки включает поля справки. Поэтому безопасность
здесь держится не на непересекающихся пространствах имён, а на двух правилах:

  1. merge_ref() НИКОГДА не пишет в USER_FIELDS — только в REF_FIELDS;
  2. непустое ref-поле БЕЗ ref_meta считается заполненным рукой и не
     перетирается (нужен явный overwrite_manual).

Провенанс живёт в аддитивном блоке `ref_meta` (страница его не рисует, но
сохраняет: med-save делает Object.assign поверх записи).

    "ref_meta": {
      "filled_at": "2026-07-17",
      "confidence": "high|medium|low",
      "fields_filled": ["inn", "class"],
      "sources": [{"title": "…", "url": "…", "fetched": "2026-07-17"}]
    }

Главный инвариант: заявленное в fields_filled ⇒ непустые sources.
Факт о лекарстве без источника — не факт.

CLI:
    python3 validate_meds.py validate --meds meds.json [--labs labs.json] [--pretty]
    python3 validate_meds.py merge --meds meds.json --enrich enrich.json \
            [--labs labs.json] [--apply] [--overwrite-manual]

merge по умолчанию — dry-run: печатает отчёт и не трогает файл. Запись (--apply)
происходит ТОЛЬКО при отсутствии blocking-issue у результата.

Без внешних зависимостей.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import date
from typing import Any

# Общие модули — канон в _shared-references/; в упакованном .skill — в своей scripts/ (pack.sh кладёт по импорту).
_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (_HERE, os.path.normpath(os.path.join(_HERE, "..", "..", "..", "_shared-references"))):
    if _cand not in sys.path:
        sys.path.insert(0, _cand)
import hub_settings  # noqa: E402

SCHEMA = "health-meds@1"

# Поля справки — их заполняет скилл.
REF_FIELDS = ("inn", "class", "for", "indications", "interactions", "affects",
              "affects_strength", "group")

# Назначение — блок, в который лекарство попадает в списке аптечки. Словарь
# ЗАКРЫТ: по свободному тексту `class`/`for` группировать нельзя, на полусотне
# препаратов вышло бы полсотни групп по одной позиции.
# ⚠ SYNC: значения обязаны совпадать с MED_GROUPS в tools/health.html — по ним
# страница раскладывает список и подписывает блоки. Правится в двух местах.
MED_GROUPS = ("cold", "throat", "cough", "pain", "gi", "allergy", "skin",
              "eye", "abx", "heart", "sleep", "other")
# Поля человека — скилл не трогает их никогда.
# `archived` — третье состояние аптечки: лекарство кончилось/выброшено. Запись
# не удаляется, а прячется: она остаётся образцом для повторного добавления
# (страница подставляет из неё справку, кроме срока годности).
USER_FIELDS = ("name", "dose", "regimen", "timing", "form", "taking",
               "prescribedBy", "expiry", "notes", "archived")

CONFIDENCE = ("high", "medium", "low")

# Срок годности: только год и месяц. Полная дата тут — ошибка, а не «точнее»:
# на упаковке дня нет, и страница рисует/выбирает именно месяц.
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

# Сила влияния на биомаркер. Без неё карточка врёт равенством: у статина
# ЛПНП падает на десятки процентов, а HbA1c сдвигается на десятые доли —
# и то и другое рисовалось одинаковым чипом.
STRENGTH = ("strong", "moderate", "weak")

# Тир источника определяется по домену. Списки НЕ полные и полными не будут:
# инструкция производителя живёт на его же сайте (akrikhin.ru/…/Diakarb.pdf) —
# это тир 1, но домен заранее не известен. Поэтому правило асимметрично:
# блокируем только когда ВСЕ источники заведомо вторичные, а незнакомый домен
# трактуем в пользу записи.
TIER1_HOSTS = ("grls.rosminzdrav.ru", "dailymed.nlm.nih.gov", "ema.europa.eu",
               "medicines.org.uk", "accessdata.fda.gov")
TIER2_HOSTS = ("rlsnet.ru", "vidal.ru", "drugs.com", "medlineplus.gov",
               "webmd.com", "rxlist.com")


def _issue(severity: str, category: str, message: str, med_id: str | None = None) -> dict:
    out = {"severity": severity, "category": category, "message": message}
    if med_id is not None:
        out["id"] = med_id
    return out


def _is_iso_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _is_filled(med: dict, field: str) -> bool:
    """Непустое ref-поле. affects — список, affects_strength — словарь, прочие — строки."""
    value = med.get(field)
    if field == "affects":
        return isinstance(value, list) and len(value) > 0
    if field == "affects_strength":
        return isinstance(value, dict) and len(value) > 0
    return isinstance(value, str) and value.strip() != ""


def _host(url: Any) -> str:
    m = re.match(r"^https?://(?:www\.)?([^/?#]+)", url if isinstance(url, str) else "")
    return m.group(1).lower() if m else ""


def source_tier(url: Any) -> int:
    """1 — первичка, 2 — авторитетная вторичка, 0 — домен неизвестен."""
    h = _host(url)
    if not h:
        return 0
    for t in TIER1_HOSTS:
        if h == t or h.endswith("." + t):
            return 1
    for t in TIER2_HOSTS:
        if h == t or h.endswith("." + t):
            return 2
    return 0


def load_biomarker_ids(labs: dict) -> set[str]:
    """id биомаркеров из labs.json — цель ссылок meds[].affects."""
    out = set()
    for b in labs.get("biomarkers", []):
        if isinstance(b, dict) and isinstance(b.get("id"), str):
            out.add(b["id"])
    return out


# ─────────────────────────── валидация ───────────────────────────

def validate_meds(doc: Any, biomarker_ids: set[str] | None = None) -> list[dict]:
    """Проверяет meds.json. → плоский список issues (blocking / warning / info)."""
    issues: list[dict] = []

    if not isinstance(doc, dict):
        return [_issue("blocking", "root", "корень meds.json должен быть объектом")]
    if doc.get("schema") != SCHEMA:
        issues.append(_issue("blocking", "schema",
                             f"schema должна быть {SCHEMA!r}, получено {doc.get('schema')!r}"))
    if "updated" in doc and not _is_iso_date(doc.get("updated")):
        issues.append(_issue("warning", "updated",
                             f"updated не ISO-дата: {doc.get('updated')!r}"))

    meds = doc.get("meds")
    if not isinstance(meds, list):
        issues.append(_issue("blocking", "meds", "meds должен быть списком"))
        return issues

    seen: set[str] = set()
    for i, med in enumerate(meds):
        if not isinstance(med, dict):
            issues.append(_issue("blocking", "med", f"meds[{i}] должен быть объектом"))
            continue

        mid = med.get("id")
        where = mid if isinstance(mid, str) and mid else f"meds[{i}]"
        if not isinstance(mid, str) or not mid.strip():
            issues.append(_issue("blocking", "id", f"meds[{i}].id — непустая строка", where))
        elif mid in seen:
            issues.append(_issue("blocking", "id", f"повтор id {mid!r}", where))
        else:
            seen.add(mid)

        # Поля человека — валидируем ровно так же, как сайдкар, чтобы скилл не
        # собрал файл, который потом отвергнет POST /api/hd/save.
        if not isinstance(med.get("name"), str) or not med["name"].strip():
            issues.append(_issue("blocking", "name", "name — непустая строка", where))
        if not isinstance(med.get("taking"), bool):
            issues.append(_issue("blocking", "taking", "taking — true/false", where))

        # Срок ГОДНОСТИ — единственный срок, который хранится, и только до
        # месяца: на упаковке день не печатают. Курса приёма («принимать до»)
        # в модели нет намеренно (решение владельца 2026-07-17) — он живёт
        # в regimen прозой и устаревает сам.
        exp = med.get("expiry")
        if exp not in (None, "") and not _MONTH_RE.match(exp if isinstance(exp, str) else ""):
            issues.append(_issue("blocking", "expiry",
                                 f"expiry — «ГГГГ-ММ» или пусто, получено {exp!r} "
                                 "(срок годности хранится с точностью до месяца)", where))

        grp = med.get("group")
        if grp not in (None, "") and grp not in MED_GROUPS:
            issues.append(_issue("blocking", "group",
                                 f"group — одно из {', '.join(MED_GROUPS)} или пусто, "
                                 f"получено {grp!r}", where))

        archived = med.get("archived")
        if archived is not None and not isinstance(archived, bool):
            issues.append(_issue("blocking", "archived", "archived — true/false или отсутствует",
                                 where))
        elif archived and med.get("taking") is True:
            # Нельзя принимать то, чего нет. Обычно означает, что страница
            # заархивировала запись, не сняв галочку приёма.
            issues.append(_issue("blocking", "archived",
                                 "archived=true при taking=true — принимать нечего", where))

        issues.extend(_validate_affects(med, where, biomarker_ids))
        issues.extend(_validate_ref_meta(med, where))

    return issues


def _validate_affects(med: dict, where: str, biomarker_ids: set[str] | None) -> list[dict]:
    issues: list[dict] = []
    affects = med.get("affects", [])
    if not isinstance(affects, list) or not all(isinstance(a, str) for a in affects):
        issues.append(_issue("blocking", "affects", "affects — список строк", where))
        return issues
    if len(set(affects)) != len(affects):
        issues.append(_issue("warning", "affects", "affects содержит дубли", where))
    if biomarker_ids is not None:
        # Битая ссылка молча ломает связь вкладок: карточка маркера не покажет
        # препарат, и понять это по странице нельзя (§6.5 плана).
        for a in affects:
            if a not in biomarker_ids:
                issues.append(_issue("blocking", "affects",
                                     f"affects ссылается на {a!r} — такого id нет в labs.json",
                                     where))

    strength = med.get("affects_strength")
    if strength is None:
        return issues
    if not isinstance(strength, dict):
        issues.append(_issue("blocking", "affects_strength",
                             "affects_strength — объект {id: strong|moderate|weak}", where))
        return issues
    for k, v in strength.items():
        if k not in affects:
            issues.append(_issue("blocking", "affects_strength",
                                 f"размечена сила для {k!r}, которого нет в affects", where))
        if v not in STRENGTH:
            issues.append(_issue("blocking", "affects_strength",
                                 f"{k!r}: сила {v!r} — одно из {'/'.join(STRENGTH)}", where))
    missing = [a for a in affects if a not in strength]
    if missing:
        # Не blocking: размеченная наполовину карточка лучше неразмеченной,
        # но страница нарисует остаток нейтрально — стоит дописать.
        issues.append(_issue("warning", "affects_strength",
                             "сила влияния не размечена: " + ", ".join(missing), where))
    return issues


def _validate_ref_meta(med: dict, where: str) -> list[dict]:
    issues: list[dict] = []
    rm = med.get("ref_meta")
    filled_now = [f for f in REF_FIELDS if _is_filled(med, f)]

    if rm is None:
        if filled_now:
            # Легитимно: справку мог набить человек через форму страницы.
            # Скиллу это сигнал «не перетирать без спроса», а не ошибка.
            issues.append(_issue("info", "ref_meta",
                                 "справка заполнена без ref_meta — считается ручной, "
                                 f"скилл её не трогает: {', '.join(filled_now)}", where))
        return issues

    if not isinstance(rm, dict):
        issues.append(_issue("blocking", "ref_meta", "ref_meta — объект или отсутствует", where))
        return issues

    if not _is_iso_date(rm.get("filled_at")):
        issues.append(_issue("blocking", "ref_meta",
                             f"ref_meta.filled_at — ISO-дата, получено {rm.get('filled_at')!r}",
                             where))
    if rm.get("confidence") not in CONFIDENCE:
        issues.append(_issue("blocking", "ref_meta",
                             f"ref_meta.confidence — одно из {'/'.join(CONFIDENCE)}, "
                             f"получено {rm.get('confidence')!r}", where))

    claimed = rm.get("fields_filled")
    if not isinstance(claimed, list) or not all(isinstance(f, str) for f in claimed):
        issues.append(_issue("blocking", "ref_meta", "ref_meta.fields_filled — список строк", where))
        claimed = []
    else:
        unknown = [f for f in claimed if f not in REF_FIELDS]
        if unknown:
            issues.append(_issue("blocking", "ref_meta",
                                 f"ref_meta.fields_filled — не ref-поля: {', '.join(unknown)}",
                                 where))
        leaked = [f for f in claimed if f in USER_FIELDS]
        if leaked:
            issues.append(_issue("blocking", "ref_meta",
                                 f"ref_meta.fields_filled претендует на поля человека: "
                                 f"{', '.join(leaked)}", where))

    issues.extend(_validate_sources(rm, claimed, where))

    for f in claimed:
        if f in REF_FIELDS and not _is_filled(med, f):
            issues.append(_issue("warning", "ref_meta",
                                 f"fields_filled заявляет {f!r}, а поле пустое", where))
    for f in filled_now:
        if f not in claimed:
            issues.append(_issue("warning", "ref_meta",
                                 f"поле {f!r} заполнено, но не заявлено в fields_filled — "
                                 "провенанс его не покрывает", where))
    return issues


def _validate_sources(rm: dict, claimed: list, where: str) -> list[dict]:
    issues: list[dict] = []
    sources = rm.get("sources")
    if not isinstance(sources, list):
        issues.append(_issue("blocking", "sources", "ref_meta.sources — список", where))
        return issues

    for j, s in enumerate(sources):
        if not isinstance(s, dict):
            issues.append(_issue("blocking", "sources", f"sources[{j}] — объект", where))
            continue
        for f in ("title", "url"):
            if not isinstance(s.get(f), str) or not s[f].strip():
                issues.append(_issue("blocking", "sources",
                                     f"sources[{j}].{f} — непустая строка", where))
        if not _is_iso_date(s.get("fetched")):
            issues.append(_issue("blocking", "sources",
                                 f"sources[{j}].fetched — ISO-дата, получено {s.get('fetched')!r}",
                                 where))

    # Стержень контракта: заявил заполнение — предъяви источник.
    if claimed and not sources:
        issues.append(_issue("blocking", "sources",
                             f"fields_filled непуст ({', '.join(claimed)}), а sources пуст — "
                             "факт о лекарстве без источника не принимается", where))

    # `high` надо заслужить первичкой. Правило жило только в прозе
    # references/sources.md — и первый же прогон скилла проставил high
    # 17 записям подряд по РЛС и Vidal, ни разу не открыв ГРЛС. Проза модель
    # не держит; держит проверка (правило репозитория про model drift).
    if rm.get("confidence") == "high" and sources:
        tiers = [source_tier(s.get("url")) for s in sources if isinstance(s, dict)]
        if tiers and all(t == 2 for t in tiers):
            issues.append(_issue(
                "blocking", "confidence",
                "confidence=high, но все источники — вторичные "
                f"({', '.join(sorted({_host(s.get('url')) for s in sources if isinstance(s, dict)}))}). "
                "high требует первички (ГРЛС / DailyMed / SmPC / инструкция производителя) "
                "— либо открыть её, либо честный medium", where))
    return issues


# ─────────────────────────── merge ───────────────────────────

def merge_ref(doc: dict, enrich: dict, *, today: str,
              overwrite_manual: bool = False) -> tuple[dict, list[dict]]:
    """Вливает справку в meds.json. Возвращает (новый_doc, отчёт).

    enrich: {med_id: {"fields": {ref-поле: значение|None},
                      "sources": [...], "confidence": "high|medium|low"}}

    Значение None или пустая строка = «источник не подтвердил» → поле НЕ пишется
    и НЕ заявляется в fields_filled. Правдоподобная догадка вместо факта — то,
    ради недопущения чего этот скилл вообще существует.
    """
    out = json.loads(json.dumps(doc))  # глубокая копия: вход не мутируем
    report: list[dict] = []
    by_id = {m.get("id"): m for m in out.get("meds", []) if isinstance(m, dict)}

    for mid, payload in enrich.items():
        med = by_id.get(mid)
        if med is None:
            report.append({"id": mid, "action": "skip", "reason": "нет такого id в meds.json"})
            continue

        fields = (payload or {}).get("fields") or {}
        written: list[str] = []
        skipped_manual: list[str] = []
        skipped_empty: list[str] = []
        rejected: list[str] = []
        had_meta = isinstance(med.get("ref_meta"), dict)

        for field, value in fields.items():
            if field in USER_FIELDS:
                # Единственная жёсткая граница: данные человека неприкосновенны.
                rejected.append(field)
                continue
            if field not in REF_FIELDS:
                rejected.append(field)
                continue
            if value is None or (isinstance(value, str) and not value.strip()):
                skipped_empty.append(field)
                continue
            if field == "group" and value not in MED_GROUPS:
                # Значение вне словаря сломало бы раскладку на странице молча:
                # блока с таким ключом нет, лекарство пропало бы из списка.
                rejected.append(field)
                continue
            # `group` — единственное справочное поле, которое человек штатно
            # переопределяет на странице. Поэтому правило для него строже общего:
            # непустое значение скилл не трогает НИКОГДА, даже если сам его когда-то
            # и записал (ref_meta есть). Иначе ручной выбор молча откатывался бы
            # следующим прогоном обогащения — а это ровно то, за чем человек
            # в это поле и лезет.
            if field == "group" and _is_filled(med, field) and not overwrite_manual:
                skipped_manual.append(field)
                continue
            if _is_filled(med, field) and not had_meta and not overwrite_manual:
                skipped_manual.append(field)
                continue
            med[field] = value
            written.append(field)

        if written:
            prev = med.get("ref_meta") if had_meta else None
            prev_claimed = list(prev.get("fields_filled", [])) if isinstance(prev, dict) else []
            claimed = sorted(set(prev_claimed) | set(written))
            # Заявляем только то, что реально непусто после слияния.
            claimed = [f for f in claimed if _is_filled(med, f)]
            med["ref_meta"] = {
                "filled_at": today,
                "confidence": (payload or {}).get("confidence"),
                "fields_filled": claimed,
                "sources": (payload or {}).get("sources") or [],
            }

        report.append({
            "id": mid, "action": "fill" if written else "noop",
            "written": written, "skipped_manual": skipped_manual,
            "skipped_no_data": skipped_empty, "rejected_fields": rejected,
        })

    if any(r["action"] == "fill" for r in report):
        out["updated"] = today
    return out, report


def stale_ids(doc: dict, *, today: str, max_age_days: int = 365) -> list[str]:
    """id, чья справка старше max_age_days (для --refresh). Ручные — не в счёт."""
    out = []
    today_d = date.fromisoformat(today)
    for med in doc.get("meds", []):
        rm = med.get("ref_meta")
        if not isinstance(rm, dict) or not _is_iso_date(rm.get("filled_at")):
            continue
        if (today_d - date.fromisoformat(rm["filled_at"])).days > max_age_days:
            out.append(med.get("id"))
    return out


def pending_ids(doc: dict) -> list[str]:
    """id без справки вообще — основная очередь скилла.

    Заархивированные не в счёт: тратить на них веб-поиск незачем — лекарства
    нет. Если такое вернётся в аптечку и справка нужна, оно разархивируется
    и попадёт в очередь само.
    """
    out = []
    for med in doc.get("meds", []):
        if not isinstance(med, dict) or med.get("archived"):
            continue
        if not any(_is_filled(med, f) for f in REF_FIELDS):
            out.append(med.get("id"))
    return out


# ─────────────────────────── CLI ───────────────────────────

def _read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json_atomic(path: str, doc: Any) -> None:
    """Атомарная запись: файл на Synology читает страница, полуфайла быть не должно."""
    body = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".meds-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _print_issues(issues: list[dict]) -> None:
    if not issues:
        print("  issues: нет")
        return
    for sev in ("blocking", "warning", "info"):
        rows = [i for i in issues if i["severity"] == sev]
        for i in rows:
            tag = i.get("id", "—")
            print(f"  [{sev}] {tag}: {i['message']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Валидатор/merge аптечки health-meds@1")
    sub = ap.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="проверить meds.json")
    v.add_argument("--meds", required=True)
    v.add_argument("--labs", help="labs.json — включает проверку ссылок affects")
    v.add_argument("--json", action="store_true", help="issues машиночитаемо")

    m = sub.add_parser("merge", help="влить справку (по умолчанию dry-run)")
    m.add_argument("--meds", required=True)
    m.add_argument("--enrich", required=True)
    m.add_argument("--labs")
    m.add_argument("--today", default=date.today().isoformat())
    m.add_argument("--apply", action="store_true", help="записать файл")
    m.add_argument("--overwrite-manual", action="store_true",
                   help="перетирать справку, набитую рукой (по умолчанию — нет)")

    args = ap.parse_args(argv)
    ids = load_biomarker_ids(_read_json(args.labs)) if getattr(args, "labs", None) else None

    if args.cmd == "validate":
        doc = _read_json(args.meds)
        issues = validate_meds(doc, ids)
        if args.json:
            print(json.dumps(issues, ensure_ascii=False, indent=2))
        else:
            print(f"Проверка {args.meds}")
            _print_issues(issues)
        return 1 if any(i["severity"] == "blocking" for i in issues) else 0

    doc = _read_json(args.meds)
    new_doc, report = merge_ref(doc, _read_json(args.enrich), today=args.today,
                                overwrite_manual=args.overwrite_manual)
    issues = validate_meds(new_doc, ids)
    blocking = [i for i in issues if i["severity"] == "blocking"]

    print(f"Merge {args.meds} ({'запись' if args.apply else 'dry-run'})")
    for r in report:
        bits = []
        if r.get("written"):
            bits.append("записано: " + ", ".join(r["written"]))
        if r.get("skipped_manual"):
            bits.append("не тронуто (ручное): " + ", ".join(r["skipped_manual"]))
        if r.get("skipped_no_data"):
            bits.append("нет данных: " + ", ".join(r["skipped_no_data"]))
        if r.get("rejected_fields"):
            bits.append("ОТКЛОНЕНО (не ref-поле либо значение вне словаря): "
                        + ", ".join(r["rejected_fields"]))
        if r.get("reason"):
            bits.append(r["reason"])
        print(f"  {r['id']}: {'; '.join(bits) if bits else 'без изменений'}")
    _print_issues(issues)

    if blocking:
        print(f"\n✗ {len(blocking)} blocking-issue — файл НЕ записан.")
        return 1
    if args.apply:
        hub_settings.require_ai(args.meds, "validate_meds.py merge --apply", "запись аптечки", zones=("Health",))   # вход — вывод модели
        _write_json_atomic(args.meds, new_doc)
        print(f"\n✓ Записано: {args.meds}")
    else:
        print("\n✓ Валидация зелёная. Запись: повторить с --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
