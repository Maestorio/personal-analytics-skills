#!/usr/bin/env python3
"""
gate_aware_sizing.py

Снимает с рассуждения LLM три вещи разом: сбор входов для gate-aware сайзинга акций
(классификация Open/Blocked/Dormant/Selling/Rebalancing из snapshot + решений по бумаге (гейт — модуль (б)
`last_word.py`) + справочника бумаг (IPO-пауза) + условий conditions@2 с состоянием (модуль (а)
`conditions_merge.py`) — Rebalancing = срез до ОПРЕДЕЛЁННОЙ плановой доли, в отличие от Selling —
полного выхода/среза без целевого веса, docs/investment/spec-gate-aware-sizing-trim-fix.md),
арифметику неподвижной точки (делегируется `constraint_engine.compute_fixed_point_target`,
не дублируется здесь) и формулировку готового текста для отчёта.

Контекст и контракт формулировок — `docs/investment/gate-aware-sizing-spec.md` (методика)
и `docs/investment/portfolio/gate-aware-sizing-rollout-plan.md` §1/§T1 (термины отчёта,
CLI, поведение). Термины «база докупки» и «остаток, закрытый для покупок гейтами» —
канонические (решение владельца 20.08.2026), синонимы им не подбираются.

Область применения — ТОЛЬКО акции (`docs/investment/portfolio/gate-aware-sizing-rollout-plan.md`
§2). Для облигаций и фондов база сайзинга плановая — этот скрипт им не нужен.

Скрипт строго read-only: ничего не пишет на диск, вся выдача — в stdout.

Правило неразворота (docs/investment/spec-gate-aware-sizing-trim-fix.md §8/§10.3) —
три флага сверх задачи A:

    --cycles FILE.json         # B1/B2: список обозримых состояний цикла
                                # [{"label": "C1", "open": {"SBERP": 8.0}}, ...] —
                                # "open" в каждом состоянии ПОЛНЫЙ набор тикеров этого
                                # состояния (не дельта к предыдущему).
    --hysteresis-pp N           # B2: порог гистерезиса в пп акционной книги для флага
                                # разворота (Rule 3, default 1.0 — ПАРАМЕТР, не константа);
                                # в --auto — ещё и порог среза И докупки (недобор ≤ порога — без сделки).
    --acted TICKER=buy|trim[,...]  # B3 (§10.3): направление уже исполненной в этом
                                # горизонте сделки. Направление ОБЯЗАТЕЛЬНО — голый
                                # TICKER без "=" ошибка. Подавляется только РАЗВОРОТ
                                # (арифметика требует противоположного направления);
                                # движение в ту же сторону разрешено. --selling
                                # признаку не подчиняется — полный выход исполняется
                                # всегда.

Лимиты концентрации (docs/investment/spec-gate-aware-sizing-trim-fix.md §9, проводка —
§11 «Волна 3») — проверка через `concentration_limits.compute_concentration` подключена
здесь же, знаменатель — фактическая книга L2_cur, НЕ база докупки (T*), это разные
вопросы (см. `references/gate-aware-sizing.md` §«Лимиты концентрации»):

    --concentration-limits FILE.yaml  # конфиг лимитов; по умолчанию
                                # references/concentration-limits.yaml рядом со скриптом.
                                # Отказ загрузки (файла нет / PyYAML недоступен / данные
                                # снапшота не годятся) НЕ прерывает сайзинг — деградация
                                # с warning'ом concentration_check_unavailable:<причина>,
                                # разбор без проверки концентрации (см. отчёт по правке).
    --sector                    # включить секторный лимит (выключен по умолчанию —
                                # поле sector в снапшоте грязное, PDL-I в TODO.md).
    --concentration-today YYYY-MM-DD  # дата для проверки истечения именованных
                                # исключений; по умолчанию — реальная дата (для тестов
                                # передавать явно, не полагаться на календарь).

Нарушение лимита блокирует ДОКУПКУ (тикер не может попасть в Open, и Rebalancing не
может развернуться в докупку), но НЕ блокирует срез — им нарушение и лечится. Нарушение
также снимает признак «сделка уже была в горизонте» (--acted) для среза: риск-лимит
старше правила неразворота.

CLI:
    python3 gate_aware_sizing.py \\
        --snapshot <путь к portfolio-<date>.json> \\
        [--decisions <Portfolio/decisions>] \\
        [--security-attrs <Portfolio/security-attrs.json>] \\
        [--conditions <Portfolio/conditions.yaml> --conditions-state <Portfolio/conditions-state.json>] \\
        [--today YYYY-MM-DD] \\
        [--open TICKER[=weight_pct][,...]] \\
        [--selling TICKER[,...]] \\
        [--trim TICKER[=weight_pct][,...]] \\
        [--blocked TICKER[,...]] \\
        [--acted TICKER=buy|trim[,...]] \\
        [--cycles FILE.json] \\
        [--hysteresis-pp N] \\
        [--concentration-limits FILE.yaml] \\
        [--sector] \\
        [--concentration-today YYYY-MM-DD] \\
        [--quotes /tmp/quotes.json] \\
        [--extra-cash-from-sales N] \\
        [--json | --text]

    # режим линта черновика перед эмиссией:
    python3 gate_aware_sizing.py --snapshot <snapshot> --lint-draft <файл с черновиком>
    # суммы, количества и целевые доли сделок в строках с действием — отдельным линтом:
    #   lint_numbers.py --draft <черновик> --sources <вывод скриптов…> (доли «довести до N %» — sizing_to_target.py)

Exit codes: 0 — успех (и для --lint-draft — черновик чист); 1 — --lint-draft нашёл
нарушения; 2 — ошибка входа (снапшот/поля/данные), сообщение без traceback.

Stdlib only для основной логики; PyYAML опционален (`try: import yaml`) — без него
условия conditions.yaml не читаются (warning `yaml_unavailable`); решения (JSON) и справочник бумаг читаются всегда.
Гейт считается модулем (б) из решений (статус по вердикту новейшего решения, истечение по review_by, пауза докупки,
IPO-пауза по справочнику, new_position у первой покупки без решения); файла гейтов нет. Причины блокировки: gate:<status>,
pending_buy_condition, sell_condition:<id>, condition_hold:<id>, ipo_gate:<q>q, add_cooldown:<дата>,
user_plan:<слово>, no_price — тексты совпадают с rebalance-engine.js (test_rebalance_parity.py).
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
from math import ceil, floor
from typing import Any

# Канонические примитивы — общий движок из _shared-references/constraint_engine.py.
# Из репо берётся из _shared-references/; в упакованном .skill — из своей scripts/
# (туда его кладёт pack.sh, и Python сам добавляет каталог скрипта в sys.path).
_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (_HERE, os.path.normpath(os.path.join(_HERE, "..", "..", "..", "_shared-references"))):
    if _cand not in sys.path:
        sys.path.insert(0, _cand)
from constraint_engine import compute_fixed_point_target  # noqa: E402
import codelists  # noqa: E402  — кодлисты, тот же путь поиска (каталог скрипта, затем _shared-references)
import conditions_merge as cm  # noqa: E402  — модуль (а): строки «определение + состояние» условий
import last_word as lw  # noqa: E402  — модуль (б): «последнее слово» и статус гейта (schema.md §3.5)

# Волна 3 проводки задачи C (§9/§11 spec-gate-aware-sizing-trim-fix.md) — лимиты
# концентрации акционной книги. concentration_limits.py лежит рядом в scripts/ (тот
# же _HERE уже в sys.path выше). Импорт НА ВЕРХНЕМ УРОВНЕ здесь безопасен, несмотря на
# то что concentration_limits.py, в свою очередь, тоже ссылается на этот модуль
# (active_stock_holdings — сведённый твин, задача 3 проводки): там этот импорт СДЕЛАН
# ЛЕНИВЫМ (внутри функции, не на верхнем уровне её файла). При любом порядке первого
# импорта обоих модулей цикл не возникает — см. docstring
# concentration_limits.active_stock_holdings.
from concentration_limits import (  # noqa: E402
    ConcentrationLimitsError,
    compute_concentration,
    load_limits_config,
)


# ─────────────────────────── константы ───────────────────────────

# Money-market фонды, классифицированные в snapshot как asset_type == "stock" — не входят
# в акционную базу (§T1 п.2 плана). Близнец этой константы — build_weekly_stock_stub.py
# (skills/ru-portfolio-advisor/scripts/build_weekly_stock_stub.py::MONEY_MARKET_TICKERS).
# Тест test_gate_aware_sizing.py сверяет два множества — расхождение не должно проходить
# незамеченным.
MONEY_MARKET_TICKERS = {"TMON", "TPAY", "LQDT", "SBMM"}

# Статусы гейта (модуль (б)), которые блокируют докупку (кодлисты maps.gate_to_block).
BLOCKING_GATE_STATUSES = set(codelists.map_("gate_to_block"))
UNDER_REVIEW = "reviewed_under_review"
AFTER_REVIEW = "после разбора бумаги"
AFTER_OWNER = "после отметки владельца"

# Слова плана владельца (user_plan, ie_actual.per_ticker), запрещающие покупку. WAIT/WAIT-TRIM —
# блокировка с причиной (разблокировать можно); KEEP/SELL (NO_BUY_DORMANT_PLANS) — «ничего»:
# нечего разблокировать, в причины блокировки не входят, в авто-режиме уходят в dormant.
EXPLICIT_NO_BUY_PLANS = {"WAIT", "WAIT/TRIM", "KEEP", "SELL"}
NO_BUY_DORMANT_PLANS = {"KEEP", "SELL"}

# Порог (₽), ниже которого дельта target-current считается float-шумом, а не сигналом
# купить/срезать (S5/§4.3 спеки trim-to-target — direction: "buy" | "trim" | "hold").
_DIRECTION_EPS = 0.5

# Порог в п.п., начиная с которого отклонение веса от плана считается значимым (§4.3 спеки).
# Применяется к ДВУМ разным величинам, см. compute_post_trade: к вкладу округления по лотам
# (→ cap_breach_after_rounding) и к структурному отклонению базы от пост-трейд книги
# (→ structural_cap_offset). Разделение — по итогам ревью 26.08.2026.
_CAP_BREACH_THRESHOLD_PP = 0.25

# Порог в п.п., ниже которого перевес факта над планом считается шумом округления долей,
# а не намерением срезать (подсказка _trim_candidate_hints). Намеренно НЕ гистерезис
# Rule 3 — обоснование в докстроке функции.
_DIRECTION_EPS_PP = 0.01

# Целевой буфер кэша в долях NAV для правила «сколько кэша нормально держать»
# (`gate-aware-sizing.md` §«Сколько кэша считать нормальным, пока часть класса под гейтами»).
# Параметризуется через --cash-buffer-pct: политика буфера может меняться, формула — нет.
_CASH_BUFFER_PCT_DEFAULT = 4.0

# Правило неразворота (§8.2 B2 spec-gate-aware-sizing-trim-fix.md, Rule 3) — гистерезис по
# умолчанию, в п.п. акционной книги. ПАРАМЕТР (--hysteresis-pp), не зашитая константа —
# тест B-T3 требует запуска с 0,4 и не пройдёт, если значение зашито в арифметику.
_DEFAULT_HYSTERESIS_PP = 1.0

# Волна 3 проводки задачи C (§9/§11 spec-gate-aware-sizing-trim-fix.md) — путь по
# умолчанию к конфигу лимитов концентрации, рядом со скиллом (тот же паттерн, что и
# поиск constraint_engine.py выше). CLI-флаг --concentration-limits переопределяет.
_DEFAULT_CONCENTRATION_LIMITS_PATH = os.path.normpath(
    os.path.join(_HERE, "..", "references", "concentration-limits.yaml")
)

# §10.3 — направления признака «сделка уже была в этом горизонте» (--acted). Ровно два —
# «buy»/«trim» отражают ЗНАК движения; «hold» как признак не нужен (нечего фиксировать —
# отсутствие движения не разворачивается).
_ACTED_DIRECTIONS = {"buy", "trim"}

# --lint-draft: запрещённая нотация (§1.1/§1.4 плана — формула и имена функций/скриптов
# никогда не выводятся в отчёт).
_FORBIDDEN_NOTATION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"T\*"), "T*"),
    (re.compile(r"T_full"), "T_full"),
    (re.compile(r"F\s*/\s*\(\s*1\s*[−-]\s*S\s*\)"), "F/(1−S)"),
    (re.compile(r"1\s*/\s*\(\s*1\s*[−-]"), "1/(1−"),
    (re.compile(r"неподвижн", re.IGNORECASE), "«неподвижн…»"),
    (re.compile(r"compute_fixed_point_target"), "compute_fixed_point_target"),
]

_PURCHASE_VERB_RE = re.compile(r"докуп|добрать|купить|нараст", re.IGNORECASE)
_RUB_SUM_RE = re.compile(r"\d[\d\s ]*\s*₽")
_BASE_MENTION_RE = re.compile(r"база докупки", re.IGNORECASE)


class GateAwareSizingError(Exception):
    """Понятная ошибка входа/данных — CLI ловит и завершается exit 2 без traceback."""


# ─────────────────────────── загрузка входов ───────────────────────────

def load_snapshot(path: str) -> dict[str, Any]:
    if not path or not os.path.exists(path):
        raise GateAwareSizingError(f"Снапшот не найден: {path!r}")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise GateAwareSizingError(f"Не удалось прочитать/распарсить снапшот {path!r}: {exc}")


def _iso_str(v: Any) -> str | None:
    """Время из YAML строкой (PyYAML разбирает ISO-время в datetime/date — модулю (б) нужна строка)."""
    if v is None or v == "":
        return None
    return v.isoformat() if hasattr(v, "isoformat") else str(v)


def load_review_rows(paths: list[str] | None) -> tuple[dict[str, list[dict]], list[str]]:
    """Строки обзоров недели акций для модуля (б) (`reviews`, форма — докстринг last_word.py): по бумаге `per_stock`
    → review_date, recorded_at (шапки обзора), advisor_verdict, …, gate_review_required (`flags.gate_review_required`),
    doc. Нужны для `review_needed` (флаг обзора новее решения). Обзор без recorded_at — warning, строки не источник."""
    rows: dict[str, list[dict]] = {}
    warnings: list[str] = []
    if not paths:
        return rows, warnings
    import yaml  # noqa: PLC0415
    for path in paths:
        if not os.path.exists(path):
            raise GateAwareSizingError(f"Обзор не найден: {path!r}")
        try:
            with open(path, encoding="utf-8") as f:
                doc = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise GateAwareSizingError(f"Не удалось прочитать обзор {path!r}: {exc}")
        rec = _iso_str(doc.get("recorded_at"))
        if not rec:
            warnings.append(f"review_without_recorded_at:{os.path.basename(path)}")
        for key, r in (doc.get("per_stock") or {}).items():
            if not isinstance(r, dict):
                continue
            rows.setdefault(key, []).append({
                "review_date": _iso_str(doc.get("review_date")), "recorded_at": rec,
                "advisor_verdict": r.get("advisor_verdict"),
                "advisor_verdict_confidence": r.get("advisor_verdict_confidence"),
                "advisor_verdict_basis": r.get("advisor_verdict_basis"),
                "gate_review_required": (r.get("flags") or {}).get("gate_review_required") is True,
                "doc": os.path.basename(path)})
    return rows, warnings


def load_gate_inputs(decisions_dir: str | None, attrs_path: str | None,
                     reviews_paths: list[str] | None = None) -> tuple[dict[str, Any] | None, list[str]]:
    """Входы модуля (б): решения папки (только прошедшие валидатор decision@1; остальные — warning
    `invalid_decision:<файл>`), справочник бумаг и строки обзоров недели акций (`--reviews`, для `review_needed`).
    Ничего не задано — (None, []): гейта нет ни у одной бумаги."""
    if not decisions_dir and not attrs_path and not reviews_paths:
        return None, []
    import decisions_read as dr  # noqa: PLC0415 — общий модуль (в .skill — рядом, pack.sh по импорту)
    warnings: list[str] = []
    decisions: list[dict[str, Any]] = []
    if decisions_dir:
        if not os.path.isdir(decisions_dir):
            raise GateAwareSizingError(f"Папка решений не найдена: {decisions_dir!r}")
        decisions, invalid = dr.load_dir(decisions_dir)
        warnings += [f"invalid_decision:{x['file']}" for x in invalid]
    attrs = None
    if attrs_path:
        if not os.path.exists(attrs_path):
            raise GateAwareSizingError(f"Справочник бумаг не найден: {attrs_path!r}")
        try:
            with open(attrs_path, encoding="utf-8") as f:
                attrs = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise GateAwareSizingError(f"Не удалось прочитать справочник бумаг {attrs_path!r}: {exc}")
    reviews, rw = load_review_rows(reviews_paths)
    return {"decisions": decisions, "security_attrs": attrs, "reviews": reviews}, warnings + rw


def load_trade_inputs(snapshot_path: str, as_of: Any = None) -> dict[str, Any]:
    """Сделки и правки плана для паузы докупки (правило 7 модуля (б)) и неразворота «Сейчас» (§10.6 п.6): история
    снапшотов той же папки, что `--snapshot` (не позже его даты) — decisions_read.trade_times; журнал плана
    `../plan-journal.jsonl` рядом с папкой снапшотов — decisions_read.plan_changed_at. Нет файлов — пустые словари
    (паузы и неразворота тогда нет)."""
    import decisions_read as dr  # noqa: PLC0415
    folder = os.path.dirname(os.path.abspath(snapshot_path))
    try:
        paths = [os.path.join(folder, n) for n in os.listdir(folder)]
    except OSError:
        paths = []
    out = dr.trade_times(paths, str(as_of)[:10] if as_of else None)
    out["plan_changed_at"] = dr.plan_changed_at(os.path.join(os.path.dirname(folder), "plan-journal.jsonl"))
    return out


def load_conditions_inputs(defs_path: str | None, state_path: str | None) -> tuple[dict[str, Any] | None, list[str]]:
    """Входы модуля (а): определения conditions@2 (даты строками) + состояние conditions-state@1.
    Определений нет — (None, []); формат не conditions@2 — ошибка; без состояния — событий нет (warning)."""
    if not defs_path:
        return None, []
    try:
        import yaml  # noqa: F401,PLC0415
    except ImportError:
        return None, ["yaml_unavailable"]
    if not os.path.exists(defs_path):
        raise GateAwareSizingError(f"Файл не найден: {defs_path!r}")
    try:
        doc = cm.load_yaml(defs_path)
    except Exception as exc:  # noqa: BLE001 — любая ошибка парсинга YAML понятна пользователю
        raise GateAwareSizingError(f"Не удалось распарсить YAML {defs_path!r}: {exc}")
    if not isinstance(doc, dict) or doc.get("schema_version") != "conditions@2":
        sv = doc.get("schema_version") if isinstance(doc, dict) else None
        raise GateAwareSizingError(f"{defs_path!r}: формат {sv!r}, нужен conditions@2")
    warnings: list[str] = []
    state: dict[str, Any] = {"events": []}
    if state_path:
        try:
            with open(state_path, encoding="utf-8") as f:
                state = json.load(f) or {"events": []}
        except (OSError, json.JSONDecodeError) as exc:
            raise GateAwareSizingError(f"Не удалось прочитать состояние условий {state_path!r}: {exc}")
    else:
        warnings.append("conditions_state_missing")
    return {"defs": doc.get("conditions") or [], "state": state}, warnings


def get_nav_and_class_row(snapshot: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    """nav_excl_iis + строка {'Валюта': 'RUB', 'Бумага': 'Акция'} из balance_summary.goals_matrix.

    Пути проверены на portfolio-2026-08-19.json (§T1 п.1 плана). Отсутствующее поле —
    понятная ошибка и exit 2; похожее по имени поле НЕ подставляется (история дефекта —
    rpa-17-field-paths-audit.md).
    """
    bs = snapshot.get("balance_summary")
    if not isinstance(bs, dict):
        raise GateAwareSizingError("В снапшоте нет balance_summary (объекта) — проверь путь/версию снапшота")

    nav = bs.get("total_current_rub_excl_iis")
    if not isinstance(nav, (int, float)):
        raise GateAwareSizingError(
            "В balance_summary нет числового total_current_rub_excl_iis — не подставляю похожее поле"
        )

    goals_matrix = bs.get("goals_matrix")
    if not isinstance(goals_matrix, list):
        raise GateAwareSizingError("В balance_summary нет списка goals_matrix — проверь путь/версию снапшота")

    for row in goals_matrix:
        if isinstance(row, dict) and row.get("Валюта") == "RUB" and row.get("Бумага") == "Акция":
            return float(nav), row

    raise GateAwareSizingError(
        "В balance_summary.goals_matrix нет строки {'Валюта': 'RUB', 'Бумага': 'Акция'} — "
        "не подставляю похожее поле (история дефекта — rpa-17-field-paths-audit.md)"
    )


def active_stock_holdings(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """holdings[] c asset_type == 'stock', за вычетом cost_basis (замороженные US),
    is_blocked и money-market фондов (§T1 п.2)."""
    holdings = snapshot.get("holdings")
    if not isinstance(holdings, list):
        raise GateAwareSizingError("В снапшоте нет списка holdings — проверь путь/версию снапшота")
    out = []
    for h in holdings:
        if not isinstance(h, dict) or h.get("asset_type") != "stock":
            continue
        if h.get("current_price_source") == "cost_basis":
            continue
        if h.get("is_blocked"):
            continue
        if h.get("ticker") in MONEY_MARKET_TICKERS:
            continue
        out.append(h)
    return out


def all_stock_tickers(snapshot: dict[str, Any]) -> set[str]:
    """Все тикеры с asset_type == 'stock' в снапшоте, БЕЗ фильтров — для --lint-draft
    (§T1 п.8: «тикер, который в снапшоте — акция», фильтры фактической книги здесь не при чём)."""
    holdings = snapshot.get("holdings")
    if not isinstance(holdings, list):
        return set()
    return {h["ticker"] for h in holdings if isinstance(h, dict) and h.get("asset_type") == "stock" and h.get("ticker")}


# ─────────────────────────── классификация ───────────────────────────

def _parse_manual_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [t.strip().upper() for t in raw.split(",") if t.strip()]


def _parse_open_arg(raw: str | None) -> dict[str, float | None]:
    """'RENI=11,MBNK,X5=5.5' → {'RENI': 11.0, 'MBNK': None, 'X5': 5.5}."""
    out: dict[str, float | None] = {}
    for token in _parse_manual_list(raw):
        if "=" in token:
            ticker, weight = token.split("=", 1)
            ticker = ticker.strip().upper()
            out[ticker] = float(weight.strip())
        else:
            out[token] = None
    return out


def _parse_acted_arg(raw: str | None) -> dict[str, str]:
    """'SBERP=trim,MBNK=buy' → {'SBERP': 'trim', 'MBNK': 'buy'} (§10.3 задания B —
    признак направленный). Направление ОБЯЗАТЕЛЬНО: голый токен без '=' — понятная
    ошибка (exit 2 без traceback), а не молчаливое игнорирование. НЕ переиспользует
    `_parse_manual_list` — тот аплкейсит весь токен целиком, что сломало бы регистр
    направления ('trim' → 'TRIM')."""
    out: dict[str, str] = {}
    if not raw:
        return out
    for token in (t.strip() for t in raw.split(",") if t.strip()):
        if "=" not in token:
            raise GateAwareSizingError(
                f"--acted {token!r}: направление обязательно — передай "
                f"{token}=buy или {token}=trim, голый тикер не принимается"
            )
        ticker, direction = token.split("=", 1)
        ticker = ticker.strip().upper()
        direction = direction.strip().lower()
        if direction not in _ACTED_DIRECTIONS:
            raise GateAwareSizingError(
                f"--acted {ticker}={direction!r}: направление должно быть "
                f"'buy' или 'trim'"
            )
        out[ticker] = direction
    return out


def _qty_pos(h: dict[str, Any]) -> bool:
    """Бумага в портфеле для модуля (б) (как lwCtx вьюера: количество > 0). Записи без поля qty (синтетические
    фикстуры) считаются держимыми; явное qty ≤ 0 — нет."""
    if h.get("qty") is None:
        return True
    try:
        return float(h["qty"]) > 0
    except (TypeError, ValueError):
        return True


NO_REVERSAL_DAYS = int(codelists.defaults()["no_reversal_days"])
HORIZON_DAYS = int(codelists.defaults()["known_dates_horizon_days"])


class GateContext:
    """Гейт и условия одного прогона (ЗЕРКАЛО gateContext в rebalance-engine.js).

    gate_inputs = {"decisions": [decision@1], "security_attrs": security-attrs@1, "reviews": {ключ: [строка обзора]}}
    — карточки модуля (б) `last_word.card` по тикеру (лениво); conditions = {"defs": [определения conditions@2],
    "state": conditions-state@1} — строки модуля (а) `conditions_merge.merge` на today (по умолчанию as_of_date
    снапшота). Первая покупка — строки holdings с first_buy, бумаги снапшота — остальные, акции — asset_type stock."""

    def __init__(self, snapshot: dict[str, Any], gate_inputs: dict[str, Any] | None,
                 conditions: dict[str, Any] | None, today: str | None = None, ai_mode: str = "on"):
        self.today = today or str(snapshot.get("as_of_date") or "")[:10]
        gi = gate_inputs or {}
        holds = [h for h in snapshot.get("holdings") or [] if isinstance(h, dict) and h.get("ticker")]
        # сделки по истории снапшотов и правки плана (необязательные входы gate_inputs; считает вызывающий —
        # decisions_read.trade_times / plan_changed_at, во вьюере dsLastTradeAt / журнал плана): пауза докупки модуля (б)
        # (правило 7) и неразворот «Сейчас» (§10.6 п.6). Нет входа — паузы и неразворота нет.
        self.last_buy_at = gi.get("last_buy_at") or {}
        self.last_sell_at = gi.get("last_sell_at") or {}
        self.plan_changed_at = gi.get("plan_changed_at") or {}
        self.decisions = gi.get("decisions") or []
        self._ctx = {
            "today": self.today, "decisions": self.decisions, "reviews": gi.get("reviews") or {},
            "security_attrs": gi.get("security_attrs"),
            # как lwCtx вьюера: бумага в портфеле — количество > 0
            "snapshot_keys": sorted({h["ticker"] for h in holds if not h.get("first_buy") and _qty_pos(h)}),
            "stock_keys": sorted({h["ticker"] for h in holds if h.get("asset_type") == "stock"}),
            "first_buy": sorted({h["ticker"] for h in holds if h.get("first_buy")}),
            "ai_mode": ai_mode,
        }
        for k in ("last_buy_at", "last_sell_at", "last_trade_at", "buys_at"):
            if gi.get(k) is not None:
                self._ctx[k] = gi[k]
        self.rows = (cm.merge(conditions.get("defs") or [], conditions.get("state") or {"events": []}, self.today)
                     if conditions else [])
        self._cards: dict[str, dict[str, Any]] = {}

    def card(self, ticker: str) -> dict[str, Any]:
        if ticker not in self._cards:
            self._cards[ticker] = lw.card(self._ctx, ticker)
        return self._cards[ticker]

    def card_on(self, ticker: str, day: str) -> dict[str, Any]:
        """Карточка модуля (б) на другую дату (горизонт известных дат: гейт на день снятия блокировки)."""
        return lw.card(dict(self._ctx, today=day), ticker)

    def cond_rows(self, ticker: str) -> list[dict[str, Any]]:
        return [c for c in self.rows if c["key"] == ticker and c["active"]]


def _pending_buy_condition_for(ticker: str, ctx: GateContext) -> dict[str, Any] | None:
    """Действующее условие (строка модуля (а): pending или fired — «ждёт владельца»), чей on_trigger.verdict == BUY:
    докупка ждёт условия (детерминированный сигнал, без интерпретации текста)."""
    for c in ctx.cond_rows(ticker):
        if c.get("verdict_on_trigger") == "BUY":
            return c
    return None


def _condition_unblock_by(condition: dict[str, Any]) -> str:
    """Строка модуля (а): сработавшее ждёт отметки владельца (или отсрочки); ожидающее — своего триггера."""
    if condition.get("status") == cm.FIRED:
        return str(condition["deferred_until"]) if condition.get("deferred_until") else AFTER_OWNER
    trigger = condition.get("trigger") or {}
    ttype = trigger.get("type")
    value = trigger.get("value")
    if ttype == "date" and value:
        return str(value)
    if ttype == "report_published" and trigger.get("window_end"):
        return str(trigger["window_end"])   # окно отчётности (+3 дня)
    if ttype == "price_above" and value is not None:
        return f"цена ≥ {value} ₽"
    if ttype == "price_below" and value is not None:
        return f"цена ≤ {value} ₽"
    return "бессрочно"


def classify_stocks(
    holdings: list[dict[str, Any]],
    per_ticker: dict[str, Any],
    ctx: GateContext,
    open_overrides: dict[str, float | None],
    selling_tickers: list[str],
    blocked_overrides: list[str],
    trim_overrides: dict[str, float | None],
    concentration_reason_by_ticker: dict[str, str] | None = None,
    hold_weights: dict[str, float] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """Возвращает ({'open': [...], 'blocked': [...], 'dormant': [...], 'selling': [...],
    'rebalancing': [...]}, warnings).

    Пятая категория — Rebalancing (docs/investment/spec-gate-aware-sizing-trim-fix.md §4.1):
    срез до ОПРЕДЕЛЁННОЙ плановой доли, а не полный выход. Вне `F` (в отличие от Dormant —
    после исполнения позиция ещё не на таргете, она к нему только идёт), но, как и Open,
    участвует в `S` со своим `w_i` — арифметика в compute_sizing не различает Open и
    Rebalancing, кроме знака ожидаемой дельты.

    Приоритет при пересечении ручных множеств: Selling > Rebalancing > Open > остальное —
    полный выход старше частичного среза, явное решение аналитика сильнее автоклассификации
    (§T1 п.4; §4.3 спеки trim-fix). Тикер и в --trim, и в --selling → Selling, с warning
    (полный выход не должен молча выигрывать без объяснения — 5.4 в спеке).

    `concentration_reason_by_ticker` (§9/§11 «Волна 3» spec-gate-aware-sizing-trim-fix.md) —
    {ticker: "concentration_breach:<группа>"} для тикеров с нарушением лимита концентрации
    (по compute_concentration, знаменатель — фактическая книга L2_cur). Нарушение лимита
    блокирует Open СИЛЬНЕЕ, чем автоклассификация (gate/pending/IPO/user_plan): те
    --open ПЕРЕБИВАЕТ (manual_unblock), а лимит концентрации — нет, ручным флагом риск-лимит
    не обходится. `--trim` (Rebalancing) этой проверке не подчиняется вообще — срез это и
    есть лечение нарушения, блокировать движение ВНИЗ нельзя (§9.2); возможный разворот
    среза в докупку у уже нарушающей лимит бумаги гасится позже, в run_sizing, после того
    как арифметика посчитает цель (см. compute_sizing/apply_acted_guard)."""
    warnings: list[str] = []
    selling_set = set(selling_tickers)
    blocked_manual_set = set(blocked_overrides)
    trim_set = set(trim_overrides)

    open_list: list[dict[str, Any]] = []
    blocked_list: list[dict[str, Any]] = []
    dormant_list: list[dict[str, Any]] = []
    selling_list: list[dict[str, Any]] = []
    rebalancing_list: list[dict[str, Any]] = []

    for h in holdings:
        ticker = h["ticker"]
        current_rub = float(h.get("value_rub") or 0.0)
        row = per_ticker.get(ticker) or {}
        real_pct = row.get("real_share_pct")
        planned_pct = row.get("planned_share_pct")
        ie_pct = row.get("ie_new_pct")

        if ticker in selling_set:
            if ticker in trim_set:
                warnings.append(f"trim_overridden_by_selling:{ticker}")
            selling_list.append({"ticker": ticker, "current_rub": current_rub})
            continue

        if ticker in trim_set:
            override_weight = trim_overrides[ticker]
            if override_weight is not None:
                weight_pct, weight_source = override_weight, "override"
            elif planned_pct is not None:
                weight_pct, weight_source = planned_pct, "planned"
            elif ie_pct is not None:
                weight_pct, weight_source = ie_pct, "ie"
                warnings.append(f"weight_fallback_ie:{ticker}")
            else:
                raise GateAwareSizingError(
                    f"{ticker}: нет веса для --trim — planned_share_pct и ie_new_pct оба "
                    f"null, и не передан --trim {ticker}=<weight_pct>"
                )
            rebalancing_list.append({
                "ticker": ticker, "weight_pct": weight_pct, "weight_source": weight_source,
                "current_rub": current_rub,
            })
            continue

        if ticker in open_overrides:
            conc_reason = (concentration_reason_by_ticker or {}).get(ticker)
            if conc_reason is not None:
                # §9.2/§9.3 spec-gate-aware-sizing-trim-fix.md — нарушение лимита
                # концентрации СИЛЬНЕЕ явного --open: в отличие от gate/pending/IPO/
                # user_plan (которые --open преодолевает с manual_unblock), риск-лимит
                # ручным флагом не обходится. Тикер уходит в Blocked, а не в Open —
                # арифметика S/T* его не видит вовсе, как и любой другой Blocked.
                warnings.append(f"open_override_blocked_by_concentration:{ticker}")
                blocked_list.append({
                    "ticker": ticker,
                    "current_rub": current_rub,
                    "reason": conc_reason,
                    "unblock_by": "после среза до лимита концентрации",
                    "plan_weight_pct": planned_pct,
                })
                continue

            override_weight = open_overrides[ticker]
            if override_weight is not None:
                weight_pct, weight_source = override_weight, "override"
            elif planned_pct is not None:
                weight_pct, weight_source = planned_pct, "planned"
            elif ie_pct is not None:
                weight_pct, weight_source = ie_pct, "ie"
                warnings.append(f"weight_fallback_ie:{ticker}")
            else:
                raise GateAwareSizingError(
                    f"{ticker}: нет веса — planned_share_pct и ie_new_pct оба null, "
                    f"и не передан --open {ticker}=<weight_pct>"
                )

            auto_reasons = _blocking_reasons(h, row, ctx)
            target_not_achieved = real_pct is not None and real_pct < weight_pct
            would_be_auto_blocked = target_not_achieved and bool(auto_reasons)
            if would_be_auto_blocked or ticker in blocked_manual_set:
                # Решение аналитика (--open) сильнее автоклассификации — тикер остаётся Open,
                # но снятие блокировки не проходит молча (§T1 п.4).
                warnings.append(f"manual_unblock:{ticker}")

            open_list.append({
                "ticker": ticker,
                "weight_pct": weight_pct,
                "weight_source": weight_source,
                "current_rub": current_rub,
                # Чем именно решение аналитика перебило автоклассификацию (для отчёта).
                "overridden_block_reason": "; ".join(auto_reasons) if would_be_auto_blocked else None,
            })
            continue

        # Автоклассификация Blocked/Dormant — те же причины, что у авто-режима (§10.6 п.3): гейт, условия на покупку,
        # условия с продажей или «держать» (_auto_stop_condition), IPO, пауза, план, лимит эмитента.
        weight_pct = planned_pct if planned_pct is not None else ie_pct
        target_not_achieved = real_pct is not None and weight_pct is not None and real_pct < weight_pct
        stop = _auto_stop_condition(ticker, ctx)
        reasons = _merge_stop_reason(_blocking_reasons(h, row, ctx), stop)
        conc_reason = (concentration_reason_by_ticker or {}).get(ticker)
        if not reasons and conc_reason is not None:
            reasons = [conc_reason]
        is_manual_blocked = ticker in blocked_manual_set

        if target_not_achieved and (reasons or is_manual_blocked):
            reason_text = "; ".join(reasons) if reasons else "manual:--blocked"
            unblock_by = ("после среза до лимита концентрации" if reasons == [conc_reason]
                          else _unblock_by(h, row, ctx, stop))
            blocked_list.append({
                "ticker": ticker,
                "current_rub": current_rub,
                "reason": reason_text,
                "unblock_by": unblock_by,
                "plan_weight_pct": planned_pct,
            })
        else:
            item = {"ticker": ticker, "current_rub": current_rub, "plan_weight_pct": planned_pct,
                    "user_plan": row.get("user_plan")}
            if ticker in (hold_weights or {}):
                # «держать» (авто-режим): операций нет, но плановый вес входит в S, деньги — не в F
                item["base_weight_pct"] = float(hold_weights[ticker])
            dormant_list.append(item)

    return (
        {
            "open": open_list, "blocked": blocked_list, "dormant": dormant_list,
            "selling": selling_list, "rebalancing": rebalancing_list,
        },
        warnings,
    )


def _blocking_reasons(h: dict[str, Any], row: dict[str, Any], ctx: GateContext) -> list[str]:
    """Причины блокировки докупки (ЗЕРКАЛО blockingReasons): гейт модуля (б) (gate:<status>) → условие на покупку
    (pending_buy_condition) → IPO-пауза и пауза докупки модуля (б) (ipo_gate:<q>q, add_cooldown:<дата>) → слово
    плана (user_plan:<слово>) → нет цены у первой покупки (no_price)."""
    gr = ctx.card(h["ticker"])["gate"]["reasons"]
    reasons = [r for r in gr if r.startswith("gate:")]
    if _pending_buy_condition_for(h["ticker"], ctx) is not None:
        reasons.append("pending_buy_condition")
    reasons += [r for r in gr if not r.startswith("gate:")]
    plan = row.get("user_plan")
    if plan in EXPLICIT_NO_BUY_PLANS and plan not in NO_BUY_DORMANT_PLANS:
        reasons.append(f"user_plan:{plan}")
    if h.get("first_buy") and not h.get("current_price"):
        reasons.append("no_price")
    return reasons


def _merge_stop_reason(reasons: list[str], stop: tuple[str, dict[str, Any]] | None) -> list[str]:
    """Порядок причин: гейт → условия → IPO и пауза докупки → план; код стоп-условия идёт после
    gate:/pending_buy_condition (зеркало mergeStopReason во вьюере)."""
    if stop is None:
        return reasons
    code = f"{stop[0]}:{stop[1].get('id')}"
    out: list[str] = []
    put = False
    for r in reasons:
        if not put and not (r.startswith("gate:") or r == "pending_buy_condition"):
            out.append(code)
            put = True
        out.append(r)
    if not put:
        out.append(code)
    return out


def _unblock_by(
    h: dict[str, Any], row: dict[str, Any], ctx: GateContext,
    stop: tuple[str, dict[str, Any]] | None = None,
) -> str:
    """Когда снимется блокировка (ЗЕРКАЛО unblockBy): гейт — срок решения у «на пересмотре», иначе «после разбора
    бумаги»; условие — его триггер или отметка владельца; IPO-пауза и пауза докупки — их дата."""
    g = ctx.card(h["ticker"])["gate"]
    if any(r.startswith("gate:") for r in g["reasons"]):   # гейт блокирует; в режиме «без ИИ» срок — предупреждение
        return g["expires_on"] if g["status"] == UNDER_REVIEW and g["expires_on"] else AFTER_REVIEW
    pending = _pending_buy_condition_for(h["ticker"], ctx)
    if pending is not None:
        return _condition_unblock_by(pending)
    if stop is not None:
        return _condition_unblock_by(stop[1])
    if g["ipo_pause_until"]:
        return g["ipo_pause_until"]
    if g["add_cooldown_until"]:
        return g["add_cooldown_until"]
    if h.get("first_buy") and not h.get("current_price"):
        return "когда появится цена"
    return "бессрочно"


# ─────────────────────────── расчёт базы ───────────────────────────

def compute_sizing(
    classification: dict[str, list[dict[str, Any]]],
    class_plan_rub: float,
    extra_cash_from_sales: float,
    horizon: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Rebalancing участвует в `S` наравне с Open (docs/investment/spec-gate-aware-sizing-trim-fix.md
    §4.3): `sized = open + rebalancing`, единый `open_weights` для compute_fixed_point_target —
    никакой отдельной ветки арифметики для тримов нет, знак дельты определяется позже.

    База непрерывная (§10.6, решение владельца 11.11): T* = F / (1 − S) при любом составе F — заблокированные и
    спящие (в коридоре, «держать») одинаково своими рублями, с пределом плана класса; только если в F ничего нет
    (всё движется к плану) — база = план класса (`t_full_no_gates`). Книга после исполнения = база: деньги до плана
    класса идут лишь в бумаги, которые докупаются сейчас, и лишь до их плановой доли базы.

    Замороженная бумага выше плана — в F своими рублями, как любая неторгуемая (§10.7: правило «на плане» §10.3а
    отменено в пользу инварианта «база = книга после исполнения»).

    `horizon` ({тикер: вес %}, только авто-режим, §10.6 п.7): заблокированные бумаги с недобором, блокировка которых
    снимается в горизонте известных дат, — для базы СРЕЗОВ считаются открытыми (вес в S, рубли не в F); сегодня не
    покупаются. Срезы считаются от `base_trim_rub`, докупки — от обычной базы.

    Разрыв до плана класса (план − база) раскладывается на три слагаемых (§10.6 п.4; при fixed_point
    (1 − S)·(план − база) = Σ_F(w·план − c) + нераспределённая доля·план): `gap_gated_rub` — недобор
    заблокированных до своей доли плана, `gap_in_corridor_rub` — недобор (со знаком) спящих бумаг (в коридоре,
    «держать»), `gap_unallocated_rub` — доля плана, не распределённая по бумагам (Σ плановых долей < 100 %);
    каждое делено на (1 − S). Сумма = план − база; при пределе и «в F ничего нет» — нули."""
    blocked_sum = sum(x["current_rub"] for x in classification["blocked"])
    # весь dormant (и «держать» в коридоре) — в F своими рублями: бумага не торгуется, её вес в S не входит
    dormant_sum = sum(x["current_rub"] for x in classification["dormant"])

    sized = classification["open"] + classification["rebalancing"]
    open_weights = {x["ticker"]: (x["weight_pct"] or 0.0) / 100.0 for x in sized}
    s_breakdown = {
        "open": [{"ticker": x["ticker"], "weight_pct": x["weight_pct"]} for x in classification["open"]],
        "rebalancing": [{"ticker": x["ticker"], "weight_pct": x["weight_pct"]} for x in classification["rebalancing"]],
    }

    def _solve(weights: dict[str, float], blocked: float) -> dict[str, Any]:
        try:
            return compute_fixed_point_target(
                blocked_sum=blocked, dormant_sum=dormant_sum,
                open_weights=weights, extra_cash_from_sales=extra_cash_from_sales,
                t_full=class_plan_rub, full_plan_without_gates=False,
            )
        except ValueError as exc:
            raise GateAwareSizingError(str(exc))

    warnings: list[str] = []
    r = _solve(open_weights, blocked_sum)

    def _base(rr: dict[str, Any]) -> tuple[float | None, str]:
        if rr["near_degenerate"]:
            return None, "manual_check_required"
        if rr["degenerate"]:
            return class_plan_rub, "t_full_no_gates"
        return rr["T_star"], ("fixed_point_capped" if rr.get("capped") else "fixed_point")

    base_rub, base_source = _base(r)
    if base_rub is None:
        warnings.append("near_degenerate_manual_check")

    # горизонт известных дат (авто-режим): база срезов — как будто бумаги, открывающиеся в горизонте, уже открыты
    horizon = {t: w for t, w in (horizon or {}).items()
               if any(x["ticker"] == t for x in classification["blocked"])}
    base_trim_rub = None
    if horizon and base_rub is not None and classification["rebalancing"]:
        hw = dict(open_weights)
        hw.update({t: float(w) / 100.0 for t, w in horizon.items()})
        hb = blocked_sum - sum(x["current_rub"] for x in classification["blocked"] if x["ticker"] in horizon)
        try:
            rh = _solve(hw, hb)
        except GateAwareSizingError:
            rh = None
        if rh is not None and not rh["near_degenerate"]:
            base_trim_rub = _base(rh)[0]

    targets: dict[str, float] = {}
    if base_rub is not None:
        reb = {x["ticker"] for x in classification["rebalancing"]}
        for ticker, w in open_weights.items():
            targets[ticker] = w * (base_trim_rub if (base_trim_rub is not None and ticker in reb) else base_rub)

    # разложение разрыва до плана класса (§10.6 п.4)
    gap = {"gap_gated_rub": None, "gap_in_corridor_rub": None, "gap_unallocated_rub": None}
    if base_rub is not None:
        total = class_plan_rub - base_rub
        if base_source == "fixed_point":
            k = 1.0 - r["S"]
            def _def(items: list[dict[str, Any]]) -> float:
                return sum((x.get("plan_weight_pct") or 0.0) / 100.0 * class_plan_rub - x["current_rub"]
                           for x in items)
            gated = _def(classification["blocked"]) / k
            corridor = _def(classification["dormant"]) / k
            gap = {"gap_gated_rub": gated, "gap_in_corridor_rub": corridor,
                   "gap_unallocated_rub": total - gated - corridor}
        else:
            gap = {"gap_gated_rub": 0.0, "gap_in_corridor_rub": 0.0, "gap_unallocated_rub": total}

    return {
        "base_rub": base_rub,
        "base_source": base_source,
        "base_trim_rub": base_trim_rub,
        "horizon": sorted(horizon) if base_trim_rub is not None else [],
        "s_open": r["S"],
        "s_breakdown": s_breakdown,
        "targets": targets,
        "cash_available_for_open": r["cash_available_for_open"],
        "warnings": warnings,
        **gap,
    }


