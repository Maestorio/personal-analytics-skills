#!/usr/bin/env python3
"""Регрессионные тесты для similarity_score.py.

Запуск из корня репозитория:
    python3 skills/travel-planning/tests/test_similarity_score.py

Stdlib only. Без внешних файлов.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "skills" / "travel-planning" / "scripts" / "similarity_score.py"

sys.path.insert(0, str(SCRIPT.parent))
from similarity_score import (  # noqa: E402
    ARCHETYPE_ALIASES,
    ARCHETYPE_WEIGHTS,
    DEFAULT_WEIGHTS,
    aggregate,
    build_warnings,
    canonical_archetype,
    normalize_weights,
    resolve_override_weights,
    resolve_weights_from_archetype,
    score_author,
)
import taxonomy  # noqa: E402


checks_run = 0
checks_failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global checks_run, checks_failed
    checks_run += 1
    if condition:
        print(f"  ✓ {name}")
    else:
        checks_failed += 1
        suffix = f" — {detail}" if detail else ""
        print(f"  ✗ {name}{suffix}")


def approx(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) < tol


# ─── Помощники ────────────────────────────────────────────────────────────

def make_author(
    id: str = "a1",
    style: float | None = 5.0,
    focus: float | None = 5.0,
    pace: float | None = 5.0,
    independence: float | None = 5.0,
    depth: float | None = 5.0,
    demo: float | None = 5.0,
    signal: bool = False,
    signal_desc: str = "",
    user_added: bool = False,
) -> dict:
    return {
        "id": id,
        "url": f"https://example.com/{id}",
        "name": id,
        "components": {
            "style": style,
            "focus": focus,
            "pace": pace,
            "independence": independence,
            "depth": depth,
            "demo": demo,
        },
        "outlier_signal": {"present": signal, "description": signal_desc},
        "user_added": user_added,
    }


def score(author: dict, weights: list[float] | None = None) -> dict:
    return score_author(
        author,
        list(weights or DEFAULT_WEIGHTS),
        high_threshold=7.0,
        medium_threshold=5.0,
    )


# ─── 1. normalize_weights ─────────────────────────────────────────────────

def test_normalize_weights():
    print("\n[1] normalize_weights")

    w = normalize_weights(DEFAULT_WEIGHTS, [True] * 6)
    check("all known → identity", w == DEFAULT_WEIGHTS)
    check("sum preserved (full)", approx(sum(w), 100.0))

    w = normalize_weights(DEFAULT_WEIGHTS, [True, True, False, True, True, True])
    check("5 known → sum still 100", approx(sum(w), 100.0))
    check("dropped weight is 0", w[2] == 0.0)
    check("known weight scaled up", w[0] > 25.0)

    w = normalize_weights(DEFAULT_WEIGHTS, [True, False, True, True, False, True])
    check("4 known → sum still 100", approx(sum(w), 100.0))
    # known weights = 25+15+10+10 = 60, scale = 100/60
    check("4-known: style scale check", approx(w[0], 25.0 * 100 / 60))

    w = normalize_weights(DEFAULT_WEIGHTS, [False] * 6)
    check("nothing known → all zero", w == [0.0] * 6)

    w = normalize_weights(DEFAULT_WEIGHTS, [True, False, False, False, False, False])
    check("single known → carries all weight", approx(w[0], 100.0))
    check("single known → others 0", all(w[i] == 0.0 for i in range(1, 6)))


# ─── 2. score_author: components_known и confidence ───────────────────────

def test_components_known_and_confidence():
    print("\n[2] components_known / confidence")

    r = score(make_author())
    check("all 6 known → components_known=6", r["components_known"] == 6)
    check("all 6 known → confidence=full", r["confidence"] == "full")

    r = score(make_author(pace=None, demo=None))
    check("4 known → components_known=4", r["components_known"] == 4)
    check("4 known → confidence=partial", r["confidence"] == "partial")

    r = score(make_author(pace=None, demo=None, focus=None))
    check("3 known → components_known=3", r["components_known"] == 3)
    check("3 known → confidence=low", r["confidence"] == "low")

    r = score(make_author(pace=None, demo=None, focus=None, depth=None))
    check("2 known → components_known=2", r["components_known"] == 2)
    check("2 known → confidence=unscored", r["confidence"] == "unscored")

    r = score(make_author(
        style=None, focus=None, pace=None,
        independence=None, depth=None, demo=None,
    ))
    check("0 known → components_known=0", r["components_known"] == 0)
    check("0 known → confidence=unscored", r["confidence"] == "unscored")
    check("0 known → total_score=0", r["total_score"] == 0.0)


# ─── 3. score_author: total_score ─────────────────────────────────────────

def test_total_score():
    print("\n[3] total_score arithmetic")

    r = score(make_author(
        style=10, focus=10, pace=10,
        independence=10, depth=10, demo=10,
    ))
    check("all 10/10 → score 10.0", approx(r["total_score"], 10.0))

    r = score(make_author(
        style=0, focus=0, pace=0,
        independence=0, depth=0, demo=0,
    ))
    check("all 0/0 → score 0.0", approx(r["total_score"], 0.0))

    # 8*25 + 6*25 + 7*15 + 9*10 + 5*15 + 7*10 = 200+150+105+90+75+70 = 690
    r = score(make_author(
        style=8, focus=6, pace=7,
        independence=9, depth=5, demo=7,
    ))
    check("mixed values → score 6.9",
          approx(r["total_score"], 6.9, tol=1e-3),
          f"got {r['total_score']}")

    # Partial: 4/6 known, все 10 → нормализация даёт 10.0
    r = score(make_author(style=10, focus=10, pace=None,
                          independence=10, depth=None, demo=10))
    check("partial 4/6 all 10 → score 10.0",
          approx(r["total_score"], 10.0, tol=1e-3),
          f"got {r['total_score']}")

    # Partial mismatch: 3/6 known, 8/4/0 — нормализация
    # known=[T,T,F,T,F,F], weights known=[25,25,_,10,_,_], sum=60, scale=100/60
    # eff = [41.67, 41.67, 0, 16.67, 0, 0], sum=100
    # weighted = 8*41.67 + 4*41.67 + 0*16.67 = 333.36 + 166.68 + 0 = 500.04
    # total = 500.04/100 ≈ 5.0
    r = score(make_author(style=8, focus=4, pace=None,
                          independence=0, depth=None, demo=None))
    check("partial 3/6 mixed → score ≈5.0",
          approx(r["total_score"], 5.0, tol=1e-2),
          f"got {r['total_score']}")


# ─── 4. score_author: categorization ──────────────────────────────────────

def test_categorization():
    print("\n[4] categorization")

    # score 8 (style/focus 8, остальное 8) — HIGH
    r = score(make_author(style=8, focus=8, pace=8,
                          independence=8, depth=8, demo=8))
    check("score 8 → HIGH", r["category"] == "HIGH")

    # score 6 — MEDIUM
    r = score(make_author(style=6, focus=6, pace=6,
                          independence=6, depth=6, demo=6))
    check("score 6 no signal → MEDIUM", r["category"] == "MEDIUM")

    # score 4 — LOW
    r = score(make_author(style=4, focus=4, pace=4,
                          independence=4, depth=4, demo=4))
    check("score 4 no signal → LOW", r["category"] == "LOW")

    # score 4 + signal → OUTLIER
    r = score(make_author(style=4, focus=4, pace=4,
                          independence=4, depth=4, demo=4,
                          signal=True, signal_desc="фотограф"))
    check("score 4 + signal → OUTLIER", r["category"] == "OUTLIER")

    # score 6 + signal → OUTLIER (signal в MEDIUM зоне)
    r = score(make_author(style=6, focus=6, pace=6,
                          independence=6, depth=6, demo=6,
                          signal=True))
    check("score 6 + signal → OUTLIER", r["category"] == "OUTLIER")

    # score 8 + signal → HIGH (signal не превращает HIGH в OUTLIER)
    r = score(make_author(style=8, focus=8, pace=8,
                          independence=8, depth=8, demo=8,
                          signal=True))
    check("score 8 + signal → HIGH (не OUTLIER)", r["category"] == "HIGH")

    # 2 known + score 10 → UNSCORED (override)
    r = score(make_author(style=10, focus=10, pace=None,
                          independence=None, depth=None, demo=None))
    check("2 known → UNSCORED override", r["category"] == "UNSCORED")

    # 2 known + score 10 + signal → UNSCORED (UNSCORED перебивает OUTLIER)
    r = score(make_author(style=10, focus=10, pace=None,
                          independence=None, depth=None, demo=None,
                          signal=True))
    check("2 known + signal → UNSCORED (не OUTLIER)",
          r["category"] == "UNSCORED")


# ─── 5. low_confidence_flag ───────────────────────────────────────────────

def test_low_confidence_flag():
    print("\n[5] low_confidence_flag")

    # HIGH 6/6 — no flag
    r = score(make_author(style=8, focus=8, pace=8,
                          independence=8, depth=8, demo=8))
    check("HIGH 6/6 → no low_confidence", r["low_confidence_flag"] is False)

    # HIGH 4/6 — no flag (4 >= LOW_CONFIDENCE_KNOWN_THRESHOLD=4)
    r = score(make_author(style=10, focus=10, pace=None,
                          independence=10, depth=None, demo=10))
    check("HIGH 4/6 → no low_confidence", r["low_confidence_flag"] is False)

    # HIGH 3/6 — flag
    r = score(make_author(style=10, focus=10, pace=None,
                          independence=10, depth=None, demo=None))
    check("HIGH 3/6 → low_confidence flag", r["low_confidence_flag"] is True)

    # OUTLIER 3/6 — flag
    r = score(make_author(style=4, focus=4, pace=None,
                          independence=4, depth=None, demo=None,
                          signal=True))
    check("OUTLIER 3/6 → low_confidence flag", r["low_confidence_flag"] is True)

    # LOW 6/6 — no flag (LOW не нуждается)
    r = score(make_author(style=2, focus=2, pace=2,
                          independence=2, depth=2, demo=2))
    check("LOW 6/6 → no low_confidence", r["low_confidence_flag"] is False)

    # MEDIUM 3/6 — no flag (MEDIUM не помечается)
    r = score(make_author(style=6, focus=6, pace=None,
                          independence=6, depth=None, demo=None))
    check("MEDIUM 3/6 → no low_confidence", r["low_confidence_flag"] is False)


# ─── 6. reading_list (in_reading_list) ────────────────────────────────────

def test_reading_list():
    print("\n[6] in_reading_list")

    r = score(make_author(style=8, focus=8, pace=8,
                          independence=8, depth=8, demo=8))
    check("HIGH → in_reading_list", r["in_reading_list"] is True)

    r = score(make_author(style=4, focus=4, pace=4,
                          independence=4, depth=4, demo=4,
                          signal=True))
    check("OUTLIER → in_reading_list", r["in_reading_list"] is True)

    r = score(make_author(style=6, focus=6, pace=6,
                          independence=6, depth=6, demo=6))
    check("MEDIUM → not in_reading_list", r["in_reading_list"] is False)

    r = score(make_author(style=2, focus=2, pace=2,
                          independence=2, depth=2, demo=2))
    check("LOW → not in_reading_list", r["in_reading_list"] is False)

    r = score(make_author(style=10, focus=10, pace=None,
                          independence=None, depth=None, demo=None,
                          signal=True))
    check("UNSCORED + signal → not in_reading_list",
          r["in_reading_list"] is False)


# ─── 7. user_added — независимый scoring ─────────────────────────────────

def test_user_added():
    print("\n[7] user_added")

    r = score(make_author(style=8, focus=8, pace=8,
                          independence=8, depth=8, demo=8,
                          user_added=True))
    check("user_added HIGH → in_reading_list", r["in_reading_list"] is True)
    check("user_added field preserved", r["user_added"] is True)

    r = score(make_author(style=3, focus=3, pace=3,
                          independence=3, depth=3, demo=3,
                          user_added=True))
    check("user_added LOW → not in_reading_list (независимый scoring)",
          r["in_reading_list"] is False)
    check("user_added flag preserved для LOW", r["user_added"] is True)


# ─── 8. aggregate distribution ────────────────────────────────────────────

def test_aggregate_distribution():
    print("\n[8] aggregate distribution")

    authors = [
        # 3× HIGH
        make_author(id="h1", style=8, focus=8, pace=8,
                    independence=8, depth=8, demo=8),
        make_author(id="h2", style=9, focus=9, pace=9,
                    independence=9, depth=9, demo=9),
        make_author(id="h3", style=7, focus=7, pace=7,
                    independence=7, depth=7, demo=7),
        # 2× MEDIUM
        make_author(id="m1", style=6, focus=6, pace=6,
                    independence=6, depth=6, demo=6),
        make_author(id="m2", style=5, focus=5, pace=5,
                    independence=5, depth=5, demo=5),
        # 2× LOW
        make_author(id="l1", style=3, focus=3, pace=3,
                    independence=3, depth=3, demo=3),
        make_author(id="l2", style=2, focus=2, pace=2,
                    independence=2, depth=2, demo=2),
        # 1× OUTLIER (score=4 + signal)
        make_author(id="o1", style=4, focus=4, pace=4,
                    independence=4, depth=4, demo=4, signal=True),
        # 1× UNSCORED (2 known)
        make_author(id="u1", style=10, focus=10, pace=None,
                    independence=None, depth=None, demo=None),
    ]
    result = aggregate(authors, list(DEFAULT_WEIGHTS), 7.0, 5.0)

    d = result["distribution"]
    check("distribution.high=3", d["high"] == 3, f"got {d['high']}")
    check("distribution.medium=2", d["medium"] == 2, f"got {d['medium']}")
    check("distribution.low=2", d["low"] == 2, f"got {d['low']}")
    check("distribution.outlier=1", d["outlier"] == 1, f"got {d['outlier']}")
    check("distribution.unscored=1", d["unscored"] == 1, f"got {d['unscored']}")
    check("distribution.total=9", d["total"] == 9, f"got {d['total']}")

    check("reading_list has 4 entries (3 HIGH + 1 OUTLIER)",
          len(result["reading_list"]) == 4,
          f"got {result['reading_list']}")
    check("unscored_with_signal is empty (signal=False у u1)",
          result["unscored_with_signal"] == [])


# ─── 9. warnings ──────────────────────────────────────────────────────────

def test_warnings():
    print("\n[9] warnings")

    # 3 HIGH → critical
    authors = [
        make_author(id=f"h{i}", style=8, focus=8, pace=8,
                    independence=8, depth=8, demo=8)
        for i in range(3)
    ]
    result = aggregate(authors, list(DEFAULT_WEIGHTS), 7.0, 5.0)
    severities = [w["severity"] for w in result["warnings"]]
    check("HIGH=3 → critical warning", "critical" in severities)

    # 6 HIGH → borderline
    authors = [
        make_author(id=f"h{i}", style=8, focus=8, pace=8,
                    independence=8, depth=8, demo=8)
        for i in range(6)
    ]
    result = aggregate(authors, list(DEFAULT_WEIGHTS), 7.0, 5.0)
    severities = [w["severity"] for w in result["warnings"]]
    check("HIGH=6 → borderline warning", "borderline" in severities)
    check("HIGH=6 → no critical", "critical" not in severities)

    # 10 HIGH → no high-count warning
    authors = [
        make_author(id=f"h{i}", style=8, focus=8, pace=8,
                    independence=8, depth=8, demo=8)
        for i in range(10)
    ]
    result = aggregate(authors, list(DEFAULT_WEIGHTS), 7.0, 5.0)
    msgs = " ".join(w["message"] for w in result["warnings"])
    check("HIGH=10 → no 'выборка' warning", "выборка" not in msgs.lower())

    # UNSCORED present → info warning
    authors = [
        make_author(id="h1", style=8, focus=8, pace=8,
                    independence=8, depth=8, demo=8),
        make_author(id="u1", style=10, focus=10, pace=None,
                    independence=None, depth=None, demo=None),
        make_author(id="u2", style=10, focus=10, pace=None,
                    independence=None, depth=None, demo=None),
    ]
    result = aggregate(authors, list(DEFAULT_WEIGHTS), 7.0, 5.0)
    unscored_warning = [w for w in result["warnings"] if "UNSCORED" in w["message"]]
    check("UNSCORED=2 → info warning", len(unscored_warning) == 1)

    # UNSCORED with signal → отдельный текст в warning
    authors = [
        make_author(id="u1", style=10, focus=10, pace=None,
                    independence=None, depth=None, demo=None,
                    signal=True, signal_desc="фотограф"),
    ]
    result = aggregate(authors, list(DEFAULT_WEIGHTS), 7.0, 5.0)
    unscored_warning = next(
        (w for w in result["warnings"] if "UNSCORED" in w["message"]),
        None,
    )
    check("UNSCORED with signal → warning упоминает unscored_with_signal",
          unscored_warning is not None
          and "unscored_with_signal" in unscored_warning["message"])
    check("unscored_with_signal list имеет u1",
          result["unscored_with_signal"] == ["u1"])

    # low_confidence в HIGH → info warning
    authors = [
        # HIGH 3/6 → low_confidence
        make_author(id="h1", style=10, focus=10, pace=None,
                    independence=10, depth=None, demo=None),
        # HIGH 6/6 — без флага
        make_author(id="h2", style=8, focus=8, pace=8,
                    independence=8, depth=8, demo=8),
    ]
    result = aggregate(authors, list(DEFAULT_WEIGHTS), 7.0, 5.0)
    msgs = " ".join(w["message"] for w in result["warnings"])
    check("low_confidence в HIGH → warning о малых данных",
          "малыми данными" in msgs)

    # user_added в LOW → info warning
    authors = [
        make_author(id="h1", style=8, focus=8, pace=8,
                    independence=8, depth=8, demo=8),
        make_author(id="ua1", style=3, focus=3, pace=3,
                    independence=3, depth=3, demo=3, user_added=True),
    ]
    result = aggregate(authors, list(DEFAULT_WEIGHTS), 7.0, 5.0)
    msgs = " ".join(w["message"] for w in result["warnings"])
    check("user_added в LOW → warning о визуальной привлекательности",
          "вручную" in msgs and "ниже HIGH" in msgs)


# ─── 10. confidence_breakdown ────────────────────────────────────────────

def test_confidence_breakdown():
    print("\n[10] confidence_breakdown")
    authors = [
        # full
        make_author(id="f1", style=8, focus=8, pace=8,
                    independence=8, depth=8, demo=8),
        # partial (4)
        make_author(id="p1", style=8, focus=8, pace=None,
                    independence=8, depth=None, demo=8),
        # low (3)
        make_author(id="l1", style=8, focus=8, pace=None,
                    independence=8, depth=None, demo=None),
        # unscored (2)
        make_author(id="u1", style=10, focus=10, pace=None,
                    independence=None, depth=None, demo=None),
    ]
    result = aggregate(authors, list(DEFAULT_WEIGHTS), 7.0, 5.0)
    cb = result["confidence_breakdown"]
    check("confidence.full=1", cb["full"] == 1, f"got {cb}")
    check("confidence.partial=1", cb["partial"] == 1, f"got {cb}")
    check("confidence.low=1", cb["low"] == 1, f"got {cb}")
    check("confidence.unscored=1", cb["unscored"] == 1, f"got {cb}")


# ─── 11. custom weights и thresholds ─────────────────────────────────────

def test_custom_weights_and_thresholds():
    print("\n[11] custom weights / thresholds")

    # Custom weights, все 10 → score 10 независимо от весов
    custom = [50, 30, 5, 5, 5, 5]
    r = score_author(
        make_author(style=10, focus=10, pace=10,
                    independence=10, depth=10, demo=10),
        custom, 7.0, 5.0,
    )
    check("custom weights, all 10 → score 10",
          approx(r["total_score"], 10.0))

    # Дисбаланс: style=10 (вес 50), остальное 0 → score = 10*50/100 = 5.0
    r = score_author(
        make_author(style=10, focus=0, pace=0,
                    independence=0, depth=0, demo=0),
        custom, 7.0, 5.0,
    )
    check("custom weights, dominant style=10 → score 5.0",
          approx(r["total_score"], 5.0, tol=1e-3),
          f"got {r['total_score']}")

    # Custom thresholds: HIGH ≥ 6 → score 6.5 теперь HIGH вместо MEDIUM
    r = score_author(
        make_author(style=6.5, focus=6.5, pace=6.5,
                    independence=6.5, depth=6.5, demo=6.5),
        list(DEFAULT_WEIGHTS), 6.0, 4.0,
    )
    check("score 6.5 with high_threshold=6 → HIGH",
          r["category"] == "HIGH")


# ─── 12. End-to-end subprocess ────────────────────────────────────────────

def test_subprocess_end_to_end():
    print("\n[12] subprocess end-to-end")

    payload = {
        "authors": [
            make_author(id="h1", style=8, focus=8, pace=8,
                        independence=8, depth=8, demo=8),
            make_author(id="o1", style=4, focus=4, pace=4,
                        independence=4, depth=4, demo=4,
                        signal=True, signal_desc="редкий регион"),
            make_author(id="u1", style=10, focus=10, pace=None,
                        independence=None, depth=None, demo=None,
                        signal=True),
        ]
    }
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    check("subprocess exit 0", result.returncode == 0,
          f"stderr: {result.stderr}")
    output = json.loads(result.stdout)
    check("subprocess: 1 HIGH", output["distribution"]["high"] == 1)
    check("subprocess: 1 OUTLIER", output["distribution"]["outlier"] == 1)
    check("subprocess: 1 UNSCORED", output["distribution"]["unscored"] == 1)
    check("subprocess: reading_list has 2",
          len(output["reading_list"]) == 2)
    check("subprocess: unscored_with_signal has u1",
          output["unscored_with_signal"] == ["u1"])
    check("subprocess: weights_used = default",
          output["weights_used"] == list(DEFAULT_WEIGHTS))

    # CLI --weights override
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--weights", "50,10,10,10,10,10"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    check("subprocess --weights override exit 0", result.returncode == 0)
    output = json.loads(result.stdout)
    check("subprocess: weights_used = custom",
          output["weights_used"] == [50.0, 10.0, 10.0, 10.0, 10.0, 10.0])

    # CLI --thresholds override
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--thresholds", "6.0,4.0"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    check("subprocess --thresholds override exit 0", result.returncode == 0)
    output = json.loads(result.stdout)
    check("subprocess: thresholds_used.high=6.0",
          output["thresholds_used"]["high"] == 6.0)

    # Malformed JSON → exit 2
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input="not json",
        capture_output=True,
        text=True,
    )
    check("subprocess malformed JSON → exit 2", result.returncode == 2)

    # Missing 'authors' field
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input='{"foo": "bar"}',
        capture_output=True,
        text=True,
    )
    check("subprocess missing 'authors' → exit 2", result.returncode == 2)


# ─── 13. weighted_contributions ──────────────────────────────────────────

def test_weighted_contributions():
    print("\n[13] weighted_contributions")

    # All 10/10: contributions = [10*25/100, 10*25/100, 10*15/100,
    # 10*10/100, 10*15/100, 10*10/100] = [2.5, 2.5, 1.5, 1.0, 1.5, 1.0]
    r = score(make_author(style=10, focus=10, pace=10,
                          independence=10, depth=10, demo=10))
    wc = r["weighted_contributions"]
    check("wc.style = 2.5", approx(wc["style"], 2.5))
    check("wc.focus = 2.5", approx(wc["focus"], 2.5))
    check("wc.pace = 1.5", approx(wc["pace"], 1.5))
    check("wc.independence = 1.0", approx(wc["independence"], 1.0))
    check("wc.depth = 1.5", approx(wc["depth"], 1.5))
    check("wc.demo = 1.0", approx(wc["demo"], 1.0))
    check("sum(wc) == total_score (all 10)",
          approx(sum(wc.values()), r["total_score"]))

    # Mixed: 8,6,7,9,5,7. См. test 12 — total=6.9
    # Contributions: 8*25/100, 6*25/100, 7*15/100, 9*10/100, 5*15/100, 7*10/100
    # = 2.0, 1.5, 1.05, 0.9, 0.75, 0.7. Sum = 6.9
    r = score(make_author(style=8, focus=6, pace=7,
                          independence=9, depth=5, demo=7))
    wc = r["weighted_contributions"]
    check("mixed wc.style = 2.0", approx(wc["style"], 2.0))
    check("mixed wc.focus = 1.5", approx(wc["focus"], 1.5))
    check("mixed wc.pace = 1.05", approx(wc["pace"], 1.05))
    check("mixed wc.demo = 0.7", approx(wc["demo"], 0.7))
    check("mixed sum(wc) == 6.9", approx(sum(wc.values()), 6.9, tol=1e-3))
    check("mixed sum(wc) == total_score",
          approx(sum(wc.values()), r["total_score"]))

    # Partial: pace=null, demo=null. style=focus=indep=depth=10.
    # known_sum=70, scale=100/70. eff = [25*10/7, 25*10/7, 0, 10*10/7, 0, 10*10/7]
    # contributions = [10*(25*10/7)/100, ..., 0, 10*(10*10/7)/100, 0, 10*(10*10/7)/100]
    # = [25/7*1, ...] хм, давай прямо: contribution = value * eff_weight / 100
    # eff_weights: [35.714, 35.714, 0, 14.286, 0, 14.286]
    # contributions: [10*35.714/100, 10*35.714/100, 0, 10*14.286/100, 0, 10*14.286/100]
    # = [3.571, 3.571, 0, 1.429, 0, 1.429]. Sum = 10.0
    r = score(make_author(style=10, focus=10, pace=None,
                          independence=10, depth=None, demo=10))
    wc = r["weighted_contributions"]
    check("partial wc.pace = 0 (null)", wc["pace"] == 0.0)
    check("partial wc.depth = 0 (null)", wc["depth"] == 0.0)
    check("partial wc.style ≈ 3.571", approx(wc["style"], 100 * 25 / 70 / 10,
                                              tol=1e-3))
    check("partial sum(wc) == total_score (10.0)",
          approx(sum(wc.values()), r["total_score"], tol=1e-3))

    # UNSCORED (all null): contributions = [0, 0, 0, 0, 0, 0]
    r = score(make_author(style=None, focus=None, pace=None,
                          independence=None, depth=None, demo=None))
    wc = r["weighted_contributions"]
    check("unscored: all contributions = 0",
          all(v == 0.0 for v in wc.values()))


# ─── 14. reading_list_extended (MEDIUM borderline-high) ──────────────────

def test_reading_list_extended():
    print("\n[14] reading_list_extended (MEDIUM >= 6.5)")

    # Score 6.6 (MEDIUM с total >= 6.5) → in_extended_reading_list
    # 7*25 + 7*25 + 6*15 + 6*10 + 7*15 + 5*10 = 175+175+90+60+105+50 = 655 → 6.55
    r = score(make_author(style=7, focus=7, pace=6,
                          independence=6, depth=7, demo=5))
    check("MEDIUM 6.55 → category=MEDIUM", r["category"] == "MEDIUM")
    check("MEDIUM 6.55 → in_extended_reading_list",
          r["in_extended_reading_list"] is True,
          f"got total={r['total_score']}")
    check("MEDIUM 6.55 → NOT in_reading_list (только extended)",
          r["in_reading_list"] is False)

    # Score 6.4 → MEDIUM, НЕ в extended
    # 7*25 + 6*25 + 6*15 + 6*10 + 7*15 + 5*10 = 175+150+90+60+105+50 = 630 → 6.30
    r = score(make_author(style=7, focus=6, pace=6,
                          independence=6, depth=7, demo=5))
    check("MEDIUM 6.30 → category=MEDIUM", r["category"] == "MEDIUM")
    check("MEDIUM 6.30 → NOT in_extended (< 6.5)",
          r["in_extended_reading_list"] is False,
          f"got total={r['total_score']}")

    # HIGH 8.0 → in_reading_list, НЕ в extended (extended только для MEDIUM)
    r = score(make_author(style=8, focus=8, pace=8,
                          independence=8, depth=8, demo=8))
    check("HIGH 8.0 → in_reading_list", r["in_reading_list"] is True)
    check("HIGH 8.0 → NOT in_extended (HIGH не дублируется)",
          r["in_extended_reading_list"] is False)

    # OUTLIER (MEDIUM с signal) — приоритет OUTLIER → НЕ в extended
    # 6.55 + signal → OUTLIER, не MEDIUM
    r = score(make_author(style=7, focus=7, pace=6,
                          independence=6, depth=7, demo=5, signal=True))
    check("MEDIUM 6.55 + signal → OUTLIER (не MEDIUM)",
          r["category"] == "OUTLIER")
    check("OUTLIER 6.55 → НЕ в extended (extended только для чистых MEDIUM)",
          r["in_extended_reading_list"] is False)

    # aggregate: проверяем reading_list_extended
    authors = [
        make_author(id="h1", style=8, focus=8, pace=8,
                    independence=8, depth=8, demo=8),  # HIGH
        make_author(id="m1", style=7, focus=7, pace=6,
                    independence=6, depth=7, demo=5),  # MEDIUM 6.55
        make_author(id="m2", style=6, focus=6, pace=6,
                    independence=6, depth=6, demo=6),  # MEDIUM 6.0
        make_author(id="l1", style=3, focus=3, pace=3,
                    independence=3, depth=3, demo=3),  # LOW
    ]
    result = aggregate(authors, list(DEFAULT_WEIGHTS), 7.0, 5.0)
    check("aggregate reading_list_extended has m1",
          "m1" in result["reading_list_extended"])
    check("aggregate reading_list_extended NOT has m2",
          "m2" not in result["reading_list_extended"])
    check("aggregate reading_list_extended NOT has h1 (HIGH)",
          "h1" not in result["reading_list_extended"])

    # Custom borderline через CLI: aggregate с borderline=6.0
    result = aggregate(authors, list(DEFAULT_WEIGHTS), 7.0, 5.0,
                       medium_high_borderline=6.0)
    check("custom borderline=6.0: m1 и m2 в extended",
          "m1" in result["reading_list_extended"]
          and "m2" in result["reading_list_extended"])


# ─── 14b. anti-bloat OUTLIER warning (v0.8) ─────────────────────────────

def test_outlier_bloat_warning():
    print("\n[14b] OUTLIER bloat warning")

    # ≤30% OUTLIER — no bloat warning
    authors = [
        make_author(id="h1", style=8, focus=8, pace=8,
                    independence=8, depth=8, demo=8),  # HIGH
        make_author(id="h2", style=8, focus=8, pace=8,
                    independence=8, depth=8, demo=8),  # HIGH
        make_author(id="h3", style=8, focus=8, pace=8,
                    independence=8, depth=8, demo=8),  # HIGH
        make_author(id="h4", style=8, focus=8, pace=8,
                    independence=8, depth=8, demo=8),  # HIGH
        make_author(id="h5", style=8, focus=8, pace=8,
                    independence=8, depth=8, demo=8),  # HIGH
        make_author(id="h6", style=8, focus=8, pace=8,
                    independence=8, depth=8, demo=8),  # HIGH
        make_author(id="h7", style=8, focus=8, pace=8,
                    independence=8, depth=8, demo=8),  # HIGH
        make_author(id="o1", style=4, focus=4, pace=4,
                    independence=4, depth=4, demo=4, signal=True),  # OUTLIER
        make_author(id="o2", style=4, focus=4, pace=4,
                    independence=4, depth=4, demo=4, signal=True),  # OUTLIER
        make_author(id="l1", style=2, focus=2, pace=2,
                    independence=2, depth=2, demo=2),  # LOW
    ]
    result = aggregate(authors, list(DEFAULT_WEIGHTS), 7.0, 5.0)
    bloat_warnings = [w for w in result["warnings"]
                      if "OUTLIER" in w["message"] and "размывается" in w["message"]]
    check("20% OUTLIER → no bloat warning",
          len(bloat_warnings) == 0,
          f"got {bloat_warnings}")

    # Vietnam case: 51% OUTLIER → critical warning
    authors = []
    # 4 HIGH (10%)
    for i in range(4):
        authors.append(make_author(id=f"h{i}", style=8, focus=8, pace=8,
                                    independence=8, depth=8, demo=8))
    # 20 OUTLIER (51% of 39)
    for i in range(20):
        authors.append(make_author(id=f"o{i}", style=4, focus=4, pace=4,
                                    independence=4, depth=4, demo=4,
                                    signal=True))
    # 10 MEDIUM
    for i in range(10):
        authors.append(make_author(id=f"m{i}", style=6, focus=6, pace=6,
                                    independence=6, depth=6, demo=6))
    # 5 LOW
    for i in range(5):
        authors.append(make_author(id=f"l{i}", style=2, focus=2, pace=2,
                                    independence=2, depth=2, demo=2))
    result = aggregate(authors, list(DEFAULT_WEIGHTS), 7.0, 5.0)
    bloat_warnings = [w for w in result["warnings"] if "размывается" in w["message"]]
    check("Vietnam case (51% OUTLIER) → bloat warning",
          len(bloat_warnings) == 1,
          f"got {len(bloat_warnings)} bloat warnings")
    check("bloat warning severity=critical",
          bloat_warnings[0]["severity"] == "critical" if bloat_warnings else False)

    # Граница: exactly 30% — no warning (>30% triggers)
    authors = [
        make_author(id="h1", style=8, focus=8, pace=8,
                    independence=8, depth=8, demo=8),  # HIGH
        make_author(id="m1", style=6, focus=6, pace=6,
                    independence=6, depth=6, demo=6),  # MEDIUM
        make_author(id="m2", style=6, focus=6, pace=6,
                    independence=6, depth=6, demo=6),  # MEDIUM
        make_author(id="o1", style=4, focus=4, pace=4,
                    independence=4, depth=4, demo=4, signal=True),  # OUTLIER
        make_author(id="o2", style=4, focus=4, pace=4,
                    independence=4, depth=4, demo=4, signal=True),  # OUTLIER
        make_author(id="o3", style=4, focus=4, pace=4,
                    independence=4, depth=4, demo=4, signal=True),  # OUTLIER (3/10 = 30%)
        make_author(id="l1", style=2, focus=2, pace=2,
                    independence=2, depth=2, demo=2),
        make_author(id="l2", style=2, focus=2, pace=2,
                    independence=2, depth=2, demo=2),
        make_author(id="l3", style=2, focus=2, pace=2,
                    independence=2, depth=2, demo=2),
        make_author(id="l4", style=2, focus=2, pace=2,
                    independence=2, depth=2, demo=2),
    ]
    result = aggregate(authors, list(DEFAULT_WEIGHTS), 7.0, 5.0)
    bloat_warnings = [w for w in result["warnings"] if "размывается" in w["message"]]
    check("exactly 30% OUTLIER → no bloat warning (strict >)",
          len(bloat_warnings) == 0)

    # 0 OUTLIER — no bloat warning
    authors = [
        make_author(id="h1", style=8, focus=8, pace=8,
                    independence=8, depth=8, demo=8),
        make_author(id="m1", style=6, focus=6, pace=6,
                    independence=6, depth=6, demo=6),
    ]
    result = aggregate(authors, list(DEFAULT_WEIGHTS), 7.0, 5.0)
    bloat_warnings = [w for w in result["warnings"] if "размывается" in w["message"]]
    check("0 OUTLIER → no bloat warning", len(bloat_warnings) == 0)


# ─── 15. subprocess: medium_high_borderline и weighted_contributions ─────

def test_subprocess_v07_features():
    print("\n[15] subprocess v0.7: weighted_contributions, extended, CLI borderline")

    payload = {
        "authors": [
            make_author(id="h1", style=8, focus=8, pace=8,
                        independence=8, depth=8, demo=8),
            make_author(id="m_high", style=7, focus=7, pace=6,
                        independence=6, depth=7, demo=5),  # MEDIUM 6.55
            make_author(id="m_low", style=5, focus=5, pace=5,
                        independence=5, depth=5, demo=5),  # MEDIUM 5.0
        ]
    }
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    check("subprocess v0.7 exit 0", result.returncode == 0)
    output = json.loads(result.stdout)
    check("output has reading_list_extended",
          "reading_list_extended" in output)
    check("subprocess: m_high in extended",
          "m_high" in output["reading_list_extended"])
    check("subprocess: m_low NOT in extended",
          "m_low" not in output["reading_list_extended"])
    check("output: thresholds_used has medium_high_borderline=6.5",
          output["thresholds_used"]["medium_high_borderline"] == 6.5)

    # weighted_contributions присутствует
    h1 = next(a for a in output["scored_authors"] if a["id"] == "h1")
    check("scored_author has weighted_contributions",
          "weighted_contributions" in h1)
    check("h1 wc.style = 2.0", approx(h1["weighted_contributions"]["style"], 2.0))

    # CLI --medium-high-borderline override
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--medium-high-borderline", "5.0"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    check("CLI --medium-high-borderline 5.0 exit 0", result.returncode == 0)
    output = json.loads(result.stdout)
    check("CLI borderline=5.0: m_low входит в extended",
          "m_low" in output["reading_list_extended"])
    check("CLI borderline=5.0: thresholds_used updated",
          output["thresholds_used"]["medium_high_borderline"] == 5.0)

    # Кастомные thresholds: high=6, medium=4. Default mh = 4 + (6-4)*0.75 = 5.5
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--thresholds", "6.0,4.0"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    check("custom thresholds (6,4) exit 0", result.returncode == 0)
    output = json.loads(result.stdout)
    check("auto-computed mh_borderline = 5.5 (для high=6, medium=4)",
          approx(output["thresholds_used"]["medium_high_borderline"], 5.5))

    # Invalid borderline > high
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--medium-high-borderline", "8.0"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    check("invalid borderline > high → exit 2", result.returncode == 2)


# ─── main ────────────────────────────────────────────────────────────────

def test_archetype_weights():
    print("\n[18] archetype weights")

    # Все 4 архетипа существуют и сумма каждого = 100.
    for arch, weights in ARCHETYPE_WEIGHTS.items():
        check(f"archetype {arch}: 6 весов", len(weights) == 6)
        check(f"archetype {arch}: sum=100", approx(sum(weights), 100.0),
              f"got {sum(weights)}")

    # resolve_weights_from_archetype возвращает копию.
    independent = resolve_weights_from_archetype("самостоятельные")
    check("resolve самостоятельные: тип list", isinstance(independent, list))
    check("resolve самостоятельные: 25/25/15/10/15/10",
          independent == [25.0, 25.0, 15.0, 10.0, 15.0, 10.0])
    # Не возвращает ссылку на внутренний словарь.
    independent.append(999)
    check("resolve возвращает копию (не ссылку)",
          ARCHETYPE_WEIGHTS["самостоятельные"] != independent)

    # семья / родители / люкс — корректные значения
    family = resolve_weights_from_archetype("семья_с_детьми")
    check("семья_с_детьми: возраст=25",
          family == [20.0, 20.0, 25.0, 5.0, 5.0, 25.0])

    adults = resolve_weights_from_archetype("взрослые_50_плюс")
    check("взрослые_50_плюс: возраст=35",
          adults == [15.0, 15.0, 25.0, 5.0, 5.0, 35.0])

    # Legacy-алиас: старое имя `родители_60_плюс` резолвится в `взрослые_50_плюс`.
    legacy = resolve_weights_from_archetype("родители_60_плюс")
    check("legacy родители_60_плюс → взрослые_50_плюс веса",
          legacy == [15.0, 15.0, 25.0, 5.0, 5.0, 35.0])
    # И старого ключа в каноническом словаре больше нет.
    check("родители_60_плюс убран из ARCHETYPE_WEIGHTS",
          "родители_60_плюс" not in ARCHETYPE_WEIGHTS)

    # Переименование: `независимые_соло_пара` — legacy-алиас `самостоятельные`.
    check("независимые_соло_пара убран из ARCHETYPE_WEIGHTS",
          "независимые_соло_пара" not in ARCHETYPE_WEIGHTS)
    check("алиас независимые_соло_пара → самостоятельные",
          ARCHETYPE_ALIASES.get("независимые_соло_пара") == "самостоятельные")
    check("самостоятельные резолвится напрямую: 25/25/15/10/15/10",
          resolve_weights_from_archetype("самостоятельные")
          == [25.0, 25.0, 15.0, 10.0, 15.0, 10.0])
    check("legacy независимые_соло_пара → те же веса 25/25/15/10/15/10",
          resolve_weights_from_archetype("независимые_соло_пара")
          == [25.0, 25.0, 15.0, 10.0, 15.0, 10.0])
    check("самостоятельные == DEFAULT_WEIGHTS",
          ARCHETYPE_WEIGHTS["самостоятельные"] == list(DEFAULT_WEIGHTS))
    check("canonical_archetype: legacy → канон",
          canonical_archetype("независимые_соло_пара") == "самостоятельные")
    check("canonical_archetype: канон остаётся каноном",
          canonical_archetype("самостоятельные") == "самостоятельные")
    check("canonical_archetype: None → None", canonical_archetype(None) is None)

    luxury = resolve_weights_from_archetype("люкс")
    check("люкс: стиль=30",
          luxury == [30.0, 20.0, 15.0, 5.0, 10.0, 20.0])

    # None → None
    check("resolve None → None",
          resolve_weights_from_archetype(None) is None)

    # Неизвестный архетип → ValueError
    try:
        resolve_weights_from_archetype("backpacker")
        check("неизвестный архетип → ValueError", False)
    except ValueError:
        check("неизвестный архетип → ValueError", True)


def test_override_weights():
    print("\n[19] similarity_weights_override")

    # Корректный override
    weights = resolve_override_weights({
        "стиль": 30, "фокус": 25, "темп": 15,
        "независимость": 5, "non_touristy": 15, "возраст_состав": 10,
    })
    check("override 30/25/15/5/15/10", weights == [30.0, 25.0, 15.0, 5.0, 15.0, 10.0])

    # None → None
    check("override None → None", resolve_override_weights(None) is None)

    # Неполный override → ValueError
    try:
        resolve_override_weights({"стиль": 100})
        check("неполный override → ValueError", False)
    except ValueError:
        check("неполный override → ValueError", True)

    # Неизвестные ключи → ValueError
    try:
        resolve_override_weights({
            "стиль": 30, "фокус": 25, "темп": 15,
            "независимость": 5, "non_touristy": 15, "возраст_состав": 10,
            "лишнее_поле": 0,
        })
        check("неизвестный ключ → ValueError", False)
    except ValueError:
        check("неизвестный ключ → ValueError", True)

    # Сумма != 100 → ValueError
    try:
        resolve_override_weights({
            "стиль": 20, "фокус": 25, "темп": 15,
            "независимость": 5, "non_touristy": 15, "возраст_состав": 10,
        })
        check("сумма != 100 → ValueError", False)
    except ValueError:
        check("сумма != 100 → ValueError", True)

    # Не объект → ValueError
    try:
        resolve_override_weights([30, 25, 15, 5, 15, 10])
        check("override list (не dict) → ValueError", False)
    except ValueError:
        check("override list (не dict) → ValueError", True)


def test_archetype_subprocess():
    print("\n[20] subprocess: archetype резолв и приоритеты")

    payload = {
        "authors": [
            make_author(id="h1", style=8, focus=8, pace=8,
                        independence=8, depth=8, demo=8),
        ],
    }

    # 1. Default (нет архетипа, нет весов)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    out = json.loads(result.stdout)
    check("default weights_source", out["weights_source"] == "default")
    check("default archetype_used = None", out["archetype_used"] is None)
    check("default weights_used = DEFAULT", out["weights_used"] == list(DEFAULT_WEIGHTS))

    # 2. CLI --archetype
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--archetype", "семья_с_детьми"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    out = json.loads(result.stdout)
    check("--archetype exit 0", result.returncode == 0)
    check("--archetype weights_source", out["weights_source"] == "cli_archetype")
    check("--archetype archetype_used", out["archetype_used"] == "семья_с_детьми")
    check("--archetype weights_used = family",
          out["weights_used"] == [20.0, 20.0, 25.0, 5.0, 5.0, 25.0])

    # 3. payload.группа_архетип
    payload_with_arch = dict(payload, **{"группа_архетип": "родители_60_плюс"})
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload_with_arch),
        capture_output=True,
        text=True,
    )
    out = json.loads(result.stdout)
    check("payload архетип weights_source", out["weights_source"] == "archetype")
    # archetype_used — всегда каноническое имя (алиас уже резолвлен)
    check("payload архетип archetype_used", out["archetype_used"] == "взрослые_50_плюс")
    check("payload архетип weights_used = parents",
          out["weights_used"] == [15.0, 15.0, 25.0, 5.0, 5.0, 35.0])

    # 3a. payload с legacy `независимые_соло_пара` → веса те же, archetype_used канонический
    payload_legacy = dict(payload, **{"группа_архетип": "независимые_соло_пара"})
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload_legacy),
        capture_output=True,
        text=True,
    )
    out = json.loads(result.stdout)
    check("legacy payload: exit 0", result.returncode == 0, result.stderr)
    check("legacy payload: weights_source = archetype",
          out["weights_source"] == "archetype")
    check("legacy payload: weights_used = 25/25/15/10/15/10",
          out["weights_used"] == [25.0, 25.0, 15.0, 10.0, 15.0, 10.0])
    check("legacy payload: archetype_used = самостоятельные",
          out["archetype_used"] == "самостоятельные")

    # 3b. payload с каноническим `самостоятельные` резолвится напрямую
    payload_canon = dict(payload, **{"группа_архетип": "самостоятельные"})
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload_canon),
        capture_output=True,
        text=True,
    )
    out = json.loads(result.stdout)
    check("canon payload: exit 0", result.returncode == 0, result.stderr)
    check("canon payload: weights_source = archetype",
          out["weights_source"] == "archetype")
    check("canon payload: weights_used = 25/25/15/10/15/10",
          out["weights_used"] == [25.0, 25.0, 15.0, 10.0, 15.0, 10.0])
    check("canon payload: archetype_used = самостоятельные",
          out["archetype_used"] == "самостоятельные")

    # 3c. CLI --archetype: и канон, и legacy-алиас; выдаётся канон
    for cli_value in ("самостоятельные", "независимые_соло_пара"):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--archetype", cli_value],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
        )
        out = json.loads(result.stdout) if result.returncode == 0 else {}
        check(f"--archetype {cli_value}: exit 0", result.returncode == 0, result.stderr)
        check(f"--archetype {cli_value}: archetype_used = самостоятельные",
              out.get("archetype_used") == "самостоятельные")
        check(f"--archetype {cli_value}: weights 25/25/15/10/15/10",
              out.get("weights_used") == [25.0, 25.0, 15.0, 10.0, 15.0, 10.0])

    # 3d. legacy + override: веса из override, archetype_used канонический
    payload_legacy_override = dict(payload_legacy, **{
        "similarity_weights_override": {
            "стиль": 30, "фокус": 25, "темп": 15,
            "независимость": 5, "non_touristy": 15, "возраст_состав": 10,
        },
    })
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload_legacy_override),
        capture_output=True,
        text=True,
    )
    out = json.loads(result.stdout)
    check("legacy + override: weights_source = override",
          out["weights_source"] == "override")
    check("legacy + override: archetype_used = самостоятельные",
          out["archetype_used"] == "самостоятельные")

    # 4. CLI --weights перебивает архетип
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--archetype", "семья_с_детьми",
         "--weights", "10,10,10,10,10,50"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    out = json.loads(result.stdout)
    check("--weights перебивает --archetype",
          out["weights_source"] == "cli_weights")
    check("--weights перебил архетип в weights_used",
          out["weights_used"] == [10.0, 10.0, 10.0, 10.0, 10.0, 50.0])

    # 5. similarity_weights_override в payload
    payload_override = dict(payload, **{
        "группа_архетип": "люкс",
        "similarity_weights_override": {
            "стиль": 40, "фокус": 20, "темп": 10,
            "независимость": 5, "non_touristy": 10, "возраст_состав": 15,
        },
    })
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload_override),
        capture_output=True,
        text=True,
    )
    out = json.loads(result.stdout)
    check("payload override weights_source", out["weights_source"] == "override")
    check("payload override weights_used custom",
          out["weights_used"] == [40.0, 20.0, 10.0, 5.0, 10.0, 15.0])
    # archetype_used всё ещё фиксируется для traceability
    check("payload override + архетип: archetype_used сохранён",
          out["archetype_used"] == "люкс")

    # 6. Неизвестный архетип в payload → exit 2
    bad_payload = dict(payload, **{"группа_архетип": "backpacker"})
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(bad_payload),
        capture_output=True,
        text=True,
    )
    check("неизвестный архетип в payload → exit 2", result.returncode == 2)

    # 7. Override с суммой != 100 → exit 2
    bad_override = dict(payload, **{
        "similarity_weights_override": {
            "стиль": 50, "фокус": 25, "темп": 15,
            "независимость": 5, "non_touristy": 15, "возраст_состав": 10,
        },
    })
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(bad_override),
        capture_output=True,
        text=True,
    )
    check("override сумма != 100 → exit 2", result.returncode == 2)


def test_taxonomy_display_and_bilingual():
    """Фаза 1 русификации: display-поля category_label/severity_label +
    приём русских/алиасных имён компонентов на входе (контракт EN не меняется)."""
    print("\n[i18n] display-поля + двуязычный вход")

    # category_label рядом с EN category.
    hi = score(make_author(style=9, focus=9, pace=9, independence=9, depth=9, demo=9))
    check("score: category_label == taxonomy(author_category, category)",
          hi["category_label"] == taxonomy.label("author_category", hi["category"]))
    check("score: EN-поле category не тронуто",
          hi["category"] in {"HIGH", "MEDIUM", "LOW", "OUTLIER", "UNSCORED"})

    # Русские/алиасные имена компонентов на входе → тот же результат.
    a_en = make_author(style=8, focus=7, pace=6, independence=5, depth=9, demo=4)
    a_ru = dict(a_en, components={
        "стиль": 8, "фокус": 7, "темп": 6,
        "самостоятельность": 5, "глубина": 9, "демография": 4,
    })
    r_en, r_ru = score(a_en), score(a_ru)
    check("RU-компоненты на входе → тот же total_score",
          r_en["total_score"] == r_ru["total_score"],
          f"{r_en['total_score']} vs {r_ru['total_score']}")
    check("RU-компоненты → та же category", r_en["category"] == r_ru["category"])

    # severity_label в warnings.
    warns = build_warnings(
        {"high": 1, "medium": 2, "low": 3, "outlier": 0, "unscored": 0, "total": 6},
        [score(make_author())],
    )
    check("warnings непусты (узкая HIGH-выборка)", len(warns) > 0)
    check("каждый warning имеет severity_label == taxonomy(severity)",
          all(w.get("severity_label") == taxonomy.label("warning_severity", w["severity"])
              for w in warns))


def main():
    test_taxonomy_display_and_bilingual()
    test_normalize_weights()
    test_components_known_and_confidence()
    test_total_score()
    test_categorization()
    test_low_confidence_flag()
    test_reading_list()
    test_user_added()
    test_aggregate_distribution()
    test_warnings()
    test_confidence_breakdown()
    test_custom_weights_and_thresholds()
    test_subprocess_end_to_end()
    test_weighted_contributions()
    test_reading_list_extended()
    test_outlier_bloat_warning()
    test_subprocess_v07_features()
    test_archetype_weights()
    test_override_weights()
    test_archetype_subprocess()

    print(f"\n{'=' * 50}")
    print(f"Всего проверок: {checks_run}, провалов: {checks_failed}")
    if checks_failed:
        print("FAIL")
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
