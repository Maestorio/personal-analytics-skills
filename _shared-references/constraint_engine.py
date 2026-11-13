#!/usr/bin/env python3
"""
constraint_engine.py — общие детерминированные примитивы портфельного контура.

  - SLICE_* / slice_era / slice_form_errors — форма среза ограничений обзора недели
                                 `user_constraints[]` (schema.md §4.2): срез ПРОИЗВОДНЫЙ — строится из условий
                                 (модуль (а)) и плана владельца, в обзоре только копия с `as_of`; код его не
                                 читает как источник. Строит срез `reconcile_constraints.py` (советник),
                                 форму проверяет валидатор обзора save-to-library.
  - compute_verification_priority — derived-приоритет перепроверки (расширенное C5)
  - compute_fixed_point_target — gate-aware сайзинг покупок при частично замороженной
                                 акционной книге (docs/investment/gate-aware-sizing-spec.md)

Импортируется из:
  - ru-portfolio-advisor: reconcile_constraints.py (срез), gate_aware_sizing.py (неподвижная точка)
  - save-to-library/scripts/assemble_artifact.py (форма среза, verification_priority)

Логика НЕ дублируется в потребителях — все зовут эти функции.

Stdlib only.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codelists  # noqa: E402  — codelists.py/codelists.json рядом (в .skill — тоже в scripts/)


# ─────────────────────── срез ограничений обзора (schema.md §4.2) ───────────────────────

# Обзоры с recorded_at (или review_date, если его нет) не раньше этой даты несут срез новой формы;
# старые обзоры валидатор срезом не проверяет.
SLICE_SINCE = "2026-10-31"
# Источник записи среза: ровно одно из двух — id условия (модуль (а)) или поле плана владельца.
SLICE_PLAN_FIELDS = ("user_plan", "user_status")
SLICE_STATUSES = ("pending", "fired")
SLICE_FIELDS = ("derived", "as_of", "condition_id", "plan_field", "plan_value", "reason", "status", "until",
                "summary")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def slice_era(review: dict) -> bool:
    """True — обзор новой формы (дата записи не раньше SLICE_SINCE): срез обязан быть производным."""
    d = str((review or {}).get("recorded_at") or (review or {}).get("review_date") or "")[:10]
    return bool(_DATE_RE.match(d)) and d >= SLICE_SINCE


def is_derived(c) -> bool:
    """Запись среза новой формы (несёт `derived`); без него — устаревшая форма «ограничения обзора»."""
    return isinstance(c, dict) and "derived" in c


def slice_form_errors(constraints) -> list[str]:
    """Ошибки формы среза `user_constraints[]` — только записей новой формы (с `derived`).

    Запись: derived: true; as_of — дата YYYY-MM-DD; ровно одно из condition_id (непустая строка) или
    plan_field (∈ SLICE_PLAN_FIELDS); summary — непустая строка; reason — код кодлиста block_reason;
    status ∈ pending|fired; until — дата или null; plan_value — строка; прочие поля — ошибка.
    Пустой список = форма верна.
    """
    if not isinstance(constraints, list):
        return [f"user_constraints: ожидается список, получено {type(constraints).__name__}"]
    reasons = set(codelists.codes("block_reason"))
    errs: list[str] = []
    for i, c in enumerate(constraints):
        p = f"user_constraints[{i}]"
        if not isinstance(c, dict):
            errs.append(f"{p}: ожидается объект, получено {type(c).__name__}")
            continue
        if not is_derived(c):
            continue
        extra = sorted(set(c) - set(SLICE_FIELDS))
        if extra:
            errs.append(f"{p}: поля не из формы среза: {', '.join(extra)}")
        if c.get("derived") is not True:
            errs.append(f"{p}.derived: ожидается true, получено {c.get('derived')!r}")
        if not (isinstance(c.get("as_of"), str) and _DATE_RE.match(c["as_of"])):
            errs.append(f"{p}.as_of: ожидается дата YYYY-MM-DD, получено {c.get('as_of')!r}")
        cid, pf = c.get("condition_id"), c.get("plan_field")
        has_c = isinstance(cid, str) and bool(cid.strip())
        has_p = pf in SLICE_PLAN_FIELDS
        if has_c == has_p:
            errs.append(f"{p}: нужно ровно одно — condition_id (id условия) или plan_field "
                        f"({' | '.join(SLICE_PLAN_FIELDS)}); получено condition_id={cid!r}, plan_field={pf!r}")
        if not (isinstance(c.get("summary"), str) and c["summary"].strip()):
            errs.append(f"{p}.summary: ожидается непустая строка")
        if "reason" in c and c["reason"] not in reasons:
            errs.append(f"{p}.reason: нет в кодлисте block_reason: {c['reason']!r}")
        if "status" in c and c["status"] not in SLICE_STATUSES:
            errs.append(f"{p}.status: ожидается {' | '.join(SLICE_STATUSES)}, получено {c['status']!r}")
        if c.get("until") is not None and not (isinstance(c["until"], str) and _DATE_RE.match(c["until"])):
            errs.append(f"{p}.until: ожидается дата YYYY-MM-DD или null, получено {c['until']!r}")
        if "plan_value" in c and not isinstance(c["plan_value"], str):
            errs.append(f"{p}.plan_value: ожидается строка (слово плана)")
    return errs


# ─────────────────────── verification_priority (расширенное C5) ───────────────────────

# Вердикты-сделки: направление up/down (maps.verdict_direction), без legacy-кодов.
ACTIONABLE_VERDICTS = {v for v in codelists.codes("verdict", legacy=False)
                       if codelists.map_("verdict_direction").get(v) in ("up", "down")}
# Разбор нужен сейчас (модуль (б)): флаг обзора, новая бумага без разбора, срок решения вышел. «Наблюдать»
# (reviewed_under_review) сюда не входит — это решение, ждущее условия: MEDIUM через действующее условие.
GATE_REVIEW_PENDING = {"review_needed", "new_position", "review_aging"}


def compute_verification_priority(entry: dict,
                                  active_condition_verdicts: list | None = None,
                                  gate_status: str | None = None,
                                  has_hidden_critical_event: bool = False) -> str:
    """Детерминированный verification_priority (расширенное правило C5).

    verification_priority — DERIVED: ставит скрипт (`assemble_artifact.py stamp-report` на обзоре недели, R28),
    модель поле не заполняет; из прошлого обзора не переносится.
    Решает кейс «был BUY+HIGH+review_needed → глубокий анализ (Mode 4/8) → стал HOLD»:
    приоритет спадает сам, т.к. больше нет actionable-вердикта и review-pending gate.

    Семантика: «насколько срочно перепроверить ПЕРЕД ДЕЙСТВИЕМ сейчас».

    HIGH ⟺ действие СЕЙЧАС (effective advisor_verdict ∈ ACTIONABLE)
            ИЛИ разбор нужен сейчас (gate ∈ {review_needed, new_position, review_aging} — флаг обзора, новая
                бумага, срок решения вышел; «наблюдать» сюда не входит)
    MEDIUM ⟺ действие ОТЛОЖЕНО (actionable-soon): unconstrained_verdict actionable (намерение
                замаскировано constraint'ом, напр. MOEX HOLD/TRIM) ИЛИ активное условие
                conditions.yaml с on_trigger.verdict ∈ ACTIONABLE (ждём дату/цену)
            ИЛИ advisor_verdict_confidence < 0.6  ИЛИ  скрытое крит. событие в low-prob сценарии
    LOW иначе (устоявшийся HOLD)

    Принцип: отложенное действие (div-capture, price-gate) НЕ требует верификации прямо сейчас →
    MEDIUM, не HIGH (иначе HIGH «заливается»). HIGH резервируется под «действуй/разбирай сейчас».

    Args:
        entry: per_stock/per_bond dict (advisor_verdict, unconstrained_verdict, advisor_verdict_confidence)
        active_condition_verdicts: список on_trigger.verdict активных (pending) условий тикера
        gate_status: статус гейта тикера по модулю (б) `last_word.py` (или None); копию gate_status_snapshot
            обзора как источник не передавать
        has_hidden_critical_event: бинарный катализатор крит.события в сценарии с p<0.2 (C5 MEDIUM-клауза)
    """
    av = (entry.get("advisor_verdict") or "").upper()
    uv = (entry.get("unconstrained_verdict") or "").upper()
    conf = entry.get("advisor_verdict_confidence")
    acts = [str(a).upper() for a in (active_condition_verdicts or [])]

    # HIGH — действие сейчас или разбор не сделан
    if av in ACTIONABLE_VERDICTS:
        return "HIGH"
    if gate_status in GATE_REVIEW_PENDING:
        return "HIGH"
    # MEDIUM — отложенное действие (actionable-soon) / неопределённость
    if uv in ACTIONABLE_VERDICTS:
        return "MEDIUM"
    if any(a in ACTIONABLE_VERDICTS for a in acts):
        return "MEDIUM"
    if isinstance(conf, (int, float)) and not isinstance(conf, bool) and conf < 0.6:
        return "MEDIUM"
    if has_hidden_critical_event:
        return "MEDIUM"
    return "LOW"


# ─────────────────────── compute_fixed_point_target (gate-aware sizing) ───────────────────────

def compute_fixed_point_target(
    blocked_sum: float,
    dormant_sum: float,
    open_weights: dict,
    extra_cash_from_sales: float = 0.0,
    t_full: float | None = None,
    full_plan_without_gates: bool = True,
) -> dict:
    """
    Неподвижная точка сайзинга покупок при частично замороженной акционной книге
    (docs/investment/gate-aware-sizing-spec.md §3, вариант C). Снимает с LLM
    комбинаторную арифметику (правило скилла №1 — не выдумывай цифры распространяется
    и на арифметику, не только на факты из источников) — тот же принцип, что уже
    применён к сроку и форме среза ограничений.

    T* = F / (1 − S), где:
      F = blocked_sum + dormant_sum — часть класса, неподвижная за цикл (Blocked
          с активным gate/no_buy + Dormant без сигнала на покупку). Тикеры со статусом
          "продать/сократить" в F НЕ входят — исключаются вызывающим кодом до вызова.
          Внутри этого статуса дискриминируются два случая (docs/investment/
          spec-gate-aware-sizing-trim-fix.md §4.1): срез до ОПРЕДЕЛЁННОЙ плановой доли
          (Rebalancing) — вне F, но участвует в S наравне с Open (его вес прибавляется
          к open_weights вызывающим кодом); полный выход/срез без целевого веса
          (Selling) — вне и F, и S.
      S = Σ open_weights.values() — целевые L2-веса тикеров этого цикла, которые
          двигаются к таргету (Open + Rebalancing), доли от T_full.
    target_i = w_i × T*.
    Предохранитель: если передан t_full (план класса в ₽), T* = min(F / (1 − S), t_full) —
    замороженные бумаги выше своей плановой доли не должны поднимать базу выше полного
    плана класса (иначе открытые бумаги докупаются сверх плана). Сработал предел →
    capped=True.
    Замороженная бумага (и выше своей плановой доли) остаётся в F своими рублями, как любая неторгуемая:
    инвариант «база = книга после исполнения» (spec-gate-aware-sizing-trim-fix.md §10.7 — перевод
    перевешенной заморозки «на план» отменён).

    Args:
        blocked_sum: Σ текущих ₽ в тикерах с недостигнутым таргетом под активным
            gate/no_buy — не может быть докуплен в этом цикле.
        dormant_sum: Σ текущих ₽ в тикерах без сигнала на покупку (на таргете в
            пределах hysteresis, Rule 3 — |real − target| < 1 п.п., либо нет триггера
            на пересмотр).
        open_weights: {ticker: target_weight_within_class} для тикеров этого цикла,
            которые двигаются к своему таргету (L2, доли от T_full) — Open (докупка)
            И Rebalancing (срез до определённой плановой доли, см. выше). Тикеры
            "продать/сократить" без целевой доли (Selling) сюда НЕ передаются.
        extra_cash_from_sales: ожидаемая выручка от решённых к продаже позиций
            текущего цикла — добавляется в пул кэша на докупку Open, НЕ влияет на F/S/T*.
        t_full: план класса в ₽ (необязательно); верхний предел T*. None — без предела.
        full_plan_without_gates: True (по умолчанию) — прежняя ветка «blocked_sum ≤ 0 → база = t_full»
            (degenerate). False — непрерывная база (решение владельца 11.11, spec-gate-aware-sizing-trim-fix.md
            §10.6): T* = F / (1 − S_eff) при любом составе F (заблокированные и спящие одинаково), с пределом
            t_full; degenerate = «в F ничего нет» (F ≤ 0) → база = t_full. Снятие
            последней блокировки базу не прыгает: бумага переходит из F в S (или остаётся в F), T* меняется на её
            вклад, а не на разрыв до плана класса.

    Returns:
        {
          "T_star": float | None,        # None только при near_degenerate
          "targets": {ticker: float},    # w_i × T_star; {} при near_degenerate
          "S": float,
          "degenerate": bool,            # blocked_sum <= 0 — гейтов, блокирующих
                                          # докупку, в классе нет; T* совпадает с T_full
                                          # (в пределах hysteresis-погрешности Dormant)
          "near_degenerate": bool,       # (1 - S) < 0.01 — T* численно нестабилен,
                                          # число не досчитывается, флаг на ручную проверку
          "capped": bool,                # T* ограничен t_full (только при переданном t_full)
          "cash_available_for_open": float,  # extra_cash_from_sales; вызывающий код
                                          # добавляет сверху свежие пополнения цикла —
                                          # функция их не получает и не учитывает
        }

    Raises:
        ValueError: если S >= 1 (тикеры, двигающиеся к таргету — Open и Rebalancing —
            не могут занимать 100%+ веса класса).
    """
    F = blocked_sum + dormant_sum
    S = sum(open_weights.values()) if open_weights else 0.0

    if S >= 1:
        raise ValueError(f"compute_fixed_point_target: S >= 1 ({S!r}) — суммарный вес Open "
                          f"и Rebalancing не может покрывать весь вес класса; проверь "
                          f"open_weights (вклад дают обе категории)")

    degenerate = blocked_sum <= 0 if full_plan_without_gates else F <= 0
    near_degenerate = (1 - S) < 0.01

    result = {
        "S": S,
        "degenerate": degenerate,
        "near_degenerate": near_degenerate,
        "cash_available_for_open": extra_cash_from_sales,
    }

    if near_degenerate:
        # §3.1: при знаменателе, стремящемся к нулю, T* численно нестабилен —
        # не домысливаем число, флаг на ручную проверку.
        result["T_star"] = None
        result["targets"] = {}
        return result

    if degenerate and not full_plan_without_gates and t_full is not None:
        # непрерывная база: в F ничего нет — всё движется к плану, база = план класса
        result["T_star"] = t_full
        result["capped"] = False
        result["targets"] = {ticker: weight * t_full for ticker, weight in open_weights.items()}
        return result
    T_star = F / (1 - S)
    result["capped"] = False
    if t_full is not None and T_star > t_full:
        T_star = t_full
        result["capped"] = True
    result["T_star"] = T_star
    result["targets"] = {ticker: weight * T_star for ticker, weight in open_weights.items()}
    return result