# ─────────────────────────── правило неразворота (задача B) ───────────────────────────

def apply_acted_guard(
    classification: dict[str, list[dict[str, Any]]],
    acted: dict[str, str],
    class_plan_rub: float,
    extra_cash_from_sales: float,
    concentration_forced_trim: set[str] | None = None,
    horizon: dict[str, float] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any], list[str], int]:
    """§10.3 задания B (docs/investment/spec-gate-aware-sizing-trim-fix.md) — направленное
    правило неразворота, итеративное подавление. §8.2 B3 из постановки ОТМЕНЁН этой
    поправкой: замораживать тикер независимо от направления НЕЛЬЗЯ. Движение в ту же
    сторону, что и `acted[ticker]`, разрешено без ограничений; подавляется ТОЛЬКО
    развернувшийся тикер — арифметика (после уже применённых на этом проходе подавлений)
    предписывает направление, противоположное ранее исполненному. Подавленный тикер
    принудительно переводится в Dormant: его текущая сумма возвращается в `F`, вес
    убирается из `S`, база (`T*`) пересчитывается заново — и так по кругу, пока
    множество конфликтов не опустеет.

    `--selling` признаку не подчиняется вообще: полный выход исполняется через
    отдельную ветку classify_stocks и никогда не попадает в `classification["open"]`/
    `["rebalancing"]`, а значит этот цикл его не видит — приоритет Selling соблюдён
    без дополнительного кода.

    `concentration_forced_trim` (§9.2 spec-gate-aware-sizing-trim-fix.md, задача 2
    проводки §11 «Волна 3») — тикеры с нарушением лимита концентрации (по
    `compute_concentration`). Нарушение лимита — существенное основание в терминах
    правила неразворота и СТАРШЕ его: если по такому тикеру арифметика требует среза
    (`direction == "trim"`), а `acted[ticker] == "buy"` (недавно докупался), обычное
    подавление реверса НЕ применяется — срез, которого требует риск-лимит, не
    замораживается прошлой покупкой. Работает только в сторону "trim": если, наоборот,
    арифметика для нарушающего лимит тикера требует "buy" (см. §9.2 «важное следствие» —
    докупка при нарушении лимита запрещена в принципе), это гасится ОТДЕЛЬНО, после
    сходимости этого цикла (run_sizing капает цель на current_rub) — сюда это не
    относится.

    Сходимость (доказательство владельца, §10.3): перевод «покупаемого» тикера
    (c < w·T*, что и означает «арифметика предписывает докупку») из S в F строго
    уменьшает новую базу — из c < w·T* следует (F+c)/(1−S+w) < F/(1−S) = T*.
    Множество подвижных тикеров (`open` ∪ `rebalancing`) на каждом проходе, где
    что-то подавляется, строго сжимается минимум на один элемент — цикл не может
    пройти больше проходов, чем исходный размер этого множества. `iteration_limit`
    ниже равен этой оценке; при корректной реализации он не должен срабатывать —
    если сработал, это баг (либо противоречивый вход), поэтому явный warning, а не
    тихий выход из цикла.

    Возвращает (classification (копия списков, с перемещёнными в dormant позициями),
    финальный sizing (compute_sizing на сошедшейся классификации), warnings,
    число выполненных проходов)."""
    classification = {k: list(v) for k, v in classification.items()}
    warnings: list[str] = []
    concentration_forced_trim = concentration_forced_trim or set()

    if not acted:
        sizing = compute_sizing(classification, class_plan_rub, extra_cash_from_sales, horizon=horizon)
        return classification, sizing, warnings, 0

    iteration_limit = len(classification["open"]) + len(classification["rebalancing"])
    iterations = 0
    sizing = compute_sizing(classification, class_plan_rub, extra_cash_from_sales, horizon=horizon)

    while True:
        if sizing["base_rub"] is None:
            # near_degenerate/иное — направление считать не от чего, оставляем как есть.
            break

        to_suppress: list[tuple[str, dict[str, Any]]] = []
        for category in ("open", "rebalancing"):
            for item in classification[category]:
                acted_dir = acted.get(item["ticker"])
                if acted_dir is None:
                    continue
                target = sizing["targets"].get(item["ticker"])
                if target is None:
                    continue
                delta = target - item["current_rub"]
                direction = _direction_for(category, delta)
                if direction in ("buy", "trim") and direction != acted_dir:
                    if direction == "trim" and item["ticker"] in concentration_forced_trim:
                        # §9.2 — риск-лимит старше правила неразворота: срез, который
                        # арифметика требует по нарушающему лимит тикеру, не подавляется
                        # прошлым --acted TICKER=buy.
                        continue
                    to_suppress.append((category, item))

        if not to_suppress:
            break

        iterations += 1
        if iterations > iteration_limit:
            warnings.append(f"acted_reversal_iteration_limit_exceeded:{iterations}")
            break

        for category, item in to_suppress:
            classification[category].remove(item)
            classification["dormant"].append(
                {"ticker": item["ticker"], "current_rub": item["current_rub"]}
            )
            warnings.append(f"acted_reversal_suppressed:{item['ticker']}")

        sizing = compute_sizing(classification, class_plan_rub, extra_cash_from_sales, horizon=horizon)

    return classification, sizing, warnings, iterations


