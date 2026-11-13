#!/usr/bin/env python3
"""
carry_over_weekly.py — детерминированный перенос прошлого weekly-review в новый стаб (RPA-23).

Зачем. Каждую неделю режимы 1 (акции) и 2 (облигации) получают от стаба сотни полей
TODO_LLM, а неизменённый анализ лежит в прошлом YAML (200–265 КБ). Раньше модель
переносила его самописными одноразовыми скриптами через вызовы инструментов — это
съедало контекст и лимит. Теперь перенос делает этот скрипт, а модель пишет только
изменения недели в маленький delta.json.

Что делает (схему обзора и методику НЕ меняет — заморозка до 2027-04-07):
  1. Берёт СТАБ (свежие числа снапшота и MOEX главнее прошлого обзора: непустое
     значение стаба не перетирается ничем, кроме явного `override_stub` в delta).
  2. Для бумаг стаба, которые есть в прошлом обзоре, заполняет ТОЛЬКО поля TODO_LLM
     (рекурсивно) значениями прошлого обзора. Списки, целиком состоящие из
     плейсхолдеров (catalyst, *_sources, key_risks, caveats), переносятся целиком.
  3. Поля, которых нет в стабе, но есть у бумаги прошлого обзора (p_outperform_3m,
     prior_verdict, …), переносятся; `prior_verdict` = вердикт прошлого обзора. Срез ограничений
     (`user_constraints`, `unconstrained_verdict*`, `advisor_verdict_constraints`) НЕ переносится: он
     производный, его строит `reconcile_constraints.py` на дату обзора и кладёт через delta. Копия статуса гейта
     `gate_status_snapshot` не переносится вовсе (R28: статус — только модуль (б)); упразднённые верхние блоки старого
     формата (`conditions_evaluated`, `gate_review_directives`, `proposed_gate_review_directives`, `conditions_state`,
     `conditions_mutations_applied` — состояние условий пишет только сайт) не переносятся и через delta не
     принимаются (в отчёте `top_blocks_dropped_obsolete`), `verification_priority` стаба
     (null) не заполняется прошлым — его ставит `stamp-report` save-to-library. Новые бумаги остаются с TODO_LLM (в отчёте «требует анализа»),
     выбывшие — только в отчёт (причину скрипт не выдумывает).
  4. Верхнеуровневые блоки, которых нет в стабе или которые в нём TODO_LLM, берутся
     из прошлого; недельные журналы событий (trades_since_prior, closed_positions,
     amendments, …) сбрасываются в [] — их заполняет модель через delta.
  5. Применяет delta.json (см. ниже); неизвестное поле — ошибка, не молчаливое добавление.
  6. Ставит `carried_over: true` бумагам, у которых после всего нет источника со
     свежим `accessed_date` (окно 7 дней до review_date — правило R-COV валидатора
     save-to-library); при свежем источнике снимает флаг.
  6а. Отбирает перенесённые источники (RPA-37): свежие (окно 7 дней) остаются все; из старых —
     те, на которые ссылается катализатор или текст `*_basis` бумаги, плюс ещё `--keep-old-sources`
     самых новых (по умолчанию 3). Остальные уходят из нового обзора, но остаются в прошлых файлах.
     Без отбора источники копились: обзор акций вырос 136 → 214 КБ за три месяца при тех же 21 бумаге,
     194 из 232 ссылок 26.10 — перенос, самые старые от 27.08.
  7. Пишет отчёт: сколько заполнено, где остался TODO_LLM, новые/выбывшие бумаги и
     предупреждения (окно катализатора закончилось до review_date; число прошлой
     недели в тексте `*_basis`, а в стабе уже другое — только флаг, текст не меняется).

Формат delta.json (всё необязательно):
  {
    "top": {
      "set":    {"producer": "…", "summary.weighted_ytm_pct.ci_pct": [6.1, 34.2],
                 "key_risks": [ {…}, … ]},                     # ключ — точечный путь, значение целиком
      "append": {"caveats": [ {…} ]}                            # дописать элементы в существующий список
    },
    "per_item": {                                               # ключ — тикер (акции) / ISIN (облигации)
      "RU000A106E90": {
        "set":             {"advisor_verdict_basis": "…", "advisor_verdict_confidence": 0.7},
        "append":          {"fundamental_sources": [ {"url": "…", "label": "…", "accessed_date": "2026-10-16"} ]},
        "catalyst_add":    [ {полный катализатор} ],
        "catalyst_remove": ["supply_overhang_q4"],              # по id
        "catalyst_update": {"supply_overhang_q4": {"p": 0.5}},  # по id, поля катализатора
        "unset":           ["p_outperform_3m"],                 # убрать поле (напр. после смены вердикта на HOLD)
        "override_stub":   ["ytm_pct"]                          # разрешить set поля, посчитанного стабом
      }
    },
    "all_items": {"append": {…}, "set": {…}},                   # то же для КАЖДОЙ бумаги (например, общий источник)
    "drop_items": ["TMON", "TPAY"]                              # бумаги стаба, которых в обзоре быть не должно
  }
Поле, которого нет ни в стабе, ни в прошлом обзоре (опечатка), — ошибка с перечнем допустимых.

CLI:
  python3 carry_over_weekly.py --kind stock|bond --stub STUB.yaml --prior PRIOR.yaml \\
      [--delta delta.json] --output NEW.yaml [--report report.json] [--strict]
  python3 carry_over_weekly.py --kind stock|bond --example [--stub STUB.yaml]
      — образец delta.json с ключами этого стаба и перечнем полей (RPA-40: 26.10.2026 ~15 команд
        ушло на выяснение формата по шапке скрипта)

Код выхода: 0 — готово; 1 — `--strict` и остались TODO_LLM; 2 — ошибка входа/delta.
Зависимости: stdlib + PyYAML.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("carry_over_weekly.py требует PyYAML: pip install pyyaml --break-system-packages\n")
    sys.exit(2)

KINDS = {
    "stock": {
        "items_key": "per_stock",
        "type": "weekly-stocks-review",
        "source_keys": ["fundamental_score_sources", "div_sources"],
        "price_fields": ["price_rub", "weight_real_pct"],
    },
    "bond": {
        "items_key": "per_bond",
        "type": "weekly-bonds-review",
        "source_keys": ["fundamental_sources"],
        "price_fields": ["current_price", "ytm_pct", "weight_in_bonds_pct", "weight_real_pct"],
    },
}

# Поля бумаги, допустимые схемой/валидатором, даже если их нет ни в стабе, ни в прошлом.
ITEM_EXTRA_FIELDS = {
    "p_outperform_3m", "user_constraints", "advisor_verdict_constraints", "unconstrained_verdict",
    "unconstrained_verdict_confidence", "carried_over", "verification_checklist",
    "last_corp_event", "next_corp_event", "prior_verdict", "credit_rating_basis", "ytm_to_offer_pct",
    "credit_rating_checked_at",
    "ie_divergence_intentional", "ie_divergence_basis", "catalyst",
    "week_note", "confidence_basis",
}
# Описывают одну неделю: из прошлого обзора НЕ переносятся (контракт A плана переосмысления вьюера,
# 2026-10-26: week_note — «что произошло за неделю», в новой неделе его пишет render_weekly_md --embed-notes).
ITEM_WEEK_ONLY = {"week_note"}
# Срез ограничений (schema.md §4.2): производный, на каждый обзор строится заново из условий и плана
# (reconcile_constraints.py) — из прошлого обзора не переносится.
ITEM_REBUILT = {"user_constraints", "unconstrained_verdict", "unconstrained_verdict_confidence",
                "advisor_verdict_constraints"}
# Устаревшие копии (R28, 03.11): статус гейта даёт модуль (б) через выборку security_digest, копия в обзоре не
# читается — из прошлого обзора не переносится и через delta не задаётся.
ITEM_DROPPED = {"gate_status_snapshot"}
# Упразднённые блоки старого формата (03.11): состояние условий пишет только сайт, гейт — модуль (б); обзор их не
# несёт — из прошлого обзора не переносятся и через delta не принимаются (валидатор обзора — предупреждение).
TOP_DROPPED = {"conditions_evaluated", "gate_review_directives", "proposed_gate_review_directives",
               "conditions_state", "conditions_mutations_applied"}
# Верхнеуровневые блоки, допустимые схемой, даже если их нет ни в стабе, ни в прошлом.
TOP_EXTRA_FIELDS = {
    "amendments", "trades_since_prior",
    "closed_positions", "revision", "carried_over_from", "reports_considered", "plan_change_proposal",
    # блок из sweep_collect.py: валидатор требует его с 27.10 (RPA-34), а в стабе облигаций и в старых
    # обзорах его нет — без этого delta не могла его записать (сухой прогон 2026-10-26, Mode 2)
    "coverage",
}
# Журналы событий одной недели: из прошлого обзора НЕ переносятся (сбрасываются в []), чтобы не
# выдать прошлонедельное событие за текущее. Заполняет модель через delta (top.set).
WEEKLY_EVENT_LOGS = ("trades_since_prior", "closed_positions", "amendments")
# Только из этого прогона: из прошлого обзора не переносятся вовсе, задаются через delta (top.set).
RUN_ONLY_BLOCKS = ("coverage",)
# Описывают конкретную неделю: переносятся, но не должны остаться без пересмотра — в отчёт.
WEEK_BOUND_BLOCKS = (
    "period", "coverage", "revision", "macro_context", "gate_aware_sizing", "ie_discipline", "reports_considered",
    "scenario_matrix", "plan_change_proposal", "plan_vs_fact", "plan_vs_fact_base_rub", "plan_vs_fact_iis",
)
# Идентичность прогона и провенанс недели: прошлое значение было бы неверным — оставляем TODO_LLM.
NO_CARRY_PATHS = {"producer", "macro_source", "macro_input", "sources.macro_input", "sources.moex_quotes"}
FRESH_WINDOW_DAYS = 7
KEEP_OLD_SOURCES = 3  # сколько самых новых старых источников без ссылок оставлять на список бумаги


class DeltaError(ValueError):
    """Ошибка в delta.json или во входных файлах — выход с кодом 2."""


# ───────────────────────── утилиты ─────────────────────────

def is_todo(v: Any) -> bool:
    return isinstance(v, str) and v.startswith("TODO_LLM")


def leaves(node: Any, path: tuple = ()):
    """Все листья (path, value)."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from leaves(v, path + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from leaves(v, path + (i,))
    else:
        yield path, node


