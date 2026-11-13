#!/usr/bin/env python3
"""АРХИВ. Конвертер лабораторных данных: master_labs.csv -> labs.json (health-labs@1).

⚠ С 2026-09-29 labs.json — ГЛАВНЫЙ файл (решение владельца): новые данные
вносит scripts/intake.py из первоисточника «Медицинские анализы», а связи с
исследованиями (series[i].study/src) живут только в labs.json. Пересборка из
CSV их бы стёрла, поэтому запись без --legacy-overwrite запрещена, а поверх
labs.json с внесёнными точками — запрещена всегда. Скрипт остаётся ради
--selftest парсеров и истории миграции из Ornament.

Детерминированный data layer для страницы «Здоровье» Personal Hub. Скрипт
принадлежит скиллу health-labs (skills/health-labs/scripts/) — CSV на входе,
готовый labs.json на Synology на выходе, без промежуточного Mac-этапа.
Мастер данных остаётся CSV (выгрузка Ornament) — JSON генерируется отсюда.

Вход (CSV) — на Mac: ~/Documents/Claude/Projects/Health/данные (в репозиторий
не попадают: медицина в GitHub не едет; сюда же экспортирует Ornament, менять
некуда). Выход (labs.json) — сразу на Synology, в тот же Claude-Memory/Health/,
куда пишут health-meds и сама страница: 2026-08-05 отказались от
промежуточного Mac-этапа + tools/deploy.zsh — labs.json не участвует в общем
деплое HTML-страниц, это отдельный прямой канал. Запускать можно откуда
угодно: все пути ниже абсолютные (привязаны к дому пользователя), не к
текущей папке.

Что делает:
  * даты DD.MM.YYYY -> ISO;
  * нормализует опечатки единиц Ornament (ммол/л -> ммоль/л и т.п.);
  * парсит референсы («35 − 50», «0.00 − 10K», «< 21», «Не обнаружено», «—»)
    ПОКАЗАТЕЛЬНО ПО ИЗМЕРЕНИЯМ: у 23 маркеров интервал отличается между
    лабораториями, поэтому ref живёт в точке серии, а не на маркере;
  * делит маркеры на числовые (kind=num) и качественные (kind=qual —
    копрограмма/серология/мазки: значение текстом, без бара и графика);
  * раскладывает по категориям и присваивает стабильные короткие id
    (на них ссылается meds.json -> affects);
  * подтягивает лабораторию join'ом по дате из labs_text_results.csv
    (в master_labs колонки нет), отфильтровывая мусор вида
    «2024-03-14 Рентгенография-1»;
  * вес/рост/ИМТ НЕ идут в labs.json — это живые данные vitals.json
    (страница даёт их дописывать); их мастер — на Synology, сюда только
    разовый --seed-vitals <путь>.

Режимы:
    python3 build_health_json.py                 # CSV -> labs.json на Synology (перезапись)
    python3 build_health_json.py --seed-vitals ~/…/Claude-Memory/Health/vitals.json
    python3 build_health_json.py --selftest      # юнит-тесты парсеров

Stdlib only.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, OrderedDict
from datetime import date
from pathlib import Path

# Вход — Mac: сюда экспортирует Ornament, медицинским данным в GitHub не
# место. Выход — Synology, тот же Claude-Memory/Health/, куда пишут
# health-meds и страница напрямую (без промежуточного Mac-этапа и деплоя).
DATA = Path.home() / "Documents/Claude/Projects/Health/данные"
SRC_CSV = DATA / "master_labs.csv"
TEXT_CSV = DATA / "labs_text_results.csv"
SYN_HEALTH = Path.home() / "Library/CloudStorage/SynologyDrive-home/Claude-Memory/Health"
OUT_LABS = SYN_HEALTH / "labs.json"

SCHEMA = "health-labs@1"

# ─────────────────────────── единицы ───────────────────────────
# Ornament экспортирует с опечатками — чиним, иначе они видны пользователю.
UNIT_FIX = {
    "ммол/л": "ммоль/л",
    "мкмол/л": "мкмоль/л",
    "нмол/л": "нмоль/л",
    "пмол/л": "пмоль/л",
    "мМЕ/л": "мМЕ/л",
    "×100%": "",       # МНО и цветовой показатель безразмерны
    "ед. pH": "",
}


def norm_unit(u: str) -> str:
    u = (u or "").strip()
    if u in ("—", "-", ""):
        return ""
    return UNIT_FIX.get(u, u)


# ─────────────────────────── категории ───────────────────────────
CATEGORIES = [
    ("cbc", "Общий анализ крови"),
    ("biochem", "Биохимия крови"),
    ("lipid", "Липидный профиль"),
    ("horm", "Гормоны"),
    ("vit", "Витамины и микроэлементы"),
    ("coagul", "Коагулограмма"),
    ("auto", "Аутоиммунные и аллергия"),
    ("urine", "Моча"),
    ("stool", "Копрограмма"),
    ("serology", "Инфекции"),
    ("micro", "Микрофлора"),
    ("vision", "Зрение"),
]
CATEGORY_NAMES = dict(CATEGORIES)

# Порядок важен: первое совпадение выигрывает.
CATEGORY_RULES = [
    (r"\bмазок\b", "micro"),
    (r"\bкал\b", "stool"),
    (r"\bмоча\b|\bмочи\b", "urine"),
    (r"трепонеме|гепатит|вич|к вирусу кори|антиэритроцитарные", "serology"),
    (r"тромбиновое|протромбин|фибриноген|международный коэффициент", "coagul"),
    (r"тиреопероксидазе|тиреоглобулину|иммуноглобулин e", "auto"),
    (r"visus|авторефрактометр|межзрачков", "vision"),
    (r"холестерин|триглицериды", "lipid"),
    (r"тиреотропный|т4 |т3 |тестостерон|кортизол|пролактин|инсулин", "horm"),
    (r"витамин|фолиевая|железо|ферритин|трансферрин|железосвязывающая|гомоцистеин", "vit"),
    (
        r"гемоглобин, кровь|эритроцит|лейкоцит|тромбоцит|тромбокрит|базофил|лимфоцит|моноцит"
        r"|нейтрофил|эозинофил|гематокрит|соэ|корпускулярн|средняя концентрация"
        r"|распределения|нормобласт|гранулоцит|ретикулоцит|цветовой показатель",
        "cbc",
    ),
]


def categorize(name: str) -> str:
    low = name.lower()
    for pattern, key in CATEGORY_RULES:
        if re.search(pattern, low):
            return key
    return "biochem"


# ─────────────────────────── идентификаторы ───────────────────────────
# Короткие латинские id для ходовых маркеров — на них ссылается meds.affects.
# Остальным — транслит-слаг (детерминированный, стабильный).
ID_MAP = {
    "Глюкоза натощак": "glucose",
    "Гемоглобин гликозилированный": "hba1c",
    "Холестерин": "chol",
    "Холестерин ЛПВП": "hdl",
    "Холестерин ЛПНП": "ldl",
    "Холестерин не-ЛПВП": "nonhdl",
    "Триглицериды": "tg",
    "Аланинаминотрансфераза": "alt",
    "Аспартатаминотрансфераза": "ast",
    "Гамма-глютамилтранспептидаза": "ggt",
    "Щелочная фосфатаза": "alp",
    "Билирубин общий, кровь": "bili",
    "Билирубин прямой, кровь": "bili_direct",
    "Билирубин непрямой, кровь": "bili_indirect",
    "Общий белок, сыворотка": "tp",
    "Альбумин, сыворотка": "alb",
    "Креатинин, сыворотка": "creat",
    "Мочевина, сыворотка": "urea",
    "С-реактивный белок": "crp",
    "Лактатдегидрогеназа общая": "ldh",
    "Креатинкиназа общая": "ck",
    "Альфа-амилаза панкреатическая, кровь": "amylase",
    "Калий, сыворотка": "k",
    "Натрий, сыворотка": "na",
    "Кальций, сыворотка": "ca",
    "Хлор, сыворотка": "cl",
    "Фосфор, сыворотка": "p",
    "Гомоцистеин": "hcy",
    "Тиреотропный гормон": "tsh",
    "Т4 свободный": "ft4",
    "Тестостерон общий": "test",
    "Витамин В12": "b12",
    "Фолиевая кислота": "folate",
    "Железо, сыворотка": "iron",
    "Ферритин": "ferr",
    "Трансферрин": "transferrin",
    "Насыщение трансферрина": "tsat",
    "Общая железосвязывающая способность": "tibc",
    "Латентная железосвязывающая способность": "uibc",
    "Антитела к тиреопероксидазе": "tpo",
    "Антитела к тиреоглобулину": "tg_ab",
    "Иммуноглобулин E, сыворотка": "ige",
    "Гемоглобин, кровь": "hgb",
    "Эритроциты, кровь": "rbc",
    "Лейкоциты, кровь": "wbc",
    "Тромбоциты": "plt",
    "Гематокрит": "hct",
    "СОЭ по Вестергрену": "esr",
    "СОЭ по Панченкову": "esr_p",
    "Лимфоциты": "lym",
    "Лимфоциты, %": "lym_pct",
    "Нейтрофилы": "neu",
    "Нейтрофилы, %": "neu_pct",
    "Моноциты": "mono",
    "Моноциты, %": "mono_pct",
    "Эозинофилы": "eos",
    "Эозинофилы, %": "eos_pct",
    "Базофилы": "baso",
    "Базофилы, %": "baso_pct",
    "Средний корпускулярный объем": "mcv",
    "Средний корпускулярный гемоглобин": "mch",
    "Средняя концентрация гемоглобина": "mchc",
    "Тромбокрит": "pct",
    "Средний объем тромбоцита": "mpv",
    "Ретикулоциты": "retic",
    "Активированное частичное тромбиновое время": "aptt",
    "Международный коэффициент нормализации": "inr",
    "Протромбин по Квику": "pt_quick",
    "Протромбиновое время": "pt",
    "Тромбиновое время": "tt",
    "Фибриноген": "fibrinogen",
}

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def slugify(name: str) -> str:
    out = []
    for ch in name.lower():
        if ch in TRANSLIT:
            out.append(TRANSLIT[ch])
        elif ch.isalnum():
            out.append(ch)
        else:
            out.append("_")
    slug = re.sub(r"_+", "_", "".join(out)).strip("_")
    return slug[:44]


def make_ids(names) -> dict:
    """Имя -> уникальный id. Коллизии транслита разводятся суффиксом."""
    ids, used = {}, set()
    for name in names:
        base = ID_MAP.get(name) or slugify(name)
        cand, n = base, 2
        while cand in used:
            cand = f"{base}_{n}"
            n += 1
        used.add(cand)
        ids[name] = cand
    return ids


# ─────────────────────────── референсы и значения ───────────────────────────
DASHES = "−–—-"
RANGE_RE = re.compile(rf"^\s*(-?[\d.,]+\s*[KКkк]?)\s*[{DASHES}]\s*(-?[\d.,]+\s*[KКkк]?)\s*$")
OP_RE = re.compile(rf"^\s*(<|>|≤|≥)\s*(-?[\d.,]+)\s*$")

QUAL_REF_WORDS = (
    "не обнаружено", "обнаружено", "отрицательно", "положительно", "отсутствует",
    "отсутствуют", "отрицат", "положит", "ед. в преп", "незначит", "оформлен",
    "обычный", "коричневый", "смотри текст",
)


def _num(tok: str):
    """«10K» -> 10000.0, «4,94» -> 4.94, иначе None."""
    tok = (tok or "").strip().replace(",", ".")
    mult = 1.0
    if tok and tok[-1] in "KКkк":
        mult, tok = 1000.0, tok[:-1].strip()
    try:
        return float(tok) * mult
    except ValueError:
        return None


def parse_value(raw: str):
    """-> (число|None, текст|None). Числовое значение и текстовое — раздельно."""
    raw = (raw or "").strip()
    if not raw or raw == "—":
        return None, None
    v = _num(raw)
    if v is not None:
        return v, None
    return None, raw


def parse_ref(raw: str):
    """Референс измерения -> dict|None.

    {'low':x,'high':y} | {'op':'<','value':x} | {'text':'Не обнаружено'} | None
    """
    raw = (raw or "").strip()
    if not raw or raw in ("—", "-"):
        return None
    m = RANGE_RE.match(raw)
    if m:
        lo, hi = _num(m.group(1)), _num(m.group(2))
        if lo is not None and hi is not None:
            return {"low": lo, "high": hi}
    m = OP_RE.match(raw)
    if m:
        v = _num(m.group(2))
        if v is not None:
            return {"op": m.group(1), "value": v}
    v = _num(raw)
    if v is not None:
        # Голое число без диапазона/оператора — это конвенция Ornament для
        # порога-минимума (проверено на остроте зрения: референс «1.0» при
        # факте 0.8 даёт статус «ниже нормы», при 1.0 — «норма»), а не точка
        # с нулевой шириной — {"low":v,"high":v} рендерился бы как «1–1».
        return {"op": "≥", "value": v}
    low = raw.lower()
    if any(w in low for w in QUAL_REF_WORDS):
        return {"text": raw}
    return {"text": raw}


STATUS_MAP = {
    "Норма": "norm",
    "Выше нормы": "high",
    "Ниже нормы": "low",
    "—": "na",
    "": "na",
}


def parse_date(d: str) -> str:
    """DD.MM.YYYY -> YYYY-MM-DD."""
    p = (d or "").strip().split(".")
    if len(p) != 3:
        raise ValueError(f"нераспознанная дата: {d!r}")
    return f"{int(p[2]):04d}-{int(p[1]):02d}-{int(p[0]):02d}"


# ─────────────────────────── лаборатории ───────────────────────────
# В labs_text_results.csv поле lab_name местами содержит имя файла-исследования
# («2024-03-14 Рентгенография-1»), а не лабораторию — такие отбрасываем.
JUNK_LAB_RE = re.compile(r"^\d{4}-\d{2}-\d{2}|рентген|экг|узи|энмг|цдс", re.I)

LAB_PRETTY = {
    "ГЕМОТЕСТ": "Гемотест",
    "ГКБ № 67 ИМ. Л.А.ВОРОХОБОВА ДЗМ": "ГКБ № 67",
    "Клиника Эксперт Ростов": "Клиника Эксперт",
}


def load_labs_by_date(path: Path) -> dict:
    if not path.exists():
        return {}
    by_date = {}
    with path.open(encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            name = (row.get("lab_name") or "").strip()
            iso = (row.get("date") or "").strip()
            if not name or not iso or JUNK_LAB_RE.search(name):
                continue
            by_date.setdefault(iso, Counter())[name] += 1
    # одна дата -> одна лаборатория (самая частая)
    return {d: LAB_PRETTY.get(c.most_common(1)[0][0], c.most_common(1)[0][0])
            for d, c in by_date.items()}


# ─────────────────────────── витальные ───────────────────────────
VITAL_NAMES = {"Вес, усредненный": "weight", "Рост": "height",
               "Индекс массы тела, усредненный": "bmi"}


# ─────────────────────────── сборка ───────────────────────────
def build(src: Path, text_src: Path):
    with src.open(encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise SystemExit("master_labs.csv пуст")

    lab_by_date = load_labs_by_date(text_src)

    person = {"sex": "m" if rows[0].get("пол") == "Мужской" else "f",
              "age_at_export": int(rows[0].get("возраст") or 0)}

    grouped, vitals_rows, seen = OrderedDict(), [], set()
    for r in rows:
        name = (r.get("биомаркер") or "").strip()
        if not name:
            continue
        if name in VITAL_NAMES:
            vitals_rows.append(r)
            continue
        key = (name, r.get("дата_измерения"))
        if key in seen:            # дубль (маркер, дата) — берём первый
            continue
        seen.add(key)
        grouped.setdefault(name, []).append(r)

    ids = make_ids(grouped.keys())
    biomarkers, warnings = [], []

    for name, rs in grouped.items():
        series = []
        for r in rs:
            iso = parse_date(r["дата_измерения"])
            value, text = parse_value(r.get("значение"))
            series.append({
                "date": iso,
                "value": value,
                "text": text,
                "unit": norm_unit(r.get("единицы")),
                "ref": parse_ref(r.get("референсы")),
                "status": STATUS_MAP.get((r.get("статус") or "").strip(), "na"),
                "lab": lab_by_date.get(iso),
            })
        series.sort(key=lambda s: s["date"])

        numeric = [s for s in series if s["value"] is not None]
        last = series[-1]
        # kind=num только если ВСЕ точки числовые и у последней парсится интервал.
        last_ref = last["ref"] or {}
        has_range = "low" in last_ref or "op" in last_ref
        kind = "num" if (len(numeric) == len(series) and has_range) else "qual"
        if 0 < len(numeric) < len(series):
            warnings.append(f"смешанный маркер (число+текст): {name}")

        units = [s["unit"] for s in series if s["unit"]]
        biomarkers.append({
            "id": ids[name],
            "name": name,
            "category": categorize(name),
            "kind": kind,
            "unit": units[-1] if units else "",
            "ref": last["ref"],            # для бара — референс ПОСЛЕДНЕГО измерения
            "series": series,
        })

    biomarkers.sort(key=lambda b: (b["category"], b["name"]))
    used_cats = {b["category"] for b in biomarkers}
    doc = {
        "schema": SCHEMA,
        "generated": date.today().isoformat(),
        "source": src.name,
        "person": person,
        "categories": [{"key": k, "name": n} for k, n in CATEGORIES if k in used_cats],
        "biomarkers": biomarkers,
    }
    return doc, vitals_rows, warnings


def seed_vitals(vitals_rows, out: Path) -> str:
    """Каркас vitals.json из CSV. НЕ затирает существующий (это живой файл)."""
    if out.exists():
        return f"· vitals.json уже есть — не трогаю (живой файл, правится страницей)"
    height, weights = None, []
    for r in vitals_rows:
        kind = VITAL_NAMES[r["биомаркер"]]
        v, _ = parse_value(r.get("значение"))
        if v is None:
            continue
        if kind == "height":
            height = v
        elif kind == "weight":
            weights.append({"date": parse_date(r["дата_измерения"]), "kg": v})
    weights.sort(key=lambda w: w["date"])
    doc = {
        "schema": "health-vitals@1",
        "updated": date.today().isoformat(),
        "height_cm": height,
        "weight": weights,
    }
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return f"✓ {out.name}: рост {height} см, вес — {len(weights)} измер."


# ─────────────────────────── selftest ───────────────────────────
def selftest() -> int:
    ok, fail = 0, 0

    def check(what, got, want):
        nonlocal ok, fail
        if got == want:
            ok += 1
        else:
            fail += 1
            print(f"  ✗ {what}\n      получено: {got!r}\n      ожидалось: {want!r}")

    # референсы
    check("диапазон", parse_ref("35 − 50"), {"low": 35.0, "high": 50.0})
    check("диапазон дробный", parse_ref("18.5 − 29.99"), {"low": 18.5, "high": 29.99})
    check("диапазон 10K", parse_ref("0.00 − 10K"), {"low": 0.0, "high": 10000.0})
    check("односторонний <", parse_ref("< 21"), {"op": "<", "value": 21.0})
    check("нет референса", parse_ref("—"), None)
    check("пустой референс", parse_ref(""), None)
    check("качественный", parse_ref("Не обнаружено"), {"text": "Не обнаружено"})
    check("качественный 2", parse_ref("отрицат."), {"text": "отрицат."})
    check("голое число = порог-минимум", parse_ref("1.0"), {"op": "≥", "value": 1.0})

    # значения
    check("значение число", parse_value("4.94"), (4.94, None))
    check("значение запятая", parse_value("4,94"), (4.94, None))
    check("значение текст", parse_value("Единичные в поле зрения"),
          (None, "Единичные в поле зрения"))
    check("значение диапазон-текст", parse_value("1-3-5"), (None, "1-3-5"))
    check("значение пусто", parse_value("—"), (None, None))

    # единицы
    check("опечатка ммол", norm_unit("ммол/л"), "ммоль/л")
    check("опечатка мкмол", norm_unit("мкмол/л"), "мкмоль/л")
    check("единица без правки", norm_unit("г/л"), "г/л")
    check("безразмерный", norm_unit("×100%"), "")
    check("прочерк", norm_unit("—"), "")

    # даты
    check("дата", parse_date("14.10.2025"), "2025-10-14")
    check("дата одноразрядная", parse_date("08.03.2023"), "2023-03-08")

    # категории
    check("кат. кал", categorize("Детрит, кал качественно"), "stool")
    check("кат. кальций НЕ кал", categorize("Кальций, сыворотка"), "biochem")
    check("кат. моча", categorize("Белок, моча качественно"), "urine")
    check("кат. глюкоза натощак", categorize("Глюкоза натощак"), "biochem")
    check("кат. эритроциты кровь", categorize("Эритроциты, кровь"), "cbc")
    check("кат. эритроциты кал", categorize("Эритроциты, кал качественно"), "stool")
    check("кат. липиды", categorize("Холестерин ЛПНП"), "lipid")
    check("кат. гормон", categorize("Тиреотропный гормон"), "horm")
    check("кат. коагулограмма", categorize("Протромбиновое время"), "coagul")
    check("кат. серология", categorize("Антитела к ВИЧ-1 и ВИЧ-2, антиген p24 ВИЧ-1, качественно"), "serology")
    check("кат. мазок", categorize("Neisseria subflava, мазок из рото/носоглотки"), "micro")
    check("кат. HbA1c не ОАК", categorize("Гемоглобин гликозилированный"), "biochem")
    check("кат. гемоглобин кровь = ОАК", categorize("Гемоглобин, кровь"), "cbc")
    check("кат. витамины", categorize("Ферритин"), "vit")
    # тромбокрит ≠ тромбоцит по подстроке — но это тромбоцитарный индекс, не биохимия
    check("кат. тромбокрит = ОАК", categorize("Тромбокрит"), "cbc")
    check("кат. МНО = коагулограмма", categorize("Международный коэффициент нормализации"), "coagul")
    check("кат. острота зрения", categorize("Острота зрения (Visus), OD, без коррекции"), "vision")
    check("кат. авторефрактометрия", categorize("Авторефрактометрия, OD, sph"), "vision")
    check("кат. межзрачковое расстояние", categorize("Межзрачковое расстояние (PD)"), "vision")

    # id
    check("id из карты", make_ids(["Глюкоза натощак"])["Глюкоза натощак"], "glucose")
    check("id транслитом", make_ids(["Детрит, кал качественно"])["Детрит, кал качественно"],
          "detrit_kal_kachestvenno")
    dup = make_ids(["Глюкоза натощак", "Глюкоза натощак "])
    check("id уникальны", len(set(dup.values())), 2)

    # мусорные лаборатории
    check("мусор-лаб рентген", bool(JUNK_LAB_RE.search("2024-03-14 Рентгенография-1")), True)
    check("мусор-лаб ЭКГ", bool(JUNK_LAB_RE.search("2025-10-16 ЭКГ")), True)
    check("нормальная лаб", bool(JUNK_LAB_RE.search("ГЕМОТЕСТ")), False)

    print(f"\n{'✓ selftest OK' if not fail else '✗ ЕСТЬ ПАДЕНИЯ'}: {ok} проверок, {fail} падений")
    return 1 if fail else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="master_labs.csv -> labs.json")
    ap.add_argument("--src", type=Path, default=SRC_CSV)
    ap.add_argument("--text-src", type=Path, default=TEXT_CSV)
    ap.add_argument("--out", type=Path, default=OUT_LABS)
    ap.add_argument("--seed-vitals", metavar="ФАЙЛ", type=Path,
                    help="разово создать vitals.json ПО УКАЗАННОМУ пути (обычно "
                         "…/Claude-Memory/Health/vitals.json). Путь обязателен: "
                         "мастер живых файлов один — на Synology, и раньше рядом "
                         "с CSV тихо копился второй, устаревающий")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--legacy-overwrite", action="store_true",
                    help="АРХИВ: разрешить перезапись labs.json из CSV (только на пустом/"
                         "чистом labs.json — точки intake не затираются никогда)")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.legacy_overwrite:
        raise SystemExit("✗ Пересборка labs.json из CSV отключена (2026-09-29): labs.json — главный "
                         "файл, новые данные вносит scripts/intake.py. Архивный режим — --legacy-overwrite.")
    if args.out.exists():
        cur = json.loads(args.out.read_text(encoding="utf-8"))
        intake_pts = sum(1 for b in cur.get("biomarkers", []) for s in b.get("series", [])
                         if s.get("study") or s.get("src"))
        if intake_pts:
            raise SystemExit(f"✗ В {args.out.name} {intake_pts} точек, внесённых/привязанных intake.py — "
                             "пересборка из CSV их сотрёт. Отказ.")

    doc, vitals_rows, warnings = build(args.src, args.text_src)
    args.out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")

    bm = doc["biomarkers"]
    n_num = sum(1 for b in bm if b["kind"] == "num")
    n_pts = sum(len(b["series"]) for b in bm)
    n_chart = sum(1 for b in bm if b["kind"] == "num" and len(b["series"]) >= 3)
    n_lab = sum(1 for b in bm for s in b["series"] if s["lab"])
    print(f"✓ {args.out.name}: {len(bm)} маркеров "
          f"({n_num} числовых / {len(bm) - n_num} качественных), {n_pts} измерений")
    print(f"  графики (3+ точек): {n_chart} · лаборатория известна: {n_lab}/{n_pts}")
    by_cat = Counter(b["category"] for b in bm)
    print("  по категориям: " + ", ".join(
        f"{CATEGORY_NAMES[k]} {v}" for k, v in by_cat.most_common()))
    if args.seed_vitals:
        print(seed_vitals(vitals_rows, args.seed_vitals))
    for w in warnings:
        print(f"  ⚠ {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
