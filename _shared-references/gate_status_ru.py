#!/usr/bin/env python3
"""
gate_status_ru.py — статусы гейтов (Portfolio/gate-reviews.yaml) словами для человека.

Зачем. 23.10.2026 разбор бумаги закончился вопросом «применить гейты? YDEX reviewed_under_review,
MDMG reviewed_reduce», а обзор 26.10 написал «гейт YDEX остаётся review_needed». Владелец не понял
ни вопроса, ни строки: коды статусов в тексте для человека не читаются, и решение не было принято.

Подписи и смысл статусов — из кодлиста `gate_status` (`codelists.json` рядом; поля `ru` и `effect`):
скиллы говорят теми же словами, что и страница (вьюер читает тот же JSON через `tools/assets/codelists.js`).
Модуль — тонкая обёртка с прежними публичными именами. Совпадение с таблицей для модели
`gate-status-labels.md` держит тест `tools/tests/test_gate_status_ru.py`.

Коды остаются в машинных полях (gate-reviews.yaml, директивы, `set_by`, `gate_status_snapshot`).

Зависимости: stdlib (+ codelists.py/codelists.json из той же папки).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codelists  # noqa: E402

# код → (подпись как во вьюере, что это значит для сделок — коротко, для одной строки)
GATE_STATUS_RU: dict[str, tuple[str, str]] = {
    c: (e["ru"], e.get("effect", "")) for c, e in codelists.entries("gate_status").items()
}


def label(code: str | None) -> str:
    """«Держать» для reviewed_keep; неизвестный код возвращается как есть (не прячем ошибку)."""
    if not code:
        return "—"
    return GATE_STATUS_RU.get(code, (code, ""))[0]


def effect(code: str | None) -> str:
    """Что статус значит для докупки/сокращения; для неизвестного кода — пусто."""
    return GATE_STATUS_RU.get(code or "", ("", ""))[1]


def phrase(code: str | None) -> str:
    """«На пересмотре» (докупать нельзя, …) — подпись и смысл одной строкой."""
    e = effect(code)
    return f"«{label(code)}» ({e})" if e else f"«{label(code)}»"