def has_todo(node: Any) -> bool:
    return any(is_todo(v) for _, v in leaves(node))


def pure_placeholder(node: Any) -> bool:
    """Узел, все листья которого — TODO_LLM (напр. catalyst-плейсхолдер стаба)."""
    ls = list(leaves(node))
    return bool(ls) and all(is_todo(v) for _, v in ls)


def placeholder_list(node: Any) -> bool:
    """Список-плейсхолдер стаба: каждый элемент — объект с хотя бы одним TODO_LLM.

    Остальные поля такого элемента (например, `accessed_date` сегодняшней датой в источниках)
    — заготовка стаба, а не данные: перенос идёт целиком из прошлого, с его настоящими датами.
    """
    return (isinstance(node, list) and bool(node)
            and all(isinstance(e, dict) and has_todo(e) for e in node))


def fmt_path(path: tuple) -> str:
    return ".".join(str(p) for p in path)


def load_yaml(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as exc:
        raise DeltaError(f"не удалось прочитать {path}: {exc}")
    if not isinstance(data, dict):
        raise DeltaError(f"{path}: ожидался YAML-словарь верхнего уровня")
    return data


class _NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):  # без якорей &id001 — как в прошлых обзорах
        return True


def dump_yaml(data: dict) -> str:
    return yaml.dump(data, Dumper=_NoAliasDumper, sort_keys=False, allow_unicode=True, default_flow_style=False)