# ─────────────────────────── направление сделки ───────────────────────────

def _direction_for(category: str, delta_rub: float | None) -> str | None:
    """"buy" | "trim" | "hold" | None (delta_rub is None — цель не досчитана).

    "trim" присваивается ТОЛЬКО категории Rebalancing (S5, решение владельца сверх спеки
    docs/investment/spec-gate-aware-sizing-trim-fix.md): тикер из --open с отрицательной
    дельтой получает "hold" и сохраняет старую формулировку «уже на цели или выше, докупка
    не требуется» — продажу для него аналитик не заказывал, предписывать её нельзя.
    Rebalancing с положительной дельтой (редкий случай — цель среза выросла выше текущей
    позиции, см. S3) получает "buy": направление определяется знаком дельты, а не тем, что
    тикер когда-то был помечен на срез."""
    if delta_rub is None:
        return None
    if delta_rub > _DIRECTION_EPS:
        return "buy"
    if delta_rub < -_DIRECTION_EPS and category == "rebalancing":
        return "trim"
    return "hold"


def _sign(x: float) -> int:
    """-1/0/1 с тем же порогом шума, что и _direction_for (_DIRECTION_EPS) — иначе
    float-дребезг около нуля даёт ложное направление там, где движения фактически нет."""
    if x > _DIRECTION_EPS:
        return 1
    if x < -_DIRECTION_EPS:
        return -1
    return 0


# ───────────────── правило неразворота: диапазон целей по циклам (B1/B2) ─────────────────

def load_cycles_file(path: str | None) -> list[dict[str, Any]]:
    """--cycles FILE.json (B1, §8.2 spec-gate-aware-sizing-trim-fix.md) — список обозримых
    состояний цикла: [{"label": "C1", "open": {"SBERP": 8.0}}, ...]. "open" в каждом
    состоянии — ПОЛНЫЙ набор тикеров, движущихся к таргету в этом состоянии (не дельта
    к предыдущему): compute_cycle_targets ниже сам вычисляет F каждого состояния как
    «книга минус этот набор», предыдущее состояние ему не нужно."""
    if not path:
        return []
    if not os.path.exists(path):
        raise GateAwareSizingError(f"Файл циклов не найден: {path!r}")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise GateAwareSizingError(f"Не удалось прочитать/распарсить --cycles {path!r}: {exc}")
    if not isinstance(data, list):
        raise GateAwareSizingError(f"--cycles {path!r}: ожидается JSON-список состояний")
    for i, state in enumerate(data):
        if not isinstance(state, dict) or "label" not in state or "open" not in state:
            raise GateAwareSizingError(
                f"--cycles {path!r}: состояние #{i} без обязательных полей 'label'/'open'"
            )
        if not isinstance(state["open"], dict):
            raise GateAwareSizingError(
                f"--cycles {path!r}: 'open' состояния {state.get('label')!r} должен быть "
                f"объектом {{TICKER: weight_pct}}"
            )
    return data


def compute_cycle_targets(
    active_holdings: list[dict[str, Any]],
    cycles: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], float]:
    """B1 — цель каждой бумаги в каждом обозримом состоянии цикла. Каждое состояние
    полностью задаёт множество "sized"-тикеров этого состояния (ключи 'open'); всё
    остальное в активной акционной книге считается неподвижным в этом состоянии —
    F(состояния) = книга − Σ current_rub(sized этого состояния). Дискриминация
    Blocked/Dormant/Selling внутри F здесь не нужна: для диапазона целей на будущих
    состояниях важна только сумма, не категория (арифметически compute_fixed_point_target
    не различает Blocked и Dormant внутри F — см. её докстрок).

    Возвращает ({ticker: {"target_min", "target_max", "target_by_cycle": {label: target},
    "current_rub"}}, total_book_rub)."""
    current_by_ticker = {h["ticker"]: float(h.get("value_rub") or 0.0) for h in active_holdings}
    total_book = sum(current_by_ticker.values())

    by_ticker_by_cycle: dict[str, dict[str, float | None]] = {}
    for state in cycles:
        label = state["label"]
        try:
            weights = {t: float(w) / 100.0 for t, w in state["open"].items()}
        except (TypeError, ValueError) as exc:
            raise GateAwareSizingError(f"--cycles, состояние {label!r}: вес не число ({exc})")
        sized_current_sum = sum(current_by_ticker.get(t, 0.0) for t in weights)
        f_sum = total_book - sized_current_sum
        try:
            r = compute_fixed_point_target(blocked_sum=f_sum, dormant_sum=0.0, open_weights=weights)
        except ValueError as exc:
            raise GateAwareSizingError(f"--cycles, состояние {label!r}: {exc}")
        t_star = r["T_star"]  # None при near_degenerate — цели этого состояния не досчитаны
        for ticker, w in weights.items():
            target = (w * t_star) if t_star is not None else None
            by_ticker_by_cycle.setdefault(ticker, {})[label] = target

    result: dict[str, dict[str, Any]] = {}
    for ticker, by_cycle in by_ticker_by_cycle.items():
        values = [v for v in by_cycle.values() if v is not None]
        result[ticker] = {
            "target_min": min(values) if values else None,
            "target_max": max(values) if values else None,
            "target_by_cycle": by_cycle,
            "current_rub": current_by_ticker.get(ticker),
        }
    return result, total_book


def compute_reversal_risk(
    sized_items: list[dict[str, Any]],
    cycles: list[dict[str, Any]],
    target_ranges: dict[str, dict[str, Any]],
    total_book: float | None,
    hysteresis_pp: float,
) -> list[dict[str, Any]]:
    """B2 — для каждой бумаги с предписанным СЕГОДНЯ действием (buy/trim, не hold —
    "для каждой бумаги, по которой в текущем цикле предписано действие") проверяем,
    не потребует ли какое-то состояние из --cycles движения в обратную сторону сверх
    гистерезиса:

        после_действия = target_i сегодня
        разворот, если существует состояние k:
            знак(target_k − после_действия) ≠ знак(после_действия − current_i)
            И |target_k − после_действия| / книга × 100 > hysteresis_pp

    **Фильтр будущих состояний — по ПОРЯДКУ в списке, а не по составу.** Список `--cycles`
    упорядочен во времени. «Сегодня» — состояние, чей набор открытых тикеров совпадает с
    тем, что открыто/срезается сейчас; сравниваются только состояния ПОСЛЕ него. Если
    совпадения нет, сегодняшнее состояние в списке не описано — сравниваются все состояния,
    и это отмечается warning'ом вызывающим кодом.

    Почему не по составу (правка ревью 27.08.2026). Первая редакция требовала, чтобы набор
    открытых тикеров состояния был НАДмножеством сегодняшнего. Это верно работало на
    монотонной последовательности снятия гейтов, но отбрасывало состояние целиком, если в
    нём открытых МЕНЬШЕ, — то есть ровно случай «появился новый гейт», который §8.1 задания
    называет симметричной половиной проблемы: база падает, и недавно докупленная бумага
    оказывается в перевесе. Проверено на живом снапшоте: при гейте на RENI цель X5 падает
    299 974 → 292 473 ₽ (7 501 ₽), и надмножественный фильтр не показывал разворот даже
    при гистерезисе 0,01 пп.

    Ложное срабатывание, ради которого фильтр вводился (тест B-T4), возникало по другой
    причине: сравнение шло с БОЛЕЕ РАННИМИ состояниями. Для сегодняшнего C3 состояние C2 —
    пройденный этап, и падение цели MBNK до C2-уровня разворотом не является. Порядок в
    списке отсекает это точнее, чем состав, и при этом не слепнет к новым гейтам.

    Предупреждение, не блокировка (§8.2 B2 задания) — расчёт не прерывается, даже
    если список непуст. Возвращает [{"ticker", "cycle", "amount_rub", "deviation_pp"}],
    по одной записи на тикер (состояние с максимальным отклонением среди нарушающих
    гистерезис — самый информативный случай для предупреждения)."""
    today_tickers = {item["ticker"] for item in sized_items if item.get("direction") in ("buy", "trim")}
    if not today_tickers or not total_book:
        return []

    # Индекс «сегодня» в упорядоченном списке; сравниваем только то, что после него.
    # Сопоставляем по ВСЕМУ составу подвижных бумаг (open + rebalancing), а не по тем,
    # кому предписано действие: бумага может быть открыта и при этом стоять на цели
    # (direction "hold") — состав класса от этого не меняется.
    today_config = {item["ticker"] for item in sized_items}
    today_idx = next(
        (i for i, state in enumerate(cycles) if set(state.get("open") or {}) == today_config),
        None,
    )
    # Сегодняшнего состояния в списке нет — где мы во времени, неизвестно. Сравниваем со
    # всеми состояниями: лишнее предупреждение безопаснее пропущенного разворота, а
    # вызывающий код помечает это warning'ом cycles_today_state_not_listed.
    future_states = cycles if today_idx is None else cycles[today_idx + 1:]
    valid_labels = {state["label"] for state in future_states}

    risk: list[dict[str, Any]] = []
    for item in sized_items:
        if item.get("direction") not in ("buy", "trim"):
            continue
        ticker = item["ticker"]
        after_action = item.get("target_rub")
        current = item.get("current_rub")
        if after_action is None or current is None:
            continue
        original_sign = _sign(after_action - current)
        if original_sign == 0:
            continue
        ranges = target_ranges.get(ticker)
        if not ranges:
            continue

        worst_cycle: str | None = None
        worst_abs_dev = 0.0
        worst_dev_pp = 0.0
        for label, target_k in ranges["target_by_cycle"].items():
            if label not in valid_labels or target_k is None:
                continue
            deviation = target_k - after_action
            dev_sign = _sign(deviation)
            if dev_sign == 0 or dev_sign == original_sign:
                continue  # тот же знак/ноль — продолжение того же действия, не разворот
            deviation_pp = abs(deviation) / total_book * 100.0
            if deviation_pp <= hysteresis_pp:
                continue
            if abs(deviation) > worst_abs_dev:
                worst_abs_dev, worst_dev_pp, worst_cycle = abs(deviation), deviation_pp, label

        if worst_cycle is not None:
            risk.append({
                "ticker": ticker, "cycle": worst_cycle,
                "amount_rub": worst_abs_dev, "deviation_pp": worst_dev_pp,
            })
    return risk


# ─────────────────────────── лоты ───────────────────────────

def compute_lots(delta_rub: float, quote: dict[str, Any] | None) -> tuple[int | None, float | None, float | None]:
    """(lots, remainder_rub, price) — направление округления явное (docs/investment/
    spec-gate-aware-sizing-trim-fix.md §4.3, ревью-риск №3):

      delta_rub > 0 (покупка) → floor(|delta| / lot_rub) — недокупить лучше, чем выйти за cap;
      delta_rub < 0 (срез)    → ceil(|delta| / lot_rub)  — дорезать лучше, чем недорезать:
                                 недорезав, остаёшься выше cap — то, что механизм не должен
                                 допускать.

    remainder — со знаком, соответствующим направлению: >= 0 для покупки (неизрасходованный
    остаток), <= 0 для среза (продано сверх запрошенного, т.к. лот дорезается вверх).
    None-triple, если данных не хватает (нет quote / нет цены / нет lot_size) либо delta == 0."""
    if not delta_rub or not quote:
        return None, None, None
    price = quote.get("last")
    if price is None:
        price = quote.get("prev_close")
    lot_size = quote.get("lot_size")
    if not price or not lot_size:
        return None, None, None
    lot_rub = price * lot_size
    if delta_rub > 0:
        lots = floor(delta_rub / lot_rub)
        remainder = delta_rub - lots * lot_rub
    else:
        lots = ceil(abs(delta_rub) / lot_rub)
        remainder = -(lots * lot_rub - abs(delta_rub))
    return lots, remainder, price


# ─────────────────────────── пост-трейд веса и сведение по деньгам ───────────────────────────

