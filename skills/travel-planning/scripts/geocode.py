#!/usr/bin/env python3
"""geocode.py — Tier-1 детерминированный геокодер маршрутных точек (Stage 6).

Контент-стадия Stage 6 резолвит координаты двухтиерно:

  • **Tier 1 (этот скрипт, детерминированный).** На вход — список имён точек
    (регионы / базы / ключевые POI из устаканенного 5_vX). Читает забандленный
    газетир `data/gazetteer.json` (Natural Earth populated places: name / ascii /
    lat / lon / country). Матчит Russian↔English через транслит + alias + fuzzy,
    опц. в пределах указанных стран. Выход — найденные точки с координатами
    (`source: "gazetteer"`) + список ненайденных.
  • **Tier 2 (модель, не здесь).** Ненайденные точки доопределяет Stage 6-модель
    своим знанием городов (`source: "model"`, пометка «ориентир, не навигация»).

Авторитет координаты — газетир (реальные данные Natural Earth), не модель: даже
если LLM подсказывает английское имя (`en`), сами `lat/lon` берутся из газетира.
Это и держит Tier-1 детерминированным и ревьюабельным по полю `source`.

Хит-рейт: крупные города высоко (Ханой / Сеул / Пусан / Буэнос-Айрес ✓
проверено), деревни низко (Сапа / Мукангчай / Эль-Чальтен ✗ → Tier 2).

Stdlib only.

Формат входа (JSON через stdin или `--points`):
    {
      "points": [
        "Ханой",                                  # просто имя
        {"name": "Кёнджу", "en": "Gyeongju"},     # имя + английская подсказка
        {"name": "Сапа", "country": "Vietnam"}    # переопределить страну точки
      ],
      "countries": ["Vietnam"]                      # опц. глобальное ограничение
    }

Формат выхода (JSON в stdout):
    {
      "resolved": {"Ханой": {"lat": 21.03, "lon": 105.85, "source": "gazetteer",
                             "matched": "Hanoi", "country": "Vietnam"}},
      "unresolved": ["Сапа"],
      "diagnostic": {"requested": 2, "resolved": 1, "tier1_hit_rate": 0.5,
                     "gazetteer_size": 7342}
    }

CLI:
    geocode.py < points.json
    geocode.py --points '{"points": ["Ханой", "Сеул"]}'
    geocode.py --selftest
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
import unicodedata
from pathlib import Path

# Газетир — ассет КОНТЕНТ-стадии (D4): `scripts/data/gazetteer.json`. Контур
# стран (`ne_countries.geojson`) — ассет рендера, лежит отдельно в export/data/.
GAZETTEER_PATH = Path(__file__).resolve().parent / "data" / "gazetteer.json"

# Порог fuzzy-резолва (difflib ratio). Ниже — точка идёт в Tier 2. Подобран так,
# чтобы транслит крупных городов проходил (Сеул→seul≈seoul 0.89), а шум — нет.
# В пределах страны (когда `countries`/`country` заданы) кандидатов мало —
# ложные срабатывания маловероятны даже на 0.80.
DEFAULT_THRESHOLD = 0.80

# Кириллица → латиница (нижний регистр). Practical-translit (не строгий ГОСТ):
# цель — сблизить русское написание с ascii-именем газетира под fuzzy.
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

# Alias-карта для точек, где транслит далёк от ascii-имени (особенно корейские/
# азиатские города). Ключ — нормализованное русское имя; значение — английское,
# по которому матчим в газетире. Не исчерпывающая — основная сеть это fuzzy;
# alias лишь подстраховывает валидированный калибровочный набор и частые города.
_ALIAS: dict[str, str] = {
    # Корея
    "сеул": "Seoul", "пусан": "Busan", "кёнджу": "Gyeongju", "кенджу": "Gyeongju",
    "чонджу": "Jeonju", "сокчо": "Sokcho", "инчхон": "Incheon", "тэгу": "Daegu",
    "кванджу": "Gwangju", "тэджон": "Daejeon", "сораксан": "Sokcho",
    # Вьетнам
    "ханой": "Hanoi", "хошимин": "Ho Chi Minh City", "дананг": "Da Nang",
    "хюэ": "Hue", "хуэ": "Hue", "нячанг": "Nha Trang", "хайфон": "Hai Phong",
    # Аргентина
    "буэносайрес": "Buenos Aires", "элькалафате": "El Calafate",
    "ушуая": "Ushuaia", "ушуайя": "Ushuaia", "кордова": "Cordoba",
    "мендоса": "Mendoza", "барилоче": "San Carlos de Bariloche",
}

# Alias-карта стран (русское / разговорное → ascii adm0name газетира).
_COUNTRY_ALIAS: dict[str, str] = {
    "вьетнам": "Vietnam", "корея": "South Korea", "южная корея": "South Korea",
    "республика корея": "South Korea", "аргентина": "Argentina",
    "камбоджа": "Cambodia", "лаос": "Laos", "таиланд": "Thailand",
    "тайланд": "Thailand", "япония": "Japan", "китай": "China",
    "непал": "Nepal", "индия": "India", "чили": "Chile", "перу": "Peru",
}


# ─── Нормализация / транслит ───────────────────────────────────────────────


def _strip_accents(s: str) -> str:
    """Убрать диакритику (Córdoba → Cordoba) через NFKD."""
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c))


def normalize(s: str) -> str:
    """Каноничная форма имени для сравнения: lower, без диакритики, только alnum.

    «Buenos Aires» / «buenos-aires» → `buenosaires`; «Кёнджу» → `кенджу`
    (кириллица сохраняется — транслит делается отдельно). Пробелы, дефисы и
    пунктуация выкидываются — это сближает многословные имена.
    """
    s = _strip_accents(s).lower().replace("ё", "е")
    return "".join(ch for ch in s if ch.isalnum())


def translit(s: str) -> str:
    """Кириллица → латиница (по таблице), затем normalize."""
    out = "".join(_TRANSLIT.get(ch, ch) for ch in s.lower())
    return normalize(out)


def _strip_descriptor(name: str) -> str:
    """Срезать хвост-описатель: «Сапа / окрестности», «Ниньбинь (Чанган)»,
    «Эль-Чальтен — база» → ведущая часть. Точка резолвится по главному имени."""
    for sep in ("/", "(", "—", "–", ",", ":"):
        if sep in name:
            name = name.split(sep, 1)[0]
    return name.strip()


# ─── Газетир ───────────────────────────────────────────────────────────────


def load_gazetteer(path: str | Path | None = None) -> list[dict]:
    """Загрузить газетир. Каждая запись: {n, a, lat, lon, c}."""
    p = Path(path) if path else GAZETTEER_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def _candidate_forms(entry: dict) -> set[str]:
    """Нормализованные формы имени записи газетира (native `n` + ascii `a`)."""
    return {normalize(entry["n"]), normalize(entry["a"])}


def resolve_countries(countries, gazetteer: list[dict]) -> set[str]:
    """Список запрошенных стран → множество canonical adm0name газетира.

    Матч: alias → exact normalized → fuzzy по множеству стран газетира.
    Пустой/None вход → пустое множество (без ограничения).
    """
    if not countries:
        return set()
    gaz_countries = {r["c"] for r in gazetteer if r["c"]}
    norm_to_canon = {normalize(c): c for c in gaz_countries}
    out: set[str] = set()
    for raw in countries:
        if not raw:
            continue
        low = str(raw).strip().lower()
        if low in _COUNTRY_ALIAS:
            out.add(_COUNTRY_ALIAS[low])
            continue
        nq = normalize(raw)
        if nq in norm_to_canon:
            out.add(norm_to_canon[nq])
            continue
        # fuzzy по странам
        best, best_score = None, 0.0
        for ncan, canon in norm_to_canon.items():
            score = difflib.SequenceMatcher(None, nq, ncan).ratio()
            if score > best_score:
                best, best_score = canon, score
        if best and best_score >= 0.86:
            out.add(best)
    return out


def _query_forms(name: str, en_hint: str | None) -> list[str]:
    """Все нормализованные формы запроса в порядке надёжности.

    1. английская подсказка (если есть) — самая надёжная;
    2. alias по нормализованному русскому имени;
    3. сам normalize(name) (если уже латиница — точный матч);
    4. транслит кириллицы.
    """
    base = _strip_descriptor(name)
    forms: list[str] = []
    if en_hint:
        forms.append(normalize(en_hint))
    nb = normalize(base)
    if nb in _ALIAS:
        forms.append(normalize(_ALIAS[nb]))
    forms.append(nb)
    tr = translit(base)
    if tr and tr != nb:
        forms.append(tr)
    # уникализируем, сохраняя порядок
    seen: set[str] = set()
    uniq: list[str] = []
    for f in forms:
        if f and f not in seen:
            seen.add(f)
            uniq.append(f)
    return uniq


def _match_one(name: str, en_hint: str | None, candidates: list[dict],
               threshold: float) -> dict | None:
    """Найти лучшую запись газетира для одной точки. None — не дотянули.

    Точный матч любой формы запроса к любой форме кандидата = score 1.0;
    иначе максимум difflib-ratio. Возвращает {lat, lon, source, matched, country}.
    """
    forms = _query_forms(name, en_hint)
    if not forms:
        return None
    best_entry = None
    best_score = 0.0
    for entry in candidates:
        cand_forms = _candidate_forms(entry)
        for qf in forms:
            if qf in cand_forms:
                score = 1.0
            else:
                score = max(difflib.SequenceMatcher(None, qf, cf).ratio()
                            for cf in cand_forms)
            if score > best_score:
                best_score, best_entry = score, entry
                if score == 1.0:
                    break
        if best_score == 1.0:
            break
    if best_entry is None or best_score < threshold:
        return None
    return {
        "lat": best_entry["lat"],
        "lon": best_entry["lon"],
        "source": "gazetteer",
        "matched": best_entry["n"],
        "country": best_entry["c"],
        "score": round(best_score, 3),
    }


def geocode(points, countries=None, *, gazetteer: list[dict] | None = None,
            threshold: float = DEFAULT_THRESHOLD) -> dict:
    """Резолвить список точек по газетиру (Tier-1).

    `points` — список строк или dict'ов `{name, en?, country?}`.
    `countries` — опц. глобальное ограничение по странам.
    Возвращает {resolved, unresolved, diagnostic}.
    """
    gaz = gazetteer if gazetteer is not None else load_gazetteer()
    global_countries = resolve_countries(countries, gaz)
    by_country: dict[str, list[dict]] = {}
    for r in gaz:
        by_country.setdefault(r["c"], []).append(r)

    resolved: dict[str, dict] = {}
    unresolved: list[str] = []
    for pt in points:
        if isinstance(pt, dict):
            name = pt.get("name") or ""
            en = pt.get("en")
            pt_country = pt.get("country")
        else:
            name, en, pt_country = str(pt), None, None
        if not name.strip():
            continue
        # Кандидаты: страна точки → глобальное ограничение → весь газетир.
        if pt_country:
            cc = resolve_countries([pt_country], gaz)
        else:
            cc = global_countries
        if cc:
            candidates = [r for c in cc for r in by_country.get(c, [])]
        else:
            candidates = gaz
        hit = _match_one(name, en, candidates, threshold)
        if hit:
            resolved[name] = hit
        else:
            unresolved.append(name)

    requested = len(resolved) + len(unresolved)
    return {
        "resolved": resolved,
        "unresolved": unresolved,
        "diagnostic": {
            "requested": requested,
            "resolved": len(resolved),
            "tier1_hit_rate": round(len(resolved) / requested, 3) if requested else 0.0,
            "gazetteer_size": len(gaz),
            "countries_constraint": sorted(global_countries),
        },
    }


# ─── CLI ─────────────────────────────────────────────────────────────────


def _selftest() -> int:
    """Дымовой self-test на калибровочных городах."""
    gaz = load_gazetteer()
    out = geocode(
        ["Ханой", {"name": "Кёнджу", "en": "Gyeongju"}, "Сеул", "Пусан",
         "Буэнос-Айрес", {"name": "Сапа", "country": "Vietnam"}],
        countries=None, gazetteer=gaz,
    )
    res = out["resolved"]
    assert "Ханой" in res and res["Ханой"]["matched"] == "Hanoi", res.get("Ханой")
    assert "Сеул" in res and res["Сеул"]["matched"] == "Seoul", res.get("Сеул")
    assert "Пусан" in res and res["Пусан"]["matched"] == "Busan", res.get("Пусан")
    assert "Кёнджу" in res and res["Кёнджу"]["matched"] == "Gyeongju", res.get("Кёнджу")
    assert "Буэнос-Айрес" in res, res
    assert "Сапа" in out["unresolved"], out["unresolved"]
    print("selftest geocode: OK —", out["diagnostic"])
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="geocode.py",
        description="Tier-1 газетир-геокодер маршрутных точек Stage 6 (stdlib).",
    )
    p.add_argument("--points", help="JSON со списком точек (вместо stdin)")
    p.add_argument("--gazetteer", help="переопределить путь к gazetteer.json")
    p.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                   help=f"fuzzy-порог резолва (по умолчанию {DEFAULT_THRESHOLD})")
    p.add_argument("--selftest", action="store_true", help="дымовой self-test")
    args = p.parse_args(argv)

    if args.selftest:
        return _selftest()

    raw = args.points if args.points else sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"невалидный JSON на входе: {e}", file=sys.stderr)
        return 2
    if isinstance(payload, list):
        payload = {"points": payload}
    points = payload.get("points") or []
    countries = payload.get("countries")
    gaz = load_gazetteer(args.gazetteer) if args.gazetteer else load_gazetteer()
    out = geocode(points, countries, gazetteer=gaz, threshold=args.threshold)
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
