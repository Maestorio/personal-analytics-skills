#!/usr/bin/env python3
"""
retro_metrics.py

Детерминированные расчёты для retrospective-forecast-audit:
- Шаг 6: применение матрицы ценностей (3 шкалы → value -3..+3 + markers)
- Шаг 7: агрегаты hit_rate, alpha_generation, share_repackaging,
         share_real_alpha, share_crowd_errors, share_personal_errors,
         avg_value, bull_bear_symmetry, error_clustering

LLM делает: извлечение тезисов, сбор консенсуса, верификацию факта,
проставление трёх шкал. Расчёт ценности и агрегатов — этот скрипт.

CLI:
    cat input.json | python3 retro_metrics.py --pretty
    python3 retro_metrics.py --input theses.json --output report.json

Без внешних зависимостей.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from typing import Any

VALID_SCALE1 = {"+2", "+1", "0", "-1", "-2", "pending", "force_majeure"}
VALID_SCALE2 = {"Consensus", "Contrarian", "Off-market", "Split", "unknown"}
VALID_SCALE3 = {"L0", "L-A", "L-B", "L-C"}

# Признаки "не засчитывается" (исключаем из метрик).
NON_COUNTED_SCALE1 = {"pending", "force_majeure"}


def _scale1_int(v: str) -> int | None:
    if v in NON_COUNTED_SCALE1:
        return None
    return int(v)


def compute_value(thesis: dict) -> dict:
    """
    Возвращает {value: int|null, marker: str|null, reason: str, counted: bool}.
    Применяет матрицу ценностей Шага 6, плюс L-R дополнительный штраф.
    """
    s1 = thesis.get("scale_1")
    s2 = thesis.get("scale_2")
    s3 = thesis.get("scale_3")
    lr = bool(thesis.get("l_r", False))

    if s1 not in VALID_SCALE1:
        return {"value": None, "marker": None, "reason": f"invalid scale_1: {s1!r}",
                "counted": False, "error": True}

    if s1 in NON_COUNTED_SCALE1:
        # ⏳ или 🌪 — не засчитывается, метки нет.
        return {
            "value": None, "marker": None, "counted": False,
            "reason": "не засчитывается (pending или force_majeure)",
        }

    if s2 not in VALID_SCALE2 or s3 not in VALID_SCALE3:
        return {"value": None, "marker": None, "counted": False, "error": True,
                "reason": f"invalid scale_2/scale_3: {s2!r}/{s3!r}"}

    s1i = _scale1_int(s1)
    base_value: int | None = None
    base_marker: str | None = None
    base_reason = ""

    # Прямые комбинации из таблицы Шага 6.
    if s1i == 2 and s2 == "Contrarian" and s3 == "L0":
        base_value, base_marker = 3, "⭐"
        base_reason = "альфа: верное Contrarian-предсказание против толпы"
    elif s1i == 2 and s2 == "Off-market" and s3 == "L0":
        base_value = 2
        base_reason = "верный нишевый тезис вне зоны консенсуса"
    elif s1i == 2 and s2 == "Consensus" and s3 == "L0":
        base_value = 1
        base_reason = "ретрансляция: прав, но как и все"
    elif s1i in (1, 0) and s3 == "L-C":
        base_value = -1
        base_reason = "ошибка калибровки при верном направлении"
    elif s1i == -2 and s2 == "Consensus" and s3 == "L-A":
        base_value, base_marker = 0, "🌍"
        base_reason = "мировая ошибка: ошибся как и весь рынок"
    elif s1i == -2 and s2 == "Contrarian" and s3 in ("L-A", "L-B"):
        base_value, base_marker = -2, "👤"
        base_reason = "сольный промах: пошёл против толпы и проиграл"
    elif s1i == -2 and s2 == "Off-market" and s3 in ("L-A", "L-B"):
        base_value, base_marker = -2, "👤"
        base_reason = "сольный промах: нишевый тезис не сработал"
    else:
        # Промежуточный кейс — best-effort по логике "чем больше альфы, тем выше".
        # Используем s1i как базу, +1 для Contrarian-L0, 0 для Consensus-L0, -1 за L-A/B.
        base_value = s1i
        delta = 0
        if s2 == "Contrarian" and s3 == "L0":
            delta += 1
        if s2 == "Off-market" and s3 == "L0":
            delta += 0  # уже учтено в s1i, не доп.
        if s3 in ("L-A", "L-B"):
            delta -= 1
        base_value = max(-3, min(3, s1i + delta))
        base_reason = (f"промежуточная комбинация ({s1}/{s2}/{s3}); "
                       f"best-effort оценка на основе принципа альфы")

    # L-R — аддитивный штраф −1 (⚠️). Накладывается СВЕРХ.
    final_value = base_value
    markers = [base_marker] if base_marker else []
    if lr:
        final_value -= 1
        markers.append("⚠️")

    final_value = max(-3, min(3, final_value))

    marker_str = "".join(markers) if markers else None
    reason = base_reason
    if lr:
        reason += " | L-R: дополнительный штраф −1 за пропуск хвостового риска"

    return {
        "value": final_value,
        "marker": marker_str,
        "counted": True,
        "reason": reason,
    }


def safe_div(a: float, b: float) -> float | None:
    if b == 0:
        return None
    return a / b


def round_share(x: float | None, digits: int = 4) -> float | None:
    return None if x is None else round(x, digits)


def compute_metrics(theses: list[dict], verdicts: list[dict]) -> dict:
    """Шаг 7 — агрегированные метрики."""
    # Парные индексы (theses[i] ↔ verdicts[i]).
    counted_pairs = [
        (t, v) for t, v in zip(theses, verdicts)
        if v.get("counted") and not v.get("error")
    ]
    n_total = len(theses)
    n_counted = len(counted_pairs)

    # Hit rate, full accuracy.
    hits = sum(1 for t, _ in counted_pairs if _scale1_int(t["scale_1"]) in (1, 2))
    full = sum(1 for t, _ in counted_pairs if _scale1_int(t["scale_1"]) == 2)
    hit_rate = safe_div(hits, n_counted)
    full_accuracy = safe_div(full, n_counted)

    # Alpha generation: count(Contrarian + L0) / count(Contrarian)
    contrarian = [t for t, _ in counted_pairs if t["scale_2"] == "Contrarian"]
    alpha_correct = sum(1 for t in contrarian if t["scale_3"] == "L0")
    alpha_gen = safe_div(alpha_correct, len(contrarian))

    # Share repackaging (value=+1) и реальной альфы (value ∈ {+2, +3}).
    repackaging = sum(1 for _, v in counted_pairs if v.get("value") == 1)
    real_alpha = sum(1 for _, v in counted_pairs if v.get("value") in (2, 3))
    share_repackaging = safe_div(repackaging, n_counted)
    share_real_alpha = safe_div(real_alpha, n_counted)

    # Errors: scale_1 ∈ {-1, -2}.
    errors = [(t, v) for t, v in counted_pairs if _scale1_int(t["scale_1"]) in (-1, -2)]
    n_errors = len(errors)
    crowd_errors = sum(
        1 for t, _ in errors if t["scale_2"] == "Consensus" and t["scale_3"] == "L-A"
    )
    personal_errors = sum(
        1 for t, _ in errors
        if (t["scale_2"] == "Contrarian"
            or (t["scale_2"] == "Off-market" and t["scale_3"] in ("L-A", "L-B")))
    )
    share_crowd = safe_div(crowd_errors, n_errors)
    share_personal = safe_div(personal_errors, n_errors)

    # Average value.
    avg_value = safe_div(
        sum(v.get("value", 0) for _, v in counted_pairs),
        n_counted,
    )

    # Bull/bear symmetry.
    directions = Counter(
        t.get("direction", "neutral") for t, _ in counted_pairs
        if t.get("direction") in ("bullish", "bearish")
    )
    bull = directions.get("bullish", 0)
    bear = directions.get("bearish", 0)
    bull_bear = {
        "bullish": bull,
        "bearish": bear,
        "ratio": round_share(safe_div(bull, bear), 2) if bear else None,
        "skew": "bullish_bias" if (bear > 0 and bull / max(bear, 1) >= 2.0) else
                "bearish_bias" if (bull > 0 and bear / max(bull, 1) >= 2.0) else
                "balanced",
    }

    # Error clustering: есть ли блок, в который попадает ≥50% всех ошибок.
    block_counts = Counter(
        t.get("block") for t, _ in errors if t.get("block")
    )
    if block_counts and n_errors > 0:
        max_block, max_count = block_counts.most_common(1)[0]
        max_share = max_count / n_errors
    else:
        max_block, max_count, max_share = None, 0, 0.0
    error_clustering = {
        "max_block": max_block,
        "max_block_count": max_count,
        "max_block_share": round_share(max_share, 4) if max_block else None,
        "is_systemic": max_share >= 0.5 if max_block else False,
    }

    # L-R count (дополнительный штраф).
    l_r_count = sum(1 for t in theses if t.get("l_r"))

    # Pending / force_majeure counts.
    pending = sum(1 for t in theses if t.get("scale_1") == "pending")
    force_majeure = sum(1 for t in theses if t.get("scale_1") == "force_majeure")

    return {
        "n_total": n_total,
        "n_counted": n_counted,
        "n_pending": pending,
        "n_force_majeure": force_majeure,
        "n_errors": n_errors,
        "n_l_r": l_r_count,
        "hit_rate": round_share(hit_rate),
        "full_accuracy": round_share(full_accuracy),
        "alpha_generation": round_share(alpha_gen) if alpha_gen is not None else "n/p",
        "alpha_denominator": len(contrarian),
        "share_repackaging": round_share(share_repackaging),
        "share_real_alpha": round_share(share_real_alpha),
        "share_crowd_errors": round_share(share_crowd) if share_crowd is not None else "n/p",
        "share_personal_errors": round_share(share_personal) if share_personal is not None else "n/p",
        "avg_value": round_share(avg_value, 3),
        "bull_bear_symmetry": bull_bear,
        "error_clustering": error_clustering,
        "value_distribution": {
            v: sum(1 for _, ve in counted_pairs if ve.get("value") == v)
            for v in (-3, -2, -1, 0, 1, 2, 3)
        },
    }


def compute(payload: dict) -> dict:
    theses = payload.get("theses") or []
    verdicts = []
    warnings = []
    for idx, t in enumerate(theses):
        v = compute_value(t)
        v["thesis_id"] = t.get("id", idx)
        verdicts.append(v)
        if v.get("error"):
            warnings.append({
                "thesis_id": v["thesis_id"],
                "issue": "invalid_scales",
                "detail": v.get("reason"),
            })

    metrics = compute_metrics(theses, verdicts)

    return {
        "verdicts": verdicts,
        "metrics": metrics,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Value-matrix and metrics calculator for retrospective-forecast-audit.",
    )
    parser.add_argument("--input", "-i")
    parser.add_argument("--output", "-o")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            payload = json.load(f)
    else:
        payload = json.load(sys.stdin)

    result = compute(payload)
    indent = 2 if args.pretty else None
    serialized = json.dumps(result, ensure_ascii=False, indent=indent)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(serialized)
            f.write("\n")
    else:
        print(serialized)
    return 0


if __name__ == "__main__":
    sys.exit(main())