def compute_post_trade(
    classification: dict[str, list[dict[str, Any]]],
    targets: dict[str, float],
    quotes: dict[str, Any] | None,
) -> dict[str, Any]:
    """S4: `weight_after_pct` считается от ФАКТИЧЕСКОЙ пост-трейд книги
    (F + Σcurrent_sized + Σdelta_округлённых), НЕ от T* — знаменатель риск-метрик факт,
    не цель. Без quotes для тикера используется неокруглённая цель (лучшая доступная оценка,
    в этом случае вес после округления совпадает с идеальным — нечего округлять).

    Отклонение факта от плана `w_i` раскладывается на два слагаемых с РАЗНЫМИ причинами,
    и смешивать их нельзя (разбор 26.08.2026):

      structural_pp = weight_ideal − w_i   — отклонение при идеальном исполнении, без
          округления вовсе. Ненулевое только когда база не равна пост-трейд книге, то есть
          в ветке `t_full_no_gates`: цели считаются от полного плана класса, а книга ниже
          него, поэтому КАЖДЫЙ sized-тикер садится выше своего веса относительно факта.
          Это цена варианта B, осознанно принятая при отсутствии гейтов
          (`gate-aware-sizing.md` §«Три варианта денежной базы»), а не следствие лотности.
      rounding_pp   = weight_after − weight_ideal — вклад именно округления по лотам.

    `cap_breach_after_rounding` реагирует ТОЛЬКО на `rounding_pp` — иначе в ветке без гейтов
    он срабатывал на 100% тикеров при полностью отсутствующих котировках (реальный прогон
    21.08.2026: X5 +0,81 пп, MBNK +0,54, LSNGP +0,40, SBERP +1,08 — при том, что округлять
    было нечего). Предупреждение, срабатывающее на всех, — шум, из-за которого пропускают
    настоящее нарушение. Структурное отклонение отдаётся отдельно, одной записью на прогон.

    Возвращает {"weight_after_pct": {ticker: pct|None}, "weight_ideal_pct": {...},
    "cap_breach_after_rounding": [...], "structural_cap_offset": [...],
    "denominator_rub": float}."""
    f_sum = sum(x["current_rub"] for x in classification["blocked"]) \
        + sum(x["current_rub"] for x in classification["dormant"])

    sized = classification["open"] + classification["rebalancing"]
    post_trade_rub: dict[str, float] = {}
    ideal_rub: dict[str, float] = {}
    denom = f_sum
    denom_ideal = f_sum
    for item in sized:
        ticker = item["ticker"]
        current = item["current_rub"]
        target = targets.get(ticker)
        if target is None:
            post_trade_rub[ticker] = ideal_rub[ticker] = current
            denom += current
            denom_ideal += current
            continue
        delta = target - current
        quote = (quotes or {}).get(ticker)
        lots, _remainder, price = compute_lots(delta, quote)
        if lots is not None and price is not None:
            lot_rub = price * quote.get("lot_size")
            actual_change = lots * lot_rub if delta > 0 else -(lots * lot_rub)
        else:
            actual_change = delta
        value_after = current + actual_change
        post_trade_rub[ticker] = value_after
        ideal_rub[ticker] = target
        denom += value_after
        denom_ideal += target

    weight_after_pct: dict[str, float | None] = {}
    weight_ideal_pct: dict[str, float | None] = {}
    cap_breach: list[str] = []
    structural_offset: list[str] = []
    for item in sized:
        ticker = item["ticker"]
        w_i = item["weight_pct"] or 0.0
        pct = (post_trade_rub[ticker] / denom * 100) if denom > 0 else None
        pct_ideal = (ideal_rub[ticker] / denom_ideal * 100) if denom_ideal > 0 else None
        weight_after_pct[ticker] = pct
        weight_ideal_pct[ticker] = pct_ideal
        if pct_ideal is not None and (pct_ideal - w_i) > _CAP_BREACH_THRESHOLD_PP:
            structural_offset.append(ticker)
        if pct is not None and pct_ideal is not None and (pct - pct_ideal) > _CAP_BREACH_THRESHOLD_PP:
            cap_breach.append(ticker)

    return {
        "weight_after_pct": weight_after_pct,
        "weight_ideal_pct": weight_ideal_pct,
        "cap_breach_after_rounding": cap_breach,
        "structural_cap_offset": structural_offset,
        "denominator_rub": denom,
    }


def _get_cash_rub(snapshot: dict[str, Any]) -> float | None:
    cash = snapshot.get("cash")
    if not isinstance(cash, dict):
        return None
    total = cash.get("total_rub")
    return float(total) if isinstance(total, (int, float)) else None


def _get_liquid_cash_rub(snapshot: dict[str, Any]) -> float | None:
    """`cash.liquid_rub` = `total_rub` + `cash_equiv_rub` — брокерский остаток ПЛЮС
    money-market фонды (TMON/TPAY/LQDT/SBMM).

    Для правила буфера сравнивать надо именно с ним, а не с `total_rub`: деньги, место под
    которые забронировано бумагами под гейтами, физически стоят не на остатке, а в
    money-market. На снапшоте 21.08.2026 `total_rub` = 57 082 ₽ против `liquid_rub`
    3 957 234 ₽ — по `total_rub` правило показывало бы вечную «нехватку» 96% и при
    односторонней тревоге молчало бы всегда, то есть было бы мертво.

    Фолбэка на `total_rub` НЕТ намеренно: это разные величины, и подставлять одну вместо
    другой — та самая подмена похожего поля, на которой репозиторий уже обжигался
    (`rpa-17-field-paths-audit.md`). Нет поля — правило не считается."""
    cash = snapshot.get("cash")
    if not isinstance(cash, dict):
        return None
    liquid = cash.get("liquid_rub")
    return float(liquid) if isinstance(liquid, (int, float)) else None


def compute_cash_buffer(
    nav: float,
    class_plan_rub: float,
    base_rub: float | None,
    liquid_cash_rub: float | None,
    buffer_pct: float,
    gated_rub: float | None = None,
) -> dict[str, Any] | None:
    """Правило кэша (`gate-aware-sizing.md`): пока часть класса стоит под гейтами, деньги
    на недобор заблокированных бумаг никуда не деваются — они ждут снятия гейтов. Меряя кэш
    обычным буфером, эту сумму принимают за «перебор кэша», хотя место под неё уже
    забронировано конкретными бумагами.

        ожидаемый_кэш = buffer_pct% × NAV + gap_gated_rub (доля разрыва «план − база» от гейтов)

    `gated_rub` — только слагаемое гейтов (§10.6 п.4): недобор бумаг в коридоре и нераспределённая доля
    плана места не бронируют. Не передан — прежняя формула (план класса − база), для старых вызовов.

    Скрипт считает АРИФМЕТИКУ и применяет документированный односторонний порог; решение,
    что делать с превышением, остаётся за владельцем. Правило вынесено сюда из чистого
    текста намеренно: 19.08.2026 методика сайзинга уже была записана в референсы и в тот же
    день не сработала (за сумму докупки приняли `goals_matrix.Изменение` — ошибка ×14).
    «Не выдумывай цифры» распространяется и на арифметику (докстрока
    `constraint_engine.compute_fixed_point_target`).

    Возвращает None, если базу не досчитали (near_degenerate) или нет `cash.liquid_rub` —
    числа в этих случаях не выдумываются."""
    if base_rub is None or liquid_cash_rub is None:
        return None
    buffer_rub = nav * buffer_pct / 100.0
    if gated_rub is None:
        gated_rub = class_plan_rub - base_rub
    gated_rub = max(0.0, gated_rub)
    expected = buffer_rub + gated_rub
    excess = liquid_cash_rub - expected
    return {
        "expected_cash_rub": expected,
        "buffer_component_rub": buffer_rub,
        "gated_component_rub": gated_rub,
        "buffer_pct": buffer_pct,
        "liquid_cash_rub": liquid_cash_rub,
        # Со знаком: >0 — кэша больше ожидаемого, <0 — меньше.
        "excess_rub": excess,
        # Тревога ОДНОСТОРОННЯЯ: только превышение. Кэш ниже ожидаемого — рабочее состояние
        # (буфер частично израсходован), симметричная тревога срабатывала бы ложно на каждом
        # цикле с докупками.
        "above_expected": excess > 0,
    }


def compute_money_reconciliation(
    classification: dict[str, list[dict[str, Any]]],
    targets: dict[str, float],
    extra_cash_from_sales: float,
    cash_rub: float | None,
) -> dict[str, Any]:
    """Сведение по деньгам (docs/investment/spec-gate-aware-sizing-trim-fix.md §4.3):
    покупки vs выручка от тримов vs --extra-cash-from-sales vs кэш снапшота → дефицит/остаток.
    Дефицит — информация (цикл нужно исполнять частями), не ошибка.

    `net_trading_need_rub` = покупки − выручка от тримов (без учёта кэша/extra-cash) — именно
    эта величина названа «нетто» в тест-кейсе 5.2 спеки. `surplus_or_deficit_rub` — уже с
    учётом кэша и extra-cash; None, если `cash.total_rub` в снапшоте недоступен (не
    домысливаем дефицит без реальной цифры кэша)."""
    buys = 0.0
    trim_proceeds = 0.0
    for item in classification["open"] + classification["rebalancing"]:
        target = targets.get(item["ticker"])
        if target is None:
            continue
        delta = target - item["current_rub"]
        if delta > 0:
            buys += delta
        elif delta < 0:
            trim_proceeds += -delta

    net_trading_need = buys - trim_proceeds
    if cash_rub is None:
        surplus_or_deficit = None
    else:
        surplus_or_deficit = trim_proceeds + extra_cash_from_sales + cash_rub - buys

    return {
        "buys_rub": buys,
        "trim_proceeds_rub": trim_proceeds,
        "net_trading_need_rub": net_trading_need,
        "extra_cash_from_sales_rub": extra_cash_from_sales,
        "cash_rub": cash_rub,
        "surplus_or_deficit_rub": surplus_or_deficit,
        "is_deficit": surplus_or_deficit is not None and surplus_or_deficit < 0,
    }


# ───────────────── подсказка по недавним сделкам (§10.4, «полезное сверх задания») ─────────────────

def _recent_trade_hints(
    holdings: list[dict[str, Any]],
    per_instrument_xirr: dict[str, Any] | None,
    acted: dict[str, str],
) -> list[dict[str, Any]]:
    """§10.4 задания B — ПОДСКАЗКА, не решение. Если по тикеру есть `recent_direction`
    (свёртка недавних сделок portfolio-data-loader, правка 26.08.2026 в
    `per_instrument_xirr[ticker]`) и `--acted` по нему НЕ передан — предложить передать
    его явно. Признак НЕ выставляется автоматически: решение, что недавняя сделка была
    именно решением о ребалансе (а не, скажем, пополнением), остаётся за человеком
    (§10.3/§10.4 задания). На старых снапшотах (без группы `recent_*`) деградирует
    молча — `.get()` возвращает None, ни одной подсказки не будет."""
    if not per_instrument_xirr:
        return []
    hints: list[dict[str, Any]] = []
    for h in holdings:
        ticker = h.get("ticker")
        if not ticker or ticker in acted:
            continue
        row = per_instrument_xirr.get(ticker)
        if not isinstance(row, dict):
            continue
        direction = row.get("recent_direction")
        if direction not in ("buy", "trim"):
            continue
        hints.append({
            "ticker": ticker, "direction": direction,
            "date": row.get("recent_last_trade_date"),
        })
    return hints


def _trim_candidate_hints(
    holdings: list[dict[str, Any]],
    per_ticker: dict[str, Any],
    trim_overrides: dict[str, float | None],
    selling_tickers: list[str],
) -> list[dict[str, Any]]:
    """§6 задания — ПОДСКАЗКА, не автоклассификация. `--trim` остаётся ручным флагом.

    §6 запрещает выводить «это трим» из `advisor_verdict: TRIM`, и по делу: вердикт TRIM
    не несёт целевой доли, а дискриминатор `Rebalancing` vs `Selling` (§4.1) требует именно
    её. Но в снапшоте есть сигнал, который целевую долю НЕСЁТ: `user_plan: BALANCE`
    означает «привести к плану», и план — это `planned_share_pct`. Дискриминатор на нём
    выполним, поэтому подсказать можно, ничего не выдумывая.

    Условия подсказки: `user_plan == "BALANCE"`, факт выше плана, и тикер не передан ни в
    `--trim`, ни в `--selling`.

    **Порог здесь НЕ гистерезис Rule 3, и это не упущение.** Гистерезис решает, стоит ли
    двигать позицию на такую величину. Флаг `--trim` решает другое: попадёт ли ВСЯ позиция
    в `S` (как `Rebalancing`) или останется в `F`. Цена ошибки поэтому зависит от размера
    ПОЗИЦИИ, а не от размера перевеса. Кейс 21.08.2026: перевес SBERP всего 0,61 пп —
    внутри гистерезиса, — но сама позиция 408 542 ₽, и её отсутствие в `S` занижало базу
    докупки на 446 374 ₽. Отсекать подсказку гистерезисом значило бы молчать ровно в том
    случае, ради которого правка и делалась.

    Решение всё равно за человеком: BALANCE не отличает «срезать до плана» от «пересмотреть
    план», а именно это различие определяет, `Rebalancing` перед нами или повод поменять
    `planned_share_pct`. Автоматически классифицировать — значит выбрать за владельца.
    Кейс 21.08.2026: SBERP стоял `BALANCE` с перевесом +0,61 пп, флаг `--trim` не передали,
    и весь дефект заниженной базы поехал именно отсюда."""
    trim_set = set(trim_overrides) | set(selling_tickers)
    hints: list[dict[str, Any]] = []
    for h in holdings:
        ticker = h.get("ticker")
        if not ticker or ticker in trim_set:
            continue
        row = per_ticker.get(ticker) or {}
        if row.get("user_plan") != "BALANCE":
            continue
        planned, real = row.get("planned_share_pct"), row.get("real_share_pct")
        if not isinstance(planned, (int, float)) or not isinstance(real, (int, float)):
            continue
        excess_pp = real - planned
        if excess_pp <= _DIRECTION_EPS_PP:
            continue
        hints.append({
            "ticker": ticker, "planned_share_pct": planned,
            "real_share_pct": real, "excess_pp": excess_pp,
        })
    return hints


def _format_recent_trade_hint(hint: dict[str, Any]) -> str:
    ticker, direction, date = hint["ticker"], hint["direction"], hint.get("date")
    date_part = f"сделка {date} " if date else "сделка "
    return (
        f"ℹ️ По {ticker} {date_part}в направлении {direction} попадает в окно недавних "
        f"сделок; если это было решение о ребалансе, передай `--acted {ticker}={direction}`."
    )


# ─────────────────────────── форматирование ───────────────────────────

def _fmt_rub(x: float) -> str:
    return f"{round(x):,}".replace(",", " ") + " ₽"

def _fmt_rub_100(x: float) -> str:
    """Докупки округляются до 100 ₽ (§T1 п.7)."""
    return _fmt_rub(round(x / 100.0) * 100)

def _fmt_pct(x: float, nd: int = 1) -> str:
    """Проценты в русской типографике: десятичная запятая, без хвостовых нулей."""
    s = f"{x:.{nd}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s.replace(".", ",")


