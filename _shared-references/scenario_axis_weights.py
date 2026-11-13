#!/usr/bin/env python3
"""
scenario_axis_weights.py — канон перевода убеждений ПО ОСЯМ в веса 4 сценариев
Shell-матрицы, в том числе по горизонтам.

Зачем. Назвать вероятность каждого из четырёх сценариев трудно, а ответить на два
вопроса по осям («продолжится ли война к этому сроку?», «удержатся ли санкции?») —
легко. Совместные веса выводятся из осевых по решению D6 (ρ = 0, независимость осей;
ρ ≠ 0 задаётся явно). По умолчанию НИКАКОГО вывода не происходит: Pure Shell D1 —
0.25 каждому, и это остаётся, пока осевые убеждения не заданы явно.

ПОЛЯРНОСТЬ — источник тихих ошибок, поэтому зафиксирована явно.
Канон §17 F4 (`_shared-references/events-yaml-spec.md`): `stress_pole: A`,
`detente_pole: D`. Проверено на живой матрице `scenario-geopolitics-ru-west-2026-07-01`:

    axes_meta.axis_x (conflict_intensity):  low = «перемирие/заморозка»,
                                            high = «война продолжается»
    axes_meta.axis_y (sanctions_intensity): low = «фрагментация/снятие»,
                                            high = «единый/ужесточённый»

    A «Затяжная осада»                    = война + ужесточение  = (high, high)
    B «Война на расколотом фронте»        = война + фрагментация = (high, low)
    C «Замороженный конфликт под давлением» = перемирие + holding = (low, high)
    D «Большая сделка и разрядка»         = перемирие + снятие   = (low, low)

Перепутанная полярность НЕ падает и НЕ выглядит подозрительно: она просто
зеркалит веса — вес войны уезжает на разрядку. Поэтому маппинг здесь задаётся
данными, а не комментарием, и проверяется тестом против живой матрицы.

Единицы осевого убеждения: `ev_x` = P(ось X в HIGH-полюсе), 0..1. Скаляр уже живёт
в матрицах как `axes_meta.<ось>.quantitative_anchor.modal_expected_value`
(в матрице 07-01: 0.6 по конфликту, 0.55 по санкциям) — он только читается.
Расширение `modal_expected_value_by_horizon` — НОВОЕ поле (в живой библиотеке
пока 0 вхождений), введено спекой `scenario-yaml-spec.md` 2026-08-04.

stdlib only.
"""
from __future__ import annotations

import math
import re
from typing import Any

# Полюсы квадранта: (полюс оси X, полюс оси Y).
CANON_QUADRANT_MAPPING: dict[str, tuple[str, str]] = {
    "A": ("high", "high"),
    "B": ("high", "low"),
    "C": ("low", "high"),
    "D": ("low", "low"),
}

EQUAL_WEIGHTS: dict[str, float] = {k: 0.25 for k in CANON_QUADRANT_MAPPING}

# ⚠️ Канон верен ДЛЯ geopolitics-ru-west, но НЕ универсален. Проверено на живой
# библиотеке 2026-08-04: у `scenario-usd-rub-sept-2026` и `scenario-ai-capex-2026`
# полярность зеркальная (A — благополучный мир), у `scenario-brent-dec-2026` стресс
# вообще в C. Применить канон к такой матрице значит отдать вес стрессового мира
# благополучному — молча и правдоподобно. Поэтому матрица обязана ОБЪЯВИТЬ
# полярность блоком `matrix.polarity`, а не полагаться на умолчание.
POLARITY_KEYS = ("stress_pole", "detente_pole")

_H_KEY_RE = re.compile(r"^h(\d+)$")
_ANCHOR_PATH = ("quantitative_anchor", "modal_expected_value")
_ANCHOR_BY_HORIZON = "modal_expected_value_by_horizon"


class AxisWeightsError(ValueError):
    """Осевые убеждения не дают допустимого совместного распределения."""


def _p_high_low(ev: float, axis: str) -> tuple[float, float]:
    if not isinstance(ev, (int, float)) or isinstance(ev, bool) or not math.isfinite(ev):
        raise AxisWeightsError(f"{axis}: ожидалось число 0..1, получено {ev!r}")
    ev = float(ev)
    if not 0.0 <= ev <= 1.0:
        raise AxisWeightsError(f"{axis} = {ev:g} вне [0,1]: это вероятность HIGH-полюса")
    return ev, 1.0 - ev


def _horizon_months(h: Any) -> int:
    """
    Горизонт в месяцах из int (6) или строки-ключа («h6»). В пайплайне горизонты
    ходят обеими формами; `f"h{h}"` на строке молча давал ключ «hh6», а якоря по
    горизонтам после этого не находились и рапортовались как «скаляр оси».
    """
    if isinstance(h, bool):
        raise AxisWeightsError(f"горизонт {h!r} — не число и не ключ вида hNN")
    if isinstance(h, int):
        return h
    m = _H_KEY_RE.match(str(h).strip())
    if not m:
        raise AxisWeightsError(f"горизонт {h!r} — не число и не ключ вида hNN")
    return int(m.group(1))


