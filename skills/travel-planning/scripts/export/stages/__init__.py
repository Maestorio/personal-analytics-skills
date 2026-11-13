"""Stage-специфичные экстракторы и renderer'ы.

Каждый stage-модуль (stage0, stage1, stage3, stage4, stage5) знает свою
разметку (день-блоки, region cards, POI-таблицы, transport tables) и
строит PDF/DOCX через pdf_lib (см. родительский пакет).

Регистрация renderer'ов в renderer._RENDERERS происходит на import-time
каждого модуля. Чтобы зарегистрировать все доступные renderer'ы,
импорт всего пакета stages подтягивает все модули.
"""
from __future__ import annotations

# Подтягиваем stage-модули, чтобы их register_renderer() выполнился.
from . import stage0  # noqa: F401
from . import stage1  # noqa: F401
from . import stage2  # noqa: F401
from . import stage3  # noqa: F401
from . import stage4  # noqa: F401
from . import stage5  # noqa: F401
from . import stage6  # noqa: F401
