#!/usr/bin/env python3
"""Сторож целостности ссылок скиллов (подготовка к дроблению SKILL.md, 2026-08-12).

Перед этапом 3 (тела SKILL.md > 500 строк дробятся на диспетчер + references/)
нужен детерминированный контроль трёх осей, которые ломаются при дроблении молча:

1. `shared_refs:` и `bundle_scripts:` из frontmatter резолвятся — локальный
   override в references/ или канон в _shared-references/ существует.
2. Каждый `references/<файл>`, упомянутый в файлах скилла, существует после
   упаковки: лежит локально ИЛИ будет инжектирован pack.sh из shared_refs.
   Мёртвая ссылка не падает — скилл просто «не находит» инструкцию в рантайме.
3. Внутри файлов скилла нет литерала `_shared-references/` — правило проекта:
   ссылаться через `references/...`, доставку делает pack.sh (в бандле
   _shared-references/ не существует).
4. (2026-10-12) Общий .py из _shared-references/ не лежит копией в
   skills/*/scripts/ — канон один, в бандл его кладёт bundle_scripts. Кейс:
   moex_quotes.py жил двумя копиями (loader и advisor), и они разошлись в обе
   стороны (у advisor не было listing_from — поля для его же IPO-гейта, у
   loader — lot_size для сайзинга advisor).
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "skills"
SHARED = ROOT / "_shared-references"

REF_RE = re.compile(r"references/([A-Za-z0-9_\-./]+\.(?:md|ya?ml|py|json|csv|txt))")

CHECKS = 0
ERRORS = []


def check(cond, msg):
    global CHECKS
    CHECKS += 1
    if not cond:
        ERRORS.append(msg)


def frontmatter_list(text, key):
    m = re.search(rf"^{key}:\s*\[([^\]]*)\]", text, re.M)
    if not m:
        return []
    return [x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()]


def main():
    skill_dirs = sorted(d for d in SKILLS.iterdir() if (d / "SKILL.md").exists())
    assert len(skill_dirs) >= 20, f"подозрительно мало скиллов: {len(skill_dirs)}"

    # Кросс-скилловые упоминания легальны: скилл A описывает артефакт скилла B
    # («advisor кладёт references/output-template.md») — в бандле A файла нет,
    # но это проза о чужом бандле. Ограничение осознанное: одноимённый файл в
    # другом скилле маскирует умершую ссылку — имена references/ де-факто уникальны
    # по смыслу, риск принят.
    all_ref_names = {p.name for d in skill_dirs
                     for p in (d / "references").rglob("*") if p.is_file()}

    for sd in skill_dirs:
        name = sd.name
        text = (sd / "SKILL.md").read_text(encoding="utf-8")
        refs_dir = sd / "references"

        # 1. Резолв shared_refs и bundle_scripts
        shared_refs = frontmatter_list(text, "shared_refs")
        for ref in shared_refs:
            local = refs_dir / f"{ref}.md"
            canon = SHARED / f"{ref}.md"
            check(local.exists() or canon.exists(),
                  f"{name}: shared_ref '{ref}' не найден ни в references/, ни в _shared-references/")
        for script in frontmatter_list(text, "bundle_scripts"):
            check((SHARED / script).exists(),
                  f"{name}: bundle_script '{script}' нет в _shared-references/")

        # После упаковки в references/ лежат: локальные файлы + инжектированные shared_refs
        packed = set()
        if refs_dir.exists():
            packed.update(p.relative_to(refs_dir).as_posix()
                          for p in refs_dir.rglob("*") if p.is_file())
        packed.update(f"{r}.md" for r in shared_refs if (SHARED / f"{r}.md").exists())

        # 2. Упомянутые references/<файл> существуют в бандле
        #    (сканируем SKILL.md, сами references/ И инжектируемые каноны shared_refs —
        #    после упаковки канон лежит в references/ этого скилла, его ссылки должны
        #    резолвиться в КАЖДОМ скилле-потребителе; кейс 2026-08-12:
        #    rebuild-plan-template.md нёс битый путь во все бандлы)
        sources = [(f"{name}/SKILL.md", text)]
        if refs_dir.exists():
            sources += [(f"{name}/references/{p.name}", p.read_text(encoding="utf-8"))
                        for p in refs_dir.rglob("*.md")]
        local_names = {p.name for p in refs_dir.rglob("*.md")} if refs_dir.exists() else set()
        for r in shared_refs:
            canon = SHARED / f"{r}.md"
            if canon.exists() and f"{r}.md" not in local_names:
                sources.append((f"{name}/(инжект) {r}.md", canon.read_text(encoding="utf-8")))
        for label, src in sources:
            for m in REF_RE.finditer(src):
                target = m.group(1)
                if "stageN" in target:      # шаблон-плейсхолдер travel-planning
                    continue
                check(target in packed or Path(target).name in all_ref_names,
                      f"{label}: ссылка references/{target} не существует после упаковки "
                      f"(нет ни локально, ни в shared_refs, ни в других скиллах)")

        # 3. Запрет литерала _shared-references/ внутри скилла
        for label, src in sources:
            check("_shared-references/" not in src,
                  f"{label}: литерал '_shared-references/' — в бандле такого пути нет, "
                  f"ссылайся через references/ и объяви в shared_refs")

    # 4. Нет локальных копий общих .py — иначе две версии расходятся молча
    for canon in sorted(SHARED.glob("*.py")):
        for sd in skill_dirs:
            check(not (sd / "scripts" / canon.name).exists(),
                  f"{sd.name}: scripts/{canon.name} — копия канона из _shared-references/; "
                  f"удали её и объяви bundle_scripts: [{canon.name}]")

    if ERRORS:
        print(f"FAIL: {len(ERRORS)} дефектов из {CHECKS} проверок")
        for e in ERRORS:
            print(f"  - {e}")
        sys.exit(1)
    print(f"OK: {CHECKS} проверок — ссылки {len(skill_dirs)} скиллов целостны")


if __name__ == "__main__":
    main()
