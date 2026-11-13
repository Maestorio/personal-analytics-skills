#!/usr/bin/env python3
"""
Регрессионные тесты для retro_metrics.py.

Запуск из корня репозитория:
    python3 skills/retrospective-forecast-audit/tests/test_retro_metrics.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "skills" / "retrospective-forecast-audit" / "scripts" / "retro_metrics.py"

sys.path.insert(0, str(SCRIPT.parent))
from retro_metrics import compute, compute_metrics, compute_value  # noqa: E402


checks_run = 0
checks_failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global checks_run, checks_failed
    checks_run += 1
    status = "OK" if condition else "FAIL"
    if not condition:
        checks_failed += 1
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


# --------------------------------------------------------------------------
# Шаг 6 — матрица ценностей
# --------------------------------------------------------------------------

def test_value_alpha():
    """+2 + Contrarian + L0 → +3 (⭐ альфа)."""
    print("test_value_alpha")
    v = compute_value({"scale_1": "+2", "scale_2": "Contrarian", "scale_3": "L0"})
    check("value = +3", v["value"] == 3, f"got {v['value']}")
    check("marker = ⭐", v["marker"] == "⭐", f"got {v['marker']}")
    check("counted = True", v["counted"] is True)


def test_value_off_market_correct():
    """+2 + Off-market + L0 → +2."""
    print("test_value_off_market_correct")
    v = compute_value({"scale_1": "+2", "scale_2": "Off-market", "scale_3": "L0"})
    check("value = +2", v["value"] == 2)
    check("без markers", v["marker"] is None)


def test_value_repackaging():
    """+2 + Consensus + L0 → +1 (ретрансляция)."""
    print("test_value_repackaging")
    v = compute_value({"scale_1": "+2", "scale_2": "Consensus", "scale_3": "L0"})
    check("value = +1", v["value"] == 1)


def test_value_calibration_error():
    """+1 + L-C → -1 (ошибка калибровки)."""
    print("test_value_calibration_error")
    v = compute_value({"scale_1": "+1", "scale_2": "Contrarian", "scale_3": "L-C"})
    check("value = -1", v["value"] == -1)
    v = compute_value({"scale_1": "0", "scale_2": "Consensus", "scale_3": "L-C"})
    check("0 + L-C → -1", v["value"] == -1)


def test_value_crowd_error():
    """-2 + Consensus + L-A → 0 🌍."""
    print("test_value_crowd_error")
    v = compute_value({"scale_1": "-2", "scale_2": "Consensus", "scale_3": "L-A"})
    check("value = 0", v["value"] == 0)
    check("marker = 🌍", v["marker"] == "🌍")


def test_value_solo_miss_contrarian():
    """-2 + Contrarian + L-A → -2 (👤)."""
    print("test_value_solo_miss_contrarian")
    v = compute_value({"scale_1": "-2", "scale_2": "Contrarian", "scale_3": "L-A"})
    check("value = -2", v["value"] == -2)
    check("marker = 👤", v["marker"] == "👤")


def test_value_solo_miss_off_market():
    """-2 + Off-market + L-B → -2 (👤)."""
    print("test_value_solo_miss_off_market")
    v = compute_value({"scale_1": "-2", "scale_2": "Off-market", "scale_3": "L-B"})
    check("value = -2", v["value"] == -2)
    check("marker = 👤", v["marker"] == "👤")


def test_value_lr_penalty():
    """L-R даёт дополнительный -1, marker ⚠️."""
    print("test_value_lr_penalty")
    # Базовая +1 + L-R → 0
    v = compute_value({"scale_1": "+2", "scale_2": "Consensus", "scale_3": "L0",
                       "l_r": True})
    check("base +1 + L-R → 0", v["value"] == 0, f"got {v['value']}")
    check("marker содержит ⚠️", "⚠️" in (v["marker"] or ""))

    # альфа +3 + L-R → +2
    v = compute_value({"scale_1": "+2", "scale_2": "Contrarian", "scale_3": "L0",
                       "l_r": True})
    check("alpha +3 + L-R → +2", v["value"] == 2)
    check("marker содержит и ⭐ и ⚠️",
          "⭐" in (v["marker"] or "") and "⚠️" in (v["marker"] or ""))


def test_value_pending_not_counted():
    """⏳ pending не засчитывается."""
    print("test_value_pending_not_counted")
    v = compute_value({"scale_1": "pending", "scale_2": "Consensus", "scale_3": "L0"})
    check("counted = False", v["counted"] is False)
    check("value = None", v["value"] is None)


def test_value_force_majeure_not_counted():
    print("test_value_force_majeure_not_counted")
    v = compute_value({"scale_1": "force_majeure", "scale_2": "Contrarian", "scale_3": "L0"})
    check("counted = False", v["counted"] is False)


def test_value_unmapped_combination_falls_back():
    """Промежуточная комбинация — best-effort."""
    print("test_value_unmapped_combination_falls_back")
    v = compute_value({"scale_1": "+1", "scale_2": "Contrarian", "scale_3": "L0"})
    # +1 base + delta (Contrarian-L0 = +1) → +2
    check("+1 Contrarian L0 → +2 (best-effort)", v["value"] == 2,
          f"got {v['value']}")


def test_value_invalid_scales():
    print("test_value_invalid_scales")
    v = compute_value({"scale_1": "wrong", "scale_2": "Consensus", "scale_3": "L0"})
    check("invalid scale_1 → error", v.get("error") is True)


# --------------------------------------------------------------------------
# Шаг 7 — агрегаты
# --------------------------------------------------------------------------

def test_metrics_simple():
    """Простой набор: 1 alpha, 1 repackaging, 1 crowd error, 1 pending."""
    print("test_metrics_simple")
    theses = [
        {"id": 1, "scale_1": "+2", "scale_2": "Contrarian", "scale_3": "L0",
         "direction": "bullish", "block": "macro"},
        {"id": 2, "scale_1": "+2", "scale_2": "Consensus", "scale_3": "L0",
         "direction": "bullish", "block": "macro"},
        {"id": 3, "scale_1": "-2", "scale_2": "Consensus", "scale_3": "L-A",
         "direction": "bearish", "block": "macro"},
        {"id": 4, "scale_1": "pending", "scale_2": "Consensus", "scale_3": "L0"},
    ]
    res = compute({"theses": theses})
    m = res["metrics"]
    check("n_total = 4", m["n_total"] == 4)
    check("n_counted = 3", m["n_counted"] == 3)
    check("n_pending = 1", m["n_pending"] == 1)
    # hit_rate: 2 правильных (+2 +2) из 3 счётных
    check("hit_rate = 2/3", abs(m["hit_rate"] - 2/3) < 1e-3, f"got {m['hit_rate']}")
    # full_accuracy: 2 +2 из 3 → 2/3
    check("full_accuracy = 2/3", abs(m["full_accuracy"] - 2/3) < 1e-3)
    # alpha_generation: 1 contrarian, 1 верный → 1.0
    check("alpha_generation = 1.0", m["alpha_generation"] == 1.0)
    check("alpha_denominator = 1", m["alpha_denominator"] == 1)


def test_metrics_alpha_no_contrarian():
    """Если нет Contrarian тезисов, alpha_generation = 'n/p'."""
    print("test_metrics_alpha_no_contrarian")
    theses = [
        {"id": 1, "scale_1": "+2", "scale_2": "Consensus", "scale_3": "L0"},
        {"id": 2, "scale_1": "-2", "scale_2": "Consensus", "scale_3": "L-A"},
    ]
    res = compute({"theses": theses})
    check("alpha_generation = n/p", res["metrics"]["alpha_generation"] == "n/p")
    check("alpha_denominator = 0", res["metrics"]["alpha_denominator"] == 0)


def test_metrics_share_real_alpha():
    """share_real_alpha: value ∈ {+2, +3} / n_counted."""
    print("test_metrics_share_real_alpha")
    theses = [
        {"id": 1, "scale_1": "+2", "scale_2": "Contrarian", "scale_3": "L0"},  # +3
        {"id": 2, "scale_1": "+2", "scale_2": "Off-market", "scale_3": "L0"},  # +2
        {"id": 3, "scale_1": "+2", "scale_2": "Consensus", "scale_3": "L0"},   # +1
        {"id": 4, "scale_1": "-2", "scale_2": "Consensus", "scale_3": "L-A"},  # 0
    ]
    res = compute({"theses": theses})
    m = res["metrics"]
    # +3 и +2 = 2 из 4
    check("share_real_alpha = 0.5", m["share_real_alpha"] == 0.5,
          f"got {m['share_real_alpha']}")
    # +1 = 1 из 4
    check("share_repackaging = 0.25", m["share_repackaging"] == 0.25)


def test_metrics_crowd_vs_personal_errors():
    print("test_metrics_crowd_vs_personal_errors")
    theses = [
        {"id": 1, "scale_1": "-2", "scale_2": "Consensus", "scale_3": "L-A"},   # crowd
        {"id": 2, "scale_1": "-2", "scale_2": "Consensus", "scale_3": "L-A"},   # crowd
        {"id": 3, "scale_1": "-2", "scale_2": "Contrarian", "scale_3": "L-A"},  # personal
        {"id": 4, "scale_1": "-2", "scale_2": "Off-market", "scale_3": "L-B"},  # personal
        {"id": 5, "scale_1": "-1", "scale_2": "Contrarian", "scale_3": "L-C"},  # personal (Contrarian)
    ]
    res = compute({"theses": theses})
    m = res["metrics"]
    check("n_errors = 5", m["n_errors"] == 5)
    # crowd: 2 (Consensus + L-A)
    check("share_crowd = 2/5", abs(m["share_crowd_errors"] - 0.4) < 1e-3)
    # personal: 3 (1 contrarian L-A + 1 off-market L-B + 1 contrarian L-C)
    check("share_personal = 3/5", abs(m["share_personal_errors"] - 0.6) < 1e-3)


def test_metrics_bull_bear_symmetry():
    """Bullish bias detection (≥2:1)."""
    print("test_metrics_bull_bear_symmetry")
    theses = [
        {"scale_1": "+2", "scale_2": "Consensus", "scale_3": "L0", "direction": "bullish"},
        {"scale_1": "+2", "scale_2": "Consensus", "scale_3": "L0", "direction": "bullish"},
        {"scale_1": "+2", "scale_2": "Consensus", "scale_3": "L0", "direction": "bullish"},
        {"scale_1": "+2", "scale_2": "Consensus", "scale_3": "L0", "direction": "bearish"},
    ]
    res = compute({"theses": theses})
    bb = res["metrics"]["bull_bear_symmetry"]
    check("bullish = 3", bb["bullish"] == 3)
    check("bearish = 1", bb["bearish"] == 1)
    check("ratio = 3.0", bb["ratio"] == 3.0)
    check("skew = bullish_bias", bb["skew"] == "bullish_bias")


def test_metrics_error_clustering():
    """≥50% ошибок в одном блоке → is_systemic."""
    print("test_metrics_error_clustering")
    theses = [
        {"scale_1": "-2", "scale_2": "Consensus", "scale_3": "L-A", "block": "macro"},
        {"scale_1": "-2", "scale_2": "Consensus", "scale_3": "L-A", "block": "macro"},
        {"scale_1": "-2", "scale_2": "Consensus", "scale_3": "L-A", "block": "macro"},
        {"scale_1": "-2", "scale_2": "Consensus", "scale_3": "L-A", "block": "rates"},
    ]
    res = compute({"theses": theses})
    ec = res["metrics"]["error_clustering"]
    check("max_block = macro", ec["max_block"] == "macro")
    check("max_block_share = 0.75", ec["max_block_share"] == 0.75)
    check("is_systemic = True", ec["is_systemic"] is True)


def test_metrics_value_distribution():
    print("test_metrics_value_distribution")
    theses = [
        {"scale_1": "+2", "scale_2": "Contrarian", "scale_3": "L0"},   # +3
        {"scale_1": "+2", "scale_2": "Consensus", "scale_3": "L0"},    # +1
        {"scale_1": "+2", "scale_2": "Consensus", "scale_3": "L0"},    # +1
        {"scale_1": "-2", "scale_2": "Consensus", "scale_3": "L-A"},   # 0
        {"scale_1": "-2", "scale_2": "Contrarian", "scale_3": "L-B"},  # -2
    ]
    res = compute({"theses": theses})
    dist = res["metrics"]["value_distribution"]
    check("dist[+3] = 1", dist[3] == 1)
    check("dist[+1] = 2", dist[1] == 2)
    check("dist[0] = 1", dist[0] == 1)
    check("dist[-2] = 1", dist[-2] == 1)


def test_cli_stdin():
    print("test_cli_stdin")
    payload = {
        "theses": [
            {"id": 1, "scale_1": "+2", "scale_2": "Contrarian", "scale_3": "L0"}
        ]
    }
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload), capture_output=True, text=True, check=False,
    )
    check("exit code = 0", proc.returncode == 0, f"stderr: {proc.stderr}")
    out = json.loads(proc.stdout)
    check("CLI: первый verdict value=+3",
          out["verdicts"][0]["value"] == 3)


def main() -> int:
    print("=" * 60)
    print("retrospective-forecast-audit / retro_metrics.py")
    print("=" * 60)

    test_value_alpha()
    test_value_off_market_correct()
    test_value_repackaging()
    test_value_calibration_error()
    test_value_crowd_error()
    test_value_solo_miss_contrarian()
    test_value_solo_miss_off_market()
    test_value_lr_penalty()
    test_value_pending_not_counted()
    test_value_force_majeure_not_counted()
    test_value_unmapped_combination_falls_back()
    test_value_invalid_scales()
    test_metrics_simple()
    test_metrics_alpha_no_contrarian()
    test_metrics_share_real_alpha()
    test_metrics_crowd_vs_personal_errors()
    test_metrics_bull_bear_symmetry()
    test_metrics_error_clustering()
    test_metrics_value_distribution()
    test_cli_stdin()

    print("=" * 60)
    print(f"Итого: {checks_run - checks_failed}/{checks_run} проверок прошло")
    print("=" * 60)
    return 0 if checks_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
