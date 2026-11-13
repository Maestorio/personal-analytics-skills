#!/usr/bin/env python3
"""Регрессионные тесты Tier-1 геокодера Stage 6 (scripts/geocode.py).

Покрывают:
  - normalize / translit / _strip_descriptor
  - resolve_countries (alias / exact / fuzzy)
  - geocode: калибровочные города (Ханой/Сеул/Пусан/Буэнос-Айрес ✓),
    деревни → unresolved (Сапа/Эль-Чальтен), en-подсказка, country-override,
    глобальное ограничение стран, source=gazetteer, авторитет координат
  - CLI (stdin JSON + --selftest)

Запуск из корня репозитория:
    python3 skills/travel-planning/tests/test_geocode.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "skills" / "travel-planning" / "scripts"
GEOCODE_PY = SCRIPTS_DIR / "geocode.py"

sys.path.insert(0, str(SCRIPTS_DIR))
import geocode  # noqa: E402


checks_run = 0
checks_failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global checks_run, checks_failed
    checks_run += 1
    if condition:
        print(f"  ✓ {name}")
    else:
        checks_failed += 1
        suffix = f" — {detail}" if detail else ""
        print(f"  ✗ {name}{suffix}")


# Газетир грузим один раз — переиспользуем во всех тестах.
GAZ = geocode.load_gazetteer()


# ─── 1. normalize / translit ───────────────────────────────────────────────


def test_normalize_translit():
    print("\n[1] normalize / translit / strip_descriptor")
    check("normalize убирает диакритику", geocode.normalize("Córdoba") == "cordoba")
    check("normalize схлопывает пробелы/дефисы",
          geocode.normalize("Buenos-Aires") == geocode.normalize("Buenos Aires") == "buenosaires")
    check("normalize ё→е", geocode.normalize("Кёнджу") == "кенджу")
    check("translit Сокчо→sokcho", geocode.translit("Сокчо") == "sokcho")
    check("translit Ханой→hanoy", geocode.translit("Ханой") == "hanoy")
    check("strip_descriptor «Сапа / окрестности» → Сапа",
          geocode._strip_descriptor("Сапа / окрестности") == "Сапа")
    check("strip_descriptor «Ниньбинь (Чанган)» → Ниньбинь",
          geocode._strip_descriptor("Ниньбинь (Чанган)") == "Ниньбинь")
    check("strip_descriptor «Эль-Чальтен — база» → Эль-Чальтен",
          geocode._strip_descriptor("Эль-Чальтен — база") == "Эль-Чальтен")


# ─── 2. resolve_countries ──────────────────────────────────────────────────


def test_resolve_countries():
    print("\n[2] resolve_countries")
    check("alias вьетнам→Vietnam",
          geocode.resolve_countries(["вьетнам"], GAZ) == {"Vietnam"})
    check("alias корея→South Korea",
          geocode.resolve_countries(["Корея"], GAZ) == {"South Korea"})
    check("exact Argentina",
          geocode.resolve_countries(["Argentina"], GAZ) == {"Argentina"})
    check("несколько стран",
          geocode.resolve_countries(["вьетнам", "Аргентина"], GAZ) == {"Vietnam", "Argentina"})
    check("пустой вход → пустое множество",
          geocode.resolve_countries(None, GAZ) == set())
    check("мусор не резолвится в страну",
          "Vietnam" not in geocode.resolve_countries(["zzzqqq"], GAZ))


# ─── 3. geocode — калибровочные города ─────────────────────────────────────


def test_geocode_calibration():
    print("\n[3] geocode — калибровочные города")
    out = geocode.geocode(
        ["Ханой", "Сеул", "Пусан", "Буэнос-Айрес"], gazetteer=GAZ,
    )
    res = out["resolved"]
    check("Ханой → Hanoi", res.get("Ханой", {}).get("matched") == "Hanoi", str(res.get("Ханой")))
    check("Сеул → Seoul", res.get("Сеул", {}).get("matched") == "Seoul", str(res.get("Сеул")))
    check("Пусан → Busan", res.get("Пусан", {}).get("matched") == "Busan", str(res.get("Пусан")))
    check("Буэнос-Айрес resolved", "Буэнос-Айрес" in res, str(out["unresolved"]))
    check("source=gazetteer", all(v["source"] == "gazetteer" for v in res.values()))
    check("координаты — числа из газетира",
          isinstance(res["Ханой"]["lat"], (int, float)) and 20 < res["Ханой"]["lat"] < 22,
          str(res["Ханой"]))
    check("hit_rate == 1.0 на 4 крупных", out["diagnostic"]["tier1_hit_rate"] == 1.0)


def test_geocode_villages_to_tier2():
    print("\n[4] geocode — деревни → unresolved (Tier 2)")
    out = geocode.geocode(["Сапа", "Эль-Чальтен", "Мукангчай"], gazetteer=GAZ)
    check("Сапа не найдена (→ Tier 2)", "Сапа" in out["unresolved"])
    check("Эль-Чальтен не найден (→ Tier 2)", "Эль-Чальтен" in out["unresolved"])
    check("ничего не зарезолвилось ложно", len(out["resolved"]) == 0, str(out["resolved"]))


def test_geocode_en_hint():
    print("\n[5] geocode — английская подсказка `en`")
    # Кёнджу/Чонджу через транслит далеки от ascii — en-подсказка чинит.
    out = geocode.geocode(
        [{"name": "Кёнджу", "en": "Gyeongju"}, {"name": "Чонджу", "en": "Jeonju"}],
        gazetteer=GAZ,
    )
    res = out["resolved"]
    check("Кёнджу+en → Gyeongju", res.get("Кёнджу", {}).get("matched") == "Gyeongju", str(res))
    check("Чонджу+en → Jeonju", res.get("Чонджу", {}).get("matched") == "Jeonju", str(res))
    check("ключ результата — русское имя (а не en)", "Кёнджу" in res)
    # Координата всё равно из газетира (авторитет — не модель).
    check("координата из газетира, не из en",
          35.5 < res["Кёнджу"]["lat"] < 36.2, str(res["Кёнджу"]))


def test_geocode_country_constraint():
    print("\n[6] geocode — ограничение по стране")
    # «La Paz» есть в Argentina/Bolivia/Honduras/Mexico; country точки разводит.
    out_ar = geocode.geocode([{"name": "La Paz", "country": "Argentina"}], gazetteer=GAZ)
    out_global = geocode.geocode(["La Paz"], gazetteer=GAZ)
    check("La Paz@Argentina резолвится в аргентинскую запись",
          out_ar["resolved"].get("La Paz", {}).get("country") == "Argentina",
          str(out_ar["resolved"].get("La Paz")))
    check("глобальный La Paz тоже резолвится (любая страна)",
          "La Paz" in out_global["resolved"])
    # Глобальное ограничение стран в diagnostic.
    out_c = geocode.geocode(["Сеул"], countries=["Корея"], gazetteer=GAZ)
    check("countries_constraint отражает South Korea",
          out_c["diagnostic"]["countries_constraint"] == ["South Korea"])


def test_geocode_korea_full_route():
    print("\n[7] geocode — корейский маршрут с alias")
    # Сеул/Сокчо/Пусан — через alias/translit; Кёнджу/Чонджу — alias.
    out = geocode.geocode(
        ["Сеул", "Сокчо", "Кёнджу", "Пусан", "Чонджу"], countries=["Корея"],
        gazetteer=GAZ,
    )
    res = out["resolved"]
    check("Сокчо → Sokcho (точный транслит)", res.get("Сокчо", {}).get("matched") == "Sokcho")
    check("Кёнджу → Gyeongju (alias)", res.get("Кёнджу", {}).get("matched") == "Gyeongju")
    check("Чонджу → Jeonju (alias)", res.get("Чонджу", {}).get("matched") == "Jeonju")
    check("все 5 корейских точек резолвятся", len(res) == 5, str(out["unresolved"]))


def test_geocode_empty_and_blank():
    print("\n[8] geocode — пустой вход / пустые имена")
    check("пустой список → пусто",
          geocode.geocode([], gazetteer=GAZ)["resolved"] == {})
    out = geocode.geocode(["", "   ", "Ханой"], gazetteer=GAZ)
    check("пустые имена пропущены, Ханой резолвится",
          list(out["resolved"]) == ["Ханой"])


# ─── 9. CLI ─────────────────────────────────────────────────────────────────


def test_cli():
    print("\n[9] CLI")
    PY = sys.executable
    # stdin JSON
    payload = json.dumps({"points": ["Ханой", "Сеул"], "countries": ["Вьетнам", "Корея"]})
    r = subprocess.run([PY, str(GEOCODE_PY)], input=payload,
                       capture_output=True, text=True)
    check("CLI stdin exit 0", r.returncode == 0, r.stderr)
    try:
        out = json.loads(r.stdout)
        check("CLI вернул resolved Ханой", "Ханой" in out["resolved"])
    except Exception as e:
        check("CLI выдал валидный JSON", False, str(e))
    # --points
    r2 = subprocess.run([PY, str(GEOCODE_PY), "--points", json.dumps(["Сеул"])],
                        capture_output=True, text=True)
    check("CLI --points exit 0", r2.returncode == 0, r2.stderr)
    # список как top-level (без обёртки points)
    check("CLI принимает список верхним уровнем",
          "Сеул" in json.loads(r2.stdout)["resolved"])
    # selftest
    r3 = subprocess.run([PY, str(GEOCODE_PY), "--selftest"],
                        capture_output=True, text=True)
    check("CLI --selftest exit 0", r3.returncode == 0, r3.stderr)
    # невалидный JSON → exit 2
    r4 = subprocess.run([PY, str(GEOCODE_PY)], input="{not json",
                        capture_output=True, text=True)
    check("CLI невалидный JSON → exit 2", r4.returncode == 2)


def main() -> int:
    test_normalize_translit()
    test_resolve_countries()
    test_geocode_calibration()
    test_geocode_villages_to_tier2()
    test_geocode_en_hint()
    test_geocode_country_constraint()
    test_geocode_korea_full_route()
    test_geocode_empty_and_blank()
    test_cli()

    print(f"\n{'=' * 60}")
    print(f"Всего проверок: {checks_run}, провалов: {checks_failed}")
    return 0 if checks_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
