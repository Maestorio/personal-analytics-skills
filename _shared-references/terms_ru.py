#!/usr/bin/env python3
"""
terms_ru.py — термины системы словами для человека (контракт D плана переосмысления вьюера, 2026-10-26).

Зачем. Коды системы (L2, HOLD/TRIM, KEEP/BALANCE, Mode 4, статусы гейтов, уверенность 0,5) утекали
в текст отчётов и карточек, и владелец их не читал. Слова кодов — из кодлистов (`codelists.json` рядом, загрузчик `codelists.py`):
этот модуль — тонкая обёртка с прежними публичными именами для скриптов (render_weekly_md.py,
prior_digest.py). Вьюер берёт те же слова из сгенерированного `tools/assets/codelists.js`.
Совпадение держат `tools/tests/test_terms_ru.py` и `tools/tests/test_codelists.py`; статусы гейтов —
`gate_status_ru.py` рядом.

Коды остаются в машинных полях YAML/JSON; меняются только тексты для человека.

Зависимости: stdlib (+ codelists.py/codelists.json и gate_status_ru.py из той же папки).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codelists  # noqa: E402
from gate_status_ru import GATE_STATUS_RU, label as gate_label, effect as gate_effect, phrase as gate_phrase  # noqa: E402,F401

# Режимы советника (ru-portfolio-advisor EXAMPLES.md): ключи — mode_codes кодлистов (с legacy «4»).
MODE_RU: dict[str, str] = codelists.words("mode_codes")

# Вердикт советника (advisor_verdict, on_trigger.verdict) — кодлист verdict (с legacy-кодами облигаций).
VERDICT_RU: dict[str, str] = codelists.words("verdict")

# План владельца по бумаге (снапшот ie_actual.per_ticker[].user_plan) — кодлист user_plan.
USER_PLAN_RU: dict[str, str] = codelists.words("user_plan")

# Статус бумаги в моём плане — что владелец уже сделал (кодлист user_status; старые значения из Numbers
# остаются текстом как есть).
USER_STATUS_RU: dict[str, str] = codelists.words("user_status")


def user_status_word(code) -> str:
    return USER_STATUS_RU.get(str(code), str(code)) if code else "—"


# База долей акций: «L2» в тексте для человека.
L2_RU = "от акций"

# Уверенность вердикта (advisor_verdict_confidence, 0..1) — словом, не числом (решение владельца 26.10):
# ниже 0,6 низкая · 0,6–0,8 средняя · от 0,8 высокая. Это полнота и свежесть данных под вердиктом,
# не вероятность исхода (та — p_outperform_3m). Как во вьюере (confWord).
CONF_LOW_BELOW = 0.6
CONF_HIGH_FROM = 0.8


def conf_word(c) -> str | None:
    """0.5 → «низкая», 0.65 → «средняя», 0.85 → «высокая»; не число → None. Значения 1–100 — проценты."""
    if isinstance(c, bool) or not isinstance(c, (int, float)):
        return None
    v = c / 100 if c > 1 else c
    return "низкая" if v < CONF_LOW_BELOW else "средняя" if v < CONF_HIGH_FROM else "высокая"


def verdict_word(code) -> str:
    """HOLD → «Держать»; неизвестный код возвращается как есть (не прячем ошибку)."""
    if not code:
        return "—"
    return VERDICT_RU.get(str(code), str(code))


def mode_word(n) -> str | None:
    """'4' → «разбор бумаги»; неизвестный номер → None."""
    return MODE_RU.get(str(n))


def user_plan_word(code) -> str:
    return USER_PLAN_RU.get(str(code), str(code)) if code else "—"
