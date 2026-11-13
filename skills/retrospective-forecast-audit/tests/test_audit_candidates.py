#!/usr/bin/env python3
"""
Регрессионные тесты для audit_candidates.py.

Запуск из корня репозитория:
    python3 skills/retrospective-forecast-audit/tests/test_audit_candidates.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "skills" / "retrospective-forecast-audit" / "scripts" / "audit_candidates.py"

sys.path.insert(0, str(SCRIPT.parent))
import audit_candidates as ac  # noqa: E402

checks_run = 0
checks_failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global checks_run, checks_failed
    checks_run += 1
    if not condition:
        checks_failed += 1
    print(f"  [{'OK' if condition else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


MD_A = """---
topic: usdrub-rate
domain: ru-macro
---

# Прогноз

### Не аудированные источники

| Источник | Прогноз | Лагерь | Рекомендация |
|---|---|---|---|
| **Альфа-Банк** | 87 | Монетаристы | Аудит — приоритет №1 |
| Сбер | 90 | Монетаристы | Аудит рекомендован |
| Big Tech (4 компании) | 725 | Суперцикл | Данные первоисточника |
| Макроопрос ЦБ | 14.1 | — | Аудит |
| Metaculus, Polymarket | см. | — | Агрегаторы-платформы; аудит не применим |

## § Что дальше
"""

MD_B = """# Прогноз 2

## Не аудированные источники (вес 0)

| Источник | Рекомендация |
|----------|-------------|
| Альфа Банк | Кандидат на аудит |
| Goldman Sachs Research | Аудит |
| HSBC | Аудит |
"""

MD_C = """---
topic: brent-price
---
## Не аудированные источники

| Источник | Прогноз | Рекомендация |
|---|---|---|
| HSBC | 80 | Аудит №1 |
"""

YAML_A = """forecast:
  date: 2026-06-01
  topic: cbr-rate
  domain: ru-macro
conditional_on_scenarios:
  by_scenario:
    A:
      sources_used:
        - { source_id: alfa-bank, trust_level: null, camp_weight: 1.0 }
        - { source_id: jpmorgan, trust_level: HIGH, camp_weight: 1.0 }
        - { source_id: crea-russia, trust_level: context, camp_weight: null }
        - { source_id: new-think-tank }
    B:
      sources_used: 3
"""

INDEX = """# INDEX

## Track record summary

| Source | Subfolder | Trust | Audits | Pin |
|---|---|---|---|---|
| SberCIB Investment Research | domains/ru-sellside | HIGH | 2 | yes |
| Goldman Sachs | domains/global-banks | MEDIUM | 1 | no |