def merge_order(prior_keys: list, stub_keys: list, wanted: set) -> list:
    """Порядок ключей как в прошлом обзоре; ключи только стаба — после своего предшественника в стабе."""
    out = [k for k in prior_keys if k in wanted]
    for i, k in enumerate(stub_keys):
        if k in out or k not in wanted:
            continue
        pos = 0
        for j in range(i - 1, -1, -1):
            if stub_keys[j] in out:
                pos = out.index(stub_keys[j]) + 1
                break
        out.insert(pos, k)
    return out


# ───────────────────────── заполнение из прошлого ─────────────────────────

class Filler:
    def __init__(self) -> None:
        self.filled = 0               # листьев заполнено из прошлого
        self.nested_carried: list[str] = []  # поля прошлого обзора, которых нет в стабе, внутри его блоков
        self.skip_extras_under: str | None = None  # ключ блока бумаг: его дописывает вызывающий
        self.removed_as_prior: list[str] = []  # заготовки «…_or_remove…», удалённые в прошлом обзоре

    def fill(self, stub: Any, prior: Any, path: tuple) -> Any:
        """Рекурсивно: TODO_LLM стаба -> значение прошлого; нечисловой/непустой стаб остаётся как есть."""
        if is_todo(stub):
            if fmt_path(path) in NO_CARRY_PATHS or prior is _MISSING or has_todo(prior):
                return stub
            self.filled += sum(1 for _ in leaves(prior)) or 1
            return copy.deepcopy(prior)
        if isinstance(stub, dict):
            out = {}
            prior_done = isinstance(prior, dict) and bool(prior) and not has_todo(prior)
            for k, v in stub.items():
                p = prior.get(k, _MISSING) if isinstance(prior, dict) else _MISSING
                # Поле-заготовка «…_or_remove…», которого нет в заполненном блоке прошлого обзора, —
                # автор его сознательно удалил (напр. dividend_forward.year1_yield_pct при неопределённой
                # политике): не возвращать TODO. Сухой прогон 2026-10-26: 7 бумаг упёрлись бы в --strict.
                if p is _MISSING and prior_done and is_todo(v) and "_or_remove" in v:
                    self.removed_as_prior.append(fmt_path(path + (k,)))
                    continue
                out[k] = self.fill(v, p, path + (k,))
            if isinstance(prior, dict) and has_todo(stub) and path[:1] != (self.skip_extras_under,):
                extras = [k for k in prior if k not in stub and fmt_path(path + (k,)) not in NO_CARRY_PATHS]
                for k in extras:
                    out[k] = copy.deepcopy(prior[k])
                    self.nested_carried.append(fmt_path(path + (k,)))
                if extras:
                    order = merge_order(list(prior), list(stub), set(out))
                    out = {k: out[k] for k in order}
            return out
        if isinstance(stub, list):
            if placeholder_list(stub) and isinstance(prior, list) and not has_todo(prior):
                self.filled += sum(1 for _ in leaves(prior)) or 1
                return copy.deepcopy(prior)
            if has_todo(stub) and isinstance(prior, list):
                return [self.fill(v, prior[i] if i < len(prior) else _MISSING, path + (i,)) for i, v in enumerate(stub)]
            return stub
        if stub is None and path and path[-1] in CARRY_WHEN_STUB_NULL and prior not in (_MISSING, None):
            self.filled += 1
            return copy.deepcopy(prior)
        return stub


_MISSING = object()

# Поля, которые стаб пишет null («не знаю»), а значение прошлого обзора переносится как есть.
CARRY_WHEN_STUB_NULL = {"credit_rating_checked_at"}


# ───────────────────────── окна и предупреждения ─────────────────────────

_QUARTER_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}


def window_end(text: Any) -> date | None:
    """Конец окна катализатора: берётся последняя дата в date_window.

    Понимает YYYY-MM-DD, YYYY-MM, YYYY-Qn, YYYY (конец периода), диапазоны через 'to', '..', '–'.
    Не распознал — None (предупреждения нет).
    """
    if not isinstance(text, str):
        if isinstance(text, date):
            return text
        return None
    parts = [p.strip() for p in re.split(r"\s+to\s+|\.\.|\s+–\s+|—", text) if p.strip()]
    if not parts:
        return None
    last = parts[-1]
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", last)
    try:
        if m:
            return date(int(m[1]), int(m[2]), int(m[3]))
        m = re.fullmatch(r"(\d{4})-(\d{2})", last)
        if m:
            y, mo = int(m[1]), int(m[2])
            nxt = date(y + (mo == 12), mo % 12 + 1, 1)
            return nxt - timedelta(days=1)
        m = re.fullmatch(r"(\d{4})-Q([1-4])", last)
        if m:
            mo, d = _QUARTER_END[int(m[2])]
            return date(int(m[1]), mo, d)
        m = re.fullmatch(r"(\d{4})", last)
        if m:
            return date(int(m[1]), 12, 31)
    except ValueError:
        return None
    return None


