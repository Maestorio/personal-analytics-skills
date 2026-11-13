"""Profile mode helpers — anketa DOCX export/import.

Публичные точки входа:

    from skills.travel_planning.scripts.profile import anketa
    anketa.build_docx(out_path, prefill=None)         # CREATE / UPDATE export
    anketa.parse_docx(in_path) -> answers             # IMPORT
    anketa.parse_profile_md(profile_path) -> answers  # prefill из существующего
    anketa.assemble_profile_md(answers, …) -> str     # IMPORT financial step

Структура анкеты — `anketa_spec.ANKETA_SECTIONS` (single source of truth).
"""
# Лениво — модули доступны через явный импорт.