def quadrant_probabilities(
    ev_x: float, ev_y: float, rho: float = 0.0
) -> dict[tuple[str, str], float]:
    """
    Вероятности четырёх квадрантов (полюс X, полюс Y). Ключи — полюсы, НЕ id
    сценариев: привязка к id — отдельный, явный шаг (`weights_from_axes`).

    ρ — корреляция осей (D6: default 0). Совместное bivariate-Bernoulli
    распределение существует не при любых (ev_x, ev_y, ρ); при выходе за границу
    поднимается AxisWeightsError, а не молча обрезаются веса.
    """
    if not isinstance(rho, (int, float)) or isinstance(rho, bool) or not math.isfinite(rho):
        raise AxisWeightsError(f"rho: ожидалось число −1..1, получено {rho!r}")
    if not -1.0 <= float(rho) <= 1.0:
        raise AxisWeightsError(f"rho = {rho:g} вне [−1,1]")
    x_hi, x_lo = _p_high_low(ev_x, "ev_x")
    y_hi, y_lo = _p_high_low(ev_y, "ev_y")
    cov = float(rho) * math.sqrt(x_hi * x_lo * y_hi * y_lo)
    quad = {
        ("high", "high"): x_hi * y_hi + cov,
        ("low", "low"): x_lo * y_lo + cov,
        ("high", "low"): x_hi * y_lo - cov,
        ("low", "high"): x_lo * y_hi - cov,
    }
    tol = 1e-9
    for k, v in list(quad.items()):
        if -tol < v < 0:
            quad[k] = 0.0
        elif 1 < v < 1 + tol:
            quad[k] = 1.0
    bad = {k: round(v, 6) for k, v in quad.items() if v < 0 or v > 1}
    if bad:
        raise AxisWeightsError(
            f"совместное распределение не существует при ev_x={ev_x}, ev_y={ev_y}, "
            f"ρ={rho}: невалидные веса {bad}. Уменьши |ρ| или сдвинь ev от 0/1."
        )
    return quad


def weights_from_axes(
    ev_x: float,
    ev_y: float,
    rho: float = 0.0,
    mapping: dict[str, tuple[str, str]] | None = None,
) -> dict[str, float]:
    """
    Веса сценариев из осевых убеждений. `mapping` — {id: (полюс X, полюс Y)};
    None → канон F4 (A — стресс-полюс, D — детант-полюс).
    """
    m = mapping or CANON_QUADRANT_MAPPING
    quad = quadrant_probabilities(ev_x, ev_y, rho)
    if sorted(m.values()) != sorted(quad):
        raise AxisWeightsError(
            f"mapping должен покрывать все четыре квадранта ровно по разу, получено "
            f"{sorted(m.values())}"
        )
    weights = {sid: quad[poles] for sid, poles in m.items()}
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-6:
        raise AxisWeightsError(f"сумма весов {total} != 1")
    return {k: round(v, 6) for k, v in weights.items()}


def _read_anchor(axis_meta: Any) -> tuple[float | None, dict[int, float]]:
    """(скаляр, {месяцы: значение}) из quantitative_anchor оси. Отсутствие → (None, {})."""
    if not isinstance(axis_meta, dict):
        return None, {}
    anchor = axis_meta.get(_ANCHOR_PATH[0])
    if not isinstance(anchor, dict):
        return None, {}
    scalar = anchor.get(_ANCHOR_PATH[1])
    scalar = float(scalar) if isinstance(scalar, (int, float)) and not isinstance(scalar, bool) else None
    by_h: dict[int, float] = {}
    raw = anchor.get(_ANCHOR_BY_HORIZON)
    if isinstance(raw, dict):
        for k, v in raw.items():
            mt = _H_KEY_RE.match(str(k))
            if mt and isinstance(v, (int, float)) and not isinstance(v, bool):
                by_h[int(mt.group(1))] = float(v)
    return scalar, by_h


