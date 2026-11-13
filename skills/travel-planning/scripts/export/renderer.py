"""renderer.py — контракт рендеринга PDF/DOCX.

Реальная генерация PDF/DOCX делегируется core-скиллам anthropic (pdf,
docx). Они вызываются на уровне модели через Skill-тул, не из Python.
Этот модуль фиксирует:

  - `RenderRequest` — структура, которую stage-модуль готовит и отдаёт
    обратно в чат для исполнения core-скиллом;
  - `prepare_pdf_request` / `prepare_docx_request` — фабрики `RenderRequest`;
  - `write_request_to_disk` — сохранить request как JSON-файл (полезно
    для debugging и как «передаточный конверт» к stage-модулям).

Зачем такой косвенный путь:
  - Engine остаётся stdlib-only (см. CLAUDE.md «travel-planning особенности»).
  - Core pdf/docx skills делают heavy lifting и автоматически обновляются.
  - Stage-модули (Steps 2+) не пишут код рендера руками — только готовят
    structured payload.

Stage-модули могут зарегистрировать кастомный рендерер через
`register_renderer(stage_id, format, fn)` если core-скилла недостаточно
(например, нужны Word AcroForm fields — реализация в Step 3).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Literal


Format = Literal["pdf", "docx", "html"]


# ---------------------------------------------------------------------------
# RenderRequest — что готовит stage-модуль
# ---------------------------------------------------------------------------


@dataclass
class RenderRequest:
    """Описание задания на рендер для core pdf/docx скилла.

    Поля:
      - `format`           — `"pdf"` или `"docx"`.
      - `output_path`      — куда положить результат (абсолютный путь).
      - `template_path`    — путь к шаблону (если используется); может
                              быть None, если рендерер работает по
                              programmatic-структуре без шаблона.
      - `content`          — payload для шаблона: dict с произвольными
                              ключами, специфичными для конкретного stage.
      - `style`            — снимок style.py-констант (для воспроизводимости
                              между сессиями).
      - `metadata`         — служебные метаданные: trip_id, stage,
                              recipient, date генерации.
      - `notes`            — заметки для оператора (например, «требует
                              AcroForm fields — использовать python-docx
                              напрямую, не core docx skill»).
    """
    format: Format
    output_path: str
    content: dict[str, Any] = field(default_factory=dict)
    template_path: str | None = None
    style: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Фабрики requests
# ---------------------------------------------------------------------------


def prepare_pdf_request(
    *,
    content: dict[str, Any],
    output_path: str | Path,
    template_path: str | Path | None = None,
    style: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    notes: list[str] | None = None,
) -> RenderRequest:
    """Собрать `RenderRequest` для PDF-рендера через core pdf skill."""
    return RenderRequest(
        format="pdf",
        output_path=str(output_path),
        content=content,
        template_path=str(template_path) if template_path else None,
        style=style or {},
        metadata=metadata or {},
        notes=notes or [],
    )


def prepare_docx_request(
    *,
    content: dict[str, Any],
    output_path: str | Path,
    template_path: str | Path | None = None,
    style: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    notes: list[str] | None = None,
) -> RenderRequest:
    """Собрать `RenderRequest` для DOCX-рендера через core docx skill."""
    return RenderRequest(
        format="docx",
        output_path=str(output_path),
        content=content,
        template_path=str(template_path) if template_path else None,
        style=style or {},
        metadata=metadata or {},
        notes=notes or [],
    )


def write_request_to_disk(request: RenderRequest, path: str | Path) -> None:
    """Сериализовать request как JSON.

    Используется для:
      - debugging stage-модулей (что именно ушло в core skill);
      - hand-off между CLI и chat-сессией (CLI пишет JSON, модель
        читает и вызывает core skill).
    """
    Path(path).write_text(
        json.dumps(request.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Кастомные рендерeры (extension point для stage-модулей)
# ---------------------------------------------------------------------------


# Реестр (stage_id, format) -> функция, готовящая RenderRequest.
# Stage-модули регистрируют свои renderers здесь на import-time.
_RENDERERS: dict[tuple[str, Format], Callable[..., RenderRequest]] = {}


def register_renderer(
    stage_id: str,
    fmt: Format,
    fn: Callable[..., RenderRequest],
) -> None:
    """Зарегистрировать stage-специфичный renderer.

    `fn(parsed, recipient, output_path, **kwargs) -> RenderRequest`.
    """
    _RENDERERS[(stage_id, fmt)] = fn


def get_renderer(stage_id: str, fmt: Format) -> Callable[..., RenderRequest] | None:
    """Найти зарегистрированный renderer для (stage, format).

    Возвращает None, если ещё не реализован (это норма для Step 1 —
    реальные renderers подключаются в Steps 2+).
    """
    return _RENDERERS.get((stage_id, fmt))
