"""Движок экспорта артефактов travel-planning.

Общая инфраструктура для конвертации markdown-файлов стадий (0_scope.md,
3_poi_aggregation.md, 5_final_plan_v{N}.md, ...) в presentation-grade
PDF/DOCX-выход для разных получателей (self, parents, ...).

Stage-specific рендеринг живёт в `stages/` (один модуль на стадию).
Этот пакет знает только про:
  - generic md+YAML парсинг,
  - правила адаптации под получателя,
  - конвенции именования файлов,
  - контракт рендеринга, который stage-модули реализуют.

CLI entry point: `export.py`.
"""

__version__ = "0.1.0"