def build_report_block(
    as_of: str, nav: float, class_plan_rub: float, class_fact_rub: float,
    classification: dict[str, list[dict[str, Any]]], sizing: dict[str, Any],
    quotes: dict[str, Any] | None,
) -> str:
    base_rub = sizing["base_rub"]
    base_source = sizing["base_source"]
    lines: list[str] = []

    # Блок 1 — база докупки.
    if base_rub is None:
        lines.append(
            "**База докупки акций не досчитана автоматически:** открытые к докупке бумаги "
            "в сумме занимают почти весь плановый вес класса — дальнейший расчёт численно "
            "нестабилен, нужна ручная проверка, а не досчёт."
        )
        # Guard §4.4 (docs/investment/spec-gate-aware-sizing-trim-fix.md) — плоский
        # near_degenerate_manual_check в warnings[] сохранён для совместимости; здесь —
        # человекочитаемая разбивка вклада в S по категориям, иначе причина отказа непонятна.
        breakdown = sizing.get("s_breakdown") or {}
        parts = []
        for key, label in (("open", "открытые к докупке"), ("rebalancing", "на срез")):
            names = [c["ticker"] for c in (breakdown.get(key) or [])]
            if names:
                parts.append(f"{label} — {', '.join(names)}")
        if parts:
            lines.append(f"Вклад в суммарный вес класса, из-за которого расчёт неустойчив: {'; '.join(parts)}.")
    elif base_source == "t_full_no_gates":
        lines.append(
            f"**База докупки акций — {_fmt_rub(base_rub)} ({_fmt_pct(base_rub / nav * 100)}% NAV).** "
            "Неподвижных бумаг в классе нет — все двигаются к плану, база докупки равна "
            "полному плану класса."
        )
    elif base_source == "fixed_point_capped":
        lines.append(
            f"**База докупки акций — {_fmt_rub(base_rub)} ({_fmt_pct(base_rub / nav * 100)}% NAV).** "
            "Бумаги под гейтами уже занимают больше своей плановой доли, поэтому база ограничена "
            "полным планом класса: открытые бумаги докупаются до плана, но не сверх него."
        )
    else:
        blocked_names = [x["ticker"] for x in classification["blocked"]]
        who = (", ".join(blocked_names) + " стоят под гейтами и не растут") if blocked_names \
            else "остальные бумаги в этом цикле не торгуются"
        lines.append(
            f"**База докупки акций — {_fmt_rub(base_rub)} ({_fmt_pct(base_rub / nav * 100)}% NAV).** "
            f"Столько акционная книга может занимать сегодня: {who}, "
            f"поэтому докупка открытых бумаг считается относительно этой суммы, а не относительно "
            f"плановых {_fmt_pct(class_plan_rub / nav * 100)}% ({_fmt_rub(class_plan_rub)})."
        )

    # Блок 2 — остаток, закрытый для покупок гейтами.
    if base_rub is None:
        lines.append("")
        lines.append("**Остаток, закрытый для покупок гейтами:** не считается, пока база не досчитана.")
    else:
        gap_rub = class_plan_rub - base_rub
        gap_pp = gap_rub / nav * 100
        lines.append("")
        gated = sizing.get("gap_gated_rub") or 0.0
        corridor = sizing.get("gap_in_corridor_rub") or 0.0
        unalloc = sizing.get("gap_unallocated_rub") or 0.0
        if gap_rub <= 0.5:
            lines.append("**Остаток, закрытый для покупок гейтами — 0 ₽:** база равна плану класса, "
                         "весь план класса размещается.")
        else:
            lines.append(
                f"**Не размещается сейчас — {_fmt_rub(gap_rub)} ({_fmt_pct(gap_pp)} пп NAV)** "
                f"(план класса − база), из них:"
            )
            reasons = [f"{b['ticker']} — {b['unblock_by']}" for b in classification["blocked"]]
            lines.append(
                f"- **Остаток, закрытый для покупок гейтами — {_fmt_rub(gated)}**"
                + (f": {'; '.join(reasons)}. Часть плана в очереди, не «недобор, который надо закрывать»" if reasons else "")
                + ";"
            )
            lines.append(f"- недобор бумаг в коридоре и «держать» (со знаком) — {_fmt_rub(corridor)};")
            lines.append(f"- доля плана, не распределённая по бумагам — {_fmt_rub(unalloc)}.")

    # Блок 3 — доли к базе (для IntelInvest). Rebalancing-тикеры помечены «(срез)» — вес тот
    # же, но действие обратное; IntelInvest считает лоты только для докупки.
    lines.append("")
    open_items = classification["open"]
    rebalancing_items = classification["rebalancing"]
    sized_items = open_items + rebalancing_items
    if not sized_items:
        lines.append("**Доли к базе (для IntelInvest):** открытых к докупке бумаг в этом цикле нет.")
    else:
        parts = []
        for o in open_items:
            mark = " (IE-цель)" if o["weight_source"] == "ie" else ""
            parts.append(f"{o['ticker']} {_fmt_pct(o['weight_pct'])}%{mark}")
        for o in rebalancing_items:
            mark = " (IE-цель)" if o["weight_source"] == "ie" else ""
            parts.append(f"{o['ticker']} {_fmt_pct(o['weight_pct'])}% (срез){mark}")
        lines.append("**Доли к базе (для IntelInvest):** " + " · ".join(parts) + ".")

    # Блок 4 — открытые к докупке и на срез бумаги построчно. Rebalancing (S5) может дать
    # и положительную дельту (срез развернулся в докупку, S3) — направление определяет знак,
    # а не то, каким флагом тикер был передан; Open с отрицательной дельтой НИКОГДА не
    # рендерится как срез (аналитик его не заказывал) — держит формулировку «на цели».
    lines.append("")
    heading = "Открытые к докупке и на срез:" if rebalancing_items else "Открытые к докупке:"
    if not sized_items:
        lines.append(f"**{heading}** нет.")
    else:
        lines.append(f"**{heading}**")
        total_buy = 0.0
        total_trim = 0.0
        lots_shown = False
        flips: list[tuple[str, float]] = []
        targets = sizing["targets"]
        for o, category in [(x, "open") for x in open_items] + [(x, "rebalancing") for x in rebalancing_items]:
            ticker = o["ticker"]
            target = targets.get(ticker)
            if target is None:
                lines.append(f"- {ticker}: факт {_fmt_rub(o['current_rub'])} — цель не досчитана.")
                continue
            delta = target - o["current_rub"]
            direction = _direction_for(category, delta)
            quote = (quotes or {}).get(ticker)
            lots, remainder, price = compute_lots(delta, quote)
            lots_txt = ""
            if lots is not None:
                lots_shown = True
                verb = "докупить" if direction == "buy" else "срезать"
                lots_txt = f" ({verb} ≈ {lots} лот. по {_fmt_rub(price)}, остаток {_fmt_rub(abs(remainder))})"
            if direction == "buy":
                total_buy += delta
                lines.append(
                    f"- {ticker}: факт {_fmt_rub(o['current_rub'])} → цель {_fmt_rub(target)} "
                    f"(+{_fmt_rub_100(delta)}{lots_txt})"
                )
                if category == "rebalancing":
                    flips.append((ticker, delta))
            elif direction == "trim":
                total_trim += -delta
                lines.append(
                    f"- {ticker}: факт {_fmt_rub(o['current_rub'])} → цель {_fmt_rub(target)} "
                    f"(−{_fmt_rub_100(-delta)}{lots_txt})"
                )
            else:
                lines.append(
                    f"- {ticker}: факт {_fmt_rub(o['current_rub'])} → цель {_fmt_rub(target)} "
                    f"— уже на цели или выше, докупка не требуется."
                )
        if total_buy > 0 or total_trim > 0:
            tail = " Лоты — оценка по последней цене, точное количество считает IntelInvest." if lots_shown else ""
            totals = []
            if total_buy > 0:
                totals.append(f"докупить ≈ {_fmt_rub_100(total_buy)}")
            if total_trim > 0:
                totals.append(f"срезать ≈ {_fmt_rub_100(total_trim)}")
            lines.append(f"Итого: {'; '.join(totals)}.{tail}")
        # S3 — молчаливый разворот трима в покупку недопустим (см. также
        # warnings[] "trim_direction_flipped:TICKER").
        for ticker, amt in flips:
            lines.append("")
            lines.append(
                f"⚠️ **{ticker}: срез развернулся в докупку (+{_fmt_rub(amt)}).** База докупки "
                f"выросла настолько, что целевой вес этого тикера превысил его текущую позицию — "
                f"формальный расчёт предписывает докупку вместо среза. Решение — за владельцем: "
                f"исполнять как докупку или отложить срез до следующего цикла."
            )

    post_trade_block = sizing.get("post_trade") or {}
    cap_breach = post_trade_block.get("cap_breach_after_rounding") or []
    if cap_breach:
        lines.append("")
        lines.append(
            f"⚠️ Округление по лотам поднимает вес выше плановой доли более чем на "
            f"{_fmt_pct(_CAP_BREACH_THRESHOLD_PP, nd=2)} пп: {', '.join(cap_breach)}."
        )

    # Структурное отклонение — одной записью на прогон, а не пофамильно: причина у всех
    # тикеров одна и та же (база = полный план класса, книга ниже него), и перечисление
    # имён создаёт впечатление, будто с каждым из них что-то не так по отдельности.
    structural = post_trade_block.get("structural_cap_offset") or []
    if structural:
        lines.append("")
        lines.append(
            "ℹ️ Пока класс недобран, открытые бумаги временно занимают долю выше плановой "
            "относительно текущей книги — цели считаются от полного плана класса, а книга "
            "меньше него. Это не следствие округления и не повод сокращать: доли сойдутся "
            "к плану по мере наполнения класса."
        )

    money_reconciliation = sizing.get("money_reconciliation")
    if money_reconciliation is not None:
        lines.append("")
        lines.append("**Сведение по деньгам:**")
        lines.append(f"- Покупки: {_fmt_rub_100(money_reconciliation['buys_rub'])}")
        lines.append(f"- Выручка от тримов: {_fmt_rub_100(money_reconciliation['trim_proceeds_rub'])}")
        extra_cash = money_reconciliation["extra_cash_from_sales_rub"]
        if abs(extra_cash) > 0.5:
            lines.append(f"- Доп. выручка от продаж (--extra-cash-from-sales): {_fmt_rub_100(extra_cash)}")
        cash_rub = money_reconciliation["cash_rub"]
        if cash_rub is not None:
            lines.append(f"- Кэш (из снапшота): {_fmt_rub_100(cash_rub)}")
            surplus_or_deficit = money_reconciliation["surplus_or_deficit_rub"]
            if money_reconciliation["is_deficit"]:
                lines.append(
                    f"- **Дефицит: {_fmt_rub_100(abs(surplus_or_deficit))}** — цикл нужно "
                    f"исполнять частями, это не ошибка."
                )
            else:
                lines.append(f"- Остаток после цикла: {_fmt_rub_100(surplus_or_deficit)}")
        else:
            lines.append("- Кэш из снапшота недоступен (`cash.total_rub`) — дефицит/остаток не считается.")

    # Правило кэша (методология): сколько кэша нормально держать, пока часть класса под гейтами.
    cb = sizing.get("cash_buffer")
    if cb:
        lines.append("")
        lines.append(
            f"**Сколько кэша нормально сейчас — {_fmt_rub(cb['expected_cash_rub'])}:** "
            f"буфер {_fmt_pct(cb['buffer_pct'])}% NAV ({_fmt_rub(cb['buffer_component_rub'])}) "
            f"плюс {_fmt_rub(cb['gated_component_rub'])} — недобор бумаг под гейтами, место под него уже "
            f"забронировано. Фактически ликвидных — {_fmt_rub(cb['liquid_cash_rub'])} "
            f"(остаток и money-market вместе)."
        )
        if cb["above_expected"]:
            lines.append(
                f"⚠️ Это на {_fmt_rub(cb['excess_rub'])} больше ожидаемого — гейтами такой "
                f"остаток уже не объясняется, деньги не работают."
            )
        else:
            lines.append(
                f"Это на {_fmt_rub(abs(cb['excess_rub']))} меньше ожидаемого — в пределах нормы: "
                f"буфер частично израсходован, это рабочее состояние, а не повод для тревоги."
            )

    manual_unblocks = [w.split(":", 1)[1] for w in sizing.get("classification_warnings", []) if w.startswith("manual_unblock:")]
    reason_by_ticker = {o["ticker"]: o.get("overridden_block_reason") for o in classification["open"]}
    for ticker in manual_unblocks:
        why = reason_by_ticker.get(ticker)
        detail = f"вопреки автоклассификации ({why})" if why else "вопреки ручной пометке blocked"
        lines.append("")
        lines.append(
            f"⚠️ {ticker} открыт {detail} — причина должна быть в отчёте."
        )

    # §9.2/§9.3 — --open, отклонённый лимитом концентрации (СИЛЬНЕЕ ручного флага, в
    # отличие от manual_unblocks выше, где ручной флаг как раз побеждает).
    concentration_open_blocked = [
        w.split(":", 1)[1] for w in sizing.get("classification_warnings", [])
        if w.startswith("open_override_blocked_by_concentration:")
    ]
    for ticker in concentration_open_blocked:
        lines.append("")
        lines.append(
            f"⚠️ **{ticker}: запрошенная докупка (--open) заблокирована лимитом "
            f"концентрации.** Ручной флаг риск-лимит не отменяет — тикер переведён в "
            f"Blocked, докупка невозможна до среза группы к лимиту."
        )

    # Правило неразворота (§10.3) — подавленные развороты по --acted.
    acted_suppressed = [
        w.split(":", 1)[1] for w in (sizing.get("acted_warnings") or [])
        if w.startswith("acted_reversal_suppressed:")
    ]
    for ticker in acted_suppressed:
        lines.append("")
        lines.append(
            f"⚠️ **{ticker}: разворот подавлен правилом неразворота.** По этой бумаге уже "
            f"была сделка в этом горизонте (`--acted`) в направлении, арифметика на этот "
            f"раз требует обратного — разворот запрещён. Тикер переведён в Dormant, его "
            f"сумма возвращена в базу, база пересчитана без него."
        )
    iteration_warn = next(
        (w for w in (sizing.get("acted_warnings") or []) if w.startswith("acted_reversal_iteration_limit_exceeded:")),
        None,
    )
    if iteration_warn is not None:
        lines.append("")
        lines.append(
            "⚠️ Проверка правила неразворота не сошлась за отведённое число проходов — "
            "числа по бумагам под --acted требуют ручной проверки."
        )

    # §9.2 «важное следствие» — срез, требуемый лимитом концентрации, не может
    # развернуться в докупку (капнуто на текущую позицию, см. run_sizing).
    for ticker in (sizing.get("concentration_cap_warnings") or []):
        ticker = ticker.split(":", 1)[1]
        lines.append("")
        lines.append(
            f"⚠️ **{ticker}: срез, требуемый лимитом концентрации, не может "
            f"развернуться в докупку.** Арифметика цикла предлагала докупку — "
            f"заблокировано: лимит запрещает движение вверх, позиция держится на "
            f"текущем уровне до отдельного решения владельца."
        )

    # B2 — риск разворота на обозримом горизонте (--cycles), предупреждение, не блокировка.
    reversal_risk = sizing.get("reversal_risk") or []
    if reversal_risk:
        hysteresis_pp = sizing.get("hysteresis_pp", _DEFAULT_HYSTERESIS_PP)
        lines.append("")
        for r in reversal_risk:
            lines.append(
                f"⚠️ **Риск разворота на горизонте — {r['ticker']}.** Состояние «{r['cycle']}» "
                f"тянет цель в сторону, обратную сегодняшнему действию, на "
                f"{_fmt_rub(r['amount_rub'])} ({_fmt_pct(r['deviation_pp'], nd=2)} пп) — "
                f"больше гистерезиса {_fmt_pct(hysteresis_pp, nd=2)} пп. Это предупреждение, "
                f"не блокировка: исполнять сейчас или отложить сделку — решение за владельцем."
            )

    # §9/§11 «Волна 3» — сводка лимитов концентрации (знаменатель L2_cur, НЕ база
    # докупки — см. references/gate-aware-sizing.md §«Лимиты концентрации»).
    concentration_result = sizing.get("concentration_result")
    if concentration_result is not None:
        by_issuer = concentration_result["concentration"]["by_issuer"]
        by_sector = concentration_result["concentration"]["by_sector"]
        issuer_breaches = [(g, row) for g, row in by_issuer.items() if row["breach"]]
        sector_breaches = []
        if isinstance(by_sector, dict) and "status" not in by_sector:
            sector_breaches = [(s, row) for s, row in by_sector.items() if row["breach"]]
        lines.append("")
        if issuer_breaches or sector_breaches:
            lines.append("**Лимиты концентрации — нарушения:**")
            for group_key, row in issuer_breaches:
                lines.append(
                    f"- {group_key}: {_fmt_pct(row['share_pct'], nd=2)}% при лимите "
                    f"{_fmt_pct(row['limit_pct'], nd=2)}% ({row['limit_source']}) — "
                    f"срез до лимита ≈ {_fmt_rub(row['trim_to_limit_rub'])}."
                )
            for sector_key, row in sector_breaches:
                lines.append(
                    f"- сектор {sector_key}: {_fmt_pct(row['share_pct'], nd=2)}% при лимите "
                    f"{_fmt_pct(row['limit_pct'], nd=2)}% — срез до лимита ≈ "
                    f"{_fmt_rub(row['trim_to_limit_rub'])}."
                )
        else:
            lines.append(
                f"**Лимиты концентрации:** нарушений нет (книга "
                f"{_fmt_rub(concentration_result['l2_cur'])}, {len(by_issuer)} групп по эмитенту)."
            )
    elif sizing.get("concentration_unavailable_reason"):
        lines.append("")
        lines.append(
            f"ℹ️ Проверка лимитов концентрации не выполнена: "
            f"{sizing['concentration_unavailable_reason']}."
        )

    # Подсказка по недавним сделкам без --acted (§10.4, «полезное сверх задания»).
    for hint in (sizing.get("recent_trade_hints") or []):
        lines.append("")
        lines.append(_format_recent_trade_hint(hint))

    # Подсказка по кандидатам на трим без --trim (§6 задания).
    for hint in (sizing.get("trim_candidate_hints") or []):
        lines.append("")
        lines.append(
            f"ℹ️ {hint['ticker']}: план {_fmt_pct(hint['planned_share_pct'])}%, факт "
            f"{_fmt_pct(hint['real_share_pct'])}% — перевес {_fmt_pct(hint['excess_pp'], nd=2)} пп "
            f"при пометке «BALANCE» (привести к плану). Если это срез до плановой доли, "
            f"передай `--trim {hint['ticker']}`: без флага позиция считается неподвижной, "
            f"и база докупки выходит заниженной."
        )

    return "\n".join(lines)


# ─────────────────────────── lint-draft ───────────────────────────

def lint_draft(text: str, stock_tickers: set[str]) -> list[tuple[int, str]]:
    """Ровно две проверки (§T1 п.8). Возвращает [(line_no, message), ...]."""
    violations: list[tuple[int, str]] = []
    lines = text.splitlines()

    for i, line in enumerate(lines, start=1):
        for pattern, label in _FORBIDDEN_NOTATION_PATTERNS:
            if pattern.search(line):
                violations.append((i, f"запрещённая нотация: {label}"))

    has_base_mention = bool(_BASE_MENTION_RE.search(text))
    if not has_base_mention:
        for i, line in enumerate(lines, start=1):
            if not _PURCHASE_VERB_RE.search(line):
                continue
            if not _RUB_SUM_RE.search(line):
                continue
            matched_ticker = next(
                (t for t in stock_tickers if re.search(rf"\b{re.escape(t)}\b", line)), None
            )
            if matched_ticker:
                violations.append(
                    (i, f"сумма докупки {matched_ticker} без строки «База докупки» в черновике")
                )

    return sorted(violations)


# ─────────────────────────── оркестрация / CLI ───────────────────────────

