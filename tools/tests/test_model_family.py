#!/usr/bin/env python3
"""Сторож «семейство без версии».

В рекомендациях «какую модель брать» пишется только семейство (Sonnet / Opus /
Haiku / Fable). Номер версии живёт в одном месте — разделе «Текущие версии
семейств» в `_shared-references/model-routing.md`. Номер, размазанный по скиллам
и справкам, устаревает в десятках файлов сразу и противоречит сам себе.

Сканируются CLAUDE.md, AGENTS.md, `_shared-references/*.md`, `tools/assets/help/**/*.md`,
`skills/*/{SKILL,EXAMPLES,README,STAGES}.md`, `skills/*/references/**/*.md`.
Любое совпадение `(Sonnet|Opus|Haiku|Fable)[ -]?\\d` вне белого списка — провал
с указанием файл:строка. Новое исключение — запись в WHITELIST с причиной.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SSOT = ROOT / "_shared-references" / "model-routing.md"
SSOT_HEADING = "## Текущие версии семейств"
PAT = re.compile(r"(Sonnet|Opus|Haiku|Fable)[ -]?\d")

# Зона целиком вне проверки.
SKIP_ZONES = {}

# (файл, подстрока строки) -> причина. Строка допускается, только если содержит подстроку.
WHITELIST = {
    ("skills/travel-planning/SKILL.md", "Opus 4.7 / Sonnet 4.6 /"):
        "единственная пометка: на каких версиях калибровались режимы",
    ("skills/travel-planning/SKILL.md", "Haiku 4.5; текущая версия"):
        "единственная пометка: на каких версиях калибровались режимы",
    ("skills/travel-planning/STAGES.md", "Opus 4.7 / Sonnet 4.6 /"):
        "единственная пометка: на каких версиях калибровались режимы",
    ("skills/travel-planning/SKILL.md", "Sonnet 4.6 safety filter"):
        "наблюдение о поведении платформы на конкретной версии",
    ("skills/travel-planning/SKILL.md", "запускает Haiku 4.5"):
        "наблюдение о поведении платформы (Continue -> Haiku 4.5)",
    ("skills/retrospective-forecast-audit/references/domain-tech-ceo.md", "Opus 4.7 release"):
        "факт индустрии (релиз модели), не рекомендация",
    ("skills/memory-sync/references/index-templates.md", "audit_model"):
        "поле audit_model хранит версию по замыслу (версионирование аудитов)",
    ("skills/retrospective-forecast-audit/references/model-routing.md", "токенизатор"):
        "факт о токенизаторе конкретной версии (+30% токенов)",
    ("skills/ru-portfolio-advisor/references/model-routing.md", "токенизатор"):
        "факт о токенизаторе конкретной версии (+30% токенов)",
    ("skills/ru-portfolio-advisor/references/trust-hierarchy.md", "токенизатор"):
        "факт о токенизаторе конкретной версии (+30% токенов)",
    ("_shared-references/model-routing.md", "токенизатор"):
        "факт о токенизаторе конкретной версии (+30% токенов)",
    ("skills/retrospective-forecast-audit/references/model-routing.md", "Дата последнего пересмотра"):
        "штамп пересмотра таблицы: на какие версии она смотрела",
    ("skills/ru-portfolio-advisor/references/model-routing.md", "Дата последнего пересмотра"):
        "штамп пересмотра таблицы: на какие версии она смотрела",
}

CHECKS = 0
FAILS = []


def check(cond, msg):
    global CHECKS
    CHECKS += 1
    if not cond:
        FAILS.append(msg)


def files():
    out = [p for p in (ROOT / "CLAUDE.md", ROOT / "AGENTS.md") if p.exists()]
    out += sorted((ROOT / "_shared-references").glob("*.md"))
    out += sorted((ROOT / "tools" / "assets" / "help").rglob("*.md"))
    for name in ("SKILL", "EXAMPLES", "README", "STAGES"):
        out += sorted((ROOT / "skills").glob(f"*/{name}.md"))
    out += sorted((ROOT / "skills").glob("*/references/**/*.md"))
    return sorted(set(out))


def ssot_range(lines):
    """Номера строк (с 1) раздела SSOT: от заголовка до следующего «## »."""
    start = next((i for i, ln in enumerate(lines) if ln.startswith(SSOT_HEADING)), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return range(start + 1, end + 1)


def main():
    ssot_lines = SSOT.read_text(encoding="utf-8").splitlines()
    rng = ssot_range(ssot_lines)
    check(rng is not None, f"нет раздела «{SSOT_HEADING[3:]}» в {SSOT.relative_to(ROOT)}")
    if rng is not None:
        body = "\n".join(ssot_lines[rng.start - 1:rng.stop - 1])
        for fam in ("Haiku", "Sonnet", "Opus", "Fable"):
            check(re.search(rf"^\|\s*{fam}\s*\|\s*\d", body, re.M),
                  f"в таблице версий нет семейства {fam} с номером")

    for f in files():
        rel = f.relative_to(ROOT).as_posix()
        if any(rel.startswith(z) for z in SKIP_ZONES):
            continue
        lines = f.read_text(encoding="utf-8").splitlines()
        own = rng if (rel == "_shared-references/model-routing.md" and rng) else ()
        for n, ln in enumerate(lines, 1):
            if not PAT.search(ln) or n in own:
                continue
            ok = any(rel == wf and sub in ln for (wf, sub) in WHITELIST)
            check(ok, f"{rel}:{n}: номер версии модели вне таблицы-SSOT: {ln.strip()[:100]}")

    for (wf, sub), why in WHITELIST.items():
        p = ROOT / wf
        check(p.exists() and sub in p.read_text(encoding="utf-8"),
              f"запись белого списка устарела ({wf}, «{sub}»: {why}) — удали её")

    if FAILS:
        print("\n".join("FAIL: " + m for m in FAILS))
        print(f"Итого: {CHECKS - len(FAILS)} из {CHECKS}")
        sys.exit(1)
    print(f"Итого: {CHECKS} из {CHECKS}")


if __name__ == "__main__":
    main()
