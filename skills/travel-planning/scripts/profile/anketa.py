#!/usr/bin/env python3
"""CLI для анкеты профиля — export DOCX / import DOCX.

Команды:

    # Export пустой анкеты (CREATE)
    python3 anketa.py export --output /path/to/анкета.docx

    # Export с предзаполнением из существующего профиля (UPDATE)
    python3 anketa.py export --profile /path/to/profiles/алексей.md \\
                              --output /path/to/анкета_алексей_правка.docx

    # Import — DOCX → profile.md в stdout
    python3 anketa.py import --input /path/to/filled.docx \\
                              --profile-id алексей > алексей.md

    # Debug: распарсить заполненный DOCX и вывести answers как JSON
    python3 anketa.py parse-docx --input /path/to/filled.docx

    # Debug: распарсить profile.md и вывести answers как JSON
    python3 anketa.py parse-profile --input /path/to/profile.md

Запускается через
    /usr/bin/python3 skills/travel-planning/scripts/profile/anketa.py …
или как модуль:
    /usr/bin/python3 -m profile.anketa …
из директории skills/travel-planning/scripts/.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path


# Поддержка запуска как скрипта и как модуля.
if __package__ in (None, ""):  # запуск `python3 anketa.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from profile.anketa_builder import build_docx  # type: ignore[no-redef]
    from profile.anketa_docx_parser import parse_docx  # type: ignore[no-redef]
    from profile.profile_md_parser import parse_profile_md  # type: ignore[no-redef]
    from profile.profile_assembler import assemble_profile_md  # type: ignore[no-redef]
    from profile.profile_merger import merge_answers, merged_profile_id  # type: ignore[no-redef]
else:
    from .anketa_builder import build_docx
    from .anketa_docx_parser import parse_docx
    from .profile_md_parser import parse_profile_md
    from .profile_assembler import assemble_profile_md
    from .profile_merger import merge_answers, merged_profile_id


def cmd_export(args: argparse.Namespace) -> int:
    out = Path(args.output).expanduser()
    answers: dict = {}
    profile_id = None
    profile_updated = None
    if args.profile:
        profile_path = Path(args.profile).expanduser()
        if not profile_path.exists():
            print(f"профиль не найден: {profile_path}", file=sys.stderr)
            return 2
        parsed = parse_profile_md(profile_path)
        answers = parsed.answers
        profile_id = parsed.frontmatter.get("profile_id") or profile_path.stem
        profile_updated = parsed.frontmatter.get("updated")
    saved = build_docx(
        out_path=out,
        answers=answers,
        profile_id=profile_id,
        profile_updated=profile_updated,
    )
    print(f"saved: {saved}", file=sys.stderr)
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    in_path = Path(args.input).expanduser()
    if not in_path.exists():
        print(f"файл не найден: {in_path}", file=sys.stderr)
        return 2
    parsed = parse_docx(in_path)
    # created/updated из существующего профиля (если есть) — иначе сегодня
    created = updated = None
    if args.merge_with:
        merge_path = Path(args.merge_with).expanduser()
        if merge_path.exists():
            old = parse_profile_md(merge_path)
            created = old.frontmatter.get("created")
            # updated — обновляем на сегодня (это и есть UPDATE)
    md, warnings = assemble_profile_md(
        answers=parsed.answers,
        profile_id=args.profile_id,
        created=created,
        updated=updated,
    )
    for w in parsed.warnings + warnings:
        print(f"warning: {w}", file=sys.stderr)
    sys.stdout.write(md)
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    """MERGE из 2+ DOCX/MD: парсит каждый источник, объединяет по §4.1,
    выдаёт merged profile.md + список вопросов для уточнения в stderr."""
    sources = []
    pids = []
    for src in args.inputs:
        p = Path(src).expanduser()
        if not p.exists():
            print(f"источник не найден: {p}", file=sys.stderr)
            return 2
        if p.suffix.lower() == ".docx":
            parsed = parse_docx(p)
            ans = parsed.answers
            warnings = parsed.warnings
        elif p.suffix.lower() == ".md":
            parsed = parse_profile_md(p)
            ans = parsed.answers
            warnings = []
        else:
            print(f"неподдерживаемый формат: {p.suffix}", file=sys.stderr)
            return 2
        for w in warnings:
            print(f"warning ({p.name}): {w}", file=sys.stderr)
        pid = _infer_profile_id(p, parsed)
        sources.append(ans)
        pids.append(pid)

    merged, ask_items = merge_answers(sources, pids)
    pid_final = args.profile_id or merged_profile_id(pids)

    md, warnings = assemble_profile_md(
        answers=merged,
        profile_id=pid_final,
    )
    print(
        f"\n=== MERGE: {' + '.join(pids)} → {pid_final} ===",
        file=sys.stderr,
    )
    if ask_items:
        print(f"\nВопросы для уточнения ({len(ask_items)} полей):",
              file=sys.stderr)
        for item in ask_items:
            print(f"\n  [{item.section_title}] {item.qid}", file=sys.stderr)
            print(f"    {item.question_text}", file=sys.stderr)
            print(f"    причина: {item.reason}", file=sys.stderr)
            for src_pid, val in item.sources:
                print(f"      {src_pid}: {val}", file=sys.stderr)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)

    sys.stdout.write(md)
    return 0


def _infer_profile_id(path: Path, parsed) -> str:
    """profile_id — из YAML frontmatter (для .md) или из имени файла."""
    if hasattr(parsed, "frontmatter") and parsed.frontmatter.get("profile_id"):
        return parsed.frontmatter["profile_id"]
    # Из имени файла: «анкета_алексей_правка_….docx» → «алексей»
    stem = path.stem
    m = re.match(r"^анкета_([^_]+)_", stem)
    if m:
        return m.group(1)
    return stem


def cmd_parse_docx(args: argparse.Namespace) -> int:
    parsed = parse_docx(Path(args.input).expanduser())
    out = {"answers": parsed.answers, "warnings": parsed.warnings}
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


def cmd_parse_profile(args: argparse.Namespace) -> int:
    parsed = parse_profile_md(Path(args.input).expanduser())
    out = {
        "frontmatter": parsed.frontmatter,
        "answers": parsed.answers,
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="anketa.py",
        description="Анкета профиля путешественника — DOCX export/import.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    ex = sub.add_parser("export", help="сгенерировать DOCX анкеты")
    ex.add_argument("--output", required=True, help="путь к выходному DOCX")
    ex.add_argument("--profile", help="опц.: путь к существующему profile.md для prefill")
    ex.set_defaults(func=cmd_export)

    im = sub.add_parser("import", help="DOCX → profile.md в stdout")
    im.add_argument("--input", required=True, help="путь к заполненному DOCX")
    im.add_argument("--profile-id", required=True, help="profile_id для frontmatter")
    im.add_argument("--merge-with",
                    help="опц.: путь к существующему profile.md (берёт оттуда `created:`)")
    im.set_defaults(func=cmd_import)

    mg = sub.add_parser(
        "merge",
        help="MERGE: 2+ DOCX/MD профилей → merged profile.md (ASK-конфликты в stderr)",
    )
    mg.add_argument("inputs", nargs="+",
                    help="пути к DOCX-анкетам или profile.md")
    mg.add_argument("--profile-id",
                    help="опц.: явный profile_id для merged "
                         "(дефолт — вычисляется по §4 правилу владелец+алфавит)")
    mg.set_defaults(func=cmd_merge)

    pd = sub.add_parser("parse-docx", help="debug: распарсить DOCX → JSON")
    pd.add_argument("--input", required=True)
    pd.set_defaults(func=cmd_parse_docx)

    pp = sub.add_parser("parse-profile", help="debug: распарсить profile.md → JSON")
    pp.add_argument("--input", required=True)
    pp.set_defaults(func=cmd_parse_profile)

    return p


def main(argv: list | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