def run_sizing(
    snapshot: dict[str, Any],
    gate_inputs: dict[str, Any] | None,
    conditions: dict[str, Any] | None,
    open_arg: str | None,
    selling_arg: str | None,
    blocked_arg: str | None,
    extra_cash_from_sales: float,
    quotes: dict[str, Any] | None,
    yaml_warnings: list[str],
    trim_arg: str | None = None,
    acted_arg: str | None = None,
    cycles_arg: list[dict[str, Any]] | None = None,
    hysteresis_pp: float = _DEFAULT_HYSTERESIS_PP,
    limits_config: dict[str, Any] | None = None,
    sector_enabled: bool = False,
    concentration_today: str | None = None,
    cash_buffer_pct: float = _CASH_BUFFER_PCT_DEFAULT,
    hold_weights: dict[str, float] | None = None,
    today: str | None = None,
    ai_mode: str = "on",
    horizon: dict[str, float] | None = None,
) -> dict[str, Any]:
    # horizon {тикер: вес %} — горизонт известных дат авто-режима (§10.6 п.7): база срезов с этими бумагами как открытыми.
    # ai_mode: режим сайта on|off — при off блокируют те же статусы, что при on; решение владельца снимает блок (last_word, правила 9, 9а).
    # gate_inputs/conditions — входы модулей (б) и (а) (GateContext): решения, справочник бумаг, строки обзоров;
    # определения conditions@2 + состояние. today — дата гейта и условий (по умолчанию as_of_date снапшота).
    # trim_arg/acted_arg/cycles_arg/hysteresis_pp/limits_config/sector_enabled/
    # concentration_today — новые параметры В КОНЦЕ сигнатуры (не рядом с логически
    # близкими open_arg/selling_arg/blocked_arg/trim_arg): существующие тесты и вызовы
    # зовут run_sizing позиционно — вставка в середину сдвинула бы их и молча сломала
    # бы значения. Задние default сохраняют обратную совместимость. `limits_config`
    # default None — проверка лимитов концентрации ПОЛНОСТЬЮ выключена, пока вызывающий
    # код (main()/CLI) явно не передаст загруженный конфиг: run_sizing НИКОГДА не читает
    # файлы сам (как и с gate_inputs/conditions — уже загруженные dict'ы), а тесты,
    # которые не знают о концентрации, не должны неожиданно получить новые warnings.
    nav, class_row = get_nav_and_class_row(snapshot)
    class_plan_rub = float(class_row.get("Планы") or 0.0)
    class_fact_rub = float(class_row.get("Сейчас") or 0.0)

    holdings = active_stock_holdings(snapshot)
    per_ticker = (snapshot.get("ie_actual") or {}).get("per_ticker") or {}

    open_overrides = _parse_open_arg(open_arg)
    selling_tickers = _parse_manual_list(selling_arg)
    blocked_overrides = _parse_manual_list(blocked_arg)
    trim_overrides = _parse_open_arg(trim_arg)
    acted = _parse_acted_arg(acted_arg)

    # §9/§11 «Волна 3» spec-gate-aware-sizing-trim-fix.md — лимиты концентрации.
    # Знаменатель — фактическая книга L2_cur, а не база докупки (T*/T_full): это
    # разные вопросы (см. concentration_limits.py docstring и
    # references/gate-aware-sizing.md §«Лимиты концентрации»), поэтому проверка
    # считается по СНАПШОТУ, а не по чему-либо, зависящему от sizing ниже.
    #
    # Отказ загрузки/расчёта концентрации НЕ прерывает сайзинг — деградация с явным
    # warning'ом (concentration_check_unavailable:<причина>), а не exit 2: это
    # риск-надстройка над уже рабочим сайзингом акций, а не его предпосылка (см. отчёт
    # по правке волны 3 — обоснование выбора «деградация», а не «жёсткая ошибка»).
    concentration_result: dict[str, Any] | None = None
    concentration_reason_by_ticker: dict[str, str] = {}
    concentration_breach_tickers: set[str] = set()
    concentration_warnings: list[str] = []
    concentration_unavailable_reason: str | None = None
    if limits_config is not None:
        try:
            concentration_result = compute_concentration(
                snapshot, limits_config, sector_enabled=sector_enabled, today=concentration_today,
            )
        except ConcentrationLimitsError as exc:
            concentration_unavailable_reason = str(exc)
            concentration_warnings.append(f"concentration_check_unavailable:{exc}")
        else:
            concentration_warnings.extend(concentration_result["warnings"])
            by_issuer = concentration_result["concentration"]["by_issuer"]
            for group_key, row in by_issuer.items():
                if row["breach"]:
                    for t in row["tickers"]:
                        concentration_reason_by_ticker[t] = f"concentration_breach:{group_key}"
                        concentration_breach_tickers.add(t)
            by_sector = concentration_result["concentration"]["by_sector"]
            if isinstance(by_sector, dict) and "status" not in by_sector:
                for sector_key, row in by_sector.items():
                    if row["breach"]:
                        for t in row["tickers"]:
                            concentration_reason_by_ticker.setdefault(t, f"concentration_breach:{sector_key}")
                            concentration_breach_tickers.add(t)

    classification, class_warnings = classify_stocks(
        holdings, per_ticker, GateContext(snapshot, gate_inputs, conditions, today, ai_mode),
        open_overrides, selling_tickers, blocked_overrides, trim_overrides,
        concentration_reason_by_ticker=concentration_reason_by_ticker,
        hold_weights=hold_weights,
    )

    # §10.3 — правило неразворота: --selling признаку --acted не подчиняется вообще
    # (selling-тикеры уже вне classification["open"]/["rebalancing"] на этом этапе, значит
    # apply_acted_guard их физически не видит — приоритет Selling соблюдён без спец-кода).
    # §9.2 задача 2 проводки — concentration_breach_tickers освобождает срез,
    # который лимит концентрации требует, от подавления правилом неразворота.
    classification, sizing, acted_warnings, acted_iterations = apply_acted_guard(
        classification, acted, class_plan_rub, extra_cash_from_sales,
        concentration_forced_trim=concentration_breach_tickers,
        horizon={t: w for t, w in (horizon or {}).items() if t not in concentration_breach_tickers},
    )
    sizing["classification_warnings"] = class_warnings
    sizing["acted_warnings"] = acted_warnings
    sizing["concentration_result"] = concentration_result
    sizing["concentration_unavailable_reason"] = concentration_unavailable_reason

    all_warnings = (
        list(yaml_warnings) + concentration_warnings + class_warnings
        + sizing["warnings"] + acted_warnings
    )

    # §9.2 «важное следствие» — срез, который лимит концентрации требует, НЕ может
    # развернуться в докупку той же бумаги (в отличие от обычного S3-флипа, который
    # только предупреждает владельца — здесь докупка блокируется полностью): цель
    # капается на текущую позицию, тикер остаётся Rebalancing, но без движения вверх.
    # Срез (delta < 0) этим не затрагивается — лечение нарушения им и остаётся.
    concentration_cap_warnings: list[str] = []
    if sizing["base_rub"] is not None and concentration_breach_tickers:
        for item in classification["rebalancing"]:
            ticker = item["ticker"]
            if ticker not in concentration_breach_tickers:
                continue
            target = sizing["targets"].get(ticker)
            if target is not None and target > item["current_rub"] + _DIRECTION_EPS:
                sizing["targets"][ticker] = item["current_rub"]
                concentration_cap_warnings.append(f"concentration_blocks_rebalancing_buy:{ticker}")
    sizing["concentration_cap_warnings"] = concentration_cap_warnings
    all_warnings += concentration_cap_warnings

    # §10.4 — подсказка по недавним сделкам без --acted (не решение, деградирует молча
    # на снапшотах без группы recent_*).
    recent_hints = _recent_trade_hints(holdings, snapshot.get("per_instrument_xirr"), acted)
    all_warnings += [f"recent_trade_hint:{h['ticker']}" for h in recent_hints]
    sizing["recent_trade_hints"] = recent_hints

    # §6 задания — подсказка по кандидатам на трим (user_plan: BALANCE с перевесом сверх
    # гистерезиса, флаг --trim не передан). НЕ автоклассификация: решение за человеком.
    trim_hints = _trim_candidate_hints(
        holdings, per_ticker, trim_overrides, selling_tickers,
    )
    all_warnings += [f"trim_candidate_hint:{h['ticker']}" for h in trim_hints]
    sizing["trim_candidate_hints"] = trim_hints

    sized_raw = classification["open"] + classification["rebalancing"]

    lots_warnings = []
    if sizing["base_rub"] is not None:
        for o in sized_raw:
            target = sizing["targets"].get(o["ticker"])
            if target is None:
                continue
            delta = target - o["current_rub"]
            if delta == 0:
                continue
            quote = (quotes or {}).get(o["ticker"])
            lots, _, _ = compute_lots(delta, quote)
            if lots is None:
                lots_warnings.append(f"lots_unavailable:{o['ticker']}")
    all_warnings += lots_warnings

    base_rub = sizing["base_rub"]
    base_pct_nav = (base_rub / nav * 100) if base_rub is not None else None
    # разрыв до плана класса целиком (совместимость: так поле называлось раньше) и его три слагаемых (§10.6 п.4)
    blocked_gap_rub = (class_plan_rub - base_rub) if base_rub is not None else None
    blocked_gap_pp_nav = (blocked_gap_rub / nav * 100) if blocked_gap_rub is not None else None

    def _build_out(items: list[dict[str, Any]], category: str) -> list[dict[str, Any]]:
        out = []
        for o in items:
            target = sizing["targets"].get(o["ticker"]) if base_rub is not None else None
            buy = (target - o["current_rub"]) if target is not None else None
            out.append({
                "ticker": o["ticker"], "weight_pct": o["weight_pct"], "weight_source": o["weight_source"],
                "current_rub": o["current_rub"], "target_rub": target, "buy_rub": buy,
                "direction": _direction_for(category, buy),
            })
        return out

    open_out = _build_out(classification["open"], "open")
    rebalancing_out = _build_out(classification["rebalancing"], "rebalancing")

    # S3 — trim-to-target не должен молча разворачиваться в докупку (типично в вырожденной
    # ветке degenerate, где база = T_full без гейтов, но проверяется по знаку дельты вообще,
    # а не только в этом конкретном base_source — тот же риск возможен при резком росте базы
    # из-за одновременного снятия нескольких крупных гейтов).
    for o in rebalancing_out:
        if o["buy_rub"] is not None and o["buy_rub"] > _DIRECTION_EPS:
            all_warnings.append(f"trim_direction_flipped:{o['ticker']}")

    # S7 — --trim одновременно с ненулевым --extra-cash-from-sales: риск двойного счёта
    # выручки (срез уже даёт свою «выручку от тримов» в сведении по деньгам).
    if classification["rebalancing"] and abs(extra_cash_from_sales) > 1e-9:
        all_warnings.append("extra_cash_from_sales_double_count_risk")

    # S4 — пост-трейд веса от ФАКТИЧЕСКОЙ книги после округления по лотам, не от T*.
    if base_rub is not None:
        post_trade = compute_post_trade(classification, sizing["targets"], quotes)
    else:
        post_trade = {"weight_after_pct": {}, "weight_ideal_pct": {},
                      "cap_breach_after_rounding": [], "structural_cap_offset": [],
                      "denominator_rub": None}
    for o in open_out:
        o["weight_after_pct"] = post_trade["weight_after_pct"].get(o["ticker"])
    for o in rebalancing_out:
        o["weight_after_pct"] = post_trade["weight_after_pct"].get(o["ticker"])
    sizing["post_trade"] = post_trade

    # Сведение по деньгам (§4.3): покупки / выручка от тримов / extra-cash / кэш снапшота.
    cash_rub = _get_cash_rub(snapshot)
    # Правило буфера (методология): считается от cash.liquid_rub, а не total_rub — это
    # РАЗНЫЕ величины, см. докстроку _get_liquid_cash_rub.
    cash_buffer = compute_cash_buffer(
        nav, class_plan_rub, base_rub, _get_liquid_cash_rub(snapshot), cash_buffer_pct,
        gated_rub=sizing.get("gap_gated_rub"),
    )
    money_reconciliation = (
        compute_money_reconciliation(classification, sizing["targets"], extra_cash_from_sales, cash_rub)
        if base_rub is not None else None
    )
    sizing["money_reconciliation"] = money_reconciliation
    sizing["cash_buffer"] = cash_buffer
    if cash_buffer and cash_buffer["above_expected"]:
        all_warnings.append("cash_above_expected")

    # B1/B2 — диапазон целей по обозримым циклам и флаг разворота (--cycles, опционально).
    target_ranges: dict[str, Any] = {}
    total_book: float | None = None
    reversal_risk: list[dict[str, Any]] = []
    if cycles_arg:
        target_ranges, total_book = compute_cycle_targets(holdings, cycles_arg)
        sized_out = open_out + rebalancing_out
        reversal_risk = compute_reversal_risk(
            sized_out, cycles_arg, target_ranges, total_book, hysteresis_pp,
        )
        # Сегодняшний состав не описан ни одним состоянием списка → положение во времени
        # неизвестно, и проверка идёт против ВСЕХ состояний, включая уже пройденные.
        # Это даёт лишние предупреждения (безопасная сторона), но пользователь должен
        # знать, что основание сравнения ненадёжно, а не гадать по числу записей.
        today_config = {item["ticker"] for item in sized_out}
        if not any(set(state.get("open") or {}) == today_config for state in cycles_arg):
            all_warnings.append("cycles_today_state_not_listed")
    sizing["reversal_risk"] = reversal_risk
    sizing["hysteresis_pp"] = hysteresis_pp

    result = {
        "as_of": snapshot.get("as_of_date"),
        "nav_excl_iis": nav,
        "class_plan_rub": class_plan_rub,
        "class_fact_rub": class_fact_rub,
        "base_rub": base_rub,
        "base_pct_nav": base_pct_nav,
        "blocked_gap_rub": blocked_gap_rub,
        "blocked_gap_pp_nav": blocked_gap_pp_nav,
        "gap_gated_rub": sizing.get("gap_gated_rub"),
        "gap_in_corridor_rub": sizing.get("gap_in_corridor_rub"),
        "gap_unallocated_rub": sizing.get("gap_unallocated_rub"),
        "base_trim_rub": sizing.get("base_trim_rub"),
        "base_source": sizing["base_source"],
        "s_open": sizing["s_open"],
        "s_breakdown": sizing["s_breakdown"],
        "classification": {
            "open": open_out,
            "blocked": classification["blocked"],
            "dormant": classification["dormant"],
            "selling": classification["selling"],
            "rebalancing": rebalancing_out,
        },
        "cash_available_for_open": sizing["cash_available_for_open"],
        "cap_breach_after_rounding": post_trade["cap_breach_after_rounding"],
        "structural_cap_offset": post_trade["structural_cap_offset"],
        "money_reconciliation": money_reconciliation,
        "cash_buffer": cash_buffer,
        "target_ranges": target_ranges,
        "reversal_risk": reversal_risk,
        "hysteresis_pp": hysteresis_pp,
        "acted_reversal_iterations": acted_iterations,
        "recent_trade_hints": recent_hints,
        "trim_candidate_hints": trim_hints,
        # §9.3 задаёт путь `concentration.by_issuer` / `concentration.by_sector` — поэтому
        # сюда кладётся ВНУТРЕННИЙ блок результата, а не весь возврат compute_concentration
        # целиком (иначе получалось concentration.concentration.by_issuer, а свои warnings
        # модуля дублировались внутри, хотя они и так подмешаны в общий warnings[]).
        # `l2_cur` поднят рядом — это знаменатель лимитов, и он нужен потребителю явно.
        # None, если --concentration-limits не передан/недоступен (тогда в warnings[] —
        # concentration_check_unavailable).
        "concentration": (concentration_result["concentration"] if concentration_result else None),
        "concentration_l2_cur": (concentration_result["l2_cur"] if concentration_result else None),
        "concentration_blocked_for_open": (
            concentration_result["blocked_for_open"] if concentration_result else None
        ),
        "warnings": all_warnings,
        "_classification_raw": classification,
        "_sizing_raw": sizing,
    }
    return result


# ─────────────────────────── автоматический режим (вьюер, 2026-10-13) ───────────────────────────
# Колонка «Сейчас» в «Долях и целях» вьюера считает «купить/продать N лотов» без решения
# аналитика о том, какие бумаги двигать в этом цикле. Решение аналитика (--open/--trim)
# заменяется детерминированным правилом из той же методологии:
#   Open        — доля ниже МОЕГО плана (planned_share_pct) больше чем на гистерезис и нет
#                 блокировки (gate / pending BUY-условие / pending-условие с продажей или «держать» /
#                 IPO-гейт / user_plan WAIT); слово плана решает, что делать (таблица ниже);
#   Rebalancing — срез до плана (BALANCE, доля выше плана больше чем на гистерезис) или срез
#                 до нуля (SELL);
#   остальное   — автоклассификация (Dormant / Blocked).
# Неразворот (§10.6 п.6): докупка бумаги, проданной < defaults.no_reversal_days назад, и срез купленной — не предлагаются
#   (no_reversal:<дата>), пока нет нового решения или правки плана позже дня сделки.
# Слова плана владельца (user_plan):
#   слово  | недобор больше коридора (нет блокировки)  | перевес больше коридора
#   KEEP   | ничего (dormant, user_plan:KEEP)           | ничего
#   BALANCE| докупка                                    | срез до плана
#   BUY    | докупка                                    | ничего
#   WAIT   | ничего, блокировка с причиной user_plan:WAIT | ничего
#   SELL   | ничего (dormant, user_plan:SELL), покупка запрещена | срез до нуля БЕЗ коридора (и при пустом/нулевом плане)
# Слово плана и база (F — неподвижные деньги по текущим рублям, S — сумма плановых весов торгуемых бумаг,
# base = F/(1−S) с пределом плана класса — одна формула при любом составе F (§10.6 п.2), при пустом F — полный план класса).
# Бумага, которую цикл не торгует, всегда в F своими рублями:
#   KEEP    — в F (операций нет; её реальные рубли ≠ плановый вес × база, поэтому вес в S не кладётся);
#   BALANCE — в S (open/rebalancing); в коридоре без операции — в F;
#   BUY     — в S при недоборе больше коридора (докупка до цели); в коридоре без операции — в F;
#   SELL    — в S с весом 0: срез всей позиции, деньги уходят из класса;
#   WAIT    — вне базы: в F по текущим рублям (blocked);
#   гейты, условия, IPO-гейт, лимит эмитента — в F независимо от слова плана; бумаги в коридоре — в F.
# Инвариант: книга после идеального исполнения = база, доля каждой торгуемой бумаги = её плану.
# Причины блокировки собираются полностью и в стабильном порядке гейт → условия → IPO → план
# (через «; »); unblock_by — по первой причине с датой.
# Цели IE в этом режиме не участвуют: без planned_share_pct тикер — Dormant.
# Лоты — по цене и лоту из СНАПШОТА (current_price, lot_size); у кандидатов на первую покупку (first_buy_candidates) — по quotes@1, иначе по цене IE.
# Правило неразворота ручного режима (--acted), циклы (--cycles), отраслевой лимит — не применяются; у авто-режима свой
# мягкий неразворот по сделкам снапшотов (§10.6 п.6), каскад одним расчётом (п.1) и горизонт известных дат для срезов (п.7).
#
# ЗЕРКАЛО: tools/assets/rebalance-engine.js (runAuto) — тот же расчёт во вьюере.
# Совпадение до рубля/лота проверяет tools/tests/test_rebalance_parity.py — меняешь
# правило здесь, меняй там (тест упадёт, пока не совпадут).
AUTO_TRIM_PLANS = {"BALANCE"}
AUTO_SELL_PLANS = {"SELL"}
HOLD_IN_BASE_PLANS = {"KEEP", "BUY"}   # подпись «держать» (base_weight_pct): без операции, рубли в F, вес в S не кладётся (§10.5)
FIRST_BUY_PLANS = {"BUY", "BALANCE"}   # слова плана, при которых бумага без позиции — кандидат на первую покупку


