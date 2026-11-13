#!/usr/bin/env python3
"""
Регрессионные тесты для validate_meds.py (health-meds).

Запуск из корня репозитория:
    python3 skills/health-meds/tests/test_validate_meds.py

Медданных здесь нет и быть не может — только синтетические фикстуры:
репозиторий уезжает на GitHub (health-plan.md §0.1).
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "skills" / "health-meds" / "scripts" / "validate_meds.py"

sys.path.insert(0, str(SCRIPT.parent))
from validate_meds import (  # noqa: E402
    REF_FIELDS,
    USER_FIELDS,
    load_biomarker_ids,
    source_tier,
    merge_ref,
    pending_ids,
    stale_ids,
    validate_meds,
)

checks_run = 0
checks_failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global checks_run, checks_failed
    checks_run += 1
    status = "OK" if condition else "FAIL"
    if not condition:
        checks_failed += 1
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


def sev(issues, severity, category=None):
    return [i for i in issues
            if i["severity"] == severity and (category is None or i["category"] == category)]


def has(issues, severity, category):
    return bool(sev(issues, severity, category))


TODAY = "2026-07-17"
LABS_IDS = {"ldl", "alt", "vitamin_d", "hgb"}


def med(**over):
    """Запись в форме ЖИВОГО meds.json — плоская, как её пишет страница."""
    base = {
        "id": "atorvastatin", "name": "Аторвастатин", "inn": "", "for": "", "class": "",
        "dose": "20 мг", "regimen": "", "timing": "", "form": "", "taking": True,
        "prescribedBy": "", "expiry": "", "affects": [], "indications": "",
        "interactions": "", "notes": "",
    }
    base.update(over)
    return base


def doc(*meds):
    return {"schema": "health-meds@1", "updated": TODAY, "meds": list(meds or [med()])}


def ref_meta(**over):
    base = {"filled_at": TODAY, "confidence": "high", "fields_filled": ["inn"],
            "sources": [{"title": "ГРЛС", "url": "https://grls.example/x", "fetched": TODAY}]}
    base.update(over)
    return base


# ─────────────────── схема и поля ───────────────────

def test_schema():
    print("\nСхема и обязательные поля")
    check("валидный документ — без issues", validate_meds(doc(), LABS_IDS) == [])
    check("пустая аптечка валидна", validate_meds({"schema": "health-meds@1", "meds": []}) == [])
    check("чужая schema → blocking",
          has(validate_meds({"schema": "health-meds@2", "meds": []}), "blocking", "schema"))
    check("корень не объект → blocking", has(validate_meds([]), "blocking", "root"))
    check("meds не список → blocking",
          has(validate_meds({"schema": "health-meds@1", "meds": {}}), "blocking", "meds"))
    check("updated не ISO → warning",
          has(validate_meds({"schema": "health-meds@1", "updated": "17.07.2026", "meds": []}),
              "warning", "updated"))
    check("пустой id → blocking", has(validate_meds(doc(med(id=""))), "blocking", "id"))
    check("повтор id → blocking",
          has(validate_meds(doc(med(), med(name="Другое"))), "blocking", "id"))
    check("пустое name → blocking", has(validate_meds(doc(med(name="  "))), "blocking", "name"))
    check("taking не bool → blocking",
          has(validate_meds(doc(med(taking="да"))), "blocking", "taking"))
    check("issue несёт id лекарства",
          sev(validate_meds(doc(med(name=""))), "blocking", "name")[0]["id"] == "atorvastatin")


def test_affects():
    print("\nСсылки affects → labs.json")
    # affects — тоже поле справки: заполненное без ref_meta оно ожидаемо даёт
    # info «ручное, не трогать». Требуем отсутствия blocking, а не тишины.
    check("живой id — не blocking",
          not sev(validate_meds(doc(med(affects=["ldl", "alt"])), LABS_IDS), "blocking"))
    check("живой id + провенанс — тишина",
          validate_meds(doc(med(affects=["ldl", "alt"],
                                ref_meta=ref_meta(fields_filled=["affects"]))), LABS_IDS) == [])
    check("orphan affects → blocking",
          has(validate_meds(doc(med(affects=["cholesterol_ldl"])), LABS_IDS), "blocking", "affects"))
    check("orphan назван в тексте",
          "cholesterol_ldl" in sev(validate_meds(doc(med(affects=["cholesterol_ldl"])), LABS_IDS),
                                   "blocking", "affects")[0]["message"])
    check("без labs orphan не проверяется",
          not has(validate_meds(doc(med(affects=["cholesterol_ldl"]))), "blocking", "affects"))
    check("affects не список строк → blocking",
          has(validate_meds(doc(med(affects=[1]))), "blocking", "affects"))
    check("дубли в affects → warning",
          has(validate_meds(doc(med(affects=["ldl", "ldl"])), LABS_IDS), "warning", "affects"))


# ─────────────────── провенанс ───────────────────

def test_ref_meta():
    print("\nref_meta — структура")
    ok = med(inn="аторвастатин", ref_meta=ref_meta())
    check("заполненное поле + провенанс — без issues", validate_meds(doc(ok), LABS_IDS) == [])
    check("ref_meta не объект → blocking",
          has(validate_meds(doc(med(ref_meta="да"))), "blocking", "ref_meta"))
    check("filled_at не ISO → blocking",
          has(validate_meds(doc(med(inn="x", ref_meta=ref_meta(filled_at="17.07.2026")))),
              "blocking", "ref_meta"))
    check("confidence вне enum → blocking",
          has(validate_meds(doc(med(inn="x", ref_meta=ref_meta(confidence="точно")))),
              "blocking", "ref_meta"))
    for c in ("high", "medium", "low"):
        check(f"confidence {c} принимается",
              not has(validate_meds(doc(med(inn="x", ref_meta=ref_meta(confidence=c)))),
                      "blocking", "ref_meta"))
    check("fields_filled не список → blocking",
          has(validate_meds(doc(med(inn="x", ref_meta=ref_meta(fields_filled="inn")))),
              "blocking", "ref_meta"))
    check("fields_filled с не-ref-полем → blocking",
          has(validate_meds(doc(med(inn="x", ref_meta=ref_meta(fields_filled=["inn", "wat"])))),
              "blocking", "ref_meta"))
    check("fields_filled претендует на поле человека → blocking",
          has(validate_meds(doc(med(inn="x", ref_meta=ref_meta(fields_filled=["inn", "dose"])))),
              "blocking", "ref_meta"))


def test_sources():
    print("\nref_meta — источники (стержень контракта)")
    check("fields_filled непуст + sources пуст → blocking",
          has(validate_meds(doc(med(inn="x", ref_meta=ref_meta(sources=[])))),
              "blocking", "sources"))
    check("сообщение объясняет причину",
          "без источника" in sev(validate_meds(doc(med(inn="x", ref_meta=ref_meta(sources=[])))),
                                 "blocking", "sources")[0]["message"])
    check("sources не список → blocking",
          has(validate_meds(doc(med(inn="x", ref_meta=ref_meta(sources={})))),
              "blocking", "sources"))
    check("источник без url → blocking",
          has(validate_meds(doc(med(inn="x", ref_meta=ref_meta(
              sources=[{"title": "ГРЛС", "fetched": TODAY}])))), "blocking", "sources"))
    check("источник без title → blocking",
          has(validate_meds(doc(med(inn="x", ref_meta=ref_meta(
              sources=[{"url": "https://x", "fetched": TODAY}])))), "blocking", "sources"))
    check("источник с кривой fetched → blocking",
          has(validate_meds(doc(med(inn="x", ref_meta=ref_meta(
              sources=[{"title": "ГРЛС", "url": "https://x", "fetched": "вчера"}])))),
              "blocking", "sources"))
    check("пустой fields_filled + пустой sources — не blocking",
          not has(validate_meds(doc(med(ref_meta=ref_meta(fields_filled=[], sources=[])))),
                  "blocking", "sources"))


def test_provenance_consistency():
    print("\nref_meta ↔ реальность полей")
    check("заявлено, но поле пустое → warning",
          has(validate_meds(doc(med(ref_meta=ref_meta(fields_filled=["inn"])))),
              "warning", "ref_meta"))
    check("поле заполнено, но не заявлено → warning",
          has(validate_meds(doc(med(inn="x", class_="", indications="лечение",
                                    ref_meta=ref_meta(fields_filled=["inn"])))),
              "warning", "ref_meta"))
    check("справка без ref_meta → info «ручная»",
          has(validate_meds(doc(med(inn="набито рукой"))), "info", "ref_meta"))
    check("ручная справка НЕ blocking",
          not sev(validate_meds(doc(med(inn="набито рукой"))), "blocking"))
    check("пустая запись без ref_meta — тишина", validate_meds(doc(med())) == [])


def test_backward_compat():
    print("\nBackward-compat с живым файлом")
    # 19 записей живого meds.json: плоские, без ref_meta, справка не заполнена.
    live = doc(*[med(id=f"m{i}", name=f"Препарат {i}", taking=False) for i in range(19)])
    issues = validate_meds(live, LABS_IDS)
    check("живой файл без ref_meta проходит без blocking", not sev(issues, "blocking"))
    check("живой файл не сыплет warning'ами", not sev(issues, "warning"))
    check("REF_FIELDS и USER_FIELDS не пересекаются",
          not (set(REF_FIELDS) & set(USER_FIELDS)))


# ─────────────────── merge ───────────────────

def test_merge_basic():
    print("\nmerge — заполнение")
    d = doc(med())
    enrich = {"atorvastatin": {"fields": {"inn": "аторвастатин", "class": "статин"},
                              "confidence": "high",
                              "sources": [{"title": "ГРЛС", "url": "https://g/1",
                                           "fetched": TODAY}]}}
    out, report = merge_ref(d, enrich, today=TODAY)
    m = out["meds"][0]
    check("ref-поля записаны", m["inn"] == "аторвастатин" and m["class"] == "статин")
    check("ref_meta проставлен", m["ref_meta"]["filled_at"] == TODAY)
    check("fields_filled = что реально записано",
          sorted(m["ref_meta"]["fields_filled"]) == ["class", "inn"])
    check("confidence перенесён", m["ref_meta"]["confidence"] == "high")
    check("источник перенесён", m["ref_meta"]["sources"][0]["url"] == "https://g/1")
    check("updated обновлён", out["updated"] == TODAY)
    check("отчёт: action=fill", report[0]["action"] == "fill")
    check("результат merge проходит validate", validate_meds(out, LABS_IDS) == [])


def test_merge_never_touches_user():
    print("\nmerge — поля человека неприкосновенны (главный инвариант)")
    original = med(dose="20 мг", taking=True, notes="моя заметка", expiry="2027-03",
                   prescribedBy="кардиолог", regimen="1 раз в день")
    d = doc(original)
    # Скилл (или сбойная модель) пытается переписать данные человека.
    enrich = {"atorvastatin": {
        "fields": {"inn": "аторвастатин", "dose": "40 мг", "taking": False,
                   "notes": "перезаписано", "name": "Липримар", "expiry": "2030-01"},
        "confidence": "high",
        "sources": [{"title": "ГРЛС", "url": "https://g/1", "fetched": TODAY}]}}
    out, report = merge_ref(d, enrich, today=TODAY)
    m = out["meds"][0]
    for f, want in (("dose", "20 мг"), ("taking", True), ("notes", "моя заметка"),
                    ("name", "Аторвастатин"), ("expiry", "2027-03")):
        check(f"user-поле {f} не тронуто", m[f] == want)
    check("ref-поле при этом записано", m["inn"] == "аторвастатин")
    check("попытка отражена в rejected_fields",
          set(report[0]["rejected_fields"]) == {"dose", "taking", "notes", "name", "expiry"})
    check("fields_filled не содержит user-полей",
          not (set(m["ref_meta"]["fields_filled"]) & set(USER_FIELDS)))


def test_merge_manual_guard():
    print("\nmerge — ручная справка не перетирается")
    manual = med(inn="набито рукой", indications="и это тоже")
    enrich = {"atorvastatin": {"fields": {"inn": "аторвастатин", "class": "статин"},
                              "confidence": "high",
                              "sources": [{"title": "ГРЛС", "url": "https://g/1",
                                           "fetched": TODAY}]}}
    out, report = merge_ref(doc(manual), enrich, today=TODAY)
    m = out["meds"][0]
    check("ручное поле сохранено", m["inn"] == "набито рукой")
    check("пустое поле рядом заполнено", m["class"] == "статин")
    check("отчёт называет пропущенное", report[0]["skipped_manual"] == ["inn"])
    check("ручное поле не заявлено в fields_filled",
          m["ref_meta"]["fields_filled"] == ["class"])

    out2, report2 = merge_ref(doc(manual), enrich, today=TODAY, overwrite_manual=True)
    check("--overwrite-manual перетирает", out2["meds"][0]["inn"] == "аторвастатин")
    check("при overwrite ничего не пропущено", report2[0]["skipped_manual"] == [])

    # Поле, заполненное САМИМ скиллом (есть ref_meta), обновляется свободно.
    own = med(inn="старое", ref_meta=ref_meta(fields_filled=["inn"]))
    out3, _ = merge_ref(doc(own), enrich, today=TODAY)
    check("своё прежнее заполнение обновляется без флага", out3["meds"][0]["inn"] == "аторвастатин")


def test_merge_no_invention():
    print("\nmerge — не выдумывать")
    enrich = {"atorvastatin": {"fields": {"inn": "аторвастатин", "class": None,
                                          "indications": "   "},
                              "confidence": "medium",
                              "sources": [{"title": "ГРЛС", "url": "https://g/1",
                                           "fetched": TODAY}]}}
    out, report = merge_ref(doc(med()), enrich, today=TODAY)
    m = out["meds"][0]
    check("None не записан", m["class"] == "")
    check("пробельная строка не записана", m["indications"] == "")
    check("неподтверждённое не заявлено в fields_filled",
          m["ref_meta"]["fields_filled"] == ["inn"])
    check("отчёт: skipped_no_data", sorted(report[0]["skipped_no_data"]) == ["class", "indications"])
    check("результат валиден", validate_meds(out, LABS_IDS) == [])


def test_merge_edges():
    print("\nmerge — края")
    d = doc(med())
    before = json.dumps(d, ensure_ascii=False, sort_keys=True)
    merge_ref(d, {"atorvastatin": {"fields": {"inn": "x"}, "confidence": "low",
                                   "sources": [{"title": "t", "url": "u", "fetched": TODAY}]}},
              today=TODAY)
    check("вход не мутируется", json.dumps(d, ensure_ascii=False, sort_keys=True) == before)

    out, report = merge_ref(doc(med()), {"unknown_id": {"fields": {"inn": "x"}}}, today=TODAY)
    check("неизвестный id → skip", report[0]["action"] == "skip")
    check("неизвестный id не меняет updated", "updated" in out)

    out2, report2 = merge_ref(doc(med()), {"atorvastatin": {"fields": {}}}, today="2026-08-01")
    check("пустой enrich → noop", report2[0]["action"] == "noop")
    check("noop не двигает updated", out2["updated"] == TODAY)
    check("noop не создаёт ref_meta", "ref_meta" not in out2["meds"][0])

    prev = med(inn="старое", ref_meta=ref_meta(fields_filled=["inn"]))
    out3, _ = merge_ref(doc(prev), {"atorvastatin": {
        "fields": {"class": "статин"}, "confidence": "high",
        "sources": [{"title": "t", "url": "u", "fetched": TODAY}]}}, today=TODAY)
    check("прежние fields_filled сливаются с новыми",
          sorted(out3["meds"][0]["ref_meta"]["fields_filled"]) == ["class", "inn"])

    out4, _ = merge_ref(doc(med()), {"atorvastatin": {
        "fields": {"affects": ["ldl", "alt"]}, "confidence": "high",
        "sources": [{"title": "t", "url": "u", "fetched": TODAY}]}}, today=TODAY)
    check("affects записывается как список", out4["meds"][0]["affects"] == ["ldl", "alt"])
    check("affects попал в fields_filled", out4["meds"][0]["ref_meta"]["fields_filled"] == ["affects"])


def test_queues():
    print("\nОчереди: pending / stale")
    d = doc(med(id="empty"),
            med(id="filled", inn="x", ref_meta=ref_meta(filled_at="2026-07-01")),
            med(id="old", inn="x", ref_meta=ref_meta(filled_at="2024-01-01")),
            med(id="manual", inn="рукой"))
    check("pending — только запись без справки", pending_ids(d) == ["empty"])
    check("stale — просроченная справка", stale_ids(d, today=TODAY) == ["old"])
    check("свежая справка не stale", "filled" not in stale_ids(d, today=TODAY))
    check("ручная справка не stale (нет ref_meta)", "manual" not in stale_ids(d, today=TODAY))
    check("порог настраивается",
          "filled" in stale_ids(d, today=TODAY, max_age_days=5))


def test_confidence_tier():
    print("\nconfidence=high надо заслужить первичкой")
    def src(url):
        return {"title": "t", "url": url, "fetched": TODAY}

    def rec(conf, urls):
        return doc(med(inn="x", ref_meta=ref_meta(confidence=conf,
                                                  sources=[src(u) for u in urls])))

    check("high + только РЛС/Vidal → blocking",
          has(validate_meds(rec("high", ["https://www.rlsnet.ru/drugs/x",
                                         "https://www.vidal.ru/drugs/x"])),
              "blocking", "confidence"))
    check("сообщение называет домены и что делать",
          "rlsnet.ru" in sev(validate_meds(rec("high", ["https://rlsnet.ru/x"])),
                             "blocking", "confidence")[0]["message"])
    check("medium на вторичке — норма (так и задумано)",
          not has(validate_meds(rec("medium", ["https://www.rlsnet.ru/drugs/x"])),
                  "blocking", "confidence"))
    check("high + ГРЛС → ок",
          not has(validate_meds(rec("high", ["https://grls.rosminzdrav.ru/Grls_View.aspx?x",
                                             "https://www.rlsnet.ru/drugs/x"])),
                  "blocking", "confidence"))
    check("high + DailyMed → ок",
          not has(validate_meds(rec("high", ["https://dailymed.nlm.nih.gov/x"])),
                  "blocking", "confidence"))
    # Инструкция производителя живёт на его домене — заранее он не известен,
    # поэтому незнакомый домен трактуем в пользу записи (реальный diakarb).
    check("high + PDF инструкции производителя (домен неизвестен) → ок",
          not has(validate_meds(rec("high", ["https://akrikhin.ru/upload/Diakarb.pdf"])),
                  "blocking", "confidence"))
    check("high + вторичка + неизвестный домен → ок",
          not has(validate_meds(rec("high", ["https://rlsnet.ru/x",
                                             "https://akrikhin.ru/i.pdf"])),
                  "blocking", "confidence"))
    check("source_tier: поддомен вторички опознан",
          source_tier("https://www.rlsnet.ru/x") == 2)
    check("source_tier: первичка опознана",
          source_tier("https://grls.rosminzdrav.ru/x") == 1)
    check("source_tier: мусорный url → 0", source_tier("не url") == 0)


def test_affects_strength():
    print("\nСила влияния на биомаркер")
    def rec(affects, strength):
        return doc(med(affects=affects, affects_strength=strength,
                       ref_meta=ref_meta(fields_filled=["affects", "affects_strength"])))

    check("полная разметка — тишина",
          validate_meds(rec(["ldl", "alt"], {"ldl": "strong", "alt": "weak"}), LABS_IDS) == [])
    for s in ("strong", "moderate", "weak"):
        check(f"сила {s} принимается",
              not has(validate_meds(rec(["ldl"], {"ldl": s}), LABS_IDS), "blocking",
                      "affects_strength"))
    check("чужое значение силы → blocking",
          has(validate_meds(rec(["ldl"], {"ldl": "сильное"}), LABS_IDS),
              "blocking", "affects_strength"))
    check("не объект → blocking",
          has(validate_meds(rec(["ldl"], ["strong"]), LABS_IDS), "blocking", "affects_strength"))
    check("сила для маркера вне affects → blocking",
          has(validate_meds(rec(["ldl"], {"ldl": "strong", "alt": "weak"}), LABS_IDS),
              "blocking", "affects_strength"))
    check("частичная разметка → warning с именами",
          "alt" in sev(validate_meds(rec(["ldl", "alt"], {"ldl": "strong"}), LABS_IDS),
                       "warning", "affects_strength")[0]["message"])
    check("нет разметки вовсе → не blocking (записи первого прогона)",
          not sev(validate_meds(doc(med(affects=["ldl"],
                                        ref_meta=ref_meta(fields_filled=["affects"]))),
                                LABS_IDS), "blocking"))
    check("affects_strength — ref-поле (скилл пишет, человек нет)",
          "affects_strength" in REF_FIELDS and "affects_strength" not in USER_FIELDS)

    out, _ = merge_ref(doc(med()), {"atorvastatin": {
        "fields": {"affects": ["ldl"], "affects_strength": {"ldl": "strong"}},
        "confidence": "medium",
        "sources": [{"title": "t", "url": "https://rlsnet.ru/x", "fetched": TODAY}]}},
        today=TODAY)
    check("merge пишет силу влияния", out["meds"][0]["affects_strength"] == {"ldl": "strong"})
    check("merge заявляет её в fields_filled",
          "affects_strength" in out["meds"][0]["ref_meta"]["fields_filled"])
    check("результат merge валиден", validate_meds(out, LABS_IDS) == [])


def test_expiry_month_only():
    print("\nСрок годности — только месяц (курса приёма в модели нет)")
    check("пустой срок — норма (так у всех 19 живых записей)",
          validate_meds(doc(med(expiry="")), LABS_IDS) == [])
    check("поля expiry нет вовсе — норма",
          validate_meds(doc({k: v for k, v in med().items() if k != "expiry"}), LABS_IDS) == [])
    check("«2027-03» — норма", validate_meds(doc(med(expiry="2027-03")), LABS_IDS) == [])
    check("полная дата → blocking (день на упаковке не печатают)",
          has(validate_meds(doc(med(expiry="2027-03-01"))), "blocking", "expiry"))
    check("месяц 13 → blocking", has(validate_meds(doc(med(expiry="2027-13"))), "blocking", "expiry"))
    check("месяц 00 → blocking", has(validate_meds(doc(med(expiry="2027-00"))), "blocking", "expiry"))
    check("«март 2027» → blocking", has(validate_meds(doc(med(expiry="март 2027"))), "blocking", "expiry"))
    check("не строка → blocking", has(validate_meds(doc(med(expiry=202703))), "blocking", "expiry"))
    check("сообщение объясняет формат",
          "ГГГГ-ММ" in sev(validate_meds(doc(med(expiry="2027-03-01"))), "blocking", "expiry")[0]["message"])
    check("expiry — поле человека, скилл его не пишет",
          "expiry" in USER_FIELDS and "expiry" not in REF_FIELDS)
    # Курса приёма («принимать до») в контракте нет намеренно: он живёт в
    # regimen прозой. Поле, которого нет, невозможно рассинхронизировать.
    check("в модели нет отдельного поля курса приёма",
          not any(f in USER_FIELDS + REF_FIELDS
                  for f in ("take_until", "course_end", "until", "started")))


def test_archived():
    print("\nСостояние «нет в наличии» (archived)")
    check("archived=true при taking=false — норма",
          validate_meds(doc(med(taking=False, archived=True)), LABS_IDS) == [])
    check("archived отсутствует — норма (записи до введения поля)",
          validate_meds(doc(med(taking=True)), LABS_IDS) == [])
    check("archived=false — норма",
          validate_meds(doc(med(taking=True, archived=False)), LABS_IDS) == [])
    check("archived не bool → blocking",
          has(validate_meds(doc(med(archived="нет"))), "blocking", "archived"))
    check("archived=true + taking=true → blocking (принимать нечего)",
          has(validate_meds(doc(med(taking=True, archived=True))), "blocking", "archived"))
    check("archived — поле человека, скилл его не пишет",
          "archived" in USER_FIELDS and "archived" not in REF_FIELDS)

    out, report = merge_ref(doc(med(taking=False, archived=True)), {"atorvastatin": {
        "fields": {"inn": "аторвастатин", "archived": False, "taking": True},
        "confidence": "medium",
        "sources": [{"title": "t", "url": "https://rlsnet.ru/x", "fetched": TODAY}]}},
        today=TODAY)
    check("merge не разархивирует запись", out["meds"][0]["archived"] is True)
    check("попытка отражена в rejected_fields",
          set(report[0]["rejected_fields"]) == {"archived", "taking"})

    d = doc(med(id="live"), med(id="gone", taking=False, archived=True))
    check("pending пропускает заархивированное — веб-поиск на него не тратим",
          pending_ids(d) == ["live"])


def test_labs_loader():
    print("\nЗагрузка id биомаркеров")
    labs = {"schema": "health-labs@1",
            "biomarkers": [{"id": "ldl", "name": "ЛПНП"}, {"id": "alt"}, {"name": "без id"}, "мусор"]}
    check("id извлечены", load_biomarker_ids(labs) == {"ldl", "alt"})
    check("пустой labs → пустое множество", load_biomarker_ids({}) == set())


# ─────────────────── паритет с сайдкаром ───────────────────

def test_sidecar_parity():
    print("\nПаритет с валидатором сайдкара (server.py)")
    sys.path.insert(0, str(REPO_ROOT / "tools/hosting/api"))
    try:
        import server  # noqa
    except Exception as e:  # pragma: no cover
        check("server.py импортируется", False, str(e))
        return

    def sidecar_ok(d):
        try:
            server.validate_health("meds.json", json.dumps(d, ensure_ascii=False))
            return True
        except ValueError:
            return False

    enriched = doc(med(inn="аторвастатин", **{"class": "статин"}, affects=["ldl"],
                       ref_meta=ref_meta(fields_filled=["inn", "class", "affects"])))
    check("валидный по скиллу файл принимает сайдкар", sidecar_ok(enriched))
    check("он же зелёный у скилла", validate_meds(enriched, LABS_IDS) == [])
    check("сайдкар знает про ref_meta (не падает на нём)",
          sidecar_ok(doc(med(inn="x", ref_meta=ref_meta()))))
    check("сайдкар отвергает битый ref_meta", not sidecar_ok(doc(med(ref_meta="да"))))
    check("сайдкар отвергает кривой confidence",
          not sidecar_ok(doc(med(inn="x", ref_meta=ref_meta(confidence="точно")))))
    check("оба отвергают пустое name",
          not sidecar_ok(doc(med(name=""))) and has(validate_meds(doc(med(name=""))),
                                                    "blocking", "name"))


# ─────────────────── CLI ───────────────────

def test_cli():
    print("\nCLI")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        meds_p, labs_p, enr_p = p / "meds.json", p / "labs.json", p / "enrich.json"
        labs_p.write_text(json.dumps(
            {"schema": "health-labs@1", "biomarkers": [{"id": x} for x in LABS_IDS]}),
            encoding="utf-8")

        meds_p.write_text(json.dumps(doc(med()), ensure_ascii=False), encoding="utf-8")
        r = subprocess.run([sys.executable, str(SCRIPT), "validate", "--meds", str(meds_p)],
                           capture_output=True, text=True)
        check("validate чистого файла → exit 0", r.returncode == 0)

        meds_p.write_text(json.dumps(doc(med(affects=["nope"])), ensure_ascii=False),
                          encoding="utf-8")
        r = subprocess.run([sys.executable, str(SCRIPT), "validate", "--meds", str(meds_p),
                            "--labs", str(labs_p)], capture_output=True, text=True)
        check("validate с orphan affects → exit 1", r.returncode == 1)
        check("orphan назван в выводе", "nope" in r.stdout)

        r = subprocess.run([sys.executable, str(SCRIPT), "validate", "--meds", str(meds_p),
                            "--labs", str(labs_p), "--json"], capture_output=True, text=True)
        check("--json печатает разбираемые issues",
              isinstance(json.loads(r.stdout), list) and json.loads(r.stdout))

        # merge: dry-run не пишет
        meds_p.write_text(json.dumps(doc(med()), ensure_ascii=False), encoding="utf-8")
        enr_p.write_text(json.dumps({"atorvastatin": {
            "fields": {"inn": "аторвастатин"}, "confidence": "high",
            "sources": [{"title": "ГРЛС", "url": "https://g/1", "fetched": TODAY}]}}),
            encoding="utf-8")
        before = meds_p.read_text(encoding="utf-8")
        r = subprocess.run([sys.executable, str(SCRIPT), "merge", "--meds", str(meds_p),
                            "--enrich", str(enr_p), "--labs", str(labs_p), "--today", TODAY],
                           capture_output=True, text=True)
        check("merge без --apply → exit 0", r.returncode == 0)
        check("merge без --apply НЕ пишет файл", meds_p.read_text(encoding="utf-8") == before)
        check("dry-run говорит, что записал бы", "записано: inn" in r.stdout)

        r = subprocess.run([sys.executable, str(SCRIPT), "merge", "--meds", str(meds_p),
                            "--enrich", str(enr_p), "--labs", str(labs_p), "--today", TODAY,
                            "--apply"], capture_output=True, text=True)
        check("merge --apply → exit 0", r.returncode == 0)
        saved = json.loads(meds_p.read_text(encoding="utf-8"))
        check("--apply записал ref-поле", saved["meds"][0]["inn"] == "аторвастатин")
        check("--apply записал провенанс", saved["meds"][0]["ref_meta"]["confidence"] == "high")
        check("файл остался валидным JSON с кириллицей без \\u",
              "аторвастатин" in meds_p.read_text(encoding="utf-8"))

        # merge, ведущий к blocking, не пишет
        meds_p.write_text(json.dumps(doc(med()), ensure_ascii=False), encoding="utf-8")
        before = meds_p.read_text(encoding="utf-8")
        enr_p.write_text(json.dumps({"atorvastatin": {
            "fields": {"affects": ["no_such_marker"]}, "confidence": "high",
            "sources": [{"title": "t", "url": "u", "fetched": TODAY}]}}), encoding="utf-8")
        r = subprocess.run([sys.executable, str(SCRIPT), "merge", "--meds", str(meds_p),
                            "--enrich", str(enr_p), "--labs", str(labs_p), "--today", TODAY,
                            "--apply"], capture_output=True, text=True)
        check("merge с blocking → exit 1", r.returncode == 1)
        check("merge с blocking НЕ пишет файл", meds_p.read_text(encoding="utf-8") == before)
        check("объяснено, почему не записан", "НЕ записан" in r.stdout)


def test_group():
    print("\ngroup — назначение из закрытого словаря")
    check("пустой group допустим", not has(validate_meds(doc(med(group=""))), "blocking", "group"))
    check("отсутствие group допустимо", not has(validate_meds(doc(med())), "blocking", "group"))
    check("значение из словаря допустимо",
          not has(validate_meds(doc(med(group="gi"))), "blocking", "group"))
    # Значение вне словаря блокирующее не из педантизма: блока с таким ключом
    # на странице нет, и лекарство молча исчезло бы из списка целиком.
    check("значение вне словаря — blocking",
          has(validate_meds(doc(med(group="желудок"))), "blocking", "group"))

    src = [{"title": "ГРЛС", "url": "https://g/1", "fetched": TODAY}]
    enrich = {"atorvastatin": {"fields": {"group": "heart"}, "confidence": "high",
                               "sources": src}}
    out, rep = merge_ref(doc(med(group="")), enrich, today=TODAY)
    check("пустой group скилл заполняет", out["meds"][0]["group"] == "heart")
    check("group заявлен в fields_filled", "group" in out["meds"][0]["ref_meta"]["fields_filled"])

    # Главное свойство поля: человек ставит его руками на странице, и следующий
    # прогон обогащения обязан оставить выбор в покое — даже если сам же его
    # когда-то и записал (то есть ref_meta у записи уже есть).
    manual = med(group="other", ref_meta=ref_meta(fields_filled=["group"]))
    out2, rep2 = merge_ref(doc(manual), enrich, today=TODAY)
    check("ручной group не перетёрт при наличии ref_meta", out2["meds"][0]["group"] == "other")
    check("отчёт называет group пропущенным", "group" in rep2[0]["skipped_manual"])

    out3, _ = merge_ref(doc(manual), enrich, today=TODAY, overwrite_manual=True)
    check("--overwrite-manual перетирает и group", out3["meds"][0]["group"] == "heart")

    bad = {"atorvastatin": {"fields": {"group": "выдумка"}, "confidence": "high",
                            "sources": src}}
    out4, rep4 = merge_ref(doc(med(group="")), bad, today=TODAY)
    check("значение вне словаря скилл не пишет", not out4["meds"][0].get("group"))
    check("отчёт называет его отклонённым", "group" in rep4[0]["rejected_fields"])


def main() -> int:
    print("=" * 60)
    print("validate_meds.py — регрессионные тесты")
    print("=" * 60)
    test_schema()
    test_affects()
    test_ref_meta()
    test_sources()
    test_provenance_consistency()
    test_backward_compat()
    test_merge_basic()
    test_merge_never_touches_user()
    test_merge_manual_guard()
    test_merge_no_invention()
    test_merge_edges()
    test_queues()
    test_confidence_tier()
    test_affects_strength()
    test_expiry_month_only()
    test_archived()
    test_group()
    test_labs_loader()
    test_sidecar_parity()
    test_cli()
    print("=" * 60)
    print(f"Итого: {checks_run - checks_failed}/{checks_run} проверок прошло")
    print("=" * 60)
    return 0 if checks_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