def _num_tokens(text: str) -> list[tuple[float, int]]:
    """Числа текста (запятая/точка) с числом знаков после разделителя."""
    out = []
    for m in re.finditer(r"(?<![\d.,])(\d+)(?:[.,](\d+))?(?![\d])", text):
        dec = len(m[2]) if m[2] else 0
        out.append((float(f"{m[1]}.{m[2]}" if m[2] else m[1]), dec))
    return out


def number_in_text(value: Any, text: str) -> bool:
    """Встречается ли число value в тексте (с точностью до выводимого числа знаков; только дробные токены)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    for tok, dec in _num_tokens(text):
        if dec >= 1 and round(float(value), dec) == tok:
            return True
    return False


def basis_warnings(item_key: str, stub_item: dict, prior_item: dict, final_item: dict,
                   touched: set, fields: list[str]) -> list[dict]:
    """Текст *_basis перенесён из прошлого, в нём число прошлой недели, а у стаба уже другое."""
    out = []
    for f, text in final_item.items():
        if not (f.endswith("_basis") and isinstance(text, str)) or f in touched or is_todo(text):
            continue
        if prior_item.get(f) != text:
            continue
        for nf in fields:
            old, new = prior_item.get(nf), stub_item.get(nf)
            if isinstance(old, bool) or isinstance(new, bool):
                continue
            if not isinstance(old, (int, float)) or not isinstance(new, (int, float)) or old == new:
                continue
            if number_in_text(old, text) and not number_in_text(new, text):
                out.append({"type": "basis_stale_number", "item": item_key, "field": f, "numeric_field": nf,
                            "prior_value": old, "stub_value": new,
                            "msg": f"{item_key}/{f}: в тексте число прошлого обзора {old} ({nf}), в стабе {new}; текст не менялся"})
    return out


# ───────────────────────── delta ─────────────────────────

def _get_path(doc: Any, parts: list[str]) -> Any:
    cur = doc
    for p in parts:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return _MISSING
    return cur


def _known_top(stub: dict, prior: dict) -> set:
    return (set(stub) | set(prior) | TOP_EXTRA_FIELDS) - TOP_DROPPED


def apply_top(doc: dict, stub: dict, prior: dict, ops: dict, log: dict) -> None:
    if not isinstance(ops, dict):
        raise DeltaError("delta.top должен быть объектом {set, append}")
    unknown = set(ops) - {"set", "append"}
    if unknown:
        raise DeltaError(f"delta.top: неизвестные операции {sorted(unknown)}; допустимы set, append")
    known = _known_top(stub, prior)
    for path in list(ops.get("set") or {}) + list(ops.get("append") or {}):
        if path.split(".")[0] in TOP_DROPPED:
            raise DeltaError(f"delta.top: {path.split('.')[0]!r} — упразднённый блок старого формата; "
                             f"состояние условий пишет только сайт, обзор его не несёт")
    for path, value in (ops.get("set") or {}).items():
        parts = path.split(".")
        if parts[0] not in known:
            raise DeltaError(f"delta.top.set: неизвестный верхнеуровневый ключ {parts[0]!r}; "
                             f"допустимы: {sorted(known)}")
        cur = doc
        for i, p in enumerate(parts[:-1]):
            if not isinstance(cur.get(p), dict):
                raise DeltaError(f"delta.top.set: путь {path!r} не существует (нет {'.'.join(parts[:i + 1])!r})")
            cur = cur[p]
        if len(parts) > 1 and parts[-1] not in cur:
            raise DeltaError(f"delta.top.set: поле {parts[-1]!r} не найдено в {'.'.join(parts[:-1])!r}; "
                             f"есть: {sorted(cur)}")
        if len(parts) > 1 and _is_stub_owned(_get_path(stub, parts)):
            raise DeltaError(f"delta.top.set: {path!r} посчитано стабом (снапшот/MOEX), править нельзя")
        cur[parts[-1]] = copy.deepcopy(value)
        log["top_set"] += 1
    for path, items in (ops.get("append") or {}).items():
        parts = path.split(".")
        target = _get_path(doc, parts)
        if target is _MISSING and parts[0] in known and len(parts) == 1:
            doc[parts[0]] = target = []
        if not isinstance(target, list) or not isinstance(items, list):
            raise DeltaError(f"delta.top.append: {path!r} должен быть списком и значение — списком")
        if target and placeholder_list(target):
            target.clear()
        target.extend(copy.deepcopy(items))
        log["top_append"] += 1


def _is_stub_owned(v: Any) -> bool:
    """Значение, которое посчитал стаб (не TODO, не None, скаляр)."""
    return v is not _MISSING and v is not None and not isinstance(v, (dict, list)) and not is_todo(v)


def apply_item_ops(key: str, item: dict, stub_item: dict, ops: dict, allowed: set, log: dict) -> set:
    """Применяет операции к бумаге; возвращает множество затронутых полей."""
    touched: set = set()
    unknown = set(ops) - {"set", "append", "catalyst_add", "catalyst_remove", "catalyst_update", "override_stub", "unset"}
    if unknown:
        raise DeltaError(f"delta.per_item[{key}]: неизвестные операции {sorted(unknown)}")
    override = set(ops.get("override_stub") or [])
    for f, v in (ops.get("set") or {}).items():
        if f not in allowed:
            raise DeltaError(f"delta.per_item[{key}].set: поля {f!r} нет в схеме (опечатка?). "
                             f"Допустимые: {sorted(allowed)}")
        if _is_stub_owned(stub_item.get(f, _MISSING)) and f not in override:
            raise DeltaError(f"delta.per_item[{key}].set: {f!r} посчитано стабом (снапшот/MOEX), стаб главнее; "
                             f"если правка нужна — добавьте {f!r} в override_stub")
        item[f] = copy.deepcopy(v)
        touched.add(f)
        log["item_set"] += 1
    for f, vals in (ops.get("append") or {}).items():
        if f not in allowed:
            raise DeltaError(f"delta.per_item[{key}].append: поля {f!r} нет в схеме (опечатка?)")
        cur = item.get(f)
        if cur is None:
            item[f] = cur = []
        if not isinstance(cur, list) or not isinstance(vals, list):
            raise DeltaError(f"delta.per_item[{key}].append: {f!r} должен быть списком")
        if cur and placeholder_list(cur):
            cur.clear()
        cur.extend(copy.deepcopy(vals))
        touched.add(f)
        log["item_append"] += 1
    for f in ops.get("unset") or []:
        if f not in allowed:
            raise DeltaError(f"delta.per_item[{key}].unset: поля {f!r} нет в схеме (опечатка?)")
        if f in item:
            del item[f]
            touched.add(f)
            log["item_unset"] += 1
    cats = item.get("catalyst")
    has_cat_ops = any(ops.get(o) for o in ("catalyst_add", "catalyst_remove", "catalyst_update"))
    if has_cat_ops:
        if not isinstance(cats, list):
            cats = item["catalyst"] = []
        if cats and placeholder_list(cats):
            cats = item["catalyst"] = []
        by_id = {c.get("id"): c for c in cats if isinstance(c, dict)}
        for cid in ops.get("catalyst_remove") or []:
            if cid not in by_id:
                raise DeltaError(f"delta.per_item[{key}].catalyst_remove: катализатора id={cid!r} нет; есть {sorted(map(str, by_id))}")
            cats[:] = [c for c in cats if not (isinstance(c, dict) and c.get("id") == cid)]
            by_id.pop(cid)
            log["catalyst_remove"] += 1
        for cid, upd in (ops.get("catalyst_update") or {}).items():
            if cid not in by_id:
                raise DeltaError(f"delta.per_item[{key}].catalyst_update: катализатора id={cid!r} нет; есть {sorted(map(str, by_id))}")
            if not isinstance(upd, dict):
                raise DeltaError(f"delta.per_item[{key}].catalyst_update[{cid}] должен быть объектом")
            known_cat_fields = set().union(*[set(c) for c in cats if isinstance(c, dict)]) | CATALYST_FIELDS
            bad = set(upd) - known_cat_fields
            if bad:
                raise DeltaError(f"delta.per_item[{key}].catalyst_update[{cid}]: неизвестные поля {sorted(bad)}")
            by_id[cid].update(copy.deepcopy(upd))
            log["catalyst_update"] += 1
        for c in ops.get("catalyst_add") or []:
            if not isinstance(c, dict) or "id" not in c:
                raise DeltaError(f"delta.per_item[{key}].catalyst_add: катализатор должен быть объектом с id")
            if c["id"] in by_id:
                raise DeltaError(f"delta.per_item[{key}].catalyst_add: id={c['id']!r} уже есть (используйте catalyst_update)")
            cats.append(copy.deepcopy(c))
            by_id[c["id"]] = c
            log["catalyst_add"] += 1
        touched.add("catalyst")
    return touched


# ───────────────────────── источники ─────────────────────────

_URL = re.compile(r"https?://[^\s)\]>'\"«»,]+")


def _referenced_urls(item: dict) -> set:
    refs: set = set()
    for c in item.get("catalyst") or []:
        if isinstance(c, dict):
            refs |= set(_URL.findall(str(c.get("source") or "")))
    for f, v in item.items():
        if f.endswith("_basis") and isinstance(v, str):
            refs |= set(_URL.findall(v))
    return {u.rstrip(".;:") for u in refs}


def prune_sources(item: dict, source_keys: list[str], floor: str, keep_old: int) -> int:
    """Свежие — все; старые — со ссылкой из катализатора/basis + keep_old самых новых. Возвращает, сколько убрано."""
    refs = _referenced_urls(item)
    removed = 0
    for sk in source_keys:
        lst = item.get(sk)
        if not isinstance(lst, list) or not lst:
            continue
        old_free = []
        for i, s in enumerate(lst):
            if not isinstance(s, dict) or not s.get("accessed_date"):
                continue
            if str(s["accessed_date"])[:10] >= floor:
                continue
            if str(s.get("url") or "").rstrip(".;:") in refs:
                continue
            old_free.append((str(s["accessed_date"])[:10], i))
        old_free.sort(reverse=True)
        drop = {i for _, i in old_free[keep_old:]}
        if drop:
            item[sk] = [s for i, s in enumerate(lst) if i not in drop]
            removed += len(drop)
    return removed


CATALYST_FIELDS = {
    "id", "kind", "trigger", "date_window", "p", "upside_pct", "upside_ci_pct", "downside_pct",
    "downside_ci_pct", "source", "source_quality", "source_trust", "macro_dependency",
    "upside_by_scenario", "upside_ci_by_scenario", "active_scenarios", "event_date",
}


# ───────────────────────── основной проход ─────────────────────────

def carry_over(kind: str, stub: dict, prior: dict, delta: dict | None, prior_name: str,
               keep_old_sources: int | None = KEEP_OLD_SOURCES) -> tuple[dict, dict]:
    cfg = KINDS[kind]
    ik = cfg["items_key"]
    if stub.get("type") != cfg["type"]:
        raise DeltaError(f"стаб: type={stub.get('type')!r}, для --kind {kind} ожидался {cfg['type']!r}")
    if prior.get("type") != cfg["type"]:
        raise DeltaError(f"прошлый обзор: type={prior.get('type')!r}, ожидался {cfg['type']!r}")
    if not isinstance(stub.get(ik), dict) or not isinstance(prior.get(ik), dict):
        raise DeltaError(f"нет блока {ik} в стабе или прошлом обзоре")

    delta = delta or {}
    bad = set(delta) - {"top", "per_item", "all_items", "drop_items"}
    if bad:
        raise DeltaError(f"delta: неизвестные разделы {sorted(bad)}; допустимы top, per_item, all_items, drop_items")

    review_date = str(stub.get("review_date"))[:10]
    filler = Filler()
    filler.skip_extras_under = ik
    log = {k: 0 for k in ("top_set", "top_append", "item_set", "item_append", "catalyst_add",
                          "catalyst_remove", "catalyst_update", "item_unset")}
    warnings: list[dict] = []

    # --- верхний уровень: всё кроме блока бумаг ---
    doc: dict = {}
    top_keys = merge_order(list(prior), list(stub), set(stub) | set(prior))
    carried_blocks: list[str] = []
    reset_blocks: list[str] = []
    dropped_blocks: list[str] = []
    for k in top_keys:
        if k in TOP_DROPPED:
            dropped_blocks.append(k)   # упразднённый блок старого формата — не переносится
            continue
        if k == ik:
            doc[k] = None  # заполним ниже, место в порядке сохраняем
        elif k in stub:
            doc[k] = filler.fill(stub[k], prior.get(k, _MISSING), (k,))
            if k in prior and has_todo(stub[k]) and doc[k] != stub[k]:
                carried_blocks.append(k)
        elif k in WEEKLY_EVENT_LOGS:
            doc[k] = []
            if prior[k]:
                reset_blocks.append(k)
        elif k in RUN_ONLY_BLOCKS:
            # покрытие проверкой — свойство этого прогона: прошлое `coverage.method: sweep_collect`
            # пропустило бы обзор без свежего сбора новостей мимо валидатора (сухой прогон 2026-10-26)
            reset_blocks.append(k)
            continue
        else:
            doc[k] = copy.deepcopy(prior[k])
            carried_blocks.append(k)
    if "carried_over_from" in doc and "carried_over_from" not in stub:
        doc["carried_over_from"] = prior_name
    if isinstance(doc.get("period"), dict) and "period" not in stub and set(doc["period"]) >= {"from", "to"}:
        doc["period"] = {**doc["period"], "from": str(prior.get("review_date"))[:10], "to": review_date}
        if "period" in carried_blocks:
            carried_blocks.remove("period")
    # --- бумаги ---
    drop = delta.get("drop_items") or []
    if not isinstance(drop, list):
        raise DeltaError("delta.drop_items должен быть списком ключей")
    for key in drop:
        if key not in stub[ik]:
            raise DeltaError(f"delta.drop_items: ключа {key!r} нет в стабе; есть {sorted(stub[ik])}")
    stub_items, prior_items = {k: v for k, v in stub[ik].items() if k not in drop}, prior[ik]
    new_items = [k for k in stub_items if k not in prior_items]
    dropped = [{"key": k, "name": (v or {}).get("name"), "advisor_verdict": (v or {}).get("advisor_verdict"),
                "advisor_verdict_confidence": (v or {}).get("advisor_verdict_confidence"),
                "value_rub": (v or {}).get("value_rub")}
               for k, v in prior_items.items() if k not in stub_items]
    items: dict = {}
    carried_prior_only: dict[str, list] = {}
    slice_dropped: dict[str, list] = {}   # срез прошлого обзора не перенесён — построить заново
    for key, s_item in stub_items.items():
        p_item = prior_items.get(key)
        if p_item is None:
            items[key] = copy.deepcopy(s_item)
            continue
        item = filler.fill(s_item, p_item, (ik, key))
        extra = [f for f in p_item if f not in s_item and f not in ITEM_WEEK_ONLY and f not in ITEM_REBUILT
                 and f not in ITEM_DROPPED]
        for f in extra:
            item[f] = copy.deepcopy(p_item[f])
        if "prior_verdict" in p_item and p_item.get("advisor_verdict") is not None and not is_todo(p_item.get("advisor_verdict")):
            item["prior_verdict"] = p_item["advisor_verdict"]
        if extra:
            carried_prior_only[key] = extra
        rebuilt = sorted(f for f in ITEM_REBUILT if f in p_item and f not in s_item)
        if rebuilt:
            slice_dropped[key] = rebuilt
        order = merge_order(list(p_item), list(s_item), set(item))
        items[key] = {f: item[f] for f in order}

    # --- допустимые поля ---
    allowed = set(ITEM_EXTRA_FIELDS)
    for src in (stub_items, prior_items):
        for v in src.values():
            if isinstance(v, dict):
                allowed |= set(v)
    for it in items.values():
        allowed |= set(it)
    allowed -= ITEM_DROPPED
    doc[ik] = items

    # --- delta ---
    touched_by_item: dict[str, set] = {k: set() for k in items}
    per_item = delta.get("per_item") or {}
    if not isinstance(per_item, dict):
        raise DeltaError("delta.per_item должен быть объектом {ключ: операции}")
    for key in per_item:
        if key not in items:
            hint = " (бумага выбыла: в стабе её нет)" if key in prior_items else ""
            raise DeltaError(f"delta.per_item: ключа {key!r} нет в стабе{hint}; есть {len(items)} бумаг")
    if delta.get("all_items"):
        ops = delta["all_items"]
        for key in items:
            touched_by_item[key] |= apply_item_ops(key, items[key], stub_items[key], ops, allowed, log)
    for key, ops in per_item.items():
        touched_by_item[key] |= apply_item_ops(key, items[key], stub_items[key], ops, allowed, log)
    if delta.get("top"):
        apply_top(doc, stub, prior, delta["top"], log)

    # --- отбор перенесённых источников, carried_over по R-COV, предупреждения ---
    rd = date.fromisoformat(review_date)
    floor = (rd - timedelta(days=FRESH_WINDOW_DAYS)).isoformat()
    pruned: dict[str, int] = {}
    if keep_old_sources is not None:
        for key, item in items.items():
            if key in new_items:
                continue
            n = prune_sources(item, cfg["source_keys"], floor, keep_old_sources)
            if n:
                pruned[key] = n
    marked: list[str] = []
    unmarked: list[str] = []
    for key, item in items.items():
        if key in new_items:
            continue
        if "carried_over" in touched_by_item[key]:
            continue
        dates = []
        for sk in cfg["source_keys"]:
            for s in item.get(sk) or []:
                if isinstance(s, dict) and s.get("accessed_date"):
                    dates.append(str(s["accessed_date"])[:10])
        if any(d >= floor for d in dates):
            if item.pop("carried_over", None) is not None:
                unmarked.append(key)
        else:
            item["carried_over"] = True
            marked.append(key)
        # порядок: carried_over в конец, как в прошлых обзорах
        if "carried_over" in item:
            v = item.pop("carried_over")
            item["carried_over"] = v

    for key, item in items.items():
        p_item, s_item = prior_items.get(key), stub_items[key]
        cats = item.get("catalyst")
        for c in cats if isinstance(cats, list) else []:
            if not isinstance(c, dict):
                continue
            end = window_end(c.get("event_date")) if c.get("event_date") else window_end(c.get("date_window"))
            if end is not None and end < rd:
                src = "event_date" if c.get("event_date") else "date_window"
                warnings.append({"type": "catalyst_in_past", "item": key, "catalyst": c.get("id"),
                                "msg": f"{key}/{c.get('id')}: {src} закончилось {end.isoformat()} < review_date {review_date}, "
                                       f"а катализатор числится будущим"})
        if p_item is not None:
            warnings += basis_warnings(key, s_item, p_item, item, touched_by_item[key], cfg["price_fields"])
            # Стаб не посчитал рыночное поле (YTM флоатера, нет котировки), в прошлом обзоре оно было:
            # валидатор требует непустое значение — подсказать, что задать его надо через delta.
            for nf in cfg["price_fields"]:
                if item.get(nf) is None and nf in s_item and isinstance(p_item.get(nf), (int, float)) \
                        and nf not in touched_by_item[key]:
                    warnings.append({"type": "stub_null_field", "item": key, "field": nf, "prior_value": p_item[nf],
                                     "msg": f"{key}/{nf}: стаб не посчитал (в прошлом обзоре {p_item[nf]}); "
                                            f"задать через delta per_item.set с источником в basis"})

    # --- остаток TODO_LLM ---
    todo_paths = [fmt_path(p) for p, v in leaves(doc) if is_todo(v)]
    todo_by_item: dict[str, int] = {}
    for p in todo_paths:
        parts = p.split(".")
        k = parts[1] if parts[0] == ik and len(parts) > 1 else "(top)"
        todo_by_item[k] = todo_by_item.get(k, 0) + 1

    for blk in sorted(set(carried_blocks) & set(WEEK_BOUND_BLOCKS)):
        if blk not in (delta.get("top") or {}).get("set", {}):
            warnings.append({"type": "week_bound_block_carried", "block": blk,
                             "msg": f"блок {blk} перенесён из прошлого обзора без изменений — проверить, относится ли он к этой неделе"})
    if "producer" in todo_paths:
        warnings.append({"type": "todo_identity", "msg": "producer остался TODO_LLM — задайте через delta.top.set"})

    stale_sensitive = []
    for key, fields in carried_prior_only.items():
        hit = [f for f in fields if f in ("user_constraints", "advisor_verdict_constraints",
                                          "unconstrained_verdict", "ytm_to_offer_pct", "p_outperform_3m")]
        if hit:
            stale_sensitive.append({"item": key, "fields": hit})
    for key, fields in slice_dropped.items():
        stale_sensitive.append({"item": key, "fields": fields, "rebuild": "reconcile_constraints.py"})

    report = {
        "kind": kind,
        "review_date": review_date,
        "prior_review_date": str(prior.get("review_date"))[:10],
        "items_total": len(items),
        "items_from_prior": len(items) - len(new_items),
        "filled_from_prior_leaves": filler.filled,
        "todo_remaining": len(todo_paths),
        "todo_remaining_by_item": todo_by_item,
        "todo_remaining_paths": todo_paths,
        "dropped_by_delta": list(drop),
        "new_items_need_analysis": [{"key": k, "name": stub_items[k].get("name")} for k in new_items],
        "dropped_items": dropped,
        "delta_applied": log,
        "sources_pruned": {"total": sum(pruned.values()), "by_item": pruned,
                           "keep_old_sources": keep_old_sources},
        "carried_over_marked": marked,
        "carried_over_cleared": unmarked,
        "top_blocks_carried_unchanged": sorted(carried_blocks),
        "top_blocks_reset_to_empty": sorted(reset_blocks),
        "top_blocks_dropped_obsolete": sorted(dropped_blocks),
        "nested_prior_only_fields_carried": filler.nested_carried,
        "placeholders_removed_as_in_prior": filler.removed_as_prior,
        "prior_only_item_fields_carried": {k: v for k, v in carried_prior_only.items()},
        "need_reconcile_or_recheck": stale_sensitive,
        "warnings": warnings,
    }
    return doc, report


# ───────────────────────── образец delta (RPA-40) ─────────────────────────

def example_delta(kind: str, stub: dict | None) -> str:
    """Короткая справка + JSON-образец delta с реальным ключом бумаги и полями стаба."""
    cfg = KINDS[kind]
    items = (stub or {}).get(cfg["items_key"]) or {}
    key = next(iter(items), "TICKER" if kind == "stock" else "RU000A000000")
    item = items.get(key) or {}
    rd = str((stub or {}).get("review_date") or "YYYY-MM-DD")[:10]
    src_key = cfg["source_keys"][0]
    stub_owned = sorted(f for f, v in item.items() if _is_stub_owned(v))
    editable = sorted((set(item) | ITEM_EXTRA_FIELDS) - set(stub_owned))
    cat = {f: f"<{f}>" for f in ("id", "kind", "trigger", "date_window", "p", "upside_pct", "upside_ci_pct",
                                  "source", "source_quality", "source_trust", "macro_dependency")}
    cat.update({"kind": "binary", "p": 0.5, "upside_pct": 5.0, "upside_ci_pct": [1.0, 9.0],
                "source_trust": {"analyst": "external", "subdomain": "primary"}})
    item_set = {"advisor_verdict": "HOLD", "advisor_verdict_confidence": 0.6,
                "advisor_verdict_basis": "<почему — по фактам этой недели>"}
    if kind == "bond":  # дата сверки рейтинга с первоисточником агентства; не сверял — поле не трогать
        item_set["credit_rating_checked_at"] = rd
    delta = {
        "top": {"set": {"producer": "<модель> (ru-portfolio-advisor, …)"},
                "append": {"caveats": [{"severity": "MEDIUM", "text": "<оговорка недели>"}]}},
        "per_item": {key: {
            "set": item_set,
            "append": {src_key: [{"url": "https://…", "label": "<что подтверждает>", "accessed_date": rd}]},
            "catalyst_add": [cat],
            "catalyst_update": {"<id существующего>": {"p": 0.4}},
            "catalyst_remove": ["<id прошедшего>"],
            "unset": ["p_outperform_3m"],
        }},
        "all_items": {"append": {src_key: [{"url": "https://cbr.ru/…", "label": "<общий источник недели>",
                                            "accessed_date": rd}]}},
        "drop_items": [],
    }
    lines = [
        f"# Образец delta.json ({kind}; бумага {key}{' — из стаба' if items else ''})",
        "Разделы: top{set,append} · per_item{ключ: set|append|unset|catalyst_add|catalyst_update|"
        "catalyst_remove|override_stub} · all_items{set,append} · drop_items[]. Всё необязательно —",
        "пиши только изменения недели; неизменённое переносится само. top.set — точечный путь (a.b.c).",
        "Опечатка в поле или правка поля стаба без override_stub — ошибка с перечнем допустимых (код 2).",
        "Срез ограничений (user_constraints, unconstrained_verdict*, advisor_verdict_constraints) из прошлого",
        "обзора не переносится — положи выход reconcile_constraints.py через per_item.set.",
    ]
    if items:
        lines += [f"Поля стаба (только через override_stub с причиной в basis): {', '.join(stub_owned) or '—'}",
                  f"Поля для set/append/unset: {', '.join(editable)}"]
    lines += ["", json.dumps(delta, ensure_ascii=False, indent=2)]
    return "\n".join(lines)


# ───────────────────────── CLI ─────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--kind", required=True, choices=sorted(KINDS))
    ap.add_argument("--stub", type=Path, help="стаб нового обзора (build_weekly_*_stub.py)")
    ap.add_argument("--prior", type=Path, help="прошлый обзор .yaml")
    ap.add_argument("--delta", type=Path, default=None, help="delta.json — изменения недели")
    ap.add_argument("--output", type=Path, help="куда записать новый YAML")
    ap.add_argument("--report", type=Path, default=None, help="куда записать отчёт JSON (иначе — в stdout)")
    ap.add_argument("--strict", action="store_true", help="код выхода 1, если остались TODO_LLM")
    ap.add_argument("--keep-old-sources", type=int, default=KEEP_OLD_SOURCES,
                    help=f"сколько старых источников без ссылок оставить на список бумаги (по умолчанию {KEEP_OLD_SOURCES})")
    ap.add_argument("--no-prune", action="store_true", help="переносить все старые источники (как до RPA-37)")
    ap.add_argument("--example", action="store_true", help="напечатать образец delta.json (с --stub — с его ключами)")
    args = ap.parse_args(argv)
    if args.example:
        try:
            print(example_delta(args.kind, load_yaml(args.stub) if args.stub else None))
        except DeltaError as exc:
            sys.stderr.write(f"ОШИБКА: {exc}\n")
            return 2
        return 0
    missing = [n for n in ("stub", "prior", "output") if getattr(args, n) is None]
    if missing:
        ap.error("нужны " + ", ".join("--" + m for m in missing) + " (или --example)")
    try:
        stub = load_yaml(args.stub)
        prior = load_yaml(args.prior)
        delta = None
        if args.delta:
            try:
                delta = json.loads(args.delta.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise DeltaError(f"delta.json: {exc}")
            if not isinstance(delta, dict):
                raise DeltaError("delta.json должен быть JSON-объектом")
        doc, report = carry_over(args.kind, stub, prior, delta, args.prior.name,
                                 None if args.no_prune else max(0, args.keep_old_sources))
    except DeltaError as exc:
        sys.stderr.write(f"ОШИБКА: {exc}\n")
        return 2
    args.output.write_text(dump_yaml(doc), encoding="utf-8")
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.write_text(text + "\n", encoding="utf-8")
        brief = {k: report[k] for k in ("items_total", "filled_from_prior_leaves", "todo_remaining")}
        brief.update(new_items=len(report["new_items_need_analysis"]), dropped=len(report["dropped_items"]),
                     sources_pruned=report["sources_pruned"]["total"], warnings=len(report["warnings"]))
        print(json.dumps(brief, ensure_ascii=False))
    else:
        print(text)
    return 1 if args.strict and report["todo_remaining"] else 0


if __name__ == "__main__":
    sys.exit(main())