def first_buy_candidates(snapshot: dict[str, Any], quotes: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Синтетические «позиции» для первой покупки (ЗЕРКАЛО firstBuyCandidates в rebalance-engine.js).

    Кандидат — тикер ie_actual.per_ticker с planned_share_pct > 0 и user_plan BUY/BALANCE, которого нет среди
    активных акций снапшота (замороженные/cost_basis и фонды денежного рынка позицией не считаются; запись
    с qty = 0 идёт обычным путём). Это строка с долей 0 и стоимостью 0: дальше она проходит те же правила, что
    остальные, плюс правило гейта модуля (б): первая покупка без решения — new_position (покупка закрыта до
    первого разбора); остальные блокировки — гейт, условия, IPO-пауза по справочнику бумаг, лимит эмитента — как обычно.
    Цена: живая котировка quotes@1 (price, lot_size), иначе цена IE (ie_model.positions[].current_price_rub,
    лот неизвестен → 1), иначе строка blocked `no_price`.
    """
    per_ticker = (snapshot.get("ie_actual") or {}).get("per_ticker") or {}
    active = {h["ticker"] for h in active_stock_holdings(snapshot)}
    items = (quotes or {}).get("items") or {}
    ie_price = {p.get("ticker"): p.get("current_price_rub")
                for p in ((snapshot.get("ie_model") or {}).get("positions") or []) if isinstance(p, dict)}
    out: list[dict[str, Any]] = []
    for ticker in per_ticker:
        row = per_ticker[ticker] or {}
        plan = row.get("planned_share_pct")
        if ticker in active or ticker in MONEY_MARKET_TICKERS:
            continue
        if not isinstance(plan, (int, float)) or plan <= 0 or row.get("user_plan") not in FIRST_BUY_PLANS:
            continue
        it = items.get(ticker) or {}
        lot = it.get("lot_size")
        if it.get("price"):
            price, source = float(it["price"]), "live"
        elif ie_price.get(ticker):
            price, source = float(ie_price[ticker]), "ie"
        else:
            price, source = None, None
        out.append({
            "ticker": ticker, "asset_type": "stock", "qty": 0, "value_rub": 0.0, "account": "main",
            "current_price": price, "current_price_source": "candidate",
            "lot_size": lot if lot else 1, "lot_known": bool(lot),
            "price_source": source, "first_buy": True,
        })
    return out


_CLASS_CANON = {"кеш": "Кеш", "кэш": "Кеш", "акция": "Акция", "акции": "Акция", "облигация": "Облигация",
                "облигации": "Облигация", "золото": "Золото", "другое": "Другое"}


def _q_cur(v: Any) -> str:
    c = str(v or "RUB").strip().upper()
    return {"SUR": "RUB", "RUR": "RUB"}.get(c, c)


def _q_cell(h: dict[str, Any], fund_classes: dict[str, Any] | None) -> tuple[str, str | None]:
    """Ячейка «валюта × класс» позиции — правило загрузчика (assemble_snapshot.build_class_breakdown): акция —
    (валюта, «Акция»); облигация — корзина плана USD/EUR/CNY → своя валюта, ОФЗ/КОРП → RUB, иначе валюта номинала;
    фонд — plan.funds[T] (класс и валюта), нет записи — (валюта или RUB, None) = строка «не отнесён»."""
    at = h.get("asset_type")
    if at == "stock":
        return _q_cur(h.get("currency")), "Акция"
    if at == "bond":
        b = str(h.get("plan_bucket") or "").strip().upper()
        if b in ("USD", "EUR", "CNY"):
            return b, "Облигация"
        if b in ("ОФЗ", "КОРП"):
            return "RUB", "Облигация"
        return _q_cur(h.get("nominal_currency") or h.get("currency")), "Облигация"
    spec = (fund_classes or {}).get(h.get("ticker"))
    spec = spec if isinstance(spec, dict) else {}
    cls = _CLASS_CANON.get(str(spec.get("class") or "").strip().lower())
    cur = _q_cur(spec.get("currency")) if spec.get("currency") else ""
    return (cur, cls) if cls and cur else (cur or "RUB", None)


def apply_quotes(snapshot: dict[str, Any], quotes: dict[str, Any],
                 fund_classes: dict[str, Any] | None = None) -> dict[str, Any]:
    """Живые цены поверх снапшота → копия снапшота' (quotes@1, план live-prices-plan.md §2.2–§2.3).

    Чистая функция: исходный снапшот не меняется. Цену получают только stock/fund с
    current_price_source == "moex_iss" (cost_basis и implied_from_value не трогаются);
    ИИС-позиции цену получают, но в NAV без ИИС не входят. Тикера нет в quotes →
    остаётся цена снапшота, тикер уходит в live_quotes.missing.
    Облигации (доски TQOB/TQCB): не заблокированная, moex_iss → qty × (цена/100 × номинал × курс + НКД)
    из котировки (поиск по SECID, затем ISIN); курс = 1 для рублёвого номинала, иначе курс ЦБ quotes.fx[face_unit];
    НКД в рублях. Нет в котировках, нет курса для валюты номинала или currency_id не SUR/RUB →
    live_quotes.missing_bonds (в missing не идут); использован курс → live_quotes.fx_date.
    Пересчитываются: value_rub; real_share_pct активной книги (то же множество, что в
    run_auto — active_stock_holdings); строка goals_matrix RUB/Акция (Сейчас/Планы/
    Доля нынешняя/Изменение); total_current_rub_excl_iis и total_current_rub — на ΣΔ main;
    total_current_rub_incl_iis — на ΣΔ всех позиций, iis_balance_rub — на ΣΔ ИИС.
    Факт классов и матрицы валюта × класс (class_plan_vs_fact / matrix_plan_vs_fact, основной счёт без ИИС):
    actual_rub сдвигается на Δ стоимости позиций по правилу загрузчика (_q_cell; фонды — по `fund_classes` =
    plan.funds, без записи — строка «не отнесён»), actual_pct / target_rub / delta_* — от живого NAV без ИИС;
    Σ actual_rub классов = живой NAV, как в снапшоте.
    planned_share_pct, user_plan, ie_* — решения, не цены: не меняются.

    ЗЕРКАЛО: tools/assets/rebalance-engine.js (applyQuotes); совпадение проверяет
    tools/tests/test_rebalance_parity.py — меняешь правило здесь, меняй там.
    """
    snap = copy.deepcopy(snapshot)
    items = (quotes or {}).get("items") or {}
    by_isin = {i["isin"]: i for i in items.values() if isinstance(i, dict) and i.get("isin")}
    applied: list[str] = []
    missing: list[str] = []
    applied_bonds: list[str] = []
    missing_bonds: list[str] = []
    delta_main = delta_iis = 0.0
    cells: dict[tuple[str, str | None], float] = {}

    def _cell_add(h: dict[str, Any], d: float) -> None:
        if h.get("account") == "main" and d:
            k = _q_cell(h, fund_classes)
            cells[k] = cells.get(k, 0.0) + d
    rub_face = ("RUB", "SUR")
    fx = (quotes or {}).get("fx")
    used_fx = False
    for h in snap.get("holdings") or []:
        if isinstance(h, dict) and h.get("asset_type") == "bond":
            # облигации: цена — % номинала; живую получает рублёвая, не заблокированная, с оценкой снапшота
            # по MOEX; валютные остаются по снапшоту молча; нет в котировках → missing_bonds (не missing)
            if h.get("current_price_source") != "moex_iss" or h.get("is_blocked") \
                    or h.get("status") == "blocked" or not h.get("qty"):
                continue
            bi = (items.get(h.get("ticker")) if h.get("ticker") else None) or by_isin.get(h.get("isin") or h.get("ticker"))
            if not isinstance(bi, dict) or bi.get("price") is None:
                missing_bonds.append(h.get("ticker"))
                continue
            if bi.get("currency_id") and bi["currency_id"] not in rub_face:
                missing_bonds.append(h.get("ticker"))
                continue
            ccy = bi.get("face_unit") or h.get("nominal_currency") or "RUB"
            rate = 1.0
            if ccy not in rub_face:
                rate = float(fx.get(ccy) or 0) if isinstance(fx, dict) else 0.0
                if not rate > 0:
                    missing_bonds.append(h.get("ticker"))
                    continue
            face = bi["face_value"] if bi.get("face_value") is not None else h.get("nominal")
            if not (isinstance(face, (int, float)) and face > 0):
                missing_bonds.append(h.get("ticker"))
                continue
            acc = bi["accrued_int"] if bi.get("accrued_int") is not None else (h.get("accrued_int") or 0)
            old = h.get("value_rub") or 0.0
            new = round(h["qty"] * (bi["price"] / 100 * face * rate + acc), 2)
            h["current_price"] = bi["price"]
            h["current_price_source"] = "moex_live"
            h["current_price_ts"] = bi.get("ts")
            h["value_rub"] = new
            h["accrued_int"] = acc
            h["nominal"] = face
            if rate != 1.0:
                used_fx = True
            applied_bonds.append(h.get("ticker"))
            _cell_add(h, new - old)
            if h.get("account") == "main":
                delta_main += new - old
            else:
                delta_iis += new - old
            continue
        if not isinstance(h, dict) or h.get("asset_type") not in ("stock", "fund"):
            continue
        if h.get("current_price_source") != "moex_iss":
            continue
        t = h.get("ticker")
        it = items.get(t) if t else None
        price = it.get("price") if isinstance(it, dict) else None
        if price is None or not h.get("qty"):
            missing.append(t)
            continue
        old = h.get("value_rub") or 0.0
        new = round(h["qty"] * price, 2)
        h["current_price"] = price
        h["current_price_source"] = "moex_live"
        h["current_price_ts"] = it.get("ts")
        h["value_rub"] = new
        if h.get("lot_size") is None and it.get("lot_size") is not None:
            h["lot_size"] = it["lot_size"]
        applied.append(t)
        _cell_add(h, new - old)
        if h.get("account") == "main":
            delta_main += new - old
        else:
            delta_iis += new - old
    snap["live_quotes"] = {
        "fetched_at": (quotes or {}).get("fetched_at"), "stale": bool((quotes or {}).get("stale")),
        "applied": applied, "missing": missing,
        "applied_bonds": applied_bonds, "missing_bonds": missing_bonds,
    }
    if used_fx and isinstance(fx, dict) and fx.get("date"):
        snap["live_quotes"]["fx_date"] = fx["date"]

    # реальные доли — от активной книги после новых цен (знаменатель меняется у всех)
    book = [h for h in active_stock_holdings(snap)]
    book_sum = sum(h.get("value_rub") or 0.0 for h in book)
    per_ticker = (snap.get("ie_actual") or {}).get("per_ticker") or {}
    if book_sum > 0:
        for h in book:
            row = per_ticker.get(h.get("ticker"))
            if isinstance(row, dict) and "real_share_pct" in row:
                row["real_share_pct"] = round((h.get("value_rub") or 0.0) / book_sum * 100, 4)

    bs = snap.get("balance_summary")
    if isinstance(bs, dict):
        def shift(key: str, d: float) -> None:
            if isinstance(bs.get(key), (int, float)):
                bs[key] = round(bs[key] + d, 2)
        nav_old = bs.get("total_current_rub_excl_iis")
        shift("total_current_rub_excl_iis", delta_main)
        shift("total_current_rub", delta_main)
        shift("total_current_rub_incl_iis", delta_main + delta_iis)
        shift("iis_balance_rub", delta_iis)
        nav = bs.get("total_current_rub_excl_iis")
        for row in bs.get("goals_matrix") or []:
            if isinstance(row, dict) and row.get("Валюта") == "RUB" and row.get("Бумага") == "Акция" \
                    and isinstance(nav_old, (int, float)):
                now = round(book_sum, 2)
                row["Сейчас"] = now
                if isinstance(row.get("Доля план"), (int, float)):
                    row["Планы"] = round(row["Доля план"] * nav, 2)
                if nav:
                    row["Доля нынешняя"] = now / nav
                if isinstance(row.get("Планы"), (int, float)):
                    row["Изменение"] = round(row["Планы"] - now, 2)
        if isinstance(nav_old, (int, float)) and isinstance(nav, (int, float)) and (cells or delta_main):
            _shift_class_rows(bs, cells, nav)
    return snap


def _shift_class_rows(bs: dict[str, Any], cells: dict[tuple[str, str | None], float], nav: float) -> None:
    """Сдвиг факта классов и ячеек матрицы на Δ стоимости и пересчёт долей от живого NAV (зеркало shiftClassRows)."""
    def bump(row: dict[str, Any], d: float) -> None:
        a = row.get("actual_rub")
        row["actual_rub"] = round((a if isinstance(a, (int, float)) else 0.0) + d, 2)
        row["actual_pct"] = round(row["actual_rub"] / nav * 100, 4) if nav else None
        tp = row.get("target_pct")
        if isinstance(tp, (int, float)):
            row["target_rub"] = round(tp / 100 * nav, 2)
            row["delta_pp"] = round(tp - row["actual_pct"], 4) if row["actual_pct"] is not None else None
            row["delta_rub"] = round(row["target_rub"] - row["actual_rub"], 2)

    def blank(**kw: Any) -> dict[str, Any]:
        return {**kw, "target_pct": None, "target_rub": None, "actual_rub": 0.0, "actual_pct": None,
                "delta_pp": None, "delta_rub": None}

    by_class: dict[str | None, float] = {}
    for (_cur, cls), d in cells.items():
        name = "Акции" if cls == "Акция" else cls
        by_class[name] = by_class.get(name, 0.0) + d
    rows = bs.get("class_plan_vs_fact")
    if isinstance(rows, list) and rows:
        seen: set[str | None] = set()
        for row in rows:
            if isinstance(row, dict):
                seen.add(row.get("class"))
                bump(row, by_class.get(row.get("class"), 0.0))
        for name, d in by_class.items():
            if name not in seen and d:
                row = blank(**{"class": name})
                bump(row, d)
                rows.append(row)
    mrows = bs.get("matrix_plan_vs_fact")
    if isinstance(mrows, list) and mrows:
        seen_m: set[tuple[str, str | None]] = set()
        for row in mrows:
            if isinstance(row, dict):
                k = (str(row.get("currency") or ""), row.get("class"))
                d = cells.get(k, 0.0) if k not in seen_m else 0.0   # дубль ячейки — сдвиг один раз
                seen_m.add(k)
                bump(row, d)
        for k, d in cells.items():
            if k not in seen_m and d:
                row = blank(currency=k[0], **{"class": k[1]})
                bump(row, d)
                mrows.append(row)


def _plan_funds_near(snapshot_path: str) -> dict[str, Any] | None:
    """plan.funds из Portfolio/plan.json рядом со снапшотом (Portfolio/snapshots/…) — классы фондов для apply_quotes;
    нет файла — None (фонды с живой ценой уходят в «не отнесён»; на базу «Сейчас» это не влияет)."""
    try:
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(snapshot_path))), "plan.json")
        with open(p, encoding="utf-8") as f:
            funds = (json.load(f) or {}).get("funds")
        return funds if isinstance(funds, dict) else None
    except (OSError, ValueError, AttributeError):
        return None


def snapshot_quotes(snapshot: dict[str, Any]) -> dict[str, Any]:
    """{ticker: {last, lot_size}} из holdings снапшота — котировки для compute_lots."""
    out: dict[str, Any] = {}
    for h in snapshot.get("holdings") or []:
        if isinstance(h, dict) and h.get("asset_type") == "stock" and h.get("ticker"):
            out[h["ticker"]] = {"last": h.get("current_price"), "lot_size": h.get("lot_size")}
    return out


SELL_VERDICTS = ("TRIM", "SELL")
HOLD_VERDICTS = ("HOLD", "TRIM", "SELL")


def _cond_active_on(c: dict[str, Any], today: str) -> bool:
    """Условие действует в окне [not_before, valid_until] (включительно; как apply_condition)."""
    nb, vu = c.get("not_before"), c.get("valid_until")
    if nb and today < str(nb)[:10]:
        return False
    if vu and today > str(vu)[:10]:
        return False
    return True


def _auto_stop_condition(ticker: str, ctx: GateContext) -> tuple[str, dict[str, Any]] | None:
    """Автоматический режим: действующее условие (строка модуля (а)), закрывающее докупку без buy-триггера.
    ('sell_condition', c) — verdict_on_trigger ∈ {TRIM, SELL} (продажа по порогу — докупка
    противоречит); ('condition_hold', c) — verdict_now (while_pending) ∈ {HOLD, TRIM, SELL}
    (решение «пока держать»). Условия с on_trigger BUY — это pending_buy_condition
    (_blocking_reasons), здесь не повторяются. Продажа старше «держать». Только действующие (pending или
    fired — «ждёт владельца») и только внутри окна not_before/valid_until."""
    hold: dict[str, Any] | None = None
    for c in ctx.cond_rows(ticker):
        if not _cond_active_on(c, ctx.today):
            continue
        on_verdict = c.get("verdict_on_trigger")
        if on_verdict in SELL_VERDICTS:
            return "sell_condition", c
        if on_verdict != "BUY" and hold is None and c.get("verdict_now") in HOLD_VERDICTS:
            hold = c
    return ("condition_hold", hold) if hold is not None else None


def _no_reversal(ticker: str, action: str, ctx: GateContext) -> dict[str, Any] | None:
    """Неразворот «Сейчас» (§10.6 п.6, мягкий; ЗЕРКАЛО noReversal): докупку бумаги, проданной меньше
    defaults.no_reversal_days дней назад, и срез бумаги, купленной меньше этого срока назад, не предлагаем. Сделка —
    по истории снапшотов (last_sell_at / last_buy_at, день снапшота). Снимает событие ПОЗЖЕ дня сделки: новое решение
    по ключу (любой источник) или правка плана бумаги (plan_changed_at — user_plan / доля плана в журнале плана);
    событие в день сделки не снимает (порядок внутри дня неизвестен, решение, по которому сделка, — обычно того же
    дня). Цена запрет не снимает. → {until, trade: sell|buy, trade_at} или None."""
    trade = "sell" if action == "buy" else "buy"
    at = (ctx.last_sell_at if trade == "sell" else ctx.last_buy_at).get(ticker)
    if not at:
        return None
    day = str(at)[:10]
    until = lw.add_days(day, NO_REVERSAL_DAYS)
    if not ctx.today < until:
        return None
    if any(d.get("key") == ticker and str(d.get("recorded_at") or "")[:10] > day for d in ctx.decisions):
        return None
    pc = ctx.plan_changed_at.get(ticker)
    if pc and str(pc)[:10] > day:
        return None
    return {"until": until, "trade": trade, "trade_at": day}


def _cond_lift(c: dict[str, Any], price: float | None) -> tuple[str, bool] | None:
    """Известная дата снятия условия (горизонт §10.6 п.7; ЗЕРКАЛО condLift): ожидающее условие с триггером «дата» —
    его дата; ценовой триггер с датой начала окна (not_before) — эта дата, если текущая цена уже за порогом
    («если цена удержится»). Отчёт/событие, цена без даты, сработавшее (ждёт владельца) — None."""
    if c.get("status") != cm.PENDING:
        return None
    t = c.get("trigger") or {}
    tt, v = t.get("type"), t.get("value")
    if tt == "date" and v:
        return str(v)[:10], False
    nb = c.get("not_before")
    if tt in ("price_above", "price_below") and nb and v is not None and price:
        if (tt == "price_above" and price >= float(v)) or (tt == "price_below" and price <= float(v)):
            return str(nb)[:10], True
    return None


def _known_open_date(h: dict[str, Any], row: dict[str, Any], ctx: GateContext) -> tuple[str, bool] | None:
    """Горизонт известных дат (§10.6 п.7; ЗЕРКАЛО knownOpenDate): блокировка докупки снимается в известную дату
    d ≤ today + defaults.known_dates_horizon_days И на дату d вся картина гейта даёт открытую докупку → (d, «если цена
    удержится»). Снимаемые сегодня причины: пауза докупки, IPO-пауза, условия с известной датой (_cond_lift). Проверка
    на d: гейт модуля (б) с today = d без причин (истёк срок решения, «наблюдать», нет решения, другая пауза —
    не открыта), а каждое условие, действующее на d (окно not_before/valid_until), снимается не позже d.
    Не снимаемые: гейт сегодня, слово плана, нет цены. Иначе None."""
    g = ctx.card(h["ticker"])["gate"]
    price = h.get("current_price")
    dates: list[str] = []
    for r in _blocking_reasons(h, row, ctx):
        if r.startswith("ipo_gate:") and g["ipo_pause_until"]:
            dates.append(str(g["ipo_pause_until"]))
        elif r.startswith("add_cooldown:") and g["add_cooldown_until"]:
            dates.append(str(g["add_cooldown_until"]))
        elif r != "pending_buy_condition":
            return None

    def blocking_conds(day: str) -> list[dict[str, Any]]:
        out = []
        for c in ctx.cond_rows(h["ticker"]):
            if c.get("verdict_on_trigger") == "BUY":
                out.append(c)
            elif _cond_active_on(c, day) and (c.get("verdict_on_trigger") in SELL_VERDICTS
                                              or c.get("verdict_now") in HOLD_VERDICTS):
                out.append(c)
        return out

    cond_price = False
    for c in blocking_conds(ctx.today):
        lift = _cond_lift(c, price)
        if lift is None:
            return None
        dates.append(lift[0])
        cond_price = cond_price or lift[1]
    if not dates:
        return None
    d = max(dates)
    if not (ctx.today < d <= lw.add_days(ctx.today, HORIZON_DAYS)):
        return None
    # на дату снятия — вся картина гейта
    if ctx.card_on(h["ticker"], d)["gate"]["reasons"]:
        return None
    for c in blocking_conds(d):
        lift = _cond_lift(c, price)
        if lift is None or lift[0] > d:
            return None
        cond_price = cond_price or lift[1]
    return d, cond_price


def auto_cycle_flags(
    snapshot: dict[str, Any],
    gate_inputs: dict[str, Any] | None,
    conditions: dict[str, Any] | None,
    hysteresis_pp: float = _DEFAULT_HYSTERESIS_PP,
    today: str | None = None,
    ai_mode: str = "on",
    shares: dict[str, float] | None = None,
    ctx: GateContext | None = None,
) -> tuple[dict[str, float], dict[str, float], dict[str, dict[str, Any]], dict[str, float]]:
    """(open {ticker: plan_pct}, trim {ticker: plan_pct}, notes, hold {ticker: plan_pct}) по правилу автоматического режима.
    Докупка — недобор > гистерезиса и ни гейт/IPO/user_plan/buy-условие, ни pending-условие
    с продажей или «держать», ни неразворот (§10.6 п.6) не закрывают её. notes {ticker: {category, reason,
    unblock_by[, no_reversal][, opens_on, if_price_holds, horizon_weight]}} — для бумаг без операции по новым правилам
    (в строки результата); opens_on — горизонт известных дат (§10.6 п.7). `shares` {ticker: %} — доли от книги
    после исполнения предыдущего прохода каскада (§10.6 п.1); None — real_share_pct снапшота. hold — подпись
    «держать» (без операции, рубли в F)."""
    per_ticker = (snapshot.get("ie_actual") or {}).get("per_ticker") or {}
    ctx = ctx or GateContext(snapshot, gate_inputs, conditions, today, ai_mode)
    open_w: dict[str, float] = {}
    trim_w: dict[str, float] = {}
    notes: dict[str, dict[str, Any]] = {}
    hold_w: dict[str, float] = {}
    for h in active_stock_holdings(snapshot):
        ticker = h["ticker"]
        row = per_ticker.get(ticker) or {}
        real, plan = row.get("real_share_pct"), row.get("planned_share_pct")
        if shares is not None and real is not None and ticker in shares:
            real = shares[ticker]
        # подпись «держать» / «докупать» без блокировок (рубли — в F, вес в S не кладётся)
        if row.get("user_plan") in HOLD_IN_BASE_PLANS and plan is not None and real is not None \
                and not _blocking_reasons(h, row, ctx) \
                and _auto_stop_condition(ticker, ctx) is None:
            hold_w[ticker] = float(plan)
        is_sell = row.get("user_plan") in AUTO_SELL_PLANS
        if real is None or (plan is None and not is_sell):
            continue
        # SELL: вся позиция на продажу — независимо от доли, коридора, гейтов и условий (3.94, владелец 28.10)
        if is_sell and float(real) > 0:
            nr = _no_reversal(ticker, "trim", ctx)
            if nr is not None:
                notes[ticker] = {"category": "dormant", "reason": f"no_reversal:{nr['until']}",
                                 "unblock_by": nr["until"], "no_reversal": nr}
            else:
                trim_w[ticker] = 0.0
            continue
        if plan is None:   # «продать» без плановой доли и без позиции (после среза каскада) — операции нет
            continue
        gap = float(real) - float(plan)
        if gap < 0:
            reasons = _blocking_reasons(h, row, ctx)
            stop = _auto_stop_condition(ticker, ctx)
            if reasons or stop is not None:
                notes[ticker] = {"category": "blocked",
                                 "reason": "; ".join(_merge_stop_reason(reasons, stop)),
                                 "unblock_by": _unblock_by(h, row, ctx, stop)}
                if -gap > hysteresis_pp and row.get("user_plan") not in NO_BUY_DORMANT_PLANS:
                    ko = _known_open_date(h, row, ctx)
                    if ko is not None:
                        notes[ticker].update(opens_on=ko[0], if_price_holds=ko[1], horizon_weight=float(plan))
            elif row.get("user_plan") in NO_BUY_DORMANT_PLANS:
                notes[ticker] = {"category": "dormant", "reason": f"user_plan:{row.get('user_plan')}",
                                 "unblock_by": None}
            elif -gap > hysteresis_pp:
                nr = _no_reversal(ticker, "buy", ctx)
                if nr is not None:
                    notes[ticker] = {"category": "blocked", "reason": f"no_reversal:{nr['until']}",
                                     "unblock_by": nr["until"], "no_reversal": nr}
                else:
                    open_w[ticker] = float(plan)
            else:
                notes[ticker] = {"category": "dormant", "reason": f"below_hysteresis:{-gap:.2f}pp",
                                 "unblock_by": None}
        elif gap > hysteresis_pp and row.get("user_plan") in AUTO_TRIM_PLANS:
            nr = _no_reversal(ticker, "trim", ctx)
            if nr is not None:
                notes[ticker] = {"category": "dormant", "reason": f"no_reversal:{nr['until']}",
                                 "unblock_by": nr["until"], "no_reversal": nr}
            else:
                trim_w[ticker] = float(plan)
    for t in list(hold_w):
        if t in open_w or t in trim_w:
            del hold_w[t]
    return open_w, trim_w, notes, hold_w


def _auto_pass(
    snapshot: dict[str, Any], gate_inputs: dict[str, Any] | None, conditions: dict[str, Any] | None,
    limits_config: dict[str, Any] | None, hysteresis_pp: float, today: str | None, ai_mode: str,
    ctx: GateContext, shares: dict[str, float] | None, sticky_open: dict[str, float], sticky_trim: dict[str, float],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Один проход авто-режима: классификация (доли — снапшота или после исполнения прошлого прохода) ∪ бумаги,
    уже торгуемые каскадом (sticky: их доля после исполнения = план, коридор их не выбрасывает) → run_sizing.
    Доли прохода (`shares`) подставляются в real_share_pct копии снапшота — их видит и классификация run_sizing."""
    if shares is not None:
        snapshot = dict(snapshot)
        ie_actual = dict(snapshot.get("ie_actual") or {})
        pt = {t: (dict(r, real_share_pct=shares[t]) if isinstance(r, dict) and t in shares
                  and r.get("real_share_pct") is not None else r)
              for t, r in (ie_actual.get("per_ticker") or {}).items()}
        ie_actual["per_ticker"] = pt
        snapshot["ie_actual"] = ie_actual
    open_w, trim_w, notes, hold_w = auto_cycle_flags(snapshot, gate_inputs, conditions, hysteresis_pp, today, ai_mode,
                                                     ctx=ctx)
    for t, w in sticky_trim.items():
        trim_w[t] = w
        open_w.pop(t, None)
        notes.pop(t, None)
        hold_w.pop(t, None)
    for t, w in sticky_open.items():
        if t not in trim_w:
            open_w[t] = w
            notes.pop(t, None)
            hold_w.pop(t, None)
    # закрытые условием или неразворотом — Blocked (их недобор не уходит в докупку других), как прочие блокировки
    blocked_by_cond = [t for t, n in notes.items() if n["category"] == "blocked"]
    horizon = {t: n["horizon_weight"] for t, n in notes.items() if n.get("opens_on")}
    fmt = lambda d: ",".join(f"{t}={w!r}" for t, w in sorted(d.items())) or None  # noqa: E731
    while True:
        r = run_sizing(
            snapshot=snapshot, gate_inputs=gate_inputs, conditions=conditions,
            open_arg=fmt(open_w), selling_arg=None, blocked_arg=",".join(sorted(blocked_by_cond)) or None,
            extra_cash_from_sales=0.0, quotes=snapshot_quotes(snapshot), yaml_warnings=[],
            trim_arg=fmt(trim_w), hysteresis_pp=hysteresis_pp, hold_weights=hold_w,
            limits_config=limits_config, concentration_today=snapshot.get("as_of_date"),
            today=today, ai_mode=ai_mode, horizon=horizon,
        )
        # докупаемая бумага с целью ниже текущей (база меньше её рублей / доли) не торгуется — в F своими рублями,
        # иначе книга после исполнения ≠ база (§10.6 п.1); перевод в F только поднимает базу, проход конечен
        tg = r["_sizing_raw"]["targets"]
        drop = [x["ticker"] for x in r["_classification_raw"]["open"]
                if r["base_rub"] is not None and tg.get(x["ticker"]) is not None
                and tg[x["ticker"]] - x["current_rub"] < -_DIRECTION_EPS]
        if not drop:
            return r, notes
        for t in drop:
            open_w.pop(t, None)


def run_auto(
    snapshot: dict[str, Any],
    gate_inputs: dict[str, Any] | None,
    conditions: dict[str, Any] | None,
    limits_config: dict[str, Any] | None,
    hysteresis_pp: float = _DEFAULT_HYSTERESIS_PP,
    quotes: dict[str, Any] | None = None,
    today: str | None = None,
    ai_mode: str = "on",
) -> dict[str, Any]:
    """Автоматический режим → компактный канонический результат (его же отдаёт JS-зеркало).

    Порог `hysteresis_pp` — и для среза, и для докупки (2026-10-26: «Сейчас» предлагал докупки по
    0,1–0,4 п.п.). Pending-условие с продажей (`sell_condition`) или «держать» (`condition_hold`) в
    своём окне закрывает докупку бумаги: RENI «без добора до 30.11», NVTK у порога продажи 1 200 ₽.

    Каскад за один расчёт (§10.6 п.1): посчитать сделки → идеально исполнить в модели → доли от книги после
    исполнения → переклассифицировать (вне коридора: срез при «привести к плану», докупка, если открыта) → снова,
    пока набор торгуемых бумаг не перестанет меняться. Бумага, раз попавшая в сделки, в них остаётся (после
    исполнения она на плане). Предел — число бумаг + 1 проход; повтор уже бывшего набора (колебание) или предел →
    результат первого прохода и `cascade.converged = false` (сайт показывает предупреждение). «Держать», «ждать»,
    заблокированные — не торгуются, как и без каскада."""
    # первая покупка: бумаги плана BUY/BALANCE без позиции — строки с долей 0 (first_buy_candidates);
    # `quotes` (quotes@1) нужны только для их цены/лота: у позиций цены берутся из снапшота
    cands = first_buy_candidates(snapshot, quotes)
    cand_by = {c["ticker"]: c for c in cands}
    if cands:
        snapshot = dict(snapshot)
        snapshot["holdings"] = list(snapshot.get("holdings") or []) + cands
        ie_actual = dict(snapshot.get("ie_actual") or {})
        pt0 = dict(ie_actual.get("per_ticker") or {})
        for c in cands:
            pt0[c["ticker"]] = dict(pt0[c["ticker"]], real_share_pct=0.0)
        ie_actual["per_ticker"] = pt0
        snapshot["ie_actual"] = ie_actual
    gctx = GateContext(snapshot, gate_inputs, conditions, today, ai_mode)
    holdings_now = active_stock_holdings(snapshot)

    def movers(rr: dict[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...]]:
        c = rr["_classification_raw"]
        return tuple(sorted(x["ticker"] for x in c["open"])), tuple(sorted(x["ticker"] for x in c["rebalancing"]))

    limit = len(holdings_now) + 1
    sticky_open: dict[str, float] = {}
    sticky_trim: dict[str, float] = {}
    shares = None
    first = None
    prev_key = None
    seen: set = set()
    converged = False
    iterations = 0
    r = notes = None
    while iterations < limit:
        iterations += 1
        r, notes = _auto_pass(snapshot, gate_inputs, conditions, limits_config, hysteresis_pp, today, ai_mode,
                              gctx, shares, sticky_open, sticky_trim)
        if first is None:
            first = (r, notes)
        key = movers(r)
        if key == prev_key or (prev_key is None and r["base_rub"] is None):
            converged = True
            break
        if key in seen or r["base_rub"] is None:
            break
        seen.add(key)
        prev_key = key
        cls_k = r["_classification_raw"]
        sticky_open = {x["ticker"]: x["weight_pct"] for x in cls_k["open"]}
        sticky_trim = {x["ticker"]: x["weight_pct"] for x in cls_k["rebalancing"]}
        tg = r["_sizing_raw"]["targets"]
        post: dict[str, float] = {}
        for cat in ("open", "rebalancing", "blocked", "dormant", "selling"):
            for x in cls_k.get(cat, []):
                cur = x["current_rub"]
                t = tg.get(x["ticker"]) if cat in ("open", "rebalancing") else None
                d = _direction_for(cat, (t - cur) if t is not None else None)
                post[x["ticker"]] = t if d in ("buy", "trim") else cur
        book = sum(post.values())
        if book <= 0:
            break
        shares = {t: round(v / book * 100, 4) for t, v in post.items()}
    if converged and iterations > 2:
        # итоговый набор сделок — от книги СЕЙЧАС: неторгуемые бумаги классифицируются по своим сегодняшним долям
        # (подписи), торгуемые — весь набор каскада
        c = r["_classification_raw"]
        r, notes = _auto_pass(snapshot, gate_inputs, conditions, limits_config, hysteresis_pp, today, ai_mode, gctx, None,
                              {x["ticker"]: x["weight_pct"] for x in c["open"]},
                              {x["ticker"]: x["weight_pct"] for x in c["rebalancing"]})
    elif not converged or iterations <= 2:
        r, notes = first
    added = sorted(set(sum(movers(r), ())) - set(sum(movers(first[0]), ())))

    per_ticker = (snapshot.get("ie_actual") or {}).get("per_ticker") or {}
    cls = r["_classification_raw"]
    targets = r["_sizing_raw"]["targets"]
    hold_by = {h["ticker"]: h for h in holdings_now}
    quotes = snapshot_quotes(snapshot)
    horizon_set = set(r["_sizing_raw"].get("horizon") or [])

    def frozen_reason(item: dict[str, Any], cat: str, pt_row: dict[str, Any]) -> str | None:
        # зеркало frozenReason во вьюере: блокировка/заметка, иначе причины, держащие бумагу вне «держать в базе» при перевесе
        if not (cat == "blocked" or (cat == "dormant" and "base_weight_pct" not in item)):
            return None
        t = item["ticker"]
        if t in notes and notes[t].get("reason"):
            return notes[t]["reason"]
        if item.get("reason"):
            return item["reason"]
        hd = hold_by.get(t)
        if hd is None:
            return None
        rs = _merge_stop_reason(_blocking_reasons(hd, pt_row, gctx), _auto_stop_condition(t, gctx))
        return "; ".join(rs) if rs else None

    rows: list[dict[str, Any]] = []
    for cat in ("open", "rebalancing", "blocked", "dormant"):
        for item in cls[cat]:
            t = item["ticker"]
            pt = per_ticker.get(t) or {}
            target = targets.get(t) if cat in ("open", "rebalancing") and r["base_rub"] is not None else None
            delta = (target - item["current_rub"]) if target is not None else None
            direction = _direction_for(cat, delta) if delta is not None else None
            lots = price = None
            if direction in ("buy", "trim"):
                lots, _rem, price = compute_lots(delta, quotes.get(t))
                if lots is not None and t in cand_by and not cand_by[t]["lot_known"]:
                    lots = None  # первая покупка с неизвестным лотом: лоты не считаем, только сумма
            q = quotes.get(t) or {}
            n = notes.get(t) or {}
            rows.append({
                "ticker": t, "category": cat,
                "real_pct": pt.get("real_share_pct"), "plan_pct": pt.get("planned_share_pct"),
                "user_plan": pt.get("user_plan"),
                "current_rub": round(item["current_rub"], 2),
                "target_rub": round(target, 2) if target is not None else None,
                "delta_rub": round(delta, 2) if delta is not None else None,
                "direction": direction, "lots": lots,
                "lot_size": q.get("lot_size"), "price": price,
                "trade_rub": round(lots * price * q["lot_size"], 2) if lots is not None else None,
                "reason": (n["reason"] if t in notes else item.get("reason")),
                # PyYAML отдаёт даты объектами date — наружу строкой, как в JS-зеркале
                "unblock_by": (n["unblock_by"] if t in notes
                               else str(item["unblock_by"]) if item.get("unblock_by") is not None else None),
                "frozen": cat == "blocked" or (cat == "dormant" and "base_weight_pct" not in item),
                "frozen_reason": frozen_reason(item, cat, pt),
                "first_buy": t in cand_by,
                "price_source": cand_by[t]["price_source"] if t in cand_by else None,
                "lot_known": cand_by[t]["lot_known"] if t in cand_by else None,
                # §10.6: неразворот {until, trade, trade_at}; «откроется» (горизонт известных дат) — дата и оговорка цены;
                # cascade — бумага попала в сделки после сдвига долей от других сделок
                "no_reversal": n.get("no_reversal"),
                "opens_on": n.get("opens_on") if t in horizon_set else None,
                "opens_if_price_holds": bool(n.get("if_price_holds")) if t in horizon_set else None,
                "cascade": t in added,
            })
    rows.sort(key=lambda x: x["ticker"])
    buy = sum(x["trade_rub"] for x in rows if x["direction"] == "buy" and x["trade_rub"] is not None)
    sell = sum(x["trade_rub"] for x in rows if x["direction"] == "trim" and x["trade_rub"] is not None)
    rnd = lambda x: round(x, 2) if x is not None else None  # noqa: E731
    return {
        "mode": "auto", "as_of": snapshot.get("as_of_date"), "hysteresis_pp": hysteresis_pp,
        "nav_excl_iis": r["nav_excl_iis"], "class_plan_rub": r["class_plan_rub"],
        "class_fact_rub": r["class_fact_rub"],
        "base_rub": rnd(r["base_rub"]),
        "base_source": r["base_source"],
        "base_trim_rub": rnd(r.get("base_trim_rub")),
        "horizon": sorted(horizon_set),
        "blocked_gap_rub": rnd(r["blocked_gap_rub"]),
        "gap_gated_rub": rnd(r.get("gap_gated_rub")),
        "gap_in_corridor_rub": rnd(r.get("gap_in_corridor_rub")),
        "gap_unallocated_rub": rnd(r.get("gap_unallocated_rub")),
        "buy_rub": round(buy, 2), "sell_rub": round(sell, 2),
        "cascade": {"iterations": iterations, "converged": converged, "added": added},
        "rows": rows,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Gate-aware сайзинг докупки акций (неподвижная точка).")
    ap.add_argument("--snapshot", required=True, help="Путь к portfolio-<date>.json")
    ap.add_argument("--decisions", metavar="DIR", help="Папка решений Portfolio/decisions (decision@1) — гейт модулем (б)")
    ap.add_argument("--security-attrs", metavar="FILE",
                    help="Справочник бумаг Portfolio/security-attrs.json (security-attrs@1) — IPO-пауза")
    ap.add_argument("--reviews", metavar="FILE", action="append",
                    help="YAML обзора акций недели (weekly-review-stock-*.yaml); можно несколько — строки бумаг для "
                         "модуля (б): флаг gate_review_required обзора новее решения даёт review_needed")
    ap.add_argument("--conditions", metavar="FILE", help="Определения условий Portfolio/conditions.yaml (conditions@2)")
    ap.add_argument("--conditions-state", metavar="FILE",
                    help="Состояние условий Portfolio/conditions-state.json (conditions-state@1); без него — событий нет")
    ap.add_argument("--today", metavar="YYYY-MM-DD",
                    help="Дата гейта и условий (сроки решений, паузы, окна условий); по умолчанию as_of_date снапшота")
    ap.add_argument("--ai-mode", choices=("on", "off"), default="on",
                    help="Режим сайта (по умолчанию on). off блокирует теми же статусами, что on, но решение владельца "
                         "снимает блок как любое (правило 9а при off не действует)")
    ap.add_argument("--open", help="TICKER[=weight_pct][,...] — открытые к докупке в этом цикле")
    ap.add_argument("--selling", help="TICKER[,...] — на продажу/сокращение (вне F и S)")
    ap.add_argument(
        "--trim", help="TICKER[=weight_pct][,...] — срез до плановой/явной доли (вне F, но в S); "
        "без веса берётся planned_share_pct, как для --open"
    )
    ap.add_argument("--blocked", help="TICKER[,...] — ручное дополнение автоклассификации Blocked")
    ap.add_argument(
        "--acted", help="TICKER=buy|trim[,...] — правило неразворота (§10.3): направление "
        "уже исполненной в этом горизонте сделки. Направление ОБЯЗАТЕЛЬНО; движение в ту "
        "же сторону разрешено, подавляется только разворот. --selling признаку не подчиняется."
    )
    ap.add_argument(
        "--cycles", metavar="FILE",
        help="JSON-список обозримых состояний цикла для проверки диапазона цели и флага "
        "разворота (B1/B2): [{\"label\": \"C1\", \"open\": {\"SBERP\": 8.0}}, ...]"
    )
    ap.add_argument(
        "--hysteresis-pp", type=float, default=_DEFAULT_HYSTERESIS_PP,
        help=f"Гистерезис (пп акционной книги) для флага разворота B2, по умолчанию "
        f"{_DEFAULT_HYSTERESIS_PP} (Rule 3) — параметр, не константа; в --auto — порог среза и докупки"
    )
    ap.add_argument(
        "--concentration-limits", metavar="FILE",
        help="Конфиг лимитов концентрации (§9/§11 spec-gate-aware-sizing-trim-fix.md); "
        f"по умолчанию {_DEFAULT_CONCENTRATION_LIMITS_PATH!r}. Знаменатель — фактическая "
        "книга (L2_cur), не база докупки. Отказ загрузки (файл/PyYAML/данные снапшота) "
        "не прерывает сайзинг — деградация с warning'ом concentration_check_unavailable."
    )
    ap.add_argument(
        "--sector", action="store_true",
        help="Включить секторный лимит концентрации (выключен по умолчанию — гейт на "
        "sector=null coverage, см. concentration_limits.py)"
    )
    ap.add_argument(
        "--concentration-today", metavar="YYYY-MM-DD",
        help="Дата для проверки истечения именованных исключений лимитов концентрации; "
        "по умолчанию — реальная дата"
    )
    ap.add_argument("--quotes", help="Путь к JSON-выходу moex_quotes.py --json (для лотов). С --auto — quotes@1 "
                    "(moex_quotes.py --emit quotes@1): живые цены применяются поверх снапшота до расчёта (apply_quotes)")
    ap.add_argument("--extra-cash-from-sales", type=float, default=0.0)
    ap.add_argument("--cash-buffer-pct", type=float, default=_CASH_BUFFER_PCT_DEFAULT,
                    help="Целевой буфер кэша, %% NAV (правило кэша методологии; default 4.0)")
    ap.add_argument("--json", action="store_true", help="Только JSON-блок")
    ap.add_argument("--text", action="store_true", help="Только текстовый report_block")
    ap.add_argument("--lint-draft", metavar="FILE", help="Режим линта черновика ответа (запрещённая нотация, сумма докупки акции без базы); числа сделок против вывода скриптов — lint_numbers.py")
    ap.add_argument("--auto", action="store_true",
                    help="Автоматический режим (колонка «Сейчас» вьюера): Open/срез по правилу от МОЕГО "
                         "плана и гистерезиса, лоты по цене снапшота; --open/--trim/--acted игнорируются; "
                         "печатает компактный JSON (зеркало — tools/assets/rebalance-engine.js)")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_arg_parser()
    args = ap.parse_args(argv)

    try:
        snapshot = load_snapshot(args.snapshot)
    except GateAwareSizingError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2

    live = None
    if args.auto and args.quotes:
        # живые цены quotes@1 поверх снапшота ДО расчёта; без --quotes — цены снапшота
        try:
            with open(args.quotes, encoding="utf-8") as f:
                live = json.load(f) or {}
        except (OSError, ValueError) as exc:
            print(f"Ошибка: не удалось прочитать котировки {args.quotes!r}: {exc}", file=sys.stderr)
            return 2
        if live.get("schema") != "quotes@1":
            print(f"Ошибка: {args.quotes!r} — не quotes@1 (для --auto нужен moex_quotes.py --emit quotes@1)",
                  file=sys.stderr)
            return 2
        snapshot = apply_quotes(snapshot, live, _plan_funds_near(args.snapshot))

    if args.lint_draft:
        try:
            with open(args.lint_draft, encoding="utf-8") as f:
                draft_text = f.read()
        except OSError as exc:
            print(f"Ошибка: не удалось прочитать черновик {args.lint_draft!r}: {exc}", file=sys.stderr)
            return 2
        stock_tickers = all_stock_tickers(snapshot)
        violations = lint_draft(draft_text, stock_tickers)
        if not violations:
            print("Линт чист.")
            return 0
        for line_no, message in violations:
            print(f"{line_no}: {message}")
        return 1

    if args.hysteresis_pp < 0:
        print("Ошибка: --hysteresis-pp не может быть отрицательным", file=sys.stderr)
        return 2

    try:
        gate_inputs, gr_warnings = load_gate_inputs(args.decisions, args.security_attrs, args.reviews)
        if gate_inputs is not None:
            gate_inputs.update(load_trade_inputs(args.snapshot, snapshot.get("as_of_date")))
        conditions, cond_warnings = load_conditions_inputs(args.conditions, args.conditions_state)
        quotes_payload = None
        if args.quotes:
            if not os.path.exists(args.quotes):
                raise GateAwareSizingError(f"Файл котировок не найден: {args.quotes!r}")
            with open(args.quotes, encoding="utf-8") as f:
                quotes_payload = (json.load(f) or {}).get("quotes") or {}
        cycles_data = load_cycles_file(args.cycles)

        # §9/§11 «Волна 3» — конфиг лимитов концентрации грузится ЗДЕСЬ (main/CLI), не
        # внутри run_sizing: run_sizing принимает уже загруженный dict (как gate_inputs/
        # conditions), поэтому существующие вызовы run_sizing() из тестов, не знающие о
        # концентрации, не задеты. Отказ загрузки — деградация с warning'ом, НЕ exit 2:
        # это риск-надстройка над уже рабочим сайзингом, её недоступность не должна
        # блокировать весь разбор (см. отчёт по правке волны 3).
        limits_config = None
        concentration_yaml_warnings: list[str] = []
        limits_path = args.concentration_limits or _DEFAULT_CONCENTRATION_LIMITS_PATH
        if not os.path.exists(limits_path):
            concentration_yaml_warnings.append(
                f"concentration_check_unavailable:конфиг не найден: {limits_path!r}"
            )
        else:
            try:
                limits_config = load_limits_config(limits_path)
            except ConcentrationLimitsError as exc:
                concentration_yaml_warnings.append(f"concentration_check_unavailable:{exc}")

        result = run_sizing(
            snapshot=snapshot, gate_inputs=gate_inputs, conditions=conditions,
            open_arg=args.open, selling_arg=args.selling, blocked_arg=args.blocked,
            extra_cash_from_sales=args.extra_cash_from_sales, quotes=quotes_payload,
            yaml_warnings=gr_warnings + cond_warnings + concentration_yaml_warnings,
            trim_arg=args.trim,
            acted_arg=args.acted, cycles_arg=cycles_data, hysteresis_pp=args.hysteresis_pp,
            limits_config=limits_config, sector_enabled=args.sector,
            concentration_today=args.concentration_today,
            cash_buffer_pct=args.cash_buffer_pct, today=args.today, ai_mode=args.ai_mode,
        )
    except GateAwareSizingError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2

    show_json = args.json or not (args.json or args.text)
    show_text = args.text or not (args.json or args.text)

    if args.auto:
        try:
            auto = run_auto(snapshot, gate_inputs, conditions, limits_config, args.hysteresis_pp, quotes=live,
                            today=args.today, ai_mode=args.ai_mode)
        except GateAwareSizingError as exc:
            print(f"Ошибка: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(auto, ensure_ascii=False, indent=2, default=str))
        return 0

    if show_json:
        json_out = {k: v for k, v in result.items() if not k.startswith("_")}
        print(json.dumps(json_out, ensure_ascii=False, indent=2, default=str))
    if show_json and show_text:
        print()
    if show_text:
        report = build_report_block(
            as_of=result["as_of"], nav=result["nav_excl_iis"],
            class_plan_rub=result["class_plan_rub"], class_fact_rub=result["class_fact_rub"],
            classification=result["_classification_raw"], sizing=result["_sizing_raw"],
            quotes=quotes_payload,
        )
        print(report)

    return 0


if __name__ == "__main__":
    sys.exit(main())