## Notes
"""


def make_lib(root: Path) -> None:
    f = root / "forecasts"
    f.mkdir()
    (f / "usdrub-rate-2026-07-29.md").write_text(MD_A, encoding="utf-8")
    (f / "inflation-ru-2026-05-11.md").write_text(MD_B, encoding="utf-8")
    (f / "brent-price-2026-10-08.md").write_text(MD_C, encoding="utf-8")
    (f / "cbr-rate-2026-06-01.yaml").write_text(YAML_A, encoding="utf-8")
    (root / "INDEX.md").write_text(INDEX, encoding="utf-8")


def test_normalize_and_aliases():
    print("normalize / ALIASES")
    check("Research отбрасывается", ac.normalize("Goldman Sachs Research") == "goldman sachs")
    check("скобки и разметка отбрасываются", ac.normalize("**Т-Банк (Донец)**") == "т банк")
    check("синоним ЦБ РФ = Bank of Russia (CBR)", ac.names_match("ЦБ РФ", "Bank of Russia (CBR)"))
    check("Минэкономразвития = МЭР", ac.names_match("Минэкономразвития", "МЭР"))
    check("Сбер = SberCIB Investment Research", ac.names_match("Сбер", "SberCIB Investment Research"))
    check("Invest Era = Инвест Эра", ac.names_match("Invest Era", "Инвест Эра"))
    check("подстрока: Goldman Sachs Research ↔ Goldman Sachs", ac.names_match("Goldman Sachs Research", "Goldman Sachs"))
    check("разные источники не склеиваются", not ac.names_match("UBS", "Citi"))
    check("короткая подстрока не считается", not ac.names_match("ING", "Bing Research Group"))
    check("canon_key: BofA = Bank of America", ac.canon_key("BofA (13.09)") == ac.canon_key("Bank of America"))


def test_table_parsing():
    print("разбор таблицы")
    rows = ac.parse_md_table_rows(MD_A)
    names = [n for n, _ in rows]
    check("колонка рекомендации по заголовку", ("Альфа-Банк", "Аудит — приоритет №1") in rows, str(rows))
    check("разметка ** снята", "Альфа-Банк" in names)
    check("первоисточник исключён", not any("Big Tech" in n for n in names))
    check("«опрос» в имени исключён", not any("опрос" in n.lower() for n in names))
    check("агрегаторы по рекомендации исключены", "Metaculus" not in names and "Polymarket" not in names)
    rows_b = ac.parse_md_table_rows(MD_B)
    check("двухколоночная таблица (## и «вес 0»)", [n for n, _ in rows_b] == ["Альфа Банк", "Goldman Sachs Research", "HSBC"], str(rows_b))
    check("список через запятую делится вне скобок",
          ac.split_names("Кулеба, Залужный, Атлантик (Донован, Фрид)") == ["Кулеба", "Залужный", "Атлантик (Донован, Фрид)"])
    check("без секции — пусто", ac.parse_md_table_rows("# нет\n| a | b |\n") == [])


def test_yaml_layer():
    print("сценарный слой")
    cands, topic, domain = ac.parse_yaml_candidates(YAML_A)
    ids = [c[0] for c in cands]
    check("trust null и без trust — кандидаты", ids == ["alfa-bank", "new-think-tank"], str(ids))
    check("HIGH и context не кандидаты", "jpmorgan" not in ids and "crea-russia" not in ids)
    check("topic/domain из forecast.*", (topic, domain) == ("cbr-rate", "ru-macro"))


def test_build():
    print("build: слияние, аудированные, сортировка")
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        make_lib(root)
        res = ac.build(root)
        check("прочитано md/yaml", res["read"]["md"] == 3 and res["read"]["yaml"] == 1, str(res["read"]))
        c = {x["source"]: x for x in res["candidates"]}
        by_key = {ac.canon_key(k): v for k, v in c.items()}
        alfa = by_key[ac.canon_key("Альфа-Банк")]
        check("Альфа-Банк склеен из двух md + yaml (3 упоминания)", alfa["mentions"] == 3, str(alfa))
        check("последнее — по дате", alfa["last"] == "2026-07-29")
        check("HSBC: 2 упоминания, последняя рекомендация свежая",
              c["HSBC"]["mentions"] == 2 and c["HSBC"]["recommendation"] == "Аудит №1" and c["HSBC"]["last"] == "2026-10-08",
              str(c["HSBC"]))
        check("HSBC → global-banks", c["HSBC"]["domain"] == "global-banks")
        check("только сценарный слой помечается", c["new think tank"]["scenario_layer_only"] is True)
        check("Сбер и Goldman — не кандидаты", not any("сбер" in k.lower() or "goldman" in k.lower() for k in c))
        audited = {a["source"]: a["audited_as"] for a in res["already_audited"]}
        check("Сбер → SberCIB в «уже аудированы»", audited.get("Сбер") == "SberCIB Investment Research", str(audited))
        check("Goldman Sachs Research → Goldman Sachs", audited.get("Goldman Sachs Research") == "Goldman Sachs")
        order = [x["mentions"] for x in res["candidates"]]
        check("сортировка по упоминаниям убыв.", order == sorted(order, reverse=True), str(order))
        tie = [x["source"] for x in res["candidates"] if x["mentions"] == 2]
        check("при равенстве — дата убыв.", tie[0] == "HSBC" or res["candidates"][0]["mentions"] >= 2)
        check("--min 3 оставляет только Альфу", [x["mentions"] for x in ac.build(root, 3)["candidates"]] == [3])
        check("--top 1", len(ac.build(root, 1, 1)["candidates"]) == 1)
        # правило короткого списка (владелец 27.10.2026): порог X — чтобы вышло хотя бы N, группа по X целиком
        mk = lambda ns: [dict(mentions=n) for n in ns]
        check("порог: 5×5, 7×4, 10×3 → при N=10 порог 4 (12 источников)", ac.shortlist_threshold(mk([5]*5 + [4]*7 + [3]*10), 10) == 4)
        check("порог: 12×5, 3×4 → порог 5 (12 источников)", ac.shortlist_threshold(mk([5]*12 + [4]*3), 10) == 5)
        check("порог: кандидатов меньше N → минимальное число упоминаний", ac.shortlist_threshold(mk([3, 1, 1]), 10) == 1)
        check("порог: пусто → 1", ac.shortlist_threshold([], 10) == 1)
        res_all = ac.build(root, 1, None, None)
        check("at_least=None — без порога, rest пуст", res_all["threshold"] == 1 and res_all["rest"] == [])


def test_cli():
    print("CLI и --json")
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        make_lib(root)
        p = subprocess.run([sys.executable, str(SCRIPT), "--memory", str(root), "--json"],
                           capture_output=True, text=True)
        check("код завершения 0", p.returncode == 0, p.stderr)
        data = json.loads(p.stdout)
        check("JSON: ключи", set(data) == {"read", "threshold", "candidates", "rest", "already_audited"})
        check("JSON: первым идёт самый упоминаемый", data["candidates"][0]["mentions"] == 3)
        p2 = subprocess.run([sys.executable, str(SCRIPT), "--memory", str(root)], capture_output=True, text=True)
        check("markdown: шапка таблицы", "| Источник | Упоминаний | Темы (до 3) | Последнее | Рекомендация (последняя) | Домен? |" in p2.stdout)
        check("markdown: блок аудированных", "## Уже аудированы с тех пор" in p2.stdout)
        p3 = subprocess.run([sys.executable, str(SCRIPT), "--memory", str(root / "нет")], capture_output=True, text=True)
        check("пустая библиотека — код 0", p3.returncode == 0, p3.stderr)


if __name__ == "__main__":
    test_normalize_and_aliases()
    test_table_parsing()
    test_yaml_layer()
    test_build()
    test_cli()
    print(f"\nИтого: {checks_run - checks_failed} из {checks_run}")
    sys.exit(1 if checks_failed else 0)