def mapping_from_matrix(matrix_doc: Any) -> dict[str, tuple[str, str]] | None:
    """
    Маппинг квадрантов на id из ОБЪЯВЛЕННОЙ полярности матрицы
    (`matrix.polarity: {stress_pole: A, detente_pole: D}`). Нет блока → None:
    вызывающий обязан решить, применять ли канон, а не получить его молча.

    Стресс-полюс — обе оси HIGH, детант — обе LOW. Оставшиеся два id
    распределяются по смешанным квадрантам в алфавитном порядке; если их больше
    двух или полюсы совпадают — None (матрица нестандартная, нужен явный mapping).
    """
    if not isinstance(matrix_doc, dict):
        return None
    matrix = matrix_doc.get("matrix")
    matrix = matrix if isinstance(matrix, dict) else {}
    # `polarity` и `scenario_triggers` в живых файлах лежат по-разному: триггеры —
    # на верхнем уровне, а спека §17 F4 адресует `matrix.polarity`. Смотрим оба
    # места: угадывать один путь — способ молча получить None и уехать на канон.
    pol = matrix.get("polarity")
    if not isinstance(pol, dict):
        pol = matrix_doc.get("polarity")
    if not isinstance(pol, dict):
        return None
    stress, detente = pol.get(POLARITY_KEYS[0]), pol.get(POLARITY_KEYS[1])
    if not isinstance(stress, str) or not isinstance(detente, str) or stress == detente:
        return None
    triggers = matrix.get("scenario_triggers")
    if not isinstance(triggers, list):
        triggers = matrix_doc.get("scenario_triggers")
    if not isinstance(triggers, list):
        return None          # состав сценариев неизвестен — маппинг не выводим
    ids = [t.get("scenario_id") for t in triggers if isinstance(t, dict)]
    ids = [i for i in ids if isinstance(i, str)]
    rest = sorted(i for i in ids if i not in (stress, detente))
    if len(rest) != 2:
        return None
    return {stress: ("high", "high"), detente: ("low", "low"),
            rest[0]: ("high", "low"), rest[1]: ("low", "high")}


def axis_beliefs_from_matrix(matrix_doc: Any) -> dict[str, Any]:
    """
    Достаёт осевые убеждения из scenario YAML.

    Читает `downstream_sensitivity_hints.axes_meta.{axis_x,axis_y}.
    quantitative_anchor.modal_expected_value` (скаляр, уже существует в живых
    матрицах) и опциональное расширение `modal_expected_value_by_horizon`
    вида {h6: 0.85, h12: 0.65, h24: 0.40}.

    Возвращает {"x": {...}, "y": {...}, "mapping": …|None, "polarity_declared": bool}.
    `mapping is None` означает «полярность не объявлена» — канон применять только
    осознанно, см. предупреждение у POLARITY_KEYS.
    """
    hints = (matrix_doc or {}).get("downstream_sensitivity_hints") if isinstance(matrix_doc, dict) else None
    axes = (hints or {}).get("axes_meta") if isinstance(hints, dict) else None
    axes = axes if isinstance(axes, dict) else {}
    out: dict[str, Any] = {}
    for key, axis_key in (("x", "axis_x"), ("y", "axis_y")):
        scalar, by_h = _read_anchor(axes.get(axis_key))
        out[key] = {"scalar": scalar, "by_horizon": by_h}
    mapping = mapping_from_matrix(matrix_doc)
    out["mapping"] = mapping
    out["polarity_declared"] = mapping is not None
    return out


def weights_by_horizon(
    beliefs: dict[str, Any],
    horizons: list[int],
    rho: float = 0.0,
    mapping: dict[str, tuple[str, str]] | None = None,
) -> tuple[dict[str, dict[str, float]], list[str]]:
    """
    {hNN: {scenario_id: вес}} по горизонтам + список пояснений.

    Для каждого горизонта берётся осевое убеждение этого горизонта; если его нет —
    скаляр оси; если нет и его — горизонт получает равные веса (Pure Shell D1) и
    об этом сообщается. Никакой интерполяции между горизонтами здесь НЕ делается:
    убеждение на срок — суждение, и выдумывать промежуточные значения за
    пользователя нельзя.
    """
    notes: list[str] = []
    out: dict[str, dict[str, float]] = {}
    bx = (beliefs or {}).get("x") or {}
    by = (beliefs or {}).get("y") or {}
    for h_raw in horizons:
        h = _horizon_months(h_raw)
        hk = f"h{h}"
        ev_x = (bx.get("by_horizon") or {}).get(h, bx.get("scalar"))
        ev_y = (by.get("by_horizon") or {}).get(h, by.get("scalar"))
        if ev_x is None or ev_y is None:
            ids = list((mapping or CANON_QUADRANT_MAPPING).keys())
            out[hk] = {sid: round(1.0 / len(ids), 6) for sid in ids}
            notes.append(
                f"{hk}: осевое убеждение не задано ({'X' if ev_x is None else 'Y'}) → "
                f"равные веса 0.25 (Pure Shell D1)"
            )
            continue
        out[hk] = weights_from_axes(ev_x, ev_y, rho, mapping)
        src_x = "по горизонту" if h in (bx.get("by_horizon") or {}) else "скаляр оси"
        src_y = "по горизонту" if h in (by.get("by_horizon") or {}) else "скаляр оси"
        notes.append(f"{hk}: ev_x={ev_x:g} ({src_x}), ev_y={ev_y:g} ({src_y}), ρ={rho:g}")
    return out, notes
