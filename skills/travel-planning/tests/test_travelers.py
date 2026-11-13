#!/usr/bin/env python3
"""Регрессионные тесты для travelers.resolve_travelers (единый резолвер «Кто едет»).

Покрывает цепочку источников (первый непустой побеждает):
  1. профиль: yaml.travelers_profile → файл {travel_root}/profiles/{stem}.md,
     frontmatter `display_name`;
  2. `trip.yaml` рядом со стадийным артефактом: `travelers: [...]`;
  3. polish-маркер `[[поездка: группа: … | кто: …]]`;
  4. legacy fallback: имя файла профиля (cover_common.profile_name).

Запуск из корня репозитория:
    python3 skills/travel-planning/tests/test_travelers.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
EXPORT_DIR = REPO_ROOT / "skills" / "travel-planning" / "scripts" / "export"

sys.path.insert(0, str(EXPORT_DIR.parent))
from export import travelers  # noqa: E402

checks_run = 0
checks_failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global checks_run, checks_failed
    checks_run += 1
    if condition:
        print(f"  ✓ {name}")
    else:
        checks_failed += 1
        print(f"  ✗ {name}" + (f"  — {detail}" if detail else ""))


def _make_trip_tree(tmp: Path, *, profile_display_name: str | None = None,
                    trip_yaml_travelers: list | None = None,
                    profile_id: str = "алексей_родители") -> Path:
    """{tmp}/profiles/{profile_id}.md + {tmp}/trips/регион_a_2027/1_dr_reports.md
    (+ опц. trip.yaml). Возвращает путь к стадийному артефакту (input_path)."""
    profiles = tmp / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    profile_text = "---\nprofile_id: {}\n".format(profile_id)
    if profile_display_name is not None:
        profile_text += f"display_name: {profile_display_name}\n"
    profile_text += "---\n\n# Профиль\n"
    (profiles / f"{profile_id}.md").write_text(profile_text, encoding="utf-8")

    trip_dir = tmp / "trips" / "регион_a_2027"
    trip_dir.mkdir(parents=True, exist_ok=True)
    if trip_yaml_travelers is not None:
        names = ", ".join(trip_yaml_travelers)
        (trip_dir / "trip.yaml").write_text(
            f"schema: trip-meta@1\ntravelers: [{names}]\n", encoding="utf-8")

    stage_path = trip_dir / "1_dr_reports.md"
    stage_path.write_text("---\ntrip_id: регион_a_2027\n---\n\n# Тест\n", encoding="utf-8")
    return stage_path


def test_profile_display_name_wins():
    print("\n[1] профиль с display_name — первый источник, побеждает над всем")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        stage_path = _make_trip_tree(
            tmp, profile_display_name="Родители",
            trip_yaml_travelers=["мария", "алексей"],
        )
        yaml = {"travelers_profile": "profiles/алексей_родители.md"}
        marker = {"группа": "Текст из маркера"}
        who = travelers.resolve_travelers(yaml, marker, stage_path)
        check("display_name «Родители» побеждает над trip.yaml и маркером",
              who == "Родители", who)


def test_trip_yaml_fallback_without_profile():
    print("\n[2] без профиля (или без display_name) — trip.yaml travelers:")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        stage_path = _make_trip_tree(
            tmp, profile_display_name=None, trip_yaml_travelers=["родители"],
        )
        # yaml без travelers_profile вовсе — шаг 1 должен молча пропуститься.
        who = travelers.resolve_travelers({}, {}, stage_path)
        check("trip.yaml travelers: [родители] → «Родители»", who == "Родители", who)

        # Профиль указан, но без display_name — тоже пропуск шага 1.
        stage_path2 = _make_trip_tree(
            tmp, profile_display_name=None, trip_yaml_travelers=["мария", "алексей"],
            profile_id="алексей_мария",
        )
        yaml = {"travelers_profile": "profiles/алексей_мария.md"}
        who2 = travelers.resolve_travelers(yaml, {}, stage_path2)
        check("профиль без display_name → откат на trip.yaml (Мария и Алексей)",
              who2 == "Мария и Алексей", who2)


def test_marker_fallback_without_profile_or_trip_yaml():
    print("\n[3] без профиля/trip.yaml — текст polish-маркера")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        stage_path = _make_trip_tree(tmp, profile_display_name=None,
                                     trip_yaml_travelers=None)
        who = travelers.resolve_travelers({}, {"группа": "Алексей и Мария"}, stage_path)
        check("маркер «группа» как fallback", who == "Алексей и Мария", who)
        # Ключ «кто» (Stage 2 использовал именно его исторически).
        who2 = travelers.resolve_travelers({}, {"кто": "Петя"}, stage_path)
        check("маркер «кто» тоже принимается (Stage 2 legacy-ключ)",
              who2 == "Петя", who2)


def test_legacy_stem_fallback():
    print("\n[4] без всего (нет профиля/trip.yaml/маркера) — прежний fallback "
          "на имя файла профиля")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        stage_path = _make_trip_tree(tmp, profile_display_name=None,
                                     trip_yaml_travelers=None)
        yaml = {"travelers_profile": "profiles/алексей_родители.md"}
        who = travelers.resolve_travelers(yaml, {}, stage_path)
        check("имя файла профиля → «Алексей и Родители» (стем-разбор)",
              who == "Алексей и Родители", who)

        # Совсем без данных — пустая строка (никто не отвечает "—" на этом уровне;
        # "—" рисуют консьюмеры типа Stage 2 _who_goes при пустом резолве).
        who_empty = travelers.resolve_travelers({}, {}, stage_path)
        check("совсем без данных → пустая строка", who_empty == "", repr(who_empty))


def test_graceful_missing_files_and_no_input_path():
    print("\n[5] graceful: нет файла профиля / нет input_path — не падает")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        stage_path = _make_trip_tree(tmp, profile_display_name=None,
                                     trip_yaml_travelers=None)
        # travelers_profile указывает на несуществующий файл.
        yaml = {"travelers_profile": "profiles/нет_такого.md"}
        who = travelers.resolve_travelers(yaml, {"группа": "Запасной вариант"}, stage_path)
        check("несуществующий профиль → не падает, откат на маркер",
              who == "Запасной вариант", who)

        # input_path=None — шаги 1–2 пропускаются молча.
        who2 = travelers.resolve_travelers(
            {"travelers_profile": "profiles/алексей_родители.md"},
            {"группа": "Маркер без input_path"}, None,
        )
        check("input_path=None → шаги 1–2 пропущены, работает маркер",
              who2 == "Маркер без input_path", who2)

        # None/пустые аргументы целиком.
        who3 = travelers.resolve_travelers(None, None, None)
        check("yaml=None, trip_marker=None, input_path=None → пустая строка, без исключений",
              who3 == "", repr(who3))


def test_consistency_across_stages_china_like():
    """(г) на «живом Китае»-подобном дереве все стадии (через один и тот же
    input_path-паттерн `{root}/trips/{trip}/{N}_stage.md`) дают одно и то же имя."""
    print("\n[6] консистентность между «стадиями» на одном дереве (Китай-like)")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        trip_dir = tmp / "trips" / "регион_a_2027"
        trip_dir.mkdir(parents=True)
        profiles = tmp / "profiles"
        profiles.mkdir(parents=True)
        (profiles / "алексей_родители.md").write_text(
            "---\nprofile_id: алексей_родители\ndisplay_name: Родители\n---\n",
            encoding="utf-8",
        )
        yaml = {"travelers_profile": "profiles/алексей_родители.md"}
        names = {
            stage: travelers.resolve_travelers(yaml, {}, trip_dir / f"{stage}_stage.md")
            for stage in ("0_scope", "1_dr_reports", "2_similarity",
                         "3_poi_pool", "4_variants", "5_final_plan", "6_final")
        }
        check("все 7 стадий резолвят одно и то же имя «Родители»",
              len(set(names.values())) == 1 and next(iter(names.values())) == "Родители",
              str(names))


def test_polished_scratch_plus_output_dir():
    """Живой кейс Китай (батч 2, повторный прогон): экспорт идёт на эфемерном
    polished-md ВНЕ trips/ (Р9), вывод — в каноническую trips/{trip_id}/.
    Резолвер должен найти профиль/trip.yaml через ВТОРОЙ путь-кандидат
    (output), а не падать на polish-маркер («Алексей и родители»)."""
    print("\n[7] polished-md вне trips/ + output в trips/ → display_name побеждает")
    with tempfile.TemporaryDirectory() as t, tempfile.TemporaryDirectory() as t2:
        tmp = Path(t)
        stage_path = _make_trip_tree(tmp, profile_display_name="Родители")
        # Polished-копия в «скретче» контейнера — СОВСЕМ другое дерево
        # (отдельный tempdir: walk-up из него не должен дотянуться до profiles/).
        scratch = Path(t2) / "scratch" / "session"
        scratch.mkdir(parents=True)
        polished = scratch / "polished_2_similarity.md"
        polished.write_text("---\ntrip_id: регион_a_2027\n---\n", encoding="utf-8")
        output = stage_path.parent / "2_регион_a_2027_похожие_авторы.html"

        yaml = {"travelers_profile": "profiles/алексей_родители.md"}
        marker = {"кто": "Алексей и родители"}  # polish-маркер — врёт
        who = travelers.resolve_travelers(yaml, marker, [polished, output])
        check("display_name найден через output-путь (не маркер)",
              who == "Родители", who)

        # Только polished (без output-кандидата) — раньше падало на маркер.
        who2 = travelers.resolve_travelers(yaml, marker, polished)
        check("только scratch-путь → откат на маркер (нечем резолвить)",
              who2 == "Алексей и родители", who2)

        # None в списке кандидатов не ломает.
        who3 = travelers.resolve_travelers(yaml, marker, [None, output])
        check("None в списке путей игнорируется", who3 == "Родители", who3)


def test_walk_up_profile_search():
    """profiles/ ищется walk-up'ом (до 4 уровней), не фикс-глубиной — работает
    и при нестандартной вложенности (артефакт глубже канона)."""
    print("\n[8] walk-up поиск profiles/ (нестандартная вложенность)")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        (tmp / "profiles").mkdir(parents=True)
        (tmp / "profiles" / "алексей.md").write_text(
            "---\nprofile_id: алексей\ndisplay_name: Алексей\n---\n",
            encoding="utf-8")
        deep = tmp / "trips" / "поездка" / "подпапка"
        deep.mkdir(parents=True)
        artefact = deep / "5_final_plan.md"
        artefact.write_text("---\n---\n", encoding="utf-8")
        who = travelers.resolve_travelers(
            {"travelers_profile": "profiles/алексей.md"}, {}, artefact)
        check("профиль найден на 3 уровня выше", who == "Алексей", who)


def test_replace_profile_stem():
    """Сырой стем профиля в прозе → резолвнутое имя (Stage 2/3 контекст)."""
    print("\n[9] replace_profile_stem")
    yaml = {"travelers_profile": "profiles/алексей_родители.md"}
    line = "- **Кто/когда:** пара 60–61 (`алексей_родители`), Китай, апрель 2027"
    out = travelers.replace_profile_stem(line, yaml, "Родители")
    check("`стем` в бэктиках → имя",
          out == "- **Кто/когда:** пара 60–61 (Родители), Китай, апрель 2027", out)
    check("голый стем тоже заменяется",
          travelers.replace_profile_stem("группа алексей_родители едет", yaml, "Родители")
          == "группа Родители едет")
    check("без who — не тронуто",
          travelers.replace_profile_stem(line, yaml, "") == line)
    check("без travelers_profile — не тронуто",
          travelers.replace_profile_stem(line, {}, "Родители") == line)
    check("None-текст → пустая строка", travelers.replace_profile_stem(None, yaml, "X") == "")


def main() -> int:
    print("=" * 70)
    print("Регрессионные тесты: travelers.resolve_travelers (Кто едет — SSOT)")
    print("=" * 70)

    test_profile_display_name_wins()
    test_trip_yaml_fallback_without_profile()
    test_marker_fallback_without_profile_or_trip_yaml()
    test_legacy_stem_fallback()
    test_graceful_missing_files_and_no_input_path()
    test_consistency_across_stages_china_like()
    test_polished_scratch_plus_output_dir()
    test_walk_up_profile_search()
    test_replace_profile_stem()

    print(f"\n{'=' * 70}")
    if checks_failed:
        print(f"ПРОВАЛ: {checks_failed}/{checks_run} проверок не прошли")
        return 1
    print(f"OK — все {checks_run} проверок прошли")
    return 0


if __name__ == "__main__":
    sys.exit(main())
